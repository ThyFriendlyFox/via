"""blocks_i2c - the I2C bus block: the 2 pull-ups of a bus, by TI SLVA689A, "I2C Bus Pullup Resistor
Calculation".

`blocks.i2c(...)` takes the bus voltage, the speed and the bus capacitance (stated, or summed from each
device's pin capacitance in its facts and a stated track), and every device on the bus by its part number.
It works out RP(min) from the low level and the sink current (equation 1 and table 2-1) and from each
device's own sink, and RP(max) from the rise time and the bus capacitance (equation 6 and table 2-1). It
takes the first stocked resistor that holds both bounds at its tolerance, and refuses with the equation
when the bounds cross or no stocked value lies between them. Each device's bus pins are held to their
voltage limits, each pin named SDA or SCL to its own line, and no ground pin may sit on the supply the
pull-ups go to; the block states that supply's span, `volts`, for `workcenter ratings`. The block reads
its 2 pull-ups back from the design before it returns, and writes a deck that holds the rise of SDA to
the speed's limit.

The numbers of the note stand in `rules/blocks/i2c.json`, each with its section, table and page.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path
from types import SimpleNamespace

import ratings
from blocks import RULES, Block, Refused, Stock, _g, load_rules, rows_of

SPEEDS = {"standard": "standard mode", "fast": "fast mode", "fast-plus": "fast mode plus"}
BUS_ROLES = ("open_drain", "io", "input")


def _ohms(x: float) -> str:
    """A resistance as a deck writes it: 2200 is 2.2k."""
    return f"{x / 1e3:g}k" if x >= 1e3 else f"{x:g}"


def _where(note: dict, text: str) -> str:
    return f"{note['short']}, {text}"


def _resolve(limit, part, pin_of: dict, vdd: str, top: float) -> tuple[float | None, str]:
    """A limit of a pin as a voltage on this bus: a number, or another pin's net plus a margin when that
    pin is on the bus's supply. (None, the pin's name and its net) when it follows a pin on another net."""
    for one in limit if isinstance(limit, list) else [limit]:
        if not isinstance(one, dict):
            continue
        numbers = pin_of.get(one["pin"], {}).get("numbers", [])
        net = next((part.nets[n] for n in numbers if n in part.nets), None)
        if net != vdd:
            return None, f"{one['pin']}, on {net or 'no net'}"
    values = [
        top + one["plus"] if isinstance(one, dict) else one
        for one in (limit if isinstance(limit, list) else [limit])
    ]
    return min(values), ""


def _bus_parts(d, lines: tuple[str, str], devices: dict, found, facts: Path, mine: set[str]):
    """Each part on SDA or SCL, line by line: (line, part, its pin number, its facts or None for a
    connector). A part that is neither a named device nor a connector is refused."""
    out = []
    for line in lines:
        for part in d.parts:
            if part.ref in mine:
                continue
            for number, net in part.nets.items():
                if net != line:
                    continue
                if part.ref in devices:
                    stock = SimpleNamespace(ref=part.ref, symbol=part.symbol.lib_id, footprint="")
                    f = ratings.facts_of(found, stock, devices[part.ref])
                    if f is None:
                        raise Refused(f"i2c {part.ref}: {facts} holds no facts of {devices[part.ref]}")
                    if "pins" not in f.data:
                        raise Refused(
                            f"i2c {part.ref}: the facts of {devices[part.ref]} give no pins (a {f.kind}): "
                            f"the block judges a device on the bus by its pins [{f.source}]"
                        )
                    out.append((line, part, number, f))
                elif part.symbol.lib_id.startswith("Connector"):
                    out.append((line, part, number, None))
                else:
                    raise Refused(
                        f"i2c {part.ref}: on {line}, and `devices` names no part number for it: the block "
                        "judges each device on the bus by its facts"
                    )
    return out


def _src(f, pin: dict) -> str:
    return f"{f.source}, {ratings._p(pin['page'])}" if "page" in pin else f.source


def _device_nets(part, f, nets: tuple[str, str, str], pair: str) -> None:
    """Each pin of a device on the bus where its facts name it: a pin named SDA on the data line, SCL on
    the clock line, and no ground on the net the pull-ups go to."""
    sda, scl, vdd = nets
    for pin in f.data["pins"]:
        here = [(n, part.nets.get(n)) for n in pin["numbers"]]
        if pin["role"] == "ground" and any(net == vdd for _, net in here):
            n = next(n for n, net in here if net == vdd)
            raise Refused(
                f"i2c {pair}: the pull-ups go to {vdd}, and {part.ref} {pin['name']}, pin {n}, a ground, is "
                f"on it: the bus is pulled up to its supply, not to a ground [{_src(f, pin)}]"
            )
        words = set(re.split(r"[^A-Za-z0-9]+", pin["name"].upper()))
        for word, want, what in (("SDA", sda, "data"), ("SCL", scl, "clock")):
            if word not in words:
                continue
            for n, net in here:
                if net != want:
                    raise Refused(
                        f"i2c {part.ref} {pin['name']}: pin {n} is on {net or 'no net'}, not on {want}, the "
                        f"bus's {what} line [{_src(f, pin)}]"
                    )


def _spec(pair: str, volts, farads, track, nets) -> None:
    """The numbers of the spec: each finite and over 0, the bus voltage least first, 3 nets."""

    def over_0(*xs) -> bool:
        return all(isinstance(x, (int, float)) and math.isfinite(x) and x > 0 for x in xs)

    if len(set(nets)) != 3:
        raise Refused(
            f"i2c {pair}: nets={nets!r}: SDA, SCL and the supply they pull up to are 3 different nets"
        )
    if not over_0(*volts):
        raise Refused(f"i2c {pair}: volts={volts!r}: each a finite number over 0")
    if volts[0] > volts[1]:
        raise Refused(
            f"i2c {pair}: volts=({_g(volts[0])}, {_g(volts[1])}) is written greatest first: volts is (least, "
            "greatest), and the block judges the pins and the sinks at the greatest"
        )
    if farads is not None and not over_0(farads):
        raise Refused(f"i2c {pair}: farads={farads!r}: the bus capacitance is a finite number over 0")
    if track is not None and not over_0(*track[:2]):
        raise Refused(f"i2c {pair}: track={track!r}: mm and farads per mm are each a finite number over 0")


def _device_pin(line, part, number, f, vdd: str, top: float, sums: list[str]) -> dict:
    """A device's pin on the bus: its role, its voltage limits against the bus's 0 V to `top`."""
    pin_of = {p["name"]: p for p in f.data["pins"]}
    pin = next((p for p in f.data["pins"] if number in p["numbers"]), None)
    if pin is None:
        raise Refused(f"i2c {part.ref}: its facts give no pin {number} [{f.source}]")
    name = f"{part.ref} {pin['name']}"
    src = _src(f, pin)
    if pin["role"] not in BUS_ROLES:
        raise Refused(
            f"i2c {name}: its role is {pin['role']}: a line of the bus takes an open drain, an io or an "
            f"input [{src}]"
        )
    for key, label in (("abs", "absolute"), ("operating", "operating")):
        if key not in pin:
            continue
        low, high = pin[key]
        most, follows = _resolve(high, part, pin_of, vdd, top)
        if most is None:
            sums.append(
                f"{name}: its {label} limit follows {follows}, not on the bus's {vdd}: not judged here; "
                "`workcenter ratings` judges it"
            )
        elif top > most * (1 + ratings.EPS):
            word = "absolute maximum" if key == "abs" else "operating limit"
            raise Refused(
                f"i2c {name}: the bus reaches {ratings.si(top, 'V')}, over its {word}, "
                f"{ratings.si(most, 'V')} [{src}]"
            )
        least, follows = _resolve(low, part, pin_of, vdd, top)
        if least is not None and least > 0:
            raise Refused(
                f"i2c {name}: the bus falls to 0 V, under its {label} least, {ratings.si(least, 'V')} [{src}]"
            )
    return {"name": name, "pin": pin, "src": src, "line": line}


def i2c(  # noqa: PLR0912, PLR0913, PLR0915
    d,
    *,
    volts: tuple[float, float],
    speed: str,
    nets: tuple[str, str, str],
    devices: dict[str, str],
    stock: list[Stock],
    facts: Path,
    sch_at: tuple[float, float],
    pcb_at: tuple[float, float],
    farads: float | None = None,
    track: tuple[float, float, str] | None = None,
    refs: dict[str, str] | None = None,
    rules: Path = RULES / "i2c.json",
) -> Block:
    """The pull-ups of an I2C bus `nets` = (SDA, SCL, the supply they pull up to), whose voltage spans
    `volts`. `devices` names each part on the bus by its part number; a connector stands for what is off
    the board. The bus capacitance is `farads`, or the devices' pins and `track` = (mm, farads per mm, the
    source of that figure)."""
    refs = {"sda": "R1", "scl": "R2"} | (refs or {})
    pair = f"{refs['sda']} {refs['scl']}"
    shown = f"{refs['sda']}, {refs['scl']}"
    _spec(pair, volts, farads, track, nets)
    note = load_rules(rules)["note"]
    table = _where(note, note["speeds_where"])
    eq = {n: _where(note, f"equation {n}, page {e['page']}") for n, e in note["equations"].items()}
    choice = _where(note, note["choice"])
    if speed not in note["speeds"]:
        raise Refused(f"i2c {pair}: speed `{speed}` is none of {', '.join(note['speeds'])} [{table}]")
    mode = note["speeds"][speed]
    sda, scl, vdd = nets
    for ref in refs.values():
        if any(p.ref == ref for p in d.parts):
            raise Refused(f"i2c {ref}: the design holds {ref} already; name the block's pull-ups with refs=")
    found = ratings.read_facts(Path(facts))
    bottom, top = volts
    sums: list[str] = []

    # RP(min) by equation 1, from the low level of table 2-1 at each end of the bus's voltage.
    least, least_line, least_where = 0.0, "", ""
    for v in sorted({bottom, top}):
        row = next(r for r in note["low"] if r["above_volts"] is None or v > r["above_volts"])
        where = _where(note, row["where"])
        if speed not in row["speeds"]:
            raise Refused(f"i2c {pair}: table 2-1 gives no VOL for {SPEEDS[speed]} at {_g(v)} V [{where}]")
        vol = row["volts"] if "volts" in row else row["share"] * v
        r = (v - vol) / row["amps"]
        if r > least:
            least = r
            least_line = (
                f"{shown}: RP(min) = ({_g(v)} V - {ratings.si(vol, 'V')}) / {ratings.si(row['amps'], 'A')} = "
                f"{ratings.si(r, 'ohm')} [{eq['1']}; {where}]"
            )
            least_where = where
    sums.append(least_line)

    # Each device on the bus: its pins' limits, its sink, its capacitance.
    bus = _bus_parts(d, (sda, scl), devices, found, Path(facts), set(refs.values()))
    for part, f in {part.ref: (part, f) for _, part, _, f in bus if f}.values():
        _device_nets(part, f, nets, pair)
    pins = [(line, part, _device_pin(line, part, n, f, vdd, top, sums)) for line, part, n, f in bus if f]
    connectors = sorted({part.ref for line, part, n, f in bus if f is None})
    for _line, _part, one in pins:
        pin = one["pin"]
        if pin["role"] == "input":
            continue
        if "sink" not in pin:
            raise Refused(
                f"i2c {one['name']}: its facts give no sink (the current it sinks at its low voltage): the "
                f"pull-up cannot be held to it [{one['src']}]"
            )
        sink = pin["sink"]
        r = (top - sink["volts"]) / sink["amps"]
        sums.append(
            f"{one['name']}: RP(min) = ({_g(top)} V - {ratings.si(sink['volts'], 'V')}) / "
            f"{ratings.si(sink['amps'], 'A')} = {ratings.si(r, 'ohm')}, its sink [{one['src']}; {eq['1']}]"
        )
        if r > least:
            least, least_where = r, one["src"]

    # The bus capacitance, per line; the greater line's is the bus's.
    per_line = {}
    for line in (sda, scl):
        here = [(part.ref, one) for ln, part, one in pins if ln == line and "farads" in one["pin"]]
        per_line[line] = (sum(one["pin"]["farads"] for _, one in here), here)
    unsummed = [(line, one) for line, _part, one in pins if "farads" not in one["pin"]]
    if farads is not None:
        for line, (total, here) in per_line.items():
            if farads < total * (1 - ratings.EPS):
                each = ", ".join(f"{ref} {ratings.si(one['pin']['farads'], 'F')}" for ref, one in here)
                srcs = "; ".join(dict.fromkeys(one["src"] for _, one in here))
                raise Refused(
                    f"i2c {pair}: the stated Cb, {ratings.si(farads, 'F')}, is under the "
                    f"{ratings.si(total, 'F')} the devices' pins give on {line}: {each} [{srcs}]"
                )
        cb = farads
        sums.append(
            f"{sda}, {scl}: Cb = {ratings.si(cb, 'F')}, stated; the devices' pins give "
            f"{ratings.si(per_line[sda][0], 'F')} on {sda} and {ratings.si(per_line[scl][0], 'F')} on {scl}"
        )
        sums += [
            f"{one['name']}: its facts give no capacitance: not in the devices' sum on {line}; not judged "
            f"against the stated Cb [{one['src']}]"
            for line, one in unsummed
        ]
        sums += [f"{ref}: a connector: what stands behind it is in the stated Cb" for ref in connectors]
    elif track is not None:
        if connectors:
            line = next(ln for ln, part, n, f in bus if f is None)
            raise Refused(
                f"i2c {connectors[0]}: a connector on {line}: what stands behind it is in no sum; state the "
                "bus capacitance, farads="
            )
        if unsummed:
            one = unsummed[0][1]
            raise Refused(
                f"i2c {one['name']}: its facts give no capacitance: Cb cannot be summed; state the bus "
                f"capacitance, farads= [{one['src']}]"
            )
        mm, per_mm, said = track
        cb = 0.0
        for line, (total, here) in per_line.items():
            each = " + ".join(f"{ref} {ratings.si(one['pin']['farads'], 'F')}" for ref, one in here)
            srcs = "; ".join(dict.fromkeys(one["src"] for _, one in here))
            on = total + mm * per_mm
            sums.append(
                f"{line}: Cb = {each} + {_g(mm)} mm x {per_mm * 1e12:g} pF/mm ({said}) = "
                f"{ratings.si(on, 'F')} [{srcs}]"
            )
            cb = max(cb, on)
    else:
        raise Refused(
            f"i2c {pair}: the bus capacitance is asked: farads=, or track=(mm, farads per mm, source)"
        )
    if cb > mode["farads_max"] * (1 + ratings.EPS):
        raise Refused(
            f"i2c {pair}: Cb of {ratings.si(cb, 'F')} is over the {ratings.si(mode['farads_max'], 'F')} of "
            f"{SPEEDS[speed]} [{table}]"
        )
    factor = note["rise_factor"]["value"]
    rise = mode["rise_max"]
    most = rise / (factor * cb)  # equation 6
    most_sum = (
        f"RP(max) = {ratings.si(rise, 's')} / ({factor:g} x {ratings.si(cb, 'F')}) = "
        f"{ratings.si(most, 'ohm')}"
    )
    sums.append(f"{shown}: {most_sum} [{eq['6']}; {table}]")
    if most < least:
        raise Refused(
            f"i2c {pair}: {most_sum} is under RP(min) = {ratings.si(least, 'ohm')}: no resistor lies between "
            f"[{eq['1']}; {eq['6']}; {least_where}; {table}]"
        )

    # The first stocked resistor that holds both bounds at its tolerance (section 3).
    taken, missed = None, []
    for item in stock:
        f = ratings.facts_of(
            found, SimpleNamespace(ref=item.mpn, symbol="", footprint=item.footprint), item.mpn
        )
        ohms = ratings.part_value(item.value)
        if f is None or f.kind != "resistor" or ohms is None:
            continue
        t = f.data["tolerance"]
        if ohms * (1 + t) > most * (1 + ratings.EPS):
            missed.append(
                f"{item.value}, {ratings.si(ohms * (1 + t), 'ohm')} at +{t * 100:g} %, over RP(max)"
            )
        elif ohms * (1 - t) < least * (1 - ratings.EPS):
            missed.append(
                f"{item.value}, {ratings.si(ohms * (1 - t), 'ohm')} at -{t * 100:g} %, under RP(min)"
            )
        else:
            taken = (item, f, ohms, t)
            break
    if taken is None:
        raise Refused(
            f"i2c {pair}: no stocked resistor lies between RP(min) = {ratings.si(least, 'ohm')} and "
            f"RP(max) = {ratings.si(most, 'ohm')} at its tolerance: "
            f"{'; '.join(missed) or 'no resistor with facts'} [{eq['1']}; {eq['6']}; {choice}]"
        )
    item, f, ohms, t = taken
    over = f"; passed over: {'; '.join(missed)}" if missed else ""
    sums.append(
        f"{shown}: {item.value}, {t * 100:g} %: {ratings.si(ohms * (1 - t), 'ohm')} to "
        f"{ratings.si(ohms * (1 + t), 'ohm')}, within {ratings.si(least, 'ohm')} to {ratings.si(most, 'ohm')}"
        f"{over} [{choice}]"
    )
    sums.append(
        f"{sda}, {scl}: the devices' greatest clock is not judged: their facts hold none; "
        f"{SPEEDS[speed]} is the speed asked"
    )

    sx, sy = sch_at
    px, py = pcb_at
    chosen = {refs["sda"]: (vdd, sda), refs["scl"]: (vdd, scl)}
    for k, (ref, (a, b)) in enumerate(chosen.items()):
        d.add(ref, "Device:R", item.value, item.footprint, sch_at=(sx + 12.7 * k, sy),
              pcb_at=(px + 3.0 * k, py), nets={"1": a, "2": b})  # fmt: skip
    _read_back(d, chosen, item.value, ohms, t, least, rise, factor, cb)

    # No span is stated for SDA and SCL: `workcenter ratings` works them out from the pull-ups and the open
    # drains, and holds the supply where each pin's limit is tightest. A stated span would stand apart
    # from the supply's, and a limit of VCC on a line pulled up to the same VCC would fail. The supply's
    # span is stated: `volts`, which the sums and the deck use; `blocks.ratings_json` refuses a design
    # that states another span for the same net.
    entries = {
        "nets": {
            vdd: {
                "volts": [bottom, top],
                "source": f"the bus voltage of the I2C block {pair}: i2c(volts=({_g(bottom)}, {_g(top)}))",
            }
        }
    }
    rows = rows_of([(item, 2)])
    files = _deck(refs["sda"], (sda, scl), item, f, ohms, cb, top, rise, note, speed, sums)
    return Block("i2c", sums, entries, rows, files)


def _read_back(d, chosen, value, ohms, t, least, rise, factor, cb) -> None:  # noqa: PLR0913
    """The pull-ups as the design holds them: each between the nets chosen, of the value chosen, and the
    value holds both bounds again at its tolerance."""
    for ref, (a, b) in chosen.items():
        part = next(p for p in d.parts if p.ref == ref)
        held = (part.value, part.nets.get("1"), part.nets.get("2"))
        if held != (value, a, b):
            raise Refused(
                f"i2c {ref}: the design holds {held[0]} from {held[1]} to {held[2]}; the block chose {value} "
                f"from {a} to {b}"
            )
        r = ratings.part_value(part.value)
        if (
            r is None
            or r != ohms
            or factor * r * (1 + t) * cb > rise * (1 + ratings.EPS)
            or r * (1 - t) < least * (1 - ratings.EPS)
        ):
            raise Refused(f"i2c {ref}: {part.value} does not hold the bounds the block worked out")


def _deck(ref, lines_of, item, f, ohms, cb, top, rise, note, speed, sums) -> dict[str, str]:  # noqa: PLR0913
    """sim/i2c.cir: SDA let go from 0 V, charged through its pull-up into the bus capacitance; the rise
    from 0.3 to 0.7 of the supply (equations 3 and 4) is held to the speed's tr of table 2-1. Its
    `* deck: i2c-rise SDA SCL` line answers the SIM gate's question for both lines (tools/simneeds.py):
    the 2 pull-ups are 1 value, so the one the deck runs stands for the other."""
    line, scl = lines_of
    lo, hi = note["rise_from"]["value"] * top, note["rise_to"]["value"] * top
    tau = ohms * cb
    lines = [
        f"i2c: the {line} line of the I2C block {ref}, written by tools/blocks_i2c.py",
        f"* deck: i2c-rise {line} {scl}",
        f"* {ref} {item.mpn} pulls {line} up to {_g(top)} V, the bus's greatest voltage; CBUS is the bus "
        "capacitance. The open drain lets go at 0 s.",
        f"* tr runs from {note['rise_from']['value']:g} to {note['rise_to']['value']:g} of the supply "
        f"[{note['short']}, {note['rise_from']['where']}; {note['rise_to']['where']}].",
        f"* The bound is {SPEEDS[speed]}'s tr [{note['short']}, {note['speeds_where']}].",
        "* The sums:",
        *[f"*   {s}" for s in sums],
        f"V1 vdd 0 {_g(top)}",
        f"{ref} vdd {line.lower()} {_ohms(ohms)}",
        f"CBUS {line.lower()} 0 {cb * 1e12:g}p",
        f".ic v({line.lower()})=0",
        ".control",
        f"tran {tau / 200 * 1e9:.4g}n {tau * 10 * 1e9:.4g}n uic",
        f"meas tran tr trig v({line.lower()}) val={lo:.6g} rise=1 targ v({line.lower()}) val={hi:.6g} rise=1",
        "print tr",
        ".endc",
        ".end",
    ]
    expect = {
        "tr": {
            "max": rise,
            "source": (
                f"{SPEEDS[speed]}'s tr, {ratings.si(rise, 's')} [{note['short']}, {note['speeds_where']}]"
            ),
        }
    }
    corners = {"tolerance": {"R": f.data["tolerance"], "source": f"{ref} {item.mpn} from {f.source}"}}
    return {
        "sim/i2c.cir": "\n".join(lines) + "\n",
        "sim/i2c.expect.json": json.dumps(expect, indent=2) + "\n",
        "sim/corners.json": json.dumps(corners, indent=2) + "\n",
    }
