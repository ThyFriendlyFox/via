"""Signet v0.2, the cell tile: where the cell lies and where the ring charges, 4 layers.

The cell is a 3.0 x 10 x 10 mm LiPo pouch (301010 size, about 20 mAh) with its own protection board,
lying on this tile's outer face from its fingertip edge; its 2 tabs fold onto TP1 (BAT+) and TP2
(BAT-), beyond its end at the tile's hand edge. The inner face carries 2 flat pads, TP3 (VCHG) and TP4
(GND): the ring slides onto a charging post whose 2 spring pins meet them. Both pass to the power
tile through J2.

J1 joins the clicks tile with 8 ground pads.

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
        ("TP1", "BAT+", "VBAT", at(NAME, -2.2, 4.9), "TestPoint:TestPoint_Pad_1.5x1.5mm", "F.Cu"),
        ("TP2", "BAT-", "GND", at(NAME, 2.2, 4.9), "TestPoint:TestPoint_Pad_1.5x1.5mm", "F.Cu"),
        ("TP3", "VCHG", "VCHG", at(NAME, -2.2, 0), "TestPoint:TestPoint_Pad_D2.0mm", "B.Cu"),
        ("TP4", "GND", "GND", at(NAME, 2.2, 0), "TestPoint:TestPoint_Pad_D2.0mm", "B.Cu"),
    ):
        d.add(ref, "Connector:TestPoint", value, fp, sch_at=(0, 0), pcb_at=pos, pcb_layer=layer, nets={"1": net})
    ring.finish(d, [("+", *at(NAME, -0.7, 4.9), "F.SilkS", 0.8), ("-", *at(NAME, 0.7, 4.9), "F.SilkS", 0.8),
                    ("5V", *at(NAME, -2.2, -1.9), "B.SilkS", 0.6), ("GND", *at(NAME, 2.2, -1.9), "B.SilkS", 0.6),
                    ("CELL", *at(NAME, 0, -4.2), "B.SilkS", 0.8)])  # fmt: skip
    return d
