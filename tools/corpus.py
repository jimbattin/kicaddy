#!/usr/bin/env python3
"""Rebuild the design corpus (`schematics/*/build.py`) into a temporary directory on a KiCad build, and with
`--record` add that build to the plugin's tested-builds list. `--latest` downloads the newest KiCad nightly AppImage
into ~/.cache/kicaddy-nightly and tests it on its own runtime there; the configured KiCad and runtime are untouched.

    python3 tools/corpus.py [--latest] [--record]

Stdlib only. Not shipped with the plugin.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugin"
BIN = PLUGIN / "bin/kicaddy"
SYMBOL_TABLES = {"daisy_seed3": [PLUGIN / "skills/kicaddy/examples/daisy_seed3.json"]}
LATEST = "https://kicad-downloads.s3.cern.ch/appimage/latest.json"
NIGHTLY = "https://kicad-downloads.s3.cern.ch/appimage/nightly/"
TESTED_BUILDS = PLUGIN / "engine/kicaddy/tested_builds.json"

sys.path.insert(0, str(PLUGIN / "engine"))
from kicaddy import bootstrap  # noqa: E402


class Failure(Exception):
    pass


def download(url: str, dest: Path) -> None:
    """Stream `url` to `dest`, reporting progress in MB on stderr every 50 MB."""
    step = 50 * 1024 * 1024
    done, mark = 0, step
    with urllib.request.urlopen(url, timeout=60) as response, open(dest, "wb") as f:
        total = int(response.headers.get("Content-Length") or 0)
        while chunk := response.read(1024 * 1024):
            f.write(chunk)
            done += len(chunk)
            if done >= mark:
                of = f" / {total // 2**20}" if total else ""
                print(f"  {done // 2**20}{of} MB", file=sys.stderr, flush=True)
                mark += step


def fetch_latest() -> tuple[Path, str]:
    """(AppImage path, git sha) of the newest nightly, downloaded into the cache if missing."""
    root = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "kicaddy-nightly"
    try:
        with urllib.request.urlopen(LATEST, timeout=60) as response:
            nightly = json.load(response)["variants"]["nightly"]
        filename, sha = nightly["filename"], nightly["git_sha"]
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise Failure(f"{LATEST}: {e}") from None
    directory = root / "appimage"
    appimage = directory / filename
    if not appimage.exists():
        directory.mkdir(parents=True, exist_ok=True)
        part = directory / f"{filename}.tar.part"
        print(f"downloading {filename}", file=sys.stderr, flush=True)
        try:
            download(NIGHTLY + filename + ".tar", part)
            with tarfile.open(part) as tar:
                members = tar.getmembers()
                if len(members) != 1 or not members[0].isreg() or not members[0].name.endswith(".AppImage"):
                    raise Failure(f"unexpected archive contents: {', '.join(m.name for m in members)}")
                source = tar.extractfile(members[0])
                with open(appimage, "wb") as f:
                    shutil.copyfileobj(source, f, 1024 * 1024)
        except (OSError, tarfile.TarError) as e:
            appimage.unlink(missing_ok=True)
            raise Failure(f"{NIGHTLY}{filename}.tar: {e}") from None
        except Failure:
            appimage.unlink(missing_ok=True)
            raise
        appimage.chmod(0o755)
        with open(appimage, "rb") as f:
            magic = f.read(11)[8:11]
        if magic != bootstrap.APPIMAGE_MAGIC:
            appimage.unlink()
            raise Failure(f"{filename} is not a type-2 AppImage")
        part.unlink()
        for old in directory.glob("*.AppImage"):
            if old != appimage:
                old.unlink()
    os.environ["KICADDY_CACHE"] = str(root / "runtime")
    os.environ["KICADDY_KICAD"] = str(appimage)
    return appimage, sha


def build(design: str, script: Path, out: Path) -> tuple[bool, str]:
    commands = [[sys.executable, str(BIN), "symbol", str(table), "--dir", str(out)]
                for table in SYMBOL_TABLES.get(design, [])]
    commands.append([sys.executable, str(BIN), "run", str(script), "--out", str(out)])
    log = []
    for command in commands:
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=600)
        except subprocess.TimeoutExpired as e:
            log.append(f"{e.stdout or ''}{e.stderr or ''}timed out after 600 s: {' '.join(command)}")
            return False, "timeout\n" + "\n".join(log)
        log.append(result.stdout + result.stderr)
        if result.returncode != 0:
            return False, f"exit {result.returncode}\n" + "\n".join(log)
    return True, "\n".join(log)


def record(current: dict) -> None:
    try:
        data = json.loads(TESTED_BUILDS.read_text())
    except FileNotFoundError:
        data = {"builds": []}
    version = json.loads((PLUGIN / "package.json").read_text())["version"]
    builds = [b for b in data.get("builds", []) if b.get("key") != current["bindings_key"]]
    builds.append({"key": current["bindings_key"], "version": current["full_version"],
                   "date": date.today().isoformat(), "kicaddy": version})
    data["builds"] = builds
    TESTED_BUILDS.write_text(json.dumps(data, indent=2) + "\n")
    print(f"recorded: {current['full_version']}")


def main() -> int:
    parser = argparse.ArgumentParser(prog="corpus.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--latest", action="store_true", help="download and test the newest KiCad nightly")
    parser.add_argument("--record", action="store_true", help="add the build to the tested-builds list if all pass")
    args = parser.parse_args()

    if args.latest:
        try:
            appimage, sha = fetch_latest()
        except Failure as e:
            print(f"error: {e}")
            return 1
        if subprocess.run([sys.executable, str(BIN), "doctor"]).returncode != 0:
            return 1
    try:
        current = bootstrap.load_current()
    except bootstrap.SetupError as e:
        print(e)
        return 1
    if args.latest and not current["full_version"].endswith("-g" + sha):
        print(f"error: downloaded {appimage.name} reports {current['full_version']}")
        return 1

    scripts = sorted(REPO.glob("schematics/*/build.py"), key=lambda p: p.parent.name)
    tmp = Path(tempfile.mkdtemp(prefix="kicaddy-corpus-"))
    passed = 0
    for script in scripts:
        design = script.parent.name
        out = tmp / design
        out.mkdir()
        start = time.monotonic()
        ok, log = build(design, script, out)
        if ok:
            passed += 1
            print(f"ok    {design:<20} {time.monotonic() - start:.1f} s", flush=True)
        else:
            head, _, rest = log.partition("\n")
            print(f"FAIL  {design:<20} {head}")
            for line in rest.strip().splitlines()[-25:]:
                print(f"  {line}")
            sys.stdout.flush()
    if passed == len(scripts):
        shutil.rmtree(tmp)
    else:
        print(f"kept: {tmp}")
    print(f"corpus: {passed}/{len(scripts)} on KiCad {current['full_version']}")
    if passed != len(scripts):
        return 1
    if args.record:
        record(current)
    else:
        print("not recorded (pass --record)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
