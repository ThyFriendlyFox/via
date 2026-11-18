"""Signet v0.5, the radio tile: the ring's crown, 13.2 x 12 mm, 4 layers, the widest of the 8.

U1, an STM32WB5MMG, is Bluetooth LE with its antenna, crystals and SMPS inside a 7.3 x 11 mm module.
It stands on the tile's outer face with its antenna end at the tile's fingertip edge; no copper lies
over the antenna on any layer. The module talks to the computer as a BLE HID mouse, reads the IMU
on the motion tile, the scroll strip on the touch tile (its own touch controller, TSC), the 2 clicks,
and the cell's voltage and the charger's state from the power tile.

Its left edge (J1) joins the motion tile, its right edge (J2) the touch tile. Each joint's signals
sit level with the module pins they serve. The tile is 13.2 mm since v0.5 (15.6 before): a column of
0201s lies flat between J1 and pins 1-17, the supply's capacitors and BOOT0's resistor, each level
with its pin and a filled via in its ground pad; another stands on end between J2 and pins 31-47,
the touch sampling capacitor and VDDUSB's. The module sits 0.35 mm right of the tile's middle, so
its antenna's keep-out leaves a track's room beside J1's top pads. The light's
resistor and the bulk capacitor stand on the motion tile, the touch resistors on the touch tile. The
SWD pads lie on the inner face, flat, for a pogo jig.

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
from ring import C0201, R0201, X0, Y0, at  # noqa: E402

NAME = "radio"
W = ring.WIDTH[NAME]
# The antenna end 0.05 mm in from the edge; 0.35 mm right of the middle, so the antenna's keep-out
# (5.2 mm left of the module's middle) leaves 0.45 mm to J1's pads, 1.3 mm from the edge: room for
# the light's track up to J1's first pad, which sits level with the keep-out.
U1_AT = (round(X0 + W / 2 + 0.35, 4), round(Y0 + 0.05 + 5.5, 4))
# The footprint's antenna keep-out, x -4.95..2.65, y -6.5..-3 in the module's frame, 0.25 mm larger.
ANTENNA = [(U1_AT[0] - 5.2, U1_AT[1] - 6.75), (U1_AT[0] + 2.9, U1_AT[1] - 6.75), (U1_AT[0] + 2.9, U1_AT[1] - 2.75),
           (U1_AT[0] - 5.2, U1_AT[1] - 2.75)]  # fmt: skip
# The 2 columns of 0201s, between each joint's courtyard (1.45 mm in) and the module's (7.99 mm wide,
# 4.09 left and 3.9 right of its middle): 1.41 mm on the left, room for 1 lying flat; 0.9 mm on the
# right, room for 1 on end.
LEFT_X, RIGHT_X = round((X0 + 1.45 + U1_AT[0] - 4.09) / 2, 4), round((U1_AT[0] + 3.9 + X0 + W - 1.45) / 2, 4)


def build():
    d = ring.tile(NAME, uuid.UUID("0b6f1d2c-7a43-4e58-9c21-3f8e5d6a7b01"), sheet="A3")
    d.power_nets = {"GND": "GND", "+3V3": "+3V3"}
    d.flagged_nets = ["GND", "+3V3"]  # both arrive through J1 from the power tile

    def add(ref, lib, value, fp, nets, pos, rot=0.0, layer="F.Cu"):
        return d.add(ref, lib, value, fp, sch_at=(0, 0), pcb_at=pos, pcb_rot=rot, pcb_layer=layer, nets=nets)

    def r(ref, value, a, b, pos, rot):
        return add(ref, "Device:R", value, R0201, {"1": a, "2": b}, pos, rot)

    def c(ref, value, a, pos, rot):
        return add(ref, "Device:C", value, C0201, {"1": a, "2": "GND"}, pos, rot)

    def grounded(ref):
        """A via in the part's ground pad (2), filled and capped at the fab: the columns leave no room
        beside a 0201 for one."""
        b = next(b for b in d.pad_boxes() if b.ref == ref and b.number == "2")
        d.via("GND", round((b.x1 + b.x2) / 2, 4), round((b.y1 + b.y2) / 2, 4))

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

    # Left: the supply's capacitors and BOOT0's resistor, flat, each level with its pin, its ground
    # pad (2) toward J1. The tracks to J1's pads pass between them.
    for ref, value, net, pin_y in (("C2", "100n", "+3V3", -0.7), ("C3", "100n", "+3V3", 0.2),  # VREF+ (4); VDDA (6)
                                   ("C4", "100n", "NRST", 2.0), ("C5", "100n", "+3V3", 4.25),  # NRST (10); VBAT (15)
                                   ("C6", "100n", "+3V3", 5.175)):  # VDDSMPS (17)
        c(ref, value, net, (LEFT_X, round(U1_AT[1] + pin_y, 4)), 180)  # fmt: skip
        grounded(ref)
    r("R1", "10k", "BOOT0", "GND", (LEFT_X, round(U1_AT[1] + 3.35, 4)), 180)  # BOOT0 (13) low: boot from flash
    grounded("R1")

    # Right: the touch sampling capacitor and VDDUSB's, on end; C7 above PC13's line to J2.
    c("C7", "10n", "TSC_CS", (RIGHT_X, 105.6), 90)  # C0G: the TSC counts charge into it
    c("C8", "100n", "+3V3", (RIGHT_X, 110.44), 90)  # VDDUSB (32)
    grounded("C7")
    grounded("C8")

    # By hand, the links the router leaves for last and then cannot make: each part's pad to its pin,
    # straight across where the part stands level with it; the light's line up the channel between
    # J1's pads and the antenna's keep-out to J1's first pad; a ground via beside each of the 2
    # ground pins (5, 16) in the gap between the column and the module.
    def mid(ref, number):
        b = next(b for b in d.pad_boxes() if b.ref == ref and b.number == number and b.layer == "F.Cu")
        return round((b.x1 + b.x2) / 2, 4), round((b.y1 + b.y2) / 2, 4)

    for ref, net, pin in (("C2", "+3V3", "4"), ("C3", "+3V3", "6"), ("C4", "NRST", "10"), ("R1", "BOOT0", "13"),
                          ("C5", "+3V3", "15"), ("C6", "+3V3", "17")):  # fmt: skip
        d.track(net, [mid(ref, "1"), mid("U1", pin)], "F.Cu")
    gap_x = round((mid("C2", "1")[0] + 0.23 + mid("U1", "4")[0] - 0.175) / 2, 4)
    for pin in ("5", "16"):
        x, y = mid("U1", pin)
        d.via("GND", gap_x, y)
        d.track("GND", [(x, y), (gap_x, y)], "F.Cu")
    (xl, yl), (xj, yj) = mid("U1", "2"), mid("J1", "1")
    lane = round(X0 + 1.52, 4)  # 0.22 mm from J1's pads, 0.23 from the keep-out
    d.track("LED", [(xl, yl), (lane, yl), (lane, yj), (xj, yj)], "F.Cu")
    (x41, y41), (xc7, yc7) = mid("U1", "41"), mid("C7", "1")
    d.track("TSC_CS", [(x41, y41), (xc7 - 0.35 - (y41 - yc7), y41), (xc7 - 0.35, yc7), (xc7, yc7)], "F.Cu")
    (x32, y32), (xc8, yc8) = mid("U1", "32"), mid("C8", "1")
    d.track("+3V3", [(x32, y32), (xc8 - 0.35 - (yc8 - y32), y32), (xc8 - 0.35, yc8), (xc8, yc8)], "F.Cu")

    # The inner face: 5 flat pads for a pogo jig below the module, clear of the 2 columns' filled vias:
    # 4 in a row 2.0 mm apart, ground in a second row.
    for ref, value, net, dx, dy in (("TP1", "SWDIO", "SWDIO", -2.5, 3.6), ("TP2", "SWCLK", "SWCLK", -0.5, 3.6),
                                    ("TP3", "NRST", "NRST", 1.5, 3.6), ("TP4", "3V3", "+3V3", 3.5, 3.6),
                                    ("TP5", "GND", "GND", 2.5, 1.4)):  # fmt: skip
        add(ref, "Connector:TestPoint", value, "TestPoint:TestPoint_Pad_D1.0mm", {"1": net}, at(NAME, dx, dy), layer="B.Cu")

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
