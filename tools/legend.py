#!/usr/bin/env python3
"""legend — every text printed on a board, judged for whether it can be read, and a placer for designators.

The legend is the board's silkscreen text: each part's designator, a value printed on it, and the texts a
design adds. `judge` holds each to 5 rules and gives 1 line per failure:

    size       its height and stroke under the least the board's fab prints, read from the fab's own page
               (its rule set in rules/, or the project's own copy of a rule set from elsewhere); a board
               that names no fab is held, for each size, to the least of the fabs in rules/
    overlap    on another text, on a pad's opening in the solder mask, on a hole, or off the board: over
               its edge, outside its outline or inside a cutout (a footprint's own Edge.Cuts included)
    hidden     a designator under a part's courtyard or body, its own or another's, on its side
    nearest    a designator nearer another part than its own, or further from its own than the reach of
               rules/legend.json
    direction  text in more than 2 directions on 1 side (180 degrees is a direction of its own: KiCad 10
               prints a board text at 180 upside down; a footprint's text it keeps upright, at 0, unless
               the text is written (unlocked yes)), and text on the back that is not mirrored

A text's box is measured for KiCad's stroke font: each character 1.34 / 1.27 of the glyph width
(kicadgen.TEXT_ADVANCE), plus the stroke; the glyph height plus the stroke; justified top or bottom, half a
glyph height below or above its anchor. A text with no (thickness) has KiCad's stroke, 1/8 of its glyph width.
A text in another font, of more than 1 line, holding a text variable the tool does not resolve, or in a
text box, is not measured: it is printed as not judged with the reason. So is a designator whose part has
no courtyard, body or pad, and the edge of a board with no outline.

The board's edge is every Edge.Cuts line, arc, circle, rectangle, polygon and curve, a footprint's own
included; an arc or a circle is followed by chords no more than CHORD_MM from it. A part is the convex hull
of its courtyard and Fab drawing, turned with it (its pads where it has neither).

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
# The stroke KiCad 10 gives a text with no (thickness), over its glyph width (the second number of its
# (size height width)): kicad-cli 10.0.8 DRC read 0.125 mm on "AB" (size 1 1), and pcbnew 10.0.8 read
# 0.25, 0.125 and 0.25 mm on (size 1 2), (size 2 1) and (size 2 2) (scratch probes of 2026-11-17).
DEFAULT_STROKE = 1 / 8
UNLOCKED = "unlocked"  # the word KiCad writes on a footprint text it does not keep upright
CHORD_MM = 0.001  # the most a chord the tool follows an arc or a circle by lies inside it
# A text variable of the title block, as KiCad names it, and its field in (title_block).
TITLE_VARS = {"TITLE": "title", "ISSUE_DATE": "date", "REVISION": "rev", "COMPANY": "company"}

Box = tuple[float, float, float, float]  # x1, y1, x2, y2
Point = tuple[float, float]


class Refusal(ValueError):
    """A board file the tool cannot read: the line names the file and the place."""


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
    page += f" (rules/{path.name})" if path.resolve().parent == RULES.resolve() else f" ({path})"
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
    """The fab a project names: the rule set `workcenter design` copied in as <name>.kicad_dru. A copy of
    a set in rules/ gives that set's name; a copy of a set from elsewhere (Design.fab takes a path) gives
    the project's own copy, whose rules are the fab's."""
    dru = project_dir / f"{name}.kicad_dru"
    if not dru.is_file():
        return None
    m = re.search(r"Copied by the workcenter from (\S+)\.kicad_dru", dru.read_text(encoding="utf-8"))
    if not m:
        return None
    stem = m.group(1)
    return stem if "/" not in stem and (RULES / f"{stem}.kicad_dru").is_file() else str(dru)


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
    vjust: int = 0  # 1 top, 0 centre, -1 bottom
    variable: str = ""  # a text variable the tool does not resolve
    upright: bool = False  # KiCad keeps it upright: drawn at its angle turned into -90..90
    name: str = ""  # a part's own field: its name
    knockout: bool = False  # written (layer "F.SilkS" knockout): KiCad prints the area round it

    @property
    def reads(self) -> float:
        """The direction it reads in on the board."""
        return direction(self.angle, self.upright)

    @property
    def what(self) -> str:
        if self.kind == "designator":
            return f"designator {self.owner}"
        if self.kind == "value":
            return f'value of {self.owner} "{self.text}"'
        if self.kind == "field":
            return f'field {self.name} of {self.owner} "{self.text}"'
        return f'text "{self.text}"'

    @property
    def unmeasured(self) -> str:
        if self.face:
            return f"its font {self.face!r} is not KiCad's stroke font, whose size the tool measures"
        if "\n" in self.text or "\\n" in self.text:
            return "it has more than 1 line; the tool measures 1"
        if self.variable:
            return f"it holds {self.variable}, a text variable the tool does not resolve"
        if self.knockout:
            # kicad-cli 10.0.8 plotted a knocked-out "AB" (1 mm, 0.15 mm) filled from 0.156 mm above to
            # 0.066 mm below the box this tool measures (the second review's p1-probe, its F.SilkS Gerber).
            return "it is knocked out: KiCad fills an area round it larger than the box the tool measures"
        return ""

    @property
    def drawn(self) -> float:
        """The angle KiCad draws it at. A text kept upright whose angle is in (90, 270] is drawn turned back
        by 180, with its justification as written: kicad-cli 10.0.8 plotted a designator at 180 justified
        left running right of its anchor (the second review's h5-upright-justify)."""
        if self.upright and 90 < self.angle % 360 <= 270:
            return self.angle - 180
        return self.angle

    @property
    def box(self) -> Box:
        return text_box(
            self.x,
            self.y,
            self.drawn,
            len(self.text),
            self.h,
            self.w,
            self.t,
            self.justify,
            self.mirrored,
            self.vjust,
        )

    @property
    def side(self) -> str:
        return self.layer[0]


def text_box(x, y, angle, chars, h, w, t, justify=0, mirrored=False, vjust=0) -> Box:
    """A text's box on the board: `chars` characters of glyph height `h`, width `w`, stroke `t`."""
    width, height = chars * ADVANCE * w + t, h + t
    a = math.radians(angle)
    ux, uy = math.cos(a), -math.sin(a)  # the reading direction; y grows down the board
    # A left-justified text starts at its anchor, a right-justified one ends there; mirrored, the reverse.
    shift = -justify * (width / 2) * (-1 if mirrored else 1)
    # Justified top, the glyphs hang below the anchor; bottom, they stand on it: half a glyph height down or
    # up along the text's own up, (uy, -ux) (kicad-cli 10 plot: "AB" justified top at y = 110 has its
    # glyphs from 110.04 to 111.04, a centred one at 105 from 104.45 to 105.45).
    drop = -vjust * h / 2
    cx, cy = x + shift * ux + drop * uy, y + shift * uy - drop * ux
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
    poly: list[Point]  # the convex hull of its courtyard and body, on the board
    node: list = field(repr=False, default_factory=list)
    box: Box = field(init=False)  # the upright box round the hull
    square: bool = field(init=False)  # the hull is that box, so the box's sums are exact

    def __post_init__(self) -> None:
        xs, ys = [p[0] for p in self.poly], [p[1] for p in self.poly]
        b = self.box = (min(xs), min(ys), max(xs), max(ys))
        corners = ((b[0], b[1]), (b[2], b[1]), (b[2], b[3]), (b[0], b[3]))
        self.square = len(self.poly) == 4 and all(
            any(abs(p[0] - c[0]) < EPS and abs(p[1] - c[1]) < EPS for p in self.poly) for c in corners
        )

    @property
    def area(self) -> float:
        return (self.box[2] - self.box[0]) * (self.box[3] - self.box[1])


@dataclass
class Board:
    texts: list[Text] = field(default_factory=list)
    parts: list[Part] = field(default_factory=list)
    openings: list[tuple[str, Box, str]] = field(default_factory=list)  # side (F, B), box, what
    holes: list[tuple[Box, str]] = field(default_factory=list)
    edges: list[tuple[Point, Point]] = field(default_factory=list)
    unread: list[Unread] = field(default_factory=list)  # what is printed and not measured
    unplaced: dict[str, str] = field(default_factory=dict)  # a footprint with no outline: ref -> side


@dataclass
class Unread:
    """An item printed on the silkscreen that the tool does not measure: a text box, a dimension, a table, a
    barcode. Its box, where the tool can bound it, keeps other texts and the placer off it."""

    rule: str
    where: str
    why: str
    layer: str
    box: Box | None


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


def _resolve(text: str, values: dict[str, str]) -> tuple[str, str]:
    """A text with each variable it holds replaced by its value, and the first one with no value."""
    left = ""

    def one(m: re.Match) -> str:
        nonlocal left
        if m.group(1) in values:
            return values[m.group(1)]
        left = left or m.group(0)
        return m.group(0)

    return re.sub(r"\$\{([^}]*)\}", one, text), left


def _numbers(node, head: str, what: str) -> list[float]:
    """The numbers of `head` in `node`, or a refusal that names the item."""
    found = child(node, head)
    try:
        vals = [float(a) for a in atoms(found)] if found is not None else []
    except ValueError:
        vals = []
    if len(vals) < 2:
        raise Refusal(f"{what} has no ({head})" if found is None else f"{what}: ({head}) is not 2 numbers")
    return vals


def _text(node, kind: str, owner: str, text: str, origin=None, values=None, what: str = "") -> Text:
    what = what or f'{node[0]} "{text}"'
    at = _numbers(node, "at", what)
    x, y = at[0], at[1]
    angle = at[2] if len(at) > 2 else 0.0
    if origin:
        x, y = to_board(*origin, x, y)
    eff = child(node, "effects") or ["effects"]
    font = child(eff, "font") or ["font"]
    size = child(font, "size")
    h, w = _numbers(font, "size", what)[:2] if size is not None else (1.0, 1.0)
    if h <= 0 or w <= 0:
        raise Refusal(f"{what} at ({_mm(x)}, {_mm(y)}): its size {fmt(h)} x {fmt(w)} mm is not a size")
    thick = child(font, "thickness")
    t = _f(thick, 0, 0.0) if thick else round(w * DEFAULT_STROKE, 6)
    face = child(font, "face")
    just = [str(a) for a in atoms(child(eff, "justify") or ["justify"])]
    shown, variable = _resolve(text, values or {})
    return Text(
        kind,
        owner,
        shown,
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
        1 if "top" in just else -1 if "bottom" in just else 0,
        variable,
        _upright(node, origin is not None),
        knockout="knockout" in atoms(child(node, "layer") or ["layer"]),
    )


def _upright(node, in_footprint: bool) -> bool:
    """KiCad keeps a footprint's text upright unless the text is written (unlocked yes); it keeps no board
    text upright. pcbnew 10 saved a designator whose keep upright it had turned off as (unlocked yes), and a
    gr_text it had been told to keep upright read back as not kept (scratch probe of 2026-11-18)."""
    if not in_footprint:
        return False
    said = child(node, UNLOCKED)
    return said is None or "no" in atoms(said)


def _arc(cx: float, cy: float, r: float, a0: float, sweep: float) -> list[Point]:
    """Points along a circle's arc from angle a0 (radians, on the board) through `sweep`, each chord no
    more than CHORD_MM inside the arc."""
    step = 2 * math.acos(1 - CHORD_MM / r) if r > CHORD_MM else math.pi
    n = max(1, math.ceil(abs(sweep) / step))
    return [
        (cx + r * math.cos(a0 + sweep * i / n), cy + r * math.sin(a0 + sweep * i / n)) for i in range(n + 1)
    ]


def _three(s: Point, m: Point, e: Point) -> list[Point]:
    """The arc that starts at s, runs through m and ends at e."""
    (ax, ay), (bx, by), (qx, qy) = s, m, e
    d = 2 * (ax * (by - qy) + bx * (qy - ay) + qx * (ay - by))
    if abs(d) < 1e-12:
        return [s, e]
    a2, b2, q2 = ax * ax + ay * ay, bx * bx + by * by, qx * qx + qy * qy
    cx = (a2 * (by - qy) + b2 * (qy - ay) + q2 * (ay - by)) / d
    cy = (a2 * (qx - bx) + b2 * (ax - qx) + q2 * (bx - ax)) / d
    tau = 2 * math.pi
    a_s, a_m, a_e = (math.atan2(p[1] - cy, p[0] - cx) for p in (s, m, e))
    sweep = (a_e - a_s) % tau
    if (a_m - a_s) % tau > sweep:
        sweep -= tau
    return _arc(cx, cy, math.hypot(ax - cx, ay - cy), a_s, sweep)


def _path(shape) -> list[Point]:
    """A drawn shape as the points of a path, in its own frame; a closed shape ends where it starts."""
    kind = shape[0][3:]  # fp_line -> line, gr_line -> line
    get = {h: _xy(child(shape, h)) for h in ("start", "mid", "end", "center") if child(shape, h)}
    if kind == "line" and {"start", "end"} <= get.keys():
        return [get["start"], get["end"]]
    if kind == "rect" and {"start", "end"} <= get.keys():
        (x1, y1), (x2, y2) = get["start"], get["end"]
        return [(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)]
    if kind == "circle" and {"center", "end"} <= get.keys():
        (cx, cy), (ex, ey) = get["center"], get["end"]
        return _arc(cx, cy, math.hypot(ex - cx, ey - cy), 0.0, 2 * math.pi)
    if kind == "arc" and {"start", "mid", "end"} <= get.keys():
        return _three(get["start"], get["mid"], get["end"])
    pts = [_xy(xy) for xy in children(child(shape, "pts") or ["pts"], "xy")]
    if kind == "poly" and pts:
        return pts + pts[:1]
    if kind == "curve" and len(pts) == 4:  # a cubic Bezier, at 64 points
        out = []
        for i in range(65):
            u = i / 64
            k = ((1 - u) ** 3, 3 * u * (1 - u) ** 2, 3 * u * u * (1 - u), u**3)
            out.append(
                (
                    sum(c * p[0] for c, p in zip(k, pts, strict=True)),
                    sum(c * p[1] for c, p in zip(k, pts, strict=True)),
                )
            )
        return out
    return []


def _hull(points: list[Point]) -> list[Point]:
    """The convex hull, anticlockwise on the page, of the points (Andrew's monotone chain)."""
    pts = sorted(set((round(x, 9), round(y, 9)) for x, y in points))
    if len(pts) <= 2:
        return pts

    def turn(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: list[Point] = []
    upper: list[Point] = []
    for p in pts:
        while len(lower) >= 2 and turn(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and turn(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _pad_corners(cx: float, cy: float, w: float, h: float, angle: float) -> list[Point]:
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    return [(cx + dx * c + dy * s, cy - dx * s + dy * c) for dx in (-w / 2, w / 2) for dy in (-h / 2, h / 2)]


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
    values = {}
    block = child(root, "title_block")
    for var, head in TITLE_VARS.items():
        if block is not None and child(block, head) is not None and atoms(child(block, head)):
            values[var] = str(atoms(child(block, head))[0])
    for c in children(block, "comment") if block is not None else []:
        if len(atoms(c)) >= 2:
            values[f"COMMENT{atoms(c)[0]}"] = str(atoms(c)[1])
    for node in root[1:]:
        if not isinstance(node, list) or not node:
            continue
        head = node[0]
        if head == "gr_text" and _layer(node) in SILK and not _hidden(node):
            board.texts.append(_text(node, "text", "", str(node[1]), values=values))
        elif head == "gr_text_box" and _layer(node) in SILK and not _hidden(node):
            _unread_box(board, node, None)
        elif head in DRAWN and _layer(node) in SILK and not _hidden(node):
            _unread_drawn(board, node, None, "")
        elif head.startswith("gr_") and _layer(node) == "Edge.Cuts":
            path = _path(node)
            board.edges += list(zip(path, path[1:], strict=False))
        elif head == "via":
            vx, vy = _numbers(node, "at", "via")[:2]
            d = _f(child(node, "drill"))
            board.holes.append(
                ((vx - d / 2, vy - d / 2, vx + d / 2, vy + d / 2), f"via at ({_mm(vx)}, {_mm(vy)})")
            )
        elif head == "footprint":
            _footprint(board, node, margin, values)
    return board


def _bounds(points: list[Point], grow: float = 0.0) -> Box | None:
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs) - grow, min(ys) - grow, max(xs) + grow, max(ys) + grow)


def _unread_box(board: Board, node: list, origin) -> None:
    """A text box: its text is wrapped to its box by KiCad, which the tool does not do. Its rectangle
    (start and end, or the 4 corners of a turned one) is its box."""
    corners = [_xy(p) for p in children(child(node, "pts") or ["pts"], "xy")]
    corners += [_xy(child(node, h)) for h in ("start", "end") if child(node, h)]
    if origin:
        corners = [to_board(*origin, *p) for p in corners]
    x, y = corners[0] if corners else (0.0, 0.0)
    where = f'text box "{node[1]}" at ({_mm(x)}, {_mm(y)}) mm on {_layer(node)}'
    why = "KiCad wraps its text to the box, which the tool does not measure"
    board.unread.append(Unread("text box", where, why, _layer(node), _bounds(corners)))


# What KiCad draws on a layer from an item the tool does not measure: a dimension's number and arrows, a
# table's cells, a barcode's bars.
DRAWN = ("dimension", "table", "barcode")


def _unread_drawn(board: Board, node: list, origin, ref: str) -> None:
    """A dimension, a table or a barcode on the silkscreen: printed as not judged, by name and place. Its
    box bounds its points, its text's box, its cells or (a barcode, whose anchor KiCad may put at its centre
    or its corner) its size either way round its anchor."""
    head = str(node[0])
    label = child(node, "gr_text")
    cells = children(child(node, "cells") or ["cells"], "table_cell")
    said = child(node, "text")
    if label is not None and len(label) > 1:
        shown = str(label[1])
    elif cells and len(cells[0]) > 1:
        shown = str(cells[0][1])
    elif said is not None and atoms(said):
        shown = str(atoms(said)[0])
    else:
        shown = ""
    points = [_xy(p) for p in children(child(node, "pts") or ["pts"], "xy")]
    for cell in cells:
        points += [_xy(child(cell, h)) for h in ("start", "end") if child(cell, h)]
    if child(node, "at") is not None:
        ax, ay = _xy(child(node, "at"))
        sw, sh = _xy(child(node, "size")) if child(node, "size") else (0.0, 0.0)
        points = [(ax, ay)] + [(ax + dx, ay + dy) for dx in (-sw, sw) for dy in (-sh, sh)] + points
    if origin:
        points = [to_board(*origin, *p) for p in points]
    if label is not None and child(label, "at") is not None:
        t = _text(label, "text", ref, shown, origin, what=f'{head} "{shown}"')
        points += [(t.box[0], t.box[1]), (t.box[2], t.box[3])]
    x, y = points[0] if points else (0.0, 0.0)
    of = f" of {ref}" if ref else ""
    name = f'{head} "{shown}"' if shown else head
    where = f"{name}{of} at ({_mm(x)}, {_mm(y)}) mm on {_layer(node)}"
    why = "the tool does not measure what KiCad draws for it"
    board.unread.append(Unread(head, where, why, _layer(node), _bounds(points)))


def _footprint(board: Board, node: list, margin: float, values: dict[str, str]) -> None:
    ref = ""
    for prop in children(node, "property"):
        if str(prop[1]) == "Reference":
            ref = str(prop[2])
    at = _numbers(node, "at", f"footprint {ref or node[1]}")
    fx, fy = at[0], at[1]
    rot = at[2] if len(at) > 2 else 0.0
    side = "B" if _layer(node).startswith("B.") else "F"
    origin = (fx, fy, rot)
    own = dict(values, REFERENCE=ref)
    for prop in children(node, "property"):
        if str(prop[1]) == "Value":
            own["VALUE"] = str(prop[2])
    for prop in children(node, "property"):
        if _layer(prop) not in SILK or _hidden(prop):
            continue
        name = str(prop[1])
        if name in ("Reference", "Value"):
            kind = "designator" if name == "Reference" else "value"
            board.texts.append(_text(prop, kind, ref, str(prop[2]), origin, what=f"{kind} of {ref}"))
        else:
            # A part's own field shown on the silkscreen (an MPN, a rating) is printed like any text.
            shown = _text(prop, "field", ref, str(prop[2]), origin, own, f"field {name} of {ref}")
            shown.name = name
            board.texts.append(shown)
    for item in node[1:]:
        if (
            isinstance(item, list)
            and item
            and item[0] in DRAWN
            and _layer(item) in SILK
            and not _hidden(item)
        ):
            _unread_drawn(board, item, origin, ref)
    for item in children(node, "fp_text"):
        if _layer(item) in SILK and not _hidden(item):
            raw = str(item[2])
            kind = "designator" if raw == "${REFERENCE}" else "text"
            board.texts.append(_text(item, kind, ref, raw, origin, own, f'fp_text "{raw}" of {ref}'))
    for item in children(node, "fp_text_box"):
        if _layer(item) in SILK and not _hidden(item):
            _unread_box(board, item, origin)
    court, body = [], []
    for shape in node[1:]:
        if (
            not isinstance(shape, list)
            or not str(shape[0]).startswith("fp_")
            or shape[0].startswith("fp_text")
        ):
            continue
        layer = _layer(shape)
        pts = [to_board(fx, fy, rot, *p) for p in _path(shape)]
        if layer in ("F.CrtYd", "B.CrtYd"):
            court += pts
        elif layer in ("F.Fab", "B.Fab"):
            body += pts
        elif layer == "Edge.Cuts":
            board.edges += list(zip(pts, pts[1:], strict=False))
    pad_pts: list[Point] = []
    for pad in children(node, "pad"):
        pat = _numbers(pad, "at", f"{ref} pad {pad[1]}")
        cx, cy = to_board(fx, fy, rot, pat[0], pat[1])
        # KiCad writes a pad's angle on the board, the footprint's turn included, and leaves out 0.
        angle = pat[2] if len(pat) > 2 else 0.0
        w, h = _xy(child(pad, "size")) if child(pad, "size") else (0.0, 0.0)
        names = [str(a) for a in atoms(child(pad, "layers") or ["layers"])]
        own = _f(child(pad, "solder_mask_margin")) if child(pad, "solder_mask_margin") else margin
        box = _pad_box(cx, cy, w + 2 * own, h + 2 * own, angle)
        # A custom pad's copper is its anchor and its primitives, each in the pad's own frame, turned with
        # it; a primitive's line width widens it by half.
        shape: list[Point] = []
        for prim in (child(pad, "primitives") or ["primitives"])[1:]:
            if not isinstance(prim, list):
                continue
            pts = [to_board(cx, cy, angle, *p) for p in _path(prim)]
            stroke = child(prim, "width") or child(child(prim, "stroke") or ["stroke"], "width")
            if (b := _bounds(pts, own + _f(stroke) / 2)) is not None:
                box = (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
                shape += pts
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
        pad_pts += _pad_corners(cx, cy, w, h, angle) + shape
    pts = court + body or pad_pts
    if ref and pts:
        board.parts.append(Part(ref, side, fx, fy, rot, _hull(pts), node))
    elif ref:
        board.unplaced[ref] = side


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


def inside(board: Board, p: Point) -> bool:
    """A point on the board: a ray from it to the right crosses the edge an odd number of times, so a point
    in a cutout, or in the notch of an outline, is off it."""
    x, y = p
    odd = False
    for (x0, y0), (x1, y1) in board.edges:
        if (y0 > y) != (y1 > y) and x < x0 + (y - y0) * (x1 - x0) / (y1 - y0):
            odd = not odd
    return odd


def off_board(board: Board, box: Box) -> bool:
    """A box that crosses the edge, or lies off the board: outside its outline or inside a cutout."""
    if not board.edges:
        return False
    if any(crosses(e, box) for e in board.edges):
        return True
    return not inside(board, ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2))


def _clip(poly: list[Point], box: Box) -> list[Point]:
    """The part of a convex polygon inside a box (Sutherland-Hodgman)."""
    out = list(poly)
    for k, lim, keep_low in ((0, box[0], False), (0, box[2], True), (1, box[1], False), (1, box[3], True)):
        if not out:
            break
        src, out = out, []
        for i, cur in enumerate(src):
            prev = src[i - 1]
            cin = cur[k] <= lim if keep_low else cur[k] >= lim
            pin = prev[k] <= lim if keep_low else prev[k] >= lim
            if cin != pin:
                t = (lim - prev[k]) / (cur[k] - prev[k])
                cross = (prev[0] + t * (cur[0] - prev[0]), prev[1] + t * (cur[1] - prev[1]))
                out.append(cross)
            if cin:
                out.append(cur)
    return out


def under(box: Box, part: Part) -> tuple[float, float] | None:
    """How far a box lies on a part, along x and along y, or None where they only touch or are apart."""
    if part.square or not overlap(box, part.box):
        return overlap(box, part.box)
    if len(part.poly) < 3:
        return None
    cut = _clip(part.poly, box)
    if len(cut) < 3:
        return None
    xs, ys = [p[0] for p in cut], [p[1] for p in cut]
    area = sum(cut[i - 1][0] * p[1] - p[0] * cut[i - 1][1] for i, p in enumerate(cut)) / 2
    dx, dy = max(xs) - min(xs), max(ys) - min(ys)
    return (dx, dy) if dx > EPS and dy > EPS and abs(area) > EPS * EPS else None


def _to_segment(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    n = dx * dx + dy * dy
    t = 0.0 if n == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / n))
    return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)


def part_gap(box: Box, part: Part) -> float:
    """How far a box is from a part's hull: 0 where they touch or share."""
    if part.square:
        return gap(box, part.box)
    if under(box, part):
        return 0.0
    corners = [(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])]
    sides = list(zip(corners, corners[1:] + corners[:1], strict=True))
    poly = part.poly
    edges = list(zip(poly, poly[1:] + poly[:1], strict=True)) if len(poly) > 1 else [(poly[0], poly[0])]
    if any(crosses(e, box) for e in edges):
        return 0.0
    best = min(_to_segment(p, a, b) for p in poly for a, b in sides)
    return min(best, min(_to_segment(c, a, b) for c in corners for a, b in edges))


def direction(angle: float, upright: bool = False) -> float:
    """The direction a text reads in: its angle, once round. 180 is not 0: KiCad 10 prints a gr_text at
    180 degrees upside down (a kicad-cli plot of an "L" at 180 has its foot at the top). A text KiCad keeps
    upright (a footprint's, unless it says not) is drawn at its angle turned into -90..90: 180 reads as 0,
    270 as 90 (pcbnew 10 drew a designator written at 180 at 0)."""
    whole = 180.0 if upright else 360.0
    return round(angle % whole, 3) % whole


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
            rule = "variable" if t.variable and not (t.face or "\n" in t.text or "\\n" in t.text) else "font"
            out.append(Finding(rule, t.what, "not judged", f"legend not judged: {where(t)}: {t.unmeasured}"))
        else:
            measured.append(t)
    for u in board.unread:
        out.append(Finding(u.rule, u.where, "not judged", f"legend not judged: {u.where}: {u.why}"))
    if not board.edges and measured:
        out.append(
            Finding(
                "overlap",
                "the board's edge",
                "not judged",
                "legend not judged: the board's edge: it has no outline on Edge.Cuts",
            )
        )
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
    if limit.stroke is None and measured:
        out.append(
            Finding(
                "size",
                "the board",
                "not judged",
                f"legend not judged: text stroke on {len(measured)} texts: {limit.label} names no least "
                f"stroke ({limit.height_source})",
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
        for u in board.unread:
            if u.box is not None and u.layer == a.layer and (o := overlap(a.box, u.box)):
                fail("overlap", a, f"on the area of {u.where} by {_mm(o[0])} x {_mm(o[1])} mm", own)
        for s, box, what in board.openings:
            if s == a.side and (o := overlap(a.box, box)):
                fail("overlap", a, f"on {what} by {_mm(o[0])} x {_mm(o[1])} mm", own)
        for box, what in board.holes:
            if o := overlap(a.box, box):
                fail("overlap", a, f"on {what} by {_mm(o[0])} x {_mm(o[1])} mm", own)
        if off_board(board, a.box):
            fail("overlap", a, "over the board edge, outside its outline or inside a cutout", own)
    # hidden and nearest
    reach = pack["designator_reach_mm"]
    for t in measured:
        if t.kind != "designator":
            continue
        same = [p for p in board.parts if p.side == t.side]
        hits = [(p, o) for p in same if (o := under(t.box, p))]
        for p, o in hits:
            whose = "its own courtyard" if p.ref == t.owner else f"the courtyard of {p.ref}"
            fail("hidden", t, f"under {whose} by {_mm(o[0])} x {_mm(o[1])} mm: hidden once assembled", own)
        mine = next((p for p in same if p.ref == t.owner), None)
        if mine is None and not hits:
            why = (
                "its part has no courtyard, body or pad"
                if t.owner in board.unplaced or not any(p.ref == t.owner for p in board.parts)
                else "its part is on the other side"
            )
            out.append(
                Finding(
                    "nearest",
                    t.what,
                    "not judged",
                    f"legend not judged: {where(t)}: {why}, so hidden and nearest are not judged",
                )
            )
        if mine is None or hits:
            continue
        d_own = part_gap(t.box, mine)
        gaps = sorted((part_gap(t.box, p), p.ref) for p in same if p.ref != t.owner)
        if gaps and gaps[0][0] < d_own - EPS:
            fail(
                "nearest",
                t,
                f"{_mm(gaps[0][0])} mm from {gaps[0][1]}, nearer than {_mm(d_own)} mm from {t.owner}",
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
        dirs = sorted({t.reads for t in on})
        if len(dirs) > most:
            counts = ", ".join(f"{fmt(d)} degrees: {sum(t.reads == d for t in on)}" for d in dirs)
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
    dirs = {layer: {t.reads for t in keep if t.layer == layer} for layer in SILK}
    parts = sorted((p for p in board.parts if p.ref in moving), key=lambda p: (-round(p.area, 6), p.ref))

    def clear(t: Text, box: Box, angle: float) -> bool:
        if off_board(board, box):
            return False
        if any(k.layer == t.layer and overlap(box, k.box) for k in keep):
            return False
        if any(layer == t.layer and overlap(box, b) for layer, b in placed):
            return False
        if any(u.box is not None and u.layer == t.layer and overlap(box, u.box) for u in board.unread):
            return False
        if any(s == t.side and overlap(box, b) for s, b, _ in board.openings):
            return False
        if any(overlap(box, b) for b, _ in board.holes):
            return False
        same = [p for p in board.parts if p.side == t.side]
        if any(under(box, p) for p in same):
            return False
        mine = next(p for p in same if p.ref == t.owner)  # place() moves only a designator on its part's side
        d_own = part_gap(box, mine)
        if d_own > pack["designator_reach_mm"] + EPS:
            return False
        # The box's gap to a part's upright box is no more than its gap to the part: a part whose box is
        # far enough is far enough.
        if any(
            gap(box, p.box) < d_own + EPS and part_gap(box, p) < d_own + EPS for p in same if p.ref != t.owner
        ):
            return False
        # A direction the side reads in already adds none; a design's own art may have more than the rule
        # allows, and that is its own failure, not the designator's.
        return direction(angle) in dirs[t.layer] or len(dirs[t.layer] | {direction(angle)}) <= most

    for part in parts:
        t = moving[part.ref]
        if part.side != t.side:
            # A designator on the other side from its part has no side to be placed on; the check prints
            # it as not judged.
            lines.append(
                f"legend: {part.ref} is on {part.side}.Cu and its designator on {t.layer}; the placer "
                "leaves it where it is"
            )
            continue
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
        # The mask or the edge clipping a footprint's own silk outline is no matter of the legend's text.
        if v.get("type") in ("silk_over_copper", "silk_edge_clearance") and not any(
            _is_text(it) for it in items
        ):
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


def kicad_unnamed(report: dict, board: Board) -> tuple[list[str], list[str]]:
    """KiCad's silk_over_copper that names only pads: kicad-cli 10.0.8 named only "Pad 1 [<no net>] of R1
    on F.Cu", at the pad, for a field of R1 printed on it (the second review's h1-field), so the silkscreen
    item it clips is not named. A failure where a text of the board is on that pad's opening; else not
    judged. Returns (failures, not judged)."""
    fails, unjudged = [], []
    for v in report.get("violations", []):
        items = v.get("items", [])
        if v.get("type") != "silk_over_copper" or not items:
            continue
        if not all(str(it.get("description", "")).startswith("Pad ") for it in items):
            continue
        pos = next((it["pos"] for it in items if "pos" in it), None)
        said = "; ".join(str(it.get("description", "")) for it in items)
        at = f" at ({_mm(pos['x'])}, {_mm(pos['y'])}) mm" if pos else ""
        head = f"KiCad silk_over_copper{at}: {v.get('description')}: {said}"
        tail = f"(KiCad's own check, {v.get('severity')} in its report)"
        pads = [
            (s, box)
            for s, box, _ in board.openings
            if pos and box[0] - EPS <= pos["x"] <= box[2] + EPS and box[1] - EPS <= pos["y"] <= box[3] + EPS
        ]
        on = [t.what for t in board.texts if any(s == t.side and overlap(t.box, box) for s, box in pads)]
        if on:
            fails.append(f"legend overlap: {head}; on it: {', '.join(on)} {tail}")
        else:
            unjudged.append(
                f"legend not judged: {head}: KiCad names no silkscreen item and no text the tool reads is on "
                f"it {tail}"
            )
    return fails, unjudged


def _is_text(item: dict) -> bool:
    d = str(item.get("description", ""))
    # kicad-cli 10 names a board text "PCB text 'AB' on F.Silkscreen" and a designator "Reference field of C3"
    return (
        bool(re.match(r"(PCB text|Reference field|Value field|Text|Footprint text|Field)", d))
        or " field " in d
    )


def read_file(pcb: Path) -> list:
    """A .kicad_pcb parsed, or a refusal that names the file and why."""
    try:
        text = Path(pcb).read_text(encoding="utf-8")
        root = kicadgen.parse(text)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise Refusal(f"{pcb}: {exc}") from exc
    if not root or root[0] != "kicad_pcb":
        raise Refusal(f"{pcb}: not a KiCad board (it starts {str(root[0]) if root else 'empty'!r})")
    return root


def read_board_file(pcb: Path, root: list | None = None) -> Board:
    try:
        return read_board(read_file(pcb) if root is None else root)
    except Refusal as exc:
        raise exc if str(exc).startswith(f"{pcb}: ") else Refusal(f"{pcb}: {exc}") from exc


def gate(project, report: dict, strict: bool, fab: str | None) -> dict:
    """The DRC gate's part: red on a failure of this module or of KiCad's own legend checks, and with
    --strict on what was not judged."""
    try:
        fab = fab or fab_named(project.dir, project.name)
        limit = limits(fab)
        board = read_board_file(project.pcb)
        found = judge(board, limit, read_pack())
    except (ValueError, OSError) as exc:
        return {
            "red": True,
            "summary": "legend: not run",
            "failures": [f"legend: not run: {exc}"],
            "warnings": [],
        }
    pad_fails, pad_unjudged = kicad_unnamed(report, board)
    fails = [f.line for f in found if f.status == "fail"] + kicad_findings(report) + pad_fails
    unjudged = [f.line for f in found if f.status != "fail"] + pad_unjudged
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
    """0 held, 1 red, 2 refused: a file the tool cannot read, named with the reason."""
    path = Path(args.board)
    if path.is_dir():
        boards = sorted(path.glob("*.kicad_pcb"))
        if len(boards) != 1:
            print(f"legend: refused: {path} holds {len(boards)} boards; name 1")
            return 2
        path = boards[0]
    try:
        fab = args.fab or fab_named(path.parent, path.stem)
        limit = limits(fab)
        root = read_file(path)
        read_board_file(path, root)
        if args.show:
            print(f"legend: {show_designators(root)} hidden designators put back on the silkscreen")
        if args.place:
            for line in place(root, limit, read_pack()):
                print(line)
            out = Path(args.place)
            try:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(kicadgen.dumps(root) + "\n", encoding="utf-8")
            except OSError as exc:
                raise Refusal(f"{out}: {exc}") from exc
            print(f"legend: placed board written to {out}")
        found = judge(read_board_file(path, root), limit, read_pack())
    except (Refusal, OSError, ValueError) as exc:
        print(f"legend: refused: {exc}")
        return 2
    except Exception as exc:  # a fault of the tool is no verdict on the board: never exit code 1
        print(f"legend: refused: {path}: the tool failed on it ({type(exc).__name__}: {exc})")
        return 2
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
