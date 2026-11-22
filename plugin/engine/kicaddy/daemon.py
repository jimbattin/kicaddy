"""Session daemon behind the omp extension: one warm KiCad `api-server` per omp session.

Protocol: one JSON object per line. Request {"id", "op", ...}; response {"id", "ok", "output", "images", "state"}
(plus "fingerprint" for `status`). Ops: status, open, build, query, render, edit, shutdown. The daemon exits on
stdin EOF (omp gone), SIGTERM, SIGHUP, or `shutdown`, and stops its server on the way out.

An edit batch runs builder calls on the project built this session in two commits: the batch code runs inside
the first, which holds the symbol placements (PlaceSymbolFromLibrary); the second sends the field updates and the
new items (a symbol placed inside an open commit does not exist for UpdateItems until that commit ends). An
exception in the code drops the first; a failure in the second drops it and deletes the placed symbols.
"""

import builtins
import contextlib
import hashlib
import io
import json
import linecache
import os
import runpy
import signal
import sys
import traceback
from pathlib import Path

from . import bootstrap, runtime, schematic

NO_DOCUMENT = "no document: call kicaddy_build or kicaddy_open first"
NO_PROJECT = ("kicaddy_edit needs a project built in this session with kicaddy_build; kicaddy_open is for query "
              "and render only")
GRID_NM = schematic.GRID_MM * 1e6


class OpError(Exception):
    """An expected failure: the message is the op's whole output."""


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
        self.project = None  # schematic.Project built this session
        self.opened = None  # {"root": Path, "document": DocumentSpecifier, "sheets": [...]} from open
        self.batches = 0
        self.notes = []  # lines put before the current op's output

    # -- server and documents ------------------------------------------------------------------
    def _server_alive(self):
        return self.api is not None and self.api.process.poll() is None

    def _check_server(self):
        """A server found dead: drop it and the document state, and say so."""
        if self.api is not None and not self._server_alive():
            self.notes.append(f"KiCad server exited (code {self.api.process.returncode}); restarted")
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
        self.project = self.opened = None
        self.batches = 0

    @contextlib.contextmanager
    def attach(self, out):
        """schematic.run()'s server: this session's, with every document closed."""
        self.ensure_server(out)
        self.reset_documents()
        yield self.api

    def adopt(self, project):
        self.project = project
        self.batches = 0

    def close(self):
        stack, self.stack = self.stack, None
        self.api = self.directory = self.project = self.opened = None
        self.batches = 0
        if stack is not None:
            stack.close()

    def require_document(self):
        self._check_server()
        if self.project is None and self.opened is None:
            raise OpError(NO_DOCUMENT)

    def root(self):
        """(root .kicad_sch path, root DocumentSpecifier) of the open document."""
        if self.project is not None:
            return self.project.root.path.resolve(), self.project.root.document
        return self.opened["root"], self.opened["document"]

    def sheets(self):
        """[(file stem, hierarchical path, DocumentSpecifier, path)] of every sheet, root first."""
        if self.project is not None:
            return [(s.path.stem, s.hier_path, s.document, s.path.resolve()) for s in self.project.sheets]
        return self.opened["sheets"]

    def files(self):
        if self.project is None and self.opened is None:
            return []
        root, _ = self.root()
        return [str(path) for _, _, _, path in self.sheets()] + [str(root.with_suffix(".kicad_pro"))]

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
        document = self.project is not None or self.opened is not None
        root = str(self.root()[0]) if document else None
        return {"pid": os.getpid(), "server_pid": self.api.process.pid if self._server_alive() else None,
                "project_dir": str(Path(root).parent) if root else None, "root": root, "files": self.files(),
                "built": self.project is not None, "batches": self.batches, "kicad": self.current["full_version"]}

    def _instances(self, spec):
        p = schematic._proto
        items = self.api(p.editor.GetItems(header=p.types.ItemHeader(document=spec),
                                           types=[p.enums.KOT_SCH_SYMBOL])).items
        for item in items:
            instance = p.sch.SchematicSymbolInstance()
            item.Unpack(instance)
            yield instance

    # -- ops ------------------------------------------------------------------------------------
    def op_status(self, request):
        self._check_server()
        document = self.project is not None or self.opened is not None
        lines = [f"daemon pid: {os.getpid()}",
                 f"server pid: {self.api.process.pid if self._server_alive() else 'none'}"]
        if document:
            lines.append(f"project: {self.root()[0]} ({'built this session' if self.project else 'opened'})")
            lines.append(f"batches: {self.batches}")
        else:
            lines.append("project: none")
        lines.append(f"kicad: {self.current['full_version']}")
        return {"output": "\n".join(lines), "fingerprint": self.fingerprint() if document else None}

    def op_open(self, request):
        path = Path(request["path"]).expanduser().resolve()
        if path.is_dir():
            projects = sorted(path.glob("*.kicad_pro"))
            if len(projects) != 1:
                names = ", ".join(p.name for p in projects) or "none"
                raise OpError(f"{path}: {len(projects)} .kicad_pro files ({names}); pass one")
            root = projects[0].with_suffix(".kicad_sch")
        elif path.suffix == ".kicad_pro":
            root = path.with_suffix(".kicad_sch")
        elif path.suffix == ".kicad_sch":
            if not path.with_suffix(".kicad_pro").exists():
                raise OpError(f"not a root schematic: no {path.stem}.kicad_pro")
            root = path
        else:
            raise OpError(f"{path}: pass a project directory, a .kicad_pro, or a root .kicad_sch")
        if not root.exists():
            raise OpError(f"no such file: {root}")
        self._check_server()
        if self.project is not None and self.project.root.path.resolve() == root:
            return {"output": "already open (built this session)"}

        p, t = schematic._proto, schematic._proto.types
        self.ensure_server(root.parent)
        self.reset_documents()
        doc = self.api(p.project.OpenDocument(type=t.DOCTYPE_SCHEMATIC, path=str(root))).document
        top = self.api(p.sch_cmd.GetSchematicHierarchy(document=doc)).top_level_sheets[0]
        sheets = []

        def walk(node, stem):
            spec = t.DocumentSpecifier(type=t.DOCTYPE_SCHEMATIC, sheet_path=node.path, project=doc.project)
            sheets.append((stem, node.path.path_human_readable or "/", spec, (root.parent / node.filename).resolve()))
            for child in node.children:
                walk(child, Path(child.filename).stem)

        walk(top, root.stem)
        self.opened = {"root": root, "document": doc, "sheets": sheets}
        symbols = sum(1 for _, _, spec, _ in sheets for i in self._instances(spec)
                      if not i.reference_field.text.text.startswith("#"))
        return {"output": f"opened {root} ({len(sheets)} sheet(s): {' '.join(h for _, h, _, _ in sheets)})\n"
                          f"symbols: {symbols}\nedits need a project built with kicaddy_build in this session"}

    def op_build(self, request):
        script = Path(request["script"]).expanduser().resolve()
        if not script.is_file():
            raise OpError(f"no such script: {script}")
        saved_argv, saved_path, saved_cwd = sys.argv[:], sys.path[:], os.getcwd()
        modules = set(sys.modules)
        buf = io.StringIO()
        code = 0
        try:
            sys.argv = [str(script), *request.get("args", [])]
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
            raise OpError(f"{buf.getvalue()}{traceback.format_exc()}") from None
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
        self.require_document()
        what = request.get("what")
        p = schematic._proto
        _, document = self.root()
        if what == "symbols":
            lines = []
            for _, hier, spec, _ in self.sheets():
                for i in self._instances(spec):
                    ref = i.reference_field.text.text
                    if ref.startswith("#"):
                        continue
                    lib = i.definition.id
                    lines.append(f"{hier} {ref} unit {i.unit.unit or 1}  {lib.library_nickname}:{lib.entry_name}  "
                                 f"{i.value_field.text.text}  @ ({i.position.x_nm / GRID_NM:g}, "
                                 f"{i.position.y_nm / GRID_NM:g})")
            return {"output": "\n".join(lines) or "no symbols"}
        if what == "nets":
            if self.project is not None:
                nets = self.project.netlist()
            else:
                pin_ids = {}
                for _, _, spec, _ in self.sheets():
                    for i in self._instances(spec):
                        ref = i.reference_field.text.text
                        for child in i.definition.items:
                            if child.item.Is(p.sch.SchematicPin.DESCRIPTOR):
                                pin = p.sch.SchematicPin()
                                child.item.Unpack(pin)
                                pin_ids[pin.id.value] = f"{ref}.{pin.number}"
                nets = schematic.get_netlist(self.api, document, pin_ids)
            return {"output": _capture(schematic.print_nets, nets)[1].rstrip() or "no nets"}
        if what == "erc":
            return {"output": _capture(schematic.print_erc, schematic.run_erc(self.api, document))[1].rstrip()}
        if what == "pins":
            lib_ids = request.get("lib_ids") or []
            if not lib_ids or not all(":" in i for i in lib_ids):
                raise OpError("pins needs lib_ids as Library:Symbol")
            found, text = _capture(schematic.print_library_pins, self.api, document, lib_ids)
            text += "".join(f"not found: {i}\n" for i in lib_ids if i not in found)
            return {"output": text.rstrip()}
        raise OpError(f"what must be symbols, nets, erc, or pins, not {what!r}")

    def op_render(self, request):
        self.require_document()
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

    def op_edit(self, request):
        self.require_document()
        if self.project is None:
            raise OpError(NO_PROJECT)
        project, api, e = self.project, self.api, schematic._proto.editor
        stems = {s.path.stem: s for s in project.sheets}
        target = stems.get(request.get("sheet") or project.root.path.stem)
        if target is None:
            raise OpError(f"no sheet {request.get('sheet')!r}; sheets: {', '.join(stems)}")
        number = self.batches + 1
        code = request.get("code") or ""
        linecache.cache["<batch>"] = (len(code), None, code.splitlines(True), "<batch>")  # source in tracebacks
        snapshot = project.snapshot()
        before = self.fingerprint()
        nets_before = {frozenset(m) for _, m in project.netlist()}
        known = [set(s.placements) for s in project.sheets]
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
            placed = [(s, p.instance.id) for s, keys in zip(project.sheets, known)
                      for key, p in s.placements.items() if key not in keys]
            commit = api(e.BeginCommit(header=header))
            for s in project.sheets:
                s.commit(staged=True)
            api(e.EndCommit(id=commit.id, action=e.CMA_COMMIT, message=f"kicaddy batch {number}", header=header))
            commit = None
        except Exception:
            error = traceback.format_exc()
            project.in_batch = False
            if commit is not None:
                with contextlib.suppress(Exception):
                    api(e.EndCommit(id=commit.id, action=e.CMA_DROP, header=header))
            for s in {s for s, _ in placed}:
                with contextlib.suppress(Exception):
                    api(e.DeleteItems(header=s.header, item_ids=[i for t, i in placed if t is s]))
            project.restore(snapshot)
            if self.fingerprint() == before:
                raise OpError(f"{buf.getvalue()}{error}batch dropped: document unchanged") from None
            self.reset_documents()
            raise OpError(f"{buf.getvalue()}{error}batch dropped, but the document could not be restored; closed "
                          "it: rebuild with kicaddy_build") from None
        finally:
            project.in_batch = False

        api(schematic._proto.project.SaveDocument(document=project.root.document))
        self.batches = number
        nets = project.netlist()
        after = {frozenset(m) for _, m in nets}
        added, removed = after - nets_before, nets_before - after
        lines = [buf.getvalue().rstrip(), f"batch {number} committed (sheet {target.hier_path})",
                 f"nets: {len(nets)} (+{len(added)} -{len(removed)})"]
        lines += [f"  + {' '.join(sorted(m))}" for m in sorted(added, key=sorted)]
        lines += [f"  - {' '.join(sorted(m))}" for m in sorted(removed, key=sorted)]
        lines.append(_capture(schematic.print_erc, project.erc())[1].rstrip())
        lines.append(_capture(schematic.print_lint, schematic.lint_issues(project))[1].rstrip())
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
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda *_: sys.exit(0))
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
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
