#!/usr/bin/env python3
"""Stereo headphone amplifier, 9 V battery, NJM4556A (dual op-amp, 70 mA outputs).

Each channel is a non-inverting stage biased at VREF = 4.5 V (mid-supply), AC-coupled in and out:
    gain       G   = 1 + Rf / Rg               = 1 + 10k / 10k      = 2 (6 dB)
    input HPF  f1  = 1 / (2 pi Rb Cin)         = 1 / (2 pi 100k 1u) = 1.6 Hz, Zin = 100k
    Rg leg     f2  = 1 / (2 pi Rg Cg)          = 1 / (2 pi 10k 22u) = 0.72 Hz (DC gain 1 -> Vout_dc = VREF)
    output HPF f3  = 1 / (2 pi RL Cout)        = 21 Hz @ 16R, 11 Hz @ 32R with 470u
    VREF       f4  = 1 / (2 pi (10k||10k) 47u) = 0.68 Hz
"""

import sys

from kicaddy.schematic import run

# channel: (y0, op-amp unit, (out, -, +) pins, Rb, Rf, Rg, Rbleed, Cin, Cg, Cout)
CHANNELS = [
    (40, 1, ("1", "2", "3"), "R1", "R2", "R3", "R4", "C1", "C2", "C3"),
    (84, 2, ("7", "6", "5"), "R5", "R6", "R7", "R8", "C4", "C5", "C6"),
]


def channel(s, y0, unit, pins, rb, rf, rg, rbl, cin, cg, cout):
    out, inv, ninv = (f"U1.{p}" for p in pins)
    s.symbol("U1", "Amplifier_Operational:NJM4556A", (90, y0), value="NJM4556A", unit=unit)
    s.symbol(cin, "Device:C", (72, y0 - 2), value="1u film", rotation=90)
    s.symbol(rb, "Device:R", (79, y0 - 8), value="100k")
    s.symbol(rf, "Device:R", (90, y0 + 8), value="10k", rotation=90)
    s.symbol(rg, "Device:R", (84, y0 + 13), value="10k")
    s.symbol(cg, "Device:C_Polarized", (84, y0 + 22), value="22u")
    s.symbol(cout, "Device:C_Polarized", (106, y0), value="470u", rotation=90)
    s.symbol(rbl, "Device:R", (113, y0 + 3), value="10k")

    s.wire(f"{cin}.2", ninv)
    s.wire(f"{rb}.2", (79, y0 - 2))
    s.wire(f"{rb}.1", (79, y0 - 13))
    s.label("VREF", (79, y0 - 13), spin="up")
    s.wire(inv, f"{rg}.1")
    s.wire((84, y0 + 8), f"{rf}.1")
    s.wire(f"{rf}.2", (100, y0 + 8), (100, y0))
    s.wire(out, f"{cout}.1")
    s.wire(f"{rg}.2", f"{cg}.1")
    s.wire(f"{cg}.2", (84, y0 + 28))
    s.power("GND", (84, y0 + 28))
    s.wire(f"{cout}.2", f"{rbl}.1")
    s.wire(f"{rbl}.2", (113, y0 + 9))
    s.power("GND", (113, y0 + 9))


def supply(s):
    s.symbol("BT1", "Device:Battery", (150, 50), value="9V")
    s.symbol("SW1", "Switch:SW_SPST", (158, 40), value="POWER")
    s.symbol("U1", "Amplifier_Operational:NJM4556A", (172, 50), value="NJM4556A", unit=3)
    s.symbol("C7", "Device:C", (180, 50), value="100n")
    s.symbol("C8", "Device:C_Polarized", (188, 50), value="100u")
    s.symbol("R9", "Device:R", (196, 45), value="10k")
    s.symbol("R10", "Device:R", (196, 55), value="10k")
    s.symbol("C9", "Device:C_Polarized", (204, 55), value="47u")

    s.wire("BT1.1", (150, 40), "SW1.1")
    s.wire("SW1.2", (196, 40), "R9.1")
    s.wire("BT1.2", (150, 60), (204, 60), "C9.2")
    for x, top, bot in [(170, "U1.8", "U1.4"), (180, "C7.1", "C7.2"), (188, "C8.1", "C8.2")]:
        s.wire((x, 40), top)
        s.wire(bot, (x, 60))
    s.wire("R9.2", "R10.1")
    s.wire("R10.2", (196, 60))
    s.wire((196, 50), (204, 50), "C9.1")
    s.wire((204, 50), (208, 50))
    s.label("VREF", (208, 50), spin="right")

    s.power("+9V", (176, 40))
    s.power("PWR_FLAG", (164, 40))
    s.power("GND", (150, 60))
    s.power("PWR_FLAG", (160, 60), rotation=180)


def build(s):
    for ch in CHANNELS:
        channel(s, *ch)

    # Input jack: tip = left, ring = right, sleeve = ground.
    s.symbol("J1", "Connector_Audio:AudioJack3", (55, 82), value="LINE IN", mirror="x")
    s.wire("J1.T", (64, 80), (64, 38), "C1.1")
    s.wire("J1.R", "C4.1")
    s.wire("J1.S", (62, 84), (62, 88))
    s.power("GND", (62, 88))

    # Headphone jack, facing left.
    s.symbol("J2", "Connector_Audio:AudioJack3", (130, 84), value="PHONES", rotation=180)
    s.wire("R4.1", (120, 40), (120, 82), "J2.T")
    s.wire("R8.1", "J2.R")
    s.wire("J2.S", (122, 86), (122, 90))
    s.power("GND", (122, 90))

    supply(s)

    s.note("Stereo headphone amp, 9 V battery, 16-32 R phones; U1 = NJM4556A (70 mA out)\n"
           "Non-inverting, biased at VREF = 9 V / 2 = 4.5 V (R9/R10, C9)\n"
           "G = 1 + Rf/Rg = 1 + 10k/10k = 2 (6 dB);  Zin = Rb = 100k\n"
           "f_in = 1/(2 pi Rb Cin) = 1.6 Hz;  f_Rg = 1/(2 pi Rg Cg) = 0.72 Hz (DC gain 1)\n"
           "f_out = 1/(2 pi RL Cout) = 21 Hz @ 16 R, 11 Hz @ 32 R (Cout = 470u)\n"
           "Out swing ~ +/-3.5 V pk; current limit 70 mA -> 39 mW @ 16 R, 78 mW @ 32 R\n"
           "R4/R8 hold the jack side of Cout at 0 V (no plug-in pop)\n"
           "Rb = R1/R5, Rf = R2/R6, Rg = R3/R7, Cin = C1/C4, Cg = C2/C5, Cout = C3/C6",
           (142, 96))

    return [
        {"J1.T", "C1.1"},
        {"J1.R", "C4.1"},
        {"C1.2", "R1.2", "U1.3"},
        {"C4.2", "R5.2", "U1.5"},
        {"R1.1", "R5.1", "R9.2", "R10.1", "C9.1"},
        {"U1.2", "R2.1", "R3.1"},
        {"U1.6", "R6.1", "R7.1"},
        {"U1.1", "R2.2", "C3.1"},
        {"U1.7", "R6.2", "C6.1"},
        {"R3.2", "C2.1"},
        {"R7.2", "C5.1"},
        {"C3.2", "R4.1", "J2.T"},
        {"C6.2", "R8.1", "J2.R"},
        {"J1.S", "J2.S", "C2.2", "C5.2", "R4.2", "R8.2", "BT1.2", "U1.4", "C7.2", "C8.2",
         "R10.2", "C9.2"},
        {"BT1.1", "SW1.1"},
        {"SW1.2", "U1.8", "C7.1", "C8.1", "R9.1"},
    ]


if __name__ == "__main__":
    sys.exit(run(build, "headphone_amp", page="A4", title="Stereo headphone amplifier, 9 V, NJM4556A",
                 comments=("G = 1 + Rf/Rg = 2; VREF = 4.5 V; Cout 470u -> 21 Hz @ 16 R",)))
