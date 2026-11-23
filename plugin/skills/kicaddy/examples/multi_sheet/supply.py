"""Sheet `supply`: 9-12 V barrel jack, reverse-polarity Schottky, L7805 to 5 V.

A sheet module: draw(s) draws the sheet; GLOBAL, LOCAL and UNDRIVEN describe its nets for build.py (the
project) and bench.py (this sheet alone beside stubs).
"""

# nets that leave the sheet, by name (a global label or a power symbol of that name): their pins on this sheet
GLOBAL = {
    "VIN": {"D1.1", "C1.1", "U1.1"},
    "+5V": {"U1.3", "C2.1"},
    "GND": {"J1.2", "C1.2", "U1.2", "C2.2"},
}
LOCAL = [{"J1.1", "D1.2"}]  # nets only on this sheet
UNDRIVEN = set()  # GLOBAL nets nothing on this sheet drives: on the bench their stub gets a PWR_FLAG


def draw(s):
    s.symbol("J1", "Connector:Barrel_Jack", (20, 40), value="9-12V DC")
    s.symbol("D1", "Diode:1N5819", (34, 38), value="1N5819", mirror="y")  # anode left, to the jack
    s.symbol("C1", "Device:C_Polarized", (42, 41), value="100u 25V")
    s.symbol("U1", "Regulator_Linear:L7805", (54, 38), value="L7805")
    s.symbol("C2", "Device:C", (66, 41), value="100n")

    s.wire("J1.1", "D1.2")
    s.wire("D1.1", "C1.1", "U1.1")
    s.wire("U1.3", "C2.1", (74, 38))
    s.power("+5V", (74, 38))
    for pin, x in (("J1.2", 26), ("C1.2", 42), ("U1.2", 54), ("C2.2", 66)):
        s.wire(pin, (x, 47))
        s.power("GND", (x, 47))

    # VIN leaves the sheet for the indicator; the jack and the diode drive nothing, so VIN and GND get flags
    s.wire((46, 38), (46, 32))
    s.global_label("VIN", (46, 32), spin="up")
    s.wire((39, 38), (39, 34))
    s.power("PWR_FLAG", (39, 34))
    s.wire((26, 45), (30, 45))
    s.power("PWR_FLAG", (30, 45))

    s.note("VIN = 9-12 V - 0.4 V (D1)\n"
           "U1: 5 V, 1 A max; C1 bulk, C2 output", (20, 54))
