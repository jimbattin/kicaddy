"""Session daemon behind the omp extension: one warm KiCad `api-server` per omp session.

Protocol: one JSON object per line. Request {"id", "op", ...}; response {"id", "ok", "output", "images", "state"}
(plus "fingerprint" for `status`). Ops: status, open, build, query, render, edit, shutdown. The daemon exits on
stdin EOF (omp gone), SIGTERM, SIGHUP, or `shutdown`, and stops its server on the way out.

An edit batch runs builder calls on the open project, built this session or opened, in two commits: the batch
code runs inside the first, which holds the symbol placements (PlaceSymbolFromLibrary); the second sends the field
updates, the changed and deleted items, and the new items (a symbol placed inside an open commit does not exist
for UpdateItems until that commit ends). An exception in the code drops the first; a failure in the second drops
it and deletes the placed symbols. The model is loaded from the document before and after each batch; the netlist
difference is reported, and when the batch declares `expect` (required for opened projects) a difference from it
drops the batch and reopens the saved files. A project whose root sheet was saved by another KiCad release opens
for query and render; `edit` is refused until `open` is sent with `upgrade`, because a save rewrites every sheet
in the running release's file format.
"""

import builtins
import contextlib
import hashlib
import io
import json
import linecache
import os
import re
import runpy
import signal
import sys
import traceback
from pathlib import Path

from . import bootstrap, netdiff, runtime, schematic

NO_DOCUMENT = "no document: call kicaddy_build or kicaddy_open first"
NO_EXPECT = ("kicaddy_edit on a project opened with kicaddy_open needs expect: the netlist change the batch makes "
             "({} for none)")
NEEDS_UPGRADE = ("this project is in the file format of {saved}; a save rewrites every sheet in that of KiCad "
                 "{ours}, which {saved} cannot open. Reopen with upgrade: true when the user has agreed")
GRID_NM = schematic.GRID_MM * 1e6


class OpError(Exception):
    """An expected failure: the message is the op's whole output."""


class _Stop(BaseException):
    """SIGTERM or SIGHUP. Not SystemExit, which op_build takes as the design script's own exit."""


def _stop(*_):
    raise _Stop


def _trace(first):
    """The traceback of the exception being handled, from the first frame in file `first` (the design script,
    or "<batch>") on: the daemon and runpy frames above it say nothing about the design. Code that does not
    compile has no such frame, and its SyntaxError names the line."""
    kind, error, tb = sys.exc_info()
    start = tb
    while start is not None and start.tb_frame.f_code.co_filename != first:
        start = start.tb_next
    if start is None and not isinstance(error, SyntaxError):
        start = tb
    return "".join(traceback.format_exception(kind, error, start))


def _capture(fn, *args):
    """(result, printed text) of fn(*args)."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        result = fn(*args)
    return result, buf.getvalue()


class Session:
    def __init__(self, current):
        self.current = current
        self.stack = None  # ExitStack holding runtime.server()
        self.api = None
        self.directory = None  # the server's project directory
        self.project = None  # schematic.Project: built this session (run() adopts it) or opened
        self.built = False  # the project was built this session by kicaddy_build
        self.batches = 0
        self.foreign = None  # (format version, "KiCad 10.0", "10.99"): the opened root was saved by another release
        self.upgrade = False  # kicaddy_open was told that a save may rewrite such a project
        # The plot jobs draw the files as they were at the first plot after the document was opened, whatever
        # was committed and saved since (docs/02-ipc-protocol.md#export-jobs): reopen before plotting again.
        self.plots_stale = False
        self.notes = []  # lines put before the current op's output

    # -- server and documents ------------------------------------------------------------------
    def _server_alive(self):
        return self.api is not None and self.api.process.poll() is None

    def _check_server(self):
        """A server found dead: drop it and the document state, and say so."""
        if self.api is not None and not self._server_alive():
            self.notes.append(f"KiCad server exited (code {self.api.process.returncode}): the open project is "
                              "closed; build or open it again")
            self.close()

    def ensure_server(self, directory):
        directory = Path(directory).resolve()
        self._check_server()
        if self._server_alive() and self.directory == directory:
            return
        self.close()
        stack = contextlib.ExitStack()
        try:
            self.api = stack.enter_context(runtime.server(self.current["launcher"], Path(self.current["config_home"]),
                                                          directory))
        except BaseException:
            stack.close()
            self.api = None
            raise
        self.stack, self.directory = stack, directory

    def reset_documents(self):
        if self._server_alive():
            self.api(schematic._proto.project.CloseAllDocuments(force=True))
        self.project = None
        self.built = False
        self.batches = 0
        self.plots_stale = False
        self.foreign, self.upgrade = None, False

    @contextlib.contextmanager
    def attach(self, out):
        """schematic.run()'s server: this session's, with every document closed."""
        self.ensure_server(out)
        self.reset_documents()
        yield self.api

    def adopt(self, project):
        self.project = project
        self.built = True
        self.batches = 0

    def reopen(self):
        """Close every document and open the project again from its saved files."""
        root, kept = self.project.root.path.resolve(), (self.built, self.batches, self.foreign, self.upgrade)
        self.reset_documents()
        self.project = schematic.Project.open(self.api, root)
        self.built, self.batches, self.foreign, self.upgrade = kept

    def close(self):
        stack, self.stack = self.stack, None
        self.api = self.directory = self.project = None
        self.built = False
        self.batches = 0
        self.plots_stale = False
        self.foreign, self.upgrade = None, False
        if stack is not None:
            stack.close()

    def require_document(self):
        self._check_server()
        if self.project is None:
            raise OpError(NO_DOCUMENT)

    def _sheet(self, request):
        """The sheet a query names with `sheet` (a file stem), or None when it names none."""
        stem = request.get("sheet")
        if not stem:
            return None
        found = next((s for s in self.project.sheets if s.path.stem == stem), None)
        if found is None:
            raise OpError(f"no sheet {stem!r}; sheets: {', '.join(s.path.stem for s in self.project.sheets)}")
        return found

    def _foreign(self, root):
        """(format version, saved by, running release) when the root sheet was last saved by another KiCad
        release than the running one, else None. KiCad saves only its own file format."""
        head = root.read_text(errors="replace")[:2000]
        saved = re.search(r'\(generator_version "([^"]*)"\)', head)
        ours = ".".join(self.current["full_version"].split(".")[:2])
        if saved and saved[1] == ours:
            return None
        version = re.search(r"\(version (\d+)\)", head)
        return (version[1] if version else "unknown", f"KiCad {saved[1]}" if saved else "another KiCad release",
                ours)

    def root(self):
        """(root .kicad_sch path, root DocumentSpecifier) of the open document."""
        return self.project.root.path.resolve(), self.project.root.document

    def sheets(self):
        """[(file stem, hierarchical path, DocumentSpecifier, path)] of every sheet, root first."""
        return [(s.path.stem, s.hier_path, s.document, s.path.resolve()) for s in self.project.sheets]

    def files(self):
        if self.project is None:
            return []
        root, _ = self.root()
        return [str(path) for _, _, _, path in self.sheets()] + [str(root.with_suffix(".kicad_pro"))]

    def _hashes(self):
        """sha256 of every sheet file and the .kicad_pro on disk."""
        return [hashlib.sha256(Path(f).read_bytes()).hexdigest() if Path(f).exists() else None for f in self.files()]

    def fingerprint(self):
        """sha256 over every sheet's items (symbol instances without their library definition)."""
        p = schematic._proto
        en = p.enums
        kinds = [en.KOT_SCH_SYMBOL, en.KOT_SCH_LINE, en.KOT_SCH_JUNCTION, en.KOT_SCH_NO_CONNECT, en.KOT_SCH_LABEL,
                 en.KOT_SCH_GLOBAL_LABEL, en.KOT_SCH_HIER_LABEL, en.KOT_SCH_TEXT, en.KOT_SCH_SHEET]
        total = hashlib.sha256()
        for _, _, spec, _ in self.sheets():
            blobs = []
            for item in self.api(p.editor.GetItems(header=p.types.ItemHeader(document=spec), types=kinds)).items:
                if item.Is(p.sch.SchematicSymbolInstance.DESCRIPTOR):
                    instance = p.sch.SchematicSymbolInstance()
                    item.Unpack(instance)
                    instance.ClearField("definition")
                    blobs.append(instance.SerializeToString(deterministic=True))
                else:
                    blobs.append(item.SerializeToString(deterministic=True))
            sheet = hashlib.sha256()
            for blob in sorted(blobs):
                sheet.update(blob)
            total.update(sheet.digest())
        return total.hexdigest()

    def state(self):
        root = str(self.root()[0]) if self.project is not None else None
        return {"pid": os.getpid(), "server_pid": self.api.process.pid if self._server_alive() else None,
                "project_dir": str(Path(root).parent) if root else None, "root": root, "files": self.files(),
                "built": self.built, "batches": self.batches, "kicad": self.current["full_version"]}

    # -- ops ------------------------------------------------------------------------------------
    def op_status(self, request):
        self._check_server()
        document = self.project is not None
        lines = [f"daemon pid: {os.getpid()}",
                 f"server pid: {self.api.process.pid if self._server_alive() else 'none'}"]
        if document:
            lines.append(f"project: {self.root()[0]} ({'built this session' if self.built else 'opened'})")
            lines.append(f"batches: {self.batches}")
        else:
            lines.append("project: none")
        lines.append(f"kicad: {self.current['full_version']}")
        return {"output": "\n".join(lines), "fingerprint": self.fingerprint() if document else None}

    def op_open(self, request):
        try:
            root = runtime.project_root(request["path"])
        except ValueError as e:
            raise OpError(str(e)) from None
        self._check_server()
        if self.project is not None and self.built and self.project.root.path.resolve() == root:
            return {"output": "already open (built this session)"}

        self.ensure_server(root.parent)
        self.reset_documents()
        self.project = schematic.Project.open(self.api, root)
        self.foreign, self.upgrade = self._foreign(root), request.get("upgrade") is True
        sheets = self.project.sheets
        symbols = sum(1 for s in sheets for p in s.placements.values() if not p.ref.startswith("#"))
        lines = [f"opened {root} ({len(sheets)} sheet(s): {' '.join(s.hier_path for s in sheets)})",
                 f"symbols: {symbols}"]
        if self.foreign:
            version, saved, ours = self.foreign
            lines.append(f"file format: {version}, saved by {saved}; this is KiCad {ours}. " + (
                f"upgrade: true given: the first committed kicaddy_edit batch rewrites every sheet in the {ours} "
                f"format, which {saved} cannot open." if self.upgrade else
                "kicaddy_query and kicaddy_render change nothing. kicaddy_edit is refused: a save rewrites every "
                f"sheet in the {ours} format, which {saved} cannot open. Ask the user; when they agree, reopen "
                "with upgrade: true."))
        if not self.foreign or self.upgrade:
            lines.append("edit with kicaddy_edit; pass expect")
        return {"output": "\n".join(lines)}

    def op_build(self, request):
        script = Path(request["script"]).expanduser().resolve()
        if not script.is_file():
            raise OpError(f"no such script: {script}")
        saved_argv, saved_path, saved_cwd = sys.argv[:], sys.path[:], os.getcwd()
        modules = set(sys.modules)
        buf = io.StringIO()
        code = 0
        try:
            out = request.get("out")
            sys.argv = [str(script), *(["--out", out] if out else [])]
            sys.path.insert(0, str(script.parent))
            os.chdir(request.get("cwd") or script.parent)
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                try:
                    runpy.run_path(str(script), run_name="__main__")
                except SystemExit as e:
                    if e.code is None:
                        code = 0
                    elif isinstance(e.code, int):
                        code = e.code
                    else:
                        print(e.code)
                        code = 1
        except Exception:
            self.reset_documents()
            raise OpError(f"{buf.getvalue()}{_trace(str(script))}") from None
        finally:
            sys.argv = saved_argv
            sys.path[:] = saved_path
            os.chdir(saved_cwd)
            for name in set(sys.modules) - modules:  # the design's helper modules load fresh next time
                file = getattr(sys.modules[name], "__file__", None) or ""
                if file and Path(file).resolve().is_relative_to(script.parent):
                    del sys.modules[name]
        return {"output": f"{buf.getvalue()}exit: {code}"}

    def op_query(self, request):
        what = request.get("what")
        if what == "pins":
            lib_ids = request.get("lib_ids") or []
            if not lib_ids:
                raise OpError('pins needs lib_ids, e.g. ["Device:R"]')
            self._check_server()
            directory = request.get("dir")
            if directory is None and self.project is None:  # nothing open: the session directory's tables
                directory = request.get("cwd") or os.getcwd()
            if directory is None:
                return {"output": _capture(schematic.print_library_pins, self.api, self.root()[1], lib_ids)[1].rstrip()}
            if not Path(directory).is_dir():
                raise OpError(f"no such directory: {directory}")
            try:  # a short-lived server, as `kicaddy pins --dir`: the open project's server keeps its own tables
                return {"output": _capture(schematic.probe_pins, lib_ids, directory)[1].rstrip()}
            except RuntimeError as e:  # a library that does not load, as the CLI reports it
                raise OpError(f"error: {e}") from None
        self.require_document()
        sheet = self._sheet(request)
        if what == "symbols":
            refs = set(request.get("refs") or [])
            lines, seen = [], set()
            for s in [sheet] if sheet else self.project.sheets:
                for p in s.placements.values():
                    if p.ref.startswith("#") or (refs and p.ref not in refs):
                        continue
                    seen.add(p.ref)
                    lib = p.definition.id
                    unit = f" unit {p.unit}" if p.definition.unit_count > 1 else ""
                    turn = (f" rot {p.rotation}" if p.rotation else "") + (f" mirror {p.mirror}" if p.mirror else "")
                    flags = schematic.flag_text(p.instance)
                    lines.append(f"{s.hier_path} {p.ref}{unit}  {lib.library_nickname}:{lib.entry_name}  "
                                 f"{p.instance.value_field.text.text}  @ ({p.origin[0]:g}, {p.origin[1]:g}){turn}"
                                 f"{' ' + flags if flags else ''}")
                    if refs:
                        lines += schematic.symbol_detail(s, p)
            lines += [f"not found: {ref}" for ref in sorted(refs - seen)]
            return {"output": "\n".join(lines) or "no symbols"}
        if what == "nets":
            here = set(sheet.pins) if sheet else None
            return {"output": _capture(schematic.print_nets, self.project.netlist(), here)[1].rstrip() or "no nets"}
        if what == "erc":
            violations = self.project.erc()
            if sheet:
                violations = [v for v in violations
                              if (v.sheet_specific_path.path_human_readable or "/") == sheet.hier_path]
            return {"output": _capture(schematic.print_erc, violations)[1].rstrip()}
        if what == "lint":
            issues = schematic.lint_issues(self.project, sheet)
            return {"output": _capture(schematic.print_lint, issues)[1].rstrip()}
        if what == "items":
            self.project.load()  # the document as it is: a project built this session has no item ids until loaded
            try:
                lines = schematic.sheet_items(self.project, sheet or self.project.root, request.get("net") or None)
            except ValueError as e:
                raise OpError(str(e)) from None
            return {"output": "\n".join(lines)}
        raise OpError(f"what must be symbols, nets, erc, lint, items, or pins, not {what!r}")

    def op_render(self, request):
        self.require_document()
        if self.plots_stale:
            self.reopen()
        sheets = self.sheets()
        wanted = request.get("sheet")
        if wanted:
            sheets = [s for s in sheets if s[0] == wanted]
            if not sheets:
                raise OpError(f"no sheet {wanted!r}; sheets: {', '.join(s[0] for s in self.sheets())}")
        root, _ = self.root()
        images = []
        for stem, _, spec, _ in sheets:
            images += [str(path) for path in schematic.plot_cropped(self.api, spec, root.parent / f"{stem}_crop.png")]
        return {"output": "\n".join(f"crop: {path}" for path in images), "images": images}

    @staticmethod
    def _erc_key(v):
        return (schematic._proto.types.RuleSeverity.Name(v.severity), v.description,
                round(v.position.x_nm / GRID_NM, 2), round(v.position.y_nm / GRID_NM, 2),
                v.sheet_specific_path.path_human_readable)

    def op_edit(self, request):
        self.require_document()
        if self.foreign and not self.upgrade:
            raise OpError(NEEDS_UPGRADE.format(saved=self.foreign[1], ours=self.foreign[2]))
        project, api, e = self.project, self.api, schematic._proto.editor
        stems = {s.path.stem: s for s in project.sheets}
        target = stems.get(request.get("sheet") or project.root.path.stem)
        if target is None:
            raise OpError(f"no sheet {request.get('sheet')!r}; sheets: {', '.join(stems)}")
        expect = request.get("expect")
        if expect is None and not self.built:
            raise OpError(NO_EXPECT)
        number = self.batches + 1
        code = request.get("code") or ""
        linecache.cache["<batch>"] = (len(code), None, code.splitlines(True), "<batch>")  # source in tracebacks
        project.load()  # the model equals the document at batch start
        before = netdiff.Snapshot(project.components(), project.netlist())
        flags_before = project.part_flags()
        hints_before = set(schematic.crossing_hints(project))
        if expect is not None:
            try:
                want = netdiff.expected(before, expect)
            except ValueError as err:
                raise OpError(f"expect: {err}") from None
        erc_before = {self._erc_key(v) for v in project.erc()}
        lint_before = set(schematic.lint_issues(project))
        snapshot = project.snapshot()
        fingerprint = self.fingerprint()
        hashes = self._hashes()
        header = project.root.header
        buf = io.StringIO()
        placed = []  # (sheet, instance KIID) of symbols committed by the first commit
        commit = None
        try:
            commit = api(e.BeginCommit(header=header))
            project.in_batch = True
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                exec(compile(code, "<batch>", "exec"),
                     {"s": target, "project": project, "sheets": stems, "__builtins__": builtins})
            project.in_batch = False
            api(e.EndCommit(id=commit.id, action=e.CMA_COMMIT, message=f"kicaddy batch {number}: place",
                            header=header))
            commit = None
            placed = [(s, p.instance.id) for s in project.sheets for p in s.placements.values() if not p.existing]
            commit = api(e.BeginCommit(header=header))
            for s in project.sheets:
                s.commit(staged=True)
            api(e.EndCommit(id=commit.id, action=e.CMA_COMMIT, message=f"kicaddy batch {number}", header=header))
            commit = None
        except (Exception, SystemExit):
            # exit() in a batch drops the batch like any error; _Stop (SIGTERM) still propagates
            error = _trace("<batch>")
            project.in_batch = False
            if commit is not None:
                with contextlib.suppress(Exception):
                    api(e.EndCommit(id=commit.id, action=e.CMA_DROP, header=header))
            for s in {s for s, _ in placed}:
                with contextlib.suppress(Exception):
                    api(e.DeleteItems(header=s.header, item_ids=[i for t, i in placed if t is s]))
            project.restore(snapshot)
            if self.fingerprint() == fingerprint:
                raise OpError(f"{buf.getvalue()}{error}batch dropped: document unchanged") from None
            self.reopen()
            raise OpError(f"{buf.getvalue()}{error}batch dropped; reopened the saved files "
                          f"({'unchanged' if self._hashes() == hashes else 'CHANGED'})") from None
        finally:
            project.in_batch = False

        hints = [h for h in schematic.crossing_hints(project) if h not in hints_before]  # before the reload merges
        project.load()
        after = netdiff.Snapshot(project.components(), project.netlist())
        changes = netdiff.diff(before, after)
        lines = [buf.getvalue().rstrip()]
        if changes:
            report = [f"netlist: {len(after.nets)} nets, {len(changes)} change(s)", *(f"  {c}" for c in changes)]
        else:
            report = ["netlist: unchanged"]
        report += [f"flags: {ref} {text or 'none'}" for ref, text in sorted(project.part_flags().items())
                   if text != flags_before.get(ref, "")]
        if expect is not None:
            mismatch = netdiff.check(want, after, set(expect.get("add", {})))
            if mismatch:
                self.reopen()
                state = "unchanged" if self._hashes() == hashes else "CHANGED"
                lines += [*report, "expect mismatch:", *(f"  {m}" for m in mismatch), *hints,
                          f"batch dropped: the netlist change does not match expect; reopened the saved files ({state})"]
                raise OpError("\n".join(line for line in lines if line))

        api(schematic._proto.project.SaveDocument(document=project.root.document))
        self.batches = number
        self.plots_stale = True
        lines += [f"batch {number} committed (sheet {target.hier_path})", *report,
                  "expect: matched" if expect is not None else "expect: not given"]
        violations = project.erc()
        new = [v for v in violations if self._erc_key(v) not in erc_before]
        lines += [f"ERC: {len(violations)} violation(s), {len(new)} new", *(f"  {schematic.format_violation(v)}"
                                                                         for v in new)]
        issues = schematic.lint_issues(project)
        fresh = [i for i in issues if i not in lint_before]
        lines += [f"LINT: {len(issues)} issue(s), {len(fresh)} new", *(f"  {i}" for i in fresh)]
        lines.append(f"saved: {project.root.path.resolve()}")
        return {"output": "\n".join(line for line in lines if line)}

    def op_shutdown(self, request):
        self.close()
        return {"output": "stopped"}

    def handle(self, request):
        self.notes = []
        result = {}
        op = request.get("op")
        handler = getattr(self, f"op_{op}", None) if isinstance(op, str) else None
        try:
            if handler is None:
                raise OpError(f"unknown op {op!r}")
            result = handler(request)
            ok, output = True, result.get("output", "")
        except (OpError, runtime.ProjectBusyError, bootstrap.SetupError) as e:
            ok, output = False, str(e)
        except Exception:
            ok, output = False, traceback.format_exc()
        response = {"id": request.get("id"), "ok": ok, "output": "\n".join([*self.notes, output]).strip(),
                    "images": result.get("images", []) if ok else [], "state": self.state()}
        if "fingerprint" in result:
            response["fingerprint"] = result["fingerprint"]
        return response


def main():
    with contextlib.suppress(OSError):
        os.setsid()  # terminal signals aimed at omp's process group reach neither the daemon nor its server
    protocol = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)  # stray prints and C-level writes go to stderr
    try:
        current = bootstrap.load_current()
    except bootstrap.SetupError as e:
        print(e, file=sys.stderr)
        return 1
    schematic.bind(current["bindings"])
    session = Session(current)
    schematic._live = session
    try:
        for sig in (signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, _stop)
        while line := sys.stdin.readline():
            if not line.strip():
                continue
            try:
                request = json.loads(line)
                if not isinstance(request, dict):
                    raise ValueError("not an object")
            except ValueError as e:
                request = {"op": None}
                response = {"id": None, "ok": False, "output": f"bad request: {e}", "images": [],
                            "state": session.state()}
            else:
                response = session.handle(request)
            try:
                protocol.write(json.dumps(response) + "\n")
            except OSError:  # omp is gone
                break
            if request.get("op") == "shutdown":
                break
    except _Stop:
        pass
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
