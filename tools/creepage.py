#!/usr/bin/env python3
"""creepage — the gap between 2 nets' copper held to their working voltage, through air and along the
board's face.

A creepage pack (`rules/board/<pack>.json`, `"kind": "creepage"`) holds a document's tables of
clearance (through air) and creepage (along a surface) by voltage, under conditions the project states
in `board-rules.json` under `creepage`. The voltage between 2 nets is the most their spans in
`ratings.json` allow. The copper of each outer layer is read as polygons drawn round it, so a gap is
never read larger than it is. A slot (an inner cut of Edge.Cuts with 4 corners) between 2 nets
lengthens the way along the face: the way goes round its corners. Standard library only.
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
        ("clearance", "slot", "scope", "reprints"),
    )
    if data["kind"] != "creepage":
        raise Refusal(f"{name}: kind: `creepage` is asked")
    document = ratings._keys(f"{name}: document", data["document"], ratings.DOCUMENT_KEYS)
    for key in ratings.DOCUMENT_KEYS:
        ratings._text(f"{name}: document: {key}", document[key])
    ratings._source(f"{name}: document", document)
    conditions = data["conditions"]
    if not isinstance(conditions, dict) or not conditions:
        raise Refusal(f"{name}: conditions: an object of conditions is asked")
    for key, spec in conditions.items():
        spec = ratings._keys(f"{name}: conditions: {key}", spec, ("values", "where"))
        ratings._names(f"{name}: conditions: {key}: values", spec["values"])
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
        for k, v in slot["least_mm"].items():
            ratings._number(f"{name}: slot: least_mm: {k}", v, None, None, 0)
        boardrules._where(f"{name}: slot", slot["where"])
    if not isinstance(data["not_judged"], list):
        raise Refusal(f"{name}: not_judged: a list of places is asked")
    for i, text in enumerate(data["not_judged"], start=1):
        boardrules._where(f"{name}: not_judged {i}", text)
    return Pack(
        ratings._text(f"{name}: pack", data["pack"]),
        document,
        conditions,
        data["voltage"],
        data["between_rows"],
        tables,
        slot,
        data["not_judged"],
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
    shapes: dict[str, list[tuple[str, Polygon]]] = {layer: [] for layer in board.copper}
    for t in board.tracks:
        if t.net and t.layer in shapes:
            shapes[t.layer].append((t.net, capsule(t.start, t.end, t.width)))
    for v in board.vias:
        for layer in v.layers:
            if v.net and layer in shapes:
                shapes[layer].append((v.net, circle(v.at, v.size / 2)))
    for z in board.zones:
        if z.net and z.layer in shapes:
            shapes[z.layer].extend((z.net, p) for p in z.polygons if len(p) >= 3)
    for fp in kicadgen.children(root, "footprint"):
        fx, fy, *rot = (float(v) for v in kicadgen.atoms(kicadgen.child(fp, "at")))
        frot = rot[0] if rot else 0.0
        for pad in kicadgen.children(fp, "pad"):
            net_node = kicadgen.child(pad, "net")
            got = kicadgen.atoms(net_node) if net_node else []
            quoted = [x for x in got if isinstance(x, kicadgen.Q)]
            net = str(quoted[0]) if quoted else ids.get(str(got[0]), "") if got else ""
            if not net:
                continue
            px, py, *prot = (float(v) for v in kicadgen.atoms(kicadgen.child(pad, "at")))
            r = math.radians(frot)
            at = (fx + px * math.cos(r) + py * math.sin(r), fy - px * math.sin(r) + py * math.cos(r))
            w, h = boardrules._xy(kicadgen.child(pad, "size"))
            shape = str(pad[3]) if len(pad) > 3 else "rect"
            deg = prot[0] if prot else frot  # a pad's angle in the file is the board's
            if shape == "custom":
                w = h = max(w, h)  # the anchor; a custom pad's primitives are not read
            poly = _pad_shape(at, shape, w, h, deg)
            names = [str(x) for x in kicadgen.atoms(kicadgen.child(pad, "layers") or ["layers"])]
            on = list(board.copper) if "*.Cu" in names else [n for n in names if n in board.copper]
            if "F&B.Cu" in names:
                on = [board.copper[0], board.copper[-1]]
            for layer in on:
                shapes[layer].append((net, poly))
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
    return Copper(list(board.copper), shapes, cuts)


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


def gap(pa: list[Polygon], pb: list[Polygon]) -> tuple[float, Point, Point]:
    """The straight gap between 2 sets of polygons, with the 2 points it runs between. Of equal gaps, the
    one with the least point on the first set (by x, then y)."""
    best: tuple[float, Point, Point] = (math.inf, (0.0, 0.0), (0.0, 0.0))

    def take(d: float, p: Point, q: Point) -> None:
        nonlocal best
        if d < best[0] - EPS or (abs(d - best[0]) <= EPS and p < best[1]):
            best = (d, p, q)

    for a in pa:
        for b in pb:
            if _inside(a[0], b) or _inside(b[0], a):
                take(0.0, a[0], a[0])
                continue
            for a1, a2 in _edges(a):
                for b1, b2 in _edges(b):
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


def measure(cu: Copper, layer: str, a: str, b: str, reach: float, least_slot: float | None) -> Measure:
    """The gap through air between nets a and b on a layer, and the way along the face. Only a way under
    `reach` mm is looked for round a slot; a slot narrower than `least_slot` is crossed. A pack with no
    least width (None) measures every slot of 4 corners, and `slots_used` says one lengthened the way."""
    pa = [p for n, p in cu.shapes.get(layer, []) if n == a]
    pb = [p for n, p in cu.shapes.get(layer, []) if n == b]
    d, at, to = gap(pa, pb)
    near = [c for c in cu.cuts if _near(c, pa, pb, reach)]
    unread = [c.what for c in near if c.polygon is None]
    if unread:
        return Measure(d, at, None, f"the way may run round {unread[0]}, which this check does not measure")
    slots = [c.polygon for c in near if least_slot is None or _width(c.polygon) >= least_slot - EPS]
    if not slots or not _blocked(at, to, slots):
        return Measure(d, at, d)  # the straight way runs along the face: nothing is shorter
    # A graph of the points the shortest way can turn at: the slots' corners; and on each net's copper,
    # its corners, its nearest point to each slot corner and to the other net. A way bends only at a
    # slot's corner, and leaves the copper from its nearest point to the first corner it meets.
    corners = [c for poly in slots for c in poly]
    sources = {at: 0.0}
    targets = {to}
    for c in corners:
        sources[nearest(pa, c)[1]] = 0.0
        targets.add(nearest(pb, c)[1])
    for poly in pa:
        sources.update(dict.fromkeys(poly, 0.0))
    for poly in pb:
        targets.update(poly)
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
    return Measure(d, at, found, slots_used=found > d + 1e-7)


def _near(cut: Cut, pa: list[Polygon], pb: list[Polygon], reach: float) -> bool:
    """A cut that can stand on a way under `reach` between the 2 nets: within reach of both. A cut this
    module does not read counts as near."""
    if cut.polygon is None:
        return True
    return gap([cut.polygon], pa)[0] < reach and gap([cut.polygon], pb)[0] < reach


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
    least_slot = pack.least_slot(cond)
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
            out += _pair(cu, layer, a, b, boardrules.between(spans[a], spans[b]), pack, cond, least_slot)
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
    where = f"at {boardrules._p((round(m.at[0], 3), round(m.at[1], 3)))}"
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
        return out  # the way along the face is never shorter than the straight gap
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
    if creep.fails_under is not None and s < creep.fails_under - EPS:
        out.append(
            Finding(
                "fail",
                f"creepage {head} {where}: {_mm(s)} mm along the surface at {volts:g} V, at least "
                f"{_mm(creep.fails_under)} mm ({_said(cond, keys)})",
                pack.cite(creep.where),
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
        "creepage: between 2 nets on 1 outer layer; not between layers, through a hole or round the "
        "board's edge",
    ]
    if "clearance" not in pack.tables:
        notes.append(f"clearance: {pack.name} holds no clearance table; {pack.not_judged[0]}")
    return label, findings(cu, spans, pack, cond), notes
