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

import itertools
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
# The most runs spent on every combination of the ends of a deck's ranges: 6 ranges, or 5 and a
# temperature. Past it the worst case is a guess from one range at a time, and the run says so.
EXHAUSTIVE_RUNS = 64
SWEEP_STEP = 0.02  # of a part's value, for a deck that answers an overlap
REFINE_ROUNDS = 5  # halvings toward a peak inside a part's range: to 1/64 of the tolerance

# A SPICE number: digits, an optional exponent, an optional scale suffix, then letters ngspice ignores
# (10uF, 1kOhm). M is milli and Meg is mega; F alone is femto and A alone is atto (ngspice 42 reads
# `5a` as 5e-18).
NUMBER_RE = re.compile(
    r"^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)(meg|mil|[tgkmunpfa])?[a-zA-Z]*$", re.IGNORECASE
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
    "a": 1e-18,
}
# A value with a digit after its scale letter, the way a schematic writes 4.7 k: ngspice 42 reads
# `4k7` as 4k and says nothing.
DROPPED_DIGITS_RE = re.compile(
    r"^([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)(meg|mil|[tgkmunpfa])(\d+)[a-zA-Z]*$", re.IGNORECASE
)
# A token of a netlist line: a braced or a quoted expression whole, whatever stands inside it, then
# words; `=` is a token of its own.
TOKEN_RE = re.compile(r"\{[^{}]*\}|'[^']*'|[^\s=]+|=")
# A deck element named the way a board names its parts: the kind's letter and a number.
REFERENCE_RE = re.compile(r"^[RCL]\d+$", re.IGNORECASE)
# The words that may stand before an element's value on its line or in an `alter`: `R1 a b r=10k`,
# `alter r2 resistance = 10k`, `V1 in 0 DC 5`, `alter v1 dc = 4.2`.
VALUE_WORDS = {
    "R": ("r", "resistance"),
    "C": ("c", "capacitance"),
    "L": ("l", "inductance"),
    "V": ("dc",),
    "I": ("dc",),
}
PARAM_RE = re.compile(r"([A-Za-z_]\w*)\s*=\s*([^\s=,]+)")
BRACED_RE = re.compile(r"^[{']\s*([A-Za-z_]\w*)\s*[}']$")
# A value set again in a .control block, in each form ngspice 42 takes: `alter @r2[resistance] = 10k`,
# `alter r2 resistance = 10k`, `alterparam rbot = 10k`, `alter r2 10k` and `alter r2 = 10k`.
ALTER_FORMS = (
    re.compile(r"^\s*alter\s+@(?P<dev>[A-Za-z]\w*)\[(?P<param>\w+)\]\s*=?\s*(?P<value>\S+)\s*$", re.I),
    re.compile(r"^\s*alter\s+(?P<dev>[A-Za-z]\w*)\s+(?P<param>[A-Za-z]\w*)\s*=\s*(?P<value>\S+)\s*$", re.I),
    re.compile(r"^\s*alterparam\s+(?P<dev>[A-Za-z_]\w*)\s*=\s*(?P<value>\S+)\s*$", re.I),
    re.compile(r"^\s*alter\s+(?P<dev>[A-Za-z]\w*)\s*=?\s*(?P<value>\S+)\s*$", re.I),
)
ALTER_ANY_RE = re.compile(r"^\s*alter(?:param)?\s+@?(?P<dev>[A-Za-z_]\w*)", re.I)
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
    """One place a deck writes a value: the line's index, the token's span in it, and the number there.
    `value` is None where the deck writes an expression or a parameter's name (`{rtop}`, `rtop`,
    `{2*rtop}`): a corner scales such a place by wrapping it, `{(2*rtop)*1.05}`, so 2 parts written
    from 1 parameter still move apart."""

    line: int
    start: int
    end: int
    value: float | None


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
    def nominal(self) -> float | None:
        """The part's written value, or None when the deck writes it as an expression."""
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
    declined: bool = False  # the project set this deck's tolerance to false, with why


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
                resolved.tolerance, resolved.declined, off = None, True, True
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


def statement_lines(lines: list[str], i: int) -> list[tuple[int, int, int]]:
    """The physical lines of the netlist statement that starts at index i, as (line, begin, end):
    the line itself, then every following line that starts with `+`, a comment or an empty line
    between them passed over, as ngspice joins them. `begin` is past the `+`; `end` stops at a `;`."""
    out: list[tuple[int, int, int]] = []
    j = i
    while j < len(lines):
        raw = lines[j]
        begin = 0
        if j > i:
            s = raw.strip()
            if not s or s.startswith("*"):
                j += 1
                continue
            if not s.startswith("+"):
                break
            begin = raw.index("+") + 1
        cut = raw.find(";", begin)
        out.append((j, begin, cut if cut >= 0 else len(raw)))
        j += 1
    return out


def logical_tokens(lines: list[str], i: int) -> list[tuple[int, int, int, str]]:
    """The tokens of the netlist statement at index i, continuation lines included, as (line, start,
    end, text) in order. `=` is a token of its own, so `r=10k`, `r =10k` and `r = 10k` read alike; a
    braced or quoted expression is 1 token."""
    return [
        (j, begin + m.start(), begin + m.end(), m.group())
        for j, begin, end in statement_lines(lines, i)
        for m in TOKEN_RE.finditer(lines[j][begin:end])
    ]


def value_place(tokens: list[tuple[int, int, int, str]]) -> tuple[int, int, int, str] | None:
    """Where an element writes its value among its tokens. An R, C or L: the fourth token, or the one
    after `r =` (`c =`, `l =`) when the fourth is the kind's own parameter. A V or I source: the
    fourth token, or the one after `dc`. None for an element with no such token."""
    if len(tokens) < 4:
        return None
    words = VALUE_WORDS.get(tokens[0][3][0].upper(), ())
    at = 3
    if tokens[at][3].lower() in words and len(tokens) > at + 1:
        at += 2 if tokens[at + 1][3] == "=" else 1
    return tokens[at] if at < len(tokens) else None


def place_of(place: tuple[int, int, int, str], params: dict) -> Site | None:
    """A value token as a place a corner can scale: a number, an expression in braces or quotes, or the
    bare name of a parameter. None for anything else (a model's name, `4k7`)."""
    j, start, end, token = place
    value = spice_number(token)
    if value is not None:
        return Site(j, start, end, value)
    if (token[0], token[-1]) in (("{", "}"), ("'", "'")) or token.upper() in params:
        return Site(j, start, end, None)
    return None


def control_commands(lines: list[str]) -> list[tuple[int, int, str]]:
    """Each command of the deck's `.control` blocks as (line, offset, text). A line holds several
    commands between `;`, and ends at a `$ ` comment."""
    out = []
    for i in control_lines(lines):
        raw = lines[i]
        comment = re.search(r"(?:^|\s)\$(?:\s|$)", raw)
        body = raw[: comment.start()] if comment else raw
        offset = 0
        for part in body.split(";"):
            out.append((i, offset, part))
            offset += len(part) + 1
    return out


def deck_values(lines: list[str]) -> tuple[dict, dict, dict, dict]:
    """Where a deck writes each value: (elements, params, sources, unscaled). The first 3 map an
    upper-case name to its places in the deck's order: an R, C or L element's value, a `.param`'s
    number, a V or I source's DC value; a place is None where the deck writes something a corner
    cannot scale. A value the deck sets again in `.control` (`alter rcoil 0.8`, `alter @r2[resistance]
    = 10k`, `alterparam rbot = 10k`) is one more place: the part is as far off its value in every
    analysis the deck runs. `unscaled` maps a name to each such command whose value is no number
    (`alter r2 = $&rv`): a corner cannot follow it."""
    elements: dict[str, list[Site | None]] = {}
    params: dict[str, list[Site | None]] = {}
    sources: dict[str, list[Site | None]] = {}
    unscaled: dict[str, list[str]] = {}
    starts = netlist_lines(lines)
    for i in starts:
        if not lines[i].strip().lower().startswith(".param"):
            continue
        for j, begin, end in statement_lines(lines, i):
            if j == i:
                begin = lines[i].lower().index(".param") + len(".param")
            for m in PARAM_RE.finditer(lines[j][:end], begin):
                value = spice_number(m.group(2))
                site = None if value is None else Site(j, m.start(2), m.end(2), value)
                params.setdefault(m.group(1).upper(), []).append(site)
    for i in starts:
        first = lines[i].strip()[0].upper()
        if first not in VALUE_WORDS:
            continue
        tokens = logical_tokens(lines, i)
        place = value_place(tokens)
        if place:
            held_in = elements if first in KINDS else sources
            held_in.setdefault(tokens[0][3].upper(), []).append(place_of(place, params))
    for i, offset, text in control_commands(lines):
        m = next((m for m in (form.match(text) for form in ALTER_FORMS) if m), None)
        if m is None:
            loose = ALTER_ANY_RE.match(text)
            if loose:
                unscaled.setdefault(loose.group("dev").upper(), []).append(text.strip())
            continue
        name = m.group("dev").upper()
        param = m.groupdict().get("param")
        is_param = text.strip().lower().startswith("alterparam")
        held_in = params if is_param else elements if name in elements else sources
        if name not in held_in or (param and param.lower() not in VALUE_WORDS.get(name[0], ())):
            continue
        value = spice_number(m.group("value"))
        if value is None:
            unscaled.setdefault(name, []).append(text.strip())
        else:
            held_in[name].append(Site(i, offset + m.start("value"), offset + m.end("value"), value))
    return elements, params, sources, unscaled


def deck_names(lines: list[str]) -> dict[str, str]:
    """Each element of the deck's own netlist lines as the deck writes its name, by upper-case name."""
    names = {}
    for i in netlist_lines(lines):
        word = lines[i].split()[0]
        if not word.startswith("."):
            names.setdefault(word.upper(), word)
    return names


def find_varied(
    text: str, tolerance: dict | None, declined: bool = False
) -> tuple[list[Varied], list[str], list[str]]:
    """What a deck's text lets a tolerance corner move: (varied, problems, uncovered).

    Each R, C or L element named like a board reference moves by its kind's tolerance, and whatever
    `tolerance.parts` names moves by its own: an element, a `.param`, a V or I source's DC value. A
    part moves at every place the deck writes it, the copies inside its own `.subckt` blocks and the
    values `.control` sets again included. An element written as an expression or from a parameter
    is scaled where it stands, so 2 parts written from 1 parameter move apart; a parameter `parts`
    names moves as one, and the elements written from it with it.

    A problem is something the file asks for that the deck's text does not allow: a named part
    whose value is no number, a value `.control` sets again in a way a corner cannot scale, a name
    a corner cannot move. `uncovered` lists the elements named like board references that no
    tolerance covers; with no tolerance block at all that is every one of them, unless the project
    declined the tolerance for this deck with its reason (`declined`)."""
    lines = text.split("\n")
    elements, params, sources, unscaled = deck_values(lines)
    names = deck_names(lines)
    if tolerance is None:
        return [], [], [] if declined else [names[k] for k in elements if REFERENCE_RE.match(k)]
    parts: dict[str, float] = tolerance.get("parts", {})

    varied: list[Varied] = []
    problems: list[str] = []
    uncovered: list[str] = []
    by_param: set[Site] = set()  # the places of the parameters `parts` moves

    def claim(key: str, kind: str, tol: float, sites: list[Site]) -> None:
        free = [s for s in sites if s.value != 0]
        if free:
            varied.append(Varied(names.get(key, key.lower()), kind, tol, free))
        for command in unscaled.get(key, []):
            problems.append(
                f"{names.get(key, key.lower())} moves and `.control` sets it again with `{command}`, which "
                "a corner cannot scale: write that value as a number"
            )

    # A parameter `parts` names moves first, and as one: the elements written from it move with it.
    for key, tol in parts.items():
        if key in elements or key in sources or key not in params:
            continue
        sites = [s for s in params[key] if s is not None]
        if len(sites) < len(params[key]):
            problems.append(f".param {key} is named in {CORNERS_FILE} and its value is not a number")
        by_param.update(sites)
        claim(key, "param", tol, sites)

    def moved_by_param(site: Site) -> bool:
        """Whether a place is a bare reference to a parameter that `parts` already moves."""
        token = lines[site.line][site.start : site.end]
        braced = BRACED_RE.match(token)
        target = params.get((braced.group(1) if braced else token).upper(), [])
        return site.value is None and any(s in by_param for s in target if s)

    for key, places in elements.items():
        kind = key[0]
        tol = parts.get(key)
        if tol is None and REFERENCE_RE.match(key):
            tol = tolerance.get(kind)
            covered = all(s is not None and moved_by_param(s) for s in places)
            if tol is None and not covered:
                uncovered.append(names[key])
        if tol is None:
            continue
        if any(s is None for s in places):
            if key in parts:
                problems.append(f"{names[key]} is named in {CORNERS_FILE} and its value is not a number")
            else:
                uncovered.append(names[key])
        claim(key, kind, tol, [s for s in places if s is not None and not moved_by_param(s)])

    for key, tol in parts.items():
        if key not in sources:
            continue
        sites = [s for s in sources[key] if s is not None]
        if len(sites) < len(sources[key]) or not sites:
            problems.append(
                f"{names[key]} is named in {CORNERS_FILE} and its DC value is not a number a corner can "
                f"scale: write it as `{names[key]} n+ n- DC 5`, or from a .param that `parts` names"
            )
        claim(key, key[0], tol, sites)
    return varied, problems, uncovered


def unmoved(text: str, tolerance: dict | None, varied: list[Varied]) -> list[str]:
    """The names under `tolerance.parts` that this deck holds and no corner moves: something other
    than an R, C or L element, a V or I source, or a `.param` (a diode, a subcircuit, a model)."""
    if tolerance is None:
        return []
    present = names_in(text)
    moving = {v.key for v in varied}
    return [name for name in tolerance.get("parts", {}) if name in present and name not in moving]


def held(text: str, varied: list[Varied]) -> list[str]:
    """The R, C and L elements of a deck that no corner moves, by the names the deck writes: an
    element with a word for a name (`LCABLE`) that `tolerance.parts` does not name. Each stays at its
    written value in every run, so a reader of a corner run sees what it did not vary. An element
    named like a board reference is not listed here: with no tolerance it is `uncovered`, a warning."""
    lines = text.split("\n")
    elements, params, _, _ = deck_values(lines)
    names = deck_names(lines)
    moving = {site for v in varied for site in v.sites}
    out: list[str] = []
    for key, places in elements.items():
        if REFERENCE_RE.match(key):
            continue
        sites = [s for s in places if s is not None]
        from_params = {
            s
            for site in sites
            if site.value is None
            for s in params.get(lines[site.line][site.start : site.end].strip("{}'").upper(), [])
            if s
        }
        if any(s.value != 0 for s in sites) and not any(s in moving for s in [*sites, *from_params]):
            out.append(names[key])
    return out


def shared_parts(text: str, varied: list[Varied]) -> list[str]:
    """Moved elements that are more than 1 part on the board: an element inside a `.subckt` the deck
    places more than once. Every copy moves with the others, so nothing that rests on 2 copies
    differing (2 cells, 2 channels, the 2 halves of a divider) can show."""
    lines = text.split("\n")
    scope: dict[int, str] = {}
    inside = ""
    placed: dict[str, list[str]] = {}
    for i, raw in enumerate(lines):
        words = raw.split()
        low = words[0].lower() if words else ""
        if low == ".subckt" and len(words) > 1:
            inside = words[1]
        elif low == ".ends":
            inside = ""
        scope[i] = inside
    for i in netlist_lines(lines):
        if lines[i].strip()[0].upper() != "X":
            continue
        words = [t[3] for t in logical_tokens(lines, i)]
        cut = words.index("=") - 1 if "=" in words else len(words)
        if cut >= 2:
            placed.setdefault(words[cut - 1].lower(), []).append(words[0])
    out = []
    for v in varied:
        for sub in dict.fromkeys(scope[s.line] for s in v.sites if scope.get(s.line)):
            copies = placed.get(sub.lower(), [])
            if len(copies) > 1:
                out.append(
                    f"{v.name} in .subckt {sub} is {len(copies)} parts on the board "
                    f"({', '.join(copies)}): a corner moves them together"
                )
    return out


def top_level_parts(text: str) -> list[str]:
    """The R, C and L elements named like board references that a file holds outside any `.subckt`:
    the parts of a netlist fragment a deck includes, not the insides of a model."""
    lines = ["*", *text.split("\n")]  # an included file has no title line
    out: list[str] = []
    inside = False
    for i in netlist_lines(lines):
        word = lines[i].split()[0]
        if word.lower() == ".subckt":
            inside = True
        elif word.lower() == ".ends":
            inside = False
        elif not inside and REFERENCE_RE.match(word):
            out.append(word)
    return out


def pinned_temperatures(text: str) -> list[str]:
    """The devices a deck holds at a temperature of their own: `temp=` on a device's line or its
    continuation lines, or `alter <device> temp = ...` in `.control`. A temperature corner sets the
    circuit's temperature and ngspice names that one for the analysis, while such a device stays
    where the deck put it: the run is not at the corner's temperature for the part that matters.
    `dtemp=` is a difference from the circuit's temperature and moves with it."""
    lines = text.split("\n")
    pinned: list[str] = []
    for i in netlist_lines(lines):
        tokens = [t[3] for t in logical_tokens(lines, i)]
        if not tokens or not tokens[0][0].isalpha():
            continue
        if any(a.lower() == "temp" and b == "=" for a, b in zip(tokens[1:], tokens[2:], strict=False)):
            pinned.append(tokens[0])
    for i in control_lines(lines):
        m = re.match(r"^\s*alter\s+@?([A-Za-z]\w*)(?:\[temp\]|\s+temp)\s*=", lines[i], re.IGNORECASE)
        if m:
            pinned.append(m.group(1))
    return list(dict.fromkeys(pinned))


def misread_values(text: str) -> list[str]:
    """R, C and L values ngspice reads as another number than they look: a digit after the scale
    letter (`4k7`, `2n2`) is dropped, so `4k7` is 4k. One line for each, with the value ngspice takes."""
    lines = text.split("\n")
    out: list[str] = []
    for i in netlist_lines(lines):
        if lines[i].strip()[0].upper() not in KINDS:
            continue
        tokens = logical_tokens(lines, i)
        place = value_place(tokens)
        m = DROPPED_DIGITS_RE.match(place[3]) if place else None
        if m:
            number, scale, digits = m.groups()
            meant = f"{number}.{digits}{scale}" if number.isdigit() else "the number with its point"
            out.append(
                f"{tokens[0][3]}: ngspice reads the value {place[3]} as {number}{scale}: it drops a digit "
                f"after the scale letter. Write {meant}"
            )
    return out


def names_in(text: str) -> set[str]:
    """Every element and parameter name a deck's own netlist lines define, upper case."""
    lines = text.split("\n")
    return set(deck_names(lines)) | set(deck_values(lines)[1])


def scaled(token: str, site: Site, factor: float) -> str:
    """A place's text at a corner: a number times the factor, or an expression wrapped in the factor
    (`{rtop}` is `{(rtop)*1.05}`, a bare `rtop` too), which ngspice evaluates where it stands."""
    if site.value is not None:
        return spice_text(site.value * factor)
    inner = token[1:-1] if token[0] in "{'" else token
    quote = ("'", "'") if token[0] == "'" else ("{", "}")
    return f"{quote[0]}({inner})*{spice_text(factor)}{quote[1]}"


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
            line = line[: site.start] + scaled(line[site.start : site.end], site, factor) + line[site.end :]
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


def ran_at(output: str) -> float:
    """The temperature a deck ran at as written: the one ngspice names for its analyses, or 27 C when
    it names none or more than one."""
    seen = {round(float(t), 2) for t in ANALYSIS_TEMP_RE.findall(output)}
    return seen.pop() if len(seen) == 1 else NOMINAL_TEMP


def other_temperatures(temperatures: list[float], written_at: float) -> list[float]:
    """The temperatures a corner must set: those the project names, without the one the deck as
    written already ran at. A deck that sets its own 40 C leaves 27 C to be run when the file names it."""
    return [t for t in sorted(set(temperatures)) if abs(t - written_at) > TEMP_MATCH]


def end_label(v: Varied, factor: float) -> str:
    return f"{v.name} {'+' if factor > 1 else '-'}{percent(abs(factor - 1))}"


def first_corners(
    temperatures: list[float], varied: list[Varied], written_at: float = NOMINAL_TEMP
) -> list[Corner]:
    """One range at a time: each temperature with the parts as written, then each part alone at both
    ends of its tolerance and half-way to each, at the deck's own temperature. The half-way runs see
    a measure that peaks inside a part's range, which neither end shows."""
    out = [
        Corner(f"t{t:g}", "temperature", f"{t:g} C", temp=t)
        for t in other_temperatures(temperatures, written_at)
    ]
    for v in varied:
        for mark, share in (("-", -1.0), ("+", 1.0), ("-h", -0.5), ("+h", 0.5)):
            factor = 1 + share * v.tol
            out.append(
                Corner(file_id(f"{v.name}{mark}"), "tolerance", end_label(v, factor), scale={v.key: factor})
            )
    return out


def refine_corners(
    bounded: dict[str, tuple[bool, bool]],
    nominal: dict[str, float],
    alone: list[tuple[Corner, dict[str, float]]],
    varied: list[Varied],
) -> list[Corner]:
    """The next runs for a measure that peaks inside a part's range: where a part moved alone gives a
    bounded measure its furthest value at neither end, 2 runs half-way between that point and its
    neighbours. Called again on the larger set of runs, it closes on the peak; it returns nothing for
    a measure that runs one way across each range, which is the usual case. `alone` holds the runs
    that moved 1 part, with their measures."""
    by_key = {v.key: v for v in varied}
    points: dict[str, dict[float, dict[str, float]]] = {v.key: {0.0: nominal} for v in varied}
    for corner, measures in alone:
        if len(corner.scale) == 1 and corner.temp is None:
            ((key, factor),) = corner.scale.items()
            if key in by_key:
                points[key][round((factor - 1) / by_key[key].tol, 6)] = measures
    asked: dict[tuple[str, float], Corner] = {}
    for measure in sorted(bounded):
        for side, wanted in zip(("min", "max"), bounded[measure], strict=True):
            if not wanted:
                continue
            for key, runs in points.items():
                seen = sorted((share, m[measure]) for share, m in runs.items() if measure in m)
                if len(seen) < 3:
                    continue
                values = [value for _, value in seen]
                top = min(values) if side == "min" else max(values)
                ends = (values[0], values[-1])
                scale = max(abs(v) for v in values) or 1.0
                if any(abs(top - end) <= 1e-9 * scale for end in ends):
                    continue  # an end is as far as any point between: the measure runs one way
                at = values.index(top)
                for a, b in ((seen[at - 1][0], seen[at][0]), (seen[at][0], seen[at + 1][0])):
                    share = round((a + b) / 2, 6)
                    if share not in runs and (key, share) not in asked:
                        v = by_key[key]
                        factor = 1 + share * v.tol
                        asked[(key, share)] = Corner(
                            file_id(f"{v.name}{share:+g}"),
                            "tolerance",
                            end_label(v, factor),
                            scale={key: factor},
                        )
    return list(asked.values())


def every_end(
    temperatures: list[float], varied: list[Varied], written_at: float = NOMINAL_TEMP
) -> list[Corner] | None:
    """Every combination of the ends: each part at the low or the high end of its tolerance, at the
    deck's own temperature and at each one the project names. None when that is more than
    EXHAUSTIVE_RUNS runs; then the worst case is a guess from the first corners (worst_corners)."""
    temps = [None, *other_temperatures(temperatures, written_at)]
    if not varied:
        return []
    if 2 ** len(varied) * len(temps) > EXHAUSTIVE_RUNS:
        return None
    out: list[Corner] = []
    for temp in temps:
        for ends in itertools.product((-1, 1), repeat=len(varied)):
            scale = {v.key: 1 + end * v.tol for v, end in zip(varied, ends, strict=True)}
            said = ([f"{temp:g} C"] if temp is not None else []) + [
                end_label(v, scale[v.key]) for v in varied
            ]
            out.append(Corner(f"e{len(out) + 1:03d}", "worst", ", ".join(said), temp=temp, scale=scale))
    return out


def sweep_corners(varied: list[Varied]) -> list[Corner]:
    """The runs that carry a resonance across its whole span along the side where it is strongest,
    for a deck that answers an overlap of the frequency plan. A resonance rises with L / C, so: every
    inductor at its high end with the capacitors stepped from low to high, then every capacitor at
    its low end with the inductors stepped from high to low. A step is SWEEP_STEP of a part's value,
    which moves the resonance by half as much. The worst-case runs put each part at an end, where the
    resonance has left the source; the coincidence lies between the ends."""
    coils = [v for v in varied if v.kind == "L"]
    caps = [v for v in varied if v.kind == "C"]
    if not coils or not caps:
        return []
    steps = max(2, math.ceil(2 * max(v.tol for v in [*coils, *caps]) / SWEEP_STEP))
    out: list[Corner] = []
    for fixed, end, moved in ((coils, 1, caps), (caps, -1, coils)):
        for n in range(steps + 1):
            share = -1 + 2 * n / steps
            scale = {v.key: 1 + end * v.tol for v in fixed} | {v.key: 1 + share * v.tol for v in moved}
            said = ", ".join(end_label(v, scale[v.key]) for v in varied if scale.get(v.key, 1) != 1)
            out.append(Corner(f"s{len(out) + 1:03d}", "sweep", said, scale=scale))
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
    deck: str,
    monte: dict | None,
    temperatures: list[float],
    varied: list[Varied],
    written_at: float = NOMINAL_TEMP,
) -> list[Corner]:
    """`runs` draws for one deck: each covered value evenly inside its tolerance, the temperature evenly
    inside its range. The seed and the deck's name fix the draws, so a run repeats."""
    if not monte or not (varied or temperatures):
        return []
    rng = random.Random(f"{monte['seed']}:{deck}")
    # The range is the one the project names. A single temperature has none, so its draws run from
    # the deck's own temperature to it.
    span = temperatures if len(set(temperatures)) > 1 else [*temperatures, written_at]
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
