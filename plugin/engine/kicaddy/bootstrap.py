"""Runtime bootstrap: resolve the chosen KiCad, isolated config, pinned venv, protobuf bindings cached per KiCad
build (source commit, or release tag when the build reports none).

Stdlib only: runs on any system python3 >= 3.9 and creates the venv everything else needs.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
BIN = ENGINE.parent / "bin" / "kicaddy"
CLI = f"python3 {shlex.quote(str(BIN))}"
REQUIREMENTS = "pynng==0.9.0\nprotobuf==7.36.2\ngrpcio-tools==1.85.3\nPillow==13.0.0\n"
KICAD_SOURCE = "https://github.com/KiCad/kicad-source-mirror.git"
FLATPAK_APP = "org.kicad.KiCad"
SYSTEM_CANDIDATES = {
    "linux": ("/usr/bin/kicad-cli", "/usr/local/bin/kicad-cli"),
    "darwin": ("/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
               "/Applications/KiCad.app/Contents/MacOS/kicad-cli"),
}
DIR_CANDIDATES = ("bin/kicad-cli", "kicad-cli", "Contents/MacOS/kicad-cli", "KiCad.app/Contents/MacOS/kicad-cli")
APPIMAGE_MAGIC = b"AI\x02"  # type-2 AppImage marker at byte offset 8


class SetupError(RuntimeError):
    pass


# -- paths ---------------------------------------------------------------------------------------
def cache_root() -> Path:
    if os.environ.get("KICADDY_CACHE"):
        return Path(os.environ["KICADDY_CACHE"]).expanduser()
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "kicaddy"


def runtime_root() -> Path:
    if os.environ.get("XDG_RUNTIME_DIR"):
        root = Path(os.environ["XDG_RUNTIME_DIR"]) / "kicaddy"
    else:
        root = Path(f"/tmp/kicaddy-{os.getuid()}")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    return root


def config_home() -> Path:
    """KICAD_CONFIG_HOME for every KiCad process kicaddy starts; KiCad appends `<major.minor>/`."""
    return cache_root() / "config"


# -- KiCad selection -----------------------------------------------------------------------------
def _executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def resolve_kicad(choice: str) -> dict:
    """{mode, kicad, launcher} for a choice: `system`, `flatpak[:APP_ID]`, or a path."""
    if choice == "system":
        return _resolve_system()
    if choice == "flatpak" or choice.startswith("flatpak:"):
        return _resolve_flatpak(choice.partition(":")[2] or FLATPAK_APP)
    return _resolve_path(choice)


def _resolve_system() -> dict:
    candidates = SYSTEM_CANDIDATES.get(sys.platform, ())
    found = shutil.which("kicad-cli") or next((c for c in candidates if _executable(Path(c))), None)
    if not found:
        raise SetupError(f"no kicad-cli on PATH or in {', '.join(candidates)}; kicaddy needs a KiCad 10.99 nightly "
                         f"or later; choose one with `{CLI} config kicad <path>`")
    return {"mode": "system", "kicad": found, "launcher": [found]}


def _resolve_path(value: str) -> dict:
    p = Path(os.path.abspath(os.path.expanduser(value)))
    if not p.exists():
        raise SetupError(f"KiCad not found at {p}")
    if p.is_dir():
        for relative in DIR_CANDIDATES:
            if _executable(p / relative):
                found = str(p / relative)
                return {"mode": "path", "kicad": found, "launcher": [found]}
        raise SetupError(f"no kicad-cli in {p} (looked for: {', '.join(DIR_CANDIDATES)})")
    try:
        with open(p, "rb") as handle:  # follows symlinks: kicad-nightly -> the AppImage
            head = handle.read(11)
    except OSError as e:
        raise SetupError(f"cannot read {p}: {e}") from None
    if head[8:11] == APPIMAGE_MAGIC:  # AppRun dispatches to the bundled tool named by the first argument
        return {"mode": "path", "kicad": str(p), "launcher": [str(p), "kicad-cli"]}
    if p.name.startswith("kicad-cli"):
        return {"mode": "path", "kicad": str(p), "launcher": [str(p)]}
    raise SetupError(f"{p} is not kicad-cli, a KiCad AppImage, an install directory, or an app bundle")


def _flatpak() -> str:
    found = shutil.which("flatpak")
    if not found:
        raise SetupError("flatpak not found on PATH")
    return found


def _resolve_flatpak(app: str) -> dict:
    flatpak = _flatpak()
    if _run([flatpak, "info", app], check=False).returncode != 0:
        raise SetupError(f"Flatpak app {app} is not installed")
    return {"mode": "flatpak", "kicad": f"flatpak:{app}", "launcher": [flatpak, "run", "--command=kicad-cli", app]}


def fingerprint(mode: str, kicad: str) -> dict:
    """Changes when the KiCad behind `kicad` changes: a re-pointed symlink, a replaced or touched file, a
    Flatpak update."""
    if mode == "flatpak":
        app = kicad.partition(":")[2]
        commit = _run([_flatpak(), "info", "--show-commit", app]).stdout.strip()
        return {"flatpak": app, "commit": commit}
    path = os.path.realpath(kicad)
    stat = os.stat(path)
    return {"path": path, "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _flatpak_fs(path: Path) -> str:
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir:
        try:
            return f"xdg-run/{Path(path).relative_to(runtime_dir)}"
        except ValueError:
            pass
    return str(path)


def kicad_command(launcher: list, args: list, config_home: Path, paths=()) -> tuple[list, dict]:
    """(argv, env) for one KiCad invocation: headless, on the isolated config. A Flatpak launcher also gets the
    config, the socket directory, and the project directory (`paths`) exposed in its sandbox."""
    env = {k: v for k, v in os.environ.items() if k not in ("DISPLAY", "WAYLAND_DISPLAY")}
    env["KICAD_CONFIG_HOME"] = str(config_home)
    if Path(launcher[0]).name == "flatpak":
        mounts = [f"--filesystem={_flatpak_fs(Path(p))}" for p in (config_home, *paths)]
        argv = [*launcher[:-1], f"--env=KICAD_CONFIG_HOME={config_home}", "--die-with-parent", *mounts,
                launcher[-1], *args]
    else:
        argv = [*launcher, *args]
    return [str(a) for a in argv], env


def gui_command(launcher: list, tool: str, args: list, config_home: Path) -> tuple[list, dict]:
    """(argv, env) to start the KiCad GUI program `tool` (eeschema, ...) on the isolated config, with the display
    kept, so the user's own KiCad settings stay untouched."""
    env = dict(os.environ)
    env["KICAD_CONFIG_HOME"] = str(config_home)
    if Path(launcher[0]).name == "flatpak":
        mounts = [f"--filesystem={_flatpak_fs(Path(a).parent)}" for a in args]
        argv = [launcher[0], "run", f"--command={tool}", f"--env=KICAD_CONFIG_HOME={config_home}",
                f"--filesystem={_flatpak_fs(config_home)}", *mounts, launcher[-1], *args]
    elif len(launcher) == 2 and launcher[1] == "kicad-cli":  # AppImage: AppRun dispatches on the first argument
        argv = [launcher[0], tool, *args]
    else:
        cli = Path(launcher[0])
        candidates = (cli.with_name(tool), cli.parent.parent / "Applications" / f"{tool}.app" / "Contents" / "MacOS" / tool)
        found = next((c for c in candidates if _executable(c)), None)
        if found is None:
            raise SetupError(f"no {tool} next to {cli}")
        argv = [found, *args]
    return [str(a) for a in argv], env


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


def probe_kicad(kicad: str, launcher: list, config_home: Path) -> dict:
    """Version, api-server support, and where the matching API protos live (commit, else release tag)."""
    def kicad_cli(*args, check=True):
        argv, env = kicad_command(launcher, list(args), config_home)
        return _run(argv, env=env, check=check)

    about = kicad_cli("version", "--format", "about").stdout
    match = re.search(r"^Version: (\S+?),", about, re.M)
    if not match:
        raise SetupError("no `Version:` line in `kicad-cli version --format about`")
    full_version = match.group(1)
    server = kicad_cli("api-server", "--help", check=False)
    if server.returncode != 0 or "api-server" not in server.stdout + server.stderr:
        raise SetupError(f"KiCad {full_version} at {kicad} has no headless API server; kicaddy needs a 10.99 "
                         f"nightly or later; choose one with `{CLI} config kicad <path>`")
    commit = kicad_cli("version", "--format", "commit", check=False).stdout.strip()
    if re.fullmatch(r"[0-9a-f]{40}", commit):
        bindings_key = source_ref = commit
    elif re.fullmatch(r"\d+\.\d+\.\d+(-rc\d+)?", full_version):
        bindings_key, source_ref = f"tag-{full_version}", f"refs/tags/{full_version}"
    else:
        raise SetupError(f"KiCad {full_version} at {kicad} reports no source commit and is not a release; "
                         "kicaddy cannot fetch its API protos")
    return {"full_version": full_version, "settings_version": ".".join(full_version.split(".")[:2]),
            "major": int(full_version.split(".")[0]), "bindings_key": bindings_key, "source_ref": source_ref}


# -- config, venv, bindings ----------------------------------------------------------------------
def lib_tables(major: int) -> dict:
    """The stock library-table chain; KiCad sets KICAD<major>_TEMPLATE_DIR to its own template directory."""
    def table(kind: str, what: str) -> str:
        return (f"({kind}_lib_table\n"
                "  (version 7)\n"
                f'  (lib (name "KiCad")(type "Table")(uri "${{KICAD{major}_TEMPLATE_DIR}}/{kind}-lib-table")'
                f'(options "")(descr "Official KiCad {what} libraries"))\n'
                ")\n")

    return {"sym-lib-table": table("sym", "symbol"), "fp-lib-table": table("fp", "footprint")}


def ensure_config(settings_version: str, major: int) -> tuple[Path, str]:
    """Isolated KICAD_CONFIG_HOME seeded with the stock library-table chain; existing tables are kept."""
    home = config_home()
    settings = home / settings_version
    settings.mkdir(parents=True, exist_ok=True)
    state = "existing"
    for name, text in lib_tables(major).items():
        if not (settings / name).exists():
            (settings / name).write_text(text)
            state = "created"
    return home, state


def ensure_venv(refresh: bool) -> tuple[Path, str]:
    venv = cache_root() / "venv"
    py = venv / "bin/python"
    marker = venv / ".kicaddy-requirements"
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


def ensure_bindings(key: str, ref: str, full_version: str, py: Path, refresh: bool) -> tuple[Path, str]:
    """Python bindings from the KiCad `api/proto` tree at `ref` (a commit or a release tag), cached under `key`."""
    dest = cache_root() / "bindings" / key
    if not refresh and (dest / "gen/common/envelope_pb2.py").exists():
        try:
            valid = json.loads((dest / "manifest.json").read_text()).get("key") == key
        except (OSError, ValueError):
            valid = False
        if valid:
            return dest / "gen", "cached"
    cache_root().mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(dir=cache_root(), prefix=f".gen-{key[:16]}-"))
    try:
        src, out = tmp / "src", tmp / "out"
        _run(["git", "init", "-q", src])
        _run(["git", "-C", src, "remote", "add", "origin", KICAD_SOURCE])
        _run(["git", "-C", src, "sparse-checkout", "set", "--no-cone", "/api/"])
        _run(["git", "-C", src, "fetch", "-q", "--depth", "1", "--filter=blob:none", "origin", ref], timeout=600)
        _run(["git", "-C", src, "checkout", "-q", "FETCH_HEAD"], timeout=600)  # peels an annotated tag
        proto_root = src / "api/proto"
        protos = sorted(proto_root.rglob("*.proto"))
        if not protos:
            raise SetupError(f"no .proto files at {ref}")
        (out / "gen").mkdir(parents=True)
        _run([py, "-m", "grpc_tools.protoc", "-I", proto_root, f"--python_out={out / 'gen'}",
              f"--pyi_out={out / 'gen'}", *protos], timeout=300)
        (out / "manifest.json").write_text(json.dumps({
            "key": key, "ref": ref, "full_version": full_version, "proto_count": len(protos),
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        }, indent=2) + "\n")
        shutil.rmtree(dest, ignore_errors=True)
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.replace(out, dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dest / "gen", "generated"


def smoke_server(py: Path, launcher: list, bindings: Path, home: Path, settings_version: str,
                 full_version: str) -> dict:
    """Start the server from the venv on the isolated config: version handshake, settings directory,
    library tables, and a schematic round trip must work."""
    result = _run([py, BIN, "_smoke", "--launcher", json.dumps(launcher), "--bindings", bindings,
                   "--config-home", home, "--settings-dir", home / settings_version,
                   "--expect-version", full_version], timeout=240, check=False)
    if result.returncode != 0:
        raise SetupError(_tail(result.stderr or result.stdout) or f"smoke exited {result.returncode}")
    try:
        return json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        raise SetupError(f"unparseable smoke output: {result.stdout!r}") from None


# -- doctor and current.json ---------------------------------------------------------------------
def doctor(kicad_arg: str | None, refresh: bool) -> int:
    from . import config

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

    def platform():
        if sys.platform not in ("linux", "darwin"):
            raise SetupError(f"kicaddy supports Linux and macOS; this is {sys.platform}")
        return sys.platform

    def kicad():
        state["config_kicad"] = config.read().get("kicad")
        value, source = config.kicad_choice(kicad_arg)
        state["choice"] = {"value": value, "source": source}
        state.update(resolve_kicad(value))
        state["kicad_fingerprint"] = fingerprint(state["mode"], state["kicad"])
        return f"{state['kicad']} ({state['mode']}, from {source})"

    def api_server():
        config_home().mkdir(parents=True, exist_ok=True)  # a Flatpak sandbox can only expose existing paths
        state.update(probe_kicad(state["kicad"], state["launcher"], config_home()))
        return f"{state['full_version']} ({state['bindings_key'][:14]})"

    def config_dir():
        state["config_home"], how = ensure_config(state["settings_version"], state["major"])
        return f"{state['config_home']} ({how})"

    def venv():
        state["python"], how = ensure_venv(refresh)
        return f"{state['python']} ({how})"

    def bindings():
        state["bindings"], how = ensure_bindings(state["bindings_key"], state["source_ref"], state["full_version"],
                                                 state["python"], refresh)
        return f"{state['bindings']} ({how})"

    def server():
        r = smoke_server(state["python"], state["launcher"], state["bindings"], state["config_home"],
                         state["settings_version"], state["full_version"])
        return (f"{r['symbol_libraries']} symbol / {r['footprint_libraries']} footprint libraries, "
                f"schematic round trip ok, {r['seconds']} s")

    steps = (("platform", platform), ("kicad", kicad), ("api-server", api_server), ("config", config_dir),
             ("venv", venv), ("bindings", bindings), ("server", server))
    for name, step in steps:
        if not check(name, step):
            return 1

    current = {key: state[key] for key in ("mode", "kicad", "launcher", "kicad_fingerprint", "choice",
                                            "config_kicad", "full_version", "settings_version", "bindings_key")}
    current.update(python=str(state["python"]), bindings=str(state["bindings"]),
                   config_home=str(state["config_home"]))
    path = cache_root() / "current.json"
    tmp = path.with_name("current.json.tmp")
    tmp.write_text(json.dumps(current, indent=2) + "\n")
    os.replace(tmp, path)
    print(f"ready: {state['full_version']} ({state['bindings_key'][:10]})")
    print(f"cli:   {CLI}")
    return 0


def load_current() -> dict:
    """The runtime recorded by the last successful doctor; refuses a KiCad or a config file that changed since.
    A one-run `doctor --kicad` or KICADDY_KICAD override is not compared."""
    from . import config

    path = cache_root() / "current.json"
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        raise SetupError(f"runtime not set up; run: {CLI} doctor") from None
    kicad = data["kicad"]
    try:
        same = fingerprint(data["mode"], kicad) == data["kicad_fingerprint"]
    except (OSError, SetupError):
        same = False
    if not same:
        raise SetupError(f"KiCad at {kicad} changed since doctor ran; rerun: {CLI} doctor")
    old, new = data["config_kicad"], config.read().get("kicad")
    if new != old:
        raise SetupError(f"kicaddy config changed since doctor ran (kicad: {old} -> {new}); rerun: {CLI} doctor")
    return data
