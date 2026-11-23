# kicaddy: designs of more than one sheet

Part of the `kicaddy` skill (`skill://kicaddy`, SKILL.md): two more methods on `s`, beside those of its
"Build script contract".

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

## Example

`skill://kicaddy/examples/multi_sheet/`: a two-sheet project (`supply.py`, `indicator.py`) sharing nets by
name. `kicaddy run <dir>/bench.py supply --out <dir>` builds one sheet beside its stubs;
`kicaddy run <dir>/build.py --out <dir>` builds the project. Read it before a project of three or more sheets.
