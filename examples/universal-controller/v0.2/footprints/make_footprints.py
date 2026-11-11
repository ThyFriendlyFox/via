"""Write the project footprints into Rosetta.pretty.

    python3 footprints/make_footprints.py      # from the board's folder

Thumbstick_ALPS_RKJXV122400R: ALPS Alpine's ThumbPointer RKJXV122400R (the stick of PlayStation and
Xbox pads) from the "Mounting Hole Dimensions" of its catalog page, Drawing No. 1, viewed from the
mounting side; the origin is the stick's centre. Hall-effect drop-in sticks use the same holes, with
VCC, the output and GND on each axis's 3 pins.

  6 x d1.0 axis pins, 2.5 mm pitch: A row at y -8.73 (1 at x +2.5), B column at x +8.73 (1 at y +2.5)
  4 x d1.5 frame legs at (+-6.325, +-5.0)
  2 x d1.6 +-0.05 locating holes at (+-4.3, 0), not plated
  4 x d1.2 push-switch pins a (-3.25, 5.6), c (3.25, 5.6), b (-3.25, 10.1), d (3.25, 10.1)
  the prohibited wiring area (d4 at the centre, d3.5 at (0, 8), a 2.2 mm slot between, 4 x d2.6
  at (+-3.5, +-3.4)) is a keep-out in design.py, so the router and the DRC hold it.
"""

from __future__ import annotations

import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
NS = uuid.UUID("2f6f9d0e-8f5a-4f7e-9a51-0c6d1f0b7a11")


def uid(key: str) -> str:
    return str(uuid.uuid5(NS, key))


def text(kind: str, value: str, x: float, y: float, layer: str, hide: bool = False) -> str:
    return (f'\t(property "{kind}" "{value}"\n\t\t(at {x} {y} 0)\n\t\t(layer "{layer}")\n'
            + ("\t\t(hide yes)\n" if hide else "")
            + f'\t\t(uuid "{uid(kind)}")\n\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n\t\t\t\t(thickness 0.15)\n\t\t\t)\n\t\t)\n\t)\n')


def rect(x1, y1, x2, y2, layer, width, key):
    return (f'\t(fp_rect\n\t\t(start {x1} {y1})\n\t\t(end {x2} {y2})\n\t\t(stroke\n\t\t\t(width {width})\n'
            f'\t\t\t(type solid)\n\t\t)\n\t\t(fill no)\n\t\t(layer "{layer}")\n\t\t(uuid "{uid(key)}")\n\t)\n')


def circle(cx, cy, r, layer, width, key):
    return (f'\t(fp_circle\n\t\t(center {cx} {cy})\n\t\t(end {cx + r} {cy})\n\t\t(stroke\n\t\t\t(width {width})\n'
            f'\t\t\t(type solid)\n\t\t)\n\t\t(fill no)\n\t\t(layer "{layer}")\n\t\t(uuid "{uid(key)}")\n\t)\n')


def pad(number, x, y, size, drill, key, shape="circle", kind="thru_hole"):
    layers = '"*.Cu" "*.Mask"'
    return (f'\t(pad "{number}" {kind} {shape}\n\t\t(at {x} {y})\n\t\t(size {size} {size})\n\t\t(drill {drill})\n'
            f'\t\t(layers {layers})\n\t\t(uuid "{uid(key)}")\n\t)\n')


def thumbstick() -> None:
    name = "Thumbstick_ALPS_RKJXV122400R"
    out = [f'(footprint "{name}"\n\t(version 20260206)\n\t(generator "rosetta")\n\t(layer "F.Cu")\n'
           '\t(descr "ALPS RKJXV122400R ThumbPointer, 2-axis stick with centre push; Hall-effect drop-ins share it. '
           'Catalog Drawing No. 1, mounting hole dimensions")\n\t(tags "thumbstick joystick hall")\n']
    out.append(text("Reference", "REF**", 0, -11.6, "F.SilkS"))
    out.append(text("Value", name, 0, 12.6, "F.Fab"))
    out.append("\t(attr through_hole)\n")
    # The body, 18.2 x 21.7 (catalog), and its courtyard round every pad.
    out.append(rect(-9.1, -10.2, 10.1, 11.5, "F.Fab", 0.1, "fab"))
    out.append(rect(-9.6, -10.7, 10.6, 12.0, "F.CrtYd", 0.05, "crtyd"))
    out.append(rect(-9.2, -10.3, 10.2, 11.6, "F.SilkS", 0.12, "silk"))
    out.append(circle(0, 0, 9.0, "F.Fab", 0.1, "cap"))
    for k, x in ((1, 2.5), (2, 0.0), (3, -2.5)):
        out.append(pad(f"A{k}", x, -8.73, 1.6, 1.0, f"A{k}"))
    for k, y in ((1, 2.5), (2, 0.0), (3, -2.5)):
        out.append(pad(f"B{k}", 8.73, y, 1.6, 1.0, f"B{k}"))
    for n, x, y in (("a", -3.25, 5.6), ("c", 3.25, 5.6), ("b", -3.25, 10.1), ("d", 3.25, 10.1)):
        out.append(pad(n, x, y, 1.9, 1.2, n))
    for i, (x, y) in enumerate(((-6.325, -5.0), (6.325, -5.0), (-6.325, 5.0), (6.325, 5.0))):
        out.append(pad("MP", x, y, 2.3, 1.5, f"MP{i}"))
    for i, x in enumerate((-4.3, 4.3)):
        out.append(pad("", x, 0.0, 1.6, 1.6, f"loc{i}", kind="np_thru_hole"))
    out.append('\t(model "${KIPRJMOD}/models/thumbstick.wrl"\n\t\t(offset\n\t\t\t(xyz 0 0 0)\n\t\t)\n\t\t(scale\n'
               '\t\t\t(xyz 1 1 1)\n\t\t)\n\t\t(rotate\n\t\t\t(xyz 0 0 0)\n\t\t)\n\t)\n)\n')
    (HERE / "Rosetta.pretty" / f"{name}.kicad_mod").write_text("".join(out), encoding="utf-8")


if __name__ == "__main__":
    thumbstick()
    print(f"wrote {HERE / 'Rosetta.pretty'}")
