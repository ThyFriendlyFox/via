"""A small writer for KiCad footprints: pads, holes, lines and outlines as KiCad 9 S-expressions.

KiCad 10 reads these; `kicadgen` reads them as a project footprint library (`d.footprint_dirs`).
Coordinates are millimetres in the footprint's frame, y downward, as KiCad stores them.
"""

from __future__ import annotations

from pathlib import Path


def f(v: float) -> str:
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


class Footprint:
    def __init__(self, name: str, descr: str, smd: bool = False):
        self.name = name
        self.descr = descr
        self.smd = smd
        self.items: list[str] = []
        self.ref_at = (0.0, 0.0)
        self.value_at = (0.0, 0.0)
        self.ref_layer = "F.SilkS"

    # ---- pads
    def smd_pad(self, num: str, x: float, y: float, w: float, h: float, shape: str = "roundrect",
                layers: tuple[str, ...] = ("F.Cu", "F.Mask", "F.Paste"), rratio: float = 0.25,
                angle: float = 0.0) -> None:
        rr = f" (roundrect_rratio {f(rratio)})" if shape == "roundrect" else ""
        at = f"(at {f(x)} {f(y)}{' ' + f(angle) if angle else ''})"
        lay = " ".join(f'"{layer}"' for layer in layers)
        self.items.append(f'\t(pad "{num}" smd {shape} {at} (size {f(w)} {f(h)}) (layers {lay}){rr})')

    def tht_pad(self, num: str, x: float, y: float, pad: float, drill: float, shape: str = "circle",
                pad_h: float | None = None, drill_h: float | None = None) -> None:
        """A plated hole; `pad_h` and `drill_h` make an oval pad and a slot."""
        h = pad if pad_h is None else pad_h
        d = f"(drill {f(drill)})" if drill_h is None else f"(drill oval {f(drill)} {f(drill_h)})"
        self.items.append(
            f'\t(pad "{num}" thru_hole {shape} (at {f(x)} {f(y)}) (size {f(pad)} {f(h)}) {d} '
            f'(layers "*.Cu" "*.Mask") (remove_unused_layers no))'
        )

    def npth(self, x: float, y: float, drill: float) -> None:
        self.items.append(
            f'\t(pad "" np_thru_hole circle (at {f(x)} {f(y)}) (size {f(drill)} {f(drill)}) (drill {f(drill)}) '
            f'(layers "*.Cu" "*.Mask"))'
        )

    # ---- graphics
    def line(self, x1: float, y1: float, x2: float, y2: float, layer: str, w: float = 0.12) -> None:
        self.items.append(
            f'\t(fp_line (start {f(x1)} {f(y1)}) (end {f(x2)} {f(y2)}) (stroke (width {f(w)}) (type solid)) '
            f'(layer "{layer}"))'
        )

    def rect(self, x1: float, y1: float, x2: float, y2: float, layer: str, w: float = 0.12, fill: bool = False) -> None:
        self.items.append(
            f'\t(fp_rect (start {f(x1)} {f(y1)}) (end {f(x2)} {f(y2)}) (stroke (width {f(w)}) (type solid)) '
            f'(fill {"yes" if fill else "no"}) (layer "{layer}"))'
        )

    def poly(self, pts: list[tuple[float, float]], layer: str, w: float = 0.12, fill: bool = False) -> None:
        xy = " ".join(f"(xy {f(x)} {f(y)})" for x, y in pts)
        self.items.append(
            f'\t(fp_poly (pts {xy}) (stroke (width {f(w)}) (type solid)) (fill {"yes" if fill else "no"}) '
            f'(layer "{layer}"))'
        )

    def circle(self, cx: float, cy: float, r: float, layer: str, w: float = 0.12, fill: bool = False) -> None:
        self.items.append(
            f'\t(fp_circle (center {f(cx)} {f(cy)}) (end {f(cx + r)} {f(cy)}) (stroke (width {f(w)}) (type solid)) '
            f'(fill {"yes" if fill else "no"}) (layer "{layer}"))'
        )

    def text(self, s: str, x: float, y: float, layer: str, size: float = 1.0, thick: float = 0.15) -> None:
        self.items.append(
            f'\t(fp_text user "{s}" (at {f(x)} {f(y)}) (layer "{layer}") '
            f'(effects (font (size {f(size)} {f(size)}) (thickness {f(thick)}))))'
        )

    def courtyard(self, x1: float, y1: float, x2: float, y2: float, layer: str = "F.CrtYd") -> None:
        self.rect(x1, y1, x2, y2, layer, 0.05)

    def model(self, path: str) -> None:
        self.items.append(f'\t(model "{path}" (offset (xyz 0 0 0)) (scale (xyz 1 1 1)) (rotate (xyz 0 0 0)))')

    def write(self, lib: Path) -> Path:
        lib.mkdir(parents=True, exist_ok=True)
        rx, ry = self.ref_at
        vx, vy = self.value_at
        text = (
            f'(footprint "{self.name}"\n\t(version 20241229)\n\t(generator "pcbnew")\n\t(layer "F.Cu")\n'
            f'\t(descr "{self.descr}")\n'
            f'\t(property "Reference" "REF**" (at {f(rx)} {f(ry)} 0) (layer "{self.ref_layer}") '
            f"(effects (font (size 1 1) (thickness 0.15))))\n"
            f'\t(property "Value" "{self.name}" (at {f(vx)} {f(vy)} 0) (layer "F.Fab") '
            f"(effects (font (size 1 1) (thickness 0.15))))\n"
            f"\t(attr {'smd' if self.smd else 'through_hole'})\n" + "\n".join(self.items) + "\n)\n"
        )
        path = lib / f"{self.name}.kicad_mod"
        path.write_text(text, encoding="utf-8")
        return path
