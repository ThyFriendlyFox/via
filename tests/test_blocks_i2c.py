"""The I2C bus block (tools/blocks_i2c.py): the 2 pull-ups of a bus, worked out by the equations of TI
SLVA689A from the bus voltage, the speed and the bus capacitance, and every device on the bus held to its
facts.

The sums of the fixtures, by hand. The bus is 3.3 V less and plus 5 %: 3.135 V to 3.465 V, over 2 V, so
table 2-1 (SLVA689A page 3) gives VOL 0.4 V at 3 mA in fast mode, with tr 300 ns and Cb 400 pF at the most.
The stocked resistors are Vishay CRCW0603 of 1 % (tests/boards/library/facts/passives.json).

    equation 1    RP(min) = (3.465 - 0.4) / 0.003 = 3.065 / 0.003 = 1021.667 ohm
    TCA9534 SDA   its sink, 3 mA at VOL 0.4 V (SCPS197D page 6): the same 1021.667 ohm; SCL is an input
    equation 6    at 100 pF: RP(max) = 300e-9 / (0.8473 x 100e-12) = 300e-9 / 8.473e-11 = 3540.659 ohm
                  at 200 pF: 300e-9 / 1.6946e-10 = 1770.329 ohm
    the stock     4.7k, 2.2k, 1.5k, 1k in this order; a resistor is taken when it holds both bounds at
                  its tolerance: R x 0.99 >= RP(min) and R x 1.01 <= RP(max)
                  at 100 pF: 4.7k x 1.01 = 4747 > 3540.659; 2.2k: 2222 <= 3540.659 and 2178 >= 1021.667
                  at 200 pF: 2.2k x 1.01 = 2222 > 1770.329; 1.5k: 1515 <= 1770.329 and 1485 >= 1021.667
    equation 5    the deck's rise, 0.8473 x R x Cb: 2.2k and 100 pF, 184.54 ns to 188.27 ns at 1 %;
                  1.5k and 200 pF, 251.65 ns to 256.73 ns; both under 300 ns
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from conftest import engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import blocks  # noqa: E402
import kicadgen  # noqa: E402
import ratings  # noqa: E402

CITES = {
    "ti-slva689a": "section 2, equations 1, 5 and 6 and table 2-1, page 3; section 3, page 4",
    "ti-scps197d": "pages 5, 6 and 7: the pins' ratings and the SDA sink",
}
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
FACTS = BOARDS / "library" / "facts"

needs_libs = pytest.mark.skipif(
    not (kicadgen.SYMBOL_DIR / "Device.kicad_sym").is_file(),
    reason="KiCad symbol libraries are not installed",
)
needs_kicad = engine(
    pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
)

R_0603 = "Resistor_SMD:R_0603_1608Metric"
SOIC16 = "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm"
HEADER_2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"


def res(value: str, code: str) -> blocks.Stock:
    return blocks.Stock("Vishay", f"CRCW0603{code}FKEA", value, R_0603)


R47, R22, R15, R10 = res("4.7k", "4K70"), res("2.2k", "2K20"), res("1.5k", "1K50"), res("1k", "1K00")
R33 = res("3.3k", "3K30")
STOCK = [R47, R22, R15, R10]
NOTE = "TI SLVA689A"
EQ1 = f"{NOTE}, equation 1, page 3"
EQ6 = f"{NOTE}, equation 6, page 3"
TABLE = f"{NOTE}, section 2, table 2-1, Parametrics from I2C specifications, the rows tr and Cb, page 3"
LOW = f"{NOTE}, section 2, table 2-1, the row VOL at 3 mA current sink, VCC > 2 V: 0.4 V in each mode, page 3"
CHOICE = (
    f"{NOTE}, section 3, page 4: any resistor between RP(min) and RP(max); a smaller one is faster, a larger "
    "one draws less power"
)
TCA = "TCA9534 datasheet, SCPS197D, September 2014, revised October 2017, p 5, 6 and 7"


def design(vcc: str = "+3V3", connector: bool = True, u1: dict | None = None) -> kicadgen.Design:
    """J1 brings the bus's supply, J2 the 2 lines from a controller off the board; U1 is a TCA9534. `u1`
    replaces U1's nets."""
    d = kicadgen.Design(
        name="t", namespace=uuid.UUID(int=5), outline=(100.0, 100.0, 140.0, 125.0), sheet="A4"
    )
    d.power_nets = {"+3V3": "+3V3", "GND": "GND"}
    d.add("J1", "Connector_Generic:Conn_01x02", "3V3 IN", HEADER_2, sch_at=(50.8, 76.2),
          pcb_at=(104.0, 104.0), nets={"1": "+3V3", "2": "GND"})  # fmt: skip
    if connector:
        d.add("J2", "Connector_Generic:Conn_01x02", "I2C", HEADER_2, sch_at=(50.8, 101.6),
              pcb_at=(104.0, 118.0), nets={"1": "SDA", "2": "SCL"})  # fmt: skip
    nets = {"1": "GND", "2": "GND", "3": "GND", "8": "GND", "14": "SCL", "15": "SDA", "16": vcc}
    d.add("U1", "Interface_Expansion:TCA9534", "TCA9534", SOIC16, sch_at=(127.0, 88.9), pcb_at=(124.0, 112.0),
          nets=nets if u1 is None else u1)  # fmt: skip
    return d


U1_NETS = {"1": "GND", "2": "GND", "3": "GND", "8": "GND", "14": "SCL", "15": "SDA", "16": "+3V3"}


def i2c(
    d=None,
    *,
    stock=STOCK,
    volts=(3.135, 3.465),
    speed="fast",
    facts=FACTS,
    devices=None,
    nets=("SDA", "SCL", "+3V3"),
    **kwargs,
):
    d = d or design()
    block = blocks.i2c(
        d,
        volts=volts,
        speed=speed,
        nets=nets,
        devices={"U1": "TCA9534DWR"} if devices is None else devices,
        stock=stock,
        facts=facts,
        sch_at=(88.9, 63.5),
        pcb_at=(112.0, 104.0),
        **kwargs,
    )
    return d, block


def refused(*args, **kwargs) -> str:
    with pytest.raises(blocks.Refused) as exc:
        i2c(*args, **kwargs)
    return str(exc.value)


MADE_UP = {"document": "no datasheet: a part made up for tests/test_blocks_i2c.py", "read": "2026-11-17"}


def facts_with(tmp_path: Path, *parts: dict) -> Path:
    """The fixtures' facts folder and, beside it, parts made up for 1 test."""
    folder = tmp_path / "facts"
    shutil.copytree(FACTS, folder)
    entries = [{**part, "source": {**MADE_UP, "second_reader": "no"}} for part in parts]
    (folder / "zz-made-up.json").write_text(json.dumps({"parts": entries}), encoding="utf-8")
    return folder


def tca_like(sda: dict, mpn: str = "FIXTURE-I2C") -> dict:
    """A made-up part with the TCA9534's pins, its SDA pin replaced."""
    data = json.loads((FACTS / "ti-tca9534.json").read_text(encoding="utf-8"))
    pins = [sda if p["name"] == "SDA" else p for p in data["pins"]]
    return {"kind": "ic", "mpn": mpn, "family": "digital", "pins": pins}


SDA = {"numbers": ["15"], "name": "SDA", "role": "open_drain", "abs": [-0.5, 6], "swing": ["GND"], "page": 1}


# The facts a bus pin may hold: its capacitance and its sink, read by item 1's reader.


def test_a_pin_may_hold_its_capacitance_and_its_sink(tmp_path):
    """The TCA9534's facts hold SDA's 9.5 pF and its 3 mA at 0.4 V (SCPS197D pages 6 and 7)."""
    found = ratings.read_facts(FACTS)
    tca = next(f for f in found if "TCA9534DWR" in f.data.get("mpns", ()))
    sda = next(p for p in tca.data["pins"] if p["name"] == "SDA")
    assert (sda["farads"], sda["sink"]) == (9.5e-12, {"amps": 0.003, "volts": 0.4})


@pytest.mark.parametrize(
    ("sink", "says"),
    [
        ({"amps": 0.003}, "pin SDA: sink: "),
        ({"amps": 0, "volts": 0.4}, "pin SDA: sink: amps"),
        ({"amps": 0.003, "volts": -0.1}, "pin SDA: sink: volts"),
    ],
)
def test_a_sink_is_a_current_over_0_at_a_voltage_of_0_or_more(tmp_path, sink, says):
    """A sink with no voltage, a current of 0 or a voltage under 0 is refused where it stands."""
    facts = facts_with(tmp_path, tca_like({**SDA, "sink": sink}))
    with pytest.raises(ratings.Refusal, match=says):
        ratings.read_facts(facts)


def test_a_pin_capacitance_of_0_is_refused(tmp_path):
    facts = facts_with(tmp_path, tca_like({**SDA, "farads": 0}))
    with pytest.raises(ratings.Refusal, match="pin SDA: farads"):
        ratings.read_facts(facts)


# The block.


@needs_libs
def test_100_pf_in_fast_mode_takes_the_first_stocked_resistor_between_the_bounds():
    """At 100 pF RP(max) is 3540.659 ohm: 4.7k at +1 % is over it, 2.2k holds both bounds (the sums above).
    The 2 pull-ups go from +3V3 to SDA and to SCL."""
    d, block = i2c(farads=100e-12)
    parts = {p.ref: (p.value, dict(p.nets)) for p in d.parts if p.ref in ("R1", "R2")}
    assert parts == {"R1": ("2.2k", {"1": "+3V3", "2": "SDA"}), "R2": ("2.2k", {"1": "+3V3", "2": "SCL"})}
    assert block.sums[0] == f"R1, R2: RP(min) = (3.465 V - 400 mV) / 3 mA = 1.02 kohm [{EQ1}; {LOW}]"
    assert f"R1, R2: RP(max) = 300 ns / (0.8473 x 100 pF) = 3.54 kohm [{EQ6}; {TABLE}]" in block.sums
    assert (
        "R1, R2: 2.2k, 1 %: 2.18 kohm to 2.22 kohm, within 1.02 kohm to 3.54 kohm; passed over: 4.7k, "
        f"4.75 kohm at +1 %, over RP(max) [{CHOICE}]"
    ) in block.sums


@needs_libs
def test_twice_the_bus_capacitance_takes_another_resistor():
    """At 200 pF RP(max) is 1770.329 ohm: 2.2k at +1 %, 2222 ohm, is over it; 1.5k is taken."""
    d, block = i2c(farads=200e-12)
    assert {p.ref: p.value for p in d.parts if p.ref.startswith("R")} == {"R1": "1.5k", "R2": "1.5k"}
    assert f"R1, R2: RP(max) = 300 ns / (0.8473 x 200 pF) = 1.77 kohm [{EQ6}; {TABLE}]" in block.sums


@needs_libs
def test_no_stocked_resistor_between_the_bounds_is_1_line_with_the_equations():
    """At 300 pF RP(max) = 300e-9 / (0.8473 x 300e-12) = 1180.220 ohm. 4.7k, 2.2k and 1.5k at +1 % (4747,
    2222, 1515.0000000000002 ohm, which rounds to 1.52 kohm) are over it; 1k at -1 % (989.9999999999999 ohm,
    990) is under 1021.667."""
    assert refused(farads=300e-12) == (
        "i2c R1 R2: no stocked resistor lies between RP(min) = 1.02 kohm and RP(max) = 1.18 kohm at its "
        "tolerance: 4.7k, 4.75 kohm at +1 %, over RP(max); 2.2k, 2.22 kohm at +1 %, over RP(max); 1.5k, "
        f"1.52 kohm at +1 %, over RP(max); 1k, 990 ohm at -1 %, under RP(min) [{EQ1}; {EQ6}; {CHOICE}]"
    )


@needs_libs
def test_bounds_that_cross_are_refused_with_both_equations():
    """Fast mode plus at 550 pF: RP(max) = 120e-9 / (0.8473 x 550e-12) = 120e-9 / 4.66015e-10 = 257.502 ohm,
    under RP(min), 1021.667 ohm: no resistor can lie between."""
    assert refused(farads=550e-12, speed="fast-plus") == (
        "i2c R1 R2: RP(max) = 120 ns / (0.8473 x 550 pF) = 258 ohm is under RP(min) = 1.02 kohm: no resistor "
        f"lies between [{EQ1}; {EQ6}; {LOW}; {TABLE}]"
    )


@needs_libs
def test_a_bus_capacitance_over_the_speeds_limit_is_refused():
    """450 pF is over the 400 pF of table 2-1 for fast mode."""
    assert refused(farads=450e-12) == (f"i2c R1 R2: Cb of 450 pF is over the 400 pF of fast mode [{TABLE}]")


@needs_libs
def test_an_unknown_speed_is_refused():
    assert refused(farads=100e-12, speed="high") == (
        f"i2c R1 R2: speed `high` is none of standard, fast, fast-plus [{TABLE}]"
    )


@needs_libs
def test_at_2_v_or_less_the_low_level_is_a_share_of_vcc_at_2_ma():
    """At 1.8 V table 2-1 gives VOL 0.2 x 1.8 = 0.36 V at 2 mA: RP(min) = (1.8 - 0.36) / 0.002 = 720 ohm.
    The TCA9534's SDA sinks 3 mA at 0.4 V: (1.8 - 0.4) / 0.003 = 466.7 ohm, under it."""
    _, block = i2c(farads=100e-12, volts=(1.8, 1.8))
    assert block.sums[0] == (
        "R1, R2: RP(min) = (1.8 V - 360 mV) / 2 mA = 720 ohm [TI SLVA689A, equation 1, page 3; TI SLVA689A, "
        "section 2, table 2-1, the row VOL at 2 mA current sink, VCC <= 2 V: 0.2 x VCC in fast mode and fast "
        "mode plus, none in standard mode, page 3]"
    )


@needs_libs
def test_standard_mode_at_2_v_or_less_is_refused():
    """Table 2-1 gives no VOL for standard mode at VCC <= 2 V."""
    assert refused(farads=100e-12, volts=(1.8, 1.8), speed="standard") == (
        "i2c R1 R2: table 2-1 gives no VOL for standard mode at 1.8 V [TI SLVA689A, section 2, table 2-1, "
        "the row VOL at 2 mA current sink, VCC <= 2 V: 0.2 x VCC in fast mode and fast mode plus, none in "
        "standard mode, page 3]"
    )


@needs_libs
def test_a_device_that_sinks_less_raises_rp_min_and_another_resistor_is_taken(tmp_path):
    """A made-up device sinks 1.5 mA at 0.4 V: (3.465 - 0.4) / 0.0015 = 2043.333 ohm. With 1.5k and 2.2k
    stocked, 1.5k at -1 % (1485 ohm) is under it, and 2.2k at -1 % (2178 ohm) holds it."""
    facts = facts_with(tmp_path, tca_like({**SDA, "sink": {"amps": 0.0015, "volts": 0.4}}))
    d, block = i2c(farads=100e-12, stock=[R15, R22], facts=facts, devices={"U1": "FIXTURE-I2C"})
    assert {p.ref: p.value for p in d.parts if p.ref.startswith("R")} == {"R1": "2.2k", "R2": "2.2k"}
    assert (
        "U1 SDA: RP(min) = (3.465 V - 400 mV) / 1.5 mA = 2.04 kohm, its sink [no datasheet: a part made up "
        f"for tests/test_blocks_i2c.py, p 1; {EQ1}]"
    ) in block.sums


@needs_libs
def test_the_same_bus_with_the_tca9534_alone_takes_1_5k():
    """With 1.5k first in the stock and the TCA9534's 3 mA, 1.5k holds both bounds at 100 pF."""
    d, _ = i2c(farads=100e-12, stock=[R15, R22])
    assert {p.ref: p.value for p in d.parts if p.ref.startswith("R")} == {"R1": "1.5k", "R2": "1.5k"}


@needs_libs
def test_an_open_drain_pin_with_no_sink_in_its_facts_is_refused(tmp_path):
    """The block cannot hold the pull-up to a sink its facts do not give."""
    facts = facts_with(tmp_path, tca_like(SDA))
    assert refused(farads=100e-12, facts=facts, devices={"U1": "FIXTURE-I2C"}) == (
        "i2c U1 SDA: its facts give no sink (the current it sinks at its low voltage): the pull-up cannot be "
        "held to it [no datasheet: a part made up for tests/test_blocks_i2c.py, p 1]"
    )


@needs_libs
def test_a_push_pull_output_on_the_bus_is_refused(tmp_path):
    """An I2C line is driven by open drains; an output that drives it high fights the others."""
    out = {**SDA, "role": "output", "swing": ["GND", "VCC"]}
    facts = facts_with(tmp_path, tca_like(out))
    assert refused(farads=100e-12, facts=facts, devices={"U1": "FIXTURE-I2C"}) == (
        "i2c U1 SDA: its role is output: a line of the bus takes an open drain, an io or an input "
        "[no datasheet: a part made up for tests/test_blocks_i2c.py, p 1]"
    )


@needs_libs
def test_a_bus_over_a_pins_absolute_maximum_is_refused():
    """6.2 V is over the TCA9534's 6 V for VI (SCPS197D page 5). RP(min) at 6.2 V is 1933 ohm; the check
    of the pin comes first."""
    assert refused(farads=100e-12, volts=(5.8, 6.2)) == (
        f"i2c U1 SDA: the bus reaches 6.2 V, over its absolute maximum, 6 V [{TCA}]"
    )


@needs_libs
def test_an_operating_limit_that_follows_a_pin_on_another_net_is_not_judged_by_the_block():
    """U1's VCC on +5V: SDA's limit of VCC + 0 is not the bus's to judge; the sum says so."""
    _, block = i2c(design(vcc="+5V"), farads=100e-12)
    assert (
        "U1 SDA: its operating limit follows VCC, on +5V, not on the bus's +3V3: not judged here; "
        "`workcenter ratings` judges it"
    ) in block.sums


@needs_libs
def test_a_part_on_the_bus_with_no_part_number_is_refused():
    assert refused(farads=100e-12, devices={}) == (
        "i2c U1: on SDA, and `devices` names no part number for it: the block judges each device on the bus "
        "by its facts"
    )


@needs_libs
def test_a_device_with_no_facts_is_refused():
    assert refused(farads=100e-12, devices={"U1": "TCA9534XYZ"}) == (
        f"i2c U1: {FACTS} holds no facts of TCA9534XYZ"
    )


@needs_libs
def test_a_stated_capacitance_under_the_devices_own_pins_is_refused():
    """5 pF is under the 9.5 pF of the TCA9534's SDA alone (SCPS197D page 7)."""
    assert refused(farads=5e-12) == (
        "i2c R1 R2: the stated Cb, 5 pF, is under the 9.5 pF the devices' pins give on SDA: U1 9.5 pF "
        f"[{TCA}]"
    )


@needs_libs
def test_the_bus_capacitance_is_summed_from_the_pins_and_the_track():
    """No connector on the bus, 50 mm of track at a made-up 0.1 pF/mm: SDA 9.5 + 5 = 14.5 pF, SCL 8 + 5 =
    13 pF; the greater is the bus's. RP(max) = 300e-9 / (0.8473 x 14.5e-12) = 24418.3 ohm: 4.7k is taken."""
    d, block = i2c(design(connector=False), track=(50, 0.1e-12, "made up for this test"))
    assert {p.ref: p.value for p in d.parts if p.ref.startswith("R")} == {"R1": "4.7k", "R2": "4.7k"}
    assert f"SDA: Cb = U1 9.5 pF + 50 mm x 0.1 pF/mm (made up for this test) = 14.5 pF [{TCA}]" in block.sums
    scl = TCA.replace("p 5, 6 and 7", "p 5 and 7")  # the pages of SCL's facts
    assert f"SCL: Cb = U1 8 pF + 50 mm x 0.1 pF/mm (made up for this test) = 13 pF [{scl}]" in block.sums
    assert f"R1, R2: RP(max) = 300 ns / (0.8473 x 14.5 pF) = 24.4 kohm [{EQ6}; {TABLE}]" in block.sums


@needs_libs
def test_a_connector_on_the_bus_cannot_be_summed():
    """What stands behind J2 is in no facts: the bus capacitance must be stated."""
    assert refused(track=(50, 0.1e-12, "made up")) == (
        "i2c J2: a connector on SDA: what stands behind it is in no sum; state the bus capacitance, farads="
    )


@needs_libs
def test_neither_a_capacitance_nor_a_track_is_refused():
    assert (
        refused() == "i2c R1 R2: the bus capacitance is asked: farads=, or track=(mm, farads per mm, source)"
    )


@needs_libs
def test_the_block_hands_its_parts_to_ratings_and_states_no_span_for_the_lines():
    """R1 and R2 are 1 row of parts.csv. The block states no span for SDA and SCL: `workcenter ratings`
    works them out from the pull-ups and the open drains, with the supply held where each pin's limit is
    tightest. A stated span of 0 V to 3.465 V would stand apart from VCC's 3.135 V, and fail SDA's
    limit of VCC, which the pull-up to the same +3V3 never passes. It states the span of the supply it pulls
    up to: `volts`, which its sums and its deck use."""
    _, block = i2c(farads=100e-12)
    assert block.ratings == {
        "nets": {
            "+3V3": {
                "volts": [3.135, 3.465],
                "source": "the bus voltage of the I2C block R1 R2: i2c(volts=(3.135, 3.465))",
            }
        }
    }
    assert [(r.value, r.mpn, r.qty) for r in block.rows] == [("2.2k", "CRCW06032K20FKEA", 2)]


# What a review found the block let through (findings I1 to I8).


@needs_libs
def test_a_pull_up_to_a_net_that_holds_a_devices_ground_is_refused():
    """I1: nets=(SDA, SCL, GND). R1 and R2 would hold both lines at 0 V; U1's GND, pin 8, is on GND."""
    assert refused(farads=100e-12, nets=("SDA", "SCL", "GND")) == (
        "i2c R1 R2: the pull-ups go to GND, and U1 GND, pin 8, a ground, is on it: the bus is pulled up to "
        "its supply, not to a ground [TCA9534 datasheet, SCPS197D, September 2014, revised October 2017]"
    )


@needs_libs
def test_ratings_json_refuses_a_net_the_block_and_the_design_state_with_2_spans():
    """I1: the block says +3V3 spans 3.135 V to 3.465 V; a design that says 0 V to 0 V for the same net
    has 2 spans for 1 net, and ratings would judge only the last."""
    _, block = i2c(farads=100e-12)
    own = {"nets": {"+3V3": {"volts": [0, 0], "source": "the reference"}}}
    with pytest.raises(blocks.Refused) as exc:
        blocks.ratings_json("nasa-eee-inst-002", block.ratings, own)
    assert str(exc.value) == (
        "ratings.json +3V3: 3.135 V to 3.465 V by the bus voltage of the I2C block R1 R2: i2c(volts=(3.135, "
        "3.465)), and 0 V to 0 V by the reference: 1 net holds 1 span"
    )


def test_ratings_json_takes_the_same_span_stated_twice():
    """The fixtures' own +3V3 is the block's 3.135 V to 3.465 V again: no refusal, the last source stands."""
    a = {"nets": {"+3V3": {"volts": [3.135, 3.465], "source": "a"}}}
    b = {"nets": {"+3V3": {"volts": [3.135, 3.465], "source": "b"}}}
    assert json.loads(blocks.ratings_json("p", a, b))["nets"]["+3V3"]["source"] == "b"


SCL = TCA.replace("p 5, 6 and 7", "p 5 and 7")  # the pages of SCL's facts
MADE = "no datasheet: a part made up for tests/test_blocks_i2c.py, p 1"


@needs_libs
def test_a_device_whose_sda_and_scl_are_crossed_is_refused():
    """I2: U1's SCL, pin 14, on the net SDA and its SDA, pin 15, on SCL. SCL comes first in its facts."""
    d = design(u1={**U1_NETS, "14": "SDA", "15": "SCL"})
    assert (
        refused(d, farads=100e-12)
        == f"i2c U1 SCL: pin 14 is on SDA, not on SCL, the bus's clock line [{SCL}]"
    )


@needs_libs
def test_a_device_whose_scl_is_left_open_is_refused():
    """I3: U1's SDA is on the bus and its SCL, pin 14, on no net: the device is not judged on SCL."""
    nets = {k: v for k, v in U1_NETS.items() if k != "14"}
    assert refused(design(u1=nets), farads=100e-12) == (
        f"i2c U1 SCL: pin 14 is on no net, not on SCL, the bus's clock line [{SCL}]"
    )


@needs_libs
@pytest.mark.parametrize("nets", [("SDA", "SDA", "+3V3"), ("SDA", "SCL", "SCL")])
def test_sda_scl_and_the_supply_are_3_nets(nets):
    """I3: nets=(SDA, SDA, +3V3) put both pull-ups on SDA and left SCL with none."""
    assert refused(farads=100e-12, nets=nets) == (
        f"i2c R1 R2: nets={nets!r}: SDA, SCL and the supply they pull up to are 3 different nets"
    )


ON_SDA = {**SDA, "sink": {"amps": 0.003, "volts": 0.4}}


@needs_libs
def test_in_track_mode_a_pin_with_no_capacitance_is_refused(tmp_path):
    """I4: a made-up part whose SDA gives no farads: the track's sum would count it as 0 pF."""
    facts = facts_with(tmp_path, tca_like(ON_SDA))
    assert refused(design(connector=False), track=(50, 0.1e-12, "made up"), facts=facts,
                   devices={"U1": "FIXTURE-I2C"}) == (
        "i2c U1 SDA: its facts give no capacitance: Cb cannot be summed; state the bus capacitance, farads= "
        "[no datasheet: a part made up for tests/test_blocks_i2c.py, p 1]"
    )  # fmt: skip


@needs_libs
def test_with_a_stated_capacitance_a_pin_with_none_is_said_not_judged(tmp_path):
    """I4: with farads= the pin's own capacitance is in the stated Cb; the sums say it was not summed."""
    facts = facts_with(tmp_path, tca_like(ON_SDA))
    _, block = i2c(farads=100e-12, facts=facts, devices={"U1": "FIXTURE-I2C"})
    assert (
        "U1 SDA: its facts give no capacitance: not in the devices' sum on SDA; not judged against the "
        "stated Cb [no datasheet: a part made up for tests/test_blocks_i2c.py, p 1]"
    ) in block.sums


@needs_libs
@pytest.mark.parametrize(
    ("kwargs", "says"),
    [
        ({"farads": 0.0}, "farads=0.0: the bus capacitance is a finite number over 0"),
        ({"farads": -1e-12}, "farads=-1e-12: the bus capacitance is a finite number over 0"),
        ({"farads": float("nan")}, "farads=nan: the bus capacitance is a finite number over 0"),
        (
            {"track": (-3000, 0.1e-12, "made up")},
            "track=(-3000, 1e-13, 'made up'): mm and farads per mm are each a finite number over 0",
        ),
        (
            {"track": (50, 0.0, "made up")},
            "track=(50, 0.0, 'made up'): mm and farads per mm are each a finite number over 0",
        ),
        ({"farads": 1e-10, "volts": (0.0, 3.465)}, "volts=(0.0, 3.465): each a finite number over 0"),
        (
            {"farads": 1e-10, "volts": (3.135, float("inf"))},
            "volts=(3.135, inf): each a finite number over 0",
        ),
    ],
)
def test_each_number_of_the_spec_is_finite_and_over_0(kwargs, says):
    """I5: farads=0 ended in a division by 0 in equation 6; a negative track gave Cb of 0 the same way."""
    d = design(connector="track" not in kwargs)
    assert refused(d, **kwargs) == f"i2c R1 R2: {says}"


@needs_libs
def test_a_part_named_in_devices_whose_facts_hold_no_pins_is_refused():
    """I6: a designer's 10k on SDA named as a device: its facts are a resistor's, with no pins to judge."""
    d = design()
    d.add("R3", "Device:R", "10k", R_0603, sch_at=(60.0, 60.0), pcb_at=(110.0, 110.0),
          nets={"1": "+3V3", "2": "SDA"})  # fmt: skip
    assert refused(d, farads=100e-12, devices={"U1": "TCA9534DWR", "R3": "CRCW060310K0FKEA"}) == (
        "i2c R3: the facts of CRCW060310K0FKEA give no pins (a resistor): the block judges a device on the "
        "bus by its pins [Vishay D/CRCW e3 datasheet, document 20035, 14-Apr-2026]"
    )


@needs_libs
def test_volts_written_greatest_first_is_refused():
    """I7: volts=(5.5, 3.135) judged the sink and the pins at 3.135 V; (6.5, 3.135) let 6.5 V past the
    TCA9534's 6 V."""
    assert refused(farads=100e-12, volts=(5.5, 3.135)) == (
        "i2c R1 R2: volts=(5.5, 3.135) is written greatest first: volts is (least, greatest), and the block "
        "judges the pins and the sinks at the greatest"
    )


@needs_libs
def test_a_bus_over_a_pins_numeric_operating_limit_is_refused(tmp_path):
    """I8: a made-up SDA that works to 3.3 V and stands 6 V: the bus's 3.465 V is over 3.3 V."""
    facts = facts_with(tmp_path, tca_like({**ON_SDA, "operating": [-0.5, 3.3]}))
    assert refused(farads=100e-12, facts=facts, devices={"U1": "FIXTURE-I2C"}) == (
        f"i2c U1 SDA: the bus reaches 3.46 V, over its operating limit, 3.3 V [{MADE}]"
    )


@needs_libs
def test_a_pin_whose_least_limit_is_over_0_v_is_refused(tmp_path):
    """I8: a made-up SDA that stands 0.5 V to 6 V: an open drain pulls the line to 0 V, under 0.5 V."""
    facts = facts_with(tmp_path, tca_like({**ON_SDA, "abs": [0.5, 6]}))
    assert refused(farads=100e-12, facts=facts, devices={"U1": "FIXTURE-I2C"}) == (
        f"i2c U1 SDA: the bus falls to 0 V, under its absolute least, 500 mV [{MADE}]"
    )


@needs_libs
def test_the_deck_holds_the_rise_to_table_2_1():
    """sim/i2c.cir charges 100 pF through 2.2k from 0 V to 3.465 V and measures from 0.3 x 3.465 = 1.0395 V
    to 0.7 x 3.465 = 2.4255 V; the bound is fast mode's 300 ns."""
    _, block = i2c(farads=100e-12)
    deck = block.files["sim/i2c.cir"]
    for line in ("V1 vdd 0 3.465", "R1 vdd sda 2.2k", "CBUS sda 0 100p", ".ic v(sda)=0"):
        assert line in deck.splitlines()
    assert "meas tran tr trig v(sda) val=1.0395 rise=1 targ v(sda) val=2.4255 rise=1" in deck
    expect = json.loads(block.files["sim/i2c.expect.json"])
    assert expect["tr"]["max"] == 300e-9
    corners = json.loads(block.files["sim/corners.json"])
    assert corners["tolerance"]["R"] == 0.01


def netlist_of(d: kicadgen.Design) -> ratings.Netlist:
    """The design's parts and nets as the SIM gate reads them from kicad-cli's netlist, without KiCad."""
    comps = "".join(
        f'<comp ref="{p.ref}"><value>{p.value}</value>'
        f'<libsource lib="{p.symbol.lib}" part="{p.symbol.name}"/></comp>'
        for p in d.parts
    )
    nets: dict[str, list[str]] = {}
    for p in d.parts:
        for pin, net in p.nets.items():
            nets.setdefault(net, []).append(f'<node ref="{p.ref}" pin="{pin}" pintype="passive"/>')
    body = "".join(f'<net name="/{name}">{"".join(nodes)}</net>' for name, nodes in nets.items())
    return ratings.read_netlist(f"<export><components>{comps}</components><nets>{body}</nets></export>")


@needs_libs
@pytest.mark.parametrize("farads", [100e-12, 200e-12])
def test_the_deck_answers_the_rise_time_the_sim_gate_asks_of_the_bus(farads):
    """The SIM gate asks each I2C line with a pull-up for a deck (tools/simneeds.py). The block's deck
    says `* deck: i2c-rise SDA SCL` and runs R1 at the schematic's value; R2 has that value too, so R1
    stands for it. Without the line, the block's fixtures failed `gates --strict`."""
    import simneeds

    d, block = i2c(farads=farads)
    deck = block.files["sim/i2c.cir"]
    assert "* deck: i2c-rise SDA SCL" in deck.splitlines()
    assert simneeds.needs(netlist_of(d), [], {"i2c": deck}) == []
    asked = simneeds.needs(netlist_of(d), [], {})
    assert [n.names for n in asked] == [("SCL", "SDA")]


@needs_libs
def test_a_ref_the_design_holds_already_is_refused():
    """R1 is the design's own 10k: the block names its pull-ups with other refs or not at all."""
    d = design()
    d.add("R1", "Device:R", "10k", R_0603, sch_at=(88.9, 50.8), pcb_at=(130.0, 104.0),
          nets={"1": "+3V3", "2": "SDA"})  # fmt: skip
    with pytest.raises(blocks.Refused) as exc:
        i2c(d, farads=100e-12)
    assert str(exc.value) == "i2c R1: the design holds R1 already; name the block's pull-ups with refs="


class Crossed(kicadgen.Design):
    """A design whose add() puts SCL's pull-up on SDA: what the block built is not what it chose."""

    def add(self, ref, lib_id, value, footprint, sch_at, nets, **kwargs):
        if ref == "R2":
            nets = {"1": "+3V3", "2": "SDA"}
        return super().add(ref, lib_id, value, footprint, sch_at, nets, **kwargs)


@needs_libs
def test_the_block_reads_back_what_it_built_before_it_returns():
    """The block reads R1 and R2 back from the design: R2 between +3V3 and SDA is refused."""
    d = design()
    d.__class__ = Crossed
    with pytest.raises(blocks.Refused) as exc:
        i2c(d, farads=100e-12)
    assert str(exc.value) == (
        "i2c R2: the design holds 2.2k from +3V3 to SDA; the block chose 2.2k from +3V3 to SCL"
    )


def test_every_number_of_the_rules_names_where_it_stands():
    """Each equation has its page, each speed's numbers the table they stand in, each low level its row."""
    rules = json.loads((ROOT / "rules" / "blocks" / "i2c.json").read_text(encoding="utf-8"))
    note = rules["note"]
    assert all(isinstance(e["page"], int) for e in note["equations"].values())
    assert "page 3" in note["speeds_where"]
    assert all("page " in row["where"] for row in note["low"])
    assert all("page " in note[k]["where"] for k in ("rise_factor", "rise_from", "rise_to"))


FIXTURES = {"pass-block-i2c": "2.2k", "pass-block-i2c-2x": "1.5k"}


@needs_kicad
@needs_libs
@pytest.mark.parametrize("name", FIXTURES)
def test_each_fixture_is_what_its_design_file_writes_and_passes_ratings_strict(name, tmp_path):
    """`workcenter design` writes the committed schematic, project, ratings.json, parts.csv and deck; a
    strict `workcenter ratings` of the fixture passes, and R1 is the resistor the sums above take."""
    out = tmp_path / name
    made = subprocess.run(
        [sys.executable, str(CLI), "design", str(BOARDS / name / "design.py"), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert made.returncode == 0, made.stdout + made.stderr
    for rel in (
        "node.kicad_sch",
        "node.kicad_pro",
        "ratings.json",
        "parts.csv",
        "sim/i2c.cir",
        "sim/i2c.expect.json",
        "sim/corners.json",
    ):
        assert (out / rel).read_bytes() == (BOARDS / name / rel).read_bytes(), rel
    assert f"R1 vdd sda {FIXTURES[name]}" in (out / "sim" / "i2c.cir").read_text(encoding="utf-8")
    run = subprocess.run(
        [sys.executable, str(CLI), "ratings", str(BOARDS / name), "--out", str(tmp_path / "r"), "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr


# The rise of each fixture's deck at its resistor's 2 ends, by equation 5 (the sums above), and the bound.
RISES = {"pass-block-i2c": (184.54e-9, 188.27e-9), "pass-block-i2c-2x": (251.65e-9, 256.73e-9)}


def rated_copy(name: str, tmp_path: Path) -> Path:
    """A copy of the fixture beside the fixtures' shared library, and its `ratings` run. `gates --strict`
    reads that record: a project with a ratings.json is GREEN under --strict only when it is held."""
    boards = tmp_path / "boards"
    boards.mkdir()
    (boards / "library").symlink_to(BOARDS / "library")
    proj = boards / name
    shutil.copytree(BOARDS / name, proj, ignore=shutil.ignore_patterns("build"))
    rated = subprocess.run(
        [sys.executable, str(CLI), "ratings", str(proj)], capture_output=True, text=True, check=False
    )
    assert rated.returncode == 0, rated.stdout + rated.stderr
    return proj


@needs_kicad
@pytest.mark.parametrize("name", FIXTURES)
def test_each_fixture_is_routed_and_its_gates_are_green(name, tmp_path):
    """ERC, DRC (0 unconnected: the router finished), SIM and EXPORT pass, and a strict run too, once a
    `ratings` run holds the fixture's ratings: the deck's rise at its corners is equation 5's, under fast
    mode's 300 ns."""
    proj = rated_copy(name, tmp_path)
    run = subprocess.run(
        [sys.executable, str(CLI), "--json", "gates", str(proj), "--out", str(tmp_path), "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert "RATINGS held: build/ratings/report.json says RATINGS HELD" in run.stderr.splitlines(), run.stderr
    records = {r["gate"]: r for r in json.loads(run.stdout)}
    assert [records[g]["status"] for g in ("erc", "drc", "sim", "export")] == ["pass"] * 4
    assert records["drc"]["summary"] == (
        "0 errors, 0 warnings (0 unconnected, 0 parity), legend (no fab named: held to the least of the 4 "
        "fabs Via knows (height pcbway-standard, stroke oshpark-2layer)): 0 fail, 0 not judged"
    )
    runs = json.loads((tmp_path / "sim" / "corners" / "i2c" / "runs.json").read_text(encoding="utf-8"))
    rises = [r["measures"]["tr"] for r in runs]
    assert (min(rises), max(rises)) == pytest.approx(RISES[name], rel=1e-2)
    assert records["sim"]["details"]["decks"]["i2c"]["checks"]["tr"]["max"] == 300e-9
