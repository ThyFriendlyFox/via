"""blocks_ldo — the linear regulator block: a fixed-output LDO, its input capacitor and its output
capacitor, from the input range, the output voltage, the load current and the project's ambient.

The note is TI SLVA079, "Understanding the Terms and Definitions of LDO Voltage Regulators": the dropout
as the load current times the pass element's on-resistance (equation 1, page 2), the output capacitor
held to its maker's stable range (section 10, page 9), and the dissipation against the junction's limit
(equations 10 and 11, page 11). The IC's own numbers, its datasheet's, stand in `rules/blocks/ldo.json`
with their pages; each part's ratings are read from `library/facts/`, as `workcenter ratings` reads them.

The block tries the stocked ICs that the rules hold, in the stock's order, and takes the first that holds
every check: the output it gives holds the output asked, the input stays in its operating range, the load
in its recommended current, the input at its least stays over the output and the dropout at the full
load, the junction at the project's greatest ambient, dissipating at the least output its accuracy gives,
stays under the pack's derated limit (the sum of tools/thermal.py, roadmap item 7), and the junction from
the least ambient to that one stays in the datasheet's recommended span. Then each capacitor: the first
stocked one of a dielectric the datasheet names, rated over its pin's greatest voltage, whose value less
its tolerance, kept at that voltage on its maker's curve (roadmap item 4) and at the ambient's worst on
its curve over temperature, stays over the effective capacitance the datasheet asks, and whose value lies
in the datasheet's span. What no stocked part meets is refused on 1 line. A spec range written greatest
first, a number that is not finite, or an entry of the rules or the facts that the block cannot read is
refused or passed over on 1 line, before any sum.

Standard library only, as kicadgen is.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import blocks
import ratings
import thermal

RULES = blocks.RULES / "ldo.json"
PACKS = blocks.ROOT / "rules" / "ratings"
si = ratings.si


def _g(x: float) -> str:
    return f"{x:.4g}"


# What ldo reads of an IC's entry in its rules: its own names, each number with its `where`, and the
# entries that hold only a `where`.
LDO_NAMES = ("mpn", "maker", "value", "symbol", "footprint", "pins", "source")
LDO_NUMBERS = (
    "vout_nominal", "accuracy", "amps_max", "dropout", "output_effective", "output_span", "input_effective",
    "input_least", "dielectrics", "junction_span",
)  # fmt: skip
LDO_WHERES = ("normal", "csr", "dissipation")
LDO_PINS = ("IN", "GND", "EN", "OUT")
NOT_HOT = "its value over temperature is not judged: its facts give no kept_celsius"
# The equations of the note the sums cite, each with its page.
LDO_EQUATIONS = ("1", "8", "10", "11")


def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def _pair(v, least=-math.inf) -> bool:
    return isinstance(v, list) and len(v) == 2 and all(_finite(x) and x > least for x in v) and v[0] <= v[1]


# The shape of each number ldo reads, and the words that name it.
SHAPES = {
    "vout_nominal": (lambda v: _finite(v) and v > 0, "a number over 0"),
    "accuracy": (lambda v: _finite(v) and 0 <= v < 1, "a share from 0 to under 1"),
    "amps_max": (lambda v: _finite(v) and v > 0, "a number over 0"),
    "dropout": (lambda v: _finite(v) and v >= 0, "a number of 0 or more"),
    "output_effective": (lambda v: _finite(v) and v > 0, "a number over 0"),
    "output_span": (lambda v: _pair(v, 0), "2 numbers over 0, the least first"),
    "input_effective": (lambda v: _finite(v) and v > 0, "a number over 0"),
    "input_least": (lambda v: _finite(v) and v > 0, "a number over 0"),
    "dielectrics": (
        lambda v: isinstance(v, list) and bool(v) and all(isinstance(x, str) for x in v),
        "a list of names",
    ),
    "junction_span": (lambda v: _pair(v) and v[0] < v[1], "2 numbers, the least first"),
}


def _unentered(chip: dict) -> str | None:
    """What of the IC's entry ldo cannot read: None, or the words that name each key it lacks (or holds
    with no number or no `where`) and each value not of the shape ldo reads."""
    lacks: list[str] = []
    wrong: list[str] = []
    for key in LDO_NAMES:
        if key not in chip:
            lacks.append(key)
        elif key == "pins":
            if not isinstance(chip["pins"], dict):
                wrong.append(f"pins as {chip['pins']!r}, not a map of pin names to numbers")
            else:
                lacks += [f"pins {p}" for p in LDO_PINS if not isinstance(chip["pins"].get(p), str)]
        elif key == "source":
            if not (isinstance(chip["source"], dict) and isinstance(chip["source"].get("document"), str)):
                lacks.append("source document")
        elif not isinstance(chip[key], str) or not chip[key]:
            wrong.append(f"{key} as {chip[key]!r}, not a name")
    for key in LDO_NUMBERS + LDO_WHERES:
        entry = chip.get(key)
        if not (
            isinstance(entry, dict)
            and isinstance(entry.get("where"), str)
            and (key in LDO_WHERES or "value" in entry)
        ):
            lacks.append(key)
            continue
        if key in LDO_WHERES:
            continue
        holds, what = SHAPES[key]
        if not holds(entry["value"]):
            wrong.append(f"{key} as {entry['value']!r}, not {what}")
        if key == "dropout":
            if "amps" not in entry:
                lacks.append("dropout amps")
            elif not (_finite(entry["amps"]) and entry["amps"] > 0):
                wrong.append(f"dropout amps as {entry['amps']!r}, not a number over 0")
    said = ([f"gives it no {', '.join(lacks)}"] if lacks else []) + [f"holds {w}" for w in wrong]
    return "; ".join(said) or None


def _note_lacks(note) -> list[str]:
    """What of the note's entry the sums cite and the rules do not give: its short name, an equation's
    page."""
    if not isinstance(note, dict):
        return ["entry"]
    out = [] if isinstance(note.get("short"), str) else ["short name"]
    equations = note.get("equations") if isinstance(note.get("equations"), dict) else {}
    for n in LDO_EQUATIONS:
        entry = equations.get(n)
        if not (isinstance(entry, dict) and isinstance(entry.get("page"), int)):
            out.append(f"page of equation {n}")
    return out


def _facts_lack(f) -> list[str]:
    """What of the IC's facts the sums read and the facts do not give."""
    supply = next((p for p in f.data.get("pins", []) if p.get("name") == "IN"), None)
    out = []
    if supply is None:
        out.append("pin IN")
    else:
        out += [f"IN {key}" for key in ("operating", "amps") if key not in supply]
    if "theta_ja" not in f.data.get("thermal", {}):
        out.append("thermal theta_ja")
    return out


def _least_kept(curve: list[list[float]], low: float, high: float) -> float | None:
    """The least share of its value a capacitor keeps from `low` to `high` C on its maker's curve over
    temperature: at the 2 ends and at each point between. None when the curve does not cover the span."""
    if low < curve[0][0] or high > curve[-1][0]:
        return None
    shares = [ratings.kept_at(curve, low), ratings.kept_at(curve, high)]
    return min(shares + [share for celsius, share in curve if low < celsius < high])


def built(chip) -> tuple[float, float]:
    """The output an IC builds: its nominal less and plus its accuracy, the datasheet's span."""
    nom, acc = chip["vout_nominal"]["value"], chip["accuracy"]["value"]
    return round(nom * (1 - acc), 9), round(nom * (1 + acc), 9)


def _check_ic(chip, f, vin, vout, amps, ambient, pack, note, eq):  # noqa: PLR0913
    """The sums of 1 IC, or the line that says why it misses: (sums, None) or (None, miss)."""
    mpn = chip["mpn"]
    ds = chip["source"]["document"]
    if lacking := _facts_lack(f):
        return None, (
            f"{mpn}: {f.where} gives no {', '.join(lacking)}: the block judges no IC whose facts lack "
            f"{'it' if len(lacking) == 1 else 'them'}"
        )
    supply = next(p for p in f.data["pins"] if p.get("name") == "IN")
    ambient_min, ambient_max = ambient
    # The output it builds: its nominal, held to the output asked, and its accuracy's span.
    nom, acc = chip["vout_nominal"]["value"], chip["accuracy"]["value"]
    nom_where = f"{ds}, {chip['vout_nominal']['where']}"
    if abs(nom - vout) > ratings.EPS * max(abs(vout), 1.0):
        return (
            None,
            f"{mpn} regulates to VOUT(NOM) = {si(nom, 'V')}, not the {_g(vout)} V asked [{nom_where}]",
        )
    lo, hi = built(chip)
    sums = [
        f"U: {mpn} regulates to VOUT(NOM) = {si(nom, 'V')}, the {_g(vout)} V asked; with its accuracy, "
        f"{si(nom, 'V')} x (1 +- {acc:g}) = {si(lo, 'V')} to {si(hi, 'V')} "
        f"[{nom_where}; {chip['accuracy']['where']}]"
    ]
    vout = nom
    vin_low, vin_high = vin
    op_lo, op_hi = supply["operating"]
    in_where = f"{f.source}, {ratings._p(supply['page'])}"
    if vin_high > op_hi or vin_low < op_lo:
        reach = vin_high if vin_high > op_hi else vin_low
        return None, (
            f"{mpn}: the input reaches {si(reach, 'V')}, IN operates from {si(op_lo, 'V')} to "
            f"{si(op_hi, 'V')} [{in_where}]"
        )
    sums.append(
        f"U: the input, {si(vin_low, 'V')} to {si(vin_high, 'V')}, is within IN's "
        f"{si(op_lo, 'V')} to {si(op_hi, 'V')} [{in_where}]"
    )
    most = chip["amps_max"]["value"]
    amps_where = f"{ds}, {chip['amps_max']['where']}"
    if amps > most:
        return None, f"{mpn}: IOUT of {si(amps, 'A')} is over {si(most, 'A')} [{amps_where}]"
    sums.append(f"U: IOUT of {si(amps, 'A')}, under {si(most, 'A')} [{amps_where}]")

    # The dropout: SLVA079 equation 1, the on-resistance from the datasheet's greatest VDO at its current.
    drop = chip["dropout"]
    vdo = amps * drop["value"] / drop["amps"]
    head = vout + vdo
    drop_where = f"{eq('1')}; {ds}, {drop['where']}; {chip['normal']['where']}"
    line = (
        f"VDO = {si(amps, 'A')} x {si(drop['value'], 'V')} / {si(drop['amps'], 'A')} = "
        f"{si(vdo, 'V')}; VOUT(NOM) + VDO = {_g(vout)} V + {si(vdo, 'V')} = {_g(head)} V"
    )
    if not vin_low > head:
        return None, f"{mpn}: {line}, not under the least input, {_g(vin_low)} V [{drop_where}]"
    sums.append(f"U: {line}, under the least input, {_g(vin_low)} V [{drop_where}]")

    # The dissipation and the junction: the datasheet's equations 6 and 7, SLVA079's 10 and 11, item 7's
    # limit from the pack. The IC dissipates the most at the greatest input and the least output its
    # accuracy allows.
    ground = supply["amps"]
    watts = (ground + amps) * (vin_high - lo)
    pd_where = f"{eq('11')}; {ds}, {chip['dissipation']['where']}"
    sums.append(
        f"U: PD = ({si(ground, 'A')} + {si(amps, 'A')}) x ({vin_high:g} V - {lo:g} V, the least output) = "
        f"{si(watts, 'W')} [{pd_where}]"
    )
    term = f.data["thermal"]
    theta, rated = term["theta_ja"], term["junction_max"]
    kind = thermal.kind_of(f)
    rule = thermal.rule_for(pack, kind)
    if rule is None:
        limit, said = (
            rated,
            f"{rated:g} C, the part's own rating: {pack.name} has no junction rule for {kind}",
        )
    else:
        limit, how = thermal.limit(rule, rated)
        said = f"{how} ({pack.name}, {rule.where})"
    junction = ambient_max + theta * watts
    tj_where = (
        f"{note['short']}, equation 10, page {note['equations']['10']['page']}; {pd_where}; "
        f"theta_ja and junction_max of {f.source}, {ratings._p(term['page'])}"
    )
    tj = f"TJ = {ambient_max:g} C + {theta:g} C/W x {si(watts, 'W')} = {junction:.5g} C at the most ambient"
    if not junction <= limit:
        return None, f"{mpn}: {tj}, over {said} [{tj_where}]"
    sums.append(
        f"U: {tj}, under {said}; PD(max) = ({limit:g} C - {ambient_max:g} C) / {theta:g} C/W = "
        f"{si((limit - ambient_max) / theta, 'W')}; {thermal.assumes(theta)} [{tj_where}]"
    )
    # The junction from the least ambient, where it starts at no load, to the most: the recommended span.
    tj_lo, tj_hi = chip["junction_span"]["value"]
    held = tj_lo <= ambient_min <= junction <= tj_hi
    span = (
        f"TJ from the least ambient, {ambient_min:g} C, to {junction:.5g} C, {'' if held else 'not '}within "
        f"TJ's {tj_lo:g} C to {tj_hi:g} C [{ds}, {chip['junction_span']['where']}]"
    )
    if not held:
        return None, f"{mpn}: {span}"
    sums.append(f"U: {span}")
    return sums, None


def _capacitor(chip, caps, volts, ref, which, ambient):  # noqa: PLR0913
    """The first stocked capacitor that holds the pin at `volts`: (stock, facts, sum), or Refused."""
    ds = chip["source"]["document"]
    good = chip["dielectrics"]["value"]
    least = chip[f"{which}_effective"]["value"]
    if which == "output":
        lo, hi = chip["output_span"]["value"]
        span_where = chip["output_span"]["where"]
        where = f"{ds}, {chip['output_effective']['where']}; {span_where}; {chip['dielectrics']['where']}"
    else:
        lo, hi = chip["input_least"]["value"], None
        span_where = chip["input_least"]["where"]
        where = f"{ds}, {chip['input_effective']['where']}; {span_where}; {chip['dielectrics']['where']}"
    missed = []
    for s, cf in caps:
        farads = ratings.part_value(s.value)
        dielectric = cf.data.get("dielectric")
        if dielectric not in good:
            missed.append(f"{s.mpn}: {dielectric or 'no dielectric'}, not {' or '.join(good)}")
        elif cf.data["volts"] <= volts:
            missed.append(f"{s.mpn}: rated {si(cf.data['volts'], 'V')}, not over {si(volts, 'V')}")
        elif farads < lo * (1 - ratings.EPS) or (hi is not None and farads > hi * (1 + ratings.EPS)):
            span = f"outside {si(lo, 'F')} to {si(hi, 'F')}" if hi else f"under {si(lo, 'F')}"
            missed.append(f"{s.mpn}: {si(farads, 'F')}, {span}")
        elif "kept" not in cf.data:
            missed.append(f"{s.mpn}: its facts give no value it keeps under voltage")
        elif (share := ratings.kept_at(cf.data["kept"], volts)) is None:
            missed.append(f"{s.mpn}: its kept value ends under {si(volts, 'V')}")
        elif "kept_celsius" in cf.data and (hot := _least_kept(cf.data["kept_celsius"], *ambient)) is None:
            curve = cf.data["kept_celsius"]
            missed.append(
                f"{s.mpn}: its kept_celsius covers {curve[0][0]:g} C to {curve[-1][0]:g} C, not the "
                f"ambient's {ambient[0]:g} C to {ambient[1]:g} C"
            )
        else:
            # Over temperature: the least share on its maker's curve from the least ambient to the most,
            # or, with no curve, not judged and said so.
            hot = _least_kept(cf.data["kept_celsius"], *ambient) if "kept_celsius" in cf.data else None
            low = 1 - cf.data["tolerance"]
            each = farads * low * share * (1.0 if hot is None else hot)
            sum_ = (
                f"{si(farads, 'F')} x {low:g} x {share:.3g}{'' if hot is None else f' x {hot:.3g}'} = "
                f"{si(each, 'F')}, {'over' if each > least else 'not over'} {si(least, 'F')}"
            )
            if each <= least:
                missed.append(f"{s.mpn}: {sum_}")
                continue
            span = f"is within {si(lo, 'F')} to {si(hi, 'F')}" if hi else f"is {si(lo, 'F')} or more"
            kept = f"keeps {share:.3g} of {si(farads, 'F')} at {si(volts, 'V')}"
            if hot is None:
                span += f"; {NOT_HOT}"
            else:
                kept += f" and {hot:.3g} of it at {ambient[0]:g} C to {ambient[1]:g} C"
            line = (
                f"{ref}: {s.mpn}, {dielectric}, rated {si(cf.data['volts'], 'V')}, {kept}: {sum_}; "
                f"{si(farads, 'F')} {span} [{where}]"
            )
            return s, line
    raise blocks.Refused(
        f"no stocked capacitor holds {ref} at {si(volts, 'V')}: {'; '.join(missed)} [{where}]"
    )


def ldo(  # noqa: PLR0913
    d,
    *,
    vin: tuple[float, float],
    vout: float,
    amps: float,
    ambient: tuple[float, float],
    pack: str,
    nets: tuple[str, str, str],
    stock: list[blocks.Stock],
    facts: Path,
    sch_at: tuple[float, float],
    pcb_at: tuple[float, float],
    refs: dict[str, str] | None = None,
    rules: Path = RULES,
) -> blocks.Block:
    """A fixed-output linear regulator from `nets` = (input, output, ground): the IC, its input capacitor
    and its output capacitor, by TI SLVA079 and the IC's datasheet. `ambient` is the project's (least,
    greatest) air temperature in C; `pack` the rating pack whose junction rule limits the IC."""
    refs = {"ic": "U1", "input": "C1", "output": "C2"} | (refs or {})
    u = refs["ic"]
    data = blocks.load_rules(rules)
    note = data.get("note")
    if lacking := _note_lacks(note):
        raise blocks.Refused(
            f"ldo {u}: {Path(rules).name}: its note gives no {', '.join(lacking)}: the block cites each "
            "equation it uses with its page"
        )

    def eq(n: str) -> str:
        return f"{note['short']}, equation {n}, page {note['equations'][n]['page']}"

    # The spec: each number finite, each range (least, greatest). NaN is under no limit and over none.
    for name, given, pair in (("vin", vin, True), ("vout", vout, False), ("amps", amps, False),
                              ("ambient", ambient, True)):  # fmt: skip
        numbers = tuple(given) if pair and isinstance(given, (tuple, list)) else (given,)
        if not (all(_finite(x) for x in numbers) and len(numbers) == (2 if pair else 1)):
            raise blocks.Refused(f"ldo {u}: {name}={given!r}: each number of the spec must be finite")
    if vin[0] > vin[1]:
        raise blocks.Refused(
            f"ldo {u}: vin=({vin[0]:g}, {vin[1]:g}) is written greatest first: vin is (least, greatest), and "
            f"the block takes the dropout at the least and the dissipation at the greatest [{eq('1')}; "
            f"{eq('11')}]"
        )
    if ambient[0] > ambient[1]:
        raise blocks.Refused(
            f"ldo {u}: ambient=({ambient[0]:g}, {ambient[1]:g}) is written greatest first: ambient is "
            f"(least, greatest) in C, and the block takes the junction at the greatest [{eq('10')}]"
        )
    if amps <= 0:
        raise blocks.Refused(
            f"ldo {u}: a load of {si(amps, 'A')}: the block sizes the dropout and the dissipation for "
            f"a load over 0 A [{note['short']}, equations 1 and 11, pages {note['equations']['1']['page']} "
            f"and {note['equations']['11']['page']}]"
        )
    held = {c["mpn"]: c for c in data["ics"]}
    found = ratings.read_facts(Path(facts))
    the_pack = ratings.read_pack(PACKS / f"{pack}.json")
    sums: list[str] = []
    misses: list[str] = []
    taken = None
    for item in stock:
        chip = held.get(item.mpn)
        if chip is None:
            continue
        if lacking := _unentered(chip):
            miss = (
                f"{item.mpn}: {Path(rules).name} {lacking}: the block builds no IC whose numbers are not all "
                "entered"
            )
            misses.append(miss)
            sums.append(f"{u}: {item.mpn} passed over: {miss[len(item.mpn) + 2 :]}")
            continue
        f = blocks._facts(found, item, chip["symbol"])
        if f is None:
            misses.append(f"{item.mpn}: {facts} holds no facts of it")
            continue
        got, miss = _check_ic(chip, f, vin, vout, amps, ambient, the_pack, note, eq)
        if miss:
            misses.append(miss)
            sums.append(f"{u}: {item.mpn} passed over: {miss[len(item.mpn) :].lstrip(': ')}")
            continue
        taken = (item, chip, f)
        sums += [line.replace("U:", f"{u}:", 1) for line in got]
        break
    if taken is None:
        if not misses:
            names = ", ".join(held)
            raise blocks.Refused(f"ldo {u}: no stocked IC is one of {Path(rules).name}; it holds {names}")
        raise blocks.Refused(f"ldo {u}: no stocked IC holds the spec: {'; '.join(misses)}")
    item, chip, f = taken
    out_hi = built(chip)[1]
    caps = [
        (s, cf)
        for s in stock
        if (cf := blocks._facts(found, s)) is not None and cf.kind.startswith("capacitor")
    ]
    try:
        out_cap, out_line = _capacitor(chip, caps, out_hi, refs["output"], "output", ambient)
        sums.append(f"{out_line}; its CSR is not judged: {chip['csr']['where']} [{eq('8')}]")
        in_cap, in_line = _capacitor(chip, caps, vin[1], refs["input"], "input", ambient)
        sums.append(in_line)
    except blocks.Refused as exc:
        raise blocks.Refused(f"ldo {u}: {exc}") from None

    # The parts, placed from the block's corner on the sheet and on the board.
    vin_net, vout_net, gnd = nets
    sx, sy = sch_at
    px, py = pcb_at
    p = chip["pins"]
    pin_nets = {p["IN"]: vin_net, p["EN"]: vin_net, p["GND"]: gnd, p["OUT"]: vout_net}
    if "PAD" in p:
        pin_nets[p["PAD"]] = gnd
    d.add(u, chip["symbol"], chip["value"], chip["footprint"], sch_at=(sx + 25.4, sy),
          pcb_at=(px + 6.0, py), nets=pin_nets)  # fmt: skip
    d.add(refs["input"], "Device:C", in_cap.value, in_cap.footprint, sch_at=(sx, sy + 7.62),
          pcb_at=(px + 1.5, py), nets={"1": vin_net, "2": gnd})  # fmt: skip
    d.add(refs["output"], "Device:C", out_cap.value, out_cap.footprint, sch_at=(sx + 50.8, sy + 7.62),
          pcb_at=(px + 10.5, py), nets={"1": vout_net, "2": gnd})  # fmt: skip

    rows = blocks.rows_of([(blocks.Stock(chip["maker"], item.mpn, chip["value"], chip["footprint"]), 1),
                           (in_cap, 1), (out_cap, 1)])  # fmt: skip
    call = f"ldo(ambient=({ambient[0]:g}, {ambient[1]:g}))"
    entries = {
        "nets": {
            vin_net: {
                "volts": [vin[0], vin[1]],
                "source": f"the input range of the ldo block {u}: ldo(vin=({_g(vin[0])}, {_g(vin[1])}))",
            }
        },
        "ambient": {"max": ambient[1], "source": f"the ambient of the ldo block {u}: {call}"},
    }
    files = _deck(u, item.mpn, chip, f, vin[1], vout, amps, ambient, pack, call, sums)
    return blocks.Block("ldo", sums, entries, rows, files)


def _deck(u, mpn, chip, f, vin, vout, amps, ambient, pack, call, sums):  # noqa: PLR0913
    """sim/ldo.cir, its bound, its corners and its thermal plan: the IC drawn as what it does at the
    greatest input into the load, its power for the SIM gate to hold its junction by (item 7). Its output
    is drawn, at the least its accuracy gives, where it dissipates the most: no bound holds it."""
    ground = next(p for p in f.data["pins"] if p.get("name") == "IN")["amps"]
    most = chip["amps_max"]
    nom, (lo, hi) = chip["vout_nominal"]["value"], built(chip)
    lines = [
        f"ldo: the linear regulator block {u} ({mpn}), written by tools/blocks_ldo.py",
        f"* {u} is drawn as what it does: its output holds {lo:g} V, the least of its nominal, {_g(nom)} V,",
        f"* with its accuracy, {lo:g} V to {hi:g} V, where it dissipates the most; its input carries the",
        f"* load's current and its greatest ground current, {si(ground, 'A')} [{f.source}].",
        f"* vout is drawn, not judged: no bound holds it, since the deck does not model {u}'s regulation.",
        f"* The input is the greatest, {_g(vin)} V; the load is {si(amps, 'A')}, a current source.",
        f"* p_{u.lower()} is {u}'s input power less its output power: what its junction dissipates.",
        "* sim/thermal.json names it, and the SIM gate holds the junction at each temperature of",
        "* sim/corners.json.",
        "* The sums:",
        *[f"*   {line}" for line in sums],
        f"VIN in 0 DC {_g(vin)}",
        f"B{u} reg 0 V={lo:g}",
        f"V{u} reg out DC 0",
        f"F{u} in 0 V{u} 1",
        f"I{u} in 0 DC {_g(ground * 1e6)}u",
        f"ILOAD out 0 DC {_g(amps)}",
        ".control",
        "op",
        f"let iout = i(v{u.lower()})",
        "let vout = v(out)",
        f"let p_{u.lower()} = -v(in) * i(vin) - v(out) * i(v{u.lower()})",
        f"print iout vout p_{u.lower()}",
        ".endc",
        ".end",
    ]
    expect = {
        "iout": {
            "max": most["value"],
            "source": f"{u} {mpn} gives {si(most['value'], 'A')} at the most "
            f"[{chip['source']['document']}, {most['where']}]",
        },
    }
    corners = {
        "temperature": {
            "values": [ambient[0], ambient[1]],
            "source": f"the ambient of the ldo block {u}: {call}",
        }
    }
    plan = {
        "pack": pack,
        "parts": {
            u: {
                "mpn": mpn,
                "watts": f"ldo.p_{u.lower()}",
                "source": "the deck's input power less its output power",
            }
        },
    }
    return {
        "sim/ldo.cir": "\n".join(lines) + "\n",
        "sim/ldo.expect.json": json.dumps(expect, indent=2) + "\n",
        "sim/corners.json": json.dumps(corners, indent=2) + "\n",
        "sim/thermal.json": json.dumps(plan, indent=2) + "\n",
    }
