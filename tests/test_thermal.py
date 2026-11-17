"""A part's junction temperature at every corner (tools/thermal.py, `sim/thermal.json`).

The first half needs no engine: a part's thermal facts, the junction rules of the 2 rating packs, the
project's file, and the judgement on runs written here. The second half runs the SIM gate on the
fixtures `fail-sim-thermal` (a regulator inside its limit at 25 C and past it at 85 C) and
`pass-sim-thermal` (the same deck, its hot end at 60 C); those tests skip when ngspice is absent.

The numbers are read from these documents:
- TLV755P datasheet SBVS320D: the DBV column of section 5.4 (page 5), RthetaJA 231.1 C/W; the
  operating junction temperature of section 5.1 (page 4), 150 C at the most.
- NASA EEE-INST-002, section M4, table 4, page 10 of 10: a plastic linear part's junction at 0.7 of
  its maximum or 85 C, whichever is lesser; note 2: a power device at 110 C or 40 C under its rating.
- ECSS-Q-ST-30-11C Rev.2, clause 6.21.2, table 6-21, page 57: 110 C or Tjmax - 40 C, the lower.
- TI SPRA953D, section 1.1, equation 1, page 2: TJ = TA + RthetaJA x power, which the same section
  calls a misapplication on a system board; section 1.2, page 3: a 2s2p test board gives a best case.
"""

from __future__ import annotations

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
import ratings  # noqa: E402
import thermal  # noqa: E402

needs_ngspice = engine(pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice is not installed"))

NASA = ratings.read_pack(PACKS / "nasa-eee-inst-002.json")
ECSS = ratings.read_pack(PACKS / "ecss-q-st-30-11c-rev2.json")
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
TLV755 = "TLV755P datasheet, SBVS320D, November 2017, revised September 2024"


def with_thermal(thermal_facts: object) -> dict:
    return {**MOSFET, "thermal": thermal_facts}


def refusal(raw: dict) -> str:
    with pytest.raises(ratings.Refusal) as caught:
        ratings._facts("part.json", raw)
    return str(caught.value)


# ---------------------------------------------------------------- the facts


def test_the_regulator_s_facts_carry_its_figures_and_the_pages_they_stand_on():
    """SBVS320D, the DBV column: RthetaJA 231.1, RthetaJC(top) 118.4, RthetaJB 64.4, psiJT 28.4 and psiJB
    63.8 C/W (page 5), and an operating junction of 150 C at the most (page 4)."""
    facts = {f.name: f for f in ratings.read_facts(FACTS)}
    term = facts["TLV75533PDBVR"].data["thermal"]
    assert term == {
        "junction_max": 150,
        "theta_ja": 231.1,
        "theta_jc": 118.4,
        "theta_jb": 64.4,
        "psi_jt": 28.4,
        "psi_jb": 63.8,
        "page": [4, 5],
    }


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        (with_thermal({"theta_ja": 100, "page": 2}), "part.json: thermal: `junction_max` is missing"),
        (with_thermal({"junction_max": 150, "theta_ja": 100}), "part.json: thermal: `page` is missing"),
        (
            with_thermal({"junction_max": 150, "page": 2}),
            "part.json: thermal: 1 figure at least is asked, of theta_ja, theta_jc, theta_jb, psi_jt, psi_jb",
        ),
        (
            with_thermal({"junction_max": 150, "theta_ja": 0, "page": 2}),
            "part.json: thermal: theta_ja: 0 is not above 0",
        ),
        (
            with_thermal({"junction_max": 150, "rja": 100, "page": 2}),
            "part.json: thermal: `rja` is no key here",
        ),
        (with_thermal([150, 100]), "part.json: thermal: an object is asked"),
    ],
)
def test_thermal_facts_that_are_wrong_in_1_place_are_refused_with_the_place(raw, message):
    assert ratings._facts("part.json", MOSFET).data["thermal"]["theta_ja"] == 100
    assert refusal(raw).startswith(message)


def test_a_resistor_carries_no_junction():
    raw = {"kind": "resistor", "mpn": "R-1", "tolerance": 0.01, "watts": 0.1, "volts": 50, "source": SOURCE}
    assert ratings._facts("part.json", raw).kind == "resistor"
    assert refusal({**raw, "thermal": MOSFET["thermal"]}).startswith("part.json: `thermal` is no key here")


# ---------------------------------------------------------------- the packs


def test_nasa_s_junction_limits_are_those_of_its_tables():
    """Section M4, table 4, page 10 of 10: a digital part at 0.8 of its maximum or 95 C, a linear one at
    0.7 or 85 C; note 2 holds a power device to 110 C or 40 C under its rating. Section S1, table 4,
    pages 12 and 13 of 13: a diode and a transistor at 0.80, notes 1 and 2: 125 C or 40 C under."""
    limits = {(r.id, r.kinds, r.celsius, r.share, r.below) for r in NASA.junction}
    assert limits == {
        ("junction.ic.digital", ("ic.digital",), 95, 0.8, None),
        ("junction.ic.linear", ("ic.linear",), 85, 0.7, None),
        ("junction.ic.regulator", ("ic.regulator",), 85, 0.7, 40),
        ("junction.diode", ("diode",), 125, 0.8, 40),
        ("junction.mosfet", ("transistor.mosfet",), 125, 0.8, 40),
    }
    for rule in NASA.junction:
        assert "table 4" in rule.where and "page" in rule.where, rule.id


def test_ecss_s_junction_limits_are_those_of_its_tables():
    """Tables 6-13 (page 43), 6-14 (44), 6-19 (52), 6-21 (57) and 6-36 (76): 110 C or Tjmax - 40 C,
    whichever is lower. The exception of 125 C asks for ESCC evaluation reports: no pack holds it."""
    found = {
        r.id: (r.kinds, r.celsius, r.share, r.below, r.where.split(",")[1].strip()) for r in ECSS.junction
    }
    assert found == {
        "junction.diode.rectifier": (("diode.rectifier",), 110, None, 40, "table 6-13"),
        "junction.diode.clamp": (("diode.clamp",), 110, None, 40, "table 6-14"),
        "junction.ic.digital": (("ic.digital",), 110, None, 40, "table 6-19"),
        "junction.ic.linear": (("ic.linear", "ic.regulator"), 110, None, 40, "table 6-21"),
        "junction.mosfet": (("transistor.mosfet",), 110, None, 40, "table 6-36"),
    }


def test_the_rating_rules_of_a_pack_stay_as_they_were():
    """A junction rule is no share of a rating: `workcenter ratings` reads only the other rules."""
    assert {r.stress for r in NASA.rules} | {r.stress for r in ECSS.rules} <= set(ratings.STRESSES)
    assert all(r.stress != thermal.JUNCTION for r in NASA.rules + ECSS.rules)


def test_the_regulator_s_derated_limit_in_each_pack():
    """Tjmax 150 C. NASA: the least of 85 C, 0.7 x 150 = 105 C and 150 - 40 = 110 C is 85 C. ECSS: the
    lower of 110 C and 150 - 40 = 110 C is 110 C."""
    nasa = thermal.rule_for(NASA, "ic.regulator.linear")
    assert thermal.limit(nasa, 150) == (85, "85 C, the least of 85 C, 0.7 x 150 C and 150 C - 40 C")
    ecss = thermal.rule_for(ECSS, "ic.regulator.linear")
    assert thermal.limit(ecss, 150) == (110, "110 C, the least of 110 C and 150 C - 40 C")
    # a part rated 125 C: 0.7 x 125 = 87.5 C and 125 - 40 = 85 C, so 85 C either way in NASA's
    assert thermal.limit(nasa, 125)[0] == 85
    # ECSS for a diode rated 125 C: 125 - 40 = 85 C is under 110 C
    assert thermal.limit(thermal.rule_for(ECSS, "diode.rectifier"), 125)[0] == 85


# The ECSS pack's 11 rating rules: a junction rule added after them is rule 12.
CARD = json.loads((PACKS / "ecss-q-st-30-11c-rev2.json").read_text(encoding="utf-8"))
CARD["rules"] = [r for r in CARD["rules"] if r["stress"] != "junction.temperature"]
JUNCTION_RULE = {
    "id": "j",
    "stress": "junction.temperature",
    "kinds": ["ic"],
    "celsius": 110,
    "where": "table 1, page 1",
}


@pytest.mark.parametrize(
    ("rule", "message"),
    [
        (
            {k: v for k, v in JUNCTION_RULE.items() if k != "celsius"},
            "pack.json: rule 12: 1 limit at least is asked",
        ),
        ({**JUNCTION_RULE, "share": 1.5}, "pack.json: rule 12: share: 1.5 is over 1"),
        ({**JUNCTION_RULE, "below_rating": -5}, "pack.json: rule 12: below_rating: -5 is under 0"),
        ({**JUNCTION_RULE, "max": 0.8}, "pack.json: rule 12: `max` is no key here"),
        ({**JUNCTION_RULE, "kinds": ["chip"]}, "pack.json: rule 12: kinds: `chip` names no kind of part"),
        ({**JUNCTION_RULE, "where": " "}, "pack.json: rule 12: where: text is asked"),
        (
            {**JUNCTION_RULE, "id": "output.current"},
            "pack.json: rule 12: the id `output.current` stands 2 times",
        ),
    ],
)
def test_a_junction_rule_that_is_wrong_in_1_place_is_refused_with_the_place(tmp_path, rule, message):
    path = tmp_path / "pack.json"
    path.write_text(json.dumps({**CARD, "rules": CARD["rules"] + [JUNCTION_RULE]}), encoding="utf-8")
    assert ratings.read_pack(path).junction[-1].celsius == 110
    path.write_text(json.dumps({**CARD, "rules": CARD["rules"] + [rule]}), encoding="utf-8")
    with pytest.raises(ratings.Refusal) as caught:
        ratings.read_pack(path)
    assert str(caught.value).startswith(message)


# ---------------------------------------------------------------- the project's thermal.json

PLAN = {
    "pack": "ecss-q-st-30-11c-rev2",
    "parts": {"U1": {"mpn": "TLV75533PDBVR", "watts": "ldo.p_u1", "source": "input power less output power"}},
}


def read(tmp_path: Path, data: object) -> tuple[object, list[str]]:
    (tmp_path / "thermal.json").write_text(
        data if isinstance(data, str) else json.dumps(data), encoding="utf-8"
    )
    return thermal.read_plan(tmp_path, ["ldo"])


def test_no_file_is_no_plan(tmp_path):
    assert thermal.read_plan(tmp_path, ["ldo"]) == (None, [])


def test_the_fixture_s_plan_names_its_regulator(tmp_path):
    plan, problems = read(tmp_path, PLAN)
    assert problems == []
    assert plan.pack == "ecss-q-st-30-11c-rev2"
    part = plan.parts["U1"]
    assert (part.mpn, part.deck, part.measure) == ("TLV75533PDBVR", "ldo", "p_u1")


@pytest.mark.parametrize(
    ("data", "problem"),
    [
        ("{", "thermal.json: not JSON: "),
        ({"parts": PLAN["parts"]}, "thermal.json: `pack` is missing"),
        ({**PLAN, "corners": 1}, "thermal.json: `corners` is no key here; the keys are pack, parts"),
        ({**PLAN, "parts": {}}, "thermal.json: parts: 1 part at least is asked"),
        (
            {**PLAN, "parts": {"U1": {"mpn": "X", "watts": "ldo.p_u1"}}},
            "thermal.json: parts: U1: `source` is missing",
        ),
        (
            {**PLAN, "parts": {"U1": {"mpn": "X", "watts": "pdn.p_u1", "source": "s"}}},
            "thermal.json: parts: U1: watts: `pdn` is no deck of sim/; the decks are ldo",
        ),
        (
            {**PLAN, "parts": {"U1": {"mpn": "X", "watts": "p_u1", "source": "s"}}},
            "thermal.json: parts: U1: watts: `p_u1` is no deck.measure",
        ),
        (
            {**PLAN, "parts": {"U1": {"mpn": "X", "watts": "ldo.P_U1", "source": "s"}}},
            "thermal.json: parts: U1: watts: ngspice prints a name in lower case, so `P_U1` is never "
            "measured",
        ),
    ],
)
def test_a_plan_that_is_wrong_in_1_place_is_refused_with_the_place(tmp_path, data, problem):
    plan, problems = read(tmp_path, data)
    assert plan is None
    assert len(problems) == 1 and problems[0].startswith(problem), problems


# ---------------------------------------------------------------- the judgement

FACTS_LIST = ratings.read_facts(FACTS)


def plan_of(tmp_path: Path, data: dict = PLAN):
    plan, problems = read(tmp_path, data)
    assert problems == []
    return plan


def test_a_part_past_its_limit_fails_on_1_line_with_the_corner_and_both_temperatures(tmp_path):
    """At 85 C with p_u1 = 0.17296 W: 85 + 231.1 x 0.17296 = 85 + 39.97 = 124.97 C, over ECSS's 110 C.
    At 85 C with 0.171227 W: 85 + 39.57 = 124.57 C, over too. As written, 25 C and 0.1702 W:
    25 + 39.33 = 64.33 C, inside."""
    runs = {
        "ldo": [
            ("as written", 25.0, {"p_u1": 0.1702}),
            ("85 C", 85.0, {"p_u1": 0.171227}),
            ("85 C, R1 -1 %", 85.0, {"p_u1": 0.17296}),
        ]
    }
    judged = thermal.judge(plan_of(tmp_path), runs, FACTS_LIST, ECSS)
    assert judged["failures"] == [
        "thermal: U1 (TLV75533PDBVR) at 85 C ambient: junction 124.97 C, over 110 C "
        "(85 C, R1 -1 %, and 1 more run): 85 C + 231.1 C/W x 0.17296 W of ldo.p_u1, theta_ja and "
        f"junction_max of {TLV755}, p 4 and 5; limit 110 C, the least of 110 C and 150 C - 40 C "
        "(ecss-q-st-30-11c-rev2, clause 6.21.2, table 6-21, page 57)"
    ]
    assert judged["not_judged"] == []
    part = judged["parts"]["U1"]
    assert part["written"] == {
        "run": "as written",
        "ambient": 25.0,
        "watts": 0.1702,
        "junction": pytest.approx(64.33322),
    }
    assert part["worst"]["junction"] == pytest.approx(124.971056)
    assert (part["limit"], part["held"], part["runs"]) == (110, False, 3)


def test_a_part_inside_its_limit_at_every_run_holds(tmp_path):
    """NASA's limit for the regulator is 85 C. At 50 C and 0.1702 W: 50 + 39.33 = 89.33 C, over; at
    40 C: 79.33 C, inside. So 40 C holds and 50 C does not."""
    runs = {"ldo": [("as written", 25.0, {"p_u1": 0.1702}), ("40 C", 40.0, {"p_u1": 0.1702})]}
    nasa = {**PLAN, "pack": "nasa-eee-inst-002"}
    judged = thermal.judge(plan_of(tmp_path, nasa), runs, FACTS_LIST, NASA)
    assert judged["failures"] == [] and judged["parts"]["U1"]["held"] is True
    assert judged["parts"]["U1"]["worst"]["junction"] == pytest.approx(79.33322)
    runs["ldo"].append(("50 C", 50.0, {"p_u1": 0.1702}))
    judged = thermal.judge(plan_of(tmp_path, nasa), runs, FACTS_LIST, NASA)
    assert judged["failures"][0].startswith(
        "thermal: U1 (TLV75533PDBVR) at 50 C ambient: junction 89.333 C, over 85 C (50 C):"
    )


def made_up(tmp_path: Path, thermal_facts: dict | None) -> list:
    raw = {**MOSFET, "mpn": "Q-1"}
    if thermal_facts is None:
        del raw["thermal"]
    else:
        raw["thermal"] = thermal_facts
    return [ratings._facts("q.json", raw)]


def test_a_part_with_no_thermal_figure_is_not_judged_and_says_why(tmp_path):
    plan = plan_of(tmp_path, {**PLAN, "parts": {"Q1": {"mpn": "Q-1", "watts": "ldo.p_q1", "source": "s"}}})
    runs = {"ldo": [("as written", 25.0, {"p_q1": 0.5})]}
    judged = thermal.judge(plan, runs, made_up(tmp_path, None), ECSS)
    assert judged["failures"] == []
    assert judged["not_judged"] == [
        "thermal: Q1 (Q-1) not judged: its facts (q.json) give no thermal figure: write `thermal` from the "
        "datasheet's thermal table"
    ]
    figures = {"junction_max": 150, "psi_jt": 5, "theta_jc": 20, "page": 2}
    judged = thermal.judge(plan, runs, made_up(tmp_path, figures), ECSS)
    assert judged["not_judged"] == [
        "thermal: Q1 (Q-1) not judged: its facts give theta_jc and psi_jt, and no theta_ja: theta_jc "
        "gives the junction from the case's temperature (ECSS-Q-ST-30-11C Rev.2, clause 3.2, page 12; "
        "SPRA953D, section 2), and psi_jt from the package top's temperature (SPRA953D, section 3); no "
        "deck gives either"
    ]
    judged = thermal.judge(plan, runs, [], ECSS)
    assert judged["not_judged"] == [
        "thermal: Q1 (Q-1) not judged: no facts entry names Q-1: write one from its datasheet (the "
        "ratings skill)"
    ]


def test_a_part_whose_deck_did_not_run_is_not_judged(tmp_path):
    judged = thermal.judge(plan_of(tmp_path), {"ldo": None}, FACTS_LIST, ECSS)
    assert judged["not_judged"] == [
        "thermal: U1 (TLV75533PDBVR) not judged: its deck ldo did not run to its end"
    ]


def test_a_measure_a_run_does_not_print_fails_and_so_does_a_power_under_0(tmp_path):
    runs = {"ldo": [("as written", 25.0, {"p_u1": 0.1}), ("85 C", 85.0, {}), ("-20 C", -20.0, {})]}
    judged = thermal.judge(plan_of(tmp_path), runs, FACTS_LIST, ECSS)
    assert judged["failures"] == [
        "thermal: U1: ldo.p_u1 is not printed at 85 C (and 1 more run): its junction there is not known"
    ]
    runs = {"ldo": [("as written", 25.0, {"p_u1": -0.17})]}
    judged = thermal.judge(plan_of(tmp_path), runs, FACTS_LIST, ECSS)
    assert judged["failures"] == [
        "thermal: U1: ldo.p_u1 is -0.17 W as written: a part's dissipation is not under 0; read the "
        "sign of the deck's sum"
    ]


def test_a_part_kind_with_no_junction_rule_is_held_to_its_own_rating(tmp_path):
    """A pack with no junction rule: the limit is the part's own 150 C. 25 + 231.1 x 0.6 = 163.66 C."""
    bare = ratings.Pack("bare", ECSS.document, ECSS.rules)
    runs = {"ldo": [("as written", 25.0, {"p_u1": 0.6})]}
    judged = thermal.judge(plan_of(tmp_path), runs, FACTS_LIST, bare)
    assert judged["failures"][0].endswith(
        "limit 150 C, the part's own rating: bare has no junction rule for ic.regulator.linear"
    )
    assert "junction 163.66 C, over 150 C (as written)" in judged["failures"][0]


def test_a_deck_whose_corners_were_not_run_leaves_its_parts_not_judged_there_and_not_held(tmp_path):
    """As written, 25 C and 0.1702 W: 25 + 231.1 x 0.1702 = 64.333 C, inside 110 C. The corners of the
    deck were skipped, so the part is not held: it is named as not judged at them, with the reason.
    At 0.6 W: 25 + 231.1 x 0.6 = 163.66 C, over 110 C: the run it was judged at still fails."""
    runs = {"ldo": [("as written", 25.0, {"p_u1": 0.1702})]}
    unrun = {"ldo": "the file skips deck ldo: a model fitted at 25 C"}
    judged = thermal.judge(plan_of(tmp_path), runs, FACTS_LIST, ECSS, unrun)
    assert judged["failures"] == []
    assert judged["not_judged"] == [
        "thermal: U1 (TLV75533PDBVR) not judged at the corners of sim/corners.json: the file skips deck "
        "ldo: a model fitted at 25 C"
    ]
    part = judged["parts"]["U1"]
    assert (part["held"], part["runs"]) == (None, 1)
    assert part["written"]["junction"] == pytest.approx(64.33322)
    runs = {"ldo": [("as written", 25.0, {"p_u1": 0.6})]}
    judged = thermal.judge(plan_of(tmp_path), runs, FACTS_LIST, ECSS, unrun)
    assert "junction 163.66 C, over 110 C (as written)" in judged["failures"][0]
    assert judged["parts"]["U1"]["held"] is False and len(judged["not_judged"]) == 1


def test_a_run_whose_temperature_is_not_known_is_not_judged_and_says_why(tmp_path):
    """A deck as written that ran at 25 C and at 85 C printed its power from 1 of them: that run's
    ambient is not known, so it is not judged. The corner at -20 C is: -20 + 231.1 x 0.17 = 19.287 C."""
    why = "the deck ran at 25 C and 85 C"
    runs = {"ldo": [("as written", why, {"p_u1": 0.1712262}), ("-20 C", -20.0, {"p_u1": 0.17})]}
    judged = thermal.judge(plan_of(tmp_path), runs, FACTS_LIST, ECSS)
    assert judged["failures"] == []
    assert judged["not_judged"] == [
        "thermal: U1 (TLV75533PDBVR) not judged as written: the deck ran at 25 C and 85 C, so the "
        "ambient of the run that printed ldo.p_u1 is not known"
    ]
    part = judged["parts"]["U1"]
    assert (part["written"], part["held"], part["runs"]) == (None, None, 1)
    assert part["worst"]["junction"] == pytest.approx(19.287)
    judged = thermal.judge(plan_of(tmp_path), {"ldo": runs["ldo"][:1]}, FACTS_LIST, ECSS)
    assert judged["parts"] == {} and len(judged["not_judged"]) == 1


def test_a_judged_part_names_the_board_its_figure_stands_on(tmp_path):
    """SPRA953D, section 1.2, page 3: a 2s2p test board gives a best case, a 1s board a typical one;
    section 1.1, page 2: a board unlike the test board changes RthetaJA."""
    runs = {"ldo": [("as written", 25.0, {"p_u1": 0.1702})]}
    part = thermal.judge(plan_of(tmp_path), runs, FACTS_LIST, ECSS)["parts"]["U1"]
    assert part["assumes"] == (
        "theta_ja 231.1 C/W is the datasheet's test board's: a JEDEC 2s2p board gives a best case and a "
        "1s board a typical one (SPRA953D, section 1.2, page 3); a board unlike the test board changes "
        "it (section 1.1, page 2)"
    )


def test_workcenter_next_sends_a_hot_part_and_an_unjudged_one_to_the_skill_s_section():
    import guide

    hot = "thermal: U1 (TLV75533PDBVR) at 85 C ambient: junction 124.97 C, over 110 C (85 C): ..."
    do, read = guide.hint("sim", hot)
    assert do.startswith("The part runs past its derated junction limit") and read.endswith(
        '"A part\'s temperature"'
    )
    do, read = guide.hint("sim", "thermal: Q1 (Q-1) not judged: its facts (q.json) give no thermal figure")
    assert do.startswith("Do what the line asks") and read.endswith('"A part\'s temperature"')
    assert guide.hint("sim", "thermal.json: pack is missing")[1].endswith('"A part\'s temperature"')


# ---------------------------------------------------------------- the SIM gate


def gate(*args: object) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", "sim", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, json.loads(proc.stdout)[0]


@needs_ngspice
def test_the_regulator_holds_at_25_c_and_fails_at_the_hot_corner(tmp_path):
    """R1 at 85 C and 1 % low: 33 x 0.99 x (1 - 100e-6 x 60) = 32.474 ohm. The load takes 3.3 / 32.474
    = 0.10162 A, and U1 dissipates 1.7 x 0.10162 + 5 x 40e-6 = 0.17295 W. Its junction: 85 + 231.1 x
    0.17295 = 124.97 C, over ECSS's 110 C. As written: 33 ohm, 0.1 A, 0.1702 W, 25 + 39.33 = 64.33 C.
    3 runs stand at 85 C: R1 as written, 1 % low and 1 % high."""
    code, record = gate(BOARDS / "fail-sim-thermal", "--out", tmp_path)
    assert code == 1
    failures = record["details"]["failures"]
    assert failures == [
        "thermal: U1 (TLV75533PDBVR) at 85 C ambient: junction 124.97 C, over 110 C "
        "(85 C, R1 -1 %, and 2 more runs): 85 C + 231.1 C/W x 0.17295 W of ldo.p_u1, theta_ja and "
        f"junction_max of {TLV755}, p 4 and 5; limit 110 C, the least of 110 C and 150 C - 40 C "
        "(ecss-q-st-30-11c-rev2, clause 6.21.2, table 6-21, page 57)"
    ]
    part = record["details"]["thermal"]["parts"]["U1"]
    assert part["written"]["ambient"] == 25.0
    assert part["written"]["watts"] == pytest.approx(0.1702, rel=1e-6)
    assert part["written"]["junction"] == pytest.approx(64.33322, rel=1e-6)
    assert part["held"] is False


@needs_ngspice
def test_the_same_regulator_with_its_hot_end_at_60_c_is_green_with_strict(tmp_path):
    """At 60 C, R1 1 % low: 33 x 0.99 x (1 - 100e-6 x 35) = 32.556 ohm, 0.10136 A, 1.7 x 0.10136 +
    0.0002 = 0.17252 W, and 60 + 231.1 x 0.17252 = 99.87 C, under 110 C."""
    code, record = gate(BOARDS / "pass-sim-thermal", "--out", tmp_path, "--strict")
    assert code == 0, record["details"]["failures"]
    part = record["details"]["thermal"]["parts"]["U1"]
    assert part["held"] is True
    assert part["worst"]["ambient"] == 60.0
    assert part["worst"]["junction"] == pytest.approx(99.87, abs=0.01)


def copied(tmp_path: Path, plan: dict) -> Path:
    """pass-sim-thermal beside a copy of the facts library, with its thermal.json replaced."""
    shutil.copytree(BOARDS / "library", tmp_path / "boards" / "library")
    project = tmp_path / "boards" / "thermal"
    shutil.copytree(BOARDS / "pass-sim-thermal", project, ignore=shutil.ignore_patterns("build"))
    (project / "sim" / "thermal.json").write_text(json.dumps(plan), encoding="utf-8")
    return project


@needs_ngspice
def test_a_pack_the_workcenter_does_not_hold_fails_the_gate_on_1_line(tmp_path):
    code, record = gate(copied(tmp_path, {**PLAN, "pack": "nope"}), "--out", tmp_path / "out")
    assert code == 1
    assert record["details"]["failures"] == [
        "thermal.json: pack: `nope` is no pack; the workcenter holds ecss-q-st-30-11c-rev2, nasa-eee-inst-002"
    ]


@needs_ngspice
def test_a_part_with_no_facts_passes_only_without_strict_and_is_named_either_way(tmp_path):
    plan = {**PLAN, "parts": {"U9": {"mpn": "NOT-IN-LIBRARY", "watts": "ldo.p_u1", "source": "s"}}}
    project = copied(tmp_path, plan)
    line = (
        "thermal: U9 (NOT-IN-LIBRARY) not judged: no facts entry names NOT-IN-LIBRARY: write one from its "
        "datasheet (the ratings skill)"
    )
    code, record = gate(project, "--out", tmp_path / "out")
    assert code == 0 and record["details"]["warnings"] == [line]
    code, record = gate(project, "--out", tmp_path / "out", "--strict")
    assert code == 1 and record["details"]["failures"] == [line]


@needs_ngspice
def test_one_deck_alone_leaves_a_part_of_another_deck_not_judged(tmp_path):
    """--deck runs 1 deck. A part whose power another deck prints is named, not passed."""
    project = copied(tmp_path, PLAN)
    (project / "sim" / "other.cir").write_text(
        "* a second deck\nV1 a 0 DC 1\nR1 a 0 1k\n.control\nop\nlet p_u2 = v(a) * v(a) / 1000\nprint p_u2\n"
        ".endc\n.end\n",
        encoding="utf-8",
    )
    plan = {
        **PLAN,
        "parts": {**PLAN["parts"], "U2": {"mpn": "TLV75533PDBVR", "watts": "other.p_u2", "source": "s"}},
    }
    (project / "sim" / "thermal.json").write_text(json.dumps(plan), encoding="utf-8")
    code, record = gate(project, "--out", tmp_path / "out", "--deck", "ldo")
    assert record["details"]["thermal"]["not_judged"] == [
        "thermal: U2 (TLV75533PDBVR) not judged: its deck other was not run (--deck)"
    ]
    assert record["details"]["thermal"]["parts"]["U1"]["held"] is True


def failing_copy(tmp_path: Path) -> Path:
    """fail-sim-thermal beside a copy of the facts library."""
    shutil.copytree(BOARDS / "library", tmp_path / "boards" / "library")
    project = tmp_path / "boards" / "thermal"
    shutil.copytree(BOARDS / "fail-sim-thermal", project, ignore=shutil.ignore_patterns("build"))
    return project


@needs_ngspice
def test_a_deck_whose_corners_the_file_skips_leaves_the_part_not_judged_and_fails_strict(tmp_path):
    """The skip hides the 85 C corner, where the junction is 124.97 C (the test above). As written:
    25 + 231.1 x 0.1702 = 64.333 C. The part is named as not judged at the corners; --strict fails."""
    project = failing_copy(tmp_path)
    corners = json.loads((project / "sim" / "corners.json").read_text(encoding="utf-8"))
    corners["decks"] = {"ldo": {"skip": "the regulator's model is fitted at 25 C only"}}
    (project / "sim" / "corners.json").write_text(json.dumps(corners), encoding="utf-8")
    line = (
        "thermal: U1 (TLV75533PDBVR) not judged at the corners of sim/corners.json: the file skips deck "
        "ldo: the regulator's model is fitted at 25 C only"
    )
    code, record = gate(project, "--out", tmp_path / "out", "--strict")
    assert code == 1 and line in record["details"]["failures"]
    part = record["details"]["thermal"]["parts"]["U1"]
    assert part["held"] is None and part["written"]["junction"] == pytest.approx(64.33322, rel=1e-6)


@needs_ngspice
def test_a_deck_whose_temperature_the_file_sets_to_false_leaves_the_part_not_judged_at_its_ends(tmp_path):
    """The deck runs its tolerance corners at its own 25 C only, so the file's -20 C and 85 C ends are
    not judged for the part."""
    project = failing_copy(tmp_path)
    corners = json.loads((project / "sim" / "corners.json").read_text(encoding="utf-8"))
    corners["decks"] = {"ldo": {"temperature": False, "why": "a model fitted at 25 C only"}}
    (project / "sim" / "corners.json").write_text(json.dumps(corners), encoding="utf-8")
    code, record = gate(project, "--out", tmp_path / "out", "--strict")
    assert (
        code == 1
        and (
            "thermal: U1 (TLV75533PDBVR) not judged at the corners of sim/corners.json: the file sets deck "
            "ldo's temperature to false, so it ran at none of -20 C and 85 C"
        )
        in record["details"]["failures"]
    )
    assert record["details"]["thermal"]["parts"]["U1"]["held"] is None


@needs_ngspice
def test_nominal_leaves_the_part_not_judged_at_the_corners(tmp_path):
    code, record = gate(BOARDS / "fail-sim-thermal", "--out", tmp_path, "--nominal")
    assert code == 0
    assert (
        "thermal: U1 (TLV75533PDBVR) not judged at the corners of sim/corners.json: they were not run "
        "(--nominal)"
    ) in record["details"]["warnings"]
    assert record["details"]["thermal"]["parts"]["U1"]["held"] is None


@needs_ngspice
def test_a_deck_that_runs_at_2_temperatures_is_not_judged_at_27_c(tmp_path):
    """The deck runs `op` at 25 C, then at 85 C, and prints the power of the 85 C run, 0.1712262 W:
    85 + 231.1 x 0.1712262 = 124.57 C, over 110 C. Taken at 27 C it read 66.57 C and passed. Which run
    printed the power is not known, so the part is not judged."""
    project = failing_copy(tmp_path)
    (project / "sim" / "corners.json").unlink()
    deck = project / "sim" / "ldo.cir"
    deck.write_text(
        deck.read_text(encoding="utf-8").replace(".control\nop\n", ".control\nop\noption temp=85\nop\n"),
        encoding="utf-8",
    )
    code, record = gate(project, "--out", tmp_path / "out")
    assert record["details"]["thermal"]["parts"] == {}
    assert (
        "thermal: U1 (TLV75533PDBVR) not judged as written: the deck ran at 25 C and 85 C, so the ambient "
        "of the run that printed ldo.p_u1 is not known"
    ) in record["details"]["warnings"]


@needs_ngspice
def test_the_printed_line_of_a_judged_part_names_the_board_its_figure_stands_on(tmp_path):
    proc = subprocess.run(
        [sys.executable, str(CLI), "sim", str(BOARDS / "pass-sim-thermal"), "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (
        "limit 110 C; theta_ja 231.1 C/W is the datasheet's test board's: a JEDEC 2s2p board" in proc.stdout
    )
