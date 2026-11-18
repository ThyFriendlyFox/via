"""Lark v0.1, the light: an aluminium disc under the dome with 16 LEDs on a ring, warm and cool.

The disc lies on the neck's ledge (bulb.py: DISC_Z) and carries the light's heat into the housing.
It is a 1-layer aluminium board: copper, a thin dielectric, 1.0 mm of aluminium. B.Cu stays empty
and stands for the aluminium in the generated files; the fab notes in the README say so.

16 LEDs stand on 17 places round a circle 4 mm in from the edge, the place at -x left empty: the gap where the
warm string's 2 ends cross the ring. Round the ring from the gap they run W C W C W C W C C W C W C
W C W: each colour's 8 LEDs spread round the whole ring, and every string end sits next to the gap.
Both strings run clockwise (seen from the dome): the warm string joins its LEDs on the outside of
the ring, the cool string on the inside, and no 2 traces cross. Both anodes come back on the LED
slot's +y side, where its 2 pads are joined; both cathodes on its -y side.

3 slots take the driver's 2 tongues and the brain's tongue (bulb.py: disc_slots). Their pads
(J1-J6) carry the LED strings from the driver and 8 signals between the driver and the brain. RT1,
a 100k NTC, tells the brain the disc's temperature. Every trace on the disc is drawn here: the LED
links on their circles, and the 8 signals in 2 nests of 4 round the corners the brain's slot shares
with the driver's low-voltage slot, the driver's GND outermost and on round the brain slot's end to
RT1.

    workcenter design light/design.py --route      # from the version's folder
"""

from __future__ import annotations

import math
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import bulb  # noqa: E402
from bulb import X0, Y0  # noqa: E402

LED_FP = "LED_SMD:LED_PLCC_2835"
R_LED = bulb.DISC_R - 4.5  # the LEDs' circle: 18.1 mm on the A19's disc
R_OUT = R_LED + 2.4  # the warm string's links, outside the ring
R_IN = R_LED - 2.0  # the cool string's links, inside it
PLACES = 17  # 16 LEDs and the gap at -x
ORDER = "WCWCWCWCCWCWCWCW"  # round the ring anticlockwise from the gap
W_LINK = 0.6  # a link's width: the strings carry 0.13 A, and the copper spreads each LED's heat
HV_CLEAR = 0.6  # LED net to LED net, up to 2 strings' 70 V: IPC-2221B B2 (bare), 51-100 V. To logic: rules/lark.kicad_dru


class LightDesign(bulb.BulbDesign):
    def routing_layers(self) -> list[str]:
        return ["F.Cu"]  # 1 layer: B.Cu is the aluminium


def polar(r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return bulb.disc_xy(r * math.cos(a), r * math.sin(a))


def place_angle(k: int) -> float:
    return 180.0 + 360.0 * (k + 1) / PLACES


def build() -> LightDesign:
    d = LightDesign(
        name="lark_light",
        namespace=uuid.UUID("2f8b6c1e-94d7-4a35-b0e2-6c71d5a3f08e"),
        outline=(X0 - bulb.DISC_R, Y0 - bulb.DISC_R, X0 + bulb.DISC_R, Y0 + bulb.DISC_R),
        sheet="A3",
        thickness=1.0,
        track_width=0.3,
        clearance=0.2,
    )
    d.circle = (X0, Y0, bulb.DISC_R)
    d.holes = bulb.slot_holes()
    d.colours = {"F.Mask": "White", "F.SilkS": "Black"}
    d.core = "Aluminium"
    d.footprint_dirs = {"Lark": bulb.FOOTPRINTS}
    d.power_nets = {"GND": "GND", "+3V3": "+3V3"}
    d.flagged_nets = ["GND", "+3V3"]  # both arrive from the driver through J1
    d.sch_wires = True
    d.check_sim = True
    d.check_pulls = True
    hv = ["LED_A", "LED_KW", "LED_KC"] + [f"W{k}" for k in range(1, 8)] + [f"C{k}" for k in range(1, 8)]
    d.net_classes = {"HV": {"width": W_LINK, "clearance": HV_CLEAR, "via": 0.6, "via_drill": 0.3, "nets": hv}}
    d.fab = str(bulb.HERE / "rules" / "lark.kicad_dru")

    # ---- the joints: J1-J4 the driver's tongues, J5-J6 the brain's
    for k, j in enumerate(j for j in bulb.JOINTS if j.slot == "light"):
        n = len(j.nets)
        d.add(f"J{k + 1}", f"Connector_Generic:Conn_01x{n:02d}", j.name.upper(), f"Lark:SlotPads_{j.name}",
              sch_at=(0, 0), pcb_at=(X0, Y0), nets={str(i + 1): net for i, net in enumerate(j.nets)})  # fmt: skip
        d.no_sim(f"J{k + 1}", "solder joints to the driver or the brain: the strings' ends and the signals")

    # ---- the LEDs: both strings run clockwise, each from the place next to the gap at +y
    ws = [k for k, c in enumerate(ORDER) if c == "W"]
    cs = [k for k, c in enumerate(ORDER) if c == "C"]
    ref_of = {}
    for colour, places, first in (("W", ws, 1), ("C", cs, 9)):
        nets = ["LED_A"] + [f"{colour}{i}" for i in range(1, 8)] + [f"LED_K{colour}"]
        for i, k in enumerate(reversed(places)):
            ref_of[k] = (f"D{first + i}", nets[i], nets[i + 1])
    for k in range(len(ORDER)):
        ref, a, kk = ref_of[k]
        th = place_angle(k)
        # The footprint's +x (its anode pad) points back along the string, anticlockwise.
        # kicadgen turns the footprint's +x to (cos r, -sin r) on the sheet.
        # Bridgelux BXEN-27G-13H-9C (2700 K) and BXEN-50G-13H-9C (5000 K): 2835, 9 V (DS207)
        part = "BXEN-27G 2700K" if ORDER[k] == "W" else "BXEN-50G 5000K"
        d.add(ref, "Device:LED", part, LED_FP, sch_at=(0, 0), pcb_at=polar(R_LED, th),
              pcb_rot=round((th + 90.0) % 360.0, 4), nets={"1": kk, "2": a})  # fmt: skip
        d.sim(ref, library="sim/models/led_2835_9v.lib", name="LED9V", pins={"1": "K", "2": "A"})

    # ---- the disc's temperature: RT1 between the brain's back pads and the ground round the slot
    d.add("RT1", "Device:Thermistor_NTC", "100k B4250", "Resistor_SMD:R_0402_1005Metric", sch_at=(0, 0),
          pcb_at=bulb.disc_xy(-1.7, -3.4), pcb_rot=270.0, nets={"1": "NTC", "2": "GND"})  # fmt: skip
    d.sim("RT1", device="R", params="r=100k")

    # Each slot is a hole the router does not see: a keep-out over it and EDGE_PAD round it.
    e = bulb.EDGE_PAD
    for k, (x0, y0, x1, y1) in enumerate(bulb.disc_slots()):
        a, b = bulb.disc_xy(x0 - e, y1 + e), bulb.disc_xy(x1 + e, y0 - e)
        d.keepout([(a[0], a[1]), (b[0], a[1]), (b[0], b[1]), (a[0], b[1])], layers=("F.Cu",), name=f"slot {k + 1}")

    links(d, ref_of)
    for part in d.parts:
        part.hide_ref = True
    for part in [p for p in d.parts if p.footprint.name.endswith("LED_PLCC_2835")]:
        d.model(part.ref, "${KIPRJMOD}/models/led_2835.wrl", replace=True)  # footprints/make_models.py
    lay_out_schematic(d)
    bulb.fit(d, "light")
    return d


def lay_out_schematic(d) -> None:
    """The warm string on one row and the cool string under it, each LED's anode on its left, the
    LED tongue's pads at their left; the driver's 8 signals from J1 and J2 across to the brain's
    J5 under them; the NTC beside the brain's back pads (J6)."""
    g = 2.54
    table = {"J4": (25, 22, 180), "J3": (25, 34, 180), "J1": (25, 48, 180), "J2": (25, 58, 180),
             "J5": (75, 52, 0), "J6": (75, 66, 0), "RT1": (68, 66, 0)}  # fmt: skip
    for i in range(8):
        table[f"D{i + 1}"] = (36 + 6 * i, 20, 180)
        table[f"D{i + 9}"] = (36 + 6 * i, 30, 180)
    for part in d.parts:
        x, y, r = table[part.ref]
        part.sch_at, part.sch_rot = (x * g, y * g), r


def pad_at(d, ref: str, number: str) -> tuple[float, float]:
    box = next(b for b in d.pad_boxes() if b.ref == ref and b.number == number and b.layer == "F.Cu")
    return (round((box.x1 + box.x2) / 2, 4), round((box.y1 + box.y2) / 2, 4))


def angle_of(p: tuple[float, float]) -> float:
    return math.degrees(math.atan2(Y0 - p[1], p[0] - X0)) % 360.0


def arc(r: float, a0: float, a1: float, step: float = 4.0) -> list[tuple[float, float]]:
    n = max(1, int(abs(a1 - a0) / step))
    return [polar(r, a0 + (a1 - a0) * i / n) for i in range(n + 1)]


def links(d, ref_of) -> None:
    """Each string's links: from an LED's cathode out (warm) or in (cool) to its link circle,
    clockwise round it, and back to the next LED's anode; then each string's ends to the driver's
    pads beside the LED slot; then the 8 signals and the NTC."""
    for colour, r in (("W", R_OUT), ("C", R_IN)):
        seq = list(reversed([k for k, c in enumerate(ORDER) if c == colour]))
        for a, b in zip(seq, seq[1:], strict=False):
            ka, ab = pad_at(d, ref_of[a][0], "1"), pad_at(d, ref_of[b][0], "2")
            ta, tb = angle_of(ka), angle_of(ab)
            if tb > ta:
                tb -= 360.0
            d.track(ref_of[a][2], [ka, *arc(r, ta, tb), ab], "F.Cu", width=W_LINK)
    jf = {net: b for net, b in bulb.joint_pad_boxes(bulb.JOINTS[2])}  # hv-front, -y side: the cathodes
    jb = bulb.joint_pad_boxes(bulb.JOINTS[3])  # hv-back, +y side: the 2 anodes

    def centre(box) -> tuple[float, float]:
        return bulb.disc_xy((box[0] + box[2]) / 2, (box[1] + box[3]) / 2)

    # Warm: through the gap at -x, along the slot's side 1.05 mm off it, into the outer pads.
    wa, wk = ref_of[len(ORDER) - 1][0], ref_of[ORDER.index("W")][0]
    pa, pk = centre(jb[0][1]), centre(jf["LED_KW"])
    d.track("LED_A", [pad_at(d, wa, "2"), polar(R_LED, 172.0), polar(12.4, 173.0), (X0 - 10.4, pa[1]), pa],
            "F.Cu", width=W_LINK)  # fmt: skip
    d.track("LED_KW", [pad_at(d, wk, "1"), polar(R_LED, 188.0), polar(12.4, 187.0), (X0 - 10.4, pk[1]), pk],
            "F.Cu", width=W_LINK)  # fmt: skip
    # The 2 anode pads, joined beside the slot.
    d.track("LED_A", [pa, centre(jb[1][1])], "F.Cu", width=W_LINK)
    # Cool: from the LEDs next to the warm ends, inward to the inner pads.
    ca = pad_at(d, ref_of[len(ORDER) - 2][0], "2")
    d.track("LED_A", [ca, polar(R_IN, angle_of(ca)), centre(jb[1][1])], "F.Cu", width=W_LINK)
    ck = pad_at(d, ref_of[1][0], "1")
    d.track("LED_KC", [ck, polar(R_IN, angle_of(ck)), centre(jf["LED_KC"])], "F.Cu", width=W_LINK)
    signals(d)


def signals(d) -> None:
    """The driver's 8 signals to the brain's front pads, in 2 nests of 4 (bulb.py, JOINTS): each from
    its brain pad along its own height to its lane, then to its level past the driver's pads nearer
    the corner, then across and into its driver pad from outside. Bulb coordinates, mirrored for +y."""
    t = 0.3
    brain = {net: ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for net, b in bulb.joint_pad_boxes(bulb.JOINTS[4])}
    for j, s in ((bulb.JOINTS[0], -1.0), (bulb.JOINTS[1], 1.0)):
        for i, (net, box) in enumerate(bulb.joint_pad_boxes(j)):
            bx, by = brain[net]
            dx = (box[0] + box[2]) / 2
            end = box[1] if s < 0 else box[3]  # the driver pad's outer end
            route = [
                [(bx, by), (3.0, by), (3.0, s * 1.6), (dx, s * 1.6)],  # into the pad's side, under the slot
                [(bx, by), (3.0, by), (3.0, s * 3.3), (dx, s * 3.3), (dx, end)],
                [(bx, by), (dx, by), (dx, end)],
                # the outermost stays 1 mm inside the cool string's links (HV to logic, 0.8 mm)
                [(bx, by), (8.5, by), (8.5, s * 4.6), (dx, s * 4.6), (dx, end)],
            ][i]
            d.track(net, [bulb.disc_xy(x, y) for x, y in route], "F.Cu", width=t)
    # GND goes on from the brain's outermost front pad round the brain slot's -y end to RT1.
    gx, gy = brain["GND"]
    rt = pad_at(d, "RT1", "2")
    d.track("GND", [bulb.disc_xy(gx, gy), bulb.disc_xy(gx, -8.2), bulb.disc_xy(-1.7, -8.2), rt], "F.Cu", width=t)
    # The NTC up to the brain's 2 back pads, which are joined.
    back = [((b[0] + b[2]) / 2, (b[1] + b[3]) / 2) for _, b in bulb.joint_pad_boxes(bulb.JOINTS[5])]
    d.track("NTC", [pad_at(d, "RT1", "1"), bulb.disc_xy(*back[0]), bulb.disc_xy(*back[1])], "F.Cu", width=t)
