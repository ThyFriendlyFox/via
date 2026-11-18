"""blocks_mcu — the microcontroller block of tools/blocks.py: an MSP430 with its 32768 Hz crystal and the
crystal's 2 load capacitors, its decoupling, its reset network and its Spy-Bi-Wire programming header.

Each value comes from TI SLAA322D ("MSP430 32-kHz Crystal Oscillators") and the IC's own documents, as
`rules/blocks/mcu.json` holds them with their clauses and pages:

- the crystal: the first stocked crystal whose shunt capacitance the datasheet allows, whose load is a
  load the datasheet states the oscillation allowance (OA) at, and whose safety factor, SF = OA / ESR
  (equation 5), with ESR at its load by equation 1, is the least table 2 calls safe; its 2 terminals are
  the pads its maker names (its facts' `terminals`), and the symbol is the KiCad crystal on those pins;
- the load capacitors: CL1 = 2 x CLoad - CParasitic (equation 3), the pin's capacitance and the board's
  stray, which the designer states; the stock's nearest C0G capacitor whose value lies within its own
  tolerance of CL1, or a refusal;
- the decoupling: the bulk and the bypass capacitors of SLAU278AH figure 2-3, the VCORE capacitor and
  the ratio of VCC to VCORE of the datasheet's section 5.3;
- the reset: the pull-up and the capacitor of SLAU278AH figure 2-3, the capacitor within its note B;
- the header: the pins figure 2-3 joins to RST, TEST, VCC and GND.

What neither document states (the crystal's drive level, and its shunt capacitance against the 1.6 pF
when its datasheet states only a typical C0) is a sum that says it is not judged. Before it returns, the
block reads its parts back from the design and checks them (check()): the crystal on its terminal pads,
the load capacitors' value by equation 3, VCORE, the ratio at VCC, the pull-up's value, the reset
capacitor and the header.
"""

from __future__ import annotations

import math
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
    return {
        **chip,
        "_note": data["note"],
        "_documents": data["documents"],
        "_load": data["load_dielectric"],
        "_symbols": data["crystal_symbols"],
    }


def _where(chip: dict, key: str) -> str:
    """A value's clause, after the IC's datasheet unless the clause names another of the rules' documents."""
    where = chip[key]["where"]
    if where.startswith(tuple(doc["number"] for doc in chip["_documents"].values())):
        return where
    return blocks._where(chip, key)


def _load_where(chip: dict) -> str:
    note = chip["_note"]
    return f"{_eq3_where(chip)}; {note['short']}, {note['load_match']}; {chip['_load']['where']}"


def _match_where(chip: dict) -> str:
    return f"{_eq3_where(chip)}; {chip['_note']['short']}, {chip['_note']['load_match']}"


def _terminals(data: dict) -> list[str] | None:
    """The 2 pads a crystal's facts name as its terminals, or None when they name no 2."""
    t = data.get("terminals")
    pads = t.get("pads") if isinstance(t, dict) else None
    if not (isinstance(pads, list) and len(pads) == 2 and isinstance(t.get("where"), str)):
        return None
    if not all(isinstance(p, str) and p for p in pads) or pads[0] == pads[1]:
        return None
    return pads


def _pair_key(pads: list[str]) -> str:
    return " ".join(sorted(pads, key=lambda n: (len(n), n)))


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"


def _eq(chip: dict, n: str) -> str:
    note = chip["_note"]
    return f"{note['short']}, equation {n}, page {note['equations'][n]['page']}"


def _f(farads: float) -> str:
    if 0 < abs(farads) < 1e-12 * (1 - EPS):  # ratings.si has no prefix under pico
        return f"{farads * 1e12:.3g} pF"
    return ratings.si(farads, "F")


def _sf_where(chip: dict) -> str:
    return f"{_eq(chip, '5')}; {chip['_note']['sf_min']['where']}; {_where(chip, 'allowance')}"


def _eq3_where(chip: dict) -> str:
    return f"{_eq(chip, '3')}; {_where(chip, 'pin_farads')}"


def _crystal(d, u, chip, crystals, sf_min):  # noqa: PLR0912
    """The first crystal the oscillator starts with a safe factor, and why each one before it was not."""
    rows = chip["allowance"]["rows"]
    loads = ", ".join(_f(r[0]) for r in rows)
    shunt_max = chip["shunt_max"]["value"]
    hertz = chip["crystal_hz"]["value"]
    symbols = chip["_symbols"]
    missed = []  # (stock, why, where) or, for a factor too low, (stock, why, where, esr sum, sf sum)
    for item, f in crystals:
        data = f.data
        load, esr = data["farads_load"], data["ohms_esr"]
        if data["hertz"] != hertz:
            why = f"its {data['hertz']:g} Hz is not the {hertz:g} Hz of XT1's LF mode"
            missed.append((item, why, _where(chip, "crystal_hz")))
            continue
        most, typical = data.get("farads_shunt_max"), data.get("farads_shunt")
        if most is None and typical is None:
            missed.append(
                (item, "its facts give no shunt capacitance, which equation 1 needs", _eq(chip, "1"))
            )
            continue
        if most is not None and most > shunt_max * (1 + EPS):
            why = f"its shunt capacitance, {_f(most)} at the most, is over {_f(shunt_max)}"
            missed.append((item, why, _where(chip, "shunt_max")))
            continue
        if most is None and typical > shunt_max * (1 + EPS):
            why = f"its typical shunt capacitance, {_f(typical)}, is over {_f(shunt_max)}"
            missed.append((item, why, _where(chip, "shunt_max")))
            continue
        shunt = most if most is not None else typical
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
        # XIN and XOUT go to the 2 pads its maker names, on the KiCad symbol whose crystal is on them.
        pads = _terminals(data)
        if pads is None:
            why = "its facts name no 2 terminal pads, which XIN and XOUT are wired to"
            missed.append((item, why, f.source))
            continue
        symbol = symbols["pairs"].get(_pair_key(pads))
        if symbol is None:
            why = f"its terminals, pads {pads[0]} and {pads[1]}, are the crystal of no symbol the rules hold"
            missed.append((item, why, symbols["where"]))
            continue
        on_footprint = {p.number for p in d.fp(item.footprint).pads}
        lost = [p for p in pads if p not in on_footprint]
        if lost:
            why = f"its footprint {item.footprint} has no pad {_and(lost)}"
            missed.append((item, why, f"{f.source}, {data['terminals']['where']}"))
            continue
        others = sorted(on_footprint - set(pads), key=lambda n: (len(n), n))
        return (item, f, load, esr_sum, sf_sum, pads, symbol, others), missed
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


def _unfit(stock: Stock, cf, cl1: float, volts: float, dielectric: str) -> str | None:
    """Why a stocked capacitor cannot be a load capacitor of CL1, or None when it can."""
    data = cf.data
    if "dielectric" not in data:
        return f"{stock.value}: its facts give no dielectric, and {dielectric} is asked"
    if data["dielectric"] != dielectric:
        return f"{stock.value}: its dielectric is {data['dielectric']}, not {dielectric}"
    if "volts" not in data:
        return f"{stock.value}: its facts give no volts"
    if data["volts"] < volts:
        return f"{stock.value}: it is rated for {_g(data['volts'])} V, under {_g(volts)} V"
    if "tolerance" not in data:
        return f"{stock.value}: its facts give no tolerance"
    value, tol = _value(stock), data["tolerance"]
    off = abs(value - cl1)
    if off > tol * value * (1 + EPS):
        return f"{stock.value} is {_f(off)} from it, over its {tol * 100:g} % ({_f(tol * value)})"
    return None


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
    if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vcc):
        raise Refused(f"mcu {u}: vcc = {tuple(vcc)!r}: 2 finite volts are asked")
    if vcc_low > vcc_high:
        raise Refused(f"mcu {u}: vcc = ({_g(vcc_low)}, {_g(vcc_high)}): its low end is over its high end")
    if not (isinstance(stray, (int, float)) and math.isfinite(stray)) or stray < 0:
        raise Refused(
            f"mcu {u}: stray = {stray!r}: a finite capacitance of 0 F or more is asked [{_eq3_where(chip)}]"
        )
    if nets[0] == nets[1]:
        raise Refused(f"mcu {u}: nets = {tuple(nets)!r}: the supply and the ground are 1 net")
    if vcc_high > high or vcc_low < low:
        reach = vcc_high if vcc_high > high else vcc_low
        raise Refused(
            f"mcu {u}: the supply reaches {ratings.si(reach, 'V')}, DVCC of {ic} operates from "
            f"{ratings.si(low, 'V')} to {ratings.si(high, 'V')} "
            f"[{chip_facts.source}, {ratings._p(pins['DVCC']['page'])}]"
        )
    sums: list[str] = []
    sf_min = chip["_note"]["sf_min"]["value"]
    y = refs["crystal"]

    crystals = [(s, f) for s in stock if (f := blocks._facts(found, s)) is not None and f.kind == "crystal"]
    taken, missed = _crystal(d, u, chip, crystals, sf_min)
    for m in missed:
        sums.append(f"{y}: {m[0].mpn} is passed over: {m[1]} [{m[2]}]")
    crystal, crystal_facts, load, esr_sum, sf_sum, terminals, x_symbol, open_pads = taken
    sums.append(f"{y}: {esr_sum} [{_eq(chip, '1')}]; {sf_sum}, {sf_min:g} or more [{_sf_where(chip)}]")
    if "farads_shunt_max" not in crystal_facts.data:
        shunt_max = chip["shunt_max"]["value"]
        sums.append(
            f"{y}: its shunt capacitance is not judged against {_f(shunt_max)}: the facts of {crystal.mpn} "
            f"give C0 {_f(crystal_facts.data['farads_shunt'])} typical and no maximum, and equation 1 takes "
            f"the typical [{crystal_facts.source}; {_where(chip, 'shunt_max')}]"
        )

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
    rated = [(s, cf) for s, cf in caps if _rated(cf, vcc_high)]  # for the reset capacitor
    # The load capacitor: C0G, and its value within its own tolerance of CL1, so the stock's step moves
    # CLoad off the crystal's load no more than the part's tolerance does.
    dielectric = chip["_load"]["value"]
    pair = refs["load"].split()
    judged = sorted(
        ((s, cf, _unfit(s, cf, cl1, vcc_high, dielectric)) for s, cf in caps),
        key=lambda one: abs(_value(one[0]) - cl1),
    )
    fits = [(s, cf) for s, cf, why in judged if why is None]
    if not fits:
        why = "; ".join(one[2] for one in judged[:3]) or "the stock holds no capacitor with facts"
        raise Refused(
            f"mcu {u}: {load_sum} for {crystal.mpn}, and no stocked capacitor is {dielectric}, rated for "
            f"{_g(vcc_high)} V and within its own tolerance of it: {why} [{_load_where(chip)}]"
        )
    load_cap = fits[0]
    for s, _, why in judged:
        if s is load_cap[0]:
            break
        sums.append(f"{', '.join(pair)}: passed over: {why} [{_load_where(chip)}]")
    c_load = _value(load_cap[0])
    tolerance = load_cap[1].data["tolerance"]
    got = (c_load + parasitic) / 2  # equation 3
    sums.append(
        f"{', '.join(pair)}: {load_sum}; {load_cap[0].value}, {dielectric}, is {_f(abs(c_load - cl1))} from "
        f"it, within its {tolerance * 100:g} % ({_f(tolerance * c_load)}); CLoad = ({_f(c_load)} + "
        f"{_f(parasitic)}) / 2 = {_f(got)} [{_load_where(chip)}]"
    )
    x_where = f"{crystal_facts.source}, {crystal_facts.data['terminals']['where']}"
    # The symbol's other pins stand at 1 point, so the schematic joins them: 1 net of their own, or the
    # board's pads would differ from the schematic and DRC would find them unconnected.
    floating = f"{y}_G"
    opened = (
        f"; {x_symbol} joins pads {_and(open_pads)} on {floating}, and nothing else is on it "
        f"[{chip['_symbols']['where']}]"
        if open_pads
        else ""
    )
    sums.append(f"{y}: XIN on pad {terminals[0]}, XOUT on pad {terminals[1]} [{x_where}]{opened}")
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
    d.add(y, x_symbol, crystal.value, crystal.footprint, sch_at=(sx + 101.6, sy + 25.4),
          pcb_at=(px + 12.0, py + 17.0),
          nets={terminals[0]: xin, terminals[1]: xout} | dict.fromkeys(open_pads, floating))  # fmt: skip
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

    problems = check(d, u, chip, nets, stray, crystal_facts, tolerance, refs)
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


def check(  # noqa: PLR0913, PLR0912
    d,
    u: str,
    chip: dict,
    nets: tuple[str, str],
    stray: float,
    crystal: ratings.Facts,
    tolerance: float,
    refs: dict | None = None,
) -> list[str]:
    """Read the block's parts back from the design and hold them to the rules: the crystal's terminal
    pads (its facts' `terminals`) on XIN and XOUT, 1 capacitor of 1 value from each to ground whose value
    lies within `tolerance` of CL1 by equation 3, VCORE's capacitor, the ratio at VCC, the reset's
    pull-up and its value, the reset capacitor, the header's 4 pins. Each problem is 1 line with its
    source."""
    refs = DEFAULT_REFS | (refs or {})
    vnet, gnd = nets
    xin, xout, rst, test, core = (f"{u}_{n}" for n in ("XIN", "XOUT", "RST", "TEST", "VCORE"))
    y = refs["crystal"]

    def between(a: str, b: str, lib_id: str) -> list:
        return [
            part
            for part in d.parts
            if part.symbol.lib_id == lib_id and sorted(part.nets.values()) == sorted([a, b])
        ]

    def total(parts) -> float:
        return sum(ratings.part_value(c.value) for c in parts)

    problems = []
    part = next((p for p in d.parts if p.ref == y and p.footprint is not None), None)
    pads = _terminals(crystal.data)
    if part is None:
        problems.append(f"{y}: no crystal on the board [{_eq3_where(chip)}]")
    elif pads is None:
        problems.append(f"{y}: the facts of the crystal name no 2 terminal pads [{crystal.source}]")
    else:
        numbers = {p.number for p in part.footprint.pads}
        carried = [part.nets.get(n) if n in numbers else None for n in pads]
        if sorted(str(c) for c in carried) != sorted([xin, xout]):
            problems.append(
                f"{y}: its terminals, pads {pads[0]} and {pads[1]}, carry {carried[0] or 'none'} and "
                f"{carried[1] or 'none'}, not {xin} and {xout} "
                f"[{crystal.source}, {crystal.data['terminals']['where']}]"
            )
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
        c = total(on[xin])
        parasitic = chip["pin_farads"]["value"] + stray
        cl1 = 2 * crystal.data["farads_load"] - parasitic
        if c != total(on[xout]):
            problems.append(
                f"the 2 load capacitors differ: equation 3 takes 2 equal ones [{_eq3_where(chip)}]"
            )
        elif abs(c - cl1) > tolerance * c * (1 + EPS):
            pair = ", ".join(refs["load"].split())
            got = (c + parasitic) / 2  # equation 3
            problems.append(
                f"{pair}: {_f(c)} is {_f(abs(c - cl1))} from CL1 = {_f(cl1)}, over its {tolerance * 100:g} % "
                f"({_f(tolerance * c)}): CLoad = ({_f(c)} + {_f(parasitic)}) / 2 = {_f(got)}, "
                f"not {_f(crystal.data['farads_load'])} [{_match_where(chip)}]"
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
    pulls = between(vnet, rst, "Device:R")
    r_asked = chip["reset_ohms"]["value"]
    off = [r for r in pulls if abs(ratings.part_value(r.value) - r_asked) > r_asked * EPS]
    if not pulls:
        problems.append(f"no pull-up from {rst} to {vnet} [{_where(chip, 'reset_ohms')}]")
    elif off:
        problems.append(
            f"{rst} is pulled up to {vnet} by {ratings.si(ratings.part_value(off[0].value), 'ohm')}, not "
            f"{ratings.si(r_asked, 'ohm')} [{_where(chip, 'reset_ohms')}]"
        )
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
