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
    gap     the board's gap is the one interfaces.json gives, when it gives one. KiCad's own
            diff_pair_gap rule reads only nets whose names end in _P/_N or +/-
    length  each net's track length (or its delay, where the document sets a delay) under the limit
    skew    the difference of the pair's 2 lengths under the limit
    vias    the vias of each net, where the document sets a count
    plane   every point of a fast track's centre line over the fill of each ground pour that bounds it:
            the nearest copper layer below and the nearest above that hold a ground pour. A pour of
            another net (a power plane) nearer to the track fails.

A ground pour is a pour of a net named GND or VSS, or whose name begins or ends with GND. Via barrels
are not counted in a length. A limit the documents set that the command does not judge, and a limit
they do not set, is printed as not judged, with the reason. Standard library only.
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

    def planes(self) -> set[str]:
        """The layers that hold a ground pour."""
        return {layer for layer, nets in self.pours.items() if any(is_ground(n) for n in nets)}


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


def _xy(node) -> tuple[float, float]:
    vals = kicadgen.atoms(node)
    return (kicadgen.num(vals[0]), kicadgen.num(vals[1]))


def _pts(node) -> list[tuple[float, float]]:
    pts = kicadgen.child(node, "pts")
    return [_xy(p) for p in kicadgen.children(pts, "xy")] if pts else []


def _text(node, head: str) -> str:
    c = kicadgen.child(node, head)
    return kicadgen.atoms(c)[0] if c is not None and kicadgen.atoms(c) else ""


def read_board(text: str) -> Board:
    root = kicadgen.parse(text)
    setup = kicadgen.child(root, "setup")
    stackup = kicadgen.child(setup, "stackup") if setup is not None else None
    stack: list[tuple] = []
    if stackup is not None:
        for layer in kicadgen.children(stackup, "layer"):
            kind = _text(layer, "type")
            thick = _text(layer, "thickness")
            name = kicadgen.atoms(layer)[0]
            if kind == "copper":
                stack.append(("copper", name, kicadgen.num(thick)))
            elif kind in ("core", "prepreg") and thick:
                er = _text(layer, "epsilon_r")
                stack.append(("dielectric", kicadgen.num(thick), kicadgen.num(er) if er else None, name))
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
    for item in kicadgen.children(root, "via"):
        net = _text(item, "net")
        vias[net] = vias.get(net, 0) + 1
        x, y = _xy(kicadgen.child(item, "at"))
        holes.append((net, x, y, kicadgen.num(_text(item, "size")) / 2))
    fills: dict[str, list] = {}
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
        for pad in kicadgen.children(item, "pad"):
            n = _text(pad, "net")
            if n:
                nets.add(n)
            if "thru_hole" not in kicadgen.atoms(pad):
                continue  # only a hole through the board makes a hole in an inner plane
            px, py = _xy(kicadgen.child(pad, "at"))
            sx, sy = _xy(kicadgen.child(pad, "size"))
            x = fx + px * math.cos(angle) + py * math.sin(angle)
            y = fy - px * math.sin(angle) + py * math.cos(angle)
            holes.append((n, x, y, math.hypot(sx, sy) / 2))
    return Board(stack, tracks, vias, fills, pours, nets, holes, margins)


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
    n_chords = [
        (a, b, t.width)
        for t in board.tracks
        if t.net == nets[1] and t.layer == layer
        for a, b in zip(t.points, t.points[1:], strict=False)
    ]
    runs: list[tuple[float, float, tuple, tuple]] = []
    for track in (t for t in board.tracks if t.net == nets[0] and t.layer == layer):
        for (ax, ay), (bx, by) in zip(track.points, track.points[1:], strict=False):
            length = math.hypot(bx - ax, by - ay)
            if length < 1e-9:
                continue
            ux, uy = (bx - ax) / length, (by - ay) / length
            near = []
            for (cx, cy), (dx, dy), width in n_chords:
                other = math.hypot(dx - cx, dy - cy)
                if other < 1e-9 or abs(ux * (dy - cy) - uy * (dx - cx)) / other > PARALLEL:
                    continue
                s0 = (cx - ax) * ux + (cy - ay) * uy
                s1 = (dx - ax) * ux + (dy - ay) * uy
                lo, hi = max(0.0, min(s0, s1)), min(length, max(s0, s1))
                if hi - lo > 1e-6:
                    apart = abs((cy - ay) * ux - (cx - ax) * uy)
                    near.append((lo, hi, apart, apart - (track.width + width) / 2))
            cuts = sorted({c for lo, hi, _, _ in near for c in (lo, hi)})
            for s, e in zip(cuts, cuts[1:], strict=False):
                over = [n for n in near if n[0] <= s + 1e-9 and n[1] >= e - 1e-9]
                if not over:
                    continue
                gap = round(min(over, key=lambda n: n[2])[3], READ)
                first = (round(ax + ux * s, 3), round(ay + uy * s, 3))
                last = (round(ax + ux * e, 3), round(ay + uy * e, 3))
                if runs and runs[-1][0] == gap and runs[-1][3] == first:
                    runs[-1] = (gap, runs[-1][1] + e - s, runs[-1][2], last)
                else:
                    runs.append((gap, e - s, first, last))
    return runs


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
        for gap, total in totals.items():
            if gap != main:
                first = next(r for r in runs if r[0] == gap)
                report.findings.append(
                    Finding(
                        "not judged",
                        "gap",
                        f"{label} on {layer}: {total:.4g} mm of the pair runs {gap:g} mm apart, from "
                        f"{first[2]} to {first[3]} mm; the width is judged at {main:g} mm, the gap over the "
                        "most of its length",
                    )
                )
        if declared is not None:
            if abs(declared - main) > 0.5 * 10**-READ:
                report.findings.append(
                    Finding(
                        "fail",
                        "gap",
                        f"{label} on {layer}: the 2 tracks run {main:g} mm apart, edge to edge, over "
                        f"{totals[main]:.4g} mm; limit {declared:g} mm, the gap interfaces.json gives and "
                        "the KiCad rule is written for",
                    )
                )
            else:
                report.findings.append(
                    Finding(
                        "held",
                        "gap",
                        f"{label} on {layer}: the 2 tracks run {main:g} mm apart over {totals[main]:.4g} mm, "
                        "the gap interfaces.json gives",
                    )
                )
        if main <= 0:
            each_net("width", f"the 2 tracks touch or overlap ({main:g} mm apart)")
            continue
        try:
            section, refs = section_for(board, layer)
        except NotJudged as exc:
            each_net("width", str(exc))
            continue
        if section is None:
            each_net("width", "no ground pour on any copper layer to stand as its plane")
            continue
        section.update({"widths": [0.3, 0.3], "gap": main})
        band = "min" in imp and "max" in imp
        req = {"section": section, "target": imp["nominal"]}
        if band:
            req.update({"low": imp["min"], "high": imp["max"]})
        ans = solver(req)
        if "error" in ans:
            each_net("width", ans["error"])
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
        if gmin and gmax:
            blocks.append(
                _rule_block(
                    f"{label} gap {layer}",
                    layer,
                    cond,
                    f"diff_pair_gap (min {gmin:.4f}mm) (opt {opt_gap:.4f}mm) (max {gmax:.4f}mm)",
                )
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

    # ---- length, or delay
    lengths = {n: net_length(board, n) for n in nets}
    vias = sum(board.vias.get(n, 0) for n in nets)
    tail = f" ({vias} via barrels not counted)" if vias else ""
    if "max" in limits.get("length", {}):
        lim = limits["length"]
        blocks.append(f"# {label} length: {cite(spec, lim)}")
        blocks.append(_rule_block(f"{label} length", None, cond, f"length (max {lim['max']:.4f}mm)"))
        for net, value in lengths.items():
            text = f"{net.lstrip('/')} is {value:.4f} mm long{tail}; limit {lim['max']:g} mm; "
            text += f"source: {cite(spec, lim)}"
            report.findings.append(Finding("fail" if value > lim["max"] else "held", "length", text))
    elif "max" in limits.get("delay", {}):
        lim = limits["delay"]
        for net in nets:
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
    if "max" in lim:
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
        for layer in sorted({t.layer for t in board.tracks if t.net == net}):
            report.findings += _plane(board, spec, lim, net, layer)


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
