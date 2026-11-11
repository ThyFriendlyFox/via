"""3D bodies for the parts KiCad's 3D library has none for, and the Snapdragon module for the assembly.

    python3 models/make_models.py      # from the board's folder; writes the .wrl files here

Each body is in its footprint's own frame (tools/wrlgen.py's convention): origin at the footprint's
origin, X right, Y toward the top of the footprint, Z out of the board.

- rp2350_qfn60.wrl, tps62130_vqfn16.wrl: the 2 leadless packages (KiCad's QFN-60 7x7 and VQFN-16
  3x3 footprints name bodies its 3D library does not ship), by wrlgen's `leadless` preset.
- df40hc_100ds.wrl: the SOM's receptacle, a beige housing on the footprint's outline (22.6 x 2.88 mm,
  F.Fab) with its 2 rows of gold tails; 2.4 mm tall, a stand-in: the stack is 3.0 mm with the SOM's
  1.14 mm header in it.
- microsd_104031.wrl: Molex's push-pull socket, a steel shell on the footprint's outline (11.95 x
  11.4 mm, F.Fab), 1.42 mm tall (its datasheet title), the card's slot dark at the contact end.
- open_q_845.wrl: the Lantronix Open-Q 845 uSOM, for the assembly scene only: its 50 x 25 x 1.06 mm
  board, the Wi-Fi shield, the Snapdragon 845 with its memory on top, the UFS flash, the 2 U.FL
  antenna sockets and their 3 headers underneath, placed from its datasheet's Figure 6 (top view)
  and Figure 7 (the headers). Its origin is the module's centre on its underside, X along its 50 mm,
  Y toward the edge Figure 6 draws on top.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "tools"))
sys.path.insert(0, str(HERE.parent))

import wrlgen  # noqa: E402
from wrlgen import Mesh, box, cylinder, write_wrl  # noqa: E402

import open_q_845 as som  # noqa: E402

GOLD = (0.86, 0.70, 0.30)
BEIGE = (0.86, 0.80, 0.66)
STEEL = (0.74, 0.75, 0.77)
DARK = (0.10, 0.10, 0.11)
SOM_GREEN = (0.10, 0.36, 0.20)
SHIELD = (0.80, 0.81, 0.83)
SOC = (0.14, 0.14, 0.16)
LABEL = (0.95, 0.95, 0.93)


def leadless() -> None:
    write_wrl(HERE / "rp2350_qfn60.wrl", wrlgen.leadless((7.0, 7.0, 0.85), (15, 15), 0.4, (0.4, 0.2)), "RP2350A QFN-60")
    write_wrl(HERE / "tps62130_vqfn16.wrl", wrlgen.leadless((3.0, 3.0, 0.9), (4, 4), 0.5, (0.4, 0.25)), "TPS62130 VQFN-16")


def df40() -> None:
    """Hirose DF40HC(3.0)-100DS-0.4V: housing, the mating slot on top, 50 tails a side."""
    housing, slot, tails = Mesh(BEIGE), Mesh((0.55, 0.50, 0.42)), Mesh(GOLD)
    box(housing, 0.0, 0.0, 0.0, 22.6, 2.88, 2.4)
    box(slot, 0.0, 0.0, 2.4, 20.4, 1.1, 0.01)
    for k in range(50):
        x = -9.8 + 0.4 * k
        for y in (1.54, -1.54):
            box(tails, x, y, 0.0, 0.2, 0.6, 0.15)
    write_wrl(HERE / "df40hc_100ds.wrl", [housing, slot, tails], "Hirose DF40HC(3.0)-100DS-0.4V")


def microsd() -> None:
    """Molex 104031-0811: a steel shell, the slot at the contact end (the footprint's -y, Y up here)."""
    shell, slot = Mesh(STEEL), Mesh(DARK)
    box(shell, 0.02, 0.0, 0.0, 11.95, 11.4, 1.42)
    box(slot, 0.02, 5.7, 0.35, 11.0, 0.02, 0.75)
    write_wrl(HERE / "microsd_104031.wrl", [shell, slot], "Molex 104031-0811")


def open_q() -> None:
    """The module from its datasheet: Figure 6 places each body on its top face, seen from above with
    the U.FL sockets top left; (fx, fy) there are mm from the top left corner, y down."""
    w, h = som.SIZE
    t = som.PCB_THICKNESS

    def at(fx: float, fy: float) -> tuple[float, float]:  # Figure 6's top-left frame to the body's centre frame
        return (fx - w / 2, h / 2 - fy)

    board, shield, soc, flash, ufl, gold, label = (Mesh(c) for c in (SOM_GREEN, SHIELD, SOC, SOC, GOLD, GOLD, LABEL))
    box(board, 0.0, 0.0, 0.0, w, h, t)
    # The Wi-Fi shield, 1.32 mm, the tallest part on top (section 6.2), at 0.6 to 11.7 by 4.8 to 23.2.
    cx, cy = at(6.15, 14.0)
    box(shield, cx, cy, t, 11.1, 18.4, som.TOP_HEIGHT)
    # The SDA845 with its LPDDR4X on top (package on package), 18.0 to 30.6 by 6.2 to 18.6.
    cx, cy = at(24.3, 12.4)
    box(soc, cx, cy, t, 12.6, 12.4, 0.75)
    box(soc, cx, cy, t + 0.75, 12.0, 11.8, 0.25)
    # The UFS flash, 37.4 to 49.0 by 10.9 to 24.2.
    cx, cy = at(43.2, 17.55)
    box(flash, cx, cy, t, 11.6, 13.3, 1.0)
    # The label on the shield (section 7.1: a white label on the top).
    cx, cy = at(6.15, 14.0)
    box(label, cx, cy, t + som.TOP_HEIGHT, 9.0, 12.0, 0.02)
    # The 2 U.FL sockets, at (3.0, 1.8) and (9.0, 1.8).
    for fx in (3.0, 9.0):
        cx, cy = at(fx, 1.8)
        box(ufl, cx, cy, t, 2.6, 2.6, 0.3)
        cylinder(ufl, cx, cy, t + 0.3, 0.95, 0.95, 32)
    # A pad ring at each corner Figure 4 photographs.
    for fx, fy in ((1.1, 1.5), (48.9, 1.5), (1.1, 23.5), (48.9, 23.5)):
        cx, cy = at(fx, fy)
        cylinder(gold, cx, cy, t, 0.7, 0.02, 24)
    # The 3 headers underneath (Figure 7, seen through the top, y up from the lower left).
    headers = Mesh(DARK)
    for jt, (sx, sy) in som.CENTRES.items():
        box(headers, sx - w / 2, sy - h / 2, -som.BOTTOM_HEIGHT, 22.6, 2.6, som.BOTTOM_HEIGHT)
    write_wrl(HERE / "open_q_845.wrl", [board, shield, soc, flash, ufl, gold, label, headers], "Lantronix Open-Q 845 uSOM")


if __name__ == "__main__":
    leadless()
    df40()
    microsd()
    open_q()
    print(f"wrote 5 bodies into {HERE}")
