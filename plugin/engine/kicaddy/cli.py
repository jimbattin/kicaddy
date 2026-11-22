"""Argument parsing for `bin/kicaddy`. Stdlib only; `run`/`pins` exec the venv python, `_smoke` runs inside it."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys

from . import bootstrap, config

ENV_KEYS = (("KICADDY_PYTHON", "python"), ("KICADDY_KICAD_PATH", "kicad"),
            ("KICAD_API_BINDINGS", "bindings"), ("KICAD_CONFIG_HOME", "config_home"))


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

    smoke = commands.add_parser("_smoke", help=argparse.SUPPRESS)
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
    try:
        from . import smoke as smoke_test

        result = smoke_test.run(json.loads(args.launcher), args.bindings, args.config_home, args.settings_dir,
                                args.expect_version)
    except Exception as e:  # reported to doctor, which shows it as the `server` FAIL line
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0
