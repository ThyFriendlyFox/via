"""Signet v0.5, the cell tile: where the cell lies and where the ring charges, 4 layers, 6.83 mm.

The cell is a 3.0 x 10 x 10 mm LiPo pouch (301010 size, about 20 mAh) with its own protection board,
lying on this tile's outer face from its fingertip edge. The tile is 6.83 mm wide since v0.5, so the
pouch reaches 1.6 mm past each edge, over the 2 joints, where the neighbours turn away beneath it.
Its 2 tabs, trimmed to 1 mm, fold onto TP1 (BAT+) and TP2 (BAT-), 1.0 x 1.4 mm pads 0.9 mm apart
(`Ring:CellTab_1x1.4mm`), beyond its end at the tile's hand edge. The inner face carries 2 flat pads, TP3 (VCHG) and TP4 (GND), 1.0 mm round
(2.0 until v0.5): the ring slides onto a charging post whose 2 spring pins meet them. The static guard on VCHG, D1, stands on the charge tile, the
first part the post's 5 V reaches through J1 (since v0.5: no room for it between the tab pads).

J1 joins the charge tile: the cell's and the post's lines, and the charger's STAT on its way to the
radio. J2 joins the rail tile: the cell to the regulator, and STAT again.

    workcenter design cell/design.py --route     # from the version's folder
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import ring  # noqa: E402
from ring import at  # noqa: E402

NAME = "cell"


def build():
    d = ring.tile(NAME, uuid.UUID("7a2f9c15-6b8d-4e93-a4d5-0e1f7b8c9d04"))
    d.power_nets = {"GND": "GND", "VBAT": "+BATT", "VCHG": "VBUS"}
    d.flagged_nets = ["GND", "VBAT", "VCHG"]  # the cell's tabs and the charging post's pins: no pin drives them
    for ref, value, net, pos, fp, layer in (
        ("TP1", "BAT+", "VBAT", at(NAME, -0.95, 4.9), "Ring:CellTab_1x1.4mm", "F.Cu"),
        ("TP2", "BAT-", "GND", at(NAME, 0.95, 4.9), "Ring:CellTab_1x1.4mm", "F.Cu"),
        ("TP3", "VCHG", "VCHG", at(NAME, -1.1, 0), "TestPoint:TestPoint_Pad_D1.0mm", "B.Cu"),
        ("TP4", "GND", "GND", at(NAME, 1.1, 0), "TestPoint:TestPoint_Pad_D1.0mm", "B.Cu"),
    ):
        d.add(ref, "Connector:TestPoint", value, fp, sch_at=(0, 0), pcb_at=pos, pcb_layer=layer, nets={"1": net})
    d.defined_nets = {"CHG_STAT": "PC1's internal pull-up on the radio tile; it crosses this tile from J1 to J2"}
    ring.finish(d, [("+", *at(NAME, -0.95, 3.4), "F.SilkS", 0.8), ("-", *at(NAME, 0.95, 3.4), "F.SilkS", 0.8),
                    ("5V", *at(NAME, -1.1, -1.5), "B.SilkS", 0.6), ("GND", *at(NAME, 1.1, -1.5), "B.SilkS", 0.6),
                    ("CELL", *at(NAME, 0, -4.2), "B.SilkS", 0.6)])  # fmt: skip
    return d
