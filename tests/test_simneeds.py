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


def bus(sda: str = "/SDA", rail: str = "+3V3", pin: str = "Pin_2_2"):
    """A header J1 with 1 line, pulled up by R1 4.7k to `rail`."""
    return netlist(
        [("J1", "I2C", "Connector_Generic:Conn_01x02"), ("R1", "4.7k", "Device:R")],
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
    """`* deck: i2c-rise SDA` answers SDA. A deck naming SCL alone leaves SDA asked for."""
    assert simneeds.needs(bus(), [], {"i2c_rise": "* deck: i2c-rise SDA\nV1 a 0 1\n.end\n"}) == []
    assert len(simneeds.needs(bus(), [], {"other": "* deck: i2c-rise SCL\n.end\n"})) == 1
    assert len(simneeds.needs(bus(), [], {"som_i2c": "* the I2C on SDA, pulled up by R1\n.end\n"})) == 1


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
    assert simneeds.needs(net, ["J2.1 1.1 A"], {"step": "* deck: load-step U1\n"}) == []


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
