"""Draw the headphone-amp schematic (one channel) with schemdraw."""
import schemdraw
import schemdraw.elements as elm

OUT = '/tmp/hpamp-5b58fe37d9f1/hpamp_schematic'
YR = 10.5      # +9 V rail of the amplifier
YG = -1.2      # ground-symbol level of the output stage
YFB = -3.0     # feedback run (below the output-stage grounds)
FS = 15        # label font size
LBL = dict(loc='bot', ofst=0.25)   # for vertical parts: label on the right

schemdraw.config(fontsize=FS, lw=1.8)
d = schemdraw.Drawing(show=False)

# ================= input =================
YIN = 7.5
j1 = d.add(elm.AudioJack(ring=False).right().anchor('tip').at((2.2, YIN)))
d.add(elm.Label().at((0.3, YIN + 0.75)).label('J1  LINE / PHONE IN', halign='left', fontsize=FS - 1))
d.add(elm.Ground().at(j1.sleeve))
d.add(elm.Line().at(j1.tip).to((4.5, YIN)))
rv = d.add(elm.Potentiometer().at((4.5, YIN)).down().length(3.5))
d.add(elm.Ground())
d.add(elm.Label().at((4.95, rv.tap[1] - 0.55)).label('RV1\n10k log\n(volume)', halign='left', valign='top'))
c1 = d.add(elm.Capacitor().at(rv.tap).right().length(3.5).label('C1\n1µ film', loc='top', ofst=0.15))
inp = c1.end
d.add(elm.Dot())
d.add(elm.Resistor().at(inp).down().length(3).label('R1\n100k', **LBL))
d.add(elm.Line().down().length(0.5))
d.add(elm.Line().left().length(0.6))
d.add(elm.Tag().left().label('VREF', fontsize=FS - 2))
d.add(elm.Line().at(inp).right().length(5))

# ================= op-amp =================
# flip=True puts '+' (in2) on top; the 'vs' anchor is then the top (V+) pin.
op = d.add(elm.Opamp(leads=True, flip=True).anchor('in2').at(d.here))
xm, yop = op.in1[0], op.out[1]
d.add(elm.Line().at(op.vs).toy(YR))
d.add(elm.Dot())
d.add(elm.Vdd().at((op.vs[0], YR)).label('+9 V'))
d.add(elm.Label().at((op.vs[0] + 0.25, yop + 1.2)).label('U1A\n½ NE5532', halign='left', valign='bottom'))
d.add(elm.Line().at(op.vd).down().length(0.8))
d.add(elm.Ground())
for a, txt, dx, dy, ha, va in ((op.vs, '8', 0.15, 0.15, 'left', 'bottom'),
                               (op.vd, '4', 0.15, -0.15, 'left', 'top'),
                               (op.in2, '3', 0.1, 0.1, 'left', 'bottom'),
                               (op.in1, '2', 0.1, -0.1, 'left', 'top'),
                               (op.out, '1', -0.15, 0.1, 'right', 'bottom')):
    d.add(elm.Label().at((a[0] + dx, a[1] + dy))
          .label(txt, fontsize=FS - 4, halign=ha, valign=va))

# inverting input -> junction J; R9 + C3 to ground on the left
J = (xm, 0.8)
d.add(elm.Line().at(op.in1).to(J))
d.add(elm.Dot())
d.add(elm.Resistor().at(J).left().length(2.6).label('R9  4.7k', loc='top', ofst=0.15))
d.add(elm.Capacitor(polar=True).down().length(2.2).label('C3\n22µ', loc='bot', ofst=0.25))
d.add(elm.Ground())

# ================= class-AB buffer =================
xd = op.out[0] + 4.0
d.add(elm.Line().at(op.out).to((xd, yop)))
d.add(elm.Dot())
b1n, b2n = (xd, yop + 3.2), (xd, yop - 3.2)
d.add(elm.Dot().at((xd, YR)))
d.add(elm.Resistor().at((xd, YR)).to(b1n).label('R4\n1k', loc='top', ofst=0.25))
d.add(elm.Dot())
d.add(elm.Diode().at(b1n).to((xd, yop)).label('D1\n1N4148', loc='top', ofst=0.25))
d.add(elm.Diode().at((xd, yop)).to(b2n).label('D2\n1N4148', loc='top', ofst=0.25))
d.add(elm.Dot())
d.add(elm.Resistor().at(b2n).to((xd, YG)).label('R5\n1k', loc='top', ofst=0.25))
d.add(elm.Ground())

d.add(elm.Line().at(b1n).right().length(1.5))
q1 = d.add(elm.BjtNpn(circle=True).anchor('base').label('Q1\nBD139', loc='right', ofst=0.15))
d.add(elm.Line().at(q1.collector).toy(YR))
d.add(elm.Line().at((op.vs[0], YR)).to((q1.collector[0], YR)))      # +9 V rail
xe = q1.emitter[0]
outn = (xe, yop)
d.add(elm.Resistor().at(q1.emitter).to(outn).label('R6\n2.2Ω', **LBL))
d.add(elm.Dot())
d.add(elm.Line().at(b2n).right().length(1.5))
q2 = d.add(elm.BjtPnp(circle=True).anchor('base').label('Q2\nBD140', loc='right', ofst=0.15))
d.add(elm.Resistor().at(outn).to(q2.emitter).label('R7\n2.2Ω', **LBL))
d.add(elm.Line().at(q2.collector).toy(YG))
d.add(elm.Ground())

# ================= output =================
xf = xe + 2.2
d.add(elm.Line().at(outn).to((xf, yop)))
d.add(elm.Dot())
c4 = d.add(elm.Capacitor(polar=True).at((xf, yop)).right().length(3.5)
           .label('C4\n1000µ 16V', loc='top', ofst=0.15))
hp = c4.end
d.add(elm.Dot())
d.add(elm.Resistor().at(hp).down().length(3).label('R10\n1k', **LBL))
d.add(elm.Ground())
d.add(elm.Line().at(hp).right().length(2.5))
j2 = d.add(elm.AudioJack(ring=False).anchor('tip').at(d.here).left().flip())
d.add(elm.Label().at((j2.tip[0] - 0.2, j2.tip[1] + 0.55))
      .label('J2  PHONES\n16–32 Ω', halign='left', valign='bottom'))
d.add(elm.Ground().at(j2.sleeve))

# ================= feedback (runs under the grounds) =================
xa = xf - 3.0
xb = xa - 3.5
d.add(elm.Line().at((xf, yop)).to((xf, YFB)))
d.add(elm.Line().at((xf, YFB)).to((xa, YFB)))
d.add(elm.Dot())
d.add(elm.Resistor().at((xa, YFB)).to((xb, YFB)).label('R8  10k', loc='top', ofst=0.15))
d.add(elm.Dot())
d.add(elm.Line().at((xa, YFB)).down().length(1.6))
d.add(elm.Capacitor().left().length(3.5).label('C5  100p', loc='bot', ofst=0.15))
d.add(elm.Line().up().length(1.6))
d.add(elm.Line().at((xb, YFB)).to((xm, YFB)))
d.add(elm.Line().at((xm, YFB)).to(J))

# ================= power + VREF (bottom left, joined by net labels) =================
YP = -7.5
b1 = d.add(elm.Battery().at((0.5, YP - 4.5)).up().length(3).reverse()
           .label('B1\n9 V', loc='bot', ofst=0.3))
d.add(elm.Label().at(b1.end).label('+', ofst=(-0.45, -0.35)))
d.add(elm.Ground().at(b1.start))
d.add(elm.Line().at(b1.end).to((0.5, YP)))
sw = d.add(elm.Switch().at((0.5, YP)).right().length(2.5).label('SW1', loc='top'))
d.add(elm.Line().at(sw.end).to((11.5, YP)))
d.add(elm.Vdd().at((11.5, YP)).label('+9 V'))
for x, el, lab in ((4.0, elm.Capacitor(polar=True), 'C9\n100µ'),
                   (6.0, elm.Capacitor(), 'C10\n100n')):
    d.add(elm.Dot().at((x, YP)))
    d.add(el.at((x, YP)).down().length(3).label(lab, **LBL))
    d.add(elm.Ground())
d.add(elm.Dot().at((8.0, YP)))
d.add(elm.Resistor().at((8.0, YP)).down().length(3).label('R2\n100k', **LBL))
vref = (8.0, YP - 3)
d.add(elm.Dot())
d.add(elm.Resistor().down().length(3).label('R3\n100k', **LBL))
d.add(elm.Ground())
d.add(elm.Line().at(vref).right().length(2.2))
d.add(elm.Dot())
d.add(elm.Capacitor(polar=True).down().length(3).label('C2\n47µ', **LBL))
d.add(elm.Ground())
d.add(elm.Line().at((10.2, vref[1])).right().length(1.0))
d.add(elm.Tag(height=1.1).right().label('VREF\n4.5 V', fontsize=FS - 2))

# ================= notes =================
note = (
    'Headphone amplifier, 9 V single supply. Left channel shown; the right channel\n'
    'is identical using U1B (pins 5, 6, 7) and shares B1, SW1, C9, C10, R2, R3, C2.\n'
    '\n'
    'Gain   Av = 1 + R8/R9 = 1 + 10k/4.7k = 3.1  (+9.8 dB); feedback is taken after\n'
    '           R6/R7, so the Q1/Q2 buffer sits inside the loop.\n'
    'Bias   VREF = 9 V·R3/(R2+R3) = 4.5 V;  I(R4) = I(R5) ≈ (4.5 − 0.65) V / 1k ≈ 3.9 mA;\n'
    '           D1 + D2 ≈ 2·VBE  →  Iq(Q1, Q2) ≈ 5 mA.\n'
    'Poles  R1·C1: 1.6 Hz   R9·C3: 1.5 Hz (DC gain = 1)   R8·C5: 160 kHz\n'
    '           RL·C4: 10 Hz @ 16 Ω, 5 Hz @ 32 Ω    fc = 1/(2πRC)\n'
    'ngspice  2.2 Vpk ≈ 150 mW into 16 Ω, 2.5 Vpk ≈ 95 mW into 32 Ω before clipping;\n'
    '           idle supply ≈ 9 mA per channel.'
)
d.add(elm.Label().at((14.0, YP + 0.6)).label(note, halign='left', valign='top', fontsize=FS - 1.5))

d.save(OUT + '.svg')
d.save(OUT + '.png', dpi=92)
print('saved')
