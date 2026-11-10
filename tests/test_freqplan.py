"""A project's frequency plan (tools/freqplan.py, `sim/frequency-plan.json`).

The first half needs no engine: reading the plan, reading a deck's periodic stimuli, and judging the
plan against a run's measures. The second half runs the gate on the fixtures `pass-lc-filter` (a
switching load clear of its filter's resonance) and `fail-freq-overlap` (the same filter with the
load's third harmonic on the resonance); those tests skip when ngspice is absent.
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
import freqplan  # noqa: E402

needs_ngspice = pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice is not installed")

# Every way a deck writes a source: a node called `sin`, a SIN, a PULSE with and without a period, a
# period written as a parameter, a PULSE without parentheses continued on a second line, and an
# `alter` in .control, which is not a netlist line.
DECK = """* stimuli
V1 sin 0 DC 1
V2 a 0 SIN(0 1 1k)
V3 b 0 PULSE(0 1 0 1n 1n 5u 10u)
V4 c 0 PULSE(0 1 0 1n 1n 5u)
V5 d 0 PULSE(0 1 0 1n 1n {ton} {per})
I6 0 e pulse 0 1 0 1n 1n
+ 1u 2u
R1 a 0 1k
.control
alter @v3[pulse] = [ 0 1 0 1n 1n 1u 2u ]
.endc
.end
"""

PLAN = {
    "sources": [
        {"name": "keep-alive", "hz": 100000, "tolerance": 0.01, "source": "config.h LH_KEEPALIVE_HZ"},
        {"name": "heater PWM", "hz": 1000, "tolerance": 0.01, "source": "config.h LH_PWM_HZ"},
        {"name": "I2C clock", "hz": [100000, 400000], "source": "UM10204 Table 10"},
    ],
    "resonances": [
        {"name": "strips with C5", "hz": "pdn.f_peak", "q": "pdn.q_peak", "source": "sim/pdn.cir"}
    ],
}
# The resonance over its deck's corners: 420 to 450 kHz, Q 1.6 at the least. 1/(2 x 1.6) = 0.3125 is
# wider than the 0.1 guard, so the band is 420k x 0.6875 = 288.75 kHz to 450k x 1.3125 = 590.625 kHz.
VALUES = {"pdn.f_peak": (420e3, 450e3), "pdn.q_peak": (1.6, 1.7)}


def run(*args: object) -> tuple[int, list[dict]]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", *map(str, args)], capture_output=True, text=True, check=False
    )
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else [])


def plan_of(tmp_path: Path, spec: dict) -> tuple[freqplan.Plan, list[str]]:
    (tmp_path / freqplan.PLAN_FILE).write_text(json.dumps(spec), encoding="utf-8")
    return freqplan.read_plan(tmp_path)


# ------------------------------------------------------------- no engine


def test_a_decks_periodic_stimuli_are_read_and_a_single_event_is_not():
    found, unread = freqplan.stimuli(DECK)
    assert [(e, round(hz)) for e, hz in found] == [("V2", 1000), ("V3", 100000), ("I6", 500000)]
    assert unread == ["V5"]  # its period is a parameter: named, so it is not passed over in silence


def test_a_project_without_the_file_has_no_plan(tmp_path):
    assert freqplan.read_plan(tmp_path) == (None, [])


def test_the_plan_is_read_with_its_defaults(tmp_path):
    plan, problems = plan_of(tmp_path, PLAN)
    assert problems == []
    assert [(s.name, s.low, s.high) for s in plan.sources] == [
        ("keep-alive", 99000.0, 101000.0),
        ("heater PWM", 990.0, 1010.0),
        ("I2C clock", 100000.0, 400000.0),
    ]
    assert [(r.name, r.hz, r.q) for r in plan.resonances] == [("strips with C5", "pdn.f_peak", "pdn.q_peak")]
    assert (plan.harmonics, plan.guard, plan.overlaps) == (10, 0.1, [])


@pytest.mark.parametrize(
    ("change", "said"),
    [
        ({"sorces": []}, "unknown key 'sorces'"),
        ({"sources": [{"name": "a", "hz": 0, "source": "x"}]}, "hz 0 is not a frequency"),
        (
            {"sources": [{"name": "a", "hz": [5, 1], "source": "x"}]},
            "is not a frequency in Hz or a [low, high]",
        ),
        ({"sources": [{"name": "a", "hz": 1000}]}, "no source"),
        ({"sources": [{"hz": 1000, "source": "x"}]}, "sources[1]: no name"),
        (
            {"sources": [{"name": "a", "hz": 1, "source": "x"}, {"name": "a", "hz": 2, "source": "x"}]},
            "the name 'a' is used twice",
        ),
        (
            {"sources": [{"name": "a", "hz": 1000, "tolerance": 2, "source": "x"}]},
            "tolerance 2 is not a fraction",
        ),
        ({"sources": [{"name": "a", "hz": [1, 2], "tolerance": 0.1, "source": "x"}]}, "a range has its ends"),
        ({"sources": []}, "names no source"),
        (
            {"resonances": [{"name": "r", "hz": "f_peak", "source": "x"}]},
            "is not a frequency in Hz or a deck.measure",
        ),
        ({"resonances": [{"name": "r", "hz": 1e5, "q": 0, "source": "x"}]}, "q 0 is not a number above 0"),
        ({"harmonics": 0}, "harmonics: 0 is not a count"),
        ({"guard": 1.5}, "guard: 1.5 is not a fraction"),
        (
            {"overlaps": [{"between": ["keep-alive"], "evidence": "d.m", "why": "x"}]},
            "between is not two names",
        ),
        (
            {"overlaps": [{"between": ["keep-alive", "nobody"], "evidence": "d.m", "why": "x"}]},
            "nobody is not a source or a resonance",
        ),
        (
            {"overlaps": [{"between": ["keep-alive", "I2C clock"], "evidence": "ripple", "why": "x"}]},
            "evidence 'ripple' is not a deck.measure",
        ),
        (
            {"overlaps": [{"between": ["keep-alive", "I2C clock"], "evidence": "d.m", "why": "x"}]},
            "no stimulus: the deck's element that runs each source",
        ),
        (
            {
                "overlaps": [
                    {"between": ["keep-alive", "I2C clock"], "evidence": "d.m", "stimulus": "IKA", "why": "x"}
                ]
            },
            "1 stimulus for 2 source: one element for each of keep-alive, I2C clock",
        ),
        (
            {
                "overlaps": [
                    {
                        "between": ["keep-alive", "strips with C5"],
                        "evidence": "d.m",
                        "stimulus": ["A", "B"],
                        "why": "x",
                    }
                ]
            },
            "2 stimulus for 1 source: one element for each of keep-alive",
        ),
        (
            {
                "overlaps": [
                    {"between": ["keep-alive", "I2C clock"], "evidence": "d.m", "stimulus": ["IKA", "ICLK"]}
                ]
            },
            "no why",
        ),
    ],
)
def test_every_line_of_the_plan_the_gate_cannot_act_on_is_named(tmp_path, change, said):
    _, problems = plan_of(tmp_path, {**PLAN, **change})
    assert any(said in p for p in problems), problems


def test_a_plan_that_is_not_json_is_one_problem(tmp_path):
    (tmp_path / freqplan.PLAN_FILE).write_text("[", encoding="utf-8")
    _, problems = freqplan.read_plan(tmp_path)
    assert len(problems) == 1 and "not JSON" in problems[0]


def test_a_harmonic_in_a_resonances_band_and_two_sources_at_one_frequency_are_found(tmp_path):
    plan, _ = plan_of(tmp_path, PLAN)
    result = freqplan.check_plan(plan, VALUES, set(), {})
    assert result["bands"] == [
        {"name": "strips with C5", "hz": [420e3, 450e3], "q": 1.6, "band": [288750.0, 590625.0]}
    ]
    band = "the band of strips with C5 (288.8 kHz to 590.6 kHz)"
    assert result["overlaps"] == [
        f"I2C clock's frequency (100 kHz to 400 kHz) is in {band}",
        # the clock's range starts at 100 kHz, inside the keep-alive's 99 to 101 kHz
        "keep-alive (99 kHz to 101 kHz) and I2C clock (100 kHz to 400 kHz) can run at one frequency",
        # 3 x 99 to 101 kHz is the first of the keep-alive's harmonics past 288.75 kHz
        f"keep-alive's harmonic 3 (297 kHz to 303 kHz) is in {band}",
    ]
    # The heater's tenth harmonic ends at 10.1 kHz: it reaches no band. Its 100th harmonic is the
    # keep-alive's frequency, and that is no overlap: only two frequencies that can be one are.
    assert not any("heater PWM" in o for o in result["overlaps"])
    assert result["failures"] == [
        f"{o}: no overlap answers it with a deck that drives it" for o in result["overlaps"]
    ]
    assert result["warnings"] == []


def test_the_band_is_the_wider_of_the_guard_and_the_q_and_a_number_needs_no_deck(tmp_path):
    spec = {**PLAN, "resonances": [{"name": "r", "hz": 400e3, "q": 20, "source": "a bench sweep"}]}
    plan, problems = plan_of(tmp_path, spec)
    assert problems == []
    # 1/(2 x 20) = 0.025 is under the 0.1 guard: 360 to 440 kHz, which the keep-alive's 4th harmonic is in
    result = freqplan.check_plan(plan, {}, set(), {})
    assert result["bands"][0]["band"] == [pytest.approx(360e3), pytest.approx(440e3)]
    assert any("keep-alive's harmonic 4" in o for o in result["overlaps"])
    # fewer harmonics, and the keep-alive no longer reaches the band
    plan.harmonics = 3
    assert not any("keep-alive's harmonic" in o for o in freqplan.check_plan(plan, {}, set(), {})["overlaps"])


BOUNDED = {"ripple.v_pp", "ripple.v_i2c", "both.v_pp"}
# ripple.cir runs the keep-alive from IKA at 100 kHz (its 3rd harmonic, 300 kHz, is in the band) and the
# I2C clock from ICLK at 400 kHz (in the band itself); both.cir runs the two at one frequency.
GOOD = {"ripple": [("IKA", 100e3), ("ICLK", 400e3)], "both": [("IKA", 100e3), ("ICLK", 100e3)]}


def answered(tmp_path: Path, stimuli: dict, bounded: set[str], values: dict | None = None) -> list[str]:
    spec = {
        **PLAN,
        "overlaps": [
            {
                "between": ["keep-alive", "strips with C5"],
                "evidence": "ripple.v_pp",
                "stimulus": "IKA",
                "why": "4 mV",
            },
            {
                "between": ["strips with C5", "I2C clock"],
                "evidence": "ripple.v_i2c",
                "stimulus": "iclk",
                "why": "1 mV",
            },
            {
                "between": ["keep-alive", "I2C clock"],
                "evidence": "both.v_pp",
                "stimulus": ["IKA", "ICLK"],
                "why": "5 mV",
            },
        ],
    }
    plan, problems = plan_of(tmp_path, spec)
    assert problems == []
    measured = {
        **VALUES,
        "ripple.v_pp": (0.004, 0.005),
        "ripple.v_i2c": (0.001, 0.001),
        "both.v_pp": (0.005, 0.005),
    }
    return freqplan.check_plan(plan, measured if values is None else values, bounded, stimuli)["failures"]


def test_an_overlap_is_answered_by_a_bounded_measure_of_a_deck_that_drives_it(tmp_path):
    assert answered(tmp_path, GOOD, BOUNDED) == []
    # the I2C clock anywhere in its range with a harmonic in the band: 150 kHz x 2 = 300 kHz
    assert answered(tmp_path, {**GOOD, "ripple": [("IKA", 100e3), ("ICLK", 150e3)]}, BOUNDED) == []
    # two sources within 1 % of each other run at one frequency
    assert answered(tmp_path, {**GOOD, "both": [("IKA", 100e3), ("ICLK", 100.9e3)]}, BOUNDED) == []


def test_an_answer_whose_measure_holds_nothing_fails(tmp_path):
    # the measure has no bound: nothing holds the result to a limit
    assert answered(tmp_path, GOOD, BOUNDED - {"ripple.v_pp"}) == [
        "overlap keep-alive and strips with C5: ripple.v_pp has no bound in its expect file"
    ]
    # the deck does not print the measure
    without = {**VALUES, "ripple.v_i2c": (0.001, 0.001), "both.v_pp": (0.005, 0.005)}
    assert answered(tmp_path, GOOD, BOUNDED, without) == [
        "overlap keep-alive and strips with C5: ripple.v_pp is not measured by its deck"
    ]


def test_an_answer_whose_deck_does_not_drive_the_overlap_fails(tmp_path):
    # the named element is not a periodic stimulus of the deck
    assert answered(tmp_path, {**GOOD, "ripple": [("IKA", 100e3)]}, BOUNDED) == [
        "overlap strips with C5 and I2C clock: sim/ripple.cir has no periodic stimulus iclk"
    ]
    # it runs outside its source's range: the keep-alive's own element cannot stand in for the clock
    assert answered(tmp_path, {**GOOD, "ripple": [("IKA", 100e3), ("ICLK", 50e3)]}, BOUNDED) == [
        "overlap strips with C5 and I2C clock: iclk runs at 50 kHz, outside I2C clock (100 kHz to 400 kHz)",
        "sim/ripple.cir drives ICLK at 50 kHz, which the plan does not name",
    ]
    # two sources, each inside its own range, and apart: the deck does not drive them together.
    # 300 kHz is the keep-alive's 3rd harmonic, and a harmonic is not the frequency.
    assert answered(tmp_path, {**GOOD, "both": [("IKA", 100e3), ("ICLK", 300e3)]}, BOUNDED) == [
        "overlap keep-alive and I2C clock: IKA at 100 kHz and ICLK at 300 kHz do not run at one frequency"
    ]
    # two sources, and the deck runs one of them
    assert answered(tmp_path, {**GOOD, "both": [("IKA", 100e3)]}, BOUNDED) == [
        "overlap keep-alive and I2C clock: sim/both.cir has no periodic stimulus ICLK"
    ]


def test_a_source_run_with_no_harmonic_in_the_band_does_not_drive_it(tmp_path):
    # A pump anywhere from 140 to 160 kHz, and a 300 kHz resonance with Q 100 and a 0.01 guard: its band
    # is 297 to 303 kHz. The pump's 2nd harmonic spans 280 to 320 kHz, so the two overlap. A deck that
    # runs the pump at 150 kHz puts the harmonic at 300 kHz, in the band; one that runs it at 141 kHz
    # puts its harmonics at 282 and 423 kHz, clear of the band, and proves nothing about the overlap.
    spec = {
        "sources": [{"name": "pump", "hz": [140e3, 160e3], "source": "its datasheet"}],
        "resonances": [{"name": "filter", "hz": 300e3, "q": 100, "source": "a bench sweep"}],
        "harmonics": 3,
        "guard": 0.01,
        "overlaps": [{"between": ["pump", "filter"], "evidence": "d.v", "stimulus": "IP", "why": "x"}],
    }
    plan, problems = plan_of(tmp_path, spec)
    assert problems == []
    values, bounded = {"d.v": (1.0, 1.0)}, {"d.v"}
    assert freqplan.check_plan(plan, values, bounded, {"d": [("IP", 150e3)]})["failures"] == []
    assert freqplan.check_plan(plan, values, bounded, {"d": [("IP", 141e3)]})["failures"] == [
        "overlap pump and filter: IP at 141 kHz has no harmonic in the band (297 kHz to 303 kHz)"
    ]
    # one element cannot run two sources
    two = {
        "sources": [
            {"name": "a", "hz": 100e3, "source": "x"},
            {"name": "b", "hz": 100e3, "source": "x"},
        ],
        "overlaps": [{"between": ["a", "b"], "evidence": "d.v", "stimulus": ["I1", "i1"], "why": "x"}],
    }
    plan, problems = plan_of(tmp_path, two)
    assert problems == []
    assert freqplan.check_plan(plan, values, bounded, {"d": [("I1", 100e3)]})["failures"] == [
        "overlap a and b: one element, I1, cannot run both sources"
    ]


def test_an_answer_to_an_overlap_that_is_gone_fails(tmp_path):
    spec = {
        "sources": [{"name": "heater PWM", "hz": 1000, "source": "config.h"}],
        "resonances": PLAN["resonances"],
        "overlaps": [
            {
                "between": ["heater PWM", "strips with C5"],
                "evidence": "ripple.v_pp",
                "stimulus": "V1",
                "why": "x",
            }
        ],
    }
    plan, problems = plan_of(tmp_path, spec)
    assert problems == []
    result = freqplan.check_plan(plan, {**VALUES, "ripple.v_pp": (1, 1)}, {"ripple.v_pp"}, {})
    assert result["failures"] == [
        "overlap heater PWM and strips with C5: the run shows none; remove the answer"
    ]


def test_a_resonance_no_deck_measures_fails_and_a_plan_without_one_warns(tmp_path):
    plan, _ = plan_of(tmp_path, PLAN)
    result = freqplan.check_plan(plan, {"pdn.q_peak": (1.6, 1.7)}, set(), {})
    assert "resonance strips with C5: pdn.f_peak is not measured by its deck" in result["failures"]
    assert result["bands"] == []
    bare, problems = plan_of(tmp_path, {"sources": PLAN["sources"][1:2]})
    assert problems == []
    result = freqplan.check_plan(bare, {}, set(), {"heater": [("VPWM", 1000.0)]})
    assert result["failures"] == []
    assert result["warnings"] == [
        "frequency-plan.json names no resonance: no deck has looked for one with an .ac analysis"
    ]


def test_a_decks_stimulus_the_plan_does_not_name_fails(tmp_path):
    plan, _ = plan_of(tmp_path, {"sources": PLAN["sources"][1:2], "resonances": []})
    stimuli = {"heater": [("VPWM", 1000.5)], "odd": [("V9", 7777.0)]}  # 1000.5 Hz is inside 990 to 1010
    assert freqplan.check_plan(plan, {}, set(), stimuli)["failures"] == [
        "sim/odd.cir drives V9 at 7.777 kHz, which the plan does not name"
    ]


# ------------------------------------------------------------- the gate


@needs_ngspice
def test_a_load_clear_of_the_filters_resonance_and_an_answered_overlap_pass_even_strict(tmp_path):
    code, records = run("sim", BOARDS / "pass-lc-filter", "--out", tmp_path, "--strict")
    assert code == 0, records
    judged = records[0]["details"]["frequency_plan"]
    assert [(s["name"], s["hz"]) for s in judged["sources"]] == [
        ("load", [99000.0, 101000.0]),
        ("clock", [15840.0, 16160.0]),
    ]
    # 1/(2 pi sqrt(10 uH x 10 uF)) = 15.9 kHz; with both parts 20 % high or low, 13.3 and 19.9 kHz.
    # The plan reads the resonance at every corner, both ends looked for though no bound asks.
    (band,) = judged["bands"]
    assert band["name"] == "input filter"
    assert band["hz"][0] == pytest.approx(15915 / 1.2, rel=0.01) and band["hz"][1] == pytest.approx(
        15915 / 0.8, rel=0.01
    )
    assert band["band"][0] == pytest.approx(0.9 * band["hz"][0]) and band["band"][1] == pytest.approx(
        1.1 * band["hz"][1]
    )
    # the clock sits in the band, and sim/clock_ripple.cir answers it; the load's harmonics start at 99 kHz
    (overlap,) = judged["overlaps"]
    assert overlap.startswith("clock's frequency (15.84 kHz to 16.16 kHz) is in the band of input filter (")
    assert "failures" not in judged and "warnings" not in judged


@needs_ngspice
def test_a_harmonic_on_the_resonance_fails_though_every_bound_holds(tmp_path):
    code, records = run("sim", BOARDS / "fail-freq-overlap", "--out", tmp_path)
    assert code == 1
    decks = records[0]["details"]["decks"]
    # the rail swings 6.8 V on a 5 V supply while its average, the one thing bounded, stays at 4.98 V
    assert decks["load"]["measures"]["v_pp"] == pytest.approx(6.78, abs=0.05)
    assert decks["load"]["checks"]["v_avg"]["ok"] is True and decks["load"]["checks"]["v_avg"]["held"] is True
    (failure,) = records[0]["details"]["failures"]
    assert re.fullmatch(
        r"frequency plan: load's harmonic 3 \(15\.74 kHz to 16\.06 kHz\) is in the band of input filter "
        r"\(1[12]\.\d+ kHz to 2[12]\.\d+ kHz\): no overlap answers it with a deck that drives it",
        failure,
    ), failure


@needs_ngspice
def test_decks_that_drive_periodic_sources_ask_for_a_plan(tmp_path):
    proj = tmp_path / "proj"
    shutil.copytree(BOARDS / "fail-freq-overlap", proj, ignore=shutil.ignore_patterns("build"))
    (proj / "sim" / freqplan.PLAN_FILE).unlink()
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 0 and records[0]["details"]["frequency_plan"] is None
    assert records[0]["details"]["warnings"] == [
        "no sim/frequency-plan.json: 1 decks drive periodic sources: load (ILOAD)"
    ]
    code, records = run("sim", proj, "--out", tmp_path / "o", "--strict")
    assert code == 1
    # one deck alone does not judge the plan: it needs every deck's measures
    code, records = run("sim", BOARDS / "fail-freq-overlap", "--out", tmp_path / "o2", "--deck", "load")
    assert code == 0 and records[0]["details"]["frequency_plan"] is None


@needs_ngspice
def test_a_plan_the_gate_cannot_read_or_whose_resonance_no_deck_measures_fails(tmp_path):
    proj = tmp_path / "proj"
    shutil.copytree(BOARDS / "pass-lc-filter", proj, ignore=shutil.ignore_patterns("build"))
    plan_file = proj / "sim" / freqplan.PLAN_FILE
    spec = json.loads(plan_file.read_text(encoding="utf-8"))
    spec["resonances"][0]["hz"] = "filter.f_top"
    plan_file.write_text(json.dumps(spec), encoding="utf-8")
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1
    failures = records[0]["details"]["failures"]
    assert "frequency plan: resonance input filter: filter.f_top is not measured by its deck" in failures
    # with no band, the answer in the plan answers nothing
    assert "frequency plan: overlap clock and input filter: the run shows none; remove the answer" in failures
    spec["sources"][0].pop("source")
    plan_file.write_text(json.dumps(spec), encoding="utf-8")
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1 and records[0]["details"]["frequency_plan"] is None
    assert any(
        f.startswith("frequency-plan.json: sources[1] (load): no source")
        for f in records[0]["details"]["failures"]
    )
