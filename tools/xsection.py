#!/usr/bin/env python3
"""xsection — the impedance of a track on a board's layer stack, from a field solution.

A 2-D finite-difference solution of Laplace's equation over the cross-section: the reference plane
below at y = 0, dielectric slabs stacked on it, a second plane on top of the stack or open air above,
and 1 strip or 2 (an edge-coupled pair) at a height y with a thickness t. The capacitance per metre
with the dielectric (C) and with air everywhere (C0) gives the quasi-TEM line: Z0 = Z_F0 / sqrt(C' C0'),
eps_eff = C / C0, where C' and C0' are in units of the vacuum permittivity. For a pair the strips stand
at +1 and -1 (odd mode) and at +1 and +1 (even mode); Z_diff = 2 Z_odd.

The grid is rectilinear and graded: fine at every strip edge and slab face, growing by RATIO outward.
The outer walls are grounded and stand WALL times the stack height or the pair's width away. The
discrete energy, sum of g (phi_a - phi_b)^2 over the grid's edges, is the capacitance; it is
variational, so an error in phi enters it squared. tests/test_xsection.py holds the solver to 1 % of
Hammerstad and Jensen's microstrip and Cohn's exact stripline and coupled stripline.

A copper layer's own thickness beside the strip is taken as the slab the strip sits in, or air when the
strip stands on top of the stack (an outer layer, no solder mask).

Needs numpy: it runs under Via's venv's Python, as `tools/workcenter` runs it. As a script it
reads 1 JSON request on its argument and prints 1 JSON answer.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

import numpy as np

# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {
    "hammerstad-jensen-1980": "the microstrip's closed forms the test holds it to, as Qucs gives them",
    "matthaei-ad0402852": "section 5.05: Cohn's exact stripline and coupled stripline forms",
}

CONSTANTS = json.loads(
    (Path(__file__).resolve().parents[1] / "rules" / "interfaces" / "constants.json").read_text()
)
Z_F0 = CONSTANTS["z_f0_ohm"]["value"]
C0 = CONSTANTS["c0_m_per_s"]["value"]

RATIO = 1.25  # growth of a grid step away from an edge
WALL = 25.0  # the grounded walls' distance, in stack heights (and pair widths) from the strips
# Grid steps across the thinnest slab, strip or gap, and how much finer the grid is at a strip's edge
# and faces. At 12 and 16 the 5 closed-form cases of tests/test_xsection.py come within 0.6 %; at 24
# and 64 within 0.4 %, at 4 times the time.
CELLS = 12
EDGE = 16


@dataclass(frozen=True)
class Section:
    """slabs: (thickness, er) from the lower plane up, in mm. top_plane: a plane on the last slab,
    else air above. y: the strips' lower face above the lower plane; t: their thickness. widths: 1
    strip, or 2 for a pair `gap` apart, edge to edge."""

    slabs: list[tuple[float, float]]
    top_plane: bool
    y: float
    t: float
    widths: list[float]
    gap: float = 0.0


@dataclass
class Line:
    z0: float
    eps_eff: float
    z_odd: float = 0.0
    z_even: float = 0.0
    z_diff: float = 0.0
    eps_odd: float = 0.0
    eps_even: float = 0.0
    nodes: int = 0
    extra: dict = field(default_factory=dict)


def replace_widths(sec: Section, width: float) -> Section:
    return replace(sec, widths=[width] * len(sec.widths))


def _axis(keys: dict[float, float], lo: float, hi: float, coarse: float) -> np.ndarray:
    """Nodes from lo to hi through every key, each key's own step at it, growing by RATIO away from
    it; `coarse` at the walls."""
    steps = {round(k, 12): s for k, s in keys.items()}
    for k in (lo, hi):
        steps.setdefault(k, coarse)
    pts = sorted(steps)
    out = [pts[0]]
    for a, b in zip(pts, pts[1:], strict=False):
        left, right = [], []
        pos_l, pos_r, step_l, step_r = a, b, steps[a], steps[b]
        while pos_r - pos_l > step_l + step_r:
            if step_l <= step_r:
                pos_l += step_l
                left.append(pos_l)
                step_l *= RATIO
            else:
                pos_r -= step_r
                right.append(pos_r)
                step_r *= RATIO
        mid = [(pos_l + pos_r) / 2] if pos_r - pos_l > max(step_l, step_r) else []
        out += left + mid + right[::-1] + [b]
    return np.array(out)


def _strips(sec: Section) -> list[tuple[float, float]]:
    if len(sec.widths) == 1:
        return [(-sec.widths[0] / 2, sec.widths[0] / 2)]
    w1, w2 = sec.widths
    return [(-sec.gap / 2 - w1, -sec.gap / 2), (sec.gap / 2, sec.gap / 2 + w2)]


def _grid(sec: Section):
    faces = [0.0]
    for h, _ in sec.slabs:
        faces.append(faces[-1] + h)
    height = faces[-1]
    strips = _strips(sec)
    span = strips[-1][1] - strips[0][0]
    features = [h for h, _ in sec.slabs] + [w for w in sec.widths] + ([sec.gap] if len(strips) == 2 else [])
    fine = min(features) / CELLS
    top = height if sec.top_plane else max(height, sec.y + sec.t) + WALL * height
    side = span / 2 + WALL * max(height, span)
    # The field is singular at a strip's edge; the grid is EDGE times finer there than at a slab face.
    edge = fine / EDGE
    xs = _axis({e: edge for s in strips for e in s}, -side, side, fine * CELLS)
    ys = _axis({f: fine for f in faces} | {sec.y: edge, sec.y + sec.t: edge}, 0.0, top, fine * CELLS)
    return xs, ys, faces, strips


def _solve(sec: Section, potentials: list[float], dielectric: bool) -> tuple[float, int]:
    xs, ys, faces, strips = _grid(sec)
    nx, ny = len(xs), len(ys)
    dx, dy = np.diff(xs), np.diff(ys)
    ym = (ys[:-1] + ys[1:]) / 2
    eps_row = np.ones(ny - 1)
    if dielectric:
        for (h, er), lo in zip(sec.slabs, faces, strict=False):
            eps_row[(ym > lo) & (ym < lo + h)] = er
    eps = np.broadcast_to(eps_row, (nx - 1, ny - 1))
    # Edge conductances of the finite-volume stencil: the flux through the half cells either side.
    gx = np.zeros((nx - 1, ny))
    gx[:, :-1] += eps * dy / 2
    gx[:, 1:] += eps * dy / 2
    gx /= dx[:, None]
    gy = np.zeros((nx, ny - 1))
    gy[:-1, :] += eps * dx[:, None] / 2
    gy[1:, :] += eps * dx[:, None] / 2
    gy /= dy[None, :]

    fixed = np.zeros((nx, ny), bool)
    value = np.zeros((nx, ny))
    fixed[0, :] = fixed[-1, :] = fixed[:, 0] = fixed[:, -1] = True
    tol = 1e-9
    in_y = (ys >= sec.y - tol) & (ys <= sec.y + sec.t + tol)
    for (a, b), v in zip(strips, potentials, strict=True):
        in_x = (xs >= a - tol) & (xs <= b + tol)
        box = in_x[:, None] & in_y[None, :]
        fixed |= box
        value[box] = v
    free = ~fixed

    def apply(u: np.ndarray) -> np.ndarray:
        out = np.zeros_like(u)
        d = gx * (u[1:, :] - u[:-1, :])
        out[:-1, :] -= d
        out[1:, :] += d
        d = gy * (u[:, 1:] - u[:, :-1])
        out[:, :-1] -= d
        out[:, 1:] += d
        return out

    diag = np.zeros((nx, ny))
    diag[:-1, :] += gx
    diag[1:, :] += gx
    diag[:, :-1] += gy
    diag[:, 1:] += gy
    inv = np.where(free, 1.0 / np.where(diag > 0, diag, 1.0), 0.0)

    # Conjugate gradients on the free nodes, Jacobi-preconditioned.
    b = -apply(value) * free
    u = np.zeros_like(value)
    r = b.copy()
    z = r * inv
    p = z.copy()
    rz = float((r * z).sum())
    stop = 1e-20 * max(float((b * b).sum()), 1e-300)
    for _ in range(20 * (nx + ny)):
        ap = apply(p) * free
        alpha = rz / float((p * ap).sum())
        u += alpha * p
        r -= alpha * ap
        if float((r * r).sum()) < stop:
            break
        z = r * inv
        rz_new = float((r * z).sum())
        p = z + (rz_new / rz) * p
        rz = rz_new
    phi = value + u
    energy = float((gx * np.diff(phi, axis=0) ** 2).sum() + (gy * np.diff(phi, axis=1) ** 2).sum())
    return energy / sum(v * v for v in potentials), nx * ny


def solve(sec: Section) -> Line:
    """The line's impedance and effective permittivity; for a pair, its odd, even and differential
    impedances too."""
    if len(sec.widths) == 1:
        c, n = _solve(sec, [1.0], True)
        c_air, _ = _solve(sec, [1.0], False)
        return Line(z0=Z_F0 / np.sqrt(c * c_air), eps_eff=c / c_air, nodes=n)
    out = {}
    for mode, pots in (("odd", [1.0, -1.0]), ("even", [1.0, 1.0])):
        c, n = _solve(sec, pots, True)
        c_air, _ = _solve(sec, pots, False)
        out[mode] = (Z_F0 / np.sqrt(c * c_air), c / c_air)
    z_odd, eps_odd = out["odd"]
    z_even, eps_even = out["even"]
    return Line(
        z0=z_odd,
        eps_eff=eps_odd,
        z_odd=z_odd,
        z_even=z_even,
        z_diff=2 * z_odd,
        eps_odd=eps_odd,
        eps_even=eps_even,
        nodes=n,
    )


def impedance(sec: Section) -> float:
    """The impedance a rule holds: Z0 of a single track, Z_diff = 2 Z_odd of a pair (the odd mode
    alone)."""
    if len(sec.widths) == 1:
        return solve(sec).z0
    c, _ = _solve(sec, [1.0, -1.0], True)
    c_air, _ = _solve(sec, [1.0, -1.0], False)
    return 2 * Z_F0 / float(np.sqrt(c * c_air))


def _search(z_of, start: float, target: float, stop: float, what: str) -> float:
    """The x where z_of(x) is the target, within `stop`: a secant on log z against log x, which is
    near a straight line for a width and for a gap. Each step is held to a factor of 3, and x to
    LIMITS."""
    lo, hi = LIMITS
    x0, z0 = start, z_of(start)
    x1 = x0 * 1.3
    for _ in range(30):
        z1 = z_of(x1)
        if abs(z1 - target) <= stop * target:
            return x1
        slope = (np.log(z1) - np.log(z0)) / (np.log(x1) - np.log(x0))
        if slope == 0:
            break
        step = (np.log(target) - np.log(z1)) / slope
        x2 = float(np.exp(np.log(x1) + min(max(step, -np.log(3)), np.log(3))))
        if not lo <= x2 <= hi:
            raise ValueError(f"no {what} from {lo} to {hi} mm gives {target:.1f} ohm on this stack")
        x0, z0, x1 = x1, z1, x2
    raise ValueError(f"the {what} for {target:.1f} ohm did not settle within {stop:.1%}")


LIMITS = (0.01, 10.0)  # mm: the widths and gaps a search may try


def width_for(sec: Section, target: float, stop: float = 0.002) -> float:
    """The width whose impedance is the target, within `stop` of it. The search starts at the
    stack's height under the strip."""
    return _search(lambda w: impedance(replace_widths(sec, w)), max(sec.y, 0.05), target, stop, "width")


def gap_for(sec: Section, target: float, stop: float = 0.002) -> float:
    """The gap of a pair whose Z_diff is the target at the section's widths."""
    return _search(lambda g: impedance(replace(sec, gap=g)), max(sec.gap, 0.05), target, stop, "gap")


def main(argv: list[str]) -> int:
    print(json.dumps(answer(json.loads(argv[0]))))
    return 0


def answer(req: dict) -> dict:
    """Request: {"section": {...Section...}, "target": ohm, "low": ohm, "high": ohm}. Answer: the width
    for the target and for each end of the band (a pair keeps its gap), the gap range at that width for
    a pair (a bound with no solution is None and named in "gap_error"), and the line at the target
    width. With "impedance_only": true, the answer is {"impedance": ohm} of the section as given."""
    s = req["section"]
    sec = Section(
        [tuple(x) for x in s["slabs"]], s["top_plane"], s["y"], s["t"], s["widths"], s.get("gap", 0.0)
    )
    bad = [f"slab {i + 1} is {h:g} mm thick" for i, (h, _) in enumerate(sec.slabs) if not h > 0]
    bad += [f"slab {i + 1} has an er of {er:g}" for i, (_, er) in enumerate(sec.slabs) if not er > 0]
    bad += [f"the strip is {sec.t:g} mm thick"] if not sec.t > 0 else []
    bad += [f"a strip is {w:g} mm wide" for w in sec.widths if not w > 0]
    bad += [f"the gap is {sec.gap:g} mm" for _ in [1] if len(sec.widths) == 2 and not sec.gap > 0]
    if not sec.slabs or bad:
        # A size of 0 makes the grid's finest step 0, and the grid then has no end.
        return {"error": f"{'; '.join(bad) or 'no slab'}: every size must be above 0"}
    if req.get("impedance_only"):
        return {"impedance": float(impedance(sec))}
    out: dict = {}
    try:
        w = width_for(sec, req["target"])
        out["width"] = w
        out["width_min"] = width_for(sec, req["high"]) if req.get("high") else None
        out["width_max"] = width_for(sec, req["low"]) if req.get("low") else None
        at = replace_widths(sec, w)
        line = solve(at)
        out["line"] = {k: float(v) for k, v in line.__dict__.items() if isinstance(v, (int, float))}
    except ValueError as exc:
        out["error"] = str(exc)
        return out
    if len(sec.widths) == 2:
        # A gap bound with no solution leaves the width band standing: a loose pair may reach no gap
        # for the band's top at the nominal width (its Z_diff stays under twice a lone track's Z0).
        errors = []
        for key, ohm in (("gap_min", req.get("low")), ("gap_max", req.get("high"))):
            out[key] = None
            if ohm:
                try:
                    out[key] = gap_for(at, ohm)
                except ValueError as exc:
                    errors.append(str(exc))
        if errors:
            out["gap_error"] = "; ".join(errors)
    return out


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
