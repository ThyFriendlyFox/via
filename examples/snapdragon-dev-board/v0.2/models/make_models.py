"""3D bodies for the parts KiCad's 3D library has none for.

    python3 models/make_models.py      # from the board's folder; writes the .wrl files here

Each body is in its footprint's own frame (tools/wrlgen.py's convention): origin at the footprint's
origin, X right, Y toward the top of the footprint, Z out of the board.

- rp2350_qfn60.wrl, tps552892_ryq21.wrl, hd3ss3220_rnh30.wrl: 3 leadless packages (KiCad's QFN-60
  7x7 and RNH0030A footprints name bodies its 3D library does not ship; the RYQ0021A footprint is
  this board's own), by wrlgen's `leadless` preset. The TPS552892's 5 x 3 x 1.0 mm body and the
  HD3SS3220's 2.5 x 4.5 x 0.75 mm are their datasheets' (RYQ0021A, RNH0030A outlines).
- microsd_104031.wrl: Molex's push-pull socket, a steel shell on the footprint's outline (11.95 x
  11.4 mm, F.Fab), 1.42 mm tall (its datasheet title), the card's slot dark at the contact end.
- vosm6490.wrl: the module, 45 x 45 mm. Vantron publishes no drawing of its top, so the body is a
  stand-in of the shape OSM modules take: a 1.2 mm green board (iWave's OSM, 1.2 mm) under a dark
  metal shield that covers it to 0.6 mm from each edge, 2.5 mm high in all (`osm_l.HEIGHT`), a
  white label with a code square, and a gold triangle at pad A1's corner.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "tools"))
sys.path.insert(0, str(HERE.parent))

import wrlgen  # noqa: E402
from wrlgen import Mesh, box, prism, write_wrl  # noqa: E402

import osm_l  # noqa: E402

GOLD = (0.86, 0.70, 0.30)
STEEL = (0.60, 0.61, 0.64)  # under the renderer's light a lighter grey reads as white
SHIELD = (0.30, 0.31, 0.33)
DARK = (0.10, 0.10, 0.11)
SOM_GREEN = (0.10, 0.36, 0.20)
LABEL = (0.92, 0.92, 0.90)


def leadless() -> None:
    write_wrl(HERE / "rp2350_qfn60.wrl", wrlgen.leadless((7.0, 7.0, 0.85), (15, 15), 0.4, (0.4, 0.2)), "RP2350A QFN-60")
    write_wrl(HERE / "tps552892_ryq21.wrl", wrlgen.leadless((5.0, 3.0, 1.0), (9, 4), 0.5, (0.35, 0.25)),
              "TPS552892 RYQ0021A")
    write_wrl(HERE / "hd3ss3220_rnh30.wrl", wrlgen.leadless((2.5, 4.5, 0.75), (5, 10), 0.4, (0.4, 0.2)),
              "HD3SS3220 RNH0030A")


def microsd() -> None:
    """Molex 104031-0811: a steel shell, the slot at the contact end (the footprint's -y, Y up here)."""
    shell, slot = Mesh(STEEL), Mesh(DARK)
    box(shell, 0.02, 0.0, 0.0, 11.95, 11.4, 1.42)
    box(slot, 0.02, 5.7, 0.35, 11.0, 0.02, 0.75)
    write_wrl(HERE / "microsd_104031.wrl", [shell, slot], "Molex 104031-0811")


def module() -> None:
    s = osm_l.SIZE
    board_t = 1.2
    board, shield, label, code, mark = (Mesh(c) for c in (SOM_GREEN, SHIELD, LABEL, DARK, GOLD))
    box(board, 0.0, 0.0, 0.0, s, s, board_t)
    box(shield, 0.0, 0.0, board_t, s - 1.2, s - 1.2, osm_l.HEIGHT - board_t)
    # A white label with a code square on it, as modules carry their serial number.
    box(label, 0.0, -s / 4, osm_l.HEIGHT, 24.0, 8.0, 0.02)
    box(code, 8.5, -s / 4, osm_l.HEIGHT + 0.02, 5.0, 5.0, 0.01)
    # Pad A1's corner is the footprint's top left: x -s/2, y +s/2 in this Y-up frame.
    c = s / 2 - 0.15
    prism(mark, [(-c, c), (-c + 2.4, c), (-c, c - 2.4)], board_t, board_t + 0.02)
    write_wrl(HERE / "vosm6490.wrl", [board, shield, label, code, mark], "Vantron VOSM6490 (OSM Size-L), stand-in")


if __name__ == "__main__":
    leadless()
    microsd()
    module()
    print(f"wrote 5 bodies into {HERE}")
