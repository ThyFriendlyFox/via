#!/usr/bin/env python3
"""layoutrules — a board held to the layout rules a maker's note states.

A layout pack (`rules/board/<pack>.json`, `"kind": "layout"`) names a maker's note and the rules of it the
workcenter judges, each with its section and page. A project names its layout packs in `board-rules.json`
under `layout`, beside the voltage pack of `tools/boardrules.py`, and states what the board file cannot
say: which connectors leave the device, which parts protect against ESD, which nets are ground, which are
power. The DRC gate prints each finding on the same line as the voltage pack's. Standard library only.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

import boardrules
import ratings
from boardrules import Board, Finding, _p
from ratings import Refusal

CHECKS = {
    "esd_protector": ("connectors", "protectors", "ground"),
    "esd_nearest": ("connectors", "protectors", "ground"),
    "esd_no_via": ("connectors", "protectors", "ground"),
    "length_to_width": ("power",),
}
CONNECTOR_RE = re.compile(r"^[JP]\d+$")  # IEEE 315's letters for a connector and a plug
NEAR = 1e-3


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
            ratings._number(f"{at}: copper_layers", rule.get("copper_layers"), 1, None, None)
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


def esd_findings(board: Board, pack: Pack, data: dict) -> list[Finding]:
    rules = {r["check"]: r for r in pack.rules}
    out: list[Finding] = []
    connectors, protectors = data["connectors"], data["protectors"]
    inside, ground = set(data.get("inside", [])), set(data["ground"])
    for ref in sorted({p.ref for p in board.pads if CONNECTOR_RE.match(p.ref)}):
        if ref not in connectors and ref not in inside:
            text = (
                f"esd {ref}: board-rules.json does not say whether it leaves the device "
                "(`connectors` or `inside`)"
            )
            out.append(Finding("not judged", text))
    for ref in sorted(connectors):
        mine = [p for p in board.pads if p.ref == ref]
        for pad in sorted(
            mine, key=lambda p: [int(s) if s.isdigit() else s for s in re.split(r"(\d+)", p.number)]
        ):
            if not pad.net or pad.net in ground or pad.net.startswith("unconnected-"):
                continue
            at = f"esd {ref}.{pad.number} {pad.net}"
            guards = [p for p in board.pads if p.net == pad.net and p.ref in protectors]
            if not guards:
                if "esd_protector" in rules:
                    rule = rules["esd_protector"]
                    out.append(Finding("fail", f"{at}: no protector on the net", pack.cite(rule["where"])))
                continue
            guard = min(guards, key=lambda g: math.dist(g.at, pad.at))
            reach = math.dist(guard.at, pad.at)
            name = f"{guard.ref}.{guard.number}"
            if "esd_nearest" in rules:
                others = [
                    p
                    for p in board.pads
                    if p.net == pad.net and p.ref not in protectors and p.ref not in connectors
                ]
                near = [p for p in others if math.dist(p.at, guard.at) <= reach + NEAR]
                if near:
                    x = min(near, key=lambda p: math.dist(p.at, guard.at))
                    text = (
                        f"{at}: {x.ref}.{x.number} stands {math.dist(x.at, guard.at):.3g} mm from {name}, "
                        "and "
                        f"{name} stands {reach:.3g} mm from {ref}.{pad.number}"
                    )
                    out.append(Finding("fail", text, pack.cite(rules["esd_nearest"]["where"])))
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


def runs(board: Board, net: str, layer: str) -> list[tuple[list[tuple[float, float]], float, float]]:
    """The runs of track of `net` on `layer`: segments joined end to end where no pad or via stands and
    no third segment meets. Each run as its points, its length and its narrowest width."""
    segs = [t for t in board.tracks if t.net == net and t.layer == layer]
    ends: dict[tuple[int, int], list[int]] = {}
    for i, t in enumerate(segs):
        for xy in (t.start, t.end):
            ends.setdefault(_key(xy), []).append(i)
    stops = [(p.at, p.reach) for p in board.pads if p.net == net and layer in p.layers]
    stops += [(v.at, v.size / 2) for v in board.vias if v.net == net and layer in v.layers]

    def through(xy: tuple[float, float]) -> bool:
        """A run goes on through this end: 2 segments meet here, and no pad or via."""
        return len(ends[_key(xy)]) == 2 and not any(math.dist(xy, at) <= reach + NEAR for at, reach in stops)

    seen: set[int] = set()
    out = []
    order = sorted(range(len(segs)), key=lambda i: (through(segs[i].start) and through(segs[i].end), i))
    for first in order:
        if first in seen:
            continue
        seen.add(first)
        t = segs[first]
        a, b = (t.start, t.end) if not through(t.start) or through(t.end) else (t.end, t.start)
        points, width = [a, b], t.width
        while through(points[-1]):
            nxt = next((i for i in ends[_key(points[-1])] if i not in seen), None)
            if nxt is None:
                break
            seen.add(nxt)
            s = segs[nxt]
            points.append(s.end if _key(s.start) == _key(points[-1]) else s.start)
            width = min(width, s.width)
        length = sum(math.dist(p, q) for p, q in zip(points, points[1:], strict=False))
        out.append((points, length, width))
    return out


def ratio_findings(board: Board, pack: Pack, rule: dict, data: dict) -> list[Finding]:
    if len(board.copper) != rule["copper_layers"]:
        return []
    out: list[Finding] = []
    for net in data["power"]:
        for layer in board.copper:
            for points, length, width in runs(board, net, layer):
                if length > rule["most"] * width + 1e-9:
                    text = (
                        f"length to width {net} on {layer} from {_p(points[0])} to {_p(points[-1])}: "
                        f"{length:.3g} mm by {width:g} mm, {length / width:.3g} to 1, "
                        f"limit {rule['most']:g} to 1"
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
