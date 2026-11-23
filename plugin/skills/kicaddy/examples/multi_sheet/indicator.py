"""Sheet `indicator`: one LED on +5V, one on VIN (the supply sheet's global label).

A sheet module, as supply.py.
"""

GLOBAL = {
    "+5V": {"R1.1"},
    "VIN": {"R2.1"},
    "GND": {"D2.1", "D3.1"},
}
LOCAL = [{"R1.2", "D2.2"}, {"R2.2", "D3.2"}]
UNDRIVEN = {"+5V", "GND"}  # power symbols here, driven on the supply sheet


def draw(s):
    s.symbol("R1", "Device:R", (20, 35), value="1k")
    s.symbol("D2", "Device:LED", (20, 44), value="5V green", rotation=90)  # anode up
    s.symbol("R2", "Device:R", (40, 35), value="4.7k")
    s.symbol("D3", "Device:LED", (40, 44), value="VIN red", rotation=90)
    for ref, x in (("D2", 24), ("D3", 44)):
        s.field(ref, "Value", at=(x, 44))  # right of the LED's arrows, not across them

    s.power("+5V", (20, 30))
    s.wire((20, 30), "R1.1")
    s.global_label("VIN", (34, 32), spin="left")
    s.wire((34, 32), "R2.1")
    for r, d, x in (("R1", "D2", 20), ("R2", "D3", 40)):
        s.wire(f"{r}.2", f"{d}.2")
        s.wire(f"{d}.1", (x, 50))
        s.power("GND", (x, 50))

    s.note("I_D2 = (5 V - 2.1 V) / 1k = 2.9 mA\n"
           "I_D3 = (11.6 V - 1.9 V) / 4.7k = 2.1 mA", (16, 56))
