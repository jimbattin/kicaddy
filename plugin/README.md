# kicaddy

Headless KiCad schematic building for pi / oh-my-pi agents. An agent writes
a Python `build.py` that places library symbols and wires them by pin, optionally split into hierarchical sheets
(one build function per sheet); kicaddy runs it against KiCad's IPC API (`kicad-cli api-server`, no GUI), saves a
KiCad project (`.kicad_pro`, every `.kicad_sch`, net classes, an empty `.kicad_pcb` created once, project-local
library tables, `datasheets/` and `analysis/` for kicad-happy), checks the netlist against the nets the script
declares, runs ERC and a layout lint (overlapping symbols and text, wires over pins), and, when all three pass,
plots PNG/SVG plus a cropped PNG per sheet the agent can read, and one multi-page PDF (a failing build removes the
plots of an earlier one). Parts missing from the stock libraries get a
symbol generated from a pin table (JSON) into a project library. Through the omp extension, existing projects
(built or not) can be edited in batches whose netlist change is checked against the change the agent declares.

The plugin ships:

- `bin/kicaddy`: the command line (stdlib Python; the runtime it sets up lives in its own venv).
- `engine/kicaddy/`: the engine (runtime bootstrap, IPC client, schematic builder and read model of existing
  projects, schematic geometry and lint, netlist diff, pin-table symbol generator, crop tool, and the session daemon
  behind the extension).
- `extension/index.ts`: the omp / pi extension: tools on a KiCad server kept warm per session, a guard on the
  schematic files it holds open, and `/kicaddy`.
- `skills/kicaddy/`: the `kicaddy` skill (`SKILL.md`), a worked example design, and an example pin table.

## Prerequisites

- `python3` 3.9 or later.
- [`uv`](https://docs.astral.sh/uv/) (creates the pinned venv).
- `git`, and network access on the first `doctor` for each KiCad build (fetches the API protos of that build).
- A KiCad **10.99 nightly** or later. Stable 10.0.x has no `kicad-cli api-server`.

## Platforms

| Platform | Status |
|---|---|
| Linux | tested (this machine, and a clean Debian container with only an extracted AppImage) |
| macOS | expected to work, untested |
| Flatpak KiCad | supported, untested |
| Windows | not supported |

## Install

oh-my-pi, from the repository's marketplace catalog (`.omp-plugin/marketplace.json`):

```sh
omp plugin marketplace add <clone>
omp plugin install kicaddy@kicaddy
```

or linked to a working copy:

```sh
omp plugin link <clone>/plugin
```

Upstream pi (smoke-tested: tools, guard, and commands with a scripted model):

```sh
pi install <clone>/plugin
```

Then set up the runtime once (or let the agent do it from the skill):

```sh
python3 <clone>/plugin/bin/kicaddy doctor
```

## KiCad nightly AppImage

```sh
python3 <clone>/plugin/bin/kicaddy config kicad /path/to/kicad-nightly-….AppImage
```

A symlink to the AppImage works too, and is recommended: point the config at a stable symlink
(e.g. `~/.local/bin/kicad-nightly`) and re-point the symlink on updates. kicaddy notices the change and asks for a
new `doctor`.

The AppImage needs FUSE. Without FUSE, run `<AppImage> --appimage-extract`, which extracts into `./AppDir`, and
point the config at that directory; kicaddy uses its `bin/kicad-cli`.

## Choosing KiCad

A KiCad choice is one of:

| Choice | Meaning |
|---|---|
| `system` | `kicad-cli` on `PATH`, else `/usr/bin/kicad-cli`, `/usr/local/bin/kicad-cli` (Linux) or `/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli`, `/Applications/KiCad.app/Contents/MacOS/kicad-cli` (macOS) |
| `flatpak`, `flatpak:<APP_ID>` | the Flatpak app (default `org.kicad.KiCad`) |
| any other value | a path: a KiCad AppImage (or a symlink to one), a `kicad-cli` binary, an install directory (`bin/kicad-cli` or `kicad-cli` inside), or an app bundle (`KiCad.app`, or a directory holding it) |

Precedence, first set wins: `doctor --kicad <choice>` > `KICADDY_KICAD` > config file > `system`.

The config file is `${XDG_CONFIG_HOME:-~/.config}/kicaddy/config.json`; `kicaddy config kicad <choice>` validates
the choice and writes it there. `--kicad` and `KICADDY_KICAD` override it for one `doctor` run without changing it.

## doctor

`kicaddy doctor [--kicad CHOICE] [--refresh]` checks, in order, and stops at the first failure:

| Check | What it does |
|---|---|
| `platform` | Linux or macOS |
| `kicad` | resolves the choice to a `kicad-cli` launcher |
| `api-server` | reads the KiCad version, requires `kicad-cli api-server`, and finds the build's source commit (or its release tag) |
| `tested` | not a check: `warn` when this KiCad build is not on the plugin's tested-builds list (`engine/kicaddy/tested_builds.json`, the builds the design corpus was rebuilt on), `ok` when it is |
| `config` | an isolated `KICAD_CONFIG_HOME` with the stock library tables, so your own KiCad settings are untouched |
| `venv` | a pinned venv (pynng, protobuf, grpcio-tools, Pillow), created with `uv` |
| `bindings` | Python bindings generated from the `api/proto` tree of that KiCad build |
| `server` | starts the headless server, checks version, settings directory, and libraries, and builds, saves, and reads back the netlist of a two-resistor schematic |

`--refresh` rebuilds the venv and bindings even if cached. On success doctor records the runtime and prints the
`cli:` line to use. Afterwards, `run`, `pins`, `symbol`, `bom`, `view`, and `env` refuse to start if the KiCad file (or
Flatpak commit) changed, or if the config file's `kicad` changed, until doctor runs again.

Locations:

| What | Where |
|---|---|
| cache (venv, bindings, isolated KiCad config, `current.json`) | `$KICADDY_CACHE`, else `${XDG_CACHE_HOME:-~/.cache}/kicaddy` |
| server sockets and project locks | `$XDG_RUNTIME_DIR/kicaddy`, else `/tmp/kicaddy-<uid>` |
| config | `${XDG_CONFIG_HOME:-~/.config}/kicaddy/config.json` |

## CLI

| Command | What it does |
|---|---|
| `kicaddy doctor [--kicad CHOICE] [--refresh]` | set up and check the runtime |
| `kicaddy config kicad [CHOICE]` | show the KiCad choice and its source, or validate and save one |
| `kicaddy run SCRIPT [ARGS…]` | run a Python script (a design `build.py`) on the runtime's venv, with the engine importable |
| `kicaddy pins LIB:SYM… [--dir PROJECT]` | print pin offsets (grid units, Y down) of library symbols; `--dir` adds the project's `sym-lib-table`. An id that does not exist gets a `not found:` line with the closest names, and the exit status is 1 |
| `kicaddy symbol TABLE.json… --dir PROJECT` | write pin-table JSON files into a project symbol library, register it in `sym-lib-table`, and print the pin offsets |
| `kicaddy env` | print shell exports: `KICADDY_PYTHON`, `KICADDY_KICAD_PATH`, `KICAD_API_BINDINGS`, `KICAD_CONFIG_HOME` |
| `kicaddy view FILE` | open a schematic in eeschema on the isolated KiCad config (your own settings stay untouched; the first launch shows KiCad's startup wizard once) |
| `kicaddy sweep` | stop `api-server`s whose kicaddy process was killed, and remove their socket directories |
| `kicaddy bom PROJECT [-o FILE]` | write a grouped BOM CSV (Reference, Value, Footprint, Qty, MPN, Manufacturer, Datasheet, DNP; one row per Value, Footprint, and MPN) of a saved project (directory, `.kicad_pro`, or root `.kicad_sch`) with `kicad-cli sch export bom`; default `<root stem>_bom.csv` next to the root sheet |

`kicaddy` here means `python3 <clone>/plugin/bin/kicaddy`.

## Using the skill

Ask the agent to draw or build a schematic; the `kicaddy` skill tells it to look up pin offsets, write a pin table
and run `kicaddy symbol` for any part the stock libraries lack, write `build.py` in your project directory, build it
until the netlist matches and ERC and the layout lint are clean, and review each sheet's cropped PNG. With the
extension it does this through the tools below; without it, it runs `kicaddy doctor` first and builds with
`kicaddy run build.py`. If `doctor` fails at `kicad` or `api-server`, the agent asks which KiCad nightly to use and
saves your answer with `kicaddy config kicad`.

## omp extension

With the plugin linked into omp (or installed in pi), each session gets a daemon (`kicaddy daemon`, started on the
first tool call) that keeps one `kicad-cli api-server` running for the session's project, and stops it when the
session ends or omp exits. A session start also runs `kicaddy sweep`, which stops servers left by a killed session.
A tool call the user aborts that is still running 5 s later stops the daemon; the next call starts a new one.

omp lists these tools as commands of its `bash` tool (`kicaddy_build build.py --out DIR`, `kicaddy_edit -j '{…}'`);
pi exposes them as tools.

| Tool | What it does |
|---|---|
| `kicaddy_build` | run a design `build.py` (`script`, optional `out` directory) on the warm server: same output and files as `kicaddy run` |
| `kicaddy_open` | open an existing project (directory, `.kicad_pro`, root `.kicad_sch`) for query, render, and edit |
| `kicaddy_query` | placed symbols (with `refs`: those symbols and their pin points), nets, or ERC of the open project; library pin offsets (`lib_ids`), with or without an open project |
| `kicaddy_render` | cropped PNGs of every sheet (or one), returned as images |
| `kicaddy_edit` | builder calls on the open project (built or opened) as one batch, plus moving, removing, and changing items already in it (`s.move`, `s.remove`, `s.remove_wire`, `s.remove_label`, `s.remove_no_connect`, `s.field(..., text=)`, `project.rename_net`); reports the netlist change and the ERC and LINT issues it added. `expect` declares the netlist change (required for opened projects); a batch whose change differs is dropped and the saved files reopened. Any exception drops the batch and leaves the document unchanged; a committed batch is saved (for a built project not into `build.py`; a rebuild discards it) |

While a project is open, the agent's `edit`/`write` calls on its `.kicad_sch`/`.kicad_pro` files are blocked.

| Command | What it does |
|---|---|
| `/kicaddy config [CHOICE]` | show the KiCad choice, or set it and run `doctor` |
| `/kicaddy doctor` | stop the session's server and run `doctor` |
| `/kicaddy status` | daemon and server pids, open project, edit batches, KiCad version |
| `/kicaddy view [FILE]` | open the file (default: the open project's root sheet) in eeschema |
