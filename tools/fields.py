#!/usr/bin/env python3
"""fields — the nets a design names as critical, simulated by a field solver from the board file.

A project's fields.json names groups of nets (a line, a pair, an antenna's feed), the band each is used
in and the limits each is held to, every limit with the document it comes from. For each group this
module writes a model from the .kicad_pcb: the copper of the group's nets as sheets at their layers'
heights, the planes of the reference net, the dielectrics of the stack-up, a lumped port at each end
of each net and a mesh made from the geometry. An engine turns the model into S-parameters; the
measures (impedance, return loss, insertion loss, near- and far-end coupling) are held to the limits
as the SIM gate holds a deck's measures.

The engine is a separate program behind 1 interface: `prepare` writes its input from the model,
`run` runs it, and `column` reads back the S-parameters of 1 driven port, S[receiver][driven] over the
model's frequencies. openEMS is the first engine; it runs as its own process and none of its code is
in this repository. Another solver takes its place by the same 3 functions and its name in
fields.json's `engine`.

Standard library only: `tools/workcenter` imports this module and runs on a bare python3.
"""

from __future__ import annotations

import bisect
import cmath
import json
import math
import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

from kicadgen import Q, parse

C0 = 299792458.0  # m/s, exact by the definition of the metre (SI Brochure, 9th edition, 2019, 2.3.1)
MU0 = 4e-7 * math.pi  # H/m; CODATA 2018 gives 1.00000000055 times this
EPS0 = 1.0 / (MU0 * C0 * C0)

MEASURES = ("fext_db", "impedance_ohm", "insertion_loss_db", "next_db", "return_loss_db")
COUPLING = ("fext_db", "next_db")
SETTINGS = {
    "margin_mm": 3.0,  # copper to the box's side, and air above the top copper and below the bottom
    "cells_per_wavelength": 20,  # the largest cell is the shortest wavelength in the stack over this
    "cells_across_width": 3,  # cells across a straight track's width
    "cells_per_dielectric": 4,  # cells through each dielectric layer of the box
    "port_ohm": 50.0,
    "frequencies": 201,
    "end_criteria_db": -40.0,  # the run stops when the energy in the box falls this far
    "absorbing_cells": 8,  # cells of absorbing layer (openEMS: PML_8) outside the box on every side
    "max_timesteps": 200000,
    "timeout_s": 3600,
}
# The settings that count something, with the least each takes: a band of 1 frequency has no step.
COUNTS = {
    "cells_across_width": 1,
    "cells_per_dielectric": 1,
    "frequencies": 2,
    "absorbing_cells": 1,
    "max_timesteps": 1,
}


class Refusal(ValueError):
    """A file the command does not take: the message names the file, the place in it and what is wrong."""


# ---------------------------------------------------------------- the board


@dataclass
class Track:
    net: str
    layer: str
    a: tuple[float, float]
    b: tuple[float, float]
    width: float


@dataclass
class Via:
    net: str
    at: tuple[float, float]
    drill: float
    layers: tuple[str, str]


@dataclass
class Board:
    path: Path
    copper_z: dict[str, float]  # mm above the bottom copper; copper is a sheet
    dielectrics: list[tuple[float, float, float, float]]  # (z0, z1, epsilon_r, loss tangent), bottom up
    tracks: list[Track] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    # (net, layers, {layer: [polygon, ...]}): the zone's fill on each layer where it is filled, else
    # its outline
    zones: list[tuple[str, tuple[str, ...], dict]] = field(default_factory=list)
    # REF.PAD: (x, y, net, reach); reach is half the pad's diagonal, the farthest a point of it lies
    pads: dict[str, tuple[float, float, str, float]] = field(default_factory=dict)


def _child(node: list, head: str) -> list | None:
    return next((c for c in node[1:] if isinstance(c, list) and c and c[0] == head), None)


def _children(node: list, head: str) -> list[list]:
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == head]


def _float(value, what: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        raise Refusal(f"{what} is {str(value)!r}, not a number") from None


def _xy(node: list | None) -> tuple[float, float]:
    if node is None or len(node) < 3:
        raise Refusal(f"a {node[0] if node else 'point'} without its 2 numbers")
    return _float(node[1], f"`{node[0]}`"), _float(node[2], f"`{node[0]}`")


def _num(node: list, head: str) -> float | None:
    found = _child(node, head)
    return _float(found[1], f"`{head}`") if found is not None and len(found) > 1 else None


def _layer(node: list) -> str:
    found = _child(node, "layer")
    if found is None or len(found) < 2:
        raise Refusal("no `layer`")
    return str(found[1])


def _rotate(dx: float, dy: float, degrees: float) -> tuple[float, float]:
    """A footprint's local offset on the board: KiCad turns counter-clockwise on a screen whose y grows
    downward, so (1, 0) at 90 degrees is (0, -1)."""
    r = math.radians(degrees)
    return dx * math.cos(r) + dy * math.sin(r), -dx * math.sin(r) + dy * math.cos(r)


def _arc_points(a, m, b, n: int = 8) -> list[tuple[float, float]]:
    """n chords along the circle through a, m and b, from a to b by way of m."""
    (ax, ay), (mx, my), (bx, by) = a, m, b
    d = 2 * (ax * (my - by) + mx * (by - ay) + bx * (ay - my))
    if abs(d) < 1e-12:
        return [a, b]
    ux = ((ax**2 + ay**2) * (my - by) + (mx**2 + my**2) * (by - ay) + (bx**2 + by**2) * (ay - my)) / d
    uy = ((ax**2 + ay**2) * (bx - mx) + (mx**2 + my**2) * (ax - bx) + (bx**2 + by**2) * (mx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    ta, tm, tb = (math.atan2(p[1] - uy, p[0] - ux) for p in (a, m, b))
    sweep = (tb - ta) % (2 * math.pi)
    if (tm - ta) % (2 * math.pi) > sweep:  # m is not on the counter-clockwise way from a to b
        sweep -= 2 * math.pi
    pts = [
        (ux + r * math.cos(ta + sweep * k / n), uy + r * math.sin(ta + sweep * k / n)) for k in range(n + 1)
    ]
    pts[0], pts[-1] = a, b
    return pts


def _pts(node: list | None) -> list[tuple[float, float]]:
    """The corners of a zone's outline or fill: its xy points, an arc as chords."""
    out: list[tuple[float, float]] = []
    for c in node[1:] if node is not None else []:
        if isinstance(c, list) and c and c[0] == "xy":
            out.append(_xy(c))
        elif isinstance(c, list) and c and c[0] == "arc":
            arc = _arc_points(_xy(_child(c, "start")), _xy(_child(c, "mid")), _xy(_child(c, "end")))
            out.extend(arc if not out or _key(out[-1]) != _key(arc[0]) else arc[1:])
    return out


def _rings(poly) -> list[list]:
    """The closed rings of a polygon: its points, rings split by None (an outline and its holes)."""
    rings, ring = [], []
    for p in poly:
        if p is None:
            rings.append(ring)
            ring = []
        else:
            ring.append(p)
    return [r for r in rings + [ring] if r]


def _in_polygon(q, poly, tol: float = 1e-7) -> bool:
    """Even-odd over every ring: whether a point lies inside a polygon. A hole is a ring of its own
    (after a None) or, as KiCad writes a fill, joined to its outline by a slit of 2 edges on 1 line.
    A point within `tol` mm of an edge is inside, at every edge alike (KiCad's unit is 1 nm): the
    crossing count alone took a point on a left edge and left one on a right edge. A negative `tol`
    takes a point within -tol of an edge as outside: strictly inside."""
    x, y = q
    inside = False
    for ring in _rings(poly):
        for (ax, ay), (bx, by) in zip(ring, ring[1:] + ring[:1], strict=True):
            dx, dy = bx - ax, by - ay
            span = dx * dx + dy * dy
            r = min(1.0, max(0.0, ((x - ax) * dx + (y - ay) * dy) / span)) if span > 0 else 0.0
            if math.hypot(x - ax - r * dx, y - ay - r * dy) <= abs(tol):
                return tol >= 0
            if (ay > y) != (by > y) and x < ax + (y - ay) * dx / dy:
                inside = not inside
    return inside


def read_board(path: Path) -> Board:
    """The parts of a .kicad_pcb a field model needs: the stack-up, and the tracks, arcs, vias, zones
    and pads with their nets. KiCad 10 names an item's net by its name; KiCad 6 to 9 by a number in the
    board's net table."""
    path = Path(path)
    try:
        root = parse(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise Refusal(f"{path.name}: not read as a KiCad board: {exc}") from exc
    if not root or root[0] != "kicad_pcb":
        raise Refusal(f"{path.name}: not a KiCad board")
    table = {c[1]: str(c[2]) for c in _children(root, "net") if len(c) > 2}

    def net_of(node: list) -> str:
        named = _child(node, "net_name")
        if named is not None and len(named) > 1:
            return str(named[1])
        found = _child(node, "net")
        if found is None or len(found) < 2:
            return ""
        value = found[1]
        if isinstance(value, Q):
            return str(value)
        return table.get(value, "") if len(found) == 2 else str(found[2])

    setup = _child(root, "setup")
    stack = _child(setup, "stackup") if setup is not None else None
    if stack is None:
        raise Refusal(f"{path.name}: the board has no stack-up (Board Setup, Physical Stackup)")
    layers = _children(stack, "layer")

    def each(kind: str, nodes: list, read) -> None:
        """read(node) for each item; a refusal names the file and the item, by name or by count."""
        for i, node in enumerate(nodes, 1):
            try:
                read(node)
            except Refusal as exc:
                name = f"{kind} {node[1]}" if kind == "stack-up layer" and len(node) > 1 else f"{kind} {i}"
                raise Refusal(f"{path.name}: {name}: {exc}") from None

    def thickness(ly: list) -> None:
        kind = _child(ly, "type")
        if kind is not None and len(kind) > 1 and kind[1] in ("core", "prepreg"):
            totals.append(_num(ly, "thickness") or 0.0)

    totals: list[float] = []
    each("stack-up layer", layers, thickness)
    copper_z, diel, at_z = {}, [], [sum(totals)]

    def stack_layer(ly: list) -> None:
        z = at_z[0]
        kind = _child(ly, "type")
        kind = str(kind[1]) if kind is not None and len(kind) > 1 else ""
        if kind == "copper":
            copper_z[str(ly[1])] = z
        elif kind in ("core", "prepreg"):
            t, er, tand = _num(ly, "thickness"), _num(ly, "epsilon_r"), _num(ly, "loss_tangent")
            if t is None or er is None:
                raise Refusal("no thickness or no epsilon_r")
            diel.append((z - t, z, er, tand or 0.0))
            at_z[0] = z - t

    each("stack-up layer", layers, stack_layer)
    shift = min(copper_z.values(), default=0.0)
    copper_z = {k: round(v - shift, 9) for k, v in copper_z.items()}
    diel = sorted((round(a - shift, 9), round(b - shift, 9), er, tand) for a, b, er, tand in diel)
    board = Board(path=path, copper_z=copper_z, dielectrics=diel)

    def segment(seg: list) -> None:
        layer, width = _layer(seg), _num(seg, "width") or 0.0
        a, b = _xy(_child(seg, "start")), _xy(_child(seg, "end"))
        board.tracks.append(Track(net_of(seg), layer, a, b, width))

    def arc(node: list) -> None:
        pts = _arc_points(_xy(_child(node, "start")), _xy(_child(node, "mid")), _xy(_child(node, "end")))
        layer, width, net = _layer(node), _num(node, "width") or 0.0, net_of(node)
        board.tracks.extend(Track(net, layer, p, q, width) for p, q in pairwise(pts))

    def via(node: list) -> None:
        names = _child(node, "layers")
        pair = (str(names[1]), str(names[2])) if names is not None and len(names) > 2 else ("F.Cu", "B.Cu")
        board.vias.append(Via(net_of(node), _xy(_child(node, "at")), _num(node, "drill") or 0.0, pair))

    each("segment", _children(root, "segment"), segment)
    each("arc", _children(root, "arc"), arc)
    each("via", _children(root, "via"), via)
    each("zone", _children(root, "zone"), lambda zone: _read_zone(zone, board, net_of))
    each(
        "footprint",
        _children(root, "footprint") + _children(root, "module"),
        lambda fp: _read_pads(fp, board, net_of),
    )
    return board


def _read_zone(zone: list, board: Board, net_of) -> None:
    """A zone's net, layers and shape on each layer, onto the board; a keepout is no copper."""
    if _child(zone, "keepout") is not None:
        return
    one, many = _child(zone, "layer"), _child(zone, "layers")
    names = tuple(str(x) for x in (many[1:] if many is not None else one[1:] if one is not None else []))
    shapes: dict[str, list] = {}
    for filled in _children(zone, "filled_polygon"):
        ly = _child(filled, "layer")
        if ly is not None and len(ly) > 1:
            shapes.setdefault(str(ly[1]), []).append(_pts(_child(filled, "pts")))
    # The first `polygon` is the zone's outline, each later one a cutout: a hole of it (KiCad 10 loads
    # and saves a zone so). A hole follows the outline after a None (`_rings`).
    rings = [_pts(_child(p, "pts")) for p in _children(zone, "polygon")]
    outline = [rings[0] + [q for hole in rings[1:] for q in [None, *hole]]] if rings else []
    for ly in names:
        if ly not in shapes:
            shapes[ly] = outline
    board.zones.append((net_of(zone), names, shapes))


def _read_pads(fp: list, board: Board, net_of) -> None:
    """A footprint's pads onto the board, as REF.PAD: where each stands, its net and its reach."""
    at = _child(fp, "at")
    fx, fy = _xy(at)
    rot = _float(at[3], "`at`'s angle") if len(at) > 3 else 0.0
    ref = next((str(p[2]) for p in _children(fp, "property") if len(p) > 2 and p[1] == "Reference"), None)
    ref = ref or next((str(t[2]) for t in _children(fp, "fp_text") if len(t) > 2 and t[1] == "reference"), "")
    for pad in _children(fp, "pad"):
        dx, dy = _xy(_child(pad, "at"))
        ox, oy = _rotate(dx, dy, rot)
        size = _child(pad, "size")
        reach = math.hypot(*_xy(size)) / 2 if size is not None and len(size) > 2 else 0.0
        board.pads[f"{ref}.{pad[1] if len(pad) > 1 else ''}"] = (fx + ox, fy + oy, net_of(pad), reach)


# ---------------------------------------------------------------- fields.json


def _json(path: Path) -> object:
    def once(pairs):
        seen = {}
        for key, value in pairs:
            if key in seen:
                raise Refusal(f"{path.name}: `{key}` stands 2 times")
            seen[key] = value
        return seen

    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=once)
    except OSError as exc:
        raise Refusal(f"{path}: {exc.strerror}") from exc
    except ValueError as exc:
        if isinstance(exc, Refusal):
            raise
        raise Refusal(f"{path.name}: not JSON: {exc}") from exc


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def read_spec(path: Path) -> dict:
    """fields.json, with its defaults filled in. Every limit names its measure, its net, a min or a max
    and its source; a coupling limit also names the net it comes `from`."""
    path = Path(path)
    data = _json(path)
    where = path.name
    if not isinstance(data, dict):
        raise Refusal(f"{where}: an object is expected")
    unknown = set(data) - {"engine", "reference", "settings", "groups"}
    if unknown:
        raise Refusal(f"{where}: `{sorted(unknown)[0]}` is not a key fields.json takes")
    engine = data.get("engine", "openems")
    if engine not in ENGINES:
        raise Refusal(f"{where}: engine `{engine}` is none of {', '.join(ENGINES)}")
    settings = dict(SETTINGS)
    given = data.get("settings", {})
    if not isinstance(given, dict):
        raise Refusal(f"{where}: `settings` is an object of names and numbers, not {given!r}")
    for key, value in given.items():
        if key not in SETTINGS:
            raise Refusal(f"{where}: setting `{key}` is none of {', '.join(SETTINGS)}")
        if key in COUNTS:
            least = COUNTS[key]
            if not (_number(value) and value == int(value) and value >= least):
                raise Refusal(f"{where}: setting `{key}` is {value!r}, not a whole number of {least} or more")
            value = int(value)
        elif key == "end_criteria_db":
            if not _number(value) or value >= 0:
                raise Refusal(f"{where}: setting `{key}` is {value!r}, not a number below 0")
        elif not _number(value) or value <= 0:
            raise Refusal(f"{where}: setting `{key}` is {value!r}, not a number above 0")
        settings[key] = value
    if not isinstance(data.get("reference", "GND"), str) or not data.get("reference", "GND"):
        raise Refusal(f"{where}: `reference` is the name of the reference net, not {data['reference']!r}")
    groups = data.get("groups")
    if not isinstance(groups, list):
        raise Refusal(f"{where}: `groups` is a list of groups")
    names = set()
    for g in groups:
        name = g.get("name") if isinstance(g, dict) else None
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_.+-]+", name) or name in names:
            raise Refusal(f"{where}: a group's `name` is a word of letters, digits and _.+- used 1 time")
        names.add(name)
        at = f"{where}: group {name}"
        extra = set(g) - {"name", "nets", "kind", "ports", "band_ghz", "limits"}
        if extra:
            raise Refusal(f"{at}: `{sorted(extra)[0]}` is not a key a group takes")
        nets = g.get("nets")
        if not isinstance(nets, list) or not nets or not all(isinstance(n, str) and n for n in nets):
            raise Refusal(f"{at}: `nets` is a list of net names")
        kind = g.setdefault("kind", "lines")
        if kind not in ("lines", "antenna"):
            raise Refusal(f"{at}: kind `{kind}` is none of lines, antenna")
        ports = g.get("ports")
        if ports is not None and (not isinstance(ports, list) or not all(isinstance(p, str) for p in ports)):
            raise Refusal(f"{at}: `ports` is a list of pads, REF.PAD")
        if kind == "antenna" and (len(nets) != 1 or not ports or len(ports) != 1):
            raise Refusal(f"{at}: an antenna is 1 net fed at 1 pad: `nets` of 1 and `ports` of 1")
        band = g.get("band_ghz")
        if not (
            isinstance(band, list) and len(band) == 2 and all(map(_number, band)) and 0 < band[0] < band[1]
        ):
            raise Refusal(f"{at}: `band_ghz` is [low, high] in GHz, 0 < low < high")
        limits = g.get("limits", [])
        if not isinstance(limits, list):
            raise Refusal(f"{at}: `limits` is a list")
        for lim in limits:
            m = lim.get("measure") if isinstance(lim, dict) else None
            if m not in MEASURES:
                raise Refusal(f"{at}: measure `{m}` is none of {', '.join(MEASURES)}")
            net = lim.get("net")
            if net not in nets:
                raise Refusal(f"{at}: {m}: net `{net}` is not one of the group's nets")
            extra = set(lim) - {"measure", "net", "from", "min", "max", "source"}
            if extra:
                raise Refusal(f"{at}: {m} of {net}: `{sorted(extra)[0]}` is not a key a limit takes")
            if m in COUPLING and (lim.get("from") not in nets or lim.get("from") == net):
                raise Refusal(f"{at}: {m} of {net} names `from`, another net of the group")
            if m not in COUPLING and "from" in lim:
                raise Refusal(f"{at}: {m} of {net} takes no `from`")
            if m in COUPLING or m == "insertion_loss_db":
                if kind == "antenna":
                    raise Refusal(f"{at}: an antenna has 1 port: {m} is not measured")
            if "min" not in lim and "max" not in lim:
                raise Refusal(f"{at}: {m} of {net} has neither min nor max")
            for k in ("min", "max"):
                if k in lim and not _number(lim[k]):
                    raise Refusal(f"{at}: {m} of {net}: {k} is {lim[k]!r}, not a number")
            if "min" in lim and "max" in lim and lim["min"] > lim["max"]:
                raise Refusal(f"{at}: {m} of {net}: min {lim['min']} is above max {lim['max']}")
            source = lim.get("source")
            if not isinstance(source, str) or not source.strip():
                raise Refusal(f"{at}: {m} of {net} has no source: name the document, clause and page")
    reference = data.get("reference", "GND")
    return {
        "engine": engine,
        "reference": reference,
        "settings": settings,
        "groups": groups,
        "file": str(path),
    }


# ---------------------------------------------------------------- the mesh


def max_cell_mm(f_max_hz: float, er_max: float, cells_per_wavelength: float) -> float:
    """The shortest wavelength in the stack, in mm, over the cells it is cut in."""
    return C0 / (f_max_hz * math.sqrt(er_max)) / cells_per_wavelength * 1000.0


def _grade(length: float, s_a: float, s_b: float, max_cell: float, ratio: float) -> list[float]:
    """The cells of 1 gap between fixed lines. From each end the cells grow by `ratio` from the
    smallest gap at that line, the smaller next cell first, up to max_cell; the middle is cut in equal
    cells no larger than max_cell and `ratio` times the smaller last grown cell. A middle smaller than
    a grown cell over `ratio` is joined with the last grown cell and cut again."""
    if length <= max_cell + 1e-12 and length <= ratio * min(s_a, s_b) + 1e-12:
        return [length]
    left, right, total = [], [], 0.0
    c_l, c_r = s_a * ratio, s_b * ratio
    while True:
        side = min((c, k) for k, c in enumerate((c_l, c_r)))
        c, k = side
        if c >= max_cell or total + c > length + 1e-12:
            break
        (left if k == 0 else right).append(c)
        total += c
        if k == 0:
            c_l *= ratio
        else:
            c_r *= ratio
    middle = length - total
    lasts = [run[-1] for run in (left, right) if run]
    if lasts and middle < min(lasts) / ratio:
        run = left if left and (not right or left[-1] <= right[-1]) else right
        middle += run.pop()
        lasts = [r[-1] for r in (left, right) if r] or [middle]
    top = min([max_cell] + [x * ratio for x in lasts]) if lasts else max_cell
    n = max(1, math.ceil(middle / top - 1e-9)) if middle > 1e-12 else 0
    return left + [middle / n] * n + right[::-1]


def mesh_lines(
    fixed: list[float], max_cell: float, ratio: float = 1.5, min_cell: float = 1e-6, keep=()
) -> list[float]:
    """Mesh lines through every fixed line, no cell larger than max_cell. A line in `keep` (a port's
    bounds) always stays. Another fixed line closer than min_cell to a line already taken is dropped:
    the solver's time step falls with the least cell. In each gap between fixed lines the cells grow by
    `ratio` from the smaller gap at each end (`_grade`). Where 2 runs of cells meet, 2 neighbours can
    differ by up to 2 times. Every fixed line taken is a line of the mesh, to the digit."""
    kept = sorted(set(round(v, 9) for v in keep))
    merged = list(kept)
    for v in sorted(set(round(v, 9) for v in fixed) - set(kept)):
        k = bisect.bisect_left(merged, v)
        near = [merged[i] for i in (k - 1, k) if 0 <= i < len(merged)]
        if all(abs(v - n) >= min_cell - 1e-12 for n in near):
            merged.insert(k, v)
    gaps = [b - a for a, b in pairwise(merged)]
    local = [min([g for g in gaps[max(0, k - 1) : k + 1]] + [max_cell]) for k in range(len(merged))]
    out = [merged[0]]
    for k, (a, b) in enumerate(pairwise(merged)):
        for c in _grade(b - a, local[k], local[k + 1], max_cell, ratio)[:-1]:
            out.append(out[-1] + c)
        out.append(b)  # held exactly: a sheet on a fixed line lies on a line of the mesh
    return [round(v, 9) for v in out]


# ---------------------------------------------------------------- the model


def _key(p) -> tuple[float, float]:
    return (round(p[0], 4), round(p[1], 4))


def _octagon(c, r) -> list[list[float]]:
    rr = r / math.cos(math.pi / 8)  # flats at r
    angles = [math.pi / 8 + k * math.pi / 4 for k in range(8)]
    return [[c[0] + rr * math.cos(a), c[1] + rr * math.sin(a)] for a in angles]


def _inside(q, t: Track, tol: float = 1e-6) -> bool:
    """Whether a point lies on a track's rectangle: along it between its ends, across it within half
    its width."""
    (ax, ay), (bx, by) = t.a, t.b
    length = math.hypot(bx - ax, by - ay)
    if length < 1e-9:
        return False
    ux, uy = (bx - ax) / length, (by - ay) / length
    along = (q[0] - ax) * ux + (q[1] - ay) * uy
    across = -(q[0] - ax) * uy + (q[1] - ay) * ux
    return -tol <= along <= length + tol and abs(across) <= t.width / 2 + tol


def _pt(p) -> str:
    return f"({p[0]:g}, {p[1]:g})"


def _cell_across(width: float, k: int) -> float:
    """The cell across a track of `width` cut in `k` cells with its edges a third of a cell inside."""
    return width / (k + 2 / 3)


def _across(centre: float, width: float, k: int) -> list[float]:
    """The mesh lines across a straight track: k + 1 lines inside its metal, the outer ones a third of a
    cell d inside each edge, and 1 line two thirds of d outside each edge, so that every cell across
    the edge is d. A sheet's edge on a mesh line is wider to the solver than to the board; openEMS's
    own microstrip tutorial puts lines a third of a cell inside the edge and two thirds outside
    (openEMS 0.0.35, Tutorials/MSL_NotchFilter.m, lines 36 to 39)."""
    d = _cell_across(width, k)
    lo, hi = centre - width / 2, centre + width / 2
    return [lo - 2 * d / 3] + [lo + d / 3 + d * i for i in range(k + 1)] + [hi + 2 * d / 3]


def _samples(t: Track) -> list[tuple[float, float]]:
    """The points a track is checked at: its centre line and its 2 edges (a micrometre inside them),
    every half its width along it, ends included."""
    (ax, ay), (bx, by), h = t.a, t.b, t.width / 2
    length = math.hypot(bx - ax, by - ay)
    if length < 1e-9:
        return []
    ux, uy = (bx - ax) / length, (by - ay) / length
    n = max(1, math.ceil(length / max(h, 1e-3)))
    side = max(h - 1e-3, 0.0)
    out = []
    for i in range(n + 1):
        cx, cy = ax + ux * length * i / n, ay + uy * length * i / n
        out.extend((cx - uy * off, cy + ux * off) for off in (0.0, side, -side))
    return out


def _bare_point(t: Track, polys: list) -> tuple[float, float] | None:
    """The first point of a track (`_samples`) with no polygon of `polys` under it, or None."""
    return next((q for q in _samples(t) if not any(_in_polygon(q, p) for p in polys)), None)


def _own_nodes(polygons: list[dict], mesh: dict) -> list[dict]:
    """The polygons that each hold, strictly inside, a mesh node or edge centre that no later polygon
    of their net and height holds. openEMS drops a primitive that wins no point of the mesh (`Unused
    primitive`, a fault to the command): on Wyvern's USB 3 pair a piece of /SS_TX1_N 0.0586 mm long
    lay under the octagons at its 2 ends but for its corners, and openEMS stopped warning when the
    piece or either octagon was taken out, the later winning. Leaving such a polygon out changes no
    point of the structure."""
    xs_all, ys_all = mesh["x"], mesh["y"]
    points = [(x, y) for x in xs_all for y in ys_all]
    points += [((a + b) / 2, y) for a, b in pairwise(xs_all) for y in ys_all]
    points += [(x, (a + b) / 2) for x in xs_all for a, b in pairwise(ys_all)]
    kept: list[dict] = []
    for poly in reversed(polygons):
        xs, ys = [p[0] for p in poly["points"]], [p[1] for p in poly["points"]]
        later = [e for e in kept if e["net"] == poly["net"] and e["z"] == poly["z"]]
        own = (
            q
            for q in points
            if min(xs) - 1e-7 <= q[0] <= max(xs) + 1e-7
            and min(ys) - 1e-7 <= q[1] <= max(ys) + 1e-7
            and _in_polygon(q, poly["points"], tol=-1e-7)
            and not any(_in_polygon(q, e["points"]) for e in later)
        )
        if next(own, None) is not None:
            kept.append(poly)
    return kept[::-1]


def _pour_between(board: Board, t: Track, plane: str, reference: str):
    """(net, layer, point): the first point of a track (`_samples`) over a pour of a net other than
    `reference` on a copper layer strictly between the track's and the plane's, or None."""
    lo, hi = sorted((board.copper_z[t.layer], board.copper_z[plane]))
    for net, _, by_layer in board.zones:
        if net == reference:
            continue
        for mid, polys in sorted(by_layer.items()):
            if mid not in board.copper_z or not lo + 1e-9 < board.copper_z[mid] < hi - 1e-9:
                continue
            for q in _samples(t):
                if any(_in_polygon(q, p) for p in polys if len(p) > 2):
                    return net, mid, q
    return None


def build_model(board: Board, group: dict, spec: dict) -> dict:
    """The engine-neutral model of 1 group, in mm: the box, the dielectrics, the reference planes, the
    copper of the group's nets as polygons, the vias, the ports and the mesh."""
    s = spec["settings"]
    nets, reference = group["nets"], spec["reference"]
    where = f"group {group['name']}"
    tracks = [t for t in board.tracks if t.net in nets]
    for net in nets:
        if not any(t.net == net for t in tracks):
            raise Refusal(f"{where}: net {net} has no track on {board.path.name}")
    unknown = [t.layer for t in tracks if t.layer not in board.copper_z]
    if unknown:
        raise Refusal(f"{where}: layer {unknown[0]} is not in the board's stack-up")
    poured = {ly for net, lys, _ in board.zones if net == reference for ly in lys if ly in board.copper_z}
    # A pour on a layer the group's tracks use is copper beside them, not a plane: as a sheet over the
    # box it would short them. The planes are the nearest pour under and over each layer of tracks; the
    # ones beyond those are shielded by them.
    signal_z = sorted({board.copper_z[t.layer] for t in tracks})
    sheets = sorted((board.copper_z[ly], ly) for ly in poured if board.copper_z[ly] not in signal_z)
    chosen_planes = set()
    for zt in signal_z:
        under = [s for s in sheets if s[0] < zt]
        over = [s for s in sheets if s[0] > zt]
        chosen_planes.update(([under[-1]] if under else []) + ([over[0]] if over else []))
    plane_layers = [ly for _, ly in sorted(chosen_planes)]
    beside = sorted(ly for ly in poured if board.copper_z[ly] in signal_z)
    if not plane_layers:
        raise Refusal(f"{where}: no zone of {reference} on a copper layer: a port has no plane to stand on")
    # The model makes each plane whole over the box. That holds only where the pour lies under every
    # track: a track is sampled at its centre and both edges, every half its width along it, and each
    # point must lie in the pour on each plane next to its layer.
    shapes = {}
    for net, _, by_layer in board.zones:
        if net == reference:
            for ly, polys in by_layer.items():
                shapes.setdefault(ly, []).extend(p for p in polys if len(p) > 2)
    for t in tracks:
        zt = board.copper_z[t.layer]
        under = [s for s in sheets if s[0] < zt]
        over = [s for s in sheets if s[0] > zt]
        for _, ly in ([under[-1]] if under else []) + ([over[0]] if over else []):
            bare = _bare_point(t, shapes.get(ly, []))
            if bare is not None:
                raise Refusal(
                    f"{where}: the track of {t.net} from {_pt(t.a)} to {_pt(t.b)} on {t.layer} has no "
                    f"{reference} pour on {ly} under {_pt(bare)}: the model would put a plane where the "
                    f"board has none"
                )
            # A pour of another net between the track and its plane carries the return current; the
            # model has no other net, so the reference would be the plane, farther away.
            found = _pour_between(board, t, ly, reference)
            if found is not None:
                net, mid, hit = found
                raise Refusal(
                    f"{where}: the track of {t.net} from {_pt(t.a)} to {_pt(t.b)} on {t.layer} has a "
                    f"{net or '(no net)'} pour on {mid} at {_pt(hit)}, between it and the {reference} "
                    f"plane on {ly}: the model leaves every other net out, so its return path would be "
                    f"the plane's"
                )
    vias = [v for v in board.vias if v.net in nets]
    for v in vias:
        za, zb = sorted(board.copper_z.get(ly, 0.0) for ly in v.layers)
        crossed = [ly for ly in plane_layers if za + 1e-9 < board.copper_z[ly] < zb - 1e-9]
        if crossed:
            raise Refusal(
                f"{where}: the via of {v.net} at {_pt(v.at)} crosses the {reference} plane on {crossed[0]}: "
                f"the model cuts no antipad, so the via would short the net to the plane"
            )

    # nodes: track ends per layer; a via joins its layers at its centre
    degree: dict[tuple[str, tuple[float, float]], list[Track]] = {}
    for t in tracks:
        for p in (t.a, t.b):
            degree.setdefault((t.layer, _key(p)), []).append(t)
    via_at = {_key(v.at) for v in vias}
    # The impedance a 2-port's S-parameters give is the image impedance of whatever lies between its
    # ports: 30, 80 and 30 ohm sections read 49.32 ohm. It is a track's only on a uniform line: 1 width,
    # 1 layer, no branch (3 or more ends at 1 point, or an end on another track of the net).
    no_impedance = {}
    for net in nets:
        own = [t for t in tracks if t.net == net]
        widths = sorted({round(t.width, 6) for t in own})
        layers = sorted({t.layer for t in own})
        branch = next(
            (
                p
                for (ly, p), ts in sorted(degree.items())
                if ts[0].net == net
                and (
                    len(ts) > 2
                    or (len(ts) == 1 and any(_inside(p, o) for o in own if o.layer == ly and o not in ts))
                )
            ),
            None,
        )
        if branch is not None:
            why = f"{net} branches at {_pt(branch)}"
        elif len(widths) > 1:
            why = f"{net} has {len(widths)} widths ({', '.join(f'{w:g}' for w in widths)} mm)"
        elif len(layers) > 1:
            why = f"{net} is on {len(layers)} layers ({', '.join(layers)})"
        else:
            continue
        no_impedance[net] = f"{why}: the impedance is a uniform line's"
    polygons, mesh_x, mesh_y = [], [], []
    k = max(1, int(s["cells_across_width"]))
    for t in tracks:
        (ax, ay), (bx, by), h = t.a, t.b, t.width / 2
        length = math.hypot(bx - ax, by - ay)
        if length < 1e-9:
            continue
        nx, ny = -(by - ay) / length * h, (bx - ax) / length * h
        pts = [[ax + nx, ay + ny], [bx + nx, by + ny], [bx - nx, by - ny], [ax - nx, ay - ny]]
        polygons.append({"net": t.net, "z": board.copper_z[t.layer], "points": pts})
        # A sheet's edge on a mesh line is wider to the solver than to the board: the line fixture read
        # 43.14 ohm, Hammerstad and Jensen give 51.34. The edge lies a third of a cell inside the
        # metal and two thirds outside (`_across`): 50.88 ohm.
        if abs(by - ay) < 1e-9:
            mesh_y.extend(_across(ay, t.width, k))
            mesh_x.extend([ax, bx])
        elif abs(bx - ax) < 1e-9:
            mesh_x.extend(_across(ax, t.width, k))
            mesh_y.extend([ay, by])
        else:
            mesh_x.extend(q[0] for q in pts)
            mesh_y.extend(q[1] for q in pts)
    for (layer, p), ts in degree.items():
        if len(ts) > 1 or p in via_at:
            octagon = _octagon(p, max(t.width for t in ts) / 2)
            # A joint the tracks' own rectangles cover (a straight run, a T) needs none: openEMS warns of
            # a primitive that fills no cell, and the run counts that warning as a fault.
            if not all(any(_inside(q, t) for t in ts) for q in octagon):
                polygons.append({"net": ts[0].net, "z": board.copper_z[layer], "points": octagon})

    ends = [(layer, p, ts[0]) for (layer, p), ts in degree.items() if len(ts) == 1 and p not in via_at]
    chosen = []
    if group.get("ports"):
        at = f"{where}, `ports` of {Path(spec.get('file', 'fields.json')).name}"
        for name in group["ports"]:
            if name not in board.pads:
                raise Refusal(f"{at}: pad {name} is not on {board.path.name}")
            if group["ports"].count(name) > 1:
                raise Refusal(f"{at}: pad {name} is named {group['ports'].count(name)} times")
            px, py, pad_net, reach = board.pads[name]
            if pad_net not in nets:
                raise Refusal(f"{at}: pad {name} is on net {pad_net or '(none)'}, not a net of the group")
            near = [e for e in ends if e[2].net == pad_net]
            if not near:
                raise Refusal(f"{at}: net {pad_net} has no free track end to put the port of {name} on")
            end = min(near, key=lambda e: math.hypot(e[1][0] - px, e[1][1] - py))
            gap = math.hypot(end[1][0] - px, end[1][1] - py)
            if gap > reach + 1e-6:
                raise Refusal(
                    f"{at}: pad {name} at {_pt((px, py))}: the nearest free end of {pad_net}, {_pt(end[1])}, "
                    f"is {gap:.3f} mm away and the pad reaches {reach:.3f} mm"
                )
            if end in chosen:
                raise Refusal(f"{at}: pad {name} gives the end at {_pt(end[1])}, a port already")
            chosen.append(end)
    else:
        for net in nets:
            free = sorted((e for e in ends if e[2].net == net), key=lambda e: (e[1], e[0]))
            if len(free) > 2:
                raise Refusal(
                    f"{where}: net {net} has {len(free)} free track ends "
                    f"({', '.join(_pt(e[1]) for e in free)}) and fields.json names no `ports`: "
                    "an open end is part of the structure, never a port; name the pads"
                )
            chosen.extend(free)
    ports = []
    for n, (layer, p, t) in enumerate(chosen, 1):
        zt = board.copper_z[layer]
        others = [ly for ly in plane_layers if abs(board.copper_z[ly] - zt) > 1e-9]
        if not others:
            raise Refusal(f"{where}: the end at {p} on {layer} has no {reference} plane on another layer")
        zp = board.copper_z[min(others, key=lambda ly: abs(board.copper_z[ly] - zt))]
        # A straight track: across it from its first mesh line inside the metal to its last
        # (`_across`). A slanted one has no such lines: from edge to edge, as its corners' lines.
        straight = abs(t.b[0] - t.a[0]) < 1e-9 or abs(t.b[1] - t.a[1]) < 1e-9
        h = t.width / 2 - (_cell_across(t.width, k) / 3 if straight else 0.0)
        along_x = abs(t.b[0] - t.a[0]) >= abs(t.b[1] - t.a[1])
        x, y = p
        start = [x, y - h, zp] if along_x else [x - h, y, zp]
        stop = [x, y + h, zt] if along_x else [x + h, y, zt]
        start, stop = [round(v, 9) for v in start], [round(v, 9) for v in stop]  # as the mesh holds lines
        ports.append({"n": n, "net": t.net, "layer": layer, "start": start, "stop": stop, "r": s["port_ohm"]})

    xs = [q[0] for poly in polygons for q in poly["points"]] + [v.at[0] for v in vias]
    ys = [q[1] for poly in polygons for q in poly["points"]] + [v.at[1] for v in vias]
    m = s["margin_mm"]
    z_used = [board.copper_z[t.layer] for t in tracks] + [board.copper_z[ly] for ly in plane_layers]
    for v in vias:
        z_used.extend(board.copper_z.get(ly, 0.0) for ly in v.layers)
    zlo, zhi = min(z_used), max(z_used)
    box = [min(xs) - m, min(ys) - m, zlo - m, max(xs) + m, max(ys) + m, zhi + m]
    planes = [
        {"layer": ly, "net": reference, "z": board.copper_z[ly]}
        for ly in plane_layers
        if zlo - 1e-9 <= board.copper_z[ly] <= zhi + 1e-9
    ]
    dielectrics = [
        {"z": [max(a, zlo), min(b, zhi)], "er": er, "tand": tand}
        for a, b, er, tand in board.dielectrics
        if min(b, zhi) - max(a, zlo) > 1e-9
    ]
    cylinders = []
    for v in vias:
        za, zb = sorted(board.copper_z.get(ly, 0.0) for ly in v.layers)
        cylinders.append({"net": v.net, "at": list(v.at), "z": [za, zb], "r": v.drill / 2})
        mesh_x.extend([v.at[0] - v.drill / 2, v.at[0] + v.drill / 2])
        mesh_y.extend([v.at[1] - v.drill / 2, v.at[1] + v.drill / 2])

    f_lo, f_hi = (g * 1e9 for g in group["band_ghz"])
    er_max = max([d["er"] for d in dielectrics] or [1.0])
    cell = max_cell_mm(f_hi, er_max, s["cells_per_wavelength"])
    mesh_x += [box[0], box[3]]
    mesh_y += [box[1], box[4]]
    mesh_z = [box[2], box[5]] + [z for z in z_used]
    for d in dielectrics:
        k = int(s["cells_per_dielectric"])
        mesh_z.extend(d["z"][0] + (d["z"][1] - d["z"][0]) * i / k for i in range(k + 1))
    # The absorbing layers take the outermost cells of the mesh: they lie outside the box.
    pml = int(s["absorbing_cells"])
    for lines, lo_, hi_ in ((mesh_x, box[0], box[3]), (mesh_y, box[1], box[4]), (mesh_z, box[2], box[5])):
        lines.extend([lo_ - pml * cell, hi_ + pml * cell])
    # The least cell: half a cell across the narrowest track, and half a cell through the thinnest
    # dielectric. Lines closer than that (the corners of a slanted track) are 1 line.
    least_xy = _cell_across(min(t.width for t in tracks), k) / 2
    thin = [d["z"][1] - d["z"][0] for d in dielectrics] or [zhi - zlo or 1.0]
    least_z = min(thin) / (2 * max(1, int(s["cells_per_dielectric"])))
    # A port's bounds are lines of the mesh: its excitation is a sheet, dropped when it lies on none.
    port_at = [[p[e][k] for p in ports for e in ("start", "stop")] for k in range(3)]
    n_f = int(s["frequencies"])
    freqs = [f_lo + (f_hi - f_lo) * i / (n_f - 1) for i in range(n_f)]
    mesh = {
        "x": mesh_lines(mesh_x, cell, min_cell=least_xy, keep=port_at[0]),
        "y": mesh_lines(mesh_y, cell, min_cell=least_xy, keep=port_at[1]),
        "z": mesh_lines(mesh_z, cell, min_cell=least_z, keep=port_at[2] + z_used),
    }
    polygons = _own_nodes(polygons, mesh)
    return {
        "unit_m": 1e-3,
        "group": group["name"],
        "kind": group.get("kind", "lines"),
        "nets": nets,
        "reference": reference,
        "board": board.path.name,
        "box": box,
        "dielectrics": dielectrics,
        "planes": planes,
        "metals": [
            {
                "net": net,
                "polygons": [{"z": p["z"], "points": p["points"]} for p in polygons if p["net"] == net],
                "vias": [c for c in cylinders if c["net"] == net],
            }
            for net in nets
        ],
        "ports": ports,
        "no_impedance": no_impedance,
        "frequencies_hz": freqs,
        "max_cell_mm": cell,
        "mesh": mesh,
        "settings": dict(s),
        "left_out": [
            "copper thickness: copper is a sheet at its layer's height; 35 um lowers a 0.36 mm line over "
            "0.2 mm of 4.5 from 51.34 to 48.94 ohm (Hammerstad and Jensen 1980, thickness correction)",
            "conductor loss: copper is a perfect conductor; loss is the dielectric's alone",
            f"the {reference} planes' own outlines: each is whole over the box; the pour, less its cutouts, "
            "was checked under each track of the group, at its centre and edges every half its width along "
            "it, and no pour of another net lies between a track and its plane",
            f"antipads: a via of the group that crosses a {reference} plane is refused",
            "pads, parts, solder mask and every net outside the group",
            "the board's edge: the dielectric fills the box",
        ]
        + [f"the {reference} pour on {ly}, the layer of the group's own tracks" for ly in beside],
    }


# ---------------------------------------------------------------- measures


def dft(t: list[float], v: list[float], freqs: list[float]) -> list[complex]:
    """sum(v e^(-j 2 pi f t)) dt over samples at equal steps."""
    if len(t) < 2:
        return [0j for _ in freqs]
    dt = t[1] - t[0]
    out = []
    for f in freqs:
        w = cmath.exp(-2j * math.pi * f * dt)
        p = cmath.exp(-2j * math.pi * f * t[0])
        acc = 0j
        for x in v:
            acc += x * p
            p *= w
        out.append(acc * dt)
    return out


def s_column(ui: list[tuple[complex, complex]], zref: float, driven: int) -> list[complex]:
    """S[receiver][driven] at 1 frequency from each port's voltage and current, the current into the
    structure: the wave in is 0.5 (u + Z i), the wave out is u less the wave in."""
    inc = [0.5 * (u + zref * i) for u, i in ui]
    ref = [u - a for (u, _), a in zip(ui, inc, strict=True)]
    return [r / inc[driven] for r in ref]


FLOOR = 1e-30  # |S| at or under this is 0 to the arithmetic: no wave reached the port


def _db(x: complex) -> float:
    return 20 * math.log10(max(abs(x), FLOOR))


def _worst(freqs, s, sign: int) -> dict:
    """The worst of sign x 20 log10 |s| over the band, the larger; a |s| at the floor is no measure."""
    zero = [f for x, f in zip(s, freqs, strict=True) if abs(x) <= FLOOR]
    if zero:
        why = f"|S| is 0 at {zero[0] / 1e9:.3g} GHz: no wave reached the port, so nothing was measured"
        return {"value": None, "at_hz": zero[0], "why": why}
    v, f = max((sign * _db(x), f) for x, f in zip(s, freqs, strict=True))
    return {"value": v, "at_hz": f}


def line_measures(freqs, s11, s21=None, zref: float = 50.0) -> dict:
    """A driven net's measures over the band: the least return loss, the most insertion loss, and the
    line's impedance as a symmetric 2-port gives it, the median over the frequencies where it is
    defined."""
    out = {}
    rl = _worst(freqs, s11, 1)
    if rl["value"] is not None:
        rl["value"] = -rl["value"]
    out["return_loss_db"] = rl
    if s21 is not None:
        out["insertion_loss_db"] = _worst(freqs, s21, -1)
        if out["insertion_loss_db"]["value"] is None:
            return out
        z = []
        for a, b in zip(s11, s21, strict=True):
            a, b = complex(a), complex(b)
            num, den = (1 + a) ** 2 - b * b, (1 - a) ** 2 - b * b
            if abs(den) >= 0.05 and abs(num) >= 0.05:
                z.append((zref * cmath.sqrt(num / den)).real)
        if z:
            z.sort()
            mid = len(z) // 2
            out["impedance_ohm"] = {
                "value": z[mid] if len(z) % 2 else (z[mid - 1] + z[mid]) / 2,
                "at_hz": None,
                "median_of": len(z),
            }
    return out


def coupling_measure(freqs, s) -> dict:
    return _worst(freqs, s, 1)


def _fmt(v: float) -> str:
    return f"{v:g}"


def judge(limits: list[dict], measures: dict) -> tuple[list[str], list[str], list[str]]:
    """Each limit against its measure: the lines that failed, held and were not judged."""
    fails, held, unjudged = [], [], []
    for lim in limits:
        m, net = lim["measure"], lim["net"]
        key = f"{m} from {lim['from']}" if "from" in lim else m
        label = f"{net} {key}"
        got = measures.get(net, {}).get(key)
        if got is None:
            unjudged.append(f"{label}: not judged, the run gave no such measure")
            continue
        v = got["value"]
        if v is None:
            unjudged.append(f"{label}: not judged, {got['why']}")
            continue
        at = f" at {got['at_hz'] / 1e9:.3g} GHz" if got.get("at_hz") is not None else ""
        if got.get("median_of"):
            at = f" (the median over {got['median_of']} frequencies)"
        if "min" in lim and v < lim["min"]:
            fails.append(f"{label} {v:.2f}{at} below min {_fmt(lim['min'])} ({lim['source']})")
        elif "max" in lim and v > lim["max"]:
            fails.append(f"{label} {v:.2f}{at} above max {_fmt(lim['max'])} ({lim['source']})")
        else:
            span = f"{_fmt(lim['min']) if 'min' in lim else ''}..{_fmt(lim['max']) if 'max' in lim else ''}"
            held.append(f"{label} {v:.2f}{at} within {span} ({lim['source']})")
    return fails, held, unjudged


# ---------------------------------------------------------------- engines


def _n(v: float) -> str:
    return f"{v:.10g}"


def _box(a, b, prio: int) -> str:
    return (
        f'<Box Priority="{prio}"><P1 X="{_n(a[0])}" Y="{_n(a[1])}" Z="{_n(a[2])}"/>'
        f'<P2 X="{_n(b[0])}" Y="{_n(b[1])}" Z="{_n(b[2])}"/></Box>'
    )


def _polygon(z: float, points, prio: int = 10) -> str:
    verts = "".join(f'<Vertex X1="{_n(x)}" X2="{_n(y)}"/>' for x, y in points)
    return f'<Polygon Priority="{prio}" Elevation="{_n(z)}" NormDir="2">{verts}</Polygon>'


class EngineFault(RuntimeError):
    """A run whose output is no result: the message says why."""


SETTLE_SAMPLES = 5  # samples in a row the port energy must stay under the end criterion
ENGINE_MARGIN_DB = 10.0  # how much further than the end criterion openEMS lets the box's energy fall


def settled(energy: list[float], end_db: float, window: int = SETTLE_SAMPLES) -> int | None:
    """The sample that ends the first `window` samples in a row lying `end_db` under the series' peak
    after the last sample that does not, or None when the series ends before. On a line longer than
    the pulse every port is quiet while the wave crosses: a cut there missed the far port's wave (the
    z57 run's probes with port 2 delayed by 40 samples gave |S21| of -85 to -66 dB). A run that stops
    later adds only quiet samples, since openEMS stops 10 dB under the end criterion
    (ENGINE_MARGIN_DB), so it gives the same answer."""
    peak = max(energy, default=0.0)
    if peak <= 0:
        return None
    floor = peak * 10 ** (end_db / 10)
    loud = max(k for k, e in enumerate(energy) if e > floor)
    return loud + window if loud + window < len(energy) else None


class OpenEMS:
    """openEMS run as its own program on an XML file this class writes. Its lumped port is the one of
    openEMS's own AddLumpedPort: a resistor, a soft excitation against the port's direction, a voltage
    probe weighted by minus the direction and a current probe by the direction."""

    name = "openems"
    program = "openEMS"

    @staticmethod
    def binary() -> str | None:
        stated = os.environ.get("OPENEMS")
        if stated:
            return stated if Path(stated).is_file() and os.access(stated, os.X_OK) else None
        root = Path(os.environ.get("WORKCENTER_ROOT", "/opt/workcenters/ee"))
        pinned = root / "openems" / "bin" / "openEMS"
        if pinned.is_file():
            return str(pinned)
        return shutil.which("openEMS")

    @classmethod
    def version(cls) -> str | None:
        exe = cls.binary()
        if not exe:
            return None
        try:
            proc = subprocess.run([exe], capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            return None
        found = re.search(r"version v?(\d+(?:\.\d+)+)", proc.stdout + proc.stderr)
        return found.group(1) if found else None

    @staticmethod
    def xml(model: dict, driven: int) -> str:
        s, mesh = model["settings"], model["mesh"]
        f_max = model["frequencies_hz"][-1]
        f0 = fc = f_max / 2
        # The dielectric and the planes run into the absorbing layers, to the mesh's ends in x and y.
        lo, hi = [mesh["x"][0], mesh["y"][0]], [mesh["x"][-1], mesh["y"][-1]]
        pml = f"PML_{int(s['absorbing_cells'])}"
        props = []
        for i, d in enumerate(model["dielectrics"], 1):
            kappa = 2 * math.pi * f0 * EPS0 * d["er"] * d["tand"]
            fill = _box([lo[0], lo[1], d["z"][0]], [hi[0], hi[1], d["z"][1]], 1)
            props.append(
                f'<Material Name="dielectric_{i}"><Property Epsilon="{_n(d["er"])}" Kappa="{_n(kappa)}"/>'
                f"<Primitives>{fill}</Primitives></Material>"
            )
        corners = [[lo[0], lo[1]], [hi[0], lo[1]], [hi[0], hi[1]], [lo[0], hi[1]]]
        for p in model["planes"]:
            sheet = _polygon(p["z"], corners)
            props.append(f'<Metal Name="plane_{p["layer"]}"><Primitives>{sheet}</Primitives></Metal>')
        for k, metal in enumerate(model["metals"], 1):
            prims = "".join(_polygon(p["z"], p["points"]) for p in metal["polygons"])
            for c in metal["vias"]:
                x, y = _n(c["at"][0]), _n(c["at"][1])
                prims += (
                    f'<Cylinder Priority="10" Radius="{_n(c["r"])}"><P1 X="{x}" Y="{y}" Z="{_n(c["z"][0])}"/>'
                    f'<P2 X="{x}" Y="{y}" Z="{_n(c["z"][1])}"/></Cylinder>'
                )
            props.append(f'<Metal Name="net_{k}"><Primitives>{prims}</Primitives></Metal>')
        for p in model["ports"]:
            n, a, b = p["n"], p["start"], p["stop"]
            direction = 1 if b[2] > a[2] else -1
            props.append(
                f'<LumpedElement Name="port_resist_{n}" Direction="2" Caps="1" R="{_n(p["r"])}">'
                f"<Primitives>{_box(a, b, 5)}</Primitives></LumpedElement>"
            )
            if n == driven:
                props.append(
                    f'<Excitation Name="port_excite_{n}" Type="0" Excite="0,0,{-direction}">'
                    f"<Primitives>{_box(a, b, 5)}</Primitives></Excitation>"
                )
            mx, my, mz = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2
            props.append(
                f'<ProbeBox Name="port_ut{n}" Type="0" Weight="{-direction}">'
                f"<Primitives>{_box([mx, my, a[2]], [mx, my, b[2]], 5)}</Primitives></ProbeBox>"
            )
            props.append(
                f'<ProbeBox Name="port_it{n}" Type="1" Weight="{direction}" NormDir="2">'
                f"<Primitives>{_box([a[0], a[1], mz], [b[0], b[1], mz], 5)}</Primitives></ProbeBox>"
            )
        # openEMS stops on the box's energy, the spectra are cut where the ports' settles (`column`):
        # openEMS runs on to 10 dB further, so that the ports have settled before it stops. On the
        # Wyvern lane at -40 dB the ports reached -40 dB 3 samples before openEMS stopped.
        end = 10 ** ((s["end_criteria_db"] - ENGINE_MARGIN_DB) / 10)
        bc = " ".join(f'{side}="{pml}"' for side in ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"))
        steps = int(s["max_timesteps"])
        return "\n".join(
            [
                '<?xml version="1.0" encoding="UTF-8"?>',
                "<openEMS>",
                f'<FDTD NumberOfTimesteps="{steps}" endCriteria="{_n(end)}" f_max="{_n(f0 + fc)}">',
                f'<Excitation Type="0" f0="{_n(f0)}" fc="{_n(fc)}"/>',
                f"<BoundaryCond {bc}/>",
                "</FDTD>",
                '<ContinuousStructure CoordSystem="0">',
                "<Properties>",
                *props,
                "</Properties>",
                f'<RectilinearGrid DeltaUnit="{_n(model["unit_m"])}" CoordSystem="0">',
                *(
                    f"<{ax.upper()}Lines>{','.join(_n(v) for v in mesh[ax])}</{ax.upper()}Lines>"
                    for ax in "xyz"
                ),
                "</RectilinearGrid>",
                "</ContinuousStructure>",
                "</openEMS>",
                "",
            ]
        )

    @classmethod
    def prepare(cls, model: dict, folder: Path, driven: list[int]) -> list[Path]:
        out = []
        for n in driven:
            run = folder / "openems" / f"port{n}"
            run.mkdir(parents=True, exist_ok=True)
            (run / "model.xml").write_text(cls.xml(model, n), encoding="utf-8")
            out.append(run)
        return out

    @staticmethod
    def fault(text: str) -> str | None:
        """What in openEMS's log makes its result another structure's, or a cut one. Each of these
        comes with exit 0."""
        # A primitive that lies on no mesh line is dropped: the run simulates another structure.
        unused = re.search(r"Unused primitive.*", text)
        if unused:
            return unused.group(0)
        if "Cutting to max number of timesteps" in text:
            return "the excitation alone needs more steps than max_timesteps: a cell is too small"
        # A run that stops at its step limit has not let the energy leave the box: its spectra are cut.
        if "Max. number of timesteps was reached" in text:
            return "the energy in the box did not fall to the end criterion within the step limit"
        return None

    @classmethod
    def run(cls, run: Path, timeout: float) -> tuple[bool, str]:
        """openEMS on the run's model.xml. The log is read every 2 s: a fault openEMS states before
        its time steps (a dropped primitive, a cut excitation) stops the run there."""
        exe, path = cls.binary(), run / "openems.log"
        start = time.monotonic()
        with path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                [exe, "model.xml", "--disable-dumps"], cwd=run, stdout=log, stderr=subprocess.STDOUT
            )
            while proc.poll() is None:
                if time.monotonic() - start > timeout:
                    proc.kill()
                    proc.wait()
                    raise subprocess.TimeoutExpired(exe, timeout)
                found = cls.fault(path.read_text(encoding="utf-8", errors="replace"))
                if found:
                    proc.kill()
                    proc.wait()
                    return False, found
                time.sleep(2)
        text = path.read_text(encoding="utf-8", errors="replace")
        found = cls.fault(text)
        if found:
            return False, found
        return proc.returncode == 0, text

    @staticmethod
    def _probe(path: Path) -> tuple[list[float], list[float]]:
        t, v = [], []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.startswith("%") or not line.strip():
                continue
            a, b = line.split()[:2]
            t.append(float(a))
            v.append(float(b))
        return t, v

    @classmethod
    def column(cls, run: Path, model: dict, driven: int) -> list[list[complex]]:
        """S[receiver][driven] at each of the model's frequencies, receivers in port order.

        openEMS checks its end criterion every 4 s of the clock, so where a run stops hangs on the
        machine's load. Every sample before the stop is the same from run to run: the spectra are read
        up to the sample where the ports' energy, the sum of u^2 + (Z i)^2, has settled after its last
        loud sample (`settled`), and not beyond. A run that stopped before that is a fault."""
        freqs, zref = model["frequencies_hz"], model["settings"]["port_ohm"]
        probes = [
            (cls._probe(run / f"port_ut{p['n']}"), cls._probe(run / f"port_it{p['n']}"))
            for p in model["ports"]
        ]
        n = min(len(s[0]) for pair in probes for s in pair)
        energy = [sum(u[1][k] ** 2 + (zref * i[1][k]) ** 2 for u, i in probes) for k in range(n)]
        end_db = model["settings"]["end_criteria_db"]
        last = settled(energy, end_db)
        if last is None:
            raise EngineFault(
                f"the port signals did not settle {-end_db:g} dB under their peak for {SETTLE_SAMPLES} "
                f"samples after their last sample above it, in the {n} samples openEMS wrote"
            )
        ui = []
        for (tu, vu), (ti, vi) in probes:
            u = dft(tu[: last + 1], vu[: last + 1], freqs)
            i = dft(ti[: last + 1], vi[: last + 1], freqs)
            ui.append(list(zip(u, i, strict=True)))
        index = [p["n"] for p in model["ports"]].index(driven)
        per_f = [s_column([col[k] for col in ui], zref, index) for k in range(len(freqs))]
        return [[row[r] for row in per_f] for r in range(len(model["ports"]))]


ENGINES = {"openems": OpenEMS}


# ---------------------------------------------------------------- a run


def group_measures(model: dict, columns: dict[int, list[list[complex]]]) -> dict:
    """The measures of each net: its own when its first port is driven, and the coupling into each other
    net of the group from each driven net. Ports keep the order fields.json names them in: NEXT into
    another net is taken at its first port, FEXT at its last."""
    freqs, zref = model["frequencies_hz"], model["settings"]["port_ohm"]
    index = {p["n"]: k for k, p in enumerate(model["ports"])}
    by_net = {net: [p["n"] for p in model["ports"] if p["net"] == net] for net in model["nets"]}
    out: dict[str, dict] = {net: {} for net in model["nets"]}
    for net, ns in by_net.items():
        if not ns or ns[0] not in columns:
            continue
        col = columns[ns[0]]
        far = col[index[ns[-1]]] if len(ns) > 1 else None
        out[net].update(line_measures(freqs, col[index[ns[0]]], far, zref))
        if len(ns) != 2:  # the impedance formula is a symmetric 2-port's: a net of 3 ports is none
            out[net].pop("impedance_ohm", None)
        elif net in model.get("no_impedance", {}):
            out[net]["impedance_ohm"] = {"value": None, "at_hz": None, "why": model["no_impedance"][net]}
        for other, os_ in by_net.items():
            if other == net or not os_:
                continue
            out[other][f"next_db from {net}"] = coupling_measure(freqs, col[index[os_[0]]])
            if len(os_) > 1:
                out[other][f"fext_db from {net}"] = coupling_measure(freqs, col[index[os_[-1]]])
    return out


def report_md(project: str, engine: str, version: str | None, groups: list[dict], verdict: str) -> str:
    out = [
        f"# Fields: {project}",
        "",
        f"Engine: {engine} {version or ''}".rstrip(),
        "",
        f"Verdict: {verdict}",
        "",
    ]
    for g in groups:
        model = g["model"]
        nx, ny, nz = (len(model["mesh"][a]) for a in "xyz")
        f0, f1 = model["frequencies_hz"][0] / 1e9, model["frequencies_hz"][-1] / 1e9
        out += [
            f"## {model['group']}",
            "",
            f"Nets {', '.join(model['nets'])} over {model['reference']}; {len(model['ports'])} ports of "
            f"{_fmt(model['settings']['port_ohm'])} ohm; band {f0:g} to {f1:g} GHz; mesh lines {nx} x {ny} x "
            f"{nz}, the largest cell {model['max_cell_mm']:.4f} mm.",
            "",
            "| Net | Measure | Value | At |",
            "|---|---|---|---|",
        ]
        for net, ms in g.get("measures", {}).items():
            for key, m in sorted(ms.items()):
                at = f"{m['at_hz'] / 1e9:.3g} GHz" if m.get("at_hz") is not None else "median"
                value = f"{m['value']:.3f}" if m["value"] is not None else "not measured"
                if m["value"] is None and m.get("at_hz") is None:
                    at = m.get("why", "")
                out.append(f"| {net} | {key} | {value} | {at} |")
        out += ["", "Limits:", ""]
        out += [f"- FAIL {x}" for x in g["fails"]] + [f"- held {x}" for x in g["held"]]
        out += [f"- {x}" for x in g["unjudged"]]
        out += ["", "The model leaves out:", ""] + [f"- {x}" for x in model["left_out"]] + [""]
    return "\n".join(out)


def cmd_fields(args, cli) -> int:
    project = cli.find_project(args.project)
    gate = "fields"
    if project.pcb is None:
        return cli.emit([cli.Result(gate, "skip", "no board in project")], args, None)
    spec_path = Path(args.spec).resolve() if args.spec else project.dir / "fields.json"
    if not spec_path.is_file():
        return cli.emit(
            [cli.Result(gate, "skip", f"no {spec_path.name}: no net is named critical")], args, None
        )
    t0 = time.monotonic()
    try:
        spec = read_spec(spec_path)
        board = read_board(project.pcb)
        models = [build_model(board, g, spec) for g in spec["groups"]]
    except Refusal as exc:
        return cli.emit(
            [cli.Result(gate, "fail", "a file is not as the command reads it", {"failures": [str(exc)]})],
            args,
            None,
        )
    engine = ENGINES[spec["engine"]]
    out = cli.out_dir_for(project, args.out) / "fields"
    runs = {}
    for model in models:
        folder = out / model["group"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "model.json").write_text(json.dumps(model, indent=1), encoding="utf-8")
        firsts = {}
        for p in model["ports"]:
            firsts.setdefault(p["net"], p["n"])
        driven = sorted(firsts.values())
        runs[model["group"]] = (driven, engine.prepare(model, folder, driven))
    if args.model:
        print(f"fields: wrote the model of {len(models)} groups into {out}; ran nothing and judged nothing")
        return 0
    if engine.binary() is None:
        why = f"engine missing: {engine.program} (`sudo ./install.sh --openems`; `doctor` says where)"
        return cli.emit([cli.Result(gate, "skip", why, {"engine_missing": engine.program})], args, None)
    version = engine.version()
    groups, all_fails, all_unjudged, all_held = [], [], [], []
    for model in models:
        driven, folders = runs[model["group"]]
        columns, errors = {}, []
        for n, run in zip(driven, folders, strict=True):
            try:
                ok, log = engine.run(run, model["settings"]["timeout_s"])
            except subprocess.TimeoutExpired:
                ok, log = False, f"no end within {model['settings']['timeout_s']} s"
            if not ok:
                last = (log.strip().splitlines() or ["no output"])[-1]
                errors.append(f"{engine.program} on port {n} ended without a result: {last}")
                continue
            try:
                columns[n] = engine.column(run, model, n)
            except EngineFault as exc:
                errors.append(f"{engine.program} on port {n} ended without a result: {exc}")
        measures = group_measures(model, columns)
        group = next(g for g in spec["groups"] if g["name"] == model["group"])
        fails, held, unjudged = judge(group.get("limits", []), measures)
        fails = errors + fails
        groups.append(
            {"model": model, "measures": measures, "fails": fails, "held": held, "unjudged": unjudged}
        )
        all_fails += [f"{model['group']}: {x}" for x in fails]
        all_held += held
        all_unjudged += [f"{model['group']}: {x}" for x in unjudged]
    failed = all_fails or (args.strict and all_unjudged)
    # A run that held no limit judged nothing: it measured, and says so, and it does not pass.
    empty = not failed and not all_held
    verdict = "FIELDS FAIL" if failed else ("FIELDS NOT JUDGED" if empty else "FIELDS HELD")
    report = out / "report.md"
    report.write_text(report_md(project.name, engine.program, version, groups, verdict), encoding="utf-8")
    summary = (
        f"{len(all_held)} held, {len(all_fails)} failed, {len(all_unjudged)} not judged in "
        f"{len(groups)} groups ({engine.program} {version or '?'})"
    )
    if empty:
        who = f"{engine.program} {version or '?'}"
        summary = f"no limit stated: nothing judged; measured {len(groups)} groups ({who})"
    details = {
        "failures": all_fails + (all_unjudged if args.strict else []),
        "warnings": [] if args.strict else all_unjudged,
        "verdict": verdict,
        "measures": {g["model"]["group"]: g["measures"] for g in groups},
    }
    seconds = round(time.monotonic() - t0, 1)
    status = "fail" if failed else ("skip" if empty else "pass")
    result = cli.Result(gate, status, summary, details, [str(report)], seconds)
    (out / "report.json").write_text(json.dumps(vars(result), indent=2, default=str), encoding="utf-8")
    code = cli.emit([result], args, None)
    if not args.json:
        print(f"{verdict}: {project.name}  report {report}")
    return code


def register(sub, cli) -> None:
    """Add `fields` to the workcenter's parser; it sets `run` to its handler."""
    p = sub.add_parser(
        "fields",
        help="simulate the nets fields.json names as critical with a field solver (openEMS), from the board "
        "file: impedance, return and insertion loss, coupling, each held to its limit; writes model.json, "
        "the engine's input, report.md and report.json into <out>/fields/",
    )
    p.add_argument("project", help="project directory or a .kicad_pro/.kicad_pcb file")
    p.add_argument("--out", help="output directory (default <project>/build)")
    p.add_argument("--spec", help="the groups and limits (default <project>/fields.json)")
    p.add_argument("--strict", action="store_true", help="a limit that is not judged fails the run")
    p.add_argument("--model", action="store_true", help="write the model and the engine's input; run nothing")
    p.set_defaults(run=lambda a: cmd_fields(a, cli))
