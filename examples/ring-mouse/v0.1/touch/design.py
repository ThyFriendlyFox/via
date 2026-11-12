"""Signet v0.1, the touch tile: the scroll strip and the light, 4 layers.

The thumb rests here. 6 copper stripes under the solder mask cross the tile, A B C A B C from the
fingertip's end: a thumb that slides along the finger crosses them in turn, and the radio's touch
controller reads the 3 channels through J1. Above the strip, the amber light (D1), driven from the
radio tile's PB11 through its 1k.

J1 joins the radio tile, J2 the clicks tile; the 2 clicks' lines cross this tile from J2 to J1 at
the heights both joints give them.

    workcenter design touch/design.py --route     # from the version's folder

Layers: F.Cu the strip and the light, In1.Cu a ground plane (the strip's shield from what lies
inside the ring), In2.Cu and B.Cu signals.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import ring  # noqa: E402
from ring import at  # noqa: E402

NAME = "touch"


def build():
    d = ring.tile(NAME, uuid.UUID("3e8c5a71-2d4b-4f60-9a1e-7b2c8d4e5f02"), copper_layers=4)
    d.plane_layers = ("In1.Cu",)
    d.power_nets = {"GND": "GND"}
    d.flagged_nets = ["GND"]
    d.net_classes = {
        # The channels keep other nets 0.2 mm away: no track fits between 2 stripes.
        "touch": {"width": 0.15, "clearance": 0.2, "via": 0.45, "via_drill": 0.2, "nets": ["TOUCH_A", "TOUCH_B", "TOUCH_C"]},
    }
    d.add("E1", "Ring:TouchStrip_3ch", "STRIP", "Ring:TouchStrip_3ch_6x", sch_at=(0, 0), pcb_at=at(NAME, 0, 0.62),
          nets={"1": "TOUCH_A", "2": "TOUCH_B", "3": "TOUCH_C"})  # fmt: skip
    # Each stripe's own via near its left end, A, B and C at 3 x positions: the router joins each
    # channel's 2 stripes on the inner layers without its 3 lines crossing.
    strip = next(p for p in d.parts if p.ref == "E1")
    for b in d.pad_boxes():
        if b.ref == "E1":
            d.via(strip.nets[b.number], round(b.x1 + 0.6 + 0.8 * (int(b.number) - 1), 4), round((b.y1 + b.y2) / 2, 4))
    d.add("D1", "Device:LED", "AMBER", "LED_SMD:LED_0402_1005Metric", sch_at=(0, 0), pcb_at=at(NAME, 0, -4.85),
          nets={"1": "GND", "2": "LED_A"})  # fmt: skip
    d.zone("GND", layers=("In1.Cu",), connect="solid")
    d.defined_nets = {
        "BTN_L": "PC13's internal pull-up on the radio tile, through J1",
        "BTN_R": "PC5's internal pull-up on the radio tile, through J1",
    }
    d.check_pulls = True
    ring.finish(d, [("TOUCH", *at(NAME, 0, 0), "B.SilkS", 0.8)])
    return d
