"""The project symbols, written into basalt.kicad_sym from the pin tables in pins/.

    python3 symbols/make_symbols.py     # from the board's folder; design.py runs it too

A part of a thousand pins does not fit one rectangle on any sheet, so the processor, the memory
slots and the PCI Express slots are drawn as banks: rectangles side by side in 1 symbol, each with
its pins on the left and the right, a bank for each interface. kicadgen places 1 unit per part, and
a bank keeps every pin of the part in that unit.
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parents[2] / "tools"))

import kicadgen  # noqa: E402

LIB = HERE / "basalt.kicad_sym"
P = 2.54  # pin pitch
L = 2.54  # pin length
CHAR = 1.1  # mm per character of a 1.27 mm pin name


def pins_csv(name: str) -> list[dict]:
    with (ROOT / "pins" / name).open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def g(v: float) -> float:
    """Up to the next multiple of 2.54."""
    import math

    return math.ceil(round(v / P, 6)) * P


def banked(name: str, ref: str, banks: list[tuple[str, list[dict], list[dict]]], per_row: int,
           footprint: str = "", description: str = "") -> str:
    """A one-unit symbol of rectangles in rows of `per_row`: each bank a title and its left and right
    pins ({number, name, type}), top to bottom."""
    widths, heights = [], []
    for _, left, right in banks:
        ll = max((len(p["name"]) for p in left), default=0)
        lr = max((len(p["name"]) for p in right), default=0)
        widths.append(g(max(5 * P, (ll + lr) * CHAR / 2 + 2.0)))
        heights.append(g((max(len(left), len(right), 1) + 1) * P / 2))
    gap_x = 16 * P  # room for the labels of 2 facing columns of pins
    rows = [list(range(i, min(i + per_row, len(banks)))) for i in range(0, len(banks), per_row)]
    col_w = [max(widths[i] for i in col) for col in zip(*[r + [r[-1]] * (per_row - len(r)) for r in rows])]
    shapes, pins = [], []
    y = 0.0
    for row in rows:
        hh = max(heights[i] for i in row)
        x = 0.0
        for k, i in enumerate(row):
            title, left, right = banks[i]
            hw = col_w[k]
            cx, cy = x + hw, y - hh
            shapes.append(
                f'\t\t\t(rectangle (start {cx - hw:g} {cy + heights[i]:g}) (end {cx + hw:g} {cy - heights[i]:g}) '
                f"(stroke (width 0.254) (type default)) (fill (type background)))"
            )
            shapes.append(
                f'\t\t\t(text "{title}" (at {cx:g} {cy + heights[i] + 1.27:g} 0) (effects (font (size 1.27 1.27))))'
            )
            for side, items in (("left", left), ("right", right)):
                top = cy + (len(items) - 1) * P / 2
                px = cx - hw - L if side == "left" else cx + hw + L
                ang = 0 if side == "left" else 180
                for j, p in enumerate(items):
                    py = round(top - j * P, 4)
                    pins.append(
                        f'\t\t\t(pin {p["type"]} line (at {px:g} {py:g} {ang}) (length {L:g}) '
                        f'(name "{p["name"]}" (effects (font (size 1.27 1.27)))) '
                        f'(number "{p["number"]}" (effects (font (size 1.27 1.27)))))'
                    )
            x += 2 * hw + 2 * L + gap_x
        y -= 2 * hh + 6 * P
    top_y = 1.27 + 2.54
    bottom_y = y
    return (
        f'\t(symbol "{name}" (pin_names (offset 0.762)) (exclude_from_sim no) (in_bom yes) (on_board yes)\n'
        f'\t\t(property "Reference" "{ref}" (at 0 {top_y + 2.54:g} 0) (effects (font (size 1.27 1.27)) (justify left)))\n'
        f'\t\t(property "Value" "{name}" (at 0 {top_y:g} 0) (effects (font (size 1.27 1.27)) (justify left)))\n'
        f'\t\t(property "Footprint" "{footprint}" (at 0 {bottom_y:g} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
        f'\t\t(property "Datasheet" "" (at 0 {bottom_y - 2.54:g} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
        f'\t\t(property "Description" "{description}" (at 0 {bottom_y - 5.08:g} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
        f'\t\t(symbol "{name}_0_1"\n' + "\n".join(shapes) + "\n\t\t)\n"
        f'\t\t(symbol "{name}_1_1"\n' + "\n".join(pins) + "\n\t\t)\n\t\t(embedded_fonts no)\n\t)"
    )


def simple(name: str, pins: list[dict], ref: str = "U", footprint: str = "", description: str = "") -> str:
    node = kicadgen.symbol_node(name, pins, reference=ref, footprint=footprint, description=description)
    return "\t" + kicadgen.dumps(node, 1)


def split(items: list[dict]) -> tuple[list[dict], list[dict]]:
    half = (len(items) + 1) // 2
    return items[:half], items[half:]


def chunks(title: str, items: list[dict], size: int) -> list[tuple[str, list[dict], list[dict]]]:
    out = []
    for i in range(0, len(items), size):
        part = items[i : i + size]
        left, right = split(part)
        out.append((f"{title} {i // size + 1}" if len(items) > size else title, left, right))
    return out


DIMM_POWER = {"VSS": "power_in", "VIN_BULK": "power_in", "VIN_MGMT": "power_in", "RFU": "no_connect"}


def dimm() -> str:
    rows = [r for r in pins_csv("ddr5_rdimm.csv") if r["pin"] != "220"]  # the socket has no contact 220
    items = [
        {"number": r["pin"], "name": r["name"].split("/")[0], "type": DIMM_POWER.get(r["name"], "bidirectional")}
        for r in rows
    ]
    items.append({"number": "MP", "name": "MP", "type": "passive"})
    banks = chunks("DIMM", items, 72)
    return banked("DDR5_RDIMM_SLOT", "J", banks, 4, "Basalt:DDR5_DIMM_288_SMT",
                  "DDR5 RDIMM slot, 287 contacts (Amphenol DDR516112010E)")


def pcie() -> str:
    items = []
    for r in pins_csv("pcie_x16.csv"):
        nm = r["name"].split(" ")[0].replace("(", "").replace(")", "")
        kind = "power_in" if nm in ("GND", "+12V", "+3.3V", "+3.3Vaux") else ("no_connect" if nm == "RSVD" else "bidirectional")
        items.append({"number": r["pin"], "name": nm, "type": kind})
    a = [p for p in items if p["number"].startswith("A")]
    b = [p for p in items if p["number"].startswith("B")]
    banks = [("SIDE A", *split(a)), ("SIDE B", *split(b))]
    return banked("PCIe_x16_SLOT", "J", banks, 2, "Basalt:PCIe_x16_THT", "PCI Express x16 slot, 164 contacts")


def m2() -> str:
    items = []
    for r in pins_csv("m2_key_m.csv"):
        if r["name"].startswith("KEY_M"):
            continue
        nm = r["name"].split("/")[0].split(" ")[0]
        kind = "power_in" if nm in ("GND", "3.3V") else ("no_connect" if nm == "NC" else "bidirectional")
        items.append({"number": r["pin"], "name": nm, "type": kind})
    items.append({"number": "MP", "name": "MP", "type": "passive"})
    return banked("M2_KEY_M", "J", [("M.2 KEY M", *split(items))], 1, "Basalt:M2_KeyM_SMT", "M.2 Key M socket, PCIe x4")


def from_table(name: str, table: str, ref: str, footprint: str, description: str) -> str:
    pins = [
        {"number": r["Number"], "name": r["Name"], "type": r["Type"], "side": r["Side"]}
        for r in pins_csv(table)
    ]
    return simple(name, pins, ref, footprint, description)


def write(extra: list[str] | None = None) -> Path:
    """Every project symbol into basalt.kicad_sym; `extra` adds symbols written elsewhere (the
    processor's, from its pin map)."""
    body = [dimm(), pcie(), m2()]
    body.append(from_table("CSD95490Q5MC", "csd95490q5mc.csv", "U", "Basalt:CSD95490Q5MC",
                           "75 A smart power stage, TI SLPS669A"))
    body.append(from_table("uPD720202", "upd720202.csv", "U",
                           "Package_DFN_QFN:QFN-48-1EP_7x7mm_P0.5mm_EP5.7x5.7mm",
                           "USB 3.0 host controller, PCIe Gen2 x1, 2 ports, Renesas R19DS0047"))
    body.append(from_table("ARGB_HEADER", "argb_header.csv", "J", "Basalt:PinHeader_1x04_Key3",
                           "Addressable RGB header, 5 V: +5V, DIN, the key, GND"))
    body.append(from_table("SATA_7P", "sata_7p.csv", "J", "Basalt:SATA_7P_RA_SMT",
                           "SATA 7-pin host plug, right angle (Adam Tech SATA-A-PL-SMT-K)"))
    body.append(from_table("USB3_A_STACKED", "usb3_a_stacked.csv", "J",
                           "Connector_USB:USB3_A_Molex_48406-0001_Horizontal_Stacked",
                           "Two USB 3.0 Type-A receptacles, stacked, Molex 48406-0001"))
    body.append(from_table("RJ45_JK0654219NL", "jk0654219nl.csv", "J",
                           "Connector_RJ:RJ45_Pulse_JK0654219NL_Horizontal",
                           "Gigabit RJ45 with magnetics and 2 green LEDs, Pulse JK0654219NL (J411.L)"))
    body += extra or []
    text = '(kicad_symbol_lib\n\t(version 20241209)\n\t(generator "basalt")\n' + "\n".join(body) + "\n)\n"
    LIB.write_text(text, encoding="utf-8")
    kicadgen._LIB_CACHE.pop(LIB, None)
    return LIB


if __name__ == "__main__":
    print("wrote", write())
