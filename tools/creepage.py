#!/usr/bin/env python3
"""creepage — the gap between 2 nets' copper held to their working voltage, through air and along the
board's face.

A creepage pack (`rules/board/<pack>.json`, `"kind": "creepage"`) holds a document's tables of
clearance (through air) and creepage (along a surface) by voltage, under conditions the project states
in `board-rules.json` under `creepage`. The voltage between 2 nets is the most their spans in
`ratings.json` allow. The copper of each outer layer is read as polygons drawn round it, so a gap is
never read larger than it is. A slot (an inner cut of Edge.Cuts with 4 corners) between 2 nets
lengthens the way along the face: the way goes round its corners. Copper with no net shortens it: the
way crosses it. Between the 2 faces the way round the board's edge or through a hole is not measured;
a pair is held only by the least length that way can have. Standard library only.
"""

from __future__ import annotations

import heapq
import itertools
import math
from dataclasses import dataclass, field
from pathlib import Path

import boardrules
import kicadgen
import ratings
from boardrules import Finding
from ratings import Refusal

EPS = 1e-9
ROUND = 16  # sides of the polygon drawn round a circle: its corners stand at r / cos(pi / 16)
Point = tuple[float, float]
Polygon = list[Point]


# ---------------------------------------------------------------- the pack


@dataclass
class Limit:
    at_least: float | None  # a gap at or over it holds
    fails_under: float | None  # a gap under it fails
    where: str = ""
    why: str = ""  # with no limit, or between rows: the reason
    rows: tuple = ()  # between rows: ((volts, mm), (volts, mm))


@dataclass
class Pack:
    name: str
    document: dict
    conditions: dict[str, dict]
    voltage: str
    between_rows: str  # range or points
    tables: dict[str, dict]
    slot: dict | None
    not_judged: list[str]
    text: dict | None = None  # the SHA256 of the pages' text, for a document each download stamps

    @property
    def most(self) -> float:
        """The greatest distance in the pack's tables, mm."""
        return max(v for spec in self.tables.values() for row in spec["rows"] for v in row["mm"].values())

    def cite(self, where: str) -> str:
        return f"{self.document['number']}: {where}"

    def conditions_of(self, stated: dict) -> dict[str, str]:
        """The conditions a project states under `creepage`, each one of the pack's values."""
        at = f"{boardrules.PROJECT_FILE}: creepage"
        if not isinstance(stated, dict):
            raise Refusal(f"{at}: an object of `pack` and the pack's conditions is asked")
        for key in self.conditions:
            if key not in stated:
                raise Refusal(f"{at}: `{key}` is missing; the pack {self.name} asks it")
        data = ratings._keys(at, stated, ("pack", *self.conditions))
        out = {}
        for key, spec in self.conditions.items():
            value = str(data[key]) if isinstance(data[key], (str, int)) else None
            if value not in spec["values"]:
                raise Refusal(f"{at}: {key}: `{data[key]}` is none of {', '.join(spec['values'])}")
            out[key] = value
        return out

    def least_slot(self, cond: dict[str, str]) -> float | None:
        if not self.slot:
            return None
        return self.slot["least_mm"].get(cond[self.slot["key"]])

    def limit(self, table: str, volts: float, cond: dict[str, str]) -> Limit:
        """The least gap a table asks at `volts` under `cond`."""
        spec = self.tables[table]
        key = " ".join(cond[k] for k in spec["keys"])
        rows = spec["rows"]
        where = spec["where"]
        if self.between_rows == "range":
            last = rows[-1]["volts"][1]
            if volts > last + EPS:
                return Limit(None, None, where, f"{volts:g} V is over {last:g} V, the table's last row")
            held = [r["mm"][key] for r in rows if r["volts"][0] - EPS <= volts <= r["volts"][1] + EPS]
            mm = max(held)
            return Limit(mm, mm, where)
        points = [(r["volts"], r["mm"][key]) for r in rows]
        if volts > points[-1][0] + EPS:
            return Limit(None, None, where, f"{volts:g} V is over {points[-1][0]:g} V, the table's last row")
        for (v0, m0), (v1, m1) in itertools.pairwise([(None, None), *points]):
            if abs(volts - v1) <= EPS:
                return Limit(m1, m1, where)
            if volts < v1:
                if v0 is None:
                    why = f"under {v1:g} V, the table's first row"
                    return Limit(m1, None, where, why, ((v1, m1),))
                return Limit(m1, m0, where, "", ((v0, m0), (v1, m1)))
        raise AssertionError("unreachable")


def _table(name: str, label: str, spec: object, conditions: dict, between: str) -> dict:
    at = f"{name}: {label}"
    spec = ratings._keys(at, spec, ("keys", "where", "rows"))
    keys = ratings._names(f"{at}: keys", spec["keys"])
    for k in keys:
        if k not in conditions:
            raise Refusal(f"{at}: keys: `{k}` is no condition of the pack")
    boardrules._where(at, spec["where"])
    combos = [" ".join(c) for c in itertools.product(*(conditions[k]["values"] for k in keys))]
    rows = spec["rows"]
    if not isinstance(rows, list) or not rows:
        raise Refusal(f"{at}: rows: a list of rows is asked")
    last_v: float | None = None
    last_mm: dict[str, float] = {}
    for i, row in enumerate(rows, start=1):
        rat = f"{at} rows {i}"
        row = ratings._keys(rat, row, ("volts", "mm"))
        if between == "range":
            v = row["volts"]
            if not (isinstance(v, list) and len(v) == 2):
                raise Refusal(f"{rat}: volts: a range [from, to] is asked")
            lo = ratings._number(f"{rat}: volts", v[0], 0, None, None)
            hi = ratings._number(f"{rat}: volts", v[1], None, None, lo)
            if last_v is None and abs(lo) > EPS:
                raise Refusal(f"{rat}: volts: a table of ranges starts at 0 V, not {lo:g} V")
            if last_v is not None and abs(lo - last_v) > EPS:
                raise Refusal(
                    f"{rat}: volts: the row starts at {lo:g} V, and the row before ends at {last_v:g} V"
                )
            last_v = hi
        else:
            v = ratings._number(
                f"{rat}: volts", row["volts"], None, None, last_v if last_v is not None else 0
            )
            last_v = v
        mm = row["mm"]
        if not isinstance(mm, dict) or sorted(mm) != sorted(combos):
            raise Refusal(f"{rat}: mm: an object of {', '.join(combos)} is asked")
        for combo in combos:
            value = ratings._number(f"{rat}: mm: {combo}", mm[combo], None, None, 0)
            if combo in last_mm and value < last_mm[combo] - EPS:
                raise Refusal(
                    f"{rat}: {combo}: {value:g} mm is under {last_mm[combo]:g} mm of the row before"
                )
            last_mm[combo] = value
    return spec


def read_pack(path: Path) -> Pack:
    """A creepage pack: its document with URL and SHA256, the conditions a project states, and its tables
    by voltage, each with the place in the document."""
    name = path.name
    data = ratings._keys(
        name,
        ratings._json(path),
        ("pack", "kind", "document", "conditions", "voltage", "between_rows", "creepage", "not_judged"),
        ("clearance", "slot", "scope", "reprints", "text"),
    )
    if data["kind"] != "creepage":
        raise Refusal(f"{name}: kind: `creepage` is asked")
    document = ratings._keys(f"{name}: document", data["document"], ratings.DOCUMENT_KEYS)
    for key in ratings.DOCUMENT_KEYS:
        ratings._text(f"{name}: document: {key}", document[key])
    ratings._source(f"{name}: document", document)
    text = data.get("text")
    if text is not None:
        text = ratings._keys(f"{name}: text", text, ("pages", "how", "sha256"))
        for key in ("pages", "how"):
            ratings._text(f"{name}: text: {key}", text[key])
        if not ratings.SHA256_RE.fullmatch(str(text["sha256"])):
            raise Refusal(f"{name}: text: sha256: 64 hex digits are asked")
    conditions = data["conditions"]
    if not isinstance(conditions, dict) or not conditions:
        raise Refusal(f"{name}: conditions: an object of conditions is asked")
    for key, spec in conditions.items():
        spec = ratings._keys(f"{name}: conditions: {key}", spec, ("values", "where"))
        ratings._names(f"{name}: conditions: {key}: values", spec["values"])
        for value in spec["values"]:
            if any(ch.isspace() for ch in str(value)):
                raise Refusal(f"{name}: conditions: {key}: values: `{value}` holds a space")
        boardrules._where(f"{name}: conditions: {key}", spec["where"])
    boardrules._where(f"{name}: voltage", data["voltage"])
    if data["between_rows"] not in ("range", "points"):
        raise Refusal(f"{name}: between_rows: `range` or `points` is asked")
    tables = {
        t: _table(name, t, data[t], conditions, data["between_rows"])
        for t in ("creepage", "clearance")
        if t in data
    }
    slot = data.get("slot")
    if slot is not None:
        slot = ratings._keys(f"{name}: slot", slot, ("key", "least_mm", "where"))
        if slot["key"] not in conditions:
            raise Refusal(f"{name}: slot: key: `{slot['key']}` is no condition of the pack")
        if not isinstance(slot["least_mm"], dict) or not slot["least_mm"]:
            raise Refusal(
                f"{name}: slot: least_mm: an object of each value of {slot['key']} and its mm is asked"
            )
        for k, v in slot["least_mm"].items():
            ratings._number(f"{name}: slot: least_mm: {k}", v, None, None, 0)
        boardrules._where(f"{name}: slot", slot["where"])
    if not isinstance(data["not_judged"], list):
        raise Refusal(f"{name}: not_judged: a list of places is asked")
    for i, place in enumerate(data["not_judged"], start=1):
        boardrules._where(f"{name}: not_judged {i}", place)
    if "clearance" not in tables and not data["not_judged"]:
        raise Refusal(
            f"{name}: not_judged: a pack with no clearance table names in its first line why the document "
            "gives none"
        )
    return Pack(
        ratings._text(f"{name}: pack", data["pack"]),
        document,
        conditions,
        data["voltage"],
        data["between_rows"],
        tables,
        slot,
        data["not_judged"],
        text,
    )


def is_creepage(path: Path) -> bool:
    data = ratings._json(path)
    return isinstance(data, dict) and data.get("kind") == "creepage"


# ---------------------------------------------------------------- the copper


@dataclass
class Cut:
    polygon: Polygon | None  # a convex cut of 4 corners, or None: a cut this module does not measure
    what: str  # for None: what it is and where


@dataclass
class Copper:
    layers: list[str]
    shapes: dict[str, list[tuple[str, Polygon]]]  # layer -> (net, polygon round its copper)
    cuts: list[Cut] = field(default_factory=list)
    thickness: float = 0.0  # the board's, mm; 0, for copper a test draws, is less than any board's
    walls: list[Polygon] = field(default_factory=list)  # each side of the outline and of each hole: 2 points
    walls_slack: float = 0.0  # how much nearer an arc or a circle of Edge.Cuts stands than its chords
    walls_unread: str = ""  # a shape of Edge.Cuts this module does not read, and where
    floating: dict[str, list[tuple[str, Polygon]]] = field(default_factory=dict)  # layer -> copper, no net
    unread: dict[str, list[str]] = field(default_factory=dict)  # layer -> copper shapes not read
    _by: dict = field(default_factory=dict, repr=False, compare=False)

    def polys(self, layer: str, net: str) -> list[Polygon]:
        """The polygons of a net on a layer."""
        if layer not in self._by:
            by: dict[str, list[Polygon]] = {}
            for n, p in self.shapes.get(layer, []):
                by.setdefault(n, []).append(p)
            self._by[layer] = by
        return self._by[layer].get(net, [])


def circle(c: Point, r: float) -> Polygon:
    """A polygon round a circle: its sides touch the circle, so it holds all of it."""
    big = r / math.cos(math.pi / ROUND)
    return [
        (c[0] + big * math.cos(2 * math.pi * k / ROUND), c[1] + big * math.sin(2 * math.pi * k / ROUND))
        for k in range(ROUND)
    ]


def _hull(points: list[Point]) -> Polygon:
    pts = sorted(set(points))
    if len(pts) <= 2:
        return pts

    def cross(o: Point, a: Point, b: Point) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Point] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper: list[Point] = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def capsule(a: Point, b: Point, width: float) -> Polygon:
    """A track of `width` from a to b with round ends, drawn round its copper."""
    return _hull(circle(a, width / 2) + circle(b, width / 2))


def _circle_of(s: Point, m: Point, e: Point) -> tuple[Point, float] | None:
    """The centre and radius of the circle through 3 points; None when they stand on a line."""
    d = 2 * (s[0] * (m[1] - e[1]) + m[0] * (e[1] - s[1]) + e[0] * (s[1] - m[1]))
    if abs(d) < EPS:
        return None
    sq = [p[0] ** 2 + p[1] ** 2 for p in (s, m, e)]
    cx = (sq[0] * (m[1] - e[1]) + sq[1] * (e[1] - s[1]) + sq[2] * (s[1] - m[1])) / d
    cy = (sq[0] * (e[0] - m[0]) + sq[1] * (s[0] - e[0]) + sq[2] * (m[0] - s[0])) / d
    return (cx, cy), math.hypot(s[0] - cx, s[1] - cy)


def _sweep(c: Point, s: Point, m: Point, e: Point) -> tuple[float, float]:
    """The angle of an arc's start round its centre, and the angle it sweeps through its middle."""
    a0, am, a1 = (math.atan2(p[1] - c[1], p[0] - c[0]) for p in (s, m, e))
    sweep, to_mid = (a1 - a0) % math.tau, (am - a0) % math.tau
    return a0, sweep - math.tau if to_mid > sweep else sweep


ARC_STEPS = 64  # steps an arc is drawn in


def arc_track(s: Point, m: Point, e: Point, width: float) -> list[Polygon]:
    """An arc track drawn round its copper: a band and its 2 round ends. The band's outer corners stand at
    (r + w/2) / cos(half a step), so each outer side touches the copper's outer edge from outside; the
    inner side's chords lie inside its inner edge."""
    half = width / 2
    got = _circle_of(s, m, e)
    if got is None:
        return [_hull(circle(s, half) + circle(m, half) + circle(e, half))]
    c, r = got
    ends = [circle(s, half), circle(e, half)]
    if r - half <= EPS:
        return [circle(c, r + half), *ends]
    a0, sweep = _sweep(c, s, m, e)
    step = sweep / ARC_STEPS

    def at(radius: float, angle: float) -> Point:
        return (c[0] + radius * math.cos(angle), c[1] + radius * math.sin(angle))

    far = (r + half) / math.cos(step / 2)
    outer = [at(r + half, a0), *(at(far, a0 + step * (i + 0.5)) for i in range(ARC_STEPS))]
    outer.append(at(r + half, a0 + sweep))
    inner = [at(r - half, a0 + step * i) for i in range(ARC_STEPS, -1, -1)]
    return [outer + inner, *ends]


def box(c: Point, w: float, h: float, deg: float) -> Polygon:
    """A rectangle w by h at c, turned `deg` as KiCad turns a pad (y down)."""
    r = math.radians(deg)
    cos, sin = math.cos(r), math.sin(r)
    out = []
    for dx, dy in ((-w / 2, -h / 2), (w / 2, -h / 2), (w / 2, h / 2), (-w / 2, h / 2)):
        out.append((c[0] + dx * cos + dy * sin, c[1] - dx * sin + dy * cos))
    return out


def _pad_shape(at: Point, shape: str, w: float, h: float, deg: float) -> Polygon:
    if shape == "circle":
        return circle(at, max(w, h) / 2)
    if shape == "oval" and abs(w - h) > EPS:
        r = math.radians(deg)
        half = (max(w, h) - min(w, h)) / 2
        ux, uy = (math.cos(r), -math.sin(r)) if w > h else (math.sin(r), math.cos(r))
        return capsule(
            (at[0] - ux * half, at[1] - uy * half), (at[0] + ux * half, at[1] + uy * half), min(w, h)
        )
    if shape == "oval":
        return circle(at, w / 2)
    return box(at, w, h, deg)  # rect, roundrect, chamfered rect, trapezoid: the rectangle holds them


def _cuts(root) -> list[tuple[Polygon | None, str, float]]:
    """Each closed outline on Edge.Cuts: (polygon, or None for one with a curve or one that does not
    close; what it is and where; its area, an arc taken as its chord)."""
    out: list[tuple[Polygon | None, str, float]] = []
    lines: list[tuple[Point, Point, bool]] = []  # start, end, whether it is an arc
    for node in root[1:]:
        if not isinstance(node, list) or not node or not str(node[0]).startswith("gr_"):
            continue
        layer = kicadgen.child(node, "layer")
        if layer is None or str(kicadgen.atoms(layer)[0]) != "Edge.Cuts":
            continue
        head = node[0]
        if head == "gr_rect":
            x1, y1 = boardrules._xy(kicadgen.child(node, "start"))
            x2, y2 = boardrules._xy(kicadgen.child(node, "end"))
            poly = [(min(x1, x2), min(y1, y2)), (max(x1, x2), min(y1, y2)), (max(x1, x2), max(y1, y2))]
            poly.append((min(x1, x2), max(y1, y2)))
            out.append((poly, f"a rectangle on Edge.Cuts at {boardrules._p(poly[0])}", abs(_area(poly))))
        elif head == "gr_poly":
            pts = [boardrules._xy(p) for p in kicadgen.children(kicadgen.child(node, "pts"), "xy")]
            out.append((pts, f"a polygon on Edge.Cuts at {boardrules._p(pts[0])}", abs(_area(pts))))
        elif head in ("gr_line", "gr_arc"):
            start = boardrules._xy(kicadgen.child(node, "start"))
            lines.append((start, boardrules._xy(kicadgen.child(node, "end")), head == "gr_arc"))
        elif head == "gr_circle":
            c = boardrules._xy(kicadgen.child(node, "center"))
            e = boardrules._xy(kicadgen.child(node, "end"))
            r = math.hypot(e[0] - c[0], e[1] - c[1])
            out.append((None, f"a circle on Edge.Cuts at {boardrules._p(c)}", math.pi * r * r))
        elif head in ("gr_curve", "gr_bbox"):
            out.append((None, f"a {head[3:]} on Edge.Cuts", 0.0))
    # Lines and arcs joined end to end into loops.
    while lines:
        a, b, curved = lines.pop()
        loop = [a, b]
        while not _same(loop[0], loop[-1]):
            for i, (p, q, arc) in enumerate(lines):
                if _same(p, loop[-1]) or _same(q, loop[-1]):
                    loop.append(q if _same(p, loop[-1]) else p)
                    curved = curved or arc
                    lines.pop(i)
                    break
            else:
                break
        what = f"lines on Edge.Cuts from {boardrules._p(loop[0])}"
        if _same(loop[0], loop[-1]) and len(loop) >= 4:
            out.append((None if curved else loop[:-1], what, abs(_area(loop[:-1]))))
        else:
            out.append((None, what + " that do not close", 0.0))
    return out


def _same(a: Point, b: Point) -> bool:
    return abs(a[0] - b[0]) < 1e-6 and abs(a[1] - b[1]) < 1e-6


def _area(poly: Polygon) -> float:
    return sum(a[0] * b[1] - b[0] * a[1] for a, b in _edges(poly)) / 2


def _convex(poly: Polygon) -> bool:
    signs = set()
    for a, b, c in zip(poly, poly[1:] + poly[:1], poly[2:] + poly[:2], strict=True):
        cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cr) > EPS:
            signs.add(cr > 0)
    return len(signs) == 1


def read_copper(text: str) -> Copper:
    """The copper of a .kicad_pcb as polygons on each layer, and the cuts inside its outline."""
    board = boardrules.read_board(text)
    root = kicadgen.parse(text)
    ids = {  # KiCad 9 numbers its nets at the top; KiCad 10 names a pad's net in place
        str(a[0]): str(a[1])
        for a in (kicadgen.atoms(n) for n in kicadgen.children(root, "net"))
        if len(a) >= 2
    }
    _INDEX.clear()
    shapes: dict[str, list[tuple[str, Polygon]]] = {layer: [] for layer in board.copper}
    floating: dict[str, list[tuple[str, Polygon]]] = {layer: [] for layer in board.copper}
    unread: dict[str, list[str]] = {layer: [] for layer in board.copper}

    def put(net: str, layer: str, polys: list[Polygon], what: str) -> None:
        if layer not in shapes:
            return
        if net:
            shapes[layer].extend((net, p) for p in polys)
        else:
            floating[layer].extend((what, p) for p in polys)

    walls, slack, walls_unread = _walls(root)
    for node in root[1:]:
        if not isinstance(node, list) or not node:
            continue
        head = str(node[0])
        if head in ("segment", "arc"):
            layer = str(kicadgen.atoms(kicadgen.child(node, "layer"))[0])
            width = float(kicadgen.atoms(kicadgen.child(node, "width"))[0])
            start, end = (
                boardrules._xy(kicadgen.child(node, "start")),
                boardrules._xy(kicadgen.child(node, "end")),
            )
            if head == "arc":  # drawn round its curve, never as chords through its middle
                polys = arc_track(start, boardrules._xy(kicadgen.child(node, "mid")), end, width)
            else:
                polys = [capsule(start, end, width)]
            put(_net(node, ids), layer, polys, f"a track with no net at {_p(start)}")
        elif head.startswith("gr_") and _layer(node) in unread:
            unread[_layer(node)].append(f"a {head} at {_p(_first(node))}")
    for v in board.vias:
        for layer in v.layers:
            put(v.net, layer, [circle(v.at, v.size / 2)], f"a via with no net at {_p(v.at)}")
    for z in board.zones:
        polys = [p for p in z.polygons if len(p) >= 3]
        if polys:
            put(z.net, z.layer, polys, f"a zone with no net at {_p(polys[0][0])}")
    fp_edges: list[str] = []
    for fp in kicadgen.children(root, "footprint"):
        fx, fy, *rot = (float(v) for v in kicadgen.atoms(kicadgen.child(fp, "at")))
        frot = rot[0] if rot else 0.0
        ref = next((str(p[2]) for p in kicadgen.children(fp, "property") if str(p[1]) == "Reference"), "")
        name = ref or str(fp[1])
        for item in fp[1:]:
            if isinstance(item, list) and item and str(item[0]).startswith("fp_"):
                if _layer(item) == "Edge.Cuts":
                    fp_edges.append(f"a {item[0]} of {name} on Edge.Cuts at {_p((fx, fy))}")
                elif _layer(item) in unread:
                    unread[_layer(item)].append(f"a {item[0]} of {name} at {_p((fx, fy))}")
        for pad in kicadgen.children(fp, "pad"):
            net = _net(pad, ids)
            px, py, *prot = (float(v) for v in kicadgen.atoms(kicadgen.child(pad, "at")))
            r = math.radians(frot)
            at = (fx + px * math.cos(r) + py * math.sin(r), fy - px * math.sin(r) + py * math.cos(r))
            w, h = boardrules._xy(kicadgen.child(pad, "size"))
            shape = str(pad[3]) if len(pad) > 3 else "rect"
            # A pad's angle in a board file is the board's, and KiCad leaves it out when it is 0: the
            # footprint's angle is already in it.
            deg = prot[0] if prot else 0.0
            names = [str(x) for x in kicadgen.atoms(kicadgen.child(pad, "layers") or ["layers"])]
            on = list(board.copper) if "*.Cu" in names else [n for n in names if n in board.copper]
            if "F&B.Cu" in names:
                on = [board.copper[0], board.copper[-1]]
            drill, hole = _hole(pad)
            if len(pad) > 2 and str(pad[2]) == "np_thru_hole" and hole > 0:
                walls += _segments(circle(at, hole), closed=True)  # a hole with no plating: a wall
                if max(w, h) <= drill + EPS:
                    continue  # no copper round it
            if shape == "custom":
                w = h = max(w, h)  # the anchor
                prims = kicadgen.child(pad, "primitives")
                if prims is not None and len(prims) > 1:
                    for layer in on:
                        unread[layer].append(f"a custom pad of {name} at {_p(at)}")
            if kicadgen.child(pad, "padstack") is not None:  # another size on another layer: not read
                for layer in on:
                    unread[layer].append(f"a pad with a padstack of {name} at {_p(at)}")
            moved = _offset(pad)
            if moved:  # the copper stands off its hole, at an angle: a square round both holds it
                w = h = max(w, h) + 2 * moved
                shape = "rect" if shape != "circle" else shape
            for layer in on:
                put(net, layer, [_pad_shape(at, shape, w, h, deg)], f"a pad with no net at {_p(at)}")
    loops = _cuts(root)
    outline = max(range(len(loops)), key=lambda i: loops[i][2]) if loops else None
    cuts = []
    for i, (poly, what, _) in enumerate(loops):
        if i == outline:
            continue
        if poly is not None and len(poly) == 4 and _convex(poly):
            cuts.append(Cut(poly if _area(poly) > 0 else poly[::-1], what))
        else:
            cuts.append(Cut(None, what))
    cuts += [Cut(None, what) for what in fp_edges]
    walls_unread = walls_unread or (fp_edges[0] if fp_edges else "")
    return Copper(
        list(board.copper), shapes, cuts, board.thickness, walls, slack, walls_unread, floating, unread
    )


def _p(xy: Point) -> str:
    return boardrules._p((round(xy[0], 3), round(xy[1], 3)))


def _layer(node) -> str:
    found = kicadgen.child(node, "layer")
    got = kicadgen.atoms(found) if found is not None else []
    return str(got[0]) if got else ""


def _net(node, ids: dict[str, str]) -> str:
    """The net of a pad, a track or a via: quoted in place (KiCad 10), or by its number (KiCad 9)."""
    found = kicadgen.child(node, "net")
    if found is None:
        return ""
    got = kicadgen.atoms(found)
    quoted = [x for x in got if isinstance(x, kicadgen.Q)]
    return str(quoted[0]) if quoted else ids.get(str(got[0]), "") if got else ""


def _first(node) -> Point:
    """The first point a shape names, to say where it is."""
    for key in ("start", "center", "at"):
        found = kicadgen.child(node, key)
        if found is not None:
            return boardrules._xy(found)
    pts = kicadgen.child(node, "pts")
    xy = kicadgen.children(pts, "xy") if pts is not None else []
    return boardrules._xy(xy[0]) if xy else (0.0, 0.0)


def _offset(pad) -> float:
    """How far a pad's copper stands from its hole: `(drill ... (offset x y))`."""
    found = kicadgen.child(pad, "drill")
    offset = kicadgen.child(found, "offset") if found is not None else None
    return math.hypot(*boardrules._xy(offset)) if offset is not None else 0.0


def _hole(pad) -> tuple[float, float]:
    """A pad's drill, mm (the greater side of an oval), and the radius of a circle round its hole."""
    found = kicadgen.child(pad, "drill")
    if found is None:
        return 0.0, 0.0
    sizes = []
    for x in kicadgen.atoms(found):
        try:
            sizes.append(float(x))
        except ValueError:
            continue
    offset = kicadgen.child(found, "offset")
    off = math.hypot(*boardrules._xy(offset)) if offset is not None else 0.0
    drill = max(sizes) if sizes else 0.0
    return drill, drill / 2 + off


def _segments(points: list[Point], closed: bool) -> list[Polygon]:
    pairs = zip(points, points[1:] + points[:1], strict=True) if closed else itertools.pairwise(points)
    return [[a, b] for a, b in pairs if not _same(a, b)]


def _walls(root) -> tuple[list[Polygon], float, str]:
    """Each side of the outline and of each hole on Edge.Cuts as a segment; how much nearer an arc or a
    circle stands than its chords; and a shape this module does not read, with where it is."""
    walls: list[Polygon] = []
    slack = 0.0
    unread = ""
    for node in root[1:]:
        if not isinstance(node, list) or not node or not str(node[0]).startswith("gr_"):
            continue
        if _layer(node) != "Edge.Cuts":
            continue
        head = str(node[0])
        if head == "gr_line":
            walls += _segments([boardrules._xy(kicadgen.child(node, k)) for k in ("start", "end")], False)
        elif head == "gr_rect":
            (x1, y1), (x2, y2) = (boardrules._xy(kicadgen.child(node, k)) for k in ("start", "end"))
            walls += _segments([(x1, y1), (x2, y1), (x2, y2), (x1, y2)], True)
        elif head == "gr_poly":
            walls += _segments(
                [boardrules._xy(p) for p in kicadgen.children(kicadgen.child(node, "pts"), "xy")], True
            )
        elif head == "gr_arc":
            s, m, e = (boardrules._xy(kicadgen.child(node, k)) for k in ("start", "mid", "end"))
            walls += _segments(boardrules._arc_points(s, m, e), False)
            got = _circle_of(s, m, e)
            if got is not None:
                sweep = abs(_sweep(got[0], s, m, e)[1])
                slack = max(slack, got[1] * (1 - math.cos(sweep / boardrules.ARC_STEPS / 2)))
        elif head == "gr_circle":
            c = boardrules._xy(kicadgen.child(node, "center"))
            e = boardrules._xy(kicadgen.child(node, "end"))
            r = math.hypot(e[0] - c[0], e[1] - c[1])
            pts = [
                (c[0] + r * math.cos(math.tau * k / ARC_STEPS), c[1] + r * math.sin(math.tau * k / ARC_STEPS))
                for k in range(ARC_STEPS)
            ]
            walls += _segments(pts, True)
            slack = max(slack, r * (1 - math.cos(math.pi / ARC_STEPS)))
        else:
            unread = unread or f"a {head[3:]} on Edge.Cuts"
    return walls, slack, unread


# ---------------------------------------------------------------- distances


def _seg_point(p: Point, a: Point, b: Point) -> tuple[float, Point]:
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = dx * dx + dy * dy
    t = 0.0 if n < EPS else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n))
    q = (a[0] + t * dx, a[1] + t * dy)
    return math.hypot(p[0] - q[0], p[1] - q[1]), q


def _cross(a: Point, b: Point, c: Point, d: Point) -> bool:
    def o(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])

    return o(a, b, c) * o(a, b, d) < 0 and o(c, d, a) * o(c, d, b) < 0


def _inside(p: Point, poly: Polygon) -> bool:
    hit = False
    for a, b in _edges(poly):
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x > p[0]:
                hit = not hit
    return hit


def _edges(poly: Polygon):
    return zip(poly, poly[1:] + poly[:1], strict=True)


def nearest(polys: list[Polygon], q: Point) -> tuple[float, Point]:
    """The nearest point of the copper to q, and how far."""
    best = (math.inf, q)
    for poly in polys:
        if _inside(q, poly):
            return 0.0, q
        for a, b in _edges(poly):
            d, p = _seg_point(q, a, b)
            if d < best[0] - EPS or (abs(d - best[0]) <= EPS and p < best[1]):
                best = (d, p)
    return best


Box = tuple[float, float, float, float]


def _box_gap(a: Box, b: Box) -> float:
    """The gap between 2 boxes (x0, y0, x1, y1): never more than the gap between what they hold."""
    dx = max(0.0, b[0] - a[2], a[0] - b[2])
    dy = max(0.0, b[1] - a[3], a[1] - b[3])
    return math.hypot(dx, dy)


def _seg_box(a: Point, b: Point) -> Box:
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[0], b[0]), max(a[1], b[1]))


class _Index:
    """A polygon's box, and its edges in a grid of square cells, so that only the edges near a place are
    compared: a zone of thousands of corners is compared only where it comes near."""

    def __init__(self, poly: Polygon) -> None:
        xs, ys = [p[0] for p in poly], [p[1] for p in poly]
        self.box: Box = (min(xs), min(ys), max(xs), max(ys))
        self.edges = list(_edges(poly)) if len(poly) > 1 else []
        self.boxes = [_seg_box(a, b) for a, b in self.edges]
        self.cell = max(0.25, (self.box[2] - self.box[0]) / 64, (self.box[3] - self.box[1]) / 64)
        self.grid: dict[tuple[int, int], list[int]] | None = None

    def _cells(self, box: Box):
        c = self.cell
        for i in range(math.floor(box[0] / c), math.floor(box[2] / c) + 1):
            for j in range(math.floor(box[1] / c), math.floor(box[3] / c) + 1):
                yield (i, j)

    def near(self, box: Box, lim: float) -> list[tuple[Point, Point]]:
        """The edges within `lim` of a box."""
        if len(self.edges) <= 32 or math.isinf(lim):
            return [e for e, eb in zip(self.edges, self.boxes, strict=True) if _box_gap(eb, box) <= lim]
        if self.grid is None:
            self.grid = {}
            for k, eb in enumerate(self.boxes):
                for cell in self._cells(eb):
                    self.grid.setdefault(cell, []).append(k)
        seen: set[int] = set()
        out = []
        for cell in self._cells((box[0] - lim, box[1] - lim, box[2] + lim, box[3] + lim)):
            for k in self.grid.get(cell, ()):
                if k not in seen:
                    seen.add(k)
                    if _box_gap(self.boxes[k], box) <= lim:
                        out.append(self.edges[k])
        return out


_INDEX: dict[int, tuple[Polygon, _Index]] = {}


def _index(poly: Polygon) -> _Index:
    got = _INDEX.get(id(poly))
    if got is None or got[0] is not poly:
        got = (poly, _Index(poly))
        _INDEX[id(poly)] = got
    return got[1]


def _union(boxes: list[Box]) -> Box:
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def gap(pa: list[Polygon], pb: list[Polygon], cutoff: float = math.inf) -> tuple[float, Point, Point]:
    """The straight gap between 2 sets of polygons, with the 2 points it runs between. Of equal gaps, the
    one with the least point on the first set (by x, then y). A gap of `cutoff` or more is not looked for:
    then the gap returned is `cutoff` or more, or infinite."""
    best: tuple[float, Point, Point] = (math.inf, (0.0, 0.0), (0.0, 0.0))
    if not pa or not pb:
        return best

    def take(d: float, p: Point, q: Point) -> None:
        nonlocal best
        if d < best[0] - EPS or (abs(d - best[0]) <= EPS and p < best[1]):
            best = (d, p, q)

    ia = [_index(a) for a in pa]
    ib = [_index(b) for b in pb]
    box_b = _union([i.box for i in ib])
    if _box_gap(_union([i.box for i in ia]), box_b) > cutoff:
        return best
    for a, xa in zip(pa, ia, strict=True):
        if _box_gap(xa.box, box_b) > min(best[0] + EPS, cutoff):
            continue
        for b, xb in zip(pb, ib, strict=True):
            lim = min(best[0] + EPS, cutoff)
            apart = _box_gap(xa.box, xb.box)
            if apart > lim:
                continue
            if apart == 0 and (_inside(a[0], b) or _inside(b[0], a)):
                take(0.0, a[0], a[0])
                continue
            for a1, a2 in xa.near(xb.box, lim):
                lim = min(best[0] + EPS, cutoff)
                for b1, b2 in xb.near(_seg_box(a1, a2), lim):
                    if _cross(a1, a2, b1, b2):
                        take(0.0, a1, a1)
                        continue
                    for p in (a1, a2):
                        d, q = _seg_point(p, b1, b2)
                        take(d, p, q)
                    for q in (b1, b2):
                        d, p = _seg_point(q, a1, a2)
                        take(d, p, q)
    return best


def _blocked(p: Point, q: Point, slots: list[Polygon]) -> bool:
    """Whether the way from p to q runs through the inside of a slot (a convex polygon, anticlockwise in
    the file's axes). Along a slot's side or through its corner is not through it."""
    for poly in slots:
        t0, t1 = 0.0, 1.0
        d = (q[0] - p[0], q[1] - p[1])
        for a, b in _edges(poly):
            n = (-(b[1] - a[1]), b[0] - a[0])  # points inward for a polygon of positive area
            num = (p[0] - a[0]) * n[0] + (p[1] - a[1]) * n[1]
            den = d[0] * n[0] + d[1] * n[1]
            if abs(den) < EPS:
                if num < EPS:
                    t0, t1 = 1.0, 0.0
                    break
                continue
            t = -num / den
            if den > 0:
                t0 = max(t0, t)
            else:
                t1 = min(t1, t)
        if t1 - t0 > 1e-7:
            m = (p[0] + d[0] * (t0 + t1) / 2, p[1] + d[1] * (t0 + t1) / 2)
            inside = all(
                (m[0] - a[0]) * -(b[1] - a[1]) + (m[1] - a[1]) * (b[0] - a[0]) > 1e-7 for a, b in _edges(poly)
            )
            if inside:
                return True
    return False


def _width(poly: Polygon) -> float:
    """The lesser side of a cut of 4 corners."""
    sides = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in _edges(poly)]
    return min(sides)


@dataclass
class Measure:
    clearance: float
    at: Point
    creepage: float | None
    why: str = ""
    slots_used: bool = False
    narrow: list[Polygon] = field(default_factory=list)  # slots on the straight way, under the least width


def measure(cu: Copper, layer: str, a: str, b: str, reach: float, least_slot: float | None) -> Measure:
    """The gap through air between nets a and b on a layer, and the way along the face. Only a gap under
    `reach` mm is looked for, and only a way under it round a slot; a slot narrower than `least_slot` is
    crossed. A pack with no least width (None) measures every slot of 4 corners, and `slots_used` says
    one lengthened the way. A gap of `reach` or more reads as infinite."""
    return measure_sets(cu.polys(layer, a), cu.polys(layer, b), cu.cuts, reach, least_slot)


def measure_sets(
    pa: list[Polygon], pb: list[Polygon], cuts: list[Cut], reach: float, least_slot: float | None
) -> Measure:
    """`measure` between 2 sets of polygons."""
    d, at, to = gap(pa, pb, reach)
    if d >= reach:
        return Measure(math.inf, at, math.inf)
    near = [c for c in cuts if _near(c, pa, pb, reach)]
    unread = [c.what for c in near if c.polygon is None]
    if unread:
        return Measure(d, at, None, f"the way may run round {unread[0]}, which this check does not measure")
    slots = [c.polygon for c in near if least_slot is None or _width(c.polygon) >= least_slot - EPS]
    narrow = [
        c.polygon
        for c in near
        if least_slot is not None and _width(c.polygon) < least_slot - EPS and _blocked(at, to, [c.polygon])
    ]
    if not slots or not _blocked(at, to, slots):
        return Measure(d, at, d, narrow=narrow)  # the straight way runs along the face: nothing is shorter
    # A graph of the points the shortest way can turn at: the slots' corners; and on each net's copper,
    # its corners, its nearest point to each slot corner and to the other net. A way bends only at a
    # slot's corner, and leaves the copper from its nearest point to the first corner it meets.
    corners = [c for poly in slots for c in poly]
    sources = {at: 0.0}
    targets = {to}
    for c in corners:
        sources[nearest(pa, c)[1]] = 0.0
        targets.add(nearest(pb, c)[1])
    lots = _union([_index(s).box for s in slots])  # corners of the copper further than reach turn no way
    for poly in pa:
        sources.update(dict.fromkeys((p for p in poly if _box_gap((*p, *p), lots) < reach), 0.0))
    for poly in pb:
        targets.update(p for p in poly if _box_gap((*p, *p), lots) < reach)
    nodes = list(dict.fromkeys([*sources, *corners, *targets]))
    best = {n: math.inf for n in nodes}
    heap = []
    for s in sources:
        best[s] = 0.0
        heap.append((0.0, s))
    heapq.heapify(heap)
    found = math.inf
    while heap:
        dist, u = heapq.heappop(heap)
        if dist > best[u] + EPS:
            continue
        if u in targets:
            found = min(found, dist)
            break
        for v in nodes:
            if v == u or _blocked(u, v, slots):
                continue
            nd = dist + math.hypot(v[0] - u[0], v[1] - u[1])
            if nd < best[v] - EPS:
                best[v] = nd
                heapq.heappush(heap, (nd, v))
    return Measure(d, at, found, slots_used=found > d + 1e-7, narrow=narrow)


def _near(cut: Cut, pa: list[Polygon], pb: list[Polygon], reach: float) -> bool:
    """A cut that can stand on a way under `reach` between the 2 nets: within reach of both. A cut this
    module does not read counts as near."""
    if cut.polygon is None:
        return True
    return gap([cut.polygon], pa, reach)[0] < reach and gap([cut.polygon], pb, reach)[0] < reach


def _across_floating(
    items: list[tuple[str, Polygon]], pa: list[Polygon], pb: list[Polygon], limit: float
) -> tuple[float, str] | None:
    """The shortest way from 1 set of polygons to the other across 1 or more of `items`, copper with no
    net, under `limit`: the sum of the gaps, the conductors' own width counted as nothing; and the first
    conductor on it."""
    if not items:
        return None
    best: dict[int, float] = {}
    first: dict[int, int] = {}
    for i, (_, poly) in enumerate(items):
        d = gap([poly], pa, limit)[0]
        if d < limit:
            best[i], first[i] = d, i
    heap = [(d, i) for i, d in best.items()]
    heapq.heapify(heap)
    found: tuple[float, int] | None = None
    while heap:
        d, i = heapq.heappop(heap)
        if d > best[i] + EPS:
            continue
        if found is not None and d >= found[0]:
            break
        poly = items[i][1]
        db = gap([poly], pb, limit - d)[0]
        if d + db < limit and (found is None or d + db < found[0]):
            found = (d + db, first[i])
        for j, (_, other) in enumerate(items):
            if j == i:
                continue
            nd = d + gap([poly], [other], limit - d)[0]
            if nd < limit and nd < best.get(j, math.inf) - EPS:
                best[j], first[j] = nd, first[i]
                heapq.heappush(heap, (nd, j))
    return (found[0], items[found[1]][0]) if found else None


# ---------------------------------------------------------------- the findings


def _mm(v: float) -> str:
    return f"{round(v, 3):g}"


def _said(cond: dict[str, str], keys: list[str]) -> str:
    return ", ".join(f"{k.replace('_', ' ')} {cond[k]}" for k in keys)


def findings(
    cu: Copper, spans: dict[str, tuple[float, float]], pack: Pack, cond: dict[str, str]
) -> list[Finding]:
    """Each pair of nets with a voltage between them, on each outer layer, held to the pack's tables."""
    out: list[Finding] = []
    outer = [cu.layers[0], cu.layers[-1]] if cu.layers else []
    nets = sorted({n for layer in cu.shapes for n, _ in cu.shapes[layer]})
    for n in nets:
        if n not in spans:
            out.append(Finding("not judged", f"creepage of {n}: ratings.json states no voltage for it"))
    for layer in dict.fromkeys(outer):
        items = cu.unread.get(layer, [])
        if items:
            some = (
                f"{len(items)} shapes drawn on the copper are"
                if len(items) > 1
                else "1 shape drawn on the copper is"
            )
            out.append(Finding("not judged", f"creepage on {layer}: {some} not read ({items[0]})"))
    least_slot = pack.least_slot(cond)
    failed: set[tuple[str, str]] = set()
    flagged: set[tuple[str, str]] = set()
    for layer in cu.layers:
        # The net of the higher voltage first: `HV to GND`.
        here = sorted({n for n, _ in cu.shapes.get(layer, []) if n in spans}, key=lambda n: (-spans[n][1], n))
        pairs = [
            (a, b) for a, b in itertools.combinations(here, 2) if boardrules.between(spans[a], spans[b]) > 0
        ]
        if layer not in outer:
            if pairs:
                count = f"{len(pairs)} pair{'s' if len(pairs) > 1 else ''} of nets"
                out.append(
                    Finding(
                        "not judged",
                        f"creepage on {layer}: {count} with a voltage between them inside the laminate, "
                        "where there is no surface",
                    )
                )
            continue
        for a, b in pairs:
            got = _pair(cu, layer, a, b, boardrules.between(spans[a], spans[b]), pack, cond, least_slot)
            out += got
            if got:
                flagged.add((a, b))
            if any(f.status == "fail" for f in got):
                failed.add((a, b))
    if len(cu.layers) >= 2:
        out += _faces(cu, spans, pack, cond, least_slot, failed, flagged)
    return out


def _faces(cu: Copper, spans, pack: Pack, cond, least_slot, failed: set, flagged: set) -> list[Finding]:
    """Each pair of nets with a voltage between them, 1 on F.Cu and the other on B.Cu: a way between them
    runs round the board's edge or through a hole. This module does not measure that way; it holds the
    pair only when the least length such a way can have reaches the pack's distance, and prints it `not
    judged` otherwise. The least length along the faces: the 2 nets' gaps to the nearest wall and the
    board's thickness, and no less than the way along 1 face between the 2 nets' outlines. Through air:
    sqrt((the 2 gaps to a wall)^2 + thickness^2), and no less than the straight gap in 3 dimensions.
    Each gap may cross copper with no net, whose own width counts nothing. A pair that already fails on
    1 face gets no more lines."""
    out: list[Finding] = []
    top, bot = cu.layers[0], cu.layers[-1]
    cap = pack.most + 1
    to_wall: dict[tuple[str, str], tuple[float, Point | None]] = {}
    stray = cu.floating.get(top, []) + cu.floating.get(bot, [])

    def wall(net: str, layer: str) -> tuple[float, Point | None]:
        if (net, layer) not in to_wall:
            if cu.walls_unread or not cu.walls:
                to_wall[(net, layer)] = (0.0, None)
            else:
                polys = cu.polys(layer, net)
                d, p, _ = gap(polys, cu.walls, cap)
                across = _across_floating(cu.floating.get(layer, []), polys, cu.walls, min(d, cap))
                if across is not None:
                    d = across[0]
                to_wall[(net, layer)] = (max(0.0, min(d, cap) - cu.walls_slack), p if d < cap else None)
        return to_wall[(net, layer)]

    on = {layer: {n for n, _ in cu.shapes.get(layer, []) if n in spans} for layer in (top, bot)}
    nets = sorted(on[top] | on[bot], key=lambda n: (-spans[n][1], n))
    for a, b in itertools.combinations(nets, 2):
        volts = boardrules.between(spans[a], spans[b])
        if volts <= 0 or (a, b) in failed:
            continue
        creep = pack.limit("creepage", volts, cond)
        clear = pack.limit("clearance", volts, cond) if "clearance" in pack.tables else None
        for la, lb in ((top, bot), (bot, top)):
            if a not in on[la] or b not in on[lb]:
                continue
            head = f"{a} on {la} to {b} on {lb}"
            if creep.at_least is None:
                if (a, b) not in flagged:
                    flagged.add((a, b))
                    out.append(Finding("not judged", f"creepage {head}: {creep.why}", pack.cite(creep.where)))
                continue
            pa, pb = cu.polys(la, a), cu.polys(lb, b)
            da, at = wall(a, la)
            db, _ = wall(b, lb)
            low = da + cu.thickness + db
            low_c = math.hypot(da + db, cu.thickness)
            need_c = clear.at_least if clear is not None else None
            if low >= creep.at_least - EPS and (need_c is None or low_c >= need_c - EPS):
                continue
            m = measure_sets(pa, pb, cu.cuts, creep.at_least + 1, least_slot)
            plan = m.creepage if m.creepage is not None else m.clearance
            straight = m.clearance
            across = _across_floating(stray, pa, pb, min(plan, creep.at_least + 1))
            if across is not None:
                plan, straight = min(plan, across[0]), min(straight, across[0])
            low = max(low, plan)
            low_c = max(low_c, math.hypot(straight, cu.thickness))
            where = (
                f" at {_p(at if at is not None else m.at)}"
                if at is not None or math.isfinite(m.clearance)
                else ""
            )
            if need_c is not None and low_c < need_c - EPS:
                out.append(
                    Finding(
                        "not judged",
                        f"clearance {head}{where}: at least {_mm(low_c)} mm through air round the board's "
                        f"edge or through a hole, {_mm(need_c)} mm asked at {volts:g} V: this check does not "
                        "measure a way between the 2 faces",
                        pack.cite(clear.where),
                    )
                )
            if low < creep.at_least - EPS:
                out.append(
                    Finding(
                        "not judged",
                        f"creepage {head}{where}: at least {_mm(low)} mm round the board's edge or through a "
                        f"hole, {_mm(creep.at_least)} mm asked at {volts:g} V: this check does not measure a "
                        "way between the 2 faces",
                        pack.cite(creep.where),
                    )
                )
    return out


def _pair(cu, layer, a, b, volts, pack: Pack, cond, least_slot) -> list[Finding]:
    out: list[Finding] = []
    head = f"{a} to {b} on {layer}"
    creep = pack.limit("creepage", volts, cond)
    clear = pack.limit("clearance", volts, cond) if "clearance" in pack.tables else None
    reach = max(
        x for x in (creep.at_least, creep.fails_under, clear.at_least if clear else None, 0) if x is not None
    )
    m = measure(cu, layer, a, b, reach + 1, least_slot)
    where = f"at {_p(m.at)}" if math.isfinite(m.clearance) else ""
    if clear is not None:
        keys = pack.tables["clearance"]["keys"]
        if clear.at_least is None:
            out.append(Finding("not judged", f"clearance {head}: {clear.why}", pack.cite(clear.where)))
        elif m.clearance < clear.at_least - EPS:
            out.append(
                Finding(
                    "fail",
                    f"clearance {head} {where}: {_mm(m.clearance)} mm through air at {volts:g} V, at least "
                    f"{_mm(clear.at_least)} mm ({_said(cond, keys)})",
                    pack.cite(clear.where),
                )
            )
    keys = pack.tables["creepage"]["keys"]
    if creep.at_least is None:
        out.append(Finding("not judged", f"creepage {head}: {creep.why}", pack.cite(creep.where)))
        return out
    if m.clearance >= creep.at_least - EPS:
        # The way along the face is never shorter than the straight gap, unless it crosses copper with no net.
        return out + _stray(cu, layer, a, b, head, where, volts, pack, creep, clear, out)
    if m.creepage is None:
        out.append(Finding("not judged", f"creepage {head} {where}: {m.why}", pack.cite(creep.where)))
        return out
    s = m.creepage
    if s >= creep.at_least - EPS:
        if m.slots_used and least_slot is None:
            out.append(
                Finding(
                    "not judged",
                    f"creepage {head} {where}: {_mm(m.clearance)} mm straight, {_mm(s)} mm round a slot, at "
                    f"least {_mm(creep.at_least)} mm at {volts:g} V: the pack states no least width for a "
                    "slot",
                    pack.cite(creep.where),
                )
            )
            return out
        return out + _stray(cu, layer, a, b, head, where, volts, pack, creep, clear, out)
    if creep.fails_under is not None and s < creep.fails_under - EPS:
        out.append(
            Finding(
                "fail",
                f"creepage {head} {where}: {_mm(s)} mm along the surface at {volts:g} V, at least "
                f"{_mm(creep.fails_under)} mm ({_said(cond, keys)})",
                pack.cite(creep.where),
            )
        )
        for slot in m.narrow:
            out.append(
                Finding(
                    "fail",
                    f"slot {head} at {_p(min(slot))}: {_mm(_width(slot))} mm wide, at least "
                    f"{_mm(least_slot)} mm to lengthen the way ({_said(cond, [pack.slot['key']])})",
                    pack.cite(pack.slot["where"]),
                )
            )
        return out
    if len(creep.rows) == 2:
        (v0, m0), (v1, m1) = creep.rows
        why = f"{_mm(s)} mm at {volts:g} V lies between {_mm(m0)} mm ({v0:g} V) and {_mm(m1)} mm ({v1:g} V)"
    else:
        why = f"{_mm(s)} mm at {volts:g} V, {creep.why}, under its {_mm(creep.at_least)} mm"
    out.append(Finding("not judged", f"creepage {head} {where}: {why}", pack.cite(creep.where)))
    return out


def _stray(cu, layer, a, b, head, where, volts, pack: Pack, creep: Limit, clear: Limit | None, out) -> list:
    """A pair that holds on its straight gap: `not judged` when a way across copper with no net is shorter
    than the pack asks, through air or along the face."""
    if any(f.status == "fail" for f in out):
        return []
    limit = max(creep.at_least, clear.at_least if clear is not None and clear.at_least is not None else 0)
    over = _across_floating(cu.floating.get(layer, []), cu.polys(layer, a), cu.polys(layer, b), limit)
    if over is None:
        return []
    at = f" {where}" if where else ""
    return [
        Finding(
            "not judged",
            f"creepage {head}{at}: {_mm(over[0])} mm across copper with no net ({over[1]}), under the "
            f"{_mm(limit)} mm asked at {volts:g} V: this check does not judge a way across a conductor with "
            "no net",
            pack.cite(creep.where),
        )
    ]


# ---------------------------------------------------------------- the run


def judge(project, stated: dict, board_text: str, spans: dict) -> tuple[str, list[Finding], list[str]]:
    """The board held to the creepage pack `board-rules.json` names under `creepage`: the pack's label,
    the findings and the notes."""
    at = f"{boardrules.PROJECT_FILE}: creepage"
    if not isinstance(stated, dict) or "pack" not in stated:
        raise Refusal(f"{at}: an object with `pack` and the pack's conditions is asked")
    path, label = boardrules.find_pack(ratings._text(f"{at}: pack", stated["pack"]), project.dir)
    if not is_creepage(path):
        raise Refusal(f"{at}: pack: {label} is no creepage pack")
    pack = read_pack(path)
    cond = pack.conditions_of(stated)
    cu = read_copper(board_text)
    notes = [
        f"board rules: {label}, {pack.document['number']} ({pack.document['revision']}), "
        f"{_said(cond, list(pack.conditions))}",
        "creepage: between 2 nets on 1 outer layer, and across copper with no net; between F.Cu and B.Cu "
        "only the least length a way round the board's edge or through a hole can have",
    ]
    if "clearance" not in pack.tables:
        notes.append(f"clearance: {pack.name} holds no clearance table; {pack.not_judged[0]}")
    return label, findings(cu, spans, pack, cond), notes
