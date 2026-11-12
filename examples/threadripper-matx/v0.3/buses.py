"""The board's buses, drawn as tracks and vias: DDR5 from the processor to its 4 slots.

Each memory channel leaves the socket from the side nearest its slot and each row of a slot's pins
gets a layer of its own (F.Cu, In2, In3, In6). On every layer the 72 lands and the 72 pins are paired
in order along v, so no 2 traces of a layer cross. A trace runs:

1. from its land, 45 degrees into the gap below the land's row (a land past the outermost column
   carries a via in the land, so the trace starts on its layer);
2. along that gap out of the socket: every via in the array sits on a land, none in a gap, so each
   gap carries 1 trace on every layer;
3. into the comb beside the socket: a column of its own, up or down to its lane. The trace that moves
   up the furthest takes the column nearest the socket, and so on outward, so a trace's last leg never
   crosses another's column; upward and downward traces share the columns;
4. along its lane to the slot: on F.Cu straight onto its pad; on an inner layer half a pin pitch
   (0.425 mm) off its pin's line, which passes every via of the slots between the pin rows' vias, then
   a 45 degree jog onto its pin's line, a via, and a short F.Cu stub to the pad.

The slots' ground pins each take a via between the 2 pin rows. The processor's land of each trace is
its pin in the pin map (pinmap.assign()).
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import mech
import pinmap

HERE = Path(__file__).resolve().parent

W = 0.1  # the buses' track width
LANE = 0.425  # half the slot's 0.85 mm pitch: an inner trace's offset from its pin's line
STEP = 0.25  # the comb's column pitch
CHAMFER = 0.3  # each corner of a trace cut at 45 degrees
NON_BUS = {"VSS", "VIN_BULK", "VIN_MGMT", "RFU", "HSCL", "HSDA", "HSA", "PCAMP", "DLBDQ", "DLBDQS"}
# side -> [(channel, row, layer)] by the land's depth in its band
PLAN = {
    "L": [("A", "front", "F.Cu"), ("A", "back", "In2.Cu"), ("B", "front", "In3.Cu"), ("B", "back", "In6.Cu")],
    "R": [("C", "front", "F.Cu"), ("C", "back", "In2.Cu"), ("D", "front", "In3.Cu"), ("D", "back", "In6.Cu")],
}
# The DIMM side: the pin rows' offsets from the slot's centre line, toward the processor (+) or away (-)
ROW_U = {"front": 2.05, "back": -2.05}
GND_VIA_U = {"front": 0.7, "back": -0.7}  # a ground pin's via, between the rows
SIG_VIA_U = {"front": 3.4, "back": -3.4}  # a signal pin's via, outside its row


def dimm_pins() -> list[tuple[str, str]]:
    with (HERE / "pins" / "ddr5_rdimm.csv").open(encoding="utf-8") as fh:
        return [(r["pin"], r["name"].split("/")[0]) for r in csv.DictReader(fh) if r["pin"] != "220"]


def net_of(ch: str, name: str) -> str:
    return f"M{ch}_{name}"


def dimm_rot(ch: str) -> int:
    return 90 if ch in "AB" else 270


def toward_cpu(ch: str) -> int:
    """+1 when the processor lies toward +u from the slot."""
    return 1 if ch in "AB" else -1


def pad_uv(ch: str, pin: str) -> tuple[float, float]:
    """A slot pin's pad centre in mech.py's frame."""
    import make_footprints  # noqa: PLC0415

    x, y = make_footprints.dimm_pads()[pin]
    th = math.radians(dimm_rot(ch))
    u0, v0 = mech.DIMMS[ch], mech.DIMM_V
    return (round(u0 + x * math.cos(th) + y * math.sin(th), 4), round(v0 - x * math.sin(th) + y * math.cos(th), 4))


@dataclass
class Trace:
    net: str
    layer: str
    land: pinmap.Land
    pin: str
    row: str
    ch: str


def plan() -> list[Trace]:
    """Every DDR5 trace: its land, its pin and its layer."""
    pins = dimm_pins()
    out: list[Trace] = []
    for side, layers in PLAN.items():
        for depth, (ch, row, layer) in enumerate(layers):
            mine = [(p, n) for p, n in pins if n not in NON_BUS and (int(p) <= 144) == (row == "front")]
            mine.sort(key=lambda pn: pad_uv(ch, pn[0])[1])
            lands = pinmap.ddr_lands(side, depth)
            # The 72 lands nearest the array's middle row, top to bottom.
            best = min(range(len(lands) - len(mine) + 1),
                       key=lambda i: abs((lands[i].r + lands[i + len(mine) - 1].r) / 2 - (pinmap.ROWS - 1) / 2))
            for land, (pin, name) in zip(lands[best : best + len(mine)], mine, strict=True):
                out.append(Trace(net_of(ch, name), layer, land, pin, row, ch))
    return out


def land_nets() -> dict[str, str]:
    return {t.land.name: t.net for t in plan()}


def dimm_nets(ch: str) -> dict[str, str]:
    return {t.pin: t.net for t in plan() if t.ch == ch}


def chamfered(pts: list[tuple[float, float]], c: float = CHAMFER) -> list[tuple[float, float]]:
    """A polyline of right angles with each inner corner cut at 45 degrees by up to c."""
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for a, b, n in zip(pts, pts[1:], pts[2:], strict=False):
        la = math.hypot(b[0] - a[0], b[1] - a[1])
        lb = math.hypot(n[0] - b[0], n[1] - b[1])
        k = min(c, la / 2, lb / 2)
        if k < 0.05:
            out.append(b)
            continue
        out.append((round(b[0] - (b[0] - a[0]) / la * k, 4), round(b[1] - (b[1] - a[1]) / la * k, 4)))
        out.append((round(b[0] + (n[0] - b[0]) / lb * k, 4), round(b[1] + (n[1] - b[1]) / lb * k, 4)))
    out.append(pts[-1])
    return out


def route(d, at) -> None:
    """Draw every DDR5 trace, its vias, and the slots' ground vias."""
    traces = plan()
    cu, cv = mech.CPU
    by_layer: dict[tuple[str, str], list[Trace]] = {}
    for t in traces:
        by_layer.setdefault((t.land.side, t.layer), []).append(t)
    for (side, layer), group in by_layer.items():
        out = -1 if side == "L" else 1  # the direction from the socket toward its slots
        # The comb: from just outside the outermost lands toward the near slot's pads.
        edge = min(x.u for x in pinmap.lands()) if side == "L" else max(x.u for x in pinmap.lands())
        x0 = cu + edge + out * 1.0
        near = "A" if side == "L" else "C"
        x_stop = mech.DIMMS[near] + toward_cpu(near) * (2.8 + 0.5)
        group.sort(key=lambda t: t.land.v)
        src = [cv + t.land.v + 0.405 for t in group]
        dst = [pad_uv(t.ch, t.pin)[1] + (0.0 if t.layer == "F.Cu" else LANE) for t in group]
        column: dict[int, float] = {}
        ups = [i for i in range(len(group)) if dst[i] < src[i] - 1e-6]
        downs = [i for i in reversed(range(len(group))) if dst[i] > src[i] + 1e-6]
        for order in (ups, downs):
            for k, i in enumerate(order):
                column[i] = x0 + out * k * STEP
        lim = x0 + out * (max(len(ups), len(downs)) - 1) * STEP
        assert (lim - x_stop) * out <= 0, f"{side} {layer}: the comb needs {lim:.2f}, the slot starts at {x_stop:.2f}"
        for i, t in enumerate(group):
            lx, ly = cu + t.land.u, cv + t.land.v
            if layer != "F.Cu":
                d.via(t.net, *at_abs(lx, ly), 0.4, 0.2)
            stub = (lx + out * 0.405, src[i])
            pts = [stub]  # the escape (land to stub) keeps its exact 45 degrees; the comb's corners are cut
            if i in column:
                pts += [(column[i], src[i]), (column[i], dst[i])]
            pu, pv = pad_uv(t.ch, t.pin)
            if layer == "F.Cu":
                pts.append((pu, pv))
            else:
                du = toward_cpu(t.ch)
                via_u = mech.DIMMS[t.ch] + du * SIG_VIA_U[t.row]
                if t.row == "back":
                    jog = mech.DIMMS[t.ch] - du * 1.2  # past the slot's own back ground vias
                else:
                    a = "A" if t.ch == "B" else "C"
                    jog = mech.DIMMS[a] - du * (3.4 + 0.5)  # past the near slot's back-pin vias
                pts += [(jog, dst[i]), (jog - du * LANE, pv), (via_u, pv)]
                d.via(t.net, *at_abs(via_u, pv), 0.4, 0.2)
                d.track(t.net, [at_abs(via_u, pv), at_abs(pu, pv)], "F.Cu", 0.2)
            comb = chamfered(pts[:4]) + pts[4:] if i in column else pts
            d.track(t.net, [at_abs(lx, ly)] + [at_abs(*p) for p in comb], layer, W)
    # The slots' ground pins: a via between the rows, and a stub from the pad.
    for ch in mech.DIMMS:
        for pin, name in dimm_pins():
            if name != "VSS":
                continue
            row = "front" if int(pin) <= 144 else "back"
            pu, pv = pad_uv(ch, pin)
            gu = mech.DIMMS[ch] + toward_cpu(ch) * GND_VIA_U[row]
            d.via("GND", *at_abs(gu, pv), 0.4, 0.2)
            d.track("GND", [at_abs(pu, pv), at_abs(gu, pv)], "F.Cu", 0.25)


def at_abs(u: float, v: float) -> tuple[float, float]:
    """A point of mech.py's frame in board coordinates."""
    return mech.at(u, v)
