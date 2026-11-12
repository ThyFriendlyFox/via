"""The corners a SIM deck runs at (tools/simcorners.py, `sim/corners.json`).

The first half needs no engine: reading the file, finding what a deck's text lets a corner move,
writing the deck as a corner runs it, choosing the worst-case runs and judging a bound. The second
half runs the gate on projects built in tmp_path and on the fixtures `pass-rc-divider` (GREEN at its
corners) and `fail-sim-corner` (two decks, each inside its bound as written and outside it at one
corner); those tests skip when ngspice is absent.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
sys.path.insert(0, str(ROOT / "tools"))
import simcorners  # noqa: E402

needs_ngspice = pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice is not installed")

# ngspice 42's own line for each analysis it starts, copied from a run (PROCESSES.md P7 step 3).
RAN_AT_85 = "Doing analysis at TEMP = 85.000000 and TNOM = 27.000000\n"
RAN_AT_50 = "Doing analysis at TEMP = 50.000000 and TNOM = 27.000000\n"

# A deck that writes a value every way the corners must read: a number, a parameter in braces, a bare
# parameter, an expression, a copy inside its own .subckt, and in .control an element's value set
# again with and without `=`, beside an `alter` of a source, which is no part's value.
DECK = """* a deck with every way to write a value
.param rtop=10k cx = 1n
R1 in out {rtop}
R2 out 0 rtop
C1 out 0 {cx}
R3 a b {2*rtop}
RLOAD out 0 1Meg
.subckt S a b
R1 a b 5k
.ends
.control
alter r1 2k
alter rload = 2Meg
alter v1 dc=4.2
.endc
.end
"""


def run(*args: object) -> tuple[int, list[dict]]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", *map(str, args)], capture_output=True, text=True, check=False
    )
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else [])


def write_corners(sim: Path, spec: dict) -> None:
    (sim / simcorners.CORNERS_FILE).write_text(json.dumps(spec), encoding="utf-8")


# ------------------------------------------------------------- no engine


@pytest.mark.parametrize(
    ("token", "value"),
    [
        ("20m", 0.02),
        ("1k", 1e3),
        ("4.7u", 4.7e-6),
        ("1Meg", 1e6),
        ("1M", 1e-3),  # M is milli in SPICE; mega is Meg
        ("1F", 1e-15),  # F alone is femto, not farad
        ("5a", 5e-18),  # A alone is atto: ngspice 42 prints @r8[resistance] = 5.000000e-18 for `5a`
        ("100nF", 100e-9),
        ("1kOhm", 1e3),
        ("1e-9", 1e-9),
        (".5", 0.5),
        ("-3.3", -3.3),
    ],
)
def test_a_spice_number_is_read_the_way_ngspice_reads_it(token, value):
    assert simcorners.spice_number(token) == pytest.approx(value, rel=1e-12)


@pytest.mark.parametrize("token", ["{rtop}", "rtop", "{2*rtop}", "3.3k,", "", "1k5"])
def test_what_is_not_a_number_is_not_moved(token):
    assert simcorners.spice_number(token) is None


def test_corners_json_is_resolved_for_each_deck(tmp_path):
    write_corners(
        tmp_path,
        {
            "temperature": {"values": [-20, 85], "source": "REQ-ENV-01"},
            "tolerance": {"R": 0.01, "parts": {"r12": 0.001}, "source": "the parts list"},
            "monte_carlo": {"runs": 5, "seed": 7},
            "decks": {
                "model": {"skip": "the model against its datasheet's 25 C rows"},
                "ac": {"temperature": False, "why": "the deck sweeps the temperature itself"},
                "own": {"tolerance": {"C": 0.2, "source": "X5R"}},
            },
        },
    )
    spec, problems = simcorners.read_corners(tmp_path, ["ac", "model", "own", "plain"])
    assert problems == []
    assert spec["plain"].temperatures == [-20.0, 85.0]
    assert spec["plain"].tolerance == {"R": 0.01, "parts": {"R12": 0.001}}  # names are upper case
    assert spec["plain"].monte_carlo == {"runs": 5, "seed": 7}
    assert spec["model"].skip == "the model against its datasheet's 25 C rows"
    assert spec["ac"].temperatures == [] and spec["ac"].tolerance == spec["plain"].tolerance
    assert spec["own"].tolerance == {"C": 0.2, "parts": {}}  # a deck's own block replaces the project's
    assert spec["own"].temperatures == [-20.0, 85.0]


def test_a_project_without_the_file_has_no_corners(tmp_path):
    assert simcorners.read_corners(tmp_path, ["a"]) == (None, [])


@pytest.mark.parametrize(
    ("spec", "said"),
    [
        ({"temprature": {"values": [85], "source": "x"}}, "unknown key 'temprature'"),
        ({"temperature": {"values": [85]}}, "temperature: no source"),
        ({"temperature": {"values": [], "source": "x"}}, "values is not a list of temperatures"),
        ({"temperature": {"values": ["85"], "source": "x"}}, "values is not a list of temperatures"),
        ({"tolerance": {"R": 1, "source": "x"}}, "tolerance.R: 1 is not a fraction"),
        ({"tolerance": {"R": 0.01}}, "tolerance: no source"),
        ({"tolerance": {"Q": 0.01, "source": "x"}}, "tolerance: unknown key 'Q'"),
        ({"tolerance": {"parts": {"R7": "1%"}, "source": "x"}}, "tolerance.parts.R7: '1%' is not a fraction"),
        ({"monte_carlo": {"runs": 5}}, "names neither temperature nor tolerance"),
        (
            {"temperature": {"values": [85], "source": "x"}, "monte_carlo": {"runs": 0}},
            "monte_carlo.runs: 0 is not a count",
        ),
        (
            {"temperature": {"values": [85], "source": "x"}, "decks": {"gone": {"skip": "x"}}},
            "decks.gone: no sim/gone.cir",
        ),
        (
            {"temperature": {"values": [85], "source": "x"}, "decks": {"a": {"temperature": False}}},
            "decks.a: a corner set to false needs why",
        ),
        (
            {"temperature": {"values": [85], "source": "x"}, "decks": {"a": {"skip": ""}}},
            "decks.a.skip: no reason",
        ),
        (
            {"temperature": {"values": [85], "source": "x"}, "decks": {"a": {"skipp": "x"}}},
            "decks.a: unknown key 'skipp'",
        ),
    ],
)
def test_every_line_of_the_file_the_gate_cannot_act_on_is_named(tmp_path, spec, said):
    write_corners(tmp_path, spec)
    _, problems = simcorners.read_corners(tmp_path, ["a"])
    assert any(said in p for p in problems), problems


def test_a_file_that_is_not_json_is_one_problem(tmp_path):
    (tmp_path / simcorners.CORNERS_FILE).write_text("{not json", encoding="utf-8")
    spec, problems = simcorners.read_corners(tmp_path, ["a"])
    assert spec == {} and len(problems) == 1 and "not JSON" in problems[0]


def test_the_template_is_refused_until_its_sources_are_written(tmp_path):
    template = ROOT / "templates" / "project" / simcorners.CORNERS_FILE
    shutil.copyfile(template, tmp_path / simcorners.CORNERS_FILE)
    _, problems = simcorners.read_corners(tmp_path, ["a"])
    assert problems == [
        "temperature: no source: the requirement or datasheet the range comes from",
        "tolerance: no source: where the tolerances come from",
    ]
    spec = json.loads(template.read_text(encoding="utf-8"))
    spec["temperature"]["source"] = "REQ-ENV-01"
    spec["tolerance"]["source"] = "the parts list"
    write_corners(tmp_path, spec)
    resolved, problems = simcorners.read_corners(tmp_path, ["a"])
    assert problems == [] and resolved["a"].temperatures == [0.0, 40.0]
    assert resolved["a"].monte_carlo == {"runs": 50, "seed": 1}


def test_a_tolerance_finds_board_named_elements_parts_and_parameters():
    varied, problems, uncovered = simcorners.find_varied(
        DECK, {"R": 0.05, "parts": {"CX": 0.1, "R3": 0.01, "RLOAD": 0.02}}
    )
    found = {v.name: (v.kind, v.tol, [(s.line, s.value) for s in v.sites]) for v in varied}
    assert found == {
        # the parameter `parts` names moves under its own name, so C1, written from it, claims nothing
        "cx": ("param", 0.1, [(1, 1e-9)]),
        # R1 is written from rtop at the top level, as a number in the .subckt, and set again by an
        # `alter` in .control: all three places move. Its top-level place is its own token, `{rtop}`,
        # which has no number (None) and is scaled where it stands, not the parameter's number
        "R1": ("R", 0.05, [(2, None), (8, 5e3), (11, 2e3)]),
        # R2 is written from the same parameter and is another resistor: it moves by itself
        "R2": ("R", 0.05, [(3, None)]),
        # an expression is scaled where it stands too
        "R3": ("R", 0.01, [(5, None)]),
        # a word, not a board reference: moved only because `parts` names it, its `alter` with it
        "RLOAD": ("R", 0.02, [(6, 1e6), (12, 2e6)]),
    }
    assert problems == []
    assert uncovered == []  # C has no tolerance of its own, and C1 moves with cx


def test_an_element_named_like_a_board_part_with_no_tolerance_is_listed():
    varied, problems, uncovered = simcorners.find_varied(DECK, {"C": 0.2, "parts": {}})
    assert [v.name for v in varied] == ["C1"] and problems == []
    assert uncovered == ["R1", "R2", "R3"]  # RLOAD is a word: no board part, so not expected


def test_no_tolerance_moves_nothing_and_says_which_parts_that_leaves():
    # a file with temperatures and no tolerance block leaves every board part where it is written
    assert simcorners.find_varied(DECK, None) == ([], [], ["R1", "R2", "C1", "R3"])
    # a deck whose tolerance the project set to false, with why, is not asked again
    assert simcorners.find_varied(DECK, None, declined=True) == ([], [], [])


def test_two_parts_written_from_one_parameter_move_apart():
    """`.param rdiv=10k`, `R1 in out {rdiv}`, `R2 out 0 {rdiv}` is 2 resistors. Moved as 1, their ratio
    never changes and a 5 % divider that reaches 2.375 V passes [2.42, 2.58]."""
    deck = "* d\n.param rdiv=10k\nV1 in 0 DC 5\nR1 in out {rdiv}\nR2 out 0 'rdiv'\nR3 out 0 rdiv\n.end\n"
    varied, problems, uncovered = simcorners.find_varied(deck, {"R": 0.05, "parts": {}})
    assert [v.name for v in varied] == ["R1", "R2", "R3"] and not problems and not uncovered
    corner = simcorners.Corner("w", "worst", "", scale={"R1": 1.05, "R2": 0.95, "R3": 0.95})
    lines = simcorners.corner_text(deck, varied, corner).split("\n")
    assert lines[1] == ".param rdiv=10k"
    assert lines[3:6] == ["R1 in out {(rdiv)*1.05}", "R2 out 0 '(rdiv)*0.95'", "R3 out 0 {(rdiv)*0.95}"]
    # a parameter `parts` names is 1 quantity: it moves as 1, and the parts written from it with it
    varied, _, _ = simcorners.find_varied(deck, {"R": 0.05, "parts": {"RDIV": 0.01}})
    assert [(v.name, v.kind, v.tol) for v in varied] == [("rdiv", "param", 0.01)]


def test_a_word_named_element_no_tolerance_moves_is_listed_as_held():
    """A reader of a corner run sees what it left where the deck wrote it. An element named like a
    board part is not in this list: with no tolerance it is `uncovered`, which warns."""

    def held(deck: str, tolerance: dict) -> list[str]:
        return simcorners.held(deck, simcorners.find_varied(deck, tolerance)[0])

    assert held(DECK, {"R": 0.05}) == ["RLOAD"]
    assert held(DECK, {"R": 0.05, "parts": {"CX": 0.1, "RLOAD": 0.02}}) == []
    cable = "* x\nV1 a 0 5\nRCABLE a b 0.05\nLCABLE b c {lc}\nCBULK c 0 0\nR1 c 0 1k\n.param lc=1u\n.end\n"
    assert held(cable, {"R": 0.01}) == ["RCABLE", "LCABLE"]
    # a parameter `parts` names moves the element written from it; a value of 0 has nowhere to move
    assert held(cable, {"R": 0.01, "parts": {"LC": 0.2}}) == ["RCABLE"]
    assert held(cable, {"R": 0.01, "parts": {"RCABLE": 0.1}}) == ["LCABLE"]


def test_a_corner_rewrites_each_value_in_place_and_sets_the_temperature_before_control():
    varied, _, _ = simcorners.find_varied(DECK, {"R": 0.05, "parts": {"CX": 0.1}})
    corner = simcorners.Corner("w1", "worst", "", temp=-20, scale={"R1": 1.05, "CX": 0.9})
    lines = simcorners.corner_text(DECK, varied, corner).split("\n")
    # the parameter `parts` names moves by its number; R1's own `{rtop}` is scaled where it stands, so
    # rtop keeps its number for R2, which this corner does not move
    assert lines[1] == ".param rtop=10k cx = 9e-10"
    assert lines[2] == "R1 in out {(rtop)*1.05}" and lines[8] == "R1 a b 5250"
    assert lines[3] == "R2 out 0 rtop" and lines[5] == "R3 a b {2*rtop}"  # the rest is as written
    assert lines[10:12] == [".options temp=-20", ".control"]
    # the part is as far off its value in the analyses after the deck sets it again
    assert lines[12] == "alter r1 2100"
    # an element this corner does not move, and a source, stay as written
    assert lines[13:15] == ["alter rload = 2Meg", "alter v1 dc=4.2"]
    assert len(lines) == len(DECK.split("\n")) + 1


# Every way ngspice 42 was seen to read an element's value: on a continuation line, behind the
# kind's own parameter with and without spaces, behind a comment line between continuations.
FORMS = """* values written the long way
V1 in 0 DC 5
R1 in out
+ 10k
R2 out 0 r=20k
R3 out 0 r = 30k ; a comment
C1 out 0 c=10u
L1 out x l = 10m
R5 x 0
+ r=2k
* a comment between
+ tc1=2m
R9 in w 4k7
.end
"""


def test_a_value_is_found_on_a_continuation_line_and_behind_its_parameter():
    varied, problems, uncovered = simcorners.find_varied(FORMS, {"R": 0.05, "C": 0.1, "L": 0.1})
    found = {v.name: [(s.line, FORMS.split("\n")[s.line][s.start : s.end]) for s in v.sites] for v in varied}
    assert found == {
        "R1": [(3, "10k")],
        "R2": [(4, "20k")],
        "R3": [(5, "30k")],
        "C1": [(6, "10u")],
        "L1": [(7, "10m")],
        "R5": [(9, "2k")],
    }
    values = {v.name: v.nominal for v in varied}
    assert values == pytest.approx({"R1": 1e4, "R2": 2e4, "R3": 3e4, "C1": 1e-5, "L1": 1e-2, "R5": 2e3})
    assert problems == [] and uncovered == ["R9"]  # 4k7 is no number the corners can scale
    corner = simcorners.Corner("w", "worst", "", temp=None, scale={"R1": 1.05, "C1": 1.1, "R5": 0.95})
    lines = simcorners.corner_text(FORMS, varied, corner).split("\n")
    assert lines[2:4] == ["R1 in out", "+ 10500"]
    assert lines[6] == "C1 out 0 c=1.1e-05" and lines[9] == "+ r=1900" and lines[11] == "+ tc1=2m"
    assert lines[5] == "R3 out 0 r = 30k ; a comment"


def test_a_digit_after_the_scale_letter_is_named_with_what_ngspice_takes():
    """ngspice 42 prints @r9[resistance] = 4.000000e+03 for `R9 in w 4k7` and says nothing."""
    assert simcorners.misread_values(FORMS) == [
        "R9: ngspice reads the value 4k7 as 4k: it drops a digit after the scale letter. Write 4.7k"
    ]
    assert simcorners.misread_values("* t\nC1 a 0 2n2\nL1 a b 1.5m5\nR1 a 0 1e3\nR2 a 0 10kOhm\n.end\n") == [
        "C1: ngspice reads the value 2n2 as 2n: it drops a digit after the scale letter. Write 2.2n",
        "L1: ngspice reads the value 1.5m5 as 1.5m: it drops a digit after the scale letter. Write the "
        "number with its point",
    ]


def test_an_altermod_line_with_several_parameters_is_named():
    """One line per parameter is what ngspice 42 applies; a netlist line outside .control is no
    altermod and a single parameter, written either way, is right (M163)."""
    deck = """* models switched in .control
.model DMOD D(is=1e-14)
.control
altermod DMOD is=1e-12 rs=500
altermod DMOD rs=1
altermod @DMOD[is] = 1e-13
altermod QMAX vto = 1.0 kp = 550 rd=1.15m ; the maximum model
op
.endc
.end
"""
    assert simcorners.crowded_altermods(deck) == [
        "altermod DMOD: ngspice applies only the first parameter on the line (is) and drops rs. Write 1 "
        "altermod line for each parameter",
        "altermod QMAX: ngspice applies only the first parameter on the line (vto) and drops kp, rd. Write "
        "1 altermod line for each parameter",
    ]
    assert simcorners.crowded_altermods("* t\nR1 a 0 1k\n.end\n") == []


def test_a_device_held_at_its_own_temperature_is_named():
    deck = """* pinned
R1 in ref 10k tc1=100u
D1 ref 0 DREF temp=27
D2 ref 0 DREF
+ temp = 40
D3 ref 0 DREF dtemp=5
.model DREF D(IS=2.52n tnom=27)
.options temp=50
.control
alter d4 temp=27
alter @d5[temp] = 30
alter r1 2k
.endc
.end
"""
    # dtemp moves with the circuit; a model's tnom and the circuit's own temperature are not a pin
    assert simcorners.pinned_temperatures(deck) == ["D1", "D2", "d4", "d5"]
    assert simcorners.pinned_temperatures(DECK) == []


def test_a_corner_with_no_temperature_adds_no_line_and_a_deck_without_control_gets_it_before_end():
    varied, _, _ = simcorners.find_varied(DECK, {"R": 0.05, "parts": {}})
    plain = simcorners.Corner("R1+", "tolerance", "", scale={"R1": 1.05})
    assert ".options temp" not in simcorners.corner_text(DECK, varied, plain)
    batch = "* batch deck\nV1 in 0 1\nR1 in 0 1k\n.op\n.end\n"
    hot = simcorners.Corner("t85", "temperature", "85 C", temp=85)
    assert simcorners.corner_text(batch, [], hot).split("\n")[4:6] == [".options temp=85", ".end"]


def two_parts() -> list[simcorners.Varied]:
    return [
        simcorners.Varied("R1", "R", 0.01, [simcorners.Site(2, 0, 1, 1000.0)]),
        simcorners.Varied("R2", "R", 0.05, [simcorners.Site(3, 0, 1, 1000.0)]),
    ]


def test_the_first_corners_move_one_range_at_a_time():
    firsts = simcorners.first_corners([-20, 27, 85], two_parts())
    assert [(c.id, c.kind, c.label, c.temp, c.scale) for c in firsts] == [
        ("t-20", "temperature", "-20 C", -20, {}),
        ("t85", "temperature", "85 C", 85, {}),  # 27 C is the deck as written: no run of its own
        # each part alone at both ends, then half-way to each: a peak inside the range shows there
        ("R1-", "tolerance", "R1 -1 %", None, {"R1": 0.99}),
        ("R1+", "tolerance", "R1 +1 %", None, {"R1": 1.01}),
        ("R1-h", "tolerance", "R1 -0.5 %", None, {"R1": 0.995}),
        ("R1+h", "tolerance", "R1 +0.5 %", None, {"R1": 1.005}),
        ("R2-", "tolerance", "R2 -5 %", None, {"R2": 0.95}),
        ("R2+", "tolerance", "R2 +5 %", None, {"R2": 1.05}),
        ("R2-h", "tolerance", "R2 -2.5 %", None, {"R2": 0.975}),
        ("R2+h", "tolerance", "R2 +2.5 %", None, {"R2": 1.025}),
    ]
    # a deck that sets its own 40 C as written leaves the 27 C the project names to be run
    at_40 = simcorners.first_corners([27, 85], [], written_at=40.0)
    assert [(c.id, c.temp) for c in at_40] == [("t27", 27), ("t85", 85)]


def test_the_worst_corner_sets_every_range_to_the_end_that_pushed_the_measure():
    # g falls when hot, falls with R1 and rises with R2; h moves with nothing.
    varied = two_parts()
    firsts = simcorners.first_corners([-20, 85], varied)
    results = {
        "t-20": {"g": 1.02, "h": 5.0},
        "t85": {"g": 0.95, "h": 5.0},
        "R1-": {"g": 1.01, "h": 5.0},
        "R1+": {"g": 0.99, "h": 5.0},
        "R2-": {"g": 0.96, "h": 5.0},
        "R2+": {"g": 1.04, "h": 5.0},
    }
    bounded = {"g": (True, True), "h": (True, False)}
    worst = simcorners.worst_corners(bounded, {"g": 1.0, "h": 5.0}, firsts, results, varied)
    assert [(c.id, c.label, c.temp, c.scale) for c in worst] == [
        ("w1", "85 C, R1 +1 %, R2 -5 %", 85, {"R1": 1.01, "R2": 0.95}),  # g's least
        ("w2", "-20 C, R1 -1 %, R2 +5 %", -20, {"R1": 0.99, "R2": 1.05}),  # g's greatest
    ]  # h's worst case is the deck as written, which has run
    # a measure bounded on one side asks for one run; a second measure with the same worst case, none
    twice = {cid: {"g": m["g"], "g2": 2 * m["g"]} for cid, m in results.items()}
    one_side = {"g": (False, True), "g2": (False, True)}
    only_max = simcorners.worst_corners(one_side, {"g": 1.0, "g2": 2.0}, firsts, twice, varied)
    assert [c.label for c in only_max] == ["-20 C, R1 -1 %, R2 +5 %"]
    # a measure the deck as written did not print has no worst case to look for
    assert simcorners.worst_corners({"g3": (True, True)}, {"g": 1.0}, firsts, results, varied) == []
    # a measure only one range moves has its worst case among the first corners already
    one = {"t-20": {"g": 1.0}, "t85": {"g": 0.9}, "R1-": {"g": 1.0}, "R1+": {"g": 1.0}}
    assert simcorners.worst_corners({"g": (True, True)}, {"g": 1.0}, firsts, one, varied) == []


def test_monte_carlo_draws_repeat_for_a_seed_and_stay_inside_every_range():
    varied = two_parts()
    monte = {"runs": 200, "seed": 1}
    draws = simcorners.monte_carlo_corners("isense", monte, [-20, 85], varied)
    again = simcorners.monte_carlo_corners("isense", monte, [-20, 85], varied)
    assert [(c.id, c.temp, c.scale) for c in draws] == [(c.id, c.temp, c.scale) for c in again]
    assert draws[0].id == "mc001" and draws[-1].id == "mc200" and draws[0].kind == "monte-carlo"
    assert all(0.99 <= c.scale["R1"] <= 1.01 and 0.95 <= c.scale["R2"] <= 1.05 for c in draws)
    assert all(-20 <= c.temp <= 85 for c in draws)
    assert min(c.scale["R2"] for c in draws) < 0.96 and max(c.scale["R2"] for c in draws) > 1.04
    other_deck = simcorners.monte_carlo_corners("heater", monte, [-20, 85], varied)
    other_seed = simcorners.monte_carlo_corners("isense", {"runs": 200, "seed": 2}, [-20, 85], varied)
    assert other_deck[0].scale != draws[0].scale and other_seed[0].scale != draws[0].scale
    # with no temperature range the draws leave the deck's own temperature; with nothing to move, none
    assert simcorners.monte_carlo_corners("isense", monte, [], varied)[0].temp is None
    assert simcorners.monte_carlo_corners("isense", monte, [], []) == []
    assert simcorners.monte_carlo_corners("isense", None, [-20, 85], varied) == []


def test_a_run_at_another_temperature_than_its_corners_is_named():
    hot = simcorners.Corner("t85", "temperature", "85 C", temp=85)
    assert simcorners.temperature_problem(hot, "Circuit: x\n" + RAN_AT_85 + RAN_AT_85) is None
    assert (
        simcorners.temperature_problem(hot, RAN_AT_50 + RAN_AT_85)
        == "ran at 50 C, not 85 C: the deck sets its own temperature"
    )
    assert "is not confirmed" in simcorners.temperature_problem(hot, "No. of Data Rows : 1\n")
    # a corner that sets no temperature leaves the deck's own, whatever it is
    part = simcorners.Corner("R1+", "tolerance", "R1 +1 %", scale={"R1": 1.01})
    assert simcorners.temperature_problem(part, RAN_AT_50) is None


def test_the_envelope_names_the_run_at_each_end_and_a_bound_fails_at_its_worst_corner():
    firsts = simcorners.first_corners([-20, 85], two_parts())
    by_id = {c.id: c for c in firsts}
    runs = [
        (by_id["t85"], {"g": 0.95, "h": 5.0}),
        (by_id["R2+"], {"g": 1.04, "h": 5.0}),
        (by_id["t-20"], {"h": 5.0}),  # g was not measured cold
    ]
    env = simcorners.envelope({"g": 1.0, "h": 5.0}, runs)
    assert env["g"] == {"min": 0.95, "min_at": "85 C", "max": 1.04, "max_at": "R2 +5 %", "missing": ["-20 C"]}
    assert env["h"]["min_at"] == "nominal" and env["h"]["missing"] == []
    # inside its bound at every corner that measured it, still failed by the one that did not
    corner, value, count = simcorners.worst_offender("g", {"min": 0.9, "max": 1.1}, runs)
    assert (corner.id, value, count) == ("t-20", None, 1)
    # 0.95 is 0.02 under 0.97; 1.04 is 0.01 over 1.03: the missing one is worst, then the hot one
    corner, value, count = simcorners.worst_offender("g", {"min": 0.97, "max": 1.03}, runs[:2])
    assert (corner.id, value, count) == ("t85", 0.95, 2)
    assert simcorners.worst_offender("h", {"min": 4.9, "max": 5.1}, runs) is None
    assert simcorners.worst_offender("h", {"max": 4.9}, runs)[2] == 3


def test_a_model_bound_and_a_bound_that_says_so_are_judged_as_written_only():
    assert simcorners.nominal_only({"min": 1, "warn": "the model against its datasheet"})
    assert simcorners.nominal_only({"min": 1, "at": "nominal"})
    assert not simcorners.nominal_only({"min": 1, "source": "the firmware's limit"})


def test_monte_carlo_statistics_cover_only_its_own_runs():
    draws = simcorners.monte_carlo_corners("d", {"runs": 3, "seed": 1}, [], two_parts())
    hot = simcorners.Corner("t85", "temperature", "85 C", temp=85)
    runs = [(hot, {"g": 100.0}), (draws[0], {"g": 1.0}), (draws[1], {"g": 2.0}), (draws[2], {"g": 3.0})]
    stats = simcorners.statistics(runs)
    assert stats == {"g": {"runs": 3, "mean": 2.0, "stdev": 1.0, "min": 1.0, "max": 3.0}}
    assert simcorners.statistics(runs[:1]) == {}


# ------------------------------------------------------------- the gate

DIVIDER = """* a divider: 5 V through 10k into 10k
V1 in 0 DC 5
R1 in out 10k
R2 out 0 10k
.control
op
let vout = v(out)
print vout
.endc
.end
"""


def project(tmp_path: Path, deck: str, bounds: dict, corners: dict | None) -> Path:
    proj = tmp_path / "proj"
    (proj / "sim").mkdir(parents=True)
    (proj / "sim" / "d.cir").write_text(deck, encoding="utf-8")
    (proj / "sim" / "d.expect.json").write_text(json.dumps({"vout": bounds}), encoding="utf-8")
    if corners is not None:
        write_corners(proj / "sim", corners)
    return proj


@needs_ngspice
def test_the_passing_fixture_holds_its_bound_at_every_corner_even_strict(tmp_path):
    code, records = run("sim", BOARDS / "pass-rc-divider", "--out", tmp_path, "--strict")
    assert code == 0, records
    # 2 temperatures; R1, R2 and C1 each alone at both ends and half-way (12); the 8 combinations of
    # their ends at the deck's own temperature and at each of the 2 (24); 8 Monte Carlo draws
    assert records[0]["summary"] == "1 decks, 46 corner runs, 0 failures"
    assert records[0]["details"]["corners"] == {"runs": 46, "nominal_only": False}
    deck = records[0]["details"]["decks"]["rc_divider"]
    corners = deck["corners"]
    assert corners["search"] == "every combination of the ends"
    assert corners["temperatures"] == [-40.0, 85.0] and corners["uncovered"] == []
    assert [(v["name"], v["tolerance"]) for v in corners["varied"]] == [
        ("R1", 0.01),
        ("R2", 0.01),
        ("C1", 0.1),
    ]
    # R1 = 10k x 1.01 x (1 + 100e-6 x 58), R2 = 10k x 0.99 x (1 - 100e-6 x 58): 5 R2/(R1 + R2) = 2.4605;
    # cold with the parts the other way, 67 K under 27 C: 2.5417
    span = corners["envelope"]["vout"]
    assert span["min"] == pytest.approx(2.4605, abs=1e-4)
    assert span["min_at"].startswith("85 C, R1 +1 %, R2 -1 %")  # C1 is at an end too and moves nothing
    assert span["max"] == pytest.approx(2.5417, abs=1e-4)
    assert span["max_at"].startswith("-40 C, R1 -1 %, R2 +1 %")
    assert deck["checks"]["vout"]["ok"] is True and deck["checks"]["vout"]["held"] is True
    # how far inside its bound the output stays at its worst: 2.55 - 2.54175
    assert deck["checks"]["vout"]["margin"] == pytest.approx(0.00825, abs=1e-5)
    assert corners["monte_carlo"]["statistics"]["vout"]["runs"] == 8
    # what it writes: a folder per corner with its own deck and log, and every run's measures
    folder = tmp_path / "sim" / "corners" / "rc_divider"
    assert corners["folder"] == str(folder)
    assert sorted(p.name for p in folder.iterdir() if p.is_dir())[:4] == ["C1+", "C1+h", "C1-", "C1-h"]
    rows = json.loads((folder / "runs.json").read_text(encoding="utf-8"))
    # the run that gives the least output: hot, R1 high, R2 low
    least = next(r for r in rows if r["label"] == "85 C, R1 +1 %, R2 -1 %, C1 -10 %")
    text = (folder / least["id"] / "rc_divider.cir").read_text(encoding="utf-8")
    assert "R1 in out 10100 tc1=100u" in text and ".options temp=85" in text
    assert (folder / "t85" / "ngspice.log").is_file()
    assert len(rows) == 46 and {r["kind"] for r in rows} == {
        "temperature",
        "tolerance",
        "worst",
        "monte-carlo",
    }


@needs_ngspice
def test_a_bound_that_holds_as_written_fails_at_the_corner_that_breaks_it(tmp_path):
    code, records = run("sim", BOARDS / "fail-sim-corner", "--out", tmp_path)
    assert code == 1
    failures = records[0]["details"]["failures"]
    assert len(failures) == 2
    # the diode's forward voltage: 0.548 V as written, 0.42 V hot, with R1 high a little lower still
    assert failures[0] == (
        "diode_ref:vref=0.4215933 at 85 C, R1 +5 % (and 5 more corners) not in [0.5, 0.6] "
        "(the fixture's reference window, 0.55 V within 0.05 V)"
    )
    # 5 x 9.5/(10.5 + 9.5) = 2.375 and 5 x 10.5/(9.5 + 10.5) = 2.625 are as far out as each other
    worst = r"divider:vout=2\.[36]\d+ at R1 [+-]5 %, R2 [+-]5 % \(and 9 more corners\) "
    assert re.fullmatch(worst + r"not in \[2\.45, 2\.55\] .*", failures[1]), failures[1]
    decks = records[0]["details"]["decks"]
    for name, measure in (("diode_ref", "vref"), ("divider", "vout")):
        check = decks[name]["checks"][measure]
        assert check["ok"] is True and check["held"] is False  # inside as written, outside at a corner
    assert decks["divider"]["corners"]["envelope"]["vout"]["min"] == pytest.approx(2.375)
    assert decks["divider"]["corners"]["envelope"]["vout"]["max"] == pytest.approx(2.625)
    # the divider's resistors carry no temperature coefficient: its temperature corners prove nothing
    assert records[0]["details"]["warnings"] == [
        "divider: no measure moves with temperature: nothing in the deck or its models carries one"
    ]


@needs_ngspice
def test_one_deck_prints_each_value_with_its_corners(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "sim",
            BOARDS / "fail-sim-corner",
            "--deck",
            "diode_ref",
            "--out",
            tmp_path,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    line = r"^\s+vref = 0\.547756  \[0\.5, 0\.6\] ok  corners 0\.421593 \(85 C, R1 \+5 %\) to 0\.648079 "
    assert re.search(line + r"\(-20 C, R1 -5 %\) OUT$", proc.stdout, re.M), proc.stdout


@needs_ngspice
def test_a_project_that_names_no_corners_is_warned_and_fails_a_strict_run(tmp_path):
    proj = project(tmp_path, DIVIDER, {"min": 2.4, "max": 2.6}, None)
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 0 and records[0]["details"]["corners"] is None
    assert records[0]["details"]["warnings"] == [
        "no sim/corners.json: each deck ran once, at 27 C with every part at its written value"
    ]
    assert records[0]["summary"] == "1 decks, 0 failures, 1 warnings"
    assert "corners" not in records[0]["details"]["decks"]["d"]
    code, records = run("sim", proj, "--out", tmp_path / "o", "--strict")
    assert code == 1


@needs_ngspice
def test_nominal_leaves_the_corners_out_and_says_so(tmp_path):
    proj = project(tmp_path, DIVIDER, {"min": 2.4, "max": 2.6}, {"tolerance": {"R": 0.1, "source": "x"}})
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1  # 10 % resistors: 5 x 9/(11 + 9) = 2.25
    code, records = run("sim", proj, "--out", tmp_path / "o", "--nominal")
    assert code == 0 and records[0]["details"]["corners"] == {"runs": 0, "nominal_only": True}
    assert records[0]["details"]["warnings"] == ["the corners of sim/corners.json were not run (--nominal)"]
    code, records = run("sim", proj, "--out", tmp_path / "o", "--nominal", "--strict")
    assert code == 1


@needs_ngspice
def test_a_deck_the_project_keeps_out_runs_no_corner_and_carries_the_reason(tmp_path):
    spec = {"tolerance": {"R": 0.1, "source": "x"}, "decks": {"d": {"skip": "a model check at 25 C"}}}
    proj = project(tmp_path, DIVIDER, {"min": 2.4, "max": 2.6}, spec)
    code, records = run("sim", proj, "--out", tmp_path / "o", "--strict")
    assert code == 0, records
    assert records[0]["details"]["decks"]["d"]["corners"] == {"skip": "a model check at 25 C"}
    assert records[0]["summary"] == "1 decks, 0 failures"


@needs_ngspice
def test_a_deck_that_sets_its_own_temperature_does_not_pass_for_a_hot_run(tmp_path):
    own = DIVIDER.replace("R1 in out 10k", "R1 in out 10k tc1=1m").replace(
        ".control", ".control\nset temp=50"
    )
    spec = {"temperature": {"values": [85], "source": "x"}}
    proj = project(tmp_path, own, {"min": 2.0, "max": 3.0}, spec)
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1
    assert records[0]["details"]["failures"] == [
        "d: at 85 C: ran at 50 C, not 85 C: the deck sets its own temperature"
    ]
    # a temperature the deck sets among its netlist lines yields to the corner's, which comes after it
    yields = DIVIDER.replace("R1 in out 10k", "R1 in out 10k tc1=1m\n.options temp=50")
    proj2 = project(tmp_path / "2", yields, {"min": 2.0, "max": 3.0}, spec)
    code, records = run("sim", proj2, "--out", tmp_path / "o2")
    assert code == 0, records
    # R1 = 10k x (1 + 1e-3 x 58) at 85 C: 5 x 10/(10.58 + 10) = 2.4295; at the deck's own 50 C,
    # 5 x 10/(10.23 + 10) = 2.4716
    span = records[0]["details"]["decks"]["d"]["corners"]["envelope"]["vout"]
    assert span["min"] == pytest.approx(2.4295, abs=1e-4) and span["min_at"] == "85 C"
    assert span["max"] == pytest.approx(2.4716, abs=1e-4) and span["max_at"] == "nominal"


PINNED = """* a diode reference whose diode is held at 27 C
V1 in 0 DC 5
R1 in ref 10k tc1=100u
D1 ref 0 DREF temp=27
.model DREF D(IS=2.52n RS=0.568 N=1.752 EG=1.11 XTI=3)
.control
op
let vout = v(ref)
print vout
.endc
.end
"""


@needs_ngspice
def test_a_part_held_at_its_own_temperature_does_not_pass_for_a_hot_run(tmp_path):
    """ngspice names the circuit's 85 C for the run while the diode stays at 27 C, and the resistor's
    coefficient still moves the output a little: only the deck's text shows the pin. Without the pin
    the reference is 0.4239 V at 85 C, under its 0.5 V bound."""
    spec = {"temperature": {"values": [85], "source": "x"}}
    proj = project(tmp_path, PINNED, {"min": 0.5, "max": 0.6}, spec)
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1
    assert records[0]["details"]["failures"] == [
        "d: D1 is held at its own temperature (temp=), so no temperature corner moves it: remove the "
        "setting, or set the deck's temperature to false in corners.json with why"
    ]
    proj2 = project(tmp_path / "2", PINNED.replace(" temp=27", ""), {"min": 0.5, "max": 0.6}, spec)
    code, records = run("sim", proj2, "--out", tmp_path / "o2")
    assert code == 1
    assert records[0]["details"]["failures"] == ["d:vout=0.4239014 at 85 C not in [0.5, 0.6]"]
    # a deck that says why it runs at one temperature has no temperature corner to fail
    spec = {"decks": {"d": {"temperature": False, "why": "the diode sits in an oven at 27 C"}}}
    proj3 = project(
        tmp_path / "3", PINNED, {"min": 0.5, "max": 0.6}, {**spec, "tolerance": {"R": 0.01, "source": "x"}}
    )
    code, records = run("sim", proj3, "--out", tmp_path / "o3")
    assert code == 0, records


@needs_ngspice
def test_a_value_the_deck_sets_again_moves_with_its_part(tmp_path):
    # R2 becomes 20k before the analysis: 5 x 20/30 = 3.3333. With 1 % parts the worst cases are
    # 5 x 19.8/(10.1 + 19.8) = 3.3110 and 5 x 20.2/(9.9 + 20.2) = 3.3555: the `alter` moved too.
    deck = DIVIDER.replace(".control", ".control\nalter r2 20k")
    proj = project(tmp_path, deck, {"min": 3.2, "max": 3.5}, {"tolerance": {"R": 0.01, "source": "x"}})
    code, records = run("sim", proj, "--out", tmp_path / "o", "--strict")
    assert code == 0, records
    span = records[0]["details"]["decks"]["d"]["corners"]["envelope"]["vout"]
    assert span["min"] == pytest.approx(3.3110, abs=1e-4) and span["max"] == pytest.approx(3.3555, abs=1e-4)


@needs_ngspice
def test_a_corner_run_names_the_parts_it_left_at_their_written_value(tmp_path):
    deck = DIVIDER.replace("R2 out 0 10k\n", "R2 out 0 10k\nRPROBE out 0 10Meg\n")
    proj = project(tmp_path, deck, {"min": 2.4, "max": 2.6}, {"tolerance": {"R": 0.01, "source": "x"}})
    code, records = run("sim", proj, "--out", tmp_path / "o", "--strict")
    assert code == 0, records
    assert records[0]["details"]["decks"]["d"]["corners"]["fixed"] == ["RPROBE"]
    proc = subprocess.run(
        [sys.executable, str(CLI), "sim", proj, "--deck", "d", "--out", tmp_path / "o2"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert "       at its written value in every run: RPROBE\n" in proc.stdout
    # with no tolerance in the file there is no tolerance run to speak of
    write_corners(proj / "sim", {"temperature": {"values": [85], "source": "x"}})
    code, records = run("sim", proj, "--out", tmp_path / "o3")
    assert records[0]["details"]["decks"]["d"]["corners"]["fixed"] == []


@needs_ngspice
def test_what_the_file_cannot_do_is_a_failure_and_what_it_leaves_open_a_warning(tmp_path):
    # a part `parts` names that no deck has; a kind with no tolerance beside board-named elements
    spec = {"tolerance": {"C": 0.2, "parts": {"R99": 0.01}, "source": "x"}}
    proj = project(tmp_path, DIVIDER, {"min": 2.4, "max": 2.6}, spec)
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1
    assert records[0]["details"]["failures"] == ["corners.json: tolerance.parts names R99, which no deck has"]
    assert records[0]["details"]["warnings"] == ["d: no tolerance covers R1, R2"]
    # a line of the file the gate cannot act on
    write_corners(proj / "sim", {"temperature": {"values": [85]}})
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1 and "corners.json: temperature: no source" in records[0]["details"]["failures"][0]


# ------------------------------------------- what 2 reviews of the corners found
#
# Each deck below passed its bound and should not have. The numbers are the circuit's own: computed
# by hand in the comment, then read from a run.

WINDOW = {"min": 2.42, "max": 2.58}
FIVE_PERCENT = {"tolerance": {"R": 0.05, "source": "5 % resistors"}}
SET_AGAIN = """* a divider whose lower resistor is set again before the analysis
V1 in 0 DC 5
R1 in out 10k
R2 out 0 20k
.control
ALTER
op
let vout = v(out)
print vout
.endc
.end
"""


def span_of(records: list[dict], measure: str = "vout") -> dict:
    return records[0]["details"]["decks"]["d"]["corners"]["envelope"][measure]


@needs_ngspice
def test_two_resistors_written_from_one_parameter_reach_their_worst_case(tmp_path):
    # R1 +5 %, R2 -5 %: 5 x 9.5 / (10.5 + 9.5) = 2.375 V; the other way 2.625 V
    deck = DIVIDER.replace("R1 in out 10k", ".param rdiv=10k\nR1 in out {rdiv}").replace(
        "R2 out 0 10k", "R2 out 0 {rdiv}"
    )
    proj = project(tmp_path, deck, WINDOW, FIVE_PERCENT)
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1
    span = span_of(records)
    assert span["min"] == pytest.approx(2.375, abs=1e-6) and span["max"] == pytest.approx(2.625, abs=1e-6)
    assert [v["name"] for v in records[0]["details"]["decks"]["d"]["corners"]["varied"]] == ["R1", "R2"]


@needs_ngspice
@pytest.mark.parametrize(
    "command",
    [
        "alter r2 10k",
        "alter r2 = 10k",
        "alter @r2[resistance] = 10k",
        "alter r2 resistance = 10k",
        "alter r2 10k $ the fitted value",
        "alter r2 10k ; echo done",
    ],
)
def test_a_value_set_again_in_control_moves_in_each_form_ngspice_takes(tmp_path, command):
    """R2 is 20k in the netlist and 10k before the analysis: 2.5 V. A form the reader passes over puts
    R2 back to exactly 10k at every corner; the span is then R1's alone, 2.439 to 2.564 V, inside the
    bound, where the 2 resistors together reach 2.375 and 2.625 V."""
    proj = project(tmp_path, SET_AGAIN.replace("ALTER", command), WINDOW, FIVE_PERCENT)
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1, records
    span = span_of(records)
    assert span["min"] == pytest.approx(2.375, abs=1e-6) and span["max"] == pytest.approx(2.625, abs=1e-6)


@needs_ngspice
def test_alterparam_moves_and_a_value_no_corner_can_scale_fails_the_deck(tmp_path):
    aparam = SET_AGAIN.replace("R2 out 0 20k", ".param rbot=20k\nR2 out 0 {rbot}").replace(
        "ALTER", "alterparam rbot=10k\nreset"
    )
    code, records = run("sim", project(tmp_path, aparam, WINDOW, FIVE_PERCENT), "--out", tmp_path / "o")
    assert code == 1
    assert span_of(records)["min"] == pytest.approx(2.375, abs=1e-6)
    by_variable = SET_AGAIN.replace("ALTER", "let rv = 10k\nalter r2 = $&rv")
    proj = project(tmp_path / "2", by_variable, WINDOW, FIVE_PERCENT)
    code, records = run("sim", proj, "--out", tmp_path / "o2")
    assert code == 1
    assert records[0]["details"]["failures"] == [
        "d: R2 moves and `.control` sets it again with `alter r2 = $&rv`, which a corner cannot scale: "
        "write that value as a number"
    ]


@needs_ngspice
def test_a_supply_named_under_parts_moves_and_a_name_no_corner_moves_fails(tmp_path):
    # 5.5 V x 10.01 / (9.99 + 10.01) = 2.75275 V and 4.5 V x 9.99 / 20 = 2.24775 V
    spec = {"tolerance": {"R": 0.001, "parts": {"V1": 0.1}, "source": "0.1 % resistors, a 10 % supply"}}
    code, records = run("sim", project(tmp_path, DIVIDER, WINDOW, spec), "--out", tmp_path / "o")
    assert code == 1
    span = span_of(records)
    assert (
        span["max"] == pytest.approx(2.75275, abs=1e-6) and span["max_at"] == "R1 -0.1 %, R2 +0.1 %, V1 +10 %"
    )
    assert (
        span["min"] == pytest.approx(2.24775, abs=1e-6) and span["min_at"] == "R1 +0.1 %, R2 -0.1 %, V1 -10 %"
    )
    # a diode is no part a corner can move: the file's line is answered, never passed over
    spec = {"tolerance": {"R": 0.01, "parts": {"D1": 0.1}, "source": "x"}}
    proj = project(tmp_path / "2", PINNED.replace(" temp=27", ""), {"min": 0.4, "max": 0.7}, spec)
    code, records = run("sim", proj, "--out", tmp_path / "o2")
    assert code == 1
    assert records[0]["details"]["failures"] == [
        "d: tolerance.parts names D1, which a corner cannot move: it moves R, C and L elements, V and I "
        "sources with a DC value, and .param"
    ]


@needs_ngspice
def test_a_parameter_on_a_continuation_line_is_in_the_deck(tmp_path):
    deck = DIVIDER.replace("R1 in out 10k", ".param rtop=10k\n+ rbot=10k\nR1 in out {rtop}").replace(
        "R2 out 0 10k", "R2 out 0 {rbot}"
    )
    spec = {"tolerance": {"parts": {"rtop": 0.01, "rbot": 0.01}, "source": "1 % resistors"}}
    code, records = run(
        "sim", project(tmp_path, deck, {"min": 2.3, "max": 2.7}, spec), "--out", tmp_path / "o"
    )
    assert code == 0, records
    # 5 x 10.1 / (9.9 + 10.1) = 2.525 V
    assert span_of(records)["max"] == pytest.approx(2.525, abs=1e-6)
    assert [v["name"] for v in records[0]["details"]["decks"]["d"]["corners"]["varied"]] == ["rtop", "rbot"]


@needs_ngspice
def test_parts_a_corner_does_not_reach_are_named(tmp_path):
    # 2 instances of 1 subcircuit are 2 resistors on the board, and they move together
    twice = DIVIDER.replace("R1 in out 10k\nR2 out 0 10k", "X1 in out half\nX2 out 0 half").replace(
        ".control", ".subckt half a b\nR1 a b 10k\n.ends\n.control"
    )
    code, records = run("sim", project(tmp_path, twice, WINDOW, FIVE_PERCENT), "--out", tmp_path / "o")
    assert code == 0
    assert records[0]["details"]["warnings"] == [
        "d: R1 in .subckt half is 2 parts on the board (X1, X2): a corner moves them together"
    ]
    code, _ = run(
        "sim", project(tmp_path / "s", twice, WINDOW, FIVE_PERCENT), "--out", tmp_path / "os", "--strict"
    )
    assert code == 1
    # a part in a file of the project's own that the deck includes is read by no corner
    included = DIVIDER.replace("R2 out 0 10k", '.include "lower.inc"')
    proj = project(tmp_path / "2", included, WINDOW, FIVE_PERCENT)
    (proj / "sim" / "lower.inc").write_text("R2 out 0 10k\n", encoding="utf-8")
    code, records = run("sim", proj, "--out", tmp_path / "o2")
    assert code == 0
    assert records[0]["details"]["warnings"] == [
        "d: lower.inc holds R2, which no corner moves: a corner reads the deck's own lines. Write those "
        "parts in the deck"
    ]


@needs_ngspice
def test_parts_that_act_only_together_are_found_by_running_every_end(tmp_path):
    """A bridge's imbalance is 0 as written and at most 0.064 V with 1 resistor off. With R1 9.5k, R2
    10.5k, R3 10.5k and R4 9.5k it is |2.625 - 2.375| = 0.25 V. One range at a time never shows it."""
    bridge = DIVIDER.replace(
        "R1 in out 10k\nR2 out 0 10k", "R1 in a 10k\nR2 a 0 10k\nR3 in b 10k\nR4 b 0 10k"
    )
    bridge = bridge.replace("let vout = v(out)", "let vout = abs(v(a) - v(b))")
    code, records = run("sim", project(tmp_path, bridge, {"max": 0.1}, FIVE_PERCENT), "--out", tmp_path / "o")
    assert code == 1
    corners = records[0]["details"]["decks"]["d"]["corners"]
    assert corners["search"] == "every combination of the ends"
    assert corners["envelope"]["vout"]["max"] == pytest.approx(0.25, abs=1e-6)
    assert corners["envelope"]["vout"]["max_at"] in (
        "R1 -5 %, R2 +5 %, R3 +5 %, R4 -5 %",
        "R1 +5 %, R2 -5 %, R3 -5 %, R4 +5 %",
    )


@needs_ngspice
def test_a_measure_that_peaks_inside_a_range_is_closed_in_on(tmp_path):
    """The gain of a series LC at 10 kHz is 0.147 as written, 0.239 with C1 20 % low and 0.072 with it
    20 % high. With C1 13.5 % low the resonance, 1 / (2 pi sqrt(10 mH x 25.33 nF)), is the 10 kHz of
    the test and the gain is 1.0. Neither end shows it; the run closes in from the half-way point."""
    deck = "\n".join(
        [
            "* band-pass gain at 10 kHz",
            "V1 in 0 DC 0 AC 1",
            "LCOIL in m 10m",
            "C1 m out 29.28n",
            "RSER out 0 12.57",
            ".control",
            "ac lin 1 10k 10k",
            "let vout = vm(out)",
            "print vout",
            ".endc",
            ".end",
            "",
        ]
    )
    spec = {"tolerance": {"C": 0.2, "source": "a 20 % capacitor"}}
    code, records = run("sim", project(tmp_path, deck, {"max": 0.5}, spec), "--out", tmp_path / "o")
    assert code == 1
    span = span_of(records)
    assert span["max"] > 0.99 and span["max_at"] == "C1 -13.4375 %"
    assert records[0]["details"]["failures"] == [
        "d:vout=0.9995508 at C1 -13.4375 % (and 7 more corners) not in [None, 0.5]"
    ]


@needs_ngspice
def test_a_deck_with_too_many_ranges_says_its_worst_case_is_a_guess(tmp_path):
    # 7 resistors in a chain: 128 combinations of the ends, past the 64 runs the search spends
    chain = DIVIDER.replace(
        "R1 in out 10k\nR2 out 0 10k",
        "R1 in n1 1k\nR2 n1 n2 1k\nR3 n2 n3 1k\nR4 n3 n4 1k\nR5 n4 n5 1k\nR6 n5 out 1k\nR7 out 0 1k",
    )
    spec = {"tolerance": {"R": 0.01, "source": "x"}}
    code, records = run(
        "sim", project(tmp_path, chain, {"min": 0.6, "max": 0.8}, spec), "--out", tmp_path / "o"
    )
    assert code == 0
    assert records[0]["details"]["warnings"] == [
        "d: 7 ranges move and the worst case is searched 1 range at a time, so 2 parts off together can "
        "hide a miss: name monte_carlo in corners.json"
    ]
    corners = records[0]["details"]["decks"]["d"]["corners"]
    assert corners["search"] == "1 range at a time, then 1 worst case for each bound"
    # a chain runs one way with each part, so the guess is right here: 5 x 0.99 / (6 x 1.01 + 0.99)
    assert corners["envelope"]["vout"]["min"] == pytest.approx(0.7021277, abs=1e-6)
    spec["monte_carlo"] = {"runs": 4, "seed": 1}
    code, records = run(
        "sim", project(tmp_path / "2", chain, {"min": 0.6, "max": 0.8}, spec), "--out", tmp_path / "o2"
    )
    assert code == 0 and records[0]["details"]["warnings"] == []


@needs_ngspice
def test_the_temperature_the_project_names_runs_when_the_deck_sets_another(tmp_path):
    """The deck sets 40 C among its netlist lines, so as written it gives 0.5202 V, under the 0.53 V
    ceiling. The project names 27 C, where the reference is 0.5478 V: that run is made and fails."""
    deck = PINNED.replace(" temp=27", "").replace(".control", ".options temp=40\n.control")
    spec = {"temperature": {"values": [27, 85], "source": "27 to 85 C"}}
    code, records = run("sim", project(tmp_path, deck, {"max": 0.53}, spec), "--out", tmp_path / "o")
    assert code == 1
    assert records[0]["details"]["decks"]["d"]["measures"]["vout"] == pytest.approx(0.520193, abs=1e-6)
    assert records[0]["details"]["failures"] == ["d:vout=0.5477564 at 27 C not in [None, 0.53]"]


def test_monte_carlo_draws_its_temperatures_inside_the_range_the_project_names():
    draws = simcorners.monte_carlo_corners("d", {"runs": 300, "seed": 1}, [60, 85], [])
    assert len(draws) == 300 and all(60 <= c.temp <= 85 for c in draws)
    # a single temperature has no range: the draws run from the deck's own temperature to it
    draws = simcorners.monte_carlo_corners("d", {"runs": 300, "seed": 1}, [85], [], written_at=27.0)
    assert min(c.temp for c in draws) < 30 and all(27 <= c.temp <= 85 for c in draws)


def test_every_end_is_every_combination_until_it_is_too_many():
    parts = two_parts()
    ends = simcorners.every_end([-20, 85], parts)
    # 2 parts, 4 combinations, at the deck's own temperature and at each of the 2 named
    assert len(ends) == 12 and {c.temp for c in ends} == {None, -20, 85}
    assert ends[0].label == "R1 -1 %, R2 -5 %" and ends[-1].label == "85 C, R1 +1 %, R2 +5 %"
    assert ends[3].scale == {"R1": 1.01, "R2": 1.05}
    assert simcorners.every_end([85], []) == []
    seven = [simcorners.Varied(f"R{n}", "R", 0.01, [simcorners.Site(n, 0, 1, 1e3)]) for n in range(1, 8)]
    assert simcorners.every_end([], seven) is None  # 128 runs: past the 64 the search spends
    assert len(simcorners.every_end([], seven[:6])) == 64


def test_a_resonance_is_carried_across_its_span_for_a_deck_that_answers_an_overlap():
    coil = simcorners.Varied("L1", "L", 0.2, [simcorners.Site(1, 0, 1, 1e-5)])
    cap = simcorners.Varied("C1", "C", 0.2, [simcorners.Site(2, 0, 1, 1e-5)])
    other = simcorners.Varied("R1", "R", 0.01, [simcorners.Site(3, 0, 1, 1.0)])
    sweep = simcorners.sweep_corners([coil, cap, other])
    # 0.4 of the value in steps of 0.02: 21 runs with the inductor high and the capacitor stepped,
    # 21 with the capacitor low and the inductor stepped; the resistor stays where it is
    assert len(sweep) == 42 and all("R1" not in c.scale for c in sweep)
    assert sweep[0].scale == pytest.approx({"L1": 1.2, "C1": 0.8})
    assert sweep[20].scale == pytest.approx({"L1": 1.2, "C1": 1.2})
    assert sweep[21].scale == pytest.approx({"C1": 0.8, "L1": 0.8})
    assert sweep[10].label == "L1 +20 %" and sweep[5].label == "L1 +20 %, C1 -10 %"
    assert simcorners.sweep_corners([cap, other]) == []  # nothing resonates without both kinds
