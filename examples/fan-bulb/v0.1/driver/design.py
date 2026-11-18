"""Lark v0.1, the driver: the mains in, 2 LED currents and the 3.3 V rail, standing in the neck.

The board stands in the bulb's XZ plane from the E26 base up to 1 mm under the light disc
(bulb.py: driver_corners); its 2 tongues pass the disc and solder to its pads. It is 20.0 mm wide
in the base and widens with the neck's cone to 45.9 mm under the disc. The tall parts stand on the
axis, where the cavity is deepest; bulb.fit() holds every part inside the housing.

Mains: J1 (the base's eyelet, L) and J2 (its shell, N). F1, a 10 ohm fusible resistor, limits the
inrush and opens on a fault; RV1 (150 V rms) clamps a surge at 395 V; BR1 rectifies. C2, L1 and
C3+C4 are a pi filter: 9.9 uF of 400 V electrolytic holds the bus above the LED strings' 77 V
through each 120 Hz valley down to 108 V rms at full power (sim/bus_valley.cir), so the LEDs see no
120 Hz ripple: under a ceiling fan's blades a ripple shows as a strobe.

LEDs: 2 average-current bucks, U1 (warm) and U2 (cool), HV9961 each. The strings' anodes sit on
VBUS (LED_A); each string's cathode returns through its choke (L2, L3) to its MOSFET (Q1, Q2). The
current is 0.185 x V(LD) / R_CS (Microchip DS20005588B, Eq. 3-3): the brain's 20 kHz PWM on DIM_W
and DIM_C, filtered to a steady LD voltage by R5-R8 and C7-C8, sets each string's current from
13.5 % to 100 % with no PWM at the LEDs. LED_EN holds both off until the brain runs.

3.3 V: U3, a LinkSwitch-TN2 LNK3205 high-side buck, from VBUS straight to +3V3 for the brain (about
0.5 W, always on: the brain listens with the light off).

The mode slider: U5 and U6, Hall switches at the neck's +x edge, under the slider's magnet track.
A magnet over U5 is Alexa, over U6 Apple, between them neither: the slider's 3 places.

    workcenter design driver/design.py --route      # from the version's folder
"""

from __future__ import annotations

import math
import re
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import bulb  # noqa: E402
from bulb import X0  # noqa: E402

R0402 = "Resistor_SMD:R_0402_1005Metric"
R0603 = "Resistor_SMD:R_0603_1608Metric"
R1206 = "Resistor_SMD:R_1206_3216Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"
C1812 = "Capacitor_SMD:C_1812_4532Metric"
CAP_LYING = "Lark:CP_Radial_D8.0mm_L11.5mm_P3.50mm_Lying"
CHOKE = "Inductor_THT:L_Radial_D9.5mm_P5.00mm_Fastron_07HVP"
SDR0604 = "Inductor_SMD:L_Bourns_SDR0604"
B = "B.Cu"
F = "F.Cu"

# Net class HV: every node that differs from GND by up to the rectified mains. Net class LNK: the
# LinkSwitch's switch node and the pins that ride on it. rules/lark.kicad_dru keeps both 0.8 mm
# from the logic.
HV = ["AC_L", "AC_LF", "AC_N", "VRECT", "VBUS", "LED_A", "LED_KW", "LED_KC", "SW_W", "SW_C"]
LNK = ["LNK_SW", "LNK_BP", "LNK_FB", "LNK_FBV"]


class DriverDesign(bulb.BulbDesign):
    def dsn(self, seed=None) -> str:
        """The router's file, with 2 changes.

        FreeRouting keeps the larger of 2 net classes' clearances and never sees
        rules/lark.kicad_dru. A class_class rule gives it the rule file's 0.8 mm between the
        LinkSwitch's nets and the logic, GND among them, while LNK keeps 0.2 mm among its own nets;
        a layer rule gives HV and LNK the rule file's 0.2 mm on In2.

        kicadgen leaves In1, the ground plane, out of the router's file, so the router would join
        every GND pad with tracks of its own. Here In1 goes back in as a power layer holding a GND
        plane: each surface GND pad's via (plane_vias) and each through-hole GND pad meets it, so
        GND has nothing left to route, and its pads keep GND's clearances."""
        text = super().dsn(seed)
        layers = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
        text = re.sub(r"    \(layer (\S+) \(type signal\) \(property \(index \d+\)\)\)\n", "", text)
        defs = "".join(
            f"    (layer {name} (type {'power' if name == 'In1.Cu' else 'signal'}) (property (index {i})))\n"
            for i, name in enumerate(layers)
        )
        text = text.replace("  (structure\n", "  (structure\n" + defs, 1)
        # Every shape a hole carries on In2 it carries on In1.
        text = re.sub(r"(\n(\s+)\(shape \((\w+) )In2\.Cu( [^\n]*)", r"\n\2(shape (\3 In1.Cu\4\1In2.Cu\4", text)
        outline = re.search(r"\(boundary\n\s+\(path pcb 0 ([^)]*)\)", text).group(1)
        plane = f'    (plane "GND" (polygon In1.Cu 0 {outline}))\n'
        text = text.replace("    (boundary\n", plane + "    (boundary\n", 1)
        # Inside the board the rule file keeps 0.2 mm (IPC-2221B B1): so does the router on In2.
        inner = "(layer_rule In2.Cu (rule (clearance 2000)))"
        text = re.sub(r"(\n    \(class (?:HV|LNK) [^\n]*\n(?:      [^\n]*\n)*?      \(rule [^\n]*\))", r"\1\n      " + inner, text)
        last = text.rindex("\n    (class ")
        end = text.index("\n    )", last) + len("\n    )")
        pair = f"\n    (class_class (classes LNK kicad_default) (rule (clearance 8000)) {inner})"
        return text[:end] + pair + text[end:]


def at(x: float, z: float) -> tuple[float, float]:
    return bulb.drv_xy(x, z)


def build() -> DriverDesign:
    zb, zt = bulb.DRV_Z0, bulb.TONGUE_TOP
    w = bulb.half_width(bulb.DRV_ZTOP)
    d = DriverDesign(
        name="lark_driver",
        namespace=uuid.UUID("4d7f0a92-63b1-4c8e-9a25-e1f6b30c7d58"),
        outline=(X0 - w, 160.0 - zt, X0 + w, 160.0 - zb),
        sheet="A3",
        thickness=bulb.DRV_T,
        copper_layers=4,
        plane_layers=("In1.Cu",),
        track_width=0.3,
        clearance=0.2,
    )
    d.corners = bulb.driver_corners()
    d.colours = {"F.Mask": "Black", "B.Mask": "Black", "F.SilkS": "White", "B.SilkS": "White"}
    d.footprint_dirs = {"Lark": bulb.FOOTPRINTS}
    d.symbol_dirs = {"Lark": bulb.SYMBOLS}
    d.fab = str(bulb.HERE / "rules" / "lark.kicad_dru")
    # VBUS is drawn as KiCad's HT (high tension), LNK_SW as +VSW (a switched rail). Each comes through
    # a passive part (L1, U3's own switch), so each gets a PWR_FLAG, as GND (BR1's -) and +3V3 (L4) do.
    d.power_nets = {"GND": "GND", "+3V3": "+3V3", "VBUS": "HT", "LNK_SW": "+VSW"}
    d.flagged_nets = ["GND", "+3V3", "VBUS", "LNK_SW"]
    d.sch_wires = True
    d.check_sim = True
    d.check_pulls = True
    # In1.Cu is a whole ground plane (bus -); 2 layers left 26 links unrouted at 0.8 mm of mains
    # spacing in the base's 20 mm.
    d.zone("GND", layers=("In1.Cu",), connect="solid")
    d.net_classes = {
        "HV": {"width": 0.4, "clearance": 0.8, "via": 0.8, "via_drill": 0.4, "nets": HV},
        # The LinkSwitch's own nets ride on its switch node, within 5 V of each other.
        "LNK": {"width": 0.3, "clearance": 0.2, "via": 0.6, "via_drill": 0.3, "nets": LNK},
    }

    def add(ref, lib, value, fp, nets, pos, rot=0.0, layer=F):
        return d.add(ref, lib, value, fp, sch_at=(0, 0), pcb_at=pos, pcb_rot=rot, pcb_layer=layer, nets=nets)

    def r(ref, value, a, b, pos, rot=0.0, layer=F, fp=R0402):
        return add(ref, "Device:R", value, fp, {"1": a, "2": b}, pos, rot, layer)

    def c(ref, value, a, pos, rot=0.0, layer=F, fp=C0402, b="GND"):
        return add(ref, "Device:C", value, fp, {"1": a, "2": b}, pos, rot, layer)

    # ---- the joints at the top: J3-J6
    for k, j in enumerate(j for j in bulb.JOINTS if j.board == "driver"):
        n = len(j.nets)
        add(f"J{k + 3}", f"Connector_Generic:Conn_01x{n:02d}", j.name.upper(), f"Lark:Tongue_{j.name}",
            {str(i + 1): net for i, net in enumerate(j.nets)}, bulb.tongue_at(j), 0.0, bulb.tongue_layer(j))  # fmt: skip
        d.no_sim(f"J{k + 3}", "solder joints to the light disc")

    # ---- the mains: in the E26 base, surface-mount parts only (a lead through the board would
    # stand under a part on the other face)
    tp = "TestPoint:TestPoint_THTPad_D2.0mm_Drill1.0mm"
    add("J1", "Connector:TestPoint", "L (eyelet)", tp, {"1": "AC_L"}, at(-6.6, 6.6))
    add("J2", "Connector:TestPoint", "N (shell)", tp, {"1": "AC_N"}, at(6.6, 6.6))
    d.no_sim("J1", "the lamp's lead to the base's eyelet")
    d.no_sim("J2", "the lamp's lead to the base's shell")
    r("F1", "10 fusible", "AC_L", "AC_LF", at(0.0, 7.0), 0.0, F, "Resistor_SMD:R_MELF_MMB-0207")
    add("RV1", "Device:Varistor", "CU3225K150G2", "Lark:RV_SMD_TDK_CU3225", {"1": "AC_LF", "2": "AC_N"},
        at(0.0, 9.4), 0.0, B)  # fmt: skip
    d.no_sim("RV1", "a varistor: it conducts only in a surge, which the decks do not apply")
    add("BR1", "Diode_Bridge:MB6S", "MB10S", "Package_TO_SOT_SMD:TO-269AA",
        {"1": "AC_LF", "2": "AC_N", "3": "VRECT", "4": "GND"}, at(0.0, 11.8), 0.0, F)  # fmt: skip
    d.sim("BR1", library="sim/models/mb10s.lib", name="MB10S", pins={"1": "AC1", "2": "AC2", "3": "P", "4": "N"})
    c("C1", "100n 630V", "VRECT", at(-6.4, 12.0), 90.0, F, C1812)
    add("L1", "Device:L", "470u", SDR0604, {"1": "VRECT", "2": "VBUS"}, at(8.0, 33.0), 0.0, B)
    # The pi filter's 3 x 3.3 uF 400 V, 105 C, 15000 h (Nichicon ULD2G3R3MPD), all on the back in a
    # column on the axis, where the cavity is deepest, each with its leads at the top of its can (on
    # the back a rotation of 180 lays the can down the board). Nothing on the front stands over a lead.
    add("C2", "Device:C_Polarized", "3.3u 400V", CAP_LYING, {"1": "VRECT", "2": "GND"}, at(0.0, 28.6), 180.0, B)
    add("C3", "Device:C_Polarized", "3.3u 400V", CAP_LYING, {"1": "VBUS", "2": "GND"}, at(0.0, 43.0), 180.0, B)
    add("C4", "Device:C_Polarized", "3.3u 400V", CAP_LYING, {"1": "VBUS", "2": "GND"}, at(0.0, 57.4), 180.0, B)

    # ---- 3.3 V: U3, LNK3205 high-side buck. Pins from KiCad's symbol, values from Power
    # Integrations' LinkSwitch-TN2 datasheet rev. Q: FB 2.00 V, 49 uA; R11 2.49k to S, R10 sets
    # (3.3 - 2.0) / (2.0 / 2.49k + 49 uA) = 1.53k; C10 0.1 uF, the standard current limit.
    # The project's symbol (symbols/lnk3205d.csv): KiCad's marks D open-collector, and D is the
    # part's power input from VBUS.
    add("U3", "Lark:LNK3205D", "LNK3205D", "Package_SO:PowerIntegrations_SO-8C",
        {"1": "LNK_BP", "2": "LNK_FB", "4": "VBUS", "5": "LNK_SW", "6": "LNK_SW", "7": "LNK_SW", "8": "LNK_SW"},
        at(0.0, 18.8), 90.0, F)  # fmt: skip
    d.no_sim("U3", "Power Integrations publishes no SPICE model (PI Expert only)")
    c("C10", "100n", "LNK_BP", at(-3.4, 24.3), 90.0, F, C0603, b="LNK_SW")
    add("D4", "Diode:US1J", "US1J", "Diode_SMD:D_SMA", {"1": "LNK_FBV", "2": "+3V3"}, at(6.3, 18.8), 90.0, F)
    d.sim("D4", library="../../library/diodes/US1J.spice.txt", name="DI_US1J", pins={"1": "K", "2": "A"})
    c("C11", "10u", "LNK_FBV", at(1.6, 24.4), 90.0, F, C0805, b="LNK_SW")
    r("R10", "1.54k", "LNK_FBV", "LNK_FB", at(-0.2, 24.0), 90.0)
    r("R11", "2.49k", "LNK_FB", "LNK_SW", at(-1.6, 24.0), 90.0)
    add("D3", "Diode:US1J", "ES1J", "Diode_SMD:D_SMA", {"1": "LNK_SW", "2": "GND"}, at(-6.3, 18.8), 90.0, F)
    d.no_sim("D3", "ES1J: Diodes Inc. publishes no model, and the LinkSwitch it serves has none")
    add("L4", "Device:L", "150u", SDR0604, {"1": "LNK_SW", "2": "+3V3"}, at(-6.6, 29.4), 0.0, F)
    c("C12", "47u", "+3V3", at(5.6, 29.0), 90.0, F, C1206)
    c("C13", "47u", "+3V3", at(-1.0, 33.6), 0.0, F, C1206)
    r("R12", "1k", "+3V3", "GND", at(8.0, 27.6), 90.0, F, R0603)  # PI's 3 mA minimum load

    # ---- the LED channels: U1 warm at -x, U2 cool at +x, both on the front, each turned so its
    # PWMD, VDD, LD and RT face the axis and the small parts behind them (turned the other way, 30
    # links stayed open, against 20); their chokes L2 and L3
    # stand on the front in the neck's widest part, their leads clear of the capacitors' column.
    # Values: R_CS 2.74 ohm, 100 mA at V(LD) 1.48 V (Eq. 3-3); R_T 54.9k, a 2.5 us off-time
    # (Eq. 3-1: RT/25 + 0.3); L 2.2 mH, 84 mA of ripple at 74 V; C_O 2.2 uF across each string.
    for ref_u, ref_q, ref_d, ref_l, ref_rcs, ref_rt, ref_cdd, ref_co, ref_ra, ref_rb, ref_cl, side, s in (
        ("U1", "Q1", "D1", "L2", "R1", "R2", "C5", "C14", "R5", "R6", "C7", "W", -1.0),
        ("U2", "Q2", "D2", "L3", "R3", "R4", "C6", "C15", "R7", "R8", "C8", "C", 1.0),
    ):
        k, sw, cs, gate, vdd, rt, ld = (f"LED_K{side}", f"SW_{side}", f"CS_{side}", f"GATE_{side}", f"VDD_{side}",
                                        f"RT_{side}", f"LD_{side}")  # fmt: skip
        add(ref_u, "Driver_LED:HV9961LG-G", "HV9961LG-G", "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm",
            {"1": "VBUS", "2": cs, "3": "GND", "4": gate, "5": "LED_EN", "6": vdd, "7": ld, "8": rt},
            at(8.8 * s, 36.0), 0.0 if s < 0 else 180.0, F)  # fmt: skip
        d.sim(ref_u, library="sim/models/hv9961.lib", name="HV9961",
              pins={"1": "VIN", "2": "CS", "3": "GND", "4": "GATE", "5": "PWMD", "6": "VDD", "7": "LD", "8": "RT"})  # fmt: skip
        add(ref_q, "Transistor_FET:BSP89", "IPN60R1K5PFD7S", "Package_TO_SOT_SMD:SOT-223-3_TabPin2",
            {"1": gate, "2": sw, "3": cs}, at(11.4 * s, 43.4), 0.0 if s < 0 else 180.0, F)  # fmt: skip
        # Both MOSFETs' pins face out, their tabs in. The tab and the middle pin are both the drain,
        # 2 pads the router left apart on both channels: joined here across the body, 1.4 mm from
        # the gate's and the source's pads.
        xq, yq = at(11.4 * s, 43.4)
        d.track(sw, [(xq - 3.15, yq), (xq + 3.15, yq)], F, width=0.6)
        d.sim(ref_q, library="../../library/infineon/Simulation_model_CoolMOS_PFD7_MOSFET_600V_Spice.lib",
              name="IPN60R1K5PFD7S_L1", pins={"1": "gate", "2": "drain", "3": "source"})  # fmt: skip
        add(ref_d, "Diode:US1J", "US1J", "Diode_SMD:D_SMA", {"1": "VBUS", "2": sw}, at(4.6 * s, 45.0), 90.0, F)
        d.sim(ref_d, library="../../library/diodes/US1J.spice.txt", name="DI_US1J", pins={"1": "K", "2": "A"})
        add(ref_l, "Device:L", "2.2m 07HVP", CHOKE, {"1": sw, "2": k}, at(10.2 * s, 51.6), 90.0, F)
        # its small parts on the back, behind its controller
        r(ref_rcs, "2.74", cs, "GND", at(13.0 * s, 40.0), 90.0, B, R1206)
        x = 6.0 * s
        z0 = 34.2 if s < 0 else 37.6
        r(ref_rt, "54.9k", rt, "GND", at(x, z0), 0.0, B)
        c(ref_cdd, "1u", vdd, at(x, z0 + 1.2), 0.0, B)
        r(ref_ra, "12.1k", f"DIM_{side}", ld, at(x, z0 + 2.4), 0.0 if s < 0 else 180.0, B)  # LD toward U2's links
        r(ref_rb, "10k", ld, "GND", at(x, z0 + 3.6), 0.0, B)
        c(ref_cl, "1u", ld, at(x, z0 + 4.8), 0.0, B)
        c(ref_co, "2.2u 100V", "LED_A", at(4.0 * s, 51.3), 90.0, F, C1206, b=k)
    # The strings' anodes are VBUS: the tongue's LED_A pads join it here.
    r("R9", "0", "VBUS", "LED_A", at(0.0, 50.6), 0.0, F, R1206)

    # ---- VBUS for the brain's ADC: 2 M over 24.9k, 2.43 V at 198 V (140 V rms)
    r("R13", "1M", "VBUS", "VS1", at(-6.0, 15.4), 90.0, B, R1206)
    r("R14", "1M", "VS1", "VBUS_SENSE", at(-6.0, 20.2), 90.0, B, R1206)
    r("R15", "24.9k", "VBUS_SENSE", "GND", at(-8.2, 20.2), 90.0, B)
    c("C16", "10n", "VBUS_SENSE", at(-8.2, 17.6), 90.0, B)

    # ---- the mode slider's Hall switches at the neck's +x edge, 19 mm apart along it: U6 stands
    # above Q2, whose source and gate reach the back behind it
    for ref, cref, z, net, layer in (("U5", "C17", 31.0, "HALL_A", F), ("U6", "C18", 50.0, "HALL_B", B)):
        x = bulb.half_width(z) - 3.0
        add(ref, "Sensor_Magnetic:DRV5033AJxDBZ", "DRV5033AJQDBZ", "Package_TO_SOT_SMD:SOT-23",
            {"1": "+3V3", "2": net, "3": "GND"}, at(x, z), 90.0, layer)  # fmt: skip
        d.no_sim(ref, "a Hall switch: digital out, read by the brain")
        c(cref, "100n", "+3V3", at(x - 2.2, z), 90.0, layer)

    # Values that carry a rating on the sheet; each simulates as the number.
    for ref, kind, value in (("F1", "R", "r=10"), ("C1", "C", "c=100n"), ("C2", "C", "c=3.3u"), ("C3", "C", "c=3.3u"),
                             ("C4", "C", "c=3.3u"), ("L2", "L", "l=2.2m"), ("L3", "L", "l=2.2m"), ("C14", "C", "c=2.2u"),
                             ("C15", "C", "c=2.2u")):  # fmt: skip
        d.sim(ref, device=kind, params=value)
    d.defined_nets = {
        "LNK_BP": "U3's own BYPASS regulator charges C10 from the drain, 5.0 V over its source (LinkSwitch-TN2 datasheet)",
        "LED_EN": "each HV9961's PWMD has a 100k pull-down of its own (DS20005588B, p.3): both off until U1 on the brain drives it",
        "DIM_W": "the brain's U1 (IO2, LEDC) drives it; R6 holds LD_W at 0 until then",
        "DIM_C": "the brain's U1 (IO3, LEDC) drives it; R8 holds LD_C at 0 until then",
    }
    hand_routes(d)
    missed = plane_vias(d)
    if missed:
        raise SystemExit(f"driver: no via to the ground plane fits beside {', '.join(missed)}")
    for part in d.parts:
        part.hide_ref = True
    # Bodies for the parts KiCad's 3D library has none for (footprints/make_models.py).
    for ref, body in (("L1", "sdr0604"), ("L4", "sdr0604"), ("C2", "cap_lying_d8_l11.5"), ("C3", "cap_lying_d8_l11.5"),
                      ("C4", "cap_lying_d8_l11.5"), ("RV1", "cu3225")):  # fmt: skip
        d.model(ref, f"${{KIPRJMOD}}/models/{body}.wrl", replace=True)
    lay_out_schematic(d)
    bulb.fit(d, "driver")
    return d


def hand_routes(d) -> None:
    """The links the router leaves open, drawn pad to pad (PROCESSES.md P4, step 7). Every
    coordinate is a pad's position from `workcenter inspect list driver`, or a via placed beside one.

    The tongues' pads stand 0.35 mm from the tongue's top edge, under the HV class's 0.8 mm, so the
    router starts no track from an HV tongue pad: the 3 string nets are drawn from the tongue into the
    board. The LV tongue's 4 back pads go down past C4's and L3's leads together. Each controller's
    VIN, CS and GATE face out at the cone's edge, where the router found no way: each goes through a
    via, CS by its sense resistor on the back, VIN on In2 to C3."""
    hv = {"size": 0.8, "drill": 0.4}
    # The HV tongue: LED_KW down to L2; LED_KC down and across on In2 to L3; LED_A's 2 back pads
    # joined, and down to a via and across on In2 to C14.
    d.track("LED_KW", [(91.4, 98.225), (91.4, 101.8), (89.8, 103.4)], F)
    d.track("LED_KC", [(94.4, 98.225), (94.4, 101.0), (95.2, 101.8)], F)
    d.via("LED_KC", 95.2, 101.8, **hv)
    d.track("LED_KC", [(95.2, 101.8), (96.2, 104.6), (108.0, 104.6), (110.2, 103.4)], "In2.Cu")
    d.track("LED_A", [(91.4, 98.225), (94.4, 98.225)], B)
    d.track("LED_A", [(92.9, 98.225), (92.9, 102.2)], B)
    d.via("LED_A", 92.9, 102.2, **hv)
    d.track("LED_A", [(92.9, 102.2), (94.6, 110.5)], "In2.Cu")
    d.via("LED_A", 94.6, 110.5, **hv)
    d.track("LED_A", [(94.6, 110.5), (96.0, 110.175)], F)
    d.track("LED_A", [(94.6, 110.5), (100.2, 110.5), (100.6, 110.9)], "In2.Cu")  # under R9, to R9 and C15
    d.via("LED_A", 100.6, 110.9, **hv)
    d.track("LED_A", [(100.6, 110.9), (101.463, 109.4), (102.6, 110.175), (104.0, 110.175)], F)
    # DIM_C from the LV tongue: down the front, round C4's VBUS lead, to a via 1.6 mm under LED_KC's
    # In2 track, and on In2 past C15 and under Q2's tab to R7 on the back.
    d.track("DIM_C", [(104.7, 98.225), (104.7, 103.6), (102.4, 105.9), (100.3, 105.9), (100.0, 106.2)], F)
    d.via("DIM_C", 100.0, 106.2)
    d.track("DIM_C", [(100.0, 106.2), (106.9, 113.1), (107.4, 113.6), (107.4, 119.6), (107.3, 119.7)], "In2.Cu")
    d.via("DIM_C", 107.3, 119.7)
    d.track("DIM_C", [(107.3, 119.7), (106.51, 120.0)], B)
    # The LV tongue's back: LED_EN, HALL_A, HALL_B, VBUS_SENSE side by side, 1.1 mm apart, from the
    # tongue to under the capacitors' column, clear of C4's VBUS lead and L3's LED_KC lead.
    for net, x0, x1 in (("LED_EN", 104.7, 104.3), ("HALL_A", 106.3, 105.4), ("HALL_B", 107.9, 106.5),
                        ("VBUS_SENSE", 109.5, 107.6)):  # fmt: skip
        d.track(net, [(x0, 98.225), (x1, 98.225 + 1.25 * (x0 - x1) + 0.8), (x1, 105.5)], B)
    # The front's GND pad to the plane, between the bundle and L3's lead: 0.9 mm from the lead.
    d.track("GND", [(109.5, 98.225), (108.65, 101.45)], F)
    d.via("GND", 108.65, 101.45)
    # U1: GATE from Q1's gate to a via and on In2 under Q1 and U1 to U1's pin 4; CS from Q1's
    # source to R1 on the back and on to U1's pin 2; VIN from a via under U1 on In2 to C3's lead.
    d.track("GATE_W", [(85.45, 114.3), (85.45, 113.0)], F)
    d.via("GATE_W", 85.45, 113.0)
    d.track("GATE_W", [(85.45, 113.0), (89.0, 113.0), (89.0, 126.8)], "In2.Cu")  # inside: the cone's edge is near
    d.via("GATE_W", 89.0, 126.8)
    d.track("GATE_W", [(89.0, 126.8), (88.725, 125.905)], F)
    d.track("CS_W", [(85.45, 118.9), (85.45, 120.2)], F)
    d.via("CS_W", 85.45, 120.2)
    d.track("CS_W", [(85.45, 120.2), (87.0, 121.463), (87.2, 123.4)], B)
    d.via("CS_W", 87.2, 123.4)
    d.track("CS_W", [(87.2, 123.4), (88.725, 123.365)], F)
    d.track("VBUS", [(88.725, 122.0), (90.2, 122.0), (90.6, 121.6)], F, width=0.3)
    d.via("VBUS", 90.6, 121.6, **hv)
    d.track("VBUS", [(90.6, 121.6), (91.2, 121.0), (97.3, 121.0), (101.75, 117.0)], "In2.Cu")
    d.track("VDD_W", [(93.675, 124.635), (91.9, 124.635)], F)
    d.via("VDD_W", 91.9, 124.635)
    d.track("VDD_W", [(91.9, 124.635), (93.52, 124.6)], B)
    # U2, turned the other way: GATE straight to Q2's gate; CS from Q2's source out to a via, on the
    # back to R3 and on to U2's pin 2; VIN from a via under U2 on In2 to C3's lead.
    d.track("GATE_C", [(111.275, 122.095), (113.3, 122.095), (114.55, 120.85), (114.55, 118.9)], F)
    d.track("CS_C", [(114.55, 114.3), (116.15, 114.3)], F)
    d.via("CS_C", 116.15, 114.3)
    d.track("CS_C", [(116.15, 114.3), (114.3, 116.15), (114.3, 121.463), (113.0, 121.463), (112.85, 124.635)], B)
    d.via("CS_C", 112.85, 124.635)
    d.track("CS_C", [(112.85, 124.635), (111.275, 124.635)], F)
    d.track("VBUS", [(111.275, 126.0), (109.4, 126.0)], F, width=0.3)
    d.via("VBUS", 109.4, 126.0, **hv)
    d.track("VBUS", [(109.4, 126.0), (102.4, 126.0), (102.0, 125.6), (102.0, 118.0), (101.75, 117.0)], "In2.Cu")
    # U2's VDD, LD and RT pins face the axis, its parts sit above it on the back and L1 below it: each
    # pin's link runs out on the front, nested, and up to a via beside its part.
    for net, y_pin, x_up, y_via, x_part in (("VDD_C", 123.365, 104.9, 121.2, 105.52), ("LD_C", 124.635, 104.2, 120.0, 105.49),
                                            ("RT_C", 125.905, 103.5, 122.4, 105.49)):  # fmt: skip
        d.track(net, [(106.325, y_pin), (x_up, y_pin), (x_up, y_via)], F)
        d.via(net, x_up, y_via)
        d.track(net, [(x_up, y_via), (x_part, y_via)], B)
    # +3V3 for U6 and C18, and HALL_B from U6, through the 2.4 mm between L3's leads: +3V3 on the
    # front, 1.05 mm from each lead, HALL_B on In2. HALL_A from the bundle's end down In2 to U5.
    d.track("+3V3", [(107.9, 98.225), (107.9, 105.9), (113.2, 105.9)], F)
    d.via("+3V3", 113.2, 105.9)
    d.track("+3V3", [(113.2, 105.9), (113.2, 110.48), (114.656, 110.48), (114.656, 112.2), (117.806, 112.2),
                     (117.806, 110.938)], B)  # fmt: skip
    d.track("HALL_B", [(106.5, 105.5), (106.5, 106.4)], B)
    d.via("HALL_B", 106.5, 106.4)
    d.track("HALL_B", [(106.5, 106.4), (107.0, 105.9), (111.8, 105.9), (115.606, 109.7), (115.906, 109.7)], "In2.Cu")
    d.via("HALL_B", 115.906, 109.7)
    d.track("HALL_B", [(115.906, 109.7), (115.906, 110.938)], B)
    d.track("HALL_A", [(105.4, 105.5), (105.4, 107.4), (106.0, 108.0), (106.0, 108.6)], B)
    d.via("HALL_A", 106.0, 108.6)  # 1.1 mm from C15's 2 string pads
    d.track("HALL_A", [(106.0, 108.6), (108.4, 111.0), (111.8, 114.4), (111.8, 127.85), (112.15, 128.2)], "In2.Cu")
    d.via("HALL_A", 112.15, 128.2)
    d.track("HALL_A", [(112.15, 128.2), (111.261, 129.938)], F)


def plane_vias(d, net: str = "GND") -> list[str]:
    """A via to In1's ground plane beside every surface GND pad, and a track from the pad's middle to
    it: the router never joins GND (DriverDesign.dsn). The nearest place that fits wins, up to 4.5 mm
    off (a tongue's pad reaches down to the board). Each via and track keeps the board's clearance,
    and 0.8 mm from every HV and LNK pad (rules/lark.kicad_dru), which kicadgen's own checks do not
    read. Returns the pads where none fits."""
    r, drill = d.via_size / 2, d.via_drill
    holes = d.hole_clearances()
    hot = {n for n in HV + LNK}

    def clear(n1: str, n2: str) -> float:
        if n1.lstrip("/") in hot or n2.lstrip("/") in hot:
            return 0.8 - 1e-6
        return max(d.class_of(n1)["clearance"], d.class_of(n2)["clearance"]) - 1e-6

    def gap(h, x: float, y: float) -> float:
        """A point's distance to a pad's copper: its circle, or its box."""
        if h.shape == "circle":
            return math.hypot(x - (h.x1 + h.x2) / 2, y - (h.y1 + h.y2) / 2) - (h.x2 - h.x1) / 2
        return math.hypot(max(h.x1 - x, 0.0, x - h.x2), max(h.y1 - y, 0.0, y - h.y2))

    def places(pad):
        cx, cy = (pad.x1 + pad.x2) / 2, (pad.y1 + pad.y2) / 2
        g = 0.15
        yield from ((cx, pad.y2 + g + r), (cx, pad.y1 - g - r), (pad.x2 + g + r, cy), (pad.x1 - g - r, cy))
        reach = max(pad.x2 - pad.x1, pad.y2 - pad.y1) / 2 + g + r
        for k in range(int((4.5 - reach) / 0.25) + 1):
            for j in range(32):
                a = math.pi * j / 16
                yield cx + (reach + 0.25 * k) * math.cos(a), cy + (reach + 0.25 * k) * math.sin(a)

    missed = []
    boxes = d.pad_boxes()
    drawn = {end for n, a, b, _, _ in d.segments if n == net for end in (a, b)}  # pads with a hand via
    for pad in [b for b in boxes if b.net == net and b.kind == "smd"]:
        if (round((pad.x1 + pad.x2) / 2, 3), round((pad.y1 + pad.y2) / 2, 3)) in drawn:
            continue
        hot_pads = [b for b in boxes if b.net.lstrip("/") in hot]
        mid = (round((pad.x1 + pad.x2) / 2, 3), round((pad.y1 + pad.y2) / 2, 3))
        for vx, vy in places(pad):
            v = (round(vx, 3), round(vy, 3))
            far = all(gap(h, vx, vy) >= 0.8 + r for h in hot_pads)
            body = vy >= 160.0 - bulb.DRV_ZTOP + r  # on the board, not on a tongue in the disc's slot
            if not (far and body and d.inside_outline(vx, vy, 0.35 + r) and d._via_fits(vx, vy, r, drill, net, boxes)):
                continue
            if d._track_problem((net, mid, v, 0.3, pad.layer), boxes, holes, clear, []):
                continue
            d.via(net, *v)
            d.track(net, [mid, v], pad.layer, width=0.3)
            break
        else:
            missed.append(f"{pad.ref}.{pad.number}")
    return missed


def lay_out_schematic(d) -> None:
    """Mains left to right along the top, the 2 channels under it, the 3.3 V supply at the bottom."""
    g = 2.54
    parts = {p.ref: p for p in d.parts}
    rows = [["J1", "F1", "RV1", "J2", "BR1", "C1", "C2", "L1", "C3", "C4", "R9", "R13", "R14", "R15", "C16"],
            ["U1", "Q1", "D1", "L2", "R1", "R2", "C5", "C14", "R5", "R6", "C7", "J3", "J5"],
            ["U2", "Q2", "D2", "L3", "R3", "R4", "C6", "C15", "R7", "R8", "C8", "J4", "J6"],
            ["U3", "C10", "D4", "C11", "R10", "R11", "D3", "L4", "C12", "C13", "R12", "U5", "C17", "U6", "C18"]]  # fmt: skip
    for i, row in enumerate(rows):
        x = 14
        for ref in row:
            wide = 12 if ref.startswith(("U", "J")) else 7
            parts[ref].sch_at, parts[ref].sch_rot = ((x + wide // 2) * g, (16 + 22 * i) * g), 0
            x += wide
