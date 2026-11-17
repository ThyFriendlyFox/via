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

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
FIXTURE = ROOT / "tests" / "boards" / "pass-first-design"
DECK = (FIXTURE / "sim" / "divider.cir").read_text(encoding="utf-8")
sys.path.insert(0, str(ROOT / "tools"))
import measureplan  # noqa: E402

needs_engines = pytest.mark.skipif(
    shutil.which("kicad-cli") is None or shutil.which("ngspice") is None, reason="kicad-cli or ngspice absent"
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
        "vout": {"analysis": "op", "quantity": "voltage", "unit": "V", "nodes": ["out"], "reads": "v(out)"},
        "f3": {"analysis": "ac", "quantity": "frequency", "unit": "Hz", "nodes": ["out"], "reads": "vm(out)"},
    }


def test_a_measure_of_a_current_names_no_node():
    got = measureplan.measures("V1 a 0 DC 5\nR1 a 0 1k\n.control\nop\nlet iin = -i(v1)\n.endc\n")
    assert got == {
        "iin": {"analysis": "op", "quantity": "current", "unit": "A", "nodes": [], "reads": "i(v1)"}
    }


def test_a_let_that_scales_a_measure_reads_what_that_measure_reads_in_no_named_unit():
    """Last Hit's master_switch deck writes `let t_trip_us = (t_trip - 37e-3) * 1e6` after a `meas`:
    the same crossing, in microseconds, which the plan does not name."""
    deck = ".control\ntran 1u 1m\nmeas tran t_x when v(out)=1.0 fall=1\nlet t_x_us = t_x * 1e6\n.endc\n"
    got = measureplan.measures(deck)["t_x_us"]
    assert got == {"analysis": "tran", "quantity": "time", "unit": "", "nodes": ["out"], "reads": "t_x * 1e6"}


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
        "| divider | vout | J1 pad 2 (/OUT) | J1 pad 3 (GND) | DC voltmeter | 2.45 to 2.55 V | 2.5 V | "
        "2.460502 to 2.541747 V |  |  |" in md
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
