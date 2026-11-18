"""Roadmap item 7, the parts the SIM gate asks for: every part of the board whose facts carry a thermal
figure, whether sim/thermal.json names it or not; and the record of a run that SPRA953D's equation 5
judged. No test here starts an engine.

The numbers are read from these documents:
- TLV755P datasheet SBVS320D, section 5.4, page 5: the JEDEC rows of the DBV column, RthetaJA 231.1,
  RthetaJC(top) 118.4, RthetaJB 64.4, psiJT 28.4 and psiJB 63.8 C/W; section 5.1, page 4: an operating
  junction of 150 C at the most (tests/boards/library/facts/ti-tlv755p.json).
- TI SPRA953D, section 1.1, equation 1, page 2: TJ = TA + RthetaJA x power; section 2.2, equation 4,
  page 7: TJ = TC + RthetaJC x power; equation 5: TJ = TA + (RthetaJC + Rtheta(CS) + Rtheta(SA)) x power.
- ECSS-Q-ST-30-11C Rev.2, clause 6.21.2, table 6-21, page 57: 110 C or Tjmax - 40 C, the lower.
"""

from __future__ import annotations

import importlib.machinery
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
FACTS = BOARDS / "library" / "facts"
sys.path.insert(0, str(ROOT / "tools"))
import guide  # noqa: E402
import ratings  # noqa: E402
import thermal  # noqa: E402

# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {
    "ti-sbvs320": "sections 5.1 and 5.4, pages 4 and 5",
    "ti-spra953d": "section 1.1, equation 1, page 2; section 2.2, equations 4 and 5, page 7",
    "ecss-q-st-30-11c-rev2": "clause 6.21.2, table 6-21, page 57",
}

FACTS_LIST = ratings.read_facts(FACTS)
ECSS = ratings.read_pack(ROOT / "rules" / "ratings" / "ecss-q-st-30-11c-rev2.json")
TLV = next(f for f in FACTS_LIST if f.data.get("mpn") == "TLV75533PDBVR")
CAP = next(f for f in FACTS_LIST if "thermal" not in f.data)
U1_LINE = (
    "thermal: U1 (TLV75533PDBVR) not judged: its facts (ti-tlv755p.json) carry junction_max 150 C and "
    "theta_ja 231.1 C/W, theta_jc 118.4 C/W, theta_jb 64.4 C/W, psi_jt 28.4 C/W and psi_jb 63.8 C/W (p 4 "
    "and 5), and sim/thermal.json names no row for it: write its row under `parts` (the simulate skill, A "
    'part\'s temperature, step 3): "U1": {"mpn": "TLV75533PDBVR", "watts": "<deck>.<measure>", '
    '"source": "<how the deck gives its power>"}'
)


def load_cli() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_thermal_asked", str(CLI))
    module = types.ModuleType("workcenter_cli_thermal_asked")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module  # dataclasses look the defining module up here
    loader.exec_module(module)
    return module


# ---------------------------------------------------------------- the parts asked for


def test_a_part_whose_facts_carry_a_thermal_figure_and_no_row_is_not_judged_and_named():
    """U1's facts carry junction_max 150 C and 5 figures; the plan names only U9, so U1 is asked for, on 1
    line that names the part, every figure its facts carry with their pages, and the row to write. C1's
    facts carry no `thermal`: it is not asked for."""
    entries = {"U1": ("TLV75533PDBVR", TLV), "C1": ("CL10A106KP8NNN", CAP), "R1": ("", None)}
    board = thermal.asked(entries, {"U9"})
    assert board["not_judged"] == [U1_LINE]
    assert board["asked"] == ["U1"] and board["unplanned"] == ["U1"]
    assert board["line"] == (
        "thermal: 1 part of the board carries a thermal figure in its facts: U1; sim/thermal.json names 0 "
        "of them"
    )


def test_the_same_part_named_in_the_plan_is_asked_for_and_not_named_again():
    """The same board with U1's row: nothing is left unjudged by the board's parts."""
    entries = {"U1": ("TLV75533PDBVR", TLV), "C1": ("CL10A106KP8NNN", CAP)}
    board = thermal.asked(entries, {"U1"})
    assert board["not_judged"] == [] and board["unplanned"] == []
    assert board["line"] == (
        "thermal: 1 part of the board carries a thermal figure in its facts: U1; sim/thermal.json names 1 "
        "of them"
    )


def test_with_no_plan_every_part_with_a_thermal_figure_is_named():
    """No sim/thermal.json: U1 and U2 are both asked for, in the board's order (U2 before U10)."""
    entries = {"U10": ("TLV75533PDBVR", TLV), "U2": ("TLV75533PDBVR", TLV)}
    board = thermal.asked(entries, None)
    assert [line.split(" not judged")[0] for line in board["not_judged"]] == [
        "thermal: U2 (TLV75533PDBVR)",
        "thermal: U10 (TLV75533PDBVR)",
    ]


def test_a_board_with_no_part_that_carries_a_thermal_figure_says_so_in_1_line():
    """3 parts: C1's facts carry no thermal figure, R1 and R2 have no facts entry. Nothing is asked for,
    and the line counts the 2 parts with no facts, which `workcenter ratings` names."""
    entries = {"C1": ("CL10A106KP8NNN", CAP), "R1": ("", None), "R2": ("", None)}
    board = thermal.asked(entries, None)
    assert board["not_judged"] == [] and board["asked"] == []
    assert board["line"] == (
        "thermal: no part of the board carries a thermal figure in its facts, so no junction is asked for "
        "(3 parts; 2 with no facts entry, which `workcenter ratings` names)"
    )


def test_a_part_with_no_part_number_is_named_by_its_facts_entry():
    """A part matched by its symbol has no part number: the line and the row name the entry's name."""
    entry = ratings._facts("sym.json", {**{k: v for k, v in TLV.data.items() if k != "mpn"}, "symbol": "LDO"})
    board = thermal.asked({"U1": ("", entry)}, None)
    assert board["not_judged"][0].startswith("thermal: U1 (LDO) not judged: its facts (sym.json) carry")
    assert board["not_judged"][0].endswith(
        '"U1": {"mpn": "LDO", "watts": "<deck>.<measure>", "source": "<how the deck gives its power>"}'
    )


# ---------------------------------------------------------------- the gate's reading of the board


def project_at(cli, folder: Path, sch: bool):
    folder.mkdir(parents=True, exist_ok=True)
    schematic = folder / "node.kicad_sch"
    if sch:
        schematic.write_text("(kicad_sch)", encoding="utf-8")
    return cli.Project(folder, "node", None, schematic if sch else None, None)


def test_a_project_with_no_facts_says_so_in_1_line_and_starts_no_engine(tmp_path, monkeypatch):
    """No library/facts: no part carries a thermal figure. kicad-cli is pointed at nothing, so a run that
    asked for it would say so: the 1 line is the whole answer."""
    cli = load_cli()
    monkeypatch.setattr(cli, "KICAD_CLI", "no-such-kicad-cli")
    project = project_at(cli, tmp_path / "board", sch=True)
    record, unjudged = cli.thermal_board(project, tmp_path / "out", None)
    assert unjudged == []
    assert record["line"] == (
        "thermal: the project has no library/facts, so no part of the board carries a thermal figure and "
        "none is asked for; `workcenter ratings` names the parts with no facts"
    )


def test_facts_with_no_thermal_figure_say_so_in_1_line_and_start_no_engine(tmp_path, monkeypatch):
    """A library whose 1 entry, a capacitor, carries no `thermal`: nothing is asked for."""
    cli = load_cli()
    monkeypatch.setattr(cli, "KICAD_CLI", "no-such-kicad-cli")
    (tmp_path / "library" / "facts").mkdir(parents=True)
    (tmp_path / "library" / "facts" / "c.json").write_text(json.dumps(CAP.data), encoding="utf-8")
    project = project_at(cli, tmp_path / "board", sch=True)
    record, unjudged = cli.thermal_board(project, tmp_path / "out", None)
    assert unjudged == []
    assert record["line"] == (
        "thermal: no facts entry of library/facts carries a thermal figure (1 entry), so no part of the "
        "board is asked for"
    )


def test_a_project_with_no_schematic_names_no_part_of_a_board(tmp_path):
    """Thermal facts and no schematic: the project names no part of a board, and the line says that only
    the plan's parts are judged."""
    cli = load_cli()
    (tmp_path / "library" / "facts").mkdir(parents=True)
    (tmp_path / "library" / "facts" / "u.json").write_text(json.dumps(TLV.data), encoding="utf-8")
    project = project_at(cli, tmp_path / "board", sch=False)
    record, unjudged = cli.thermal_board(project, tmp_path / "out", {"U1"})
    assert unjudged == []
    assert record["line"] == (
        "thermal: the project has no schematic, so it names no part of a board: only the parts "
        "sim/thermal.json names are judged"
    )


def test_a_schematic_kicad_cli_cannot_read_leaves_the_board_s_parts_not_judged(tmp_path, monkeypatch):
    """Thermal facts and a schematic, and no kicad-cli: which parts carry a figure is not judged, 1 line
    with the reason; --strict fails on it as on every not-judged line."""
    cli = load_cli()
    monkeypatch.setattr(cli, "KICAD_CLI", "no-such-kicad-cli")
    (tmp_path / "library" / "facts").mkdir(parents=True)
    (tmp_path / "library" / "facts" / "u.json").write_text(json.dumps(TLV.data), encoding="utf-8")
    project = project_at(cli, tmp_path / "board", sch=True)
    record, unjudged = cli.thermal_board(project, tmp_path / "out", None)
    assert record["line"] is None
    assert unjudged == [
        "thermal: which parts of the board carry a thermal figure is not judged: no-such-kicad-cli is not "
        "on PATH to read the schematic's parts"
    ]


def test_the_record_carries_the_board_s_line_and_the_gate_prints_it():
    """`sim` and `gates` print the board's line from the record, after the line of no plan."""
    details = {"thermal": {"parts": {}, "unplanned": thermal.NO_PLAN, "board": {"line": "thermal: x"}}}
    assert thermal.lines(details) == [thermal.NO_PLAN, "thermal: x"]


# ---------------------------------------------------------------- workcenter next


def test_workcenter_next_sends_an_unplanned_part_to_step_3_of_the_skill():
    """The not-judged line of a part with no row asks for its row in sim/thermal.json."""
    do, read = guide.hint("sim", U1_LINE)
    assert do.startswith("Write the part's row in sim/thermal.json, as the line gives it (step 3).")
    assert read.endswith('"A part\'s temperature"')


# ---------------------------------------------------------------- the record of equation 5


def plan_of(tmp_path: Path, parts: dict) -> thermal.Plan:
    (tmp_path / "thermal.json").write_text(
        json.dumps({"pack": "ecss-q-st-30-11c-rev2", "parts": parts}), encoding="utf-8"
    )
    plan, problems = thermal.read_plan(tmp_path, ["ldo"])
    assert problems == []
    return plan


U1 = {"mpn": "TLV75533PDBVR", "watts": "ldo.p_u1", "source": "input power less output power"}
SINK = {"name": "a sink made up for the test", "theta_cs": 0.5, "source": "made up for the test"}


def test_a_run_equation_5_judged_names_theta_jc_and_keeps_what_theta_ja_gave_beside_it(tmp_path):
    """A case stated at 25 C only, on a sink of theta_sa 120 C/W. At 85 C no case is stated, so theta_ja
    gives 85 + 231.1 x 0.17295 = 124.968745 C (equation 1) and equation 5 gives 85 + (118.4 + 0.5 + 120)
    x 0.17295 = 126.317755 C: equation 5 judges, so the row names theta_jc, not theta_ja."""
    case = {"figure": "theta_jc", "celsius": {"25": 27}, "source": "a thermocouple"}
    plan = plan_of(tmp_path, {"U1": {**U1, "from": {**case, "heat_sink": {**SINK, "theta_sa": 120}}}})
    runs = {"ldo": [("85 C", 85.0, {"p_u1": 0.17295})]}
    worst = thermal.judge(plan, runs, FACTS_LIST, ECSS)["parts"]["U1"]["worst"]
    assert worst["equation"] == "5" and worst["figure"] == "theta_jc"
    assert worst["junction"] == pytest.approx(126.317755)
    assert worst["beside"] == {"figure": "theta_ja", "equation": "1", "junction": pytest.approx(124.968745)}


def test_a_run_equation_5_judged_over_a_stated_case_starts_from_the_ambient(tmp_path):
    """A case 0.001 C above the air at 85 C on a sink of theta_sa 30 C/W: equation 4 gives 85.001 + 118.4
    x 0.17295 = 105.47828 C, equation 5 gives 85 + 148.9 x 0.17295 = 110.752255 C. The row names
    equation 5's start, the ambient, and keeps the case beside; the printed line names no case."""
    case = {"figure": "theta_jc", "celsius": {"85": 85.001}, "source": "a case 0.001 C above the air"}
    plan = plan_of(tmp_path, {"U1": {**U1, "from": {**case, "heat_sink": {**SINK, "theta_sa": 30}}}})
    runs = {"ldo": [("85 C", 85.0, {"p_u1": 0.17295})]}
    judged = thermal.judge(plan, runs, FACTS_LIST, ECSS)
    worst = judged["parts"]["U1"]["worst"]
    assert worst["figure"] == "theta_jc" and "from" not in worst
    assert worst["beside"] == {
        "figure": "theta_jc",
        "equation": "4",
        "from": 85.001,
        "junction": pytest.approx(105.47828),
    }
    assert judged["not_judged"] == []
    line = thermal.lines({"thermal": judged})[0]
    assert "from case" not in line and "the worst junction by SPRA953D, section 2.2, equation 5" in line
