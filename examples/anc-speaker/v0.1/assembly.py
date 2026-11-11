#!/usr/bin/env python3
"""Hush v0.1 assembly: the routed ring on the face of its speaker driver.

The Dayton Audio CE40-4 (library/dayton/CE40-4.pdf) sits under the board, its frame's flange against
the back face from the opening to 20 mm out; the cone shows through the three windows, and the mic's
port, on the hub, looks down at the dust cap. The speaker's two wires run from J3 down past the frame
to the driver's tabs. None of this changes the copper. The scene, the bodies the board names, the
renders and the GIF come from the EE Workcenter's `tools/scene.py`; this file holds only Hush's driver
and its placement.

    workcenter design design.py --route     # the routed board this reads
    workcenter pictures .                   # runs this with the workcenter's tools/ on PYTHONPATH

Writes build/assembly/: the scene's bodies, hush_assembly.kicad_pcb, the images
assembly-{iso,front,side,back}.png and assembly-spin.gif, the assembly turning round once.
"""

from __future__ import annotations

import math

import scene
import wrlgen as w

# The CE40-4's sizes (mm) from its specification sheet's drawing: a 40.0 frame, a 36.5 baffle cutout,
# a 23.0 magnet, 23.3 deep from the flange's face; the radiating area 7.07 cm2 (a 15 mm piston radius).
FRAME_R, OPENING_R, MAGNET_R, DEPTH = 20.0, 16.5, 11.5, 23.3
FLANGE_T = 0.8
SURROUND_R0, SURROUND_R1 = 14.6, 16.4
COIL_R = 8.0  # the 16 mm voice coil, where the cone meets the dust cap
CONE_DEPTH = 5.0
BOARD_T = 1.6
CENTRE = (130.0, 130.0)

BLACK = (0.06, 0.06, 0.07)
CONE = (0.13, 0.13, 0.14)
RUBBER = (0.18, 0.18, 0.19)
STEEL = (0.62, 0.63, 0.66)
RED = (0.78, 0.10, 0.10)

# The board's own colours (black mask, white silk, gold finish) in every view.
LOOK = {"stackup_colors": True, "pivot": "0,0,-1.0"}
VIEWS = {
    "assembly-iso": {**LOOK, "rotate": "-55,0,30", "perspective": True, "zoom": 0.85},
    "assembly-front": {**LOOK, "rotate": "0,0,0", "zoom": 1.0},
    "assembly-side": {**LOOK, "rotate": "-90,0,0", "zoom": 0.9},
    "assembly-back": {**LOOK, "rotate": "-125,0,30", "perspective": True, "zoom": 0.85},
}


def frustum(m: w.Mesh, r0: float, z0: float, r1: float, z1: float, n: int = 96) -> None:
    """The side of a cone's frustum from radius r0 at z0 to r1 at z1, both faces drawn."""
    a = [(r0 * math.cos(2 * math.pi * i / n), r0 * math.sin(2 * math.pi * i / n)) for i in range(n)]
    b = [(r1 * math.cos(2 * math.pi * i / n), r1 * math.sin(2 * math.pi * i / n)) for i in range(n)]
    for i in range(n):
        j = (i + 1) % n
        quad = [m.vertex(*a[i], z0), m.vertex(*a[j], z0), m.vertex(*b[j], z1), m.vertex(*b[i], z1)]
        m.face(*quad)
        m.face(*reversed(quad))


def dome(m: w.Mesh, r: float, z0: float, h: float, rings: int = 10, n: int = 64) -> None:
    """A shallow spherical cap of radius r on its rim at z0, rising h at its centre."""
    R = (r * r + h * h) / (2 * h)
    for k in range(rings):
        ra, rb = r * k / rings, r * (k + 1) / rings
        za = z0 + h - (R - math.sqrt(R * R - ra * ra))
        zb = z0 + h - (R - math.sqrt(R * R - rb * rb))
        frustum(m, ra, za, rb, zb, n)


def rod(m: w.Mesh, p0: tuple, p1: tuple, r: float, n: int = 16) -> None:
    """A round wire from p0 to p1 (x, y, z in the body's frame)."""
    d = [p1[i] - p0[i] for i in range(3)]
    length = math.sqrt(sum(c * c for c in d))
    u = [c / length for c in d]
    a = [0.0, 0.0, 1.0] if abs(u[2]) < 0.9 else [1.0, 0.0, 0.0]
    v1 = [u[1] * a[2] - u[2] * a[1], u[2] * a[0] - u[0] * a[2], u[0] * a[1] - u[1] * a[0]]
    k = math.sqrt(sum(c * c for c in v1))
    v1 = [c / k for c in v1]
    v2 = [u[1] * v1[2] - u[2] * v1[1], u[2] * v1[0] - u[0] * v1[2], u[0] * v1[1] - u[1] * v1[0]]
    ring0, ring1 = [], []
    for i in range(n):
        t = 2 * math.pi * i / n
        off = [r * (math.cos(t) * v1[j] + math.sin(t) * v2[j]) for j in range(3)]
        ring0.append(m.vertex(*(p0[j] + off[j] for j in range(3))))
        ring1.append(m.vertex(*(p1[j] + off[j] for j in range(3))))
    for i in range(n):
        j = (i + 1) % n
        m.face(ring0[i], ring0[j], ring1[j], ring1[i])


def driver() -> list:
    """The CE40-4 in its own frame: origin on its axis at the flange's face, z up toward the board."""
    frame, cone, surround, steel = w.Mesh(BLACK), w.Mesh(CONE), w.Mesh(RUBBER), w.Mesh(STEEL)
    w.tube(frame, w.circle(FRAME_R, 96), w.circle(OPENING_R, 96), -FLANGE_T, 0.0)
    # the surround: a rubber roll between the cone's rim and the frame
    frustum(surround, SURROUND_R0, -1.4, (SURROUND_R0 + SURROUND_R1) / 2, -0.6)
    frustum(surround, (SURROUND_R0 + SURROUND_R1) / 2, -0.6, SURROUND_R1, -1.4)
    w.tube(surround, w.circle(OPENING_R + 0.05, 96), w.circle(SURROUND_R1, 96), -1.5, -1.4)
    # the cone down to the voice coil, and the dust cap over the coil
    frustum(cone, SURROUND_R0, -1.4, COIL_R, -1.4 - CONE_DEPTH)
    dome(cone, COIL_R + 0.2, -1.4 - CONE_DEPTH, 2.6)
    # the basket and the magnet behind it
    frustum(steel, FRAME_R - 0.4, -FLANGE_T, MAGNET_R + 1.0, -11.0)
    w.cylinder(steel, 0.0, 0.0, -DEPTH, MAGNET_R, DEPTH - 11.0, 96)
    return [frame, cone, surround, steel]


def wires(tabs: list[tuple[float, float]], pads: list[tuple[float, float]]) -> list:
    """The speaker's wires: from each of J3's pads straight down past the frame, then in to its tab on
    the basket, red to +, black to -. In the board's frame relative to CENTRE, y up (KiCad's models)."""
    red, black = w.Mesh(RED), w.Mesh(BLACK)
    for (px, py), (tx, ty), m in zip(pads, tabs, (red, black), strict=True):
        p_top = (px, py, -BOARD_T)
        p_low = (px, py, -BOARD_T - 6.0)
        tab = (tx, ty, -BOARD_T - 8.0)
        rod(m, p_top, p_low, 0.55)
        rod(m, p_low, tab, 0.55)
    return [red, black]


def main() -> int:
    s = scene.Scene("hush.kicad_pcb", out="build/assembly", name="hush_assembly")
    s.place(s.write("ce40_4.wrl", driver(), "Dayton Audio CE40-4, 40 mm frame"), (*CENTRE, -BOARD_T))
    # J3's pads, and the tabs on the basket beneath them, relative to the centre with y up
    pads = []
    fp = s.board.FindFootprintByReference("J3")
    for pad in fp.Pads():
        p = pad.GetPosition()
        pads.append((scene.pcbnew.ToMM(p.x) - CENTRE[0], -(scene.pcbnew.ToMM(p.y) - CENTRE[1])))
    tabs = []
    for x, y in pads:
        r = math.hypot(x, y)
        tabs.append((x * (FRAME_R - 1.5) / r, y * (FRAME_R - 1.5) / r))
    s.place(s.write("speaker_wires.wrl", wires(tabs, pads), "the speaker's wires"), (*CENTRE, 0.0))
    s.stills(VIEWS)
    s.spin("assembly-spin.gif", tilt=-60, zoom=0.95, pivot="0,0,-1.0", stackup_colors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
