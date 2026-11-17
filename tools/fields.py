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
    zones: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)  # (net, layers)
    pads: dict[str, tuple[float, float, str]] = field(default_factory=dict)  # REF.PAD: (x, y, net)


def _child(node: list, head: str) -> list | None:
    return next((c for c in node[1:] if isinstance(c, list) and c and c[0] == head), None)


def _children(node: list, head: str) -> list[list]:
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == head]


def _xy(node: list | None) -> tuple[float, float]:
    if node is None or len(node) < 3:
        raise Refusal(f"a {node[0] if node else 'point'} without its 2 numbers")
    return float(node[1]), float(node[2])


def _num(node: list, head: str) -> float | None:
    found = _child(node, head)
    return float(found[1]) if found is not None and len(found) > 1 else None


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
    total = 0.0
    for ly in layers:
        kind = _child(ly, "type")
        if kind is not None and kind[1] in ("core", "prepreg"):
            total += _num(ly, "thickness") or 0.0
    z, copper_z, diel = total, {}, []
    for ly in layers:
        kind = _child(ly, "type")
        kind = str(kind[1]) if kind is not None else ""
        if kind == "copper":
            copper_z[str(ly[1])] = z
        elif kind in ("core", "prepreg"):
            t, er, tand = _num(ly, "thickness"), _num(ly, "epsilon_r"), _num(ly, "loss_tangent")
            if t is None or er is None:
                raise Refusal(f"{path.name}: stack-up layer {ly[1]} has no thickness or no epsilon_r")
            diel.append((z - t, z, er, tand or 0.0))
            z -= t
    shift = min(copper_z.values(), default=0.0)
    copper_z = {k: round(v - shift, 9) for k, v in copper_z.items()}
    diel = sorted((round(a - shift, 9), round(b - shift, 9), er, tand) for a, b, er, tand in diel)
    board = Board(path=path, copper_z=copper_z, dielectrics=diel)

    for seg in _children(root, "segment"):
        layer, width = str(_child(seg, "layer")[1]), _num(seg, "width") or 0.0
        a, b = _xy(_child(seg, "start")), _xy(_child(seg, "end"))
        board.tracks.append(Track(net_of(seg), layer, a, b, width))
    for arc in _children(root, "arc"):
        pts = _arc_points(_xy(_child(arc, "start")), _xy(_child(arc, "mid")), _xy(_child(arc, "end")))
        layer, width, net = str(_child(arc, "layer")[1]), _num(arc, "width") or 0.0, net_of(arc)
        board.tracks.extend(Track(net, layer, p, q, width) for p, q in pairwise(pts))
    for via in _children(root, "via"):
        names = _child(via, "layers")
        pair = (str(names[1]), str(names[2])) if names is not None and len(names) > 2 else ("F.Cu", "B.Cu")
        board.vias.append(Via(net_of(via), _xy(_child(via, "at")), _num(via, "drill") or 0.0, pair))
    for zone in _children(root, "zone"):
        if _child(zone, "keepout") is not None:
            continue
        one, many = _child(zone, "layer"), _child(zone, "layers")
        names = tuple(str(x) for x in (many[1:] if many is not None else one[1:] if one is not None else []))
        board.zones.append((net_of(zone), names))
    for fp in _children(root, "footprint") + _children(root, "module"):
        at = _child(fp, "at")
        fx, fy = _xy(at)
        rot = float(at[3]) if len(at) > 3 else 0.0
        ref = next((str(p[2]) for p in _children(fp, "property") if len(p) > 2 and p[1] == "Reference"), None)
        ref = ref or next(
            (str(t[2]) for t in _children(fp, "fp_text") if len(t) > 2 and t[1] == "reference"), ""
        )
        for pad in _children(fp, "pad"):
            dx, dy = _xy(_child(pad, "at"))
            ox, oy = _rotate(dx, dy, rot)
            board.pads[f"{ref}.{pad[1]}"] = (fx + ox, fy + oy, net_of(pad))
    return board


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
    for key, value in (data.get("settings") or {}).items():
        if key not in SETTINGS:
            raise Refusal(f"{where}: setting `{key}` is none of {', '.join(SETTINGS)}")
        if not _number(value) or value <= 0:
            raise Refusal(f"{where}: setting `{key}` is {value!r}, not a number above 0")
        settings[key] = value
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
    fixed: list[float], max_cell: float, ratio: float = 1.5, min_cell: float = 1e-6
) -> list[float]:
    """Mesh lines through every fixed line, no cell larger than max_cell. A fixed line closer than
    min_cell to the one before it is dropped: the solver's time step falls with the least cell. In
    each gap between fixed lines the cells grow by `ratio` from the smaller gap at each end (`_grade`).
    Where 2 runs of cells meet, 2 neighbours can differ by up to 2 times. Every fixed line kept is a
    line of the mesh, to the digit."""
    lines = sorted(set(round(v, 9) for v in fixed))
    merged = [lines[0]]
    for v in lines[1:]:
        if v - merged[-1] >= min_cell - 1e-12:
            merged.append(v)
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
    poured = {ly for net, lys in board.zones if net == reference for ly in lys if ly in board.copper_z}
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
    vias = [v for v in board.vias if v.net in nets]

    # nodes: track ends per layer; a via joins its layers at its centre
    degree: dict[tuple[str, tuple[float, float]], list[Track]] = {}
    for t in tracks:
        for p in (t.a, t.b):
            degree.setdefault((t.layer, _key(p)), []).append(t)
    via_at = {_key(v.at) for v in vias}
    polygons, mesh_x, mesh_y = [], [], []
    for t in tracks:
        (ax, ay), (bx, by), h = t.a, t.b, t.width / 2
        length = math.hypot(bx - ax, by - ay)
        if length < 1e-9:
            continue
        nx, ny = -(by - ay) / length * h, (bx - ax) / length * h
        pts = [[ax + nx, ay + ny], [bx + nx, by + ny], [bx - nx, by - ny], [ax - nx, ay - ny]]
        polygons.append({"net": t.net, "z": board.copper_z[t.layer], "points": pts})
        k = max(1, int(s["cells_across_width"]))
        if abs(by - ay) < 1e-9:
            mesh_y.extend(ay - h + 2 * h * i / k for i in range(k + 1))
        elif abs(bx - ax) < 1e-9:
            mesh_x.extend(ax - h + 2 * h * i / k for i in range(k + 1))
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
        for name in group["ports"]:
            if name not in board.pads:
                raise Refusal(f"{where}: pad {name} is not on {board.path.name}")
            px, py, _ = board.pads[name]
            near = [e for e in ends if e[2].net in nets]
            if not near:
                raise Refusal(f"{where}: no free track end to put the port of {name} on")
            chosen.append(min(near, key=lambda e: math.hypot(e[1][0] - px, e[1][1] - py)))
    else:
        for net in nets:
            chosen.extend(sorted((e for e in ends if e[2].net == net), key=lambda e: (e[1], e[0])))
    ports = []
    for n, (layer, p, t) in enumerate(chosen, 1):
        zt = board.copper_z[layer]
        others = [ly for ly in plane_layers if abs(board.copper_z[ly] - zt) > 1e-9]
        if not others:
            raise Refusal(f"{where}: the end at {p} on {layer} has no {reference} plane on another layer")
        zp = board.copper_z[min(others, key=lambda ly: abs(board.copper_z[ly] - zt))]
        h = t.width / 2
        along_x = abs(t.b[0] - t.a[0]) >= abs(t.b[1] - t.a[1])
        x, y = p
        start = [x, y - h, zp] if along_x else [x - h, y, zp]
        stop = [x, y + h, zt] if along_x else [x + h, y, zt]
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
    mesh_x += [box[0], box[3]] + [
        q[0] for poly in polygons if len(poly["points"]) == 4 for q in poly["points"]
    ]
    mesh_y += [box[1], box[4]] + [
        q[1] for poly in polygons if len(poly["points"]) == 4 for q in poly["points"]
    ]
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
    least_xy = min(t.width for t in tracks) / (2 * max(1, int(s["cells_across_width"])))
    thin = [d["z"][1] - d["z"][0] for d in dielectrics] or [zhi - zlo or 1.0]
    least_z = min(thin) / (2 * max(1, int(s["cells_per_dielectric"])))
    n_f = int(s["frequencies"])
    freqs = [f_lo + (f_hi - f_lo) * i / (n_f - 1) for i in range(n_f)]
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
        "frequencies_hz": freqs,
        "max_cell_mm": cell,
        "mesh": {
            "x": mesh_lines(mesh_x, cell, min_cell=least_xy),
            "y": mesh_lines(mesh_y, cell, min_cell=least_xy),
            "z": mesh_lines(mesh_z, cell, min_cell=least_z),
        },
        "settings": dict(s),
        "left_out": [
            "copper thickness: copper is a sheet at its layer's height",
            "conductor loss: copper is a perfect conductor; loss is the dielectric's alone",
            f"cut-outs in the {reference} planes: each is whole over the box",
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


def _db(x: complex) -> float:
    return 20 * math.log10(max(abs(x), 1e-30))


def line_measures(freqs, s11, s21=None, zref: float = 50.0) -> dict:
    """A driven net's measures over the band: the least return loss, the most insertion loss, and the
    line's impedance as a symmetric 2-port gives it, the median over the frequencies where it is
    defined."""
    out = {}
    rl = [(-_db(s), f) for s, f in zip(s11, freqs, strict=True)]
    v, f = min(rl)
    out["return_loss_db"] = {"value": v, "at_hz": f}
    if s21 is not None:
        il = [(-_db(s), f) for s, f in zip(s21, freqs, strict=True)]
        v, f = max(il)
        out["insertion_loss_db"] = {"value": v, "at_hz": f}
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
            }
    return out


def coupling_measure(freqs, s) -> dict:
    v, f = max((_db(x), f) for x, f in zip(s, freqs, strict=True))
    return {"value": v, "at_hz": f}


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
        at = f" at {got['at_hz'] / 1e9:.3g} GHz" if got.get("at_hz") is not None else ""
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
        end = 10 ** (s["end_criteria_db"] / 10)
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

    @classmethod
    def run(cls, run: Path, timeout: float) -> tuple[bool, str]:
        exe = cls.binary()
        with (run / "openems.log").open("w", encoding="utf-8") as log:
            proc = subprocess.run(
                [exe, "model.xml", "--disable-dumps"],
                cwd=run,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=timeout,
            )
        text = (run / "openems.log").read_text(encoding="utf-8", errors="replace")
        # A primitive that lies on no mesh line is dropped with a warning and exit 0: the run then
        # simulated another structure than the model.
        unused = re.search(r"Unused primitive.*", text)
        if unused:
            return False, unused.group(0)
        # A run that stops at its step limit has not let the energy leave the box: its spectra are cut.
        if "Max. number of timesteps was reached" in text:
            return False, "the energy in the box did not fall to the end criterion within the step limit"
        if "Cutting to max number of timesteps" in text:
            return False, "the excitation alone needs more steps than max_timesteps: a cell is too small"
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
        """S[receiver][driven] at each of the model's frequencies, receivers in port order."""
        freqs = model["frequencies_hz"]
        ui = []
        for p in model["ports"]:
            u = dft(*cls._probe(run / f"port_ut{p['n']}"), freqs)
            i = dft(*cls._probe(run / f"port_it{p['n']}"), freqs)
            ui.append(list(zip(u, i, strict=True)))
        zref = model["settings"]["port_ohm"]
        index = [p["n"] for p in model["ports"]].index(driven)
        per_f = [s_column([col[k] for col in ui], zref, index) for k in range(len(freqs))]
        return [[row[r] for row in per_f] for r in range(len(model["ports"]))]


ENGINES = {"openems": OpenEMS}


# ---------------------------------------------------------------- a run


def group_measures(model: dict, columns: dict[int, list[list[complex]]]) -> dict:
    """The measures of each net: its own when its first port is driven, and the coupling into each other
    net of the group from each driven net."""
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
                out.append(f"| {net} | {key} | {m['value']:.3f} | {at} |")
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
            columns[n] = engine.column(run, model, n)
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
    verdict = "FIELDS FAIL" if failed else "FIELDS HELD"
    report = out / "report.md"
    report.write_text(report_md(project.name, engine.program, version, groups, verdict), encoding="utf-8")
    summary = (
        f"{len(all_held)} held, {len(all_fails)} failed, {len(all_unjudged)} not judged in "
        f"{len(groups)} groups ({engine.program} {version or '?'})"
    )
    details = {
        "failures": all_fails + (all_unjudged if args.strict else []),
        "warnings": [] if args.strict else all_unjudged,
        "verdict": verdict,
        "measures": {g["model"]["group"]: g["measures"] for g in groups},
    }
    seconds = round(time.monotonic() - t0, 1)
    result = cli.Result(gate, "fail" if failed else "pass", summary, details, [str(report)], seconds)
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
