# KiCad 11 IPC API: analysis of the nightly AppImage

Subject: `kicad-nightly-10.99.0.6860.gbdd2930d2b-x86_64.AppImage` (KiCad `10.99.0-6860-gbdd2930d2b`, source commit
`bdd2930d2be6000ed615d81deff253bbafd414bb`). Analysis date: 2026-11-21. Only this build and its matching source were
used; no other KiCad installation.

## Verdict

The build is a workable base for headless, agent-driven schematic and PCB work using only the IPC API.

- `kicad-cli api-server` runs the IPC API server with no display and no GUI process.
- The headless server can create, open, edit, save, and close projects, schematics, boards, and library items.
- A complete flow ran end to end through the API alone: new schematic → placed and wired symbols → ERC → netlist
  → new board → netlist import → footprint placement → tracks, via, zone → zone fill → DRC → Gerber, drill, SVG,
  STEP, position, and raytraced render output. API DRC results matched `kicad-cli pcb drc` on the saved file.
- The legacy SWIG `pcbnew` Python module is not in this build: no legacy fallback.
- API-drawn schematics come out readable with little layout work. A small builder
  (`plugin/engine/kicaddy/schematic.py`) and a crop heuristic ([05](05-cropping-schematic-plots.md)) produced seven
  ERC-clean designs whose netlists matched their scripts' intent, one of them on a symbol generated from a pin table.
  In a head-to-head test it cost 1.7× fewer tokens and 1.8× less time than an agent free to draw any other way
  ([06](06-method-comparison-headphone-amp.md)).

Main limits: no routing commands (tracks are placed as raw geometry), no stackup write, no library-table editing,
and no selection, view, or `RunAction` commands in headless mode. See [04-workflows.md](04-workflows.md#gaps).

## Documents

| File | Content |
|---|---|
| [01-appimage-runtime.md](01-appimage-runtime.md) | What the AppImage contains, how to launch tools from it, configuration and library setup |
| [02-ipc-protocol.md](02-ipc-protocol.md) | Transport, envelope, status codes, server modes, document model, items, commits, tasks, jobs, client bindings |
| [03-command-reference.md](03-command-reference.md) | All 134 registered commands with headless availability; declared-but-unimplemented commands; creatable item types |
| [04-workflows.md](04-workflows.md) | Verified end-to-end recipes, behaviors that differ from what the protos suggest, and gaps |
| [05-cropping-schematic-plots.md](05-cropping-schematic-plots.md) | Heuristic for cropping schematic plots to readable images (fit or tile), with results on four example designs |
| [06-method-comparison-headphone-amp.md](06-method-comparison-headphone-amp.md) | Time and token cost of the KiCad IPC method against a free-choice method, on the same headphone-amp task |
| [examples/minimal_client.py](examples/minimal_client.py) | Self-contained client: starts the headless server, reads a document, shuts down |
| [../plugin/](../plugin/) | The `kicaddy` plugin (0.5.8): `bin/kicaddy` (`doctor` resolves the chosen KiCad and sets up cached bindings, pinned venv, isolated config, and warns when the build is not on the tested-builds list `engine/kicaddy/tested_builds.json`; `run`, `pins`, `symbol`, `bom`, `config`, `view`, `sweep`), the engine (`engine/kicaddy/`: runtime, project and schematic builder `schematic.py` with hierarchical sheets, net classes, automatic junctions, text boxes and section frames, a layout lint (overlaps, text over a symbol's own lines, wires over pins), and a read model of existing projects (text boxes, frames and tables included) with move/remove/rename and note-editing operations, geometry `sch_geometry.py`, netlist diff and declared-change check `netdiff.py`, pin-table symbol generator `symbols.py`, crop tool `crop.py`, session daemon `daemon.py`), the omp / pi extension (`extension/index.ts`: build, open, query, render (sheet crops or one region), and edit-batch tools on a server kept warm per session, edits of built or opened projects checked against a declared netlist change, optionally strict about new ERC and LINT lines, an edit guard, `/kicaddy`), and the `kicaddy` skill (workflow through one image review and a circuit check with kicad-happy's simulator, BOM, kicad-happy handoff). Installable from the repository's marketplace catalog, [`../.omp-plugin/marketplace.json`](../.omp-plugin/marketplace.json) |
| [../schematics/](../schematics/) | Example designs on the builder: NE555 blinker, buzzer, AM radio, 16-bit SRAM, headphone amp, the headphone amp as a three-sheet project (`headphone_amp_hier`), and a Daisy Seed3 demo on a generated project symbol library (`daisy_seed3`). The KiCad files are tracked; the plots (PNG, SVG, PDF, crops) are git-ignored and written by `kicaddy run` |
| [../tools/](../tools/) | Repository tools, not shipped: `corpus.py` rebuilds every `schematics/*/build.py` into a temporary directory on the configured KiCad, or with `--latest` on the newest nightly downloaded into `~/.cache/kicaddy-nightly/`, and with `--record` adds the build to the tested-builds list; `daemon_check.py` runs the session daemon through build (with the `--out` library hint), query (with body and field geometry, one sheet, `lint` and `items` with text boxes, frames and tables), render (sheet crops, regions, nothing written into an opened project), edit batches (the split hint, `strict`), part flags, field angle and alignment, named rails, note and text-box edits, the file-format gate, and no lock file after shutdown in a temporary directory; `clean/run.sh` installs the plugin from the marketplace catalog in a clean container with only a KiCad AppImage, configures it, builds the NE555 example and its BOM, and smoke-tests it on upstream pi |

## Evidence labels

- **[live]**: observed against the running headless server from this AppImage.
- **[src]**: read from KiCad source at the matching commit; not executed here.

Unlabelled statements in the protocol and workflow documents are **[live]**.

## Numbers

| Measure | Value |
|---|---|
| Commands with a registered handler | 134 |
| of which usable in headless mode | 116 fully, 2 partly |
| of which exercised successfully here | 63 |
| Commands declared in the protos with no handler | 8 |
| Server start to socket ready | about 0.5 s extracted, about 1.2 s via the AppImage mount |
| Typical request round trip | about 10 ms |

## Scratch data

Working data left in `~/.cache/kicad-ipc/` (3.8 GB, mostly the extracted `AppDir/`): extracted AppImage,
sparse source checkout, probe scripts, test projects, the generated Python bindings (`gen/`), and a venv with
`pynng`, `protobuf`, and `Pillow` (`venv/`). The docs do not depend on it. The `schematics/` scripts do not use it
either: they run on the runtime set up by `python3 plugin/bin/kicaddy doctor` (chosen KiCad resolved, bindings
generated and cached per KiCad build, pinned venv, isolated `KICAD_CONFIG_HOME`, all under `~/.cache/kicaddy/`);
run them with `python3 plugin/bin/kicaddy run schematics/<design>/build.py`.
