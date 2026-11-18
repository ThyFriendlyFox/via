"""tools/simneeds.py: the decks a schematic asks for, read from netlists written here by hand.

Each netlist is the smallest that shows 1 rule: an I2C line by its net's name or a pin's name, a pull-up
to a rail and not to ground, a regulator by its library, a load from ratings.json, a deck that answers
by its `* deck:` line. No engine runs.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import ratings  # noqa: E402
import simneeds  # noqa: E402

SAMPLE = ROOT / "tests" / "samples" / "ratings" / "pass-ratings-node.xml"
# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {"nxp-um10204": "Rev. 7.0, table 11, page 44 and section 7.1, page 50"}


def netlist(parts: list[tuple[str, str, str]], nets: dict[str, list[tuple[str, str, str, str]]]):
    """A netlist in KiCad's XML form: parts as (ref, value, lib:part), nets as {name: [(ref, pin,
    pinfunction, pintype)]}."""
    comps = "".join(
        f'<comp ref="{r}"><value>{v}</value><libsource lib="{lib}" part="{name}"/></comp>'
        for r, v, (lib, name) in ((r, v, s.split(":")) for r, v, s in parts)
    )
    body = "".join(
        f'<net name="{name}">'
        + "".join(f'<node ref="{r}" pin="{p}" pinfunction="{f}" pintype="{t}"/>' for r, p, f, t in nodes)
        + "</net>"
        for name, nodes in nets.items()
    )
    return ratings.read_netlist(f"<export><components>{comps}</components><nets>{body}</nets></export>")


def bus(sda: str = "/SDA", rail: str = "+3V3", pin: str = "Pin_2_2", value: str = "4.7k"):
    """A header J1 with 1 line, pulled up by R1 (4.7k unless `value` says) to `rail`."""
    return netlist(
        [("J1", "I2C", "Connector_Generic:Conn_01x02"), ("R1", value, "Device:R")],
        {
            rail: [("J1", "1", "Pin_1_1", "passive"), ("R1", "1", "", "passive")],
            sda: [("J1", "2", pin, "passive"), ("R1", "2", "", "passive")],
        },
    )


def test_a_pulled_up_sda_net_asks_for_a_rise_time_deck():
    """The net /SDA (SDA on the root sheet) with R1 4.7k to +3V3: 1 need, its line names the net, the
    pull-up with its value and UM10204's table and page."""
    (need,) = simneeds.needs(bus(), [], {})
    assert need.kind == "i2c-rise" and need.names == ("SDA",)
    assert need.line == (
        "not judged: the I2C lines SDA are pulled up by R1 (4.7k) and no deck says "
        "`* deck: i2c-rise SDA`: their rise time is held to nothing (UM10204 Rev. 7.0, Table 11, page 44); "
        "copy templates/project/sim/i2c_rise.cir"
    )


def test_a_line_is_known_by_a_word_of_its_name_or_of_a_pin_name():
    """I2C1_SDA and SCL2 are I2C lines by their words; a net named DATA is one by a pin named PB1/SDA on
    it; SDAX and ISCL are not (SDA or SCL is no whole word of them, with digits or without)."""
    assert simneeds.needs(bus("I2C1_SDA"), [], {})[0].names == ("I2C1_SDA",)
    assert simneeds.needs(bus("SCL2"), [], {})[0].names == ("SCL2",)
    assert simneeds.needs(bus("DATA", pin="PB1/SDA_2"), [], {})[0].names == ("DATA",)
    assert simneeds.needs(bus("SDAX", pin="Pin_2_2"), [], {}) == []
    assert simneeds.needs(bus("ISCL", pin="Pin_2_2"), [], {}) == []


def test_a_resistor_to_ground_is_no_pull_up():
    """R1 from SDA to GND pulls the line down: no rise-time need; to VDD_IO it is a pull-up."""
    assert simneeds.needs(bus(rail="GND"), [], {}) == []
    assert len(simneeds.needs(bus(rail="VDD_IO"), [], {})) == 1


def test_a_net_with_a_power_pin_is_a_rail_whatever_its_name():
    """R1 goes to LDO_OUT, a name no rail pattern takes; U1's power_out pin stands on it: a pull-up."""
    n = netlist(
        [("U1", "LDO", "Regulator_Linear:X"), ("R1", "2.2k", "Device:R")],
        {
            "LDO_OUT": [("U1", "5", "OUT_5", "power_out"), ("R1", "1", "", "passive")],
            "SCL": [("R1", "2", "", "passive")],
        },
    )
    (need,) = simneeds.needs(n, [], {})
    assert need.names == ("SCL",) and "R1 (2.2k)" in need.line


def test_a_deck_answers_the_lines_it_names():
    """`* deck: i2c-rise SDA` with R1 at the schematic's 4.7k answers SDA. A deck naming SCL alone leaves
    SDA asked for."""
    assert simneeds.needs(bus(), [], {"i2c_rise": "* deck: i2c-rise SDA\nR1 vdd sda 4.7k\n.end\n"}) == []
    assert len(simneeds.needs(bus(), [], {"other": "* deck: i2c-rise SCL\n.end\n"})) == 1
    assert len(simneeds.needs(bus(), [], {"som_i2c": "* the I2C on SDA, pulled up by R1\n.end\n"})) == 1


def test_the_marker_is_read_in_any_case_and_with_commas():
    """`* DECK: I2C-RISE SDA` answers SDA; `* deck: i2c-rise SDA, SCL` answers both lines of a bus whose
    pull-ups R1 and R2 are 4.7k each."""
    assert simneeds.needs(bus(), [], {"d": "* DECK: I2C-RISE SDA\nR1 vdd sda 4.7k\n"}) == []
    deck = "* deck: i2c-rise SDA, SCL\nR1 vdd sda 4.7k\n"
    assert simneeds.needs(bus_of_2("4.7k", "4.7k"), [], {"d": deck}) == []


def bus_of_2(sda_ohms: str, scl_ohms: str):
    """SDA pulled up by R1 and SCL by R2 to +3V3, beside J1."""
    return netlist(
        [
            ("J1", "I2C", "Connector_Generic:Conn_01x03"),
            ("R1", sda_ohms, "Device:R"),
            ("R2", scl_ohms, "Device:R"),
        ],
        {
            "+3V3": [
                ("J1", "1", "Pin_1_1", "passive"),
                ("R1", "1", "", "passive"),
                ("R2", "1", "", "passive"),
            ],
            "SDA": [("J1", "2", "Pin_2_2", "passive"), ("R1", "2", "", "passive")],
            "SCL": [("J1", "3", "Pin_3_3", "passive"), ("R2", "2", "", "passive")],
        },
    )


def test_a_deck_whose_pull_up_is_not_the_schematics_fails():
    """The schematic's R1 is 4.7k, the deck runs R1 at 47k: the deck's tr is 10 times the board's
    (0.8473 x Rp x Cb, UM10204 section 7.1, page 50), so the deck answers nothing: 1 failure, not a
    warning. 4k7 in the schematic and 4.7k in the deck are both 4700 ohm: they agree."""
    (need,) = simneeds.needs(bus(), [], {"i2c_rise": "* deck: i2c-rise SDA\nR1 vdd sda 47k\n"})
    assert need.failed and need.line == (
        "i2c_rise.cir: R1 is 47k in the deck and 4.7k in the schematic, on SDA: the deck does not run "
        "the board's pull-up; write the schematic's value"
    )
    assert simneeds.needs(bus(value="4k7"), [], {"d": "* deck: i2c-rise SDA\nr1 vdd sda 4.7k\n"}) == []


def test_a_deck_that_models_none_of_the_pull_ups_fails():
    """`* deck: i2c-rise SDA` over a deck whose resistor is RP, not R1: it runs no pull-up of the board."""
    (need,) = simneeds.needs(bus(), [], {"d": "* deck: i2c-rise SDA\nRP vdd sda 4.7k\n"})
    assert need.failed and need.line == (
        "d.cir: says `* deck: i2c-rise SDA` and has no line for R1 (4.7k): name each pull-up as the "
        "schematic does, with its value"
    )


def test_one_pull_up_stands_for_another_of_its_value_only():
    """The deck runs R1 alone. R2 at R1's 4.7k is stood for (the template: 1 line stands for the bus
    when every line has the same pull-up); R2 at 10k is not."""
    deck = {"d": "* deck: i2c-rise SDA SCL\nR1 vdd sda 4.7k\n"}
    assert simneeds.needs(bus_of_2("4.7k", "4.7k"), [], deck) == []
    (need,) = simneeds.needs(bus_of_2("4.7k", "10k"), [], deck)
    assert need.failed and need.line == (
        "d.cir: R2 (10k) on SCL has no line in the deck, and no pull-up the deck runs has its value: "
        "name it as the schematic does, with its value"
    )


def test_a_pull_up_written_as_a_parameter_is_not_judged():
    """R1 is `{rp}` in the deck: the gate reads no number from it, so the line is not judged, and stays
    asked for (a warning, a failure with --strict)."""
    (need,) = simneeds.needs(bus(), [], {"d": "* deck: i2c-rise SDA\n.param rp=4.7k\nR1 vdd sda {rp}\n"})
    assert not need.failed and need.line == (
        "not judged: d.cir: R1 is {rp} in the deck and 4.7k in the schematic, on SDA: the gate reads no "
        "number from one of them, so the deck's pull-up is not compared with the board's"
    )


def test_a_load_step_deck_runs_the_regulator_it_names():
    """`* deck: load-step U1` answers U1 only in a deck that runs it: a line XU1. Without one: 1
    failure."""
    net = ratings.read_netlist(SAMPLE.read_text(encoding="utf-8"))
    assert simneeds.needs(net, ["J2.1 1.1 A"], {"s": "* deck: load-step U1\nXU1 in 0 out M\n"}) == []
    (need,) = simneeds.needs(net, ["J2.1 1.1 A"], {"s": "* deck: load-step U1\nV1 a 0 1\n"})
    assert need.failed and need.line == (
        "s.cir: says `* deck: load-step U1` and no line runs U1 (an element XU1): the deck does not run "
        "the board's regulator"
    )


def test_a_rail_on_a_sub_sheet_is_known_by_its_last_name():
    """R1 goes to /power/+3V3, a net of a sub-sheet with no power pin on it: +3V3 is a rail's name."""
    (need,) = simneeds.needs(bus(rail="/power/+3V3"), [], {})
    assert need.names == ("SDA",)


def test_a_net_named_0v_or_com_or_with_only_ground_pins_is_ground():
    """R1 from SDA to 0V or to COM, each with a sensor's GND pin (power_in) on it, pulls down; so does a
    net named PWR whose only power pin is named VSS. The same net with a pin named VDD is a rail."""
    for ground, pin in (("0V", "GND"), ("COM", "GND"), ("PWR", "VSS")):
        n = netlist(
            [("U2", "SENSOR", "Sensor:X"), ("R1", "100k", "Device:R")],
            {
                ground: [("U2", "4", pin, "power_in"), ("R1", "1", "", "passive")],
                "SDA": [("U2", "2", "SDA", "bidirectional"), ("R1", "2", "", "passive")],
            },
        )
        assert simneeds.needs(n, [], {}) == [], ground
    n = netlist(
        [("U2", "SENSOR", "Sensor:X"), ("R1", "100k", "Device:R")],
        {
            "PWR": [("U2", "4", "VDD", "power_in"), ("R1", "1", "", "passive")],
            "SDA": [("U2", "2", "SDA", "bidirectional"), ("R1", "2", "", "passive")],
        },
    )
    assert len(simneeds.needs(n, [], {})) == 1


def test_a_pull_up_is_known_by_its_symbol_whatever_its_reference():
    """RP1, a Device:R, pulls SDA up: 1 need that names it."""
    n = netlist(
        [("J1", "I2C", "Connector_Generic:Conn_01x02"), ("RP1", "4.7k", "Device:R")],
        {
            "+3V3": [("J1", "1", "Pin_1_1", "passive"), ("RP1", "1", "", "passive")],
            "SDA": [("J1", "2", "Pin_2_2", "passive"), ("RP1", "2", "", "passive")],
        },
    )
    (need,) = simneeds.needs(n, [], {})
    assert "RP1 (4.7k)" in need.line


def test_a_resistor_array_on_a_line_is_not_judged():
    """RN1, a Device:R_Pack02 with 2 of its pins on SDA and +3V3, stands on the line: simneeds reads no
    array, and says so in 1 line that no deck answers. So does RN2 of a library of the board's own, and
    R3, a Device:R_Small drawn with 3 pins on nets."""
    n = netlist(
        [("J1", "I2C", "Connector_Generic:Conn_01x02"), ("RN1", "4.7k", "Device:R_Pack02")],
        {
            "+3V3": [("J1", "1", "Pin_1_1", "passive"), ("RN1", "1", "R1.1", "passive")],
            "SDA": [("J1", "2", "Pin_2_2", "passive"), ("RN1", "4", "R1.2", "passive")],
        },
    )
    line = (
        "not judged: the I2C line SDA meets RN1 (Device:R_Pack02, 4.7k), a resistor array or network: "
        "simneeds reads 2-pin resistors only, so its pull-up is not known and its rise time is held to "
        f"nothing ({simneeds.UM10204})"
    )
    assert [x.line for x in simneeds.needs(n, [], {})] == [line]
    assert [x.line for x in simneeds.needs(n, [], {"d": "* deck: i2c-rise SDA\nR1 vdd sda 4.7k\n"})] == [line]
    n = netlist(  # RP5 is known for an array by its symbol alone
        [("J1", "I2C", "Connector_Generic:Conn_01x02"), ("RP5", "4.7k", "Device:R_Pack04")],
        {
            "+3V3": [("J1", "1", "Pin_1_1", "passive"), ("RP5", "1", "R1.1", "passive")],
            "SDA": [("J1", "2", "Pin_2_2", "passive"), ("RP5", "8", "R1.2", "passive")],
        },
    )
    assert [x.line for x in simneeds.needs(n, [], {})] == [
        line.replace("RN1 (Device:R_Pack02", "RP5 (Device:R_Pack04")
    ]
    for ref, symbol in (("RN2", "Board:PULLUPS"), ("R3", "Device:R_Small")):
        n = netlist(
            [("J1", "I2C", "Connector_Generic:Conn_01x02"), (ref, "4.7k", symbol)],
            {
                "+3V3": [("J1", "1", "Pin_1_1", "passive"), (ref, "1", "", "passive")],
                "SDA": [("J1", "2", "Pin_2_2", "passive"), (ref, "2", "", "passive")],
                "SCL": [(ref, "3", "", "passive")],
            },
        )
        found = [x.line for x in simneeds.needs(n, [], {})]
        assert found and all(f"meets {ref} ({symbol}, 4.7k), a resistor array" in x for x in found), found


def test_every_sheet_the_root_names_is_read(tmp_path):
    """The root names sheets/bus.kicad_sch, which names ../power.kicad_sch; a third file beside them is
    named by no sheet and is not read. A sheet named and absent is named in the second list."""
    (tmp_path / "sheets").mkdir()
    root = tmp_path / "top.kicad_sch"
    root.write_text('(kicad_sch (sheet (property "Sheetfile" "sheets/bus.kicad_sch")))')
    (tmp_path / "sheets" / "bus.kicad_sch").write_text(
        '(kicad_sch (label "SDA") (sheet (property "Sheetfile" "../power.kicad_sch")))'
    )
    (tmp_path / "power.kicad_sch").write_text('(kicad_sch (sheet (property "Sheetfile" "gone.kicad_sch")))')
    (tmp_path / "other.kicad_sch").write_text('(kicad_sch (label "SCL"))')
    texts, unread = simneeds.schematic_texts(root)
    assert len(texts) == 3 and any('(label "SDA")' in t for t in texts)
    assert not any('(label "SCL")' in t for t in texts)
    assert unread == [str(tmp_path / "gone.kicad_sch")]


def test_a_regulator_with_a_stated_load_asks_for_a_load_step_deck():
    """tests/samples/ratings/pass-ratings-node.xml (kicad-cli 10.0.8) holds U1, a TLV62569DBV of
    Regulator_Switching; with the 1.1 A its ratings.json states on J2.1 it asks for 1 deck. Without a
    stated load it asks for none, and a `* deck: load-step U1` answers it."""
    net = ratings.read_netlist(SAMPLE.read_text(encoding="utf-8"))
    (need,) = simneeds.needs(net, ["J2.1 1.1 A"], {})
    assert need.kind == "load-step" and need.names == ("U1",)
    assert need.line == (
        "not judged: U1 (Regulator_Switching:TLV62569DBV) feeds the loads ratings.json states (J2.1 1.1 A) "
        "and no deck says `* deck: load-step U1`: its output under a load step is held to nothing (its "
        "datasheet's load transient); copy templates/project/sim/load_step.cir"
    )
    assert simneeds.needs(net, [], {}) == []
    assert simneeds.needs(net, ["J2.1 1.1 A"], {"step": "* deck: load-step U1\nXU1 in 0 out M\n"}) == []


def test_stated_loads_are_the_amps_above_0(tmp_path):
    """J2.1 at 1.1 A and J3.2 at 0 A (a logic input): 1 load. A file that is not JSON states none."""
    path = tmp_path / "ratings.json"
    path.write_text(json.dumps({"parts": {"J2.1": {"amps": 1.1}, "J3.2": {"amps": 0}, "C7": {"volts": 3}}}))
    assert simneeds.stated_loads(path) == ["J2.1 1.1 A"]
    path.write_text("{")
    assert simneeds.stated_loads(path) == []
    assert simneeds.stated_loads(tmp_path / "absent.json") == []


def test_only_a_schematic_that_can_hold_a_need_is_worth_a_netlist():
    """A label SDA, a net I2C1_SCL or a regulator's library makes the export worth its run; ESDA and a
    divider do not."""
    assert simneeds.worth_reading(['(label "SDA"'])
    assert simneeds.worth_reading(['(net "I2C1_SCL")'])
    assert simneeds.worth_reading(['(lib_id "Regulator_Linear:TLV75533PDBV")'])
    assert not simneeds.worth_reading(['(lib_id "Device:R") (label "VOUT") (label "ESDA")'])


def test_a_copy_never_takes_a_name_in_use(tmp_path):
    """sim/ holds i2c_rise.cir and i2c_rise_2.expect.json: the next free name is i2c_rise_3."""
    assert simneeds.free_name(tmp_path, "i2c_rise") == "i2c_rise"
    (tmp_path / "i2c_rise.cir").write_text("")
    (tmp_path / "i2c_rise_2.expect.json").write_text("")
    assert simneeds.free_name(tmp_path, "i2c_rise") == "i2c_rise_3"
