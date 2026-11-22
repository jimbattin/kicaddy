# Goal
Draw this fixed circuit as a KiCad schematic and a human-readable PNG; do not change the circuit.

# Circuit (fixed)
Stereo headphone amplifier, 9 V battery, NJM4556A dual op-amp. Use exactly these parts, values, and symbols:

| Ref | Symbol | Value | Notes |
|---|---|---|---|
| U1 | `Amplifier_Operational:NJM4556A` | NJM4556A | unit 1 = right channel, unit 2 = left channel, unit 3 = power |
| C1, C2 | `Device:C` | 1u | input coupling, right / left |
| R1, R2 | `Device:R` | 100k | input bias to Vref, right / left |
| R3, R4 | `Device:R` | 10k | feedback, right / left |
| R5, R6 | `Device:R` | 10k | gain-set to ground via C3 / C4 |
| C3, C4 | `Device:C_Polarized` | 10u | gain-set capacitors |
| C5, C6 | `Device:C_Polarized` | 1000u | output coupling, right / left |
| R7, R8 | `Device:R` | 1k | output bleed to ground |
| R9, R10 | `Device:R` | 47k | Vref divider |
| C9 | `Device:C_Polarized` | 10u | Vref filter |
| C7 | `Device:C_Polarized` | 100u | supply bulk |
| C8 | `Device:C` | 100n | supply decoupling |
| J1 | `Connector_Audio:AudioJack3` | Line in | |
| J2 | `Connector_Audio:AudioJack3` | Phones | |
| BT1 | `Device:Battery` | 9V | |
| SW1 | `Switch:SW_SPST` | Power | |

Nets (exactly these 16; every pin listed, sets of `REF.PIN`):

```
{J1.S, J2.S, C3.2, C4.2, R7.2, R8.2, R10.2, C9.2, C7.2, C8.2, U1.4, BT1.2}   ground
{SW1.2, C7.1, C8.1, U1.8, R9.1}                                              switched +9 V
{BT1.1, SW1.1}
{J1.R, C1.1}
{J1.T, C2.1}
{C1.2, R1.1, U1.3}
{C2.2, R2.2, U1.5}
{R1.2, R2.1, R9.2, R10.1, C9.1}                                              Vref
{U1.2, R3.1, R5.1}
{U1.6, R4.1, R6.1}
{R5.2, C3.1}
{R6.2, C4.1}
{U1.1, R3.2, C5.1}
{U1.7, R4.2, C6.1}
{C5.2, R7.1, J2.R}
{C6.2, R8.1, J2.T}
```

Put a `+9V` power symbol on the net of SW1.2 and `GND` power symbols on the ground net; add `PWR_FLAG` where needed.

# Common requirements
- Output: a schematic image (PNG) that a human can read: no overlapping parts, text or wires; junction dots at T connections; a short note on the drawing with key values or equations. Look at your own output image with the read tool and iterate until it is clean.

# Method
Use the kicaddy skill. Work only in the current directory.

# Final report
The output file paths; a circuit summary with values and reasoning; how you verified it; and the problems you hit along the way.
