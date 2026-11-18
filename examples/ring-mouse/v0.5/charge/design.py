"""Signet v0.5, the charge tile: the charger and its guards, 4 layers, 6.83 mm.

The charging post's 5 V (VCHG) comes in on J2 from the cell tile's inner pads. D1 (TPD1E05U06, TI
SLVSBO7O: 5.5 V stand-off, 6.5 V breakdown at least) takes a static discharge on those pads to
ground; a 5 V post never makes it conduct. D2, a Schottky, keeps a post wired the wrong way round,
or a wet ring, from reaching the charger's input backward. U1 (MCP73831) charges the cell at 30 mA:
1000 V / 33k (R1), MCP73831 datasheet DS20001984H, section 5.1; about 1.5 C for a 20 mAh cell. Its
output goes back to the cell through J2, and its STAT on to the radio, round the ring through the
cell, rail, gauge and motion tiles.

Until v0.5 these parts shared the power tile with the regulator and the gauge; 8 tiles leave each
small tile 6.83 mm, room for 1 SOT-23 between its 2 joints. J1 joins the clicks tile with 8 ground
pads.

    workcenter design charge/design.py --route     # from the version's folder
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import ring  # noqa: E402
from ring import C0402, R0402, at  # noqa: E402

NAME = "charge"


def build():
    d = ring.tile(NAME, uuid.UUID("4c8e2a61-3f7d-4b19-a0c5-6d2e9f1b3a08"))
    d.power_nets = {"GND": "GND", "VBAT": "+BATT", "VCHG": "VBUS", "VIN_CHG": "VBUS"}
    # VCHG and GND come in through the joints, VIN_CHG through D2: no pin drives them. VBAT has the
    # charger's output pin.
    d.flagged_nets = ["GND", "VCHG", "VIN_CHG"]

    def add(ref, lib, value, fp, nets, dx, dy, rot=0.0):
        return d.add(ref, lib, value, fp, sch_at=(0, 0), pcb_at=at(NAME, dx, dy), pcb_rot=rot, nets=nets)

    # Turned so its output (3) and STAT (1) face the top and J2's VBAT and STAT pads, its input (4)
    # and PROG (5) the bottom, toward D2 and R1.
    add("U1", "Battery_Management:MCP73831-2-OT", "MCP73831", "Package_TO_SOT_SMD:SOT-23-5",
        {"1": "CHG_STAT", "2": "GND", "3": "VBAT", "4": "VIN_CHG", "5": "PROG"}, 0, -2.0, 270)  # fmt: skip
    add("C2", "Device:C", "4.7u", C0402, {"1": "VBAT", "2": "GND"}, -1.0, -4.75)  # its output, the cell's node
    add("C1", "Device:C", "4.7u", C0402, {"1": "VIN_CHG", "2": "GND"}, -1.0, 0.95)  # its input
    add("R1", "Device:R", "33k", R0402, {"1": "PROG", "2": "GND"}, 1.0, 0.95)  # 30 mA into the cell
    add("D2", "Device:D_Schottky", "BAT54XV2", "Diode_SMD:D_SOD-523", {"1": "VIN_CHG", "2": "VCHG"}, 0, 2.55)
    add("D1", "Power_Protection:TPD1E05U06DYA", "TPD1E05U06", "Diode_SMD:D_SOD-523", {"1": "VCHG", "2": "GND"},
        0, 4.3, 180)  # fmt: skip
    d.defined_nets = {"CHG_STAT": "PC1's internal pull-up on the radio tile, round the ring from J2"}
    d.check_pulls = True
    ring.finish(d, [("CHARGE", *at(NAME, 0, 0), "B.SilkS", 0.6)])
    return d
