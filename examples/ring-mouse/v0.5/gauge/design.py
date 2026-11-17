"""Signet v0.5, the gauge tile: the cell's voltage for the radio's ADC, 4 layers, 6.83 mm.

R2 and R3 (1M each) halve the cell's voltage for the radio's ADC (PC3); C5 holds the reading for its
sampling (sim/vbat_sense.cir). The cell comes in on J1 from the rail tile with +3V3; +3V3, the
reading and the charger's STAT go on through J2 to the motion tile and the radio. Until v0.5 the
gauge shared the power tile with the charger and the regulator.

    workcenter design gauge/design.py --route     # from the version's folder
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import ring  # noqa: E402
from ring import C0402, R0402, at  # noqa: E402

NAME = "gauge"


def build():
    d = ring.tile(NAME, uuid.UUID("e5a3c1f7-9b24-4d6e-8f0a-2c7b5d9e1f0a"))
    d.power_nets = {"GND": "GND", "VBAT": "+BATT", "+3V3": "+3V3"}
    d.flagged_nets = ["GND", "VBAT", "+3V3"]  # all 3 arrive through J1

    def add(ref, lib, value, fp, nets, dx, dy, rot=0.0):
        return d.add(ref, lib, value, fp, sch_at=(0, 0), pcb_at=at(NAME, dx, dy), pcb_rot=rot, nets=nets)

    # The cell's pad on J1 (3) and the reading's on J2 (4) sit 1.3 mm apart: R2 level with the one, R3
    # and C5 with the other.
    add("R2", "Device:R", "1M", R0402, {"1": "VBAT", "2": "VBAT_SENSE"}, -0.95, -1.95)  # 2.1 uA at 4.2 V
    add("R3", "Device:R", "1M", R0402, {"1": "VBAT_SENSE", "2": "GND"}, 0.95, -1.95)
    add("C5", "Device:C", "100n", C0402, {"1": "VBAT_SENSE", "2": "GND"}, 0.95, -0.55, 180)
    d.defined_nets = {"CHG_STAT": "PC1's internal pull-up on the radio tile; it crosses this tile from J1 to J2"}
    d.check_pulls = True
    ring.finish(d, [("GAUGE", *at(NAME, 0, 3.0), "B.SilkS", 0.6)])
    return d
