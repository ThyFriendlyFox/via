"""Signet v0.5, the clicks tile: 2 tactile switches, 4 layers, 6.83 mm.

SW1 (left click, nearer the fingertip) and SW2 (right click), C&K KMR2: 4.2 x 2.8 mm, 1.9 mm tall,
a short, firm click a thumb finds by feel. Each pulls its line to ground; the radio holds both lines
up and wakes on either (PC13 and PC5 are wake-up pins). Since v0.5 the tile is 6.83 mm wide and the
2 switches stand turned a quarter turn, their 4.2 mm along the finger, one above the other; their
L and R marks have no room left beside them.

J1 joins the touch tile, which carries both lines on to the radio; J2 joins the charge tile with 8
ground pads.

    workcenter design clicks/design.py --route     # from the version's folder
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import ring  # noqa: E402
from ring import at  # noqa: E402

NAME = "clicks"
KMR2 = "Button_Switch_SMD:SW_Push_1P1T_NO_CK_KMR2"


def build():
    d = ring.tile(NAME, uuid.UUID("5c1e7b93-4f6a-4d82-8b3c-9d4e0f6a7b03"))
    d.power_nets = {"GND": "GND"}
    d.flagged_nets = ["GND"]
    for ref, value, net, dy in (("SW1", "LEFT", "BTN_L", -2.85), ("SW2", "RIGHT", "BTN_R", 2.85)):
        d.add(ref, "Switch:SW_Push", value, KMR2, sch_at=(0, 0), pcb_at=at(NAME, 0, dy), pcb_rot=90,
              nets={"1": net, "2": "GND"})  # fmt: skip
    d.defined_nets = {
        "BTN_L": "PC13's internal pull-up on the radio tile, through the touch tile",
        "BTN_R": "PC5's internal pull-up on the radio tile, through the touch tile",
    }
    d.check_pulls = True
    ring.finish(d, [("CLICKS", *at(NAME, 0, 0), "B.SilkS", 0.6)])
    return d
