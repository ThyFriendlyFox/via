"""The charger block (tools/blocks_charger.py): a BQ21040 linear charger for 1 lithium cell with a BQ29700
protector and its 2 CSD17313Q2 transistors, added to a design in 1 call, every value from the 2 datasheets
(rules/blocks/charger.json) and the parts' facts (tests/boards/library/facts).

The sums of the fixture, by hand. The input is 4.75 V to 5.25 V; the cell's limits are made up: 2.5 V to
4.3 V, 0.5 A in charge, 3 A in discharge; the system draws 1 A; the ambient is 0 C to 40 C.

    KISET, 150 mA     the row of 60 mA to 1000 mA: 490, 540, 590 A ohm (SLUSCE2D 7.5, page 5)
    equation 1        RISET = 540 / 0.15 = 3600 ohm; the stock holds 3.6k, 1 %
                      typical 540 / 3600 = 0.15 A; least 490 / (3600 x 1.01) = 490 / 3636 = 0.134763 A;
                      greatest 590 / (3600 x 0.99) = 590 / 3564 = 0.165544 A, under the cell's 0.5 A
    equation 8        the least cell voltage in fast charge: the larger of the cell's 2.5 V and VLOWV's least,
                      2.4 V (page 5): 2.5 V. P = (5.25 - 2.5) x 0.165544 + 5.25 x 0.001 (ICC, page 5)
                      = 0.455246 + 0.00525 = 0.460496 W
    junction          TJ = 40 + 130.8 x 0.460496 = 40 + 60.2329 = 100.233 C, under 125 C (7.3, page 4)
    at 0.3 A          RISET = 540 / 0.3 = 1800 ohm: 1.8k; greatest 590 / (1800 x 0.99) = 590 / 1782
                      = 0.331089 A; P = 2.75 x 0.331089 + 0.00525 = 0.915744 W;
                      TJ = 40 + 130.8 x 0.915744 = 159.779 C, over 125 C. The most: (125 - 40) / 130.8
                      = 0.649847 W, (0.649847 - 0.00525) / 2.75 = 0.234399 A
    C1                CL10A106KP8NNN at 5.25 V keeps, between (5.2344, 0.26773) and (5.35535, 0.26029),
                      0.26773 - 0.00744 x 0.0156 / 0.12095 = 0.266770: 10 uF x 0.9 x 0.266770 = 2.40093 uF,
                      within 1 uF to 10 uF (SLUSCE2D pin table, page 3; figure 10, page 17)
    C2                at 4.3 V, between (4.279525, 0.33833) and (4.3748, 0.33003): 0.33833 - 0.0083 x 0.020475
                      / 0.095275 = 0.336546: 10 uF x 0.9 x 0.336546 = 3.02892 uF
    OVP               4.275 V -/+ 20 mV (SLUSBU9I table 4, page 3; 6.6, page 6): 4.255 V to 4.295 V; over
                      the charger's 4.23 V (VOUT(REG) MAX, page 5), within the cell's 4.3 V
    UVP               2.8 V - 50 mV = 2.75 V, over the cell's 2.5 V
    transistors       2 x 42 mohm = 84 mohm (SLPS260E 5.1, VGS = 3 V, MAX, page 3); OCD's least 100 - 15
                      = 85 mV; OCC's least 85 mV. The load: 0.084 x 1 = 84 mV, under 85 mV. The charge:
                      0.084 x 0.165544 = 13.906 mV. At the typical 31 mohm the discharge trips at
                      0.115 / 0.062 = 1.854839 A, under the cell's 3 A
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

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests" / "boards"))
sys.dont_write_bytecode = True

import blocks  # noqa: E402
import kicadgen  # noqa: E402

CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
FACTS = BOARDS / "library" / "facts"
RULES = ROOT / "rules" / "blocks" / "charger.json"

needs_libs = pytest.mark.skipif(
    not (kicadgen.SYMBOL_DIR / "Device.kicad_sym").is_file(),
    reason="KiCad symbol libraries are not installed",
)
needs_kicad = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")

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
    assert block.sums[:9] == [
        "R1: RISET = 540 AΩ / 150 mA = 3.6 kohm; the stock's nearest is 3.6k, which sets 150 mA, and 135 mA "
        f"to 166 mA with KISET of 490 to 590 AΩ and 1 % of resistor [{EQ1}]",
        f"U1: the charge current reaches 166 mA, the cell takes 500 mA [{CELL_SOURCE}]",
        "U1: P = (5.25 V - 2.5 V) x 166 mA + 5.25 V x 1 mA = 0.4605 W at 2.5 V, the cell's least; "
        f"TJ = 40 C + 130.8 C/W x 0.4605 W = 100.2 C, under 125 C [{HEAT}]",
        f"C1: 10u 10V, X5R, keeps 2.4 uF at 5.25 V less 10 %, within 1 uF to 10 uF [{CAPS}]",
        f"C2: 10u 10V, X5R, keeps 3.03 uF at 4.3 V less 10 %, within 1 uF to 10 uF [{CAPS}]",
        "U2: the overcharge threshold is 4.255 V to 4.295 V: over the charger's 4.23 V and within the cell's "
        f"4.3 V [{DS}, section 7.5, VOUT(REG), MIN and MAX, page 5; {OVP}; {CELL_SOURCE}]",
        "U2: the overdischarge threshold is 2.75 V at the least, over the cell's 2.5 V; its tolerance is the "
        f"one at 25 C, the 1 the datasheet gives [{UVP}; {CELL_SOURCE}]",
        "Q1, Q2: CSD17313Q2, 2 x 42 mohm = 84 mohm; the load gives 84 mV, under VOCD's least, 85 mV; the "
        f"charge gives 13.9 mV, under OCC's least, 85 mV [{FETS}; {RDS}]",
        "Q1, Q2: at the typical 31 mohm the discharge trips at 115 mV / 62 mohm = 1.85 A, the cell gives "
        "3 A; not judged: the trip with a transistor under its typical on-resistance, which the datasheet "
        "does not bound, and the on-resistance with a gate under the 3.4 V the protector gives at a cell of "
        f"3.8 V [{FETS}; {RDS}; {PS}, section 6.5, VOH of COUT and DOUT at BAT = 3.8 V, MIN, page 5; "
        f"{CELL_SOURCE}]",
    ]


@needs_libs
def test_twice_the_current_is_refused_with_equation_8():
    """0.3 A takes 1.8k and reaches 0.331089 A: 0.915744 W, 159.779 C at 40 C, over 125 C. The most at
    40 C is 0.234399 A."""
    assert refused(amps=0.3) == (
        "charger U1: P = (5.25 V - 2.5 V) x 331 mA + 5.25 V x 1 mA = 0.9157 W at 2.5 V, the cell's least; "
        "TJ = 40 C + 130.8 C/W x 0.9157 W = 159.8 C, over 125 C: at 40 C the charge current reaches 234 mA "
        f"at the most [{HEAT}]"
    )


@needs_libs
def test_a_current_over_the_ics_800_ma_is_refused():
    """0.9 A is over IOUT's 0.8 A (SLUSCE2D 7.3, page 4; 7.5, page 5)."""
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
    """6.5 V is over the 6.45 V where OVP restricts IN (SLUSCE2D 7.3, page 4)."""
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
    which is 0.163889 A as written. Its bounds: the cell's 0.5 A, and (125 - 40) / 130.8 = 0.649847 W."""
    _, block = charger()
    deck = block.files["sim/charger.cir"].splitlines()
    for line in ("VIN in 0 DC 5.25", "R1 iset 0 3600", "BU1 in out I=-590*i(vset)", "VBAT out 0 DC 2.5"):
        assert line in deck
    expect = json.loads(block.files["sim/charger.expect.json"])
    assert (expect["ichg"]["max"], expect["p_u1"]["max"]) == (0.5, 0.649847)
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
def test_the_fixture_is_what_its_design_file_writes_and_passes_ratings_strict(tmp_path):
    """`workcenter design` writes the committed schematic, project, ratings.json, parts.csv and deck; a
    strict `workcenter ratings` of the fixture passes."""
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
    run = subprocess.run(
        [sys.executable, str(CLI), "ratings", str(board), "--out", str(tmp_path / "r"), "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr


@needs_kicad
@needs_libs
def test_the_fixture_at_twice_the_current_is_refused_by_design_with_the_line(tmp_path):
    """`workcenter design` of refuse-block-charger-2x fails, writes no schematic and prints the refusal."""
    made = design("refuse-block-charger-2x", tmp_path / "out")
    assert made.returncode != 0
    assert "TJ = 40 C + 130.8 C/W x 0.9157 W = 159.8 C, over 125 C" in made.stdout + made.stderr
    assert not (tmp_path / "out" / "node.kicad_sch").exists()
    assert sorted(p.name for p in (BOARDS / "refuse-block-charger-2x").iterdir()) == ["design.py"]
