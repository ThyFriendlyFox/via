"""3D bodies for the 3 parts KiCad's 3D library has none for, for the renders and the STEP export.

    python3 models/make_models.py      # from the board's folder; writes the 3 .wrl files here

Each body is sized from its footprint and the maker's drawing, in the footprint's own frame:
origin at the footprint's origin, X right, Y toward the footprint's top, Z out of the board
(tools/wrlgen.py's convention).
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "tools"))

import wrlgen  # noqa: E402
from wrlgen import Mesh, box, cylinder, write_wrl  # noqa: E402

DARK = (0.12, 0.12, 0.13)
GREY = (0.55, 0.56, 0.58)
CREAM = (0.93, 0.91, 0.85)
WHITE = (0.96, 0.96, 0.96)
LENS = (0.85, 0.88, 0.92)


def nr01() -> None:
    """NKK NR01 rotary switch: a 11.6 x 11.2 x 5 mm body over pin 1..5's grid, its shaft, and the
    knob cap the controller's face shows (the cap is drawn for the renders; it is not on the BOM)."""
    body, shaft, cap, mark = Mesh(DARK), Mesh(GREY), Mesh((0.2, 0.2, 0.22)), Mesh(WHITE)
    cx, cy = 5.08, -2.54  # the centre of the pin grid, in the footprint's frame with Y up
    box(body, cx, cy, 0.0, 11.6, 11.2, 5.0)
    cylinder(shaft, cx, cy, 5.0, 1.6, 3.0)
    cylinder(cap, cx, cy, 8.0, 6.0, 5.5, 64)
    box(mark, cx, cy + 3.6, 13.5, 0.8, 3.2, 0.1)
    write_wrl(HERE / "nr01.wrl", [body, shaft, cap, mark], "NKK NR01 rotary switch with a knob cap")


def jst_ph_sm() -> None:
    """JST S2B-PH-SM4-TB: a 2-way PH header lying down, 6.0 wide, 5.8 deep, 4.8 high."""
    body = Mesh(CREAM)
    box(body, 0.0, -0.3, 0.0, 6.0, 5.8, 4.8)
    write_wrl(HERE / "jst_ph_s2b_sm4.wrl", [body], "JST S2B-PH-SM4-TB")


def ws2812_2020() -> None:
    """WS2812B-2020: a 2.0 x 2.0 x 0.84 mm white body with a clear window."""
    body, lens = Mesh(WHITE), Mesh(LENS, transparency=0.2)
    box(body, 0.0, 0.0, 0.0, 2.0, 2.0, 0.7)
    box(lens, 0.0, 0.0, 0.7, 1.6, 1.6, 0.14)
    write_wrl(HERE / "ws2812b_2020.wrl", [body, lens], "WS2812B-2020")


def thumbstick() -> None:
    """ALPS RKJXV122400R or a Hall-effect drop-in, from the catalog's outline: a body 18.2 x 21.7 mm and
    11.2 mm high over the footprint (its pins at y -8.73 and its switch at y +10.1, footprint frame
    with Y down), the lever, and a thumb cap 17 mm across drawn for the renders."""
    body, frame, lever, cap, rim = Mesh(DARK), Mesh(GREY), Mesh(GREY), Mesh((0.16, 0.16, 0.17)), Mesh((0.1, 0.1, 0.1))
    box(body, 0.5, -0.65, 0.0, 18.2, 21.7, 7.5)
    box(frame, 0.5, -0.65, 7.5, 16.0, 16.0, 3.7)
    cylinder(frame, 0.0, 0.0, 11.2, 5.5, 0.8, 48)
    cylinder(lever, 0.0, 0.0, 12.0, 1.9, 7.0, 32)
    cylinder(cap, 0.0, 0.0, 19.0, 8.5, 2.6, 64)
    cylinder(rim, 0.0, 0.0, 21.6, 7.2, 0.6, 64)
    write_wrl(HERE / "thumbstick.wrl", [body, frame, lever, cap, rim], "ALPS RKJXV thumbstick with a cap")


if __name__ == "__main__":
    thumbstick()
    nr01()
    jst_ph_sm()
    ws2812_2020()
    print(f"wrote 4 bodies into {HERE}, with {wrlgen.__name__}")
