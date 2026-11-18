"""The decks a schematic asks for, through the SIM gate and `workcenter next`, on tests/boards/pass-sim-bus.

pass-sim-bus is the board of tests/boards/sim_bus.py: SDA and SCL pulled up by R1 and R2 (4.7k) to +3V3,
and U1, a TLV75533PDBV of KiCad's Regulator_Linear library, with 100 mA stated on J2.1. Its 2 decks are
the templates of templates/project/sim/ with the board's values. The numbers, worked out by hand:

    i2c_rise   tr = 0.8473 x 4.7k x 50p = 199.1 ns (UM10204 Rev. 7.0, section 7.1, page 50), inside
               20 to 300 ns (Table 11, page 44); held low it sinks 3.3 / (4700 + 133.3) = 0.683 mA
    weak       fail-sim-i2c-weak: R1 10k on the same 50 pF: 0.8473 x 10k x 50p = 423.65 ns, over 300 ns;
               at its least corner, R1 -1 % and CBUS -20 %: 0.8473 x 9.9k x 40p = 335.5 ns, still over
    template   the I2C deck as shipped: 0.8473 x 4.7k x 100p = 398.2 ns

A copy of the board without a deck asks for it: a warning, a failure with --strict, and `next` names the
copy. Each test runs on a copy in tmp_path.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
TEMPLATES = ROOT / "templates" / "project" / "sim"

pytestmark = pytest.mark.skipif(
    shutil.which("kicad-cli") is None or shutil.which("ngspice") is None,
    reason="kicad-cli and ngspice are needed",
)

# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {"nxp-um10204": "Rev. 7.0, table 11, page 44, table 10, page 43 and section 7.1, page 50"}
I2C_LINE = (
    "not judged: the I2C lines SCL, SDA are pulled up by R2 (4.7k), R1 (4.7k) and no deck says "
    "`* deck: i2c-rise SCL SDA`: their rise time is held to nothing (UM10204 Rev. 7.0, Table 11, page 44); "
    "copy templates/project/sim/i2c_rise.cir"
)
LDO_LINE = (
    "not judged: U1 (Regulator_Linear:TLV75533PDBV) feeds the loads ratings.json states (J2.1 0.1 A) and "
    "no deck says `* deck: load-step U1`: its output under a load step is held to nothing (its datasheet's "
    "load transient); copy templates/project/sim/load_step.cir"
)


def run(*args: object) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    return proc.returncode, proc.stdout + proc.stderr


def sim(project: Path, *flags: str) -> dict:
    """The SIM gate's record of `project`."""
    _, text = run("sim", project, "--json", "--out", project / "build", *flags)
    return json.loads(text)[0]


def board(tmp_path: Path, *drop: str) -> Path:
    """A copy of pass-sim-bus beside a copy of tests/boards/sim_bus.py, without the decks `drop` names."""
    shutil.copy(BOARDS / "sim_bus.py", tmp_path / "sim_bus.py")
    project = tmp_path / "pass-sim-bus"
    shutil.copytree(BOARDS / "pass-sim-bus", project, ignore=shutil.ignore_patterns("build", "__pycache__"))
    for stem in drop:
        (project / "sim" / f"{stem}.cir").unlink()
        (project / "sim" / f"{stem}.expect.json").unlink()
    if "i2c_rise" in drop:  # CBUS stands in that deck alone: the corners may not name it without it
        corners = project / "sim" / "corners.json"
        data = json.loads(corners.read_text())
        del data["tolerance"]["parts"]
        corners.write_text(json.dumps(data))
    return project


def next_after_gates(project: Path) -> dict:
    """`next`'s answer once ratings (whose step comes first: the board has a ratings.json) and the
    gates have run. The ratings run judges no part of this board (no facts), which `next` names after
    the gates' steps."""
    run("ratings", project)
    run("gates", project)
    code, text = run("next", project, "--json", "--trust-design")
    assert code == 1, text
    return json.loads(text)


def test_the_fixture_is_what_its_design_file_writes():
    """bus.kicad_sch and bus.kicad_pro are what `workcenter design` writes from sim_bus.py."""
    code, text = run("design", BOARDS / "pass-sim-bus" / "design.py", "--check")
    assert code == 0 and "check: pass-sim-bus: 2 files match design.py" in text, text


def test_the_board_with_both_decks_passes_strict(tmp_path):
    """Both decks run and hold their bounds at every corner; no deck is asked for. tr is 199.1 ns."""
    r = sim(board(tmp_path), "--strict")
    assert (r["status"], r["details"]["failures"], r["details"]["warnings"]) == ("pass", [], [])
    tr = r["details"]["decks"]["i2c_rise"]["measures"]["tr"]
    assert tr == pytest.approx(199.1e-9, rel=1e-3)
    assert r["details"]["decks"]["i2c_rise"]["measures"]["isink"] == pytest.approx(0.683e-3, rel=1e-3)


def test_a_pull_up_too_weak_for_its_bus_fails_on_tr_alone(tmp_path):
    """fail-sim-i2c-weak: 423.65 ns as written, over 300 ns; every failure line is of tr."""
    project = tmp_path / "weak"
    shutil.copytree(BOARDS / "fail-sim-i2c-weak", project)
    r = sim(project, "--strict")
    failures = r["details"]["failures"]
    assert r["status"] == "fail" and failures
    assert all(f.startswith("i2c_rise:tr=") for f in failures), failures
    assert r["details"]["decks"]["i2c_rise"]["measures"]["tr"] == pytest.approx(423.65e-9, rel=1e-3)


def test_a_bus_with_no_deck_is_a_warning_and_fails_strict(tmp_path):
    """Without sim/i2c_rise.*, the I2C line is the 1 warning, and the 1 failure with --strict."""
    project = board(tmp_path, "i2c_rise")
    plain = sim(project)
    assert (plain["status"], plain["details"]["warnings"], plain["details"]["failures"]) == (
        "pass",
        [I2C_LINE],
        [],
    )
    strict = sim(project, "--strict")
    assert (strict["status"], strict["details"]["failures"]) == ("fail", [I2C_LINE])


def test_a_board_with_no_deck_at_all_is_not_green_strict(tmp_path):
    """Without sim/*.cir: SIM skips with the 2 lines as warnings, so the gates are GREEN with 2 warnings;
    with --strict SIM fails on the 2 lines, and the gates are RED."""
    project = board(tmp_path, "i2c_rise", "load_step")
    plain = sim(project)
    assert (plain["status"], plain["details"]["warnings"]) == ("skip", [I2C_LINE, LDO_LINE])
    strict = sim(project, "--strict")
    assert (strict["status"], strict["details"]["failures"]) == ("fail", [I2C_LINE, LDO_LINE])
    code, text = run("gates", project, "--strict")
    assert code == 1 and text.splitlines()[-1].startswith("RED: bus")


def test_next_names_the_copy_of_the_deck_the_board_lacks(tmp_path):
    """After a gates run, `next` names the I2C deck's copy first; its RUN line copies the deck and its
    bounds. Run as written, the copy holds the template's `* fill:` lines, and the SIM gate fails on
    each, so a copy never passes unwritten."""
    project = board(tmp_path, "i2c_rise", "load_step")
    step = next_after_gates(project)
    assert step["next"].startswith("Copy the I2C rise-time deck into sim/.")
    assert step["run"] == (
        f"mkdir -p {project}/sim && cp {TEMPLATES}/i2c_rise.cir {project}/sim/i2c_rise.cir && "
        f"cp {TEMPLATES}/i2c_rise.expect.json {project}/sim/i2c_rise.expect.json"
    )
    assert step["why"] == f"SIM: {I2C_LINE}"
    subprocess.run(["bash", "-c", step["run"]], check=True)
    failures = sim(project)["details"]["failures"]
    assert [f for f in failures if "fill:" in f] == [
        f"i2c_rise.cir:{n}: still says fill: set what it names, then delete the line" for n in (2, 9, 11, 13)
    ]


def test_next_never_names_a_deck_the_project_has(tmp_path):
    """The I2C deck is there and answers SDA and SCL: `next` names the load-step deck."""
    project = board(tmp_path, "load_step")
    step = next_after_gates(project)
    assert step["next"].startswith("Copy the load-step deck into sim/.")
    assert step["why"] == f"SIM: {LDO_LINE}"
    assert "i2c_rise" not in step["run"]


def test_a_copy_never_replaces_a_file(tmp_path):
    """sim/i2c_rise.cir is another deck that says no `* deck:` line: the copy goes to i2c_rise_2."""
    project = board(tmp_path, "load_step")
    deck = project / "sim" / "i2c_rise.cir"
    deck.write_text(deck.read_text().replace("* deck: i2c-rise SDA SCL", "* the bus"))
    step = next_after_gates(project)
    assert step["why"] == f"SIM: {I2C_LINE}"
    assert f"{project}/sim/i2c_rise_2.cir" in step["run"] and f"{project}/sim/i2c_rise.cir" not in step["run"]


def test_the_templates_run_and_fail_until_they_are_written(tmp_path):
    """The I2C template runs headless as shipped (398.2 ns over 300 ns); both templates fail on each
    `* fill:` line, and the load-step template on each bound whose source still says fill:."""
    project = tmp_path / "decks"
    shutil.copytree(TEMPLATES, project / "sim")
    r = sim(project, "--nominal")
    assert r["details"]["decks"]["i2c_rise"]["measures"]["tr"] == pytest.approx(398.2e-9, rel=1e-3)
    failures = r["details"]["failures"]
    assert sum(f.startswith("i2c_rise.cir:") and "fill:" in f for f in failures) == 4
    assert sum(f.startswith("load_step.cir:") and "fill:" in f for f in failures) == 6
    assert [f for f in failures if f.startswith("load_step.expect.json:")] == [
        f"load_step.expect.json: {n}: its source still says fill: write the document, the table and the page"
        for n in ("undershoot", "overshoot", "v_low")
    ]


def test_a_deck_that_runs_another_pull_up_than_the_schematics_fails(tmp_path):
    """The schematic's R1 and R2 made 47k, the deck left at 4.7k: the board's tr is 0.8473 x 47k x 50p
    = 1991 ns, the deck's 199.1 ns. The deck's `* deck:` line no longer answers: R1 differs, and R2 has
    no line and no pull-up the deck runs at its 47k stands for it. 2 failures, plain run or --strict."""
    project = board(tmp_path)
    sch = project / "bus.kicad_sch"
    sch.write_text(sch.read_text().replace('(property "Value" "4.7k"', '(property "Value" "47k"'))
    r = sim(project, "--nominal")
    assert r["status"] == "fail"
    assert [f for f in r["details"]["failures"] if f.startswith("i2c_rise.cir:")] == [
        "i2c_rise.cir: R1 is 4.7k in the deck and 47k in the schematic, on SDA: the deck does not run the "
        "board's pull-up; write the schematic's value",
        "i2c_rise.cir: R2 (47k) on SCL has no line in the deck, and no pull-up the deck runs has its value: "
        "name it as the schematic does, with its value",
    ]


ROOT_SHEET = """(kicad_sch
\t(version 20250114)
\t(generator "eeschema")
\t(generator_version "9.0")
\t(uuid "99999999-8888-4777-8666-555555555555")
\t(paper "A4")
\t(lib_symbols)
\t(sheet
\t\t(at 50.8 50.8)
\t\t(size 25.4 12.7)
\t\t(stroke (width 0.1524) (type solid))
\t\t(fill (color 0 0 0 0.0000))
\t\t(uuid "11111111-2222-4333-8444-555555555555")
\t\t(property "Sheetname" "bus" (at 50.8 50.0 0) (effects (font (size 1.27 1.27)) (justify left bottom)))
\t\t(property "Sheetfile" "sheets/bus.kicad_sch" (at 50.8 64.0 0)
\t\t\t(effects (font (size 1.27 1.27)) (justify left top)))
\t\t(instances (project "bus" (path "/99999999-8888-4777-8666-555555555555" (page "2"))))
\t)
\t(sheet_instances (path "/" (page "1")))
\t(embedded_fonts no)
)
"""


def test_a_bus_on_a_sheet_in_a_subfolder_is_asked_for(tmp_path):
    """The board's schematic moved to sheets/bus.kicad_sch under a root sheet that holds only its sheet
    symbol, and no deck: SIM --strict fails on both circuits, as on the flat board. The sub-sheet's
    lines keep their whole names, /bus/SCL and /bus/SDA; +3V3 is a power symbol's, global."""
    project = board(tmp_path, "i2c_rise", "load_step")
    sch = project / "bus.kicad_sch"
    text = sch.read_text().replace(
        '(path "/673f28b1-c979-5912-a8ab-2e8190040689"',
        '(path "/99999999-8888-4777-8666-555555555555/11111111-2222-4333-8444-555555555555"',
    )
    (project / "sheets").mkdir()
    (project / "sheets" / "bus.kicad_sch").write_text(text)
    sch.write_text(ROOT_SHEET)
    strict = sim(project, "--strict")
    assert (strict["status"], strict["details"]["failures"]) == (
        "fail",
        [
            "not judged: the I2C lines /bus/SCL, /bus/SDA are pulled up by R2 (4.7k), R1 (4.7k) and no deck "
            "says `* deck: i2c-rise /bus/SCL /bus/SDA`: their rise time is held to nothing (UM10204 "
            "Rev. 7.0, Table 11, page 44); copy templates/project/sim/i2c_rise.cir",
            LDO_LINE,
        ],
    )


def test_the_i2c_template_holds_a_low_voltage_bus_to_2_ma(tmp_path):
    """The I2C template filled for a 1.8 V bus as its comments say: VDD 1.8, Ron 0.2 x 1.8 / 0.002 = 180
    ohm, a 560 ohm pull-up. Held low it sinks 1.8 / (560 + 180) = 2.432 mA. UM10204 Rev. 7.0, Table 10,
    page 43: for VDD at 2 V or below a device sinks 2 mA at VOL2 (0.2 VDD), not 3 mA, so the share of
    that current the pull-up asks for is 2.432 / 2 = 1.216, over 1: a failure. The template as shipped,
    3.3 V and 4.7k, asks 3.3 / (4700 + 133.3) / 0.003 = 0.2276 of 3 mA."""
    project = tmp_path / "low"
    shutil.copytree(TEMPLATES, project / "sim")
    (project / "sim" / "load_step.cir").unlink()
    (project / "sim" / "load_step.expect.json").unlink()
    shipped = sim(project, "--nominal")["details"]["decks"]["i2c_rise"]["measures"]
    assert shipped["isink_share"] == pytest.approx(0.2276, rel=1e-3)
    deck = project / "sim" / "i2c_rise.cir"
    lines = [ln for ln in deck.read_text().splitlines() if not ln.startswith("* fill:")]
    text = "\n".join(lines) + "\n"
    text = text.replace("VDD vdd 0 DC 3.3", "VDD vdd 0 DC 1.8").replace("R1 vdd sda 4.7k", "R1 vdd sda 560")
    deck.write_text(text.replace("Ron=133.3", "Ron=180"))
    r = sim(project, "--nominal")
    assert r["details"]["decks"]["i2c_rise"]["measures"]["isink_share"] == pytest.approx(1.216, rel=1e-3)
    assert [f for f in r["details"]["failures"] if f.startswith("i2c_rise:isink_share")], r["details"]
