# kicaddy

Headless KiCad schematic building and editing for [pi](https://www.npmjs.com/package/@earendil-works/pi-coding-agent)
and oh-my-pi (omp) coding agents.

An agent writes a Python `build.py` that places library symbols and wires them by pin. kicaddy runs it against
KiCad's IPC API through `kicad-cli api-server` (no GUI, no display), saves a KiCad project, and accepts the build
only when three checks pass: the netlist matches the nets the script declares, ERC is clean, and a layout lint
finds no overlapping symbols or text and no wires over pins. A build that passes is plotted, and the agent reads a
cropped PNG of each sheet to review its own drawing.

## What it does

- **Build from a script.** Symbols from the KiCad libraries, wires between named pins (`"U1.3"` to `"R3.1"`),
  power symbols, labels, notes, text boxes, section frames and tables, net classes, junctions placed
  automatically. A design can be split into hierarchical sheets, one build function per sheet.
- **Check every build.** Netlist against the nets the script returns, ERC, and a layout lint (overlapping symbols
  and text, text over a symbol's own lines, wires over pins). The build fails until all three are clean.
- **Save a KiCad project.** `.kicad_pro`, one `.kicad_sch` per sheet, an empty `.kicad_pcb`, project-local library
  tables, and PNG, SVG and PDF plots with a cropped PNG per sheet.
- **Generate missing symbols.** A part the stock libraries lack gets a symbol generated from a pin table (JSON)
  into a project symbol library.
- **Edit existing projects.** With the omp / pi extension, a project (built by kicaddy or not) can be opened,
  queried, rendered, and edited in batches. Each batch states the netlist change it intends, and is dropped if the
  actual change differs.
- **Export a BOM.** A grouped CSV (Reference, Value, Footprint, Qty, MPN, Manufacturer, Datasheet, DNP).
- **Keep KiCad warm.** The extension runs one `kicad-cli api-server` per agent session and stops it when the
  session ends.

Your own KiCad settings are not touched: kicaddy runs KiCad on an isolated configuration directory in its cache.

## Requirements

- A KiCad **10.99 nightly** or later ([kicad.org/download](https://www.kicad.org/download/)). Stable 10.0.x has
  no `kicad-cli api-server`.
- `python3` 3.9 or later.
- [`uv`](https://docs.astral.sh/uv/), which creates kicaddy's pinned virtual environment.
- `git`, and network access the first time a KiCad build is set up (kicaddy fetches that build's API definitions).

| Platform | Status |
|---|---|
| Linux | tested |
| macOS | expected to work, untested |
| Flatpak KiCad | supported, untested |
| Windows | not supported |

## Install

oh-my-pi, from this repository's marketplace catalog:

```sh
omp plugin marketplace add jimbattin/kicaddy
omp plugin install kicaddy@kicaddy
```

oh-my-pi, linked to a clone (for working on the plugin):

```sh
git clone https://github.com/jimbattin/kicaddy.git
omp plugin link "$PWD/kicaddy/plugin"
```

pi:

```sh
git clone https://github.com/jimbattin/kicaddy.git
pi install "$PWD/kicaddy/plugin"
```

## Set up KiCad

Tell kicaddy which KiCad to use, then let `doctor` set up and check the runtime (virtual environment, API
bindings for that KiCad build, isolated KiCad configuration, and a test build of a two-resistor schematic).

In an omp session:

```
/kicaddy config /path/to/kicad-nightly.AppImage
```

From a shell (`kicaddy` is `python3 <plugin>/bin/kicaddy`; `<plugin>` is `kicaddy/plugin` in a clone, or
`~/.omp/plugins/node_modules/kicaddy` after a marketplace install):

```sh
kicaddy config kicad /path/to/kicad-nightly.AppImage
kicaddy doctor
```

The KiCad choice can be an AppImage (or a symlink to one), a `kicad-cli` binary, an install directory, a macOS app
bundle, `flatpak[:APP_ID]`, or `system` (`kicad-cli` on `PATH`). An AppImage needs FUSE; without it, extract the
AppImage with `--appimage-extract` and choose the extracted directory.

`doctor` warns when the KiCad build is not one the example designs were rebuilt on. The nightly API is unreleased
and changes between builds; the tested builds are listed in
[`plugin/engine/kicaddy/tested_builds.json`](plugin/engine/kicaddy/tested_builds.json).

## Use

### With an agent

Ask for a schematic:

> Draw a 9 V NE555 LED blinker at about 5 Hz as a KiCad schematic in `./blinker`.

The `kicaddy` skill tells the agent to look up pin positions, write `build.py`, build until the netlist, ERC and
lint are clean, and review the cropped image of each sheet. To change an existing project, name it:

> Open `./amp` and add a 100 nF decoupling capacitor at U2's supply pins.

The extension gives the agent these tools:

| Tool | What it does |
|---|---|
| `kicaddy_build` | run a `build.py` on the session's KiCad server |
| `kicaddy_open` | open an existing project for query, render, and edit |
| `kicaddy_query` | symbols, nets, ERC, lint and drawn items of the open project; pin positions of library symbols |
| `kicaddy_render` | cropped PNGs of the sheets, or of one region |
| `kicaddy_edit` | a batch of changes to the open project, checked against the netlist change it declares |

and these commands:

| Command | What it does |
|---|---|
| `/kicaddy config [CHOICE]` | show the KiCad choice, or set it and run `doctor` |
| `/kicaddy doctor` | stop the session's server and run `doctor` |
| `/kicaddy status` | daemon and server, open project, KiCad version |
| `/kicaddy view [FILE]` | open a schematic in KiCad's schematic editor |

Without the extension, the agent uses the command line below.

### From the command line

Build the bundled example, look at it, and write its BOM:

```sh
kicaddy run <plugin>/skills/kicaddy/examples/ne555_blinker.py --out /tmp/ne555
kicaddy view /tmp/ne555/ne555_blinker.kicad_sch
kicaddy bom /tmp/ne555
```

| Command | What it does |
|---|---|
| `kicaddy doctor` | set up and check the runtime |
| `kicaddy config kicad [CHOICE]` | show or save the KiCad choice |
| `kicaddy run SCRIPT [ARGS…]` | run a design `build.py` |
| `kicaddy pins LIB:SYM…` | print the pin positions, body box and field positions of library symbols |
| `kicaddy symbol TABLE.json… --dir PROJECT` | generate symbols from pin tables into a project library |
| `kicaddy bom PROJECT` | write a grouped BOM CSV |
| `kicaddy view FILE` | open a schematic in KiCad's schematic editor on the isolated configuration |
| `kicaddy sweep` | stop KiCad servers left behind by a killed session |

### A build script

Part of [`plugin/skills/kicaddy/examples/ne555_blinker.py`](plugin/skills/kicaddy/examples/ne555_blinker.py).
Positions are grid units; `build` returns the nets it expects, each a set of `REF.PIN` names, and the build fails
if KiCad's netlist differs:

```python
import sys

from kicaddy.schematic import run
def build(s):
    s.symbol("U1", "Timer:NE555P", (92, 38), value="NE555P")
    s.symbol("R3", "Device:R", (110, 41), value="470")
    s.symbol("D1", "Device:LED", (110, 48), value="Red", rotation=90)
    s.power("GND", (110, 53))
    ...
    s.wire("U1.3", "R3.1")
    s.wire("R3.2", "D1.2")
    s.wire("D1.1", (110, 53))
    ...
    return [
        {"U1.3", "R3.1"},
        {"R3.2", "D1.2"},
        ...
    ]
if __name__ == "__main__":
    sys.exit(run(build, "ne555_blinker", page="A5", title="NE555 LED blinker, 5 Hz, 9 V battery"))
```

## Repository

| Path | Content |
|---|---|
| [`plugin/`](plugin/) | the plugin: command line, engine, omp / pi extension, and the `kicaddy` skill. [`plugin/README.md`](plugin/README.md) is the full reference |
| [`.omp-plugin/`](.omp-plugin/) | the omp marketplace catalog |
| [`docs/`](docs/README.md) | analysis of the KiCad IPC API in the nightly build: runtime, protocol, command reference, verified workflows |
| [`schematics/`](schematics/) | example designs, each a `build.py` with the KiCad files it produces |
| [`comparisons/`](comparisons/) | a benchmark of this method against free-choice drawing ([docs/06](docs/06-method-comparison-headphone-amp.md)) |
| [`tools/`](tools/) | repository tools: rebuild the examples on a KiCad build, test the session daemon, clean-container install test |

## License

[MIT](LICENSE). Copyright (c) 2026 Jim Battin.
