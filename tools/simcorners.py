#!/usr/bin/env python3
"""simcorners — the corners a SIM deck runs at: temperature, part tolerance, Monte Carlo.

A deck is written at one condition: 27 C, every part at its written value. A limit holds only when it
holds at the ends of every range the board can meet (PROCESSES.md P28 step 4). A project's
`sim/corners.json` names those ranges once, and the SIM gate runs every deck at each of them and holds
every bound at all of them:

    {
      "temperature": {"values": [-20, 85], "source": "REQ-ENV-01: operation from -20 to 85 C"},
      "tolerance": {"R": 0.01, "C": 0.2, "parts": {"R12": 0.001}, "source": "parts/catalog.csv"},
      "monte_carlo": {"runs": 100, "seed": 1},
      "decks": {"mosfets": {"skip": "fitted models against their datasheets' 25 C rows"}}
    }

- temperature: each value is one run of the deck with `.options temp=<value>` and its parts as written.
- tolerance: each part it covers runs twice, at its value less and plus the tolerance. `R`, `C` and `L`
  cover every element of that kind named like a board reference (R7, C15); `parts` names any element or
  `.param`, and wins over the kind. Only a value written as a number is moved.
- worst case: for each bound, the setting of every range that pushed its measure furthest that way, run
  together. One run per distinct combination.
- monte_carlo: `runs` more runs, every covered part drawn evenly inside its tolerance and the temperature
  inside its range, from `seed`.
- decks: one deck's own answer: `skip` with the reason, or `temperature`, `tolerance` or `monte_carlo`
  set to false (with `why`) or replaced.

This module holds the parts that need no engine: reading the file, finding what a deck's text lets a
corner move, writing the deck as a corner runs it, choosing the worst-case runs, and judging a bound.
`tools/workcenter` runs ngspice. Standard library only.
"""

from __future__ import annotations

import json
import math
import operator
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

CORNERS_FILE = "corners.json"
NOMINAL_TEMP = 27.0  # ngspice's circuit temperature when a deck sets none, C
KINDS = ("R", "C", "L")
TOP_KEYS = ("temperature", "tolerance", "monte_carlo", "decks")
DECK_KEYS = ("skip", "why", "temperature", "tolerance", "monte_carlo")
TOLERANCE_KEYS = (*KINDS, "parts", "source")
MAX_RUNS = 10000  # Monte Carlo runs one deck may ask for

# A SPICE number: digits, an optional exponent, an optional scale suffix, then letters ngspice ignores
# (10uF, 1kOhm). M is milli and Meg is mega; F alone is femto.
NUMBER_RE = re.compile(
    r"^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)(meg|mil|[tgkmunpf])?[a-zA-Z]*$", re.IGNORECASE
)
SCALE = {
    "t": 1e12,
    "g": 1e9,
    "meg": 1e6,
    "k": 1e3,
    "mil": 25.4e-6,
    "m": 1e-3,
    "u": 1e-6,
    "n": 1e-9,
    "p": 1e-12,
    "f": 1e-15,
}
# A deck element named the way a board names its parts: the kind's letter and a number.
REFERENCE_RE = re.compile(r"^[RCL]\d+$", re.IGNORECASE)
ELEMENT_RE = re.compile(r"^(\s*)(\S+)(\s+)(\S+)(\s+)(\S+)(\s+)(\S+)")
PARAM_RE = re.compile(r"([A-Za-z_]\w*)\s*=\s*([^\s=,]+)")
BRACED_RE = re.compile(r"^[{']\s*([A-Za-z_]\w*)\s*[}']$")
# `alter rcoil 0.8` and `alter c4 = 1u` in a .control block: an element's value set again.
ALTER_RE = re.compile(r"^\s*alter\s+([A-Za-z]\w*)\s*=?\s*(\S+)\s*$", re.IGNORECASE)
# ngspice names the temperature of every analysis it starts; a corner's run is checked against it.
ANALYSIS_TEMP_RE = re.compile(r"^Doing analysis at TEMP = ([-+]?[\d.]+(?:[eE][-+]?\d+)?)", re.MULTILINE)
TEMP_MATCH = 0.01  # C: a run's printed temperature against the corner's


def spice_number(token: str) -> float | None:
    """A SPICE number's value, or None for anything else (an expression, a name, a model)."""
    m = NUMBER_RE.match(token.strip())
    if not m:
        return None
    return float(m.group(1)) * SCALE.get((m.group(2) or "").lower(), 1.0)


def spice_text(value: float) -> str:
    """A value as a deck writes it: every digit ngspice reads, no suffix."""
    return f"{value:.12g}"


@dataclass(frozen=True)
class Site:
    """One place a deck writes a number: the line's index, the token's span in it, and its value."""

    line: int
    start: int
    end: int
    value: float


@dataclass
class Varied:
    """One part a corner moves: an element's or a `.param`'s number, at every place the deck writes it.
    A deck that models a part in each of several `.subckt` copies writes it more than once."""

    name: str  # as the deck writes the element or the parameter
    kind: str  # R | C | L | param
    tol: float  # a fraction: 0.01 is 1 %
    sites: list[Site]

    @property
    def key(self) -> str:
        return self.name.upper()

    @property
    def nominal(self) -> float:
        return self.sites[0].value


@dataclass
class Corner:
    """One run of a deck: a temperature, and a scale for each value it moves."""

    id: str  # a file name: t85, R7+, w3, mc012
    kind: str  # temperature | tolerance | worst | monte-carlo
    label: str  # as a failure line names it: "85 C", "R7 +1 %"
    temp: float | None = None  # None: the deck's own
    scale: dict[str, float] = field(default_factory=dict)  # Varied.key -> multiplier

    def signature(self) -> tuple:
        return (self.temp, tuple(sorted(self.scale.items())))


@dataclass
class DeckCorners:
    """What one deck runs at: its temperatures, its tolerance block and its Monte Carlo block, each None
    when it does not apply, or `skip` with the reason the project gave."""

    skip: str = ""
    temperatures: list[float] = field(default_factory=list)
    tolerance: dict | None = None
    monte_carlo: dict | None = None


# ------------------------------------------------------------------ the file


def fraction(value: object, where: str, problems: list[str]) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value < 1:
        problems.append(f"{where}: {value!r} is not a fraction between 0 and 1 (0.01 is 1 %)")
        return None
    return float(value)


def stated(text: object) -> bool:
    """Whether a `source`, a `why` or a name says something: text that is not the template's own
    `fill: ...`, which a project copied from templates/project/ still carries until it is written."""
    return isinstance(text, str) and bool(text.strip()) and not text.strip().lower().startswith("fill:")


def check_temperature(block: object, where: str, problems: list[str]) -> list[float]:
    if not isinstance(block, dict):
        problems.append(f"{where}: not an object with values and source")
        return []
    for key in sorted(set(block) - {"values", "source"}):
        problems.append(f"{where}: unknown key {key!r}")
    values = block.get("values")
    numbers = (
        isinstance(values, list)
        and values
        and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values)
    )
    if not numbers:
        problems.append(f"{where}: values is not a list of temperatures in C")
        return []
    if not stated(block.get("source")):
        problems.append(f"{where}: no source: the requirement or datasheet the range comes from")
    return [float(v) for v in values]


def check_tolerance(block: object, where: str, problems: list[str]) -> dict | None:
    if not isinstance(block, dict):
        problems.append(f"{where}: not an object")
        return None
    for key in sorted(set(block) - set(TOLERANCE_KEYS)):
        problems.append(f"{where}: unknown key {key!r}")
    out: dict = {"parts": {}}
    for kind in KINDS:
        if kind in block:
            out[kind] = fraction(block[kind], f"{where}.{kind}", problems)
    parts = block.get("parts", {})
    if not isinstance(parts, dict):
        problems.append(f"{where}.parts: not an object of name: fraction")
        parts = {}
    for name, value in parts.items():
        tol = fraction(value, f"{where}.parts.{name}", problems)
        if tol is not None:
            out["parts"][str(name).upper()] = tol
    if not stated(block.get("source")):
        problems.append(f"{where}: no source: where the tolerances come from")
    return out


def check_monte_carlo(block: object, where: str, problems: list[str]) -> dict | None:
    if not isinstance(block, dict):
        problems.append(f"{where}: not an object with runs and seed")
        return None
    for key in sorted(set(block) - {"runs", "seed"}):
        problems.append(f"{where}: unknown key {key!r}")
    runs, seed = block.get("runs"), block.get("seed", 1)
    if isinstance(runs, bool) or not isinstance(runs, int) or not 1 <= runs <= MAX_RUNS:
        problems.append(f"{where}.runs: {runs!r} is not a count from 1 to {MAX_RUNS}")
        return None
    if isinstance(seed, bool) or not isinstance(seed, int):
        problems.append(f"{where}.seed: {seed!r} is not a whole number")
        return None
    return {"runs": runs, "seed": seed}


def read_corners(sim_dir: Path, decks: list[str]) -> tuple[dict[str, DeckCorners] | None, list[str]]:
    """`sim_dir`/corners.json resolved for each deck: (None, []) when the project has none, else
    ({deck: DeckCorners}, problems). A problem is a line of the file the gate cannot act on: a key it
    does not know, a range without its source, a deck that is not there."""
    path = sim_dir / CORNERS_FILE
    if not path.is_file():
        return None, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return {}, [f"{CORNERS_FILE}: not JSON: {exc}"]
    if not isinstance(data, dict):
        return {}, [f"{CORNERS_FILE}: not an object"]
    problems: list[str] = []
    for key in sorted(set(data) - set(TOP_KEYS)):
        problems.append(f"{CORNERS_FILE}: unknown key {key!r}")
    temps = check_temperature(data["temperature"], "temperature", problems) if "temperature" in data else []
    tolerance = check_tolerance(data["tolerance"], "tolerance", problems) if "tolerance" in data else None
    monte = check_monte_carlo(data["monte_carlo"], "monte_carlo", problems) if "monte_carlo" in data else None
    if not temps and tolerance is None:
        problems.append(f"{CORNERS_FILE}: names neither temperature nor tolerance")
    own = data.get("decks", {})
    if not isinstance(own, dict):
        problems.append("decks: not an object of deck: answer")
        own = {}
    for name in sorted(set(own) - set(decks)):
        problems.append(f"decks.{name}: no sim/{name}.cir")
    out: dict[str, DeckCorners] = {}
    for deck in decks:
        entry = own.get(deck, {})
        where = f"decks.{deck}"
        if not isinstance(entry, dict):
            problems.append(f"{where}: not an object")
            entry = {}
        for key in sorted(set(entry) - set(DECK_KEYS)):
            problems.append(f"{where}: unknown key {key!r}")
        if "skip" in entry:
            reason = entry["skip"].strip() if stated(entry["skip"]) else ""
            if not reason:
                problems.append(f"{where}.skip: no reason")
            out[deck] = DeckCorners(skip=reason or "no reason given")
            continue
        resolved = DeckCorners(
            temperatures=list(temps),
            tolerance={**tolerance, "parts": dict(tolerance["parts"])} if tolerance else None,
            monte_carlo=dict(monte) if monte else None,
        )
        off = False
        if "temperature" in entry:
            if entry["temperature"] is False:
                resolved.temperatures, off = [], True
            else:
                resolved.temperatures = check_temperature(
                    entry["temperature"], f"{where}.temperature", problems
                )
        if "tolerance" in entry:
            if entry["tolerance"] is False:
                resolved.tolerance, off = None, True
            else:
                resolved.tolerance = check_tolerance(entry["tolerance"], f"{where}.tolerance", problems)
        if "monte_carlo" in entry:
            if entry["monte_carlo"] is False:
                resolved.monte_carlo, off = None, True
            else:
                resolved.monte_carlo = check_monte_carlo(
                    entry["monte_carlo"], f"{where}.monte_carlo", problems
                )
        if off and not stated(entry.get("why")):
            problems.append(f"{where}: a corner set to false needs why")
        out[deck] = resolved
    return out, problems


# ------------------------------------------------------------------ the deck


def netlist_lines(lines: list[str]) -> list[int]:
    """Indexes of the deck's own netlist lines, the insides of its own `.subckt` blocks too: not its
    title, a comment, a continuation or a `.control` block. A file the deck includes is not the deck."""
    out = []
    control = False
    for i, raw in enumerate(lines):
        if i == 0:
            continue
        s = raw.strip()
        low = s.lower()
        if control:
            control = not low.startswith(".endc")
            continue
        if low.startswith(".control"):
            control = True
            continue
        if not s or s[0] in "*+;$":
            continue
        out.append(i)
    return out


def control_lines(lines: list[str]) -> list[int]:
    """Indexes of the lines inside the deck's `.control` blocks."""
    out = []
    control = False
    for i, raw in enumerate(lines):
        low = raw.strip().lower()
        if control and low.startswith(".endc"):
            control = False
        elif control:
            out.append(i)
        elif low.startswith(".control"):
            control = True
    return out


def deck_values(lines: list[str]) -> tuple[dict[str, list[tuple[Site | None, str]]], dict[str, list]]:
    """Where a deck writes each value: (elements, params). Each maps an upper-case name to its places,
    in the deck's order: for an R, C or L element (the place of its fourth token, or None when that is
    not a number, with the token), for a `.param` (its number's place, or None). A value the deck sets
    again in `.control` (`alter rcoil 0.8`) is one more place of that element: the part is as far off
    its value in every analysis the deck runs."""
    elements: dict[str, list[tuple[Site | None, str]]] = {}
    params: dict[str, list[Site | None]] = {}
    for i in netlist_lines(lines):
        line = lines[i]
        if line.strip().lower().startswith(".param"):
            offset = line.lower().index(".param") + len(".param")
            for m in PARAM_RE.finditer(line, offset):
                value = spice_number(m.group(2))
                site = None if value is None else Site(i, m.start(2), m.end(2), value)
                params.setdefault(m.group(1).upper(), []).append(site)
            continue
        if line.strip()[0].upper() not in KINDS:
            continue
        m = ELEMENT_RE.match(line)
        if m:
            value = spice_number(m.group(8))
            site = None if value is None else Site(i, m.start(8), m.end(8), value)
            elements.setdefault(m.group(2).upper(), []).append((site, m.group(8)))
    for i in control_lines(lines):
        m = ALTER_RE.match(lines[i])
        if m and m.group(1).upper() in elements:
            value = spice_number(m.group(2))
            if value is not None:
                elements[m.group(1).upper()].append((Site(i, m.start(2), m.end(2), value), m.group(2)))
    return elements, params


def find_varied(text: str, tolerance: dict | None) -> tuple[list[Varied], list[str], list[str]]:
    """What a deck's text lets a tolerance corner move: (varied, problems, uncovered). A part is moved
    at every place the deck writes it, the copies inside its own `.subckt` blocks included. A problem
    is a part `tolerance.parts` names whose value the deck writes as something other than a number.
    `uncovered` lists the elements named like board references that no tolerance covers."""
    if tolerance is None:
        return [], [], []
    lines = text.split("\n")
    parts: dict[str, float] = tolerance.get("parts", {})
    elements, params = deck_values(lines)
    names = {ln.split()[0].upper(): ln.split()[0] for ln in (lines[i] for i in netlist_lines(lines))}

    varied: list[Varied] = []
    problems: list[str] = []
    uncovered: list[str] = []
    taken: dict[Site, str] = {}  # a place moves with one part: the first that claims it

    def claim(key: str, kind: str, tol: float, sites: list[Site]) -> None:
        free = [s for s in sites if s.value != 0 and s not in taken]
        for s in free:
            taken[s] = key
        if free:
            varied.append(Varied(names.get(key, key.lower()), kind, tol, free))

    # A parameter `parts` names moves first, so an element written from it does not claim its number.
    for key, tol in parts.items():
        if key not in params or key in elements:
            continue
        sites = [s for s in params[key] if s is not None]
        if len(sites) < len(params[key]):
            problems.append(f".param {key} is named in {CORNERS_FILE} and its value is not a number")
        claim(key, "param", tol, sites)

    def written_from(token: str) -> list[Site]:
        braced = BRACED_RE.match(token)
        return [s for s in params.get((braced.group(1) if braced else token).upper(), []) if s]

    for key, places in elements.items():
        kind = key[0]
        tol = parts.get(key)
        if tol is None and REFERENCE_RE.match(key):
            tol = tolerance.get(kind)
            # An element written from a parameter that `parts` moves is covered by that parameter.
            moved = all(s is None and any(t in taken for t in written_from(tok)) for s, tok in places)
            if tol is None and not moved:
                uncovered.append(names[key])
        if tol is None:
            continue
        sites: list[Site] = []
        for site, token in places:
            if site is not None:
                sites.append(site)
                continue
            # A value written as one parameter moves that parameter's own number.
            target = written_from(token)
            if target:
                sites += target
            elif key in parts:
                problems.append(
                    f"{names[key]} is named in {CORNERS_FILE} and its value {token} is not a number"
                )
            else:
                uncovered.append(names[key])
        claim(key, kind, tol, sites)
    return varied, problems, uncovered


def names_in(text: str) -> set[str]:
    """Every element and parameter name a deck's own netlist lines define, upper case."""
    lines = text.split("\n")
    out: set[str] = set()
    for i in netlist_lines(lines):
        line = lines[i]
        if line.strip().lower().startswith(".param"):
            offset = line.lower().index(".param") + len(".param")
            out |= {m.group(1).upper() for m in PARAM_RE.finditer(line, offset)}
        elif not line.strip().startswith("."):
            out.add(line.split()[0].upper())
    return out


def corner_text(text: str, varied: list[Varied], corner: Corner) -> str:
    """The deck as a corner runs it: each moved value rewritten in place, and the temperature set on a
    line of its own before the `.control` block (before `.end` in a deck without one). ngspice takes
    the last `.options temp` of a netlist, so the corner's wins over one the deck writes above it; a
    temperature the deck sets inside `.control` wins over both and is caught by `temperature_problem`."""
    lines = text.split("\n")
    edits: dict[int, list[tuple[Site, float]]] = {}
    for v in varied:
        if v.key in corner.scale:
            for site in v.sites:
                edits.setdefault(site.line, []).append((site, corner.scale[v.key]))
    for i, group in edits.items():
        line = lines[i]
        for site, factor in sorted(group, key=lambda g: g[0].start, reverse=True):
            line = line[: site.start] + spice_text(site.value * factor) + line[site.end :]
        lines[i] = line
    if corner.temp is not None:
        ends = [
            i for i, ln in enumerate(lines) if i and ln.strip().lower().split(" ")[0] in (".control", ".end")
        ]
        lines.insert(ends[0] if ends else len(lines), f".options temp={corner.temp:g}")
    return "\n".join(lines)


# ------------------------------------------------------------------ the runs


def percent(tol: float) -> str:
    return f"{tol * 100:g} %"


def file_id(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", text)


def first_corners(temperatures: list[float], varied: list[Varied]) -> list[Corner]:
    """One range at a time: each temperature with the parts as written, then each part at both ends of
    its tolerance at the deck's own temperature."""
    out = []
    for t in sorted(set(temperatures)):
        if abs(t - NOMINAL_TEMP) > TEMP_MATCH:
            out.append(Corner(f"t{t:g}", "temperature", f"{t:g} C", temp=t))
    for v in varied:
        out.append(
            Corner(
                file_id(f"{v.name}-"), "tolerance", f"{v.name} -{percent(v.tol)}", scale={v.key: 1 - v.tol}
            )
        )
        out.append(
            Corner(
                file_id(f"{v.name}+"), "tolerance", f"{v.name} +{percent(v.tol)}", scale={v.key: 1 + v.tol}
            )
        )
    return out


def worst_corners(
    bounded: dict[str, tuple[bool, bool]],
    nominal: dict[str, float],
    firsts: list[Corner],
    results: dict[str, dict[str, float]],
    varied: list[Varied],
) -> list[Corner]:
    """For each bounded measure and each side it is bounded on, the run that sets every range to the end
    which, alone, pushed the measure furthest that way. `bounded` maps a measure to (has a minimum, has
    a maximum); `results` maps a first corner's id to its measures. A combination already run, or equal
    to the deck as written, is left out; one combination serves every bound that asks for it.

    The choice assumes each range pushes the measure one way across its span, which holds for the
    passive networks and operating points a deck usually bounds; Monte Carlo covers the rest."""
    done = {c.signature() for c in firsts} | {Corner("", "", "").signature()}
    by_key = {v.key: v for v in varied}
    out: list[Corner] = []
    for measure in sorted(bounded):
        base = nominal.get(measure)
        if base is None:
            continue
        for side, wanted in zip(("min", "max"), bounded[measure], strict=True):
            if not wanted:
                continue
            better = operator.lt if side == "min" else operator.gt
            temp, temp_value = None, base
            scale: dict[str, float] = {}
            best: dict[str, float] = {}
            for c in firsts:
                value = results.get(c.id, {}).get(measure)
                if value is None:
                    continue
                if c.kind == "temperature":
                    if better(value, temp_value):
                        temp, temp_value = c.temp, value
                    continue
                ((key, factor),) = c.scale.items()
                if better(value, best.get(key, base)):
                    best[key], scale[key] = value, factor
            corner = Corner("", "worst", "", temp=temp, scale=scale)
            if corner.signature() in done:
                continue
            done.add(corner.signature())
            said = [f"{temp:g} C"] if temp is not None else []
            for key in sorted(scale):
                v = by_key[key]
                said.append(f"{v.name} {'+' if scale[key] > 1 else '-'}{percent(v.tol)}")
            corner.id, corner.label = f"w{len(out) + 1}", ", ".join(said)
            out.append(corner)
    return out


def monte_carlo_corners(
    deck: str, monte: dict | None, temperatures: list[float], varied: list[Varied]
) -> list[Corner]:
    """`runs` draws for one deck: each covered value evenly inside its tolerance, the temperature evenly
    inside its range. The seed and the deck's name fix the draws, so a run repeats."""
    if not monte or not (varied or temperatures):
        return []
    rng = random.Random(f"{monte['seed']}:{deck}")
    span = [*temperatures, NOMINAL_TEMP]
    low, high = min(span), max(span)
    width = len(str(monte["runs"]))
    out = []
    for n in range(1, monte["runs"] + 1):
        scale = {v.key: 1 + v.tol * rng.uniform(-1, 1) for v in varied}
        temp = round(rng.uniform(low, high), 2) if temperatures else None
        out.append(Corner(f"mc{n:0{width}d}", "monte-carlo", f"Monte Carlo run {n}", temp=temp, scale=scale))
    return out


def temperature_problem(corner: Corner, output: str) -> str | None:
    """Why a run did not happen at its corner's temperature, from ngspice's own line for each analysis,
    or None: the corner sets no temperature, or every analysis ran at it."""
    if corner.temp is None:
        return None
    ran = [float(t) for t in ANALYSIS_TEMP_RE.findall(output)]
    if not ran:
        return f"ngspice named no analysis temperature, so {corner.temp:g} C is not confirmed"
    off = sorted({t for t in ran if abs(t - corner.temp) > TEMP_MATCH})
    if off:
        said = ", ".join(f"{t:g}" for t in off)
        return f"ran at {said} C, not {corner.temp:g} C: the deck sets its own temperature"
    return None


# ------------------------------------------------------------------ the verdict


def nominal_only(bounds: dict) -> bool:
    """A bound judged at the deck as written and at no corner: a model against its datasheet's row
    (`warn`), which holds at the row's own conditions, or one that says `"at": "nominal"`."""
    return bool(bounds.get("warn")) or bounds.get("at") == "nominal"


def envelope(nominal: dict[str, float], runs: list[tuple[Corner, dict[str, float]]]) -> dict[str, dict]:
    """Each measure's least and greatest value over the deck as written and every corner that printed
    it, with the run that gave each, and the corners that did not print it."""
    out: dict[str, dict] = {}
    names = set(nominal)
    for _, measures in runs:
        names |= set(measures)
    for name in sorted(names):
        seen = [("nominal", nominal[name])] if name in nominal else []
        missing = []
        for corner, measures in runs:
            if name in measures:
                seen.append((corner.label, measures[name]))
            else:
                missing.append(corner.label)
        low = min(seen, key=lambda s: s[1])
        high = max(seen, key=lambda s: s[1])
        out[name] = {"min": low[1], "min_at": low[0], "max": high[1], "max_at": high[0], "missing": missing}
    return out


def outside(value: float | None, bounds: dict) -> float:
    """How far a value is outside its bound: 0 inside, infinity when it was not measured."""
    if value is None:
        return math.inf
    low, high = bounds.get("min"), bounds.get("max")
    if low is not None and value < low:
        return low - value
    if high is not None and value > high:
        return value - high
    return 0.0


def worst_offender(
    name: str, bounds: dict, runs: list[tuple[Corner, dict[str, float]]]
) -> tuple[Corner, float | None, int] | None:
    """The corner at which a bound fails by the most: (corner, its value, how many corners fail), or
    None when the bound holds at every corner."""
    failing = [(outside(m.get(name), bounds), c, m.get(name)) for c, m in runs]
    failing = [f for f in failing if f[0] > 0]
    if not failing:
        return None
    _, corner, value = max(failing, key=lambda f: f[0])
    return corner, value, len(failing)


def statistics(runs: list[tuple[Corner, dict[str, float]]]) -> dict[str, dict]:
    """Each measure over the Monte Carlo runs: how many printed it, its mean, its standard deviation,
    its least and greatest value."""
    out: dict[str, dict] = {}
    names = {n for c, m in runs if c.kind == "monte-carlo" for n in m}
    for name in sorted(names):
        values = [m[name] for c, m in runs if c.kind == "monte-carlo" and name in m]
        mean = sum(values) / len(values)
        spread = (
            math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1)) if len(values) > 1 else 0.0
        )
        out[name] = {
            "runs": len(values),
            "mean": mean,
            "stdev": spread,
            "min": min(values),
            "max": max(values),
        }
    return out
