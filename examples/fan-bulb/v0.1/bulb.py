"""Lark: what the 4 boards share. The housing, each board's place in it, the joints, the fit check.

Lark is an A19 bulb for a ceiling fan's light kit: an E26 base, a neck, a dome. It hangs base-up
and lights the room below. Inside are 4 boards, stacked in 2 directions:

- driver: stands upright in the neck and down into the E26 base, in the bulb's XZ plane. It takes
  the mains and makes the 2 LED currents and the 3.3 V rail.
- light: an aluminium disc that lies flat under the dome, in the XY plane. It carries the LEDs.
- brain: a mast that stands in the dome, in the YZ plane, 90 degrees round from the driver. It
  carries the radio chip and the voice chip.
- ear: a small disc that lies flat under the dome's tip, in the XY plane. It carries the 2
  microphones, where they face the room.

The driver's 2 tongues and the brain's bottom tongue pass through slots in the light disc; the
brain's top tongue passes through the ear's slot. Each tongue has a row of pads on both faces at
its end, the disc has a pad beside each, and a solder fillet joins each pair across the corner:
the way LED bulbs join a driver to its LED board. The light disc's copper carries every signal
between the driver and the brain, so no other connector is needed.

The first try was an A15 (47.6 mm by 87 mm). Each of the driver's 56 parts fit the housing on its
own, but not together: its first layout had 36 courtyard overlaps and 14 through-hole pads in the
courtyards of parts on the other face, with no free area to move them to. SHAPE is now "A19"
(60 mm by 108 mm), and every board grew with it; HOUSINGS keeps both.

The bulb's frame: z along the axis from the base's contact (z = 0) to the dome's tip, x and y
across. Each board's frame is KiCad's, x right and y down, with z up the bulb:

    driver  F.Cu faces -y   x = bx - 100   z = 160 - by
    brain   F.Cu faces +x   y = bx - 100   z = 160 - by
    light   F.Cu faces +z   x = bx - 100   y = 100 - by
    ear     F.Cu faces +z   x = bx - 100   y = 100 - by

Every number of the housing is in HOUSINGS. `fit(d, board)` is called by each design's build() and
stops the design when any part's body, its courtyard and its height on its face, leaves the
housing's inside or reaches another board.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from pathlib import Path

import kicadgen

Q = kicadgen.Q
HERE = Path(__file__).resolve().parent


# ---- the housing --------------------------------------------------------------------------------
@dataclass(frozen=True)
class Housing:
    """The inside of a bulb's housing: the cavities the boards and their parts must stay in."""

    name: str
    dia: float  # the envelope's widest diameter (ANSI C78.20's A15 is 15/8 in)
    length: float  # the base's contact to the dome's tip
    base: tuple[float, float, float]  # the E26 base's cavity: z from, z to, inside radius
    neck: tuple[float, float, float, float]  # the neck's inside, a cone: z0, r0 at the base, z1, r1 at the disc
    disc_t: float  # the light disc's thickness: it lies on the neck's ledge at z1
    dome_c: float  # the dome's inside is a sphere: its centre's z
    dome_r: float  # and its radius


# A15: 47.6 mm by 87 mm, as fan-light A15 lamps are sold. The E26 base's shell is 26.05 mm across
# its thread (ANSI C81.61); its plastic liner leaves a 20.6 mm bore. The neck's wall is 2.0 mm of
# thermally conductive polycarbonate; the dome's is 1.2 mm.
HOUSINGS = {
    "A15": Housing("A15", 47.6, 87.0, (3.5, 24.0, 10.3), (24.0, 11.2, 49.5, 19.0), 1.0, 63.2, 22.6),
    "A19": Housing("A19", 60.0, 108.0, (3.5, 24.0, 10.3), (24.0, 11.2, 60.0, 23.6), 1.0, 78.6, 28.8),
}
SHAPE = "A19"
H = HOUSINGS[SHAPE]
DISC_Z = H.neck[2]  # the light disc's underside
DISC_TOP = DISC_Z + H.disc_t
WALL = 0.3  # each board's edge to the housing's inside: the ribs it slides in
CLEAR = 0.4  # every part's body to the housing's inside


def r_inside(z: float) -> float:
    """The housing's inside radius at height z; 0 where nothing may be (below the base's cavity)."""
    z0, z1, rb = H.base
    nz0, nr0, nz1, nr1 = H.neck
    if z0 <= z <= z1:
        return rb
    if nz0 <= z <= nz1:
        return nr0 + (nr1 - nr0) * (z - nz0) / (nz1 - nz0)
    if nz1 < z < DISC_TOP:
        return nr1
    if z >= DISC_TOP:
        dz = z - H.dome_c
        return math.sqrt(max(0.0, H.dome_r**2 - dz * dz))
    return 0.0


# ---- the boards ---------------------------------------------------------------------------------
X0, Y0 = 100.0, 100.0
DRV_T = 1.6  # the driver: FR-4, 4 layers
BRN_T = 1.0  # the brain: FR-4, 4 layers
EAR_T = 0.8  # the ear: FR-4, 2 layers
DRV_Z0 = 5.0  # the driver's bottom edge, over the base's eyelet
DRV_ZTOP = DISC_Z - 1.0  # the driver's top edge: 1 mm of air under the disc
TONGUE_TOP = DISC_TOP + 1.8  # each tongue stands 1.8 mm through the disc
EDGE_PAD = 0.3  # copper to any board edge or slot, the generator's edge clearance
PAD_Z = (DISC_TOP + 0.1, TONGUE_TOP - EDGE_PAD - 0.05)  # tongue pads over the disc's top face
BRN_W = 16.0  # the brain mast's width
BRN_TONGUE = 14.0  # its bottom tongue's width: the shoulders either side rest on the disc
BRN_Z0 = DISC_Z - 0.5  # the bottom tongue ends 0.5 mm under the disc
EAR_TOP = round(H.dome_c + H.dome_r - 2.4, 2)  # the ear's top face, 2.4 mm under the dome's tip: a gasket ring fills it
EAR_Z = EAR_TOP - EAR_T  # its underside, where the brain's shoulders stop
EAR_R = 7.5
EAR_TONGUE = 6.0  # the brain's top tongue, flush with the ear's top face
EAR_PAD_Z = (EAR_Z - 1.45, EAR_Z - 0.1)  # tongue pads under the ear
DISC_R = H.neck[3] - 1.0
SLOT_GAP = 0.15  # a slot is this much wider than its tongue on each side
SLOT_R = 0.4  # a slot's milled corners


def half_width(z: float) -> float:
    """The driver's half-width at height z: the housing's inside less the rib's clearance."""
    return r_inside(z) - WALL


def drv_xy(x: float, z: float) -> tuple[float, float]:
    """The driver board's point for bulb x and z."""
    return (round(X0 + x, 4), round(160.0 - z, 4))


def brn_xy(y: float, z: float) -> tuple[float, float]:
    return (round(X0 + y, 4), round(160.0 - z, 4))


def disc_xy(x: float, y: float) -> tuple[float, float]:
    """The light disc's or the ear's point for bulb x and y: both have F.Cu up, toward the tip."""
    return (round(X0 + x, 4), round(Y0 - y, 4))


# The driver's 2 tongues, as bulb x: the low-voltage signals at +x, the LED strings at -x.
LV_TONGUE = (3.8, 10.6)
HV_TONGUE = (-10.0, -4.2)


def driver_corners() -> list[tuple[float, float, float]]:
    """The driver's outline as (x, y, radius), clockwise on its own sheet. The neck's cone and the
    base's bore meet at a concave corner on each side."""
    zb = H.neck[0]
    wt, wn, wb = half_width(DRV_ZTOP), half_width(zb), half_width(DRV_Z0)
    hv0, hv1 = HV_TONGUE
    lv0, lv1 = LV_TONGUE
    pts = [
        (-wt, DRV_ZTOP, 1.0),
        (hv0, DRV_ZTOP, 0.3),
        (hv0, TONGUE_TOP, 0.3),
        (hv1, TONGUE_TOP, 0.3),
        (hv1, DRV_ZTOP, 0.3),
        (lv0, DRV_ZTOP, 0.3),
        (lv0, TONGUE_TOP, 0.3),
        (lv1, TONGUE_TOP, 0.3),
        (lv1, DRV_ZTOP, 0.3),
        (wt, DRV_ZTOP, 1.0),
        (wn, zb, 4.0),
        (wb, DRV_Z0, 2.0),
        (-wb, DRV_Z0, 2.0),
        (-wn, zb, 4.0),
    ]
    return [(*drv_xy(x, z), r) for x, z, r in pts]


def brain_corners() -> list[tuple[float, float, float]]:
    """The mast: its body stands on the disc between its 2 shoulders and stops under the ear; a
    tongue at each end passes through the disc and through the ear."""
    w, t, e = BRN_W / 2, BRN_TONGUE / 2, EAR_TONGUE / 2
    pts = [
        (-w, EAR_Z, 1.0),
        (-e, EAR_Z, 0.2),
        (-e, EAR_TOP, 0.3),
        (e, EAR_TOP, 0.3),
        (e, EAR_Z, 0.2),
        (w, EAR_Z, 1.0),
        (w, DISC_TOP, 0.3),
        (t, DISC_TOP, 0.2),
        (t, BRN_Z0, 0.4),
        (-t, BRN_Z0, 0.4),
        (-t, DISC_TOP, 0.2),
        (-w, DISC_TOP, 0.3),
    ]
    return [(*brn_xy(y, z), r) for y, z, r in pts]


def disc_slots() -> list[tuple[float, float, float, float]]:
    """The light disc's 3 slots as bulb boxes (x0, y0, x1, y1): a tongue and SLOT_GAP each side."""
    g, dt, bt = SLOT_GAP, DRV_T / 2, BRN_T / 2
    return [
        (HV_TONGUE[0] - g, -dt - g, HV_TONGUE[1] + g, dt + g),
        (LV_TONGUE[0] - g, -dt - g, LV_TONGUE[1] + g, dt + g),
        (-bt - g, -BRN_TONGUE / 2 - g, bt + g, BRN_TONGUE / 2 + g),
    ]


def ear_slots() -> list[tuple[float, float, float, float]]:
    g, bt = SLOT_GAP, BRN_T / 2
    return [(-bt - g, -EAR_TONGUE / 2 - g, bt + g, EAR_TONGUE / 2 + g)]


# ---- the joints ---------------------------------------------------------------------------------
#
# Each pad on a tongue faces a pad beside the slot it passes through: on the light disc's top face,
# or on the ear's underside for the brain's top tongue. A joint names its pads along the tongue in
# bulb coordinates and the net of each. A tongue pad is TP_W wide along the tongue; its slot pad is
# as wide and TP_D deep, from EDGE_PAD outside the slot's edge.
TP_W, TP_D = 1.1, 1.5
HV_W = 2.0  # the LED pads: wider, 1.0 mm apart


@dataclass(frozen=True)
class Joint:
    name: str
    board: str  # the tongue's board
    slot: str  # the board whose slot it passes: "light" or "ear"
    face: str  # the tongue's face, as the bulb sees it: "-y", "+y", "+x", "-x"
    along: tuple[float, ...]  # each pad's centre along the tongue, bulb x for the driver, y for the brain
    nets: tuple[str, ...]
    width: float = TP_W

    @property
    def pad_z(self) -> tuple[float, float]:
        return PAD_Z if self.slot == "light" else EAR_PAD_Z


JOINTS = [
    # The driver's low-voltage tongue at +x: F.Cu faces -y, B.Cu +y. Each side's 4 nets nest on the
    # disc round the corner they share with the brain's slot, GND outermost: it goes on round the
    # brain slot's end to the disc's temperature sensor.
    Joint("lv-front", "driver", "light", "-y", (4.7, 6.3, 7.9, 9.5), ("DIM_C", "DIM_W", "+3V3", "GND")),
    Joint("lv-back", "driver", "light", "+y", (4.7, 6.3, 7.9, 9.5), ("LED_EN", "HALL_A", "HALL_B", "VBUS_SENSE")),
    # The LED tongue at -x. Both strings run clockwise round the ring (seen from the dome), so both
    # anodes come back on the slot's +y side and both cathodes on its -y side; the warm string's
    # ends cross the ring through the gap at -x and take the outer pads.
    Joint("hv-front", "driver", "light", "-y", (-8.6, -5.6), ("LED_KW", "LED_KC"), HV_W),
    Joint("hv-back", "driver", "light", "+y", (-8.6, -5.6), ("LED_A", "LED_A"), HV_W),
    # The brain's bottom tongue: its +x face takes the driver's 8 signals in the same nesting; its
    # -x face takes the disc's temperature sensor on 2 pads, for a joint as strong on that face.
    Joint(
        "brain-front",
        "brain",
        "light",
        "+x",
        tuple(round(-5.6 + 1.6 * k, 2) for k in range(8)),
        ("GND", "+3V3", "DIM_W", "DIM_C", "LED_EN", "HALL_A", "HALL_B", "VBUS_SENSE"),
    ),
    Joint("brain-back", "brain", "light", "-x", (-0.8, 0.8), ("NTC", "NTC")),
    # The brain's top tongue through the ear: the microphones' supply and their PDM pair.
    Joint("ear-front", "brain", "ear", "+x", (-1.0, 1.0), ("+3V3", "PDM_CLK")),
    Joint("ear-back", "brain", "ear", "-x", (-1.0, 1.0), ("GND", "PDM_DATA")),
]


def joint_pad_boxes(j: Joint) -> list[tuple[str, tuple[float, float, float, float]]]:
    """The slot board's pad for each pad of joint j, as (net, bulb box x0, y0, x1, y1)."""
    out = []
    for at, net in zip(j.along, j.nets, strict=True):
        a0, a1 = at - j.width / 2, at + j.width / 2
        if j.board == "driver":
            e = DRV_T / 2 + SLOT_GAP + EDGE_PAD
            y0, y1 = (-e - TP_D, -e) if j.face == "-y" else (e, e + TP_D)
            out.append((net, (a0, y0, a1, y1)))
        else:
            e = BRN_T / 2 + SLOT_GAP + EDGE_PAD
            x0, x1 = (e, e + TP_D) if j.face == "+x" else (-e - TP_D, -e)
            out.append((net, (x0, a0, x1, a1)))
    return out


def tongue_at(j: Joint) -> tuple[float, float]:
    """Where a tongue's footprint goes on its board: the axis, at its pads' middle height."""
    zc = round((j.pad_z[0] + j.pad_z[1]) / 2, 4)
    return drv_xy(0.0, zc) if j.board == "driver" else brn_xy(0.0, zc)


def tongue_layer(j: Joint) -> str:
    """A tongue's pads face: the driver's F.Cu faces -y, the brain's +x."""
    return "F.Cu" if j.face in ("-y", "+x") else "B.Cu"


def _check_joints() -> None:
    """Each tongue lies inside its slot with SLOT_GAP to spare, each pad on its tongue, and no 2
    disc pads closer than 0.4 mm (1.0 mm where either is an LED pad)."""
    for j in JOINTS:
        lo, hi = min(j.along) - j.width / 2, max(j.along) + j.width / 2
        if j.board == "driver":
            span = LV_TONGUE if min(j.along) > 0 else HV_TONGUE
        else:
            w = BRN_TONGUE if j.slot == "light" else EAR_TONGUE
            span = (-w / 2, w / 2)
        if lo < span[0] + EDGE_PAD or hi > span[1] - EDGE_PAD:
            raise SystemExit(f"bulb.py: joint {j.name}'s pads ({lo:.2f} to {hi:.2f}) leave its tongue {span}")
    boxes = [(j, net, b) for j in JOINTS for net, b in joint_pad_boxes(j)]
    for i, (ja, na, a) in enumerate(boxes):
        slots, rim = (disc_slots(), DISC_R) if ja.slot == "light" else (ear_slots(), EAR_R)
        for jb, nb, b in boxes[i + 1 :]:
            if jb.slot != ja.slot:
                continue
            gap = max(b[0] - a[2], a[0] - b[2], b[1] - a[3], a[1] - b[3])
            need = 1.0 if (ja.width == HV_W or jb.width == HV_W) else 0.4
            if gap < need and na != nb:
                raise SystemExit(f"bulb.py: disc pads {na} ({ja.name}) and {nb} ({jb.name}) stand {gap:.2f} mm apart")
        for s in slots:
            if max(s[0] - a[2], a[0] - s[2], s[1] - a[3], a[1] - s[3]) < -1e-6:
                raise SystemExit(f"bulb.py: disc pad {na} ({ja.name}) lies over a slot")
        if math.hypot(max(abs(a[0]), abs(a[2])), max(abs(a[1]), abs(a[3]))) > rim - 1.0:
            raise SystemExit(f"bulb.py: pad {na} ({ja.name}) is within 1 mm of its board's edge")


_check_joints()


# ---- what each part takes up --------------------------------------------------------------------
#
# A part's height over its face, from its datasheet's package drawing (the README's parts table
# names each). The fit check takes the courtyard's box and this height; BODY gives a part whose
# body is not its courtyard (a module whose antenna hangs past the board) its own box.
HEIGHT = {
    "R_0402_1005Metric": 0.4,
    "C_0402_1005Metric": 0.55,
    "R_0603_1608Metric": 0.55,
    "C_0603_1608Metric": 0.9,
    "C_0805_2012Metric": 1.35,
    "C_1210_3225Metric": 2.5,
    "C_1812_4532Metric": 2.0,
    "R_1206_3216Metric": 0.65,
    "R_2512_6332Metric": 0.65,
    "SOIC-8_3.9x4.9mm_P1.27mm": 1.75,
    "PowerIntegrations_SO-8C": 1.75,
    "SOT-23": 1.12,
    "SOT-23-5": 1.45,
    "SOT-223-3_TabPin2": 1.8,
    "D_SMA": 2.44,
    "D_SOD-123F": 1.1,
    "Diode_Bridge_Diotec_ABS": 1.55,
    "TO-269AA": 2.7,
    "QFN-56-1EP_7x7mm_P0.4mm_EP4x4mm": 0.9,
    "Winbond_USON-8-1EP_3x2mm_P0.5mm_EP0.2x1.6mm": 0.6,
    "WSON-8-1EP_6x5mm_P1.27mm_EP3.4x4.3mm": 0.8,
    "Crystal_SMD_2016-4Pin_2.0x1.6mm": 0.55,
    "InvenSense_ICS-43434-6_3.5x2.65mm": 0.98,
    "Knowles_LGA-5_3.5x2.65mm": 0.98,
    "LED_PLCC_2835": 0.8,
    "ESP32-C6-MINI-1": 2.55,
    "TestPoint_Pad_D1.0mm": 0.05,
    "TestPoint_THTPad_D2.0mm_Drill1.0mm": 1.0,  # the lead's solder joint
    "R_MELF_MMB-0207": 2.2,
    "RV_SMD_TDK_CU3225": 3.2,  # EPCOS SIOV CU catalog: 8.0 x 6.3 x 3.2 mm
    "CP_Radial_D8.0mm_L11.5mm_P3.50mm_Lying": 8.0,  # Nichicon ULD: phi 8 laid on its side
    "L_Bourns_SDR0604": 4.8,  # Bourns SDR0604: 5.8 mm phi, 4.8 mm max
    "L_Radial_D9.5mm_P5.00mm_Fastron_07HVP": 12.0,  # Fastron 07HVP: phi 9.5; its height not read (README)
    "C_1206_3216Metric": 1.8,
}
# Round bodies standing on the board: the footprint-frame centre and radius. fit() checks points
# round the circle, each at its own height, where a box's corner would stand lower in the cone.
ROUND = {
    "L_Radial_D9.5mm_P5.00mm_Fastron_07HVP": (2.5, 0.0, 4.75),
}
# Footprint-frame boxes (x0, y0, x1, y1) of bodies their courtyard does not describe.
BODY = {
    "ESP32-C6-MINI-1": (-6.75, -11.15, 6.75, 5.75),  # the module; the antenna's keep-out is air past the mast
}


def _height(d: kicadgen.Design, part) -> float:
    name = part.footprint.name
    if part.ref in getattr(d, "heights", {}):
        return d.heights[part.ref]
    if name in HEIGHT:
        return HEIGHT[name]
    if name.startswith(("Tongue_", "SlotPads_", "WirePad_")):
        return 0.05
    raise SystemExit(f"bulb.py: no height for {part.ref} ({name}): add it to HEIGHT or d.heights")


def _body_box(d: kicadgen.Design, part) -> tuple[float, float, float, float]:
    name = part.footprint.name
    if name not in BODY:
        box = d.courtyard_box(part)
        if box is None:
            raise SystemExit(f"bulb.py: {part.ref} has no courtyard")
        return box
    x0, y0, x1, y1 = BODY[name]
    a = math.radians(-part.pcb_rot) if part.pcb_layer == "F.Cu" else math.radians(part.pcb_rot)
    sx = 1.0 if part.pcb_layer == "F.Cu" else -1.0
    pts = []
    for fx, fy in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
        fx *= sx
        pts.append((part.pcb_at[0] + fx * math.cos(a) - fy * math.sin(a), part.pcb_at[1] + fx * math.sin(a) + fy * math.cos(a)))
    return (min(p[0] for p in pts), min(p[1] for p in pts), max(p[0] for p in pts), max(p[1] for p in pts))


def _corners(board: str, part, box, h: float) -> list[tuple[float, float, float]]:
    """A part's box as 8 bulb points (x, y, z): its footprint box and its height off its face."""
    bx0, by0, bx1, by1 = box
    front = part.pcb_layer == "F.Cu"
    out = []
    if board == "driver":
        t = DRV_T / 2
        n0, n1 = (-t - h, -t) if front else (t, t + h)  # F.Cu faces -y
        for bx in (bx0, bx1):
            for by in (by0, by1):
                for n in (n0, n1):
                    out.append((bx - X0, n, 160.0 - by))
    elif board == "brain":
        t = BRN_T / 2
        n0, n1 = (t, t + h) if front else (-t - h, -t)  # F.Cu faces +x
        for bx in (bx0, bx1):
            for by in (by0, by1):
                for n in (n0, n1):
                    out.append((n, bx - X0, 160.0 - by))
    else:
        lo, hi = (DISC_Z, DISC_TOP) if board == "light" else (EAR_Z, EAR_TOP)
        z0, z1 = (hi, hi + h) if front else (lo - h, lo)
        for bx in (bx0, bx1):
            for by in (by0, by1):
                for z in (z0, z1):
                    out.append((bx - X0, Y0 - by, z))
    return out


def _round_points(board: str, part, h: float) -> list[tuple[float, float, float]]:
    """A round body's outline as 24 points on each of its 2 faces, in bulb coordinates."""
    cx, cy, rad = ROUND[part.footprint.name]
    th = math.radians(part.pcb_rot)
    fy_sign = -1.0 if part.pcb_layer == "B.Cu" else 1.0
    out = []
    for k in range(24):
        a = 2 * math.pi * k / 24
        fx, fy = cx + rad * math.cos(a), fy_sign * (cy + rad * math.sin(a))
        bx = part.pcb_at[0] + fx * math.cos(th) + fy * math.sin(th)
        by = part.pcb_at[1] - fx * math.sin(th) + fy * math.cos(th)
        out += _corners(board, part, (bx, by, bx, by), h)
    return out


def fit(d: kicadgen.Design, board: str) -> None:
    """Stop the design when a part leaves the housing or reaches another board's space.

    The driver's parts stay under the disc and clear of the brain's tongue; the brain's stay
    between the disc's top face and the ear's joint; every part stays CLEAR inside the housing at
    each height it spans. The tongues' pads have no body and are left out.
    """
    bad = []
    for part in d.parts:
        h = _height(d, part)
        if h <= 0.05:
            continue
        pts = _corners(board, part, _body_box(d, part), h)
        if part.footprint.name in ROUND:
            pts = _round_points(board, part, h)
        zs = [p[2] for p in pts]
        z0, z1 = min(zs), max(zs)
        if part.footprint.name in ROUND:  # each point against the housing at its own height
            over = max(math.hypot(p[0], p[1]) - (r_inside(p[2]) - CLEAR) for p in pts)
            rad, worst = 0.0, math.inf
            if over > 0:
                bad.append(f"{part.ref} stands {over:.2f} mm past the housing's inside less {CLEAR} mm at z {z0:.1f}-{z1:.1f}")
        else:
            rad = max(math.hypot(p[0], p[1]) for p in pts)
            worst = min(r_inside(z0 + (z1 - z0) * k / 8) for k in range(9))
        if board == "driver" and z1 > BRN_Z0 - 0.2:
            bad.append(f"{part.ref} reaches z {z1:.2f}, above the driver's space (to {BRN_Z0 - 0.2:.2f})")
        if board == "brain" and z0 < DISC_TOP + 0.2:
            bad.append(f"{part.ref} reaches down to z {z0:.2f}, into the disc (from {DISC_TOP + 0.2:.2f})")
        if board == "brain" and z1 > EAR_PAD_Z[0] - 0.2:
            bad.append(f"{part.ref} reaches up to z {z1:.2f}, into the ear's joint (to {EAR_PAD_Z[0] - 0.2:.2f})")
        if rad > worst - CLEAR:
            bad.append(f"{part.ref} stands {rad:.2f} mm from the axis at z {z0:.1f}-{z1:.1f}; the housing allows {worst - CLEAR:.2f}")
    if bad:
        raise SystemExit("bulb.py: parts outside the " + SHAPE + " housing:\n  " + "\n  ".join(bad))


# ---- a board whose edge is a filleted polygon, with holes ---------------------------------------
def _fillets(corners, inset: float):
    """For each corner: its centre, its radius at `inset`, and where the arc meets the edge in and
    out (the outline method of Rosetta v0.2's design.py). A concave corner turns the other way."""
    n = len(corners)
    out = []
    for i in range(n):
        (px, py, _), (x, y, r), (nx, ny, _) = corners[i - 1], corners[i], corners[(i + 1) % n]
        din = ((x - px), (y - py))
        dout = ((nx - x), (ny - y))
        lin, lout = math.hypot(*din), math.hypot(*dout)
        din, dout = (din[0] / lin, din[1] / lin), (dout[0] / lout, dout[1] / lout)
        nin, nout = (-din[1], din[0]), (-dout[1], dout[0])
        convex = din[0] * dout[1] - din[1] * dout[0] > 0
        s = r if convex else -r
        a = (x + s * nin[0], y + s * nin[1])
        b = (x + s * nout[0], y + s * nout[1])
        det = din[0] * (-dout[1]) - din[1] * (-dout[0])
        t = ((b[0] - a[0]) * (-dout[1]) - (b[1] - a[1]) * (-dout[0])) / det
        c = (a[0] + t * din[0], a[1] + t * din[1])
        rr = r - inset if convex else r + inset
        sign = 1.0 if convex else -1.0
        tin = (c[0] - sign * rr * nin[0], c[1] - sign * rr * nin[1])
        tout = (c[0] - sign * rr * nout[0], c[1] - sign * rr * nout[1])
        out.append((c, rr, tin, tout))
    return out


def _arc(c, r, a, b, n):
    a0 = math.atan2(a[1] - c[1], a[0] - c[0])
    a1 = math.atan2(b[1] - c[1], b[0] - c[0])
    sweep = (a1 - a0 + math.pi) % (2 * math.pi) - math.pi
    return [(c[0] + r * math.cos(a0 + sweep * k / n), c[1] + r * math.sin(a0 + sweep * k / n)) for k in range(n + 1)]


def _inside(poly, x, y) -> bool:
    inside = False
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            inside = not inside
    return inside


def _dist(poly, x, y) -> float:
    best = math.inf
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1], strict=True):
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy or 1e-12
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
    return best


def _poly(corners, inset: float, n: int) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for c, r, tin, tout in _fillets(corners, inset):
        for p in _arc(c, r, tin, tout, max(n, 4)):
            p = (round(p[0], 4), round(p[1], 4))
            if not pts or math.hypot(p[0] - pts[-1][0], p[1] - pts[-1][1]) > 1e-6:
                pts.append(p)
    return pts


class BulbDesign(kicadgen.Design):
    """A board of the bulb: its edge a filleted polygon (`corners`), or a circle (`circle`), less
    filleted holes (`holes`); its stackup in the bulb's colours (`colours`)."""

    corners: list = []
    circle: tuple[float, float, float] | None = None
    holes: list = []
    colours: dict = {}
    core: str = ""
    heights: dict = {}

    def outline_polygon(self, inset: float = 0.0, n: int = 8) -> list[tuple[float, float]]:
        if self.circle:
            cx, cy, r = self.circle
            return [(round(cx + (r - inset) * math.cos(2 * math.pi * k / 144), 4),
                     round(cy + (r - inset) * math.sin(2 * math.pi * k / 144), 4)) for k in range(144)]  # fmt: skip
        return _poly(self.corners, inset, n)

    def inside_outline(self, x: float, y: float, margin: float = 0.0) -> bool:
        if not _inside(self.outline_polygon(margin, 16), x, y):
            return False
        for h in self.holes:
            hp = _poly(h, 0.0, 6)
            if _inside(hp, x, y) or _dist(hp, x, y) < margin:
                return False
        return True

    def hole_polygons(self) -> list[list[tuple[float, float]]]:
        return [_poly(h, 0.0, 6) for h in self.holes]

    def _stackup(self, copper, thickness=1.6) -> list:  # noqa: D102 - the generator calls it on the instance
        out = kicadgen.Design._stackup(copper, thickness)
        for item in out[1:]:
            if isinstance(item, list) and item[0] == "layer" and str(item[1]) in self.colours:
                item.insert(3, ["color", Q(self.colours[str(item[1])])])
            if isinstance(item, list) and item[0] == "layer" and str(item[1]).startswith("dielectric") and self.core:
                for field in item[2:]:
                    if field[0] == "material":
                        field[1] = Q(self.core)
            if isinstance(item, list) and item[0] == "copper_finish":
                item[1] = Q("ENIG")
        return out

    def _edge_cuts(self, ns: uuid.UUID) -> list:
        fmt, uid = kicadgen.fmt, kicadgen.uid
        stroke = ["stroke", ["width", "0.1"], ["type", "default"]]
        items: list = []
        if self.circle:
            cx, cy, r = self.circle
            items.append(["gr_circle", ["center", fmt(cx), fmt(cy)], ["end", fmt(cx + r), fmt(cy)], stroke,
                          ["fill", "no"], ["layer", Q("Edge.Cuts")], ["uuid", uid(ns, "edge/outer")]])  # fmt: skip
            shapes = [("hole%d" % k, h) for k, h in enumerate(self.holes)]
        else:
            shapes = [("edge", self.corners)] + [("hole%d" % k, h) for k, h in enumerate(self.holes)]
        for key, corners in shapes:
            fil = _fillets(corners, 0.0)
            for i, (c, r, tin, tout) in enumerate(fil):
                mid = _arc(c, r, tin, tout, 2)[1]
                items.append(["gr_arc", ["start", fmt(tin[0]), fmt(tin[1])], ["mid", fmt(mid[0]), fmt(mid[1])],
                              ["end", fmt(tout[0]), fmt(tout[1])], stroke, ["layer", Q("Edge.Cuts")],
                              ["uuid", uid(ns, f"{key}/arc/{i}")]])  # fmt: skip
                nxt = fil[(i + 1) % len(fil)][2]
                if math.hypot(nxt[0] - tout[0], nxt[1] - tout[1]) > 1e-4:
                    items.append(["gr_line", ["start", fmt(tout[0]), fmt(tout[1])], ["end", fmt(nxt[0]), fmt(nxt[1])],
                                  stroke, ["layer", Q("Edge.Cuts")], ["uuid", uid(ns, f"{key}/line/{i}")]])  # fmt: skip
        return items


def box_corners(x0: float, y0: float, x1: float, y1: float, r: float) -> list[tuple[float, float, float]]:
    """A rounded rectangle as polygon corners, clockwise on a KiCad sheet (y down)."""
    return [(x0, y0, r), (x1, y0, r), (x1, y1, r), (x0, y1, r)]


def slot_holes() -> list[list[tuple[float, float, float]]]:
    """The disc's slots as hole corners in the disc's frame."""
    out = []
    for x0, y0, x1, y1 in disc_slots():
        a, b = disc_xy(x0, y1), disc_xy(x1, y0)
        out.append(box_corners(a[0], a[1], b[0], b[1], SLOT_R))
    return out


FOOTPRINTS = HERE / "footprints" / "Lark.pretty"
SYMBOLS = HERE / "symbols" / "lark.kicad_sym"
