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


# The forms a review found the first reader lost or misread. A source it lost was a source no plan had
# to place, so a deck could drive a resonance and pass.
FORMS = """* every form of a periodic source
V1 a 0 SINE(0 1 2k)
V2 b 0 SIN(0 1 {fsw})
V3 c 0 PULSE(0 1 0 1n 1n {ton} 20u)
V4 d 0 PULSE(0 {vhi} 0 1n 1n 5u 10u)
V5 e 0 PULSE(0 1 0 1n 1n 5u {1/fsw})
V6 f 0 PULSE(0 1 0 1n 1n 5u 10u) ; a comment with PULSE(0 1 0 1n 1n 1u 2u)
V7 g 0 PULSE(0 1 0 1n 1n 5u 40u) $ another with SIN(0 1 9k)
* V8 h 0 PULSE(0 1 0 1n 1n 5u 10u)
V9 i 0 PWL(0 0 1u 1 2u 0) r=0
V10 j 0 PWL(0 0 1u 1 2u 0)
V11 k 0 SFFM(0 1 20k 5 1k)
V12 l 0 AM(1 0 1k 20k 0)
B1 m 0 V=sin(2*3.14159*5k*time)
B2 n 0 V=v(a)*2
I13 0 o PULSE(0 1 0 1n 1n 'ton' 50u)
V14 p 0 dc 0 ac 1 SIN(0 1 3k 0 0)
V15 q 0 PULSE(0 1 0 1n 1n 5u, 25u)
V16 r 0 EXP(0 1 1u 1u 5u 1u)
V17 s 0 DC 5 ; sin 0 1 2k is the tone the next deck will use
V18 t 0 DC 5 $ PULSE(0 1 0 1n 1n 1u 2u) was here
V19 u 0 PULSE(0 {vdd * 1} 0 1n 1n 5u 10u)
V20 w 0 PULSE(0 {max(vdd,3)} 0 1n 1n 5u 10u)
R1 a 0 1k
.end
"""


def test_a_source_is_read_in_every_form_a_deck_writes_it_and_named_when_it_cannot_be():
    found, unread = freqplan.stimuli(FORMS)
    # SINE as SIN; a braced or quoted argument before the period; a comment that holds another
    # stimulus; DC and AC values before the stimulus; a comma between arguments; a braced argument
    # with spaces in it (once read as 3 words: 1000 MHz) and one with parentheses in it (once cut
    # at the inner `)`: 1 event, so no source at all)
    assert [(e, round(hz)) for e, hz in found] == [
        ("V1", 2000),
        ("V3", 50000),
        ("V4", 100000),
        ("V6", 100000),
        ("V7", 25000),
        ("I13", 20000),
        ("V14", 3000),
        ("V15", 40000),
        ("V19", 100000),
        ("V20", 100000),
    ]
    # periodic, and the frequency is no number in the text: a parameter, an expression, a PWL that
    # repeats, SFFM, AM, a B source of `time`
    assert unread == ["V2", "V5", "V9", "V11", "V12", "B1"]
    # not periodic, so neither list holds it: a commented line, a PWL that runs once, a B source
    # that reads no time, a single EXP, and 2 DC sources with a stimulus in their comment
    assert {"V8", "V10", "B2", "V16", "V17", "V18"}.isdisjoint([e for e, _ in found] + unread)


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


def test_the_template_is_refused_until_it_is_written(tmp_path):
    template = ROOT / "templates" / "project" / freqplan.PLAN_FILE
    shutil.copyfile(template, tmp_path / freqplan.PLAN_FILE)
    plan, problems = freqplan.read_plan(tmp_path)
    assert problems == ["sources[1]: no name", "resonances[1]: no name"] and plan.sources == []
    spec = json.loads(template.read_text(encoding="utf-8"))
    spec["sources"][0].update(name="pump", source="its datasheet, table 6.5")
    spec["resonances"][0].update(name="input filter", source="sim/filter.cir")
    plan, problems = plan_of(tmp_path, spec)
    assert problems == [] and (plan.harmonics, plan.guard) == (10, 0.1)
    assert [(s.name, s.low, s.high) for s in plan.sources] == [("pump", 98000.0, 102000.0)]


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


# ------------------------------------------------- what a review of the plan found


def filter_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    shutil.copytree(BOARDS / "pass-lc-filter", proj, ignore=shutil.ignore_patterns("build"))
    return proj


@needs_ngspice
def test_a_resonance_that_meets_the_clock_between_the_ends_of_its_parts_is_found(tmp_path):
    """With 11.3 uF the filter resonates at 15.0 kHz as written, and from 12.4 to 18.7 kHz over its 20 %
    parts. The 16 kHz clock is on the peak where L x C is 0.876 of nominal: between the ends, at none of
    them. A deck that answers an overlap is also run with L stepped against C, and the ripple there is
    the number judged."""
    proj = filter_project(tmp_path)
    sim = proj / "sim"
    for name in ("clock_ripple.cir", "filter.cir"):
        text = (sim / name).read_text(encoding="utf-8")
        assert "C1 rail c1e 10u" in text
        (sim / name).write_text(text.replace("C1 rail c1e 10u", "C1 rail c1e 11.3u"), encoding="utf-8")
    for name in ("ripple.cir", "ripple.expect.json"):
        (sim / name).unlink()
    plan = json.loads((sim / freqplan.PLAN_FILE).read_text(encoding="utf-8"))
    plan["sources"] = [s for s in plan["sources"] if s["name"] == "clock"]
    (sim / freqplan.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
    bound = {"v_pp": {"max": 0.017, "source": "the rail's ripple with the clock on the resonance"}}
    (sim / "clock_ripple.expect.json").write_text(json.dumps(bound), encoding="utf-8")
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1
    decks = records[0]["details"]["decks"]
    corners = decks["clock_ripple"]["corners"]
    # 7.9 mV as written; the 4 combinations of the ends give 2.6 to 13.2 mV, all under the 17 mV bound
    assert decks["clock_ripple"]["measures"]["v_pp"] == pytest.approx(0.007862, abs=1e-6)
    rows = json.loads((tmp_path / "o" / "sim" / "corners" / "clock_ripple" / "runs.json").read_text("utf-8"))
    ends = {r["label"]: r["measures"]["v_pp"] for r in rows if r["label"].count("20 %") == 2}
    assert len(ends) == 4 and max(ends.values()) == pytest.approx(0.013248, abs=1e-6)
    assert corners["search"] == "every combination of the ends, then L stepped against C between them"
    assert corners["swept"] == 38
    assert corners["envelope"]["v_pp"]["max"] == pytest.approx(0.022048, abs=1e-6)
    assert corners["envelope"]["v_pp"]["max_at"] == "L1 +10 %, C1 -20 %"
    assert records[0]["details"]["failures"] == [
        "clock_ripple:v_pp=0.022048 at L1 +10 %, C1 -20 % (and 12 more corners) not in [None, 0.017] "
        "(the rail's ripple with the clock on the resonance)"
    ]
    # the filter's own deck answers no overlap: its corners are the ends alone
    assert decks["filter"]["corners"]["swept"] == 0
    assert decks["filter"]["corners"]["search"] == "every combination of the ends"


PARAM_PERIOD = """* a source whose period is a parameter
.param per=10u
V1 in 0 PULSE(0 5 0 1n 1n 5u {per})
R1 in out 10k
R2 out 0 10k
.control
tran 100n 100u
meas tran vavg avg v(out) from=20u to=100u
print vavg
.endc
.end
"""


@needs_ngspice
def test_a_source_the_gate_cannot_place_is_named_with_and_without_a_plan(tmp_path):
    """A period written as a parameter is a 100 kHz source the reader gets no number from. It is held
    against no resonance, so the run says so: a deck could drive a resonance through it unseen."""
    proj = tmp_path / "proj"
    (proj / "sim").mkdir(parents=True)
    (proj / "sim" / "d.cir").write_text(PARAM_PERIOD, encoding="utf-8")
    bound = {"vavg": {"min": 1.2, "max": 1.3, "source": "half of 2.5 V"}}
    (proj / "sim" / "d.expect.json").write_text(json.dumps(bound), encoding="utf-8")
    unread = (
        "d: V1 is periodic and the deck gives its frequency as no number (a parameter, a PWL that "
        "repeats, an expression of time), so no plan can place it"
    )
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 0
    assert records[0]["details"]["warnings"] == [
        "no sim/corners.json: each deck ran once, at 27 C with every part at its written value",
        unread,
        "no sim/frequency-plan.json: 1 decks drive periodic sources: d (V1)",
    ]
    plan = {
        "sources": [{"name": "pwm", "hz": 100000, "tolerance": 0.01, "source": "the test's premise"}],
        "resonances": [],
    }
    (proj / "sim" / freqplan.PLAN_FILE).write_text(json.dumps(plan), encoding="utf-8")
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 0 and unread in records[0]["details"]["warnings"]
    code, records = run("sim", proj, "--out", tmp_path / "o", "--strict")
    assert code == 1 and unread in records[0]["details"]["failures"]


@needs_ngspice
def test_a_resonance_read_from_a_deck_that_runs_no_corner_fails(tmp_path):
    """A band is a resonance over its parts' tolerances. A deck taken out of the corners gives 1 number,
    and a band drawn from it would be too narrow by the whole tolerance."""
    proj = filter_project(tmp_path)
    corners_file = proj / "sim" / "corners.json"
    spec = json.loads(corners_file.read_text(encoding="utf-8"))
    spec["decks"] = {"filter": {"skip": "an AC characterisation with no design bound"}}
    corners_file.write_text(json.dumps(spec), encoding="utf-8")
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1
    assert records[0]["details"]["failures"] == [
        "frequency plan: resonance input filter is read from filter, which no tolerance moves, so its "
        "band holds no part's tolerance: give the deck its corners in sim/corners.json"
    ]


@needs_ngspice
def test_a_measure_the_plan_reads_must_be_printed_at_every_corner(tmp_path):
    """The band's ends are the least and the greatest of a measure over the corners. A measure the deck
    prints at some corners only has an end nobody saw."""
    proj = filter_project(tmp_path)
    deck = proj / "sim" / "filter.cir"
    text = deck.read_text(encoding="utf-8")
    assert "print z_peak f_peak q_peak" in text
    some = "print z_peak f_peak\nif q_peak > 13\nprint q_peak\nend"
    deck.write_text(text.replace("print z_peak f_peak q_peak", some), encoding="utf-8")
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1
    assert records[0]["details"]["failures"] == [
        "filter: q_peak is not printed at L1 -20 %; L1 -20 %, C1 +20 %: its least and its greatest are "
        "not known"
    ]
