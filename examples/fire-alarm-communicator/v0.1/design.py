"""Herald v0.1: a fire alarm communicator. It sits beside a fire alarm control panel (FACP), takes
the panel's alarm, supervisory and trouble signals, and sends each one to a monitoring station over
LTE-M, with Wi-Fi as the second path.

The hard parts this board takes on, and where each lives:

- Dialer capture. A panel reports by phone: its dialer (a DACT) seizes a line, dials, waits for the
  station's handshake tone, sends a Contact ID message as DTMF digits and waits for the kissoff tone.
  J2 is that phone line. Q3 and Q4 feed it a current-limited 24 V loop, R22 reads the loop current
  (off-hook), and the ESP32 plays the dial tone, the handshake and the kissoff through R25-R27 and
  hears the DTMF digits through C31 and R28 on an ADC pin. When neither path reaches the station,
  the firmware drops the line (LINE_EN low) and the panel reports its own phone-line trouble.
- 3 supervised inputs (J3) for panels that report by relay: each loop ends in a 4.7k resistor at
  the panel's contact, so the ADC tells a closed contact, a normal loop and a cut wire apart.
  `sim/zone_*.cir` hold each window at every corner.
- A trouble output the panel watches (K1): the relay is held on while the communicator is healthy,
  so a dead board, a crash or a lost supply opens it. Both poles run in parallel.
- 2 paths: a Quectel BG95-M1 LTE-M modem (U3) with its nano SIM (J5) and antenna (J4), and the
  ESP32-S3's own Wi-Fi (U5, antenna on its u.FL). The BG95's I/O is 1.8 V; U4 translates the UART.
- Power from the panel's 24 V auxiliary output: J1, a PTC (F1), a TVS (D1) and a series Schottky
  (D2), then a 3 A buck (U1) to 3.8 V for the modem and a 1 A LDO (U2) to 3.3 V. USB (J6) can feed
  the buck through D3 for set-up on the bench.
- The panel's 0 V must not reach the cabinet: a panel reports an earth fault. The 4 mounting holes
  are bare (no copper), and nothing on the board ties GND to them.

    workcenter design design.py --route     # from this folder

Board: 84.4 x 64 mm, 4 layers (F.Cu signal, In1.Cu GND plane, In2.Cu signal, B.Cu signal and GND),
every part on the front. Red solder mask, white legend, ENIG.
"""

from __future__ import annotations

import math
import uuid
from pathlib import Path

import kicadgen

HERE = Path(__file__).resolve().parent

# ---- the board -----------------------------------------------------------------------------------
X0, Y0, X1, Y1 = 100.0, 100.0, 184.4, 164.0
TERM_Y = Y1 - 5.2  # the terminal blocks' pins: the body's front (wire entry) at the bottom edge


class HeraldDesign(kicadgen.Design):
    """A Design with a coloured stackup (red mask, white legend, ENIG) and silkscreen art: the mark,
    the words, the rules and boxes this file draws (`art`)."""

    art: list = []

    @staticmethod
    def _stackup(copper: list[str], thickness: float = 1.6) -> list:
        node = kicadgen.Design._stackup(copper, thickness)
        Q = kicadgen.Q
        colors = {"F.Mask": "Red", "B.Mask": "Red", "F.SilkS": "White", "B.SilkS": "White"}
        for item in node[1:]:
            if item[0] == "layer" and item[1] in colors:
                item.insert(3, ["color", Q(colors[item[1]])])
            if item[0] == "copper_finish":
                item[1] = Q("ENIG")
        return node

    def _edge_cuts(self, ns: uuid.UUID) -> list:
        return super()._edge_cuts(ns) + [
            self._art_node(item, ns, i) for i, item in enumerate(self.art)
        ]

    @staticmethod
    def _art_node(item: tuple, ns: uuid.UUID, i: int) -> list:
        fmt, Q = kicadgen.fmt, kicadgen.Q
        kind = item[0]
        stroke = ["stroke", ["width", fmt(item[-1])], ["type", "solid"]]
        if kind == "line":
            _, (ax, ay), (bx, by), layer, _w = item
            return ["gr_line", ["start", fmt(ax), fmt(ay)], ["end", fmt(bx), fmt(by)], stroke,
                    ["layer", Q(layer)], ["uuid", kicadgen.uid(ns, f"art/{i}")]]  # fmt: skip
        if kind == "rect":
            _, (ax, ay), (bx, by), layer, fill, _w = item
            return ["gr_rect", ["start", fmt(ax), fmt(ay)], ["end", fmt(bx), fmt(by)], stroke,
                    ["fill", "yes" if fill else "no"], ["layer", Q(layer)], ["uuid", kicadgen.uid(ns, f"art/{i}")]]  # fmt: skip
        if kind == "poly":
            _, pts, layer, fill, _w = item
            return ["gr_poly", ["pts", *[["xy", fmt(x), fmt(y)] for x, y in pts]], stroke,
                    ["fill", "yes" if fill else "no"], ["layer", Q(layer)], ["uuid", kicadgen.uid(ns, f"art/{i}")]]  # fmt: skip
        if kind == "text":
            _, text, (x, y), layer, size, thick, justify, angle, _w = item
            effects = ["effects", ["font", ["size", fmt(size), fmt(size)], ["thickness", fmt(thick)]]]
            just = ([justify] if justify else []) + (["mirror"] if layer.startswith("B.") else [])
            if just:
                effects.append(["justify", *just])
            return ["gr_text", Q(text), ["at", fmt(x), fmt(y), fmt(angle)], ["layer", Q(layer)],
                    ["uuid", kicadgen.uid(ns, f"art/{i}")], effects]  # fmt: skip
        raise ValueError(kind)


# ---- footprints ----------------------------------------------------------------------------------
R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
R0603 = "Resistor_SMD:R_0603_1608Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
R0805 = "Resistor_SMD:R_0805_2012Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"
C1210 = "Capacitor_SMD:C_1210_3225Metric"
PTC = "Fuse:Fuse_1206_3216Metric"
SMA = "Diode_SMD:D_SMA"
SOD123 = "Diode_SMD:D_SOD-123"
SOT23 = "Package_TO_SOT_SMD:SOT-23"
SOT23_5 = "Package_TO_SOT_SMD:SOT-23-5"
SOT23_6 = "Package_TO_SOT_SMD:SOT-23-6"
LED0603 = "LED_SMD:LED_0603_1608Metric"
BUTTON = "Button_Switch_SMD:SW_SPST_PTS810"


def term(n: int) -> str:
    """A Phoenix PT 1,5 3.5 mm screw terminal of n ways, wire entry toward the board's bottom edge."""
    return f"TerminalBlock_Phoenix:TerminalBlock_Phoenix_PT-1,5-{n}-3.5-H_1x{n:02d}_P3.50mm_Horizontal"


# ---- where things are ----------------------------------------------------------------------------
MDM = (118.4, 117.8)  # U3, the BG95 (LGA, 22 x 25.6 mm courtyard)
SIM = (139.8, 111.8)  # J5, turned so its contacts face the modem's USIM pins
ESP = (159.4, 112.8)  # U5, the ESP32-S3-MINI-1U
# Pin 1 of each field connector: equal gaps between the bodies, and an equal margin at each end.
J_PWR, J_LINE, J_TAMPER, J_IN, J_OUT = 110.0, 122.6, 135.2, 147.8, 167.4
LABEL_Y = TERM_Y - 4.6  # the terminals' names
LEDS_X = 171.4
LED_Y = [109.6, 112.1, 114.6, 117.1, 119.6]


def build() -> kicadgen.Design:
    d = HeraldDesign(
        name="herald",
        namespace=uuid.UUID("69541661-a090-4f85-b7f9-284b36c69012"),
        outline=(X0, Y0, X1, Y1),
        corner_radius=3.0,
        sheet="A1",
        copper_layers=4,
        plane_layers=("In1.Cu",),
        track_width=0.2,
        clearance=0.15,
        via_size=0.5,
        via_drill=0.3,
    )
    d.art = []
    d.power_nets = {
        "GND": "GND",
        "VIN": "+24V",
        "+3V8": "+3V8",
        "+3V3": "+3V3",
        "+1V8": "+1V8",
        "VBUS": "VBUS",
    }
    # No power-output pin drives these: GND and VIN come in on J1 (VIN through D2), VBUS on J6, and the
    # buck's inductor makes +3V8. +3V3 is U2's output and +1V8 the modem's VDD_EXT, both power outputs.
    d.flagged_nets = ["GND", "VIN", "VBUS", "+3V8"]
    d.net_classes = {
        "power": {
            "width": 0.5,
            "clearance": 0.15,
            "via": 0.6,
            "via_drill": 0.3,
            "nets": ["VFACP", "VIN_F", "VIN", "VBUS", "+3V8", "SW_BUCK"],
        },
        "rail": {"width": 0.3, "clearance": 0.15, "via": 0.5, "via_drill": 0.3, "nets": ["+3V3", "+1V8", "SIM_VCC"]},
        # The phone line and the relay's contacts leave the board: 0.3 mm apart for 30 V and a surge.
        "line": {
            "width": 0.4,
            "clearance": 0.3,
            "via": 0.6,
            "via_drill": 0.3,
            "nets": ["TIP_EXT", "TIP", "RING", "FEED_E", "TRBL_C", "TRBL_NC", "TRBL_NO"],
        },
        # 50 ohm microstrip over In1.Cu (0.21 mm of 7628 prepreg, er 4.5): 0.35 mm.
        "rf": {"width": 0.35, "clearance": 0.3, "via": 0.5, "via_drill": 0.3, "nets": ["ANT_MAIN"]},
    }
    d.rules = {"min_text_height": 0.7, "min_text_thickness": 0.12}
    # 3 keep-outs: the strip under the terminals' names on F.Cu (`terminal names`), and the mark and the
    # name on B.Cu (`the mark on the back`, `the name on the back`). Each bans tracks on its layer and
    # vias on every layer; a pad inside one is reached from its own face outside it (P3 step 4).
    d.zone("GND", layers=("In1.Cu",), connect="solid")
    d.zone("GND", layers=("F.Cu", "B.Cu"), connect="solid")

    grid = iter(range(10_000))

    def sch() -> tuple[float, float]:
        k = next(grid)
        return (25.4 + 25.4 * (k % 30), 25.4 + 25.4 * (k // 30))

    def add(ref, lib, value, fp, at, nets, rot=0.0):
        return d.add(ref, lib, value, fp, sch_at=sch(), pcb_at=at, pcb_rot=rot, nets=nets)

    def r(ref, value, a, b, at, rot=0.0, fp=R0402):
        return add(ref, "Device:R", value, fp, at, {"1": a, "2": b}, rot)

    def c(ref, value, a, at, rot=0.0, b="GND", fp=C0402):
        return add(ref, "Device:C", value, fp, at, {"1": a, "2": b}, rot)

    def label(text, x, y, size=0.8, justify=None, layer="F.SilkS", thick=0.13, angle=0.0):
        d.art.append(("text", text, (x, y), layer, size, thick, justify, angle, thick))

    def box(ax, ay, bx, by, w=0.15, layer="F.SilkS"):
        d.art.append(("rect", (ax, ay), (bx, by), layer, False, w))

    def line(a, b, w=0.15, layer="F.SilkS"):
        d.art.append(("line", a, b, layer, w))

    def poly(pts, layer="F.SilkS", fill=True, w=0.1):
        d.art.append(("poly", pts, layer, fill, w))

    def flame(cx, cy, h, layer="F.SilkS"):
        """The mark, h tall, centred on (cx, cy): a flame's outline with its inner tongue filled."""
        outer = [(0.0, 0.0), (0.14, 0.02), (0.28, 0.08), (0.38, 0.20), (0.41, 0.36), (0.36, 0.52), (0.26, 0.66),
                 (0.18, 0.78), (0.13, 0.90), (0.10, 1.0), (-0.02, 0.90), (-0.14, 0.80), (-0.27, 0.68),
                 (-0.37, 0.54), (-0.41, 0.38), (-0.38, 0.20), (-0.28, 0.08), (-0.14, 0.02)]  # fmt: skip
        tongue = [(0.0, 0.07), (0.08, 0.09), (0.15, 0.17), (0.17, 0.30), (0.11, 0.44), (0.04, 0.56), (-0.06, 0.44),
                  (-0.15, 0.31), (-0.16, 0.18), (-0.08, 0.09)]  # fmt: skip

        def at(pts):
            return [(round(cx + x * h, 3), round(cy + (0.5 - y) * h, 3)) for x, y in pts]

        poly(at(outer), layer, False, 0.32)
        poly(at(tongue), layer, True, 0.05)

    # ---- power in: J1, F1, D1, D2, then the buck (U1) to +3V8 and the LDO (U2) to +3V3 ----------
    add("J1", "Connector_Generic:Conn_01x02", "24V IN", term(2), (J_PWR, TERM_Y), {"1": "VFACP", "2": "GND"})
    add("F1", "Device:Polyfuse", "0.75A 30V", PTC, (J_PWR, 150.0), {"1": "VFACP", "2": "VIN_F"}, 90)
    # Across the input after F1: it clamps a surge, and a supply wired backwards drives it forward
    # until F1 trips. D2 keeps the reversed voltage off everything else.
    add("D1", "Diode:SMAJ28A", "SMAJ28A", SMA, (J_PWR + 4.2, 150.0), {"1": "VIN_F", "2": "GND"}, 270)
    add("D2", "Device:D_Schottky", "SS34", SMA, (J_PWR, 144.0), {"1": "VIN", "2": "VIN_F"}, 270)
    add("C1", "Device:C_Polarized", "47u 50V", "Capacitor_SMD:CP_Elec_6.3x7.7", (104.6, 144.6),
        {"1": "VIN", "2": "GND"}, 270)  # fmt: skip
    add("C2", "Device:C", "4.7u 50V", C1210, (111.4, 136.8), {"1": "VIN", "2": "GND"}, 270)
    U1 = (117.0, 137.0)
    # EN tied to VIN: the buck starts at its own 3.8 V minimum, which lets USB's 5 V run it too.
    add("U1", "Regulator_Switching:LMR33630ADDA", "LMR33630A", "Package_SO:HSOP-8-1EP_3.9x4.9mm_P1.27mm_EP2.41x3.1mm",
        U1, {"1": "GND", "2": "VIN", "3": "VIN", "5": "FB", "6": "VCC_BUCK", "7": "BOOT", "8": "SW_BUCK", "9": "GND"})  # fmt: skip
    c("C3", "100n", "BOOT", (121.4, 135.8), 90, b="SW_BUCK")
    c("C4", "1u", "VCC_BUCK", (121.4, 138.2), 90)
    # 3.8 V out: FB is 1.0 V (LMR33630 datasheet 7.5), so R1/R2 = 2.8.
    r("R1", "100k", "+3V8", "FB", (118.0, 141.2))
    r("R2", "35.7k", "FB", "GND", (118.0, 142.4))
    add("L1", "Device:L", "10u 3A", "Inductor_SMD:L_Bourns_SRN6045TA", (126.0, 136.6), {"1": "SW_BUCK", "2": "+3V8"})
    c("C5", "22u", "+3V8", (131.2, 134.8), 90, fp=C0805)
    c("C6", "22u", "+3V8", (131.2, 138.6), 90, fp=C0805)
    # VIN read by the ESP32: 28 V reads 2.55 V.
    r("R3", "100k", "VIN", "VSENSE", (114.0, 141.2))
    r("R4", "10k", "VSENSE", "GND", (114.0, 142.4))
    U2 = (153.0, 137.6)
    add("U2", "Regulator_Linear:TLV75733PDBV", "TLV75733P", SOT23_5, U2, {"1": "+3V8", "2": "GND", "3": "+3V8", "5": "+3V3"})
    c("C7", "1u", "+3V8", (U2[0] - 3.0, U2[1]), 90)
    c("C8", "10u", "+3V3", (U2[0] + 3.2, U2[1]), 90, fp=C0603)

    # ---- the modem: BG95-M1 (U3), its supply, its switches, the UART translator (U4) ------------
    gnd = ["3", "31", "48", "50", "54", "55", "58", "59", "61", "62", *map(str, range(67, 75)),
           *map(str, range(79, 83)), "89", "90", "91", "100", "101", "102", "47"]  # fmt: skip
    add("U3", "RF_GSM:BG95-M1", "BG95-M1", "RF_GSM:Quectel_BG95", MDM,
        {**{p: "GND" for p in gnd}, "32": "+3V8", "33": "+3V8", "52": "+3V8", "53": "+3V8", "29": "+1V8",
         "15": "MDM_PWRKEY", "17": "MDM_RESET", "34": "MDM_RXD", "35": "MDM_TXD", "39": "MDM_RI",
         "20": "MDM_STATUS", "43": "SIM_VCC", "44": "SIM_RST_M", "45": "SIM_IO_M", "46": "SIM_CLK_M",
         "60": "ANT_MAIN"})  # fmt: skip
    mx, my = MDM
    # VBAT_RF (pins 52, 53 on the top row): the bulk and the RF decoupling Quectel's design shows. The
    # bulk is a polymer part (KEMET T520B107M006ATE040) on the tantalum B-case land.
    add("C9", "Device:C_Polarized", "100u 6.3V polymer", "Capacitor_Tantalum_SMD:CP_EIA-3528-21_Kemet-B",
        (mx + 8.6, 102.2), {"1": "+3V8", "2": "GND"}, 180)  # fmt: skip
    c("C10", "100n", "+3V8", (mx + 1.7, 103.7), 90)
    c("C11", "33p", "+3V8", (mx + 2.8, 103.7), 90)
    c("C12", "10p", "+3V8", (mx + 3.9, 103.7), 90)
    # VBAT_BB (pins 32, 33, the right column's bottom): under the module's corner, out of the UART's way.
    # Each ground pad keeps room for its via outside the band kept clear under the back's subtitles.
    c("C13", "4.7u", "+3V8", (mx + 12.6, 127.4), 0, fp=C0603)
    c("C14", "100n", "+3V8", (mx + 15.4, 129.8), 0)
    # J4 straight above pad 60, its centre pin toward the pad: a 2.9 mm feed, 50 ohm (the rf class).
    pad60 = (mx - 5.25, my - 11.0)
    add("J4", "Connector:Conn_Coaxial", "LTE", "Connector_Coaxial:U.FL_Hirose_U.FL-R-SMT-1_Vertical",
        (pad60[0], 102.4), {"1": "ANT_MAIN", "2": "GND"}, 90)  # fmt: skip
    d.track("ANT_MAIN", [pad60, (pad60[0], 102.4 + 1.525)], "F.Cu")
    # PWRKEY and RESET_N: an open collector each, off in reset (R6, R8).
    add("Q1", "Transistor_BJT:MMBT3904", "MMBT3904", SOT23, (mx - 13.2, my + 4.6), {"1": "PWRKEY_B", "2": "GND", "3": "MDM_PWRKEY"}, 90)
    r("R5", "4.7k", "PWRKEY_CTL", "PWRKEY_B", (mx - 13.2, my + 0.9), 90)
    r("R6", "47k", "PWRKEY_B", "GND", (mx - 14.4, my + 0.9), 90)
    add("Q2", "Transistor_BJT:MMBT3904", "MMBT3904", SOT23, (mx - 13.2, my + 9.4), {"1": "RESET_B", "2": "GND", "3": "MDM_RESET"}, 90)
    r("R7", "4.7k", "RESET_CTL", "RESET_B", (mx - 13.2, my + 13.1), 90)
    r("R8", "47k", "RESET_B", "GND", (mx - 14.4, my + 13.1), 90)
    U4 = (136.8, 126.0)
    # A side 1.8 V (the modem's VDD_EXT), B side 3.3 V. OE on VCCA: the outputs float while the modem
    # is off.
    add("U4", "Logic_LevelTranslator:TXS0104EPW", "TXS0104E", "Package_SO:TSSOP-14_4.4x5mm_P0.65mm", U4,
        {"1": "+1V8", "8": "+1V8", "2": "MDM_TXD", "3": "MDM_RXD", "4": "MDM_STATUS", "5": "MDM_RI",
         "13": "ESP_RXD", "12": "ESP_TXD", "11": "STATUS_3V3", "10": "RI_3V3", "14": "+3V3", "7": "GND"})  # fmt: skip
    c("C15", "100n", "+1V8", (U4[0] - 3.0, 122.4), 0)
    c("C16", "100n", "+3V3", (U4[0] + 3.0, 122.4), 0)

    # ---- the nano SIM (J5) on the modem's USIM pins ---------------------------------------------
    add("J5", "Connector:SIM_Card_Shielded", "nano SIM", "Connector_Card:nanoSIM_Hinged_CUI_NSIM-2-C", SIM,
        {"1": "SIM_VCC", "2": "SIM_RST", "3": "SIM_CLK", "5": "GND", "7": "SIM_IO", "SH": "GND"}, 90)  # fmt: skip
    sx, sy = SIM
    for k, (ref, a, b) in enumerate((("R9", "SIM_RST_M", "SIM_RST"), ("R10", "SIM_CLK_M", "SIM_CLK"),
                                     ("R11", "SIM_IO_M", "SIM_IO"))):  # fmt: skip
        r(ref, "22", a, b, (sx - 9.3, sy - 2.0 + 1.2 * k))
    r("R12", "10k", "SIM_IO_M", "SIM_VCC", (sx - 9.3, sy + 1.6))
    c("C17", "100n", "SIM_VCC", (sx - 9.3, sy + 2.8))
    add("U6", "Power_Protection:ESDA6V1-5SC6", "ESDA6V1-5SC6", SOT23_6, (143.0, 121.4),
        {"1": "SIM_VCC", "3": "SIM_RST", "4": "SIM_CLK", "5": "SIM_IO", "2": "GND"})  # fmt: skip
    for k, net in enumerate(("SIM_RST", "SIM_IO", "SIM_CLK")):
        c(f"C{18 + k}", "33p", net, (146.6, 120.2 + 1.2 * k), 0)

    # ---- the ESP32-S3 (U5): Wi-Fi, the CPU, USB --------------------------------------------------
    ex, ey = ESP
    esp = {
        "3": "+3V3", "45": "EN", "4": "IO0", "7": "IO3",
        "5": "ZONE1_ADC", "6": "ZONE2_ADC", "8": "ZONE3_ADC", "9": "LOOP_ADC", "10": "VSENSE", "11": "DTMF_ADC",
        "12": "PWRKEY_CTL", "13": "RESET_CTL", "14": "ESP_TXD", "15": "ESP_RXD",
        "16": "STATUS_3V3", "17": "RI_3V3", "18": "TONE", "19": "LINE_EN", "20": "RELAY_DRV", "21": "TAMPER",
        "23": "USB_DN", "24": "USB_DP",
        "31": "LED_CELL", "32": "LED_WIFI", "33": "LED_ALARM", "34": "LED_TRBL", "35": "BTN_TEST",
    }  # fmt: skip
    for p in ["1", "2", "42", "43", *map(str, range(46, 66))]:
        esp[p] = "GND"
    add("U5", "RF_Module:ESP32-S3-MINI-1U", "ESP32-S3-MINI-1U", "RF_Module:ESP32-S2-MINI-1U", ESP, esp)
    c("C21", "10u", "+3V3", (ex - 5.0, ey - 9.6), 0, fp=C0603)
    c("C22", "100n", "+3V3", (ex - 7.6, ey - 9.6), 0)
    r("R13", "10k", "EN", "+3V3", (ex + 9.0, ey - 6.2), 90)
    c("C23", "1u", "EN", (ex + 10.2, ey - 6.2), 90)
    r("R14", "10k", "IO0", "+3V3", (ex - 9.0, ey - 3.6), 90)
    # GPIO3 is a strapping pin with no internal pull and must not float (datasheet v1.7, 4.4).
    r("R17", "10k", "IO3", "GND", (ex - 10.2, ey - 3.6), 90)

    # USB-C (J6) on the right edge, for set-up and firmware; D3 lets it run the buck.
    # A through-hole receptacle: an installer's cable gets pulled. Its shell stands 1.5 mm past the
    # edge; its pins are 0.15 mm apart, which sets the power class's clearance.
    J6 = (X1 - 7.6, 131.0)
    usb = {"A4": "VBUS", "A9": "VBUS", "B4": "VBUS", "B9": "VBUS", "A1": "GND", "A12": "GND", "B1": "GND",
           "B12": "GND", "SH": "GND", "A5": "CC1", "B5": "CC2", "A6": "USB_DP", "B6": "USB_DP",
           "A7": "USB_DN", "B7": "USB_DN"}  # fmt: skip
    add("J6", "Connector:USB_C_Receptacle_USB2.0_16P", "USB-C",
        "Connector_USB:USB_C_Receptacle_GCT_USB4085", J6, usb, 90)  # fmt: skip
    # CC2 (J6.B5, the far row) on the right, so CC1 and CC2 leave without crossing.
    r("R15", "5.1k", "CC1", "GND", (173.4, 124.2), 90)
    r("R16", "5.1k", "CC2", "GND", (174.6, 124.2), 90)
    # By hand: CC1 straight down from R15 and across into J6.A5, between D+ (A6) above and VBUS (A4)
    # below. Left to the router, D+ walled A5 in (round 6).
    d.track("CC1", [(173.4, 124.71), (173.4, 129.3), (176.8, 129.3)], "F.Cu")
    add("U7", "Power_Protection:USBLC6-2SC6", "USBLC6-2SC6", SOT23_6, (173.0, 131.6),
        {"1": "USB_DP", "6": "USB_DP", "3": "USB_DN", "4": "USB_DN", "5": "VBUS", "2": "GND"}, 90)  # fmt: skip
    add("D3", "Device:D_Schottky", "B5819W", SOD123, (172.0, 137.0), {"1": "VIN", "2": "VBUS"}, 180)

    # ---- the phone line: protection, loop sense and AC load, the feed, the switch ---------------
    add("J2", "Connector_Generic:Conn_01x02", "PHONE", term(2), (J_LINE, TERM_Y), {"1": "TIP_EXT", "2": "RING"})
    add("F2", "Device:Polyfuse", "0.1A 60V", PTC, (J_LINE, 151.0), {"1": "TIP_EXT", "2": "TIP"}, 90)
    # RING returns through R22: 24 mA off hook reads 1.1 V.
    r("R22", "47", "RING", "GND", (J_LINE + 3.5, 151.0), 90, fp=R0805)
    # Flat, above the strip kept for the terminals' names, between R22 and R19.
    add("D4", "Device:D_TVS", "SMAJ30CA", SMA, (130.6, 149.8), {"1": "TIP", "2": "GND"}, 0)
    r("R23", "10k", "RING", "LOOP_ADC", (124.5, 147.6), 0)
    c("C24", "10n", "LOOP_ADC", (124.5, 143.4), 0)  # above the serial box's keep-out: its via goes beside it
    # The line's AC load: 620 ohm through 2.2 uF across TIP and RING.
    r("R24", "620", "TIP", "TERM_AC", (121.6, 144.4), 0, fp=R0805)
    add("C25", "Device:C", "2.2u 50V", C1206, (121.6, 141.6), {"1": "TERM_AC", "2": "RING"}, 0)
    # The feed: Q3 passes the loop current, Q4 limits it to ~0.65 V / 27 ohm = 24 mA. Q5 (LINE_EN)
    # turns the line on; R21 holds it off in reset.
    add("Q3", "Transistor_BJT:BCP53", "BCP53", "Package_TO_SOT_SMD:SOT-223", (131.6, 144.2),
        {"1": "FEED_B", "2": "TIP", "3": "FEED_E", "4": "TIP"}, 180)  # fmt: skip
    r("R18", "27", "VIN", "FEED_E", (138.4, 141.2), 0, fp=R0805)
    add("Q4", "Transistor_BJT:MMBT3906", "MMBT3906", SOT23, (138.4, 144.2), {"1": "FEED_E", "2": "VIN", "3": "FEED_B"}, 0)
    r("R42", "47k", "FEED_B", "VIN", (141.0, 144.2), 90)  # Q3 off while Q5 is off
    r("R19", "10k", "FEED_B", "FEED_ON", (135.0, 150.0), 90, fp=R0603)
    add("Q5", "Transistor_BJT:MMBT3904", "MMBT3904", SOT23, (138.4, 150.0), {"1": "LINE_EN_B", "2": "GND", "3": "FEED_ON"}, 0)
    # R20, R43 and R21, R44 stand in 2 columns beside Q5.
    r("R20", "4.7k", "LINE_EN", "LINE_EN_B", (141.0, 149.4), 90)
    r("R21", "100k", "LINE_EN_B", "GND", (142.2, 149.4), 90)
    # Tones out: the LEDC PWM through 2 RC poles (2.3 kHz each), then onto TIP through C28 and R27.
    # Low impedances: with 10k and 10n the line's load took the tone down to -33 dBm (sim/tone_out.cir).
    r("R25", "1k", "TONE", "TONE_1", (134.6, 131.6), 0)
    c("C26", "68n", "TONE_1", (134.6, 132.8), 0)
    r("R26", "1k", "TONE_1", "TONE_2", (134.6, 134.0), 0)
    c("C27", "68n", "TONE_2", (134.6, 135.2), 0)
    c("C28", "1u 50V", "TONE_2", (137.2, 133.4), 90, b="TONE_AC", fp=C0805)
    r("R27", "470", "TONE_AC", "TIP", (139.4, 133.4), 90, fp=R0603)
    # DTMF in: TIP through C29 and R28 onto a mid-rail bias (R29, R30), clamped by D5.
    c("C29", "100n 50V", "TIP", (141.4, 133.4), 90, b="DTMF_AC", fp=C0603)
    r("R28", "22k", "DTMF_AC", "DTMF_ADC", (143.0, 133.4), 90)
    r("R29", "100k", "+3V3", "DTMF_ADC", (144.2, 133.4), 90)
    r("R30", "100k", "DTMF_ADC", "GND", (145.4, 133.4), 90)
    add("D5", "Diode:BAV99", "BAV99", SOT23, (148.6, 133.4), {"1": "GND", "2": "+3V3", "3": "DTMF_ADC"}, 0)

    # ---- the supervised inputs (J3): pull-up, series R, filter; U8 clamps the field wiring -------
    add("J3", "Connector_Generic:Conn_01x04", "INPUTS", term(4), (J_IN, TERM_Y),
        {"1": "Z1_EXT", "2": "Z2_EXT", "3": "Z3_EXT", "4": "GND"})  # fmt: skip
    add("U8", "Power_Protection:ESDA6V1-5SC6", "ESDA6V1-5SC6", SOT23_6, (J_IN + 5.2, 151.6),
        {"1": "Z1_EXT", "3": "Z2_EXT", "4": "Z3_EXT", "5": "TAMPER_EXT", "2": "GND"})  # fmt: skip
    for k in range(3):
        n = k + 1
        x = J_IN + 3.5 * k
        r(f"R{31 + 4 * k}", "100", f"Z{n}_EXT", f"ZONE{n}", (x, 147.6), 90, fp=R0603)
        r(f"R{32 + 4 * k}", "4.7k", "+3V3", f"ZONE{n}", (x - 0.6, 144.0), 90)
        r(f"R{33 + 4 * k}", "10k", f"ZONE{n}", f"ZONE{n}_ADC", (x + 0.6, 144.0), 90)
        c(f"C{30 + k}", "10n", f"ZONE{n}_ADC", (x + 0.6, 141.6), 90)
    # The cabinet's tamper switch (closed while the door is shut) on J8, a screw terminal in the row
    # beside the inputs: the switch arrives on bare wire, and U8 clamps its line too.
    add("J8", "Connector_Generic:Conn_01x02", "TAMPER", term(2), (J_TAMPER, TERM_Y), {"1": "TAMPER_EXT", "2": "GND"})
    r("R43", "1k", "TAMPER_EXT", "TAMPER", (141.0, 152.4), 90)
    r("R44", "10k", "TAMPER", "+3V3", (142.2, 152.4), 90)

    # ---- the trouble relay (K1), held on while healthy -------------------------------------------
    add("J7", "Connector_Generic:Conn_01x03", "TROUBLE", term(3), (J_OUT, TERM_Y),
        {"1": "TRBL_NC", "2": "TRBL_C", "3": "TRBL_NO"})  # fmt: skip
    K1 = (169.0, 143.0)
    add("K1", "Relay:Omron_G6K-2", "G6K-2F-Y 3V", "Relay_SMD:Relay_DPDT_Omron_G6K-2F-Y", K1,
        {"A1": "+3V3", "A2": "RELAY_COIL", "11": "TRBL_C", "21": "TRBL_C", "12": "TRBL_NC", "22": "TRBL_NC",
         "14": "TRBL_NO", "24": "TRBL_NO"}, 90)  # fmt: skip
    # The driver beside the coil: Q6's drain next to A2.
    add("Q6", "Transistor_FET:2N7002", "2N7002", SOT23, (161.7, 140.6), {"1": "RELAY_G", "2": "GND", "3": "RELAY_COIL"}, 0)
    r("R45", "100", "RELAY_DRV", "RELAY_G", (158.3, 139.4), 90)
    r("R46", "100k", "RELAY_G", "GND", (158.3, 141.8), 90)
    add("D6", "Diode:1N4148W", "1N4148W", SOD123, (167.1, 137.0), {"1": "+3V3", "2": "RELAY_COIL"}, 180)
    # By hand: K1's C and NO contacts (pads 11 and 14) straight down to J7's pins 2 and 3. The router
    # found no way for NO past the strip under the terminals' names, and took C round the label; each
    # piece was probed clear (`workcenter inspect probe`) on the routed board: the front to a via
    # clear of the legend, then In2.Cu under both faces' words.
    for net, dx, pin in (("TRBL_C", 1.6, 3.5), ("TRBL_NO", 3.8, 7.0)):
        pad, to = (K1[0] + dx, K1[1] + 3.5), (J_OUT + pin, TERM_Y)
        via_at = (pad[0], 149.6)
        d.track(net, [pad, via_at], "F.Cu")
        d.via(net, *via_at)
        d.track(net, [via_at, to], "In2.Cu")

    # ---- the status column, the buttons ---------------------------------------------------------
    leds = [("D7", "POWER", "green", None), ("D8", "CELL", "green", "LED_CELL"), ("D9", "WI-FI", "green", "LED_WIFI"),
            ("D10", "ALARM", "red", "LED_ALARM"), ("D11", "TROUBLE", "yellow", "LED_TRBL")]  # fmt: skip
    for k, (ref, name, colour, net) in enumerate(leds):
        y = LED_Y[k]
        a = f"{ref}_A"
        add(ref, "Device:LED", colour, LED0603, (LEDS_X, y), {"1": "GND", "2": a}, 180)
        r(f"R{47 + k}", "1k", net or "+3V3", a, (LEDS_X - 3.0, y), 0)
        # The name on the far side of the light, where no track runs (the keep-out below).
        label(name, LEDS_X + 2.2, y, 1.0, "left", thick=0.15)
    add("SW1", "Switch:SW_Push", "TEST", BUTTON, (179.4, 140.0), {"1": "BTN_TEST", "2": "GND"})
    add("SW2", "Switch:SW_Push", "RESET", BUTTON, (179.4, 146.0), {"1": "EN", "2": "GND"})
    label("TEST", 179.4, 137.4, 1.0, thick=0.15)
    label("RESET", 179.4, 143.0, 1.0, thick=0.15)
    # No copper on the face under the lights' and the buttons' names.
    for x0, y0, x1, y1, what in ((173.2, 108.6, 180.9, 120.6, "the lights' names"),
                                 (177.4, 136.7, 181.4, 138.1, "TEST"), (177.4, 142.3, 181.4, 143.7, "RESET")):  # fmt: skip
        d.keepout([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layers=("F.Cu",), name=what)

    # ---- the mounting holes: bare, so the panel's 0 V never meets the cabinet; fiducials ----------
    for k, (hx, hy) in enumerate(((X0 + 3.8, Y0 + 3.8), (X1 - 3.8, Y0 + 3.8), (X0 + 3.8, Y1 - 3.8), (X1 - 3.8, Y1 - 3.8))):
        add(f"H{k + 1}", "Mechanical:MountingHole", "M3", "MountingHole:MountingHole_3.2mm_M3", (hx, hy), {})
    # 3 fiducials for the pick and place: the BG95's LGA and the 0.65 mm TSSOP want them.
    for k, at in enumerate(((105.0, 109.4), (175.0, 106.6), (179.4, 152.6))):
        add(f"FID{k + 1}", "Mechanical:Fiducial", "Fiducial", "Fiducial:Fiducial_1mm_Mask2mm", at, {})

    # ---- the legend -----------------------------------------------------------------------------
    def terminal_names(x, names, pitch=3.5):
        for k, name in enumerate(names):
            label(name, x + pitch * k, LABEL_Y, 1.0, thick=0.15)

    terminal_names(J_PWR, ["+24V", "0V"])
    terminal_names(J_LINE, ["TIP", "RING"])
    terminal_names(J_TAMPER, ["TAMP", "0V"])
    label("TROUBLE OUT", J_OUT + 3.5, LABEL_Y - 2.0, 0.8, thick=0.13)
    terminal_names(J_IN, ["ALM", "SUP", "TBL", "0V"])
    terminal_names(J_OUT, ["NC", "C", "NO"])
    # No copper on the face under the names: every track to a terminal arrives from the inner layers.
    d.keepout([(J_PWR - 2.4, LABEL_Y - 0.8), (J_OUT + 9.4, LABEL_Y - 0.8), (J_OUT + 9.4, LABEL_Y + 0.8),
               (J_PWR - 2.4, LABEL_Y + 0.8)], layers=("F.Cu",), name="terminal names")  # fmt: skip
    label("LTE", pad60[0] + 4.0, 103.4, 1.0, thick=0.15)
    label("NANO SIM", sx, 103.4, 1.0, thick=0.15)
    label("WI-FI", ex + 5.2, 103.4, 1.0, thick=0.15)
    # Beside the port, above CC1's track into A5, with no copper on the face under it.
    label("USB", 175.2, 127.5, 1.0, thick=0.15, angle=90)
    d.keepout([(174.6, 125.9), (175.8, 125.9), (175.8, 129.0), (174.6, 129.0)], layers=("F.Cu",), name="USB")
    # The mark, in the clearing under the ESP32: a flame and the name.
    flame(150.0, 126.0, 6.0)
    label("HERALD", 153.8, 125.0, 2.4, "left", thick=0.4)
    label("FIRE ALARM COMMUNICATOR", 153.9, 128.0, 0.75, "left", thick=0.13)
    label("LTE-M + WI-FI   v0.1", 153.9, 129.7, 0.75, "left", thick=0.13)
    # No copper on the face under the mark; the left edge clears C20's pad (M137).
    d.keepout([(147.7, 122.6), (170.3, 122.6), (170.3, 130.5), (147.7, 130.5)], layers=("F.Cu",), name="the mark on the front")

    # ---- the back: the mark, and what an installer needs before the board goes in the cabinet -----
    B_SILK = "B.SilkS"
    cx = (X0 + X1) / 2
    flame(cx, 108.6, 8.0, B_SILK)
    # No track or via under the mark and the name on the back, nor between them.
    for x0, y0, x1, y1, what in ((cx - 3.8, 104.2, cx + 3.8, 113.0, "the mark"), (cx - 8.2, 113.0, cx + 8.2, 119.0, "the name")):
        d.keepout([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layers=("B.Cu",), name=f"{what} on the back")
    label("HERALD", cx, 117.2, 3.0, None, B_SILK, 0.5)
    line((cx - 30.0, 125.6), (cx + 30.0, 125.6), 0.2, B_SILK)
    # What it is, under the rule: the band above it is the vias between the SIM, the modem and U4.
    label("FIRE ALARM COMMUNICATOR", cx, 129.2, 1.2, None, B_SILK, 0.2)
    label("LTE-M  +  WI-FI    v0.1", cx, 131.2, 1.0, None, B_SILK, 0.16)
    notes = [
        "NEVER TIE 0 V TO EARTH OR TO THE CABINET:",
        "THE PANEL REPORTS AN EARTH FAULT. THE HOLES ARE BARE.",
        "TIP AND RING ARE THE PANEL DIALER'S PHONE LINE.",
        "LTE ANTENNA ON THE U.FL BESIDE THE MODEM;",
        "WI-FI ANTENNA ON THE ESP32 MODULE'S OWN U.FL.",
    ]
    for k, note in enumerate(notes):
        label(note, cx, 133.6 + 1.75 * k, 0.9, None, B_SILK, 0.15)
    # Write-on boxes for the modem's IMEI and the board's serial number.
    # Read from the back, the board's +x is to the left: each name sits at the larger x, its box after
    # it, in 1 row.
    for name, at, x0, x1 in (("IMEI", 170.8, 143.8, 167.8), ("SERIAL", 136.8, 111.8, 132.8)):
        label(name, at, 145.8, 1.0, None, B_SILK, 0.15)
        box(x0, 144.6, x1, 147.0, 0.15, B_SILK)
    label("MADE WITH VIA: DESIGN.PY TO KICAD 10, ERC, DRC, SIM, EXPORT", cx, 150.6, 0.8, None, B_SILK, 0.13)
    groups = [
        (J_PWR + 1.75, "24 V IN", "AUX 18-28 V"),
        (J_LINE + 1.75, "DIALER", "DACT LINE"),
        (J_TAMPER + 1.75, "TAMPER", "CLOSED = SHUT"),
        (J_IN + 5.25, "SUPERVISED INPUTS", "4.7k EOL AT CONTACT"),
        (J_OUT + 3.5, "TROUBLE OUT", "C-NO CLOSED = OK"),
    ]
    # Each group's 2 lines just over its terminal's pins, in the band behind the front's names, where
    # no via goes: the band above is where U8 and the tamper line need theirs.
    for gx, title, what in groups:
        label(title, gx, 154.6, 0.9, None, B_SILK, 0.15)
        label(what, gx, 156.2, 0.7, None, B_SILK, 0.12)
    # No track or via under the back's words: the subtitles, both write-on boxes with their names, and
    # each terminal group's 2 lines (a letter is about 0.92 of its height wide).
    words = [(cx - 12.6, 128.3, cx + 12.6, 131.9, "the subtitles"),
             (143.6, 144.35, 173.0, 147.25, "the IMEI box"), (111.6, 144.35, 139.8, 147.25, "the serial box")]  # fmt: skip
    for gx, title, what in groups:
        half = max(len(title) * 0.9, len(what) * 0.7) * 0.92 / 2 + 0.5
        words.append((gx - half, 153.9, gx + half, 156.8, f"{title.lower()}'s lines"))
    for x0, y0, x1, y1, what in words:
        d.keepout([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], layers=("B.Cu",), name=f"{what} on the back")

    # 3D bodies for the 2 modules KiCad's 3D library has none for (models/make_models.py).
    d.model("U3", "${KIPRJMOD}/models/bg95.wrl", replace=True)
    d.model("U5", "${KIPRJMOD}/models/esp32_s3_mini_1u.wrl", replace=True)
    d.model("C9", "${KIPRJMOD}/models/polymer_3528.wrl", replace=True)
    # The terminals are the black PT 1,5 (BK): KiCad's bodies recoloured (models/make_models.py).
    for ref, n in (("J1", 2), ("J2", 2), ("J8", 2), ("J3", 4), ("J7", 3)):
        d.model(ref, f"${{KIPRJMOD}}/models/pt15_{n}_bk.step", replace=True)

    # Pulls the board does not hold itself, each with what holds it.
    d.defined_nets = {
        "MDM_STATUS": "the BG95 drives STATUS",
        "MDM_RI": "the BG95 drives RI",
        "MDM_TXD": "the BG95 drives its TXD",
        "STATUS_3V3": "U4's B side, driven from the BG95's STATUS through the translator",
        "RI_3V3": "U4's B side, driven from the BG95's RI through the translator",
        "ESP_RXD": "U4's B side, driven from the BG95's TXD",
        "TAMPER_EXT": "R44 (10k) to +3V3 through R43",
        "BTN_TEST": "GPIO39's internal pull-up, set in firmware",
        "BOOT": "U1 charges C3 from its VCC through its own bootstrap switch each cycle",
        "MDM_RESET": "the BG95 pulls RESET_N up inside (Hardware Design V1.1, 3.7); Q2 only pulls it low",
        "MDM_RXD": "U4's A side holds it at VDD_EXT through its internal 10k while the modem is on",
        "SIM_RST": "the BG95 drives USIM_RST through R9",
        "SIM_CLK": "the BG95 drives USIM_CLK through R10",
    }
    d.check_pulls = True
    # No reference designators on the legend: the board's own words name each connector, light and
    # button, and 120 references at this density print over pads and each other. The fabrication
    # layer and the assembly drawing carry them.
    for part in d.parts:
        part.hide_ref = True
    # A ground via beside each pad a route of round 6 walled off from the front pour, held before routing.
    d.reserve_vias(["U5.63", "C24.2", "J5.SH", "C13.2"])
    lay_out_schematic(d)
    return d


# ---- the schematic: blocks in signal order, each support part beside the pin it serves ------------
#
# Each block: its ICs and connectors in a row at the block's origin (sheet grid units of 2.54 mm),
# then every small part placed next to the pin of a part already placed that shares a net with it,
# turned so the pin it joins faces that pin. A net inside 1 block is a wire; a net that joins 2 blocks
# is a label at each pin. Power nets are drawn with their symbols.
BLOCKS = [
    ("power", (10, 24), ["J1", "U1", "U2", "F1", "D2", "D1", "C1", "C2", "C4", "C3", "L1", "R1", "R2", "C5", "C6",
                        "R3", "R4", "C7", "C8"]),
    ("ESP32, USB, status", (130, 24), ["U5", "J6", "U7", "R13", "C23", "SW2", "R14", "R17", "C21", "C22", "R15",
                                       "R16", "D3", "SW1", "R47", "D7", "R48", "D8", "R49", "D9", "R50", "D10",
                                       "R51", "D11"]),
    ("modem", (10, 84), ["U3", "J4", "U4", "J5", "Q1", "R5", "R6", "Q2", "R7", "R8", "C9", "C10", "C11", "C12",
                        "C13", "C14", "C15", "C16", "R9", "R10", "R11", "R12", "C17", "U6", "C18", "C19", "C20"]),
    ("phone line", (150, 96), ["J2", "Q3", "Q5", "D5", "F2", "D4", "R22", "R23", "C24", "R24", "C25", "R18", "Q4",
                               "R42", "R19", "R20", "R21", "R27", "C28", "R26", "C27", "R25", "C26", "C29", "R28",
                               "R29", "R30"]),
    ("inputs, relay", (150, 150), ["J3", "U8", "J8", "K1", "J7", "R31", "R32", "R33", "C30", "R35", "R36", "R37",
                                   "C31", "R39", "R40", "R41", "C32", "R43", "R44", "Q6", "R45", "R46", "D6"]),
    ("holes", (10, 200), ["H1", "H2", "H3", "H4", "FID1", "FID2", "FID3"]),
]


def lay_out_schematic(d: kicadgen.Design) -> None:
    g = 2.54
    parts = {p.ref: p for p in d.parts}
    occupied: dict[str, tuple[float, float, float, float]] = {}
    block_of: dict[str, str] = {}
    skips: dict[str, int] = {}

    def extent(p: kicadgen.Part, margin: float) -> tuple[float, float, float, float]:
        x0, y0, x1, y1 = kicadgen.Design._sheet_box(p.symbol, p.sch_at, p.sch_rot)
        for pin in p.symbol.pins:
            x, y, _, _ = d._pin_point(p, pin)
            x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
        # Room for the reference and value beside the body, and for a power symbol off each pin.
        return (x0 - margin, y0 - 2 * margin, x1 + margin + 4 * g, y1 + 2 * margin)

    def free(b: tuple[float, float, float, float], ref: str) -> bool:
        if b[0] < 15 * g or b[1] < 15 * g or b[2] > 315 * g or b[3] > 220 * g:
            return False  # off the A1 sheet's frame
        return all(b[2] <= o[0] or b[0] >= o[2] or b[3] <= o[1] or b[1] >= o[3] for r, o in occupied.items() if r != ref)

    def anchor_and_pin(p: kicadgen.Part, rails: bool):
        """The placed pin p should sit beside, and p's own pin that joins it: a signal net, or a rail
        once no signal partner is left to wait for; never GND alone."""
        block = block_of[p.ref]
        # Sorted in full: a set's order changes from run to run, and the sheet must not.
        for net in sorted(set(p.nets.values()), key=lambda n: (n in d.power_nets, n == "GND", n)):
            if net == "GND" or (net in d.power_nets and not rails):
                continue
            for q in d.parts:
                if q is p or q.ref not in occupied or block_of.get(q.ref) != block:
                    continue
                for qpin in q.symbol.pins:
                    if q.nets.get(qpin.number) == net:
                        own = next(pin for pin in p.symbol.pins if p.nets.get(pin.number) == net)
                        return q, qpin, own
        return None

    def candidates(p: kicadgen.Part, rails: bool):
        """Where p may go, nearest first: (position, angle)."""
        found = anchor_and_pin(p, rails)
        if found is None:
            return
        q, qpin, own = found
        ax, ay, adx, ady = d._pin_point(q, qpin)
        rail = q.nets.get(qpin.number) in d.power_nets
        lateral = (5, -5, 9, -9, 13, -13, 17, -17) if rail else (0, 3, -3, 6, -6, 9, -9, 12, -12)
        for rot in (0, 90, 180, 270):
            p.sch_rot, p.sch_at = rot, (0.0, 0.0)
            ox, oy, odx, ody = d._pin_point(p, own)
            # A rail is drawn as a symbol off each pin, so a part on a rail stands upright beside the
            # pin; a part on a signal faces the pin it joins.
            if (rail and rot != 0) or (not rail and (odx, ody) != (-adx, -ady)):
                continue
            for k in range(4 if rail else 3, 13):
                for j in lateral:
                    tx = ax + adx * k * g + ady * j * g
                    ty = ay + ady * k * g + adx * j * g
                    yield (round((tx - ox) / g) * g, round((ty - oy) / g) * g), rot

    def place(p: kicadgen.Part, rails: bool) -> bool:
        """The first free spot after the ones refused before (`skips`)."""
        n = skips.get(p.ref, 0)
        for at, rot in candidates(p, rails):
            p.sch_at, p.sch_rot = at, rot
            b = extent(p, g)
            if free(b, p.ref):
                if n == 0:
                    occupied[p.ref] = b
                    return True
                n -= 1
        return False

    order: list[str] = []
    for name, (bx, by), refs in BLOCKS:
        big = [r for r in refs if not (r[0] in "RCDQLF" or r.startswith(("SW", "FID", "H")))]
        x = bx
        for ref in big:
            p = parts[ref]
            xs = [pin.x for pin in p.symbol.pins] or [0]
            ys = [pin.y for pin in p.symbol.pins] or [0]
            w = (max(xs) - min(xs)) / g + 4
            h = (max(ys) - min(ys)) / g + 4
            p.sch_at, p.sch_rot = ((x + round(w / 2)) * g, (by + round(h / 2)) * g), 0
            occupied[ref] = extent(p, g)
            block_of[ref] = name
            x += round(w) + 14
        small = [r for r in refs if r not in big]
        for ref in small:
            block_of[ref] = name
        for attempt in range(6):
            small = [r for r in small if not place(parts[r], rails=attempt >= 2)]
            if not small:
                break
        # What found no spot beside a pin (a hole, a fiducial, a part whose neighbours are full): the
        # nearest free spot to the block's origin, scanning rows of the sheet downward.
        for ref in small:
            p = parts[ref]
            spots = ((bx + 6 * col, by + 4 * row) for row in range(0, 50) for col in range(0, 50))
            for sx, sy in spots:
                p.sch_at, p.sch_rot = (sx * g, sy * g), 0
                if free(extent(p, g), ref):
                    occupied[ref] = extent(p, g)
                    break
            else:
                raise ValueError(f"{ref}: no free spot on the sheet")
        order += refs
    missing = [r for r in parts if r not in block_of]
    if missing:
        raise ValueError(f"no block for {missing}")
    blocks_of_net: dict[str, set] = {}
    for p in d.parts:
        for net in p.nets.values():
            blocks_of_net.setdefault(net, set()).add(block_of[p.ref])
    d.sch_label_nets = tuple(sorted(n for n, b in blocks_of_net.items() if len(b) > 1 and n not in d.power_nets))
    d.sch_wires = True
    # The sheet's wiring knows what this layout does not (each rail's symbol, each field's text): draw
    # it, and move a part it refuses to that part's next free spot, until it draws.
    for _ in range(200):
        try:
            d.schematic()
            return
        except ValueError as e:
            ref = str(e).split()[0]
            if ref not in parts or ref not in occupied:
                raise
            skips[ref] = skips.get(ref, 0) + 1
            del occupied[ref]
            if not place(parts[ref], rails=True):
                raise
    raise ValueError("the schematic did not draw after 200 moves")
