"""The makers' data in the decks (ROADMAP item 4): a capacitor at its working voltage and temperature,
an inductor at its current, from the curves of a part's facts whose maker's file has its row in
library/sources.csv. The SIM gate runs each deck with the curves in place of the written values, and
names each deck part that runs as an ideal part while the library holds its data.

The fixture tests/boards/fail-sim-bias is the power stage of a TLV62569 buck: 5 V to 3.3 V at 1.5 MHz,
L1 2.2 uH (Coilcraft XAL4020-222MEC), C2 10 uF (Samsung CL10A106KP8NNN), a 3 ohm load. Its ripple, by
hand, with a duty of 0.66 and a period of 666.67 ns:

    ideal       dI = (5 - 3.3) x 0.66 x 666.67n / 2.2u = 0.340 A; vpp = dI x 666.67n / (8 x 10u) = 2.83 mV
    C2's data   at 3.3 V its DC bias curve keeps 0.45041 - (3.3 - 3.246475) / (3.3368 - 3.246475)
                x (0.45041 - 0.43771) = 0.44288; at 27 C its curve keeps 1 - 2 / 2.311481 x 0.00297 =
                0.99743: 10u x 0.44288 x 0.99743 = 4.4174 uF
    L1's data   at 1.1 A its curve keeps 0.9683 - (1.1 - 0.753) / (1.454 - 0.753) x (0.9683 - 0.9362) =
                0.95241: 2.0953 uH, and dI = 0.340 x 2.2 / 2.0953 = 0.357 A
    both        vpp = 0.357 x 666.67n / (8 x 4.4174u) = 6.73 mV, over the 5 mV bound
    C2 alone    vpp = 0.340 x 666.67n / (8 x 4.4174u) = 6.41 mV, over it
    L1 alone    vpp = 0.357 x 666.67n / (8 x 10u) = 2.97 mV, under it

The formula leaves out the edges of the switch and the output's own ripple in dI, so a run is held to
it within 10 %: the ideal deck printed 3.04 mV in a run of ngspice 42.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
sys.path.insert(0, str(ROOT / "tools"))

import partdata  # noqa: E402
import ratings  # noqa: E402

needs_engines = pytest.mark.skipif(
    shutil.which("ngspice") is None or shutil.which("kicad-cli") is None,
    reason="ngspice or kicad-cli is not installed",
)
needs_ngspice = pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice is not installed")

SHA = "e7cb912bac00275e53505aa5870ec3543af75375920ac7fbb31cf92ebea3c182"


def curve(ref: str, kept: list, celsius: list | None = None, rating: float | None = None) -> partdata.Curve:
    return partdata.Curve(
        ref=ref,
        kind=ref[0],
        kept=kept,
        celsius=celsius,
        facts="parts.json: part 1",
        row="sources.csv:2",
        rating=rating,
    )


# ------------------------------------------------------------------ the deck as the gate runs it


def test_a_capacitor_takes_its_curve_of_volts_and_of_celsius():
    deck = "t\nV1 in 0 5\nC2 out 0 10u\nR1 in out 1k\n.end\n"
    c2 = curve("C2", [[0, 1.0], [4, 0.5]], [[25, 1.0], [85, 0.8]])
    text, applied, ideal = partdata.apply(deck, {"C2": c2})
    assert applied == ["C2"] and ideal == {}
    assert text.splitlines()[2] == "C2 out 0 C='(10u)*pwl(abs(v(out,0)),0,1,4,0.5)*pwl(temper,25,1,85,0.8)'"
    assert text.splitlines()[1] == "V1 in 0 5" and text.splitlines()[3] == "R1 in out 1k"


def test_an_inductor_takes_its_curve_of_amps_through_a_sense_source_of_its_own():
    deck = "t\nL1 sw out 2.2u\n.end\n"
    text, applied, _ = partdata.apply(deck, {"L1": curve("L1", [[0, 1.0], [2, 0.5]])})
    assert applied == ["L1"]
    lines = text.splitlines()
    assert lines[1] == "L1 sw l1_kept L='(2.2u)*pwl(abs(i(vl1_kept)),0,1,2,0.5)'"
    assert lines[2] == "vl1_kept l1_kept out 0"


def test_a_value_in_braces_or_after_its_word_keeps_its_place():
    deck = "t\nC2 out 0 c={cout}\nC3 out 0 {2*cout}\n.end\n"
    curves = {"C2": curve("C2", [[0, 1.0], [4, 0.5]]), "C3": curve("C3", [[0, 1.0], [4, 0.5]])}
    text, applied, _ = partdata.apply(deck, curves)
    assert applied == ["C2", "C3"]
    assert text.splitlines()[1] == "C2 out 0 c='(cout)*pwl(abs(v(out,0)),0,1,4,0.5)'"
    assert text.splitlines()[2] == "C3 out 0 C='(2*cout)*pwl(abs(v(out,0)),0,1,4,0.5)'"


def test_a_part_the_gate_cannot_rewrite_runs_ideal_and_is_named_with_the_reason():
    deck = "t\n.subckt rail a b\nC2 a b 10u\n.ends\nC5 out 0 cmodel\nX1 out 0 rail\n.end\n"
    curves = {"C2": curve("C2", [[0, 1.0], [4, 0.5]]), "C5": curve("C5", [[0, 1.0], [4, 0.5]])}
    text, applied, ideal = partdata.apply(deck, curves)
    assert applied == [] and text == deck
    assert ideal == {
        "C2": "it stands inside .subckt rail, which the gate does not rewrite",
        "C5": "its value cmodel is no number and no expression",
    }


def test_a_part_the_deck_does_not_hold_is_not_named():
    text, applied, ideal = partdata.apply("t\nR1 a 0 1k\n.end\n", {"C2": curve("C2", [[0, 1.0], [4, 0.5]])})
    assert (applied, ideal) == ([], {})


def test_a_curve_that_ends_under_the_part_s_rating_is_a_warning():
    """The curve stops at 4 V and the part is rated 10 V: above 4 V ngspice's pwl holds the last share."""
    short = curve("C2", [[0, 1.0], [4, 0.5]], rating=10)
    assert partdata.short_of_rating(short) == "C2's curve ends at 4 V, under its rating of 10 V"
    assert partdata.short_of_rating(curve("C2", [[0, 1.0], [10, 0.2]], rating=10)) is None
    amps = curve("L1", [[0, 1.0], [5.989, 0.69]], rating=5.6)
    assert partdata.short_of_rating(amps) is None


# ------------------------------------------------------------------ which data is the maker's


def facts(**keys) -> ratings.Facts:
    source = {"document": "d", "read": "2026-11-17", "second_reader": "no", "sha256": SHA}
    data = {"kind": "capacitor.ceramic", "mpn": "CL10A106KP8NNN", "source": source, **keys}
    return ratings.Facts("parts.json: part 1", data["kind"], data)


def row(sha: str = SHA, mpn: str = "CL10A106KP8NNN") -> partdata.Row:
    return partdata.Row(mpn=mpn, sha256=sha, source="sources.csv:2")


def test_a_curve_is_taken_when_its_maker_s_file_has_its_row():
    found, refused = partdata.choose(
        {"C2": ("CL10A106KP8NNN", facts(kept=[[0, 1.0], [4, 0.5]], volts=10))}, [row()]
    )
    assert refused == {}
    c2 = found["C2"]
    assert (c2.kind, c2.kept, c2.celsius, c2.row, c2.rating) == (
        "C",
        [[0, 1.0], [4, 0.5]],
        None,
        "sources.csv:2",
        10,
    )


def test_a_curve_with_no_row_of_its_maker_s_file_is_refused_and_named():
    other = "0" * 64
    found, refused = partdata.choose(
        {"C2": ("CL10A106KP8NNN", facts(kept=[[0, 1.0], [4, 0.5]]))}, [row(other)]
    )
    assert found == {}
    why = "no row of library/sources.csv for CL10A106KP8NNN holds the SHA256 its facts name"
    assert refused == {"C2": f"{why} ({SHA[:12]}...)"}
    found, refused = partdata.choose(
        {"C2": ("CL10A106KP8NNN", facts(kept=[[0, 1.0], [4, 0.5]]))}, [row(mpn="X")]
    )
    assert "C2" in refused and found == {}


def test_a_curve_entered_for_a_symbol_is_no_part_s_data():
    entry = facts(kept=[[0, 1.0], [4, 0.5]])
    del entry.data["mpn"]
    entry.data["symbol"] = "Device:C"
    found, refused = partdata.choose({"C2": ("", entry)}, [row()])
    assert found == {} and refused == {"C2": "its facts speak of the symbol Device:C, not of a part number"}


def test_facts_with_no_curve_and_parts_of_other_letters_are_passed_over():
    found, refused = partdata.choose(
        {
            "C2": ("CL10A106KP8NNN", facts(volts=10)),
            "R1": ("CL10A106KP8NNN", facts(kept=[[0, 1.0], [4, 0.5]])),
        },
        [row()],
    )
    assert (found, refused) == ({}, {})


def test_the_facts_take_an_inductor_s_curve_and_a_capacitor_s_temperature_curve(tmp_path):
    source = {"document": "d", "read": "2026-11-17", "second_reader": "no"}
    good = {
        "parts": [
            {"kind": "inductor", "mpn": "L-1", "tolerance": 0.2, "amps_saturation": 5.6,
             "kept": [[0, 1.0], [5.989, 0.6908]], "source": source},
            {"kind": "capacitor.ceramic", "mpn": "C-1", "kept_celsius": [[-55, 1.0228], [85, 0.85275]],
             "source": source},
        ]
    }  # fmt: skip
    (tmp_path / "a.json").write_text(json.dumps(good), encoding="utf-8")
    entries = ratings.read_facts(tmp_path)
    assert [e.kind for e in entries] == ["inductor", "capacitor.ceramic"]
    good["parts"][1]["kept_celsius"] = [[85, 0.85275], [-55, 1.0228]]
    (tmp_path / "a.json").write_text(json.dumps(good), encoding="utf-8")
    with pytest.raises(ratings.Refusal, match="kept_celsius: the celsius rise from pair to pair"):
        ratings.read_facts(tmp_path)


# ------------------------------------------------------------------ what ngspice does with it


@needs_ngspice
def test_ngspice_takes_the_rewritten_capacitor_as_its_capacitance_at_the_voltage(tmp_path):
    """1 mA into 10 uF that keeps 1 - 0.125 V of its value, at 27 C where its 25 to 85 C curve keeps
    1 - 0.2 x 2 / 60 = 0.99333: dt = C(v) dv / I, so 0 to 2 V takes 10u x 0.99333 x (2 - 0.0625 x 4)
    / 1m = 17.383 ms. A charge of C(v) x v would take 10u x 0.99333 x (2 - 0.125 x 4) / 1m = 14.9 ms."""
    deck = (
        "t\nI1 0 b 1m\nC2 b 0 10u\n.control\ntran 1u 20m\nmeas tran tb when v(b)=2\nprint tb\n.endc\n.end\n"
    )
    c2 = curve("C2", [[0, 1.0], [4, 0.5]], [[25, 1.0], [85, 0.8]])
    (tmp_path / "c.cir").write_text(partdata.apply(deck, {"C2": c2})[0], encoding="utf-8")
    proc = subprocess.run(
        ["ngspice", "-b", "c.cir"], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    tb = float(next(ln for ln in proc.stdout.splitlines() if ln.startswith("tb =")).split("=")[1])
    assert tb == pytest.approx(17.383e-3, rel=2e-3)


# ------------------------------------------------------------------ the gate on the fixture


def gate(*args: object) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", "sim", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ},
    )
    return proc.returncode, json.loads(proc.stdout)[0]


def fixture(tmp_path: Path) -> Path:
    target = tmp_path / "fail-sim-bias"
    shutil.copytree(BOARDS / "fail-sim-bias", target, ignore=shutil.ignore_patterns("build", "*.kicad_prl"))
    return target


@needs_engines
def test_the_regulator_misses_its_ripple_bound_with_the_makers_data_and_the_gate_names_the_capacitor(
    tmp_path,
):
    code, result = gate(fixture(tmp_path))
    assert code == 1 and result["status"] == "fail"
    lines = [f for f in result["details"]["failures"] if f.startswith("buck:vpp=")]
    assert len(lines) == 1 and len(result["details"]["failures"]) == 1, result["details"]["failures"]
    line = lines[0]
    assert "with the makers' data of C2 and L1" in line
    assert "C2 alone on its data misses it" in line and "L1 alone" not in line
    deck = result["details"]["decks"]["buck"]
    assert deck["measures"]["vpp"] == pytest.approx(6.73e-3, rel=0.10)
    assert deck["ideal"]["vpp"] == pytest.approx(2.83e-3, rel=0.10)
    assert [p["ref"] for p in deck["parts"]] == ["C2", "L1"]
    assert deck["parts"][0]["row"] == "sources.csv:2" and deck["parts"][1]["row"] == "sources.csv:3"


@needs_engines
def test_the_same_regulator_meets_its_bound_with_ideal_parts(tmp_path):
    project = fixture(tmp_path)
    shutil.rmtree(project / "library" / "facts")
    code, result = gate(project)
    assert code == 0, result["details"]["failures"]
    assert "parts" not in result["details"]["decks"]["buck"]
    assert result["details"]["decks"]["buck"]["measures"]["vpp"] == pytest.approx(2.83e-3, rel=0.10)


@needs_engines
def test_a_part_whose_data_has_no_row_runs_ideal_and_the_gate_names_it(tmp_path):
    project = fixture(tmp_path)
    csv = project / "library" / "sources.csv"
    csv.write_text(csv.read_text(encoding="utf-8").replace(SHA, "0" * 64), encoding="utf-8")
    code, result = gate(project)
    assert code == 1
    assert result["details"]["failures"] == [
        "buck: C2 runs as an ideal part while the library holds its maker's data (parts.json: part 1, "
        f"CL10A106KP8NNN): no row of library/sources.csv for CL10A106KP8NNN holds the SHA256 its facts name "
        f"({SHA[:12]}...)"
    ]
    # L1 alone on its data: 2.97 mV, under the bound
    assert result["details"]["decks"]["buck"]["measures"]["vpp"] == pytest.approx(2.97e-3, rel=0.10)


@needs_engines
def test_a_temperature_corner_runs_the_capacitor_on_its_temperature_curve(tmp_path):
    """At 85 C C2's curve keeps 0.85275: 10u x 0.44288 x 0.85275 = 3.7767 uF, and the ripple is
    0.357 x 666.67n / (8 x 3.7767u) = 7.88 mV; the deck at 27 C gave 6.73 mV by hand."""
    project = fixture(tmp_path)
    corners = {"temperature": {"values": [85], "source": "the fixture's requirement: 85 C"}}
    (project / "sim" / "corners.json").write_text(json.dumps(corners), encoding="utf-8")
    code, result = gate(project, "--deck", "buck")
    assert code == 1
    deck = result["details"]["decks"]["buck"]
    assert deck["corners"]["envelope"]["vpp"]["max"] == pytest.approx(7.88e-3, rel=0.10)
    assert not [w for w in result["details"]["warnings"] if "moves with temperature" in w]


@needs_engines
def test_a_bundle_of_the_deck_carries_the_makers_data(tmp_path):
    """The bundle runs from another folder and prints the gate's numbers: the curves go with it."""
    code, result = gate(fixture(tmp_path), "--bundle", tmp_path / "bundle")
    assert not [f for f in result["details"]["failures"] if "bundle" in f], result["details"]["failures"]
    assert "pwl(temper," in (tmp_path / "bundle" / "buck" / "buck.cir").read_text(encoding="utf-8")
