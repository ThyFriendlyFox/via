"""`tools/ratings.py`: the cases a mutation run found untested.

The run made 431 single changes to the engine, 1 at a time, and ran `tests/test_ratings.py` on each:
205 of them passed it. Each test here fails on at least 1 of those changes. The engine has changed on
purpose since, and the tests that spoke of the old behaviour speak of the present one. The helpers
come from `tests/test_ratings.py`.
"""

from __future__ import annotations

import json
import types
from pathlib import Path

import pytest
from test_ratings import (
    ADJ_PINS,
    ADJUSTABLE,
    BUCK,
    BUCK_PINS,
    CAP,
    CARD,
    DIVIDER,
    EFFECTIVE,
    FIXED_BUCK,
    FIXED_BUCK_PINS,
    GND,
    LDO,
    LINEAR,
    MCU,
    MCU_FACTS,
    NASA,
    NASA_SOURCE,
    NETLIST,
    ON_V1P2,
    ON_VOUT,
    OUT_CAP,
    POWER_FET,
    RAILS,
    READ,
    RESISTOR,
    ROOT,
    STATED,
    SWITCHER,
    SWITCHER_PINS,
    TWO_PINS,
    V5,
    V12,
    board,
    buck_board,
    ceramic,
    changed,
    chip_resistor,
    circuit,
    entry,
    found,
    library,
    load,
    mcu,
    pin,
    power_fet,
    project,
    ratings,
    refused,
    regulator,
    resistor,
    second_stage,
    supply,
)

CERAMIC = f"[{NASA_SOURCE}, section C1, table 4, page 23 of 23]"

# ---------------------------------------------------------------- the Value of a passive part


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("4K7", 4.7e3),
        ("1G", 1e9),
        ("2MEG", 2e6),
        ("1meg", 1e6),
        ("10kohm", 10e3),
        ("47Ohm", 47.0),
        ("100ohms", 100.0),
    ],
)
def test_a_value_is_read_with_each_multiplier_and_each_unit_the_reader_names(text, number):
    assert ratings.part_value(text) == pytest.approx(number, rel=1e-12)


def test_a_value_with_decimals_on_both_sides_of_its_multiplier_is_none():
    """`4.7k7` is 2 numbers in 1 word: 4.7 kohm, or 4.77. The reader takes neither."""
    assert ratings.part_value("4.7k7") is None


# ---------------------------------------------------------------- the netlist


def test_a_net_that_names_a_part_the_netlist_does_not_hold_is_refused():
    stray = NETLIST.replace(
        '<node ref="R1" pin="1" pintype="passive"/>', '<node ref="R9" pin="1" pintype="passive"/>'
    )
    with pytest.raises(ValueError, match=r"net VIN names R9, which is no part of the netlist"):
        ratings.read_netlist(stray)


def test_a_netlist_with_no_nets_is_refused_and_says_so():
    with pytest.raises(ValueError, match="no <nets>"):
        ratings.read_netlist("<export version='E'><components/></export>")


def test_the_netlist_gives_each_part_its_fields():
    net = ratings.read_netlist(NETLIST)
    assert net.parts["R1"].fields == {"Footprint": "Resistor_SMD:R_0603_1608Metric", "Datasheet": ""}
    assert net.parts["R2"].fields == {}


# ---------------------------------------------------------------- resistors between held nets


def test_a_chain_of_3_free_nodes_is_solved():
    """4 equal resistors from 4 V to ground: the 3 nodes between stand at 3 V, 2 V and 1 V. The first
    column of the 3 equations holds a 0: the solver has to take the largest pivot."""
    spans = ratings.resistor_spans(
        [("V", "A", 1e3, 1e3), ("A", "B", 1e3, 1e3), ("B", "C", 1e3, 1e3), ("C", "GND", 1e3, 1e3)],
        {"V": (4.0, 4.0), "GND": (0.0, 0.0)},
    )
    assert spans == {
        "A": (pytest.approx(3.0), pytest.approx(3.0)),
        "B": (pytest.approx(2.0), pytest.approx(2.0)),
        "C": (pytest.approx(1.0), pytest.approx(1.0)),
    }


def test_a_resistor_whose_least_value_is_above_its_greatest_is_refused():
    with pytest.raises(ValueError, match="the resistor between V and A has the values 2000.0 and 1000.0"):
        ratings.resistor_spans([("V", "A", 2e3, 1e3)], {"V": (3.0, 3.3)})


def test_12_resistors_with_a_tolerance_are_4096_corners_and_are_solved_at_each():
    """6 resistors of 1 kohm at 10 % from a node to a rail of 1 to 5 V, and 6 to ground. The node is
    highest with the 6 above at 0.9 kohm and the 6 below at 1.1 kohm: 5 x 1.1 / 2.0 = 2.75 V. It is
    lowest the other way round, from 1 V: 0.9 / 2.0 = 0.45 V. The hull of the 2 rails says 0 to 5 V."""
    star = [("V", "X", 0.9e3, 1.1e3)] * 6 + [("X", "GND", 0.9e3, 1.1e3)] * 6
    spans = ratings.resistor_spans(star, {"V": (1.0, 5.0), "GND": (0.0, 0.0)})
    assert spans == {"X": (pytest.approx(0.45), pytest.approx(2.75))}


# ---------------------------------------------------------------- the span of each net


def test_a_supply_pin_and_a_pin_marked_not_connected_of_a_part_with_no_facts_put_nothing_on_a_net():
    """Neither net is declared: a regulator holds each. Were the pin a source nothing describes, its
    net would have no span."""
    net = board(
        U1={"1": ("V33", "OUT", "power_out")},
        U2={"1": ("V18", "OUT", "power_out")},
        U9={"1": ("V33", "VDD", "power_in"), "2": ("V18", "NC", "no_connect")},
    )
    got = ratings.net_spans(net, {"U1": supply(3.3), "U2": supply(1.8)}, {})
    assert got.stress == {"V33": (0.0, 3.3), "V18": (0.0, 1.8)}
    assert got.why == {}


def test_a_resistor_does_not_move_a_net_a_regulator_holds_whichever_pin_is_on_it():
    """Not modelled: the lift while the regulator is off. The rail keeps the regulator's span, and
    ground stays at 0 V, with the resistor drawn either way round."""
    for first, second in (("V5", "V33"), ("V33", "V5")):
        net = board(
            U1={"1": ("V33", "OUT", "power_out")},
            R1={"1": first, "2": second},
            R2={"1": "GND", "2": "V33"},
        )
        models = {"U1": supply(3.3), "R1": resistor(10e3), "R2": resistor(10e3)}
        got = ratings.net_spans(net, models, {"V5": (4.5, 5.5), **GND})
        assert got.stress == {"V33": (0.0, 3.3), "V5": (0.0, 5.5), "GND": (0.0, 0.0)}, first


def test_an_unknown_source_behind_a_resistor_leaves_a_held_net_its_span_and_takes_none_from_it():
    """A header behind 1 kohm onto a regulator's rail and onto a declared one. Each rail keeps its
    span, since a resistor does not move it, and the header's net has none, since nothing states it."""
    net = board(
        U1={"1": ("V33", "OUT", "power_out")},
        J1={"1": "EXT"},
        R1={"1": "EXT", "2": "V33"},
        R2={"1": "EXT", "2": "V5"},
    )
    models = {"U1": supply(3.3), "R1": resistor(1e3), "R2": resistor(1e3)}
    got = ratings.net_spans(net, models, {"V5": (4.5, 5.5)})
    assert got.stress == {"V33": (0.0, 3.3), "V5": (0.0, 5.5)}
    assert got.why == {"EXT": "J1 pin 1 can put a voltage on EXT that nothing states"}


def test_an_unknown_source_behind_a_transistor_takes_no_span_from_a_declared_net():
    net = board(Q1={"2": ("EXT", "S", "passive"), "3": ("V5", "D", "passive")}, J1={"1": "EXT"})
    got = ratings.net_spans(net, {"Q1": ratings.Model(passes=[("2", "3", False)])}, {"V5": (4.5, 5.5)})
    assert got.stress == {"V5": (0.0, 5.5)}
    assert got.why == {"EXT": "J1 pin 1 can put a voltage on EXT that nothing states"}


def test_a_net_2_parts_from_an_unknown_source_names_the_source_and_the_part_next_to_it():
    net = board(
        J1={"1": "EXT"}, R1={"1": "EXT", "2": "A"}, R2={"1": "A", "2": "B"}, C1={"1": "B", "2": "GND"}
    )
    got = ratings.net_spans(net, {"R1": resistor(1e3), "R2": resistor(1e3), "C1": CAP}, GND)
    assert got.why == {
        "EXT": "J1 pin 1 can put a voltage on EXT that nothing states",
        "A": "J1 pin 1 can put a voltage on EXT that nothing states; R1 joins the 2 nets",
        "B": "J1 pin 1 can put a voltage on EXT that nothing states; R2 joins the 2 nets",
    }


def test_an_output_between_a_negative_rail_and_a_positive_one_reaches_down_to_the_negative():
    """Its low level is its ground pin's net at its least, -5.2 V, and its sources hold it there too."""
    pins = {
        "1": ("V33", "VDD", "power_in"),
        "2": ("VNEG", "VSS", "power_in"),
        "3": ("SIG", "PA0", "bidirectional"),
    }
    net = board(U1=pins, C1={"1": "SIG", "2": "GND"})
    got = ratings.net_spans(net, {"U1": MCU, "C1": CAP}, {"VNEG": (-5.2, -4.8), **RAILS})
    assert got.stress["SIG"] == (-5.2, 3.3)
    assert got.held["SIG"] == (-5.2, 3.3)


def test_a_transistor_does_not_move_a_net_declared_at_0_volts_whichever_end_is_on_it():
    for first, second in (("VBAT", "GND"), ("GND", "VBAT")):
        net = board(Q1={"2": (first, "D", "passive"), "3": (second, "S", "passive")})
        models = {"Q1": ratings.Model(passes=[("2", "3", False)])}
        got = ratings.net_spans(net, models, {"VBAT": (3.0, 4.2), **GND})
        assert got.stress == {"VBAT": (0.0, 4.2), "GND": (0.0, 0.0)}, first


def test_a_transistor_passes_a_negative_rail_and_a_diode_never_pulls_its_cathode_down():
    """Behind a transistor from -5 V the net can stand at -5.2 V. A diode with its anode on that rail
    conducts only while its cathode is lower still: the cathode keeps its own low end."""
    negative = {"VNEG": (-5.2, -4.8)}
    net = board(
        Q1={"2": ("VNEG", "S", "passive"), "3": ("LOAD", "D", "passive")}, C1={"1": "LOAD", "2": "GND"}
    )
    models = {"Q1": ratings.Model(passes=[("2", "3", False)]), "C1": CAP}
    assert ratings.net_spans(net, models, {**negative, **GND}).stress["LOAD"] == (-5.2, 0.0)
    net = board(
        D1={"1": ("VNEG", "A", "passive"), "2": ("OUT", "K", "passive")},
        U1={"1": ("OUT", "OUT", "power_out")},
    )
    models = {"D1": ratings.Model(passes=[("1", "2", True)]), "U1": supply(3.3)}
    assert ratings.net_spans(net, models, negative).stress == {"VNEG": (-5.2, 0.0), "OUT": (0.0, 3.3)}


def test_an_output_whose_supply_net_has_no_span_has_none_and_says_which_pin():
    """Nothing holds V33. The output on SIG swings to it, so SIG has no span, and neither has the net
    a resistor ties to SIG. A net the project declares keeps what it declares."""
    net = board(U1=mcu(), R1={"1": "SIG", "2": "NODE"}, C1={"1": "NODE", "2": "GND"})
    models = {"U1": MCU, "R1": resistor(1e3), "C1": CAP}
    got = ratings.net_spans(net, models, GND)
    assert got.stress == {"GND": (0.0, 0.0)}
    assert got.why == {
        "SIG": "U1 pin 3 swings with its pin 1 on V33, which has no span",
        "NODE": "U1 pin 3 swings with its pin 1 on V33, which has no span; R1 joins the 2 nets",
    }
    stated = ratings.net_spans(net, models, {"SIG": (0.0, 3.3), **GND})
    assert stated.stress["SIG"] == (0.0, 3.3) and stated.why == {}


def test_a_drive_may_be_a_number_at_1_end_and_follow_a_pin_at_the_other():
    """An output from 0.5 V to its supply less 0.5 V: its sources hold the net at 0.5 to 2.8 V, and
    unpowered it stands at 0 V."""
    net = board(U1=mcu(), C1={"1": "SIG", "2": "GND"})
    model = ratings.Model(drives={"3": ratings.Drive(0.5, ("1", -0.5))}, quiet=frozenset({"1", "2"}))
    got = ratings.net_spans(net, {"U1": model, "C1": CAP}, RAILS)
    assert got.stress["SIG"] == (0.0, pytest.approx(2.8))
    assert got.held["SIG"] == (0.5, pytest.approx(2.8))


def test_a_net_of_1_pin_that_nothing_drives_is_not_named_among_the_nets_with_no_span():
    net = board(U1={"3": ("ALONE", "PA0", "input")}, C1={"1": "V33", "2": "GND"})
    got = ratings.net_spans(net, {"U1": ratings.Model(quiet=frozenset({"3"})), "C1": CAP}, RAILS)
    assert "ALONE" not in got.stress and got.why == {}


# ---------------------------------------------------------------- a rule's factor


def test_a_rule_counted_from_the_case_says_the_part_s_own_heating_is_not_counted():
    """A limit that falls with the ambient says nothing more once the project states one. A limit that
    falls with the case temperature is judged at the ambient, and the report says what that leaves out."""
    rule = ratings.Rule(
        "r", "capacitor.voltage", ("capacitor",), 0.5, "table 1", ("ambient", 70.0, 0.3, 110.0)
    )
    assert ratings.factor(rule, 60) == (0.5, "")
    assert ratings.factor(rule, 90) == (pytest.approx(0.4), "")
    case = ratings.Rule("r", "capacitor.voltage", ("capacitor",), 0.5, "table 1", ("case", 70.0, 0.3, 110.0))
    note = "r: the part's own heating above the ambient is not counted"
    assert ratings.factor(case, 60) == (0.5, note)
    assert ratings.factor(case, 120) == (0.0, note)


def test_at_the_last_temperature_a_rule_names_the_share_is_the_document_s_own_number():
    """0.9 + (0.1 - 0.9) is 0.09999999999999998 in binary: the document's 0.1 is returned as it is."""
    steep = ratings.Rule(
        "r", "capacitor.voltage", ("capacitor",), 0.9, "table 1", ("ambient", 70.0, 0.1, 110.0)
    )
    assert ratings.factor(steep, 110) == (0.1, "")


# ---------------------------------------------------------------- files the command does not take


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            changed(CARD, "document", "url", to=""),
            "pack.json: document: url: text is asked, and there is none",
        ),
        (
            changed(CARD, "rules", 0, "above", "falls_to", to=1.5),
            "pack.json: rule 1: above: falls_to: 1.5 is over 1",
        ),
        (changed(CARD, "rules", 0, "max", to=-0.1), "pack.json: rule 1: max: -0.1 is under 0"),
    ],
)
def test_more_packs_that_are_wrong_in_1_place_are_refused_with_the_place(tmp_path, data, message):
    assert refused(ratings.read_pack, tmp_path / "pack.json", data).startswith(message)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            changed(STATED, "parts", "R1.1", "amps", to=-0.01),
            "ratings.json: parts: R1.1: amps: -0.01 is under 0",
        ),
        (
            changed(STATED, "accepted", 0, "by", to="the owner's decision of 2026-11-17 or so"),
            "ratings.json: accepted: entry 1: by: write `the owner's decision of YYYY-MM-DD`",
        ),
        (
            changed(STATED, "ambient", "source", to=""),
            "ratings.json: ambient: source: text is asked, and there is none",
        ),
        (
            changed(STATED, "parts", "C1", "source", to=" "),
            "ratings.json: parts: C1: source: text is asked, and there is none",
        ),
        (
            changed(STATED, "parts", "Q1", to={"volts": 5, "source": "s"}),
            "ratings.json: parts: Q1: volts: the voltage across a part of 2 pins is asked",
        ),
        (
            changed(STATED, "parts", "R1.1", "amps", to=True),
            "ratings.json: parts: R1.1: amps: True is no number",
        ),
        (
            '{"pack": "p", "nets": {"V5": {"volts": [0, NaN], "source": "s"}}}',
            "ratings.json: nets: V5: volts: nan is no number",
        ),
    ],
)
def test_more_project_files_that_are_wrong_in_1_place_are_refused_with_the_place(tmp_path, data, message):
    net = board(C1={"1": "V5", "2": "GND"}, R1={"1": "V5", "2": "GND"}, Q1={"1": "V5", "2": "GND", "3": "V5"})
    assert refused(lambda p: ratings.read_project(p, net), tmp_path / "ratings.json", data).startswith(
        message
    )


def test_an_accepted_failure_is_read_as_its_part_its_rule_and_the_owner_s_words(tmp_path):
    """An entry is kept under its part and its rule, as the words of the line it means and the owner's
    words. An entry with no `line` means the part's 1 failure under the rule. 2 entries of 1 part
    under 1 rule name 1 line each, and are kept in the order of the file."""
    net = board(C1={"1": "V5", "2": "GND"}, R1={"1": "V5", "2": "GND"})
    path = tmp_path / "ratings.json"
    path.write_text(json.dumps(STATED), encoding="utf-8")
    words = "y (the owner's decision of 2026-11-17)"
    assert ratings.read_project(path, net).accepted == {("C1", "x"): [("", words)]}
    named = [{**STATED["accepted"][0], "line": line} for line in ("pin IN", "pin OUT")]
    path.write_text(json.dumps(changed(STATED, "accepted", to=named)), encoding="utf-8")
    assert ratings.read_project(path, net).accepted == {("C1", "x"): [("pin IN", words), ("pin OUT", words)]}


def test_a_net_declared_with_a_slash_is_found_when_the_schematic_writes_it_with_none(tmp_path):
    net = board(C1={"1": "/SENSE", "2": "GND"})
    path = tmp_path / "ratings.json"
    path.write_text(
        json.dumps({"pack": "p", "nets": {"/GND": {"volts": [0, 0], "source": "s"}}}), encoding="utf-8"
    )
    assert ratings.read_project(path, net).nets == {"GND": (0.0, 0.0)}


DIODE = entry("diode.rectifier", "D-1", diodes=[{"anode": "1", "cathode": "2"}], volts_reverse=30)
NEEDY = regulator(needs=[OUT_CAP])
OPEN_DRAIN = changed(
    {**MCU_FACTS, "mpn": "MCU-OD"},
    "pins",
    2,
    to=pin("SDA", ["3"], "open_drain", abs=[-0.3, 5.5], swing=["VSS"]),
)


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (
            {k: v for k, v in RESISTOR.items() if k != "mpn"},
            "x.json: exactly 1 of mpn, mpns, match, symbol says which parts the entry speaks of",
        ),
        (
            changed(RESISTOR, "source", "second_reader", to=""),
            "x.json: source: second_reader: text is asked, and there is none",
        ),
        (changed(RESISTOR, "watts", to="0.1"), "x.json: watts: '0.1' is no number"),
        (changed(DIODE, "volts_reverse", to=-30), "x.json: volts_reverse: -30 is not above 0"),
        (changed(DIODE, "diodes", to=[]), "x.json: diodes: a list is asked"),
        (
            power_fet(amps_drain=[[25, 4.0]]),
            "x.json: amps_drain: a number is asked, or 2 or more pairs [celsius, amps]",
        ),
        (
            power_fet(amps_drain=[[70, 3.2], [25, 4.0]]),
            "x.json: amps_drain: the celsius rise from pair to pair",
        ),
        (ceramic("C-1", 16, kept=[[0, 1.0], [5, 2.0]]), "x.json: kept: fraction: 2 is over 1.5"),
        (
            entry("connector", "HDR-1", pins=[{"numbers": ["1"], "outside": "sink"}]),
            "x.json: pin 1: outside: one of source, load, nothing is asked",
        ),
        (
            changed(SWITCHER, "switching", "efficiency", to=1.5),
            "x.json: switching: efficiency: 1.5 is over 1",
        ),
        (changed(MCU_FACTS, "pins", to=[]), "x.json: pins: a list of pins is asked"),
        (
            changed(MCU_FACTS, "pins", 0, "numbers", to=[1]),
            "x.json: pin VDD: numbers: a list of names is asked",
        ),
        (
            changed(MCU_FACTS, "pins", 0, "page", to=0),
            "x.json: pin VDD: page: a page number is asked, or a list of them",
        ),
        (
            changed(MCU_FACTS, "pins", 0, "operating", to=[3.6, 1.7]),
            "x.json: pin VDD: operating: the span's first number, 3.6, is above its second, 1.7",
        ),
        (changed(MCU_FACTS, "pins", 0, "amps", to=-0.05), "x.json: pin VDD: amps: -0.05 is under 0"),
        (
            changed(MCU_FACTS, "pins", 2, "swing", to=["VSS"]),
            "x.json: pin PA0: swing: 2 of this part's pin names are asked, of VDD, VSS, PA0",
        ),
        (
            changed(OPEN_DRAIN, "pins", 2, "swing", to=["VSS", "VDD"]),
            "x.json: pin SDA: swing: 1 of this part's pin names are asked, of VDD, VSS, SDA",
        ),
        (
            changed(ADJUSTABLE, "pins", 2, "set_by", drop=True),
            "x.json: pin OUT: `volts`, or `set_by` with the name of its feedback pin: 1 of the 2",
        ),
        (
            changed(ADJUSTABLE, "pins", 2, "from", to="IN"),
            "x.json: pin OUT: `from` stands on the feedback pin FB",
        ),
        (
            changed(NEEDY, "pins", 2, "from", to="GND"),
            "x.json: pin OUT: from: `GND` is no pin of role supply",
        ),
        (
            changed(SWITCHER, "needs", 0, "page", to="12"),
            "x.json: needs 1: page: a page number is asked, or a list of them",
        ),
        (
            changed(SWITCHER, "needs", 0, "inductor", "from", to="LX"),
            "x.json: needs 1: inductor: from: `LX` is no pin name of this part",
        ),
        (
            changed(BUCK, "needs", 0, "inductor", "henries", to=[4.7e-6, 1.5e-6]),
            "x.json: needs 1: inductor: henries: the span's first number, 4.7e-06, is above its second, "
            "1.5e-06",
        ),
        (
            changed(NEEDY, "needs", 0, "capacitor", "farads_min", to=-1e-6),
            "x.json: needs 1: capacitor: farads_min: -1e-06 is not above 0",
        ),
        (
            changed(NEEDY, "needs", 0, "capacitor", "effective", to="yes"),
            "x.json: needs 1: capacitor: effective: true or false is asked",
        ),
    ],
)
def test_more_facts_that_are_wrong_in_1_place_are_refused_with_the_place(tmp_path, data, message):
    for holds in (DIODE, NEEDY, OPEN_DRAIN, BUCK, power_fet(amps_drain=[[25, 4.0], [70, 3.2]])):
        (tmp_path / "x.json").write_text(json.dumps(holds), encoding="utf-8")
        assert len(ratings.read_facts(tmp_path)) == 1
    assert refused(lambda p: ratings.read_facts(p.parent), tmp_path / "x.json", data).startswith(message)


# ---------------------------------------------------------------- how an entry names its parts


def test_an_entry_of_several_part_numbers_is_named_by_the_first_and_a_source_with_no_revision_by_its_document(
    tmp_path,
):
    net, mpns = circuit(C1=("10u", "C-25V-B", {"1": "V12", "2": "GND"}))
    several = {k: v for k, v in ceramic("", 25).items() if k != "mpn"}
    several |= {"mpns": ["C-25V-A", "C-25V-B"], "note": "its bias curve is not entered"}
    several["source"] = {k: v for k, v in READ.items() if k != "revision"}
    bare = ratings.Pack("bare", NASA.document, [])
    report = ratings.judge(net, mpns, library(tmp_path, several), project({"V12": (11.4, 12.6), **GND}), bare)
    assert report.notes == ["C1 (C-25V-A): its bias curve is not entered"]
    assert [f.line for f in report.findings] == [
        "hold C1 10u between V12 and GND: 12.6 V on 25 V rated is 0.50, the limit is 1.00 "
        "[DS-1: the part's own rating]"
    ]


def test_a_part_whose_value_is_its_name_takes_the_value_its_facts_hold(tmp_path):
    """The schematic says `XAL4020-222` and the facts say 2.2 uH: 1.76 to 2.64 uH at 20 %. Without
    the facts' value the need says which Value it could not read."""
    net, mpns = circuit(U1=("BUCK", "BUCK-1", BUCK_PINS), L1=("XAL4020-222", "L-1", {"1": "SW", "2": "V33"}))
    nets = {"V12": (11.4, 12.6), "V33": (3.2, 3.4), **GND}
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=2.0, henries=2.2e-6)
    report = ratings.judge(net, mpns, library(tmp_path, BUCK, coil), project(nets), NASA)
    assert (
        "hold U1 pin SW (SW) needs 1.5 uH to 4.7 uH, L1 is 1.76 uH to 2.64 uH [DS-1, rev A, p 12]"
        in found(report, "hold")
    )
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=2.0)
    report = ratings.judge(net, mpns, library(tmp_path, BUCK, coil), project(nets), NASA)
    assert found(report, "not judged") == ["not judged U1 pin SW (SW): the Value of L1 is no number"]


# ---------------------------------------------------------------- what a part does to its nets


def test_a_0_ohm_resistor_joins_its_2_nets_and_has_no_power_to_judge(tmp_path):
    """Behind the link the capacitor sees the rail's 5.5 V: 0.87 of its 6.3 V."""
    net, mpns = circuit(
        R1=("0", "R-0402", {"1": "V5", "2": "V5F"}), C1=("10u", "C-6V3", {"1": "V5F", "2": "GND"})
    )
    facts = library(tmp_path, chip_resistor(), ceramic("C-6V3", 6.3))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert found(report, "fail") == [
        f"fail C1 10u between V5F and GND: 5.5 V on 6.3 V rated is 0.87, the limit is 0.60 {CERAMIC}"
    ]
    assert [f.rule for f in report.findings if f.part == "R1"] == ["resistor.voltage"]


def test_a_resistor_whose_value_is_no_number_may_conduct_and_its_power_is_not_judged(tmp_path):
    """A thermistor named by its part: nothing says its resistance. The net behind it can stand
    anywhere between the rail and ground, so the capacitor there is held to the rail's 5.5 V."""
    net, mpns = circuit(
        R1=("NTC", "R-0402", {"1": "V5", "2": "NODE"}), C1=("10u", "C-6V3", {"1": "NODE", "2": "GND"})
    )
    facts = library(tmp_path, chip_resistor(), ceramic("C-6V3", 6.3))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert found(report, "not judged") == ["not judged R1 NTC between V5 and NODE: its Value is no number"]
    assert found(report, "fail") == [
        f"fail C1 10u between NODE and GND: 5.5 V on 6.3 V rated is 0.87, the limit is 0.60 {CERAMIC}"
    ]


@pytest.mark.parametrize("kind", ["fuse", "ferrite", "link"])
def test_a_fuse_a_ferrite_and_a_link_join_their_2_nets(tmp_path, kind):
    """Behind each the capacitor sees the rail's 5.5 V."""
    net, mpns = circuit(
        F1=("X", "F-1", {"1": "V5", "2": "V5F"}), C1=("10u", "C-6V3", {"1": "V5F", "2": "GND"})
    )
    wire = entry(kind, "F-1", **({"amps": 1.0} if kind == "fuse" else {}))
    report = ratings.judge(net, mpns, library(tmp_path, wire, ceramic("C-6V3", 6.3)), project(V5), NASA)
    assert found(report, "fail") == [
        f"fail C1 10u between V5F and GND: 5.5 V on 6.3 V rated is 0.87, the limit is 0.60 {CERAMIC}"
    ]


def test_a_switch_may_conduct_either_way(tmp_path):
    """Closed, the rail's 5.5 V stands behind it, whichever of its pins is on the rail."""
    for pins in ({"1": "V5", "2": "V5S"}, {"1": "V5S", "2": "V5"}):
        net, mpns = circuit(SW1=("SPST", "SW-1", pins), C1=("10u", "C-6V3", {"1": "V5S", "2": "GND"}))
        facts = library(tmp_path, entry("switch", "SW-1"), ceramic("C-6V3", 6.3))
        report = ratings.judge(net, mpns, facts, project(V5), NASA)
        assert found(report, "fail") == [
            f"fail C1 10u between V5S and GND: 5.5 V on 6.3 V rated is 0.87, the limit is 0.60 {CERAMIC}"
        ], pins


HEADER = entry(
    "connector",
    "HDR-3",
    pins=[
        {"numbers": ["1"], "outside": "source"},
        {"numbers": ["2"], "outside": "load"},
        {"numbers": ["3"], "outside": "nothing"},
    ],
)


def test_a_connector_pin_is_a_source_only_where_its_facts_say_a_source_stands_behind_it(tmp_path):
    net, mpns = circuit(
        J1=("HDR", "HDR-3", {"1": "IN", "2": "OUT", "3": "SPARE"}),
        C1=("100n", "C-16V", {"1": "IN", "2": "GND"}),
        C2=("100n", "C-16V", {"1": "OUT", "2": "GND"}),
        C3=("100n", "C-16V", {"1": "SPARE", "2": "GND"}),
    )
    report = ratings.judge(net, mpns, library(tmp_path, HEADER, ceramic("C-16V", 16)), project(GND), NASA)
    assert found(report, "not judged") == [
        "not judged C1 100n between IN and GND: IN has no span: "
        "J1 pin 1 can put a voltage on IN that nothing states",
        "not judged C2 100n between OUT and GND: OUT has no span: nothing drives it",
        "not judged C3 100n between SPARE and GND: SPARE has no span: nothing drives it",
    ]


def test_a_diode_from_a_low_rail_to_a_high_one_never_lifts_the_low_rail(tmp_path):
    """The diode blocks the 12 V: the capacitor on the 5 V side sees 5.5 V, 0.34 of its 16 V. Read
    the wrong way round, or as a part that conducts both ways, it would see 12.6 V and fail."""
    net, mpns = circuit(
        D1=("SS14", "D-1", {"1": ("V5", "A", "passive"), "2": ("V12", "K", "passive")}),
        C1=("10u", "C-16V", {"1": "V5", "2": "GND"}),
    )
    nets = {"V12": (11.4, 12.6), **V5}
    report = ratings.judge(net, mpns, library(tmp_path, DIODE, ceramic("C-16V", 16)), project(nets), NASA)
    assert found(report, "fail") == []
    assert f"hold C1 10u between V5 and GND: 5.5 V on 16 V rated is 0.34, the limit is 0.60 {CERAMIC}" in (
        found(report, "hold")
    )


def test_a_transistor_s_second_drain_pin_is_no_source_on_a_net_nothing_declares(tmp_path):
    """The load is no declared net: 10 kohm pulls it up to 12 V, and its span comes through the
    resistor. Each of the 2 drain pins on it is the drain, and neither is a source nothing describes."""
    net, mpns = circuit(Q1=("FET", "FET-2", POWER_FET), R1=("10k", "R-0402", {"1": "V12", "2": "LOAD"}))
    nets = {"V12": (11.4, 12.6), "GATE": (0.0, 3.6), **GND}
    report = ratings.judge(net, mpns, library(tmp_path, power_fet(), chip_resistor()), project(nets), NASA)
    assert found(report, "not judged") == []
    assert "hold Q1 FET drain LOAD to source GND: 12.6 V on 30 V rated is 0.42, the limit is 0.75" in [
        f.line.split(" [")[0] for f in report.findings
    ]


def test_an_open_drain_pin_pulls_its_net_down_and_its_pull_up_lifts_it(tmp_path):
    """The pin swings to its ground pin alone: with nothing else on the net the pin beside it sees
    0 V. Released, a 5 V pull-up puts 5.5 V there, on a pin that takes 3.3 V."""
    pins = {
        "1": ("V33", "VDD", "power_in"),
        "2": ("GND", "VSS", "power_in"),
        "3": ("SDA", "SDA", "open_collector"),
    }
    parts = {"U1": ("OD", "MCU-OD", pins), "U2": ("MCU", "MCU-1", mcu("SDA"))}
    facts = library(tmp_path, OPEN_DRAIN, MCU_FACTS, chip_resistor())
    net, mpns = circuit(**parts)
    report = ratings.judge(net, mpns, facts, project(RAILS), NASA)
    assert [f.line for f in report.findings if f.part == "U2.3"] == [
        "hold U2 pin 3 (PA0) on SDA: 0 to 0 V can stand on it, its limits are -0.3 V and 3.3 V "
        "(pin VDD at 3 V, +0.3 V) [DS-1, rev A, p 4]"
    ]
    net, mpns = circuit(**parts, R1=("4.7k", "R-0402", {"1": "V5", "2": "SDA"}))
    report = ratings.judge(net, mpns, facts, project({"V5": (4.5, 5.5), **RAILS}), NASA)
    assert found(report, "fail") == [
        "fail U2 pin 3 (PA0) on SDA: 5.5 V can stand on it, its limit is 3.3 V "
        "(pin VDD at 3 V, +0.3 V) [DS-1, rev A, p 4]"
    ]
    assert (
        "hold U1 pin 3 (SDA) on SDA: 0 to 5.5 V can stand on it, its limits are -0.3 V and 5.5 V "
        "[DS-1, rev A, p 4]" in found(report, "hold")
    )


# ---------------------------------------------------------------- an output a divider sets


def test_a_limit_that_follows_a_rail_a_divider_sets_is_judged_with_the_rail_at_its_least(tmp_path):
    """The pin takes VDD + 0.1 V and a pull-up ties it to VDD, which the divider puts at 3.2487 to
    3.4166 V. With the rail at 3.2487 V the pin sees 3.2487 V against 3.3487 V. Were the regulator
    still to hold the rail's whole span there, the pin would see 3.4166 V and fail."""
    close = changed(MCU_FACTS, "pins", 2, "abs", to=[-0.3, {"pin": "VDD", "plus": 0.1}])
    pins = {
        "1": ("VOUT", "VDD", "power_in"),
        "2": ("GND", "VSS", "power_in"),
        "3": ("SIG", "PA0", "bidirectional"),
    }
    net, mpns = circuit(
        U1=("ADJ", "ADJ-1", ADJ_PINS),
        U2=("MCU", "MCU-1", pins),
        R3=("4.7k", "R-0402", {"1": "VOUT", "2": "SIG"}),
        **DIVIDER,
    )
    report = ratings.judge(
        net, mpns, library(tmp_path, ADJUSTABLE, close, chip_resistor()), project(V5), NASA
    )
    assert found(report, "fail") == []
    assert [f.line for f in report.findings if f.part == "U2.3"] == [
        "hold U2 pin 3 (PA0) on SIG: 0 to 3.25 V can stand on it, its limits are -0.3 V and 3.35 V "
        "(pin VDD at 3.25 V, +0.1 V) [DS-1, rev A, p 4]"
    ]


def test_a_capacitor_on_a_divider_s_tap_does_not_stop_the_divider_being_read(tmp_path):
    """A capacitor across the top resistor puts no voltage on the tap."""
    net, mpns = circuit(
        U1=("ADJ", "ADJ-1", ADJ_PINS), C1=("22p", "C-16V", {"1": "VOUT", "2": "FB"}), **DIVIDER
    )
    facts = library(tmp_path, ADJUSTABLE, chip_resistor(), ceramic("C-16V", 16))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert found(report, "not judged") == []
    assert (
        "U1 holds VOUT at 3.25 to 3.42 V: its pin FB at 0.792 to 0.808 V, R1 over R2 "
        "[TI SLVA477C, equation 11]"
    ) in report.notes


@pytest.mark.parametrize(
    ("part", "facts", "pin_"),
    [
        (("SPST", "SW-1", {"1": "FB", "2": "GND"}), entry("switch", "SW-1"), "1"),
        (("0", "R-0402", {"1": "TP", "2": "FB"}), None, "2"),
        (
            ("HDR", "HDR-1", {"1": "FB"}),
            entry("connector", "HDR-1", pins=[{"numbers": ["1"], "outside": "source"}]),
            "1",
        ),
        (("MCU", "MCU-1", {**mcu("FB"), "1": ("V5", "VDD", "power_in")}), MCU_FACTS, "3"),
    ],
)
def test_a_part_that_can_move_a_divider_s_tap_leaves_the_output_not_judged(tmp_path, part, facts, pin_):
    """A switch to ground, a 0 ohm link to another net, a connector's pin with a source behind it and
    an output: none is a resistor of the divider, and each can move the tap."""
    net, mpns = circuit(U1=("ADJ", "ADJ-1", ADJ_PINS), X1=part, **DIVIDER)
    entries = [ADJUSTABLE, chip_resistor(), *([facts] if facts else [])]
    report = ratings.judge(net, mpns, library(tmp_path, *entries), project(V5), NASA)
    assert (
        f"not judged U1 pin 4 (FB) on FB: X1 pin {pin_} stands on FB too, and is no resistor of a divider"
        in found(report, "not judged")
    )


def test_a_pin_that_drives_on_a_divider_s_tap_is_no_resistor_of_the_divider():
    """A model whose pins are all named: `quiet` is None, and the pin that drives is no quiet one."""
    net = board(
        U1={"4": ("FB", "FB", "input")},
        U2={"1": ("FB", "OUT", "output")},
        R1={"1": "VOUT", "2": "FB"},
        R2={"1": "FB", "2": "GND"},
    )
    models = {
        "U2": ratings.Model(drives={"1": ratings.Drive(0.0, 3.3)}),
        "R1": resistor(100e3),
        "R2": resistor(31.6e3),
    }
    assert ratings.divider_output(net, models, "U1", "4", (0.792, 0.808), {"GND"}) == (
        "U2 pin 1 stands on FB too, and is no resistor of a divider"
    )


def test_a_feedback_pin_on_the_output_itself_holds_the_output_at_its_own_voltage(tmp_path):
    """No resistor stands between the pin's net and ground: the output is fed back whole, and what
    stands on the net is its load. 150 mA of the 300 mA the regulator gives is 0.50."""
    pins = {**ADJ_PINS, "4": ("VOUT", "FB", "input")}
    net, mpns = circuit(U1=("ADJ", "ADJ-1", pins), U2=("A", "LOAD-A", ON_VOUT))
    report = ratings.judge(net, mpns, library(tmp_path, ADJUSTABLE, load("LOAD-A", 0.15)), project(V5), NASA)
    assert report.notes == [
        "U1 holds VOUT at 0.792 to 0.808 V: its pin FB at 0.792 to 0.808 V, fed back whole"
    ]
    assert found(report, "not judged") == []
    assert (
        "hold VOUT: U1 pin 4 (FB) gives 300 mA, its loads take 150 mA: 0.50, the limit is 0.70 "
        f"[{NASA_SOURCE}, {LINEAR}]" in found(report, "hold")
    )


def test_the_efficiency_the_command_takes_is_said_1_time_for_a_regulator(tmp_path):
    """The load it passes up and its inductor's ripple both take the 0.9."""
    report = second_stage(FIXED_BUCK, tmp_path)
    said = "U2: its facts state no efficiency, and 0.9 is taken [TI SLVA477C, section 2]"
    assert report.notes.count(said) == 1


# ---------------------------------------------------------------- the judgement


def test_the_voltage_across_a_part_is_the_greatest_between_its_2_nets_whichever_pin_is_on_which(tmp_path):
    """Either rail can be off while the other is on: between 12.6 V and 5.5 V a part sees 12.6 V, and
    so does a part drawn with its first pin on ground."""
    net, mpns = circuit(
        C1=("10u", "C-16V", {"1": "GND", "2": "V12"}),
        C2=("10u", "C-16V", {"1": "V12", "2": "V5"}),
        C3=("10u", "C-16V", {"1": "V5", "2": "V12"}),
    )
    nets = {"V12": (11.4, 12.6), **V5}
    report = ratings.judge(net, mpns, library(tmp_path, ceramic("C-16V", 16)), project(nets), NASA)
    assert found(report, "fail") == [
        f"fail C1 10u between GND and V12: 12.6 V on 16 V rated is 0.79, the limit is 0.60 {CERAMIC}",
        f"fail C2 10u between V12 and V5: 12.6 V on 16 V rated is 0.79, the limit is 0.60 {CERAMIC}",
        f"fail C3 10u between V5 and V12: 12.6 V on 16 V rated is 0.79, the limit is 0.60 {CERAMIC}",
    ]


def test_a_failure_of_a_part_s_own_rating_is_accepted_under_the_stress_s_name(tmp_path):
    """No rule of the pack covers an electrolytic capacitor: 12.6 V on 10 V fails at 1.00, and the
    rule the page tells the owner to name is the stress."""
    net, mpns = circuit(C1=("100u", "C-EL", {"1": "V12", "2": "GND"}))
    facts = library(tmp_path, entry("capacitor.electrolytic", "C-EL", tolerance=0.2, volts=10))
    nets = {"V12": (11.4, 12.6), **GND}
    report = ratings.judge(net, mpns, facts, project(nets), NASA)
    assert [(f.status, f.part, f.rule) for f in report.findings] == [("fail", "C1", "capacitor.voltage")]
    assert "  - to accept it, the owner names part `C1` and rule `capacitor.voltage`" in ratings.markdown(
        report
    )
    owner = {("C1", "capacitor.voltage"): "x (the owner's decision of 2026-11-17)"}
    report = ratings.judge(net, mpns, facts, project(nets, accepted=owner), NASA)
    assert [f.status for f in report.findings] == ["accepted"]


def test_the_page_offers_acceptance_under_a_failure_and_under_nothing_else(tmp_path):
    """C1 holds and its entry of `accepted` is stale; C2 fails. The stale entry is a failure of the
    rule `accepted`, which no owner can accept, and a hold is nothing to accept."""
    net, mpns = circuit(
        C1=("10u", "C-25V", {"1": "V12", "2": "GND"}), C2=("10u", "C-10V", {"1": "V12", "2": "GND"})
    )
    owner = {("C1", "capacitor.ceramic.voltage"): "x (the owner's decision of 2026-11-17)"}
    facts = library(tmp_path, ceramic("C-25V", 25), ceramic("C-10V", 10))
    report = ratings.judge(net, mpns, facts, project({"V12": (11.4, 12.6), **GND}, accepted=owner), NASA)
    assert [(f.part, f.rule) for f in report.findings if f.status == "fail"] == [
        ("C2", "capacitor.ceramic.voltage"),
        ("C1", "accepted"),
    ]
    page = ratings.markdown(report)
    assert page.count("to accept it") == 1
    assert "  - to accept it, the owner names part `C2` and rule `capacitor.ceramic.voltage`" in page


def test_what_a_rule_says_of_the_ambient_is_said_1_time_for_all_its_parts(tmp_path):
    net, mpns = circuit(
        C1=("10u", "C-TA", {"1": "V5", "2": "GND"}), C2=("10u", "C-TA", {"1": "V5", "2": "GND"})
    )
    facts = library(tmp_path, entry("capacitor.tantalum", "C-TA", tolerance=0.1, volts=10))
    cold = ratings.judge(net, mpns, facts, project({"V5": (4.4, 4.5), **GND}), NASA)
    assert cold.notes == [
        "capacitor.tantalum.voltage: judged as under 70 C, since the project states no ambient"
    ]


def test_a_stress_that_equals_its_limit_holds(tmp_path):
    """9.6 V on a 16 V part is 0.60 of its rating, and NASA allows a ceramic capacitor 0.60."""
    net, mpns = circuit(C1=("10u", "C-16V", {"1": "V9", "2": "GND"}))
    report = ratings.judge(
        net, mpns, library(tmp_path, ceramic("C-16V", 16)), project({"V9": (9.0, 9.6), **GND}), NASA
    )
    assert [f.line for f in report.findings] == [
        f"hold C1 10u between V9 and GND: 9.6 V on 16 V rated is 0.60, the limit is 0.60 {CERAMIC}"
    ]


def test_a_rail_loaded_to_exactly_its_limit_holds(tmp_path):
    """50 mA and 90 mA on a 200 mA regulator is 0.70, and NASA allows 0.70. In binary 0.2 x 0.7 falls
    a last bit under 0.14: that bit does not decide."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), U2=("A", "LOAD-A", TWO_PINS), U3=("B", "LOAD-B", TWO_PINS))
    facts = library(tmp_path, regulator(), load("LOAD-A", 0.05), load("LOAD-B", 0.09))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert found(report, "fail") == []
    assert any("its loads take 140 mA: 0.70, the limit is 0.70" in f.text for f in report.findings)


# 5.5 V across 1 kohm less 1 % is 30.6 mW; 3.3 V across it is 11 mW.
FLOWS = "with 5.5 V across it: 30.6 mW on 62.5 mW rated is 0.49, the limit is 0.50"
NONE = "no steady current: one end meets no source: 0 W on 62.5 mW rated is 0.00, the limit is 0.50"
ONLY_V5 = {"V5": (4.5, 5.5)}


@pytest.mark.parametrize(("kind", "flows"), [("input", False), ("no_connect", False), ("power_in", True)])
def test_a_resistor_into_a_part_with_no_facts_carries_a_current_into_its_supply_pin_alone(
    tmp_path, kind, flows
):
    """KiCad's pin type says what a pin of an unknown part can take: a supply pin takes a steady
    current, an input and a pin not connected inside take none."""
    net, mpns = circuit(
        R1=("1k", "R-0402", {"1": "V5", "2": "NODE"}), U9=("X", "", {"1": ("NODE", "P", kind)})
    )
    report = ratings.judge(net, mpns, library(tmp_path, chip_resistor()), project(ONLY_V5), NASA)
    assert [f.text for f in report.findings if f.rule == "resistor.power"] == [
        f"R1 1k between V5 and NODE, {FLOWS if flows else NONE}"
    ]


@pytest.mark.parametrize(
    ("role", "flows"), [("input", False), ("analog", False), ("nc", False), ("io", True), ("output", True)]
)
def test_a_resistor_into_a_pin_of_an_ic_carries_a_current_unless_the_pin_s_role_takes_none(
    tmp_path, role, flows
):
    keys = {} if role == "nc" else {"abs": [-0.5, 6.0]} | ({"swing": ["VSS", "VDD"]} if flows else {})
    chip = changed(MCU_FACTS, "pins", 2, to=pin("PA0", ["3"], role, **keys))
    net, mpns = circuit(U1=("MCU", "MCU-1", mcu("NODE")), R1=("1k", "R-0402", {"1": "V33", "2": "NODE"}))
    report = ratings.judge(net, mpns, library(tmp_path, chip, chip_resistor()), project(RAILS), NASA)
    how = "with 3.3 V across it: 11 mW on 62.5 mW rated is 0.18" if flows else NONE.split(", the")[0]
    assert [f.text for f in report.findings if f.rule == "resistor.power"] == [
        f"R1 1k between V33 and NODE, {how}, the limit is 0.50"
    ]


def test_a_resistor_into_a_capacitor_or_a_test_point_alone_carries_no_steady_current(tmp_path):
    facts = library(tmp_path, chip_resistor(), ceramic("C-16V", 16), entry("testpoint", "TP-1"))
    for other in (("100n", "C-16V", {"1": "NODE", "2": "GND"}), ("TP", "TP-1", {"1": "NODE"})):
        net, mpns = circuit(R1=("1k", "R-0402", {"1": "V5", "2": "NODE"}), X1=other)
        report = ratings.judge(net, mpns, facts, project(ONLY_V5), NASA)
        assert [f.text for f in report.findings if f.rule == "resistor.power"] == [
            f"R1 1k between V5 and NODE, {NONE}"
        ], other[0]


def test_a_resistor_into_a_connector_pin_carries_a_current_unless_nothing_stands_behind_the_pin(tmp_path):
    net, mpns = circuit(
        J1=("HDR", "HDR-3", {"1": "V5", "2": "TO_LOAD", "3": "SPARE"}),
        R1=("1k", "R-0402", {"1": "V5", "2": "TO_LOAD"}),
        R2=("1k", "R-0402", {"1": "V5", "2": "SPARE"}),
    )
    report = ratings.judge(net, mpns, library(tmp_path, HEADER, chip_resistor()), project(ONLY_V5), NASA)
    assert [f.text for f in report.findings if f.rule == "resistor.power"] == [
        f"R1 1k between V5 and TO_LOAD, {FLOWS}",
        f"R2 1k between V5 and SPARE, {NONE}",
    ]


def test_an_inductor_is_held_to_the_current_the_project_states_for_it(tmp_path):
    """On a steady rail, and on a buck's output in place of the peak the command works out."""
    net, mpns = circuit(
        L1=("10u", "L-1", {"1": "V5", "2": "V5F"}), C1=("10u", "C-16V", {"1": "V5F", "2": "GND"})
    )
    for saturation, status in ((2.0, "hold"), (1.0, "fail")):
        coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=saturation)
        report = ratings.judge(
            net, mpns, library(tmp_path, coil, ceramic("C-16V", 16)), project(V5, amps={"L1": 1.5}), NASA
        )
        assert [f.line for f in report.findings if f.part == "L1"] == [
            f"{status} L1 10u: the project states 1.5 A, and it saturates at {saturation:g} A "
            "[DS-1, rev A: the part's own rating]"
        ]
    net, mpns = buck_board()
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=2.0)
    facts = library(tmp_path, SWITCHER, coil, chip_resistor(), load("LOAD-A", 1.0))
    report = ratings.judge(net, mpns, facts, project(V12, amps={"L1": 1.9}), NASA)
    assert [f.line for f in report.findings if f.part == "L1"] == [
        "hold L1 2.2u: the project states 1.9 A, and it saturates at 2 A [DS-1, rev A: the part's own rating]"
    ]


def test_a_current_stated_for_a_part_whose_facts_rate_none_leaves_its_voltages_judged(tmp_path):
    """A diode with no `amps_forward` and a transistor with no `amps_drain`: the run does not stop."""
    net, mpns = circuit(D1=("SS14", "D-1", {"1": ("VBUS", "A", "passive"), "2": ("V12", "K", "passive")}))
    nets = {"VBUS": (4.4, 5.5), "V12": (11.4, 12.6)}
    report = ratings.judge(net, mpns, library(tmp_path, DIODE), project(nets, amps={"D1": 0.6}), NASA)
    assert "diode.reverse" in [f.rule for f in report.findings]
    net, mpns = circuit(Q1=("FET", "FET-2", POWER_FET))
    nets = {"LOAD": (0.0, 12.6), "GATE": (0.0, 3.3), **GND}
    report = ratings.judge(net, mpns, library(tmp_path, power_fet()), project(nets, amps={"Q1": 4.0}), NASA)
    assert {"mosfet.drain_source", "mosfet.gate_source"} <= {f.rule for f in report.findings}


@pytest.mark.parametrize(
    ("kind", "rating", "rule"),
    [
        ("diode.rectifier", {"volts_reverse": 30}, "diode.reverse"),
        ("diode.clamp", {"volts_standoff": 5.5}, "diode.standoff"),
    ],
)
def test_a_diode_on_a_net_with_no_span_is_not_judged_and_says_why(tmp_path, kind, rating, rule):
    net, mpns = circuit(
        D1=("D", "D-1", {"1": ("GND", "A", "passive"), "2": ("EXT", "K", "passive")}),
        J1=("Conn", "", {"1": "EXT"}),
    )
    diode = entry(kind, "D-1", diodes=[{"anode": "1", "cathode": "2"}], **rating)
    report = ratings.judge(net, mpns, library(tmp_path, diode), project(GND), NASA)
    assert [(f.status, f.rule, f.text) for f in report.findings if f.part == "D1"] == [
        (
            "not judged",
            rule,
            "D1 D from GND to EXT: EXT has no span: J1 pin 1 can put a voltage on EXT that nothing states",
        )
    ]


def test_an_ic_whose_pins_were_judged_is_not_among_the_parts_held_to_nothing(tmp_path):
    """The parts held to nothing are named by their kind, the kinds in order."""
    net, mpns = circuit(
        TP1=("TP", "TP-1", {"1": "SIG"}),
        J1=("IN", "HDR-1", {"1": "V33", "2": "GND"}),
        U1=("MCU", "MCU-1", mcu()),
    )
    facts = library(tmp_path, MCU_FACTS, entry("testpoint", "TP-1"), entry("connector", "HDR-1"))
    report = ratings.judge(net, mpns, facts, project(RAILS), NASA)
    assert report.notes == ["no stress is judged of J1 (connector), TP1 (testpoint)"]


def test_an_entry_2_parts_use_counts_1_time_among_the_sources_not_read_a_second_time(tmp_path):
    net, mpns = circuit(
        C1=("10u", "C-25V", {"1": "V12", "2": "GND"}), C2=("10u", "C-25V", {"1": "V12", "2": "GND"})
    )
    once = {**ceramic("C-25V", 25), "source": {**READ, "second_reader": "no"}}
    report = ratings.judge(net, mpns, library(tmp_path, once), project({"V12": (11.4, 12.6), **GND}), NASA)
    assert report.unread == 1


def test_under_its_first_point_a_rating_and_a_bias_curve_stand_at_that_point():
    """A datasheet's first point is the best it states: nothing is read into what lies before it."""
    assert ratings.rated_at([[25, 4.0], [70, 3.2]], 0) == (4.0, "")
    assert ratings.kept_at([[1, 0.9], [5, 0.5]], 0.5) == 0.9


# ---------------------------------------------------------------- the pins of an IC


def test_a_pin_under_its_least_limit_fails_on_a_line_of_its_own(tmp_path):
    """U1 swings between a -5 V rail and 3.3 V. U2's pin takes -0.3 V at the least: its upper limit
    holds, with VDD at 3 V, and the -5.2 V of U1's low level fails."""
    driver = {
        "1": ("V33", "VDD", "power_in"),
        "2": ("VNEG", "VSS", "power_in"),
        "3": ("SIG", "PA0", "bidirectional"),
    }
    net, mpns = circuit(U1=("MCU", "MCU-1", driver), U2=("MCU", "MCU-1", mcu()))
    nets = {"VNEG": (-5.2, -4.8), **RAILS}
    report = ratings.judge(net, mpns, library(tmp_path, MCU_FACTS), project(nets), NASA)
    assert [f.line for f in report.findings if f.part == "U2.3"] == [
        "fail U2 pin 3 (PA0) on SIG: -5.2 V can stand on it, its limit is -0.3 V [DS-1, rev A, p 4]",
        "hold U2 pin 3 (PA0) on SIG: 3 V can stand on it, its limit is 3.3 V (pin VDD at 3 V, +0.3 V) "
        "[DS-1, rev A, p 4]",
    ]


def test_an_output_is_not_judged_against_its_own_level(tmp_path):
    """The pin takes 3 V from another part and drives 3.3 V itself. Alone on its net with a capacitor,
    nothing is put on it: no line speaks of it."""
    low = changed(MCU_FACTS, "pins", 2, "abs", to=[-0.3, 3.0])
    net, mpns = circuit(U1=("MCU", "MCU-1", mcu()), C1=("100n", "C-16V", {"1": "SIG", "2": "GND"}))
    report = ratings.judge(net, mpns, library(tmp_path, low, ceramic("C-16V", 16)), project(RAILS), NASA)
    assert [f.line for f in report.findings if "pin 3 (PA0)" in f.text] == []
    assert found(report, "fail") == []


def test_a_pin_tied_to_the_rail_its_limit_follows_is_not_held_to_that_limit(tmp_path):
    """PA0 is tied to VDD and takes VDD + 0.3 V: whatever the rail does, the pin is inside. Its line
    names its lower limit alone."""
    net, mpns = circuit(U1=("MCU", "MCU-1", mcu("V33")))
    report = ratings.judge(net, mpns, library(tmp_path, MCU_FACTS), project(RAILS), NASA)
    assert [f.line for f in report.findings if f.part == "U1.3"] == [
        "hold U1 pin 3 (PA0) on V33: 0 V can stand on it, its limit is -0.3 V [DS-1, rev A, p 4]"
    ]


def test_a_supply_net_no_source_holds_leaves_its_pins_not_judged_1_line_each(tmp_path):
    """Nothing declares V33 and no regulator holds it. The supply pin's range, the limit that follows
    it and the output that swings to it each say so, and the pin's working range adds no second line.
    The pin's least limit is a number and follows no rail: it is judged on its own, and holds."""
    ranged = changed(MCU_FACTS, "pins", 2, "operating", to=[0, {"pin": "VDD", "plus": 0}])
    net, mpns = circuit(U1=("MCU", "MCU-1", mcu()), R1=("4.7k", "R-0402", {"1": "V5", "2": "SIG"}))
    report = ratings.judge(net, mpns, library(tmp_path, ranged, chip_resistor()), project(V5), NASA)
    assert found(report, "not judged") == [
        "not judged U1 pin 1 (VDD) on V33: no source holds V33",
        "not judged U1 pin 3 (PA0) on SIG: its limit follows pin VDD on V33, which no source holds",
        "not judged R1 4.7k between V5 and SIG: SIG has no span: "
        "U1 pin 3 swings with its pin 1 on V33, which has no span",
    ]
    assert found(report, "fail") == []
    assert found(report, "hold") == [
        "hold U1 pin 3 (PA0) on SIG: 0 V can stand on it, its limit is -0.3 V [DS-1, rev A, p 4]"
    ]


def test_of_2_limits_on_1_end_the_one_passed_furthest_is_the_one_the_line_names(tmp_path):
    """The output takes IN + 0.3 V and 5.5 V. A 6 V rail behind a resistor puts 6 V on it: 1.2 V past
    the first limit with IN at its least, 4.5 V, and 0.5 V past the second."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), R1=("10k", "R-0402", {"1": "V6", "2": "V33"}))
    nets = {"V6": (5.8, 6.0), **V5}
    report = ratings.judge(net, mpns, library(tmp_path, regulator(), chip_resistor()), project(nets), NASA)
    assert found(report, "fail") == [
        "fail U1 pin 3 (OUT) on V33: 6 V can stand on it, its limit is 4.8 V (pin IN at 4.5 V, +0.3 V) "
        "[DS-1, rev A, p 4]"
    ]


def test_a_pin_outside_its_working_range_fails_under_the_rule_pin_range(tmp_path):
    net, mpns = circuit(U1=("MCU", "MCU-1", mcu()))
    wide = pin("PA0", ["3"], "input", abs=[-0.5, 4.6], operating=[0, 3.6])
    facts = library(tmp_path, {**MCU_FACTS, "pins": [*MCU_FACTS["pins"][:2], wide]})
    report = ratings.judge(net, mpns, facts, project({"SIG": (0.0, 4.0), **RAILS}), NASA)
    assert [(f.part, f.rule) for f in report.findings if f.status == "fail"] == [("U1.3", "pin.range")]


def test_a_supply_held_at_exactly_the_ends_of_the_pin_s_working_range_holds(tmp_path):
    net, mpns = circuit(U1=("MCU", "MCU-1", mcu()))
    report = ratings.judge(net, mpns, library(tmp_path, MCU_FACTS), project({"V33": (1.7, 3.6), **GND}), NASA)
    assert found(report, "fail") == []
    assert (
        "hold U1 pin 1 (VDD) on V33: its sources hold it at 1.7 to 3.6 V, the pin works from 1.7 to 3.6 V "
        "[DS-1, rev A, p 4]" in found(report, "hold")
    )


def test_a_supply_pin_left_open_is_held_to_nothing(tmp_path):
    """kicad-cli names the net of a pin left open `unconnected-(...)`. No line speaks of the pin."""
    pins = {**mcu(), "1": ("unconnected-(U1-VDD-Pad1)", "VDD", "power_in")}
    net, mpns = circuit(U1=("MCU", "MCU-1", pins))
    report = ratings.judge(net, mpns, library(tmp_path, MCU_FACTS), project(GND), NASA)
    assert [f.line for f in report.findings if "pin 1 (VDD)" in f.text] == []


# ---------------------------------------------------------------- the load on a rail


def test_a_load_behind_a_ferrite_or_a_transistor_is_on_its_regulator_s_rail(tmp_path):
    """150 mA behind a ferrite and 100 mA behind a load switch: 250 mA on a 200 mA regulator. The
    resistor across the ferrite stands between 2 nets of the rail, and is no load on it."""
    fet = entry(
        "transistor.mosfet",
        "FET-1",
        transistors=[{"gate": "1", "drain": "3", "source": "2"}],
        volts_drain_source=20,
        volts_gate_source=12,
    )
    net, mpns = circuit(
        U1=("LDO", "LDO-1", LDO),
        FB1=("600R", "FB-1", {"1": "V33", "2": "V33A"}),
        R1=("10", "R-5W", {"1": "V33", "2": "V33A"}),
        U2=("A", "LOAD-A", {"1": ("V33A", "VDD", "power_in"), "2": ("GND", "VSS", "power_in")}),
        Q1=(
            "FET",
            "FET-1",
            {"1": ("ON", "G", "input"), "2": ("V33", "S", "passive"), "3": ("V33S", "D", "passive")},
        ),
        U3=("B", "LOAD-B", {"1": ("V33S", "VDD", "power_in"), "2": ("GND", "VSS", "power_in")}),
    )
    facts = library(
        tmp_path,
        regulator(),
        entry("ferrite", "FB-1"),
        chip_resistor("R-5W", 5.0),
        fet,
        load("LOAD-A", 0.15),
        load("LOAD-B", 0.1),
    )
    report = ratings.judge(net, mpns, facts, project({"ON": (0.0, 3.4), **V5}), NASA)
    assert found(report, "fail") == [
        "fail V33: U1 pin 3 (OUT) gives 200 mA, its loads take 250 mA: 1.25, the limit is 0.70 "
        f"[{NASA_SOURCE}, {LINEAR}]"
    ]


def test_a_supply_pin_of_a_part_with_no_facts_leaves_its_rail_not_judged(tmp_path):
    pins = {"1": ("V33", "VDD", "power_in"), "2": ("GND", "VSS", "power_in"), "3": ("V33", "EN", "input")}
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), U9=("X", "", pins))
    report = ratings.judge(net, mpns, library(tmp_path, regulator()), project(V5), NASA)
    assert found(report, "not judged") == [
        "not judged U9 X: no facts for a part with no part number ()",
        "not judged V33: U1 pin 3 (OUT) feeds a load nothing states: "
        "U9 pin 1 takes current from V33 and has no facts",
    ]


def test_a_load_nothing_states_behind_a_second_regulator_leaves_both_rails_not_judged(tmp_path):
    second = {
        "1": ("V33", "IN", "power_in"),
        "2": ("GND", "GND", "power_in"),
        "3": ("V18", "OUT", "power_out"),
    }
    far = {"1": ("V18", "VDD", "power_in"), "2": ("GND", "VSS", "power_in")}
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), U2=("LDO", "LDO-2", second), U3=("B", "LOAD-B", far))
    low = regulator()
    low["mpn"] = "LDO-2"
    low["pins"][2]["volts"] = [1.7, 1.9]
    report = ratings.judge(
        net, mpns, library(tmp_path, regulator(), low, load("LOAD-B", None)), project(V5), NASA
    )
    assert found(report, "not judged") == [
        "not judged V33: U1 pin 3 (OUT) feeds a load nothing states: "
        "U3 pin 1 (VDD) has no `amps` in its facts",
        "not judged V18: U2 pin 3 (OUT) feeds a load nothing states: "
        "U3 pin 1 (VDD) has no `amps` in its facts",
    ]


def test_a_switching_regulator_on_a_rail_that_can_be_held_at_0_volts_leaves_the_rail_not_judged(tmp_path):
    """The first regulator's facts give its output from 0 V: the current a load's power takes from 0 V
    has no number. Where the project states that rail from 0 V instead, a second source feeds its
    loads too: a note says so, and no line speaks of the rail's load."""
    net, mpns = circuit(
        U1=("LDO", "LDO-1", LDO),
        U2=("BUCK", "BUCK-3", FIXED_BUCK_PINS),
        L1=("2.2u", "L-1", {"1": "SW", "2": "V1P2"}),
        U3=("A", "LOAD-A", ON_V1P2),
    )
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=3.0)
    from_0 = changed(regulator(0.5), "pins", 2, "volts", to=[0.0, 3.4])
    facts = library(tmp_path, from_0, FIXED_BUCK, coil, load("LOAD-A", 1.0))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert (
        "not judged V33: U1 pin 3 (OUT) feeds a load nothing states: "
        "U2 takes its load's power from V33, and no source holds V33 and V1P2 above 0 V"
        in found(report, "not judged")
    )
    facts = library(tmp_path, regulator(0.5), FIXED_BUCK, coil, load("LOAD-A", 1.0))
    report = ratings.judge(net, mpns, facts, project({"V33": (0.0, 3.4), **V5}), NASA)
    assert [f.line for f in report.findings if f.part == "U1"] == []
    assert (
        "V33: U1 pin 3 (OUT) stands on a net ratings.json states, V33: another source feeds its loads "
        "too, and its load is not judged"
    ) in report.notes


def test_a_resistor_from_a_rail_to_ground_is_a_load_on_its_regulator(tmp_path):
    """3.4 V across 33 ohm less 1 % is 104 mA, and the load beside it takes 50 mA: 154 mA of 200 mA
    is 0.77."""
    net, mpns = circuit(
        U1=("LDO", "LDO-1", LDO), U2=("A", "LOAD-A", TWO_PINS), R1=("33", "R-1W", {"1": "V33", "2": "GND"})
    )
    facts = library(tmp_path, regulator(), load("LOAD-A", 0.05), chip_resistor("R-1W", 1.0))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert found(report, "fail") == [
        "fail V33: U1 pin 3 (OUT) gives 200 mA, its loads take 154 mA: 0.77, the limit is 0.70 "
        f"[{NASA_SOURCE}, {LINEAR}]"
    ]


def test_a_connector_pin_with_a_load_behind_it_and_no_current_stated_leaves_its_rail_not_judged(tmp_path):
    """Pin 2 feeds a load and pin 3 has nothing behind it: pin 2 is the one the project owes a current."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), J1=("HDR", "HDR-3", {"1": "V5", "2": "V33", "3": "V33"}))
    facts = library(tmp_path, regulator(), HEADER)
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert found(report, "not judged") == [
        "not judged V33: U1 pin 3 (OUT) feeds a load nothing states: "
        "J1 pin 2 feeds a load, and ratings.json states no amps for J1.2"
    ]
    report = ratings.judge(net, mpns, facts, project(V5, amps={"J1.2": 0.1}), NASA)
    assert found(report, "not judged") == []
    assert any("its loads take 100 mA: 0.50, the limit is 0.70" in f.text for f in report.findings)


def test_a_regulator_whose_facts_state_no_output_current_is_judged_on_its_pins_all_the_same(tmp_path):
    """`amps` of a regulated pin is a key the pin may hold: without it the run does not stop."""
    bare = regulator()
    del bare["pins"][2]["amps"]
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), U2=("A", "LOAD-A", TWO_PINS))
    report = ratings.judge(net, mpns, library(tmp_path, bare, load("LOAD-A", 0.15)), project(V5), NASA)
    assert found(report, "fail") == []
    assert any(
        line.startswith("hold U1 pin 1 (IN) on V5: its sources hold it at") for line in found(report, "hold")
    )


def test_a_rail_s_load_is_held_to_the_regulator_s_own_rating_when_the_pack_has_no_rule(tmp_path):
    """150 mA on a 200 mA regulator is 0.75: over NASA's 0.70, and inside the part's own 1.00."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), U2=("A", "LOAD-A", TWO_PINS))
    bare = ratings.Pack("bare", NASA.document, [])
    report = ratings.judge(net, mpns, library(tmp_path, regulator(), load("LOAD-A", 0.15)), project(V5), bare)
    assert [(f.rule, f.line) for f in report.findings if f.part == "U1"] == [
        (
            "rail.load",
            "hold V33: U1 pin 3 (OUT) gives 200 mA, its loads take 150 mA: 0.75, the limit is 1.00 "
            "[DS-1, rev A, p 4: the part's own rating]",
        )
    ]


def test_a_regulator_s_own_supply_pin_on_its_output_is_not_counted_among_its_loads(tmp_path):
    """The BIAS pin takes 1 mA from the output it helps to make. The load is the 500 mA beside it."""
    dual = entry(
        "ic",
        "LDO-BIAS",
        family="regulator.linear",
        pins=[
            pin("IN", ["1"], "supply", abs=[-0.3, 6.5], amps=0.0001),
            pin("BIAS", ["2"], "supply", abs=[-0.3, 6.5], amps=0.001),
            pin("GND", ["3"], "ground"),
            pin("OUT", ["4"], "regulated", abs=[-0.3, 6.5], volts=[1.7, 1.9], amps=1.0, **{"from": "IN"}),
        ],
    )
    pins = {
        "1": ("V5", "IN", "power_in"),
        "2": ("V18", "BIAS", "power_in"),
        "3": ("GND", "GND", "power_in"),
        "4": ("V18", "OUT", "power_out"),
    }
    far = {"1": ("V18", "VDD", "power_in"), "2": ("GND", "VSS", "power_in")}
    net, mpns = circuit(U1=("LDO", "LDO-BIAS", pins), U2=("A", "LOAD-A", far))
    report = ratings.judge(net, mpns, library(tmp_path, dual, load("LOAD-A", 0.5)), project(V5), NASA)
    assert [f.text for f in report.findings if f.part == "U1"] == [
        "V18: U1 pin 4 (OUT) gives 1 A, its loads take 500 mA: 0.50, the limit is 0.70"
    ]


# ---------------------------------------------------------------- a buck's inductor


def test_a_buck_with_no_inductor_to_its_output_fails_on_1_line(tmp_path):
    """By its switching facts when its facts ask for no inductor, and by the need when they do."""
    net, mpns = circuit(
        U2=("BUCK", "BUCK-3", FIXED_BUCK_PINS), C1=("10u", "C-16V", {"1": "V1P2", "2": "GND"})
    )
    report = ratings.judge(
        net, mpns, library(tmp_path, FIXED_BUCK, ceramic("C-16V", 16)), project(RAILS), NASA
    )
    assert [f.line for f in report.findings if f.rule == "needs.inductor"] == [
        "fail U2 pin 3 (SW) on SW: a buck needs an inductor to V1P2, and none stands there [DS-1, rev A, p 7]"
    ]
    net, mpns = circuit(U1=("BUCK", "BUCK-2", SWITCHER_PINS), U2=("A", "LOAD-A", ON_VOUT), **DIVIDER)
    facts = library(tmp_path, SWITCHER, chip_resistor(), load("LOAD-A", 1.0))
    report = ratings.judge(net, mpns, facts, project(V12), NASA)
    assert [f.line for f in report.findings if f.rule == "needs.inductor"] == [
        "fail U1 pin SW (SW) needs an inductor to VOUT, and none stands there [DS-1, rev A, p 12]"
    ]


def test_an_inductor_s_peak_current_is_not_worked_out_without_its_load_its_value_or_its_input(tmp_path):
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=2.0)
    net, mpns = buck_board()
    facts = library(tmp_path, SWITCHER, coil, chip_resistor(), load("LOAD-A", None))
    report = ratings.judge(net, mpns, facts, project(V12), NASA)
    assert [f.line for f in report.findings if f.part == "L1"] == [
        "not judged L1 2.2u: its peak current is not worked out: the load on VOUT is not known: "
        "U2 pin 1 (VDD) has no `amps` in its facts"
    ]
    facts = library(tmp_path, SWITCHER, coil, chip_resistor(), load("LOAD-A", 1.0))
    report = ratings.judge(net, mpns, facts, project(GND), NASA)
    assert [f.line for f in report.findings if f.part == "L1"] == [
        "not judged L1 2.2u: its peak current is not worked out: no source holds V12"
    ]
    net, mpns = circuit(
        U1=("BUCK", "BUCK-2", SWITCHER_PINS),
        L1=("SRN2010", "L-1", {"1": "SW", "2": "VOUT"}),
        U2=("A", "LOAD-A", ON_VOUT),
        **DIVIDER,
    )
    report = ratings.judge(net, mpns, facts, project(V12), NASA)
    assert [f.line for f in report.findings if f.part == "L1"] == [
        "not judged L1 SRN2010: its peak current is not worked out: its Value is no number"
    ]


@pytest.mark.parametrize(
    ("volts", "peak"),
    [
        ([1.5, 1.9], "1.13 A: 1 A of load and half of 268 mA of ripple (3.4 V in, 1.7 V out"),
        ([3.1, 3.3], "1.04 A: 1 A of load and half of 85.2 mA of ripple (3.4 V in, 3.1 V out"),
        ([3.5, 3.7], "1 A: 1 A of load and half of 0 A of ripple (3.4 V in, 3.5 V out"),
    ],
)
def test_a_buck_s_ripple_is_taken_where_it_is_greatest_and_its_duty_cycle_ends_at_1(tmp_path, volts, peak):
    """From 3.4 V at 2 MHz into 2.2 uH less 20 %, at 90 %: (3.4 - v) x min(1, v / 3.06) / 3.52.
    An output span that holds half the input has its greatest ripple there: at 1.7 V,
    1.7 x 0.5556 / 3.52 = 0.268 A, and at 1.5 V and 1.9 V 0.265 A. Above 3.06 V the duty cycle is 1:
    at 3.1 V, 0.3 / 3.52 = 0.0852 A. An output above the input has no ripple."""
    report = second_stage(changed(FIXED_BUCK, "pins", 3, "volts", to=volts), tmp_path)
    assert [f.text for f in report.findings if f.rule == "inductor.current"] == [
        f"L1 2.2u: its peak current is {peak}, 1.76 uH, 2 MHz); it saturates at 3 A"
    ]


def test_an_inductor_loaded_to_exactly_its_rated_current_holds(tmp_path):
    net, mpns = circuit(
        U2=("BUCK", "BUCK-3", FIXED_BUCK_PINS),
        L1=("2.2u", "L-1", {"1": "SW", "2": "V1P2"}),
        U3=("A", "LOAD-A", ON_V1P2),
    )
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=3.0, amps_rms=1.0)
    report = ratings.judge(
        net, mpns, library(tmp_path, FIXED_BUCK, coil, load("LOAD-A", 1.0)), project(RAILS), NASA
    )
    assert [f.line for f in report.findings if f.rule == "inductor.heating"] == [
        "hold L1 2.2u: its loads take 1 A, its rated current is 1 A [DS-1, rev A: the part's own rating]"
    ]


# ---------------------------------------------------------------- the parts a datasheet asks for


def test_an_inductor_at_exactly_the_least_value_and_the_least_saturation_asked_holds(tmp_path):
    """1.875 uH less 20 % is the 1.5 uH asked, and it saturates at the 1.5 A asked."""
    net, mpns = circuit(U1=("BUCK", "BUCK-1", BUCK_PINS), L1=("1.875u", "L-1", {"1": "SW", "2": "V33"}))
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=1.5)
    nets = {"V12": (11.4, 12.6), "V33": (3.2, 3.4), **GND}
    report = ratings.judge(net, mpns, library(tmp_path, BUCK, coil), project(nets), NASA)
    assert [f.line for f in report.findings if f.rule == "needs.inductor"] == [
        "hold U1 pin SW (SW) needs 1.5 uH to 4.7 uH, L1 is 1.5 uH to 2.25 uH [DS-1, rev A, p 12]",
        "hold U1 pin SW (SW) needs an inductor that saturates above 1.5 A, L1 saturates at 1.5 A "
        "[DS-1, rev A, p 12]",
    ]


def test_an_inductor_under_the_range_asked_fails(tmp_path):
    """1 uH at 20 % is 0.8 to 1.2 uH, under the 1.5 uH asked."""
    net, mpns = circuit(U1=("BUCK", "BUCK-1", BUCK_PINS), L1=("1u", "L-1", {"1": "SW", "2": "V33"}))
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=2.0)
    nets = {"V12": (11.4, 12.6), "V33": (3.2, 3.4), **GND}
    report = ratings.judge(net, mpns, library(tmp_path, BUCK, coil), project(nets), NASA)
    assert found(report, "fail") == [
        "fail U1 pin SW (SW) needs 1.5 uH to 4.7 uH, L1 is 800 nH to 1.2 uH [DS-1, rev A, p 12]"
    ]


def test_a_need_through_a_feedback_pin_whose_divider_was_not_read_adds_no_line(tmp_path):
    """The divider's own line says why. The inductor asked for from SW to FB is not looked for."""
    net, mpns = circuit(
        U1=("BUCK", "BUCK-2", SWITCHER_PINS),
        L1=("2.2u", "L-1", {"1": "SW", "2": "VOUT"}),
        J1=("TP", "", {"1": "FB"}),
        **DIVIDER,
    )
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=2.0)
    report = ratings.judge(net, mpns, library(tmp_path, SWITCHER, coil, chip_resistor()), project(V12), NASA)
    assert (
        "not judged U1 pin 4 (FB) on FB: J1 pin 1 stands on FB too, and is no resistor of a divider"
        in found(report, "not judged")
    )
    assert [f.line for f in report.findings if f.rule.startswith("needs.")] == []


RTC = entry(
    "ic",
    "RTC-1",
    family="digital",
    pins=[
        pin("VDD", ["1"], "supply", abs=[-0.3, 4.0]),
        pin("VBAT", ["2"], "supply", abs=[-0.3, 4.0]),
        pin("VSS", ["3"], "ground"),
        pin("VREF", ["4"], "analog", abs=[-0.3, 4.0]),
    ],
)
RTC_PINS = {
    "1": ("V33", "VDD", "power_in"),
    "2": ("VB", "VBAT", "power_in"),
    "3": ("GND", "VSS", "power_in"),
    "4": ("REF", "VREF", "input"),
}


def test_a_needed_capacitor_s_working_voltage_is_what_its_2_nets_are_held_to_or_can_stand_at(tmp_path):
    """Between 2 rails that are held at 3.0 to 3.3 V and 2.0 to 3.0 V the capacitor works at 1.3 V and
    keeps 0.80: 1 uF less 10 % gives 720 nF. Counted from 0 V it would work at 3.3 V and keep 0.40.
    On a divider's tap, which no source holds, it works at what can stand there: 3.3 x 10.1 / 20 =
    1.6665 V, where it keeps 0.80 - 0.40 x 0.3665 / 2.0 = 0.7267: 654 nF."""
    curve = ceramic("C-KEPT", 16, kept=[[0, 1.0], [1.3, 0.8], [3.3, 0.4]])
    asks = {"capacitor": {"from": "VDD", "to": "VBAT", "farads_min": 0.5e-6, "effective": True}, "page": 5}
    net, mpns = circuit(U1=("RTC", "RTC-1", RTC_PINS), C1=("1u", "C-KEPT", {"1": "V33", "2": "VB"}))
    nets = {"VB": (2.0, 3.0), "REF": (0.0, 3.3), **RAILS}
    report = ratings.judge(net, mpns, library(tmp_path, {**RTC, "needs": [asks]}, curve), project(nets), NASA)
    assert "hold U1 pin VDD (V33) needs 500 nF effective to VB: C1 gives 720 nF [DS-1, rev A, p 5]" in found(
        report, "hold"
    )
    asks = {"capacitor": {"from": "VREF", "to": "VSS", "farads_min": 0.5e-6, "effective": True}, "page": 5}
    net, mpns = circuit(
        U1=("RTC", "RTC-1", RTC_PINS),
        R1=("10k", "R-0402", {"1": "V33", "2": "REF"}),
        R2=("10k", "R-0402", {"1": "REF", "2": "GND"}),
        C1=("1u", "C-KEPT", {"1": "REF", "2": "GND"}),
    )
    nets = {"VB": (2.0, 3.0), **RAILS}
    facts = library(tmp_path, {**RTC, "needs": [asks]}, curve, chip_resistor())
    report = ratings.judge(net, mpns, facts, project(nets), NASA)
    assert (
        "hold U1 pin VREF (REF) needs 500 nF effective to GND: C1 gives 654 nF [DS-1, rev A, p 5]"
        in found(report, "hold")
    )


def test_a_needed_capacitor_whose_value_is_no_number_is_not_judged(tmp_path):
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), C1=("DNP", "C-16V", {"1": "V33", "2": "GND"}))
    facts = library(tmp_path, regulator(needs=[OUT_CAP]), ceramic("C-16V", 16))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert "not judged U1 pin OUT (V33): the Value of C1 is no number" in found(report, "not judged")


def test_a_capacitor_whose_curve_ends_under_the_rail_s_voltage_is_not_judged_and_says_where(tmp_path):
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), C1=("1u", "C-2V5", {"1": "V33", "2": "GND"}))
    short = ceramic("C-2V5", 6.3, kept=[[0, 1.0], [2.5, 0.6]])
    report = ratings.judge(
        net, mpns, library(tmp_path, regulator(needs=[EFFECTIVE]), short), project(V5), NASA
    )
    assert "not judged U1 pin OUT (V33): C1: its data on the value it keeps ends below 3.4 V" in found(
        report, "not judged"
    )


def test_the_most_a_capacitor_with_no_data_could_give_is_its_value_and_its_tolerance(tmp_path):
    """315 nF known. 180 nF plus 10 % is 198 nF: 513 nF at the most, over the 500 nF asked, so the
    data that is missing decides. Counted at its value, or less its tolerance, the need would fail."""
    net, mpns = circuit(
        U1=("LDO", "LDO-1", LDO),
        C1=("1u", "C-KEPT", {"1": "V33", "2": "GND"}),
        C2=("180n", "C-16V", {"1": "V33", "2": "GND"}),
    )
    known = ceramic("C-KEPT", 16, kept=[[0, 1.0], [3.4, 0.35], [16, 0.1]])
    facts = library(tmp_path, regulator(needs=[EFFECTIVE]), known, ceramic("C-16V", 16))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert found(report, "not judged") == [
        "not judged U1 pin OUT (V33): C2 has no data on the value it keeps at 3.4 V"
    ]


def test_a_capacitor_of_exactly_the_value_asked_is_enough(tmp_path):
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), C1=("500n", "C-16V", {"1": "V33", "2": "GND"}))
    facts = library(tmp_path, regulator(needs=[OUT_CAP]), ceramic("C-16V", 16))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert "hold U1 pin OUT (V33) needs 500 nF to GND: C1 gives 500 nF [DS-1, rev A, p 5]" in found(
        report, "hold"
    )


# ---------------------------------------------------------------- the lines, the files a run finds


def test_20_lines_to_show_are_all_shown_and_no_line_counts_0_more(tmp_path):
    parts = {f"C{i}": ("10u", "C-16V", {"1": "V12", "2": "GND"}) for i in range(1, 21)}
    net, mpns = circuit(**parts)
    report = ratings.judge(
        net, mpns, library(tmp_path, ceramic("C-16V", 16)), project({"V12": (11.4, 12.6), **GND}), NASA
    )
    out = ratings.lines(report)
    assert len(out) == 21 and out[20].startswith("fail C20 10u between V12 and GND")


def test_the_facts_in_the_project_s_own_folder_are_the_nearest(tmp_path):
    (tmp_path / "library" / "facts").mkdir(parents=True)
    assert ratings.find_facts(tmp_path) == tmp_path / "library" / "facts"


def test_the_packs_a_refusal_names_stand_in_order_whatever_order_the_folder_gives_them(tmp_path):
    class Backwards(type(tmp_path)):
        def glob(self, pattern):
            return iter(sorted(super().glob(pattern), reverse=True))

    for name in ("b", "a", "c"):
        (tmp_path / f"{name}.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ratings.Refusal) as caught:
        ratings.find_pack("mil-hdbk", tmp_path, Backwards(tmp_path))
    assert str(caught.value) == "ratings.json: pack: `mil-hdbk` is no pack; the workcenter holds a, b, c"


def test_a_row_with_no_footprint_or_no_number_names_no_part():
    """An item off the board has no footprint: it is no part of the board, even one whose own
    footprint is empty. A row with no number gives a part none."""
    bare = NETLIST.replace(
        "<footprint>Capacitor_SMD:C_0603_1608Metric</footprint>", "<footprint></footprint>"
    )
    net = ratings.read_netlist(bare)
    row = types.SimpleNamespace
    rows = [
        row(value="100n", footprint="", buys=True, mpn="OFF-BOARD"),
        row(value="10k", footprint="Resistor_SMD:R_0603_1608Metric", buys=True, mpn=""),
    ]
    assert net.parts["C1"].footprint == ""
    assert ratings.part_numbers(net, rows) == {}


def test_an_entry_to_fill_lists_the_numbers_of_a_pin_name_in_order():
    twice = NETLIST.replace(
        '<node ref="U1" pin="4" pinfunction="VSS_4" pintype="power_in"/>',
        '<node ref="U1" pin="4" pinfunction="VSS_4" pintype="power_in"/>'
        '<node ref="U1" pin="1" pinfunction="VSS_1" pintype="power_in"/>',
    )
    entry_ = ratings.skeleton(ratings.read_netlist(twice), "U1", "")
    assert {"numbers": ["1", "4"], "name": "VSS", "role": "", "page": 0} in entry_["pins"]


# ---------------------------------------------------------------- the gate
#
# gate_ratings on a netlist's text. The 4 things it takes from the workcenter are stood in for: its
# Result, the netlist kicad-cli writes, the folder of the packs and the reader of the parts files.


def gate(folder: Path, text: str, strict: bool = False, facts: tuple = ()):
    (folder / "library" / "facts").mkdir(parents=True, exist_ok=True)
    (folder / "library" / "facts" / "parts.json").write_text(
        json.dumps({"parts": list(facts)}), encoding="utf-8"
    )
    stated = {"V12": {"volts": [11.4, 12.6], "source": "s"}, "GND": {"volts": [0, 0], "source": "s"}}
    (folder / "ratings.json").write_text(
        json.dumps({"pack": "nasa-eee-inst-002", "nets": stated}), encoding="utf-8"
    )
    cli = types.SimpleNamespace(
        Result=lambda gate, status, summary, details=None, artifacts=None: types.SimpleNamespace(
            gate=gate, status=status, summary=summary, details=details or {}, artifacts=artifacts or []
        ),
        schematic_netlist=lambda project, out: (text, ""),
        SRC_DIR=ROOT,
        read_parts=lambda path: [],
    )
    board_ = types.SimpleNamespace(sch=folder / "x.kicad_sch", dir=folder)
    return ratings.gate_ratings(board_, folder / "build", [], strict, cli)


def capacitors(*symbols: str) -> str:
    """A netlist of 1 capacitor from V12 to GND for each symbol, C1 on."""
    parts = "".join(
        f'<comp ref="C{i}"><value>10u</value><footprint>F</footprint><libsource lib="T" part="{s}"/></comp>'
        for i, s in enumerate(symbols, start=1)
    )
    nodes = ['<node ref="C{i}" pin="{pin}" pintype="passive"/>'] * len(symbols)
    v12 = "".join(n.format(i=i, pin=1) for i, n in enumerate(nodes, start=1))
    gnd = "".join(n.format(i=i, pin=2) for i, n in enumerate(nodes, start=1))
    return (
        f'<export version="E"><components>{parts}</components><nets><net code="1" name="V12">{v12}</net>'
        f'<net code="2" name="GND">{gnd}</net></nets></export>'
    )


def by_symbol(symbol: str, volts: float, **more) -> dict:
    return {**{k: v for k, v in ceramic("", volts, **more).items() if k != "mpn"}, "symbol": f"T:{symbol}"}


WEAK, STRONG = by_symbol("C16", 16), by_symbol("C25", 25, note="its bias curve is not entered")


def test_the_gate_lists_20_lines_failures_first_and_counts_the_rest(tmp_path):
    """12 capacitors fail and 13 have no facts. A run shows the 12 failures and 8 of the 13 as
    warnings, and counts 5 more; a strict run fails on all 25, shows 20 and counts 5 more."""
    text = capacitors(*["C16"] * 12, *["NONE"] * 13)
    result = gate(tmp_path, text, facts=(WEAK,))
    page = tmp_path / "build" / "ratings" / "report.md"
    details = result.details
    assert (result.status, details["verdict"]) == ("fail", "RATINGS NOT HELD (12 fail, 13 not judged)")
    assert [line.split()[1] for line in details["failures"]] == [f"C{i}" for i in range(1, 13)]
    assert details["warnings"][:8] == [
        f"not judged C{i} 10u: no facts for a part with no part number (T:NONE)" for i in range(13, 21)
    ]
    assert details["warnings"][8:] == [f"... 5 more in {page}"]
    strict = gate(tmp_path, text, strict=True, facts=(WEAK,)).details
    assert len(strict["failures"]) == 21 and strict["failures"][20] == f"... 5 more in {page}"
    assert strict["failures"][12] == "not judged C13 10u: no facts for a part with no part number (T:NONE)"
    assert strict["warnings"] == []


def test_the_gate_cuts_25_failures_at_20_and_adds_no_count_to_exactly_20(tmp_path):
    result = gate(tmp_path, capacitors(*["C16"] * 25), facts=(WEAK,))
    page = tmp_path / "build" / "ratings" / "report.md"
    assert len(result.details["failures"]) == 21 and result.details["failures"][20] == f"... 5 more in {page}"
    result = gate(tmp_path, capacitors(*["C16"] * 20), facts=(WEAK,))
    assert len(result.details["failures"]) == 20 and result.details["warnings"] == []


def test_the_gate_s_record_holds_the_pack_the_notes_and_no_hold_among_its_warnings(tmp_path):
    """A part that holds and a part with no facts: the run passes with 1 warning, and a strict run
    fails on it."""
    text = capacitors("C25", "NONE")
    result = gate(tmp_path, text, facts=(STRONG,))
    assert (result.status, result.details["verdict"]) == ("pass", "RATINGS HELD, 1 NOT JUDGED")
    assert result.details["failures"] == []
    assert result.details["warnings"] == [
        "not judged C2 10u: no facts for a part with no part number (T:NONE)"
    ]
    assert result.details["pack"] == "nasa-eee-inst-002"
    assert result.details["notes"] == ["C1 (T:C25): its bias curve is not entered"]
    strict = gate(tmp_path, text, strict=True, facts=(STRONG,))
    assert (strict.status, strict.details["verdict"]) == ("fail", "RATINGS HELD, 1 NOT JUDGED")
    assert strict.details["failures"] == [
        "not judged C2 10u: no facts for a part with no part number (T:NONE)"
    ]
    assert strict.details["warnings"] == []


# ---------------------------------------------------------------- the second of 2


def test_each_number_of_a_pin_name_is_judged_on_its_own_net(tmp_path):
    """VDD has pins 1 and 3. Pin 3 stands on the 5 V rail and fails, whatever pin 1 does."""
    pins = {**TWO_PINS, "3": ("V5", "VDD", "power_in")}
    wide = load("LOAD-A", 0.13)
    wide["pins"][0]["numbers"] = ["1", "3"]
    net, mpns = circuit(U2=("A", "LOAD-A", pins))
    report = ratings.judge(net, mpns, library(tmp_path, wide), project({"V5": (4.5, 5.5), **RAILS}), NASA)
    assert found(report, "fail") == [
        "fail U2 pin 3 (VDD) on V5: 5.5 V can stand on it, its limit is 4 V [DS-1, rev A, p 4]"
    ]


def test_the_second_number_of_a_supply_pin_puts_nothing_on_its_net(tmp_path):
    """The rail is no declared net: a regulator holds it. Were pin 3 a source nothing describes, the
    rail would have no span."""
    pins = {**TWO_PINS, "3": ("V33", "VDD", "power_in")}
    wide = load("LOAD-A", 0.13)
    wide["pins"][0]["numbers"] = ["1", "3"]
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), U2=("A", "LOAD-A", pins))
    report = ratings.judge(net, mpns, library(tmp_path, regulator(), wide), project(V5), NASA)
    assert found(report, "not judged") == []


def test_each_number_of_an_output_s_name_drives_its_own_net(tmp_path):
    pins = {**mcu("A"), "4": ("B", "PA0", "bidirectional")}
    chip = changed(MCU_FACTS, "pins", 2, "numbers", to=["3", "4"])
    net, mpns = circuit(
        U1=("MCU", "MCU-1", pins),
        C1=("100n", "C-16V", {"1": "A", "2": "GND"}),
        C2=("100n", "C-16V", {"1": "B", "2": "GND"}),
    )
    report = ratings.judge(net, mpns, library(tmp_path, chip, ceramic("C-16V", 16)), project(RAILS), NASA)
    assert found(report, "not judged") == []
    assert [f.text.split(",")[0] for f in report.findings if f.part in ("C1", "C2")] == [
        "C1 100n between A and GND: 3.3 V on 16 V rated is 0.21",
        "C2 100n between B and GND: 3.3 V on 16 V rated is 0.21",
    ]


def test_each_diode_of_a_part_of_2_conducts_and_is_judged(tmp_path):
    """The second diode goes from the 12 V rail to a net of its own. The capacitor there sees 12.6 V,
    0.79 of its 16 V, and each diode has its line: 12.6 V on 30 V."""
    pins = {
        "1": ("VBUS", "A1", "passive"),
        "2": ("V12", "K1", "passive"),
        "3": ("V12", "A2", "passive"),
        "4": ("OUT", "K2", "passive"),
    }
    pair = entry(
        "diode.rectifier",
        "D-2",
        diodes=[{"anode": "1", "cathode": "2"}, {"anode": "3", "cathode": "4"}],
        volts_reverse=30,
    )
    net, mpns = circuit(D1=("BAT54", "D-2", pins), C1=("10u", "C-16V", {"1": "OUT", "2": "GND"}))
    nets = {"VBUS": (4.4, 5.5), "V12": (11.4, 12.6), **GND}
    report = ratings.judge(net, mpns, library(tmp_path, pair, ceramic("C-16V", 16)), project(nets), NASA)
    assert found(report, "fail") == [
        f"fail C1 10u between OUT and GND: 12.6 V on 16 V rated is 0.79, the limit is 0.60 {CERAMIC}"
    ]
    assert [f.text for f in report.findings if f.part == "D1"] == [
        "D1 BAT54 from VBUS to V12: 12.6 V on 30 V rated is 0.42, the limit is 0.70",
        "D1 BAT54 from V12 to OUT: 12.6 V on 30 V rated is 0.42, the limit is 0.70",
    ]


def test_each_transistor_of_a_part_of_2_is_judged(tmp_path):
    """The second transistor's gate stands on the 12 V rail: 12.6 V on its 8 V."""
    pins = {
        "1": ("GATE", "G1", "input"),
        "2": ("GND", "S1", "passive"),
        "3": ("LOAD", "D1", "passive"),
        "4": ("V12", "G2", "input"),
        "5": ("GND", "S2", "passive"),
        "6": ("V12", "D2", "passive"),
    }
    pair = entry(
        "transistor.mosfet",
        "FET-3",
        transistors=[{"gate": "1", "drain": "3", "source": "2"}, {"gate": "4", "drain": "6", "source": "5"}],
        volts_drain_source=20,
        volts_gate_source=8,
    )
    net, mpns = circuit(Q1=("FET", "FET-3", pins))
    nets = {"LOAD": (0.0, 12.6), "GATE": (0.0, 3.6), "V12": (11.4, 12.6), **GND}
    report = ratings.judge(net, mpns, library(tmp_path, pair), project(nets), NASA)
    assert [f.line.split(" [")[0] for f in report.findings] == [
        "fail Q1 FET gate V12 to source GND: 12.6 V on 8 V rated is 1.57, the limit is 0.60",
        "hold Q1 FET drain LOAD to source GND: 12.6 V on 20 V rated is 0.63, the limit is 0.75",
        "hold Q1 FET gate GATE to source GND: 3.6 V on 8 V rated is 0.45, the limit is 0.60",
        "hold Q1 FET drain V12 to source GND: 12.6 V on 20 V rated is 0.63, the limit is 0.75",
    ]


def test_each_output_of_a_regulator_of_2_has_its_load_judged(tmp_path):
    """150 mA of 200 mA on the first output is 0.75, and 90 mA of 100 mA on the second is 0.90."""
    dual = entry(
        "ic",
        "LDO-2X",
        family="regulator.linear",
        pins=[
            pin("IN", ["1"], "supply", abs=[-0.3, 6.5], amps=0.0001),
            pin("GND", ["2"], "ground"),
            pin("OUT1", ["3"], "regulated", abs=[-0.3, 6.5], volts=[3.2, 3.4], amps=0.2),
            pin("OUT2", ["4"], "regulated", abs=[-0.3, 6.5], volts=[1.7, 1.9], amps=0.1),
        ],
    )
    pins = {
        "1": ("V5", "IN", "power_in"),
        "2": ("GND", "GND", "power_in"),
        "3": ("V33", "OUT1", "power_out"),
        "4": ("V18", "OUT2", "power_out"),
    }
    far = {"1": ("V18", "VDD", "power_in"), "2": ("GND", "VSS", "power_in")}
    net, mpns = circuit(U1=("LDO", "LDO-2X", pins), U2=("A", "LOAD-A", TWO_PINS), U3=("B", "LOAD-B", far))
    facts = library(tmp_path, dual, load("LOAD-A", 0.15), load("LOAD-B", 0.09))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert found(report, "fail") == [
        "fail V33: U1 pin 3 (OUT1) gives 200 mA, its loads take 150 mA: 0.75, the limit is 0.70 "
        f"[{NASA_SOURCE}, {LINEAR}]",
        "fail V18: U1 pin 4 (OUT2) gives 100 mA, its loads take 90 mA: 0.90, the limit is 0.70 "
        f"[{NASA_SOURCE}, {LINEAR}]",
    ]


def test_a_note_of_facts_2_parts_use_is_said_1_time_and_names_both(tmp_path):
    net, mpns = circuit(
        C1=("10u", "C-25V", {"1": "V12", "2": "GND"}), C2=("10u", "C-25V", {"1": "V12", "2": "GND"})
    )
    facts = library(tmp_path, ceramic("C-25V", 25, note="its bias curve is not entered"))
    report = ratings.judge(net, mpns, facts, project({"V12": (11.4, 12.6), **GND}), NASA)
    assert report.notes == ["C1, C2 (C-25V): its bias curve is not entered"]


def test_a_fact_read_on_3_pages_names_all_3(tmp_path):
    net, mpns = circuit(U1=("MCU", "MCU-1", TWO_PINS))
    chip = entry(
        "ic",
        "MCU-1",
        family="digital",
        pins=[
            {**pin("VDD", ["1"], "supply", abs=[-0.3, 4.0], operating=[3.4, 3.6]), "page": [4, 5, 6]},
            pin("VSS", ["2"], "ground"),
        ],
    )
    report = ratings.judge(net, mpns, library(tmp_path, chip), project({"V33": (3.2, 3.4), **GND}), NASA)
    assert found(report, "fail") == [
        "fail U1 pin 1 (VDD) on V33: its sources hold it at 3.2 to 3.4 V, the pin works from 3.4 to 3.6 V "
        "[DS-1, rev A, p 4, 5 and 6]"
    ]


# ---------------------------------------------------------------- the survivors of the mutation list
#
# `make mutate-ratings` runs tests/ratings_mutations.py against this file and tests/test_ratings.py.
# Each test below fails on the mutation its docstring names, which the 2 files let pass before.


def test_a_pin_past_its_limit_gets_1_line_and_no_line_of_its_working_range(tmp_path):
    """IC13. 0 to 5 V on an input rated to 4.6 V that works to 3.6 V: the limit fails, and that line
    says it all; a second line on its working range would count 1 fault 2 times."""
    net, mpns = circuit(U1=("MCU", "MCU-1", mcu()))
    wide = pin("PA0", ["3"], "input", abs=[-0.5, 4.6], operating=[0, 3.6])
    facts = library(tmp_path, {**MCU_FACTS, "pins": [*MCU_FACTS["pins"][:2], wide]})
    report = ratings.judge(net, mpns, facts, project({"SIG": (0.0, 5.0), **RAILS}), NASA)
    assert [(f.status, f.rule) for f in report.findings if f.part == "U1.3"] == [
        ("fail", "pin.voltage"),  # its greatest limit, 4.6 V
        ("hold", "pin.voltage"),  # its least, -0.5 V
    ]


def test_a_pin_whose_least_limit_cannot_be_judged_is_not_held_to_its_working_range(tmp_path):
    """IC14. The input's least limit follows VDD, and no source holds V33: that end is not judged, and
    a working range judged beside it would read as a pass of the pin."""
    net, mpns = circuit(U1=("MCU", "MCU-1", mcu()))
    follows = pin("PA0", ["3"], "input", abs=[{"pin": "VDD", "plus": -3.9}, 4.6], operating=[0, 3.6])
    facts = library(tmp_path, {**MCU_FACTS, "pins": [*MCU_FACTS["pins"][:2], follows]})
    report = ratings.judge(net, mpns, facts, project({"SIG": (0.0, 3.3), **GND}), NASA)
    assert [f.rule for f in report.findings if f.part == "U1.3"] == ["pin.voltage"]


def test_a_part_s_name_alone_leaves_out_the_output_its_divider_sets():
    """NS02. U1's divider holds VOUT at 3.2 to 3.4 V. With U1 left out by its name, every source of
    U1 is out, that one too, and nothing drives VOUT."""
    net = board(
        U1={"1": ("VIN", "IN", "power_in"), "2": ("VOUT", "OUT", "power_out")}, C1={"1": "VOUT", "2": "GND"}
    )
    models = {"U1": ratings.Model(quiet=frozenset({"1", "2"})), "C1": CAP}
    fed, declared = {"VOUT": [("U1", (3.2, 3.4))]}, {"VIN": (4.5, 5.5), **GND}
    assert ratings.net_spans(net, models, declared, fed=fed).held["VOUT"] == (3.2, 3.4)
    alone = ratings.net_spans(net, models, declared, without="U1", fed=fed)
    assert "VOUT" not in alone.held and alone.why["VOUT"] == "nothing drives it"


def test_an_acceptance_that_meets_2_failures_fails_under_the_rule_accepted(tmp_path):
    """JG49. Its line is no stress of the rule it names: no entry of `accepted` takes it."""
    in_cap = {"capacitor": {"from": "IN", "to": "GND", "farads_min": 1e-6}, "page": 5}
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO))
    facts = library(tmp_path, regulator(needs=[in_cap, OUT_CAP]))
    stated = project(V5, accepted={("U1", "needs.capacitor"): "the owner's decision of 2026-11-17"})
    report = ratings.judge(net, mpns, facts, stated, NASA)
    assert [f.rule for f in report.findings if "name the 1 it means" in f.text] == ["accepted"]


def test_an_inductor_at_the_greatest_value_asked_holds(tmp_path):
    """NE09. 4.7 uH of 0 % tolerance on a need of 1.5 uH to 4.7 uH: 4.7 uH is inside, at its end."""
    net, mpns = circuit(U1=("BUCK", "BUCK-1", BUCK_PINS), L1=("4.7u", "L-1", {"1": "SW", "2": "V33"}))
    coil = entry("inductor", "L-1", tolerance=0, amps_saturation=2.0)
    nets = {"V12": (11.4, 12.6), "V33": (3.2, 3.4), **GND}
    report = ratings.judge(net, mpns, library(tmp_path, BUCK, coil), project(nets), NASA)
    assert "hold U1 pin SW (SW) needs 1.5 uH to 4.7 uH, L1 is 4.7 uH to 4.7 uH [DS-1, rev A, p 12]" in [
        f.line for f in report.findings
    ]


def test_the_gate_s_summary_is_the_line_of_counts_without_the_command_s_name(tmp_path):
    """GT09. The workcenter prints `FAIL ratings <summary>`: the name stands there once."""
    result = gate(tmp_path, capacitors("C16"), facts=(WEAK,))
    assert result.summary.startswith("1 fail, 0 accepted, 0 hold, 0 not judged; pack nasa-eee-inst-002")


def test_the_gate_skips_a_project_with_no_ratings_json(tmp_path):
    """GT14. A project that asks for no judgement is skipped, with the command that starts one."""
    cli = types.SimpleNamespace(
        Result=lambda *a, **k: types.SimpleNamespace(gate=a[0], status=a[1], summary=a[2])
    )
    board_ = types.SimpleNamespace(sch=tmp_path / "x.kicad_sch", dir=tmp_path)
    result = ratings.gate_ratings(board_, tmp_path / "build", [], False, cli)
    assert (result.status, result.summary) == (
        "skip",
        f"no ratings.json beside the schematic: `workcenter ratings {tmp_path} --init` writes one",
    )
    assert not (tmp_path / "build").exists()


# `workcenter ratings` itself: cmd_ratings with the workcenter's 7 parts it calls stood in for.


def command(folder: Path, text: str = NETLIST, rows: tuple = (), **flags):
    """cmd_ratings on a project in `folder` whose schematic exports `text`. Returns its exit code and the
    paths it read parts files from. emit prints `status summary` for each result, and nothing for --json."""
    read: list[Path] = []

    def emit(results, args, out):
        for r in results if not args.json else []:
            print(f"{r.status} {r.summary}")
        return 1 if any(r.status in ("fail", "error") for r in results) else 0

    def out_dir_for(project, out):
        path = Path(out) if out else project.dir / "build"
        path.mkdir(parents=True, exist_ok=True)
        return path

    cli = types.SimpleNamespace(
        Result=lambda gate, status, summary, details=None, artifacts=None: types.SimpleNamespace(
            gate=gate, status=status, summary=summary, details=details or {}, artifacts=artifacts or []
        ),
        schematic_netlist=lambda project, out: (text, ""),
        SRC_DIR=ROOT,
        read_parts=lambda path: read.append(path) or list(rows),
        find_project=lambda p: types.SimpleNamespace(dir=folder, sch=folder / "x.kicad_sch", name="x"),
        out_dir_for=out_dir_for,
        emit=emit,
        timed=lambda fn: fn,
    )
    args = {"project": str(folder), "out": None, "strict": False, "parts": None, "init": False}
    args = types.SimpleNamespace(**{**args, "facts": None, "json": False, **flags})
    return ratings.cmd_ratings(args, cli), read


PARTS_HEADER = "Value,Footprint,Qty,Manufacturer,MPN,Supplier,SKU,Pack,Breaks\n"


def test_init_writes_ratings_json_once_and_exits_0(tmp_path, capsys):
    """CM01, CM02. A second --init leaves the file as it is."""
    assert command(tmp_path, init=True)[0] == 0
    stated = tmp_path / "ratings.json"
    assert json.loads(stated.read_text(encoding="utf-8")) == {"pack": "nasa-eee-inst-002", "nets": {}}
    assert capsys.readouterr().out == f"wrote {stated}: pack nasa-eee-inst-002, no net stated yet\n"
    stated.write_text("{}", encoding="utf-8")
    assert command(tmp_path, init=True)[0] == 0
    assert stated.read_text(encoding="utf-8") == "{}"
    assert capsys.readouterr().out == f"{stated} is there already: nothing written\n"


def test_a_run_reads_the_project_s_parts_csv_or_the_files_parts_names(tmp_path):
    """CM03, CM12."""
    (tmp_path / "parts.csv").write_text(PARTS_HEADER, encoding="utf-8")
    (tmp_path / "other.csv").write_text(PARTS_HEADER, encoding="utf-8")
    assert command(tmp_path, facts="C1")[1] == [tmp_path / "parts.csv"]
    assert command(tmp_path, facts="C1", parts=[str(tmp_path / "other.csv")])[1] == [tmp_path / "other.csv"]


def test_facts_of_a_part_the_schematic_lacks_is_refused(tmp_path):
    """CM04."""
    with pytest.raises(SystemExit) as caught:
        command(tmp_path, facts="X9")
    assert str(caught.value) == "X9 is no part of the schematic"


def test_facts_of_a_part_name_its_part_number_from_the_parts_file(tmp_path, capsys):
    """CM05. C1 is 100n in an 0603 footprint, and the parts file's row of that Value and Footprint
    names GRM188R71C104KA01D."""
    (tmp_path / "parts.csv").write_text(PARTS_HEADER, encoding="utf-8")
    row = types.SimpleNamespace(
        value="100n", footprint="Capacitor_SMD:C_0603_1608Metric", buys=True, mpn="GRM188R71C104KA01D"
    )
    assert command(tmp_path, rows=(row,), facts="C1")[0] == 0
    assert json.loads(capsys.readouterr().out)["mpn"] == "GRM188R71C104KA01D"


def test_a_skipped_run_leaves_no_record_and_a_judged_one_leaves_its_own(tmp_path, capsys):
    """CM06, CM07, CM13, CM08. With no ratings.json the run is skipped and writes nothing. A run that
    fails leaves report.json with its status, which `workcenter next` reads, and prints its verdict
    unless --json asks for the JSON alone."""
    record = tmp_path / "build" / "ratings" / "report.json"
    assert command(tmp_path)[0] == 0
    assert capsys.readouterr().out.startswith("skip no ratings.json beside the schematic: ")
    assert not record.exists()
    stated = {"VIN": {"volts": [0, 30], "source": "s"}, "GND": {"volts": [0, 0], "source": "s"}}
    (tmp_path / "ratings.json").write_text(json.dumps({"pack": "nasa-eee-inst-002", "nets": stated}))
    assert command(tmp_path)[0] == 1
    saved = json.loads(record.read_text(encoding="utf-8"))
    assert (saved["gate"], saved["status"]) == ("ratings", "fail")
    assert capsys.readouterr().out.splitlines()[-1].startswith("NOTHING JUDGED")
    command(tmp_path, json=True)
    assert capsys.readouterr().out == ""
