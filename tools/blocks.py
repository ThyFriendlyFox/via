"""blocks — circuit blocks a design file adds in 1 call, each written from the note its maker publishes.

A block takes what a designer knows of the circuit (the input range, the output voltage, the load current),
the IC, and the parts the designer stocks. It works out each part's value by the equations of the note it
names, takes each part from the stock, and adds the parts to a kicadgen Design. What it worked out comes
back as lines that name the equation and the page; what `workcenter ratings` needs to judge the parts comes
back as `ratings.json` entries and `parts.csv` rows; its deck and its bound come back as files.

The numbers of each note and of each IC's datasheet stand in `rules/blocks/<block>.json`, each with its
clause and page. A part's own ratings (an inductor's saturation, a capacitor's kept value, an IC's
reference and its operating range) are read from `library/facts/`, the same entries `workcenter ratings`
reads. A block holds what its note states and no more: a part the note does not cover is the designer's
own, and `workcenter ratings` judges it.

Standard library only, as kicadgen is.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import ratings

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "rules" / "blocks"
HEADER = "Value,Footprint,Qty,Manufacturer,MPN,Supplier,SKU,Pack,Breaks"


class Refused(ValueError):
    """A block that cannot be built as asked: 1 line with what, the value, the limit and the source."""


@dataclass(frozen=True)
class Stock:
    """A part the designer can buy: its maker, its number, the Value the schematic shows, its footprint."""

    maker: str
    mpn: str
    value: str
    footprint: str


@dataclass
class Row:
    """A line of parts.csv."""

    value: str
    footprint: str
    qty: int
    maker: str
    mpn: str


@dataclass
class Block:
    name: str
    sums: list[str]  # each value worked out, with the equation and the page
    ratings: dict  # entries of ratings.json: {"nets": {...}}
    rows: list[Row]
    files: dict[str, str] = field(default_factory=dict)  # path beside the project -> text


def load_rules(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _facts(found: list[ratings.Facts], stock: Stock, symbol: str = "") -> ratings.Facts | None:
    part = SimpleNamespace(ref=stock.mpn, symbol=symbol, footprint=stock.footprint)
    return ratings.facts_of(found, part, stock.mpn)


def _where(ic: dict, key: str) -> str:
    return f"{ic['source']['document']}, {ic[key]['where']}"


def _g(x: float) -> str:
    """A number as the sums print it: 4 significant digits."""
    return f"{x:.4g}"


def rows_of(parts: list[tuple[Stock, int]]) -> list[Row]:
    """Rows of parts.csv, 1 for each Value and footprint, in the order the parts came."""
    out: dict[tuple[str, str], Row] = {}
    for stock, qty in parts:
        key = (stock.value, stock.footprint)
        if key in out:
            out[key].qty += qty
        else:
            out[key] = Row(stock.value, stock.footprint, qty, stock.maker, stock.mpn)
    return list(out.values())


def parts_csv(rows: list[Row]) -> str:
    """parts.csv as `workcenter ratings`, `sources` and `procure` read it."""

    def cell(text: str) -> str:
        return f'"{text}"' if "," in text or '"' in text else text

    lines = [HEADER] + [
        ",".join([cell(r.value), cell(r.footprint), str(r.qty), cell(r.maker), cell(r.mpn), "", "", "", ""])
        for r in rows
    ]
    return "\n".join(lines) + "\n"


def ratings_json(pack: str, *entries: dict) -> str:
    """ratings.json from a pack and the entries of each block and of the design's own."""
    merged: dict = {"pack": pack}
    for entry in entries:
        for key, value in entry.items():
            merged.setdefault(key, {}).update(value)
    return json.dumps(merged, indent=2) + "\n"


# What buck reads of an IC's entry in its rules: its own names, and each number with its `where`. `vout_set`
# and `dropout` name an equation and hold no number.
BUCK_NAMES = ("maker", "value", "symbol", "footprint", "pins", "source")
BUCK_NUMBERS = (
    "amps_max", "vout_min", "vout_set", "ilim_min", "henries", "henries_low", "saturation_margin", "r2",
    "output_farads", "kept_share", "output_span", "dielectrics", "input_farads", "rds_on_high", "dropout",
)  # fmt: skip


def _unentered(chip: dict) -> list[str]:
    """The keys buck reads that the IC's entry lacks, or holds with no number or no `where`."""
    out = [key for key in BUCK_NAMES if key not in chip]
    for key in BUCK_NUMBERS:
        entry = chip.get(key)
        held = isinstance(entry, dict) and "where" in entry
        if not held or (key not in ("vout_set", "dropout") and "value" not in entry and "rows" not in entry):
            out.append(key)
    return out


def buck(  # noqa: PLR0913, PLR0915
    d,
    *,
    ic: str,
    vin: tuple[float, float],
    vout: float,
    amps: float,
    nets: tuple[str, str, str],
    stock: list[Stock],
    facts: Path,
    sch_at: tuple[float, float],
    pcb_at: tuple[float, float],
    refs: dict[str, str] | None = None,
    rules: Path = RULES / "buck.json",
) -> Block:
    """A synchronous buck regulator from `nets` = (input, output, ground): the IC, its inductor, its
    feedback divider, its input capacitor and its output capacitors, by TI SLVA477C."""
    refs = {
        "ic": "U1",
        "inductor": "L1",
        "top": "R1",
        "bottom": "R2",
        "input": "C1",
        "output": "C2 C3 C4",
    } | (refs or {})
    u = refs["ic"]
    for name, given in (("vin", vin), ("vout", vout), ("amps", amps)):
        if not all(
            isinstance(x, (int, float)) and math.isfinite(x) for x in (given if name == "vin" else (given,))
        ):
            raise Refused(f"buck {u}: {name}={given!r}: each number of the spec must be finite")
    data = load_rules(rules)
    note = data["note"]
    short = note["short"]

    def eq(n: str) -> str:
        return f"{short}, equation {n}, page {note['equations'][n]['page']}"

    vin_low, vin_high = vin
    if vin_low > vin_high:
        raise Refused(
            f"buck {u}: vin=({_g(vin_low)}, {_g(vin_high)}) is written greatest first: "
            f"vin is (least, greatest), and the block sizes its parts at the greatest [{eq('1')}]"
        )
    chip = next((c for c in data["ics"] if c["mpn"] == ic), None)
    if chip is None:
        names = ", ".join(c["mpn"] for c in data["ics"])
        raise Refused(f"buck {u}: {ic} is no IC of {Path(rules).name}; it holds {names}")
    if missing := _unentered(chip):
        raise Refused(
            f"buck {u}: {Path(rules).name} gives {ic} no {', '.join(missing)}: the block builds no IC whose "
            "numbers are not all entered"
        )
    found = ratings.read_facts(Path(facts))
    chip_facts = _facts(found, Stock("", ic, "", chip["footprint"]), chip["symbol"])
    if chip_facts is None:
        raise Refused(f"buck {u}: {facts} holds no facts of {ic}")
    pins = {p["name"]: p for p in chip_facts.data["pins"]}
    for what, held in (
        ("switching hertz", chip_facts.data.get("switching", {}).get("hertz")),
        ("FB volts", pins.get("FB", {}).get("volts")),
        ("VIN operating", pins.get("VIN", {}).get("operating")),
    ):
        if held is None:
            raise Refused(f"buck {u}: the facts of {ic} give no {what} [{chip_facts.where}]")
    source = f"{chip_facts.source}, {ratings._p(pins['VIN']['page'])}"
    low, high = pins["VIN"]["operating"]
    if vin_high > high or vin_low < low:
        reach = vin_high if vin_high > high else vin_low
        raise Refused(
            f"buck {u}: the input reaches {ratings.si(reach, 'V')}, VIN of {ic} operates from "
            f"{ratings.si(low, 'V')} to {ratings.si(high, 'V')} [{source}]"
        )
    if amps <= 0:
        raise Refused(
            f"buck {u}: a load of {ratings.si(amps, 'A')}: the block sizes its parts and its deck's load, "
            f"VOUT / IOUT, for a load over 0 A [{_where(chip, 'amps_max')}]"
        )
    if amps > chip["amps_max"]["value"]:
        raise Refused(
            f"buck {u}: the load of {ratings.si(amps, 'A')} is over {ic}'s "
            f"{ratings.si(chip['amps_max']['value'], 'A')} [{_where(chip, 'amps_max')}]"
        )
    if vout < chip["vout_min"]["value"]:
        raise Refused(
            f"buck {u}: VOUT of {ratings.si(vout, 'V')} is under "
            f"{ratings.si(chip['vout_min']['value'], 'V')} [{_where(chip, 'vout_min')}]"
        )
    if vout > vin_low:
        raise Refused(
            f"buck {u}: VOUT of {ratings.si(vout, 'V')} is over the least input, {ratings.si(vin_low, 'V')} "
            f"[{_where(chip, 'vout_min')}]"
        )
    term = chip_facts.data["switching"]
    hertz = term["hertz"][0]
    eta = term.get("efficiency", note["efficiency"]["value"])
    sums = []
    duty = vout / (vin_high * eta)  # equation 1
    line = f"D = {_g(vout)} V / ({_g(vin_high)} V x {_g(eta)}) = {duty:.4f}"
    if duty > 1:
        raise Refused(
            f"buck {u}: {line}, over 1: the switch would be on for more than its period [{eq('1')}]"
        )
    sums.append(f"{u}: {line} [{eq('1')}]")

    # The inductor: the value the datasheet recommends (section 3), then the first in the stock whose
    # facts hold the peak of equation 4 with the datasheet's margin, and carry the load.
    henries = chip["henries"]["value"]
    coils = []
    for item in stock:
        f = _facts(found, item)
        if f is not None and f.kind == "inductor" and ratings.part_value(item.value) == henries:
            coils.append((item, f))
    if not coils:
        raise Refused(
            f"buck {u}: no stocked inductor of {ratings.si(henries, 'H')} with facts in {facts} "
            f"[{_where(chip, 'henries')}; {short}, {note['inductor_choice']}]"
        )
    margin = chip["saturation_margin"]["value"]
    pct = f"{margin * 100:g} %"
    peak_where = f"{eq('4')}, and {note['inductor_rule'].split(':')[0]}; {_where(chip, 'saturation_margin')}"

    def ripple_of(f: ratings.Facts) -> tuple[float, float, str]:
        """dIL of equation 2 at the least inductance: the part's tolerance or table 4's note 1, the larger."""
        low = max(f.data["tolerance"], chip["henries_low"]["value"])
        where = _where(chip, "henries_low") if low > f.data["tolerance"] else f.source
        least = henries * (1 - low)
        return least, (vin_high - vout) * duty / (hertz * least), f"less {low * 100:g} % [{where}]"

    taken = None
    missed = []
    for item, f in coils:
        least, ripple, low = ripple_of(f)
        peak = ripple / 2 + amps  # equation 4
        saturation = f.data["amps_saturation"]
        rms = f.data.get("amps_rms")
        if peak * (1 + margin) > saturation:
            missed.append(f"{item.mpn} saturates at {ratings.si(saturation, 'A')}")
        elif rms is not None and amps > rms:
            missed.append(f"{item.mpn} is rated {ratings.si(rms, 'A')} rms")
        else:
            taken = (item, f, least, ripple, peak, low)
            break
    imax = chip["ilim_min"]["value"]
    if taken is None:
        _, ripple, _ = ripple_of(coils[0][1])
        peak = ripple / 2 + amps
        raise Refused(
            f"buck {u}: no stocked inductor holds the peak of {ratings.si(peak, 'A')} with {pct} of margin, "
            f"{ratings.si(peak * (1 + margin), 'A')} ({ratings.si(amps, 'A')} of load and half of "
            f"{ratings.si(ripple, 'A')} of ripple): {', '.join(missed)} [{peak_where}]"
        )
    item, f, least, ripple, peak, low = taken
    coil = refs["inductor"]
    sums.append(
        f"{coil}: dIL = ({_g(vin_high)} V - {_g(vout)} V) x {duty:.4f} / ({ratings.si(hertz, 'Hz')} x "
        f"{ratings.si(least, 'H')}) = {ratings.si(ripple, 'A')} [{eq('2')}]; "
        f"L is {ratings.si(henries, 'H')} {low}"
    )
    most = imax - ripple / 2  # equation 3
    if most < amps:
        raise Refused(
            f"buck {u}: IMAXOUT = {ratings.si(imax, 'A')} - {ratings.si(ripple, 'A')} / 2 = "
            f"{ratings.si(most, 'A')}, under the load of {ratings.si(amps, 'A')} "
            f"[{eq('3')}; {_where(chip, 'ilim_min')}]"
        )
    sums.append(
        f"{u}: IMAXOUT = {ratings.si(imax, 'A')} - {ratings.si(ripple, 'A')} / 2 = {ratings.si(most, 'A')}, "
        f"the load is {ratings.si(amps, 'A')} [{eq('3')}]"
    )
    rms = f.data.get("amps_rms")
    carries = (
        f" and is rated {ratings.si(rms, 'A')} rms"
        if rms is not None
        else "; its rms current is not judged: its facts give none"
    )
    sums.append(
        f"{coil}: ISW(max) = {ratings.si(ripple, 'A')} / 2 + {ratings.si(amps, 'A')} = "
        f"{ratings.si(peak, 'A')}, {ratings.si(peak * (1 + margin), 'A')} with {pct} of margin; {item.mpn} "
        f"saturates at {ratings.si(f.data['amps_saturation'], 'A')}{carries} [{peak_where}]"
    )
    inductor = item

    # The divider: R2 as the datasheet gives it, R1 by equation 11 from the reference's typical value.
    # The output it sets is held to the output asked: the asked must lie in the span the reference's
    # limits and the resistors' tolerances give (the datasheet's equation 2).
    vfb = pins["FB"]["volts"]
    reference = (vfb[0] + vfb[1]) / 2
    r2 = chip["r2"]["value"]
    resistors = [(s, rf) for s in stock if (rf := _facts(found, s)) is not None and rf.kind == "resistor"]
    bottom = next(((s, rf) for s, rf in resistors if ratings.part_value(s.value) == r2), None)
    if bottom is None:
        raise Refused(f"buck {u}: no stocked resistor of {ratings.si(r2, 'ohm')} [{_where(chip, 'r2')}]")
    r1 = r2 * (vout / reference - 1)  # equation 11
    top = min(resistors, key=lambda pair: abs(ratings.part_value(pair[0].value) - r1))
    r_top, t_top, t_bottom = (
        ratings.part_value(top[0].value),
        top[1].data["tolerance"],
        bottom[1].data["tolerance"],
    )
    vset = reference * (1 + r_top / r2)  # the datasheet's equation 2
    out_low = vfb[0] * (1 + r_top * (1 - t_top) / (r2 * (1 + t_bottom)))
    out_high = vfb[1] * (1 + r_top * (1 + t_top) / (r2 * (1 - t_bottom)))
    divider_where = f"{eq('11')}; {_where(chip, 'vout_set')}"
    span = (
        f"{ratings.si(out_low, 'V')} to {ratings.si(out_high, 'V')} with VFB of {ratings.si(vfb[0], 'V')} to "
        f"{ratings.si(vfb[1], 'V')} and the resistors' tolerances"
    )
    if not out_low <= vout <= out_high:
        raise Refused(
            f"buck {u}: R1 of {top[0].value} and R2 of {bottom[0].value} set VOUT to {_g(vset)} V, {span}, "
            f"and {_g(vout)} V is asked: no stocked resistor is near {ratings.si(r1, 'ohm')} "
            f"[{divider_where}]"
        )
    # The output the divider sets is held to the output asked within the reference's own accuracy: a
    # looser resistor widens the span above and would let a farther value pass.
    accuracy = (vfb[1] - vfb[0]) / (vfb[1] + vfb[0])
    off = (vset - vout) / vout
    if abs(off) > accuracy * (1 + ratings.EPS):
        side = "under" if off < 0 else "over"
        fb_where = f"{chip_facts.source}, {ratings._p(pins['FB']['page'])}"
        raise Refused(
            f"buck {u}: R1 of {top[0].value} and R2 of {bottom[0].value} set VOUT to {_g(vset)} V, "
            f"{abs(off) * 100:.2g} % {side} the {_g(vout)} V asked; the block holds it within "
            f"{accuracy * 100:.3g} %, the reference's own accuracy, VFB of {ratings.si(vfb[0], 'V')} to "
            f"{ratings.si(vfb[1], 'V')} [{fb_where}; {divider_where}]"
        )
    sums.append(
        f"{refs['top']}: R1 = {ratings.si(r2, 'ohm')} x ({_g(vout)} V / {_g(reference)} V - 1) = "
        f"{ratings.si(r1, 'ohm')}; the stock's nearest is {top[0].value}, which sets {_g(vset)} V, "
        f"and {span} [{divider_where}]"
    )

    # The least input that holds the output: the datasheet's equation 1 of 100 % duty cycle, at the top of
    # the output's span, with the high-side FET's resistance and the inductor's DCR.
    rds = chip["rds_on_high"]["value"]
    dcr = f.data.get("ohms_dc")
    dropout_where = f"{_where(chip, 'dropout')}; {_where(chip, 'rds_on_high')}"
    if dcr is None:
        vin_min = out_high + amps * rds
        line = f"VIN(MIN) = {ratings.si(out_high, 'V')} + {ratings.si(amps, 'A')} x "
        line += ratings.si(rds, "ohm")
        unjudged = f"; {coil}'s DCR is not judged: its facts give none"
    else:
        vin_min = out_high + amps * (rds + dcr)
        line = (
            f"VIN(MIN) = {ratings.si(out_high, 'V')} + {ratings.si(amps, 'A')} x ({ratings.si(rds, 'ohm')} + "
            f"{ratings.si(dcr, 'ohm')})"
        )
        unjudged = ""
        dropout_where += f"; {coil}'s DCR: {f.source}"
    line += f" = {ratings.si(vin_min, 'V')}"
    least = ratings.si(vin_low, "V")
    if vin_low < vin_min:
        raise Refused(
            f"buck {u}: {line}, over the least input, {least}: at {least} the IC cannot hold the output's "
            f"span [{dropout_where}]"
        )
    sums.append(f"{u}: {line}, and the least input is {least}{unjudged} [{dropout_where}]")

    caps = [
        (s, cf) for s in stock if (cf := _facts(found, s)) is not None and cf.kind.startswith("capacitor")
    ]
    names = refs["output"].split()
    out_cap, count, asked, needed, each = _output_caps(u, chip, caps, vset, out_high, names)
    outs = names[:count]
    lo, hi = chip["output_span"]["value"]
    farads = ratings.part_value(out_cap[0].value)
    sums.append(
        f"{', '.join(outs)}: {ratings.si(asked, 'F')} of output capacitance for {_g(vset)} V, "
        f"{ratings.si(needed, 'F')} effective; each, {out_cap[1].data['dielectric']}, keeps "
        f"{ratings.si(each, 'F')} at {ratings.si(out_high, 'V')}; {count} x {ratings.si(farads, 'F')} = "
        f"{ratings.si(count * farads, 'F')}, within {ratings.si(lo, 'F')} to {ratings.si(hi, 'F')} "
        f"[{_output_where(chip)}]"
    )
    in_cap, kept_in = _input_cap(u, chip, caps, vin_high)
    in_where = _input_where(chip)
    sums.append(
        f"{refs['input']}: {ratings.si(ratings.part_value(in_cap[0].value), 'F')} of input capacitance, "
        f"{in_cap[1].data['dielectric']}, {kept_in}; {ratings.si(chip['input_farads']['value'], 'F')} asked "
        f"[{in_where}]"
    )

    # The parts, placed from the block's corner on the sheet and on the board.
    vin_net, vout_net, gnd = nets
    sw, fb = f"{u}_SW", f"{u}_FB"
    sx, sy = sch_at
    px, py = pcb_at
    p = chip["pins"]
    value = chip["value"]
    d.add(u, chip["symbol"], value, chip["footprint"], sch_at=(sx + 25.4, sy), pcb_at=(px + 6.0, py + 2.0),
          nets={p["VIN"]: vin_net, p["EN"]: vin_net, p["GND"]: gnd, p["SW"]: sw, p["FB"]: fb})  # fmt: skip
    d.add(coil, "Device:L", inductor.value, inductor.footprint, sch_at=(sx + 50.8, sy - 7.62),
          pcb_at=(px + 13.0, py), nets={"1": sw, "2": vout_net})  # fmt: skip
    d.add(refs["top"], "Device:R", top[0].value, top[0].footprint, sch_at=(sx + 66.04, sy),
          pcb_at=(px + 6.0, py - 3.0), nets={"1": vout_net, "2": fb})  # fmt: skip
    d.add(refs["bottom"], "Device:R", bottom[0].value, bottom[0].footprint, sch_at=(sx + 66.04, sy + 15.24),
          pcb_at=(px + 9.0, py - 3.0), nets={"1": fb, "2": gnd})  # fmt: skip
    d.add(refs["input"], "Device:C", in_cap[0].value, in_cap[0].footprint, sch_at=(sx, sy + 7.62),
          pcb_at=(px + 1.0, py + 6.0), nets={"1": vin_net, "2": gnd})  # fmt: skip
    for k, ref in enumerate(outs):
        d.add(ref, "Device:C", out_cap[0].value, out_cap[0].footprint,
              sch_at=(sx + 83.82 + 12.7 * k, sy + 7.62), pcb_at=(px + 22.0, py + 3.0 * k),
              nets={"1": vout_net, "2": gnd})  # fmt: skip

    chip_stock = Stock(chip["maker"], ic, value, chip["footprint"])
    rows = rows_of(
        [(chip_stock, 1), (inductor, 1), (top[0], 1), (bottom[0], 1), (in_cap[0], 1), (out_cap[0], count)]
    )
    entries = {
        "nets": {
            vin_net: {
                "volts": [vin_low, vin_high],
                "source": f"the input range of the buck block {u}: buck(vin=({_g(vin_low)}, {_g(vin_high)}))",
            }
        }
    }
    files = buck_deck(
        u, ic, vin_high, vout, amps, hertz, inductor, coil, f, outs, *out_cap, chip_facts, short, sums
    )
    return Block("buck", sums, entries, rows, files)


def _lacks(s: Stock, cf: ratings.Facts) -> str | None:
    """What a capacitor's facts lack that a block counts it by: its rating and its tolerance."""
    lack = [key for key in ("volts", "tolerance") if key not in cf.data]
    return f"{s.mpn}: its facts give no {' and no '.join(lack)}" if lack else None


def _input_where(chip: dict) -> str:
    return f"{_where(chip, 'input_farads')}; {chip['dielectrics']['where']}"


def _input_cap(u, chip, caps, vin_high):
    """The input capacitor: the first stocked capacitor rated for the greatest input, of a dielectric the
    datasheet names, that holds the datasheet's input capacitance less its tolerance and, when its facts
    give it, at the value it keeps at the greatest input (TI SLVA477C section 6, page 5: the input
    capacitor loses much of its capacitance to DC bias). Returns it and the words of its sum."""
    least = chip["input_farads"]["value"]
    good = chip["dielectrics"]["value"]
    missed = []
    for s, cf in caps:
        data = cf.data
        if lacks := _lacks(s, cf):
            missed.append(lacks)
            continue
        if data["volts"] < vin_high:
            missed.append(
                f"{s.mpn}: rated {ratings.si(data['volts'], 'V')}, under {ratings.si(vin_high, 'V')}"
            )
            continue
        if data.get("dielectric") not in good:
            missed.append(f"{s.mpn}: {data.get('dielectric', 'no dielectric')}, not {' or '.join(good)}")
            continue
        farads = ratings.part_value(s.value)
        written = farads * (1 - data["tolerance"])
        less = f"{ratings.si(farads, 'F')} less {data['tolerance'] * 100:g} %"
        if "kept" in data:
            share = ratings.kept_at(data["kept"], vin_high)
            if share is None:
                missed.append(f"{s.mpn}: its kept value ends under {ratings.si(vin_high, 'V')}")
                continue
            each = written * share
            if each < least * (1 - ratings.EPS):
                missed.append(
                    f"{s.mpn}: {less} keeps {ratings.si(each, 'F')} at {ratings.si(vin_high, 'V')}, under "
                    f"{ratings.si(least, 'F')}"
                )
                continue
            return (s, cf), f"keeps {ratings.si(each, 'F')} at {ratings.si(vin_high, 'V')} less its tolerance"
        if written < least * (1 - ratings.EPS):
            missed.append(f"{s.mpn}: {less} is {ratings.si(written, 'F')}, under {ratings.si(least, 'F')}")
            continue
        return (s, cf), (
            f"{ratings.si(written, 'F')} less its tolerance; its value under {ratings.si(vin_high, 'V')} "
            "is not judged: its facts give none"
        )
    raise Refused(
        f"buck {u}: no stocked capacitor gives {ratings.si(least, 'F')} of input capacitance at "
        f"{ratings.si(vin_high, 'V')}: {'; '.join(missed) or 'the stock holds none with facts'} "
        f"[{_input_where(chip)}]"
    )


def _output_where(chip: dict) -> str:
    span, dielectrics = chip["output_span"]["where"], chip["dielectrics"]["where"]
    return f"{_where(chip, 'output_farads')}; note 2; {span}; {dielectrics}"


def _output_caps(u, chip, caps, vset, out_high, names):  # noqa: PLR0913
    """The output capacitors: table 4's value for the output the divider sets, of which its note keeps a
    share, counted on each capacitor's kept value at the output's highest voltage. The first stocked
    capacitor that is rated over that voltage, of a dielectric the datasheet names, and whose count fits
    the refs and the datasheet's span of output capacitance is taken."""
    table = chip["output_farads"]["rows"]
    asked = next((c for lo, hi, c in table if vset >= lo and (hi is None or vset < hi)), None)
    if asked is None:
        raise Refused(f"buck {u}: table 4 has no row for {_g(vset)} V [{_where(chip, 'output_farads')}]")
    needed = asked * chip["kept_share"]["value"]
    lo, hi = chip["output_span"]["value"]
    good = chip["dielectrics"]["value"]
    missed = []
    for s, cf in caps:
        farads = ratings.part_value(s.value)
        if lacks := _lacks(s, cf):
            missed.append(lacks)
            continue
        share = ratings.kept_at(cf.data["kept"], out_high) if "kept" in cf.data else None
        if "kept" not in cf.data:
            missed.append(f"{s.mpn}: its facts give no value it keeps under voltage")
        elif cf.data["volts"] <= out_high:
            missed.append(
                f"{s.mpn}: rated {ratings.si(cf.data['volts'], 'V')}, not over {ratings.si(out_high, 'V')}"
            )
        elif cf.data.get("dielectric") not in good:
            missed.append(f"{s.mpn}: {cf.data.get('dielectric', 'no dielectric')}, not {' or '.join(good)}")
        elif share is None:
            missed.append(f"{s.mpn}: its kept value ends under {ratings.si(out_high, 'V')}")
        else:
            each = farads * (1 - cf.data["tolerance"]) * share
            count = math.ceil(needed / each)
            total = f"{count} x {ratings.si(farads, 'F')} = {ratings.si(count * farads, 'F')}"
            if count > len(names):
                missed.append(f"{s.mpn}: {count} are asked and refs['output'] names {len(names)}")
            elif count * farads > hi * (1 + ratings.EPS):  # part_value("10u") is 9.999999999999999e-06
                missed.append(f"{s.mpn}: {total}, over {ratings.si(hi, 'F')}")
            elif count * farads < lo * (1 - ratings.EPS):
                missed.append(f"{s.mpn}: {total}, under {ratings.si(lo, 'F')}")
            else:
                return (s, cf), count, asked, needed, each
    raise Refused(
        f"buck {u}: no stocked capacitor gives {ratings.si(asked, 'F')} of output capacitance for "
        f"{_g(vset)} V: {'; '.join(missed)} [{_output_where(chip)}]"
    )


def buck_deck(  # noqa: PLR0913
    u, ic, vin, vout, amps, hertz, coil_part, coil, coil_facts, outs, cap, cap_facts, chip_facts, short, sums
):
    """sim/buck.cir and its bound: the power stage at the greatest input and the least frequency, its
    parts at their written values. It runs 1 ms from rest and measures the last 10 us, when the start
    has died away: the SIM gate drops a starting voltage from a part it runs on its maker's data. The
    bound is the inductor's saturation."""
    period = 1 / hertz
    duty = vout / vin  # a lossless stage: the deck has no loss to make up
    on = duty * period
    henries = ratings.part_value(coil_part.value)
    farads = ratings.part_value(cap.value)
    load = vout / amps
    lines = [
        f"buck: the power stage of the buck block {u} ({ic}), written by tools/blocks.py",
        f"* The switch is an ideal source at {ic}'s least frequency, {ratings.si(hertz, 'Hz')} "
        f"[{chip_facts.source}], from the greatest input, {_g(vin)} V.",
        f"* Its duty is a lossless stage's, {_g(vout)} / {_g(vin)}: {_g(on * 1e9)} ns of "
        f"{_g(period * 1e9)} ns. {coil} and {', '.join(outs)} are the board's parts.",
        f"* The load is {_g(vout)} V / {ratings.si(amps, 'A')} = {_g(load)} ohm. The deck runs 1 ms from "
        "rest and measures the last 10 us, after the start has died away.",
        f"* The bound is {coil}'s saturation current [{coil_facts.source}]; {short} section 3 asks the "
        "inductor to carry the peak.",
        "* The sums:",
        *[f"*   {line}" for line in sums],
        f"VSW sw 0 PULSE(0 {_g(vin)} 0 1n 1n {_g(on * 1e9)}n {_g(period * 1e9)}n)",
        f"{coil} sw out {_g(henries * 1e6)}u",
        *[f"{ref} out 0 {_g(farads * 1e6)}u" for ref in outs],
        f"RLOAD out 0 {_g(load)}",
        ".control",
        "tran 2n 1m",
        f"meas tran ipeak max i({coil.lower()}) from=990u to=1m",
        "print ipeak",
        ".endc",
        ".end",
    ]
    expect = {
        "ipeak": {
            "max": coil_facts.data["amps_saturation"],
            "source": f"{coil} {coil_part.mpn} saturates at "
            f"{ratings.si(coil_facts.data['amps_saturation'], 'A')} [{coil_facts.source}]",
        }
    }
    corners = {
        "tolerance": {
            "L": coil_facts.data["tolerance"],
            "C": cap_facts.data["tolerance"],
            "source": f"{coil} from {coil_facts.source}; {', '.join(outs)} from {cap_facts.source}",
        }
    }
    return {
        "sim/buck.cir": "\n".join(lines) + "\n",
        "sim/buck.expect.json": json.dumps(expect, indent=2) + "\n",
        "sim/corners.json": json.dumps(corners, indent=2) + "\n",
    }


# The other blocks stand in their own modules, which import this one: each is joined here, at the end.
from blocks_i2c import i2c  # noqa: E402, F401
