#!/usr/bin/env python3
"""chipguide — the one next step for a chip project.

A chip project goes from RTL to a mask layout through a fixed order of steps, as a board does through
its own (tools/guide.py). `workcenter next <project>` hands a folder that holds a chip.json to this
module, which reads what is on disk and names the first step that is not done:

    NEXT       Run the chip gates.
    RUN        workcenter chip gates chips/uart
    WHY        no build/gates.json yet
    READ       .claude/skills/chip-gates/SKILL.md, "Steps"
    DONE WHEN  the last line starts with GREEN

The order: chip.json, the engines and the process kit, the RTL, a bench, the gates' report (run again
when a file a gate reads is newer, or when the report is from a run without an engine), the first
failure of the first red gate, the first warning of a GREEN run. A failure or a warning is answered
from HINTS: the fix this workcenter's skills give for that kind of line. Most lines of the chip gates
say what to do themselves; the hint adds where to read.

A reader runs every RUN line as written, so a RUN line is 1 command a shell takes, and an answer with
no such command has none. Each sentence of an answer is 1 instruction of at most 20 words
(ee-agent-kit/docs/STYLE.md, rules 1 and 2). The command writes nothing and starts no engine.

Standard library only. tools/chipflow.py reads chip.json and finds the engines; tools/chipfront.py
names the files a gate reads.
"""

from __future__ import annotations

import json
import re
import shlex
from pathlib import Path

import chipflow
import chipfront
from guide import Step

DESIGN = ".claude/skills/chip-design/SKILL.md"
GATES = ".claude/skills/chip-gates/SKILL.md"
RULE = "A limit, a bound or a constraint is never changed to pass: the design changes."

# A failure or warning line, as `gate: line`, and the fix for its kind: (pattern, what to do, what to
# read). The first pattern that matches answers; the last one matches everything.
HINTS: list[tuple[str, str, str]] = [
    (
        r"^\w+: chip\.json: pdk\.",
        "Correct the pdk block of chip.json as the line says.",
        f'{DESIGN}, "chip.json"',
    ),
    (r"^\w+: chip\.json: ", "Correct chip.json as the line says.", f'{DESIGN}, "chip.json"'),
    (r"^lint: (LATCH|.*[Ll]atch)", "Assign the signal in every branch of its block.", f'{GATES}, "LINT"'),
    (
        r"^lint: .*a second clock",
        "Use 1 clock, and an enable where the second clock was.",
        f'{GATES}, "LINT"',
    ),
    (r"^lint: .*lint_off", "Remove the comment, then correct what the class names.", f'{GATES}, "LINT"'),
    (
        r"^lint: \S+\.sdc: ",
        "Correct the constraints file as the line says.",
        f'{DESIGN}, "The constraints"',
    ),
    (r"^lint: ", "Correct the RTL at the file and the line the failure names.", f'{GATES}, "LINT"'),
    (
        r"^sim: (no rtl/mutations\.json|rtl/mutations\.json lists no change)",
        "List 1 change of the RTL for each thing a bench must catch, in rtl/mutations.json.",
        f'{DESIGN}, "The list of changes"',
    ),
    (
        r"^sim: rtl/mutations\.json: ",
        "Correct the list of changes as the line says.",
        f'{DESIGN}, "The list of changes"',
    ),
    (
        r"^sim: the benches pass with the change ",
        "Add a check to a bench that fails on the change the line names.",
        f'{DESIGN}, "The list of changes"',
    ),
    (
        r"^(sim|glsim): .*(does not compile|does not reach \$finish|does not print|expect\.json)",
        "Correct the bench as the line says.",
        f'{DESIGN}, "A bench"',
    ),
    (
        r"^sim: .*x_outputs=",
        "Give every flop that an output depends on a reset.",
        f'{GATES}, "SIM"',
    ),
    (
        r"^sim: ",
        "Read the first mismatch in the bench's run.log, then correct the RTL.",
        f'{GATES}, "SIM"',
    ),
    (
        r"^synth: .*flops have no reset",
        "Give each named flop a reset, or answer for it in chip.json.",
        f'{GATES}, "SYNTH"',
    ),
    (r"^synth: .*latch bits", "Assign the signal in every branch of its block.", f'{GATES}, "SYNTH"'),
    (r"^synth: ", "Correct the RTL as the line says.", f'{GATES}, "SYNTH"'),
    (
        r"^layout: .*(utilisation|do not fit|floorplans of the gate|router left)",
        "Name a larger die in chip.json's floorplan.die_um, or cut logic.",
        f'{GATES}, "LAYOUT"',
    ),
    (
        r"^layout: ",
        "Read build/chip/layout/openroad.log at the line the failure names.",
        f'{GATES}, "LAYOUT"',
    ),
    (
        r"^sta: .*setup slack",
        "Shorten the path the line names: add a register stage, or do less between 2 flops.",
        f'{GATES}, "STA"',
    ),
    (
        r"^sta: .*hold slack",
        "Read the path in build/chip/sta/<corner>/sta.log: the build's hold repair did not reach it.",
        f'{GATES}, "STA"',
    ),
    (
        r"^sta: chip\.json names no limits\.clock_skew_ns",
        "Name a limit for the clock skew in chip.json, with its source.",
        f'{DESIGN}, "chip.json"',
    ),
    (
        r"^sta: .*pins break a limit",
        "Name a larger die: the build's repair left a slow signal or a heavy net.",
        f'{GATES}, "STA"',
    ),
    (
        r"^sta: .*clock skew .* is over the limit",
        "Report the line with the limit's source: the clock tree is the build's own.",
        f'{GATES}, "STA"',
    ),
    (r"^sta: ", "Correct what the corner's line names.", f'{GATES}, "STA"'),
    (
        r"^glsim: .*x_outputs=",
        "Give every flop a reset: a flop with none starts unknown on the netlist.",
        f'{GATES}, "GLSIM"',
    ),
    (
        r"^glsim: ",
        "Read the first mismatch in build/chip/glsim/<bench>/run.log: the netlist differs there.",
        f'{GATES}, "GLSIM"',
    ),
    (r"^drc: ", "Read the deck's report for the first rule the line names.", f'{GATES}, "DRC"'),
    (r"^antenna: ", "Name a larger die, so the wires are shorter.", f'{GATES}, "ANTENNA"'),
    (r"^lvs: ", "Read build/chip/lvs for the first cell that does not match.", f'{GATES}, "LVS"'),
    (
        r"^export: .*(changed after|was added after|is gone since|is not the file|did not judge)",
        "Run all the chip gates again: a file is not the one a gate passed.",
        f'{GATES}, "EXPORT"',
    ),
    (r"^export: ", "Do what the line says, then run all the chip gates again.", f'{GATES}, "EXPORT"'),
    (r"", f"Read the gate's report, then correct the design. {RULE}", f'{GATES}, "Steps"'),
]


def hint(gate: str, line: str) -> tuple[str, str]:
    """What to do about a failure or warning line of a chip gate, and what to read."""
    for pattern, do, read in HINTS:
        if re.search(pattern, f"{gate}: {line}"):
            return do, read
    raise AssertionError("the last hint matches every line")


def is_chip(path: Path) -> bool:
    """Whether a path names a chip project: a folder that holds a chip.json, or that file."""
    return (path / chipflow.CHIP_FILE).is_file() or (path.is_file() and path.name == chipflow.CHIP_FILE)


def inputs_of(run) -> list[Path]:
    """The project's files the gates read, each 1 time: when one is newer than the report, the report
    is stale."""
    found: dict[Path, None] = {}
    for gate in chipfront.INPUT_GATES:
        for path in chipfront.project_inputs(run, gate):
            if path.is_file():
                found[path] = None
    return list(found)


def trouble(results: list) -> tuple[str, str, bool] | None:
    """The first thing a run of the chip gates asks for: (gate, line, whether it is a failure). A red
    gate's first failure, else the first warning of any gate, else None."""
    for r in results:
        if r.status in ("fail", "error"):
            said = list(r.details.get("failures", []))
            return r.gate, (said[0] if said else r.summary), True
    for r in results:
        said = list(r.details.get("warnings", []))
        if said:
            return r.gate, said[0], False
    return None


def next_step(cli, target: str) -> Step:
    """The first step a chip project has not done."""
    wc = "workcenter"
    path = Path(target).resolve()
    folder = path.parent if path.is_file() else path
    quoted = shlex.quote(target if path.is_dir() else str(folder))
    again = f"`{wc} next {quoted}` names another step"
    gates = f"{wc} chip gates {quoted}"

    chip, problems = chipflow.read_chip(folder)
    if chip is None:
        more = f" ({len(problems)} lines of chip.json are named in all)" if len(problems) > 1 else ""
        do, read = hint("lint", problems[0])
        return Step(do, why=problems[0] + more, read=read, done_when=again)
    absent = [name for name in chipflow.ENGINES if chipflow.find_engine(cli, name) is None]
    pdk, pdk_problems, pdk_absent = chipflow.read_pdk(cli, chip)
    if absent or pdk_absent:
        missing = [*absent, *(pdk_problems[:1] if pdk_absent else [])]
        return Step(
            "Install the chip engines: a gate cannot run without its engine.",
            f"sudo {cli.SRC_DIR / 'install.sh'} --chip",
            f"not installed: {', '.join(missing)}",
            'ee-agent-kit/docs/ENGINES.md, "The chip engines"',
            f"`{wc} doctor` prints a version beside each chip engine and beside the process kit",
        )
    if pdk is None:
        do, read = hint("lint", pdk_problems[0])
        return Step(do, why=pdk_problems[0], read=read, done_when=again)
    if not chip.rtl:
        return Step(
            f"Write the RTL: the module {chip.top} in {quoted}/rtl/{chip.top}.v.",
            why="no file matches chip.json's rtl patterns",
            read=f'{DESIGN}, "The RTL"',
            done_when=again,
        )
    run = chipflow.Run(cli=cli, project=folder, out=folder / "build", chip=chip)
    if not chipfront.benches(run):
        return Step(
            f"Write a bench, {quoted}/tb/tb_{chip.top}.v, that prints errors, checks and x_outputs.",
            why="tb/ holds no bench: nothing shows what the RTL does",
            read=f'{DESIGN}, "A bench"',
            done_when=again,
        )
    report = folder / "build" / "gates.json"
    green = "the last line starts with GREEN"
    if not report.is_file():
        return Step("Run the chip gates.", gates, "no build/gates.json yet", f'{GATES}, "Steps"', green)
    made = report.stat().st_mtime
    newer = next((p for p in inputs_of(run) if p.stat().st_mtime > made), None)
    if newer:
        return Step(
            "Run the chip gates again: a file changed after the last run.",
            gates,
            f"build/gates.json is older than {run.name_of(newer)}",
            f'{GATES}, "Steps"',
            green,
        )
    results = [cli.Result(**r) for r in json.loads(report.read_text(encoding="utf-8"))]
    verdict, _ = chipflow.chip_verdict(results, whole=True)
    skipped = next((r for r in results if r.status == "skip"), None)
    if skipped is not None and skipped.details.get("engine_missing"):
        # Every engine was found above, so the report is older than the toolchain.
        return Step(
            "Run the chip gates again: the report is from a run with an engine absent.",
            gates,
            f"build/gates.json says {verdict}; every chip engine is installed now",
            f'{GATES}, "Steps"',
            green,
        )
    found = trouble(results)
    if found:
        gate, line, failed = found
        do, read = hint(gate, line)
        return Step(
            do,
            gates if failed else f"{gates} --strict",
            f"{gate.upper()} {'failed' if failed else 'warns'}: {line}",
            read,
            green if failed else "the last line is GREEN, with no warning",
        )
    if not verdict.startswith("GREEN"):
        # A gate that did not run, and not for an engine: its line says what it waits for.
        return Step(
            "Run the chip gates again, all 10 in their order.",
            gates,
            f"build/gates.json says {verdict}",
            f'{GATES}, "A gate that did not run"',
            green,
        )
    return Step(
        "Nothing: all 10 chip gates are GREEN with no warning.",
        why=f"{quoted}/build/chip/tapeout holds the layout, its netlists and manifest.json. GREEN says "
        "what the run's scope line says: the open engines found no fault, and no foundry deck ran "
        f'({GATES}, "What GREEN says")',
        done=True,
    )
