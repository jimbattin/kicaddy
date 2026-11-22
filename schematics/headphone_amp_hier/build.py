#!/usr/bin/env python3
"""Stereo 9 V battery headphone amplifier (NJM4556A) as a three-sheet KiCad project, drawn through the KiCad
IPC API: the flat `schematics/headphone_amp` design split into a root (jacks), `power` (battery, op-amp
supply unit U1C, mid-rail reference), and `amp` (both channels, U1A and U1B).

Per channel, non-inverting op-amp stage on a single supply with a buffered-by-capacitor mid-rail:
    Vref  = 9 V x R8 / (R7 + R8)               = 4.5 V   (C3 47 uF holds it at AC ground)
    G     = 1 + Rf / Rg = 1 + 22k / 10k         = 3.2 (+10 dB); DC gain 1 via Cg, output sits at Vref
    f_in  = 1 / (2 pi R1 C1)  = 1 / (2 pi 100k 1u)    = 1.6 Hz
    f_g   = 1 / (2 pi Rg Cg)  = 1 / (2 pi 10k 22u)    = 0.7 Hz
    f_out = 1 / (2 pi RL Cout) = 1 / (2 pi 16 1000u)  = 10 Hz (5 Hz at 32 ohm)
"""

import sys

from kicaddy.schematic import run


def power(s):
    # mid-rail reference
    s.symbol("R7", "Device:R", (44, 45), value="22k")
    s.symbol("R8", "Device:R", (44, 51), value="22k")
    s.symbol("C3", "Device:C_Polarized", (52, 51), value="47u")
    s.power("+9V", (44, 40))
    s.power("GND", (44, 56))
    s.power("GND", (52, 56))
    s.wire((44, 40), "R7.1")
    s.wire("R8.2", (44, 56))
    s.wire("C3.2", (52, 56))
    s.wire("R7.2", (52, 48), (60, 48))
    s.hier_label("VREF", (60, 48), shape="output")

    # supply: battery, op-amp power unit, decoupling
    s.symbol("U1", "Amplifier_Operational:NJM4556A", (30, 85), value="NJM4556A", unit=3)
    s.symbol("BT1", "Device:Battery", (10, 85), value="9V")
    s.symbol("C4", "Device:C", (38, 85), value="100n")
    s.symbol("C5", "Device:C_Polarized", (46, 85), value="220u")
    for name, x, y in [("+9V", 10, 77), ("GND", 10, 93), ("PWR_FLAG", 16, 79), ("PWR_FLAG", 16, 91),
                       ("+9V", 28, 77), ("GND", 28, 93), ("+9V", 38, 80), ("GND", 38, 90),
                       ("+9V", 46, 80), ("GND", 46, 90)]:
        s.power(name, (x, y))
    s.wire("BT1.1", (10, 79), (10, 77))
    s.wire((10, 79), (16, 79))
    s.wire("BT1.2", (10, 91), (10, 93))
    s.wire((10, 91), (16, 91))
    s.wire((28, 77), "U1.8")
    s.wire("U1.4", (28, 93))
    s.wire((38, 80), "C4.1")
    s.wire("C4.2", (38, 90))
    s.wire((46, 80), "C5.1")
    s.wire("C5.2", (46, 90))


def amp(s):
    # top row: right channel (U1A), bottom row: left channel (U1B)
    s.symbol("U1", "Amplifier_Operational:NJM4556A", (70, 30), value="NJM4556A", unit=1)
    s.symbol("U1", "Amplifier_Operational:NJM4556A", (70, 70), value="NJM4556A", unit=2)
    for i, y in ((0, 30), (1, 70)):
        n = 2 * i
        s.symbol(f"C{1 + i}", "Device:C", (26, y - 2), value="1u", rotation=90)
        s.symbol(f"R{1 + i}", "Device:R", (36, y + 1) if i == 0 else (36, y - 5), value="100k")
        s.symbol(f"R{3 + n}", "Device:R", (70, y + 8), value="22k", rotation=90)
        s.symbol(f"R{4 + n}", "Device:R", (62, y + 11), value="10k")
        s.symbol(f"C{6 + n}", "Device:C_Polarized", (62, y + 17), value="22u")
        s.symbol(f"C{7 + n}", "Device:C_Polarized", (86, y), value="1000u", rotation=90)
        s.symbol(f"R{9 + i}", "Device:R", (96, y + 3), value="10k")
        s.power("GND", (62, y + 22))
        s.power("GND", (96, y + 8))

    # inputs from the root through the input capacitors
    s.wire("C1.1", (16, 28))
    s.hier_label("IN_R", (16, 28), spin="left")
    s.wire("C2.1", (16, 68))
    s.hier_label("IN_L", (16, 68), spin="left")

    # non-inverting inputs, bias resistors to Vref from the power sheet
    s.wire("C1.2", (36, 28), "U1.3")
    s.wire("C2.2", (36, 68), "U1.5")
    s.wire("R1.2", (36, 48), "R2.1")
    s.wire((36, 48), (28, 48))
    s.hier_label("VREF", (28, 48), spin="left")

    # feedback networks
    for y, inv, out, rf, rg, cg, cout, rbl in ((30, "U1.2", "U1.1", "R3", "R4", "C6", "C7", "R9"),
                                                (70, "U1.6", "U1.7", "R5", "R6", "C8", "C9", "R10")):
        s.wire(inv, (62, y + 2), (62, y + 8), f"{rf}.1")
        s.wire(f"{rf}.2", (80, y + 8), (80, y), out)
        s.wire((80, y), f"{cout}.1")
        s.wire(f"{cg}.2", (62, y + 22))
        s.wire(f"{rbl}.2", (96, y + 8))

    # outputs to the phone jack on the root: right -> ring, left -> tip
    s.wire("C7.2", (96, 30), (104, 30))
    s.hier_label("OUT_R", (104, 30), shape="output")
    s.wire("C9.2", (96, 70), (104, 70))
    s.hier_label("OUT_L", (104, 70), shape="output")

    s.note("Stereo headphone amp, 9 V battery, single supply, NJM4556A (70 mA out)\n"
           "U1A = right (ring), U1B = left (tip)\n"
           "Vref = 9 V x R8 / (R7 + R8) = 4.5 V, C3 47 uF makes it an AC ground\n"
           "G = 1 + R3 / R4 = 1 + 22k / 10k = 3.2 (+10 dB); C6 gives DC gain 1\n"
           "f_in = 1 / (2 pi 100k 1 uF) = 1.6 Hz;  f_fb = 1 / (2 pi 10k 22 uF) = 0.7 Hz\n"
           "f_out = 1 / (2 pi RL 1000 uF) = 10 Hz at 16 ohm, 5 Hz at 32 ohm\n"
           "I_out max 70 mA: 2.2 V pk = 78 mW into 32 ohm, 1.1 V pk = 39 mW into 16 ohm\n"
           "R9/R10 hold the jack side at 0 V so plugging in does not pop", (70, 95))


def build(s):
    # input jack: sleeve = GND, ring = right, tip = left
    s.symbol("J1", "Connector_Audio:AudioJack3", (8, 50), value="Line in")
    s.power("GND", (15, 48), rotation=90)
    s.wire("J1.S", (15, 48))
    # phone jack, mirrored so that its pins face the amp: sleeve, ring, tip from the top
    s.symbol("J2", "Connector_Audio:AudioJack3", (76, 50), value="Phones", mirror="y")
    s.power("GND", (69, 48), rotation=270)
    s.wire("J2.S", (69, 48))

    s.sheet("amp", amp, (30, 48), (30, 10), title="Amplifier: U1A right, U1B left",
            pins={"IN_R": ("left", 2), "IN_L": ("left", 4), "VREF": ("left", 6),
                  "OUT_R": ("right", 2), "OUT_L": ("right", 4)})
    s.sheet("power", power, (8, 64), (18, 6), title="Battery, op-amp supply, mid-rail reference")

    s.wire("J1.R", "amp.IN_R")
    s.wire("J1.T", "amp.IN_L")
    s.wire("power.VREF", (28, 66), (28, 54), "amp.VREF")
    s.wire("amp.OUT_R", "J2.R")
    s.wire("amp.OUT_L", "J2.T")
    s.net_class("Power", ["+9V", "GND"], track_width=0.5)

    return [
        {"J1.R", "C1.1"},
        {"J1.T", "C2.1"},
        {"C1.2", "R1.1", "U1.3"},
        {"C2.2", "R2.2", "U1.5"},
        {"R1.2", "R2.1", "R7.2", "R8.1", "C3.1"},
        {"U1.2", "R3.1", "R4.1"},
        {"U1.6", "R5.1", "R6.1"},
        {"R4.2", "C6.1"},
        {"R6.2", "C8.1"},
        {"U1.1", "R3.2", "C7.1"},
        {"U1.7", "R5.2", "C9.1"},
        {"C7.2", "R9.1", "J2.R"},
        {"C9.2", "R10.1", "J2.T"},
        {"BT1.1", "R7.1", "U1.8", "C4.1", "C5.1"},
        {"BT1.2", "J1.S", "J2.S", "R8.2", "C3.2", "C6.2", "C8.2", "R9.2", "R10.2", "U1.4", "C4.2", "C5.2"},
    ]


if __name__ == "__main__":
    sys.exit(run(build, "headphone_amp_hier", page="A4",
                 title="Stereo headphone amplifier, 9 V, NJM4556A",
                 comments=("G = 1 + 22k / 10k = 3.2, Vref = 4.5 V",
                           "Drawn through the KiCad IPC API (headless kicad-cli api-server)")))
