#!/usr/bin/env python3
"""16-bit SRAM: 4 x 4 array of 6T CMOS cells, drawn through the KiCad IPC API.

Each cell (row r, column c) is two cross-coupled CMOS inverters (PMOS pull-up PU + NMOS pull-down PD)
storing Qrc / QBrc, plus two NMOS pass-gate (access) transistors PG that connect Qrc to BLc and QBrc to
BLcB while word line WLr is high.

Sizing (W/L relative to the minimum device), pull-down > access > pull-up:
    PD = 3, PG = 1.5, PU = 1
    cell ratio   CR = (W/L)PD / (W/L)PG = 3 / 1.5 = 2    -> read: the '0' node rises only ~0.1-0.2 VDD
                                                            through PG, well below the inverter trip point
    pull-up ratio PR = (W/L)PU / (W/L)PG = 1 / 1.5 = 0.67 -> write: PG overpowers PU and pulls the '1'
                                                            node below the trip point
"""

import sys

from kicaddy.schematic import run

ROWS, COLS = 4, 4
X0, Y0 = 60, 40  # inverter-1 channel / storage-node level of cell (0, 0)
PX, PY = 64, 32  # cell pitch
PU, PD, PG = "W/L=1", "W/L=3", "W/L=1.5"


def build(s):
    refs = iter(range(1, 6 * ROWS * COLS + 1))
    q = {}  # (row, col) -> refs of (A1, P1, N1, P2, N2, A2)

    def cell(r, c, x0, y0):
        a1, p1, n1, p2, n2, a2 = (f"Q{next(refs)}" for _ in range(6))
        q[r, c] = (a1, p1, n1, p2, n2, a2)
        x2 = x0 + 16  # inverter-2 channel
        s.symbol(a1, "Device:Q_NMOS", (x0 - 14, y0 - 2), value=PG, rotation=270)
        s.symbol(p1, "Device:Q_PMOS", (x0 + 2, y0 - 6), value=PU, rotation=180)
        s.symbol(n1, "Device:Q_NMOS", (x0 - 2, y0 + 6), value=PD)
        s.symbol(p2, "Device:Q_PMOS", (x2 + 2, y0 - 6), value=PU, rotation=180)
        s.symbol(n2, "Device:Q_NMOS", (x2 - 2, y0 + 6), value=PD)
        s.symbol(a2, "Device:Q_NMOS", (x0 + 33, y0 - 2), value=PG, rotation=270)
        for x in (x0, x2):
            s.power("VDD", (x, y0 - 10))
            s.power("GND", (x, y0 + 10))

        # inverter 1 (output Q) and its link to BL
        s.wire(f"{p1}.D", (x0, y0), f"{n1}.D")
        s.wire(f"{a1}.D", (x0, y0))
        s.wire(f"{a1}.S", (x0 - 20, y0))
        # inverter 2 (output QB) and its link to BLB
        s.wire(f"{p2}.D", (x2, y0), f"{n2}.D")
        s.wire((x2, y0), f"{a2}.S")
        s.wire(f"{a2}.D", (x0 + 39, y0))
        # cross-coupling: inner gates wired, outer gates by label
        s.wire(f"{n1}.D", (x2 - 6, y0 + 2), f"{n2}.G")  # Q -> PD2 gate
        s.wire(f"{p2}.D", (x0 + 6, y0 - 2), f"{p1}.G")  # QB -> PU1 gate
        s.wire(f"{n1}.G", (x0 - 7, y0 + 6))
        s.label(f"QB{r}{c}", (x0 - 7, y0 + 6), spin="left")
        s.wire(f"{p2}.G", (x2 + 7, y0 - 6))
        s.label(f"Q{r}{c}", (x2 + 7, y0 - 6), spin="right")
        s.label(f"Q{r}{c}", (x0 + 3, y0 + 2))
        s.label(f"QB{r}{c}", (x2 - 2, y0 - 2), spin="left")
        # access gates up to the word line
        s.wire(f"{a1}.G", (x0 - 14, y0 - 16))
        s.wire(f"{a2}.G", (x0 + 33, y0 - 16))
        s.junction((x0, y0), (x0, y0 + 2), (x2, y0), (x2, y0 - 2))
        return [{f"{p1}.D", f"{n1}.D", f"{a1}.D", f"{n2}.G", f"{p2}.G"},
                {f"{p2}.D", f"{n2}.D", f"{a2}.S", f"{p1}.G", f"{n1}.G"}]

    nets = []
    for r in range(ROWS):
        for c in range(COLS):
            nets += cell(r, c, X0 + c * PX, Y0 + r * PY)

    y_last = Y0 + (ROWS - 1) * PY
    for r in range(ROWS):  # word lines, driven from the left
        y = Y0 + r * PY - 16
        x_left, x_end = X0 - 24, X0 + (COLS - 1) * PX + 33
        s.symbol(f"J{r + 1}", "Connector_Generic:Conn_01x01", (x_left - 12, y), value="WL driver", rotation=180)
        s.wire(f"J{r + 1}.1", (x_end, y))
        s.label(f"WL{r}", (x_left, y), spin="left")
        s.junction(*((X0 + c * PX + dx, y) for c in range(COLS) for dx in (-14, 33) if (c, dx) != (COLS - 1, 33)))
        nets.append({f"J{r + 1}.1"} | {f"{q[r, c][i]}.G" for c in range(COLS) for i in (0, 5)})
    for c in range(COLS):  # bit-line pairs, labelled at the top
        x_top = Y0 - 22
        for name, x, i, pin in ((f"BL{c}", X0 + c * PX - 20, 0, "S"), (f"BL{c}B", X0 + c * PX + 39, 5, "D")):
            s.wire((x, x_top), (x, y_last))
            s.label(name, (x, x_top), spin="up")
            s.junction(*((x, Y0 + r * PY) for r in range(ROWS - 1)))
            nets.append({f"{q[r, c][i]}.{pin}" for r in range(ROWS)})
    nets.append({f"{q[r, c][i]}.S" for r in range(ROWS) for c in range(COLS) for i in (1, 3)})  # VDD
    nets.append({f"{q[r, c][i]}.S" for r in range(ROWS) for c in range(COLS) for i in (2, 4)})  # GND

    # supply flags
    xf, yf = X0 - 20, Y0 + (ROWS - 1) * PY + 24
    s.power("VDD", (xf, yf))
    s.wire((xf, yf), (xf + 6, yf))
    s.power("PWR_FLAG", (xf + 6, yf))
    s.power("GND", (xf + 10, yf + 4))
    s.wire((xf + 10, yf + 4), (xf + 16, yf + 4))
    s.power("PWR_FLAG", (xf + 16, yf + 4))

    s.note("16-bit SRAM, 4 x 4 array of 6T cells (PU = PMOS pull-up, PD = NMOS pull-down, PG = NMOS access)\n"
           "Read: precharge BLc and BLcB to VDD, raise WLr; the '0' side discharges its bit line through PG + PD,\n"
           "      a sense amplifier resolves the BL - BLB difference.\n"
           "Write: drive BLc / BLcB to the data and its complement, raise WLr; PG pulls the '1' node low and flips the cell.\n"
           "Sizing (W/L): PD 3 > PG 1.5 > PU 1\n"
           "  cell ratio CR = PD / PG = 3 / 1.5 = 2 (read stability: '0' node stays below the trip point)\n"
           "  pull-up ratio PR = PU / PG = 1 / 1.5 = 0.67 (writability: PG overpowers PU)",
           (xf + 22, yf))
    return nets


if __name__ == "__main__":
    sys.exit(run(build, "sram16", page="A3", title="16-bit SRAM, 4 x 4 array of 6T CMOS cells",
                 comments=("Cell ratio PD/PG = 2, pull-up ratio PU/PG = 0.67",
                           "Drawn through the KiCad IPC API (headless kicad-cli api-server)")))
