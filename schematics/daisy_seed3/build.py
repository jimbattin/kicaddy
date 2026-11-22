#!/usr/bin/env python3
"""Daisy Seed3 demo: a custom 40-pin symbol (absent from the stock libraries) placed and wired through the normal
builder. Barrel jack on VIN, line in and line out jacks on the codec pins, a pot on A0 fed from +3V3A, and an LED
on D7.

The symbol library `daisy.kicad_sym` and its `sym-lib-table` row in this directory come from the pin table:

    kicaddy symbol plugin/skills/kicaddy/examples/daisy_seed3.json --dir schematics/daisy_seed3

    I_LED = (3.3 V - 2 V) / 1k = 1.3 mA
"""

import sys

from kicaddy.schematic import run

USED = {"8", "16", "17", "18", "19", "20", "21", "22", "39", "40"}


def build(s):
    s.symbol("U1", "daisy:Daisy_Seed3", (110, 75), value="Daisy_Seed3",
             datasheet="https://daisy.nyc3.cdn.digitaloceanspaces.com/products/seed3/Daisy_Seed3_datasheet.pdf",
             fields={"Manufacturer": "Daisy (Qu-Bit Electronix)"})
    s.field("U1", "Value", at=(121, 105))

    # VIN from a barrel jack
    s.symbol("J1", "Connector:Barrel_Jack", (70, 36), value="9V DC")
    s.wire("J1.1", (108, 34), "U1.39")
    s.power("+9V", (80, 34))
    s.power("PWR_FLAG", (88, 34))
    s.wire("J1.2", (80, 38), (80, 41), (84, 41))
    s.power("GND", (80, 41))
    s.power("PWR_FLAG", (84, 41))

    # line in (J2) and line out (J3)
    s.symbol("J2", "Connector_Audio:AudioJack3", (60, 50), value="Line in", mirror="x")
    s.symbol("J3", "Connector_Audio:AudioJack3", (60, 63), value="Line out", mirror="x")
    s.wire("J2.T", (95, 48), (95, 57), "U1.16")
    s.wire("J2.R", (93, 50), (93, 59), "U1.17")
    s.wire("J2.S", (66, 52), (66, 54))
    s.power("GND", (66, 54))
    s.wire("J3.T", "U1.18")
    s.wire("J3.R", "U1.19")
    s.wire("J3.S", (66, 65), (66, 67))
    s.power("GND", (66, 67))

    # pot on A0, fed from the codec's analog 3.3 V
    s.symbol("RV1", "Device:R_Potentiometer", (84, 80), value="10k")
    s.wire("RV1.2", (95, 80), (95, 65), "U1.22")
    s.label("3V3A", "RV1.1", spin="up")
    s.label("3V3A", "U1.21", spin="up")
    s.wire("RV1.3", (84, 86))
    s.power("GND", (84, 86))

    # LED on D7
    s.symbol("R1", "Device:R", (128, 71), value="1k", rotation=90)
    s.symbol("D1", "Device:LED", (138, 71), value="Red", rotation=180)
    s.wire("U1.8", "R1.1")
    s.wire("R1.2", "D1.2")
    s.wire("D1.1", (144, 71), (144, 74))
    s.power("GND", (144, 74))

    # AGND and DGND joined (datasheet)
    s.wire("U1.20", (109, 107), (111, 107), "U1.40")
    s.power("GND", (110, 107))

    unused = [str(n) for n in range(1, 41) if str(n) not in USED]
    for n in unused:
        s.no_connect(f"U1.{n}")

    return [
        {"J1.1", "U1.39"},
        {"J1.2", "J2.S", "J3.S", "RV1.3", "D1.1", "U1.20", "U1.40"},
        {"J2.T", "U1.16"},
        {"J2.R", "U1.17"},
        {"J3.T", "U1.18"},
        {"J3.R", "U1.19"},
        {"U1.21", "RV1.1"},
        {"RV1.2", "U1.22"},
        {"U1.8", "R1.1"},
        {"R1.2", "D1.2"},
        *({f"U1.{n}"} for n in unused),
    ]


if __name__ == "__main__":
    sys.exit(run(build, "daisy_seed3", page="A4", title="Daisy Seed3 demo",
                 comments=("Custom symbol daisy:Daisy_Seed3 from plugin/skills/kicaddy/examples/daisy_seed3.json",)))
