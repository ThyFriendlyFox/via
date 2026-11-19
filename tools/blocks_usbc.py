"""blocks_usbc — the USB Type-C port block: a receptacle as a sink that takes 5 V, in 1 call.

`usbc(d, amps=..., detects=..., ...)` adds a USB Type-C receptacle wired for USB 2.0, the 2 Rd pull-downs
on CC1 and CC2, 2 ESD clamps on D+, D-, CC1 and CC2, and the capacitor on VBUS, to a kicadgen Design. Its
numbers stand in `rules/blocks/usbc.json`, each with its document, section, table and page: the USB Type-C
Cable and Connector Specification (Rd, the current each Rp advertisement allows, the CC voltages, the
receptacle's wiring) and the USB 2.0 Specification with its ECNs (the VBUS range and the capacitance a
device may put on VBUS). A part's own ratings are read from `library/facts/`, as `workcenter ratings`
reads them.

The block takes the current the design draws from VBUS and the highest advertisement the design reads
on CC (`detects`). It refuses, with the clause, a current that advertisement does not allow. Before it
returns it reads back what it added to the design and checks the wiring the specification asks for,
each Rd, each clamp and the capacitance on VBUS: a fault is 1 line with the value, the limit and the
clause. It hands the port's nets and their voltage ranges to ratings.json, and writes `sim/cc.cir`,
the CC pin under each advertisement, with its bounds.

Standard library only, as kicadgen is.
"""

from __future__ import annotations

import itertools
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import blocks
import ratings

RULES = blocks.RULES / "usbc.json"
LEVELS = ("default", "1.5A", "3.0A")
SIGNALS = ("VBUS", "GND", "D+", "D-", "CC1", "CC2")
# Where the block puts each clamp on the board, from the receptacle's centre, in mm.
CLAMP_AT = (1.5, -10.5)


def _number(x) -> bool:
    """A finite int or float, not a bool."""
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _shorts(j: str, nets: dict[str, str], signals_where: str, rd_where: str) -> list[str]:
    """1 line for each net that holds more than 1 of the port's signals."""
    held: dict[str, list[str]] = {}
    for signal in SIGNALS:
        held.setdefault(nets[signal], []).append(signal)
    out = []
    for net, signals in held.items():
        if len(signals) < 2:  # noqa: PLR2004
            continue
        names = f"{', '.join(signals[:-1])} and {signals[-1]}"
        where = signals_where + (f"; {rd_where}" if any(s.startswith("CC") for s in signals) else "")
        out.append(
            f"usbc {j}: {names} are on 1 net, {net}; each signal of the port asks a net of its own [{where}]"
        )
    return out


@dataclass
class Port:
    """What the block built, as its check reads it back."""

    connector: str  # the receptacle's ref
    pins: dict[str, list[str]]  # the receptacle's pin numbers by signal
    nets: dict[str, str]  # VBUS, GND, D+, D-, CC1, CC2 -> the design's net
    rd: tuple[str, str]  # the 2 Rd refs, on CC1 and CC2
    rd_span: tuple[float, float]  # ohms
    rd_tolerance: float  # of the stocked resistor the block took, from its facts
    esd: tuple[str, str]  # the clamp on D+ and D-, the clamp on CC1 and CC2
    esd_pins: dict[str, str]  # IO1, IO2, GND -> pin number
    standoff: float  # volts
    cap: str  # the capacitor's ref on VBUS
    farads: tuple[float, float]  # what the block's capacitor and the design's own give on VBUS
    most: dict[str, float]  # the greatest voltage of each signal, volts
    amps: float
    amps_vbus: float  # the receptacle's rating for its VBUS pins
    where: dict[str, str]  # the clause of each check


@dataclass
class UsbcBlock(blocks.Block):
    port: Port | None = field(default=None)


def _doc(data: dict, entry: dict) -> str:
    return f"{data['documents'][entry['doc']]['short']}, {entry['where']}"


def _wiring(data: dict, key: str) -> str:
    return f"{data['documents']['typec']['short']}, {data['wiring'][key]}"


def usbc(  # noqa: PLR0913, PLR0915
    d,
    *,
    amps: float,
    detects: str,
    nets: tuple[str, str, str, str, str, str],
    stock: list[blocks.Stock],
    facts: Path,
    sch_at: tuple[float, float],
    pcb_at: tuple[float, float],
    farads: tuple[float, float] = (0.0, 0.0),
    connector: str = "USB4115-03-C",
    refs: dict[str, str] | None = None,
    rules: Path = RULES,
) -> UsbcBlock:
    """A USB Type-C receptacle as a sink from `nets` = (VBUS, GND, D+, D-, CC1, CC2). `amps` is what the
    design draws from VBUS; `detects` the highest advertisement the design reads on CC: "default" (it
    reads none), "1.5A" or "3.0A". `farads` is the least and the greatest capacitance the design puts on
    VBUS beside the block's own capacitor."""
    refs = {"connector": "J1", "rd": "R1 R2", "esd": "U1 U2", "vbus": "C1"} | (refs or {})
    j = refs["connector"]
    data = blocks.load_rules(rules)
    typec = data["documents"]["typec"]["short"]
    if detects not in LEVELS:
        raise blocks.Refused(f"usbc {j}: detects={detects!r}: one of {', '.join(LEVELS)} is asked")
    plug = next((c for c in data["connectors"] if c["mpn"] == connector), None)
    if plug is None:
        names = ", ".join(c["mpn"] for c in data["connectors"])
        raise blocks.Refused(
            f"usbc {j}: {connector} is no receptacle of {Path(rules).name}; it holds {names}"
        )
    ads = {a["name"]: a for a in data["advertisements"]}

    # What the call gives, before any number is worked out of it.
    if not _number(amps):
        raise blocks.Refused(f"usbc {j}: amps={amps!r}: a number of amperes is asked")
    if (
        not isinstance(nets, (tuple, list))
        or len(nets) != len(SIGNALS)
        or not all(isinstance(n, str) and n for n in nets)
    ):
        raise blocks.Refused(
            f"usbc {j}: nets={nets!r}: 6 net names are asked, for {', '.join(SIGNALS[:-1])} and {SIGNALS[-1]}"
        )
    shorts = _shorts(j, dict(zip(SIGNALS, nets, strict=True)), f"{typec}, {data['signals']['where']}",
                     _doc(data, data["rd"]))  # fmt: skip
    if shorts:
        raise blocks.Refused("\n".join(shorts))
    if (
        not isinstance(farads, (tuple, list))
        or len(farads) != 2  # noqa: PLR2004
        or not all(_number(x) and x >= 0 for x in farads)
        or farads[0] > farads[1]
    ):
        raise blocks.Refused(
            f"usbc {j}: farads={farads!r}: (least, most) is asked, in farads, each 0 or more, the least first"
        )

    # The current: the least advertisement that allows it, held to the one the design can read.
    if amps <= 0:
        raise blocks.Refused(
            f"usbc {j}: a load of {ratings.si(amps, 'A')}: the block sizes the port for a load over 0 A "
            f"[{_doc(data, ads['default'])}]"
        )
    needed = next((a for a in data["advertisements"] if amps <= a["amps"] * (1 + ratings.EPS)), None)
    if needed is None:
        top = data["advertisements"][-1]
        raise blocks.Refused(
            f"usbc {j}: a load of {ratings.si(amps, 'A')} is over the {ratings.si(top['amps'], 'A')} of the "
            f"highest advertisement [{_doc(data, top)}; {_doc(data, data['beyond'])}]"
        )
    read = ads[detects]
    if LEVELS.index(needed["name"]) > LEVELS.index(detects):
        raise blocks.Refused(
            f"usbc {j}: a load of {ratings.si(amps, 'A')} is over the {ratings.si(read['amps'], 'A')} that "
            f"{detects}, the highest advertisement the design detects, allows [{_doc(data, read)}]; "
            f"{needed['name']} allows {ratings.si(needed['amps'], 'A')} [{_doc(data, needed)}]"
        )
    sums = [
        f"{j}: a load of {ratings.si(amps, 'A')} needs the {needed['name']} advertisement, which allows "
        f"{ratings.si(needed['amps'], 'A')}; the design detects up to {detects} [{_doc(data, needed)}]"
    ]
    unit = data["unit_load"]
    if needed["name"] == "default" and amps > unit["value"] * (1 + ratings.EPS):
        # The block wires D+ and D-: the sink is a USB 2.0 device, not a Power Sinking Device.
        sums.append(
            f"{j}: {nets[2]} and {nets[3]} are wired, so the sink connects as a USB 2.0 device and draws at "
            f"most {ratings.si(unit['value'], 'A')} until it is configured; whether the design waits for its "
            f"configuration is not judged: the block cannot see the firmware [{_doc(data, unit)}; {typec}, "
            f"{unit['psd']}]"
        )
    # Each step up asks the part that reads CC for the threshold of table 4-36 between the 2 ranges, set
    # inside the threshold's band: a range's own end lies outside that band.
    for below, ad in itertools.pairwise(data["advertisements"][: LEVELS.index(needed["name"]) + 1]):
        t_lo, t_hi = ad["threshold"]
        sums.append(
            f"{nets[4]}, {nets[5]}: draw over {ratings.si(below['amps'], 'A')} only while {nets[4]} or "
            f"{nets[5]} is over the threshold, which the part that reads CC sets within {t_lo:g} V to "
            f"{t_hi:g} V [{typec}, {ad['threshold_where']}; {_doc(data, data['adjust'])}]"
        )

    found = ratings.read_facts(Path(facts))
    kind = "detects" if detects != "default" else "default"

    # Rd: the first stocked resistor whose value and tolerance stay inside table 4-28's span.
    rd = data["rd"]
    tol = rd["tolerance"][kind]
    lo, hi = rd["ohms"] * (1 - tol), rd["ohms"] * (1 + tol)
    rd_where = _doc(data, rd)
    missed = []
    taken = None
    for s in stock:
        f = blocks._facts(found, s)
        if f is None or f.kind != "resistor":
            continue
        ohms, t = ratings.part_value(s.value), f.data["tolerance"]
        if ohms is None:
            missed.append(f"{s.mpn}: its Value {s.value!r} names no resistance")
            continue
        least, most = ohms * (1 - t), ohms * (1 + t)
        if least < lo * (1 - ratings.EPS) or most > hi * (1 + ratings.EPS):
            missed.append(f"{s.mpn} is {ratings.si(least, 'ohm')} to {ratings.si(most, 'ohm')}")
        else:
            taken = (s, f, least, most)
            break
    span = (
        f"Rd of {ratings.si(rd['ohms'], 'ohm')} +-{tol * 100:g} %, "
        f"{ratings.si(lo, 'ohm')} to {ratings.si(hi, 'ohm')}"
    )
    if taken is None:
        why = f": {', '.join(missed)}" if missed else ""
        raise blocks.Refused(f"usbc {j}: no stocked resistor with facts is {span}{why} [{rd_where}]")
    res, res_facts, least, most = taken
    r1, r2 = refs["rd"].split()
    sums.append(
        f"{r1}, {r2}: {span}; {res.mpn}, {res.value} {res_facts.data['tolerance'] * 100:g} %, is "
        f"{ratings.si(least, 'ohm')} to {ratings.si(most, 'ohm')} [{rd_where}]"
    )

    # The clamps: the protection part whose facts stand off the most each protected line reaches.
    cc_most = data["cc_max"]["volts"][kind]
    data_most = data["data_volts"]["value"][1]
    clamp = data["protection"][0]
    clamp_facts = blocks._facts(
        found, blocks.Stock("", clamp["mpn"], "", clamp["footprint"]), clamp["symbol"]
    )
    if clamp_facts is None:
        raise blocks.Refused(f"usbc {j}: {facts} holds no facts of {clamp['mpn']}")
    standoff = clamp_facts.data["volts_standoff"]
    u1, u2 = refs["esd"].split()
    cc_where = f"{typec}, {data['cc_max']['where']}"
    sums.append(
        f"{u1}, {u2}: {clamp['mpn']} stands off {ratings.si(standoff, 'V')} [{clamp_facts.source}]; "
        f"{nets[2]} and {nets[3]} reach {ratings.si(data_most, 'V')} [{_doc(data, data['data_volts'])}], "
        f"{nets[4]} and {nets[5]} {ratings.si(cc_most, 'V')} [{cc_where}]; each is placed "
        f"{math.hypot(*CLAMP_AT):.3g} mm from {j}'s centre, and the length of copper from {j} to each after "
        f"routing is not judged: the block runs before the router "
        f"[{clamp['source']['document']}, {clamp['placement']['where']}]"
    )

    # VBUS: the first stocked capacitor that keeps the total within CRPB at 0 V and at 5.25 V.
    c_lo, c_hi = data["vbus_farads"]["value"]
    bias = data["vbus_bias"]["value"]
    v_most = data["vbus_volts"]["value"][1]
    cap_where = _doc(data, data["vbus_farads"])
    own = f"the design's own {ratings.si(farads[0], 'F')} to {ratings.si(farads[1], 'F')}"
    if farads[1] > c_hi * (1 + ratings.EPS):
        raise blocks.Refused(
            f"usbc {j}: {own} on {nets[0]} is over {ratings.si(c_hi, 'F')} before the block adds a part "
            f"[{cap_where}]"
        )
    missed = []
    cap = None
    for s in stock:
        f = blocks._facts(found, s)
        if f is None or not f.kind.startswith("capacitor"):
            continue
        value = ratings.part_value(s.value)
        t = f.data.get("tolerance")
        if value is None:
            missed.append(f"{s.mpn}: its Value {s.value!r} names no capacitance")
            continue
        if t is None or "volts" not in f.data:
            missed.append(f"{s.mpn}: its facts give no tolerance or no voltage rating")
            continue
        if f.data["volts"] < v_most:
            missed.append(
                f"{s.mpn}: rated {ratings.si(f.data['volts'], 'V')}, under {ratings.si(v_most, 'V')}"
            )
            continue
        share = ratings.kept_at(f.data["kept"], bias) if "kept" in f.data else None
        if share is None:
            missed.append(f"{s.mpn}: its facts give no value it keeps at {ratings.si(bias, 'V')}")
            continue
        small, big = value * (1 - t) * share + farads[0], value * (1 + t) + farads[1]
        if big > c_hi * (1 + ratings.EPS):
            missed.append(f"{s.mpn}: up to {ratings.si(big, 'F')}, over {ratings.si(c_hi, 'F')}")
        elif small < c_lo * (1 - ratings.EPS):
            missed.append(
                f"{s.mpn}: {ratings.si(small, 'F')} at {ratings.si(bias, 'V')}, under {ratings.si(c_lo, 'F')}"
            )
        else:
            cap = (s, f, share, small, big)
            break
    if cap is None:
        why = f": {'; '.join(missed)}" if missed else ""
        raise blocks.Refused(
            f"usbc {j}: no stocked capacitor keeps {nets[0]} within {ratings.si(c_lo, 'F')} to "
            f"{ratings.si(c_hi, 'F')} with {own}{why} [{cap_where}]"
        )
    c, cf, share, small, big = cap
    value = ratings.part_value(c.value)
    t = cf.data["tolerance"]
    sums.append(
        f"{refs['vbus']}: {c.mpn} on {nets[0]}: {ratings.si(value, 'F')} x {1 - t:g} x {share:.4f} = "
        f"{ratings.si(value * (1 - t) * share, 'F')} at {ratings.si(bias, 'V')} to "
        f"{ratings.si(value, 'F')} x {1 + t:g} = {ratings.si(value * (1 + t), 'F')}, with {own}: "
        f"{ratings.si(small, 'F')} to {ratings.si(big, 'F')}, within {ratings.si(c_lo, 'F')} to "
        f"{ratings.si(c_hi, 'F')} [{cap_where}; {_doc(data, data['vbus_bias'])}; {cf.source}]"
    )

    # The parts, placed from the block's corner on the sheet and on the board.
    vbus, gnd, dp, dm, cc1, cc2 = nets
    pins = plug["pins"]
    sig = {"VBUS": vbus, "GND": gnd, "SHIELD": gnd, "CC1": cc1, "CC2": cc2, "D+": dp, "D-": dm}
    sx, sy = sch_at
    px, py = pcb_at
    d.add(j, plug["symbol"], plug["value"], plug["footprint"], sch_at=(sx, sy), pcb_at=(px, py),
          nets={n: sig[name] for name, numbers in pins.items() if name in sig for n in numbers})  # fmt: skip
    d.add(r1, "Device:R", res.value, res.footprint, sch_at=(sx + 30.48, sy - 5.08),
          pcb_at=(px - 3.0, py - 7.5), pcb_rot=90, nets={"1": cc1, "2": gnd})  # fmt: skip
    d.add(r2, "Device:R", res.value, res.footprint, sch_at=(sx + 40.64, sy - 5.08),
          pcb_at=(px + 3.0, py - 7.5), pcb_rot=90, nets={"1": cc2, "2": gnd})  # fmt: skip
    io = clamp["pins"]
    cx, cy = CLAMP_AT
    d.add(u1, clamp["symbol"], clamp["value"], clamp["footprint"], sch_at=(sx + 30.48, sy + 15.24),
          pcb_at=(px - cx, py + cy), nets={io["IO1"]: dp, io["IO2"]: dm, io["GND"]: gnd})  # fmt: skip
    d.add(u2, clamp["symbol"], clamp["value"], clamp["footprint"], sch_at=(sx + 45.72, sy + 15.24),
          pcb_at=(px + cx, py + cy), nets={io["IO1"]: cc1, io["IO2"]: cc2, io["GND"]: gnd})  # fmt: skip
    d.add(refs["vbus"], "Device:C", c.value, c.footprint, sch_at=(sx + 55.88, sy - 5.08),
          pcb_at=(px + 6.5, py - 8.0), pcb_rot=90, nets={"1": vbus, "2": gnd})  # fmt: skip

    port = Port(
        connector=j,
        pins=pins,
        nets={"VBUS": vbus, "GND": gnd, "D+": dp, "D-": dm, "CC1": cc1, "CC2": cc2},
        rd=(r1, r2),
        rd_span=(lo, hi),
        rd_tolerance=res_facts.data["tolerance"],
        esd=(u1, u2),
        esd_pins=io,
        standoff=standoff,
        cap=refs["vbus"],
        farads=farads,
        most={"D+": data_most, "D-": data_most, "CC1": cc_most, "CC2": cc_most},
        amps=amps,
        amps_vbus=plug["amps_vbus"]["value"],
        where={
            "shell": _wiring(data, "shell"),
            "vbus": _wiring(data, "vbus"),
            "gnd": _wiring(data, "gnd"),
            "data": _wiring(data, "data"),
            "sbu": _wiring(data, "sbu"),
            "unused": _wiring(data, "unused"),
            "signals": f"{typec}, {data['signals']['where']}",
            "rd": rd_where,
            "cc": cc_where,
            "data_volts": _doc(data, data["data_volts"]),
            "farads": cap_where,
            "amps": f"{plug['source']['document']}, {plug['amps_vbus']['where']}",
        },
    )
    faults = check(d, port)
    if faults:
        raise blocks.Refused("\n".join(faults))
    sums.append(
        f"{j}: the shell and the 4 GND pins on {gnd}, the 4 VBUS pins on {vbus}, A6 and B6 on {dp}, "
        f"A7 and B7 on {dm}, SBU1, SBU2 and the unused pins not connected [{typec}, section 3.2.1, note 11, "
        "page 47; section 3.2.3, table 3-5, notes 1 to 5, page 77]; the length of the A6 to B6 and A7 to B7 "
        f"shorts, at most {data['short']['value_mm']:g} mm, is not judged: the block runs before the router "
        f"[{_doc(data, data['short'])}]"
    )

    rows = blocks.rows_of(
        [(blocks.Stock(plug["maker"], plug["mpn"], plug["value"], plug["footprint"]), 1), (res, 2),
         (blocks.Stock(clamp["maker"], clamp["mpn"], clamp["value"], clamp["footprint"]), 2), (c, 1)]
    )  # fmt: skip
    call = f"usbc(amps={amps:g}, detects={detects!r})"
    entries = {
        "nets": {
            vbus: {
                "volts": data["vbus_volts"]["value"],
                "source": f"{_doc(data, data['vbus_volts'])}; {call}",
            },
            dp: {"volts": data["data_volts"]["value"], "source": f"{_doc(data, data['data_volts'])}; {call}"},
            dm: {"volts": data["data_volts"]["value"], "source": f"{_doc(data, data['data_volts'])}; {call}"},
            cc1: {"volts": [0, cc_most], "source": f"{cc_where}; {call}"},
            cc2: {"volts": [0, cc_most], "source": f"{cc_where}; {call}"},
        }
    }
    files = cc_deck(j, data, detects, res, res_facts, sums)
    return UsbcBlock("usbc", sums, entries, rows, files, port)


def _nets_of(d, ref: str) -> dict[str, str]:
    part = next((p for p in d.parts if p.ref == ref), None)
    return {} if part is None else dict(part.nets)


def check(d, port: Port) -> list[str]:  # noqa: PLR0912
    """Read back what the block added to the design and check it; 1 line per fault, with the value, the
    limit and the clause. An empty list: the port is as the specification asks."""
    j = port.connector
    # 2 signals on 1 net is a short, whatever each pin reads: CC1 and CC2 together put both Rd on each pin.
    shorts = _shorts(j, port.nets, port.where["signals"], port.where["rd"])
    if shorts:
        return shorts
    out: list[str] = []
    jn = _nets_of(d, j)
    if not jn:
        return [f"usbc {j}: no part {j} in the design"]
    gnd = port.nets["GND"]

    def pins_on(signal: str, net: str, key: str) -> None:
        wrong = [n for n in port.pins[signal] if jn.get(n) != net]
        if wrong:
            got = ", ".join(f"{n} on {jn.get(n, 'nothing')}" for n in wrong)
            out.append(f"usbc {j}: {signal} pins {got}, not {net} [{port.where[key]}]")

    pins_on("VBUS", port.nets["VBUS"], "vbus")
    pins_on("GND", gnd, "gnd")
    pins_on("SHIELD", gnd, "shell")
    pins_on("D+", port.nets["D+"], "data")
    pins_on("D-", port.nets["D-"], "data")
    pins_on("CC1", port.nets["CC1"], "rd")
    pins_on("CC2", port.nets["CC2"], "rd")
    for signal, key in (("SBU", "sbu"), ("UNUSED", "unused")):
        joined = [n for n in port.pins.get(signal, []) if n in jn]
        if joined:
            pins = ", ".join(f"{n} on {jn[n]}" for n in joined)
            out.append(f"usbc {j}: {signal} pins {pins} [{port.where[key]}]")
    parts = {p.ref: p for p in d.parts}
    for signal, ref in zip(("CC1", "CC2"), port.rd, strict=True):
        p = parts.get(ref)
        net = port.nets[signal]
        if p is None or sorted(p.nets.values()) != sorted([net, gnd]):
            got = "missing" if p is None else f"on {', '.join(sorted(set(p.nets.values())))}"
            out.append(
                f"usbc {j}: Rd {ref} on {signal} is {got}, not between {net} and {gnd} [{port.where['rd']}]"
            )
            continue
        ohms, t = ratings.part_value(p.value), port.rd_tolerance
        lo, hi = port.rd_span
        if ohms is None:
            out.append(
                f"usbc {j}: Rd {ref} has the Value {p.value!r}, which names no resistance "
                f"[{port.where['rd']}]"
            )
        elif ohms * (1 - t) < lo * (1 - ratings.EPS) or ohms * (1 + t) > hi * (1 + ratings.EPS):
            out.append(
                f"usbc {j}: Rd {ref} is {ratings.si(ohms * (1 - t), 'ohm')} to "
                f"{ratings.si(ohms * (1 + t), 'ohm')}, outside {ratings.si(lo, 'ohm')} to "
                f"{ratings.si(hi, 'ohm')} [{port.where['rd']}]"
            )
    io = port.esd_pins
    for ref, signals in zip(port.esd, (("D+", "D-"), ("CC1", "CC2")), strict=True):
        p = parts.get(ref)
        want = {io["IO1"]: port.nets[signals[0]], io["IO2"]: port.nets[signals[1]], io["GND"]: gnd}
        if p is None or p.nets != want:
            got = "missing" if p is None else ", ".join(f"pin {k} on {v}" for k, v in sorted(p.nets.items()))
            out.append(
                f"usbc {j}: the clamp {ref} of {' and '.join(signals)} is {got} [{port.where['cc']}; "
                f"{port.where['data_volts']}]"
            )
            continue
        for s in signals:
            if port.most[s] > port.standoff * (1 + ratings.EPS):
                out.append(
                    f"usbc {j}: {s} reaches {ratings.si(port.most[s], 'V')}, over the "
                    f"{ratings.si(port.standoff, 'V')} {ref} stands off "
                    f"[{port.where['data_volts'] if s.startswith('D') else port.where['cc']}]"
                )
    c = parts.get(port.cap)
    if c is None or sorted(c.nets.values()) != sorted([port.nets["VBUS"], gnd]):
        out.append(
            f"usbc {j}: {port.cap} is not between {port.nets['VBUS']} and {gnd} [{port.where['farads']}]"
        )
    if port.amps > port.amps_vbus * (1 + ratings.EPS):
        out.append(
            f"usbc {j}: {ratings.si(port.amps, 'A')} on VBUS is over the receptacle's "
            f"{ratings.si(port.amps_vbus, 'A')} [{port.where['amps']}]"
        )
    return out


def cc_deck(
    j: str, data: dict, detects: str, res: blocks.Stock, res_facts, sums: list[str]
) -> dict[str, str]:
    """sim/cc.cir and its bounds: the sink's CC pin under each source advertisement, Rp pulled up to the
    pull-up's range (table 4-27) into the block's Rd. A sink that reads the advertisement is held to
    each one's range of table 4-36; one that reads none to vRd-connected, the same table's widest."""
    typec = data["documents"]["typec"]["short"]
    lo, hi = data["pullup_volts"]["value"]
    mid = (lo + hi) / 2
    half = (hi - lo) / 2 / mid
    ohms = ratings.part_value(res.value)
    names = {"default": "vrd_usb", "1.5A": "vrd_15", "3.0A": "vrd_30"}
    lines = [
        f"cc: the CC pin of the USB-C block {j} under each advertisement, written by tools/blocks_usbc.py",
        f"* Rp pulls up to {_n(lo)} V to {_n(hi)} V, the .param vpu at {_n(mid)} V +-{half * 100:.4f} % "
        f"[{typec}, {data['pullup_volts']['where']}].",
        f"* Rd is {j}'s {res.value}, {res.mpn}, the .param rd at {res_facts.data['tolerance'] * 100:g} % "
        f"[{res_facts.source}].",
        f"* Not judged: Rp as the 2 other columns of {typec}, {data['rp_not_modelled']['where']}; the deck "
        f"models the resistor pull-up to {_n(lo)} V to {_n(hi)} V alone.",
        "* The sums:",
        *[f"*   {line}" for line in sums],
        f".param vpu={_n(mid)}",
        f".param rd={_n(ohms)}",
    ]
    expect: dict = {}
    parts: dict = {"vpu": round(half, 9), "rd": res_facts.data["tolerance"]}
    connected = data["connected"]
    for k, ad in enumerate(data["advertisements"]):
        rp = ad["rp"]
        lines += [
            f"VPU{k} pu{k} 0 {{vpu}}",
            f"RP{k} pu{k} cc{k} {_n(rp['ohms'])}",
            f"RD{k} cc{k} 0 {{rd}}",
        ]
        parts[f"RP{k}"] = rp["tolerance"]
        name = names[ad["name"]]
        if detects == "default":
            bound, where = connected["cc"], f"{typec}, {connected['where']}"
        else:
            bound, where = ad["cc"], f"{typec}, {ad['cc_where']}"
        expect[name] = {
            "min": bound[0],
            "max": bound[1],
            "source": f"Rp of {ad['name']} [{typec}, {ad['rp_where']}] into Rd: {where}",
        }
    lines += [".control", "op"]
    for k, ad in enumerate(data["advertisements"]):
        lines += [f"let {names[ad['name']]} = v(cc{k})", f"print {names[ad['name']]}"]
    lines += [".endc", ".end"]
    corners = {
        "tolerance": {
            "parts": parts,
            "source": f"Rp from {typec}, table 4-27, page 245; the pull-up from the same table; Rd from "
            f"{res_facts.source}",
        }
    }
    return {
        "sim/cc.cir": "\n".join(lines) + "\n",
        "sim/cc.expect.json": json.dumps(expect, indent=2) + "\n",
        "sim/corners.json": json.dumps(corners, indent=2) + "\n",
    }


def _n(x: float) -> str:
    return f"{x:.6g}"
