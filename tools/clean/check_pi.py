#!/usr/bin/env python3
"""Check a `pi --mode json` run of tools/clean/pi-faux.ts: python3 check_pi.py JSONL STDERR OUT.

Prints `PI SMOKE: ok`, or one line per failed check and exits 1.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ORDER = ["kicaddy_build", "write", "kicaddy_query", "kicaddy_render"]
TOOLS = {"kicaddy_build", "kicaddy_open", "kicaddy_query", "kicaddy_render", "kicaddy_edit"}


def text(record: dict) -> str:
    content = (record.get("result") or {}).get("content") or []
    return "\n".join(c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text")


def main() -> int:
    jsonl, stderr, out = (Path(a) for a in sys.argv[1:4])
    records = []
    for line in jsonl.read_text().splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "tool_execution_end":
            records.append(event)
    failures = []
    names = [r.get("toolName") for r in records]
    if names != ORDER:
        failures.append(f"tool order: {names}, want {ORDER}")
    by_name = {r.get("toolName"): r for r in records}

    build = by_name.get("kicaddy_build")
    if build is not None:
        body = text(build)
        if build.get("isError"):
            failures.append(f"kicaddy_build: error: {body[-400:]}")
        for want in ("ERC: 0 violation(s)", "LINT: 0 issue(s)", "exit: 0"):
            if want not in body:
                failures.append(f"kicaddy_build: no {want!r}")

    write = by_name.get("write")
    if write is not None:
        if not write.get("isError"):
            failures.append("write: not blocked")
        if "kicaddy holds" not in json.dumps(write):
            failures.append(f"write: no 'kicaddy holds' in {json.dumps(write)[:400]}")
    sch = out / "ne555_blinker.kicad_sch"
    if not sch.is_file() or not sch.read_text().startswith("(kicad_sch"):
        failures.append(f"{sch}: missing or overwritten")

    query = by_name.get("kicaddy_query")
    if query is not None:
        if query.get("isError"):
            failures.append(f"kicaddy_query: error: {text(query)[-400:]}")
        if "net " not in text(query):
            failures.append("kicaddy_query: no `net ` line")

    render = by_name.get("kicaddy_render")
    if render is not None:
        if render.get("isError"):
            failures.append(f"kicaddy_render: error: {text(render)[-400:]}")
        content = (render.get("result") or {}).get("content") or []
        if not any(isinstance(c, dict) and c.get("type") == "image" for c in content):
            failures.append("kicaddy_render: no image content")

    smoke = None
    for line in stderr.read_text().splitlines():
        if line.startswith("KICADDY_SMOKE "):
            smoke = json.loads(line.removeprefix("KICADDY_SMOKE "))
    if smoke is None:
        failures.append("stderr: no KICADDY_SMOKE line")
    else:
        if set(smoke.get("tools", [])) != TOOLS or len(smoke["tools"]) != len(TOOLS):
            failures.append(f"tools: {smoke.get('tools')}, want {sorted(TOOLS)}")
        for command in ("kicaddy", "skill:kicaddy"):
            if command not in smoke.get("commands", []):
                failures.append(f"commands: no {command!r} in {smoke.get('commands')}")

    for failure in failures:
        print(failure)
    if failures:
        return 1
    print("PI SMOKE: ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
