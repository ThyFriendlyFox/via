"""A part's junction temperature at every corner of the SIM gate (`sim/thermal.json`).

A project names each part that dissipates power, its part number, and the measure of a deck that
prints that power. The part's facts (the facts `workcenter ratings` reads) give its thermal figure and
its greatest junction temperature, with their pages; the project's rating pack gives the derated
limit. For every run the gate judged, the deck as written and each corner ngspice finished at its own
temperature, the junction is the run's temperature as the ambient plus the figure times the power:
TJ = TA + RthetaJA x power (TI SPRA953D, section 1.1, equation 1, page 2, from EIA/JESD51-1 and -2).

Standard library only, as the CLI is. No engine runs here: `tools/workcenter` runs the decks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import ratings

PLAN_FILE = "thermal.json"
JUNCTION = ratings.JUNCTION
FIGURES = ratings.FIGURES
# The figures that give the junction from a temperature other than the ambient's, which no deck gives,
# and where each one's method stands.
FROM = {
    "theta_jc": "the case's temperature (ECSS-Q-ST-30-11C Rev.2, clause 3.2, page 12; SPRA953D, section 2)",
    "theta_jb": "the board's temperature (SPRA953D, section 4)",
    "psi_jt": "the package top's temperature (SPRA953D, section 3)",
    "psi_jb": "the board's temperature (SPRA953D, section 5)",
}
MEASURE_RE = re.compile(r"([A-Za-z_]\w*)\.([A-Za-z_]\w*)")
WRITTEN = "as written"  # the label of the run of a deck as written


@dataclass(frozen=True)
class Part:
    ref: str
    mpn: str
    deck: str
    measure: str
    source: str


@dataclass(frozen=True)
class Plan:
    pack: str
    parts: dict[str, Part]


def read_plan(sim_dir: Path, decks: list[str]) -> tuple[Plan | None, list[str]]:
    """The project's sim/thermal.json: (plan, problems). No file is no plan and no problem."""
    path = sim_dir / PLAN_FILE
    if not path.is_file():
        return None, []
    try:
        data = ratings._keys(PLAN_FILE, ratings._json(path), ("pack", "parts"))
        pack = ratings._text(f"{PLAN_FILE}: pack", data["pack"])
        raw_parts = ratings._object(f"{PLAN_FILE}: parts", data["parts"], "part")
        if not raw_parts:
            raise ratings.Refusal(f"{PLAN_FILE}: parts: 1 part at least is asked")
        parts = {}
        for ref, raw in raw_parts.items():
            where = f"{PLAN_FILE}: parts: {ref}"
            entry = ratings._keys(where, raw, ("mpn", "watts", "source"))
            watts = ratings._text(f"{where}: watts", entry["watts"])
            m = MEASURE_RE.fullmatch(watts)
            if not m:
                raise ratings.Refusal(f"{where}: watts: `{watts}` is no deck.measure, as ldo.p_u1")
            deck, measure = m.groups()
            if deck not in decks:
                raise ratings.Refusal(
                    f"{where}: watts: `{deck}` is no deck of sim/; the decks are {', '.join(decks)}"
                )
            if measure != measure.lower():
                raise ratings.Refusal(
                    f"{where}: watts: ngspice prints a name in lower case, so `{measure}` is never measured"
                )
            mpn = ratings._text(f"{where}: mpn", entry["mpn"])
            parts[ref] = Part(ref, mpn, deck, measure, ratings._text(f"{where}: source", entry["source"]))
    except ratings.Refusal as exc:
        message = str(exc)
        return None, [message if message.startswith(PLAN_FILE) else f"{PLAN_FILE}: {message}"]
    return Plan(pack, parts), []


def kind_of(facts: ratings.Facts) -> str:
    """A part's kind as a pack's rule names it: an integrated circuit by its family, `ic.linear`."""
    return f"ic.{facts.data['family']}" if facts.kind == "ic" else facts.kind


def rule_for(pack: ratings.Pack, kind: str) -> ratings.JunctionRule | None:
    return pack.junction_rule(kind)


def limit(rule: ratings.JunctionRule, junction_max: float) -> tuple[float, str]:
    """The derated limit of a junction rated `junction_max`, and how it was found: the least of the
    terms the rule names."""
    terms = []
    if rule.celsius is not None:
        terms.append((rule.celsius, f"{rule.celsius:g} C"))
    if rule.share is not None:
        terms.append((rule.share * junction_max, f"{rule.share:g} x {junction_max:g} C"))
    if rule.below is not None:
        terms.append((junction_max - rule.below, f"{junction_max:g} C - {rule.below:g} C"))
    value = min(t[0] for t in terms)
    if len(terms) == 1:
        return value, f"{value:g} C"
    names = [t[1] for t in terms]
    return value, f"{value:g} C, the least of {', '.join(names[:-1])} and {names[-1]}"


def _facts_of(facts: list[ratings.Facts], mpn: str) -> tuple[ratings.Facts | None, str]:
    """The entry that names a part number most closely, as `ratings` finds it: the number before a
    pattern. 2 entries that name it as closely leave the part unjudged."""
    close = [(f.speaks_of(mpn, "", ""), f) for f in facts]
    best = max((c for c, _ in close), default=0)
    if best == 0:
        return None, f"no facts entry names {mpn}: write one from its datasheet (the ratings skill)"
    named = [f for c, f in close if c == best]
    if len(named) > 1:
        return None, f"{len(named)} facts entries name {mpn} as closely: {', '.join(f.where for f in named)}"
    return named[0], ""


def _at(label: str) -> str:
    return label if label == WRITTEN else f"at {label}"


def _unjudged(name: str, entry: ratings.Facts) -> str | None:
    """Why a part with facts is not judged, or None when its facts give RthetaJA."""
    term = entry.data.get("thermal")
    if term is None:
        return (
            f"{name} not judged: its facts ({entry.where}) give no thermal figure: write `thermal` from "
            "the datasheet's thermal table"
        )
    if "theta_ja" in term:
        return None
    given = [f for f in FIGURES if f in term]
    said = [f"{given[0]} gives the junction from {FROM[given[0]]}"] + [
        f"{g} from {FROM[g]}" for g in given[1:]
    ]
    either = {1: "it", 2: "either"}.get(len(given), "any")
    return (
        f"{name} not judged: its facts give {' and '.join(given)}, and no theta_ja: "
        f"{', and '.join(said)}; no deck gives {either}"
    )


def judge(
    plan: Plan,
    runs: dict[str, list[tuple[str, float, dict[str, float]]] | None],
    facts: list[ratings.Facts],
    pack: ratings.Pack,
) -> dict:
    """Each part of the plan at each run of its deck: {"failures", "not_judged", "parts"}.

    `runs` maps a deck to its runs, each (label, ambient in C, measures), the run as written first, or
    to None when the deck did not run to its end. A part past its limit fails on 1 line: the worst run,
    how many more are past the limit, the sum, and where each number stands."""
    failures: list[str] = []
    not_judged: list[str] = []
    parts: dict[str, dict] = {}
    for ref, part in plan.parts.items():
        name = f"thermal: {ref} ({part.mpn})"
        entry, why = _facts_of(facts, part.mpn)
        if entry is None:
            not_judged.append(f"{name} not judged: {why}")
            continue
        why = _unjudged(name, entry)
        if why:
            not_judged.append(why)
            continue
        ran = runs.get(part.deck)
        if ran is None:
            not_judged.append(f"{name} not judged: its deck {part.deck} did not run to its end")
            continue
        term = entry.data["thermal"]
        theta, rated = term["theta_ja"], term["junction_max"]
        kind = kind_of(entry)
        rule = rule_for(pack, kind)
        if rule is None:
            most, said = (
                rated,
                f"{rated:g} C, the part's own rating: {pack.name} has no junction rule for {kind}",
            )
        else:
            most, how = limit(rule, rated)
            said = f"{how} ({pack.name}, {rule.where})"
        measure = f"{part.deck}.{part.measure}"
        missing = [label for label, _, measures in ran if part.measure not in measures]
        if missing:
            more = len(missing) - 1
            failures.append(
                f"thermal: {ref}: {measure} is not printed {_at(missing[0])}"
                + (f" (and {more} more run{'s' if more > 1 else ''})" if more else "")
                + ": its junction there is not known"
            )
            continue
        negative = [(label, m[part.measure]) for label, _, m in ran if m[part.measure] < 0]
        if negative:
            label, watts = negative[0]
            failures.append(
                f"thermal: {ref}: {measure} is {watts:g} W {_at(label)}: a part's dissipation is not "
                "under 0; read the sign of the deck's sum"
            )
            continue
        rows = [
            {
                "run": label,
                "ambient": ambient,
                "watts": m[part.measure],
                "junction": ambient + theta * m[part.measure],
            }
            for label, ambient, m in ran
        ]
        worst = max(rows, key=lambda r: r["junction"])
        over = [r for r in rows if r["junction"] > most]
        parts[ref] = {
            "mpn": part.mpn,
            "facts": entry.where,
            "theta_ja": theta,
            "junction_max": rated,
            "limit": most,
            "limit_source": said,
            "written": rows[0],
            "worst": worst,
            "runs": len(rows),
            "held": not over,
        }
        if over:
            more = len(over) - 1
            failures.append(
                f"{name} at {worst['ambient']:g} C ambient: junction {worst['junction']:.5g} C, over "
                f"{most:g} C ({worst['run']}"
                + (f", and {more} more run{'s' if more > 1 else ''}" if more else "")
                + f"): {worst['ambient']:g} C + {theta:g} C/W x {worst['watts']:.5g} W of {measure}, "
                f"theta_ja and junction_max of {entry.source}, {ratings._p(term['page'])}; limit {said}"
            )
    return {"failures": failures, "not_judged": not_judged, "parts": parts}
