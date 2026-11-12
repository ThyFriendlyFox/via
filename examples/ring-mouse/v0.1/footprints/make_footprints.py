"""The ring's own footprints, written into Ring.pretty/.

    python3 footprints/make_footprints.py      # from the version's folder

- Joint_Edge_1x08_P1.3mm: the edge of a tile that solders to its neighbour. 8 plated pads, 1.0 x 1.0
  mm with a 0.4 mm hole, 1.3 mm apart along the edge, numbered from the fingertip's end. Placed 0.8
  mm in from the edge, each pad starts 0.3 mm from it. The 2 tiles meet at their inner corners and
  open a V on the outside; a solder fillet fills the V from pad to pad, and the hole lets it wet
  the pad's other face too.
- TouchStrip_3ch_6x: the scroll strip. 6 stripes across the touch tile, A B C A B C from the
  fingertip's end, under the solder mask. A thumb that slides along the finger crosses them in
  turn: the firmware reads the 3 channels as a 3-phase encoder (firmware/src/strip.c).
"""

from __future__ import annotations

import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
NS = uuid.UUID("9d3a0c5e-2b71-4f0e-8c46-1e5b7a2d4f60")

JOINT_PADS, JOINT_PITCH, JOINT_PAD, JOINT_DRILL = 8, 1.3, 1.0, 0.4
STRIPES, STRIPE_W, STRIPE_H, STRIPE_GAP = 6, 7.4, 1.2, 0.35


def uid(key: str) -> str:
    return str(uuid.uuid5(NS, key))


def fmt(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def text(kind: str, value: str, y: float, layer: str, key: str, hide: bool = True) -> str:
    return (
        f'\t(property "{kind}" "{value}"\n\t\t(at 0 {fmt(y)} 0)\n\t\t(layer "{layer}")\n'
        + ("\t\t(hide yes)\n" if hide else "")
        + f'\t\t(uuid "{uid(key)}")\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 0.6 0.6)\n\t\t\t\t(thickness 0.1)\n\t\t\t)\n\t\t)\n\t)\n'
    )


def rect(layer: str, x0: float, y0: float, x1: float, y1: float, width: float, key: str) -> str:
    return (
        f"\t(fp_rect\n\t\t(start {fmt(x0)} {fmt(y0)})\n\t\t(end {fmt(x1)} {fmt(y1)})\n"
        f"\t\t(stroke\n\t\t\t(width {fmt(width)})\n\t\t\t(type solid)\n\t\t)\n\t\t(fill no)\n"
        f'\t\t(layer "{layer}")\n\t\t(uuid "{uid(key)}")\n\t)\n'
    )


def joint() -> str:
    name = f"Joint_Edge_1x{JOINT_PADS:02d}_P{JOINT_PITCH}mm"
    half = (JOINT_PADS - 1) * JOINT_PITCH / 2
    pads = []
    for k in range(JOINT_PADS):
        y = -half + k * JOINT_PITCH
        pads.append(
            f'\t(pad "{k + 1}" thru_hole rect\n\t\t(at 0 {fmt(y)})\n\t\t(size {fmt(JOINT_PAD)} {fmt(JOINT_PAD)})\n'
            f'\t\t(drill {fmt(JOINT_DRILL)})\n\t\t(layers "*.Cu" "*.Mask")\n\t\t(remove_unused_layers no)\n'
            f'\t\t(uuid "{uid(f"joint/{k}")}")\n\t)'
        )
    c = JOINT_PAD / 2 + 0.15
    return (
        f'(footprint "{name}"\n\t(version 20241229)\n\t(generator "make_footprints")\n\t(layer "F.Cu")\n'
        f'\t(descr "Edge-to-edge solder joint between 2 tiles of a ring: {JOINT_PADS} plated pads {fmt(JOINT_PAD)} mm '
        f'square, {fmt(JOINT_DRILL)} mm hole, {fmt(JOINT_PITCH)} mm apart; place 0.8 mm in from the edge")\n'
        '\t(tags "joint board-to-board edge castellated ring")\n'
        + text("Reference", "J**", -half - 1.2, "F.SilkS", "joint/ref")
        + text("Value", name, half + 1.2, "F.Fab", "joint/value")
        + "\t(attr through_hole)\n"
        + rect("F.CrtYd", -c, -half - c, c, half + c, 0.05, "joint/court")
        + rect("F.Fab", -JOINT_PAD / 2, -half - JOINT_PAD / 2, JOINT_PAD / 2, half + JOINT_PAD / 2, 0.1, "joint/fab")
        + "\n".join(pads)
        + "\n)\n"
    )


def strip() -> str:
    name = f"TouchStrip_3ch_{STRIPES}x"
    pitch = STRIPE_H + STRIPE_GAP
    half = (STRIPES - 1) * pitch / 2
    pads = []
    for k in range(STRIPES):
        y = -half + k * pitch
        pads.append(
            f'\t(pad "{k % 3 + 1}" smd rect\n\t\t(at 0 {fmt(y)})\n\t\t(size {fmt(STRIPE_W)} {fmt(STRIPE_H)})\n'
            f'\t\t(layers "F.Cu")\n\t\t(uuid "{uid(f"strip/{k}")}")\n\t)'
        )
    cx, cy = STRIPE_W / 2 + 0.2, half + STRIPE_H / 2 + 0.2
    return (
        f'(footprint "{name}"\n\t(version 20241229)\n\t(generator "make_footprints")\n\t(layer "F.Cu")\n'
        f'\t(descr "Self-capacitance scroll strip: {STRIPES} stripes {fmt(STRIPE_W)} x {fmt(STRIPE_H)} mm, '
        f'{fmt(STRIPE_GAP)} mm apart, channels A B C repeated, under the solder mask")\n'
        '\t(tags "touch slider capacitive TSC")\n'
        + text("Reference", "E**", -cy - 0.8, "F.SilkS", "strip/ref")
        + text("Value", name, cy + 0.8, "F.Fab", "strip/value")
        + "\t(attr smd exclude_from_bom)\n"
        + rect("F.CrtYd", -cx, -cy, cx, cy, 0.05, "strip/court")
        + "\n".join(pads)
        + "\n)\n"
    )


def main() -> None:
    lib = HERE / "Ring.pretty"
    lib.mkdir(exist_ok=True)
    for name, body in ((f"Joint_Edge_1x{JOINT_PADS:02d}_P{JOINT_PITCH}mm", joint()), (f"TouchStrip_3ch_{STRIPES}x", strip())):
        (lib / f"{name}.kicad_mod").write_text(body, encoding="utf-8")
        print(f"wrote {lib / name}.kicad_mod")


if __name__ == "__main__":
    main()
