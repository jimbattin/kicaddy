#!/usr/bin/env python3
"""Stereo headphone amplifier, 9 V battery, NJM4556A (70 mA output dual op-amp).

Per channel (non-inverting, single supply, AC coupled):
    Vref     = 9 V * R10 / (R9 + R10)          = 4.5 V   (C9 10 uF: Rth 23.5k -> 0.68 Hz)
    f_in     = 1 / (2 pi R1 C1) = 1/(2 pi 100k 1u) = 1.6 Hz
    G        = 1 + R3 / R5      = 1 + 10k/10k      = 2 (+6 dB); DC gain 1 via C3
    f_fb     = 1 / (2 pi R5 C3) = 1/(2 pi 10k 10u)  = 1.6 Hz
    f_out    = 1 / (2 pi R_L C5) = 9.9 Hz (16 R), 5.0 Hz (32 R) with 1000 uF
    P_max    : I_out 70 mA pk -> 32 R: 2.24 V pk, 78 mW; 16 R: 1.12 V pk, 39 mW
"""

import sys

from kicaddy.schematic import run

DY = 60  # vertical offset of the left channel below the right channel


def channel(s, unit, cin, rf, rg, cg, cout, rbl, dy):
    """One amplifier channel; the op-amp unit sits at (100, 40 + dy)."""
    y = 40 + dy
    s.symbol("U1", "Amplifier_Operational:NJM4556A", (100, y), value="NJM4556A", unit=unit)
    s.symbol(cin, "Device:C", (70, y - 2), value="1u", rotation=90)
    s.symbol(rf, "Device:R", (100, y + 10), value="10k", rotation=90)
    s.symbol(rg, "Device:R", (90, y + 15), value="10k")
    s.symbol(cg, "Device:C_Polarized", (90, y + 23), value="10u")
    s.symbol(cout, "Device:C_Polarized", (125, y), value="1000u", rotation=90)
    s.symbol(rbl, "Device:R", (135, y + 6), value="1k")
    s.power("GND", (90, y + 28))
    s.power("GND", (135, y + 12))

    plus, minus, out = ("U1.3", "U1.2", "U1.1") if unit == 1 else ("U1.5", "U1.6", "U1.7")
    s.wire(f"{cin}.2", plus)  # coupling cap to + input, bias resistor tees in at x = 80
    s.wire(minus, (90, y + 2), (90, y + 10), f"{rf}.1")
    s.wire((90, y + 10), f"{rg}.1")
    s.wire(f"{rg}.2", f"{cg}.1")
    s.wire(f"{cg}.2", (90, y + 28))
    s.wire(f"{rf}.2", (110, y + 10), (110, y))
    s.wire(out, f"{cout}.1")
    s.wire(f"{cout}.2", (135, y))
    s.wire((135, y), f"{rbl}.1")
    s.wire(f"{rbl}.2", (135, y + 12))
    s.junction((80, y - 2), (90, y + 10), (110, y), (135, y))


def build(s):
    channel(s, 1, "C1", "R3", "R5", "C3", "C5", "R7", 0)    # right channel (ring)
    channel(s, 2, "C2", "R4", "R6", "C4", "C6", "R8", DY)   # left channel (tip)

    # Bias resistors from each + input to the shared Vref node at (80, 76)
    s.symbol("R1", "Device:R", (80, 45), value="100k")
    s.symbol("R2", "Device:R", (80, 90), value="100k")
    s.wire((80, 38), "R1.1")
    s.wire("R1.2", (80, 76), "R2.1")
    s.wire("R2.2", (80, 98))

    # Vref divider and filter
    s.symbol("R9", "Device:R", (60, 70), value="47k")
    s.symbol("R10", "Device:R", (60, 82), value="47k")
    s.symbol("C9", "Device:C_Polarized", (68, 82), value="10u")
    s.power("+9V", (60, 64))
    s.power("GND", (60, 88))
    s.power("GND", (68, 88))
    s.wire((60, 64), "R9.1")
    s.wire("R9.2", "R10.1")
    s.wire((60, 76), (80, 76))
    s.wire((68, 76), "C9.1")
    s.wire("R10.2", (60, 88))
    s.wire("C9.2", (68, 88))
    s.junction((60, 76), (68, 76), (80, 76))

    # Input jack (pins up: S x-2, R x0, T x+2)
    s.symbol("J1", "Connector_Audio:AudioJack3", (20, 70), value="Line in", rotation=90)
    s.power("GND", (10, 62))
    s.wire("J1.R", (20, 38), "C1.1")
    s.wire("J1.T", (22, 62), (30, 62), (30, 98), "C2.1")
    s.wire("J1.S", (18, 58), (10, 58), (10, 62))

    # Output jack (pins up); left channel loops round the right side to the tip
    s.symbol("J2", "Connector_Audio:AudioJack3", (170, 75), value="Phones", rotation=90)
    s.wire((135, 40), (170, 40), "J2.R")
    s.wire((135, 100), (180, 100), (180, 67), (172, 67), "J2.T")
    s.wire("J2.S", (168, 69), (156, 69), (156, 74))
    s.power("GND", (156, 74))

    # Supply: battery, switch, decoupling, op-amp power unit
    s.symbol("BT1", "Device:Battery", (20, 125), value="9V")
    s.symbol("SW1", "Switch:SW_SPST", (28, 117), value="Power")
    s.symbol("C7", "Device:C_Polarized", (44, 124), value="100u")
    s.symbol("C8", "Device:C", (50, 124), value="100n")
    s.symbol("U1", "Amplifier_Operational:NJM4556A", (60, 125), value="NJM4556A", unit=3)
    s.wire("BT1.1", (20, 117), "SW1.1")
    s.wire("SW1.2", (58, 117), "U1.8")
    s.wire((58, 117), (66, 117), (66, 114))
    s.power("PWR_FLAG", (66, 114))
    s.wire((38, 117), (38, 114))
    s.power("+9V", (38, 114))
    s.wire((44, 117), "C7.1")
    s.wire((50, 117), "C8.1")
    s.wire("C7.2", (44, 131))
    s.wire("C8.2", (50, 131))
    s.wire("U1.4", (58, 134))
    s.wire("BT1.2", (20, 133))
    s.wire((20, 131), (14, 131), (14, 128))
    s.power("PWR_FLAG", (14, 128))
    for x, y in [(44, 131), (50, 131), (58, 134), (20, 133)]:
        s.power("GND", (x, y))
    s.junction((38, 117), (44, 117), (50, 117), (58, 117), (20, 131))

    s.note("RIGHT (ring)", (100, 30))
    s.note("LEFT (tip)", (100, 90))
    s.note("Stereo headphone amp, 9 V battery, 16-32 ohm phones, line/phone input\n"
           "Vref = 9 V x R10/(R9+R10) = 4.5 V (C9 filters, 0.7 Hz)\n"
           "G = 1 + R3/R5 = 1 + 10k/10k = 2 (+6 dB); C3 makes DC gain 1\n"
           "f_in = 1/(2pi R1 C1) = 1.6 Hz;  f_fb = 1/(2pi R5 C3) = 1.6 Hz\n"
           "f_out = 1/(2pi RL C5) = 9.9 Hz @ 16 ohm, 5 Hz @ 32 ohm\n"
           "NJM4556A 70 mA pk: 78 mW @ 32 ohm, 39 mW @ 16 ohm\n"
           "R7/R8 hold jack side at 0 V (no plug-in pop)", (100, 124))

    return [
        {"J1.S", "J2.S", "C3.2", "C4.2", "R7.2", "R8.2", "R10.2", "C9.2",
         "C7.2", "C8.2", "U1.4", "BT1.2"},
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
                 comments=("G = 1 + R3/R5 = 2, Vref = 4.5 V, Cout 1000 uF",
                           "Drawn through the KiCad IPC API (headless kicad-cli api-server)")))
