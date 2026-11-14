"""`workcenter next`: the one next step for a project (tools/guide.py).

Most tests write the gates report a project would have, by hand, and read the step the command gives
for it. They need no engine: `next` asks only whether an engine's name is on PATH, and they name one
that is always there. One runs the real gates on fixtures and skips when ngspice is absent. One holds
every hint to the document it points at: a fix that names a section which is not there is no fix. One
holds every sentence of an answer to its count of words.
"""

from __future__ import annotations

import ast
import importlib.machinery
import inspect
import json
import os
import re
import shlex
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
# `next` asks only whether an engine's name is on PATH. A test that writes its report by hand names
# one that is always there, and so runs on a machine with no engine.
FOUND = {"NGSPICE": sys.executable, "KICAD_CLI": sys.executable}
# The engines under their own names, for a test that runs them.
INSTALLED: dict[str, str] = {}


def load_cli():
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_guide", str(CLI))
    module = types.ModuleType("workcenter_cli_guide")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module  # dataclasses look the defining module up here
    loader.exec_module(module)
    return module


def ask(project: Path, *flags: str, env: dict | None = None) -> tuple[int, dict]:
    """The answer of `next --json`. Every engine is found unless `env` names the engines."""
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", "next", str(project), *flags],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(FOUND if env is None else env)},
    )
    return proc.returncode, json.loads(proc.stdout)


def run_line(step: dict, *flags: str) -> subprocess.CompletedProcess:
    """Run a step's RUN line as its reader does, with this checkout's `workcenter`."""
    words = shlex.split(step["run"])
    assert words[0] == "workcenter", step["run"]
    return subprocess.run(
        [sys.executable, str(CLI), *flags, *words[1:]],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **FOUND},
    )


def follow(step: dict) -> tuple[int, dict]:
    """The answer a step's RUN line gives when that line is `workcenter next <path>`."""
    assert step["run"].startswith("workcenter next "), step["run"]
    proc = run_line(step, "--json")
    return proc.returncode, json.loads(proc.stdout)


def sim_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / "sim").mkdir(parents=True)
    (proj / "sim" / "d.cir").write_text(DECK, encoding="utf-8")
    return proj


def files(folder: Path) -> list[str]:
    return sorted(str(p.relative_to(folder)) for p in folder.rglob("*"))


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


def verified(verdicts: dict, failures: list[str]) -> dict:
    """The record `workcenter verify` leaves in build/verify.json."""
    total = sum(len(v) for v in verdicts.values())
    details = {"verdicts": verdicts, "requirements": total, "problems": 0, "corners": True}
    return record("verify", "fail" if failures else "pass", {**details, "failures": failures})


# ------------------------------------------------------------- the hints

# The lines of the gates' newer checks: (gate, line, a phrase of the hint, what the hint points at).
NEWER = [
    (
        "sim",
        "d: VX is periodic and the deck gives its frequency as no number (a parameter, a PWL that "
        "repeats, an expression of time), so no plan can place it",
        "places a frequency only when the deck gives a number",
        f'{guide.SIMULATE}, "The frequency plan"',
    ),
    (
        "sim",
        "d: R2 moves and `.control` sets it again with `alter r2 = $&rv`, which a corner cannot scale: "
        "write that value as a number",
        "only when the deck writes it as a number",
        f'{guide.SIMULATE}, "Corners"',
    ),
    (
        "sim",
        "d: tolerance.parts names D1, which a corner cannot move: it moves R, C and L elements, V and I "
        "sources with a DC value, and .param",
        "no corner moves such a part",
        f'{guide.SIMULATE}, "Corners"',
    ),
    (
        "sim",
        "d: lower.inc holds R2, which no corner moves: a corner reads the deck's own lines. Write those "
        "parts in the deck",
        "not in the file it includes",
        f'{guide.SIMULATE}, "Corners"',
    ),
    (
        "sim",
        "d: R1 in .subckt half is 2 parts on the board (X1, X2): a corner moves them together",
        "as its own element",
        f'{guide.SIMULATE}, "Corners"',
    ),
    (
        "sim",
        "d: 7 ranges move and the worst case is searched 1 range at a time, so 2 parts off together can "
        "hide a miss: name monte_carlo in corners.json",
        "Its draws move the parts together",
        f'{guide.SIMULATE}, "Corners"',
    ),
    (
        "sim",
        "d: q_peak is not printed at L1 -20 %: its least and its greatest are not known",
        "exists at every corner",
        f'{guide.SIMULATE}, "Corners"',
    ),
    (
        "sim",
        "frequency plan: resonance input filter is read from filter, which no tolerance moves, so its "
        "band holds no part's tolerance: give the deck its corners in sim/corners.json",
        "the resonance then moves with its parts",
        f'{guide.SIMULATE}, "The frequency plan"',
    ),
    (
        "sim",
        "d:vout=4.5 not in [2.3, 2.7]: the deck prints vout more than once, and this value came before "
        "its last",
        "Print each measure once",
        f'{guide.SIMULATE}, "Steps"',
    ),
    (
        "verify",
        "REQ-OUT-01: judged as written only: its deck rc_divider ran no corner (the reason)",
        "its deck ran none",
        f'{guide.VERIFICATION}, "Corners"',
    ),
]


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
        (
            "erc",
            "simulation_model_issue: Simulation model library not found at '/p/models/none.lib'",
            "KiCad cannot load the model",
        ),
        (
            "design",
            "sim: U1: pins leaves out 3, 4: map each to a node of the model, or to None for a pin the "
            "model has no node for",
            "names every pin number of the symbol",
        ),
        ("design", "pull: GATE: Q1.1 (G, input), and no resistor to a rail holds it", "Hold the net"),
        ("design", "via: GND via at (1, 2) is 0.05 mm from R1.1", "Move the via"),
        ("design", "part: R1 stands in the keep-out 'strip'", "Move the part"),
        (
            "design",
            "part: J1 at (4, 7.5): every pad lies outside the outline, (100, 100) to (125, 120). pcb_at is "
            "in board coordinates, as the outline is: the board's top left corner is (100, 100), so a part "
            "4 mm right of it and 7.5 mm below it is at pcb_at=(104, 107.5)",
            "Write the part's pcb_at in board coordinates",
        ),
        (
            "design",
            'file: power_nets is a list, not a dict. Write d.power_nets = {"GND": "GND"}: each power net, '
            "then the symbol of KiCad's power library that draws it.",
            "Correct the design file as the line says",
        ),
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
        (
            "sim",
            "inst: D1 is held at its own temperature (temp=), so no temperature corner moves it: remove "
            "the setting, or set the deck's temperature to false in corners.json with why",
            "fixes its temperature",
        ),
        (
            "sim",
            "d: R1: ngspice reads the value 4k7 as 4k: it drops a digit after the scale letter. Write 4.7k",
            "the way ngspice reads a number",
        ),
        (
            "sim",
            "d: altermod DMOD: ngspice applies only the first parameter on the line (is) and drops rs. "
            "Write 1 altermod line for each parameter",
            "Split the altermod line",
        ),
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
        *[row[:3] for row in NEWER],
    ],
)
def test_a_line_is_answered_with_the_fix_for_its_kind(gate, line, said):
    do, read = guide.hint(gate, line)
    assert said in do, do
    assert read


@pytest.mark.parametrize(("gate", "line", "read"), [(row[0], row[1], row[3]) for row in NEWER])
def test_a_line_of_a_newer_check_points_at_the_section_that_explains_it(gate, line, read):
    """An older, looser pattern above a line's own would answer it first, with another section."""
    assert guide.hint(gate, line)[1] == read


def sentences(text: str) -> list[str]:
    """A text's sentences as STYLE.md's rule 2 counts them: a sentence ends at ". " or at the text's
    end, and a code span in backticks is 1 word."""
    return [s for s in re.sub(r"`[^`]*`", "`code`", text).split(". ") if s]


def test_no_sentence_of_a_hint_or_of_a_step_is_over_20_words(tmp_path, monkeypatch):
    """A small model follows an answer word for word, so a sentence is 1 instruction it can hold
    (ee-agent-kit/docs/STYLE.md, rules 1 and 2). Every hint is counted, and every step: the last
    assertion fails when a `Step(` of guide.py is the answer of no project here.

    A WHY that quotes a line of a gate is as long as that line. The lines here are short, so the count
    is of guide.py's own words."""
    cli = load_cli()
    monkeypatch.setattr(cli, "NGSPICE", sys.executable)
    monkeypatch.setattr(cli, "KICAD_CLI", sys.executable)
    reached: set[int] = set()

    class Seen(guide.Step):
        def __init__(self, *args, **kwargs):
            reached.add(inspect.currentframe().f_back.f_lineno)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(guide, "Step", Seen)
    steps: list[guide.Step] = []

    def answer(target: Path) -> None:
        steps.append(guide.next_step(cli, str(target)))

    def project(name: str, *records: dict) -> Path:
        proj = sim_project(tmp_path / name)
        if records:
            report(proj, list(records))
        return proj

    def says(text: str) -> types.SimpleNamespace:
        """Stand in for `subprocess` in guide.py: a design check that exits 1 and prints `text`."""
        check = types.SimpleNamespace(returncode=1, stdout=text)
        return types.SimpleNamespace(run=lambda *args, **kwargs: check)

    passed = record("sim", "pass", {"failures": [], "warnings": []})
    later = time.time() + 60
    # the path
    answer(tmp_path / "missing")
    answer(project("file") / "sim" / "d.cir")
    two = tmp_path / "two"
    two.mkdir()
    for name in ("a", "b"):
        (two / f"{name}.kicad_pro").write_text("{}\n", encoding="utf-8")
    answer(two)
    empty = tmp_path / "empty"
    empty.mkdir()
    answer(empty)
    (empty / "design.py").write_text("# a design\n", encoding="utf-8")
    answer(empty)
    # the toolchain
    with monkeypatch.context() as patch:
        patch.setattr(cli, "NGSPICE", "no-such-ngspice")
        answer(project("absent"))
    # the design file: refused, then different from the project
    designed = project("designed")
    (designed / "design.py").write_text("# a design\n", encoding="utf-8")
    for printed in (
        "sim: U1: pins leaves out 3\ndesign proj red: 1 simulation problem\n",
        "check: differs  proj.kicad_sch\ncheck: proj: red, 1 of 2 files differ from design.py\n",
    ):
        with monkeypatch.context() as patch:
            patch.setattr(guide, "subprocess", says(printed))
            answer(designed)
    # the gates' report
    answer(project("fresh"))
    stale = project("stale", passed)
    os.utime(stale / "sim" / "d.cir", (later, later))
    answer(stale)
    answer(project("engine", record("sim", "skip", {"engine_missing": "ngspice"}, "engine missing: ngspice")))
    nothing = tmp_path / "nothing"
    (nothing / "sim").mkdir(parents=True)
    report(nothing, [record("sim", "skip", summary="no sim/*.cir in project")])
    answer(nothing)
    answer(project("red", record("sim", "fail", {"failures": ["d:vout=3.0 not in [2.45, 2.55]"]})))
    answer(project("warned", record("sim", "pass", {"failures": [], "warnings": ["w"]})))
    answer(project("decks", passed))
    board = tmp_path / "board"
    board.mkdir()
    (board / "b.kicad_sch").write_text("", encoding="utf-8")
    report(board, [record("erc", "pass")])
    answer(board)
    # the verification package: not run, a requirement open, met, changed after its run
    package = project("package", passed)
    (package / "verification").mkdir()
    (package / "verification" / "README.md").write_text("# Package\n", encoding="utf-8")
    answer(package)
    report(
        package, [verified({"PASS": [], "FAIL": [], "OPEN": ["REQ-A-01"]}, ["REQ-A-01: OPEN"])], "verify.json"
    )
    answer(package)
    report(package, [verified({"PASS": ["REQ-A-01"], "FAIL": [], "OPEN": []}, [])], "verify.json")
    answer(package)
    os.utime(package / "verification" / "README.md", (later, later))
    answer(package)

    texts = [do for _, do, _ in guide.HINTS]
    texts += [text for step in steps for text in (step.next, step.why, step.done_when)]
    long = [(len(s.split()), s) for text in texts for s in sentences(text) if len(s.split()) > 20]
    assert not long, long
    tree = ast.parse(Path(guide.__file__).read_text(encoding="utf-8"))
    sites = {
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Step"
    }
    assert sites == reached, f"no project here is answered by the Step of line {sorted(sites - reached)}"


# ------------------------------------------------------------- the path


def test_a_file_is_answered_with_the_folder_of_its_project(tmp_path):
    """Taken for a project, a deck was told "Run the gates" with its own path. That run left build/
    inside sim/, and the next answers named paths under the deck's name, which cannot exist."""
    proj = sim_project(tmp_path)
    deck = proj / "sim" / "d.cir"
    code, step = ask(deck)
    assert code == 1 and step["done"] is False
    assert step["next"] == "Name the project's folder: the path leads to a file, and a project is a folder."
    assert step["run"] == f"workcenter next {proj}"
    assert step["why"] == f"{deck} is a file; a project is named by its folder"
    assert step["done_when"] == f"`workcenter next {proj}` names another step"
    # the RUN line is a command, and its answer is the project's
    code, step = follow(step)
    assert (code, step["next"], step["run"]) == (1, "Run the gates.", f"workcenter gates {proj}")
    # a file beside the project's own, a file that is not written yet, and the paths the old answers
    # led to, under the deck: each is answered with the same folder
    (proj / "notes.txt").write_text("a note\n", encoding="utf-8")
    for path in (
        proj / "notes.txt",
        proj / "design.py",
        proj / "sim" / "new.cir",
        deck / "design.py",
        deck / "sim" / "x.cir",
    ):
        code, step = ask(path)
        assert (code, step["run"]) == (1, f"workcenter next {proj}"), path
    assert files(proj) == ["notes.txt", "sim", "sim/d.cir"]  # no answer made a folder of a file's name


def test_a_folder_with_two_project_files_is_told_to_name_one(tmp_path):
    """Every refusal of `find_project` was answered "Start the project". 2 project files in a folder
    are answered with one of them, and each later RUN line takes that file."""
    for name in ("b", "a"):
        (tmp_path / f"{name}.kicad_pro").write_text("{}\n", encoding="utf-8")
    code, step = ask(tmp_path)
    assert code == 1 and step["next"] == (
        "Name one of the folder's 2 project files: a.kicad_pro, b.kicad_pro. The RUN line names the first."
    )
    assert step["run"] == f"workcenter next {tmp_path}/a.kicad_pro"
    assert step["why"] == f"{tmp_path}: 2 .kicad_pro files; name one"
    assert step["done_when"] == f"`workcenter next {tmp_path}/a.kicad_pro` names another step"
    code, step = follow(step)
    assert (code, step["next"]) == (1, "Run the gates.")
    assert step["run"] == f"workcenter gates {tmp_path}/a.kicad_pro"
    # that line runs: with no schematic, no board and no deck it has nothing for an engine
    ran = run_line(step)
    assert ran.returncode == 2 and ran.stdout.splitlines()[-1].startswith("SKIPPED"), ran.stdout + ran.stderr
    code, step = ask(tmp_path / "a.kicad_pro")
    assert code == 1 and step["next"].startswith("Give the gates something to run")
    # a path inside the project starts at its folder, not at the file that names the project
    assert step["next"].endswith(f"Write {tmp_path}/sim/<name>.cir, or {tmp_path}/design.py for a board.")
    # a design file does not change the first answer: generated again, the folder holds 2 project files
    (tmp_path / "design.py").write_text("# a design\n", encoding="utf-8")
    code, step = ask(tmp_path)
    assert (code, step["run"]) == (1, f"workcenter next {tmp_path}/a.kicad_pro")


def test_a_folder_that_is_not_there_is_created_first(tmp_path):
    """ "<path>: not found" under "Start the project" did not say whether the command had failed."""
    new = tmp_path / "boards" / "psu"
    code, step = ask(new)
    assert code == 1 and step["next"] == "Create the project's folder: it does not exist yet."
    assert step["run"] == f"mkdir -p {new}" and step["why"] == f"{new}: not found"
    assert step["done_when"] == f"`workcenter next {new}` names another step"
    assert not new.parent.exists()  # the command writes nothing
    new.mkdir(parents=True)  # what the RUN line does
    code, step = ask(new)
    assert code == 1 and step["next"].startswith("Start the project with a deck")


# ------------------------------------------------------------- the steps


def test_a_folder_with_nothing_in_it_is_told_the_ways_to_start(tmp_path):
    code, step = ask(tmp_path)
    assert code == 1 and step["done"] is False
    assert step["next"].startswith("Start the project with a deck, or with a design file for a board.")
    assert f"{tmp_path}/sim/<name>.cir" in step["next"] and f"{tmp_path}/design.py" in step["next"]
    assert f"{tmp_path}/sim/<name>.expect.json" in step["next"]
    assert f"can start from a copy of {ROOT}/templates/project/design.py." in step["next"]
    # a chip starts with its own command, which writes the folder's first files
    assert step["next"].endswith(
        f"For a chip, `workcenter chip init {tmp_path} --top <module>` writes the project's first files."
    )
    # 3 ways to start are not 1 command: a reader who runs every RUN line is given none
    assert step["run"] == ""
    assert step["done_when"] == f"`workcenter next {tmp_path}` names another step"
    assert step["read"] == (
        '.claude/skills/simulate/SKILL.md, "Steps"; .claude/skills/board-design/SKILL.md, "Steps"; '
        '.claude/skills/chip-design/SKILL.md, "Steps"'
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


def test_a_report_from_a_run_without_an_engine_is_run_again_when_the_engine_is_found(tmp_path):
    """The report's SKIPPED was answered "Install the toolchain" for as long as the report stood, also
    after the installation: no step ran the gates again."""
    proj = sim_project(tmp_path)
    report(proj, [record("sim", "skip", {"engine_missing": "ngspice"}, "engine missing: ngspice")])
    absent = str(tmp_path / "no-such-ngspice")
    code, step = ask(proj, env={"NGSPICE": absent})
    assert code == 1 and step["next"] == "Install the toolchain: a gate cannot run without its engine."
    assert step["why"] == f"{absent} is not on PATH"
    code, step = ask(proj)
    assert (
        code == 1 and step["next"] == "Run the gates again: the report is from a run with an engine absent."
    )
    assert step["run"] == f"workcenter gates {proj}"
    assert step["why"] == (
        "build/gates.json says SKIPPED (SIM: engine missing); every engine the project needs is on PATH now"
    )
    assert step["done_when"] == "the last line starts with GREEN"


def test_a_project_with_a_package_is_done_only_when_its_requirements_are_met(tmp_path):
    proj = sim_project(tmp_path)
    (proj / "verification").mkdir()
    (proj / "verification" / "README.md").write_text("# Package\n", encoding="utf-8")
    report(proj, [record("sim", "pass", {"failures": [], "warnings": []})])
    code, step = ask(proj)
    assert code == 1 and step["next"] == "Check the verification package against a fresh run."
    assert step["run"] == f"workcenter verify {proj} --strict"
    report(
        proj,
        [verified({"PASS": ["REQ-A-01"], "FAIL": [], "OPEN": ["REQ-A-02"]}, ["REQ-A-02: OPEN"])],
        "verify.json",
    )
    code, step = ask(proj)
    assert (
        code == 1 and step["why"] == "REQ-A-02: OPEN" and step["next"].startswith("A requirement is not met")
    )
    report(proj, [verified({"PASS": ["REQ-A-01", "REQ-A-02"], "FAIL": [], "OPEN": []}, [])], "verify.json")
    code, step = ask(proj)
    assert code == 0 and step["done"] is True
    assert step["next"] == "Nothing: the gates are GREEN with no warning and the requirements are met."
    # the package changes after the run
    later = time.time() + 60
    os.utime(proj / "verification" / "README.md", (later, later))
    code, step = ask(proj)
    assert code == 1 and step["why"] == "README.md changed after the last run"


def test_the_answer_prints_one_field_to_a_line(tmp_path):
    def printed(project: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CLI), "next", str(project)],
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, **FOUND},
        )

    proj = sim_project(tmp_path)
    proc = printed(proj)
    assert proc.returncode == 1
    assert proc.stdout.splitlines() == [
        "NEXT       Run the gates.",
        f"RUN        workcenter gates {proj}",
        "WHY        no build/gates.json yet",
        'READ       .claude/skills/board-gates/SKILL.md, "Steps"',
        "DONE WHEN  the last line starts with GREEN",
    ]
    assert not (proj / "build").exists()  # the command writes nothing
    # an answer with no single command prints no RUN line: a shell refuses 2 commands joined by "or"
    empty = tmp_path / "empty"
    empty.mkdir()
    labels = [line[:10].strip() for line in printed(empty).stdout.splitlines()]
    assert labels == ["NEXT", "WHY", "READ", "DONE WHEN"]


def test_next_leaves_the_project_as_it_was(tmp_path):
    """`next` checks a design file against its project, and the check imports the file. Started with
    no word about bytecode, the check left __pycache__/design.cpython-*.pyc in the project."""
    proj = sim_project(tmp_path)
    (proj / "design.py").write_text("# a design\n", encoding="utf-8")
    before = files(proj)
    # the caller's own setting is taken away, so the answer's own is what keeps the folder as it was
    code, step = ask(proj, env={**FOUND, "PYTHONDONTWRITEBYTECODE": ""})
    assert code == 1 and step["next"].startswith("Regenerate the KiCad project")  # the check ran
    assert files(proj) == before


# ------------------------------------------------------------- real runs


@needs_ngspice
def test_next_walks_a_failing_project_to_its_corner_and_a_passing_one_to_done(tmp_path):
    failing = tmp_path / "corner"
    shutil.copytree(BOARDS / "fail-sim-corner", failing, ignore=shutil.ignore_patterns("build"))
    code, step = ask(failing, env=INSTALLED)
    assert step["next"] == "Run the gates."
    subprocess.run([sys.executable, str(CLI), "gates", str(failing)], capture_output=True, check=False)
    code, step = ask(failing, env=INSTALLED)
    assert code == 1 and step["why"].startswith("SIM failed: diode_ref:vref=0.4215933 at 85 C, R1 +5 %")
    assert step["next"].startswith(
        "The circuit is inside its bound as written and outside it at that corner."
    )
    passing = tmp_path / "filter"
    shutil.copytree(BOARDS / "pass-lc-filter", passing, ignore=shutil.ignore_patterns("build"))
    subprocess.run([sys.executable, str(CLI), "gates", str(passing)], capture_output=True, check=False)
    code, step = ask(passing, env=INSTALLED)
    assert code == 0 and step["next"] == "Nothing: every deck holds its bounds, GREEN with no warning."
    # a finished project is given no command: a reader who runs every RUN line would run one more
    assert step["run"] == "" and step["done"] is True


def test_a_finished_board_is_told_what_proves_it_and_given_no_command(tmp_path):
    proj = tmp_path / "divider"
    shutil.copytree(BOARDS / "pass-rc-divider", proj, ignore=shutil.ignore_patterns("build"))
    gates = ("erc", "drc", "sim", "export")
    report(proj, [record(gate, "pass", {"failures": [], "warnings": []}) for gate in gates])
    code, step = ask(proj)
    assert code == 0 and step["next"] == "Nothing for the bench: the gates are GREEN with no warning."
    assert step["run"] == ""
    assert step["why"] == (
        "a board that leaves the bench has its parts and its requirements proven first. "
        f"`workcenter sources {proj}` holds each part to its datasheet and its model "
        "(ee-agent-kit/PROCESSES.md, P27). "
        f"`workcenter verify {proj} --init` starts the requirements (ee-agent-kit/PROCESSES.md, P28)"
    )
    # named by its project file, the board is the same project, and both commands take the file
    named = proj / "rc_divider.kicad_pro"
    code, step = ask(named)
    assert code == 0 and step["run"] == ""
    assert (
        f"`workcenter sources {named}`" in step["why"]
        and f"`workcenter verify {named} --init`" in step["why"]
    )


def test_the_steps_follow_the_command_lines_own_verdict(tmp_path, monkeypatch):
    """`next` reads a report with the verdict function the gates print with: one definition of GREEN."""
    cli = load_cli()
    monkeypatch.setattr(cli, "NGSPICE", sys.executable)
    proj = sim_project(tmp_path)
    warned = record("sim", "pass", {"failures": [], "warnings": ["w"]})
    report(proj, [warned])
    results = [cli.Result(**warned)]
    assert cli.gates_verdict(results)[0].startswith("GREEN with 1 warning")
    assert guide.trouble(cli, results) == ("sim", "w", False)
    assert guide.trouble(cli, [cli.Result("sim", "pass", "", {"warnings": []})]) is None
    assert guide.next_step(cli, str(proj)).why == "SIM warns: w"
    # given another verdict for the same report, the step is that verdict's: `next` has none of its own
    asked = []

    def skipped(results: list) -> tuple[str, int]:
        asked.append([(r.gate, r.status) for r in results])
        return "SKIPPED", cli.EXIT_SKIP

    monkeypatch.setattr(cli, "gates_verdict", skipped)
    step = guide.next_step(cli, str(proj))
    assert asked == [[("sim", "pass")]]
    assert step.next.startswith("Give the gates something to run") and step.run == f"workcenter gates {proj}"


REFUSED = """
import sys, uuid
sys.path.insert(0, {tools!r})
from kicadgen import Design

def build():
    d = Design(name="refused", namespace=uuid.UUID("11111111-2222-3333-4444-55555555555b"))
    d.power_nets = {{"GND": "GND"}}
    d.flagged_nets = ["GND"]
    d.outline = (100.0, 100.0, 110.0, 110.0)
    d.add("R1", "Device:R", "10k", None, sch_at=(50.8, 50.8), nets={{"1": "A", "2": "GND"}})
    d.add("D1", "Device:D", "D", None, sch_at=(76.2, 50.8), nets={{"1": "GND", "2": "A"}})
    PINS
    return d
"""


@pytest.mark.skipif(
    not Path("/usr/share/kicad/symbols/Device.kicad_sym").is_file(),
    reason="KiCad symbol libraries are not installed",
)
def test_a_design_file_that_is_refused_is_answered_with_its_first_problem(tmp_path):
    """`design --check` exits 1 on a difference and on the design step's own refusal. Told to
    regenerate, a reader of the second gets the same refusal again: the step names the problem."""
    proj = tmp_path / "proj"
    proj.mkdir()
    src = proj / "design.py"
    body = REFUSED.format(tools=str(ROOT / "tools"))
    src.write_text(body.replace("PINS", "pass"), encoding="utf-8")
    made = subprocess.run(
        [sys.executable, str(CLI), "design", str(src)], capture_output=True, text=True, check=False
    )
    assert made.returncode == 0, made.stdout + made.stderr
    code, step = ask(proj)
    assert code == 1 and step["next"] == "Run the gates."
    src.write_text(body.replace("PINS", 'd.sim("D1", device="D", pins={"1": "K"})'), encoding="utf-8")
    code, step = ask(proj)
    assert code == 1 and step["next"].startswith("Correct what the design file says about that part's")
    assert step["why"].startswith("the design file is refused: sim: D1: pins leaves out 2: map each")
    assert step["run"].endswith("design.py --route") and step["read"].endswith(
        'board-design/SKILL.md, "Steps"'
    )
    # a design file the generator refuses when it is loaded prints no traceback: the step names the line
    src.write_text(body.replace("PINS", 'd.power_nets = ["GND"]'), encoding="utf-8")
    code, step = ask(proj)
    assert code == 1 and step["next"] == "Correct the design file as the line says: it names what to write."
    assert step["why"] == (
        "the design file is refused: file: power_nets is a list, not a dict. Write d.power_nets = "
        '{"GND": "GND"}: each power net, then the symbol of KiCad\'s power library that draws it.'
    )
    # a design file that differs from the project and is not refused is still told to regenerate
    src.write_text(body.replace("PINS", 'd.no_sim("D1", "left out of this test")'), encoding="utf-8")
    code, step = ask(proj)
    assert code == 1 and step["next"].startswith("Regenerate the KiCad project")
