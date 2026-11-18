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
`* deck: load-step U1` the regulator. templates/project/sim/ holds a deck of each kind with its bounds
and their sources. What is not recognized: a line with no pull-up on this board, a bus by any other
name, a regulator drawn with a symbol of another library, and a load stated anywhere but ratings.json.

Standard library only. `tools/workcenter` exports the netlist and reads it with `ratings.read_netlist`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {"nxp-um10204": "Rev. 7.0, table 11, page 44: the rise time an I2C line is held to"}
KINDS = {"i2c-rise": "i2c_rise", "load-step": "load_step"}  # a need's kind -> its template's name
REGULATOR_LIBS = ("Regulator_Linear", "Regulator_Switching")
I2C_WORD_RE = re.compile(r"(?:SDA|SCL)\d*")
GROUND_RE = re.compile(r"(?:GND|VSS|AGND|DGND|PGND)\w*", re.I)
RAIL_RE = re.compile(r"\+.*|(?:VCC|VDD|VIO|VBUS|VBAT|VIN|VOUT|\d+V\d*)\w*", re.I)
MARK_RE = re.compile(r"^\*\s*deck:\s*(\S+)(.*)$", re.I)
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


def words(text: str) -> list[str]:
    """The words of a name, in upper case: `PB1/SDA` -> PB1, SDA; `I2C_SCL` -> I2C, SCL."""
    return [w for w in re.split(r"[^A-Za-z0-9]+", text.upper()) if w]


def is_i2c(name: str, pin_names: list[str]) -> bool:
    """Whether a net is an I2C line: SDA or SCL is a word of its name or of a pin's name on it."""
    return any(I2C_WORD_RE.fullmatch(w) for text in [name, *pin_names] for w in words(text))


def is_rail(name: str, kinds: list[str]) -> bool:
    """Whether a net is a supply rail: a power pin stands on it, or its name is a rail's (+3V3, VCC,
    VDD_IO, 3V3). Ground is no rail: a resistor to it pulls down."""
    bare = name.rsplit("/", 1)[-1]
    if GROUND_RE.fullmatch(bare):
        return False
    return bool(RAIL_RE.fullmatch(bare)) or any(k in ("power_in", "power_out") for k in kinds)


def worth_reading(texts: list[str]) -> bool:
    """Whether a schematic's text can hold a need: its netlist is exported only then."""
    return any(WORTH_RE.search(t) for t in texts)


def answered(decks: dict[str, str]) -> dict[str, set[str]]:
    """What the decks answer, by kind: the names each `* deck: <kind> <names>` line gives. A kind the
    module does not know is left out."""
    out: dict[str, set[str]] = {kind: set() for kind in KINDS}
    for text in decks.values():
        for raw in text.splitlines():
            m = MARK_RE.match(raw.strip())
            if m and m.group(1).lower() in out:
                out[m.group(1).lower()].update(n.strip(",") for n in m.group(2).split() if n.strip(","))
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
    pulled: dict[str, list[str]] = {}  # an I2C net -> its pull-ups, as `R1 (4.7k)`
    for net, nodes in sorted(netlist.nets.items()):
        if not is_i2c(net, [n.name for n in nodes]):
            continue
        for node in nodes:
            part = netlist.parts.get(node.ref)
            if part is None or not re.fullmatch(r"R\d+", part.ref) or len(part.pins) != 2:
                continue
            other = next((n for n in part.pins.values() if n != net), None)
            if other is not None and is_rail(other, [n.kind for n in netlist.nets.get(other, [])]):
                pulled.setdefault(net, []).append(f"{part.ref} ({part.value})")
    left = [n for n in pulled if n not in done["i2c-rise"]]
    if left:
        shown = " ".join(left)
        ups = ", ".join(r for n in left for r in pulled[n])
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
