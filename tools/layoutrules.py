#!/usr/bin/env python3
"""layoutrules — a board held to the layout rules a maker's note states.

A layout pack (`rules/board/<pack>.json`, `"kind": "layout"`) names a maker's note and the rules of it the
workcenter judges, each with its section and page. A project names its layout packs in `board-rules.json`
under `layout`, beside the voltage pack of `tools/boardrules.py`, and states what the board file cannot
say: which connectors leave the device, which parts protect against ESD, which nets are ground, which are
power. The DRC gate prints each finding on the same line as the voltage pack's. Standard library only.
"""

from __future__ import annotations

import heapq
import math
import re
from pathlib import Path

import boardrules
import kicadgen
import ratings
from boardrules import Board, Finding, _p
from ratings import Refusal

CHECKS = {
    "esd_protector": ("connectors", "protectors", "ground"),
    "esd_nearest": ("connectors", "protectors", "ground"),
    "esd_no_via": ("connectors", "protectors", "ground"),
    "length_to_width": ("power", "ground"),
}
CONNECTOR_RE = re.compile(r"^[JP]\d+$")  # IEEE 315's letters for a connector and a plug
CONNECTOR_LIBRARY = (
    "Connector"  # KiCad's footprint libraries of connectors: Connector_USB, Connector_JST, ...
)
NEAR = 1e-3


def is_connector(pad) -> bool:
    """A part is a connector by its reference (J or P and digits) or by its footprint's library."""
    return bool(CONNECTOR_RE.match(pad.ref)) or pad.footprint.split(":")[0].startswith(CONNECTOR_LIBRARY)


class Pack:
    def __init__(self, name: str, document: dict, rules: list[dict], not_judged: list[str]):
        self.name, self.document, self.rules, self.not_judged = name, document, rules, not_judged

    def cite(self, where: str) -> str:
        return f"{self.document['number']}: {where}"

    def asks(self) -> set[str]:
        return {key for r in self.rules for key in CHECKS[r["check"]]}


def read_pack(path: Path) -> Pack:
    """A layout pack: its document with URL and SHA256, and rules whose `check` this module knows, each
    with a `where` that names its page."""
    name = path.name
    data = ratings._keys(name, ratings._json(path), ("pack", "kind", "document", "rules", "not_judged"))
    if data["kind"] != "layout":
        raise Refusal(f"{name}: kind: `layout` is asked")
    document = ratings._keys(f"{name}: document", data["document"], ratings.DOCUMENT_KEYS)
    for key in ratings.DOCUMENT_KEYS:
        ratings._text(f"{name}: document: {key}", document[key])
    ratings._source(f"{name}: document", document)
    if not isinstance(data["rules"], list) or not data["rules"]:
        raise Refusal(f"{name}: rules: a list of rules is asked")
    for i, rule in enumerate(data["rules"], start=1):
        at = f"{name}: rules {i}"
        ratings._keys(at, rule, ("id", "check", "where"), ("most", "copper_layers"))
        ratings._text(f"{at}: id", rule["id"])
        if rule["check"] not in CHECKS:
            raise Refusal(f"{at}: check: `{rule['check']}` is no check; the checks are {', '.join(CHECKS)}")
        boardrules._where(at, rule["where"])
        if rule["check"] == "length_to_width":
            ratings._number(f"{at}: most", rule.get("most"), 0, None, 0)
            layers = ratings._number(f"{at}: copper_layers", rule.get("copper_layers"), 1, None, None)
            if not layers.is_integer():
                raise Refusal(f"{at}: copper_layers: {layers:g} is no whole number")
    if not isinstance(data["not_judged"], list):
        raise Refusal(f"{name}: not_judged: a list of places is asked")
    for i, text in enumerate(data["not_judged"], start=1):
        boardrules._where(f"{name}: not_judged {i}", text)
    return Pack(ratings._text(f"{name}: pack", data["pack"]), document, data["rules"], data["not_judged"])


def is_layout(path: Path) -> bool:
    data = ratings._json(path)
    return isinstance(data, dict) and data.get("kind") == "layout"


# ---------------------------------------------------------------- what the project states


def stated(board: Board, pack: Pack, data: dict) -> dict:
    """The keys of board-rules.json the pack asks, each part and net on the board."""
    refs = {p.ref for p in board.pads}
    for key in sorted(pack.asks()):
        if key not in data:
            raise Refusal(f"{boardrules.PROJECT_FILE}: `{key}` is missing; the pack {pack.name} asks it")
    for key in ("connectors", "protectors"):
        if key in data:
            if not isinstance(data[key], dict):
                raise Refusal(f"{boardrules.PROJECT_FILE}: {key}: an object of reference: why is asked")
            for ref, why in data[key].items():
                ratings._text(f"{boardrules.PROJECT_FILE}: {key}: {ref}", why)
                if ref not in refs:
                    raise Refusal(f"{boardrules.PROJECT_FILE}: {key}: {ref} is not on the board")
    for key in ("ground", "power", "inside"):
        if key in data:
            names = ratings._names(f"{boardrules.PROJECT_FILE}: {key}", data[key])
            known = refs if key == "inside" else board.nets
            for name in names:
                if name not in known:
                    what = "is not on the board" if key == "inside" else "is no net of the board"
                    raise Refusal(f"{boardrules.PROJECT_FILE}: {key}: {name} {what}")
    return data


# ---------------------------------------------------------------- ESD


def _joined(board: Board, net: str, a, b) -> str:
    """How pads a and b meet in the copper of `net`: `layer` on 1 layer, `via` only through layers,
    `none` not at all."""
    roots: dict[str, tuple[list[tuple], dict[int, int]]] = {}
    for layer in board.copper:
        roots[layer] = boardrules._pieces(board, net, layer)

    def piece(pad, layer: str) -> int | None:
        items, root = roots[layer]
        dot = ("seg", pad.at, pad.at, pad.reach)
        return next((root[i] for i, item in enumerate(items) if item == dot), None)

    for layer in set(a.layers) & set(b.layers):
        pa, pb = piece(a, layer), piece(b, layer)
        if pa is not None and pa == pb:
            return "layer"
    # The pieces of every layer, joined where a via or a pad on several layers touches them.
    parent: dict[tuple[str, int], tuple[str, int]] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    links = [(v.at, v.size / 2, v.layers) for v in board.vias if v.net == net]
    links += [(p.at, p.reach, p.layers) for p in board.pads if p.net == net and len(p.layers) > 1]
    for at, reach, layers in links:
        dot = ("seg", at, at, reach)
        touched = [
            (ly, roots[ly][1][i])
            for ly in layers
            for i, item in enumerate(roots[ly][0])
            if boardrules._meets(dot, item)
        ]
        for x in touched[1:]:
            parent[find(x)] = find(touched[0])
    ends = [{find((ly, r)) for ly in pad.layers if (r := piece(pad, ly)) is not None} for pad in (a, b)]
    return "via" if ends[0] & ends[1] else "none"


def _natural(text: str) -> list:
    return [(0, int(s), "") if s.isdigit() else (1, 0, s) for s in re.split(r"(\d+)", text)]


def _pad_order(p) -> tuple:
    return (_natural(p.ref), _natural(p.number))


def _name(p) -> str:
    return f"{p.ref}.{p.number}"


class Copper:
    """The tracks of 1 net on every layer as a graph. Its points lie on the tracks' centre lines: the ends
    of each track, where another track's end or a crossing meets it, and where a via, a pad or a pour
    touches it. A track between 2 points is an edge of its length and width. A via, a pad or a pour joins
    every point it touches into 1 node, so a via ends no trace, and a pad or a pour is an end."""

    def __init__(self, board: Board, net: str):
        self.where: dict[tuple, tuple[float, float]] = {}
        self.pads: dict[tuple, list] = {}  # a node: the pads it is
        self.pours: dict[tuple, str] = {}  # a node: the layer of the pour it is
        segs = [t for t in board.tracks if t.net == net]
        vias = [v for v in board.vias if v.net == net]
        pads = [p for p in board.pads if p.net == net]
        edges: list[tuple[tuple, tuple, float, float, str]] = []
        joins: list[tuple[tuple, tuple]] = []

        def pt(layer: str, xy: tuple[float, float]) -> tuple:
            node = ("pt", layer, *_key(xy))
            self.where.setdefault(node, xy)
            return node

        def foot(xy, s) -> tuple[float, float, tuple[float, float]]:
            (ax, ay), (bx, by) = s.start, s.end
            dx, dy = bx - ax, by - ay
            span = dx * dx + dy * dy
            t = 0.0 if span == 0 else max(0.0, min(1.0, ((xy[0] - ax) * dx + (xy[1] - ay) * dy) / span))
            at = (ax + t * dx, ay + t * dy)
            return t, math.dist(xy, at), at

        cuts: list[list[tuple[float, tuple[float, float]]]] = [[(0.0, s.start), (1.0, s.end)] for s in segs]
        for i, s in enumerate(segs):
            for j, o in enumerate(segs):
                if i == j or o.layer != s.layer:
                    continue
                for xy in (o.start, o.end):
                    t, d, at = foot(xy, s)
                    if d <= s.width / 2 + NEAR:
                        cuts[i].append((t, at))
                        if d > NEAR:  # an end inside the track's copper, off its centre line
                            edges.append((pt(s.layer, xy), pt(s.layer, at), d, o.width, s.layer))
                cross = _crossing(s.start, s.end, o.start, o.end)
                if cross is not None:
                    cuts[i].append((foot(cross, s)[0], cross))
            touching = [(("via", k), v.at, v.size / 2, v.layers) for k, v in enumerate(vias)]
            touching += [(("pad", k), p.at, p.reach, p.layers) for k, p in enumerate(pads)]
            for node, at, reach, layers in touching:
                # A track that ends on the pad or via is joined at that end, below; one that passes over it
                # is cut where the centre falls on it.
                ends_on = min(math.dist(at, s.start), math.dist(at, s.end)) <= reach + NEAR
                if s.layer in layers and not ends_on:
                    t, d, on = foot(at, s)
                    if d <= s.width / 2 + reach + NEAR:
                        cuts[i].append((t, on))
                        joins.append((node, pt(s.layer, on)))
        for i, s in enumerate(segs):
            points: list[tuple[float, float]] = []
            for _, xy in sorted(cuts[i], key=lambda c: c[0]):
                if not points or _key(points[-1]) != _key(xy):
                    points.append(xy)
            for a, b in zip(points, points[1:], strict=False):
                edges.append((pt(s.layer, a), pt(s.layer, b), math.dist(a, b), s.width, s.layer))
        # A pad or a via joins each point within its reach; a pour each point inside it.
        for node in list(self.where):
            layer, xy = node[1], self.where[node]
            for k, v in enumerate(vias):
                if layer in v.layers and math.dist(xy, v.at) <= v.size / 2 + NEAR:
                    joins.append((("via", k), node))
            for k, p in enumerate(pads):
                if layer in p.layers and math.dist(xy, p.at) <= p.reach + NEAR:
                    joins.append((("pad", k), node))
            for k, z in enumerate(board.zones):
                if (
                    z.net == net
                    and z.layer == layer
                    and any(kicadgen._inside_polygon(*xy, q) for q in z.polygons)
                ):
                    joins.append((("pour", k), node))
        parent: dict[tuple, tuple] = {}

        def find(x: tuple) -> tuple:
            parent.setdefault(x, x)
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        rank = {"pad": 0, "pour": 1, "via": 2, "pt": 3}  # a pad names the node it joins, then a pour
        for a, b in joins:
            ra, rb = find(a), find(b)
            if ra != rb:
                lo, hi = sorted((ra, rb), key=lambda n: (rank[n[0]], n[1:]))
                parent[hi] = lo
        for k, p in enumerate(pads):
            self.pads.setdefault(find(("pad", k)), []).append(p)
        for k, z in enumerate(board.zones):
            if z.net == net:
                self.pours.setdefault(find(("pour", k)), z.layer)
        self.node_of = {id(p): find(("pad", k)) for k, p in enumerate(pads)}
        self.adj: dict[tuple, list[tuple[tuple, float, float, str]]] = {}
        for a, b, length, width, layer in edges:
            ra, rb = find(a), find(b)
            if ra != rb:
                self.adj.setdefault(ra, []).append((rb, length, width, layer))
                self.adj.setdefault(rb, []).append((ra, length, width, layer))
        for a in list(self.where):
            r = find(a)
            if r != a and r[0] == "pour":
                self.where.setdefault(r, self.where[a])

    def node(self, pad) -> tuple:
        return self.node_of[id(pad)]

    def reach(self, start: tuple, stops: set | frozenset = frozenset()) -> tuple[dict, dict]:
        """The shortest length of track from `start` to each node, not going on through a node in
        `stops`; and the edge each node is reached by."""
        dist, prev = {start: 0.0}, {}
        heap = [(0.0, 0, start)]
        count = 1
        while heap:
            d, _, node = heapq.heappop(heap)
            if d > dist[node] or (node in stops and node != start):
                continue
            for nxt, length, width, layer in self.adj.get(node, []):
                if d + length < dist.get(nxt, math.inf) - 1e-12:
                    dist[nxt] = d + length
                    prev[nxt] = (node, width, layer)
                    heapq.heappush(heap, (d + length, count, nxt))
                    count += 1
        return dist, prev

    @staticmethod
    def path(prev: dict, end: tuple) -> list[tuple[tuple, float, str]]:
        """The nodes from the start to `end`, each with the width and layer of the edge that reaches it."""
        out = []
        while end in prev:
            node, width, layer = prev[end]
            out.append((end, width, layer))
            end = node
        out.append((end, math.inf, ""))
        return out[::-1]


def _crossing(a, b, c, d) -> tuple[float, float] | None:
    """Where segments ab and cd cross inside both, or None."""
    rx, ry, sx, sy = b[0] - a[0], b[1] - a[1], d[0] - c[0], d[1] - c[1]
    den = rx * sy - ry * sx
    if abs(den) < 1e-12:
        return None
    t = ((c[0] - a[0]) * sy - (c[1] - a[1]) * sx) / den
    u = ((c[0] - a[0]) * ry - (c[1] - a[1]) * rx) / den
    if 0.0 < t < 1.0 and 0.0 < u < 1.0:
        return (a[0] + t * rx, a[1] + t * ry)
    return None


def _nearest(board: Board, pad, guard, data: dict) -> str:
    """Why the protector `guard` is not the nearest part to the connector's `pad`, or ''. The copper from
    the connector meets another part first; or a part stands as near to the TVS as the TVS to the
    connector, centre to centre; or lies as near along the copper."""
    protectors, connectors = data["protectors"], data["connectors"]
    me, name = _name(pad), _name(guard)
    others = [
        p for p in board.pads if p.net == pad.net and p.ref not in protectors and p.ref not in connectors
    ]
    copper = Copper(board, pad.net)
    start, end = copper.node(pad), copper.node(guard)
    dist, prev = copper.reach(start)
    if end in dist:
        for node, _, _ in copper.path(prev, end)[1:-1]:
            hit = [p for p in copper.pads.get(node, []) if p in others]
            if hit:
                return f"the copper from {me} reaches {_name(min(hit, key=_pad_order))} before {name}"
    reach = math.dist(guard.at, pad.at)
    near = [p for p in others if math.dist(p.at, guard.at) <= reach + NEAR]
    if near:
        x = min(near, key=lambda p: math.dist(p.at, guard.at))
        return (
            f"{_name(x)} stands {math.dist(x.at, guard.at):.3g} mm from {name}, "
            f"and {name} stands {reach:.3g} mm from {me}"
        )
    if end in dist:
        along, _ = copper.reach(end)
        near = [
            (along[copper.node(p)], p)
            for p in others
            if along.get(copper.node(p), math.inf) <= dist[end] + NEAR
        ]
        if near:
            d, x = min(near, key=lambda n: (n[0], _pad_order(n[1])))
            return (
                f"{_name(x)} lies {d:.3g} mm of copper from {name}, "
                f"and {name} lies {dist[end]:.3g} mm of copper from {me}"
            )
    return ""


def esd_findings(board: Board, pack: Pack, data: dict) -> list[Finding]:
    rules = {r["check"]: r for r in pack.rules}
    out: list[Finding] = []
    connectors, protectors = data["connectors"], data["protectors"]
    inside, ground = set(data.get("inside", [])), set(data["ground"])
    if not connectors:
        text = "esd: board-rules.json names no part under `connectors`, so no line is judged"
        out.append(Finding("not judged", text))
    for ref in sorted({p.ref for p in board.pads if is_connector(p)}, key=_natural):
        if ref not in connectors and ref not in inside:
            text = (
                f"esd {ref}: board-rules.json does not say whether it leaves the device "
                "(`connectors` or `inside`)"
            )
            out.append(Finding("not judged", text))
    grounded = {p.ref for p in board.pads if p.ref in protectors and p.net in ground}
    for ref in sorted(connectors, key=_natural):
        for pad in sorted((p for p in board.pads if p.ref == ref), key=_pad_order):
            if not pad.net or pad.net in ground or pad.net.startswith("unconnected-"):
                continue
            at = f"esd {ref}.{pad.number} {pad.net}"
            on_net = [p for p in board.pads if p.net == pad.net and p.ref in protectors]
            if not on_net:
                if "esd_protector" in rules:
                    rule = rules["esd_protector"]
                    out.append(Finding("fail", f"{at}: no protector on the net", pack.cite(rule["where"])))
                continue
            guards = [g for g in on_net if g.ref in grounded]
            if not guards:
                if "esd_protector" in rules:
                    refs = sorted({g.ref for g in on_net}, key=_natural)
                    verb = "stands on the net and has" if len(refs) == 1 else "stand on the net and have"
                    text = f"{at}: {', '.join(refs)} {verb} no pad on ground ({', '.join(sorted(ground))})"
                    out.append(Finding("fail", text, pack.cite(rules["esd_protector"]["where"])))
                continue
            guard = min(guards, key=lambda g: (math.dist(g.at, pad.at), _pad_order(g)))
            name = _name(guard)
            if "esd_nearest" in rules:
                why = _nearest(board, pad, guard, data)
                if why:
                    out.append(Finding("fail", f"{at}: {why}", pack.cite(rules["esd_nearest"]["where"])))
            if "esd_no_via" in rules:
                how = _joined(board, pad.net, pad, guard)
                if how == "via":
                    text = f"{at}: joined to {name} through a via"
                    out.append(Finding("fail", text, pack.cite(rules["esd_no_via"]["where"])))
                elif how == "none":
                    text = f"{at}: no copper joins it to {name}, so the path to the protector is not judged"
                    out.append(Finding("not judged", text))
    return out


# ---------------------------------------------------------------- the 3:1 rule


def _key(xy: tuple[float, float]) -> tuple[int, int]:
    return (round(xy[0] / NEAR), round(xy[1] / NEAR))


def traces(board: Board, net: str) -> list[tuple[str, str, float, float, list[str]]]:
    """The traces of `net`: for each 2 ends (pads and pours) the copper joins without passing another end,
    the shortest way along the tracks, through vias and joins and over overlaps. Each as its 2 ends (a name
    and a place), its length, its narrowest width, and the layers it runs on in order."""
    copper = Copper(board, net)

    def label(node: tuple, near: tuple) -> tuple:
        if node in copper.pads:
            p = min(copper.pads[node], key=_pad_order)
            return (0, _pad_order(p)), f"{_name(p)} {_p(p.at)}"
        xy = copper.where.get(near, (0.0, 0.0))
        return (1, copper.pours[node], _key(xy)), f"the {net} pour on {copper.pours[node]} {_p(xy)}"

    ends = set(copper.pads) | set(copper.pours)
    starts = sorted(ends, key=lambda n: label(n, n)[0])
    out, seen = [], set()
    for start in starts:
        dist, prev = copper.reach(start, ends)
        for end in ends:
            if end == start or end not in dist or frozenset((start, end)) in seen:
                continue
            seen.add(frozenset((start, end)))
            steps = copper.path(prev, end)
            widths = [w for _, w, _ in steps[1:]]
            if not widths or dist[end] <= NEAR:
                continue
            layers = list(dict.fromkeys(layer for _, _, layer in steps[1:]))
            a, b = label(start, steps[1][0]), label(end, steps[-2][0])
            if a[0] > b[0]:
                a, b = b, a
                layers.reverse()
            out.append((a[1], b[1], dist[end], min(widths), layers))
    return sorted(out)


def ratio_findings(board: Board, pack: Pack, rule: dict, data: dict) -> list[Finding]:
    if len(board.copper) != rule["copper_layers"]:
        return []
    out: list[Finding] = []
    for net in dict.fromkeys([*data["power"], *data["ground"]]):
        for a, b, length, width, layers in traces(board, net):
            if length > rule["most"] * width + 1e-9:
                on = layers[0] if len(layers) == 1 else ", ".join(layers[:-1]) + f" and {layers[-1]}"
                text = (
                    f"length to width {net} on {on} from {a} to {b}: {length:.3g} mm by {width:g} mm, "
                    f"{length / width:.3g} to 1, limit {rule['most']:g} to 1"
                )
                out.append(Finding("fail", text, pack.cite(rule["where"])))
    return out


# ---------------------------------------------------------------- the run


def findings(board: Board, pack: Pack, data: dict) -> list[Finding]:
    """The board held to every rule of the pack."""
    stated(board, pack, data)
    out: list[Finding] = []
    if any(r["check"].startswith("esd_") for r in pack.rules):
        out += esd_findings(board, pack, data)
    for rule in pack.rules:
        if rule["check"] == "length_to_width":
            out += ratio_findings(board, pack, rule, data)
    return out


def notes(board: Board, pack: Pack) -> list[str]:
    """What the pack's rules leave aside on this board, 1 line each."""
    out = []
    for rule in pack.rules:
        layers = rule.get("copper_layers")
        if layers and len(board.copper) != layers:
            out.append(
                f"{pack.name} {rule['id']}: the rule is for a board of {layers} copper layers, and this one "
                f"has {len(board.copper)}"
            )
    return out
