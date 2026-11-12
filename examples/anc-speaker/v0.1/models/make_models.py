"""3D bodies for the 4 parts KiCad's 3D library has none for, for the renders and the STEP export.

    python3 models/make_models.py      # from the board's folder; writes the 4 .wrl files here

Each body is sized from its footprint's fab outline and the maker's drawing, in the footprint's own
frame: origin at the footprint's origin, X right, Y toward the footprint's top, Z out of the board
(tools/wrlgen.py's convention).
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "tools"))

import wrlgen  # noqa: E402
from wrlgen import Mesh, box, circle, cylinder, write_wrl  # noqa: E402

LID = (0.60, 0.61, 0.64)  # a steel lid; a brighter grey renders white under KiCad's lights
SUBSTRATE = (0.20, 0.42, 0.28)
DARK = (0.10, 0.10, 0.11)
NICKEL = (0.72, 0.72, 0.70)
CERMET = (0.12, 0.12, 0.13)
ROTOR = (0.93, 0.93, 0.91)
RED = (0.78, 0.10, 0.10)
SOLDER = (0.75, 0.75, 0.78)
COPPER = (0.80, 0.50, 0.30)


def tube_x(m: Mesh, r_out: float, r_in: float, x0: float, x1: float, zc: float, n: int = 48) -> None:
    """A tube along x from x0 to x1, its axis at height zc: a collar a plug enters."""
    outer, inner = circle(r_out, n), circle(r_in, n)
    for i in range(n):
        j = (i + 1) % n
        for ring, flip in ((outer, False), (inner, True)):
            (ya, za), (yb, zb) = ring[i], ring[j]
            quad = [m.vertex(x0, ya, zc + za), m.vertex(x0, yb, zc + zb), m.vertex(x1, yb, zc + zb),
                    m.vertex(x1, ya, zc + za)]  # fmt: skip
            m.face(*(reversed(quad) if flip else quad))
        for x, flip in ((x0, True), (x1, False)):
            quad = [m.vertex(x, outer[i][0], zc + outer[i][1]), m.vertex(x, outer[j][0], zc + outer[j][1]),
                    m.vertex(x, inner[j][0], zc + inner[j][1]), m.vertex(x, inner[i][0], zc + inner[i][1])]  # fmt: skip
            m.face(*(reversed(quad) if flip else quad))


def mic() -> None:
    """Infineon IM73A135V01: a 4.0 x 3.0 x 1.2 mm LGA, a laminate base under a metal lid (datasheet,
    package drawing). The sound port is in the base, over the board's hole."""
    base, lid = Mesh(SUBSTRATE), Mesh(LID)
    box(base, 0.0, 0.0, 0.0, 4.0, 3.0, 0.3)
    box(lid, 0.0, 0.0, 0.3, 3.9, 2.9, 0.9)
    write_wrl(HERE / "im73a135.wrl", [base, lid], "Infineon IM73A135V01, 4 x 3 x 1.2 mm")


def jack() -> None:
    """PJ-320D 3.5 mm jack: the body from the footprint's fab outline, x -6.225 to 5.575 and 5.8 wide,
    5.0 tall; the collar the plug enters, x -8.225 to -6.225, 5.0 across with a 3.6 mm bore."""
    body, collar = Mesh(DARK), Mesh(NICKEL)
    box(body, -0.325, 0.0, 0.0, 11.8, 5.8, 5.0)
    tube_x(collar, 2.5, 1.8, -8.225, -6.225, 2.5)
    write_wrl(HERE / "jack_pj320d.wrl", [body, collar], "PJ-320D 3.5 mm audio jack, 5 mm tall")


def trimmer() -> None:
    """Bourns TC33X: a 3.8 x 3.6 mm cermet base 0.9 mm tall, and the white rotor 3.0 mm across with
    its cross slot, 1.7 mm overall (Bourns TC33 drawing)."""
    base, rotor, slot = Mesh(CERMET), Mesh(ROTOR), Mesh(DARK)
    box(base, -0.1, 0.0, 0.0, 3.8, 3.6, 0.9)
    cylinder(rotor, -0.1, 0.0, 0.9, 1.5, 0.8, 48)
    box(slot, -0.1, 0.0, 1.7, 2.4, 0.45, 0.06)
    box(slot, -0.1, 0.0, 1.7, 0.45, 2.4, 0.06)
    write_wrl(HERE / "trimmer_tc33x.wrl", [base, rotor, slot], "Bourns TC33X trimmer, 3.8 x 3.6 x 1.7 mm")


def speaker_wires() -> None:
    """The speaker's two wires soldered in J3's pads (pad 1 at the origin, pad 2 4.2 mm along x): a
    solder fillet on each and the cut end of the wire above it, red for SPK+ and black for SPK-."""
    solder, red, black, cu = Mesh(SOLDER), Mesh(RED), Mesh(DARK), Mesh(COPPER)
    for x, sleeve in ((0.0, red), (4.2, black)):
        cylinder(solder, x, 0.0, 0.0, 0.85, 0.3, 32)
        cylinder(sleeve, x, 0.0, 0.3, 0.6, 1.6, 32)
        cylinder(cu, x, 0.0, 1.9, 0.33, 0.25, 24)
    write_wrl(HERE / "speaker_wires.wrl", [solder, red, black, cu], "the speaker's wires in J3")


if __name__ == "__main__":
    mic()
    jack()
    trimmer()
    speaker_wires()
    print(f"wrote 4 bodies into {HERE}, with {wrlgen.__name__}")
