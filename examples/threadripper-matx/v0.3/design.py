"""Basalt v0.3: a microATX board for an AMD Threadripper on the sTR5 socket (TRX50).

No microATX TRX50 board exists; the smallest is ATX. Basalt fits the platform on 244 x 244 mm:
4 DDR5 RDIMM slots, 2 each side of the socket, 1 per channel; 3 PCI Express 5.0 x16 slots that take
the processor's 48 Gen5 lanes; 2 M.2 sockets on Gen4 lanes; 14 phases of 75 A smart power stages
(12 for the cores, 2 for the SoC) for 350 W; 2 gigabit ports and 8 USB 3 ports on the rear edge.

    workcenter design design.py      # from this folder; every supply is drawn, nothing is routed

The board is drawn in mech.py's frame (the rear I/O edge on the left, the slots along the bottom)
and placed at mech.ORIGIN. What the makers publish is drawn from their drawings; what AMD keeps under
NDA (the socket's pin map, the voltage regulator's control interface) is a stand-in, named so in
README.md.
"""

from __future__ import annotations

import re
import sys
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
for sub in ("", "footprints", "symbols"):
    sys.path.insert(0, str(HERE / sub) if sub else str(HERE))

import kicadgen  # noqa: E402
import make_footprints  # noqa: E402
import make_symbols  # noqa: E402
import mech  # noqa: E402
import pinmap  # noqa: E402
import ports  # noqa: E402
import supply  # noqa: E402
import buses  # noqa: E402
import vrm  # noqa: E402
from heatsinks import HEATSINKS  # noqa: E402
from mech import at  # noqa: E402

# Nets an inner plane carries: every pad of theirs has a via of its own to the plane, so the router
# gets none of them; KiCad's fill joins them, and its DRC checks that it did.
PLANE_NETS = ("GND", "VDDCR_CPU", "VDDCR_SOC", "+12V", "+3V3", "+12V_CPU")


class BasaltDesign(kicadgen.Design):
    """A Design in black: a black solder mask, white legend and silver pads (immersion silver: flat for a
    fine-pitch socket, and quieter than gold on black in the renders); plane nets kept
    from the router."""

    @staticmethod
    def _stackup(copper, thickness=1.6):
        node = kicadgen.Design._stackup(copper, thickness)
        for item in node[1:]:
            if isinstance(item, list) and item[0] == "layer":
                name = str(item[1])
                if name in ("F.Mask", "B.Mask"):
                    item.insert(3, ["color", kicadgen.Q("#0B0C0EFF")])  # opaque: copper tints a translucent one brown
                elif name in ("F.SilkS", "B.SilkS"):
                    item.append(["color", kicadgen.Q("White")])
            elif isinstance(item, list) and item[0] == "copper_finish":
                item[1] = kicadgen.Q("Immersion silver")
        return node

    def dsn(self, seed=None):
        """The router's file with each plane net cut to 1 pin: the net stays declared, so its vias and
        pads stay obstacles the router keeps clear of, and it has nothing to connect. Its pours on the
        faces go too: the plane joins it."""
        text = super().dsn(seed)
        for net in PLANE_NETS:
            text = re.sub(
                r'(\n    \(net "%s"\n      \(pins )(\S+)[^\n]*' % re.escape(net), r"\g<1>\g<2>)", text
            )
            text = re.sub(r'\n    \(plane "%s" [^\n]*' % re.escape(net), "", text)
        return text

    def board(self) -> str:
        """kicadgen writes every pour at priority 0; a pour laid over another (the SOC pour on the
        back's ground) takes the priority its dict names, so KiCad fills it first and the ground
        round it."""
        text = super().board()
        for i, z in enumerate(self.zones):
            if z.get("priority"):
                zid = re.escape(str(self.uid(f"zone/{i}")))
                pattern = r'(\(uuid "%s"\)\s*\(hatch edge 0\.5\)\s*)\(priority 0\)' % zid
                text, n = re.subn(pattern, r"\g<1>(priority %d)" % z["priority"], text)
                assert n == 1, f"zone {i}: its priority was not written"
        return text


# ---- footprints -----------------------------------------------------------------------------------
R0402 = "Resistor_SMD:R_0402_1005Metric"
C0402 = "Capacitor_SMD:C_0402_1005Metric"
C0603 = "Capacitor_SMD:C_0603_1608Metric"
C1206 = "Capacitor_SMD:C_1206_3216Metric"
POLY = "Capacitor_SMD:CP_Elec_6.3x5.8"
CHOKE = "Inductor_SMD:L_Coilcraft_XAL1010-XXX"
EPS = "Connector_Molex:Molex_Mini-Fit_Jr_5566-08A_2x04_P4.20mm_Vertical"
ATX = "Connector_Molex:Molex_Mini-Fit_Jr_5566-24A_2x12_P4.20mm_Vertical"
USB3 = "Connector_USB:USB3_A_Molex_48406-0001_Horizontal_Stacked"
RJ45 = "Basalt:RJ45_JK0654219NL_Edge"  # KiCad's, its legend cut at the board edge (make_footprints.py)

# ---- the rear I/O, top to bottom: 4 stacked USB 3 pairs, 2 network jacks ---------------------------------
# The jacks at the bottom, nearest the network controllers that will sit below the I/O cover.
USB_V = (17.0, 35.0, 53.0, 71.0)  # each pair's origin; 15.5 mm with its courtyard
RJ45_V = (114.95, 135.25)  # each jack's origin: its face on the edge; 19.75 mm with its courtyard


def extent(sym) -> tuple[float, float, float, float]:
    """A symbol's body and pin ends in library coordinates (y up)."""
    x1, y1, x2, y2 = kicadgen.symbol_box(sym)
    xs, ys = [x1, x2], [y1, y2]
    for p in sym.pins:
        xs.append(p.x)
        ys.append(p.y)
    return min(xs), min(ys), max(xs), max(ys)


def sheet_blocks(d: kicadgen.Design) -> list[list]:
    """The parts in the order the shelves take them, in blocks a shelf never splits: each connector and
    the processor alone, tallest first; then each phase, its stage, bootstrap capacitor, choke and 2
    more capacitors side by side, so its switch node and bootstrap wires stay inside the phase; then
    the holes and heatsinks."""
    by_ref = {p.ref: p for p in d.parts}
    phases = [[by_ref[r] for r in (f"Q{n}", f"C{99 + n}", f"L{n}", f"C{119 + n}", f"C{139 + n}")]
              for n in range(1, len(vrm.phases()) + 1)]
    placed = {p.ref for block in phases for p in block}
    rest = [p for p in d.parts if p.ref not in placed]
    big = sorted((p for p in rest if p.ref[0] in "JU"), key=lambda p: (-(extent(p.symbol)[3] - extent(p.symbol)[1]), p.ref))
    small = sorted((p for p in rest if p.ref[0] not in "JU"), key=lambda p: p.ref)
    return [[p] for p in big] + phases + [[p] for p in small]


def schematic_layout(d: kicadgen.Design) -> None:
    """Shelves across an A0 sheet in `sheet_blocks`. A connector or the processor has room round it
    for its pins' labels; a phase's parts, wired to each other, sit closer. A library point (x, y)
    lands on the sheet at (sx + x, sy - y)."""
    g = 2.54
    left, top = 10 * g, 10 * g
    width = kicadgen.SHEETS[d.sheet][0] - 10 * g

    def room(part) -> float:
        return 12 * g if part.ref[0] in "JU" else 4 * g  # a label's length past its pin, or a wire's

    def size(part) -> tuple[float, float]:
        x1, y1, x2, y2 = extent(part.symbol)
        return x2 - x1 + 2 * room(part), y2 - y1 + 4 * g

    x, y, shelf = left, top, 0.0
    for block in sheet_blocks(d):
        if x + sum(size(p)[0] for p in block) > width:
            x, y, shelf = left, y + shelf, 0.0
        for part in block:
            x1, _y1, _x2, y2 = extent(part.symbol)
            w, h = size(part)
            part.sch_at = (round((x + room(part) - x1) / g) * g, round((y + 2 * g + y2) / g) * g)
            part.sch_rot = 0
            x += w
            shelf = max(shelf, h)


def legend(d: kicadgen.Design) -> None:
    """The silkscreen's words, each where no pad or part is: the board's name in the right-hand field
    between the memory and the 24-pin, and a name beside each slot, socket and power connector."""
    big = [
        ("BASALT", (198.0, 122.0), 7.0, 1.1),
        ("microATX  /  sTR5  /  TRX50", (198.0, 131.0), 1.6, 0.25),
        ("THREADRIPPER 7000 & 9000 WORKSTATION", (198.0, 135.0), 1.2, 0.2),
        ("v0.3", (198.0, 140.0), 1.2, 0.2),
    ]
    names = [
        ("PCIE1  GEN5 x16", (146.5, mech.SLOT_V[1])),
        ("PCIE3  GEN5 x16", (146.5, mech.SLOT_V[3])),
        ("PCIE4  GEN5 x16", (146.5, mech.SLOT_V[4])),
        ("M.2_1", (60.0, 196.4)),
        ("M.2_2", (200.0, 200.5)),
        ("ATX 24P", (223.0, 70.0)),
    ]
    for text, (u, v), size, thick in big:
        d.text(text, *at(u, v), "F.SilkS", size, thick)
    for text, (u, v) in names:
        d.text(text, *at(u, v), "F.SilkS", 1.2, 0.18)


def build() -> kicadgen.Design:
    assigned = pinmap.assign()
    make_footprints.write(assigned)
    make_symbols.write([pinmap.symbol(assigned)])

    ox, oy = mech.ORIGIN
    d = BasaltDesign(
        name="basalt",
        namespace=uuid.UUID("d66e8b73-7167-459d-93f2-5673fe2e45e7"),
        outline=(ox, oy, ox + mech.W, oy + mech.H),
        sheet="A0",
        copper_layers=10,
        # F.Cu signal | In1 GND | In2, In3 signal | In4 GND | In5 power | In6, In7 signal | In8 GND | B.Cu
        plane_layers=("In1.Cu", "In4.Cu", "In5.Cu", "In8.Cu"),
        track_width=0.1,
        clearance=0.1,
        via_size=0.4,
        via_drill=0.2,
    )
    # 4 mil tracks and gaps, 0.4/0.2 mm vias: a motherboard fab's standard limits, and what the
    # processor's 0.94 x 0.81 mm lands leave room for (README, "Fabrication").
    d.rules = {
        "min_through_hole_diameter": 0.2,
        "min_via_diameter": 0.4,
        "min_via_annular_width": 0.1,
        "min_track_width": 0.1,
        "min_clearance": 0.1,
        "min_text_height": 0.8,
        "min_text_thickness": 0.12,
    }
    d.sch_wires = True  # each pin wired to its net's label; the processor is drawn as banks
    d.symbol_dirs = {"Basalt": HERE / "symbols" / "basalt.kicad_sym"}
    d.footprint_dirs = {"Basalt": HERE / "footprints" / "basalt.pretty"}
    d.power_nets = {
        "GND": "GND",
        "+12V": "+12V",
        "+12V_CPU": "+12V",
        "+5V": "+5V",
        "+3V3": "+3V3",
        "+5VSB": "+5V",
        "+3V3SB": "+3V3",
        "VDDCR_CPU": "VDD",
        "VDDCR_SOC": "VDD",
    }
    # Iteration 1: the regulators for the small rails come with the processor's signals.
    d.flagged_nets = ["GND", "+12V", "+12V_CPU", "+5V", "+3V3", "+5VSB", "VDDCR_CPU", "VDDCR_SOC"]
    d.net_classes = {
        "power": {"width": 0.6, "clearance": 0.15, "via": 0.6, "via_drill": 0.3,
                  "nets": ["+12V", "+12V_CPU", "+5V", "+3V3", "+5VSB"]},
    }

    def add(ref, lib, value, fp, uv, nets, rot=0.0, layer="F.Cu"):
        return d.add(ref, lib, value, fp, sch_at=(0.0, 0.0), pcb_at=at(*uv), pcb_rot=rot, pcb_layer=layer, nets=nets)

    def cap(ref, value, a, uv, rot=0.0, b="GND", fp=C0402, layer="F.Cu"):
        return add(ref, "Device:C", value, fp, uv, {"1": a, "2": b}, rot, layer)

    # ---- mounting holes (ATX 2.2) --------------------------------------------------------------------
    for i, (letter, uv) in enumerate(sorted(mech.HOLES.items())):
        add(f"H{i + 1}", "Mechanical:MountingHole_Pad", f"HOLE_{letter}", "Basalt:MountingHole_ATX", uv, {"1": "GND"})

    # ---- the processor --------------------------------------------------------------------------------
    cpu_nets = {r: r for r in pinmap.ACTIVE_RAILS} | {land: net for land, net in assigned.items()}
    add("U1", "Basalt:sTR5_STANDIN", "Threadripper sTR5", "Basalt:sTR5_LGA4844", mech.CPU, cpu_nets)
    # A via in every supply land, to its plane: In5 for VDDCR_CPU, In1/In4/In8 for ground; the
    # small rails' lands join their back-side pours through theirs.
    cu, cv = at(*mech.CPU)
    for land in pinmap.lands():
        net = pinmap.land_net(land, assigned)
        if net in pinmap.RAILS:
            d.via(net, round(cu + land.u, 4), round(cv + land.v, 4))

    # ---- memory: 4 DDR5 RDIMM slots ----------------------------------------------------------------
    for k, (ch, u) in enumerate(mech.DIMMS.items()):
        nets = {"MP": "GND", "1": "+12V", "145": "+12V", "146": "+12V", "3": "+3V3"} | buses.dimm_nets(ch)
        for row in make_symbols.pins_csv("ddr5_rdimm.csv"):
            if row["name"] == "VSS":
                nets[row["pin"]] = "GND"
        add(f"J{k + 1}", "Basalt:DDR5_RDIMM_SLOT", f"DIMM_{ch}", "Basalt:DDR5_DIMM_288_SMT", (u, mech.DIMM_V),
            nets, 90 if ch in "AB" else 270)

    # The 4 channels' buses: 576 traces from the processor's lands to the slots' pins (buses.py).
    buses.route(d, at)
    # The buses cross the whole sheet, from the processor's banks to the 4 slots: each net a label at
    # both ends (P24 step 2), so the sheet stays readable and its 576 wires are not drawn round it.
    d.sch_label_nets = tuple(sorted({t.net for t in buses.plan()}))

    # ---- PCI Express x16 slots 1, 3 and 4 --------------------------------------------------------------
    for k, slot in enumerate((1, 3, 4)):
        nets = {}
        for row in make_symbols.pins_csv("pcie_x16.csv"):
            name = row["name"].split(" ")[0]
            net = {"GND": "GND", "+12V": "+12V", "+3.3V": "+3V3", "+3.3Vaux": "+3V3"}.get(name)
            if net:
                nets[row["pin"]] = net
        add(f"J{5 + k}", "Basalt:PCIe_x16_SLOT", f"PCIE{slot}", "Basalt:PCIe_x16_THT",
            (mech.PCIE_PEG_U, mech.SLOT_V[slot]), nets)
        if slot == 1:
            d.model("J5", "${KIPRJMOD}/models/pcie_x16_armor.wrl", replace=True)

    # ---- M.2: one between slots 1 and 3, one right of the slots ------------------------------------------
    m2_nets = {"MP": "GND"}
    for row in make_symbols.pins_csv("m2_key_m.csv"):
        name = row["name"]
        if name in ("GND", "3.3V"):
            m2_nets[row["pin"]] = "GND" if name == "GND" else "+3V3"
    # Each connector beside the right-hand trunk that will carry its lanes, its signal row facing the
    # trunk: M.2_1 in slot 2's place with its drive toward the rear edge, M.2_2 right of the slots with
    # its drive toward the right edge.
    for ref, (u, v), rot, sref in (("J8", mech.M2_1, 270, "H10"), ("J9", mech.M2_2, 90, "H11")):
        add(ref, "Basalt:M2_KEY_M", "M.2_" + ref[-1], "Basalt:M2_KeyM_SMT", (u, v), m2_nets, rot)
        su = u - mech.M2_STANDOFF if rot == 270 else u + mech.M2_STANDOFF
        add(sref, "Mechanical:MountingHole_Pad", "M2_STANDOFF", "Basalt:M2_Standoff", (su, v), {"1": "GND"})

    # ---- power in: the 24-pin ATX, 2 EPS 8-pin -----------------------------------------------------
    atx = {"1": "+3V3", "2": "+3V3", "3": "GND", "4": "+5V", "5": "GND", "6": "+5V", "7": "GND",
           "9": "+5VSB", "10": "+12V", "11": "+12V", "12": "+3V3", "13": "+3V3",
           "15": "GND", "17": "GND", "18": "GND", "19": "GND", "21": "+5V",
           "22": "+5V", "23": "+5V", "24": "GND"}  # fmt: skip
    add("J10", "Connector_Generic:Conn_02x12_Top_Bottom", "ATX_24P", ATX, (239.0, 45.0), atx, 270)
    eps = {str(n): "GND" for n in range(1, 5)} | {str(n): "+12V_CPU" for n in range(5, 9)}
    add("J11", "Connector_Generic:Conn_02x04_Top_Bottom", "EPS_8P", EPS, (41.5, 3.25), eps)
    add("J12", "Connector_Generic:Conn_02x04_Top_Bottom", "EPS_8P", EPS, (61.0, 3.25), eps)

    # ---- the voltage regulator: 14 phases (vrm.py) ------------------------------------------------------
    vrm.build(d, at, add, cap, C0402, C1206, CHOKE)
    supply.build(d)  # +12V, +3V3 and +12V_CPU as pours, +5V as 1 track (supply.py)

    # ---- the rear I/O --------------------------------------------------------------------------------
    for i, v in enumerate(RJ45_V):
        add(f"J{13 + i}", "Basalt:RJ45_JK0654219NL", f"LAN{i + 1}", RJ45, (25.01, v), {"SH": "GND"}, 180)
    for i, v in enumerate(USB_V):
        add(f"J{15 + i}", "Basalt:USB3_A_STACKED", f"USB{2 * i + 1}_{2 * i + 2}", USB3, (10.3, v),
            {"SH": "GND", "4": "GND", "7": "GND", "13": "GND", "16": "GND"}, 270)

    # KiCad's 3D library has no body for these 3; models/make_models.py draws them.
    d.model("J10", "${KIPRJMOD}/models/minifit_24.wrl", replace=True)
    for ref in ("J11", "J12"):
        d.model(ref, "${KIPRJMOD}/models/minifit_8.wrl", replace=True)
    for i in range(len(USB_V)):
        d.model(f"J{15 + i}", "${KIPRJMOD}/models/usb3_a_stacked.wrl", replace=True)

    # ---- heatsinks --------------------------------------------------------------------------------------
    for i, (name, spec) in enumerate(HEATSINKS.items()):
        add(f"HS{i + 1}", "Mechanical:MountingHole_Pad", name.replace("Heatsink_", "HEATSINK_").upper(),
            f"Basalt:{name}", spec["holes_uv"][0], {"1": "GND"})

    # ---- the ports and headers (ports.py), their own nets joined by the grid router ----------------------
    failed = ports.route(d, at, ports.build(d, at, add))
    if failed:
        raise RuntimeError(f"{len(failed)} links of the ports' nets found no way: {failed[:6]}")

    # ---- copper pours -------------------------------------------------------------------------------
    for layer in ("In1.Cu", "In4.Cu", "In8.Cu"):
        d.zone("GND", layers=(layer,), connect="solid")
    # VDDCR_CPU on In5: from the left column's chokes under the memory to the socket's middle, and up
    # to the row's chokes.
    poly = [(38.0, 10.0), (124.0, 10.0), (124.0, 60.0), (133.5, 60.0), (133.5, 114.0), (90.0, 114.0),
            (90.0, 143.0), (38.0, 143.0)]  # fmt: skip
    d.zone("VDDCR_CPU", layers=("In5.Cu",), polygon=[at(u, v) for u, v in poly], connect="solid")
    d.zones[-1]["priority"] = 1  # over the +12V that fills the rest of In5
    d.zone("GND", layers=("F.Cu", "B.Cu"), connect="solid")
    # VDDCR_SOC on the back: from its 2 chokes at the row's right end down to its band of lands.
    soc = [(109.0, 4.0), (135.0, 4.0), (135.0, 66.0), (86.5, 66.0), (86.5, 46.0), (109.0, 46.0)]  # fmt: skip
    d.zone("VDDCR_SOC", layers=("B.Cu",), polygon=[at(u, v) for u, v in soc], connect="solid")
    d.zones[-1]["priority"] = 1

    legend(d)
    for part in d.parts:
        part.hide_ref = True
    schematic_layout(d)
    return d
