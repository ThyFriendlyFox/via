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
        # `alter` in .control: all three places move; R2, written from the same parameter, adds none
        "R1": ("R", 0.05, [(1, 10e3), (8, 5e3), (11, 2e3)]),
        # a word, not a board reference: moved only because `parts` names it, its `alter` with it
        "RLOAD": ("R", 0.02, [(6, 1e6), (12, 2e6)]),
    }
    assert problems == ["R3 is named in corners.json and its value {2*rtop} is not a number"]
    assert uncovered == []  # C has no tolerance of its own, and C1 moves with cx


def test_an_element_named_like_a_board_part_with_no_tolerance_is_listed():
    varied, problems, uncovered = simcorners.find_varied(DECK, {"C": 0.2, "parts": {}})
    assert [v.name for v in varied] == ["C1"] and problems == []
    assert uncovered == ["R1", "R2", "R3"]  # RLOAD is a word: no board part, so not expected


def test_no_tolerance_moves_nothing():
    assert simcorners.find_varied(DECK, None) == ([], [], [])


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
    assert lines[1] == ".param rtop=10500 cx = 9e-10"
    assert lines[8] == "R1 a b 5250"
    assert lines[2] == "R1 in out {rtop}" and lines[5] == "R3 a b {2*rtop}"  # the rest is as written
    assert lines[10:12] == [".options temp=-20", ".control"]
    # the part is as far off its value in the analyses after the deck sets it again
    assert lines[12] == "alter r1 2100"
    # an element this corner does not move, and a source, stay as written
    assert lines[13:15] == ["alter rload = 2Meg", "alter v1 dc=4.2"]
    assert len(lines) == len(DECK.split("\n")) + 1


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
        ("R1-", "tolerance", "R1 -1 %", None, {"R1": 0.99}),
        ("R1+", "tolerance", "R1 +1 %", None, {"R1": 1.01}),
        ("R2-", "tolerance", "R2 -5 %", None, {"R2": 0.95}),
        ("R2+", "tolerance", "R2 +5 %", None, {"R2": 1.05}),
    ]


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
    # 2 temperatures, R1, R2 and C1 at both ends, the 2 worst cases of vout, 8 Monte Carlo draws
    assert records[0]["summary"] == "1 decks, 18 corner runs, 0 failures"
    assert records[0]["details"]["corners"] == {"runs": 18, "nominal_only": False}
    deck = records[0]["details"]["decks"]["rc_divider"]
    corners = deck["corners"]
    assert corners["temperatures"] == [-40.0, 85.0] and corners["uncovered"] == []
    assert [(v["name"], v["tolerance"]) for v in corners["varied"]] == [
        ("R1", 0.01),
        ("R2", 0.01),
        ("C1", 0.1),
    ]
    # R1 = 10k x 1.01 x (1 + 100e-6 x 58), R2 = 10k x 0.99 x (1 - 100e-6 x 58): 5 R2/(R1 + R2) = 2.4605;
    # cold with the parts the other way, 67 K under 27 C: 2.5417
    span = corners["envelope"]["vout"]
    assert span["min"] == pytest.approx(2.4605, abs=1e-4) and span["min_at"] == "85 C, R1 +1 %, R2 -1 %"
    assert span["max"] == pytest.approx(2.5417, abs=1e-4) and span["max_at"] == "-40 C, R1 -1 %, R2 +1 %"
    assert deck["checks"]["vout"]["ok"] is True and deck["checks"]["vout"]["held"] is True
    assert corners["monte_carlo"]["statistics"]["vout"]["runs"] == 8
    # what it writes: a folder per corner with its own deck and log, and every run's measures
    folder = tmp_path / "sim" / "corners" / "rc_divider"
    assert corners["folder"] == str(folder)
    assert sorted(p.name for p in folder.iterdir() if p.is_dir())[:4] == ["C1+", "C1-", "R1+", "R1-"]
    assert "R1 in out 10100 tc1=100u" in (folder / "w1" / "rc_divider.cir").read_text(encoding="utf-8")
    assert (folder / "t85" / "ngspice.log").is_file()
    rows = json.loads((folder / "runs.json").read_text(encoding="utf-8"))
    assert len(rows) == 18 and {r["kind"] for r in rows} == {
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
        "diode_ref:vref=0.4215933 at 85 C, R1 +5 % (and 3 more corners) not in [0.5, 0.6] "
        "(the fixture's reference window, 0.55 V within 0.05 V)"
    )
    # 5 x 9.5/(10.5 + 9.5) = 2.375 and 5 x 10.5/(9.5 + 10.5) = 2.625 are as far out as each other
    worst = r"divider:vout=2\.[36]\d+ at R1 [+-]5 %, R2 [+-]5 % \(and 5 more corners\) "
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
