#!/usr/bin/env python3
"""legend — every text printed on a board, judged for whether it can be read, and a placer for designators.

The legend is the board's silkscreen text: each part's designator, a value printed on it, and the texts a
design adds. `judge` holds each to 5 rules and gives 1 line per failure:

    size       its height and stroke under the least the board's fab prints, read from the fab's own page
               (its rule set in rules/); a board that names no fab is held to the largest least of them all
    overlap    on another text, on a pad's opening in the solder mask, on a hole, or over the board's edge
    hidden     a designator under a part's courtyard or body, its own or another's
    nearest    a designator nearer another part than its own, or further from its own than the reach of
               rules/legend.json
    direction  text in more than 2 directions on 1 side, and text on the back that is not mirrored

A text's box is measured for KiCad's stroke font: each character 1.34 / 1.27 of the glyph width
(kicadgen.TEXT_ADVANCE), plus the stroke; the glyph height plus the stroke. A text in another font, or of
more than 1 line, is not measured: it is printed as not judged with the reason.

`place` puts each designator itself, the same on every run: for each part, largest first, it tries 8
places round the part's courtyard (above, right, below, left, then the 4 corners), upright and then turned
a quarter, and takes the first that breaks no rule. Where none fits it makes the text smaller, down to the
fab's least height; where that does not fit either the designator goes to the part's Fab layer, and 1 line
names the part. A designator fixed by hand is left where it is, and still judged.

`gate` is the DRC gate's part (tools/workcenter): this module's findings, and KiCad's own legend checks
(text height and thickness, silkscreen overlap, silkscreen clipped by the mask or the edge) as failures.
Standard library only.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import kicadgen
from kicadgen import Q, atoms, child, children, fmt

ROOT = Path(__file__).resolve().parent.parent
RULES = ROOT / "rules"
PACK = RULES / "legend.json"
SILK = ("F.SilkS", "B.SilkS")
ADVANCE = kicadgen.TEXT_ADVANCE / 1.27  # a character's advance over its glyph width, KiCad's stroke font
EPS = 1e-6
SPOTS = ("above", "right", "below", "left", "above left", "above right", "below right", "below left")
# KiCad's own DRC checks of the legend (the `type` of a violation in kicad-cli's JSON report), and the
# rule of this module each one is.
KICAD_CHECKS = {
    "text_height": "size",
    "text_thickness": "size",
    "silk_overlap": "overlap",
    "silk_over_copper": "overlap",
    "silk_edge_clearance": "overlap",
}

Box = tuple[float, float, float, float]  # x1, y1, x2, y2

# ---------------------------------------------------------------- the limits


@dataclass
class Limit:
    height: float | None
    stroke: float | None
    height_source: str
    stroke_source: str
    label: str


def read_fab(path: Path) -> dict:
    """The least text height and stroke a fab's rule set names for the legend, with its page."""
    text = path.read_text(encoding="utf-8")
    url = re.search(r"https://\S+?(?=[\s,)]|$)", text)
    read = re.search(r"read (\d{4}-\d{2}-\d{2})", text)
    page = f"{path.stem}: {url.group(0) if url else 'no page named'}"
    if read:
        page += f", read {read.group(1)}"
    page += f" (rules/{path.name})"
    out: dict = {"name": path.stem, "page": page, "height": None, "stroke": None}
    for chunk in re.split(r"\n(?=\(rule )", text):
        if not chunk.startswith("(rule ") or "Silkscreen" not in chunk:
            continue
        for key, constraint in (("height", "text_height"), ("stroke", "text_thickness")):
            m = re.search(rf"\(constraint {constraint} \(min ([\d.]+)mm\)\)", chunk)
            if m:
                out[key] = float(m.group(1))
    return out


def known_fabs() -> list[dict]:
    return [read_fab(p) for p in sorted(RULES.glob("*.kicad_dru"))]


def limits(fab: str | None) -> Limit:
    """The least height and stroke of the legend: the named fab's, or, with no fab, the least of the fabs
    in rules/ for each (the owner's word of 2026-11-17). A board that names its fab is held to that fab."""
    if fab:
        f = read_fab(kicadgen.fab_rules(fab))
        return Limit(f["height"], f["stroke"], f["page"], f["page"], f"fab {f['name']}")
    fabs = known_fabs()
    low = min((f for f in fabs if f["height"] is not None), key=lambda f: f["height"], default=None)
    thin = min((f for f in fabs if f["stroke"] is not None), key=lambda f: f["stroke"], default=None)
    return Limit(
        low["height"] if low else None,
        thin["stroke"] if thin else None,
        low["page"] if low else "",
        thin["page"] if thin else "",
        f"no fab named: held to the least of the {len(fabs)} fabs the workcenter knows "
        f"(height {low['name'] if low else 'none'}, stroke {thin['name'] if thin else 'none'})",
    )


def fab_named(project_dir: Path, name: str) -> str | None:
    """The fab a project names: the rule set `workcenter design` copied in as <name>.kicad_dru."""
    dru = project_dir / f"{name}.kicad_dru"
    if not dru.is_file():
        return None
    m = re.search(r"Copied by the workcenter from (\S+)\.kicad_dru", dru.read_text(encoding="utf-8"))
    return m.group(1) if m and (RULES / f"{m.group(1)}.kicad_dru").is_file() else None


def read_pack(path: Path = PACK) -> dict[str, float]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: float(v["value"]) for k, v in data.items() if isinstance(v, dict)}


# ---------------------------------------------------------------- the board


@dataclass
class Text:
    kind: str  # designator | value | text
    owner: str  # the part's designator, "" for a board text
    text: str
    x: float  # the anchor, on the board
    y: float
    angle: float
    layer: str
    h: float  # glyph height
    w: float  # glyph width
    t: float  # stroke
    mirrored: bool
    justify: int  # -1 left, 0 centre, 1 right
    face: str  # a font other than KiCad's stroke font
    node: list | None = None

    @property
    def what(self) -> str:
        if self.kind == "designator":
            return f"designator {self.owner}"
        if self.kind == "value":
            return f'value of {self.owner} "{self.text}"'
        return f'text "{self.text}"'

    @property
    def unmeasured(self) -> str:
        if self.face:
            return f"its font {self.face!r} is not KiCad's stroke font, whose size the tool measures"
        if "\n" in self.text or "\\n" in self.text:
            return "it has more than 1 line; the tool measures 1"
        return ""

    @property
    def box(self) -> Box:
        return text_box(
            self.x, self.y, self.angle, len(self.text), self.h, self.w, self.t, self.justify, self.mirrored
        )

    @property
    def side(self) -> str:
        return self.layer[0]


def text_box(x, y, angle, chars, h, w, t, justify=0, mirrored=False) -> Box:
    """A text's box on the board: `chars` characters of glyph height `h`, width `w`, stroke `t`."""
    width, height = chars * ADVANCE * w + t, h + t
    a = math.radians(angle)
    ux, uy = math.cos(a), -math.sin(a)  # the reading direction; y grows down the board
    # A left-justified text starts at its anchor, a right-justified one ends there; mirrored, the reverse.
    shift = -justify * (width / 2) * (-1 if mirrored else 1)
    cx, cy = x + shift * ux, y + shift * uy
    c, s = abs(math.cos(a)), abs(math.sin(a))
    c, s = (0.0 if c < 1e-9 else c), (0.0 if s < 1e-9 else s)
    hx, hy = c * width / 2 + s * height / 2, s * width / 2 + c * height / 2
    return (cx - hx, cy - hy, cx + hx, cy + hy)


@dataclass
class Part:
    ref: str
    side: str  # F or B
    x: float
    y: float
    rot: float
    box: Box  # courtyard and body, on the board
    node: list = field(repr=False, default_factory=list)

    @property
    def area(self) -> float:
        return (self.box[2] - self.box[0]) * (self.box[3] - self.box[1])


@dataclass
class Board:
    texts: list[Text] = field(default_factory=list)
    parts: list[Part] = field(default_factory=list)
    openings: list[tuple[str, Box, str]] = field(default_factory=list)  # side (F, B), box, what
    holes: list[tuple[Box, str]] = field(default_factory=list)
    edges: list[tuple[tuple[float, float], tuple[float, float]]] = field(default_factory=list)

    @property
    def outline(self) -> Box | None:
        if not self.edges:
            return None
        xs = [p[0] for e in self.edges for p in e]
        ys = [p[1] for e in self.edges for p in e]
        return (min(xs), min(ys), max(xs), max(ys))


def _f(node, i: int = 0, default: float = 0.0) -> float:
    a = atoms(node) if node else []
    return float(a[i]) if len(a) > i else default


def _xy(node) -> tuple[float, float]:
    return (_f(node, 0), _f(node, 1))


def to_board(fx: float, fy: float, rot: float, px: float, py: float) -> tuple[float, float]:
    """A point of a footprint's own frame on the board, as tools/boardrules.py and KiCad place it."""
    r = math.radians(rot)
    return (fx + px * math.cos(r) + py * math.sin(r), fy - px * math.sin(r) + py * math.cos(r))


def to_local(fx: float, fy: float, rot: float, bx: float, by: float) -> tuple[float, float]:
    r = math.radians(rot)
    dx, dy = bx - fx, by - fy
    return (dx * math.cos(r) - dy * math.sin(r), dx * math.sin(r) + dy * math.cos(r))


def _layer(node) -> str:
    found = child(node, "layer")
    return str(atoms(found)[0]) if found else ""


def _hidden(node) -> bool:
    if child(node, "hide") is not None and "yes" in atoms(child(node, "hide")):
        return True
    if "hide" in atoms(node):
        return True
    eff = child(node, "effects")
    if eff is None:
        return False
    h = child(eff, "hide")
    return "hide" in atoms(eff) or (h is not None and "no" not in atoms(h))


def _text(node, kind: str, owner: str, text: str, origin=None) -> Text:
    at = atoms(child(node, "at"))
    x, y = float(at[0]), float(at[1])
    angle = float(at[2]) if len(at) > 2 else 0.0
    if origin:
        x, y = to_board(*origin, x, y)
    eff = child(node, "effects") or ["effects"]
    font = child(eff, "font") or ["font"]
    size = child(font, "size")
    h, w = (_f(size, 0, 1.0), _f(size, 1, 1.0)) if size else (1.0, 1.0)
    t = _f(child(font, "thickness"), 0, 0.15) if child(font, "thickness") else round(h * 0.15, 6)
    face = child(font, "face")
    just = [str(a) for a in atoms(child(eff, "justify") or ["justify"])]
    return Text(
        kind,
        owner,
        text,
        x,
        y,
        angle,
        _layer(node),
        h,
        w,
        t,
        "mirror" in just,
        -1 if "left" in just else 1 if "right" in just else 0,
        str(atoms(face)[0]) if face else "",
        node,
    )


def _shape_points(shape) -> list[tuple[float, float]]:
    pts = [_xy(child(shape, h)) for h in ("start", "end", "mid") if child(shape, h)]
    if child(shape, "pts"):
        pts += [_xy(xy) for xy in children(child(shape, "pts"), "xy")]
    if shape[0] in ("fp_circle", "gr_circle") and child(shape, "center") and child(shape, "end"):
        (cx, cy), (ex, ey) = _xy(child(shape, "center")), _xy(child(shape, "end"))
        r = math.hypot(ex - cx, ey - cy)
        pts = [(cx + sx * r, cy + sy * r) for sx in (-1, 1) for sy in (-1, 1)]
    return pts


def _pad_box(cx: float, cy: float, w: float, h: float, angle: float) -> Box:
    a = math.radians(angle)
    c, s = abs(math.cos(a)), abs(math.sin(a))
    hx, hy = c * w / 2 + s * h / 2, s * w / 2 + c * h / 2
    return (cx - hx, cy - hy, cx + hx, cy + hy)


def read_board(root: list) -> Board:
    """The legend of a .kicad_pcb, parsed: its texts on the silkscreen, each part's courtyard and body,
    the pads' openings in the solder mask, the holes and the board's edge."""
    board = Board()
    setup = child(root, "setup")
    margin = (
        _f(child(setup, "pad_to_mask_clearance")) if setup and child(setup, "pad_to_mask_clearance") else 0.0
    )
    for node in root[1:]:
        if not isinstance(node, list) or not node:
            continue
        head = node[0]
        if head == "gr_text" and _layer(node) in SILK and not _hidden(node):
            board.texts.append(_text(node, "text", "", str(node[1])))
        elif head in ("gr_line", "gr_rect", "gr_arc", "gr_circle", "gr_poly") and _layer(node) == "Edge.Cuts":
            pts = _shape_points(node)
            if head in ("gr_rect", "gr_circle"):
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                pts = [(min(xs), min(ys)), (max(xs), min(ys)), (max(xs), max(ys)), (min(xs), max(ys))]
                board.edges += list(zip(pts, pts[1:] + pts[:1], strict=True))
            elif head == "gr_arc":
                s, m, e = (_xy(child(node, k)) for k in ("start", "mid", "end"))
                board.edges += [(s, m), (m, e)]
            elif head == "gr_poly":
                board.edges += list(zip(pts, pts[1:] + pts[:1], strict=True))
            else:
                board.edges.append((pts[0], pts[1]))
        elif head == "via":
            (vx, vy), d = _xy(child(node, "at")), _f(child(node, "drill"))
            board.holes.append(
                ((vx - d / 2, vy - d / 2, vx + d / 2, vy + d / 2), f"via at ({_mm(vx)}, {_mm(vy)})")
            )
        elif head == "footprint":
            _footprint(board, node, margin)
    return board


def _footprint(board: Board, node: list, margin: float) -> None:
    at = atoms(child(node, "at"))
    fx, fy = float(at[0]), float(at[1])
    rot = float(at[2]) if len(at) > 2 else 0.0
    side = "B" if _layer(node).startswith("B.") else "F"
    ref = ""
    for prop in children(node, "property"):
        if str(prop[1]) == "Reference":
            ref = str(prop[2])
    origin = (fx, fy, rot)
    for prop in children(node, "property"):
        if str(prop[1]) in ("Reference", "Value") and _layer(prop) in SILK and not _hidden(prop):
            kind = "designator" if str(prop[1]) == "Reference" else "value"
            board.texts.append(_text(prop, kind, ref, str(prop[2]), origin))
    for item in children(node, "fp_text"):
        if _layer(item) in SILK and not _hidden(item):
            raw = str(item[2])
            text = raw.replace("${REFERENCE}", ref)
            kind = "designator" if raw == "${REFERENCE}" else "text"
            board.texts.append(_text(item, kind, ref, text, origin))
    court, body = [], []
    for shape in node[1:]:
        if not isinstance(shape, list) or shape[0] not in (
            "fp_line",
            "fp_rect",
            "fp_poly",
            "fp_circle",
            "fp_arc",
        ):
            continue
        layer = _layer(shape)
        pts = [to_board(fx, fy, rot, *p) for p in _shape_points(shape)]
        if layer in ("F.CrtYd", "B.CrtYd"):
            court += pts
        elif layer in ("F.Fab", "B.Fab"):
            body += pts
    pad_pts: list[tuple[float, float]] = []
    for pad in children(node, "pad"):
        pat = atoms(child(pad, "at"))
        cx, cy = to_board(fx, fy, rot, float(pat[0]), float(pat[1]))
        angle = float(pat[2]) if len(pat) > 2 else rot
        w, h = _xy(child(pad, "size")) if child(pad, "size") else (0.0, 0.0)
        names = [str(a) for a in atoms(child(pad, "layers") or ["layers"])]
        own = _f(child(pad, "solder_mask_margin")) if child(pad, "solder_mask_margin") else margin
        box = _pad_box(cx, cy, w + 2 * own, h + 2 * own, angle)
        what = f"the solder mask opening of {ref} pad {pad[1]}"
        for s in ("F", "B"):
            if f"{s}.Mask" in names or "*.Mask" in names:
                board.openings.append((s, box, what))
        drill = child(pad, "drill")
        if drill is not None:
            vals = [float(a) for a in atoms(drill) if a != "oval"]
            if vals and vals[0] > 0:
                dw, dh = vals[0], vals[1] if len(vals) > 1 else vals[0]
                board.holes.append((_pad_box(cx, cy, dw, dh, angle), f"the hole of {ref} pad {pad[1]}"))
        pad_pts += [(box[0], box[1]), (box[2], box[3])]
    pts = court + body or pad_pts
    if ref and pts:
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        board.parts.append(Part(ref, side, fx, fy, rot, (min(xs), min(ys), max(xs), max(ys)), node))


# ---------------------------------------------------------------- geometry


def overlap(a: Box, b: Box) -> tuple[float, float] | None:
    """How far 2 boxes share, along x and along y, or None where they only touch or are apart."""
    dx, dy = min(a[2], b[2]) - max(a[0], b[0]), min(a[3], b[3]) - max(a[1], b[1])
    return (dx, dy) if dx > EPS and dy > EPS else None


def gap(a: Box, b: Box) -> float:
    dx = max(0.0, b[0] - a[2], a[0] - b[2])
    dy = max(0.0, b[1] - a[3], a[1] - b[3])
    return math.hypot(dx, dy)


def crosses(seg, box: Box) -> bool:
    """A segment that enters the inside of a box (Liang-Barsky); one that runs along its side does not."""
    (x0, y0), (x1, y1) = seg
    lo, hi = 0.0, 1.0
    dx, dy = x1 - x0, y1 - y0
    for p, q in (
        (-dx, x0 - box[0] - EPS),
        (dx, box[2] - EPS - x0),
        (-dy, y0 - box[1] - EPS),
        (dy, box[3] - EPS - y0),
    ):
        if abs(p) < 1e-12:
            if q < 0:
                return False
            continue
        r = q / p
        if p < 0:
            lo = max(lo, r)
        else:
            hi = min(hi, r)
        if lo > hi:
            return False
    return True


def off_board(board: Board, box: Box) -> bool:
    out = board.outline
    if out is None:
        return False
    if box[0] < out[0] - EPS or box[1] < out[1] - EPS or box[2] > out[2] + EPS or box[3] > out[3] + EPS:
        return True
    return any(crosses(e, box) for e in board.edges)


def direction(angle: float) -> float:
    return round(angle % 180.0, 3) % 180.0


def _mm(v: float) -> str:
    return fmt(round(v, 3))


# ---------------------------------------------------------------- the check


@dataclass
class Finding:
    rule: str
    what: str
    status: str  # fail | not judged
    line: str


def judge(board: Board, limit: Limit, pack: dict[str, float]) -> list[Finding]:
    out: list[Finding] = []

    def where(t: Text) -> str:
        return f"{t.what} at ({_mm(t.x)}, {_mm(t.y)}) mm on {t.layer}"

    def fail(rule: str, t: Text, why: str, source: str) -> None:
        out.append(Finding(rule, t.what, "fail", f"legend {rule}: {where(t)}: {why} ({source})"))

    own = "rules/legend.json"
    texts = [t for t in board.texts]
    measured = []
    for t in texts:
        if t.unmeasured:
            out.append(
                Finding("font", t.what, "not judged", f"legend not judged: {where(t)}: {t.unmeasured}")
            )
        else:
            measured.append(t)
    # size
    if limit.height is None and measured:
        out.append(
            Finding(
                "size",
                "the board",
                "not judged",
                f"legend not judged: text height on {len(measured)} texts: {limit.label} names no least "
                f"height ({limit.stroke_source})",
            )
        )
    for t in measured:
        if limit.height is not None and t.h < limit.height - EPS:
            fail(
                "size",
                t,
                f"height {_mm(t.h)} mm, under the least {fmt(limit.height)} mm of {limit.label}",
                limit.height_source,
            )
        if limit.stroke is not None and t.t < limit.stroke - EPS:
            fail(
                "size",
                t,
                f"stroke {fmt(t.t)} mm, under the least {fmt(limit.stroke)} mm of {limit.label}",
                limit.stroke_source,
            )
    # overlap
    for i, a in enumerate(measured):
        for b in measured[i + 1 :]:
            if a.layer == b.layer and (o := overlap(a.box, b.box)):
                fail(
                    "overlap",
                    a,
                    f"on {b.what} at ({_mm(b.x)}, {_mm(b.y)}) mm by {_mm(o[0])} x {_mm(o[1])} mm",
                    own,
                )
        for s, box, what in board.openings:
            if s == a.side and (o := overlap(a.box, box)):
                fail("overlap", a, f"on {what} by {_mm(o[0])} x {_mm(o[1])} mm", own)
        for box, what in board.holes:
            if o := overlap(a.box, box):
                fail("overlap", a, f"on {what} by {_mm(o[0])} x {_mm(o[1])} mm", own)
        if off_board(board, a.box):
            fail("overlap", a, "over the board edge", own)
    # hidden and nearest
    reach = pack["designator_reach_mm"]
    for t in measured:
        if t.kind != "designator":
            continue
        same = [p for p in board.parts if p.side == t.side]
        for p in same:
            if o := overlap(t.box, p.box):
                whose = "its own courtyard" if p.ref == t.owner else f"the courtyard of {p.ref}"
                fail(
                    "hidden", t, f"under {whose} by {_mm(o[0])} x {_mm(o[1])} mm: hidden once assembled", own
                )
        mine = next((p for p in same if p.ref == t.owner), None)
        if mine is None or any(overlap(t.box, p.box) for p in same):
            continue
        d_own = gap(t.box, mine.box)
        near = min(
            (p for p in same if p.ref != t.owner), key=lambda p: (gap(t.box, p.box), p.ref), default=None
        )
        if near is not None and gap(t.box, near.box) < d_own - EPS:
            fail(
                "nearest",
                t,
                f"{_mm(gap(t.box, near.box))} mm from {near.ref}, nearer than {_mm(d_own)} mm from {t.owner}",
                own,
            )
        elif d_own > reach + EPS:
            fail(
                "nearest",
                t,
                f"{_mm(d_own)} mm from {t.owner}, over the reach of {fmt(reach)} mm",
                f"{own}, designator_reach_mm",
            )
    # direction
    most = int(pack["directions_per_side"])
    for layer in SILK:
        on = [t for t in measured if t.layer == layer]
        dirs = sorted({direction(t.angle) for t in on})
        if len(dirs) > most:
            counts = ", ".join(f"{fmt(d)} degrees: {sum(direction(t.angle) == d for t in on)}" for d in dirs)
            out.append(
                Finding(
                    "direction",
                    layer,
                    "fail",
                    f"legend direction: {layer} reads in {len(dirs)} directions ({counts}), over {most} "
                    f"({own}, directions_per_side)",
                )
            )
    for t in measured:
        if t.layer == "B.SilkS" and not t.mirrored:
            fail("direction", t, "on the back and not mirrored: it reads backwards from below", own)
    return out


# ---------------------------------------------------------------- the placer


def place(root: list, limit: Limit, pack: dict[str, float], fixed: set[str] = frozenset()) -> list[str]:
    """Place each designator of the board `root` (a parsed .kicad_pcb, changed in place) that is not in
    `fixed`. Returns 1 line for each part whose designator found no place and went to its Fab layer."""
    board = read_board(root)
    lines: list[str] = []
    gap_mm, step = pack["placer_gap_mm"], pack["size_step_mm"]
    most = int(pack["directions_per_side"])
    moving = {
        t.owner: t
        for t in board.texts
        if t.kind == "designator" and t.node is not None and t.node[0] == "property" and t.owner not in fixed
    }
    keep = [
        t
        for t in board.texts
        if not (t.kind == "designator" and t.owner in moving and t.node is moving[t.owner].node)
    ]
    placed: list[tuple[str, Box]] = []  # layer, box
    dirs = {layer: {direction(t.angle) for t in keep if t.layer == layer} for layer in SILK}
    parts = sorted((p for p in board.parts if p.ref in moving), key=lambda p: (-round(p.area, 6), p.ref))

    def clear(t: Text, box: Box, angle: float) -> bool:
        if off_board(board, box):
            return False
        if any(k.layer == t.layer and overlap(box, k.box) for k in keep):
            return False
        if any(layer == t.layer and overlap(box, b) for layer, b in placed):
            return False
        if any(s == t.side and overlap(box, b) for s, b, _ in board.openings):
            return False
        if any(overlap(box, b) for b, _ in board.holes):
            return False
        same = [p for p in board.parts if p.side == t.side]
        if any(overlap(box, p.box) for p in same):
            return False
        mine = next(p for p in same if p.ref == t.owner)
        d_own = gap(box, mine.box)
        if d_own > pack["designator_reach_mm"] + EPS:
            return False
        if any(gap(box, p.box) < d_own + EPS for p in same if p.ref != t.owner):
            return False
        # A direction the side reads in already adds none; a design's own art may have more than the rule
        # allows, and that is its own failure, not the designator's.
        return direction(angle) in dirs[t.layer] or len(dirs[t.layer] | {direction(angle)}) <= most

    for part in parts:
        t = moving[part.ref]
        h0 = max(t.h, limit.height or t.h)
        floor = limit.height if limit.height is not None else h0
        sizes = [h0]
        while sizes[-1] - step >= floor - EPS:
            sizes.append(round(sizes[-1] - step, 6))
        ratio_w, ratio_t = t.w / t.h if t.h else 1.0, t.t / t.h if t.h else 0.15
        done = False
        for h in sizes:
            w = round(h * ratio_w, 6)
            th = round(max(h * ratio_t, limit.stroke or 0.0), 6)
            for angle in (0.0, 90.0):
                for spot in SPOTS:
                    bx, by = _spot(part.box, spot, len(t.text), h, w, th, angle, gap_mm)
                    box = text_box(bx, by, angle, len(t.text), h, w, th)
                    if clear(t, box, angle):
                        _write(t.node, part, bx, by, angle, h, w, th)
                        placed.append((t.layer, box))
                        dirs[t.layer].add(direction(angle))
                        done = True
                        break
                if done:
                    break
            if done:
                break
        if not done:
            fab = t.layer.replace("SilkS", "Fab")
            kicadgen.set_child(t.node, "layer", ["layer", Q(fab)])
            lines.append(f"legend: {part.ref} has no place on {t.layer}; its designator is kept on {fab}")
    return lines


def lay(root: list, fab: str | None, fixed: dict[str, tuple[float, float, float]], auto: bool) -> list[str]:
    """kicadgen's step: the designators a design fixes by hand (ref -> x, y, angle on the board), then,
    with `auto`, every other designator placed. Returns the placer's lines."""
    board = read_board(root)
    for ref, (x, y, angle) in sorted(fixed.items()):
        part = next((p for p in board.parts if p.ref == ref), None)
        text = next((t for t in board.texts if t.kind == "designator" and t.owner == ref and t.node), None)
        if part is None or text is None or text.node[0] != "property":
            raise ValueError(f"designator({ref!r}): no part {ref!r} with a designator on the silkscreen")
        lx, ly = to_local(part.x, part.y, part.rot, x, y)
        kicadgen.set_child(text.node, "at", ["at", fmt(round(lx, 6)), fmt(round(ly, 6)), fmt(angle)])
    return place(root, limits(fab), read_pack(), fixed=set(fixed)) if auto else []


def show_designators(root: list) -> int:
    """Put every hidden designator back on its part's silkscreen, where its footprint has it: for a board
    whose design hid them (Part.hide_ref), to see what the placer makes of them. Returns how many."""
    shown = 0
    for fpn in children(root, "footprint"):
        side = "B" if _layer(fpn).startswith("B.") else "F"
        for prop in children(fpn, "property"):
            if str(prop[1]) != "Reference" or (_layer(prop) in SILK and not _hidden(prop)):
                continue
            kicadgen.remove_children(prop, {"hide"})
            eff = child(prop, "effects")
            if eff is not None:
                kicadgen.remove_children(eff, {"hide"})
                eff[:] = [a for a in eff if a != "hide"]
            kicadgen.set_child(prop, "layer", ["layer", Q(f"{side}.SilkS")])
            shown += 1
    return shown


def _spot(box: Box, spot: str, chars: int, h, w, t, angle, g) -> tuple[float, float]:
    width, height = chars * ADVANCE * w + t, h + t
    if direction(angle) == 90.0:
        width, height = height, width
    cx, cy = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    x = {"left": box[0] - g - width / 2, "right": box[2] + g + width / 2}
    y = {"above": box[1] - g - height / 2, "below": box[3] + g + height / 2}
    words = spot.split()
    px = next((x[k] for k in words if k in x), cx)
    py = next((y[k] for k in words if k in y), cy)
    return (round(px, 6), round(py, 6))


def _write(node: list, part: Part, bx: float, by: float, angle: float, h: float, w: float, t: float) -> None:
    lx, ly = to_local(part.x, part.y, part.rot, bx, by)
    kicadgen.set_child(node, "at", ["at", fmt(round(lx, 6)), fmt(round(ly, 6)), fmt(angle)])
    eff = child(node, "effects")
    if eff is None:
        eff = ["effects"]
        node.append(eff)
    font = child(eff, "font")
    if font is None:
        font = ["font"]
        eff.append(font)
    kicadgen.set_child(font, "size", ["size", fmt(h), fmt(w)])
    kicadgen.set_child(font, "thickness", ["thickness", fmt(t)])
    just = child(eff, "justify")
    if just is not None:
        keep = [a for a in atoms(just) if a == "mirror"]
        if keep:
            just[1:] = keep
        else:
            kicadgen.remove_children(eff, {"justify"})


# ---------------------------------------------------------------- the gate and the command


def kicad_findings(report: dict) -> list[str]:
    """KiCad's own legend violations, 1 line each, as failures whatever their severity in the report."""
    out = []
    for v in report.get("violations", []):
        rule = KICAD_CHECKS.get(str(v.get("type")))
        if rule is None:
            continue
        items = v.get("items", [])
        if v.get("type") == "silk_over_copper" and not any(_is_text(it) for it in items):
            continue
        if v.get("type") == "silk_overlap" and not all(_is_text(it) for it in items):
            continue
        pos = next((it["pos"] for it in items if "pos" in it), None)
        at = f" at ({_mm(pos['x'])}, {_mm(pos['y'])}) mm" if pos else ""
        said = "; ".join(str(it.get("description", "")) for it in items)
        out.append(
            f"legend {rule}: KiCad {v.get('type')}{at}: {v.get('description')}: {said} "
            f"(KiCad's own check, {v.get('severity')} in its report)"
        )
    return out


def _is_text(item: dict) -> bool:
    d = str(item.get("description", ""))
    return bool(re.match(r"(Reference field|Value field|Text|Footprint text|Field)", d)) or " field " in d


def judge_file(pcb: Path, fab: str | None) -> tuple[Limit, list[Finding]]:
    limit = limits(fab)
    return limit, judge(read_board(kicadgen.parse(pcb.read_text(encoding="utf-8"))), limit, read_pack())


def gate(project, report: dict, strict: bool, fab: str | None) -> dict:
    """The DRC gate's part: red on a failure of this module or of KiCad's own legend checks, and with
    --strict on what was not judged."""
    fab = fab or fab_named(project.dir, project.name)
    try:
        limit, found = judge_file(project.pcb, fab)
    except (ValueError, OSError) as exc:
        return {
            "red": True,
            "summary": "legend: not run",
            "failures": [f"legend: not run: {exc}"],
            "warnings": [],
        }
    fails = [f.line for f in found if f.status == "fail"] + kicad_findings(report)
    unjudged = [f.line for f in found if f.status != "fail"]
    return {
        "red": bool(fails) or (strict and bool(unjudged)),
        "summary": f"legend ({limit.label}): {len(fails)} fail, {len(unjudged)} not judged",
        "failures": fails + (unjudged if strict else []),
        "warnings": [] if strict else unjudged,
    }


def _arguments(ap) -> None:
    ap.add_argument("board", help="a .kicad_pcb, or a project folder")
    ap.add_argument("--fab", help="the fab's rule set (rules/<name>.kicad_dru), for this run")
    ap.add_argument(
        "--place",
        metavar="OUT",
        help="write a copy of the board, its designators placed, to OUT (.kicad_pcb)",
    )
    ap.add_argument(
        "--show",
        action="store_true",
        help="put every hidden designator back on the silkscreen first, where its footprint has it",
    )
    ap.add_argument("--strict", action="store_true", help="what was not judged fails too")


def register(sub, cli) -> None:
    """Add `legend` to the workcenter's parser."""
    p = sub.add_parser(
        "legend",
        help="every text printed on a board against its fab's least size and the legend's rules, without "
        "KiCad; --place OUT writes a copy with each designator placed",
    )
    _arguments(p)
    p.set_defaults(run=run)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="workcenter legend", description=__doc__.splitlines()[0])
    _arguments(ap)
    return run(ap.parse_args(argv))


def run(args) -> int:
    path = Path(args.board)
    if path.is_dir():
        boards = sorted(path.glob("*.kicad_pcb"))
        if len(boards) != 1:
            print(f"legend: {path} holds {len(boards)} boards; name 1")
            return 2
        path = boards[0]
    fab = args.fab or fab_named(path.parent, path.stem)
    root = kicadgen.parse(path.read_text(encoding="utf-8"))
    limit = limits(fab)
    if args.show:
        print(f"legend: {show_designators(root)} hidden designators put back on the silkscreen")
    if args.place:
        for line in place(root, limit, read_pack()):
            print(line)
        out = Path(args.place)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(kicadgen.dumps(root) + "\n", encoding="utf-8")
        print(f"legend: placed board written to {out}")
    found = judge(read_board(root), limit, read_pack())
    for f in found:
        print(f.line)
    fails = sum(f.status == "fail" for f in found)
    unjudged = len(found) - fails
    red = fails or (args.strict and unjudged)
    counts = ", ".join(f"{r} {sum(f.rule == r and f.status == 'fail' for f in found)}" for r in RULE_NAMES)
    print(f"LEGEND {'RED' if red else 'HELD'}: {fails} fail ({counts}), {unjudged} not judged; {limit.label}")
    return 1 if red else 0


RULE_NAMES = ("size", "overlap", "hidden", "nearest", "direction")

if __name__ == "__main__":
    sys.exit(main())
