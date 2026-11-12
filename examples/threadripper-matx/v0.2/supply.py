"""The board's supplies, drawn: +12V, +3V3 and the processor's +12V_CPU as pours, +5V as 1 track.

A motherboard carries its supplies in copper planes, and so does Basalt. FreeRouting given the 4
supply nets as tracks across 244 mm of board ran 20 minutes without finishing a pass, and the
tracks it would have drawn cross the paths the memory and PCI Express buses take in later versions.

    In5 (power)  VDDCR_CPU under the socket and the left memory (design.py); +12V everywhere else:
                 the ATX connector, every slot's 12 V pins, the memory slots' 12 V vias
    In6 (signal) +5V, 1 track from the ATX connector along the top edge and down the phase column:
                 the power stages' driver supply, 14 x 25 mA
    In7 (signal) +12V_CPU from the 2 EPS connectors along the top edge and down the phase column,
                 under each stage's input; +3V3 everywhere else: the ATX connector, every slot's and
                 M.2 socket's 3.3 V

A through-hole pin joins a pour on its own. A surface pin of a supply gets a via of its own beside it
(the memory slots', the M.2 sockets'), or in it (each power stage's input, 3 vias in the pad).
Positions are in mech.py's frame.
"""

from __future__ import annotations

import vrm
from mech import DIMM_V, DIMMS, H, M2_1, M2_2, W, at

# The DIMMs' contacts: 2 rows 2.05 mm each side of the slot's centre line; pin 1 at the slot's end
# nearer the slots for channels A and B, nearer the top edge for C and D (design.py turns them).
ROW = 2.05
END = 63.33  # pin 1's distance from the slot's centre along it
PITCH = 0.85
OUTER = 3.4  # a pin's own via, outside its row: where the memory buses put theirs (v0.2)

# The +5V track on In6: a run along the top edge, between the top phases' sense vias and the memory
# slots' end pegs, and a spine down the phase column, between the stages' ground and sense vias.
RUN_V = 13.0  # 0.5 mm from the top sense vias and from the left heatsink's front hole
SPINE_U = 40.0
ATX_GAP_U = 236.25  # between the ATX connector's 2 columns of pins
ATX_5V = {"4": (239.0, 57.6), "6": (239.0, 66.0), "21": (233.5, 78.6), "23": (233.5, 87.0)}

# +12V_CPU's region on In7: the top edge from the left of the EPS connectors to past the top row, and
# the phase column's input side.
CPU12 = [(24.0, 0.6), (136.0, 0.6), (136.0, 16.0), (37.8, 16.0), (37.8, 141.0), (24.0, 141.0)]


def dimm_vias(d, ref: str, centre_u: float, top_end: bool) -> None:
    """Pins 1, 145 and 146 (+12V) and 3 (+3V3) of a memory slot to their planes: each 12 V pin up a
    stub past the slot's end to a via; pin 3 out past its row to a via where a bus pin's would be."""
    s = -1.0 if top_end else 1.0  # the direction from the slot's centre to pin 1's end
    end = DIMM_V + s * END
    left, right = centre_u - ROW, centre_u + ROW
    near, far = (left, right) if top_end else (right, left)  # pin 1's row, pin 145's
    beyond = end + s * 1.9  # the vias past the slot's last pins
    d.track("+12V", [at(near, end), at(near, beyond)], "F.Cu", 0.4)
    d.track("+12V", [at(far, end + s * -PITCH), at(far, end), at(far, beyond)], "F.Cu", 0.4)
    for u in (near, far):
        d.via("+12V", *at(u, beyond), 0.6, 0.3)
    pin3 = end - s * 2 * PITCH
    out = near - OUTER + ROW if top_end else near + OUTER - ROW
    d.track("+3V3", [at(near, pin3), at(out, pin3)], "F.Cu", 0.3)
    d.via("+3V3", *at(out, pin3), 0.6, 0.3)


def m2_vias(d, centre: tuple[float, float], rot: int) -> None:
    """An M.2 socket's 3.3 V pins (2-4, 12-18, 70-74, the even row) out past their row to a bar and a
    via per group. The row faces away from the socket's centre: left for M.2_1 (turned 270), right for
    M.2_2 (turned 90)."""
    u0, v0 = centre
    side = -1.0 if rot == 270 else 1.0
    row_u = u0 + side * 2.28
    bar_u = row_u + side * 1.52
    via_u = row_u + side * 2.3
    for pins in ((2, 4), (12, 14, 16, 18), (70, 72, 74)):
        vs = [v0 + side * (9.0 - 0.25 * (p - 2)) for p in pins]  # pin 2 at the row's far end, 0.5 mm a pin
        for v in vs:
            d.track("+3V3", [at(row_u, v), at(bar_u, v)], "F.Cu", 0.3)
        mid = (min(vs) + max(vs)) / 2
        d.track("+3V3", [at(bar_u, min(vs)), at(bar_u, max(vs))], "F.Cu", 0.3)
        d.track("+3V3", [at(bar_u, mid), at(via_u, mid)], "F.Cu", 0.3)
        d.via("+3V3", *at(via_u, mid), 0.6, 0.3)


def build(d) -> None:
    # ---- the pours ------------------------------------------------------------------------------------
    edge = [(0.0, 0.0), (W, 0.0), (W, H), (0.0, H)]
    d.zone("+12V", layers=("In5.Cu",), polygon=[at(u, v) for u, v in edge], connect="solid")
    d.zone("+3V3", layers=("In7.Cu",), polygon=[at(u, v) for u, v in edge], connect="solid")
    d.zone("+12V_CPU", layers=("In7.Cu",), polygon=[at(u, v) for u, v in CPU12], connect="solid")
    d.zones[-1]["priority"] = 1

    # ---- each power stage's input: 3 vias in its pad, 2 in its capacitor's -----------------------------
    for n, (u, v), side, _ in vrm.phases():
        rot = 180 if side == "left" else 90
        here = at(u, v)
        for dy in (-0.95, 0.0, 0.95):
            vx, vy = vrm.PADS["7"]
            d.via("+12V_CPU", *vrm.place((vx, vy + dy), here, rot), 0.4, 0.2)
        cap = (u - 1.0, v - 5.2) if side == "left" else (u + 0.5, v - 5.7)
        # The capacitor's pad 1, turned with it: 0 in the column, 180 in the row.
        pad1 = (cap[0] - 1.475, cap[1]) if side == "left" else (cap[0] + 1.475, cap[1])
        for k in (-0.45, 0.45):
            d.via("+12V_CPU", *at(pad1[0], pad1[1] + k), 0.4, 0.2)

    # ---- +5V on In6 -----------------------------------------------------------------------------------
    trunk = [(SPINE_U, vrm.LEFT[-1][1] + 2.7), (SPINE_U, RUN_V), (ATX_GAP_U, RUN_V), (ATX_GAP_U, ATX_5V["21"][1])]
    d.track("+5V", [at(*p) for p in trunk] + [at(*ATX_5V["21"])], "In6.Cu", 0.6)
    for pin in ("4", "6"):
        d.track("+5V", [at(*ATX_5V[pin]), at(ATX_GAP_U, ATX_5V[pin][1])], "In6.Cu", 0.6)
    d.track("+5V", [at(*ATX_5V["21"]), at(*ATX_5V["23"])], "In6.Cu", 0.6)
    for u, v in vrm.LEFT:
        tap = (u + 3.3, v + 2.7)  # on the stage's +5V track from pin 4 to its capacitor
        d.via("+5V", *at(*tap), 0.6, 0.3)
        d.track("+5V", [at(*tap), at(SPINE_U, tap[1])], "In6.Cu", 0.6)
    for u, v in vrm.TOP:
        tap = (u - 3.4, v + 3.08)  # on the +5V track to its capacitor, clear of pin 1
        d.via("+5V", *at(*tap), 0.6, 0.3)
        d.track("+5V", [at(*tap), at(tap[0], RUN_V)], "In6.Cu", 0.6)

    # ---- the memory slots' and M.2 sockets' supply pins ----------------------------------------------------
    for k, (ch, u) in enumerate(DIMMS.items()):
        dimm_vias(d, f"J{k + 1}", u, top_end=ch in "CD")
    m2_vias(d, M2_1, 270)
    m2_vias(d, M2_2, 90)
