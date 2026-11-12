"""Draw Herald, the fire alarm communicator, for the site, from its design file and its routed board.

    python3 site/showcase/draw_face.py      # from the repository's root, with KiCad's libraries

It reads examples/fire-alarm-communicator/v0.1/design.py (the outline, every pad, where each part
sits, the silkscreen's words and mark) and herald.kicad_pcb (the routed tracks and vias), and
writes the drawing into site/index.html between the `face:begin` and `face:end` comments. Every
coordinate is the board's own, in mm: the drawing is the board, not a picture of it. Draw it again
when the board changes.

Each signal the page's buttons name lights the parts it passes (`data-part`), the path it takes
(`data-route`) and the status light it turns on (`data-led`). The paths are drawn over the board
from part to part; they are not its tracks.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "examples" / "fire-alarm-communicator" / "v0.1"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(PROJECT))

import kicadgen  # noqa: E402

# The signals, in the order of the page's buttons.
SIGNALS = ["dialer", "closed", "whole", "cut", "fails"]
ZONES = "closed whole cut"
# The parts each signal passes, and the status light it turns on (the light's silkscreen name).
PARTS = {
    "J2": "dialer",
    "Q3": "dialer",
    "Q4": "dialer",
    "U5": "dialer closed whole cut fails",
    "U4": "dialer",
    "U3": "dialer",
    "J4": "dialer",
    "J3": ZONES,
    "U8": ZONES,
    "Q6": "fails",
    "K1": "fails",
    "J7": "fails",
}
LIGHTS = {"CELL": "dialer", "ALARM": "closed", "POWER": "whole", "TROUBLE": "cut"}
TAGS = {"U3": "LTE-M", "U5": "ESP32-S3", "K1": "RELAY"}


def f(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def path_of(points: list[tuple[float, float]], close: bool = True) -> str:
    d = "M" + " L".join(f"{f(x)} {f(y)}" for x, y in points)
    return d + (" Z" if close else "")


def main() -> int:
    d = kicadgen.load_design(PROJECT / "design.py")
    import design as source  # the same file, for its constants

    copper = kicadgen.board_copper(PROJECT / "herald.kicad_pcb")
    parts = {p.ref: p for p in d.parts}
    out: list[str] = []
    x1, y1, x2, y2 = d.outline
    pad = 3.0
    out.append(
        f'<svg class="face-svg" viewBox="{f(x1 - pad)} {f(y1 - pad)} {f(x2 - x1 + 2 * pad)} {f(y2 - y1 + 2 * pad)}" '
        'role="img" aria-labelledby="face-title">'
    )
    out.append(
        '<title id="face-title">Herald v0.1 from the front: its outline, copper, the modem, the ESP32 module, '
        "the relay, the status lights and the screw terminals along the bottom edge</title>"
    )
    out.append(f'<path class="pcb" d="{path_of(d.outline_polygon(0.0, 10))}"/>')

    # The copper, the drawing's subject: the back first, then the inner signal layer, then the front,
    # each layer in a group of its own (`data-copper`) that the page sweeps in.
    for layer, cls in (("B.Cu", "cu-b"), ("In2.Cu", "cu-i"), ("F.Cu", "cu-f")):
        widths: dict[float, list[str]] = {}
        for _, a, b, w, lay in copper["segments"]:
            if lay == layer:
                widths.setdefault(round(w, 2), []).append(f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}")
        out.append(f'<g class="{cls}" data-copper="{layer}">')
        for w, segs in sorted(widths.items()):
            out.append(f'<path stroke-width="{f(w)}" d="{"".join(segs)}"/>')
        out.append("</g>")
    out.append('<g class="vias" data-copper="vias">' + "".join(
        f'<circle cx="{f(at[0])}" cy="{f(at[1])}" r="{f(size / 2)}"/>' for _, at, size, _ in copper["vias"]
    ) + "</g>")  # fmt: skip

    # The front's pads.
    rects = []
    for b in d.pad_boxes():
        if b.layer != "F.Cu" or b.kind == "np_thru_hole":
            continue
        rects.append(f'<rect x="{f(b.x1)}" y="{f(b.y1)}" width="{f(b.x2 - b.x1)}" height="{f(b.y2 - b.y1)}"/>')
    out.append('<g class="pads">' + "".join(rects) + "</g>")

    # The silkscreen's art on the front: the mark, the rules, the boxes, the words.
    for item in d.art:  # the loaded design's own list: `source` is a second copy of the module
        kind = item[0]
        layer = item[2] if kind == "poly" else item[3]  # ("poly", pts, layer, fill, w)
        if layer != "F.SilkS":
            continue
        if kind == "line":
            (ax, ay), (bx, by), w = item[1], item[2], item[4]
            out.append(f'<path class="silk-line" stroke-width="{f(w)}" d="M{f(ax)} {f(ay)}L{f(bx)} {f(by)}"/>')
        elif kind == "rect":
            (ax, ay), (bx, by), w = item[1], item[2], item[5]
            out.append(
                f'<rect class="silk-line" stroke-width="{f(w)}" x="{f(min(ax, bx))}" y="{f(min(ay, by))}" '
                f'width="{f(abs(bx - ax))}" height="{f(abs(by - ay))}"/>'
            )
        elif kind == "poly":
            pts, fill, w = item[1], item[3], item[4]
            cls = "silk-fill" if fill else "silk-line"
            out.append(f'<path class="{cls}" stroke-width="{f(w)}" d="{path_of(pts)}"/>')
        elif kind == "text":
            text, (x, y), size, justify, angle = item[1], item[2], item[4], item[6], item[7]
            # The stylesheet centres every text; a style beats it where the board's text is not.
            anchor = {"left": "start", "right": "end"}.get(justify)
            style = f' style="text-anchor:{anchor}"' if anchor else ""
            turn = f' transform="rotate({f(-angle)} {f(x)} {f(y)})"' if angle else ""
            out.append(
                f'<text class="silk"{style} x="{f(x)}" y="{f(y + size * 0.35)}" '
                f'font-size="{f(size)}"{turn}>{html.escape(text)}</text>'
            )

    # The bodies of the parts a signal passes, lit when it passes them.
    for ref, signals in PARTS.items():
        bx = d.courtyard_box(parts[ref])
        if bx is None:
            continue
        a, b_, c, e = bx
        out.append(
            f'<rect class="body" data-part="{signals}" x="{f(a)}" y="{f(b_)}" width="{f(c - a)}" '
            f'height="{f(e - b_)}" rx="0.6"/>'
        )
        if ref in TAGS:
            out.append(f'<text class="tag" x="{f((a + c) / 2)}" y="{f((b_ + e) / 2 + 0.55)}">{TAGS[ref]}</text>')

    # The status lights: each signal lights the 1 it turns on. A light named by 2 signals would
    # need 2 circles; each name here is 1 signal's.
    for k, y in enumerate(source.LED_Y):
        name = ["POWER", "CELL", "WI-FI", "ALARM", "TROUBLE"][k]
        signal = LIGHTS.get(name, "")
        out.append(f'<circle class="led" data-led="{signal}" cx="{f(source.LEDS_X)}" cy="{f(y)}" r="0.9"/>')

    # The paths each signal takes, from where it enters to where it goes.
    at = {ref: parts[ref].pcb_at for ref in ("J2", "Q3", "U5", "U4", "U3", "J4", "J3", "U8", "Q6", "K1", "J7")}
    j2 = (at["J2"][0] + 1.75, source.TERM_Y - 1.0)
    j3 = (at["J3"][0] + 5.25, source.TERM_Y - 1.0)
    j7 = (at["J7"][0] + 3.5, source.TERM_Y - 1.0)
    esp = at["U5"]
    routes = [
        ("dialer", [j2, (j2[0], at["Q3"][1]), at["Q3"], (150.4, at["Q3"][1]), (150.4, esp[1] + 3.0), (esp[0], esp[1] + 3.0), esp]),
        ("dialer", [esp, (esp[0] - 8.0, esp[1]), (esp[0] - 8.0, at["U4"][1]), at["U4"], (at["U3"][0], at["U4"][1]), at["U3"], at["J4"]]),
        (ZONES, [j3, (j3[0], at["U8"][1]), at["U8"], (at["U8"][0], esp[1] + 5.0), (esp[0], esp[1] + 5.0), esp]),
        ("fails", [esp, (esp[0] + 2.3, esp[1]), (esp[0] + 2.3, at["Q6"][1]), at["Q6"], (at["K1"][0], at["Q6"][1]), at["K1"], (j7[0], at["K1"][1]), j7]),
    ]  # fmt: skip
    for signals, pts in routes:
        out.append(f'<path class="route" data-route="{signals}" pathLength="1" d="{path_of(pts, close=False)}"/>')
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
