#!/usr/bin/env python3
"""highspeed — a board's fast nets held to the rules of their interfaces.

A project names each interface in `interfaces.json`: the interface (a file in rules/interfaces/), its 2
nets, and, if it likes, the pair's gap. Each limit of an interface file names its document, clause, table
and page. For each layer a pair runs on, the gap is measured on the board: the edge-to-edge distance of
the 2 tracks where they run side by side, the gap over the most of their length. The cross-section
solver (tools/xsection.py, under the venv) gives the widths for the impedance band on the board's own
stackup at that gap, and the gaps for the band at the nominal width.

The command writes KiCad's rules (`track_width`, `diff_pair_gap`, `length`, `skew`) into
<out>/highspeed/highspeed.kicad_dru, for KiCad's DRC, and judges these rules itself on the board file:

    width   every segment of a fast net within the band the solver gave for its layer, at the gap the
            board has there
    gap     every run of the pair at the gap interfaces.json gives, when it gives one; else each gap
            but the main one solved at the tracks' widths and held to the band. KiCad's own
            diff_pair_gap rule reads only nets whose names end in _P/_N or +/-
    coupling  the stretches of a net with no parallel partner: break-out within the interface's
            distance of the pair's pads holds, any other is not judged
    spacing, stitching  the TI files' 30 mil to other signals' tracks, and a ground via within 200 mil
            of a via that moves the pair to other ground planes
    length  each net's track length (or its delay, where the document sets a delay) under the limit
    skew    the difference of the pair's 2 lengths under the limit
    vias    the vias of each net, where the document sets a count
    plane   every point of a fast track's centre line over the fill of each ground pour that bounds it:
            the nearest copper layer below and the nearest above that hold a ground pour. A pour of
            another net (a power plane) nearer to the track fails.

A ground pour is a pour of a net named GND or VSS, or whose name begins or ends with GND. Via barrels
are not counted in a length. The width is not judged beside ground on the track's own layer (COPLANAR),
and length, skew and plane are not judged on a net whose tracks do not reach all its pads. A dielectric
of several sublayers is read sublayer by sublayer. A limit the documents set that the command does not
judge, and a limit they do not set, is printed as not judged, with the reason. Standard library only.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kicadgen  # noqa: E402  S-expressions

SPEC_DIR = Path(__file__).resolve().parents[1] / "rules" / "interfaces"
CONSTANTS = json.loads((SPEC_DIR / "constants.json").read_text(encoding="utf-8"))
C0 = CONSTANTS["c0_m_per_s"]["value"]
STEP = 0.01  # mm between the points of a track's centre line the plane check looks under
READ = 3  # decimals of a mm a gap is read to: 1 um
PARALLEL = 1e-3  # the sine of the angle under which 2 tracks count as parallel
RAYS = 16  # directions looked along from a via or a pad for the fill round its hole
# Ground poured on a track's own layer within this many times the track's height over its plane makes
# the width not judged: the solver has no ground beside the track. With 2 grounded strips added to the
# solver's grid, a pour 3 heights from the pair's outer edges moved Z_diff by 0.11 % on the fixtures'
# 0.2104 mm microstrip and 0.26 % on a 1.51 mm 2-layer board; 1 height away, by 2.3 % and 1.0 %.
COPLANAR = 3.0
BREAK_SAMPLE = 0.1  # mm between the points of a stretch held to the pads' break-out distance


class NotJudged(Exception):
    """What the board does not give, so a rule cannot be judged."""


@dataclass
class Finding:
    status: str  # held, fail, not judged
    rule: str
    text: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    rules: str = ""
    bands: dict = field(default_factory=dict)

    def fails(self) -> list[Finding]:
        return [f for f in self.findings if f.status == "fail"]

    def not_judged(self) -> list[Finding]:
        return [f for f in self.findings if f.status == "not judged"]


@dataclass
class Track:
    net: str
    layer: str
    points: list[tuple[float, float]]  # a segment's 2 ends, an arc's start, middle and end
    width: float

    def length(self) -> float:
        if len(self.points) == 2:
            (x1, y1), (x2, y2) = self.points
            return math.hypot(x2 - x1, y2 - y1)
        return _arc_length(*self.points)

    def samples(self) -> list[tuple[float, float]]:
        """Points along the centre line, STEP apart (an arc as its 2 chords through the middle)."""
        out = []
        for (x1, y1), (x2, y2) in zip(self.points, self.points[1:], strict=False):
            n = max(1, math.ceil(math.hypot(x2 - x1, y2 - y1) / STEP))
            out += [(x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n) for i in range(n + 1)]
        return out


@dataclass
class Board:
    # ("copper", name, thickness) and ("dielectric", thickness, er, name), top to bottom
    stack: list[tuple]
    tracks: list[Track]
    vias: dict[str, int]  # net -> count
    fills: dict[str, list[list[tuple[float, float]]]]  # layer -> filled polygons of its ground pours
    pours: dict[str, set[str]]  # layer -> the nets of its pours
    nets: set[str]
    holes: list[tuple[str, float, float, float]] = field(default_factory=list)  # net, x, y, half diagonal
    margins: dict[str, float] = field(default_factory=dict)  # layer -> pour clearance + min thickness
    pads: list[Pad] = field(default_factory=list)
    via_at: list[tuple[str, float, float, float]] = field(default_factory=list)  # net, x, y, radius
    fill_nets: dict[str, list[str]] = field(default_factory=dict)  # layer -> the net of each of its fills

    def planes(self) -> set[str]:
        """The layers that hold a ground pour."""
        return {layer for layer, nets in self.pours.items() if any(is_ground(n) for n in nets)}


@dataclass
class Pad:
    net: str
    name: str  # "J2 pad 1"
    x: float
    y: float
    reach: float  # half the pad's diagonal: a track end within it lands on the pad
    through: bool
    layers: list[str]

    def on(self, layer: str) -> bool:
        return self.through or layer in self.layers or ("*.Cu" in self.layers and layer.endswith(".Cu"))


def is_ground(net: str) -> bool:
    name = net.rsplit("/", 1)[-1].upper()
    return name in ("GND", "VSS") or name.startswith("GND") or name.endswith("GND")


def _arc_length(a, m, b) -> float:
    (ax, ay), (mx, my), (bx, by) = a, m, b
    d = 2 * (ax * (my - by) + mx * (by - ay) + bx * (ay - my))
    if abs(d) < 1e-12:
        return math.hypot(bx - ax, by - ay)
    ux = ((ax**2 + ay**2) * (my - by) + (mx**2 + my**2) * (by - ay) + (bx**2 + by**2) * (ay - my)) / d
    uy = ((ax**2 + ay**2) * (bx - mx) + (mx**2 + my**2) * (ax - bx) + (bx**2 + by**2) * (mx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    chord = math.hypot(bx - ax, by - ay)
    angle = 2 * math.asin(min(1.0, chord / (2 * r)))
    # The middle point on the far side of the chord's centre makes the arc the major one.
    cx, cy = (ax + bx) / 2, (ay + by) / 2
    if (mx - cx) * (ux - cx) + (my - cy) * (uy - cy) > 0:
        angle = 2 * math.pi - angle
    return r * angle


def _to_segment(p, a, b) -> float:
    """The distance from point p to the segment a b."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    span = dx * dx + dy * dy
    s = 0.0 if span == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / span))
    return math.hypot(px - ax - s * dx, py - ay - s * dy)


def _between(a, b, c, d) -> float:
    """The least distance between the segments a b and c d."""

    def side(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    if side(a, b, c) * side(a, b, d) < 0 and side(c, d, a) * side(c, d, b) < 0:
        return 0.0
    return min(_to_segment(a, c, d), _to_segment(b, c, d), _to_segment(c, a, b), _to_segment(d, a, b))


def _xy(node) -> tuple[float, float]:
    vals = kicadgen.atoms(node)
    return (kicadgen.num(vals[0]), kicadgen.num(vals[1]))


def _pts(node) -> list[tuple[float, float]]:
    pts = kicadgen.child(node, "pts")
    return [_xy(p) for p in kicadgen.children(pts, "xy")] if pts else []


def _text(node, head: str) -> str:
    c = kicadgen.child(node, head)
    return kicadgen.atoms(c)[0] if c is not None and kicadgen.atoms(c) else ""


def _number(value: str, layer: str, what: str) -> float:
    try:
        return kicadgen.num(value)
    except ValueError:
        given = f"gives its {what} as {value!r}" if value else f"gives no {what}"
        raise ValueError(f"stackup layer {layer!r} {given}; the command cannot read this stack") from None


def _sublayers(layer: list, name: str) -> list[tuple]:
    """A dielectric's slabs, top down: ("dielectric", thickness, er or None, name). KiCad writes a
    dielectric of several sublayers as 1 layer whose children run on after the bare word `addsublayer`,
    1 run a sublayer. Neighbouring sublayers of one er are 1 slab."""
    runs: list[list] = [[]]
    for item in layer[2:]:
        if item == "addsublayer":
            runs.append([])
        elif isinstance(item, list):
            runs[-1].append(item)
    out: list[tuple] = []
    for i, run in enumerate(runs):
        node = ["sublayer", *run]
        label = name if len(runs) == 1 else f"{name}, sublayer {i + 1}"
        thick = _number(_text(node, "thickness"), label, "thickness")
        er_text = _text(node, "epsilon_r")
        er = _number(er_text, label, "epsilon_r") if er_text else None
        if out and er is not None and out[-1][2] == er:
            out[-1] = ("dielectric", out[-1][1] + thick, er, name)
        else:
            out.append(("dielectric", thick, er, name))
    return out


def read_board(text: str) -> Board:
    root = kicadgen.parse(text)
    setup = kicadgen.child(root, "setup")
    stackup = kicadgen.child(setup, "stackup") if setup is not None else None
    stack: list[tuple] = []
    if stackup is not None:
        for layer in kicadgen.children(stackup, "layer"):
            kind = _text(layer, "type")
            name = kicadgen.atoms(layer)[0]
            if kind == "copper":
                stack.append(("copper", name, _number(_text(layer, "thickness"), name, "thickness")))
            elif kind in ("core", "prepreg"):
                stack += _sublayers(layer, name)
    tracks, vias, nets = [], {}, set()
    for net in kicadgen.children(root, "net"):
        vals = kicadgen.atoms(net)
        if vals:
            nets.add(vals[-1])
    for head in ("segment", "arc"):
        for item in kicadgen.children(root, head):
            net = _text(item, "net")
            nets.add(net)
            keys = ("start", "end") if head == "segment" else ("start", "mid", "end")
            points = [_xy(kicadgen.child(item, k)) for k in keys]
            tracks.append(Track(net, _text(item, "layer"), points, kicadgen.num(_text(item, "width"))))
    holes: list[tuple[str, float, float, float]] = []
    via_at: list[tuple[str, float, float, float]] = []
    pads: list[Pad] = []
    for item in kicadgen.children(root, "via"):
        net = _text(item, "net")
        vias[net] = vias.get(net, 0) + 1
        x, y = _xy(kicadgen.child(item, "at"))
        holes.append((net, x, y, kicadgen.num(_text(item, "size")) / 2))
        via_at.append((net, x, y, kicadgen.num(_text(item, "size")) / 2))
    fills: dict[str, list] = {}
    fill_nets: dict[str, list[str]] = {}
    pours: dict[str, set[str]] = {}
    margins: dict[str, float] = {}
    for zone in kicadgen.children(root, "zone"):
        if kicadgen.child(zone, "keepout") is not None:
            continue
        net = _text(zone, "net_name") or _text(zone, "net")
        layers = [_text(zone, "layer")] if kicadgen.child(zone, "layer") is not None else []
        many = kicadgen.child(zone, "layers")
        if many is not None:
            layers = kicadgen.atoms(many)
        for layer in layers:
            pours.setdefault(layer, set()).add(net)
        if is_ground(net):
            for filled in kicadgen.children(zone, "filled_polygon"):
                fills.setdefault(_text(filled, "layer"), []).append(_pts(filled))
                fill_nets.setdefault(_text(filled, "layer"), []).append(net)
        clearance = kicadgen.child(zone, "connect_pads")
        clear = (
            kicadgen.num(_text(clearance, "clearance"))
            if clearance is not None and _text(clearance, "clearance")
            else 0.0
        )
        thick = kicadgen.num(_text(zone, "min_thickness")) if _text(zone, "min_thickness") else 0.0
        for layer in layers:
            margins[layer] = max(margins.get(layer, 0.0), clear + thick)
    for item in kicadgen.children(root, "footprint"):
        fx, fy, *rot = (kicadgen.num(v) for v in kicadgen.atoms(kicadgen.child(item, "at")))
        angle = math.radians(rot[0]) if rot else 0.0
        ref = next(
            (
                kicadgen.atoms(p)[1]
                for p in kicadgen.children(item, "property")
                if kicadgen.atoms(p)[:1] == ["Reference"] and len(kicadgen.atoms(p)) > 1
            ),
            "?",
        )
        for pad in kicadgen.children(item, "pad"):
            n = _text(pad, "net")
            if n:
                nets.add(n)
            px, py = _xy(kicadgen.child(pad, "at"))
            sx, sy = _xy(kicadgen.child(pad, "size"))
            x = fx + px * math.cos(angle) + py * math.sin(angle)
            y = fy - px * math.sin(angle) + py * math.cos(angle)
            through = "thru_hole" in kicadgen.atoms(pad)
            layers = kicadgen.atoms(kicadgen.child(pad, "layers")) if kicadgen.child(pad, "layers") else []
            name = kicadgen.atoms(pad)[0] if kicadgen.atoms(pad) else "?"
            pads.append(Pad(n, f"{ref} pad {name}", x, y, math.hypot(sx, sy) / 2, through, layers))
            if through:  # only a hole through the board makes a hole in an inner plane
                holes.append((n, x, y, math.hypot(sx, sy) / 2))
    return Board(stack, tracks, vias, fills, pours, nets, holes, margins, pads, via_at, fill_nets)


def _index(board: Board, layer: str) -> int | None:
    return next((i for i, s in enumerate(board.stack) if s[0] == "copper" and s[1] == layer), None)


def _nearest(board: Board, layer: str, step: int, among: set[str]) -> int | None:
    """The index in the stack of the nearest copper layer past `layer`, in the direction `step`, whose
    name is in `among`."""
    i = _index(board, layer) + step
    while 0 <= i < len(board.stack):
        if board.stack[i][0] == "copper" and board.stack[i][1] in among:
            return i
        i += step
    return None


def plane_refs(board: Board, layer: str) -> list[str]:
    """The ground planes that bound a track on `layer`: the nearest below first, then the nearest above."""
    if _index(board, layer) is None:
        return []
    planes = board.planes()
    found = [_nearest(board, layer, +1, planes), _nearest(board, layer, -1, planes)]
    return [board.stack[i][1] for i in found if i is not None]


def section_for(board: Board, layer: str) -> tuple[dict | None, list[str]]:
    """The cross-section of a track on `layer`: the slabs from its reference plane to it (and on to a
    second plane, or to the board's face), the strip's height and thickness. The planes are the nearest
    copper layers above and below that hold a ground pour. (None, []) when no layer does. NotJudged when
    a dielectric between them has no epsilon_r."""
    idx = _index(board, layer)
    if idx is None:
        return None, []
    planes = board.planes()
    below, above = _nearest(board, layer, +1, planes), _nearest(board, layer, -1, planes)
    base, other = (below, above) if below is not None else (above, None)
    if base is None:
        return None, []
    step = -1 if base > idx else 1
    end = other if other is not None else (-1 if step == -1 else len(board.stack))

    def er_of(item: tuple) -> float:
        if item[2] is None:
            raise NotJudged(f"the stackup gives no epsilon_r for {item[3]} ({item[1]:g} mm) by {layer}")
        return item[2]

    slabs: list[list[float]] = []
    height, y, t, er_last = 0.0, None, 0.0, None
    i = base + step
    while i != end:
        item = board.stack[i]
        if item[0] == "dielectric":
            er_last = er_of(item)
            slabs.append([item[1], er_last])
            height += item[1]
        elif item[1] == layer:
            y, t = height, item[2]
            # The copper's own height beside the strip: the next slab's resin, or air on the face.
            j = i + step
            while j != end and board.stack[j][0] != "dielectric":
                j += step
            if j != end:
                slabs.append([t, er_of(board.stack[j])])
                height += t
        else:
            if er_last is None:
                raise NotJudged(
                    f"the stackup gives no dielectric between {board.stack[base][1]} and {item[1]}"
                )
            slabs.append([item[2], er_last])
            height += item[2]
        i += step
    refs = [board.stack[base][1]] + ([board.stack[other][1]] if other is not None else [])
    section = {"slabs": [[round(h, 6), er] for h, er in slabs], "top_plane": other is not None}
    section.update({"y": round(y, 6), "t": t})
    return section, refs


def net_length(board: Board, net: str) -> float:
    return sum(t.length() for t in board.tracks if t.net == net)


def _inside(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    x, y = pt
    hit = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def load_spec(name: str) -> dict:
    path = SPEC_DIR / f"{name}.json" if isinstance(name, str) else None
    if path is None or name == "constants" or not path.is_file():
        known = ", ".join(sorted(p.stem for p in SPEC_DIR.glob("*.json") if p.stem != "constants"))
        raise ValueError(f"no interface {name!r} in rules/interfaces/: it holds {known}")
    return json.loads(path.read_text(encoding="utf-8"))


SHAPE = 'expected {"interfaces": [...]} with 1 interface or more, each {"interface": ..., "nets": [P, N]}'


def read_interfaces(project: Path) -> list[dict]:
    path = project / "interfaces.json"
    if not path.is_file():
        raise ValueError(f"{path}: no interfaces.json; name each interface and its nets there")
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("interfaces") if isinstance(data, dict) else None
    if not isinstance(entries, list) or not entries or not all(isinstance(e, dict) for e in entries):
        raise ValueError(f"{path}: interfaces.json: {SHAPE}")
    return entries


def cite(spec: dict, limit: dict) -> str:
    doc = spec["documents"][limit["doc"]]
    return f"{doc['maker']} {doc['number']} ({doc['revision']}), {limit['where']}"


def _board_net(board: Board, name: str) -> str:
    for candidate in (name, f"/{name}"):
        if candidate in board.nets:
            return candidate
    raise ValueError(f"no net {name!r} on the board")


def _rule_block(name: str, layer: str | None, condition: str, constraint: str) -> str:
    lines = [f'(rule "{name}"']
    if layer:
        lines.append(f'  (layer "{layer}")')
    lines += [f'  (condition "{condition}")', f"  (constraint {constraint}))"]
    return "\n".join(lines)


def pair_runs(board: Board, nets: list[str], layer: str) -> list[tuple[float, float, tuple, tuple]]:
    """Where the pair's 2 tracks on `layer` run side by side: (gap edge to edge, length, first point,
    last point). Each piece of a P track is paired with the nearest parallel N track beside it. An arc
    counts as its 2 chords."""
    return coverage(board, nets[0], nets[1], layer)[0]


def _chords(board: Board, net: str, layer: str) -> list[tuple[tuple, tuple, float]]:
    return [
        (a, b, t.width)
        for t in board.tracks
        if t.net == net and t.layer == layer
        for a, b in zip(t.points, t.points[1:], strict=False)
    ]


def coverage(board: Board, net: str, other: str, layer: str) -> tuple[list, list]:
    """The pieces of `net`'s tracks on `layer` with a parallel track of `other` beside them, as runs
    (gap edge to edge, length, first point, last point), and the stretches with none, as (length, first
    point, last point), 1 for each straight piece. The runs' lengths and the stretches' lengths add up to
    the net's length on the layer (an arc as its 2 chords)."""
    partners = _chords(board, other, layer)
    runs: list[tuple[float, float, tuple, tuple]] = []
    free: list[tuple[float, tuple, tuple]] = []
    for (ax, ay), (bx, by), own in _chords(board, net, layer):
        length = math.hypot(bx - ax, by - ay)
        if length < 1e-9:
            continue
        ux, uy = (bx - ax) / length, (by - ay) / length

        def at(s: float, ax=ax, ay=ay, ux=ux, uy=uy) -> tuple[float, float]:
            return (round(ax + ux * s, 3), round(ay + uy * s, 3))

        near = []
        for (cx, cy), (dx, dy), width in partners:
            span = math.hypot(dx - cx, dy - cy)
            if span < 1e-9 or abs(ux * (dy - cy) - uy * (dx - cx)) / span > PARALLEL:
                continue
            s0 = (cx - ax) * ux + (cy - ay) * uy
            s1 = (dx - ax) * ux + (dy - ay) * uy
            lo, hi = max(0.0, min(s0, s1)), min(length, max(s0, s1))
            if hi - lo > 1e-6:
                apart = abs((cy - ay) * ux - (cx - ax) * uy)
                near.append((lo, hi, apart, apart - (own + width) / 2))
        cuts = sorted({0.0, length} | {c for lo, hi, _, _ in near for c in (lo, hi)})
        for s, e in zip(cuts, cuts[1:], strict=False):
            if e - s < 1e-9:
                continue
            over = [n for n in near if n[0] <= s + 1e-9 and n[1] >= e - 1e-9]
            if not over:
                free.append((e - s, (ax + ux * s, ay + uy * s), (ax + ux * e, ay + uy * e)))
                continue
            gap = round(min(over, key=lambda n: n[2])[3], READ)
            if runs and runs[-1][0] == gap and runs[-1][3] == at(s):
                runs[-1] = (gap, runs[-1][1] + e - s, runs[-1][2], at(e))
            else:
                runs.append((gap, e - s, at(s), at(e)))
    return runs, free


def _gap_of(entry: dict, label: str) -> float | None:
    gap = entry.get("gap")
    if gap is None:
        return None
    if isinstance(gap, bool) or not isinstance(gap, (int, float)) or not gap > 0:
        raise ValueError(f"interfaces.json: {label}: gap must be a number of mm above 0, not {gap!r}")
    return float(gap)


def _check_stack(board: Board, name: str) -> None:
    if not board.stack:
        raise ValueError(f"{name}: the board has no stackup; the solver needs its layers and their er")
    for item in board.stack:
        layer, thick = (item[1], item[2]) if item[0] == "copper" else (item[3], item[1])
        if not thick > 0:
            raise ValueError(
                f"{name}: stackup layer {layer!r} is {thick:g} mm thick; a layer must be above 0"
            )


def check(pcb: Path, interfaces: list[dict], solver) -> Report:
    """Judge the board's fast nets. `solver` takes an xsection request and returns its answer."""
    board = read_board(pcb.read_text(encoding="utf-8"))
    report = Report()
    blocks = [
        "(version 1)",
        "# Written by `workcenter highspeed` from interfaces.json and rules/interfaces/.",
    ]
    if not interfaces:
        raise ValueError("interfaces.json names no interface; there is nothing to judge")
    _check_stack(board, pcb.name)
    for entry in interfaces:
        if not isinstance(entry, dict):
            raise ValueError(f"interfaces.json: {SHAPE}; found {entry!r}")
        spec = load_spec(entry.get("interface", ""))
        names = entry.get("nets")
        if not isinstance(names, list) or len(names) != 2 or not all(isinstance(n, str) for n in names):
            raise ValueError(f"interfaces.json: {spec['interface']}: name the pair's 2 nets, P then N")
        label = f"{spec['interface']} {'/'.join(names)}"
        declared = _gap_of(entry, label)
        nets = [_board_net(board, n) for n in names]
        cond = " || ".join(f"A.NetName == '{n}'" for n in nets)
        unrouted = [n.lstrip("/") for n in nets if not any(t.net == n for t in board.tracks)]
        if unrouted:
            rules = {"impedance": "width", "delay": "length"}
            for name in spec["limits"]:
                report.findings.append(
                    Finding(
                        "not judged",
                        rules.get(name, name),
                        f"{label}: no track of {unrouted[0]} on the board; route the pair, then run again",
                    )
                )
            continue
        _judge_pair(board, spec, label, nets, declared, cond, blocks, report, solver)
    blocks.append(
        "# KiCad applies diff_pair_gap only to nets named as a pair (_P/_N, +/-); highspeed judges it."
    )
    report.rules = "\n".join(blocks) + "\n"
    return report


def _judge_pair(board, spec, label, nets, declared, cond, blocks, report, solver) -> None:
    limits = spec["limits"]
    imp = limits["impedance"]
    layers = sorted({t.layer for t in board.tracks if t.net in nets})
    eps_by_layer: dict[str, float] = {}

    def each_net(rule: str, why: str) -> None:
        for net in nets:
            report.findings.append(Finding("not judged", rule, f"{net.lstrip('/')} on {layer}: {why}"))

    # ---- gap and width, per layer: the solver's band at the gap the board has
    for layer in layers:
        for net, other in (nets, nets[::-1]):
            report.findings += _coupling(board, spec, nets, net, other, layer)
        here = [n for n in nets if any(t.net == n and t.layer == layer for t in board.tracks)]
        runs = pair_runs(board, nets, layer) if len(here) == 2 else []
        if not runs:
            why = (
                f"{({*nets} - {*here}).pop().lstrip('/')} has no track on {layer}"
                if len(here) == 1
                else f"its 2 tracks never run side by side on {layer}"
            )
            for net in here:
                report.findings.append(
                    Finding(
                        "not judged", "width", f"{net.lstrip('/')} on {layer}: {why}; no impedance to judge"
                    )
                )
            continue
        totals: dict[float, float] = {}
        for gap, length, _, _ in runs:
            totals[gap] = totals.get(gap, 0.0) + length
        main = max(totals, key=lambda g: totals[g])

        def stretch(gap: float, layer=layer, totals=totals, runs=runs) -> str:
            first = next(r for r in runs if r[0] == gap)
            more = sum(1 for r in runs if r[0] == gap) - 1
            return (
                f"{label} on {layer}: {totals[gap]:.4g} mm of the pair runs {gap:g} mm apart, edge to "
                f"edge, from {first[2]} to {first[3]} mm" + (f" and {more} more" if more > 0 else "")
            )

        # Every run at a gap other than the declared one fails: the gap is a limit the project set.
        if declared is not None:
            for gap in sorted(totals, key=lambda g: (g != main, g)):
                if abs(declared - gap) > 0.5 * 10**-READ:
                    report.findings.append(
                        Finding(
                            "fail",
                            "gap",
                            f"{stretch(gap)}; limit {declared:g} mm, the gap interfaces.json gives and the "
                            "KiCad rule is written for",
                        )
                    )
                else:
                    report.findings.append(
                        Finding(
                            "held",
                            "gap",
                            f"{label} on {layer}: the 2 tracks run {gap:g} mm apart over "
                            f"{totals[gap]:.4g} mm, the gap interfaces.json gives",
                        )
                    )
        others = [] if declared is not None else [g for g in sorted(totals) if g != main]

        def others_not_judged(why: str, others=others, stretch=stretch) -> None:
            for gap in others:
                report.findings.append(Finding("not judged", "gap", f"{stretch(gap)}; {why}"))

        if main <= 0:
            each_net("width", f"the 2 tracks touch or overlap ({main:g} mm apart)")
            others_not_judged(f"the pair's main run touches or overlaps ({main:g} mm apart)")
            continue
        try:
            section, refs = section_for(board, layer)
        except NotJudged as exc:
            each_net("width", str(exc))
            others_not_judged(str(exc))
            continue
        if section is None:
            each_net("width", "no ground pour on any copper layer to stand as its plane")
            others_not_judged("no ground pour on any copper layer to stand as its plane")
            continue
        beside = _ground_beside(board, nets, layer, COPLANAR * section["y"])
        if beside is not None:
            fill_net, apart, (x, y) = beside
            why = (
                f"{fill_net.lstrip('/')} is poured on {layer} itself, {apart:.3g} mm from the track's edge "
                f"at ({x:g}, {y:g}) mm, within {COPLANAR:g} times its {section['y']:g} mm height over its "
                "plane; the solver puts no ground beside the track, and such ground lowers the impedance"
            )
            each_net("width", why)
            others_not_judged(why)
            continue
        section.update({"widths": [0.3, 0.3], "gap": main})
        band = "min" in imp and "max" in imp
        req = {"section": section, "target": imp["nominal"]}
        if band:
            req.update({"low": imp["min"], "high": imp["max"]})
        ans = solver(req)
        if "error" in ans:
            each_net("width", ans["error"])
            others_not_judged(ans["error"])
            continue
        eps_by_layer[layer] = ans["line"]["eps_eff"]
        report.bands[layer] = {**ans, "refs": refs, "gap": main}
        src = cite(spec, imp)
        opt_gap = declared if declared is not None else main
        blocks.append(f"# {label} on {layer}: {imp['nominal']} ohm {imp['mode']}; {src}")
        if not band:
            blocks.append(
                _rule_block(f"{label} width {layer}", layer, cond, f"track_width (opt {ans['width']:.4f}mm)")
            )
            report.findings.append(
                Finding("not judged", "width", f"{label} on {layer}: {imp['band_not_stated']}")
            )
            others_not_judged(imp["band_not_stated"])
            continue
        wmin, wmax = round(ans["width_min"], 4), round(ans["width_max"], 4)
        blocks.append(
            _rule_block(
                f"{label} width {layer}",
                layer,
                cond,
                f"track_width (min {wmin:.4f}mm) (opt {ans['width']:.4f}mm) (max {wmax:.4f}mm)",
            )
        )
        gmin, gmax = ans.get("gap_min"), ans.get("gap_max")
        if ans.get("gap_error"):
            blocks.append(f"# {label} gap {layer}: {ans['gap_error']}; that bound is left out")
        bounds = [f"(min {gmin:.4f}mm)"] if gmin else []
        bounds += [f"(opt {opt_gap:.4f}mm)"] + ([f"(max {gmax:.4f}mm)"] if gmax else [])
        if gmin or gmax:
            blocks.append(
                _rule_block(f"{label} gap {layer}", layer, cond, f"diff_pair_gap {' '.join(bounds)}")
            )
        for net in nets:
            widths = [t.width for t in board.tracks if t.net == net and t.layer == layer]
            worst = min(widths) if min(widths) < wmin else max(widths)
            where = f"{net.lstrip('/')} on {layer}"
            if wmin <= worst <= wmax:
                text = f"{where}: {worst:g} mm in {wmin:g} to {wmax:g} mm at the board's {main:g} mm gap"
                report.findings.append(Finding("held", "width", text))
            else:
                report.findings.append(
                    Finding(
                        "fail",
                        "width",
                        f"{where} is {worst:g} mm wide; limit {wmin:g} to {wmax:g} mm, the widths the "
                        f"solver gives for {imp['min']:g} to {imp['max']:g} ohm {imp['mode']} at the board's "
                        f"{main:g} mm gap over {', '.join(refs)}; source: {src}",
                    )
                )
        # The runs at the other gaps: the impedance of the tracks there, at their own widths.
        widths = [
            sorted({t.width for t in board.tracks if t.net == net and t.layer == layer}) for net in nets
        ]
        for gap in others:
            if gap <= 0:
                report.findings.append(
                    Finding("fail", "gap", f"{stretch(gap)}: the 2 tracks touch or overlap; source: {src}")
                )
                continue
            # The narrowest tracks give the highest impedance, the widest the lowest.
            picks = sorted({tuple(w[0] for w in widths), tuple(w[-1] for w in widths)})
            zs = []
            for pick in picks:
                got = solver(
                    {"section": {**section, "widths": list(pick), "gap": gap}, "impedance_only": True}
                )
                if "error" in got:
                    break
                zs.append(got["impedance"])
            if len(zs) < len(picks):
                report.findings.append(Finding("not judged", "gap", f"{stretch(gap)}; {got['error']}"))
                continue
            low, high = min(zs), max(zs)
            shown = f"{low:.1f} ohm" if high - low < 0.05 else f"{low:.1f} to {high:.1f} ohm"
            ok = imp["min"] <= low and high <= imp["max"]
            report.findings.append(
                Finding(
                    "held" if ok else "fail",
                    "gap",
                    f"{stretch(gap)}: Z_diff {shown} there at its tracks' widths; limit {imp['min']:g} to "
                    f"{imp['max']:g} ohm {imp['mode']}; source: {src}",
                )
            )

    # ---- spacing to other signals, per layer
    for net in nets:
        for layer in sorted({t.layer for t in board.tracks if t.net == net}):
            report.findings += _spacing(board, spec, nets, net, layer)

    # ---- a route that does not reach every pad of its net is not judged as if it were finished
    unjoined = {n: _unjoined(board, n) for n in nets}

    def unfinished(net: str) -> str | None:
        pads = unjoined[net]
        if not pads:
            return None
        names = ", ".join(f"{p.name} at ({p.x:g}, {p.y:g}) mm" for p in pads)
        return f"{net.lstrip('/')}: its tracks do not reach {names}; the route is not finished"

    # ---- length, or delay
    lengths = {n: net_length(board, n) for n in nets}
    vias = sum(board.vias.get(n, 0) for n in nets)
    tail = f" ({vias} via barrels not counted)" if vias else ""
    if "max" in limits.get("length", {}):
        lim = limits["length"]
        blocks.append(f"# {label} length: {cite(spec, lim)}")
        blocks.append(_rule_block(f"{label} length", None, cond, f"length (max {lim['max']:.4f}mm)"))
        for net, value in lengths.items():
            if unfinished(net):
                report.findings.append(Finding("not judged", "length", unfinished(net)))
                continue
            text = f"{net.lstrip('/')} is {value:.4f} mm long{tail}; limit {lim['max']:g} mm; "
            text += f"source: {cite(spec, lim)}"
            report.findings.append(Finding("fail" if value > lim["max"] else "held", "length", text))
    elif "max" in limits.get("delay", {}):
        lim = limits["delay"]
        for net in nets:
            if unfinished(net):
                report.findings.append(Finding("not judged", "length", unfinished(net)))
                continue
            delays = [
                t.length() * math.sqrt(eps_by_layer[t.layer]) / C0 * 1e6
                for t in board.tracks
                if t.net == net and t.layer in eps_by_layer
            ]
            if len(delays) < sum(1 for t in board.tracks if t.net == net):
                report.findings.append(
                    Finding("not judged", "length", f"{net.lstrip('/')}: a layer had no solution")
                )
                continue
            value = sum(delays)
            text = f"{net.lstrip('/')} delays {value:.4f} ns{tail}; limit {lim['max']:g} ns; "
            text += f"source: {cite(spec, lim)}"
            report.findings.append(Finding("fail" if value > lim["max"] else "held", "length", text))
    else:
        why = limits.get("length", {}).get("not_stated", "the interface file sets no length")
        report.findings.append(Finding("not judged", "length", f"{label}: {why}"))

    # ---- skew
    lim = limits.get("skew", {})
    open_nets = [unfinished(n) for n in nets if unfinished(n)]
    if "max" in lim and open_nets:
        blocks.append(f"# {label} skew: {cite(spec, lim)}")
        blocks.append(_rule_block(f"{label} skew", None, cond, f"skew (max {lim['max']:.4f}mm)"))
        report.findings.append(Finding("not judged", "skew", f"{label}: {'; '.join(open_nets)}"))
    elif "max" in lim:
        blocks.append(f"# {label} skew: {cite(spec, lim)}")
        blocks.append(_rule_block(f"{label} skew", None, cond, f"skew (max {lim['max']:.4f}mm)"))
        value = abs(lengths[nets[0]] - lengths[nets[1]])
        text = f"{label}: the 2 tracks differ by {value:.4g} mm{tail}; limit {lim['max']:g} mm; "
        text += f"source: {cite(spec, lim)}"
        report.findings.append(Finding("fail" if value > lim["max"] + 1e-9 else "held", "skew", text))
    else:
        report.findings.append(
            Finding("not judged", "skew", f"{label}: {lim.get('not_stated', 'no skew set')}")
        )

    # ---- vias, where the document counts them
    lim = limits.get("vias", {})
    if "max" in lim:
        for net in nets:
            count = board.vias.get(net, 0)
            text = f"{net.lstrip('/')} has {count} vias; limit {lim['max']:g}; source: {cite(spec, lim)}"
            report.findings.append(Finding("fail" if count > lim["max"] else "held", "vias", text))

    # ---- a via that changes the ground planes, and its ground via
    report.findings += _stitching(board, spec, nets)

    # ---- what the documents set and the command does not judge
    for name, lim in limits.items():
        if "not_judged" in lim:
            report.findings.append(
                Finding("not judged", name, f"{label}: {lim['not_judged']}; source: {cite(spec, lim)}")
            )

    # ---- plane
    lim = limits.get("plane", {})
    if "doc" not in lim:
        report.findings.append(
            Finding("not judged", "plane", f"{label}: {lim.get('not_stated', 'no plane set')}")
        )
        return
    for net in nets:
        if unfinished(net):
            report.findings.append(Finding("not judged", "plane", unfinished(net)))
            continue
        for layer in sorted({t.layer for t in board.tracks if t.net == net}):
            report.findings += _plane(board, spec, lim, net, layer)


def _ground_beside(board: Board, nets: list[str], layer: str, reach: float):
    """The nearest ground fill on the pair's own layer within `reach` of a track's edge: (its net, the
    distance edge to fill, the track's point nearest it), or None."""
    best = None
    for net, poly in zip(board.fill_nets.get(layer, []), board.fills.get(layer, []), strict=True):
        edges = list(zip(poly, poly[1:] + poly[:1], strict=True))
        for a, b, width in (c for n in nets for c in _chords(board, n, layer)):
            for c, d in edges:
                apart = _between(a, b, c, d) - width / 2
                if apart <= reach and (best is None or apart < best[1]):
                    near = min((a, b), key=lambda p, c=c, d=d: _to_segment(p, c, d))
                    best = (net, max(apart, 0.0), (round(near[0], 3), round(near[1], 3)))
    return best


def _coupling(board: Board, spec: dict, nets: list[str], net: str, other: str, layer: str) -> list[Finding]:
    """The stretches of `net` on `layer` with no parallel track of `other` beside them: held when each
    lies within the interface's break-out distance of the pair's pads, else not judged (the solver
    gives no impedance to an uncoupled stretch of a pair)."""
    if not any(t.net == net and t.layer == layer for t in board.tracks):
        return []
    runs, free = coverage(board, net, other, layer)
    loose = sum(f[0] for f in free)
    if loose < 1e-6:
        return []
    total = loose + sum(r[1] for r in runs)
    lim = spec["limits"].get("coupling", {})
    reach = lim.get("break_out")
    pads = [(p.x, p.y) for p in board.pads if p.net in nets and p.on(layer)]

    def broken_out(piece) -> bool:
        if reach is None or not pads:
            return False
        length, (ax, ay), (bx, by) = piece
        n = max(1, math.ceil(length / BREAK_SAMPLE))
        points = [(ax + (bx - ax) * i / n, ay + (by - ay) * i / n) for i in range(n + 1)]
        return all(min(math.hypot(x - px, y - py) for px, py in pads) <= reach for x, y in points)

    away = [f for f in free if not broken_out(f)]
    where = f"{net.lstrip('/')} on {layer}"
    partner = other.lstrip("/")
    head = f"{where}: {loose:.4g} mm of its {total:.4g} mm has no parallel track of {partner} beside it"
    if not away:
        return [
            Finding(
                "held",
                "coupling",
                f"{head}, all within {reach:g} mm of the pair's pads: break-out; limit: break-out within "
                f"{reach:g} mm of the package; source: {cite(spec, lim)}",
            )
        ]
    # The first stretch away from the pads, run on through the pieces that join it.
    (_, start, end), joined = away[0], 1
    for piece in away[1:]:
        if math.hypot(piece[1][0] - end[0], piece[1][1] - end[1]) > 1e-6:
            break
        end, joined = piece[2], joined + 1
    more = len(away) - joined
    spot = f"from ({start[0]:.6g}, {start[1]:.6g}) to ({end[0]:.6g}, {end[1]:.6g}) mm"
    text = head + (
        f"; {sum(f[0] for f in away):.4g} mm of that lies more than {reach:g} mm from the pair's pads"
        if reach is not None
        else ""
    )
    text += f", {spot}" + (f" and {more} more" if more > 0 else "")
    text += "; the impedance of a track with no partner is not judged"
    return [Finding("not judged", "coupling", text)]


def _unjoined(board: Board, net: str) -> list[Pad]:
    """The pads of `net` its tracks do not join to the rest: tracks join where an end lies on another
    track of the layer, on a via, or within a pad on that layer (half the pad's diagonal)."""
    pads = [p for p in board.pads if p.net == net]
    tracks = [t for t in board.tracks if t.net == net]
    vias = [v for v in board.via_at if v[0] == net]
    if not pads or not tracks:
        return []
    items = len(tracks) + len(vias) + len(pads)
    root = list(range(items))

    def find(i: int) -> int:
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i

    def join(i: int, j: int) -> None:
        root[find(i)] = find(j)

    for i, t in enumerate(tracks):
        ends = (t.points[0], t.points[-1])
        for j, u in enumerate(tracks[:i]):
            if u.layer == t.layer:
                reach = max(t.width, u.width) / 2
                chords = list(zip(u.points, u.points[1:], strict=False))
                if any(_to_segment(e, a, b) <= reach for e in ends for a, b in chords) or any(
                    _to_segment(e, a, b) <= reach
                    for e in (u.points[0], u.points[-1])
                    for a, b in zip(t.points, t.points[1:], strict=False)
                ):
                    join(i, j)
        for k, (_, x, y, r) in enumerate(vias):
            if any(math.hypot(e[0] - x, e[1] - y) <= r for e in ends):
                join(i, len(tracks) + k)
        for k, p in enumerate(pads):
            if p.on(t.layer) and any(math.hypot(e[0] - p.x, e[1] - p.y) <= p.reach for e in ends):
                join(i, len(tracks) + len(vias) + k)
    for k, (_, x, y, _r) in enumerate(vias):
        for m, p in enumerate(pads):
            if math.hypot(x - p.x, y - p.y) <= p.reach:
                join(len(tracks) + k, len(tracks) + len(vias) + m)
    groups: dict[int, int] = {}
    for i in range(len(tracks)):
        groups[find(i)] = groups.get(find(i), 0) + 1
    routed = max(groups, key=lambda g: groups[g])
    return [p for m, p in enumerate(pads) if find(len(tracks) + len(vias) + m) != routed]


def _stitching(board: Board, spec: dict, nets: list[str]) -> list[Finding]:
    """A via of the pair whose tracks change their ground planes needs a ground via (or through pad)
    within the interface's distance of it."""
    lim = spec["limits"].get("stitching", {})
    if "max" not in lim:
        return []
    grounds = [(x, y) for n, x, y, _ in board.holes if is_ground(n)]
    out = []
    for net, x, y, r in board.via_at:
        if net not in nets:
            continue
        layers = sorted(
            {
                t.layer
                for t in board.tracks
                if t.net == net
                and any(math.hypot(e[0] - x, e[1] - y) <= r for e in (t.points[0], t.points[-1]))
            }
        )
        refs = {layer: plane_refs(board, layer) for layer in layers}
        if len({tuple(v) for v in refs.values()}) < 2:
            continue
        change = " to ".join(f"{layer} over {', '.join(v) or 'no plane'}" for layer, v in refs.items())
        where = f"{net.lstrip('/')}'s via at ({x:g}, {y:g}) mm, {change}"
        near = min((math.hypot(gx - x, gy - y) for gx, gy in grounds), default=None)
        src = cite(spec, lim)
        if near is not None and near <= lim["max"] + 1e-9:
            text = f"{where}: a ground via {near:.3g} mm from it; limit {lim['max']:g} mm; source: {src}"
            out.append(Finding("held", "stitching", text))
        else:
            got = f"the nearest ground via is {near:.3g} mm from it" if near is not None else "no ground via"
            out.append(
                Finding(
                    "fail",
                    "stitching",
                    f"{where}: {got}; limit: a ground via within {lim['max']:g} mm, center to center; "
                    f"source: {cite(spec, lim)}",
                )
            )
    return out


def _spacing(board: Board, spec: dict, nets: list[str], net: str, layer: str) -> list[Finding]:
    """The nearest track of another signal on the same layer, edge to edge (ground nets are no signal)."""
    lim = spec["limits"].get("spacing", {})
    if "min" not in lim:
        return []
    where = f"{net.lstrip('/')} on {layer}"
    best = None
    own = _chords(board, net, layer)
    for t in board.tracks:
        if t.layer != layer or t.net in nets or is_ground(t.net):
            continue
        for c, d in zip(t.points, t.points[1:], strict=False):
            for a, b, width in own:
                apart = _between(a, b, c, d) - (width + t.width) / 2
                if best is None or apart < best[0]:
                    best = (apart, t.net)
    src = cite(spec, lim)
    if best is None:
        text = f"{where}: no track of another signal on {layer}; limit {lim['min']:g} mm; source: {src}"
        return [Finding("held", "spacing", text)]
    apart, other = best
    text = (
        f"{where}: the nearest track of another signal, {other.lstrip('/')}, is {apart:.3g} mm from it, "
        f"edge to edge; limit {lim['min']:g} mm; source: {src}"
    )
    return [Finding("fail" if apart < lim["min"] - 1e-9 else "held", "spacing", text)]


def _plane(board: Board, spec: dict, lim: dict, net: str, layer: str) -> list[Finding]:
    where = f"{net.lstrip('/')} on {layer}"
    if _index(board, layer) is None:
        return [Finding("not judged", "plane", f"{where}: {layer} is not a copper layer of the stackup")]
    out: list[Finding] = []
    for step, side in ((+1, "below"), (-1, "above")):
        i = _nearest(board, layer, step, set(board.pours))
        if i is None:
            continue
        name = board.stack[i][1]
        if not any(is_ground(n) for n in board.pours[name]):
            others = ", ".join(sorted(n.lstrip("/") for n in board.pours[name]))
            out.append(
                Finding(
                    "fail",
                    "plane",
                    f"{where}: the nearest pour {side} it, on {name}, is of {others}, not a ground; limit: a "
                    f"ground reference plane; source: {cite(spec, lim)}",
                )
            )
    refs = plane_refs(board, layer)
    if not refs:
        return out + [Finding("not judged", "plane", f"{where}: no ground pour on any copper layer")]
    for ref in refs:
        polys = board.fills.get(ref)
        if not polys:
            out.append(Finding("not judged", "plane", f"{where}: the ground pours on {ref} are not filled"))
            continue
        gaps = _gaps(board, net, layer, ref, polys)
        if not gaps:
            out.append(Finding("held", "plane", f"{where}: over {ref} along its whole length"))
            continue
        (x1, y1), (x2, y2), run = gaps[0]
        more = f", and {len(gaps) - 1} more" if len(gaps) > 1 else ""
        out.append(
            Finding(
                "fail",
                "plane",
                f"{where} crosses a gap in the plane on {ref} from ({x1:g}, {y1:g}) to ({x2:g}, {y2:g}) mm: "
                f"{run:.2f} mm with no copper under it{more}; limit: a solid plane; "
                f"source: {cite(spec, lim)}",
            )
        )
    return out


def _antipads(board: Board, net: str, ref: str, polys: list) -> list[tuple[float, float, float]]:
    """The holes the plane on `ref` keeps round the through pads and vias of `net`: (x, y, radius). The
    radius is half the pad's diagonal, the pour's clearance and its least thickness. A hole counts only
    where fill closes round it: on each of RAYS directions the point STEP past the radius is in the fill,
    or within the hole of another pad or via. A via in a split has no fill round it and excuses nothing."""
    margin = board.margins.get(ref, 0.0)
    out = []
    for n, x, y, r in board.holes:
        if n != net:
            continue
        reach = r + margin
        closed = True
        for k in range(RAYS):
            a = 2 * math.pi * k / RAYS
            pt = (x + (reach + STEP) * math.cos(a), y + (reach + STEP) * math.sin(a))
            others = (h for h in board.holes if (h[1], h[2]) != (x, y))
            if any(math.hypot(pt[0] - hx, pt[1] - hy) <= hr + margin for _, hx, hy, hr in others):
                continue
            if not any(_inside(pt, p) for p in polys):
                closed = False
                break
        if closed:
            out.append((x, y, reach))
    return out


def _gaps(board: Board, net: str, layer: str, ref: str, polys: list) -> list:
    """Runs of a net's centre line on a layer with no fill of `ref` under them: (first point, last
    point, length). A point within the hole the plane keeps round a through pad or a via of the same
    net (`_antipads`) is no gap: the track enters that pad there."""
    own = _antipads(board, net, ref, polys)
    runs = []
    for track in (t for t in board.tracks if t.net == net and t.layer == layer):
        current: list = []
        for pt in track.samples():
            near = any(math.hypot(pt[0] - x, pt[1] - y) <= r for x, y, r in own)
            if near or any(_inside(pt, p) for p in polys):
                if current:
                    runs.append(current)
                    current = []
            else:
                current.append(pt)
        if current:
            runs.append(current)
    out = []
    for run in runs:
        (x1, y1), (x2, y2) = run[0], run[-1]
        out.append(((round(x1, 2), round(y1, 3)), (round(x2, 2), round(y2, 3)), math.hypot(x2 - x1, y2 - y1)))
    return out


def cmd_highspeed(args, cli) -> int:
    project = cli.find_project(args.project)
    if not project.pcb:
        print(f"SKIPPED highspeed: no board in {project.dir}")
        return cli.EXIT_SKIP
    script = Path(__file__).resolve().parent / "xsection.py"

    def solver(req: dict) -> dict:
        proc = cli.run([cli.venv_python(), "-s", str(script), json.dumps(req)], timeout=900)
        if proc.returncode != 0:
            last = (proc.stderr.strip().splitlines() or ["no output"])[-1]
            return {"error": f"the solver under {cli.venv_python()} ended with {proc.returncode}: {last}"}
        return json.loads(proc.stdout)

    try:
        interfaces = read_interfaces(project.dir)
        report = check(project.pcb, interfaces, solver)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL highspeed: {exc}")
        return cli.EXIT_FAIL
    folder = cli.out_dir_for(project, args.out) / "highspeed"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "highspeed.kicad_dru").write_text(report.rules, encoding="utf-8")
    record = {"findings": [f.__dict__ for f in report.findings], "bands": report.bands}
    (folder / "report.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    for f in report.findings:
        word = {"fail": "FAIL", "held": "held", "not judged": "NOT JUDGED"}[f.status]
        if f.status != "held" or args.verbose:
            print(f"{word} highspeed.{f.rule}: {f.text}")
    for layer, band in report.bands.items():
        print(
            f"rules {layer}: width {band['width']:.4f} mm"
            + (f" ({band['width_min']:.4f} to {band['width_max']:.4f})" if band.get("width_min") else "")
            + f" at the board's {band['gap']:g} mm gap, eps_eff {band['line']['eps_eff']:.3f}, over "
            + ", ".join(band["refs"])
        )
    print(f"wrote {folder / 'highspeed.kicad_dru'}")
    fails, unjudged = len(report.fails()), len(report.not_judged())
    held = sum(1 for f in report.findings if f.status == "held")
    if fails or (args.strict and unjudged):
        print(f"HIGHSPEED FAIL: {fails} failed, {unjudged} not judged, {held} held")
        return cli.EXIT_FAIL
    print(f"HIGHSPEED HELD: {held} held, {unjudged} not judged")
    return cli.EXIT_PASS


def register(sub, cli) -> None:
    """Add `highspeed` to the workcenter's parser; it sets `run` to its handler."""
    p = sub.add_parser(
        "highspeed",
        help="hold the fast nets that interfaces.json names to their interface's rules: width from the "
        "cross-section solver at the board's own gap, the gap, length, skew, vias and the ground plane; "
        "writes <out>/highspeed/highspeed.kicad_dru for KiCad's DRC",
    )
    p.add_argument("project", help="project directory or a .kicad_pro/.kicad_pcb file")
    p.add_argument("--out", help="output directory (default <project>/build)")
    p.add_argument("--strict", action="store_true", help="what is not judged fails the run")
    p.add_argument("--verbose", action="store_true", help="print the rules that held too")
    p.set_defaults(run=lambda a: cmd_highspeed(a, cli))
