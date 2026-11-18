"""Circuit blocks (tools/blocks.py): a buck regulator added to a design in 1 call, its values worked out by
the equations of TI SLVA477C and its parts' facts from library/facts, as `workcenter ratings` reads them.

The sums of the 5 V to 3.3 V block, by hand. The input is 4.75 V to 5.25 V. The TLV62569's facts give the
least frequency, 1.35 MHz; its datasheet gives ILIM(min) 3 A and the inductor 2.2 uH (rules/blocks/buck.json).
Both stocked 2.2 uH inductors are 20 % parts, and table 4's note 1 (SLVSDG1C page 9) lets the effective
inductance fall 30 %: the block counts the larger, 2.2 uH x 0.7 = 1.54 uH at the least.

    equation 1    D = 3.3 / (5.25 x 0.9) = 3.3 / 4.725 = 0.698413
    equation 2    dIL = (5.25 - 3.3) x 0.698413 / (1.35e6 x 1.54e-6) = 1.361905 / 2.079 = 0.655077 A
    equation 3    IMAXOUT = 3 - 0.655077 / 2 = 2.672462 A
    equation 4    at 0.5 A: 0.5 + 0.327538 = 0.827538 A; with SLVSDG1C section 8.2.2.4's 20 % (page 10)
                  0.827538 x 1.2 = 0.993046 A, under SRN2010TA-2R2M's 1.26 A
                  at 1.0 A: 1.327538 A, x 1.2 = 1.593046 A, over its 1.26 A and under XAL4020-222ME's 5.6 A
                  at 0.9 A: 1.227538 A, under 1.26 A, but x 1.2 = 1.473046 A, over it
    equation 11   R1 = 100k x (3.3 / 0.6 - 1) = 100k x 4.5 = 450k; the stock's nearest is 453k
    output        0.6 x (1 + 453k / 100k) = 0.6 x 5.53 = 3.318 V as set (SLVSDG1C equation 2, page 9);
                  0.588 x (1 + 453k x 0.99 / (100k x 1.01)) = 0.588 x 5.440297 = 3.198895 V at the least,
                  0.612 x (1 + 453k x 1.01 / (100k x 0.99)) = 0.612 x 5.621515 = 3.440367 V at the most
    table 4       3.318 V is the row of 1.8 V and over: 10 uF, of which note 2 keeps 50 %: 5 uF effective.
                  Samsung CL10A106KP8NNN keeps, between its points (3.422325, 0.4264) and (3.5044, 0.41623),
                  0.4264 - 0.01017 x 0.018042 / 0.082075 = 0.42416 at 3.440367 V, and 10 uF x 0.9 x 0.42416
                  = 3.817 uF: 5 / 3.817 = 1.31, so 2; 2 x 10 uF = 20 uF, within 8.2.2.5's 10 uF to 47 uF
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

CITES = {
    "ti-slva477c": "equations 1, 2, 3, 4 and 11; sections 6 and 7",
    "ti-slvsdg1": "equations 1 (7.3.2) and 2, table 4 and its notes; sections 6.3, 6.5, 8.2.2.4 and 8.2.2.5",
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


def buck(  # noqa: PLR0913
    amps: float, stock=STOCK, vin=(4.75, 5.25), rules: Path | None = None, vout: float = 3.3, facts=FACTS
) -> tuple[kicadgen.Design, object]:
    d = design()
    kwargs = {"rules": rules} if rules else {}
    block = blocks.buck(
        d,
        ic="TLV62569DBVR",
        vin=vin,
        vout=vout,
        amps=amps,
        nets=("+5V", "+3V3", "GND"),
        stock=stock,
        facts=facts,
        sch_at=(76.2, 76.2),
        pcb_at=(108.0, 106.0),
        **kwargs,
    )
    return d, block


def refused(**kwargs) -> str:
    with pytest.raises(blocks.Refused) as exc:
        buck(**kwargs)
    return str(exc.value)


MADE_UP = {"document": "no datasheet: a part made up for tests/test_blocks.py", "read": "2026-11-17"}


def facts_with(tmp_path: Path, *parts: dict) -> Path:
    """The fixtures' facts folder and, beside it, parts made up for 1 test."""
    folder = tmp_path / "facts"
    shutil.copytree(FACTS, folder)
    entries = [{**part, "source": {**MADE_UP, "second_reader": "no"}} for part in parts]
    (folder / "zz-made-up.json").write_text(json.dumps({"parts": entries}), encoding="utf-8")
    return folder


R100, R453 = STOCK[2], STOCK[3]
CIN, COUT = STOCK[5], STOCK[6]
EQ11_EQ2 = f"{NOTE}, equation 11, page 5; TLV62569 datasheet, SLVSDG1C, section 8.2.2.2, equation 2, page 9"
VOUT_WHERE = (
    "TLV62569 datasheet, SLVSDG1C, section 6.3, Recommended Operating Conditions, VOUT from 0.6 V to VIN, "
    "page 4"
)
MARGIN = (
    "TLV62569 datasheet, SLVSDG1C, section 8.2.2.4, page 10: a saturation current about 20 % to 30 % above "
    "IL,MAX; the block asks the least, 20 %"
)
DIELECTRIC = (
    "section 8.2.2.5, page 10: X7R or X5R dielectric is recommended; TI SLVA477C, sections 6 and 7, page 5: "
    "X5R or better"
)
TABLE4 = (
    "TLV62569 datasheet, SLVSDG1C, section 8.2.2.3, table 4, the cell marked ++ of each row of VOUT "
    "(2 x 22, 22 and 10 uF), page 9; note 2; section 8.2.2.5, page 10: designed to operate with an output "
    f"capacitor of 10 uF to 47 uF; {DIELECTRIC}"
)
DROPOUT = (
    "TLV62569 datasheet, SLVSDG1C, section 7.3.2, equation 1, page 6; TLV62569 datasheet, SLVSDG1C, section "
    "6.5, Electrical Characteristics, RDS(on) of the high-side FET, typical: no MAX is stated, page 5"
)
INPUT_WHERE = (
    "TLV62569 datasheet, SLVSDG1C, section 8.2.2.5, page 10: 4.7 uF of input capacitance is sufficient for "
    f"most applications; {DIELECTRIC}"
)


@needs_libs
def test_half_an_amp_takes_the_first_stocked_inductor_that_holds_equation_4():
    """0.827538 A of peak (equation 4, the sums above), 0.993046 A with 20 % of margin, is under
    SRN2010TA-2R2M's 1.26 A: the first inductor of the stock is the one taken."""
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
        f"L1: dIL = (5.25 V - 3.3 V) x 0.6984 / (1.35 MHz x 1.54 uH) = 655 mA [{NOTE}, equation 2, page 2]; "
        "L is 2.2 uH less 30 % [TLV62569 datasheet, SLVSDG1C, section 8.2.2.3, table 4, note 1: the "
        "effective inductance can vary by +20 % and -30 %, page 9]",
        f"U1: IMAXOUT = 3 A - 655 mA / 2 = 2.67 A, the load is 500 mA [{NOTE}, equation 3, page 3]",
        "L1: ISW(max) = 655 mA / 2 + 500 mA = 828 mA, 993 mA with 20 % of margin; SRN2010TA-2R2M saturates "
        f"at 1.26 A and is rated 1.2 A rms [{NOTE}, equation 4, page 3, and section 3, page 3; {MARGIN}]",
        "R1: R1 = 100 kohm x (3.3 V / 0.6 V - 1) = 450 kohm; the stock's nearest is 453k, which sets "
        "3.318 V, and 3.2 V to 3.44 V with VFB of 588 mV to 612 mV and the resistors' tolerances "
        f"[{EQ11_EQ2}]",
        "U1: VIN(MIN) = 3.44 V + 500 mA x (100 mohm + 174 mohm) = 3.58 V, and the least input is 4.75 V "
        f"[{DROPOUT}; L1's DCR: Bourns SRN2010TA series datasheet, REV. 06/25]",
        "C2, C3: 10 uF of output capacitance for 3.318 V, 5 uF effective; each, X5R, keeps 3.82 uF at "
        f"3.44 V; 2 x 10 uF = 20 uF, within 10 uF to 47 uF [{TABLE4}]",
        "C1: 10 uF of input capacitance, X5R, 9 uF less its tolerance; its value under 5.25 V is not judged: "
        "its facts give none; 4.7 uF asked [TLV62569 datasheet, SLVSDG1C, section 8.2.2.5, "
        f"page 10: 4.7 uF of input capacitance is sufficient for most applications; {DIELECTRIC}]",
    ]


@needs_libs
def test_twice_the_load_takes_another_inductor():
    """At 1.0 A the peak is 1.327538 A, 1.593046 A with 20 % of margin: over SRN2010TA-2R2M's 1.26 A, so
    the block takes the next in the stock, XAL4020-222MEC, which saturates at 5.6 A."""
    d, block = buck(1.0)
    assert {p.ref: p.value for p in d.parts}["L1"] == "2.2u XAL4020"
    assert (
        "L1: ISW(max) = 655 mA / 2 + 1 A = 1.33 A, 1.59 A with 20 % of margin; XAL4020-222MEC saturates at "
        f"5.6 A and is rated 4 A rms [{NOTE}, " in "\n".join(block.sums)
    )


@needs_libs
def test_no_stocked_inductor_that_holds_equation_4_is_1_line_that_names_it():
    """With SRN2010TA-2R2M alone in the stock, 1.0 A peaks at 1.327538 A, 1.593046 A with the margin,
    over its 1.26 A."""
    stock = [s for s in STOCK if s is not XAL]
    assert refused(amps=1.0, stock=stock) == (
        "buck U1: no stocked inductor holds the peak of 1.33 A with 20 % of margin, 1.59 A (1 A of load and "
        "half of 655 mA of ripple): SRN2010TA-2R2M saturates at 1.26 A "
        f"[{NOTE}, equation 4, page 3, and section 3, page 3; {MARGIN}]"
    )


@needs_libs
def test_the_margin_of_section_8_2_2_4_is_applied():
    """At 0.9 A the peak is 0.9 + 0.327538 = 1.227538 A, under SRN2010TA-2R2M's 1.26 A; with 20 % of
    margin it is 1.473046 A, over it: the inductor is not taken."""
    stock = [s for s in STOCK if s is not XAL]
    assert refused(amps=0.9, stock=stock) == (
        "buck U1: no stocked inductor holds the peak of 1.23 A with 20 % of margin, 1.47 A (900 mA of load "
        "and half of 655 mA of ripple): SRN2010TA-2R2M saturates at 1.26 A "
        f"[{NOTE}, equation 4, page 3, and section 3, page 3; {MARGIN}]"
    )


@needs_libs
def test_an_inductor_under_the_load_in_rms_current_is_passed_over(tmp_path):
    """A made-up 2.2 uH inductor, first in the stock, saturates at 5 A but is rated 0.4 A rms, under the
    0.5 A of load: the block takes the next, SRN2010TA-2R2M."""
    low = {"kind": "inductor", "mpn": "FIXTURE-2R2-LOWRMS", "tolerance": 0.2, "amps_saturation": 5.0}
    facts = facts_with(tmp_path, {**low, "amps_rms": 0.4})
    lowrms = blocks.Stock("made up", "FIXTURE-2R2-LOWRMS", "2.2u LOWRMS", "Inductor_SMD:L_0805_2012Metric")
    d, _ = buck(0.5, stock=[lowrms, *STOCK], facts=facts)
    assert {p.ref: p.value for p in d.parts}["L1"] == "2.2u SRN2010TA"


@needs_libs
def test_an_inductor_with_no_rms_rating_says_its_rms_current_is_not_judged(tmp_path):
    """The same made-up inductor with no amps_rms in its facts is taken, and its sum says so."""
    low = {"kind": "inductor", "mpn": "FIXTURE-2R2-LOWRMS", "tolerance": 0.2, "amps_saturation": 5.0}
    facts = facts_with(tmp_path, low)
    lowrms = blocks.Stock("made up", "FIXTURE-2R2-LOWRMS", "2.2u LOWRMS", "Inductor_SMD:L_0805_2012Metric")
    _, block = buck(0.5, stock=[lowrms, *STOCK], facts=facts)
    assert "FIXTURE-2R2-LOWRMS saturates at 5 A; its rms current is not judged: its facts give none [" in (
        "\n".join(block.sums)
    )


@needs_libs
def test_a_divider_that_misses_the_output_asked_is_refused():
    """With 100k the only stocked resistor, R1 and R2 are both 100k: 0.6 x (1 + 1) = 1.2 V as set, and
    0.588 x (1 + 99/101) = 1.164356 V to 0.612 x (1 + 101/99) = 1.236364 V; 3.3 V is not in it."""
    stock = [SRN, XAL, R100, CIN, COUT]
    assert refused(amps=0.5, stock=stock) == (
        "buck U1: R1 of 100k and R2 of 100k set VOUT to 1.2 V, 1.16 V to 1.24 V with VFB of 588 mV to "
        "612 mV and the resistors' tolerances, and 3.3 V is asked: no stocked resistor is near 450 kohm "
        f"[{EQ11_EQ2}]"
    )


@needs_libs
def test_table_4s_row_is_taken_from_the_voltage_the_divider_sets():
    """1.8 V asked: R1 = 100k x (1.8 / 0.6 - 1) = 200k, and the stock's nearest is 196k. It sets
    0.6 x 2.96 = 1.776 V, in table 4's row 1.2 V to 1.8 V: 22 uF, 11 uF effective. 1.8 V lies in its span,
    0.588 x (1 + 196 x 0.99 / 101) = 1.717659 V to 0.612 x (1 + 196 x 1.01 / 99) = 1.835753 V.
    CL10A106KP8NNN keeps, between (1.7824, 0.71514) and (1.891675, 0.69174), 0.71514 - 0.0234 x 0.053353 /
    0.109275 = 0.703715 at 1.835753 V: 10 uF x 0.9 x 0.703715 = 6.33 uF each, 11 / 6.33 = 1.74, so 2.
    The row of 1.8 V and over would ask 10 uF, 5 uF effective: 1."""
    r196 = blocks.Stock("Vishay", "CRCW0603196KFKEA", "196k", R_0603)
    d, block = buck(0.5, vout=1.8, stock=[SRN, R100, r196, CIN, COUT])
    parts = {p.ref: p.value for p in d.parts}
    assert (parts["R1"], parts["C2"], parts["C3"]) == ("196k", "10u 10V", "10u 10V")
    assert "C2, C3: 22 uF of output capacitance for 1.776 V, 11 uF effective; each, X5R, keeps 6.33 uF" in (
        "\n".join(block.sums)
    )


@needs_libs
def test_an_output_over_the_least_input_is_refused():
    """5 V is over the least input, 4.75 V: VOUT runs from 0.6 V to VIN (SLVSDG1C section 6.3, page 4)."""
    assert (
        refused(amps=0.5, vout=5.0) == f"buck U1: VOUT of 5 V is over the least input, 4.75 V [{VOUT_WHERE}]"
    )


@needs_libs
def test_a_duty_cycle_over_1_is_refused():
    """4.75 V is the least input, which 6.3 allows; D = 4.75 / (5.25 x 0.9) = 4.75 / 4.725 = 1.005291."""
    assert refused(amps=0.5, vout=4.75) == (
        f"buck U1: D = 4.75 V / (5.25 V x 0.9) = 1.0053, over 1: the switch would be on for more than its "
        f"period [{NOTE}, equation 1, page 2]"
    )


@needs_libs
def test_an_output_under_the_reference_is_refused():
    """0.5 V is under the 0.6 V that VOUT starts at (SLVSDG1C section 6.3, page 4)."""
    assert refused(amps=0.5, vout=0.5) == f"buck U1: VOUT of 500 mV is under 600 mV [{VOUT_WHERE}]"


@needs_libs
@pytest.mark.parametrize(("amps", "shown"), [(0.0, "0 A"), (-0.5, "-500 mA")])
def test_a_load_of_0_or_less_is_refused(amps, shown):
    """The deck's load is VOUT / IOUT, and the block sizes its parts for the load: 0 A or less has none."""
    assert refused(amps=amps) == (
        f"buck U1: a load of {shown}: the block sizes its parts and its deck's load, VOUT / IOUT, for a load "
        "over 0 A [TLV62569 datasheet, SLVSDG1C, section 6.3, Recommended Operating Conditions, IOUT, page 4]"
    )


@needs_libs
def test_an_input_under_the_ics_operating_range_is_refused():
    """2.4 V is under the 2.5 V the TLV62569's facts give for VIN."""
    assert refused(amps=0.5, vin=(2.4, 5.0)) == (
        "buck U1: the input reaches 2.4 V, VIN of TLV62569DBVR operates from 2.5 V to 5.5 V "
        "[TLV62569 datasheet, SLVSDG1C, December 2016, revised October 2017, p 3 and 4]"
    )


@needs_libs
def test_a_least_input_under_vin_min_of_equation_1_is_refused():
    """SLVSDG1C section 7.3.2, equation 1 (page 6): VIN(MIN) = VOUT + IOUT x (RDS(ON) + RL). The output
    reaches 3.440367 V at the top of its span (the sums above); RDS(on) of the high-side FET is 100 mohm
    (6.5, page 5) and XAL4020-222ME's DCR is 38.7 mohm at the most (Coilcraft document 806, page 1). At
    1.2 A: 3.440367 + 1.2 x 0.1387 = 3.606807 V, over the least input, 3.3 V. Before the fix it built."""
    assert refused(amps=1.2, stock=[XAL, R100, R453, CIN, COUT], vin=(3.3, 5.0)) == (
        "buck U1: VIN(MIN) = 3.44 V + 1.2 A x (100 mohm + 38.7 mohm) = 3.61 V, over the least input, 3.3 V: "
        "at 3.3 V the IC cannot hold the output's span "
        f"[{DROPOUT}; L1's DCR: Coilcraft XAL40xx datasheet, document 806, revised 02/25/26]"
    )


@needs_libs
def test_an_inductor_with_no_dcr_says_its_dcr_is_not_judged(tmp_path):
    """The made-up inductor of the tests above has no ohms_dc: VIN(MIN) is 3.440367 + 0.5 x 0.1 =
    3.490367 V with RDS(on) alone, and the sum says the DCR is not judged."""
    low = {"kind": "inductor", "mpn": "FIXTURE-2R2-LOWRMS", "tolerance": 0.2, "amps_saturation": 5.0}
    lowrms = blocks.Stock("made up", "FIXTURE-2R2-LOWRMS", "2.2u LOWRMS", "Inductor_SMD:L_0805_2012Metric")
    _, block = buck(0.5, stock=[lowrms, *STOCK], facts=facts_with(tmp_path, low))
    assert (
        "U1: VIN(MIN) = 3.44 V + 500 mA x 100 mohm = 3.49 V, and the least input is 4.75 V; L1's DCR is not "
        f"judged: its facts give none [{DROPOUT}]"
    ) in block.sums


def test_an_inductors_dcr_under_0_is_wrong_facts(tmp_path):
    """ohms_dc is the inductor's DC resistance at the most: a number of 0 or more."""
    bad = {"kind": "inductor", "mpn": "FIXTURE-BAD-DCR", "tolerance": 0.2, "amps_saturation": 1.0}
    read = blocks.ratings.read_facts(facts_with(tmp_path / "good", {**bad, "ohms_dc": 0.1}))
    assert [f.data["ohms_dc"] for f in read if f.data.get("mpn") == "FIXTURE-BAD-DCR"] == [0.1]
    with pytest.raises(blocks.ratings.Refusal, match="ohms_dc: .*0"):
        blocks.ratings.read_facts(facts_with(tmp_path / "bad", {**bad, "ohms_dc": -0.1}))


@needs_libs
def test_an_input_range_written_greatest_first_is_refused():
    """vin=(5.5, 3.7) built before the fix: D at 3.7 V, dIL of 191 mA and 1.25 A with the margin, under
    SRN2010TA-2R2M's 1.26 A. At the real greatest input, 5.5 V, D = 3.3 / 4.95 = 0.6667 and dIL =
    2.2 x 0.6667 / (1.35 MHz x 1.54 uH) = 0.7055 A: 0.95 + 0.3527 = 1.303 A, over 1.26 A."""
    assert refused(amps=0.95, stock=[SRN, XAL, R100, R453, CIN, COUT], vin=(5.5, 3.7)) == (
        "buck U1: vin=(5.5, 3.7) is written greatest first: vin is (least, greatest), and the block sizes "
        f"its parts at the greatest [{NOTE}, equation 1, page 2]"
    )


@needs_libs
@pytest.mark.parametrize(
    ("spec", "says"),
    [
        ({"amps": float("nan")}, "amps=nan"),
        ({"amps": float("inf")}, "amps=inf"),
        ({"amps": 0.5, "vout": float("nan")}, "vout=nan"),
        ({"amps": 0.5, "vin": (float("nan"), 5.25)}, "vin=(nan, 5.25)"),
        ({"amps": 0.5, "vin": (4.75, float("inf"))}, "vin=(4.75, inf)"),
    ],
)
def test_a_number_of_the_spec_that_is_not_finite_is_refused(spec, says):
    """A NaN load built before the fix: `amps <= 0` and `amps > amps_max` are both False for NaN, and the
    deck said `RLOAD out 0 nan`."""
    assert refused(**spec) == f"buck U1: {says}: each number of the spec must be finite"


@needs_libs
def test_a_divider_that_sets_the_output_outside_the_references_accuracy_is_refused(tmp_path):
    """A made-up 5 % 430k is the stock's nearest to 450k: 0.6 x 5.3 = 3.18 V, 3.6 % under 3.3 V. The span
    0.588 x (1 + 430 x 0.95 / 101) = 2.966 V to 0.612 x (1 + 430 x 1.05 / 99) = 3.403 V holds 3.3 V, and
    the block took it before the fix. It now holds the output set to 2 %, the reference's own accuracy:
    588 mV to 612 mV around 600 mV (SLVSDG1C section 6.5, page 4)."""
    loose = {"kind": "resistor", "mpn": "LOOSE-430K", "tolerance": 0.05, "watts": 0.1, "volts": 50}
    r430 = blocks.Stock("made up", "LOOSE-430K", "430k", R_0603)
    assert refused(amps=0.5, stock=[SRN, R100, r430, CIN, COUT], facts=facts_with(tmp_path, loose)) == (
        "buck U1: R1 of 430k and R2 of 100k set VOUT to 3.18 V, 3.6 % under the 3.3 V asked; the block holds "
        "it within 2 %, the reference's own accuracy, VFB of 588 mV to 612 mV [TLV62569 datasheet, SLVSDG1C, "
        f"December 2016, revised October 2017, p 3 and 4; {EQ11_EQ2}]"
    )


@needs_libs
def test_an_input_capacitor_is_held_to_the_value_it_keeps_at_the_greatest_input():
    """With no 16 V capacitor stocked, C1 was CL10A106KP8NNN before the fix, counted at its written 10 uF.
    Its facts keep 0.26677 of it at 5.25 V (between (5.2344, 0.26773) and (5.35535, 0.26029)):
    10 uF x 0.9 x 0.26677 = 2.4 uF, under the 4.7 uF of SLVSDG1C section 8.2.2.5 (page 10)."""
    assert refused(amps=0.5, stock=[SRN, R100, R453, COUT]) == (
        "buck U1: no stocked capacitor gives 4.7 uF of input capacitance at 5.25 V: CL10A106KP8NNN: 10 uF "
        f"less 10 % keeps 2.4 uF at 5.25 V, under 4.7 uF [{INPUT_WHERE}]"
    )


@needs_libs
def test_an_input_capacitor_that_keeps_enough_says_so(tmp_path):
    """A made-up 10 uF capacitor that keeps all its value to 10 V: 10 uF x 0.8 = 8 uF at 5.25 V."""
    facts = facts_with(tmp_path, {**KEEPS_ALL, "mpn": "FIXTURE-10U-FLAT", "kept": [[0, 1.0], [10, 1.0]]})
    cap = blocks.Stock("made up", "FIXTURE-10U-FLAT", "10u flat", C_0603)
    _, block = buck(0.5, stock=[SRN, R100, R453, cap, COUT], facts=facts)
    assert (
        f"C1: 10 uF of input capacitance, X5R, keeps 8 uF at 5.25 V less its tolerance; 4.7 uF asked "
        f"[{INPUT_WHERE}]"
    ) in block.sums


@needs_libs
def test_a_capacitor_whose_facts_give_no_volts_is_passed_over(tmp_path):
    """ratings reads a capacitor with no `volts` (tools/ratings.py CAPACITOR requires no key). A made-up
    100 nF X7R with none, first in the stock, ended in KeyError: volts before the fix."""
    dec = {"kind": "capacitor.ceramic", "mpn": "DECOUPLE-100N", "tolerance": 0.1, "dielectric": "X7R"}
    cap = blocks.Stock("made up", "DECOUPLE-100N", "100n", C_0603)
    d, _ = buck(0.5, stock=[SRN, R100, R453, cap, CIN, COUT], facts=facts_with(tmp_path, dec))
    parts = {p.ref: p.value for p in d.parts}
    assert (parts["C1"], parts["C2"]) == ("10u 16V", "10u 10V")


@needs_libs
def test_a_capacitor_whose_facts_give_no_tolerance_is_passed_over_and_named(tmp_path):
    """A made-up 10 uF X5R with a kept value and no tolerance ended in KeyError: tolerance before the fix."""
    notol = {"kind": "capacitor.ceramic", "mpn": "NOTOL-10U-10V", "volts": 10, "dielectric": "X5R"}
    facts = facts_with(tmp_path, {**notol, "kept": [[0, 1.0], [10, 0.5]]})
    cap = blocks.Stock("made up", "NOTOL-10U-10V", "10u 10V notol", C_0603)
    assert refused(amps=0.5, stock=[SRN, R100, R453, CIN, cap], facts=facts) == (
        "buck U1: no stocked capacitor gives 10 uF of output capacitance for 3.318 V: FIXTURE-10U-16V: its "
        "facts give no value it keeps under voltage; NOTOL-10U-10V: its facts give no tolerance "
        f"[{TABLE4}]"
    )


@needs_libs
@pytest.mark.parametrize(
    ("drop", "says"),
    [("switching", "switching hertz"), ("FB", "FB volts"), ("VIN", "VIN operating")],
)
def test_an_ic_whose_facts_lack_a_number_the_block_reads_is_refused(tmp_path, drop, says):
    """ratings reads the TLV62569's facts without `switching`, without VIN's `operating`, and with FB an
    analog pin, which has no `volts`: each ended in a KeyError before the fix."""
    folder = tmp_path / "facts"
    shutil.copytree(FACTS, folder)
    path = folder / "ti-tlv62569.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if drop == "switching":
        del data["switching"]
    for pin in data["pins"]:
        if pin["name"] == drop == "VIN":
            del pin["operating"]
        elif pin["name"] == drop == "FB":
            pin["role"] = "analog"
            del pin["volts"], pin["amps"]
    path.write_text(json.dumps(data), encoding="utf-8")
    assert len(blocks.ratings.read_facts(folder)) == len(blocks.ratings.read_facts(FACTS))
    assert refused(amps=0.5, facts=folder) == (
        f"buck U1: the facts of TLV62569DBVR give no {says} [ti-tlv62569.json]"
    )


BLOCK_READS = (
    "maker value symbol footprint pins source amps_max vout_min vout_set ilim_min henries henries_low "
    "saturation_margin r2 output_farads kept_share output_span dielectrics input_farads rds_on_high dropout"
).split()


@pytest.mark.parametrize("key", BLOCK_READS)
def test_an_ic_whose_rules_lack_a_number_is_refused(tmp_path, key):
    """The blocks skill: a number you cannot find in the datasheet is not entered, and the block then
    refuses that IC. Before the fix a rules file without ilim_min ended in KeyError: ilim_min."""
    rules = json.loads((ROOT / "rules" / "blocks" / "buck.json").read_text(encoding="utf-8"))
    del rules["ics"][0][key]
    (tmp_path / "buck.json").write_text(json.dumps(rules), encoding="utf-8")
    assert refused(amps=0.5, rules=tmp_path / "buck.json") == (
        f"buck U1: buck.json gives TLV62569DBVR no {key}: the block builds no IC whose numbers are not all "
        "entered"
    )


LOW_VOLTS = {
    "kind": "capacitor.ceramic",
    "mpn": "FIXTURE-10U-3V",
    "tolerance": 0.1,
    "volts": 3.0,
    "dielectric": "X5R",
    "kept": [[0, 1.0], [6, 0.5]],
}
LOW_CAP = blocks.Stock("made up", "FIXTURE-10U-3V", "10u 3V", C_0603)


@needs_libs
def test_an_input_capacitor_rated_under_the_input_is_passed_over(tmp_path):
    """A made-up 10 uF capacitor rated 3 V, first in the stock, is under the 5.25 V input: C1 is the next."""
    d, _ = buck(0.5, stock=[LOW_CAP, *STOCK], facts=facts_with(tmp_path, LOW_VOLTS))
    assert {p.ref: p.value for p in d.parts}["C1"] == "10u 16V"


@needs_libs
def test_an_output_capacitor_rated_under_the_output_is_passed_over(tmp_path):
    """The same capacitor is rated 3 V, under the 3.440367 V the output reaches; its made-up data, which
    runs to 6 V, would keep 1 - 0.5 x 3.44 / 6 = 0.71 of it, and 1 would do. C2 and C3 are the next."""
    d, _ = buck(0.5, stock=[LOW_CAP, *STOCK], facts=facts_with(tmp_path, LOW_VOLTS))
    parts = {p.ref: p.value for p in d.parts}
    assert (parts["C2"], parts["C3"]) == ("10u 10V", "10u 10V")


@needs_libs
def test_a_capacitor_under_x5r_is_passed_over(tmp_path):
    """A made-up 10 uF 16 V Y5V capacitor, first in the stock, is taken neither at the input nor at the
    output (SLVA477C sections 6 and 7, page 5: X5R or better). Its made-up data would keep
    1 - 0.8 x 3.44 / 16 = 0.83 at the output, and 1 would do."""
    y5v = {"kind": "capacitor.ceramic", "mpn": "FIXTURE-10U-Y5V", "tolerance": 0.2, "volts": 16}
    facts = facts_with(tmp_path, {**y5v, "dielectric": "Y5V", "kept": [[0, 1.0], [16, 0.2]]})
    cap = blocks.Stock("made up", "FIXTURE-10U-Y5V", "10u 16V Y5V", C_0805)
    d, _ = buck(0.5, stock=[cap, *STOCK], facts=facts)
    parts = {p.ref: p.value for p in d.parts}
    assert (parts["C1"], parts["C2"]) == ("10u 16V", "10u 10V")


@needs_libs
def test_output_capacitance_over_47_uf_is_refused(tmp_path):
    """A made-up 100 uF capacitor that keeps all its value: 5 uF / (100 uF x 0.8) = 0.06, so 1, and
    1 x 100 uF is over the 47 uF of SLVSDG1C section 8.2.2.5 (page 10). FIXTURE-10U-16V gives no kept
    value."""
    big = {"kind": "capacitor.ceramic", "mpn": "FIXTURE-100U-10V", "tolerance": 0.2, "volts": 10}
    facts = facts_with(tmp_path, {**big, "dielectric": "X5R", "kept": [[0, 1.0], [10, 1.0]]})
    cap = blocks.Stock("made up", "FIXTURE-100U-10V", "100u 10V", "Capacitor_SMD:C_1210_3225Metric")
    assert refused(amps=0.5, stock=[SRN, R100, R453, CIN, cap], facts=facts) == (
        "buck U1: no stocked capacitor gives 10 uF of output capacitance for 3.318 V: FIXTURE-10U-16V: its "
        "facts give no value it keeps under voltage; FIXTURE-100U-10V: 1 x 100 uF = 100 uF, over 47 uF "
        f"[{TABLE4}]"
    )


KEEPS_ALL = {"kind": "capacitor.ceramic", "tolerance": 0.2, "volts": 10, "dielectric": "X5R"}


@needs_libs
def test_1_capacitor_of_10_uf_is_within_10_uf_to_47_uf(tmp_path):
    """A made-up 10 uF capacitor that keeps all its value: 5 uF / (10 uF x 0.8) = 0.625, so 1, and
    1 x 10 uF is the 10 uF the span starts at (SLVSDG1C section 8.2.2.5, page 10)."""
    facts = facts_with(tmp_path, {**KEEPS_ALL, "mpn": "FIXTURE-10U-FLAT", "kept": [[0, 1.0], [10, 1.0]]})
    cap = blocks.Stock("made up", "FIXTURE-10U-FLAT", "10u flat", C_0603)
    d, _ = buck(0.5, stock=[SRN, R100, R453, CIN, cap], facts=facts)
    parts = {p.ref: p.value for p in d.parts}
    assert (parts["C2"], "C3" in parts) == ("10u flat", False)


@needs_libs
def test_output_capacitance_under_10_uf_is_refused(tmp_path):
    """A made-up 4.7 uF capacitor that keeps all its value: 5 uF / (4.7 uF x 0.8) = 5 / 3.76 = 1.33, so 2,
    and 2 x 4.7 uF = 9.4 uF is under the 10 uF of SLVSDG1C section 8.2.2.5 (page 10)."""
    facts = facts_with(tmp_path, {**KEEPS_ALL, "mpn": "FIXTURE-4U7-FLAT", "kept": [[0, 1.0], [10, 1.0]]})
    cap = blocks.Stock("made up", "FIXTURE-4U7-FLAT", "4.7u flat", C_0603)
    assert refused(amps=0.5, stock=[SRN, R100, R453, cap, CIN], facts=facts) == (
        "buck U1: no stocked capacitor gives 10 uF of output capacitance for 3.318 V: FIXTURE-4U7-FLAT: "
        "2 x 4.7 uF = 9.4 uF, under 10 uF; FIXTURE-10U-16V: its facts give no value it keeps under voltage "
        f"[{TABLE4}]"
    )


@needs_libs
def test_more_output_capacitors_than_the_refs_name_is_refused():
    """CL10A106KP8NNN needs 2 (the sums above) and refs['output'] names 1."""
    d = design()
    with pytest.raises(blocks.Refused) as exc:
        blocks.buck(d, ic="TLV62569DBVR", vin=(4.75, 5.25), vout=3.3, amps=0.5, nets=("+5V", "+3V3", "GND"),
                    stock=[SRN, R100, R453, CIN, COUT], facts=FACTS, sch_at=(76.2, 76.2),
                    pcb_at=(108.0, 106.0), refs={"output": "C2"})  # fmt: skip
    assert str(exc.value) == (
        "buck U1: no stocked capacitor gives 10 uF of output capacitance for 3.318 V: FIXTURE-10U-16V: its "
        f"facts give no value it keeps under voltage; CL10A106KP8NNN: 2 are asked and refs['output'] names 1 "
        f"[{TABLE4}]"
    )


@needs_libs
def test_a_load_over_what_the_ic_can_give_by_equation_3_is_refused(tmp_path):
    """A copy of the rules with ILIM(min) 2 A: IMAXOUT = 2 - 0.327538 = 1.672462 A, under 1.8 A of load.
    XAL4020-222MEC holds its peak, 1.8 + 0.327538 = 2.127538 A."""
    rules = json.loads((ROOT / "rules" / "blocks" / "buck.json").read_text(encoding="utf-8"))
    rules["ics"][0]["ilim_min"]["value"] = 2.0
    (tmp_path / "buck.json").write_text(json.dumps(rules), encoding="utf-8")
    with pytest.raises(blocks.Refused) as exc:
        buck(1.8, rules=tmp_path / "buck.json")
    assert str(exc.value) == (
        "buck U1: IMAXOUT = 2 A - 655 mA / 2 = 1.67 A, under the load of 1.8 A "
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


@needs_libs
@pytest.mark.parametrize(
    ("rel", "says"),
    [
        ("t.kicad_sch", "t.kicad_sch is a file write() makes itself"),
        ("./t.kicad_pro", "./t.kicad_pro is a file write() makes itself"),
        (".", ". names no file under the project"),
    ],
)
def test_design_files_never_replace_what_write_makes(tmp_path, rel, says):
    """A path of Design.files that names the schematic, the board, the project or the folder itself is
    refused before anything is written."""
    d = design()
    d.files = {"sim/a.cir": "* a\n", rel: "not a schematic\n"}
    with pytest.raises(ValueError, match=r"^Design\.files: " + says.replace("(", r"\(").replace(")", r"\)")):
        d.write(tmp_path / "p")
    assert not (tmp_path / "p" / "t.kicad_sch").exists()
    assert not (tmp_path / "p" / "sim" / "a.cir").exists()


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
# inductor's saturation current from its facts. SLVA477C's equation 4 gives 0.828 A and 1.33 A (the decks'
# sums): higher than the runs, since equation 1 takes 90 % efficiency, the deck's lossless stage has a
# shorter duty, and the block works the ripple at 2.2 uH less table 4's 30 % while the deck runs 2.2 uH.
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
    no frequency plan. A strict run fails on them, and on the ratings until a `ratings` run holds them
    (the fixture holds a ratings.json; `gates` reads its record), and on nothing else."""
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
