"""`tools/ratings.py`: a schematic held to its parts' ratings.

No engine runs here. A netlist is the text `kicad-cli sch export netlist --format kicadxml` writes,
cut down to what the reader takes from it; facts, a project's file and a rule pack are written in
tmp_path. `tests/test_ratings_cli.py` runs the command on schematics.
"""

from __future__ import annotations

import json
import re
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKS = ROOT / "rules" / "ratings"
sys.path.insert(0, str(ROOT / "tools"))
import ratings  # noqa: E402

# What kicad-cli 10.0.8 writes for a divider from VIN to GND with a capacitor on its tap, a header and
# a pin left open: the elements and attributes are copied from an export of tests/boards/pass-rc-divider
# and of a board with an IC (the `+no_connect` type, the `unconnected-(...)` net, and `pinfunction`,
# which is the pin's name, an underscore and its number).
NETLIST = """<?xml version="1.0" encoding="UTF-8"?>
<export version="E">
  <components>
    <comp ref="R1"><value>10k</value><footprint>Resistor_SMD:R_0603_1608Metric</footprint>
      <fields><field name="Footprint">Resistor_SMD:R_0603_1608Metric</field><field name="Datasheet"/></fields>
      <libsource lib="Device" part="R" description="Resistor"/></comp>
    <comp ref="R2"><value>10k</value><footprint>Resistor_SMD:R_0603_1608Metric</footprint>
      <libsource lib="Device" part="R" description="Resistor"/></comp>
    <comp ref="C1"><value>100n</value><footprint>Capacitor_SMD:C_0603_1608Metric</footprint>
      <libsource lib="Device" part="C" description="Unpolarized capacitor"/></comp>
    <comp ref="U1"><value>MCU</value><footprint>Package_SO:SOIC-8_3.9x4.9mm_P1.27mm</footprint>
      <libsource lib="Test" part="MCU" description="a microcontroller"/>
      <property name="exclude_from_bom"/></comp>
  </components>
  <nets>
    <net code="1" name="GND" class="Default">
      <node ref="C1" pin="2" pintype="passive"/>
      <node ref="R2" pin="2" pintype="passive"/>
      <node ref="U1" pin="4" pinfunction="VSS_4" pintype="power_in"/>
    </net>
    <net code="2" name="/VIN" class="Default">
      <node ref="R1" pin="1" pintype="passive"/>
    </net>
    <net code="3" name="/TAP" class="Default">
      <node ref="C1" pin="1" pintype="passive"/>
      <node ref="R1" pin="2" pintype="passive"/>
      <node ref="R2" pin="1" pintype="passive"/>
      <node ref="U1" pin="3" pinfunction="PA0_3" pintype="bidirectional"/>
    </net>
    <net code="4" name="unconnected-(U1-PA1-Pad2)" class="Default">
      <node ref="U1" pin="2" pinfunction="PA1_2" pintype="bidirectional+no_connect"/>
    </net>
  </nets>
</export>
"""


# ---------------------------------------------------------------- the Value of a passive part


@pytest.mark.parametrize(
    ("text", "number"),
    [
        ("10k", 10e3),
        ("4.7k", 4.7e3),
        ("4k7", 4.7e3),
        ("4R7", 4.7),
        ("100R", 100.0),
        ("100", 100.0),
        ("0", 0.0),
        ("0.33", 0.33),
        ("20m", 0.02),
        ("1M", 1e6),
        ("1Meg", 1e6),
        ("560k", 560e3),
        ("100n", 100e-9),
        ("100nF", 100e-9),
        ("4.7u", 4.7e-6),
        ("4u7", 4.7e-6),
        ("10µ", 10e-6),
        ("10μF", 10e-6),
        ("15p", 15e-12),
        ("2.2uH", 2.2e-6),
        ("10kΩ", 10e3),
        ("100nF/50V", 100e-9),
        ("10k 1%", 10e3),
        ("2.2u XAL4020-222", 2.2e-6),
        ("100k NCP15WF104", 100e3),
        ("100 nF", 100e-9),  # a space before the unit: the prefix belongs to the number
        ("10 k", 10e3),
        ("2.2 uH", 2.2e-6),
        ("10 mΩ", 10e-3),
        ("15 pF", 15e-12),
        ("4.7 µF 10V", 4.7e-6),
        ("100 R", 100.0),
        ("100 1%", 100.0),  # 100 ohm: what follows is a tolerance, no second value
    ],
)
def test_a_value_is_read_as_the_number_an_engineer_reads(text, number):
    assert ratings.part_value(text) == pytest.approx(number, rel=1e-12)


@pytest.mark.parametrize(
    "text", ["", "red", "BAT54S", "Conn_01x03", "k10", "1.2.3k", "10kk", "4k7k", "-5k", "1e3"]
)
def test_a_value_that_is_no_number_is_none_and_never_a_guess(text):
    """A wrong number is a wrong verdict: `1e3` and `-5k` are forms no schematic here writes, and the
    reader takes neither."""
    assert ratings.part_value(text) is None


@pytest.mark.parametrize("text", ["0402 10k", "1/4W 10k", "0603 100n 16V", "1 2k2", "50 100nF"])
def test_a_value_of_2_numbers_is_none_when_the_first_is_bare(text):
    """A case size or a rating before the value: `0402 10k` is not 402 ohm and `1/4W 10k` is not 1
    ohm. A bare number followed by a second value does not say which of the 2 is the part's."""
    assert ratings.part_value(text) is None


def test_m_is_milli_and_capital_m_is_mega():
    """KiCad's own netlist writes 1M as 1Meg for a resistor, and ngspice reads M as milli (AGENTS.md,
    "KiCad's passive values"). A schematic's Value is read the way its writer meant it."""
    assert ratings.part_value("1m") == pytest.approx(1e-3)
    assert ratings.part_value("1M") == pytest.approx(1e6)


# ---------------------------------------------------------------- the netlist


def test_the_netlist_gives_each_part_its_value_footprint_and_symbol():
    net = ratings.read_netlist(NETLIST)
    assert sorted(net.parts) == ["C1", "R1", "R2", "U1"]
    r1 = net.parts["R1"]
    assert (r1.value, r1.footprint, r1.symbol) == ("10k", "Resistor_SMD:R_0603_1608Metric", "Device:R")
    assert net.parts["U1"].in_bom is False and r1.in_bom is True


def test_a_net_of_the_root_sheet_loses_its_slash_and_keeps_its_pins():
    net = ratings.read_netlist(NETLIST)
    assert sorted(net.nets) == ["GND", "TAP", "VIN", "unconnected-(U1-PA1-Pad2)"]
    tap = {(n.ref, n.pin): n for n in net.nets["TAP"]}
    assert sorted(tap) == [("C1", "1"), ("R1", "2"), ("R2", "1"), ("U1", "3")]
    assert (tap[("U1", "3")].name, tap[("U1", "3")].kind) == ("PA0", "bidirectional")
    assert tap[("R1", "2")].name == ""


def test_a_net_of_a_sheet_below_the_root_keeps_its_whole_name():
    """KiCad names a net of the sheet `sub` /sub/FB. Only the root sheet's own nets lose their slash:
    `sub/FB` is a name no schematic holds."""
    below = NETLIST.replace('name="/TAP"', 'name="/sub/TAP"')
    net = ratings.read_netlist(below)
    assert "/sub/TAP" in net.nets and "sub/TAP" not in net.nets
    assert net.parts["R1"].pins["2"] == "/sub/TAP"


def test_a_local_net_keeps_its_slash_when_a_global_net_has_its_name():
    """KiCad keeps `VIN` (a power symbol) and `/VIN` (a label of the root sheet) apart. Read as 1 net,
    the pins of 2 would be judged as if they met."""
    both = NETLIST.replace('<net code="1" name="GND"', '<net code="1" name="VIN"')
    net = ratings.read_netlist(both)
    assert sorted(net.nets) == ["/VIN", "TAP", "VIN", "unconnected-(U1-PA1-Pad2)"]
    assert net.parts["R1"].pins["1"] == "/VIN" and net.parts["R2"].pins["2"] == "VIN"


def test_a_part_knows_the_net_of_each_of_its_pins():
    net = ratings.read_netlist(NETLIST)
    assert net.parts["R1"].pins == {"1": "VIN", "2": "TAP"}
    assert net.parts["U1"].pins == {"4": "GND", "3": "TAP", "2": "unconnected-(U1-PA1-Pad2)"}


def test_a_pin_left_open_is_marked_and_its_type_is_the_type_before_the_plus():
    net = ratings.read_netlist(NETLIST)
    (node,) = net.nets["unconnected-(U1-PA1-Pad2)"]
    assert (node.kind, node.open) == ("bidirectional", True)
    assert net.nets["TAP"][0].open is False


def test_a_part_marked_dnp_is_no_part_of_the_circuit():
    """kicad-cli writes `<property name="dnp"/>` for a part that is not fitted. It meets no need, loads
    no rail and lifts no net: no pin of it stands on a net, and the netlist names it apart."""
    fitted = 'description="Unpolarized capacitor"/></comp>'
    text = NETLIST.replace(fitted, fitted.replace("</comp>", '<property name="dnp"/></comp>'))
    assert text != NETLIST
    net = ratings.read_netlist(text)
    assert "C1" not in net.parts and net.absent == ["C1"]
    assert all(node.ref != "C1" for nodes in net.nets.values() for node in nodes)
    assert [node.ref for node in net.nets["TAP"]] == ["R1", "R2", "U1"]
    assert ratings.read_netlist(NETLIST).absent == []


def test_2_parts_with_1_reference_are_refused_by_what_the_schematic_holds():
    """kicad-cli writes 1 <comp> for 2 symbols annotated R1, and both symbols' pins: pin 1 of R1 then
    stands on 2 nets. The fault is the schematic's, and the message says which."""
    text = NETLIST.replace(
        '<net code="2" name="/VIN" class="Default">',
        '<net code="2" name="/VIN" class="Default">\n      <node ref="R2" pin="1" pintype="passive"/>',
    )
    with pytest.raises(ValueError, match="the schematic holds 2 parts with the reference R2"):
        ratings.read_netlist(text)


def test_a_real_export_of_kicad_cli_is_read_whole():
    """tests/samples/ratings/pass-ratings-node.xml is what kicad-cli 10.0.8 wrote for the fixture of
    that name (PROCESSES.md P7): 14 parts on 10 nets, 2 of them the nets of pins left open."""
    sample = ROOT / "tests" / "samples" / "ratings" / "pass-ratings-node.xml"
    net = ratings.read_netlist(sample.read_text(encoding="utf-8"))
    assert len(net.parts) == 14 and len(net.nets) == 10
    assert sorted(n for n in net.nets if not n.startswith("unconnected-(")) == [
        "+3V3",
        "+5V",
        "FB",
        "GND",
        "IN",
        "OUT",
        "SIG",
        "SW",
    ]
    u1 = net.parts["U1"]
    assert (u1.value, u1.symbol) == ("TLV62569", "Regulator_Switching:TLV62569DBV")
    assert u1.footprint == "Package_TO_SOT_SMD:SOT-23-5"
    assert u1.pins == {"1": "+5V", "2": "GND", "3": "SW", "4": "+5V", "5": "FB"}
    named = {n.pin: (n.name, n.kind) for nodes in net.nets.values() for n in nodes if n.ref == "U1"}
    assert named == {
        "1": ("EN", "input"),
        "2": ("GND", "power_in"),
        "3": ("SW", "power_out"),
        "4": ("VIN", "power_in"),
        "5": ("FB", "input"),
    }
    (left_open,) = net.nets["unconnected-(U2-NC-Pad1)"]
    assert (left_open.ref, left_open.pin, left_open.name, left_open.kind) == ("U2", "1", "NC", "no_connect")


def test_text_that_is_no_netlist_is_refused_with_what_is_wrong():
    with pytest.raises(ValueError, match="no <components>"):
        ratings.read_netlist("<export version='E'><nets/></export>")
    with pytest.raises(ValueError, match="not XML"):
        ratings.read_netlist("(export (version E))")


def test_a_pin_on_2_nets_is_refused():
    """One pin has one net. A netlist that says otherwise is not read as either."""
    twice = NETLIST.replace(
        '<node ref="R1" pin="1" pintype="passive"/>',
        '<node ref="R1" pin="1" pintype="passive"/><node ref="R2" pin="2" pintype="passive"/>',
    )
    with pytest.raises(ValueError, match=r"R2 pin 2 is on GND and on VIN"):
        ratings.read_netlist(twice)


# ---------------------------------------------------------------- resistors between held nets


def test_a_divider_tap_is_solved_and_not_taken_as_its_top_rail():
    """5.5 V on 10k over 10k is 2.75 V at the tap. The hull of the 2 rails says 5.5 V, which fails a
    3.6 V pin that the divider protects."""
    spans = ratings.resistor_spans(
        [("VIN", "TAP", 10e3, 10e3), ("TAP", "GND", 10e3, 10e3)], {"VIN": (0.0, 5.5), "GND": (0.0, 0.0)}
    )
    assert spans == {"TAP": (pytest.approx(0.0), pytest.approx(2.75))}


def test_a_divider_is_judged_at_the_corner_of_its_tolerances():
    """Top 1 % low and bottom 1 % high gives the highest tap: 5.5 x 10.1 / (9.9 + 10.1) = 2.7775."""
    spans = ratings.resistor_spans(
        [("VIN", "TAP", 9.9e3, 10.1e3), ("TAP", "GND", 9.9e3, 10.1e3)], {"VIN": (4.4, 5.5), "GND": (0.0, 0.0)}
    )
    low, high = spans["TAP"]
    assert high == pytest.approx(5.5 * 10.1 / 20.0)
    assert low == pytest.approx(4.4 * 9.9 / 20.0)


def test_a_chain_of_free_nodes_is_solved_together():
    """3 equal resistors from 3 V to ground: the 2 nodes between stand at 2 V and 1 V."""
    spans = ratings.resistor_spans(
        [("V", "A", 1e3, 1e3), ("A", "B", 1e3, 1e3), ("B", "GND", 1e3, 1e3)],
        {"V": (3.0, 3.0), "GND": (0.0, 0.0)},
    )
    assert spans["A"] == (pytest.approx(2.0), pytest.approx(2.0))
    assert spans["B"] == (pytest.approx(1.0), pytest.approx(1.0))


def test_a_node_with_one_way_out_stands_at_that_net():
    """A pull-up with nothing else on its node carries no current: the node is at the rail."""
    spans = ratings.resistor_spans([("V", "A", 10e3, 10e3)], {"V": (3.0, 3.3)})
    assert spans == {"A": (pytest.approx(3.0), pytest.approx(3.3))}


def test_a_node_no_resistor_ties_to_a_held_net_has_no_span():
    spans = ratings.resistor_spans([("A", "B", 1e3, 1e3)], {"V": (3.0, 3.3)})
    assert spans == {}


def test_a_zero_ohm_link_joins_its_2_nodes():
    spans = ratings.resistor_spans(
        [("V", "A", 0.0, 0.0), ("A", "B", 1e3, 1e3), ("B", "GND", 1e3, 1e3)],
        {"V": (2.0, 2.0), "GND": (0.0, 0.0)},
    )
    assert spans["A"] == (pytest.approx(2.0), pytest.approx(2.0))
    assert spans["B"] == (pytest.approx(1.0), pytest.approx(1.0))


def test_more_resistors_than_the_corners_can_cover_fall_back_to_the_hull():
    """13 resistors with a tolerance are 8192 corners. The answer is then the hull of the held nets the
    group meets: coarser, and never lower than the truth."""
    chain = [("V", "N0", 0.9e3, 1.1e3)]
    chain += [(f"N{i}", f"N{i + 1}", 0.9e3, 1.1e3) for i in range(11)]
    chain += [("N11", "GND", 0.9e3, 1.1e3)]
    spans = ratings.resistor_spans(chain, {"V": (1.0, 5.0), "GND": (0.0, 0.0)})
    assert len(chain) == 13 and len(spans) == 12
    assert all(span == (0.0, 5.0) for span in spans.values())


# ---------------------------------------------------------------- the span of each net
#
# 2 spans. `stress` is every voltage a net can stand at, with its sources on or off and each output
# driving or released: a rating is held to it, and 0 V is always inside it. `held` is what a net's own
# sources hold it to while they are on: a supply pin's working range is held to it.


def board(**parts: dict) -> ratings.Netlist:
    """A netlist from REF={pin: net}, or REF={pin: (net, name, kind)} for a pin with a name and a type.
    A pin given by its net alone is passive and has no name."""
    out, nets = {}, {}
    for ref, pins in parts.items():
        out[ref] = ratings.Part(ref, "", "", "", True)
        for pin, spec in pins.items():
            net, name, kind = (spec, "", "passive") if isinstance(spec, str) else spec
            out[ref].pins[pin] = net
            nets.setdefault(net, []).append(ratings.Node(ref, pin, name, kind, False))
    return ratings.Netlist(out, nets)


CAP = ratings.Model()  # puts nothing on its nets
GND = {"GND": (0.0, 0.0)}


def resistor(ohms: float, tolerance: float = 0.0) -> ratings.Model:
    return ratings.Model(ohms=(ohms * (1 - tolerance), ohms * (1 + tolerance)))


def test_a_declared_net_is_held_to_its_span_and_can_be_unpowered():
    net = board(C1={"1": "VBUS", "2": "GND"})
    got = ratings.net_spans(net, {"C1": CAP}, {"VBUS": (4.4, 5.5), **GND})
    assert got.held == {"VBUS": (4.4, 5.5), "GND": (0.0, 0.0)}
    assert got.stress == {"VBUS": (0.0, 5.5), "GND": (0.0, 0.0)}
    assert got.why == {}


def test_a_negative_rail_reaches_up_to_0():
    net = board(C1={"1": "VNEG", "2": "GND"})
    got = ratings.net_spans(net, {"C1": CAP}, {"VNEG": (-5.2, -4.8), **GND})
    assert got.stress["VNEG"] == (-5.2, 0.0)


def test_a_divider_tap_into_an_input_is_solved_and_is_not_the_hull():
    net = board(
        R1={"1": "VBUS", "2": "TAP"},
        R2={"1": "TAP", "2": "GND"},
        U1={"3": ("TAP", "PA0", "input")},
    )
    models = {"R1": resistor(10e3), "R2": resistor(10e3), "U1": ratings.Model(quiet=frozenset({"3"}))}
    got = ratings.net_spans(net, models, {"VBUS": (4.4, 5.5), **GND})
    assert got.stress["TAP"] == (pytest.approx(0.0), pytest.approx(2.75))
    assert "TAP" not in got.held
    assert got.why == {}


def test_a_net_behind_a_transistor_takes_the_hull_of_what_it_can_meet():
    """A switch is open or closed, and the net behind it is then anywhere between the rail and what
    pulls it down. No number between is safe to state."""
    net = board(
        Q1={"1": ("GATE", "G", "input"), "2": ("VBAT", "S", "passive"), "3": ("LOAD", "D", "passive")},
        R1={"1": "LOAD", "2": "GND"},
    )
    models = {"Q1": ratings.Model(passes=[("2", "3", False)], quiet=frozenset({"1"})), "R1": resistor(1e3)}
    got = ratings.net_spans(net, models, {"VBAT": (3.0, 4.2), "GATE": (0.0, 4.2), **GND})
    assert got.stress["LOAD"] == (0.0, 4.2)


def supply(volts: float) -> ratings.Model:
    return ratings.Model(drives={"1": ratings.Drive(volts, volts)}, quiet=frozenset())


def test_a_diode_lifts_its_cathode_and_never_its_anode():
    net = board(
        D1={"1": ("LOW", "A", "passive"), "2": ("HIGH", "K", "passive")},
        U1={"1": ("LOW", "OUT", "power_out")},
        U2={"1": ("HIGH", "OUT", "power_out")},
    )
    models = {"D1": ratings.Model(passes=[("1", "2", True)]), "U1": supply(1.0), "U2": supply(5.0)}
    got = ratings.net_spans(net, models, {})
    assert got.stress == {"LOW": (0.0, 1.0), "HIGH": (0.0, 5.0)}


def test_a_diode_from_a_higher_net_widens_a_rail():
    """A diode from 5 V into a 3.3 V rail can lift the rail: every pin on the rail then sees 5.5 V.
    The rail's own source still holds it at 3.3 V: that is what its loads are fed."""
    net = board(
        D1={"1": ("V5", "A", "passive"), "2": ("V33", "K", "passive")},
        U1={"1": ("V33", "OUT", "power_out")},
    )
    models = {"D1": ratings.Model(passes=[("1", "2", True)]), "U1": supply(3.3)}
    got = ratings.net_spans(net, models, {"V5": (4.5, 5.5)})
    assert got.stress["V33"] == (0.0, 5.5)
    assert got.held["V33"] == (3.3, 3.3)


def mcu(signal: str = "SIG") -> dict:
    return {
        "1": ("V33", "VDD", "power_in"),
        "2": ("GND", "VSS", "power_in"),
        "3": (signal, "PA0", "bidirectional"),
    }


MCU = ratings.Model(drives={"3": ratings.Drive(("2", 0.0), ("1", 0.0))}, quiet=frozenset({"1", "2"}))
RAILS = {"V33": (3.0, 3.3), **GND}


def test_an_output_spans_from_its_ground_pin_to_its_supply_pin():
    net = board(U1=mcu(), C1={"1": "SIG", "2": "GND"})
    got = ratings.net_spans(net, {"U1": MCU, "C1": CAP}, RAILS)
    assert got.stress["SIG"] == (0.0, 3.3)
    assert got.why == {}


def test_a_pull_up_to_a_higher_rail_lifts_a_driven_net():
    """A microcontroller releases its pins in reset. A 5 V pull-up then puts 5 V on a 3.3 V pin, and
    on every other pin of that net: the driver does not hold the net when it does not drive."""
    net = board(U1=mcu(), R1={"1": "V5", "2": "SIG"})
    got = ratings.net_spans(net, {"U1": MCU, "R1": resistor(4.7e3)}, {"V5": (4.5, 5.5), **RAILS})
    assert got.stress["SIG"] == (0.0, 5.5)


def test_a_pin_does_not_count_against_itself():
    """What a pin has to stand is what the others put on its net. A 3.3 V output on a net with a
    divider from 5 V is judged against the divider's tap, not against its own high level."""
    net = board(U1=mcu(), R1={"1": "V5", "2": "SIG"}, R2={"1": "SIG", "2": "GND"})
    models = {"U1": MCU, "R1": resistor(30e3), "R2": resistor(10e3)}
    declared = {"V5": (4.5, 5.5), **RAILS}
    assert ratings.net_spans(net, models, declared).stress["SIG"] == (0.0, 5.5)
    seen = ratings.net_spans(net, models, declared, without="U1")
    assert seen.stress["SIG"] == (pytest.approx(0.0), pytest.approx(5.5 / 4))


def test_a_regulator_output_is_held_to_a_span_of_its_own():
    net = board(
        U1={"1": ("VIN", "IN", "power_in"), "2": ("VOUT", "OUT", "power_out")}, C1={"1": "VOUT", "2": "GND"}
    )
    models = {
        "U1": ratings.Model(drives={"2": ratings.Drive(3.038, 3.162)}, quiet=frozenset({"1"})),
        "C1": CAP,
    }
    got = ratings.net_spans(net, models, {"VIN": (3.3, 4.2), **GND})
    assert got.held["VOUT"] == (3.038, 3.162)
    assert got.stress["VOUT"] == (0.0, 3.162)


def test_a_fuse_makes_2_nets_1_node():
    net = board(F1={"1": "VBAT", "2": "VSYS"}, C1={"1": "VSYS", "2": "GND"})
    models = {"F1": ratings.Model(links=[("1", "2")]), "C1": CAP}
    got = ratings.net_spans(net, models, {"VBAT": (3.0, 4.2), **GND})
    assert got.held["VSYS"] == (3.0, 4.2)
    assert got.stress["VSYS"] == (0.0, 4.2)


def test_a_net_nothing_drives_has_no_span_and_says_so():
    net = board(C1={"1": "FLOAT", "2": "GND"}, U1={"3": ("FLOAT", "PA0", "input")})
    got = ratings.net_spans(net, {"C1": CAP, "U1": ratings.Model(quiet=frozenset({"3"}))}, GND)
    assert "FLOAT" not in got.stress and "FLOAT" not in got.held
    assert got.why == {"FLOAT": "nothing drives it"}


def test_a_connector_pin_leaves_its_net_without_a_span_and_says_which_pin():
    """Nothing on the board says what stands behind a connector. The net has no span, and neither has
    a node that only a resistor parts from it."""
    net = board(J1={"1": "EXT"}, R1={"1": "EXT", "2": "NODE"}, C1={"1": "NODE", "2": "GND"})
    got = ratings.net_spans(net, {"R1": resistor(1e3), "C1": CAP}, GND)
    assert "EXT" not in got.stress and "NODE" not in got.stress
    assert "J1 pin 1" in got.why["EXT"]
    assert "J1 pin 1" in got.why["NODE"] and "R1" in got.why["NODE"]


def test_a_declared_net_with_a_connector_pin_keeps_what_the_project_declares():
    net = board(J1={"1": "VBUS"}, C1={"1": "VBUS", "2": "GND"})
    got = ratings.net_spans(net, {"C1": CAP}, {"VBUS": (4.4, 5.5), **GND})
    assert got.stress["VBUS"] == (0.0, 5.5)
    assert got.why == {}


def test_an_unknown_source_behind_a_resistor_reaches_a_driven_net():
    """A header behind 100 ohm can hold 12 V. Nothing says the driver wins, so the net has no span
    until the project declares the header's net."""
    net = board(U1=mcu(), R1={"1": "SIG", "2": "EXT"}, J1={"1": "EXT"})
    models = {"U1": MCU, "R1": resistor(100.0)}
    got = ratings.net_spans(net, models, RAILS)
    assert "SIG" not in got.stress
    assert "J1 pin 1" in got.why["SIG"] and "R1" in got.why["SIG"]
    stated = ratings.net_spans(net, models, {"EXT": (0.0, 3.3), **RAILS})
    assert stated.stress["SIG"] == (0.0, 3.3) and stated.why == {}


def test_an_unknown_source_reaches_a_driven_net_through_a_transistor():
    net = board(
        U1={"1": ("RAIL", "OUT", "power_out")},
        Q1={"2": ("EXT", "S", "passive"), "3": ("RAIL", "D", "passive")},
        J1={"1": "EXT"},
    )
    models = {"U1": supply(3.3), "Q1": ratings.Model(passes=[("2", "3", False)])}
    got = ratings.net_spans(net, models, {})
    assert "RAIL" not in got.stress
    assert "J1 pin 1" in got.why["RAIL"] and "Q1" in got.why["RAIL"]


def test_a_part_with_no_facts_is_a_source_at_every_pin_that_can_drive():
    """KiCad's pin type says which pins of an unknown part take and which can give. An input and a
    supply pin put nothing on their nets; any other pin may."""
    net = board(
        U9={"1": ("A", "IN", "input"), "2": ("B", "OUT", "output"), "3": ("V33", "VDD", "power_in")},
        C1={"1": "A", "2": "GND"},
        C2={"1": "B", "2": "GND"},
    )
    got = ratings.net_spans(net, {"C1": CAP, "C2": CAP}, RAILS)
    assert got.stress["V33"] == (0.0, 3.3)
    assert got.why["A"] == "nothing drives it"
    assert "U9 pin 2" in got.why["B"]


def test_a_pin_its_part_s_facts_do_not_name_is_a_source_too():
    net = board(U1=mcu(), U2={"1": ("SIG", "X", "passive")})
    got = ratings.net_spans(net, {"U1": MCU, "U2": ratings.Model(quiet=frozenset())}, RAILS)
    assert "SIG" not in got.stress and "U2 pin 1" in got.why["SIG"]


def test_a_net_forced_to_a_span_takes_no_other_source():
    """A pin whose limit is "VDD + 0.3 V" is judged with VDD at its least. The rail's regulator is
    left out for that: forced, the rail stands where it is put."""
    net = board(
        U1={"1": ("V33", "OUT", "power_out")}, R1={"1": "V33", "2": "SIG"}, C1={"1": "SIG", "2": "GND"}
    )
    models = {"U1": supply(3.3), "R1": resistor(10e3), "C1": CAP}
    got = ratings.net_spans(net, models, GND, forced={"V33": (3.0, 3.0)})
    assert got.held["V33"] == (3.0, 3.0)
    assert got.stress["V33"] == (0.0, 3.0)
    assert got.stress["SIG"] == (pytest.approx(0.0), pytest.approx(3.0))


def test_the_part_left_out_puts_nothing_on_its_nets_not_even_an_unknown():
    """A part's own pin is not what its pin is rated against, whatever the pin is."""
    net = board(U1=mcu(), U2={"1": ("SIG", "X", "passive")})
    seen = ratings.net_spans(net, {"U1": MCU, "U2": ratings.Model(quiet=frozenset())}, RAILS, without="U2")
    assert seen.stress["SIG"] == (0.0, 3.3)


# ---------------------------------------------------------------- the judgement
#
# A circuit is REF=(value, part number, pins). Facts are written as a library holds them and read back
# by the reader the command uses, so a test's facts are held to the same strictness as a project's.

READ = {"document": "DS-1", "revision": "rev A", "read": "2026-11-17", "second_reader": "2026-11-17"}
NASA = ratings.read_pack(PACKS / "nasa-eee-inst-002.json")
NASA_SOURCE = "EEE-INST-002 (NASA/TP-2003-212242)"
LINEAR = "section M4, table 4, page 10 of 10, the column Linear/Mixed Signal"  # a regulator's output


def circuit(**parts: tuple) -> tuple[ratings.Netlist, dict[str, str]]:
    """The netlist and each part's number, from REF=(value, part number, pins as for board())."""
    net = board(**{ref: pins for ref, (_, _, pins) in parts.items()})
    for ref, (value, _, _) in parts.items():
        net.parts[ref].value = value
    return net, {ref: number for ref, (_, number, _) in parts.items() if number}


def library(tmp_path: Path, *entries: dict) -> list[ratings.Facts]:
    (tmp_path / "facts.json").write_text(json.dumps({"parts": list(entries)}), encoding="utf-8")
    return ratings.read_facts(tmp_path)


def entry(kind: str, number: str, **keys) -> dict:
    return {"kind": kind, "mpn": number, "source": READ, **keys}


def project(nets: dict, **more) -> ratings.Project:
    return ratings.Project(
        "t",
        more.get("ambient"),
        nets,
        more.get("amps", {}),
        more.get("accepted", {}),
        more.get("volts", {}),
    )


def found(report: ratings.Report, status: str) -> list[str]:
    return [f.line for f in report.findings if f.status == status]


def ceramic(number: str, volts: float, **more) -> dict:
    return entry("capacitor.ceramic", number, tolerance=0.1, volts=volts, **more)


def chip_resistor(number: str = "R-0402", watts: float = 0.0625) -> dict:
    return entry("resistor", number, tolerance=0.01, watts=watts, volts=50)


def test_a_capacitor_past_its_derating_fails_with_the_pack_s_table(tmp_path):
    """12.6 V on a 16 V part is 0.79 of its rating. NASA's table allows a ceramic capacitor 0.60."""
    net, mpns = circuit(C1=("10u", "C-16V", {"1": "V12", "2": "GND"}))
    report = ratings.judge(
        net, mpns, library(tmp_path, ceramic("C-16V", 16)), project({"V12": (11.4, 12.6), **GND}), NASA
    )
    (line,) = found(report, "fail")
    assert line == (
        "fail C1 10u between V12 and GND: 12.6 V on 16 V rated is 0.79, the limit is 0.60 "
        f"[{NASA_SOURCE}, section C1, table 4, page 23 of 23]"
    )


def test_a_capacitor_inside_its_derating_holds(tmp_path):
    net, mpns = circuit(C1=("10u", "C-25V", {"1": "V12", "2": "GND"}))
    report = ratings.judge(
        net, mpns, library(tmp_path, ceramic("C-25V", 25)), project({"V12": (11.4, 12.6), **GND}), NASA
    )
    assert found(report, "fail") == [] and len(found(report, "hold")) == 1


def test_a_capacitor_on_a_net_with_no_span_is_not_judged_and_says_why(tmp_path):
    net, mpns = circuit(C1=("10u", "C-16V", {"1": "EXT", "2": "GND"}), J1=("Conn", "", {"1": "EXT"}))
    report = ratings.judge(net, mpns, library(tmp_path, ceramic("C-16V", 16)), project(GND), NASA)
    lines = found(report, "not judged")
    assert any(
        line.startswith("not judged C1 10u between EXT and GND: EXT has no span: J1 pin 1") for line in lines
    )
    assert found(report, "fail") == []


def test_a_part_with_no_facts_is_not_judged_and_is_named_with_its_part_number(tmp_path):
    net, mpns = circuit(C1=("10u", "C-16V", {"1": "V12", "2": "GND"}))
    report = ratings.judge(
        net, mpns, library(tmp_path, ceramic("OTHER", 16)), project({"V12": (0.0, 12.6), **GND}), NASA
    )
    assert found(report, "not judged") == ["not judged C1 10u: no facts for C-16V"]


def test_a_capacitor_whose_rating_nothing_states_is_1_line_and_holds_no_net_back(tmp_path):
    """A capacitor with no datasheet to be had is entered with its kind alone. The command then knows
    it passes no steady current: the tap of the divider beside it keeps its span, the 2 resistors are
    judged, and the capacitor's own voltage is the 1 thing not judged."""
    net, mpns = circuit(
        R1=("10k", "R-0402", {"1": "V5", "2": "TAP"}),
        R2=("10k", "R-0402", {"1": "TAP", "2": "GND"}),
        C1=("1n", "C-BARE", {"1": "TAP", "2": "GND"}),
    )
    facts = library(tmp_path, chip_resistor(), entry("capacitor.ceramic", "C-BARE"))
    report = ratings.judge(net, mpns, facts, project({"V5": (4.5, 5.5), **GND}), NASA)
    assert found(report, "not judged") == [
        "not judged C1 1n between TAP and GND: its facts hold no voltage rating"
    ]
    assert sorted(f.part for f in report.findings if f.status == "hold") == ["R1", "R1", "R2", "R2"]


def test_a_capacitor_with_a_voltage_and_no_tolerance_is_held_to_the_voltage(tmp_path):
    net, mpns = circuit(C1=("10u", "C-16V", {"1": "V12", "2": "GND"}))
    facts = library(tmp_path, entry("capacitor.ceramic", "C-16V", volts=16))
    report = ratings.judge(net, mpns, facts, project({"V12": (11.4, 12.6), **GND}), NASA)
    (line,) = found(report, "fail")
    assert line.startswith("fail C1 10u between V12 and GND: 12.6 V on 16 V rated is 0.79")


def test_a_stress_the_pack_has_no_rule_for_is_held_to_the_part_s_own_rating(tmp_path):
    """An electrolytic capacitor is in neither table read so far. 12.6 V on 16 V holds at 1.0, and the
    line says whose limit that is."""
    net, mpns = circuit(C1=("100u", "C-EL", {"1": "V12", "2": "GND"}))
    facts = library(tmp_path, entry("capacitor.electrolytic", "C-EL", tolerance=0.2, volts=16))
    report = ratings.judge(net, mpns, facts, project({"V12": (11.4, 12.6), **GND}), NASA)
    (line,) = found(report, "hold")
    assert line.endswith("the limit is 1.00 [DS-1, rev A: the part's own rating]")


def test_a_resistor_that_burns_more_than_its_derated_power_fails(tmp_path):
    """5.5 V across 100 ohm less 1 % is 306 mW in a 62.5 mW part."""
    net, mpns = circuit(R1=("100", "R-0402", {"1": "V5", "2": "GND"}))
    report = ratings.judge(
        net, mpns, library(tmp_path, chip_resistor()), project({"V5": (4.5, 5.5), **GND}), NASA
    )
    (line,) = found(report, "fail")
    assert line.startswith(
        "fail R1 100 between V5 and GND, with 5.5 V across it: 306 mW on 62.5 mW rated is 4.89"
    )
    assert "the limit is 0.50" in line and "section R2, table 4, page 24 of 24, the row Others" in line


def test_a_pull_down_of_10k_holds_its_power_and_its_voltage(tmp_path):
    net, mpns = circuit(R1=("10k", "R-0402", {"1": "V5", "2": "GND"}))
    report = ratings.judge(
        net, mpns, library(tmp_path, chip_resistor()), project({"V5": (4.5, 5.5), **GND}), NASA
    )
    assert found(report, "fail") == []
    assert sorted(f.rule for f in report.findings) == ["resistor.power", "resistor.voltage"]


def test_a_series_resistor_into_an_input_carries_no_steady_current(tmp_path):
    """33 ohm between an output and a gate: 3.3 V can stand across it, and no current flows for long.
    Judged by the voltage alone it would burn 330 mW."""
    net, mpns = circuit(
        U1=("MCU", "MCU-1", mcu("DRIVE")),
        R1=("33", "R-0402", {"1": "DRIVE", "2": "GATE"}),
        Q1=(
            "FET",
            "FET-1",
            {"1": ("GATE", "G", "input"), "2": ("GND", "S", "passive"), "3": ("V33", "D", "passive")},
        ),
    )
    fet = entry(
        "transistor.mosfet",
        "FET-1",
        transistors=[{"gate": "1", "drain": "3", "source": "2"}],
        volts_drain_source=20,
        volts_gate_source=12,
    )
    report = ratings.judge(
        net, mpns, library(tmp_path, chip_resistor(), fet, MCU_FACTS), project(RAILS), NASA
    )
    power = [f for f in report.findings if f.rule == "resistor.power"]
    assert [f.status for f in power] == ["hold"]
    assert "no steady current: one end meets no source" in power[0].text


def test_a_sense_resistor_is_judged_with_the_current_the_project_states(tmp_path):
    """20 mohm between 2 nets of 4.2 V: the nets say 882 W. With the 3 A the project states, 0.18 W."""
    net, mpns = circuit(R1=("20m", "R-SENSE", {"1": "VBAT", "2": "LOAD"}), J1=("Conn", "", {"1": "LOAD"}))
    nets = {"VBAT": (3.0, 4.2), "LOAD": (0.0, 4.2)}
    for watts, status in ((1.0, "hold"), (0.25, "fail")):
        facts = library(tmp_path, chip_resistor("R-SENSE", watts))
        report = ratings.judge(net, mpns, facts, project(nets, amps={"R1": 3.0}), NASA)
        (line,) = [f.line for f in report.findings if f.rule == "resistor.power"]
        assert line.startswith(
            f"{status} R1 20m between VBAT and LOAD, with the 3 A the project states: 182 mW"
        )


def test_a_sense_resistor_s_voltage_is_the_stated_current_times_its_resistance(tmp_path):
    """The 2 nets of a 20 mohm shunt can stand 4.2 V apart, and the shunt never sees that: a load takes
    the rest. 3 A through 20.2 mohm (1 % over) is 60.6 mV: 0.61 of a 100 mV part, 0.87 of a 70 mV one,
    and NASA allows 0.80."""
    net, mpns = circuit(R1=("20m", "R-SENSE", {"1": "VBAT", "2": "LOAD"}), J1=("Conn", "", {"1": "LOAD"}))
    nets = {"VBAT": (3.0, 4.2), "LOAD": (0.0, 4.2)}
    for volts, rated, status, share in ((0.1, "100 mV", "hold", "0.61"), (0.07, "70 mV", "fail", "0.87")):
        facts = library(tmp_path, entry("resistor", "R-SENSE", tolerance=0.01, watts=1.0, volts=volts))
        report = ratings.judge(net, mpns, facts, project(nets, amps={"R1": 3.0}), NASA)
        (line,) = [f.line for f in report.findings if f.rule == "resistor.voltage"]
        assert line.startswith(
            f"{status} R1 20m between VBAT and LOAD, with the 3 A the project states: 60.6 mV on "
            f"{rated} rated is {share}, the limit is 0.80"
        )


def test_a_stated_current_judges_a_resistor_whose_far_net_nothing_states(tmp_path):
    """A connector's pin stands on the load's net and nothing states it: the net has no span. The
    current the project states is enough for the resistor's own 2 stresses."""
    net, mpns = circuit(R1=("20m", "R-SENSE", {"1": "VBAT", "2": "LOAD"}), J1=("Conn", "", {"1": "LOAD"}))
    facts = library(tmp_path, entry("resistor", "R-SENSE", tolerance=0.01, watts=1.0, volts=0.1))
    report = ratings.judge(net, mpns, facts, project({"VBAT": (3.0, 4.2)}, amps={"R1": 3.0}), NASA)
    assert sorted((f.rule, f.status) for f in report.findings if f.part == "R1") == [
        ("resistor.power", "hold"),
        ("resistor.voltage", "hold"),
    ]


def test_a_mosfet_is_held_to_its_drain_and_to_its_gate_rating(tmp_path):
    """12.6 V on a 20 V drain is 0.63, under NASA's 0.75. The same 12.6 V on an 8 V gate is over."""
    net, mpns = circuit(
        Q1=(
            "FET",
            "FET-1",
            {"1": ("V12", "G", "input"), "2": ("GND", "S", "passive"), "3": ("V12", "D", "passive")},
        )
    )
    fet = entry(
        "transistor.mosfet",
        "FET-1",
        transistors=[{"gate": "1", "drain": "3", "source": "2"}],
        volts_drain_source=20,
        volts_gate_source=8,
    )
    report = ratings.judge(net, mpns, library(tmp_path, fet), project({"V12": (11.4, 12.6), **GND}), NASA)
    assert {f.rule: f.status for f in report.findings} == {
        "mosfet.drain_source": "hold",
        "mosfet.gate_source": "fail",
    }
    (line,) = found(report, "fail")
    assert "gate V12 to source GND: 12.6 V on 8 V rated" in line and "the limit is 0.60" in line


def test_a_diode_is_held_to_its_reverse_voltage(tmp_path):
    net, mpns = circuit(D1=("SS14", "D-1", {"1": ("VBUS", "A", "passive"), "2": ("V12", "K", "passive")}))
    nets = {"VBUS": (4.4, 5.5), "V12": (11.4, 12.6)}
    for volts, status in ((30, "hold"), (15, "fail")):
        diode = entry("diode.rectifier", "D-1", diodes=[{"anode": "1", "cathode": "2"}], volts_reverse=volts)
        report = ratings.judge(net, mpns, library(tmp_path, diode), project(nets), NASA)
        (line,) = [f.line for f in report.findings]
        assert line.startswith(f"{status} D1 SS14 from VBUS to V12: 12.6 V on {volts} V rated")
        assert "the limit is 0.70" in line


def test_a_clamp_that_conducts_at_the_rail_s_own_voltage_fails(tmp_path):
    """A 5 V clamp on a bus that may stand at 5.5 V conducts in normal use."""
    net, mpns = circuit(D1=("TVS", "TVS-1", {"1": ("GND", "A", "passive"), "2": ("VBUS", "K", "passive")}))
    for volts, status in ((5.5, "hold"), (5.0, "fail")):
        clamp = entry("diode.clamp", "TVS-1", diodes=[{"anode": "1", "cathode": "2"}], volts_standoff=volts)
        report = ratings.judge(
            net, mpns, library(tmp_path, clamp), project({"VBUS": (4.4, 5.5), **GND}), NASA
        )
        (line,) = [f.line for f in report.findings]
        assert line.startswith(
            f"{status} D1 TVS from GND to VBUS: 5.5 V can stand across it, and it stands off {volts:g} V"
        )


POWER_FET = {
    "1": ("GATE", "G", "input"),
    "2": ("GND", "S", "passive"),
    "3": ("GND", "S", "passive"),
    "4": ("LOAD", "D", "passive"),
    "5": ("LOAD", "D", "passive"),
}


def power_fet(**more) -> dict:
    """A transistor with 2 source pins and 2 drain pins, as a power package has them."""
    ends = {"gate": "1", "drain": ["4", "5"], "source": ["2", "3"]}
    return entry(
        "transistor.mosfet", "FET-2", transistors=[ends], volts_drain_source=30, volts_gate_source=12, **more
    )


def test_a_transistor_with_2_pins_for_an_end_names_them_all(tmp_path):
    """The second source pin and the second drain pin are no sources nothing describes."""
    net, mpns = circuit(Q1=("FET", "FET-2", POWER_FET))
    nets = {"LOAD": (0.0, 12.6), "GATE": (0.0, 3.6), **GND}
    report = ratings.judge(net, mpns, library(tmp_path, power_fet()), project(nets), NASA)
    assert found(report, "not judged") == []
    assert [f.line.split(" [")[0] for f in report.findings] == [
        "hold Q1 FET drain LOAD to source GND: 12.6 V on 30 V rated is 0.42, the limit is 0.75",
        "hold Q1 FET gate GATE to source GND: 3.6 V on 12 V rated is 0.30, the limit is 0.60",
    ]


def test_a_transistor_s_current_is_held_to_the_drain_current_at_the_ambient(tmp_path):
    """4 A through a part rated 4 A at 25 C and 3.2 A at 70 C: 1.00 with no ambient stated, 1.25 at
    70 C, and at 47.5 C, half-way, 4 / 3.6 = 1.11. NASA allows 0.75. Past 70 C the data ends."""
    net, mpns = circuit(Q1=("FET", "FET-2", POWER_FET))
    nets = {"LOAD": (0.0, 12.6), "GATE": (0.0, 3.3), **GND}
    facts = library(tmp_path, power_fet(amps_drain=[[25, 4.0], [70, 3.2]]))
    where = f"[{NASA_SOURCE}, section S1, table 4, page 13 of 13]"
    for ambient, rated, share in ((None, "4 A", "1.00"), (70, "3.2 A", "1.25"), (47.5, "3.6 A", "1.11")):
        report = ratings.judge(net, mpns, facts, project(nets, amps={"Q1": 4.0}, ambient=ambient), NASA)
        assert found(report, "fail") == [
            f"fail Q1 FET drain current, with the 4 A the project states: 4 A on {rated} rated is {share}, "
            f"the limit is 0.75 {where}"
        ]
    assert "Q1: its drain current is rated as at 25 C, since the project states no ambient" in (
        ratings.judge(net, mpns, facts, project(nets, amps={"Q1": 4.0}), NASA).notes
    )
    hot = ratings.judge(net, mpns, facts, project(nets, amps={"Q1": 4.0}, ambient=85), NASA)
    assert found(hot, "not judged") == [
        "not judged Q1 FET drain current: its rating is stated up to 70 C, and the ambient is 85 C"
    ]
    one = library(tmp_path, power_fet(amps_drain=6.0))
    report = ratings.judge(net, mpns, one, project(nets, amps={"Q1": 4.0}), NASA)
    assert any("4 A on 6 A rated is 0.67, the limit is 0.75" in line for line in found(report, "hold"))
    unstated = ratings.judge(net, mpns, one, project(nets), NASA)
    assert not any("drain current" in f.text for f in unstated.findings)


def test_a_diode_s_current_is_held_to_its_forward_current(tmp_path):
    """600 mA through a 1 A diode is 0.60, and NASA allows 0.50."""
    net, mpns = circuit(D1=("SS14", "D-1", {"1": ("VBUS", "A", "passive"), "2": ("V12", "K", "passive")}))
    nets = {"VBUS": (4.4, 5.5), "V12": (11.4, 12.6)}
    diode = entry(
        "diode.rectifier", "D-1", diodes=[{"anode": "1", "cathode": "2"}], volts_reverse=30, amps_forward=1.0
    )
    report = ratings.judge(net, mpns, library(tmp_path, diode), project(nets, amps={"D1": 0.6}), NASA)
    assert found(report, "fail") == [
        "fail D1 SS14 forward current, with the 600 mA the project states: 600 mA on 1 A rated is 0.60, "
        f"the limit is 0.50 [{NASA_SOURCE}, section S1, table 4, page 12 of 13]"
    ]


def pin(name: str, numbers: list[str], role: str, **keys) -> dict:
    return {
        "name": name,
        "numbers": numbers,
        "role": role,
        **({} if role in ("ground", "nc") else {"page": 4}),
        **keys,
    }


FOLLOWS_VDD = [-0.3, {"pin": "VDD", "plus": 0.3}]
MCU_FACTS = entry(
    "ic",
    "MCU-1",
    family="digital",
    pins=[
        pin("VDD", ["1"], "supply", abs=[-0.3, 4.0], operating=[1.7, 3.6], amps=0.05),
        pin("VSS", ["2"], "ground"),
        pin("PA0", ["3"], "io", abs=FOLLOWS_VDD, swing=["VSS", "VDD"]),
    ],
)


def test_a_part_whose_ground_pin_stands_on_a_negative_rail_is_judged_from_that_pin(tmp_path):
    """A datasheet's limits are against the part's ground pin. VDD at 3.4 V with VSS on a rail at
    -5.2 V is 8.6 V on a part that takes 4.0 V: the limit is -5.2 + 4.0 = -1.2 V from the board's 0 V.
    Its supply stands 8.0 to 8.6 V above VSS, and works from 1.7 to 3.6 V."""
    pins = {"1": ("V33", "VDD", "power_in"), "2": ("VNEG", "VSS", "power_in"), "3": ("SIG", "PA0", "input")}
    net, mpns = circuit(U1=("MCU", "MCU-1", pins))
    nets = {"V33": (3.2, 3.4), "VNEG": (-5.2, -4.8), **GND}
    net.nets["GND"] = []
    report = ratings.judge(net, mpns, library(tmp_path, MCU_FACTS), project(nets), NASA)
    fails = found(report, "fail")
    assert (
        "fail U1 pin 1 (VDD) on V33: 3.4 V can stand on it, its limit is -1.2 V "
        "(pin VSS at -5.2 V, +4 V) [DS-1, rev A, p 4]"
    ) in fails
    assert (
        "fail U1 pin 1 (VDD) on V33: its sources hold it 8 to 8.6 V above pin VSS on VNEG, "
        "the pin works from 1.7 to 3.6 V [DS-1, rev A, p 4]"
    ) in fails


def test_a_pull_up_to_a_higher_rail_lifts_a_net_the_project_states(tmp_path):
    """SDA comes in on a connector and is stated at 0 to 3.3 V. With the cable out, or its driver
    released, the 4k7 to the 5 V rail puts 5.5 V on a pin that takes 4.6 V."""
    chip = entry(
        "ic",
        "BUF-1",
        family="digital",
        pins=[
            pin("VCC", ["1"], "supply", abs=[-0.5, 6.5], amps=0.001),
            pin("GND", ["2"], "ground"),
            pin("A", ["3"], "input", abs=[-0.5, 4.6]),
        ],
    )
    pins = {"1": ("V33", "VCC", "power_in"), "2": ("GND", "GND", "power_in"), "3": ("SDA", "A", "input")}
    net, mpns = circuit(
        U1=("BUF", "BUF-1", pins),
        R1=("4k7", "R-0402", {"1": "V5", "2": "SDA"}),
        J1=("IN", "HDR-1", {"1": "SDA", "2": "GND"}),
    )
    source = entry("connector", "HDR-1", pins=[{"numbers": ["1"], "outside": "source"}])
    nets = {"V5": (4.5, 5.5), "SDA": (0.0, 3.3), **RAILS}
    report = ratings.judge(net, mpns, library(tmp_path, chip, chip_resistor(), source), project(nets), NASA)
    assert any(
        line.startswith("fail U1 pin 3 (A) on SDA: 5.5 V can stand on it, its limit is 4.6 V")
        for line in found(report, "fail")
    ), [f.line for f in report.findings]


def test_an_output_swings_between_its_2_pins_whichever_is_named_first(tmp_path):
    """`swing` written [supply, ground]: the output still reaches its supply's 5.5 V, and the 4.6 V
    input beside it fails. Read in the order written, it drove 0 V to 0 V."""
    for swing in (["GND", "VCC"], ["VCC", "GND"]):
        driver = entry(
            "ic",
            "DRV-1",
            family="digital",
            pins=[
                pin("VCC", ["1"], "supply", abs=[-0.5, 6.5], amps=0.001),
                pin("GND", ["2"], "ground"),
                pin("Y", ["3"], "output", abs=[-0.5, 6.5], swing=swing),
            ],
        )
        taker = entry(
            "ic",
            "BUF-1",
            family="digital",
            pins=[
                pin("VCC", ["1"], "supply", abs=[-0.5, 6.5], amps=0.001),
                pin("GND", ["2"], "ground"),
                pin("A", ["3"], "input", abs=[-0.5, 4.6]),
            ],
        )
        net, mpns = circuit(
            U1=(
                "DRV",
                "DRV-1",
                {"1": ("V5", "VCC", "power_in"), "2": ("GND", "GND", "power_in"), "3": "SIG"},
            ),
            U2=(
                "BUF",
                "BUF-1",
                {"1": ("V33", "VCC", "power_in"), "2": ("GND", "GND", "power_in"), "3": "SIG"},
            ),
        )
        nets = {"V5": (4.5, 5.5), **RAILS}
        report = ratings.judge(net, mpns, library(tmp_path, driver, taker), project(nets), NASA)
        assert any(
            line.startswith("fail U2 pin 3 (A) on SIG: 5.5 V can stand on it, its limit is 4.6 V")
            for line in found(report, "fail")
        ), (swing, [f.line for f in report.findings])


def test_a_limit_that_is_certainly_passed_is_not_hidden_by_one_that_cannot_be_judged(tmp_path):
    """A pin takes VCC + 0.5 V and 4.6 V, whichever is less. Its VCC stands on a net no source holds,
    so the first limit cannot be judged. The pull-up to 12 V passes the second whatever VCC is: the
    pin fails on 4.6 V, the first limit is listed as not judged, and its least limit is judged too."""
    chip = entry(
        "ic",
        "OD-1",
        family="digital",
        pins=[
            pin("VCC", ["1"], "supply", abs=[-0.5, 6.5], amps=0.001),
            pin("GND", ["2"], "ground"),
            pin("Y", ["3"], "open_drain", abs=[-0.5, [{"pin": "VCC", "plus": 0.5}, 4.6]], swing=["GND"]),
        ],
    )
    pins = {
        "1": ("VSW", "VCC", "power_in"),
        "2": ("GND", "GND", "power_in"),
        "3": ("OD", "Y", "open_collector"),
    }
    net, mpns = circuit(
        U1=("OD", "OD-1", pins),
        R1=("10k", "R-0402", {"1": "V12", "2": "OD"}),
        J1=("SW", "", {"1": "VSW"}),
    )
    report = ratings.judge(net, mpns, library(tmp_path, chip, chip_resistor()), project(V12), NASA)
    lines = [f.line for f in report.findings if f.part in ("U1", "U1.3")]
    assert "fail U1 pin 3 (Y) on OD: 12.6 V can stand on it, its limit is 4.6 V [DS-1, rev A, p 4]" in lines
    assert "hold U1 pin 3 (Y) on OD: 0 V can stand on it, its limit is -0.5 V [DS-1, rev A, p 4]" in lines
    assert (
        lines.count("not judged U1 pin 3 (Y) on OD: its limit follows pin VCC on VSW, which no source holds")
        == 1
    )


def test_a_diode_drawn_forward_between_2_sources_fails(tmp_path):
    """A clamp drawn backwards: its anode on the 5 V rail and its cathode on ground. The rail holds
    its anode at 4.5 V or more above its cathode, and it carries all the rail gives."""
    net, mpns = circuit(D1=("TVS", "TVS-1", {"1": "V5", "2": "GND"}))
    clamp = entry("diode.clamp", "TVS-1", diodes=[{"anode": "1", "cathode": "2"}], volts_standoff=5.5)
    report = ratings.judge(net, mpns, library(tmp_path, clamp), project(V5), NASA)
    assert (
        "fail D1 TVS from V5 to GND: its anode is held at 4.5 V or more and its cathode at 0 V or less: "
        "it stands forward between 2 sources [DS-1, rev A: the part's own rating]"
    ) in found(report, "fail")


def test_a_5_volt_pull_up_on_a_3_volt_pin_fails_with_the_datasheet_s_page(tmp_path):
    net, mpns = circuit(U1=("MCU", "MCU-1", mcu()), R1=("4.7k", "R-0402", {"1": "V5", "2": "SIG"}))
    facts = library(tmp_path, MCU_FACTS, chip_resistor())
    report = ratings.judge(net, mpns, facts, project({"V5": (4.5, 5.5), **RAILS}), NASA)
    (line,) = found(report, "fail")
    assert line == (
        "fail U1 pin 3 (PA0) on SIG: 5.5 V can stand on it, its limit is 3.3 V "
        "(pin VDD at 3 V, +0.3 V) [DS-1, rev A, p 4]"
    )


def test_a_pull_up_to_the_pin_s_own_rail_holds_at_the_rail_s_least(tmp_path):
    """The limit is VDD + 0.3 V and the pull-up follows VDD. Judged with the rail at 3.3 V against a
    limit taken at 3.0 V, a correct circuit would fail."""
    net, mpns = circuit(U1=("MCU", "MCU-1", mcu()), R1=("4.7k", "R-0402", {"1": "V33", "2": "SIG"}))
    report = ratings.judge(net, mpns, library(tmp_path, MCU_FACTS, chip_resistor()), project(RAILS), NASA)
    assert found(report, "fail") == []
    lines = [f.line for f in report.findings if f.part == "U1.3"]
    assert lines == [
        "hold U1 pin 3 (PA0) on SIG: 0 to 3 V can stand on it, its limits are -0.3 V and 3.3 V "
        "(pin VDD at 3 V, +0.3 V) [DS-1, rev A, p 4]"
    ]


def test_a_divider_from_5_volts_into_a_3_volt_pin_holds(tmp_path):
    net, mpns = circuit(
        U1=("MCU", "MCU-1", mcu()),
        R1=("10k", "R-0402", {"1": "V5", "2": "SIG"}),
        R2=("10k", "R-0402", {"1": "SIG", "2": "GND"}),
    )
    facts = library(tmp_path, MCU_FACTS, chip_resistor())
    report = ratings.judge(net, mpns, facts, project({"V5": (4.5, 5.5), **RAILS}), NASA)
    assert found(report, "fail") == []
    # 5.5 V on 10k less 1 % over 10k plus 1 %: 5.5 x 10.1 / 20 = 2.7775
    assert any("2.78 V can stand on it" in f.text for f in report.findings if f.part == "U1.3")


def test_a_supply_pin_above_its_absolute_limit_fails(tmp_path):
    net, mpns = circuit(U1=("MCU", "MCU-1", mcu()), C1=("100n", "C-16V", {"1": "V33", "2": "GND"}))
    facts = library(tmp_path, MCU_FACTS, ceramic("C-16V", 16))
    report = ratings.judge(net, mpns, facts, project({"V33": (4.5, 5.5), **GND}), NASA)
    lines = found(report, "fail")
    assert "fail U1 pin 1 (VDD) on V33: 5.5 V can stand on it, its limit is 4 V [DS-1, rev A, p 4]" in lines
    assert any(
        "its sources hold it at 4.5 to 5.5 V, the pin works from 1.7 to 3.6 V" in line for line in lines
    )


def test_a_supply_held_under_the_pin_s_working_range_fails(tmp_path):
    net, mpns = circuit(U1=("MCU", "MCU-1", mcu()))
    report = ratings.judge(net, mpns, library(tmp_path, MCU_FACTS), project({"V33": (1.5, 1.9), **GND}), NASA)
    (line,) = found(report, "fail")
    assert line.startswith(
        "fail U1 pin 1 (VDD) on V33: its sources hold it at 1.5 to 1.9 V, the pin works from 1.7 to 3.6 V"
    )


def test_a_signal_pin_is_held_to_the_range_its_datasheet_recommends(tmp_path):
    """An input takes 4.6 V at the most and works from 0 to 3.6 V. 4 V on it breaks no limit, and is
    outside the range the datasheet recommends; 3.3 V is inside both."""
    net, mpns = circuit(U1=("MCU", "MCU-1", mcu()))
    wide = pin("PA0", ["3"], "input", abs=[-0.5, 4.6], operating=[0, 3.6])
    chip = {**MCU_FACTS, "pins": [*MCU_FACTS["pins"][:2], wide]}
    facts = library(tmp_path, chip)
    report = ratings.judge(net, mpns, facts, project({"SIG": (0.0, 4.0), **RAILS}), NASA)
    assert found(report, "fail") == [
        "fail U1 pin 3 (PA0) on SIG: 0 to 4 V can stand on it, the pin works from 0 V to 3.6 V "
        "[DS-1, rev A, p 4]"
    ]
    assert (
        "hold U1 pin 3 (PA0) on SIG: 0 to 4 V can stand on it, its limits are -0.5 V and 4.6 V "
        "[DS-1, rev A, p 4]" in found(report, "hold")
    )
    report = ratings.judge(net, mpns, facts, project({"SIG": (0.0, 3.3), **RAILS}), NASA)
    assert found(report, "fail") == []
    assert (
        "hold U1 pin 3 (PA0) on SIG: 0 to 3.3 V can stand on it, the pin works from 0 V to 3.6 V "
        "[DS-1, rev A, p 4]" in found(report, "hold")
    )


def regulator(amps: float = 0.2, needs: list | None = None) -> dict:
    return entry(
        "ic",
        "LDO-1",
        family="regulator.linear",
        pins=[
            pin("IN", ["1"], "supply", abs=[-0.3, 6.5], operating=[2.5, 6.0], amps=0.0001),
            pin("GND", ["2"], "ground"),
            pin(
                "OUT",
                ["3"],
                "regulated",
                abs=[-0.3, [{"pin": "IN", "plus": 0.3}, 5.5]],
                volts=[3.2, 3.4],
                amps=amps,
            ),
        ],
        needs=needs or [],
    )


LDO = {"1": ("V5", "IN", "power_in"), "2": ("GND", "GND", "power_in"), "3": ("V33", "OUT", "power_out")}
V5 = {"V5": (4.5, 5.5), **GND}


def load(number: str, amps: float | None) -> dict:
    supply_pin = pin("VDD", ["1"], "supply", abs=[-0.3, 4.0], **({} if amps is None else {"amps": amps}))
    return entry("ic", number, family="digital", pins=[supply_pin, pin("VSS", ["2"], "ground")])


TWO_PINS = {"1": ("V33", "VDD", "power_in"), "2": ("GND", "VSS", "power_in")}


def test_a_rail_loaded_past_its_regulator_fails(tmp_path):
    """150 mA and 100 mA on a 200 mA regulator is 1.25 of what it gives. NASA allows a plastic linear
    part 0.70."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), U2=("A", "LOAD-A", TWO_PINS), U3=("B", "LOAD-B", TWO_PINS))
    facts = library(tmp_path, regulator(), load("LOAD-A", 0.15), load("LOAD-B", 0.1))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    (line,) = found(report, "fail")
    assert line == (
        "fail V33: U1 pin 3 (OUT) gives 200 mA, its loads take 250 mA: 1.25, the limit is 0.70 "
        f"[{NASA_SOURCE}, {LINEAR}]"
    )


def test_a_load_that_is_over_the_limit_before_the_last_pin_is_known_fails(tmp_path):
    """250 mA of 1 load on a 200 mA regulator is 1.25 already. A second pin whose facts state no
    current can only add to it: the rail fails, and is not left as not judged."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), U2=("A", "LOAD-A", TWO_PINS), U3=("B", "LOAD-B", TWO_PINS))
    facts = library(tmp_path, regulator(), load("LOAD-A", 0.25), load("LOAD-B", None))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert found(report, "fail") == [
        "fail V33: U1 pin 3 (OUT) gives 200 mA, its loads take at least 250 mA: 1.25, the limit is 0.70 "
        f"[{NASA_SOURCE}, {LINEAR}]"
    ]
    assert not any(f.rule == "rail.load" for f in report.findings if f.status == "not judged")


def test_a_load_under_the_limit_with_a_pin_unknown_stays_not_judged(tmp_path):
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), U2=("A", "LOAD-A", TWO_PINS), U3=("B", "LOAD-B", TWO_PINS))
    facts = library(tmp_path, regulator(), load("LOAD-A", 0.05), load("LOAD-B", None))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert found(report, "fail") == []
    assert found(report, "not judged") == [
        "not judged V33: U1 pin 3 (OUT) feeds a load nothing states: "
        "U3 pin 1 (VDD) has no `amps` in its facts"
    ]


def test_a_load_the_project_states_for_a_part_with_no_facts_is_counted(tmp_path):
    """ratings.json states 190 mA for J1 pin 1. J1 has no facts, and the 190 mA is on the rail all the
    same: 0.95 of the 200 mA the regulator gives."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), J1=("OUT", "", {"1": "V33", "2": "GND"}))
    report = ratings.judge(net, mpns, library(tmp_path, regulator()), project(V5, amps={"J1.1": 0.19}), NASA)
    assert any(
        "U1 pin 3 (OUT) gives 200 mA, its loads take 190 mA: 0.95, the limit is 0.70" in line
        for line in found(report, "fail")
    )


def test_a_rail_s_load_through_a_resistor_is_the_current_the_resistor_is_judged_with(tmp_path):
    """A 20 mohm shunt from the rail to a load the project states at 100 mA, and a 330 ohm filter in
    front of a pin that takes 5.5 uA: the rail gives 100.0055 mA, 0.50 of 200 mA. Taken from the
    extremes of their 2 nets, the 2 resistors alone would take 172 A and 10 mA."""
    net, mpns = circuit(
        U1=("LDO", "LDO-1", LDO),
        R1=("20m", "R-0402", {"1": "V33", "2": "LOAD"}),
        J1=("OUT", "HDR-1", {"1": "LOAD", "2": "GND"}),
        R2=("330", "R-0402", {"1": "V33", "2": "VDD"}),
        U2=("A", "LOAD-A", FILTERED),
    )
    facts = library(
        tmp_path, regulator(), chip_resistor(), entry("connector", "HDR-1"), load("LOAD-A", 5.5e-6)
    )
    stated = project(V5, amps={"R1": 0.1, "J1.1": 0.1})
    report = ratings.judge(net, mpns, facts, stated, NASA)
    assert any(
        "U1 pin 3 (OUT) gives 200 mA, its loads take 100 mA: 0.50, the limit is 0.70" in f.text
        for f in report.findings
        if f.status == "hold"
    ), [f.line for f in report.findings]


def test_a_regulator_on_a_net_another_source_holds_is_not_held_to_the_rail_s_load(tmp_path):
    """A charger's output stands on the cell's net, which ratings.json states: the cell feeds the loads
    there too, and nothing says how the 2 share them. The report notes it and judges no load."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), U2=("A", "LOAD-A", TWO_PINS))
    facts = library(tmp_path, regulator(), load("LOAD-A", 0.5))
    nets = {**V5, "V33": (2.8, 4.2)}
    report = ratings.judge(net, mpns, facts, project(nets), NASA)
    assert not any(f.rule.startswith(("rail.load", "output.current")) for f in report.findings)
    assert (
        "V33: U1 pin 3 (OUT) stands on a net ratings.json states, V33: another source feeds its loads "
        "too, and its load is not judged"
    ) in report.notes


def test_a_clamp_from_ground_to_a_rail_takes_no_load_out_of_the_sum(tmp_path):
    """10 ohm from the 3.3 V rail to ground takes 3.4 V / 9.9 ohm = 343 mA from a 200 mA regulator. A
    TVS from ground to the rail is reverse biased: it carries nothing, and it does not make ground a
    part of the rail, which would take every resistor to ground out of the sum."""
    net, mpns = circuit(
        U1=("LDO", "LDO-1", LDO),
        R1=("10", "R-0402", {"1": "V33", "2": "GND"}),
        D1=("TVS", "TVS-1", {"1": "GND", "2": "V33"}),
    )
    clamp = entry("diode.clamp", "TVS-1", diodes=[{"anode": "1", "cathode": "2"}], volts_standoff=5.0)
    facts = library(
        tmp_path, regulator(), entry("resistor", "R-0402", tolerance=0.01, watts=2.0, volts=50), clamp
    )
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert any(
        "U1 pin 3 (OUT) gives 200 mA, its loads take 343 mA: 1.72, the limit is 0.70" in line
        for line in found(report, "fail")
    ), [f.line for f in report.findings]


def test_a_resistor_with_no_number_on_a_rail_makes_its_load_unknown(tmp_path):
    """A thermistor valued `NTC` from the rail to ground may conduct, and nothing says how much: it is
    no wire that joins ground to the rail, and the rail's load is not known."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), R2=("NTC", "R-0402", {"1": "V33", "2": "GND"}))
    report = ratings.judge(net, mpns, library(tmp_path, regulator(), chip_resistor()), project(V5), NASA)
    assert (
        "not judged V33: U1 pin 3 (OUT) feeds a load nothing states: "
        "R2 has no number for its Value, and may take a current"
    ) in found(report, "not judged")


def test_a_part_with_no_facts_on_a_rail_makes_its_load_unknown(tmp_path):
    """A passive pin of a part nothing describes may take a current: the load is not 0 A."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), M1=("MOTOR", "", {"1": "V33", "2": "GND"}))
    report = ratings.judge(net, mpns, library(tmp_path, regulator()), project(V5), NASA)
    assert not any("its loads take 0 A" in f.text for f in report.findings)
    assert any(
        line.startswith("not judged V33: U1 pin 3 (OUT) feeds a load nothing states: M1 pin 1 stands on")
        for line in found(report, "not judged")
    )


def test_a_reference_output_its_datasheet_rates_nowhere_is_noted_and_never_guessed(tmp_path):
    """A comparator's reference output: the datasheet gives its voltage and no limit for the pin. The
    entry leaves `abs` out. The net still stands at the reference, the resistor on it is judged with
    1.26 V across it, and a note says that nothing holds the reference pin to a limit."""
    chip = entry(
        "ic",
        "CMP-1",
        family="linear",
        pins=[
            pin("V+", ["1"], "supply", abs=[-0.5, 7.0], amps=0.000005),
            pin("V-", ["2"], "ground"),
            pin("REF", ["3"], "regulated", volts=[1.223, 1.26], amps=0.0005),
            pin("IN+", ["4"], "input", abs=[-0.5, 7.0]),
        ],
    )
    pins = {
        "1": ("V33", "V+", "power_in"),
        "2": ("GND", "V-", "power_in"),
        "3": ("VREF", "REF", "output"),
        "4": ("VREF", "IN+", "input"),
    }
    net, mpns = circuit(U1=("CMP", "CMP-1", pins), R1=("100k", "R-0402", {"1": "VREF", "2": "GND"}))
    facts = library(tmp_path, chip, chip_resistor())
    report = ratings.judge(net, mpns, facts, project({"V33": (3.0, 3.3), **GND}), NASA)
    assert "U1 pin 3 (REF): its facts hold no limits, and no voltage on VREF is held to one" in report.notes
    assert not any(f.part == "U1.3" for f in report.findings)
    assert any(
        line.startswith("hold R1 100k between VREF and GND: 1.26 V on 50 V rated is 0.03")
        for line in found(report, "hold")
    )
    assert found(report, "not judged") == []


def test_a_rail_inside_its_regulator_holds(tmp_path):
    """50 mA and 80 mA on a 200 mA regulator is 0.65."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), U2=("A", "LOAD-A", TWO_PINS), U3=("B", "LOAD-B", TWO_PINS))
    facts = library(tmp_path, regulator(), load("LOAD-A", 0.05), load("LOAD-B", 0.08))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert found(report, "fail") == []
    assert any("its loads take 130 mA: 0.65, the limit is 0.70" in f.text for f in report.findings)


def monitor(iout: str, minus: str) -> dict:
    """A current monitor of 3 pins, with its output and its sense input on the 2 numbers given."""
    return entry(
        "ic",
        "MON-1",
        family="linear",
        pins=[
            pin("VSENSE+", ["2"], "supply", abs=[-0.6, 20], amps=0.00002),
            pin("VSENSE-", [minus], "input", abs=[-0.6, 20]),
            pin("IOUT", [iout], "open_drain", abs=[-0.6, 20], swing=["VSENSE+"]),
        ],
    )


MONITOR = {"1": ("LOAD", "Vs-", "input"), "2": ("VBAT", "Vs+", "input"), "3": ("SENSE", "Iout", "output")}


def test_facts_that_number_a_pin_another_way_than_the_symbol_fail_and_say_which(tmp_path):
    """A datasheet draws its SOT-23 with the lone pin as 1, the output; the symbol follows the
    footprint, where the lone pad is 3. Facts copied from the drawing put IOUT on pin 1, and the
    symbol has Iout on pin 3: every line of the part would be judged on the wrong net."""
    net, mpns = circuit(U1=("MON", "MON-1", MONITOR))
    nets = {"VBAT": (2.8, 4.2), "LOAD": (0.0, 4.2)}
    report = ratings.judge(net, mpns, library(tmp_path, monitor("1", "3")), project(nets), NASA)
    assert (
        "fail U1: its facts name pin 1 IOUT, and the symbol names pin 3 Iout: "
        "the 2 number the pins differently [DS-1, rev A]"
    ) in found(report, "fail")
    report = ratings.judge(net, mpns, library(tmp_path, monitor("3", "1")), project(nets), NASA)
    assert not any(f.rule == "facts" for f in report.findings)


def above_its_output(tmp_path: Path, sense_net: dict) -> ratings.Report:
    """A part whose sense pin may not fall more than 0.6 V under its output pin. The output's net is
    stated at up to 1.26 V; the sense pin stands on the net given."""
    chip = entry(
        "ic",
        "MON-2",
        family="linear",
        pins=[
            pin("SENSE", ["1"], "input", abs=[{"pin": "OUT", "plus": -0.6}, 20]),
            pin("OUT", ["2"], "analog", abs=[-0.3, 20]),
        ],
    )
    pins = {"1": ("VSENSE", "SENSE", "input"), "2": ("VOUT", "OUT", "passive")}
    net, mpns = circuit(U1=("MON", "MON-2", pins), J1=("Conn", "", {"1": "VSENSE"}))
    nets = {"VOUT": (0.0, 1.26), **sense_net}
    return ratings.judge(net, mpns, library(tmp_path, chip), project(nets), NASA)


def test_a_least_limit_that_follows_a_pin_is_judged_with_both_nets_on(tmp_path):
    """The cell holds the sense pin at 2.8 V or more while it is on, over the 0.66 V its output asks
    for. With every source off both nets are at 0 V, and no limit between 2 pins is broken: the 0 V a
    net can stand at when off is not held against a limit that follows a pin that is on."""
    report = above_its_output(tmp_path, {"VSENSE": (2.8, 4.2)})
    assert (
        "hold U1 pin 1 (SENSE) on VSENSE: 2.8 to 4.2 V can stand on it, its limits are 0.66 V "
        "(pin OUT at 1.26 V, -0.6 V) and 20 V [DS-1, rev A, p 4]"
    ) in found(report, "hold")
    assert not any(f.part == "U1.1" and f.status == "fail" for f in report.findings)


def test_a_least_limit_that_follows_a_pin_fails_when_the_net_is_held_too_low(tmp_path):
    report = above_its_output(tmp_path, {"VSENSE": (0.3, 4.2)})
    assert (
        "fail U1 pin 1 (SENSE) on VSENSE: 0.3 V can stand on it, its limit is 0.66 V "
        "(pin OUT at 1.26 V, -0.6 V) [DS-1, rev A, p 4]"
    ) in found(report, "fail")


def test_a_name_the_symbol_spells_another_way_is_no_conflict(tmp_path):
    """`~{CHG}` on the symbol and `CHG` in the facts are 1 name; `V+` and `V-` are 2."""
    chip = entry(
        "ic",
        "CMP-2",
        family="linear",
        pins=[
            pin("V+", ["1"], "supply", abs=[-0.5, 7.0], amps=0.000005),
            pin("V-", ["2"], "ground"),
            pin("CHG", ["3"], "open_drain", abs=[-0.5, 7.0], swing=["V-"]),
        ],
    )
    pins = {"1": ("V33", "V+", "power_in"), "2": ("GND", "V-", "power_in"), "3": ("OUT", "~{CHG}", "output")}
    net, mpns = circuit(U1=("CMP", "CMP-2", pins))
    report = ratings.judge(net, mpns, library(tmp_path, chip), project({"V33": (3.0, 3.3), **GND}), NASA)
    assert not any(f.rule == "facts" for f in report.findings)


FILTERED = {"1": ("VDD", "VDD", "power_in"), "2": ("GND", "VSS", "power_in")}


def filtered(number: str) -> tuple[ratings.Netlist, dict[str, str]]:
    """330 ohm and a capacitor in front of 1 part's supply pin: nothing but the resistor feeds VDD."""
    return circuit(
        R1=("330", "R-0402", {"1": "VBAT", "2": "VDD"}),
        C1=("100n", "C-16V", {"1": "VDD", "2": "GND"}),
        U1=("A", number, FILTERED),
    )


def test_a_resistor_that_alone_feeds_a_supply_pin_carries_what_the_pin_takes(tmp_path):
    """The part takes 5.5 uA through 333.3 ohm (1 % over): 1.83 mV across the resistor and 10.1 nW in
    it. Judged by its 2 nets it would stand 4.2 V and burn 54 mW, as if the pin were a short."""
    net, mpns = filtered("LOAD-A")
    facts = library(tmp_path, chip_resistor(), ceramic("C-16V", 16), load("LOAD-A", 5.5e-6))
    report = ratings.judge(net, mpns, facts, project({"VBAT": (2.8, 4.2), **GND}), NASA)
    lines = {f.rule: f.line for f in report.findings if f.part == "R1"}
    said = "hold R1 330 between VBAT and VDD, with the 5.5 uA that VDD takes: "
    assert lines["resistor.voltage"].startswith(said + "1.83 mV on 50 V rated is 0.00, the limit is 0.80")
    assert lines["resistor.power"].startswith(said + "10.1 nW on 62.5 mW rated is 0.00, the limit is 0.50")


def test_a_supply_pin_behind_a_filter_resistor_is_held_to_its_working_range(tmp_path):
    """Nothing but the resistor feeds VDD, so what holds VBAT holds VDD: 2.8 to 4.2 V, against the 1.7
    to 3.6 V the part works from. Without that, no source held the net and the range was not judged."""
    net, mpns = filtered("LOAD-F")
    part = entry(
        "ic",
        "LOAD-F",
        family="digital",
        pins=[
            pin("VDD", ["1"], "supply", abs=[-0.3, 6.0], operating=[1.7, 3.6], amps=5.5e-6),
            pin("VSS", ["2"], "ground"),
        ],
    )
    facts = library(tmp_path, chip_resistor(), ceramic("C-16V", 16), part)
    report = ratings.judge(net, mpns, facts, project({"VBAT": (2.8, 4.2), **GND}), NASA)
    assert found(report, "not judged") == []
    assert found(report, "fail") == [
        "fail U1 pin 1 (VDD) on VDD: its sources hold it at 2.8 to 4.2 V, the pin works from 1.7 to 3.6 V "
        "[DS-1, rev A, p 4]"
    ]


def test_a_resistor_that_feeds_a_pin_of_unknown_current_is_judged_at_the_worst(tmp_path):
    """The supply pin's facts state no current: the whole 4.2 V stays across 326.7 ohm (1 % under),
    54 mW, 0.86 of the part."""
    net, mpns = filtered("LOAD-B")
    facts = library(tmp_path, chip_resistor(), ceramic("C-16V", 16), load("LOAD-B", None))
    report = ratings.judge(net, mpns, facts, project({"VBAT": (2.8, 4.2), **GND}), NASA)
    lines = {f.rule: f.line for f in report.findings if f.part == "R1"}
    assert lines["resistor.voltage"].startswith(
        "hold R1 330 between VBAT and VDD: 4.2 V on 50 V rated is 0.08"
    )
    assert lines["resistor.power"].startswith(
        "fail R1 330 between VBAT and VDD, with 4.2 V across it: 54 mW on 62.5 mW rated is 0.86"
    )


def test_a_resistor_beside_another_source_is_judged_by_its_2_nets(tmp_path):
    """An output of a second part stands on the net behind the resistor and can pull it to 0 V: the
    resistor then stands the whole 4.2 V, whatever the supply pin beside it takes."""
    net, mpns = circuit(
        R1=("330", "R-0402", {"1": "VBAT", "2": "VDD"}),
        U1=("A", "LOAD-A", FILTERED),
        U2=("MCU", "MCU-1", mcu("VDD")),
    )
    facts = library(tmp_path, chip_resistor(), load("LOAD-A", 5.5e-6), MCU_FACTS)
    report = ratings.judge(net, mpns, facts, project({"VBAT": (2.8, 4.2), **RAILS}), NASA)
    (watts,) = (f.line for f in report.findings if f.part == "R1" and f.rule == "resistor.power")
    assert "with 4.2 V across it" in watts and "that VDD takes" not in watts


def test_a_digital_part_s_own_regulator_is_held_to_the_digital_column(tmp_path):
    """A microcontroller's core regulator gives 50 mA on its VCAP pin, and a load there takes 45 mA:
    0.90. NASA allows a plastic digital part 0.80, and a linear one 0.70."""
    core = entry(
        "ic",
        "MCU-2",
        family="digital",
        pins=[
            pin("VDD", ["1"], "supply", abs=[-0.3, 4.0], amps=0.06),
            pin("VSS", ["2"], "ground"),
            pin("VCAP", ["3"], "regulated", abs=[-0.3, 1.5], volts=[1.1, 1.3], amps=0.05),
        ],
    )
    pins = {
        "1": ("V33", "VDD", "power_in"),
        "2": ("GND", "VSS", "power_in"),
        "3": ("V1P2", "VCAP", "power_out"),
    }
    far = {"1": ("V1P2", "VDD", "power_in"), "2": ("GND", "VSS", "power_in")}
    net, mpns = circuit(U1=("MCU", "MCU-2", pins), U2=("A", "LOAD-A", far))
    report = ratings.judge(net, mpns, library(tmp_path, core, load("LOAD-A", 0.045)), project(RAILS), NASA)
    assert found(report, "fail") == [
        "fail V1P2: U1 pin 3 (VCAP) gives 50 mA, its loads take 45 mA: 0.90, the limit is 0.80 "
        f"[{NASA_SOURCE}, section M4, table 4, page 10 of 10, the column Digital]"
    ]


def test_a_load_with_no_current_in_its_facts_leaves_the_rail_not_judged(tmp_path):
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), U2=("A", "LOAD-A", TWO_PINS))
    report = ratings.judge(net, mpns, library(tmp_path, regulator(), load("LOAD-A", None)), project(V5), NASA)
    assert found(report, "not judged") == [
        "not judged V33: U1 pin 3 (OUT) feeds a load nothing states: "
        "U2 pin 1 (VDD) has no `amps` in its facts"
    ]


def test_a_linear_regulator_passes_the_load_on_its_output_to_its_input(tmp_path):
    """A second regulator on the first one's rail takes what its own loads take, and its own 0.1 mA."""
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
        net, mpns, library(tmp_path, regulator(), low, load("LOAD-B", 0.19)), project(V5), NASA
    )
    lines = [f.text for f in report.findings if f.rule == "output.current.linear"]
    assert any(
        text.startswith("V33: U1 pin 3 (OUT) gives 200 mA, its loads take 190 mA: 0.95") for text in lines
    )
    assert any(
        text.startswith("V18: U2 pin 3 (OUT) gives 200 mA, its loads take 190 mA: 0.95") for text in lines
    )


OUT_CAP = {"capacitor": {"from": "OUT", "to": "GND", "farads_min": 0.5e-6}, "page": 5}
EFFECTIVE = {"capacitor": {"from": "OUT", "to": "GND", "farads_min": 0.5e-6, "effective": True}, "page": 5}


def test_a_capacitor_with_no_facts_where_one_is_asked_is_not_judged_and_is_not_absent(tmp_path):
    """C1 stands from the output to ground and no entry names its part number. A capacitor is there;
    what it gives is not known."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), C1=("1u", "C-NOFACTS", {"1": "V33", "2": "GND"}))
    report = ratings.judge(net, mpns, library(tmp_path, regulator(needs=[OUT_CAP])), project(V5), NASA)
    assert not any("none stands there" in f.text for f in report.findings)
    assert "not judged U1 pin OUT (V33) needs a capacitor to GND: C1 stands there and has no facts" in found(
        report, "not judged"
    )


def test_a_capacitor_behind_a_fuse_stands_on_the_pin_s_node(tmp_path):
    """The input pin stands on V5F, behind a fuse from V5, and the capacitor from V5 to ground. A fuse
    is a wire: the 2 nets are 1 node, and the capacitor is the one the datasheet asks for."""
    need = {"capacitor": {"from": "IN", "to": "GND", "farads_min": 0.5e-6}, "page": 5}
    pins = {**LDO, "1": ("V5F", "IN", "power_in")}
    net, mpns = circuit(
        U1=("LDO", "LDO-1", pins),
        F1=("1A", "FUSE-1", {"1": "V5", "2": "V5F"}),
        C1=("1u", "C-16V", {"1": "V5", "2": "GND"}),
    )
    facts = library(
        tmp_path, regulator(needs=[need]), ceramic("C-16V", 16), entry("fuse", "FUSE-1", amps=1.0)
    )
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert any(f.text == "U1 pin IN (V5F) needs 500 nF to GND: C1 gives 1 uF" for f in report.findings), [
        f.line for f in report.findings
    ]
    assert found(report, "fail") == []


def test_a_regulator_with_no_capacitor_on_its_output_fails(tmp_path):
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO))
    report = ratings.judge(net, mpns, library(tmp_path, regulator(needs=[OUT_CAP])), project(V5), NASA)
    assert (
        "fail U1 pin OUT (V33) needs a capacitor to GND, and none stands there [DS-1, rev A, p 5]"
        in found(report, "fail")
    )


def test_a_capacitor_that_is_there_and_large_enough_holds(tmp_path):
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), C1=("1u", "C-16V", {"1": "V33", "2": "GND"}))
    facts = library(tmp_path, regulator(needs=[OUT_CAP]), ceramic("C-16V", 16))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert found(report, "fail") == []
    assert any(f.text == "U1 pin OUT (V33) needs 500 nF to GND: C1 gives 1 uF" for f in report.findings)


def needy_load(farads: float) -> dict:
    """A load whose datasheet asks for a capacitor of its own from VDD to VSS."""
    asks = {"capacitor": {"from": "VDD", "to": "VSS", "farads_min": farads}, "page": 9}
    return {**load("LOAD-A", 0.05), "needs": [asks]}


def test_the_needs_on_1_rail_share_its_capacitors_and_the_last_one_goes_short(tmp_path):
    """The regulator asks for 500 nF and the load for 1 uF of its own. 1 capacitor of 1 uF meets the
    first and leaves 500 nF for the second; 2 of them meet both."""
    parts = {"U1": ("LDO", "LDO-1", LDO), "U2": ("A", "LOAD-A", TWO_PINS)}
    one = {"C1": ("1u", "C-16V", {"1": "V33", "2": "GND"})}
    two = {**one, "C2": ("1u", "C-16V", {"1": "V33", "2": "GND"})}
    facts = library(tmp_path, regulator(needs=[OUT_CAP]), needy_load(1e-6), ceramic("C-16V", 16))
    net, mpns = circuit(**parts, **one)
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert found(report, "fail") == [
        "fail U2 pin VDD (V33) needs 1 uF to GND: C1 gives 1 uF, and the needs before it take 500 nF "
        "[DS-1, rev A, p 9]"
    ]
    net, mpns = circuit(**parts, **two)
    assert found(ratings.judge(net, mpns, facts, project(V5), NASA), "fail") == []


def test_a_connector_pin_the_project_states_a_current_for_is_a_load(tmp_path):
    """Without the statement the pin is a source nothing describes, and its rail has no span."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), J1=("OUT", "HDR-1", {"1": "V33", "2": "GND"}))
    facts = library(tmp_path, regulator(), entry("connector", "HDR-1"))
    report = ratings.judge(net, mpns, facts, project(V5, amps={"J1.1": 0.1}), NASA)
    assert found(report, "not judged") == []
    assert any("its loads take 100 mA: 0.50, the limit is 0.70" in f.text for f in report.findings)
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert any("J1 pin 1 can put a voltage on V33" in line for line in found(report, "not judged"))


def test_a_capacitor_that_keeps_a_third_of_its_value_at_the_rail_fails(tmp_path):
    """1 uF less 10 % that keeps 0.35 of its value at 3.4 V is 315 nF, under the 500 nF asked."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), C1=("1u", "C-6V3", {"1": "V33", "2": "GND"}))
    small = ceramic("C-6V3", 6.3, kept=[[0, 1.0], [3.4, 0.35], [6.3, 0.15]])
    report = ratings.judge(
        net, mpns, library(tmp_path, regulator(needs=[EFFECTIVE]), small), project(V5), NASA
    )
    assert "fail U1 pin OUT (V33) needs 500 nF effective to GND: C1 gives 315 nF [DS-1, rev A, p 5]" in found(
        report, "fail"
    )


def test_an_effective_value_is_not_judged_without_the_maker_s_data(tmp_path):
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), C1=("1u", "C-16V", {"1": "V33", "2": "GND"}))
    facts = library(tmp_path, regulator(needs=[EFFECTIVE]), ceramic("C-16V", 16))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert "not judged U1 pin OUT (V33): C1 has no data on the value it keeps at 3.4 V" in found(
        report, "not judged"
    )


def test_an_effective_value_is_not_judged_of_a_capacitor_with_no_tolerance(tmp_path):
    """What is left of 1 uF under a voltage starts from the value less its tolerance. With no tolerance
    in its facts the capacitor gives nothing for sure, and nothing bounds what it gives at the most."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), C1=("1u", "C-BARE", {"1": "V33", "2": "GND"}))
    bare = entry("capacitor.ceramic", "C-BARE", volts=16, kept=[[0, 1.0], [3.4, 0.7], [16, 0.2]])
    facts = library(tmp_path, regulator(needs=[EFFECTIVE]), bare)
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert "not judged U1 pin OUT (V33): C1 has no tolerance in its facts" in found(report, "not judged")
    assert not any(f.rule == "needs.capacitor" and f.status != "not judged" for f in report.findings)


def test_a_nominal_value_asks_no_tolerance_of_the_capacitor(tmp_path):
    """A datasheet that names a value names the part's nominal one: 1 uF meets 500 nF as it is."""
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), C1=("1u", "C-BARE", {"1": "V33", "2": "GND"}))
    facts = library(tmp_path, regulator(needs=[OUT_CAP]), entry("capacitor.ceramic", "C-BARE", volts=16))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert any(f.text == "U1 pin OUT (V33) needs 500 nF to GND: C1 gives 1 uF" for f in report.findings)


def test_a_capacitor_with_no_data_counts_as_nothing_when_the_others_give_enough(tmp_path):
    """1 uF less 10 % that keeps 0.7 of its value at 3.4 V is 630 nF: over the 500 nF asked alone."""
    net, mpns = circuit(
        U1=("LDO", "LDO-1", LDO),
        C1=("1u", "C-KEPT", {"1": "V33", "2": "GND"}),
        C2=("100n", "C-16V", {"1": "V33", "2": "GND"}),
    )
    known = ceramic("C-KEPT", 16, kept=[[0, 1.0], [3.4, 0.7], [16, 0.2]])
    facts = library(tmp_path, regulator(needs=[EFFECTIVE]), known, ceramic("C-16V", 16))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert found(report, "not judged") == []
    assert any(
        f.text == "U1 pin OUT (V33) needs 500 nF effective to GND: C1 gives 630 nF, "
        "C2 gives 110 nF at most (no data on the value it keeps)"
        for f in report.findings
    )


def test_a_need_fails_when_the_most_a_capacitor_with_no_data_could_give_is_too_little(tmp_path):
    """315 nF known, and 100 nF plus 10 % at the most from the one with no data: 425 nF, under 500 nF."""
    net, mpns = circuit(
        U1=("LDO", "LDO-1", LDO),
        C1=("1u", "C-KEPT", {"1": "V33", "2": "GND"}),
        C2=("100n", "C-16V", {"1": "V33", "2": "GND"}),
    )
    known = ceramic("C-KEPT", 16, kept=[[0, 1.0], [3.4, 0.35], [16, 0.1]])
    facts = library(tmp_path, regulator(needs=[EFFECTIVE]), known, ceramic("C-16V", 16))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert found(report, "fail") == [
        "fail U1 pin OUT (V33) needs 500 nF effective to GND: C1 gives 315 nF, "
        "C2 gives 110 nF at most (no data on the value it keeps) [DS-1, rev A, p 5]"
    ]


def test_a_fact_read_on_2_pages_names_both_and_a_note_of_the_facts_is_in_the_report(tmp_path):
    net, mpns = circuit(
        U1=("MCU", "MCU-1", {"1": ("V33", "VDD", "power_in"), "2": ("GND", "VSS", "power_in")})
    )
    chip = entry(
        "ic",
        "MCU-1",
        family="digital",
        note="its brown-out level is not judged",
        pins=[
            {**pin("VDD", ["1"], "supply", abs=[-0.3, 4.0], operating=[3.4, 3.6]), "page": [4, 5]},
            pin("VSS", ["2"], "ground"),
        ],
    )
    report = ratings.judge(net, mpns, library(tmp_path, chip), project({"V33": (3.2, 3.4), **GND}), NASA)
    assert found(report, "fail") == [
        "fail U1 pin 1 (VDD) on V33: its sources hold it at 3.2 to 3.4 V, the pin works from 3.4 to 3.6 V "
        "[DS-1, rev A, p 4 and 5]"
    ]
    assert "U1 (MCU-1): its brown-out level is not judged" in report.notes


BUCK = entry(
    "ic",
    "BUCK-1",
    family="regulator.switching",
    pins=[
        pin("VIN", ["1"], "supply", abs=[-0.3, 20.0], amps=1.0),
        pin("GND", ["2"], "ground"),
        pin("SW", ["3"], "switched", abs=[-1.0, 20.0], swing=["GND", "VIN"]),
        pin("VOS", ["4"], "input", abs=[-0.3, 6.0]),
    ],
    needs=[
        {
            "inductor": {"from": "SW", "to": "VOS", "henries": [1.5e-6, 4.7e-6], "amps_saturation_min": 1.5},
            "page": 12,
        }
    ],
)
BUCK_PINS = {
    "1": ("V12", "VIN", "power_in"),
    "2": ("GND", "GND", "power_in"),
    "3": ("SW", "SW", "output"),
    "4": ("V33", "VOS", "input"),
}


def test_an_inductor_that_saturates_under_the_current_asked_fails(tmp_path):
    net, mpns = circuit(U1=("BUCK", "BUCK-1", BUCK_PINS), L1=("2.2u", "L-1", {"1": "SW", "2": "V33"}))
    nets = {"V12": (11.4, 12.6), "V33": (3.2, 3.4), **GND}
    for saturation, status in ((2.0, "hold"), (1.0, "fail")):
        coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=saturation)
        report = ratings.judge(net, mpns, library(tmp_path, BUCK, coil), project(nets), NASA)
        lines = [f.line for f in report.findings if f.rule == "needs.inductor"]
        assert (
            f"{status} U1 pin SW (SW) needs an inductor that saturates above 1.5 A, "
            f"L1 saturates at {saturation:g} A [DS-1, rev A, p 12]" in lines
        )
        assert (
            "hold U1 pin SW (SW) needs 1.5 uH to 4.7 uH, L1 is 1.76 uH to 2.64 uH [DS-1, rev A, p 12]"
            in lines
        )


def test_an_inductor_outside_the_range_asked_fails(tmp_path):
    net, mpns = circuit(U1=("BUCK", "BUCK-1", BUCK_PINS), L1=("10u", "L-1", {"1": "SW", "2": "V33"}))
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=2.0)
    nets = {"V12": (11.4, 12.6), "V33": (3.2, 3.4), **GND}
    report = ratings.judge(net, mpns, library(tmp_path, BUCK, coil), project(nets), NASA)
    assert any(
        line.startswith("fail U1 pin SW (SW) needs 1.5 uH to 4.7 uH, L1 is 8 uH to 12 uH")
        for line in found(report, "fail")
    )


# ---------------------------------------------------------------- an output a divider sets, and a buck

ADJUSTABLE = entry(
    "ic",
    "ADJ-1",
    family="regulator.linear",
    pins=[
        pin("IN", ["1"], "supply", abs=[-0.3, 6.5], operating=[2.5, 6.0], amps=0.0001),
        pin("GND", ["2"], "ground"),
        pin("OUT", ["3"], "regulated", abs=[-0.3, 6.5], set_by="FB"),
        pin("FB", ["4"], "feedback", abs=[-0.3, 6.5], volts=[0.792, 0.808], amps=0.3),
    ],
)
ADJ_PINS = {
    "1": ("V5", "IN", "power_in"),
    "2": ("GND", "GND", "power_in"),
    "3": ("VOUT", "OUT", "power_out"),
    "4": ("FB", "FB", "input"),
}
# 100k over 31.6k at 1 %, under 0.8 V at 1 %: 0.792 x (1 + 99000 / 31916) is 3.2487 V, and
# 0.808 x (1 + 101000 / 31284) is 3.4166 V.
DIVIDER = {
    "R1": ("100k", "R-0402", {"1": "VOUT", "2": "FB"}),
    "R2": ("31.6k", "R-0402", {"1": "FB", "2": "GND"}),
}
ON_VOUT = {"1": ("VOUT", "VDD", "power_in"), "2": ("GND", "VSS", "power_in")}


def test_an_output_a_divider_sets_is_worked_out_at_the_corners_of_its_resistors(tmp_path):
    """A load that works from 3.3 V on is under its range when the divider puts the rail at 3.25 V."""
    net, mpns = circuit(U1=("ADJ", "ADJ-1", ADJ_PINS), U2=("A", "LOAD-A", ON_VOUT), **DIVIDER)
    needy = load("LOAD-A", 0.05)
    needy["pins"][0]["operating"] = [3.3, 3.6]
    facts = library(tmp_path, ADJUSTABLE, chip_resistor(), needy)
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert (
        "U1 holds VOUT at 3.25 to 3.42 V: its pin FB at 0.792 to 0.808 V, R1 over R2 "
        "[TI SLVA477C, equation 11]"
    ) in report.notes
    assert found(report, "fail") == [
        "fail U2 pin 1 (VDD) on VOUT: its sources hold it at 3.25 to 3.42 V, "
        "the pin works from 3.3 to 3.6 V [DS-1, rev A, p 4]"
    ]
    assert found(report, "not judged") == []


def test_a_divider_with_another_part_on_its_tap_is_not_judged_and_says_which(tmp_path):
    net, mpns = circuit(U1=("ADJ", "ADJ-1", ADJ_PINS), J1=("TP", "", {"1": "FB"}), **DIVIDER)
    report = ratings.judge(net, mpns, library(tmp_path, ADJUSTABLE, chip_resistor()), project(V5), NASA)
    assert (
        "not judged U1 pin 4 (FB) on FB: J1 pin 1 stands on FB too, and is no resistor of a divider"
        in found(report, "not judged")
    )


def test_a_divider_of_3_resistors_is_not_judged(tmp_path):
    third = {"R3": ("10k", "R-0402", {"1": "FB", "2": "GND"})}
    net, mpns = circuit(U1=("ADJ", "ADJ-1", ADJ_PINS), **DIVIDER, **third)
    report = ratings.judge(net, mpns, library(tmp_path, ADJUSTABLE, chip_resistor()), project(V5), NASA)
    assert (
        "not judged U1 pin 4 (FB) on FB: its divider is 1 resistor to another net and 2 to a net at 0 V, "
        "not 1 and 1" in found(report, "not judged")
    )


def test_a_bottom_resistor_on_a_net_a_link_joins_to_ground_is_a_divider_s(tmp_path):
    """The bottom resistor ends on AGND, which a 0 ohm link joins to GND: AGND is at 0 V. The output is
    0.8 V x (1 + 100k / 31.6k), 3.25 to 3.42 V, and not the 0.8 V of a pin on its own output."""
    parts = {**DIVIDER, "R2": ("31.6k", "R-0402", {"1": "FB", "2": "AGND"})}
    link = {"JP1": ("0R", "LINK-1", {"1": "AGND", "2": "GND"})}
    net, mpns = circuit(U1=("ADJ", "ADJ-1", ADJ_PINS), **parts, **link)
    facts = library(tmp_path, ADJUSTABLE, chip_resistor(), entry("link", "LINK-1"))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert (
        "U1 holds VOUT at 3.25 to 3.42 V: its pin FB at 0.792 to 0.808 V, R1 over R2 "
        "[TI SLVA477C, equation 11]"
    ) in report.notes


def test_a_tap_with_no_resistor_to_0_volts_is_not_a_pin_on_its_own_output(tmp_path):
    """The bottom is 2 resistors in a row. The pin's net then has 2 resistors to other nets and none
    to a net at 0 V: a divider the command does not read, and never an output of 0.8 V."""
    parts = {
        **DIVIDER,
        "R2": ("15.8k", "R-0402", {"1": "FB", "2": "TRIM"}),
        "R3": ("15.8k", "R-0402", {"1": "TRIM", "2": "GND"}),
    }
    net, mpns = circuit(U1=("ADJ", "ADJ-1", ADJ_PINS), **parts)
    report = ratings.judge(net, mpns, library(tmp_path, ADJUSTABLE, chip_resistor()), project(V5), NASA)
    assert (
        "not judged U1 pin 4 (FB) on FB: its divider is 2 resistors to another net and 0 to a net at 0 V, "
        "not 1 and 1" in found(report, "not judged")
    )
    assert not any("fed back whole" in note for note in report.notes)


def test_an_output_under_a_negative_reference_is_worked_out_at_its_own_corners(tmp_path):
    """A reference of -1.2 to -1.16 V under 32.4k over 10k at 5 %: the ratio is 1 + 30780 / 10500 =
    3.931 to 1 + 34020 / 9500 = 4.581. The least output is the least reference times the greatest
    ratio, -5.497 V, and the greatest is -1.16 x 3.931 = -4.560 V."""
    below = json.loads(json.dumps(ADJUSTABLE))
    below["mpn"], below["pins"][3]["volts"] = "ADJ-N", [-1.2, -1.16]
    wide = entry("resistor", "R-5PCT", tolerance=0.05, watts=0.0625, volts=50)
    pins = {**ADJ_PINS, "1": ("VNEG", "IN", "power_in")}
    net, mpns = circuit(
        U1=("ADJ", "ADJ-N", pins),
        R1=("32.4k", "R-5PCT", {"1": "VOUT", "2": "FB"}),
        R2=("10k", "R-5PCT", {"1": "FB", "2": "GND"}),
    )
    nets = {"VNEG": (-12.6, -11.4), **GND}
    report = ratings.judge(net, mpns, library(tmp_path, below, wide), project(nets), NASA)
    assert (
        "U1 holds VOUT at -5.5 to -4.56 V: its pin FB at -1.2 to -1.16 V, R1 over R2 "
        "[TI SLVA477C, equation 11]"
    ) in report.notes


def test_a_part_s_other_pins_are_held_to_the_output_its_own_divider_sets(tmp_path):
    """100k over 10k under a 0.8 V reference sets 8.56 to 9.05 V. The part's OUT pin takes 6.5 V, its
    sense pin on the same net 6 V, and its power-good pin, pulled up to that net, 6 V: all 3 fail. A
    pin is not judged against its own drive; another pin of its part is another source."""
    chip = entry(
        "ic",
        "ADJ-2",
        family="regulator.linear",
        pins=[
            pin("IN", ["1"], "supply", abs=[-0.3, 20.0], amps=0.0001),
            pin("GND", ["2"], "ground"),
            pin("OUT", ["3"], "regulated", abs=[-0.3, 6.5], set_by="FB"),
            pin("FB", ["4"], "feedback", abs=[-0.3, 6.5], volts=[0.792, 0.808], amps=0.3),
            pin("PG", ["5"], "open_drain", abs=[-0.3, 6.0], swing=["GND"]),
            pin("VOS", ["6"], "input", abs=[-0.3, 6.0]),
        ],
    )
    pins = {
        "1": ("V12", "IN", "power_in"),
        "2": ("GND", "GND", "power_in"),
        "3": ("VOUT", "OUT", "power_out"),
        "4": ("FB", "FB", "input"),
        "5": ("PG", "PG", "open_collector"),
        "6": ("VOUT", "VOS", "input"),
    }
    net, mpns = circuit(
        U1=("ADJ", "ADJ-2", pins),
        R1=("100k", "R-0402", {"1": "VOUT", "2": "FB"}),
        R2=("10k", "R-0402", {"1": "FB", "2": "GND"}),
        R3=("100k", "R-0402", {"1": "VOUT", "2": "PG"}),
    )
    report = ratings.judge(net, mpns, library(tmp_path, chip, chip_resistor()), project(V12), NASA)
    fails = found(report, "fail")
    for said in (
        "fail U1 pin 3 (OUT) on VOUT: 9.05 V can stand on it, its limit is 6.5 V",
        "fail U1 pin 5 (PG) on PG: 9.05 V can stand on it, its limit is 6 V",
        "fail U1 pin 6 (VOS) on VOUT: 9.05 V can stand on it, its limit is 6 V",
    ):
        assert any(line.startswith(said) for line in fails), (said, fails)


def test_a_pin_pulled_up_to_its_own_part_s_fixed_output_is_held_to_that_output(tmp_path):
    """A regulator that gives 8.8 to 9.2 V, and its power-good pin, which takes 6 V, pulled up to it."""
    chip = entry(
        "ic",
        "FIX-9",
        family="regulator.linear",
        pins=[
            pin("IN", ["1"], "supply", abs=[-0.3, 20.0], amps=0.0001),
            pin("GND", ["2"], "ground"),
            pin("OUT", ["3"], "regulated", abs=[-0.3, 12.0], volts=[8.8, 9.2], amps=0.3),
            pin("PG", ["5"], "open_drain", abs=[-0.3, 6.0], swing=["GND"]),
        ],
    )
    pins = {
        "1": ("V12", "IN", "power_in"),
        "2": ("GND", "GND", "power_in"),
        "3": ("V9", "OUT", "power_out"),
        "5": ("PG", "PG", "open_collector"),
    }
    net, mpns = circuit(U1=("FIX", "FIX-9", pins), R3=("100k", "R-0402", {"1": "V9", "2": "PG"}))
    report = ratings.judge(net, mpns, library(tmp_path, chip, chip_resistor()), project(V12), NASA)
    assert any(
        line.startswith("fail U1 pin 5 (PG) on PG: 9.2 V can stand on it, its limit is 6 V")
        for line in found(report, "fail")
    )


def test_a_feedback_pin_left_open_regulates_nothing_the_command_can_name(tmp_path):
    """Nothing but the pin stands on its net: no divider, and no output the pin is fed back from."""
    pins = {**ADJ_PINS, "4": ("unconnected-(U1-FB-Pad4)", "FB", "input")}
    net, mpns = circuit(U1=("ADJ", "ADJ-1", pins))
    report = ratings.judge(net, mpns, library(tmp_path, ADJUSTABLE), project(V5), NASA)
    assert (
        "not judged U1 pin 4 (FB) on unconnected-(U1-FB-Pad4): no other part stands on its net, "
        "and nothing sets the output" in found(report, "not judged")
    )
    assert not any("fed back whole" in note for note in report.notes)


def test_an_output_pin_off_the_net_its_divider_regulates_fails(tmp_path):
    pins = {**ADJ_PINS, "3": ("OTHER", "OUT", "power_out")}
    net, mpns = circuit(U1=("ADJ", "ADJ-1", pins), C1=("1u", "C-10V", {"1": "OTHER", "2": "GND"}), **DIVIDER)
    facts = library(tmp_path, ADJUSTABLE, chip_resistor(), ceramic("C-10V", 10))
    report = ratings.judge(net, mpns, facts, project(V5), NASA)
    assert (
        "fail U1 pin 3 (OUT) is on OTHER, and the divider on its pin FB regulates VOUT [DS-1, rev A, p 4]"
        in found(report, "fail")
    )


SWITCHER = entry(
    "ic",
    "BUCK-2",
    family="regulator.switching",
    switching={"topology": "buck", "hertz": [2.0e6, 3.0e6], "page": 7},
    pins=[
        pin("VIN", ["1"], "supply", abs=[-0.3, 20.0], amps=0.001),
        pin("GND", ["2"], "ground"),
        pin("SW", ["3"], "switched", abs=[-1.0, 20.0], swing=["GND", "VIN"]),
        pin("FB", ["4"], "feedback", abs=[-0.3, 6.0], volts=[0.792, 0.808], amps=3.0),
    ],
    needs=[{"inductor": {"from": "SW", "to": "FB"}, "page": 12}],
)
SWITCHER_PINS = {
    "1": ("V12", "VIN", "power_in"),
    "2": ("GND", "GND", "power_in"),
    "3": ("SW", "SW", "output"),
    "4": ("FB", "FB", "input"),
}
V12 = {"V12": (11.4, 12.6), **GND}


def buck_board(**more: tuple) -> tuple[ratings.Netlist, dict[str, str]]:
    """A buck from 12 V with the divider above, a 2.2 uH inductor and a load of 1 A on its output."""
    return circuit(
        U1=("BUCK", "BUCK-2", SWITCHER_PINS),
        L1=("2.2u", "L-1", {"1": "SW", "2": "VOUT"}),
        U2=("A", "LOAD-A", ON_VOUT),
        **DIVIDER,
        **more,
    )


def test_2_inductors_side_by_side_share_the_load(tmp_path):
    """2 equal inductors from the switch node to the output carry 0.5 A each of the 1 A load, and each
    its own ripple: 0.5 A and half of 786 mA is 0.893 A, under the 1.2 A each saturates at. Judged as
    if each carried the whole load, 1.39 A, both would fail."""
    net, mpns = buck_board(L2=("2.2u", "L-1", {"1": "SW", "2": "VOUT"}))
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=1.2)
    facts = library(tmp_path, SWITCHER, chip_resistor(), coil, load("LOAD-A", 1.0))
    report = ratings.judge(net, mpns, facts, project(V12), NASA)
    lines = [f.line for f in report.findings if f.part in ("L1", "L2") and f.rule == "inductor.current"]
    assert len(lines) == 2 and all(line.startswith("hold L") for line in lines), lines
    assert (
        "its peak current is 893 mA: 500 mA of load, 1 of 2 inductors side by side, and half of" in lines[0]
    )


def test_an_inductor_past_its_ratings_before_the_last_load_is_known_fails(tmp_path):
    """2.5 A of 1 load is over the 1.5 A the inductor is rated for and the 2 A it saturates at, before
    any ripple and whatever a second pin with no stated current takes."""
    net, mpns = buck_board(U3=("B", "LOAD-B", ON_VOUT))
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=2.0, amps_rms=1.5)
    facts = library(tmp_path, SWITCHER, chip_resistor(), coil, load("LOAD-A", 2.5), load("LOAD-B", None))
    report = ratings.judge(net, mpns, facts, project(V12), NASA)
    lines = [f.line for f in report.findings if f.part == "L1"]
    assert lines == [
        "fail L1 2.2u: its loads take at least 2.5 A, its rated current is 1.5 A "
        "[DS-1, rev A: the part's own rating]",
        "fail L1 2.2u: its loads take at least 2.5 A before any ripple, and it saturates at 2 A "
        "[DS-1, rev A: the part's own rating]",
    ]


def test_a_buck_s_inductor_is_held_to_its_load_and_half_its_ripple(tmp_path):
    """At 12.6 V in, 3.4166 V out, 2 MHz, 2.2 uH less 20 % and 90 % efficiency the ripple is
    (12.6 - 3.4166) x 3.4166 / (12.6 x 0.9) / (2e6 x 1.76e-6) = 0.786 A. The load is 1 A and the 35 uA
    of the divider: the peak is 1.393 A."""
    net, mpns = buck_board()
    for saturation, status in ((2.0, "hold"), (1.2, "fail")):
        coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=saturation)
        facts = library(tmp_path, SWITCHER, coil, chip_resistor(), load("LOAD-A", 1.0))
        report = ratings.judge(net, mpns, facts, project(V12), NASA)
        assert (
            f"{status} L1 2.2u: its peak current is 1.39 A: 1 A of load and half of 786 mA of ripple "
            f"(12.6 V in, 3.42 V out, 1.76 uH, 2 MHz); it saturates at {saturation:g} A "
            "[DS-1, rev A: the part's own rating; TI SLVA477C, equations 1, 2 and 4]"
        ) in [f.line for f in report.findings if f.rule == "inductor.current"]
        assert "U1: its facts state no efficiency, and 0.9 is taken [TI SLVA477C, section 2]" in report.notes


def test_a_load_behind_a_buck_s_inductor_is_held_to_the_output_and_not_to_the_input(tmp_path):
    """The switched pin swings to 12.6 V. The inductor carries its average, which the divider sets."""
    net, mpns = buck_board()
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=2.0)
    facts = library(tmp_path, SWITCHER, coil, chip_resistor(), load("LOAD-A", 1.0))
    report = ratings.judge(net, mpns, facts, project(V12), NASA)
    assert found(report, "fail") == []
    assert (
        "hold U2 pin 1 (VDD) on VOUT: 0 to 3.42 V can stand on it, its limits are -0.3 V and 4 V "
        "[DS-1, rev A, p 4]" in found(report, "hold")
    )


def test_an_inductor_s_rated_current_is_held_to_the_load(tmp_path):
    net, mpns = buck_board()
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=2.0, amps_rms=0.8)
    facts = library(tmp_path, SWITCHER, coil, chip_resistor(), load("LOAD-A", 1.0))
    report = ratings.judge(net, mpns, facts, project(V12), NASA)
    assert found(report, "fail") == [
        "fail L1 2.2u: its loads take 1 A, its rated current is 800 mA [DS-1, rev A: the part's own rating]"
    ]


def test_a_choke_on_a_steady_rail_joins_its_2_nets(tmp_path):
    """No switched pin stands on it: behind the inductor the capacitor sees the rail's 5.5 V."""
    net, mpns = circuit(
        L1=("10u", "L-1", {"1": "V5", "2": "V5F"}), C1=("10u", "C-6V3", {"1": "V5F", "2": "GND"})
    )
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=2.0)
    report = ratings.judge(net, mpns, library(tmp_path, coil, ceramic("C-6V3", 6.3)), project(V5), NASA)
    assert found(report, "fail") == [
        "fail C1 10u between V5F and GND: 5.5 V on 6.3 V rated is 0.87, the limit is 0.60 "
        f"[{NASA_SOURCE}, section C1, table 4, page 23 of 23]"
    ]


FIXED_BUCK = entry(
    "ic",
    "BUCK-3",
    family="regulator.switching",
    switching={"topology": "buck", "hertz": [2.0e6, 3.0e6], "page": 7},
    pins=[
        pin("VIN", ["1"], "supply", abs=[-0.3, 6.0], amps=0.001),
        pin("GND", ["2"], "ground"),
        pin("SW", ["3"], "switched", abs=[-1.0, 6.0], swing=["GND", "VIN"]),
        pin("VOS", ["4"], "regulated", abs=[-0.3, 6.0], volts=[1.188, 1.212], amps=2.0),
    ],
)
FIXED_BUCK_PINS = {
    "1": ("V33", "VIN", "power_in"),
    "2": ("GND", "GND", "power_in"),
    "3": ("SW", "SW", "output"),
    "4": ("V1P2", "VOS", "input"),
}
ON_V1P2 = {"1": ("V1P2", "VDD", "power_in"), "2": ("GND", "VSS", "power_in")}


def second_stage(buck: dict, tmp_path: Path) -> ratings.Report:
    """A 500 mA regulator at 3.2 to 3.4 V feeds a buck that gives 1 A at 1.188 to 1.212 V."""
    net, mpns = circuit(
        U1=("LDO", "LDO-1", LDO),
        U2=("BUCK", "BUCK-3", FIXED_BUCK_PINS),
        L1=("2.2u", "L-1", {"1": "SW", "2": "V1P2"}),
        U3=("A", "LOAD-A", ON_V1P2),
    )
    coil = entry("inductor", "L-1", tolerance=0.2, amps_saturation=3.0)
    facts = library(tmp_path, regulator(0.5), buck, coil, load("LOAD-A", 1.0))
    return ratings.judge(net, mpns, facts, project(V5), NASA)


def test_a_switching_regulator_takes_its_load_s_power_over_its_efficiency(tmp_path):
    """1 A at 1.212 V from 3.2 V at 90 % is 1.212 / (0.9 x 3.2) = 0.4208 A, and its own 1 mA: 0.84 of
    500 mA. At the 80 % its facts state it is 1.212 / (0.8 x 3.2) + 0.001 = 0.4744 A: 0.95."""
    report = second_stage(FIXED_BUCK, tmp_path)
    assert (
        "fail V33: U1 pin 3 (OUT) gives 500 mA, its loads take 422 mA: 0.84, the limit is 0.70 "
        f"[{NASA_SOURCE}, {LINEAR}]" in found(report, "fail")
    )
    stated = {**FIXED_BUCK, "switching": {**FIXED_BUCK["switching"], "efficiency": 0.8}}
    report = second_stage(stated, tmp_path)
    assert any("its loads take 474 mA: 0.95, the limit is 0.70" in line for line in found(report, "fail"))
    assert not any("efficiency" in note for note in report.notes)


def test_a_switching_regulator_with_no_switching_facts_leaves_the_rail_above_it_not_judged(tmp_path):
    bare = {k: v for k, v in FIXED_BUCK.items() if k != "switching"}
    report = second_stage(bare, tmp_path)
    assert (
        "not judged V33: U1 pin 3 (OUT) feeds a load nothing states: "
        "U2 is a switching regulator, and its facts state no `switching`" in found(report, "not judged")
    )


def test_a_supply_pin_with_2_numbers_is_counted_1_time(tmp_path):
    pins = {**TWO_PINS, "3": ("V33", "VDD", "power_in")}
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), U2=("A", "LOAD-A", pins))
    wide = load("LOAD-A", 0.13)
    wide["pins"][0]["numbers"] = ["1", "3"]
    report = ratings.judge(net, mpns, library(tmp_path, regulator(), wide), project(V5), NASA)
    assert found(report, "fail") == []
    assert any("its loads take 130 mA: 0.65, the limit is 0.70" in f.text for f in report.findings)


def test_a_regulator_passes_its_load_to_the_supply_pin_its_facts_name(tmp_path):
    """The second regulator's output current comes from IN on the 5 V rail. Its BIAS pin on the first
    regulator's rail takes 1 mA and no more."""
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
        "2": ("V33", "BIAS", "power_in"),
        "3": ("GND", "GND", "power_in"),
        "4": ("V18", "OUT", "power_out"),
    }
    far = {"1": ("V18", "VDD", "power_in"), "2": ("GND", "VSS", "power_in")}
    net, mpns = circuit(U1=("LDO", "LDO-1", LDO), U2=("LDO", "LDO-BIAS", pins), U3=("A", "LOAD-A", far))
    report = ratings.judge(
        net, mpns, library(tmp_path, regulator(), dual, load("LOAD-A", 0.5)), project(V5), NASA
    )
    texts = [f.text for f in report.findings if f.rule == "output.current.linear"]
    assert any(t.startswith("V33: U1 pin 3 (OUT) gives 200 mA, its loads take 1 mA: 0.01") for t in texts)
    assert any(t.startswith("V18: U2 pin 4 (OUT) gives 1 A, its loads take 500 mA: 0.50") for t in texts)


def test_a_voltage_the_project_states_across_a_part_is_what_the_part_is_held_to(tmp_path):
    """A bootstrap capacitor rides on the switched pin: the board's nets do not give the 5.5 V across it."""
    net, mpns = circuit(C1=("100n", "C-16V", {"1": "BOOT", "2": "SW"}))
    asked = project({}, volts={"C1": 5.5})
    report = ratings.judge(net, mpns, library(tmp_path, ceramic("C-16V", 16)), asked, NASA)
    assert [f.line for f in report.findings] == [
        "hold C1 100n between BOOT and SW, with the 5.5 V the project states: 5.5 V on 16 V rated is 0.34, "
        f"the limit is 0.60 [{NASA_SOURCE}, section C1, table 4, page 23 of 23]"
    ]


# ---------------------------------------------------------------- what the owner accepts, and the lines


def test_a_failure_the_owner_accepts_is_printed_as_accepted_and_is_no_pass(tmp_path):
    net, mpns = circuit(C1=("10u", "C-16V", {"1": "V12", "2": "GND"}))
    owner = {
        ("C1", "capacitor.ceramic.voltage"): "a 25 V part does not fit (the owner's decision of 2026-11-17)"
    }
    nets = {"V12": (11.4, 12.6), **GND}
    report = ratings.judge(
        net, mpns, library(tmp_path, ceramic("C-16V", 16)), project(nets, accepted=owner), NASA
    )
    assert found(report, "fail") == [] and found(report, "hold") == []
    (line,) = found(report, "accepted")
    assert "accepted: a 25 V part does not fit (the owner's decision of 2026-11-17)" in line
    assert ratings.lines(report)[0].startswith(
        "ratings: 0 fail, 1 accepted, 0 hold, 0 not judged; pack nasa-eee-inst-002"
    )
    assert ratings.verdict(report) == ("RATINGS HELD", 0)


def test_an_accepted_failure_that_fails_no_more_is_a_failure_of_its_own(tmp_path):
    net, mpns = circuit(C1=("10u", "C-25V", {"1": "V12", "2": "GND"}))
    owner = {("C1", "capacitor.ceramic.voltage"): "x (the owner's decision of 2026-11-17)"}
    nets = {"V12": (11.4, 12.6), **GND}
    report = ratings.judge(
        net, mpns, library(tmp_path, ceramic("C-25V", 25)), project(nets, accepted=owner), NASA
    )
    assert found(report, "fail") == [
        "fail C1: ratings.json accepts a failure of capacitor.ceramic.voltage, and nothing fails there: "
        "take the entry out"
    ]


def test_the_lines_put_failures_first_and_stop_at_the_limit(tmp_path):
    parts = {f"C{i}": ("10u", "C-16V", {"1": "V12", "2": "GND"}) for i in range(1, 25)}
    parts["C30"] = ("10u", "C-NONE", {"1": "V12", "2": "GND"})
    net, mpns = circuit(**parts)
    report = ratings.judge(
        net, mpns, library(tmp_path, ceramic("C-16V", 16)), project({"V12": (11.4, 12.6), **GND}), NASA
    )
    out = ratings.lines(report)
    assert out[0].startswith("ratings: 24 fail, 0 accepted, 0 hold, 1 not judged; pack nasa-eee-inst-002")
    assert len(out) == 22 and all(line.startswith("fail C") for line in out[1:21])
    assert out[21] == "... 5 more in the report"
    assert ratings.verdict(report) == ("RATINGS NOT HELD (24 fail, 1 not judged)", 1)
    page = ratings.markdown(report)
    assert page.count("\n- ") == 25 and "## Not judged: 1" in page and "## Fail: 24" in page


def test_what_is_not_judged_is_in_the_verdict_and_fails_a_strict_run(tmp_path):
    """12.6 V on the 25 V capacitor is 0.50 and holds. The other capacitor has no facts."""
    net, mpns = circuit(
        C1=("10u", "C-NONE", {"1": "V12", "2": "GND"}), C2=("10u", "C-25V", {"1": "V12", "2": "GND"})
    )
    report = ratings.judge(
        net, mpns, library(tmp_path, ceramic("C-25V", 25)), project({"V12": (0.0, 12.6), **GND}), NASA
    )
    assert ratings.verdict(report) == ("RATINGS HELD, 1 NOT JUDGED", 0)
    assert ratings.verdict(report, strict=True) == ("RATINGS HELD, 1 NOT JUDGED", 1)


def test_the_report_names_the_parts_it_held_to_nothing(tmp_path):
    """A connector and a test point have facts and no stress the command computes: the report says so."""
    net, mpns = circuit(
        C1=("10u", "C-25V", {"1": "V12", "2": "GND"}),
        J1=("IN", "HDR-1", {"1": "V12", "2": "GND"}),
        J2=("IN", "HDR-1", {"1": "V12", "2": "GND"}),
        TP1=("TP", "TP-1", {"1": "V12"}),
    )
    facts = library(tmp_path, ceramic("C-25V", 25), entry("connector", "HDR-1"), entry("testpoint", "TP-1"))
    report = ratings.judge(net, mpns, facts, project({"V12": (11.4, 12.6), **GND}), NASA)
    assert "no stress is judged of J1, J2 (connector), TP1 (testpoint)" in report.notes
    assert ratings.verdict(report) == ("RATINGS HELD", 0)


def test_a_run_that_judged_nothing_is_no_pass(tmp_path):
    net, mpns = circuit(C1=("10u", "C-NONE", {"1": "V12", "2": "GND"}))
    report = ratings.judge(
        net, mpns, library(tmp_path, ceramic("C-16V", 16)), project({"V12": (0.0, 12.6), **GND}), NASA
    )
    assert ratings.verdict(report) == ("NOTHING JUDGED (1 not judged)", 1)
    assert ratings.lines(report)[0].startswith("ratings: 0 fail, 0 accepted, 0 hold, 1 not judged")


def test_sources_no_second_reader_has_read_are_counted_in_the_first_line(tmp_path):
    """A pack counts until a second reader has read it, and so does each facts entry that is used."""
    net, mpns = circuit(C1=("10u", "C-25V", {"1": "V12", "2": "GND"}))
    nets = project({"V12": (11.4, 12.6), **GND})
    once = {**ceramic("C-25V", 25), "source": {**READ, "second_reader": "no"}}
    unread_pack = ratings.Pack(NASA.name, {**NASA.document, "second_reader": "no"}, NASA.rules)
    read_pack = ratings.Pack(NASA.name, {**NASA.document, "second_reader": "2026-11-17"}, NASA.rules)
    report = ratings.judge(net, mpns, library(tmp_path, once), nets, unread_pack)
    assert report.unread == 2
    assert ratings.lines(report)[0].endswith("; 2 sources not read a second time")
    report = ratings.judge(net, mpns, library(tmp_path, once), nets, read_pack)
    assert ratings.lines(report)[0].endswith("; 1 source not read a second time")
    report = ratings.judge(net, mpns, library(tmp_path, ceramic("C-25V", 25)), nets, read_pack)
    assert ratings.lines(report)[0].endswith("; pack nasa-eee-inst-002")


def test_a_rule_s_factor_falls_with_the_ambient_the_project_states(tmp_path):
    """NASA allows a solid tantalum capacitor 0.50 up to 70 C and 0.30 at 110 C: 0.40 at 90 C."""
    net, mpns = circuit(C1=("10u", "C-TA", {"1": "V5", "2": "GND"}))
    facts = library(tmp_path, entry("capacitor.tantalum", "C-TA", tolerance=0.1, volts=10))
    nets = {"V5": (4.4, 4.5), **GND}
    assert found(ratings.judge(net, mpns, facts, project(nets, ambient=60), NASA), "fail") == []
    hot = ratings.judge(net, mpns, facts, project(nets, ambient=90), NASA)
    assert "4.5 V on 10 V rated is 0.45, the limit is 0.40" in found(hot, "fail")[0]
    # at the last temperature the table names the share is its last one; past it the part is not allowed
    for ambient, share in ((110, "0.30"), (110.5, "0.00"), (150, "0.00")):
        report = ratings.judge(net, mpns, facts, project(nets, ambient=ambient), NASA)
        assert f"4.5 V on 10 V rated is 0.45, the limit is {share}" in found(report, "fail")[0]
    cold = ratings.judge(net, mpns, facts, project(nets), NASA)
    assert cold.notes == [
        "capacitor.tantalum.voltage: judged as under 70 C, since the project states no ambient"
    ]


@pytest.mark.parametrize(
    ("value", "unit", "text"),
    [
        (4.7e-6, "F", "4.7 uF"),
        (0.02, "ohm", "20 mohm"),
        (12.6, "V", "12.6 V"),
        (0.0, "W", "0 W"),
        (1e3, "ohm", "1 kohm"),
    ],
)
def test_a_quantity_is_written_with_its_prefix(value, unit, text):
    assert ratings.si(value, unit) == text


def test_the_value_a_capacitor_keeps_is_read_between_the_maker_s_points_and_not_past_them():
    kept = [[0, 1.0], [5, 0.5], [10, 0.2]]
    assert ratings.kept_at(kept, 0) == 1.0
    assert ratings.kept_at(kept, 2.5) == pytest.approx(0.75)
    assert ratings.kept_at(kept, 10) == pytest.approx(0.2)
    assert ratings.kept_at(kept, 10.5) is None


# ---------------------------------------------------------------- files the command does not take
#
# A file that is wrong in 1 place is refused, and the message names the file, the place and the fault.
# Each case is a file that holds, then the 1 change that breaks it.


def refused(read, path: Path, data: object) -> str:
    path.write_text(data if isinstance(data, str) else json.dumps(data), encoding="utf-8")
    with pytest.raises(ratings.Refusal) as caught:
        read(path)
    return str(caught.value)


def changed(base: dict, *path: object, to: object = None, drop: bool = False) -> dict:
    """A deep copy of `base` with the value at `path` set to `to`, or taken out."""
    out = json.loads(json.dumps(base))
    at = out
    for key in path[:-1]:
        at = at[key]
    if drop:
        del at[path[-1]]
    else:
        at[path[-1]] = to
    return out


STATED = {
    "pack": "nasa-eee-inst-002",
    "ambient": {"max": 60, "source": "the enclosure's limit"},
    "nets": {"V5": {"volts": [4.5, 5.5], "source": "the supply"}, "GND": {"volts": [0, 0], "source": "J1"}},
    "parts": {"C1": {"volts": 5.5, "source": "the rail"}, "R1.1": {"amps": 0.01, "source": "the load"}},
    "accepted": [{"part": "C1", "rule": "x", "why": "y", "by": "the owner's decision of 2026-11-17"}],
}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ("{", "ratings.json: not JSON: "),
        (changed(STATED, "nets", drop=True), "ratings.json: `nets` is missing"),
        (
            changed(STATED, "speed", to=1),
            "ratings.json: `speed` is no key here; the keys are pack, nets, ambient, parts, accepted",
        ),
        (changed(STATED, "nets", "V5", "source", drop=True), "ratings.json: nets: V5: `source` is missing"),
        (
            changed(STATED, "nets", "V5", "source", to=" "),
            "ratings.json: nets: V5: source: text is asked, and there is none",
        ),
        (
            changed(STATED, "nets", "V9", to={"volts": [1, 2], "source": "s"}),
            "ratings.json: nets: V9: no net of the schematic has this name",
        ),
        (
            changed(STATED, "nets", "V5", "volts", to=[5.5, 4.5]),
            "ratings.json: nets: V5: volts: the span's first number, 5.5, is above its second, 4.5",
        ),
        (
            changed(STATED, "nets", "V5", "volts", to=[4.5, "5"]),
            "ratings.json: nets: V5: volts: '5' is no number",
        ),
        (changed(STATED, "ambient", "source", drop=True), "ratings.json: ambient: `source` is missing"),
        (
            changed(STATED, "parts", "R9", to={"amps": 1, "source": "s"}),
            "ratings.json: parts: R9: the schematic has no such part",
        ),
        (
            changed(STATED, "parts", "C1.7", to={"amps": 1, "source": "s"}),
            "ratings.json: parts: C1.7: the schematic has no such part and pin",
        ),
        (
            changed(STATED, "parts", "C1", to={"source": "s"}),
            "ratings.json: parts: C1: `amps` or `volts` is asked",
        ),
        (
            changed(STATED, "parts", "R1.1", to={"volts": 3, "source": "s"}),
            "ratings.json: parts: R1.1: volts: the voltage across a part of 2 pins is asked",
        ),
        (changed(STATED, "parts", "C1", "volts", to=-1), "ratings.json: parts: C1: volts: -1 is under 0"),
        (
            changed(STATED, "accepted", 0, "by", to="me"),
            "ratings.json: accepted: entry 1: by: write `the owner's decision of YYYY-MM-DD`",
        ),
        (changed(STATED, "accepted", to={}), "ratings.json: accepted: a list is asked"),
    ],
)
def test_a_project_file_that_is_wrong_in_1_place_is_refused_with_the_place(tmp_path, data, message):
    net = board(C1={"1": "V5", "2": "GND"}, R1={"1": "V5", "2": "GND"})
    path = tmp_path / "ratings.json"
    path.write_text(json.dumps(STATED), encoding="utf-8")
    held = ratings.read_project(path, net)
    assert (held.ambient, held.nets["V5"], held.volts, held.amps) == (
        60.0,
        (4.5, 5.5),
        {"C1": 5.5},
        {"R1.1": 0.01},
    )
    assert refused(lambda p: ratings.read_project(p, net), path, data).startswith(message)


def test_a_declared_net_is_found_with_or_without_the_slash_of_its_sheet(tmp_path):
    net = board(C1={"1": "/SENSE", "2": "GND"})
    path = tmp_path / "ratings.json"
    for name in ("SENSE", "/SENSE"):
        path.write_text(
            json.dumps({"pack": "p", "nets": {name: {"volts": [0, 1], "source": "s"}}}), encoding="utf-8"
        )
        assert ratings.read_project(path, net).nets == {"/SENSE": (0.0, 1.0)}


CARD = {
    "pack": "t",
    "document": dict.fromkeys(ratings.DOCUMENT_KEYS, "x"),
    "rules": [
        {
            "id": "a",
            "stress": "capacitor.voltage",
            "kinds": ["capacitor"],
            "max": 0.5,
            "where": "table 1, page 2",
            "above": {"temperature": "ambient", "celsius": 70, "falls_to": 0.3, "at": 110},
        }
    ],
}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (changed(CARD, "document", "sha256", drop=True), "pack.json: document: `sha256` is missing"),
        (changed(CARD, "rules", to=[]), "pack.json: rules: a list of rules is asked"),
        (
            changed(CARD, "rules", 0, "stress", to="capacitor.heat"),
            "pack.json: rule 1: `capacitor.heat` is no stress the command computes; they are capacitor.volt",
        ),
        (changed(CARD, "rules", 0, "max", to=1.2), "pack.json: rule 1: max: 1.2 is over 1"),
        (
            changed(CARD, "rules", 0, "where", to=""),
            "pack.json: rule 1: where: text is asked, and there is none",
        ),
        (changed(CARD, "rules", 0, "kinds", to=[]), "pack.json: rule 1: kinds: a list of names is asked"),
        (
            changed(CARD, "rules", 0, "above", "at", to=70),
            "pack.json: rule 1: above: `at` is not above `celsius`",
        ),
        (
            changed(CARD, "rules", 0, "above", "temperature", to="junction"),
            "pack.json: rule 1: above: temperature is `ambient` or `case`",
        ),
        (
            {**CARD, "rules": [CARD["rules"][0], CARD["rules"][0]]},
            "pack.json: rule 2: the id `a` stands 2 times",
        ),
    ],
)
def test_a_pack_that_is_wrong_in_1_place_is_refused_with_the_place(tmp_path, data, message):
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(CARD), encoding="utf-8")
    assert ratings.read_pack(path).rule("capacitor.voltage", "capacitor.ceramic").max == 0.5
    assert refused(ratings.read_pack, path, data).startswith(message)


@pytest.mark.parametrize("name", ["nasa-eee-inst-002", "ecss-q-st-30-11c-rev2"])
def test_a_shipped_pack_loads_and_each_of_its_limits_names_a_table_and_a_page(name):
    pack = ratings.read_pack(PACKS / f"{name}.json")
    assert pack.name == name
    assert re.fullmatch(r"[0-9a-f]{64}", pack.document["sha256"])
    assert pack.document["url"].startswith("https://")
    assert {rule.stress for rule in pack.rules} == set(ratings.STRESSES)
    for rule in pack.rules:
        assert "table" in rule.where and "page" in rule.where, rule.id
        assert 0 < rule.max < 1, rule.id


RESISTOR = {"kind": "resistor", "mpn": "R-1", "tolerance": 0.01, "watts": 0.1, "volts": 50, "source": READ}
SWITCHING = {"topology": "buck", "hertz": [1e6, 2e6], "page": 7}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"parts": []}, "x.json: parts: a list of parts is asked"),
        (changed(RESISTOR, "kind", to="relay"), "x.json: kind: one of resistor, capacitor.ceramic,"),
        (
            changed(RESISTOR, "symbol", to="Device:R"),
            "x.json: exactly 1 of mpn, mpns, match, symbol says which parts the entry speaks of",
        ),
        (
            changed(RESISTOR, "footprint", to="*0603*"),
            "x.json: `footprint` narrows a `symbol`, and the entry names none",
        ),
        (changed(RESISTOR, "source", "read", drop=True), "x.json: source: `read` is missing"),
        (changed(RESISTOR, "watts", drop=True), "x.json: `watts` is missing"),
        (changed(RESISTOR, "tolerance", to=1.5), "x.json: tolerance: 1.5 is over 0.99"),
        (changed(RESISTOR, "note", to=""), "x.json: note: text is asked, and there is none"),
        (
            ceramic("C-1", 16, kept=[[0, 1.0], [5, 0.5], [5, 0.4]]),
            "x.json: kept: the volts rise from pair to pair",
        ),
        (
            ceramic("C-1", 16, kept=[[0, 1.0]]),
            "x.json: kept: 2 or more pairs [volts, fraction of the value kept]",
        ),
        (changed(MCU_FACTS, "pins", 0, "role", to="power"), "x.json: pin 1: role: one of supply, ground,"),
        (
            changed(MCU_FACTS, "pins", 0, "page", drop=True),
            "x.json: pin VDD: `page` is missing: the datasheet's page the numbers stand on",
        ),
        (
            changed(MCU_FACTS, "pins", 0, "page", to="4"),
            "x.json: pin VDD: page: a page number is asked, or a list of them",
        ),
        (changed(MCU_FACTS, "pins", 0, "abs", to=[4.0]), "x.json: pin VDD: abs: a span of 2 limits is asked"),
        (
            changed(MCU_FACTS, "pins", 2, "abs", to=[-0.3, {"pin": "VCC", "plus": 0.3}]),
            "x.json: pin PA0: abs: `VCC` is no pin name of this part",
        ),
        (
            '{"kind": "link", "mpn": "A", "mpn": "B", "source": '
            '{"document": "d", "read": "r", "second_reader": "no"}}',
            "x.json: `mpn` stands 2 times",
        ),
        (
            changed(MCU_FACTS, "pins", 2, "swing", to=["VSS", "VCC"]),
            "x.json: pin PA0: swing: 2 of this part's pin names are asked, of VDD, VSS, PA0",
        ),
        (changed(MCU_FACTS, "family", to="logic"), "x.json: family: one of digital, linear,"),
        (
            changed(MCU_FACTS, "switching", to=SWITCHING),
            "x.json: switching: the family is digital, not regulator.switching",
        ),
        (
            changed(SWITCHER, "switching", "topology", to="boost"),
            "x.json: switching: topology: `buck` is the 1 topology the command computes",
        ),
        (
            changed(SWITCHER, "switching", "hertz", to=[0, 1e6]),
            "x.json: switching: hertz: the least frequency",
        ),
        (
            changed(SWITCHER, "switching", "efficiency", to=0),
            "x.json: switching: efficiency: a share above 0",
        ),
        (
            changed(SWITCHER, "needs", 0, "inductor", "to", to="OUT"),
            "x.json: needs 1: inductor: to: `OUT` is no pin name of this part",
        ),
        (
            changed(ADJUSTABLE, "pins", 2, "volts", to=[3.2, 3.4]),
            "x.json: pin OUT: `volts`, or `set_by` with the name of its feedback pin: 1 of the 2",
        ),
        (
            changed(ADJUSTABLE, "pins", 2, "set_by", to="IN"),
            "x.json: pin OUT: set_by: `IN` is no pin of role feedback",
        ),
        (
            changed(ADJUSTABLE, "pins", 2, "amps", to=0.3),
            "x.json: pin OUT: `amps` stands on the feedback pin FB",
        ),
        (
            changed(ADJUSTABLE, "pins", 3, "from", to="GND"),
            "x.json: pin FB: from: `GND` is no pin of role supply",
        ),
        (
            changed(ADJUSTABLE, "pins", 1, to=pin("BIAS", ["2"], "supply", abs=[-0.3, 6.5])),
            "x.json: pin FB: `from` is missing: which of IN, BIAS its current comes from",
        ),
    ],
)
def test_facts_that_are_wrong_in_1_place_are_refused_with_the_place(tmp_path, data, message):
    for holds in (RESISTOR, MCU_FACTS, SWITCHER, ADJUSTABLE):
        (tmp_path / "x.json").write_text(json.dumps(holds), encoding="utf-8")
        assert len(ratings.read_facts(tmp_path)) == 1
    assert refused(lambda p: ratings.read_facts(p.parent), tmp_path / "x.json", data).startswith(message)


def test_facts_that_do_not_fit_the_part_s_symbol_are_refused(tmp_path):
    """A pin the facts leave out, a pin number the symbol lacks, and a resistor's facts on 3 pins."""
    three = {"1": ("V33", "VDD", "power_in"), "2": ("GND", "VSS", "power_in"), "3": ("SIG", "PA0", "output")}
    short = changed(MCU_FACTS, "pins", to=MCU_FACTS["pins"][:2])
    net, mpns = circuit(U1=("MCU", "MCU-1", three))
    with pytest.raises(ratings.Refusal, match=r"U1 \(\) has pin 3, and the facts name no such pin"):
        ratings.judge(net, mpns, library(tmp_path, short), project(RAILS), NASA)
    net, mpns = circuit(U1=("MCU", "MCU-1", {"1": three["1"], "2": three["2"]}))
    with pytest.raises(ratings.Refusal, match=r"pin 3 is no pin of U1"):
        ratings.judge(net, mpns, library(tmp_path, MCU_FACTS), project(RAILS), NASA)
    net, mpns = circuit(R1=("10k", "R-1", {"1": "V33", "2": "GND", "3": "GND"}))
    with pytest.raises(ratings.Refusal, match=r"R1 is a resistor and has 3 pins, not 2"):
        ratings.judge(net, mpns, library(tmp_path, RESISTOR), project(RAILS), NASA)


def test_the_entry_that_names_a_part_most_closely_is_the_one_that_speaks_of_it(tmp_path):
    """Its part number, before a pattern of it, before its symbol; a symbol's entry can ask a footprint."""
    by_number = ceramic("C-16V", 16)
    by_pattern = {**ceramic("", 10), "match": "C-*"}
    by_symbol = {**ceramic("", 6.3), "symbol": "Device:C", "footprint": "*0603*"}
    for entry_ in (by_pattern, by_symbol):
        del entry_["mpn"]
    facts = library(tmp_path, by_symbol, by_pattern, by_number)
    part = ratings.Part("C1", "1u", "Capacitor_SMD:C_0603_1608Metric", "Device:C", True)
    assert ratings.facts_of(facts, part, "C-16V").data["volts"] == 16
    assert ratings.facts_of(facts, part, "C-25V").data["volts"] == 10
    assert ratings.facts_of(facts, part, "").data["volts"] == 6.3
    part.footprint = "Capacitor_SMD:C_0805_2012Metric"
    assert ratings.facts_of(facts, part, "") is None


def test_a_symbol_s_entry_speaks_of_no_part_that_has_a_part_number(tmp_path):
    """C1 is a 6.3 V part by its number, and no entry names that number. The entry of the symbol
    Device:C, a 50 V part, is another part's: C1 has no facts, and is not held to 50 V."""
    by_symbol = {**ceramic("", 50), "symbol": "Device:C"}
    del by_symbol["mpn"]
    facts = library(tmp_path, by_symbol)
    part = ratings.Part("C1", "10u", "Capacitor_SMD:C_0603_1608Metric", "Device:C", True)
    assert ratings.facts_of(facts, part, "CL10A106MQ8NNNC") is None
    assert ratings.facts_of(facts, part, "").data["volts"] == 50


def test_2_entries_that_name_a_part_equally_closely_are_refused(tmp_path):
    facts = library(tmp_path, ceramic("C-16V", 16), ceramic("C-16V", 25))
    part = ratings.Part("C1", "1u", "", "Device:C", True)
    with pytest.raises(ratings.Refusal) as caught:
        ratings.facts_of(facts, part, "C-16V")
    assert str(caught.value) == "facts.json: part 1 and facts.json: part 2 both speak of C1 (C-16V)"


def test_a_part_s_number_is_that_of_the_first_row_with_its_value_and_its_footprint():
    """As `sources` and `procure` match a line: a row with no footprint is an item off the board, and a
    row nothing is bought for names no part."""
    net = ratings.read_netlist(NETLIST)
    row = types.SimpleNamespace
    rows = [
        row(value="10k", footprint="", buys=True, mpn="OFF-BOARD"),
        row(value="10k", footprint="Resistor_SMD:R_0603_1608Metric", buys=True, mpn="R-FIRST"),
        row(value="10k", footprint="Resistor_SMD:R_0603_1608Metric", buys=True, mpn="R-SECOND"),
        row(value="100n", footprint="Capacitor_SMD:C_0603_1608Metric", buys=False, mpn="COPPER"),
    ]
    assert ratings.part_numbers(net, rows) == {"R1": "R-FIRST", "R2": "R-FIRST"}


def test_an_entry_to_fill_holds_the_part_s_pins_and_nothing_a_reader_did_not_read():
    net = ratings.read_netlist(NETLIST)
    entry_ = ratings.skeleton(net, "U1", "MCU-1")
    assert (entry_["kind"], entry_["mpn"]) == ("", "MCU-1")
    assert entry_["source"] == {
        "document": "",
        "revision": "",
        "url": "",
        "sha256": "",
        "read": "",
        "second_reader": "no",
    }
    assert {"numbers": ["3"], "name": "PA0", "role": "", "page": 0} in entry_["pins"]
    passive = ratings.skeleton(net, "R1", "")
    assert passive["symbol"] == "Device:R" and "pins" not in passive and "mpn" not in passive


def test_a_pack_is_found_by_its_name_or_by_a_path_from_the_project(tmp_path):
    assert ratings.find_pack("nasa-eee-inst-002", tmp_path, PACKS) == PACKS / "nasa-eee-inst-002.json"
    (tmp_path / "house.json").write_text("{}", encoding="utf-8")
    assert ratings.find_pack("house.json", tmp_path, PACKS) == tmp_path / "house.json"
    with pytest.raises(ratings.Refusal) as caught:
        ratings.find_pack("mil-hdbk", tmp_path, PACKS)
    assert str(caught.value) == (
        "ratings.json: pack: `mil-hdbk` is no pack; the workcenter holds "
        "ecss-q-st-30-11c-rev2, nasa-eee-inst-002"
    )


def test_the_facts_are_the_nearest_library_at_or_above_a_folder(tmp_path):
    project_dir = tmp_path / "boards" / "v1"
    project_dir.mkdir(parents=True)
    assert ratings.find_facts(project_dir) is None or tmp_path not in ratings.find_facts(project_dir).parents
    (tmp_path / "library" / "facts").mkdir(parents=True)
    assert ratings.find_facts(project_dir) == tmp_path / "library" / "facts"
    (tmp_path / "boards" / "library" / "facts").mkdir(parents=True)
    assert ratings.find_facts(project_dir) == tmp_path / "boards" / "library" / "facts"
