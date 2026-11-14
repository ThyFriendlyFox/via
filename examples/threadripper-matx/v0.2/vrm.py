"""The voltage regulator's 14 phases: a TI CSD95490Q5MC power stage and a 10 x 10 mm choke each.

10 phases stand in a column left of the memory, 4 in a row above the socket, between the 2 regions
where the memory buses turn up to the slots' top pins. Each phase is drawn from
the stage's land pattern (TI SLPS669A section 9.2, footprints/csd95490q5mc_land.csv): the switch node
from the stage's SW pad to the choke by a short wide track, the choke's output into the plane through
5 vias in its pad, the stage's ground pad into the ground planes through 6, and the output-sense pin
(VOS) to its plane through 1. Each stage's input, bootstrap and driver-supply capacitors sit above and
below it, where the column's pitch leaves room.

    column (stage turned 180, choke to its right)      row (stage turned 90, choke below)
      VIN cap                                             VIN cap
      [VIN | SW ] -> choke -> VDDCR_CPU vias              [stage]  SW down to the choke
      boot cap, VDD cap                                   choke -> output vias
"""

from __future__ import annotations

import csv
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent

LEFT = [(37.4, 26.0 + 12.5 * i) for i in range(10)]  # the column's stages (mech.py's frame)
TOP = [(88.5 + 12.5 * i, 8.0) for i in range(4)]  # the row's stages
SOC = (12, 13)  # phase index: the row's last 2 make VDDCR_SOC
CHOKE_DX = 9.1  # column: the choke's centre right of its stage
CHOKE_DV = 13.0  # row: the choke's centre below its stage
CHOKE_PAD = 3.325  # the XAL1010's pads from its centre (KiCad's footprint)

with (HERE / "footprints" / "csd95490q5mc_land.csv").open(encoding="utf-8") as _fh:
    PADS = {row["pad"]: (float(row["x"]), float(row["y"])) for row in csv.DictReader(_fh)}


def place(local: tuple[float, float], at: tuple[float, float], rot: float) -> tuple[float, float]:
    """A footprint point in board coordinates, turned the way kicadgen and KiCad turn a footprint."""
    th = math.radians(rot)
    x, y = local
    return (round(at[0] + x * math.cos(th) + y * math.sin(th), 4), round(at[1] - x * math.sin(th) + y * math.cos(th), 4))


def phases() -> list[tuple[int, tuple[float, float], str, str]]:
    """(index, stage position, "left" or "top", output net) for each phase."""
    out = [(n, uv, "left", "VDDCR_CPU") for n, uv in enumerate(LEFT)]
    out += [(len(LEFT) + i, uv, "top", "VDDCR_SOC" if len(LEFT) + i in SOC else "VDDCR_CPU") for i, uv in enumerate(TOP)]
    return out


def build(d, at, add, cap, c0402: str, c1206: str, choke: str) -> None:
    """Every phase: its parts, and the copper a router must not be left to draw."""
    for n, (u, v), side, out in phases():
        # BOOTR (pad 8) is the switch node inside the package (SLPS669A, pin functions): on the board it
        # is the bootstrap capacitor's other end only.
        sw, boot, bootr = f"PH{n + 1}_SW", f"PH{n + 1}_BOOT", f"PH{n + 1}_BOOTR"
        stage = {"4": "+5V", "5": out, "6": sw, "7": "+12V_CPU", "8": bootr, "9": boot, "13": "GND"}
        rot = 180 if side == "left" else 90
        here = at(u, v)
        add(f"Q{n + 1}", "Basalt:CSD95490Q5MC", "CSD95490Q5MC", "Basalt:CSD95490Q5MC", (u, v), stage, rot)
        swp = place(PADS["6"], here, rot)
        vos = place(PADS["5"], here, rot)
        if side == "left":
            cu = (u + CHOKE_DX, v)
            add(f"L{n + 1}", "Device:L", "150n", choke, cu, {"1": sw, "2": out})
            choke_in = at(cu[0] - CHOKE_PAD, v)
            outs = [at(cu[0] + CHOKE_PAD, v + dv) for dv in (-3.6, -1.8, 0.0, 1.8, 3.6)]
            # From the SW pad's outer edge: a round end at its centre would reach the ground pad.
            d.track(sw, [(swp[0] + 0.65, swp[1]), (choke_in[0], swp[1])], "F.Cu", 2.0)
            # VOS (pad 5) out to a via between the stage and the choke; VDD (pad 4) under it to its
            # capacitor, which a sense track drawn the other way would box in.
            sense = at(u + 3.5, v + 0.5)
            d.track(out, [vos, sense], "F.Cu", 0.15)
            d.track("+5V", [place(PADS["4"], here, rot), at(u + 3.3, v + 1.0), at(u + 3.3, v + 4.4), at(u + 2.48, v + 4.4)],
                    "F.Cu", 0.15)
            cap(f"C{140 + n}", "22u", "+12V_CPU", (u - 1.0, v - 5.2), 0, fp=c1206)
            # The bootstrap capacitor beside BOOT (pad 9) and BOOTR (pad 8), each a straight 0.5 mm link.
            cap(f"C{100 + n}", "100n", boot, (u - 4.0, v + 0.75), 90, b=bootr)
            d.track(boot, [at(u - 3.69, v + 1.0), place(PADS["9"], here, rot)], "F.Cu", 0.15)
            d.track(bootr, [at(u - 3.69, v + 0.5), place(PADS["8"], here, rot)], "F.Cu", 0.15)
            cap(f"C{120 + n}", "1u", "+5V", (u + 2.0, v + 4.4), 180)
        else:
            cu = (u, v + CHOKE_DV)
            add(f"L{n + 1}", "Device:L", "150n", choke, cu, {"1": sw, "2": out})
            choke_in = at(cu[0] - CHOKE_PAD, cu[1])
            outs = [at(cu[0] + CHOKE_PAD, cu[1] + dv) for dv in (-3.6, -1.8, 0.0, 1.8, 3.6)]
            start, bend = (swp[0], swp[1] + 0.55), (swp[0], swp[1] + 2.65)
            d.track(sw, [start, bend, (choke_in[0], choke_in[1] - 3.5)], "F.Cu", 1.5)
            sense = at(u - 0.5, v + 4.0)
            d.track(out, [vos, sense], "F.Cu", 0.15)
            cap(f"C{140 + n}", "22u", "+12V_CPU", (u + 0.5, v - 5.7), 180, fp=c1206)
            cap(f"C{100 + n}", "100n", boot, (u - 0.75, v - 4.0), 0, b=bootr)
            d.track(boot, [at(u - 1.0, v - 3.72), place(PADS["9"], here, rot)], "F.Cu", 0.15)
            d.track(bootr, [at(u - 0.5, v - 3.72), place(PADS["8"], here, rot)], "F.Cu", 0.15)
            cap(f"C{120 + n}", "1u", "+5V", (u - 4.2, v + 2.6), 90)
            d.track("+5V", [place(PADS["4"], here, rot), at(u - 1.0, v + 3.08), at(u - 4.2, v + 3.08)], "F.Cu", 0.15)
        d.via(out, *sense, 0.4, 0.2)
        for x, y in outs:
            d.via(out, x, y, 0.6, 0.3)
        for lx in (-0.8, 0.8):
            for ly in (-1.8, 0.0, 1.8):
                d.via("GND", *place((lx, ly), here, rot), 0.4, 0.2)
