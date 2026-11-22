---
name: kicaddy
description: Draw, build, or edit KiCad schematics headless from Python (not for reviewing or analyzing one) - a build script places library symbols and wires them by pin through KiCad's IPC API, with hierarchical sheets and custom symbols from a pin table; the netlist is checked against declared intent, with ERC, a layout lint, and cropped PNG renders. With the kicaddy tools, also edit an existing schematic (add, move, remove parts, change values, rename nets) with the netlist change checked.
---

# kicaddy: headless KiCad schematics from a build script

## Setup

`kicaddy` below is this command line (outside omp, replace `$(realpath skill://kicaddy)` with the directory
containing this file):

```sh
python3 "$(realpath skill://kicaddy)/../../bin/kicaddy"
```

- With the kicaddy tools (next section) there is no setup step. A tool that cannot start names the command to
  run (`python3 /…/bin/kicaddy doctor`): run it, then call the tool again.
- Without them, run `kicaddy doctor` once per session. On success its last line is
  `cli:   python3 /…/bin/kicaddy`, the same command line with the path resolved; reuse it verbatim.

On a `FAIL` line from `doctor`:

- `kicad` or `api-server`: kicaddy needs a KiCad 10.99 nightly or later (stable 10.0.x has no headless API
  server). Ask the user which KiCad to use: an AppImage, a `kicad-cli` binary, an install directory, an app
  bundle, or `flatpak[:APP_ID]`. Run `kicaddy config kicad <choice>`, then rerun `kicaddy doctor`.
- `venv`: `uv` is missing; ask the user to install it (https://docs.astral.sh/uv/).
- `bindings`: needs `git` and network access (first run per KiCad build).
- `server`: show the user the message.

## kicaddy tools (omp extension)

When the `kicaddy_build` tool is available, the plugin's extension keeps one KiCad server warm for the session:

- **Build** with `kicaddy_build` (`script`, optional `out`: the output directory) instead of
  `kicaddy run`: same output, files, and exit line (`exit: 0`), without a server start per build.
- **Review** with `kicaddy_render` (optional `sheet`: a file stem) instead of reading `<stem>_crop.png`: it
  plots the crops again and returns them as images.
- **Query** with `kicaddy_query`, `what` =
  - `pins` with `lib_ids`: library pin offsets, as `kicaddy pins`; works before any project is open.
  - `symbols`: one line per placed symbol (sheet, reference, library id, value, origin, `rot`/`mirror` when
    set). With `refs` (a list of references), only those, each followed by its pin points on the sheet: look
    there before wiring to a part of an opened project.
  - `nets` (`REF.PIN` sets) and `erc`.

  `kicaddy_open` opens an existing project (directory, `.kicad_pro`, or root `.kicad_sch`) for query, render,
  and edit.
- **Edit** with `kicaddy_edit`: `code` is Python run as one batch against the open project, `s` the sheet
  (`sheet`: file stem, default the root), `sheets` maps stems to sheets, `project` the project. Before the batch
  the model is loaded from the document, so `s.pins["R5.1"]` holds every pin, built or opened. The builder
  methods work as in `build.py` (`s.symbol`, `s.wire`, `s.label`, `s.power`, ...), except `s.sheet`,
  `s.net_class`, and `commit()`. Items already in the document can also be changed:
  - `s.move(ref, at, unit=None)`: translate the symbol so its origin is `at` (no rotation); returns the new
    pins. A wire ending on a pin follows it (stretched, or with one dog-leg corner); labels and no-connect
    markers on its pins move with it; a power symbol alone on a pin moves too; any other contact gets a stub
    wire from the old pin point. Move before wiring new items to its pins in the same batch.
  - `s.remove(ref, unit=None)`: delete every unit of `ref` on the sheet (or one unit) and the no-connect
    markers on its pins; its wires and labels stay.
  - `s.remove_wire(a, b)`: delete the wires lying on the straight run from `a` to `b` (points or `"REF.PIN"`);
    a wire reaching past either end is refused, so pass its full extent.
  - `s.remove_label(text, at=None)`, `s.remove_no_connect(at)`: local or global labels; no-connect markers.
  - `s.field(ref, name, text="330")`: change a field's text (not `Reference`; remove and place instead).
  - `project.rename_net("/VPP_ON", "VPP_EN")`: give the local or global labels naming that net (full name, as
    `kicaddy_query nets` prints it) the new text. A net named by a power symbol is refused.
  These work only on items in the document when the batch started; a symbol placed in the batch is placed at
  its final position instead.
- **`expect`** declares the netlist change of a batch. Always pass it; `{}` for a layout-only change. It is
  required for projects from `kicaddy_open`; when the change differs, the batch is dropped and the saved files
  are reopened. Keys, all optional:
  - `add` `{ref: value}`, `remove` `[ref]`, `values` `{ref: new value}`;
  - `connect` `{"C8.1": target}`: the pin joins `target`, a `"REF.PIN"`, an existing net name, or a new net
    name; `disconnect` `["R5.1"]`;
  - `rename` `{"/VPP_ON": "/VPP_EN"}` (full net names).
  Pins of added parts left unconnected need not be declared.
- A committed batch saves the files and reports `netlist: …` (component and net changes, or `unchanged`),
  `expect: matched`, and the ERC and LINT totals with the issues the batch added. Any exception drops the whole
  batch and leaves the document unchanged. For a project from `kicaddy_build`, a rebuild discards batches, so
  copy every change you keep into `build.py` (the source of truth), then rebuild once at the end. For a project
  from `kicaddy_open`, the saved files are the only copy of the batches.
- While a project is open, `edit`/`write` on its `.kicad_sch`/`.kicad_pro` are blocked, and `kicaddy run` on the
  same directory fails as busy: use the tools.

Without the tools, the CLI workflow below is unchanged.

## Workflow

1. **Pin offsets.** `kicaddy pins Lib:Sym …` (e.g. `kicaddy pins Device:R Timer:NE555P`) prints each pin's
   unit, number, name, offset from the symbol origin in grid units at rotation 0, and electrical type.
   Look up every symbol you will place, in one call, before laying anything out. An id that does not exist
   gets a line `not found: Timer:NE555 (Timer has NE555P, NE555D, …)` with the closest names in that library
   (or the closest library names), and the exit status is 1: pick from that line instead of guessing again.
   The library files are not searchable on disk; these IDs exist in the stock libraries:
   - `Device:` `R`, `C`, `C_Polarized`, `L`, `D`, `LED`, `R_Potentiometer`, `R_Potentiometer_Dual`, `Q_NPN`,
     `Q_PNP`, `Q_NMOS`, `Q_PMOS`, `Battery`, `Battery_Cell`, `Speaker`
   - `Amplifier_Operational:` `NE5532`, `TL072`, `LM358`, `NJM4556A` (dual, 70 mA output);
     `Amplifier_Audio:LM386`; `Timer:NE555P`; `Regulator_Linear:L7805`
   - `Transistor_BJT:` `BC547`, `BC557`, `BD139`, `BD140`; `Diode:` `1N4148`, `1N4001`
   - `Connector_Audio:AudioJack3`, `Connector:Barrel_Jack`, `Connector_Generic:Conn_01x02` (`…x03`, …),
     `Switch:SW_SPST`, `Switch:SW_Push`
   - `power:` `GND`, `+5V`, `+9V`, `+12V`, `VCC`, `PWR_FLAG` (through `s.power`)
2. **Custom symbols.** For a part that `kicaddy pins` leaves out, write a pin table (one symbol per JSON file;
   example: `skill://kicaddy/examples/daisy_seed3.json`, a 40-pin module) and run
   `kicaddy symbol table.json … --dir <project dir>`, where the project dir is the `build.py` directory or its
   `--out` dir. It merges the symbol into `<library>.kicad_sym` there, adds the library to that directory's
   `sym-lib-table`, loads it through KiCad, and prints its pin offsets as `kicaddy pins` does. Place it as
   `library:name`; `kicaddy pins --dir <project dir> library:name` reprints the offsets later. Table keys:
   - `library`, `name` (required): letters, digits, `_ . + -`. A library name already in `sym-lib-table`
     with another file is refused.
   - `reference` (default `U`), `value` (default `name`), `footprint`, `datasheet`, `description`, and
     `fields` (extra hidden fields, e.g. `{"Manufacturer": "..."}`; not the five mandatory names).
   - `pins` (required): objects `{"numbers": ["1"], "name": "D0", "type": "bidirectional"}` (or
     `"number": 1`); `base.pinout` from a `datasheets/extracted/<MPN>.json` can be pasted as is. Names have no
     spaces (`""` for none). Types: `input`, `output`, `bidirectional`, `tri_state`, `passive`,
     `open_collector`, `open_emitter`, `power_in`, `power_out`, `unspecified`, `free`, `no_connect`
     (or `not_connected`). Each object is placed at its first number; further numbers are stacked on it,
     hidden (the same net).
   - `sides` (optional): `{"top": [...], "bottom": [...], "left": [...], "right": [...]}` of first numbers,
     each pin object exactly once; `left`/`right` run top to bottom, `top`/`bottom` left to right. Without it
     the layout is DIP: the first half down the left, the rest up the right (pin 1 top left, the last pin top
     right). Group by function: power on top, grounds on the bottom, inputs left, outputs right.

   A bad table prints one `error: <file>: <key>: …` line (e.g. `pins[3].numbers`, `sides.left[0]`,
   `fields.MPN`) with the expected shape and the value found, exits 1, and writes nothing: fix that key and
   rerun. `KiCad could not load the library: …` means KiCad rejected the written file.
3. **Net intent.** Write down the expected nets (sets of `"REF.PIN"`) before any layout. This list is what
   `build()` returns and what the build checks against.
4. **Layout on the grid.** Pick a page, place symbols so that the pins you connect line up on X or Y, and route
   orthogonal wires between them (see Geometry and Rules). Put everything the drawing needs in this first
   `build.py`: the note right next to the circuit (not at a far edge of the page), and any section titles.
5. **Build.** Write `build.py` in the user's project directory, then run `kicaddy run build.py [--out DIR]`. It
   prints every net (`net <name> <pins>`; pins connected to nothing share one `unconnected:` line), the ERC
   violations with positions, `LINT: n issue(s)` with one line per layout issue, and the output paths. Exit 0
   only when the netlist matches the declared nets, ERC reports 0 violations, and LINT reports 0 issues; on
   `NETLIST MISMATCH` it lists missing and unexpected nets. A failing build writes no plots, removes the
   earlier ones, and prints `plots: none (the build failed)`. An ERC line ends in
   `on <sheet path>` (`/` for the root, `/amp/` for child sheet `amp`). A LINT line reads
   `<sheet path> kind: a / b @ (x, y)` (grid units on that sheet, the centre of the clash); kinds:
   - `body-body`: two symbol bodies (or sheet boxes) overlap.
   - `text-text`: two texts overlap (fields such as `R1.Value`, labels, notes).
   - `text-body`: a text overlaps another symbol's body.
   - `text-pin`: a pin runs through a text.
   - `text-wire`: a wire runs through a text (a label on its own wire is fine).
   - `wire-body`: a wire runs through a symbol body it is not attached to.
   - `wire-pin`: a wire runs along a pin or crosses it away from its connection point.

   Names in LINT lines: `R1.Value` (a field), `label 'X'`, `global 'X'`, `hier 'X'` (labels), `note (x, y)`,
   `sheet <name>` (a child sheet's box), `sheet <name>.Sheetname` / `.Sheetfile` (its fields), and
   `sheet pin <name>.<label>`.
6. **Review.** Fix every LINT line in `build.py` and rebuild before looking at any image: move the symbol,
   wire, label, or note, or move a field with `s.field(ref, "Value", at=...)`. Once LINT is 0, read each sheet's
   `<stem>_crop.png` (or the tiles `<stem>_crop_r<r>c<c>.png` for a large drawing) once. LINT 0 already means
   no overlaps; the review looks only for what LINT cannot see: text that sits closer to the wrong part than to
   its own, or a crop split into tiles. If the image has neither, stop: do not rebuild to add decorations, to
   nudge text that does not touch anything, or to tighten spacing. Aim for one image review.

## Build script contract

A design script defines `build(s)` that places symbols and wires on the root sheet, adds child sheets, and
returns the nets it expects; `run()` does the rest: headless server, project scaffold, save, connectivity check,
ERC, plots, cropped PNGs.

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
  status 1 on netlist mismatch, any ERC violation, or any LINT issue; the schematic files are saved either
  way, the plots only on exit status 0.
  `page` is one of `A5 A4 A3 A2 A B` (`A`, `B`: ANSI); the sheet is landscape. `comments` fill up to 4
  title-block comment lines. The command-line option `--out DIR` overrides `out_dir`; the default is the
  script's directory.
- `build(s)` returns a list of sets of `"REF.PIN"`, one set per net, for the whole project (every sheet).
  Power-symbol and `PWR_FLAG` pins are excluded. A pin connected to nothing (including every pin with a
  `no_connect`) is its own single-pin set.
- Outputs, in the output directory:
  - `<name>.kicad_pro`, `<name>.kicad_sch` (root sheet), and one `<sheet>.kicad_sch` per child sheet,
    rewritten on every build.
  - `<name>.kicad_pcb`: an empty board, created on the first build and never overwritten.
  - `sym-lib-table`, `fp-lib-table`: project-local library tables, created empty only if absent;
    `sym-lib-table` keeps the rows `kicaddy symbol` added.
  - `<library>.kicad_sym`: written only by `kicaddy symbol`, kept by `kicaddy run`.
  - `datasheets/`, `analysis/`: empty directories for kicad-happy.
  - Per sheet (`<stem>` = `<name>` for the root, the sheet name for a child): `<stem>.png`, `<stem>.svg`, and
    the crop `<stem>_crop.png` (or tiles).
  - `<name>.pdf`: every sheet, one page each.
  - The plots (PNG, SVG, crop, PDF) exist only after a build that exits 0.
- Every sheet gets the same title block (date, revision 1, `comments`); a child's title is its `title`.

Methods on `s`:

- `s.symbol(ref, lib_id, at, value=None, rotation=0, unit=None, footprint=None, mirror=None, datasheet=None,
  fields=None)`: place a library symbol with its origin at grid point `at`; returns `{pin number: (x, y)}`.
  `(ref, unit)` is unique across the project; the units of one symbol may sit on different sheets (e.g. the
  amplifiers on one sheet, the supply unit on another).
  Each pin is also available as `"REF.PIN"` (and in `s.pins`). Fails if a pin lands off the connection grid.
  `mirror="x"` flips the symbol top-bottom, `mirror="y"` left-right (see Geometry). `datasheet` sets the
  Datasheet field; `fields` is a dict of extra hidden fields, e.g. `{"MPN": "RC0603FR-0710KL",
  "Manufacturer": "Yageo"}` (not `Reference`, `Value`, `Footprint`, `Datasheet`, `Description`).
- `s.field(ref, name, at=None, visible=None, unit=None)`: move a field of a placed symbol to grid point `at`
  (half units such as `(40, 33.5)` are fine) and/or show or hide it. `name` is `Reference`, `Value`,
  `Footprint`, `Datasheet`, `Description`, or a name from `fields`. Pass `unit=` for a multi-unit symbol.
  Call it after `s.symbol`.
- `s.power(name, at, rotation=0)`: place `power:<name>` (`GND`, `+5V`, `+9V`, `PWR_FLAG`, …) with an automatic
  `#PWR`/`#FLG` reference; its pin is at `at`, a grid point or `"REF.PIN"`. Returns the reference.
- `s.wire(*points)`: polyline through grid points and/or `"REF.PIN"` names; one wire segment per leg. Legs must
  be horizontal or vertical and non-zero.
- `s.label(text, at, spin="right")`: local net label; `spin` is the side the text extends to: `left`, `right`,
  `up`, `bottom`.
- `s.global_label(text, at, spin="right", shape="passive")`: global net label, same `spin`; `shape` is `input`,
  `output`, `bidirectional`, `tri_state`, or `passive`.
- `s.no_connect(at)`: no-connect marker on an unused pin (`"REF.PIN"`).
- `s.note(text, at, size=1.27)`: left-aligned text; `size` in mm; `\n` for new lines. Multi-line notes are
  centred vertically on `at`.
- `s.junction(*points)`: explicit dot for a deliberate four-way connection; T junctions are automatic.
- `s.sheet(name, build, at, size, pins=None, page=None, title=None)`: child sheet, drawn as a box with its
  top-left corner at `at` and `size` (w, h) in grid units; returns `{label: (x, y)}` of its sheet pins.
  - `name`: letters, digits, `_`, `-`; it is also the file name `<name>.kicad_sch`, so it is unique in the
    project and differs from the project name.
  - `build(child)` draws the child sheet with the same methods as `s` and returns nothing; the root `build`
    returns every net in the project. `page` defaults to the project's page; `title` to `name`.
  - Sheet pins come from the child's `hier_label`s, one per distinct text, with the label's `shape`.
    Automatic (`pins=None`): `output` labels on the right edge, all others on the left, in the order the
    labels were created, at offsets 2, 4, 6, … from the top edge; a side with n pins needs height ≥ 2n + 2.
    Explicit: `pins={label: (side, offset)}` with one entry per label; `side` is `left`, `right`, `top`, or
    `bottom`; `offset` is an integer counted from the top edge (left, right) or the left edge (top, bottom),
    strictly inside the edge.
  - Each pin is addressable on the parent as `"<sheet>.<LABEL>"`, e.g. `s.wire("J1.T", "amp.IN_L")`. The pin
    text is drawn inside the box; the name is above the box and the file name below it, at `x`.
  - Child sheets can contain sheets.
- `s.hier_label(text, at, spin="right", shape="input")`: hierarchical label on a child sheet (fails on the
  root): connects the net at `at` to the parent's sheet pin `text`. `spin` and `shape` as for `global_label`.
  The label text and pin name are the same. A net named by a hierarchical label prints as
  `<sheet path><text>` (`/amp/IN_L`); a net with several labels takes one of their names.
- `s.net_class(name, nets, track_width=None, clearance=None)`: project net class, from any sheet. `nets` is a
  list of net-name patterns matched against full net names: `"+9V"`, `"GND"`, `"/amp/OUT_L"`, with `*`
  wildcards (`"/amp/*"`). `track_width` and `clearance` in mm; unset values inherit from `Default`.
  `name` must be new and not `Default`. Saved in `<name>.kicad_pro`.

## Geometry

- 1 unit = 1.27 mm, Y down. Pins are addressed by number, not name.
- Connection point = symbol position + M(T(pin offset)): `rotation` turns the symbol counter-clockwise on
  screen, then `mirror` flips the result: `"x"` top-bottom, M(x, y) = (x, −y); `"y"` left-right,
  M(x, y) = (−x, y).

  | `rotation` | T(x, y) |
  |---|---|
  | `0` | (x, y) |
  | `90` | (y, −x) |
  | `180` | (−x, −y) |
  | `270` | (−y, x) |

  Example: offset (−4, 0) at `rotation=90, mirror="x"` → T = (0, 4) → M = (0, −4).
- Fields move with the symbol when it is mirrored; `s.field(..., at=...)` takes absolute grid points.
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
- Junction dots are automatic wherever 3 or more wire directions or pins meet, including a wire end or a pin
  on the middle of another wire. A pin or wire end that touches the middle of a wire connects to it, so route
  wires around pins they must not join. Two wires crossing middle to middle do not connect.
- A field that collides with a pin, wire, or another text: move it with `s.field(ref, "Value", at=...)`.
- Put the part number in `fields={"MPN": ..., "Manufacturer": ...}` and the datasheet URL in `datasheet=`
  when known.
- A global label alone on a one-pin net gives the ERC warning `Label connected to only one pin`.
- `Device:Q_NMOS` / `Q_PMOS` gates are input pins: drive a gate net from an output or passive pin, or ERC
  reports `Input pin not driven`. These symbols have three pins (D, G, S) and no bulk pin.
- Put a `PWR_FLAG` on each supply net fed only by passive pins (a battery, a connector), or ERC reports the
  power input pins as not driven. The example flags both battery nets.

## Example

`skill://kicaddy/examples/ne555_blinker.py`: NE555 astable LED blinker on A5 with power flags, automatic T
junctions, rotation, and a note. Build it with `kicaddy run <path> --out <dir>`. Read it before writing
`build.py`; you do not need the engine source.
