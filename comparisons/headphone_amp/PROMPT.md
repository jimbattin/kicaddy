# Benchmark prompt: headphone amplifier

The exact prompt behind [docs/06](../../docs/06-method-comparison-headphone-amp.md), copied from the `task` tool call of
the benchmark session (2026-11-21T22:50:47Z), verbatim except that `<repo>` stands for the absolute path of this
repository's checkout. Both subagents got the shared context plus their own task; neither saw the other's task.

Paths are as they were then: the `/tmp/hpamp-*` output directories, and the old `~/.cache/kicad-ipc` bindings and
venv, which the builder no longer uses (it now runs on `plugin/bin/kicaddy doctor`). For the M2 benchmark, keep the
shared context and replace agent A's `# Method (required)` section with use of the `kicaddy` plugin: that prompt is
[PROMPT_PLUGIN.md](PROMPT_PLUGIN.md) (used from M8 on; run with `omp -p` in an empty directory).

## Shared context

````markdown
# Goal
Produce a schematic for a basic headphone amplifier as a human-readable image.

# Common requirements
- Circuit: a basic headphone amplifier for typical 16-32 ohm headphones, driven from a line-level or phone source. You choose the topology, the supply (battery or single supply is fine) and whether it is mono or stereo. Component values must be electrically sound, with the key design equations and reasoning stated.
- Output: a schematic image (PNG) that a human can read: no overlapping parts, text or wires; junction dots at T connections; a short note on the drawing with key values or equations. Look at your own output image with the read tool and iterate until it is clean.
- Verify electrical correctness by whatever means your method allows.

# Isolation rules (strict)
- Work only inside your assigned output directory, plus any tool/library locations your task explicitly permits.
- Do NOT list, read or search other directories under /tmp. Do NOT read agent:// or history:// URIs. Do NOT message other agents.

# Final report
The output file paths; a circuit summary with values and reasoning; how you verified it; and the problems you hit along the way.
````

## Agent A: `HpAmpKicadIpc`

Solution space: method fixed (repo KiCad IPC builder + crop heuristic); circuit topology open.

````markdown
# Target
Your output directory: /tmp/hpamp-35b4623e0d8c (already exists). Put your design script and every output there.

# Method (required)
Use this repo's KiCad IPC approach. The repo is <repo>.
- Read docs/05-cropping-schematic-plots.md and schematics/kicad_sch_ipc.py (its docstring is the API contract).
- Use schematics/ne555_blinker/build.py as a worked example. Read only that one example design.
- Write /tmp/hpamp-35b4623e0d8c/build.py. Put `sys.path.insert(0, "<repo>/schematics")` near the top, then `from kicad_sch_ipc import run`. Define `build(s)` returning the expected nets, and end with `sys.exit(run(build, "headphone_amp", page=..., title=...))`. Outputs land next to the script by default.
- Look up pin offsets: `KICAD_API_BINDINGS=~/.cache/kicad-ipc/gen ~/.cache/kicad-ipc/venv/bin/python <repo>/schematics/kicad_sch_ipc.py pins Lib:Sym ...`
- Build: `KICAD_API_BINDINGS=~/.cache/kicad-ipc/gen ~/.cache/kicad-ipc/venv/bin/python /tmp/hpamp-35b4623e0d8c/build.py`. It exits 0 only when the netlist matches and ERC reports 0 violations; rerun it as often as you need.
- The deliverable image is the crop the build produces (headphone_amp_crop.png, or tiles).
- Do not edit any file in the repo.

# Acceptance
The common requirements. The build exits 0. The crop image is clean.
````

## Agent B: `HpAmpOther`

Solution space: any method except the forbidden one; topology open.

````markdown
# Target
Your output directory: /tmp/hpamp-5b58fe37d9f1 (already exists). Put every script and output there.

# Method constraint
Do NOT use the KiCad IPC API, and do NOT read, list or search <repo> or ~/.cache/kicad-ipc (they are off-limits). Otherwise use any approach you like: hand-written KiCad files plotted with an installed kicad-cli, a Python schematic-drawing library, hand-built SVG, or anything else available on this machine. You may install Python packages into a venv inside your output directory (`uv` is available).

# Acceptance
The common requirements. Produce a final PNG at a size that is readable in a terminal image viewer (about 1600 px wide at most, with the drawing filling the image).
````
