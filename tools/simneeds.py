#!/usr/bin/env python3
"""simneeds — the decks a board's schematic asks for, and the decks that answer them.

An engineer asks 2 questions of a board before it is called done, whatever its spec says: does each
I2C line rise in time with its pull-up and its bus capacitance, and does each regulator hold its rail
when its load steps. The SIM gate asks them too. It reads the schematic's netlist and names each
circuit that has no deck:

    i2c-rise    a net named SDA or SCL (a word of the net's name, or of a pin's name on it, with digits
                after it or not: I2C1_SDA, PB1/SDA, SCL2) that a resistor holds to a rail
    load-step   a part of KiCad's Regulator_Linear or Regulator_Switching library, on a board whose
                ratings.json states a load: a part or a pin under `parts` with `amps` above 0

A deck answers a need by a comment line: `* deck: i2c-rise SDA SCL` names the lines it stands for,
`* deck: load-step U1` the regulator. The line is checked against the schematic: an I2C deck runs each
pull-up of the lines it names by its reference (`R1 vdd sda 4.7k`) at the schematic's value, or a
pull-up of the same value stands for it; a load-step deck runs the regulator it names (`XU1 ...`). A
deck that does not is a failure. templates/project/sim/ holds a deck of each kind with its bounds and
their sources. What is not recognized: a line with no pull-up on this board, a bus by any other name, a
regulator drawn with a symbol of another library, and a load stated anywhere but ratings.json. A
resistor of more than 2 pins (an array, a network) on an I2C line is not read: it is named as not
judged.

Standard library only. `tools/workcenter` exports the netlist and reads it with `ratings.read_netlist`.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from ratings import part_value
from simcorners import spice_number

# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {"nxp-um10204": "Rev. 7.0, table 11, page 44: the rise time an I2C line is held to"}
KINDS = {"i2c-rise": "i2c_rise", "load-step": "load_step"}  # a need's kind -> its template's name
REGULATOR_LIBS = ("Regulator_Linear", "Regulator_Switching")
I2C_WORD_RE = re.compile(r"(?:SDA|SCL)\d*")
# Ground, a net's name or a power pin's: a resistor to it pulls down. VEE is a negative supply.
GROUND_RE = re.compile(r"(?:GND|VSS|VEE|AGND|DGND|PGND)\w*|0V|COM", re.I)
RAIL_RE = re.compile(r"\+.*|(?:VCC|VDD|VIO|VBUS|VBAT|VIN|VOUT|\d+V\d*)\w*", re.I)
MARK_RE = re.compile(r"^\*\s*deck:\s*(\S+)(.*)$", re.I)
# A resistor by its symbol (KiCad's Device:R, R_Small, R_US, R_Pack04, ...) or by its reference (R7).
RESISTOR_SYMBOL_RE = re.compile(r"Device:R(?:_\w+)?")
RESISTOR_REF_RE = re.compile(r"R\d+")
# A resistor array or network: KiCad's Device:R_Pack04, R_Network08, R_Array_...; read by no rule here.
ARRAY_SYMBOL_RE = re.compile(r"Device:R_(?:Pack|Network|Array)\w*")
ARRAY_REF_RE = re.compile(r"RN\d+")
ELEMENT_RE = re.compile(r"^([A-Za-z]\w*)\s+\S+\s+\S+\s+(\S+)")  # a 2-node element: name, nodes, value
SHEETFILE_RE = re.compile(r'\(property\s+"Sheetfile"\s+"((?:[^"\\]|\\.)*)"')
# The text a schematic must hold before its netlist is worth exporting: a word SDA or SCL, or a
# regulator's library. Every other board costs the SIM gate no kicad-cli run.
WORTH_RE = re.compile(r"(?<![A-Za-z0-9])(?:SDA|SCL)\d*(?![A-Za-z])|Regulator_(?:Linear|Switching):")
UM10204 = "UM10204 Rev. 7.0, Table 11, page 44"


@dataclass(frozen=True)
class Need:
    """1 circuit the schematic holds and no deck answers."""

    kind: str  # a key of KINDS
    names: tuple[str, ...]  # the nets of an I2C bus; the reference of a regulator
    line: str  # the gate's line: what, where, the value and the source
    failed: bool = False  # a deck that answers it and does not run the board's part: a failure


def words(text: str) -> list[str]:
    """The words of a name, in upper case: `PB1/SDA` -> PB1, SDA; `I2C_SCL` -> I2C, SCL."""
    return [w for w in re.split(r"[^A-Za-z0-9]+", text.upper()) if w]


def is_i2c(name: str, pin_names: list[str]) -> bool:
    """Whether a net is an I2C line: SDA or SCL is a word of its name or of a pin's name on it."""
    return any(I2C_WORD_RE.fullmatch(w) for text in [name, *pin_names] for w in words(text))


def is_rail(name: str, nodes: list) -> bool:
    """Whether a net is a supply rail: its name is a rail's (+3V3, VCC, VDD_IO, 3V3, /power/+3V3), or a
    power pin stands on it whose name is no ground's. Ground is no rail: a net named GND, VSS, VEE, 0V
    or COM, or one whose power pins are all ground pins (an IC's GND is a power_in pin). A resistor to
    ground pulls down. `nodes` are the net's ratings.Node."""
    bare = name.rsplit("/", 1)[-1]
    if GROUND_RE.fullmatch(bare):
        return False
    power = [n.name for n in nodes if n.kind in ("power_in", "power_out")]
    return bool(RAIL_RE.fullmatch(bare)) or any(not GROUND_RE.fullmatch(p.rsplit("/", 1)[-1]) for p in power)


def worth_reading(texts: list[str]) -> bool:
    """Whether a schematic's text can hold a need: its netlist is exported only then."""
    return any(WORTH_RE.search(t) for t in texts)


def schematic_texts(root: Path) -> tuple[list[str], list[str]]:
    """The text of the root sheet and of every sheet it names, by each sheet's Sheetfile (a path from
    the sheet that names it, in a subfolder or not), each read once. The second list names the sheets
    named and not read: what they hold is not known."""
    texts: list[str] = []
    unread: list[str] = []
    seen: set[Path] = set()
    todo = [root]
    while todo:
        sheet = todo.pop(0)
        key = sheet.resolve()
        if key in seen:
            continue
        seen.add(key)
        try:
            text = sheet.read_text(encoding="utf-8", errors="replace")
        except OSError:
            unread.append(str(sheet))
            continue
        texts.append(text)
        named = [m.group(1).replace('\\"', '"') for m in SHEETFILE_RE.finditer(text)]
        todo += [Path(os.path.normpath(sheet.parent / name)) for name in named]
    return texts, unread


def markers(decks: dict[str, str]) -> list[tuple[str, str, list[str]]]:
    """Each `* deck: <kind> <names>` line of `decks`, as (deck, kind, names), the kind in lower case and
    the names split at spaces and commas. A kind the module does not know is left out."""
    out = []
    for stem, text in decks.items():
        for raw in text.splitlines():
            m = MARK_RE.match(raw.strip())
            if m and m.group(1).lower() in KINDS:
                out.append((stem, m.group(1).lower(), [n for n in re.split(r"[\s,]+", m.group(2)) if n]))
    return out


def answered(decks: dict[str, str]) -> dict[str, set[str]]:
    """What the decks say they answer, by kind: the names each `* deck: <kind> <names>` line gives."""
    out: dict[str, set[str]] = {kind: set() for kind in KINDS}
    for _, kind, names in markers(decks):
        out[kind].update(names)
    return out


def elements(text: str) -> dict[str, str]:
    """A deck's 2-node elements, by name in upper case: {`R1`: `4.7k`}. Comments and dot lines are not."""
    out = {}
    for raw in text.splitlines():
        m = ELEMENT_RE.match(raw.strip())
        if m:
            out[m.group(1).upper()] = m.group(2)
    return out


def instances(text: str) -> set[str]:
    """The names of a deck's element lines, in upper case: R1, XU1, VIN."""
    return {m.group(1).upper() for m in re.finditer(r"^\s*([A-Za-z]\w*)\s", text, re.M)}


def same(a: float, b: float) -> bool:
    """2 values a deck and a schematic write: the same to 1 part in a million."""
    return abs(a - b) <= 1e-6 * max(abs(a), abs(b))


def deck_checks(stem: str, names: list[str], pulled: dict[str, list], text: str) -> list[Need]:
    """What 1 `* deck: i2c-rise <names>` deck gets wrong against the schematic's pull-ups (`pulled`, an
    I2C net -> its 2-pin pull-ups as ratings.Part). Each pull-up of a line it names runs in the deck by
    its reference at the schematic's value, or one of the same value runs and stands for it."""
    ups = [(net, part) for net in names for part in pulled.get(net, [])]
    if not ups:
        return []
    deck = elements(text)
    marker = f"`* deck: i2c-rise {' '.join(names)}`"
    run = [(net, p) for net, p in ups if p.ref.upper() in deck]
    if not run:
        refs = ", ".join(f"{p.ref} ({p.value})" for _, p in ups)
        line = (
            f"{stem}.cir: says {marker} and has no line for {refs}: name each pull-up as the schematic "
            "does, with its value"
        )
        return [Need("i2c-rise", tuple(names), line, failed=True)]
    out: list[Need] = []
    held: list[float] = []  # the schematic's values the deck runs
    for net, p in run:
        written, ohms = deck[p.ref.upper()], part_value(p.value)
        value = spice_number(written)
        if value is None or ohms is None:
            out.append(
                Need(
                    "i2c-rise",
                    (net,),
                    f"not judged: {stem}.cir: {p.ref} is {written} in the deck and {p.value} in the "
                    f"schematic, on {net}: the gate reads no number from one of them, so the deck's "
                    "pull-up is not compared with the board's",
                )
            )
        elif not same(value, ohms):
            out.append(
                Need(
                    "i2c-rise",
                    (net,),
                    f"{stem}.cir: {p.ref} is {written} in the deck and {p.value} in the schematic, on {net}: "
                    "the deck does not run the board's pull-up; write the schematic's value",
                    failed=True,
                )
            )
        else:
            held.append(ohms)
    for net, p in ups:
        if p.ref.upper() in deck:
            continue
        ohms = part_value(p.value)
        if ohms is None:
            out.append(
                Need(
                    "i2c-rise",
                    (net,),
                    f"not judged: {stem}.cir: {p.ref} ({p.value}) on {net} has no line in the deck, and the "
                    "gate reads no number from its value to say whether a pull-up the deck runs stands "
                    "for it",
                )
            )
        elif not any(same(ohms, h) for h in held):
            out.append(
                Need(
                    "i2c-rise",
                    (net,),
                    f"{stem}.cir: {p.ref} ({p.value}) on {net} has no line in the deck, and no pull-up the "
                    "deck runs has its value: name it as the schematic does, with its value",
                    failed=True,
                )
            )
    return out


def stated_loads(ratings: Path) -> list[str]:
    """The loads a ratings.json states, as `J2.1 0.1 A`: each part or pin under `parts` with `amps` above
    0. A file that is not JSON, or not of that shape, states none: `workcenter ratings` names its fault."""
    try:
        data = json.loads(ratings.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    parts = data.get("parts") if isinstance(data, dict) else None
    out = []
    for key, entry in (parts if isinstance(parts, dict) else {}).items():
        amps = entry.get("amps") if isinstance(entry, dict) else None
        if isinstance(amps, (int, float)) and not isinstance(amps, bool) and amps > 0:
            out.append(f"{key} {amps:g} A")
    return out


def needs(netlist, loads: list[str], decks: dict[str, str]) -> list[Need]:
    """The circuits of `netlist` (ratings.Netlist) that no deck of `decks` ({name: text}) answers.
    `loads` are the loads ratings.json states (`stated_loads`)."""
    done = answered(decks)
    out: list[Need] = []
    pulled: dict[str, list] = {}  # an I2C net -> its 2-pin pull-ups (ratings.Part)
    for net, nodes in sorted(netlist.nets.items()):
        if not is_i2c(net, [n.name for n in nodes]):
            continue
        for ref in dict.fromkeys(node.ref for node in nodes):
            part = netlist.parts.get(ref)
            if part is None:
                continue
            resistor = RESISTOR_SYMBOL_RE.fullmatch(part.symbol) or RESISTOR_REF_RE.fullmatch(ref)
            array = ARRAY_SYMBOL_RE.fullmatch(part.symbol) or ARRAY_REF_RE.fullmatch(ref)
            if array or (resistor and len(part.pins) > 2):
                out.append(
                    Need(
                        "i2c-rise",
                        (net,),
                        f"not judged: the I2C line {net} meets {ref} ({part.symbol}, {part.value}), a "
                        "resistor array or network: simneeds reads 2-pin resistors only, so its pull-up "
                        f"is not known and its rise time is held to nothing ({UM10204})",
                    )
                )
                continue
            if not resistor or len(part.pins) != 2:
                continue
            other = next((n for n in part.pins.values() if n != net), None)
            if other is not None and is_rail(other, netlist.nets.get(other, [])):
                pulled.setdefault(net, []).append(part)
    for stem, kind, names in markers(decks):
        if kind == "i2c-rise":
            out += deck_checks(stem, names, pulled, decks[stem])
            continue
        for ref in names:  # a load-step deck runs the regulator it names: an element X<ref> (or <ref>)
            if ref in netlist.parts and not {f"X{ref}".upper(), ref.upper()} & instances(decks[stem]):
                out.append(
                    Need(
                        "load-step",
                        (ref,),
                        f"{stem}.cir: says `* deck: load-step {ref}` and no line runs {ref} (an element "
                        f"X{ref}): the deck does not run the board's regulator",
                        failed=True,
                    )
                )
    left = [n for n in pulled if n not in done["i2c-rise"]]
    if left:
        shown = " ".join(left)
        ups = ", ".join(f"{p.ref} ({p.value})" for n in left for p in pulled[n])
        out.append(
            Need(
                "i2c-rise",
                tuple(left),
                f"not judged: the I2C lines {', '.join(left)} are pulled up by {ups} and no deck says "
                f"`* deck: i2c-rise {shown}`: their rise time is held to nothing ({UM10204}); copy "
                "templates/project/sim/i2c_rise.cir",
            )
        )
    if loads:
        for ref, part in sorted(netlist.parts.items()):
            if part.symbol.split(":", 1)[0] not in REGULATOR_LIBS or ref in done["load-step"]:
                continue
            out.append(
                Need(
                    "load-step",
                    (ref,),
                    f"not judged: {ref} ({part.symbol}) feeds the loads ratings.json states "
                    f"({', '.join(loads)}) and no deck says `* deck: load-step {ref}`: its output under a "
                    "load step is held to nothing (its datasheet's load transient); copy "
                    "templates/project/sim/load_step.cir",
                )
            )
    return out


def free_name(sim_dir: Path, stem: str) -> str:
    """The first name `stem`, `stem_2`, `stem_3`, ... that neither a deck nor its expect file holds in
    `sim_dir`: a copied template never replaces a file."""
    n = 1
    while True:
        name = stem if n == 1 else f"{stem}_{n}"
        if not (sim_dir / f"{name}.cir").exists() and not (sim_dir / f"{name}.expect.json").exists():
            return name
        n += 1
