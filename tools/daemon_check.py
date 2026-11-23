#!/usr/bin/env python3
"""Check the session daemon (`kicaddy daemon`, behind the omp extension) on the configured KiCad: library pins
through `cwd` and `dir`, the library hint of a build with `--out`, build, query, render (sheet crops, regions
`around` references and by `box`, nothing written into an opened project), edit batches with `expect` (the
split hint of a series insert) and `strict`, `exit()` in a batch, part flags and the BOM, lookups with body and
field geometry, queries by sheet, lint and items, field angle and alignment, `s.power(symbol=)`, notes and text
boxes changed and removed, frames and tables in `items`, the crossing hint, LINT text boxes, the file-format gate
of `open`, and no lock file left after shutdown. Everything is written to a temporary directory (region images
to kicaddy's render cache, removed at the end); one `ok`/`FAIL` line per check, exit status 1 on any `FAIL`.

    python3 tools/daemon_check.py

Stdlib only. Not shipped with the plugin. Run it with tools/corpus.py before a release.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BIN = REPO / "plugin/bin/kicaddy"
EXAMPLES = REPO / "plugin/skills/kicaddy/examples"
DAISY = "daisy:Daisy_Seed3"

# An empty root sheet as stable KiCad 10.0 saves it: the fixture for the file-format gate.
STABLE_SHEET = "\n".join([
    "(kicad_sch", "\t(version 20260306)", '\t(generator "eeschema")', '\t(generator_version "10.0")',
    '\t(uuid "5b0b2c6e-6c1e-4b7e-9a57-2f1d1c0e7a01")', '\t(paper "A4")', "\t(lib_symbols)", "\t(sheet_instances",
    '\t\t(path "/"', '\t\t\t(page "1")', "\t\t)", "\t)", "\t(embedded_fonts no)", ")", ""])
STABLE_PROJECT = '{\n  "meta": {\n    "filename": "stable.kicad_pro",\n    "version": 3\n  }\n}\n'
STABLE_BATCH = """s.symbol("R1", "Device:R", (40, 40), rotation=90, value="102k 0.1%")
s.symbol("U1", "Amplifier_Operational:TL072", (40, 60), unit=1, value="TL072", dnp=True)
s.symbol("U1", "Amplifier_Operational:TL072", (70, 60), unit=2, value="TL072")
s.symbol("U1", "Amplifier_Operational:TL072", (100, 60), unit=3, value="TL072")
s.symbol("H1", "Mechanical:MountingHole", (130, 40), value="MountingHole")
s.symbol("H2", "Mechanical:MountingHole", (140, 40), value="MountingHole", exclude_from_bom=False)
"""
STABLE_EXPECT = {"add": {"R1": "102k 0.1%", "U1": "TL072", "H1": "MountingHole", "H2": "MountingHole"}}

# Two wire ends meeting on the middle of a third wire: a crossing, unless the junction is set.
CROSS = '''import sys

from kicaddy.schematic import run


def build(s):
    s.symbol("R1", "Device:R", (40, 20))
    s.symbol("R4", "Device:R", (40, 60))
    s.symbol("R2", "Device:R", (30, 40), rotation=90)
    s.symbol("R3", "Device:R", (50, 40), rotation=90)
    s.wire("R1.2", "R4.1")
    s.wire("R2.2", (40, 40))
    s.wire("R3.1", (40, 40))
    for pin in ("R1.1", "R2.1", "R3.2", "R4.2"):
        s.no_connect(pin)
    JUNCTION
    return [{"R1.2", "R4.1", "R2.2", "R3.1"}, {"R1.1"}, {"R2.1"}, {"R3.2"}, {"R4.2"}]


if __name__ == "__main__":
    sys.exit(run(build, "cross", page="A4", title="cross"))
'''
HINT = "hint: wire ends meet on a crossing at ({0}, {1}) on /: s.junction(({0}, {1})) joins all four"
TEXT_BOX = (r"text-pin: R1\.Value / pin R1\.1 @ \([^)]*\); "
            r"R1\.Value box \([\d.]+, [\d.]+\)-\([\d.]+, [\d.]+\) horizontal")

# A design placing a symbol of the project library `daisy`, built from beside the library and from elsewhere.
HINT_SCRIPT = '''import sys
from kicaddy.schematic import run
def build(s):
    s.symbol("U1", "daisy:Daisy_Seed3", (60, 60))
    return []
if __name__ == "__main__":
    sys.exit(run(build, "hint", page="A4", title="hint"))
'''

# The series insert of the skill's `expect` section on the NE555 example: INSERT without its field move (one new
# LINT line), MOVED as the skill has it.
INSERT = '''s.remove_wire("U1.3", "R3.1")
s.symbol("R10", "Device:R", (105, 38), rotation=90, value="100")
s.wire("U1.3", "R10.1")
s.wire("R10.2", "R3.1")
'''
MOVED = INSERT.replace('value="100")\n', 'value="100")\ns.field("R10", "Reference", at=(105, 40))\n')
RIGHT = {"add": {"R10": "100"}, "disconnect": ["R3.1"], "connect": {"R10.1": "U1.3", "R10.2": "R3.1"}}
WRONG = {k: v for k, v in RIGHT.items() if k != "disconnect"}
SPLIT_HINT = ("hint: connect joins a pin's whole net to the target; to move a pin off its net, list it under "
              "disconnect too")

TEXT = ("The quick brown fox jumps over the lazy dog. " * 9)[:400]
TABLE = '''import kicaddy.schematic as S
P = S._proto; sch, t, en, e = P.sch, P.types, P.enums, P.editor
tab = sch.SchematicTable(column_count=2)
for w in (20, 20): tab.column_widths.add(value_nm=round(w * 1.27e6))
for h in (4, 4): tab.row_heights.add(value_nm=round(h * 1.27e6))
for r in range(2):
    for c in range(2):
        b = tab.cells.add(column_span=1, row_span=1).text_box.textbox
        b.top_left.CopyFrom(s.mm((120 + 20 * c, 70 + 4 * r))); b.bottom_right.CopyFrom(s.mm((140 + 20 * c, 74 + 4 * r)))
        b.text = f"cell {r}{c}"
        b.attributes.size.CopyFrom(t.Vector2(x_nm=1270000, y_nm=1270000)); b.attributes.multiline = True
        b.attributes.horizontal_alignment = en.HA_LEFT; b.attributes.vertical_alignment = en.VA_TOP
made = s.api(e.CreateItems(header=s.header, items=[S._pack(tab)]))
S._check(made.created_items, made.status, "table")
'''

RESULTS = []
RENDER_DIRS = set()  # kicaddy's render-cache directories the checks wrote to, removed at the end


class Failure(Exception):
    pass


class Daemon:
    """JSON-lines client of `kicaddy daemon`."""

    def __init__(self, cwd):
        self.process = subprocess.Popen([sys.executable, str(BIN), "daemon"], cwd=cwd, stdin=subprocess.PIPE,
                                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self.next_id = 0

    def request(self, op, **fields):
        self.next_id += 1
        self.process.stdin.write(json.dumps({"id": self.next_id, "op": op, **fields}) + "\n")
        line = self.process.stdout.readline()
        if not line:
            raise Failure(f"{op}: the daemon exited")
        return json.loads(line)

    def close(self):
        try:
            if self.process.poll() is None:
                self.request("shutdown")
        except (Failure, OSError):
            pass
        finally:
            self.process.stdin.close()
            self.process.wait(timeout=60)


def check(name, passed, detail=""):
    RESULTS.append(bool(passed))
    print(f"{'ok  ' if passed else 'FAIL'}  {name}", flush=True)
    if not passed and detail:
        print("      " + str(detail).strip().replace("\n", "\n      "), flush=True)


def kicaddy(*args):
    result = subprocess.run([sys.executable, str(BIN), *map(str, args)], capture_output=True, text=True, timeout=300)
    return result.returncode, result.stdout + result.stderr


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def png_size(path):
    """(width, height) of a PNG file."""
    with open(path, "rb") as f:
        return struct.unpack(">II", f.read(24)[16:24])


def rendered(r, tmp):
    """The images of a render response; those outside `tmp` are in the render cache: remember their directory."""
    images = [Path(p) for p in r.get("images", [])]
    RENDER_DIRS.update(p.parent for p in images if not p.resolve().is_relative_to(tmp.resolve()))
    return images


def symbol_lines(output):
    """{ref: its line} of `query symbols` output (the last unit's for a multi-unit symbol)."""
    return {line.split()[1]: line for line in output.splitlines() if line.startswith("/ ")}


def pins(d, tmp):
    lib, other = tmp / "lib", tmp / "other"
    for directory in (lib, other):
        directory.mkdir()
    code, out = kicaddy("symbol", EXAMPLES / "daisy_seed3.json", "--dir", lib)
    check("symbol: project library written", code == 0 and f"{DAISY}  units=" in out, out)
    r = d.request("query", what="pins", lib_ids=[DAISY], cwd=str(lib))
    check("pins: the session directory's library", r["ok"] and f"{DAISY}  units=" in r["output"], r["output"])
    r = d.request("query", what="pins", lib_ids=[DAISY], cwd=str(other), dir=str(lib))
    check("pins: dir", r["ok"] and f"{DAISY}  units=" in r["output"], r["output"])
    r = d.request("query", what="pins", lib_ids=[DAISY], cwd=str(other))
    check("pins: not found elsewhere", f"not found: {DAISY}" in r["output"], r["output"])
    r = d.request("query", what="pins", lib_ids=[DAISY], dir=str(tmp / "missing"))
    check("pins: a missing dir is an error", not r["ok"] and "no such directory" in r["output"], r["output"])


def library_hint(d, tmp):
    """A build with `--out` that misses a library the script's directory has names it; elsewhere it does not."""
    for where in ("lib", "other"):
        (tmp / where / "build.py").write_text(HINT_SCRIPT)
    r = d.request("build", script=str(tmp / "lib/build.py"), out=str(tmp / "hint_out"), cwd=str(tmp))
    want = f"no symbol library 'daisy' in {tmp.resolve()}/hint_out/sym-lib-table; build.py's directory has it"
    check("hint: library beside the script", not r["ok"] and want in r["output"], r["output"][-800:])
    r = d.request("build", script=str(tmp / "other/build.py"), out=str(tmp / "hint_out2"), cwd=str(tmp))
    check("hint: plain message otherwise", not r["ok"] and "no symbol library 'daisy'" in r["output"]
          and "directory has it" not in r["output"], r["output"][-800:])


def built(d, tmp):
    out = tmp / "ne555"
    r = d.request("build", script=str(EXAMPLES / "ne555_blinker.py"), out=str(out), cwd=str(tmp))
    check("build: exit 0", r["ok"] and r["output"].endswith("exit: 0"), r["output"][-600:])
    r = d.request("query", what="symbols")
    check("query symbols", r["ok"] and "/ R1  Device:R  4.7k  @ " in r["output"], r["output"])
    r = d.request("query", what="nets")
    check("query nets", r["ok"] and "R1.2" in r["output"], r["output"])
    r = d.request("query", what="erc")
    check("query erc", r["ok"] and r["output"].startswith("ERC: 0 violation(s)"), r["output"])
    r = d.request("render")
    check("render: crops exist", r["ok"] and r["images"] and all(Path(p).exists() for p in r["images"]), r["output"])

    r = d.request("edit", code='s.field("R3", "Value", text="1k")', expect={"values": {"R3": "1k"}})
    check("edit: committed, expect matched", r["ok"] and "batch 1 committed" in r["output"]
          and "expect: matched" in r["output"], r["output"])
    r = d.request("edit", code='s.field("R3", "Value", text="2k")', expect={})
    check("edit: expect mismatch drops the batch", not r["ok"] and "expect mismatch:" in r["output"], r["output"])
    r = d.request("edit", code="raise SystemExit('stop')", expect={})
    check("edit: exit() drops the batch", not r["ok"] and "SystemExit: stop" in r["output"]
          and r["output"].rstrip().endswith("batch dropped: document unchanged"), r["output"])
    r = d.request("status")
    check("status: the daemon is up, 1 batch", r["ok"] and "batches: 1" in r["output"], r["output"])

    r = d.request("edit", code='s.flags("C2", dnp=True)\ns.flags("R3", exclude_from_bom=True)', expect={})
    check("flags: batch report", r["ok"] and "netlist: unchanged" in r["output"] and "flags: C2 dnp" in r["output"]
          and "flags: R3 no-bom" in r["output"], r["output"])
    r = d.request("edit", code='s.symbol("C4", "Device:C", (130, 30), value="10n", exclude_from_board=True)',
                  expect={"add": {"C4": "10n"}})
    check("flags: s.symbol argument", r["ok"] and "flags: C4 no-board" in r["output"], r["output"])
    r = d.request("edit", code='s.flags("C2", dnp="yes")', expect={})
    check("flags: a non-boolean is refused", not r["ok"] and "dnp must be True, False, or None" in r["output"],
          r["output"])
    r = d.request("query", what="symbols", refs=["C2", "R3", "C4", "R1"])
    lines = symbol_lines(r["output"])
    check("flags: query symbols", lines.get("C2", "").endswith(" dnp") and lines.get("R3", "").endswith(" no-bom")
          and lines.get("C4", "").endswith(" no-board") and lines.get("R1", "").endswith(")"), r["output"])
    check("flags: saved", (out / "ne555_blinker.kicad_sch").read_text().count("(dnp yes)") == 1)
    code, text = kicaddy("bom", out)
    rows = {}
    if code == 0:
        with open(out / "ne555_blinker_bom.csv", newline="") as f:
            rows = {row[0]: row for row in list(csv.reader(f))[1:]}
    check("bom: DNP and populated parts of one value are separate rows; no-bom parts have none",
          rows.get("C2", [""])[-1] == "DNP" and rows.get("C4", ["x"])[-1] == ""
          and not any("R3" in ref.split(",") for ref in rows), f"{text}\n{rows}")


VALUE_BOX = r'  Value "Red" at \((\d+), (\d+)\) (\w+) box \(([\d.]+), ([\d.]+)\)-\(([\d.]+), ([\d.]+)\) (\w+)'
R9 = '''s.symbol("R9", "Device:R", (150, 30), rotation=90, value="102k 0.1%")
for pin in ("R9.1", "R9.2"):
    s.no_connect(pin)
'''


def queries(d, tmp):
    """On the NE555 project built() left open: lookups with geometry, queries by sheet, lint, items, and
    s.field(angle=, justify=)."""
    r = d.request("query", what="pins", lib_ids=["Device:R", "Amplifier_Operational:TL072"])
    check("pins: body boxes and field positions", r["ok"] and "  unit 1  body (-0.8, -2)-(0.8, 2)" in r["output"]
          and "  Value at (0, 0) center vertical" in r["output"] and "  unit 3  body none" in r["output"]
          and "  Reference at (0, -4) left horizontal" in r["output"], r["output"])
    r = d.request("query", what="symbols", refs=["D1"])
    m = re.search(VALUE_BOX, r["output"])
    check("symbols: body and field boxes of a placed symbol", r["ok"] and "\n  body (" in r["output"] and m
          and (m[3], m[8]) == ("center", "vertical"), r["output"])
    r = d.request("edit", code='s.field("D1", "Value", at=(113, 50), angle=0, justify="left")', expect={})
    q = d.request("query", what="symbols", refs=["D1"])
    m = re.search(VALUE_BOX, q["output"])
    check("field: angle and justify as read on the sheet", r["ok"] and m
          and (m[1], m[2], m[3], m[8]) == ("113", "50", "left", "horizontal") and 113 <= float(m[4]) < 113.5,
          f'{r["output"]}\n{q["output"]}')
    r = d.request("edit", code='s.field("D1", "Value", angle=45)', expect={})
    check("field: a bad angle is refused", not r["ok"] and "angle must be 0 or 90" in r["output"], r["output"])
    r = d.request("query", what="symbols", sheet="ne555_blinker")
    check("query: sheet", r["ok"] and "/ R1  Device:R  4.7k  @ " in r["output"], r["output"])
    r = d.request("query", what="symbols", sheet="nope")
    check("query: an unknown sheet is an error", not r["ok"]
          and r["output"] == "no sheet 'nope'; sheets: ne555_blinker", r["output"])
    r = d.request("query", what="nets", sheet="ne555_blinker")
    check("query nets: sheet", r["ok"] and "R1.2" in r["output"] and "on other sheets" not in r["output"],
          r["output"])
    r = d.request("edit", code=R9, expect={"add": {"R9": "102k 0.1%"}})
    total = re.search(r"^LINT: (\d+) issue\(s\), (\d+) new$", r["output"], re.M)
    q = d.request("query", what="lint")
    check("query lint: the batch's total, one line each", r["ok"] and q["ok"] and total and int(total[2]) >= 1
          and q["output"].splitlines()[0] == f"LINT: {total[1]} issue(s)"
          and len(q["output"].splitlines()) == int(total[1]) + 1
          and "text-pin: R9.Value / pin R9.1" in q["output"], f'{r["output"]}\n{q["output"]}')
    r = d.request("query", what="lint", sheet="ne555_blinker")
    check("query lint: sheet", r["ok"] and r["output"] == q["output"], r["output"])
    r = d.request("query", what="items")
    lines = r["output"].splitlines()
    check("items: power symbols, wires, junctions, no-connects, notes", r["ok"]
          and re.fullmatch(r"/ \d+ item\(s\)", lines[0]) and len(lines) == int(lines[0].split()[1]) + 1
          and re.search(r"^power #PWR\d+ \+9V \(\d+, \d+\)$", r["output"], re.M)
          and re.search(r"^wire \(\d+, \d+\)-\(\d+, \d+\)$", r["output"], re.M)
          and all(f"\n{kind} (" in r["output"] for kind in ("junction", "no-connect", "note")), r["output"])
    r = d.request("query", what="items", net="+9V")
    check("items: one net", r["ok"] and r["output"].splitlines()[0].endswith(" item(s) of net +9V")
          and "\npins BT1.1 C3.1 R1.1 U1.4 U1.8\n" in r["output"] and " PWR_FLAG (" in r["output"]
          and "\nnote (" not in r["output"], r["output"])
    r = d.request("query", what="items", net="NOPE")
    check("items: an unknown net is an error", not r["ok"] and r["output"].startswith("no net 'NOPE'"),
          r["output"])


def edits(d, tmp):
    """On the NE555 project queries() left open: the split hint, strict batches, s.power(symbol=), note_text,
    remove_note, and region renders."""
    root = tmp / "ne555/ne555_blinker.kicad_sch"
    r = d.request("edit", code=INSERT, expect=WRONG)
    check("expect: split hint", not r["ok"] and "expect mismatch:" in r["output"] and SPLIT_HINT in r["output"],
          r["output"])
    before = sha(root)
    r = d.request("edit", code=INSERT, expect=RIGHT, strict=True)
    check("strict: a new LINT line drops the batch", not r["ok"] and "batch dropped: 1 new LINT line" in r["output"]
          and re.search(r"text-text: (R10\.Reference / #PWR07\.Value|#PWR07\.Value / R10\.Reference) @", r["output"])
          and r["output"].endswith("reopened the saved files (unchanged)") and sha(root) == before, r["output"])
    r = d.request("edit", code=MOVED, expect=RIGHT, strict=True)
    check("strict: a clean batch commits", r["ok"] and "expect: matched" in r["output"]
          and re.search(r"^LINT: \d+ issue\(s\), 0 new$", r["output"], re.M), r["output"])

    r = d.request("edit", code='s.power("VBAT", "C4.1", symbol="VCC")', expect={"connect": {"C4.1": "VBAT"}})
    q = d.request("query", what="items", net="VBAT")
    check("power: symbol= names the net", r["ok"] and "expect: matched" in r["output"]
          and re.search(r"^power #PWR\d+ VBAT \(130, 27\)$", q["output"], re.M), f'{r["output"]}\n{q["output"]}')
    r = d.request("edit", code='s.power("VBAT", (140, 20))', expect={})
    check("power: a missing symbol names symbol=", not r["ok"] and "symbol=" in r["output"], r["output"])

    r = d.request("edit", code='s.note_text((48, 63), "edited note")', expect={})
    q = d.request("query", what="items")
    check("note_text", r["ok"] and "netlist: unchanged" in r["output"]
          and 'note (48, 63) "edited note"' in q["output"], f'{r["output"]}\n{q["output"]}')
    r = d.request("edit", code="s.remove_note((48, 63))", expect={})
    q = d.request("query", what="items")
    check("remove_note", r["ok"] and not re.search(r"^note \(", q["output"], re.M), f'{r["output"]}\n{q["output"]}')

    r = d.request("render", around=["R10"])
    images = rendered(r, tmp)
    check("render: around", r["ok"] and len(images) == 1 and images[0].exists()
          and not images[0].resolve().is_relative_to((tmp / "ne555").resolve())
          and all(a <= b for a, b in zip(png_size(images[0]), (1600, 1200))) and r["output"].startswith("region: "),
          r["output"])
    r = d.request("render", box=[80, 25, 120, 55])
    images = rendered(r, tmp)
    check("render: box is 15 px per unit", r["ok"] and len(images) == 1 and png_size(images[0]) == (600, 450),
          f'{r["output"]} {[png_size(p) for p in images]}')
    r = d.request("render", around=["NOPE"])
    q = d.request("render", around=["R10"], box=[0, 0, 9, 9])
    check("render: bad region arguments", not r["ok"] and r["output"] == "around: not placed: NOPE"
          and not q["ok"] and q["output"] == "pass around or box, not both", f'{r["output"]}\n{q["output"]}')


def crossing(d, tmp):
    script = tmp / "cross/build.py"
    script.parent.mkdir()
    script.write_text(CROSS.replace("JUNCTION", "pass"))
    r = d.request("build", script=str(script), cwd=str(tmp))
    check("hint: NETLIST MISMATCH names the crossing", r["ok"] and "NETLIST MISMATCH" in r["output"]
          and HINT.format(40, 40) in r["output"] and r["output"].endswith("exit: 1"), r["output"])
    script.write_text(CROSS.replace("JUNCTION", "s.junction((40, 40))"))
    r = d.request("build", script=str(script), cwd=str(tmp))
    check("hint: none with the junction, exit 0", r["ok"] and "hint:" not in r["output"]
          and r["output"].endswith("exit: 0"), r["output"])
    r = d.request("edit", code="s.wire((60, 70), (60, 80))\ns.wire((55, 75), (60, 75))\ns.wire((60, 75), (65, 75))",
                  expect={"values": {"R1": "1k"}})
    check("hint: expect mismatch names the batch's crossing only", not r["ok"] and "expect mismatch:" in r["output"]
          and HINT.format(60, 75) in r["output"] and r["output"].count("hint:") == 1, r["output"])


def stable(d, tmp):
    directory = tmp / "stable"
    directory.mkdir()
    root = directory / "stable.kicad_sch"
    root.write_text(STABLE_SHEET)
    (directory / "stable.kicad_pro").write_text(STABLE_PROJECT)
    before = sha(root)
    r = d.request("open", path=str(directory))
    note = [line for line in r["output"].splitlines()
            if line.startswith("file format: 20260306, saved by KiCad 10.0; this is KiCad ")]
    check("open: format line, no edit line", r["ok"] and len(note) == 1 and "kicaddy_edit is refused" in note[0]
          and "edit with kicaddy_edit" not in r["output"], r["output"])
    r = d.request("edit", code="", expect={})
    check("edit: refused without upgrade, file unchanged", not r["ok"]
          and r["output"].startswith("this project is in the file format of KiCad 10.0") and sha(root) == before,
          r["output"])
    r = d.request("query", what="symbols")
    check("query: allowed without upgrade", r["ok"] and r["output"] == "no symbols", r["output"])
    r = d.request("open", path=str(directory), upgrade=True)
    check("open: upgrade", r["ok"] and "upgrade: true given" in r["output"]
          and r["output"].splitlines()[-1] == "edit with kicaddy_edit; pass expect", r["output"])
    r = d.request("edit", code=STABLE_BATCH, expect=STABLE_EXPECT)
    text = root.read_text()
    check("edit: committed after upgrade, file rewritten", r["ok"] and "(version 20260306)" not in text, r["output"])
    check("LINT: a text line carries the text's box", re.search(TEXT_BOX, r["output"]), r["output"])
    check("flags: reported for added parts, library default included", "flags: U1 dnp" in r["output"]
          and "flags: H1 no-bom" in r["output"] and "flags: H2" not in r["output"], r["output"])
    check("flags: every unit of a part", text.count("(dnp yes)") == 3, text.count("(dnp yes)"))
    r = d.request("open", path=str(directory))
    check("open: no format line once saved by this KiCad", r["ok"] and "file format:" not in r["output"]
          and r["output"].splitlines()[-1] == "edit with kicaddy_edit; pass expect", r["output"])


def annotations(d, tmp):
    """On the project stable() left open: text boxes and frames, LINT inside a text box, note_text and
    remove_note on a text box, tables in items, and renders that write nothing into an opened project."""
    directory = tmp / "stable"
    root = directory / "stable.kicad_sch"
    r = d.request("edit", code=f"s.text_box({TEXT!r}, (20, 80), (80, 12))\ns.rectangle((10, 76), (110, 96))",
                  expect={})
    text = root.read_text()
    check("text_box and rectangle commit clean", r["ok"] and "netlist: unchanged" in r["output"]
          and re.search(r"^LINT: \d+ issue\(s\), 0 new$", r["output"], re.M) and text.count("(text_box") == 1
          and "(type dash)" in text, r["output"])
    q = d.request("query", what="items")
    check("items: text box and frame", q["ok"] and 'text box (20, 80)-(100, 92) "The quick' in q["output"]
          and re.search(r"^rectangle \(10, 76\)-\(110, 96\) dash$", q["output"], re.M), q["output"])
    r = d.request("edit", code='s.symbol("R5", "Device:R", (60, 86), value="1k")\n'
                  's.no_connect("R5.1")\ns.no_connect("R5.2")', expect={"add": {"R5": "1k"}})
    check("LINT: a part inside a text box", r["ok"] and "text-body: text box (20, 80) / R5 @" in r["output"],
          r["output"])
    r = d.request("edit", code='s.note_text((20, 80), "short")', expect={})
    q = d.request("query", what="items")
    check("note_text on a text box", r["ok"] and 'text box (20, 80)-(100, 92) "short"' in q["output"]
          and root.read_text().count("(text_box") == 1, f'{r["output"]}\n{q["output"]}')
    r = d.request("edit", code="s.remove_note((20, 80))", expect={})
    q = d.request("query", what="items")
    again = d.request("edit", code="s.remove_note((20, 80))", expect={})
    check("remove_note on a text box; a second call fails", r["ok"] and "\ntext box" not in q["output"]
          and not again["ok"] and "no note or text box at (20, 80)" in again["output"],
          f'{r["output"]}\n{q["output"]}\n{again["output"]}')
    r = d.request("edit", code=TABLE, expect={})
    q = d.request("query", what="items")
    check("items: table", r["ok"] and "table (120, 70)-(160, 78) 2 columns, 4 cells" in q["output"],
          f'{r["output"]}\n{q["output"]}')

    r = d.request("render")
    images = rendered(r, tmp)
    check("render: an opened project gets no file", r["ok"] and images and all(p.exists() for p in images)
          and not any(p.resolve().is_relative_to(directory.resolve()) for p in images)
          and not list(directory.glob("*_crop*.png")) and not list(directory.glob(".crop-*")), r["output"])
    r = d.request("render", box=[10, 70, 50, 100], sheet="stable")
    images = rendered(r, tmp)
    check("render: box on an opened project", r["ok"] and len(images) == 1 and png_size(images[0]) == (600, 450),
          f'{r["output"]} {[png_size(p) for p in images]}')


def main():
    tmp = Path(tempfile.mkdtemp(prefix="kicaddy-daemon-check-"))
    started = time.time()
    d = Daemon(tmp)
    try:
        for part in (pins, library_hint, built, queries, edits, crossing, stable, annotations):
            part(d, tmp)
    except Failure as e:
        check("the daemon stayed up", False, e)
    finally:
        d.close()
        check("shutdown: no lock file left in the opened project", not list((tmp / "stable").glob("~*.lck")))
        shutil.rmtree(tmp, ignore_errors=True)
        for directory in RENDER_DIRS:
            shutil.rmtree(directory, ignore_errors=True)
    print(f"daemon check: {sum(RESULTS)}/{len(RESULTS)} in {time.time() - started:.0f} s")
    return 0 if all(RESULTS) else 1


if __name__ == "__main__":
    sys.exit(main())
