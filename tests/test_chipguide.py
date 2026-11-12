"""`workcenter next` on a chip project: the one next step (tools/chipguide.py).

Most tests write the gates report a chip project would have, by hand, and read the step the command
gives for it. They need no engine: `next` asks only whether each engine and the process kit are there,
and a folder of empty files stands in for them. One test walks a project from the template to GREEN
with the engines themselves, and skips by name where they are absent. One holds every hint to the
document it points at, and one holds every sentence of an answer to its count of words.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import chipflow  # noqa: E402
import chipguide  # noqa: E402
from test_chipflow import VERSION, command, fill, load_cli  # noqa: E402
from test_chips import EVERY, needs  # noqa: E402

DESIGN = ".claude/skills/chip-design/SKILL.md"
GATES = ".claude/skills/chip-gates/SKILL.md"


def toolchain(folder: Path, *without: str) -> dict[str, str]:
    """The environment of a machine that has every chip engine and the process kit, but for `without`:
    empty files under their names. `next` starts none of them."""
    for name, (where, _, _) in chipflow.ENGINES.items():
        if name in without:
            continue
        path = folder / ("chip/bin" if where == "chip" else "bin") / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
        path.chmod(0o755)
    (folder / "bin").mkdir(parents=True, exist_ok=True)
    if "kit" not in without:
        stated = chipflow.read_table("sky130A")[0]["version"]["file"]
        tech = folder / "chip" / "pdk" / "sky130A" / stated
        tech.parent.mkdir(parents=True, exist_ok=True)
        tech.write_text(f"version\n version {VERSION}\n", encoding="utf-8")
    return {"WORKCENTER_CHIP_TOOLS": str(folder / "chip"), "PATH": str(folder / "bin")}


def ask(project: Path, env: dict[str, str]) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", "next", str(project)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **env},
    )
    assert proc.stdout, proc.stderr
    return proc.returncode, json.loads(proc.stdout)


OWN = "// the project's own: no longer the file `chip init` wrote\n"


def a_project(tmp_path: Path) -> Path:
    """A project past its first files: chip.json and the constraints filled, the RTL and the bench the
    project's own (the template's register with 1 line more), the README written."""
    folder = tmp_path / "reg8"
    assert command("chip", "init", folder, "--top", "reg8").returncode == 0
    fill(folder)
    for name in ("rtl/reg8.v", "tb/tb_reg8.v"):
        with (folder / name).open("a", encoding="utf-8") as fh:
            fh.write(OWN)
    (folder / "README.md").write_text("# reg8\n\nAn 8-bit register with an enable.\n", encoding="utf-8")
    return folder


def record(gate: str, status: str = "pass", failures=(), warnings=(), **details) -> dict:
    return {
        "gate": gate,
        "status": status,
        "summary": f"{len(failures)} failures",
        "details": {**details, "failures": list(failures), "warnings": list(warnings)},
        "artifacts": [],
        "seconds": 0.1,
    }


def report(folder: Path, records: list[dict]) -> None:
    (folder / "build").mkdir(exist_ok=True)
    (folder / "build" / "gates.json").write_text(json.dumps(records), encoding="utf-8")


def passed(upto: str | None = None) -> list[dict]:
    """A record of a pass for each gate, or for each gate before `upto`."""
    names = chipflow.GATE_NAMES
    return [record(name) for name in names[: names.index(upto) if upto else len(names)]]


# ------------------------------------------------------------------ the hints


def test_every_chip_hint_points_at_a_file_and_a_heading_that_exist():
    for pattern, do, read in chipguide.HINTS:
        assert do.endswith("."), (pattern, do)
        path, _, section = read.partition(", ")
        text = (ROOT / path).read_text(encoding="utf-8")  # the file is there
        heading = section.strip('"')
        assert section.startswith('"') and re.search(rf"^#+ {re.escape(heading)}$", text, re.M), (
            f"{path} has no heading {heading!r}"
        )
    # the steps' own targets too: each names a file, and a heading of it
    source = Path(chipguide.__file__).read_text(encoding="utf-8")
    for name, heading in re.findall(r"\{(DESIGN|GATES)\}, \"([^\"]+)\"", source):
        text = (ROOT / getattr(chipguide, name)).read_text(encoding="utf-8")
        assert re.search(rf"^#+ {re.escape(heading)}$", text, re.M), (name, heading)
    engines = (ROOT / "ee-agent-kit" / "docs" / "ENGINES.md").read_text(encoding="utf-8")
    assert "## The chip engines\n" in engines


@pytest.mark.parametrize(
    ("gate", "line", "do", "section"),
    [
        (
            "lint",
            "chip.json: pdk.version: not written (the text still starts with fill:)",
            "Correct the pdk block of chip.json as the line says.",
            f'{DESIGN}, "chip.json"',
        ),
        (
            "lint",
            "LATCH: rtl/counter.v:11:5: Latch inferred for signal 'counter.next' (not all control paths of "
            "combinational always assign a value)",
            "Assign the signal in every branch of its block.",
            f'{GATES}, "LINT"',
        ),
        (
            "lint",
            "constraints.sdc: line 4: a second clock: the first flow takes 1 clock. Use 1 clock and an "
            "enable",
            "Use 1 clock, and an enable where the second clock was.",
            f'{GATES}, "LINT"',
        ),
        (
            "lint",
            "constraints.sdc: input en has no set_input_delay: STA cannot judge a path through it",
            "Correct the constraints file as the line says.",
            f'{DESIGN}, "The constraints"',
        ),
        (
            "sim",
            "tb_counter: errors=5 not in [None, 0]",
            "Read the first mismatch in the bench's run.log, then correct the RTL.",
            f'{GATES}, "SIM"',
        ),
        (
            "sim",
            "no rtl/mutations.json: nothing shows that the benches can fail. List 1 change of the RTL for "
            "each thing a bench must catch",
            "List 1 change of the RTL for each thing a bench must catch, in rtl/mutations.json.",
            f'{DESIGN}, "The list of changes"',
        ),
        (
            "sim",
            "the benches pass with the change enable-ignored in rtl/counter.v: add the check that fails "
            "on it",
            "Add a check to a bench that fails on the change the line names.",
            f'{DESIGN}, "The list of changes"',
        ),
        (
            "sim",
            "tb_counter: does not reach $finish: end the bench with $finish after its last check",
            "Correct the bench as the line says.",
            f'{DESIGN}, "A bench"',
        ),
        (
            "synth",
            "1 flops have no reset: en_q: reset each, or name it in chip.json's "
            "answers.flops_without_reset with why and the bench that proves it",
            "Give each named flop a reset, or answer for it in chip.json.",
            f'{GATES}, "SYNTH"',
        ),
        (
            "layout",
            "utilisation 0.6451 is over the limit 0.5 of chip.json after the floorplan, before the clock "
            "tree adds cells: take a larger die, or cut logic. Do not raise the limit",
            "Name a larger die in chip.json's floorplan.die_um, or cut logic.",
            f'{GATES}, "LAYOUT"',
        ),
        (
            "sta",
            "max_ss_n40C_1v60: setup slack -0.3277 ns, from _49_ to count[3]",
            "Shorten the path the line names: add a register stage, or do less between 2 flops.",
            f'{GATES}, "STA"',
        ),
        (
            "sta",
            "chip.json names no limits.clock_skew_ns: the skew is reported and held to nothing",
            "Name a limit for the clock skew in chip.json, with its source.",
            f'{DESIGN}, "The 2 limits"',
        ),
        (
            "glsim",
            "tb_counter: x_outputs=266 not in [None, 0]",
            "Give every flop a reset: a flop with none starts unknown on the netlist.",
            f'{GATES}, "GLSIM"',
        ),
        (
            "drc",
            "klayout-mr: 8 items break a rule: npc.2, nsd.2, psd.2",
            "Read the deck's report for the first rule the line names.",
            f'{GATES}, "DRC"',
        ),
        (
            "export",
            "rtl/reg8.v changed after LINT passed: its hash differs. Run the gates again",
            "Run all the chip gates again: a file is not the one a gate passed.",
            f'{GATES}, "EXPORT"',
        ),
    ],
)
def test_a_line_of_a_chip_gate_is_answered_with_the_fix_for_its_kind(gate, line, do, section):
    """Each line here is one a gate printed for a fixture chip or a test's project."""
    assert chipguide.hint(gate, line) == (do, section)


# ------------------------------------------------------------------ the steps


def test_a_folder_with_a_chip_json_is_a_chip_project_and_its_file_names_it_too(tmp_path):
    env = toolchain(tmp_path / "tools")
    folder = a_project(tmp_path)
    code, step = ask(folder, env)
    assert (code, step["next"], step["run"]) == (1, "Run the chip gates.", f"workcenter chip gates {folder}")
    assert step["why"] == "no build/gates.json yet"
    assert step["read"] == f'{GATES}, "Steps"'
    assert step["done_when"] == "the last line starts with GREEN"
    assert ask(folder / "chip.json", env)[1] == step
    # a folder with no chip.json is asked as a board's: the answer names the chip's way to start
    code, step = ask(tmp_path / "tools", env)
    assert step["next"].startswith("Start the project with a deck, or with a design file for a board.")
    assert f"`workcenter chip init {tmp_path / 'tools'} --top <module>` writes" in step["next"]
    assert step["read"].endswith(f'; {DESIGN}, "Steps"')


def test_chip_json_comes_first_then_the_engines_the_kit_the_rtl_and_a_bench(tmp_path):
    env = toolchain(tmp_path / "tools")
    folder = tmp_path / "reg8"
    assert command("chip", "init", folder, "--top", "reg8").returncode == 0
    code, step = ask(folder, env)
    assert (code, step["run"]) == (1, "")
    assert step["next"] == "Correct the pdk block of chip.json as the line says."
    assert step["why"] == (
        "chip.json: pdk.version: not written (the text still starts with fill:) (5 lines of chip.json are "
        "named in all)"
    )
    assert step["read"] == f'{DESIGN}, "chip.json"'
    assert step["done_when"] == f"`workcenter next {folder}` names another step"
    fill(folder)
    # an engine and the kit: the answer names each thing that is absent
    bare = toolchain(tmp_path / "bare", "openroad", "yosys", "kit")
    code, step = ask(folder, bare)
    assert step["next"] == "Install the chip engines: a gate cannot run without its engine."
    assert step["run"] == f"sudo {ROOT / 'install.sh'} --chip"
    kit = tmp_path / "bare" / "chip" / "pdk" / "sky130A"
    assert step["why"] == f"not installed: yosys, openroad, the process kit sky130A is not installed in {kit}"
    assert step["read"] == 'ee-agent-kit/docs/ENGINES.md, "The chip engines"'
    # a kit of another version than chip.json names is the project's to answer, not an install
    data = json.loads((folder / "chip.json").read_text(encoding="utf-8"))
    data["pdk"]["version"] = "1.0.999"
    (folder / "chip.json").write_text(json.dumps(data), encoding="utf-8")
    code, step = ask(folder, env)
    assert (step["next"], step["run"]) == ("Correct the pdk block of chip.json as the line says.", "")
    assert step["why"] == (
        f"chip.json: pdk.version is 1.0.999, and the installed sky130A states {VERSION}: the project is "
        "proven on 1 version"
    )
    data["pdk"]["version"] = VERSION
    (folder / "chip.json").write_text(json.dumps(data), encoding="utf-8")
    # the RTL, then a bench
    rtl, bench = folder / "rtl" / "reg8.v", folder / "tb" / "tb_reg8.v"
    kept = rtl.read_text(encoding="utf-8")
    rtl.unlink()
    code, step = ask(folder, env)
    assert step["next"] == f"Write the RTL: the module reg8 in {folder}/rtl/reg8.v."
    assert (step["run"], step["read"]) == ("", f'{DESIGN}, "The RTL"')
    rtl.write_text(kept, encoding="utf-8")
    example = bench.read_text(encoding="utf-8")
    bench.unlink()
    code, step = ask(folder, env)
    assert step["next"] == f"Write a bench, {folder}/tb/tb_reg8.v, that prints errors, checks and x_outputs."
    assert (step["run"], step["read"]) == ("", f'{DESIGN}, "A bench"')
    # `chip init` writes a register and its bench as examples, and the gates pass on them. A small model
    # that was told to run the gates on them took the example for its design (2026-11-12): each file
    # that is still the example is named before any gate runs, the RTL first.
    bench.write_text(example, encoding="utf-8")
    code, step = ask(folder, env)
    assert (code, step["run"]) == (1, "")
    assert step["next"] == (
        f"Write the design in {folder}/rtl/reg8.v: the file still holds the template's register."
    )
    assert step["why"] == "rtl/reg8.v is as `workcenter chip init` wrote it"
    assert step["read"] == f'{DESIGN}, "The RTL"'
    rtl.write_text(kept + OWN, encoding="utf-8")
    code, step = ask(folder, env)
    assert step["next"] == (
        f"Write the design's bench in {folder}/tb/tb_reg8.v: the file still holds the template's."
    )
    assert (step["why"], step["read"]) == (
        "tb/tb_reg8.v is as `workcenter chip init` wrote it",
        f'{DESIGN}, "A bench"',
    )
    bench.write_text(example + OWN, encoding="utf-8")
    assert ask(folder, env)[1]["next"] == "Run the chip gates."
    # The README comes last. With all 10 gates GREEN, a line the template left keeps the project open.
    report(folder, passed())
    code, step = ask(folder, env)
    assert (code, step["run"]) == (1, "")
    assert step["next"] == (
        f"Fill {folder}/README.md: the spec with its sources, the pins, how to test, each decision."
    )
    assert step["why"] == (
        "4 lines of README.md still say fill:, the first: fill: 1 paragraph: what the chip does, for whom, "
        "and what proves that it works."
    )
    assert step["read"] == f'{DESIGN}, "Steps"'
    (folder / "README.md").write_text("# reg8\n\nAn 8-bit register with an enable.\n", encoding="utf-8")
    code, step = ask(folder, env)
    assert (code, step["next"]) == (0, "Nothing: all 10 chip gates are GREEN with no warning.")


def test_the_gates_run_again_when_a_file_a_gate_reads_is_newer_than_the_report(tmp_path):
    env = toolchain(tmp_path / "tools")
    folder = a_project(tmp_path)
    rtl = folder / "rtl" / "reg8.v"
    rtl.write_text('`include "widths.vh"\n' + rtl.read_text(encoding="utf-8"), encoding="utf-8")
    (folder / "rtl" / "widths.vh").write_text("// the widths\n", encoding="utf-8")
    report(folder, passed())
    assert ask(folder, env)[1]["next"] == "Nothing: all 10 chip gates are GREEN with no warning."
    later = time.time() + 60
    # a header is read through the file that names it; a note beside the RTL is read by no gate
    (folder / "rtl" / "notes.txt").write_text("a note\n", encoding="utf-8")
    os.utime(folder / "rtl" / "notes.txt", (later, later))
    assert ask(folder, env)[0] == 0
    for name in ("rtl/widths.vh", "tb/tb_reg8.v", "constraints.sdc", "chip.json"):
        path = folder / name
        before = path.stat().st_mtime
        os.utime(path, (later, later))
        code, step = ask(folder, env)
        assert code == 1, name
        assert step["next"] == "Run the chip gates again: a file changed after the last run."
        assert step["why"] == f"build/gates.json is older than {name}"
        assert step["run"] == f"workcenter chip gates {folder}"
        os.utime(path, (before, before))
    assert ask(folder, env)[0] == 0


def test_a_red_gate_a_warning_a_skip_and_a_green_run_are_each_answered(tmp_path):
    env = toolchain(tmp_path / "tools")
    folder = a_project(tmp_path)
    gates = f"workcenter chip gates {folder}"
    # the first failure of the first red gate, with the fix for its kind
    lines = ["max_ss_n40C_1v60: setup slack -0.3277 ns, from _49_ to count[3]", "another line"]
    report(folder, [*passed("sta"), record("sta", "fail", lines)])
    code, step = ask(folder, env)
    assert code == 1 and step["run"] == gates
    shorten = "Shorten the path the line names: add a register stage, or do less between 2 flops."
    assert step["next"] == shorten
    assert step["why"] == f"STA failed: {lines[0]}"
    assert step["read"] == f'{GATES}, "STA"'
    assert step["done_when"] == "the last line starts with GREEN"
    # a GREEN run with a warning is not done: the next run is strict
    warning = "chip.json names no limits.clock_skew_ns: the skew is reported and held to nothing"
    records = passed()
    records[4]["details"]["warnings"] = [warning]
    report(folder, records)
    code, step = ask(folder, env)
    assert (code, step["run"]) == (1, f"{gates} --strict")
    assert step["next"] == "Name a limit for the clock skew in chip.json, with its source."
    assert step["why"] == f"STA warns: {warning}"
    assert step["done_when"] == "the last line is GREEN, with no warning"
    # a report from a run with an engine absent, on a machine that has it now
    skip = record("layout", "skip", engine_missing=True, reason="openroad is not installed")
    skip["summary"] = "openroad is not installed: `workcenter doctor` lists the chip engines"
    report(folder, [*passed("layout"), skip])
    code, step = ask(folder, env)
    assert step["next"] == "Run the chip gates again: the report is from a run with an engine absent."
    assert step["why"] == (
        "build/gates.json says SKIPPED (LAYOUT: openroad is not installed: `workcenter doctor` lists the "
        "chip engines); every chip engine is installed now"
    )
    # a gate that did not run for another reason, and a report of fewer than 10 gates
    skip = record("sta", "skip", engine_missing=False, reason="LAYOUT has not run")
    skip["summary"] = "LAYOUT has not run in build: STA judges only a layout that LAYOUT passed"
    for records in ([skip], passed("drc")):
        report(folder, records)
        code, step = ask(folder, env)
        assert (code, step["run"]) == (1, gates)
        assert step["next"] == "Run the chip gates again, all 10 in their order."
        assert step["read"] == f'{GATES}, "A gate that did not run"'
    assert step["why"] == "build/gates.json says SKIPPED (not every gate ran)"
    # all 10 passed with no warning: nothing is left, and a reader who runs every RUN line is given none
    report(folder, passed())
    code, step = ask(folder, env)
    assert (code, step["done"], step["run"]) == (0, True, "")
    assert step["next"] == "Nothing: all 10 chip gates are GREEN with no warning."
    assert f"{folder}/build/chip/tapeout holds the layout" in step["why"]
    assert "no foundry deck ran" in step["why"]


def sentences(text: str) -> list[str]:
    """A text's sentences as STYLE.md's rule 2 counts them: a sentence ends at ". " or at the text's
    end, and a code span in backticks is 1 word."""
    return [s for s in re.sub(r"`[^`]*`", "`code`", text).split(". ") if s]


def test_no_sentence_of_a_chip_hint_or_step_is_over_20_words_and_every_step_is_reached(tmp_path, monkeypatch):
    """A small model follows an answer word for word (ee-agent-kit/docs/STYLE.md, rules 1 and 2). Every
    hint is counted, and every step: the last assertion fails when a `Step(` of chipguide.py is the
    answer of no project here. A WHY that quotes a gate's line is as long as that line, so the count
    is of the guide's own words: NEXT and DONE WHEN."""
    cli = load_cli()
    env = toolchain(tmp_path / "tools")
    monkeypatch.setenv("WORKCENTER_CHIP_TOOLS", env["WORKCENTER_CHIP_TOOLS"])
    monkeypatch.setenv("PATH", env["PATH"])
    reached: set[int] = set()
    steps = []
    original = chipguide.Step

    def noted(*args, **kwargs):
        reached.add(sys._getframe(1).f_lineno)
        step = original(*args, **kwargs)
        steps.append(step)
        return step

    monkeypatch.setattr(chipguide, "Step", noted)

    def answer(folder: Path) -> None:
        chipguide.next_step(cli, str(folder))

    folder = tmp_path / "reg8"
    assert command("chip", "init", folder, "--top", "reg8").returncode == 0
    answer(folder)  # chip.json still holds fill:
    fill(folder)
    monkeypatch.setenv("WORKCENTER_CHIP_TOOLS", str(tmp_path / "none"))
    answer(folder)  # no engine, no kit
    monkeypatch.setenv("WORKCENTER_CHIP_TOOLS", env["WORKCENTER_CHIP_TOOLS"])
    data = json.loads((folder / "chip.json").read_text(encoding="utf-8"))
    (folder / "chip.json").write_text(json.dumps({**data, "pdk": {**data["pdk"], "version": "0"}}), "utf-8")
    answer(folder)  # another version of the kit
    (folder / "chip.json").write_text(json.dumps(data), encoding="utf-8")
    rtl, bench = folder / "rtl" / "reg8.v", folder / "tb" / "tb_reg8.v"
    kept = rtl.read_text(encoding="utf-8"), bench.read_text(encoding="utf-8")
    rtl.unlink()
    answer(folder)
    rtl.write_text(kept[0], encoding="utf-8")
    bench.unlink()
    answer(folder)
    bench.write_text(kept[1], encoding="utf-8")
    answer(folder)  # the RTL is still the template's example
    rtl.write_text(kept[0] + OWN, encoding="utf-8")
    bench.write_text(kept[1] + OWN, encoding="utf-8")
    answer(folder)  # no report
    report(folder, passed())
    later = time.time() + 60
    os.utime(rtl, (later, later))
    answer(folder)  # stale
    os.utime(rtl, None)
    os.utime(folder / "build" / "gates.json", (later + 60, later + 60))
    skip = record("layout", "skip", engine_missing=True)
    report(folder, [*passed("layout"), skip])
    os.utime(folder / "build" / "gates.json", (later + 60, later + 60))
    answer(folder)
    report(folder, [*passed("sim"), record("sim", "fail", ["tb_reg8: errors=1 not in [None, 0]"])])
    os.utime(folder / "build" / "gates.json", (later + 60, later + 60))
    answer(folder)
    report(folder, passed("drc"))
    os.utime(folder / "build" / "gates.json", (later + 60, later + 60))
    answer(folder)
    report(folder, passed())
    os.utime(folder / "build" / "gates.json", (later + 60, later + 60))
    answer(folder)  # the README still says fill:
    (folder / "README.md").write_text("# reg8\n", encoding="utf-8")
    answer(folder)

    texts = [do for _, do, _ in chipguide.HINTS]
    texts += [text for step in steps for text in (step.next, step.done_when)]
    long = [(len(s.split()), s) for text in texts for s in sentences(text) if len(s.split()) > 20]
    assert not long, long
    tree = ast.parse(Path(chipguide.__file__).read_text(encoding="utf-8"))
    sites = {
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Step"
    }
    assert sites == reached, f"no project here is answered by the Step of line {sorted(sites - reached)}"


def test_next_writes_nothing_into_a_chip_project(tmp_path):
    env = toolchain(tmp_path / "tools")
    folder = a_project(tmp_path)
    report(folder, [*passed("sta"), record("sta", "fail", ["max_ss_n40C_1v60: setup slack -1.0000 ns"])])

    def state() -> dict[str, tuple[int, int]]:
        return {
            str(p.relative_to(folder)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(folder.rglob("*"))
            if p.is_file()
        }

    before = state()
    assert ask(folder, env)[0] == 1
    assert state() == before


def test_the_answer_of_a_chip_prints_one_field_to_a_line(tmp_path):
    env = toolchain(tmp_path / "tools")
    folder = a_project(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(CLI), "next", str(folder)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **env},
    )
    assert proc.returncode == 1
    assert proc.stdout.splitlines() == [
        "NEXT       Run the chip gates.",
        f"RUN        workcenter chip gates {folder}",
        "WHY        no build/gates.json yet",
        f'READ       {GATES}, "Steps"',
        "DONE WHEN  the last line starts with GREEN",
    ]


# ---------------------------------------------------------------- with the engines


def run_line(step: dict) -> subprocess.CompletedProcess:
    """Run a step's RUN line as its reader does, with this checkout's `workcenter`."""
    words = shlex.split(step["run"])
    assert words[0] == "workcenter", step["run"]
    return command(*words[1:])


@needs(EVERY)
def test_next_walks_the_template_from_its_first_file_to_green(tmp_path):
    """The answers alone take a project from `chip init` to a GREEN chip: each RUN line is run as
    written, and each NEXT with no RUN line is done as it says. The design here is the template's own
    register, written as the project's. It is GREEN with 2 warnings until the project names a limit
    for the skew and lists changes its bench must catch, and done when its README is written."""
    folder = tmp_path / "reg8"
    assert command("chip", "init", folder, "--top", "reg8").returncode == 0
    code, step = ask(folder, {})
    assert step["next"] == "Correct the pdk block of chip.json as the line says."
    fill(folder)
    for name, said in (
        ("rtl/reg8.v", "Write the design in {}: the file still holds the template's register."),
        ("tb/tb_reg8.v", "Write the design's bench in {}: the file still holds the template's."),
    ):
        code, step = ask(folder, {})
        assert (step["next"], step["run"]) == (said.format(folder / name), "")
        with (folder / name).open("a", encoding="utf-8") as fh:
            fh.write(OWN)
    code, step = ask(folder, {})
    assert step["next"] == "Run the chip gates."
    ran = run_line(step)
    assert ran.returncode == 0 and ran.stdout.splitlines()[-1].startswith("GREEN with 2 warnings: reg8")
    code, step = ask(folder, {})
    assert (code, step["run"]) == (1, f"workcenter chip gates {folder} --strict")
    listing = "List 1 change of the RTL for each thing a bench must catch, in rtl/mutations.json."
    assert step["next"] == listing
    changes = [
        {"name": "enable-ignored", "file": "rtl/reg8.v", "old": "else if (en) q", "new": "else q"},
        {"name": "reset-to-1", "file": "rtl/reg8.v", "old": "q <= 8'd0", "new": "q <= 8'd1"},
    ]
    (folder / "rtl" / "mutations.json").write_text(json.dumps({"mutations": changes}), encoding="utf-8")
    code, step = ask(folder, {})
    assert step["next"] == "Run the chip gates again: a file changed after the last run."
    assert step["why"] == "build/gates.json is older than rtl/mutations.json"
    ran = run_line(step)
    assert ran.stdout.splitlines()[-1].startswith("GREEN with 1 warning: reg8")
    assert "sim        1 benches, 4 checks, 2 of 2 changes of the RTL caught, 0 failures" in ran.stdout
    code, step = ask(folder, {})
    assert step["next"] == "Name a limit for the clock skew in chip.json, with its source."
    # the section the answer names says where the number comes from when the spec gives none
    assert step["read"] == f'{DESIGN}, "The 2 limits"'
    skill = (ROOT / DESIGN).read_text(encoding="utf-8")
    assert "take a twentieth of the clock period (1 ns for a 20 ns\n   clock)" in skill
    data = json.loads((folder / "chip.json").read_text(encoding="utf-8"))
    budget = "the project's budget: a twentieth of the 20 ns clock period"
    data["limits"]["clock_skew_ns"] = {"max": 1.0, "source": budget}
    (folder / "chip.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    code, step = ask(folder, {})
    assert step["next"] == "Run the chip gates again: a file changed after the last run."
    ran = command("chip", "gates", folder, "--strict")
    assert ran.returncode == 0 and ran.stdout.splitlines()[-1].startswith("GREEN: reg8")
    code, step = ask(folder, {})
    assert (code, step["done"], step["run"]) == (1, False, "")
    assert step["next"].startswith(f"Fill {folder}/README.md: the spec with its sources")
    (folder / "README.md").write_text("# reg8\n\nAn 8-bit register with an enable.\n", encoding="utf-8")
    code, step = ask(folder, {})
    assert (code, step["done"]) == (0, True)
    assert step["next"] == "Nothing: all 10 chip gates are GREEN with no warning."
