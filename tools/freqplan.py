#!/usr/bin/env python3
"""freqplan — a project's frequency plan: what switches, what resonates, and where the two meet.

Two parts that switch at one frequency put their energy on one line of the spectrum, and a line that
lands on a resonance is amplified by it. A project's `sim/frequency-plan.json` names every periodic
source and every resonance a deck has measured; the SIM gate finds each place they meet and asks for
a deck that drives it and bounds the result:

    {
      "sources": [
        {"name": "heater PWM", "hz": 1000, "tolerance": 0.01, "source": "config.h LH_PWM_HZ; HSI 1 %"},
        {"name": "I2C clock", "hz": [100000, 400000], "source": "UM10204 Table 10"}
      ],
      "resonances": [
        {"name": "cell strips with C5", "hz": "pdn.f_peak", "q": "pdn.q_peak", "source": "sim/pdn.cir"}
      ],
      "harmonics": 10,
      "guard": 0.1,
      "overlaps": [
        {"between": ["I2C clock", "cell strips with C5"], "evidence": "pdn_ripple.v_ripple",
         "stimulus": "ICLK", "why": "the clock's edges at the peak move the rail 4 mV"}
      ]
    }

- A source's `hz` is one frequency, widened by `tolerance`, or its range.
- A resonance's `hz` and `q` name a deck's measure (`deck.measure`), taken at every corner the deck
  ran at, or are numbers. Its band reaches `guard` (a fraction) or 1/(2 Q), whichever is wider, past
  each end of that range.
- An overlap is a source whose harmonic (1 to `harmonics`) lies in a resonance's band, or two sources
  that can run at one frequency. The gate finds them; `overlaps` answers each with `evidence`, a
  bounded measure of a deck that drives the overlap, and `stimulus`, that deck's element for each
  source `between` names: it runs at the source's frequency with a harmonic in the band, or the two
  elements run at one frequency. Two sources whose harmonics alone coincide are no overlap of their
  own: each harmonic is held against every resonance.
- A periodic stimulus in any deck (a PULSE with a period, a SIN or SINE) is a source the plan names.
  One with no frequency to read (a period that is not a number, a PWL that repeats, an SFFM, an AM, a
  B source of `time`) is named as unread.

This module reads the file, reads a deck's stimuli, and judges; `tools/workcenter` supplies the
measures. Standard library only.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from itertools import takewhile
from pathlib import Path

from simcorners import netlist_lines, spice_number, stated

PLAN_FILE = "frequency-plan.json"
DEFAULT_HARMONICS = 10
DEFAULT_GUARD = 0.1
MAX_HARMONICS = 1000
TOP_KEYS = ("sources", "resonances", "harmonics", "guard", "overlaps")
SOURCE_KEYS = ("name", "hz", "tolerance", "source")
RESONANCE_KEYS = ("name", "hz", "q", "source")
OVERLAP_KEYS = ("between", "evidence", "stimulus", "why")
MEASURE_RE = re.compile(r"^[A-Za-z_]\w*\.[A-Za-z_]\w*$")
# A source's stimulus function as one word of its line, with the list written against it. ngspice 42
# ran each of these forms at the frequency `stimuli` reads from it: PULSE(...) in either case,
# `PULSE ...` without parentheses (a list of 6 before `AC 1` is one event), `PULSE (...)`, commas between
# arguments, `{vdd * 1}`, `{max(vdd,3)}` and `'vdd * 1'` as one argument, a list continued on a `+` line
# with a comment line or an empty one before it, SIN(...) and SINE(...), on a V and on an I source,
# inside a .subckt. It takes SFFM(...) and AM(...), and repeats a V source's PWL that has `r=0`, `r = 0`,
# `r 0` or `r` alone after its points, inside the parentheses or past them.
STIMULUS_RE = re.compile(r"\b(pulse|sine?|pwl|sffm|am)\b(\(.*)?", re.IGNORECASE)
REPEAT_RE = re.compile(r"r(=|$)", re.IGNORECASE)
# Where ngspice 42 ends a netlist line: at `;` or `//` anywhere, and at `$` after a space, a tab or a
# comma. `DC 5$ PULSE(...)` runs its PULSE.
COMMENT_RE = re.compile(r";|//|(?<=[\s,])\$")
TIME_RE = re.compile(r"\btime\b", re.IGNORECASE)
GROUPS = {"(": ")", "{": "}"}
RANGE_SLACK = 1e-3  # a deck's stimulus against a source's range, as a fraction
ALIGNED = 0.01  # two stimuli run at one frequency within this fraction
MAX_WIDTH = 0.9  # a band's half-width as a fraction of its frequency: below Q 0.56 nothing peaks


@dataclass
class Source:
    name: str
    low: float
    high: float


@dataclass
class Resonance:
    name: str
    hz: float | str  # a number, or the `deck.measure` that gives it
    q: float | str | None


@dataclass
class Overlap:
    between: tuple[str, str]
    evidence: str  # the `deck.measure` that bounds the result
    stimulus: tuple[str, ...]  # the deck's element that runs each source `between` names, in its order
    why: str


@dataclass
class Plan:
    sources: list[Source] = field(default_factory=list)
    resonances: list[Resonance] = field(default_factory=list)
    harmonics: int = DEFAULT_HARMONICS
    guard: float = DEFAULT_GUARD
    overlaps: list[Overlap] = field(default_factory=list)


def number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def said(entry: dict, key: str) -> str:
    """An entry's text for a key, or "" when it says nothing: absent, not text, or the template's
    own `fill: ...`."""
    return entry[key].strip() if stated(entry.get(key)) else ""


def read_plan(sim_dir: Path) -> tuple[Plan | None, list[str]]:
    """`sim_dir`/frequency-plan.json: (None, []) when the project has none, else (plan, problems). A
    problem is a line of the file the gate cannot act on."""
    path = sim_dir / PLAN_FILE
    if not path.is_file():
        return None, []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return Plan(), [f"{PLAN_FILE}: not JSON: {exc}"]
    if not isinstance(data, dict):
        return Plan(), [f"{PLAN_FILE}: not an object"]
    problems = [f"{PLAN_FILE}: unknown key {key!r}" for key in sorted(set(data) - set(TOP_KEYS))]
    plan = Plan()
    names: set[str] = set()

    def entries(key: str, keys: tuple[str, ...]) -> list[tuple[str, dict]]:
        block = data.get(key, [])
        if not isinstance(block, list):
            problems.append(f"{key}: not a list")
            return []
        out = []
        for n, entry in enumerate(block, start=1):
            where = f"{key}[{n}]"
            if not isinstance(entry, dict):
                problems.append(f"{where}: not an object")
                continue
            problems.extend(f"{where}: unknown key {k!r}" for k in sorted(set(entry) - set(keys)))
            out.append((where, entry))
        return out

    def named(where: str, entry: dict) -> str | None:
        name = said(entry, "name")
        if not name:
            problems.append(f"{where}: no name")
            return None
        if name in names:
            problems.append(f"{where}: the name {name!r} is used twice")
            return None
        names.add(name)
        if not said(entry, "source"):
            problems.append(f"{where} ({name}): no source: where the frequency comes from")
        return name

    for where, entry in entries("sources", SOURCE_KEYS):
        name = named(where, entry)
        hz, tol = entry.get("hz"), entry.get("tolerance", 0)
        if number(hz) and hz > 0:
            if not number(tol) or not 0 <= tol < 1:
                problems.append(f"{where}: tolerance {tol!r} is not a fraction from 0 to 1")
                continue
            low, high = hz * (1 - tol), hz * (1 + tol)
        elif (
            isinstance(hz, list) and len(hz) == 2 and all(number(v) and v > 0 for v in hz) and hz[0] <= hz[1]
        ):
            if "tolerance" in entry:
                problems.append(f"{where}: a range has its ends; tolerance goes with one frequency")
            low, high = float(hz[0]), float(hz[1])
        else:
            problems.append(f"{where}: hz {hz!r} is not a frequency in Hz or a [low, high] range")
            continue
        if name:
            plan.sources.append(Source(name, low, high))
    for where, entry in entries("resonances", RESONANCE_KEYS):
        name = named(where, entry)
        hz, q = entry.get("hz"), entry.get("q")
        if not ((number(hz) and hz > 0) or (isinstance(hz, str) and MEASURE_RE.match(hz))):
            problems.append(f"{where}: hz {hz!r} is not a frequency in Hz or a deck.measure")
            continue
        if q is not None and not ((number(q) and q > 0) or (isinstance(q, str) and MEASURE_RE.match(q))):
            problems.append(f"{where}: q {q!r} is not a number above 0 or a deck.measure")
            continue
        if name:
            plan.resonances.append(Resonance(name, hz, q))
    harmonics = data.get("harmonics", DEFAULT_HARMONICS)
    if isinstance(harmonics, bool) or not isinstance(harmonics, int) or not 1 <= harmonics <= MAX_HARMONICS:
        problems.append(f"harmonics: {harmonics!r} is not a count from 1 to {MAX_HARMONICS}")
    else:
        plan.harmonics = harmonics
    guard = data.get("guard", DEFAULT_GUARD)
    if not number(guard) or not 0 <= guard < 1:
        problems.append(f"guard: {guard!r} is not a fraction from 0 to 1")
    else:
        plan.guard = float(guard)
    for where, entry in entries("overlaps", OVERLAP_KEYS):
        between = entry.get("between")
        if not (isinstance(between, list) and len(between) == 2 and all(isinstance(b, str) for b in between)):
            problems.append(f"{where}: between is not two names")
            continue
        unknown = [b for b in between if b not in names]
        if unknown:
            problems.append(f"{where}: {', '.join(unknown)} is not a source or a resonance of the plan")
            continue
        evidence = said(entry, "evidence")
        if not MEASURE_RE.match(evidence):
            problems.append(f"{where}: evidence {entry.get('evidence')!r} is not a deck.measure")
            continue
        stimulus = entry.get("stimulus")
        stimulus = [stimulus] if isinstance(stimulus, str) else stimulus
        running = [b for b in between if any(s.name == b for s in plan.sources)]
        if not running:
            problems.append(f"{where}: between names no source")
            continue
        if not (isinstance(stimulus, list) and all(isinstance(e, str) and e.strip() for e in stimulus)):
            problems.append(f"{where}: no stimulus: the deck's element that runs each source")
            continue
        if len(stimulus) != len(running):
            problems.append(
                f"{where}: {len(stimulus)} stimulus for {len(running)} source: one element for each of "
                f"{', '.join(running) or 'none'}"
            )
            continue
        if not said(entry, "why"):
            problems.append(f"{where}: no why")
        plan.overlaps.append(
            Overlap(
                (between[0], between[1]), evidence, tuple(e.strip() for e in stimulus), said(entry, "why")
            )
        )
    if not plan.sources and not problems:
        problems.append(f"{PLAN_FILE}: names no source")
    return plan, problems


def uncommented(line: str) -> str:
    return COMMENT_RE.split(line, maxsplit=1)[0]


def split(text: str) -> list[str] | None:
    """`text` cut at its spaces and commas, with `{...}`, '...' and `(...)` whole inside the word they
    are written in: `PULSE(0 {max(vdd, 3)} 0)` is one word. None when one of them is left open, or
    closes what nothing opened."""
    words: list[str] = []
    word = ""
    closers: list[str] = []
    quoted = False
    for ch in text:
        if quoted:
            quoted = ch != "'"
        elif ch == "'":
            quoted = True
        elif ch in GROUPS:
            closers.append(GROUPS[ch])
        elif ch in GROUPS.values():
            if not closers or closers.pop() != ch:
                return None
        elif not closers and (ch.isspace() or ch == ","):
            if word:
                words.append(word)
            word = ""
            continue
        word += ch
    if quoted or closers:
        return None
    return [*words, word] if word else words


def stimuli(text: str) -> tuple[list[tuple[str, float]], list[str]]:
    """The periodic stimuli of a deck's own netlist: ([(element, Hz)], unread). A PULSE with a period
    and a SIN or SINE with a frequency are periodic; a PULSE without a period is one event, and so is a
    PWL without `r`. `unread` names each periodic source no frequency is read from: a period or a
    frequency written as something other than a number, a list that cannot be split, a PWL that
    repeats, an SFFM, an AM, and a B source whose expression holds `time`."""
    lines = text.split("\n")
    found: list[tuple[str, float]] = []
    unread: list[str] = []
    for i in netlist_lines(lines):
        kind = lines[i].strip()[0].upper()
        if kind not in "VIB":
            continue
        line = uncommented(lines[i])
        # A continuation line carries the rest of a long stimulus. Each line loses its own comment before
        # they are joined, and a comment line or an empty one between them does not end the source.
        j = i + 1
        while j < len(lines):
            s = lines[j].strip()
            if s.startswith("+"):
                line += " " + uncommented(s[1:])
            elif s and not s.startswith("*"):
                break
            j += 1
        # The function follows the element's name and its two nodes; a node may be called `sin`.
        tokens = line.split(None, 3)
        if len(tokens) < 4:
            continue
        element, rest = tokens[0], tokens[3]
        if kind == "B":
            if TIME_RE.search(rest):
                unread.append(element)
            continue
        words = split(rest)
        if words is None:
            if STIMULUS_RE.search(rest):
                unread.append(element)
            continue
        hits = ((n, m) for n, w in enumerate(words) if (m := STIMULUS_RE.fullmatch(w)))
        at, m = next(hits, (0, None))
        if m is None:
            continue
        name, listed = m.group(1).lower(), m.group(2)
        after = words[at + 1 :]
        if listed is None and after and after[0].startswith("("):
            listed, after = after[0], after[1:]
        if listed is None:
            # Without parentheses the list runs to `AC` or `DC`, or to the end of the line.
            args = list(takewhile(lambda w: w.lower() not in ("ac", "dc"), after))
        else:
            args = split(listed[1:-1]) if listed.endswith(")") else None
        if args is None or name in ("sffm", "am"):
            unread.append(element)
        elif name == "pwl":
            if any(REPEAT_RE.match(w) for w in (*args, *after)):
                unread.append(element)
        else:
            index = 6 if name == "pulse" else 2
            if len(args) <= index:
                continue
            value = spice_number(args[index])
            if value is None:
                unread.append(element)
            elif value > 0:
                found.append((element, 1 / value if index == 6 else value))
    return found, unread


def hertz(value: float) -> str:
    for scale, unit in ((1e9, "GHz"), (1e6, "MHz"), (1e3, "kHz")):
        if value >= scale:
            return f"{value / scale:.4g} {unit}"
    return f"{value:.4g} Hz"


def span(low: float, high: float) -> str:
    return hertz(low) if high - low <= 1e-9 * high else f"{hertz(low)} to {hertz(high)}"


def meet(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def inside(hz: float, source: Source) -> bool:
    """Whether a deck's stimulus runs at a source's frequency."""
    return source.low * (1 - RANGE_SLACK) <= hz <= source.high * (1 + RANGE_SLACK)


def check_plan(
    plan: Plan,
    values: dict[str, tuple[float, float]],
    bounded: set[str],
    deck_stimuli: dict[str, list[tuple[str, float]]],
) -> dict:
    """Judge a plan against a run: {"failures", "warnings", "bands", "overlaps"}.

    `values` maps each `deck.measure` to its least and greatest value over the corners the deck ran at;
    `bounded` holds the measures an expect file bounds for the design; `deck_stimuli` maps each deck to
    its periodic stimuli. A failure is an overlap the plan does not answer, an answer that proves
    nothing, an answer to an overlap that is gone, a resonance no deck measures, or a deck's stimulus
    the plan does not name."""
    failures: list[str] = []
    warnings: list[str] = []
    sources = {s.name: s for s in plan.sources}

    # Each resonance's band: its frequency over the corners, widened by the guard or by 1/(2 Q).
    bands: dict[str, tuple[float, float]] = {}
    shown: list[dict] = []
    for r in plan.resonances:
        if isinstance(r.hz, str):
            if r.hz not in values:
                failures.append(f"resonance {r.name}: {r.hz} is not measured by its deck")
                continue
            low, high = values[r.hz]
        else:
            low = high = float(r.hz)
        q = None
        if isinstance(r.q, str):
            if r.q not in values:
                failures.append(f"resonance {r.name}: {r.q} is not measured by its deck")
                continue
            q = values[r.q][0]  # the lowest Q is the widest band
        elif r.q is not None:
            q = float(r.q)
        if low <= 0 or (q is not None and q <= 0):
            failures.append(f"resonance {r.name}: a frequency or Q of 0 or less is no resonance")
            continue
        width = min(max(plan.guard, 1 / (2 * q)) if q else plan.guard, MAX_WIDTH)
        bands[r.name] = (low * (1 - width), high * (1 + width))
        shown.append({"name": r.name, "hz": [low, high], "q": q, "band": list(bands[r.name])})

    # The overlaps the run shows: a source's harmonic in a band, a source on another's harmonic.
    seen: dict[frozenset[str], str] = {}
    for s in plan.sources:
        for name, band in bands.items():
            orders = [n for n in range(1, plan.harmonics + 1) if meet((s.low * n, s.high * n), band)]
            if orders:
                n = orders[0]
                which = "frequency" if n == 1 else f"harmonic {n}"
                seen[frozenset((s.name, name))] = (
                    f"{s.name}'s {which} ({span(s.low * n, s.high * n)}) is in the band of {name} "
                    f"({span(*band)})"
                )
    for i, a in enumerate(plan.sources):
        for b in plan.sources[i + 1 :]:
            if meet((a.low, a.high), (b.low, b.high)):
                seen[frozenset((a.name, b.name))] = (
                    f"{a.name} ({span(a.low, a.high)}) and {b.name} ({span(b.low, b.high)}) can run at "
                    "one frequency"
                )

    # Each answer names an overlap the run shows, and its evidence drives that overlap.
    answered: set[frozenset[str]] = set()
    for o in plan.overlaps:
        pair = frozenset(o.between)
        both = " and ".join(o.between)
        deck = o.evidence.split(".")[0]
        if pair not in seen:
            failures.append(f"overlap {both}: the run shows none; remove the answer")
            continue
        answered.add(pair)
        if o.evidence not in values:
            failures.append(f"overlap {both}: {o.evidence} is not measured by its deck")
            continue
        if o.evidence not in bounded:
            failures.append(f"overlap {both}: {o.evidence} has no bound in its expect file")
            continue
        driven = {element.upper(): hz for element, hz in deck_stimuli.get(deck, [])}
        orders = range(1, plan.harmonics + 1)
        named = [sources[n] for n in o.between if n in sources]
        band = next((bands[n] for n in o.between if n in bands), None)
        # Each source runs from the element the answer names, at that source's frequency.
        runs: list[float] = []
        for s, element in zip(named, o.stimulus, strict=True):
            hz = driven.get(element.upper())
            if hz is None:
                failures.append(f"overlap {both}: sim/{deck}.cir has no periodic stimulus {element}")
            elif not inside(hz, s):
                failures.append(
                    f"overlap {both}: {element} runs at {hertz(hz)}, outside {s.name} ({span(s.low, s.high)})"
                )
            else:
                runs.append(hz)
        if len(runs) < len(named):
            continue
        if len(named) == 1 and band:
            # The source, run so that one of its harmonics is inside the resonance's band.
            if not any(band[0] <= n * runs[0] <= band[1] for n in orders):
                failures.append(
                    f"overlap {both}: {o.stimulus[0]} at {hertz(runs[0])} has no harmonic in the band "
                    f"({span(*band)})"
                )
        elif len(named) == 2:
            # Both sources, each from its own element, at one frequency.
            fa, fb = runs
            if o.stimulus[0].upper() == o.stimulus[1].upper():
                failures.append(f"overlap {both}: one element, {o.stimulus[0]}, cannot run both sources")
            elif abs(fa - fb) > ALIGNED * fb:
                failures.append(
                    f"overlap {both}: {o.stimulus[0]} at {hertz(fa)} and {o.stimulus[1]} at {hertz(fb)} "
                    "do not run at one frequency"
                )
    for pair, text in sorted(seen.items(), key=lambda kv: kv[1]):
        if pair not in answered:
            failures.append(f"{text}: no overlap answers it with a deck that drives it")

    # Every periodic stimulus a deck drives is a source the plan names.
    for deck in sorted(deck_stimuli):
        for element, hz in deck_stimuli[deck]:
            if not any(inside(hz, s) for s in plan.sources):
                failures.append(
                    f"sim/{deck}.cir drives {element} at {hertz(hz)}, which the plan does not name"
                )
    if plan.sources and not plan.resonances:
        warnings.append(f"{PLAN_FILE} names no resonance: no deck has looked for one with an .ac analysis")
    return {
        "failures": failures,
        "warnings": warnings,
        "sources": [{"name": s.name, "hz": [s.low, s.high]} for s in plan.sources],
        "bands": shown,
        "overlaps": sorted(seen.values()),
    }
