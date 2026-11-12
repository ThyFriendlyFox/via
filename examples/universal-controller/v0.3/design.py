"""Rosetta v0.2: one game controller for a PS4, a PS5, an Xbox, a Switch or anything over Bluetooth,
picked with a 5-position knob, on a board shaped and laid out like an Xbox 360 controller's.

What v0.2 changes from v0.1: the board is the controller's own main board, not a carrier for
modules. Everything a hand touches is on it.

- The thumbsticks (SL, SR) solder on: ALPS RKJXV122400R holes (Footprint Rosetta.pretty, from the
  catalog's mounting drawing), which Hall-effect drop-in sticks share. Each axis is VCC, output, GND.
  Their prohibited wiring areas are keep-outs on the front.
- The triggers read on-board linear Hall sensors (U15, U16, DRV5055A1) under each trigger's magnet,
  on the shoulder horns, beside each trigger's mounting hole.
- The bumpers (SW10, SW11) are right-angle switches on the horns' top edges.
- 2 rumble motors on J7 and J8 in the grips, driven by the DRV8833 (U6), as the 360's are.
- The outline: 2 shoulder horns, a dip between them where the ESP32's antenna hangs out, the grips
  and a tab at the bottom with both USB-C ports.

The knob (SW1 and its ladder R40-R46), the auth donor port (J2), the RP2040, the ESP32, the ADC,
the IMU, the shift registers and the light ring work as in v0.1.

    workcenter design design.py --route --passes 40 --timeout 3500     # from this folder

Board: 148 x 82 mm, 6 layers (F.Cu signal, In1.Cu GND plane, In2.Cu to In4.Cu signal, B.Cu signal). The
front carries what a hand touches; the back carries the electronics.
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

STICK = "Rosetta:Thumbstick_ALPS_RKJXV122400R"
BUMPER = "Button_Switch_THT:SW_Tactile_SPST_Angled_PTS645Vx31-2LFS"
HOLE = "MountingHole:MountingHole_2.5mm_Pad"

# The outline, clockwise from the left horn's top left: (x, y, radius). The dip between the horns
# and the corners beside the bottom tab turn the other way (concave).
CORNERS[:] = [
    (96.0, 100.0, 10.0),  # left horn, outer
    (132.0, 100.0, 6.0),  # left horn, inner
    (140.0, 112.0, 6.0),  # the dip, left (concave)
    (180.0, 112.0, 6.0),  # the dip, right (concave)
    (188.0, 100.0, 6.0),  # right horn, inner
    (224.0, 100.0, 10.0),  # right horn, outer
    (234.0, 136.0, 14.0),  # right shoulder
    (212.0, 168.0, 12.0),  # right grip
    (184.0, 170.0, 6.0),  # beside the tab, right (concave)
    (178.0, 182.0, 5.0),  # the tab, right
    (142.0, 182.0, 5.0),  # the tab, left
    (136.0, 170.0, 6.0),  # beside the tab, left (concave)
    (108.0, 168.0, 12.0),  # left grip
    (86.0, 136.0, 14.0),  # left shoulder
]
DIP_Y = 112.0  # the edge between the horns: the ESP32's antenna hangs past it
TAB_Y = 182.0  # the bottom tab's edge: the 2 USB-C ports open through it

# ---- where things are ---------------------------------------------------------------------------
KNOB = (160.0, 144.0)  # the centre of SW1's shaft, where the 360 has its guide button
RING_R = 10.5  # the LEDs' circle round it
LABEL_R = 13.6  # the modes' names, outside the LEDs
STICK_L = (112.0, 128.0)  # left stick high, as an Xbox pad has it
STICK_R = (182.0, 154.0)  # right stick low, 3 mm lower than v0.2's to clear its LED ring
DPAD = (138.0, 151.0)
STICK_RING_R = 15.0  # each stick's ring of 8 LEDs, just outside its footprint's courtyard
STICK_RING_PHASE = 22.5  # the first LED's angle: 8 LEDs between the stick's 4 directions
OLED_AT = (177.5, 114.6)  # the screen module's pin 1; its body runs left across the dip
OLED_ROT = 270
FACE = (208.0, 127.0)
# The ESP32 module on the back, turned so its antenna hangs past the dip's edge into the air
# between the horns: the antenna's clearance (the bar of its courtyard) is off the board.
ESP_AT = (160.0, DIP_Y + 6.31)


def label_at(deg: float) -> tuple[float, float]:
    """Where a mode's name sits: outside its LED, the top one closer in."""
    r = 12.4 if deg == 90 else LABEL_R
    a = math.radians(deg)
    return (round(KNOB[0] + r * math.cos(a), 2), round(KNOB[1] - r * math.sin(a), 2))


# The 5 modes, left to right round the top of the knob: the angle of each LED on the ring, its label.
MODES = [(162, "PS4"), (126, "PS5"), (90, "XBOX"), (54, "SWITCH"), (18, "BT")]


def usb_at(x: float) -> tuple[float, float]:
    """A GCT USB4085's place for a receptacle centred on x that opens out of the bottom tab: the
    footprint's origin is pin A1, 2.975 mm from its centre line, at rotation 0."""
    return (x - 2.975, TAB_Y - 7.6)


def stick_keepouts(d: kicadgen.Design, x: float, y: float, name: str) -> None:
    """The stick's prohibited wiring area from its mounting drawing, as keep-outs on the front: d4 at
    the centre, d3.5 at (0, 8), the 2.2 mm slot between, and 4 x d2.6 at (+-3.5, +-3.4)."""
    for k, (cx, cy, r) in enumerate([(0, 0, 2.0), (0, 8, 1.75), (-3.5, -3.4, 1.3), (3.5, -3.4, 1.3),
                                      (-3.5, 3.4, 1.3), (3.5, 3.4, 1.3)]):  # fmt: skip
        d.keepout(d.circle(x + cx, y + cy, r, 16), layers=("F.Cu",), name=f"{name} {k}")
    d.keepout([(x - 1.1, y), (x + 1.1, y), (x + 1.1, y + 8), (x - 1.1, y + 8)], layers=("F.Cu",), name=f"{name} slot")


# ---- the schematic: blocks, each IC with its own parts; labels between blocks -----------------
BLOCKS = [
    # name, sheet origin in 2.54 mm steps (the A1 sheet is 331 x 234 steps), the parts
    ("console USB", (12, 14), ["J1", "R1", "R2", "R3", "R4"]),
    ("auth port", (12, 52), ["J2", "R5", "R6", "R7", "R8", "R9", "R10", "U13", "C1", "C2", "R11"]),
    ("power", (12, 100), ["J9", "U11", "U17", "U12", "L1", "L2", "R12", "R13", "R15", "C3", "C4", "C5", "C6", "C7",
                          "C8", "C9", "R14", "R53", "C51", "C52", "C47", "C48", "C49", "C50", "R54", "R55", "C53"]),
    ("screen", (12, 185), ["DS1", "C54"]),
    ("mechanical", (60, 185), ["H1", "H2", "H3", "H4"]),
    ("RP2040", (115, 14), ["U1", "C10", "C11", "C12", "C13", "C14", "C15", "C16", "C17", "C18", "Y1", "C19", "C20",
                          "R16", "U2", "C21", "R17", "R18", "SW17", "R19", "J10", "R26", "R27", "R47", "R48", "R49"]),
    ("ESP32", (115, 105), ["U3", "C22", "C23", "R20", "C24", "R21"]),
    ("knob ring", (115, 150), ["U14", "C41", "D2", "D3", "D4", "D5", "D6", "C42", "C43", "C44", "C45", "C46"]),
    ("stick rings", (115, 190), [f"D{k}" for k in range(7, 23)] + [f"C{k}" for k in range(55, 63)]),
    ("sticks, ADC, knob", (200, 14), ["U4", "C25", "C26", "R22", "SL", "SR", "SW1", "R40", "R41", "R42", "R43",
                                       "R44", "R45", "R46", "C27"]),
    ("rumble", (200, 70), ["U6", "C28", "C29", "C30", "R23", "R24", "R50", "R51", "J7", "J8"]),
    ("IMU", (200, 125), ["U5", "R52", "C37", "C38"]),
    ("triggers", (200, 165), ["U15", "U16", "C31", "C32"]),
    ("buttons", (245, 125), ["U7", "C39", "RN1", "RN2", "U8", "C40", "RN3", "RN4", "SW2", "SW3", "SW4", "SW5", "SW6",
                             "SW7", "SW8", "SW9", "SW10", "SW11", "SW12", "SW13", "SW14", "SW18", "SW15", "SW16",
                             "SW19", "SW20"]),
]

def lay_out_schematic(d: kicadgen.Design) -> None:
    """Each block's ICs in a row, its small parts in rows of 8 under them. A net that stays in 1
    block is drawn as a wire; a net that joins 2 blocks is a label at each pin."""
    g = 2.54
    parts = {p.ref: p for p in d.parts}
    block_of = {}
    for name, (bx, by), refs in BLOCKS:
        x, col_h = bx, 0
        big = [r for r in refs if not (r[0] in "RCDQYHL" or r.startswith(("SW", "RN")))]
        small = [r for r in refs if r not in big]
        for ref in big:
            p = parts[ref]
            xs = [pin.x for pin in p.symbol.pins] or [0]
            ys = [pin.y for pin in p.symbol.pins] or [0]
            w = (max(xs) - min(xs)) / g + 6
            h = (max(ys) - min(ys)) / g + 6
            p.sch_at = ((x + round(w / 2)) * g, (by + round(h / 2)) * g)
            p.sch_rot = 0
            x += round(w) + 4
            col_h = max(col_h, round(h))
            block_of[ref] = name
        sx, sy = bx, by + col_h + 6
        for k, ref in enumerate(small):
            p = parts[ref]
            p.sch_at = ((sx + 10 * (k % 8)) * g, (sy + 9 * (k // 8)) * g)
            p.sch_rot = 0
            block_of[ref] = name
    missing = [r for r in parts if r not in block_of]
    if missing:
        raise ValueError(f"no block for {missing}")
    blocks_of_net = {}
    for p in d.parts:
        for net in p.nets.values():
            blocks_of_net.setdefault(net, set()).add(block_of[p.ref])
    d.sch_label_nets = tuple(sorted(n for n, b in blocks_of_net.items() if len(b) > 1 and n not in d.power_nets))
    d.sch_wires = True


def build() -> kicadgen.Design:
    d = ControllerDesign(
        name="rosetta",
        namespace=uuid.UUID("9b2f6c41-5d0e-4a8b-b3c7-2e8f1a6d4c90"),
        outline=(86.0, 100.0, 234.0, 182.0),
        sheet="A1",
        # 6 layers: F.Cu, In1.Cu a whole GND plane, In2-In4 signal, B.Cu. On 4 the RP2040's 0.4 mm
        # pins had 1 inner layer to fan out on, and every route left 2 to 6 of them open.
        copper_layers=6,
        plane_layers=("In1.Cu",),
        track_width=0.2,
        clearance=0.15,
        via_size=0.45,
        via_drill=0.2,
    )
    here = Path(__file__).resolve().parent
    d.symbol_dirs = {"Rosetta": here / "symbols" / "rosetta.kicad_sym"}
    d.footprint_dirs = {"Rosetta": here / "footprints" / "Rosetta.pretty"}
    d.power_nets = {
        "GND": "GND", "VBUS": "VBUS", "VSYS": "VCC", "BAT": "+BATT", "+3V3": "+3V3", "+1V1": "+1V1",
        "VBUS_HOST": "VBUS", "VINT": "VINT",
    }  # fmt: skip
    # No power-output pin drives these: VBUS comes in on J1, VSYS and BAT through the charger's
    # passive SYS and BAT pins.
    d.flagged_nets = ["GND", "VBUS", "VSYS", "VINT", "BAT"]
    d.net_classes = {
        # 0.4 mm: the widest track that enters the charger's 0.5 mm pins with 0.15 mm to the next;
        # up to 3 A in, 2.5 A to the cell, on short runs in the left grip.
        "power": {"width": 0.4, "clearance": 0.15, "via": 0.6, "via_drill": 0.3,
                  "nets": ["VBUS", "VSYS", "BAT", "BAT_N", "PMID", "CHG_SW", "BB_L1", "BB_L2", "VBUS_HOST"]},
        # 0.25 mm and 0.45 mm vias: the rails enter the RP2040's 0.4 mm pins (0.3 mm and 0.6 mm vias
        # left 3 of its supply pins open on every route). Under 300 mA on any branch.
        "rail": {"width": 0.25, "clearance": 0.15, "via": 0.45, "via_drill": 0.2, "nets": ["+3V3", "+1V1"]},
        # 0.3 mm: a motor draws 400 mA at most (R50, R51), about 70 mV over the 100 mm run to J7.
        "motor": {"width": 0.3, "clearance": 0.15, "via": 0.6, "via_drill": 0.3,
                  "nets": ["MOT_L+", "MOT_L-", "MOT_R+", "MOT_R-"]},
    }  # fmt: skip
    d.rules = {"min_through_hole_diameter": 0.2, "min_via_diameter": 0.45, "min_text_height": 0.8, "min_text_thickness": 0.12}
    d.zone("GND", layers=("In1.Cu",), connect="solid")

    def add(ref, lib, value, fp, at, nets, rot=0.0, layer="F.Cu"):
        return d.add(ref, lib, value, fp, sch_at=(0.0, 0.0), pcb_at=at, pcb_rot=rot, pcb_layer=layer, nets=nets)

    def r(ref, value, a, b, at, rot=0.0, layer=B, fp=R0603):
        return add(ref, "Device:R", value, fp, at, {"1": a, "2": b}, rot, layer)

    def c(ref, value, a, at, rot=0.0, layer=B, b="GND", fp=C0603):
        return add(ref, "Device:C", value, fp, at, {"1": a, "2": b}, rot, layer)

    # ---- USB to the console (J1) and to the auth donor (J2), both through the bottom tab ----------
    usb = {"A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS", "A1": "GND", "A12": "GND", "B1": "GND",
           "B12": "GND", "SH": "GND", "A5": "CC1", "B5": "CC2", "A6": "USB_D+", "B6": "USB_D+",
           "A7": "USB_D-", "B7": "USB_D-"}  # fmt: skip
    J1X, J2X = 152.5, 167.5
    add("J1", "Connector:USB_C_Receptacle_USB2.0_16P", "CONSOLE", USBC, usb_at(J1X), usb)
    r("R1", "5.1k", "CC1", "GND", (J1X - 3.0, 170.0), 90)  # a device's Rd on each CC pin
    r("R2", "5.1k", "CC2", "GND", (J1X - 0.6, 170.0), 90)
    r("R3", "27", "USB_D+", "RP_D+", (J1X + 1.8, 170.0), 90)
    r("R4", "27", "USB_D-", "RP_D-", (J1X + 4.2, 170.0), 90)
    # By hand: J1's CC pins to their pull-downs, under and between the receptacle's 2 rows of pins.
    # The 30-pass route left both open; each piece was probed clear on that board.
    d.via("CC1", 148.6, 171.6)
    d.track("CC1", [(149.5, 170.82), (148.6, 171.6)], "B.Cu")
    d.track("CC1", [(148.6, 171.6), (148.6, 173.2), (151.22, 173.6), (151.22, 174.4)], "F.Cu")
    d.via("CC2", 151.9, 172.3)
    d.track("CC2", [(151.9, 170.82), (151.9, 172.3)], "B.Cu")
    d.track("CC2", [(151.9, 172.3), (156.1, 172.3), (156.1, 175.08), (153.78, 175.08), (153.78, 175.75)], "F.Cu")
    # And J2's CC2 the same way, 15 mm to the right.
    d.via("HCC2", 165.7, 172.3)
    d.track("HCC2", [(165.7, 170.82), (165.7, 172.3)], "B.Cu")
    d.track("HCC2", [(165.7, 172.3), (171.1, 172.3), (171.1, 175.08), (168.78, 175.08), (168.78, 175.75)], "F.Cu")
    host = {k: v.replace("VBUS", "VBUS_HOST").replace("CC", "HCC").replace("USB_D", "HOST_D")
            for k, v in usb.items()}  # fmt: skip
    add("J2", "Connector:USB_C_Receptacle_USB2.0_16P", "AUTH", USBC, usb_at(J2X), host)
    r("R5", "56k", "HCC1", "VBUS_HOST", (J2X - 4.2, 170.0), 90)  # a source's Rp: default USB power
    r("R6", "56k", "HCC2", "VBUS_HOST", (J2X - 1.8, 170.0), 90)
    r("R7", "27", "HOST_D+", "PIO_D+", (J2X + 0.6, 170.0), 90)
    r("R8", "27", "HOST_D-", "PIO_D-", (J2X + 3.0, 170.0), 90)
    r("R9", "15k", "HOST_D+", "GND", (J2X + 0.6, 166.6), 90)  # a host's pull-downs
    r("R10", "15k", "HOST_D-", "GND", (J2X + 3.0, 166.6), 90)
    add("U13", "Power_Management:TPS2051CDBV", "TPS2051C", "Package_TO_SOT_SMD:SOT-23-5", (J2X - 2.0, 162.5),
        {"1": "VBUS_HOST", "2": "GND", "3": "FAULT_N", "4": "HOST_EN", "5": "VBUS"}, 0, B)  # fmt: skip
    c("C1", "1u", "VBUS", (J2X - 6.0, 162.5), 90)
    c("C2", "10u", "VBUS_HOST", (J2X + 2.5, 162.5), 90, fp=C0805)
    r("R11", "100k", "HOST_EN", "GND", (J2X - 2.0, 159.0))  # the donor port is off in reset

    # ---- power, in the left grip: cell, charger with power path, fuel gauge, 3.3 V buck-boost ---
    # The cell: a 1-cell Li-ion pack with its 10k NTC (103AT) on a 3-way JST PH, on the back.
    add("J9", "Connector_Generic_MountingPin:Conn_01x03_MountingPin", "BATTERY",
        "Connector_JST:JST_PH_S3B-PH-SM4-TB_1x03-1MP_P2.00mm_Horizontal", (106.0, 151.0),
        {"1": "BAT", "2": "TS", "3": "BAT_N", "MP": "GND"}, 0, B)  # fmt: skip
    # U11, BQ25895: a 5 A switching charger whose power path runs the controller from USB with a flat
    # or missing cell, so USB-C is a data cable whatever the cell holds. Firmware sets 2.5 A into the
    # cell over I2C; ILIM (R12, 120 ohm) caps the input at 355/120 = 2.96 A, what a 5 V/3 A USB-C
    # source gives. D+ and D- are left open: with no BC1.2 or HVDCP handshake the charger never asks
    # a quick charger for 9 or 12 V, which would reach the auth donor's 5 V port through U13.
    add("U11", "Battery_Management:BQ25895RTW", "BQ25895", "Package_DFN_QFN:Texas_RTW_WQFN-24-1EP_4x4mm_P0.5mm_EP2.7x2.7mm_ThermalVias",
        (118.0, 152.0), {"1": "VBUS", "4": "CHG_STAT", "5": "I2C0_SCL", "6": "I2C0_SDA", "7": "CHG_INT",
                         "8": "GND", "9": "GND", "10": "ILIM", "11": "TS", "13": "BAT", "14": "BAT", "15": "VSYS",
                         "16": "VSYS", "17": "GND", "18": "GND", "25": "GND", "19": "CHG_SW", "20": "CHG_SW",
                         "21": "BTST", "22": "REGN", "23": "PMID"}, 0, B)  # fmt: skip
    add("L1", "Device:L", "1u", "Inductor_SMD:L_Coilcraft_XAL4020-XXX", (118.0, 159.5),
        {"1": "CHG_SW", "2": "VSYS"}, 0, B)  # fmt: skip
    r("R12", "120", "ILIM", "GND", (113.5, 156.6), 90)  # clear of PMID's neck
    r("R13", "5.23k", "REGN", "TS", (122.6, 155.5), 90)  # the TS divider of TI's BQ2589x EVM for a 103AT
    r("R15", "30.1k", "TS", "GND", (125.0, 155.5), 90)
    c("C3", "1u", "VBUS", (113.5, 149.0), 90)
    c("C4", "10u", "PMID", (113.5, 152.5), 90, fp=C0805)
    c("C5", "47n", "BTST", (122.6, 149.0), 90, b="CHG_SW")
    c("C6", "4.7u", "REGN", (125.0, 149.0), 90)
    c("C7", "10u", "VSYS", (123.0, 160.5), 90, fp=C0805)
    c("C8", "10u", "VSYS", (125.4, 160.5), 90, fp=C0805)
    c("C9", "10u", "BAT", (127.8, 160.5), 90, fp=C0805)
    # U17, BQ27441: the fuel gauge the screen reads. It counts charge through R14 (10 mOhm) in the
    # cell's return; SRP is the cell's side.
    add("U17", "Battery_Management:BQ27441-G1", "BQ27441-G1", "Package_SON:Texas_S-PDSO-N12", (134.0, 165.0),
        {"1": "I2C0_SDA", "2": "I2C0_SCL", "3": "GND", "5": "GAUGE_VDD", "6": "BAT", "7": "GND", "8": "BAT_N",
         "10": "GAUGE_BIN", "13": "GND"}, 0, B)  # fmt: skip
    r("R14", "10m", "BAT_N", "GND", (108.5, 157.6), 0, fp="Resistor_SMD:R_0805_2012Metric")
    r("R53", "10k", "GAUGE_BIN", "GND", (131.2, 161.6), 0)  # the cell is always in: BIN held low
    c("C51", "470n", "GAUGE_VDD", (137.4, 167.0), 90)
    c("C52", "100n", "BAT", (139.4, 166.0), 90)
    # U12, TPS63001: a buck-boost that holds +3V3 from the cell's 4.35 V down to its end, where the
    # v0.1 regulator dropped out. PS/SYNC low: power save at light load, for battery life.
    add("U12", "Regulator_Switching:TPS63001", "TPS63001", "Package_SON:Texas_DRC0010J_ThermalVias", (116.0, 166.0),
        {"1": "+3V3", "2": "BB_L2", "3": "GND", "4": "BB_L1", "5": "VSYS", "6": "VSYS", "7": "GND", "8": "VSYS",
         "9": "GND", "10": "+3V3", "11": "GND"}, 0, B)  # fmt: skip
    add("L2", "Device:L", "1.5u", "Inductor_SMD:L_Coilcraft_LPS4018", (122.0, 166.0), {"1": "BB_L1", "2": "BB_L2"}, 90, B)
    c("C47", "10u", "VSYS", (112.0, 166.0), 90, fp=C0805)
    c("C48", "10u", "+3V3", (127.0, 165.0), 90, fp=C0805)
    c("C49", "10u", "+3V3", (129.4, 165.0), 90, fp=C0805)
    c("C50", "100n", "VSYS", (114.6, 163.2))

    # Necks out of the 0.5 mm pins of U11, U12 and U17 (P4 step 11). The power class's 0.4 mm does
    # not fit between them, and an 8-pass route left each of these open. Each pin leaves at its own
    # width and widens past the pad row.
    d.track("GND", [(114.6, 166.0), (115.4, 166.0)], B, width=0.24)  # U12 PGND to its pad
    d.track("VSYS", [(117.4, 166.0), (118.2, 166.0), (118.2, 165.0), (117.4, 165.0)], B, width=0.24)  # VINA, EN
    d.track("VSYS", [(118.2, 165.5), (119.0, 165.5)], B, width=0.24)
    for y in (165.5, 166.5):  # PS/SYNC and GND, inside the VSYS neck: in to the pad
        d.track("GND", [(117.4, y), (116.7, y)], B, width=0.24)
    d.via("VSYS", 119.0, 165.5)
    d.track("VSYS", [(113.825, 163.2), (114.6, 164.0), (114.6, 165.0)], B, width=0.24)  # C50 to VIN
    d.track("GND", [(115.375, 163.2), (115.6, 163.7), (115.6, 164.6)], B, width=0.24)
    # The charge path: BAT's 2 pins into a bar and 2 vias.
    d.track("BAT", [(119.963, 150.75), (120.9, 150.75)], B, width=0.25)
    d.track("BAT", [(119.963, 151.25), (120.9, 151.25)], B, width=0.25)
    d.track("BAT", [(120.9, 149.6), (120.9, 151.25)], B, width=0.5)
    d.track("BAT", [(120.9, 150.6), (121.6, 150.6)], B, width=0.5)
    d.via("BAT", 120.9, 149.6)
    d.via("BAT", 121.6, 150.6)
    # PMID to its capacitor, under the package's edge.
    d.track("PMID", [(117.25, 153.963), (117.25, 154.85)], B, width=0.25)
    d.track("PMID", [(117.25, 154.85), (114.4, 154.85), (113.9, 154.35), (113.9, 153.6)], B, width=0.4)
    # The gauge's sense pin SRP out to a via.
    d.track("BAT_N", [(135.9, 164.4), (137.0, 164.4)], B, width=0.2)
    d.via("BAT_N", 137.0, 164.4)
    # The system rail for the ADC (channel 7), halved.
    r("R54", "100k", "VSYS", "VSYS_DIV", (135.6, 147.2), 90)
    r("R55", "100k", "VSYS_DIV", "GND", (137.6, 147.2), 90)
    c("C53", "100n", "VSYS_DIV", (139.6, 147.2), 90)

    # ---- RP2040 (U1), its flash (U2), crystal (Y1), on the back left of centre --------------------
    rp = {
        "1": "+3V3", "10": "+3V3", "22": "+3V3", "33": "+3V3", "42": "+3V3", "49": "+3V3",
        "48": "+3V3", "43": "+3V3", "44": "+3V3", "45": "+1V1", "23": "+1V1", "50": "+1V1", "57": "GND",
        "19": "GND", "20": "XIN", "21": "XOUT", "24": "SWCLK", "25": "SWDIO", "26": "RUN",
        "46": "RP_D-", "47": "RP_D+",
        "51": "QSPI_SD3", "52": "QSPI_SCLK", "53": "QSPI_SD0", "54": "QSPI_SD2", "55": "QSPI_SD1", "56": "QSPI_SS",
        "2": "ESP_RXD", "3": "ESP_TXD", "4": "ESP_EN", "5": "ESP_IO0", "6": "I2C0_SDA", "7": "I2C0_SCL", "8": "TURBO_A", "9": "TURBO_B",
        "11": "ADC_MISO", "12": "ADC_CS", "13": "ADC_SCK", "14": "ADC_MOSI",
        "15": "SR_PL", "16": "SR_CLK", "17": "SR_Q", "18": "LED_DATA",
        "27": "PIO_D+", "28": "PIO_D-", "29": "HOST_EN", "30": "FAULT_N",
        "31": "RUMBLE_L_A", "32": "RUMBLE_L_B", "34": "RUMBLE_R_A", "35": "RUMBLE_R_B",
        "36": "MOT_SLEEP", "37": "IMU_INT", "38": "CHG_INT", "39": "PADDLE_L", "40": "PADDLE_R", "41": "CHG_STAT",
    }  # fmt: skip
    U1 = (138.0, 127.0)
    add("U1", "MCU_RaspberryPi:RP2040", "RP2040", "Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP3.2x3.2mm", U1, rp, 0, B)
    for vx in (-0.8, 0.8):
        for vy in (-0.8, 0.8):
            d.via("GND", U1[0] + vx, U1[1] + vy)  # the exposed pad into the In1 plane
    # 4 of the IO supply's caps on the QFN's corners, where it has no pins; the rest a row out.
    for i, (dx, dy) in enumerate([(-5.4, -5.4), (-5.4, 5.4), (5.4, -5.4), (5.4, 5.4), (-2.2, -8.0), (2.2, -8.0)]):
        c(f"C{10 + i}", "100n", "+3V3", (U1[0] + dx, U1[1] + dy))
    # By hand: the core supply from VREG_VOUT (pin 45, the bottom row) to DVDD (pin 23, the top row),
    # down through a via at each and along In2 under the chip, between its ground vias.
    d.via("+1V1", 139.8, 132.2)
    d.via("+1V1", 138.6, 121.8)
    d.track("+1V1", [(139.8, 130.44), (139.8, 132.2)], "B.Cu")
    d.track("+1V1", [(138.6, 123.56), (138.6, 121.8)], "B.Cu")
    d.track("+1V1", [(138.6, 121.8), (139.5, 122.7), (139.5, 131.3), (139.8, 132.2)], "In2.Cu")
    c("C16", "1u", "+3V3", (U1[0] - 2.2, U1[1] + 8.0))  # VREG_VIN
    c("C17", "1u", "+1V1", (U1[0] + 2.2, U1[1] + 8.0))  # VREG_VOUT
    c("C18", "100n", "+1V1", (U1[0] + 6.2, U1[1] + 8.0))
    add("Y1", "Device:Crystal_GND24", "12MHz", "Crystal:Crystal_SMD_3225-4Pin_3.2x2.5mm", (129.5, 127.0),
        {"1": "XIN", "2": "GND", "3": "XTAL_O", "4": "GND"}, 90, B)  # fmt: skip
    c("C19", "15p", "XIN", (126.0, 124.5))
    c("C20", "15p", "XTAL_O", (126.0, 129.5))
    r("R16", "1k", "XTAL_O", "XOUT", (129.5, 132.5))
    add("U2", "Memory_Flash:W25Q128JVS", "W25Q128JV", "Package_SO:SOIC-8_5.3x5.3mm_P1.27mm", (138.0, 141.0),
        {"1": "QSPI_SS", "2": "QSPI_SD1", "3": "QSPI_SD2", "4": "GND", "5": "QSPI_SD0", "6": "QSPI_SCLK",
         "7": "QSPI_SD3", "8": "+3V3"}, 0, B)  # fmt: skip
    c("C21", "100n", "+3V3", (143.5, 138.5), 90)
    r("R17", "10k", "QSPI_SS", "+3V3", (132.0, 138.5), 90)
    r("R18", "10k", "RUN", "+3V3", (131.0, 119.0))
    add("SW17", "Switch:SW_Push", "BOOTSEL", SMALL, (128.0, 114.5), {"1": "BOOT_R", "2": "GND"}, 0, B)
    r("R19", "1k", "QSPI_SS", "BOOT_R", (133.5, 114.5))
    add("J10", "Connector_Generic_MountingPin:Conn_01x03_MountingPin", "SWD", SH3, (131.0, 106.0),
        {"1": "SWCLK", "2": "GND", "3": "SWDIO", "MP": "GND"}, 0, B)  # fmt: skip
    for k, net in enumerate(("I2C0_SDA", "I2C0_SCL")):
        r(f"R{26 + k}", "4.7k", net, "+3V3", (140.0 + 2.4 * k, 115.0), 90)

    # ---- ESP32 (U3): Bluetooth Classic and BLE, on the back, its antenna past the dip -------------
    add("U3", "Rosetta:ESP32-WROOM-32E", "ESP32-WROOM-32E", "RF_Module:ESP32-WROOM-32E", ESP_AT,
        {"2": "+3V3", "1": "GND", "15": "GND", "38": "GND", "39": "GND", "3": "ESP_EN", "25": "ESP_IO0",
         "34": "ESP_RXD", "35": "ESP_TXD"}, 180, B)  # fmt: skip
    c("C22", "10u", "+3V3", (181.0, 114.5), 90, fp=C0805)
    c("C23", "100n", "+3V3", (183.4, 114.5), 90)
    r("R20", "10k", "ESP_EN", "+3V3", (181.0, 118.5), 90)
    c("C24", "1u", "ESP_EN", (183.4, 118.5), 90)
    r("R21", "10k", "ESP_IO0", "+3V3", (147.4, 128.0), 90)

    # ---- the analog inputs: sticks, Hall triggers, knob, cell (U4) --------------------------------
    U4 = (181.0, 128.0)
    add("U4", "Analog_ADC:MCP3208", "MCP3208", SOIC16, U4,
        {"1": "STICK_LX", "2": "STICK_LY", "3": "STICK_RX", "4": "STICK_RY", "5": "TRIG_L", "6": "TRIG_R",
         "7": "MODE_SENSE", "8": "VSYS_DIV", "9": "GND", "10": "ADC_CS", "11": "ADC_MOSI", "12": "ADC_MISO",
         "13": "ADC_SCK", "14": "GND", "15": "+3V3", "16": "+3V3"}, 90, B)  # fmt: skip
    c("C25", "100n", "+3V3", (U4[0] + 6.5, U4[1] - 4.0), 90)
    c("C26", "1u", "+3V3", (U4[0] + 6.5, U4[1] - 1.0), 90)
    r("R22", "10k", "ADC_CS", "+3V3", (U4[0] + 6.5, U4[1] + 2.0), 90)

    def stick(ref, at, side):
        # Each axis's ends on the rails and its middle pin out: a pot as a divider, a Hall drop-in
        # as VCC, output, GND. a and d are the push switch's 2 sides; b and c are soldered, unused.
        add(ref, "Rosetta:THUMBSTICK_HALL", f"STICK_{side}", STICK, at,
            {"A1": "+3V3", "A2": f"STICK_{side}X", "A3": "GND", "B1": "+3V3", "B2": f"STICK_{side}Y", "B3": "GND",
             "a": f"BTN_{side}3", "d": "GND", "MP": "GND"})  # fmt: skip
        stick_keepouts(d, *at, f"{side} stick")

    stick("SL", STICK_L, "L")
    stick("SR", STICK_R, "R")

    # The triggers: a linear Hall sensor under each trigger's magnet, on the horn, with its cap.
    for ref, cref, at, side in (("U15", "C31", (110.0, 110.0), "L"), ("U16", "C32", (210.0, 110.0), "R")):
        add(ref, "Sensor_Magnetic:DRV5055A1xDBZxQ1", "DRV5055A1", "Package_TO_SOT_SMD:SOT-23", at,
            {"1": "+3V3", "2": f"TRIG_{side}", "3": "GND"}, 0)  # fmt: skip
        c(cref, "100n", "+3V3", (at[0], at[1] + 3.2), 0, layer="F.Cu")

    # The knob and its ladder (see sim/mode_*.cir): taps from 5/6 of 3.3 V down to 1/6.
    sw1 = {"C": "MODE_SENSE", "MP": "GND"} | {str(k): f"TAP{k}" for k in range(1, 6)}
    add("SW1", "Switch:SW_SP5T_NR01105", "MODE", "Button_Switch_THT:SW_NKK_NR01",
        (KNOB[0] - 5.08, KNOB[1] - 2.54), sw1)  # fmt: skip
    ladder = ["+3V3", "TAP1", "TAP2", "TAP3", "TAP4", "TAP5", "GND"]
    for k in range(6):
        r(f"R{40 + k}", "1k", ladder[k], ladder[k + 1], (152.8 + 2.4 * k, 153.5), 90)
    # By hand: the knob's pin 5 to R44, on the front round the knob's mounting pads (2 routes
    # left this 1 link open; each piece was probed clear on the routed board).
    d.via("TAP5", 162.4, 151.4)
    d.track("TAP5", [(154.92, 146.54), (154.92, 150.6), (162.4, 150.6), (162.4, 151.4)], "F.Cu")
    d.track("TAP5", [(162.4, 151.4), (162.4, 152.68)], "B.Cu")
    r("R46", "100k", "MODE_SENSE", "GND", (167.2, 153.5), 90)
    c("C27", "100n", "MODE_SENSE", (169.6, 153.5), 90)

    # ---- rumble: 2 motors in the grips, on the DRV8833's 2 bridges (U6) ---------------------------
    U6 = (196.0, 141.0)
    add("U6", "Driver_Motor:DRV8833PW", "DRV8833", "Package_SO:TSSOP-16_4.4x5mm_P0.65mm", U6,
        {"1": "MOT_SLEEP", "2": "MOT_L+", "3": "ISEN_A", "4": "MOT_L-", "5": "MOT_R-", "6": "ISEN_B", "7": "MOT_R+",
         "8": "FAULT_N", "9": "RUMBLE_R_A", "10": "RUMBLE_R_B", "11": "VCP", "12": "VSYS", "13": "GND",
         "14": "VINT", "15": "RUMBLE_L_B", "16": "RUMBLE_L_A"}, 90, B)  # fmt: skip
    c("C28", "10u", "VSYS", (U6[0] - 5.0, U6[1] - 2.0), 90, fp=C0805)
    c("C29", "2.2u", "VINT", (U6[0] - 5.0, U6[1] + 2.0), 90)
    c("C30", "10n", "VCP", (U6[0] + 5.0, U6[1] + 2.0), 90, b="VSYS")
    r("R23", "100k", "MOT_SLEEP", "GND", (U6[0] + 5.0, U6[1] - 2.0), 90)
    r("R24", "10k", "FAULT_N", "+3V3", (U6[0] + 7.4, U6[1] - 2.0), 90)
    # Each bridge's current through 0.5 ohm: the DRV8833 chops at 200 mV, 400 mA, a stalled motor's.
    r("R50", "0.5", "ISEN_A", "GND", (U6[0] - 1.2, U6[1] + 5.5), 90)
    r("R51", "0.5", "ISEN_B", "GND", (U6[0] + 1.2, U6[1] + 5.5), 90)
    for jref, at, side in (("J7", (98.0, 146.0), "L"), ("J8", (222.0, 146.0), "R")):
        add(jref, "Connector_Generic_MountingPin:Conn_01x02_MountingPin", f"RUMBLE_{side}", SH2, at,
            {"1": f"MOT_{side}+", "2": f"MOT_{side}-", "MP": "GND"}, 0)  # fmt: skip
        # Each mounting pad down to the ground plane: the first routes left both pads of each apart.
        for mx in (-1.8, 1.8):
            d.via("GND", at[0] + mx, at[1] + 3.6)
            d.track("GND", [(at[0] + mx, at[1] + 1.875), (at[0] + mx, at[1] + 3.6)], "F.Cu")

    # ---- the IMU (U5), on the back under the right stick's top -----------------------------------
    U5 = (173.0, 136.0)
    add("U5", "Sensor_Motion:LSM6DSL", "LSM6DSL", "Package_LGA:LGA-14_3x2.5mm_P0.5mm_LayoutBorder3x4y", U5,
        {"1": "IMU_SA0", "2": "IMU_SA0", "3": "GND", "4": "IMU_INT", "5": "+3V3", "6": "GND", "7": "GND", "8": "+3V3",
         "12": "+3V3", "13": "I2C0_SCL", "14": "I2C0_SDA"}, 0, B)  # fmt: skip
    # SA0 high: address 0x6B, since the charger answers at 0x6A. The aux bus's SDx with it.
    r("R52", "10k", "IMU_SA0", "+3V3", (U5[0], U5[1] + 3.8), 90)
    c("C37", "100n", "+3V3", (U5[0] + 3.5, U5[1] - 1.0), 90)
    c("C38", "100n", "+3V3", (U5[0] + 3.5, U5[1] + 2.0), 90)

    # ---- buttons: 16 on 2 shift registers (U7 left, U8 right), each input pulled up -------------
    left = ["UP", "DOWN", "LEFT", "RIGHT", "L1", "L3", "SHARE", "HOME"]
    right = ["Y", "B", "A", "X", "R1", "R3", "OPTIONS", "CAPTURE"]
    shift = {"1": "SR_PL", "2": "SR_CLK", "8": "GND", "15": "GND", "16": "+3V3"}
    order = ["11", "12", "13", "14", "3", "4", "5", "6"]  # D0..D7
    add("U7", "74xx:74HC165", "74HC165", SOIC16, (138.0, 158.0),
        shift | {"10": "GND", "9": "SR_MID"} | {p: f"BTN_{n}" for p, n in zip(order, left, strict=True)}, 90, B)  # fmt: skip
    add("U8", "74xx:74HC165", "74HC165", SOIC16, (208.0, 127.0),
        shift | {"10": "SR_MID", "9": "SR_Q"} | {p: f"BTN_{n}" for p, n in zip(order, right, strict=True)}, 0, B)  # fmt: skip
    r("R47", "10k", "SR_PL", "+3V3", (144.5, 115.0), 90)  # the RP2040's pins float in reset
    r("R48", "100k", "SR_CLK", "GND", (146.9, 115.0), 90)
    r("R49", "100k", "LED_DATA", "GND", (149.3, 115.0), 90)
    c("C39", "100n", "+3V3", (138.0, 163.0))
    c("C40", "100n", "+3V3", (208.0, 120.5))
    for k, (names, at) in enumerate(((left[:4], (133.5, 151.0)), (left[4:], (142.5, 151.0)),
                                      (right[:4], (202.5, 127.0)), (right[4:], (213.5, 127.0)))):  # fmt: skip
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
    # The bumpers: right-angle switches whose plungers stand out of the horns' top edge.
    button("SW10", "L1", (114.0 - 2.25, 103.2), fp=BUMPER)
    button("SW11", "R1", (206.0 - 2.25, 103.2), fp=BUMPER)
    button("SW12", "SHARE", (146.0, 131.0), fp=SMALL)  # View
    button("SW13", "OPTIONS", (174.0, 131.0), fp=SMALL)  # Menu
    button("SW14", "HOME", (156.5, 160.0), fp=SMALL)
    button("SW18", "CAPTURE", (163.5, 160.0), fp=SMALL)
    button("SW15", "PADDLE_L", (100.0, 140.0), layer=B, net="PADDLE_L")
    # The turbo buttons beside the paddles: each press steps its side's turbo mode (firmware/src/turbo.c).
    button("SW19", "TURBO_A", (98.0, 126.0), layer=B, net="TURBO_A")
    button("SW20", "TURBO_B", (222.0, 126.0), layer=B, net="TURBO_B")
    button("SW16", "PADDLE_R", (220.0, 140.0), layer=B, net="PADDLE_R")

    # ---- mounting: the shell's 4 screws, 2 by the triggers' pivots, 2 in the grips -------------
    for ref, at in (("H1", (124.0, 108.0)), ("H2", (196.0, 108.0)), ("H3", (126.0, 140.0)), ("H4", (202.0, 160.0))):
        add(ref, "Mechanical:MountingHole_Pad", "M2.5", HOLE, at, {"1": "GND"})

    # ---- the light ring: 5 RGB LEDs round the knob, data level-shifted to VSYS (U14) -----------
    add("U14", "74xGxx:74AHCT1G125", "74AHCT1G125", "Package_TO_SOT_SMD:SOT-23-5", (147.0, 138.0),
        {"1": "GND", "2": "LED_DATA", "3": "GND", "4": "LED_D0", "5": "VSYS"}, 90, B)  # fmt: skip
    c("C41", "100n", "VSYS", (147.0, 142.0))
    chain = ["LED_D0", "LED_D1", "LED_D2", "LED_D3", "LED_D4", "LED_D5"]
    for k, (deg, label) in enumerate(MODES):
        a = math.radians(deg)
        at = (round(KNOB[0] + RING_R * math.cos(a), 3), round(KNOB[1] - RING_R * math.sin(a), 3))
        add(f"D{k + 2}", "LED:WS2812B-2020", label, "LED_SMD:LED_WS2812B-2020_PLCC4_2.0x2.0mm", at,
            {"1": chain[k + 1], "2": "GND", "3": chain[k], "4": "VSYS"},
            90 - deg)  # fmt: skip
        d.text(label, *label_at(deg), "F.SilkS", 1.0, 0.15)
        c(f"C{42 + k}", "100n", "VSYS", at, 90 - deg)  # behind its LED

    # ---- the screen: a 0.91 in 128 x 32 OLED module on I2C0, over the ESP32, between the horns ----
    add("DS1", "Display_Graphic:ER_OLEDM0.91_1x-I2C", "ER-OLEDM0.91-1", "Display:ER_OLEDM0.91_1x-I2C", OLED_AT,
        {"1": "GND", "2": "+3V3", "3": "I2C0_SCL", "4": "I2C0_SDA"}, OLED_ROT)  # fmt: skip
    c("C54", "100n", "+3V3", (OLED_AT[0] - 3.0, OLED_AT[1] + 2.54), 90, layer=B)

    # ---- a ring of 8 RGB LEDs round each stick, chained after the knob's ring ------------------
    ring_chain = ["LED_D5"] + [f"LED_S{k}" for k in range(1, 17)]
    n = 0
    for side, (sx, sy) in (("L", STICK_L), ("R", STICK_R)):
        for k in range(8):
            deg = STICK_RING_PHASE + 45 * k
            a = math.radians(deg)
            at = (round(sx + STICK_RING_R * math.cos(a), 3), round(sy - STICK_RING_R * math.sin(a), 3))
            ref = f"D{7 + n}"
            nets = {"2": "GND", "3": ring_chain[n], "4": "VSYS"} | ({"1": ring_chain[n + 1]} if n + 1 < 16 else {})
            add(ref, "LED:WS2812B-2020", f"STICK_{side}{k}", "LED_SMD:LED_WS2812B-2020_PLCC4_2.0x2.0mm", at, nets, 0)
            d.model(ref, "${KIPRJMOD}/models/ws2812b_2020.wrl", replace=True)
            if k % 2 == 1:  # 1 cap for each 2 LEDs, behind the second of the pair
                c(f"C{55 + n // 2}", "100n", "VSYS", at, 0)
            n += 1
    # The right ring's link under its stick: 12 passes left it open, so it is drawn on In3, probed
    # clear on the unrouted board.
    d.track("LED_S14", [(175.34, 167.31), (174.4, 167.31)], "F.Cu")
    d.via("LED_S14", 174.4, 167.31)
    d.track("LED_S14", [(174.4, 167.31), (174.4, 168.7), (189.4, 168.7), (189.4, 168.41)], "In3.Cu")
    d.via("LED_S14", 189.4, 168.41)
    d.track("LED_S14", [(189.4, 168.41), (188.66, 168.41)], "F.Cu")

    # ---- the face's words -----------------------------------------------------------------------
    for label, x, y in (("LB", 114.0, 107.0), ("RB", 206.0, 107.0), ("LT", 110.0, 115.0), ("RT", 210.0, 115.0),
                        ("Y", fx, fy - 11.8), ("A", fx, fy + 11.8), ("X", fx - 12.0, fy), ("B", fx + 12.0, fy),
                        ("VIEW", 146.0, 127.8), ("MENU", 174.0, 127.8), ("HOME", 156.5, 163.3),
                        ("CAPTURE", 163.5, 163.3), ("ROSETTA v0.3", 160.0, 167.0)):  # fmt: skip
        d.text(label, x, y, "F.SilkS", 1.0, 0.15)

    # 3D bodies for the parts KiCad's 3D library has none for (models/make_models.py).
    d.model("SW1", "${KIPRJMOD}/models/nr01.wrl", replace=True)
    d.model("J9", "${KIPRJMOD}/models/jst_ph_s3b_sm4.wrl", replace=True)
    d.model("DS1", "${KIPRJMOD}/models/oled_091.wrl", replace=True)
    d.model("L2", "${KIPRJMOD}/models/lps4018.wrl", replace=True)
    d.model("U12", "${KIPRJMOD}/models/son10_drc.wrl", replace=True)
    for k in range(len(MODES)):
        d.model(f"D{k + 2}", "${KIPRJMOD}/models/ws2812b_2020.wrl", replace=True)

    # Pulls the board does not hold itself, each with what holds it.
    d.defined_nets = {
        "CHG_STAT": "GPIO29's internal pull-up, set in firmware (the BQ25895's STAT is open-drain)",
        "CHG_INT": "GPIO26's internal pull-up, set in firmware (the BQ25895's INT is open-drain)",
        "TURBO_A": "GPIO6's internal pull-up, set in firmware",
        "TURBO_B": "GPIO7's internal pull-up, set in firmware",
        "BB_L1": "the TPS63001's switch node: its power stage drives it",
        "BB_L2": "the TPS63001's switch node: its power stage drives it",
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
    for net in ("STICK_LX", "STICK_LY", "STICK_RX", "STICK_RY"):
        d.defined_nets[net] = "the stick's Hall sensor (or its pot's wiper between the rails) drives it"
    for net in ("TRIG_L", "TRIG_R"):
        d.defined_nets[net] = "the DRV5055 drives its output push-pull"
    for net in ("RUMBLE_L_A", "RUMBLE_L_B", "RUMBLE_R_A", "RUMBLE_R_B"):
        d.defined_nets[net] = "the DRV8833's inputs have internal pull-downs, and R23 holds nSLEEP low in reset"
    d.check_pulls = True
    for part in d.parts:
        part.hide_ref = True
    lay_out_schematic(d)
    return d
