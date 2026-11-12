#!/usr/bin/env python3
"""Signet v0.4 assembly: the 6 tiles round the finger, the solder in their joints, and the cell.

The radio tile is the scene's board; the other 5 are bodies from their own routed boards, each
turned about the ring's axis to where it touches the finger (ring.py: face_angle, TOUCH). The
ring's axis runs along the radio tile's y, under its middle, R_IN below its inner face. Each joint's
8 pads hold a solder fillet across the V the 2 boards open outside their shared inner corner. The cell, a 3 x 10 x 10 mm foil pouch with a Kapton
band, lies on the cell tile's outer face from its fingertip edge, its 2 nickel tabs folded onto the
pads beyond its end. The scene, the bodies the boards name, the renders and the GIF come from the EE
Workcenter's `tools/scene.py`; this file holds only the ring's placements.

    workcenter design radio/design.py --route       # and each other tile: the routed boards this reads
    workcenter pictures .                           # runs this with the workcenter's tools/ on PYTHONPATH

Writes build/assembly/: the scene's bodies, signet_assembly.kicad_pcb, the images assembly-iso.png
(the thumb's side), assembly-iso-back.png, assembly-end.png, assembly-top.png and assembly-palm.png,
and assembly-spin.gif.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import scene
import wrlgen as w

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ring  # noqa: E402

CELL = (10.0, 10.0, 3.0)  # the pouch: across the tile, along the finger, its thickness
CELL_SHIFT = -1.0  # toward the fingertip: its end clears the tab pads at the hand edge
TABS = (-2.7, 2.7)  # the tab pads' x on the cell tile (cell/design.py, TP1 and TP2)
SOLDER = (0.74, 0.74, 0.72)
KAPTON = (0.85, 0.50, 0.10)
NICKEL = (0.70, 0.70, 0.66)
# The ring's axis under the radio tile's middle, in the scene's frame: x right, y down, z up from the
# radio tile's outer face, where `scene.place` measures a body's height from. The radio's inner face
# is T below that, and every tile's inner face lies R_IN from the axis.
AXIS = (ring.X0 + ring.TOUCH["radio"], ring.Y0 + ring.H / 2, -(ring.R_IN + ring.T))
PIVOT = "0,0,-1.08"  # the axis, in cm
VIEWS = {
    "assembly-iso": {"rotate": "-58,0,-32", "perspective": True, "zoom": 0.4, "pivot": PIVOT},  # the thumb's side
    "assembly-iso-back": {"rotate": "-58,0,148", "perspective": True, "zoom": 0.4, "pivot": PIVOT},
    "assembly-end": {"rotate": "-90,0,0", "zoom": 0.4, "pivot": PIVOT},  # along the finger, from the hand
    "assembly-top": {"rotate": "0,0,0", "zoom": 0.45, "pivot": PIVOT},  # the radio's face
    "assembly-palm": {"rotate": "180,0,0", "zoom": 0.45, "pivot": PIVOT},  # the cell's face, from the palm
}


def on_ring(phi: float, out: float) -> tuple[float, float, float]:
    """The point `out` mm from the axis at phi degrees round it (0 is the radio tile's middle)."""
    a = math.radians(phi)
    return (AXIS[0] + out * math.sin(a), AXIS[1], AXIS[2] + out * math.cos(a))


def turn(phi: float) -> tuple[float, float, float]:
    """The rotation that lays a body's face along the ring at phi degrees: about y, the way KiCad
    turns a model (M42: opposite to the right-hand rule)."""
    return (0.0, -phi, 0.0)


def fillets() -> w.Mesh:
    """Every joint's 8 fillets, in a frame whose x is the scene's x, whose y is up from the axis, and
    whose z runs along the finger: each a prism across its pad's 0.8 mm. Seen along the finger a
    fillet runs from 1.3 mm in on one tile's outer face, over its corner, down into the V and up the
    other side, with a meniscus between the 2 pads' far edges."""
    m = w.Mesh(SOLDER)
    r_out = ring.R_IN + ring.T
    for k, name in enumerate(ring.TILES):
        nxt = ring.TILES[(k + 1) % len(ring.TILES)]
        a, b = math.radians(ring.face_angle(name)), math.radians(ring.face_angle(nxt))
        na, nb = (math.sin(a), math.cos(a)), (math.sin(b), math.cos(b))
        ha = ring.WIDTH[name] - ring.TOUCH[name]  # from where each tile touches the finger to the joint
        hb = ring.TOUCH[nxt]

        e1, e2 = ring.on_face(name, r_out, ha), ring.on_face(nxt, r_out, -hb)  # the 2 outer corners
        v = ring.on_face(name, ring.R_IN, ha)  # the inner corner the 2 tiles share
        a1, b2 = ring.on_face(name, r_out, ha - 0.95), ring.on_face(nxt, r_out, -hb + 0.95)  # where the wetting stops
        d = (v[0] + 0.45 * (e1[0] + e2[0] - 2 * v[0]), v[1] + 0.45 * (e1[1] + e2[1] - 2 * v[1]))
        # The bead's surface: a curve from pad to pad that rounds over the gap between the 2 corners,
        # 0.08 mm out from the gap's middle along the joint's outward bisector.
        bis = (na[0] + nb[0], na[1] + nb[1])
        L = math.hypot(*bis)
        c = ((e1[0] + e2[0]) / 2 + 0.08 * bis[0] / L, (e1[1] + e2[1]) / 2 + 0.08 * bis[1] / L)
        bead = [
            ((1 - s) ** 2 * b2[0] + 2 * s * (1 - s) * c[0] + s**2 * a1[0], (1 - s) ** 2 * b2[1] + 2 * s * (1 - s) * c[1] + s**2 * a1[1])
            for s in (k / 10 for k in range(1, 10))
        ]
        outline = [a1, e1, d, e2, b2, *bead]
        for j in range(8):
            off = (j - 3.5) * ring.JOINT_PITCH
            w.prism(m, outline, off - 0.4, off + 0.4)  # a pad is 0.8 mm along the joint
    return m


def cell() -> list:
    """The pouch in its own frame: x across the tile, y toward the fingertip, z out of the tile, the
    origin on the tile's face under the pouch's middle. Foil, a Kapton band, 2 nickel tabs out of its
    hand end and folded down onto the pads."""
    cx, cy, cz = CELL
    foil = w.Mesh(w.FOIL)
    w.prism(foil, w.rounded_rect(cx, cy, 0.8), 0.05, cz)
    band = w.Mesh(KAPTON, transparency=0.15)
    w.prism(band, w.rounded_rect(cx + 0.12, 3.0, 0.3), 0.04, cz + 0.06)
    tabs = w.Mesh(NICKEL)
    for x in TABS:
        w.box(tabs, x, -cy / 2 - 0.08, 0.0, 2.0, 0.15, cz / 2)  # down the pouch's end
        w.box(tabs, x, -cy / 2 - 0.85, 0.0, 2.0, 1.4, 0.1)  # flat on its pad
    return [foil, band, tabs]


def main() -> int:
    s = scene.Scene("radio/signet_radio.kicad_pcb", out="build/assembly", name="signet_assembly")
    for name in ring.TILES[1:]:
        phi = ring.face_angle(name)
        x0, y0 = ring.X0 + ring.TOUCH[name], ring.Y0 + ring.H / 2  # where the tile touches the finger
        body = s.board_body(f"{name}/signet_{name}.kicad_pcb", origin=f"{x0}x{y0}mm", name=f"{name}.wrl")
        x, y, z = on_ring(phi, ring.R_IN + ring.T / 2)  # a board body's origin is its mid-plane
        s.place(body, (x, y, z), rotate=turn(phi))
    # The fillets' frame: its y up from the axis to the scene's z, its z along the finger.
    s.place(s.write("fillets.wrl", [fillets()], "solder in the 6 joints"), AXIS, rotate=(-90.0, 0.0, 0.0))
    phi = ring.face_angle("cell")
    x, y, z = on_ring(phi, ring.R_IN + ring.T)
    s.place(s.write("cell.wrl", cell(), "301010 LiPo pouch"), (x, y + CELL_SHIFT, z), rotate=turn(phi))
    s.stills(VIEWS)
    s.spin("assembly-spin.gif", tilt=-62, zoom=0.8, pivot=PIVOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
