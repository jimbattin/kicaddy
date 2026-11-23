"""KiCad IPC runtime: generated bindings, the NNG client, and a locked private-socket `api-server`.

Needs the venv created by `kicaddy doctor` (pynng, protobuf).
"""

import argparse
import contextlib
import difflib
import fcntl
import hashlib
import importlib
import json
import os
import secrets
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import bootstrap

_proto = None  # namespace of generated modules, filled by load_bindings()
_bindings = None  # the directory they were loaded from


class ProjectBusyError(RuntimeError):
    pass


def load_bindings(path):
    global _proto, _bindings
    path = Path(path).expanduser().resolve()
    if path == _bindings:
        return _proto
    sys.path.insert(0, str(path))
    for module in sorted(path.rglob("*_pb2.py")):  # registers every kiapi type for response unpacking
        importlib.import_module(".".join(module.relative_to(path).with_suffix("").parts))
    from common import envelope_pb2, tasks_pb2
    from common.commands import (base_commands_pb2, editor_commands_pb2, library_commands_pb2,
                                 project_commands_pb2)
    from common.types import base_types_pb2, enums_pb2, jobs_pb2, library_types_pb2, project_settings_pb2
    from schematic import (schematic_commands_pb2, schematic_jobs_pb2, schematic_tasks_pb2,
                           schematic_types_pb2)

    _proto = argparse.Namespace(
        envelope=envelope_pb2, tasks=tasks_pb2, base=base_commands_pb2, editor=editor_commands_pb2,
        library=library_commands_pb2, project=project_commands_pb2, types=base_types_pb2, enums=enums_pb2,
        jobs=jobs_pb2, library_types=library_types_pb2, project_settings=project_settings_pb2,
        sch_cmd=schematic_commands_pb2, sch_jobs=schematic_jobs_pb2, sch_tasks=schematic_tasks_pb2,
        sch=schematic_types_pb2,
    )
    _bindings = path
    return _proto


class Api:
    """One NNG REQ socket; call(request) returns the unpacked response or raises."""

    def __init__(self, socket_path, deadline, client_name="kicaddy"):
        import pynng
        from google.protobuf import empty_pb2, symbol_database  # noqa: F401  (empty_pb2 registers Empty)

        self.symbols = symbol_database.Default()
        self.deadline = deadline
        self.client_name = client_name
        # GetTextExtents answers by text and attributes (schematic.Schematic._extents); server() fills it from
        # kicaddy's cache and saves what it learned there
        self.text_boxes = {}
        self.sock = pynng.Req0(dial=f"ipc://{socket_path}", send_timeout=60000, recv_timeout=60000)

    def __call__(self, request):
        envelope = _proto.envelope.ApiRequest()
        envelope.header.client_name = self.client_name
        envelope.message.Pack(request)
        while True:
            self.sock.send(envelope.SerializeToString())
            reply = _proto.envelope.ApiResponse()
            reply.ParseFromString(self.sock.recv())
            if reply.status.status != _proto.envelope.AS_NOT_READY:
                break
            if time.monotonic() > self.deadline:
                raise TimeoutError("api-server never became ready")
            time.sleep(0.05)
        if reply.status.status != _proto.envelope.AS_OK:
            code = _proto.envelope.ApiStatusCode.Name(reply.status.status)
            raise RuntimeError(f"{type(request).__name__}: {code}: {reply.status.error_message}")
        type_name = reply.message.type_url.rsplit("/", 1)[-1]
        if not type_name:
            return None
        response = self.symbols.GetSymbol(type_name)()
        reply.message.Unpack(response)
        return response


def project_key(project_dir):
    """A short stable key of a project directory: its lock file and its render cache are named by it."""
    return hashlib.sha256(str(Path(project_dir).resolve()).encode()).hexdigest()[:16]


def _extents_file(api):
    """kicaddy's cache file of GetTextExtents answers (Api.text_boxes) for the running KiCad build: an answer
    depends on the text, its attributes, and the build only, so it is kept across servers."""
    version = api(_proto.base.GetVersion()).version.full_version
    return bootstrap.cache_root() / "text-extents" / f"{hashlib.sha256(version.encode()).hexdigest()[:16]}.json"


def _load_extents(path):
    try:
        return {bytes.fromhex(k): tuple(v) for k, v in json.loads(path.read_text()).items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def _save_extents(path, boxes):
    """Merge `boxes` into the cache file; another server may have added answers since this one read it."""
    merged = _load_extents(path)
    merged.update(boxes)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}")
    tmp.write_text(json.dumps({k.hex(): list(v) for k, v in merged.items()}))
    os.replace(tmp, path)


def _lock(root, project_dir):
    """Exclusive advisory lock on a project; flock (not lockf) so a second open in-process also conflicts."""
    key = project_key(project_dir)
    path = root / "locks" / f"{key}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.seek(0)
        pid = (handle.readline().split() or ["?"])[0]
        handle.close()
        raise ProjectBusyError(f"{project_dir} is in use by another kicaddy server (pid {pid})") from None
    handle.truncate(0)
    handle.write(f"{os.getpid()} {project_dir.resolve()}\n")
    handle.flush()
    return key, handle


@contextlib.contextmanager
def server(launcher, config_home, project_dir=None, paths=()):
    """Start `kicad-cli api-server` on a private socket under the runtime dir, with an advisory lock
    per project directory; yield an Api; stop it with SIGINT. `paths`: more directories the server reads."""
    root = bootstrap.runtime_root()
    if project_dir is not None:
        key, lock = _lock(root, Path(project_dir))
    else:
        key, lock = f"anon-{os.getpid()}-{secrets.token_hex(4)}", None
    sock_dir = root / key
    try:
        _stop_servers(sock_dir)  # a killed run's server may still be running there; ours while we hold the lock
        shutil.rmtree(sock_dir, ignore_errors=True)
        sock_dir.mkdir(mode=0o700)
        owner = {"pid": os.getpid(), "project": str(Path(project_dir).resolve()) if project_dir is not None else None}
        (sock_dir / "owner.json").write_text(json.dumps(owner))
        socket_path = sock_dir / "api.sock"
        log_path = sock_dir / "server.log"
        with open(log_path, "wb") as log:
            paths = [sock_dir] + ([Path(project_dir)] if project_dir is not None else []) + [Path(p) for p in paths]
            argv, env = bootstrap.kicad_command(launcher, ["api-server", "--socket", str(socket_path)],
                                                config_home, paths)
            locks = set(Path(project_dir).glob("~*.lck")) if project_dir is not None else set()
            process = subprocess.Popen(argv, env=env, stdout=log, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 90
                while not socket_path.exists():
                    if process.poll() is not None or time.monotonic() > deadline:
                        what = (f"api-server exited with code {process.returncode}" if process.returncode is not None
                                else "api-server did not create its socket")
                        log.flush()
                        tail = "\n".join(log_path.read_text(errors="replace").splitlines()[-20:])
                        raise RuntimeError(f"{what}\n{tail}".rstrip())
                    time.sleep(0.05)
                api = Api(socket_path, deadline)
                api.process = process
                api.scratch = sock_dir  # the server writes here (Flatpak mounts it), the client reads: raw plots
                extents = _extents_file(api)
                api.text_boxes = _load_extents(extents)
                known = len(api.text_boxes)
                try:
                    yield api
                finally:
                    if len(api.text_boxes) > known:
                        with contextlib.suppress(OSError):
                            _save_extents(extents, api.text_boxes)
            finally:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                if project_dir is not None:  # KiCad removes its project lock on SIGINT; a killed server leaves it
                    for stale in set(Path(project_dir).glob("~*.lck")) - locks:
                        stale.unlink(missing_ok=True)
    finally:
        shutil.rmtree(sock_dir, ignore_errors=True)
        if lock is not None:
            lock.close()


def symbol_libraries(api):
    """{nickname: LibraryLoadStatus} of every symbol library row. Global rows exist from server start,
    project rows once the document is open."""
    lt = _proto.library_types
    rows = api(_proto.library.GetLibraryStatuses(types=[lt.LT_SYMBOL], scope=lt.LTS_BOTH)).libraries
    return {row.entry.nickname: row.status for row in rows}


def close_names(name, names, n=5):
    """Up to `n` of `names` that `name` was probably meant to be: near spellings, then names containing it."""
    found = difflib.get_close_matches(name, names, n=n, cutoff=0.6)
    found += [c for c in sorted(names) if name.lower() in c.lower() and c not in found]
    return found[:n]


def unknown_library(nickname, known):
    """Message for a symbol library that is in no library table."""
    close = close_names(nickname, known, 3)
    return f"no symbol library {nickname!r}" + (f"; did you mean {', '.join(close)}?" if close else "")


def wait_for_symbol_libraries(api, nicknames, timeout=60):
    """PlaceSymbolFromLibrary does not wait for the background library load. Rows report
    LLS_INVALID until their load starts, so only LLS_ERROR counts as a failure. A nickname without a row
    fails at once: no load will add it."""
    lt = _proto.library_types
    deadline = time.monotonic() + timeout
    api(_proto.library.LoadAllLibraries(type=[lt.LT_SYMBOL]))
    while True:
        rows = symbol_libraries(api)
        unknown = sorted(nicknames - rows.keys())
        if unknown:
            raise RuntimeError(unknown_library(unknown[0], rows))
        states = {n: rows[n] for n in nicknames}
        if all(s == lt.LLS_LOADED for s in states.values()):
            return
        if any(s == lt.LLS_ERROR for s in states.values()) or time.monotonic() > deadline:
            names = {n: lt.LibraryLoadStatus.Name(s) for n, s in states.items()}
            raise RuntimeError(f"symbol libraries not loaded: {names}")
        time.sleep(0.1)


# -- stdlib only, Python 3.9 (bin/kicaddy imports this module on the system python3) -----------------------------
def project_root(path) -> Path:
    """The root .kicad_sch for a project directory, a .kicad_pro, or a root .kicad_sch; ValueError otherwise."""
    path = Path(path).expanduser().resolve()
    if path.is_dir():
        projects = sorted(path.glob("*.kicad_pro"))
        if len(projects) != 1:
            names = ", ".join(p.name for p in projects) or "none"
            raise ValueError(f"{path}: {len(projects)} .kicad_pro files ({names}); pass one")
        root = projects[0].with_suffix(".kicad_sch")
    elif path.suffix == ".kicad_pro":
        root = path.with_suffix(".kicad_sch")
    elif path.suffix == ".kicad_sch":
        if not path.with_suffix(".kicad_pro").exists():
            raise ValueError(f"not a root schematic: no {path.stem}.kicad_pro")
        root = path
    else:
        raise ValueError(f"{path}: pass a project directory, a .kicad_pro, or a root .kicad_sch")
    if not root.exists():
        raise ValueError(f"no such file: {root}")
    return root


# orphan servers
def _processes():
    """[(pid, args)] of every process."""
    lines = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True).stdout.splitlines()
    out = []
    for line in lines:
        pid, _, args = line.strip().partition(" ")
        if pid.isdigit():
            out.append((int(pid), args))
    return out


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _stop_servers(sock_dir):
    """SIGINT every process serving `sock_dir`/api.sock (the AppImage runtime, its kicad-cli child, Flatpak's
    bwrap), SIGKILL what is left after 5 s; return the pids signalled."""
    socket_path = str(Path(sock_dir) / "api.sock")
    pids = [pid for pid, args in _processes() if socket_path in args and pid != os.getpid()]
    for pid in pids:
        try:
            os.kill(pid, signal.SIGINT)
        except OSError:  # gone, or not ours
            pass
    deadline = time.monotonic() + 5
    while any(_alive(p) for p in pids) and time.monotonic() < deadline:
        time.sleep(0.1)
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
    return pids


def sweep():
    """Stop servers and remove socket directories whose owner process is gone; return one line per directory."""
    lines = []
    for directory in sorted(bootstrap.runtime_root().iterdir()):
        if not directory.is_dir() or directory.name == "locks":
            continue
        record = directory / "owner.json"
        try:
            pid = json.loads(record.read_text())["pid"]
        except (OSError, ValueError, KeyError, TypeError):
            pid = None
        if pid is not None and _alive(pid):
            continue
        if pid is None and not record.exists():
            try:
                if time.time() - directory.stat().st_mtime < 10:  # a server() between mkdir and the record
                    continue
            except FileNotFoundError:
                continue
        pids = _stop_servers(directory)
        shutil.rmtree(directory, ignore_errors=True)
        lines.append(f"{directory.name}: stopped {pids}" if pids else f"{directory.name}: removed")
    return lines
