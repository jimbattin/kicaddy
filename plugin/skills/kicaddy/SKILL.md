---
name: kicaddy
description: Create KiCad schematics (.kicad_sch/.kicad_pro) from a Python build script, headless through KiCad's IPC API - place library symbols, wire by pin, check the netlist against declared intent and ERC, render a cropped PNG. Use to draw, design, or build a new schematic; not for reviewing or analyzing an existing one.
---

# kicaddy: headless KiCad schematics from a build script

## Setup

Run once per session:

```sh
python3 "$(realpath skill://kicaddy)/../../bin/kicaddy" doctor
```

Outside omp, replace `$(realpath skill://kicaddy)` with the directory containing this file.

On success the last line is `cli:   python3 /…/bin/kicaddy`. That command line is `kicaddy` everywhere below;
reuse it verbatim for the rest of the session.

On a `FAIL` line:

- `kicad` or `api-server`: kicaddy needs a KiCad 10.99 nightly or later (stable 10.0.x has no headless API
  server). Ask the user which KiCad to use: an AppImage, a `kicad-cli` binary, an install directory, an app
  bundle, or `flatpak[:APP_ID]`. Run `kicaddy config kicad <choice>`, then rerun `kicaddy doctor`.
- `venv`: `uv` is missing; ask the user to install it (https://docs.astral.sh/uv/).
- `bindings`: needs `git` and network access (first run per KiCad build).
- `server`: show the user the message.

## Workflow

1. **Pin offsets.** `kicaddy pins Lib:Sym …` (e.g. `kicaddy pins Device:R Timer:NE555P`) prints each pin's
   unit, number, name, offset from the symbol origin in grid units at rotation 0, and electrical type.
   Look up every symbol you will place, in one call, before laying anything out. Symbols that do not exist are
   left out of the output; when none exist it fails with `none of the requested items were found`. The library
   files are not searchable on disk; these IDs exist in the stock libraries:
   - `Device:` `R`, `C`, `C_Polarized`, `L`, `D`, `LED`, `R_Potentiometer`, `R_Potentiometer_Dual`, `Q_NPN`,
     `Q_PNP`, `Q_NMOS`, `Q_PMOS`, `Battery`, `Battery_Cell`, `Speaker`
   - `Amplifier_Operational:` `NE5532`, `TL072`, `LM358`, `NJM4556A` (dual, 70 mA output);
     `Amplifier_Audio:LM386`; `Timer:NE555P`; `Regulator_Linear:L7805`
   - `Transistor_BJT:` `BC547`, `BC557`, `BD139`, `BD140`; `Diode:` `1N4148`, `1N4001`
   - `Connector_Audio:AudioJack3`, `Connector:Barrel_Jack`, `Connector_Generic:Conn_01x02` (`…x03`, …),
     `Switch:SW_SPST`, `Switch:SW_Push`
   - `power:` `GND`, `+5V`, `+9V`, `+12V`, `VCC`, `PWR_FLAG` (through `s.power`)
2. **Net intent.** Write down the expected nets (sets of `"REF.PIN"`) before any layout. This list is what
   `build()` returns and what the build checks against.
3. **Layout on the grid.** Pick a page, place symbols so that the pins you connect line up on X or Y, and route
   orthogonal wires between them (see Geometry and Rules).
4. **Build.** Write `build.py` in the user's project directory, then run `kicaddy run build.py [--out DIR]`. It
   prints every net, the ERC violations with positions, and the output paths. Exit 0 only when the netlist
   matches the declared nets and ERC reports 0 violations; on `NETLIST MISMATCH` it lists missing and
   unexpected nets.
5. **Review.** Read `<name>_crop.png` (or the tiles `<name>_crop_r<r>c<c>.png` for a large drawing). Fix
   overlaps, crossings, and unreadable text in `build.py`, and rebuild. Two or three build-and-review rounds
   are normal; stop when the image is clean.

## Build script contract

A design script defines `build(s)` that places symbols and wires on a grid and returns the nets it expects;
`run()` does the rest: headless server, save, connectivity check, ERC, plots, cropped PNG.

```python
import sys

from kicaddy.schematic import run


def build(s):
    s.symbol("R1", "Device:R", (40, 30), value="10k")  # pins 1 (40, 27) and 2 (40, 33)
    s.no_connect("R1.1")
    s.power("GND", (40, 36))
    s.power("PWR_FLAG", (44, 36))  # GND is fed only by passive pins
    s.wire("R1.2", (40, 36), (44, 36))
    return [{"R1.1"}, {"R1.2"}]  # expected nets as sets of "REF.PIN"; power-symbol pins are ignored


if __name__ == "__main__":
    sys.exit(run(build, "my_design", page="A4", title="My design"))
```

Coordinates are in units of the 1.27 mm connection grid, Y down. A point given as `"REF.PIN"` resolves to that
pin's connection point (pin number, not name).

- `run(build, name, page="A4", title="", comments=(), out_dir=None)`: entry point for a design script. Exit
  status 1 on netlist mismatch or any ERC violation. `page` is one of `A5 A4 A3 A2 A B` (`A`, `B`: ANSI);
  the sheet is landscape. `comments` fill up to 4 title-block comment lines. The command-line option `--out DIR`
  overrides `out_dir`; the default is the script's directory.
- `build(s)` returns a list of sets of `"REF.PIN"`, one set per net. Power-symbol and `PWR_FLAG` pins are
  excluded. A pin connected to nothing (including every pin with a `no_connect`) is its own single-pin set.
- Outputs, in the output directory: `<name>.kicad_sch`, `<name>.kicad_pro`, `<name>.png`, `<name>.svg`,
  `<name>.pdf`, and the crop `<name>_crop.png` (or tiles).

Methods on `s`:

- `s.symbol(ref, lib_id, at, value=None, rotation=0, unit=None, footprint=None)`: place a library symbol with
  its origin at grid point `at`; returns `{pin number: (x, y)}`. Each pin is also available as `"REF.PIN"`
  (and in `s.pins`). Fails if a pin lands off the connection grid.
- `s.power(name, at, rotation=0)`: place `power:<name>` (`GND`, `+5V`, `+9V`, `PWR_FLAG`, …) with an automatic
  `#PWR`/`#FLG` reference; its pin is at `at`. Returns the reference.
- `s.wire(*points)`: polyline through grid points and/or `"REF.PIN"` names; one wire segment per leg. Legs must
  be horizontal or vertical and non-zero.
- `s.junction(*points)`: a junction dot at each point.
- `s.label(text, at, spin="right")`: local net label; `spin` is the side the text extends to: `left`, `right`,
  `up`, `bottom`.
- `s.no_connect(at)`: no-connect marker on an unused pin (`"REF.PIN"`).
- `s.note(text, at, size=1.27)`: left-aligned text; `size` in mm; `\n` for new lines.

## Geometry

- 1 unit = 1.27 mm, Y down. Pins are addressed by number, not name.
- Connection point = symbol position + T(pin offset), where `rotation` turns the symbol counter-clockwise on
  screen:

  | `rotation` | T(x, y) |
  |---|---|
  | `0` | (x, y) |
  | `90` | (y, −x) |
  | `180` | (−x, −y) |
  | `270` | (−y, x) |

- Multi-unit symbols (e.g. a dual op-amp): place each unit with the same `ref` and `unit=1`, `unit=2`, …;
  they become `U1A`, `U1B`, … of one `U1`. The dual op-amps above have 3 units: 1 and 2 are the amplifiers,
  3 carries V+ and V−; place unit 3 too and wire its supply pins. In `kicaddy pins` output, unit `0` or `*`
  means the pin is in every unit. Address a pin as `"U1.<pin number>"` after placing the unit that has it.
- The crop is one image when the drawn content, including text, the note, and power symbols, fits in about
  205 × 150 grid units; anything larger comes out as tiles. Lay out for one image unless the circuit cannot fit.
- Page sizes in grid units (landscape): A5 165×116, A4 233×165, A3 330×233, A 220×170, B 340×220. Keep 8 units
  clear at each edge (frame) and the bottom-right 87×28 (title block).

## Rules that keep the build and image clean

- Wires are orthogonal.
- Add a `junction` at every T and wherever a wire ends on the middle of another wire; the builder adds none.
- Keep values short: library field positions can collide with pins (`100k log` on a potentiometer overlapped a
  pin number).
- `Device:Q_NMOS` / `Q_PMOS` gates are input pins: drive a gate net from an output or passive pin, or ERC
  reports `Input pin not driven`. These symbols have three pins (D, G, S) and no bulk pin.
- Put a `PWR_FLAG` on each supply net fed only by passive pins (a battery, a connector), or ERC reports the
  power input pins as not driven. The example flags both battery nets.

## Example

`skill://kicaddy/examples/ne555_blinker.py`: NE555 astable LED blinker on A5 with power flags, junctions,
rotation, and a note. Build it with `kicaddy run <path> --out <dir>`. Read it before writing `build.py`; you do
not need the engine source.
