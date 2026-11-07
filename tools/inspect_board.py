#!/usr/bin/env python3
"""inspect_board: a board read with KiCad's own geometry, for `workcenter inspect`.

`tools/workcenter` parses the arguments and runs this file under the workcenter venv's Python,
which sees KiCad's `pcbnew` module and Pillow:

    python inspect_board.py '<the arguments as JSON>'

It prints text, or JSON with "json": true, and writes nothing but the images of `map`, into the
folder it is given. Exit codes: 0 nothing found, 1 something found (a conflict, a group cut off, a
pour island, a net the new board leaves open) or an input the board does not have, 2 an engine
missing.
"""

from __future__ import annotations

import heapq
import json
import math
import re
import sys
import zlib
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kicadgen  # noqa: E402  S-expressions: the board's stackup and the project's rule file

try:
    import pcbnew
except ImportError:  # the CLI reports the skip
    pcbnew = None

RHO_20 = 1.72e-8  # copper's resistivity at 20 °C, Ohm m
ALPHA = 0.00393  # copper's temperature coefficient of resistance, per °C
DEFAULT_CU = 0.035  # KiCad's copper thickness when a board carries no stackup, mm
RULE_KINDS = ("clearance", "hole_clearance", "hole_to_hole", "edge_clearance")
UNITS = {"mm": 1.0, "mil": 0.0254, "in": 25.4, "um": 0.001}
MAX_PX = 6000  # the longest side of a map image
PALETTE = (
    (31, 119, 180),
    (255, 127, 14),
    (44, 160, 44),
    (214, 39, 40),
    (148, 103, 189),
    (140, 86, 75),
    (227, 119, 194),
    (188, 189, 34),
    (23, 190, 207),
    (100, 60, 0),
    (0, 110, 110),
    (110, 0, 110),
)


class InputError(Exception):
    """An input the board does not have: a net, a part, a pad, a layer."""


def nm(v: float) -> int:
    return int(round(v * 1e6))


def mm(v: int) -> float:
    return v / 1e6


def at(p) -> str:
    return f"({p.x / 1e6:.3f}, {p.y / 1e6:.3f})"


def count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def where(path: str) -> str:
    """A board as its folder and file: versions of one project share the file name."""
    p = Path(path)
    return f"{p.parent.name}/{p.name}"


def short(net: str) -> str:
    return net.lstrip("/").replace("unconnected-", "nc-")[:12] or "no net"


# ------------------------------------------------------------------ the board's own numbers


@dataclass
class Rule:
    """A constraint from the project's rule file that names no condition: one layer, inner, outer, or
    every layer."""

    name: str
    layer: str
    value: float  # mm

    def applies(self, layer: str) -> bool:
        if not self.layer:
            return True
        if self.layer == "inner":
            return layer not in ("F.Cu", "B.Cu")
        if self.layer == "outer":
            return layer in ("F.Cu", "B.Cu")
        return self.layer == layer


def length(text: str) -> float:
    m = re.fullmatch(r"(-?[\d.]+)\s*(mm|mil|in|um)?", text.strip())
    if not m:
        raise ValueError(f"not a length: {text!r}")
    return float(m[1]) * UNITS[m[2] or "mm"]


def read_rules(path: Path) -> tuple[dict[str, list[Rule]], list[str]]:
    """The clearance-type constraints of a `.kicad_dru` that hold without a condition, and the names
    of those with a condition, which this reader does not evaluate."""
    text = "\n".join(
        ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.lstrip().startswith("#")
    )
    rules: dict[str, list[Rule]] = {k: [] for k in RULE_KINDS}
    unread: list[str] = []
    for node in kicadgen.parse_all(text):
        if not isinstance(node, list) or node[0] != "rule":
            continue
        layer = kicadgen.child(node, "layer")
        for constraint in kicadgen.children(node, "constraint"):
            kind, low = str(constraint[1]), kicadgen.child(constraint, "min")
            if kind not in rules or low is None:
                continue
            if kicadgen.child(node, "condition") is not None:
                unread.append(str(node[1]))
                continue
            where = str(kicadgen.atoms(layer)[0]) if layer else ""
            rules[kind].append(Rule(str(node[1]), where, length(str(kicadgen.atoms(low)[0]))))
    return rules, unread


def sexp_block(text: str, head: str) -> str | None:
    """The balanced S-expression in `text` that opens with `(head`, or None."""
    i = text.find(f"({head}")
    if i < 0:
        return None
    depth, quoted, k = 0, False, i
    while k < len(text):
        ch = text[k]
        if quoted:
            if ch == "\\":
                k += 1
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[i : k + 1]
        k += 1
    return None


@dataclass
class Copper:
    name: str
    thickness: float  # mm
    z: float  # depth of the layer's middle below the top face, mm


def stackup(text: str, copper: list[str], board_thickness: float) -> tuple[dict[str, Copper], bool]:
    """Each copper layer's thickness and depth, from the board's stackup. A board without one gets
    KiCad's default, 35 µm on every layer, spread evenly through the board; the flag says which."""
    block = sexp_block(text, "stackup")
    layers: dict[str, Copper] = {}
    if block:
        depth = 0.0
        for ly in kicadgen.children(kicadgen.parse(block), "layer"):
            kind = kicadgen.child(ly, "type")
            kind = str(kicadgen.atoms(kind)[0]) if kind else ""
            t = sum(float(kicadgen.atoms(n)[0]) for n in kicadgen.children(ly, "thickness"))
            if kind == "copper":
                layers[str(ly[1])] = Copper(str(ly[1]), t, depth + t / 2)
                depth += t
            elif str(ly[1]).startswith("dielectric"):
                depth += t
    if all(name in layers for name in copper):
        return layers, True
    n = len(copper)
    step = (board_thickness - DEFAULT_CU) / max(n - 1, 1)
    return {name: Copper(name, DEFAULT_CU, DEFAULT_CU / 2 + i * step) for i, name in enumerate(copper)}, False


# ------------------------------------------------------------------ items


@dataclass
class Item:
    kind: str  # pad, npth, track, arc, via, pour
    name: str
    net: str
    layers: list[str]
    obj: object  # the pcbnew item; for a pour, the one piece as a SHAPE_POLY_SET
    shapes: dict[str, object] = field(default_factory=dict)  # copper layer -> SHAPE
    hole: object = None  # SHAPE of the drilled hole, if any
    ref: str = ""  # a pad's footprint
    area: float = 0.0  # a pour piece's, mm²
    bbox: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)  # mm, x1 y1 x2 y2

    def ends(self) -> list:
        return [self.obj.GetStart(), self.obj.GetEnd()] if self.kind in ("track", "arc") else []


@dataclass
class Area:
    """A rule area (a keepout): what it keeps out on which layers."""

    name: str
    layers: list[str]
    outline: object  # SHAPE_POLY_SET
    no: list[str]  # tracks, vias, pads, footprints, pours


class Board:
    def __init__(self, path: Path):
        self.path = path
        self.pcb = pcbnew.LoadBoard(str(path))
        self.ds = self.pcb.GetDesignSettings()
        self.copper = [pcbnew.LayerName(ly) for ly in self.pcb.GetEnabledLayers().CuStack()]
        self.lid = {name: self.pcb.GetLayerID(name) for name in self.copper}
        self.cu, self.has_stackup = stackup(
            path.read_text(encoding="utf-8"), self.copper, self.ds.GetBoardThickness() / 1e6
        )
        dru = path.with_suffix(".kicad_dru")
        self.dru = dru if dru.is_file() else None
        pro = path.with_suffix(".kicad_pro")
        settings = (
            json.loads(pro.read_text(encoding="utf-8")).get("net_settings", {}) if pro.is_file() else {}
        )
        self.classes = {c.get("name"): c for c in settings.get("classes", [])}
        self.rules, self.unread = read_rules(dru) if self.dru else ({k: [] for k in RULE_KINDS}, [])

    # -- what is on it

    def net(self, name: str) -> str:
        """The board's own name for a net: a local label's net is `/NAME` in KiCad, and either
        spelling finds it."""
        for spelling in (name, f"/{name}", name.removeprefix("/")):
            if spelling and self.pcb.FindNet(spelling) is not None:
                return spelling
        raise InputError(f"no net {name!r} on {self.path.name}")

    def footprint(self, ref: str):
        fp = self.pcb.FindFootprintByReference(ref)
        if fp is None:
            raise InputError(f"no part {ref} on {self.path.name}")
        return fp

    def new_footprint(self, lib_id: str):
        """A footprint the board does not have yet, by LIB:NAME: from the project's fp-lib-table, else
        from KiCad's footprint library."""
        lib, _, name = lib_id.partition(":")
        dirs = []
        table = self.path.parent / "fp-lib-table"
        if table.is_file():
            for m in re.finditer(
                r'\(lib \(name "([^"]+)"\).*?\(uri "([^"]+)"\)', table.read_text(encoding="utf-8")
            ):
                if m[1] == lib:
                    dirs.append(Path(m[2].replace("${KIPRJMOD}", str(self.path.parent))))
        dirs.append(kicadgen.FOOTPRINT_DIR / f"{lib}.pretty")
        for d in dirs:
            if (d / f"{name}.kicad_mod").is_file():
                return pcbnew.FootprintLoad(str(d), name)
        raise InputError(
            f"no footprint {lib_id} in the project's fp-lib-table or in {kicadgen.FOOTPRINT_DIR}"
        )

    def class_value(self, net: str, key: str, default: int) -> int:
        """A size from the net's class in the project file (track_width, via_diameter, via_drill), nm."""
        found = self.pcb.FindNet(net)
        cls = self.classes.get(found.GetNetClassName() if found else "", self.classes.get("Default", {}))
        value = cls.get(key)
        return nm(value) if isinstance(value, (int, float)) and value > 0 else default

    def layer(self, name: str) -> str:
        if name not in self.lid:
            raise InputError(f"{name} is not a copper layer of {self.path.name}: {', '.join(self.copper)}")
        return name

    def on(self, obj) -> list[str]:
        return [name for name in self.copper if obj.IsOnLayer(self.lid[name])]

    def pad_item(self, fp, pad) -> Item:
        npth = pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH
        layers = [] if npth else self.on(pad)
        bb = pad.GetBoundingBox()
        return Item(
            "npth" if npth else "pad",
            f"{fp.GetReference()}.{pad.GetNumber()}",
            pad.GetNetname(),
            layers,
            pad,
            {ly: pad.GetEffectiveShape(self.lid[ly]) for ly in layers},
            pad.GetEffectiveHoleShape() if pad.HasHole() else None,
            fp.GetReference(),
            bbox=(mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom())),
        )

    def track_item(self, t) -> Item:
        bb = t.GetBoundingBox()
        box = (mm(bb.GetLeft()), mm(bb.GetTop()), mm(bb.GetRight()), mm(bb.GetBottom()))
        if t.GetClass() == "PCB_VIA":
            layers = self.on(t)
            size = mm(t.GetWidth(self.lid[layers[0]]))
            return Item(
                "via",
                f"via {at(t.GetPosition())} {size:.2f}/{mm(t.GetDrillValue()):.2f}",
                t.GetNetname(),
                layers,
                t,
                {ly: t.GetEffectiveShape(self.lid[ly]) for ly in layers},
                t.GetEffectiveHoleShape(),
                bbox=box,
            )
        layer = pcbnew.LayerName(t.GetLayer())
        kind = "arc" if t.GetClass() == "PCB_ARC" else "track"
        return Item(
            kind,
            f"{kind} {layer} {at(t.GetStart())}-{at(t.GetEnd())} w{mm(t.GetWidth()):.2f}",
            t.GetNetname(),
            [layer],
            t,
            {layer: t.GetEffectiveShape(self.lid[layer])},
            bbox=box,
        )

    def items(self, net: str | None = None, pours: bool = False, skip_ref: str = "") -> list[Item]:
        """Every pad, track and via, of one net when `net` is given; the filled pours' pieces too
        when asked. A part named in `skip_ref` is left out (it is the one being moved)."""
        out = []
        for fp in self.pcb.GetFootprints():
            if fp.GetReference() == skip_ref:
                continue
            for pad in fp.Pads():
                if net is None or pad.GetNetname() == net:
                    out.append(self.pad_item(fp, pad))
        for t in self.pcb.GetTracks():
            if net is None or t.GetNetname() == net:
                out.append(self.track_item(t))
        if pours:
            out.extend(self.pour_pieces(net))
        return out

    def pour_pieces(self, net: str | None = None) -> list[Item]:
        out = []
        for zone in self.pcb.Zones():
            if zone.GetIsRuleArea() or (net is not None and zone.GetNetname() != net):
                continue
            for lid in zone.GetLayerSet().CuStack():
                layer = pcbnew.LayerName(lid)
                polys = zone.GetFilledPolysList(lid)
                for i in range(polys.OutlineCount()):
                    piece = pcbnew.SHAPE_POLY_SET()
                    piece.AddOutline(polys.Outline(i))
                    for h in range(polys.HoleCount(i)):
                        piece.AddHole(polys.Hole(i, h))
                    n = sum(1 for p in out if p.layers == [layer]) + 1
                    out.append(
                        Item(
                            "pour",
                            f"pour {layer} #{n}",
                            zone.GetNetname(),
                            [layer],
                            piece,
                            {layer: piece},
                            area=piece.Area() / 1e12,
                            bbox=extent(piece),
                        )
                    )
        return out

    def areas(self) -> list[Area]:
        out = []
        for zone in self.pcb.Zones():
            if not zone.GetIsRuleArea():
                continue
            no = [
                what
                for what, flag in (
                    ("tracks", zone.GetDoNotAllowTracks()),
                    ("vias", zone.GetDoNotAllowVias()),
                    ("pads", zone.GetDoNotAllowPads()),
                    ("footprints", zone.GetDoNotAllowFootprints()),
                    ("pours", zone.GetDoNotAllowZoneFills()),
                )
                if flag
            ]
            layers = [pcbnew.LayerName(ly) for ly in zone.GetLayerSet().CuStack()]
            out.append(Area(zone.GetZoneName() or "unnamed", layers, zone.Outline(), no))
        return out

    def courtyards(self, skip_ref: str = "") -> list[tuple[str, str, object]]:
        """(ref, face, courtyard) for each part with one; the face is F.Cu or B.Cu."""
        out = []
        for fp in self.pcb.GetFootprints():
            if fp.GetReference() == skip_ref:
                continue
            fp.BuildCourtyardCaches()
            face = "B.Cu" if fp.IsFlipped() else "F.Cu"
            cy = fp.GetCourtyard(pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd)
            if cy.OutlineCount():
                out.append((fp.GetReference(), face, cy))
        return out

    def edges(self) -> list[tuple[str, object]]:
        """The board edge's shapes, and each non-plated hole, which the DRC holds copper off as edge."""
        out = []
        for d in self.pcb.GetDrawings():
            if d.GetLayer() == pcbnew.Edge_Cuts:
                out.append((f"board edge ({d.GetShapeStr().lower()})", d.GetEffectiveShape()))
        for fp in self.pcb.GetFootprints():
            for pad in fp.Pads():
                if pad.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH and pad.HasHole():
                    out.append(
                        (
                            f"{fp.GetReference()}.{pad.GetNumber()} non-plated hole",
                            pad.GetEffectiveHoleShape(),
                        )
                    )
        return out

    # -- the rules

    def floor(self, kind: str, layer: str | None, board_value: int) -> tuple[int, str]:
        need, rule = board_value, "the board's rules"
        for r in self.rules[kind]:
            if (layer is None or r.applies(layer)) and nm(r.value) > need:
                need, rule = nm(r.value), f"rule {r.name!r}"
        return need, rule

    def copper_need(self, a, b, layer: str) -> tuple[int, str]:
        """The clearance between two items of different nets on a layer: the larger of their net
        classes', as KiCad's DRC takes it, raised by a layer rule of the project's rule file."""
        lid = self.lid[layer]
        need = max(a.GetOwnClearance(lid), b.GetOwnClearance(lid), self.ds.m_MinClearance)
        floor, rule = self.floor("clearance", layer, need)
        return floor, (rule if floor > need else "net classes")

    def hole_need(self, layer: str) -> tuple[int, str]:
        return self.floor("hole_clearance", layer, self.ds.m_HoleClearance)

    def hole_to_hole(self) -> tuple[int, str]:
        return self.floor("hole_to_hole", None, self.ds.m_HoleToHoleMin)

    def edge_need(self, layer: str) -> tuple[int, str]:
        return self.floor("edge_clearance", layer, self.ds.m_CopperEdgeClearance)


def gap(a, b, limit: int) -> int | None:
    """The distance from shape `a` to shape `b` in nm when it is under `limit`, else None. The board's
    own shapes take the other: SWIG maps SHAPE::Collide(const SHAPE*, int) on those."""
    if not a.Collide(b, limit):
        return None
    if a.Collide(b, 0):
        return 0
    lo, hi = 0, limit
    while hi - lo > 20:
        mid = (lo + hi) // 2
        if a.Collide(b, mid):
            hi = mid
        else:
            lo = mid
    return hi


def window(box: list[float]):
    x0, x1, y0, y1 = box
    return pcbnew.SHAPE_RECT(pcbnew.VECTOR2I(nm(x0), nm(y0)), nm(x1 - x0), nm(y1 - y0))


def outlines(polys) -> list[tuple[list, list[list]]]:
    """(outline points, [hole points]) per polygon of a SHAPE_POLY_SET, in mm."""
    out = []
    for i in range(polys.OutlineCount()):
        ol = polys.Outline(i)
        pts = [(mm(ol.CPoint(k).x), mm(ol.CPoint(k).y)) for k in range(ol.PointCount())]
        holes = []
        for h in range(polys.HoleCount(i)):
            hl = polys.Hole(i, h)
            holes.append([(mm(hl.CPoint(k).x), mm(hl.CPoint(k).y)) for k in range(hl.PointCount())])
        out.append((pts, holes))
    return out


def extent(polys) -> tuple[float, float, float, float]:
    """(x1, y1, x2, y2) of a SHAPE_POLY_SET's points, mm. Its own BBox() pads a courtyard's box."""
    pts = [pt for outline, _ in outlines(polys) for pt in outline]
    if not pts:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(x for x, _ in pts), min(y for _, y in pts), max(x for x, _ in pts), max(y for _, y in pts))


def box_of(polys) -> list[float]:
    x1, y1, x2, y2 = extent(polys)
    return [round(v, 4) for v in (x1, x2, y1, y2)]


# ------------------------------------------------------------------ connectivity


def touch(a: Item, b: Item) -> bool:
    """Whether two items of one net join on a layer they share, the way KiCad's connectivity has it:
    a track joins where one of its ends lies on the other item, or another item's anchor lies on it;
    other items join where their copper overlaps."""
    for layer in set(a.layers) & set(b.layers):
        sa, sb = a.shapes[layer], b.shapes[layer]
        if a.kind in ("track", "arc") or b.kind in ("track", "arc"):
            t, o = (a, b) if a.kind in ("track", "arc") else (b, a)
            st, so = t.shapes[layer], o.shapes[layer]
            if o.kind == "pour":
                if so.Collide(st, 0):
                    return True
                continue
            if any(so.Collide(p, 0) for p in t.ends()):
                return True
            anchors = o.ends() if o.kind in ("track", "arc") else [o.obj.GetPosition()]
            if any(st.Collide(p, 0) for p in anchors):
                return True
        elif a.kind == "pour" or b.kind == "pour":
            p, o = (a, b) if a.kind == "pour" else (b, a)
            if p.shapes[layer].Collide(o.shapes[layer], 0):
                return True
        elif sa.Collide(sb, 0):
            return True
    return False


def groups(items: list[Item]) -> list[list[Item]]:
    """The items joined to each other, one list per connected group, the group with most pads first."""
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            a, b = items[i], items[j]
            if find(i) == find(j) or not overlap(a.bbox, b.bbox):
                continue
            if touch(a, b):
                parent[find(j)] = find(i)
    out: dict[int, list[Item]] = {}
    for i, item in enumerate(items):
        out.setdefault(find(i), []).append(item)
    return sorted(
        out.values(),
        key=lambda g: (-sum(it.kind == "pad" for it in g), -sum(it.area for it in g), -len(g)),
    )


def overlap(a: tuple, b: tuple, margin: float = 0.01) -> bool:
    return a[0] <= b[2] + margin and b[0] <= a[2] + margin and a[1] <= b[3] + margin and b[1] <= a[3] + margin


def describe(group: list[Item]) -> dict:
    pads = [it.name for it in group if it.kind == "pad"]
    x1 = min(it.bbox[0] for it in group)
    y1 = min(it.bbox[1] for it in group)
    x2 = max(it.bbox[2] for it in group)
    y2 = max(it.bbox[3] for it in group)
    return {
        "pads": pads,
        "tracks": sum(it.kind in ("track", "arc") for it in group),
        "vias": [it.name for it in group if it.kind == "via"],
        "pours": [it.name for it in group if it.kind == "pour"],
        "box": [round(v, 3) for v in (x1, x2, y1, y2)],
    }


def net_report(board: Board, net: str) -> dict:
    net = board.net(net)
    items = board.items(net, pours=True)
    found = [describe(g) for g in groups(items)]
    joined = [g for g in found if g["pads"]]
    return {
        "net": net,
        "pads": sum(it.kind == "pad" for it in items),
        "tracks": sum(it.kind in ("track", "arc") for it in items),
        "vias": sum(it.kind == "via" for it in items),
        "pours": sum(it.kind == "pour" for it in items),
        "groups": found,
        "unconnected": max(len(joined) - 1, 0),
    }


# ------------------------------------------------------------------ commands


def cmd_list(board: Board, a: dict) -> tuple[dict, int]:
    rect = window(a["box"])
    layer = board.layer(a["layer"]) if a.get("layer") else None
    net = board.net(a["net"]) if a.get("net") else None
    rep: dict = {"board": str(board.path), "box": a["box"], "pads": [], "tracks": [], "vias": []}
    rep.update(courtyards=[], keepouts=[])
    for it in board.items(net):
        if layer and it.layers and layer not in it.layers:  # a non-plated hole passes every layer
            continue
        shapes = list(it.shapes.values()) or ([it.hole] if it.hole else [])
        if not any(s.Collide(rect, 0) for s in shapes):
            continue
        x1, y1, x2, y2 = it.bbox
        if it.kind in ("pad", "npth"):
            pos = it.obj.GetPosition()
            rep["pads"].append(
                {
                    "pad": it.name,
                    "net": it.net,
                    "at": [round(mm(pos.x), 4), round(mm(pos.y), 4)],
                    "box": [round(v, 4) for v in (x1, x2, y1, y2)],
                    "layers": it.layers or ["hole"],
                    "drill": round(mm(it.obj.GetDrillSizeX()), 4) if it.hole else 0.0,
                }
            )
        elif it.kind == "via":
            pos = it.obj.GetPosition()
            rep["vias"].append(
                {
                    "net": it.net,
                    "at": [round(mm(pos.x), 4), round(mm(pos.y), 4)],
                    "size": round(mm(it.obj.GetWidth(board.lid[it.layers[0]])), 4),
                    "drill": round(mm(it.obj.GetDrillValue()), 4),
                    "layers": [it.layers[0], it.layers[-1]],
                }
            )
        else:
            s, e = it.obj.GetStart(), it.obj.GetEnd()
            rep["tracks"].append(
                {
                    "net": it.net,
                    "layer": it.layers[0],
                    "start": [round(mm(s.x), 4), round(mm(s.y), 4)],
                    "end": [round(mm(e.x), 4), round(mm(e.y), 4)],
                    "width": round(mm(it.obj.GetWidth()), 4),
                    "length": round(mm(it.obj.GetLength()), 4),
                    "arc": it.kind == "arc",
                }
            )
    if not net:
        for ref, face, cy in board.courtyards():
            if (layer is None or layer == face) and cy.Collide(rect, 0):
                rep["courtyards"].append({"ref": ref, "face": face, "box": box_of(cy)})
        for area in board.areas():
            if (layer is None or layer in area.layers) and area.outline.Collide(rect, 0):
                rep["keepouts"].append(
                    {"name": area.name, "layers": area.layers, "no": area.no, "box": box_of(area.outline)}
                )
    return rep, 0


def text_list(rep: dict) -> str:
    x0, x1, y0, y1 = rep["box"]
    lines = [f"{where(rep['board'])}: x {x0}..{x1}, y {y0}..{y1}"]
    lines.append(f"pads: {len(rep['pads'])}")
    for p in sorted(rep["pads"], key=lambda p: p["pad"]):
        bx = p["box"]
        lines.append(
            f"  {p['pad']:8} {short(p['net']):12} {','.join(p['layers']):14}"
            f" at ({p['at'][0]:.3f}, {p['at'][1]:.3f})"
            f"  x {bx[0]:.3f}..{bx[1]:.3f} y {bx[2]:.3f}..{bx[3]:.3f}"
            + (f"  drill {p['drill']:.2f}" if p["drill"] else "")
        )
    lines.append(f"tracks: {len(rep['tracks'])}")
    for t in sorted(rep["tracks"], key=lambda t: (t["net"], t["layer"])):
        s, e = t["start"], t["end"]
        lines.append(
            f"  {short(t['net']):12} {t['layer']:7} ({s[0]:.3f}, {s[1]:.3f})-({e[0]:.3f}, {e[1]:.3f})"
            f"  w {t['width']:.3f}  {t['length']:.3f} mm" + ("  arc" if t["arc"] else "")
        )
    lines.append(f"vias: {len(rep['vias'])}")
    for v in sorted(rep["vias"], key=lambda v: v["net"]):
        lines.append(
            f"  {short(v['net']):12} ({v['at'][0]:.3f}, {v['at'][1]:.3f})  {v['size']:.2f}/{v['drill']:.2f}"
            f"  {v['layers'][0]}-{v['layers'][1]}"
        )
    lines.append(f"courtyards: {len(rep['courtyards'])}")
    for c in sorted(rep["courtyards"], key=lambda c: c["ref"]):
        bx = c["box"]
        lines.append(f"  {c['ref']:6} {c['face']:5} x {bx[0]:.3f}..{bx[1]:.3f} y {bx[2]:.3f}..{bx[3]:.3f}")
    lines.append(f"keep-outs: {len(rep['keepouts'])}")
    for k in rep["keepouts"]:
        bx = k["box"]
        lines.append(
            f"  {k['name']!r} on {','.join(k['layers'])}: no {', '.join(k['no']) or 'nothing'}"
            f"  x {bx[0]:.3f}..{bx[1]:.3f} y {bx[2]:.3f}..{bx[3]:.3f}"
        )
    return "\n".join(lines)


def candidate(board: Board, a: dict) -> tuple[str, list, list, object]:
    """What the probe places: (label, copper as [(item, layer, shape)], holes as [(item, shape)],
    the part's footprint or None). The copper items are real board items, so KiCad resolves their
    clearance from their net class."""
    if a.get("part"):
        fp = board.pcb.FindFootprintByReference(a["part"])
        new = fp is None
        if new:
            if not a.get("footprint"):
                raise InputError(
                    f"no part {a['part']} on {board.path.name}: a new part needs --footprint LIB:NAME"
                )
            fp = board.new_footprint(a["footprint"])
            fp.SetReference(a["part"])
            board.pcb.Add(fp)
            if a.get("back"):
                fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_TOP_BOTTOM)
            for number, net in (a.get("nets") or {}).items():
                pads = [pad for pad in fp.Pads() if pad.GetNumber() == number]
                if not pads:
                    raise InputError(f"{a['footprint']} has no pad {number}")
                for pad in pads:
                    pad.SetNet(board.pcb.FindNet(board.net(net)))
        x, y = a["at"]
        fp.SetPosition(pcbnew.VECTOR2I(nm(x), nm(y)))
        if a.get("rot") is not None:
            fp.SetOrientationDegrees(a["rot"])
        copper, holes = [], []
        for pad in fp.Pads():
            it = board.pad_item(fp, pad)
            copper += [(it, ly, s) for ly, s in it.shapes.items()]
            if it.hole is not None:
                holes.append((it, it.hole))
        side = "bottom" if fp.IsFlipped() else "top"
        what = f"new {a['footprint']}, " if new else ""
        angle = fp.GetOrientationDegrees() + 0.0  # a flipped part's -0 prints as 0
        label = f"part {fp.GetReference()} ({what}{side}) at ({x}, {y}) {angle:g} deg"
        return label, copper, holes, fp
    net = board.pcb.FindNet(board.net(a["net"]))
    if a.get("via"):
        x, y = a["via"]
        v = pcbnew.PCB_VIA(board.pcb)
        v.SetPosition(pcbnew.VECTOR2I(nm(x), nm(y)))
        v.SetLayerPair(board.lid[board.copper[0]], board.lid[board.copper[-1]])
        v.SetNet(net)
        size, drill = a.get("size"), a.get("drill")
        size = (
            nm(size)
            if size
            else board.class_value(net.GetNetname(), "via_diameter", board.ds.GetCurrentViaSize())
        )
        drill = (
            nm(drill)
            if drill
            else board.class_value(net.GetNetname(), "via_drill", board.ds.GetCurrentViaDrill())
        )
        v.SetWidth(size)
        v.SetDrill(drill)
        it = board.track_item(v)
        label = f"via {a['net']} at ({x}, {y}) {mm(size):.2f}/{mm(drill):.2f}"
        return label, [(it, ly, s) for ly, s in it.shapes.items()], [(it, it.hole)], None
    layer = board.layer(a["layer"])
    width = (
        nm(a["width"])
        if a.get("width")
        else board.class_value(net.GetNetname(), "track_width", board.ds.GetCurrentTrackWidth())
    )
    copper = []
    pts = a["track"]
    for (x1, y1), (x2, y2) in zip(pts, pts[1:], strict=False):
        t = pcbnew.PCB_TRACK(board.pcb)
        t.SetStart(pcbnew.VECTOR2I(nm(x1), nm(y1)))
        t.SetEnd(pcbnew.VECTOR2I(nm(x2), nm(y2)))
        t.SetWidth(width)
        t.SetLayer(board.lid[layer])
        t.SetNet(net)
        it = board.track_item(t)
        copper.append((it, layer, it.shapes[layer]))
    label = f"track {a['net']} on {layer} w{mm(width):.2f} " + " ".join(f"({x}, {y})" for x, y in pts)
    return label, copper, [], None


def cmd_probe(board: Board, a: dict) -> tuple[dict, int]:
    """Every conflict the candidate would have on the routed board, as the DRC would list it, and
    the keep-outs and courtyards it enters. Pours are left out: KiCad refills them round new copper."""
    # Taken before the part moves or arrives: a part on the board leaves its old place.
    others = board.items(pours=False, skip_ref=a.get("part") or "")
    label, copper, holes, fp = candidate(board, a)
    found: list[dict] = []

    def add(kind: str, layer: str, what: str, net: str, g: int | None, need: int, rule: str, by: str) -> None:
        found.append(
            {
                "kind": kind,
                "layer": layer,
                "item": what,
                "net": net,
                "gap": None if g is None else round(mm(g), 4),
                "need": round(mm(need), 4),
                "rule": rule,
                "by": by,
            }
        )

    for it, layer, shape in copper:
        for o in others:
            if layer not in o.shapes or (o.net == it.net and it.net):
                continue
            need, rule = board.copper_need(it.obj, o.obj, layer)
            g = gap(o.shapes[layer], shape, need)
            if g is not None and g < need - board.ds.GetDRCEpsilon():
                add("clearance", layer, o.name, o.net, g, need, rule, it.name)
        for o in others:  # other nets' holes against the new copper, on every layer it is on
            if o.hole is None or (o.net == it.net and it.net):
                continue
            need, rule = board.hole_need(layer)
            g = gap(o.hole, shape, need)
            if g is not None and g < need:
                add("hole", layer, f"{o.name} hole", o.net, g, need, rule, it.name)
        for name, edge in board.edges():
            need, rule = board.edge_need(layer)
            g = gap(edge, shape, need)
            if g is not None and g < need:
                add("edge", layer, name, "", g, need, rule, it.name)
    for it, hole in holes:
        for o in others:  # the new hole against other nets' copper on every layer
            if o.net == it.net and it.net:
                continue
            for layer, shape in o.shapes.items():
                need, rule = board.hole_need(layer)
                g = gap(shape, hole, need)
                if g is not None and g < need:
                    add("hole", layer, o.name, o.net, g, need, rule, f"{it.name} hole")
        need, rule = board.hole_to_hole()
        for o in others:
            if o.hole is None:
                continue
            g = gap(o.hole, hole, need)
            if g is not None and g < need:
                add("hole-hole", "", f"{o.name} hole", o.net, g, need, rule, f"{it.name} hole")
    for area in board.areas():
        for it, layer, shape in copper:
            if layer not in area.layers:
                continue
            what = {"via": "vias", "track": "tracks", "arc": "tracks", "pad": "pads"}[it.kind]
            if what in area.no and area.outline.Collide(shape, 0):
                add(
                    "keep-out",
                    layer,
                    f"keep-out {area.name!r} (no {what})",
                    "",
                    None,
                    0,
                    "rule area",
                    it.name,
                )
        if fp is not None and "footprints" in area.no:
            face = "B.Cu" if fp.IsFlipped() else "F.Cu"
            fp.BuildCourtyardCaches()
            cy = fp.GetCourtyard(pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd)
            if face in area.layers and cy.OutlineCount() and area.outline.Collide(cy, 0):
                add(
                    "keep-out",
                    face,
                    f"keep-out {area.name!r} (no footprints)",
                    "",
                    None,
                    0,
                    "rule area",
                    label,
                )
    if fp is not None:
        fp.BuildCourtyardCaches()
        face = "B.Cu" if fp.IsFlipped() else "F.Cu"
        mine = fp.GetCourtyard(pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd)
        for ref, other_face, cy in board.courtyards(skip_ref=fp.GetReference()):
            if other_face != face or not mine.OutlineCount() or not mine.Collide(cy, 0):
                continue
            both = pcbnew.SHAPE_POLY_SET(mine)
            both.BooleanIntersection(cy)
            x1, y1, x2, y2 = extent(both)
            size = f"{x2 - x1:.3f} x {y2 - y1:.3f} mm" if both.OutlineCount() else "edges touch"
            add(
                "courtyard",
                face,
                f"{ref} courtyard (overlap {size})",
                "",
                None,
                0,
                "courtyards",
                fp.GetReference(),
            )
    seen, unique = set(), []
    for f in found:
        key = (f["kind"], f["layer"], f["item"], f["by"])
        if key not in seen:
            seen.add(key)
            unique.append(f)
    rep = {
        "board": str(board.path),
        "probe": label,
        "conflicts": unique,
        "rules_file": str(board.dru) if board.dru else None,
        "rules_not_read": board.unread,
    }
    return rep, 1 if unique else 0


def text_probe(rep: dict) -> str:
    lines = [f"probe {rep['probe']}  (pours left out: they refill round new copper)"]
    for f in rep["conflicts"]:
        where = f"{f['layer']:7}" if f["layer"] else " " * 7
        if f["gap"] is None:
            lines.append(f"  {f['kind']:10} {where} {f['item']}  [{f['by']}]")
        else:
            net = f" ({short(f['net'])})" if f["net"] else ""
            lines.append(
                f"  {f['kind']:10} {where} {f['item']}{net}  gap {f['gap']:.3f} < {f['need']:.4f} mm"
                f"  {f['rule']}  [{f['by']}]"
            )
    if rep["rules_not_read"]:
        lines.append(f"  rules with a condition, not checked here: {', '.join(rep['rules_not_read'])}")
    n = len(rep["conflicts"])
    lines.append(f"probe: {n} conflict{'s' if n != 1 else ''}" if n else "probe: clear")
    return "\n".join(lines)


def cmd_net(board: Board, a: dict) -> tuple[dict, int]:
    rep = net_report(board, a["net"])
    return rep, 1 if rep["unconnected"] else 0


def text_net(rep: dict) -> str:
    joined = [g for g in rep["groups"] if g["pads"]]
    lines = [
        f"net {rep['net']}: {count(rep['pads'], 'pad')}, {count(rep['tracks'], 'track')}, "
        f"{count(rep['vias'], 'via')}, "
        f"{count(rep['pours'], 'pour piece')}; {count(len(joined), 'group')} with pads"
    ]
    for n, g in enumerate(rep["groups"], 1):
        bx = g["box"]
        what = "pads " + " ".join(g["pads"]) if g["pads"] else "no pad (dangling copper)"
        parts = (
            count(g["tracks"], "track"),
            count(len(g["vias"]), "via"),
            count(len(g["pours"]), "pour piece"),
        )
        extra = "; " + ", ".join(parts)
        lines.append(f"  group {n}: {what}{extra}; x {bx[0]:.2f}..{bx[1]:.2f} y {bx[2]:.2f}..{bx[3]:.2f}")
    if rep["unconnected"]:
        lines.append(f"unconnected: {rep['unconnected']} (the DRC's unconnected items for this net)")
    else:
        lines.append("connected")
    return "\n".join(lines)


def cmd_islands(board: Board, a: dict) -> tuple[dict, int]:
    net = board.net(a.get("net") or "GND")
    items = board.items(net, pours=True)
    pieces = [it for it in items if it.kind == "pour"]
    rep: dict = {"net": net, "layers": {}, "islands": []}
    if not pieces:
        rep["note"] = f"{net} has no filled pour"
        return rep, 0
    found = groups(items)
    main = max(found, key=lambda g: sum(it.area for it in g))
    for g in found:
        for p in (it for it in g if it.kind == "pour"):
            layer = p.layers[0]
            holds = list(
                dict.fromkeys(
                    it.name for it in g if it is not p and it.kind in ("pad", "via") and touch(p, it)
                )
            )
            state = "main" if g is main else ("island" if any(it.kind == "pad" for it in g) else "bare")
            piece = {
                "piece": p.name,
                "box": [round(v, 3) for v in (p.bbox[0], p.bbox[2], p.bbox[1], p.bbox[3])],
                "area": round(p.area, 3),
                "holds": holds,
                "state": state,
            }
            rep["layers"].setdefault(layer, []).append(piece)
    for g in found:
        if g is not main and any(it.kind == "pad" for it in g):
            rep["islands"].append(
                {
                    "pads": [it.name for it in g if it.kind == "pad"],
                    "vias": [it.name for it in g if it.kind == "via"],
                    "pieces": [it.name for it in g if it.kind == "pour"],
                }
            )
    for layer in rep["layers"]:
        rep["layers"][layer].sort(key=lambda p: -p["area"])
    return rep, 1 if rep["islands"] else 0


def text_islands(rep: dict) -> str:
    if "note" in rep:
        return rep["note"]
    lines = []
    for layer, pieces in rep["layers"].items():
        lines.append(f"{rep['net']} on {layer}: {len(pieces)} piece{'s' if len(pieces) != 1 else ''}")
        for p in pieces:
            bx = p["box"]
            holds = ", ".join(p["holds"]) or "nothing"
            lines.append(
                f"  {p['piece']:14} {p['state']:6} {p['area']:9.2f} mm²  x {bx[0]:.2f}..{bx[1]:.2f}"
                f" y {bx[2]:.2f}..{bx[3]:.2f}  holds {holds}"
            )
    for isl in rep["islands"]:
        vias = f" and {count(len(isl['vias']), 'via')} of their own" if isl["vias"] else ""
        lines.append(
            f"island: {' '.join(isl['pads'])}{vias} on {', '.join(isl['pieces']) or 'no piece'}: "
            "no via, pad or track joins it to the rest of the pour"
        )
    lines.append(f"islands: {len(rep['islands'])}")
    return "\n".join(lines)


# -- resistance


@dataclass
class Edge:
    to: tuple
    ohm: float
    kind: str  # track, via, pad
    note: dict


def seg_param(p: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    """(distance from p to segment ab, the parameter 0..1 of the nearest point)."""
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay), 0.0
    u = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + u * dx), py - (ay + u * dy)), u


def cmd_resistance(board: Board, a: dict) -> tuple[dict, int]:
    net = board.net(a["net"])
    temp = a.get("temp", 20.0)
    rho = RHO_20 * (1 + ALPHA * (temp - 20.0))
    plating = a["plating"] if a.get("plating") else mm(board.ds.GetHolePlatingThickness())
    items = board.items(net)
    graph: dict[tuple, list[Edge]] = {}

    def link(u: tuple, v: tuple, ohm: float, kind: str, note: dict) -> None:
        graph.setdefault(u, []).append(Edge(v, ohm, kind, note))
        graph.setdefault(v, []).append(Edge(u, ohm, kind, {**note, "reverse": True}))

    def key(layer: str, x: float, y: float) -> tuple:
        return (layer, round(x, 6), round(y, 6))

    def barrel(drill: float, z1: float, z2: float) -> tuple[float, float]:
        r = drill / 2
        area = math.pi * ((r + plating) ** 2 - r**2) * 1e-6
        return rho * abs(z2 - z1) * 1e-3 / area, abs(z2 - z1)

    tracks = [it for it in items if it.kind in ("track", "arc")]
    vias = [it for it in items if it.kind == "via"]
    pads = [it for it in items if it.kind == "pad"]
    pos = {id(it): (mm(it.obj.GetPosition().x), mm(it.obj.GetPosition().y)) for it in vias + pads}
    ends = {id(t): [(mm(p.x), mm(p.y)) for p in (t.obj.GetStart(), t.obj.GetEnd())] for t in tracks}
    for t in tracks:
        layer, w = t.layers[0], mm(t.obj.GetWidth())
        cu = board.cu[layer].thickness
        a0, b0 = ends[id(t)]
        splits = {0.0: a0, 1.0: b0}
        if t.kind == "track":
            # Where another track's end, a via or a pad's centre sits on this one, it joins mid-run.
            anchors = [p for o in tracks if o is not t and o.layers[0] == layer for p in ends[id(o)]]
            anchors += [pos[id(o)] for o in vias + pads if layer in o.layers]
            for p in anchors:
                d, u = seg_param(p, a0, b0)
                if d <= w / 2 + 1e-6:
                    q = (a0[0] + u * (b0[0] - a0[0]), a0[1] + u * (b0[1] - a0[1]))
                    splits[u] = q
                    if math.hypot(p[0] - q[0], p[1] - q[1]) > 1e-9:
                        link(key(layer, *p), key(layer, *q), 0.0, "pad", {"layer": layer})
            run = sorted(splits.items())
            for (_, p), (_, q) in zip(run, run[1:], strict=False):
                ln = math.hypot(q[0] - p[0], q[1] - p[1])
                ohm = rho * ln * 1e-3 / (w * 1e-3 * cu * 1e-3)
                link(
                    key(layer, *p),
                    key(layer, *q),
                    ohm,
                    "track",
                    {"layer": layer, "w": w, "t": cu, "a": p, "b": q},
                )
        else:
            ln = mm(t.obj.GetLength())
            ohm = rho * ln * 1e-3 / (w * 1e-3 * cu * 1e-3)
            note = {"layer": layer, "w": w, "t": cu, "a": a0, "b": b0, "arc": ln}
            link(key(layer, *a0), key(layer, *b0), ohm, "track", note)
    for it in vias + pads:
        x, y = pos[id(it)]
        for layer in it.layers:
            here = key(layer, x, y)
            graph.setdefault(here, [])
            for t in tracks:
                if t.layers[0] != layer:
                    continue
                w, cu = mm(t.obj.GetWidth()), board.cu[layer].thickness
                for p in ends[id(t)]:
                    if not it.shapes[layer].Collide(pcbnew.VECTOR2I(nm(p[0]), nm(p[1])), 0):
                        continue
                    # A track that ends off the centre is measured on to it, as a hand calculation
                    # does; the pad's or via's own copper is taken as ideal.
                    ln = math.hypot(p[0] - x, p[1] - y)
                    ohm = rho * ln * 1e-3 / (w * 1e-3 * cu * 1e-3)
                    note = {"layer": layer, "w": w, "t": cu, "a": (x, y), "b": p}
                    link(here, key(layer, *p), ohm, "track" if ln > 1e-9 else "pad", note)
        if it.hole is not None and len(it.layers) > 1:
            drill = mm(it.obj.GetDrillValue() if it.kind == "via" else it.obj.GetDrillSizeX())
            for l1, l2 in zip(it.layers, it.layers[1:], strict=False):
                ohm, ln = barrel(drill, board.cu[l1].z, board.cu[l2].z)
                note = {"from": l1, "to": l2, "drill": drill, "length": ln, "at": (x, y), "name": it.name}
                link(key(l1, x, y), key(l2, x, y), ohm, "via", note)
    for v in vias:  # a via in a pad
        x, y = pos[id(v)]
        for p in pads:
            for layer in set(v.layers) & set(p.layers):
                if p.shapes[layer].Collide(pcbnew.VECTOR2I(nm(x), nm(y)), 0):
                    link(key(layer, x, y), key(layer, *pos[id(p)]), 0.0, "pad", {"layer": layer})

    def pad_nodes(name: str) -> list[tuple]:
        found = [p for p in pads if p.name == name]
        if not found:
            raise InputError(f"no pad {name} on net {net}")
        return [key(ly, *pos[id(p)]) for p in found for ly in p.layers]

    src, dst = pad_nodes(a["from"]), set(pad_nodes(a["to"]))
    best: dict[tuple, float] = {}
    prev: dict[tuple, tuple[tuple, Edge] | None] = {}
    heap = []
    for s in src:
        best[s] = 0.0
        prev[s] = None
        heapq.heappush(heap, (0.0, s))
    end = None
    while heap:
        d, u = heapq.heappop(heap)
        if d > best.get(u, math.inf):
            continue
        if u in dst:
            end = u
            break
        for e in graph.get(u, []):
            nd = d + e.ohm
            if nd < best.get(e.to, math.inf) - 1e-15:
                best[e.to] = nd
                prev[e.to] = (u, e)
                heapq.heappush(heap, (nd, e.to))
    pours = sum(1 for z in board.pcb.Zones() if not z.GetIsRuleArea() and z.GetNetname() == net)
    rep: dict = {
        "net": net,
        "from": a["from"],
        "to": a["to"],
        "temperature": temp,
        "rho": rho,
        "alpha": ALPHA,
        "plating": plating,
        "stackup": {ly: round(c.thickness * 1000, 2) for ly, c in board.cu.items() if ly in board.copper},
        "stackup_from_board": board.has_stackup,
        "pours_not_counted": pours,
    }
    if end is None:
        rep["path"] = None
        return rep, 1
    chain = []
    k = end
    while prev[k] is not None:
        u, e = prev[k]
        chain.append(e)
        k = u
    chain.reverse()
    steps: list[dict] = []
    for e in chain:
        if e.kind == "pad":
            continue
        n = e.note
        if e.kind == "track":
            a0, b0 = (n["b"], n["a"]) if n.get("reverse") else (n["a"], n["b"])
            ln = n.get("arc") or math.hypot(b0[0] - a0[0], b0[1] - a0[1])
            last = steps[-1] if steps else None
            if last and last["kind"] == "track" and last["layer"] == n["layer"] and last["width"] == n["w"]:
                last["length"] += ln
                last["ohm"] += e.ohm
                last["end"] = list(b0)
                last["segments"] += 1
                continue
            steps.append(
                {
                    "kind": "track",
                    "layer": n["layer"],
                    "width": n["w"],
                    "thickness": n["t"],
                    "start": list(a0),
                    "end": list(b0),
                    "length": ln,
                    "ohm": e.ohm,
                    "segments": 1,
                }
            )
        else:
            l1, l2 = (n["to"], n["from"]) if n.get("reverse") else (n["from"], n["to"])
            last = steps[-1] if steps else None
            if last and last["kind"] == "via" and last["name"] == n["name"] and last["to"] == l1:
                last["to"] = l2
                last["length"] += n["length"]
                last["ohm"] += e.ohm
                continue
            steps.append(
                {
                    "kind": "via",
                    "name": n["name"],
                    "from": l1,
                    "to": l2,
                    "drill": n["drill"],
                    "length": n["length"],
                    "ohm": e.ohm,
                }
            )
    for s in steps:
        s["length"] = round(s["length"], 4)
        s["ohm"] = round(s["ohm"], 7)
    rep["path"] = steps
    rep["ohm"] = round(best[end], 7)
    rep["track_length"] = round(sum(s["length"] for s in steps if s["kind"] == "track"), 4)
    rep["barrels"] = sum(s["kind"] == "via" for s in steps)
    return rep, 0


def text_resistance(rep: dict) -> str:
    head = (
        f"resistance {rep['net']} {rep['from']} -> {rep['to']} at {rep['temperature']:g} °C: copper "
        f"{RHO_20:.3g} Ohm m at 20 °C, +{rep['alpha'] * 100:.3f} %/°C; "
        f"via plating {rep['plating'] * 1000:g} µm"
    )
    cu = ", ".join(f"{ly} {t:g} µm" for ly, t in rep["stackup"].items())
    lines = [
        head,
        f"  copper: {cu}"
        + ("" if rep["stackup_from_board"] else " (no stackup on the board: KiCad's default)"),
    ]
    if rep["path"] is None:
        lines.append(
            f"no track path from {rep['from']} to {rep['to']}: they join through a pour, or not at all"
        )
        return "\n".join(lines)
    for s in rep["path"]:
        if s["kind"] == "track":
            a0, b0 = s["start"], s["end"]
            segs = f", {s['segments']} segments" if s["segments"] > 1 else ""
            lines.append(
                f"  {s['layer']:7} ({a0[0]:.3f}, {a0[1]:.3f})-({b0[0]:.3f}, {b0[1]:.3f})  "
                f"{s['length']:.3f} mm x "
                f"{s['width']:.3f} mm x {s['thickness'] * 1000:g} µm{segs}  {s['ohm'] * 1000:.2f} mOhm"
            )
        else:
            lines.append(
                f"  via     {s['name']} {s['from']} to {s['to']}  {s['drill']:.3f} mm hole, "
                f"{s['length']:.3f} mm of barrel  {s['ohm'] * 1000:.2f} mOhm"
            )
    lines.append(
        f"total {rep['ohm'] * 1000:.2f} mOhm: {rep['track_length']:.3f} mm of track and "
        f"{rep['barrels']} via barrel(s), pads taken as ideal"
    )
    note = "the path of least resistance; copper in parallel with it lowers the figure"
    if rep["pours_not_counted"]:
        note += f"; {rep['pours_not_counted']} pour(s) of the net not counted"
    lines.append(f"  {note}")
    return "\n".join(lines)


def cmd_crossed(board: Board, a: dict) -> tuple[dict, int]:
    rect = window(a["box"])
    nets: dict[str, dict] = {}
    for t in board.pcb.GetTracks():
        it = board.track_item(t)
        if not it.net or not any(s.Collide(rect, 0) for s in it.shapes.values()):
            continue
        rec = nets.setdefault(it.net, {"net": it.net, "tracks": 0, "vias": 0, "layers": set()})
        if it.kind == "via":
            rec["vias"] += 1
        else:
            rec["tracks"] += 1
            rec["layers"].add(it.layers[0])
    rep: dict = {"board": str(board.path), "box": a["box"], "new": a.get("new"), "nets": []}
    new = Board(Path(a["new"])) if a.get("new") else None
    code = 0
    for name in sorted(nets):
        rec = nets[name]
        rec["layers"] = [ly for ly in board.copper if ly in rec["layers"]]
        if new is not None:
            if new.pcb.FindNet(name) is None:
                rec["new"] = "not on the new board"
            else:
                r = net_report(new, name)
                still = any(
                    s.Collide(window(a["box"]), 0)
                    for t in new.pcb.GetTracks()
                    if t.GetNetname() == name
                    for s in new.track_item(t).shapes.values()
                )
                rec["crosses_new"] = still
                if r["unconnected"]:
                    cut = [g["pads"] for g in r["groups"] if g["pads"]]
                    rec["new"] = f"open: {r['unconnected']} unconnected, groups " + " | ".join(
                        " ".join(g) for g in cut
                    )
                    code = 1
                else:
                    rec["new"] = "connected"
        rep["nets"].append(rec)
    return rep, code


def text_crossed(rep: dict) -> str:
    x0, x1, y0, y1 = rep["box"]
    lines = [f"{where(rep['board'])}: nets whose copper crosses x {x0}..{x1}, y {y0}..{y1}"]
    for rec in rep["nets"]:
        on = ",".join(rec["layers"]) or "-"
        line = f"  {rec['net']:16} {count(rec['tracks'], 'track')} on {on}, {count(rec['vias'], 'via')}"
        if "new" in rec:
            line += f"; new board: {rec['new']}"
            if rec.get("crosses_new") is not None:
                line += ", still crosses" if rec["crosses_new"] else ", no longer crosses"
        lines.append(line)
    if rep["new"]:
        open_ = [r["net"] for r in rep["nets"] if r.get("new", "").startswith(("open", "not on"))]
        lines.append(f"open on {where(rep['new'])}: {', '.join(open_) or 'none'}")
    return "\n".join(lines)


# -- map


def colour(net: str) -> tuple[int, int, int]:
    if net == "GND":
        return (120, 120, 120)
    if not net:
        return (60, 60, 60)
    return PALETTE[zlib.crc32(net.encode()) % len(PALETTE)]


def cmd_map(board: Board, a: dict) -> tuple[dict, int]:
    from PIL import Image, ImageDraw, ImageFont

    x0, x1, y0, y1 = a["box"]
    k = float(a.get("scale") or 60)
    k = min(k, MAX_PX / max(x1 - x0, y1 - y0))
    inner = (max(1, round((x1 - x0) * k)), max(1, round((y1 - y0) * k)))
    left, top, right = 48, 24, 12
    out = Path(a["out"])
    out.mkdir(parents=True, exist_ok=True)
    layers = [board.layer(ly) for ly in a["layers"]] if a.get("layers") else list(board.copper)
    font = ImageFont.load_default(size=max(9, min(14, int(k / 6))))
    small = ImageFont.load_default(size=max(9, min(12, int(k / 7))))
    caption_font = ImageFont.load_default(size=12)
    items = board.items(pours=False)
    pours = board.pour_pieces()
    areas = board.areas()
    courts = board.courtyards()
    edge = pcbnew.SHAPE_POLY_SET()
    board.pcb.GetBoardPolygonOutlines(edge, False)
    rect = window(a["box"])
    written = []

    def P(x: float, y: float) -> tuple[float, float]:  # board mm to the window's pixels
        return ((x - x0) * k, (y - y0) * k)

    def poly(draw, pts, **kw) -> None:
        if len(pts) > 2:
            draw.polygon([P(x, y) for x, y in pts], **kw)

    def item_polys(it: Item, layer: str):
        buf = pcbnew.SHAPE_POLY_SET()
        it.obj.TransformShapeToPolygon(buf, board.lid[layer], 0, 2000, pcbnew.ERROR_INSIDE)
        return outlines(buf)

    def hole(draw, shape) -> None:
        seg = shape.GetSeg()
        r = mm(shape.GetWidth()) / 2
        (ax, ay), (bx, by) = (mm(seg.A.x), mm(seg.A.y)), (mm(seg.B.x), mm(seg.B.y))
        draw.line([P(ax, ay), P(bx, by)], fill=(255, 255, 255), width=max(1, int(2 * r * k)))
        for cx, cy in ((ax, ay), (bx, by)):
            draw.ellipse([P(cx - r, cy - r), P(cx + r, cy + r)], fill=(255, 255, 255))

    for layer in layers:
        # RGB, so that ImageDraw's "RGBA" mode blends each colour over what is already drawn.
        img = Image.new("RGB", inner, (255, 255, 255))
        d = ImageDraw.Draw(img, "RGBA")
        labels: list[tuple[tuple[float, float], str, tuple]] = []
        for gx in range(math.ceil(x0), math.floor(x1) + 1):
            d.line([P(gx, y0), P(gx, y1)], fill=(150, 150, 150) if gx % 5 == 0 else (215, 215, 215), width=1)
        for gy in range(math.ceil(y0), math.floor(y1) + 1):
            d.line([P(x0, gy), P(x1, gy)], fill=(150, 150, 150) if gy % 5 == 0 else (215, 215, 215), width=1)
        for p in pours:
            if p.layers != [layer] or not p.obj.Collide(rect, 0):
                continue
            c = colour(p.net)
            for pts, holes in outlines(p.obj):
                mask = Image.new("L", inner, 0)
                md = ImageDraw.Draw(mask)
                poly(md, pts, fill=60)
                for h in holes:
                    poly(md, h, fill=0)
                img.paste(Image.new("RGB", inner, c), (0, 0), mask)
            bb = p.bbox
            spot = (min(max((bb[0] + bb[2]) / 2, x0 + 0.6), x1 - 0.6), max(bb[1], y0) + 0.3)
            labels.append((spot, f"pour {short(p.net)}", c))
        d = ImageDraw.Draw(img, "RGBA")
        face = {"F.Cu": "F.Cu", "B.Cu": "B.Cu"}.get(layer)
        for ref, side, cy in courts:
            if not cy.Collide(rect, 0):
                continue
            mine = face is None or side == face
            for pts, _ in outlines(cy):
                poly(
                    d,
                    pts,
                    fill=(244, 194, 122, 70) if mine else None,
                    outline=(160, 82, 45, 255) if mine else (200, 185, 170, 255),
                )
            bx1, by1, bx2, _ = extent(cy)
            spot = ((bx1 + bx2) / 2, by1 + 0.25)
            labels.append((spot, ref if mine else f"({ref})", (120, 60, 20) if mine else (150, 130, 110)))
        for area in areas:
            if layer not in area.layers or not area.outline.Collide(rect, 0):
                continue
            for pts, _ in outlines(area.outline):
                poly(d, pts, fill=(150, 0, 150, 30), outline=(150, 0, 150, 255), width=2)
            bx1, _, bx2, by2 = extent(area.outline)
            spot = ((bx1 + bx2) / 2, by2 - 0.4)
            labels.append((spot, f"keep-out {area.name}: no {', '.join(area.no)}", (120, 0, 120)))
        for it in items:
            if layer not in it.shapes or not it.shapes[layer].Collide(rect, 0):
                continue
            c = colour(it.net)
            for pts, _ in item_polys(it, layer):
                poly(d, pts, fill=(*c, 170 if it.kind == "pad" else 200), outline=(*c, 255))
            if it.hole is not None:
                hole(d, it.hole)
            if it.kind == "pad":
                p = it.obj.GetPosition()
                labels.append(((mm(p.x), mm(p.y)), f"{it.name} {short(it.net)}", (0, 0, 0)))
            elif it.kind == "via":
                p = it.obj.GetPosition()
                labels.append(((mm(p.x), mm(p.y) + 0.45), short(it.net), (0, 70, 0)))
            elif mm(it.obj.GetLength()) >= 1.0:
                s, e = it.obj.GetStart(), it.obj.GetEnd()
                labels.append(((mm(s.x + e.x) / 2, mm(s.y + e.y) / 2), short(it.net), (0, 0, 110)))
        for it in items:
            if it.kind == "npth" and it.hole.Collide(rect, 0):
                hole(d, it.hole)
        for pts, holes in outlines(edge):
            for ring in [pts, *holes]:
                d.line([P(x, y) for x, y in [*ring, ring[0]]], fill=(0, 0, 0), width=2)
        for (x, y), text, col in labels:
            if not (x0 <= x <= x1 and y0 <= y <= y1):
                continue
            px, py = P(x, y)
            bx1, by1, bx2, by2 = d.textbbox((px, py), text, font=font, anchor="mm")
            d.rectangle([bx1 - 1, by1 - 1, bx2 + 1, by2 + 1], fill=(255, 255, 255, 170))
            d.text((px, py), text, fill=col, font=font, anchor="mm")
        # The frame: the window, its axes in mm, and what the picture shows.
        seen = "seen from the top" + (", not mirrored" if layer != board.copper[0] else "")
        caption = [
            f"{board.path.parent.name}/{board.path.name}  {layer}, {seen}",
            f"x {x0:g}..{x1:g}, y {y0:g}..{y1:g} mm, 1 mm grid; courtyards brown, (REF) on the other face; "
            "keep-outs purple; pours tinted by net",
        ]
        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        text_w = max(probe.textbbox((0, 0), ln, font=caption_font)[2] for ln in caption)
        width = max(left + inner[0] + right, left + text_w + right)
        height = top + inner[1] + 14 + 18 * len(caption)
        frame = Image.new("RGB", (width, height), (255, 255, 255))
        frame.paste(img, (left, top))
        fd = ImageDraw.Draw(frame)
        fd.rectangle([left - 1, top - 1, left + inner[0], top + inner[1]], outline=(0, 0, 0))
        step = 1 if k >= 25 else 5
        for gx in range(math.ceil(x0), math.floor(x1) + 1):
            if gx % step == 0:
                fd.text((left + (gx - x0) * k, top - 4), str(gx), fill=(0, 0, 0), font=small, anchor="mb")
        for gy in range(math.ceil(y0), math.floor(y1) + 1):
            if gy % step == 0:
                fd.text((left - 5, top + (gy - y0) * k), str(gy), fill=(0, 0, 0), font=small, anchor="rm")
        for n, ln in enumerate(caption):
            fd.text((left, top + inner[1] + 12 + 18 * n), ln, fill=(0, 0, 0), font=caption_font, anchor="lt")
        path = out / f"{layer.replace('.', '-')}.png"
        frame.save(path)
        written.append(str(path))
    return {"board": str(board.path), "box": a["box"], "scale": round(k, 2), "files": written}, 0


def text_map(rep: dict) -> str:
    return "\n".join(f"wrote {f}" for f in rep["files"])


COMMANDS = {
    "list": (cmd_list, text_list),
    "map": (cmd_map, text_map),
    "probe": (cmd_probe, text_probe),
    "net": (cmd_net, text_net),
    "islands": (cmd_islands, text_islands),
    "resistance": (cmd_resistance, text_resistance),
    "crossed": (cmd_crossed, text_crossed),
}


def main(argv: list[str]) -> int:
    a = json.loads(argv[1])
    if pcbnew is None:
        print("inspect: KiCad's pcbnew module is not importable here", file=sys.stderr)
        return 2
    if a["what"] == "map":
        try:
            import PIL  # noqa: F401
        except ImportError:
            print("inspect: Pillow is not importable here; map draws with it", file=sys.stderr)
            return 2
    run, text = COMMANDS[a["what"]]
    try:
        rep, code = run(Board(Path(a["board"])), a)
    except InputError as exc:
        print(f"inspect {a['what']}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(rep, indent=2, default=list) if a.get("json") else text(rep))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
