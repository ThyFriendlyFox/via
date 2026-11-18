"""partdata — the makers' data of a deck's capacitors and inductors, as the SIM gate runs them.

A capacitor's facts may hold `kept`, pairs [volts, share of the value kept] from its maker's DC bias
curve, and `kept_celsius`, pairs [celsius, share] from its temperature curve; `kept_celsius_at`, its
maker's temperature curve at 1 bias; and `esr` and `esl`, which go in series. An inductor's facts may
hold `kept`, pairs [amps, share]. The gate takes a curve only from facts that name the part's number
(`mpn`, or `mpns`; never a pattern) and whose source's SHA256 is a row of the project's
library/sources.csv for that part: the maker's file. A row that keeps no file leaves that not judged.

The gate writes each such part of a deck as ngspice's behavioural element: a capacitor's value times
`pwl()` of the voltage across it and of `temper`, an inductor's value times `pwl()` of the current
through a 0 V source put in series with it. ngspice takes the expression as the part's incremental
value: i = C(v) dv/dt, v = L(i) di/dt, which is what a maker measures with a small signal on a bias.
`pwl()` holds the last share past the last point.

Standard library only, as the CLI is; it runs no engine (AGENTS.md invariant 14).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import simcorners

REF_RE = re.compile(r"^([CL])\d+$")  # a board reference whose whole letter prefix is C or L (P27 step 5)
KIND_OF = {"C": "capacitor", "L": "inductor"}
UNIT = {"C": "V", "L": "A"}
CAPACITOR_ONLY = ("kept_celsius_at", "esr", "esl")
UIC_RE = re.compile(r"^\s*tran\b.*\buic\b", re.IGNORECASE)  # a `.control` transient from the ICs
HOLDS = ("kept", "kept_celsius", *CAPACITOR_ONLY)  # the facts keys the gate runs a part on


@dataclass
class Curve:
    """1 part's data as the gate applies it."""

    ref: str
    kind: str  # C or L
    kept: list | None  # [volts or amps, share]
    celsius: list | None  # a capacitor's [celsius, share against 25 C]
    facts: str  # the facts entry: its file and its place
    row: str  # the row of sources.csv that names the maker's file
    rating: float | None  # a capacitor's volts, an inductor's saturation current
    unjudged: str = ""  # why the SHA256 of its maker's file is not judged, when it is not
    bias: dict | None = None  # a capacitor's temperature curve at 1 bias: {"volts", "kept": [celsius, share]}
    esr: dict | None = None  # a capacitor's series resistance: {"ohms", "hz"}
    esl: dict | None = None  # a capacitor's series inductance: {"henries", "hz"}


@dataclass
class Row:
    """What partdata reads of a row of library/sources.csv."""

    mpn: str
    sha256: str
    source: str  # file:line
    file: str = ""  # the path of the file the row keeps, or "" when it keeps none


def _sha256(path: str) -> str | None:
    """The SHA256 of a file, or None when it is not there."""
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def choose(
    parts: dict[str, tuple[str, object]], rows: list[Row]
) -> tuple[dict[str, Curve], dict[str, str], dict[str, str]]:
    """The curves of a schematic's capacitors and inductors: (curves, refused, unjudged). `parts` maps a
    reference to its part number and its facts entry (a ratings.Facts, or None). An entry with a curve
    is refused, with the reason, when it does not name the part's number (a symbol's entry, a pattern's:
    a series datasheet covers every value of the series), when no row of sources.csv for the part holds
    the SHA256 its source names, or when the file that row keeps has another SHA256: no part gets another
    part's data, and none gets data that is not its maker's file. `unjudged` names each curve taken
    whose row keeps no file: then 2 typed strings agree, and no file holds them."""
    found: dict[str, Curve] = {}
    refused: dict[str, str] = {}
    unjudged: dict[str, str] = {}
    for ref, (mpn, entry) in sorted(parts.items()):
        m = REF_RE.match(ref)
        if not m or entry is None or not entry.kind.startswith(KIND_OF[m.group(1)]):
            continue
        kind, data = m.group(1), entry.data
        kept, celsius = data.get("kept"), data.get("kept_celsius") if kind == "C" else None
        bias, esr, esl = (data.get(k) for k in CAPACITOR_ONLY) if kind == "C" else (None, None, None)
        if all(x is None for x in (kept, celsius, bias, esr, esl)):
            continue
        if "symbol" in data:
            refused[ref] = f"its facts speak of the symbol {data['symbol']}, not of a part number"
            continue
        if not mpn or (data.get("mpn") != mpn and mpn not in data.get("mpns", ())):
            refused[ref] = (
                f"its facts name the parts by the pattern {data.get('match')}, not by its part number "
                f"{mpn or '(none)'}: a curve is taken from an entry whose mpn or mpns names the part"
            )
            continue
        sha = str(data["source"].get("sha256", "")).lower()
        row = next(
            (r for r in rows if sha and r.sha256.lower() == sha and r.mpn.upper() == mpn.upper()), None
        )
        if row is None:
            refused[ref] = (
                f"no row of library/sources.csv for {mpn} holds the SHA256 its facts name ({sha[:12]}...)"
                if sha
                else "its facts name no SHA256 of the maker's file"
            )
            continue
        if not row.file:
            unjudged[ref] = (
                f"{row.source} keeps no file, so nothing holds its SHA256 ({sha[:12]}...) against the maker's"
            )
        elif _sha256(row.file) != sha:
            name = row.file.replace("\\", "/").rsplit("/", 1)[-1]
            refused[ref] = f"the file {row.source} keeps, {name}, is not the one its SHA256 names"
            continue
        if bias is not None and (why := _bias_refused(bias, kept)):
            refused[ref] = why
            continue
        rating = data.get("volts") if kind == "C" else data.get("amps_saturation")
        found[ref] = Curve(ref, kind, kept, celsius, entry.where, row.source, rating, "", bias, esr, esl)
    return found, refused, unjudged


def _bias_refused(bias: dict, kept: list | None) -> str | None:
    """Why a temperature curve at 1 bias cannot be taken, or None. `apply` divides its shares by the
    share the DC bias curve keeps at that bias, so they are to be against the value at 0 V and 25 C, as
    Samsung's BiasTCC data gives them: its 25 C share is then nearer that share than 1. A curve that
    keeps 1 at 25 C was entered against 25 C at its own bias, and would undo the DC bias loss."""
    reference = "the value at 0 V and 25 C"
    if not kept:
        return f"its kept_celsius_at has no DC bias curve (`kept`) to hold its shares to {reference}"
    points = bias["kept"]
    if not points[0][0] <= 25 <= points[-1][0]:
        return f"its kept_celsius_at does not reach 25 C, so its shares cannot be held to {reference}"
    volts, there, at25 = bias["volts"], _at(kept, bias["volts"]), _at(points, 25)
    if abs(at25 - there) <= abs(at25 - 1):
        return None
    return (
        f"its kept_celsius_at keeps {at25:.5g} at 25 C, nearer 1 than the {there:.5g} its DC bias curve "
        f"keeps at {volts:g} V: its shares are to be against the value at 0 V and 25 C, as the gate "
        f"divides them by {there:.5g}"
    )


def between(curve: Curve) -> str | None:
    """The line that names the temperature factor between 0 V and a capacitor's bias curve as the
    gate's, not the maker's: a straight line in volts between the maker's 2 curves."""
    if not curve.bias:
        return None
    volts = f"{curve.bias['volts']:g} V"
    return (
        f"not judged: {curve.ref}'s share at a temperature between 0 V and {volts}: the gate goes from its "
        f"maker's temperature curve at 0 V to the one at {volts} in a straight line in volts, which the "
        "maker does not publish"
    )


def _uic(lines: list[str]) -> bool:
    """Whether the deck's transient starts from the initial conditions: `uic` among the tokens of a
    `.tran` statement, its `+` lines included as ngspice joins them, or on a `tran` of `.control`."""
    for i in simcorners.netlist_lines(lines):
        tokens = [t[3].lower() for t in simcorners.logical_tokens(lines, i)]
        if tokens and tokens[0] == ".tran" and "uic" in tokens:
            return True
    return any(UIC_RE.match(text) for _, _, text in simcorners.control_commands(lines))


def _blocks(lines: list[str], starts: list[int]) -> dict[int, str]:
    """The `.subckt` each netlist line inside one stands in, by its index."""
    within: dict[int, str] = {}
    block = ""
    for i in starts:
        word = lines[i].split()[0].lower()
        if word == ".subckt":
            block = lines[i].split()[1] if len(lines[i].split()) > 1 else "?"
        elif word == ".ends":
            block = ""
        elif block:
            within[i] = block
    return within


def short_of_rating(curve: Curve) -> str | None:
    """A curve that stops under the part's rating: past its last point the deck holds the last share."""
    if curve.rating is None or not curve.kept or curve.kept[-1][0] >= curve.rating:
        return None
    unit = UNIT[curve.kind]
    last = f"{curve.kept[-1][0]:g} {unit}"
    return f"{curve.ref}'s curve ends at {last}, under its rating of {curve.rating:g} {unit}"


def _pairs(pairs: list) -> str:
    return ",".join(f"{x:.10g},{y:.10g}" for x, y in pairs)


def _at(pairs: list, x: float) -> float:
    """A curve's share at x, as ngspice's pwl() reads it: in a straight line between 2 points, the
    end's share past an end."""
    if x <= pairs[0][0]:
        return pairs[0][1]
    for (x0, y0), (x1, y1) in zip(pairs, pairs[1:], strict=False):
        if x <= x1:
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    return pairs[-1][1]


def _value(token: str) -> str | None:
    """A value token as a factor of an expression: a number as written, an expression in braces or
    quotes, each in parentheses. None for anything else: a model's name, a parameter's bare name."""
    if simcorners.spice_number(token) is not None:
        return f"({token})"
    if len(token) > 1 and (token[0], token[-1]) in (("{", "}"), ("'", "'")):
        return f"({token[1:-1]})"
    return None


def _coupled(lines: list[str]) -> dict[str, str]:
    """Each inductor a K element of the deck's top level couples, upper case, and the first K that names
    it. A K inside a `.subckt` couples that block's own inductors, not the deck's."""
    coupled: dict[str, str] = {}
    starts = simcorners.netlist_lines(lines)
    within = _blocks(lines, starts)
    for i in starts:
        if i not in within and lines[i].split()[0][0].lower() == "k":
            for other in [t[3].upper() for t in simcorners.logical_tokens(lines, i)[1:3]]:
                coupled.setdefault(other, lines[i].split()[0])
    return coupled


def not_modelled(text: str, curves: dict[str, Curve]) -> dict[str, str]:
    """Each inductor of `curves` that a K element of the deck couples, with the reason: K names the
    inductor the gate would replace, and a coupled inductor's curve is of its core, which both
    windings share. It runs as written; the gate names it and does not fail the deck for it."""
    return {
        name: f"it is coupled by {k}, and the gate models no coupled inductor's curve"
        for name, k in sorted(_coupled(text.split("\n")).items())
        if name in curves and curves[name].kind == "L" and name in simcorners.deck_names(text.split("\n"))
    }


def apply(
    text: str, curves: dict[str, Curve], included: dict[str, str] | None = None
) -> tuple[str, list[str], dict[str, str]]:
    """The deck with each part `curves` names written on its maker's data: (text, applied, ideal).
    `ideal` names each part the gate cannot rewrite, with the reason: it stands inside a .subckt (each
    copy would share 1 rewrite), and no element of its name stands at the deck's top level, or outside
    the deck's own lines, in a file of `included` (the path as the deck writes it, and its text); its
    value is no number and no expression; or, in a deck whose transient starts from the initial
    conditions (`uic`, on the `.tran` card or its `+` lines), it has an ic= that is no capacitor's with
    a number, or its line holds another parameter (m=, tc1=) that the form for an ic= does not carry.
    ngspice 42 drops an ic= from a behavioural C or L: a capacitor's moves to a unit capacitor whose
    current drives the part, and without `uic`, where ngspice uses no ic=, an ic= is taken off. An
    inductor a K element couples is left as written and is in neither list: `not_modelled` names it.
    A capacitor's ESR and ESL go in series with it, toward its second node."""
    lines = text.split("\n")
    starts = simcorners.netlist_lines(lines)
    within = _blocks(lines, starts)
    top = {lines[i].split()[0].upper() for i in starts if i not in within}
    coupled = _coupled(lines)
    edits: dict[int, list[tuple[int, int, str]]] = {}
    after: dict[int, list[str]] = {}
    uic = _uic(lines)
    hidden: set[int] = set()  # the lines of an element the gate writes again in another form
    applied: list[str] = []
    ideal: dict[str, str] = {}
    own = simcorners.deck_names(lines)
    for path, body in (included or {}).items():
        for name in simcorners.top_level_parts(body):
            if name.upper() in curves and name.upper() not in own:
                ideal.setdefault(
                    name.upper(),
                    f"it stands in {path}, a file the deck includes, which the gate does not rewrite",
                )
    for i in starts:
        name = lines[i].split()[0].upper()
        curve = curves.get(name)
        if curve is None or name[0] != curve.kind:
            continue
        if name in coupled:
            continue
        if i in within:
            # an element of the same name at the top level is the board's part; this one is the block's
            if name not in top:
                ideal[name] = f"it stands inside .subckt {within[i]}, which the gate does not rewrite"
            continue
        tokens = simcorners.logical_tokens(lines, i)
        n1, n2 = tokens[1], tokens[2]
        last = simcorners.statement_lines(lines, i)[-1][0]
        place = simcorners.value_place(tokens)
        factor = _value(place[3]) if place else None
        if factor is None:
            ideal[name] = (
                f"its value {place[3] if place else 'that is missing'} is no number and no expression"
            )
            continue
        ic = next(
            (
                k
                for k in range(3, len(tokens) - 2)
                if tokens[k][3].lower() == "ic" and tokens[k + 1][3] == "="
            ),
            None,
        )
        begin = None  # a capacitor's starting voltage, which the gate writes on a unit capacitor
        if ic is not None:
            # ngspice 42 drops ic= from the element the gate writes, and its own behavioural capacitor
            # starts from 0 V under a node's .ic too (a run of tests/test_partdata.py). It uses an
            # element's ic= only with uic: without it the gate takes the ic= off; with it a capacitor
            # is written as a current source of C(v) times the current of a 1 F capacitor that carries
            # the ic=, and the test runs both forms to the same numbers.
            told = tokens[ic + 2][3]
            begin = simcorners.spice_number(told) if uic else None
            if uic and (curve.kind == "L" or begin is None):
                ideal[name] = (
                    "its ic= sets its starting current, which ngspice 42 drops from the element the gate "
                    "writes"
                    if curve.kind == "L"
                    else f"its ic={told} is no number, and the gate writes a starting voltage only as a "
                    "number"
                )
                continue
            # the B source carries none of the line's other parameters (m=, tc1=, scale=, ...), which
            # ngspice keeps on the named form `C='...'` (a run of tests/test_partdata.py)
            at = tokens.index(place)
            used = {0, 1, 2, at, ic, ic + 1, ic + 2} | (
                {at - 2, at - 1} if tokens[at - 1][3] == "=" else set()
            )
            rest = " ".join(t[3] for k, t in enumerate(tokens) if k not in used).replace(" = ", "=")
            if uic and rest:
                ideal[name] = (
                    f"its line also holds {rest}, which the form the gate writes for an ic= under uic "
                    "does not carry"
                )
                continue
            if not uic:
                for t in tokens[ic : ic + 3]:
                    edits.setdefault(t[0], []).append((t[1], t[2], ""))
        j, start, end, _ = place
        low = name.lower()
        if curve.kind == "C":
            series = [
                (f"r{low}_esr", f"{low}_esr", curve.esr["ohms"]) if curve.esr else None,
                (f"l{low}_esl", f"{low}_esl", curve.esl["henries"]) if curve.esl else None,
            ]
            series = [s for s in series if s]
            inner = series[0][1] if series else n2[3]  # the capacitance's own second node
            for k, (element, node, value) in enumerate(series):
                to = series[k + 1][1] if k + 1 < len(series) else n2[3]
                after.setdefault(last, []).append(f"{element} {node} {to} {value:.10g}")
            if series and begin is None:
                edits.setdefault(n2[0], []).append((n2[1], n2[2], inner))
            v = f"abs(v({n1[3]},{inner}))"
            terms = [f"pwl({v},{_pairs(curve.kept)})"] if curve.kept else []
            t0 = f"pwl(temper,{_pairs(curve.celsius)})" if curve.celsius else ""
            if curve.bias:
                # the maker's curve at 1 bias, over the share the DC bias curve keeps there: the
                # temperature factor at that bias, reached in proportion to the volts from 0 V's
                volts = curve.bias["volts"]
                there = _at(curve.kept, volts) if curve.kept else 1.0
                tb = f"pwl(temper,{_pairs([[c, s / there] for c, s in curve.bias['kept']])})"
                t0 = t0 or "1"
                terms.append(f"({t0}+({tb}-{t0})*min({v}/{volts:.10g},1))")
            elif t0:
                terms.append(t0)
        else:
            node, sense = f"{low}_kept", f"v{low}_kept"
            terms = [f"pwl(abs(i({sense})),{_pairs(curve.kept)})"]
            edits.setdefault(n2[0], []).append((n2[1], n2[2], node))
            after.setdefault(last, []).append(f"{sense} {node} {n2[3]} 0")
        expression = "*".join([factor, *terms])
        applied.append(name)
        if begin is not None:
            # the written element stays as a comment; the unit capacitor's current is dv/dt
            hidden.update(j2 for j2, _, _ in simcorners.statement_lines(lines, i))
            inner = series[0][1] if series else n2[3]
            after.setdefault(last, []).extend(
                [
                    f"b{low}_ic {n1[3]} {inner} I=i(v{low}_ic)*{expression}",
                    f"e{low}_ic {low}_ic_e 0 {n1[3]} {inner} 1",
                    f"v{low}_ic {low}_ic_e {low}_ic 0",
                    f"c{low}_ic {low}_ic 0 1 ic={begin:.10g}",
                ]
            )
            continue
        # `C='...'`: ngspice 42 takes the bare quoted form for another element, which stopped a run
        # on `Timestep too small` where the named form ran (tests/test_partdata.py)
        named = "" if tokens[tokens.index(place) - 1][3] == "=" else f"{curve.kind}="
        edits.setdefault(j, []).append((start, end, named + "'" + expression + "'"))
    for j, group in edits.items():
        line = lines[j]
        for start, end, new in sorted(group, reverse=True):
            line = line[:start] + new + line[end:]
        lines[j] = " ".join(line.split())  # an ic= taken off leaves its spaces
    out: list[str] = []
    for j, line in enumerate(lines):
        out.append(f"* {line}" if j in hidden else line)
        out += after.get(j, [])
    return "\n".join(out), sorted(applied), ideal
