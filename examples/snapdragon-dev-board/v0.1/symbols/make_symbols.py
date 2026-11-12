"""The 3 connectors of the Open-Q 845 uSOM as symbols, named pin by pin from its datasheet.

    python3 symbols/make_symbols.py      # from the board's folder; writes symbols/wyvern.kicad_sym

KiCad's library draws a 100-pin board-to-board receptacle as `Conn_02x50`, 100 numbers and no names.
These symbols carry the SOM's own signal names (`open_q_845.PINS`), so the sheet says what each pin
is. One pin is drawn for each name, in the order the names first appear; a name the SOM repeats 5
times or more (GND 26 times on JT1, SOM_SYS_PWR 17 times on JT2, USB_VBUS 5) stacks its other pins
hidden on the same spot, the way KiCad's own RP2350 symbol draws its extra supply pins. A name
repeated fewer times (VREG_S3A_1P35 on 4 pins) gets a pin each: the board leaves some of those open,
and an open pin keeps a net of its own. The SOM's regulator outputs are
power outputs, its supply input a power input, every other pin passive.
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import open_q_845  # noqa: E402

G = 2.54
HALF_WIDTH = 30.48  # the body's half width: room for the longest name on each side
STACK = 5  # a name on this many pins or more is drawn once


def kind(name: str) -> str:
    if name.startswith("VREG_") or name in ("VDISP_P_OUT", "VDISP_M_OUT"):
        return "power_out"
    if name in ("SOM_SYS_PWR", "GND"):
        return "power_in"
    return "passive"


def pin(etype: str, x: float, y: float, angle: int, name: str, number: str, hidden: bool) -> str:
    hide = "\n\t\t\t\t(hide yes)" if hidden else ""
    return (
        f"\t\t\t(pin {etype} line{hide}\n\t\t\t\t(at {x:g} {y:g} {angle})\n\t\t\t\t(length 2.54)\n"
        f'\t\t\t\t(name "{name}"\n\t\t\t\t\t(effects\n\t\t\t\t\t\t(font\n\t\t\t\t\t\t\t(size 1.27 1.27)\n'
        f"\t\t\t\t\t\t)\n\t\t\t\t\t)\n\t\t\t\t)\n"
        f'\t\t\t\t(number "{number}"\n\t\t\t\t\t(effects\n\t\t\t\t\t\t(font\n\t\t\t\t\t\t\t(size 1.27 1.27)\n'
        f"\t\t\t\t\t\t)\n\t\t\t\t\t)\n\t\t\t\t)\n\t\t\t)"
    )


def prop(key: str, value: str, x: float, y: float, hidden: bool = False, justify: str = "") -> str:
    hide = "\n\t\t\t(hide yes)" if hidden else ""
    just = f"\n\t\t\t\t(justify {justify})" if justify else ""
    return (
        f'\t\t(property "{key}" "{value}"\n\t\t\t(at {x:g} {y:g} 0)\n\t\t\t(show_name no)\n'
        f"\t\t\t(do_not_autoplace no){hide}\n\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n"
        f"\t\t\t\t){just}\n\t\t\t)\n\t\t)"
    )


def symbol(jt: str) -> str:
    pins = open_q_845.PINS[jt]
    count = {name: list(pins.values()).count(name) for name in pins.values()}

    def key(n: int) -> str:
        return pins[n] if count[pins[n]] >= STACK else f"{pins[n]}#{n}"

    names: list[str] = []
    for n in sorted(pins):
        if key(n) not in names:
            names.append(key(n))
    rows = (len(names) + 1) // 2
    top = (rows - 1) / 2 * G
    top = round(top / G) * G  # every pin on the 2.54 grid
    slot: dict[str, tuple[float, float, int]] = {}
    for i, name in enumerate(names):
        col, row = divmod(i, rows)
        y = round(top - row * G, 2)
        slot[name] = (-(HALF_WIDTH + G), y, 0) if col == 0 else (HALF_WIDTH + G, y, 180)
    body_top = top + G
    body_bottom = top - rows * G
    name = f"OpenQ845_{jt}"
    out = [
        f'\t(symbol "{name}"\n\t\t(exclude_from_sim no)\n\t\t(in_bom yes)\n\t\t(on_board yes)\n'
        "\t\t(in_pos_files yes)\n\t\t(duplicate_pin_numbers_are_jumpers no)",
        prop("Reference", "J", -HALF_WIDTH, body_top + 1.27, justify="left"),
        prop("Value", name, HALF_WIDTH, body_top + 1.27, justify="right"),
        prop("Footprint", "", 0, 0, hidden=True),
        prop("Datasheet", "https://cdn.lantronix.com/wp-content/uploads/pdf/PDS-0007c-Open-Q-845-uSOM-HW-Datasheet.pdf",
             0, 0, hidden=True),  # fmt: skip
        prop(
            "Description",
            f"Hirose DF40HC(3.0)-100DS-0.4V receptacle for the Lantronix Open-Q 845 uSOM's {jt}, "
            "pins named as in its datasheet",
            0,
            0,
            hidden=True,
        ),
        f'\t\t(symbol "{name}_0_1"\n\t\t\t(rectangle\n\t\t\t\t(start {-HALF_WIDTH:g} {body_top:g})\n'
        f"\t\t\t\t(end {HALF_WIDTH:g} {body_bottom:g})\n\t\t\t\t(stroke\n\t\t\t\t\t(width 0.254)\n"
        "\t\t\t\t\t(type default)\n\t\t\t\t)\n\t\t\t\t(fill\n\t\t\t\t\t(type background)\n\t\t\t\t)\n\t\t\t)\n\t\t)",
        f'\t\t(symbol "{name}_1_1"',
    ]
    seen: set[str] = set()
    typed: set[str] = set()  # only a name's first pin is a power pin: the SOM joins the rest inside
    for n in sorted(pins):
        sig = pins[n]
        x, y, angle = slot[key(n)]
        first = key(n) not in seen
        seen.add(key(n))
        etype = kind(sig) if sig not in typed else "passive"
        typed.add(sig)
        out.append(pin(etype, x, y, angle, sig, str(n), hidden=not first))
    out.append("\t\t)\n\t\t(embedded_fonts no)\n\t)")
    return "\n".join(out)


def main() -> None:
    body = "\n".join(symbol(jt) for jt in ("JT1", "JT2", "JT3"))
    text = f'(kicad_symbol_lib\n\t(version 20241209)\n\t(generator "wyvern")\n{body}\n)\n'
    (HERE / "wyvern.kicad_sym").write_text(text, encoding="utf-8")
    print(f"wrote 3 symbols into {HERE / 'wyvern.kicad_sym'}")


if __name__ == "__main__":
    main()
