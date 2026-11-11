"""`workcenter next`: the one next step for a project (tools/guide.py).

Most tests write the gates report a project would have, by hand, and read the step the command gives
for it; they need no engine. Two run the real gates on fixtures and skip when ngspice is absent. One
holds every hint to the document it points at: a fix that names a section which is not there is no fix.
"""

from __future__ import annotations

import importlib.machinery
import json
import os
import re
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
sys.path.insert(0, str(ROOT / "tools"))
import guide  # noqa: E402

needs_ngspice = pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice is not installed")

DECK = "* a deck\nV1 in 0 DC 5\nR1 in 0 1k\n.control\nop\n.endc\n.end\n"


def load_cli():
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_guide", str(CLI))
    module = types.ModuleType("workcenter_cli_guide")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module  # dataclasses look the defining module up here
    loader.exec_module(module)
    return module


def ask(project: Path, *flags: str, env: dict | None = None) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", "next", str(project), *flags],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
    )
    return proc.returncode, json.loads(proc.stdout)


def sim_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / "sim").mkdir(parents=True)
    (proj / "sim" / "d.cir").write_text(DECK, encoding="utf-8")
    return proj


def report(proj: Path, records: list[dict], name: str = "gates.json") -> None:
    """Write a report as a gate run leaves it, a moment after the project's files."""
    (proj / "build").mkdir(exist_ok=True)
    body = records if name == "gates.json" else records[0]
    (proj / "build" / name).write_text(json.dumps(body), encoding="utf-8")
    later = time.time() + 5
    os.utime(proj / "build" / name, (later, later))


def record(gate: str, status: str, details: dict | None = None, summary: str = "") -> dict:
    return {
        "gate": gate,
        "status": status,
        "summary": summary,
        "details": details or {},
        "artifacts": [],
        "seconds": 0.0,
    }


# ------------------------------------------------------------- the hints


def test_every_hint_points_at_a_file_and_a_heading_that_exist():
    for pattern, do, read in guide.HINTS:
        assert do.endswith((".", "`.")), (pattern, do)
        path, _, section = read.partition(", ")
        text = (ROOT / path).read_text(encoding="utf-8")  # the file is there
        if section.startswith('"'):
            heading = section.strip('"')
            assert re.search(rf"^#+ .*{re.escape(heading)}", text, re.M), f"{path} has no heading {heading!r}"
        elif section:
            assert re.search(rf"^## {re.escape(section)} ", text, re.M), f"{path} has no {section}"


@pytest.mark.parametrize(
    ("gate", "line", "said"),
    [
        ("erc", "pin_not_connected: Pin not connected at (10, 20)", "Wire the pin"),
        ("drc", "clearance: Clearance violation ( clearance 0.2000 mm; actual 0.0500 mm)", "Move the track"),
        ("drc", "unconnected_items: Missing connection between items", "Route the net"),
        ("sim", "no sim/corners.json: each deck ran once, at 27 C with every part", "Write sim/corners.json"),
        (
            "sim",
            "d:vout=2.375 at R1 +5 %, R2 -5 % (and 5 more corners) not in [2.45, 2.55]",
            "at that corner",
        ),
        ("sim", "d:vout=3.0 not in [2.45, 2.55] (the spec)", "The circuit misses its bound"),
        ("sim", "ac:h=None not in [0.5, 0.9]", "does not print that measure"),
        (
            "sim",
            "d: at 85 C: ran at 50 C, not 85 C: the deck sets its own temperature",
            "sets its own temperature",
        ),
        ("sim", "abort: ngspice exit 0, 2 error lines", "did not run the deck to its end"),
        ("sim", "typo.expect.json: vout: unknown key 'minimum'", "Correct the expect file"),
        ("sim", "d: no measure moves with temperature: nothing in the deck", "temperature behaviour"),
        ("sim", "d: no tolerance covers R1, R2", "Add the kind"),
        ("sim", "corners.json: tolerance.parts names R99, which no deck has", "Correct sim/corners.json"),
        ("sim", "floating: ngspice: Warning: singular matrix:  check node mid", "no path to ground"),
        (
            "sim",
            "no sim/frequency-plan.json: 1 decks drive periodic sources: load (ILOAD)",
            "every periodic source",
        ),
        (
            "sim",
            "frequency plan: load's harmonic 3 (15.74 kHz to 16.06 kHz) is in the band of input filter "
            "(11.93 kHz to 21.82 kHz): no overlap answers it with a deck that drives it",
            "A source and a resonance meet",
        ),
        (
            "sim",
            "frequency plan: sim/odd.cir drives V9 at 7.777 kHz, which the plan does not name",
            "Name that source",
        ),
        ("sim", "frequency plan: overlap a and b: d.v has no bound in its expect file", "as the line says"),
        ("sim", "rdiv: lib.lib changed since its sources row (RDIV-1, rev 1)", "is never edited"),
        (
            "verify",
            "traceability: REQ-OUT-01 says PASS, `2.45 V<=d.vout` with 2.5 is FAIL at R1 +5 % (2.375)",
            "fails at that corner",
        ),
        ("verify", "REQ-OUT-02: OPEN", "A requirement is not met"),
        ("verify", "requirements: REQ-OUT-01 has no source", "Correct the verification package"),
        ("export", "kicad-cli exited 3", "Read the gate's report"),
    ],
)
def test_a_line_is_answered_with_the_fix_for_its_kind(gate, line, said):
    do, read = guide.hint(gate, line)
    assert said in do, do
    assert read


# ------------------------------------------------------------- the steps


def test_a_folder_with_nothing_in_it_is_told_the_two_ways_to_start(tmp_path):
    code, step = ask(tmp_path)
    assert code == 1 and step["done"] is False
    assert step["next"].startswith("Start the project.")
    assert f"{tmp_path}/sim/<name>.cir" in step["next"] and f"{tmp_path}/design.py" in step["next"]
    assert step["read"] == (
        '.claude/skills/simulate/SKILL.md, "Steps"; .claude/skills/board-design/SKILL.md, "Steps"'
    )
    (tmp_path / "design.py").write_text("# a design\n", encoding="utf-8")
    code, step = ask(tmp_path)
    assert code == 1 and step["next"] == "Generate the KiCad project from its design file."
    assert step["run"] == f"workcenter design {tmp_path}/design.py --route"


def test_a_project_with_nothing_for_a_gate_to_run_is_not_told_to_install_anything(tmp_path):
    (tmp_path / "sim").mkdir()  # a sim folder and no deck in it
    report(tmp_path, [record("sim", "skip", summary="no sim/*.cir in project")])
    code, step = ask(tmp_path)
    assert code == 1 and step["next"].startswith("Give the gates something to run")
    assert step["why"] == "every gate was skipped: sim: no sim/*.cir in project"


def test_a_project_whose_engine_is_absent_is_told_to_install_it(tmp_path):
    proj = sim_project(tmp_path)
    code, step = ask(proj, env={"NGSPICE": str(tmp_path / "no-such-ngspice")})
    assert code == 1 and step["next"].startswith("Install the toolchain")
    assert step["why"] == f"{tmp_path / 'no-such-ngspice'} is not on PATH"
    assert step["run"] == f"sudo {ROOT / 'install.sh'}"


def test_the_gates_run_first_and_again_when_an_input_is_newer(tmp_path):
    proj = sim_project(tmp_path)
    code, step = ask(proj)
    assert (code, step["next"], step["why"]) == (1, "Run the gates.", "no build/gates.json yet")
    assert (
        step["run"] == f"workcenter gates {proj}" and step["done_when"] == "the last line starts with GREEN"
    )
    report(proj, [record("sim", "pass", {"failures": [], "warnings": []})])
    code, step = ask(proj)
    assert code == 0 and step["done"] is True
    # the deck changes after the run: the report no longer speaks for the project
    later = time.time() + 60
    os.utime(proj / "sim" / "d.cir", (later, later))
    code, step = ask(proj)
    assert code == 1 and step["next"] == "Run the gates again: an input changed after the last run."
    assert step["why"] == "build/gates.json is older than sim/d.cir"


def test_a_red_gate_is_answered_with_its_first_failure_and_the_fix(tmp_path):
    proj = sim_project(tmp_path)
    violation = {
        "type": "clearance",
        "severity": "error",
        "description": "Clearance violation ( clearance 0.2000 mm; actual 0.0500 mm)",
        "pos": {"x": 119.0, "y": 112.65},
    }
    dangling = {"type": "track_dangling", "severity": "warning", "description": "Track has unconnected end"}
    report(proj, [record("erc", "pass"), record("drc", "fail", {"first": [dangling, violation]})])
    code, step = ask(proj)
    assert code == 1
    # the error is the failure, though the report lists a warning before it
    assert step["why"] == (
        "DRC failed: clearance: Clearance violation ( clearance 0.2000 mm; actual 0.0500 mm) "
        "at (119.0, 112.65)"
    )
    assert step["next"] == "Move the track or the pad apart; check the net class clearance."
    assert step["read"] == '.claude/skills/board-gates/SKILL.md, "Common violations"'
    assert step["run"] == f"workcenter gates {proj}"
    # a gate that ended in an engine error has its summary for a line
    report(proj, [record("erc", "error", summary="kicad-cli exited 3")])
    code, step = ask(proj)
    assert step["why"] == "ERC failed: kicad-cli exited 3" and step["next"].startswith(
        "Read the gate's report"
    )


def test_a_green_run_with_a_warning_is_not_done(tmp_path):
    proj = sim_project(tmp_path)
    warning = "no sim/corners.json: each deck ran once, at 27 C with every part at its written value"
    report(proj, [record("sim", "pass", {"failures": [], "warnings": [warning]})])
    code, step = ask(proj)
    assert code == 1 and step["why"] == f"SIM warns: {warning}"
    assert step["next"].startswith("Write sim/corners.json")
    assert step["run"] == f"workcenter gates {proj} --strict"
    assert step["done_when"] == "the last line is GREEN, with no warning"
    assert step["read"] == '.claude/skills/simulate/SKILL.md, "Corners"'


def test_a_run_whose_engine_was_absent_is_told_to_install_it(tmp_path):
    proj = sim_project(tmp_path)
    report(proj, [record("sim", "skip", {"engine_missing": "ngspice"}, "engine missing: ngspice")])
    code, step = ask(proj)
    assert code == 1 and step["next"] == "Install the toolchain: a gate did not run."
    assert step["why"] == "SKIPPED (SIM: engine missing)"


def test_a_project_with_a_package_is_done_only_when_its_requirements_are_met(tmp_path):
    proj = sim_project(tmp_path)
    (proj / "verification").mkdir()
    (proj / "verification" / "README.md").write_text("# Package\n", encoding="utf-8")
    report(proj, [record("sim", "pass", {"failures": [], "warnings": []})])
    code, step = ask(proj)
    assert code == 1 and step["next"] == "Check the verification package against a fresh run."
    assert step["run"] == f"workcenter verify {proj} --strict"

    def verify(verdicts: dict, failures: list[str]) -> dict:
        total = sum(len(v) for v in verdicts.values())
        details = {"verdicts": verdicts, "requirements": total, "problems": 0, "corners": True}
        return record("verify", "fail" if failures else "pass", {**details, "failures": failures})

    report(
        proj,
        [verify({"PASS": ["REQ-A-01"], "FAIL": [], "OPEN": ["REQ-A-02"]}, ["REQ-A-02: OPEN"])],
        "verify.json",
    )
    code, step = ask(proj)
    assert (
        code == 1 and step["why"] == "REQ-A-02: OPEN" and step["next"].startswith("A requirement is not met")
    )
    report(proj, [verify({"PASS": ["REQ-A-01", "REQ-A-02"], "FAIL": [], "OPEN": []}, [])], "verify.json")
    code, step = ask(proj)
    assert code == 0 and step["done"] is True
    assert step["next"] == "Nothing: the gates are GREEN with no warning and the requirements are met."
    # the package changes after the run
    later = time.time() + 60
    os.utime(proj / "verification" / "README.md", (later, later))
    code, step = ask(proj)
    assert code == 1 and step["why"] == "README.md changed after the last run"


def test_the_answer_prints_one_field_to_a_line(tmp_path):
    proj = sim_project(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(CLI), "next", str(proj)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 1
    assert proc.stdout.splitlines() == [
        "NEXT       Run the gates.",
        f"RUN        workcenter gates {proj}",
        "WHY        no build/gates.json yet",
        'READ       .claude/skills/board-gates/SKILL.md, "Steps"',
        "DONE WHEN  the last line starts with GREEN",
    ]
    assert not (proj / "build").exists()  # the command writes nothing


# ------------------------------------------------------------- real runs


@needs_ngspice
def test_next_walks_a_failing_project_to_its_corner_and_a_passing_one_to_done(tmp_path):
    failing = tmp_path / "corner"
    shutil.copytree(BOARDS / "fail-sim-corner", failing, ignore=shutil.ignore_patterns("build"))
    code, step = ask(failing)
    assert step["next"] == "Run the gates."
    subprocess.run([sys.executable, str(CLI), "gates", str(failing)], capture_output=True, check=False)
    code, step = ask(failing)
    assert code == 1 and step["why"].startswith("SIM failed: diode_ref:vref=0.4215933 at 85 C, R1 +5 %")
    assert step["next"].startswith(
        "The circuit is inside its bound as written and outside it at that corner."
    )
    passing = tmp_path / "filter"
    shutil.copytree(BOARDS / "pass-lc-filter", passing, ignore=shutil.ignore_patterns("build"))
    subprocess.run([sys.executable, str(CLI), "gates", str(passing)], capture_output=True, check=False)
    code, step = ask(passing)
    assert code == 0 and step["next"] == "Nothing for the bench: the gates are GREEN with no warning."


def test_the_steps_follow_the_command_lines_own_verdict():
    """`next` reads a report with the verdict function the gates print with: one definition of GREEN."""
    cli = load_cli()
    results = [cli.Result("sim", "pass", "", {"warnings": ["w"]})]
    assert cli.gates_verdict(results) == ("GREEN with 1 warning", 0)
    assert guide.trouble(cli, results) == ("sim", "w", False)
    assert guide.trouble(cli, [cli.Result("sim", "pass", "", {"warnings": []})]) is None
