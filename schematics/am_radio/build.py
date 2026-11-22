#!/usr/bin/env python3
"""AM broadcast-band (530-1700 kHz) receiver: ferrite loopstick tank, Schottky envelope detector,
LM386 audio amplifier, 9 V battery; drawn through the KiCad IPC API.

Tuned tank, L1 = 240 uH loopstick, C2 = 12-365 pF single-gang tuning capacitor. Strays, the
detector and the 10 pF antenna coupling cap C1 add ~20 pF, so the tank spans 32-385 pF:
    f = 1 / (2 pi sqrt(L C))
    f_low  = 1 / (2 pi sqrt(240 uH x 375 pF))  = 530 kHz   (C2 near 355 pF)
    f_high = 1 / (2 pi sqrt(240 uH x 36.5 pF)) = 1700 kHz  (C2 near 17 pF)
    range at C2 = 365 / 12 pF: 523 kHz ... 1.82 MHz, so the whole band is covered with margin.
C1 = 10 pF couples an optional long wire lightly (in series with the wire's ~100 pF it adds
< 10 pF) so it does not detune or damp the tank much.

Envelope detector: D1 BAT85 Schottky (V_F ~0.25 V at small current, like a germanium 1N34A).
RV1 = 100k log is both the detector DC load and the volume control; C3 = 330 pF across it:
    tau = 100k x 330 pF = 33 us  ->  audio corner 1 / (2 pi tau) = 4.8 kHz (AM audio <= 5 kHz)
    carrier period at 530 kHz = 1.9 us << tau, so the carrier ripple is filtered out.
C4 = 100 nF blocks the detector DC from the LM386 input (R_in 50k): f_c = 1 / (2 pi 50k 100n) = 32 Hz.

LM386 in the datasheet gain-20 configuration (pins 1 and 8 open), pin 2 grounded, C5 = 10 uF on
BYPASS for supply-ripple rejection, C6 = 100 nF + C7 = 100 uF supply decoupling.
Output: C8 = 220 uF to an 8 ohm speaker, f_c = 1 / (2 pi 8 x 220 uF) = 90 Hz; Zobel R3 = 10 ohm
+ C9 = 47 nF from pin 5 to ground keeps the amplifier stable into the inductive speaker.
"""

import sys

from kicaddy.schematic import run

DX, DY = 34, 16  # layout drawn around (70, 45); shifted to centre it above the A4 title block


def p(x, y):
    return (x + DX, y + DY)


def build(s):
    # antenna input and tuned tank
    s.symbol("J1", "Connector:Screw_Terminal_01x02", p(14, 32), value="ANT/EARTH", rotation=180)
    s.symbol("C1", "Device:C", p(24, 30), value="10p", rotation=90)
    s.symbol("L1", "Device:L_Ferrite", p(32, 36), value="240u loopstick")
    s.symbol("C2", "Device:C_Variable", p(42, 36), value="12-365p")
    # detector and volume
    s.symbol("D1", "Device:D_Schottky", p(53, 30), value="BAT85", rotation=180)
    s.symbol("C3", "Device:C", p(61, 36), value="330p")
    s.symbol("RV1", "Device:R_Potentiometer", p(72, 36), value="100k")  # log taper
    s.symbol("C4", "Device:C", p(79, 36), value="100n", rotation=90)
    # audio amplifier
    s.symbol("U1", "Amplifier_Audio:LM386", p(96, 38), value="LM386")
    s.symbol("C6", "Device:C", p(84, 26), value="100n")
    s.symbol("C5", "Device:C_Polarized", p(104, 29), value="10u")
    s.symbol("C8", "Device:C_Polarized", p(116, 38), value="220u", rotation=90)
    s.symbol("R3", "Device:R", p(108, 44), value="10")
    s.symbol("C9", "Device:C", p(108, 52), value="47n")
    s.symbol("LS1", "Device:Speaker", p(128, 38), value="8R")
    # battery
    s.symbol("BT1", "Device:Battery", p(20, 70), value="9V")
    s.symbol("C7", "Device:C_Polarized", p(30, 70), value="100u")

    for name, x, y in [("GND", 36, 44), ("GND", 61, 42), ("GND", 72, 42), ("GND", 88, 44),
                       ("GND", 94, 46), ("GND", 84, 30), ("GND", 104, 34), ("GND", 108, 57),
                       ("GND", 122, 44), ("+9V", 94, 20),
                       ("+9V", 20, 62), ("GND", 20, 78), ("PWR_FLAG", 40, 64), ("PWR_FLAG", 40, 76)]:
        s.power(name, p(x, y))

    # antenna, coupling cap, tank
    s.wire("J1.2", "C1.1")
    s.wire("J1.1", p(20, 32), p(20, 44), p(42, 44), "C2.2")
    s.wire("C1.2", "D1.2")
    s.wire("L1.1", p(32, 30))
    s.wire("C2.1", p(42, 30))
    s.wire("L1.2", p(32, 44))
    # detector, RC load / volume pot
    s.wire("D1.1", p(72, 30), "RV1.1")
    s.wire("C3.1", p(61, 30))
    s.wire("C3.2", p(61, 42))
    s.wire("RV1.3", p(72, 42))
    s.wire("RV1.2", "C4.1")
    s.wire("C4.2", "U1.3")
    s.wire("U1.2", p(88, 40), p(88, 44))
    s.wire("U1.4", p(94, 46))
    s.no_connect("U1.1")
    s.no_connect("U1.8")
    # supply and bypass
    s.wire("U1.6", p(94, 20))
    s.wire(p(94, 23), "C6.1")
    s.wire("C6.2", p(84, 30))
    s.wire("U1.7", p(96, 26), "C5.1")
    s.wire("C5.2", p(104, 34))
    # output, Zobel, speaker
    s.wire("U1.5", "C8.1")
    s.wire(p(108, 38), "R3.1")
    s.wire("R3.2", "C9.1")
    s.wire("C9.2", p(108, 57))
    s.wire("C8.2", "LS1.1")
    s.wire("LS1.2", p(122, 40), p(122, 44))
    # battery, bulk decoupling, power flags
    s.wire("BT1.1", p(20, 62))
    s.wire(p(20, 64), p(40, 64))
    s.wire(p(30, 64), "C7.1")
    s.wire("BT1.2", p(20, 78))
    s.wire(p(20, 76), p(40, 76))
    s.wire(p(30, 76), "C7.2")
    s.junction(*(p(x, y) for x, y in [(32, 30), (42, 30), (32, 44), (36, 44), (61, 30),
                                      (94, 23), (108, 38), (20, 64), (30, 64), (20, 76), (30, 76)]))

    s.note("AM receiver, 530-1700 kHz, 9 V battery\n"
           "Tank: f = 1 / (2 pi sqrt(L1 C)), L1 = 240 uH\n"
           "  f_low  = 1 / (2 pi sqrt(240 uH x 375 pF)) = 530 kHz\n"
           "  f_high = 1 / (2 pi sqrt(240 uH x 36.5 pF)) = 1700 kHz\n"
           "  C2 12-365 pF + ~20 pF strays/C1 = 32-385 pF: 1.82 MHz-523 kHz\n"
           "Detector D1 BAT85; RV1 (100k log volume) is its load:\n"
           "  tau = RV1 x C3 = 100k x 330 pF = 33 us, audio -3 dB 4.8 kHz\n"
           "C4: 1 / (2 pi x 50k R_in x 100 nF) = 32 Hz\n"
           "LM386 gain 20 (pins 1, 8 open); C8: 1 / (2 pi x 8R x 220 uF) = 90 Hz\n"
           "Zobel R3 + C9 = 10R + 47 nF", p(50, 64))

    return [
        {"J1.2", "C1.1"},
        {"C1.2", "L1.1", "C2.1", "D1.2"},
        {"J1.1", "L1.2", "C2.2", "C3.2", "RV1.3", "U1.2", "U1.4", "C5.2", "C6.2", "C9.2", "LS1.2",
         "BT1.2", "C7.2"},
        {"U1.1"},  # GAIN pins open: gain 20
        {"U1.8"},
        {"D1.1", "C3.1", "RV1.1"},
        {"RV1.2", "C4.1"},
        {"C4.2", "U1.3"},
        {"U1.7", "C5.1"},
        {"U1.6", "C6.1", "C7.1", "BT1.1"},
        {"U1.5", "C8.1", "R3.1"},
        {"R3.2", "C9.1"},
        {"C8.2", "LS1.1"},
    ]


if __name__ == "__main__":
    sys.exit(run(build, "am_radio", page="A4", title="AM broadcast-band receiver, LM386, 9 V battery",
                 comments=("Loopstick 240 uH + 12-365 pF tuning: 530-1700 kHz",
                           "Drawn through the KiCad IPC API (headless kicad-cli api-server)")))
