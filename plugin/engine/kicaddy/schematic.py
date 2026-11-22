"""Headless schematic builder on the KiCad IPC API: the engine behind a design's `build.py`.

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
to that pin's connection point (pin number, not name). `kicaddy pins Lib:Sym ...` prints pin offsets
in grid units for planning a layout; `kicaddy symbol TABLE.json --dir DIR` writes a custom symbol from a
pin table into the project's library (symbols.py) and prints its offsets.

Methods: `symbol` (rotation, mirror, value, footprint, datasheet, user fields such as MPN), `field` (move
or show a field), `power`, `wire`, `label`, `global_label`, `hier_label`, `no_connect`, `note`, `junction`
for a deliberate four-way dot, `sheet` (a child sheet drawn by its own build function, with sheet pins from
its hierarchical labels), and `net_class`. `Project` holds what the sheets share and writes the project
scaffold (.kicad_pro, empty board, library tables, datasheets/ and analysis/); `run()` builds into it.
`commit` adds junctions where KiCad's rule finds 3+ wire directions or pins meeting
(sch_geometry.junctions). `lint` reports overlapping bodies and text and wires crossing pins, bodies, and
text (sch_geometry.lint).

Requires the runtime set up by `kicaddy doctor`; run a design script with `kicaddy run build.py [--out DIR]`.
"""

import argparse
import math
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from . import bootstrap, crop, runtime, sch_geometry, symbols

GRID_MM = 1.27
PLOT_DPI = 300  # source resolution for the cropped PNG; crop downsamples to fit
SHEET_DPI = 200  # full-sheet PNG

_proto = None  # namespace of generated modules, filled by bind()


def bind(bindings):
    """Load the generated bindings at `bindings` for this module."""
    global _proto
    _proto = runtime.load_bindings(bindings)
    return _proto


def _server(project_dir=None, paths=()):
    """Load bindings recorded by `kicaddy doctor` and start a locked server; `paths` are more directories the
    server reads (mounted under Flatpak)."""
    current = bootstrap.load_current()
    bind(current["bindings"])
    return runtime.server(current["launcher"], Path(current["config_home"]), project_dir, paths)


def _pins(definition, unit):
    """Yield (pin, dx, dy), library offsets in grid units, for the pins of `unit` (None: unit 1)."""
    sch = _proto.sch
    for child in definition.items:
        if not child.item.Is(sch.SchematicPin.DESCRIPTOR):
            continue
        if child.HasField("unit") and child.unit.unit not in (0, unit or 1):  # 0: shared by all units
            continue
        pin = sch.SchematicPin()
        child.item.Unpack(pin)
        yield pin, pin.position.x_nm / 1e6 / GRID_MM, pin.position.y_nm / 1e6 / GRID_MM


def _shape_points(shape):
    """(x_nm, y_nm) points whose bounding box covers a library GraphicShape (arcs: start, mid, end)."""
    kind = shape.WhichOneof("geometry")
    g = getattr(shape, kind) if kind else None
    if kind in ("segment", "rectangle", "arc", "bezier"):
        names = {"segment": ("start", "end"), "rectangle": ("top_left", "bottom_right"),
                 "arc": ("start", "mid", "end"), "bezier": ("start", "control1", "control2", "end")}[kind]
        vectors = [getattr(g, n) for n in names]
    elif kind == "polygon":
        vectors = [v for polygon in g.polygons for node in polygon.outline.nodes
                   for v in ([node.point] if node.HasField("point") else [node.arc.start, node.arc.mid, node.arc.end])]
    elif kind in ("circle", "ellipse", "ellipse_arc"):
        c = g.center
        r = (math.hypot(g.radius_point.x_nm - c.x_nm, g.radius_point.y_nm - c.y_nm) if kind == "circle"
             else g.major_radius.value_nm)
        return [(c.x_nm - r, c.y_nm - r), (c.x_nm + r, c.y_nm + r)]
    else:
        return []
    return [(v.x_nm, v.y_nm) for v in vectors]


@dataclass
class _Placement:
    """One placed symbol item (each unit of a multi-unit symbol is its own item)."""
    name: str  # R1, or U1A, U1B, ... for multi-unit symbols
    ref: str
    unit: int
    origin: tuple  # grid point
    rotation: int
    mirror: object  # None, "x", "y"
    instance: object  # SchematicSymbolInstance, definition cleared
    definition: object  # SchematicSymbol
    pins: dict  # pin number -> grid point
    # True until commit() sends the instance. Every new symbol goes through UpdateItems once: one placed by
    # PlaceSymbolFromLibrary alone has pins the server's junction cleanup does not see, and the cleanup then
    # deletes every junction dot that depends on them (observed headless, KiCad 10.99.0-6860).
    dirty: bool = True


SHEET_SIDES = {"left": "SHS_LEFT", "right": "SHS_RIGHT", "top": "SHS_TOP", "bottom": "SHS_BOTTOM"}
SHEET_PIN_SPIN = {"left": "right", "right": "left", "top": "bottom", "bottom": "up"}  # text inside the box (probed)


@dataclass
class _SheetBox:
    """One child sheet drawn on its parent."""
    name: str
    box: tuple  # (x0, y0, x1, y1) grid
    pins: dict  # label -> (point, spin, shape)
    fields: list  # Text protos: Sheetname, Sheetfile


MANDATORY = {"Reference": "reference_field", "Value": "value_field", "Footprint": "footprint_field",
             "Datasheet": "datasheet_field", "Description": "description_field"}


def _pack(message):
    from google.protobuf import any_pb2

    packed = any_pb2.Any()
    packed.Pack(message)
    return packed


def _check(results, request_status, what):
    """Raise unless an item request and each of its item results succeeded."""
    t = _proto.types
    if request_status != t.IRS_OK:
        raise RuntimeError(f"{what}: {t.ItemRequestStatus.Name(request_status)}")
    for r in results:
        if r.status.code != _proto.editor.ISC_OK:
            raise RuntimeError(f"{what}: {r.status}")


class Project:
    """One KiCad project in `directory`: the root sheet `root` (a Schematic), its child sheets, and what they
    share: references, power-symbol numbering, net classes, the title block, and the board file."""

    def __init__(self, api, directory, name, page="A4", title="", comments=()):
        t = _proto.types
        self.api = api
        self.directory = Path(directory)
        self.name = name
        self.page = page
        path = self.directory / f"{name}.kicad_sch"
        for suffix in (".kicad_sch", ".kicad_pro", ".kicad_prl"):  # never the board
            path.with_suffix(suffix).unlink(missing_ok=True)
        for table in ("sym_lib_table", "fp_lib_table"):  # project-local tables; an existing one is kept
            file = self.directory / table.replace("_", "-")
            if not file.exists():
                file.write_text(f"({table}\n  (version 7)\n)\n")
        for sub in ("datasheets", "analysis"):  # where kicad-happy looks
            (self.directory / sub).mkdir(exist_ok=True)
        self.pin_ids = {}  # pin KIID -> "REF.PIN", every sheet
        self.units = {}  # (ref, unit) -> name of the sheet it is placed on
        self.auto = {"#PWR": 0, "#FLG": 0}
        self.libraries_ready = set()
        self.net_classes = []  # (NetClass proto, [net-name patterns])
        self.sheets = []  # every Schematic, root first, in creation order
        self.files = {name}  # sheet file stems in use
        self.title_block = (time.strftime("%Y-%m-%d"), "1", tuple(comments[:4]))
        doc = api(_proto.project.CreateDocument(type=t.DOCTYPE_SCHEMATIC, path=str(path))).document
        root = api(_proto.sch_cmd.GetSchematicHierarchy(document=doc)).top_level_sheets[0].path
        spec = t.DocumentSpecifier(type=t.DOCTYPE_SCHEMATIC, sheet_path=root, project=doc.project)
        self.root = Schematic(self, spec, name, path, "/", page, title)

    def commit(self):
        """Create every sheet's pending items, send the net classes, create the board once, and save."""
        t = _proto.types
        for s in self.sheets:
            s.commit()
        project = self.root.document.project
        if self.net_classes:
            self.api(_proto.project.SetNetClasses(net_classes=[c for c, _ in self.net_classes],
                                                  merge_mode=t.MMM_MERGE, project=project))
            patterns = [_proto.project_settings.NetClassPatternAssignment(pattern=p, netclass=c.name)
                        for c, nets in self.net_classes for p in nets]
            self.api(_proto.project.SetNetClassAssignments(pattern_assignments=patterns,
                                                           merge_mode=t.MMM_MERGE, project=project))
        board = self.directory / f"{self.name}.kicad_pcb"
        if not board.exists():
            doc = self.api(_proto.project.CreateDocument(type=t.DOCTYPE_PCB, path=str(board))).document
            self.api(_proto.project.SaveDocument(document=doc))
        self.api(_proto.project.SaveDocument(document=self.root.document))

    def netlist(self):
        """[(net name, {"REF.PIN", ...})] over the whole hierarchy; power-symbol and flag pins dropped."""
        response = self.api(_proto.sch_cmd.GetSchematicNetlist(document=self.root.document,
                                                                types=[_proto.enums.KOT_SCH_PIN]))
        nets = []
        for net in response.nets:
            members = {self.pin_ids[i.value] for s in net.sheets for i in s.items if i.value in self.pin_ids}
            members = {m for m in members if not m.startswith("#")}
            if members:
                nets.append((net.name, members))
        return sorted(nets, key=lambda n: n[0])

    def erc(self):
        """ERC violations over every sheet."""
        tasks = _proto.tasks
        token = self.api(_proto.sch_tasks.StartErcTask(document=self.root.document)).token
        while (status := self.api(tasks.GetTaskStatus(token=token))).state == tasks.TS_RUNNING:
            time.sleep(0.05)
        if status.state != tasks.TS_COMPLETED:
            raise RuntimeError(f"ERC task: {tasks.TaskState.Name(status.state)} {status.error_message}")
        return list(self.api(_proto.sch_tasks.GetErcTaskResult(token=token)).violations)


class Schematic:
    PAGES = {"A5": "PS_A5", "A4": "PS_A4", "A3": "PS_A3", "A2": "PS_A2", "A": "PS_ANSI_A", "B": "PS_ANSI_B"}
    LABEL_SIZE = 1_270_000  # nm
    SHAPES = {"input": "SLSH_INPUT", "output": "SLSH_OUTPUT", "bidirectional": "SLSH_BIDI",
              "tri_state": "SLSH_TRISTATE", "passive": "SLSH_PASSIVE"}

    def __init__(self, project, spec, name, path, hier_path, page, title):
        """One sheet of `project`, addressed by `spec`; `hier_path` is "/" for the root, "/amp/" for a child."""
        t = _proto.types
        self.project = project
        self.api = project.api
        self.document = spec  # DocumentSpecifier of this sheet
        self.header = t.ItemHeader(document=spec)
        self.name = name
        self.path = Path(path)
        self.hier_path = hier_path
        self.api(_proto.editor.SetPageSettings(document=spec, page_settings=t.PageSettings(
            page_size=t.PageSize.Value(self.PAGES[page]), orientation=t.PO_LANDSCAPE)))
        date, revision, comments = project.title_block
        block = t.TitleBlockInfo(title=title, date=date, revision=revision)
        for i, comment in enumerate(comments, 1):
            setattr(block, f"comment{i}", comment)
        self.api(_proto.editor.SetTitleBlockInfo(document=spec, title_block=block))
        self.pins = {}  # "REF.PIN" and "<sheet>.<LABEL>" -> (x, y) grid
        self.placements = {}  # (ref, unit) -> _Placement
        self._items = []  # protos for the next CreateItems
        self._wires = []  # ((x1, y1), (x2, y2)) grid segments
        self._labels = []  # (kind, text, point, spin, shape)
        self._notes = []  # (at, Text proto)
        self._sheets = []  # child sheet boxes (_SheetBox)
        self._junctions = set()  # explicit junction points
        self._junctions_created = set()
        project.sheets.append(self)

    # -- geometry ---------------------------------------------------------------------------------
    @staticmethod
    def mm(point):
        x, y = point
        return _proto.types.Vector2(x_nm=round(x * GRID_MM * 1e6), y_nm=round(y * GRID_MM * 1e6))

    def at(self, point):
        return self.pins[point] if isinstance(point, str) else point

    # -- symbols ----------------------------------------------------------------------------------
    def symbol(self, ref, lib_id, at, value=None, rotation=0, unit=None, footprint=None, mirror=None,
               datasheet=None, fields=None):
        """Place a library symbol with its origin at grid point `at`; return {pin number: (x, y)}.
        `mirror` ("x": top-bottom, "y": left-right) applies to the library drawing before `rotation`;
        `fields` adds or sets hidden user fields (MPN, Manufacturer, ...)."""
        sch, t = _proto.sch, _proto.types
        rotation, mirror = sch_geometry.canonical(rotation, mirror)
        sch_geometry.orient(0, 0, rotation, mirror)  # validates both
        for name in fields or {}:
            if name in MANDATORY:
                raise ValueError(f"{name} is a mandatory field; use value=, footprint=, datasheet=")
        key = (ref, unit or 1)
        if key in self.project.units:
            raise ValueError(f"{ref} unit {unit or 1} is already placed on sheet {self.project.units[key]}")
        self.project.units[key] = self.name
        library, entry = lib_id.split(":", 1)
        if library not in self.project.libraries_ready:
            runtime.wait_for_symbol_libraries(self.api, {library})
            self.project.libraries_ready.add(library)
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
        definition = sch.SchematicSymbol()
        definition.CopyFrom(placed.definition)
        placed.ClearField("definition")  # keeps the instance matching its library symbol on update
        result = {}
        for pin, dx, dy in _pins(definition, unit):
            dx, dy = sch_geometry.orient(dx, dy, rotation, mirror)
            if abs(dx - round(dx)) > 1e-6 or abs(dy - round(dy)) > 1e-6:
                raise RuntimeError(f"{ref}.{pin.number} is off the connection grid")
            point = (at[0] + round(dx), at[1] + round(dy))
            self.pins[f"{ref}.{pin.number}"] = result[pin.number] = point
            self.project.pin_ids[pin.id.value] = f"{ref}.{pin.number}"
        name = ref + chr(64 + (unit or 1)) if definition.unit_count > 1 else ref
        p = _Placement(name, ref, unit or 1, tuple(at), rotation, mirror, placed, definition, result)
        self.placements[(ref, p.unit)] = p

        if mirror:
            placed.transform.mirror_x = mirror == "x"
            placed.transform.mirror_y = mirror == "y"
            origin = self.mm(at)
            for field in self._fields(placed):  # move the fields with the drawing, as the GUI does
                rel = (field.text.position.x_nm - origin.x_nm, field.text.position.y_nm - origin.y_nm)
                x, y = sch_geometry.orient(*sch_geometry.unorient(*rel, rotation), rotation, mirror)
                field.text.position.x_nm, field.text.position.y_nm = origin.x_nm + x, origin.y_nm + y

        for field, text in ((placed.value_field, value), (placed.footprint_field, footprint),
                            (placed.datasheet_field, datasheet)):
            if text is not None:
                field.text.text = text
        for name, text in (fields or {}).items():
            field = next((f for f in placed.user_fields if f.name == name), None)
            if field is None:
                field = placed.user_fields.add(name=name, visible=False, show_name=False)
                field.text.CopyFrom(placed.value_field.text)
                field.text.position.CopyFrom(self.mm(at))
                field.text.attributes.visible = False
            field.text.text = text
        return result

    @staticmethod
    def _fields(instance):
        return [getattr(instance, attr) for attr in MANDATORY.values()] + list(instance.user_fields)

    def field(self, ref, name, at=None, visible=None, unit=None):
        """Move (`at`: absolute grid point, half-grid allowed) or show/hide a field of a placed symbol."""
        units = sorted(u for r, u in self.placements if r == ref)
        if not units:
            raise ValueError(f"no symbol {ref}")
        if unit is None:
            if len(units) > 1:
                raise ValueError(f"{ref} has units {units}; pass unit=")
            unit = units[0]
        if (ref, unit) not in self.placements:
            raise ValueError(f"{ref} has units {units}; no unit {unit}")
        p = self.placements[(ref, unit)]
        if name in MANDATORY:
            field = getattr(p.instance, MANDATORY[name])
        else:
            field = next((f for f in p.instance.user_fields if f.name == name), None)
            if field is None:
                raise ValueError(f"{ref} has no field {name!r}")
        if at is not None:
            field.text.position.CopyFrom(self.mm(at))
        if visible is not None:
            field.visible = field.text.attributes.visible = visible
        p.dirty = True

    def power(self, name, at, rotation=0):
        """Place power:<name> (GND, +5V, PWR_FLAG, ...) with an automatic #PWR/#FLG reference; its pin lands
        on `at`, a grid point or "REF.PIN"."""
        prefix = "#FLG" if name == "PWR_FLAG" else "#PWR"
        self.project.auto[prefix] += 1
        ref = f"{prefix}{self.project.auto[prefix]:02d}"
        self.symbol(ref, f"power:{name}", self.at(at), rotation=rotation)
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
            self._wires.append((tuple(a), tuple(b)))

    def junction(self, *points):
        """Explicit junction dot, for a deliberate four-way connection; T junctions are automatic."""
        self._junctions.update(tuple(self.at(p)) for p in points)

    def _label(self, item, kind, text, at, spin, shape=None):
        sch = _proto.sch
        point = tuple(self.at(at))
        item.position.CopyFrom(self.mm(point))
        item.spin_style = sch.SchematicLabelSpinStyle.Value(f"SLSS_{spin.upper()}")
        item.text.text = text
        item.text.attributes.size.CopyFrom(_proto.types.Vector2(x_nm=self.LABEL_SIZE, y_nm=self.LABEL_SIZE))
        self._items.append(item)
        self._labels.append((kind, text, point, spin, shape))

    def label(self, text, at, spin="right"):
        """Local net label; `spin` is the side the text extends to: left, right, up, bottom."""
        self._label(_proto.sch.LocalLabel(), "label", text, at, spin)

    def global_label(self, text, at, spin="right", shape="passive"):
        """Global net label; `shape`: input, output, bidirectional, tri_state, passive."""
        if shape not in self.SHAPES:
            raise ValueError(f"shape must be one of {', '.join(self.SHAPES)}, not {shape!r}")
        item = _proto.sch.GlobalLabel(shape=_proto.sch.SchematicLabelShape.Value(self.SHAPES[shape]))
        self._label(item, "global", text, at, spin, shape)

    def hier_label(self, text, at, spin="right", shape="input"):
        """Hierarchical label on a child sheet: becomes the sheet pin `text` on the parent's sheet box;
        `shape`: input, output, bidirectional, tri_state, passive."""
        if self.project.root is self:
            raise ValueError("hier_label belongs on a child sheet; the root sheet has no parent")
        if shape not in self.SHAPES:
            raise ValueError(f"shape must be one of {', '.join(self.SHAPES)}, not {shape!r}")
        item = _proto.sch.HierarchicalLabel(shape=_proto.sch.SchematicLabelShape.Value(self.SHAPES[shape]))
        self._label(item, "hier", text, at, spin, shape)

    def no_connect(self, at):
        self._items.append(_proto.sch.NoConnectMarker(position=self.mm(self.at(at))))

    def note(self, text, at, size=1.27):
        item = _proto.sch.SchematicText()
        item.text.position.CopyFrom(self.mm(at))
        item.text.text = text
        item.text.attributes.horizontal_alignment = _proto.enums.HA_LEFT
        item.text.attributes.size.CopyFrom(_proto.types.Vector2(x_nm=round(size * 1e6), y_nm=round(size * 1e6)))
        self._items.append(item)
        self._notes.append((tuple(at), item.text))

    # -- hierarchy --------------------------------------------------------------------------------
    def sheet(self, name, build, at, size, pins=None, page=None, title=None):
        """Child sheet `name`, file <name>.kicad_sch, drawn as a box with its top-left corner at `at` and
        `size` (w, h) in grid units; `build(child)` draws the child and returns None. Sheet pins come from
        the child's hierarchical labels: automatic (outputs on the right, the rest on the left, 2 units apart
        from the top in label order) or `pins={label: (side, offset)}`, offset from the top (left, right) or
        left (top, bottom) edge. Returns {label: (x, y)}; each pin is also "<name>.<label>"."""
        sch, t, e, enums = _proto.sch, _proto.types, _proto.editor, _proto.enums
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", name):
            raise ValueError(f"sheet name {name!r}: letters, digits, _ and - only")
        if name in self.project.files:
            raise ValueError(f"sheet name {name!r} is already used in this project")
        for pair in (at, size):
            if len(pair) != 2 or not all(isinstance(v, int) for v in pair):
                raise ValueError(f"sheet {name}: at and size are (x, y) integer grid pairs, not {pair!r}")
        (x, y), (w, h) = at, size
        if w <= 0 or h <= 0:
            raise ValueError(f"sheet {name}: size {size!r} must be positive")
        if any(k.startswith(f"{name}.") for k in self.pins):
            raise ValueError(f"sheet name {name!r} clashes with a reference on this sheet")

        self.project.files.add(name)
        file = f"{name}.kicad_sch"
        (self.path.parent / file).unlink(missing_ok=True)  # a stale file is not loaded; keep the folder clean
        sym = sch.SheetSymbol(position=self.mm(at), size=self.mm(size),
                              page_number=str(len(self.project.sheets) + 1))
        for field, text, point, valign in ((sym.name_field, name, (x, y - 1), enums.VA_BOTTOM),
                                           (sym.filename_field, file, (x, y + h + 1), enums.VA_TOP)):
            field.visible = field.text.attributes.visible = True  # hidden at (0, 0) by default
            field.text.text = text
            field.text.position.CopyFrom(self.mm(point))
            field.text.attributes.size.CopyFrom(t.Vector2(x_nm=self.LABEL_SIZE, y_nm=self.LABEL_SIZE))
            field.text.attributes.horizontal_alignment = enums.HA_LEFT
            field.text.attributes.vertical_alignment = valign
        commit = self.api(e.BeginCommit(header=self.header))  # the hierarchy shows the child only once created
        result = self.api(e.CreateItems(header=self.header, items=[_pack(sym)]))
        _check(result.created_items, result.status, f"sheet {name}")
        self.api(e.EndCommit(id=commit.id, action=e.CMA_COMMIT, message=f"sheet {name}", header=self.header))
        result.created_items[0].item.Unpack(sym)

        def find(node):
            if node.filename == file:  # file names are unique project-wide
                return node
            return next((n for n in map(find, node.children) if n is not None), None)

        top = self.api(_proto.sch_cmd.GetSchematicHierarchy(document=self.project.root.document)).top_level_sheets[0]
        node = find(top)
        if node is None:
            raise RuntimeError(f"sheet {name}: not in the hierarchy after create")
        spec = t.DocumentSpecifier(type=t.DOCTYPE_SCHEMATIC, sheet_path=node.path, project=self.document.project)
        child = Schematic(self.project, spec, name, self.path.parent / file, node.path.path_human_readable,
                          page or self.project.page, title or name)
        if build(child) is not None:
            raise ValueError(f"sheet {name}: a sheet build function returns None; return every net from the "
                             "root build")

        labels = {}  # text -> shape, first occurrence
        for kind, text, _, _, shape in child._labels:
            if kind == "hier":
                labels.setdefault(text, shape)
        if pins is None:
            sides = {"left": [l for l, s in labels.items() if s != "output"],
                     "right": [l for l, s in labels.items() if s == "output"]}
            for side, names in sides.items():
                if names and 2 * len(names) > h - 2:
                    raise ValueError(f"sheet {name}: {len(names)} pins on the {side} need height >= "
                                     f"{2 * len(names) + 2}")
            layout = {label: (side, 2 * (i + 1)) for side, names in sides.items() for i, label in enumerate(names)}
        else:
            if set(pins) != set(labels):
                raise ValueError(f"sheet {name}: pins without a hierarchical label: {sorted(set(pins) - set(labels))}; "
                                 f"hierarchical labels without a pin: {sorted(set(labels) - set(pins))}")
            layout = {}
            for label in labels:
                side, offset = pins[label]
                if side not in SHEET_SIDES:
                    raise ValueError(f"sheet {name}: pin {label} side must be one of {', '.join(SHEET_SIDES)}, "
                                     f"not {side!r}")
                span = h if side in ("left", "right") else w
                if not isinstance(offset, int) or not 0 < offset < span:
                    raise ValueError(f"sheet {name}: pin {label} offset {offset} is not inside the {side} edge")
                layout[label] = (side, offset)
        points = {}
        for label, (side, off) in layout.items():
            point = {"left": (x, y + off), "right": (x + w, y + off), "top": (x + off, y),
                     "bottom": (x + off, y + h)}[side]
            other = next((l for l, p in points.items() if p == point), None)
            if other is not None:
                raise ValueError(f"sheet {name}: pins {other} and {label} share {point}")
            points[label] = point

        for label, (side, _) in layout.items():
            pin = sym.pins.add(
                position=self.mm(points[label]), side=sch.SheetSide.Value(SHEET_SIDES[side]),
                shape=sch.SchematicLabelShape.Value(self.SHAPES[labels[label]]),
                spin_style=sch.SchematicLabelSpinStyle.Value(f"SLSS_{SHEET_PIN_SPIN[side].upper()}"))
            pin.text.text = label
            pin.text.attributes.size.CopyFrom(t.Vector2(x_nm=self.LABEL_SIZE, y_nm=self.LABEL_SIZE))
        if layout:
            result = self.api(e.UpdateItems(header=self.header, items=[_pack(sym)]))
            _check(result.updated_items, result.status, f"sheet {name} pins")

        self._sheets.append(_SheetBox(
            name, (x, y, x + w, y + h),
            {label: (points[label], SHEET_PIN_SPIN[side], labels[label]) for label, (side, _) in layout.items()},
            [sym.name_field.text, sym.filename_field.text]))
        for label, point in points.items():
            self.pins[f"{name}.{label}"] = point
        return dict(points)

    def net_class(self, name, nets, track_width=None, clearance=None):
        """Project net class `name` for the net-name patterns `nets` (full names: "+9V", "/amp/OUT_L", "*"
        wildcards); `track_width`, `clearance` in mm, unset ones inherit from Default."""
        classes = self.project.net_classes
        if name == "Default" or any(c.name == name for c, _ in classes):
            raise ValueError(f"net class {name!r} is already defined")
        if isinstance(nets, str) or not nets:
            raise ValueError(f"net class {name!r}: nets is a non-empty list of net-name patterns")
        net_class = _proto.project_settings.NetClass(name=name, priority=len(classes))
        if track_width is not None:
            net_class.board.track_width.value_nm = round(track_width * 1e6)
        if clearance is not None:
            net_class.board.clearance.value_nm = round(clearance * 1e6)
        classes.append((net_class, list(nets)))

    # -- finishing --------------------------------------------------------------------------------
    def commit(self):
        """Send this sheet's pending field updates, items, and junctions; the project saves."""
        e = _proto.editor
        dirty = [p for p in self.placements.values() if p.dirty]
        if dirty:
            result = self.api(e.UpdateItems(header=self.header, items=[_pack(p.instance) for p in dirty]))
            _check(result.updated_items, result.status, "UpdateItems")
            for p, updated in zip(dirty, result.updated_items):  # the server's version, for lint
                updated.item.Unpack(p.instance)
                p.instance.ClearField("definition")
                p.dirty = False
        points = self._junctions | sch_geometry.junctions(
            self._wires, [set(p.pins.values()) for p in self.placements.values()]
            + [{p for p, _, _ in b.pins.values()} for b in self._sheets],
            {point for _, _, point, _, _ in self._labels})
        for point in sorted(points - self._junctions_created):
            self._items.append(_proto.sch.Junction(position=self.mm(point)))
        self._junctions_created |= points
        if self._items:
            commit = self.api(e.BeginCommit(header=self.header))
            result = self.api(e.CreateItems(header=self.header, items=[_pack(i) for i in self._items]))
            _check(result.created_items, result.status, "CreateItems")
            self.api(e.EndCommit(id=commit.id, action=e.CMA_COMMIT, message="build", header=self.header))
        self._items = []

    # -- lint -------------------------------------------------------------------------------------
    def _extents(self, text, ink=True):
        """Box (x0, y0, x1, y1) in nm of a Text at its position, rotated by its angle: KiCad's text box
        (EDA_TEXT::GetTextBox), or with `ink` that box less its stroke-font padding: KiCad inflates the
        glyph box by 1.5 pen widths where the ink reaches 0.5, then adds 17 % of that height. Stock
        symbols stack Reference and Value so that the padded boxes overlap with no ink touching."""
        box = self.api(_proto.base.GetTextExtents(text=text))
        x0, y0 = box.position.x_nm, box.position.y_nm
        x1, y1 = x0 + box.size.x_nm, y0 + box.size.y_nm
        if not ink:
            return (x0, y0, x1, y1)
        a = text.attributes
        size = min(a.size.x_nm, a.size.y_nm)
        pen = a.stroke_width.value_nm if a.stroke_width.value_nm > 1 else round(a.size.x_nm / 8)
        pen = min(pen, round(size * 0.25))  # GetEffectiveTextPenWidth, ClampTextPenSize
        along, across = pen, pen + round(0.17 * (a.size.y_nm + 3 * pen)) / 2
        if round(a.angle.value_degrees / 90) % 2:  # vertical text: its height runs along x
            along, across = across, along
        return (x0 + along, y0 + across, x1 - along, y1 - across)

    def _field_box(self, p, field):
        """SCH_FIELD::GetBoundingBox: the text box in library coordinates, then the symbol transform."""
        origin = self.mm(p.origin)
        rel = (field.text.position.x_nm - origin.x_nm, field.text.position.y_nm - origin.y_nm)
        text = _proto.types.Text()
        text.CopyFrom(field.text)
        local = sch_geometry.unorient(*rel, p.rotation, p.mirror)
        text.position.x_nm, text.position.y_nm = round(local[0]), round(local[1])
        x0, y0, x1, y1 = self._extents(text)
        corners = [sch_geometry.orient(x, y, p.rotation, p.mirror) for x in (x0, x1) for y in (y0, y1)]
        xs = [(origin.x_nm + x) / 1e6 / GRID_MM for x, _ in corners]
        ys = [(origin.y_nm + y) / 1e6 / GRID_MM for _, y in corners]
        return (min(xs), min(ys), max(xs), max(ys))

    def _label_box(self, kind, text, anchor, spin, shape):
        enums = _proto.enums
        ax, ay = anchor
        item = _proto.types.Text(text=text, position=self.mm(anchor))
        item.attributes.size.CopyFrom(_proto.types.Vector2(x_nm=self.LABEL_SIZE, y_nm=self.LABEL_SIZE))
        item.attributes.vertical_alignment = enums.VA_BOTTOM
        h = self.LABEL_SIZE / 1e6 / GRID_MM
        vertical = spin in ("up", "bottom")
        if kind in ("global", "hier"):  # a hierarchical label's flag fits inside the global-label outline
            item.attributes.horizontal_alignment = enums.HA_LEFT
            x0, _, x1, _ = (v / 1e6 / GRID_MM for v in self._extents(item, ink=False))  # as the outline
            margin = 0.375 * h  # label size ratio, eeschema/default_values.h
            half = h / 2 + margin
            length = x1 - x0 + 2 * margin + {"passive": 0, "input": half, "output": half,
                                              "bidirectional": 2 * half, "tri_state": 2 * half}[shape]
            lo, hi = {"right": (0, length), "left": (-length, 0), "up": (-length, 0), "bottom": (0, length)}[spin]
            if vertical:
                return (ax - half, ay + lo, ax + half, ay + hi)
            return (ax + lo, ay - half, ax + hi, ay + half)
        item.attributes.horizontal_alignment = enums.HA_LEFT if spin in ("right", "up") else enums.HA_RIGHT
        if vertical:
            item.attributes.angle.value_degrees = 90
        x0, y0, x1, y1 = (v / 1e6 / GRID_MM for v in self._extents(item))
        dist = 0.15 * h + 0.1524 / GRID_MM  # text offset ratio and default line width
        if vertical:
            x0, x1 = x0 - dist, x1 - dist
        else:
            y0, y1 = y0 - dist, y1 - dist
        return (min(x0, ax), min(y0, ay), max(x1, ax), max(y1, ay))

    def lint(self):
        """Layout issues: overlapping bodies and text, wires over pins, bodies, and text (sch_geometry.lint)."""
        sch, enums, g = _proto.sch, _proto.enums, sch_geometry
        directions = {sch.SPO_RIGHT: (1, 0), sch.SPO_LEFT: (-1, 0), sch.SPO_UP: (0, -1), sch.SPO_DOWN: (0, 1)}
        bodies, texts, pin_lines = [], [], []
        for p in self.placements.values():
            def place(x, y):  # library nm -> screen grid point
                dx, dy = g.orient(x / 1e6 / GRID_MM, y / 1e6 / GRID_MM, p.rotation, p.mirror)
                return (p.origin[0] + dx, p.origin[1] + dy)

            points = []
            for child in p.definition.items:
                if child.HasField("unit") and child.unit.unit not in (0, p.unit):
                    continue
                if child.HasField("body_style") and child.body_style.style not in (0, 1):
                    continue
                if child.item.Is(sch.SchematicGraphicShape.DESCRIPTOR):
                    shape = sch.SchematicGraphicShape()
                    child.item.Unpack(shape)
                    points += [place(x, y) for x, y in _shape_points(shape.shape)]
                elif child.item.Is(sch.SchematicPin.DESCRIPTOR):
                    pin = sch.SchematicPin()
                    child.item.Unpack(pin)
                    if not pin.visible or pin.length.value_nm <= 0 or pin.orientation not in directions:
                        continue
                    dx, dy = directions[pin.orientation]
                    n = pin.length.value_nm
                    start = place(pin.position.x_nm, pin.position.y_nm)
                    end = place(pin.position.x_nm + dx * n, pin.position.y_nm + dy * n)
                    pin_lines.append(g.PinLine(f"pin {p.ref}.{pin.number}", start, end))
            if points:
                xs, ys = [x for x, _ in points], [y for _, y in points]
                bodies.append(g.Body(p.name, (min(xs), min(ys), max(xs), max(ys)), frozenset(p.pins.values())))
            fields = [(name, getattr(p.instance, attr)) for name, attr in MANDATORY.items()]
            for name, field in fields + [(f.name, f) for f in p.instance.user_fields]:
                if field.visible and field.text.text:
                    texts.append(g.TextBox(f"{p.name}.{name}", self._field_box(p, field), p.name, None))
        for kind, text, anchor, spin, shape in self._labels:
            texts.append(g.TextBox(f"{kind} {text!r}", self._label_box(kind, text, anchor, spin, shape), None, anchor))
        for b in self._sheets:
            bodies.append(g.Body(f"sheet {b.name}", b.box, frozenset(p for p, _, _ in b.pins.values())))
            for i, text in enumerate(b.fields):
                box = tuple(v / 1e6 / GRID_MM for v in self._extents(text))
                texts.append(g.TextBox(f"sheet {b.name}.{'Sheetname' if i == 0 else 'Sheetfile'}", box,
                                       f"sheet {b.name}", None))
            for label, (point, spin, shape) in b.pins.items():
                texts.append(g.TextBox(f"sheet pin {b.name}.{label}", self._label_box("hier", label, point, spin, shape),
                                       f"sheet {b.name}", point))
        for at, note in self._notes:
            text = _proto.types.Text()
            text.CopyFrom(note)
            text.attributes.multiline = True
            if text.attributes.vertical_alignment == enums.VA_UNKNOWN:
                text.attributes.vertical_alignment = enums.VA_CENTER  # multi-line notes centre vertically
            box = tuple(v / 1e6 / GRID_MM for v in self._extents(text))
            texts.append(g.TextBox(f"note ({at[0]:g}, {at[1]:g})", box, None, None))
        return g.lint(bodies, texts, pin_lines, self._wires)

    def plot(self, kind, output, drawing_sheet=True, dpi=None, all_sheets=False):
        """Plot this sheet, or with `all_sheets` (from the root) every sheet: one page each in a PDF."""
        sj = _proto.sch_jobs
        job = {"png": sj.RunSchematicJobExportPng, "svg": sj.RunSchematicJobExportSvg,
               "pdf": sj.RunSchematicJobExportPdf}[kind]()
        job.plot_settings.CopyFrom(sj.SchematicPlotSettings(
            plot_drawing_sheet=drawing_sheet, page_size=sj.SJPS_AUTO,
            sheet_mode=sj.SJSM_ALL_SHEETS if all_sheets else sj.SJSM_SINGLE_SHEET))
        job.job_settings.CopyFrom(_proto.jobs.RunJobSettings(document=self.document, output_path=str(output)))
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
                return crop.save(crop.crop(image, PLOT_DPI), output)


def pins_command(api, lib_ids, directory):
    """Print pin offsets (grid units, Y down, rotation 0) of library symbols; the library lookup needs a
    document, created as `directory`/probe.kicad_sch (the server's project directory), before the libraries
    load so the project's sym-lib-table rows exist. Returns the "lib:name" ids printed."""
    lt = _proto.library_types
    doc = api(_proto.project.CreateDocument(type=_proto.types.DOCTYPE_SCHEMATIC,
                                            path=str(Path(directory) / "probe.kicad_sch"))).document
    runtime.wait_for_symbol_libraries(api, {i.split(":", 1)[0] for i in lib_ids})
    ids = [_proto.types.LibraryIdentifier(library_nickname=i.split(":", 1)[0], entry_name=i.split(":", 1)[1])
           for i in lib_ids]
    response = api(_proto.library.GetItemsFromLibrary(type=lt.LT_SYMBOL, document=doc, item_ids=ids))
    found = set()
    for item in response.items:  # not in request order
        symbol = _proto.sch.SchematicSymbol()
        item.Unpack(symbol)
        found.add(f"{symbol.id.library_nickname}:{symbol.id.entry_name}")
        print(f"{symbol.id.library_nickname}:{symbol.id.entry_name}  units={symbol.unit_count or 1}")
        for child in symbol.items:
            if child.item.Is(_proto.sch.SchematicPin.DESCRIPTOR):
                pin = _proto.sch.SchematicPin()
                child.item.Unpack(pin)
                unit = child.unit.unit if child.HasField("unit") else "*"
                print(f"  unit {unit}  pin {pin.number:>3} {pin.name:12s} "
                      f"({pin.position.x_nm / 1e6 / GRID_MM:g}, {pin.position.y_nm / 1e6 / GRID_MM:g})  "
                      f"{_proto.types.ElectricalPinType.Name(pin.electrical_type)}")
    return found


def probe_pins(lib_ids, project_dir=None):
    """pins_command on a server in a temporary directory (the project stays unlocked and free of probe
    files), with `project_dir`'s sym-lib-table rows made absolute."""
    with tempfile.TemporaryDirectory(prefix="kicaddy-pins-") as tmp:
        paths = ()
        if project_dir is not None:
            project_dir = Path(project_dir).resolve()
            symbols.probe_table(project_dir, Path(tmp))
            paths = (project_dir,)
        with _server(Path(tmp), paths) as api:
            return pins_command(api, lib_ids, Path(tmp))


def symbol_command(tables, directory):
    """`kicaddy symbol`: write pin tables into project libraries, then load them through KiCad and print
    their pin offsets. Exit status 1 on a bad table or a library KiCad does not load."""
    try:
        specs = [symbols.load(t) for t in tables]
        for line in symbols.write(Path(directory).resolve(), specs):
            print(line)
    except ValueError as e:
        print(f"error: {e}")
        return 1
    ids = [f"{s.library}:{s.name}" for s in specs]
    try:
        found = probe_pins(ids, directory)
    except RuntimeError as e:
        print(f"KiCad could not load the library: {e}")
        return 1
    missing = [i for i in ids if i not in found]
    if missing:
        print(f"KiCad did not load: {' '.join(missing)}")
        return 1
    return 0


def _arguments(extra=None):
    parser = argparse.ArgumentParser()
    if extra:
        extra(parser)
    return parser.parse_args()


def run(build, name, page="A4", title="", comments=(), out_dir=None):
    """Entry point for a design script. Exit status 1 on netlist mismatch, any ERC violation, or any lint
    issue; the plots are written either way."""
    args = _arguments(lambda p: p.add_argument("--out", default=out_dir, help="output directory"))
    out = Path(args.out or Path(sys.argv[0]).resolve().parent).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with _server(out) as api:
        project = Project(api, out, name, page=page, title=title, comments=comments)
        expected = build(project.root)
        project.commit()

        actual = project.netlist()
        for net, members in actual:
            print(f"net {net:28s} {' '.join(sorted(members))}")
        got, want = {frozenset(m) for _, m in actual}, {frozenset(n) for n in expected}
        ok = got == want
        if not ok:
            print(f"NETLIST MISMATCH\n  missing:    {[sorted(n) for n in want - got]}\n"
                  f"  unexpected: {[sorted(n) for n in got - want]}")

        violations = project.erc()
        print(f"ERC: {len(violations)} violation(s)")
        for v in violations:
            print(f"  {_proto.types.RuleSeverity.Name(v.severity)} {v.description} @ "
                  f"({v.position.x_nm / 1e6 / GRID_MM:g}, {v.position.y_nm / 1e6 / GRID_MM:g}) "
                  f"on {v.sheet_specific_path.path_human_readable or '/'}")

        issues = [f"{s.hier_path} {i}" for s in project.sheets for i in s.lint()]
        print(f"LINT: {len(issues)} issue(s)")
        for issue in issues:
            print(f"  {issue}")

        for s in project.sheets:
            stem = s.path.stem
            for kind in ("png", "svg"):
                print(f"{kind}: {s.plot(kind, out / f'{stem}.{kind}')}")
            for path in s.plot_cropped(out / f"{stem}_crop.png"):
                print(f"crop: {path}")
        print(f"pdf: {project.root.plot('pdf', out / f'{name}.pdf', all_sheets=True)}")
    return 0 if ok and not violations and not issues else 1


if __name__ == "__main__":
    command = sys.argv.pop(1) if len(sys.argv) > 1 else None
    if command == "pins":
        args = _arguments(lambda p: (p.add_argument("lib_ids", nargs="+", help="Library:Symbol"),
                                     p.add_argument("--dir", type=Path, help="project directory")))
        probe_pins(args.lib_ids, args.dir)
    elif command == "symbol":
        args = _arguments(lambda p: (p.add_argument("tables", nargs="+", type=Path, help="pin table JSON"),
                                     p.add_argument("--dir", type=Path, required=True, help="project directory")))
        sys.exit(symbol_command(args.tables, args.dir))
    else:
        print(__doc__)
