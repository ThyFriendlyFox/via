"""partdata — the makers' data of a deck's capacitors and inductors, as the SIM gate runs them.

A capacitor's facts may hold `kept`, pairs [volts, share of the value kept] from its maker's DC bias
curve, and `kept_celsius`, pairs [celsius, share] from its temperature curve. An inductor's facts may
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
        if kept is None and celsius is None:
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
        rating = data.get("volts") if kind == "C" else data.get("amps_saturation")
        found[ref] = Curve(ref, kind, kept, celsius, entry.where, row.source, rating)
    return found, refused, unjudged


def short_of_rating(curve: Curve) -> str | None:
    """A curve that stops under the part's rating: past its last point the deck holds the last share."""
    if curve.rating is None or not curve.kept or curve.kept[-1][0] >= curve.rating:
        return None
    unit = UNIT[curve.kind]
    last = f"{curve.kept[-1][0]:g} {unit}"
    return f"{curve.ref}'s curve ends at {last}, under its rating of {curve.rating:g} {unit}"


def _pairs(pairs: list) -> str:
    return ",".join(f"{x:.10g},{y:.10g}" for x, y in pairs)


def _value(token: str) -> str | None:
    """A value token as a factor of an expression: a number as written, an expression in braces or
    quotes, each in parentheses. None for anything else: a model's name, a parameter's bare name."""
    if simcorners.spice_number(token) is not None:
        return f"({token})"
    if len(token) > 1 and (token[0], token[-1]) in (("{", "}"), ("'", "'")):
        return f"({token[1:-1]})"
    return None


def apply(
    text: str, curves: dict[str, Curve], included: dict[str, str] | None = None
) -> tuple[str, list[str], dict[str, str]]:
    """The deck with each part `curves` names written on its maker's data: (text, applied, ideal).
    `ideal` names each part the gate cannot rewrite, with the reason: it stands inside a .subckt (each
    copy would share 1 rewrite) or outside the deck's own lines, in a file of `included` (the path as
    the deck writes it, and its text); its value is no number and no expression; it has an ic=, which
    ngspice 42 drops from a behavioural C or L; or a K element couples it, and K names the inductor
    the gate replaces."""
    lines = text.split("\n")
    starts = simcorners.netlist_lines(lines)
    within: dict[int, str] = {}
    coupled: dict[str, str] = {}
    block = ""
    for i in starts:
        word = lines[i].split()[0].lower()
        if word == ".subckt":
            block = lines[i].split()[1] if len(lines[i].split()) > 1 else "?"
        elif word == ".ends":
            block = ""
        elif block:
            within[i] = block
        if word[0] == "k":
            for other in [t[3].upper() for t in simcorners.logical_tokens(lines, i)[1:3]]:
                coupled.setdefault(other, lines[i].split()[0])
    edits: dict[int, list[tuple[int, int, str]]] = {}
    after: dict[int, str] = {}
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
        if i in within:
            ideal[name] = f"it stands inside .subckt {within[i]}, which the gate does not rewrite"
            continue
        if name in coupled:
            ideal[name] = f"it is coupled by {coupled[name]}, which the gate does not rewrite"
            continue
        tokens = simcorners.logical_tokens(lines, i)
        if any(a[3].lower() == "ic" and b[3] == "=" for a, b in zip(tokens[3:], tokens[4:], strict=False)):
            state = "voltage" if curve.kind == "C" else "current"
            ideal[name] = (
                f"its ic= sets its starting {state}, which ngspice 42 drops from the element the gate writes"
            )
            continue
        place = simcorners.value_place(tokens)
        factor = _value(place[3]) if place else None
        if factor is None:
            ideal[name] = (
                f"its value {place[3] if place else 'that is missing'} is no number and no expression"
            )
            continue
        n1, n2 = tokens[1], tokens[2]
        j, start, end, _ = place
        if curve.kind == "C":
            terms = [f"pwl(abs(v({n1[3]},{n2[3]})),{_pairs(curve.kept)})"] if curve.kept else []
            terms += [f"pwl(temper,{_pairs(curve.celsius)})"] if curve.celsius else []
        else:
            node, sense = f"{name.lower()}_kept", f"v{name.lower()}_kept"
            terms = [f"pwl(abs(i({sense})),{_pairs(curve.kept)})"]
            edits.setdefault(n2[0], []).append((n2[1], n2[2], node))
            last = simcorners.statement_lines(lines, i)[-1][0]
            after[last] = f"{sense} {node} {n2[3]} 0"
        # `C='...'`: ngspice 42 takes the bare quoted form for another element, which stopped a run
        # on `Timestep too small` where the named form ran (tests/test_partdata.py)
        named = "" if tokens[tokens.index(place) - 1][3] == "=" else f"{curve.kind}="
        edits.setdefault(j, []).append((start, end, named + "'" + "*".join([factor, *terms]) + "'"))
        applied.append(name)
    for j, group in edits.items():
        line = lines[j]
        for start, end, new in sorted(group, reverse=True):
            line = line[:start] + new + line[end:]
        lines[j] = line
    out: list[str] = []
    for j, line in enumerate(lines):
        out.append(line)
        if j in after:
            out.append(after[j])
    return "\n".join(out), sorted(applied), ideal
