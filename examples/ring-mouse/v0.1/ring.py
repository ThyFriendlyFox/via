"""Signet: what every tile of the ring shares, the ring's geometry and its joints.

The ring is 6 flat tiles on the faces of a hexagonal prism round the finger. Each tile is its own
board, a folder beside this file with its own `design.py`; each `design.py` imports this file. Seen
from outside with the fingertip's edge up, every tile joins the next one in `TILES` along its right
edge and the one before along its left edge, the last joining the first: a closed ring of 6
right-angle-free solder joints, each a row of 8 plated pads on both boards with a fillet across the
V between them.

The tiles' inner faces touch a cylinder of radius R_IN (a 19.4 mm finger, US size 9 1/2, in a 0.3 mm
silicone liner), each at its middle. The radio tile is wider than the others: the STM32WB5MMG
module is 7.3 x 11 mm and its supply capacitors stand beside it. The other 5 share the rest of the
circle equally.
"""

from __future__ import annotations

import math
import uuid
from pathlib import Path

import kicadgen

Q = kicadgen.Q
HERE = Path(__file__).resolve().parent

R_IN = 10.0  # the inner faces' cylinder
T = 0.8  # every tile's thickness
H = 12.0  # every tile's height, along the finger
W_RADIO = 15.6
TILES = ["radio", "touch", "clicks", "cell", "power", "motion"]


def _width_of_the_rest() -> float:
    taken = 2 * math.atan(W_RADIO / 2 / R_IN)
    each = (2 * math.pi - taken) / (len(TILES) - 1)
    return round(2 * R_IN * math.tan(each / 2), 2)


WIDTH = {name: (W_RADIO if name == "radio" else _width_of_the_rest()) for name in TILES}
X0, Y0 = 100.0, 100.0  # every tile's top left corner on its own board; y grows toward the hand

# Each joint's 8 pads, top to bottom, as the left tile names its right edge and the right tile its
# left edge. A pad no signal needs is ground: every joint holds 8 fillets.
JOINT_NETS = {
    # Each signal sits level with the module pin it serves (radio/design.py), and passes straight
    # across the tiles between at the same height.
    ("radio", "touch"): ["GND", "LED_A", "BTN_R", "GND", "BTN_L", "TOUCH_C", "TOUCH_B", "TOUCH_A"],
    ("touch", "clicks"): ["GND", "GND", "BTN_R", "GND", "BTN_L", "GND", "GND", "GND"],
    ("clicks", "cell"): ["GND"] * 8,
    ("cell", "power"): ["GND", "VBAT", "VBAT", "GND", "VCHG", "VCHG", "GND", "GND"],
    ("power", "motion"): ["GND", "+3V3", "GND", "VBAT_SENSE", "CHG_STAT", "GND", "GND", "GND"],
    ("motion", "radio"): ["GND", "+3V3", "IMU_INT", "VBAT_SENSE", "CHG_STAT", "I2C_SDA", "I2C_SCL", "GND"],
}
JOINT_PITCH = 1.3
JOINT_FP = "Ring:Joint_Edge_1x08_P1.3mm"
JOINT_INSET = 0.8  # the pads' centres from the edge: 0.3 mm of board, then half a 1.0 mm pad

R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"


def neighbours(name: str) -> tuple[str, str]:
    i = TILES.index(name)
    return TILES[i - 1], TILES[(i + 1) % len(TILES)]


def centre_angle(name: str) -> float:
    """Where a tile's middle sits round the ring, in degrees from the radio tile's, in the direction
    the ring runs (each tile's +x)."""
    a = 0.0
    for prev, cur in zip(TILES, TILES[1:], strict=False):
        a += math.degrees(math.atan(WIDTH[prev] / 2 / R_IN) + math.atan(WIDTH[cur] / 2 / R_IN))
        if cur == name:
            return a
    return 0.0


class TileDesign(kicadgen.Design):
    """A tile: its stackup names the colours KiCad's 3D views read, matte black mask, white legend
    and gold (ENIG) pads."""

    @staticmethod
    def _stackup(copper: list[str], thickness: float = 1.6) -> list:
        out = kicadgen.Design._stackup(copper, thickness)
        colours = {"F.SilkS": "White", "B.SilkS": "White", "F.Mask": "Black", "B.Mask": "Black"}
        for item in out[1:]:
            if isinstance(item, list) and item[0] == "layer" and str(item[1]) in colours:
                item.insert(3, ["color", Q(colours[str(item[1])])])
            if isinstance(item, list) and item[0] == "copper_finish":
                item[1] = Q("ENIG")
        return out


def tile(name: str, namespace: uuid.UUID, copper_layers: int = 2) -> TileDesign:
    """A tile's design with what every tile shares: its outline, rules, footprints, and its 2 joints
    (J1 on its left edge, J2 on its right). The caller adds its parts and calls `finish`."""
    w = WIDTH[name]
    d = TileDesign(
        name=f"signet_{name}",
        namespace=namespace,
        outline=(X0, Y0, X0 + w, Y0 + H),
        corner_radius=0.6,
        thickness=T,
        copper_layers=copper_layers,
        sheet="A3" if copper_layers > 2 else "A4",
        track_width=0.15,
        clearance=0.12,
        via_size=0.45,
        via_drill=0.2,
    )
    d.footprint_dirs = {"Ring": HERE / "footprints" / "Ring.pretty"}
    d.symbol_dirs = {"Ring": HERE / "symbols" / "ring.kicad_sym"}
    d.rules = {"min_through_hole_diameter": 0.2, "min_via_diameter": 0.45, "min_text_height": 0.6,
               "min_text_thickness": 0.1}  # fmt: skip
    left, right = neighbours(name)
    for ref, other, nets, x in (
        ("J1", left, JOINT_NETS[(left, name)], X0 + JOINT_INSET),
        ("J2", right, JOINT_NETS[(name, right)], X0 + w - JOINT_INSET),
    ):
        d.add(ref, "Connector_Generic:Conn_01x08", other.upper(), JOINT_FP, sch_at=(0, 0), pcb_at=(x, Y0 + H / 2),
              pcb_rot=0, pcb_layer="F.Cu", nets={str(k + 1): net for k, net in enumerate(nets)},
              descr=f"Solder joint to the {other} tile")  # fmt: skip
    return d


def at(name: str, dx: float, dy: float) -> tuple[float, float]:
    """A point on a tile given from its middle: dx toward its right edge, dy toward the hand."""
    return (round(X0 + WIDTH[name] / 2 + dx, 4), round(Y0 + H / 2 + dy, 4))


def finish(d: kicadgen.Design, words: list[tuple[str, float, float, str, float]]) -> None:
    """Every tile's last step: its words, no references on the legend, and the schematic in rows."""
    for text, x, y, layer, size in words:
        d.text(text, x, y, layer, size, 0.1 if size < 0.8 else 0.15)
    for part in d.parts:
        part.hide_ref = True
    lay_out_schematic(d)


def lay_out_schematic(d: kicadgen.Design) -> None:
    """The joints at the sheet's left and right, the chips in a row between them, the small parts in
    rows under the chips; every net wired."""
    g = 2.54
    parts = {p.ref: p for p in d.parts}

    def size(p) -> tuple[int, int]:
        xs = [pin.x for pin in p.symbol.pins] or [0]
        ys = [pin.y for pin in p.symbol.pins] or [0]
        return round((max(xs) - min(xs)) / g) + 6, round((max(ys) - min(ys)) / g) + 6

    big = [p for r, p in parts.items() if r not in ("J1", "J2") and not (r[0] in "RCD" or r.startswith(("SW", "TP")))]
    small = [p for r, p in parts.items() if r not in ("J1", "J2") and p not in big]
    x, tall = 30, 20
    for p in big:
        w, h = size(p)
        p.sch_at, p.sch_rot = ((x + w // 2) * g, (12 + h // 2) * g), 0
        x += w + 6
        tall = max(tall, h)
    x = max(x, 30 + 9 * min(len(small), 6))
    for k, p in enumerate(small):
        p.sch_at, p.sch_rot = ((30 + 9 * (k % 6)) * g, (12 + tall + 8 + 10 * (k // 6)) * g), 0
    parts["J1"].sch_at, parts["J1"].sch_rot = (14 * g, (12 + tall // 2) * g), 0
    parts["J2"].sch_at, parts["J2"].sch_rot = ((x + 8) * g, (12 + tall // 2) * g), 180
    d.sch_wires = True
