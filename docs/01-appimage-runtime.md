# AppImage and runtime

## Build identity

| Item | Value |
|---|---|
| File | `~/.local/bin/kicad-nightly` → `kicad-nightly-10.99.0.6860.gbdd2930d2b-x86_64.AppImage` (502 MB) |
| Version | `10.99.0-6860-gbdd2930d2b`, release build |
| Source commit | `bdd2930d2be6000ed615d81deff253bbafd414bb` |
| AppImage runtime | uruntime 0.5.6 (SquashFS/DwarFS, FUSE mount) |
| Linked libraries | NNG 1.5.2, protobuf 3.21.12, wxWidgets 3.3.2, OCC 7.9.1, ngspice 45.2 |

Full commit hash, from the build itself:

```sh
kicad-nightly kicad-cli version --format commit
```

## Launching tools

`AppRun` runs a bundled tool when the first argument names a file in `bin/`; otherwise it starts the project manager.

```sh
kicad-nightly kicad-cli <args>      # CLI, including the API server
kicad-nightly pcbnew board.kicad_pcb
kicad-nightly                       # project manager GUI
```

Two ways to run:

| Mode | Command | Notes |
|---|---|---|
| FUSE mount | `kicad-nightly kicad-cli …` | Mounts at `/tmp/.mount_kicad…`, unmounts on exit. First launch this session: 7 s; later about 1 s. |
| Extracted | `kicad-nightly --appimage-extract`, then `AppDir/bin/kicad-cli …` | 3.8 GB on disk, no FUSE, about 0.5 s to start. Extracts into `./AppDir`. |

`bin/*` are hard links to the `sharun` launcher, which loads the environment from `AppDir/.env` and runs the real
binary in `shared/bin/`.

## Contents relevant to the IPC API

| Path in AppDir | Content |
|---|---|
| `bin/kicad-cli` | CLI; has the `api-server` subcommand |
| `bin/kicad`, `eeschema`, `pcbnew`, `gerbview`, `pl_editor`, `pcb_calculator` | GUI programs |
| `bin/_eeschema.kiface`, `_pcbnew.kiface`, … | Editor modules; contain the API handlers |
| `shared/lib/…/libkiapi.so.10.99.0` | Compiled protobuf message classes |
| `shared/lib/libnng.so.1.5.2`, `libprotobuf.so.32.0.12` | Transport and serialization |
| `bin/python3.11`, `shared/lib/python3.11` | Bundled Python with `wx` and `requests` only |
| `share/kicad/schemas/api.v1.schema.json` | JSON schema for IPC plugin manifests (`plugin.json`) |
| `share/kicad/{symbols,footprints,3dmodels,template,demos}` | Stock libraries, templates, 17 demo projects |

Not shipped:

- **`.proto` files.** Take them from the source tree at the matching commit (`api/proto/`). See
  [02-ipc-protocol.md](02-ipc-protocol.md#client-bindings).
- **Any Python API client.** No `kipy` package.
- **The SWIG `pcbnew` module.** No `pcbnew.py` or `_pcbnew.so`; `_pcbnew.kiface` contains no `PyInit__pcbnew` or
  `SWIG_` strings.

## `kicad-cli` subcommands

`api-server`, `fp`, `gerber`, `import`, `jobset`, `mergetool`, `pcb`, `project`, `sch`, `sym`, `version`.

```
kicad-cli api-server [--socket SOCKET_PATH] [PROJECT_OR_FILE]
```

`PROJECT_OR_FILE`: optional `.kicad_pro`, `.kicad_sch`, or `.kicad_pcb` to pre-load. The one-shot subcommands
(`sch erc`, `pcb drc`, `pcb export …`) remain useful as an independent check on files written through the API.

## Display

The API server needs no display. Every test here ran with `DISPLAY` and `WAYLAND_DISPLAY` unset, including the
raytraced 3D render.

## Configuration

| Item | Value |
|---|---|
| Settings directory | `~/.config/kicad/10.99/`, separate from other KiCad versions |
| Override | `KICAD_CONFIG_HOME=<dir>`; settings then live in `<dir>/10.99/` |
| Stock data root | `KICAD_STOCK_DATA_HOME` (set by `.env` to `AppDir/share/kicad`) |
| Template directory | `KICAD10_TEMPLATE_DIR` (set by `.env`) |
| API switch for the GUI | `api.enable_server` in `kicad_common.json`. Not needed for `kicad-cli api-server`. |

Path variables keep the `KICAD10_` prefix in this 10.99 build (`KICAD10_TEMPLATE_DIR`, `KICAD10_SYMBOL_DIR`,
`KICAD10_FOOTPRINT_DIR`).

### Library tables

Global library tables are read from the settings directory. A fresh `KICAD_CONFIG_HOME` has none, so the server
knows only project-local libraries: `OpenDocument` for `Device:R` failed with `Symbol not found` until the tables
were added. The server does not create them. The existing `~/.config/kicad/10.99/` already has both.

An isolated settings directory needs these two files in `<dir>/10.99/`, each chaining to the stock table shipped in
the AppImage:

`sym-lib-table`
```
(sym_lib_table
  (version 7)
  (lib (name "KiCad")(type "Table")(uri "${KICAD10_TEMPLATE_DIR}/sym-lib-table")(options "")(descr "Official KiCad symbol libraries"))
)
```

`fp-lib-table`
```
(fp_lib_table
  (version 7)
  (lib (name "KiCad")(type "Table")(uri "${KICAD10_TEMPLATE_DIR}/fp-lib-table")(options "")(descr "Official KiCad footprint libraries"))
)
```

With these, the server reported 224 symbol and 156 footprint libraries, all `LLS_LOADED`. First library query after
start: 5.7 s; later ones about 10 ms.

Project-local tables (`sym-lib-table`, `fp-lib-table` next to the `.kicad_pro`) are picked up when the project opens.
