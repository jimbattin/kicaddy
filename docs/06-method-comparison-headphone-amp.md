# Method comparison: headphone amplifier schematic

On 2026-11-21, two subagents (same model, same harness) got the same problem: produce a readable schematic image of a
basic headphone amplifier for 16–32 Ω headphones. Shared requirements:
- electrically sound values, reasoning stated
- a note on the drawing
- no overlaps; junction dots at T connections
- the agent must review its own output and iterate until clean
- it must verify the circuit by whatever means its method allows
- final report covers files, circuit, verification, and problems

Topology, supply, and mono or stereo were each agent's choice. Full prompt, verbatim:
[`comparisons/headphone_amp/PROMPT.md`](../comparisons/headphone_amp/PROMPT.md).

| | Agent A: `HpAmpKicadIpc` | Agent B: `HpAmpOther` |
|---|---|---|
| Method | Required: the repo's KiCad IPC builder (`schematics/kicad_sch_ipc.py`, since M2 `plugin/engine/kicaddy/schematic.py`) and the crop heuristic ([05](05-cropping-schematic-plots.md)) | Forbidden: the KiCad IPC API, this repo, and `~/.cache/kicad-ipc`. Free to use anything else. |
| Chose | KiCad symbols, placed and wired through the API | `schemdraw` (Python drawing library) in its own venv |

## Isolation

- Each agent got its own randomly named output directory under `/tmp`, mode 700. Each task prompt contained only its
  own directory and method. The shared context did not mention a second agent and forbade listing other `/tmp`
  directories, reading `agent://` or `history://` URIs, and messaging other agents.
- **Audit.** Every tool call in both transcripts was checked afterwards:
  - B touched only its own directory.
  - A touched the repo (the docs, the module, and the NE555 example), its own directory, and a listing of
    `/usr/share/kicad/symbols`.
  - Neither transcript contains the other agent's directory name.

  The audit covers tool arguments. Isolation was enforced by instruction and an unguessable path, not OS
  permissions, since both agents run as the same user.

## Cost

From the subagent session transcripts (`usage` summed over every model call; side calls such as title generation
listed separately).

| Measure | A: KiCad IPC | B: other | B / A |
|---|---|---|---|
| Wall time (s) | 304 | 544 | 1.79 |
| Model turns | 19 | 28 | 1.47 |
| Output tokens | 27,313 | 53,619 | 1.96 |
| Uncached input tokens | 40 | 58 | — |
| Cache-read tokens | 828,366 | 1,450,507 | 1.75 |
| Cache-write tokens | 52,232 | 74,577 | 1.43 |
| Total tokens | 907,951 | 1,578,761 | 1.74 |
| Cost (USD) | 1.13 | 1.96 | 1.73 |
| Side calls: tokens / cost (USD) | 31,192 / 0.009 | 90,234 / 0.024 | — |
| Tool calls (bash / read / edit / write) | 12 / 4 / 4 / 1 | 19 / 7 / 7 / 4 | — |
| Layout iterations: renders / image reviews | 4 / 3 | 8 / 6 | — |

## What each produced

| | A: KiCad IPC | B: other |
|---|---|---|
| Circuit | Stereo, 9 V. NJM4556A dual op-amp (70 mA output) as two non-inverting gain-3.2 stages; 4.5 V divider reference; 1000 µF output coupling | One channel drawn (right channel described as identical). 9 V. One NE5532 half with a BD139/BD140 emitter-follower buffer inside the feedback loop, gain 3.1, volume pot, power switch |
| Image | `kicad_ipc/headphone_amp_crop.png`, 1600 × 953, from the crop heuristic | `other/hpamp_schematic.png`, 1564 × 1187 |
| Editable source | `.kicad_sch` / `.kicad_pro`, opens in KiCad | `draw.py` (schemdraw); no EDA netlist |
| Connectivity check | KiCad netlist matched the 15 nets the script expected; ERC 0 violations | None on the drawing. SPICE deck written separately, so not tied to the drawing |
| Circuit simulation | ngspice, one channel, generic op-amp model: 10.1 dB gain, 3.2 Vpp into 32 Ω | ngspice, one channel, hand-made transistor models: DC, AC, clipping sweep, square wave, bias vs temperature |

Artifacts: [`comparisons/headphone_amp/`](../comparisons/headphone_amp/). No B virtualenv there; `draw.py` needs
`schemdraw` and `matplotlib`.

## Reading the numbers

- **Layout effort.** A needed half the render and review cycles (4/3 vs 8/6). KiCad supplies symbol graphics, pin
  positions, junctions, and field placement; the builder resolves wire endpoints from pin names, the netlist
  comparison catches a missed connection, and the crop gives a readable image directly. B placed text, pin numbers,
  and labels by hand and fixed overlaps one at a time. Its report lists a symbol mirror that swapped the supply pins,
  pin-number offsets in inconsistent directions, a reversed C3, and a too-wide layout.
- **Not like-for-like.** The circuits differ in scope. B chose a harder circuit (discrete output stage with bias
  design) and spent more turns simulating it; A drew both channels. Part of B's extra cost is design and simulation
  work, not drawing. A drawing-only comparison would need a fixed circuit given to both agents.
- **Verification differs in kind.** A's image is a plot of a design file whose netlist was checked against the
  script's intent and passed ERC. B's correctness rests on the drawing and the SPICE deck agreeing, which nothing
  checks.
- **One run each.** One sample per method, run concurrently on the same machine. Agent runs vary; treat the ratios
  as indicative, not measured effects.
