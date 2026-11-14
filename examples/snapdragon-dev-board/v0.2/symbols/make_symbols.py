"""The board's own symbols: the QCS6490 module, and 2 chips KiCad's library does not draw.

    python3 symbols/make_symbols.py      # from the board's folder; writes symbols/wyvern.kicad_sym

- `VOSM6490`: the module's 662 pads, named as `osm_l.name` gives them (Vantron's name where the
  board reads it, the OSM standard's elsewhere). 662 pins do not fit one rectangle on a sheet, so the
  symbol draws them as banks, a rectangle for each interface side by side, the way the Threadripper
  example draws its socket (examples/threadripper-matx). GND (135 pads) and VCC_IN_5V (17) are drawn
  once each, their other pads hidden on the same spot, the way KiCad's own RP2350 symbol draws its
  extra supply pins; every other pad has a pin of its own, so a pad the board leaves open stays on
  a net of its own. The module's regulator outputs are power outputs, its supply a power input, every
  other pin passive.
- `HD3SS3220`: TI's USB Type-C controller and SuperSpeed 2:1 mux, RNH0030A, from its datasheet's
  pin table (SLLSES1E, section 4).
- `TPS552892`: TI's 4-switch buck-boost, RYQ0021A, from its datasheet's pin table (SLVSH28A,
  Table 5-1).
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[3] / "tools"))

import kicadgen  # noqa: E402
import osm_l  # noqa: E402

P = 2.54  # pin pitch
L = 2.54  # pin length
CHAR = 1.1  # mm per character of a 1.27 mm pin name
STACKED = ("GND", "VCC_IN_5V")
POWER_OUT = ("VCC_OUT_IO", "VREG_L9C_2P96", "SDC2_VDDIO")

# Each bank: a title and the OSM names (prefixes) it holds, in order; a pad goes to the first match.
BANKS = [
    ("Power", r"^(VCC_IN_5V|VCC_IN_3V3|GND|VCC_OUT_IO|V_BAT|RTC_PWR|VCC_\d+_TEST)$"),
    ("USB", r"^(~\{)?USB_"),
    ("PCI Express", r"^(~\{)?PCIe_"),
    ("Cameras", r"^(CSI_|CAM_)"),
    ("DSI and eDP", r"^(DSI_|eDP_)"),
    ("LVDS and RGB", r"^(~\{)?(LVDS|RGB)_"),
    ("Ethernet A and B", r"^ETH_(A_|B_|IOPWR|CDE_|MDC|MDIO)"),
    ("Ethernet C to E", r"^ETH_[CDE]_"),
    ("SD and UFS", r"^(~\{)?(SDIO_|UFS_)"),
    ("Serial", r"^(~\{)?(UART_|I2C_|SPI_|CAN_|I2S_)"),
    ("GPIO", r"^(GPIO_|PWM_|ADC_|Vendor_Defined)"),
    ("System", r"^(~\{)?(BOOT_|RESET_|PWR_BTN|FORCE_RECOVERY|CARRIER_|Carrier_|JTAG_|DEBUG_|TEST_)"),
    ("Reserved", r"^(RESERVED|COM_AREA_)"),
]


def g(v: float) -> float:
    """Up to the next multiple of 2.54."""
    return math.ceil(round(v / P, 6)) * P


def banked(name: str, ref: str, banks: list[tuple[str, list[dict], list[dict]]], per_row: int,
           footprint: str = "", description: str = "", datasheet: str = "") -> str:
    """A one-unit symbol of rectangles in rows of `per_row`: each bank a title and its left and right
    pins ({number, name, type, hidden}), top to bottom; a hidden pin sits on the pin before it."""
    widths, heights = [], []
    for _, left, right in banks:
        ll = max((len(p["name"]) for p in left), default=0)
        lr = max((len(p["name"]) for p in right), default=0)
        shown = [sum(1 for p in side if not p["hidden"]) for side in (left, right)]
        widths.append(g(max(5 * P, (ll + lr) * CHAR / 2 + 2.0)))
        heights.append(g((max(*shown, 1) + 1) * P / 2))
    gap_x = 16 * P  # room for the labels of 2 facing columns of pins
    rows = [list(range(i, min(i + per_row, len(banks)))) for i in range(0, len(banks), per_row)]
    col_w = [max(widths[r[k]] for r in rows if k < len(r)) for k in range(per_row)]
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
                f"\t\t\t(rectangle (start {cx - hw:g} {cy + heights[i]:g}) (end {cx + hw:g} {cy - heights[i]:g}) "
                f"(stroke (width 0.254) (type default)) (fill (type background)))"
            )
            shapes.append(
                f'\t\t\t(text "{title}" (at {cx:g} {cy + heights[i] + 1.27:g} 0) (effects (font (size 1.27 1.27))))'
            )
            for side, items in (("left", left), ("right", right)):
                shown = sum(1 for p in items if not p["hidden"])
                top = cy + (shown - 1) * P / 2
                px = cx - hw - L if side == "left" else cx + hw + L
                ang = 0 if side == "left" else 180
                j = -1
                for p in items:
                    if not p["hidden"]:
                        j += 1
                    py = round(top - j * P, 4)
                    hide = " hide" if p["hidden"] else ""
                    pins.append(
                        f'\t\t\t(pin {p["type"]} line{hide} (at {px:g} {py:g} {ang}) (length {L:g}) '
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
        f'\t\t(property "Datasheet" "{datasheet}" (at 0 {bottom_y - 2.54:g} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
        f'\t\t(property "Description" "{description}" (at 0 {bottom_y - 5.08:g} 0) (effects (font (size 1.27 1.27)) (hide yes)))\n'
        f'\t\t(symbol "{name}_0_1"\n' + "\n".join(shapes) + "\n\t\t)\n"
        f'\t\t(symbol "{name}_1_1"\n' + "\n".join(pins) + "\n\t\t)\n\t\t(embedded_fonts no)\n\t)"
    )


def module() -> str:
    grouped: dict[str, list[str]] = {title: [] for title, _ in BANKS}
    for pad in osm_l.PADS:
        osm = osm_l.OSM[pad]
        for title, pattern in BANKS:
            if re.search(pattern, osm):
                grouped[title].append(pad)
                break
        else:
            raise SystemExit(f"{pad} ({osm}) falls in no bank")
    banks = []
    for title, _ in BANKS:
        pads = sorted(grouped[title], key=lambda p: (osm_l.name(p).lower(), p))
        pins: list[dict] = []
        typed: set[str] = set()
        for p in pads:
            sig = osm_l.name(p)
            stacked = sig in STACKED
            hidden = stacked and sig in typed
            if sig in STACKED:
                kind = "power_in" if sig not in typed else "passive"
            elif sig in POWER_OUT:
                kind = "power_out"
            else:
                kind = "passive"
            typed.add(sig)
            pins.append({"number": p, "name": sig, "type": kind, "hidden": hidden})
        # Half the shown pins on each side; a hidden pin stays with the pin it hides under.
        shown = [i for i, q in enumerate(pins) if not q["hidden"]]
        cut = shown[(len(shown) + 1) // 2] if len(shown) > 1 else len(pins)
        banks.append((title, pins[:cut], pins[cut:]))
    return banked(
        "VOSM6490",
        "U",
        banks,
        per_row=5,
        footprint="Wyvern:OSM_L_LGA-662_45x45mm_P1.25mm",
        description="Vantron VOSM6490, Qualcomm QCS6490 on an OSM Size-L module, 662 LGA pads",
        datasheet="https://www.vantrontech.com/",
    )


def table(name: str, ref: str, footprint: str, datasheet: str, description: str, rows: list[tuple]) -> str:
    pins = [{"number": n, "name": nm, "type": t, "side": s} for n, nm, t, s in rows]
    node = kicadgen.symbol_node(name, pins, reference=ref, footprint=footprint, datasheet=datasheet,
                                description=description)
    return "\t" + kicadgen.dumps(node, 1)


HD3SS3220 = [
    ("30", "VDD5", "power_in", "left"), ("8", "VCC33", "power_in", "left"),
    ("6", "TXp", "bidirectional", "left"), ("7", "TXn", "bidirectional", "left"),
    ("9", "RXp", "bidirectional", "left"), ("10", "RXn", "bidirectional", "left"),
    ("5", "VBUS_DET", "input", "left"), ("4", "PORT", "input", "left"),
    ("3", "CURRENT_MODE", "input", "left"), ("22", "ADDR", "input", "left"),
    ("29", "ENn_CC", "input", "left"), ("12", "ENn_MUX", "input", "left"),
    ("2", "CC1", "bidirectional", "right"), ("1", "CC2", "bidirectional", "right"),
    ("17", "TX1p", "bidirectional", "right"), ("16", "TX1n", "bidirectional", "right"),
    ("15", "RX1p", "bidirectional", "right"), ("14", "RX1n", "bidirectional", "right"),
    ("21", "TX2p", "bidirectional", "right"), ("20", "TX2n", "bidirectional", "right"),
    ("19", "RX2p", "bidirectional", "right"), ("18", "RX2n", "bidirectional", "right"),
    ("11", "DIR", "open_collector", "right"), ("27", "ID", "open_collector", "right"),
    ("25", "SDA/OUT1", "open_collector", "right"), ("26", "SCL/OUT2", "open_collector", "right"),
    ("23", "INT_N/OUT3", "open_collector", "right"), ("24", "VCONN_FAULT_N", "open_collector", "right"),
    ("13", "GND", "power_in", "bottom"), ("28", "GND", "passive", "bottom"), ("31", "EP", "passive", "bottom"),
]  # fmt: skip

TPS552892 = [
    ("7", "VIN", "power_in", "left"), ("1", "EN/UVLO", "input", "left"), ("2", "MODE", "input", "left"),
    ("21", "EXTVCC", "input", "left"), ("5", "DITH/SYNC", "input", "left"), ("6", "FSW", "passive", "left"),
    ("18", "VCC", "power_out", "left"), ("17", "AGND", "power_in", "left"),
    ("11", "VOUT", "power_out", "right"), ("8", "SW1", "passive", "right"), ("20", "BOOT1", "passive", "right"),
    ("10", "SW2", "passive", "right"), ("19", "BOOT2", "passive", "right"), ("12", "ISP", "input", "right"),
    ("13", "ISN", "input", "right"), ("14", "FB", "input", "right"), ("15", "COMP", "passive", "right"),
    ("16", "CDC", "passive", "right"), ("3", "PG", "open_collector", "right"), ("4", "~{CC}", "open_collector", "right"),
    ("9", "PGND", "power_in", "bottom"),
]  # fmt: skip


def main() -> None:
    body = [
        module(),
        table("HD3SS3220", "U", "Package_DFN_QFN:Texas_RNH0030A_WQFN-30-1EP_2.5x4.5mm_P0.4mm_EP1.2x3.2mm",
              "https://www.ti.com/lit/ds/symlink/hd3ss3220.pdf",
              "USB Type-C DRP port controller with a SuperSpeed 2:1 mux, RNH0030A", HD3SS3220),
        table("TPS552892", "U", "Wyvern:Texas_RYQ0021A_VQFN-HR-21_5x3mm_P0.5mm",
              "https://www.ti.com/lit/ds/symlink/tps552892.pdf",
              "36 V 8 A 4-switch buck-boost converter, 1.2 V reference, RYQ0021A", TPS552892),
    ]
    text = '(kicad_symbol_lib\n\t(version 20241209)\n\t(generator "wyvern")\n' + "\n".join(body) + "\n)\n"
    (HERE / "wyvern.kicad_sym").write_text(text, encoding="utf-8")
    print(f"wrote {len(body)} symbols into {HERE / 'wyvern.kicad_sym'}")


if __name__ == "__main__":
    main()
