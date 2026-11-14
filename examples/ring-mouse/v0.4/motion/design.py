"""Signet v0.4, the motion tile: the IMU, 4 layers.

U1, an LSM6DSL, a 6-axis accelerometer and gyroscope on I2C1 of the radio, address 0x6A (SA0 held
low by R3). The gyro's turn rates are the cursor's motion; INT1 wakes the radio when the hand moves.
R1 and R2 are the bus's pull-ups. D1, the amber light, sits by the name, where the wearer sees
it on the side of the hand; the radio drives it from PA1 through 1k on its own tile and J2. The tile sits on the side of the finger, its axes turned from the
radio's by the angle between their faces; the firmware turns them back (firmware/src/air.c).

J1 joins the power tile, J2 the radio tile; +3V3, the cell's gauge and the charger's STAT cross this
tile from J1 to J2 at the heights both joints give them.

    workcenter design motion/design.py --route     # from the version's folder
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import ring  # noqa: E402
from ring import C0402, R0402, at  # noqa: E402

NAME = "motion"


def build():
    d = ring.tile(NAME, uuid.UUID("1d6e3f49-0a2b-4c37-8d8f-4a5b1e2f3a06"))
    d.power_nets = {"GND": "GND", "+3V3": "+3V3"}
    d.flagged_nets = ["GND", "+3V3"]  # both arrive through J1 from the power tile

    def add(ref, lib, value, fp, nets, dx, dy, rot=0.0):
        return d.add(ref, lib, value, fp, sch_at=(0, 0), pcb_at=at(NAME, dx, dy), pcb_rot=rot, nets=nets)

    # Turned so SDA and SCL face J2 and leave straight for it, INT1 on the top side.
    add("U1", "Sensor_Motion:LSM6DSL", "LSM6DSL", "Package_LGA:LGA-14_3x2.5mm_P0.5mm_LayoutBorder3x4y",
        {"1": "IMU_SA0", "2": "IMU_SA0", "3": "GND", "4": "IMU_INT", "5": "+3V3", "6": "GND", "7": "GND",
         "8": "+3V3", "12": "+3V3", "13": "I2C_SCL", "14": "I2C_SDA"}, 1.0, 2.6, -90)  # fmt: skip
    for ref, value, a, b, dx, dy in (
        ("C1", "100n", "+3V3", "GND", -0.4, 4.85),  # VDD (8), on the bottom side
        ("C2", "100n", "+3V3", "GND", -1.6, 2.0),  # VDDIO (5), on the left side
    ):
        add(ref, "Device:C", value, C0402, {"1": a, "2": b}, dx, dy)
    for ref, value, a, b, dx, dy, rot in (
        ("R1", "4.7k", "I2C_SCL", "+3V3", -2.0, -1.3, 0),
        ("R2", "4.7k", "I2C_SDA", "+3V3", -2.0, -2.3, 0),
        ("R3", "10k", "IMU_SA0", "GND", 3.4, 0.4, 90),  # SA0 low: address 0x6A; the unused aux bus's SDx with it
    ):
        add(ref, "Device:R", value, R0402, {"1": a, "2": b}, dx, dy, rot)
    d.defined_nets = {
        "IMU_INT": "the LSM6DSL drives INT1 push-pull",
        "CHG_STAT": "PC1's internal pull-up on the radio tile, through J2",
    }
    add("D1", "Device:LED", "AMBER", "LED_SMD:LED_0402_1005Metric", {"1": "GND", "2": "LED_A"}, 3.0, -4.55)
    d.check_pulls = True
    ring.finish(d, [("MOTION", *at(NAME, 0, 0), "B.SilkS", 0.8), ("SIGNET", *at(NAME, -0.6, -4.6), "F.SilkS", 0.9)])
    return d
