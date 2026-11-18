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
load, and the junction at the project's greatest ambient stays under the pack's derated limit (the sum of
tools/thermal.py, roadmap item 7). Then each capacitor: the first stocked one of a dielectric the
datasheet names, rated over its pin's greatest voltage, whose value less its tolerance, kept at that
voltage on its maker's curve (roadmap item 4), stays over the effective capacitance the datasheet asks,
and whose value lies in the datasheet's span. What no stocked part meets is refused on 1 line.

Standard library only, as kicadgen is.
"""

from __future__ import annotations

import json
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
    "input_least", "dielectrics",
)  # fmt: skip
LDO_WHERES = ("normal", "csr", "dissipation")


def _unentered(chip: dict) -> list[str]:
    """The keys ldo reads that the IC's entry lacks, or holds with no number or no `where`."""
    out = [key for key in LDO_NAMES if key not in chip]
    for key in LDO_NUMBERS + LDO_WHERES:
        entry = chip.get(key)
        if not (isinstance(entry, dict) and "where" in entry and (key in LDO_WHERES or "value" in entry)):
            out.append(key)
    return out


def built(chip) -> tuple[float, float]:
    """The output an IC builds: its nominal less and plus its accuracy, the datasheet's span."""
    nom, acc = chip["vout_nominal"]["value"], chip["accuracy"]["value"]
    return round(nom * (1 - acc), 9), round(nom * (1 + acc), 9)


def _check_ic(chip, f, vin, vout, amps, ambient_max, pack, note, eq):  # noqa: PLR0913
    """The sums of 1 IC, or the line that says why it misses: (sums, None) or (None, miss)."""
    mpn = chip["mpn"]
    ds = chip["source"]["document"]
    supply = next(p for p in f.data["pins"] if p["name"] == "IN")
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
    # limit from the pack.
    ground = supply.get("amps", 0.0)
    watts = (ground + amps) * (vin_high - vout)
    pd_where = f"{eq('11')}; {ds}, {chip['dissipation']['where']}"
    sums.append(
        f"U: PD = ({si(ground, 'A')} + {si(amps, 'A')}) x ({_g(vin_high)} V - {_g(vout)} V) = "
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
    tj = f"TJ = {ambient_max:g} C + {theta:g} C/W x {si(watts, 'W')} = {junction:.4g} C at the most ambient"
    if junction > limit:
        return None, f"{mpn}: {tj}, over {said} [{tj_where}]"
    sums.append(
        f"U: {tj}, under {said}; PD(max) = ({limit:g} C - {ambient_max:g} C) / {theta:g} C/W = "
        f"{si((limit - ambient_max) / theta, 'W')} [{tj_where}]"
    )
    return sums, None


def _capacitor(chip, caps, volts, ref, which):
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
        else:
            low = 1 - cf.data["tolerance"]
            each = farads * low * share
            sum_ = (
                f"{si(farads, 'F')} x {low:g} x {share:.3g} = {si(each, 'F')}, "
                f"{'over' if each > least else 'not over'} {si(least, 'F')}"
            )
            if each <= least:
                missed.append(f"{s.mpn}: {sum_}")
                continue
            span = f"is within {si(lo, 'F')} to {si(hi, 'F')}" if hi else f"is {si(lo, 'F')} or more"
            line = (
                f"{ref}: {s.mpn}, {dielectric}, rated {si(cf.data['volts'], 'V')}, keeps {share:.3g} "
                f"of {si(farads, 'F')} at {si(volts, 'V')}: {sum_}; {si(farads, 'F')} "
                f"{span} [{where}]"
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
    note = data["note"]

    def eq(n: str) -> str:
        return f"{note['short']}, equation {n}, page {note['equations'][n]['page']}"

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
                f"{item.mpn}: {Path(rules).name} gives it no {', '.join(lacking)}: the block builds no IC "
                "whose numbers are not all entered"
            )
            misses.append(miss)
            sums.append(f"{u}: {item.mpn} passed over: {miss[len(item.mpn) + 2 :]}")
            continue
        f = blocks._facts(found, item, chip["symbol"])
        if f is None:
            misses.append(f"{item.mpn}: {facts} holds no facts of it")
            continue
        got, miss = _check_ic(chip, f, vin, vout, amps, ambient[1], the_pack, note, eq)
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
        out_cap, out_line = _capacitor(chip, caps, out_hi, refs["output"], "output")
        sums.append(f"{out_line}; its CSR is not judged: {chip['csr']['where']} [{eq('8')}]")
        in_cap, in_line = _capacitor(chip, caps, vin[1], refs["input"], "input")
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
    greatest input into the load, its power for the SIM gate to hold its junction by (item 7)."""
    ground = next(p for p in f.data["pins"] if p["name"] == "IN").get("amps", 0.0)
    most = chip["amps_max"]
    nom, (lo, hi) = chip["vout_nominal"]["value"], built(chip)
    lines = [
        f"ldo: the linear regulator block {u} ({mpn}), written by tools/blocks_ldo.py",
        f"* {u} is drawn as what it does: its output holds its nominal, {_g(nom)} V, and its input",
        f"* carries the load's current and its greatest ground current, {si(ground, 'A')} [{f.source}].",
        f"* vout is held to the span its accuracy gives, {si(lo, 'V')} to {si(hi, 'V')}.",
        f"* The input is the greatest, {_g(vin)} V; the load is {si(amps, 'A')}, a current source.",
        f"* p_{u.lower()} is {u}'s input power less its output power: what its junction dissipates.",
        "* sim/thermal.json names it, and the SIM gate holds the junction at each temperature of",
        "* sim/corners.json.",
        "* The sums:",
        *[f"*   {line}" for line in sums],
        f"VIN in 0 DC {_g(vin)}",
        f"B{u} reg 0 V={_g(nom)}",
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
        "vout": {
            "min": lo,
            "max": hi,
            "source": f"{u} {mpn} regulates to {si(nom, 'V')} x (1 +- {chip['accuracy']['value']:g}), the "
            f"{_g(vout)} V asked [{chip['source']['document']}, {chip['vout_nominal']['where']}; "
            f"{chip['accuracy']['where']}]",
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
