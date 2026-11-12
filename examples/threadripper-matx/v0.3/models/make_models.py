"""3D bodies for the parts KiCad's 3D library has none for, for the renders and the STEP export.

    python3 models/make_models.py      # from the board's folder; writes the .wrl files here

Each body is in its footprint's own frame (tools/wrlgen.py's convention): origin at the footprint's
origin, X right, Y toward the footprint's top, Z out of the board, millimetres in, KiCad's VRML unit
out. The sizes come from the makers' drawings named in each function. What sits in a socket or a
slot for the pictures (the processor, 4 memory modules, the M.2 drive) is drawn with its socket and
is not on the BOM.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "tools"))

import wrlgen  # noqa: E402
from wrlgen import MM, Mesh, box, cylinder, prism, rounded_rect  # noqa: E402

sys.path.insert(0, str(HERE.parent))
import mech  # noqa: E402  the board's dimensions, shared with design.py and the footprints

# Colours. The board is black; the metal is dark and light aluminium, the plastics near black.
BLACK = (0.045, 0.047, 0.052)
PLASTIC = (0.09, 0.09, 0.10)
GUNMETAL = (0.20, 0.21, 0.23)
ALU = (0.46, 0.47, 0.50)
ALU_LIGHT = (0.34, 0.35, 0.37)
NICKEL = (0.52, 0.53, 0.55)
STEEL = (0.55, 0.57, 0.60)
GOLD = (0.86, 0.70, 0.30)
COPPER = (0.78, 0.45, 0.25)
DIMM_PCB = (0.05, 0.25, 0.12)
DRAM = (0.06, 0.06, 0.07)
LATCH = (0.78, 0.78, 0.76)
WHITE = (0.92, 0.92, 0.90)
ACCENT = (0.85, 0.42, 0.12)  # a thin copper-orange line on the heatsinks: the only colour on the board


class Part(Mesh):
    """A mesh with its own shine: metal is brighter and sharper than plastic."""

    def __init__(self, color, spec: float = 0.35, shine: float = 0.45, transparency: float = 0.0):
        super().__init__(color, transparency)
        self.spec = spec
        self.shine = shine


def metal(color) -> Part:
    return Part(color, spec=0.45, shine=0.55)


def plastic(color) -> Part:
    return Part(color, spec=0.18, shine=0.25)


def write(name: str, meshes: list[Part], comment: str) -> None:
    """wrlgen.write_wrl with each mesh's own specular colour and shininess."""
    out = ["#VRML V2.0 utf8", f"# make_models: {comment}"]
    for m in meshes:
        if not m.faces:
            continue
        r, g, b = m.color
        s = getattr(m, "spec", 0.35)
        sh = getattr(m, "shine", 0.45)
        clear = f" transparency {m.transparency:.2f}" if m.transparency > 0 else ""
        pts = ", ".join(f"{x * MM:.5f} {y * MM:.5f} {z * MM:.5f}" for x, y, z in m.vertices)
        idx = ", ".join(" ".join(str(i) for i in f) + " -1" for f in m.faces)
        out.append(
            "Shape {\n"
            f"  appearance Appearance {{ material Material {{ diffuseColor {r:.3f} {g:.3f} {b:.3f} "
            f"specularColor {s:.2f} {s:.2f} {s:.2f} shininess {sh:.2f}{clear} }} }}\n"
            "  geometry IndexedFaceSet {\n    solid FALSE\n    creaseAngle 0.5\n"
            f"    coord Coordinate {{ point [ {pts} ] }}\n    coordIndex [ {idx} ]\n  }}\n}}"
        )
    (HERE / name).write_text("\n".join(out) + "\n", encoding="utf-8")


def chamfer_box(m: Mesh, cx: float, cy: float, z0: float, sx: float, sy: float, sz: float, c: float) -> None:
    """A box whose top edges are cut at 45 degrees by c: the soft edge machined heatsinks have."""
    hx, hy = sx / 2, sy / 2
    prism(m, [(cx - hx, cy - hy), (cx + hx, cy - hy), (cx + hx, cy + hy), (cx - hx, cy + hy)], z0, z0 + sz - c)
    lo = [(cx - hx, cy - hy), (cx + hx, cy - hy), (cx + hx, cy + hy), (cx - hx, cy + hy)]
    hi = [(cx - hx + c, cy - hy + c), (cx + hx - c, cy - hy + c), (cx + hx - c, cy + hy - c), (cx - hx + c, cy + hy - c)]
    b = [m.vertex(x, y, z0 + sz - c) for x, y in lo]
    t = [m.vertex(x, y, z0 + sz) for x, y in hi]
    for i in range(4):
        j = (i + 1) % 4
        m.face(b[i], b[j], t[j], t[i])
    m.face(*t)


def fins(m: Mesh, x0: float, x1: float, y0: float, y1: float, z0: float, h: float, n: int, t: float, along_x: bool) -> None:
    """n fins of thickness t, each running along x (or y), spread across the other axis."""
    if along_x:
        step = (y1 - y0 - t) / (n - 1)
        for i in range(n):
            box(m, (x0 + x1) / 2, y0 + t / 2 + i * step, z0, x1 - x0, t, h)
    else:
        step = (x1 - x0 - t) / (n - 1)
        for i in range(n):
            box(m, x0 + t / 2 + i * step, (y0 + y1) / 2, z0, t, y1 - y0, h)




def frame_ring(m: Mesh, w: float, d: float, band: float, z0: float, z1: float) -> None:
    """A rectangular ring w x d whose sides are `band` wide."""
    hw, hd = w / 2, d / 2
    box(m, 0.0, hd - band / 2, z0, w, band, z1 - z0)
    box(m, 0.0, -hd + band / 2, z0, w, band, z1 - z0)
    box(m, -hw + band / 2, 0.0, z0, band, d - 2 * band, z1 - z0)
    box(m, hw - band / 2, 0.0, z0, band, d - 2 * band, z1 - z0)


def str5_socket() -> None:
    """The socket, its rail frame and force frame, and a processor in it. Sizes: the 58.5 x 75.4 mm
    package (sourced); the housing, frames and heat spreader are estimates sized to it."""
    housing, frame, plate, substrate = plastic(BLACK), metal(GUNMETAL), metal(STEEL), Part(DIMM_PCB, 0.3, 0.4)
    ihs, screws, mark = metal(NICKEL), metal(ALU_LIGHT), plastic(GOLD)
    hw, hh = mech.HOUSING
    fw, fh = mech.FRAME
    pw, ph = mech.PACKAGE
    box(housing, 0.0, 0.0, 0.0, hw, hh, 3.2)
    frame_ring(frame, fw, fh, 5.0, 0.0, 4.2)  # the rail frame round the housing
    frame_ring(plate, pw + 7.0, ph + 9.0, 3.6, 5.4, 6.6)  # the force frame, closed over the package
    box(plate, 0.0, ph / 2 + 4.5, 4.2, pw + 7.0, 3.0, 1.2)  # its hinge side
    box(substrate, 0.0, 0.0, 3.2, pw, ph, 1.6)
    chamfer_box(ihs, 0.0, 0.0, 4.8, pw - 3.0, ph - 4.0, 2.6, 0.6)
    box(mark, -pw / 2 + 2.2, ph / 2 - 2.2, 4.8, 1.6, 1.6, 0.05)  # the package's pin 1 triangle, as a pad
    box(metal((0.44, 0.45, 0.47)), 0.0, 0.0, 7.4, pw - 9.0, ph - 12.0, 0.02)  # the lid's brushed field
    for x, y in ((-fw / 2 + 2.5, fh / 2 - 2.5), (fw / 2 - 2.5, fh / 2 - 2.5), (0.0, -fh / 2 + 2.5)):
        cylinder(screws, x, y, 4.2, 2.6, 2.2, 32)  # the 3 Torx screws of the force frame
    write("str5_socket.wrl", [housing, frame, plate, substrate, ihs, screws, mark],
          "sTR5 socket with its frames and a processor")


def ddr5_dimm() -> None:
    """Amphenol DDR516112010E (142 x 6.1 mm, 21.3 mm over its latches) with an RDIMM in it: a
    133.35 x 31.25 mm module (JEDEC MO-329) under a heat spreader. The module is for the pictures."""
    body, latch, pcb, spreader, accent, contacts = plastic(BLACK), plastic(PLASTIC), Part(DIMM_PCB, 0.3, 0.4), metal(GUNMETAL), metal(ACCENT), metal(GOLD)
    box(body, 0.0, 0.0, 0.0, 138.0, 6.1, 7.6)
    for sx in (-1, 1):
        box(latch, sx * 69.4, 0.0, 0.0, 4.2, 6.6, 9.0)
        box(latch, sx * 70.2, 0.0, 9.0, 2.6, 5.4, 12.3)
        box(latch, sx * 68.9, 0.0, 19.0, 2.6, 4.0, 2.3)
    box(pcb, 0.0, 0.0, 3.6, 133.35, 1.27, 31.25)
    box(contacts, 0.0, 0.0, 3.6, 126.0, 1.35, 3.6)
    for sy in (-1, 1):
        chamfer_box(spreader, 0.0, sy * 1.25, 9.0, 128.0, 1.1, 24.0, 0.3)
        box(accent, 0.0, sy * 1.82, 28.6, 120.0, 0.05, 0.9)
    write("ddr5_dimm.wrl", [body, latch, pcb, contacts, spreader, accent], "DDR5 RDIMM slot with a module")


def pcie_x16(armor: bool) -> None:
    """Molex 87715 x16 slot, 89.0 x 7.5 mm, 11.25 mm tall, from peg 1 (the key) at the origin; the
    first slot wears a steel sleeve."""
    body, contacts, latch = plastic(BLACK), metal(GOLD), plastic(PLASTIC)
    x0, x1 = -14.5, 74.5
    cx = (x0 + x1) / 2
    box(body, cx, 0.0, 0.0, x1 - x0, 7.5, 5.2)  # the floor
    for sy in (-1, 1):
        box(body, cx, sy * 2.85, 5.2, x1 - x0, 1.8, 6.05)  # the walls
    box(body, 0.0, 0.0, 5.2, 1.6, 3.9, 4.0)  # the key
    for sx in (x0 + 0.9, x1 - 0.9):
        box(body, sx, 0.0, 5.2, 1.8, 3.9, 6.05)
    for n in range(82):
        x = -11.65 + n if n < 11 else 1.35 + (n - 11)
        for sy in (-1, 1):
            box(contacts, x, sy * 1.7, 5.2, 0.45, 0.5, 3.0)
    box(latch, x1 + 1.2, 0.0, 0.0, 2.4, 6.2, 12.0)
    meshes = [body, contacts, latch]
    if armor:
        sleeve = metal(STEEL)
        for sy in (-1, 1):
            box(sleeve, cx, sy * 3.95, 0.4, x1 - x0 + 1.0, 0.35, 11.0)
            box(sleeve, cx, sy * 3.35, 11.05, x1 - x0 + 1.0, 1.2, 0.35)
        box(sleeve, x0 - 0.35, 0.0, 0.4, 0.35, 8.25, 11.0)
        meshes.append(sleeve)
    write("pcie_x16_armor.wrl" if armor else "pcie_x16.wrl", meshes, "PCIe x16 slot" + (" with a steel sleeve" if armor else ""))


def m2_socket() -> None:
    """Foxconn 2E0BC2x-S64BM (22 x 6.4 mm) with a 2280 drive in it, for the pictures. The drive lies
    toward the footprint's +y, the standoff 78.25 mm away."""
    body, pcb, chips, label = plastic(BLACK), Part((0.04, 0.05, 0.06), 0.3, 0.4), plastic(DRAM), plastic((0.16, 0.16, 0.17))
    box(body, 0.0, 1.0, 0.0, 22.0, 6.4, 6.4)
    y0, y1 = -3.0, -80.5  # the drive's ends in the model's y (up the footprint)
    box(pcb, 0.0, (y0 + y1) / 2, 3.8, 22.0, y0 - y1, 0.8)
    box(chips, 0.0, -14.0, 4.6, 12.0, 12.0, 1.1)
    for yc in (-33.0, -50.0, -67.0):
        box(chips, 0.0, yc, 4.6, 14.0, 12.0, 1.3)
    box(label, 0.0, -50.0, 5.95, 18.0, 46.0, 0.05)
    write("m2_socket.wrl", [body, pcb, chips, label], "M.2 Key M socket with a 2280 drive")


def m2_standoff() -> None:
    post, screw = metal(BRASS_DARK), metal(STEEL)
    cylinder(post, 0.0, 0.0, 0.0, 2.1, 4.6, 24)
    cylinder(screw, 0.0, 0.0, 4.6, 2.0, 1.2, 24)
    write("m2_standoff.wrl", [post, screw], "M.2 standoff and screw")


def csd95490() -> None:
    """TI CSD95490Q5MC: 5 x 6 x 1.0 mm QFN with its clip on top."""
    body, clip = plastic(DRAM), metal(STEEL)
    box(body, 0.0, 0.0, 0.0, 5.0, 6.0, 0.85)
    box(clip, 0.0, 0.0, 0.85, 3.6, 4.6, 0.15)
    write("csd95490q5mc.wrl", [body, clip], "TI CSD95490Q5MC")


def heatsink(name: str) -> None:
    """A heatsink from heatsinks.py: a machined base, fins along its long side, a capping plate and a
    thin copper line, in the frame of its first screw."""
    spec = HEATSINKS[name]
    u0, v0 = spec["holes_uv"][0]
    a, b, c, d = spec["box_uv"]
    x0, x1 = a - u0, c - u0
    y0, y1 = -(d - v0), -(b - v0)  # the model's y points up the board
    base, fin, cap, line, screw = metal(GUNMETAL), metal(GUNMETAL), metal(ALU), metal(ACCENT), metal(ALU_LIGHT)
    z0, z1 = spec["base"], spec["top"]
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    zb = z0 + (z1 - z0) * 0.35
    chamfer_box(base, cx, cy, z0, w, h, zb - z0, 0.8)
    along_x = w >= h
    n = max(6, int((h if along_x else w) / 2.6))
    fins(fin, x0 + 1.0, x1 - 1.0, y0 + 1.0, y1 - 1.0, zb, z1 - zb - 2.0, n, 1.1, along_x)
    if along_x:
        chamfer_box(cap, cx, cy, z1 - 2.0, w, h * 0.42, 2.0, 0.5)
        box(line, cx, cy + h * 0.21 + 0.02, z1 - 1.2, w * 0.9, 0.06, 0.4)
    else:
        chamfer_box(cap, cx, cy, z1 - 2.0, w * 0.42, h, 2.0, 0.5)
        box(line, cx + w * 0.21 + 0.02, cy, z1 - 1.2, 0.06, h * 0.9, 0.4)
    for hx, hy in spec["holes"]:
        cylinder(screw, hx, -hy, z1, 2.4, 0.8, 24)
    meshes = [base, fin, cap, line, screw]
    if name == "Heatsink_VRM_Left":
        # The rear I/O cover: a shell over the connectors from the edge to the fins, stepped down where
        # the cables plug in.
        shroud, slit = metal(GUNMETAL), metal(ACCENT)
        sx0, sx1 = -1.0 - u0, 27.0 - u0
        chamfer_box(shroud, (sx0 + sx1) / 2, cy, 17.0, sx1 - sx0, h, z1 - 17.0, 1.2)
        box(slit, sx1 - 2.0, cy, z1 - 0.2, 0.6, h * 0.86, 0.25)
        grooves = metal((0.10, 0.10, 0.11))
        for k in range(9):  # machined grooves across the cover's top
            box(grooves, (sx0 + sx1) / 2 - 2.0, cy - h * 0.38 + k * h * 0.095, z1 - 0.1, (sx1 - sx0) * 0.7, 0.8, 0.12)
        meshes += [shroud, slit, grooves]
    write(f"{name.lower()}.wrl", meshes, name.replace("_", " "))


def minifit(positions: int) -> None:
    """Molex Mini-Fit Jr 5566 vertical header, 2 rows of `positions` at 4.2 mm, 9.6 mm tall, from pin
    1 at the origin (KiCad's footprint): the housing, a latch on the row-1 side, and a dark cavity
    over each pin. KiCad's 3D library has no body for it."""
    housing, cavity, latch = plastic(PLASTIC), plastic(BLACK), plastic(PLASTIC)
    n = positions // 2
    x0, x1 = -3.05, (n - 1) * 4.2 + 3.05
    y0, y1 = -8.75, 2.6  # the model's y: up the footprint
    box(housing, (x0 + x1) / 2, (y0 + y1) / 2, 0.0, x1 - x0, y1 - y0, 9.6)
    for i in range(n):
        for row in (0.0, -5.5):
            box(cavity, i * 4.2, row, 9.6, 3.4, 3.4, 0.05)
    box(latch, (x0 + x1) / 2, y1 + 0.8, 4.0, 4.0, 1.6, 5.4)
    write(f"minifit_{positions}.wrl", [housing, cavity, latch], f"Molex Mini-Fit Jr 5566, {positions} positions, vertical")


def usb3_stacked() -> None:
    """Molex 48406-0001: 2 USB 3.0 Type-A receptacles stacked, a 15.25 x 17.46 mm steel shell, 15.6 mm
    tall, its face toward the footprint's +y (the board's edge); 2 openings with blue tongues. KiCad's
    3D library has no body for it."""
    shell, mouth, tongue = metal(STEEL), plastic(BLACK), plastic((0.05, 0.25, 0.72))
    x0, x1 = -4.5, 10.75
    yb, yf = 6.02, -11.44  # the back and the face, in the model's y
    cx = (x0 + x1) / 2
    box(shell, cx, (yb + yf) / 2, 0.0, x1 - x0, yb - yf, 15.6)
    for z in (1.8, 9.0):
        box(mouth, cx, yf - 0.03, z, 12.6, 0.06, 5.4)
        box(tongue, cx, yf - 0.05, z + 1.2, 11.0, 0.06, 1.7)
    write("usb3_a_stacked.wrl", [shell, mouth, tongue], "Molex 48406-0001, 2 USB 3.0 Type-A stacked")


def sata_ra() -> None:
    """A host's 7-pin SATA plug, right angle (Adam Tech SATA-A-PL-SMT-K, drawing rev D): a 17.47 mm wide
    body, its shroud 6.15 mm deep and 5.50 tall at the face, a lower block behind it, the dark mouth
    on the face 10.71 mm ahead of pad S4. KiCad's 3D library has none."""
    body, mouth, tongue = plastic(PLASTIC), plastic(BLACK), plastic(GUNMETAL)
    x0, x1 = -8.24, 9.23
    box(body, (x0 + x1) / 2, (10.71 + 4.56) / 2, 0.0, x1 - x0, 10.71 - 4.56, 5.5)
    box(body, (x0 + x1) / 2, (4.56 - 0.79) / 2, 0.0, x1 - x0, 4.56 + 0.79, 2.8)
    box(mouth, (x0 + x1) / 2, 10.74, 0.9, 13.6, 0.06, 3.8)
    box(tongue, (x0 + x1) / 2 - 0.6, 10.76, 2.3, 10.2, 0.06, 1.1)
    write("sata_ra.wrl", [body, mouth, tongue], "SATA 7-pin host plug, right angle")


BRASS_DARK = (0.66, 0.55, 0.30)
from heatsinks import HEATSINKS  # noqa: E402


if __name__ == "__main__":
    str5_socket()
    ddr5_dimm()
    pcie_x16(False)
    pcie_x16(True)
    m2_socket()
    m2_standoff()
    csd95490()
    minifit(8)
    minifit(24)
    sata_ra()
    usb3_stacked()
    for _name in HEATSINKS:
        heatsink(_name)
    print(f"wrote the bodies into {HERE}, with {wrlgen.__name__} and {rounded_rect.__name__} at {math.pi:.2f}")
