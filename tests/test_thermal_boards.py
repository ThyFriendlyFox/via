"""What is left of roadmap item 7: the board a figure was measured on, a junction from a stated case,
board or top temperature, a deck's temperature block narrower than the file's, and the second reading
of the junction rules and the regulator's facts.

The numbers are read from these documents:
- TLV755P datasheet SBVS320D, section 5.4, page 5: the JEDEC rows of the DBV column, RthetaJA 231.1,
  RthetaJC(top) 118.4, RthetaJB 64.4, psiJT 28.4 and psiJB 63.8 C/W; footnote 2: "JEDEC thermal
  metrics apply to JEDEC standard PCB (2s2p, no vias to internal plane and bottom layer)". Section
  5.1, page 4: an operating junction of 150 C at the most.
- TI SPRA953D, table 3-1, note 11, page 9: JEDEC high-k (2s2p) and low-k (1s0p) boards as defined in
  JESD 51-7 and JESD 51-3. Section 1.2, page 3: a 2s2p board gives a best case, a 1s board a typical
  one. Section 2.2, equation 4, page 7: TJ = TC + RthetaJC x power gives a junction higher than
  reality. Section 3, equation 8, page 8: TJ = TC + psiJT x power. Section 4, figure 4-1, page 10.
  Section 5.1, equation 9, page 11: TJ = T(PCB) + psiJB x power; the board takes 75 % to 95 % of the
  heat.
- ECSS-Q-ST-30-11C Rev.2, clause 6.21.2, table 6-21, page 57: 110 C or Tjmax - 40 C, the lower.
"""

from __future__ import annotations

import datetime
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import engine

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
PACKS = ROOT / "rules" / "ratings"
FACTS = BOARDS / "library" / "facts"
sys.path.insert(0, str(ROOT / "tools"))
import clock  # noqa: E402
import ratings  # noqa: E402
import simcorners  # noqa: E402
import thermal  # noqa: E402

# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {
    "ti-sbvs320": "sections 5.1 and 5.4, footnote 2, pages 4 and 5",
    "ti-spra953d": "sections 1.1 to 5.1, equations 4, 8 and 9, table 3-1, pages 2 to 11",
    "ecss-q-st-30-11c-rev2": "clause 6.21.2, table 6-21, page 57",
    "nasa-eee-inst-002": "section M4, table 4, page 10 of 10; section S1, pages 12 and 13 of 13",
}

needs_ngspice = engine(pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice is not installed"))

ECSS = ratings.read_pack(PACKS / "ecss-q-st-30-11c-rev2.json")
NASA = ratings.read_pack(PACKS / "nasa-eee-inst-002.json")
FACTS_LIST = ratings.read_facts(FACTS)
TLV755 = "TLV755P datasheet, SBVS320D, November 2017, revised September 2024"
LIMIT = (
    "limit 110 C, the least of 110 C and 150 C - 40 C (ecss-q-st-30-11c-rev2, clause 6.21.2, table 6-21, "
    "page 57)"
)
SOURCE = {
    "document": "a datasheet made up for the tests",
    "revision": "A",
    "url": "https://example.com/part.pdf",
    "sha256": "0123456789abcdef" * 4,
    "read": "2026-11-17",
    "second_reader": "no",
}
MOSFET = {
    "kind": "transistor.mosfet",
    "mpn": "Q-1",
    "transistors": [{"gate": "1", "drain": "3", "source": "2"}],
    "volts_drain_source": 30,
    "volts_gate_source": 12,
    "source": SOURCE,
    "thermal": {"junction_max": 150, "theta_ja": 100, "page": 2},
}


def facts_with(term: dict) -> list:
    return [ratings._facts("q.json", {**MOSFET, "thermal": term})]


def refusal(term: object) -> str:
    with pytest.raises(ratings.Refusal) as caught:
        ratings._facts("part.json", {**MOSFET, "thermal": term})
    return str(caught.value)


def plan_of(tmp_path: Path, parts: dict) -> thermal.Plan:
    (tmp_path / "thermal.json").write_text(
        json.dumps({"pack": "ecss-q-st-30-11c-rev2", "parts": parts}), encoding="utf-8"
    )
    plan, problems = thermal.read_plan(tmp_path, ["ldo"])
    assert problems == []
    return plan


U1 = {"mpn": "TLV75533PDBVR", "watts": "ldo.p_u1", "source": "input power less output power"}

# ---------------------------------------------------------------- the board of each figure


def test_the_regulator_s_facts_name_the_jedec_board_of_its_5_figures_and_were_read_twice():
    """SBVS320D, section 5.4, footnote 2, page 5: the JEDEC rows apply to the 2s2p board."""
    entry = {f.name: f for f in FACTS_LIST}["TLV75533PDBVR"]
    assert entry.data["thermal"]["boards"] == {
        "theta_ja": "2s2p",
        "theta_jc": "2s2p",
        "theta_jb": "2s2p",
        "psi_jt": "2s2p",
        "psi_jb": "2s2p",
        "page": 5,
    }
    assert entry.data["source"]["second_reader"] == "2026-11-18" and entry.read_twice


def test_the_drv_regulator_s_facts_name_the_2s2p_board_of_its_5_figures():
    """SBVS320D, section 5.4, footnote 2, page 5: the JEDEC rows, the DRV column's among them, apply to
    the JEDEC standard 2s2p board. pass-block-ldo-2x's U1 is held on them."""
    entry = {f.name: f for f in FACTS_LIST}["TLV75533PDRVR"]
    assert entry.data["thermal"]["boards"] == {
        "theta_ja": "2s2p",
        "theta_jc": "2s2p",
        "theta_jb": "2s2p",
        "psi_jt": "2s2p",
        "psi_jb": "2s2p",
        "page": 5,
    }


def test_the_2_boards_are_those_spra953d_names_after_jesd51():
    """SPRA953D, table 3-1, note 11, page 9: high-k (2s2p) in JESD 51-7, low-k (1s0p) in JESD 51-3."""
    assert ratings.BOARDS == {
        "1s0p": "the low-k 1s0p board of JESD 51-3",
        "2s2p": "the high-k 2s2p board of JESD 51-7",
    }


BASE = {"junction_max": 150, "theta_ja": 100, "page": 2}


@pytest.mark.parametrize(
    ("boards", "message"),
    [
        ({"theta_ja": "2s2p"}, "part.json: thermal: boards: `page` is missing"),
        (["2s2p"], "part.json: thermal: boards: an object is asked"),
        ({"page": 3}, "part.json: thermal: boards: 1 figure at least is asked"),
        (
            {"theta_ja": "2s", "page": 3},
            "part.json: thermal: boards: theta_ja: `2s` is no JEDEC board the workcenter knows; they are "
            "1s0p, 2s2p",
        ),
        (
            {"theta_ja": "2s2p", "psi_jb": "2s2p", "page": 3},
            "part.json: thermal: boards: psi_jb: the facts give no psi_jb",
        ),
        ({"theta_ja": "2s2p", "page": 0}, "part.json: thermal: boards: page: a page number is asked"),
        ({"rja": "2s2p", "page": 3}, "part.json: thermal: boards: `rja` is no key here"),
        (
            {"theta_ja": ["2s2p"], "page": 3},
            "part.json: thermal: boards: theta_ja: `['2s2p']` is no JEDEC board the workcenter knows",
        ),
        (
            {"theta_ja": {"a": 1}, "page": 3},
            "part.json: thermal: boards: theta_ja: `{'a': 1}` is no JEDEC board the workcenter knows",
        ),
    ],
)
def test_a_boards_key_wrong_in_1_place_is_refused_with_the_place(boards, message):
    term = ratings._facts(
        "part.json", {**MOSFET, "thermal": {**BASE, "boards": {"theta_ja": "1s0p", "page": 3}}}
    )
    assert term.data["thermal"]["boards"]["theta_ja"] == "1s0p"
    assert refusal({**BASE, "boards": boards}).startswith(message)


def runs_at(*rows: tuple[str, float, float]) -> dict:
    return {"ldo": [(label, ambient, {"p_u1": watts}) for label, ambient, watts in rows]}


def test_a_failure_and_the_assumption_name_the_board_of_the_figure(tmp_path):
    """At 85 C and 0.17296 W: 85 + 231.1 x 0.17296 = 85 + 39.971 = 124.97 C, over ECSS's 110 C. The
    figure stands on the 2s2p board of JESD 51-7, page 5 of SBVS320D."""
    plan = plan_of(tmp_path, {"U1": U1})
    judged = thermal.judge(
        plan, runs_at(("as written", 25.0, 0.1702), ("85 C", 85.0, 0.17296)), FACTS_LIST, ECSS
    )
    assert judged["failures"] == [
        "thermal: U1 (TLV75533PDBVR) at 85 C ambient: junction 124.97 C, over 110 C (85 C): 85 C + 231.1 C/W "
        f"x 0.17296 W of ldo.p_u1, theta_ja and junction_max of {TLV755}, p 4 and 5, theta_ja on the high-k "
        f"2s2p board of JESD 51-7 (p 5); {LIMIT}"
    ]
    assert judged["parts"]["U1"]["assumes"] == (
        "theta_ja 231.1 C/W was measured on the high-k 2s2p board of JESD 51-7 (p 5): a 2s2p board gives a "
        "best case and a 1s0p board a typical one (SPRA953D, section 1.2, page 3); a board unlike the test "
        "board changes it (section 1.1, page 2)"
    )


def test_a_figure_whose_board_the_facts_do_not_name_holds_no_part_and_still_fails_one_over(tmp_path):
    """Q-1, a MOSFET, theta_ja 100 C/W, Tjmax 150 C: ECSS's limit (clause 6.29.2, table 6-36, page 76)
    is the lower of 110 C and 150 - 40 = 110 C. At 25 C and 0.5 W: 25 + 100 x 0.5 = 75 C, inside, yet
    not held: no board is named. At 0.9 W: 25 + 90 = 115 C, over: it fails."""
    plan = plan_of(tmp_path, {"Q1": {"mpn": "Q-1", "watts": "ldo.p_u1", "source": "s"}})
    judged = thermal.judge(plan, runs_at(("as written", 25.0, 0.5)), facts_with(BASE), ECSS)
    assert judged["failures"] == []
    assert judged["not_judged"] == [
        "thermal: Q1 (Q-1) not held: its facts (q.json) name no JEDEC board for theta_ja: write `boards` in "
        "`thermal` from the datasheet's thermal table"
    ]
    part = judged["parts"]["Q1"]
    assert part["held"] is None and part["worst"]["junction"] == 75
    assert part["assumes"].startswith("theta_ja 100 C/W: its facts name no JEDEC board it was measured on")
    judged = thermal.judge(plan, runs_at(("as written", 25.0, 0.9)), facts_with(BASE), ECSS)
    assert judged["failures"][0].endswith(
        "theta_ja on no board its facts name; limit 110 C, the least of 110 C and 150 C - 40 C "
        "(ecss-q-st-30-11c-rev2, clause 6.29.2, table 6-36, page 76)"
    )
    assert judged["parts"]["Q1"]["held"] is False


# ---------------------------------------------------------------- a stated case, board or top temperature


def test_a_plan_s_stated_temperature_is_read(tmp_path):
    stated = {
        "figure": "psi_jb",
        "celsius": {"60": 100, "-20": -5.5},
        "source": "a board temperature for the test",
    }
    plan = plan_of(tmp_path, {"U1": {**U1, "from": stated}})
    assert plan.parts["U1"].stated == thermal.Stated(
        "psi_jb", {60.0: 100.0, -20.0: -5.5}, "a board temperature for the test"
    )
    assert plan_of(tmp_path, {"U1": U1}).parts["U1"].stated is None


@pytest.mark.parametrize(
    ("stated", "problem"),
    [
        ({"figure": "psi_jb", "celsius": {"60": 100}}, "thermal.json: parts: U1: from: `source` is missing"),
        (
            {"figure": "theta_ja", "celsius": {"60": 100}, "source": "s"},
            "thermal.json: parts: U1: from: figure: `theta_ja` is no figure from a stated temperature; they "
            "are theta_jc, theta_jb, psi_jt, psi_jb",
        ),
        (
            {"figure": "psi_jb", "celsius": {}, "source": "s"},
            'thermal.json: parts: U1: from: celsius: 1 ambient at least is asked, as {"85": 101.5}',
        ),
        (
            {"figure": "psi_jb", "celsius": {"hot": 100}, "source": "s"},
            "thermal.json: parts: U1: from: celsius: `hot` is no ambient in C",
        ),
        (
            {"figure": "psi_jb", "celsius": {"60": "100"}, "source": "s"},
            "thermal.json: parts: U1: from: celsius: 60: '100' is no number",
        ),
        ("psi_jb", "thermal.json: parts: U1: from: an object is asked"),
        (
            {"figure": "psi_jb", "celsius": {"85": 90, "85.0": 20}, "source": "s"},
            "thermal.json: parts: U1: from: celsius: `85` and `85.0` are the same ambient: state it once",
        ),
        (
            {"figure": "psi_jb", "celsius": {"85": 90, "85.005": 20}, "source": "s"},
            "thermal.json: parts: U1: from: celsius: `85` and `85.005` are the same ambient: state it once",
        ),
    ],
)
def test_a_stated_temperature_wrong_in_1_place_is_refused_with_the_place(tmp_path, stated, problem):
    (tmp_path / "thermal.json").write_text(
        json.dumps({"pack": "p", "parts": {"U1": {**U1, "from": stated}}}), encoding="utf-8"
    )
    plan, problems = thermal.read_plan(tmp_path, ["ldo"])
    assert plan is None and len(problems) == 1 and problems[0].startswith(problem), problems


BOARD_AT_60 = {
    "figure": "psi_jb",
    "celsius": {"60": 100},
    "source": "a board temperature made up for the test",
}


def test_a_stated_board_temperature_gives_the_junction_with_the_sum_and_its_source_on_the_line(tmp_path):
    """At 60 C the board stands at 100 C as stated: 100 + 63.8 x 0.17252 = 100 + 11.007 = 111.01 C,
    over 110 C, where theta_ja would give 60 + 231.1 x 0.17252 = 99.87 C. As written, 25 C, no board
    temperature is stated, so theta_ja gives 25 + 231.1 x 0.1702 = 64.333 C."""
    plan = plan_of(tmp_path, {"U1": {**U1, "from": BOARD_AT_60}})
    runs = runs_at(("as written", 25.0, 0.1702), ("60 C", 60.0, 0.17252))
    judged = thermal.judge(plan, runs, FACTS_LIST, ECSS)
    assert judged["failures"] == [
        "thermal: U1 (TLV75533PDBVR) at 60 C ambient: junction 111.01 C, over 110 C (60 C): board 100 C at "
        "60 C ambient (a board temperature made up for the test) + 63.8 C/W x 0.17252 W of ldo.p_u1, psi_jb "
        f"and junction_max of {TLV755}, p 4 and 5, psi_jb on the high-k 2s2p board of JESD 51-7 (p 5); "
        f"{LIMIT}"
    ]
    part = judged["parts"]["U1"]
    assert part["written"]["figure"] == "theta_ja"
    assert part["written"]["junction"] == pytest.approx(64.33322)
    assert part["worst"] == {
        "run": "60 C",
        "ambient": 60.0,
        "watts": 0.17252,
        "figure": "psi_jb",
        "from": 100.0,
        "junction": pytest.approx(111.006776),
    }
    assert part["assumes"].endswith(
        "psi_jb 63.8 C/W was measured on the high-k 2s2p board of JESD 51-7 (p 5): TJ = T(PCB) + psi_jb x "
        "power (SPRA953D, section 5.1, equation 9, page 11)"
    )


def test_a_stated_temperature_at_an_ambient_no_run_stands_at_is_named(tmp_path):
    """No run stands at 70 C, so the stated 100 C is used nowhere: theta_ja judges both runs, 25 +
    231.1 x 0.1702 = 64.333 C and 60 + 231.1 x 0.17252 = 99.869 C, inside 110 C."""
    stated = {**BOARD_AT_60, "celsius": {"70": 100}}
    plan = plan_of(tmp_path, {"U1": {**U1, "from": stated}})
    runs = runs_at(("as written", 25.0, 0.1702), ("60 C", 60.0, 0.17252))
    judged = thermal.judge(plan, runs, FACTS_LIST, ECSS)
    assert judged["not_judged"] == [
        "thermal: U1 (TLV75533PDBVR): sim/thermal.json states its board temperature at 70 C ambient, where "
        "no run of ldo stands"
    ]
    assert judged["parts"]["U1"]["worst"]["junction"] == pytest.approx(99.869, abs=0.001)


def test_a_stated_temperature_is_taken_only_within_0_01_c_of_the_run_s_ambient(tmp_path):
    """simcorners.TEMP_MATCH is 0.01 C. A run at 60.5 C does not stand at the stated 60 C: theta_ja
    judges it, 60.5 + 231.1 x 0.17252 = 60.5 + 39.869 = 100.369 C, inside 110 C, and the stated board
    is named as used nowhere. A run at 60.005 C does: 100 + 63.8 x 0.17252 = 111.007 C, over 110 C."""
    plan = plan_of(tmp_path, {"U1": {**U1, "from": BOARD_AT_60}})
    judged = thermal.judge(plan, runs_at(("60.5 C", 60.5, 0.17252)), FACTS_LIST, ECSS)
    assert judged["failures"] == []
    assert judged["not_judged"] == [
        "thermal: U1 (TLV75533PDBVR): sim/thermal.json states its board temperature at 60 C ambient, where "
        "no run of ldo stands"
    ]
    worst = judged["parts"]["U1"]["worst"]
    assert worst["figure"] == "theta_ja" and worst["junction"] == pytest.approx(100.369372)
    judged = thermal.judge(plan, runs_at(("60 C", 60.005, 0.17252)), FACTS_LIST, ECSS)
    worst = judged["parts"]["U1"]["worst"]
    assert worst["figure"] == "psi_jb" and worst["junction"] == pytest.approx(111.006776)
    assert judged["not_judged"] == [] and len(judged["failures"]) == 1


BELOW = (
    "a part's heat flows from its junction through its case and board to the air (SPRA953D, section 4, "
    "figure 4-1, page 10), so it is set aside"
)


def test_a_stated_board_under_its_run_s_ambient_is_set_aside_and_theta_ja_judges_the_run(tmp_path):
    """fail-sim-thermal with a board stated at 20 C at 85 C ambient: 20 + 63.8 x 0.17296 = 31.03 C
    would hold the part. The board is set aside, and theta_ja gives 85 + 231.1 x 0.17296 = 124.97 C,
    over 110 C, as with nothing stated."""
    cold = {"figure": "psi_jb", "celsius": {"85": 20}, "source": "a board under the air"}
    plan = plan_of(tmp_path, {"U1": {**U1, "from": cold}})
    judged = thermal.judge(
        plan, runs_at(("as written", 25.0, 0.1702), ("85 C", 85.0, 0.17296)), FACTS_LIST, ECSS
    )
    assert judged["failures"] == [
        "thermal: U1 (TLV75533PDBVR) at 85 C ambient: junction 124.97 C, over 110 C (85 C): 85 C + 231.1 C/W "
        f"x 0.17296 W of ldo.p_u1, theta_ja and junction_max of {TLV755}, p 4 and 5, theta_ja on the high-k "
        f"2s2p board of JESD 51-7 (p 5); {LIMIT}"
    ]
    assert judged["not_judged"] == [
        "thermal: U1 (TLV75533PDBVR) not judged from its stated board temperature: sim/thermal.json states "
        f"20 C at 85 C ambient, not above the air; {BELOW}"
    ]
    assert judged["parts"]["U1"]["held"] is False


def test_a_part_with_a_stated_temperature_set_aside_is_never_held(tmp_path):
    """A board stated at 50 C at 60 C ambient is set aside; theta_ja gives 60 + 231.1 x 0.1 = 83.11 C,
    inside 110 C, and the part is still not held."""
    cold = {"figure": "psi_jb", "celsius": {"60": 50}, "source": "s"}
    plan = plan_of(tmp_path, {"U1": {**U1, "from": cold}})
    judged = thermal.judge(plan, runs_at(("60 C", 60.0, 0.1)), FACTS_LIST, ECSS)
    assert judged["failures"] == []
    assert judged["not_judged"] == [
        "thermal: U1 (TLV75533PDBVR) not judged from its stated board temperature: sim/thermal.json states "
        f"50 C at 60 C ambient, not above the air; {BELOW}"
    ]
    part = judged["parts"]["U1"]
    assert part["held"] is None and part["worst"]["figure"] == "theta_ja"
    assert part["worst"]["junction"] == pytest.approx(83.11)


def test_a_stated_board_at_its_run_s_ambient_is_set_aside_as_one_under_it(tmp_path):
    """A part that dissipates heats its board above the air (SPRA953D, section 4, figure 4-1, page 10),
    so a board stated at 85 C at 85 C ambient is set aside as well: theta_ja gives 85 + 231.1 x 0.17296
    = 124.97 C, over 110 C. Taken, the board would give 85 + 63.8 x 0.17296 = 96.03 C and hold it."""
    even = {"figure": "psi_jb", "celsius": {"85": 85}, "source": "measured"}
    plan = plan_of(tmp_path, {"U1": {**U1, "from": even}})
    judged = thermal.judge(plan, runs_at(("85 C", 85.0, 0.17296)), FACTS_LIST, ECSS)
    assert len(judged["failures"]) == 1
    assert judged["failures"][0].startswith(
        "thermal: U1 (TLV75533PDBVR) at 85 C ambient: junction 124.97 C, over 110 C (85 C): 85 C + 231.1 C/W"
    )
    assert judged["not_judged"] == [
        "thermal: U1 (TLV75533PDBVR) not judged from its stated board temperature: sim/thermal.json states "
        f"85 C at 85 C ambient, not above the air; {BELOW}"
    ]
    assert judged["parts"]["U1"]["held"] is False


def test_a_stated_junction_under_the_one_theta_ja_gives_on_the_2s2p_board_holds_no_part(tmp_path):
    """SPRA953D, section 1.2, page 3: a 2s2p board gives a best case. A board stated at 85.001 C at 85 C
    ambient gives 85.001 + 63.8 x 0.17296 = 96.036 C, inside 110 C, under the 85 + 231.1 x 0.17296 =
    124.97 C theta_ja gives on the 2s2p board of JESD 51-7: the junction is judged from the board, and
    the part is not held."""
    above = {"figure": "psi_jb", "celsius": {"85": 85.001}, "source": "measured"}
    plan = plan_of(tmp_path, {"U1": {**U1, "from": above}})
    judged = thermal.judge(plan, runs_at(("85 C", 85.0, 0.17296)), FACTS_LIST, ECSS)
    assert judged["failures"] == []
    assert judged["not_judged"] == [
        "thermal: U1 (TLV75533PDBVR) not held at 85 C: its stated board 85.001 C gives a junction of "
        "96.036 C, under the 124.97 C theta_ja gives on the high-k 2s2p board of JESD 51-7, which "
        "SPRA953D calls a best case (section 1.2, page 3)"
    ]
    part = judged["parts"]["U1"]
    assert part["held"] is None and part["worst"]["junction"] == pytest.approx(96.035848)


# theta_ja 231.1 on the low-k 1s0p board, psi_jb 63.8 and psi_jt 28.4 on the 2s2p board: the TLV755P's
# figures (SBVS320D, section 5.4, page 5) with theta_ja's board changed, as in the reviewer's variants.
ONE_S = {
    "junction_max": 150,
    "theta_ja": 231.1,
    "psi_jb": 63.8,
    "psi_jt": 28.4,
    "page": 5,
    "boards": {"theta_ja": "1s0p", "psi_jb": "2s2p", "psi_jt": "2s2p", "page": 5},
}
NO_JA = {
    **{k: v for k, v in ONE_S.items() if k != "theta_ja"},
    "boards": {"psi_jb": "2s2p", "psi_jt": "2s2p", "page": 5},
}
JA_NO_BOARD = {**ONE_S, "boards": {"psi_jb": "2s2p", "psi_jt": "2s2p", "page": 5}}
EPSILON = {"figure": "psi_jb", "celsius": {"-20": -19.999, "25": 25.001, "85": 85.001}, "source": "measured"}
EPS_RUNS = (("as written", 25.0, 0.1702), ("-20 C", -20.0, 0.17), ("85 C", 85.0, 0.17295))
UNCHECKED = (
    "thermal: Q1 (Q-1) not held as written (and 2 more runs): its stated board 25.001 C, which gives a "
    "junction of 35.86 C, was checked against no board: {why}, and only theta_ja on the high-k 2s2p board "
    "of JESD 51-7, which SPRA953D calls a best case (section 1.2, page 3), bounds a stated temperature"
)


@pytest.mark.parametrize(
    ("term", "why"),
    [
        (
            ONE_S,
            "its facts give theta_ja on the low-k 1s0p board of JESD 51-3, which SPRA953D calls a typical "
            "case",
        ),
        (NO_JA, "its facts give no theta_ja"),
        (JA_NO_BOARD, "its facts name no JEDEC board for theta_ja"),
    ],
)
def test_a_stated_temperature_no_2s2p_theta_ja_bounds_holds_no_part(tmp_path, term, why):
    """A board 0.001 C above the air at each ambient. At 85 C and 0.17295 W, psi_jb gives 85.001 + 63.8
    x 0.17295 = 96.035 C, inside 110 C, where theta_ja gives 85 + 231.1 x 0.17295 = 124.97 C, over it.
    Only theta_ja on the 2s2p board, a best case (SPRA953D, section 1.2, page 3), bounds the statement;
    with none the stated board is judged by nothing, and the part is not held. As written: 25.001 + 63.8
    x 0.1702 = 35.86 C."""
    plan = plan_of(tmp_path, {"Q1": {"mpn": "Q-1", "watts": "ldo.p_u1", "source": "s", "from": EPSILON}})
    judged = thermal.judge(plan, runs_at(*EPS_RUNS), facts_with(term), ECSS)
    assert judged["failures"] == []
    assert judged["not_judged"] == [UNCHECKED.format(why=why)]
    part = judged["parts"]["Q1"]
    assert part["held"] is None and part["worst"]["junction"] == pytest.approx(96.03521)


def test_a_stated_temperature_names_the_junction_theta_ja_gives_there_and_its_board(tmp_path):
    """Where a stated board judged every run, theta_ja's junction is still on the record: at 85 C and
    0.17295 W, 85 + 231.1 x 0.17295 = 124.97 C on the 1s0p board, over the 110 C the board's 96.035 C is
    under. With no theta_ja in the facts there is none."""
    plan = plan_of(tmp_path, {"Q1": {"mpn": "Q-1", "watts": "ldo.p_u1", "source": "s", "from": EPSILON}})
    part = thermal.judge(plan, runs_at(*EPS_RUNS), facts_with(ONE_S), ECSS)["parts"]["Q1"]
    assert part["theta_ja_gives"] == {
        "run": "85 C",
        "ambient": 85.0,
        "junction": pytest.approx(124.968745),
        "theta_ja": 231.1,
        "board": "1s0p",
    }
    part = thermal.judge(plan, runs_at(*EPS_RUNS), facts_with(NO_JA), ECSS)["parts"]["Q1"]
    assert "theta_ja_gives" not in part


HEAT_SINK = "an aluminium heat sink on the case, made up for the test"
SUNK = {"figure": "theta_jc", "celsius": {"25": 27, "85": 87}, "source": "a thermocouple through the sink"}


def test_a_case_stated_on_a_heat_sink_is_not_bound_by_the_2s2p_board(tmp_path):
    """RthetaJC was devised for a case on a heat sink (SPRA953D, section 2, page 6; section 2.2, equation
    5, page 7). theta_jc 118.4 C/W: as written 27 + 118.4 x 0.1702 = 47.152 C, under the 25 + 231.1 x
    0.1702 = 64.333 C theta_ja gives on the 2s2p board; at 85 C 87 + 118.4 x 0.17295 = 107.48 C, inside
    110 C. Stated on a heat sink, the part is held; without it, the best case holds it not."""
    plan = plan_of(tmp_path, {"U1": {**U1, "from": {**SUNK, "heat_sink": HEAT_SINK}}})
    runs = runs_at(("as written", 25.0, 0.1702), ("85 C", 85.0, 0.17295))
    judged = thermal.judge(plan, runs, FACTS_LIST, ECSS)
    assert judged["failures"] == [] and judged["not_judged"] == []
    part = judged["parts"]["U1"]
    assert part["held"] is True and part["worst"]["junction"] == pytest.approx(107.47728)
    assert part["stated"]["heat_sink"] == HEAT_SINK
    plan = plan_of(tmp_path, {"U1": {**U1, "from": SUNK}})
    judged = thermal.judge(plan, runs, FACTS_LIST, ECSS)
    assert judged["parts"]["U1"]["held"] is None
    assert judged["not_judged"][0].startswith(
        "thermal: U1 (TLV75533PDBVR) not held as written (and 1 more run): its stated case 27 C gives a "
        "junction of 47.152 C, under the 64.333 C theta_ja gives"
    )


@pytest.mark.parametrize("figure", ["psi_jb", "psi_jt", "theta_jb"])
def test_a_heat_sink_is_stated_with_theta_jc_only(tmp_path, figure):
    """SPRA953D, section 3.2, page 10: psi_jt should not be used when a heat sink is applied."""
    (tmp_path / "thermal.json").write_text(
        json.dumps(
            {"pack": "p", "parts": {"U1": {**U1, "from": {**SUNK, "figure": figure, "heat_sink": HEAT_SINK}}}}
        ),
        encoding="utf-8",
    )
    plan, problems = thermal.read_plan(tmp_path, ["ldo"])
    assert plan is None
    assert problems == [
        "thermal.json: parts: U1: from: heat_sink: a heat sink is stated with theta_jc only: RthetaJC was "
        "devised for a case on a heat sink (SPRA953D, section 2, page 6; section 2.2, equation 5, page 7), "
        f"and psi_jt should not be used with one (section 3.2, page 10); `from` names {figure}"
    ]


def test_a_junction_from_theta_jb_holds_no_part(tmp_path):
    """SPRA953D, section 4, page 10: RthetaJB is useful for a first-pass estimation, and no bound is
    given. A board at 90 C at 60 C ambient, 0.1 W: 90 + 64.4 x 0.1 = 96.44 C, inside 110 C and above the
    60 + 231.1 x 0.1 = 83.11 C of theta_ja; the part is still not held."""
    board = {"figure": "theta_jb", "celsius": {"60": 90}, "source": "measured"}
    plan = plan_of(tmp_path, {"U1": {**U1, "from": board}})
    judged = thermal.judge(plan, runs_at(("60 C", 60.0, 0.1)), FACTS_LIST, ECSS)
    assert judged["failures"] == []
    assert judged["not_judged"] == [
        "thermal: U1 (TLV75533PDBVR) not held at 60 C: its junction there comes from theta_jb, which "
        "SPRA953D calls useful for a first-pass estimation only and gives no bound on (section 4, page "
        "10); psi_jb gives the junction from the board's temperature (section 5.1, equation 9, page 11)"
    ]
    part = judged["parts"]["U1"]
    assert part["held"] is None and part["worst"]["junction"] == pytest.approx(96.44)


def test_a_part_judged_from_a_stated_temperature_names_it_and_its_source(tmp_path):
    """A board at 90 C at 60 C ambient, 0.1 W: 90 + 63.8 x 0.1 = 96.38 C on psi_jb, above the 83.11 C of
    theta_ja, inside 110 C: held, and the record names the stated board and where it comes from."""
    board = {"figure": "psi_jb", "celsius": {"60": 90}, "source": "a thermocouple under U1"}
    plan = plan_of(tmp_path, {"U1": {**U1, "from": board}})
    part = thermal.judge(plan, runs_at(("60 C", 60.0, 0.1)), FACTS_LIST, ECSS)["parts"]["U1"]
    assert part["held"] is True and part["worst"]["from"] == 90
    assert part["stated"] == {"figure": "psi_jb", "temperature": "board", "source": "a thermocouple under U1"}
    plan = plan_of(tmp_path, {"U1": U1})
    assert "stated" not in thermal.judge(plan, runs_at(("60 C", 60.0, 0.1)), FACTS_LIST, ECSS)["parts"]["U1"]


def test_theta_jb_claims_no_bound_spra953d_does_not_give():
    """SPRA953D, section 4, page 10: RthetaJB is 'useful for a first-pass estimation', from a board
    taken as 1 uniform node, 'which is erroneous'; no bound is given. SBVS320D, section 5.4, page 5:
    RthetaJB 64.4 C/W on the 2s2p board."""
    term = {f.name: f for f in FACTS_LIST}["TLV75533PDBVR"].data["thermal"]
    assert thermal.assumes("theta_jb", term) == (
        "theta_jb 64.4 C/W was measured on the high-k 2s2p board of JESD 51-7 (p 5): TJ = TB + theta_jb x "
        "power; SPRA953D calls theta_jb useful for a first-pass estimation only, as it takes the board "
        "under the part as 1 uniform temperature, which is erroneous, and gives no bound on the junction "
        "it gives (section 4, page 10); psi_jb gives the junction from the board's temperature (section "
        "5.1, equation 9, page 11)"
    )


def test_a_stated_case_temperature_says_its_junction_is_high(tmp_path):
    """theta_jc 118.4 C/W, a case at 90 C at 60 C ambient and 0.1 W: 90 + 11.84 = 101.84 C, inside 110 C."""
    case = {"figure": "theta_jc", "celsius": {"60": 90}, "source": "a thermocouple on the case"}
    plan = plan_of(tmp_path, {"U1": {**U1, "from": case}})
    part = thermal.judge(plan, runs_at(("60 C", 60.0, 0.1)), FACTS_LIST, ECSS)["parts"]["U1"]
    assert part["worst"]["junction"] == pytest.approx(101.84)
    assert part["held"] is True
    assert part["assumes"] == (
        "theta_jc 118.4 C/W was measured on the high-k 2s2p board of JESD 51-7 (p 5): TJ = TC + theta_jc x "
        "power puts all of the power through the case, so the junction it gives is above the real one in a "
        "plastic package (SPRA953D, section 2.2, equation 4, page 7; ECSS-Q-ST-30-11C Rev.2, clause 3.2, "
        "page 12)"
    )


def test_a_part_with_no_theta_ja_is_judged_only_where_its_temperature_is_stated(tmp_path):
    """Q-1 gives psi_jb 5 C/W on a 2s2p board. At 85 C the board stands at 90 C: 90 + 5 x 0.5 = 92.5 C,
    inside 110 C. As written, at 25 C, nothing is stated and the facts give no theta_ja."""
    term = {"junction_max": 150, "psi_jb": 5, "page": 2, "boards": {"psi_jb": "2s2p", "page": 2}}
    stated = {"figure": "psi_jb", "celsius": {"85": 90}, "source": "s"}
    plan = plan_of(tmp_path, {"Q1": {"mpn": "Q-1", "watts": "ldo.p_u1", "source": "s", "from": stated}})
    judged = thermal.judge(
        plan, runs_at(("as written", 25.0, 0.5), ("85 C", 85.0, 0.5)), facts_with(term), ECSS
    )
    assert judged["failures"] == []
    assert judged["not_judged"] == [
        "thermal: Q1 (Q-1) not judged as written: sim/thermal.json states its board temperature at 85 C "
        "ambient only, and its facts give no theta_ja",
        "thermal: Q1 (Q-1) not held at 85 C: its stated board 90 C, which gives a junction of 92.5 C, was "
        "checked against no board: its facts give no theta_ja, and only theta_ja on the high-k 2s2p board of "
        "JESD 51-7, which SPRA953D calls a best case (section 1.2, page 3), bounds a stated temperature",
    ]
    part = judged["parts"]["Q1"]
    assert (part["runs"], part["held"], part["worst"]["junction"]) == (1, None, 92.5)


def test_a_stated_figure_the_facts_do_not_give_sets_the_statement_aside_and_theta_ja_judges(tmp_path):
    """Q-1 gives theta_ja 100 C/W on a 2s2p board and no psi_jb. `from` names psi_jb: the statement is
    set aside and theta_ja judges every run: at 60 C and 0.6 W, 60 + 100 x 0.6 = 120 C, over 110 C."""
    term = {**BASE, "boards": {"theta_ja": "2s2p", "page": 2}}
    plan = plan_of(tmp_path, {"Q1": {"mpn": "Q-1", "watts": "ldo.p_u1", "source": "s", "from": BOARD_AT_60}})
    judged = thermal.judge(plan, runs_at(("60 C", 60.0, 0.6)), facts_with(term), ECSS)
    assert len(judged["failures"]) == 1
    assert judged["failures"][0].startswith(
        "thermal: Q1 (Q-1) at 60 C ambient: junction 120 C, over 110 C (60 C): 60 C + 100 C/W x 0.6 W"
    )
    assert judged["not_judged"] == [
        "thermal: Q1 (Q-1) not judged from its stated board temperature: sim/thermal.json names psi_jb in "
        "`from`, and its facts (q.json) give no psi_jb; theta_ja judges its runs"
    ]
    assert judged["parts"]["Q1"]["held"] is False
    judged = thermal.judge(plan, runs_at(("60 C", 60.0, 0.1)), facts_with(term), ECSS)
    assert judged["failures"] == [] and judged["parts"]["Q1"]["held"] is None


def test_a_stated_figure_the_facts_do_not_give_and_no_theta_ja_leaves_the_part_not_judged(tmp_path):
    term = {"junction_max": 150, "theta_jc": 20, "page": 2, "boards": {"theta_jc": "2s2p", "page": 2}}
    plan = plan_of(tmp_path, {"Q1": {"mpn": "Q-1", "watts": "ldo.p_u1", "source": "s", "from": BOARD_AT_60}})
    judged = thermal.judge(plan, runs_at(("60 C", 60.0, 0.1)), facts_with(term), ECSS)
    assert judged["parts"] == {} and judged["failures"] == []
    assert judged["not_judged"] == [
        "thermal: Q1 (Q-1) not judged: sim/thermal.json names psi_jb in `from`, and its facts (q.json) give "
        "no psi_jb"
    ]


def test_a_part_with_no_theta_ja_and_no_stated_temperature_says_what_to_state(tmp_path):
    term = {"junction_max": 150, "psi_jt": 5, "theta_jc": 20, "page": 2}
    plan = plan_of(tmp_path, {"Q1": {"mpn": "Q-1", "watts": "ldo.p_u1", "source": "s"}})
    judged = thermal.judge(plan, runs_at(("as written", 25.0, 0.5)), facts_with(term), ECSS)
    assert judged["not_judged"] == [
        "thermal: Q1 (Q-1) not judged: its facts give theta_jc and psi_jt, and no theta_ja: theta_jc gives "
        "the junction from the case's temperature (ECSS-Q-ST-30-11C Rev.2, clause 3.2, page 12; SPRA953D, "
        "section 2), and psi_jt from the package top's temperature (SPRA953D, section 3); state either in "
        "sim/thermal.json's `from`, with its source"
    ]


# ---------------------------------------------------------------- the readings


def test_the_10_junction_rules_of_the_2_packs_were_read_a_second_time():
    """Each limit compared with its page: ECSS tables 6-13 (page 43), 6-14 (44), 6-19 (52), 6-21 (57) and
    6-36 (76); NASA section M4 table 4 (page 10 of 10) and section S1 tables 4 (pages 12 and 13 of 13)."""
    rules = ECSS.junction + NASA.junction
    assert len(rules) == 10
    assert {r.second_reader for r in rules} == {"2026-11-18"}


def test_a_junction_rule_takes_its_own_reading_or_its_document_s(tmp_path):
    card = json.loads((PACKS / "ecss-q-st-30-11c-rev2.json").read_text(encoding="utf-8"))
    rule = {
        "id": "j",
        "stress": "junction.temperature",
        "kinds": ["ic"],
        "celsius": 110,
        "where": "t 1, page 1",
    }
    card["rules"] = [r for r in card["rules"] if r["stress"] != "junction.temperature"] + [rule]
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(card), encoding="utf-8")
    assert ratings.read_pack(path).junction[0].second_reader == "2026-11-17"
    card["rules"][-1] = {**rule, "second_reader": "no"}
    path.write_text(json.dumps(card), encoding="utf-8")
    assert ratings.read_pack(path).junction[0].second_reader == "no"
    card["rules"][-1] = {**rule, "second_reader": "yes"}
    path.write_text(json.dumps(card), encoding="utf-8")
    with pytest.raises(ratings.Refusal) as caught:
        ratings.read_pack(path)
    # The junction rule is the pack's last: its number is the count of the pack's rules.
    assert str(caught.value).startswith(
        f"pack.json: rule {len(card['rules'])}: second_reader: write `no`, or the date"
    )


def test_a_reading_dated_after_today_is_refused(tmp_path):
    """No one has read a document on a day still to come: a rule's or a facts entry's second reading, or
    its first, dated after today counts as no reading and is refused with its place."""
    card = json.loads((PACKS / "ecss-q-st-30-11c-rev2.json").read_text(encoding="utf-8"))
    junction = next(r for r in card["rules"] if r["stress"] == "junction.temperature")
    junction["second_reader"] = "2099-01-01"
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(card), encoding="utf-8")
    with pytest.raises(ratings.Refusal) as caught:
        ratings.read_pack(path)
    assert "second_reader: 2099-01-01 is after today" in str(caught.value)
    for key in ("second_reader", "read"):
        with pytest.raises(ratings.Refusal) as caught:
            ratings._facts("part.json", {**MOSFET, "source": {**SOURCE, key: "2099-01-01"}})
        assert f"{key}: 2099-01-01 is after today" in str(caught.value)


def at_wall(monkeypatch, moment: str) -> None:
    """Pin the machine's clock, the 1 place a tool reads it (tools/clock.py `_wall`), to an aware moment."""
    monkeypatch.setattr(clock, "_wall", lambda: datetime.datetime.fromisoformat(moment))


def test_a_reading_is_judged_on_the_clock_module_s_day_and_a_day_ahead_for_time_zones(monkeypatch, tmp_path):
    """A reader writes the day of their own zone, up to 1 day ahead of UTC (UTC+14), so a date is
    refused only after the machine's day in UTC plus 1. 2027-03-01 20:00 at UTC-8 is 2027-03-02 04:00
    UTC: 2027-03-03 is accepted, 2027-03-04 refused."""
    card = json.loads((PACKS / "ecss-q-st-30-11c-rev2.json").read_text(encoding="utf-8"))
    junction = next(r for r in card["rules"] if r["stress"] == "junction.temperature")
    path = tmp_path / "pack.json"
    at_wall(monkeypatch, "2027-03-01T20:00:00-08:00")
    junction["second_reader"] = "2027-03-03"
    path.write_text(json.dumps(card), encoding="utf-8")
    ratings.read_pack(path)
    junction["second_reader"] = "2027-03-04"
    path.write_text(json.dumps(card), encoding="utf-8")
    with pytest.raises(ratings.Refusal) as caught:
        ratings.read_pack(path)
    assert "second_reader: 2027-03-04 is after today" in str(caught.value)


def test_the_shipped_readings_stand_on_a_machine_still_on_the_day_before(monkeypatch):
    """The 2 packs' junction rules and the TLV755P facts carry 2026-11-18. A machine at UTC-8 whose day
    is still 2026-11-17 reads them, and so does one at UTC whose day is 2026-11-17."""
    for moment in ("2026-11-17T20:00:00-08:00", "2026-11-17T01:00:00+00:00"):
        at_wall(monkeypatch, moment)
        for name in ("ecss-q-st-30-11c-rev2.json", "nasa-eee-inst-002.json"):
            ratings.read_pack(PACKS / name)
        ratings.read_facts(FACTS)


def test_a_part_names_what_rests_on_1_reading(tmp_path):
    plan = plan_of(tmp_path, {"Q1": {"mpn": "Q-1", "watts": "ldo.p_u1", "source": "s"}})
    part = thermal.judge(plan, runs_at(("as written", 25.0, 0.1)), facts_with(BASE), ECSS)["parts"]["Q1"]
    assert part["read_once"] == ["the facts q.json"]
    plan = plan_of(tmp_path, {"U1": U1})
    part = thermal.judge(plan, runs_at(("as written", 25.0, 0.1)), FACTS_LIST, ECSS)["parts"]["U1"]
    assert part["read_once"] == []


# ---------------------------------------------------------------- a deck narrower than the file


@pytest.mark.parametrize(
    ("own", "file", "left"),
    [
        ([-20, 60], [-20, 85], [85]),
        ([-40, 85], [-20, 85], [-20]),
        ([25], [-20, 85], [-20, 85]),
        ([-20, 40, 85], [-20, 85], []),
        ([], [-20, 85], []),
        # an inner corner of the file the block does not name never runs either
        ([-20, 60], [-20, 40, 60], [40]),
        # within 0.01 C (simcorners.TEMP_MATCH) a temperature is the same corner
        ([-20, 60], [-20.005, 60.005], []),
    ],
)
def test_the_temperatures_a_deck_s_own_block_leaves_out(own, file, left):
    assert simcorners.left_out(own, file) == left


def gate(*args: object) -> tuple[int, dict, str]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", "sim", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, json.loads(proc.stdout)[0], proc.stdout


def copy_of(tmp_path: Path, fixture: str) -> Path:
    shutil.copytree(BOARDS / "library", tmp_path / "boards" / "library")
    project = tmp_path / "boards" / "thermal"
    shutil.copytree(BOARDS / fixture, project, ignore=shutil.ignore_patterns("build"))
    return project


@needs_ngspice
def test_a_deck_block_narrower_than_the_file_is_flagged_and_its_part_not_held(tmp_path):
    """fail-sim-thermal's file runs -20 C and 85 C. A deck block of -20 C and 60 C hides the 85 C corner,
    where the junction is 124.97 C; at 60 C it is 60 + 231.1 x 0.17252 = 99.87 C, inside 110 C."""
    project = copy_of(tmp_path, "fail-sim-thermal")
    corners = json.loads((project / "sim" / "corners.json").read_text(encoding="utf-8"))
    corners["decks"] = {"ldo": {"temperature": {"values": [-20, 60], "source": "the deck's own range"}}}
    (project / "sim" / "corners.json").write_text(json.dumps(corners), encoding="utf-8")
    code, record, _ = gate(project, "--out", tmp_path / "out")
    assert code == 0
    assert record["details"]["warnings"] == [
        "corners.json: decks.ldo.temperature runs -20 C and 60 C, so 85 C of the file's -20 C and 85 C is "
        "not run for ldo",
        "thermal: U1 (TLV75533PDBVR) not judged at the corners of sim/corners.json: decks.ldo.temperature "
        "runs -20 C and 60 C, so 85 C of the file's -20 C and 85 C is not run",
    ]
    part = record["details"]["thermal"]["parts"]["U1"]
    assert part["held"] is None and part["worst"]["junction"] == pytest.approx(99.87, abs=0.01)
    code, record, _ = gate(project, "--out", tmp_path / "out", "--strict")
    assert code == 1


@needs_ngspice
def test_a_stated_board_temperature_fails_a_part_theta_ja_holds_in_the_gate(tmp_path):
    """pass-sim-thermal at 60 C, R1 1 % low: 0.17252 W. theta_ja gives 60 + 231.1 x 0.17252 = 99.87 C;
    a board at 100 C gives 100 + 63.8 x 0.17252 = 111.01 C, over 110 C. 3 runs stand at 60 C: R1 as
    written, 1 % low and 1 % high."""
    project = copy_of(tmp_path, "pass-sim-thermal")
    plan = json.loads((project / "sim" / "thermal.json").read_text(encoding="utf-8"))
    plan["parts"]["U1"]["from"] = BOARD_AT_60
    (project / "sim" / "thermal.json").write_text(json.dumps(plan), encoding="utf-8")
    code, record, _ = gate(project, "--out", tmp_path / "out")
    assert code == 1
    assert record["details"]["failures"] == [
        "thermal: U1 (TLV75533PDBVR) at 60 C ambient: junction 111.01 C, over 110 C (60 C, R1 -1 %, and 2 "
        "more runs): board 100 C at 60 C ambient (a board temperature made up for the test) + 63.8 C/W x "
        f"0.17252 W of ldo.p_u1, psi_jb and junction_max of {TLV755}, p 4 and 5, psi_jb on the high-k 2s2p "
        f"board of JESD 51-7 (p 5); {LIMIT}"
    ]


@needs_ngspice
def test_a_passing_line_names_the_stated_temperature_and_its_source(tmp_path):
    """pass-sim-thermal with a board at 90 C at 60 C ambient: 90 + 63.8 x 0.17252 = 101.01 C at R1 1 %
    low, inside 110 C and above the 99.87 C of theta_ja there. The line names the board and its source."""
    project = copy_of(tmp_path, "pass-sim-thermal")
    plan = json.loads((project / "sim" / "thermal.json").read_text(encoding="utf-8"))
    plan["parts"]["U1"]["from"] = {**BOARD_AT_60, "celsius": {"60": 90}}
    (project / "sim" / "thermal.json").write_text(json.dumps(plan), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CLI), "sim", str(project), "--out", str(tmp_path / "out"), "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout
    line = next(x for x in proc.stdout.splitlines() if x.startswith("thermal U1:"))
    assert "101.01 C at its worst of" in line
    assert (
        "(60 C, R1 -1 %), from board 90 C at 60 C ambient (a board temperature made up for the test);" in line
    )


def sim_text(project: Path, out: Path, *flags: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), "sim", str(project), "--out", str(out), *flags],
        capture_output=True,
        text=True,
        check=False,
    )


@needs_ngspice
def test_a_stated_board_a_hair_above_the_air_on_a_1s0p_theta_ja_fails_strict(tmp_path):
    """The reviewer's eps_1s0p_psi_jb: the TLV755P's facts with theta_ja on the 1s0p board, a board
    stated 0.001 C above the air at -20, 25 and 85 C. psi_jb gives 85.001 + 63.8 x 0.17295 = 96.035 C at
    85 C, R1 1 % low; theta_ja there gives 85 + 231.1 x 0.17295 = 124.97 C, over 110 C. Nothing bounds
    the stated board, so the part is not held and --strict fails; the line names theta_ja's junction."""
    project = copy_of(tmp_path, "fail-sim-thermal")
    facts_file = tmp_path / "boards" / "library" / "facts" / "ti-tlv755p.json"
    facts = json.loads(facts_file.read_text(encoding="utf-8"))
    facts["thermal"]["boards"]["theta_ja"] = "1s0p"
    facts_file.write_text(json.dumps(facts), encoding="utf-8")
    plan = json.loads((project / "sim" / "thermal.json").read_text(encoding="utf-8"))
    plan["parts"]["U1"]["from"] = EPSILON
    (project / "sim" / "thermal.json").write_text(json.dumps(plan), encoding="utf-8")
    proc = sim_text(project, tmp_path / "out", "--strict")
    assert proc.returncode == 1, proc.stdout
    assert (
        "thermal: U1 (TLV75533PDBVR) not held as written (and 10 more runs): its stated board 25.001 C, "
        "which gives a junction of 35.86 C, was checked against no board: its facts give theta_ja on the "
        "low-k 1s0p board of JESD 51-3, which SPRA953D calls a typical case" in proc.stdout
    )
    line = next(x for x in proc.stdout.splitlines() if x.startswith("thermal U1:"))
    assert "96.035 C at its worst of 11 runs (85 C, R1 -1 %), from board 85.001 C at 85 C ambient" in line
    assert (
        "; where a stated temperature judged, theta_ja 231.1 C/W on the low-k 1s0p board of JESD 51-3 gives "
        "124.97 C at its worst (85 C, R1 -1 %)" in line
    )


@needs_ngspice
def test_a_project_with_decks_and_no_thermal_file_is_told_no_junction_is_judged(tmp_path):
    """fail-sim-thermal with no sim/thermal.json: U1 reaches 124.97 C at 85 C on theta_ja, and the gate,
    which judges only the parts the file names, says that it judged no junction."""
    project = copy_of(tmp_path, "fail-sim-thermal")
    (project / "sim" / "thermal.json").unlink()
    proc = sim_text(project, tmp_path / "out")
    said = (
        "thermal: no part's junction is judged: sim/thermal.json is not there, and the gate judges only the "
        "parts it names (the simulate skill, A part's temperature)"
    )
    assert said in proc.stdout.splitlines(), proc.stdout
