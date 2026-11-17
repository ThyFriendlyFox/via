"""Circuit blocks (tools/blocks.py): a buck regulator added to a design in 1 call, its values worked out by
the equations of TI SLVA477C and its parts' facts from library/facts, as `workcenter ratings` reads them.

The sums of the 5 V to 3.3 V block, by hand. The input is 4.75 V to 5.25 V. The TLV62569's facts give the
least frequency, 1.35 MHz; its datasheet gives ILIM(min) 3 A and the inductor 2.2 uH (rules/blocks/buck.json).
Both stocked 2.2 uH inductors are 20 % parts: 2.2 uH x 0.8 = 1.76 uH at the least.

    equation 1    D = 3.3 / (5.25 x 0.9) = 3.3 / 4.725 = 0.698413
    equation 2    dIL = (5.25 - 3.3) x 0.698413 / (1.35e6 x 1.76e-6) = 1.361905 / 2.376 = 0.573192 A
    equation 3    IMAXOUT = 3 - 0.573192 / 2 = 2.713404 A
    equation 4    at 0.5 A: 0.5 + 0.286596 = 0.786596 A, under SRN2010TA-2R2M's 1.26 A
                  at 1.0 A: 1.0 + 0.286596 = 1.286596 A, over its 1.26 A and under XAL4020-222ME's 5.6 A
    equation 11   R1 = 100k x (3.3 / 0.6 - 1) = 100k x 4.5 = 450k; the stock's nearest is 453k
    output        0.612 x (1 + 453k x 1.01 / (100k x 0.99)) = 0.612 x 5.621515 = 3.440 V at the most
    table 4       10 uF, of which note 2 keeps 50 %: 5 uF effective. Samsung CL10A106KP8NNN keeps, between
                  its points (3.422325, 0.4264) and (3.5044, 0.41623), 0.4264 - 0.01017 x 0.018042 / 0.082075
                  = 0.42416 at 3.440367 V, and 10 uF x 0.9 x 0.42416 = 3.817 uF: 5 / 3.817 = 1.31, so 2
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import blocks  # noqa: E402
import kicadgen  # noqa: E402

CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
FACTS = BOARDS / "library" / "facts"

needs_libs = pytest.mark.skipif(
    not (kicadgen.SYMBOL_DIR / "Device.kicad_sym").is_file(),
    reason="KiCad symbol libraries are not installed",
)
needs_kicad = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")

L_0805 = "Inductor_SMD:L_0805_2012Metric"
L_XAL = "Inductor_SMD:L_Coilcraft_XAL4020-XXX"
R_0603 = "Resistor_SMD:R_0603_1608Metric"
C_0603 = "Capacitor_SMD:C_0603_1608Metric"
C_0805 = "Capacitor_SMD:C_0805_2012Metric"

SRN = blocks.Stock("Bourns", "SRN2010TA-2R2M", "2.2u SRN2010TA", L_0805)
XAL = blocks.Stock("Coilcraft", "XAL4020-222MEC", "2.2u XAL4020", L_XAL)
STOCK = [
    SRN,
    XAL,
    blocks.Stock("Vishay", "CRCW0603100KFKEA", "100k", R_0603),
    blocks.Stock("Vishay", "CRCW0603453KFKEA", "453k", R_0603),
    blocks.Stock("Vishay", "CRCW0603470KFKEA", "470k", R_0603),
    blocks.Stock("made up", "FIXTURE-10U-16V", "10u 16V", C_0805),
    blocks.Stock("Samsung", "CL10A106KP8NNN", "10u 10V", C_0603),
]
NOTE = "TI SLVA477C"


def design() -> kicadgen.Design:
    d = kicadgen.Design(
        name="t", namespace=uuid.UUID(int=3), outline=(100.0, 100.0, 140.0, 125.0), sheet="A4"
    )
    d.power_nets = {"+5V": "+5V", "+3V3": "+3V3", "GND": "GND"}
    return d


def buck(
    amps: float, stock=STOCK, vin=(4.75, 5.25), rules: Path | None = None
) -> tuple[kicadgen.Design, object]:
    d = design()
    kwargs = {"rules": rules} if rules else {}
    block = blocks.buck(
        d,
        ic="TLV62569DBVR",
        vin=vin,
        vout=3.3,
        amps=amps,
        nets=("+5V", "+3V3", "GND"),
        stock=stock,
        facts=FACTS,
        sch_at=(76.2, 76.2),
        pcb_at=(108.0, 106.0),
        **kwargs,
    )
    return d, block


@needs_libs
def test_half_an_amp_takes_the_first_stocked_inductor_that_holds_equation_4():
    """0.786596 A of peak (equation 4, the sums above) is under SRN2010TA-2R2M's 1.26 A: the first
    inductor of the stock is the one taken."""
    d, block = buck(0.5)
    parts = {p.ref: p.value for p in d.parts}
    assert parts == {
        "U1": "TLV62569",
        "L1": "2.2u SRN2010TA",
        "R1": "453k",
        "R2": "100k",
        "C1": "10u 16V",
        "C2": "10u 10V",
        "C3": "10u 10V",
    }
    assert block.sums == [
        f"U1: D = 3.3 V / (5.25 V x 0.9) = 0.6984 [{NOTE}, equation 1, page 2]",
        f"L1: dIL = (5.25 V - 3.3 V) x 0.6984 / (1.35 MHz x 1.76 uH) = 573 mA [{NOTE}, equation 2, page 2]",
        f"U1: IMAXOUT = 3 A - 573 mA / 2 = 2.71 A, the load is 500 mA [{NOTE}, equation 3, page 3]",
        f"L1: ISW(max) = 573 mA / 2 + 500 mA = 787 mA; SRN2010TA-2R2M saturates at 1.26 A "
        f"[{NOTE}, equation 4, page 3, and section 3, page 3]",
        f"R1: R1 = 100 kohm x (3.3 V / 0.6 V - 1) = 450 kohm; the stock's nearest is 453k "
        f"[{NOTE}, equation 11, page 5]",
        "C2, C3: 10 uF of output capacitance, 5 uF effective; each keeps 3.82 uF at 3.44 V "
        "[TLV62569 datasheet, SLVSDG1C, section 8.2.2.3, table 4, the cell marked ++ of each row of VOUT "
        "(2 x 22, 22 and 10 uF), page 9; note 2]",
        "C1: 10 uF of input capacitance, 4.7 uF asked [TLV62569 datasheet, SLVSDG1C, section 8.2.2.5, "
        "page 10: 4.7 uF of input capacitance is sufficient for most applications]",
    ]


@needs_libs
def test_twice_the_load_takes_another_inductor():
    """At 1.0 A the peak is 1.286596 A: over SRN2010TA-2R2M's 1.26 A, so the block takes the next in the
    stock, XAL4020-222MEC, which saturates at 5.6 A."""
    d, block = buck(1.0)
    assert {p.ref: p.value for p in d.parts}["L1"] == "2.2u XAL4020"
    assert (
        f"L1: ISW(max) = 573 mA / 2 + 1 A = 1.29 A; XAL4020-222MEC saturates at 5.6 A [{NOTE}, "
        in "\n".join(block.sums)
    )


@needs_libs
def test_no_stocked_inductor_that_holds_equation_4_is_1_line_that_names_it():
    """With SRN2010TA-2R2M alone in the stock, 1.0 A peaks at 1.286596 A over its 1.26 A."""
    stock = [s for s in STOCK if s is not XAL]
    with pytest.raises(blocks.Refused) as exc:
        buck(1.0, stock=stock)
    assert str(exc.value) == (
        "buck U1: no stocked inductor holds the peak of 1.29 A (1 A of load and half of 573 mA of ripple): "
        "SRN2010TA-2R2M saturates at 1.26 A "
        f"[{NOTE}, equation 4, page 3, and section 3, page 3]"
    )


@needs_libs
def test_a_load_over_what_the_ic_can_give_by_equation_3_is_refused(tmp_path):
    """A copy of the rules with ILIM(min) 2 A: IMAXOUT = 2 - 0.286596 = 1.713404 A, under 1.8 A of load."""
    rules = json.loads((ROOT / "rules" / "blocks" / "buck.json").read_text(encoding="utf-8"))
    rules["ics"][0]["ilim_min"]["value"] = 2.0
    (tmp_path / "buck.json").write_text(json.dumps(rules), encoding="utf-8")
    with pytest.raises(blocks.Refused) as exc:
        buck(1.8, rules=tmp_path / "buck.json")
    assert str(exc.value) == (
        "buck U1: IMAXOUT = 2 A - 573 mA / 2 = 1.71 A, under the load of 1.8 A "
        f"[{NOTE}, equation 3, page 3; TLV62569 datasheet, SLVSDG1C, section 6.5, Electrical "
        "Characteristics, ILIM of the DBV package, the column MIN, page 5]"
    )


@needs_libs
def test_a_load_over_the_ics_recommended_current_is_refused():
    """2.5 A is over the 2 A of section 6.3."""
    with pytest.raises(blocks.Refused) as exc:
        buck(2.5)
    assert str(exc.value) == (
        "buck U1: the load of 2.5 A is over TLV62569DBVR's 2 A [TLV62569 datasheet, SLVSDG1C, section 6.3, "
        "Recommended Operating Conditions, IOUT, page 4]"
    )


@needs_libs
def test_an_input_outside_the_ics_operating_range_is_refused():
    """6 V is over the 5.5 V the TLV62569's facts give for VIN."""
    with pytest.raises(blocks.Refused) as exc:
        buck(0.5, vin=(4.5, 6.0))
    assert str(exc.value) == (
        "buck U1: the input reaches 6 V, VIN of TLV62569DBVR operates from 2.5 V to 5.5 V "
        "[TLV62569 datasheet, SLVSDG1C, December 2016, revised October 2017, p 3 and 4]"
    )


@needs_libs
def test_the_block_hands_its_input_and_its_parts_to_ratings():
    """The input range is the net's span in ratings.json, with the call it came from; each part is a row of
    parts.csv with its maker and its number, 2 output capacitors on 1 row."""
    _, block = buck(0.5)
    assert block.ratings == {
        "nets": {
            "+5V": {
                "volts": [4.75, 5.25],
                "source": "the input range of the buck block U1: buck(vin=(4.75, 5.25))",
            }
        }
    }
    assert [(r.value, r.mpn, r.qty) for r in block.rows] == [
        ("TLV62569", "TLV62569DBVR", 1),
        ("2.2u SRN2010TA", "SRN2010TA-2R2M", 1),
        ("453k", "CRCW0603453KFKEA", 1),
        ("100k", "CRCW0603100KFKEA", 1),
        ("10u 16V", "FIXTURE-10U-16V", 1),
        ("10u 10V", "CL10A106KP8NNN", 2),
    ]


@needs_libs
def test_design_files_are_written_beside_the_project_and_never_outside_it(tmp_path):
    """Design.files puts a block's deck and ratings.json under the project folder; a path that climbs out
    of it is refused before anything is written."""
    d = design()
    d.files = {"sim/a.cir": "* a\n", "ratings.json": "{}\n"}
    d.write(tmp_path / "p")
    assert (tmp_path / "p" / "sim" / "a.cir").read_text(encoding="utf-8") == "* a\n"
    assert (tmp_path / "p" / "ratings.json").read_text(encoding="utf-8") == "{}\n"
    d.files = {"../out.txt": "x"}
    with pytest.raises(ValueError, match=r"Design.files: \.\./out\.txt is no path under the project"):
        d.write(tmp_path / "q")
    assert not (tmp_path / "out.txt").exists()


def test_every_number_of_the_rules_names_where_it_stands():
    """No number of rules/blocks/buck.json stands without its clause and page: each value of an IC has a
    `where` with a page, and each equation its page."""
    rules = json.loads((ROOT / "rules" / "blocks" / "buck.json").read_text(encoding="utf-8"))
    for ic in rules["ics"]:
        for key, entry in ic.items():
            if isinstance(entry, dict) and ("value" in entry or "rows" in entry):
                assert "page " in entry["where"], (ic["mpn"], key)
    assert all(isinstance(e["page"], int) for e in rules["note"]["equations"].values())


FIXTURES = {"pass-block-buck": "2.2u SRN2010TA", "pass-block-buck-2x": "2.2u XAL4020"}


@needs_kicad
@needs_libs
@pytest.mark.parametrize("name", FIXTURES)
def test_each_fixture_is_what_its_design_file_writes_and_passes_ratings_strict(name, tmp_path):
    """`workcenter design` writes the committed schematic, project, ratings.json, parts.csv and deck; a
    strict `workcenter ratings` of the fixture passes."""
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
        "library/sources.csv",
        "sim/buck.cir",
        "sim/buck.expect.json",
        "sim/corners.json",
    ):
        assert (out / rel).read_bytes() == (BOARDS / name / rel).read_bytes(), rel
    run = subprocess.run(
        [sys.executable, str(CLI), "ratings", str(BOARDS / name), "--out", str(tmp_path / "r"), "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    report = (tmp_path / "r" / "ratings" / "report.md").read_text(encoding="utf-8")
    assert f"- L1 {FIXTURES[name]}: its peak current is " in report


# The span of the deck's `ipeak` over its 20 corner runs on 2026-11-17, and the bound each is held to: the
# inductor's saturation current from its facts. SLVA477C's equation 4 gave 0.787 A and 1.29 A: higher
# than the runs, since equation 1 takes 90 % efficiency and the deck's lossless stage has a shorter duty.
PEAKS = {"pass-block-buck": (0.6718417, 0.7626507, 1.26), "pass-block-buck-2x": (1.173663, 1.259503, 5.6)}
WARNINGS = [
    "C2 runs on its maker's data, and whether that is its maker's file is not judged",
    "C3 runs on its maker's data, and whether that is its maker's file is not judged",
    "no sim/frequency-plan.json: 1 decks drive periodic sources: buck (VSW)",
]


@needs_kicad
@pytest.mark.parametrize("name", FIXTURES)
def test_each_fixture_is_routed_and_its_gates_are_green_with_the_3_warnings_named(name, tmp_path):
    """ERC, DRC (0 unconnected: the router finished), SIM and EXPORT pass. The 3 warnings are what the
    gates cannot judge: the capacitors' maker's page is kept outside the repository, and the block writes
    no frequency plan. A strict run fails on them and on nothing else."""
    run = subprocess.run(
        [sys.executable, str(CLI), "--json", "gates", str(BOARDS / name), "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    records = {r["gate"]: r for r in json.loads(run.stdout)}
    assert [records[g]["status"] for g in ("erc", "drc", "sim", "export")] == ["pass"] * 4
    assert records["drc"]["summary"] == "0 errors, 0 warnings (0 unconnected, 0 parity)"
    assert records["sim"]["summary"] == "1 decks, 20 corner runs, 0 failures, 3 warnings"
    text = json.dumps(records["sim"])
    assert all(w in text for w in WARNINGS)
    low, high, bound = PEAKS[name]
    runs = json.loads((tmp_path / "sim" / "corners" / "buck" / "runs.json").read_text(encoding="utf-8"))
    peaks = [r["measures"]["ipeak"] for r in runs]
    assert (min(peaks), max(peaks)) == pytest.approx((low, high), rel=1e-3)
    assert records["sim"]["details"]["decks"]["buck"]["checks"]["ipeak"]["max"] == bound
