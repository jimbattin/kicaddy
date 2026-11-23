#!/usr/bin/env python3
"""A two-sheet project from sheet modules: `kicaddy run build.py --out DIR`.

Each sheet is a module (supply.py, indicator.py) with draw(s) and its nets. The root only places the sheets;
the sheets share nets by name (global labels and power symbols), so the root draws no wires and the sheet boxes
have no pins. Build and fix one sheet at a time with bench.py, then build the root.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import indicator  # noqa: E402
import supply  # noqa: E402
from kicaddy.schematic import run  # noqa: E402

SHEETS = [("supply", supply, "Supply: 9-12 V in, 5 V out"), ("indicator", indicator, "Power indicators")]


def build(s):
    nets = {}
    for i, (name, module, title) in enumerate(SHEETS):
        s.sheet(name, module.draw, (20 + 50 * i, 30), (40, 20), title=title)
        for net, pins in module.GLOBAL.items():
            nets.setdefault(net, set()).update(pins)
    s.note("supply drives VIN, +5V and GND; indicator lights one LED on each rail.\n"
           "The sheets share these nets by name: global label VIN, power symbols +5V and GND.", (20, 58))
    return list(nets.values()) + [n for _, module, _ in SHEETS for n in module.LOCAL]


if __name__ == "__main__":
    sys.exit(run(build, "multi_sheet", page="A4", title="Two-sheet example: supply and indicators"))
