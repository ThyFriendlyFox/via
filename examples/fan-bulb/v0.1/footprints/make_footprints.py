"""Lark's own footprints, written into Lark.pretty/ from the joints in bulb.py.

    python3 footprints/make_footprints.py      # from the version's folder

For each joint of bulb.JOINTS:

- Tongue_<joint>: the pads on a tongue's face, TP_W (or HV_W) along the tongue and PAD_Z high,
  above the disc's top face. The origin is the bulb's axis at the pads' middle height, so the
  design places it at bulb.tongue_at(), on bulb.tongue_layer().
- SlotPads_<joint>: the pads beside the slot that tongue passes through, TP_D deep from EDGE_PAD
  outside the slot's edge: on the light disc's top face, or on the ear's underside. The origin is
  the board's centre.

A solder fillet joins each tongue pad to its disc pad across the corner they make.

And 2 parts KiCad's library draws only another way: CP_Radial_D8.0mm_L11.5mm_P3.50mm_Lying, the
driver's bulk capacitors laid along the board, and RV_SMD_TDK_CU3225, its SMD varistor.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import bulb  # noqa: E402

NS = uuid.UUID("5b1f0d3e-7a9c-4e21-b8d4-0c6f2e9a1b73")


def uid(key: str) -> str:
    return str(uuid.uuid5(NS, key))


def fmt(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def text(kind: str, value: str, y: float, layer: str, key: str) -> str:
    return (
        f'\t(property "{kind}" "{value}"\n\t\t(at 0 {fmt(y)} 0)\n\t\t(layer "{layer}")\n\t\t(hide yes)\n'
        f'\t\t(uuid "{uid(key)}")\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 0.6 0.6)\n\t\t\t\t(thickness 0.1)\n\t\t\t)\n\t\t)\n\t)\n'
    )


def rect(layer: str, x0: float, y0: float, x1: float, y1: float, key: str) -> str:
    return (
        f"\t(fp_rect\n\t\t(start {fmt(x0)} {fmt(y0)})\n\t\t(end {fmt(x1)} {fmt(y1)})\n"
        f"\t\t(stroke\n\t\t\t(width 0.05)\n\t\t\t(type solid)\n\t\t)\n\t\t(fill no)\n"
        f'\t\t(layer "{layer}")\n\t\t(uuid "{uid(key)}")\n\t)\n'
    )


def footprint(name: str, descr: str, pads: list[tuple[float, float, float, float]]) -> str:
    """SMD pads given as boxes (x0, y0, x1, y1) in the footprint's frame, numbered in order."""
    body = []
    for k, (x0, y0, x1, y1) in enumerate(pads):
        cx, cy, w, h = (x0 + x1) / 2, (y0 + y1) / 2, x1 - x0, y1 - y0
        body.append(
            f'\t(pad "{k + 1}" smd rect\n\t\t(at {fmt(cx)} {fmt(cy)})\n\t\t(size {fmt(w)} {fmt(h)})\n'
            f'\t\t(layers "F.Cu" "F.Mask")\n\t\t(uuid "{uid(f"{name}/pad/{k}")}")\n\t)'
        )
    xs = [p[0] for p in pads] + [p[2] for p in pads]
    ys = [p[1] for p in pads] + [p[3] for p in pads]
    c = 0.15
    return (
        f'(footprint "{name}"\n\t(version 20241229)\n\t(generator "make_footprints")\n\t(layer "F.Cu")\n'
        f'\t(descr "{descr}")\n\t(tags "joint tongue slot bulb")\n'
        + text("Reference", "J**", min(ys) - 1.0, "F.SilkS", f"{name}/ref")
        + text("Value", name, max(ys) + 1.0, "F.Fab", f"{name}/value")
        + "\t(attr smd exclude_from_pos_files exclude_from_bom)\n"
        + rect("F.CrtYd", min(xs) - c, min(ys) - c, max(xs) + c, max(ys) + c, f"{name}/court")
        + "\n".join(body)
        + "\n)\n"
    )


def tongue(j: bulb.Joint) -> tuple[str, str]:
    """The tongue's pads: x along the tongue, y down the board. A part on a back face is mirrored
    in y (kicadgen, as KiCad flips it), so the same pads serve either face."""
    zc = (j.pad_z[0] + j.pad_z[1]) / 2
    h = j.pad_z[1] - j.pad_z[0]
    pads = []
    for at in j.along:
        pads.append((at - j.width / 2, -h / 2, at + j.width / 2, h / 2))
    name = f"Tongue_{j.name}"
    descr = (
        f"Lark joint {j.name}: {len(j.along)} pads on the {j.board}'s tongue, {fmt(j.width)} x {fmt(h)} mm, "
        f"their middle at z {fmt(zc)} mm; place at the bulb's axis"
    )
    return name, footprint(name, descr, pads)


def slot(j: bulb.Joint) -> tuple[str, str]:
    """The slot board's pads from its centre, x bulb x. On the light disc's top face y is minus bulb
    y; on the ear's underside the footprint goes on B.Cu, which kicadgen mirrors in y, so y is bulb y."""
    pads = []
    for _, (x0, y0, x1, y1) in bulb.joint_pad_boxes(j):
        pads.append((x0, -y1, x1, -y0) if j.slot == "light" else (x0, y0, x1, y1))
    name = f"SlotPads_{j.name}"
    descr = f"Lark joint {j.name}: {len(pads)} pads beside the slot of the {j.board}'s tongue; place at the disc's centre"
    return name, footprint(name, descr, pads)


def tht_pad(num: str, x: float, y: float, size: float, drill: float, key: str, shape: str = "circle") -> str:
    return (
        f'\t(pad "{num}" thru_hole {shape}\n\t\t(at {fmt(x)} {fmt(y)})\n\t\t(size {fmt(size)} {fmt(size)})\n'
        f'\t\t(drill {fmt(drill)})\n\t\t(layers "*.Cu" "*.Mask")\n\t\t(remove_unused_layers no)\n\t\t(uuid "{uid(key)}")\n\t)'
    )


def smd_pad(num: str, x: float, y: float, w: float, h: float, key: str) -> str:
    return (
        f'\t(pad "{num}" smd rect\n\t\t(at {fmt(x)} {fmt(y)})\n\t\t(size {fmt(w)} {fmt(h)})\n'
        f'\t\t(layers "F.Cu" "F.Mask" "F.Paste")\n\t\t(uuid "{uid(key)}")\n\t)'
    )


def lying_cap(d: float, length: float, pitch: float) -> tuple[str, str]:
    """A radial electrolytic laid on the board: its 2 leads bent 90 degrees into holes `pitch` apart
    on the x axis, the can lying along +y from 1.0 mm past them. The leads are 0.6 mm (Nichicon ULD,
    phi-d for phi-D 8): 0.9 mm holes. Pad 1 is +."""
    name = f"CP_Radial_D{d:.1f}mm_L{length}mm_P{pitch:.2f}mm_Lying"
    y0, y1 = 1.0, 1.0 + length + 0.5  # the sleeve stands 0.5 mm past the can's end
    body = [
        tht_pad("1", -pitch / 2, 0.0, 1.6, 0.9, f"{name}/1", "rect"),
        tht_pad("2", pitch / 2, 0.0, 1.6, 0.9, f"{name}/2"),
    ]
    return name, (
        f'(footprint "{name}"\n\t(version 20241229)\n\t(generator "make_footprints")\n\t(layer "F.Cu")\n'
        f'\t(descr "Radial electrolytic {fmt(d)} x {fmt(length)} mm laid on the board, leads bent into {fmt(pitch)} mm '
        f'holes, the can along +y; Lark\'s bulk capacitors in the bulb\'s neck")\n\t(tags "capacitor electrolytic lying")\n'
        + text("Reference", "C**", -2.0, "F.SilkS", f"{name}/ref")
        + text("Value", name, y1 + 1.0, "F.Fab", f"{name}/value")
        + "\t(attr through_hole)\n"
        + rect("F.CrtYd", -d / 2 - 0.25, -1.05, d / 2 + 0.25, y1 + 0.25, f"{name}/court")
        + rect("F.Fab", -d / 2, y0, d / 2, y1, f"{name}/fab")
        + "\n".join(body)
        + "\n)\n"
    )


def smd_varistor() -> tuple[str, str]:
    """TDK (EPCOS) CU3225 SMD varistor: body 8.0 x 6.3 x 3.2 mm, 2 pads 2.8 x 3.5 mm, 10.1 mm over
    both (EPCOS SIOV CU catalog, CU3225 land pattern)."""
    name = "RV_SMD_TDK_CU3225"
    pw, ph, over = 2.8, 3.5, 10.1
    cx = (over - pw) / 2
    body = [smd_pad("1", -cx, 0.0, pw, ph, f"{name}/1"), smd_pad("2", cx, 0.0, pw, ph, f"{name}/2")]
    return name, (
        f'(footprint "{name}"\n\t(version 20241229)\n\t(generator "make_footprints")\n\t(layer "F.Cu")\n'
        f'\t(descr "TDK EPCOS CU3225 SMD varistor, 8.0 x 6.3 x 3.2 mm")\n\t(tags "varistor MOV SMD")\n'
        + text("Reference", "RV**", -4.0, "F.SilkS", f"{name}/ref")
        + text("Value", name, 4.0, "F.Fab", f"{name}/value")
        + "\t(attr smd)\n"
        + rect("F.CrtYd", -over / 2 - 0.25, -3.4, over / 2 + 0.25, 3.4, f"{name}/court")
        + rect("F.Fab", -4.0, -3.15, 4.0, 3.15, f"{name}/fab")
        + "\n".join(body)
        + "\n)\n"
    )


def main() -> None:
    lib = HERE / "Lark.pretty"
    lib.mkdir(exist_ok=True)
    made = [lying_cap(8.0, 11.5, 3.5), smd_varistor()]
    for j in bulb.JOINTS:
        made += [tongue(j), slot(j)]
    for name, body in made:
        (lib / f"{name}.kicad_mod").write_text(body, encoding="utf-8")
        print(f"wrote {lib / name}.kicad_mod")


if __name__ == "__main__":
    main()
