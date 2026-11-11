"""Wyvern v0.1: a Snapdragon 845 development board in a stick 61 x 30.5 mm, laid out like a Teensy.

A Snapdragon cannot sit on a board this size by itself: it needs LPDDR4X, flash and 3 PMICs round
it on a high-density board. Lantronix sells all of that as the Open-Q 845 uSOM, 50 x 25 mm, on 3
Hirose DF40 100-pin connectors, with its pinout and land pattern in a public datasheet
(`open_q_845.py`). Wyvern is the carrier: the module sits on top on 3 mm receptacles, and the board
round it gives it what a Teensy gives its MCU.

- USB-C (J4, a 24-pin receptacle) carries the SOM's USB 3.1 port and its DisplayPort alternate mode:
  4 SuperSpeed pairs and the USB 2 pair, drawn here by hand as coupled 90-ohm pairs on the outer
  layers over ground (`usb_pairs`).
- 5 V from USB-C or the 5V pin: a TPS62130 buck (U2) makes the SOM's 3.8 V supply, up to 3 A for
  the 8.7 W the module draws while it boots. An AP2112K (U3) makes 3.3 V from it.
- An RP2350 (U4) owns the 0.1-inch pins at 3.3 V, the way a Teensy's MCU does: 30 GPIO, 4 of them
  analog. It talks to the Snapdragon over the SOM's second USB port, and the Snapdragon can reset it
  and put it in its bootloader through 2 open-drain buffers (U6, U7): Linux flashes it.
- The Snapdragon's own 1.8 V I2C, debug UART, power key and reset are on the pins too, apart.
- A microSD slot (J7) on the SOM's SD card interface, under the far end like a Teensy 4.1's.

    workcenter design design.py --route     # from this folder

Board: 60.96 x 30.48 mm, 6 layers, 1.6 mm: F.Cu signal, In1.Cu ground, In2.Cu and In3.Cu signal and
power, In4.Cu ground, B.Cu signal. Every outer-layer pair has a ground plane right under it. The pins
are 2 rows of 24 on a 0.1-inch grid, 1.1 inch apart; the headers sit underneath, pins down.
"""

from __future__ import annotations

import math
import sys
import uuid
from pathlib import Path

import kicadgen

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import open_q_845 as som  # noqa: E402

# ---- the board ----------------------------------------------------------------------------------
LEFT, TOP = 100.0, 100.0
WIDTH, HEIGHT = 60.96, 30.48  # 2.4 x 1.2 inch
RIGHT, BOTTOM = LEFT + WIDTH, TOP + HEIGHT
CY = TOP + HEIGHT / 2  # 115.24
PITCH = 2.54
ROW_TOP = TOP + 1.27  # the pins' rows, 1.1 inch apart
ROW_BOTTOM = BOTTOM - 1.27


def pin_x(k: int) -> float:
    return round(LEFT + 1.27 + PITCH * k, 3)


# ---- the SOM: turned 180 degrees, so its power connector (JT2) sits next to USB-C ---------------
SOM_X0 = 110.1  # its left edge on the board: J4's courtyard ends here
SOM_Y0 = CY - som.SIZE[1] / 2  # its top edge


def som_at(sx: float, sy: float) -> tuple[float, float]:
    """A point given in the SOM's datasheet frame (Figure 7: from its lower left corner, y up), on the
    board. The SOM is turned 180 degrees, so its lower left corner lands at the board's lower right."""
    return (round(SOM_X0 + som.SIZE[0] - sx, 3), round(SOM_Y0 + sy, 3))


# Each receptacle: its centre, and its rotation. The datasheet puts JT1's and JT2's pin 1 at the upper
# right and JT3's at the lower left, seen from above; turned 180 degrees with the SOM, the first two
# land at the lower left, where KiCad's footprint has pad 1 at 0 degrees, and JT3 at 180.
SOCKETS = {"J1": ("JT1", 0.0), "J2": ("JT2", 0.0), "J3": ("JT3", 180.0)}


def socket_pad(ref: str, n: int) -> tuple[float, float]:
    """Where pad n of a SOM receptacle sits on the board (the footprint's pads: pitch 0.4, odd row at
    +1.54, pad 1 at x -9.8)."""
    jt, rot = SOCKETS[ref]
    cx, cy = som_at(*som.CENTRES[jt])
    fx, fy = -9.8 + 0.4 * ((n - 1) // 2), 1.54 if n % 2 else -1.54
    if rot == 180.0:
        fx, fy = -fx, -fy
    return (round(cx + fx, 3), round(cy + fy, 3))


# ---- footprints ---------------------------------------------------------------------------------
R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
LED0603 = "LED_SMD:LED_0603_1608Metric"
SOCKET = "Wyvern:Hirose_DF40HC(3.0)-100DS-0.4V_2x50_P0.4mm_SOM"
USBC = "Wyvern:USB_C_Receptacle_Amphenol_12401610E4-2A_Ring6mil"
HEADER = "Connector_PinHeader_2.54mm:PinHeader_1x24_P2.54mm_Vertical"
BUTTON = "Button_Switch_SMD:SW_Push_1P1T_NO_CK_KMR2"
SOT353 = "Package_TO_SOT_SMD:SOT-353_SC-70-5"
TP = "TestPoint:TestPoint_Pad_D1.0mm"
B = "B.Cu"

# ---- the pins, left to right; the top row is the one next to the SOM's JT1 and JT2 ----------------
TOP_PINS = ["GND", "5V", "3V3", "GND", "PWR", "RST", "1V8", "SDA", "SCL", "TX", "RX", "GND",
            "GP29", "GP28", "GP27", "GP26", "GP25", "GP24", "GP23", "GP22", "GP21", "GP20", "3V3", "GND"]  # fmt: skip
BOTTOM_PINS = ["GND"] + [f"GP{i}" for i in range(20)] + ["GND", "RUN", "GND"]
PIN_NET = {
    "GND": "GND", "5V": "VBUS", "3V3": "+3V3", "1V8": "+1V8", "PWR": "SOM_PWR_N", "RST": "SOM_RESIN_N",
    "SDA": "SOM_I2C_SDA", "SCL": "SOM_I2C_SCL", "TX": "SOM_UART_TX", "RX": "SOM_UART_RX", "RUN": "MCU_RUN",
} | {f"GP{i}": f"GP{i}" for i in range(30)}  # fmt: skip

# ---- what the board connects on each SOM connector; every other pin is left open ----------------
SOM_NETS = {
    "J1": {  # JT1
        "GND": "GND",
        "SDC2_DATA0": "SD_D0", "SDC2_DATA1": "SD_D1", "SDC2_DATA2": "SD_D2", "SDC2_DATA3": "SD_D3",
        "SDC2_CMD": "SD_CMD", "SDC2_CLK": "SD_CLK",
        "VREG_S4A_1P8": "+1V8",
        "CBL_PWR_N": "SOM_AUTO_ON",
        "PM_RESIN_VOLDN_N": "SOM_RESIN_N",
    },
    "J2": {  # JT2
        "GND": "GND", "SOM_SYS_PWR": "SOM_SYS", "USB_VBUS": "VBUS",
        "CS_P": "GND", "CS_N": "GND", "VBATT_CONN_VSENSE_P": "SOM_SYS", "VBATT_CONN_VSENSE_N": "GND",
        "AUX_THERM": "SOM_THERM", "PHONE_ON_N": "SOM_PWR_N",
        "USB_CC1": "USB_CC1", "USB_CC2": "USB_CC2", "USB_SBU_P": "USB_SBU_P", "USB_SBU_N": "USB_SBU_N",
        "RGB_RED": "LED_R", "RGB_GREEN": "LED_G", "RGB_BLUE": "LED_B",
        "GPIO126_SDC2_CARD_DET_N": "SD_DET_N", "GPIO57_FORCE_USB_BOOT": "SOM_EDL",
        "GPIO55_QUP10_0_I2C_SDA": "SOM_I2C_SDA", "GPIO56_QUP10_1_I2C_SCL": "SOM_I2C_SCL",
        "GPIO4_QUP9_2_DBG_UART_TX": "SOM_UART_TX", "GPIO5_QUP9_3_DBG_UART_RX": "SOM_UART_RX",
    },
    "J3": {  # JT3
        "GND": "GND",
        "VREG_L13A_2P95": "SD_VIO", "VREG_L21A_2P95": "SD_VDD",
        "GPIO27_CAM_ELDO3_EN": "MCU_RUN_CTL", "GPIO11_LCD_TE1": "MCU_BOOT_CTL",
        "USB2_HS_D_P": "MCU_USB_P", "USB2_HS_D_N": "MCU_USB_N",
        "USB3_HS_D_P": "USB_D_P", "USB3_HS_D_N": "USB_D_N",
        "USB3_SS_TX0_C_P": "SS_TX0_P", "USB3_SS_TX0_C_N": "SS_TX0_N",
        "USB3_SS_RX0_P": "SS_RX0_P", "USB3_SS_RX0_N": "SS_RX0_N",
        "USB3_SS_TX1_C_P": "SS_TX1_P", "USB3_SS_TX1_C_N": "SS_TX1_N",
        "USB3_SS_RX1_P": "SS_RX1_P", "USB3_SS_RX1_N": "SS_RX1_N",
    },
}  # fmt: skip

# USB-C, wired the way a plug turned over sees it: the SOM's lane 0 (TX0, RX0) on the receptacle's
# second pair of SuperSpeed pins (TX2, RX2) and its lane 1 on the first, with CC and SBU swapped to
# match. A plug in either orientation still meets the lane its CC pin selects, and every pair
# reaches its pins without crossing another on its layer (`usb_pairs`).
USB_C = {
    "A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS",
    "A1": "GND", "A12": "GND", "B1": "GND", "B12": "GND", "SH": "GND",
    "A5": "USB_CC2", "B5": "USB_CC1", "A8": "USB_SBU_N", "B8": "USB_SBU_P",
    "A6": "USB_D_P", "B6": "USB_D_P", "A7": "USB_D_N", "B7": "USB_D_N",
    "A2": "SS_TX1_P", "A3": "SS_TX1_N", "B11": "SS_RX1_P", "B10": "SS_RX1_N",
    "B2": "SS_TX0_P", "B3": "SS_TX0_N", "A11": "SS_RX0_P", "A10": "SS_RX0_N",
}  # fmt: skip
# The receptacle's front face is 5.23 mm in front of its footprint's origin (Amphenol's cut sheet:
# 9.59 mm from the face to its pegs, which the footprint puts at -4.36). It stands 1.0 mm past the
# edge, its front shell legs 0.7 mm inside it.
USB_C_AT = (LEFT - 1.0 + 5.23, CY)

DIFF = ("SS_TX0", "SS_TX1", "SS_RX0", "SS_RX1", "USB_D", "MCU_USB")
PAIR_W, PAIR_GAP = 0.25, 0.15  # 90 ohm on 0.21 mm of 7628 to the plane under it (IPC-2141): 0.4 mm pitch
NECK = 0.15  # a pair's width for the last mm between the receptacle's pads and the vias in front of them


def offset(points: list[tuple[float, float]], d: float) -> list[tuple[float, float]]:
    """A polyline moved `d` mm to the left of its direction of travel (board coordinates, y down, so
    heading west the left is south), its corners mitred: the 2 tracks of a pair from 1 centre line."""

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
        out.append((round(p[0] + d * nx, 4), round(p[1] + d * ny, 4)))
    return out


def pair(d, name: str, centre, layer: str, p_left: bool, p_end=(), n_end=(), p_start=(), n_start=()) -> None:
    """A coupled pair from its centre line, P on the left of travel or on the right, 0.4 mm apart. The
    stubs at each end, from a pad or a via to where the pair's own tracks begin, are drawn necked down."""
    half = (PAIR_W + PAIR_GAP) / 2
    p = offset(centre, half if p_left else -half)
    n = offset(centre, -half if p_left else half)
    d.track(f"{name}_P", p, layer)
    d.track(f"{name}_N", n, layer)
    for net, ends, points in ((f"{name}_P", (p_start, p_end), p), (f"{name}_N", (n_start, n_end), n)):
        if ends[0]:
            d.track(net, [*ends[0], points[0]], layer, width=NECK)
        if ends[1]:
            d.track(net, [points[-1], *ends[1]], layer, width=NECK)


def hand_via(d: kicadgen.Design, net: str, x: float, y: float) -> None:
    """A signal-size via (0.51 mm, 0.2 mm hole, Sierra's 6 mil ring) on any net, the supplies included."""
    d.via(net, x, y, size=0.51, drill=0.2)


def usb_pairs(d: kicadgen.Design) -> None:
    """The USB-C port's 4 SuperSpeed pairs and its USB 2 pair, by hand.

    JT3 puts the SOM's USB pins at its end nearest the receptacle, each pair beside a ground pin.
    The inner row's pairs leave towards the board's middle, the outer row's into the gap between the
    rows or south to vias; on the receptacle the A row is on the top layer, the B row reached through
    vias in front of it. The plug-turned-over wiring (`USB_C`) gives each layer 1 pair per side, so
    no 2 pairs on a layer cross. Each pair keeps P on the same side the whole way, so none is turned
    over: a USB 3 receiver can invert a pair, a DisplayPort lane need not.
    """
    vx = (106.75, 106.0)  # the 2 columns of vias in front of the receptacle's B row
    # The B row: each pad's stub to its via, alternate pads to alternate columns.
    for k, (pad, net) in enumerate([("B12", "GND"), ("B11", "SS_RX1_P"), ("B10", "SS_RX1_N"), ("B9", "VBUS"),
                                    ("B8", "USB_SBU_P"), ("B7", "USB_D_N"), ("B6", "USB_D_P"), ("B5", "USB_CC1"),
                                    ("B4", "VBUS"), ("B3", "SS_TX0_N"), ("B2", "SS_TX0_P"), ("B1", "GND")]):  # fmt: skip
        y = round(112.24 + 0.5 * k, 2)
        x = vx[0] if k % 2 else vx[1]
        d.track(net, [(107.55, y), (x, y)], "F.Cu", width=NECK)
        hand_via(d, net, x, y)
    # Each A-row ground and supply pad to the B-row pad beside it, between the rows.
    for (ya, yb), net in (((112.49, 112.24), "GND"), ((113.99, 113.74), "VBUS"), ((116.49, 116.24), "VBUS"),
                          ((117.99, 117.74), "GND")):  # fmt: skip
        d.track(net, [(109.25, ya), (108.9, ya), (107.9, yb), (107.55, yb)], "F.Cu", width=NECK)

    # SS_TX1, top layer: JT3's inner row into the gap between its rows, west, north beside the RP2350's
    # flash, west to A2 (P) and A3 (N).
    pair(d, "SS_TX1", [(130.5, 124.1), (130.5, 124.6), (130.1, 125.0), (127.4, 125.0), (127.0, 124.6),
                       (127.0, 113.64), (126.6, 113.24), (110.6, 113.24)], "F.Cu", p_left=False,
         p_end=[(109.25, 112.99)], n_end=[(109.25, 113.49)])  # fmt: skip
    # SS_RX0, top layer: JT3's outer row into the gap, west under the inner pair, north, west to A11 (P)
    # and A10 (N).
    pair(d, "SS_RX0", [(130.5, 127.18), (130.5, 126.35), (130.1, 125.95), (112.4, 125.95), (112.0, 125.55),
                       (112.0, 117.64), (111.6, 117.24), (110.6, 117.24)], "F.Cu", p_left=True,
         p_end=[(109.25, 117.49)], n_end=[(109.25, 116.99)])  # fmt: skip

    # SS_RX1, bottom layer: JT3's inner row north to a via each, then north-west and west to B11 (P)
    # and B10 (N).
    for net, pad, via in (("SS_RX1_P", (129.5, 124.1), (129.75, 122.95)), ("SS_RX1_N", (129.1, 124.1), (128.85, 123.05))):
        d.track(net, [pad, (pad[0], 123.3), via], "F.Cu")
        hand_via(d, net, *via)
    pair(d, "SS_RX1", [(129.1, 122.3), (119.79, 112.99), (108.6, 112.99)], "B.Cu", p_left=False,
         p_start=[(129.75, 122.95)], n_start=[(128.85, 123.05)],
         p_end=[(107.5, 112.79), (vx[0], 112.74)], n_end=[(107.5, 113.24), (vx[1], 113.24)])  # fmt: skip

    # SS_TX0 and the USB 2 pair leave JT3's outer row south, to a via each between the row and the pins.
    for net, pad, via in (("SS_TX0_P", (129.1, 127.18), (128.85, 127.95)), ("SS_TX0_N", (129.5, 127.18), (129.65, 127.95)),
                          ("USB_D_N", (131.5, 127.18), (131.3, 127.95)), ("USB_D_P", (131.9, 127.18), (132.1, 127.95))):  # fmt: skip
        # Straight down past the neighbouring ground pads' ends, then to the via.
        d.track(net, [pad, (pad[0], 127.62), via], "F.Cu", width=NECK)
        hand_via(d, net, *via)
    # SS_TX0, bottom layer: N passes north of P's via, then west along the pins, north-west to B2 (P)
    # and B3 (N).
    pair(d, "SS_TX0", [(128.0, 127.75), (114.6, 127.75), (110.4, 123.55), (110.4, 117.64), (110.0, 117.24),
                       (108.6, 117.24)], "B.Cu", p_left=True,
         p_start=[(128.85, 127.95)], n_start=[(129.65, 127.95), (129.2, 127.45), (128.4, 127.45)],
         p_end=[(107.5, 117.24), (vx[1], 117.24)], n_end=[(107.5, 116.74), (vx[0], 116.74)])  # fmt: skip

    # The USB 2 pair, bottom layer: north of SS_TX0, west, north, to 2 vias just behind the A row,
    # where A6 (P) and A7 (N) and the ESD clamp U1 take it on the top layer. B6 (P) joins on the bottom
    # layer and B7 (N) on In2: the B row has D+ and D- the other way round.
    pair(d, "USB_D", [(131.7, 127.95), (131.7, 126.95), (131.3, 126.55), (116.4, 126.55), (111.6, 121.75),
                      (111.6, 116.2)], "B.Cu", p_left=False,
         p_start=[(132.1, 127.95)], n_start=[(131.3, 127.95)],
         p_end=[(111.8, 115.3), (111.5, 114.99), (110.15, 114.99)], n_end=[(110.9, 115.49)])  # fmt: skip
    # The A row's middle pads to vias just behind it: D+, D-, CC2 and SBU_N go on below from here.
    for net, a, via in (("USB_D_P", (109.25, 114.99), (110.15, 114.99)), ("USB_D_N", (109.25, 115.49), (110.9, 115.49)),
                        ("USB_CC2", (109.25, 114.49), (110.9, 114.49)), ("USB_SBU_N", (109.25, 115.99), (110.15, 116.04))):  # fmt: skip
        d.track(net, [a, via], "F.Cu", width=NECK)
        hand_via(d, net, *via)
    d.track("USB_D_P", [(vx[1], 115.24), (106.8, 115.24), (107.6, 115.04), (110.15, 115.04), (110.15, 114.99)], "B.Cu",
            width=NECK)
    # In2 keeps Sierra's 13 mil from every other hole only along y = 115.515, between the D+ and SBU_N vias.
    d.track("USB_D_N", [(vx[0], 114.74), (107.6, 115.515), (110.9, 115.515), (110.9, 115.49)], "In2.Cu", width=NECK)
    # The ESD clamp, inside the top layer's pairs: D+ along its north pins, D- along its south pins.
    d.track("USB_D_P", [(110.15, 114.99), (111.9, 114.99), (112.5, 114.35), (113.46, 114.35)], "F.Cu", width=NECK)
    d.track("USB_D_N", [(110.9, 115.49), (111.9, 115.49), (112.6, 116.25), (113.46, 116.25)], "F.Cu", width=NECK)


def core_rail(d: kicadgen.Design) -> None:
    """The RP2350's 1.1 V core (DVDD 6, 23, 39 and VREG_FB 50) by hand. Each pin's straight way out is
    taken (C18's ground pad, the crystal, C14, C9), and the router left all 4 bare (M129). So each pin
    has a stub inward to a via inside the ring of pads, and In3 joins the 4 vias under the ground pad,
    with C18 west and the regulator's output (C10, L2) north-east. 4 vias tie the ground pad to the
    planes clear of them."""
    vias = {"6": (138.95, 114.70), "23": (141.5, 118.05), "39": (144.05, 115.10), "50": (142.7, 112.95)}
    pads = {"6": (138.05, 114.70), "23": (141.5, 118.95), "39": (144.95, 115.10), "50": (142.7, 112.05)}
    for pin, via in vias.items():
        d.track("+1V1", [pads[pin], via], "F.Cu", width=0.25)
        hand_via(d, "+1V1", *via)
    c18, c10 = (135.7, 115.98), (147.2, 111.2)  # c10 clear of the microSD shell under it
    d.track("+1V1", [(136.4, 115.98), c18], "F.Cu", width=0.25)
    d.track("+1V1", [(147.6, 110.38), c10], "F.Cu", width=0.25)
    hand_via(d, "+1V1", *c18)
    hand_via(d, "+1V1", *c10)
    d.track("+1V1", [c18, (136.98, 114.70), vias["6"], (142.7, 114.70)], "In3.Cu")
    d.track("+1V1", [c10, (145.45, 112.95), vias["50"], (142.7, 115.10), vias["39"]], "In3.Cu")
    d.track("+1V1", [vias["23"], (141.5, 114.70)], "In3.Cu")
    for x, y in ((140.4, 115.6), (140.4, 116.6), (142.6, 116.0), (142.6, 116.9)):
        hand_via(d, "GND", x, y)


# ---- the schematic: blocks the way the signal flows, each IC with its own parts ------------------
BLOCKS = [
    # name, the parts; blocks flow left to right across the sheet and wrap
    ("SOM JT2: power, USB-C control, lights", ["J2", "TH1", "R16", "R17", "D1", "D2", "D3", "SW1"]),
    ("SOM JT3: USB, the RP2350's controls, SD power", ["J3", "U6", "U7", "R10", "R11", "C22"]),
    ("SOM JT1: SD card, 1.8 V, reset", ["J1", "R15", "SW4", "SW5", "R13", "R14"]),
    ("USB-C", ["J4", "U1"]),
    ("5 V to 3.8 V to 3.3 V", ["U2", "L1", "C1", "C2", "C3", "C4", "C5", "R1", "R2", "C6", "U3", "C7", "C8"]),
    ("RP2350", ["U4", "U5", "Y1", "L2", "C9", "C10", "R3", "C11", "C12", "C13", "C14", "C15", "C16", "C17",
                "C18", "C19", "R4", "C20", "C21", "R5", "R6", "R7", "R8", "R9", "SW2", "SW3", "D4", "R12",
                "TP1", "TP2"]),
    ("microSD", ["J7", "R18", "R19", "R20", "R21", "R22", "R23", "C23", "C24"]),
    ("the pins", ["J5", "J6"]),
]
SHEET_W = 320  # A1's width in 2.54 mm steps, less the margins


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
            p.sch_at = ((x + w // 2) * g, (y0 + h // 2) * g)
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


def build() -> kicadgen.Design:
    d = kicadgen.Design(
        name="wyvern",
        namespace=uuid.UUID("3f2b8c4e-91d7-4a6e-b5c2-7e0d4f1a9c63"),
        outline=(LEFT, TOP, RIGHT, BOTTOM),
        sheet="A1",
        copper_layers=6,
        plane_layers=("In1.Cu", "In4.Cu"),
        # Rounded only as far as the corner pins' square pads allow (0.3 mm to the edge).
        corner_radius=0.6,
        track_width=0.15,
        clearance=0.12,
        # 0.2 mm copper to an edge or a hole: the USB-C receptacle's rear shell slot and its locating peg
        # are 0.375 mm apart, so a 6 mil ring leaves 0.22 mm, under the workcenter's 0.3 mm default.
        edge_clearance=0.2,
        # Sierra's 6 mil ring on a 0.2 mm hole.
        via_size=0.51,
        via_drill=0.2,
    )
    d.fab = "sierra-circuits-web"
    # The fab's floors, not the workcenter's 0.3 mm hole: Sierra drills 6 mil and rings 6 mil (rules/README.md).
    d.rules = {"min_through_hole_diameter": 0.2, "min_hole_clearance": 0.2, "min_text_height": 0.6,
               "min_text_thickness": 0.13}
    d.symbol_dirs = {"Wyvern": HERE / "symbols" / "wyvern.kicad_sym"}
    d.footprint_dirs = {"Wyvern": HERE / "footprints" / "wyvern.pretty"}
    d.power_nets = {
        "GND": "GND",
        "VBUS": "VBUS",
        "SOM_SYS": "+3V8",
        "+3V3": "+3V3",
        "+1V8": "+1V8",
        "SD_VDD": "VDD",
        "SD_VIO": "VDDA",
        "+1V1": "+1V1",
        "VREG_AVDD": "+3.3VA",
    }
    # No power output drives these: VBUS and GND come in on J4, the 3.8 V rail through L1.
    # The RP2350's 1.1 V core comes out of L2, and VREG_AVDD through R3: passive parts.
    d.flagged_nets = ["GND", "VBUS", "SOM_SYS", "+1V1", "VREG_AVDD"]
    d.net_classes = {
        "power": {"width": 0.6, "clearance": 0.15, "via": 0.65, "via_drill": 0.3, "nets": ["VBUS", "SOM_SYS", "BUCK_SW"]},
        "rail": {"width": 0.3, "clearance": 0.12, "via": 0.51, "via_drill": 0.2,
                 "nets": ["+3V3", "+1V8", "SD_VDD", "SD_VIO", "+1V1", "VREG_LX"]},
        "pairs": {"width": PAIR_W, "clearance": 0.15, "via": 0.51, "via_drill": 0.2,
                  "nets": [f"{p}_{s}" for p in DIFF for s in "PN"]},
    }  # fmt: skip
    d.zone("GND", layers=("In1.Cu", "In4.Cu"), connect="solid")
    # Ground on both faces too: beside every outer-layer pair, and onto the SOM's 70-odd ground pins.
    d.zone("GND", layers=("F.Cu", "B.Cu"), connect="solid")

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

    # ---- the SOM's 3 receptacles ------------------------------------------------------------------
    for ref, (jt, rot) in SOCKETS.items():
        nets = {str(n): SOM_NETS[ref][name] for n, name in som.PINS[jt].items() if name in SOM_NETS[ref]}
        add(ref, f"Wyvern:OpenQ845_{jt}", "DF40HC(3.0)-100DS-0.4V", SOCKET, som_at(*som.CENTRES[jt]), nets, rot)

    # ---- USB-C (J4) and its ESD clamp (U1, beside the A row, inside the SuperSpeed pairs' loop) ---
    add("J4", "Connector:USB_C_Receptacle", "12401610E4#2A", USBC, USB_C_AT, USB_C, rot=270)
    add("U1", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", "Package_TO_SOT_SMD:SOT-23-6", (114.6, 115.3),
        {"1": "USB_D_P", "6": "USB_D_P", "3": "USB_D_N", "4": "USB_D_N", "2": "GND", "5": "VBUS"}, 0)  # fmt: skip

    # ---- power, on the back under JT2: 5 V to the SOM's 3.8 V (U2), 3.8 V to 3.3 V (U3) -----------
    add("U2", "Regulator_Switching:TPS62130", "TPS62130", "Package_DFN_QFN:VQFN-16-1EP_3x3mm_P0.5mm_EP1.68x1.68mm",
        (119.6, 107.4),
        {"1": "BUCK_SW", "2": "BUCK_SW", "3": "BUCK_SW", "5": "BUCK_FB", "6": "GND", "7": "GND", "8": "GND",
         "9": "BUCK_SS", "10": "VBUS", "11": "VBUS", "12": "VBUS", "13": "VBUS", "14": "SOM_SYS",
         "15": "GND", "16": "GND", "17": "GND"}, 180, B)  # fmt: skip
    add("L1", "Device:L", "2.2u XAL4020-222", "Inductor_SMD:L_Coilcraft_XAL4020-XXX", (114.2, 107.6),
        {"1": "BUCK_SW", "2": "SOM_SYS"}, 0, B)  # fmt: skip
    c("C1", "10u", "VBUS", (123.6, 106.0), 0, B, fp=C0805)
    c("C2", "10u", "VBUS", (123.6, 108.4), 0, B, fp=C0805)
    c("C3", "22u", "SOM_SYS", (110.4, 105.6), 90, B, fp=C0805)
    c("C4", "22u", "SOM_SYS", (110.4, 109.2), 90, B, fp=C0805)
    c("C5", "22u", "SOM_SYS", (108.3, 106.9), 90, B, fp=C0805)
    # VOUT = 0.8 V x (1 + R1/R2) = 3.79 V: in the SOM's 3.45 to 4.75 V at every corner (sim/sys_rail.cir).
    r("R1", "374k", "SOM_SYS", "BUCK_FB", (122.9, 110.5), 0, B)
    r("R2", "100k", "BUCK_FB", "GND", (122.9, 111.5), 0, B)
    c("C6", "3.3n", "BUCK_SS", (119.6, 110.4), 0, B)
    add("U3", "Regulator_Linear:AP2112K-3.3", "AP2112K-3.3", "Package_TO_SOT_SMD:SOT-23-5", (128.0, 108.4),
        {"1": "SOM_SYS", "2": "GND", "3": "SOM_SYS", "5": "+3V3"}, 0, B)  # fmt: skip
    c("C7", "1u", "SOM_SYS", (128.0, 105.9), 0, B)
    c("C8", "1u", "+3V3", (131.0, 108.4), 90, B)

    # ---- the RP2350 (U4) under the SOM, its flash (U5), crystal (Y1) and core regulator -----------
    MCU = (141.5, 115.5)
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
    add("U4", "MCU_RaspberryPi:RP2350A", "RP2350A", "Package_DFN_QFN:QFN-60-1EP_7x7mm_P0.4mm_EP3.4x3.4mm", MCU, rp)
    # North of it, in a row under JT1: the core regulator as Raspberry Pi lays it out (Hardware design
    # with RP2350, 2.1: the polarised 3.3 uH inductor, 4.7 uF in and out, 33 ohm and 4.7 uF filtering
    # VREG_AVDD), then the USB series resistors, QSPI_SS's pull-up and BOOT's 1k.
    ny = 109.9
    add("L2", "Device:L", "3.3u AOTA-B201610S3R3", "Inductor_SMD:L_Abracon_AOTA-B201610S", (145.2, ny),
        {"1": "VREG_LX", "2": "+1V1"}, 0)  # fmt: skip
    c("C9", "4.7u", "+3V3", (143.0, ny), 90)
    c("C10", "4.7u", "+1V1", (147.6, ny), 90)
    r("R3", "33", "+3V3", "VREG_AVDD", (148.7, ny), 90)
    c("C11", "4.7u", "VREG_AVDD", (149.8, ny), 90)
    r("R6", "27", "MCU_DP", "MCU_USB_P", (141.8, ny), 90)
    r("R7", "27", "MCU_DM", "MCU_USB_N", (140.7, ny), 90)
    r("R4", "10k", "QSPI_SS", "+3V3", (139.6, ny), 90)
    r("R9", "1k", "QSPI_SS", "BOOT_R", (138.5, ny), 90)
    # 100n on each supply pin's side: IOVDD 1 and DVDD 6 west, IOVDD 38 and ADC_AVDD 44 east, IOVDD 20
    # and 30 south beside the crystal.
    mx, my = MCU
    c("C12", "100n", "+3V3", (mx - 5.1, my - 2.0), 90)
    c("C18", "100n", "+1V1", (mx - 5.1, my + 0.0), 90)
    c("C13", "100n", "+3V3", (mx - 5.1, my + 2.0), 90)
    c("C14", "100n", "+3V3", (mx + 5.1, my + 0.0), 90)
    c("C15", "100n", "+3V3", (mx + 5.1, my - 2.0), 90)
    c("C16", "100n", "+3V3", (mx + 5.1, my + 2.0), 90)
    add("U5", "Memory_Flash:W25Q128JVP", "W25Q128JV", "Package_SON:WSON-8-1EP_6x5mm_P1.27mm_EP3.4x4.3mm",
        (132.3, 113.0),
        {"1": "QSPI_SS", "2": "QSPI_SD1", "3": "QSPI_SD2", "4": "GND", "5": "QSPI_SD0", "6": "QSPI_SCLK",
         "7": "QSPI_SD3", "8": "+3V3", "9": "GND"}, 90)  # fmt: skip
    c("C19", "100n", "+3V3", (132.3, 117.0))
    add("Y1", "Device:Crystal_GND24", "12MHz ABM8-272-T3", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm",
        (140.4, 121.43), {"1": "XIN", "2": "GND", "3": "XTAL_O", "4": "GND"}, 0)  # fmt: skip
    c("C20", "15p", "XIN", (137.3, 120.9), 90)
    c("C21", "15p", "XTAL_O", (143.5, 121.9), 90)
    r("R5", "1k", "XTAL_O", "XOUT", (144.6, 121.9), 90)
    c("C17", "100n", "+3V3", (136.2, 120.9), 90)
    r("R8", "10k", "MCU_RUN", "+3V3", (145.7, 121.9), 90)
    # The Snapdragon's 2 GPIOs (1.8 V) pull RUN and QSPI_SS low through open-drain buffers on its own
    # 1.8 V: each output stands 3.3 V, and each input has 100k to ground while the SOM is off.
    add("U6", "74xGxx:74LVC1G07", "74LVC1G07", SOT353, (149.0, 120.6),
        {"2": "MCU_RUN_CTL", "3": "GND", "4": "MCU_RUN", "5": "+1V8"}, 0)  # fmt: skip
    add("U7", "74xGxx:74LVC1G07", "74LVC1G07", SOT353, (152.4, 120.6),
        {"2": "MCU_BOOT_CTL", "3": "GND", "4": "BOOT_R", "5": "+1V8"}, 0)  # fmt: skip
    r("R10", "100k", "MCU_RUN_CTL", "GND", (150.7, 118.0), 90)
    r("R11", "100k", "MCU_BOOT_CTL", "GND", (154.1, 118.0), 90)
    c("C22", "100n", "+1V8", (155.6, 120.6), 90)

    # ---- the USB end, on top: PWR and its 3 lights above J4, BOOT and GP25's light below -----------
    add("SW1", "Switch:SW_Push", "PWR", BUTTON, (102.6, 106.0), {"1": "SOM_PWR_N", "2": "GND"}, 90)
    for k, (net, colour) in enumerate((("LED_R", "red"), ("LED_G", "green"), ("LED_B", "blue"))):
        add(f"D{k + 1}", "Device:LED", colour, LED0603, (105.7 + 1.8 * k, 104.6), {"1": "GND", "2": net}, 90)
    add("SW2", "Switch:SW_Push", "BOOT", BUTTON, (102.6, 124.5), {"1": "BOOT_R", "2": "GND"}, 90)
    add("D4", "Device:LED", "green", LED0603, (106.9, 126.6), {"1": "GND", "2": "LED_GP25"}, 0)
    r("R12", "1k", "LED_GP25", "GP25", (106.9, 125.0), 0)

    # ---- the back: buttons the board rarely needs, the SOM's helpers, the microSD (J7) --------------
    add("SW3", "Switch:SW_Push", "RUN", BUTTON, (135.6, 124.8), {"1": "MCU_RUN", "2": "GND"}, 0, B)
    add("SW4", "Switch:SW_Push", "VOL-", BUTTON, (141.4, 124.8), {"1": "SOM_RESIN_N", "2": "GND"}, 0, B)
    add("SW5", "Switch:SW_Push", "EDL", BUTTON, (147.2, 124.8), {"1": "SOM_EDL", "2": "EDL_R"}, 0, B)
    r("R13", "1k", "EDL_R", "+1V8", (151.4, 124.8), 90, B)
    r("R14", "100k", "SOM_EDL", "GND", (152.6, 124.8), 90, B)
    # CBL_PWR_N to ground: the SOM starts when power arrives. Leave R15 off to start it with PWR.
    r("R15", "0", "SOM_AUTO_ON", "GND", (151.0, 105.0), 0, B)
    add("TH1", "Device:Thermistor_NTC", "100k NCP15WF104", R0402, (116.4, 104.6), {"1": "SOM_THERM", "2": "GND"}, 0, B)
    r("R16", "2.2k", "SOM_I2C_SDA", "+1V8", (133.6, 104.8), 0, B)
    r("R17", "2.2k", "SOM_I2C_SCL", "+1V8", (133.6, 105.9), 0, B)
    add("TP1", "Connector:TestPoint", "SWCLK", TP, (135.6, 108.0), {"1": "SWCLK"}, 0, B)
    add("TP2", "Connector:TestPoint", "SWDIO", TP, (137.6, 108.0), {"1": "SWDIO"}, 0, B)
    # The card leaves from the end with the contact pads (the footprint's F.Fab draws it out past them):
    # at 90 degrees on the back that end is the board's right end, and the card stands 4 mm past it.
    add("J7", "Connector:Micro_SD_Card_Det2", "104031-0811", "Connector_Card:microSD_HC_Molex_104031-0811",
        (154.0, CY), {"1": "SD_D2", "2": "SD_D3", "3": "SD_CMD", "4": "SD_VDD", "5": "SD_CLK", "6": "GND",
                      "7": "SD_D0", "8": "SD_D1", "9": "SD_DET_N", "10": "GND", "SH": "GND"}, 90, B)  # fmt: skip
    for k, net in enumerate(("SD_CMD", "SD_D0", "SD_D1", "SD_D2", "SD_D3")):
        r(f"R{18 + k}", "47k", net, "SD_VIO", (141.0 + 1.2 * k, 105.0), 90, B)
    r("R23", "100k", "SD_DET_N", "SD_VIO", (147.0, 105.0), 90, B)
    c("C23", "4.7u", "SD_VDD", (144.6, 107.6), 0, B, fp=C0603)
    c("C24", "100n", "SD_VIO", (144.6, 109.2), 0, B)

    # ---- the pins: 2 rows of 24, headers underneath ---------------------------------------------
    add("J5", "Connector_Generic:Conn_01x24", "1x24 header", HEADER, (pin_x(0), ROW_TOP),
        {str(k + 1): PIN_NET[name] for k, name in enumerate(TOP_PINS)}, 270, B)  # fmt: skip
    add("J6", "Connector_Generic:Conn_01x24", "1x24 header", HEADER, (pin_x(0), ROW_BOTTOM),
        {str(k + 1): PIN_NET[name] for k, name in enumerate(BOTTOM_PINS)}, 270, B)  # fmt: skip

    # ---- the words: each pin named on the back, under its pad, the way a Teensy's pinout card reads;
    # the buttons named on the front; the board's name on both faces.
    for row, y in ((TOP_PINS, 103.55), (BOTTOM_PINS, 127.3)):
        for k, name in enumerate(row):
            d.text(name, pin_x(k), y, "B.SilkS", 0.6, 0.13)
    d.text("PWR", 102.6, 109.35, "F.SilkS", 0.6, 0.13)
    d.text("BOOT", 102.6, 121.1, "F.SilkS", 0.6, 0.13)
    d.text("WYVERN", 138.6, 114.2, "B.SilkS", 2.0, 0.3)
    d.text("SNAPDRAGON 845 + RP2350", 138.6, 116.9, "B.SilkS", 0.8, 0.15)
    d.text("v0.1  RUN  VOL-  EDL", 138.6, 118.6, "B.SilkS", 0.6, 0.13)

    d.defined_nets = {
        "SOM_PWR_N": "the PMIC's power key input, which the datasheet (Table 3, pin 30) has grounded by a button",
        "SOM_RESIN_N": "the PMIC's RESIN input, which the datasheet (Table 2, pin 79) has grounded by a button",
        "MCU_RUN": "R8 (10k) to +3V3, and the RP2350's own pull-up on RUN (datasheet, pin list)",
        "QSPI_SS": "R4 (10k) to +3V3, and the RP2350's own pull-up on QSPI_SS (datasheet, pin list)",
        "BOOT_R": "R9 (1k) to QSPI_SS, which R4 holds at +3V3",
        "XIN": "the crystal Y1 and C20; the RP2350's oscillator drives the pair",
        "SWCLK": "the RP2350's own pull-up on SWCLK",
        "SWDIO": "the RP2350's own pull-up on SWDIO",
        "BUCK_SS": "the TPS62130's SS/TR current source (2.5 uA, datasheet ISS/TR) charges C6",
        "SD_CLK": "the SDA845 drives SDC2_CLK; the card's supply (VREG_L21A) is off whenever the SoC is",
    }
    for i in range(30):
        d.defined_nets[f"GP{i}"] = "a pin of the RP2350 on the header; firmware sets it"
    d.check_pulls = True
    usb_pairs(d)
    core_rail(d)
    # 3D bodies for the 4 parts KiCad's 3D library has none for (models/make_models.py).
    d.model("U4", "${KIPRJMOD}/models/rp2350_qfn60.wrl", replace=True)
    d.model("U2", "${KIPRJMOD}/models/tps62130_vqfn16.wrl", replace=True)
    for ref in SOCKETS:
        d.model(ref, "${KIPRJMOD}/models/df40hc_100ds.wrl", replace=True)
    d.model("J7", "${KIPRJMOD}/models/microsd_104031.wrl", replace=True)
    # No reference designators on the silkscreen: at this density they print over pads and each other.
    # The assembly drawing has them; the faces carry the pins' names instead.
    for part in d.parts:
        part.hide_ref = True
    lay_out_schematic(d)
    return d
