"""Signet v0.3, the power tile: the charger, the 3.3 V rail and the cell's gauge, 4 layers.

The charging post's 5 V (VCHG) comes in on J1 from the cell tile and passes D2, a Schottky that
keeps a post wired the wrong way round, or a wet ring, from reaching the charger's input backward.
U1 (MCP73831) charges the cell at 30 mA: 1000 V / 33k (R1), MCP73831 datasheet DS20001984H, section
5.1; about 1.5 C for a 20 mAh cell. Its STAT goes to the radio. U2 (TPS7A0533, 1 uA quiescent,
TPS7A05 datasheet SBVS254D) makes +3V3 from the cell. R2 and R3 halve the cell's voltage for the
radio's ADC; C5 holds the reading for its sampling (sim/vbat_sense.cir).

J1 joins the cell tile, J2 the motion tile: +3V3, the gauge and STAT pass on to the radio.

    workcenter design power/design.py --route     # from the version's folder
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import ring  # noqa: E402
from ring import C0402, R0402, at  # noqa: E402

NAME = "power"


def build():
    d = ring.tile(NAME, uuid.UUID("9b4d1e27-8c0f-4a15-b6e7-2f3a9c0d1e05"))
    d.power_nets = {"GND": "GND", "VBAT": "+BATT", "VCHG": "VBUS", "VIN_CHG": "VBUS", "+3V3": "+3V3"}
    # VCHG and GND come in through J1, VIN_CHG through D2: no pin drives them. VBAT has the charger's
    # output pin, +3V3 the regulator's.
    d.flagged_nets = ["GND", "VCHG", "VIN_CHG"]

    def add(ref, lib, value, fp, nets, dx, dy, rot=0.0):
        return d.add(ref, lib, value, fp, sch_at=(0, 0), pcb_at=at(NAME, dx, dy), pcb_rot=rot, nets=nets)

    add("U1", "Battery_Management:MCP73831-2-OT", "MCP73831", "Package_TO_SOT_SMD:SOT-23-5",
        {"1": "CHG_STAT", "2": "GND", "3": "VBAT", "4": "VIN_CHG", "5": "PROG"}, -1.85, -3.1, 90)  # fmt: skip
    add("U2", "Regulator_Linear:TPS7A0533PDBZ", "TPS7A0533", "Package_TO_SOT_SMD:SOT-23-3",
        {"1": "GND", "2": "+3V3", "3": "VBAT"}, 1.85, -3.1, 90)  # fmt: skip
    add("D2", "Device:D_Schottky", "BAT54XV2", "Diode_SMD:D_SOD-523", {"1": "VIN_CHG", "2": "VCHG"}, -2.4, 0.9)
    for ref, value, a, b, dx, dy in (
        ("C1", "4.7u", "VIN_CHG", "GND", -2.0, 2.5),  # the charger's input
        ("C2", "4.7u", "VBAT", "GND", 0.0, 0.9),  # its output, the cell's node
        ("C3", "1u", "VBAT", "GND", 2.0, 0.9),  # the regulator's input
        ("C4", "1u", "+3V3", "GND", 2.0, 2.5),  # its output
        ("C5", "100n", "VBAT_SENSE", "GND", 2.0, 4.1),
    ):
        add(ref, "Device:C", value, C0402, {"1": a, "2": b}, dx, dy)
    for ref, value, a, b, dx, dy in (
        ("R1", "33k", "PROG", "GND", 0.0, 2.5),  # 30 mA into the cell
        ("R2", "1M", "VBAT", "VBAT_SENSE", -2.0, 4.1),  # the gauge: 2.1 uA from the cell at 4.2 V
        ("R3", "1M", "VBAT_SENSE", "GND", 0.0, 4.1),
    ):
        add(ref, "Device:R", value, R0402, {"1": a, "2": b}, dx, dy)
    # VBAT by hand, the way v0.2's router drew it: from J1's 2 cell pads over the top of the charger,
    # down between its pins 5 and 4 to its output (U1 pin 3), and on to the regulator's input (U2
    # pin 3). Left to itself the router runs PROG between them and leaves VBAT in 2 pieces.
    def mid(ref, number):
        b = next(b for b in d.pad_boxes() if b.ref == ref and b.number == number and b.layer == "F.Cu")
        return (b.x1 + b.x2) / 2, (b.y1 + b.y2) / 2

    (xj, yj), (_, yj3) = mid("J1", "2"), mid("J1", "3")
    (x5, y5), (x1, y1), (x2, y2) = mid("U1", "5"), mid("U1", "3"), mid("U2", "3")
    xa, yt, xc = xj + 1.04, y5 - 0.88, (x5 + x1) / 2  # beside J1, above U1, between its pins 5 and 4
    ym, xm = y1 - 0.86, x2 - 0.5  # between U1's pins 4 and 3; beside U2's pin 3
    d.track("VBAT", [(xj, yj3), (xj, yj)], "F.Cu")
    d.track("VBAT", [(xj, yj), (xa, yj - 1.04), (xa, yt + 0.39), (xa + 0.39, yt), (xc, yt),
                     (xc, ym - (x1 - xc)), (x1, ym), (x1, y1)], "F.Cu")  # fmt: skip
    d.track("VBAT", [(x1, ym), (xm - (ym - y2), ym), (xm, y2), (x2, y2)], "F.Cu")
    d.defined_nets = {"CHG_STAT": "PC1's internal pull-up on the radio tile, through J2 and the motion tile"}
    d.check_pulls = True
    ring.finish(d, [("POWER", *at(NAME, 0, 0), "B.SilkS", 0.8)])
    return d
