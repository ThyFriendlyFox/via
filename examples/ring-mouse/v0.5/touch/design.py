"""Signet v0.5, the touch tile: the scroll strip, 4 layers, 10.02 mm.

The thumb rests here. 6 copper stripes under the solder mask cross the tile, A B C A B C from the
fingertip's end: a thumb that slides along the finger crosses them in turn, and the radio's touch
controller reads the 3 channels through J1. Each channel's 10k series resistor (R1 to R3) stands
below the strip, by the channels' 3 pads on J1 (on the radio tile until v0.5, which left it no
room); the strip stands 0.45 mm toward the fingertip to leave room for their vias. The stripes are 6.4 mm long since v0.5 (7.4 before), the room between the 2 joints.

J1 joins the radio tile, J2 the clicks tile; the 2 clicks' lines cross this tile from J2 to J1 at
the heights both joints give them.

    workcenter design touch/design.py --route     # from the version's folder

Layers: F.Cu the strip, In1.Cu a ground plane (the strip's shield from what lies
inside the ring), In2.Cu and B.Cu signals.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import ring  # noqa: E402
from ring import R0402, at  # noqa: E402

NAME = "touch"
STRIP_DY = -0.45  # the strip's middle from the tile's, toward the fingertip


def build():
    d = ring.tile(NAME, uuid.UUID("3e8c5a71-2d4b-4f60-9a1e-7b2c8d4e5f02"))
    d.power_nets = {"GND": "GND"}
    d.flagged_nets = ["GND"]
    d.net_classes = {
        # The channels keep other nets 0.2 mm away: no track fits between 2 stripes.
        "touch": {"width": 0.15, "clearance": 0.2, "via": 0.45, "via_drill": 0.2, "nets": ["TOUCH_A", "TOUCH_B", "TOUCH_C"]},
    }
    d.add("E1", "Ring:TouchStrip_3ch", "STRIP", "Ring:TouchStrip_3ch_6x", sch_at=(0, 0), pcb_at=at(NAME, 0, STRIP_DY),
          nets={"1": "TOUCH_A", "2": "TOUCH_B", "3": "TOUCH_C"})  # fmt: skip
    # Each stripe's own via near its left end, A, B and C at 3 x positions: the router joins each
    # channel's 2 stripes on the inner layers without its 3 lines crossing.
    strip = next(p for p in d.parts if p.ref == "E1")
    for b in d.pad_boxes():
        if b.ref == "E1":
            d.via(strip.nets[b.number], round(b.x1 + 0.6 + 0.8 * (int(b.number) - 1), 4), round((b.y1 + b.y2) / 2, 4))
    # The 3 channels' series resistors in a row under the strip, by J1's TSC pads (6 to 8); the strip
    # stands 0.45 mm toward the fingertip to leave a row of vias between them.
    for k, (ch, dx) in enumerate((("C", -1.95), ("B", 0.0), ("A", 1.95))):
        d.add(f"R{k + 1}", "Device:R", "10k", R0402, sch_at=(0, 0), pcb_at=at(NAME, dx, 5.3),
              nets={"1": f"TSC_{ch}", "2": f"TOUCH_{ch}"})  # fmt: skip
    d.defined_nets = {
        "BTN_L": "PC13's internal pull-up on the radio tile, through J1",
        "BTN_R": "PC5's internal pull-up on the radio tile, through J1",
    }
    d.check_pulls = True
    ring.finish(d, [("TOUCH", *at(NAME, 0, 0), "B.SilkS", 0.8)])
    return d
