"""Hush v0.1: a speaker that listens to the room and plays the inverse wave.

A ring of circuit board sits on the face of a 40 mm speaker driver. Through the ring's three windows
you see the cone; at the centre, held on three spokes, a MEMS microphone listens a few millimetres in
front of it. Two op-amps turn what the mic hears into its inverse, a class-D amplifier plays it, and
low-frequency noise cancels in the air in front of the cone. Music from the line input plays at the
same time; the loop takes it as its target instead of cancelling it.

There is no microcontroller and no firmware: the inverse wave is made by analog parts in a few
microseconds, which is what a feedback loop through 4 mm of air needs.

    workcenter design design.py --route     # from this folder: the KiCad project beside this file
    workcenter gates .                      # ERC, DRC, SIM, EXPORT

The circuit, left to right on the schematic:
  J1      USB-C, 5 V only (CC pull-downs R1, R2), +5V straight to the amplifier.
  U1      LP5907 makes +2V8 for the analog side behind R25/C3; the mic's maximum is 3.0 V.
  R3, R4  VREF, half of +2V8: the op-amps' and the mic's signal ground (C6).
  MIC1    Infineon IM73A135, a differential analog MEMS mic on the hub, its port on the cone's axis.
  U2      the error amplifier: a balanced difference amplifier, mic minus the music reference
          (R12/C12 into its + leg, R13/C13 the matching leg), gain 5, with a lag shelf in each leg
          (R9/C10, R11/C11 under R8, R10) that buys phase margin below 50 Hz.
  U3      the controller: an integrator (C17, R16) behind the depth trimmer RV1 and a lead network
          (R14, R15, C16). U4, an analog switch across C17, turns the cancelling off.
  U5      PAM8302A class-D amplifier: the anti-noise into IN+, the music into IN-.
  J3      the speaker's two wires.
  J2      line in, left and right mixed to mono (R20-R22).
  SW1     ANC on or off; D1 lights while it is on.

The board: a ring 62 mm across around a 33 mm opening, with a hub 9.2 mm across on three spokes,
4 layers: F.Cu parts and signals, In1.Cu a whole ground plane, In2.Cu signals, B.Cu a whole ground
pour that the router never uses, so the back's artwork and its gold rims sit on unbroken copper.
"""

from __future__ import annotations

import math
import uuid
from pathlib import Path

import kicadgen

HERE = Path(__file__).resolve().parent
NAME = "hush"
NS = uuid.UUID("16d03d5c-0b13-4854-98ac-de12a39510b1")
g = 2.54

# ---- the ring ------------------------------------------------------------------------------------
# Board coordinates in mm, y down. The ring is centred on (CX, CY).
CX, CY = 130.0, 130.0
R_OUT = 31.0  # the board's edge
R_HOLE = 16.5  # the opening over the cone: the CE40-4's frame is 40 mm across, its cone and surround 33
R_HUB = 4.6  # the hub that carries the mic
SPOKE_W = 3.2
FILLET = 1.0  # every inside corner of a window, for the router bit
SPOKES = (270.0, 30.0, 150.0)  # screen angles: 0 east, 90 south
R_FLANGE = 20.0  # the driver's frame rests on the back face from R_HOLE to here
R_HOLES = 26.9  # the three M2 mounting holes, on the spokes' axes, their pads 1 mm inside the rim
RIM = 0.8  # the gold rims on the back: mask openings this wide over the ground pour
PORT_RIM = 1.3  # the gold ring round the mic's port, on the back
EDGE = 0.3


def polar(r: float, deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return (round(CX + r * math.cos(a), 4), round(CY + r * math.sin(a), 4))


def facing(deg: float) -> float:
    """The rotation that turns a footprint's +y toward the board's edge at screen angle `deg`."""
    return (90.0 - deg) % 360.0


def _unit(deg: float) -> tuple[float, float]:
    a = math.radians(deg)
    return (math.cos(a), math.sin(a))


def window(k: int, grow: float = 0.0, arc_pts: int = 24) -> tuple[list, list[tuple[float, float]]]:
    """Window k, between spoke k and spoke k+1 (clockwise on screen), grown outward by `grow`.

    Returns its outline as primitives (("line", a, b) and ("arc", start, mid, end)) and as a polygon.
    The window is the opening between the hole's circle, the hub's circle and the two spokes' edges,
    each of its four corners rounded with FILLET (grown with it).
    """
    r_out, r_in, half, rf = R_HOLE + grow, R_HUB - grow, SPOKE_W / 2 - grow, FILLET + grow
    a_deg, b_deg = SPOKES[k], SPOKES[(k + 1) % 3]
    if b_deg < a_deg:
        b_deg += 360.0
    ua, ub = _unit(a_deg), _unit(b_deg)
    na = (-ua[1], ua[0])  # spoke A's edge normal, into the window (toward larger angles)
    nb = (ub[1], -ub[0])  # spoke B's edge normal, into the window (toward smaller angles)

    def corner(u, n, R, outer):
        """The fillet between a spoke's edge (n . x = half) and a circle of radius R about the centre."""
        d = half + rf
        rr = R - rf if outer else R + rf
        t = math.sqrt(rr * rr - d * d)
        p = (n[0] * d + u[0] * t, n[1] * d + u[1] * t)
        on_line = (p[0] - n[0] * rf, p[1] - n[1] * rf)
        pl = math.hypot(*p)
        on_circle = (p[0] * R / pl, p[1] * R / pl)
        return p, on_line, on_circle

    def fillet_mid(p, a, b):
        mx, my = (a[0] + b[0]) / 2 - p[0], (a[1] + b[1]) / 2 - p[1]
        m = math.hypot(mx, my)
        return (p[0] + mx / m * rf, p[1] + my / m * rf)

    def circle_mid(R, a, b, short):
        aa, ab = math.atan2(a[1], a[0]), math.atan2(b[1], b[0])
        sweep = (ab - aa) % (2 * math.pi)
        if short and sweep > math.pi or not short and sweep < math.pi:
            sweep -= 2 * math.pi
        am = aa + sweep / 2
        return (R * math.cos(am), R * math.sin(am)), aa, sweep

    pa_o, la_o, ca_o = corner(ua, na, r_out, True)
    pb_o, lb_o, cb_o = corner(ub, nb, r_out, True)
    pa_i, la_i, ca_i = corner(ua, na, r_in, False)
    pb_i, lb_i, cb_i = corner(ub, nb, r_in, False)
    mid_out, aa_out, sw_out = circle_mid(r_out, ca_o, cb_o, short=True)
    mid_in, aa_in, sw_in = circle_mid(r_in, cb_i, ca_i, short=True)
    prims = [
        ("line", la_i, la_o),
        ("arc", la_o, fillet_mid(pa_o, la_o, ca_o), ca_o),
        ("arc", ca_o, mid_out, cb_o),
        ("arc", cb_o, fillet_mid(pb_o, cb_o, lb_o), lb_o),
        ("line", lb_o, lb_i),
        ("arc", lb_i, fillet_mid(pb_i, lb_i, cb_i), cb_i),
        ("arc", cb_i, mid_in, ca_i),
        ("arc", ca_i, fillet_mid(pa_i, ca_i, la_i), la_i),
    ]

    def arc_points(s, m, e, n):
        # the circle through s, m, e, sampled from s to e through m
        ax, ay = s
        bx, by = m
        cx, cy = e
        dd = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
        ux = ((ax * ax + ay * ay) * (by - cy) + (bx * bx + by * by) * (cy - ay) + (cx * cx + cy * cy) * (ay - by)) / dd
        uy = ((ax * ax + ay * ay) * (cx - bx) + (bx * bx + by * by) * (ax - cx) + (cx * cx + cy * cy) * (bx - ax)) / dd
        r = math.hypot(ax - ux, ay - uy)
        a0 = math.atan2(ay - uy, ax - ux)
        am = math.atan2(by - uy, bx - ux)
        a1 = math.atan2(cy - uy, cx - ux)
        sw = (a1 - a0) % (2 * math.pi)
        if (am - a0) % (2 * math.pi) > sw:
            sw -= 2 * math.pi
        return [(ux + r * math.cos(a0 + sw * i / n), uy + r * math.sin(a0 + sw * i / n)) for i in range(n)]

    poly: list[tuple[float, float]] = []
    for prim in prims:
        if prim[0] == "line":
            poly.append(prim[1])
        else:
            n = arc_pts if prim[2] in (mid_out, mid_in) else max(4, arc_pts // 4)
            poly.extend(arc_points(prim[1], prim[2], prim[3], n))

    def shift(p):
        return (round(CX + p[0], 4), round(CY + p[1], 4))

    prims = [(p[0], *[shift(q) for q in p[1:]]) for p in prims]
    return prims, [shift(p) for p in poly]


def _inside(poly: list[tuple[float, float]], x: float, y: float) -> bool:
    inside = False
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
            inside = not inside
    return inside


def _dist(poly: list[tuple[float, float]], x: float, y: float) -> float:
    best = float("inf")
    for (ax, ay), (bx, by) in zip(poly, poly[1:] + poly[:1], strict=True):
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy or 1e-12
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
        best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
    return best


def pad_at(d: kicadgen.Design, ref: str, number: str) -> tuple[float, float]:
    """A placed pad's centre on the front copper, as the generator places it (P1: never by hand)."""
    box = next(b for b in d.pad_boxes() if b.ref == ref and b.number == number and b.layer == "F.Cu")
    return (round((box.x1 + box.x2) / 2, 4), round((box.y1 + box.y2) / 2, 4))


def ring(r0: float, r1: float, a0: float, a1: float, n: int = 48) -> list[tuple[float, float]]:
    """An annular sector from radius r0 to r1, screen angles a0 to a1: a simple polygon."""
    outer = [polar(r1, a0 + (a1 - a0) * i / n) for i in range(n + 1)]
    inner = [polar(r0, a1 - (a1 - a0) * i / n) for i in range(n + 1)]
    return outer + inner


class RingDesign(kicadgen.Design):
    """A Design whose board is the ring: an outer circle with three windows round a hub.

    The generator knows rectangles; this class gives it the ring's edge (Edge.Cuts), the test it uses
    for "on the board" (vias, parts, stitching), the router's outer boundary (the windows reach it as
    keep-outs, `build()`), the back's artwork, and the stackup's colours.
    """

    def outline_polygon(self, inset: float = 0.0, n: int = 8) -> list[tuple[float, float]]:
        return [polar(R_OUT - inset, -360.0 * i / 144) for i in range(144)]

    def inside_outline(self, x: float, y: float, margin: float = 0.0) -> bool:
        if math.hypot(x - CX, y - CY) > R_OUT - margin:
            return False
        for k in range(3):
            poly = window(k)[1]
            if _inside(poly, x, y) or _dist(poly, x, y) < margin:
                return False
        return True

    def routing_layers(self) -> list[str]:
        # The back is a whole ground pour: no track there, so the art's gold reads on unbroken copper.
        return [layer for layer in super().routing_layers() if layer != "B.Cu"]

    @staticmethod
    def _stackup(copper: list[str], thickness: float = 1.6) -> list:
        Q = kicadgen.Q
        out = kicadgen.Design._stackup(copper, thickness)
        # The masks are black. Under KiCad's named "Black" the renders show the ground pour brown;
        # this one is 95 % opaque. The fab's job file reads it as R11G11B12: order black.
        black = "#0B0B0CF2"
        colours = {"F.SilkS": "White", "B.SilkS": "White", "F.Mask": black, "B.Mask": black}
        for item in out[1:]:
            if item[0] == "layer" and item[1] in colours:
                item.insert(3, ["color", Q(colours[item[1]])])
            if item[0] == "copper_finish":
                item[1] = Q("ENIG")
        return out

    def _edge_cuts(self, ns: uuid.UUID) -> list:
        """The Edge.Cuts graphics (the outer circle, the three windows' arcs and lines), and the
        artwork on the silkscreens and the back's mask, which the generator has no call for."""
        fmt, Q, uid = kicadgen.fmt, kicadgen.Q, kicadgen.uid

        def stroke(w: float = 0.1) -> list:
            return ["stroke", ["width", fmt(w)], ["type", "solid"]]

        items: list = [
            ["gr_circle", ["center", fmt(CX), fmt(CY)], ["end", fmt(CX + R_OUT), fmt(CY)], stroke(), ["fill", "no"],
             ["layer", Q("Edge.Cuts")], ["uuid", uid(ns, "edge/outer")]]
        ]  # fmt: skip
        for k in range(3):
            for i, prim in enumerate(window(k)[0]):
                if prim[0] == "line":
                    a, b = prim[1], prim[2]
                    items.append(["gr_line", ["start", fmt(a[0]), fmt(a[1])], ["end", fmt(b[0]), fmt(b[1])], stroke(),
                                  ["layer", Q("Edge.Cuts")], ["uuid", uid(ns, f"edge/w{k}/{i}")]])  # fmt: skip
                else:
                    s, m, e = prim[1:]
                    items.append(["gr_arc", ["start", fmt(s[0]), fmt(s[1])], ["mid", fmt(m[0]), fmt(m[1])],
                                  ["end", fmt(e[0]), fmt(e[1])], stroke(), ["layer", Q("Edge.Cuts")],
                                  ["uuid", uid(ns, f"edge/w{k}/{i}")]])  # fmt: skip
        return items + art(ns, self)


# ---- the artwork -----------------------------------------------------------------------------------
WAVE_R = 22.0  # the back's two waves circle the ring here, outside the driver's 20 mm frame
WAVE_A = 1.3
WAVE_N = 20  # cycles from start to end
# They start beside the line-in jack's inner peg hole (22.55 mm out at 180 degrees, on their radius)
# and come round to its other side as one line.
WAVE_FROM, WAVE_SWEEP = 185.0, 350.0
WAVE_CLEAR = 0.45  # no via within this of either wave: the keep-out that follows them (wave_band)

# The back's lettering round the outside, between the holes: text, radius, centre angle, size,
# stroke, spacing. BACK_TEXT is each line's via keep-out: its name, radius, size, centre and half-span.
BACK_LINES = [
    ("HUSH  v0.1", 27.4, 124.0, 1.6, 0.25, 1.1),
    ("NOISE + ITS INVERSE = SILENCE", 27.4, 210.0, 1.0, 0.16, 0.9),
    ("DESIGNED IN PYTHON WITH VIA", 27.4, 330.0, 1.0, 0.16, 0.9),
]
BACK_TEXT = [
    (f"lettering {i + 1}", r, size, at, math.degrees((size * sp * (len(text) - 1) / 2 + size * 0.6) / r))
    for i, (text, r, at, size, _, sp) in enumerate(BACK_LINES)
]


def wave_env(t: float) -> float:
    """The waves' height at t, 0 at the start to 1 at the end: full, shrinking to nothing."""
    return WAVE_A * (1.0 - t) ** 1.6


def wave_band(n: int = 140) -> list[tuple[float, float]]:
    """The band both waves fill, grown by WAVE_CLEAR: a via keep-out on the back."""
    ts = [i / n for i in range(n + 1)]
    outer = [polar(WAVE_R + wave_env(t) + WAVE_CLEAR, WAVE_FROM + WAVE_SWEEP * t) for t in ts]
    inner = [polar(WAVE_R - wave_env(t) - WAVE_CLEAR, WAVE_FROM + WAVE_SWEEP * t) for t in reversed(ts)]
    return outer + inner


def art(ns: uuid.UUID, d: kicadgen.Design) -> list:
    """The back: the noise and its inverse circling the ring, shrinking to one quiet line, in white;
    gold rims round the edge, the windows and the mic's port, where the mask opens on the pour."""
    fmt, Q, uid = kicadgen.fmt, kicadgen.Q, kicadgen.uid
    out: list = []

    def line(a, b, layer, w, key):
        out.append(["gr_line", ["start", fmt(a[0]), fmt(a[1])], ["end", fmt(b[0]), fmt(b[1])],
                    ["stroke", ["width", fmt(w)], ["type", "solid"]], ["layer", Q(layer)], ["uuid", uid(ns, key)]])  # fmt: skip

    def circle(c, r, layer, w, key):
        out.append(["gr_circle", ["center", fmt(c[0]), fmt(c[1])], ["end", fmt(c[0] + r), fmt(c[1])],
                    ["stroke", ["width", fmt(w)], ["type", "solid"]], ["fill", "no"], ["layer", Q(layer)],
                    ["uuid", uid(ns, key)]])  # fmt: skip

    def arc_text(text: str, r: float, at: float, layer: str, size: float, thick: float, key: str,
                 spacing: float = 0.9) -> None:
        """Text set along the ring, centred on screen angle `at`: across the top it reads clockwise,
        across the bottom it stands upright and reads counter-clockwise. On the back it is laid out as
        the back is seen (mirrored left to right) and written mirrored, so it reads from behind."""
        back = layer.startswith("B.")
        view_at = (180.0 - at) % 360.0 if back else at % 360.0
        lower = 0.0 < view_at < 180.0
        adv = size * spacing
        half = adv * (len(text) - 1) / 2
        for i, ch in enumerate(text):
            if ch == " ":
                continue
            s = (half - i * adv) if lower else (-half + i * adv)
            th = view_at + math.degrees(s / r)
            x, y = polar(r, th)
            angle = (90.0 - th) if lower else (270.0 - th)
            if back:
                x, angle = 2 * CX - x, -angle
            effects = ["effects", ["font", ["size", fmt(size), fmt(size)], ["thickness", fmt(thick)]]]
            if back:
                effects.append(["justify", "mirror"])
            out.append(["gr_text", Q(ch), ["at", fmt(x), fmt(y), fmt(angle % 360.0)], ["layer", Q(layer)],
                        ["uuid", uid(ns, f"{key}/{i}")], effects])  # fmt: skip

    # The front: the name in the open arc south-west, and a word at each thing a hand touches.
    arc_text("HUSH", 26.6, 122.0, "F.SilkS", 2.6, 0.4, "label/hush", spacing=1.25)
    arc_text("ACTIVE NOISE CANCELLING", 22.9, 122.0, "F.SilkS", 0.8, 0.14, "label/sub")
    arc_text("5V", 22.6, 90.0, "F.SilkS", 0.9, 0.15, "label/usb")
    arc_text("LINE IN", 20.0, 202.0, "F.SilkS", 0.9, 0.15, "label/line")
    arc_text("ANC", 24.2, 0.0, "F.SilkS", 1.0, 0.16, "label/anc")
    arc_text("ON", 29.5, 345.0, "F.SilkS", 0.8, 0.14, "label/led")  # D1 lights while it cancels
    arc_text("DEPTH", 24.6, 290.0, "F.SilkS", 0.8, 0.14, "label/depth")  # inside the trimmer
    arc_text("SPEAKER", 27.4, 42.0, "F.SilkS", 0.8, 0.14, "label/spk")
    # The speaker's polarity, upright on the line through each pad: wired the other way round, the
    # loop's feedback turns positive.
    for text, at, key in (("+", 39.0, "label/spk+"), ("-", 48.7, "label/spk-")):
        x, y = polar(22.6, at)
        out.append(["gr_text", Q(text), ["at", fmt(x), fmt(y), "0"], ["layer", Q("F.SilkS")], ["uuid", uid(ns, key)],
                    ["effects", ["font", ["size", "1.1", "1.1"], ["thickness", "0.2"]]]])  # fmt: skip
    # The back: what it is, round the outside between the holes.
    for (text, r, at, size, thick, sp), key in zip(BACK_LINES, ("back/name", "back/motto", "back/via"), strict=True):
        arc_text(text, r, at, "B.SilkS", size, thick, key, spacing=sp)

    # Every hole through the board, which the silkscreen must keep clear of.
    holes = []
    for b in d.pad_boxes():
        if b.kind in ("thru_hole", "np_thru_hole") and b.layer == "B.Cu":
            holes.append(((b.x1 + b.x2) / 2, (b.y1 + b.y2) / 2, max(b.x2 - b.x1, b.y2 - b.y1) / 2 + 0.35))

    def clear(p) -> bool:
        return all(math.hypot(p[0] - hx, p[1] - hy) > hr for hx, hy, hr in holes)

    # The waves: the noise (0.25 mm) and the anti-noise (0.15 mm) start beside the jack at full height
    # and shrink together round the ring until they meet as one line: noise plus its inverse is
    # silence.
    steps = 1440
    for name, sign, w in (("noise", 1.0, 0.25), ("anti", -1.0, 0.15)):
        pts = []
        for i in range(steps + 1):
            t = i / steps
            r = WAVE_R + sign * wave_env(t) * math.sin(2 * math.pi * WAVE_N * t)
            pts.append(polar(r, WAVE_FROM + WAVE_SWEEP * t))
        for i in range(steps):
            if clear(pts[i]) and clear(pts[i + 1]):
                line(pts[i], pts[i + 1], "B.SilkS", w, f"art/{name}/{i}")
    # Gold rims: the mask opens in a band over the back's ground pour, round the edge, along each
    # window's arc over the cone, and round the mic's port. The spokes and the hub stay black: vias
    # may stand there. The edge's rim breaks where a hole comes within 0.3 mm of it (the USB-C
    # shell's slots, the jack's outer peg); 2 breaks less than 12 degrees apart are one.
    r_rim = R_OUT - EDGE - 0.2 - RIM / 2
    gaps = []
    for b in d.pad_boxes():
        if b.kind in ("thru_hole", "np_thru_hole") and b.layer == "B.Cu":
            hx, hy = (b.x1 + b.x2) / 2, (b.y1 + b.y2) / 2
            hr = max(b.x2 - b.x1, b.y2 - b.y1) / 2
            if abs(math.hypot(hx - CX, hy - CY) - r_rim) - RIM / 2 < hr + 0.3:
                at = math.degrees(math.atan2(hy - CY, hx - CX)) % 360.0
                half = math.degrees((hr + 0.3 + RIM / 2) / r_rim)
                gaps.append([at - half, at + half])
    gaps.sort()
    merged: list[list[float]] = []
    for g0, g1 in gaps:
        if merged and g0 - merged[-1][1] < 12.0:
            merged[-1][1] = max(merged[-1][1], g1)
        else:
            merged.append([g0, g1])
    if not merged:
        circle((CX, CY), r_rim, "B.Mask", RIM, "art/rim/outer")
    for i, (g0, g1) in enumerate(merged):
        a0, a1 = g1, merged[(i + 1) % len(merged)][0] + (360.0 if i == len(merged) - 1 else 0.0)
        s, m, e = polar(r_rim, a0), polar(r_rim, (a0 + a1) / 2), polar(r_rim, a1)
        out.append(["gr_arc", ["start", fmt(s[0]), fmt(s[1])], ["mid", fmt(m[0]), fmt(m[1])],
                    ["end", fmt(e[0]), fmt(e[1])], ["stroke", ["width", fmt(RIM)], ["type", "solid"]],
                    ["layer", Q("B.Mask")], ["uuid", uid(ns, f"art/rim/outer/{i}")]])  # fmt: skip
    for k in range(3):
        s, m, e = window(k, grow=EDGE + 0.2 + RIM / 2)[0][2][1:]
        out.append(["gr_arc", ["start", fmt(s[0]), fmt(s[1])], ["mid", fmt(m[0]), fmt(m[1])],
                    ["end", fmt(e[0]), fmt(e[1])], ["stroke", ["width", fmt(RIM)], ["type", "solid"]],
                    ["layer", Q("B.Mask")], ["uuid", uid(ns, f"art/rim/w{k}")]])  # fmt: skip
    circle((CX, CY), PORT_RIM, "B.Mask", RIM, "art/rim/port")
    return out


def window_arc(k: int) -> tuple[float, float]:
    """The screen angles where window k's arc over the cone starts and ends."""
    s, _, e = window(k)[0][2][1:]
    a0 = math.degrees(math.atan2(s[1] - CY, s[0] - CX)) % 360.0
    a1 = math.degrees(math.atan2(e[1] - CY, e[0] - CX)) % 360.0
    return (a0, a1 if a1 > a0 else a1 + 360.0)


# ---- footprints --------------------------------------------------------------------------------------
R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
SOT23_5 = "Package_TO_SOT_SMD:SOT-23-5"
TOP = "F.Cu"

# Where each symbol sits on the sheet (A3): x, y in 2.54 mm steps, angle counter-clockwise. The signal
# runs left to right: power along the top; the mic, the error amplifier, the controller and the
# amplifier across the middle; the line input and the switch along the bottom.
SCHEMATIC = {
    # USB-C, its CC pull-downs, +5V's bulk; the LDO behind its RC filter; +2V8's caps; VREF
    "J1": (12, 20, 0), "R1": (22, 26, 0), "R2": (25, 26, 0), "C1": (29, 20, 0), "C2": (32, 20, 0),
    "R25": (37, 20, 0), "C3": (42, 20, 0), "U1": (52, 18, 0), "C4": (60, 20, 0), "C5": (63, 20, 0),
    "R3": (70, 18, 0), "R4": (70, 27, 0), "C6": (74, 26, 0),
    # the mic, its supply filter, its coupling into the error amplifier
    "MIC1": (14, 52, 0), "R5": (14, 43, 0), "C7": (18, 40, 0),
    "C8": (22, 51, 90), "R6": (29, 51, 90), "C9": (22, 56, 90), "R7": (29, 56, 90),
    # the error amplifier: the + leg's shelf above it, the - leg's below, the music reference on each
    "U2": (40, 54, 0), "C14": (46, 47, 0),
    "R10": (33, 46, 180), "R11": (36, 46, 180), "C11": (36, 39, 180),
    "R8": (40, 62, 90), "R9": (36, 66, 90), "C10": (42, 66, 90),
    "R12": (23, 46, 90), "C12": (29, 46, 90), "R13": (23, 62, 90), "C13": (29, 62, 90),
    # the controller: coupling, depth, lead, integrator, its switch
    "C15": (54, 54, 90), "RV1": (61, 54, 90), "R14": (67, 54, 90), "R15": (73, 54, 90), "C16": (73, 50, 90),
    "U3": (82, 56, 0), "C19": (90, 49, 0), "C17": (82, 64, 90), "R16": (82, 68, 90),
    "U4": (84, 78, 0), "C18": (94, 73, 0),
    # the amplifier and the speaker
    "C20": (96, 56, 90), "R17": (104, 56, 90), "U5": (116, 58, 0), "J3": (126, 57, 0),
    "C21": (96, 62, 90), "R18": (104, 62, 90), "R19": (108, 70, 0), "C22": (112, 70, 0),
    # line in, mixed to mono
    "J2": (12, 84, 0), "R20": (20, 86, 90), "R21": (20, 90, 90), "R22": (26, 92, 0),
    # the ANC switch, its pull-down and the LED
    "SW1": (62, 88, 0), "R23": (54, 92, 0), "D1": (52, 84, 0), "R24": (58, 80, 90),
    # the mounting holes
    "H1": (136, 90, 0), "H2": (140, 90, 0), "H3": (144, 90, 0),
}


def build() -> kicadgen.Design:
    d = RingDesign(
        name=NAME,
        namespace=NS,
        outline=(CX - R_OUT, CY - R_OUT, CX + R_OUT, CY + R_OUT),
        sheet="A3",
        track_width=0.2,
        clearance=0.15,
        edge_clearance=EDGE,
        via_size=0.5,
        via_drill=0.3,
        copper_layers=4,
        plane_layers=("In1.Cu",),
        title="",
    )
    d.power_nets = {"GND": "GND", "+5V": "+5V", "+2V8": "+2V8", "VREF": "VCOM", "MIC_VDD": "VDD", "LDO_IN": "+5VA"}
    # USB brings +5V and GND on a connector; VREF is a divider; MIC_VDD and LDO_IN are rails behind an RC
    # filter (R5/C7, R25/C3). +2V8 has U1's output.
    d.flagged_nets = ["GND", "+5V", "VREF", "MIC_VDD", "LDO_IN"]
    d.net_classes = {
        "power": {"width": 0.4, "clearance": 0.15, "via": 0.6, "via_drill": 0.3, "nets": ["+5V", "SPK_P", "SPK_N"]},
        "rail": {"width": 0.3, "clearance": 0.15, "via": 0.5, "via_drill": 0.3, "nets": ["+2V8", "LDO_IN"]},
    }
    d.check_pulls = True
    d.defined_nets = {
        "EA_N": "U2's inverting input, held by its own feedback: R8 (2.2M) to its output",
        "CT_N": "U3's inverting input, held by its own feedback: R16 (10M) to its output",
        "AMP_INP": "the PAM8302A's 10k input resistor to its internal VDD/2 node (datasheet, block diagram)",
        "AMP_INN": "the PAM8302A's 10k input resistor to its internal VDD/2 node (datasheet, block diagram)",
    }
    d.check_sim = True

    parts: dict[str, kicadgen.Part] = {}

    def add(ref, lib, value, fp, at, rot, nets, layer=TOP):
        parts[ref] = d.add(ref, lib, value, fp, sch_at=(0.0, 0.0), pcb_at=at, pcb_rot=rot, pcb_layer=layer, nets=nets)

    def r(ref, value, a, b, at, rot, fp=R0402):
        add(ref, "Device:R", value, fp, at, rot, {"1": a, "2": b})

    def c(ref, value, a, b, at, rot, fp=C0402):
        add(ref, "Device:C", value, fp, at, rot, {"1": a, "2": b})

    # Every part sits on one of four tracks round the ring, in blocks the way the signal flows: the
    # error amplifier west of the mic's spoke, the controller east of it, power and the ANC switch on
    # the east edge, the amplifier with the speaker's pads south-east, the line input west. A part
    # along a track is turned with it (tangential); TA..TD are the tracks' radii.
    TA, TB, TC, TD = 18.9, 21.3, 24.2, 27.6

    def along(deg: float) -> float:
        return facing(deg)

    def across(deg: float) -> float:
        return facing(deg) + 90.0

    # ---- power: USB-C at the south edge, the LDO east ------------------------------------------------
    add("J1", "Connector:USB_C_Receptacle_PowerOnly_6P", "USB-C 5V", "Connector_USB:USB_C_Receptacle_GCT_USB4125-xx-x_6P_TopMnt_Horizontal",
        polar(R_OUT - 2.8, 90.0), facing(90.0), {"A9": "+5V", "B9": "+5V", "A12": "GND", "B12": "GND", "SH": "GND", "A5": "CC1", "B5": "CC2"})  # fmt: skip
    r("R1", "5.1k", "CC1", "GND", polar(TB, 96.0), along(96.0))
    r("R2", "5.1k", "CC2", "GND", polar(TB, 84.0), along(84.0))
    add("U1", "Regulator_Linear:LP5907MFX-2.8", "LP5907-2.8", SOT23_5, polar(TC, 14.0), facing(14.0),
        {"1": "LDO_IN", "3": "LDO_IN", "2": "GND", "5": "+2V8"})
    r("R25", "10", "+5V", "LDO_IN", polar(TD, 20.0), along(20.0))
    c("C3", "1u", "LDO_IN", "GND", polar(TD, 12.0), along(12.0))
    c("C4", "1u", "+2V8", "GND", polar(TA, 10.0), along(10.0))
    c("C5", "10u", "+2V8", "GND", polar(TA + 0.6, 19.0), along(19.0), fp=C0603)

    # ---- the ANC switch on the east edge, the LED that says it is on ----------------------------------
    add("SW1", "Switch:SW_SPDT", "ANC", "Button_Switch_SMD:SW_SPDT_PCM12", polar(R_OUT - 2.6, 0.0), facing(0.0),
        {"1": "+2V8", "2": "ANC_OFF", "3": "GND"})
    r("R23", "100k", "ANC_OFF", "GND", polar(TB, 352.0), along(352.0))
    r("R24", "470", "+2V8", "LED_A", polar(TB, 345.0), along(345.0))
    add("D1", "Device:LED", "red", "LED_SMD:LED_0603_1608Metric", polar(TD, 345.0), along(345.0),
        {"2": "LED_A", "1": "ANC_OFF"})

    # ---- the hub: the mic with its port on the cone's axis -------------------------------------------
    # The footprint's port is 0.68 mm from its origin along +x; turned 270, its pads face north up the
    # spoke and the port lands on (CX, CY).
    add("MIC1", "Sensor_Audio:IM73A135V01", "IM73A135V01", "Sensor_Audio:Infineon_PG-LLGA-5-2", (CX, CY - 0.68), 270.0,
        {"1": "MIC_P", "2": "MIC_VDD", "3": "MIC_N", "4": "GND", "5": "GND"})
    c("C7", "1u", "MIC_VDD", "GND", (CX + 0.7, CY - 4.2), 90.0)  # on the spoke's root, by the mic's VDD pin
    # The hub's ground (the mic's sealing ring, its ground pad, C7) reaches the plane through 2 vias on
    # the hub south of the mic; the spoke's tracks cut its top pour off from the ring's.
    hub_vias = [(CX, CY + 3.0), (CX - 1.6, CY + 2.6)]
    r("R5", "100", "+2V8", "MIC_VDD", polar(TA, 278.0), along(278.0))

    # ---- the error amplifier, west of the spoke -------------------------------------------------------
    c("C8", "2.2u", "MIC_P", "EA_INP", polar(TA, 262.0), along(262.0))
    r("R6", "30k", "EA_INP", "EA_P", polar(TA, 254.0), along(254.0))
    c("C9", "2.2u", "MIC_N", "EA_INN", polar(TB, 262.0), along(262.0))
    r("R7", "30k", "EA_INN", "EA_N", polar(TB, 254.0), along(254.0))
    add("U2", "Amplifier_Operational:TLV9061xDBV", "TLV9061", SOT23_5, polar(TC, 244.0), facing(244.0),
        {"3": "EA_P", "4": "EA_N", "1": "EA_OUT", "5": "+2V8", "2": "GND"})
    c("C14", "100n", "+2V8", "GND", polar(TD, 254.0), along(254.0))
    # the - leg: R8, and R9 with C10 (the shelf)
    r("R8", "2.2M", "EA_N", "EA_OUT", polar(TA, 246.0), along(246.0))
    r("R9", "150k", "EA_N", "EA_FBN", polar(TA, 238.0), along(238.0))
    c("C10", "47n", "EA_FBN", "EA_OUT", polar(TA + 0.6, 230.0), along(230.0), fp=C0603)
    # the + leg: R10, and R11 with C11
    r("R10", "2.2M", "EA_P", "VREF", polar(TD, 246.0), along(246.0))
    r("R11", "150k", "EA_P", "EA_FBP", polar(TD, 238.0), along(238.0))
    c("C11", "47n", "EA_FBP", "VREF", polar(TD, 230.0), along(230.0), fp=C0603)
    # the music reference: R12 and C12 into the + leg, R13 and C13 the matching - leg
    r("R12", "56k", "MUSIC", "REF_P", polar(TB, 230.0), along(230.0))
    c("C12", "15n", "REF_P", "EA_P", polar(TB, 238.0), along(238.0))
    r("R13", "56k", "VREF", "REF_N", polar(TA, 214.0), along(214.0))
    c("C13", "15n", "REF_N", "EA_N", polar(TA, 222.0), along(222.0))
    # VREF, on the spoke's east side, between the two amplifiers
    r("R3", "100k", "+2V8", "VREF", polar(TB, 286.0), along(286.0))
    r("R4", "100k", "VREF", "GND", polar(TA, 286.0), along(286.0))
    c("C6", "10u", "VREF", "GND", polar(TB, 278.0), along(278.0), fp=C0603)

    # ---- the controller, east of the spoke --------------------------------------------------------------
    c("C15", "10u", "EA_OUT", "CT_IN", polar(TC, 280.0), along(280.0), fp=C0603)
    add("RV1", "Device:R_Potentiometer_Trim", "50k DEPTH", "Potentiometer_SMD:Potentiometer_Bourns_TC33X_Vertical",
        polar(TD - 0.4, 290.0), facing(290.0), {"1": "CT_IN", "2": "CT_RV", "3": "CT_RV"})
    r("R14", "6.2k", "CT_RV", "CT_LEAD", polar(TA, 294.0), along(294.0))
    r("R15", "15k", "CT_LEAD", "CT_N", polar(TA, 302.0), along(302.0))
    c("C16", "1.2n", "CT_LEAD", "CT_N", polar(TB, 294.0), along(294.0))
    add("U3", "Amplifier_Operational:TLV9061xDBV", "TLV9061", SOT23_5, polar(TC, 306.0), facing(306.0),
        {"3": "VREF", "4": "CT_N", "1": "CT_OUT", "5": "+2V8", "2": "GND"})
    c("C19", "100n", "+2V8", "GND", polar(TD, 302.0), along(302.0))
    c("C17", "10n", "CT_N", "CT_OUT", polar(TA, 310.0), along(310.0))
    r("R16", "10M", "CT_N", "CT_OUT", polar(TB, 310.0), along(310.0))
    add("U4", "Analog_Switch:TS5A3166DCKR", "TS5A3166", "Package_TO_SOT_SMD:SOT-353_SC-70-5", polar(TC, 320.0), facing(320.0),
        {"1": "CT_N", "2": "CT_OUT", "4": "ANC_OFF", "5": "+2V8", "3": "GND"})
    c("C18", "100n", "+2V8", "GND", polar(TD, 320.0), along(320.0))

    # ---- the amplifier, south-east, with the speaker's wires beside its outputs ---------------------------
    c("C20", "2.2u", "CT_OUT", "AMP_INP_C", polar(TA, 46.0), along(46.0))
    r("R17", "20k", "AMP_INP_C", "AMP_INP", polar(TA, 54.0), along(54.0))
    c("C21", "2.2u", "MUSIC", "AMP_INN_C", polar(TB, 46.0), along(46.0))
    r("R18", "20k", "AMP_INN_C", "AMP_INN", polar(TB, 54.0), along(54.0))
    # Square to the board, not along the ring: FreeRouting 1.9.0 reached none of this MSOP's 0.65 mm
    # pins with the part turned 26 degrees, and all of them at 0.
    add("U5", "Amplifier_Audio:PAM8302AAS", "PAM8302A", "Package_SO:MSOP-8_3x3mm_P0.65mm", polar(TC, 64.0), 0.0,
        {"1": "AMP_SD", "3": "AMP_INP", "4": "AMP_INN", "6": "+5V", "7": "GND", "5": "SPK_P", "8": "SPK_N"})
    r("R19", "100k", "+5V", "AMP_SD", polar(TA, 64.0), along(64.0))
    c("C22", "470n", "AMP_SD", "GND", polar(TA, 72.0), along(72.0))
    c("C1", "10u", "+5V", "GND", polar(TD, 64.0), along(64.0), fp=C0805)
    c("C2", "1u", "+5V", "GND", polar(TD, 72.0), along(72.0))
    # The wires drop past the driver's 40 mm frame to its tabs; the pads lie along the ring (+x tangent).
    add("J3", "Connector_Generic:Conn_01x02", "SPEAKER", "Connector_Wire:SolderWire-0.25sqmm_1x02_P4.2mm_D0.65mm_OD1.7mm",
        polar(TC + 0.6, 39.0), (270.0 - 44.0) % 360.0, {"1": "SPK_P", "2": "SPK_N"})

    # ---- line in, west, and its mono mix ----------------------------------------------------------
    add("J2", "Connector_Audio:AudioJack4", "LINE IN", "Connector_Audio:Jack_3.5mm_PJ320D_Horizontal", polar(R_OUT - 6.225, 180.0),
        0.0, {"T": "AUD_L", "R1": "AUD_R", "R2": "GND", "S": "GND"})  # fmt: skip
    r("R20", "10k", "AUD_L", "MUSIC", polar(TB, 161.0), along(161.0))
    r("R21", "10k", "AUD_R", "MUSIC", polar(TB, 154.0), along(154.0))
    r("R22", "47k", "MUSIC", "GND", polar(TB, 147.0), along(147.0))

    # ---- three M2 holes on the spokes' axes ---------------------------------------------------------
    # For button-head screws (ISO 7380): a 3.5 mm pad, which leaves 1 mm of black between it and the
    # back's gold rim.
    for i, deg in enumerate(SPOKES):
        add(f"H{i + 1}", "Mechanical:MountingHole_Pad", "M2", "MountingHole:MountingHole_2.2mm_M2_ISO7380_Pad",
            polar(R_HOLES, deg), 0.0, {"1": "GND"})

    # The silkscreen carries labels a person uses, not 62 references: each part's reference stays on
    # its fab layer (the assembly drawing) and in the BOM.
    for part in parts.values():
        part.hide_ref = True

    # ---- the schematic, as a drawing --------------------------------------------------------------
    d.sch_wires = True
    d.sch_label_nets = ("MUSIC", "ANC_OFF", "EA_OUT", "CT_OUT")
    for ref, (sx, sy, rot) in SCHEMATIC.items():
        parts[ref].sch_at, parts[ref].sch_rot = (sx * g, sy * g), rot
    missing = sorted(set(parts) - set(SCHEMATIC))
    if missing:
        raise ValueError(f"no schematic position for {', '.join(missing)}")

    # ---- 3D bodies KiCad's library does not ship (models/make_models.py) ------------------------------
    d.model("MIC1", "${KIPRJMOD}/models/im73a135.wrl", replace=True)
    d.model("J2", "${KIPRJMOD}/models/jack_pj320d.wrl", replace=True)
    d.model("RV1", "${KIPRJMOD}/models/trimmer_tc33x.wrl", replace=True)
    d.model("J3", "${KIPRJMOD}/models/speaker_wires.wrl", replace=True)

    # ---- how each part simulates (sim/ holds the decks that use them) ---------------------------------
    tlv = {"3": "IN+", "4": "IN-", "5": "VCC", "2": "VEE", "1": "OUT"}
    for ref in ("U2", "U3"):
        d.sim(ref, library="../library/ti/tlv9062.lib", name="TLV9062", pins=tlv)
    d.sim("U5", library="sim/models/pam8302a.lib", name="PAM8302A",
          pins={"1": "SD", "3": "INP", "4": "INN", "6": "VDD", "7": "GND", "5": "OUTP", "8": "OUTN", "2": None})  # fmt: skip
    d.no_sim("J1", "a connector: USB's +5V is the decks' source VP5")
    d.no_sim("J2", "a connector: the decks drive the line input with sources VAUDL and VAUDR")
    d.no_sim("J3", "the speaker's wires: the decks carry the CE40-4's Thiele-Small model in their place")
    d.no_sim("U1", "the decks take +2V8 as a source (VSUP, +-2 %, the LP5907's tolerance)")
    d.no_sim("MIC1", "an acoustic transducer: the decks model its sensitivity, roll-off and outputs from its datasheet")
    d.no_sim("U4", "an analog switch: the decks hold it open, ANC on, as its off capacitances CSWN and CSWO")
    d.no_sim("RV1", "a trimmer: the decks take it at its end stop as a resistor of the same name")
    d.no_sim("SW1", "a switch: the decks run with ANC on")
    d.no_sim("D1", "an indicator LED, not in any deck")
    for ref in ("H1", "H2", "H3"):
        d.no_sim(ref, "a mounting hole")
    d.sim_directives = []

    # ---- areas: the windows, the driver's flange, the gold rims -----------------------------------------
    # Via-free areas (P3 step 4): each window grown by the edge clearance (no copper on any layer); the
    # back's rims, round the edge, the windows and the mic's port (B.Cu only: the router gets them as
    # via keep-outs and still runs tracks on F.Cu and In2.Cu across them).
    for k in range(3):
        d.keepout(window(k, grow=EDGE)[1], layers=("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"), name=f"window {k + 1}", parts=True)
        a0, a1 = window_arc(k)
        d.keepout(ring(R_HOLE, R_HOLE + EDGE + 0.2 + RIM + 0.3, a0, a1, 24), layers=("B.Cu",), name=f"window {k + 1} rim")
    d.keepout(ring(R_OUT - EDGE - 0.2 - RIM - 0.3, R_OUT, 0.0, 180.0), layers=("B.Cu",), name="south rim")
    d.keepout(ring(R_OUT - EDGE - 0.2 - RIM - 0.3, R_OUT, 180.0, 360.0), layers=("B.Cu",), name="north rim")
    d.keepout(d.circle(CX, CY, PORT_RIM + RIM / 2 + 0.3), layers=("B.Cu",), name="port rim")
    # The waves and the lettering on the back cross no via: their bands are via keep-outs the same way.
    d.keepout(wave_band(), layers=("B.Cu",), name="waves")
    for name, r, h, at, half in BACK_TEXT:
        d.keepout(ring(r - h / 2 - 0.25, r + h / 2 + 0.25, at - half, at + half, 24), layers=("B.Cu",), name=name)
    # The two lower spokes carry the ground pour and no track: the hub and its spoke north are the mic's.
    for k, deg in enumerate(SPOKES[1:]):
        u, v = _unit(deg), _unit(deg + 90.0)
        w = SPOKE_W / 2 + 0.1
        r0, r1 = R_HUB + 0.3, R_HOLE + 0.1
        corners = [(r0, -w), (r1, -w), (r1, w), (r0, w)]
        poly = [(CX + a * u[0] + b * v[0], CY + a * u[1] + b * v[1]) for a, b in corners]
        d.keepout(poly, layers=("F.Cu", "In2.Cu"), name=f"spoke {k + 2}")
    # The driver's frame rests on the back from the opening to 20 mm: no part there.
    d.keepout(ring(R_HOLE, R_FLANGE, 0.0, 180.0), layers=("B.Cu",), name="flange south", parts=True, copper=False)
    d.keepout(ring(R_HOLE, R_FLANGE, 180.0, 360.0), layers=("B.Cu",), name="flange north", parts=True, copper=False)

    for x, y in hub_vias:  # probed clear (workcenter inspect probe --via X,Y --net GND)
        d.via("GND", x, y)
    # The mic's sealing ring is its ground pad, and its footprint keeps it out of every pour
    # (zone_connect 0): a track from the ring's south side to the hub's via.
    d.track("GND", [(CX, CY + 0.81), hub_vias[0]], "F.Cu", width=0.3)

    # ---- hand copper: the two long hops the router gave up on --------------------------------------
    # Concentric arcs on In2.Cu, each between 2 vias in the gap between tracks TA and TB or inside the
    # top hole's pad; every via and chord probed clear (workcenter inspect probe). A wall on In2 in its
    # sector: nets that cross it cross on F.Cu, between the parts.
    def arc(r: float, a0: float, a1: float, step: float = 4.0) -> list[tuple[float, float]]:
        n = max(1, round(abs(a1 - a0) / step))
        return [polar(r, a0 + (a1 - a0) * i / n) for i in range(n + 1)]

    # CT_OUT, the anti-noise, from the controller (C17, 309 degrees) clockwise to C20 (47.5 degrees).
    ct_a, ct_b = polar(20.1, 309.0), polar(20.1, 47.5)
    d.via("CT_OUT", *ct_a)
    d.via("CT_OUT", *ct_b)
    d.track("CT_OUT", arc(20.1, 309.0, 407.5), "In2.Cu")
    d.track("CT_OUT", [ct_a, pad_at(d, "C17", "2")], "F.Cu")
    d.track("CT_OUT", [ct_b, pad_at(d, "C20", "1")], "F.Cu")
    # VREF, from C11 west of the spoke across the top, inside H1's pad, to C6 east of it. Both vias
    # stand outside the waves on the back.
    vw, ve = polar(26.3, 226.0), polar(24.4, 274.0)
    d.via("VREF", *vw)
    d.via("VREF", *ve)
    d.track("VREF", [vw, *arc(24.4, 229.0, 274.0)], "In2.Cu")
    d.track("VREF", [vw, pad_at(d, "C11", "2")], "F.Cu")
    d.track("VREF", [ve, pad_at(d, "C6", "1")], "F.Cu")

    # ---- pours ---------------------------------------------------------------------------------------
    d.zone("GND", layers=("In1.Cu",), connect="solid")
    d.zone("GND", layers=("B.Cu",), connect="solid")
    d.zone("GND", layers=("F.Cu",), connect="solid")

    # ---- labels on the front -------------------------------------------------------------------------
    # The mic's land pattern (Infineon's, KiCad's Infineon_PG-LLGA-5-2) seals its 0.8 mm port with a
    # ground ring 0.18 mm from the hole. KiCad's custom rules cannot loosen one item's clearance here
    # (the workcenter raises a rule file to the board's own floor), so the board's floor is 0.18 mm.
    d.rules = {"min_text_height": 0.8, "min_text_thickness": 0.12, "min_hole_clearance": 0.18}
    return d
