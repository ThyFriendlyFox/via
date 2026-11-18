"""A part's junction temperature at every corner of the SIM gate (`sim/thermal.json`).

A project names each part that dissipates power, its part number, and the measure of a deck that
prints that power. The part's facts (the facts `workcenter ratings` reads) give its thermal figures,
the JEDEC board each was measured on and its greatest junction temperature, with their pages; the
project's rating pack gives the derated limit. For every run the gate judged, the deck as written and
each corner ngspice finished at its own temperature, the junction is the run's temperature as the
ambient plus the figure times the power: TJ = TA + RthetaJA x power (TI SPRA953D, section 1.1,
equation 1, page 2).

That sum is an estimate on the datasheet's test board, not on the project's board. SPRA953D calls its
use for a system board a misapplication with erroneous results (section 1.1, page 2): the test board
is the heat sink, and RthetaJA changes with it. A JEDEC 2s2p board gives a best case, a 1s board a
typical one (section 1.2, page 3). EIA/JESD51 defines how RthetaJA is measured, not this estimate.
So every judged part carries `assumes`, which names the board of each figure it used, and a figure
whose board the facts do not name holds no part.

Where the project states the case, the board or the package top's temperature at a run's ambient
(`from`: measured, or computed as `workcenter copper` computes a board), the junction there is that
temperature plus the figure the project names times the power (SPRA953D, equations 4, 8 and 9), and
the line names the stated temperature's source. A run or a corner the gate could not judge leaves
the part not held and named as not judged.

Standard library only, as the CLI is. No engine runs here: `tools/workcenter` runs the decks.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import ratings
from simcorners import TEMP_MATCH

# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {
    "ti-spra953d": (
        "section 1.1, equation 1, page 2; section 1.2, page 3; section 2.2, equation 4, page 7; section 3, "
        "equation 8, page 8; table 3-1, note 11, page 9; section 4, figure 4-1, page 10; section 5.1, "
        "equation 9, page 11"
    ),
    "ecss-q-st-30-11c-rev2": "clause 3.2, page 12",
}
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
# The temperature each of those figures starts from, as a project states it in `from`.
STATED = {"theta_jc": "case", "theta_jb": "board", "psi_jt": "package top", "psi_jb": "board"}
# How each of them gives the junction, and where the method stands.
METHOD = {
    "theta_jc": (
        "TJ = TC + theta_jc x power puts all of the power through the case, so the junction it gives is "
        "above the real one in a plastic package (SPRA953D, section 2.2, equation 4, page 7; "
        "ECSS-Q-ST-30-11C Rev.2, clause 3.2, page 12)"
    ),
    "theta_jb": (
        "TJ = TB + theta_jb x power puts all of the power through the board, which takes 75 % to 95 % of "
        "it, so the junction it gives is above the real one (SPRA953D, section 4, figure 4-1, page 10; "
        "section 5.1, page 11)"
    ),
    "psi_jt": (
        "TJ = TC + psi_jt x power, TC the package top's temperature (SPRA953D, section 3, equation 8, page 8)"
    ),
    "psi_jb": "TJ = T(PCB) + psi_jb x power (SPRA953D, section 5.1, equation 9, page 11)",
}
MEASURE_RE = re.compile(r"([A-Za-z_]\w*)\.([A-Za-z_]\w*)")
WRITTEN = "as written"  # the label of the run of a deck as written


@dataclass(frozen=True)
class Stated:
    """A case, board or top temperature the project states: the figure that starts from it, the
    temperature at each ambient in C, and where the number comes from."""

    figure: str
    celsius: dict[float, float]
    source: str


@dataclass(frozen=True)
class Part:
    ref: str
    mpn: str
    deck: str
    measure: str
    source: str
    stated: Stated | None = None


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
            entry = ratings._keys(where, raw, ("mpn", "watts", "source"), ("from",))
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
            source = ratings._text(f"{where}: source", entry["source"])
            stated = _stated(f"{where}: from", entry["from"]) if "from" in entry else None
            parts[ref] = Part(ref, mpn, deck, measure, source, stated)
    except ratings.Refusal as exc:
        message = str(exc)
        return None, [message if message.startswith(PLAN_FILE) else f"{PLAN_FILE}: {message}"]
    return Plan(pack, parts), []


def _stated(where: str, raw: object) -> Stated:
    """A part's `from`: {"figure": "psi_jb", "celsius": {"85": 101.5}, "source": "..."}."""
    data = ratings._keys(where, raw, ("figure", "celsius", "source"))
    figure = data["figure"]
    if not isinstance(figure, str) or figure not in STATED:
        raise ratings.Refusal(
            f"{where}: figure: `{figure}` is no figure from a stated temperature; they are "
            f"{', '.join(STATED)}"
        )
    temps = data["celsius"]
    if not isinstance(temps, dict) or not temps:
        raise ratings.Refusal(
            f'{where}: celsius: 1 ambient at least is asked, as {{"85": 101.5}}: the {STATED[figure]} '
            "temperature at that ambient, in C"
        )
    celsius: dict[float, float] = {}
    for at, value in temps.items():
        try:
            ambient = float(at)
        except ValueError:
            ambient = math.nan
        if not math.isfinite(ambient):
            raise ratings.Refusal(f"{where}: celsius: `{at}` is no ambient in C")
        celsius[ambient] = ratings._number(f"{where}: celsius: {at}", value, -273.15)
    return Stated(figure, celsius, ratings._text(f"{where}: source", data["source"]))


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


def celsius(temperatures: list[float]) -> str:
    """Temperatures as a line names them: `-20 C and 85 C`, `25 C, 60 C and 85 C`."""
    said = [f"{t:g} C" for t in sorted(temperatures)]
    return said[0] if len(said) == 1 else f"{', '.join(said[:-1])} and {said[-1]}"


def _at(label: str) -> str:
    return label if label == WRITTEN else f"at {label}"


def _unjudged(name: str, entry: ratings.Facts, part: Part) -> str | None:
    """Why a part with facts is not judged at all, or None when its facts give RthetaJA or the figure
    the project's stated temperature starts from."""
    term = entry.data.get("thermal")
    if term is None:
        return (
            f"{name} not judged: its facts ({entry.where}) give no thermal figure: write `thermal` from "
            "the datasheet's thermal table"
        )
    if part.stated:
        figure = part.stated.figure
        if figure not in term:
            return (
                f"{name} not judged: sim/thermal.json names {figure} in `from`, and its facts "
                f"({entry.where}) give no {figure}"
            )
        return None
    if "theta_ja" in term:
        return None
    given = [f for f in FIGURES if f in term]
    said = [f"{given[0]} gives the junction from {FROM[given[0]]}"] + [
        f"{g} from {FROM[g]}" for g in given[1:]
    ]
    either = {1: "it", 2: "either"}.get(len(given), "one")
    return (
        f"{name} not judged: its facts give {' and '.join(given)}, and no theta_ja: "
        f"{', and '.join(said)}; state {either} in sim/thermal.json's `from`, with its source"
    )


def _board(figure: str, term: dict) -> str:
    """Where a figure was measured, as a failure line says it."""
    boards = term.get("boards", {})
    if figure not in boards:
        return f"{figure} on no board its facts name"
    return f"{figure} on {ratings.BOARDS[boards[figure]]} ({ratings._p(boards['page'])})"


def assumes(figure: str, term: dict) -> str:
    """What a junction from 1 figure rests on: the board it was measured on (SPRA953D, table 3-1, note
    11, page 9) and the method (sections 1.1 to 5.1)."""
    value, boards = term[figure], term.get("boards", {})
    if figure == "theta_ja":
        if figure not in boards:
            return (
                f"theta_ja {value:g} C/W: its facts name no JEDEC board it was measured on, so it holds no "
                "part; a board unlike the test board changes it (SPRA953D, section 1.1, page 2)"
            )
        return (
            f"theta_ja {value:g} C/W was measured on {ratings.BOARDS[boards[figure]]} "
            f"({ratings._p(boards['page'])}): a 2s2p board gives a best case and a 1s0p board a typical one "
            "(SPRA953D, section 1.2, page 3); a board unlike the test board changes it (section 1.1, page 2)"
        )
    on = (
        f"was measured on {ratings.BOARDS[boards[figure]]} ({ratings._p(boards['page'])})"
        if figure in boards
        else "is on no JEDEC board its facts name, so it holds no part"
    )
    return f"{figure} {value:g} C/W {on}: {METHOD[figure]}"


def _how(part: Part, term: dict, ambient: float) -> tuple[str, float] | None:
    """The figure a run's junction comes from and the temperature it starts from: the project's stated
    one at that ambient, else RthetaJA from the ambient, else None."""
    if part.stated:
        for at, temp in part.stated.celsius.items():
            if abs(at - ambient) <= TEMP_MATCH:
                return part.stated.figure, temp
    if "theta_ja" in term:
        return "theta_ja", ambient
    return None


def _more(count: int) -> str:
    return f" (and {count} more run{'s' if count > 1 else ''})" if count else ""


def judge(
    plan: Plan,
    runs: dict[str, list[tuple[str, float | str, dict[str, float]]] | None],
    facts: list[ratings.Facts],
    pack: ratings.Pack,
    unrun: dict[str, str] | None = None,
) -> dict:
    """Each part of the plan at each run of its deck: {"failures", "not_judged", "parts"}.

    `runs` maps a deck to its runs, each (label, ambient in C, measures), the run as written first, or
    to None when the deck did not run to its end. An ambient that is text is the reason the run's
    temperature is not known: that run is not judged. `unrun` maps a deck to the reason its corners
    of sim/corners.json were not run. A part with a run or corners not judged is never held: it is
    named as not judged, and fails only on the runs judged. A part past its limit fails on 1 line: the
    worst run, how many more are past the limit, the sum, and where each number stands."""
    unrun = unrun or {}
    failures: list[str] = []
    not_judged: list[str] = []
    parts: dict[str, dict] = {}
    for ref, part in plan.parts.items():
        name = f"thermal: {ref} ({part.mpn})"
        entry, why = _facts_of(facts, part.mpn)
        if entry is None:
            not_judged.append(f"{name} not judged: {why}")
            continue
        why = _unjudged(name, entry, part)
        if why:
            not_judged.append(why)
            continue
        ran = runs.get(part.deck)
        if ran is None:
            not_judged.append(f"{name} not judged: its deck {part.deck} did not run to its end")
            continue
        term = entry.data["thermal"]
        rated = term["junction_max"]
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
        unknown = [(label, ambient) for label, ambient, _ in ran if isinstance(ambient, str)]
        if unknown:
            more = len(unknown) - 1
            not_judged.append(
                f"{name} not judged {_at(unknown[0][0])}"
                + (f" (and {more} more run{'s' if more > 1 else ''})" if more else "")
                + f": {unknown[0][1]}, so the ambient of the run that printed {measure} is not known"
            )
        if part.deck in unrun:
            not_judged.append(f"{name} not judged at the corners of sim/corners.json: {unrun[part.deck]}")
        rows, unstated = [], []
        for label, ambient, m in ran:
            if isinstance(ambient, str):
                continue
            how = _how(part, term, ambient)
            if how is None:
                unstated.append(label)
                continue
            figure, start = how
            watts = m[part.measure]
            row = {"run": label, "ambient": ambient, "watts": watts, "figure": figure}
            if figure != "theta_ja":
                row["from"] = start
            rows.append({**row, "junction": start + term[figure] * watts})
        if unstated:
            not_judged.append(
                f"{name} not judged {_at(unstated[0])}{_more(len(unstated) - 1)}: sim/thermal.json states "
                f"its {STATED[part.stated.figure]} temperature at {celsius(list(part.stated.celsius))} "
                "ambient only, and its facts give no theta_ja"
            )
        if part.stated:
            idle = [
                t
                for t in part.stated.celsius
                if not any(r.get("from") is not None and abs(r["ambient"] - t) <= TEMP_MATCH for r in rows)
            ]
            if idle:
                not_judged.append(
                    f"{name}: sim/thermal.json states its {STATED[part.stated.figure]} temperature at "
                    f"{celsius(idle)} ambient, where no run of {part.deck} stands"
                )
        if not rows:
            continue
        used = list(dict.fromkeys(r["figure"] for r in rows))
        unboarded = [f for f in used if f not in term.get("boards", {})]
        not_judged += [
            f"{name} not held: its facts ({entry.where}) name no JEDEC board for {f}: write `boards` in "
            "`thermal` from the datasheet's thermal table"
            for f in unboarded
        ]
        read_once = [f"the facts {entry.where}"] if not entry.read_twice else []
        if rule is not None and rule.second_reader == "no":
            read_once.append(f"{pack.name} rule {rule.id}")
        worst = max(rows, key=lambda r: r["junction"])
        over = [r for r in rows if r["junction"] > most]
        parts[ref] = {
            "mpn": part.mpn,
            "facts": entry.where,
            "theta_ja": term.get("theta_ja"),
            "figures": {f: term[f] for f in used},
            "boards": {f: term.get("boards", {}).get(f) for f in used},
            "junction_max": rated,
            "limit": most,
            "limit_source": said,
            "assumes": "; ".join(assumes(f, term) for f in used),
            "read_once": read_once,
            "written": rows[0] if rows[0]["run"] == WRITTEN else None,
            "worst": worst,
            "runs": len(rows),
            # Held only when every run and every corner was judged, each on a figure whose board the
            # facts name; None when some were not.
            "held": False
            if over
            else (None if unknown or part.deck in unrun or unstated or unboarded else True),
        }
        if over:
            figure = worst["figure"]
            start = (
                f"{worst['ambient']:g} C"
                if figure == "theta_ja"
                else f"{STATED[figure]} {worst['from']:g} C at {worst['ambient']:g} C ambient "
                f"({part.stated.source})"
            )
            more = len(over) - 1
            failures.append(
                f"{name} at {worst['ambient']:g} C ambient: junction {worst['junction']:.5g} C, over "
                f"{most:g} C ({worst['run']}"
                + (f", and {more} more run{'s' if more > 1 else ''}" if more else "")
                + f"): {start} + {term[figure]:g} C/W x {worst['watts']:.5g} W of {measure}, {figure} and "
                f"junction_max of {entry.source}, {ratings._p(term['page'])}, {_board(figure, term)}; "
                f"limit {said}"
            )
    return {"failures": failures, "not_judged": not_judged, "parts": parts}
