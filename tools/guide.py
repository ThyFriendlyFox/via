#!/usr/bin/env python3
"""guide — the one next step for a project.

A project goes from a design file to fabrication outputs through a fixed order of steps, each with a
command and a check of its own. `workcenter next <project>` reads what is on disk and names the first
step that is not done: what to do, the command, why, what to read, and when the step is done. The
answer asks no judgement of its caller, so a person or an agent of any size follows the same path:

    NEXT       Run the gates.
    RUN        workcenter gates boards/psu
    WHY        build/gates.json is older than sim/ripple.cir
    READ       .claude/skills/board-gates/SKILL.md, "Steps"
    DONE WHEN  the last line starts with GREEN

The order: the path (a folder, or a KiCad file that names its project), the project's files, the
toolchain, the design file against the KiCad files it generates, a board with nets that hold no copper
(routed before the gates), the gates' report (run again when any
input is newer, or when it is from a run without an engine), the first failure of the first red gate,
the first warning of a GREEN run, the verification package when the project has one. A failure or a
warning is answered from HINTS: the fix this workcenter's skills give for that kind of line.

A reader runs every RUN line as written, so a RUN line is 1 command a shell takes, and an answer with
no such command has none. Each sentence of an answer is 1 instruction of at most 20 words
(ee-agent-kit/docs/STYLE.md, rules 1 and 2). The command writes nothing.

Standard library only. `tools/workcenter` supplies the engines' names, `find_project` and the verdicts.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

GATES = ".claude/skills/board-gates/SKILL.md"
DESIGN = ".claude/skills/board-design/SKILL.md"
SIMULATE = ".claude/skills/simulate/SKILL.md"
VERIFICATION = ".claude/skills/verification/SKILL.md"
RATINGS = ".claude/skills/ratings/SKILL.md"
INPUT_SUFFIXES = (".kicad_sch", ".kicad_pcb", ".kicad_pro", ".kicad_dru")
# A file of these names its project, as `find_project` reads it. Any other file is inside a project.
PROJECT_FILES = (".kicad_pro", ".kicad_sch", ".kicad_pcb")
# A path that is not there and ends like these is a file's name: a folder made under it is no project.
FILE_SUFFIXES = (*PROJECT_FILES, ".cir", ".json", ".py")
RULE = "A bound, a rule or a requirement is never changed to pass: the design changes."

# A failure or warning line, as `gate: line`, and the fix for its kind: (pattern, what to do, what to
# read). The first pattern that matches answers; the last one matches everything.
HINTS: list[tuple[str, str, str]] = [
    # `workcenter ratings`: its lines begin with their status, and a file it does not take with its name.
    (
        r"^ratings: .*no facts for ",
        "Write the part's facts from its datasheet. `workcenter ratings <project> --facts <REF>` prints "
        "the entry to fill.",
        f'{RATINGS}, "Steps"',
    ),
    (
        r"^ratings: .*can put a voltage on ",
        "A connector's pin. A source behind it: state the net under `nets`. A load: state its `amps` "
        "under `parts`.",
        f'{RATINGS}, "Steps"',
    ),
    (
        r"^ratings: not judged .*its facts hold no voltage rating",
        "Add `volts` to the capacitor's facts from its datasheet. With no datasheet in `library/`, "
        "get it first.",
        f'{RATINGS}, "A part\'s facts"',
    ),
    (
        r"^ratings: not judged .*its facts hold no current rating",
        "`ratings.json` states a current through the part. Add the rating to the part's facts from its "
        "datasheet. It is `amps_forward` for a diode, `amps_drain` for a transistor and `amps` for a "
        "ferrite or a switch.",
        f'{RATINGS}, "A part\'s facts"',
    ),
    (
        r"^ratings: not judged .* and has no facts",
        "Write the facts of the part the line names. `workcenter ratings <project> --facts <REF>` "
        "prints the entry to fill.",
        f'{RATINGS}, "Steps"',
    ),
    (
        r"^ratings: not judged .*accepts a failure of .* is not judged now",
        "Give that part what its own `not judged` line asks for. The acceptance then meets its "
        "failure again.",
        f'{RATINGS}, "Steps"',
    ),
    (
        r"^ratings: not judged .*no source holds ",
        "No source the command knows holds the net. State the net in `nets`, or correct the facts of "
        "the part that drives it. For a net behind a sense resistor, state the resistor's current "
        "under `parts`.",
        f'{RATINGS}, "Steps"',
    ),
    (
        r"^ratings: not judged ",
        "Give the command what the line says is missing: a fact, a net's voltage or a load's current.",
        f'{RATINGS}, "Steps"',
    ),
    (
        r"^ratings: fail .*stands forward between 2 sources",
        "Turn the diode, or take 1 of the 2 sources off its nets. Nothing limits its current as drawn.",
        f'{RATINGS}, "How the command reads a circuit"',
    ),
    (
        r"^ratings: fail .*number the pins differently",
        "Hold the facts and the symbol to the datasheet's package drawing. An entry's pin numbers are "
        "the symbol's. A symbol that is wrong is a fault of the design.",
        f'{RATINGS}, "A part\'s facts"',
    ),
    (
        r"^ratings: fail .*accepts a failure of ",
        "Take that entry out of `accepted` in ratings.json: nothing fails there now.",
        f'{RATINGS}, "ratings.json"',
    ),
    (
        r"^ratings: fail ",
        "Change the design until the stress holds: a part with a higher rating, a lower voltage, a "
        "smaller load. Never change a fact, a net's voltage or a pack to pass.",
        f'{RATINGS}, "Steps"',
    ),
    # a refusal names the file first: a parts file's row, the schematic, the output folder, ratings.json
    # a name may hold a space ("My Board"), never a colon
    (
        r"^ratings: [^:]+\.csv:\d+: ",
        "Give the row of the parts file every field its header names, an empty one where nothing is "
        "known. `procure` and `sources` read the same file.",
        f'{RATINGS}, "Inputs"',
    ),
    (
        r"^ratings: [^:]+\.csv: ",
        "The parts file cannot be read, for the reason the line gives: it is not there, it is not UTF-8, "
        "or its CSV is broken. Name the file with `--parts`, or save it as UTF-8 CSV.",
        f'{RATINGS}, "Inputs"',
    ),
    (
        r"^ratings: [^:]+\.kicad_sch: ",
        "The netlist kicad-cli exports from the schematic holds what the line names. Correct the schematic "
        "in its design file and regenerate it, then run `workcenter erc` on it.",
        f'{RATINGS}, "Inputs"',
    ),
    (
        r"^ratings: (--out \S|(/[^:]*)?build: )",
        "The run cannot make its output folder there: a file stands in its place, or the folder cannot be "
        "written. Name another folder with `--out`, or move the file.",
        f'{RATINGS}, "Steps"',
    ),
    (
        r"^ratings: ratings\.json: ",
        "Correct the file at the place the line names. Each key of ratings.json is in the skill.",
        f'{RATINGS}, "ratings.json"',
    ),
    (
        r"^ratings: \S+\.json: ",
        "Correct the file at the place the line names. The skill has every key.",
        f'{RATINGS}, "A part\'s facts"',
    ),
    (r"^ratings: ", "Read build/ratings/report.md and act on its first line.", f"{RATINGS}"),
    (
        r"^erc: pin_not_connected",
        "Wire the pin, or place a no-connect flag on it.",
        f'{GATES}, "Common violations"',
    ),
    (r"^erc: power_pin_not_driven", "Add a PWR_FLAG symbol to the net.", f'{GATES}, "Common violations"'),
    (r"^erc: lib_symbol", "Update the symbol from its library.", f'{GATES}, "Common violations"'),
    (
        r"^erc: simulation_model_issue",
        "KiCad cannot load the model a part names. The fault is the file, the name in it, or a node of "
        "its pin map. Correct the part's d.sim() in the design file. A part outside the simulation gets "
        "a d.no_sim() with the reason. Regenerate the KiCad project after the change.",
        f'{DESIGN}, "Steps"',
    ),
    (
        r"^design: sim: ",
        "Correct what the design file says about that part's simulation. A d.sim() names every pin "
        "number of the symbol in `pins`. Each pin maps to a node of the model, or to None. The d.sim() "
        "names every node of the model once. Its library path starts at the design's folder. A part "
        "outside the simulation gets a d.no_sim() with the reason.",
        f'{DESIGN}, "Steps"',
    ),
    (
        r"^design: pull: ",
        "Hold the net at a level with a resistor to a rail, or name it in d.defined_nets with why.",
        f'{DESIGN}, "Steps"',
    ),
    (
        r"^design: via: ",
        "Move the via, or give it a size the board's rules allow.",
        f'{DESIGN}, "Steps"',
    ),
    (
        r"^design: file: ",
        "Correct the design file as the line says: it names what to write.",
        f'{DESIGN}, "Steps"',
    ),
    (
        r"^design: part: .*every pad lies outside the outline",
        "Write the part's pcb_at in board coordinates, from the corner the line names.",
        f'{DESIGN}, "Steps"',
    ),
    (
        r"^design: part: ",
        "Move the part out of the area the design keeps parts out of.",
        f'{DESIGN}, "Steps"',
    ),
    (
        r"^drc: clearance",
        "Move the track or the pad apart; check the net class clearance.",
        f'{GATES}, "Common violations"',
    ),
    (r"^drc: track_width", "Widen the track to the net class minimum.", f'{GATES}, "Common violations"'),
    (
        r"^drc: unconnected_items",
        "Route the net: give the router room or draw the link in the design file, then route once more.",
        f'{GATES}, "Common violations"',
    ),
    (
        r"^drc: (schematic_parity|.*parity)",
        "The board differs from the schematic. Regenerate both from the design file.",
        f'{GATES}, "Common violations"',
    ),
    (r"^drc: courtyards_overlap", "Move the footprint.", f'{GATES}, "Common violations"'),
    (r"^drc: silk", "Move the silkscreen text off the copper or the edge.", f'{GATES}, "Common violations"'),
    (
        r"^sim: no sim/corners\.json",
        "Write sim/corners.json: the temperature range from the requirement it comes from and each part's "
        "tolerance from its datasheet. Copy templates/project/corners.json and fill every source.",
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: the corners of sim/corners\.json were not run",
        "Run the gate without --nominal.",
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: .*no measure moves with temperature",
        "Give the deck's parts their temperature behaviour. A resistor takes its coefficient from its "
        "datasheet: `R1 a b 10k tc1=100u`. Another part takes a model that carries temperature. The "
        "other way: set the deck's temperature to false in sim/corners.json, with why.",
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: .*no tolerance covers",
        "Add the kind (R, C or L) or the part to tolerance in sim/corners.json, with its source.",
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: .*which a corner cannot scale",
        "A corner scales the value `alter` sets only when the deck writes it as a number. Write that "
        "value as a number in the `alter` line.",
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: .*which a corner cannot move",
        "Take that name out of tolerance.parts in sim/corners.json: no corner moves such a part. Write a "
        "value whose spread matters as a .param, and name the .param under tolerance.parts.",
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: .*which no corner moves",
        "Write those parts in the deck, not in the file it includes. A corner reads the deck's own "
        "lines only.",
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: .*in \.subckt \S+ is \d+ parts on the board",
        "Write each of those parts as its own element, outside the .subckt. A corner then moves each "
        "part on its own.",
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: .*the worst case is searched",
        'Name monte_carlo in sim/corners.json with its runs and its seed: `"monte_carlo": {"runs": 100, '
        '"seed": 1}`. Its draws move the parts together.',
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: .*is not printed at ",
        "The deck prints that measure as written and not at that corner. Read the corner's log under "
        "build/sim/corners/ at its first error line. Write the measure so it exists at every corner.",
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: .*corners\.json: ",
        "Correct sim/corners.json as the line says.",
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: .*: at .*(ran at|is not confirmed)",
        "The deck sets its own temperature in .control, so a corner cannot. Remove that line, or set the "
        "deck's temperature to false in sim/corners.json with why.",
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: .*is held at its own temperature",
        "A part's line fixes its temperature (temp=27), so a hot or a cold run leaves it there. Remove "
        "the setting, or set the deck's temperature to false in sim/corners.json with why.",
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: .*ngspice reads the value",
        "Write the value the way ngspice reads a number: 4.7k, not 4k7. It drops a digit after the scale "
        "letter and says nothing.",
        f'{SIMULATE}, "Steps"',
    ),
    (
        r"^sim: .*ngspice applies only the first parameter on the line",
        "Split the altermod line: 1 parameter to a line, each `altermod <model> <name>=<value>`. ngspice "
        "keeps the first parameter of a line and drops the rest without a word.",
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: \S+?:\S+=None ",
        "The deck does not print that measure. Print it as `name = value`, or correct the name in the "
        "expect file. A complex value prints none: take its magnitude with vm().",
        f'{SIMULATE}, "Steps"',
    ),
    (
        r"^sim: .*the deck prints \S+ more than once",
        "Print each measure once: the gate holds every printed value to the bound. Give each further "
        "value a name of its own.",
        f'{SIMULATE}, "Steps"',
    ),
    (
        r"^sim: \S+?:\S+=\S+ at .* not in \[",
        "The circuit is inside its bound as written and outside it at that corner. Change the circuit: "
        f"a tighter part, another value, another topology. {RULE}",
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: \S+?:\S+=\S+ not in \[",
        f"The circuit misses its bound. Change the values in the design, then the deck. {RULE}",
        f'{SIMULATE}, "Steps"',
    ),
    (
        r"^sim: .*ngspice exit",
        "ngspice did not run the deck to its end. Read the deck's log at its first error line; "
        "`Timestep too small` is a circuit ngspice cannot solve at that instant.",
        f'{SIMULATE}, "Steps"',
    ),
    (
        r"^sim: .*expect\.json: ",
        'Correct the expect file: each measure is {"min": n, "max": n} (one of them is enough) with its '
        "source.",
        f'{SIMULATE}, "Inputs"',
    ),
    (
        r"^sim: .*no bound in an expect file",
        "Write the deck's expect file: a bound for each value the deck exists to prove, with its source.",
        f'{SIMULATE}, "Inputs"',
    ),
    (
        r"^sim: .*ngspice: Warning: singular matrix",
        "A node has no path to ground at DC, so its voltage means nothing. Give it the path the real "
        "circuit has (the load, a bleed resistor), or remove the node.",
        f'{SIMULATE}, "Steps"',
    ),
    (
        r"^sim: thermal: .* junction \S+ C, over ",
        "The part runs past its derated junction limit at that corner. Take power off it, or choose a "
        f"package with a lower RthetaJA. Never narrow the corner. {RULE}",
        f'{SIMULATE}, "A part\'s temperature"',
    ),
    (
        r"^sim: (thermal: |.*thermal\.json: )",
        "Do what the line asks: write the part's thermal facts, print its power at every run, or correct "
        "sim/thermal.json.",
        f'{SIMULATE}, "A part\'s temperature"',
    ),
    (
        r"^sim: no sim/frequency-plan\.json",
        "Write sim/frequency-plan.json: every periodic source with its frequency and where that comes "
        "from, every resonance an .ac deck measured. Copy templates/project/frequency-plan.json.",
        f'{SIMULATE}, "The frequency plan"',
    ),
    (
        r"^sim: frequency plan: .*no overlap answers it",
        "A source and a resonance meet. Move the source's frequency or the resonance apart, or damp the "
        "resonance. If they still meet, write a deck that runs the source at the resonance. Bound the "
        "deck's result in its expect file. Name the deck under overlaps in sim/frequency-plan.json.",
        f'{SIMULATE}, "The frequency plan"',
    ),
    (
        r"^sim: frequency plan: .*which the plan does not name",
        "Name that source in sim/frequency-plan.json; a stimulus that is one event is written without a "
        "period.",
        f'{SIMULATE}, "The frequency plan"',
    ),
    (
        r"^sim: frequency plan: .*names no resonance",
        "Sweep each supply rail with an .ac deck. A 1 A AC current source at the load reads the rail's "
        "impedance in ohms. Name the peak under resonances in sim/frequency-plan.json.",
        f'{SIMULATE}, "The frequency plan"',
    ),
    (
        r"^sim: frequency plan: .*which no tolerance moves",
        "Give that deck its tolerances in sim/corners.json: the resonance then moves with its parts. A "
        "deck under `skip`, or with `tolerance` set to false, moves no part.",
        f'{SIMULATE}, "The frequency plan"',
    ),
    (
        r"^sim: .*is periodic and the deck gives its frequency as no number",
        "The plan reads the deck's text: it places a frequency only when the deck gives a number. Write "
        "the stimulus's period or frequency as a number. Write a PWL that repeats, or an expression of "
        "time, as a PULSE or a SIN.",
        f'{SIMULATE}, "The frequency plan"',
    ),
    (
        r"^sim: (frequency plan: |.*frequency-plan\.json: )",
        "Correct sim/frequency-plan.json as the line says.",
        f'{SIMULATE}, "The frequency plan"',
    ),
    (
        r"^sim: .*changed since its sources row",
        "A library file differs from its row in library/sources.csv. Restore the maker's file, or fetch "
        "its new revision and update the row. A maker's file is never edited.",
        "ee-agent-kit/PROCESSES.md, P27",
    ),
    (
        r"^sim: .*has no row in a library's sources\.csv",
        "Give the model its row: `workcenter fetch <url> --to library/<maker>/<file> --mpn <MPN> --row`.",
        "ee-agent-kit/PROCESSES.md, P27",
    ),
    (
        r"^verify: traceability: .* says PASS, .* is FAIL at ",
        "The requirement holds as the deck is written and fails at that corner. Change the design, or "
        "write FAIL in the row with its size and a proposed fix.",
        f'{VERIFICATION}, "Corners"',
    ),
    (
        r"^verify: REQ-\S+: judged as written only",
        "A requirement holds at every corner, and its deck ran none. Give the deck its corners in "
        "sim/corners.json. The line's last words say why it ran none.",
        f'{VERIFICATION}, "Corners"',
    ),
    (
        r"^verify: (REQ-\S+: (FAIL|OPEN)|.*no sim/corners\.json)",
        "A requirement is not met. FAIL: change the design. OPEN: produce the evidence the row names. "
        "No corners: write sim/corners.json.",
        f"{VERIFICATION}",
    ),
    (r"^verify: ", "Correct the verification package as the line says.", f"{VERIFICATION}"),
    (r"", f"Read the gate's report, then fix the design. {RULE}", f'{GATES}, "Steps"'),
]


@dataclass
class Step:
    """One answer of `next`."""

    next: str
    run: str = ""
    why: str = ""
    read: str = ""
    done_when: str = ""
    done: bool = False  # nothing is left to do


def hint(gate: str, line: str) -> tuple[str, str]:
    """What to do about a failure or warning line of a gate, and what to read."""
    for pattern, do, read in HINTS:
        if re.search(pattern, f"{gate}: {line}"):
            return do, read
    raise AssertionError("the last hint matches every line")


def inputs_of(project) -> list[Path]:
    """The files a gates report is made from: when one is newer than the report, the report is stale."""
    found = [p for p in project.dir.iterdir() if p.suffix in INPUT_SUFFIXES or p.name == "design.py"]
    sim = project.dir / "sim"
    found += [p for p in sim.rglob("*") if p.is_file()] if sim.is_dir() else []
    return sorted(found)


def ratings_inputs(cli, project) -> list[Path]:
    """The files a ratings report is made from: the schematic, ratings.json, the project's parts file
    and the facts of the library the command finds."""
    named = ("ratings.json", "parts.csv")
    found = sorted(p for p in project.dir.iterdir() if p.suffix == ".kicad_sch" or p.name in named)
    library = cli.ratings().find_facts(project.dir)
    return found + (sorted(library.glob("*.json")) if library else [])


# The board file's text, as `unrouted` reads it: a quoted string (parentheses in it are no block), or a
# parenthesis. A block's head is the word after its parenthesis; a net is `(net 3 "GND")` in a pad,
# `(net 3)` or `(net "GND")` in a track, a via or a pour.
BOARD_TOKEN_RE = re.compile(r'"(?:[^"\\]|\\.)*"|[()]')
HEAD_RE = re.compile(r"[a-z_]+")
NET_RE = re.compile(r'\(net\s+(?:(\d+)\s*)?(?:"((?:[^"\\]|\\.)*)"\s*)?\)')
COPPER_HEADS = ("segment", "arc", "via", "zone")


def unrouted(pcb: Path) -> tuple[int, list[str]]:
    """The nets of 2 pads or more that hold no track, via or pour on the board, and their pads' count.
    A net with some copper is not named: whether it joins every pad is DRC's to judge."""
    # A byte that is not UTF-8 (a board saved by another tool) becomes U+FFFD: the nets are still told
    # apart, and `next` names a step rather than stopping on it.
    text = pcb.read_text(encoding="utf-8", errors="replace")
    names: dict[str, str] = {}
    pads: dict[str, int] = {}
    copper: set[str] = set()
    starts: list[int] = []
    for m in BOARD_TOKEN_RE.finditer(text):
        if m.group() == "(":
            starts.append(m.start())
        elif m.group() == ")" and starts:
            start = starts.pop()
            depth = len(starts)  # 1: a child of the board; 2: a pad of a footprint
            if depth not in (1, 2):
                continue
            head = HEAD_RE.match(text, start + 1)
            word = head.group() if head else ""
            if not (word == "net" and depth == 1 or word in COPPER_HEADS and depth == 1 or word == "pad"):
                continue
            net = NET_RE.search(text, start, m.end())
            if not net:
                continue
            if word == "net":
                names[net.group(1) or ""] = net.group(2) or ""
            elif word == "pad":
                name = net.group(2) if net.group(2) is not None else names.get(net.group(1), "")
                pads[name] = pads.get(name, 0) + 1
            else:
                copper.add(net.group(2) if net.group(2) is not None else names.get(net.group(1), ""))
    loose = sorted(
        n
        for n, count in pads.items()
        if count > 1 and n and not n.startswith("unconnected-") and n not in copper
    )
    return sum(pads[n] for n in loose), loose


def newest(report: Path, inputs: list[Path]) -> Path | None:
    """The first input newer than the report, or None."""
    made = report.stat().st_mtime
    return next((p for p in inputs if p.stat().st_mtime > made), None)


def trouble(cli, results: list) -> tuple[str, str, bool] | None:
    """The first thing a gates run asks for: (gate, line, whether it is a failure). A red gate's first
    failure, else the first warning of any gate, else None."""

    def lines(result, severity: str) -> list[str]:
        out = []
        for v in result.details.get("first", []):
            if str(v.get("severity", "")).lower() == severity:
                pos = v.get("pos") or {}
                at = f" at ({pos.get('x')}, {pos.get('y')})" if pos else ""
                out.append(f"{v.get('type')}: {v.get('description')}{at}")
        return out

    for r in results:
        if r.status in ("fail", "error"):
            said = lines(r, "error") + list(r.details.get("failures", [])) + lines(r, "warning")
            return r.gate, (said[0] if said else r.summary), True
    for r in results:
        said = lines(r, "warning") + [w for w in r.details.get("warnings", [])]
        if said:
            return r.gate, said[0], False
    return None


def next_step(cli, target: str, run_check=True) -> Step:
    """The first step a project has not done. `run_check` runs `design --check` for a project with a
    design file (a few seconds); without it the design file is trusted to match."""
    wc = "workcenter"
    path = Path(target).resolve()
    quoted = shlex.quote(target)
    # A folder that holds a chip.json is a chip project: its steps are the chip gates' (chipguide.py).
    import chipguide

    if chipguide.is_chip(path):
        return chipguide.next_step(cli, target)

    def to_folder(file: Path, why: str) -> Step:
        """A file is no project: the answer names its folder, the one above sim/ for a deck. Taken
        for a project, a deck gets its build/ inside sim/ and its next steps under its own name."""
        folder = file.parent.parent if file.parent.name == "sim" else file.parent
        again = f"{wc} next {shlex.quote(str(folder))}"
        return Step(
            "Name the project's folder: the path leads to a file, and a project is a folder.",
            again,
            why,
            done_when=f"`{again}` names another step",
        )

    if path.is_file() and path.suffix not in PROJECT_FILES:
        return to_folder(path, f"{path} is a file; a project is named by its folder")
    try:
        project = cli.find_project(str(path))
    except SystemExit as exc:
        why = str(exc)
        again = f"`{wc} next {quoted}` names another step"
        if not path.exists():
            above = next(p for p in path.parents if p.exists())
            if above.is_file():
                return to_folder(above, f"{why}; {above} is a file")
            if path.suffix in FILE_SUFFIXES:
                return to_folder(path, f"{why}; a project is named by its folder")
            return Step(
                "Create the project's folder: it does not exist yet.",
                f"mkdir -p {quoted}",
                why,
                done_when=again,
            )
        pros = sorted(path.glob("*.kicad_pro")) if path.is_dir() else []
        if len(pros) > 1:
            # Before the design file: generated again, the folder holds as many project files.
            one = f"{wc} next {shlex.quote(str(Path(target) / pros[0].name))}"
            return Step(
                f"Name one of the folder's {len(pros)} project files: {', '.join(p.name for p in pros)}. "
                "The RUN line names the first.",
                one,
                why,
                done_when=f"`{one}` names another step",
            )
        if (path / "design.py").is_file():
            return Step(
                "Generate the KiCad project from its design file.",
                f"{wc} design {quoted}/design.py --route",
                "the folder holds a design file and no KiCad project",
                f'{DESIGN}, "Steps"',
                "the command exits 0 and prints no file:, sim:, pull:, via:, part: or island: line",
            )
        # A board is the common start, and its command reads nothing but the template: this answer
        # runs no engine. A deck or a chip starts otherwise, and the answer says how.
        return Step(
            "Start a board project: the RUN line writes design.py from the template, and the files beside "
            f"it. To prove a circuit before any board, write its deck as {quoted}/sim/<name>.cir instead. "
            f"Write the deck's bounds in {quoted}/sim/<name>.expect.json "
            '(`{"vout": {"min": 2.4, "max": 2.6, "source": "the spec\'s line"}}`). '
            f"For a chip, `{wc} chip init {quoted} --top <module>` writes the project's first files.",
            f"{wc} new {quoted}",
            why,
            f'{DESIGN}, "Steps"; {SIMULATE}, "Steps"; {chipguide.DESIGN}, "Steps"',
            f"`{wc} next {quoted}` names the design step",
        )
    # A command takes the project as it was named, a KiCad file too. A path inside the project starts
    # at its folder.
    folder = quoted if path.is_dir() else shlex.quote(str(project.dir))
    has_kicad = bool(project.sch or project.pcb)
    decks = sorted((project.dir / "sim").glob("*.cir")) if (project.dir / "sim").is_dir() else []
    absent = [
        name
        for name, needed in ((cli.KICAD_CLI, has_kicad), (cli.NGSPICE, bool(decks)))
        if needed and not shutil.which(name)
    ]
    if absent:
        return Step(
            "Install the toolchain: a gate cannot run without its engine.",
            f"sudo {cli.SRC_DIR / 'install.sh'}",
            f"{', '.join(absent)} is not on PATH",
            "ee-agent-kit/docs/ENGINES.md",
            f"`{wc} doctor` prints ok or degraded",
        )
    design = project.dir / "design.py"
    if design.is_file() and run_check:
        # The check imports the design file. Bytecode beside it would be a file `next` wrote.
        proc = subprocess.run(
            [sys.executable, str(cli.SRC_DIR / "tools" / "workcenter"), "design", str(design), "--check"],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if proc.returncode != 0:
            said = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
            regenerate = f"{wc} design {shlex.quote(str(design))} --route"
            # The design step's own refusal comes before any comparison: regenerating a design file
            # that is refused gives the same refusal. Its red line names the kinds; the first printed
            # line of a kind it names is the problem to answer.
            red = next((ln for ln in said if re.match(r"design .+ red: ", ln)), "")
            kinds = [
                kind
                for kind, word in (
                    ("file", "the design file is refused"),
                    ("sim", "simulation"),
                    ("via", "via"),
                    ("part", "part("),
                    ("pull", "floating"),
                )
                if word in red
            ]
            first = next((ln for kind in kinds for ln in said if ln.startswith(f"{kind}: ")), None)
            if first:
                do, read = hint("design", first)
                return Step(
                    do,
                    regenerate,
                    f"the design file is refused: {first}",
                    read,
                    f"`{wc} design {shlex.quote(str(design))} --check` exits 0",
                )
            return Step(
                "Regenerate the KiCad project: it no longer matches its design file.",
                regenerate,
                said[-1] if said else "design --check exited 1",
                f'{DESIGN}, "Steps"',
                f"`{wc} design {shlex.quote(str(design))} --check` exits 0",
            )
    # A project with a ratings.json is held to its parts' ratings. A failure there comes before the
    # board's gates: a part that changes takes its routes with it. What is left not judged comes after.
    ratings = f"{wc} ratings {quoted}"
    rated = None  # the record of the last ratings run
    if (project.dir / "ratings.json").is_file() and project.sch:
        record = project.dir / "build" / "ratings" / "report.json"
        newer = newest(record, ratings_inputs(cli, project)) if record.is_file() else None
        if not record.is_file() or newer:
            return Step(
                "Hold the schematic to its parts' ratings.",
                ratings,
                f"{newer.name} changed after the last run" if newer else "no build/ratings/report.json yet",
                f'{RATINGS}, "Steps"',
                "the last line starts with RATINGS HELD",
            )
        rated = cli.Result(**json.loads(record.read_text(encoding="utf-8")))
        failures = rated.details.get("failures", []) or ([rated.summary] if rated.status == "error" else [])
        if failures:
            do, read = hint("ratings", failures[0])
            return Step(
                do, ratings, f"RATINGS failed: {failures[0]}", read, "the last line starts with RATINGS HELD"
            )
    report = project.dir / "build" / "gates.json"
    gates = f"{wc} gates {quoted}"
    # A board generated without --route has nets with no copper: the gates would fail on each. The
    # route comes first, while the gates are still to run.
    if design.is_file() and project.pcb and (not report.is_file() or newest(report, inputs_of(project))):
        pads, loose = unrouted(project.pcb)
        if loose:
            shown = ", ".join(loose[:3]) + (f" and {len(loose) - 3} more" if len(loose) > 3 else "")
            return Step(
                "Route the board before the gates: nets on it have no copper yet.",
                f"{wc} design {shlex.quote(str(design))} --route",
                f"{pads} pads on {len(loose)} nets have no track, via or pour: {shown}",
                f'{DESIGN}, "Steps"',
                "the command exits 0 and prints no file:, sim:, pull:, via:, part: or island: line",
            )
    if not report.is_file():
        return Step(
            "Run the gates.",
            gates,
            "no build/gates.json yet",
            f'{GATES}, "Steps"',
            "the last line starts with GREEN",
        )
    newer = newest(report, inputs_of(project))
    if newer:
        return Step(
            "Run the gates again: an input changed after the last run.",
            gates,
            f"build/gates.json is older than {newer.relative_to(project.dir)}",
            f'{GATES}, "Steps"',
            "the last line starts with GREEN",
        )
    results = [cli.Result(**r) for r in json.loads(report.read_text(encoding="utf-8"))]
    verdict, _ = cli.gates_verdict(results)
    if verdict.startswith("SKIPPED ("):
        # Every engine the project needs was found above, so the report is older than the toolchain.
        # An answer to install it here is given again after every installation.
        return Step(
            "Run the gates again: the report is from a run with an engine absent.",
            gates,
            f"build/gates.json says {verdict}; every engine the project needs is on PATH now",
            f'{GATES}, "Steps"',
            "the last line starts with GREEN",
        )
    if verdict == "SKIPPED":
        return Step(
            "Give the gates something to run: the project holds no schematic, no board and no deck. "
            f"Write {folder}/sim/<name>.cir, or {folder}/design.py for a board.",
            gates,
            "every gate was skipped: " + "; ".join(f"{r.gate}: {r.summary}" for r in results),
            f'{SIMULATE}, "Steps"; {DESIGN}, "Steps"',
            "the last line starts with GREEN",
        )
    found = trouble(cli, results)
    if found:
        gate, line, failed = found
        do, read = hint(gate, line)
        return Step(
            do,
            gates if failed else f"{gates} --strict",
            f"{gate.upper()} {'failed' if failed else 'warns'}: {line}",
            read,
            "the last line is GREEN, with no warning" if not failed else "the last line starts with GREEN",
        )
    if rated is not None and rated.details.get("verdict") != "RATINGS HELD":
        left = rated.details.get("warnings", []) or [rated.details.get("verdict") or rated.summary]
        do, read = hint("ratings", left[0])
        return Step(
            do,
            f"{ratings} --strict",
            f"RATINGS not judged whole: {left[0]}",
            read,
            "the last line is RATINGS HELD",
        )
    package = project.dir / "verification"
    if package.is_dir():
        verify = f"{wc} verify {quoted} --strict"
        record = project.dir / "build" / "verify.json"
        newer = (
            None
            if not record.is_file()
            else newest(record, inputs_of(project) + sorted(package.rglob("*.md")))
        )
        if not record.is_file() or newer:
            why = (
                "no build/verify.json yet"
                if not record.is_file()
                else f"{newer.name} changed after the last run"
            )
            return Step(
                "Check the verification package against a fresh run.",
                verify,
                why,
                f"{VERIFICATION}",
                "the last line starts with REQUIREMENTS MET",
            )
        result = cli.Result(**json.loads(record.read_text(encoding="utf-8")))
        said = cli.requirements_verdict(result)
        if not said.startswith("REQUIREMENTS MET"):
            failures = result.details.get("failures", [])
            line = failures[0] if failures else said
            do, read = hint("verify", line)
            return Step(do, verify, line, read, "the last line starts with REQUIREMENTS MET")
        return Step(
            "Nothing: the gates are GREEN with no warning and the requirements are met.",
            why="close out the change: ee-agent-kit/PROCESSES.md, P14",
            done=True,
        )
    # A finished project gets no RUN line: a reader who follows each line would run one more command.
    if not has_kicad:
        return Step(
            "Nothing: every deck holds its bounds, GREEN with no warning.",
            why="the project holds decks and no board; a board starts with a design file "
            f'({DESIGN}, "Steps")',
            done=True,
        )
    unrated = (
        f"`{ratings} --init` starts holding the schematic to its parts' ratings ({RATINGS}). "
        if rated is None
        else ""
    )
    return Step(
        "Nothing for the bench: the gates are GREEN with no warning.",
        why="a board that leaves the bench has its parts and its requirements proven first. "
        f"{unrated}"
        f"`{wc} sources {quoted}` holds each part to its datasheet and its model "
        "(ee-agent-kit/PROCESSES.md, P27). "
        f"`{wc} verify {quoted} --init` starts the requirements (ee-agent-kit/PROCESSES.md, P28)",
        done=True,
    )


def cmd_next(args, cli) -> int:
    step = next_step(cli, args.project, run_check=not args.trust_design)
    if args.json:
        print(json.dumps(step.__dict__, indent=2))
    else:
        for label, value in (
            ("NEXT", step.next),
            ("RUN", step.run),
            ("WHY", step.why),
            ("READ", step.read),
            ("DONE WHEN", step.done_when),
        ):
            if value:
                print(f"{label:10} {value}")
    return 0 if step.done else 1


def register(sub, cli) -> None:
    """Add this module's command to the workcenter's parser; it sets `run` to its handler."""
    text = (
        "name the one next step for a project: what to do, the command, why, what to read, and when "
        "it is done; exit 0 when nothing is left, 1 when a step is named (no error: do the step). Reads "
        "build/gates.json and build/verify.json; writes nothing; runs no engine on a folder without a design"
    )
    p = sub.add_parser("next", help=text, description=text[0].upper() + text[1:] + ".")
    p.add_argument("project", help="the project directory")
    p.add_argument(
        "--trust-design",
        action="store_true",
        help="do not run `design --check` on the project's design file (it takes a few seconds)",
    )
    p.set_defaults(run=lambda a: cmd_next(a, cli))
