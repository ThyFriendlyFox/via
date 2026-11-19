"""The charger block (tools/blocks_charger.py): a BQ21040 linear charger for 1 lithium cell with a BQ29700
protector and its 2 CSD17313Q2 transistors, added to a design in 1 call, every value from the 2 datasheets
(rules/blocks/charger.json) and the parts' facts (tests/boards/library/facts).

The sums of the fixture, by hand. The input is 4.75 V to 5.25 V; the cell's limits are made up: 2.5 V to
4.3 V, 0.5 A in charge, 3 A in discharge; the system draws 1 A; the ambient is 0 C to 40 C.

    KISET, 150 mA     the row of 60 mA to 1000 mA: 490, 540, 590 A ohm (SLUSCE2D section 7.5, page 5)
    equation 1        RISET = 540 / 0.15 = 3600 ohm; the stock holds 3.6k, 1 %
                      typical 540 / 3600 = 0.15 A; least 490 / (3600 x 1.01) = 490 / 3636 = 0.134763 A;
                      greatest 590 / (3600 x 0.99) = 590 / 3564 = 0.165544 A, under the cell's 0.5 A
    equation 8        the least cell voltage in fast charge: the larger of the cell's 2.5 V and VLOWV's least,
                      2.4 V (page 5): 2.5 V. P = (5.25 - 2.5) x 0.165544 + 5.25 x 0.001 (ICC, page 5)
                      = 0.455246 + 0.00525 = 0.460496 W
    limit             the least of SLUSCE2D's 125 C (7.3, page 4) and the ECSS pack's limit on a junction
                      rated 150 C: the least of 110 C and 150 - 40 = 110 C (ECSS-Q-ST-30-11C Rev.2, clause
                      6.21.2, table 6-21, page 57): 110 C, the SIM gate's own limit
    junction          TJ = 40 + 130.8 x 0.460496 = 40 + 60.2329 = 100.233 C, under 110 C
    at 0.3 A          RISET = 540 / 0.3 = 1800 ohm: 1.8k; greatest 590 / (1800 x 0.99) = 590 / 1782
                      = 0.331089 A; P = 2.75 x 0.331089 + 0.00525 = 0.915744 W;
                      TJ = 40 + 130.8 x 0.915744 = 159.779 C, over 110 C. The most: (110 - 40) / 130.8
                      = 0.535168 W, (0.535168 - 0.00525) / 2.75 = 0.192698 A
    C1                CL10A106KP8NNN at 5.25 V keeps, between (5.2344, 0.26773) and (5.35535, 0.26029),
                      0.26773 - 0.00744 x 0.0156 / 0.12095 = 0.266770: 10 uF x 0.9 x 0.266770 = 2.40093 uF,
                      within 1 uF to 10 uF (SLUSCE2D pin table, page 3; figure 10, page 17)
    C2                at 4.3 V, between (4.279525, 0.33833) and (4.3748, 0.33003): 0.33833 - 0.0083 x 0.020475
                      / 0.095275 = 0.336546: 10 uF x 0.9 x 0.336546 = 3.02892 uF
    OVP               4.275 V -/+ 20 mV (SLUSBU9I table 4, page 3; 6.6, page 6): 4.255 V to 4.295 V; over
                      the charger's 4.23 V (VOUT(REG) MAX, page 5), within the cell's 4.3 V
    UVP               2.8 V - 50 mV = 2.75 V, over the cell's 2.5 V
    transistors       2 x 42 mohm = 84 mohm (SLPS260E section 5.1, VGS = 3 V, MAX, page 3); OCD's least
                      100 - 15 = 85 mV; OCC's least 85 mV. The load: 0.084 x 1 = 84 mV, under 85 mV. The
                      charge: 0.084 x 0.165544 = 13.906 mV. At the typical 31 mohm the discharge trips at
                      0.115 / 0.062 = 1.854839 A, under the cell's 3 A
    not judged        4 items, handed to `workcenter ratings` in ratings.json: the 2 transistors' drop at
                      heat and at a gate under 3 V (SLUSBU9I section 9.2.2, page 20, asks it derated; SLPS260E
                      gives no MAX above 25 C or under VGS = 3 V); the trip under the typical on-resistance;
                      VUVP's tolerance, stated at 25 C only, at 0 C to 40 C; the value C3 keeps
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests" / "boards"))
sys.dont_write_bytecode = True

import blocks  # noqa: E402
import kicadgen  # noqa: E402

CITES = {
    "ti-slusce2": "equations 1 and 8; sections 7.3 and 7.5, pages 4 and 5; the pin table, page 3",
    "ti-slusbu9": "table 4, page 3; sections 6.3 and 6.6, pages 5 and 6; section 9.2.2, page 20",
    "ti-slps260": "section 5.1, RDS(on) at VGS = 3 V, page 3",
    "ti-spra953d": "section 1.1, equation 1, page 2: TJ = TA + RthetaJA x P",
    "ecss-q-st-30-11c-rev2": "clause 6.21.2, table 6-21, page 57: a junction's limit",
}
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
FACTS = BOARDS / "library" / "facts"
RULES = ROOT / "rules" / "blocks" / "charger.json"

needs_libs = pytest.mark.skipif(
    not (kicadgen.SYMBOL_DIR / "Device.kicad_sym").is_file(),
    reason="KiCad symbol libraries are not installed",
)
needs_kicad = engine(
    pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
)

DS = "bq21040 datasheet, SLUSCE2D"
PS = "BQ297xx datasheet, SLUSBU9I"
CELL_SOURCE = (
    "the fixture's cell, made up for tests/boards: 2.5 V to 4.3 V, 0.5 A in charge, 3 A in discharge"
)
EQ1 = (
    f"TI SLUSCE2D, equation 1, page 13; {DS}, section 7.5, Electrical Characteristics, KISET, its 3 rows of "
    "current (60 mA to 1000 mA, 25 mA to 60 mA, 10 mA to 25 mA), MIN, TYP and MAX, page 5"
)
HEAT = (
    f"TI SLUSCE2D, equation 8, page 23; {DS}, section 7.5, VLOWV, MIN and MAX, page 5; section 8.1, page 8: "
    f"under VLOWV the charger gives 20 % of the fast charge current; {DS}, section 7.5, ICC, MAX, page 5; "
    f"{DS}, section 7.4, Thermal Information, RthetaJA of the DBV package, page 4; {DS}, section 7.3, "
    "Recommended Operating Conditions, TJ, MAX, page 4; TJ = TA + RthetaJA x P, TI SPRA953D, section 1.1, "
    "equation 1, page 2"
)
CAPS = (
    f"{DS}, section 6, Pin Functions, OUT and VIN: bypass capacitors of 1 uF to 10 uF, page 3; section 9.2, "
    "figure 10, 1 uF on IN and on OUT, page 17; section 9.2.2.2, the values of the application diagram are "
    "recommended, page 18"
)
OVP = (
    f"{PS}, section 4, Device Comparison Table, BQ29700, OVP, page 3; {PS}, section 6.6, VOVP, TA = 0 C to "
    "60 C, -20 mV to 20 mV, page 6"
)
UVP = (
    f"{PS}, section 4, Device Comparison Table, BQ29700, UVP, page 3; {PS}, section 6.6, VUVP, TA = 25 C, "
    "-50 mV to 50 mV, page 6"
)
FETS = (
    "TI SLUSBU9I, section 9.2.2, page 19: the total on-resistance of the 2 FETs times the greatest discharge "
    "current stays under VOCD; TI SLUSBU9I, section 9.2.2, page 20: the total on-resistance times the "
    f"greatest charge current stays under the OCC threshold; {PS}, section 6.6, VOCD, TA = -40 C to 85 C, "
    f"-15 mV to 15 mV, page 6; {PS}, section 6.6, VOCC, TA = -40 C to 85 C, -15 mV to 15 mV, page 6"
)
RDS = "CSD17313Q2 datasheet, SLPS260E, section 5.1, RDS(on) at VGS = 3 V, TYP and MAX, at 25 C, page 3"
LIMIT = (
    "the limit is the least of 125 C and ecss-q-st-30-11c-rev2's 110 C, the least of 110 C and 150 C - 40 C "
    "(clause 6.21.2, table 6-21, page 57), on a junction rated 150 C (junction_max of bq21040 datasheet, "
    "SLUSCE2D, April 2016, revised January 2019, p 3 and 4)"
)
GATE = f"{PS}, section 6.5, VOH of COUT and DOUT at BAT = 3.8 V, MIN, page 5"
DERATE = (
    "TI SLUSBU9I, section 9.2.2, page 20: the total on-resistance takes the worst case of the FETs' "
    "on-resistance, its derating for temperature and the gate drive"
)
R_0603 = "Resistor_SMD:R_0603_1608Metric"
FILTER_C = f"{PS}, section 5.1.1, a 0.1 uF input capacitor on BAT, page 4; figure 9-1, page 19"


def block_charger():
    import block_charger as module  # tests/boards/block_charger.py, the fixtures' board

    return module


def charger(amps: float = 0.15, **kwargs):
    """The fixtures' block on a bare design, with any argument changed."""
    bc = block_charger()
    d = kicadgen.Design(
        name="t", namespace=uuid.UUID(int=7), outline=(100.0, 100.0, 140.0, 125.0), sheet="A4"
    )
    d.power_nets = {"+5V": "+5V", "+BATT": "+BATT", "GND": "GND"}
    args = {
        "ic": "BQ21040DBVR",
        "protector": "BQ29700DSER",
        "vin": (4.75, 5.25),
        "amps": amps,
        "cell": bc.CELL,
        "load": 1.0,
        "ambient": (0.0, 40.0),
        "pack": bc.PACK,
        "nets": {"in": "+5V", "bat": "+BATT", "gnd": "GND", "cell": "-BATT", "chg": "CHG"},
        "stock": bc.STOCK,
        "facts": FACTS,
        "sch_at": (50.8, 63.5),
        "pcb_at": (108.0, 104.0),
    } | kwargs
    block = blocks.charger(d, **args)
    return d, block


def refused(**kwargs) -> str:
    with pytest.raises(blocks.Refused) as exc:
        charger(**kwargs)
    return str(exc.value)


@needs_libs
def test_0_15_a_takes_3_6k_and_holds_every_sum():
    """The sums above: 3.6k, 135 mA to 166 mA, 0.4605 W, 100.2 C, 2.4 uF and 3.03 uF, the thresholds and
    the 2 transistors, each with its equation or clause and page."""
    d, block = charger()
    assert {p.ref: p.value for p in d.parts} == {
        "U1": "BQ21040",
        "R1": "3.6k",
        "R2": "10k",
        "C1": "10u 10V",
        "C2": "10u 10V",
        "U2": "BQ29700",
        "R3": "330",
        "C3": "100n 16V",
        "R4": "2.2k",
        "Q1": "CSD17313Q2",
        "Q2": "CSD17313Q2",
    }
    assert block.sums == [
        "R1: RISET = 540 AΩ / 150 mA = 3.6 kohm; the stock's nearest is 3.6k, which sets 150 mA, and 135 mA "
        f"to 166 mA with KISET of 490 to 590 AΩ and 1 % of resistor [{EQ1}]",
        f"U1: the charge current reaches 166 mA, the cell takes 500 mA [{CELL_SOURCE}]",
        "U1: P = (5.25 V - 2.5 V) x 166 mA + 5.25 V x 1 mA = 0.4605 W at 2.5 V, the cell's least; "
        f"TJ = 40 C + 130.8 C/W x 0.4605 W = 100.2 C, under 110 C [{HEAT}; {LIMIT}]",
        f"C1: 10u 10V, X5R, keeps 2.4 uF at 5.25 V less 10 %, within 1 uF to 10 uF [{CAPS}]",
        f"C2: 10u 10V, X5R, keeps 3.03 uF at 4.3 V less 10 %, within 1 uF to 10 uF [{CAPS}]",
        "U2: the overcharge threshold is 4.255 V to 4.295 V: over the charger's 4.23 V and within the cell's "
        f"4.3 V [{DS}, section 7.5, VOUT(REG), MIN and MAX, page 5; {OVP}; {CELL_SOURCE}]",
        "U2: the overdischarge threshold is 2.75 V at the least, over the cell's 2.5 V "
        f"[{UVP}; {CELL_SOURCE}]",
        "not judged: U2: the overdischarge threshold's tolerance: VUVP's tolerance, 50 mV, is stated at "
        f"TA = 25 C, and the ambient runs 0 C to 40 C [{UVP}]",
        "Q1, Q2: CSD17313Q2, 2 x 42 mohm = 84 mohm at 25 C and VGS = 3 V; the load gives 84 mV, under VOCD's "
        f"least, 85 mV; the charge gives 13.9 mV, under OCC's least, 85 mV [{FETS}; {RDS}]",
        "Q1, Q2: at the typical 31 mohm the discharge trips at 115 mV / 62 mohm = 1.85 A, under the cell's "
        f"3 A [{FETS}; {RDS}; {CELL_SOURCE}]",
        "not judged: Q1, Q2: the on-resistance at heat and at a low gate: the load's 84 mV and the charge's "
        "13.9 mV are worked out at RDS(on) MAX at 25 C and VGS = 3 V; CSD17313Q2's datasheet gives no MAX "
        "above 25 C or under VGS = 3 V, and BQ29700DSER drives the gate to 3.4 V at the least only at a cell "
        f"of 3.8 V, while the cell runs down to 2.75 V [{DERATE}; {RDS}; {GATE}; {UVP}]",
        "not judged: Q1, Q2: the discharge trip: under the typical 31 mohm, which CSD17313Q2's datasheet "
        f"does not bound from below, the discharge trips over 1.85 A [{FETS}; {RDS}; {CELL_SOURCE}]",
        f"C3: 100n 16V on BAT, rated 16 V, the 100 nF BQ29700DSER asks [{FILTER_C}]",
        "not judged: C3: the value it keeps: BQ29700DSER asks 100 nF on BAT and states no value it must keep "
        f"at the cell's voltage [{FILTER_C}]",
    ]


@needs_libs
def test_what_the_block_cannot_judge_goes_to_ratings_json():
    """Each `not judged` sum is an entry of ratings.json's `not_judged`, with its parts, so that
    `workcenter ratings` prints it. At 1.01 A the load gives 2 x 42 mohm x 1.01 A = 84.84 mV, under 85 mV:
    the block builds, and the transistors' drop at heat and at a low gate is not judged (SLUSBU9I
    section 9.2.2, page 20)."""
    _, block = charger(load=1.01)
    entries = block.ratings["not_judged"]
    assert {k: v["parts"] for k, v in entries.items()} == {
        "U2: the overdischarge threshold's tolerance": ["U2"],
        "Q1, Q2: the on-resistance at heat and at a low gate": ["Q1", "Q2"],
        "Q1, Q2: the discharge trip": ["Q1", "Q2"],
        "C3: the value it keeps": ["C3"],
    }
    said = [line for line in block.sums if line.startswith("not judged: ")]
    assert said == [f"not judged: {k}: {v['why']} [{v['source']}]" for k, v in entries.items()]
    assert entries["Q1, Q2: the on-resistance at heat and at a low gate"]["why"].startswith(
        "the load's 84.8 mV and the charge's 13.9 mV are worked out at RDS(on) MAX at 25 C and VGS = 3 V"
    )


@needs_libs
def test_an_ambient_over_the_overcharge_tolerances_range_leaves_it_not_judged():
    """VOVP's 20 mV holds for TA = 0 C to 60 C (SLUSBU9I section 6.6, page 6). At 0 C to 65 C, 0.1 A on a
    stocked 5.36k: 590 / (5360 x 0.99) = 0.111186 A, P = 2.75 x 0.111186 + 0.00525 = 0.311012 W,
    TJ = 65 + 130.8 x 0.311012 = 105.68 C, under 110 C: the block builds, and the threshold's tolerance
    is not judged."""
    stock = [*block_charger().STOCK, blocks.Stock("Vishay", "CRCW06035K36FKEA", "5.36k", R_0603)]
    _, block = charger(amps=0.1, stock=stock, ambient=(0.0, 65.0))
    assert block.ratings["not_judged"]["U2: the overcharge threshold's tolerance"] == {
        "parts": ["U2"],
        "why": "VOVP's tolerance, 20 mV, is stated at TA = 0 C to 60 C, and the ambient runs 0 C to 65 C",
        "source": OVP,
    }


@needs_libs
def test_an_ambient_outside_the_protectors_range_is_refused():
    """TAmb of the BQ29700 is -40 C to 85 C (SLUSBU9I section 6.3, page 5): -60 C is under it."""
    assert refused(ambient=(-60.0, 20.0)) == (
        f"charger U2: the ambient reaches -60 C, outside BQ29700DSER's -40 C to 85 C [{PS}, section 6.3, "
        "Recommended Operating Conditions, TAmb, page 5]"
    )


@needs_libs
def test_an_ambient_under_the_chargers_least_junction_is_refused():
    """TJ of the BQ21040 is 0 C to 125 C (SLUSCE2D section 7.3, page 4); the junction is never under the
    ambient, so an ambient of -30 C puts it under 0 C."""
    assert refused(ambient=(-30.0, 20.0)) == (
        "charger U1: the ambient reaches -30 C, and the junction is at least the ambient: under "
        f"BQ21040DBVR's least, 0 C [{DS}, section 7.3, Recommended Operating Conditions, TJ, MIN, page 4]"
    )


@pytest.mark.parametrize(
    ("kwargs", "line"),
    [
        ({"ambient": (40.0, 0.0)}, "charger U1: `ambient`'s first number, 40 C, is above its second, 0 C"),
        ({"vin": (6.45, 4.45)}, "charger U1: `vin`'s first number, 6.45 V, is above its second, 4.45 V"),
        ({"vin": 5.0}, "charger U1: `vin` is 5.0; it needs 2 numbers in V, the least first"),
        ({"load": -1.0}, "charger U1: a load of -1 A is asked; the transistors are held to a load over 0 A"),
        ({"load": 0.0}, "charger U1: a load of 0 A is asked; the transistors are held to a load over 0 A"),
        (
            {"nets": {"in": "+5V", "bat": "+BATT", "gnd": "GND", "cell": "-BATT"}},
            "charger U1: `nets` lacks chg; it needs in, bat, gnd, cell and chg",
        ),
    ],
)
@needs_libs
def test_an_argument_of_the_wrong_shape_is_refused_on_1_line(kwargs, line):
    """A reversed span would put the junction at the lower ambient (0 C + 130.8 x 0.9157 = 119.8 C at
    0.3 A) or the power at the lower input; a scalar, a missing net or a load of 0 A or less is no spec."""
    assert refused(**kwargs) == line


@needs_libs
def test_a_reversed_cell_is_refused():
    cell = replace(block_charger().CELL, volts=(4.3, 2.5))
    assert refused(cell=cell) == "charger U1: `cell.volts`'s first number, 4.3 V, is above its second, 2.5 V"


@needs_libs
def test_twice_the_current_is_refused_with_equation_8():
    """0.3 A takes 1.8k and reaches 0.331089 A: 0.915744 W, 159.779 C at 40 C, over the limit of 110 C,
    the ECSS pack's, which the SIM gate holds U1 to. The most at 40 C is 0.192698 A."""
    assert refused(amps=0.3) == (
        "charger U1: P = (5.25 V - 2.5 V) x 331 mA + 5.25 V x 1 mA = 0.9157 W at 2.5 V, the cell's least; "
        "TJ = 40 C + 130.8 C/W x 0.9157 W = 159.8 C, over 110 C: at 40 C the charge current reaches 193 mA "
        f"at the most [{HEAT}; {LIMIT}]"
    )


@needs_libs
def test_a_trip_over_the_cells_discharge_current_is_refused():
    """A cell that gives 1.5 A: at the typical 31 mohm the discharge trips at 0.115 / 0.062 = 1.854839 A,
    over it."""
    cell = replace(block_charger().CELL, discharge_amps=1.5)
    assert refused(cell=cell) == (
        "charger U2: the discharge trips at 1.85 A at the typical on-resistance, over the cell's 1.5 A "
        f"[{FETS}; {RDS}; {CELL_SOURCE}]"
    )


def rules_with(tmp_path: Path, change) -> Path:
    """rules/blocks/charger.json with 1 change, in tmp_path."""
    data = json.loads(RULES.read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "charger.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@needs_libs
def test_a_regulation_not_under_the_overcharge_threshold_is_refused(tmp_path):
    """A protector of 4.24 V: its least, 4.24 - 0.02 = 4.22 V, is under VOUT(REG)'s 4.23 V."""
    rules = rules_with(tmp_path, lambda d: d["protector"]["ovp"].update(value=4.24))
    assert refused(rules=rules) == (
        "charger U2: BQ21040DBVR regulates the cell at 4.23 V at the most, not under BQ29700DSER's least "
        f"overcharge threshold, 4.22 V [{DS}, section 7.5, VOUT(REG), MIN and MAX, page 5; {OVP}]"
    )


@needs_libs
def test_a_charge_drop_not_under_occ_is_refused(tmp_path):
    """A transistor of 300 mohm at the most and a load of 0.1 A: the load gives 0.6 x 0.1 = 60 mV, under
    85 mV, and the charge 0.6 x 0.165544 = 99.33 mV, not under OCC's 85 mV."""
    rules = rules_with(tmp_path, lambda d: d["transistors"][0]["rds_on"].update(value=[0.031, 0.3]))
    assert refused(rules=rules, load=0.1) == (
        "charger U2: no stocked transistor holds the load of 100 mA and the charge of 166 mA: CSD17313Q2: "
        f"2 x 300 mohm x 166 mA = 99.3 mV, not under 85 mV [{FETS}]"
    )


@needs_libs
def test_a_transistor_whose_gate_is_rated_under_the_cell_is_refused(tmp_path):
    """Facts that rate VGS at 4 V: under the cell's 4.3 V."""
    facts = tmp_path / "facts"
    shutil.copytree(FACTS, facts)
    path = facts / "ti-csd17313q2.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(data | {"volts_gate_source": 4}), encoding="utf-8")
    assert refused(facts=facts) == (
        "charger U2: no stocked transistor holds the load of 1 A and the charge of 166 mA: CSD17313Q2: "
        f"VGS 4 V, under the cell [{FETS}]"
    )


@needs_libs
def test_a_current_span_that_crosses_a_row_of_kiset_is_refused():
    """62 mA on a stocked 8.66k: 540 / 0.062 = 8709.7 ohm, nearest 8.66k; the span is
    490 / (8660 x 1.01) = 0.056022 A to 590 / (8660 x 0.99) = 0.068817 A, and 56 mA is in the row of 25 mA
    to 60 mA, not in that of 60 mA to 1000 mA."""
    stock = [*block_charger().STOCK, blocks.Stock("Vishay", "CRCW06038K66FKEA", "8.66k", R_0603)]
    assert refused(amps=0.062, stock=stock) == (
        "charger U1: 56 mA to 68.8 mA with KISET of 490 to 590 AΩ and 1 % of resistor crosses a row of "
        f"KISET: the span is not judged on 1 row [{EQ1}]"
    )


def stock_without(mpn: str) -> list:
    return [s for s in block_charger().STOCK if s.mpn != mpn]


@pytest.mark.parametrize(
    ("mpn", "line"),
    [
        (
            "CL10A106KP8NNN",
            "charger U1: no stocked capacitor of 1 uF to 10 uF rated for 5.25 V: VJ0603Y104KXJAC: 100 nF, "
            f"outside 1 uF to 10 uF [{CAPS}]",
        ),
        (
            "CRCW060310K0FKEA",
            f"charger U1: no stocked resistor of 10 kohm [{DS}, section 9.2.2.1.3, a fixed 10 kohm between "
            "TS and VSS disables the temperature sense, page 18]",
        ),
        (
            "VJ0603Y104KXJAC",
            "charger U2: no stocked capacitor of 100 nF to 100 nF rated for 4.3 V: CL10A106KP8NNN: 10 uF, "
            f"outside 100 nF to 100 nF [{FILTER_C}]",
        ),
        (
            "CRCW0603330RFKEA",
            f"charger U2: no stocked resistor of 330 ohm [{PS}, section 9.2, figure 9-1, 330 ohm from the "
            "cell to BAT, page 19; section 9.2.2, page 20]",
        ),
        (
            "CRCW06032K20FKEA",
            f"charger U2: no stocked resistor of 2.2 kohm [{PS}, section 5.1.3, a 2.2 kohm resistor between "
            "V- and Pack-, page 4; figure 9-1, page 19]",
        ),
    ],
)
@needs_libs
def test_a_part_the_stock_lacks_is_refused_with_its_value(mpn, line):
    assert refused(stock=stock_without(mpn)) == line


@needs_libs
def test_a_protector_the_rules_do_not_hold_is_refused():
    assert (
        refused(protector="BQ29700DSET")
        == "charger U2: BQ29700DSET is no protector of charger.json; it holds BQ29700DSER"
    )


@needs_libs
def test_a_current_over_the_ics_800_ma_is_refused():
    """0.9 A is over IOUT's 0.8 A (SLUSCE2D section 7.3, page 4; section 7.5, page 5)."""
    assert refused(amps=0.9) == (
        "charger U1: a charge current of 900 mA is outside BQ21040DBVR's 10 mA to 800 mA "
        f"[{DS}, section 7.5, IOUT(RANGE), 10 mA to 800 mA, page 5; section 7.3, IOUT at most 0.8 A, page 4]"
    )


@needs_libs
def test_a_resistor_outside_the_ics_range_is_refused():
    """40 mA is in KISET's row of 25 mA to 60 mA: 527 / 0.04 = 13175 ohm, over RISET's 10.8 kohm."""
    assert refused(amps=0.04) == (
        "charger U1: RISET = 527 AΩ / 40 mA = 13.2 kohm, outside 675 ohm to 10.8 kohm [TI SLUSCE2D, "
        f"equation 1, page 13; {DS}, section 7.3, Recommended Operating Conditions, RISET from 0.675 kohm to "
        "10.8 kohm, page 4]"
    )


@needs_libs
def test_an_input_over_the_ics_operating_range_is_refused():
    """6.5 V is over the 6.45 V where OVP restricts IN (SLUSCE2D section 7.3, page 4)."""
    assert refused(vin=(4.75, 6.5)) == (
        "charger U1: the input reaches 6.5 V, IN of BQ21040DBVR operates from 4.45 V to 6.45 V "
        f"[{DS}, section 7.3, Recommended Operating Conditions, IN operating voltage range, restricted by "
        "VDPM and VOVP, page 4]"
    )


@needs_libs
def test_a_charge_current_over_the_cells_is_refused():
    """A cell that takes 0.16 A: the greatest current, 0.165544 A, is over it."""
    cell = replace(block_charger().CELL, charge_amps=0.16)
    assert refused(cell=cell) == (
        f"charger U1: the charge current reaches 166 mA, over the cell's 160 mA [{EQ1}; {CELL_SOURCE}]"
    )


@needs_libs
def test_an_overcharge_threshold_over_the_cells_limit_is_refused():
    """A cell of 4.25 V at the most: 4.275 + 0.02 = 4.295 V is over it."""
    cell = replace(block_charger().CELL, volts=(2.5, 4.25))
    assert refused(cell=cell) == (
        "charger U2: the overcharge threshold reaches 4.275 V + 20 mV = 4.295 V, over the cell's 4.25 V "
        f"[{OVP}; {CELL_SOURCE}]"
    )


@needs_libs
def test_an_overdischarge_threshold_under_the_cells_least_is_refused():
    """A cell of 2.8 V at the least: 2.8 - 0.05 = 2.75 V is under it. Its dissipation at 2.8 V is less than
    at 2.5 V, and passes."""
    cell = replace(block_charger().CELL, volts=(2.8, 4.3))
    assert refused(cell=cell) == (
        "charger U2: the overdischarge threshold reaches 2.8 V - 50 mV = 2.75 V, under the cell's 2.8 V "
        f"[{UVP}; {CELL_SOURCE}]"
    )


@needs_libs
def test_a_load_over_what_the_transistors_hold_under_ocd_is_refused():
    """1.1 A through 84 mohm is 92.4 mV, over OCD's least, 85 mV: the protector would open in normal use."""
    assert refused(load=1.1) == (
        "charger U2: no stocked transistor holds the load of 1.1 A and the charge of 166 mA: CSD17313Q2: "
        f"2 x 42 mohm x 1.1 A = 92.4 mV, over 85 mV [{FETS}]"
    )


@needs_libs
def test_a_charger_the_rules_do_not_hold_is_refused():
    assert (
        refused(ic="BQ21040DBVT")
        == "charger U1: BQ21040DBVT is no charger of charger.json; it holds BQ21040DBVR"
    )


@needs_libs
def test_the_block_hands_its_nets_and_its_parts_to_ratings():
    """The input and the cell are nets with the call they came from; the cell's negative and the node
    between the transistors stand within OCD's greatest, 115 mV, of ground. 2 transistors are 1 row."""
    _, block = charger()
    nets = block.ratings["nets"]
    assert {k: v["volts"] for k, v in nets.items()} == {
        "+5V": [4.75, 5.25],
        "+BATT": [2.5, 4.3],
        "-BATT": [-0.115, 0.115],
        "U2_FETS": [-0.115, 0.115],
    }
    assert [(r.value, r.mpn, r.qty) for r in block.rows] == [
        ("BQ21040", "BQ21040DBVR", 1),
        ("3.6k", "CRCW06033K60FKEA", 1),
        ("10k", "CRCW060310K0FKEA", 1),
        ("10u 10V", "CL10A106KP8NNN", 2),
        ("BQ29700", "BQ29700DSER", 1),
        ("330", "CRCW0603330RFKEA", 1),
        ("100n 16V", "VJ0603Y104KXJAC", 1),
        ("2.2k", "CRCW06032K20FKEA", 1),
        ("CSD17313Q2", "CSD17313Q2", 2),
    ]


@needs_libs
def test_the_deck_runs_the_greatest_current_from_the_greatest_input():
    """The deck: 5.25 V in, the cell at 2.5 V, BU1 gives 590 times the current 1 V drives into R1 (3600 ohm),
    which is 0.163889 A as written. Its bounds: the cell's 0.5 A, and (110 - 40) / 130.8 = 0.535168 W, the
    power that keeps the junction at the limit the block and the SIM gate hold it to."""
    _, block = charger()
    deck = block.files["sim/charger.cir"].splitlines()
    for line in ("VIN in 0 DC 5.25", "R1 iset 0 3600", "BU1 in out I=-590*i(vset)", "VBAT out 0 DC 2.5"):
        assert line in deck
    expect = json.loads(block.files["sim/charger.expect.json"])
    assert (expect["ichg"]["max"], expect["p_u1"]["max"]) == (0.5, 0.535168)
    assert json.loads(block.files["sim/thermal.json"])["parts"]["U1"]["watts"] == "charger.p_u1"
    assert json.loads(block.files["sim/corners.json"])["tolerance"]["R"] == 0.01


def test_every_number_of_the_rules_names_where_it_stands():
    """No number of rules/blocks/charger.json stands without its clause and page."""
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    for part in (rules["charger"], rules["protector"], *rules["transistors"]):
        for key, entry in part.items():
            if isinstance(entry, dict) and ("value" in entry or "rows" in entry):
                assert "page " in entry["where"], (part["mpn"], key)
    assert all(isinstance(e["page"], int) for e in rules["charger"]["equations"].values())


def design(name: str, out: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), "design", str(BOARDS / name / "design.py"), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )


@needs_kicad
@needs_libs
def test_the_fixture_is_what_its_design_file_writes_and_ratings_names_what_is_not_judged(tmp_path):
    """`workcenter design` writes the committed schematic, project, ratings.json, parts.csv and deck.
    `workcenter ratings` of the fixture holds every rating and prints the block's 4 items not judged:
    RATINGS HELD, 4 NOT JUDGED, exit 0; with --strict the 4 fail the run, exit 1."""
    out = tmp_path / "pass-block-charger"
    made = design("pass-block-charger", out)
    assert made.returncode == 0, made.stdout + made.stderr
    for rel in (
        "node.kicad_sch",
        "node.kicad_pro",
        "ratings.json",
        "parts.csv",
        "library/sources.csv",
        "sim/charger.cir",
        "sim/charger.expect.json",
        "sim/corners.json",
        "sim/thermal.json",
    ):
        assert (out / rel).read_bytes() == (BOARDS / "pass-block-charger" / rel).read_bytes(), rel
    board = BOARDS / "pass-block-charger"

    def ratings(*flags: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(CLI), "ratings", str(board), "--out", str(tmp_path / "r"), *flags],
            capture_output=True,
            text=True,
            check=False,
        )

    run = ratings()
    assert run.returncode == 0, run.stdout + run.stderr
    text = run.stdout.splitlines()
    assert "0 fail, 0 accepted, 28 hold, 4 not judged" in run.stdout, run.stdout
    assert text[-1].startswith("RATINGS HELD, 4 NOT JUDGED: "), run.stdout
    for line in (
        "not judged U2: the overdischarge threshold's tolerance: VUVP's tolerance, 50 mV",
        "not judged Q1, Q2: the on-resistance at heat and at a low gate: the load's 84 mV",
        "not judged Q1, Q2: the discharge trip: under the typical 31 mohm",
        "not judged C3: the value it keeps: BQ29700DSER asks 100 nF on BAT",
    ):
        assert any(line in t for t in text), (line, run.stdout)
    assert ratings("--strict").returncode == 1


@needs_kicad
@needs_libs
def test_the_fixture_at_twice_the_current_is_refused_by_design_with_the_line(tmp_path):
    """`workcenter design` of refuse-block-charger-2x fails, writes no schematic and prints the refusal."""
    made = design("refuse-block-charger-2x", tmp_path / "out")
    assert made.returncode != 0
    assert "TJ = 40 C + 130.8 C/W x 0.9157 W = 159.8 C, over 110 C" in made.stdout + made.stderr
    assert not (tmp_path / "out" / "node.kicad_sch").exists()
    # Python's own __pycache__ of design.py aside, the folder holds the design file alone
    folder = BOARDS / "refuse-block-charger-2x"
    assert sorted(p.name for p in folder.iterdir() if p.name != "__pycache__") == ["design.py"]


@needs_kicad
def test_the_fixture_is_routed_and_its_gates_are_green(tmp_path):
    """ERC, DRC (0 unconnected: the router and the block's 2 tracks under each transistor finished), SIM
    and EXPORT pass. Over the corners of R1 (1 %) and the ambient (0 C and 40 C), by hand: the charge
    current runs from 590 / 3636 = 0.162266 A to 590 / 3564 = 0.165544 A, and U1's power from
    2.75 x 0.162266 + 0.00525 = 0.451482 W to 0.460496 W; its junction at 40 C reaches
    40 + 130.8 x 0.460496 = 100.233 C.

    The fixture's ratings are held with 4 not judged by design (the block hands them to `ratings`), so
    after a `ratings` run the gates say they are not held: a plain run is GREEN with that 1 warning, and a
    strict run ends `RED (ratings not held)`. The fixture is copied beside the fixtures' shared library,
    and the record is written into the copy."""
    boards = tmp_path / "boards"
    boards.mkdir()
    (boards / "library").symlink_to(BOARDS / "library")
    proj = boards / "pass-block-charger"
    shutil.copytree(BOARDS / "pass-block-charger", proj, ignore=shutil.ignore_patterns("build"))
    rated = subprocess.run(
        [sys.executable, str(CLI), "ratings", str(proj)], capture_output=True, text=True, check=False
    )
    assert rated.returncode == 0, rated.stdout + rated.stderr
    run = subprocess.run(
        [sys.executable, str(CLI), "--json", "gates", str(proj), "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    said = run.stderr.splitlines()
    assert said[-2] == f"RATINGS not held: 4 not judged (workcenter ratings {proj})", run.stderr
    assert said[-1].startswith("GREEN with "), run.stderr
    records = {r["gate"]: r for r in json.loads(run.stdout)}
    assert [records[g]["status"] for g in ("erc", "drc", "sim", "export")] == ["pass"] * 4
    assert records["drc"]["summary"] == (
        "0 errors, 0 warnings (0 unconnected, 0 parity), legend (no fab named: held to the least of the 4 "
        "fabs Via knows (height pcbway-standard, stroke oshpark-2layer)): 0 fail, 0 not judged"
    )
    runs = json.loads((tmp_path / "sim" / "corners" / "charger" / "runs.json").read_text(encoding="utf-8"))
    amps = [r["measures"]["ichg"] for r in runs]
    watts = [r["measures"]["p_u1"] for r in runs]
    assert (min(amps), max(amps)) == pytest.approx((0.162266, 0.165544), rel=1e-4)
    assert (min(watts), max(watts)) == pytest.approx((0.451482, 0.460496), rel=1e-4)
    u1 = records["sim"]["details"]["thermal"]["parts"]["U1"]
    # Judged, not held: SLUSCE2D's thermal table (section 7.4, page 4) names no JEDEC board, so the facts
    # give no `boards` and theta_ja holds no part (the SIM gate's thermal check, roadmap item 7).
    assert (u1["worst"]["run"], u1["worst"]["junction"], u1["limit"], u1["held"]) == (
        "40 C, R1 -1 %",
        pytest.approx(100.233, abs=1e-3),
        110.0,
        None,
    )
    not_held = (
        "thermal: U1 (BQ21040DBVR) not held: its facts (ti-bq21040.json) name no JEDEC board for theta_ja: "
        "write `boards` in `thermal` from the datasheet's thermal table"
    )
    assert records["sim"]["details"]["thermal"]["not_judged"] == [not_held], records["sim"]["details"]
    # The 2 warnings. C1 and C2 hold their makers' data and the deck runs no capacitor, so no deck runs
    # them on it (roadmap item 4's line). U1's junction is judged and not held, as above. The deck holds
    # nothing that moves with temperature, and is not warned of it: sim/thermal.json names it, so the
    # ambient's corners are there for the junction, which the thermal check works out at each (the SIM
    # gate's `heated`, from the linear regulator block).
    assert records["sim"]["details"]["warnings"] == [
        "not judged: C1 and C2 hold their makers' data, and no deck holds a capacitor or an inductor: a deck "
        "runs a board part on it only under the part's reference",
        not_held,
    ]
