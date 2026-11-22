"""Argument parsing for `bin/kicaddy`. Stdlib only; `run`/`pins` exec the venv python, `_smoke` runs inside it."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

from . import bootstrap, config

ENV_KEYS = (("KICADDY_PYTHON", "python"), ("KICADDY_KICAD_PATH", "kicad"),
            ("KICAD_API_BINDINGS", "bindings"), ("KICAD_CONFIG_HOME", "config_home"))
BOM_FIELDS = "Reference,Value,Footprint,${QUANTITY},MPN,Manufacturer,Datasheet,${DNP}"
BOM_LABELS = "Reference,Value,Footprint,Qty,MPN,Manufacturer,Datasheet,DNP"
BOM_GROUP_BY = "Value,Footprint,MPN"


def _exec_venv(args: list) -> int:
    """Replace this process with the runtime's venv python, the engine on PYTHONPATH."""
    try:
        current = bootstrap.load_current()
    except bootstrap.SetupError as e:
        print(e, file=sys.stderr)
        return 1
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(bootstrap.ENGINE), env.get("PYTHONPATH")) if p)
    os.execve(current["python"], [current["python"], *args], env)


def _config(value: str | None) -> int:
    try:
        if value is None:
            choice, source = config.kicad_choice(None)
            print(f"kicad: {choice} (from {source})")
            return 0
        value = config.normalize(value)
        bootstrap.resolve_kicad(value)
        path = config.write_kicad(value)
    except bootstrap.SetupError as e:
        print(e, file=sys.stderr)
        return 1
    print(f"kicad: {value}\nwritten: {path}\nnext: {bootstrap.CLI} doctor")
    return 0


def _view(file: str) -> int:
    try:
        current = bootstrap.load_current()
    except bootstrap.SetupError as e:
        print(e, file=sys.stderr)
        return 1
    path = Path(file).resolve()
    if not path.exists():
        print(f"error: no such file: {path}", file=sys.stderr)
        return 1
    try:
        argv, env = bootstrap.gui_command(current["launcher"], "eeschema", [str(path)], Path(current["config_home"]))
    except bootstrap.SetupError as e:
        print(e, file=sys.stderr)
        return 1
    process = subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    print(f"eeschema started (pid {process.pid}): {path}")
    return 0


def _bom(path: str, output: str | None) -> int:
    """Grouped BOM CSV of the saved project, from `kicad-cli sch export bom`."""
    from . import runtime

    try:
        current = bootstrap.load_current()
    except bootstrap.SetupError as e:
        print(e, file=sys.stderr)
        return 1
    try:
        root = runtime.project_root(path)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    out = Path(output).expanduser().resolve() if output else root.with_name(f"{root.stem}_bom.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    argv, env = bootstrap.kicad_command(current["launcher"], [
        "sch", "export", "bom", "--fields", BOM_FIELDS, "--labels", BOM_LABELS, "--group-by", BOM_GROUP_BY,
        "--ref-range-delimiter", "", "--output", str(out), str(root)], Path(current["config_home"]),
        paths=(root.parent, out.parent))
    try:
        result = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=120)
        code, text = result.returncode, result.stderr + result.stdout
    except subprocess.TimeoutExpired:
        code, text = "timeout", "timed out after 120 s"
    except OSError as e:
        code, text = "none", str(e)
    if code != 0 or not out.exists():
        print(f"error: kicad-cli sch export bom failed (exit {code})", file=sys.stderr)
        lines = [line for line in text.splitlines() if line.strip() and not line.startswith("Fontconfig ")]
        for line in lines[-10:]:
            print(f"  {line}", file=sys.stderr)
        return 1
    with open(out, newline="") as f:
        rows = list(csv.reader(f))[1:]
    parts = sum(int(row[3]) for row in rows if len(row) > 3 and row[3].isdigit())
    print(f"bom: {out} ({len(rows)} rows, {parts} parts)")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="kicaddy")
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="resolve KiCad, build bindings and venv, smoke-test the server")
    doctor.add_argument("--kicad", help="system, flatpak[:APP_ID], or a path (AppImage, kicad-cli, install "
                                        "directory, app bundle)")
    doctor.add_argument("--refresh", action="store_true", help="rebuild the venv and bindings even if cached")

    configure = commands.add_parser("config", help="show or set the KiCad that doctor uses")
    configure.add_argument("key", choices=["kicad"])
    configure.add_argument("value", nargs="?", help="system, flatpak[:APP_ID], or a path; omit to show")

    run = commands.add_parser("run", help="run a Python script (a design build.py) on the runtime")
    run.add_argument("script")
    run.add_argument("args", nargs=argparse.REMAINDER)

    pins = commands.add_parser("pins", help="print pin offsets (grid units, Y down) of library symbols")
    pins.add_argument("lib_ids", nargs="+", metavar="LIB:SYM")
    pins.add_argument("--dir", help="project directory whose sym-lib-table to use (custom symbols)")

    symbol = commands.add_parser("symbol", help="write pin-table JSON files into a project symbol library and "
                                                "print their pin offsets")
    symbol.add_argument("tables", nargs="+", metavar="TABLE.json")
    symbol.add_argument("--dir", required=True, help="project directory (where kicaddy run writes the design)")

    commands.add_parser("env", help="print shell exports for the runtime recorded by doctor")
    commands.add_parser("sweep", help="stop api-servers left by killed kicaddy processes")
    view = commands.add_parser("view", help="open a schematic in eeschema (isolated KiCad config)")
    view.add_argument("file")
    bom = commands.add_parser("bom", help="write a grouped BOM CSV of a saved project")
    bom.add_argument("path", help="project directory, .kicad_pro, or root .kicad_sch")
    bom.add_argument("-o", "--output", help="CSV path; default <root stem>_bom.csv next to the root sheet")
    commands.add_parser("daemon")  # no help: internal (the omp extension's session daemon)

    smoke = commands.add_parser("_smoke")
    smoke.add_argument("--launcher", required=True, help="JSON list")
    smoke.add_argument("--bindings", required=True)
    smoke.add_argument("--config-home", required=True)
    smoke.add_argument("--settings-dir", required=True)
    smoke.add_argument("--expect-version", required=True)

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return bootstrap.doctor(args.kicad, args.refresh)
    if args.command == "config":
        return _config(args.value)
    if args.command == "run":
        return _exec_venv([args.script, *args.args])
    if args.command == "pins":
        extra = ["--dir", args.dir] if args.dir else []
        return _exec_venv(["-m", "kicaddy.schematic", "pins", *args.lib_ids, *extra])
    if args.command == "symbol":
        return _exec_venv(["-m", "kicaddy.schematic", "symbol", *args.tables, "--dir", args.dir])
    if args.command == "env":
        try:
            current = bootstrap.load_current()
        except bootstrap.SetupError as e:
            print(e, file=sys.stderr)
            return 1
        for name, key in ENV_KEYS:
            print(f"export {name}={shlex.quote(str(current[key]))}")
        return 0
    if args.command == "sweep":
        from . import runtime

        for line in runtime.sweep() or ["nothing to sweep"]:
            print(line)
        return 0
    if args.command == "view":
        return _view(args.file)
    if args.command == "bom":
        return _bom(args.path, args.output)
    if args.command == "daemon":
        return _exec_venv(["-m", "kicaddy.daemon"])
    try:
        from . import smoke as smoke_test

        result = smoke_test.run(json.loads(args.launcher), args.bindings, args.config_home, args.settings_dir,
                                args.expect_version)
    except Exception as e:  # reported to doctor, which shows it as the `server` FAIL line
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0
