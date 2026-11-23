# kicaddy: custom symbols

Part of the `kicaddy` skill (`skill://kicaddy`, SKILL.md), Workflow step 2.

For a part that `kicaddy pins` leaves out, write a pin table (one symbol per JSON file;
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
