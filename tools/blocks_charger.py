"""blocks.charger: a linear charger for 1 lithium cell with its protection IC and its 2 transistors.

The charger is TI's BQ21040 and the protector TI's BQ29700, each from its datasheet: the programming
resistor by its equation 1, the capacitors by its pin table and its typical application, the charger's
dissipation by its equation 8 at the greatest input and the least cell voltage, and its junction by
TJ = TA + RthetaJA x P (TI SPRA953D, section 1.1, equation 1, page 2; the sum tools/thermal.py makes
at every corner of the SIM gate). The protector's thresholds are held to the cell's limits the design
states, and its 2 transistors to the procedure of its section 9.2.2. The numbers stand in
rules/blocks/charger.json with their clause and page; a part's own ratings in library/facts/.

The block checks what it builds before it returns: a charge current the IC, its resistor range or its
dissipation does not allow is refused in 1 line with the equation and its page.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import blocks
import ratings

RULES = blocks.RULES / "charger.json"


@dataclass(frozen=True)
class Cell:
    """The cell's limits the design states, from the cell's datasheet: its least and greatest voltage,
    the greatest current it takes in charge and gives in discharge, and where they come from."""

    volts: tuple[float, float]
    charge_amps: float
    discharge_amps: float
    source: str


def _g(x: float) -> str:
    return f"{x:.4g}"


def _row(rows: list, amps: float) -> list | None:
    """KISET's row of a current: [least, greatest, MIN, TYP, MAX]."""
    return next((r for r in rows if r[0] <= amps <= r[1]), None)


def _capacitor(u, caps, volts, span, where, kept_needed=True):  # noqa: PLR0913
    """The first stocked capacitor rated over `volts` whose value lies in `span` and, when its facts give
    the value it keeps, keeps the least of the span at `volts` less its tolerance."""
    low, high = span
    missed = []
    for s, cf in caps:
        farads = ratings.part_value(s.value)
        if cf.data["volts"] < volts:
            missed.append(
                f"{s.mpn}: rated {ratings.si(cf.data['volts'], 'V')}, under {ratings.si(volts, 'V')}"
            )
        elif farads > high * (1 + ratings.EPS) or farads < low * (1 - ratings.EPS):
            missed.append(f"{s.mpn}: {ratings.si(farads, 'F')}, outside {ratings.si(low, 'F')} to "
                          f"{ratings.si(high, 'F')}")  # fmt: skip
        elif "kept" not in cf.data:
            if kept_needed:
                missed.append(f"{s.mpn}: its facts give no value it keeps under voltage")
            else:
                return (s, cf), None
        else:
            share = ratings.kept_at(cf.data["kept"], volts)
            if share is None:
                missed.append(f"{s.mpn}: its kept value ends under {ratings.si(volts, 'V')}")
                continue
            each = farads * (1 - cf.data["tolerance"]) * share
            if each < low * (1 - ratings.EPS):
                missed.append(f"{s.mpn}: keeps {ratings.si(each, 'F')} at {ratings.si(volts, 'V')}")
            else:
                return (s, cf), each
    raise blocks.Refused(
        f"charger {u}: no stocked capacitor of {ratings.si(low, 'F')} to {ratings.si(high, 'F')} rated for "
        f"{ratings.si(volts, 'V')}: {'; '.join(missed) or 'the stock holds none with facts'} [{where}]"
    )


def charger(  # noqa: PLR0912, PLR0913, PLR0915
    d,
    *,
    ic: str,
    protector: str,
    vin: tuple[float, float],
    amps: float,
    cell: Cell,
    load: float,
    ambient: tuple[float, float],
    pack: str,
    nets: dict[str, str],
    stock: list[blocks.Stock],
    facts: Path,
    sch_at: tuple[float, float],
    pcb_at: tuple[float, float],
    refs: dict[str, str] | None = None,
    rules: Path = RULES,
) -> blocks.Block:
    """The charger from `nets`: "in" the input, "bat" the cell's positive and the system's supply,
    "gnd" the system's ground (Pack-), "cell" the cell's negative, "chg" the charger's status. `amps` is
    the fast charge current asked; `load` the greatest current the system draws from the cell."""
    refs = {
        "ic": "U1",
        "protector": "U2",
        "iset": "R1",
        "ts": "R2",
        "filter": "R3",
        "sense": "R4",
        "input": "C1",
        "output": "C2",
        "bat": "C3",
        "dsg": "Q1",
        "chg": "Q2",
    } | (refs or {})
    u, p2 = refs["ic"], refs["protector"]
    data = blocks.load_rules(rules)
    chip, guard = data["charger"], data["protector"]
    if chip["mpn"] != ic:
        raise blocks.Refused(f"charger {u}: {ic} is no charger of {Path(rules).name}; it holds {chip['mpn']}")
    if guard["mpn"] != protector:
        raise blocks.Refused(
            f"charger {p2}: {protector} is no protector of {Path(rules).name}; it holds {guard['mpn']}"
        )
    short, gshort = chip["short"], guard["short"]

    def at(entry: dict, key: str) -> str:
        return f"{entry['source']['document']}, {entry[key]['where']}"

    def eq(n: str) -> str:
        return f"{short}, equation {n}, page {chip['equations'][n]['page']}"

    found = ratings.read_facts(Path(facts))
    chip_facts = blocks._facts(found, blocks.Stock("", ic, "", chip["footprint"]), chip["symbol"])
    if chip_facts is None or "thermal" not in chip_facts.data:
        raise blocks.Refused(f"charger {u}: {facts} holds no facts of {ic} with its thermal figures")
    sums: list[str] = []

    # The input, the current asked and the cell's limits, before any part is taken.
    low, high = chip["vin"]["value"]
    vin_low, vin_high = vin
    if vin_low < low or vin_high > high:
        reach = vin_high if vin_high > high else vin_low
        raise blocks.Refused(
            f"charger {u}: the input reaches {ratings.si(reach, 'V')}, IN of {ic} operates from "
            f"{ratings.si(low, 'V')} to {ratings.si(high, 'V')} [{at(chip, 'vin')}]"
        )
    least, most = chip["amps"]["value"]
    if not least <= amps <= most:
        raise blocks.Refused(
            f"charger {u}: a charge current of {ratings.si(amps, 'A')} is outside {ic}'s "
            f"{ratings.si(least, 'A')} to {ratings.si(most, 'A')} [{at(chip, 'amps')}]"
        )
    cell_low, cell_high = cell.volts

    # The programming resistor: equation 1 at KISET's typical value, then the stock's nearest, then the
    # span of current it gives with KISET's limits and the resistor's tolerance.
    row = _row(chip["kiset"]["rows"], amps)
    k_min, k_typ, k_max = row[2:]
    r_asked = k_typ / amps  # equation 1
    resistors = [
        (s, rf) for s in stock if (rf := blocks._facts(found, s)) is not None and rf.kind == "resistor"
    ]
    r_low, r_high = chip["riset"]["value"]
    near = [pair for pair in resistors if r_low <= ratings.part_value(pair[0].value) <= r_high]
    if not r_low <= r_asked <= r_high or not near:
        raise blocks.Refused(
            f"charger {u}: RISET = {k_typ} AΩ / {ratings.si(amps, 'A')} = {ratings.si(r_asked, 'ohm')}, "
            f"outside {ratings.si(r_low, 'ohm')} to {ratings.si(r_high, 'ohm')} "
            f"[{eq('1')}; {at(chip, 'riset')}]"
        )
    iset = min(near, key=lambda pair: abs(ratings.part_value(pair[0].value) - r_asked))
    ohms, tol = ratings.part_value(iset[0].value), iset[1].data["tolerance"]
    i_typ = k_typ / ohms
    i_low = k_min / (ohms * (1 + tol))
    i_high = k_max / (ohms * (1 - tol))
    kiset_where = f"{eq('1')}; {at(chip, 'kiset')}"
    span = (
        f"{ratings.si(i_low, 'A')} to {ratings.si(i_high, 'A')} with KISET of {k_min} to {k_max} AΩ and "
        f"{tol * 100:g} % of resistor"
    )
    if not i_low <= amps <= i_high:
        raise blocks.Refused(
            f"charger {u}: RISET of {iset[0].value} sets {ratings.si(i_typ, 'A')}, {span}, and "
            f"{ratings.si(amps, 'A')} is asked: no stocked resistor is near {ratings.si(r_asked, 'ohm')} "
            f"[{kiset_where}]"
        )
    if _row(chip["kiset"]["rows"], i_low) is not row or _row(chip["kiset"]["rows"], i_high) is not row:
        raise blocks.Refused(
            f"charger {u}: {span} crosses a row of KISET: the span is not judged on 1 row [{kiset_where}]"
        )
    sums.append(
        f"{refs['iset']}: RISET = {k_typ} AΩ / {ratings.si(amps, 'A')} = {ratings.si(r_asked, 'ohm')}; the "
        f"stock's nearest is {iset[0].value}, which sets {ratings.si(i_typ, 'A')}, and {span} [{kiset_where}]"
    )
    if i_high > cell.charge_amps * (1 + ratings.EPS):
        raise blocks.Refused(
            f"charger {u}: the charge current reaches {ratings.si(i_high, 'A')}, over the cell's "
            f"{ratings.si(cell.charge_amps, 'A')} [{kiset_where}; {cell.source}]"
        )
    sums.append(
        f"{u}: the charge current reaches {ratings.si(i_high, 'A')}, the cell takes "
        f"{ratings.si(cell.charge_amps, 'A')} [{cell.source}]"
    )

    # The dissipation at the greatest input and the least cell voltage in fast charge (equation 8), and
    # the junction at the greatest ambient.
    vlow = chip["vlowv"]["value"][0]
    vbat = max(cell_low, vlow)
    why = "the cell's least" if vbat == cell_low else "VLOWV's least: under it the charge is 20 %"
    icc = chip["icc"]["value"]
    theta = chip_facts.data["thermal"]["theta_ja"]
    limit = chip["junction"]["value"]
    hot = ambient[1]
    watts = (vin_high - vbat) * i_high + vin_high * icc  # equation 8, and the supply's own current
    tj = hot + theta * watts
    heat_where = (
        f"{eq('8')}; {at(chip, 'vlowv')}; {at(chip, 'icc')}; {at(chip, 'theta_ja')}; {at(chip, 'junction')}; "
        "TJ = TA + RthetaJA x P, TI SPRA953D, section 1.1, equation 1, page 2"
    )
    sum_p = (
        f"P = ({_g(vin_high)} V - {_g(vbat)} V) x {ratings.si(i_high, 'A')} + {_g(vin_high)} V x "
        f"{ratings.si(icc, 'A')} = {watts:.4f} W at {_g(vbat)} V, {why}; "
        f"TJ = {_g(hot)} C + {_g(theta)} C/W x {watts:.4f} W = {tj:.1f} C"
    )
    if tj > limit:
        most_w = (limit - hot) / theta
        most_a = (most_w - vin_high * icc) / (vin_high - vbat)
        raise blocks.Refused(
            f"charger {u}: {sum_p}, over {_g(limit)} C: at {_g(hot)} C the charge current reaches "
            f"{ratings.si(most_a, 'A')} at the most [{heat_where}]"
        )
    sums.append(f"{u}: {sum_p}, under {_g(limit)} C [{heat_where}]")

    # The capacitors on IN and OUT: 1 uF to 10 uF, effective at the voltage each sees.
    caps = [
        (s, cf)
        for s in stock
        if (cf := blocks._facts(found, s)) is not None and cf.kind.startswith("capacitor")
    ]
    cap_where = at(chip, "capacitors")
    c_in, c_in_each = _capacitor(u, caps, vin_high, chip["capacitors"]["value"], cap_where)
    c_out, c_out_each = _capacitor(u, caps, cell_high, chip["capacitors"]["value"], cap_where)
    c_low, c_high = chip["capacitors"]["value"]
    for ref, (s, cf), each, volts in (
        (refs["input"], c_in, c_in_each, vin_high),
        (refs["output"], c_out, c_out_each, cell_high),
    ):
        sums.append(
            f"{ref}: {s.value}, {cf.data.get('dielectric', 'no dielectric')}, keeps {ratings.si(each, 'F')} "
            f"at {ratings.si(volts, 'V')} less {cf.data['tolerance'] * 100:g} %, within "
            f"{ratings.si(c_low, 'F')} to {ratings.si(c_high, 'F')} [{cap_where}]"
        )
    ts_ohms = chip["ts"]["value"]
    ts = next((pair for pair in resistors if ratings.part_value(pair[0].value) == ts_ohms), None)
    if ts is None:
        raise blocks.Refused(
            f"charger {u}: no stocked resistor of {ratings.si(ts_ohms, 'ohm')} [{at(chip, 'ts')}]"
        )

    # The protector's thresholds against the charger and the cell.
    reg_high = chip["vout_reg"]["value"][1]
    ovp, ovp_tol = guard["ovp"]["value"], guard["ovp_tolerance"]["value"]
    ovp_where = f"{at(guard, 'ovp')}; {at(guard, 'ovp_tolerance')}"
    if reg_high >= ovp - ovp_tol:
        raise blocks.Refused(
            f"charger {p2}: {ic} regulates the cell at {ratings.si(reg_high, 'V')} at the most, not under "
            f"{protector}'s least overcharge threshold, {ratings.si(ovp - ovp_tol, 'V')} "
            f"[{at(chip, 'vout_reg')}; {ovp_where}]"
        )
    if ovp + ovp_tol > cell_high * (1 + ratings.EPS):
        raise blocks.Refused(
            f"charger {p2}: the overcharge threshold reaches {_g(ovp)} V + {_g(ovp_tol * 1000)} mV = "
            f"{_g(ovp + ovp_tol)} V, over the cell's {_g(cell_high)} V [{ovp_where}; {cell.source}]"
        )
    sums.append(
        f"{p2}: the overcharge threshold is {_g(ovp - ovp_tol)} V to {_g(ovp + ovp_tol)} V: over the "
        f"charger's {_g(reg_high)} V and within the cell's {_g(cell_high)} V "
        f"[{at(chip, 'vout_reg')}; {ovp_where}; "
        f"{cell.source}]"
    )
    uvp, uvp_tol = guard["uvp"]["value"], guard["uvp_tolerance"]["value"]
    uvp_where = f"{at(guard, 'uvp')}; {at(guard, 'uvp_tolerance')}"
    if uvp - uvp_tol < cell_low * (1 - ratings.EPS):
        raise blocks.Refused(
            f"charger {p2}: the overdischarge threshold reaches {_g(uvp)} V - {_g(uvp_tol * 1000)} mV = "
            f"{_g(uvp - uvp_tol)} V, under the cell's {_g(cell_low)} V [{uvp_where}; {cell.source}]"
        )
    sums.append(
        f"{p2}: the overdischarge threshold is {_g(uvp - uvp_tol)} V at the least, over the cell's "
        f"{_g(cell_low)} V; its tolerance is the one at 25 C, the 1 the datasheet gives [{uvp_where}; "
        f"{cell.source}]"
    )

    # The 2 transistors: section 9.2.2's procedure with each FET's greatest on-resistance.
    occ = guard["occ"]["value"] - guard["occ_tolerance"]["value"]
    ocd_low = guard["ocd"]["value"] - guard["ocd_tolerance"]["value"]
    ocd_high = guard["ocd"]["value"] + guard["ocd_tolerance"]["value"]
    fet_where = (
        f"{gshort}, {guard['ocd_rule']}; {gshort}, {guard['occ_rule']}; {at(guard, 'ocd_tolerance')}; "
        f"{at(guard, 'occ_tolerance')}"
    )
    rated = {t["mpn"]: t for t in data["transistors"]}
    worst = max(load, i_high)
    missed = []
    taken = None
    for s in stock:
        tf = blocks._facts(found, s)
        if tf is None or tf.kind != "transistor.mosfet":
            continue
        if s.mpn not in rated:
            missed.append(f"{s.mpn}: {Path(rules).name} holds no on-resistance of it")
            continue
        r_typ, r_max = rated[s.mpn]["rds_on"]["value"]
        total = 2 * r_max
        if tf.data["volts_drain_source"] < vin_high:
            missed.append(f"{s.mpn}: VDS {ratings.si(tf.data['volts_drain_source'], 'V')}, under the input")
        elif tf.data["volts_gate_source"] < cell_high:
            missed.append(f"{s.mpn}: VGS {ratings.si(tf.data['volts_gate_source'], 'V')}, under the cell")
        elif "amps_drain" in tf.data and tf.data["amps_drain"] < worst:
            missed.append(
                f"{s.mpn}: ID {ratings.si(tf.data['amps_drain'], 'A')}, under {ratings.si(worst, 'A')}"
            )
        elif total * load > ocd_low:
            missed.append(f"{s.mpn}: 2 x {ratings.si(r_max, 'ohm')} x {ratings.si(load, 'A')} = "
                          f"{ratings.si(total * load, 'V')}, over {ratings.si(ocd_low, 'V')}")  # fmt: skip
        elif total * i_high >= occ:
            missed.append(f"{s.mpn}: 2 x {ratings.si(r_max, 'ohm')} x {ratings.si(i_high, 'A')} = "
                          f"{ratings.si(total * i_high, 'V')}, not under {ratings.si(occ, 'V')}")  # fmt: skip
        else:
            taken = (s, tf, r_typ, r_max)
            break
    if taken is None:
        raise blocks.Refused(
            f"charger {p2}: no stocked transistor holds the load of {ratings.si(load, 'A')} and the charge "
            f"of {ratings.si(i_high, 'A')}: {'; '.join(missed) or 'the stock holds none with facts'} "
            f"[{fet_where}]"
        )
    fet, fet_facts, r_typ, r_max = taken
    rds_where = rated[fet.mpn]["rds_on"]["where"]
    total = 2 * r_max
    pair_refs = f"{refs['dsg']}, {refs['chg']}"
    sums.append(
        f"{pair_refs}: {fet.mpn}, 2 x {ratings.si(r_max, 'ohm')} = {ratings.si(total, 'ohm')}; "
        f"the load gives {ratings.si(total * load, 'V')}, under VOCD's least, {ratings.si(ocd_low, 'V')}; "
        f"the charge gives {ratings.si(total * i_high, 'V')}, under OCC's least, {ratings.si(occ, 'V')} "
        f"[{fet_where}; {rds_where}]"
    )
    trip = ocd_high / (2 * r_typ)
    gate = guard["gate_volts"]["value"]
    sums.append(
        f"{pair_refs}: at the typical {ratings.si(r_typ, 'ohm')} the discharge trips at "
        f"{ratings.si(ocd_high, 'V')} / {ratings.si(2 * r_typ, 'ohm')} = {ratings.si(trip, 'A')}, the cell "
        f"gives {ratings.si(cell.discharge_amps, 'A')}; not judged: the trip with a transistor under its "
        f"typical on-resistance, which the datasheet does not bound, and the on-resistance with a gate under "
        f"the {ratings.si(gate, 'V')} the protector gives at a cell of 3.8 V [{fet_where}; {rds_where}; "
        f"{at(guard, 'gate_volts')}; {cell.source}]"
    )
    if trip > cell.discharge_amps:
        raise blocks.Refused(
            f"charger {p2}: the discharge trips at {ratings.si(trip, 'A')} at the typical on-resistance, "
            f"over the cell's {ratings.si(cell.discharge_amps, 'A')} "
            f"[{fet_where}; {rds_where}; {cell.source}]"
        )
    filt = guard["filter_farads"]["value"]
    c_bat, _ = _capacitor(p2, caps, cell_high, (filt, filt), at(guard, "filter_farads"), kept_needed=False)
    sums.append(
        f"{refs['bat']}: {c_bat[0].value} on BAT, rated {ratings.si(c_bat[1].data['volts'], 'V')}; the value "
        f"it keeps is not judged: the datasheet asks {ratings.si(filt, 'F')} and no effective value "
        f"[{at(guard, 'filter_farads')}]"
    )
    pairs = {}
    for key in ("filter_ohms", "sense_ohms"):
        want = guard[key]["value"]
        pair = next((pr for pr in resistors if ratings.part_value(pr[0].value) == want), None)
        if pair is None:
            raise blocks.Refused(
                f"charger {p2}: no stocked resistor of {ratings.si(want, 'ohm')} [{at(guard, key)}]"
            )
        pairs[key] = pair

    # The parts, placed from the block's corner on the sheet and on the board.
    vin_net, bat, gnd, neg, chg = (nets[k] for k in ("in", "bat", "gnd", "cell", "chg"))
    n_iset, n_ts, n_bat, n_vm = f"{u}_ISET", f"{u}_TS", f"{p2}_BAT", f"{p2}_VM"
    n_cout, n_dout, n_mid = f"{p2}_COUT", f"{p2}_DOUT", f"{p2}_FETS"
    sx, sy = sch_at
    px, py = pcb_at
    cp, gp = chip["pins"], guard["pins"]
    fp = rated[fet.mpn]["pins"]

    def two(ref: str, symbol: str, part: blocks.Stock, sch: tuple, pcb: tuple, one: str, other: str) -> None:
        """A part of 2 pins, its corner offsets from the block's on the sheet and on the board."""
        d.add(ref, symbol, part.value, part.footprint, sch_at=(sx + sch[0], sy + sch[1]),
              pcb_at=(px + pcb[0], py + pcb[1]), nets={"1": one, "2": other})  # fmt: skip

    chip_nets = {"VIN": vin_net, "GND": gnd, "OUT": bat, "ISET": n_iset, "TS": n_ts, "CHG": chg}
    d.add(u, chip["symbol"], chip["value"], chip["footprint"], sch_at=(sx + 25.4, sy), pcb_at=(px + 6.0, py),
          nets={cp[name]: net for name, net in chip_nets.items()})  # fmt: skip
    two(refs["iset"], "Device:R", iset[0], (10.16, 17.78), (3.0, 5.0), n_iset, gnd)
    two(refs["ts"], "Device:R", ts[0], (2.54, 17.78), (6.0, 5.0), n_ts, gnd)
    two(refs["input"], "Device:C", c_in[0], (0, 2.54), (1.0, 0), vin_net, gnd)
    two(refs["output"], "Device:C", c_out[0], (45.72, 2.54), (11.0, 0), bat, gnd)
    guard_nets = {"BAT": n_bat, "VSS": neg, "V-": n_vm, "COUT": n_cout, "DOUT": n_dout}
    d.add(p2, guard["symbol"], guard["value"], guard["footprint"], sch_at=(sx + 76.2, sy + 2.54),
          pcb_at=(px + 17.0, py + 6.0), nets={gp[name]: net for name, net in guard_nets.items()})  # fmt: skip
    two(refs["filter"], "Device:R", pairs["filter_ohms"][0], (60.96, -7.62), (17.0, 1.0), bat, n_bat)
    two(refs["bat"], "Device:C", c_bat[0], (99.06, 2.54), (21.0, 3.0), n_bat, neg)
    two(refs["sense"], "Device:R", pairs["sense_ohms"][0], (60.96, 20.32), (13.0, 6.0), n_vm, gnd)
    for ref, gate_net, source_net, k in ((refs["dsg"], n_dout, neg, 0), (refs["chg"], n_cout, gnd, 1)):
        ends = {"G": gate_net, "S": source_net, "D": n_mid}
        pins = {n: net for end, net in ends.items() for n in fp[end]}
        fx, fy = px + 13.0 + 7.0 * k, py + 11.0
        d.add(ref, rated[fet.mpn]["symbol"], fet.value, fet.footprint,
              sch_at=(sx + 76.2 + 15.24 * k, sy + 25.4), pcb_at=(fx, fy), nets=pins)  # fmt: skip
        for end, net in (("D", n_mid), ("S", source_net)):
            (x1, y1), (x2, y2) = rated[fet.mpn].get("links", {}).get(end, ((0, 0), (0, 0)))
            if (x1, y1) != (x2, y2):
                d.track(net, [(fx + x1, fy + y1), (fx + x2, fy + y2)])

    rows = blocks.rows_of(
        [
            (blocks.Stock(chip["maker"], ic, chip["value"], chip["footprint"]), 1),
            (iset[0], 1),
            (ts[0], 1),
            (c_in[0], 1),
            (c_out[0], 1),
            (blocks.Stock(guard["maker"], protector, guard["value"], guard["footprint"]), 1),
            (pairs["filter_ohms"][0], 1),
            (c_bat[0], 1),
            (pairs["sense_ohms"][0], 1),
            (fet, 2),
        ]
    )
    call = f"charger(vin=({_g(vin_low)}, {_g(vin_high)}), cell=Cell(volts=({_g(cell_low)}, {_g(cell_high)})))"
    drop = ratings.si(ocd_high, "V")
    entries = {
        "nets": {
            vin_net: {
                "volts": [vin_low, vin_high],
                "source": f"the input range of the charger block {u}: {call}",
            },
            bat: {
                "volts": [cell_low, cell_high],
                "source": f"the cell of the charger block {u}: {call}; {cell.source}",
            },
            neg: {
                "volts": [-ocd_high, ocd_high],
                "source": f"the cell's negative, 2 transistors from {gnd}: under {drop}, or {p2} opens them "
                f"[{at(guard, 'ocd_tolerance')}]",
            },
            n_mid: {
                "volts": [-ocd_high, ocd_high],
                "source": f"between the 2 transistors, {gnd} and {neg}: under {drop}, or {p2} opens them "
                f"[{at(guard, 'ocd_tolerance')}]",
            },
        }
    }
    files = charger_deck(
        u, ic, refs["iset"], ohms, k_max, vin_high, vbat, icc, cell, hot, theta, limit, chip, short, sums,
        pack, iset[1].data["tolerance"], iset[1].source, ambient,
    )  # fmt: skip
    return blocks.Block("charger", sums, entries, rows, files)


def charger_deck(  # noqa: PLR0913
    u,
    ic,
    r_ref,
    ohms,
    k_max,
    vin,
    vbat,
    icc,
    cell,
    hot,
    theta,
    limit,
    chip,
    short,
    sums,
    pack,
    tol,
    r_source,
    ambient,
):
    """sim/charger.cir: the charger at the greatest input and the least cell voltage, its current
    KISET's greatest over RISET (equation 1), its power what IN gives less what OUT gives (equation 8).
    The bounds: the cell's charge current and the power that keeps the junction at its limit at the
    greatest ambient. sim/thermal.json hands the power to the SIM gate's junction check."""
    most_w = (limit - hot) / theta
    lines = [
        f"charger: the charger block {u} ({ic}), written by tools/blocks_charger.py",
        f"* IN is the greatest input, {_g(vin)} V; the cell is a source at {_g(vbat)} V, the least it",
        f"* charges from at the full current. {u} gives KISET's greatest, {k_max} AΩ, over {r_ref}",
        f"* [{short}, equation 1, page 13; {chip['kiset']['where']}]:",
        f"* VSET puts 1 V on {r_ref} and BU1 gives {k_max} times its",
        "* current; the 1 V is the deck's own, not the IC's. IU1 is the supply's own current "
        f"[{chip['icc']['where']}].",
        f"* p_u1 is what IN gives less what OUT gives [{short}, equation 8, page 23].",
        "* The sums:",
        *[f"*   {line}" for line in sums],
        ".options tnom=25 temp=25",
        f"VIN in 0 DC {_g(vin)}",
        "VSET iset 0 DC 1",
        f"{r_ref} iset 0 {_g(ohms)}",
        f"BU1 in out I=-{k_max}*i(vset)",
        f"IU1 in 0 DC {_g(icc * 1000)}m",
        f"VBAT out 0 DC {_g(vbat)}",
        ".control",
        "op",
        "let ichg = i(vbat)",
        "let p_u1 = -v(in) * i(vin) - v(out) * i(vbat)",
        "print ichg p_u1",
        ".endc",
        ".end",
    ]
    expect = {
        "ichg": {"max": cell.charge_amps, "source": f"the cell's greatest charge current [{cell.source}]"},
        "p_u1": {
            "max": round(most_w, 6),
            "source": f"({_g(limit)} C - {_g(hot)} C) / {_g(theta)} C/W: the power that keeps {u}'s junction "
            f"at {_g(limit)} C at the greatest ambient [{chip['junction']['where']}; "
            f"{chip['theta_ja']['where']}]",
        },
    }
    corners = {
        "temperature": {
            "values": list(ambient),
            "source": "the design's ambient, the charger block's `ambient`",
        },
        "tolerance": {"R": tol, "source": f"{r_ref} from {r_source}"},
    }
    thermal = {
        "pack": pack,
        "parts": {
            u: {"mpn": ic, "watts": "charger.p_u1", "source": "the deck's input power less its output power"}
        },
    }
    return {
        "sim/charger.cir": "\n".join(lines) + "\n",
        "sim/charger.expect.json": json.dumps(expect, indent=2) + "\n",
        "sim/corners.json": json.dumps(corners, indent=2) + "\n",
        "sim/thermal.json": json.dumps(thermal, indent=2) + "\n",
    }
