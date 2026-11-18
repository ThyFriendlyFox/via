"""The linear regulator block (tools/blocks_ldo.py, `blocks.ldo`): a fixed 3.3 V LDO added to a design in
1 call, its checks by the equations of TI SLVA079 and the TLV755P datasheet SBVS320D, its parts' facts
from library/facts as `workcenter ratings` reads them.

The sums of the 5 V to 3.3 V block, by hand. The input is 4.75 V to 5.25 V, the ambient 0 C to 30 C, the
pack nasa-eee-inst-002.

    VOUT       both ICs are TLV75533P: xx = 33 is the nominal output, 3.3 V (SBVS320D table 8-1, page 23),
               held to the 3.3 V asked; with the accuracy of 1.5 % (section 5.5, VOUT >= 1 V, page 5),
               3.3 x 0.985 = 3.2505 V to 3.3 x 1.015 = 3.3495 V, the span the deck holds v(out) to

The facts of both ICs give the input 1.45 V to 5.5 V and the ground current 40 uA; the SOT-23-5 (DBV)
has RthetaJA 231.1 C/W, the WSON-6 (DRV) 100.2 C/W (section 5.4, page 5), both a junction of 150 C at
the most (page 4). The pack's rule junction.ic.regulator allows the least of 85 C, 0.7 x 150 = 105 C
and 150 - 40 = 110 C: 85 C.

    dropout    VDO = IOUT x 238 mV / 500 mA (SLVA079 equation 1, page 2; SBVS320D section 5.5, page 6,
               and 7.1.2): at 0.1 A 47.6 mV, 3.3 + 0.0476 = 3.3476 V under 4.75 V; at 0.2 A 95.2 mV, 3.3952 V
    PD         (40e-6 + IOUT) x (5.25 - 3.2505), at the least output the accuracy gives (SBVS320D
               equation 6, page 20; SLVA079 equation 11, page 11): at 0.1 A 0.10004 x 1.9995 = 0.20008 -
               0.00005002 = 0.20002998 W; at 0.2 A 0.20004 x 1.9995 = 0.40008 - 0.00010002 = 0.39997998 W
    TJ         30 + RthetaJA x PD (SBVS320D equation 7; item 7's sum):
               DBV at 0.1 A 30 + 231.1 x 0.20002998 = 30 + 46.226928 = 76.226928 C, under 85 C
               DBV at 0.2 A 30 + 231.1 x 0.39997998 = 30 + 92.435373 = 122.435373 C, over 85 C
               DRV at 0.1 A 30 + 100.2 x 0.20002998 = 30 + 20.043004 = 50.043004 C
               DRV at 0.2 A 30 + 100.2 x 0.39997998 = 30 + 40.077994 = 70.077994 C, under 85 C
               and each from the least ambient, 0 C, within TJ's -40 C to 125 C (5.3, page 4)
    PD(max)    (85 - 30) / 231.1 = 0.237992 W; (85 - 30) / 100.2 = 0.548902 W (SLVA079 equation 10)
    C2         CL10A106KP8NNN keeps, between its points (3.3368, 0.43771) and (3.422325, 0.4264),
               0.43771 - 0.01131 x 0.0127 / 0.085525 = 0.436031 at 3.3495 V; its kept_celsius falls from
               0 C to 30 C, least at 30 C, between (29.58074, 0.9938) and (31.809999, 0.99032):
               0.9938 - 0.00348 x 0.41926 / 2.229259 = 0.993146. 10 uF x 0.9 x 0.436031 x 0.993146 =
               3.897 uF, over 0.47 uF (7.1.1, page 15); 10 uF within 1 uF to 200 uF (5.3, page 4)
    C1         it keeps, between (5.2344, 0.26773) and (5.35535, 0.26029), 0.26773 - 0.00744 x 0.0156 /
               0.12095 = 0.266770 at 5.25 V: 10 uF x 0.9 x 0.266770 x 0.993146 = 2.384 uF, over 0.47 uF;
               10 uF is over the 1 uF of CIN (5.3, page 4)
"""

from __future__ import annotations

import json
import math
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

CITES = {
    "ti-slva079": "equation 1, page 2; equation 8, page 9; equations 10 and 11, page 11",
    "ti-sbvs320": "sections 5.3, 5.4 and 5.5, pages 4 to 6; sections 7.1.1 and 7.1.2, page 15; equations 6 "
    "and 7, page 20; table 8-1, page 23",
    "ti-spra953d": "sections 1.1 and 1.2, pages 2 and 3: what RthetaJA rests on",
}
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
FACTS = BOARDS / "library" / "facts"

needs_libs = pytest.mark.skipif(
    not (kicadgen.SYMBOL_DIR / "Device.kicad_sym").is_file(),
    reason="KiCad symbol libraries are not installed",
)
needs_kicad = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")

C_0603 = "Capacitor_SMD:C_0603_1608Metric"
C_0805 = "Capacitor_SMD:C_0805_2012Metric"
WSON = "Package_SON:WSON-6-1EP_2x2mm_P0.65mm_EP1x1.6mm"
DBV = blocks.Stock("Texas Instruments", "TLV75533PDBVR", "TLV75533P", "Package_TO_SOT_SMD:SOT-23-5")
DRV = blocks.Stock("Texas Instruments", "TLV75533PDRVR", "TLV75533P", WSON)
CIN = blocks.Stock("made up", "FIXTURE-10U-16V", "10u 16V", C_0805)
SAMSUNG = blocks.Stock("Samsung", "CL10A106KP8NNN", "10u 10V", C_0603)
STOCK = [DBV, DRV, CIN, SAMSUNG]

NOTE = "TI SLVA079"
DS = "TLV755P datasheet, SBVS320D"
FACTS_SRC = "TLV755P datasheet, SBVS320D, November 2017, revised September 2024"
DROPOUT = (
    f"{NOTE}, equation 1, page 2; {DS}, section 5.5, VDO at IOUT = 500 mA and -40 C to 125 C, the row "
    "3.3 V <= VOUT < 5.0 V, the column MAX, page 6; section 7.1.2, page 15: VDO scales linearly with the "
    "output current; table 6-1 and section 6.4.1, page 14: VIN > VOUT(NOM) + VDO"
)
PD = f"{NOTE}, equation 11, page 11; {DS}, section 7.2.2.2, equations 6 and 7, page 20"
LIMIT = (
    "85 C, the least of 85 C, 0.7 x 150 C and 150 C - 40 C (nasa-eee-inst-002, section M4, table 4, "
    "page 10 of 10, the column Linear/Mixed Signal and note 2)"
)
TJ_WHERE = f"{NOTE}, equation 10, page 11; {PD}; theta_ja and junction_max of {FACTS_SRC}, p 4 and 5"
CSR = (
    "its CSR is not judged: the datasheet gives no graph of a stable CSR; section 7.1.1, page 15, names X5R "
    f"and X7R ceramics for their small change of ESR [{NOTE}, equation 8, page 9]"
)
OUT_WHERE = (
    f"{DS}, section 7.1.1, page 15, and table 4-1, note 1, page 3: the effective capacitance at the pin "
    "greater than 0.47 uF; section 5.3, Recommended Operating Conditions, COUT, page 4; section 7.1.1, "
    "page 15: X5R- and X7R-type ceramic capacitors"
)
NOMINAL = f"{DS}, table 8-1, Device Nomenclature, page 23: xx in TLV755xxP is the nominal output, 33 = 3.3 V"
ACCURACY = "section 5.5, Output accuracy, VOUT >= 1 V, -1.5 % to 1.5 %, page 5"
TJ_SPAN = f"{DS}, section 5.3, Recommended Operating Conditions, TJ, page 4"
NOT_HOT = "its value over temperature is not judged: its facts give no kept_celsius"


def assumes(theta: str) -> str:
    """What a junction from RthetaJA rests on, as tools/thermal.py says it (SPRA953D)."""
    return (
        f"theta_ja {theta} C/W is the datasheet's test board's: a JEDEC 2s2p board gives a best case and a "
        "1s board a typical one (SPRA953D, section 1.2, page 3); a board unlike the test board changes it "
        "(section 1.1, page 2)"
    )


def regulates(mpn: str) -> str:
    """The first sum of an IC taken: 3.3 V x (1 - 0.015) = 3.2505 V, x (1 + 0.015) = 3.3495 V."""
    return (
        f"U1: {mpn} regulates to VOUT(NOM) = 3.3 V, the 3.3 V asked; with its accuracy, "
        f"3.3 V x (1 +- 0.015) = 3.25 V to 3.35 V [{NOMINAL}; {ACCURACY}]"
    )


IN_WHERE = (
    f"{DS}, table 4-1, note 1, page 3: the effective capacitance at the pin greater than 0.47 uF; "
    "section 5.3, Recommended Operating Conditions, CIN, page 4; section 7.1.1, page 15: X5R- and X7R-type "
    "ceramic capacitors"
)


def design() -> kicadgen.Design:
    d = kicadgen.Design(
        name="t", namespace=uuid.UUID(int=7), outline=(100.0, 100.0, 135.0, 120.0), sheet="A4"
    )
    d.power_nets = {"+5V": "+5V", "+3V3": "+3V3", "GND": "GND"}
    return d


def ldo(  # noqa: PLR0913
    amps: float,
    stock=STOCK,
    vin=(4.75, 5.25),
    vout: float = 3.3,
    ambient=(0, 30),
    facts=FACTS,
    pack: str = "nasa-eee-inst-002",
) -> tuple[kicadgen.Design, object]:
    d = design()
    block = blocks.ldo(
        d,
        vin=vin,
        vout=vout,
        amps=amps,
        ambient=ambient,
        pack=pack,
        nets=("+5V", "+3V3", "GND"),
        stock=stock,
        facts=facts,
        sch_at=(76.2, 76.2),
        pcb_at=(111.0, 108.0),
    )
    return d, block


def ldo_with(tmp_path: Path, rules: dict, facts=FACTS) -> tuple[kicadgen.Design, object]:
    """The block at 0.1 A on the full stock, with its rules written to a file of the test's own."""
    path = tmp_path / "ldo.json"
    path.write_text(json.dumps(rules), encoding="utf-8")
    d = design()
    block = blocks.ldo(
        d, vin=(4.75, 5.25), vout=3.3, amps=0.1, ambient=(0, 30), pack="nasa-eee-inst-002",
        nets=("+5V", "+3V3", "GND"), stock=STOCK, facts=facts, sch_at=(76.2, 76.2), pcb_at=(111.0, 108.0),
        rules=path,
    )  # fmt: skip
    return d, block


def refused(**kwargs) -> str:
    with pytest.raises(blocks.Refused) as exc:
        ldo(**kwargs)
    return str(exc.value)


MADE_UP = {"document": "no datasheet: a part made up for tests/test_blocks_ldo.py", "read": "2026-11-17"}


def facts_with(tmp_path: Path, *parts: dict) -> Path:
    """The fixtures' facts folder and, beside it, parts made up for 1 test."""
    folder = tmp_path / "facts"
    shutil.copytree(FACTS, folder)
    entries = [{**part, "source": {**MADE_UP, "second_reader": "no"}} for part in parts]
    (folder / "zz-made-up.json").write_text(json.dumps({"parts": entries}), encoding="utf-8")
    return folder


@needs_libs
def test_a_tenth_of_an_amp_takes_the_first_stocked_ic_and_checks_what_it_built():
    """At 0.1 A the SOT-23-5 holds every check (the sums above): it is taken, and each sum names its
    equation and page. FIXTURE-10U-16V, first of the capacitors, has no value it keeps under voltage, so
    C1 and C2 are CL10A106KP8NNN."""
    d, block = ldo(0.1)
    assert {p.ref: (p.value, p.footprint.lib_id) for p in d.parts} == {
        "U1": ("TLV75533P", "Package_TO_SOT_SMD:SOT-23-5"),
        "C1": ("10u 10V", C_0603),
        "C2": ("10u 10V", C_0603),
    }
    assert block.sums == [
        regulates("TLV75533PDBVR"),
        f"U1: the input, 4.75 V to 5.25 V, is within IN's 1.45 V to 5.5 V [{FACTS_SRC}, p 3, 4 and 5]",
        f"U1: IOUT of 100 mA, under 500 mA [{DS}, section 5.3, Recommended Operating Conditions, IOUT, "
        "page 4]",
        "U1: VDO = 100 mA x 238 mV / 500 mA = 47.6 mV; VOUT(NOM) + VDO = 3.3 V + 47.6 mV = 3.348 V, under "
        f"the least input, 4.75 V [{DROPOUT}]",
        f"U1: PD = (40 uA + 100 mA) x (5.25 V - 3.2505 V, the least output) = 200 mW [{PD}]",
        f"U1: TJ = 30 C + 231.1 C/W x 200 mW = 76.227 C at the most ambient, under {LIMIT}; PD(max) = "
        f"(85 C - 30 C) / 231.1 C/W = 238 mW; {assumes('231.1')} [{TJ_WHERE}]",
        f"U1: TJ from the least ambient, 0 C, to 76.227 C, within TJ's -40 C to 125 C [{TJ_SPAN}]",
        "C2: CL10A106KP8NNN, X5R, rated 10 V, keeps 0.436 of 10 uF at 3.35 V and 0.993 of it at 0 C to 30 C: "
        "10 uF x 0.9 x 0.436 x 0.993 = 3.9 uF, over 470 nF; 10 uF is within 1 uF to 200 uF "
        f"[{OUT_WHERE}]; {CSR}",
        "C1: CL10A106KP8NNN, X5R, rated 10 V, keeps 0.267 of 10 uF at 5.25 V and 0.993 of it at 0 C to 30 C: "
        f"10 uF x 0.9 x 0.267 x 0.993 = 2.38 uF, over 470 nF; 10 uF is 1 uF or more [{IN_WHERE}]",
    ]


@needs_libs
def test_twice_the_load_takes_the_other_package_since_the_first_junction_passes_its_limit():
    """At 0.2 A the SOT-23-5 reaches 122.435373 C, over 85 C; the WSON-6 reaches 70.077994 C and is taken.
    Its GND pad, pin 7, is on GND with pin 3."""
    d, block = ldo(0.2)
    u1 = next(p for p in d.parts if p.ref == "U1")
    assert u1.footprint.lib_id == WSON
    assert u1.nets == {"6": "+5V", "4": "+5V", "3": "GND", "7": "GND", "1": "+3V3"}
    assert block.sums[0] == (
        f"U1: TLV75533PDBVR passed over: TJ = 30 C + 231.1 C/W x 400 mW = 122.44 C at the most ambient, over "
        f"{LIMIT} [{TJ_WHERE}]"
    )
    assert block.sums[1] == regulates("TLV75533PDRVR")
    assert (
        f"U1: TJ = 30 C + 100.2 C/W x 400 mW = 70.078 C at the most ambient, under {LIMIT}; PD(max) = "
        f"(85 C - 30 C) / 100.2 C/W = 549 mW; {assumes('100.2')} [{TJ_WHERE}]"
    ) in block.sums


@needs_libs
def test_no_stocked_ic_that_holds_the_junction_is_1_line_with_its_sum():
    """With the SOT-23-5 alone in the stock, 0.2 A puts its junction at 122.435373 C, over 85 C."""
    assert refused(amps=0.2, stock=[DBV, CIN, SAMSUNG]) == (
        "ldo U1: no stocked IC holds the spec: TLV75533PDBVR: TJ = 30 C + 231.1 C/W x 400 mW = 122.44 C at "
        f"the most ambient, over {LIMIT} [{TJ_WHERE}]"
    )


@needs_libs
def test_the_dissipation_is_taken_at_the_least_output_the_accuracy_gives():
    """At 0.122 A, at 3.3 V: (40e-6 + 0.122) x 1.95 = 0.237978 W and 30 + 231.1 x 0.237978 = 84.997 C,
    under 85 C. At 3.2505 V, the least output of 1.5 %: 0.12204 x 1.9995 = 0.24408 - 0.00006102 =
    0.24401898 W, and 30 + 231.1 x 0.24401898 = 30 + 56.392786 = 86.392786 C, over 85 C."""
    assert refused(amps=0.122, stock=[DBV, CIN, SAMSUNG]) == (
        "ldo U1: no stocked IC holds the spec: TLV75533PDBVR: TJ = 30 C + 231.1 C/W x 244 mW = 86.393 C at "
        f"the most ambient, over {LIMIT} [{TJ_WHERE}]"
    )


@needs_libs
@pytest.mark.parametrize(
    ("spec", "said"),
    [
        (
            {"vin": (5.25, 3.6)},
            "vin=(5.25, 3.6) is written greatest first: vin is (least, greatest), and the block takes the "
            f"dropout at the least and the dissipation at the greatest [{NOTE}, equation 1, page 2; {NOTE}, "
            "equation 11, page 11]",
        ),
        (
            {"ambient": (30, 0)},
            "ambient=(30, 0) is written greatest first: ambient is (least, greatest) in C, and the block "
            f"takes the junction at the greatest [{NOTE}, equation 10, page 11]",
        ),
        ({"ambient": (0, math.nan)}, "ambient=(0, nan): each number of the spec must be finite"),
        ({"vin": (4.75, math.nan)}, "vin=(4.75, nan): each number of the spec must be finite"),
        ({"amps": math.inf}, "amps=inf: each number of the spec must be finite"),
        ({"vout": math.nan}, "vout=nan: each number of the spec must be finite"),
    ],
)
def test_a_spec_written_greatest_first_or_not_finite_is_refused(spec, said):
    """A range is (least, greatest): the dropout is held at the least input, the dissipation taken at the
    greatest input and the junction at the greatest ambient. A number that is not finite is judged by
    nothing: NaN is under no limit."""
    assert refused(**({"amps": 0.18} | spec)) == f"ldo U1: {said}"


@needs_libs
def test_an_ambient_under_the_ics_least_junction_is_refused():
    """At no load the junction is the ambient: -60 C is under the -40 C of SBVS320D section 5.3, page 4.
    At 0.1 A the junction at 30 C is 76.227 C, under 85 C (the sums above)."""
    assert refused(amps=0.1, ambient=(-60, 30), stock=[DBV, CIN, SAMSUNG]) == (
        "ldo U1: no stocked IC holds the spec: TLV75533PDBVR: TJ from the least ambient, -60 C, to 76.227 C, "
        f"not within TJ's -40 C to 125 C [{TJ_SPAN}]"
    )


@needs_libs
def test_a_junction_over_the_ics_recommended_most_is_passed_over(tmp_path):
    """With the SOT-23-5's TJ span made -40 C to 70 C, its 76.227 C at 0.1 A is over it; the WSON-6's
    50.043004 C is within it, and it is taken."""
    rules = json.loads((ROOT / "rules" / "blocks" / "ldo.json").read_text(encoding="utf-8"))
    rules["ics"][0]["junction_span"]["value"] = [-40, 70]
    d, block = ldo_with(tmp_path, rules)
    assert block.sums[0] == (
        "U1: TLV75533PDBVR passed over: TJ from the least ambient, 0 C, to 76.227 C, not within TJ's -40 C "
        f"to 70 C [{TJ_SPAN}]"
    )
    assert next(p for p in d.parts if p.ref == "U1").footprint.lib_id == WSON


@needs_libs
def test_the_dropout_at_the_least_input_and_the_full_load_is_checked():
    """3.4 V to 3.6 V in, 0.5 A: VDO = 0.5 x 0.238 / 0.5 = 0.238 V and 3.3 + 0.238 = 3.538 V is over
    3.4 V, for both ICs. Their junctions would hold: (40e-6 + 0.5) x 0.3 = 0.150012 W, 30 + 231.1 x
    0.150012 = 64.67 C."""
    miss = (
        "VDO = 500 mA x 238 mV / 500 mA = 238 mV; VOUT(NOM) + VDO = 3.3 V + 238 mV = 3.538 V, not under the "
        f"least input, 3.4 V [{DROPOUT}]"
    )
    assert refused(amps=0.5, vin=(3.4, 3.6)) == (
        f"ldo U1: no stocked IC holds the spec: TLV75533PDBVR: {miss}; TLV75533PDRVR: {miss}"
    )


@needs_libs
def test_an_output_the_ic_does_not_give_is_refused():
    """Both ICs regulate to 3.3 V (table 8-1, page 23), not 3.0 V."""
    miss = f"regulates to VOUT(NOM) = 3.3 V, not the 3 V asked [{NOMINAL}]"
    assert refused(amps=0.1, vout=3.0) == (
        f"ldo U1: no stocked IC holds the spec: TLV75533PDBVR {miss}; TLV75533PDRVR {miss}"
    )


@needs_libs
def test_an_output_inside_the_ics_accuracy_but_not_its_nominal_is_refused():
    """3.26 V lies inside 3.2505 V to 3.3495 V, the span the IC's accuracy gives, but the IC regulates to
    3.3 V: it builds 3.3 V, not the 3.26 V asked, and is refused."""
    assert refused(amps=0.1, vout=3.26, stock=[DBV, CIN, SAMSUNG]) == (
        f"ldo U1: no stocked IC holds the spec: TLV75533PDBVR regulates to VOUT(NOM) = 3.3 V, not the 3.26 V "
        f"asked [{NOMINAL}]"
    )


@needs_libs
def test_an_input_outside_ins_operating_range_is_refused():
    """6 V is over the 5.5 V the facts give for IN."""
    miss = f"the input reaches 6 V, IN operates from 1.45 V to 5.5 V [{FACTS_SRC}, p 3, 4 and 5]"
    assert refused(amps=0.1, vin=(4.5, 6.0), stock=[DBV, CIN, SAMSUNG]) == (
        f"ldo U1: no stocked IC holds the spec: TLV75533PDBVR: {miss}"
    )


@needs_libs
def test_a_load_over_the_ics_recommended_current_is_refused():
    """0.6 A is over the 500 mA of section 5.3."""
    assert refused(amps=0.6, stock=[DBV, CIN, SAMSUNG]) == (
        "ldo U1: no stocked IC holds the spec: TLV75533PDBVR: IOUT of 600 mA is over 500 mA "
        f"[{DS}, section 5.3, Recommended Operating Conditions, IOUT, page 4]"
    )


@needs_libs
@pytest.mark.parametrize(("amps", "shown"), [(0.0, "0 A"), (-0.1, "-100 mA")])
def test_a_load_of_0_or_less_is_refused(amps, shown):
    """The block sizes its dropout and its dissipation for a load: 0 A or less has none."""
    assert refused(amps=amps) == (
        f"ldo U1: a load of {shown}: the block sizes the dropout and the dissipation for a load over 0 A "
        f"[{NOTE}, equations 1 and 11, pages 2 and 11]"
    )


@needs_libs
def test_a_hotter_ambient_takes_the_package_whose_junction_holds():
    """At 0.1 A and 60 C at the most: 60 + 231.1 x 0.20002998 = 106.226928 C, over 85 C, and
    60 + 100.2 x 0.20002998 = 80.043004 C, under it: the WSON-6 is taken."""
    d, _ = ldo(0.1, ambient=(0, 60))
    assert next(p for p in d.parts if p.ref == "U1").footprint.lib_id == WSON


SMALL = {
    "kind": "capacitor.ceramic",
    "mpn": "FIXTURE-1U-SMALL",
    "tolerance": 0.2,
    "volts": 10,
    "dielectric": "X5R",
    "kept": [[0, 1.0], [10, 0.4]],
}
SMALL_CAP = blocks.Stock("made up", "FIXTURE-1U-SMALL", "1u small", C_0603)
WEAK = {**SMALL, "mpn": "FIXTURE-1U-WEAK", "kept": [[0, 1.0], [5, 0.2], [10, 0.1]]}
WEAK_CAP = blocks.Stock("made up", "FIXTURE-1U-WEAK", "1u weak", C_0603)


@needs_libs
def test_a_capacitor_that_keeps_over_047_uf_is_taken(tmp_path):
    """A made-up 1 uF capacitor, first in the stock, keeps 1 - 0.6 x 3.3495 / 10 = 0.79903 of its value at
    3.3495 V: 1 uF x 0.8 x 0.79903 = 0.6392 uF, over 0.47 uF, and at 5.25 V 1 - 0.6 x 0.525 = 0.685:
    0.548 uF, over it too. It is taken at both pins. Its facts give no curve over temperature: each line
    says the value over temperature is not judged."""
    d, block = ldo(0.1, stock=[DBV, SMALL_CAP, SAMSUNG], facts=facts_with(tmp_path, SMALL))
    parts = {p.ref: p.value for p in d.parts}
    assert (parts["C1"], parts["C2"]) == ("1u small", "1u small")
    lines = [s for s in block.sums if s.startswith(("C1:", "C2:"))]
    assert len(lines) == 2
    assert all(NOT_HOT in s for s in lines)


COLD = {
    **SMALL,
    "mpn": "FIXTURE-1U-COLD",
    "kept": [[0, 1.0], [10, 1.0]],
    "kept_celsius": [[-55, 1.0], [25, 1.0]],
}
COLD_CAP = blocks.Stock("made up", "FIXTURE-1U-COLD", "1u cold", C_0603)


@needs_libs
def test_a_capacitor_whose_curve_over_temperature_ends_inside_the_ambient_is_passed_over(tmp_path):
    """A made-up 1 uF that keeps all its value from 0 V to 10 V, 1 uF x 0.8 = 0.8 uF, over 0.47 uF: but its
    curve over temperature ends at 25 C, under the 30 C of the ambient. Its value there is not known: it is
    passed over, and CL10A106KP8NNN is taken."""
    d, _ = ldo(0.1, stock=[DBV, COLD_CAP, SAMSUNG], facts=facts_with(tmp_path, COLD))
    parts = {p.ref: p.value for p in d.parts}
    assert (parts["C1"], parts["C2"]) == ("10u 10V", "10u 10V")


@needs_libs
def test_at_100_c_the_x5r_whose_curve_ends_at_85_c_is_refused():
    """Under the ECSS pack (junction 110 C at the most), 10 mA at 0 C to 100 C: PD = (40e-6 + 0.01) x
    1.9995 = 0.020075 W, TJ = 100 + 231.1 x 0.020075 = 104.639 C, under 110 C and 125 C: the IC holds.
    CL10A106KP8NNN's kept_celsius covers -55 C to 85 C, not 100 C: no capacitor holds C2."""
    assert refused(amps=0.01, ambient=(0, 100), pack="ecss-q-st-30-11c-rev2") == (
        "ldo U1: no stocked capacitor holds C2 at 3.35 V: FIXTURE-10U-16V: its facts give no value it keeps "
        "under voltage; CL10A106KP8NNN: its kept_celsius covers -55 C to 85 C, not the ambient's 0 C to "
        f"100 C [{OUT_WHERE}]"
    )


@needs_libs
def test_a_capacitor_that_keeps_under_047_uf_is_passed_over(tmp_path):
    """A made-up 1 uF capacitor keeps 1 - 0.8 x 3.3495 / 5 = 0.46408 at 3.3495 V: 1 uF x 0.8 x 0.46408 =
    0.3713 uF, and 0.2 - 0.1 x 0.25 / 5 = 0.195 at 5.25 V: 0.156 uF. Both are under 0.47 uF: it is passed
    over, and CL10A106KP8NNN is taken."""
    d, _ = ldo(0.1, stock=[DBV, WEAK_CAP, SAMSUNG], facts=facts_with(tmp_path, WEAK))
    parts = {p.ref: p.value for p in d.parts}
    assert (parts["C1"], parts["C2"]) == ("10u 10V", "10u 10V")


@needs_libs
def test_no_stocked_capacitor_is_1_line_that_says_why_each_was_passed_over(tmp_path):
    """FIXTURE-1U-WEAK keeps 0.3713 uF at 3.3495 V, under 0.47 uF; FIXTURE-10U-16V gives no value it
    keeps; a made-up 220 uF that keeps all of it is over 200 uF; a made-up Y5V is not X5R or X7R. The
    output's capacitor is chosen first."""
    big = {**SMALL, "mpn": "FIXTURE-220U", "kept": [[0, 1.0], [10, 1.0]]}
    y5v = {**SMALL, "mpn": "FIXTURE-Y5V", "dielectric": "Y5V"}
    stock = [
        DBV,
        WEAK_CAP,
        CIN,
        blocks.Stock("made up", "FIXTURE-220U", "220u", "Capacitor_SMD:C_1210_3225Metric"),
        blocks.Stock("made up", "FIXTURE-Y5V", "10u Y5V", C_0603),
    ]
    assert refused(amps=0.1, stock=stock, facts=facts_with(tmp_path, WEAK, big, y5v)) == (
        "ldo U1: no stocked capacitor holds C2 at 3.35 V: FIXTURE-1U-WEAK: 1 uF x 0.8 x 0.464 = 371 nF, "
        "not over 470 nF; FIXTURE-10U-16V: its facts give no value it keeps under voltage; FIXTURE-220U: "
        f"220 uF, outside 1 uF to 200 uF; FIXTURE-Y5V: Y5V, not X5R or X7R [{OUT_WHERE}]"
    )


@needs_libs
def test_a_capacitor_rated_under_the_pins_voltage_is_passed_over(tmp_path):
    """A made-up 1 uF X5R rated 4 V that keeps all its value: over 3.3495 V at the output and taken
    there, under 5.25 V at the input and passed over there."""
    low = {**SMALL, "mpn": "FIXTURE-1U-4V", "volts": 4, "kept": [[0, 1.0], [4, 1.0]]}
    cap = blocks.Stock("made up", "FIXTURE-1U-4V", "1u 4V", C_0603)
    d, _ = ldo(0.1, stock=[DBV, cap, SAMSUNG], facts=facts_with(tmp_path, low))
    parts = {p.ref: p.value for p in d.parts}
    assert (parts["C1"], parts["C2"]) == ("10u 10V", "1u 4V")


@needs_libs
def test_the_block_hands_its_input_its_ambient_and_its_parts_to_ratings():
    """The input range is the net's span in ratings.json and the ambient its most, each with the call it
    came from; each part is a row of parts.csv, the 2 capacitors on 1 row."""
    _, block = ldo(0.1)
    assert block.ratings == {
        "nets": {
            "+5V": {
                "volts": [4.75, 5.25],
                "source": "the input range of the ldo block U1: ldo(vin=(4.75, 5.25))",
            }
        },
        "ambient": {"max": 30, "source": "the ambient of the ldo block U1: ldo(ambient=(0, 30))"},
    }
    assert [(r.value, r.mpn, r.qty) for r in block.rows] == [
        ("TLV75533P", "TLV75533PDBVR", 1),
        ("10u 10V", "CL10A106KP8NNN", 2),
    ]


@needs_libs
def test_the_deck_dissipates_what_the_sums_say_and_names_its_junction_for_the_sim_gate():
    """sim/ldo.cir holds U1 at the greatest input, 5.25 V, into 0.1 A, with its 40 uA of ground current,
    and its output drawn at 3.2505 V, the least of 3.3 V x (1 - 0.015), where it dissipates the most (the
    sums above). vout is drawn, so no bound holds it: the deck says so. sim/thermal.json names U1's power
    to the SIM gate under the same pack; sim/corners.json runs it at 0 C and 30 C, the ambient's ends."""
    _, block = ldo(0.1)
    deck = block.files["sim/ldo.cir"].splitlines()
    assert deck[0] == "ldo: the linear regulator block U1 (TLV75533PDBVR), written by tools/blocks_ldo.py"
    assert (
        "* vout is drawn, not judged: no bound holds it, since the deck does not model U1's regulation."
        in deck
    )
    body = [line for line in deck if not line.startswith("*")][1:]
    assert body == [
        "VIN in 0 DC 5.25",
        "BU1 reg 0 V=3.2505",
        "VU1 reg out DC 0",
        "FU1 in 0 VU1 1",
        "IU1 in 0 DC 40u",
        "ILOAD out 0 DC 0.1",
        ".control",
        "op",
        "let iout = i(vu1)",
        "let vout = v(out)",
        "let p_u1 = -v(in) * i(vin) - v(out) * i(vu1)",
        "print iout vout p_u1",
        ".endc",
        ".end",
    ]
    assert "*   " + block.sums[5] in deck
    assert json.loads(block.files["sim/thermal.json"]) == {
        "pack": "nasa-eee-inst-002",
        "parts": {
            "U1": {
                "mpn": "TLV75533PDBVR",
                "watts": "ldo.p_u1",
                "source": "the deck's input power less its output power",
            }
        },
    }
    assert json.loads(block.files["sim/corners.json"]) == {
        "temperature": {"values": [0, 30], "source": "the ambient of the ldo block U1: ldo(ambient=(0, 30))"}
    }
    assert json.loads(block.files["sim/ldo.expect.json"]) == {
        "iout": {
            "max": 0.5,
            "source": f"U1 TLV75533PDBVR gives 500 mA at the most [{DS}, section 5.3, Recommended Operating "
            "Conditions, IOUT, page 4]",
        },
    }


def _pop(*keys):
    def change(ic):
        entry = ic
        for key in keys[:-1]:
            entry = entry[key]
        del entry[keys[-1]]

    return change


def _set(key, value, field="value"):
    def change(ic):
        ic[key][field] = value

    return change


@needs_libs
@pytest.mark.parametrize(
    ("change", "said"),
    [
        (_pop("csr"), "gives it no csr"),
        (_pop("dissipation", "where"), "gives it no dissipation"),
        (_pop("dropout", "amps"), "gives it no dropout amps"),
        (_pop("pins", "EN"), "gives it no pins EN"),
        (_pop("source", "document"), "gives it no source document"),
        (_pop("junction_span"), "gives it no junction_span"),
        (_set("dropout", 0, "amps"), "holds dropout amps as 0, not a number over 0"),
        (_set("accuracy", "1.5 %"), "holds accuracy as '1.5 %', not a share from 0 to under 1"),
        (_set("accuracy", -0.015), "holds accuracy as -0.015, not a share from 0 to under 1"),
        (_set("output_span", 1e-6), "holds output_span as 1e-06, not 2 numbers over 0, the least first"),
        (_set("amps_max", [0.5]), "holds amps_max as [0.5], not a number over 0"),
        (_set("dielectrics", "X5R"), "holds dielectrics as 'X5R', not a list of names"),
        (
            _set("junction_span", [125, -40]),
            "holds junction_span as [125, -40], not 2 numbers, the least first",
        ),
    ],
)
def test_an_ic_whose_rules_hold_a_number_ldo_cannot_read_is_passed_over_on_1_line(tmp_path, change, said):
    """A key missing, a key inside an entry missing, or a value not of its shape: the SOT-23-5 is passed
    over on 1 line that names it, and the WSON-6 is taken. No entry reaches a sum unread."""
    rules = json.loads((ROOT / "rules" / "blocks" / "ldo.json").read_text(encoding="utf-8"))
    change(rules["ics"][0])
    d, block = ldo_with(tmp_path, rules)
    assert block.sums[0] == (
        f"U1: TLV75533PDBVR passed over: ldo.json {said}: the block builds no IC whose numbers are not all "
        "entered"
    )
    assert next(p for p in d.parts if p.ref == "U1").footprint.lib_id == WSON


@needs_libs
def test_an_ic_whose_rules_lack_a_number_is_passed_over_on_1_line(tmp_path):
    """The SOT-23-5's entry with no vout_nominal and an accuracy with no `where` is passed over, naming
    both; the WSON-6 is then taken."""
    rules = json.loads((ROOT / "rules" / "blocks" / "ldo.json").read_text(encoding="utf-8"))
    del rules["ics"][0]["vout_nominal"]
    del rules["ics"][0]["accuracy"]["where"]
    d, block = ldo_with(tmp_path, rules)
    assert block.sums[0] == (
        "U1: TLV75533PDBVR passed over: ldo.json gives it no vout_nominal, accuracy: the block builds no IC "
        "whose numbers are not all entered"
    )
    assert next(p for p in d.parts if p.ref == "U1").footprint.lib_id == WSON


@needs_libs
def test_a_note_that_lacks_an_equations_page_is_refused_on_1_line(tmp_path):
    """Every sum cites its equation with its page: a note without equation 10 builds nothing."""
    rules = json.loads((ROOT / "rules" / "blocks" / "ldo.json").read_text(encoding="utf-8"))
    del rules["note"]["equations"]["10"]
    with pytest.raises(blocks.Refused) as exc:
        ldo_with(tmp_path, rules)
    assert str(exc.value) == (
        "ldo U1: ldo.json: its note gives no page of equation 10: the block cites each equation it uses with "
        "its page"
    )


@needs_libs
@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda data: data.pop("thermal"), "thermal theta_ja"),
        (lambda data: data["pins"][0].pop("operating"), "IN operating"),
        (lambda data: data["pins"][0].pop("amps"), "IN amps"),
    ],
)
def test_an_ic_whose_facts_lack_what_ldo_reads_is_passed_over_on_1_line(tmp_path, change, said):
    """The SOT-23-5's facts with no RthetaJA, no operating range of IN or no ground current: it is passed
    over on 1 line that names the file and the key, and the WSON-6 (its own facts file) is taken."""
    folder = tmp_path / "facts"
    shutil.copytree(FACTS, folder)
    path = folder / "ti-tlv755p.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")
    rules = json.loads((ROOT / "rules" / "blocks" / "ldo.json").read_text(encoding="utf-8"))
    d, block = ldo_with(tmp_path, rules, facts=folder)
    assert block.sums[0] == (
        f"U1: TLV75533PDBVR passed over: ti-tlv755p.json gives no {said}: the block judges no IC whose facts "
        "lack it"
    )
    assert next(p for p in d.parts if p.ref == "U1").footprint.lib_id == WSON


def test_every_number_of_the_rules_names_where_it_stands():
    """No number of rules/blocks/ldo.json stands without its clause and page."""
    rules = json.loads((ROOT / "rules" / "blocks" / "ldo.json").read_text(encoding="utf-8"))
    for ic in rules["ics"]:
        for key, entry in ic.items():
            if isinstance(entry, dict) and "value" in entry:
                assert "page " in entry["where"], (ic["mpn"], key)
    assert all(isinstance(e["page"], int) for e in rules["note"]["equations"].values())


FIXTURES = {"pass-block-ldo": "TLV75533PDBVR", "pass-block-ldo-2x": "TLV75533PDRVR"}
WRITTEN = ("node.kicad_sch", "node.kicad_pro", "ratings.json", "parts.csv", "sim/ldo.cir",
           "sim/ldo.expect.json", "sim/corners.json", "sim/thermal.json")  # fmt: skip


@needs_kicad
@needs_libs
@pytest.mark.parametrize("name", FIXTURES)
def test_each_fixture_is_what_its_design_file_writes_and_passes_ratings_strict(name, tmp_path):
    """`workcenter design` writes the committed schematic, project, ratings.json, parts.csv and decks; a
    strict `workcenter ratings` of the fixture passes, and the fixture holds the IC the block took."""
    out = tmp_path / name
    made = subprocess.run(
        [sys.executable, str(CLI), "design", str(BOARDS / name / "design.py"), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert made.returncode == 0, made.stdout + made.stderr
    for rel in WRITTEN:
        assert (out / rel).read_bytes() == (BOARDS / name / rel).read_bytes(), rel
    run = subprocess.run(
        [sys.executable, str(CLI), "ratings", str(BOARDS / name), "--out", str(tmp_path / "r"), "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert f",{FIXTURES[name]}," in (BOARDS / name / "parts.csv").read_text(encoding="utf-8")


# The junction the SIM gate gives U1 at its worst run, 30 C: 30 + RthetaJA x p_u1, with p_u1 the deck's
# input power less its output power, 5.25 x (IOUT + 40e-6) - 3.2505 x IOUT, its output drawn at the least
# its accuracy gives. At 0.1 A p_u1 = 0.52521 - 0.32505 = 0.20016 W and 30 + 231.1 x 0.20016 = 30 +
# 46.256976 = 76.256976 C; at 0.2 A p_u1 = 1.05021 - 0.6501 = 0.40011 W and 30 + 100.2 x 0.40011 = 30 +
# 40.091022 = 70.091022 C. The deck counts the ground current at the whole input, equation 6 at the drop
# only: 5.25 x 40e-6 - 1.9995 x 40e-6 = 0.13002 mW more.
JUNCTIONS = {"pass-block-ldo": 76.256976, "pass-block-ldo-2x": 70.091022}


@needs_kicad
@pytest.mark.parametrize("name", FIXTURES)
def test_each_fixture_is_routed_and_its_gates_are_green_strict(name, tmp_path):
    """ERC, DRC (0 unconnected: the router finished), SIM and EXPORT pass with --strict: no warning. The
    SIM gate holds U1's junction at 0 C and 30 C under the pack's 85 C."""
    run = subprocess.run(
        [sys.executable, str(CLI), "--json", "gates", str(BOARDS / name), "--out", str(tmp_path), "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    records = {r["gate"]: r for r in json.loads(run.stdout)}
    assert [records[g]["status"] for g in ("erc", "drc", "sim", "export")] == ["pass"] * 4
    assert records["drc"]["summary"] == "0 errors, 0 warnings (0 unconnected, 0 parity)"
    u1 = records["sim"]["details"]["thermal"]["parts"]["U1"]
    assert (u1["mpn"], u1["limit"], u1["held"]) == (FIXTURES[name], 85, True)
    assert u1["worst"]["ambient"] == 30
    assert u1["worst"]["junction"] == pytest.approx(JUNCTIONS[name], abs=1e-3)
