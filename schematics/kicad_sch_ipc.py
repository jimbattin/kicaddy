"""Headless schematic builder on the KiCad IPC API, shared by the designs in this directory.

A design script defines `build(sch)` that places symbols and wires on a grid, and returns the nets it
expects; `run()` does the rest: headless server, save, connectivity check, ERC, plots, cropped PNG.

    def build(sch):
        sch.symbol("R1", "Device:R", (40, 30), value="10k")
        sch.power("GND", (40, 36))
        sch.wire("R1.2", (40, 36))
        return [{"R1.2"}]  # expected nets as sets of "REF.PIN"; power-symbol pins are ignored

    if __name__ == "__main__":
        sys.exit(run(build, "my_design", page="A4", title="My design"))

Coordinates are in units of the 1.27 mm connection grid, Y down. A point given as "REF.PIN" resolves
to that pin's connection point (pin number, not name). `python kicad_sch_ipc.py pins Lib:Sym ...`
prints pin offsets in grid units for planning a layout.

Requires the runtime set up by `python3 engine/kicad-agent doctor`; run design scripts with the python it records
(`eval "$(python3 engine/kicad-agent env)"`, then `"$KICAD_AGENT_PYTHON" build.py`).
"""

import argparse
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import crop_plot  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "engine"))
from kicad_agent import bootstrap, runtime  # noqa: E402

GRID_MM = 1.27
PLOT_DPI = 300  # source resolution for the cropped PNG; crop_plot downsamples to fit
SHEET_DPI = 200  # full-sheet PNG

_proto = None  # namespace of generated modules, filled by _server()


def _server(project_dir=None):
    """Load bindings recorded by `engine/kicad-agent doctor` and start a locked server."""
    global _proto
    current = bootstrap.load_current()
    _proto = runtime.load_bindings(current["bindings"])
    return runtime.server(current["launcher"], Path(current["config_home"]), project_dir)


def rotate(x, y, degrees):
    """Pin offset (Y down) after rotating the symbol counter-clockwise on screen."""
    return {0: (x, y), 90: (y, -x), 180: (-x, -y), 270: (-y, x)}[degrees]


def _pins(definition, rotation, unit):
    """Yield (pin, dx, dy), offsets in grid units, for the pins of `unit` (None: unit 1)."""
    sch = _proto.sch
    for child in definition.items:
        if not child.item.Is(sch.SchematicPin.DESCRIPTOR):
            continue
        if child.HasField("unit") and child.unit.unit not in (0, unit or 1):  # 0: shared by all units
            continue
        pin = sch.SchematicPin()
        child.item.Unpack(pin)
        x, y = rotate(pin.position.x_nm / 1e6 / GRID_MM, pin.position.y_nm / 1e6 / GRID_MM, rotation)
        yield pin, x, y


class Schematic:
    PAGES = {"A5": "PS_A5", "A4": "PS_A4", "A3": "PS_A3", "A2": "PS_A2", "A": "PS_ANSI_A", "B": "PS_ANSI_B"}

    def __init__(self, api, path, page="A4", title="", comments=()):
        t = _proto.types
        self.api = api
        self.path = Path(path)
        self.name = self.path.stem
        for suffix in (".kicad_sch", ".kicad_pro", ".kicad_prl"):
            self.path.with_suffix(suffix).unlink(missing_ok=True)
        doc = api(_proto.project.CreateDocument(type=t.DOCTYPE_SCHEMATIC, path=str(self.path))).document
        root = api(_proto.sch_cmd.GetSchematicHierarchy(document=doc)).top_level_sheets[0].path
        self.sheet = t.DocumentSpecifier(type=t.DOCTYPE_SCHEMATIC, sheet_path=root, project=doc.project)
        self.header = t.ItemHeader(document=self.sheet)
        api(_proto.editor.SetPageSettings(document=self.sheet, page_settings=t.PageSettings(
            page_size=t.PageSize.Value(self.PAGES[page]), orientation=t.PO_LANDSCAPE)))
        block = t.TitleBlockInfo(title=title, date=time.strftime("%Y-%m-%d"), revision="1")
        for i, comment in enumerate(comments[:4], 1):
            setattr(block, f"comment{i}", comment)
        api(_proto.editor.SetTitleBlockInfo(document=self.sheet, title_block=block))
        self.pins = {}  # "REF.PIN" -> (x, y) grid
        self.pin_ids = {}  # pin KIID -> "REF.PIN"
        self._items = []
        self._updates = []
        self._auto = {"#PWR": 0, "#FLG": 0}
        self._libraries_ready = set()

    # -- geometry ---------------------------------------------------------------------------------
    @staticmethod
    def mm(point):
        x, y = point
        return _proto.types.Vector2(x_nm=round(x * GRID_MM * 1e6), y_nm=round(y * GRID_MM * 1e6))

    def at(self, point):
        return self.pins[point] if isinstance(point, str) else point

    # -- symbols ----------------------------------------------------------------------------------
    def symbol(self, ref, lib_id, at, value=None, rotation=0, unit=None, footprint=None):
        """Place a library symbol with its origin at grid point `at`; return {pin number: (x, y)}."""
        sch, t = _proto.sch, _proto.types
        library, entry = lib_id.split(":", 1)
        if library not in self._libraries_ready:
            runtime.wait_for_symbol_libraries(self.api, {library})
            self._libraries_ready.add(library)
        request = _proto.sch_cmd.PlaceSymbolFromLibrary(
            header=self.header,
            lib_id=t.LibraryIdentifier(library_nickname=library, entry_name=entry),
            position=self.mm(at),
            orientation={0: sch.SSO_0, 90: sch.SSO_90, 180: sch.SSO_180, 270: sch.SSO_270}[rotation],
            reference=ref,
        )
        if unit:
            request.unit.unit = unit
        placed = sch.SchematicSymbolInstance()
        self.api(request).item.Unpack(placed)
        result = {}
        for pin, dx, dy in _pins(placed.definition, rotation, unit):
            if abs(dx - round(dx)) > 1e-6 or abs(dy - round(dy)) > 1e-6:
                raise RuntimeError(f"{ref}.{pin.number} is off the connection grid")
            point = (at[0] + round(dx), at[1] + round(dy))
            self.pins[f"{ref}.{pin.number}"] = result[pin.number] = point
            self.pin_ids[pin.id.value] = f"{ref}.{pin.number}"
        changed = False
        if value is not None and placed.value_field.text.text != value:
            placed.value_field.text.text = value
            changed = True
        if footprint is not None and placed.footprint_field.text.text != footprint:
            placed.footprint_field.text.text = footprint
            changed = True
        if changed:
            placed.ClearField("definition")  # keeps the instance matching its library symbol
            self._updates.append(placed)
        return result

    def power(self, name, at, rotation=0):
        """Place power:<name> (GND, +5V, PWR_FLAG, ...) with an automatic #PWR/#FLG reference."""
        prefix = "#FLG" if name == "PWR_FLAG" else "#PWR"
        self._auto[prefix] += 1
        ref = f"{prefix}{self._auto[prefix]:02d}"
        self.symbol(ref, f"power:{name}", at, rotation=rotation)
        return ref

    # -- connections and annotations ------------------------------------------------------------
    def wire(self, *points):
        """Polyline through grid points and/or "REF.PIN" names; one wire segment per leg."""
        pts = [self.at(p) for p in points]
        for a, b in zip(pts, pts[1:]):
            if a == b:
                raise ValueError(f"zero-length wire at {a}")
            if a[0] != b[0] and a[1] != b[1]:
                raise ValueError(f"diagonal wire {a} -> {b}")
            self._items.append(_proto.sch.SchematicLine(start=self.mm(a), end=self.mm(b), type=_proto.sch.SLT_WIRE))

    def junction(self, *points):
        for p in points:
            self._items.append(_proto.sch.Junction(position=self.mm(self.at(p))))

    def label(self, text, at, spin="right"):
        """Local net label; `spin` is the side the text extends to: left, right, up, bottom."""
        sch = _proto.sch
        item = sch.LocalLabel(position=self.mm(self.at(at)),
                              spin_style=sch.SchematicLabelSpinStyle.Value(f"SLSS_{spin.upper()}"))
        item.text.text = text
        self._items.append(item)

    def no_connect(self, at):
        self._items.append(_proto.sch.NoConnectMarker(position=self.mm(self.at(at))))

    def note(self, text, at, size=1.27):
        item = _proto.sch.SchematicText()
        item.text.position.CopyFrom(self.mm(at))
        item.text.text = text
        item.text.attributes.horizontal_alignment = _proto.enums.HA_LEFT
        item.text.attributes.size.CopyFrom(_proto.types.Vector2(x_nm=round(size * 1e6), y_nm=round(size * 1e6)))
        self._items.append(item)

    # -- finishing --------------------------------------------------------------------------------
    def commit(self):
        from google.protobuf import any_pb2

        def pack(message):
            packed = any_pb2.Any()
            packed.Pack(message)
            return packed

        e, t = _proto.editor, _proto.types

        def check(results, request_status, what):
            if request_status != t.IRS_OK:
                raise RuntimeError(f"{what}: {t.ItemRequestStatus.Name(request_status)}")
            for r in results:
                if r.status.code != e.ISC_OK:
                    raise RuntimeError(f"{what}: {r.status}")

        if self._updates:
            result = self.api(e.UpdateItems(header=self.header, items=[pack(s) for s in self._updates]))
            check(result.updated_items, result.status, "UpdateItems")
        if self._items:
            commit = self.api(e.BeginCommit(header=self.header))
            result = self.api(e.CreateItems(header=self.header, items=[pack(i) for i in self._items]))
            check(result.created_items, result.status, "CreateItems")
            self.api(e.EndCommit(id=commit.id, action=e.CMA_COMMIT, message="build", header=self.header))
        self._updates, self._items = [], []
        self.api(_proto.project.SaveDocument(document=self.sheet))

    def netlist(self):
        """[(net name, {"REF.PIN", ...})] from the server; power-symbol and flag pins dropped."""
        response = self.api(_proto.sch_cmd.GetSchematicNetlist(document=self.sheet,
                                                                types=[_proto.enums.KOT_SCH_PIN]))
        nets = []
        for net in response.nets:
            members = {self.pin_ids[i.value] for s in net.sheets for i in s.items if i.value in self.pin_ids}
            members = {m for m in members if not m.startswith("#")}
            if members:
                nets.append((net.name, members))
        return sorted(nets, key=lambda n: n[0])

    def erc(self):
        tasks = _proto.tasks
        token = self.api(_proto.sch_tasks.StartErcTask(document=self.sheet)).token
        while (status := self.api(tasks.GetTaskStatus(token=token))).state == tasks.TS_RUNNING:
            time.sleep(0.05)
        if status.state != tasks.TS_COMPLETED:
            raise RuntimeError(f"ERC task: {tasks.TaskState.Name(status.state)} {status.error_message}")
        return list(self.api(_proto.sch_tasks.GetErcTaskResult(token=token)).violations)

    def plot(self, kind, output, drawing_sheet=True, dpi=None):
        sj = _proto.sch_jobs
        job = {"png": sj.RunSchematicJobExportPng, "svg": sj.RunSchematicJobExportSvg,
               "pdf": sj.RunSchematicJobExportPdf}[kind]()
        job.plot_settings.CopyFrom(sj.SchematicPlotSettings(
            plot_drawing_sheet=drawing_sheet, page_size=sj.SJPS_AUTO, sheet_mode=sj.SJSM_SINGLE_SHEET))
        job.job_settings.CopyFrom(_proto.jobs.RunJobSettings(document=self.sheet, output_path=str(output)))
        if kind == "png":
            job.dpi = dpi or SHEET_DPI
            job.plot_background_color = True
        result = self.api(job)
        if result.status != _proto.jobs.JS_SUCCESS:
            raise RuntimeError(f"{type(job).__name__}: {_proto.jobs.JobStatus.Name(result.status)} {result.message}")
        return Path(output)

    def plot_cropped(self, output):
        """Crop heuristic, docs/05-cropping-schematic-plots.md: plot without the drawing sheet at
        PLOT_DPI, trim to ink, pad, downsample to fit, or tile when that would make text illegible."""
        from PIL import Image

        with tempfile.TemporaryDirectory(dir=self.path.parent, prefix=".crop-") as tmp:
            raw = self.plot("png", Path(tmp) / "raw.png", drawing_sheet=False, dpi=PLOT_DPI)
            with Image.open(raw) as image:
                return crop_plot.save(crop_plot.crop(image, PLOT_DPI), output)


def pins_command(api, lib_ids):
    """Print pin offsets (grid units, Y down, rotation 0) of library symbols."""
    lt = _proto.library_types
    runtime.wait_for_symbol_libraries(api, {i.split(":", 1)[0] for i in lib_ids})
    ids = [_proto.types.LibraryIdentifier(library_nickname=i.split(":", 1)[0], entry_name=i.split(":", 1)[1])
           for i in lib_ids]
    with tempfile.TemporaryDirectory() as tmp:
        doc = api(_proto.project.CreateDocument(type=_proto.types.DOCTYPE_SCHEMATIC,
                                                path=f"{tmp}/probe.kicad_sch")).document
        response = api(_proto.library.GetItemsFromLibrary(type=lt.LT_SYMBOL, document=doc, item_ids=ids))
    for item in response.items:  # not in request order
        symbol = _proto.sch.SchematicSymbol()
        item.Unpack(symbol)
        print(f"{symbol.id.library_nickname}:{symbol.id.entry_name}  units={symbol.unit_count or 1}")
        for child in symbol.items:
            if child.item.Is(_proto.sch.SchematicPin.DESCRIPTOR):
                pin = _proto.sch.SchematicPin()
                child.item.Unpack(pin)
                unit = child.unit.unit if child.HasField("unit") else "*"
                print(f"  unit {unit}  pin {pin.number:>3} {pin.name:12s} "
                      f"({pin.position.x_nm / 1e6 / GRID_MM:g}, {pin.position.y_nm / 1e6 / GRID_MM:g})  "
                      f"{_proto.types.ElectricalPinType.Name(pin.electrical_type)}")


def _arguments(extra=None):
    parser = argparse.ArgumentParser()
    if extra:
        extra(parser)
    return parser.parse_args()


def run(build, name, page="A4", title="", comments=(), out_dir=None):
    """Entry point for a design script. Exit status 1 on netlist mismatch or any ERC violation."""
    args = _arguments(lambda p: p.add_argument("--out", default=out_dir, help="output directory"))
    out = Path(args.out or Path(sys.argv[0]).resolve().parent).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with _server(out) as api:
        sch = Schematic(api, out / f"{name}.kicad_sch", page=page, title=title, comments=comments)
        expected = build(sch)
        sch.commit()

        actual = sch.netlist()
        for net, members in actual:
            print(f"net {net:28s} {' '.join(sorted(members))}")
        got, want = {frozenset(m) for _, m in actual}, {frozenset(n) for n in expected}
        ok = got == want
        if not ok:
            print(f"NETLIST MISMATCH\n  missing:    {[sorted(n) for n in want - got]}\n"
                  f"  unexpected: {[sorted(n) for n in got - want]}")

        violations = sch.erc()
        print(f"ERC: {len(violations)} violation(s)")
        for v in violations:
            print(f"  {_proto.types.RuleSeverity.Name(v.severity)} {v.description} @ "
                  f"({v.position.x_nm / 1e6 / GRID_MM:g}, {v.position.y_nm / 1e6 / GRID_MM:g})")

        for kind in ("png", "svg", "pdf"):
            print(f"{kind}: {sch.plot(kind, out / f'{name}.{kind}')}")
        for path in sch.plot_cropped(out / f"{name}_crop.png"):
            print(f"crop: {path}")
    return 0 if ok and not violations else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "pins":
        sys.argv.pop(1)
        args = _arguments(lambda p: p.add_argument("lib_ids", nargs="+", help="Library:Symbol"))
        with _server() as api:
            pins_command(api, args.lib_ids)
    else:
        print(__doc__)
