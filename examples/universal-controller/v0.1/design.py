"""Rosetta v0.1: one game controller that speaks to a PS4, a PS5, an Xbox, a Switch, or anything over
Bluetooth, chosen with a 5-position knob on its face.

The hard parts this board takes on, and where each lives:

- The mode knob (SW1, an NKK NR01 1-pole 5-position rotary switch) is read as 1 analog value: each
  position taps a 6-resistor ladder (R40-R45), and a 100k pull-down (R46) reads ~0 V while the wiper
  is between detents. The firmware drops off the USB bus on that 0 V and comes back as the new
  console's device. `sim/mode_ladder.cir` proves the 5 windows never meet at any corner.
- Console authentication: a PS4, a PS5 and an Xbox only talk to a licensed controller. J2 is a USB
  host port for an auth donor (a licensed controller or dongle). The RP2040 runs a second USB port
  in software (PIO-USB on GPIO16/17) and relays the console's challenge to the donor.
- Bluetooth Classic and BLE: an ESP32-WROOM-32E (U3) on the RP2040's UART. The RP2040 holds its EN
  and IO0, so 1 USB cable updates both chips. Its antenna hangs over the gap between the grips.
- Hall-effect sticks and triggers: no drift. 8 analog inputs on a 12-bit SPI ADC (U4, MCP3208).
- Adaptive triggers: a small motor in each trigger module, driven by a DRV8833 H-bridge (U6).
- Haptics: 2 LRAs, each with a DRV2605L (U9, U10). The chip has 1 fixed I2C address, so each has a
  bus of its own.
- Gyro aim: a 6-axis IMU (U5, LSM6DSL).
- A light ring: 5 RGB LEDs (D2-D6) round the knob light the chosen console's colour.
- Back paddles (SW15, SW16) and 16 face buttons on 2 shift registers (U7, U8).

    workcenter design design.py --route     # from this folder

Board: a controller-shaped outline 160 x 92 mm, 4 layers (F.Cu signal, In1.Cu GND plane, In2.Cu
signal, B.Cu signal). The front carries what a hand touches: buttons, the knob, the ring, the
connectors. The back carries the electronics.
"""

from __future__ import annotations

import math
import uuid
from pathlib import Path

import kicadgen

# ---- the outline: a polygon whose corners are filleted ------------------------------------------
#
# Each corner is (x, y, radius), clockwise on the page (y grows downward). A corner that turns the
# other way (the notch between the grips) is concave. Shrinking the outline by `inset` moves every
# edge in, takes `inset` from a convex corner's radius and adds it to a concave one's, with the
# same centres: the shrunk outline is exact, so the router's boundary, the pours and the DRC agree.
CORNERS = [
    (100.0, 100.0, 12.0),  # top left
    (240.0, 100.0, 12.0),  # top right
    (250.0, 150.0, 12.0),  # right shoulder
    (240.0, 192.0, 16.0),  # right grip, outer tip
    (208.0, 192.0, 14.0),  # right grip, inner tip
    (198.0, 152.0, 10.0),  # the notch, right (concave)
    (142.0, 152.0, 10.0),  # the notch, left (concave)
    (132.0, 192.0, 14.0),  # left grip, inner tip
    (100.0, 192.0, 16.0),  # left grip, outer tip
    (90.0, 150.0, 12.0),  # left shoulder
]
NOTCH_Y = 152.0


def _fillets(inset: float) -> list[tuple[tuple[float, float], float, tuple[float, float], tuple[float, float]]]:
    """For each corner: its centre, its radius at `inset`, and where the arc meets the edge in and out."""
    n = len(CORNERS)
    out = []
    for i in range(n):
        (px, py, _), (x, y, r), (nx, ny, _) = CORNERS[i - 1], CORNERS[i], CORNERS[(i + 1) % n]
        din = ((x - px), (y - py))
        dout = ((nx - x), (ny - y))
        lin, lout = math.hypot(*din), math.hypot(*dout)
        din, dout = (din[0] / lin, din[1] / lin), (dout[0] / lout, dout[1] / lout)
        nin, nout = (-din[1], din[0]), (-dout[1], dout[0])  # inward normals
        convex = din[0] * dout[1] - din[1] * dout[0] > 0
        s = r if convex else -r
        # The centre: on the lines `s` in from both edges.
        a = (x + s * nin[0], y + s * nin[1])
        b = (x + s * nout[0], y + s * nout[1])
        det = din[0] * (-dout[1]) - din[1] * (-dout[0])
        t = ((b[0] - a[0]) * (-dout[1]) - (b[1] - a[1]) * (-dout[0])) / det
        c = (a[0] + t * din[0], a[1] + t * din[1])
        rr = r - inset if convex else r + inset
        sign = 1.0 if convex else -1.0
        # Where the arc touches each shrunk edge: from the centre, against the inward normal.
        tin = (c[0] - sign * rr * nin[0], c[1] - sign * rr * nin[1])
        tout = (c[0] - sign * rr * nout[0], c[1] - sign * rr * nout[1])
        out.append((c, rr, tin, tout))
    return out


def _arc(c, r, a, b, n):
    a0 = math.atan2(a[1] - c[1], a[0] - c[0])
    a1 = math.atan2(b[1] - c[1], b[0] - c[0])
    sweep = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
    return [(c[0] + r * math.cos(a0 + sweep * k / n), c[1] + r * math.sin(a0 + sweep * k / n)) for k in range(n + 1)]


class ControllerDesign(kicadgen.Design):
    """A Design whose edge is the controller's outline (CORNERS), not a rectangle."""

    def outline_polygon(self, inset: float = 0.0, n: int = 8) -> list[tuple[float, float]]:
        pts: list[tuple[float, float]] = []
        for c, r, tin, tout in _fillets(inset):
            for p in _arc(c, r, tin, tout, max(n, 4)):
                p = (round(p[0], 4), round(p[1], 4))
                if not pts or math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 1e-6:
                    pts.append(p)
        return pts

    def inside_outline(self, x: float, y: float, margin: float = 0.0) -> bool:
        poly = self.outline_polygon(margin, 16)
        inside = False
        for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1], strict=True):
            if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                inside = not inside
        return inside

    def _edge_cuts(self, ns: uuid.UUID) -> list:
        fmt, Q = kicadgen.fmt, kicadgen.Q
        stroke = ["stroke", ["width", "0.1"], ["type", "default"]]
        fil = _fillets(0.0)
        items = []
        for i, (c, r, tin, tout) in enumerate(fil):
            mid = _arc(c, r, tin, tout, 2)[1]
            items.append(
                ["gr_arc", ["start", fmt(tin[0]), fmt(tin[1])], ["mid", fmt(mid[0]), fmt(mid[1])],
                 ["end", fmt(tout[0]), fmt(tout[1])], stroke, ["layer", Q("Edge.Cuts")],
                 ["uuid", kicadgen.uid(ns, f"edge/arc/{i}")]]
            )  # fmt: skip
            nxt = fil[(i + 1) % len(fil)][2]
            items.append(
                ["gr_line", ["start", fmt(tout[0]), fmt(tout[1])], ["end", fmt(nxt[0]), fmt(nxt[1])], stroke,
                 ["layer", Q("Edge.Cuts")], ["uuid", kicadgen.uid(ns, f"edge/line/{i}")]]
            )  # fmt: skip
        return items


# ---- footprints ---------------------------------------------------------------------------------
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
RPACK = "Resistor_SMD:R_Array_Convex_4x0603"
TACT = "Button_Switch_SMD:SW_SPST_TL3342"
SMALL = "Button_Switch_SMD:SW_SPST_PTS810"
USBC = "Connector_USB:USB_C_Receptacle_GCT_USB4085"  # all through-hole: a controller's cable gets yanked
SH2 = "Connector_JST:JST_SH_SM02B-SRSS-TB_1x02-1MP_P1.00mm_Horizontal"
SH3 = "Connector_JST:JST_SH_SM03B-SRSS-TB_1x03-1MP_P1.00mm_Horizontal"
SH5 = "Connector_JST:JST_SH_SM05B-SRSS-TB_1x05-1MP_P1.00mm_Horizontal"
SOIC16 = "Package_SO:SOIC-16_3.9x9.9mm_P1.27mm"
B = "B.Cu"

# ---- where things are ---------------------------------------------------------------------------
KNOB = (170.0, 122.0)  # the centre of SW1's shaft
RING_R = 10.5  # the LEDs' circle round it
LABEL_R = 13.6  # the modes' names, outside the LEDs


def label_at(deg: float) -> tuple[float, float]:
    """Where a mode's name sits: outside its LED, the top one closer in, clear of J1's pins."""
    r = 12.4 if deg == 90 else LABEL_R
    a = math.radians(deg)
    return (round(KNOB[0] + r * math.cos(a), 2), round(KNOB[1] - r * math.sin(a), 2))
# The 5 modes, left to right round the top of the knob: the angle of each LED on the ring, its label.
MODES = [(162, "PS4"), (126, "PS5"), (90, "XBOX"), (54, "SWITCH"), (18, "BT")]
DPAD = (114.0, 131.0)
FACE = (226.0, 131.0)
STICK_L = (147.0, 141.0)
STICK_R = (193.0, 141.0)
STICK_R_ZONE = 10.0  # a stick module's footprint over the face
# The ESP32 module on the back, turned so its antenna hangs past the notch edge: the antenna's
# clearance (the bar of the footprint's courtyard) lies in the air between the grips.
ESP_AT = (170.0, NOTCH_Y - 6.31)


def usb_at(x: float) -> tuple[float, float]:
    """A GCT USB4085's place for a receptacle centred on x that opens out of the top edge: the
    footprint's origin is pin A1, 2.975 mm from its centre line, and it is turned 180 degrees."""
    return (x + 2.975, 107.6)


# ---- the schematic: blocks, each IC with its own parts; labels between blocks -----------------
BLOCKS = [
    # name, sheet origin in 2.54 mm steps, the parts
    ("console USB", (12, 14), ["J1", "R1", "R2", "R3", "R4"]),
    ("auth port", (12, 52), ["J2", "R5", "R6", "R7", "R8", "R9", "R10", "U13", "C1", "C2", "R11"]),
    ("power", (12, 100), ["J9", "U11", "R12", "C3", "C4", "D1", "Q1", "R13", "U12", "C5", "C6", "R14", "R15", "C7"]),
    ("RP2040", (90, 14), ["U1", "C10", "C11", "C12", "C13", "C14", "C15", "C16", "C17", "C18", "Y1", "C19", "C20",
                         "R16", "U2", "C21", "R17", "R18", "SW17", "R19", "J10", "R26", "R27", "R28", "R29",
                         "R47", "R48", "R49"]),
    ("ESP32", (90, 120), ["U3", "C22", "C23", "R20", "C24", "R21"]),
    ("ADC, knob, modules", (175, 14), ["U4", "C25", "C26", "R22", "J5", "J6", "J3", "J4", "SW1", "R40", "R41", "R42",
                                       "R43", "R44", "R45", "R46", "C27"]),
    ("motors", (175, 86), ["U6", "C28", "C29", "C30", "R23", "R24", "R50", "R51", "U9", "C31", "C32", "C33", "J7", "U10", "C34",
                           "C35", "C36", "J8", "R25"]),
    ("IMU", (175, 150), ["U5", "R52", "C37", "C38"]),
    ("buttons", (250, 14), ["U7", "C39", "RN1", "RN2", "U8", "C40", "RN3", "RN4", "SW2", "SW3", "SW4", "SW5", "SW6",
                            "SW7", "SW8", "SW9", "SW10", "SW11", "SW12", "SW13", "SW14", "SW18", "SW15", "SW16"]),
    ("ring", (250, 150), ["U14", "C41", "D2", "D3", "D4", "D5", "D6", "C42", "C43", "C44", "C45", "C46"]),
]


def lay_out_schematic(d: kicadgen.Design) -> None:
    """Each block's ICs in a row, its small parts in rows of 8 under them. A net that stays in 1
    block is drawn as a wire; a net that joins 2 blocks is a label at each pin."""
    g = 2.54
    parts = {p.ref: p for p in d.parts}
    block_of = {}
    for name, (bx, by), refs in BLOCKS:
        x, y, col_h = bx, by, 0
        big = [r for r in refs if not (r[0] in "RCDQY" or r.startswith(("SW", "RN")))]
        small = [r for r in refs if r not in big]
        for ref in big:
            p = parts[ref]
            xs = [pin.x for pin in p.symbol.pins] or [0]
            ys = [pin.y for pin in p.symbol.pins] or [0]
            w = (max(xs) - min(xs)) / g + 6
            h = (max(ys) - min(ys)) / g + 6
            p.sch_at = ((x + round(w / 2)) * g, (y + round(h / 2)) * g)
            p.sch_rot = 0
            x += round(w) + 4
            col_h = max(col_h, round(h))
            block_of[ref] = name
        sx, sy = bx, by + col_h + 6
        for k, ref in enumerate(small):
            p = parts[ref]
            p.sch_at = ((sx + 8 * (k % 8)) * g, (sy + 8 * (k // 8)) * g)
            p.sch_rot = 0
            block_of[ref] = name
    missing = [r for r in parts if r not in block_of]
    if missing:
        raise ValueError(f"no block for {missing}")
    # A net that joins 2 blocks is labelled; a net inside 1 block is wired.
    blocks_of_net = {}
    for p in d.parts:
        for net in p.nets.values():
            blocks_of_net.setdefault(net, set()).add(block_of[p.ref])
    d.sch_label_nets = tuple(sorted(n for n, b in blocks_of_net.items() if len(b) > 1 and n not in d.power_nets))
    d.sch_wires = True


def build() -> kicadgen.Design:
    d = ControllerDesign(
        name="rosetta",
        namespace=uuid.UUID("507df47f-8183-4221-b77e-b993521473d0"),
        outline=(90.0, 100.0, 250.0, 192.0),
        sheet="A1",
        copper_layers=4,
        plane_layers=("In1.Cu",),
        track_width=0.2,
        clearance=0.15,
        # 0.45/0.2 mm signal vias: the RP2040's 0.4 mm pins fan out through them; 0.6 mm vias left
        # 9 of its pins with no way out. The power classes keep 0.6/0.3.
        via_size=0.45,
        via_drill=0.2,
    )
    # No title: KiCad places the title text at the outline box's corner, which is off this shape.
    # KiCad 10 draws the ESP32's 4 ground pins as 1 stacked pin; the project copy splits them
    # (symbols/split_stacked.py).
    d.symbol_dirs = {"Rosetta": Path(__file__).resolve().parent / "symbols" / "rosetta.kicad_sym"}
    d.power_nets = {
        "GND": "GND",
        "VBUS": "VBUS",
        "VSYS": "VCC",
        "BAT": "+BATT",
        "+3V3": "+3V3",
        "+1V1": "+1V1",
        "VBUS_HOST": "VBUS",
        "VINT": "VINT",  # the DRV8833's own regulator; KiCad's symbol calls its pin an input
    }
    # No power-output pin drives these: VBUS and GND come in on J1, VSYS through D1 or Q1.
    d.flagged_nets = ["GND", "VBUS", "VSYS", "VINT"]
    d.net_classes = {
        "power": {
            "width": 0.5,
            "clearance": 0.15,  # the USB4085's pins are 0.15 mm apart
            "via": 0.6,
            "via_drill": 0.3,
            "nets": ["VBUS", "VSYS", "BAT", "VBUS_HOST"],
        },
        "rail": {"width": 0.3, "clearance": 0.15, "via": 0.6, "via_drill": 0.3, "nets": ["+3V3", "+1V1"]},
        "motor": {
            "width": 0.4,
            "clearance": 0.15,
            "via": 0.6,
            "via_drill": 0.3,
            "nets": ["MOT_L+", "MOT_L-", "MOT_R+", "MOT_R-", "LRA_L+", "LRA_L-", "LRA_R+", "LRA_R-"],
        },
    }
    # The ESP32 module's footprint stitches its ground pad with 0.2 mm holes.
    d.rules = {"min_through_hole_diameter": 0.2, "min_via_diameter": 0.45, "min_text_height": 0.8, "min_text_thickness": 0.12}
    d.zone("GND", layers=("In1.Cu",), connect="solid")

    grid = iter(range(10_000))

    def sch() -> tuple[float, float]:
        k = next(grid)
        return (25.4 + 25.4 * (k % 30), 25.4 + 25.4 * (k // 30))

    def add(ref, lib, value, fp, at, nets, rot=0.0, layer="F.Cu"):
        return d.add(ref, lib, value, fp, sch_at=sch(), pcb_at=at, pcb_rot=rot, pcb_layer=layer, nets=nets)

    def r(ref, value, a, b, at, rot=0.0, layer=B, fp=R0603):
        return add(ref, "Device:R", value, fp, at, {"1": a, "2": b}, rot, layer)

    def c(ref, value, a, at, rot=0.0, layer=B, b="GND", fp=C0603):
        return add(ref, "Device:C", value, fp, at, {"1": a, "2": b}, rot, layer)

    # ---- USB to the console (J1) and to the auth donor (J2) ---------------------------------------
    usb = {"A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS", "A1": "GND", "A12": "GND", "B1": "GND",
           "B12": "GND", "SH": "GND", "A5": "CC1", "B5": "CC2", "A6": "USB_D+", "B6": "USB_D+",
           "A7": "USB_D-", "B7": "USB_D-"}  # fmt: skip
    add("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "CONSOLE", USBC, usb_at(170.0), usb, rot=180)
    r("R1", "5.1k", "CC1", "GND", (164.0, 109.5), 90)  # a device's Rd on each CC pin
    r("R2", "5.1k", "CC2", "GND", (176.0, 109.5), 90)
    r("R3", "27", "USB_D+", "RP_D+", (167.5, 110.5), 90)
    r("R4", "27", "USB_D-", "RP_D-", (172.5, 110.5), 90)

    host = {k: v.replace("VBUS", "VBUS_HOST").replace("CC", "HCC").replace("USB_D", "HOST_D")
            for k, v in usb.items()}  # fmt: skip
    add("J2", "Connector:USB_C_Receptacle_USB2.0_16P", "AUTH", USBC, usb_at(205.0), host, rot=180)
    r("R5", "56k", "HCC1", "VBUS_HOST", (199.0, 109.5), 90)  # a source's Rp: default USB power
    r("R6", "56k", "HCC2", "VBUS_HOST", (211.0, 109.5), 90)
    r("R7", "27", "HOST_D+", "PIO_D+", (202.5, 110.5), 90)
    r("R8", "27", "HOST_D-", "PIO_D-", (207.5, 110.5), 90)
    r("R9", "15k", "HOST_D+", "GND", (202.5, 114.0), 90)  # a host's pull-downs
    r("R10", "15k", "HOST_D-", "GND", (207.5, 114.0), 90)
    add("U13", "Power_Management:TPS2051CDBV", "TPS2051C", "Package_TO_SOT_SMD:SOT-23-5", (205.0, 119.0),
        {"1": "VBUS_HOST", "2": "GND", "3": "FAULT_N", "4": "HOST_EN", "5": "VBUS"}, 0, B)  # fmt: skip
    c("C1", "1u", "VBUS", (199.5, 119.0), 90)
    c("C2", "10u", "VBUS_HOST", (210.5, 119.0), 90, fp=C0805)
    r("R11", "100k", "HOST_EN", "GND", (205.0, 123.0))  # the donor port is off in reset

    # ---- power: battery, charger, load sharing, 3.3 V --------------------------------------------
    add("J9", "Connector_Generic_MountingPin:Conn_01x02_MountingPin", "BATTERY",
        "Connector_JST:JST_PH_S2B-PH-SM4-TB_1x02-1MP_P2.00mm_Horizontal", (118.0, 182.0),
        {"1": "BAT", "2": "GND", "MP": "GND"}, rot=0)  # fmt: skip
    add("U11", "Battery_Management:MCP73831-2-OT", "MCP73831", "Package_TO_SOT_SMD:SOT-23-5", (122.0, 160.0),
        {"1": "CHG_STAT", "2": "GND", "3": "BAT", "4": "VBUS", "5": "PROG"}, 0, B)  # fmt: skip
    r("R12", "2k", "PROG", "GND", (122.0, 164.0), 0)  # 500 mA into the cell
    c("C3", "4.7u", "VBUS", (117.5, 160.0), 90, fp=C0805)
    c("C4", "4.7u", "BAT", (126.5, 160.0), 90, fp=C0805)
    add("D1", "Device:D_Schottky", "SS14", "Diode_SMD:D_SOD-123", (114.0, 167.0), {"1": "VSYS", "2": "VBUS"}, 0, B)
    # Q1: the cell feeds VSYS when VBUS is gone. Its gate sits on VBUS, held low by R13 when the
    # cable is out: then it conducts, drain (cell) to source (VSYS).
    add("Q1", "Transistor_FET:AO3401A", "AO3401A", "Package_TO_SOT_SMD:SOT-23", (122.0, 168.0),
        {"1": "VBUS", "2": "VSYS", "3": "BAT"}, 0, B)  # fmt: skip
    r("R13", "100k", "VBUS", "GND", (126.5, 168.0), 90)
    add("U12", "Regulator_Linear:AP7361C-33E", "AP7361C-3.3", "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
        (114.0, 176.0), {"1": "VSYS", "2": "GND", "3": "+3V3"}, 0, B)  # fmt: skip
    c("C5", "10u", "VSYS", (107.5, 173.0), 90, fp=C0805)
    c("C6", "10u", "+3V3", (107.5, 179.0), 90, fp=C0805)
    r("R14", "100k", "BAT", "VBAT_DIV", (128.0, 176.0), 90)
    r("R15", "100k", "VBAT_DIV", "GND", (130.0, 176.0), 90)
    c("C7", "100n", "VBAT_DIV", (132.0, 176.0), 90)

    # ---- RP2040 (U1), its flash (U2), crystal (Y1) ------------------------------------------------
    rp = {
        "1": "+3V3", "10": "+3V3", "22": "+3V3", "33": "+3V3", "42": "+3V3", "49": "+3V3",
        "48": "+3V3", "43": "+3V3", "44": "+3V3", "45": "+1V1", "23": "+1V1", "50": "+1V1", "57": "GND",
        "19": "GND", "20": "XIN", "21": "XOUT", "24": "SWCLK", "25": "SWDIO", "26": "RUN",
        "46": "RP_D-", "47": "RP_D+",
        "51": "QSPI_SD3", "52": "QSPI_SCLK", "53": "QSPI_SD0", "54": "QSPI_SD2", "55": "QSPI_SD1", "56": "QSPI_SS",
        "2": "ESP_RXD", "3": "ESP_TXD", "4": "ESP_EN", "5": "ESP_IO0",
        "6": "I2C0_SDA", "7": "I2C0_SCL", "8": "I2C1_SDA", "9": "I2C1_SCL",
        "11": "ADC_MISO", "12": "ADC_CS", "13": "ADC_SCK", "14": "ADC_MOSI",
        "15": "SR_PL", "16": "SR_CLK", "17": "SR_Q", "18": "LED_DATA",
        "27": "PIO_D+", "28": "PIO_D-", "29": "HOST_EN", "30": "FAULT_N",
        "31": "TRIG_L_A", "32": "TRIG_L_B", "34": "TRIG_R_A", "35": "TRIG_R_B",
        "36": "MOT_SLEEP", "37": "IMU_INT", "38": "HAPTIC_EN", "39": "PADDLE_L", "40": "PADDLE_R",
        "41": "CHG_STAT",
    }  # fmt: skip
    U1 = (148.0, 124.0)
    add("U1", "MCU_RaspberryPi:RP2040", "RP2040", "Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm", U1, rp, 0, B)
    # The exposed pad's ground, through 2 vias into the In1 plane: on its lower half, clear of J5's
    # pads on the front.
    for vx in (-0.8, 0.8):
        d.via("GND", U1[0] + vx, U1[1] + 0.8)
    # 4 of the IO supply's caps on the QFN's corners, where it has no pins, the rest a row out: every
    # side of 0.4 mm pins keeps a lane to fan out through (the first route left 35 nets open with
    # a cap against each side).
    for i, (dx, dy, rot) in enumerate([(-5.4, -5.4, 0), (-5.4, 5.4, 0), (5.4, -5.4, 0), (5.4, 5.4, 0),
                                       (-2.2, -8.0, 0), (2.2, -8.0, 0)]):  # fmt: skip
        c(f"C{10 + i}", "100n", "+3V3", (U1[0] + dx, U1[1] + dy), rot)
    c("C16", "1u", "+3V3", (U1[0] - 2.2, U1[1] + 8.0))  # VREG_VIN
    c("C17", "1u", "+1V1", (U1[0] + 2.2, U1[1] + 8.0))  # VREG_VOUT
    c("C18", "100n", "+1V1", (U1[0] + 6.2, U1[1] + 8.0))
    add("Y1", "Device:Crystal_GND24", "12MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm", (139.0, 124.0),
        {"1": "XIN", "2": "GND", "3": "XTAL_O", "4": "GND"}, 90, B)  # fmt: skip
    c("C19", "15p", "XIN", (135.0, 121.5))
    c("C20", "15p", "XTAL_O", (135.0, 126.5))
    r("R16", "1k", "XTAL_O", "XOUT", (138.5, 129.5))
    add("U2", "Memory_Flash:W25Q128JVS", "W25Q128JV", "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm", (148.0, 138.0),
        {"1": "QSPI_SS", "2": "QSPI_SD1", "3": "QSPI_SD2", "4": "GND", "5": "QSPI_SD0", "6": "QSPI_SCLK",
         "7": "QSPI_SD3", "8": "+3V3"}, 0, B)  # fmt: skip
    c("C21", "100n", "+3V3", (153.5, 135.5), 90)
    r("R17", "10k", "QSPI_SS", "+3V3", (142.0, 135.5), 90)
    r("R18", "10k", "RUN", "+3V3", (139.0, 117.5))
    add("SW17", "Switch:SW_Push", "BOOTSEL", SMALL, (136.0, 113.0), {"1": "BOOT_R", "2": "GND"}, 0, B)
    r("R19", "1k", "QSPI_SS", "BOOT_R", (141.5, 113.0))
    add("J10", "Connector_Generic_MountingPin:Conn_01x03_MountingPin", "SWD", SH3, (156.0, 104.5),
        {"1": "SWCLK", "2": "GND", "3": "SWDIO", "MP": "GND"}, 180, B)  # fmt: skip

    # ---- ESP32 (U3): Bluetooth Classic and BLE ----------------------------------------------------
    add("U3", "Rosetta:ESP32-WROOM-32E", "ESP32-WROOM-32E", "RF_Module:ESP32-WROOM-32E", ESP_AT,
        {"2": "+3V3", "1": "GND", "15": "GND", "38": "GND", "39": "GND", "3": "ESP_EN", "25": "ESP_IO0",
         "34": "ESP_RXD", "35": "ESP_TXD"}, 0, B)  # fmt: skip
    # Beside the module's VDD and EN pins (2 and 3, its left column on the back) and IO0 (25).
    c("C22", "10u", "+3V3", (157.0, 149.0), 90, fp=C0805)
    c("C23", "100n", "+3V3", (157.0, 145.3), 90)
    r("R20", "10k", "ESP_EN", "+3V3", (154.4, 149.0), 90)
    c("C24", "1u", "ESP_EN", (154.4, 145.3), 90)
    r("R21", "10k", "ESP_IO0", "+3V3", (181.5, 134.5), 90)

    # ---- the analog inputs: sticks, triggers, knob, cell (U4) ------------------------------------
    U4 = (193.0, 126.0)
    add("U4", "Analog_ADC:MCP3208", "MCP3208", SOIC16, U4,
        {"1": "STICK_LX", "2": "STICK_LY", "3": "STICK_RX", "4": "STICK_RY", "5": "TRIG_L", "6": "TRIG_R",
         "7": "MODE_SENSE", "8": "VBAT_DIV", "9": "GND", "10": "ADC_CS", "11": "ADC_MOSI", "12": "ADC_MISO",
         "13": "ADC_SCK", "14": "GND", "15": "+3V3", "16": "+3V3"}, 90, B)  # fmt: skip
    c("C25", "100n", "+3V3", (U4[0] + 6.5, U4[1] - 4.0), 90)
    c("C26", "1u", "+3V3", (U4[0] + 6.5, U4[1] - 1.0), 90)
    r("R22", "10k", "ADC_CS", "+3V3", (U4[0] + 6.5, U4[1] + 2.0), 90)

    stick = lambda side: {"1": "+3V3", "2": f"STICK_{side}X", "3": f"STICK_{side}Y", "4": f"BTN_{side}3",  # noqa: E731
                          "5": "GND", "MP": "GND"}  # fmt: skip
    add("J5", "Connector_Generic_MountingPin:Conn_01x05_MountingPin", "STICK_L", SH5,
        (STICK_L[0], 125.5), stick("L"), 0)  # fmt: skip
    add("J6", "Connector_Generic_MountingPin:Conn_01x05_MountingPin", "STICK_R", SH5,
        (STICK_R[0], 125.5), stick("R"), 0)  # fmt: skip
    trig = lambda side: {"1": "+3V3", "2": f"TRIG_{side}", "3": "GND", "4": f"MOT_{side}+",  # noqa: E731
                         "5": f"MOT_{side}-", "MP": "GND"}  # fmt: skip
    add("J3", "Connector_Generic_MountingPin:Conn_01x05_MountingPin", "TRIGGER_L", SH5, (127.0, 104.5),
        trig("L"), 180)  # fmt: skip
    add("J4", "Connector_Generic_MountingPin:Conn_01x05_MountingPin", "TRIGGER_R", SH5, (217.0, 104.5),
        trig("R"), 180)  # fmt: skip

    # The knob and its ladder. The taps run from 5/6 of 3.3 V (position 1) down to 1/6 (position 5).
    # 1k steps, not 10k: the ADC's input leaks up to 1 uA, which on a 1 M pull-down would read 1 V
    # between detents, a position. With 100k it reads at most 0.1 V; the deck holds both.
    sw1 = {"C": "MODE_SENSE", "MP": "GND"} | {str(k): f"TAP{k}" for k in range(1, 6)}
    add("SW1", "Switch:SW_SP5T_NR01105", "MODE", "Button_Switch_THT:SW_NKK_NR01",
        (KNOB[0] - 5.08, KNOB[1] - 2.54), sw1, 0)  # fmt: skip
    ladder = ["+3V3", "TAP1", "TAP2", "TAP3", "TAP4", "TAP5", "GND"]
    for k in range(6):
        r(f"R{40 + k}", "1k", ladder[k], ladder[k + 1], (161.6 + 2.4 * k, 130.0), 90)
    # Between the knob's pins and the ESP32 on the back.
    r("R46", "100k", "MODE_SENSE", "GND", (176.0, 130.0), 90)
    c("C27", "100n", "MODE_SENSE", (178.4, 130.0), 90)

    # ---- motors: trigger feedback (U6) and haptics (U9, U10) -------------------------------------
    U6 = (186.0, 110.0)
    add("U6", "Driver_Motor:DRV8833PW", "DRV8833", "Package_SO:TSSOP-16_4.4x5mm_P0.65mm", U6,
        {"1": "MOT_SLEEP", "2": "MOT_L+", "3": "ISEN_A", "4": "MOT_L-", "5": "MOT_R-", "6": "ISEN_B", "7": "MOT_R+",
         "8": "FAULT_N", "9": "TRIG_R_A", "10": "TRIG_R_B", "11": "VCP", "12": "VSYS", "13": "GND",
         "14": "VINT", "15": "TRIG_L_B", "16": "TRIG_L_A"}, 90, B)  # fmt: skip
    c("C28", "10u", "VSYS", (U6[0] - 5.0, U6[1] - 2.0), 90, fp=C0805)
    c("C29", "2.2u", "VINT", (U6[0] - 5.0, U6[1] + 2.0), 90)
    c("C30", "10n", "VCP", (U6[0] + 5.0, U6[1] + 2.0), 90, b="VSYS")
    r("R23", "100k", "MOT_SLEEP", "GND", (U6[0] + 5.0, U6[1] - 2.0), 90)
    r("R24", "10k", "FAULT_N", "+3V3", (194.0, 113.0), 90)
    # Each bridge's current through 0.5 ohm: the DRV8833 chops at 200 mV, 400 mA, so a stalled
    # trigger motor is held there.
    r("R50", "0.5", "ISEN_A", "GND", (190.5, 116.5), 90)
    r("R51", "0.5", "ISEN_B", "GND", (190.5, 119.6), 90)

    for side, ref, at, bus, jref, jat in (
        ("L", "U9", (112.0, 152.0), "I2C0", "J7", (110.0, 163.0)),
        ("R", "U10", (228.0, 152.0), "I2C1", "J8", (230.0, 163.0)),
    ):
        add(ref, "Driver:DRV2605LDGS", "DRV2605L", "Package_SO:TSSOP-10_3x3mm_P0.5mm", at,
            {"1": f"REG_{side}", "2": f"{bus}_SCL", "3": f"{bus}_SDA", "4": "GND", "5": "HAPTIC_EN",
             "6": "VSYS", "7": f"LRA_{side}+", "8": "GND", "9": f"LRA_{side}-", "10": "VSYS"}, 0, B)  # fmt: skip
        k = 31 if side == "L" else 34
        c(f"C{k}", "1u", f"REG_{side}", (at[0] - 4.0, at[1] + 2.0), 90)
        c(f"C{k + 1}", "1u", "VSYS", (at[0] + 4.0, at[1] - 2.0), 90)
        c(f"C{k + 2}", "100n", "VSYS", (at[0] + 4.0, at[1] + 2.0), 90)
        add(jref, "Connector_Generic_MountingPin:Conn_01x02_MountingPin", f"LRA_{side}", SH2, jat,
            {"1": f"LRA_{side}+", "2": f"LRA_{side}-", "MP": "GND"}, 0)  # fmt: skip
    r("R25", "100k", "HAPTIC_EN", "GND", (118.0, 150.0), 90)

    # ---- the IMU (U5) and the I2C pull-ups ------------------------------------------------------
    U5 = (184.0, 118.0)
    add("U5", "Sensor_Motion:LSM6DSL", "LSM6DSL", "Package_LGA:LGA-14_3x2.5mm_P0.5mm_LayoutBorder3x4y", U5,
        {"1": "IMU_SA0", "2": "IMU_SA0", "3": "GND", "4": "IMU_INT", "5": "+3V3", "6": "GND", "7": "GND", "8": "+3V3",
         "12": "+3V3", "13": "I2C0_SCL", "14": "I2C0_SDA"}, 0, B)  # fmt: skip
    # SA0 low (address 0x6A), and the unused aux bus's SDx with it, through 10k.
    r("R52", "10k", "IMU_SA0", "GND", (U5[0], U5[1] + 3.8), 90)
    c("C37", "100n", "+3V3", (U5[0] + 3.5, U5[1] - 1.0), 90)
    c("C38", "100n", "+3V3", (U5[0] + 3.5, U5[1] + 2.0), 90)
    for k, net in enumerate(("I2C0_SDA", "I2C0_SCL", "I2C1_SDA", "I2C1_SCL")):
        r(f"R{26 + k}", "4.7k", net, "+3V3", (140.0 + 2.4 * k, 108.5), 90)

    # ---- buttons: 16 on 2 shift registers (U7 left, U8 right), each input pulled up -------------
    left = ["UP", "DOWN", "LEFT", "RIGHT", "L1", "L3", "SHARE", "HOME"]
    right = ["Y", "B", "A", "X", "R1", "R3", "OPTIONS", "CAPTURE"]
    shift = {"1": "SR_PL", "2": "SR_CLK", "8": "GND", "15": "GND", "16": "+3V3"}
    order = ["11", "12", "13", "14", "3", "4", "5", "6"]  # D0..D7
    add("U7", "74xx:74HC165", "74HC165", SOIC16, (126.0, 140.0),
        shift | {"10": "GND", "9": "SR_MID"} | {p: f"BTN_{n}" for p, n in zip(order, left, strict=True)}, 0, B)  # fmt: skip
    add("U8", "74xx:74HC165", "74HC165", SOIC16, (214.0, 140.0),
        shift | {"10": "SR_MID", "9": "SR_Q"} | {p: f"BTN_{n}" for p, n in zip(order, right, strict=True)}, 0, B)  # fmt: skip
    # The RP2040's pins float in reset: hold the registers' load and clock, and the LEDs' data.
    r("R47", "10k", "SR_PL", "+3V3", (156.5, 116.2))
    r("R48", "100k", "SR_CLK", "GND", (156.5, 118.0))
    r("R49", "100k", "LED_DATA", "GND", (156.5, 119.8))
    c("C39", "100n", "+3V3", (126.0, 133.5))
    c("C40", "100n", "+3V3", (214.0, 133.5))
    for k, (names, at) in enumerate(((left[:4], (120.0, 140.0)), (left[4:], (132.0, 140.0)),
                                      (right[:4], (208.0, 140.0)), (right[4:], (220.0, 140.0)))):  # fmt: skip
        add(f"RN{k + 1}", "Device:R_Pack04", "10k", RPACK, at,
            {"1": f"BTN_{names[0]}", "2": f"BTN_{names[1]}", "3": f"BTN_{names[2]}", "4": f"BTN_{names[3]}",
             "5": "+3V3", "6": "+3V3", "7": "+3V3", "8": "+3V3"}, 0, B)  # fmt: skip

    def button(ref, name, at, rot=0.0, fp=TACT, layer="F.Cu", net=None):
        add(ref, "Switch:SW_Push", name, fp, at, {"1": net or f"BTN_{name}", "2": "GND"}, rot, layer)

    dx, dy = DPAD
    button("SW2", "UP", (dx, dy - 7.5))
    button("SW3", "DOWN", (dx, dy + 7.5))
    button("SW4", "LEFT", (dx - 7.5, dy), 90)
    button("SW5", "RIGHT", (dx + 7.5, dy), 90)
    fx, fy = FACE
    button("SW6", "Y", (fx, fy - 7.5))
    button("SW7", "A", (fx, fy + 7.5))
    button("SW8", "X", (fx - 7.5, fy), 90)
    button("SW9", "B", (fx + 7.5, fy), 90)
    button("SW10", "L1", (113.5, 107.5))
    button("SW11", "R1", (226.5, 107.5))
    button("SW12", "SHARE", (150.0, 111.0), fp=SMALL)
    button("SW13", "OPTIONS", (190.0, 111.0), fp=SMALL)
    button("SW14", "HOME", (170.0, 137.5), fp=SMALL)
    button("SW18", "CAPTURE", (150.0, 117.0), fp=SMALL)
    button("SW15", "PADDLE_L", (112.0, 184.0), layer=B, net="PADDLE_L")
    button("SW16", "PADDLE_R", (228.0, 184.0), layer=B, net="PADDLE_R")

    # ---- the light ring: 5 RGB LEDs round the knob, data level-shifted to VSYS (U14) -----------
    add("U14", "74xGxx:74AHCT1G125", "74AHCT1G125", "Package_TO_SOT_SMD:SOT-23-5", (151.0, 113.0),
        {"1": "GND", "2": "LED_DATA", "3": "GND", "4": "LED_D0", "5": "VSYS"}, 0, B)  # fmt: skip
    c("C41", "100n", "VSYS", (147.5, 113.0), 90)
    chain = ["LED_D0", "LED_D1", "LED_D2", "LED_D3", "LED_D4", "LED_D5"]
    for k, (deg, label) in enumerate(MODES):
        a = math.radians(deg)
        at = (round(KNOB[0] + RING_R * math.cos(a), 3), round(KNOB[1] - RING_R * math.sin(a), 3))
        add(f"D{k + 2}", "LED:WS2812B-2020", label, "LED_SMD:LED_WS2812B-2020_PLCC4_2.0x2.0mm", at,
            {"2": "GND", "3": chain[k], "4": "VSYS"} | ({"1": chain[k + 1]} if k + 1 < len(MODES) else {}),
            90 - deg)  # fmt: skip
        d.text(label, *label_at(deg), "F.SilkS", 1.0, 0.15)
        c(f"C{42 + k}", "100n", "VSYS", at, 90 - deg, layer=B)  # behind its LED

    # ---- the faces' words, and what sits over the face ------------------------------------------
    for label, x, y in (("L1", 113.5, 112.0), ("R1", 226.5, 112.0), ("Y", fx, fy - 11.8), ("A", fx, fy + 11.8),
                        ("X", fx - 12.0, fy), ("B", fx + 12.0, fy), ("SHARE", 150.0, 108.2), ("OPTIONS", 190.0, 108.2),
                        ("CAPTURE", 150.0, 120.0), ("HOME", 170.0, 140.6), ("ROSETTA v0.1", 170.0, 147.0)):  # fmt: skip
        d.text(label, x, y, "F.SilkS", 1.0, 0.15)
    for name, (x, y) in (("left stick", STICK_L), ("right stick", STICK_R)):
        d.keepout(d.circle(x, y, STICK_R_ZONE), layers=("F.Cu",), name=name, parts=True, copper=False)

    # By hand: the IMU's supply pins (5, 8) and C37 to C38 and the rest of +3V3. 3 routes in a row
    # left this pair apart; each piece was probed clear (`workcenter inspect probe`) on a routed board.
    d.via("+3V3", 186.5, 118.0)
    d.via("+3V3", 186.5, 121.3)
    d.track("+3V3", [(187.5, 117.8), (186.5, 118.0)], "B.Cu")
    d.track("+3V3", [(186.5, 118.0), (186.5, 121.3)], "F.Cu")
    d.track("+3V3", [(186.5, 121.3), (187.5, 120.8)], "B.Cu")

    # 3D bodies for the 3 parts KiCad's 3D library has none for (models/make_models.py).
    d.model("SW1", "${KIPRJMOD}/models/nr01.wrl", replace=True)
    d.model("J9", "${KIPRJMOD}/models/jst_ph_s2b_sm4.wrl", replace=True)
    for k in range(len(MODES)):
        d.model(f"D{k + 2}", "${KIPRJMOD}/models/ws2812b_2020.wrl", replace=True)

    # Pulls the board does not hold itself, each with what holds it.
    d.defined_nets = {
        "CHG_STAT": "GPIO29's internal pull-up, set in firmware (the charger's STAT is push-pull or high-Z)",
        "PADDLE_L": "GPIO27's internal pull-up, set in firmware",
        "PADDLE_R": "GPIO28's internal pull-up, set in firmware",
        "IMU_INT": "the LSM6DSL drives INT1 push-pull",
        "SR_Q": "U8 drives Q7",
        "SR_MID": "U7 drives Q7",
        "LED_D0": "U14 drives it: its OE (pin 1) is tied to GND",
        "SWCLK": "the RP2040's internal pull-up on SWCLK (datasheet 2.3.4)",
        "XIN": "the crystal Y1 and C19; the RP2040's oscillator drives the pair",
        "BOOT_R": "R19 (1k) to QSPI_SS, which R17 pulls up to +3V3",
    }
    for net in ("ADC_SCK", "ADC_MOSI"):
        d.defined_nets[net] = "R22 holds ADC_CS high in reset, and the MCP3208 ignores its clock and data then"
    for net in ("TAP2", "TAP3", "TAP4"):
        d.defined_nets[net] = "the ladder R40-R45 holds every tap between +3V3 and GND"
    for k, names in enumerate((left[:4], left[4:], right[:4], right[4:])):
        for name in names:
            d.defined_nets[f"BTN_{name}"] = f"RN{k + 1}, a 10k in a 4-resistor pack to +3V3"
    for net in ("STICK_LX", "STICK_LY", "STICK_RX", "STICK_RY", "TRIG_L", "TRIG_R"):
        d.defined_nets[net] = "the Hall sensor in the plugged module drives it; firmware reads a missing one as out of range"
    for net in ("TRIG_L_A", "TRIG_L_B", "TRIG_R_A", "TRIG_R_B"):
        d.defined_nets[net] = "the DRV8833's inputs have internal pull-downs, and R23 holds nSLEEP low in reset"
    d.check_pulls = True
    # No reference designators on the silkscreen: the front's own words name every button, and 140
    # references at this density print over pads and each other. The assembly drawing has them.
    for part in d.parts:
        part.hide_ref = True
    lay_out_schematic(d)
    return d
