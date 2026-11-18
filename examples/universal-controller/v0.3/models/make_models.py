"""3D bodies for the parts KiCad's 3D library has none for, for the renders and the STEP export.

    python3 models/make_models.py      # from the board's folder; writes the .wrl files here

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
    """JST S3B-PH-SM4-TB: a 3-way PH header lying down, 9.9 wide, 6.0 deep, 4.8 high, its mouth
    toward pins 1-3 (the footprint's fab outline)."""
    body, mouth = Mesh(CREAM), Mesh((0.75, 0.73, 0.68))
    box(body, 0.0, -1.4, 0.0, 9.9, 6.0, 4.8)
    box(mouth, 0.0, 1.55, 0.6, 7.6, 0.1, 3.4)
    write_wrl(HERE / "jst_ph_s3b_sm4.wrl", [body, mouth], "JST S3B-PH-SM4-TB")


def oled() -> None:
    """ER-OLEDM0.91-1: a 0.91 in 128 x 32 OLED module, its board 12 x 38 mm on a 4-pin header 2.5 mm
    tall, the glass and its black active area on top (the footprint's fab outline; pins at y 0)."""
    header, board, glass, area = Mesh(DARK), Mesh((0.1, 0.25, 0.45)), Mesh((0.3, 0.32, 0.34)), Mesh((0.03, 0.03, 0.04))
    box(header, 3.81, 0.0, 0.0, 10.2, 2.5, 2.5)
    box(board, 3.81, -17.5, 2.5, 12.0, 38.0, 1.0)
    box(glass, 3.81, -19.5, 3.5, 11.5, 30.0, 1.0)
    box(area, 3.81, -20.0, 4.5, 8.0, 23.0, 0.05)
    write_wrl(HERE / "oled_091.wrl", [header, board, glass, area], "ER-OLEDM0.91-1 OLED module")


def lps4018() -> None:
    """Coilcraft LPS4018: a 3.9 x 3.9 x 1.7 mm shielded inductor."""
    body = Mesh(DARK)
    box(body, 0.0, 0.0, 0.0, 3.9, 3.9, 1.7)
    write_wrl(HERE / "lps4018.wrl", [body], "Coilcraft LPS4018")


def son10() -> None:
    """TI DRC0010J: a 3 x 3 x 0.9 mm SON-10, its pin-1 dot."""
    body, dot = Mesh(DARK), Mesh(GREY)
    box(body, 0.0, 0.0, 0.0, 3.0, 3.0, 0.9)
    cylinder(dot, -0.9, 0.9, 0.9, 0.2, 0.02, 16)
    write_wrl(HERE / "son10_drc.wrl", [body, dot], "TI DRC0010J SON-10")


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
    oled()
    lps4018()
    son10()
    print(f"wrote 7 bodies into {HERE}, with {wrlgen.__name__}")
