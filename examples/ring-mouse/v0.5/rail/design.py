"""Signet v0.5, the rail tile: the 3.3 V regulator, 4 layers, 6.83 mm.

U2 (TPS7A0533, 1 uA typical quiescent, 3 uA at most, TPS7A05 datasheet SBVS254D) makes +3V3 from the
cell; it drops 235 mV at 200 mA, and the ring draws a few mA. C3 on its input and C4 on its output.
The cell comes in on J1 from the cell tile; +3V3 and the cell go on through J2 to the gauge tile,
and the charger's STAT crosses from J1 to J2 on its way to the radio. Until v0.5 the regulator
shared the power tile with the charger and the gauge.

    workcenter design rail/design.py --route     # from the version's folder
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import ring  # noqa: E402
from ring import C0402, at  # noqa: E402

NAME = "rail"


def build():
    d = ring.tile(NAME, uuid.UUID("b2e7d4c9-5a16-4f83-9e2d-7c1a0b6f4e09"))
    d.power_nets = {"GND": "GND", "VBAT": "+BATT", "+3V3": "+3V3"}
    d.flagged_nets = ["GND", "VBAT"]  # both arrive through J1; +3V3 has the regulator's output pin

    def add(ref, lib, value, fp, nets, dx, dy, rot=0.0):
        return d.add(ref, lib, value, fp, sch_at=(0, 0), pcb_at=at(NAME, dx, dy), pcb_rot=rot, nets=nets)

    # Its input (3) at the top, level with the cell's 2 pads on J1; its output (2) toward J2's +3V3.
    add("U2", "Regulator_Linear:TPS7A0533PDBZ", "TPS7A0533", "Package_TO_SOT_SMD:SOT-23-3",
        {"1": "GND", "2": "+3V3", "3": "VBAT"}, 0, -2.6, 90)  # fmt: skip
    add("C3", "Device:C", "1u", C0402, {"1": "VBAT", "2": "GND"}, -1.0, 0.05)  # its input
    add("C4", "Device:C", "1u", C0402, {"1": "+3V3", "2": "GND"}, 1.0, 0.05)  # its output
    d.defined_nets = {"CHG_STAT": "PC1's internal pull-up on the radio tile; it crosses this tile from J1 to J2"}
    d.check_pulls = True
    ring.finish(d, [("RAIL", *at(NAME, 0, 3.0), "B.SilkS", 0.6)])
    return d
