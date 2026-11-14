"""Wyvern v0.2: a Snapdragon development board on one flat board, 76.2 x 53.34 mm.

The Qualcomm QCS6490 (8 cores, 1 at 2.7 GHz) comes on Vantron's VOSM6490, an OSM Size-L module:
45 x 45 mm with its LPDDR5, eMMC and power management, soldered straight onto this board by its 662
LGA pads like any other chip (`osm_l.py`). No sockets, no second board.

- USB-C (J1) powers the board and carries the module's USB 3 port. The module brings out 1
  SuperSpeed lane, so an HD3SS3220 (U2) reads the plug's CC pins and switches the lane to the side
  the plug is on; it answers a charger's CC before anything else is powered (its dead-battery pull
  downs), so the board starts from a cold USB-C supply.
- A TPS552892 buck-boost (U3) makes the module's 5.0 V from whatever the cable delivers (4 to 5.5 V
  at the far end of a cable carrying 3 A): the module wants 4.8 to 5.2 V. An AP2112K (U4) makes
  3.3 V from it.
- An RP2350 (U5) owns 30 of the 0.1 inch pins at 3.3 V, the way a Teensy's MCU does. It talks to
  the Snapdragon over the module's second USB port, and the Snapdragon resets it and puts it in its
  bootloader through 2 open-drain buffers (U7, U8): Linux flashes it.
- The Snapdragon's own 1.8 V signals are on the pins too, apart, at the module's end: its debug
  UART, 2 I2C buses, an SPI bus, 2 GPIOs, its power key, reset and recovery, its RTC battery input.
- A microSD slot (J4) under the far end, on the module's SD card port.

    workcenter design design.py --route     # from this folder

Board: 76.2 x 53.34 mm (3.0 x 2.1 inch), 6 layers, 1.6 mm: F.Cu signal, In1.Cu ground, In2.Cu signal,
In3.Cu signal and the 5 V plane, In4.Cu ground, B.Cu signal. The pins are 2 rows of 30 on a 0.1 inch
grid, 2.0 inch apart; the headers sit underneath, pins down.
"""

from __future__ import annotations

import math
import sys
import uuid
from pathlib import Path

import kicadgen

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import osm_l  # noqa: E402

# ---- the board ----------------------------------------------------------------------------------
LEFT, TOP = 100.0, 100.0
WIDTH, HEIGHT = 76.2, 53.34  # 3.0 x 2.1 inch
RIGHT, BOTTOM = LEFT + WIDTH, TOP + HEIGHT
CY = round(TOP + HEIGHT / 2, 3)  # 126.67
PITCH = 2.54
ROW_TOP = TOP + 1.27  # the pins' rows, 2.0 inch apart
ROW_BOTTOM = BOTTOM - 1.27


def pin_x(k: int) -> float:
    return round(LEFT + 1.27 + PITCH * k, 3)


# ---- the module: turned 90 degrees, so its row A (its USB-C lane) faces the USB-C end -----------
MODULE = (round(RIGHT - 1.0 - osm_l.SIZE / 2, 3), CY)  # its right edge 1.0 mm from the board's
MODULE_ROT = 90.0


def mod_pad(pad: str) -> tuple[float, float]:
    """Where a module pad sits on the board: the footprint turned 90 degrees, so the module's x (its
    columns) runs up the board and its y (its rows) runs to the right."""
    x, y = osm_l.pad_xy(pad)
    return (round(MODULE[0] + y, 3), round(MODULE[1] - x, 3))


def mod_local(bx: float, by: float) -> tuple[float, float]:
    """A board point in the module's own frame (seen from above, x right, y down)."""
    return (round(MODULE[1] - by, 4), round(bx - MODULE[0], 4))


# ---- footprints ---------------------------------------------------------------------------------
R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
LED0603 = "LED_SMD:LED_0603_1608Metric"
USBC = "Wyvern:USB_C_Receptacle_Amphenol_12401610E4-2A_Ring6mil"
HEADER = "Connector_PinHeader_2.54mm:PinHeader_1x30_P2.54mm_Vertical"
BUTTON = "Button_Switch_SMD:SW_Push_1P1T_NO_CK_KMR2"
SOT353 = "Package_TO_SOT_SMD:SOT-353_SC-70-5"
TP = "TestPoint:TestPoint_Pad_D1.0mm"
B = "B.Cu"

# ---- the pins, left to right; the top row is J2, the bottom row J3 ------------------------------
TOP_PINS = (["GND", "5V", "3V3"] + [f"GP{i}" for i in range(15)]
            + ["GND", "1V8", "TX", "RX", "SDA", "SCL", "SDA2", "SCL2", "IO3", "IO4", "PWR", "GND"])  # fmt: skip
BOTTOM_PINS = (["GND", "RUN", "3V3"] + [f"GP{i}" for i in range(15, 30)]
               + ["GND", "1V8", "CS", "SCK", "SDI", "SDO", "RST", "REC", "VBAT", "GND", "3V3", "GND"])  # fmt: skip
PIN_NET = {
    "GND": "GND", "5V": "VBUS", "3V3": "+3V3", "1V8": "+1V8", "RUN": "MCU_RUN",
    "PWR": "SOM_PWR_N", "RST": "SOM_RST_N", "REC": "SOM_REC_N", "VBAT": "SOM_RTC",
    "TX": "SOM_UART_TX", "RX": "SOM_UART_RX", "SDA": "SOM_I2C_SDA", "SCL": "SOM_I2C_SCL",
    "SDA2": "SOM_I2C2_SDA", "SCL2": "SOM_I2C2_SCL", "IO3": "SOM_GPIO3", "IO4": "SOM_GPIO4",
    "CS": "SOM_SPI_CS", "SCK": "SOM_SPI_SCK", "SDI": "SOM_SPI_SDI", "SDO": "SOM_SPI_SDO",
} | {f"GP{i}": f"GP{i}" for i in range(30)}  # fmt: skip
assert len(TOP_PINS) == 30 and len(BOTTOM_PINS) == 30

# ---- what the board connects on the module, by Vantron's names (osm_l.py); the rest stays open --
MODULE_NETS = {
    "VCC_IN_5V": "+5V", "GND": "GND", "VCC_OUT_IO": "+1V8", "RTC_PWR": "SOM_RTC",
    "USB0_HS_DP": "USB_D_P", "USB0_HS_DM": "USB_D_N",
    "USB0_SS_TX0_P": "SS_TXC_P", "USB0_SS_TX0_M": "SS_TXC_N", "USB0_SS_RX0_P": "SS_RX_P", "USB0_SS_RX0_M": "SS_RX_N",
    "USB-C_VBUS_DET": "SOM_VBUS_DET",
    "USB1_HS_DP": "MCU_USB_P", "USB1_HS_DM": "MCU_USB_N",
    "PWR_BTN#": "SOM_PWR_N", "SYS_RST#": "SOM_RST_N", "FORCE_RECOVERY#": "SOM_REC_N",
    "UART_DEBUG_TXD": "SOM_UART_TX", "UART_DEBUG_RXD": "SOM_UART_RX",
    "APPS_I2C_SDA": "SOM_I2C_SDA", "APPS_I2C_SCL": "SOM_I2C_SCL",
    "EXT_I2C2_SDA": "SOM_I2C2_SDA", "EXT_I2C2_SCL": "SOM_I2C2_SCL",
    "EXT_GPIO_1": "MCU_RUN_CTL", "EXT_GPIO_2": "MCU_BOOT_CTL", "EXT_GPIO_3": "SOM_GPIO3", "EXT_GPIO_4": "SOM_GPIO4",
    "SPI_A_CS0#": "SOM_SPI_CS", "SPI_A_SCK": "SOM_SPI_SCK", "SPI_A_SDI": "SOM_SPI_SDI", "SPI_A_SDO": "SOM_SPI_SDO",
    "SDC2_CLK": "SD_CLK", "SDC2_CMD": "SD_CMD", "SDC2_DATA_0": "SD_D0", "SDC2_DATA_1": "SD_D1",
    "SDC2_DATA_2": "SD_D2", "SDC2_DATA_3": "SD_D3", "SD_CARD_DET_N": "SD_DET_N",
    "VREG_L9C_2P96": "SD_VDD", "SDC2_VDDIO": "SD_VIO",
}  # fmt: skip

# USB-C: the HD3SS3220's connector side to the receptacle's 2 sets of SuperSpeed pins, its CC pins
# to the receptacle's; USB 2 straight to the module, both rows. The mux's TX1 pair reaches A2 and A3
# turned over (its P on A3): the 2 pins run the other way round from the mux's, and every USB 3
# receiver inverts a lane's polarity by itself (USB 3.2, 6.4.2), so the pair stays on the top layer
# without crossing itself.
USB_C = {
    "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
    "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND", "SH": "GND",
    "A5": "USB_CC1", "B5": "USB_CC2",
    "A6": "USB_D_P", "B6": "USB_D_P", "A7": "USB_D_N", "B7": "USB_D_N",
    "A2": "SS_TX1_N", "A3": "SS_TX1_P", "B11": "SS_RX1_P", "B10": "SS_RX1_N",
    "B2": "SS_TX2_P", "B3": "SS_TX2_N", "A11": "SS_RX2_P", "A10": "SS_RX2_N",
}  # fmt: skip
UY = 135.8  # the receptacle's centre line
# The receptacle's front face is 5.23 mm in front of its footprint's origin (Amphenol's cut sheet:
# 9.59 mm from the face to its pegs, which the footprint puts at -4.36). It stands 1.0 mm past the
# edge, its front shell legs 0.7 mm inside it.
USB_C_AT = (LEFT - 1.0 + 5.23, UY)

DIFF = ("SS_TXC", "SS_TX", "SS_RX", "SS_TX1", "SS_RX1", "SS_TX2", "SS_RX2", "USB_D", "MCU_USB")
PAIR_W, PAIR_GAP = 0.25, 0.15  # 90 ohm on 0.21 mm of 7628 to the plane under it (IPC-2141): 0.4 mm pitch


def hand_via(d: kicadgen.Design, net: str, x: float, y: float) -> None:
    """A signal-size via (0.51 mm, 0.2 mm hole, Sierra's 6 mil ring) on any net, the supplies included."""
    d.via(net, x, y, size=0.51, drill=0.2)


def offset(points: list[tuple[float, float]], dist: float) -> list[tuple[float, float]]:
    """A polyline moved `dist` mm to the left of its direction of travel (board coordinates, y down,
    so heading west the left is south), its corners mitred: the 2 tracks of a pair from 1 centre line."""

    def normal(a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy)
        return (dy / n, -dx / n)

    out = []
    for i, p in enumerate(points):
        if i == 0:
            nx, ny = normal(points[0], points[1])
        elif i == len(points) - 1:
            nx, ny = normal(points[-2], points[-1])
        else:
            n1, n2 = normal(points[i - 1], p), normal(p, points[i + 1])
            k = 1 + n1[0] * n2[0] + n1[1] * n2[1]
            nx, ny = (n1[0] + n2[0]) / k, (n1[1] + n2[1]) / k
        out.append((round(p[0] + dist * nx, 4), round(p[1] + dist * ny, 4)))
    return out


def pair(d, name: str, centre, layer: str, p_left: bool, p_ends=((), ()), n_ends=((), ())) -> None:
    """A coupled pair from its centre line, P on the left of travel or on the right, 0.4 mm apart. Each
    end's stub, from a pad or a via to where the pair's own tracks begin, is drawn necked down."""
    half = (PAIR_W + PAIR_GAP) / 2
    p = offset(centre, half if p_left else -half)
    n = offset(centre, -half if p_left else half)
    for net, (start, end), points in ((f"{name}_P", p_ends, p), (f"{name}_N", n_ends, n)):
        d.track(net, points, layer)
        if start:
            d.track(net, [*start, points[0]], layer, width=NECK)
        if end:
            d.track(net, [points[-1], *end], layer, width=NECK)


NECK = 0.15  # a pair's width for its last mm into a 0.4 or 0.5 mm pitch pad row


def power_stage(d: kicadgen.Design) -> None:
    """The buck-boost's power pads by hand: 0.25 mm pads 0.5 mm apart that carry 4 A.

    Each power pad leaves from the end its neighbours leave free, 0.25 mm wide for its first 0.3 mm
    and then 0.6 mm: VIN west to its capacitors (C32, C30, C31), VOUT west to its own (C37, C33, C34)
    with ISP and ISN joined to it (no output current limit, datasheet 7.3.9), PGND west between them
    to 2 vias, SW1 and SW2 east to the inductor's 2 pads. The bootstrap capacitors sit beyond the
    inductor's ends, the VCC capacitor and the feedback and compensation parts under the chip."""
    f = "F.Cu"
    for net, y in (("VBUS", 143.96), ("GND", 145.0), ("+5V", 146.04)):
        d.track(net, [(110.8, y), (110.0, y)], f, width=0.25)
    d.track("VBUS", [(110.0, 143.96), (107.25, 143.96)], f, width=0.6)
    d.track("VBUS", [(107.25, 142.5), (107.25, 144.5)], f, width=0.6)
    d.track("GND", [(110.0, 145.0), (108.4, 145.0)], f, width=0.6)
    for x in (109.6, 108.7):
        d.via("GND", x, 145.0, size=0.51, drill=0.2)
    d.track("+5V", [(110.0, 146.04), (107.25, 146.04)], f, width=0.6)
    d.track("+5V", [(107.25, 146.04), (107.25, 148.5)], f, width=0.6)
    # The output to the 5 V plane on In3 through 3 power vias: the router left it to 1 that missed.
    for x, y in ((107.25, 147.0), (107.25, 148.0), (108.0, 146.04)):
        d.via("+5V", x, y, size=0.65, drill=0.3)
    d.track("+5V", [(110.6, 147.04), (110.6, 146.54), (110.1, 146.54), (110.1, 146.1)], f, width=0.2)
    for net, y, pad in (("BB_SW1", 144.46, (117.8, 143.06)), ("BB_SW2", 145.54, (117.8, 146.94))):
        d.track(net, [(113.2, y), (114.1, y)], f, width=0.25)
        d.track(net, [(114.1, y), (116.4, y), pad], f, width=0.6)
    d.track("BB_BOOT1", [(113.4, 143.46), (114.0, 143.46), (114.6, 142.86), (114.6, 142.2), (115.12, 141.7)], f,
            width=0.2)
    d.track("BB_SW1", [(116.08, 141.7), (116.9, 141.7), (117.7, 142.5)], f, width=0.3)
    d.track("BB_BOOT2", [(113.4, 146.54), (114.0, 146.54), (114.6, 147.14), (114.6, 147.9), (115.12, 148.4)], f,
            width=0.2)
    d.track("BB_SW2", [(116.08, 148.4), (116.9, 148.4), (117.7, 147.6)], f, width=0.3)
    d.track("BB_VCC", [(113.4, 147.04), (113.9, 147.54), (113.9, 148.92)], f, width=0.25)
    d.track("BB_FB", [(111.25, 147.4), (111.25, 148.2), (109.4, 148.2), (109.4, 148.89)], f, width=0.15)
    d.track("BB_FB", [(110.4, 148.2), (110.4, 148.89)], f, width=0.15)
    d.track("BB_COMP", [(111.75, 147.4), (111.75, 148.4), (111.9, 148.6), (111.9, 148.89)], f, width=0.15)
    d.track("BB_COMP_RC", [(111.9, 149.91), (112.9, 149.88)], f, width=0.2)
    # C32's ground pad sits between VIN's and FSW's tracks, which cut it off from the top pour in the
    # first routes: a via to the planes, through R33's ground pad beside it.
    d.track("GND", [(108.55, 143.02), (108.55, 142.3)], f, width=0.25)
    hand_via(d, "GND", 108.55, 142.3)


# The 5 V plane's strip up the module's middle, on In3, is narrow, and the router's In3 tracks cut it
# into 3 in the first routes, leaving the Y row's 5 V pads on islands. A spine of copper along the Y
# row's own line holds it together: every fan-out via sits on the diagonal grid, 0.625 mm off any pad
# line, so a 0.38 mm track on the line keeps Sierra's 13 mil from each hole, and the router can no
# longer cross the strip on In3. A second spine runs along column 27's line to C50.
SPINE_X = mod_pad("Y17")[0]  # 155.2
SPINE_Y = mod_pad("Y27")[1]  # 115.42
SPINE_W = 0.38


def five_volt_spine(d: kicadgen.Design) -> None:
    d.track("+5V", [(SPINE_X, 113.0), (SPINE_X, 141.9)], "In3.Cu", width=SPINE_W)
    d.track("+5V", [(SPINE_X, SPINE_Y), (163.0, SPINE_Y), (163.65, 116.05), (163.65, 116.4)], "In3.Cu",
            width=SPINE_W)
    hand_via(d, "+5V", 163.65, 116.4)
    d.track("+5V", [(163.65, 116.4), (163.65, 115.0)], "B.Cu", width=0.5)  # C50's 5 V pad


def five_volt_stubs(d: kicadgen.Design) -> None:
    """Each 5 V fan-out via beside the spine, joined to it on In3."""
    for net, (x, y), *_ in list(d.vias):
        if net == d.pcb_net_name("+5V") and abs(x - SPINE_X) < 0.7 and 112.6 < y < 141.6:
            d.track("+5V", [(x, y), (SPINE_X, y)], "In3.Cu", width=SPINE_W)


def usb_lane(d: kicadgen.Design) -> None:
    """The module's SuperSpeed lane through the mux to both sides of the receptacle, by hand.

    The module side: TX leaves A8 and A9 west through its 2 coupling capacitors to the mux's TXp and
    TXn, RX leaves B10 and B11 (B11 through the gap where row A has no pads 11 to 13) to RXp and RXn.
    The receptacle side: TX1 and RX2 stay on the top layer to A2/A3 and A10/A11; RX1 and TX2 drop
    to the bottom layer and come up through the vias in front of the receptacle's B row, the way v0.1
    reached that row. The mux's control pins drop to vias of their own: CC1, CC2, VBUS_DET, VCC33.
    """
    f, b = "F.Cu", "B.Cu"
    # The receptacle's B row: each pad's stub to its via in front of it, alternate pads to alternate
    # columns; each A-row ground and supply pad to the B-row pad beside it (v0.1's, moved down 20.56).
    vx = (106.75, 106.0)
    brow = [("B12", "GND"), ("B11", "SS_RX1_P"), ("B10", "SS_RX1_N"), ("B9", "VBUS"), ("B8", ""), ("B7", "USB_D_N"),
            ("B6", "USB_D_P"), ("B5", "USB_CC2"), ("B4", "VBUS"), ("B3", "SS_TX2_N"), ("B2", "SS_TX2_P"),
            ("B1", "GND")]  # fmt: skip
    for k, (_, net) in enumerate(brow):
        if not net:
            continue
        y = round(UY - 3.0 + 0.5 * k, 2)
        x = vx[0] if k % 2 else vx[1]
        d.track(net, [(107.55, y), (x, y)], f, width=NECK)
        hand_via(d, net, x, y)
    for (ya, yb), net in (((UY - 2.75, UY - 3.0), "GND"), ((UY - 1.25, UY - 1.5), "VBUS"),
                          ((UY + 1.25, UY + 1.0), "VBUS"), ((UY + 2.75, UY + 2.5), "GND")):  # fmt: skip
        d.track(net, [(109.25, ya), (108.9, ya), (107.9, yb), (107.55, yb)], f, width=NECK)

    # The module side. TX: mux pins 6 and 7 east, south-east to the coupling capacitors, on to A8, A9.
    pair(d, "SS_TX", [(116.9, 135.4), (121.0, 135.4), (122.6, 137.0), (123.9, 137.0)], f, p_left=False,
         p_ends=((), [(124.82, 137.7)]), n_ends=((), [(124.82, 136.7)]))
    pair(d, "SS_TXC", [(126.7, 137.2), (127.6, 137.2), (128.9, 138.5), (129.9, 138.5)], f, p_left=False,
         p_ends=([(125.78, 137.7)], [(130.6, 139.17), (131.45, 139.17)]),
         n_ends=([(125.78, 136.7)], [(130.6, 137.92), (131.45, 137.92)]))
    # RX: mux pins 9 and 10 east, north-east round pin 8's via, east, south-east to B10 and B11.
    pair(d, "SS_RX", [(116.9, 134.2), (117.35, 134.2), (117.95, 133.6), (124.4, 133.6), (126.6, 135.8),
                      (130.8, 135.8)], f, p_left=False,
         p_ends=((), [(131.0, 135.95), (131.9, 135.95), (132.45, 136.45), (132.7, 136.67)]),
         n_ends=((), [(131.2, 135.42), (132.7, 135.42)]))
    # VCC33 (pin 8) out between the 2 pairs to a via, and C46 under it.
    d.track("+3V3", [(116.9, 134.8), (117.6, 134.8), (117.95, 134.45), (118.5, 134.45)], f, width=0.2)
    hand_via(d, "+3V3", 118.5, 134.45)
    d.track("+3V3", [(118.5, 134.45), (118.82, 134.45)], b, width=0.25)
    # The mux's grounded pins into its exposed pad, and its control pins out to vias.
    for x0, y0, x1, y1 in ((116.5, 136.4, 115.9, 136.4), (115.5, 133.6, 115.5, 134.4), (115.9, 133.6, 115.9, 134.4),
                           (115.5, 138.0, 115.5, 137.2), (115.9, 138.0, 115.9, 137.2)):  # fmt: skip
        d.track("GND", [(x0, y0), (x1, y1)], f, width=0.2)
    for net, pts in (("HD_VBUS_DET", [(116.9, 136.0), (117.4, 136.0), (117.7, 136.3)]),
                     ("USB_CC1", [(116.9, 137.2), (118.3, 137.1)]),
                     ("USB_CC2", [(116.9, 137.6), (117.45, 137.6), (117.7, 137.75)])):  # fmt: skip
        d.track(net, pts, f, width=0.127)
        hand_via(d, net, *pts[-1])
    d.track("+5V", [(116.3, 138.4), (116.12, 139.4), (116.12, 139.7)], f, width=0.25)  # VDD5 to C45
    d.track("HD_DIR", [(116.3, 133.2), (116.3, 132.4), (116.09, 131.9)], f, width=0.15)  # DIR to R37

    # The receptacle side. TX1 on top, west to A3 (P) and A2 (N).
    pair(d, "SS_TX1", [(113.9, 134.2), (110.8, 134.2), (110.4, 133.8), (110.0, 133.8)], f, p_left=True,
         p_ends=((), [(109.25, 134.05)]), n_ends=((), [(109.25, 133.55)]))
    # RX2 on top: west, then south past the receptacle's middle pads' vias, west to A11 (P), A10 (N).
    pair(d, "SS_RX2", [(113.9, 135.0), (112.2, 135.0), (111.6, 135.6), (111.6, 137.2), (111.0, 137.8),
                       (110.0, 137.8)], f, p_left=True,
         p_ends=((), [(109.25, 138.05)]), n_ends=((), [(109.25, 137.55)]))
    # CC1, D+ and D- from the A row to vias just behind it.
    for net, pad, via in (("USB_CC1", (109.6, 135.05), (110.2, 135.0)), ("USB_D_P", (109.6, 135.55), (110.75, 135.6)),
                          ("USB_D_N", (109.6, 136.05), (110.2, 136.3))):  # fmt: skip
        d.track(net, [pad, via], f, width=NECK)
        hand_via(d, net, *via)
    # The B row's D+ joins A6's via on In3, its D- A7's on the bottom layer.
    d.track("USB_D_P", [(106.0, 135.8), (110.55, 135.8), (110.75, 135.6)], "In3.Cu", width=0.127)
    d.track("USB_D_N", [(106.75, 135.3), (109.2, 135.3), (110.2, 136.3)], b, width=NECK)
    # CC1 and CC2 on In2 to the mux's vias.
    d.track("USB_CC2", [(106.75, 136.3), (107.3, 136.85), (111.0, 136.85), (111.6, 137.45), (117.7, 137.45),
                        (117.7, 137.75)], "In2.Cu", width=0.127)  # fmt: skip
    d.track("USB_CC1", [(110.2, 135.0), (114.6, 135.0), (116.7, 137.1), (118.3, 137.1)], "In2.Cu", width=0.127)
    # TX2: mux pins 20 and 21 west to 2 vias, the bottom layer west to the B row's B3 (N) and B2 (P).
    d.track("SS_TX2_N", [(113.9, 135.6), (113.0, 135.6), (112.6, 136.0)], f, width=NECK)
    d.track("SS_TX2_P", [(113.9, 136.0), (113.6, 136.0), (113.3, 136.3), (113.3, 136.6)], f, width=NECK)
    hand_via(d, "SS_TX2_N", 112.6, 136.0)
    hand_via(d, "SS_TX2_P", 113.3, 136.6)
    d.track("SS_TX2_N", [(112.6, 136.0), (111.35, 137.25), (107.55, 137.25)], b)
    d.track("SS_TX2_N", [(107.55, 137.25), (107.5, 137.3), (106.75, 137.3)], b, width=NECK)
    d.track("SS_TX2_P", [(113.3, 136.6), (112.25, 137.65), (107.6, 137.65)], b)
    d.track("SS_TX2_P", [(107.6, 137.65), (107.45, 137.8), (106.0, 137.8)], b, width=NECK)
    # RX1: mux pins 15 (P) and 14 (N) north to 2 vias, the bottom layer west to B11 (P) and B10 (N).
    d.track("SS_RX1_P", [(114.7, 133.2), (114.7, 132.5), (114.4, 132.2), (114.4, 132.0)], f, width=NECK)
    d.track("SS_RX1_N", [(115.1, 133.2), (115.1, 132.75), (115.2, 132.55)], f, width=NECK)
    hand_via(d, "SS_RX1_P", 114.4, 132.0)
    hand_via(d, "SS_RX1_N", 115.2, 132.55)
    # Clear of the receptacle's locating peg (108.59, 132.2) by Sierra's 13 mil from a hole.
    pair(d, "SS_RX1", [(113.7, 133.2), (108.3, 133.2), (108.0, 133.5), (107.6, 133.5)], b, p_left=False,
         p_ends=([(114.4, 132.0), (113.4, 133.0)], [(106.75, 133.3)]),
         n_ends=([(115.2, 132.55), (114.4, 133.4)], [(107.5, 133.8), (106.0, 133.8)]))


# ---- the RP2350 and its parts: v0.1's block, turned a quarter turn clockwise --------------------
# v0.1 laid the chip out at (141.5, 115.5) with its GPIO 0 to 11 to the west; here the same parts
# and the same hand-drawn copper stand turned 90 degrees clockwise about the chip, so those GPIOs
# face the top row of pins, GPIO 19 to 29 the bottom row, and the USB and flash side faces the
# module. Every point and angle below is v0.1's, put through `T` and `TR`.
V1_MCU = (141.5, 115.5)
MCU = (112.5, 115.2)


def T(x: float, y: float) -> tuple[float, float]:
    """A point of v0.1's RP2350 block, on this board."""
    return (round(MCU[0] - (y - V1_MCU[1]), 3), round(MCU[1] + (x - V1_MCU[0]), 3))


def TR(rot: float) -> float:
    return (rot + 270.0) % 360.0


def core_rail(d: kicadgen.Design) -> None:
    """v0.1's hand copper round the RP2350 (its M146 fixes), turned with the block.

    The 1.1 V core (DVDD 6, 23, 39 and VREG_FB 50): each pin's stub inward to a via inside the ring of
    pads, In3 joining the 4 vias under the ground pad; 3.3 V to each pin's 100 nF; both sides' GPIOs
    fanned out to alternating columns of vias; the QSPI lines; the crystal; the core regulator."""

    def tr(net: str, pts: list[tuple[float, float]], layer: str, width: float | None = None) -> None:
        if width is None:
            d.track(net, [T(*p) for p in pts], layer)
        else:
            d.track(net, [T(*p) for p in pts], layer, width=width)

    def tv(net: str, x: float, y: float) -> None:
        hand_via(d, net, *T(x, y))

    vias = {"6": (138.95, 114.70), "23": (141.5, 117.65), "39": (144.05, 115.10), "50": (142.7, 112.95)}
    pads = {"6": (138.05, 114.70), "23": (141.5, 118.95), "39": (144.95, 115.10), "50": (142.7, 112.05)}
    for pin, via in vias.items():
        tr("+1V1", [pads[pin], via], "F.Cu", 0.25)
        tv("+1V1", *via)
    c10 = (147.2, 111.2)
    tr("+1V1", [(138.05, 114.70), (136.4, 114.70), (136.4, 115.02)], "F.Cu", 0.25)  # C18
    tr("+1V1", [(147.6, 110.38), c10], "F.Cu", 0.25)
    tv("+1V1", *c10)
    tr("+1V1", [vias["6"], (142.7, 114.70)], "In3.Cu")
    tr("+1V1", [c10, (145.45, 112.95), vias["50"], (142.7, 115.10), vias["39"]], "In3.Cu")
    tr("+1V1", [vias["23"], (141.5, 114.70)], "In3.Cu")
    for x, y in ((140.4, 115.6), (140.4, 116.6), (142.6, 116.0), (142.6, 116.7)):
        tv("GND", x, y)
    for pts in (
        [(138.05, 112.70), (136.4, 112.70), (136.4, 113.02)],  # 1 to C12
        [(138.05, 116.70), (136.4, 116.70), (136.4, 117.02)],  # 11 to C13
        [(144.95, 115.50), (146.0, 115.50), (146.4, 115.80), (146.6, 115.98)],  # 38 to C14
        [(144.95, 112.70), (145.25, 112.70), (145.25, 113.10)],  # 45 to 44
        [(144.95, 113.10), (146.6, 113.10)],  # 44 to C15
        [(144.3, 118.95), (144.3, 119.60), (146.6, 119.60), (146.6, 117.98)],  # 30 to C16, round the fan-out
        [(143.1, 112.05), (143.1, 110.38)],  # 49 to C9
        [(141.1, 112.05), (141.5, 112.05)],  # 54 to 53
        [(141.3, 112.05), (141.45, 113.3)],
    ):
        tr("+3V3", pts, "F.Cu", 0.25)
    tv("+3V3", 141.45, 113.3)
    east = {31: (145.8, 118.3), 32: (143.95, 117.9), 33: (145.8, 117.55), 34: (143.95, 117.1),
            35: (145.8, 116.8), 36: (143.95, 116.3), 37: (145.8, 116.05), 40: (145.8, 114.7),
            41: (143.95, 114.3), 42: (145.8, 113.95), 43: (143.95, 113.6)}  # fmt: skip
    for pin, via in east.items():
        net = f"GP{ {31: 19, 32: 20, 33: 21, 34: 22, 35: 23, 36: 24, 37: 25, 40: 26, 41: 27, 42: 28, 43: 29}[pin]}"
        tr(net, [(144.95, 118.3 - 0.4 * (pin - 31)), via], "F.Cu")
        tv(net, *via)
    west = {2: (138.95, 113.2), 3: (137.2, 113.45), 4: (138.95, 113.95), 5: (137.2, 114.2),
            7: (137.2, 115.2), 8: (138.95, 115.45), 9: (137.2, 115.95), 10: (138.95, 116.25),
            12: (137.2, 117.2), 13: (138.95, 117.5), 14: (137.2, 117.95), 15: (137.2, 118.7)}  # fmt: skip
    for pin, via in west.items():
        net = f"GP{ {2: 0, 3: 1, 4: 2, 5: 3, 7: 4, 8: 5, 9: 6, 10: 7, 12: 8, 13: 9, 14: 10, 15: 11}[pin]}"
        tr(net, [(138.05, 112.7 + 0.4 * (pin - 1)), via], "F.Cu")
        tv(net, *via)
    north = {"QSPI_SD1": ((139.1, 112.05), (139.1, 111.15)), "QSPI_SD0": ((139.9, 112.05), (139.9, 111.15)),
             "QSPI_SD3": ((140.7, 112.05), (140.7, 111.15)), "QSPI_SD2": ((139.5, 112.05), (139.75, 113.05)),
             "QSPI_SCLK": ((140.3, 112.05), (140.55, 113.05))}  # fmt: skip
    for net, (pad, via) in north.items():
        tr(net, [pad, via], "F.Cu")
        tv(net, *via)
    tr("QSPI_SS", [(138.7, 112.05), (138.7, 111.55), (138.5, 111.35), (138.5, 110.41), (139.6, 110.41)], "F.Cu")
    tr("XIN", [(140.7, 118.95), (140.7, 119.45), (140.4, 119.75)], "F.Cu")
    tv("XIN", 140.4, 119.75)
    tr("XIN", [(140.4, 119.75), (139.7, 119.75)], "B.Cu")
    tr("XOUT", [(141.1, 118.95), (141.0, 118.15)], "F.Cu")
    tv("XOUT", 141.0, 118.15)
    tr("XOUT", [(141.0, 118.15), (141.0, 118.85), (143.3, 118.85), (143.6, 119.15), (143.6, 119.75), (144.3, 120.39)],
       "B.Cu")
    tr("SWDIO", [(142.3, 118.95), (142.3, 117.95)], "F.Cu")
    tv("SWDIO", 142.3, 117.95)
    tr("VREG_LX", [(143.5, 112.05), (143.5, 111.0), (144.2, 110.3)], "F.Cu")
    tr("VREG_AVDD", [(144.3, 112.05), (144.3, 111.75), (149.8, 111.75), (149.8, 110.38), (148.7, 110.41)],
       "F.Cu", 0.25)
    tr("+3V3", [(148.7, 109.39), (148.7, 108.7)], "F.Cu", 0.25)  # R3's 3.3 V end to a via
    tv("+3V3", 148.7, 108.7)
    for pad, via in (((136.4, 113.02), (135.7, 113.0)), ((136.4, 117.02), (135.7, 117.0)),
                     ((146.6, 113.02), (147.3, 113.0)), ((146.6, 115.98), (147.3, 116.0)),
                     ((146.6, 117.98), (147.3, 118.0)), ((140.3, 118.95), (140.3, 117.95))):  # fmt: skip
        tr("+3V3", [pad, via], "F.Cu", 0.25)
        tv("+3V3", *via)
    tr("GND", [(143.9, 112.05), (143.9, 112.8), (143.3, 113.4), (143.1, 113.9)], "F.Cu", 0.25)
    for cap, x in (("C12", 135.7), ("C18", 135.7), ("C13", 135.7), ("C15", 147.3), ("C14", 147.3), ("C16", 147.3)):
        y = {"C12": 113.98, "C18": 115.98, "C13": 117.98, "C15": 113.98, "C14": 115.02, "C16": 117.02}[cap]
        tr("GND", [(136.4 if x < 140 else 146.6, y), (x, y)], "F.Cu", 0.25)
        tv("GND", x, y)
    for pad, via in (((143.0, 109.42), (143.0, 108.75)), ((149.8, 109.42), (149.8, 108.75))):
        tr("GND", [pad, via], "F.Cu", 0.25)
        tv("GND", *via)


# ---- the module's fan-out ----------------------------------------------------------------------
HAND_PADS = {"A8", "A9", "B10", "B11"}  # the SuperSpeed lane leaves on the top layer by hand (`usb_lane`)


def module_fanout(d: kicadgen.Design, module_nets: dict[str, str]) -> int:
    """A via beside every module pad the board uses, in the middle of the 4 pads round it.

    The pads are 0.80 mm on a 1.25 mm grid: between 2 pads there is room for no via, but the middle
    of 4 is 0.88 mm from each, room for a 0.51 mm via 0.23 mm clear of all of them. Each used pad
    takes the first of its 4 diagonal spots that is free: ground pads drop to the planes, the 5 V pads
    to the 5 V plane on In3, and the signals to the inner layers, where the router takes them out
    from under the module. Signals go first, toward the module's nearest edge."""
    boxes = d.pad_boxes()
    taken: set[tuple[float, float]] = set()
    order = sorted(module_nets, key=lambda p: (module_nets[p] in ("GND", "+5V"), p))
    placed = 0
    for pad in order:
        if pad in HAND_PADS:
            continue
        net = module_nets[pad]
        px, py = osm_l.pad_xy(pad)
        h = osm_l.PITCH / 2
        sx = 1 if px > 0 else -1
        sy = 1 if py > 0 else -1
        spots = [(px + sx * h, py + sy * h), (px + sx * h, py - sy * h), (px - sx * h, py + sy * h),
                 (px - sx * h, py - sy * h)]  # fmt: skip
        for lx, ly in spots:
            key = (round(lx, 3), round(ly, 3))
            if key in taken or abs(lx) > osm_l.SIZE / 2 - 0.4 or abs(ly) > osm_l.SIZE / 2 - 0.4:
                continue
            bx, by = round(MODULE[0] + ly, 3), round(MODULE[1] - lx, 3)
            if not d._via_fits(bx, by, 0.255, 0.2, d.pcb_net_name(net), boxes):
                continue
            taken.add(key)
            d.track(net, [mod_pad(pad), (bx, by)], "F.Cu", width=0.2)
            hand_via(d, net, bx, by)
            placed += 1
            break
    return placed


# ---- the schematic: blocks the way the signal flows, each IC with its own parts ------------------
BLOCKS = [
    ("USB-C: the plug's CC, the SuperSpeed lane's mux", ["J1", "U2", "U9", "C45", "C46", "C47", "C48", "R36",
                                                         "R37", "R38", "D3", "R39"]),
    ("The QCS6490 module", ["U1", "C49", "C50", "C51", "R40", "R41", "R42", "R43", "SW1", "SW4", "SW5"]),
    ("USB-C to 5.0 V to 3.3 V", ["U3", "L1", "C30", "C31", "C32", "C33", "C34", "C35", "C36", "C37", "C38", "C39",
                                 "C40", "C41", "C42", "R45", "R30", "R31", "R32", "R33", "R34", "R35", "U4", "C43", "C44",
                                 "D1", "R44"]),
    ("RP2350", ["U5", "U6", "Y1", "L2", "C9", "C10", "R3", "C11", "C12", "C13", "C14", "C15", "C16", "C17", "C18",
                "C19", "R4", "C20", "C21", "R5", "R6", "R7", "R8", "R9", "SW2", "SW3", "D2", "R12", "TP1", "TP2",
                "U7", "U8", "R10", "R11", "C22"]),
    ("microSD", ["J4", "R18", "R19", "R20", "R21", "C23", "C24"]),
    ("The pins", ["J2", "J3"]),
]
SHEET_W = 450  # A0's width in 2.54 mm steps, less the margins


def lay_out_schematic(d: kicadgen.Design) -> None:
    """Each block's ICs and connectors in a row, its small parts in rows of 6 under them; blocks flow
    left to right and wrap. A net inside 1 block is drawn as a wire, a net between blocks as a label."""
    g = 2.54
    parts = {p.ref: p for p in d.parts}
    block_of: dict[str, str] = {}
    x0, y0, row_h = 8, 10, 0
    for name, refs in BLOCKS:
        big = [r for r in refs if not (r[0] in "RCDLY" or r.startswith(("SW", "TP", "TH")))]
        small = [r for r in refs if r not in big]
        sizes = []
        for ref in big:
            p = parts[ref]
            xs = [pin.x for pin in p.symbol.pins] or [0]
            ys = [pin.y for pin in p.symbol.pins] or [0]
            sizes.append((round((max(xs) - min(xs)) / g) + 16, round((max(ys) - min(ys)) / g) + 8))
        width = max(sum(w for w, _ in sizes), 6 * 9) + 6
        height = (max((h for _, h in sizes), default=0)) + 8 * ((len(small) + 5) // 6) + 10
        if x0 + width > SHEET_W:
            x0, y0, row_h = 8, y0 + row_h, 0
        x = x0
        for ref, (w, h) in zip(big, sizes, strict=True):
            p = parts[ref]
            xs = [pin.x for pin in p.symbol.pins] or [0]
            ys = [pin.y for pin in p.symbol.pins] or [0]
            # The symbol's own centre, not its origin: the module's banks hang right of and below theirs.
            ox = (max(xs) + min(xs)) / 2
            oy = -(max(ys) + min(ys)) / 2
            p.sch_at = (round((x + w / 2) * g - ox, 2) // g * g, round((y0 + h / 2) * g - oy, 2) // g * g)
            p.sch_rot = 0
            x += w
            block_of[ref] = name
        sy = y0 + (max((h for _, h in sizes), default=0)) + 4
        for k, ref in enumerate(small):
            p = parts[ref]
            p.sch_at = ((x0 + 4 + 9 * (k % 6)) * g, (sy + 8 * (k // 6)) * g)
            p.sch_rot = 0
            block_of[ref] = name
        x0 += width
        row_h = max(row_h, height)
    missing = [r for r in parts if r not in block_of]
    if missing:
        raise ValueError(f"no block for {missing}")
    blocks_of_net: dict[str, set[str]] = {}
    for p in d.parts:
        for net in p.nets.values():
            blocks_of_net.setdefault(net, set()).add(block_of[p.ref])
    d.sch_label_nets = tuple(sorted(n for n, b in blocks_of_net.items() if len(b) > 1 and n not in d.power_nets))
    d.sch_wires = True


class WyvernDesign(kicadgen.Design):
    """The generator's Design with the board's colours in its stackup: black masks, white legends and
    an ENIG finish, as Hush's design writes them (examples/anc-speaker). The renders read them, and
    the fab's job file names them for the order."""

    @staticmethod
    def _stackup(copper: list[str], thickness: float = 1.6) -> list:
        Q = kicadgen.Q
        out = kicadgen.Design._stackup(copper, thickness)
        black = "#0B0B0CF2"  # 95 % opaque: under KiCad's named "Black" the pour renders brown
        colours = {"F.SilkS": "White", "B.SilkS": "White", "F.Mask": black, "B.Mask": black}
        for item in out[1:]:
            if item[0] == "layer" and item[1] in colours:
                item.insert(3, ["color", Q(colours[item[1]])])
            if item[0] == "copper_finish":
                item[1] = Q("ENIG")
        return out


# The 5 V plane on In3: from the buck-boost's output along the bottom, under the module's 5 V pads
# (the Y row up its middle and AE4 to AK4 at its lower right) and its 2 bulk capacitors underneath.
PLANE_5V = [(102.0, 141.6), (153.6, 141.6), (153.6, 112.6), (168.6, 112.6), (168.6, 117.6), (157.0, 117.6),
            (157.0, 136.4), (168.6, 136.4), (168.6, 150.4), (102.0, 150.4)]  # fmt: skip


def build() -> kicadgen.Design:
    d = WyvernDesign(
        name="wyvern",
        namespace=uuid.UUID("3f2b8c4e-91d7-4a6e-b5c2-7e0d4f1a9c63"),
        outline=(LEFT, TOP, RIGHT, BOTTOM),
        sheet="A0",
        copper_layers=6,
        plane_layers=("In1.Cu", "In4.Cu"),
        corner_radius=0.6,  # as far as the corner pins' square pads allow
        track_width=0.127,  # 5 mil: the router needs the room round the RP2350 and under the module
        clearance=0.11,
        # 0.2 mm copper to an edge or a hole: the USB-C receptacle's rear shell slot and its locating peg
        # are 0.375 mm apart, so a 6 mil ring leaves 0.22 mm, under the workcenter's 0.3 mm default.
        edge_clearance=0.2,
        via_size=0.51,  # Sierra's 6 mil ring on a 0.2 mm hole
        via_drill=0.2,
    )
    d.fab = "sierra-circuits-web"
    d.rules = {"min_through_hole_diameter": 0.2, "min_hole_clearance": 0.2, "min_text_height": 0.6,
               "min_text_thickness": 0.13}
    d.symbol_dirs = {"Wyvern": HERE / "symbols" / "wyvern.kicad_sym"}
    d.footprint_dirs = {"Wyvern": HERE / "footprints" / "wyvern.pretty"}
    d.power_nets = {
        "GND": "GND",
        "VBUS": "VBUS",
        "+5V": "+5V",
        "+3V3": "+3V3",
        "+1V8": "+1V8",
        "SD_VDD": "VDD",
        "SD_VIO": "VDDA",
        "+1V1": "+1V1",
        "VREG_AVDD": "+3.3VA",
    }
    # No power output drives these: VBUS and GND come in on J1, the RP2350's 1.1 V core out of L2,
    # VREG_AVDD through R3.
    d.flagged_nets = ["GND", "VBUS", "+1V1", "VREG_AVDD"]
    d.net_classes = {
        "power": {"width": 0.6, "clearance": 0.15, "via": 0.65, "via_drill": 0.3,
                  "nets": ["VBUS", "+5V", "BB_SW1", "BB_SW2"]},
        "rail": {"width": 0.3, "clearance": 0.12, "via": 0.51, "via_drill": 0.2,
                 "nets": ["+3V3", "+1V8", "SD_VDD", "SD_VIO", "+1V1", "VREG_LX"]},
        "pairs": {"width": PAIR_W, "clearance": 0.15, "via": 0.51, "via_drill": 0.2,
                  "nets": [f"{p}_{s}" for p in DIFF for s in "PN"]},
    }  # fmt: skip
    d.zone("GND", layers=("In1.Cu", "In4.Cu"), connect="solid")
    d.zone("GND", layers=("F.Cu", "B.Cu"), connect="solid")
    d.zone("+5V", layers=("In3.Cu",), polygon=PLANE_5V, connect="solid")

    grid = iter(range(10_000))

    def sch() -> tuple[float, float]:
        k = next(grid)
        return (25.4 + 25.4 * (k % 24), 25.4 + 25.4 * (k // 24))

    def add(ref, lib, value, fp, at, nets, rot=0.0, layer="F.Cu"):
        return d.add(ref, lib, value, fp, sch_at=sch(), pcb_at=at, pcb_rot=rot, pcb_layer=layer, nets=nets)

    def r(ref, value, a, b, at, rot=0.0, layer="F.Cu", fp=R0402):
        return add(ref, "Device:R", value, fp, at, {"1": a, "2": b}, rot, layer)

    def c(ref, value, a, at, rot=0.0, layer="F.Cu", b="GND", fp=C0402):
        return add(ref, "Device:C", value, fp, at, {"1": a, "2": b}, rot, layer)

    # ---- the module (U1) ---------------------------------------------------------------------------
    module_nets = {p: MODULE_NETS[osm_l.name(p)] for p in osm_l.PADS if osm_l.name(p) in MODULE_NETS}
    add("U1", "Wyvern:VOSM6490", "VOSM6490", "Wyvern:OSM_L_LGA-662_45x45mm_P1.25mm", MODULE, module_nets,
        MODULE_ROT)
    c("C49", "1u", "+1V8", (148.6, 126.67), 90, B)  # VCC_OUT_IO (U18), under the module's middle
    c("C50", "22u", "+5V", (164.6, 115.0), 0, B, fp=C0805)
    c("C51", "22u", "+5V", (164.6, 139.0), 0, B, fp=C0805)
    # The module's I2C buses pulled up to its own 1.8 V, under it.
    r("R40", "2.2k", "SOM_I2C_SDA", "+1V8", (158.4, 130.2), 90, B)
    r("R41", "2.2k", "SOM_I2C_SCL", "+1V8", (159.6, 130.2), 90, B)
    r("R42", "2.2k", "SOM_I2C2_SDA", "+1V8", (166.0, 108.2), 0, B)
    r("R43", "2.2k", "SOM_I2C2_SCL", "+1V8", (166.0, 109.4), 0, B)

    # ---- USB-C (J1), its CC controller and SuperSpeed mux (U2), the USB 2 clamp (U9) ----------------
    add("J1", "Connector:USB_C_Receptacle", "12401610E4#2A", USBC, USB_C_AT, USB_C, rot=270)
    add("U2", "Wyvern:HD3SS3220", "HD3SS3220",
        "Package_DFN_QFN:Texas_RNH0030A_WQFN-30-1EP_2.5x4.5mm_P0.4mm_EP1.2x3.2mm", (115.5, UY),
        {"30": "+5V", "8": "+3V3", "6": "SS_TX_P", "7": "SS_TX_N", "9": "SS_RX_P", "10": "SS_RX_N",
         "5": "HD_VBUS_DET", "4": "GND", "29": "GND", "12": "GND",
         "2": "USB_CC1", "1": "USB_CC2", "17": "SS_TX1_P", "16": "SS_TX1_N", "15": "SS_RX1_P", "14": "SS_RX1_N",
         "21": "SS_TX2_P", "20": "SS_TX2_N", "19": "SS_RX2_P", "18": "SS_RX2_N", "11": "HD_DIR",
         "26": "LED_3A", "13": "GND", "28": "GND", "31": "GND"}, 180)  # fmt: skip
    c("C45", "100n", "+5V", (116.6, 139.7), 0)  # VDD5 (30)
    c("C46", "100n", "+3V3", (119.3, 134.45), 0, B)  # VCC33 (8), under, from its via
    # The module's transmit pair is AC coupled here, on the way to the mux (TI: 100 nF on TX only).
    c("C47", "100n", "SS_TX_P", (125.3, 137.7), 0, b="SS_TXC_P")
    c("C48", "100n", "SS_TX_N", (125.3, 136.7), 0, b="SS_TXC_N")
    r("R36", "910k", "VBUS", "HD_VBUS_DET", (119.6, 137.6), 90, B)  # TI's 900k to VBUS_DET
    r("R37", "200k", "HD_DIR", "+3V3", (116.6, 131.9), 0)  # DIR is open drain and needs its pull-up
    r("R38", "10k", "VBUS", "SOM_VBUS_DET", (128.6, 140.4), 0)  # the module's own VBUS sense (C9)
    add("U9", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6", (114.4, 129.6),
        {"1": "USB_D_P", "6": "USB_D_P", "3": "USB_D_N", "4": "USB_D_N", "2": "GND", "5": "VBUS"}, 0)  # fmt: skip

    # ---- power: USB-C VBUS to the module's 5.0 V (U3), 5.0 V to 3.3 V (U4) ---------------------------
    # U3 turned so its input and output leave west to their capacitors and its 2 switch nodes east to
    # the inductor: VIN's pad north of VOUT's, the capacitors' grounds between them on PGND's end.
    add("U3", "Wyvern:TPS552892", "TPS552892", "Wyvern:Texas_RYQ0021A_VQFN-HR-21_5x3mm_P0.5mm", (112.0, 145.0),
        {"7": "VBUS", "1": "BB_EN", "2": "BB_VCC", "5": "GND", "6": "BB_FSW", "18": "BB_VCC", "17": "GND",
         "11": "+5V", "8": "BB_SW1", "20": "BB_BOOT1", "10": "BB_SW2", "19": "BB_BOOT2", "12": "+5V", "13": "+5V",
         "14": "BB_FB", "15": "BB_COMP", "9": "GND"}, 270)  # fmt: skip
    add("L1", "Device:L", "2.2u XAL6030-222", "Inductor_SMD:L_Coilcraft_XAL6030-XXX", (120.2, 145.0),
        {"1": "BB_SW1", "2": "BB_SW2"}, 270)  # fmt: skip
    # MODE (2) high: forced PWM, the switching at 746 kHz at every load, clear of the cable's resonance
    # (sim/frequency-plan.json). In FPWM the converter can return current to its input when something
    # holds its output above 5.0 V, so the 5V pin is VBUS, before it, and nothing outside reaches +5V.
    c("C30", "10u", "VBUS", (106.3, 142.5), 180, fp=C0805)
    c("C31", "10u", "VBUS", (106.3, 144.5), 180, fp=C0805)
    c("C32", "100n", "VBUS", (108.55, 143.5), 90)
    # A damper across VBUS: the cable's inductance and C30, C31 peak at 2.2 Ohm without it, above the
    # converter's input resistance; C42 and R45 hold the peak under 0.5 Ohm (sim/vbus_pdn.cir).
    c("C42", "22u", "VBUS", (102.6, 142.5), 180, b="BB_DAMP", fp=C0805)
    r("R45", "0.33", "BB_DAMP", "GND", (102.6, 144.4), 0)
    for k, (x, y) in enumerate(((106.3, 146.5), (106.3, 148.5), (102.6, 146.5), (102.6, 148.5))):
        c(f"C{33 + k}", "22u", "+5V", (x, y), 180 if x > 105 else 0, fp=C0805)
    c("C37", "100n", "+5V", (108.55, 146.5), 270)
    c("C38", "100n", "BB_BOOT1", (115.6, 141.7), 0, b="BB_SW1")
    c("C39", "100n", "BB_BOOT2", (115.6, 148.4), 0, b="BB_SW2")
    c("C40", "4.7u", "BB_VCC", (113.9, 149.4), 270)
    # VOUT = 1.2 V x (1 + R30/R31) = 4.997 V: in the module's 4.8 to 5.2 V at every corner (sim/sys_rail.cir).
    r("R30", "100k", "+5V", "BB_FB", (109.4, 149.4), 90)
    r("R31", "31.6k", "BB_FB", "GND", (110.4, 149.4), 270)
    r("R32", "4.7k", "BB_COMP", "BB_COMP_RC", (111.9, 149.4), 270)
    c("C41", "10n", "BB_COMP_RC", (112.9, 149.4), 90)
    # fSW = 1000 / (0.05 x 26.1k + 35) MHz = 746 kHz (datasheet, equation 3).
    r("R33", "26.1k", "GND", "BB_FSW", (109.1, 141.7), 0)  # FSW's end east, toward U3's pin 6
    # EN/UVLO: on above 1.23 V x (1 + 100k/51k) = 3.64 V of VBUS, 3.51 to 3.78 V over VUVLO's spread
    # and the resistors' 1 %
    # (sim/vbus_uvlo_low.cir, vbus_uvlo_high.cir).
    r("R34", "100k", "VBUS", "BB_EN", (119.0, 140.2), 0)
    r("R35", "51k", "BB_EN", "GND", (121.0, 140.2), 0)
    add("U4", "Regulator_Linear:AP2112K-3.3", "AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5", (124.4, 128.4),
        {"1": "+5V", "2": "GND", "3": "+5V", "5": "+3V3"}, 0)  # fmt: skip
    c("C43", "1u", "+5V", (121.6, 128.4), 90)
    c("C44", "1u", "+3V3", (127.0, 128.4), 90)

    # ---- the RP2350 (U5), its flash (U6), crystal (Y1) and core regulator: v0.1's block, turned -----
    def tadd(ref, lib, value, fp, at, nets, rot=0.0, layer="F.Cu"):
        return add(ref, lib, value, fp, T(*at), nets, TR(rot), layer)

    def tr_(ref, value, a, b_, at, rot=0.0, layer="F.Cu", fp=R0402):
        return tadd(ref, "Device:R", value, fp, at, {"1": a, "2": b_}, rot, layer)

    def tc(ref, value, a, at, rot=0.0, layer="F.Cu", b_="GND", fp=C0402):
        return tadd(ref, "Device:C", value, fp, at, {"1": a, "2": b_}, rot, layer)

    rp = {
        "1": "+3V3", "11": "+3V3", "20": "+3V3", "30": "+3V3", "38": "+3V3", "45": "+3V3",
        "6": "+1V1", "23": "+1V1", "39": "+1V1", "44": "+3V3", "53": "+3V3", "54": "+3V3",
        "46": "VREG_AVDD", "47": "GND", "48": "VREG_LX", "49": "+3V3", "50": "+1V1", "61": "GND",
        "21": "XIN", "22": "XOUT", "24": "SWCLK", "25": "SWDIO", "26": "MCU_RUN",
        "51": "MCU_DM", "52": "MCU_DP",
        "55": "QSPI_SD3", "56": "QSPI_SCLK", "57": "QSPI_SD0", "58": "QSPI_SD2", "59": "QSPI_SD1", "60": "QSPI_SS",
    }  # fmt: skip
    gpio_pin = {0: 2, 1: 3, 2: 4, 3: 5, 4: 7, 5: 8, 6: 9, 7: 10, 8: 12, 9: 13, 10: 14, 11: 15, 12: 16, 13: 17,
                14: 18, 15: 19, 16: 27, 17: 28, 18: 29, 19: 31, 20: 32, 21: 33, 22: 34, 23: 35, 24: 36, 25: 37,
                26: 40, 27: 41, 28: 42, 29: 43}  # fmt: skip
    rp |= {str(p): f"GP{g}" for g, p in gpio_pin.items()}
    tadd("U5", "MCU_RaspberryPi:RP2350A", "RP2350A", "Package_DFN_QFN:QFN-60-1EP_7x7mm_P0.4mm_EP3.4x3.4mm",
         V1_MCU, rp)
    ny = 109.9
    tadd("L2", "Device:L", "3.3u AOTA-B201610S3R3", "Inductor_SMD:L_Abracon_AOTA-B201610S", (145.2, ny),
         {"1": "VREG_LX", "2": "+1V1"}, 0)  # fmt: skip
    tc("C9", "4.7u", "+3V3", (143.0, ny), 90)
    tc("C10", "4.7u", "+1V1", (147.6, ny), 90)
    tr_("R3", "33", "+3V3", "VREG_AVDD", (148.7, ny), 270)
    tc("C11", "4.7u", "VREG_AVDD", (149.8, ny), 90)
    tr_("R6", "27", "MCU_DP", "MCU_USB_P", (141.8, ny), 90)
    tr_("R7", "27", "MCU_DM", "MCU_USB_N", (140.7, ny), 90)
    tr_("R4", "10k", "QSPI_SS", "+3V3", (139.6, ny), 90)
    tr_("R9", "1k", "QSPI_SS", "BOOT_R", (138.5, ny), 90)
    mx, my = V1_MCU
    tc("C12", "100n", "+3V3", (mx - 5.1, my - 2.0), 270)
    tc("C18", "100n", "+1V1", (mx - 5.1, my + 0.0), 270)
    tc("C13", "100n", "+3V3", (mx - 5.1, my + 2.0), 270)
    tc("C14", "100n", "+3V3", (mx + 5.1, my + 0.0), 90)
    tc("C15", "100n", "+3V3", (mx + 5.1, my - 2.0), 270)
    tc("C16", "100n", "+3V3", (mx + 5.1, my + 2.0), 90)
    tadd("U6", "Memory_Flash:W25Q128JVP", "W25Q128JV", "Package_SON:WSON-8-1EP_6x5mm_P1.27mm_EP3.4x4.3mm",
         (132.3, 113.0),
         {"1": "QSPI_SS", "2": "QSPI_SD1", "3": "QSPI_SD2", "4": "GND", "5": "QSPI_SD0", "6": "QSPI_SCLK",
          "7": "QSPI_SD3", "8": "+3V3", "9": "GND"}, 90)  # fmt: skip
    tc("C19", "100n", "+3V3", (132.3, 117.0))
    tadd("Y1", "Device:Crystal_GND24", "12MHz ABM8-272-T3", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
         (140.4, 120.9), {"1": "XIN", "2": "GND", "3": "XTAL_O", "4": "GND"}, 0, B)  # fmt: skip
    tc("C20", "15p", "XIN", (137.6, 120.9), 90, B)
    tc("C21", "15p", "XTAL_O", (143.2, 120.9), 90, B)
    tr_("R5", "1k", "XTAL_O", "XOUT", (144.3, 120.9), 90, B)
    tc("C17", "100n", "+3V3", (136.2, 120.9), 90)
    tr_("R8", "10k", "MCU_RUN", "+3V3", (145.7, 121.9), 90)
    tadd("TP1", "Connector:TestPoint", "SWCLK", TP, (135.6, 108.0), {"1": "SWCLK"}, 0, B)
    tadd("TP2", "Connector:TestPoint", "SWDIO", TP, (137.6, 108.0), {"1": "SWDIO"}, 0, B)
    # The Snapdragon's 2 GPIOs (1.8 V) pull RUN and QSPI_SS low through open-drain buffers on its own
    # 1.8 V: each output stands 3.3 V, and each input has 100k to ground while the module is off.
    add("U7", "74xGxx:74LVC1G07", "74LVC1G07", SOT353, (122.0, 120.4),
        {"2": "MCU_RUN_CTL", "3": "GND", "4": "MCU_RUN", "5": "+1V8"}, 0)  # fmt: skip
    add("U8", "74xGxx:74LVC1G07", "74LVC1G07", SOT353, (125.6, 120.4),
        {"2": "MCU_BOOT_CTL", "3": "GND", "4": "BOOT_R", "5": "+1V8"}, 0)  # fmt: skip
    r("R10", "100k", "MCU_RUN_CTL", "GND", (122.0, 122.6), 0)
    r("R11", "100k", "MCU_BOOT_CTL", "GND", (125.6, 122.6), 0)
    c("C22", "100n", "+1V8", (127.8, 120.4), 90)

    # ---- the buttons along the USB-C end, and the 3 lights ---------------------------------------
    for k, (ref, name, a, b_) in enumerate((("SW2", "BOOT", "BOOT_R", "GND"), ("SW3", "RUN", "MCU_RUN", "GND"),
                                            ("SW1", "PWR", "SOM_PWR_N", "GND"), ("SW4", "RST", "SOM_RST_N", "GND"),
                                            ("SW5", "REC", "SOM_REC_N", "GND"))):  # fmt: skip
        add(ref, "Switch:SW_Push", name, BUTTON, (102.6, 105.1 + 5.6 * k), {"1": a, "2": b_}, 90)
    # The 3 lights in a row clear of the buttons' names; each anode faces its resistor straight below.
    for ref, rref, net, colour, src, rv, x in (("D1", "R44", "LED_PWR", "red", "+3V3", "1k", 107.7),
                                               ("D2", "R12", "LED_GP25", "green", "GP25", "1k", 109.5),
                                               ("D3", "R39", "LED_3A", "blue", "+5V", "2.2k", 111.3)):  # fmt: skip
        if ref == "D3":  # the mux's OUT2 sinks it when the charger offers 3 A
            add(ref, "Device:LED", colour, LED0603, (x, 126.3), {"1": "LED_3A", "2": "LED_3A_A"}, 270)
            r(rref, rv, "LED_3A_A", src, (x, 129.4), 270)
            d.track("LED_3A_A", [(x, 127.09), (x, 128.89)], "F.Cu", width=0.2)
        else:
            add(ref, "Device:LED", colour, LED0603, (x, 126.3), {"1": "GND", "2": net}, 270)
            r(rref, rv, net, src, (x, 129.4), 270)
            d.track(net, [(x, 127.09), (x, 128.89)], "F.Cu", width=0.2)

    # ---- the microSD slot (J4) under the far end; the card stands out past the right edge --------
    add("J4", "Connector:Micro_SD_Card_Det2", "104031-0811", "Connector_Card:microSD_HC_Molex_104031-0811",
        (RIGHT - 6.96, CY), {"1": "SD_D2", "2": "SD_D3", "3": "SD_CMD", "4": "SD_VDD", "5": "SD_CLK", "6": "GND",
                             "7": "SD_D0", "8": "SD_D1", "9": "SD_DET_N", "10": "GND", "SH": "GND"}, 90, B)  # fmt: skip
    for k, net in enumerate(("SD_D0", "SD_D1", "SD_D2", "SD_D3")):
        r(f"R{18 + k}", "47k", net, "SD_VIO", (158.6 + 1.2 * k, 121.0), 90, B)
    c("C23", "4.7u", "SD_VDD", (160.0, 133.4), 0, B, fp=C0603)
    c("C24", "100n", "SD_VIO", (160.0, 135.0), 0, B)

    # ---- the pins: 2 rows of 30, headers underneath ---------------------------------------------
    add("J2", "Connector_Generic:Conn_01x30", "1x30 header", HEADER, (pin_x(0), ROW_TOP),
        {str(k + 1): PIN_NET[name] for k, name in enumerate(TOP_PINS)}, 270, B)  # fmt: skip
    add("J3", "Connector_Generic:Conn_01x30", "1x30 header", HEADER, (pin_x(0), ROW_BOTTOM),
        {str(k + 1): PIN_NET[name] for k, name in enumerate(BOTTOM_PINS)}, 270, B)  # fmt: skip

    # ---- the words: each pin named on the back, under its pad, the way a Teensy's pinout card reads;
    # the buttons named on the front; the board's name on both faces.
    for row, y in ((TOP_PINS, 103.55), (BOTTOM_PINS, 149.8)):
        for k, name in enumerate(row):
            d.text(name, pin_x(k), y, "B.SilkS", 0.6, 0.13)
    for k, name in enumerate(("BOOT", "RUN", "PWR", "RST", "REC")):
        d.text(name, 105.6, 105.1 + 5.6 * k, "F.SilkS", 0.6, 0.13)
    # The Snapdragon's pins (20 to 29 of each row) are 1.8 V: said under their names.
    mid = (pin_x(19) + pin_x(28)) / 2
    for y in (105.0, 148.35):
        d.text("1.8 V ONLY", mid, y, "B.SilkS", 0.8, 0.15)
    # The name on the back, in the patch under the module that no pad of it reaches (an OSM cut-out area).
    d.text("WYVERN", 145.2, 114.6, "B.SilkS", 2.0, 0.3)
    d.text("QCS6490 + RP2350", 145.2, 117.3, "B.SilkS", 0.8, 0.15)
    d.text("v0.2", 145.2, 119.0, "B.SilkS", 0.6, 0.13)
    # And on the top face, in the strip between the RP2350's parts and the module.
    d.text("WYVERN", 125.0, 108.0, "F.SilkS", 1.5, 0.25)
    d.text("v0.2", 125.0, 110.1, "F.SilkS", 0.8, 0.15)

    d.defined_nets = {
        "SOM_PWR_N": "the module's power key, pulled up to its 1.8 V on the module (PU 10K, VOSM6490 pin table)",
        "SOM_RST_N": "the module's reset key, pulled up on the module (PU 10K)",
        "SOM_REC_N": "the module's forced USB boot, pulled up on the module (PU 10K)",
        "MCU_RUN": "R8 (10k) to +3V3, and the RP2350's own pull-up on RUN (datasheet, pin list)",
        "QSPI_SS": "R4 (10k) to +3V3, and the RP2350's own pull-up on QSPI_SS (datasheet, pin list)",
        "BOOT_R": "R9 (1k) to QSPI_SS, which R4 holds at +3V3",
        "XIN": "the crystal Y1 and C20; the RP2350's oscillator drives the pair",
        "SWCLK": "the RP2350's own pull-up on SWCLK",
        "SWDIO": "the RP2350's own pull-up on SWDIO",
        "SD_CLK": "the QCS6490 drives SDC2_CLK; the card's supply (VREG_L9C) is off whenever the SoC is",
        "SD_CMD": "the module's own pull-up on SDC2_CMD (PU 10K, VOSM6490 pin table)",
        "SD_DET_N": "the module's own pull-up on SD_CARD_DET_N (PU 10K)",
        "BB_EN": "R34 and R35 from VBUS: on from 3.51 to 3.78 V up (sim/vbus_uvlo_low.cir, vbus_uvlo_high.cir)",
        "SOM_RTC": "the pin for a 3 V coin cell; the module's RTC runs from its own supply without one",
        "HD_VBUS_DET": "R36 (910k) from VBUS, as TI's HD3SS3220 design asks",
    }
    for i in range(30):
        d.defined_nets[f"GP{i}"] = "a pin of the RP2350 on the header; firmware sets it"
    for net in ("SOM_UART_RX", "SOM_SPI_SDI", "SOM_GPIO3", "SOM_GPIO4"):
        d.defined_nets[net] = "a pin of the QCS6490 on the header at 1.8 V; Linux sets it"
    d.check_pulls = True
    core_rail(d)
    power_stage(d)
    usb_lane(d)
    five_volt_spine(d)
    fanned = module_fanout(d, module_nets)
    five_volt_stubs(d)
    print(f"module fan-out: {fanned} vias for {len(module_nets) - len(HAND_PADS)} pads")
    # 3D bodies for the parts KiCad's 3D library has none for (models/make_models.py).
    d.model("U1", "${KIPRJMOD}/models/vosm6490.wrl", replace=True)
    d.model("U5", "${KIPRJMOD}/models/rp2350_qfn60.wrl", replace=True)
    d.model("U3", "${KIPRJMOD}/models/tps552892_ryq21.wrl", replace=True)
    d.model("U2", "${KIPRJMOD}/models/hd3ss3220_rnh30.wrl", replace=True)
    d.model("J4", "${KIPRJMOD}/models/microsd_104031.wrl", replace=True)
    for part in d.parts:
        part.hide_ref = True
    lay_out_schematic(d)
    return d
