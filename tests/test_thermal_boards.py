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

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
PACKS = ROOT / "rules" / "ratings"
FACTS = BOARDS / "library" / "facts"
sys.path.insert(0, str(ROOT / "tools"))
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

needs_ngspice = pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice is not installed")

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
        "ambient only, and its facts give no theta_ja"
    ]
    part = judged["parts"]["Q1"]
    assert (part["runs"], part["held"], part["worst"]["junction"]) == (1, None, 92.5)


def test_a_stated_figure_the_facts_do_not_give_leaves_the_part_not_judged(tmp_path):
    plan = plan_of(tmp_path, {"Q1": {"mpn": "Q-1", "watts": "ldo.p_u1", "source": "s", "from": BOARD_AT_60}})
    judged = thermal.judge(plan, runs_at(("60 C", 60.0, 0.1)), facts_with(BASE), ECSS)
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
    assert str(caught.value).startswith("pack.json: rule 12: second_reader: write `no`, or the date")


def test_a_part_names_what_rests_on_1_reading(tmp_path):
    plan = plan_of(tmp_path, {"Q1": {"mpn": "Q-1", "watts": "ldo.p_u1", "source": "s"}})
    part = thermal.judge(plan, runs_at(("as written", 25.0, 0.1)), facts_with(BASE), ECSS)["parts"]["Q1"]
    assert part["read_once"] == ["the facts q.json"]
    plan = plan_of(tmp_path, {"U1": U1})
    part = thermal.judge(plan, runs_at(("as written", 25.0, 0.1)), FACTS_LIST, ECSS)["parts"]["U1"]
    assert part["read_once"] == []


# ---------------------------------------------------------------- a deck narrower than the file


@pytest.mark.parametrize(
    ("own", "left"),
    [([-20, 60], [85]), ([-40, 85], []), ([25], [-20, 85]), ([-20, 40, 85], []), ([], [])],
)
def test_the_temperatures_a_deck_s_own_block_leaves_out(own, left):
    assert simcorners.left_out(own, [-20, 85]) == left


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
