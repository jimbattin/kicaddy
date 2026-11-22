"""Pin table (JSON) -> KiCad symbol library: `kicaddy symbol TABLE.json --dir PROJECT`. Stdlib only.

A table describes one symbol:

    {"library": "daisy", "name": "Daisy_Seed3", "reference": "U", "value": "Daisy_Seed3",
     "footprint": "Module:Electrosmith_Daisy_Seed", "datasheet": "https://...", "description": "...",
     "fields": {"Manufacturer": "..."},
     "pins": [{"numbers": ["1"], "name": "D0", "type": "bidirectional"}, ...],
     "sides": {"top": ["39"], "bottom": ["40"], "left": ["16", ...], "right": ["1", ...]}}

Pin objects take the datasheets skill's Pin shape (`numbers` or `number`, `name`, `type`). Each pin object is
one group placed by its first number; its other numbers are stacked on the same point, hidden. `sides` lists
first numbers: `left`/`right` top to bottom, `top`/`bottom` left to right. Without `sides` the groups go
DIP-style: the first half down the left, the rest up the right.

`write` merges the symbols into `<library>.kicad_sym` in the project directory and registers the library in
the project's `sym-lib-table`.
"""

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

G = 1.27  # mm per grid unit
NAME_OFFSET = 0.4  # grid units between the body edge and a pin name
PIN_LENGTH = 2
PITCH = 2
LIB_HEADER = '(kicad_symbol_lib\n\t(version 20251024)\n\t(generator "kicaddy")\n'
EMPTY_TABLE = "(sym_lib_table\n  (version 7)\n)\n"  # what Project.__init__ writes
MANDATORY = ("Reference", "Value", "Footprint", "Datasheet", "Description")
IDENTIFIER = re.compile(r"^[A-Za-z0-9_.+-]+$")
PIN_TYPES = {t: t for t in ("input", "output", "bidirectional", "tri_state", "passive", "open_collector",
                            "open_emitter", "power_in", "power_out", "unspecified", "free")}
PIN_TYPES.update(not_connected="no_connect", no_connect="no_connect")
SIDES = ("left", "right", "top", "bottom")
ANGLE = {"left": 0, "right": 180, "top": 270, "bottom": 90}  # direction from the pin end toward the body


@dataclass
class Group:
    """One pin object of the table: `numbers[0]` is placed, the others are stacked on it, hidden."""
    numbers: list
    name: str
    type: str


@dataclass
class Spec:
    library: str
    name: str
    reference: str
    value: str
    footprint: str
    datasheet: str
    description: str
    fields: dict
    sides: dict  # side -> [Group], left/right top to bottom, top/bottom left to right


def _json_type(value):
    """JSON name of a parsed value's type, for error messages."""
    for kind, name in ((bool, "boolean"), (dict, "object"), (list, "array"), (str, "string"),
                       ((int, float), "number")):
        if isinstance(value, kind):
            return name
    return "null"


def _show(value, limit=60):
    """`value` as compact JSON, cut to `limit` characters."""
    text = json.dumps(value)
    return text if len(text) <= limit else text[:limit - 3] + "..."


def _expect(value, kinds, where, example):
    """ValueError naming `where`, the expected shape (`example`), and the JSON value found, unless `value` is
    one of `kinds` (booleans never count as numbers)."""
    if not isinstance(value, kinds) or (isinstance(value, bool) and bool not in kinds):
        found = "null" if value is None else f"{_json_type(value)} {_show(value)}"
        raise ValueError(f"{where}: expected {example}, got {found}")
    return value


def _identifier(table, key):
    if key not in table:
        raise ValueError(f"{key}: missing (required); use letters, digits, _ . + -")
    value = table[key]
    if not isinstance(value, str) or not IDENTIFIER.match(value):
        raise ValueError(f"{key} {_show(value)}: use letters, digits, _ . + -")
    return value


def _number(value, where):
    """A pin number: a JSON string or integer, as str."""
    return str(_expect(value, (str, int), where, 'a pin number such as "1" or 1'))


def _group(pin, i):
    where = f"pins[{i}]"
    _expect(pin, dict, where, 'an object such as {"numbers": ["1"], "name": "VIN", "type": "power_in"}')
    if "numbers" in pin:
        _expect(pin["numbers"], list, f"{where}.numbers", 'a list such as ["1"] (use "number" for one pin)')
        numbers = [_number(n, f"{where}.numbers[{k}]") for k, n in enumerate(pin["numbers"])]
    elif "number" in pin:
        numbers = [_number(pin["number"], f"{where}.number")]
    else:
        raise ValueError(f"{where}: needs \"numbers\" (a list) or \"number\"; "
                         f"keys found: {', '.join(pin) or 'none'}")
    if not numbers or any(not n for n in numbers):
        raise ValueError(f"{where}: empty pin number in {json.dumps(numbers)}")
    name = _expect(pin.get("name", ""), str, f"{where}.name (pin {numbers[0]})", 'a string ("" for no name)')
    if re.search(r"\s", name):
        raise ValueError(f"pin {numbers[0]}: name {name!r} contains whitespace; use _")
    kind = pin.get("type")
    if not isinstance(kind, str) or kind not in PIN_TYPES:
        found = "missing" if "type" not in pin else _show(kind)
        raise ValueError(f"pin {numbers[0]}: type {found}: use one of {', '.join(sorted(PIN_TYPES))}")
    return Group(numbers, name or "~", PIN_TYPES[kind])


def _sides(groups, sides):
    if sides is None:
        half = math.ceil(len(groups) / 2)
        return {"left": groups[:half], "right": groups[half:][::-1], "top": [], "bottom": []}
    _expect(sides, dict, "sides", 'an object such as {"left": ["1", "2"], "right": ["4", "3"]}')
    unknown = set(sides) - set(SIDES)
    if unknown:
        raise ValueError(f"sides: unknown key(s) {sorted(unknown)}; use {', '.join(SIDES)}")
    first = {g.numbers[0]: g for g in groups}
    stacked = {n for g in groups for n in g.numbers[1:]}
    placed, result = set(), {}
    for side in SIDES:
        result[side] = []
        listed = _expect(sides.get(side, []), list, f"sides.{side}", 'a list of pin numbers such as ["1", "2"]')
        for k, value in enumerate(listed):
            number = _number(value, f"sides.{side}[{k}]")
            if number in stacked:
                raise ValueError(f"sides.{side}: pin {number} is stacked; list stacked pins by their first number")
            if number not in first:
                raise ValueError(f"sides.{side}: unknown pin {number}")
            if number in placed:
                raise ValueError(f"sides.{side}: pin {number} is listed twice")
            placed.add(number)
            result[side].append(first[number])
    missing = [g.numbers[0] for g in groups if g.numbers[0] not in placed]
    if missing:
        raise ValueError(f"sides: pin(s) {', '.join(missing)} not on any side")
    return result


def load(path):
    """Read and validate a pin table; the ValueError starts with the file name and names the key at fault."""
    path = Path(path)
    try:
        table = json.loads(path.read_text())
    except OSError as e:
        raise ValueError(f"{path}: cannot read: {e.strerror}") from None
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        raise ValueError(f"{path}: not valid JSON: {e}") from None
    try:
        return _spec(table)
    except ValueError as e:
        raise ValueError(f"{path}: {e}") from None


def _spec(table):
    _expect(table, dict, "table", 'an object such as {"library": "mylib", "name": "MyPart", "pins": [...]}')
    library, name = _identifier(table, "library"), _identifier(table, "name")
    if "pins" not in table:
        raise ValueError('pins: missing (required); a list such as [{"numbers": ["1"], "name": "VIN", '
                         '"type": "power_in"}]')
    pins = _expect(table["pins"], list, "pins", 'a list of pin objects such as [{"numbers": ["1"], ...}]')
    if not pins:
        raise ValueError("pins: the list is empty; a symbol needs at least one pin")
    groups = [_group(p, i) for i, p in enumerate(pins)]
    seen = set()
    for number in (n for g in groups for n in g.numbers):
        if number in seen:
            raise ValueError(f"pin {number}: number used twice")
        seen.add(number)
    text = {key: _expect(table.get(key, default), str, key, "a string")
            for key, default in (("reference", "U"), ("value", name), ("footprint", ""), ("datasheet", ""),
                                 ("description", ""))}
    raw = _expect(table.get("fields", {}), dict, "fields", 'an object such as {"Manufacturer": "Acme"}')
    fields = {}
    for key, value in raw.items():
        if key in MANDATORY:
            raise ValueError(f"fields.{key}: {key} is a mandatory field; use reference, value, footprint, "
                             f"datasheet, description")
        fields[key] = str(_expect(value, (str, int, float), f"fields.{key}", "a string or number"))
    return Spec(library, name, text["reference"], text["value"], text["footprint"], text["datasheet"],
                text["description"], fields, _sides(groups, table.get("sides")))


def _quote(text):
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _mm(units):
    """Grid units (screen) -> mm text."""
    return f"{round(units * G, 4) + 0:g}"


def _at(x, y, angle=0):
    return f"(at {_mm(x)} {_mm(-y)} {angle})"  # file Y is up


def _longest(groups):
    return max((0 if g.name == "~" else len(g.name) for g in groups), default=0)


def _band(groups):
    return math.ceil(_longest(groups) + NAME_OFFSET) + 1 if groups else 0


def symbol_text(spec):
    """The `(symbol ...)` block, indented for a top-level child of `kicad_symbol_lib`."""
    left, right, top, bottom = (spec.sides[s] for s in SIDES)
    top_band, bottom_band = _band(top), _band(bottom)
    rows, cols = max(len(left), len(right)), max(len(top), len(bottom))
    w = math.ceil(max(_longest(left) + _longest(right) + 2 * NAME_OFFSET + 2, 2 * cols + 2, 4) / 2)
    height = (top_band + PITCH * (rows - 1) + 4 + bottom_band if rows
              else max(top_band + bottom_band + 2, 4))
    h = math.ceil(height / 2)
    first_y = -h + top_band + 2
    ends = {
        "left": [(-w - PIN_LENGTH, first_y + PITCH * i) for i in range(len(left))],
        "right": [(w + PIN_LENGTH, first_y + PITCH * i) for i in range(len(right))],
        "top": [(-(len(top) - 1) + PITCH * j, -h - PIN_LENGTH) for j in range(len(top))],
        "bottom": [(-(len(bottom) - 1) + PITCH * j, h + PIN_LENGTH) for j in range(len(bottom))],
    }

    font = "(effects (font (size 1.27 1.27)))"
    lines = [f"(symbol {_quote(spec.name)}", "\t\t(pin_names (offset 0.508))", "\t\t(exclude_from_sim no)",
             "\t\t(in_bom yes)", "\t\t(on_board yes)"]
    visible = [("Reference", spec.reference, (-w, -h - 1 - (2 if top else 0))),
               ("Value", spec.value, (-w, h + 1 + (2 if bottom else 0)))]
    for key, value, (x, y) in visible:
        lines.append(f"\t\t(property {_quote(key)} {_quote(value)} {_at(x, y)} "
                     f"(effects (font (size 1.27 1.27)) (justify left)))")
    hidden = [("Footprint", spec.footprint), ("Datasheet", spec.datasheet), ("Description", spec.description),
              *spec.fields.items()]
    for key, value in hidden:
        lines.append(f"\t\t(property {_quote(key)} {_quote(value)} {_at(0, 0)} (hide yes) {font})")
    lines.append(f"\t\t(symbol {_quote(spec.name + '_0_1')}")
    lines.append(f"\t\t\t(rectangle (start {_mm(-w)} {_mm(h)}) (end {_mm(w)} {_mm(-h)}) "
                 f"(stroke (width 0) (type default)) (fill (type background)))")
    lines.append("\t\t)")
    lines.append(f"\t\t(symbol {_quote(spec.name + '_1_1')}")
    for side in SIDES:
        for group, (x, y) in zip(spec.sides[side], ends[side]):
            for k, number in enumerate(group.numbers):
                hide = " (hide yes)" if k else ""
                lines.append(f"\t\t\t(pin {group.type} line {_at(x, y, ANGLE[side])} (length {_mm(PIN_LENGTH)})"
                             f"{hide} (name {_quote(group.name)} {font}) (number {_quote(number)} {font}))")
    lines.append("\t\t)")
    lines.append("\t)")
    return "\n".join(lines)


def _children(text, what):
    """[(start, end)] of the top-level children of the single list `text` (string-aware); ValueError if
    `text` is not one balanced list."""
    spans, depth, start, i, n = [], 0, None, 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n and text[i] != '"':
                i += 2 if text[i] == "\\" else 1
            if i >= n:
                raise ValueError(what)
        elif c == "(":
            depth += 1
            if depth == 2:
                start = i
        elif c == ")":
            depth -= 1
            if depth == 1:
                spans.append((start, i + 1))
            elif depth == 0:
                if text[i + 1:].strip():
                    raise ValueError(what)
                return spans
            elif depth < 0:
                raise ValueError(what)
        i += 1
    raise ValueError(what)


def _string_after(block, head):
    """The quoted string after `(head` at the start of `block`, unescaped; None if absent."""
    m = re.match(r'\(' + head + r'\s+"((?:[^"\\]|\\.)*)"', block)
    return re.sub(r"\\(.)", r"\1", m.group(1)) if m else None


def _library_text(path, specs):
    """New text of `path` with `specs` replacing same-named symbols, plus the symbol names in order."""
    blocks = []
    if path.exists():
        text = path.read_text()
        what = f"{path}: not a symbol library; not overwritten"
        if not text.lstrip().startswith("(kicad_symbol_lib"):
            raise ValueError(what)
        replaced = {s.name for s in specs}
        for start, end in _children(text, what):
            name = _string_after(text[start:end], "symbol")
            if name is not None and name not in replaced:
                blocks.append((name, text[start:end]))
    blocks += [(s.name, symbol_text(s)) for s in specs]
    body = "".join(f"\t{block}\n" for _, block in blocks)
    return LIB_HEADER + body + ")\n", [name for name, _ in blocks]


def _table_text(text, path, library):
    """(`text` of the sym-lib-table at `path` with a row for `library`, "added <lib>" or "unchanged")."""
    uri = f"${{KIPRJMOD}}/{library}.kicad_sym"
    what = f"{path}: not a library table; not changed"
    for start, end in _children(text, what):
        row = text[start:end]
        if _string_after(row, r"lib\s+\(name") == library:
            m = re.search(r'\(uri\s+"((?:[^"\\]|\\.)*)"', row)
            found = m.group(1) if m else ""
            if found == uri:
                return text, "unchanged"
            raise ValueError(f"sym-lib-table: library {library!r} already points to {found}; "
                             f"choose another library name")
    close = text.rstrip().rindex(")")
    head = text[:close] if text[:close].endswith("\n") else text[:close] + "\n"
    row = f'(lib (name "{library}")(type "KiCad")(uri "{uri}")(options "")(descr ""))'
    return f"{head}  {row}\n{text[close:]}", f"added {library}"


def write(directory, specs):
    """Merge `specs` into `<library>.kicad_sym` files in `directory` and register each library in its
    `sym-lib-table`; returns report lines. Validates everything before writing anything."""
    directory = Path(directory)
    keys = [(s.library, s.name) for s in specs]
    for key in keys:
        if keys.count(key) > 1:
            raise ValueError(f"{key[0]}:{key[1]} is given twice")
    by_library = {}
    for s in specs:
        by_library.setdefault(s.library, []).append(s)
    table_path = directory / "sym-lib-table"
    table = table_path.read_text() if table_path.exists() else EMPTY_TABLE
    files, report = [], []
    for library, group in by_library.items():
        path = directory / f"{library}.kicad_sym"
        text, names = _library_text(path, group)
        table, status = _table_text(table, table_path, library)
        files.append((path, text))
        report += [f"library: {path} ({len(names)} symbol(s): {', '.join(names)})",
                   f"sym-lib-table: {table_path} ({status})"]
    directory.mkdir(parents=True, exist_ok=True)
    for path, text in files:
        path.write_text(text)
    table_path.write_text(table)
    return report


def probe_table(project_dir, probe_dir):
    """Copy the project's sym-lib-table into `probe_dir` with `${KIPRJMOD}` made absolute, so a probe server
    in `probe_dir` loads the project's libraries without touching the project directory."""
    source = Path(project_dir) / "sym-lib-table"
    if source.exists():
        absolute = str(Path(project_dir)).replace("\\", "\\\\").replace('"', '\\"')
        (Path(probe_dir) / "sym-lib-table").write_text(source.read_text().replace("${KIPRJMOD}", absolute))
