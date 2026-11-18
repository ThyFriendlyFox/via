"""Lark v0.1, the ear: a 15 mm disc under the dome's tip with the 2 microphones.

The bulb hangs base-up in a fan's light kit, so the dome's tip is the part of it that faces the
room. The ear lies flat just under the tip (bulb.py: EAR_Z), its top face 2 mm from the dome, and a
silicone gasket ring joins each microphone's port to its hole in the dome: sound reaches each
MEMS membrane through 2.8 mm of sealed channel, not through the dome's 24 cm3 of air, whose
Helmholtz resonance near 400 Hz would take the top of the speech band away.

MK1 and MK2, Knowles SPH0641LU4H-1 PDM microphones, sit on the underside with their bottom ports
through the board, 10.4 mm apart. They share 1 clock and 1 data line: MK1 answers on 1 clock edge
(SEL low), MK2 on the other (SEL high), and the brain's ESP32-S3 reads both in its PDM receiver at
2.048 MHz, 128 times ESP-SR's 16 kHz (the part's standard mode is 1.024 to 2.475 MHz). Both are
rated -40 to 100 C from 1.62 to 3.6 V, -26 dBFS and 64.3 dB(A) SNR: ESP-SR's microphone guide asks
for -26 dBFS and 64 dB. R2 and C1 take the LinkSwitch's 66 kHz ripple off their supply
(sim/mic_supply.cir); the dome's tip is the coolest place in a bulb that hangs base-up.

The brain's top tongue passes the ear's slot and solders to J1 and J2 on the underside.

    workcenter design ear/design.py --route      # from the version's folder
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import bulb  # noqa: E402
from bulb import X0, Y0  # noqa: E402

C0402 = "Resistor_SMD:R_0402_1005Metric".replace("Resistor", "Capacitor").replace("R_", "C_")
R0402 = "Resistor_SMD:R_0402_1005Metric"
MIC_FP = "Sensor_Audio:Knowles_LGA-5_3.5x2.65mm"
B = "B.Cu"
MIC_X = 5.2  # each microphone's middle, either side of the slot: 10.4 mm apart


class EarDesign(bulb.BulbDesign):
    pass


def build() -> EarDesign:
    r = bulb.EAR_R
    d = EarDesign(
        name="lark_ear",
        namespace=uuid.UUID("8e6d2b40-51c9-4a7e-a3f2-9d0c4b17e6a5"),
        outline=(X0 - r, Y0 - r, X0 + r, Y0 + r),
        sheet="A4",
        thickness=bulb.EAR_T,
        track_width=0.2,
        clearance=0.15,
        via_size=0.45,
        via_drill=0.2,
    )
    d.circle = (X0, Y0, r)
    d.holes = []
    for x0, y0, x1, y1 in bulb.ear_slots():
        a, b = bulb.disc_xy(x0, y1), bulb.disc_xy(x1, y0)
        d.holes.append(bulb.box_corners(a[0], a[1], b[0], b[1], bulb.SLOT_R))
        e = bulb.EDGE_PAD
        d.keepout([(a[0] - e, a[1] - e), (b[0] + e, a[1] - e), (b[0] + e, b[1] + e), (a[0] - e, b[1] + e)],
                  layers=("F.Cu", "B.Cu"), name="slot")  # fmt: skip
    d.colours = {"F.Mask": "White", "B.Mask": "White", "F.SilkS": "Black", "B.SilkS": "Black"}
    d.footprint_dirs = {"Lark": bulb.FOOTPRINTS}
    d.symbol_dirs = {"Lark": bulb.SYMBOLS}
    d.fab = str(bulb.HERE / "rules" / "lark.kicad_dru")
    d.rules = {"min_through_hole_diameter": 0.2, "min_via_diameter": 0.45}
    d.power_nets = {"GND": "GND", "+3V3": "+3V3", "MIC_VDD": "VDD"}
    d.flagged_nets = ["GND", "+3V3", "MIC_VDD"]  # from the brain through J1 and J2; MIC_VDD through R2
    d.sch_wires = True
    d.check_sim = True
    d.check_pulls = True
    d.zone("GND", layers=("F.Cu",), connect="solid")

    def add(ref, lib, value, fp, nets, pos, rot=0.0, layer=B):
        return d.add(ref, lib, value, fp, sch_at=(0, 0), pcb_at=pos, pcb_rot=rot, pcb_layer=layer, nets=nets)

    for k, j in enumerate(j for j in bulb.JOINTS if j.slot == "ear"):
        add(f"J{k + 1}", "Connector_Generic:Conn_01x02", j.name.upper(), f"Lark:SlotPads_{j.name}",
            {str(i + 1): net for i, net in enumerate(j.nets)}, (X0, Y0))  # fmt: skip
        d.no_sim(f"J{k + 1}", "solder joints to the brain's top tongue")

    # The microphones: pins from Knowles' SPH0641LU4H-1 datasheet rev. B. The project's symbol
    # (symbols/sph0641lu4h-1.csv) marks DATA tri-state: each microphone lets go of it for the half
    # clock that is the other's, so 2 on 1 line is the design, not 2 outputs fighting.
    # Each port 0.77 mm from its body's middle, toward -y on the sheet.
    for ref, x, sel in (("MK1", -MIC_X, "GND"), ("MK2", MIC_X, "MIC_VDD")):
        add(ref, "Lark:SPH0641LU4H-1", "SPH0641LU4H-1", MIC_FP,
            {"1": "PDM_DATA", "2": sel, "3": "GND", "4": "PDM_CLK", "5": "MIC_VDD"}, bulb.disc_xy(x, 0.0), 0.0)  # fmt: skip
        d.no_sim(ref, "a PDM microphone: its output is a bit stream; the deck holds its supply")
    for ref, x in (("C3", -MIC_X), ("C4", MIC_X)):
        add(ref, "Device:C", "100n", C0402, {"1": "MIC_VDD", "2": "GND"}, bulb.disc_xy(x, -3.0), 0.0)
    # The supply filter: 47 ohm and 2.2 uF, a pole at 1.5 kHz under the LinkSwitch's 66 kHz; the 2
    # microphones draw 1.4 mA at most (0.7 mA each at 2.4 MHz), 66 mV across R2.
    add("R2", "Device:R", "47", R0402, {"1": "+3V3", "2": "MIC_VDD"}, bulb.disc_xy(-1.4, 4.9), 90.0)
    add("C1", "Device:C", "2.2u", C0402, {"1": "MIC_VDD", "2": "GND"}, bulb.disc_xy(1.4, 4.9), 90.0)
    # Between the 2 microphones' turns on the data line nothing drives it: 100k holds it low.
    add("R1", "Device:R", "100k", R0402, {"1": "PDM_DATA", "2": "GND"}, bulb.disc_xy(-1.4, -4.9), 90.0)
    # While the S3 is in reset its GPIO4 floats: 100k holds the clock low, and with no clock the
    # microphones sleep (fCLOCK under 250 kHz, the SPH0641's sleep mode).
    add("R3", "Device:R", "100k", R0402, {"1": "PDM_CLK", "2": "GND"}, bulb.disc_xy(1.4, -4.9), 90.0)

    for part in d.parts:
        part.hide_ref = True
    d.text("LARK", X0, Y0 - 5.0, "F.SilkS", 1.0, 0.15)
    for ref in ("MK1", "MK2"):
        d.model(ref, "${KIPRJMOD}/models/sph0641lu4h_1.wrl", replace=True)  # footprints/make_models.py
    lay_out_schematic(d)
    bulb.fit(d, "ear")
    return d


def lay_out_schematic(d) -> None:
    g = 2.54
    table = {"J1": (20, 30, 180), "J2": (20, 40, 180), "R2": (36, 24, 90), "C1": (44, 30, 0),
             "MK1": (68, 30, 0), "MK2": (68, 46, 0), "C3": (56, 30, 0), "C4": (56, 46, 0), "R1": (84, 40, 0),
             "R3": (90, 40, 0)}  # fmt: skip
    for part in d.parts:
        x, y, rot = table[part.ref]
        part.sch_at, part.sch_rot = (x * g, y * g), rot
