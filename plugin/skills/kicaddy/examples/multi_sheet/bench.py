#!/usr/bin/env python3
"""One sheet of build.py's project alone: `kicaddy run bench.py <sheet module> --out DIR`.

The sheet is a child sheet beside a stub sheet with one global label and test point per net that leaves it
(the module's GLOBAL), and a PWR_FLAG on each stub of a net nothing on the sheet drives (UNDRIVEN): without
the stubs a lone sheet fails ERC on every such net. The bench expects the sheet's nets plus one test-point pin
on each leaving net. A sheet that builds clean here joins the project with the same nets.
"""

import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kicaddy.schematic import run  # noqa: E402


def stubs(module):
    def draw(s):
        for i, name in enumerate(sorted(module.GLOBAL)):
            y = 20 + 6 * i
            s.global_label(name, (20, y), spin="left")
            s.symbol(f"XTP{i + 1}", "Connector:TestPoint", (36, y), value="stub")
            s.wire((20, y), f"XTP{i + 1}.1")
            if name in module.UNDRIVEN:
                s.power("PWR_FLAG", (25, y))
    return draw


def bench(name, module):
    def build(s):
        s.sheet(name, module.draw, (20, 20), (40, 20))
        s.sheet("stubs", stubs(module), (70, 20), (30, 20))
        leaving = [pins | {f"XTP{i + 1}.1"} for i, (_, pins) in enumerate(sorted(module.GLOBAL.items()))]
        return leaving + module.LOCAL
    return build


if __name__ == "__main__":
    name = sys.argv.pop(1)  # before run() reads --out
    sys.exit(run(bench(name, importlib.import_module(name)), f"bench_{name}", page="A4", title=f"{name} bench"))
