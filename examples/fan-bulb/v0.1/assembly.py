#!/usr/bin/env python3
"""Lark v0.1 assembly: the 4 boards in the A19 housing, as the bulb hangs in a fan's light kit.

The light disc is the scene's board; the driver, the brain and the ear are bodies from their own
routed boards, each turned into its plane (bulb.py: the frames). The housing is drawn round them:
the E26 base's shell and eyelet, the neck and the dome, both clear enough to see the boards, and the
mode slider's knob on the neck over the 2 Hall switches. The scene, the bodies, the renders and the
GIF come from the EE Workcenter's `tools/scene.py`; this file holds only the bulb's placements.

    workcenter design driver/design.py --route     # and each other board: the routed boards this reads
    workcenter pictures .                          # runs this with the workcenter's tools/ on PYTHONPATH

Writes build/assembly/: the scene's bodies, lark_assembly.kicad_pcb, the images assembly-iso.png,
assembly-side.png, assembly-room.png (the dome's tip, as the room sees it) and assembly-top.png,
and assembly-spin.gif.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import scene
import wrlgen as w

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bulb  # noqa: E402

H = bulb.H
# The bulb's frame in the scene's: the light disc's top face is the scene's z = 0, and its x and y
# are the bulb's (disc_xy). A body built in the bulb's frame goes at ORIGIN without a turn.
ORIGIN = (bulb.X0, bulb.Y0, -bulb.DISC_TOP)
SHELL = (0.80, 0.80, 0.82)  # the E26 shell, nickel-plated brass
GLASS_BLACK = (0.08, 0.08, 0.08)  # the base's insulator
NECK = (0.94, 0.94, 0.92)  # white polycarbonate
DOME = (0.97, 0.97, 0.97)  # the diffuser
KNOB = (0.20, 0.45, 0.80)
VIEWS = {
    # The bulb hangs base-up: these views put the base at the top of the picture.
    "assembly-iso": {"rotate": "65,0,215", "perspective": True, "zoom": 0.32, "pivot": "0,0,-1.0"},
    "assembly-side": {"rotate": "90,0,0", "zoom": 0.32, "pivot": "0,0,-1.0"},  # the driver's back, the slider at left
    "assembly-room": {"rotate": "180,0,0", "zoom": 0.45},  # the dome's tip, from the room below
    "assembly-top": {"rotate": "0,0,0", "zoom": 0.45},  # down the axis from the base: the disc and its LEDs
}


def lathe(m: w.Mesh, profile: list[tuple[float, float]], n: int = 64) -> None:
    """A surface of revolution about the bulb's axis: profile is (radius, z) from one end to the other."""
    rings = []
    for r, z in profile:
        rings.append([m.vertex(r * math.cos(2 * math.pi * k / n), r * math.sin(2 * math.pi * k / n), z) for k in range(n)])
    for a, b in zip(rings, rings[1:], strict=False):
        for k in range(n):
            j = (k + 1) % n
            m.face(a[k], a[j], b[j], b[k])


def housing() -> list[w.Mesh]:
    """The outside of the housing, as surfaces: shell and eyelet, neck, dome."""
    z0, z1, rb = H.base
    nz0, nr0, nz1, nr1 = H.neck
    shell, eyelet, neck, dome = w.Mesh(SHELL), w.Mesh(GLASS_BLACK), w.Mesh(NECK, 0.7), w.Mesh(DOME, 0.86)
    # The E26 shell: 26.05 mm over its thread (ANSI C81.61), 7 turns, from the insulator to the neck.
    thread = [(12.4 + 0.6 * math.cos(2 * math.pi * k / 8), z0 + 1.5 + (z1 - z0 - 1.5) * k / 56) for k in range(57)]
    lathe(shell, thread)
    lathe(eyelet, [(0.0, 0.0), (3.0, 0.0), (5.5, 1.5), (11.0, 2.5), (12.4, z0 + 1.5)])
    lathe(eyelet, [(0.0, -0.01), (2.8, -0.01)])
    w.cylinder(shell, 0.0, 0.0, -0.6, 2.8, 0.6)  # the eyelet's contact
    lathe(neck, [(nr0 + 2.0, nz0), (nr1 + 2.0, nz1), (nr1 + 2.0, bulb.DISC_TOP)])
    # The dome: a sphere about dome_c, from where it meets the neck to the tip.
    r = H.dome_r + 1.2
    a0 = math.asin(max(-1.0, min(1.0, (bulb.DISC_TOP - H.dome_c) / r)))
    arc = [(r * math.cos(a0 + (math.pi / 2 - a0) * k / 24), H.dome_c + r * math.sin(a0 + (math.pi / 2 - a0) * k / 24)) for k in range(25)]
    lathe(dome, [(nr1 + 2.0, bulb.DISC_TOP), *arc])
    return [shell, eyelet, neck, dome]


def slider() -> list[w.Mesh]:
    """The mode slider's knob in its slot on the neck, at +x over U5 and U6 (driver/design.py)."""
    knob = w.Mesh(KNOB)
    z = 40.5  # between the 2 Hall switches, z 31 and 50: neither, voice only
    nz0, nr0, nz1, nr1 = H.neck
    r = nr0 + (nr1 - nr0) * (z - nz0) / (nz1 - nz0) + 2.0
    w.box(knob, r + 0.6, 0.0, z - 3.0, 1.6, 5.0, 6.0)
    return [knob]


def main() -> int:
    s = scene.Scene("light/lark_light.kicad_pcb", out="build/assembly", name="lark_assembly")
    # The driver stands in the XZ plane, F.Cu toward -y; the brain in the YZ plane, F.Cu toward +x.
    # kicad-cli's VRML puts each board's mid-plane at its origin, here (100, 160) on its sheet, which
    # is the bulb's axis at z = 0: x (or y) = bx - 100, z = 160 - by.
    driver = s.board_body("driver/lark_driver.kicad_pcb", origin="100x160mm", name="driver.wrl")
    s.place(driver, ORIGIN, rotate=(-90.0, 0.0, 0.0))
    brain = s.board_body("brain/lark_brain.kicad_pcb", origin="100x160mm", name="brain.wrl")
    s.place(brain, ORIGIN, rotate=(-90.0, 0.0, -90.0))
    ear = s.board_body("ear/lark_ear.kicad_pcb", origin="100x100mm", name="ear.wrl")
    s.place(ear, (bulb.X0, bulb.Y0, bulb.EAR_Z + bulb.EAR_T / 2 - bulb.DISC_TOP))
    s.place(s.write("housing.wrl", housing(), "A19 housing, E26 base"), ORIGIN)
    s.place(s.write("slider.wrl", slider(), "mode slider knob"), ORIGIN)
    s.stills(VIEWS)
    s.spin("assembly-spin.gif", tilt=-115, zoom=0.26, pivot="0,0,-0.4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
