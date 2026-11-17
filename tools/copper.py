#!/usr/bin/env python3
"""copper: the voltage drop, the current density and the temperature of a board, on its own copper.

`tools/workcenter copper` runs this file under the workcenter venv's Python, which sees numpy, KiCad's
`pcbnew` module and Pillow:

    python copper.py '<the arguments as JSON>'

The board's copper is read with KiCad's own geometry and drawn on a grid of square cells. 2 solvers
work on the grid, both by conjugate gradients on the cells' conductances:

- the drop: each power net's copper as a sheet of t / rho per square, its layers joined by each via's
  and each plated hole's barrel; each entry pin `copper.json` names is held at 0 V and each other pin
  with a current in `ratings.json` draws it. The current density of a cell comes from the currents
  through its 4 sides.
- the heat: every copper layer of the board as a sheet of copper and FR-4, the layers joined through
  the FR-4 and each barrel, the 2 faces cooled by the air. Each part's dissipation comes in at its pads
  (or at the pad `ratings.json` names), and each power net's copper adds its own I^2 R.

The 2 are solved in turn, each cell's copper at the temperature the heat gives it, until the drops
settle.

Each limit is the project's, in `copper.json`; each constant is `rules/copper/materials.json`'s, with
its document. It writes `report.md`, `report.json` and the pictures into the folder it is given. Exit
codes: 0 every limit held, 1 a limit not held, a file refused, or (with strict) a thing not judged,
2 an engine missing.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ratings  # noqa: E402  ratings.json, its reader and its refusals

MATERIALS = Path(__file__).resolve().parents[1] / "rules" / "copper" / "materials.json"
DROP_PITCH = 0.05  # mm: a cell of the drop's grid; a 0.3 mm track is 6 cells wide
HEAT_PITCH = 0.25  # mm: a cell of the heat's grid, a whole number of drop cells
RELATIVE = 1e-12  # the conjugate gradients stop when the residual is this share of the right side
SETTLED = 1e-4  # the drop and the heat are solved in turn until no net's greatest drop moves more
PASSES = 8  # and stop with a not-judged line after this many passes


class CopperError(ValueError):
    """A board or a file the command cannot judge as it stands."""


# ---------------------------------------------------------------- the solvers


def _faces(shape: tuple[int, int, int]) -> tuple[np.ndarray, np.ndarray]:
    """The flat indices of each pair of neighbouring cells on 1 layer: along x, then along y."""
    idx = np.arange(int(np.prod(shape))).reshape(shape)
    a = np.concatenate([idx[:, :, :-1].ravel(), idx[:, :-1, :].ravel()])
    b = np.concatenate([idx[:, :, 1:].ravel(), idx[:, 1:, :].ravel()])
    return a, b


def _harmonic(g1: np.ndarray, g2: np.ndarray) -> np.ndarray:
    """2 half cells in series: the conductance of the side between 2 square cells."""
    total = g1 + g2
    return np.divide(2 * g1 * g2, total, out=np.zeros_like(total), where=total > 0)


def _roots(n: int, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """The connected groups of n nodes joined by the edges (a, b): each node's smallest member."""
    lab = np.arange(n)
    while True:
        lo = np.minimum(lab[a], lab[b])
        np.minimum.at(lab, lab[a], lo)
        np.minimum.at(lab, lab[b], lo)
        while True:
            jumped = lab[lab]
            if np.array_equal(jumped, lab):
                break
            lab = jumped
        if np.array_equal(lab[a], lab[b]):
            return lab


def _solve(n: int, a: np.ndarray, b: np.ndarray, g: np.ndarray, extra: np.ndarray, right: np.ndarray, free):
    """x of (the Laplacian of the edges + diag(extra)) x = right, with the nodes outside `free` held at 0.
    Conjugate gradients with the diagonal as preconditioner; the matrix is symmetric and, with a node
    held or an `extra` above 0 in each group, positive definite."""
    where = np.full(n, -1)
    where[free] = np.arange(int(free.sum()))
    m = int(free.sum())
    diag = extra[free] + np.bincount(where[a][where[a] >= 0], g[where[a] >= 0], m)
    diag += np.bincount(where[b][where[b] >= 0], g[where[b] >= 0], m)
    both = (where[a] >= 0) & (where[b] >= 0)
    ia, ib, gk = where[a][both], where[b][both], g[both]

    def apply(x: np.ndarray) -> np.ndarray:
        return diag * x - np.bincount(ia, gk * x[ib], m) - np.bincount(ib, gk * x[ia], m)

    # Sums of products, not `@`: BLAS's dot spreads 1 vector over every processor, and on a machine with
    # other work each call took 10 ms where the plain sum takes 5 us.
    def dot(u: np.ndarray, v: np.ndarray) -> float:
        return float(np.sum(u * v))

    rhs = right[free]
    x = np.zeros(m)
    r = rhs.copy()
    z = r / diag
    p = z.copy()
    rz = dot(r, z)
    goal = (RELATIVE * max(math.sqrt(dot(rhs, rhs)), 1e-300)) ** 2
    for _ in range(max(1000, 20 * m)):
        if dot(r, r) <= goal:
            break
        q = apply(p)
        step = rz / dot(p, q)
        x += step * p
        r -= step * q
        z = r / diag
        rz, before = dot(r, z), rz
        p = z + (rz / before) * p
    else:
        raise CopperError(f"the solver did not settle in {max(1000, 20 * m)} steps on {m} cells")
    out = np.zeros(n)
    out[free] = x
    return out


def _links(shape, links) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Barrels as edges: (layer, layer, iy, ix, conductance) between the 2 layers' cells at iy, ix."""
    _, ny, nx = shape
    if not links:
        return np.zeros(0, int), np.zeros(0, int), np.zeros(0)
    arr = np.array(links, dtype=float)
    l1, l2, iy, ix = (arr[:, k].astype(int) for k in range(4))
    return (l1 * ny + iy) * nx + ix, (l2 * ny + iy) * nx + ix, arr[:, 4]


def _share(mask, share) -> np.ndarray:
    return mask.astype(float) if share is None else np.where(mask, share, 0.0)


def _conducts(mask, share, factor) -> np.ndarray:
    """The part of each cell that conducts as the sheet does: its copper share times its conductivity
    over the sheet's (the resistivity the sheet was taken at over the cell's own), 1 where not given."""
    part = _share(mask, share)
    return part if factor is None else part * np.where(mask, factor, 0.0)


def solve_drop(mask, sheet, links, fixed, amps, share=None, factor=None) -> np.ndarray:
    """The voltage of each copper cell, V, NaN off the copper.

    mask: [layers, ny, nx] copper of 1 net; sheet: [layers] siemens per square; links: (layer, layer,
    iy, ix, siemens) barrels; fixed: cells held at 0 V; amps: the current into each cell (a pin that
    draws a current has it below 0); share: the part of each cell that is copper, 1 where not given;
    factor: each cell's conductivity over the sheet's, 1 where not given.
    Copper that no held cell reaches stands at NaN, and a current into it is refused."""
    shape, n = mask.shape, mask.size
    a, b = _faces(shape)
    flat = mask.ravel()
    part = _conducts(mask, share, factor).ravel()
    lay = np.repeat(np.asarray(sheet, float), shape[1] * shape[2])
    keep = flat[a] & flat[b]
    a, b = a[keep], b[keep]
    g = lay[a] * _harmonic(part[a], part[b])
    la, lb, lg = _links(shape, links)
    a, b, g = np.concatenate([a, la]), np.concatenate([b, lb]), np.concatenate([g, lg])
    root = _roots(n, a, b)
    held = np.isin(root, root[fixed.ravel() & flat])
    reached = flat & held
    lost = flat & ~held & (amps.ravel() != 0)
    if lost.any():
        iz, iy, ix = np.unravel_index(int(np.flatnonzero(lost)[0]), shape)
        raise CopperError(f"a pin's copper (layer {iz}, cell {iy},{ix}) does not reach the entry pin")
    free = reached & ~fixed.ravel()
    v = _solve(n, a, b, g, np.zeros(n), amps.ravel().astype(float), free)
    v[~reached] = np.nan
    return v.reshape(shape)


def side_conductances(mask, sheet, share=None, factor=None) -> tuple[np.ndarray, np.ndarray]:
    """The conductance of each cell's right side and lower side, S: the 2 half cells in series, each
    the sheet times the part of its cell that is copper (and its conductivity's factor); 0 where no
    copper joins."""
    s = np.asarray(sheet, float)[:, None, None]
    part = _conducts(mask, share, factor)
    gx = s * _harmonic(part[:, :, :-1], part[:, :, 1:]) * (mask[:, :, :-1] & mask[:, :, 1:])
    gy = s * _harmonic(part[:, :-1, :], part[:, 1:, :]) * (mask[:, :-1, :] & mask[:, 1:, :])
    return gx, gy


def side_currents(volts, mask, sheet, share=None, factor=None) -> tuple[np.ndarray, np.ndarray]:
    """The current through each cell's right side and lower side, amperes; 0 where no copper joins."""
    v = np.where(mask & np.isfinite(volts), volts, 0.0)
    gx, gy = side_conductances(mask, sheet, share, factor)
    return gx * (v[:, :, :-1] - v[:, :, 1:]), gy * (v[:, :-1, :] - v[:, 1:, :])


def density(volts, mask, sheet, thick, pitch, share=None, factor=None) -> np.ndarray:
    """A/mm2 in each copper cell: the mean of the currents through its 2 sides along x and along y,
    over the cell's copper section, pitch x its share x thickness (mm). NaN off the copper."""
    ix, iy = side_currents(volts, mask, sheet, share, factor)
    jx = np.zeros(mask.shape)
    jy = np.zeros(mask.shape)
    jx[:, :, :-1] += ix
    jx[:, :, 1:] += ix
    jy[:, :-1, :] += iy
    jy[:, 1:, :] += iy
    section = pitch * np.asarray(thick, float)[:, None, None] * _share(mask, share)
    j = np.divide(np.hypot(jx, jy) / 2, section, out=np.zeros(mask.shape), where=section > 0)
    return np.where(mask, j, np.nan)


def joule(volts, mask, sheet, links, share=None, factor=None) -> np.ndarray:
    """The I^2 R of each cell, W: each side's half to each of its 2 cells, each barrel's half to each
    end."""
    v = np.where(mask & np.isfinite(volts), volts, 0.0)
    gx, gy = side_conductances(mask, sheet, share, factor)
    px = gx * (v[:, :, :-1] - v[:, :, 1:]) ** 2 / 2
    py = gy * (v[:, :-1, :] - v[:, 1:, :]) ** 2 / 2
    out = np.zeros(mask.shape)
    out[:, :, :-1] += px
    out[:, :, 1:] += px
    out[:, :-1, :] += py
    out[:, 1:, :] += py
    for l1, l2, iy_, ix_, g in links:
        p = g * (v[l1, iy_, ix_] - v[l2, iy_, ix_]) ** 2 / 2
        out[l1, iy_, ix_] += p
        out[l2, iy_, ix_] += p
    return out


def solve_heat(lateral, vertical, air, watts, links) -> np.ndarray:
    """The rise of each cell over the air, K.

    lateral: [layers, ny, nx] W/K per square of each cell's sheet; vertical: [layers - 1, ny, nx] W/K
    between a cell and the one under it; air: [layers, ny, nx] W/K from a cell to the air; watts: the
    heat into each cell; links: (layer, layer, iy, ix, W/K) barrels."""
    shape, n = lateral.shape, lateral.size
    a, b = _faces(shape)
    flat = lateral.ravel()
    g = _harmonic(flat[a], flat[b])
    idx = np.arange(n).reshape(shape)
    va, vb = idx[:-1].ravel(), idx[1:].ravel()
    la, lb, lg = _links(shape, links)
    a = np.concatenate([a, va, la])
    b = np.concatenate([b, vb, lb])
    g = np.concatenate([g, np.asarray(vertical, float).ravel(), lg])
    keep = g > 0
    return _solve(
        n, a[keep], b[keep], g[keep], air.ravel().astype(float), watts.ravel(), np.ones(n, bool)
    ).reshape(shape)


# ---------------------------------------------------------------- the constants and the project's files


@dataclass
class Constant:
    value: float
    source: str  # the document, its revision and the place of the number in it


def read_materials(path: Path = MATERIALS) -> dict[str, Constant]:
    data = json.loads(path.read_text(encoding="utf-8"))
    docs = data.pop("documents")
    out = {}
    for key, entry in data.items():
        doc = docs[entry["document"]]
        out[key] = Constant(float(entry["value"]), f"{doc['number']} ({doc['revision']}), {entry['where']}")
    return out


@dataclass
class Limit:
    value: float
    source: str  # the project's words
    where: str  # the key that states it: `copper.json: nets: +5V: volts`


@dataclass
class NetAsk:
    name: str  # the board's name of the net
    entry: str  # the entry pins as the lines print them: `J1.1`, or `J1.1, J1.2`
    volts: Limit | None
    density: Limit | None
    entries: list[str] = field(default_factory=list)  # REF.PAD of each pin the current comes in at

    def __post_init__(self) -> None:
        if not self.entries:
            self.entries = [self.entry]


@dataclass
class Asked:
    nets: list[NetAsk]
    ambient: float
    h: Constant
    air: str  # the project's words for the air: the assumption the report states
    temperature: Limit | None
    drop_pitch: float
    heat_pitch: float
    plating: Constant | None = None  # mm of copper in a barrel, when copper.json states it


def board_name(key: str, names: set[str]) -> str | None:
    """The board's own spelling of a net: a local label's net is `/NAME`, and either finds it."""
    return next((n for n in (key, key.lstrip("/"), f"/{key}") if n in names), None)


def _limit(where: str, raw: object) -> Limit:
    entry = ratings._keys(where, raw, ("max", "source"))
    return Limit(
        ratings._number(f"{where}: max", entry["max"], above=0),
        ratings._text(f"{where}: source", entry["source"]),
        where,
    )


def read_copper(path: Path, nets: set[str], pads: dict[str, str], materials: dict[str, Constant]) -> Asked:
    """A project's copper.json, held to the board: each net and each entry pin is one of the board's."""
    name = path.name
    data = ratings._keys(name, ratings._json(path), ("air", "nets"), ("temperature", "grid", "plating"))
    air = ratings._keys(f"{name}: air", data["air"], ("ambient", "source"), ("h",))
    ambient = ratings._number(f"{name}: air: ambient", air["ambient"], -273.15)
    alpha = materials["copper_temperature_coefficient"]
    coldest = 20.0 - 1.0 / alpha.value  # where rho20 (1 + alpha (T - 20)) reaches 0
    if ambient <= coldest:
        raise ratings.Refusal(
            f"{name}: air: ambient: {ambient:g} C is not above {coldest:.4g} C, where copper's resistivity "
            f"by the linear coefficient {alpha.value:g} per C ({alpha.source}) reaches 0"
        )
    words = ratings._text(f"{name}: air: source", air["source"])
    if "h" in air:
        h = Constant(ratings._number(f"{name}: air: h", air["h"], above=0), f"{name}: air: {words}")
    else:
        h = materials["air_natural_convection"]
    grid = ratings._keys(f"{name}: grid", data.get("grid", {}), (), ("drop", "heat"))
    drop = ratings._number(f"{name}: grid: drop", grid.get("drop", DROP_PITCH), 0.01, 1.0)
    heat = ratings._number(f"{name}: grid: heat", grid.get("heat", HEAT_PITCH), drop, 5.0)
    cells = heat / drop
    if abs(cells - round(cells)) > 1e-6 * cells:  # the heat's cell is made of whole drop cells
        raise ratings.Refusal(
            f"{name}: grid: heat: {heat:g} mm is not a whole number of the drop's {drop:g} mm cells"
        )
    plating = None
    if "plating" in data:
        entry = ratings._keys(f"{name}: plating", data["plating"], ("mm", "source"))
        plating = Constant(
            ratings._number(f"{name}: plating: mm", entry["mm"], above=0),
            f"{name}: plating: {ratings._text(f'{name}: plating: source', entry['source'])}",
        )
    asks = []
    for key, raw in ratings._object(f"{name}: nets", data["nets"], "net").items():
        where = f"{name}: nets: {key}"
        entry = ratings._keys(where, raw, ("from",), ("volts", "amps_per_mm2"))
        found = board_name(key, nets)
        if found is None:
            raise ratings.Refusal(f"{where}: no net of the board has this name")
        raw_from = entry["from"]
        if isinstance(raw_from, list):
            if not raw_from:
                raise ratings.Refusal(f"{where}: from: a pin, or a list of pins, is asked")
            pins = [ratings._text(f"{where}: from", p) for p in raw_from]
        else:
            pins = [ratings._text(f"{where}: from", raw_from)]
        for pin in pins:
            if pads.get(pin) != found:
                on = f"is on {pads[pin]}" if pin in pads else "is no pad of the board"
                raise ratings.Refusal(f"{where}: from: {pin} {on}, not on {found}")
            if pins.count(pin) > 1:
                raise ratings.Refusal(f"{where}: from: {pin} stands more than once")
        asks.append(
            NetAsk(
                found,
                ", ".join(pins),
                _limit(f"{where}: volts", entry["volts"]) if "volts" in entry else None,
                _limit(f"{where}: amps_per_mm2", entry["amps_per_mm2"]) if "amps_per_mm2" in entry else None,
                pins,
            )
        )
    hot = _limit(f"{name}: temperature", data["temperature"]) if "temperature" in data else None
    return Asked(asks, ambient, h, words, hot, drop, heat, plating)


# ---------------------------------------------------------------- the board's copper


@dataclass
class Shape:
    """1 item's copper: a pad, a track, an arc, a via or a filled pour's piece."""

    kind: str
    net: str
    layers: list[str]
    polys: dict[str, list]  # layer -> [(outline, [holes])], mm
    at: tuple[float, float] = (0.0, 0.0)
    drill: float = 0.0  # mm, of a plated hole; 0 for none
    ref: str = ""
    pad: str = ""
    width: float = 0.0  # mm, of a track or an arc


@dataclass
class Grid:
    x0: float
    y0: float
    pitch: float
    nx: int
    ny: int

    def cell(self, x: float, y: float) -> tuple[int, int]:
        iy = min(self.ny - 1, max(0, int((y - self.y0) / self.pitch)))
        return iy, min(self.nx - 1, max(0, int((x - self.x0) / self.pitch)))

    def centre(self, iy: int, ix: int) -> tuple[float, float]:
        return self.x0 + (ix + 0.5) * self.pitch, self.y0 + (iy + 0.5) * self.pitch


def _ring(grid: Grid, pts: list) -> np.ndarray:
    """The cells whose centres lie inside 1 closed ring of points, by the count of crossings."""
    out = np.zeros((grid.ny, grid.nx), dtype=bool)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    i0 = max(0, int((min(xs) - grid.x0) / grid.pitch))
    i1 = min(grid.nx, int((max(xs) - grid.x0) / grid.pitch) + 2)
    j0 = max(0, int((min(ys) - grid.y0) / grid.pitch))
    j1 = min(grid.ny, int((max(ys) - grid.y0) / grid.pitch) + 2)
    if i0 >= i1 or j0 >= j1:
        return out
    cx = grid.x0 + (np.arange(i0, i1) + 0.5) * grid.pitch
    cy = grid.y0 + (np.arange(j0, j1) + 0.5) * grid.pitch
    x, y = np.meshgrid(cx, cy)
    inside = np.zeros(x.shape, dtype=bool)
    for (xa, ya), (xb, yb) in zip(pts, pts[1:] + pts[:1], strict=True):
        if ya == yb:
            continue
        crosses = (ya > y) != (yb > y)
        inside ^= crosses & (x < xa + (y - ya) * (xb - xa) / (yb - ya))
    out[j0:j1, i0:i1] = inside
    return out


def fill(grid: Grid, polys: list) -> np.ndarray:
    out = np.zeros((grid.ny, grid.nx), dtype=bool)
    for outline, holes in polys:
        if len(outline) < 3:
            continue
        piece = _ring(grid, outline)
        for hole in holes:
            if len(hole) > 2:
                piece &= ~_ring(grid, hole)
        out |= piece
    return out


SHARE_LEAST = (
    1e-3  # a cell with less of its area in copper is no copper: the less copper, the higher the drop
)


def _ring_area(grid: Grid, pts: list) -> np.ndarray:
    """The part of each cell's area inside 1 closed ring of points, exact for straight edges.

    Each edge adds its signed area to the cells of each row it crosses, and a sum along each row gives
    the area to the right of the edges: the accumulation of R. Levien's font-rs rasteriser."""
    acc = np.zeros((grid.ny, grid.nx + 2))
    # x is kept on the grid, so no index runs off a row; the grid holds the board's every point
    p = [(min(max((x - grid.x0) / grid.pitch, 0.0), grid.nx), (y - grid.y0) / grid.pitch) for x, y in pts]
    for (xa, ya), (xb, yb) in zip(p, p[1:] + p[:1], strict=True):
        if ya == yb:
            continue
        sign = 1.0
        if ya > yb:
            (xa, ya), (xb, yb), sign = (xb, yb), (xa, ya), -1.0
        dxdy = (xb - xa) / (yb - ya)
        for row in range(max(0, math.floor(ya)), min(grid.ny, math.ceil(yb))):
            top, bottom = max(float(row), ya), min(row + 1.0, yb)
            x = xa + (top - ya) * dxdy
            xn = x + (bottom - top) * dxdy
            d = sign * (bottom - top)
            x0, x1 = min(x, xn), max(x, xn)
            i0, i1 = math.floor(x0), math.ceil(x1)
            line = acc[row]
            if i1 <= i0 + 1:
                xm = 0.5 * (x + xn) - i0
                line[i0] += d * (1 - xm)
                line[i0 + 1] += d * xm
                continue
            s = 1.0 / (x1 - x0)
            f0 = x0 - i0
            a0 = 0.5 * s * (1 - f0) ** 2
            f1 = x1 - i1 + 1
            am = 0.5 * s * f1 * f1
            line[i0] += d * a0
            if i1 == i0 + 2:
                line[i0 + 1] += d * (1 - a0 - am)
            else:
                a1 = s * (1.5 - f0)
                line[i0 + 1] += d * (a1 - a0)
                line[i0 + 2 : i1 - 1] += d * s
                a2 = a1 + (i1 - i0 - 3) * s
                line[i1 - 1] += d * (1 - a2 - am)
            line[i1] += d * am
    return np.minimum(np.abs(np.cumsum(acc, axis=1)[:, : grid.nx]), 1.0)


def cover(grid: Grid, polys: list) -> np.ndarray:
    """The part of each cell's area that 1 item's copper covers, 0 to 1: each outline less its holes.
    2 outlines of 1 item that overlap count their overlap once, by the greater of the 2."""
    out = np.zeros((grid.ny, grid.nx))
    for outline, holes in polys:
        if len(outline) < 3:
            continue
        piece = _ring_area(grid, outline)
        for hole in holes:
            if len(hole) > 2:
                piece = piece - _ring_area(grid, hole)
        np.maximum(out, np.clip(piece, 0.0, 1.0), out=out)
    return out


class BoardCopper:
    """A board's copper and parts as KiCad's pcbnew reads them, in mm."""

    def __init__(self, path: Path):
        import inspect_board as ib
        import pcbnew

        board = ib.Board(path)
        self.path = path
        self.layers = list(board.copper)
        self.cu = board.cu
        self.stackup = board.has_stackup
        self.plating = ib.mm(board.ds.GetHolePlatingThickness())
        self.thickness = board.ds.GetBoardThickness() / 1e6
        edge = pcbnew.SHAPE_POLY_SET()
        board.pcb.GetBoardPolygonOutlines(edge, False)
        self.outline = ib.outlines(edge)
        self.shapes: list[Shape] = []
        self.parts: dict[str, ratings.Part] = {}
        self.where: dict[str, tuple[float, float]] = {}
        for it in board.items(pours=True):
            if it.kind == "npth":
                continue
            if it.kind == "pour":
                polys = {it.layers[0]: ib.outlines(it.obj)}
            else:
                polys = {}
                for layer in it.layers:
                    buf = pcbnew.SHAPE_POLY_SET()
                    it.obj.TransformShapeToPolygon(buf, board.lid[layer], 0, 2000, pcbnew.ERROR_INSIDE)
                    polys[layer] = ib.outlines(buf)
            shape = Shape(it.kind, it.net, list(it.layers), polys)
            if it.kind in ("pad", "via"):
                p = it.obj.GetPosition()
                shape.at = (ib.mm(p.x), ib.mm(p.y))
            if it.kind == "via":
                shape.drill = ib.mm(it.obj.GetDrillValue())
            if it.kind in ("track", "arc"):
                shape.width = ib.mm(it.obj.GetWidth())
            if it.kind == "pad":
                shape.ref, shape.pad = it.ref, it.obj.GetNumber()
                if it.hole is not None and len(it.layers) > 1:
                    shape.drill = ib.mm(min(it.obj.GetDrillSizeX(), it.obj.GetDrillSizeY()))
            self.shapes.append(shape)
        for fp in board.pcb.GetFootprints():
            ref = fp.GetReference()
            part = ratings.Part(ref, fp.GetValue(), str(fp.GetFPIDAsString()), "", True)
            for pad in fp.Pads():
                if pad.GetNumber() and pad.GetNetname():
                    part.pins[pad.GetNumber()] = pad.GetNetname()
            self.parts[ref] = part
            p = fp.GetPosition()
            self.where[ref] = (ib.mm(p.x), ib.mm(p.y))
        points = [pt for outline, _ in self.outline for pt in outline]
        points += [pt for s in self.shapes for polys in s.polys.values() for ol, _ in polys for pt in ol]
        if not points:
            raise CopperError(f"{path.name} holds no copper and no outline")
        self.box = (
            min(x for x, _ in points),
            min(y for _, y in points),
            max(x for x, _ in points),
            max(y for _, y in points),
        )

    def netlist(self) -> ratings.Netlist:
        """The board's parts and nets in the form ratings.json is read against."""
        nets: dict[str, list[ratings.Node]] = {}
        for part in self.parts.values():
            for pin, net in part.pins.items():
                nets.setdefault(net, []).append(ratings.Node(part.ref, pin, "", "passive", False))
        return ratings.Netlist(dict(self.parts), nets)

    def pads(self) -> dict[str, str]:
        return {f"{s.ref}.{s.pad}": s.net for s in self.shapes if s.kind == "pad"}

    def grid(self, pitch: float, multiple: int = 1) -> Grid:
        x0, y0, x1, y1 = self.box
        step = pitch * multiple
        nx = math.ceil((x1 - x0) / step) * multiple
        ny = math.ceil((y1 - y0) / step) * multiple
        return Grid(x0, y0, pitch, max(nx, multiple), max(ny, multiple))

    def barrels(self, net: str | None = None) -> list[Shape]:
        return [s for s in self.shapes if s.drill > 0 and (net is None or s.net == net)]

    def pairs(self, s: Shape) -> list[tuple[int, int, float, float]]:
        """(layer, layer, depth between them in mm, the barrel's copper section in mm2) for each 2
        neighbouring layers a plated hole joins."""
        ids = sorted((self.layers.index(ly) for ly in s.layers), key=lambda i: self.cu[self.layers[i]].z)
        r = s.drill / 2
        area = math.pi * ((r + self.plating) ** 2 - r**2)
        out = []
        for i, j in zip(ids, ids[1:], strict=False):
            dz = abs(self.cu[self.layers[j]].z - self.cu[self.layers[i]].z)
            if dz > 0:
                out.append((i, j, dz, area))
        return out

    def nearest(self, x: float, y: float) -> str:
        if not self.where:
            return ""
        return min(self.where, key=lambda r: math.hypot(self.where[r][0] - x, self.where[r][1] - y))


# ---------------------------------------------------------------- 1 net's drop


@dataclass
class Finding:
    status: str  # fail, not judged, hold
    text: str
    source: str = ""

    @property
    def line(self) -> str:
        return f"copper: {self.status} {self.text}" + (f" ({self.source})" if self.source else "")


@dataclass
class NetResult:
    name: str
    entry: str
    amps: float  # the sum of the currents drawn
    drop: float  # V, the greatest
    drop_at: str
    density: float  # A/mm2, the greatest
    density_at: tuple[float, float, str]
    files: list[str] = field(default_factory=list)
    watts: float = 0.0  # the net's own I^2 R, W
    barrel: dict | None = None  # the barrel of the greatest current density: at, layers, amps, density


def _pad_cells(bc: BoardCopper, grid: Grid, net: str) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """The part of each cell that is the net's copper, and each pad's cells."""
    share = np.zeros((len(bc.layers), grid.ny, grid.nx))
    cells: dict[str, np.ndarray] = {}
    for s in bc.shapes:
        if s.net != net:
            continue
        for layer, polys in s.polys.items():
            m = cover(grid, polys)
            li = bc.layers.index(layer)
            np.maximum(share[li], m, out=share[li])
            if s.kind == "pad":
                key = f"{s.ref}.{s.pad}"
                cells.setdefault(key, np.zeros(share.shape, dtype=bool))[li] |= m >= SHARE_LEAST
    return share, cells


def barrel_cells(grid: Grid, at: tuple[float, float], drill: float, plating: float):
    """A plated hole on the grid: the cells of its hole (no copper on any layer) and the ring of cells
    round it that its barrel joins, each taking an equal share; the nearest cell when the hole is
    smaller than a cell."""
    r = drill / 2
    reach = r + max(plating, grid.pitch)
    (j0, i0), (j1, i1) = grid.cell(at[0] - reach, at[1] - reach), grid.cell(at[0] + reach, at[1] + reach)
    jj, ii = np.mgrid[j0 : j1 + 1, i0 : i1 + 1]
    d = np.hypot(grid.x0 + (ii + 0.5) * grid.pitch - at[0], grid.y0 + (jj + 0.5) * grid.pitch - at[1])
    hole = np.zeros((grid.ny, grid.nx), dtype=bool)
    hole[jj[d < r], ii[d < r]] = True
    ring = list(zip(jj[(d >= r) & (d < reach)].tolist(), ii[(d >= r) & (d < reach)].tolist(), strict=True))
    if not ring:
        return np.zeros_like(hole), [grid.cell(*at)]
    return hole, ring


@dataclass
class Barrel:
    """The current through 1 plated hole's barrel between 2 neighbouring layers."""

    at: tuple[float, float]
    layers: tuple[str, str]
    amps: float
    area: float  # mm2 of copper: pi ((r + plating)^2 - r^2)
    density: float  # A/mm2
    name: str = "the via"


@dataclass
class NetDrop:
    volts: np.ndarray
    density: np.ndarray
    heat: np.ndarray
    drops: dict[str, float]
    mask: np.ndarray
    barrels: list[Barrel]


def net_drop(
    bc: BoardCopper,
    grid: Grid,
    net: str,
    entry: str | list[str],
    draws: dict[str, float],
    rho: float,
    rho_cells: np.ndarray | None = None,
):
    """The voltages, densities and I^2 R of 1 net with its entry pins held at 0 V and each pin drawing
    its current, and the current through each barrel. A cell's sheet is weighted by the part of it that
    is copper. rho: Ohm m of the sheet; rho_cells: Ohm m of each cell of the grid, [layers, ny, nx], at
    its own temperature, in place of rho where given."""
    entries = [entry] if isinstance(entry, str) else list(entry)
    share, cells = _pad_cells(bc, grid, net)
    factor = None if rho_cells is None else rho / np.asarray(rho_cells, float)
    links = []
    joins = []  # (the barrel, layer, layer, area, its links' first and last index)
    for s in bc.barrels(net):
        hole, ring = barrel_cells(grid, s.at, s.drill, bc.plating)
        for layer in s.layers:
            share[bc.layers.index(layer)][hole] = 0.0
        for i, j, dz, area in bc.pairs(s):
            here = rho
            if rho_cells is not None:  # the barrel at the mean of its ring's cells on its 2 layers
                here = float(np.mean([rho_cells[li, iy, ix] for iy, ix in ring for li in (i, j)]))
            g = area * 1e-6 / (here * dz * 1e-3) / len(ring)
            first = len(links)
            for iy, ix in ring:
                for li in (i, j):
                    if share[li, iy, ix] < SHARE_LEAST:  # the barrel's own copper stands there
                        share[li, iy, ix] = 1.0
                links.append((i, j, iy, ix, g))
            joins.append((s, i, j, area, first, len(links)))
    mask = share >= SHARE_LEAST
    for key in cells:
        cells[key] &= mask
    for pin in [*entries, *draws]:
        if pin not in cells or not cells[pin].any():
            raise CopperError(f"{net}: {pin} has no copper cell on a grid of {grid.pitch:g} mm")
    thick = np.array([bc.cu[ly].thickness for ly in bc.layers])
    sheet = thick * 1e-3 / rho
    amps = np.zeros(mask.shape)
    for pin, current in draws.items():  # each cell of a pad draws by the part of it that is copper
        weight = np.where(cells[pin], share, 0.0)
        amps -= current * weight / weight.sum()
    held = np.zeros(mask.shape, dtype=bool)
    for pin in entries:
        held |= cells[pin]
    try:
        volts = solve_drop(mask, sheet, links, held, amps, share, factor)
    except CopperError as exc:
        raise CopperError(f"{net}: {exc} on a grid of {grid.pitch:g} mm") from None
    dens = density(volts, mask, sheet, thick, grid.pitch, share, factor)
    heat = joule(volts, mask, sheet, links, share, factor)
    drops = {pin: -float(np.nanmean(volts[cells[pin]])) for pin in draws}
    v = np.nan_to_num(volts)
    barrels = []
    for s, i, j, area, first, last in joins:
        through = sum(g * (v[i, iy, ix] - v[j, iy, ix]) for _, _, iy, ix, g in links[first:last])
        layers = (bc.layers[i], bc.layers[j])
        name = "the via" if s.kind == "via" else f"the plated hole of {s.ref}.{s.pad}"
        barrels.append(Barrel(s.at, layers, abs(float(through)), area, abs(float(through)) / area, name))
    return NetDrop(volts, dens, heat, drops, mask, barrels)


def barrel_finding(ask: NetAsk, barrel: Barrel, near: str) -> Finding:
    """The greatest current density in a net's barrels against the net's `amps_per_mm2`."""
    x, y = barrel.at
    text = (
        f"{ask.name} barrel current density {barrel.density:.4g} A/mm2, {barrel.amps:.4g} A in "
        f"{barrel.name} at ({x:.2f}, {y:.2f}) {barrel.layers[0]} to {barrel.layers[1]}, near {near}"
    )
    if ask.density is None:
        return Finding("not judged", f"{text}: copper.json states no `amps_per_mm2` limit")
    ok = barrel.density <= ask.density.value
    return Finding(
        "hold" if ok else "fail",
        f"{text}, limit {ask.density.value:g} A/mm2",
        f"{ask.density.where}: {ask.density.source}",
    )


def check_grid(bc: BoardCopper, nets: list[str], pitch: float) -> None:
    """A cell of the drop no wider than the narrowest track of a judged net: a coarser cell can let a
    neck's copper fall between cells, and the run would blame the board for the grid."""
    for net in nets:
        widths = [s.width for s in bc.shapes if s.net == net and s.width > 0]
        if widths and pitch > min(widths) + 1e-9:
            w = min(widths)
            raise ratings.Refusal(
                f"copper.json: grid: drop: {pitch:g} mm is wider than {net}'s narrowest track, {w:g} mm; "
                f"a cell of at most {w:g} mm is asked"
            )


# ---------------------------------------------------------------- the heat


def board_inside(bc: BoardCopper, fine: Grid, f: int) -> np.ndarray:
    """The cells of the heat's grid that are board: at least half of each inside the outline."""
    ny, nx = fine.ny // f, fine.nx // f
    if not bc.outline:
        return np.ones((ny, nx), dtype=bool)
    return fill(fine, bc.outline).reshape(ny, f, nx, f).mean(axis=(1, 3)) >= 0.5


def place_heat(bc: BoardCopper, fine: Grid, f: int, watts: dict[str, float]):
    """Each stated heat on the drop's grid, W per cell: `U1` over its pads by their copper area, `U1.2`
    on that pad; only on the cells that are board, for heat put off the board would leave by nothing.
    Returns the heat, a not-judged finding for each heat with no pad on the board, and for each heat
    placed the words of how it enters."""
    inside = np.repeat(np.repeat(board_inside(bc, fine, f), f, axis=0), f, axis=1)
    heat = np.zeros((len(bc.layers), fine.ny, fine.nx))
    notes: list[Finding] = []
    how: dict[str, str] = {}
    for key, w in watts.items():
        ref, _, number = key.partition(".")
        pads = [s for s in bc.shapes if s.kind == "pad" and s.ref == ref and (not number or s.pad == number)]
        cells = np.zeros(heat.shape, dtype=bool)
        for s in pads:
            for layer, polys in s.polys.items():
                cells[bc.layers.index(layer)] |= fill(fine, polys)
        if not cells.any():
            notes.append(Finding("not judged", f"{key}: its {w:g} W has no pad copper to enter by"))
            continue
        on = cells & inside[None]
        if not on.any():
            notes.append(
                Finding(
                    "not judged",
                    f"{key}: its {w:g} W enters by pads that lie off the board's outline; it is not counted",
                )
            )
            continue
        heat[on] += w / on.sum()
        count = len({s.pad for s in pads})
        if number:
            words = "on that pad"
        elif count == 1:
            words = "over its 1 pad by its copper area"
        else:
            words = f"split over its {count} pads by their copper area"
        off = 1.0 - on.sum() / cells.sum()
        if off > 0:
            words += f"; {off * 100:.0f} % of that area lies off the board's outline"
        how[key] = words
    return heat, notes, how


def board_heat(bc: BoardCopper, asked: Asked, materials, watts_fine: np.ndarray, fine: Grid, f: int):
    """The temperature of every cell of every layer, C, on the heat's grid; NaN off the board."""
    layers = len(bc.layers)
    ny, nx = fine.ny // f, fine.nx // f
    hp = fine.pitch * f * 1e-3  # m
    coarse = Grid(fine.x0, fine.y0, fine.pitch * f, nx, ny)
    frac = np.zeros((layers, ny, nx))  # the part of each cell that is copper
    for s in bc.shapes:
        for layer, polys in s.polys.items():
            li = bc.layers.index(layer)
            np.maximum(frac[li], cover(coarse, polys), out=frac[li])
    inside = board_inside(bc, fine, f)
    k_cu = materials["copper_thermal_conductivity"].value
    k_fr4 = materials["fr4_thermal_conductivity"].value
    t = np.array([bc.cu[ly].thickness for ly in bc.layers])  # mm
    share = max(bc.thickness - t.sum(), 0.0) / layers  # each layer's share of the laminate, mm
    lateral = (k_cu * t[:, None, None] * 1e-3 * frac + k_fr4 * share * 1e-3) * inside
    z = np.array([bc.cu[ly].z for ly in bc.layers])
    vertical = (
        np.stack(
            [
                np.full((ny, nx), k_fr4 * hp * hp / (abs(z[i + 1] - z[i]) * 1e-3)) * inside
                for i in range(layers - 1)
            ]
        )
        if layers > 1
        else np.zeros((0, ny, nx))
    )
    air = np.zeros((layers, ny, nx))
    face = asked.h.value * hp * hp
    air[0] += face * inside
    air[-1] += face * inside
    air[:, ~inside] = 1.0  # a cell off the board stands alone at the air's temperature
    links = []
    for s in bc.barrels():
        _, ring = barrel_cells(coarse, s.at, s.drill, bc.plating)
        for i, j, dz, area in bc.pairs(s):
            links += [(i, j, iy, ix, k_cu * area * 1e-6 / (dz * 1e-3) / len(ring)) for iy, ix in ring]
    watts = watts_fine.reshape(layers, ny, f, nx, f).sum(axis=(2, 4)) * inside
    rise = solve_heat(lateral, vertical, air, watts, links)
    return np.where(inside, asked.ambient + rise, np.nan), coarse


# ---------------------------------------------------------------- the pictures

RAMP = ((48, 18, 59), (70, 107, 227), (40, 188, 213), (164, 252, 60), (250, 186, 57), (180, 30, 10))


def colours(values: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """An RGB image of a field, low dark blue to high dark red; NaN white."""
    span = hi - lo if hi > lo else 1.0
    u = np.clip((np.nan_to_num(values, nan=lo) - lo) / span, 0, 1) * (len(RAMP) - 1)
    k = np.minimum(u.astype(int), len(RAMP) - 2)
    w = (u - k)[..., None]
    ramp = np.array(RAMP, dtype=float)
    rgb = ramp[k] * (1 - w) + ramp[k + 1] * w
    rgb[np.isnan(values)] = 255
    return rgb.astype(np.uint8)


def picture(path: Path, values: np.ndarray, grid: Grid, caption: list[str], unit: str) -> None:
    from PIL import Image, ImageDraw, ImageFont

    finite = values[np.isfinite(values)]
    lo, hi = (float(finite.min()), float(finite.max())) if finite.size else (0.0, 1.0)
    scale = max(1, int(900 / max(grid.nx, 1)))
    img = Image.fromarray(colours(values, lo, hi)).resize((grid.nx * scale, grid.ny * scale), Image.NEAREST)
    font = ImageFont.load_default(size=12)
    bar = 16
    frame = Image.new("RGB", (max(img.width, 520) + 20, img.height + 40 + bar + 18 * len(caption)), "white")
    frame.paste(img, (10, 10))
    d = ImageDraw.Draw(frame)
    d.rectangle([9, 9, 10 + img.width, 10 + img.height], outline=(0, 0, 0))
    top = img.height + 20
    width = max(img.width, 520) - 120
    strip = colours(np.linspace(lo, hi, width)[None, :].repeat(bar, 0), lo, hi)
    frame.paste(Image.fromarray(strip), (60, top))
    d.text((55, top + bar / 2), f"{lo:.4g}", fill=(0, 0, 0), font=font, anchor="rm")
    d.text((65 + width, top + bar / 2), f"{hi:.4g} {unit}", fill=(0, 0, 0), font=font, anchor="lm")
    for n, text in enumerate(caption):
        d.text((10, top + bar + 8 + 18 * n), text, fill=(0, 0, 0), font=font, anchor="lt")
    frame.save(path)


# ---------------------------------------------------------------- the run


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    nets: list[NetResult] = field(default_factory=list)
    hottest: tuple[float, float, float, str, str] | None = None  # C, x, y, layer, the nearest part
    heat_files: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    counted: list[str] = field(default_factory=list)


def stated_currents(bc: BoardCopper, project) -> tuple[dict[str, dict[str, float]], list[Finding], set[str]]:
    """net -> {REF.PAD: amps} from ratings.json: a pin's current on its net, a 2-pin part's on both;
    and every REF.PAD ratings.json states a current for, 0 A among them."""
    out: dict[str, dict[str, float]] = {}
    notes = []
    stated: set[str] = set()
    for key, amps in project.amps.items():
        ref, _, pin = key.partition(".")
        part = bc.parts[ref]
        if pin:
            stated.add(key)
        elif len(part.pins) == 2:
            stated.update(f"{ref}.{p}" for p in part.pins)
        if not amps:
            continue
        if pin:
            out.setdefault(part.pins[pin], {})[key] = amps
        elif len(part.pins) == 2:
            for p, net in part.pins.items():
                out.setdefault(net, {})[f"{ref}.{p}"] = amps
        else:
            why = f"ratings.json states {amps:g} A through {ref}, a part of {len(part.pins)} pins"
            notes.append(Finding("not judged", f"{ref}: {why}; name the pin, `{ref}.<pad>`"))
    return out, notes, stated


def _resistor_currents(bc: BoardCopper, project) -> dict[str, float]:
    """REF -> A for each 2-pin resistor ratings.json states a current for, on the part or on a pin; the
    current through 1 pin of a 2-pin part is the current through the other. The greater, if both."""
    out: dict[str, float] = {}
    for key, amps in project.amps.items():
        ref = key.partition(".")[0]
        part = bc.parts.get(ref)
        if part is None or not amps or not ref.startswith("R") or len(part.pins) != 2:
            continue
        out[ref] = max(out.get(ref, 0.0), amps)
    return out


def dissipation(bc: BoardCopper, project) -> tuple[dict[str, float], dict[str, str]]:
    """REF or REF.PAD -> W: `watts` from ratings.json, on a part or on 1 of its pads, or the stated
    current through a resistor's Value; and for each, the words that say where it comes from."""
    out = {key: w for key, w in project.watts.items() if w}
    how = {key: f"{key} {w:g} W (ratings.json: parts: {key}: watts)" for key, w in out.items()}
    stated = {key.partition(".")[0] for key in project.watts}
    for ref, amps in _resistor_currents(bc, project).items():
        part = bc.parts[ref]
        ohms = ratings.part_value(part.value)
        if ref in stated or ohms is None:
            continue
        out[ref] = amps * amps * ohms
        how[ref] = f"{ref} {out[ref]:.4g} W ({amps:g} A from ratings.json through its Value {part.value})"
    return out, how


def entry_mates(pads: dict[str, str], ask: NetAsk, drawn: dict[str, float]) -> list[str]:
    """The pins of an entry's part on the net that are not entries and draw no stated current: a second
    contact of the supply, modelled as carrying nothing unless `from` names it."""
    refs = {pin.partition(".")[0] for pin in ask.entries}
    return sorted(
        pin
        for pin, net in pads.items()
        if net == ask.name and pin not in ask.entries and pin.partition(".")[0] in refs and not drawn.get(pin)
    )


def mates_finding(ask: NetAsk, mates: list[str]) -> Finding:
    refs = ", ".join(sorted({pin.partition(".")[0] for pin in mates}))
    pins = ", ".join(mates)
    one = len(mates) == 1
    return Finding(
        "not judged",
        f"{ask.name}: {pins} {'is a pin' if one else 'are pins'} of {refs} on {ask.name} beside the entry "
        f"{ask.entry} and {'was' if one else 'were'} taken as 0 A; if it feeds the net, name it in `from`, "
        "as a list",
    )


def dissipation_notes(bc: BoardCopper, project) -> list[Finding]:
    """A resistor with a stated current, no `watts` and a Value that gives no ohms: its heat is not
    counted, and the run says so."""
    notes = []
    for ref, amps in _resistor_currents(bc, project).items():
        part = bc.parts[ref]
        if project.watts.get(ref) or ratings.part_value(part.value) is not None:
            continue
        notes.append(
            Finding(
                "not judged",
                f"{ref}: ratings.json states {amps:g} A through it and its Value {part.value} gives no ohms; "
                "state its `watts`",
            )
        )
    return notes


def run(board: Path, out: Path) -> Report:  # noqa: PLR0915
    folder = board.parent
    materials = read_materials()
    bc = BoardCopper(board)
    stated = folder / "ratings.json"
    asked_path = folder / "copper.json"
    if not asked_path.is_file():
        raise CopperError(f"no copper.json beside {board.name}: it names each power net's entry and limits")
    if not stated.is_file():
        raise CopperError(f"no ratings.json beside {board.name}: the currents come from there")
    project = ratings.read_project(stated, bc.netlist())
    asked = read_copper(asked_path, set(bc.netlist().nets), bc.pads(), materials)
    rho20 = materials["copper_resistivity"]
    alpha = materials["copper_temperature_coefficient"]
    rho = rho20.value * (1 + alpha.value * (asked.ambient - 20.0))
    k_cu, k_fr4 = materials["copper_thermal_conductivity"], materials["fr4_thermal_conductivity"]
    if asked.plating is not None:
        bc.plating = asked.plating.value
        plating_from = asked.plating.source
    else:
        plating_from = f"{board.name}'s own setting (KiCad's board setup, hole plating thickness)"
    report = Report()
    check_grid(bc, [n.name for n in asked.nets], asked.drop_pitch)
    currents, report.findings, stated_pins = stated_currents(bc, project)
    report.findings += dissipation_notes(bc, project)
    f = max(1, round(asked.heat_pitch / asked.drop_pitch))
    grid = bc.grid(asked.drop_pitch, f)
    out.mkdir(parents=True, exist_ok=True)
    named = {n.name for n in asked.nets}
    for net in sorted(set(currents) | set(project.nets)):
        if net in named:
            continue
        if net in currents:
            amps = ", ".join(f"{pin} {a:g} A" for pin, a in currents[net].items())
            why = f"ratings.json states {amps}"
        else:
            why = "ratings.json names this net"
        report.findings.append(Finding("not judged", f"{net}: {why} and copper.json names no entry for it"))
    pads = bc.pads()
    jobs: list[tuple[NetAsk, dict[str, float]]] = []
    for ask in asked.nets:
        drawn = currents.get(ask.name, {})
        mates = entry_mates(pads, ask, drawn)
        if mates:
            report.findings.append(mates_finding(ask, mates))
        silent = sorted(
            p
            for p, n in pads.items()
            if n == ask.name and p not in ask.entries and p not in stated_pins and p not in mates
        )
        if silent:
            report.findings.append(
                Finding(
                    "not judged",
                    f"{ask.name}: ratings.json states no current at {', '.join(silent)}; taken as 0 A",
                )
            )
        draws = {pin: a for pin, a in drawn.items() if pin not in ask.entries}
        if not draws:
            report.findings.append(
                Finding(
                    "not judged", f"{ask.name}: ratings.json states no current at a pin of it but {ask.entry}"
                )
            )
            continue
        jobs.append((ask, draws))
    parts_watts, how = dissipation(bc, project)
    parts_heat, notes, placed = place_heat(bc, grid, f, parts_watts)
    report.findings += notes
    report.counted = [f"{how[key]}, {placed[key]}" for key in parts_watts if key in placed]
    # The drop and the heat in turn: each cell's copper at its own temperature, until the drops settle.
    rho_cells, before, temp, coarse, passes = None, None, None, None, 0
    while True:
        solves = [net_drop(bc, grid, ask.name, ask.entries, draws, rho, rho_cells) for ask, draws in jobs]
        heat_fine = parts_heat + sum((s.heat for s in solves), np.zeros_like(parts_heat))
        drops = [max(s.drops.values()) for s in solves]
        if not heat_fine.any():
            break
        temp, coarse = board_heat(bc, asked, materials, heat_fine, grid, f)
        passes += 1
        settled = before is not None and all(
            abs(d - b) <= SETTLED * abs(b) for d, b in zip(drops, before, strict=True)
        )
        if not jobs or settled:
            break
        if passes >= PASSES:
            report.findings.append(
                Finding("not judged", f"the drop and the heat did not settle in {PASSES} passes")
            )
            break
        hot = np.repeat(np.repeat(np.where(np.isfinite(temp), temp, asked.ambient), f, axis=1), f, axis=2)
        rho_cells = rho20.value * (1 + alpha.value * (hot - 20.0))
        before = drops
    if rho_cells is None:
        rho_words = f"{rho:.5g} Ohm m in all of the copper, at the air's {asked.ambient:g} C"
    else:
        warm = float(np.nanmax(temp))
        rho_words = (
            f"{rho:.5g} Ohm m at the air's {asked.ambient:g} C. Copper's resistivity is taken at each cell's "
            f"own temperature from the heat solve: the drop and the heat were solved in turn {passes} times, "
            f"until each net's greatest drop moved less than {SETTLED * 100:g} %; the hottest copper, "
            f"{warm:.4g} C, is {rho20.value * (1 + alpha.value * (warm - 20.0)):.5g} Ohm m"
        )
    report.assumptions = [
        "The result is a steady state on the board: every current and every dissipation as stated, held "
        "until nothing changes.",
        f"The air stands at {asked.ambient:g} C and takes h = {asked.h.value:g} W/m2 K from each face "
        f"({asked.h.source}). The project's words for the air: {asked.air}. No enclosure and no air flow "
        "are modelled; a reading of the built board replaces this (ROADMAP item 12).",
        f"Copper: {rho20.value:g} Ohm m at 20 C ({rho20.source}), {alpha.value:g} per C ({alpha.source}): "
        f"{rho_words}.",
        f"Heat: copper {k_cu.value:g} W/m K ({k_cu.source}); FR-4 {k_fr4.value:g} W/m K ({k_fr4.source}).",
        "A part's heat enters the board through its pads and leaves by the board's 2 faces; the part's own "
        "body gives none to the air. A part's heat stated on the part is split over its pads by their "
        "copper area; a part that sheds its heat through 1 pad, a regulator's tab, states it on that pad "
        "(`U1.2`), or its tab reads cooler than it runs.",
        f"Grid: {asked.drop_pitch:g} mm cells for the drop, {asked.heat_pitch:g} mm for the heat; a cell's "
        "sheet is weighted by the part of its area that is copper, and its sides run along x and along y, "
        "so copper at an angle to the grid reads more resistance than it has (the skill says how much). A "
        "plated hole has no copper inside its drill, and its barrel joins its layers through the ring of "
        "cells round the drill.",
        f"Plating: {bc.plating:g} mm in each barrel, {plating_from}.",
    ]
    if not bc.stackup:
        report.assumptions.append(
            "The board has no stackup: every copper layer is taken as 35 um, spread evenly through the board."
        )
    for (ask, draws), solved in zip(jobs, solves, strict=True):
        volts, dens, heat, drops, mask = solved.volts, solved.density, solved.heat, solved.drops, solved.mask
        worst = max(drops, key=drops.get)
        li, iy, ix = np.unravel_index(int(np.nanargmax(dens)), dens.shape)
        x, y = grid.centre(iy, ix)
        res = NetResult(
            ask.name,
            ask.entry,
            sum(draws.values()),
            drops[worst],
            worst,
            float(dens[li, iy, ix]),
            (x, y, bc.layers[li]),
            watts=float(heat.sum()),
        )
        report.nets.append(res)
        drop_text = f"{ask.name} drop {res.drop * 1e3:.4g} mV from {ask.entry} to {worst}"
        if ask.volts is None:
            report.findings.append(Finding("not judged", f"{drop_text}: copper.json states no `volts` limit"))
        else:
            ok = res.drop <= ask.volts.value
            limit = f"limit {ask.volts.value * 1e3:.4g} mV"
            report.findings.append(
                Finding(
                    "hold" if ok else "fail",
                    f"{drop_text}, {limit}",
                    f"{ask.volts.where}: {ask.volts.source}",
                )
            )
        where = f"at ({x:.2f}, {y:.2f}) {bc.layers[li]}, near {bc.nearest(x, y)}"
        dens_text = f"{ask.name} current density {res.density:.4g} A/mm2 {where}"
        if ask.density is None:
            report.findings.append(
                Finding("not judged", f"{dens_text}: copper.json states no `amps_per_mm2` limit")
            )
        else:
            ok = res.density <= ask.density.value
            report.findings.append(
                Finding(
                    "hold" if ok else "fail",
                    f"{dens_text}, limit {ask.density.value:g} A/mm2",
                    f"{ask.density.where}: {ask.density.source}",
                )
            )
        if solved.barrels:
            worst_barrel = max(solved.barrels, key=lambda b: b.density)
            res.barrel = vars(worst_barrel)
            report.findings.append(barrel_finding(ask, worst_barrel, bc.nearest(*worst_barrel.at)))
        safe = ask.name.strip("/").replace("/", "_") or "net"
        for li, layer in enumerate(bc.layers):
            if not mask[li].any():
                continue
            for kind, field_, unit, words in (
                ("drop", -volts[li] * 1e3, "mV", "drop from the entry"),
                ("density", dens[li], "A/mm2", "current density"),
            ):
                path = out / f"{safe}-{kind}-{layer.replace('.', '-')}.png"
                x1, y1 = grid.x0 + grid.nx * grid.pitch, grid.y0 + grid.ny * grid.pitch
                caption = [
                    f"{bc.path.parent.name}/{bc.path.name}  {ask.name} {words}, {layer}, seen from the top",
                    f"{res.amps:g} A in at {ask.entry}; x {grid.x0:.1f}..{x1:.1f}, "
                    f"y {grid.y0:.1f}..{y1:.1f} mm, {grid.pitch:g} mm cells",
                ]
                picture(path, np.where(mask[li], field_, np.nan), grid, caption, unit)
                res.files.append(path.name)
    if report.nets:
        report.counted.append("each judged net's own I^2 R, cell by cell")
    if asked.temperature is None:
        report.findings.append(
            Finding("not judged", "the board's temperature: copper.json states no `temperature`")
        )
    elif temp is None:
        report.findings.append(
            Finding(
                "not judged", "the board's temperature: ratings.json states no dissipation and no current"
            )
        )
    else:
        li, iy, ix = np.unravel_index(int(np.nanargmax(temp)), temp.shape)
        x, y = coarse.centre(iy, ix)
        hot, near = float(temp[li, iy, ix]), bc.nearest(x, y)
        report.hottest = (hot, x, y, bc.layers[li], near)
        ok = hot <= asked.temperature.value
        report.findings.append(
            Finding(
                "hold" if ok else "fail",
                f"board temperature {hot:.4g} C at ({x:.2f}, {y:.2f}) {bc.layers[li]}, near {near}, "
                f"limit {asked.temperature.value:g} C",
                f"{asked.temperature.where}: {asked.temperature.source}",
            )
        )
        for li, layer in enumerate(bc.layers):
            path = out / f"heat-{layer.replace('.', '-')}.png"
            caption = [
                f"{bc.path.parent.name}/{bc.path.name}  temperature, {layer}, from the top, steady state",
                f"air {asked.ambient:g} C, h {asked.h.value:g} W/m2 K each face; {coarse.pitch:g} mm cells",
            ]
            picture(path, temp[li], coarse, caption, "C")
            report.heat_files.append(path.name)
    return report


STATUSES = ("fail", "not judged", "hold")


def verdict(report: Report, strict: bool) -> tuple[str, int]:
    fail = sum(f.status == "fail" for f in report.findings)
    left = sum(f.status == "not judged" for f in report.findings)
    if fail:
        return f"COPPER NOT HELD ({fail} fail{f', {left} not judged' if left else ''})", 1
    if fail + left == len(report.findings):
        return f"NOTHING JUDGED ({left} not judged)", 1
    if left:
        return f"COPPER HELD, {left} NOT JUDGED", 1 if strict else 0
    return "COPPER HELD", 0


def head(report: Report) -> str:
    count = {s: sum(f.status == s for f in report.findings) for s in STATUSES}
    return f"copper: {count['fail']} fail, {count['hold']} hold, {count['not judged']} not judged"


def markdown(report: Report, strict: bool, name: str) -> str:
    out = ["# Copper", "", f"{name}: {head(report)}", "", verdict(report, strict)[0], ""]
    for status in STATUSES:
        found = [f for f in report.findings if f.status == status]
        if found:
            out += [f"## {status.capitalize()}: {len(found)}", ""]
            out += [f"- {f.text}" + (f" [{f.source}]" if f.source else "") for f in found] + [""]
    out += ["## Assumptions", ""] + [f"- {a}" for a in report.assumptions] + [""]
    counted = report.counted or ["nothing: ratings.json states no dissipation"]
    out += ["## Heat counted", ""] + [f"- {c}" for c in counted]
    out += ["- every other part's heat is not counted: ratings.json states none for it", ""]
    if report.nets:
        out += [
            "## Nets",
            "",
            "| Net | In at | Current | Greatest drop | At | Greatest density | At | Greatest in a barrel "
            "| I^2 R |",
        ]
        out += ["|---|---|---|---|---|---|---|---|---|"]
        for r in report.nets:
            x, y, layer = r.density_at
            barrel = "no barrel"
            if r.barrel:
                bx, by = r.barrel["at"]
                barrel = f"{r.barrel['density']:.4g} A/mm2, {r.barrel['name']} at ({bx:.2f}, {by:.2f})"
            out.append(
                f"| {r.name} | {r.entry} | {r.amps:g} A | {r.drop * 1e3:.4g} mV | {r.drop_at} | "
                f"{r.density:.4g} A/mm2 | ({x:.2f}, {y:.2f}) {layer} | {barrel} | {r.watts:.4g} W |"
            )
        out.append("")
        for r in report.nets:
            out += [f"### {r.name}", ""] + [f"![{p}]({p})" for p in r.files] + [""]
    if report.heat_files:
        hot, x, y, layer, near = report.hottest
        out += ["## Temperature", "", f"Hottest: {hot:.4g} C at ({x:.2f}, {y:.2f}) {layer}, near {near}.", ""]
        out += [f"![{p}]({p})" for p in report.heat_files] + [""]
    return "\n".join(out)


def main(argv: list[str]) -> int:
    a = json.loads(argv[1])
    try:
        import pcbnew  # noqa: F401
        import PIL  # noqa: F401
    except ImportError as exc:
        print(f"copper: {exc.name} is not importable here; install.sh puts it in the venv", file=sys.stderr)
        return 2
    board, out, strict = Path(a["board"]), Path(a["out"]), bool(a.get("strict"))
    try:
        report = run(board, out)
    except (ratings.Refusal, CopperError) as exc:
        print(f"copper: {exc}")
        return 1
    said, code = verdict(report, strict)
    (out / "report.md").write_text(markdown(report, strict, board.parent.name), encoding="utf-8")
    record = {
        "verdict": said,
        "findings": [vars(f) | {"line": f.line} for f in report.findings],
        "nets": [vars(r) for r in report.nets],
        "hottest": report.hottest,
    }
    (out / "report.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    if a.get("json"):
        print(json.dumps(record, indent=2))
        return code
    print(head(report))
    order = {"fail": 0, "not judged": 1, "hold": 2}
    for f in sorted(report.findings, key=lambda f: order[f.status]):
        print(f.line)
    print(f"{said}: {board.parent.name}  report {out / 'report.md'}")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
