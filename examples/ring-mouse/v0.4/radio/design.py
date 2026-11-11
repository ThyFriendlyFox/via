"""Signet v0.4, the radio tile: the ring's crown, 15.6 x 12 mm, 4 layers, the widest of the 6.

U1, an STM32WB5MMG, is Bluetooth LE with its antenna, crystals and SMPS inside a 7.3 x 11 mm module.
It stands on the tile's outer face with its antenna end at the tile's fingertip edge; no copper lies
over the antenna on any layer. The module talks to the computer as a BLE HID mouse, reads the IMU
on the motion tile, the scroll strip on the touch tile (its own touch controller, TSC), the 2 clicks,
and the cell's voltage and the charger's state from the power tile.

Its left edge (J1) joins the motion tile, its right edge (J2) the touch tile. Each joint's signals
sit level with the module pins they serve: the supply capacitors and the light's resistor stand in
a column between J1 and pins 1-17, the touch resistors and the touch sampling capacitor between J2
and pins 31-47. The SWD pads lie on the inner face, flat, for a pogo jig.

    workcenter design radio/design.py --route     # from the version's folder

Layers: F.Cu (outside) the parts, In1.Cu a ground plane cut away under the antenna, In2.Cu and
B.Cu (inside, toward the finger) signals; no pour on either face. Via-free: the antenna's keep-out.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import ring  # noqa: E402
from ring import C0402, R0402, X0, Y0, at  # noqa: E402

NAME = "radio"
W = ring.WIDTH[NAME]
U1_AT = (round(X0 + W / 2, 4), round(Y0 + 0.05 + 5.5, 4))  # the antenna end 0.05 mm in from the edge
# The footprint's antenna keep-out, x -4.95..2.65, y -6.5..-3 in the module's frame, 0.25 mm larger.
ANTENNA = [(U1_AT[0] - 5.2, U1_AT[1] - 6.75), (U1_AT[0] + 2.9, U1_AT[1] - 6.75), (U1_AT[0] + 2.9, U1_AT[1] - 2.75),
           (U1_AT[0] - 5.2, U1_AT[1] - 2.75)]  # fmt: skip
LEFT_X, RIGHT_X = X0 + 2.6, X0 + W - 2.6  # the 2 columns of small parts beside the module


def build():
    d = ring.tile(NAME, uuid.UUID("0b6f1d2c-7a43-4e58-9c21-3f8e5d6a7b01"), sheet="A3")
    d.power_nets = {"GND": "GND", "+3V3": "+3V3"}
    d.flagged_nets = ["GND", "+3V3"]  # both arrive through J1 from the power tile

    def add(ref, lib, value, fp, nets, pos, rot=0.0, layer="F.Cu"):
        return d.add(ref, lib, value, fp, sch_at=(0, 0), pcb_at=pos, pcb_rot=rot, pcb_layer=layer, nets=nets)

    def r(ref, value, a, b, pos, rot=0.0):
        return add(ref, "Device:R", value, R0402, {"1": a, "2": b}, pos, rot)

    def c(ref, value, a, pos, b="GND"):
        return add(ref, "Device:C", value, C0402, {"1": a, "2": b}, pos)

    # Pin numbers from KiCad's symbol; each pin's functions from ST's open pin data
    # (STM32_open_pin_data, mcu/STM32WB5MMGHx.xml). Only the module's edge pads are used; its inner
    # grid is ground (84) and spare I/O.
    wb = {
        "4": "+3V3", "6": "+3V3", "15": "+3V3", "17": "+3V3", "32": "+3V3",  # VREF+, VDDA, VBAT, VDDSMPS, VDDUSB
        "5": "GND", "16": "GND", "31": "GND", "57": "GND", "60": "GND", "84": "GND", "86": "GND",
        "58": "RF", "59": "RF",  # RF_OUT straight to ANT_IN: the module's own antenna
        "10": "NRST", "13": "BOOT0", "25": "SWDIO", "26": "SWCLK",
        "3": "IMU_INT",  # PA0, SYS_WKUP1: the IMU wakes the ring on motion
        "7": "VBAT_SENSE",  # PC3, ADC1_IN4
        "9": "CHG_STAT",  # PC1
        "2": "LED",  # PA1, TIM2_CH2: the light on the motion tile, through J1
        "11": "I2C_SDA", "14": "I2C_SCL",  # PB9 I2C1_SDA, PB8 I2C1_SCL
        "40": "BTN_L",  # PC13, SYS_WKUP2
        "45": "BTN_R",  # PC5, SYS_WKUP5
        # The touch controller's group 1, all 4 of its pins on the module's right side: PB12 holds the
        # sampling capacitor, PB13, PB14 and PB15 the 3 channels, read one after another.
        "41": "TSC_CS", "35": "TSC_A", "37": "TSC_B", "38": "TSC_C",
    }  # fmt: skip
    add("U1", "RF_Module:STM32WB5MMG", "STM32WB5MMG", "RF_Module:ST-SiP-LGA-86-11x7.3mm", wb, U1_AT)
    # The inner ground pad (84) is ringed by pads: a via in it, filled and capped at the fab.
    p84 = next(b for b in d.pad_boxes() if b.ref == "U1" and b.number == "84")
    d.via("GND", round((p84.x1 + p84.x2) / 2, 4), round((p84.y1 + p84.y2) / 2, 4))
    # RF_OUT (59) to ANT_IN (58), the 2 pads side by side on the module's top row.
    rf = sorted((b for b in d.pad_boxes() if b.ref == "U1" and b.number in ("58", "59")), key=lambda b: b.x1)
    d.track("RF", [((b.x1 + b.x2) / 2, (b.y1 + b.y2) / 2) for b in rf], "F.Cu", width=0.25)
    # Ground pad 86 sits by the antenna, where no pour reaches: a track along the top edge to J2's
    # ground pad 1.
    p86 = next(b for b in d.pad_boxes() if b.ref == "U1" and b.number == "86")
    j21 = next(b for b in d.pad_boxes() if b.ref == "J2" and b.number == "1" and b.layer == "F.Cu")
    x86, y86 = (p86.x1 + p86.x2) / 2, (p86.y1 + p86.y2) / 2
    xj, yj = (j21.x1 + j21.x2) / 2, (j21.y1 + j21.y2) / 2
    d.track("GND", [(x86, y86), (xj - (yj - y86), y86), (xj, yj)], "F.Cu", width=0.2)

    # Left: the supply's capacitors, each level with its pin.
    for ref, value, net, y in (("C2", "100n", "+3V3", 104.58), ("C3", "100n", "+3V3", 105.56),  # VREF+ (4); VDDA (6)
                               ("C1", "4.7u", "+3V3", 106.54), ("C4", "100n", "NRST", 107.52),  # bulk; NRST (10)
                               ("C5", "100n", "+3V3", 109.48), ("C6", "100n", "+3V3", 110.46)):  # VBAT (15); VDDSMPS (17)
        c(ref, value, net, (LEFT_X, y))  # fmt: skip
    r("R1", "10k", "BOOT0", "GND", (LEFT_X, 108.5), 180)  # BOOT0 (13) low: boot from flash; pin 1 to it

    r("R2", "1k", "LED", "LED_A", (LEFT_X, 103.6), 180)  # PA1 (2) to the light on the motion tile, through J1

    # Right: the touch sampling capacitor and the 3 channels' series resistors.
    c("C7", "10n", "TSC_CS", (RIGHT_X, 106.2))  # C0G: the TSC counts charge into it
    r("R3", "10k", "TSC_C", "TOUCH_C", (RIGHT_X, 107.5))
    r("R4", "10k", "TSC_B", "TOUCH_B", (RIGHT_X, 108.48))
    r("R5", "10k", "TSC_A", "TOUCH_A", (RIGHT_X, 109.46))
    c("C8", "100n", "+3V3", (RIGHT_X, 110.44))  # VDDUSB (32)

    # The inner face: 5 flat pads for a pogo jig, below the module.
    for k, (ref, value, net) in enumerate((("TP1", "SWDIO", "SWDIO"), ("TP2", "SWCLK", "SWCLK"), ("TP3", "NRST", "NRST"),
                                            ("TP4", "3V3", "+3V3"), ("TP5", "GND", "GND"))):  # fmt: skip
        add(ref, "Connector:TestPoint", value, "TestPoint:TestPoint_Pad_D1.0mm", {"1": net}, at(NAME, -4.1 + 2.05 * k, 3.6),
            layer="B.Cu")  # fmt: skip

    d.keepout(ANTENNA, layers=("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"), name="antenna")
    edge = d.outline_polygon(d.edge_clearance, 8)
    ax0, ax1, ay1 = ANTENNA[0][0] - 0.3, ANTENNA[1][0] + 0.3, ANTENNA[2][1] + 0.3
    pour = [(x, y) for x, y in edge if not (ax0 < x < ax1 and y < ay1)]
    top = min(range(len(pour)), key=lambda i: (pour[i][1], -pour[i][0]))  # where the cut leaves the top edge
    pour = [*pour[: top + 1], (ax1, ay1), (ax0, ay1), *pour[top + 1 :]] if pour[top][0] < ax0 else pour
    d.zone("GND", layers=("In1.Cu",), polygon=pour, connect="solid")

    d.defined_nets = {
        "BTN_L": "PC13's internal pull-up, set in firmware",
        "BTN_R": "PC5's internal pull-up, set in firmware",
        "IMU_INT": "the LSM6DSL on the motion tile drives INT1 push-pull",
        "CHG_STAT": "PC1's internal pull-up, set in firmware (the charger's STAT is push-pull or high-Z)",
        "I2C_SDA": "4.7k to +3V3 on the motion tile (R2), through J1",
        "I2C_SCL": "4.7k to +3V3 on the motion tile (R1), through J1",
        "SWDIO": "PA13's internal pull-up in reset (SWD)",
        "SWCLK": "PA14's internal pull-down in reset (SWD)",
        "NRST": "the STM32's own pull-up on NRST, always on",
    }
    d.check_pulls = True
    ring.finish(d, [("SIGNET", *at(NAME, 0, -3.2), "B.SilkS", 1.0), ("RADIO", *at(NAME, 0, -1.6), "B.SilkS", 0.6)])
    return d
