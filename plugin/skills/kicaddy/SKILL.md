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

A `warn  tested` line is not a failure: this KiCad build is not one the plugin's design corpus was rebuilt on.
Continue; if a build then fails in a way its output does not explain, tell the user the KiCad build is untested.

## kicaddy tools (omp extension)

When the `kicaddy_build` tool is available, the plugin's extension keeps one KiCad server warm for the session:

- **Build** with `kicaddy_build` (`script`, optional `out`: the output directory) instead of
  `kicaddy run`: same output, files, and exit line (`exit: 0`), without a server start per build.
- **Review** with `kicaddy_render` (optional `sheet`: a file stem) instead of reading `<stem>_crop.png`: it
  plots the crops again and returns them as images. With `around` (references on one sheet) or `box`
  (`[x0, y0, x1, y1]` in grid units, on `sheet`, default the root) it returns one image of that region instead:
  the parts with 12 units around them, grown to keep whole the parts, labels, notes, text boxes, tables and sheet
  boxes at its edge. Up to about 106 × 80 units is drawn at full size, up to 213 × 160 legibly. For a project
  from `kicaddy_open` the images are written to kicaddy's cache, not into the project: use the printed paths. It
  also works after a build that exited 1 (the files are saved either way): render the region of a LINT line you
  cannot resolve from its coordinates.
- **Query** with `kicaddy_query`, `what` =
  - `pins` with `lib_ids`: library pin offsets, body boxes and field positions, as `kicaddy pins`; works before
    any project is open: it then reads the `sym-lib-table` of the session directory, or of `dir` (a project
    directory, as `kicaddy pins --dir`), so the project's own `library:name` symbols are found.
  - `symbols`: one line per placed symbol (sheet, reference, library id, value, origin, `rot`/`mirror` when
    set, then the part flags that are set: `dnp`, `no-bom`, `no-board`). With `refs` (a list of references),
    only those, each followed by its pin points, its `body` box, and its fields on the sheet:
    `Value "102k 0.1%" at (40, 40) center box (36, 39.4)-(44, 40.6) horizontal` for a visible field (`at` is
    the anchor `s.field(at=…)` sets, then the alignment as read), `Footprint "…" hidden` for a hidden one. Look
    there before wiring to a part of an opened project or moving one of its fields.
  - `nets` (`REF.PIN` sets), `erc`, and `lint` (the `LINT:` block of a build, for the open project as it is).
  - `items`: what `symbols` leaves out of one sheet (`sheet`, default the root): `power <ref> <value> (x, y)`
    for power symbols and flags (the pin point), `wire (x1, y1)-(x2, y2)`, `junction`, `no-connect`,
    `label 'X' (x, y) right` (also `global`, `hier`), `note (x, y) "text"`, `text box (x0, y0)-(x1, y1) "text"`,
    `rectangle (x0, y0)-(x1, y1) dash` (a frame), `line (x1, y1)-(x2, y2)` (a graphic line), other shapes
    (`polygon`, `circle`, …) with their bounding box, `table (x0, y0)-(x1, y1) N columns, M cells`, and child
    `sheet` boxes. With `net` (a full name as `nets` prints it), only that net's power symbols, pins, wires,
    junctions and labels on the sheet. Use it instead of reading the `.kicad_sch` files or probing with a batch
    that raises.

  `sheet` (a file stem) limits `symbols`, `nets`, `erc` and `lint` to one sheet; a net line then lists that
  sheet's pins and ends with `+N on other sheets`.

  `kicaddy_open` opens an existing project (directory, `.kicad_pro`, or root `.kicad_sch`) for query, render,
  and edit. When the files were saved by another KiCad release (stable 10.0, say), its output has a
  `file format:` line and `kicaddy_edit` is refused: KiCad saves only its own format, so the first committed
  batch would rewrite every sheet in a format that release cannot open. Query and render change nothing. Tell
  the user, and only when they agree reopen with `upgrade: true`.
- **Edit** with `kicaddy_edit`: `code` is Python run as one batch against the open project, `s` the sheet
  (`sheet`: file stem, default the root), `sheets` maps stems to sheets, `project` the project. Before the batch
  the model is loaded from the document, so `s.pins["R5.1"]` holds every pin, built or opened. See what is on
  a sheet with `kicaddy_query items` and `symbols` with `refs`, not with a batch that prints and raises. The
  builder methods work as in `build.py` (`s.symbol`, `s.wire`, `s.label`, `s.power`, ...), except `s.sheet`,
  `s.net_class`, and `commit()`. Items already in the document can also be changed:
  - `s.move(ref, at, unit=None)`: translate the symbol so its origin is `at` (no rotation); returns the new
    pins. A wire ending on a pin follows it (stretched, or with one dog-leg corner); labels and no-connect
    markers on its pins move with it; a power symbol alone on a pin moves too; any other contact gets a stub
    wire from the old pin point. Move before wiring new items to its pins in the same batch.
  - `s.remove(ref, unit=None)`: delete every unit of `ref` on the sheet (or one unit) and the no-connect
    markers on its pins; its wires and labels stay. `s.move` and `s.remove` also take power symbols and flags
    (`#PWR0407`, `#FLG0401`). A junction an edit leaves with fewer than three connections is removed at commit.
  - `s.remove_wire(a, b)`: delete the wires lying on the straight run from `a` to `b` (points or `"REF.PIN"`);
    a wire reaching past either end is refused, so pass its full extent.
  - `s.remove_label(text, at=None)`, `s.remove_no_connect(at)`: local or global labels; no-connect markers.
  - `s.note_text(at, text)`, `s.remove_note(at)`: change the text of, or delete, the note or text box whose
    anchor `items` prints at `at` (a note's point, a text box's top-left corner); `expect` `{}`.
  - `s.field(ref, name, text="330")`: change a field's text (not `Reference`; remove and place instead).
  - `project.rename_net("/VPP_ON", "VPP_EN")`: give the local or global labels naming that net (full name, as
    `kicaddy_query nets` prints it) the new text. A net named by a power symbol is refused.
  These work only on items in the document when the batch started; a symbol placed in the batch is placed at
  its final position instead. `s.flags(ref, dnp=None, exclude_from_bom=None, exclude_from_board=None)`
  (Methods) works on both; a batch that only changes flags has `expect` `{}`.
- **`expect`** declares the netlist change of a batch. Always pass it; `{}` for a layout-only change. It is
  required for projects from `kicaddy_open`; when the change differs, the batch is dropped and the saved files
  are reopened. Keys, all optional:
  - `add` `{ref: value}`, `remove` `[ref]`, `values` `{ref: new value}`;
  - `connect` `{"C8.1": target}`: the pin joins `target`, a `"REF.PIN"`, an existing net name, or a new net
    name; `disconnect` `["R5.1"]`;
  - `rename` `{"/VPP_ON": "/VPP_EN"}` (full net names).
  Pins of added parts left unconnected need not be declared. A new net is named by connecting one of its pins
  to the full name (a local label `PRE_OUT` on sheet `power_analog` is `/power_analog/PRE_OUT`, a global label
  or power symbol its bare name) and the others to that pin.

  Inserting a part in series splits a net. `connect` alone declares the pin's whole net joined to the target,
  so list the pin that leaves under `disconnect` and connect to pins, not net names:

  ```python
  s.remove_wire("U1.3", "R3.1")          # U1.3 and R3.1 were one net
  s.symbol("R10", "Device:R", (105, 38), rotation=90, value="100")
  s.field("R10", "Reference", at=(105, 40))  # clear of the GND symbol's value above it
  s.wire("U1.3", "R10.1")
  s.wire("R10.2", "R3.1")
  ```

  `expect`: `{"add": {"R10": "100"}, "disconnect": ["R3.1"], "connect": {"R10.1": "U1.3", "R10.2": "R3.1"}}`.
  Without `disconnect` the batch is dropped and a `hint:` line says so.
- **`strict: true`** drops a batch that adds an ERC violation or a LINT line (`batch dropped: 1 new LINT line`,
  then the lines) and reopens the saved files, as for an `expect` mismatch.
- A committed batch saves the files and reports `netlist: …` (component and net changes, or `unchanged`), a
  `flags: <ref> <flags set, or none>` line per part whose flags changed, `expect: matched`, and the ERC and
  LINT totals with the issues the batch added. Any exception, or `exit()`, drops the whole batch and leaves the
  document unchanged. For a project from `kicaddy_build`, a rebuild discards batches, so copy every change you
  keep into `build.py` (the source of truth), then rebuild once at the end. For a project from `kicaddy_open`,
  the saved files are the only copy of the batches.
- While a project is open, `edit`/`write` on its `.kicad_sch`/`.kicad_pro` are blocked, and `kicaddy run` on the
  same directory fails as busy: use the tools.
- In omp the kicaddy tools are also commands of `bash`; these forms are all a session needs, no `--help`:
  `kicaddy_build build.py`, `kicaddy_render`, `kicaddy_query -j '{"what": "pins", "lib_ids": ["Device:R",
  "Device:C"]}'`, `kicaddy_query -j '{"what": "items", "sheet": "usb"}'`, and for a batch a JSON file with
  `code`, `sheet`, `expect` passed as `kicaddy_edit @batch.json`. Images come back only from a tool call (in
  eval: `await tool.kicaddy_render({"sheet": "usb"})`); `bash` prints the paths.

Without the tools, the CLI workflow below is unchanged.

## Workflow

1. **Pin offsets.** `kicaddy pins Lib:Sym …` (e.g. `kicaddy pins Device:R Timer:NE555P`) prints each pin's
   unit, number, name, offset from the symbol origin in grid units at rotation 0, and electrical type. After
   the pins come `unit N  body (x0, y0)-(x1, y1)`, the box that unit's drawing fills (`none` for a unit of pins
   only), and `Reference at (x, y) center vertical` / `Value at …`: each visible field's anchor, alignment and
   direction at rotation 0 (Geometry). Pins printed at the same offset are stacked: they share one connection
   point and one net. A project's own symbols may keep a field inside the body (`Value at (0, 3)` with
   `body (-4, -4)-(4, 4)`): move it with `s.field` on every placement.
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
   Write the note's equations with the references and values on the drawing (`Av = 1 + R3/R5 = 1 + 10k/4.7k =
   3.1`), not generic names (`Rf`, `Rg`, `Cout`) the reader cannot find on the sheet; one line per result, with
   its number.
5. **Build.** Write `build.py` in the user's project directory, then run `kicaddy run build.py [--out DIR]`. It
   prints every net (`net <name> <pins>`; pins connected to nothing share one `unconnected:` line), the ERC
   violations with positions, `LINT: n issue(s)` with one line per layout issue, and the output paths. Exit 0
   only when the netlist matches the declared nets, ERC reports 0 violations, and LINT reports 0 issues; on
   `NETLIST MISMATCH` it lists missing and unexpected nets, with a `hint:` line for each point where two wire
   ends meet on a crossing (Rules). A failing build writes no plots, removes the earlier ones, and prints
   `plots: none (the build failed)`. An ERC line ends in `on <sheet path>` (`/` for the root, `/amp/` for child
   sheet `amp`). A LINT line reads `<sheet path> kind: a / b @ (x, y)` (grid units on that sheet, the centre of
   the clash). A `text-*` line continues with `; <text> box (x0, y0)-(x1, y1) horizontal` (or `vertical`) for
   each text in it: the extent of that text on the sheet. That box is what has to clear the other item; take
   the distance to move from it. `s.field(ref, name, at=…)` places the field's anchor, which is the middle of
   the text only for a `center` field: `kicaddy pins` prints each field's alignment, and
   `kicaddy_query symbols` with `refs` the anchor and box of a placed one. `s.field(..., justify="center")`
   puts `at` in the middle of the box; `angle=0` turns a vertical field. Kinds:
   - `body-body`: two symbol bodies (or sheet boxes) overlap.
   - `text-text`: two texts overlap (fields such as `R1.Value`, labels, notes).
   - `text-body`: a text overlaps another symbol's body.
   - `text-own`: a symbol's own field crosses a line of its drawing (an LED's arrows, a capacitor's plates) or
     one of its own pin names or numbers (a Value moved inside an IC's body over its pin names).
     Move the field clear of the symbol.
   - `text-pin`: a pin runs through a text.
   - `text-wire`: a wire runs through a text (a label on its own wire is fine).
   - `wire-body`: a wire runs through a symbol body it is not attached to.
   - `wire-pin`: a wire runs along a pin or crosses it away from its connection point.

   Names in LINT lines: `R1.Value` (a field), `label 'X'`, `global 'X'`, `hier 'X'` (labels), `note (x, y)`,
   `text box (x, y)` (its frame is the box; nothing else may be inside it), `table (x, y)` (a table of an opened
   project, its outer box; nothing else may be inside it), `sheet <name>` (a child sheet's box),
   `sheet <name>.Sheetname` / `.Sheetfile` (its fields), and `sheet pin <name>.<label>`.
6. **Review.** Fix every LINT line in `build.py` and rebuild before looking at any image: move the symbol,
   wire, label, or note, or move a field with `s.field(ref, "Value", at=...)`. Once LINT is 0, read each sheet's
   `<stem>_crop.png` (or the tiles `<stem>_crop_r<r>c<c>.png` for a large drawing) once. LINT 0 already means
   no overlaps, including a field over its own symbol's lines. The review looks only for what a reader would
   misread and LINT cannot see: text that sits closer to another part than to its own, or a wrong fact in the
   note. A drawing that fits one image (Geometry) and still comes out as tiles is laid out too wide: fix it. A
   larger sheet is drawn in blocks that each fit one image; its tiles are expected, and the review reads each
   block once (`kicaddy_render` with `box` set to the block, or the tiles without the tools). This first clean
   build and its one review end the drawing work. Rebuild only to fix such a misreading, then read the crop
   once more; otherwise do not rebuild and do not read the crop again: no moving fields, parts, or wires that
   LINT passed, no rewording the note, no added decorations, no tighter spacing. These limits apply to your own
   review only: layout changes the user asks for are always made.
7. **Circuit check.** A build that exits 0 proves the drawing has the declared nets and passes ERC; it says
   nothing about how the circuit behaves. When the task asks for that too, check it in this order, from the
   output directory:
   - With the `kicad` and `spice` skills (kicad-happy) installed, simulate the saved schematic first; its test
     circuits are built from the drawing itself:

     ```sh
     python3 "$(realpath skill://kicad)/scripts/analyze_schematic.py" <name>.kicad_sch --analysis-dir analysis/
     python3 "$(realpath skill://spice)/scripts/simulate_subcircuits.py" --analysis-dir analysis/ --text
     python3 -c "import json,glob; d=json.load(open(sorted(glob.glob('analysis/*/spice.json'))[-1])); [print(r['subcircuit_type'], r['status'], ' '.join(r['components']), r.get('simulated') or r.get('note', '')) for r in d['simulation_results']]"
     ```

     The second command prints one summary line; the third prints each subcircuit it recognised, its status,
     and its measured values. It looks for common blocks in the netlist (RC and LC filters, dividers, op-amp
     stages, regulators, crystals, transistor stages, decoupling, …), so what it covers depends on the circuit:
     a block missing from the list was not simulated, a `skip` was not measured, and a detection can be wrong.
     Check each line against the circuit before citing it. Example, a headphone amp: it measured the RC corners
     and the bias divider, skipped four RC pairs, reported two bias resistors as a divider, saw only the
     op-amp's power unit (so no gain stage), and could not simulate the output into the headphones, which are
     not in the schematic.
   - Write your own ngspice deck, one in the output directory, only for behaviour the task needs that the list
     does not cover (or for everything, without kicad-happy). Size the effort to the task. When that behaviour
     is the purpose of the design (a filter's response, an oscillator's frequency, a regulator's output), get
     the deck to run and measure it; if it still fails after a few fixes, report it as not simulated. When it
     only confirms hand calculations, run `ngspice -b` at most twice, then stop.
   - Report what was simulated, with the numbers, and what was not.

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
    s.power("PWR_FLAG", (44, 36))  # GND is fed only by passive pins; GND's value is below, the flag's above
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
  fields=None, dnp=None, exclude_from_bom=None, exclude_from_board=None)`: place a library symbol with its
  origin at grid point `at`; returns `{pin number: (x, y)}`.
  `(ref, unit)` is unique across the project; the units of one symbol may sit on different sheets (e.g. the
  amplifiers on one sheet, the supply unit on another).
  Each pin is also available as `"REF.PIN"` (and in `s.pins`). Fails if a pin lands off the connection grid.
  `mirror="x"` flips the symbol top-bottom, `mirror="y"` left-right (see Geometry). `datasheet` sets the
  Datasheet field; `fields` is a dict of extra hidden fields, e.g. `{"MPN": "RC0603FR-0710KL",
  "Manufacturer": "Yageo"}` (not `Reference`, `Value`, `Footprint`, `Datasheet`, `Description`).
  `dnp`, `exclude_from_bom`, `exclude_from_board` (`True` or `False`) set the part's flags: do not populate,
  leave out of the BOM, leave off the board. `None` keeps the library symbol's own (`Mechanical:MountingHole`
  is excluded from the BOM unless you pass `exclude_from_bom=False`). The units of one symbol share the flags.
  A part excluded from the board keeps its pins in kicaddy's netlist (the build check, a batch's `netlist:`),
  but the `kicad-cli` netlist export a board is updated from leaves it out.
- `s.field(ref, name, at=None, visible=None, unit=None, angle=None, justify=None)`: move a field of a placed
  symbol to grid point `at` (half units such as `(40, 33.5)` are fine), show or hide it, turn it (`angle`: `0`
  horizontal or `90` vertical, as read on the sheet, whatever the symbol's rotation), and align it (`justify`:
  `"left"` the text starts at `at`, `"center"`, `"right"` it ends there; vertical text reads upwards, so it
  starts at its lower end). `name` is `Reference`, `Value`, `Footprint`, `Datasheet`, `Description`, or a name
  from `fields`. Pass `unit=` for a multi-unit symbol. Call it after `s.symbol`.
- `s.flags(ref, dnp=None, exclude_from_bom=None, exclude_from_board=None)`: set (`True`) or clear (`False`) the
  flags of a placed symbol, on every unit of it; `None` leaves one as it is.
- `s.power(name, at, rotation=0, symbol=None)`: place `power:<name>` (`GND`, `+5V`, `+9V`, `PWR_FLAG`, …) with
  an automatic `#PWR`/`#FLG` reference; its pin is at `at`, a grid point or `"REF.PIN"`. Returns the reference.
  The number continues the sheet's own (`#PWR0408` on a sheet whose highest is `#PWR0407`; a sheet with none
  continues the project's highest), written as KiCad annotates power symbols, with a 0 before it.
  With `symbol="VCC"` (any `power:` symbol) it places that symbol and sets its Value to `name`, which names the
  net: `s.power("CM5_3V3", p, symbol="VCC")`; ERC and `PWR_FLAG` rules are those of `+5V`: on a net no power
  output drives, the power symbol needs a `PWR_FLAG` (a global label does not). A power symbol and a global label
  of the same name are one net across sheets.
- `s.wire(*points)`: polyline through grid points and/or `"REF.PIN"` names; one wire segment per leg. Legs must
  be horizontal or vertical and non-zero.
- `s.label(text, at, spin="right")`: local net label; `at` is a grid point or `"REF.PIN"`, as for `s.power`;
  `spin` is the side the text extends to: `left`, `right`, `up`, `bottom`.
- `s.global_label(text, at, spin="right", shape="passive")`: global net label, same `at` and `spin`; `shape` is
  `input`, `output`, `bidirectional`, `tri_state`, or `passive`.
- `s.no_connect(at)`: no-connect marker on an unused pin (`"REF.PIN"`).
- `s.note(text, at, size=1.27)`: left-aligned text; `size` in mm; `\n` for new lines. Multi-line notes are
  centred vertically on `at`. At the default size text is about 0.85 units per character (0.8 lower case, 0.95
  digits and capitals) and lines are 1.6 units apart: 100 characters are about 85 units wide. Field values and
  labels have the same size. A note does not wrap: break lines yourself, or use `s.text_box`.
- `s.text_box(text, at, size, text_size=1.27, border=True)`: framed text that KiCad wraps; `at` is the top-left
  corner, `size` (w, h) in grid units. A line holds about (w − 1.5) / 0.85 characters and lines are 1.6 units
  apart: n lines need h ≥ 1.6 n + 1. Text longer than the box runs out below the frame and LINT does not see
  that: size the box. LINT takes the frame as the text's box. A full-sheet crop is too coarse to judge text
  against the frame: render the box with `kicaddy_render` and `box`. `border=False` saves a frameless box; this
  KiCad's plots still draw the frame.
- `s.rectangle(a, b, style="dash")`: a frame from corner `a` to corner `b` around a block; `style` is `solid`,
  `dash`, `dot`, `dashdot`, or `dashdotdot`. LINT ignores frames, also a wire or text crossing the frame line.
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
  - A project of several sheets: one module per sheet (`draw(s)` plus its nets), a root that places them, and
    a bench that builds one sheet alone beside stubs (a global label and test point per net that leaves it,
    a `PWR_FLAG` where nothing on the sheet drives the net): `skill://kicaddy/examples/multi_sheet/`. Get each
    sheet clean on its bench, then build the root.
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
- Fields turn and mirror with the symbol: a field whose anchor `kicaddy pins` prints at (x, y) sits at symbol
  position + M(T(x, y)), and one that reads horizontally at rotation 0 reads vertically at 90 and 270, and the
  other way round (`Device:R` fields are vertical at rotation 0). `s.field(..., at=...)` takes an absolute grid
  point for the anchor; `angle=` and `justify=` say how the field reads, whatever the rotation.
- Multi-unit symbols (e.g. a dual op-amp): place each unit with the same `ref` and `unit=1`, `unit=2`, …;
  they become `U1A`, `U1B`, … of one `U1`. The dual op-amps above have 3 units: 1 and 2 are the amplifiers,
  3 carries V+ and V−; place unit 3 too and wire its supply pins. In `kicaddy pins` output, unit `0` or `*`
  means the pin is in every unit. Address a pin as `"U1.<pin number>"` after placing the unit that has it.
- The crop is one image when the drawn content, including text, the note, and power symbols, fits in about
  205 × 150 grid units; anything larger comes out as tiles. Lay out for one image unless the circuit cannot fit.
  When the circuit cannot fit, lay the sheet out in blocks that each fit 205 × 150, at least 10 units apart.
- Page sizes in grid units (landscape): A5 165×116, A4 233×165, A3 330×233, A 220×170, B 340×220. Keep 8 units
  clear at each edge (frame) and the bottom-right 87×28 (title block).

## Rules that keep the build and image clean

- Wires are orthogonal.
- Junction dots are automatic wherever 3 or more wire directions or pins meet, including a wire end or a pin
  on the middle of another wire. A pin, a label anchor, or a single wire end that touches the middle of a wire
  connects to it, so route wires around pins they must not join. Two wires crossing middle to middle do not
  connect, and neither do two wire ends that meet from opposite sides on the middle of a third wire: KiCad
  reads the two as one wire crossing it, draws no dot, and the build reports `NETLIST MISMATCH` with a `hint:`
  line naming the point. To join all four directions there, add `s.junction(point)`.
- Two pins on the same point connect without a wire. `s.wire` fails with `zero-length wire at (x, y)` when two
  consecutive points coincide: a wire between pins that already touch (e.g. a resistor placed with its pin on a
  capacitor's pin), or a corner point equal to the pin the wire starts or ends at. Work out each pin's absolute
  point (Geometry) before choosing corner points.
- A symbol is placed before the first call that names one of its pins: `"U1.20"` is looked up when `s.wire`,
  `s.label`, `s.power` or `s.no_connect` runs, and fails with `no 'U1.20': U1 is not placed on sheet /` when
  `s.symbol("U1", …)` comes later in `build()`. Place all of a sheet's symbols first, then wire.
- A power symbol's drawing starts at its pin: `GND` fills (−1, 0)-(1, 2) below it, `+5V`, `VCC` and `PWR_FLAG`
  about (−0.8, −2)-(0.8, 0) above it, turned by `rotation`. A part's body box can reach past its own pin end:
  `Device:LED` has pin 1 at (−3, 0) and `body (-3.6, -1)-(1, 1.8)` (its arrows), so `s.power("GND", "D1.1")`
  gives `body-body: D1 / #PWR…` at any rotation. Before placing a power symbol on a pin, compare the two boxes
  from `kicaddy pins`; when they overlap, wire 2 units out from the pin and put the symbol on the wire's end.
- A field that collides with a pin, wire, or another text: move it with `s.field(ref, "Value", at=...)`, or
  turn it with `angle=`.
- Put the part number in `fields={"MPN": ..., "Manufacturer": ...}` and the datasheet URL in `datasheet=`
  when known.
- A global label alone on a one-pin net gives the ERC warning `Label connected to only one pin`.
- `Device:Q_NMOS` / `Q_PMOS` gates are input pins: drive a gate net from an output or passive pin, or ERC
  reports `Input pin not driven`. These symbols have three pins (D, G, S) and no bulk pin.
- Put a `PWR_FLAG` on each supply net fed only by passive pins (a battery, a connector), or ERC reports the
  power input pins as not driven. The example flags both battery nets.
- `PWR_FLAG` and the upward power symbols (`+5V`, `+9V`, `+12V`, `VCC`) all print their value above the pin. On
  one rail, keep a flag at least 6 units left or right of such a symbol: 5 or fewer gives
  `text-text: #PWR…Value / #FLG…Value`. That holds for values up to about 4 characters; a longer value (a rail
  from `symbol=`) needs half the two value widths: `CM5_3V3` beside a flag 7 units. Next to `GND` (value below
  the pin) 4 units is enough.

## After a clean build: BOM and handoff

- **BOM.** `kicaddy bom <project dir | .kicad_pro | root .kicad_sch> [-o FILE]` writes `<name>_bom.csv` next to
  the root sheet from the saved files, so it includes `kicaddy_edit` batches and works on projects from
  `kicaddy_open`. One row per group of parts with the same Value, Footprint, MPN, and DNP state; parts flagged
  `exclude_from_bom` have no row, `dnp` parts have `DNP` in the last column; columns Reference, Value,
  Footprint, Qty, MPN, Manufacturer, Datasheet, DNP. It is not part of the build: run it again after any
  change.
- **Review, simulation, sourcing.** kicaddy does not review a design. When the user asks for a design review,
  a SPICE check, or sourcing, and the `kicad`, `spice`, or `bom` skills (kicad-happy) are available, read that
  skill and run its scripts from the project directory, which already has `analysis/` and `datasheets/` (for a
  behaviour check within a build task, Workflow step 7 has the commands and what the simulation covers):
  - `python3 <kicad skill>/scripts/analyze_schematic.py <name>.kicad_sch --analysis-dir analysis/`
  - `python3 <spice skill>/scripts/simulate_subcircuits.py --analysis-dir analysis/`
  - `python3 <bom skill>/scripts/bom_manager.py export <name>.kicad_sch -o bom/bom.csv --recursive`

  The analyzer reports the file format as newer than it has tested (`FV-001`, info), and names a net on a
  child sheet by the sheet's UUID (`/e1a1…/IN_R` for `/amp/IN_R`). Its sourcing checks read the `MPN`,
  `Manufacturer`, and Datasheet fields set in `build.py`. Always give these scripts a real output path: they
  also write `analysis/capability_mode.json` under the current directory.

## Examples

`skill://kicaddy/examples/ne555_blinker.py`: NE555 astable LED blinker on A5 with power flags, automatic T
junctions, rotation, and a note. Build it with `kicaddy run <path> --out <dir>`. Read it before writing
`build.py`; you do not need the engine source.

`skill://kicaddy/examples/multi_sheet/`: a two-sheet project (`supply.py`, `indicator.py`) sharing nets by
name. `kicaddy run <dir>/bench.py supply --out <dir>` builds one sheet beside its stubs;
`kicaddy run <dir>/build.py --out <dir>` builds the project. Read it before a project of three or more sheets.
