"""The makers' data in the decks (ROADMAP item 4): a capacitor at its working voltage and temperature,
an inductor at its current, from the curves of a part's facts whose maker's file has its row in
library/sources.csv. The SIM gate runs each deck with the curves in place of the written values, and
names each deck part that runs as an ideal part while the library holds its data.

The fixture tests/boards/fail-sim-bias is the power stage of a TLV62569 buck: 5 V to 3.3 V at 1.5 MHz,
L1 2.2 uH (Coilcraft XAL4020-222MEC), C2 10 uF (Samsung CL10A106KP8NNN), a 3 ohm load. Its ripple, by
hand, with a duty of 0.66 and a period of 666.67 ns:

    ideal       dI = (5 - 3.3) x 0.66 x 666.67n / 2.2u = 0.340 A; vpp = dI x 666.67n / (8 x 10u) = 2.83 mV
    C2's data   at 3.3 V its DC bias curve keeps 0.45041 - (3.3 - 3.246475) / (3.3368 - 3.246475)
                x (0.45041 - 0.43771) = 0.44288; at 27 C its temperature curve keeps 1 - 2 / 2.311481
                x 0.00297 = 0.99743 at 0 V, and its maker's curve at 5 V moves that share to 0.991571 at
                3.3 V (the temperature corner's test shows the sum): 10u x 0.44288 x 0.991571 = 4.3915 uF
    L1's data   at 1.1 A its curve keeps 0.9683 - (1.1 - 0.753) / (1.454 - 0.753) x (0.9683 - 0.9362) =
                0.95241: 2.0953 uH, and dI = 0.340 x 2.2 / 2.0953 = 0.357 A
    both        vpp = 0.357 x 666.67n / (8 x 4.3915u) = 6.77 mV, over the 5 mV bound
    C2 alone    vpp = 0.340 x 666.67n / (8 x 4.3915u) = 6.45 mV, over it
    L1 alone    vpp = 0.357 x 666.67n / (8 x 10u) = 2.97 mV, under it

C2's ESR of 0.0034848 ohm adds R^2 C / 2 x (dI / 440n + dI / 226.67n) = 0.06 mV to a triangle's ripple,
where the 2 parts peak a quarter period apart. The formula leaves out the edges of the switch and the
output's own ripple in dI, so a run is held to it within 10 %: the ideal deck printed 3.04 mV in a run
of ngspice 42.
"""

from __future__ import annotations

import importlib.machinery
import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest
from conftest import engine

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
sys.path.insert(0, str(ROOT / "tools"))

import partdata  # noqa: E402
import ratings  # noqa: E402

needs_engines = engine(
    pytest.mark.skipif(
        shutil.which("ngspice") is None or shutil.which("kicad-cli") is None,
        reason="ngspice or kicad-cli is not installed",
    )
)
needs_ngspice = engine(pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice is not installed"))

SHA = "e7cb912bac00275e53505aa5870ec3543af75375920ac7fbb31cf92ebea3c182"


def load_cli():
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_partdata", str(CLI))
    module = types.ModuleType("workcenter_cli_partdata")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module
    loader.exec_module(module)
    return module


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


def bias_curve() -> partdata.Curve:
    """kept: 1 at 0 V, 0.5 at 10 V, so 0.75 at 5 V; its temperature curve at 0 V: 0.8 at 85 C; the
    maker's combined curve at 5 V: 0.74 at 25 C and 0.69 at 85 C."""
    c2 = curve("C2", [[0, 1.0], [10, 0.5]], [[25, 1.0], [85, 0.8]])
    c2.bias = {"volts": 5, "kept": [[25, 0.74], [85, 0.69]]}
    return c2


def test_a_capacitor_takes_its_maker_s_temperature_curve_at_a_bias():
    """At 5 V the share is the combined curve's: its temperature factor is the curve over the 0.75 the
    DC bias curve keeps at 5 V: 0.74 / 0.75 = 0.9866666667 at 25 C, 0.69 / 0.75 = 0.92 at 85 C. Between
    0 V and 5 V the factor goes from the 0 V curve's to that one in proportion to the volts."""
    text, applied, _ = partdata.apply("t\nC2 out 0 10u\n.end\n", {"C2": bias_curve()})
    v = "abs(v(out,0))"
    t0, tb = "pwl(temper,25,1,85,0.8)", "pwl(temper,25,0.9866666667,85,0.92)"
    assert applied == ["C2"]
    assert text.splitlines()[1] == f"C2 out 0 C='(10u)*pwl({v},0,1,10,0.5)*({t0}+({tb}-{t0})*min({v}/5,1))'"


def test_a_capacitor_takes_its_series_resistance_and_inductance():
    """The ESR and the ESL go in series with the part, toward its second node; the curve reads the
    voltage across the capacitance alone."""
    c2 = curve("C2", [[0, 1.0], [4, 0.5]])
    c2.esr, c2.esl = {"ohms": 0.0035, "hz": 1.5e6}, {"henries": 5e-10, "hz": 1e8}
    text, applied, _ = partdata.apply("t\nC2 out 0 10u\nR1 out 0 1k\n.end\n", {"C2": c2})
    assert applied == ["C2"]
    assert text.splitlines()[1:5] == [
        "C2 out c2_esr C='(10u)*pwl(abs(v(out,c2_esr)),0,1,4,0.5)'",
        "rc2_esr c2_esr c2_esl 0.0035",
        "lc2_esl c2_esl 0 5e-10",
        "R1 out 0 1k",
    ]
    c2.esl = None
    text, _, _ = partdata.apply("t\nC2 out 0 10u\n.end\n", {"C2": c2})
    assert text.splitlines()[1:3] == [
        "C2 out c2_esr C='(10u)*pwl(abs(v(out,c2_esr)),0,1,4,0.5)'",
        "rc2_esr c2_esr 0 0.0035",
    ]


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


def test_a_part_in_a_file_the_deck_includes_runs_ideal_and_is_named():
    """C2 stands in output.inc: the gate rewrites the deck's own lines only, so C2 would run ideal."""
    deck = "t\n.include output.inc\nL1 sw out 2.2u\n.end\n"
    c2 = curve("C2", [[0, 1.0], [4, 0.5]])
    text, applied, ideal = partdata.apply(deck, {"C2": c2}, {"output.inc": "* the output\nC2 out 0 10u\n"})
    assert applied == [] and text == deck
    assert ideal == {
        "C2": "it stands in output.inc, a file the deck includes, which the gate does not rewrite"
    }
    # a part inside a model's .subckt in an included file is no board part
    inside = {"m.lib": ".subckt amp a b\nC2 a b 1p\n.ends\n"}
    assert partdata.apply(deck, {"C2": c2}, inside)[2] == {}


def test_the_gate_reads_each_file_an_included_file_includes_once(tmp_path):
    """ngspice reads an include against the folder of the file that writes it; caps/c.inc includes
    output.inc back, and the walk stops there."""
    cli = load_cli()
    deck = tmp_path / "buck.cir"
    deck.write_text("t\n.include output.inc\n.include gone.inc\n.end\n", encoding="utf-8")
    (tmp_path / "output.inc").write_text("* out\n.include caps/c.inc\n", encoding="utf-8")
    (tmp_path / "caps").mkdir()
    (tmp_path / "caps" / "c.inc").write_text("C2 out 0 10u\n.include ../output.inc\n", encoding="utf-8")
    got = cli.deck_includes(deck, deck.read_text(encoding="utf-8"))
    assert got == {
        "output.inc": "* out\n.include caps/c.inc\n",
        "caps/c.inc (from output.inc)": "C2 out 0 10u\n.include ../output.inc\n",
    }
    text, applied, ideal = partdata.apply(
        deck.read_text(encoding="utf-8"), {"C2": curve("C2", [[0, 1.0]])}, got
    )
    assert applied == [] and ideal == {
        "C2": "it stands in caps/c.inc (from output.inc), a file the deck includes, which the gate does not "
        "rewrite"
    }


def library_with_a_curve(folder: Path) -> Path:
    """A project folder whose library's facts hold C2's curve, and a deck that names C2 and L1."""
    facts = folder / "library" / "facts"
    facts.mkdir(parents=True)
    source = {"document": "d", "read": "2026-11-17", "second_reader": "no", "sha256": SHA}
    entry = {
        "kind": "capacitor.ceramic",
        "mpn": "CL10A106KP8NNN",
        "kept": [[0, 1.0], [4, 0.5]],
        "source": source,
    }
    (facts / "parts.json").write_text(json.dumps({"parts": [entry]}), encoding="utf-8")
    (folder / "sim").mkdir()
    deck = folder / "sim" / "buck.cir"
    deck.write_text("t\nL1 sw out 2.2u\nC2 out 0 10u\nRLOAD out 0 3\n.end\n", encoding="utf-8")
    return deck


def test_a_project_with_no_schematic_leaves_its_deck_parts_not_judged(tmp_path):
    """No schematic gives C2 and L1 no part number: whether they hold data is not known, and said."""
    cli = load_cli()
    deck = library_with_a_curve(tmp_path)
    project = cli.Project(tmp_path, "p", None, None, None)
    got = cli.deck_part_data(project, tmp_path / "out", None, [deck])
    assert got == (
        {},
        {},
        {},
        [],
        [
            "not judged: whether C2 and L1 run on their makers' data: the library's facts hold curves, and "
            "the project has no schematic to give the parts' numbers"
        ],
    )
    # a C or an L not named like a reference may be a part with data too: with no schematic it is named
    deck.write_text("t\nR1 a 0 1k\nCout a 0 1u\n.end\n", encoding="utf-8")
    assert cli.deck_part_data(project, tmp_path / "out", None, [deck])[4] == [
        "not judged: whether Cout runs on its maker's data: the library's facts hold curves, and the "
        "project has no schematic to give the parts' numbers"
    ]
    deck.write_text("t\nL1 sw out 2.2u\nCout out 0 1u\n.end\n", encoding="utf-8")
    assert cli.deck_part_data(project, tmp_path / "out", None, [deck])[4] == [
        "not judged: whether L1 and Cout run on their makers' data: the library's facts hold curves, and "
        "the project has no schematic to give the parts' numbers"
    ]
    deck.write_text("t\nR1 a 0 1k\n.end\n", encoding="utf-8")  # no C or L at all
    assert cli.deck_part_data(project, tmp_path / "out", None, [deck]) == ({}, {}, {}, [], [])


def test_a_machine_with_no_kicad_cli_leaves_the_deck_parts_not_judged(tmp_path):
    cli = load_cli()
    deck = library_with_a_curve(tmp_path)
    sch = tmp_path / "p.kicad_sch"
    sch.write_text("(kicad_sch)", encoding="utf-8")
    cli.KICAD_CLI = str(tmp_path / "no-kicad-cli")
    project = cli.Project(tmp_path, "p", None, sch, None)
    *_, warnings = cli.deck_part_data(project, tmp_path / "out", None, [deck])
    assert warnings == [
        "not judged: whether C2 and L1 run on their makers' data: the library's facts hold curves, and "
        f"kicad-cli, which reads the schematic, is not there: {tmp_path / 'no-kicad-cli'}"
    ]


def test_a_capacitor_s_initial_condition_moves_to_a_unit_capacitor_it_drives():
    """ngspice 42 drops the ic= of a behavioural C, and its behavioural C starts from 0 V under a node's
    `.ic` too (a run of this file on 2026-11-18). With `uic` the gate writes the part as a current
    source of C(v) times the current of a 1 F capacitor that holds the part's voltage and its ic=; the
    written element stays as a comment. Without `uic` ngspice uses no ic=, and the gate takes it off."""
    curves = {"C2": curve("C2", [[0, 1.0], [4, 0.5]]), "C3": curve("C3", [[0, 1.0], [4, 0.5]])}
    deck = "t\nC2 out 0 10u ic=5\nC3 a neg 1u IC = 2\n.control\ntran 10u 2m uic\n.endc\n.end\n"
    text, applied, ideal = partdata.apply(deck, curves)
    assert applied == ["C2", "C3"] and ideal == {}
    assert text.splitlines()[1:11] == [
        "* C2 out 0 10u ic=5",
        "bc2_ic out 0 I=i(vc2_ic)*(10u)*pwl(abs(v(out,0)),0,1,4,0.5)",
        "ec2_ic c2_ic_e 0 out 0 1",
        "vc2_ic c2_ic_e c2_ic 0",
        "cc2_ic c2_ic 0 1 ic=5",
        "* C3 a neg 1u IC = 2",
        "bc3_ic a neg I=i(vc3_ic)*(1u)*pwl(abs(v(a,neg)),0,1,4,0.5)",
        "ec3_ic c3_ic_e 0 a neg 1",
        "vc3_ic c3_ic_e c3_ic 0",
        "cc3_ic c3_ic 0 1 ic=2",
    ]
    text, applied, _ = partdata.apply(deck.replace(" uic", ""), curves)
    assert applied == ["C2", "C3"] and "ic=" not in text.lower()
    assert text.splitlines()[1:3] == [
        "C2 out 0 C='(10u)*pwl(abs(v(out,0)),0,1,4,0.5)'",
        "C3 a neg C='(1u)*pwl(abs(v(a,neg)),0,1,4,0.5)'",
    ]


def test_uic_on_a_continuation_line_of_the_tran_card_is_read():
    """ngspice joins `+ uic` onto the `.tran` card and then uses C2's ic=: the gate moves it to the unit
    capacitor, as for `uic` on the card's own line, and does not take it off."""
    deck = "t\nC2 out 0 10u ic=5\nR1 out 0 1k\n.tran 1u 2m\n+ uic\n.end\n"
    text, applied, ideal = partdata.apply(deck, {"C2": curve("C2", [[0, 1.0], [4, 0.5]])})
    assert applied == ["C2"] and ideal == {}
    assert "cc2_ic c2_ic 0 1 ic=5" in text.splitlines()
    # a word that only holds the letters, in a title or a comment, is no uic
    deck = "t uic\nC2 out 0 10u ic=5\n* .tran 1u 2m uic\n.tran 1u 2m\n.end\n"
    text, _, _ = partdata.apply(deck, {"C2": curve("C2", [[0, 1.0], [4, 0.5]])})
    assert text.splitlines()[1] == "C2 out 0 C='(10u)*pwl(abs(v(out,0)),0,1,4,0.5)'"


def test_a_capacitor_with_an_ic_and_other_parameters_under_uic_runs_ideal_and_is_named():
    """The form the gate writes for an ic= under uic is a B source: it carries no m=, tc1= or other
    parameter of the line, so C2 with m=2 would run at half its capacitance. Without uic the gate keeps
    the named form, `C='...'`, and the line's m=2 stays on it: ngspice 42 took 39.99 ms to charge
    10 uF with m=2 by 1 mA to 2 V in that form, as written, and 19.99 ms without m (a run on 2026-11-18)."""
    c2 = curve("C2", [[0, 1.0], [4, 0.5]])
    for extra, said in (("m=2", "m=2"), ("tc1 = 0.01", "tc1=0.01")):
        deck = f"t\nC2 out 0 10u {extra} ic=5\nR1 out 0 1k\n.tran 1u 2m uic\n.end\n"
        text, applied, ideal = partdata.apply(deck, {"C2": c2})
        assert applied == [] and text == deck
        assert ideal == {
            "C2": f"its line also holds {said}, which the form the gate writes for an ic= under uic "
            "does not carry"
        }
    text, applied, _ = partdata.apply("t\nC2 out 0 10u m=2\n.end\n", {"C2": c2})
    assert applied == ["C2"]
    assert text.splitlines()[1] == "C2 out 0 C='(10u)*pwl(abs(v(out,0)),0,1,4,0.5)' m=2"


def test_a_part_whose_initial_condition_the_gate_cannot_move_runs_ideal_and_is_named():
    """With `uic`: an inductor's ic= (no form of it was run to the same numbers), and a capacitor's ic=
    that is no number."""
    deck = "t\nC2 a b 10u ic={v0}\nL1 sw out 2.2u IC = 1\n.tran 1u 1m uic\n.end\n"
    curves = {"C2": curve("C2", [[0, 1.0], [4, 0.5]]), "L1": curve("L1", [[0, 1.0], [2, 0.5]])}
    text, applied, ideal = partdata.apply(deck, curves)
    assert applied == [] and text == deck
    assert ideal == {
        "C2": "its ic={v0} is no number, and the gate writes a starting voltage only as a number",
        "L1": "its ic= sets its starting current, which ngspice 42 drops from the element the gate writes",
    }


def test_an_inductor_a_k_element_couples_runs_ideal_and_is_named_as_not_modelled():
    """The gate models no coupled inductor's curve: L1 runs ideal and is named, and the deck does not
    fail for it: a transformer with its curve in the facts runs as the deck writes it."""
    deck = "t\nL1 p 0 2.2u\nL9 s 0 2.2u\nK1 L1 L9 0.99\n.end\n"
    curves = {"L1": curve("L1", [[0, 1.0], [2, 0.5]])}
    text, applied, ideal = partdata.apply(deck, curves)
    assert applied == [] and text == deck and ideal == {}
    assert partdata.not_modelled(deck, curves) == {
        "L1": "it is coupled by K1, and the gate models no coupled inductor's curve"
    }


def test_a_k_element_inside_a_subckt_couples_only_that_block_s_inductors():
    """K1 couples the L1 and L2 of .subckt xfmr. The board's L1 stands at the top level and no K there
    names it: it runs on its curve, and nothing names it as coupled."""
    deck = (
        "t\n.subckt xfmr p s\nL1 p 0 1u\nL2 s 0 1u\nK1 L1 L2 0.9\n.ends\n"
        "L1 sw out 2.2u\nC9 out 0 10u\nX1 a b xfmr\n.end\n"
    )
    curves = {"L1": curve("L1", [[0, 1.0], [2, 0.5]])}
    text, applied, ideal = partdata.apply(deck, curves)
    assert (applied, ideal) == (["L1"], {})
    assert "L1 sw l1_kept L='(2.2u)*pwl(abs(i(vl1_kept)),0,1,2,0.5)'" in text.splitlines()
    assert "L1 p 0 1u" in text.splitlines()
    assert partdata.not_modelled(deck, curves) == {}


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


def row(sha: str = SHA, mpn: str = "CL10A106KP8NNN", file: str = "") -> partdata.Row:
    return partdata.Row(mpn=mpn, sha256=sha, source="sources.csv:2", file=file)


def test_a_curve_is_taken_when_its_maker_s_file_has_its_row():
    found, refused, _ = partdata.choose(
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
    found, refused, _ = partdata.choose(
        {"C2": ("CL10A106KP8NNN", facts(kept=[[0, 1.0], [4, 0.5]]))}, [row(other)]
    )
    assert found == {}
    why = "no row of library/sources.csv for CL10A106KP8NNN holds the SHA256 its facts name"
    assert refused == {"C2": f"{why} ({SHA[:12]}...)"}
    found, refused, _ = partdata.choose(
        {"C2": ("CL10A106KP8NNN", facts(kept=[[0, 1.0], [4, 0.5]]))}, [row(mpn="X")]
    )
    assert "C2" in refused and found == {}


def test_a_curve_entered_for_a_symbol_is_no_part_s_data():
    entry = facts(kept=[[0, 1.0], [4, 0.5]])
    del entry.data["mpn"]
    entry.data["symbol"] = "Device:C"
    found, refused, _ = partdata.choose({"C2": ("", entry)}, [row()])
    assert found == {} and refused == {"C2": "its facts speak of the symbol Device:C, not of a part number"}


def test_a_curve_entered_for_a_pattern_is_no_part_s_data():
    """A series datasheet covers every value of the series: a pattern would give a 4.7 uH part the
    2.2 uH curve. A curve is taken only from an entry that names the board's part number."""
    entry = facts(kept=[[0, 1.0], [4, 0.5]])
    del entry.data["mpn"]
    entry.data["match"] = "XAL4020-*"
    entry.kind = entry.data["kind"] = "inductor"
    found, refused, _ = partdata.choose({"L1": ("XAL4020-472MEC", entry)}, [row(mpn="XAL4020-472MEC")])
    assert found == {}
    assert refused == {
        "L1": "its facts name the parts by the pattern XAL4020-*, not by its part number XAL4020-472MEC: "
        "a curve is taken from an entry whose mpn or mpns names the part"
    }
    entry.data["mpns"] = ["XAL4020-222MEC", "XAL4020-472MEC"]
    del entry.data["match"]
    found, refused, _ = partdata.choose({"L1": ("XAL4020-472MEC", entry)}, [row(mpn="XAL4020-472MEC")])
    assert list(found) == ["L1"] and refused == {}


def test_a_row_that_keeps_no_file_leaves_the_sha256_not_judged(tmp_path):
    """Only a file can hold a SHA256: a row with none is 2 typed strings that agree."""
    entry = facts(kept=[[0, 1.0], [4, 0.5]])
    found, refused, unjudged = partdata.choose({"C2": ("CL10A106KP8NNN", entry)}, [row()])
    assert list(found) == ["C2"] and refused == {}
    assert unjudged == {
        "C2": f"sources.csv:2 keeps no file, so nothing holds its SHA256 ({SHA[:12]}...) against the maker's"
    }
    kept = tmp_path / "c.pdf"
    kept.write_bytes(b"another file")
    found, refused, unjudged = partdata.choose({"C2": ("CL10A106KP8NNN", entry)}, [row(file=str(kept))])
    assert found == {} and unjudged == {}
    assert refused == {"C2": "the file sources.csv:2 keeps, c.pdf, is not the one its SHA256 names"}
    kept.write_bytes(b"")
    empty = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # SHA256 of 0 bytes
    entry.data["source"]["sha256"] = empty
    found, refused, unjudged = partdata.choose(
        {"C2": ("CL10A106KP8NNN", entry)}, [row(sha=empty, file=str(kept))]
    )
    assert list(found) == ["C2"] and (refused, unjudged) == ({}, {})


def test_a_capacitor_s_bias_curve_esr_and_esl_are_taken_from_its_facts():
    """The DC bias curve keeps 1 + (0.44 - 1) x 5 / 10 = 0.72 at 5 V, and the curve at 5 V keeps 0.72
    at 25 C: its shares are against the value at 0 V and 25 C."""
    at = {"volts": 5, "kept": [[25, 0.72], [85, 0.7]]}
    esr, esl = {"ohms": 0.0035, "hz": 1.5e6}, {"henries": 5e-10, "hz": 1e8}
    entry = facts(kept=[[0, 1.0], [10, 0.44]], kept_celsius_at=at, esr=esr, esl=esl)
    found, refused, _ = partdata.choose({"C2": ("CL10A106KP8NNN", entry)}, [row()])
    assert refused == {} and (found["C2"].bias, found["C2"].esr, found["C2"].esl) == (at, esr, esl)


def test_a_bias_curve_whose_shares_are_not_against_0_v_and_25_c_is_refused():
    """The gate divides the curve at 5 V by the 0.75 the DC bias curve keeps there (1 + (0.5 - 1) x
    5 / 10): its shares are against the value at 0 V and 25 C, as Samsung's BiasTCC data gives them,
    and its 25 C share is then near 0.75. A curve that keeps 1 at 25 C, |1 - 1| = 0 from 1 and
    |1 - 0.75| = 0.25 from 0.75, was entered against 25 C at its own bias, and would undo the DC bias
    loss at 5 V. A curve that does not reach 25 C, or a part with no DC bias curve, cannot be held to
    that, and is refused too."""
    kept = [[0, 1.0], [10, 0.5]]
    for at, keys, said in (
        (
            {"volts": 5, "kept": [[-55, 0.95], [25, 1.0], [85, 0.95]]},
            {"kept": kept},
            "its kept_celsius_at keeps 1 at 25 C, nearer 1 than the 0.75 its DC bias curve keeps at 5 V: "
            "its shares are to be against the value at 0 V and 25 C, as the gate divides them by 0.75",
        ),
        (
            {"volts": 5, "kept": [[50, 0.74], [85, 0.7]]},
            {"kept": kept},
            "its kept_celsius_at does not reach 25 C, so its shares cannot be held to the value at 0 V "
            "and 25 C",
        ),
        (
            {"volts": 5, "kept": [[25, 0.74], [85, 0.7]]},
            {},
            "its kept_celsius_at has no DC bias curve (`kept`) to hold its shares to the value at 0 V "
            "and 25 C",
        ),
    ):
        entry = facts(kept_celsius_at=at, **keys)
        found, refused, _ = partdata.choose({"C2": ("CL10A106KP8NNN", entry)}, [row()])
        assert (found, refused) == ({}, {"C2": said})


def test_the_temperature_factor_between_0_v_and_the_bias_is_named_as_not_the_maker_s():
    """The maker gives the temperature curve at 0 V and at 1 bias; between them the gate draws a
    straight line in volts, which is no curve of the maker's: it says so."""
    assert partdata.between(bias_curve()) == (
        "not judged: C2's share at a temperature between 0 V and 5 V: the gate goes from its maker's "
        "temperature curve at 0 V to the one at 5 V in a straight line in volts, which the maker does "
        "not publish"
    )
    assert partdata.between(curve("C2", [[0, 1.0], [4, 0.5]], [[25, 1.0], [85, 0.8]])) is None


def test_the_facts_take_a_bias_curve_esr_and_esl_and_refuse_them_malformed(tmp_path):
    source = {"document": "d", "read": "2026-11-17", "second_reader": "no"}
    entry = {"kind": "capacitor.ceramic", "mpn": "C-1", "source": source,
             "kept_celsius_at": {"volts": 5, "kept": [[-55, 0.26], [85, 0.27]]},
             "esr": {"ohms": 0.0035, "hz": 1.5e6}, "esl": {"henries": 5e-10, "hz": 1e8}}  # fmt: skip
    (tmp_path / "a.json").write_text(json.dumps({"parts": [entry]}), encoding="utf-8")
    assert [e.kind for e in ratings.read_facts(tmp_path)] == ["capacitor.ceramic"]
    for key, bad, said in (
        (
            "kept_celsius_at",
            {"volts": 5, "kept": [[85, 0.27], [-55, 0.26]]},
            "the celsius rise from pair to pair",
        ),
        ("kept_celsius_at", {"kept": [[-55, 0.26], [85, 0.27]]}, "`volts` is missing"),
        ("esr", {"ohms": 0.0035}, "esr: `hz` is missing"),
        ("esl", {"henries": -1, "hz": 1e8}, "esl: henries: -1 is not above 0"),
    ):
        (tmp_path / "a.json").write_text(json.dumps({"parts": [{**entry, key: bad}]}), encoding="utf-8")
        with pytest.raises(ratings.Refusal, match=said):
            ratings.read_facts(tmp_path)


def test_facts_with_no_curve_and_parts_of_other_letters_are_passed_over():
    found, refused, _ = partdata.choose(
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


def test_the_facts_refuse_a_share_of_0(tmp_path):
    """No part keeps 0 % of its value: a share of 0 makes C or L zero, and ngspice stops on its step."""
    source = {"document": "d", "read": "2026-11-17", "second_reader": "no"}
    entry = {"kind": "inductor", "mpn": "L-1", "tolerance": 0.2, "amps_saturation": 5.6,
             "kept": [[0, 1.0], [0.5, 0.0], [5.989, 0.0]], "source": source}  # fmt: skip
    (tmp_path / "a.json").write_text(json.dumps({"parts": [entry]}), encoding="utf-8")
    with pytest.raises(ratings.Refusal) as refused:
        ratings.read_facts(tmp_path)
    assert str(refused.value) == "a.json: part 1: kept: fraction: 0 is not above 0"


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


def ngspice_print(folder: Path, deck: str, name: str) -> float:
    (folder / "c.cir").write_text(deck, encoding="utf-8")
    proc = subprocess.run(["ngspice", "-b", "c.cir"], cwd=folder, capture_output=True, text=True, check=False)
    return float(next(ln for ln in proc.stdout.splitlines() if ln.startswith(f"{name} =")).split("=")[1])


@needs_ngspice
@pytest.mark.parametrize("start", ["uic", ""])
def test_the_initial_condition_on_the_part_and_on_the_node_give_the_same_run(tmp_path, start):
    """C2 10 uF at 5 V into 1 kohm: with uic, v = 5 x e^(-1m / 10m) = 4.5242 V at 1 ms, from C2's ic=5
    as written and from the gate's unit capacitor with ic=5, C2 on a curve that keeps 1 at every
    voltage. Without uic ngspice starts from the operating point, 0 V, either way. ngspice 42's own
    behavioural C under `.ic v(out)=5` printed 0 V here on 2026-11-18: that form is not used."""
    deck = (
        f"t\nC2 out 0 10u ic=5\nR1 out 0 1k\n.control\ntran 1u 2m {start}\nmeas tran v1 find v(out) at=1m\n"
    )
    deck += "print v1\n.endc\n.end\n"
    written = ngspice_print(tmp_path, deck, "v1")
    rewritten = partdata.apply(deck, {"C2": curve("C2", [[0, 1.0], [10, 1.0]])})[0]
    assert ("cc2_ic c2_ic 0 1 ic=5" in rewritten) == bool(start)
    assert "C2 out 0 10u ic=5" not in rewritten.splitlines()
    gate_s = ngspice_print(tmp_path, rewritten, "v1")
    assert written == pytest.approx(4.5242 if start else 0, rel=1e-3, abs=1e-6)
    assert gate_s == pytest.approx(written, rel=1e-4, abs=1e-6)
    if start:
        # a curve that keeps 0.5: 5 uF, and v = 5 x e^(-1m / 5m) = 4.0937 V at 1 ms
        half = partdata.apply(deck, {"C2": curve("C2", [[0, 0.5], [10, 0.5]])})[0]
        assert ngspice_print(tmp_path, half, "v1") == pytest.approx(4.0937, rel=1e-3)


@needs_ngspice
def test_uic_on_a_continuation_line_gives_the_written_run(tmp_path):
    """`.tran 1u 2m` with `+ uic` on the next line: ngspice starts C2 from its ic=5, and v = 5 x
    e^(-1m / (10u x 1k)) = 5 x e^-0.1 = 4.5242 V at 1 ms, as written and as the gate rewrites it on a
    curve that keeps 1 at every voltage."""
    deck = "t\nC2 out 0 10u ic=5\nR1 out 0 1k\n.tran 1u 2m\n+ uic\n.meas tran v1 find v(out) at=1m\n.end\n"

    def measured(text: str) -> float:
        (tmp_path / "c.cir").write_text(text, encoding="utf-8")
        proc = subprocess.run(
            ["ngspice", "-b", "c.cir"], cwd=tmp_path, capture_output=True, text=True, check=False
        )
        return float(next(ln for ln in proc.stdout.splitlines() if ln.split()[:2] == ["v1", "="]).split()[2])

    written = measured(deck)
    rewritten = partdata.apply(deck, {"C2": curve("C2", [[0, 1.0], [10, 1.0]])})[0]
    assert written == pytest.approx(4.5242, rel=1e-3)
    assert measured(rewritten) == pytest.approx(written, rel=1e-4)


@needs_ngspice
@pytest.mark.parametrize(
    ("volts", "share"),
    [
        # at 5 V the maker's combined curve: 0.69 at 85 C, where the 2 curves multiplied give 0.75 x 0.8 = 0.6
        (5, 0.69),
        # at 2.5 V: kept 1 - 0.25 x 0.5 = 0.875; factor 0.8 + (0.92 - 0.8) x 2.5 / 5 = 0.86; 0.875 x 0.86
        (2.5, 0.7525),
    ],
)
def test_ngspice_takes_the_capacitor_at_its_bias_on_the_maker_s_combined_curve(tmp_path, volts, share):
    """An AC run at 85 C on a DC bias: |i| / (2 pi f 10 uF) is the share the deck's capacitor keeps."""
    deck = (
        f"t\nV1 b 0 DC {volts} AC 1\nC2 b 0 10u\n.options temp=85\n.control\nac lin 1 1000 1000\n"
        "let s = mag(i(v1)) / (2 * pi * 1000 * 1e-5)\nprint s\n.endc\n.end\n"
    )
    (tmp_path / "c.cir").write_text(partdata.apply(deck, {"C2": bias_curve()})[0], encoding="utf-8")
    proc = subprocess.run(
        ["ngspice", "-b", "c.cir"], cwd=tmp_path, capture_output=True, text=True, check=False
    )
    s = float(next(ln for ln in proc.stdout.splitlines() if ln.startswith("s =")).split("=")[1])
    assert s == pytest.approx(share, rel=1e-3)


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
    assert deck["measures"]["vpp"] == pytest.approx(6.77e-3, rel=0.10)
    assert deck["ideal"]["vpp"] == pytest.approx(2.83e-3, rel=0.10)
    assert [p["ref"] for p in deck["parts"]] == ["C2", "L1"]
    assert deck["parts"][0]["row"] == "sources.csv:2" and deck["parts"][1]["row"] == "sources.csv:3"
    # the fixture keeps no maker's file: the 2 SHA256 are typed, and the gate says it did not judge them
    unjudged = [w for w in result["details"]["warnings"] if "not judged" in w]
    assert unjudged == [
        "C2 runs on its maker's data, and whether that is its maker's file is not judged: sources.csv:2 "
        f"keeps no file, so nothing holds its SHA256 ({SHA[:12]}...) against the maker's",
        "not judged: C2's share at a temperature between 0 V and 5 V: the gate goes from its maker's "
        "temperature curve at 0 V to the one at 5 V in a straight line in volts, which the maker does "
        "not publish",
        "L1 runs on its maker's data, and whether that is its maker's file is not judged: sources.csv:3 "
        "keeps no file, so nothing holds its SHA256 (b26cf975bd56...) against the maker's",
    ]


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
    # L1 alone on its data: 2.97 mV by hand, under the bound. The window of 10 % holds the ideal run's
    # 3.04 mV too, so the parts the deck ran on are what tells L1 on its data from L1 ideal.
    deck = result["details"]["decks"]["buck"]
    assert [p["ref"] for p in deck["parts"]] == ["L1"]
    assert deck["measures"]["vpp"] == pytest.approx(2.97e-3, rel=0.10)


@needs_engines
def test_a_capacitor_in_a_file_the_deck_includes_runs_ideal_and_the_gate_names_it(tmp_path):
    """C2 moved into sim/output.inc: the gate rewrites the deck's own lines, so C2 runs ideal (L1 alone
    on its data, 2.97 mV by hand, under the 5 mV bound); the deck fails on the line that names C2."""
    project = fixture(tmp_path)
    deck = project / "sim" / "buck.cir"
    deck.write_text(
        deck.read_text(encoding="utf-8").replace("C2 out 0 10u\n", ".include output.inc\n"), encoding="utf-8"
    )
    (project / "sim" / "output.inc").write_text("* the output capacitor\nC2 out 0 10u\n", encoding="utf-8")
    code, result = gate(project)
    assert code == 1
    assert result["details"]["failures"] == [
        "buck: C2 runs as an ideal part while the library holds its maker's data (parts.json: part 1, "
        "CL10A106KP8NNN): it stands in output.inc, a file the deck includes, which the gate does not rewrite"
    ]
    # C2 runs on no curve, so no line says it does
    assert not [w for w in result["details"]["warnings"] if w.startswith("C2 runs on its maker's data")]


@needs_engines
def test_a_capacitor_2_includes_deep_runs_ideal_and_the_gate_names_it(tmp_path):
    """C2 in sim/caps/output.inc, which sim/stage.inc includes: the same line as 1 include deep."""
    project = fixture(tmp_path)
    deck = project / "sim" / "buck.cir"
    deck.write_text(
        deck.read_text(encoding="utf-8").replace("C2 out 0 10u\n", ".include stage.inc\n"), encoding="utf-8"
    )
    (project / "sim" / "stage.inc").write_text("* the stage\n.include caps/output.inc\n", encoding="utf-8")
    (project / "sim" / "caps").mkdir()
    (project / "sim" / "caps" / "output.inc").write_text("C2 out 0 10u\n", encoding="utf-8")
    code, result = gate(project)
    assert code == 1
    assert result["details"]["failures"] == [
        "buck: C2 runs as an ideal part while the library holds its maker's data (parts.json: part 1, "
        "CL10A106KP8NNN): it stands in caps/output.inc (from stage.inc), a file the deck includes, which the "
        "gate does not rewrite"
    ]


@needs_engines
def test_a_coupled_inductor_runs_ideal_is_named_and_does_not_fail_the_deck(tmp_path):
    """K1 couples L1 to a winding L9: L1 runs ideal with a line that says so, and no failure names it."""
    project = fixture(tmp_path)
    deck = project / "sim" / "buck.cir"
    deck.write_text(
        deck.read_text(encoding="utf-8").replace(
            "RLOAD", "L9 aux 0 2.2u\nRAUX aux 0 1k\nK1 L1 L9 0.5\nRLOAD"
        ),
        encoding="utf-8",
    )
    code, result = gate(project)
    assert not [f for f in result["details"]["failures"] if "L1 runs as an ideal part" in f]
    assert (
        "not judged: buck: L1 runs as an ideal part while the library holds its maker's data (parts.json: "
        "part 2, XAL4020-222MEC): it is coupled by K1, and the gate models no coupled inductor's curve"
    ) in result["details"]["warnings"]
    assert [p["ref"] for p in result["details"]["decks"]["buck"]["parts"]] == ["C2"]


@needs_engines
def test_decks_with_no_capacitor_or_inductor_leave_the_makers_data_not_judged(tmp_path):
    """The deck drives the load through a resistor: no deck element is a C or an L, and C2 and L1 hold
    data. The gate names them; the deck has no bound, so nothing else fails."""
    project = fixture(tmp_path)
    deck = project / "sim" / "buck.cir"
    deck.write_text(
        deck.read_text(encoding="utf-8").replace("L1 sw out 2.2u\nC2 out 0 10u\n", "RL sw out 1\n"),
        encoding="utf-8",
    )
    (project / "sim" / "buck.expect.json").unlink()
    code, result = gate(project)
    assert code == 0, result["details"]["failures"]
    assert (
        "not judged: C2 and L1 hold their makers' data, and no deck holds a capacitor or an inductor: a deck "
        "runs a board part on it only under the part's reference"
    ) in result["details"]["warnings"]


@needs_engines
def test_deck_parts_not_named_by_board_reference_leave_the_makers_data_not_judged(tmp_path):
    """Lbuck and Cout in place of L1 and C2: the deck runs ideal, 3.04 mV, under the bound, and the gate
    says that C2 and L1 hold data no deck element carries."""
    project = fixture(tmp_path)
    deck = project / "sim" / "buck.cir"
    text = deck.read_text(encoding="utf-8").replace("L1 sw out", "Lbuck sw out").replace("C2 out", "Cout out")
    deck.write_text(text, encoding="utf-8")
    code, result = gate(project)
    assert code == 0, result["details"]["failures"]
    assert "parts" not in result["details"]["decks"]["buck"]
    assert (
        "not judged: C2 and L1 hold their makers' data, and no deck element carries their reference: "
        "a deck runs a board part on it only under the part's reference"
    ) in result["details"]["warnings"]


@needs_engines
def test_a_temperature_corner_runs_the_capacitor_on_its_temperature_curve(tmp_path):
    """C2's temperature share at 3.3 V goes from its 0 V curve's toward its maker's curve at 5 V, in
    proportion to the volts. At 5 V that curve keeps 1 - 0.7238110 = 0.2761890 at 85 C and
    1 - 0.7203582 = 0.2796418 at 27 C, against the 0.28288 the DC bias curve keeps at 5 V.

        85 C   0.85275 + (0.2761890 / 0.28288 - 0.85275) x 3.3 / 5 = 0.934324: 10u x 0.44288 x 0.934324
               = 4.1379 uF, and the ripple is 0.357 x 666.67n / (8 x 4.1379u) = 7.19 mV
        27 C   0.99743 + (0.2796418 / 0.28288 - 0.99743) x 3.3 / 5 = 0.991571: 4.3915 uF
        ratio  4.3915 / 4.1379 = 1.0613; the 2 curves multiplied, 0.44288 x 0.85275 at 85 C and
               0.44288 x 0.99743 at 27 C, would give 0.99743 / 0.85275 = 1.1697

    The ratio of the 2 runs leaves out what the formula leaves out: it is held within 2 %."""
    project = fixture(tmp_path)
    corners = {"temperature": {"values": [85], "source": "the fixture's requirement: 85 C"}}
    (project / "sim" / "corners.json").write_text(json.dumps(corners), encoding="utf-8")
    code, result = gate(project, "--deck", "buck")
    assert code == 1
    deck = result["details"]["decks"]["buck"]
    hot = deck["corners"]["envelope"]["vpp"]["max"]
    assert hot == pytest.approx(7.19e-3, rel=0.10)
    assert hot / deck["measures"]["vpp"] == pytest.approx(1.0613, rel=0.02)
    assert not [w for w in result["details"]["warnings"] if "moves with temperature" in w]


ESR_DECK = """esr: a square current of 0.5 A either way at 1.5 MHz into C2, from 0 V
I1 0 out PULSE(-0.5 0.5 0 1n 1n 332.33n 666.67n)
C2 out 0 10u
RLEAK out 0 1k
.control
tran 1n 20u uic
meas tran vmax max v(out) from=18u to=20u
meas tran vmin min v(out) from=18u to=20u
let vpp = vmax - vmin
print vpp
.endc
.end
"""


@needs_engines
def test_the_capacitor_s_esr_from_its_maker_s_data_moves_the_ripple_by_its_share(tmp_path):
    """C2's facts hold its ESR, 0.0034848 ohm at 1.5 MHz, read off Samsung's R graph. A square current
    of +0.5 A and -0.5 A: the capacitance's voltage is a triangle, and the ESR adds 0.5 x R at its top
    and takes 0.5 x R off its bottom: the ripple grows by 1.0 A x 0.0034848 = 3.4848 mV."""
    runs = {}
    for name in ("with", "without"):
        project = fixture(tmp_path / name)
        (project / "sim" / "esr.cir").write_text(ESR_DECK, encoding="utf-8")
        if name == "without":
            path = project / "library" / "facts" / "parts.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            del data["parts"][0]["esr"]
            path.write_text(json.dumps(data), encoding="utf-8")
        code, result = gate(project, "--deck", "esr")
        assert not result["details"]["failures"], result["details"]["failures"]
        runs[name] = result["details"]["decks"]["esr"]["measures"]["vpp"]
    assert runs["with"] - runs["without"] == pytest.approx(3.4848e-3, rel=0.02)


@needs_engines
def test_a_bundle_of_the_deck_carries_the_makers_data(tmp_path):
    """The bundle runs from another folder and prints the gate's numbers: the curves go with it."""
    code, result = gate(fixture(tmp_path), "--bundle", tmp_path / "bundle")
    assert not [f for f in result["details"]["failures"] if "bundle" in f], result["details"]["failures"]
    assert "pwl(temper," in (tmp_path / "bundle" / "buck" / "buck.cir").read_text(encoding="utf-8")
