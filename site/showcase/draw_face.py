"""Draw the Rosetta controller's face for the site, from its design file and its routed board.

    python3 site/showcase/draw_face.py      # from the repository's root, with KiCad's libraries

It reads examples/universal-controller/v0.1/design.py (the outline, every pad, where each part
sits) and rosetta.kicad_pcb (the routed tracks and vias), and writes the drawing into
site/index.html between the `face:begin` and `face:end` comments. Every coordinate is the board's
own, in mm: the drawing is the board, not a picture of it. Draw it again when the board changes.
"""

from __future__ import annotations

import html
import math
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "examples" / "universal-controller" / "v0.1"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(PROJECT))

import kicadgen  # noqa: E402

design_module = kicadgen  # the design file imports kicadgen from tools/


def f(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def path_of(points: list[tuple[float, float]], close: bool = True) -> str:
    d = "M" + " L".join(f"{f(x)} {f(y)}" for x, y in points)
    return d + (" Z" if close else "")


def main() -> int:
    d = kicadgen.load_design(PROJECT / "design.py")
    import design as source  # the same file, for its constants

    copper = kicadgen.board_copper(PROJECT / "rosetta.kicad_pcb")
    parts = {p.ref: p for p in d.parts}
    out: list[str] = []
    x1, y1, x2, y2 = d.outline
    pad = 3.0
    out.append(
        f'<svg class="face-svg" viewBox="{f(x1 - pad)} {f(y1 - pad)} {f(x2 - x1 + 2 * pad)} {f(y2 - y1 + 2 * pad)}" '
        'role="img" aria-labelledby="face-title">'
    )
    out.append('<title id="face-title">Rosetta v0.1 from the front: its outline, copper, buttons, the mode knob and its ring</title>')
    out.append(f'<path class="pcb" d="{path_of(d.outline_polygon(0.0, 10))}"/>')

    # The copper: the back first, faint, then the front. Each layer is 1 path per track width.
    for layer, cls in (("B.Cu", "cu-b"), ("In2.Cu", "cu-i"), ("F.Cu", "cu-f")):
        widths: dict[float, list[str]] = {}
        for _, a, b, w, lay in copper["segments"]:
            if lay == layer:
                widths.setdefault(round(w, 2), []).append(f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}")
        for w, segs in sorted(widths.items()):
            out.append(f'<path class="{cls}" stroke-width="{f(w)}" d="{"".join(segs)}"/>')
    out.append('<g class="vias">' + "".join(
        f'<circle cx="{f(at[0])}" cy="{f(at[1])}" r="{f(size / 2)}"/>' for _, at, size, _ in copper["vias"]
    ) + "</g>")  # fmt: skip

    # The front's pads.
    rects = []
    for b in d.pad_boxes():
        if b.layer != "F.Cu" or b.kind == "np_thru_hole":
            continue
        rects.append(f'<rect x="{f(b.x1)}" y="{f(b.y1)}" width="{f(b.x2 - b.x1)}" height="{f(b.y2 - b.y1)}"/>')
    out.append('<g class="pads">' + "".join(rects) + "</g>")

    def box(ref: str, extra: str = "", label: str = "", inset: float = 0.0) -> None:
        bx = d.courtyard_box(parts[ref])
        if bx is None:
            return
        a, b_, c, e = bx
        out.append(
            f'<rect class="body" {extra} x="{f(a + inset)}" y="{f(b_ + inset)}" width="{f(c - a - 2 * inset)}" '
            f'height="{f(e - b_ - 2 * inset)}" rx="0.8"/>'
        )
        if label:
            out.append(f'<text class="tag" x="{f((a + c) / 2)}" y="{f(e + 2.6)}">{html.escape(label)}</text>')

    # The parts on the back that the modes use, as outlines seen through the board.
    usb_modes = "ps4 ps5 xbox switch"
    # The ESP32 module's body, not its courtyard: the courtyard holds the antenna's keep-out. The
    # module is 18 x 25.5 mm; its last 6.44 mm, the antenna, hangs past the notch's edge.
    ex, ey = source.ESP_AT
    out.append(
        f'<rect class="body" data-part="bluetooth" data-ghost="" x="{f(ex - 9)}" y="{f(ey - 12.75)}" '
        f'width="18" height="25.5" rx="0.8"/>'
    )
    out.append(f'<rect class="antenna" data-part="bluetooth" x="{f(ex - 9)}" y="{f(source.NOTCH_Y)}" width="18" height="{f(ey + 12.75 - source.NOTCH_Y)}" rx="0.8"/>')
    out.append(f'<text class="tag" x="{f(ex)}" y="{f(ey + 12.75 + 2.6)}">ESP32 · back · antenna</text>')
    box("U1", 'data-part="ps4 ps5 xbox switch bluetooth" data-ghost=""', "RP2040 · back")
    box("U6", 'data-part="ps5" data-ghost=""', "")
    box("U9", 'data-part="switch ps5" data-ghost=""', "")
    box("U10", 'data-part="switch ps5" data-ghost=""', "")

    # The parts a hand meets: buttons, connectors.
    for ref, part in parts.items():
        if part.pcb_layer != "F.Cu" or not ref.startswith(("SW", "J")) or ref == "SW1":
            continue
        extra = ""
        if ref == "J1":
            extra = f'data-part="{usb_modes}"'
        elif ref == "J2":
            extra = 'data-part="ps4 ps5 xbox"'
        elif ref in ("J3", "J4"):
            extra = 'data-part="ps5"'
        elif ref in ("J7", "J8"):
            extra = 'data-part="switch ps5"'
        box(ref, extra, inset=0.4 if ref.startswith("SW") else 0.0)
    for (x, y) in (source.STICK_L, source.STICK_R):
        out.append(f'<circle class="stick" cx="{f(x)}" cy="{f(y)}" r="{f(source.STICK_R_ZONE)}"/>')
        out.append(f'<circle class="stick-cap" cx="{f(x)}" cy="{f(y)}" r="{f(source.STICK_R_ZONE * 0.55)}"/>')

    # The words on the silkscreen.
    for text, x, y, layer, size, _ in d.texts:
        if layer == "F.SilkS" and text not in {m[1] for m in source.MODES}:
            out.append(f'<text class="silk" x="{f(x)}" y="{f(y + size * 0.35)}" font-size="{f(size)}">{html.escape(text)}</text>')

    # The routes each mode's data takes, drawn over the board from the port to the RP2040.
    u1 = parts["U1"].pcb_at
    j1 = (170.0, 101.5)
    j2 = (205.0, 101.5)
    esp = (source.ESP_AT[0], source.ESP_AT[1] + 2.0)
    routes = [
        ("ps4 ps5 xbox switch", [j1, (170.0, 113.0), (u1[0] + 6, 113.0), (u1[0] + 6, u1[1]), u1]),
        ("ps4 ps5 xbox", [j2, (205.0, 113.5), (u1[0] + 8, 113.5), (u1[0] + 8, u1[1] + 2), (u1[0], u1[1] + 2)]),
        ("bluetooth", [esp, (esp[0], 133.0), (u1[0] + 6, 133.0), (u1[0] + 6, u1[1] + 4), (u1[0], u1[1] + 4)]),
        ("ps5", [(127.0, 103.0), (127.0, 110.0), (186.0, 110.0)]),
        ("switch ps5", [(110.0, 163.0), (110.0, 152.0), (112.0, 152.0)]),
    ]
    for modes, pts in routes:
        out.append(f'<path class="route" data-route="{modes}" pathLength="1" d="{path_of(pts, close=False)}"/>')

    # The knob, its ring of LEDs and their labels.
    kx, ky = source.KNOB
    out.append(f'<circle class="knob-ring" cx="{f(kx)}" cy="{f(ky)}" r="{f(source.RING_R + 2.2)}"/>')
    ids = ["ps4", "ps5", "xbox", "switch", "bluetooth"]
    for (deg, label), mode in zip(source.MODES, ids, strict=True):
        a = math.radians(deg)
        lx, ly = kx + source.RING_R * math.cos(a), ky - source.RING_R * math.sin(a)
        out.append(f'<circle class="led" data-led="{mode}" cx="{f(lx)}" cy="{f(ly)}" r="1.25"/>')
        tx, ty = source.label_at(deg)
        out.append(f'<text class="mode-label" x="{f(tx)}" y="{f(ty + 0.45)}">{label}</text>')
    out.append(f'<circle class="knob" cx="{f(kx)}" cy="{f(ky)}" r="6.2"/>')
    out.append(
        f'<g data-pointer="" style="transform-origin:{f(kx)}px {f(ky)}px; transform-box:view-box">'
        f'<path class="pointer" d="M{f(kx)} {f(ky - 5.4)} L{f(kx)} {f(ky - 1.5)}"/></g>'
    )
    out.append("</svg>")
    drawing = "\n".join(out)

    page = ROOT / "site" / "index.html"
    text = page.read_text(encoding="utf-8")
    new, n = re.subn(
        r"(<!-- face:begin -->).*?(\n[ \t]*<!-- face:end -->)", lambda m: m.group(1) + "\n" + drawing + m.group(2), text, flags=re.S
    )
    if n != 1:
        print("site/index.html has no face:begin / face:end pair", file=sys.stderr)
        return 1
    page.write_text(new, encoding="utf-8")
    print(f"site/index.html: the face drawn, {len(drawing) // 1024} KB, {len(copper['segments'])} tracks, {len(copper['vias'])} vias")
    return 0


if __name__ == "__main__":
    sys.exit(main())
