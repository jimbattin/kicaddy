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
  (`schematics/kicad_sch_ipc.py`) and a crop heuristic ([05](05-cropping-schematic-plots.md)) produced five
  ERC-clean designs whose netlists matched their scripts' intent. In a head-to-head test it cost 1.7× fewer
  tokens and 1.8× less time than an agent free to draw any other way ([06](06-method-comparison-headphone-amp.md)).

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
| [../engine/](../engine/) | Runtime: `kicad-agent doctor` sets up KiCad discovery, cached bindings, pinned venv, isolated config; `kicad_agent/runtime.py` runs the locked headless server |
| [../schematics/](../schematics/) | Schematic builder on the API (`kicad_sch_ipc.py`), crop tool (`crop_plot.py`), example designs: NE555 blinker, buzzer, AM radio, 16-bit SRAM |

## Evidence labels

- **[live]**: observed against the running headless server from this AppImage.
- **[src]**: read from KiCad source at the matching commit; not executed here.

Unlabelled statements in the protocol and workflow documents are **[live]**.

## Numbers

| Measure | Value |
|---|---|
| Commands with a registered handler | 134 |
| of which usable in headless mode | 116 fully, 2 partly |
| of which exercised successfully here | 60 |
| Commands declared in the protos with no handler | 8 |
| Server start to socket ready | about 0.5 s extracted, about 1.2 s via the AppImage mount |
| Typical request round trip | about 10 ms |

## Scratch data

Working data left in `~/.cache/kicad-ipc/` (3.8 GB, mostly the extracted `AppDir/`): extracted AppImage,
sparse source checkout, probe scripts, test projects, the generated Python bindings (`gen/`), and a venv with
`pynng`, `protobuf`, and `Pillow` (`venv/`). The docs do not depend on it. The `schematics/` scripts do not use it
either: they run on the runtime set up by `python3 engine/kicad-agent doctor` (KiCad located, bindings generated and
cached by KiCad commit, pinned venv, isolated `KICAD_CONFIG_HOME`, all under `~/.cache/kicad-agent/`); run them with
`eval "$(python3 engine/kicad-agent env)"`, then `"$KICAD_AGENT_PYTHON" schematics/<design>/build.py`.
