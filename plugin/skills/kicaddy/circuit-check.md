# kicaddy: circuit check

Part of the `kicaddy` skill (`skill://kicaddy`, SKILL.md), Workflow step 7. When the task asks how the circuit
behaves, check it in this order, from the output directory:

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
