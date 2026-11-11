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

The order: the toolchain, the project's files, the design file against the KiCad files it generates,
the gates' report (run again when any input is newer), the first failure of the first red gate, the
first warning of a GREEN run, the verification package when the project has one. A failure or a
warning is answered from HINTS: the fix this workcenter's skills give for that kind of line.

Standard library only. `tools/workcenter` supplies the engines' names, `find_project` and the verdicts.
"""

from __future__ import annotations

import json
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
INPUT_SUFFIXES = (".kicad_sch", ".kicad_pcb", ".kicad_pro", ".kicad_dru")
RULE = "A bound, a rule or a requirement is never changed to pass: the design changes."

# A failure or warning line, as `gate: line`, and the fix for its kind: (pattern, what to do, what to
# read). The first pattern that matches answers; the last one matches everything.
HINTS: list[tuple[str, str, str]] = [
    (
        r"^erc: pin_not_connected",
        "Wire the pin, or place a no-connect flag on it.",
        f'{GATES}, "Common violations"',
    ),
    (r"^erc: power_pin_not_driven", "Add a PWR_FLAG symbol to the net.", f'{GATES}, "Common violations"'),
    (r"^erc: lib_symbol", "Update the symbol from its library.", f'{GATES}, "Common violations"'),
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
        "Give the deck's parts their temperature behaviour (a resistor's coefficient from its datasheet: "
        "`R1 a b 10k tc1=100u`; a model that carries temperature), or set the deck's temperature to false "
        "in sim/corners.json with why.",
        f'{SIMULATE}, "Corners"',
    ),
    (
        r"^sim: .*no tolerance covers",
        "Add the kind (R, C or L) or the part to tolerance in sim/corners.json, with its source.",
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
        r"^sim: \S+?:\S+=None ",
        "The deck does not print that measure. Print it as `name = value` (a complex value prints none: "
        "take its magnitude with vm()), or correct the name in the expect file.",
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
        r"^sim: no sim/frequency-plan\.json",
        "Write sim/frequency-plan.json: every periodic source with its frequency and where that comes "
        "from, every resonance an .ac deck measured. Copy templates/project/frequency-plan.json.",
        f'{SIMULATE}, "The frequency plan"',
    ),
    (
        r"^sim: frequency plan: .*no overlap answers it",
        "A source and a resonance meet. Move the source's frequency or the resonance apart, or damp the "
        "resonance. If they still meet, write a deck that runs the source at the resonance and bounds "
        "the result, and name it under overlaps in sim/frequency-plan.json.",
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
        "Sweep each supply rail with an .ac deck (a 1 A AC current source at the load reads the rail's "
        "impedance in ohms) and name the peak under resonances.",
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
    design = path / "design.py" if path.is_dir() else None
    try:
        project = cli.find_project(str(path))
    except SystemExit as exc:
        if design and design.is_file():
            return Step(
                "Generate the KiCad project from its design file.",
                f"{wc} design {quoted}/design.py --route",
                "the folder holds a design file and no KiCad project",
                f'{DESIGN}, "Steps"',
                "the command exits 0 and prints no pull:, via:, part: or island: line",
            )
        return Step(
            "Start the project. For a circuit to prove before any board, write its deck as "
            f"{quoted}/sim/<name>.cir with its bounds in sim/<name>.expect.json. For a board, write "
            f"{quoted}/design.py: the parts from the KiCad libraries, the nets as names.",
            f"{wc} sim {quoted}   (a deck)   or   {wc} design {quoted}/design.py --route   (a board)",
            str(exc),
            f'{SIMULATE}, "Steps"; {DESIGN}, "Steps"',
            f"`{wc} next {quoted}` names another step",
        )
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
        proc = subprocess.run(
            [sys.executable, str(cli.SRC_DIR / "tools" / "workcenter"), "design", str(design), "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            said = [ln for ln in proc.stdout.splitlines() if ln.strip()]
            return Step(
                "Regenerate the KiCad project: it no longer matches its design file.",
                f"{wc} design {shlex.quote(str(design))} --route",
                said[-1] if said else "design --check exited 1",
                f'{DESIGN}, "Steps"',
                f"`{wc} design {shlex.quote(str(design))} --check` exits 0",
            )
    report = project.dir / "build" / "gates.json"
    gates = f"{wc} gates {quoted}"
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
        return Step(
            "Install the toolchain: a gate did not run.",
            f"sudo {cli.SRC_DIR / 'install.sh'}",
            verdict,
            "ee-agent-kit/docs/ENGINES.md",
            f"`{wc} doctor` prints ok or degraded, then {gates}",
        )
    if verdict == "SKIPPED":
        return Step(
            "Give the gates something to run: the project holds no schematic, no board and no deck. "
            f"Write {quoted}/sim/<name>.cir, or {quoted}/design.py for a board.",
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
    return Step(
        "Nothing for the bench: the gates are GREEN with no warning.",
        f"{wc} verify {quoted} --init",
        "a board that leaves the bench needs its requirements proven: the command writes the skeleton",
        "ee-agent-kit/PROCESSES.md, P28",
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
    p = sub.add_parser(
        "next",
        help="name the one next step for a project: what to do, the command, why, what to read, and when "
        "it is done; exit 0 when nothing is left, 1 when a step is. Reads build/gates.json and "
        "build/verify.json; writes nothing",
    )
    p.add_argument("project", help="the project directory")
    p.add_argument(
        "--trust-design",
        action="store_true",
        help="do not run `design --check` on the project's design file (it takes a few seconds)",
    )
    p.set_defaults(run=lambda a: cmd_next(a, cli))
