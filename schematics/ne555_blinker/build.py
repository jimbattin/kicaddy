#!/usr/bin/env python3
"""9 V battery NE555 astable LED blinker, ~5 Hz, drawn through the KiCad IPC API.

    t_high = 0.693 (R1 + R2) C1 = 0.693 x 16.7k x 10u = 115.7 ms
    t_low  = 0.693 R2 C1        = 0.693 x 12k   x 10u =  83.2 ms
    f      = 1 / (t_high + t_low)                     =   5.03 Hz
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from kicad_sch_ipc import run  # noqa: E402

DX, DY = -8, -22  # layout drawn around (100, 60); shifted to sit above the A5 title block


def p(x, y):
    return (x + DX, y + DY)


def build(s):
    s.symbol("U1", "Timer:NE555P", p(100, 60), value="NE555P")
    s.symbol("R1", "Device:R", p(80, 50), value="4.7k")
    s.symbol("R2", "Device:R", p(80, 61), value="12k")
    s.symbol("C1", "Device:C_Polarized", p(80, 71), value="10u")
    s.symbol("C2", "Device:C", p(94, 43), value="10n")
    s.symbol("C3", "Device:C", p(112, 51), value="100n")
    s.symbol("R3", "Device:R", p(118, 63), value="470")
    s.symbol("D1", "Device:LED", p(118, 70), value="Red", rotation=90)
    s.symbol("BT1", "Device:Battery", p(62, 60), value="9V")
    for name, x, y in [("+9V", 80, 44), ("+9V", 112, 48), ("+9V", 62, 52),
                       ("GND", 80, 76), ("GND", 100, 72), ("GND", 94, 47), ("GND", 112, 55),
                       ("GND", 118, 75), ("GND", 62, 70), ("PWR_FLAG", 56, 54), ("PWR_FLAG", 56, 67)]:
        s.power(name, p(x, y))

    s.wire(p(80, 44), "R1.1")
    s.wire(p(80, 44), p(88, 44), p(88, 56), "U1.4")  # RESET tied high
    s.wire("R1.2", "R2.1")
    s.wire("U1.7", "R2.1")  # DISCH between R1 and R2
    s.wire("R2.2", "C1.1")
    s.wire("C1.1", p(88, 68), p(88, 64), "U1.2")  # TRIG
    s.wire("U1.6", p(88, 62), p(88, 64))  # THRES
    s.wire("C1.2", p(80, 76))
    s.wire("U1.1", p(100, 72))
    s.wire("U1.5", p(100, 40), "C2.1")  # CONT bypass
    s.wire("C2.2", p(94, 47))
    s.wire("U1.8", p(102, 48), "C3.1")  # VCC and its decoupling cap
    s.wire("C3.2", p(112, 55))
    s.wire("U1.3", "R3.1")
    s.wire("R3.2", "D1.2")
    s.wire("D1.1", p(118, 75))
    s.wire("BT1.1", p(62, 54), p(62, 52))
    s.wire(p(62, 54), p(56, 54))
    s.wire("BT1.2", p(62, 67), p(62, 70))
    s.wire(p(62, 67), p(56, 67))
    s.junction(*(p(x, y) for x, y in [(80, 44), (80, 58), (80, 68), (88, 64), (112, 48), (62, 54), (62, 67)]))

    s.note("NE555 astable, 9 V battery, LED blinks at ~5 Hz\n"
           "t_on  = 0.693 (R1 + R2) C1 = 0.693 x 16.7 k x 10 uF = 116 ms\n"
           "t_off = 0.693 R2 C1 = 0.693 x 12 k x 10 uF = 83 ms\n"
           "f = 1 / (t_on + t_off) = 5.0 Hz, duty 58 %\n"
           "I_LED = (V_OH - V_F) / R3 = (7.6 V - 2.0 V) / 470 R = 12 mA", p(56, 85))

    return [
        {"BT1.1", "R1.1", "U1.4", "U1.8", "C3.1"},
        {"BT1.2", "C1.2", "C2.2", "C3.2", "D1.1", "U1.1"},
        {"R1.2", "R2.1", "U1.7"},
        {"R2.2", "C1.1", "U1.2", "U1.6"},
        {"U1.5", "C2.1"},
        {"U1.3", "R3.1"},
        {"R3.2", "D1.2"},
    ]


if __name__ == "__main__":
    sys.exit(run(build, "ne555_blinker", page="A5", title="NE555 LED blinker, 5 Hz, 9 V battery",
                 comments=("f = 1.44 / ((R1 + 2 R2) C1) = 5.0 Hz",
                           "Drawn through the KiCad IPC API (headless kicad-cli api-server)")))
