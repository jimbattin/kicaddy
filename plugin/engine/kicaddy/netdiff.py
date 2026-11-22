"""Netlist snapshots of a project, their difference, and the change an edit batch declares (`expect`).

A snapshot is the component values and the nets ("REF.PIN" sets) as Project.netlist() returns them. `diff`
describes what changed between two snapshots; `expected` applies a declared change to the snapshot before a
batch, and `check` compares that with the snapshot after it. Pure Python: no protobuf, no server.

`expect` keys (all optional; {} declares no netlist change):
    add        {ref: value}       new components
    remove     [ref]              removed components; their pins leave every net
    values     {ref: value}       changed values
    connect    {pin: target}      pin "REF.PIN" joins target: a "REF.PIN", an existing net name, or a new net name
    disconnect [pin]              pin leaves its net (becomes unconnected)
    rename     {old: new}         full net names, as `kicaddy_query nets` prints them
"""

from typing import NamedTuple

AUTO_PREFIXES = ("Net-(", "unconnected-(")
EXPECT_KEYS = {"add": dict, "remove": list, "values": dict, "connect": dict, "disconnect": list, "rename": dict}
ANY = "*"  # expected name of a net merged from two named nets: either name is accepted


class Snapshot(NamedTuple):
    components: dict  # ref -> value; refs starting "#" excluded
    nets: list  # [(net name, frozenset("REF.PIN"))]


def is_auto(name):
    """True for a name KiCad makes up (Net-(...), unconnected-(...)) and for None."""
    return name is None or name.startswith(AUTO_PREFIXES)


def _pins(pins):
    return " ".join(sorted(pins))


def _ref(pin):
    return pin.split(".", 1)[0]


# -- diff ---------------------------------------------------------------------------------------

def diff(before, after):
    """Sorted lines describing how `after` differs from `before`; [] when the netlist is unchanged."""
    lines = []
    b, a = before.components, after.components
    for ref in sorted(set(b) | set(a)):
        if ref not in b:
            lines.append(f"+ {ref} {a[ref]}")
        elif ref not in a:
            lines.append(f"- {ref} {b[ref]}")
        elif a[ref] != b[ref]:
            lines.append(f"~ {ref} {b[ref]} -> {a[ref]}")

    nodes = [("b", n, frozenset(p)) for n, p in before.nets] + [("a", n, frozenset(p)) for n, p in after.nets]
    parent = list(range(len(nodes)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    first = {}  # pin -> node index of the before-net holding it
    for i, (side, _, pins) in enumerate(nodes):
        if side == "b":
            for pin in pins:
                first[pin] = i
    for i, (side, _, pins) in enumerate(nodes):
        if side == "a":
            for pin in pins:
                if pin in first:
                    parent[find(i)] = find(first[pin])
    groups = {}
    for i in range(len(nodes)):
        groups.setdefault(find(i), []).append(nodes[i])

    nets = []
    for group in groups.values():
        bs = sorted((n, p) for side, n, p in group if side == "b")
        as_ = sorted((n, p) for side, n, p in group if side == "a")
        if not as_:
            nets.append(f"net gone {bs[0][0]}")
            continue
        if not bs:
            nets.append(f"net new {as_[0][0]}: {_pins(as_[0][1])}")
            continue
        old = frozenset().union(*(p for _, p in bs))
        new = frozenset().union(*(p for _, p in as_))
        names_b, names_a = " + ".join(n for n, _ in bs), " + ".join(n for n, _ in as_)
        if len(bs) == 1 and len(as_) == 1:
            if bs[0][0] != as_[0][0] and not (is_auto(bs[0][0]) and is_auto(as_[0][0])):
                nets.append(f"net {names_b} -> {names_a}")
        elif len(as_) == 1:
            nets.append(f"net merge {names_b} -> {names_a}")
        elif len(bs) == 1:
            nets.append(f"net split {names_b} -> {names_a}")
        else:
            nets.append(f"net regroup {names_b} -> {names_a}")
        changes = [f"+ {p}" for p in sorted(new - old)] + [f"- {p}" for p in sorted(old - new)]
        if changes:
            nets.append(f"net {names_a}: {' '.join(changes)}")
    return lines + sorted(nets)


# -- expectation --------------------------------------------------------------------------------

def _validate(expect):
    if not isinstance(expect, dict):
        raise ValueError(f"expected an object with keys {', '.join(EXPECT_KEYS)}, got {expect!r}")
    for key, value in expect.items():
        kind = EXPECT_KEYS.get(key)
        if kind is None:
            raise ValueError(f"{key}: unknown key; keys are {', '.join(EXPECT_KEYS)}")
        if kind is dict:
            ok = isinstance(value, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items())
            shape = "an object of strings"
        else:
            ok = isinstance(value, list) and all(isinstance(v, str) for v in value)
            shape = "a list of strings"
        if not ok:
            raise ValueError(f"{key}: expected {shape}, got {value!r}")


def _merged_name(x, y):
    if ANY in (x, y):
        return ANY
    named = {n for n in (x, y) if n is not None}
    if len(named) == 2:
        return ANY
    return named.pop() if named else None


def expected(before, expect):
    """The snapshot `expect` declares, applied to `before`. Net names are a name, None (an automatic name),
    or ANY. Raises ValueError on a malformed or inconsistent `expect`."""
    _validate(expect)
    components = dict(before.components)
    nets = [{"name": None if is_auto(n) else n, "orig": n, "pins": set(p)} for n, p in before.nets]

    def holding(pin):
        return next((net for net in nets if pin in net["pins"]), None)

    for ref in expect.get("remove", []):
        if ref not in components:
            raise ValueError(f"remove: no component {ref}")
        del components[ref]
        for net in nets:
            net["pins"] = {p for p in net["pins"] if _ref(p) != ref}
    nets = [net for net in nets if net["pins"]]
    for ref, value in expect.get("add", {}).items():
        if ref in components:
            raise ValueError(f"add: {ref} already exists")
        components[ref] = value
    for ref, value in expect.get("values", {}).items():
        if ref not in components:
            raise ValueError(f"values: no component {ref}")
        components[ref] = value

    for pin in expect.get("disconnect", []):
        net = holding(pin)
        if net is None:
            raise ValueError(f"disconnect: {pin} is in no net")
        net["pins"].discard(pin)
        nets.append({"name": None, "orig": None, "pins": {pin}})
    nets = [net for net in nets if net["pins"]]

    for old, new in expect.get("rename", {}).items():
        found = [net for net in nets if net["orig"] == old]
        if len(found) != 1:
            raise ValueError(f"rename: no net {old!r}; use the name kicaddy_query nets prints")
        if is_auto(new) or not new:
            raise ValueError(f"rename: {new!r} is not a net name KiCad keeps")
        found[0]["name"] = new

    def component_pin(pin):
        return "." in pin and _ref(pin) in components

    for pin, target in expect.get("connect", {}).items():
        if not component_pin(pin):
            raise ValueError(f"connect: {pin} is not REF.PIN of a component")
        source = holding(pin)
        if source is None:
            source = {"name": None, "orig": None, "pins": {pin}}
            nets.append(source)
        if component_pin(target):
            other = holding(target)
            if other is None:
                other = {"name": None, "orig": None, "pins": {target}}
                nets.append(other)
        elif is_auto(target):
            other = next((net for net in nets if net["orig"] == target), None)
            if other is None:
                raise ValueError(f"connect: no net {target!r}")
        else:
            other = next((net for net in nets if net["name"] == target), None)
            if other is None:
                other = {"name": target, "orig": None, "pins": set()}
                nets.append(other)
        if other is source:
            continue
        source["name"] = _merged_name(source["name"], other["name"])
        source["pins"] |= other["pins"]
        if other["orig"] is not None and source["orig"] is None:
            source["orig"] = other["orig"]
        nets.remove(other)
    return Snapshot(components, [(net["name"], frozenset(net["pins"])) for net in nets if net["pins"]])


def check(want, after, added):
    """Lines saying how `after` differs from `want` (expected()); [] when it matches. Unconnected pins of the
    components in `added` need not be declared."""
    declared = {p for _, pins in want.nets for p in pins}
    actual = {}
    for name, pins in after.nets:
        pins = frozenset(pins)
        if len(pins) == 1 and _ref(next(iter(pins))) in added and not pins & declared:
            continue
        actual[pins] = name
    wanted = {pins: name for name, pins in want.nets}
    lines = []
    for pins in sorted(wanted.keys() - actual.keys(), key=sorted):
        name = wanted[pins]
        lines.append(f"net expected, not found: {'(auto)' if name is None else name} {_pins(pins)}")
    for pins in sorted(actual.keys() - wanted.keys(), key=sorted):
        lines.append(f"net found, not expected: {actual[pins]} {_pins(pins)}")
    for pins in sorted(wanted.keys() & actual.keys(), key=sorted):
        w, a = wanted[pins], actual[pins]
        if w == ANY:
            continue
        if w is None and not is_auto(a):
            lines.append(f"net {_pins(pins)}: expected an automatic name, found {a}")
        elif w is not None and w != a:
            lines.append(f"net {_pins(pins)}: expected name {w}, found {a}")
    for ref in sorted(set(want.components) | set(after.components)):
        if ref not in after.components:
            lines.append(f"component {ref}: expected, not found")
        elif ref not in want.components:
            lines.append(f"component {ref}: not expected")
        elif want.components[ref] != after.components[ref]:
            lines.append(f"component {ref}: expected value {want.components[ref]}, found {after.components[ref]}")
    return lines
