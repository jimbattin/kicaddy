"""KiCad IPC runtime: generated bindings, the NNG client, and a locked private-socket `api-server`.

Needs the venv created by `kicaddy doctor` (pynng, protobuf).
"""

import argparse
import contextlib
import fcntl
import hashlib
import importlib
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


class ProjectBusyError(RuntimeError):
    pass


def load_bindings(path):
    global _proto
    path = Path(path).expanduser().resolve()
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
    return _proto


class Api:
    """One NNG REQ socket; call(request) returns the unpacked response or raises."""

    def __init__(self, socket_path, deadline, client_name="kicaddy"):
        import pynng
        from google.protobuf import empty_pb2, symbol_database  # noqa: F401  (empty_pb2 registers Empty)

        self.symbols = symbol_database.Default()
        self.deadline = deadline
        self.client_name = client_name
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


def _lock(root, project_dir):
    """Exclusive advisory lock on a project; flock (not lockf) so a second open in-process also conflicts."""
    key = hashlib.sha256(str(project_dir.resolve()).encode()).hexdigest()[:16]
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
def server(launcher, config_home, project_dir=None):
    """Start `kicad-cli api-server` on a private socket under the runtime dir, with an advisory lock
    per project directory; yield an Api; stop it with SIGINT."""
    root = bootstrap.runtime_root()
    if project_dir is not None:
        key, lock = _lock(root, Path(project_dir))
    else:
        key, lock = f"anon-{os.getpid()}-{secrets.token_hex(4)}", None
    sock_dir = root / key
    try:
        shutil.rmtree(sock_dir, ignore_errors=True)  # leftover from a killed run; ours while we hold the lock
        sock_dir.mkdir(mode=0o700)
        socket_path = sock_dir / "api.sock"
        log_path = sock_dir / "server.log"
        with open(log_path, "wb") as log:
            paths = [sock_dir] + ([Path(project_dir)] if project_dir is not None else [])
            argv, env = bootstrap.kicad_command(launcher, ["api-server", "--socket", str(socket_path)],
                                                config_home, paths)
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
                yield Api(socket_path, deadline)
            finally:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
    finally:
        shutil.rmtree(sock_dir, ignore_errors=True)
        if lock is not None:
            lock.close()


def wait_for_symbol_libraries(api, nicknames):
    """PlaceSymbolFromLibrary does not wait for the background library load. Rows report
    LLS_INVALID until their load starts, so only LLS_ERROR counts as a failure."""
    lt = _proto.library_types
    api(_proto.library.LoadAllLibraries(type=[lt.LT_SYMBOL]))
    while True:
        rows = api(_proto.library.GetLibraryStatuses(types=[lt.LT_SYMBOL], scope=lt.LTS_BOTH)).libraries
        states = {row.entry.nickname: row.status for row in rows if row.entry.nickname in nicknames}
        if nicknames <= states.keys() and all(s == lt.LLS_LOADED for s in states.values()):
            return
        if any(s == lt.LLS_ERROR for s in states.values()) or time.monotonic() > api.deadline:
            raise RuntimeError(f"symbol libraries not loaded: {states}")
        time.sleep(0.1)
