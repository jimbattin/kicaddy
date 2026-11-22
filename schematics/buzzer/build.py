#!/usr/bin/env python3
"""6 V (4 x AA) push-button buzzer, NPN low-side switch, drawn through the KiCad IPC API.

Buzzer: 5 V magnetic active buzzer, ~40 mA at 6 V (rated range 4-7 V).
    I_B  = (6 V - 0.75 V) / R1 - 0.75 V / R2 = 5.25 / 2.2k - 0.75 / 47k = 2.37 mA
    I_C / hFE_min = 40 mA / 60 (2N3904 at 50 mA)                        = 0.67 mA
    -> ~3.5x overdrive, forced beta = 17: Q1 saturates hard (V_CE(sat) < 0.2 V)
R2 (47k) holds the base at 0 V when SW1 is open; D1 clamps the coil's
turn-off spike to V+ + 0.7 V.
"""

import sys

from kicaddy.schematic import run

DX, DY = 10, -8


def p(x, y):
    return (x + DX, y + DY)


def build(s):
    s.symbol("BT1", "Device:Battery", p(40, 60), value="6V 4xAA")
    s.symbol("SW1", "Switch:SW_Push", p(52, 52), value="Push")
    s.symbol("R1", "Device:R", p(62, 52), value="2.2k", rotation=90)
    s.symbol("R2", "Device:R", p(68, 57), value="47k")
    s.symbol("Q1", "Transistor_BJT:2N3904", p(74, 52), value="2N3904")
    s.symbol("BZ1", "Device:Buzzer", p(78, 42), value="5V 40mA")
    s.symbol("D1", "Device:D", p(92, 42), value="1N4148", rotation=270)
    for name, x, y in [("+6V", 40, 50), ("+6V", 48, 46), ("+6V", 76, 36),
                       ("GND", 40, 68), ("GND", 68, 62), ("GND", 76, 62),
                       ("PWR_FLAG", 34, 54), ("PWR_FLAG", 34, 66)]:
        s.power(name, p(x, y))

    s.wire("BT1.1", p(40, 54), p(40, 50))
    s.wire(p(40, 54), p(34, 54))
    s.wire("BT1.2", p(40, 66), p(40, 68))
    s.wire(p(40, 66), p(34, 66))
    s.wire(p(48, 46), "SW1.1")
    s.wire("SW1.2", "R1.1")
    s.wire("R1.2", "Q1.2")
    s.wire(p(68, 52), "R2.1")
    s.wire("R2.2", p(68, 62))
    s.wire("Q1.1", p(76, 62))
    s.wire(p(76, 36), "BZ1.1")
    s.wire("BZ1.2", "Q1.3")
    s.wire(p(76, 38), p(92, 38), "D1.1")
    s.wire("D1.2", p(92, 46), p(76, 46))

    s.note("Push-button buzzer, 6 V (4 x AA), 5 V magnetic buzzer ~40 mA\n"
           "I_B = (6 - 0.75) V / 2.2 k - 0.75 V / 47 k = 2.4 mA\n"
           "I_C / hFE_min = 40 mA / 60 = 0.67 mA -> 3.5x margin, saturated\n"
           "R2 47k: base pull-down; D1: flyback clamp across BZ1", p(34, 77))

    return [
        {"BT1.1", "SW1.1", "BZ1.1", "D1.1"},
        {"BT1.2", "R2.2", "Q1.1"},
        {"SW1.2", "R1.1"},
        {"R1.2", "Q1.2", "R2.1"},
        {"BZ1.2", "Q1.3", "D1.2"},
    ]


if __name__ == "__main__":
    sys.exit(run(build, "buzzer", page="A5", title="Push-button buzzer, 6 V battery",
                 comments=("NPN low-side switch, I_B = 2.4 mA vs I_C/hFE = 0.67 mA",
                           "Drawn through the KiCad IPC API (headless kicad-cli api-server)")))
