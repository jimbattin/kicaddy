# kicaddy: open, query and edit an existing project

Part of the `kicaddy` skill. Setup, the builder methods on `s`, Geometry, Rules and the LINT kinds are in
`skill://kicaddy` (SKILL.md); read it first. The tools below work on the project `kicaddy_build` built this
session or `kicaddy_open` opened.

## Open

`kicaddy_open` opens an existing project (directory, `.kicad_pro`, or root `.kicad_sch`) for query, render,
and edit. When the files were saved by another KiCad release (stable 10.0, say), its output has a
`file format:` line and `kicaddy_edit` is refused: KiCad saves only its own format, so the first committed
batch would rewrite every sheet in a format that release cannot open. Query and render change nothing. Tell
the user, and only when they agree reopen with `upgrade: true`.

## Query

`kicaddy_query`, `what` = (`pins` is in SKILL.md):

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

## Edit

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
- As `bash` commands in omp, no `--help`: `kicaddy_open <project dir>` (`--upgrade` when the user has agreed),
  `kicaddy_query -j '{"what": "items", "sheet": "usb"}'`, and for a batch a JSON file with `code`, `sheet`,
  `expect` passed as `kicaddy_edit @batch.json`.
