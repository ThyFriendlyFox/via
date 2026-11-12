"""The board's own footprints: 1 library footprint copied with 1 change, 2 drawn from their makers' drawings.

    python3 footprints/make_footprints.py      # from the board's folder; writes footprints/wyvern.pretty/

- The USB-C receptacle. KiCad's `USB_C_Receptacle_Amphenol_12401610E4-2A` draws the 4 shell tabs as
  0.8 x 1.4 mm pads round a 0.5 x 1.1 mm slot: a 0.15 mm ring, under Sierra Circuits' 6 mil
  (0.1524 mm). The copy's tab pads are 0.82 x 1.42 mm, a 0.16 mm ring. The 2 rear tabs stand
  0.29 mm from the receptacle's locating pegs, under Sierra's 13 mil from a hole to inner-layer
  copper. They hold the shell and nothing else, and the 2 front tabs ground it, so the copy leaves
  the rear 2 unnumbered: on no net, KiCad keeps their copper on the outer layers only.
- The QCS6490 module's land pattern, `OSM_L_LGA-662_45x45mm_P1.25mm`: SGET's OSM Size-L contact
  map as `osm_l.py` holds it, 662 round pads 0.80 mm across on a 1.25 mm grid, the origin at the
  module's centre. The paste opens each pad 1:1 (OSM's 100 um stencil); the mask opens it 1:1, as
  Antmicro's open OSM-L footprint does, leaving 0.45 mm of mask between pads. Silk marks the
  module's corners and pad A1's corner; the courtyard is 0.25 mm past the 45 mm body.
- The TPS552892's package, `Texas_RYQ0021A_VQFN-HR-21_5x3mm_P0.5mm`: TI's RYQ0021A land pattern
  example (TPS552892 datasheet SLVSH28A, page 33): 16 pads 0.25 mm wide round the edge, 0.6 mm
  long (0.65 at the 4 corners), and 5 power pads 0.25 x 3.4 mm across the middle, PGND (9) widened
  to 0.33 mm over its middle 2.35 mm. The stencil (page 34) opens each power pad as 3 windows, 88 %
  of its area (64 % on PGND); the copy opens 3 windows 1.0 mm long on VIN, SW1, SW2 and VOUT and
  3 windows 0.9 mm long on PGND.

The rest comes from KiCad's library as it is.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import osm_l  # noqa: E402

KICAD = Path("/usr/share/kicad/footprints")
COPIES = [
    (
        "Connector_USB.pretty/USB_C_Receptacle_Amphenol_12401610E4-2A",
        "USB_C_Receptacle_Amphenol_12401610E4-2A_Ring6mil",
        [("(size 0.8 1.4)", "(size 0.82 1.42)", 4)]
        + [
            (
                f'(pad "SH" thru_hole oval\n\t\t(at {x} -3.11)\n\t\t(size 0.8 1.4)\n\t\t(drill oval 0.5 1.1)\n'
                '\t\t(property pad_prop_mechanical)\n\t\t(layers "*.Cu" "*.Mask")\n\t\t(remove_unused_layers no)',
                f'(pad "" thru_hole oval\n\t\t(at {x} -3.11)\n\t\t(size 0.8 1.4)\n\t\t(drill oval 0.5 1.1)\n'
                '\t\t(property pad_prop_mechanical)\n\t\t(layers "*.Cu" "*.Mask")\n\t\t(remove_unused_layers yes)\n'
                '\t\t(keep_end_layers yes)',
                1,
            )
            for x in ("-4.13", "4.13")
        ],
    ),
]


def fmt(v: float) -> str:
    return f"{round(v, 4):g}"


def line(a: tuple[float, float], b: tuple[float, float], layer: str, width: float) -> str:
    return (
        f"\t(fp_line\n\t\t(start {fmt(a[0])} {fmt(a[1])})\n\t\t(end {fmt(b[0])} {fmt(b[1])})\n"
        f'\t\t(stroke\n\t\t\t(width {fmt(width)})\n\t\t\t(type solid)\n\t\t)\n\t\t(layer "{layer}")\n\t)'
    )


def rect(a: tuple[float, float], b: tuple[float, float], layer: str, width: float) -> str:
    return (
        f"\t(fp_rect\n\t\t(start {fmt(a[0])} {fmt(a[1])})\n\t\t(end {fmt(b[0])} {fmt(b[1])})\n"
        f'\t\t(stroke\n\t\t\t(width {fmt(width)})\n\t\t\t(type solid)\n\t\t)\n\t\t(fill no)\n\t\t(layer "{layer}")\n\t)'
    )


def poly(points: list[tuple[float, float]], layer: str) -> str:
    pts = " ".join(f"(xy {fmt(x)} {fmt(y)})" for x, y in points)
    return (
        f"\t(fp_poly\n\t\t(pts {pts})\n\t\t(stroke\n\t\t\t(width 0.1)\n\t\t\t(type solid)\n\t\t)\n"
        f'\t\t(fill yes)\n\t\t(layer "{layer}")\n\t)'
    )


def text(kind: str, value: str, y: float, layer: str, hide: bool = False) -> str:
    h = "\n\t\t(hide yes)" if hide else ""
    return (
        f'\t(property "{kind}" "{value}"\n\t\t(at 0 {fmt(y)} 0)\n\t\t(layer "{layer}"){h}\n'
        "\t\t(effects\n\t\t\t(font\n\t\t\t\t(size 1 1)\n\t\t\t\t(thickness 0.15)\n\t\t\t)\n\t\t)\n\t)"
    )


def pad(number: str, shape: str, at: tuple[float, float], size: tuple[float, float], layers: str,
        extra: str = "") -> str:
    return (
        f'\t(pad "{number}" smd {shape}\n\t\t(at {fmt(at[0])} {fmt(at[1])})\n'
        f"\t\t(size {fmt(size[0])} {fmt(size[1])})\n{extra}\t\t(layers {layers})\n\t)"
    )


def footprint(name: str, descr: str, tags: str, ref_y: float, body: list[str]) -> str:
    head = (
        f'(footprint "{name}"\n\t(version 20241229)\n\t(generator "wyvern")\n\t(layer "F.Cu")\n'
        f'\t(descr "{descr}")\n\t(tags "{tags}")\n'
    )
    props = [text("Reference", "REF**", -ref_y, "F.SilkS"), text("Value", name, ref_y, "F.Fab")]
    return head + "\n".join([*props, "\t(attr smd)", *body]) + "\n)\n"


def osm_size_l() -> str:
    half = osm_l.SIZE / 2
    body: list[str] = []
    # Silk: the module's 4 corners as L's 0.15 mm outside its edge, and a filled triangle at A1's corner.
    s, arm = half + 0.15, 3.0
    for sx in (-1, 1):
        for sy in (-1, 1):
            corner = (sx * s, sy * s)
            body.append(line(corner, (sx * (s - arm), sy * s), "F.SilkS", 0.15))
            body.append(line(corner, (sx * s, sy * (s - arm)), "F.SilkS", 0.15))
    body.append(poly([(-s - 0.3, -s - 0.3), (-s - 0.3, -s + 1.6), (-s + 1.6, -s - 0.3)], "F.SilkS"))
    body.append(rect((-half, -half), (half, half), "F.Fab", 0.1))
    body.append(poly([(-half, -half + 2.0), (-half, -half), (-half + 2.0, -half)], "F.Fab"))
    c = half + 0.25
    body.append(rect((-c, -c), (c, c), "F.CrtYd", 0.05))
    layers = '"F.Cu" "F.Mask" "F.Paste"'
    for p in osm_l.PADS:
        body.append(pad(p, "circle", osm_l.pad_xy(p), (osm_l.PAD, osm_l.PAD), layers, "\t\t(property pad_prop_bga)\n"))
    return footprint(
        "OSM_L_LGA-662_45x45mm_P1.25mm",
        "SGET OSM Size-L module, 662 LGA pads 0.80 mm on a 1.25 mm grid (OSM v1.2 contact map)",
        "OSM LGA module",
        half + 1.2,
        body,
    )


def ryq0021a() -> str:
    """TI RYQ0021A, seen from above with pins 1 to 4 on the left: x along the 5 mm side, y down."""
    body: list[str] = []
    cu = '"F.Cu" "F.Mask"'
    cup = '"F.Cu" "F.Mask" "F.Paste"'
    # The edge pads: (number, x, y, w, h).
    edge = [(str(n), -2.4, -0.75 + 0.5 * (n - 1), 0.6, 0.25) for n in range(1, 5)]
    edge += [(str(n), 2.4, 0.75 - 0.5 * (n - 14), 0.6, 0.25) for n in range(14, 18)]
    edge += [("5", -2.04, 1.375, 0.25, 0.65), ("6", -1.54, 1.4, 0.25, 0.6), ("12", 1.54, 1.4, 0.25, 0.6),
             ("13", 2.04, 1.375, 0.25, 0.65), ("18", 2.04, -1.375, 0.25, 0.65), ("19", 1.54, -1.4, 0.25, 0.6),
             ("20", -1.54, -1.4, 0.25, 0.6), ("21", -2.04, -1.375, 0.25, 0.65)]  # fmt: skip
    for n, x, y, w, h in edge:
        body.append(pad(n, "roundrect", (x, y), (w, h), cup, "\t\t(roundrect_rratio 0.2)\n"))
    # The 5 power pads across the middle, copper and mask only; the paste windows follow.
    for n, x in (("7", -1.04), ("8", -0.54), ("9", 0.0), ("10", 0.54), ("11", 1.04)):
        body.append(pad(n, "roundrect", (x, 0.0), (0.25, 3.4), cu, "\t\t(roundrect_rratio 0.2)\n"))
        length = 0.9 if n == "9" else 1.0
        for y in (-1.15, 0.0, 1.15):
            body.append(pad("", "roundrect", (x, y), (0.25, length), '"F.Paste"', "\t\t(roundrect_rratio 0.2)\n"))
    body.append(pad("9", "rect", (0.0, 0.0), (0.33, 2.35), cu))
    # Silk at the 4 corners of the 5 x 3 mm body, clear of the pads; pin 1's mark at its upper left.
    hx, hy = 2.62, 1.62
    for sx in (-1, 1):
        body.append(line((sx * hx, -hy), (sx * hx, -1.05), "F.SilkS", 0.12))
        body.append(line((sx * hx, hy), (sx * hx, 1.05), "F.SilkS", 0.12))
    body.append(poly([(-2.95, -1.2), (-2.95, -0.75), (-2.75, -0.975)], "F.SilkS"))
    body.append(rect((-2.5, -1.5), (2.5, 1.5), "F.Fab", 0.1))
    body.append(rect((-2.95, -1.95), (2.95, 1.95), "F.CrtYd", 0.05))
    return footprint(
        "Texas_RYQ0021A_VQFN-HR-21_5x3mm_P0.5mm",
        "TI RYQ0021A VQFN-HR (HotRod), 21 pins, 5 x 3 mm (https://www.ti.com/lit/ds/symlink/tps552892.pdf#page=33)",
        "Texas VQFN-HR HotRod",
        2.6,
        body,
    )


def main() -> None:
    out_dir = HERE / "wyvern.pretty"
    out_dir.mkdir(exist_ok=True)
    for old in out_dir.glob("*.kicad_mod"):
        old.unlink()
    for source, name, edits in COPIES:
        path = KICAD / f"{source}.kicad_mod"
        text_ = path.read_text(encoding="utf-8")
        for old, new, count in sorted(edits, key=lambda e: e[0].startswith("(size")):
            if text_.count(old) != count:
                raise SystemExit(f"{path.name}: expected {count} '{old}', found {text_.count(old)}; the library changed")
            text_ = text_.replace(old, new)
        old_name = f'(footprint "{Path(source).name}"'
        if text_.count(old_name) != 1:
            raise SystemExit(f"{path.name}: its name line changed")
        text_ = text_.replace(old_name, f'(footprint "{name}"')
        (out_dir / f"{name}.kicad_mod").write_text(text_, encoding="utf-8")
        print(f"wrote {out_dir / name}.kicad_mod")
    for name, text_ in (("OSM_L_LGA-662_45x45mm_P1.25mm", osm_size_l()),
                        ("Texas_RYQ0021A_VQFN-HR-21_5x3mm_P0.5mm", ryq0021a())):  # fmt: skip
        (out_dir / f"{name}.kicad_mod").write_text(text_, encoding="utf-8")
        print(f"wrote {out_dir / name}.kicad_mod")


if __name__ == "__main__":
    main()
