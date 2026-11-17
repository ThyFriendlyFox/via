"""`workcenter measure`: for each bound of each deck, the pad to probe, the instrument and the span
the reading must fall in (tools/measureplan.py).

The pure tests read the deck of pass-first-design as text. The command's tests run it on a copy of
that fixture: its deck predicts vout = 2.5 V (10k over 10k on 5 V) and f3 = 1 / (2 pi x 5k x 100n) =
318.3 Hz, and its expect file holds them to 2.45 to 2.55 and 250 to 400.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import engine

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
FIXTURE = ROOT / "tests" / "boards" / "pass-first-design"
DECK = (FIXTURE / "sim" / "divider.cir").read_text(encoding="utf-8")
sys.path.insert(0, str(ROOT / "tools"))
import measureplan  # noqa: E402

needs_engines = engine(
    pytest.mark.skipif(
        shutil.which("kicad-cli") is None or shutil.which("ngspice") is None,
        reason="kicad-cli or ngspice absent",
    )
)
# The pads of pass-first-design's board, net by net, as its divider.kicad_pcb lists them.
NETS = {
    "VCC": ["J1 pad 1", "R1 pad 1"],
    "/OUT": ["J1 pad 2", "R1 pad 2", "R2 pad 1", "C1 pad 1"],
    "GND": ["J1 pad 3", "R2 pad 2", "C1 pad 2"],
}


def test_each_measure_of_the_deck_is_read_with_its_analysis_quantity_and_node():
    got = measureplan.measures(DECK)
    assert got == {
        "vout": {
            "analysis": "op",
            "quantity": "voltage",
            "unit": "V",
            "nodes": ["out"],
            "reads": "v(out)",
            "conditions": [],
        },
        "f3": {
            "analysis": "ac",
            "quantity": "frequency",
            "unit": "Hz",
            "nodes": ["out"],
            "reads": "vm(out)",
            "conditions": [],
        },
    }


def test_a_measure_of_a_current_names_no_node():
    got = measureplan.measures("V1 a 0 DC 5\nR1 a 0 1k\n.control\nop\nlet iin = -i(v1)\n.endc\n")
    assert got == {
        "iin": {
            "analysis": "op",
            "quantity": "current",
            "unit": "A",
            "nodes": [],
            "reads": "i(v1)",
            "conditions": [],
        }
    }


def test_a_let_that_scales_a_measure_reads_what_that_measure_reads_in_no_named_unit():
    """Last Hit's master_switch deck writes `let t_trip_us = (t_trip - 37e-3) * 1e6` after a `meas`:
    the same crossing, in microseconds, which the plan does not name."""
    deck = ".control\ntran 1u 1m\nmeas tran t_x when v(out)=1.0 fall=1\nlet t_x_us = t_x * 1e6\n.endc\n"
    got = measureplan.measures(deck)["t_x_us"]
    assert got == {
        "analysis": "tran",
        "quantity": "time",
        "unit": "",
        "nodes": ["out"],
        "reads": "t_x * 1e6",
        "conditions": [],
    }


def plan(deck: str, name: str, bound: dict) -> dict:
    return measureplan.plan_rows("d", measureplan.measures(deck), {name: bound}, {}, NETS)[0]


def test_a_difference_of_2_node_voltages_is_probed_at_the_first_against_the_second():
    """`let vdrop = v(vcc) - v(out)` reads VCC against /OUT, not VCC against ground: on the divider of
    5 V over 10k and 10k that is 5 - 2.5 = 2.5 V, where a meter to ground would read 5 V. Last Hit
    v0.16's display_vbat.cir writes `let vgs_off = v(dbatt) - v(vg)`."""
    row = plan(".control\nop\nlet vdrop = v(vcc) - v(out)\n.endc\n", "vdrop", {"min": 2.4, "max": 2.6})
    assert (row["planned"], row["probe"], row["reference"], row["unit"]) == (
        True,
        "J1 pad 1 (VCC)",
        "J1 pad 2 (/OUT)",
        "V",
    )


def test_a_product_of_vectors_is_not_planned_and_says_why():
    """A power, v times i, is no voltage: a voltmeter at VCC would read 5 V against a bound of 2 mW."""
    row = plan(".control\nop\nlet p = v(vcc) * -i(v1)\n.endc\n", "p", {"max": 0.002})
    assert (row["planned"], row["why"]) == (False, "the plan cannot read v(vcc) * -i(v1)")


def test_a_square_of_1_vector_is_not_planned_and_says_why():
    """Last Hit v0.16's heater_pulse.cir:188 writes `let pcoil = v(o4) * v(o4) / 1.2`."""
    row = plan(".control\nop\nlet pcoil = v(out) * v(out) / 1.2\n.endc\n", "pcoil", {"max": 6})
    assert (row["planned"], row["why"]) == (False, "the plan cannot read v(out) * v(out) / 1.2")


def test_a_function_of_a_vector_is_not_planned_and_says_why():
    row = plan(".control\nac dec 10 1 1k\nlet g = db(v(out))\n.endc\n", "g", {"min": -3})
    assert (row["planned"], row["why"]) == (False, "the plan cannot read db(v(out))")


def test_a_ratio_of_2_measures_is_not_planned_and_says_why():
    deck = ".control\nop\nlet vout = v(out)\nlet vin = v(in)\nlet gain = vout / vin\n.endc\n"
    row = plan(deck, "gain", {"min": 2.0, "max": 2.2})
    assert (row["planned"], row["why"]) == (False, "the plan cannot read vout / vin")


def test_a_measure_divided_by_a_constant_is_planned_in_no_named_unit():
    row = plan(".control\nop\nlet vout = v(out)\nlet half = vout / 2\n.endc\n", "half", {"max": 1.3})
    assert (row["planned"], row["probe"], row["unit"]) == (True, "J1 pad 2 (/OUT)", "")


def test_a_meas_over_a_let_vector_reads_what_the_let_reads():
    """Last Hit v0.16's heater_pulse.cir:98 and :103: `let vds = v(hs) - v(out)`, then
    `meas tran vds_max max vds`. Here VCC against /OUT."""
    deck = ".control\ntran 1u 1m\nlet vds = v(vcc) - v(out)\nmeas tran vds_max max vds from=50u\n.endc\n"
    row = plan(deck, "vds_max", {"max": 3})
    assert (row["planned"], row["probe"], row["reference"], row["instrument"]) == (
        True,
        "J1 pad 1 (VCC)",
        "J1 pad 2 (/OUT)",
        "oscilloscope",
    )


def test_a_meas_over_a_let_vector_the_plan_cannot_read_says_so():
    deck = ".control\ntran 1u 1m\nlet pq = v(vcc) * i(v1)\nmeas tran p_avg avg pq from=1u to=1m\n.endc\n"
    row = plan(deck, "p_avg", {"max": 1})
    assert row["why"] == "it is a meas over the let vector pq, and the plan cannot read v(vcc) * i(v1)"


def test_a_measure_taken_after_an_alter_names_the_alter_lines_in_effect():
    """Last Hit v0.16's vbus_hotplug.cir measures hp_typical as written, then hp_worst after 4 alter
    lines; a later alter of the same element replaces the earlier one."""
    deck = (
        "VS src 0 PWL(0 0 10n 5.0)\nLC src out 0.75u\n.control\ntran 2n 40u\n"
        "meas tran hp_typical max v(out)\nalter VS pwl = [ 0 0 10n 5.0 ]\nalter LC 1u\n"
        "alter VS pwl = [ 0 0 10n 5.5 ]\ntran 2n 40u\n"
        "meas tran hp_worst max v(out)\n.endc\n"
    )
    got = measureplan.measures(deck)
    assert got["hp_typical"]["conditions"] == []
    assert got["hp_worst"]["conditions"] == ["alter LC 1u", "alter VS pwl = [ 0 0 10n 5.5 ]"]
    rows = measureplan.plan_rows("d", got, {"hp_worst": {"max": 7.0}}, {}, NETS)
    md = measureplan.markdown("p", rows, [], "PASS")
    assert "| d | hp_worst | `alter LC 1u`; `alter VS pwl = [ 0 0 10n 5.5 ]` | J1 pad 2 (/OUT) |" in md


def test_a_crossing_of_a_current_is_not_planned_and_says_why():
    deck = ".control\ntran 1u 1m\nmeas tran t_trip when i(vic)=1.0 fall=1\n.endc\n"
    rows = measureplan.plan_rows("d", measureplan.measures(deck), {"t_trip": {"max": 1e-3}}, {}, NETS)
    assert rows[0]["why"] == (
        "it reads i(vic), a current: an ammeter goes in series, and the board names no place to open"
    )


def test_a_dc_sweep_crossing_is_read_on_an_adjustable_supply():
    deck = "V1 vcc 0 DC 5\n.control\ndc V1 0 10 0.1\nmeas dc v_lim when v(out)=4.0\n.endc\n"
    rows = measureplan.plan_rows("d", measureplan.measures(deck), {"v_lim": {"min": 8}}, {}, NETS)
    assert rows[0]["instrument"] == (
        "adjustable supply in place of the deck's swept source, and a DC voltmeter at the probe"
    )
    assert rows[0]["probe"] == "J1 pad 2 (/OUT)"


def test_a_deck_node_is_probed_at_a_connector_pad_of_its_net():
    assert measureplan.test_point("out", NETS) == ("/OUT", "J1 pad 2")
    assert measureplan.test_point("vcc", NETS) == ("VCC", "J1 pad 1")
    assert measureplan.test_point("0", NETS) == ("GND", "J1 pad 3")


def test_a_test_point_comes_before_a_connector_and_a_connector_before_a_part():
    nets = {"/SENSE": ["R1 pad 2", "J4 pad 1", "TP3 pad 1"], "/X": ["R5 pad 1", "C2 pad 2"]}
    assert measureplan.test_point("sense", nets) == ("/SENSE", "TP3 pad 1")
    assert measureplan.test_point("x", nets) == ("/X", "C2 pad 2")


def test_a_node_that_names_no_net_has_no_test_point():
    assert measureplan.test_point("nowhere", NETS) is None


def test_the_deck_s_sources_are_read():
    assert measureplan.sources(DECK) == [{"name": "V1", "nodes": ["vcc", "0"], "value": "DC 5 AC 1"}]


def test_a_measure_of_a_current_is_not_planned_and_says_why():
    rows = measureplan.plan_rows(
        "d",
        {"iin": {"analysis": "op", "quantity": "current", "unit": "A", "nodes": [], "reads": "i(v1)"}},
        {"iin": {"min": 1e-3, "max": 2e-3}},
        {},
        NETS,
    )
    assert rows[0]["planned"] is False
    assert (
        rows[0]["why"]
        == "it reads i(v1), a current: an ammeter goes in series, and the board names no place to open"
    )


def run(folder: Path, out: Path) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "measure", str(folder), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


@needs_engines
def test_the_plan_of_the_first_design_names_each_bound_s_pad_instrument_span_and_prediction(tmp_path):
    """The predicted values and the corner envelope are the SIM gate's from a run on 2026-11-17:
    vout 2.5 V as written, 2.460502 to 2.541747 V over 46 corners; f3 318.3124 Hz, 280.2102 to
    365.4749 Hz."""
    folder = tmp_path / "board"
    shutil.copytree(FIXTURE, folder)
    code, said = run(folder, tmp_path / "out")
    assert code == 0, said
    plan = json.loads((tmp_path / "out" / "measure" / "plan.json").read_text(encoding="utf-8"))
    rows = {r["measure"]: r for r in plan["rows"]}
    assert rows["vout"] == {
        "deck": "divider",
        "measure": "vout",
        "planned": True,
        "quantity": "voltage",
        "unit": "V",
        "probe": "J1 pad 2 (/OUT)",
        "reference": "J1 pad 3 (GND)",
        "instrument": "DC voltmeter",
        "min": 2.45,
        "max": 2.55,
        "predicted": 2.5,
        "corners": [2.460502, 2.541747],
        "conditions": [],
        "source": "the fixture's requirement: half of the 5 V supply within 2 %",
    }
    assert (
        rows["f3"]["instrument"] == "signal generator into the deck's AC source and a 2-channel oscilloscope"
    )
    assert (rows["f3"]["min"], rows["f3"]["max"], rows["f3"]["predicted"]) == (250, 400, 318.3124)
    assert rows["f3"]["corners"] == [280.2102, 365.4749]
    assert plan["sources"] == [
        {"deck": "divider", "name": "V1", "value": "DC 5 AC 1", "at": "J1 pad 1 (VCC) to J1 pad 3 (GND)"}
    ]
    md = (tmp_path / "out" / "measure" / "plan.md").read_text(encoding="utf-8")
    assert (
        "| divider | vout | the sources as stated | J1 pad 2 (/OUT) | J1 pad 3 (GND) | DC voltmeter | "
        "2.45 to 2.55 V | 2.5 V | 2.460502 to 2.541747 V |  |  |" in md
    )
    assert "PLAN   divider vout" in said and "2 bounds planned, 0 not planned" in said


@needs_engines
def test_a_deck_node_the_board_does_not_have_is_not_planned(tmp_path):
    """The deck's node `out` is renamed `tap`: the deck still runs, and no net of the board is called
    tap, so neither bound has a pad to probe."""
    folder = tmp_path / "board"
    shutil.copytree(FIXTURE, folder)
    deck = folder / "sim" / "divider.cir"
    deck.write_text(re.sub(r"\bout\b", "tap", DECK), encoding="utf-8")
    code, said = run(folder, tmp_path / "out")
    assert code == 1, said
    assert "NOT PLANNED divider vout: deck node tap names no net of the board" in said, said
    assert "0 bounds planned, 2 not planned" in said
