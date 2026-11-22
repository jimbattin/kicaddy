#!/usr/bin/env python3
"""Stereo headphone amplifier, 9 V battery, NJM4556A dual op-amp (fixed circuit).

Each channel is a non-inverting stage biased at Vref = 4.5 V:
    AC gain = 1 + R3/R5 = 2 (DC gain 1 because C3 blocks DC through R5)
    input HPF  1/(2 pi R1 C1) = 1.6 Hz, gain-leg HPF 1/(2 pi R5 C3) = 1.6 Hz
    output HPF 1/(2 pi 32 ohm C5) = 5 Hz into 32 ohm phones
"""

import sys

from kicaddy.schematic import run

OYT, OYB, OX = 28, 64, 65  # op-amp origins: top = left channel, bottom = right channel


def channel(s, ox, oy, unit, inp, neg, out, cin, rb, rfb, rg, cg, cout, rbl, rb_rot):
    """Non-inverting AC-coupled stage around op-amp unit at (ox, oy)."""
    s.symbol("U1", "Amplifier_Operational:NJM4556A", (ox, oy), value="NJM4556A", unit=unit)
    s.symbol(cin, "Device:C", (ox - 18, oy - 2), value="1u", rotation=90)
    s.symbol(rb, "Device:R", (ox - 12, oy + 2), value="100k", rotation=rb_rot)
    s.symbol(rfb, "Device:R", (ox, oy + 8), value="10k", rotation=90)
    s.symbol(rg, "Device:R", (ox - 8, oy + 12), value="10k")
    s.symbol(cg, "Device:C_Polarized", (ox - 8, oy + 19), value="10u")
    s.symbol(cout, "Device:C_Polarized", (ox + 14, oy), value="1000u", rotation=90)
    s.symbol(rbl, "Device:R", (ox + 21, oy + 4), value="1k")

    # + input: coupling cap, bias resistor to VREF
    s.wire(f"{cin}.2", inp)
    node_a = (ox - 12, oy - 2)
    top, bot = (f"{rb}.1", f"{rb}.2") if rb_rot == 0 else (f"{rb}.2", f"{rb}.1")
    s.wire(node_a, top)
    s.wire(bot, (ox - 12, oy + 7))
    s.label("VREF", (ox - 12, oy + 7), spin="left")

    # - input: feedback resistor from output, gain-set leg R + C to ground
    s.wire(neg, (ox - 8, oy + 2), (ox - 8, oy + 8), f"{rfb}.1")
    s.wire((ox - 8, oy + 8), f"{rg}.1")
    s.wire(f"{rg}.2", f"{cg}.1")
    s.wire(f"{cg}.2", (ox - 8, oy + 24))
    s.power("GND", (ox - 8, oy + 24))
    s.wire(out, f"{cout}.1")
    s.wire((ox + 8, oy), (ox + 8, oy + 8), f"{rfb}.2")

    # output: coupling cap, bleed resistor to ground
    s.wire(f"{cout}.2", (ox + 21, oy), f"{rbl}.1")
    s.wire(f"{rbl}.2", (ox + 21, oy + 9))
    s.power("GND", (ox + 21, oy + 9))


def build(s):
    channel(s, OX, OYT, 2, "U1.5", "U1.6", "U1.7", "C2", "R2", "R4", "R6", "C4", "C6", "R8", 180)
    channel(s, OX, OYB, 1, "U1.3", "U1.2", "U1.1", "C1", "R1", "R3", "R5", "C3", "C5", "R7", 0)
    s.note("LEFT channel (U1B)", (44, 18))
    s.note("RIGHT channel (U1A)", (66, 54))

    # input jack: T -> left (top), R -> right (bottom), S -> ground
    jy = (OYT + OYB) // 2
    s.symbol("J1", "Connector_Audio:AudioJack3", (28, jy), value="Line in", mirror="x")
    s.wire("J1.T", (40, jy - 2), (40, OYT - 2), "C2.1")
    s.wire("J1.R", (40, jy), (40, OYB - 2), "C1.1")
    s.wire("J1.S", (34, jy + 2), (34, jy + 5))
    s.power("GND", (34, jy + 5))

    # output jack: left -> T, right -> R, S -> ground
    s.symbol("J2", "Connector_Audio:AudioJack3", (102, jy), value="Phones", rotation=180)
    s.wire((OX + 21, OYT), (92, OYT), (92, jy - 2), "J2.T")
    s.wire((OX + 21, OYB), (92, OYB), (92, jy), "J2.R")
    s.wire("J2.S", (96, jy + 2), (96, jy + 5))
    s.power("GND", (96, jy + 5))

    # power: battery, switch, +9V rail, bulk/decoupling, op-amp supply, VREF divider
    s.symbol("BT1", "Device:Battery", (120, 34), value="9V")
    s.symbol("SW1", "Switch:SW_SPST", (128, 26), value="Power")
    s.symbol("C7", "Device:C_Polarized", (140, 30), value="100u")
    s.symbol("C8", "Device:C", (148, 30), value="100n")
    s.symbol("U1", "Amplifier_Operational:NJM4556A", (158, 32), value="NJM4556A", unit=3)
    s.symbol("R9", "Device:R", (168, 30), value="47k")
    s.symbol("R10", "Device:R", (168, 38), value="47k")
    s.symbol("C9", "Device:C_Polarized", (176, 38), value="10u")

    s.wire("BT1.1", (120, 26), "SW1.1")
    s.wire("SW1.2", (168, 26), "R9.1")
    s.wire((140, 26), "C7.1")
    s.wire((148, 26), "C8.1")
    s.power("+9V", (136, 26))
    s.power("PWR_FLAG", (144, 26))
    s.wire("BT1.2", (120, 42))
    s.wire((120, 42), (114, 42))
    s.power("GND", (120, 42))
    s.power("PWR_FLAG", (114, 42))
    for ref in ("C7", "C8"):
        x = s.pins[f"{ref}.2"][0]
        s.wire(f"{ref}.2", (x, 36))
        s.power("GND", (x, 36))
    s.wire("U1.4", (156, 40))
    s.power("GND", (156, 40))
    s.wire("R9.2", "R10.1")
    s.wire((168, 34), (176, 34), "C9.1")
    s.wire((176, 34), (182, 34))
    s.label("VREF", (182, 34), spin="right")
    s.wire("R10.2", (168, 44))
    s.power("GND", (168, 44))
    s.wire("C9.2", (176, 44))
    s.power("GND", (176, 44))
    s.note("POWER and VREF", (114, 18))

    s.note("Stereo headphone amp, 9 V battery, NJM4556A (70 mA out)\n"
           "VREF = 9 V x R10 / (R9 + R10) = 4.5 V, filtered by C9 10u\n"
           "AC gain = 1 + R3 / R5 = 1 + 10k / 10k = 2 (+6 dB); DC gain 1 (C3, C4 block DC)\n"
           "Input HPF  = 1 / (2 pi R1 C1) = 1 / (2 pi x 100k x 1u) = 1.6 Hz\n"
           "Gain-leg HPF = 1 / (2 pi R5 C3) = 1 / (2 pi x 10k x 10u) = 1.6 Hz\n"
           "Output HPF = 1 / (2 pi x 32 ohm x 1000u) = 5 Hz into 32 ohm phones\n"
           "R7, R8 1k bleed keep C5, C6 charged (no plug-in pop)", (114, 66))

    return [
        {"J1.S", "J2.S", "C3.2", "C4.2", "R7.2", "R8.2", "R10.2", "C9.2", "C7.2", "C8.2", "U1.4", "BT1.2"},
        {"SW1.2", "C7.1", "C8.1", "U1.8", "R9.1"},
        {"BT1.1", "SW1.1"},
        {"J1.R", "C1.1"},
        {"J1.T", "C2.1"},
        {"C1.2", "R1.1", "U1.3"},
        {"C2.2", "R2.2", "U1.5"},
        {"R1.2", "R2.1", "R9.2", "R10.1", "C9.1"},
        {"U1.2", "R3.1", "R5.1"},
        {"U1.6", "R4.1", "R6.1"},
        {"R5.2", "C3.1"},
        {"R6.2", "C4.1"},
        {"U1.1", "R3.2", "C5.1"},
        {"U1.7", "R4.2", "C6.1"},
        {"C5.2", "R7.1", "J2.R"},
        {"C6.2", "R8.1", "J2.T"},
    ]


if __name__ == "__main__":
    sys.exit(run(build, "headphone_amp", page="A4", title="Stereo headphone amplifier, NJM4556A, 9 V",
                 comments=("AC gain 2 (+6 dB), VREF 4.5 V",)))
