"""blocks_mcu — the microcontroller block of tools/blocks.py: an MSP430 with its 32768 Hz crystal and the
crystal's 2 load capacitors, its decoupling, its reset network and its Spy-Bi-Wire programming header.

Each value comes from TI SLAA322D ("MSP430 32-kHz Crystal Oscillators") and the IC's own documents, as
`rules/blocks/mcu.json` holds them with their clauses and pages:

- the crystal: the first stocked crystal whose shunt capacitance the datasheet allows, whose load is a
  load the datasheet states the oscillation allowance (OA) at, and whose safety factor, SF = OA / ESR
  (equation 5), with ESR at its load by equation 1, is the least table 2 calls safe;
- the load capacitors: CL1 = 2 x CLoad - CParasitic (equation 3), the pin's capacitance and the board's
  stray, which the designer states; the stock's nearest value;
- the decoupling: the bulk and the bypass capacitors of SLAU278AH figure 2-3, the VCORE capacitor and
  the ratio of VCC to VCORE of the datasheet's section 5.3;
- the reset: the pull-up and the capacitor of SLAU278AH figure 2-3, the capacitor within its note B;
- the header: the pins figure 2-3 joins to RST, TEST, VCC and GND.

What neither document states (the crystal's drive level) is a sum that says it is not judged. Before it
returns, the block reads its parts back from the design and checks them (check()).
"""

from __future__ import annotations

from pathlib import Path

import blocks
import ratings
from blocks import Block, Refused, Stock, _g

RULES = blocks.RULES / "mcu.json"
DEFAULT_REFS = {
    "ic": "U1",
    "crystal": "Y1",
    "load": "C1 C2",
    "bulk": "C3",
    "bypass": "C4 C5",
    "vcore": "C6",
    "reset_r": "R1",
    "reset_c": "C7",
    "header": "J2",
}
EPS = ratings.EPS


def chip_of(ic: str, rules: Path = RULES) -> dict:
    """The entry of `ic` in the rules, with the rules' note and documents beside it."""
    data = blocks.load_rules(rules)
    chip = next((c for c in data["ics"] if c["mpn"] == ic), None)
    if chip is None:
        names = ", ".join(c["mpn"] for c in data["ics"])
        raise Refused(f"mcu: {ic} is no IC of {Path(rules).name}; it holds {names}")
    return {**chip, "_note": data["note"], "_documents": data["documents"]}


def _where(chip: dict, key: str) -> str:
    return blocks._where(chip, key)


def _eq(chip: dict, n: str) -> str:
    note = chip["_note"]
    return f"{note['short']}, equation {n}, page {note['equations'][n]['page']}"


def _f(farads: float) -> str:
    return ratings.si(farads, "F")


def _sf_where(chip: dict) -> str:
    return f"{_eq(chip, '5')}; {chip['_note']['sf_min']['where']}; {_where(chip, 'allowance')}"


def _eq3_where(chip: dict) -> str:
    return f"{_eq(chip, '3')}; {_where(chip, 'pin_farads')}"


def _crystal(u, chip, crystals, sf_min):
    """The first crystal the oscillator starts with a safe factor, and why each one before it was not."""
    rows = chip["allowance"]["rows"]
    loads = ", ".join(_f(r[0]) for r in rows)
    shunt_max = chip["shunt_max"]["value"]
    hertz = chip["crystal_hz"]["value"]
    missed = []  # (stock, why, where) or, for a factor too low, (stock, why, where, esr sum, sf sum)
    for item, f in crystals:
        data = f.data
        load, esr = data["farads_load"], data["ohms_esr"]
        if data["hertz"] != hertz:
            why = f"its {data['hertz']:g} Hz is not the {hertz:g} Hz of XT1's LF mode"
            missed.append((item, why, _where(chip, "crystal_hz")))
            continue
        if "farads_shunt" not in data:
            missed.append(
                (item, "its facts give no shunt capacitance, which equation 1 needs", _eq(chip, "1"))
            )
            continue
        shunt = data["farads_shunt"]
        if shunt > shunt_max * (1 + EPS):
            why = f"its shunt capacitance, {_f(shunt)}, is over {_f(shunt_max)}"
            missed.append((item, why, _where(chip, "shunt_max")))
            continue
        row = next((r for r in rows if abs(r[0] - load) <= r[0] * EPS), None)
        if row is None:
            why = f"its load, {_f(load)}, is no load OALF is stated at ({loads})"
            missed.append((item, why, _where(chip, "allowance")))
            continue
        oa = row[1]
        at_load = esr * (1 + shunt / load) ** 2  # equation 1
        sf = oa / at_load  # equation 5
        ohm = ratings.si
        esr_sum = f"ESR = {ohm(esr, 'ohm')} x (1 + {_f(shunt)} / {_f(load)})^2 = {ohm(at_load, 'ohm')}"
        sf_sum = f"SF = {ratings.si(oa, 'ohm')} / {ratings.si(at_load, 'ohm')} = {sf:.4g}"
        if sf < sf_min:
            where = f"{_eq(chip, '1')}; {_sf_where(chip)}"
            missed.append((item, f"{esr_sum}, {sf_sum}, under {sf_min:g}", where, esr_sum, sf_sum))
            continue
        return (item, f, load, esr_sum, sf_sum), missed
    if not missed:
        raise Refused(f"mcu {u}: no stocked crystal with facts [{_where(chip, 'allowance')}]")
    if all(len(m) == 5 for m in missed):  # each one would start, and none with a safe factor
        why = "; ".join(f"{m[0].mpn}: {m[3]}, {m[4]}" for m in missed)
        raise Refused(
            f"mcu {u}: no stocked crystal starts with a safety factor of {sf_min:g}: {why} "
            f"[{_eq(chip, '1')}; {_sf_where(chip)}]"
        )
    why = "; ".join(f"{m[0].mpn}: {m[1]} [{m[2]}]" for m in missed)
    raise Refused(f"mcu {u}: no stocked crystal starts with a safety factor of {sf_min:g}: {why}")


def _rated(cf, volts: float) -> bool:
    return "volts" in cf.data and cf.data["volts"] >= volts


def _value(stock: Stock) -> float:
    return ratings.part_value(stock.value)


def mcu(  # noqa: PLR0913, PLR0915
    d,
    *,
    ic: str,
    vcc: tuple[float, float],
    stray: float,
    nets: tuple[str, str],
    stock: list[Stock],
    facts: Path,
    sch_at: tuple[float, float],
    pcb_at: tuple[float, float],
    refs: dict[str, str] | None = None,
    rules: Path = RULES,
) -> Block:
    """A microcontroller from `nets` = (supply, ground), its supply range `vcc` and the board's stray
    capacitance on each crystal pin, `stray`, in farads."""
    refs = DEFAULT_REFS | (refs or {})
    u = refs["ic"]
    chip = chip_of(ic, rules)
    found = ratings.read_facts(Path(facts))
    chip_facts = blocks._facts(found, Stock("", ic, "", chip["footprint"]), chip["symbol"])
    if chip_facts is None:
        raise Refused(f"mcu {u}: {facts} holds no facts of {ic}")
    pins = {p["name"]: p for p in chip_facts.data["pins"]}
    low, high = pins["DVCC"]["operating"]
    vcc_low, vcc_high = vcc
    if vcc_high > high or vcc_low < low:
        reach = vcc_high if vcc_high > high else vcc_low
        raise Refused(
            f"mcu {u}: the supply reaches {ratings.si(reach, 'V')}, DVCC of {ic} operates from "
            f"{ratings.si(low, 'V')} to {ratings.si(high, 'V')} "
            f"[{chip_facts.source}, {ratings._p(pins['DVCC']['page'])}]"
        )
    if stray < 0:
        raise Refused(
            f"mcu {u}: a stray capacitance of {_f(stray)}: a board adds capacitance [{_eq3_where(chip)}]"
        )
    sums: list[str] = []
    sf_min = chip["_note"]["sf_min"]["value"]
    y = refs["crystal"]

    crystals = [(s, f) for s in stock if (f := blocks._facts(found, s)) is not None and f.kind == "crystal"]
    taken, missed = _crystal(u, chip, crystals, sf_min)
    for m in missed:
        sums.append(f"{y}: {m[0].mpn} is passed over: {m[1]} [{m[2]}]")
    crystal, crystal_facts, load, esr_sum, sf_sum = taken
    sums.append(f"{y}: {esr_sum} [{_eq(chip, '1')}]; {sf_sum}, {sf_min:g} or more [{_sf_where(chip)}]")

    # The load capacitors by equation 3: each pin holds the IC's own capacitance and the board's stray.
    pin_farads = chip["pin_farads"]["value"]
    parasitic = pin_farads + stray
    cl1 = 2 * load - parasitic
    load_sum = f"CL1 = 2 x {_f(load)} - ({_f(pin_farads)} + {_f(stray)}) = {_f(cl1)}"
    if cl1 <= 0:
        raise Refused(
            f"mcu {u}: {load_sum} for {crystal.mpn}: the pins and the board hold more than its load "
            f"[{_eq3_where(chip)}]"
        )
    caps = [
        (s, cf)
        for s in stock
        if (cf := blocks._facts(found, s)) is not None and cf.kind.startswith("capacitor")
    ]
    rated = [(s, cf) for s, cf in caps if _rated(cf, vcc_high)]
    if not rated:
        raise Refused(
            f"mcu {u}: no stocked capacitor rated for {ratings.si(vcc_high, 'V')} [{_eq3_where(chip)}]"
        )
    load_cap = min(rated, key=lambda pair: abs(_value(pair[0]) - cl1))
    c_load = _value(load_cap[0])
    got = (c_load + parasitic) / 2  # equation 3
    pair = refs["load"].split()
    sums.append(
        f"{', '.join(pair)}: {load_sum}; the stock's nearest is {load_cap[0].value}, and CLoad = "
        f"({_f(c_load)} + {_f(parasitic)}) / 2 = {_f(got)} [{_eq3_where(chip)}]"
    )
    drive = crystal_facts.data.get("watts_drive")
    limit = (
        f"{crystal.mpn} allows {ratings.si(drive, 'W')} [{crystal_facts.source}]"
        if drive is not None
        else "its facts give no limit"
    )
    sums.append(
        f"{y}: its drive level is not judged: neither SLAA322D nor SLASE35C states the power XT1 puts into "
        f"the crystal; {limit}"
    )

    # The decoupling: the bulk and the bypass capacitors of SLAU278AH figure 2-3, VCORE's of 5.3.
    def first(asked: float, more: bool, key: str):
        def fits(s, cf):
            v = _value(s)
            return (v >= asked * (1 - EPS) if more else abs(v - asked) <= asked * EPS) and _rated(
                cf, vcc_high
            )

        hit = next(((s, cf) for s, cf in caps if fits(s, cf)), None)
        if hit is None:
            raise Refused(
                f"mcu {u}: no stocked capacitor of {_f(asked)}{' or more' if more else ''}, rated for "
                f"{ratings.si(vcc_high, 'V')} [{_where(chip, key)}]"
            )
        return hit

    bulk = first(chip["bulk_farads"]["value"], True, "bulk_farads")
    bypass = first(chip["bypass_farads"]["value"], False, "bypass_farads")
    core_tol = chip["vcore_tolerance"]["value"]
    asked_core = chip["vcore_farads"]["value"]
    near = [
        (s, cf) for s, cf in caps if abs(_value(s) - asked_core) <= asked_core * EPS and _rated(cf, vcc_high)
    ]
    vcore = next(((s, cf) for s, cf in near if cf.data.get("tolerance", 1) <= core_tol * (1 + EPS)), None)
    if vcore is None:
        loose = "; ".join(f"{s.mpn} is {cf.data.get('tolerance', 1) * 100:g} %" for s, cf in near)
        raise Refused(
            f"mcu {u}: no stocked capacitor of {_f(asked_core)}, {core_tol * 100:g} % or better, rated for "
            f"{_g(vcc_high)} V{': ' + loose if loose else ''} [{_where(chip, 'vcore_farads')}; "
            f"{_where(chip, 'vcore_tolerance')}]"
        )
    b_refs, p_refs = refs["bulk"].split(), refs["bypass"].split()
    c_bulk, c_bypass, c_core = (_value(x[0]) for x in (bulk, bypass, vcore))
    sums.append(
        f"{', '.join(b_refs + p_refs)}: {_f(c_bulk)} and {len(p_refs)} x {_f(c_bypass)} at DVCC and AVCC "
        f"[{_where(chip, 'bulk_farads')}; {chip['bypass_farads']['where']}]"
    )
    sums.append(
        f"{refs['vcore']}: {_f(c_core)} of {vcore[1].data['tolerance'] * 100:g} %, {core_tol * 100:g} % or "
        f"better asked [{_where(chip, 'vcore_farads')}; {chip['vcore_tolerance']['where']}]"
    )
    ratio = (c_bulk + len(p_refs) * c_bypass) / c_core
    least = chip["vcc_ratio"]["value"]
    parts_sum = f"({_f(c_bulk)} + {len(p_refs)} x {_f(c_bypass)}) / {_f(c_core)} = {_g(ratio)}"
    if ratio < least:
        raise Refused(f"mcu {u}: {parts_sum}, under {least:g} [{_where(chip, 'vcc_ratio')}]")
    sums.append(f"{', '.join(b_refs + p_refs)}: {parts_sum}, {least:g} or more [{_where(chip, 'vcc_ratio')}]")

    # The reset: the pull-up of figure 2-3, the capacitor nearest its 1.1 nF within note B's span.
    r_asked = chip["reset_ohms"]["value"]
    resistors = [
        (s, rf) for s in stock if (rf := blocks._facts(found, s)) is not None and rf.kind == "resistor"
    ]
    pull = next(((s, rf) for s, rf in resistors if abs(_value(s) - r_asked) <= r_asked * EPS), None)
    if pull is None:
        raise Refused(
            f"mcu {u}: no stocked resistor of {ratings.si(r_asked, 'ohm')} [{_where(chip, 'reset_ohms')}]"
        )
    c_asked = chip["reset_farads"]["value"]
    lo, hi = chip["reset_farads"]["range"]
    within = [(s, cf) for s, cf in rated if lo * (1 - EPS) <= _value(s) <= hi * (1 + EPS)]
    if not within:
        raise Refused(
            f"mcu {u}: no stocked capacitor from {_f(lo)} to {_f(hi)} for RST "
            f"[{_where(chip, 'reset_farads')}]"
        )
    hold = min(within, key=lambda pair: abs(_value(pair[0]) - c_asked))
    sums.append(
        f"{refs['reset_r']}, {refs['reset_c']}: {ratings.si(r_asked, 'ohm')} to VCC and {hold[0].value} "
        f"to GND at RST: {hold[0].value} is the stock's nearest to {_f(c_asked)}, within {_f(lo)} to "
        f"{_f(hi)} [{_where(chip, 'reset_ohms')}; {chip['reset_farads']['where']}]"
    )
    head = chip["header"]
    hp = head["pins"]
    sums.append(
        f"{refs['header']}: pins {hp['RST']} RST, {hp['VCC']} VCC, {hp['TEST']} TEST, {hp['GND']} GND "
        f"[{head['where']}]"
    )

    # The parts, placed from the block's corner on the sheet and on the board.
    vnet, gnd = nets
    xin, xout, rst, test, core = (f"{u}_{n}" for n in ("XIN", "XOUT", "RST", "TEST", "VCORE"))
    p = chip["pins"]
    sx, sy = sch_at
    px, py = pcb_at
    d.add(u, chip["symbol"], chip["value"], chip["footprint"], sch_at=(sx + 50.8, sy),
          pcb_at=(px + 12.0, py + 8.0),
          nets={p["DVCC"]: vnet, p["AVCC"]: vnet, p["DVSS"]: gnd, p["AVSS"]: gnd, p["VCORE"]: core,
                p["XIN"]: xin, p["XOUT"]: xout, p["TEST"]: test, p["RST"]: rst})  # fmt: skip
    d.add(y, "Device:Crystal", crystal.value, crystal.footprint, sch_at=(sx + 101.6, sy + 25.4),
          pcb_at=(px + 12.0, py + 17.0), nets={"1": xin, "2": xout})  # fmt: skip
    for k, (ref, net) in enumerate(zip(pair, (xin, xout), strict=True)):
        d.add(ref, "Device:C", load_cap[0].value, load_cap[0].footprint,
              sch_at=(sx + 91.44 + 20.32 * k, sy + 38.1), pcb_at=(px + 7.0 + 10.0 * k, py + 21.0),
              nets={"1": net, "2": gnd})  # fmt: skip
    d.add(b_refs[0], "Device:C", bulk[0].value, bulk[0].footprint, sch_at=(sx, sy + 7.62),
          pcb_at=(px + 2.0, py + 2.0), nets={"1": vnet, "2": gnd})  # fmt: skip
    for k, ref in enumerate(p_refs):
        d.add(ref, "Device:C", bypass[0].value, bypass[0].footprint,
              sch_at=(sx + 12.7 + 10.16 * k, sy + 7.62), pcb_at=(px + 8.0 + 8.0 * k, py + 3.0),
              nets={"1": vnet, "2": gnd})  # fmt: skip
    d.add(refs["vcore"], "Device:C", vcore[0].value, vcore[0].footprint, sch_at=(sx + 12.7, sy + 30.48),
          pcb_at=(px + 18.0, py + 12.0), nets={"1": core, "2": gnd})  # fmt: skip
    d.add(refs["reset_r"], "Device:R", pull[0].value, pull[0].footprint, sch_at=(sx + 101.6, sy - 12.7),
          pcb_at=(px + 4.0, py + 9.0), nets={"1": vnet, "2": rst})  # fmt: skip
    d.add(refs["reset_c"], "Device:C", hold[0].value, hold[0].footprint, sch_at=(sx + 114.3, sy - 5.08),
          pcb_at=(px + 4.0, py + 13.0), nets={"1": rst, "2": gnd})  # fmt: skip
    d.add(refs["header"], head["symbol"], "SBW", head["footprint"], sch_at=(sx + 139.7, sy),
          pcb_at=(px + 28.0, py + 4.0),
          nets={hp["RST"]: rst, hp["VCC"]: vnet, hp["TEST"]: test, hp["GND"]: gnd})  # fmt: skip

    # The nets the IC holds itself, each with its source: no pull is missing on them.
    d.defined_nets[test] = (
        f"{chip['_documents']['family']['number']}, table 1-4, page 40: TEST always has an internal pulldown"
    )
    d.defined_nets[core] = (
        f"{chip['source']['document']}, section 5.18, page 26: {u}'s own regulator holds VCORE"
    )
    for net, pin in ((xin, "XIN"), (xout, "XOUT")):
        d.defined_nets[net] = (
            f"{chip['source']['document']}, table 4-1, page 13: {pin} is a terminal of {u}'s XT1"
        )

    problems = check(d, u, chip, nets, stray, refs)
    if problems:
        raise Refused(f"mcu {u}: the board as built: {'; '.join(problems)}")

    rows = blocks.rows_of(
        [
            (Stock(chip["maker"], ic, chip["value"], chip["footprint"]), 1),
            (crystal, 1),
            (load_cap[0], 2),
            (bulk[0], 1),
            (bypass[0], len(p_refs)),
            (vcore[0], 1),
            (pull[0], 1),
            (hold[0], 1),
            (Stock("", "", "SBW", head["footprint"]), 1),
        ]
    )
    entries = {
        "nets": {
            vnet: {
                "volts": [vcc_low, vcc_high],
                "source": f"the supply of the mcu block {u}: mcu(vcc=({_g(vcc_low)}, {_g(vcc_high)}))",
            },
            # the programming tool drives RST and TEST through the header, at the board's own supply
            **{
                net: {"volts": [0, vcc_high], "source": f"{refs['header']}: {head['drives']}"}
                for net in (rst, test)
            },
        }
    }
    return Block("mcu", sums, entries, rows)


def check(d, u: str, chip: dict, nets: tuple[str, str], stray: float, refs: dict | None = None) -> list[str]:  # noqa: ARG001
    """Read the block's parts back from the design and hold them to the rules: a crystal from XIN to
    XOUT, 1 capacitor of 1 value from each to ground, VCORE's capacitor, the ratio at VCC, the reset's
    pull-up and its capacitor, the header's 4 pins. Each problem is 1 line with its source."""
    refs = DEFAULT_REFS | (refs or {})
    vnet, gnd = nets
    xin, xout, rst, test, core = (f"{u}_{n}" for n in ("XIN", "XOUT", "RST", "TEST", "VCORE"))

    def between(a: str, b: str, lib_id: str) -> list:
        return [
            part
            for part in d.parts
            if part.symbol.lib_id == lib_id and sorted(part.nets.values()) == sorted([a, b])
        ]

    def total(parts) -> float:
        return sum(ratings.part_value(c.value) for c in parts)

    problems = []
    if not between(xin, xout, "Device:Crystal"):
        problems.append(f"no crystal from {xin} to {xout} [{_eq3_where(chip)}]")
    on = {net: between(net, gnd, "Device:C") for net in (xin, xout)}
    for net, other in ((xin, xout), (xout, xin)):
        if len(on[net]) != 1:
            has = ", ".join(c.value for c in on[other]) or "none"
            count = "no capacitor" if not on[net] else f"{len(on[net])} capacitors"
            problems.append(
                f"{net} has {count} to {gnd}, and {other.split('_', 1)[1]} has {has} [{_eq3_where(chip)}]"
            )
            break
    else:
        if total(on[xin]) != total(on[xout]):
            problems.append(
                f"the 2 load capacitors differ: equation 3 takes 2 equal ones [{_eq3_where(chip)}]"
            )
    asked_core = chip["vcore_farads"]["value"]
    core_total = total(between(core, gnd, "Device:C"))
    if core_total < asked_core * (1 - EPS):
        problems.append(
            f"{core} holds {_f(core_total)} to {gnd}, under {_f(asked_core)} [{_where(chip, 'vcore_farads')}]"
        )
    at_vcc = total(between(vnet, gnd, "Device:C"))
    if core_total and at_vcc / core_total < chip["vcc_ratio"]["value"]:
        problems.append(
            f"{vnet} holds {_f(at_vcc)}, under {chip['vcc_ratio']['value']:g} x {_f(core_total)} "
            f"[{_where(chip, 'vcc_ratio')}]"
        )
    if not between(vnet, rst, "Device:R"):
        problems.append(f"no pull-up from {rst} to {vnet} [{_where(chip, 'reset_ohms')}]")
    lo, hi = chip["reset_farads"]["range"]
    held = total(between(rst, gnd, "Device:C"))
    if not lo * (1 - EPS) <= held <= hi * (1 + EPS):
        problems.append(
            f"{rst} holds {_f(held)} to {gnd}, not {_f(lo)} to {_f(hi)} [{_where(chip, 'reset_farads')}]"
        )
    header = next((part for part in d.parts if part.ref == refs["header"]), None)
    hp = chip["header"]["pins"]
    wanted = {hp["RST"]: rst, hp["VCC"]: vnet, hp["TEST"]: test, hp["GND"]: gnd}
    if header is None or {k: header.nets.get(k) for k in wanted} != wanted:
        problems.append(f"{refs['header']} does not join {wanted} [{chip['header']['where']}]")
    return problems
