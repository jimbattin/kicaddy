# kicaddy: after a clean build: BOM and handoff

Part of the `kicaddy` skill (`skill://kicaddy`, SKILL.md).

- **BOM.** `kicaddy bom <project dir | .kicad_pro | root .kicad_sch> [-o FILE]` writes `<name>_bom.csv` next to
  the root sheet from the saved files, so it includes `kicaddy_edit` batches and works on projects from
  `kicaddy_open`. One row per group of parts with the same Value, Footprint, MPN, and DNP state; parts flagged
  `exclude_from_bom` have no row, `dnp` parts have `DNP` in the last column; columns Reference, Value,
  Footprint, Qty, MPN, Manufacturer, Datasheet, DNP. It is not part of the build: run it again after any
  change.
- **Review, simulation, sourcing.** kicaddy does not review a design. When the user asks for a design review,
  a SPICE check, or sourcing, and the `kicad`, `spice`, or `bom` skills (kicad-happy) are available, read that
  skill and run its scripts from the project directory, which already has `analysis/` and `datasheets/` (for a
  behaviour check within a build task, `skill://kicaddy/circuit-check.md` has the commands and what the
  simulation covers):
  - `python3 <kicad skill>/scripts/analyze_schematic.py <name>.kicad_sch --analysis-dir analysis/`
  - `python3 <spice skill>/scripts/simulate_subcircuits.py --analysis-dir analysis/`
  - `python3 <bom skill>/scripts/bom_manager.py export <name>.kicad_sch -o bom/bom.csv --recursive`

  The analyzer reports the file format as newer than it has tested (`FV-001`, info), and names a net on a
  child sheet by the sheet's UUID (`/e1a1…/IN_R` for `/amp/IN_R`). Its sourcing checks read the `MPN`,
  `Manufacturer`, and Datasheet fields set in `build.py`. Always give these scripts a real output path: they
  also write `analysis/capability_mode.json` under the current directory.
