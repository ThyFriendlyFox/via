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
typical one, and as much as a 50 % RthetaJA variation comes of that choice alone (section 1.2, page 3).
EIA/JESD51 defines how RthetaJA is measured, not this estimate. So every judged part carries
`assumes`, which names the board of each figure it used, and a figure whose board the facts do not name
holds no part. A part held on theta_ja on the 2s2p board is held on SPRA953D's best-case estimate, not
a bound, with no margin: its record (`no_margin`) and its line say so.

Where the project states the case, the board or the package top's temperature at a run's ambient
(`from`: measured, or computed as `workcenter copper` computes a board), the junction there is that
temperature plus the figure the project names times the power (SPRA953D, equations 4, 8 and 9); the
part's record (`stated`) and its line name the stated temperature and its source, and, where the facts
give theta_ja, the junction theta_ja gives at those runs and its board (`theta_ja_gives`). A stated
temperature not above its ambient, or a figure the facts lack, is set aside; a junction from theta_jb,
or under the one theta_ja gives on the 2s2p board, holds no part. The junction theta_ja gives on the 2s2p
board is SPRA953D's best-case estimate, not a bound; it is the floor the gate holds a stated
temperature's junction to, the only check on a number the project states. With theta_ja on 1s0p, on no
board, or no theta_ja, the stated temperature is checked against no board and holds no part. Equation 4
with a measured case gives a junction above the real one (section 2.2, page 7), but the gate cannot tell
a measured case from a written one, so a case is held to the floor too. A case the project states on a
heat sink (`heat_sink`, theta_jc only) is what RthetaJC was devised for (SPRA953D, section 2, page 6):
the sink is named with its Rtheta(CS) and Rtheta(SA), each above 0 C/W, and their source. Equation 5,
TJ = TA + (RthetaJC + Rtheta(CS) + Rtheta(SA)) x power (section 2.2, page 7), needs only the run's
ambient and the sink's 2 resistances, so it is worked at every run whose ambient is known: the greater
of equation 5 and what judged the run before it (equation 4 from a stated case, in place of the floor,
or theta_ja where no case is stated) judges, and a junction over the limit by equation 5 fails whatever
else is set aside. The record (`equation`) and the line name the equation that gave the worst junction,
with its section and page; a run equation 5 judged names theta_jc as its figure, and keeps what equation 1
or 4 gave there under `beside`, with the stated case it started from. Equation 6, RthetaJA in parallel
with that sum, is not taken: SPRA953D calls it more accurate only if RthetaJA is known for the system
configuration (section 2.2, page 7), and the facts' RthetaJA is the test board's, a misapplication on
a system board (section 1.1, page 2) and on 2s2p a best case (section 1.2, page 3). A run or a corner
the gate could not judge leaves the part not held and named as not judged.

The gate asks for the parts itself (`asked`): every part of the board whose facts carry `thermal`, a
junction_max and 1 figure at least, can get hot, and a part of them that sim/thermal.json does not name
is not judged, on 1 line that names its figures and the row to write. No power is guessed: a part is
asked for because its facts carry a thermal figure. A row whose part number is not the board part's
fails, as judge() reads the facts by the row's number; a part with no number and no facts entry whose
pins are those of an entry with a figure may be that part, and is not judged. A part whose entry names
it by its symbol alone cannot be named by a row, which reads facts by number: the line says it needs a
number. A row under a reference the board does not fit is named, and not judged. With no schematic
(`from_decks`), an entry with a figure whose part number a deck names is asked for.

Standard library only, as the CLI is. No engine runs here: `tools/workcenter` runs the decks.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from pathlib import Path

import ratings
from simcorners import TEMP_MATCH

# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {
    "ti-spra953d": (
        "section 1.1, equation 1, page 2; section 1.2, page 3; section 2.2, equations 4, 5 and 6, page 7; "
        "section 3, equation 8, page 8; table 3-1, note 11, page 9; section 4, figure 4-1, page 10; section "
        "5.1, equation 9, page 11"
    ),
    "ecss-q-st-30-11c-rev2": "clause 3.2, page 12",
}
PLAN_FILE = "thermal.json"
# What SIM prints when a project's decks ran and it has no sim/thermal.json: no junction was judged.
NO_PLAN = (
    "thermal: no part's junction is judged: sim/thermal.json is not there (the simulate skill, A part's "
    "temperature, step 3)"
)
# What SIM says of the board's parts when it cannot or need not read them (`asked` reads them).
NO_LIBRARY = (
    "thermal: the project has no library/facts, so no part of the board carries a thermal figure and none "
    "is asked for; `workcenter ratings` names the parts with no facts"
)
NO_SCHEMATIC = (
    "thermal: the project has no schematic, so it names no part of a board: only the parts sim/thermal.json "
    "names are judged"
)
UNREAD = "thermal: which parts of the board carry a thermal figure is not judged: {why}"
ROW = '"{ref}": {{"mpn": "{mpn}", "watts": "<deck>.<measure>", "source": "<how the deck gives its power>"}}'
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
        "TJ = TB + theta_jb x power; SPRA953D calls theta_jb useful for a first-pass estimation only, as "
        "it takes the board under the part as 1 uniform temperature, which is erroneous, and gives no "
        "bound on the junction it gives (section 4, page 10); psi_jb gives the junction from the board's "
        "temperature (section 5.1, equation 9, page 11)"
    ),
    "psi_jt": (
        "TJ = TC + psi_jt x power, TC the package top's temperature (SPRA953D, section 3, equation 8, page 8)"
    ),
    "psi_jb": "TJ = T(PCB) + psi_jb x power (SPRA953D, section 5.1, equation 9, page 11)",
}
# Why a heat sink is stated with theta_jc alone.
HEAT_SINK = (
    "a heat sink is stated with theta_jc only: RthetaJC was devised for a case on a heat sink (SPRA953D, "
    "section 2, page 6; section 2.2, equation 5, page 7), and psi_jt should not be used with one "
    "(section 3.2, page 10)"
)
# What a heat sink is stated with: SPRA953D's equation 5 is TJ = TA + (RthetaJC + Rtheta(CS) +
# Rtheta(SA)) x power (section 2.2, page 7).
SINK_KEYS = ("name", "theta_cs", "theta_sa", "source")
SINK_ASKED = (
    "SPRA953D's equation 5 asks for the heat sink's Rtheta(CS) and Rtheta(SA) (section 2.2, page 7): state "
    '{"name": ..., "theta_cs": C/W, "theta_sa": C/W, "source": ...}'
)
EQUATION_5 = "SPRA953D, section 2.2, equation 5, page 7"
# Why a heat sink with a resistance of 0 is refused: equation 5 would take the junction from the ambient
# through the case alone.
NO_RESISTANCE = "a heat sink with no resistance to the air is not a part; state the C/W of its datasheet"
# The equation that gave a junction on a heat sink, by its number, with its place.
EQUATIONS = {
    "1": "SPRA953D, section 1.1, equation 1, page 2",
    "4": "SPRA953D, section 2.2, equation 4, page 7",
    "5": EQUATION_5,
}
# What a part judged on theta_ja on the 2s2p board stands on.
NO_MARGIN = (
    f"held on theta_ja on {ratings.BOARDS['2s2p']} with no margin: SPRA953D calls that board a best case, "
    "not a bound, and gives as much as a 50 % RthetaJA variation between the 1s and 2s2p boards "
    "(section 1.2, page 3)"
)
MEASURE_RE = re.compile(r"([A-Za-z_]\w*)\.([A-Za-z_]\w*)")
WRITTEN = "as written"  # the label of the run of a deck as written


@dataclass(frozen=True)
class HeatSink:
    """What holds a case: its name, the interface's Rtheta(CS) and the sink's Rtheta(SA) in C/W, and
    where the 2 come from (SPRA953D, section 2.2, equation 5, page 7)."""

    name: str
    theta_cs: float
    theta_sa: float
    source: str

    def record(self) -> dict:
        return {
            "name": self.name,
            "theta_cs": self.theta_cs,
            "theta_sa": self.theta_sa,
            "source": self.source,
        }

    def said(self) -> str:
        return (
            f"{self.name}, theta_cs {self.theta_cs:g} C/W and theta_sa {self.theta_sa:g} C/W ({self.source})"
        )


@dataclass(frozen=True)
class Stated:
    """A case, board or top temperature the project states: the figure that starts from it, the
    temperature at each ambient in C, and where the number comes from."""

    figure: str
    celsius: dict[float, float]
    source: str
    heat_sink: HeatSink | None = None  # what holds the case, with theta_jc only


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
    """A part's `from`: {"figure": "psi_jb", "celsius": {"85": 101.5}, "source": "..."}, and with
    theta_jc `heat_sink`: what holds the case, with the 2 resistances it adds and their source."""
    data = ratings._keys(where, raw, ("figure", "celsius", "source"), ("heat_sink",))
    figure = data["figure"]
    if not isinstance(figure, str) or figure not in STATED:
        raise ratings.Refusal(
            f"{where}: figure: `{figure}` is no figure from a stated temperature; they are "
            f"{', '.join(STATED)}"
        )
    sink = None
    if "heat_sink" in data:
        if figure != "theta_jc":
            raise ratings.Refusal(f"{where}: heat_sink: {HEAT_SINK}; `from` names {figure}")
        raw_sink = data["heat_sink"]
        if not isinstance(raw_sink, dict):
            raise ratings.Refusal(f"{where}: heat_sink: {SINK_ASKED}")
        at = f"{where}: heat_sink"
        ratings._keys(at, raw_sink, SINK_KEYS)
        resistances = {}
        for key in ("theta_cs", "theta_sa"):
            resistances[key] = ratings._number(f"{at}: {key}", raw_sink[key], 0)
            if resistances[key] == 0:
                raise ratings.Refusal(f"{at}: {key}: 0 C/W: {NO_RESISTANCE}")
        sink = HeatSink(
            ratings._text(f"{at}: name", raw_sink["name"]),
            resistances["theta_cs"],
            resistances["theta_sa"],
            ratings._text(f"{at}: source", raw_sink["source"]),
        )
    temps = data["celsius"]
    if not isinstance(temps, dict) or not temps:
        raise ratings.Refusal(
            f'{where}: celsius: 1 ambient at least is asked, as {{"85": 101.5}}: the {STATED[figure]} '
            "temperature at that ambient, in C"
        )
    celsius: dict[float, float] = {}
    keys: dict[float, str] = {}
    for at, value in temps.items():
        try:
            ambient = float(at)
        except ValueError:
            ambient = math.nan
        if not math.isfinite(ambient):
            raise ratings.Refusal(f"{where}: celsius: `{at}` is no ambient in C")
        same = [k for a, k in keys.items() if abs(a - ambient) <= TEMP_MATCH]
        if same:
            raise ratings.Refusal(
                f"{where}: celsius: `{same[0]}` and `{at}` are the same ambient: state it once"
            )
        keys[ambient] = at
        celsius[ambient] = ratings._number(f"{where}: celsius: {at}", value, -273.15)
    return Stated(figure, celsius, ratings._text(f"{where}: source", data["source"]), sink)


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
        if figure not in term and "theta_ja" not in term:
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


def sink_assumes(term: dict) -> str:
    """What a junction of a case on a heat sink rests on (SPRA953D, section 2.2, page 7). Equation 6
    takes RthetaJA in parallel with RthetaJC + Rtheta(CS) + Rtheta(SA), which is under that sum, so
    equation 5 gives a junction no lower than equation 6 for any RthetaJA. Equation 6 is not taken: it
    is more accurate only if RthetaJA is known for the system configuration (section 2.2, page 7), and
    the facts' RthetaJA is the test board's, whose use for a system board SPRA953D calls a misapplication
    (section 1.1, page 2), a best case on 2s2p (section 1.2, page 3)."""
    ratio = (
        f" (here {term['theta_jc']:g} / {term['theta_ja']:g} = {term['theta_jc'] / term['theta_ja']:.3g})"
        if "theta_ja" in term
        else ""
    )
    return (
        "on a heat sink, equation 5 gives TJ = TA + (RthetaJC + Rtheta(CS) + Rtheta(SA)) x power, most "
        f"accurate where RthetaJC is small against RthetaJA{ratio}; at every run the greater of equation 5 "
        "and equation 4 from a stated case, or theta_ja where no case is stated, judges; equation 5 gives a "
        "junction no lower than equation 6, which SPRA953D calls more accurate for any combination if "
        "RthetaJA is known for the system configuration (section 2.2, page 7); equation 6 is not taken: the "
        "facts' RthetaJA is the test board's, whose use for a system board SPRA953D calls a misapplication "
        "(section 1.1, page 2), and on 2s2p a best case (section 1.2, page 3)"
    )


def _how(part: Part, term: dict, ambient: float) -> tuple[str, float] | None:
    """The figure a run's junction comes from and the temperature it starts from: the project's stated
    one at that ambient, else RthetaJA from the ambient, else None. A stated temperature not above its
    ambient is set aside (`_under`)."""
    if part.stated:
        for at, temp in part.stated.celsius.items():
            if abs(at - ambient) <= TEMP_MATCH and temp > at:
                return part.stated.figure, temp
    if "theta_ja" in term:
        return "theta_ja", ambient
    return None


def _under(part: Part) -> dict[float, float]:
    """The stated temperatures not above their own ambient, by ambient. Heat flows from the junction
    through the case and the board to the air (SPRA953D, section 4, figure 4-1, page 10), so a part that
    dissipates holds its case and board above the air: a statement at or under it is set aside."""
    if not part.stated:
        return {}
    return {at: temp for at, temp in part.stated.celsius.items() if temp <= at}


def _stated_at(row: dict) -> float | None:
    """The stated temperature a run stood on: the row's own start, or, where equation 5 judged the run,
    the one equation 4 started from beside it."""
    return row.get("from", (row.get("beside") or {}).get("from"))


def no_figure(entries: int) -> str:
    """What SIM says when no facts entry of the library carries a thermal figure."""
    return (
        f"thermal: no facts entry of library/facts carries a thermal figure ({entries} "
        f"entr{'y' if entries == 1 else 'ies'}), so no part of the board is asked for"
    )


def _by_ref(ref: str) -> tuple:
    """A board reference in the board's order: U2 before U10."""
    m = re.fullmatch(r"(\D*)(\d*)(.*)", ref)
    return (m.group(1), int(m.group(2)) if m.group(2) else -1, m.group(3))


def could_be(part: ratings.Part, hot: list[ratings.Facts]) -> list[ratings.Facts]:
    """The entries with a thermal figure that a part with no part number and no facts entry could be:
    those whose every pin number is a pin of the part. A part of 2 pins is no regulator of 5."""
    return [f for f in hot if {n for p in f.data.get("pins", []) for n in p["numbers"]} <= set(part.pins)]


BY_SYMBOL = (
    "which no row of sim/thermal.json can name: a row names a part by its number, and judge() reads the "
    "facts by that number. Give the part its number in parts.csv beside the schematic, and a facts entry "
    "that names that number (the ratings skill)"
)


def _by_symbol_only(entry: ratings.Facts) -> bool:
    """Whether a facts entry names its parts by their symbol alone, with no number and no pattern of one
    (the ratings skill's form for a part with no number): no row's part number speaks of it."""
    return not any(key in entry.data for key in ("mpn", "mpns", "match"))


def _names_its_part(row_mpn: str, mpn: str, entry: ratings.Facts | None, maybe: list) -> bool:
    """Whether a row's part number is the board part's: its number from the parts file; with none, a
    number its facts entry names; with no entry, a number an entry it could be names."""
    if mpn:
        return row_mpn == mpn
    if entry is not None:
        return entry.speaks_of(row_mpn, "", "") >= 2
    return any(f.speaks_of(row_mpn, "", "") >= 2 for f in maybe)


def asked(
    entries: dict[str, tuple[str, ratings.Facts | None]],
    named: dict[str, str] | None,
    maybe: dict[str, list[ratings.Facts]] | None = None,
    parts: str | None = "parts.csv",
    unread: tuple[str, ...] = (),
) -> dict:
    """The parts of the board that can get hot, and those sim/thermal.json leaves out: {"line", "asked",
    "unplanned", "not_judged", "failures", "mismatched", "strays"}; a stray is a row for a reference that
    is no fitted part of the board, {ref: {"mpn", "line"}}, and is not judged. `entries` maps each part
    of the board to its part number and the facts entry that names it (None: no entry); `unread` names
    the fitted parts whose facts could not be read (2 entries speak of them as closely): they are no
    strays, and their rows are judged by number. `named` maps the plan's parts to the
    part numbers of their rows (None: no plan). A part is asked for because its facts carry `thermal`, a
    junction_max and 1 figure at least: no power is guessed. `maybe` maps a part with no number and no
    entry to the entries with a figure it could be (`could_be`): it is not judged, as the gate cannot
    tell. `parts` names the parts file the numbers came from, None when the project has none. A row whose
    part number is not the board part's names facts that are not its own: it fails, and does not count
    as naming the part (judge() reads the facts by the row's number)."""
    named, maybe = named or {}, {ref: m for ref, m in (maybe or {}).items() if m}
    failures, mismatched = [], []
    for ref in sorted(set(named) & set(entries), key=_by_ref):
        mpn, entry = entries[ref]
        if _names_its_part(named[ref], mpn, entry, maybe.get(ref, [])):
            continue
        remedy = (
            ": write the board's part number in its row (the simulate skill, A part's temperature, step 3)"
        )
        if mpn:
            why = f"{parts} gives {mpn}"
        elif entry is not None and _by_symbol_only(entry):
            why, remedy = f"the facts entry of the board's part ({entry.where}) names it by its symbol", ""
        elif entry is not None:
            why = f"the facts entry of the board's part ({entry.where}) does not name it"
        else:
            why = (
                "the board's part has no part number and no facts entry, and no entry whose pins it has "
                "names it"
            )
        mismatched.append(ref)
        failures.append(
            f"thermal: {ref} ({mpn or (entry.name if entry else 'no part number')}) is judged on facts that "
            f"are not its own: its row in sim/thermal.json names {named[ref]}, and {why}"
            + (remedy or f", {BY_SYMBOL}")
        )
    held = {ref for ref in named if ref not in mismatched}
    # A row for a reference the board does not carry, or marks not fitted, is no part of the board: the
    # gate does not judge it (tools/workcenter leaves it out of judge()), and names it with its number.
    # A file with no row is refused, so the line says to delete the file when the row is its only one.
    strays = {
        ref: {
            "mpn": named[ref],
            "line": f"thermal: {ref} of sim/thermal.json is no fitted part of the board: the schematic has "
            f"no {ref}, or marks it not fitted, so its row ({named[ref]}) is not judged: write the row under "
            "the board part's reference, or take it out; if it is the only row, delete sim/thermal.json",
        }
        for ref in sorted(set(named) - set(entries) - set(unread), key=_by_ref)
    }
    hot = sorted(
        (ref for ref, (_, f) in entries.items() if f is not None and "thermal" in f.data), key=_by_ref
    )
    # A part with no number and no entry, whose row names an entry it could be, is judged on that entry's
    # figures (judge() reads them by the row's number): it carries a figure, and its number is the row's.
    by_row = sorted((ref for ref in maybe if ref in entries and ref in held), key=_by_ref)
    unsure = sorted((ref for ref in maybe if ref in entries and ref not in held), key=_by_ref)
    left = [ref for ref in hot if ref not in held and ref not in mismatched]
    not_judged = []
    for ref in [r for r in unsure if r not in mismatched]:
        could = maybe[ref]
        listed = ", ".join(f"{f.name} ({f.where})" for f in could)
        why = (
            f"no row of {parts} names its Value and Footprint"
            if parts
            else "the project has no parts.csv to give its part number"
        )
        not_judged.append(
            f"thermal: {ref} not judged: {why} and no facts entry names it by its symbol, and it has the "
            f"pins of {listed}, whose facts carry a thermal figure: give its part number in parts.csv beside "
            "the schematic, the file the gate reads it from"
        )
    unplanned = sorted({*left, *(r for r in unsure if r not in mismatched)}, key=_by_ref)
    record = {"unplanned": unplanned, "failures": failures, "mismatched": mismatched, "strays": strays}
    carrying = sorted([*hot, *by_row], key=_by_ref)
    if not carrying:
        bare = sum(1 for _, f in entries.values() if f is None)
        count = f"{len(entries)} part{'s' if len(entries) != 1 else ''}"
        said = f"{count}; {bare} with no facts entry, which `workcenter ratings` names" if bare else count
        line = (
            "thermal: no part of the board carries a thermal figure in its facts, so no junction is asked "
            f"for ({said})"
        )
        if unsure:
            line = (
                "thermal: no part of the board is known to carry a thermal figure in its facts; "
                f"{len(unsure)} part{'s' if len(unsure) != 1 else ''} with no part number may: "
                f"{', '.join(unsure)}"
            )
        return {"line": line, "asked": [], "not_judged": not_judged, **record}
    for ref in left:
        mpn, entry = entries[ref]
        if not mpn and _by_symbol_only(entry):
            # A row reads the facts by its part number: no row can name an entry named by its symbol.
            not_judged.append(
                f"thermal: {ref} ({entry.name}) not judged: {_carries(entry)} and name it by its symbol, "
                + BY_SYMBOL
            )
            continue
        number = mpn or entry.name
        not_judged.append(
            f"thermal: {ref} ({number}) not judged: {_carries(entry)}, and sim/thermal.json names no row for "
            "it: write its row under `parts` (the simulate skill, A part's temperature, step 3): "
            + ROW.format(ref=ref, mpn=number)
        )
    line = (
        f"thermal: {len(carrying)} part{'s' if len(carrying) != 1 else ''} of the board "
        f"carr{'ies' if len(carrying) == 1 else 'y'} a thermal figure in "
        f"{'its' if len(carrying) == 1 else 'their'} facts: {', '.join(carrying)}; sim/thermal.json names "
        f"{len([r for r in carrying if r in held])} of them"
    )
    for ref in by_row:
        line += f"; {ref} has no part number from a parts file: {named[ref]} is its row's in sim/thermal.json"
    if unsure:
        line += f"; {len(unsure)} more with no part number may: {', '.join(unsure)}"
    return {"line": line, "asked": carrying, "not_judged": not_judged, **record}


def _carries(entry: ratings.Facts) -> str:
    """What a facts entry's thermal figures are, with their pages: `its facts (x.json) carry ...`."""
    term = entry.data["thermal"]
    figures = [f"{f} {term[f]:g} C/W" for f in FIGURES if f in term]
    listed = figures[0] if len(figures) == 1 else f"{', '.join(figures[:-1])} and {figures[-1]}"
    return (
        f"its facts ({entry.where}) carry junction_max {term['junction_max']:g} C and {listed} "
        f"({ratings._p(term['page'])})"
    )


# A deck's text in words: a part number is 1 of them (`TLV75533PDBVR,` and `(TLV75533PDBVR)` alike).
DECK_WORD_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+#/-]*[A-Za-z0-9+#]|[A-Za-z0-9]")


def from_decks(decks: dict[str, str], hot: list[ratings.Facts], named: dict[str, str] | None) -> dict:
    """With no schematic, the parts the decks name: {"line", "asked", "not_judged"}. `decks` maps each
    deck's file name to its text; `hot` are the facts entries with a thermal figure; `named` maps the
    plan's parts to their rows' part numbers (None: no plan). An entry whose part number a deck names
    (a word of its text, by its number or its pattern) is asked for, and one no row names is not
    judged: a project that simulates before layout has decks and no board, and its decks give the
    power. A deck that names no number names no part: only the plan's parts are judged then."""
    found: dict[str, tuple[ratings.Facts, str, list[str]]] = {}
    for deck, text in sorted(decks.items()):
        for word in dict.fromkeys(DECK_WORD_RE.findall(text)):
            for f in hot:
                if f.speaks_of(word, "", "") >= 2:
                    entry = found.setdefault(f.where, (f, word, []))
                    if deck not in entry[2]:
                        entry[2].append(deck)
    if not found:
        return {"line": NO_SCHEMATIC, "asked": [], "not_judged": []}
    rows = list((named or {}).values())
    numbers, not_judged, held = [], [], 0
    for f, number, where in found.values():
        numbers.append(number)
        if any(f.speaks_of(row, "", "") >= 2 for row in rows):
            held += 1
            continue
        not_judged.append(
            f"thermal: {number} (named by {', '.join(where)}) not judged: {_carries(f)}, and "
            "sim/thermal.json names no row for it: write its row under `parts`, under the reference the part "
            "will have on the board (the simulate skill, A part's temperature, step 3): "
            + ROW.format(ref="<reference>", mpn=number)
        )
    line = (
        "thermal: the project has no schematic, so it names no part of a board; its decks name "
        f"{len(numbers)} part number{'s' if len(numbers) != 1 else ''} whose facts carry a thermal figure: "
        f"{', '.join(numbers)}; sim/thermal.json names {held} of them"
    )
    return {"line": line, "asked": numbers, "not_judged": not_judged}


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
        lacking = part.stated is not None and part.stated.figure not in term
        if lacking:
            figure = part.stated.figure
            not_judged.append(
                f"{name} not judged from its stated {STATED[figure]} temperature: sim/thermal.json names "
                f"{figure} in `from`, and its facts ({entry.where}) give no {figure}; theta_ja judges its "
                "runs"
            )
            part = replace(part, stated=None)
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
        # A part on a heat sink: equation 5 from the ambient (SPRA953D, section 2.2, page 7) needs only the
        # run's ambient and the sink's 2 resistances, so it is worked at every run whose ambient is known,
        # beside equation 4 from a stated case or theta_ja where none is stated: the greater judges, and
        # a junction over the limit by equation 5 fails whatever else is set aside.
        sink = part.stated.heat_sink if part.stated else None
        sunk = sink is not None
        rows, unstated = [], []
        for label, ambient, m in ran:
            if isinstance(ambient, str):
                continue
            watts = m[part.measure]
            how = _how(part, term, ambient)
            if how is None:
                unstated.append(label)
                if not sunk:
                    continue
                figure, junction = "theta_jc", -math.inf  # equation 5 alone gives this run's junction
            else:
                figure, start = how
                junction = start + term[figure] * watts
            row = {"run": label, "ambient": ambient, "watts": watts, "figure": figure}
            if how is not None and figure != "theta_ja":
                row["from"] = start
            if sunk:
                row["sink_junction"] = ambient + (term["theta_jc"] + sink.theta_cs + sink.theta_sa) * watts
                before = "1" if figure == "theta_ja" else "4"
                row["equation"] = "5" if row["sink_junction"] > junction else before
                if row["equation"] == "5":
                    # Equation 5 judged the run: theta_jc from the ambient. What equation 1 or 4 gave
                    # there stays beside it, with the stated case it started from.
                    if how is not None:
                        row["beside"] = {"figure": figure, "equation": before, "junction": junction}
                        if "from" in row:
                            row["beside"]["from"] = row.pop("from")
                    row["figure"] = "theta_jc"
                junction = max(junction, row["sink_junction"])
            rows.append({**row, "junction": junction})
        if unstated:
            not_judged.append(
                f"{name} not judged {_at(unstated[0])}{_more(len(unstated) - 1)}: sim/thermal.json states "
                f"its {STATED[part.stated.figure]} temperature at {celsius(list(part.stated.celsius))} "
                "ambient only, and its facts give no theta_ja"
                + (f"; equation 5 from the ambient ({EQUATION_5}) is worked there alone" if sunk else "")
            )
        under = _under(part)
        if under:
            said_under = " and ".join(f"{temp:g} C at {at:g} C ambient" for at, temp in under.items())
            not_judged.append(
                f"{name} not judged from its stated {STATED[part.stated.figure]} temperature: "
                f"sim/thermal.json states {said_under}, not above the air; a part's heat flows from its "
                "junction through its case and board to the air (SPRA953D, section 4, figure 4-1, page 10), "
                "so it is set aside"
            )
        if part.stated:
            idle = [
                t
                for t in part.stated.celsius
                if t not in under
                and not any(_stated_at(r) is not None and abs(r["ambient"] - t) <= TEMP_MATCH for r in rows)
            ]
            if idle:
                not_judged.append(
                    f"{name}: sim/thermal.json states its {STATED[part.stated.figure]} temperature at "
                    f"{celsius(idle)} ambient, where no run of {part.deck} stands"
                )
        if not rows:
            continue
        # On a heat sink equation 5 takes theta_jc at every run, so its board is asked for too.
        # A figure that equation 5 outweighed at a run (`beside`) was still worked there: its board is
        # asked for too, as before the record named equation 5's figure.
        beside = [r["beside"]["figure"] for r in rows if "beside" in r]
        used = list(dict.fromkeys([r["figure"] for r in rows] + beside + (["theta_jc"] if sunk else [])))
        unboarded = [f for f in used if f not in term.get("boards", {})]
        not_judged += [
            f"{name} not held: its facts ({entry.where}) name no JEDEC board for {f}: write `boards` in "
            "`thermal` from the datasheet's thermal table"
            for f in unboarded
        ]
        # A junction from a stated temperature under the one theta_ja gives on the 2s2p board, which
        # SPRA953D calls a best case (section 1.2, page 3), holds no part. With no theta_ja on the 2s2p
        # board nothing bounds a stated temperature, so it holds no part either. A case the project
        # states on a heat sink is what theta_jc was devised for (section 2, page 6; section 2.2,
        # equation 5, page 7): the 2s2p board bounds it not.
        ja_board = term.get("boards", {}).get("theta_ja") if "theta_ja" in term else None
        from_stated = [r for r in rows if _stated_at(r) is not None]
        best, unchecked = [], []
        if from_stated and not sunk:
            if ja_board == "2s2p":
                for r in from_stated:
                    ja = r["ambient"] + term["theta_ja"] * r["watts"]
                    if r["junction"] < ja:
                        best.append((r, ja))
            else:
                unchecked = from_stated
        if unchecked:
            r = unchecked[0]
            if "theta_ja" not in term:
                why = "its facts give no theta_ja"
            elif ja_board is None:
                why = "its facts name no JEDEC board for theta_ja"
            else:
                why = (
                    f"its facts give theta_ja on {ratings.BOARDS[ja_board]}, which SPRA953D calls a "
                    "typical case"
                )
            not_judged.append(
                f"{name} not held {_at(r['run'])}{_more(len(unchecked) - 1)}: its stated "
                f"{STATED[r['figure']]} {r['from']:g} C, which gives a junction of {r['junction']:.5g} C, "
                f"was checked against no board: {why}, and only theta_ja on {ratings.BOARDS['2s2p']}, a best "
                "case and no bound (SPRA953D, section 1.2, page 3), is the floor the gate holds a stated "
                "temperature's junction to"
            )
        if best:
            r, ja = best[0]
            not_judged.append(
                f"{name} not held {_at(r['run'])}{_more(len(best) - 1)}: its stated "
                f"{STATED[r['figure']]} {r['from']:g} C gives a junction of {r['junction']:.5g} C, under the "
                f"{ja:.5g} C theta_ja gives on {ratings.BOARDS['2s2p']}, which SPRA953D calls a best case "
                "(section 1.2, page 3)"
            )
        # SPRA953D gives theta_jb as a first-pass estimation only, with no bound (section 4, page 10).
        rough = [r for r in rows if r["figure"] == "theta_jb"]
        if rough:
            not_judged.append(
                f"{name} not held {_at(rough[0]['run'])}{_more(len(rough) - 1)}: its junction there comes "
                "from theta_jb, which SPRA953D calls useful for a first-pass estimation only and gives no "
                "bound on (section 4, page 10); psi_jb gives the junction from the board's temperature "
                "(section 5.1, equation 9, page 11)"
            )
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
            "assumes": "; ".join([assumes(f, term) for f in used] + ([sink_assumes(term)] if sunk else [])),
            "read_once": read_once,
            "written": rows[0] if rows[0]["run"] == WRITTEN else None,
            "worst": worst,
            "runs": len(rows),
            # Held only when every run and every corner was judged, each on a figure whose board the
            # facts name and that SPRA953D bounds, no stated temperature was set aside, and none gives a
            # junction under the 2s2p best case; None when some were not.
            "held": False
            if over
            else (
                None
                if unknown
                or part.deck in unrun
                or unstated
                or unboarded
                or under
                or lacking
                or best
                or unchecked
                or rough
                else True
            ),
        }
        if ja_board == "2s2p" and any(r["figure"] == "theta_ja" and r.get("equation") != "5" for r in rows):
            # SPRA953D calls the 2s2p figure a best case, with as much as a 50 % RthetaJA variation from
            # the board alone (section 1.2, page 3): a part judged on it stands with no margin.
            parts[ref]["no_margin"] = True
        if from_stated or sunk:
            parts[ref]["stated"] = {
                "figure": part.stated.figure,
                "temperature": STATED[part.stated.figure],
                "source": part.stated.source,
            }
        if sunk:
            parts[ref]["stated"]["heat_sink"] = sink.record()
            # The equation that gave the worst junction, with its section and page.
            parts[ref]["equation"] = EQUATIONS[worst["equation"]]
        if from_stated:
            if "theta_ja" in term:
                # What theta_ja gives where a stated temperature judged, so the owner sees how far the
                # statement moves the verdict.
                gives = [(r["ambient"] + term["theta_ja"] * r["watts"], r) for r in from_stated]
                ja, r = max(gives, key=lambda g: g[0])
                parts[ref]["theta_ja_gives"] = {
                    "run": r["run"],
                    "ambient": r["ambient"],
                    "junction": ja,
                    "theta_ja": term["theta_ja"],
                    "board": ja_board,
                }
        if over:
            # Equation 5 takes theta_jc from the ambient, whatever judged the run before it.
            figure = "theta_jc" if worst.get("equation") == "5" else worst["figure"]
            start = (
                f"{worst['ambient']:g} C"
                if figure == "theta_ja" or worst.get("equation") == "5"
                else f"{STATED[figure]} {worst['from']:g} C at {worst['ambient']:g} C ambient "
                f"({part.stated.source})"
            )
            through = f"{term[figure]:g} C/W"
            if worst.get("equation") == "5":
                through = (
                    f"({term[figure]:g} C/W + theta_cs {sink.theta_cs:g} C/W + theta_sa "
                    f"{sink.theta_sa:g} C/W of the heat sink, {sink.name} ({sink.source}))"
                )
            measure_said = f"{measure}, {EQUATIONS[worst['equation']]}" if sunk else measure
            more = len(over) - 1
            failures.append(
                f"{name} at {worst['ambient']:g} C ambient: junction {worst['junction']:.5g} C, over "
                f"{most:g} C ({worst['run']}"
                + (f", and {more} more run{'s' if more > 1 else ''}" if more else "")
                + f"): {start} + {through} x {worst['watts']:.5g} W of {measure_said}, {figure} and "
                f"junction_max of {entry.source}, {ratings._p(term['page'])}, {_board(figure, term)}; "
                f"limit {said}"
            )
    return {"failures": failures, "not_judged": not_judged, "parts": parts}


def lines(details: dict) -> list[str]:
    """The SIM gate's thermal lines from its record: that no junction was judged, or each part's junction
    as written and at its worst, what it started from, its limit and what it rests on. `sim` and `gates`
    print them, and `gates --report` writes them, where a reviewer decides a board is done."""
    said = []
    if (details.get("thermal") or {}).get("unplanned"):
        said.append(details["thermal"]["unplanned"])
    if ((details.get("thermal") or {}).get("board") or {}).get("line"):
        said.append(details["thermal"]["board"]["line"])
    for ref, part in ((details.get("thermal") or {}).get("parts") or {}).items():
        w, worst = part["written"], part["worst"]
        sink = (part.get("stated") or {}).get("heat_sink")
        said.append(
            f"thermal {ref}: junction "
            + (f"{w['junction']:.5g} C as written ({w['ambient']:g} C), " if w else "not judged as written, ")
            + f"{worst['junction']:.5g} C at its worst of {part['runs']} "
            f"run{'s' if part['runs'] > 1 else ''} ({worst['run']})"
            + (
                f", from {part['stated']['temperature']} {worst['from']:g} C at {worst['ambient']:g} C "
                f"ambient ({part['stated']['source']})"
                if worst.get("from") is not None
                else ""
            )
            + (
                f", the case on a heat sink, {sink['name']}, theta_cs {sink['theta_cs']:g} C/W and "
                f"theta_sa {sink['theta_sa']:g} C/W ({sink['source']}), the worst junction by "
                f"{part['equation']}"
                if sink
                else ""
            )
            + f"; limit {part['limit']:g} C"
            + (
                f"; where a stated temperature judged, theta_ja {gives['theta_ja']:g} C/W "
                + (
                    f"on {ratings.BOARDS[gives['board']]}"
                    if gives["board"]
                    else "on no JEDEC board its facts name"
                )
                + f" gives {gives['junction']:.5g} C at its worst ({gives['run']})"
                if (gives := part.get("theta_ja_gives"))
                else ""
            )
            + ("; not judged at every run" if part["held"] is None else "")
            + (f"; {NO_MARGIN}" if part.get("no_margin") and part["held"] else "")
            + f"; {part['assumes']}"
            + (f"; read once: {', '.join(part['read_once'])}" if part["read_once"] else "")
        )
    return said
