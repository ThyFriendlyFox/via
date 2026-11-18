"""Lark v0.1, the brain: a mast in the dome with the radio, the voice chip and their memory.

The mast stands on the light disc in the bulb's YZ plane, 90 degrees round from the driver, and
reaches up to the ear under the dome's tip (bulb.py: brain_corners). Its bottom tongue passes the
disc and solders to the disc's pads (J1, J2): the driver's 8 signals and the disc's temperature.
Its top tongue passes the ear (J3, J4): the microphones' supply and their PDM pair.

U1, an ESP32-C6-MINI-1-H4 (105 C), is the bulb's network and its light. It runs Zigbee 3.0 to an
Echo or HomeKit over Thread to a HomePod or an Apple TV, chosen by the mode slider (HALL_A, HALL_B),
and it sets the 2 LED currents (DIM_W, DIM_C, LED_EN). Its antenna stands past the mast's -y edge,
in the dome, clear of every copper layer.

U2, an ESP32-S3R8, hears. Its 8 MB of octal PSRAM in the package holds ESP-SR's front end, wake word
and command models (85 C with the PSRAM's ECC on). It has no antenna: its own radio is not wired to
anything, and the only path out of it is U1's UART (S3_TXD, S3_RXD), which carries commands, never
sound. U1 holds U2's CHIP_PU and GPIO0, so U1 can update U2's firmware. U3 is U2's 16 MB flash,
powered from U2's VDD_SPI.

    workcenter design brain/design.py --route      # from the version's folder

Layers: F.Cu the parts and signals, In1.Cu a ground plane, In2.Cu and B.Cu signals. The test pads
(TP1-TP10) sit on the back for a pogo jig: both chips' USB, U1's console and boot strap.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import bulb  # noqa: E402
from bulb import X0  # noqa: E402

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"
TP = "TestPoint:TestPoint_Pad_D1.0mm"
B = "B.Cu"


class BrainDesign(bulb.BulbDesign):
    pass


def at(y: float, z: float) -> tuple[float, float]:
    return bulb.brn_xy(y, z)


# Heights on the mast: U2's group stands on the disc (Z0), U1's group hangs under the ear (ZM, the
# module's middle, 10.6 mm under the ear so its antenna's top stays inside the dome).
Z0 = bulb.DISC_TOP
ZM = round(bulb.EAR_Z - 10.6, 2)


def build() -> BrainDesign:
    w = bulb.BRN_W / 2
    d = BrainDesign(
        name="lark_brain",
        namespace=uuid.UUID("c3a91e57-0d6b-4f28-9e14-7b5d2c8f6a03"),
        outline=(X0 - w, 160.0 - bulb.EAR_TOP, X0 + w, 160.0 - bulb.BRN_Z0),
        sheet="A3",
        thickness=bulb.BRN_T,
        copper_layers=4,
        plane_layers=("In1.Cu",),
        track_width=0.15,
        clearance=0.15,
        via_size=0.45,
        via_drill=0.2,
    )
    d.corners = bulb.brain_corners()
    d.colours = {"F.Mask": "White", "B.Mask": "White", "F.SilkS": "Black", "B.SilkS": "Black"}
    d.footprint_dirs = {"Lark": bulb.FOOTPRINTS}
    d.fab = str(bulb.HERE / "rules" / "lark.kicad_dru")
    d.rules = {"min_through_hole_diameter": 0.2, "min_via_diameter": 0.45}
    d.power_nets = {"GND": "GND", "+3V3": "+3V3", "VDD_SPI": "VDD"}
    d.flagged_nets = ["GND", "+3V3", "VDD_SPI"]  # +3V3 and GND come from the driver; VDD_SPI is U2's own output
    d.sch_wires = True
    d.check_sim = True
    d.check_pulls = True
    d.zone("GND", layers=("In1.Cu",), connect="solid")

    def add(ref, lib, value, fp, nets, pos, rot=0.0, layer="F.Cu"):
        return d.add(ref, lib, value, fp, sch_at=(0, 0), pcb_at=pos, pcb_rot=rot, pcb_layer=layer, nets=nets)

    def r(ref, value, a, b, pos, rot=0.0, layer=B):
        return add(ref, "Device:R", value, R0402, {"1": a, "2": b}, pos, rot, layer)

    def c(ref, value, a, pos, rot=0.0, layer=B, fp=C0402, b="GND"):
        return add(ref, "Device:C", value, fp, {"1": a, "2": b}, pos, rot, layer)

    # ---- the joints
    for k, j in enumerate(j for j in bulb.JOINTS if j.board == "brain"):
        n = len(j.nets)
        add(f"J{k + 1}", f"Connector_Generic:Conn_01x{n:02d}", j.name.upper(), f"Lark:Tongue_{j.name}",
            {str(i + 1): net for i, net in enumerate(j.nets)}, bulb.tongue_at(j), 0.0, bulb.tongue_layer(j))  # fmt: skip
        d.no_sim(f"J{k + 1}", "solder joints to the light disc and the ear")

    # ---- U1: ESP32-C6-MINI-1-H4. Pin numbers from KiCad's symbol, functions from Espressif's
    # ESP32-C6-MINI-1 datasheet v1.5, Table 3-1; the straps from Tables 4-1 and 4-3.
    c6 = {str(p): "GND" for p in (1, 2, 11, 14, *range(36, 54))}
    c6.update({
        "3": "+3V3", "8": "C6_EN",
        "12": "NTC", "13": "VBUS_SENSE",  # IO0, IO1: ADC1 channels 0 and 1
        "5": "DIM_W", "6": "DIM_C",  # IO2, IO3: LEDC, 20 kHz, filtered on the driver
        "9": "LED_EN",  # IO4: both LED controllers' PWMD
        "10": "HALL_A", "15": "HALL_B",  # IO5, IO6: the mode slider
        "16": "S3_EN", "24": "S3_BOOT",  # IO7, IO18: U2's CHIP_PU and GPIO0
        "28": "S3_RXD", "29": "S3_TXD",  # IO22 UART1 TX to U2's U0RXD, IO23 UART1 RX from its U0TXD
        "22": "C6_IO8",  # strap: 1 for download boot; it floats by default
        "23": "C6_BOOT",  # IO9, strap: weak pull-up, 1 = SPI boot
        "17": "C6_DN", "18": "C6_DP",  # USB Serial/JTAG
        "30": "C6_RX0", "31": "C6_TX0",  # the console
    })  # fmt: skip
    # The antenna past the mast's -y edge: the footprint's y = -5.6 (where its keep-out starts) on the edge.
    add("U1", "RF_Module:ESP32-C6-MINI-1", "ESP32-C6-MINI-1-H4", "RF_Module:ESP32-C6-MINI-1", c6,
        at(-w + 5.6, ZM), 90.0)  # fmt: skip
    d.no_sim("U1", "a radio module: digital, no analog behaviour in the decks")
    c("C1", "10u", "+3V3", at(-4.5, ZM + -5.4), 0.0, B, C0603)
    c("C2", "100n", "+3V3", at(-7.0, ZM + -5.4), 90.0)
    r("R1", "10k", "+3V3", "C6_EN", at(-1.6, ZM + -5.0), 90.0)
    c("C3", "1u", "C6_EN", at(-0.4, ZM + -5.0), 90.0)
    r("R2", "10k", "+3V3", "C6_IO8", at(0.8, ZM + -5.0), 90.0)

    # ---- U2: ESP32-S3R8. Pins from KiCad's symbol, functions from the ESP32-S3 datasheet v2.2,
    # Tables 2-1 and 2-11; decoupling from Espressif's hardware design guidelines, Fig. 1.
    s3 = {"2": "+3V3", "3": "+3V3", "20": "+3V3", "46": "+3V3", "55": "+3V3", "56": "+3V3", "57": "GND",
          "29": "VDD_SPI",
          "4": "S3_EN", "5": "S3_BOOT",
          "8": "S3_IO3",  # GPIO3, the JTAG strap: no pull of its own, held low by R5
          "9": "PDM_CLK", "10": "PDM_DATA",  # GPIO4, GPIO5: I2S0 in PDM receive mode
          "25": "S3_DN", "26": "S3_DP",
          "49": "S3_TXD", "50": "S3_RXD",
          "53": "XTAL_N", "54": "XTAL_P",
          "32": "FL_CS", "33": "FL_CLK", "35": "FL_IO0", "34": "FL_IO1", "31": "FL_IO2", "30": "FL_IO3"}  # fmt: skip
    # Turned so its UART, crystal and VDDA face the right column, its flash pins face down.
    add("U2", "MCU_Espressif:ESP32-S3", "ESP32-S3R8", "Package_DFN_QFN:QFN-56-1EP_7x7mm_P0.4mm_EP4x4mm", s3,
        at(-2.6, Z0 + 9.1), 270.0)  # fmt: skip
    d.no_sim("U2", "a processor: digital, no analog behaviour in the decks")
    for k in range(4):  # the exposed pad's vias to the ground plane
        d.via("GND", *at(-3.3 + 1.4 * (k % 2), Z0 + 8.4 + 1.4 * (k // 2)))
    c("C4", "10u", "+3V3", at(2.8, Z0 + 3.1), 90.0, "F.Cu", C0603)
    c("C5", "1u", "+3V3", at(1.0, Z0 + 3.1), 90.0, "F.Cu")
    c("C6", "100n", "+3V3", at(-6.6, Z0 + 8.5), 0.0)  # VDD3P3, pins 2 and 3
    c("C7", "100n", "+3V3", at(-3.6, Z0 + 4.5), 0.0)  # VDD3P3_RTC
    c("C8", "100n", "+3V3", at(3.0, Z0 + 12.1), 90.0, "F.Cu")  # VDD3P3_CPU
    c("C9", "1u", "+3V3", at(3.0, Z0 + 10.1), 90.0, "F.Cu")  # VDDA
    c("C10", "10n", "+3V3", at(3.0, Z0 + 8.1), 90.0, "F.Cu")
    c("C11", "1u", "VDD_SPI", at(1.2, Z0 + 4.5), 0.0)
    c("C12", "100n", "VDD_SPI", at(1.2, Z0 + 5.7), 0.0)
    r("R3", "10k", "+3V3", "S3_EN", at(-6.6, Z0 + 11.9), 0.0)
    c("C13", "1u", "S3_EN", at(-6.6, Z0 + 13.1), 0.0)
    r("R5", "10k", "S3_IO3", "GND", at(-6.6, Z0 + 10.7), 0.0)
    # The 40 MHz crystal beside U2's XTAL pins: 10 pF load, 12 pF on each side with about 4 pF of
    # board and pin (CL = 12 x 12 / 24 + 4); tune C14 and C15 on the first board to +-10 ppm.
    add("Y1", "Device:Crystal_GND24", "40MHz 10pF", "Crystal:Crystal_SMD_2016-4Pin_2.0x1.6mm",
        {"1": "XTAL_P", "2": "GND", "3": "XTAL_N", "4": "GND"}, at(5.6, Z0 + 10.1), 90.0)  # fmt: skip
    d.no_sim("Y1", "a crystal: its load capacitance is set by C14 and C15 and tuned on the first board")
    c("C14", "12p", "XTAL_P", at(5.6, Z0 + 12.3), 0.0, "F.Cu")
    c("C15", "12p", "XTAL_N", at(5.6, Z0 + 7.9), 0.0, "F.Cu")

    # ---- U3: 16 MB QSPI flash, 105 C grade, on the back under U2.
    fl = {"1": "FL_CS", "2": "FL_IO1", "3": "FL_IO2", "4": "GND", "5": "FL_IO0", "6": "FL_CLK", "7": "FL_IO3",
          "8": "VDD_SPI", "9": "GND"}  # fmt: skip
    add("U3", "Memory_Flash:W25Q128JVP", "W25Q128JVPJQ", "Package_SON:WSON-8-1EP_6x5mm_P1.27mm_EP3.4x4.3mm",
        fl, at(-1.8, Z0 + 9.3), 0.0, B)  # fmt: skip
    d.no_sim("U3", "flash memory: digital")
    r("R4", "10k", "VDD_SPI", "FL_CS", at(3.0, Z0 + 6.1), 90.0)  # holds the flash deselected while U2 resets

    # ---- the joint's signals: the slider's open-drain outputs and the disc's NTC
    r("R6", "10k", "+3V3", "HALL_A", at(5.4, Z0 + 5.1), 90.0, "F.Cu")
    r("R7", "10k", "+3V3", "HALL_B", at(6.6, Z0 + 5.1), 90.0, "F.Cu")
    r("R8", "10k", "+3V3", "NTC", at(6.8, Z0 + 7.5), 90.0, B)  # 0.1 %: the NTC's divider, steepest near 85 C
    c("C16", "100n", "NTC", at(6.8, Z0 + 10.1), 90.0, B)
    c("C17", "47u", "+3V3", at(-4.8, Z0 + 3.1), 0.0, "F.Cu", C1206)  # the rail's bulk, where it arrives (sim/rail_3v3.cir)

    # ---- test pads on the back, for a pogo jig: both USB ports, U1's console and boot strap
    pads = [("GND", "GND"), ("+3V3", "+3V3"), ("C6_DN", "C6 D-"), ("C6_DP", "C6 D+"), ("C6_BOOT", "C6 BOOT"),
            ("C6_EN", "C6 EN"), ("C6_TX0", "C6 TX"), ("C6_RX0", "C6 RX"), ("S3_DN", "S3 D-"), ("S3_DP", "S3 D+")]  # fmt: skip
    for k, (net, name) in enumerate(pads):
        y = -5.4 + 2.7 * (k % 5)
        z = ZM + 4.4 - 3.0 * (k // 5)
        add(f"TP{k + 1}", "Connector:TestPoint", name, TP, {"1": net}, at(y, z), 0.0, B)
        d.no_sim(f"TP{k + 1}", "a test pad")

    d.defined_nets = {
        "LED_EN": "each HV9961 on the driver pulls its PWMD down through 100k of its own: the LEDs stay off until U1 runs",
        "S3_BOOT": "U2's GPIO0 has a weak pull-up of its own (ESP32-S3 datasheet, Table 3-1)",
        "C6_BOOT": "U1's IO9 has a weak pull-up of its own (ESP32-C6-MINI-1 datasheet, Table 4-1)",
        "S3_RXD": "U1's UART1 TX drives it",
        "S3_TXD": "U2's U0TXD drives it",
        "PDM_DATA": "the microphones drive it in turn; 100k to GND on the ear holds it between",
        "FL_CLK": "U2's SPICLK: the boot ROM drives it from reset, and U3 ignores it while R4 holds FL_CS high",
        "XTAL_P": "the crystal's pin, biased inside U2 (ESP32-S3 datasheet, 40 MHz crystal input)",
    }
    # HALL_B up the mast's +y edge to U1's IO6: the router found no way past U2's group to it.
    # `workcenter inspect probe` found it clear before it was written here.
    a, b = pad_at(d, "R7", "2"), pad_at(d, "U1", "15")
    xr = X0 + 7.3
    d.track("HALL_B", [a, (xr, a[1] - 0.7), (xr, b[1] + 0.7), (xr - 0.7, b[1]), b], "F.Cu", width=0.15)

    for part in d.parts:
        part.hide_ref = True  # a mast 16 mm wide: the references are on the assembly drawing
    d.model("U1", "${KIPRJMOD}/models/esp32_c6_mini_1.wrl", replace=True)  # footprints/make_models.py
    lay_out_schematic(d)
    bulb.fit(d, "brain")
    return d


def pad_at(d, ref: str, number: str) -> tuple[float, float]:
    box = next(b for b in d.pad_boxes() if b.ref == ref and b.number == number)
    return (round((box.x1 + box.x2) / 2, 4), round((box.y1 + box.y2) / 2, 4))


def lay_out_schematic(d) -> None:
    """U1 on the left, U2 in the middle, U3 and the crystal on its right; the joints at the edges."""
    g = 2.54
    table = {"U1": (30, 40, 0), "U2": (80, 42, 0), "U3": (125, 34, 0), "Y1": (60, 72, 0),
             "J1": (10, 34, 180), "J2": (10, 54, 180), "J3": (150, 60, 0), "J4": (150, 68, 0)}  # fmt: skip
    small = [p for p in d.parts if p.ref not in table]
    for k, p in enumerate(small):
        table[p.ref] = (20 + 7 * (k % 18), 82 + 10 * (k // 18), 0)
    for part in d.parts:
        x, y, rot = table[part.ref]
        part.sch_at, part.sch_rot = (x * g, y * g), rot
