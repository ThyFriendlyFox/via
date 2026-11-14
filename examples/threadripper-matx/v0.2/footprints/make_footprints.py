"""The project footprints KiCad's library lacks, written from the makers' drawings into basalt.pretty.

    python3 footprints/make_footprints.py     # from the board's folder; design.py runs it too

| Footprint | Source |
|---|---|
| sTR5_LGA4844 | the package size (58.5 x 75.4 mm, 4844 lands) and the land pitch (0.94 x 0.81 mm, a secondary source); the lands' use from pinmap.py; the housing, frame and cooler holes are estimates |
| DDR5_DIMM_288_SMT | Amphenol DDR516112010E, drawing C-DDR516XXXXXXXX rev 5, sheet 4: 287 pads 0.52 x 1.50 at 0.85 mm, rows 4.10 apart, POS 220 absent |
| PCIe_x16_THT | Molex 87715-9306, drawing SD-87715-901 rev G, sheet 2: 164 holes 0.70 at 1.00 mm in 4 staggered lines; pegs 2.35 (the pad size, 1.00, is an estimate) |
| M2_KeyM_SMT | Foxconn 317-0000-2909 (2E0BC2*-S64BM): 67 pads 0.30 x 1.55 at 0.5 mm, pegs, 2 metal tabs (their y is scaled from the drawing) |
| M2_Standoff | the 2280 standoff 78.25 mm from the connector's pegs, a 4.20 hole in a 6.50 ring |
| CSD95490Q5MC | TI SLPS669A section 9.2: the recommended land pattern (pads 6 and 7 are combs under solder mask; drawn as their copper) |
| MountingHole_ATX | ATX 2.2: a 0.156 in (3.96 mm) hole, here in an 8 mm ground ring |
| Heatsink_* | the board's own heatsinks: screw holes only; the body is in models/ |
| RJ45_JK0654219NL_Edge | KiCad's RJ45_Pulse_JK0654219NL_Horizontal, its legend cut 0.25 mm inside the board edge the jack's face stands past |
"""

from __future__ import annotations

import csv
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import mech  # noqa: E402
import pinmap  # noqa: E402
from fpwriter import Footprint  # noqa: E402

LIB = HERE / "basalt.pretty"
MODELS = "${KIPRJMOD}/models"


def str5_socket(assigned: dict[str, str]) -> Footprint:
    """The socket's lands. A land carries its rail's name (every land of a rail is 1 pin of the
    symbol), its own name when pinmap assigned it a signal, or nothing."""
    fp = Footprint("sTR5_LGA4844", "AMD sTR5 (LGA 4844) socket, 58.5 x 75.4 mm package; land map is a stand-in", smd=True)
    for land in pinmap.lands():
        net = pinmap.land_net(land, assigned)
        num = land.name if land.name in assigned else net
        fp.smd_pad(num, land.u, land.v, 0.42, 0.42, "circle")
    pw, ph = mech.PACKAGE
    hw, hh = mech.HOUSING
    fw, fh = mech.FRAME
    fp.rect(-pw / 2, -ph / 2, pw / 2, ph / 2, "F.Fab", 0.1)
    fp.rect(-hw / 2, -hh / 2, hw / 2, hh / 2, "F.SilkS", 0.15)
    fp.rect(-fw / 2, -fh / 2, fw / 2, fh / 2, "F.SilkS", 0.2)
    # Pin 1: a triangle at the package's top left corner, outside the lands.
    x0, y0 = -hw / 2 + 1.2, -hh / 2 + 1.2
    fp.poly([(x0, y0), (x0 + 4.0, y0), (x0, y0 + 4.0)], "F.SilkS", 0.15, fill=True)
    for dx, dy in mech.COOLER_HOLES:
        fp.npth(dx, dy, 3.8)
    fp.courtyard(-fw / 2 - 0.5, -fh / 2 - 0.5, fw / 2 + 0.5, fh / 2 + 0.5)
    fp.ref_at = (0.0, -fh / 2 - 2.0)
    fp.value_at = (0.0, fh / 2 + 2.0)
    fp.model(f"{MODELS}/str5_socket.wrl")
    return fp


def dimm_pads() -> dict[str, tuple[float, float]]:
    """POS n's pad centre from the connector's centre line: x along the slot, y across. The drawing
    measures from the key, which sits 3.875 mm off centre toward POS 76."""
    out = {}
    for n in range(1, 289):
        if n == 220:
            continue
        k = n if n <= 144 else n - 144
        x = (-4.30 - (75 - k) * 0.85) if k <= 75 else (1.65 + (k - 76) * 0.85)
        out[str(n)] = (round(x + 3.875, 4), 2.05 if n <= 144 else -2.05)
    return out


def ddr5_dimm() -> Footprint:
    fp = Footprint("DDR5_DIMM_288_SMT", "DDR5 RDIMM socket, Amphenol DDR516112010E, SMT, 0.85 mm pitch", smd=True)
    for num, (x, y) in dimm_pads().items():
        fp.smd_pad(num, x, y, 0.52, 1.50, "rect")
    key = 3.875
    # The key slot and the metal-tab boardlocks are plated slots across the rows.
    for x in (key, key - 72.85, key + 65.10):
        fp.tht_pad("MP", x, 0.0, 1.70, 1.20, "oval", pad_h=2.95, drill_h=2.45)
    fp.rect(-71.0, -3.05, 71.0, 3.05, "F.Fab", 0.1)
    for y in (-3.25, 3.25):
        fp.line(-71.0, y, 71.0, y, "F.SilkS", 0.15)
    for x in (-71.0, 71.0):
        fp.line(x, -3.25, x, 3.25, "F.SilkS", 0.15)
    fp.courtyard(-71.5, -3.5, 71.5, 3.5)
    fp.ref_at = (0.0, -4.5)
    fp.value_at = (0.0, 4.5)
    fp.model(f"{MODELS}/ddr5_dimm.wrl")
    return fp


def pcie_pins() -> dict[str, tuple[float, float]]:
    """A and B pin n from peg 1 (the key): x along the slot, y across; A odd at -1.25, A even at
    -3.25, B odd at +1.25, B even at +3.25. Pins 1-11 sit before the key, 12-82 after it."""
    out = {}
    for n in range(1, 83):
        x = -11.65 + (n - 1) if n <= 11 else 1.35 + (n - 12)
        out[f"A{n}"] = (round(x, 4), -1.25 if n % 2 else -3.25)
        out[f"B{n}"] = (round(x, 4), 1.25 if n % 2 else 3.25)
    return out


def pcie_x16() -> Footprint:
    fp = Footprint("PCIe_x16_THT", "PCI Express x16 slot, Molex 87715-9306, through hole, 1.00 mm pitch")
    for num, (x, y) in pcie_pins().items():
        fp.tht_pad(num, x, y, 1.0, 0.7, "rect" if num == "A1" else "circle")
    fp.npth(0.0, 0.0, 2.35)
    fp.npth(73.15, 0.0, 2.35)
    x0, x1 = -14.5, 74.5
    fp.rect(x0, -3.75, x1, 3.75, "F.Fab", 0.1)
    for y in (-3.95, 3.95):
        fp.line(x0, y, x1, y, "F.SilkS", 0.15)
    for x in (x0, x1):
        fp.line(x, -3.95, x, 3.95, "F.SilkS", 0.15)
    fp.courtyard(x0 - 0.5, -4.25, x1 + 0.5, 4.25)
    fp.ref_at = (x0 - 3.0, 0.0)
    fp.value_at = (30.0, 5.5)
    fp.model(f"{MODELS}/pcie_x16.wrl")
    return fp


def m2_pads() -> dict[str, tuple[float, float]]:
    """Pin n's pad centre from the pegs' centre: odd pins in the row at -5.275 (pin 1 at x -9.25),
    even pins at +2.275 (pin 2 at -9.0); positions 59-66 are the key M gap."""
    out = {}
    for n in range(1, 76):
        if 59 <= n <= 66:
            continue
        x = -9.25 + (n - 1) * 0.25
        out[str(n)] = (round(x, 4), -5.275 if n % 2 else 2.275)
    return out


def m2_key_m() -> Footprint:
    fp = Footprint("M2_KeyM_SMT", "M.2 Key M socket, Foxconn 2E0BC2x-S64BM (6.4 mm), 0.5 mm pitch", smd=True)
    for num, (x, y) in m2_pads().items():
        fp.smd_pad(num, x, y, 0.30, 1.55, "rect")
    fp.npth(-10.0, 0.0, 1.10)
    fp.npth(10.0, 0.0, 1.60)
    for x in (-10.35, 10.35):
        fp.smd_pad("MP", x, -4.50, 1.20, 2.75, "rect")
    fp.rect(-11.0, -3.6, 11.0, 2.8, "F.Fab", 0.1)
    fp.line(-11.2, 3.4, 11.2, 3.4, "F.SilkS", 0.15)
    fp.courtyard(-11.5, -6.6, 11.5, 3.6)
    fp.ref_at = (0.0, 4.6)
    fp.value_at = (0.0, -7.6)
    fp.model(f"{MODELS}/m2_socket.wrl")
    return fp


def m2_standoff() -> Footprint:
    fp = Footprint("M2_Standoff", "M.2 standoff: a 4.20 hole in a 6.50 ground ring")
    fp.tht_pad("1", 0.0, 0.0, 6.5, 4.2)
    fp.circle(0.0, 0.0, 3.6, "F.SilkS", 0.12)
    fp.courtyard(-3.75, -3.75, 3.75, 3.75)
    fp.ref_at = (0.0, -5.0)
    fp.model(f"{MODELS}/m2_standoff.wrl")
    return fp


def csd95490() -> Footprint:
    fp = Footprint("CSD95490Q5MC", "TI CSD95490Q5MC smart power stage, 5 x 6 mm, SLPS669A land pattern", smd=True)
    with (HERE / "csd95490q5mc_land.csv").open(encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            x, y, w, h = (float(row[k]) for k in ("x", "y", "w", "h"))
            fp.smd_pad(row["pad"], x, y, w, h, row["shape"], rratio=0.2)
    fp.rect(-2.5, -3.0, 2.5, 3.0, "F.Fab", 0.1)
    fp.line(-2.75, -3.2, -1.5, -3.2, "F.SilkS", 0.15)
    fp.circle(-3.1, -3.2, 0.15, "F.SilkS", 0.3, fill=True)
    fp.courtyard(-3.0, -3.45, 3.0, 3.45)
    fp.ref_at = (0.0, -4.2)
    fp.value_at = (0.0, 4.2)
    fp.model(f"{MODELS}/csd95490q5mc.wrl")
    return fp


def mounting_hole() -> Footprint:
    fp = Footprint("MountingHole_ATX", "ATX/microATX mounting hole, 0.156 in (3.96 mm), 8 mm ground ring")
    fp.tht_pad("1", 0.0, 0.0, 8.0, 3.96)
    fp.circle(0.0, 0.0, 4.25, "F.SilkS", 0.12)
    fp.courtyard(-4.5, -4.5, 4.5, 4.5)
    fp.ref_at = (0.0, -5.5)
    return fp


def heatsink(name: str, holes: list[tuple[float, float]], descr: str) -> Footprint:
    """A heatsink as the board sees it: the screws' plated holes, each in a small courtyard. Its body
    stands over the parts it cools, which the courtyards leave free."""
    fp = Footprint(name, descr)
    for x, y in holes:
        fp.tht_pad("1", x, y, 4.8, 2.7)
        fp.courtyard(x - 2.6, y - 2.6, x + 2.6, y + 2.6)
    fp.ref_at = holes[0]
    fp.ref_layer = "F.Fab"
    fp.model(f"{MODELS}/{name.lower()}.wrl")
    return fp


def rj45_at_edge(face: float = 25.01) -> Path:
    """KiCad's footprint of the Pulse jack with its legend cut at the board edge. The jack stands with
    its face 1.24 mm past the edge (design.py turns it 180 and puts its origin `face` mm in), and the
    legend's lines along its sides and across its face would print off the board: the DRC names each.
    A line past x = face - 0.25 is cut there; one wholly past it goes."""
    lib = Path(os.environ.get("KICAD_FOOTPRINT_DIR", "/usr/share/kicad/footprints"))
    text = (lib / "Connector_RJ.pretty" / "RJ45_Pulse_JK0654219NL_Horizontal.kicad_mod").read_text(encoding="utf-8")
    cut = face - 0.25
    out_lines, block, cuts = [], None, 0
    for line in text.splitlines(keepends=True):
        if block is None and line == "\t(fp_line\n":
            block = [line]
            continue
        if block is None:
            out_lines.append(line)
            continue
        block.append(line)
        if line != "\t)\n":
            continue
        body, block = "".join(block), None
        ends = re.search(r"\(start (\S+) (\S+)\)\s*\(end (\S+) (\S+)\)", body)
        (x1, y1), (x2, y2) = (float(ends[1]), float(ends[2])), (float(ends[3]), float(ends[4]))
        if '(layer "F.SilkS")' not in body or (x1 <= cut and x2 <= cut):
            out_lines.append(body)
            continue
        cuts += 1
        if x1 > cut and x2 > cut:
            continue
        if x1 > cut:
            (x1, y1), (x2, y2) = (x2, y2), (x1, y1)
        y = y1 + (y2 - y1) * (cut - x1) / (x2 - x1)
        out_lines.append(body.replace(ends[0], f"(start {x1:g} {y1:g})\n\t\t(end {cut:g} {y:g})", 1))
    assert cuts >= 3, "the jack's legend lines past the edge were not found"
    text = "".join(out_lines)
    text = text.replace('(footprint "RJ45_Pulse_JK0654219NL_Horizontal"', '(footprint "RJ45_JK0654219NL_Edge"', 1)
    out = LIB / "RJ45_JK0654219NL_Edge.kicad_mod"
    LIB.mkdir(exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


def write(assigned: dict[str, str] | None = None) -> list[Path]:
    """Every footprint into basalt.pretty. `assigned` is pinmap.assign()'s land -> signal."""
    from heatsinks import HEATSINKS  # noqa: PLC0415  the heatsinks' holes, shared with the models

    fps = [str5_socket(assigned or {}), ddr5_dimm(), pcie_x16(), m2_key_m(), m2_standoff(), csd95490(), mounting_hole()]
    fps += [heatsink(name, spec["holes"], spec["descr"]) for name, spec in HEATSINKS.items()]
    return [fp.write(LIB) for fp in fps] + [rj45_at_edge()]


if __name__ == "__main__":
    for p in write(pinmap.assign() if hasattr(pinmap, "assign") else None):
        print("wrote", p.relative_to(HERE.parent))
