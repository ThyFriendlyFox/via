#!/usr/bin/env python3
"""Signet v0.1 assembly: the 6 tiles round the finger, and the cell on its tile.

The radio tile is the scene's board; the other 5 are bodies from their own routed boards, each
turned about the ring's axis to its place (ring.py: centre_angle). The ring's axis runs along the
radio tile's y, under its middle, R_IN + T below its outer face. The cell, a 3 x 10 x 10 mm pouch,
lies on the cell tile's outer face. The scene, the bodies the boards name, the renders and the GIF
come from the EE Workcenter's `tools/scene.py`; this file holds only the ring's placements.

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

CELL = (10.0, 10.0, 3.0)  # the pouch, across the tile, along the finger, its thickness
CELL_COLOUR = (0.78, 0.79, 0.81)  # aluminium laminate
# The ring's axis under the radio tile's middle, in the scene's frame: x right, y down, z up from the
# radio tile's inner face, where KiCad's 3D frame starts. Every tile's inner face lies R_IN from it.
AXIS = (ring.X0 + ring.WIDTH["radio"] / 2, ring.Y0 + ring.H / 2, -ring.R_IN)
VIEWS = {
    "assembly-iso": {"rotate": "-58,0,-32", "perspective": True, "zoom": 0.4, "pivot": "0,0,-1.0"},  # the thumb's side
    "assembly-iso-back": {"rotate": "-58,0,148", "perspective": True, "zoom": 0.4, "pivot": "0,0,-1.0"},
    "assembly-end": {"rotate": "-90,0,0", "zoom": 0.4, "pivot": "0,0,-1.0"},  # along the finger, from the hand
    "assembly-top": {"rotate": "0,0,0", "zoom": 0.45, "pivot": "0,0,-1.0"},  # the radio's face
    "assembly-palm": {"rotate": "180,0,0", "zoom": 0.45, "pivot": "0,0,-1.0"},  # the cell's face, from the palm
}


def on_ring(phi: float, out: float) -> tuple[float, float, float]:
    """The point `out` mm from the axis at phi degrees round it (0 is the radio tile's middle)."""
    a = math.radians(phi)
    return (AXIS[0] + out * math.sin(a), AXIS[1], AXIS[2] + out * math.cos(a))


def turn(phi: float) -> tuple[float, float, float]:
    """The rotation that lays a body's face along the ring at phi degrees: about y, the way KiCad
    turns a model (M42: opposite to the right-hand rule)."""
    return (0.0, -phi, 0.0)


def main() -> int:
    s = scene.Scene("radio/signet_radio.kicad_pcb", out="build/assembly", name="signet_assembly")
    for name in ring.TILES[1:]:
        phi = ring.centre_angle(name)
        x0, y0 = ring.X0 + ring.WIDTH[name] / 2, ring.Y0 + ring.H / 2
        body = s.board_body(f"{name}/signet_{name}.kicad_pcb", origin=f"{x0}x{y0}mm", name=f"{name}.wrl")
        x, y, z = on_ring(phi, ring.R_IN)  # kicad-cli's VRML puts a board's inner face at its origin
        s.place(body, (x, y, z), rotate=turn(phi))
    cell = w.Mesh(CELL_COLOUR)
    w.box(cell, 0.0, 0.0, 0.0, *CELL)
    phi = ring.centre_angle("cell")
    x, y, z = on_ring(phi, ring.R_IN + ring.T)
    s.place(s.write("cell.wrl", [cell], "301010 LiPo pouch"), (x, y - 0.7, z), rotate=turn(phi))
    s.stills(VIEWS)
    s.spin("assembly-spin.gif", tilt=-62, zoom=0.8, pivot="0,0,-1.0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
