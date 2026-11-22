"""Argument parsing for `engine/kicad-agent`. Stdlib only; `runtime` is imported only by `_smoke`."""

import argparse
import json
import shlex
import sys

from . import bootstrap

ENV_KEYS = (("KICAD_AGENT_PYTHON", "python"), ("KICAD_AGENT_KICAD", "kicad"),
            ("KICAD_API_BINDINGS", "bindings"), ("KICAD_CONFIG_HOME", "config_home"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="kicad-agent")
    commands = parser.add_subparsers(dest="command", required=True)

    doctor = commands.add_parser("doctor", help="locate KiCad, build bindings and venv, smoke-test the server")
    doctor.add_argument("--kicad", help="KiCad AppImage, or a kicad-cli binary")
    doctor.add_argument("--refresh", action="store_true", help="rebuild the venv and bindings even if cached")

    commands.add_parser("env", help="print shell exports for the runtime recorded by doctor")

    smoke = commands.add_parser("_smoke", help=argparse.SUPPRESS)
    smoke.add_argument("--kicad", required=True)
    smoke.add_argument("--bindings", required=True)
    smoke.add_argument("--config-home", required=True)
    smoke.add_argument("--expect-version", required=True)

    args = parser.parse_args(argv)
    if args.command == "doctor":
        return bootstrap.doctor(args.kicad, args.refresh)
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
        from . import runtime

        result = runtime.smoke(args.kicad, args.bindings, args.config_home, args.expect_version)
    except Exception as e:  # reported to doctor, which shows it as the `server` FAIL line
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0
