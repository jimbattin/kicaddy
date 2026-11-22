"""Schematic geometry on the connection grid (1 unit = 1.27 mm, Y down): symbol transforms, KiCad's junction
rule, and the layout lint. Pure Python: no protobuf, no server."""

import math
from typing import NamedTuple

_ROTATE = {0: lambda x, y: (x, y), 90: lambda x, y: (y, -x), 180: lambda x, y: (-x, -y), 270: lambda x, y: (-y, x)}
_MIRROR = {None: lambda x, y: (x, y), "x": lambda x, y: (x, -y), "y": lambda x, y: (-x, y)}


def _check(rotation, mirror):
    if rotation not in _ROTATE:
        raise ValueError(f"rotation must be 0, 90, 180 or 270, not {rotation!r}")
    if mirror not in _MIRROR:
        raise ValueError(f'mirror must be None, "x" or "y", not {mirror!r}')


def orient(x, y, rotation, mirror=None):
    """Library offset -> screen offset: rotate counter-clockwise on screen, then mirror ("x": top-bottom,
    "y": left-right). Order measured on the server: (90, "x") puts library (1, 0) at (0, 1)."""
    _check(rotation, mirror)
    return _MIRROR[mirror](*_ROTATE[rotation](x, y))


def unorient(x, y, rotation, mirror=None):
    """Inverse of orient(): screen offset -> library offset."""
    _check(rotation, mirror)
    return _ROTATE[(360 - rotation) % 360](*_MIRROR[mirror](x, y))


def canonical(rotation, mirror):
    """The (rotation, mirror) pair to send for a transform. KiCad's SetMirrorX on a 180-degree symbol yields
    the plain mirror-Y matrix; GetOrientation() then decodes it as MIRROR_Y + ORIENT_0, and the following
    SetMirrorY(false) clears it to identity. (0, "y") is the same matrix and survives."""
    return (0, "y") if (rotation, mirror) == (180, "x") else (rotation, mirror)


# -- junctions ------------------------------------------------------------------------------------

def _sign(v):
    return (v > 0) - (v < 0)


def _contains(segment, p):
    (x1, y1), (x2, y2) = segment
    return min(x1, x2) <= p[0] <= max(x1, x2) and min(y1, y2) <= p[1] <= max(y1, y2)


def _exit(segment, p):
    """Direction from `p` along `segment`, which ends at `p`."""
    a, b = segment
    other = b if a == p else a
    return (_sign(other[0] - p[0]), _sign(other[1] - p[1]))


def junctions(wires, pin_groups, label_points):
    """Points where KiCad's JUNCTION_HELPERS::AnalyzePoint puts a junction: 3+ distinct exits among wire ends,
    wires broken at the point, and symbol items with a pin there (one exit per item). `wires` are axis-aligned
    ((x1, y1), (x2, y2)) segments, `pin_groups` one set of pin points per placed symbol item, `label_points`
    the label anchors (they break wires but add no exit)."""
    wires = [(tuple(a), tuple(b)) for a, b in wires]
    candidates = {p for w in wires for p in w} | {p for group in pin_groups for p in group}
    found = set()
    for p in candidates:
        touching = [w for w in wires if _contains(w, p)]
        spans = touching
        if len({_exit(w, p) for w in touching if p in w}) < 3:  # merge collinear wires through p
            spans = []
            for axis in (0, 1):  # 0: horizontal (same y), 1: vertical (same x)
                along = [w for w in touching if w[0][1 - axis] == w[1][1 - axis]]
                if along:
                    lo = min(min(a[axis], b[axis]) for a, b in along)
                    hi = max(max(a[axis], b[axis]) for a, b in along)
                    spans.append(((lo, p[1]), (hi, p[1])) if axis == 0 else ((p[0], lo), (p[0], hi)))
        exits, breaks = set(), p in label_points
        for span in spans:
            if p in span:
                exits.add(_exit(span, p))
                breaks = True
        for i, group in enumerate(pin_groups):
            if p in group:
                exits.add(("pin", i))
                breaks = True
        if breaks:
            for span in spans:
                if p not in span:
                    d = _exit((span[0], p), p)
                    exits.update({d, (-d[0], -d[1])})
        if len(exits) >= 3:
            found.add(p)
    return found


def crossing(wires, p):
    """True when one wire runs horizontally and another vertically through `p`, both with `p` strictly
    inside: a middle-to-middle crossing, connected only by an explicit junction."""
    def through(w, axis):  # axis 0: horizontal run, 1: vertical
        a, b = w
        if a[1 - axis] != p[1 - axis] or b[1 - axis] != p[1 - axis]:
            return False
        return min(a[axis], b[axis]) < p[axis] < max(a[axis], b[axis])

    return any(through(w, 0) for w in wires) and any(through(w, 1) for w in wires)


def end_crossings(wires, junction_points):
    """Points without a junction where two wire ends meet in line, strictly inside a wire running the other way.
    KiCad merges the two ends into one wire, so the drawing is a crossing: no dot and no connection."""
    wires = [(tuple(a), tuple(b)) for a, b in wires]
    found = set()
    for p in {q for w in wires for q in w} - set(junction_points):
        exits = {_exit(w, p) for w in wires if p in w}
        for axis in (0, 1):  # the two ends run along x (0) or y (1); the third wire runs the other way
            if exits == {(1 - axis, axis), (axis - 1, -axis)} and any(
                    a[axis] == p[axis] == b[axis]
                    and min(a[1 - axis], b[1 - axis]) < p[1 - axis] < max(a[1 - axis], b[1 - axis])
                    for a, b in wires):
                found.add(p)
    return sorted(found)


# -- lint -----------------------------------------------------------------------------------------

class Body(NamedTuple):
    name: str
    box: tuple  # (x0, y0, x1, y1), normalized
    pins: frozenset  # connection points of this item
    strokes: tuple = ()  # ((x1, y1), (x2, y2)) segments of the item's own drawing (symbols only)


class TextBox(NamedTuple):
    name: str
    box: tuple
    owner: object  # placement name for symbol fields, else None
    anchor: object  # label anchor point for labels, else None
    vertical: bool = False  # the text runs along y on the sheet


class PinLine(NamedTuple):
    name: str
    start: tuple  # connection point
    end: tuple  # inner end


EPS = 0.05  # grid units; touching edges are not overlaps


def _box(a, b):
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


def _overlap(a, b):
    """Intersection of two boxes when it is wider and taller than EPS, else None."""
    box = (max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3]))
    return box if round(box[2] - box[0], 6) > EPS and round(box[3] - box[1], 6) > EPS else None


def _hit(segment, box):
    """Part of an axis-aligned segment inside `box` shrunk by EPS, as a box, or None."""
    s = _box(*segment)
    inner = (box[0] + EPS, box[1] + EPS, box[2] - EPS, box[3] - EPS)
    hit = (max(s[0], inner[0]), max(s[1], inner[1]), min(s[2], inner[2]), min(s[3], inner[3]))
    return hit if hit[0] <= hit[2] and hit[1] <= hit[3] else None


def _clip(segment, box):
    """Part of any segment inside `box` shrunk by EPS, as a box, or None (Liang-Barsky)."""
    (x1, y1), (x2, y2) = segment
    dx, dy = x2 - x1, y2 - y1
    t0, t1 = 0.0, 1.0
    for p, q in ((-dx, x1 - box[0] - EPS), (dx, box[2] - EPS - x1), (-dy, y1 - box[1] - EPS), (dy, box[3] - EPS - y1)):
        if p == 0:
            if q < 0:
                return None
        elif p < 0:
            t0 = max(t0, q / p)
        else:
            t1 = min(t1, q / p)
        if t0 > t1:
            return None
    return _box((x1 + t0 * dx, y1 + t0 * dy), (x1 + t1 * dx, y1 + t1 * dy))


def _meet(a, b):
    """Common part of two axis-aligned segments, as a box, or None."""
    s, t = _box(*a), _box(*b)
    hit = (max(s[0], t[0]), max(s[1], t[1]), min(s[2], t[2]), min(s[3], t[3]))
    return hit if hit[0] <= hit[2] + 1e-9 and hit[1] <= hit[3] + 1e-9 else None


def _near(p, q):
    return abs(p[0] - q[0]) <= EPS and abs(p[1] - q[1]) <= EPS


def _extent(text):
    """"; <name> box (x0, y0)-(x1, y1) <direction>" of a TextBox, the box rounded outwards to 0.1 unit."""
    x0, y0 = (math.floor(round(v * 10, 4)) / 10 + 0.0 for v in text.box[:2])
    x1, y1 = (math.ceil(round(v * 10, 4)) / 10 + 0.0 for v in text.box[2:])
    return (f"; {text.name} box ({x0:g}, {y0:g})-({x1:g}, {y1:g}) "
            f"{'vertical' if text.vertical else 'horizontal'}")


def _line(kind, a, b, box, *texts):
    """One issue line; `texts` are the TextBox items among `a` and `b`: each adds its extent on the sheet."""
    x, y = (round((box[0] + box[2]) / 2, 1) + 0.0, round((box[1] + box[3]) / 2, 1) + 0.0)
    return f"{kind}: {a} / {b} @ ({x:g}, {y:g})" + "".join(map(_extent, texts))


def lint(bodies, texts, pins, wires):
    """Layout issues as sorted lines "kind: a / b @ (x, y)", the centre of the clash; a text-* line ends with the
    box of each text in it (_extent). `wires` are ((x1, y1), (x2, y2)) segments."""
    issues = []
    wires = [(tuple(a), tuple(b)) for a, b in wires]
    names = {w: f"wire ({w[0][0]:g}, {w[0][1]:g})-({w[1][0]:g}, {w[1][1]:g})" for w in wires}
    pins = [p for p in pins if p.start != p.end]
    for i, a in enumerate(bodies):
        for b in bodies[i + 1:]:
            if box := _overlap(a.box, b.box):
                issues.append(_line("body-body", a.name, b.name, box))
    for i, a in enumerate(texts):
        for b in texts[i + 1:]:
            if box := _overlap(a.box, b.box):
                issues.append(_line("text-text", a.name, b.name, box, a, b))
        for body in bodies:
            if a.owner != body.name and (box := _overlap(a.box, body.box)):
                issues.append(_line("text-body", a.name, body.name, box, a))
            elif a.owner == body.name:
                hit = next((box for s in body.strokes if (box := _clip(s, a.box))), None)
                if hit:
                    issues.append(_line("text-own", a.name, body.name, hit, a))
        for pin in pins:
            if box := _hit((pin.start, pin.end), a.box):
                issues.append(_line("text-pin", a.name, pin.name, box, a))
        for w in wires:
            if not (a.anchor is not None and _contains(w, a.anchor)) and (box := _hit(w, a.box)):
                issues.append(_line("text-wire", a.name, names[w], box, a))
    for w in wires:
        for body in bodies:
            if w[0] not in body.pins and w[1] not in body.pins and (box := _hit(w, body.box)):
                issues.append(_line("wire-body", names[w], body.name, box))
        for pin in pins:
            box = _meet(w, (pin.start, pin.end))
            if box is None:
                continue
            if max(box[2] - box[0], box[3] - box[1]) > EPS or not _near(box[:2], pin.start):
                issues.append(_line("wire-pin", names[w], pin.name, box))
    return sorted(issues)
