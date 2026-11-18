#!/usr/bin/env python3
"""ratings — a schematic held to its parts' ratings.

An electrical rules check knows a pin's type. It does not know that the pin dies above 3.6 V, that a
16 V capacitor on a 12 V rail is past its derating, or that a regulator gives 200 mA. This module judges
those from 4 things a project holds: its netlist, the facts of each part, the voltage of each net that
nothing on the board fixes, and a rule pack whose every limit names its document.

This module holds the parts that need no engine: reading the netlist kicad-cli writes, reading a part's
Value, and working out the voltage span of each net. `tools/workcenter` runs kicad-cli. Standard library
only.
"""

from __future__ import annotations

import csv
import datetime
import fnmatch
import itertools
import json
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- the Value of a passive part

# A schematic's Value as its writer meant it: m is milli and M is mega (ngspice reads both as milli, and
# KiCad's own netlist writes 1M as 1Meg). Digits after the multiplier are the decimals: 4k7, 4R7.
MULTIPLIER = {
    "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6, "m": 1e-3, "R": 1.0,
    "k": 1e3, "K": 1e3, "M": 1e6, "Meg": 1e6, "meg": 1e6, "MEG": 1e6, "G": 1e9,
}  # fmt: skip
VALUE_RE = re.compile(r"(\d+)(?:\.(\d+))?(Meg|meg|MEG|[pnuµμmRkKMG])?(\d+)?(?:F|H|Ω|ohm|Ohm|ohms)?")
BARE_RE = re.compile(r"\d+(?:\.\d+)?")  # a number with no prefix and no unit
UNIT_RE = re.compile(r"(?:Meg|meg|MEG|[pnuµμmRkKMG])?(?:F|H|Ω|ohm|Ohm|ohms)?")  # a prefix, a unit or both


def part_value(text: str) -> float | None:
    """The number a Value holds for a resistor, a capacitor or an inductor, in ohms, farads or henries:
    `4k7` is 4700, `100n` is 1e-7, `20m` is 0.02, `1M` is 1e6, and `100 nF` is 1e-7 too. What follows
    the value (`2.2u XAL4020-222`) or a slash (`100nF/50V`) is the part's name or its rating and is
    not read. None when the Value is no number written one of these ways, or holds a bare number
    before a second value (`0402 10k`): a wrong number is a wrong verdict."""
    words = [word.split("/")[0] for word in text.split()]
    if not words:
        return None
    head, rest = words[0], words[1:]
    bare = BARE_RE.fullmatch(head) is not None
    if bare and rest and rest[0] and UNIT_RE.fullmatch(rest[0]):
        head, rest, bare = head + rest[0], rest[1:], False  # `100 nF`: the prefix stands after a space
    found = VALUE_RE.fullmatch(head)
    if not found:
        return None
    whole, decimals, multiplier, after = found.groups()
    if decimals and after:  # 4.7k7
        return None
    if after and not multiplier:
        return None
    if bare and any(VALUE_RE.fullmatch(word) and not BARE_RE.fullmatch(word) for word in rest):
        return None  # `0402 10k`, `1/4W 10k`: 2 numbers, and the bare one is a size or a rating
    return float(f"{whole}.{decimals or after or 0}") * MULTIPLIER.get(multiplier or "R", 1.0)


# ---------------------------------------------------------------- the netlist


@dataclass(frozen=True)
class Node:
    """One pin on a net, as `kicad-cli sch export netlist --format kicadxml` writes it."""

    ref: str
    pin: str  # the pin's number
    name: str  # the pin's name on its symbol; "" for a pin with none (a resistor's)
    kind: str  # KiCad's electrical type: passive, input, output, bidirectional, power_in, power_out, ...
    open: bool  # marked as left open on the sheet (KiCad writes `+no_connect` after the type)


@dataclass
class Part:
    ref: str
    value: str
    footprint: str
    symbol: str  # library:name, as the schematic took it
    in_bom: bool
    fields: dict[str, str] = field(default_factory=dict)
    pins: dict[str, str] = field(default_factory=dict)  # pin number -> net


@dataclass
class Netlist:
    parts: dict[str, Part]
    nets: dict[str, list[Node]]
    absent: list[str] = field(default_factory=list)  # the parts marked DNP: not fitted, so not read


def read_netlist(text: str) -> Netlist:
    """The parts and nets of a netlist in KiCad's XML form. A net of the root sheet is written `/NAME`
    and is NAME here, unless another net has that name already; a net of a sheet below it keeps its
    whole name, `/sub/NAME`. A part marked DNP is not on the board: it is named in `absent` and stands
    on no net. Refuses what it cannot read whole."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ValueError(f"the netlist is not XML: {exc}") from None
    components, nets = root.find("components"), root.find("nets")
    if components is None or nets is None:
        raise ValueError(f"the netlist has no <{'components' if components is None else 'nets'}>")
    parts, absent = {}, []
    for comp in components.findall("comp"):
        source = comp.find("libsource")
        if any(p.get("name") == "dnp" for p in comp.findall("property")):
            absent.append(comp.get("ref", ""))
            continue
        parts[comp.get("ref", "")] = Part(
            ref=comp.get("ref", ""),
            value=comp.findtext("value") or "",
            footprint=comp.findtext("footprint") or "",
            symbol=f"{source.get('lib', '')}:{source.get('part', '')}" if source is not None else "",
            in_bom=all(p.get("name") != "exclude_from_bom" for p in comp.findall("property")),
            fields={f.get("name", ""): f.text or "" for f in comp.findall("fields/field")},
        )
    written = [net.get("name", "") for net in nets.findall("net")]
    out: dict[str, list[Node]] = {}
    for net, raw in zip(nets.findall("net"), written, strict=True):
        root_sheet = raw.startswith("/") and "/" not in raw[1:]
        name = raw[1:] if root_sheet and raw[1:] not in written else raw
        out[name] = []
        for node in net.findall("node"):
            ref, pin = node.get("ref", ""), node.get("pin", "")
            if ref in absent:
                continue
            kind, _, flag = (node.get("pintype") or "").partition("+")
            # kicad-cli 10 writes a pin's name, an underscore and its number: `VDD_3` for pin 3, VDD
            called = (node.get("pinfunction") or "").removesuffix(f"_{pin}")
            out[name].append(Node(ref, pin, called, kind, flag == "no_connect"))
            if ref not in parts:
                raise ValueError(f"net {name} names {ref}, which is no part of the netlist")
            if pin in parts[ref].pins:
                # kicad-cli writes 1 <comp> for 2 symbols of 1 reference, and the pins of both
                raise ValueError(
                    f"{ref} pin {pin} is on {parts[ref].pins[pin]} and on {name}: "
                    f"the schematic holds 2 parts with the reference {ref}"
                )
            parts[ref].pins[pin] = name
    return Netlist(parts, out, absent)


# ---------------------------------------------------------------- resistors between held nets

CORNERS = 4096  # the most corners of resistor tolerances one group is solved at


def _solve(matrix: list[list[float]], right: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting, for the few nodes of one group."""
    n = len(right)
    rows = [row[:] + [right[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(rows[r][col]))
        rows[col], rows[pivot] = rows[pivot], rows[col]
        for r in range(col + 1, n):
            factor = rows[r][col] / rows[col][col]
            for c in range(col, n + 1):
                rows[r][c] -= factor * rows[col][c]
    out = [0.0] * n
    for r in range(n - 1, -1, -1):
        out[r] = (rows[r][n] - sum(rows[r][c] * out[c] for c in range(r + 1, n))) / rows[r][r]
    return out


def _group_volts(
    group: list[str],
    inside: list[tuple[str, str, float, float]],
    ohms: list[float],
    fixed: dict[str, tuple[float, float]],
    ends: dict[str, int],
) -> list[float]:
    """The voltage of each node of 1 group of free nodes, with each resistor at the value given and
    each held node at the end of its span that `ends` names."""
    index = {node: i for i, node in enumerate(group)}
    matrix = [[0.0] * len(group) for _ in group]
    right = [0.0] * len(group)
    for (a, b, _, _), r in zip(inside, ohms, strict=True):
        for near, far in ((a, b), (b, a)):
            if near in index:
                matrix[index[near]][index[near]] += 1 / r
                if far in index:
                    matrix[index[near]][index[far]] -= 1 / r
                else:
                    right[index[near]] += fixed[far][ends[far]] / r
    return _solve(matrix, right)


def resistor_spans(
    resistors: list[tuple[str, str, float, float]],
    held: dict[str, tuple[float, float]],
    drops: dict[tuple[str, str], float] | None = None,
) -> dict[str, tuple[float, float]]:
    """The voltage span of each node that only resistors tie to nodes held at a span.

    resistors: (node, node, least ohms, greatest ohms). held: node -> (least volts, greatest volts).
    A network of resistors puts each free node at a mean of its held nodes with weights that are never
    negative, so a node is highest when every held node is highest. Its voltage is monotone in each
    resistance, so over the tolerances the extreme lies at a corner: each group is solved at every
    corner, up to CORNERS of them. A group with more takes the hull of the held nodes it meets, which
    is coarser and never inside the truth. A node no resistor ties to a held node is left out.

    drops, when given, is filled with (node, node) -> the greatest voltage across the resistors
    between the 2, for each resistor of a solved group: the same solves, with each held node at each
    end of its span in turn, since a drop is greatest with one side up and the other down. The top of
    a divider stands its share, not the whole rail."""
    for a, b, least, greatest in resistors:
        if not 0 <= least <= greatest:
            raise ValueError(f"the resistor between {a} and {b} has the values {least} and {greatest}")
    leader: dict[str, str] = {}

    def find(node: str) -> str:
        leader.setdefault(node, node)
        while leader[node] != node:
            leader[node] = leader[leader[node]]
            node = leader[node]
        return node

    for a, b, _, greatest in resistors:
        find(a), find(b)
        if greatest == 0:  # a link: its 2 nodes are 1
            leader[find(a)] = find(b)
    fixed: dict[str, tuple[float, float]] = {}
    for node, (low, high) in held.items():
        seen = fixed.get(find(node))
        fixed[find(node)] = (low, high) if seen is None else (min(low, seen[0]), max(high, seen[1]))
    links = [(find(a), find(b), least, greatest) for a, b, least, greatest in resistors if greatest > 0]
    links = [link for link in links if link[0] != link[1]]
    free = sorted({n for a, b, _, _ in links for n in (a, b)} - set(fixed))
    spans: dict[str, tuple[float, float]] = dict(fixed)
    across: dict[tuple[str, str], float] = {}  # 2 nodes -> the greatest voltage between them, solved
    group_of: dict[str, int] = {}
    for start in free:
        if start in group_of:
            continue
        group, stack = [], [start]
        while stack:
            node = stack.pop()
            if node in group_of:
                continue
            group_of[node] = len(group_of)
            group.append(node)
            stack += [o for a, b, _, _ in links for n, o in ((a, b), (b, a)) if n == node and o not in fixed]
        inside = [link for link in links if link[0] in group or link[1] in group]
        edge = sorted({n for a, b, _, _ in inside for n in (a, b) if n in fixed})
        if not edge:
            continue
        hull = (min(fixed[n][0] for n in edge), max(fixed[n][1] for n in edge))
        loose = [i for i, link in enumerate(inside) if link[2] != link[3]]
        if 2 ** len(loose) > CORNERS or any(link[2] == 0 for link in inside):
            spans.update(dict.fromkeys(group, hull))
            continue
        index = {node: i for i, node in enumerate(group)}
        lows, highs = [hull[1]] * len(group), [hull[0]] * len(group)
        mixed = drops is not None and 2 ** (len(loose) + len(edge)) <= CORNERS
        for corner in itertools.product((2, 3), repeat=len(loose)):
            ohms = [link[2] for link in inside]
            for i, end in zip(loose, corner, strict=True):
                ohms[i] = inside[i][end]
            for end, best, pick in ((0, lows, min), (1, highs, max)):
                volts_at = _group_volts(group, inside, ohms, fixed, dict.fromkeys(edge, end))
                for i, volts in enumerate(volts_at):
                    best[i] = pick(best[i], volts)
            for picks in itertools.product((0, 1), repeat=len(edge)) if mixed else ():
                ends = dict(zip(edge, picks, strict=True))
                at = dict(zip(group, _group_volts(group, inside, ohms, fixed, ends), strict=True))
                at |= {n: fixed[n][ends[n]] for n in edge}
                for a, b, _, _ in inside:
                    across[(a, b)] = max(across.get((a, b), 0.0), abs(at[a] - at[b]))
        spans.update({node: (lows[index[node]], highs[index[node]]) for node in group})
    for a, b, _, _ in resistors if drops is not None else ():
        pair = (find(a), find(b))
        if pair in across or pair[::-1] in across:
            drops[(a, b)] = across.get(pair, across.get(pair[::-1], 0.0))
    return {node: spans[find(node)] for node in leader if node not in held and find(node) in spans}


# ---------------------------------------------------------------- the span of each net

Span = tuple[float, float]
# KiCad's pin types that put nothing on a net. Of a part with no facts, every other pin may.
QUIET_KINDS = frozenset({"input", "power_in", "no_connect"})


@dataclass(frozen=True)
class Drive:
    """What a pin puts on its net while it drives, from `low` to `high` volts. An end is a number, or
    (pin, plus): the voltage of that pin's net plus `plus`. An output swings from its part's ground
    pin to its supply pin; a regulator's output is 2 numbers."""

    low: float | tuple[str, float]
    high: float | tuple[str, float]


@dataclass
class Model:
    """What 1 part does to the nets it sits on, as far as their voltages go.

    ohms: a resistor between the part's 2 pins, least and greatest. (0, 0) joins them.
    links: pairs of pins that are 1 node: a fuse, a ferrite, a jumper.
    passes: (pin, pin, one_way). The 2 pins conduct or not, and nothing says which: a transistor's
        channel, a switch, an inductor. one_way is a diode from the first pin to the second.
    drives: pin -> what it puts on its net.
    quiet: the pins that put nothing on their net. None: every pin not named above is quiet (a
        capacitor). A set: a pin in none of these is a source nothing describes."""

    ohms: Span | None = None
    links: list[tuple[str, str]] = field(default_factory=list)
    passes: list[tuple[str, str, bool]] = field(default_factory=list)
    drives: dict[str, Drive] = field(default_factory=dict)
    quiet: frozenset[str] | None = None


@dataclass
class Spans:
    """stress: every voltage a net can stand at, with its sources on or off and each output driving
    or released; 0 V is always inside, since any net can be unpowered. A rating is held to it.
    held: what a net's own sources hold it to while they are on. A supply pin's working range is held
    to it. why: for a net with no span, the reason. drops: resistor -> the greatest voltage across it,
    for a resistor with an end that resistors alone hold: solved with its nets, not taken from the
    extremes of the 2 apart. node: net -> its node; the nets a wire joins (a fuse, a ferrite, a link, a
    0 ohm resistor, an inductor) are 1 node, and no voltage stands between 2 of them."""

    stress: dict[str, Span]
    held: dict[str, Span]
    why: dict[str, str]
    drops: dict[str, float] = field(default_factory=dict)
    node: dict[str, str] = field(default_factory=dict)


def _hull(spans: list[Span]) -> Span:
    return (min(s[0] for s in spans), max(s[1] for s in spans))


def net_spans(
    net: Netlist,
    models: dict[str, Model],
    declared: dict[str, Span],
    without: str | tuple[str, str] = "",
    forced: dict[str, Span] | None = None,
    fed: dict[str, list[tuple[str, Span]]] | None = None,
) -> Spans:
    """The spans of every net, from the nets the project declares and what each part's model says.

    A net takes the hull of all that can reach it: its own sources, every net it meets through a part
    that may conduct, and, unless a declaration or a regulator holds it, every net it meets through a
    resistor: a released output follows its pull-up. A group of nets that resistors alone tie to
    others, with no source of its own, is solved (resistor_spans): a divider's tap is not its top
    rail. A net that a source nothing describes can reach has no span, unless the project declares it.
    Not modelled: a resistor from a higher rail that lifts a regulator's output while it is off.

    without: (part, pin), a pin whose own drive is left out: a pin is rated against what the others
    put on its net, never against itself, and another pin of its part is another source. An output a
    divider sets (fed) is never left out: the board sets it, and the pin has to stand it. A part's
    name alone leaves out every source of the part.
    forced: nets taken at a span whatever their sources give: a rail at its least, to judge a pin
    whose limit follows that rail.
    fed: net -> (the regulator, the span it holds the net at) for an output no pin's model gives: one
    a divider sets (divider_output)."""
    forced = forced or {}
    declared = {**declared, **forced}
    for name in declared:
        if name not in net.nets:
            raise ValueError(f"the declared net {name} is no net of the schematic")
    leader = {name: name for name in net.nets}

    def find(name: str) -> str:
        while leader[name] != name:
            leader[name] = leader[leader[name]]
            name = leader[name]
        return name

    def nets_of(ref: str, pins: tuple[str, ...]) -> list[str]:
        missing = [p for p in pins if p not in net.parts[ref].pins]
        if missing:
            raise ValueError(f"the facts of {ref} name pin {missing[0]}, which its symbol does not have")
        return [net.parts[ref].pins[p] for p in pins]

    kind_of = {(n.ref, n.pin): n.kind for nodes in net.nets.values() for n in nodes}
    for ref, part in net.parts.items():
        model = models.get(ref)
        if model is None:
            continue
        pairs = list(model.links)
        if model.ohms is not None:
            if len(part.pins) != 2:
                raise ValueError(f"{ref} is given a resistance and has {len(part.pins)} pins, not 2")
            if model.ohms[1] == 0:
                pairs.append(tuple(part.pins))
        for pair in pairs:
            a, b = nets_of(ref, pair)
            leader[find(a)] = find(b)

    held_by: dict[str, list[Span]] = {}  # node -> the spans its own sources give
    for name, span in declared.items():
        held_by.setdefault(find(name), []).append(span)
    stated = set(held_by)  # nodes the project declares: nothing takes their span away
    pinned = {find(name) for name in forced}  # nodes taken at a span: their parts' drives are left out
    onboard: set[str] = set()  # nodes a part of the board holds: a regulator, a pin that drives
    for name, regulators in (fed or {}).items():
        for ref, span in regulators:
            if ref != without and find(name) not in pinned:
                held_by.setdefault(find(name), []).append(span)
                onboard.add(find(name))
    swings: list[tuple[str, str, str, Drive]] = []  # node, ref, pin, a drive that follows other pins
    unknown: dict[str, str] = {}  # node -> why it has no span
    edges: list[tuple[str, str, bool, str]] = []  # node, node, one_way, the part that joins them
    resistors: list[tuple[str, str, float, float, str]] = []
    for ref, part in net.parts.items():
        model = models.get(ref)
        if model is not None and model.ohms is not None and model.ohms[1] > 0:
            a, b = (find(n) for n in part.pins.values())
            if a != b:
                resistors.append((a, b, *model.ohms, ref))
        for a_pin, b_pin, one_way in model.passes if model is not None else ():
            a, b = (find(n) for n in nets_of(ref, (a_pin, b_pin)))
            if a != b:
                edges.append((a, b, one_way, ref))
        if ref == without:
            continue
        own = without[1] if isinstance(without, tuple) and without[0] == ref else None
        named = set()
        if model is not None:
            named = {p for pair in model.links for p in pair} | {
                p for a, b, _ in model.passes for p in (a, b)
            }
            for pin, drive in model.drives.items():
                (name,) = nets_of(ref, (pin,))
                if find(name) in pinned or pin == own:
                    continue
                if isinstance(drive.low, tuple) or isinstance(drive.high, tuple):
                    swings.append((find(name), ref, pin, drive))
                else:
                    held_by.setdefault(find(name), []).append((drive.low, drive.high))
                    onboard.add(find(name))
        for pin, name in part.pins.items():
            if model is None:
                silent = kind_of[(ref, pin)] in QUIET_KINDS
            else:
                silent = (
                    model.ohms is not None
                    or pin in named
                    or pin in model.drives
                    or model.quiet is None
                    or pin in model.quiet
                    or pin == own
                )
            if not silent and find(name) not in stated:
                unknown.setdefault(
                    find(name), f"{ref} pin {pin} can put a voltage on {name} that nothing states"
                )

    # A resistor does not move a net that a declaration or a regulator holds; a released output it does.
    # A part that may conduct joins 2 such nets all the same: a closed switch between 2 sources. Nothing
    # moves a net the project declares at 0 V, the reference every other voltage is counted from.
    stiff = set(held_by)
    ground = {find(name) for name, span in declared.items() if span == (0.0, 0.0)}
    joins = [(e[0], e[1], e[3], stated) for e in edges] + [(r[0], r[1], r[4], stiff) for r in resistors]
    # A net the project states and no part of the board holds has its source off the board: with the
    # cable out or the driver released, a resistor to another rail moves it. Its held span stays.
    firm = onboard | ground | pinned

    def spread(reasons: dict[str, str]) -> None:
        """A net that meets one with no span, through a resistor or a part that may conduct, has none,
        unless it is one that such a part cannot move."""
        stack = list(reasons)
        while stack:
            node = stack.pop()
            for a, b, ref, firm in joins:
                for near, far in ((a, b), (b, a)):
                    if near == node and far not in firm and far not in reasons:
                        root = reasons[node].split("; ")[0]
                        reasons[far] = f"{root}; {ref} joins the 2 nets"
                        stack.append(far)

    spread(unknown)
    while True:
        span: dict[str, Span] = {}
        for node, spans in held_by.items():
            if node not in unknown:
                span[node] = _hull([*spans, (0.0, 0.0)])

        def widen(node: str, low: float, high: float, span: dict[str, Span] = span) -> bool:
            before = span.get(node)
            after = (
                (min(low, 0.0), max(high, 0.0))
                if before is None
                else (min(before[0], low), max(before[1], high))
            )
            span[node] = after
            return after != before

        def end(
            ref: str, value: float | tuple[str, float], which: int, span: dict[str, Span] = span
        ) -> float | None:
            if not isinstance(value, tuple):
                return value
            (name,) = nets_of(ref, (value[0],))
            return span[find(name)][which] + value[1] if find(name) in span else None

        def reach(ref: str, drive: Drive) -> tuple[float | None, float | None]:
            """The least and the greatest a drive gives. A pin that swings between 2 pins reaches both,
            whichever of the 2 its facts name first."""
            lows = [end(ref, value, 0) for value in (drive.low, drive.high)]
            highs = [end(ref, value, 1) for value in (drive.low, drive.high)]
            if not (isinstance(drive.low, tuple) and isinstance(drive.high, tuple)):
                return lows[0], highs[1]
            if None in lows or None in highs:
                return None, None
            return min(lows), max(highs)

        changed = True
        while changed:
            changed = False
            for node, ref, _, drive in swings:
                low, high = reach(ref, drive)
                if node not in unknown and low is not None and high is not None:
                    changed |= widen(node, low, high)
            for a, b, one_way, _ in edges:
                if a in unknown or b in unknown:
                    continue
                if a in span and b not in ground:  # the first pin lifts the second
                    changed |= widen(b, 0.0 if one_way else span[a][0], span[a][1])
                if b in span and a not in ground:  # the second pin pulls the first down
                    changed |= widen(a, span[b][0], 0.0 if one_way else span[b][1])
            for a, b, *_ in resistors:
                if a in unknown or b in unknown:
                    continue
                if a in span and b not in firm:
                    changed |= widen(b, *span[a])
                if b in span and a not in firm:
                    changed |= widen(a, *span[b])
        stuck = {}
        for node, ref, pin, drive in swings:
            for value, which in ((drive.low, 0), (drive.high, 1)):
                if node not in unknown and node not in stated and end(ref, value, which) is None:
                    (other,) = nets_of(ref, (value[0],))
                    stuck[node] = (
                        f"{ref} pin {pin} swings with its pin {value[0]} on {other}, which has no span"
                    )
        if not stuck:
            break
        unknown.update(stuck)
        spread(unknown)

    held: dict[str, Span] = {}
    sources = {node: list(spans) for node, spans in held_by.items()}
    for node, ref, _, drive in swings:
        low, high = reach(ref, drive)
        if node in span and low is not None and high is not None:
            sources.setdefault(node, []).append((low, high))
    for node, spans in sources.items():
        if node in span:
            held[node] = _hull(spans)

    busy = {n for e in edges for n in e[:2]} | set(sources)
    loose = {n for r in resistors for n in r[:2] if n in span and n not in busy}
    across: dict[tuple[str, str], float] = {}
    solved = resistor_spans(
        [r[:4] for r in resistors if r[0] in loose or r[1] in loose],
        {n: span[n] for r in resistors for n in r[:2] if n in span and n not in loose},
        across,
    )
    for node in loose & set(solved):
        span[node] = (min(solved[node][0], 0.0), max(solved[node][1], 0.0))

    out = Spans({}, {}, {})
    out.drops = {r[4]: across[(r[0], r[1])] for r in resistors if (r[0], r[1]) in across}
    for name, nodes in net.nets.items():
        node = out.node[name] = find(name)
        if node in span:
            out.stress[name] = span[node]
            if node in held:
                out.held[name] = held[node]
        elif len(nodes) > 1 or node != name:
            out.why[name] = unknown.get(node, "nothing drives it")
    return out


# ---------------------------------------------------------------- the files a project holds


class Refusal(ValueError):
    """A file the command does not take. The message names the file, the place in it and what is wrong."""


def _json(path: Path) -> object:
    def once(pairs: list[tuple[str, object]]) -> dict:
        """An object whose every key stands 1 time: JSON's own reader keeps the last and says nothing."""
        seen: dict[str, object] = {}
        for key, value in pairs:
            if key in seen:
                raise Refusal(f"{path.name}: `{key}` stands 2 times")
            seen[key] = value
        return seen

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=once)
    except OSError as exc:
        raise Refusal(f"{path.name}: {exc.strerror}") from None
    except Refusal:
        raise
    except UnicodeDecodeError as exc:
        raise Refusal(f"{path.name}: not UTF-8: {exc}") from None
    except ValueError as exc:
        raise Refusal(f"{path.name}: not JSON: {exc}") from None
    except RecursionError:  # thousands of lists in each other: JSON's reader follows each one deeper
        raise Refusal(f"{path.name}: not JSON: nested deeper than a file of the command is") from None


def _keys(where: str, data: object, required: tuple[str, ...], optional: tuple[str, ...] = ()) -> dict:
    """An object with every required key and no key outside the 2 lists."""
    known = required + optional
    if not isinstance(data, dict):
        raise Refusal(f"{where}: an object is asked, with the keys {', '.join(known)}")
    for key in data:
        if key not in known:
            raise Refusal(f"{where}: `{key}` is no key here; the keys are {', '.join(known)}")
    for key in required:
        if key not in data:
            raise Refusal(f"{where}: `{key}` is missing")
    return data


def _object(where: str, value: object, of: str) -> dict:
    """An object whose keys are the writer's own: the nets, the parts."""
    if not isinstance(value, dict):
        raise Refusal(f"{where}: an object is asked, with 1 key for each {of} it states")
    return value


# Every number of a file is 0 or lies between these 2 on either side of it. No volt, amp, ohm, farad,
# hertz or degree of a board is outside, and inside them the square of a number and the product of 2
# stay numbers: 1e308 V squared is none, and 1e-320 Hz times an inductance is 0, which a ripple is
# divided by. JSON also writes whole numbers of any length, which no float holds.
SMALLEST, GREATEST = 1e-18, 1e15


def _number(
    where: str,
    value: object,
    least: float | None = None,
    most: float | None = None,
    above: float | None = None,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise Refusal(f"{where}: {value!r} is no number")
    if isinstance(value, float) and not math.isfinite(value):
        raise Refusal(f"{where}: {value!r} is no number")
    if value and not SMALLEST <= abs(value) <= GREATEST:
        raise Refusal(f"{where}: a number is 0, or from {SMALLEST:g} to {GREATEST:g} either side of 0")
    if least is not None and value < least:
        raise Refusal(f"{where}: {value:g} is under {least:g}")
    if most is not None and value > most:
        raise Refusal(f"{where}: {value:g} is over {most:g}")
    if above is not None and value <= above:
        raise Refusal(f"{where}: {value:g} is not above {above:g}")
    return float(value)


def _span(where: str, value: object) -> Span:
    if not isinstance(value, list) or len(value) != 2:
        raise Refusal(f"{where}: a span is asked, [least, greatest]")
    low, high = _number(where, value[0]), _number(where, value[1])
    if low > high:
        raise Refusal(f"{where}: the span's first number, {low:g}, is above its second, {high:g}")
    return (low, high)


def _text(where: str, value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Refusal(f"{where}: text is asked, and there is none")
    return value.strip()


def _names(where: str, value: object) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v for v in value):
        raise Refusal(f"{where}: a list of names is asked")
    return value


def _page(where: str, value: object) -> None:
    """A page of the source: a number from 1, or a list of them for facts read on more than 1 page."""
    pages = value if isinstance(value, list) and value else [value]
    if not all(isinstance(p, int) and not isinstance(p, bool) and p > 0 for p in pages):
        raise Refusal(f"{where}: page: a page number is asked, or a list of them")


def _p(page: int | list[int]) -> str:
    """A page as a finding's source names it: `p 4`, `p 4 and 5`."""
    pages = [str(p) for p in (page if isinstance(page, list) else [page])]
    return "p " + (", ".join(pages[:-1]) + " and " + pages[-1] if len(pages) > 1 else pages[0])


DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
URL_RE = re.compile(r"[a-z][a-z0-9+.-]*://\S+")
SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


def _date(where: str, value: object, or_no: bool = False) -> None:
    """A date the calendar has, as YYYY-MM-DD. `no` too where a second reader may not have read yet:
    any other word there would count as a reading."""
    if or_no and value == "no":
        return
    try:
        if not isinstance(value, str) or not DATE_RE.fullmatch(value):
            raise ValueError
        datetime.date.fromisoformat(value)
    except ValueError:
        raise Refusal(f"{where}: write {'`no`, or ' if or_no else ''}the date as YYYY-MM-DD") from None


def _source(where: str, source: dict) -> None:
    """Where a document stands and who read it: a URL from its scheme on, the SHA256 of the file as 64
    hex digits, the date it was read, and the date a second reader read it or `no`. A source may hold
    no URL and no SHA256; a word in their place is none."""
    if "url" in source and not URL_RE.fullmatch(source["url"]):
        raise Refusal(f"{where}: url: a whole URL is asked, as https://example.com/file.pdf")
    if "sha256" in source and not SHA256_RE.fullmatch(source["sha256"]):
        raise Refusal(f"{where}: sha256: 64 hex digits are asked")
    _date(f"{where}: read", source["read"])
    _date(f"{where}: second_reader", source["second_reader"], or_no=True)


# ---------------------------------------------------------------- a rule pack

# The stresses the command computes. A pack gives each a factor and the place in its document.
STRESSES = (
    "capacitor.voltage",
    "resistor.voltage",
    "resistor.power",
    "diode.reverse",
    "diode.forward_current",
    "mosfet.drain_source",
    "mosfet.gate_source",
    "mosfet.drain_current",
    "fuse.current",
    "ferrite.current",
    "switch.current",
    "rail.load",
)
DOCUMENT_KEYS = ("issuer", "number", "title", "revision", "url", "sha256", "read", "second_reader")
# The stress the SIM gate judges (tools/thermal.py): a junction's temperature, held to a limit in C.
JUNCTION = "junction.temperature"
JUNCTION_LIMITS = ("celsius", "share", "below_rating")


@dataclass(frozen=True)
class JunctionRule:
    """A junction's derated limit: the least of a temperature, a share of the part's greatest junction
    temperature, and that temperature less a margin, as many of the 3 as the document names."""

    id: str
    kinds: tuple[str, ...]
    celsius: float | None
    share: float | None
    below: float | None
    where: str


@dataclass(frozen=True)
class Rule:
    id: str
    stress: str
    kinds: tuple[str, ...]
    max: float  # the share of the part's rating the stress may reach
    where: str  # the clause, the table and the page of the pack's document
    above: tuple[str, float, float, float] | None  # ambient or case, from this C, falls to, at this C


@dataclass
class Pack:
    name: str
    document: dict[str, str]
    rules: list[Rule]
    junction: list[JunctionRule] = field(default_factory=list)

    def rule(self, stress: str, kind: str) -> Rule | None:
        """The rule for a stress on a part kind: `capacitor` covers `capacitor.ceramic`."""
        for rule in self.rules:
            if rule.stress == stress and any(kind == k or kind.startswith(k + ".") for k in rule.kinds):
                return rule
        return None

    def junction_rule(self, kind: str) -> JunctionRule | None:
        """The first junction rule that covers a part kind, `ic.regulator.linear` or `diode.clamp`."""
        return next(
            (r for r in self.junction if any(kind == k or kind.startswith(k + ".") for k in r.kinds)), None
        )


def read_pack(path: Path, own: str = "") -> Pack:
    """A rule pack. `own` is the path ratings.json names a pack of the project's own by: the pack then
    goes by that path, and every line that names it says whose it is. The name inside such a file is
    its writer's word, and a copy of a shipped pack keeps the shipped pack's."""
    data = _keys(path.name, _json(path), ("pack", "document", "rules"))
    document = _keys(f"{path.name}: document", data["document"], DOCUMENT_KEYS)
    for key in DOCUMENT_KEYS:
        _text(f"{path.name}: document: {key}", document[key])
    _source(f"{path.name}: document", document)
    if not isinstance(data["rules"], list) or not data["rules"]:
        raise Refusal(f"{path.name}: rules: a list of rules is asked")
    rules: list[Rule] = []
    junction: list[JunctionRule] = []
    for i, raw in enumerate(data["rules"], start=1):
        where = f"{path.name}: rule {i}"
        if isinstance(raw, dict) and raw.get("stress") == JUNCTION:
            rule = _keys(where, raw, ("id", "stress", "kinds", "where"), JUNCTION_LIMITS)
        else:
            rule = _keys(where, raw, ("id", "stress", "kinds", "max", "where"), ("above",))
        if rule["stress"] not in (*STRESSES, JUNCTION):
            known = ", ".join((*STRESSES, JUNCTION))
            raise Refusal(f"{where}: `{rule['stress']}` is no stress the command computes; they are {known}")
        if _text(f"{where}: id", rule["id"]) in {r.id for r in [*rules, *junction]}:
            raise Refusal(f"{where}: the id `{rule['id']}` stands 2 times")
        # a kind no part has holds nothing: its parts would be held to their own ratings without a word
        known = [*PASSIVE, *OTHER, *(f"ic.{family}" for family in FAMILIES)]
        for kind in _names(f"{where}: kinds", rule["kinds"]):
            if not any(k == kind or k.startswith(f"{kind}.") for k in known):
                raise Refusal(
                    f"{where}: kinds: `{kind}` names no kind of part; a rule names a kind of the facts or "
                    "its start, as capacitor for capacitor.ceramic"
                )
        if rule["stress"] == JUNCTION:
            if not any(key in rule for key in JUNCTION_LIMITS):
                raise Refusal(f"{where}: 1 limit at least is asked, of {', '.join(JUNCTION_LIMITS)}")
            junction.append(
                JunctionRule(
                    rule["id"],
                    tuple(rule["kinds"]),
                    _number(f"{where}: celsius", rule["celsius"]) if "celsius" in rule else None,
                    _number(f"{where}: share", rule["share"], most=1, above=0) if "share" in rule else None,
                    _number(f"{where}: below_rating", rule["below_rating"], 0)
                    if "below_rating" in rule
                    else None,
                    _text(f"{where}: where", rule["where"]),
                )
            )
            continue
        most = _number(f"{where}: max", rule["max"], 0, 1)
        above = None
        if "above" in rule:
            term = _keys(f"{where}: above", rule["above"], ("temperature", "celsius", "falls_to", "at"))
            if term["temperature"] not in ("ambient", "case"):
                raise Refusal(f"{where}: above: temperature is `ambient` or `case`")
            above = (
                term["temperature"],
                _number(f"{where}: above: celsius", term["celsius"]),
                _number(f"{where}: above: falls_to", term["falls_to"], 0, 1),
                _number(f"{where}: above: at", term["at"]),
            )
            if above[3] <= above[1]:
                raise Refusal(f"{where}: above: `at` is not above `celsius`")
            if above[2] > most:  # a share that rises with the temperature is no derating
                raise Refusal(f"{where}: above: `falls_to` is above `max`")
        rules.append(
            Rule(
                _text(f"{where}: id", rule["id"]),
                rule["stress"],
                tuple(_names(f"{where}: kinds", rule["kinds"])),
                most,
                _text(f"{where}: where", rule["where"]),
                above,
            )
        )
    name = _text(f"{path.name}: pack", data["pack"])
    return Pack(f"{own} (the project's own)" if own else name, document, rules, junction)


def factor(rule: Rule, ambient: float | None) -> tuple[float, str]:
    """The share a rule allows at the project's ambient temperature, and what the report says of it."""
    if rule.above is None:
        return rule.max, ""
    kind, knee, floor, end = rule.above
    if ambient is None:
        return rule.max, f"{rule.id}: judged as under {knee:g} C, since the project states no ambient"
    note = "" if kind == "ambient" else f"{rule.id}: the part's own heating above the ambient is not counted"
    if ambient <= knee:
        return rule.max, note
    if ambient > end:  # past the last temperature the document names, the part is not allowed
        return 0.0, note
    if ambient == end:
        return floor, note
    return rule.max + (floor - rule.max) * (ambient - knee) / (end - knee), note


# ---------------------------------------------------------------- a project's ratings.json

OWNER_RE = re.compile(r"the owner's decision of \d{4}-\d{2}-\d{2}")


@dataclass
class Project:
    pack: str
    ambient: float | None
    nets: dict[str, Span]  # the nets nothing on the board fixes, by the netlist's own names
    amps: dict[str, float]  # `R5`, or `J6.1` for 1 pin: a current nothing on the board gives
    # (part, rule) -> the owner's words for the report, or a list of (words of the 1 failure's line
    # that an entry means, the owner's words): an entry accepts 1 failure
    accepted: dict[tuple[str, str], str | list[tuple[str, str]]]
    # `C7`: the greatest voltage across a part of 2 pins, where the spans of its 2 nets cannot give it
    volts: dict[str, float] = field(default_factory=dict)
    # `U1`, or `U1.2` for 1 pad: the heat a part gives off, which `workcenter copper` spreads through
    # the board from its pads, or from the pad named
    watts: dict[str, float] = field(default_factory=dict)
    # (part, text, source): what a block or the designer states it could not judge, printed as not judged
    unjudged: list[tuple[str, str, str]] = field(default_factory=list)


def read_project(path: Path, net: Netlist) -> Project:
    """A project's ratings.json, held to the netlist: a net or a part it names is one of the schematic."""
    name = path.name
    data = _keys(name, _json(path), ("pack", "nets"), ("ambient", "parts", "accepted", "not_judged"))
    nets: dict[str, Span] = {}
    stated: dict[str, str] = {}  # a net of the schematic -> the key that states it
    for key, raw in _object(f"{name}: nets", data["nets"], "net").items():
        entry = _keys(f"{name}: nets: {key}", raw, ("volts", "source"))
        _text(f"{name}: nets: {key}: source", entry["source"])
        found = next((n for n in (key, key.lstrip("/"), f"/{key}") if n in net.nets), None)
        if found is None:
            raise Refusal(f"{name}: nets: {key}: no net of the schematic has this name")
        if found in stated:  # with and without its sheet's slash: the second span would replace the first
            raise Refusal(f"{name}: nets: {key}: this net stands 2 times, as {stated[found]} and as {key}")
        stated[found] = key
        nets[found] = _span(f"{name}: nets: {key}: volts", entry["volts"])
    ambient = None
    if "ambient" in data:
        entry = _keys(f"{name}: ambient", data["ambient"], ("max", "source"))
        _text(f"{name}: ambient: source", entry["source"])
        ambient = _number(f"{name}: ambient: max", entry["max"])
    amps: dict[str, float] = {}
    volts: dict[str, float] = {}
    watts: dict[str, float] = {}
    for key, raw in _object(f"{name}: parts", data.get("parts", {}), "part or pin").items():
        entry = _keys(f"{name}: parts: {key}", raw, ("source",), ("amps", "volts", "watts"))
        _text(f"{name}: parts: {key}: source", entry["source"])
        ref, _, pin = key.partition(".")
        if ref not in net.parts or (pin and pin not in net.parts[ref].pins):
            raise Refusal(
                f"{name}: parts: {key}: the schematic has no such part" + (" and pin" if pin else "")
            )
        if not any(k in entry for k in ("amps", "volts", "watts")):
            raise Refusal(f"{name}: parts: {key}: `amps`, `volts` or `watts` is asked")
        if "watts" in entry:
            watts[key] = _number(f"{name}: parts: {key}: watts", entry["watts"], 0)
        if "amps" in entry:
            amps[key] = _number(f"{name}: parts: {key}: amps", entry["amps"], 0)
        if "volts" in entry:
            if pin or len(net.parts[ref].pins) != 2:
                raise Refusal(f"{name}: parts: {key}: volts: the voltage across a part of 2 pins is asked")
            volts[key] = _number(f"{name}: parts: {key}: volts", entry["volts"], 0)
    for key in watts:  # a part's heat on the part, or on its pads: both would count it twice
        ref, _, pin = key.partition(".")
        if pin and ref in watts:
            raise Refusal(
                f"{name}: parts: {key}: watts: {ref} states the whole part's heat; state it on the part or "
                "on its pads, not both"
            )
    accepted: dict[tuple[str, str], list[tuple[str, str]]] = {}
    first: dict[tuple[str, str, str], int] = {}
    if not isinstance(data.get("accepted", []), list):
        raise Refusal(f"{name}: accepted: a list is asked")
    for i, raw in enumerate(data.get("accepted", []), start=1):
        where = f"{name}: accepted: entry {i}"
        entry = _keys(where, raw, ("part", "rule", "why", "by"), ("line",))
        if not OWNER_RE.fullmatch(_text(f"{where}: by", entry["by"])):
            raise Refusal(f"{where}: by: write `the owner's decision of YYYY-MM-DD`")
        day = entry["by"].rsplit(" ", 1)[1]
        try:
            datetime.date.fromisoformat(day)
        except ValueError:
            said = f"`{day}` is no date: write `the owner's decision of YYYY-MM-DD`"
            raise Refusal(f"{where}: by: {said}") from None
        if "line" in entry and not (isinstance(entry["line"], str) and entry["line"].strip()):
            raise Refusal(f"{where}: line: words of the failure's line are asked")
        words = f"{_text(f'{where}: why', entry['why'])} ({entry['by']})"
        key = (_text(f"{where}: part", entry["part"]), _text(f"{where}: rule", entry["rule"]))
        piece = entry.get("line", "")
        if (*key, piece) in first:
            raise Refusal(f"{where}: entry {first[(*key, piece)]} accepts the same part, rule and line")
        first[(*key, piece)] = i
        accepted.setdefault(key, []).append((piece, words))
    unjudged: list[tuple[str, str, str]] = []
    for key, raw in _object(f"{name}: not_judged", data.get("not_judged", {}), "item").items():
        where = f"{name}: not_judged: {key}"
        entry = _keys(where, raw, ("parts", "why", "source"))
        refs = entry["parts"]
        if (
            not isinstance(refs, list)
            or not refs
            or any(not isinstance(r, str) or r not in net.parts for r in refs)
        ):
            raise Refusal(f"{where}: parts: a list of parts of the schematic is asked")
        why, source = _text(f"{where}: why", entry["why"]), _text(f"{where}: source", entry["source"])
        unjudged.append((refs[0], f"{key}: {why}", source))
    pack = _text(f"{name}: pack", data["pack"])
    return Project(pack, ambient, nets, amps, accepted, volts, watts, unjudged)


# ---------------------------------------------------------------- the facts of a part

SOURCE_KEYS = (("document", "read", "second_reader"), ("revision", "url", "sha256"))
WHICH = ("mpn", "mpns", "match", "symbol")  # how an entry names the parts it speaks of: exactly 1 of these
# A capacitor's kind alone says it passes no steady current: an entry with no rating keeps its nets
# judged, and the capacitor's own voltage is then the 1 thing the report cannot judge.
CAPACITOR = ((), ("tolerance", "volts", "farads", "dielectric", "kept", "kept_celsius"))
PASSIVE = {  # kind -> the keys an entry must hold, and those it may
    "resistor": (("tolerance", "watts", "volts"), ("ohms",)),
    "capacitor.ceramic": CAPACITOR,
    "capacitor.tantalum": CAPACITOR,
    "capacitor.film": CAPACITOR,
    "capacitor.electrolytic": CAPACITOR,
    # an inductor's `kept` is pairs [amps, share of the value kept]: the SIM gate's, not judged here
    "inductor": (("tolerance", "amps_saturation"), ("henries", "amps_rms", "kept")),
    "ferrite": ((), ("amps", "volts")),
    "fuse": (("amps",), ("volts",)),
    "link": ((), ()),
    "switch": ((), ("amps", "volts")),
    "testpoint": ((), ()),
    "mechanical": ((), ()),
}
OTHER = {
    "connector": ((), ("pins",)),
    # a rectifier, a switching or a Schottky diode is rated for a reverse voltage; a clamp (a zener, a
    # TVS) stands off its working voltage and conducts above it
    "diode.rectifier": (("diodes", "volts_reverse"), ("amps_forward", "thermal")),
    "diode.clamp": (("diodes", "volts_standoff"), ("thermal",)),
    "transistor.mosfet": (
        ("transistors", "volts_drain_source", "volts_gate_source"),
        ("amps_drain", "watts", "thermal"),
    ),
    "ic": (("family", "pins"), ("needs", "switching", "thermal")),
}
# The figures of a datasheet's thermal table, in C/W, as TI SPRA953D names them: the junction to the
# ambient, to the case, to the board, and the 2 characterisation parameters to the package's top and the
# board.
FIGURES = ("theta_ja", "theta_jc", "theta_jb", "psi_jt", "psi_jb")
FAMILIES = ("digital", "linear", "regulator.linear", "regulator.switching")
# The keys that hold a rating, or a value a current is divided by. Each is above 0: a stress is a share
# of its rating, and 0 V, 0 W, 0 A, 0 F and 0 H are wrong facts and no division. `ohms` may be 0, a link.
RATED = (
    "farads",
    "henries",
    "watts",
    "volts",
    "amps",
    "amps_saturation",
    "amps_rms",
    "volts_reverse",
    "volts_standoff",
    "volts_drain_source",
    "volts_gate_source",
    "amps_forward",
)
# A pin's role -> the keys it must hold beside numbers, name, role and page, and those it may.
# regulated: the pin its regulator holds at `volts`, or, with `set_by`, at what the divider on its
# feedback pin sets. feedback: the pin its regulator holds at `volts` through a divider from its output.
# `amps` of the 2 is what the regulator gives; `from` names the supply pin that current comes from.
ROLES = {
    "supply": (("abs",), ("operating", "amps")),
    "ground": ((), ()),
    "input": (("abs",), ("operating",)),
    "analog": (("abs",), ("operating",)),
    "output": (("abs", "swing"), ("amps", "operating")),
    "io": (("abs", "swing"), ("amps", "operating")),
    "open_drain": (("abs", "swing"), ("amps", "operating")),
    # a reference's output may stand in no table of limits: `abs` is then left out, and a note says so
    "regulated": ((), ("abs", "volts", "set_by", "amps", "from")),
    "feedback": (("abs", "volts"), ("amps", "from")),
    "switched": (("abs", "swing"), ()),
    "nc": ((), ()),
}
SWING = {"output": 2, "io": 2, "switched": 2, "open_drain": 1}  # how many pins a role's swing names
OUTSIDE = ("source", "load", "nothing")  # what stands behind a connector's pin
# TI SLVA477C, "Basic Calculation of a Buck Converter's Power Stage" (revised September 2026): the
# efficiency its section 2 names for a duty cycle when a datasheet gives none, and where its sums stand.
BUCK_EFFICIENCY = 0.9
BUCK_NOTE = "TI SLVA477C, equations 1, 2 and 4"
DIVIDER_NOTE = "TI SLVA477C, equation 11"


@dataclass
class Facts:
    """What a datasheet says of 1 part, or of every part a pattern names."""

    where: str  # the file, and the entry's place in it
    kind: str
    data: dict

    def speaks_of(self, mpn: str, symbol: str, footprint: str) -> int:
        """How closely the entry names a part: 3 by its part number, 2 by a pattern of it, 1 by its
        symbol (and its footprint, when the entry names one), 0 not at all. A symbol's entry speaks
        only of a part with no part number: a part that has one is another part until an entry names
        its number."""
        data = self.data
        if mpn and (data.get("mpn") == mpn or mpn in data.get("mpns", ())):
            return 3
        if mpn and "match" in data and fnmatch.fnmatchcase(mpn, data["match"]):
            return 2
        by_symbol = data.get("symbol") == symbol and fnmatch.fnmatchcase(
            footprint, data.get("footprint", "*")
        )
        return 1 if by_symbol and not mpn else 0

    @property
    def name(self) -> str:
        """The part number, the pattern or the symbol the entry names its parts by."""
        data = self.data
        return data.get("mpn") or data.get("match") or data.get("symbol") or data["mpns"][0]

    @property
    def source(self) -> str:
        source = self.data["source"]
        return ", ".join(v for v in (source["document"], source.get("revision", "")) if v)

    @property
    def read_twice(self) -> bool:
        return self.data["source"]["second_reader"] != "no"


def _limit(where: str, value: object) -> None:
    """A limit: a number, {"pin": NAME, "plus": X} for another pin's voltage plus X, or a list of such."""
    for one in value if isinstance(value, list) and value else [value]:
        if isinstance(one, dict):
            _keys(where, one, ("pin", "plus"))
            _text(f"{where}: pin", one["pin"])
            _number(f"{where}: plus", one["plus"])
        else:
            _number(where, one)


def _ordered(where: str, low: object, high: object) -> None:
    """The 2 ends of a span of limits stand least first. A number is held to a number, and a limit that
    follows a pin to one that follows the same pin, by what each adds. A number and a limit that
    follows a pin cannot be held to each other."""
    for a in low if isinstance(low, list) else [low]:
        for b in high if isinstance(high, list) else [high]:
            if isinstance(a, dict) and isinstance(b, dict):
                if a["pin"] == b["pin"] and a["plus"] > b["plus"]:
                    first, second = (f"pin {one['pin']} {one['plus']:+g}" for one in (a, b))
                    raise Refusal(f"{where}: the span's first limit, {first}, is above its second, {second}")
            elif not isinstance(a, dict) and not isinstance(b, dict) and a > b:
                raise Refusal(f"{where}: the span's first number, {a:g}, is above its second, {b:g}")


def _pin_facts(where: str, pins: object) -> None:
    if not isinstance(pins, list) or not pins:
        raise Refusal(f"{where}: pins: a list of pins is asked")
    # a name or a role that is no text is refused at its own pin, below
    named = [p for p in pins if isinstance(p, dict) and isinstance(p.get("name"), str)]
    names = [p["name"] for p in named]
    role_of = {p["name"]: p.get("role") for p in named}
    supplies = [name for name, role in role_of.items() if role == "supply"]
    held: dict[str, str] = {}  # a pin number -> the name of the pin that holds it
    for i, raw in enumerate(pins, start=1):
        here = f"{where}: pin {i}"
        role = raw.get("role") if isinstance(raw, dict) else None
        if not isinstance(role, str) or role not in ROLES:
            raise Refusal(f"{here}: role: one of {', '.join(ROLES)} is asked")
        required, optional = ROLES[role]
        pin = _keys(here, raw, ("numbers", "name", "role") + required, ("page",) + optional)
        _text(f"{here}: name", pin["name"])
        # 1 name names 1 entry, and 1 number stands in 1: a limit, a swing and a rail's load find a pin
        # by its name, and the second entry of a name or of a number would be judged on the first one's
        first = names.index(pin["name"]) + 1
        if first != i:
            raise Refusal(f"{here}: name: `{pin['name']}` is the name of pin {first} too")
        here = f"{where}: pin {pin['name'].strip()}"
        for number in _names(f"{here}: numbers", pin["numbers"]):
            if number in held:
                other = "2 times" if held[number] == pin["name"] else f"in pin {held[number]} too"
                raise Refusal(f"{here}: numbers: `{number}` stands {other}")
            held[number] = pin["name"]
        if role == "regulated" and ("volts" in pin) == ("set_by" in pin):
            raise Refusal(f"{here}: `volts`, or `set_by` with the name of its feedback pin: 1 of the 2")
        if "set_by" in pin:
            _text(f"{here}: set_by", pin["set_by"])
            if role_of.get(pin["set_by"]) != "feedback":
                raise Refusal(f"{here}: set_by: `{pin['set_by']}` is no pin of role feedback")
            for key in ("amps", "from"):
                if key in pin:
                    raise Refusal(f"{here}: `{key}` stands on the feedback pin {pin['set_by']}")
        elif role in ("regulated", "feedback"):
            if "from" in pin and pin["from"] not in supplies:
                raise Refusal(f"{here}: from: `{pin['from']}` is no pin of role supply")
            if "from" not in pin and len(supplies) > 1:
                raise Refusal(
                    f"{here}: `from` is missing: which of {', '.join(supplies)} its current comes from"
                )
        if role not in ("ground", "nc") and "page" not in pin:
            raise Refusal(f"{here}: `page` is missing: the datasheet's page the numbers stand on")
        if "page" in pin:
            _page(here, pin["page"])
        # A supply pin's working range is 2 numbers. A signal pin's, like its absolute limits, may follow
        # another pin: "0 to VCC".
        for key in ("abs",) if role == "supply" else ("abs", "operating"):
            if key not in pin:
                continue
            if not isinstance(pin[key], list) or len(pin[key]) != 2:
                raise Refusal(f"{here}: {key}: a span of 2 limits is asked, [least, greatest]")
            for end in pin[key]:
                _limit(f"{here}: {key}", end)
                for one in end if isinstance(end, list) else [end]:
                    if isinstance(one, dict) and one["pin"] not in names:
                        raise Refusal(f"{here}: {key}: `{one['pin']}` is no pin name of this part")
            _ordered(f"{here}: {key}", *pin[key])
        for key in ("operating", "volts") if role == "supply" else ("volts",):
            if key in pin:
                _span(f"{here}: {key}", pin[key])
        if "amps" in pin and role in ("regulated", "feedback"):
            # what the regulator gives: its load is divided by it
            _number(f"{here}: amps", pin["amps"], above=0)
        elif "amps" in pin:
            _number(f"{here}: amps", pin["amps"], 0)
        if "swing" in pin:
            swing = _names(f"{here}: swing", pin["swing"])
            if len(swing) != SWING[role] or any(s not in names for s in swing):
                known = ", ".join(map(str, names))
                raise Refusal(f"{here}: swing: {SWING[role]} of this part's pin names are asked, of {known}")
            if len(set(swing)) != len(swing):  # between 1 pin and itself an output drives nothing
                raise Refusal(f"{here}: swing: `{swing[0]}` stands 2 times: the 2 names are 2 pins")


def _needs(where: str, needs: object, names: list[str]) -> None:
    if not isinstance(needs, list):
        raise Refusal(f"{where}: needs: a list is asked")
    for i, raw in enumerate(needs, start=1):
        here = f"{where}: needs {i}"
        what = next((k for k in ("capacitor", "inductor") if isinstance(raw, dict) and k in raw), None)
        if what is None:
            raise Refusal(f"{here}: `capacitor` or `inductor` is asked")
        need = _keys(here, raw, (what, "page"))
        _page(here, need["page"])
        if what == "capacitor":  # a need for 0 asks for nothing
            part = _keys(f"{here}: capacitor", need[what], ("from", "to", "farads_min"), ("effective",))
            _number(f"{here}: capacitor: farads_min", part["farads_min"], above=0)
            if not isinstance(part.get("effective", False), bool):
                raise Refusal(f"{here}: capacitor: effective: true or false is asked")
        else:
            part = _keys(f"{here}: inductor", need[what], ("from", "to"), ("henries", "amps_saturation_min"))
            if "henries" in part:
                _span(f"{here}: inductor: henries", part["henries"])
            if "amps_saturation_min" in part:
                _number(f"{here}: inductor: amps_saturation_min", part["amps_saturation_min"], above=0)
        for end in ("from", "to"):
            if part[end] not in names:
                raise Refusal(f"{here}: {what}: {end}: `{part[end]}` is no pin name of this part")
        if part["from"] == part["to"]:
            raise Refusal(
                f"{here}: {what}: `{part['from']}` stands in `from` and in `to`: a part stands between 2 pins"
            )


def _facts(where: str, raw: object) -> Facts:
    kind = raw.get("kind") if isinstance(raw, dict) else None
    if not isinstance(kind, str) or (kind not in PASSIVE and kind not in OTHER):
        raise Refusal(f"{where}: kind: one of {', '.join([*PASSIVE, *OTHER])} is asked")
    required, optional = PASSIVE.get(kind) or OTHER[kind]
    data = _keys(where, raw, ("kind", "source") + required, WHICH + ("footprint", "note") + optional)
    if sum(key in data for key in WHICH) != 1:
        raise Refusal(f"{where}: exactly 1 of {', '.join(WHICH)} says which parts the entry speaks of")
    if "footprint" in data and "symbol" not in data:
        raise Refusal(f"{where}: `footprint` narrows a `symbol`, and the entry names none")
    for key in ("mpn", "match", "symbol", "footprint", "note", "dielectric"):
        if key in data:
            _text(f"{where}: {key}", data[key])
    if "mpns" in data:
        _names(f"{where}: mpns", data["mpns"])
    source = _keys(f"{where}: source", data["source"], *SOURCE_KEYS)
    for key, value in source.items():
        _text(f"{where}: source: {key}", value)
    _source(f"{where}: source", source)
    if "ohms" in data:  # 0 ohm is a link
        _number(f"{where}: ohms", data["ohms"], 0)
    for key in RATED:
        if key in data:
            _number(f"{where}: {key}", data[key], above=0)
    if isinstance(data.get("amps_drain"), list):  # a rating that falls with temperature: [celsius, amps]
        pairs = data["amps_drain"]
        if len(pairs) < 2 or not all(isinstance(p, list) and len(p) == 2 for p in pairs):
            raise Refusal(f"{where}: amps_drain: a number is asked, or 2 or more pairs [celsius, amps]")
        degrees = [_number(f"{where}: amps_drain: celsius", p[0]) for p in pairs]
        for pair in pairs:
            _number(f"{where}: amps_drain: amps", pair[1], 0)
        if degrees != sorted(set(degrees)):
            raise Refusal(f"{where}: amps_drain: the celsius rise from pair to pair")
    elif "amps_drain" in data:
        _number(f"{where}: amps_drain", data["amps_drain"], above=0)
    if "tolerance" in data:
        _number(f"{where}: tolerance", data["tolerance"], 0, 0.99)
    # the share of its value a part keeps: a capacitor's at a voltage and at a temperature, an inductor's
    # at a current
    for key, unit, least in (
        ("kept", "amps" if kind == "inductor" else "volts", 0),
        ("kept_celsius", "celsius", None),
    ):
        if key not in data:
            continue
        kept = data[key]
        if (
            not isinstance(kept, list)
            or len(kept) < 2
            or not all(isinstance(p, list) and len(p) == 2 for p in kept)
        ):
            raise Refusal(f"{where}: {key}: 2 or more pairs [{unit}, fraction of the value kept] are asked")
        xs = [_number(f"{where}: {key}: {unit}", p[0], least) for p in kept]
        for pair in kept:
            # no part keeps 0 % of its value: a share of 0 makes C or L zero in a deck
            _number(f"{where}: {key}: fraction", pair[1], most=1.5, above=0)
        if xs != sorted(set(xs)):
            raise Refusal(f"{where}: {key}: the {unit} rise from pair to pair")
    for key, ends in (("diodes", ("anode", "cathode")), ("transistors", ("gate", "drain", "source"))):
        if key in data:
            if not isinstance(data[key], list) or not data[key]:
                raise Refusal(f"{where}: {key}: a list is asked")
            for i, one in enumerate(data[key], start=1):
                for end in _keys(f"{where}: {key} {i}", one, ends):
                    if isinstance(one[end], list):  # a part with several pins for 1 end
                        _names(f"{where}: {key} {i}: {end}", one[end])
                    else:
                        _text(f"{where}: {key} {i}: {end}", one[end])
    if "thermal" in data:
        # the greatest junction temperature and the figures, all on the pages `page` names
        term = _keys(f"{where}: thermal", data["thermal"], ("junction_max", "page"), FIGURES)
        _number(f"{where}: thermal: junction_max", term["junction_max"], above=0)
        _page(f"{where}: thermal", term["page"])
        if not any(key in term for key in FIGURES):
            raise Refusal(f"{where}: thermal: 1 figure at least is asked, of {', '.join(FIGURES)}")
        for key in FIGURES:
            if key in term:
                _number(f"{where}: thermal: {key}", term[key], above=0)
    if kind == "connector":
        if not isinstance(data.get("pins", []), list):
            raise Refusal(f"{where}: pins: a list of pins is asked")
        for i, pin in enumerate(data.get("pins", []), start=1):
            _keys(f"{where}: pin {i}", pin, ("numbers", "outside"))
            _names(f"{where}: pin {i}: numbers", pin["numbers"])
            if pin["outside"] not in OUTSIDE:
                raise Refusal(f"{where}: pin {i}: outside: one of {', '.join(OUTSIDE)} is asked")
    if kind == "ic":
        if data["family"] not in FAMILIES:
            raise Refusal(f"{where}: family: one of {', '.join(FAMILIES)} is asked")
        _pin_facts(where, data["pins"])
        _needs(where, data.get("needs", []), [p["name"] for p in data["pins"]])
        if "switching" in data:
            here = f"{where}: switching"
            if data["family"] != "regulator.switching":
                raise Refusal(f"{here}: the family is {data['family']}, not regulator.switching")
            term = _keys(here, data["switching"], ("topology", "hertz", "page"), ("efficiency",))
            _page(here, term["page"])
            if term["topology"] != "buck":
                raise Refusal(f"{here}: topology: `buck` is the 1 topology the command computes")
            if _span(f"{here}: hertz", term["hertz"])[0] <= 0:
                raise Refusal(f"{here}: hertz: the least frequency is above 0")
            if "efficiency" in term and _number(f"{here}: efficiency", term["efficiency"], 0, 1) == 0:
                raise Refusal(f"{here}: efficiency: a share above 0 is asked")
    return Facts(where, kind, data)


def read_facts(folder: Path) -> list[Facts]:
    """Every entry of every *.json in a facts folder. A file holds 1 part, or {"parts": [...]}."""
    out = []
    for path in sorted(folder.glob("*.json")):
        data = _json(path)
        if isinstance(data, dict) and set(data) == {"parts"}:
            if not isinstance(data["parts"], list) or not data["parts"]:
                raise Refusal(f"{path.name}: parts: a list of parts is asked")
            out += [_facts(f"{path.name}: part {i}", raw) for i, raw in enumerate(data["parts"], start=1)]
        else:
            out.append(_facts(path.name, data))
    return out


def facts_of(facts: list[Facts], part: Part, mpn: str) -> Facts | None:
    """The entry that names a part most closely: its part number before a pattern, a pattern before its
    symbol. None when none names it. 2 entries that name it equally closely are refused."""
    close = [f.speaks_of(mpn, part.symbol, part.footprint) for f in facts]
    best = max(close, default=0)
    found = [f for f, level in zip(facts, close, strict=True) if best and level == best]
    if len(found) > 1:
        name = mpn or part.symbol
        raise Refusal(f"{found[0].where} and {found[1].where} both speak of {part.ref} ({name})")
    return found[0] if found else None


def _plain(name: str) -> str:
    """A pin's name as 2 documents may spell it: `~{CHG}` and `CHG` are 1 name, `V+` and `V-` are 2."""
    return re.sub(r"[^a-z0-9+-]", "", name.lower())


def _ends(value: str | list[str]) -> list[str]:
    """The pins of 1 end of a diode or a transistor: 1 pin number, or the list of them."""
    return [value] if isinstance(value, str) else list(value)


def rated_at(value: float | list[list[float]], ambient: float | None) -> tuple[float | None, str]:
    """A rating a datasheet states at several temperatures, at the project's ambient: between 2 points
    by a line, the first point when the project states no ambient (the second answer says so), and
    None past the last point, where the data ends."""
    if not isinstance(value, list):
        return float(value), ""
    if ambient is None:
        return value[0][1], f"rated as at {value[0][0]:g} C, since the project states no ambient"
    if ambient <= value[0][0]:
        return value[0][1], ""
    for (t0, a0), (t1, a1) in itertools.pairwise(value):
        if ambient <= t1:
            return a0 + (a1 - a0) * (ambient - t0) / (t1 - t0), ""
    return None, f"its rating is stated up to {value[-1][0]:g} C, and the ambient is {ambient:g} C"


def _two_pins(facts: Facts, part: Part) -> tuple[str, str]:
    if len(part.pins) != 2:
        raise Refusal(f"{facts.where}: {part.ref} is a {facts.kind} and has {len(part.pins)} pins, not 2")
    first, second = part.pins
    return first, second


def _held_pins(facts: Facts, part: Part, pins: list[str]) -> list[str]:
    for pin in pins:
        if pin not in part.pins:
            raise Refusal(f"{facts.where}: pin {pin} is no pin of {part.ref} ({part.symbol})")
    return pins


def value_of(facts: Facts, part: Part) -> float | None:
    """A passive part's value in ohms, farads or henries: the facts' own, or the schematic's Value. None
    when that is no number."""
    key = {"resistor": "ohms", "inductor": "henries"}.get(facts.kind, "farads")
    return facts.data[key] if key in facts.data else part_value(part.value)


def pin_number(facts: Facts, part: Part, name: str) -> str:
    """The first pin of the part that the facts give this name."""
    for pin in facts.data["pins"]:
        if pin["name"] == name:
            return next(n for n in pin["numbers"] if n in part.pins)
    raise Refusal(f"{facts.where}: `{name}` is no pin name of this part")


def model_of(facts: Facts, part: Part) -> Model:
    """How a part acts on the voltages of its nets, from its facts. Refuses facts that do not fit the
    part's symbol: a pin number it lacks, a pin of an IC the facts do not name."""
    data, kind = facts.data, facts.kind
    if kind == "resistor":
        _two_pins(facts, part)
        ohms = value_of(facts, part)
        if ohms is None:  # it may conduct, and nothing says how much
            return Model(passes=[(*part.pins, False)])
        return Model(ohms=(ohms * (1 - data["tolerance"]), ohms * (1 + data["tolerance"])))
    if kind in ("ferrite", "fuse", "link", "inductor"):
        # An inductor is a wire to a steady voltage. One behind a switched pin is another matter: it
        # carries the average of the swing, and judge() takes its link away.
        return Model(links=[_two_pins(facts, part)])
    if kind == "switch":
        return Model(passes=[(*_two_pins(facts, part), False)])
    if kind in PASSIVE:  # a capacitor, a test point, a mounting hole
        if kind.startswith("capacitor"):
            _two_pins(facts, part)  # its voltage is taken between 2 nets: a part of 3 pins has no such 2
        return Model()
    if kind == "connector":
        quiet = [n for pin in data.get("pins", []) if pin["outside"] != "source" for n in pin["numbers"]]
        return Model(quiet=frozenset(_held_pins(facts, part, quiet)))
    if kind.startswith("diode") or kind == "transistor.mosfet":
        # An end with several pins is 1 node inside the part: its pins are linked, and the first one
        # stands for the end.
        one_way = kind.startswith("diode")
        first, second = ("anode", "cathode") if one_way else ("drain", "source")
        units = data["diodes" if one_way else "transistors"]
        groups = [_ends(unit[end]) for unit in units for end in unit]
        _held_pins(facts, part, [p for group in groups for p in group])
        return Model(
            links=[(group[0], other) for group in groups for other in group[1:]],
            passes=[(_ends(unit[first])[0], _ends(unit[second])[0], one_way) for unit in units],
            quiet=frozenset(p for unit in units for p in _ends(unit.get("gate", []))),
        )
    named = _held_pins(facts, part, [n for pin in data["pins"] for n in pin["numbers"]])
    missing = sorted(set(part.pins) - set(named))
    if missing:
        raise Refusal(
            f"{facts.where}: {part.ref} ({part.symbol}) has pin {missing[0]}, and the facts name no such pin"
        )
    drives: dict[str, Drive] = {}
    quiet: set[str] = set()
    for pin in data["pins"]:
        role = pin["role"]
        if role == "regulated" and "volts" in pin:
            drive = Drive(*pin["volts"])
        elif role in SWING:
            ends = [pin_number(facts, part, name) for name in pin["swing"]]
            drive = Drive((ends[0], 0.0), (ends[-1], 0.0))
        else:
            quiet.update(pin["numbers"])
            continue
        drives.update(dict.fromkeys(pin["numbers"], drive))
    return Model(drives=drives, quiet=frozenset(quiet))


def divider_output(
    net: Netlist, models: dict[str, Model], ref: str, number: str, volts: Span, zero: set[str]
) -> tuple[str, Span, str] | str:
    """The net a feedback pin regulates, its span, and the resistors that set it: the pin's own voltage
    times (1 + top / bottom), where the top resistor stands between the output and the pin and the
    bottom one between the pin and a net at 0 V (DIVIDER_NOTE), each at the end of its tolerance that
    moves the output furthest. With no resistor on the pin's net the output is fed back whole: the
    pin's net is the output, and what else stands on it is its load. A reason in place of the 3 when
    a divider's tap holds anything else that can move it, or is not 1 resistor up and 1 down."""
    tap = net.parts[ref].pins[number]
    top: list[tuple[str, str, Span]] = []
    bottom: list[tuple[str, str, Span]] = []
    others: list[str] = []
    for node in net.nets[tap]:
        if node.ref == ref:
            continue
        model = models.get(node.ref)
        if model is not None and model.ohms is not None and model.ohms[0] > 0:
            far = next((n for p, n in net.parts[node.ref].pins.items() if p != node.pin), tap)
            if far != tap:
                (bottom if far in zero else top).append((node.ref, far, model.ohms))
            continue
        if model is None:
            still = node.kind in QUIET_KINDS
        else:
            named = {p for pair in model.links for p in pair} | {
                p for a, b, _ in model.passes for p in (a, b)
            }
            still = (
                model.ohms is None
                and node.pin not in named
                and node.pin not in model.drives
                and (model.quiet is None or node.pin in model.quiet)
            )
        if not still:
            others.append(f"{node.ref} pin {node.pin}")
    if all(node.ref == ref for node in net.nets[tap]):
        return "no other part stands on its net, and nothing sets the output"
    if not bottom and not top:
        return tap, volts, "fed back whole"
    if others:
        return f"{others[0]} stands on {tap} too, and is no resistor of a divider"
    if len(top) != 1 or len(bottom) != 1:
        return (
            f"its divider is {len(top)} resistor{'s' * (len(top) != 1)} to another net and "
            f"{len(bottom)} to a net at 0 V, not 1 and 1"
        )
    (over, out, above), (under, _, below) = top[0], bottom[0]
    # a reference under 0 V is furthest from 0 at the greatest ratio: the 4 corners, not 2 of them
    corners = [v * (1 + ratio) for v in volts for ratio in (above[0] / below[1], above[1] / below[0])]
    return out, (min(corners), max(corners)), f"{over} over {under} [{DIVIDER_NOTE}]"


def _efficiency(ref: str, term: dict, notes: list[str]) -> float:
    """A switching regulator's efficiency: its facts' own, or the one BUCK_NOTE's document names when
    a datasheet gives none, which the report then says."""
    if "efficiency" in term:
        return term["efficiency"]
    note = f"{ref}: its facts state no efficiency, and {BUCK_EFFICIENCY:g} is taken [TI SLVA477C, section 2]"
    if note not in notes:
        notes.append(note)
    return BUCK_EFFICIENCY


# ---------------------------------------------------------------- the judgement

STATUSES = ("fail", "accepted", "not judged", "hold")
EPS = 1e-9  # a stress that equals its limit holds, whatever the last bit of a division says
PREFIXES = (
    (1e9, "G"),
    (1e6, "M"),
    (1e3, "k"),
    (1.0, ""),
    (1e-3, "m"),
    (1e-6, "u"),
    (1e-9, "n"),
    (1e-12, "p"),
)
# The roles of an IC's pin through which no steady current flows.
NO_CURRENT = frozenset({"input", "analog", "nc"})


@dataclass
class Finding:
    status: str  # one of STATUSES
    part: str
    rule: str  # the pack's rule, or the stress when the limit is the part's own rating
    text: str
    source: str = ""

    @property
    def line(self) -> str:
        return f"{self.status} {self.text}" + (f" [{self.source}]" if self.source else "")


@dataclass
class Report:
    pack: str
    findings: list[Finding]
    unread: int  # the facts and the pack that were used and that no second reader has read
    notes: list[str]  # what the report says once


def si(value: float, unit: str) -> str:
    """A quantity as an engineer writes it, to 3 digits: 4.7e-6 farads is `4.7 uF`. It is rounded
    before its prefix is chosen: 0.9997 A is `1 A`, where 999.7 of the prefix below is `1e+03 mA`."""
    value = float(f"{value:.3g}")
    for scale, prefix in PREFIXES:
        if abs(value) >= scale * (1 - EPS):
            return f"{value / scale:.3g} {prefix}{unit}"
    return f"0 {unit}"


def kept_at(kept: list[list[float]], volts: float) -> float | None:
    """The fraction of its value a capacitor keeps at a voltage, between the maker's points. None above
    the last point: the data ends there."""
    if volts <= kept[0][0]:
        return kept[0][1]
    for (v0, f0), (v1, f1) in itertools.pairwise(kept):
        if volts <= v1:
            return f0 + (f1 - f0) * (volts - v0) / (v1 - v0)
    return None


def _outputs(net, of, models, project, out, notes) -> tuple[dict, dict]:  # noqa: PLR0913
    """What each regulator regulates. rails: part -> (the pin that states the output, the output's net).
    fed: net -> (the regulator, the span) for each output a divider sets, as net_spans takes it; the
    sum goes into the notes. An inductor behind a switched pin loses its link here: it carries the
    average of the swing, and that is the output its regulator's facts state."""
    ics = {ref: found for ref, found in of.items() if found.kind == "ic"}
    switched = {
        net.parts[ref].pins[number]
        for ref, found in ics.items()
        for pin in found.data["pins"]
        if pin["role"] == "switched"
        for number in pin["numbers"]
    }
    for ref, found in of.items():
        if found.kind == "inductor" and switched & set(net.parts[ref].pins.values()):
            models[ref] = Model()
    zero = {name for name, span in project.nets.items() if span == (0.0, 0.0)}
    grew = True
    while grew:  # a net that a link, a fuse or a ferrite joins to a net at 0 V is at 0 V
        grew = False
        for ref, model in models.items():
            for pair in model.links:
                ends = {net.parts[ref].pins[p] for p in pair[:2]}
                if ends & zero and not ends <= zero:
                    zero |= ends
                    grew = True
    rails: dict[str, list[tuple[dict, str]]] = {}
    fed: dict[str, list[tuple[str, Span]]] = {}
    for ref, found in ics.items():
        part = net.parts[ref]
        for pin in found.data["pins"]:
            number = pin["numbers"][0]
            if pin["role"] == "regulated" and "volts" in pin:
                rails.setdefault(ref, []).append((pin, part.pins[number]))
            if pin["role"] != "feedback":
                continue
            got = divider_output(net, models, ref, number, (pin["volts"][0], pin["volts"][1]), zero)
            if isinstance(got, str):
                label = f"{ref} pin {number} ({pin['name']}) on {part.pins[number]}"
                out.append(Finding("not judged", ref, "regulator.feedback", f"{label}: {got}"))
                continue
            name, span, how = got
            rails.setdefault(ref, []).append((pin, name))
            fed.setdefault(name, []).append((ref, span))
            notes.append(
                f"{ref} holds {name} at {span[0]:.3g} to {span[1]:.3g} V: its pin {pin['name']} at "
                f"{pin['volts'][0]:g} to {pin['volts'][1]:g} V, {how}"
            )
    return rails, fed


def judge(net: Netlist, mpns: dict[str, str], facts: list[Facts], project: Project, pack: Pack) -> Report:
    """Every stress of every part against its limit. A part with no facts, a net with no span and a
    number nothing gives are findings of their own: not judged, with the reason."""
    out: list[Finding] = []
    notes: list[str] = []
    of: dict[str, Facts] = {}
    models: dict[str, Model] = {}
    for ref, part in net.parts.items():
        found = facts_of(facts, part, mpns.get(ref, ""))
        if found is None:
            name = mpns.get(ref) or f"a part with no part number ({part.symbol})"
            out.append(Finding("not judged", ref, "facts", f"{ref} {part.value}: no facts for {name}"))
            continue
        of[ref] = found
        models[ref] = model_of(found, part)
    for found in {id(f): f for f in of.values()}.values():  # what an entry says its facts leave out
        if "note" in found.data:
            refs = ", ".join(ref for ref, f in of.items() if f is found)
            notes.append(f"{refs} ({found.name}): {found.data['note']}")
    if net.absent:
        notes.append(f"not fitted (DNP), and left out of every line: {', '.join(net.absent)}")
    # A datasheet may number a package another way than the footprint the symbol follows. Where the
    # facts give a name to 1 pin number and the symbol gives the same name to another, 1 of the 2 is
    # wrong, and every line of the part would be judged on the wrong net.
    symbol_names = {(n.ref, n.pin): n.name for nodes in net.nets.values() for n in nodes}
    for ref, found in of.items():
        if found.kind != "ic":
            continue
        theirs = {pin: _plain(name) for (r, pin), name in symbol_names.items() if r == ref}
        for pin in found.data["pins"]:
            same = _plain(pin["name"])
            if not same or any(theirs.get(number) == same for number in pin["numbers"]):
                continue
            other = next((n for n, name in sorted(theirs.items()) if name == same), None)
            if other is not None:
                text = (
                    f"{ref}: its facts name pin {pin['numbers'][0]} {pin['name']}, and the symbol names "
                    f"pin {other} {symbol_names[(ref, other)]}: the 2 number the pins differently"
                )
                out.append(Finding("fail", ref, "facts", text, found.source))
    rails, fed = _outputs(net, of, models, project, out, notes)
    for key in project.amps:  # a connector's pin the project states a current for is a load: no source
        ref, _, pin = key.partition(".")
        if pin and ref in of and of[ref].kind == "connector":
            models[ref].quiet = (models[ref].quiet or frozenset()) | {pin}
    spans = net_spans(net, models, project.nets, fed=fed)
    alone: dict[tuple, Spans] = {}
    loads: dict[tuple[str, str], tuple[float, list[str]]] = {}  # (regulator, net) -> its load, or why not
    taken: dict[frozenset[str], float] = {}  # 2 nets -> the farads the needs judged so far took there
    # (a net, the net behind 1 resistor, how far the first can stand under the second, and how far over)
    behind: list[tuple[str, str, float, float]] = []
    # 2 nets -> the most that can stand between them, and the resistor whose stated current says so
    ties: dict[frozenset[str], tuple[float, str]] = {}

    def follow(sp: Spans) -> Spans:
        """While its sources are on, a net that 1 resistor alone feeds stands at the net behind the
        resistor, less the drop of what its pins take: a supply pin behind its filter resistor is held
        at what holds the rail. A resistor whose current the project states holds its 2 nets within its
        drop of each other, whichever way the current runs: Ohm's law, with the owner's number. The net
        stands no higher than its span allows, which is the highest source that reaches it. A net
        behind 2 resistors in a row follows the first one's net, whichever part comes first; and what
        holds a net holds every net of its node."""
        moved = True
        while moved:
            moved = False
            for lone, rail, drop, rise in behind:
                if rail in sp.held and lone not in sp.held:
                    top = sp.held[rail][1] + rise
                    if lone in sp.stress:
                        top = min(top, sp.stress[lone][1])
                    for name, node in sp.node.items():
                        if node == sp.node[lone]:
                            sp.held[name] = (sp.held[rail][0] - drop, top)
                    moved = True
        return sp

    def seen_by(ref: str, number: str, forced: tuple = ()) -> Spans:
        """The spans 1 pin is rated against: every source but the pin's own drive, and a rail put
        where the limit is tightest."""
        if not forced and number not in models[ref].drives:
            return spans
        if (ref, number, forced) not in alone:
            alone[(ref, number, forced)] = follow(
                net_spans(net, models, project.nets, without=(ref, number), forced=dict(forced), fed=fed)
            )
        return alone[(ref, number, forced)]

    def tie(a: str, b: str, but: str = "") -> tuple[float, str] | None:
        """The most that can stand between 2 nets a resistor with a stated current holds together, and
        that resistor; None for 2 other nets, and for the resistor `but` itself."""
        found = ties.get(frozenset((spans.node[a], spans.node[b])))
        return None if found is None or found[1] == but else found

    def wired(a: str, b: str, but: str = "") -> str:
        """What a line says of 2 nets that are 1 node, where no voltage stands between them, and of 2
        that a resistor with a stated current holds together."""
        if spans.node[a] != spans.node[b]:
            held = tie(a, b, but)
            return f", which {held[1]} holds within {si(held[0], 'V')}" if held else ""
        return ", both pins on 1 net" if a == b else ", 2 nets that a wire joins"

    def gap(sp: Spans, a: str, b: str) -> float | str:
        """The greatest voltage between 2 nets, or why it has none. 2 nets of 1 node never part: taken
        at their extremes, a resistor beside a ferrite would stand the rail's whole voltage. 2 nets a
        resistor with a stated current holds together part by its drop at the most."""
        if sp.node[a] == sp.node[b]:
            return 0.0
        held = tie(a, b)
        for name in (a, b):
            if name not in sp.stress:
                return held[0] if held else f"{name} has no span: {sp.why.get(name, 'nothing drives it')}"
        apart = max(sp.stress[a][1] - sp.stress[b][0], sp.stress[b][1] - sp.stress[a][0])
        return min(apart, held[0]) if held else apart

    def unrated(ref: str, stress: str) -> None:
        """A current the project states for a part whose facts rate none: it is held to nothing, and
        is no hold."""
        text = f"{name_of(ref)}: the project states {si(project.amps[ref], 'A')} through it"
        out.append(Finding("not judged", ref, stress, f"{text}, and its facts hold no current rating"))

    def limit_of(stress: str, ref: str) -> tuple[float, str, str]:
        """The share of its rating a part may reach, the rule's name, and the source for the line."""
        rule = pack.rule(stress, of[ref].kind)
        if rule is None:
            return 1.0, stress, f"{of[ref].source}: the part's own rating"
        share, note = factor(rule, project.ambient)
        if note and note not in notes:
            notes.append(note)
        return share, rule.id, f"{pack.document['number']}, {rule.where}"

    def entries(key: tuple[str, str]) -> list[tuple[str, str]]:
        """The acceptances of 1 part under 1 rule: (words of the line an entry means, the owner's)."""
        said = project.accepted.get(key, [])
        return [("", said)] if isinstance(said, str) else said

    met: dict[tuple[str, str, str], list[Finding]] = {}  # an acceptance -> the failures it meets

    def judged(ref: str, rule: str, holds: bool, text: str, source: str) -> None:
        if holds:
            out.append(Finding("hold", ref, rule, text, source))
            return
        out.append(Finding("fail", ref, rule, text, source))
        for piece, _ in entries((ref, rule)):
            if piece in text:  # an entry with no `line` means the part's 1 failure under the rule
                met.setdefault((ref, rule, piece), []).append(out[-1])
                break

    def ratio(ref: str, stress: str, label: str, value: float | str, rated: float, unit: str) -> None:
        """One stress against one rating: a voltage across a part, a power in it."""
        if isinstance(value, str):
            out.append(Finding("not judged", ref, stress, f"{label}: {value}"))
            return
        share, rule, source = limit_of(stress, ref)
        if rated <= 0:  # a rating that falls with the temperature has reached 0 at this ambient
            text = f"{label}: {si(value, unit)} on {si(rated, unit)} rated: nothing of the rating is left"
            judged(ref, rule, value <= EPS, text, source)
            return
        holds = value <= rated * share + EPS
        of_it = f"{value / rated:.2f}"
        if not holds and of_it == f"{share:.2f}":  # 0.603 on a limit of 0.60: show which side it is on
            of_it = f"{value / rated:.3f}"
        text = f"{label}: {si(value, unit)} on {si(rated, unit)} rated is {of_it}"
        judged(ref, rule, holds, f"{text}, the limit is {share:.2f}", source)

    def carries(name: str, but: str, resistors: bool = True) -> bool:
        """Whether a steady current can leave a net by another way than through the part `but`; with
        resistors False, by another way than through a resistor too."""
        if name in project.nets:
            return True
        for node in net.nets[name]:
            if node.ref == but:
                continue
            if node.ref not in of:
                if node.kind not in QUIET_KINDS or node.kind == "power_in":
                    return True
                continue
            data, kind = of[node.ref].data, of[node.ref].kind
            if kind == "resistor" and not resistors:
                continue
            if kind == "ic":
                role = next(p["role"] for p in data["pins"] if node.pin in p["numbers"])
                if role not in NO_CURRENT:
                    return True
            elif kind == "connector":
                quiet = [n for p in data.get("pins", []) if p["outside"] == "nothing" for n in p["numbers"]]
                if node.pin not in quiet:
                    return True
            elif kind == "transistor.mosfet":
                if node.pin not in [p for t in data["transistors"] for p in _ends(t["gate"])]:
                    return True
            elif not kind.startswith("capacitor") and kind not in ("testpoint", "mechanical"):
                return True
        return False

    def shares(ref: str, a: str, b: str) -> bool:
        """Whether the solved drop of a resistor is the whole of what it stands: no free net of its
        network of resistors holds a part that takes a steady current, which the solve cannot know."""
        seen: set[str] = set()
        stack = [name for name in (a, b) if name not in spans.held]
        while stack:
            name = stack.pop()
            if name in seen:
                continue
            seen.add(name)
            if carries(name, ref, resistors=False):
                return False
            for node in net.nets[name]:
                if node.ref in of and of[node.ref].kind == "resistor":
                    stack += [n for n in net.parts[node.ref].pins.values() if n not in spans.held]
        return True

    def fed_through(ref: str, a: str, b: str) -> tuple[float, str] | None:
        """The current through a resistor that alone feeds 1 of its 2 nets, and that net: what the pins
        there take, when the facts state every one. None when another source reaches the net, when a
        pin there takes a current nothing states, or when nothing there takes any."""

        def taken(name: str) -> float | None:
            """What the pins on 1 net take, or None when one of them could feed the net or takes a
            current nothing states: only capacitors, gates, inputs and supply pins may stand there."""
            if name in project.nets:
                return None
            total, counted = 0.0, set()
            for node in net.nets[name]:
                other = of.get(node.ref)
                if node.ref == ref:
                    continue
                if other is None:
                    return None
                data, kind = other.data, other.kind
                if kind.startswith("capacitor") or kind in ("testpoint", "mechanical"):
                    continue
                if kind == "transistor.mosfet":
                    if node.pin in [p for t in data["transistors"] for p in _ends(t["gate"])]:
                        continue
                    return None
                if kind != "ic":
                    return None
                pin = next(p for p in data["pins"] if node.pin in p["numbers"])
                if pin["role"] in NO_CURRENT:
                    continue
                if pin["role"] != "supply" or "amps" not in pin or node.ref in rails:
                    return None  # an output, or a supply whose current is its regulator's load
                if (node.ref, pin["name"]) not in counted:
                    counted.add((node.ref, pin["name"]))
                    total += pin["amps"]
            return total

        lone = [(amps, name) for name in (a, b) if (amps := taken(name)) is not None]
        return lone[0] if len(lone) == 1 else None

    def name_of(ref: str) -> str:
        return f"{ref} {net.parts[ref].value}".strip()

    through: dict[str, float] = {}  # resistor -> the current it is judged with, where one is known
    for ref, found in of.items():  # the nets that 1 resistor alone feeds: see follow()
        ohms = value_of(found, net.parts[ref]) if found.kind == "resistor" else None
        if ref in project.amps and found.kind == "resistor":
            through[ref] = project.amps[ref]
        if found.kind == "resistor" and (ref in project.volts or (ohms and ref in project.amps)):
            a, b = net.parts[ref].pins.values()
            drop = project.volts.get(ref)
            if drop is None:
                drop = project.amps[ref] * ohms * (1 + found.data["tolerance"])
            behind += [(a, b, drop, drop), (b, a, drop, drop)]
            pair = frozenset((spans.node[a], spans.node[b]))
            if len(pair) == 2 and (pair not in ties or drop < ties[pair][0]):
                ties[pair] = (drop, ref)
        if not ohms or ref in project.amps or ref in project.volts:
            continue
        a, b = net.parts[ref].pins.values()
        fed_by = fed_through(ref, a, b)
        if fed_by is not None:
            amps, lone = fed_by
            through[ref] = amps
            behind.append((lone, b if lone == a else a, amps * ohms * (1 + found.data["tolerance"]), 0.0))
    follow(spans)

    for ref, found in of.items():
        part, data, kind = net.parts[ref], found.data, found.kind
        if kind.startswith("capacitor") or kind == "resistor":
            a, b = part.pins.values()
            label = f"{name_of(ref)} between {a} and {b}{wired(a, b, ref)}"
            volts = gap(spans, a, b)
            if ref in spans.drops and not isinstance(volts, str) and shares(ref, a, b):
                volts = min(volts, spans.drops[ref])  # solved with its nets: a divider's share
            ohms = value_of(found, part) if kind == "resistor" else None
            said, amps = "", None
            if ref in project.volts:
                volts = project.volts[ref]
                label += f", with the {si(volts, 'V')} the project states"
            elif ohms and ref in project.amps:
                # a stated current sets the voltage across a resistor: its 2 nets' spans say what a
                # load beside it could see, and a 20 mohm shunt never sees the cell's 4.2 V
                amps = project.amps[ref]
                said = f", with the {si(amps, 'A')} the project states"
            elif ohms and (lone := fed_through(ref, a, b)) is not None and lone[0] > 0:
                # the filter resistor of a supply pin: the pin is no short, it takes what its facts say
                amps = lone[0]
                said = f", with the {si(amps, 'A')} that {lone[1]} takes"
            if amps is not None:
                volts = amps * ohms * (1 + data["tolerance"])
            what = "capacitor.voltage" if kind != "resistor" else "resistor.voltage"
            if "volts" in data:
                ratio(ref, what, label + said, volts, data["volts"], "V")
            else:
                out.append(Finding("not judged", ref, what, f"{label}: its facts hold no voltage rating"))
        if kind == "resistor":
            if ohms is None:
                out.append(Finding("not judged", ref, "resistor.power", f"{label}: its Value is no number"))
            elif ohms > 0 and not isinstance(volts, str):
                if amps is not None:
                    watts = amps**2 * ohms * (1 + data["tolerance"])
                    how = said[2:]
                elif not (carries(a, ref) and carries(b, ref)):
                    watts, how = 0.0, "no steady current: one end meets no source"
                else:
                    watts = volts**2 / (ohms * (1 - data["tolerance"]))
                    how = f"with {si(volts, 'V')} across it"
                ratio(ref, "resistor.power", f"{label}, {how}", watts, data["watts"], "W")
        elif kind == "inductor" and ref in project.amps:
            amps, rated = project.amps[ref], data["amps_saturation"]
            text = f"{name_of(ref)}: the project states {si(amps, 'A')}, and it saturates at {si(rated, 'A')}"
            judged(
                ref, "inductor.current", amps <= rated + EPS, text, f"{found.source}: the part's own rating"
            )
        elif kind in ("fuse", "ferrite", "switch") and ref in project.amps:
            if "amps" in data:
                amps = project.amps[ref]
                label = f"{name_of(ref)} current, with the {si(amps, 'A')} the project states"
                ratio(ref, f"{kind}.current", label, amps, data["amps"], "A")
            else:
                unrated(ref, f"{kind}.current")
        elif kind.startswith("diode"):
            if ref in project.amps and "amps_forward" in data:
                amps = project.amps[ref]
                label = f"{name_of(ref)} forward current, with the {si(amps, 'A')} the project states"
                ratio(ref, "diode.forward_current", label, amps, data["amps_forward"], "A")
            elif ref in project.amps:
                unrated(ref, "diode.forward_current")
            for diode in data["diodes"]:
                anode, cathode = (part.pins[_ends(diode[end])[0]] for end in ("anode", "cathode"))
                label = f"{name_of(ref)} from {anode} to {cathode}{wired(anode, cathode)}"
                both = all(n in spans.stress for n in (anode, cathode)) and not wired(anode, cathode)
                volts = (
                    spans.stress[cathode][1] - spans.stress[anode][0] if both else gap(spans, anode, cathode)
                )
                if all(n in spans.held for n in (anode, cathode)):
                    least, most = spans.held[anode][0], spans.held[cathode][1]
                    if least > most + EPS:  # held forward whatever its sources do: no limit on its current
                        text = (
                            f"{label}: its anode is held at {least:.3g} V or more and its cathode at "
                            f"{most:.3g} V or less: it stands forward between 2 sources"
                        )
                        judged(ref, "diode.forward", False, text, f"{found.source}: the part's own rating")
                        continue
                if kind == "diode.rectifier":
                    ratio(ref, "diode.reverse", label, volts, data["volts_reverse"], "V")
                elif isinstance(volts, str):
                    out.append(Finding("not judged", ref, "diode.standoff", f"{label}: {volts}"))
                else:
                    off = data["volts_standoff"]
                    text = f"{label}: {si(volts, 'V')} can stand across it, and it stands off {off:g} V"
                    holds = volts <= off + EPS
                    judged(ref, "diode.standoff", holds, text, f"{found.source}: the part's own rating")
        elif kind == "transistor.mosfet":
            if ref in project.amps and "amps_drain" in data:
                rated, said = rated_at(data["amps_drain"], project.ambient)
                if rated is None:
                    out.append(
                        Finding(
                            "not judged", ref, "mosfet.drain_current", f"{name_of(ref)} drain current: {said}"
                        )
                    )
                else:
                    if said and f"{ref}: its drain current is {said}" not in notes:
                        notes.append(f"{ref}: its drain current is {said}")
                    amps = project.amps[ref]
                    label = f"{name_of(ref)} drain current, with the {si(amps, 'A')} the project states"
                    ratio(ref, "mosfet.drain_current", label, amps, rated, "A")
            elif ref in project.amps:
                unrated(ref, "mosfet.drain_current")
            for fet in data["transistors"]:
                gate, drain, source = (part.pins[_ends(fet[end])[0]] for end in ("gate", "drain", "source"))
                label = f"{name_of(ref)} drain {drain} to source {source}{wired(drain, source)}"
                ratio(
                    ref,
                    "mosfet.drain_source",
                    label,
                    gap(spans, drain, source),
                    data["volts_drain_source"],
                    "V",
                )
                label = f"{name_of(ref)} gate {gate} to source {source}{wired(gate, source)}"
                ratio(
                    ref, "mosfet.gate_source", label, gap(spans, gate, source), data["volts_gate_source"], "V"
                )
        elif kind == "ic":
            _judge_ic(
                net,
                ref,
                of,
                models,
                spans,
                seen_by,
                project,
                pack,
                notes,
                judged,
                out,
                rails,
                loads,
                taken,
                through,
                tie,
            )
    for ref, found in of.items():
        if found.kind == "ic" and "switching" in found.data:
            _judge_buck(net, ref, of, spans, project, notes, judged, out, rails, loads)
    for key, amps in project.amps.items():  # a current behind a pin of an IC stands in no line
        ref, _, number = key.partition(".")
        if number and ref in of and of[ref].kind == "ic":
            notes.append(
                f"{key}: ratings.json states {si(amps, 'A')} behind the pin, "
                "and the command holds no pin's current to a limit"
            )

    out += [Finding("not judged", ref, "stated", text, source) for ref, text, source in project.unjudged]

    # An acceptance is the owner's word on 1 failure. One that meets 1 failure accepts it. One that
    # meets 2 accepts neither: the second is a failure the owner has not seen. One that meets none
    # fails the run, unless its part is not judged now.
    for ref, rule in project.accepted:
        for piece, words in entries((ref, rule)):
            hits = met.get((ref, rule, piece), [])
            text = f"{ref}: ratings.json accepts a failure of {rule}"
            part_ref = ref.partition(".")[0]
            if len(hits) == 1:
                hits[0].status, hits[0].text = "accepted", f"{hits[0].text}; accepted: {words}"
            elif hits:
                text = f"{ref}: ratings.json accepts 1 failure of {rule}, and {len(hits)} fail there"
                out.append(Finding("fail", ref, "accepted", f"{text}: name the 1 it means with `line`"))
            elif any(f.status == "not judged" and f.part.partition(".")[0] == part_ref for f in out):
                # the failure is not gone: it comes back with what is missing
                out.append(
                    Finding("not judged", ref, "accepted", f"{text}, and {part_ref} is not judged now")
                )
            else:
                out.append(
                    Finding("fail", ref, "accepted", f"{text}, and nothing fails there: take the entry out")
                )
    judged_parts = {f.part.partition(".")[0] for f in out}
    idle: dict[str, list[str]] = {}  # kind -> the parts with facts that no stress was computed for
    for ref, found in of.items():
        if ref not in judged_parts:
            idle.setdefault(found.kind, []).append(ref)
    if idle:
        named = ", ".join(f"{', '.join(refs)} ({kind})" for kind, refs in sorted(idle.items()))
        notes.append(f"no stress is judged of {named}")
    used = {id(f): f for f in of.values()}
    unread = sum(not f.read_twice for f in used.values()) + (pack.document["second_reader"] == "no")
    out.sort(key=lambda f: STATUSES.index(f.status))
    return Report(pack.name, out, unread, notes)


def _judge_ic(  # noqa: PLR0913
    net, ref, of, models, spans, seen_by, project, pack, notes, judged, out, rails, loads, taken, through, tie
) -> None:
    """The pins of 1 IC: each against its limits, its supply against its working range, the load on
    what it regulates, and the support parts its datasheet asks for. tie(net, net) is the most that can
    stand between 2 nets a resistor with a stated current holds together, and that resistor."""
    part, found = net.parts[ref], of[ref]
    data = found.data
    # A datasheet's limits are against the part's ground pin. Where that pin's net is not at the board's
    # 0 V (a part on a negative rail, a high-side part), a plain number is a limit that follows the pin.
    base = next((p for p in data["pins"] if p["role"] == "ground"), None)
    base_net = part.pins[base["numbers"][0]] if base else ""
    if base and spans.stress.get(base_net) == (0.0, 0.0):
        base = None

    told: set[str] = set()  # the `not judged` lines of this part's pins, each said 1 time

    def from_ground(value: object) -> object:
        if base is None or isinstance(value, dict):
            return value
        if isinstance(value, list):
            return [from_ground(one) for one in value]
        return {"pin": base["name"], "plus": value}

    def bound(pin: dict, number: str, which: int, key: str = "abs") -> tuple | None:
        """1 end of a pin's absolute limits, or of a signal pin's working range (key `operating`): which
        is 0 for the least and 1 for the greatest. Whether it holds, the voltage and the limit as the
        line names it; an empty tuple when nothing but the pin puts a voltage on its net. None when no
        limit of this end could be judged. Of 2 limits, each is judged on its own: one that cannot be
        gets its `not judged` line, and never hides one that is certainly passed."""
        name = part.pins[number]
        label = f"{ref} pin {number} ({pin['name']}) on {name}"
        raw = from_ground(pin[key][which])
        worst: tuple[float, str, str] | None = None
        missed = False

        def shown(volts: float, limit: float, over: float) -> str:
            """A voltage to 3 digits; past its limit, to as many as tell it from the limit: 4.001 V on
            a limit of 4 V does not print as `4 V can stand on it, its limit is 4 V`."""
            for digits in (3, 4, 5, 6):
                text = f"{volts:.{digits}g}"
                if over <= EPS or text != f"{limit:.{digits}g}":
                    break
            return text

        def miss(text: str) -> None:
            if text not in told:  # the pin's other end would say the same again
                told.add(text)
                out.append(Finding("not judged", ref, "pin.voltage", text))

        for one in raw if isinstance(raw, list) else [raw]:
            forced, how = (), ""
            if isinstance(one, dict):
                rail = part.pins[pin_number(found, part, one["pin"])]
                if rail == name:
                    continue  # the pin is on the rail its limit follows
                if rail not in spans.held:
                    miss(f"{label}: its limit follows pin {one['pin']} on {rail}, which no source holds")
                    missed = True
                    continue
                held = tie(name, rail)
                if held is not None:
                    # The 2 pins stand on the 2 nets of a resistor whose current the project states. The
                    # limit is between the 2 pins, and so is the drop, wherever the rail stands and
                    # whichever way the current runs: the line gives both with the rail at its greatest.
                    at = spans.held[rail][1]
                    volts = at + held[0] if which else at - held[0]
                    limit = at + one["plus"]
                    how = (
                        f" (pin {one['pin']} at {at:.3g} V, {one['plus']:+g} V; "
                        f"{held[1]} holds the 2 nets within {si(held[0], 'V')})"
                    )
                    over = (volts - limit) if which else (limit - volts)
                    if worst is None or over > worst[0]:
                        worst = (over, shown(volts, limit, over), f"{limit:.3g} V{how}")
                    continue
                at = spans.held[rail][1 - which]  # the rail where the limit is tightest
                forced, limit = ((rail, (at, at)),), at + one["plus"]
                how = f" (pin {one['pin']} at {at:.3g} V, {one['plus']:+g} V)"
            else:
                limit = one
            sp = seen_by(ref, number, forced)
            if name not in sp.stress:
                why = sp.why.get(name, "nothing drives it")
                if why == "nothing drives it":
                    continue  # nothing but the pin itself puts a voltage on its net
                miss(f"{label}: {name} has no span: {why}")
                missed = True
                continue
            volts = sp.stress[name][which]
            if forced and not which:
                # A least limit that follows a pin that is on: with every source off both nets are at
                # 0 V and no limit between 2 pins is broken, so the pin is taken where its own sources
                # hold it. The order rails come up in is not judged.
                if name not in sp.held:
                    miss(f"{label}: its least limit follows pin {one['pin']}, and no source holds {name}")
                    missed = True
                    continue
                volts = sp.held[name][0]
            over = (volts - limit) if which else (limit - volts)
            if worst is None or over > worst[0]:
                worst = (over, shown(volts, limit, over), f"{limit:.3g} V{how}")
        if worst is None:
            return None if missed else ()
        return (worst[0] <= EPS, worst[1], worst[2])

    for pin in data["pins"]:
        for number in pin["numbers"]:
            name = part.pins[number]
            nodes = net.nets[name]
            if len(nodes) == 1 and (nodes[0].open or name.startswith("unconnected-(")):
                continue  # a pin left open
            high = bound(pin, number, 1) if "abs" in pin else None
            low = bound(pin, number, 0) if "abs" in pin else None
            if "abs" not in pin and pin["role"] not in ("ground", "nc"):
                notes.append(
                    f"{ref} pin {number} ({pin['name']}): its facts hold no limits, "
                    f"and no voltage on {name} is held to one"
                )
            label = f"{ref} pin {number} ({pin['name']}) on {name}"
            source = f"{found.source}, {_p(pin['page'])}" if "page" in pin else found.source
            if low and high and low[0] and high[0]:  # both ends hold: 1 line says so
                text = (
                    f"{label}: {low[1]} to {high[1]} V can stand on it, its limits are {low[2]} and {high[2]}"
                )
                judged(f"{ref}.{number}", "pin.voltage", True, text, source)
            else:
                for end in (high, low):
                    if end:
                        text = f"{label}: {end[1]} V can stand on it, its limit is {end[2]}"
                        judged(f"{ref}.{number}", "pin.voltage", end[0], text, source)
            broke = any(end and not end[0] for end in (high, low))  # past a limit: 1 line says it
            if pin["role"] != "supply" and "operating" in pin and low is not None and not broke:
                # a signal pin's working range, against what the other parts put on its net
                most, least = bound(pin, number, 1, "operating"), bound(pin, number, 0, "operating")
                if most and least:
                    text = (
                        f"{label}: {least[1]} to {most[1]} V can stand on it, "
                        f"the pin works from {least[2]} to {most[2]}"
                    )
                    judged(f"{ref}.{number}", "pin.range", least[0] and most[0], text, source)
            if pin["role"] == "supply" and "operating" in pin:
                label = f"{ref} pin {number} ({pin['name']}) on {name}"
                if name not in spans.held:
                    out.append(Finding("not judged", ref, "supply.range", f"{label}: no source holds {name}"))
                    continue
                low, high = spans.held[name]
                works, where = pin["operating"], f"at {low:.3g} to {high:.3g} V"
                if base is not None and name != base_net:  # the range is from the part's ground pin
                    under = f"pin {base['name']} on {base_net}"
                    if base_net not in spans.held:
                        text = f"{label}: its range is from {under}, which no source holds"
                        out.append(Finding("not judged", ref, "supply.range", text))
                        continue
                    low, high = low - spans.held[base_net][1], high - spans.held[base_net][0]
                    where = f"{low:.3g} to {high:.3g} V above {under}"
                text = (
                    f"{label}: its sources hold it {where}, the pin works from {works[0]:g} to {works[1]:g} V"
                )
                holds = low >= works[0] - EPS and high <= works[1] + EPS
                judged(f"{ref}.{number}", "supply.range", holds, text, f"{found.source}, {_p(pin['page'])}")
        if "set_by" in pin:  # the output pin of a regulator a divider sets: is it on the divider's net
            there = part.pins[pin["numbers"][0]]
            set_to = next((name for p, name in rails.get(ref, []) if p["name"] == pin["set_by"]), None)
            if set_to is not None:
                text = (
                    f"{ref} pin {pin['numbers'][0]} ({pin['name']}) is on {there}, and the divider on its "
                    f"pin {pin['set_by']} regulates {set_to}"
                )
                source = f"{found.source}, {_p(pin['page'])}"
                judged(ref, "regulator.feedback", there == set_to, text, source)
    for pin, name in rails.get(ref, []):
        _judge_rail(
            net, ref, pin, name, of, models, spans, project, pack, notes, judged, out, rails, loads, through
        )
    for need in data.get("needs", []):
        _judge_need(net, ref, need, of, spans, judged, out, rails, taken)


def _rail(
    net: Netlist,
    models: dict[str, Model],
    start: str,
    stops: frozenset[str] = frozenset(),
    blind: frozenset[str] = frozenset(),
) -> tuple[set[str], set[str]]:
    """The nets a current from 1 net reaches without passing a resistor: through a fuse, a ferrite, a
    switch, a transistor or an inductor either way, and through a diode from its anode to its cathode.
    stops: nets the walk does not enter, since another source holds them (the nets the project
    states); the second set is those it met. blind: parts it does not walk through (a resistor with
    no number, which may conduct and is no wire)."""
    rail, met, stack = set(), set(), [start]
    while stack:
        name = stack.pop()
        if name in rail:
            continue
        rail.add(name)
        for node in net.nets[name]:
            model = models.get(node.ref)
            if model is None or node.ref in blind:
                continue
            ways = [way for a, b in (pair[:2] for pair in model.links) for way in ((a, b), (b, a))]
            for a, b, one_way in model.passes:
                ways += [(a, b)] if one_way else [(a, b), (b, a)]
            for near, far in ways:
                if node.pin != near:
                    continue
                other = net.parts[node.ref].pins[far]
                if other in stops:
                    met.add(other)
                else:
                    stack.append(other)
    return rail, met


def _judge_rail(  # noqa: PLR0913
    net, ref, pin, name, of, models, spans, project, pack, notes, judged, out, rails, loads, through
) -> None:
    """The load on the net 1 pin regulates: the supply pins on its rail, each regulator among them
    passing its own load on (a linear one its current, a switching one its power over its efficiency),
    the pins of connectors the project gives a current for, and the resistors, each with the current
    it is judged with (through) where one is known. The load is kept in `loads` for the regulator's
    inductor; it is judged when the pin's facts say what it gives. A rail that meets a net the project
    states has a second source, and nothing says how the 2 share the load: it is noted, not judged."""
    found = of[ref]
    label = f"{name}: {ref} pin {pin['numbers'][0]} ({pin['name']})"
    seen: set[tuple[str, str]] = set()  # the supply pins counted: one of 2 numbers is counted 1 time
    stops = frozenset(project.nets)
    blind = frozenset(r for r, f in of.items() if f.kind == "resistor")

    def others(start: str) -> list[str]:
        """The nets above 0 V or under it that the project states and a rail meets."""
        nets, met = _rail(net, models, start, stops, blind)
        return sorted(n for n in nets | met if n in project.nets and project.nets[n] != (0.0, 0.0))

    def load(start: str, came: frozenset[str]) -> tuple[float, list[str]]:
        total, unknown = 0.0, []
        here, _ = _rail(net, models, start, stops, blind)
        if came != frozenset({ref}) and others(start):
            unknown.append(f"{start} meets {others(start)[0]}, which ratings.json states: a second source")
        for rail in sorted(here):
            for node in net.nets[rail]:
                if node.ref in came:
                    continue
                other = of.get(node.ref)
                where = f"{node.ref} pin {node.pin}"
                if other is None:
                    # what the project states for the pin is on the rail whatever the part is; a pin
                    # nothing describes may take a current, unless it is an input or left open
                    key = f"{node.ref}.{node.pin}"
                    if key in project.amps:
                        total += project.amps[key]
                    elif node.kind == "power_in":
                        unknown.append(f"{where} takes current from {rail} and has no facts")
                    elif node.kind not in ("input", "no_connect") and not node.open:
                        unknown.append(f"{where} stands on {rail} and has no facts")
                elif other.kind == "ic":
                    theirs = next(p for p in other.data["pins"] if node.pin in p["numbers"])
                    if theirs["role"] != "supply" or (node.ref, theirs["name"]) in seen:
                        continue
                    seen.add((node.ref, theirs["name"]))
                    if "amps" not in theirs:
                        unknown.append(f"{where} ({theirs['name']}) has no `amps` in its facts")
                        continue
                    total += theirs["amps"]
                    first = next(p["name"] for p in other.data["pins"] if p["role"] == "supply")
                    for out_pin, below in rails.get(node.ref, []):
                        if out_pin.get("from", first) != theirs["name"]:
                            continue
                        more, more_unknown = load(below, came | {node.ref})
                        unknown += more_unknown
                        term = other.data.get("switching")
                        if other.data["family"] != "regulator.switching":
                            total += more
                        elif term is None:
                            unknown.append(
                                f"{node.ref} is a switching regulator, and its facts state no `switching`"
                            )
                        elif rail not in spans.held or below not in spans.held or spans.held[rail][0] <= 0:
                            unknown.append(
                                f"{node.ref} takes its load's power from {rail}, and no source holds "
                                f"{rail} and {below} above 0 V"
                            )
                        else:  # its load's power, over its efficiency, at its least input
                            share = _efficiency(node.ref, term, notes)
                            total += more * spans.held[below][1] / (share * spans.held[rail][0])
                elif other.kind == "connector":
                    outside = next(
                        (p["outside"] for p in other.data.get("pins", []) if node.pin in p["numbers"]), ""
                    )
                    key = f"{node.ref}.{node.pin}"
                    if outside == "load" and key not in project.amps:
                        unknown.append(f"{where} feeds a load, and ratings.json states no amps for {key}")
                    total += project.amps.get(key, 0.0)
                elif other.kind == "resistor":
                    ohms = value_of(other, net.parts[node.ref])
                    far = next(n for p, n in net.parts[node.ref].pins.items() if p != node.pin)
                    if far in here:
                        continue  # both ends on the rail: it takes nothing from it
                    if node.ref in through:  # the current the resistor itself is judged with
                        total += through[node.ref]
                    elif ohms is None:
                        unknown.append(f"{node.ref} has no number for its Value, and may take a current")
                    elif ohms and all(n in spans.stress for n in (rail, far)):
                        volts = max(
                            spans.stress[rail][1] - spans.stress[far][0],
                            spans.stress[far][1] - spans.stress[rail][0],
                        )
                        total += volts / (ohms * (1 - other.data["tolerance"]))
        return total, unknown

    shared = others(name)
    if shared:
        why = f"{label} stands on a net ratings.json states, {shared[0]}: another source feeds its loads too"
        loads[(ref, name)] = (0.0, [why])
        if "amps" in pin:
            notes.append(f"{why}, and its load is not judged")
        return
    total, unknown = load(name, frozenset({ref}))
    loads[(ref, name)] = (total, unknown)
    if "amps" not in pin:
        return
    # a pack may hold a digital part and a linear one to 2 limits: the kind is `ic.` and the family
    rule = pack.rule("rail.load", f"{found.kind}.{found.data['family']}")
    share, rule_id = 1.0, "rail.load"
    source = f"{found.source}, {_p(pin['page'])}: the part's own rating"
    if rule is not None:
        share, note = factor(rule, project.ambient)
        rule_id, source = rule.id, f"{pack.document['number']}, {rule.where}"
        if note and note not in notes:
            notes.append(note)
    holds = total <= pin["amps"] * share + EPS
    if unknown and holds:  # what is known is inside the limit, and what is not known decides
        out.append(
            Finding("not judged", ref, "rail.load", f"{label} feeds a load nothing states: {unknown[0]}")
        )
        return
    of_it = f"{total / pin['amps']:.2f}"
    if not holds and of_it == f"{share:.2f}":  # 0.701 on a limit of 0.70: show which side it is on
        of_it = f"{total / pin['amps']:.3f}"
    text = (
        f"{label} gives {si(pin['amps'], 'A')}, its loads take {'at least ' * bool(unknown)}"
        f"{si(total, 'A')}: {of_it}, the limit is {share:.2f}"
    )
    judged(ref, rule_id, holds, text, source)


def _joined(net: Netlist, of: dict[str, Facts]) -> dict[str, str]:
    """Each net's node: the nets that a fuse, a ferrite, a link or a 0 ohm resistor joins are 1 node."""
    leader = {name: name for name in net.nets}

    def find(name: str) -> str:
        while leader[name] != name:
            leader[name] = leader[leader[name]]
            name = leader[name]
        return name

    for ref, found in of.items():
        pins = list(net.parts[ref].pins.values())
        wire = found.kind in ("fuse", "ferrite", "link")
        wire = wire or (found.kind == "resistor" and value_of(found, net.parts[ref]) == 0)
        if wire and len(pins) == 2:
            leader[find(pins[0])] = find(pins[1])
    return {name: find(name) for name in net.nets}


def _judge_buck(net, ref, of, spans, project, notes, judged, out, rails, loads) -> None:  # noqa: PLR0913
    """The inductor of 1 buck regulator. Against its saturation: the load on the output and half the
    ripple, at the greatest input, the least frequency and the least inductance (BUCK_NOTE). Against its
    rated current: the load."""
    found, part = of[ref], net.parts[ref]
    term = found.data["switching"]
    outputs = {name for _, name in rails.get(ref, [])}
    asked = any("inductor" in need for need in found.data.get("needs", []))
    for pin in found.data["pins"]:
        if pin["role"] != "switched":
            continue
        node = part.pins[pin["numbers"][0]]
        supply = part.pins[pin_number(found, part, pin["swing"][-1])]
        joined = _joined(net, of)  # a ferrite or a link after the inductor: still the output's node
        reached = {joined[name]: name for name in outputs}
        coils = [
            (n.ref, reached[joined[far]])
            for n in net.nets[node]
            if n.ref in of and of[n.ref].kind == "inductor"
            for far in net.parts[n.ref].pins.values()
            if joined[far] in reached
        ]
        if not coils and outputs and not asked:
            text = (
                f"{ref} pin {pin['numbers'][0]} ({pin['name']}) on {node}: a buck needs an inductor to "
                f"{', '.join(sorted(outputs))}, and none stands there"
            )
            judged(ref, "needs.inductor", False, text, f"{found.source}, {_p(term['page'])}")
        for coil, name in coils:
            data, label = of[coil].data, f"{coil} {net.parts[coil].value}".strip()
            source = f"{of[coil].source}: the part's own rating"
            total, unknown = loads.get((ref, name), (0.0, ["it was not worked out"]))
            beside = sum(1 for _, other in coils if other == name)  # inductors side by side share the load
            total, shared = total / beside, f", 1 of {beside} inductors side by side," if beside > 1 else ""
            henries = value_of(of[coil], net.parts[coil])
            why = ""
            if unknown and total > 0:
                # what is known of the load is a least value: past a rating, it fails whatever is left
                least = f"{label}: its loads take at least {si(total, 'A')}"
                over = False
                if "amps_rms" in data and total > data["amps_rms"] + EPS:
                    text = f"{least}, its rated current is {si(data['amps_rms'], 'A')}"
                    judged(coil, "inductor.heating", False, text, source)
                    over = True
                if total > data["amps_saturation"] + EPS and coil not in project.amps:
                    text = (
                        f"{least} before any ripple, and it saturates at {si(data['amps_saturation'], 'A')}"
                    )
                    judged(coil, "inductor.current", False, text, source)
                    over = True
                if over:
                    continue
            if unknown:
                why = f"the load on {name} is not known: {unknown[0]}"
            elif henries is None:
                why = "its Value is no number"
            elif not henries:  # `0u`: a number, and no inductance to divide a ripple by
                why = "its Value is 0 H"
            elif name not in spans.held or spans.held.get(supply, (0.0, 0.0))[1] <= 0:
                why = f"no source holds {supply if name in spans.held else name}"
            if why:
                text = f"{label}: its peak current is not worked out: {why}"
                out.append(Finding("not judged", coil, "inductor.current", text))
                continue
            if "amps_rms" in data:
                rated = si(data["amps_rms"], "A")
                text = f"{label}: its loads take {si(total, 'A')}, its rated current is {rated}"
                judged(coil, "inductor.heating", total <= data["amps_rms"] + EPS, text, source)
            if coil in project.amps:
                continue  # the project states its current, and that is what is judged
            least, hertz = henries * (1 - data["tolerance"]), term["hertz"][0]
            vin, share = spans.held[supply][1], _efficiency(ref, term, notes)

            def ripple(volts: float, vin=vin, share=share, least=least, hertz=hertz) -> float:
                return max(0.0, vin - volts) * min(1.0, volts / (vin * share)) / (hertz * least)

            low, high = spans.held[name]
            volts = max([low, high] + ([vin / 2] if low < vin / 2 < high else []), key=ripple)
            peak = total + ripple(volts) / 2
            text = (
                f"{label}: its peak current is {si(peak, 'A')}: {si(total, 'A')} of load{shared} and half of "
                f"{si(ripple(volts), 'A')} of ripple ({vin:.3g} V in, {volts:.3g} V out, {si(least, 'H')}, "
                f"{si(hertz, 'Hz')}); it saturates at {si(data['amps_saturation'], 'A')}"
            )
            judged(
                coil,
                "inductor.current",
                peak <= data["amps_saturation"] + EPS,
                text,
                f"{source}; {BUCK_NOTE}",
            )


def _judge_need(net, ref, need, of, spans, judged, out, rails, taken) -> None:  # noqa: PLR0913
    """1 support part a datasheet asks for: there, in range, and enough of it at its working voltage.
    An end that names a feedback pin is the net that pin's divider regulates. A value a datasheet names
    is a part's nominal value; an effective one is what the part keeps of it. taken: what the needs
    judged before this one took of the capacitors between each 2 nets."""
    found, part = of[ref], net.parts[ref]
    what = "capacitor" if "capacitor" in need else "inductor"
    asked = need[what]
    ends = []
    for end in ("from", "to"):
        pin = next(p for p in found.data["pins"] if p["name"] == asked[end])
        if pin["role"] != "feedback":
            ends.append(part.pins[pin_number(found, part, asked[end])])
            continue
        name = next((n for p, n in rails.get(ref, []) if p is pin), None)
        if name is None:
            return  # the divider was not read, and its own line says so
        ends.append(name)
    label = f"{ref} pin {asked['from']} ({ends[0]})"
    source = f"{found.source}, {_p(need['page'])}"
    joined = _joined(net, of)  # a part behind a fuse or a link stands on the pin's node
    spot = {joined[name] for name in ends}

    def between(r: str) -> bool:
        pins = net.parts[r].pins
        return len(pins) == 2 and {joined[name] for name in pins.values()} == spot

    there = [r for r, f in of.items() if f.kind.startswith(what) and between(r)]
    if not there:
        one = "a capacitor" if what == "capacitor" else "an inductor"
        blank = [r for r in net.parts if r not in of and between(r)]
        if blank:  # a part stands there, and nothing says what it is or what it gives
            text = f"{label} needs {one} to {ends[1]}: {blank[0]} stands there and has no facts"
            out.append(Finding("not judged", ref, f"needs.{what}", text))
            return
        judged(
            ref, f"needs.{what}", False, f"{label} needs {one} to {ends[1]}, and none stands there", source
        )
        return
    if what == "inductor":
        for r in there:
            henries, data = value_of(of[r], net.parts[r]), of[r].data
            if henries is None:
                out.append(
                    Finding("not judged", ref, "needs.inductor", f"{label}: the Value of {r} is no number")
                )
                continue
            low, high = henries * (1 - data["tolerance"]), henries * (1 + data["tolerance"])
            if "henries" in asked:
                text = (
                    f"{label} needs {si(asked['henries'][0], 'H')} to {si(asked['henries'][1], 'H')}, "
                    f"{r} is {si(low, 'H')} to {si(high, 'H')}"
                )
                holds = low >= asked["henries"][0] * (1 - EPS) and high <= asked["henries"][1] * (1 + EPS)
                judged(ref, "needs.inductor", holds, text, source)
            if "amps_saturation_min" in asked:
                least = si(asked["amps_saturation_min"], "A")
                text = (
                    f"{label} needs an inductor that saturates above {least}, "
                    f"{r} saturates at {si(data['amps_saturation'], 'A')}"
                )
                judged(
                    ref,
                    "needs.inductor",
                    data["amps_saturation"] >= asked["amps_saturation_min"] - EPS,
                    text,
                    source,
                )
        return
    held = all(n in spans.held for n in ends)
    if held:
        volts = max(
            spans.held[ends[0]][1] - spans.held[ends[1]][0], spans.held[ends[1]][1] - spans.held[ends[0]][0]
        )
    elif all(n in spans.stress for n in ends):
        volts = max(
            spans.stress[ends[0]][1] - spans.stress[ends[1]][0],
            spans.stress[ends[1]][1] - spans.stress[ends[0]][0],
        )
    else:
        volts = None
    total, most, parts, missing = 0.0, 0.0, [], ""
    for r in there:
        farads, data = value_of(of[r], net.parts[r]), of[r].data
        if farads is None:
            out.append(
                Finding("not judged", ref, "needs.capacitor", f"{label}: the Value of {r} is no number")
            )
            return
        if asked.get("effective") and "tolerance" not in data:
            # nothing for sure, and nothing bounds the most it gives: the need cannot be judged
            out.append(
                Finding("not judged", ref, "needs.capacitor", f"{label}: {r} has no tolerance in its facts")
            )
            return
        if asked.get("effective"):  # what is left of it: less its tolerance, at this voltage
            share = kept_at(data["kept"], volts) if "kept" in data and volts is not None else None
            if share is None:  # it gives its whole value at the most, and nothing for sure
                at = "its working voltage" if volts is None else si(volts, "V")
                why = "no data on the value it keeps"
                if "kept" in data:
                    why = f"its data on the value it keeps ends below {at}"
                missing = missing or (f"{r}: {why}" if "kept" in data else f"{r} has {why} at {at}")
                most += farads * (1 + data["tolerance"])
                parts.append(f"{r} gives {si(farads * (1 + data['tolerance']), 'F')} at most ({why})")
                continue
            farads *= (1 - data["tolerance"]) * share
        total += farads
        parts.append(f"{r} gives {si(farads, 'F')}")
    # The needs on 2 nets share the capacitors between them: each takes its own, in the order of the
    # parts, and the one that finds too little left is the one that fails.
    before = taken.get(frozenset(ends), 0.0)
    taken[frozenset(ends)] = before + asked["farads_min"]
    enough = total - before >= asked["farads_min"] * (1 - EPS)
    if not enough and total + most - before >= asked["farads_min"] * (1 - EPS):
        # short for sure, enough at the most: the data that is missing decides
        out.append(Finding("not judged", ref, "needs.capacitor", f"{label}: {missing}"))
        return
    kind = "effective " if asked.get("effective") else ""
    text = f"{label} needs {si(asked['farads_min'], 'F')} {kind}to {ends[1]}: {', '.join(parts)}"
    if before:
        text += f", and the needs before it take {si(before, 'F')}"
    judged(ref, "needs.capacitor", enough, text, source)


def lines(report: Report, limit: int = 20) -> list[str]:
    """What the command prints: 1 line of counts, then the findings that are no hold, failures first."""
    count = {s: sum(f.status == s for f in report.findings) for s in STATUSES}
    head = (
        f"ratings: {count['fail']} fail, {count['accepted']} accepted, {count['hold']} hold, "
        f"{count['not judged']} not judged; pack {report.pack}"
    )
    if report.unread:
        head += f"; {report.unread} source{'s' * (report.unread != 1)} not read a second time"
    shown = [f for f in report.findings if f.status != "hold"]
    out = [head] + [f.line for f in shown[:limit]]
    if len(shown) > limit:
        out.append(f"... {len(shown) - limit} more in the report")
    return out


def verdict(report: Report, strict: bool = False) -> tuple[str, int]:
    """The last line and the exit code. A verdict is never stronger than its run: what was not judged is
    in the line, and fails the run when strict."""
    fail = sum(f.status == "fail" for f in report.findings)
    left = sum(f.status == "not judged" for f in report.findings)
    if fail:
        return f"RATINGS NOT HELD ({fail} fail{f', {left} not judged' if left else ''})", 1
    if fail + left == len(report.findings):  # no stress was held to a limit: that is no pass
        return f"NOTHING JUDGED ({left} not judged)", 1
    if left:
        return f"RATINGS HELD, {left} NOT JUDGED", 1 if strict else 0
    return "RATINGS HELD", 0


# The rules of 2 failures that are no stress past a limit: an entry of `accepted` that nothing fails
# under, and facts that number a pin another way than the symbol. No entry of `accepted` takes either.
NO_STRESS = ("accepted", "facts")


def markdown(report: Report, strict: bool = False) -> str:
    """The whole report as a page: every finding, the holds too, and what the report says once."""
    out = ["# Ratings", "", lines(report, 0)[0], "", verdict(report, strict)[0], ""]
    for status in STATUSES:
        found = [f for f in report.findings if f.status == status]
        if found:
            out += [f"## {status.capitalize()}: {len(found)}", ""]
            for f in found:
                out.append(f"- {f.text}" + (f" [{f.source}]" if f.source else ""))
                if status == "fail" and f.rule not in NO_STRESS:  # what ratings.json's `accepted` names
                    out.append(f"  - to accept it, the owner names part `{f.part}` and rule `{f.rule}`")
            out.append("")
    if report.notes:
        out += ["## Notes", ""] + [f"- {note}" for note in report.notes] + [""]
    return "\n".join(out)


def unjudged(summary: str, why: list[str]) -> str:
    """The page of a run that judged nothing: a file the command does not take, a schematic kicad-cli
    did not load. It takes the place of an earlier run's page, which holds the verdict of other files."""
    out = ["# Ratings", "", f"ratings: {summary}", "", "Nothing was judged.", ""]
    said = [f"- {line.strip()}" for line in why if line.strip()]
    return "\n".join(out + (said + [""] if said else []))


# ---------------------------------------------------------------- the command

FIRST = {"pack": "nasa-eee-inst-002", "nets": {}}  # what --init writes: a pack, and no net stated yet
SHOWN = 20  # the most finding lines the command prints; the report file holds them all


def find_facts(start: Path) -> Path | None:
    """The nearest library/facts at or above a folder."""
    for folder in (start, *start.parents):
        if (folder / "library" / "facts").is_dir():
            return folder / "library" / "facts"
    return None


def find_pack(name: str, project_dir: Path, packs: Path) -> Path:
    """A pack by its name among the workcenter's, or by a path from the project's folder. A pack of the
    workcenter goes by its name alone: a name that walks out of the packs' folder is none of them."""
    shipped = packs / f"{name}.json"
    if shipped.parent == packs and shipped.is_file():
        return shipped
    if (project_dir / name).is_file():
        return project_dir / name
    known = ", ".join(sorted(p.stem for p in packs.glob("*.json")))
    raise Refusal(f"ratings.json: pack: `{name}` is no pack; the workcenter holds {known}")


def parts_rows(paths: list[Path], cli) -> list:
    """The rows of the parts files, as `procure` and `sources` read them. A file that is not there, that
    is no UTF-8, or that holds a row with fewer fields than its header is refused with its name and its
    line: the workcenter's reader of a row asks every field of it."""
    rows = []
    for path in paths:
        try:
            with path.open(encoding="utf-8", newline="") as fh:
                reader = csv.reader(fh)
                header = next(reader, [])
                for row in reader:
                    if row and len(row) < len(header):
                        fields = f"{len(row)} field{'s' * (len(row) != 1)}"
                        raise Refusal(
                            f"{path.name}:{reader.line_num}: {fields}, and the header names {len(header)}"
                        )
        except OSError as exc:
            raise Refusal(f"{path}: {exc.strerror or exc}") from None
        except UnicodeDecodeError as exc:
            raise Refusal(f"{path.name}: not UTF-8: {exc}") from None
        except csv.Error as exc:
            raise Refusal(f"{path.name}: {exc}") from None
        try:
            rows += cli.read_parts(path)
        except ValueError as exc:  # the workcenter's reader names the file and the line
            raise Refusal(str(exc)) from None
    return rows


def export_netlist(project, folder: Path, cli) -> tuple[Netlist | None, str]:
    """The schematic's netlist, exported into a folder: the netlist, or None and what kicad-cli said.
    A run that exports none leaves none: the netlist of an earlier run is of another schematic. A
    netlist its reader does not take is refused with the name of the schematic, the file the fault
    is in."""
    text, stderr = cli.schematic_netlist(project, folder)
    if text is None:
        (folder / "netlist.xml").unlink(missing_ok=True)
        return None, stderr
    try:
        return read_netlist(text), ""
    except ValueError as exc:
        raise Refusal(f"{project.sch.name}: {exc}") from None


def refusal(exc: Exception, cli):
    """A file or a flag the command does not take, as a Result of the workcenter's kind."""
    return cli.Result("ratings", "fail", "a file is not as the command reads it", {"failures": [str(exc)]})


def part_numbers(net: Netlist, rows: list) -> dict[str, str]:
    """Each part's manufacturer part number from the parts files: the first row with the part's Value
    and Footprint, as `sources` and `procure` match a line."""
    out = {}
    for ref, part in net.parts.items():
        row = next(
            (r for r in rows if r.footprint and (r.value, r.footprint) == (part.value, part.footprint)), None
        )
        if row is not None and row.buys and row.mpn:
            out[ref] = row.mpn
    return out


# What `parts` of ratings.json may state, by the kind of the part's facts. judge() reads the current
# through a resistor, an inductor, a diode, a transistor, a fuse, a ferrite and a switch, the load
# behind a connector's pin, and the voltage across a capacitor and a resistor. The current behind an
# output pin of an IC is taken and held to nothing yet: the report's notes name it.
CURRENT_KINDS = ("resistor", "inductor", "diode.rectifier", "transistor.mosfet", "fuse", "ferrite", "switch")
VOLTAGE_KINDS = ("capacitor", "resistor")
LOAD_ROLES = ("output", "io", "open_drain")


def check_stated(project: Project, net: Netlist, mpns: dict[str, str], facts: list[Facts]) -> None:
    """Refuses a current or a voltage ratings.json states for a part or a pin the command reads none
    for: it would be taken without a word and held to nothing, and `J2` written for `J2.1` leaves a
    load out of its rail. A part with no facts is passed over: nothing says yet what it is."""

    def among(kinds: tuple[str, ...], kind: str) -> bool:
        return any(kind == k or kind.startswith(f"{k}.") for k in kinds)

    for key in project.amps:
        ref, _, pin = key.partition(".")
        found = facts_of(facts, net.parts[ref], mpns.get(ref, ""))
        if found is None:
            continue
        kind, where = found.kind, f"ratings.json: parts: {key}: amps"
        if not pin and kind == "connector":
            one = min(net.parts[ref].pins, default="")
            how = f", as {ref}.{one}" if one else ""
            raise Refusal(f"{where}: {ref} is a connector: its load is stated for 1 pin{how}")
        if not pin and not among(CURRENT_KINDS, kind):
            raise Refusal(f"{where}: {ref} is of kind {kind}: the command reads no current through one")
        if pin and kind == "ic":
            # a pin its facts do not name has no role here: judge() refuses those facts
            role = next((p["role"] for p in found.data["pins"] if pin in p["numbers"]), None)
            if role is not None and role not in LOAD_ROLES:
                raise Refusal(
                    f"{where}: pin {pin} of {ref} is of role {role}: the command reads no load behind one"
                )
        elif pin and kind != "connector":
            raise Refusal(f"{where}: {ref} is of kind {kind}: the command reads no load behind a pin of one")
    for ref in project.volts:
        found = facts_of(facts, net.parts[ref], mpns.get(ref, ""))
        if found is not None and not among(VOLTAGE_KINDS, found.kind):
            where = f"ratings.json: parts: {ref}: volts"
            raise Refusal(f"{where}: {ref} is of kind {found.kind}: the command reads no voltage across one")


def skeleton(net: Netlist, ref: str, mpn: str) -> dict:
    """A facts entry for 1 part with its pins from the schematic and every fact left to fill from the
    datasheet. The command refuses the entry until it is filled: an empty kind, role or source."""
    part = net.parts[ref]
    pins: dict[str, list[str]] = {}
    for nodes in net.nets.values():
        for node in nodes:
            if node.ref == ref:
                pins.setdefault(node.name or node.pin, []).append(node.pin)
    source = {"document": "", "revision": "", "url": "", "sha256": "", "read": "", "second_reader": "no"}
    entry = {"kind": "", **({"mpn": mpn} if mpn else {"symbol": part.symbol}), "source": source}
    if len(part.pins) > 2:
        entry["pins"] = [
            {"numbers": sorted(n), "name": name, "role": "", "page": 0} for name, n in pins.items()
        ]
    return entry


def gate_ratings(project, out: Path, parts: list[Path], strict: bool, cli):
    """The command's run as a Result of the workcenter's kind: skip when the project asks for no
    judgement or holds no schematic, fail on a file the command does not take, on a failure, and with
    --strict on what was not judged."""
    if not project.sch:
        return cli.Result("ratings", "skip", "no schematic in project")
    stated = project.dir / "ratings.json"
    if not stated.is_file():
        how = f"`workcenter ratings {project.dir} --init` writes one"
        return cli.Result("ratings", "skip", f"no ratings.json beside the schematic: {how}")
    folder = out / "ratings"
    folder.mkdir(parents=True, exist_ok=True)
    try:  # the reader's refusal alone: kicad-cli that is not installed goes on to `timed`, which names it
        net, stderr = export_netlist(project, folder, cli)
    except ValueError as exc:
        return refusal(exc, cli)
    if net is None:
        return cli.Result("ratings", "error", "kicad-cli wrote no netlist", {"stderr": stderr})
    try:
        asked = read_project(stated, net)
        packs = cli.SRC_DIR / "rules" / "ratings"
        found = find_pack(asked.pack, project.dir, packs)
        # a file of the workcenter's packs is the workcenter's, by whatever path the project names it
        pack = read_pack(found, "" if found.resolve().parent == packs.resolve() else asked.pack)
        library = find_facts(project.dir)
        facts = read_facts(library) if library else []
        mpns = part_numbers(net, parts_rows(parts, cli))
        report = judge(net, mpns, facts, asked, pack)
        # after the judgement, which refuses facts that do not fit their part: those are the fault
        # then, and not the number ratings.json states for the part
        check_stated(asked, net, mpns, facts)
    except (ValueError, OSError) as exc:
        return refusal(exc, cli)
    said, code = verdict(report, strict)
    page = folder / "report.md"
    page.write_text(markdown(report, strict), encoding="utf-8")
    red = ("fail", "not judged") if strict else ("fail",)
    failures = [f.line for f in report.findings if f.status in red]
    warnings = [f.line for f in report.findings if f.status not in (*red, "hold")]
    more = len(failures) + len(warnings) - SHOWN
    failures, warnings = failures[:SHOWN], warnings[: max(0, SHOWN - len(failures))]
    if more > 0:
        (failures if not warnings else warnings).append(f"... {more} more in {page}")
    details = {
        "failures": failures,
        "warnings": warnings,
        "verdict": said,
        "pack": report.pack,
        "notes": report.notes,
        "findings": [vars(f) for f in report.findings],
    }
    summary = lines(report, 0)[0].removeprefix("ratings: ")
    return cli.Result("ratings", "fail" if code else "pass", summary, details, [str(page)])


def cmd_ratings(args, cli) -> int:
    """A run, or with --init or --facts 1 thing that judges nothing and leaves no record of a run. A
    file or a flag the command does not take is answered the same way in all 3: the line of a refusal,
    and exit code 1."""
    project = cli.find_project(args.project)
    stated = project.dir / "ratings.json"
    if args.init:  # 1 file beside the schematic: no folder of output is asked for, and none is made
        if stated.is_file():
            print(f"{stated} is there already: nothing written")
        else:
            stated.write_text(json.dumps(FIRST, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {stated}: pack {FIRST['pack']}, no net stated yet")
        return 0
    parts = [Path(p).resolve() for p in args.parts or []]
    if not parts and (project.dir / "parts.csv").is_file():
        parts = [project.dir / "parts.csv"]
    try:
        out = cli.out_dir_for(project, args.out)
    except OSError as exc:
        folder = Path(args.out).resolve() if args.out else project.dir / "build"
        why = "a file stands there, and a folder is asked" if folder.is_file() else exc.strerror or exc
        where = f"--out {folder}" if args.out else folder
        return cli.emit([refusal(Refusal(f"{where}: {why}"), cli)], args, None)
    if args.facts:
        if not project.sch:  # as a run says it: kicad-cli is not asked, and no folder is made
            return cli.emit([cli.Result("ratings", "skip", "no schematic in project")], args, None)
        folder = out / "ratings"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            net, stderr = export_netlist(project, folder, cli)
            if net is None:
                raise SystemExit(f"{project.dir}: kicad-cli wrote no netlist: {stderr}")
            if args.facts not in net.parts:
                raise SystemExit(f"{args.facts} is no part of the schematic")
            mpn = part_numbers(net, parts_rows(parts, cli)).get(args.facts, "")
        except FileNotFoundError as exc:  # kicad-cli itself: a file that is not there is a Refusal
            missing = {"engine_missing": str(exc.filename)}
            return cli.emit(
                [cli.Result("ratings", "skip", f"engine missing: {exc.filename}", missing)], args, None
            )
        except (ValueError, OSError) as exc:
            return cli.emit([refusal(exc, cli)], args, None)
        print(json.dumps(skeleton(net, args.facts, mpn), indent=2))
        return 0
    result = cli.timed(gate_ratings)(project, out, parts, args.strict, cli)
    if result.status != "skip":  # a refusal and an error leave their record too: `next` reads it
        folder = out / "ratings"
        if "verdict" not in result.details:  # and their page, in place of an earlier run's verdict
            why = result.details.get("failures") or result.details.get("stderr", "").splitlines()
            (folder / "report.md").write_text(unjudged(result.summary, why), encoding="utf-8")
            result.artifacts.append(str(folder / "report.md"))
        (folder / "report.json").write_text(json.dumps(vars(result), indent=2), encoding="utf-8")
    code = cli.emit([result], args, None)
    if not args.json and "verdict" in result.details:
        print(f"{result.details['verdict']}: {project.name}  report {result.artifacts[0]}")
    return code


def register(sub, cli) -> None:
    """Add `ratings` to the workcenter's parser; it sets `run` to its handler."""
    p = sub.add_parser(
        "ratings",
        help="hold the schematic to its parts' ratings: each pin's voltage limits, each capacitor's, "
        "resistor's, diode's and transistor's derating by the rule pack ratings.json names, each "
        "regulator's load and the support parts its datasheet asks for; writes netlist.xml, report.md "
        "and report.json into <out>/ratings/, and lists what it could not judge",
    )
    p.add_argument("project", help="project directory or a .kicad_pro/.kicad_sch/.kicad_pcb file")
    p.add_argument("--out", help="output directory (default <project>/build)")
    p.add_argument("--strict", action="store_true", help="what is not judged fails the run")
    p.add_argument(
        "--parts",
        action="append",
        metavar="FILE",
        help="a parts CSV naming each line's MPN (repeatable); default <project>/parts.csv",
    )
    p.add_argument(
        "--init",
        action="store_true",
        help="write ratings.json beside the schematic when there is none, and judge nothing",
    )
    p.add_argument(
        "--facts",
        metavar="REF",
        help="print an empty facts entry for one part, with its pins, to fill from its datasheet",
    )
    p.set_defaults(run=lambda a: cmd_ratings(a, cli))
