"""Runtime bootstrap: locate KiCad, isolated config, pinned venv, protobuf bindings cached by KiCad commit.

Stdlib only: runs on any system python3 and creates the venv everything else needs.
"""

import datetime
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
REQUIREMENTS = "pynng==0.9.0\nprotobuf==7.36.2\ngrpcio-tools==1.85.3\nPillow==13.0.0\n"
KICAD_SOURCE = "https://github.com/KiCad/kicad-source-mirror.git"

LIB_TABLES = {
    "sym-lib-table": """(sym_lib_table
  (version 7)
  (lib (name "KiCad")(type "Table")(uri "${KICAD10_TEMPLATE_DIR}/sym-lib-table")(options "")(descr "Official KiCad symbol libraries"))
)
""",
    "fp-lib-table": """(fp_lib_table
  (version 7)
  (lib (name "KiCad")(type "Table")(uri "${KICAD10_TEMPLATE_DIR}/fp-lib-table")(options "")(descr "Official KiCad footprint libraries"))
)
""",
}


class SetupError(RuntimeError):
    pass


# -- paths ---------------------------------------------------------------------------------------
def cache_root() -> Path:
    if os.environ.get("KICAD_AGENT_CACHE"):
        return Path(os.environ["KICAD_AGENT_CACHE"]).expanduser()
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "kicad-agent"


def runtime_root() -> Path:
    if os.environ.get("XDG_RUNTIME_DIR"):
        root = Path(os.environ["XDG_RUNTIME_DIR"]) / "kicad-agent"
    else:
        root = Path(f"/tmp/kicad-agent-{os.getuid()}")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def config_home() -> Path:
    """KICAD_CONFIG_HOME for every KiCad process the agent starts; KiCad appends `<major.minor>/`."""
    return cache_root() / "config"


# -- KiCad discovery -----------------------------------------------------------------------------
def launcher_for(kicad: str) -> list[str]:
    """The AppImage's AppRun dispatches to a bundled tool named by the first argument."""
    return [kicad] if Path(kicad).name.startswith("kicad-cli") else [kicad, "kicad-cli"]


def locate_kicad(explicit: str | None) -> str:
    for given in (explicit, os.environ.get("KICAD_AGENT_KICAD")):
        if given:
            path = str(Path(given).expanduser())
            if not os.path.exists(path):
                raise SetupError(f"KiCad not found at {path}")
            return path
    nightly = Path.home() / ".local/bin/kicad-nightly"
    if nightly.exists():
        return str(nightly)
    found = shutil.which("kicad-cli")
    if found:
        return found
    raise SetupError("KiCad not found: pass --kicad PATH (AppImage or kicad-cli)")


def kicad_env(config_home: Path) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    env["KICAD_CONFIG_HOME"] = str(config_home)
    return env


def _tail(text: str, lines: int = 20) -> str:
    return "\n".join((text or "").strip().splitlines()[-lines:])


def _run(command: list, timeout: float = 120, env: dict | None = None, check: bool = True):
    """subprocess.run with captured text output; failures become SetupError with the stderr tail."""
    shown = " ".join(str(c) for c in command)
    try:
        result = subprocess.run([str(c) for c in command], capture_output=True, text=True,
                                timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        raise SetupError(f"timed out after {timeout:g} s: {shown}") from None
    except OSError as e:
        raise SetupError(f"{shown}: {e}") from None
    if check and result.returncode != 0:
        raise SetupError(f"exit {result.returncode}: {shown}\n{_tail(result.stderr or result.stdout)}")
    return result


def probe_kicad(launcher: list[str], env: dict) -> dict:
    sha = _run([*launcher, "version", "--format", "commit"], env=env).stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise SetupError(f"unexpected commit from `kicad-cli version --format commit`: {sha!r}")
    about = _run([*launcher, "version", "--format", "about"], env=env).stdout
    match = re.search(r"^Version: (\S+?),", about, re.M)
    if not match:
        raise SetupError("no `Version:` line in `kicad-cli version --format about`")
    full_version = match.group(1)
    server = _run([*launcher, "api-server", "--help"], env=env, check=False)
    if server.returncode != 0 or "api-server" not in server.stdout + server.stderr:
        raise SetupError("this KiCad build has no api-server subcommand (needs a 10.99+ nightly)")
    return {"sha": sha, "full_version": full_version,
            "settings_version": ".".join(full_version.split(".")[:2])}


def fingerprint(kicad: str) -> dict:
    path = os.path.realpath(kicad)
    stat = os.stat(path)
    return {"path": path, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


# -- config, venv, bindings ----------------------------------------------------------------------
def ensure_config(settings_version: str) -> tuple[Path, str]:
    """Isolated KICAD_CONFIG_HOME seeded with the stock library-table chain; existing tables are kept."""
    home = config_home()
    settings = home / settings_version
    settings.mkdir(parents=True, exist_ok=True)
    state = "existing"
    for name, text in LIB_TABLES.items():
        if not (settings / name).exists():
            (settings / name).write_text(text)
            state = "created"
    return home, state


def ensure_venv(refresh: bool) -> tuple[Path, str]:
    venv = cache_root() / "venv"
    py = venv / "bin/python"
    marker = venv / ".kicad-agent-requirements"
    if not refresh and py.exists() and marker.exists() and marker.read_text() == REQUIREMENTS:
        probe = _run([py, "-c", "import pynng, google.protobuf, PIL, grpc_tools"], check=False)
        if probe.returncode == 0:
            return py, "cached"
    uv = shutil.which("uv")
    if not uv:
        raise SetupError("uv not found on PATH; install it: https://docs.astral.sh/uv/")
    shutil.rmtree(venv, ignore_errors=True)
    _run([uv, "venv", "--python", "3.12", venv], timeout=600)
    _run([uv, "pip", "install", "--python", py, *REQUIREMENTS.split()], timeout=600)
    marker.write_text(REQUIREMENTS)
    return py, "created"


def ensure_bindings(sha: str, full_version: str, py: Path, refresh: bool) -> tuple[Path, str]:
    """Python bindings from the KiCad `api/proto` tree at `sha` (docs/02-ipc-protocol.md, "Client bindings")."""
    dest = cache_root() / "bindings" / sha
    if not refresh and (dest / "gen/common/envelope_pb2.py").exists():
        try:
            valid = json.loads((dest / "manifest.json").read_text()).get("sha") == sha
        except (OSError, ValueError):
            valid = False
        if valid:
            return dest / "gen", "cached"
    cache_root().mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=cache_root(), prefix=f".gen-{sha[:10]}-"))
    try:
        src, out = tmp / "src", tmp / "out"
        _run(["git", "init", "-q", src])
        _run(["git", "-C", src, "remote", "add", "origin", KICAD_SOURCE])
        _run(["git", "-C", src, "sparse-checkout", "set", "--no-cone", "/api/"])
        _run(["git", "-C", src, "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", sha], timeout=600)
        _run(["git", "-C", src, "checkout", "-q", "FETCH_HEAD"], timeout=600)
        proto_root = src / "api/proto"
        protos = sorted(proto_root.rglob("*.proto"))
        if not protos:
            raise SetupError(f"no .proto files at {sha}")
        (out / "gen").mkdir(parents=True)
        _run([py, "-m", "grpc_tools.protoc", "-I", proto_root, f"--python_out={out / 'gen'}",
              f"--pyi_out={out / 'gen'}", *protos], timeout=300)
        (out / "manifest.json").write_text(json.dumps({
            "sha": sha, "full_version": full_version, "proto_count": len(protos),
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        }, indent=2) + "\n")
        shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(out, dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dest / "gen", "generated"


def smoke_server(py: Path, kicad: str, bindings: Path, home: Path, full_version: str) -> dict:
    """Start the server from the venv on an isolated config; GetVersion and library status must work."""
    result = _run([py, ENGINE / "kicad-agent", "_smoke", "--kicad", kicad, "--bindings", bindings,
                   "--config-home", home, "--expect-version", full_version], timeout=180, check=False)
    if result.returncode != 0:
        raise SetupError(_tail(result.stderr or result.stdout) or f"smoke exited {result.returncode}")
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        raise SetupError(f"unparseable smoke output: {result.stdout!r}") from None


# -- doctor and current.json ---------------------------------------------------------------------
def doctor(kicad_arg: str | None, refresh: bool) -> int:
    state = {}

    def check(name, step):
        try:
            detail = step()
        except SetupError as e:
            lines = str(e).splitlines() or [""]
            print(f"FAIL  {name:<10} {lines[0]}")
            for line in lines[1:]:
                print(f"      {'':<10} {line}")
            return False
        print(f"ok    {name:<10} {detail}", flush=True)
        return True

    def kicad():
        state["kicad"] = locate_kicad(kicad_arg)
        state["launcher"] = launcher_for(state["kicad"])
        state["kicad_fingerprint"] = fingerprint(state["kicad"])
        return state["kicad"]

    def api_server():
        state.update(probe_kicad(state["launcher"], kicad_env(config_home())))
        return f"{state['full_version']} ({state['sha'][:10]})"

    def config():
        state["config_home"], how = ensure_config(state["settings_version"])
        return f"{state['config_home']} ({how})"

    def venv():
        state["python"], how = ensure_venv(refresh)
        return f"{state['python']} ({how})"

    def bindings():
        state["bindings"], how = ensure_bindings(state["sha"], state["full_version"], state["python"], refresh)
        return f"{state['bindings']} ({how})"

    def server():
        r = smoke_server(state["python"], state["kicad"], state["bindings"], state["config_home"],
                         state["full_version"])
        return (f"{r['symbol_libraries']} symbol / {r['footprint_libraries']} footprint libraries, "
                f"{r['seconds']} s")

    steps = (("kicad", kicad), ("api-server", api_server), ("config", config), ("venv", venv),
             ("bindings", bindings), ("server", server))
    for name, step in steps:
        if not check(name, step):
            return 1

    current = {key: state[key] for key in ("kicad", "launcher", "kicad_fingerprint", "sha", "full_version",
                                            "settings_version")}
    current.update(python=str(state["python"]), bindings=str(state["bindings"]),
                   config_home=str(state["config_home"]))
    path = cache_root() / "current.json"
    tmp = path.with_name("current.json.tmp")
    tmp.write_text(json.dumps(current, indent=2) + "\n")
    os.replace(tmp, path)
    print(f"ready: {state['full_version']} ({state['sha'][:10]})")
    print(f'shell: eval "$(python3 {ENGINE / "kicad-agent"} env)"')
    return 0


def load_current() -> dict:
    """The runtime recorded by the last successful doctor; refuses a KiCad that changed since."""
    path = cache_root() / "current.json"
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise SetupError(f"runtime not set up; run: python3 {ENGINE / 'kicad-agent'} doctor") from None
    kicad = data["kicad"]
    try:
        same = fingerprint(kicad) == data["kicad_fingerprint"]
    except OSError:
        same = False
    if not same:
        raise SetupError(f"KiCad at {kicad} changed since doctor ran; rerun: python3 {ENGINE / 'kicad-agent'} doctor")
    return data
