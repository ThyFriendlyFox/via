"""The microcontroller block (tools/blocks_mcu.py): an MSP430FR5720 with its 32768 Hz crystal, its load
capacitors, its decoupling, its reset network and its programming header, each value from TI SLAA322D,
the MSP430FR572x datasheet SLASE35C, SLAU278AH and SLAU272D (rules/blocks/mcu.json).

The sums of the fixture's block, by hand. The stock holds 2 crystals, in this order:

    ABS07-32.768KHZ-6-T   its shunt C0 is 2.0 pF at the most (ABS07 datasheet, page 1), over the
                          1.6 pF SLASE35C 5.13 note 9 allows (page 22): passed over
    ABS25-32.768KHZ-12-T  C0 1.35 pF typical (page 1); the datasheet states no maximum, so the 1.6 pF
                          is not judged, and equation 1 takes the typical. Its load, 12 pF, is a row
                          of OALF (SLASE35C 5.13, page 22): 300 kohm at 12 pF with XT1DRIVE 3.
    terminals             ABS25 page 2, Electrode Arrangement: the crystal is between pins 1 and 4,
                          pins 2 and 3 float. XIN goes to pad 1, XOUT to pad 4, and the symbol is
                          KiCad's Crystal_GND23 (crystal on pins 1 and 4), its pins 2 and 3 open.
    equation 1            ESR = 50 kohm x (1 + 1.35 / 12)^2 = 50 x 1.1125^2 = 50 x 1.23765625
                          = 61.8828 kohm
    equation 5            SF = 300 / 61.8828 = 4.8478, 3 or more: safe by table 2 (page 11)
    twice the ESR         100 kohm x 1.23765625 = 123.7656 kohm, SF = 300 / 123.7656 = 2.4239: under 3
    equation 3            CL1 = 2 x CLoad - CParasitic. CParasitic is the pin's 2 pF (note 9) and the
                          board's 1 pF: 3 pF. CL1 = 2 x 12 - 3 = 21 pF. The stock has 18p, 22p, 27p,
                          all C0G of 5 % (Vishay 45199, page 3): 22p is 1 pF away, within its
                          0.05 x 22 = 1.1 pF; 18p is 3 pF away, over its 0.9 pF; 27p 6 pF, over its
                          1.35 pF. CLoad = (22 + 3) / 2 = 12.5 pF
    VCC                   (10 uF + 2 x 100 nF) / 470 nF = 10.2 / 0.47 = 21.70, 10 or more (5.3, page 14)
    reset                 47k up; of 1n and 4.7n, 4.7n is over the 2.2 nF of SLAU278AH note B (page 23),
                          1n is 0.1 nF from the 1.1 nF the figure shows
"""

from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import blocks  # noqa: E402
import blocks_mcu  # noqa: E402
import kicadgen  # noqa: E402
import ratings  # noqa: E402

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
R_0603 = "Resistor_SMD:R_0603_1608Metric"
X_ABS07 = "Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm"
X_ABS25 = "Crystal:Crystal_SMD_Abracon_ABS25-4Pin_8.0x3.8mm"

ABS07 = blocks.Stock("Abracon", "ABS07-32.768KHZ-6-T", "32.768k ABS07", X_ABS07)
ABS25 = blocks.Stock("Abracon", "ABS25-32.768KHZ-12-T", "32.768k ABS25", X_ABS25)
TWICE = blocks.Stock("made up", "FIXTURE-32K768-100K", "32.768k 100k", X_ABS25)
C18 = blocks.Stock("Vishay", "VJ0603A180JXAAC", "18p", C_0603)
C22 = blocks.Stock("Vishay", "VJ0603A220JXAAC", "22p", C_0603)
C27 = blocks.Stock("Vishay", "VJ0603A270JXAAC", "27p", C_0603)
STOCK = [
    ABS07,
    ABS25,
    C18,
    C22,
    C27,
    blocks.Stock("made up", "FIXTURE-10U-16V", "10u 16V", C_0805),
    blocks.Stock("Vishay", "VJ0603Y104KXJAC", "100n", C_0603),
    blocks.Stock("Vishay", "VJ0805Y474KXJAC", "470n", C_0805),
    blocks.Stock("Vishay", "VJ0603Y102KXJAC", "1n", C_0603),
    blocks.Stock("Vishay", "CRCW060347K0FKEA", "47k", R_0603),
]
NOTE = "TI SLAA322D"
DS = "MSP430FR572x datasheet, SLASE35C"
EQ5 = (
    f"{NOTE}, equation 5, page 11; table 2, page 11: SF under 2 is unsafe, 2 to 3 suitable, 3 to 5 safe, "
    "5 and over very safe; the block asks the least the table calls safe, 3; "
    f"{DS}, section 5.13, OALF at 32768 Hz: 210 kohm at CL,eff 6 pF with XT1DRIVE 0, 300 kohm at CL,eff "
    "12 pF with XT1DRIVE 3, page 22"
)
SHUNT = f"{DS}, section 5.13, note 9: a maximum shunt capacitance of 1.6 pF, page 22"
EQ3 = (
    f"{NOTE}, equation 3, page 4; {DS}, section 5.13, note 9: parasitic bond and package capacitance of "
    "approximately 2 pF per pin, page 22"
)
MATCH = (
    f"{NOTE}, section 2.1, page 5: the wrong load capacitors give an incorrect oscillation frequency "
    "(figure 5); the block takes a load capacitor whose value lies within its own tolerance of CL1"
)
DIELECTRIC = (
    "Vishay VJ Commercial Series datasheet, document 45199, revision 08-May-2026, page 1: C0G (NP0) holds "
    "0 ppm/C +/- 30 ppm/C from -55 C to +125 C, X7R +/- 15 % over the same span; the block takes C0G"
)
LOAD = f"{EQ3}; {MATCH}; {DIELECTRIC}"
ABS25_SRC = "Abracon ABS25 datasheet, REVISED: 09-30-19"
ABS25_PINS = (
    f"{ABS25_SRC}, page 2, outline drawing, Electrode Arrangement: the crystal between pins 1 and 4, "
    "pins 2 and 3 not connected to GND (floating)"
)
RESET = "SLAU278AH, figure 2-3, R1, page 23; SLAU272D, table 1-4, RST/NMI: a 47-kohm pullup, page 40"


def design() -> kicadgen.Design:
    d = kicadgen.Design(
        name="t", namespace=uuid.UUID(int=5), outline=(100.0, 100.0, 140.0, 130.0), sheet="A4"
    )
    d.power_nets = {"+3V3": "+3V3", "GND": "GND"}
    return d


def mcu(stock=STOCK, stray=1e-12, vcc=(3.135, 3.465), facts=FACTS, refs=None, nets=("+3V3", "GND"), **more):  # noqa: PLR0913
    d = design()
    block = blocks.mcu(
        d,
        ic="MSP430FR5720IRGE",
        vcc=vcc,
        stray=stray,
        nets=nets,
        stock=stock,
        facts=facts,
        sch_at=(50.8, 63.5),
        pcb_at=(105.0, 105.0),
        refs=refs,
        **more,
    )
    return d, block


def refused(**kwargs) -> str:
    with pytest.raises(blocks.Refused) as exc:
        mcu(**kwargs)
    return str(exc.value)


MADE_UP = {"document": "no datasheet: a part made up for tests/test_blocks_mcu.py", "read": "2026-11-17"}


def facts_with(tmp_path: Path, *parts: dict) -> Path:
    folder = tmp_path / "facts"
    shutil.copytree(FACTS, folder)
    entries = [{**part, "source": {**MADE_UP, "second_reader": "no"}} for part in parts]
    (folder / "zz-made-up.json").write_text(json.dumps({"parts": entries}), encoding="utf-8")
    return folder


def test_a_crystals_facts_are_read_by_ratings():
    """The crystal kind of ratings' facts: ABS25-32.768KHZ-12's entry holds 50 kohm and 12 pF."""
    found = ratings.read_facts(FACTS)
    entry = next(f for f in found if f.data.get("match") == "ABS25-32.768KHZ-12*")
    assert (entry.kind, entry.data["ohms_esr"], entry.data["farads_load"]) == ("crystal", 50000, 12e-12)


@needs_libs
def test_the_first_crystal_that_starts_with_a_safe_factor_is_taken():
    """ABS07 is passed over on its shunt; ABS25 holds SF 4.848 by equations 1 and 5 (the sums above)."""
    d, block = mcu()
    parts = {p.ref: p.value for p in d.parts}
    assert parts == {
        "U1": "MSP430FR5720",
        "Y1": "32.768k ABS25",
        "C1": "22p",
        "C2": "22p",
        "C3": "10u 16V",
        "C4": "100n",
        "C5": "100n",
        "C6": "470n",
        "R1": "47k",
        "C7": "1n",
        "J2": "SBW",
    }
    assert block.sums[:4] == [
        f"Y1: ABS07-32.768KHZ-6-T is passed over: its shunt capacitance, 2 pF at the most, is over 1.6 pF "
        f"[{SHUNT}]",
        f"Y1: ESR = 50 kohm x (1 + 1.35 pF / 12 pF)^2 = 61.9 kohm [{NOTE}, equation 1, page 3]; "
        f"SF = 300 kohm / 61.9 kohm = 4.848, 3 or more [{EQ5}]",
        "Y1: its shunt capacitance is not judged against 1.6 pF: the facts of ABS25-32.768KHZ-12-T give C0 "
        f"1.35 pF typical and no maximum, and equation 1 takes the typical [{ABS25_SRC}; {SHUNT}]",
        f"C1, C2: CL1 = 2 x 12 pF - (2 pF + 1 pF) = 21 pF; 22p, C0G, is 1 pF from it, within its 5 % "
        f"(1.1 pF); CLoad = (22 pF + 3 pF) / 2 = 12.5 pF [{LOAD}]",
    ]
    assert any(s.startswith(f"Y1: XIN on pad 1, XOUT on pad 4 [{ABS25_PINS}]; ") for s in block.sums)
    assert (
        "C3, C4, C5: (10 uF + 2 x 100 nF) / 470 nF = 21.7, 10 or more [MSP430FR572x datasheet, SLASE35C, "
        "section 5.3, CVCC / CVCORE, the column MIN, page 14]" in block.sums
    )
    assert any(
        s.startswith("Y1: its drive level is not judged: neither SLAA322D nor SLASE35C") for s in block.sums
    )


@needs_libs
def test_twice_the_esr_alone_is_refused_with_equation_5():
    """100 kohm x 1.23765625 = 123.77 kohm; SF = 300 / 123.77 = 2.424, under 3."""
    assert refused(stock=[TWICE, *STOCK[2:]]) == (
        "mcu U1: no stocked crystal starts with a safety factor of 3: FIXTURE-32K768-100K: ESR = 100 kohm x "
        f"(1 + 1.35 pF / 12 pF)^2 = 124 kohm, SF = 300 kohm / 124 kohm = 2.424 [{NOTE}, equation 1, page 3; "
        f"{EQ5}]"
    )


@needs_libs
def test_twice_the_esr_first_in_the_stock_takes_the_next_crystal():
    """The made-up crystal of 100 kohm is passed over (SF 2.424) and ABS25 is taken (SF 4.848)."""
    d, block = mcu(stock=[TWICE, ABS25, *STOCK[2:]])
    assert {p.ref: p.value for p in d.parts}["Y1"] == "32.768k ABS25"
    assert block.sums[0] == (
        "Y1: FIXTURE-32K768-100K is passed over: ESR = 100 kohm x (1 + 1.35 pF / 12 pF)^2 = 124 kohm, "
        f"SF = 300 kohm / 124 kohm = 2.424, under 3 [{NOTE}, equation 1, page 3; {EQ5}]"
    )


@needs_libs
def test_a_crystal_whose_load_has_no_allowance_in_the_datasheet_is_passed_over(tmp_path):
    """A made-up crystal of 9 pF: OALF is stated at 6 pF and 12 pF only (SLASE35C 5.13, page 22)."""
    nine = {"kind": "crystal", "mpn": "FIXTURE-32K-9P", "hertz": 32768, "ohms_esr": 30000}
    facts = facts_with(tmp_path, {**nine, "farads_load": 9e-12, "farads_shunt": 1e-12})
    stock = [blocks.Stock("made up", "FIXTURE-32K-9P", "32.768k 9p", X_ABS25), ABS25, *STOCK[2:]]
    d, block = mcu(stock=stock, facts=facts)
    assert {p.ref: p.value for p in d.parts}["Y1"] == "32.768k ABS25"
    assert block.sums[0] == (
        "Y1: FIXTURE-32K-9P is passed over: its load, 9 pF, is no load OALF is stated at (6 pF, 12 pF) "
        f"[{DS}, section 5.13, OALF at 32768 Hz: 210 kohm at CL,eff 6 pF with XT1DRIVE 0, 300 kohm at CL,eff "
        "12 pF with XT1DRIVE 3, page 22]"
    )


@needs_libs
def test_a_crystal_with_no_shunt_capacitance_in_its_facts_is_passed_over(tmp_path):
    """Equation 1 needs C0: a crystal whose facts give none cannot be judged, and is not taken."""
    bare = {"kind": "crystal", "mpn": "FIXTURE-32K-NOC0", "hertz": 32768, "ohms_esr": 30000}
    facts = facts_with(tmp_path, {**bare, "farads_load": 12e-12})
    stock = [blocks.Stock("made up", "FIXTURE-32K-NOC0", "32.768k", X_ABS25), *STOCK[2:]]
    assert refused(stock=stock, facts=facts).startswith(
        "mcu U1: no stocked crystal starts with a safety factor of 3: FIXTURE-32K-NOC0: its facts give no "
        "shunt capacitance, which equation 1 needs ["
    )


@needs_libs
def test_the_load_capacitor_is_the_stocks_nearest_within_its_own_tolerance_of_equation_3():
    """With 3.4 pF of board: CL1 = 24 - (2 + 3.4) = 18.6 pF; 18p is 0.6 pF away, within its
    0.05 x 18 = 0.9 pF; 22p is 3.4 pF away, over its 1.1 pF: 18p, and CLoad = (18 + 5.4) / 2 = 11.7 pF."""
    d, block = mcu(stray=3.4e-12)
    assert {p.ref: p.value for p in d.parts}["C1"] == "18p"
    assert block.sums[3] == (
        "C1, C2: CL1 = 2 x 12 pF - (2 pF + 3.4 pF) = 18.6 pF; 18p, C0G, is 0.6 pF from it, within its 5 % "
        f"(0.9 pF); CLoad = (18 pF + 5.4 pF) / 2 = 11.7 pF [{LOAD}]"
    )


@needs_libs
def test_a_load_capacitor_off_cl1_by_more_than_its_tolerance_is_refused():
    """With 3 pF of board: CL1 = 24 - 5 = 19 pF. 18p is 1 pF away, over its 0.05 x 18 = 0.9 pF; 22p is
    3 pF away, over its 1.1 pF; 27p 8 pF, over its 1.35 pF. None holds CLoad to the crystal's 12 pF."""
    assert refused(stray=3e-12) == (
        "mcu U1: CL1 = 2 x 12 pF - (2 pF + 3 pF) = 19 pF for ABS25-32.768KHZ-12-T, and no stocked capacitor "
        "is C0G, rated for 3.465 V and within its own tolerance of it: 18p is 1 pF from it, over its 5 % "
        f"(0.9 pF); 22p is 3 pF from it, over its 5 % (1.1 pF); 27p is 8 pF from it, over its 5 % (1.35 pF) "
        f"[{LOAD}]"
    )


@needs_libs
def test_a_stock_with_no_pf_capacitor_is_refused_not_given_a_1_nf_load():
    """The reviewer's case: no 18p, 22p or 27p. The nearest to 21 pF are 1n (X7R, Vishay 45199 page 3:
    Y is X7R), then 100n and 470n: none is C0G, and the block refuses where it took 1n (CLoad 502 pF)."""
    message = refused(stock=[ABS25, *STOCK[5:]])
    assert message.startswith(
        "mcu U1: CL1 = 2 x 12 pF - (2 pF + 1 pF) = 21 pF for ABS25-32.768KHZ-12-T, and no stocked capacitor "
        "is C0G, rated for 3.465 V and within its own tolerance of it: 1n: its dielectric is X7R, not C0G; "
    )
    assert message.endswith(f"[{LOAD}]")


@needs_libs
def test_only_a_27p_in_stock_is_refused():
    """CL1 = 21 pF; 27p is 6 pF away, over its 0.05 x 27 = 1.35 pF: it would give CLoad = (27 + 3) / 2 =
    15 pF on a crystal of 12 pF."""
    message = refused(stock=[ABS25, C27, *STOCK[5:]])
    assert "it: 27p is 6 pF from it, over its 5 % (1.35 pF); 1n: its dielectric is X7R, not C0G; " in message


@needs_libs
def test_a_capacitor_whose_facts_give_no_volts_is_named_and_not_taken(tmp_path):
    """A made-up 22p of C0G and 5 % with no volts in its facts cannot be judged at 3.465 V: it is named
    with the reason, and the 1n of X7R is not taken in its place."""
    bare = {"kind": "capacitor.ceramic", "mpn": "FIXTURE-22P-NOV", "tolerance": 0.05, "dielectric": "C0G"}
    facts = facts_with(tmp_path, bare)
    stock = [ABS25, blocks.Stock("made up", "FIXTURE-22P-NOV", "22p", C_0603), *STOCK[5:]]
    assert "of it: 22p: its facts give no volts; 1n: its dielectric is X7R, not C0G; " in refused(
        stock=stock, facts=facts
    )


@needs_libs
def test_a_board_whose_strays_reach_the_load_is_refused_with_equation_3():
    """With 23 pF of board: CL1 = 24 - 25 = -1 pF, no capacitor at all."""
    assert refused(stray=23e-12) == (
        "mcu U1: CL1 = 2 x 12 pF - (2 pF + 23 pF) = -1 pF for ABS25-32.768KHZ-12-T: the pins and the board "
        f"hold more than its load [{EQ3}]"
    )


@needs_libs
def test_a_reset_capacitor_over_2_2_nf_is_passed_over(tmp_path):
    """A made-up 4.7 nF, first in the stock, is over the 2.2 nF of SLAU278AH note B: 1n is taken."""
    big = {"kind": "capacitor.ceramic", "mpn": "FIXTURE-4N7", "tolerance": 0.1, "volts": 16}
    facts = facts_with(tmp_path, {**big, "dielectric": "X7R"})
    stock = [blocks.Stock("made up", "FIXTURE-4N7", "4.7n", C_0603), *STOCK]
    d, _ = mcu(stock=stock, facts=facts)
    assert {p.ref: p.value for p in d.parts}["C7"] == "1n"


@needs_libs
def test_a_vcore_capacitor_looser_than_20_percent_is_refused(tmp_path):
    """SLASE35C 5.3 note 2 asks 20 % or better: a made-up 470 nF of 30 % is not taken."""
    loose = {"kind": "capacitor.ceramic", "mpn": "FIXTURE-470N-30", "tolerance": 0.3, "volts": 16}
    facts = facts_with(tmp_path, {**loose, "dielectric": "Y5V"})
    stock = [s for s in STOCK if s.value != "470n"] + [
        blocks.Stock("made up", "FIXTURE-470N-30", "470n", C_0805)
    ]
    assert refused(stock=stock, facts=facts) == (
        "mcu U1: no stocked capacitor of 470 nF, 20 % or better, rated for 3.465 V: FIXTURE-470N-30 is 30 % "
        f"[{DS}, section 5.3, CVCORE, page 14; {DS}, section 5.3, note 2: a capacitor tolerance of 20 % or "
        "better, page 14]"
    )


@needs_libs
def test_a_supply_outside_the_ics_range_is_refused():
    """3.7 V is over the 3.6 V of SLASE35C 5.3 (page 14), which the IC's facts hold."""
    assert refused(vcc=(3.3, 3.7)) == (
        "mcu U1: the supply reaches 3.7 V, DVCC of MSP430FR5720IRGE operates from 2 V to 3.6 V "
        f"[{DS}, May 2014, revised December 2017, p 14]"
    )


@needs_libs
def test_a_supply_under_the_ics_range_is_refused():
    """1.9 V is under the 2.0 V of SLASE35C 5.3 (page 14), which the IC's facts hold."""
    assert refused(vcc=(1.9, 3.3)) == (
        "mcu U1: the supply reaches 1.9 V, DVCC of MSP430FR5720IRGE operates from 2 V to 3.6 V "
        f"[{DS}, May 2014, revised December 2017, p 14]"
    )


@needs_libs
def test_bad_arguments_are_refused_with_their_names_and_values():
    """A supply range low above high, a stray that is no finite number, and 1 net for supply and
    ground are each refused, not built."""
    assert refused(vcc=(3.6, 2.0)) == "mcu U1: vcc = (3.6, 2): its low end is over its high end"
    assert refused(stray=math.nan) == (
        f"mcu U1: stray = nan: a finite capacitance of 0 F or more is asked [{EQ3}]"
    )
    assert (
        refused(nets=("GND", "GND")) == "mcu U1: nets = ('GND', 'GND'): the supply and the ground are 1 net"
    )


@needs_libs
def test_a_ratio_of_vcc_to_vcore_under_the_rules_is_refused(tmp_path):
    """Rules that ask a ratio of 30: (10 uF + 2 x 100 nF) / 470 nF = 21.70, under 30."""
    rules = json.loads(blocks_mcu.RULES.read_text(encoding="utf-8"))
    rules["ics"][0]["vcc_ratio"]["value"] = 30
    path = tmp_path / "mcu.json"
    path.write_text(json.dumps(rules), encoding="utf-8")
    assert refused(rules=path) == (
        "mcu U1: (10 uF + 2 x 100 nF) / 470 nF = 21.7, under 30 [MSP430FR572x datasheet, SLASE35C, "
        "section 5.3, CVCC / CVCORE, the column MIN, page 14]"
    )


@needs_libs
def test_the_crystal_is_wired_to_the_terminals_its_maker_names():
    """ABS25 page 2: the crystal is between pins 1 and 4. Y1 is KiCad's Crystal_GND23 with XIN on pin 1
    and XOUT on pin 4; pins 2 and 3 are left open, as Abracon's floating pins."""
    d, _ = mcu()
    y1 = next(p for p in d.parts if p.ref == "Y1")
    assert (y1.symbol.lib_id, y1.nets) == ("Device:Crystal_GND23", {"1": "U1_XIN", "4": "U1_XOUT"})


@needs_libs
def test_a_crystal_whose_facts_give_no_terminals_is_passed_over(tmp_path):
    """The block cannot know which pads of the footprint hold the crystal: it does not guess."""
    bare = {"kind": "crystal", "mpn": "FIXTURE-32K-NOPADS", "hertz": 32768, "ohms_esr": 30000}
    facts = facts_with(tmp_path, {**bare, "farads_load": 12e-12, "farads_shunt": 1e-12})
    stock = [blocks.Stock("made up", "FIXTURE-32K-NOPADS", "32.768k", X_ABS25), ABS25, *STOCK[2:]]
    d, block = mcu(stock=stock, facts=facts)
    assert {p.ref: p.value for p in d.parts}["Y1"] == "32.768k ABS25"
    assert block.sums[0].startswith(
        "Y1: FIXTURE-32K-NOPADS is passed over: its facts name no 2 terminal pads, which XIN and XOUT "
        "are wired to ["
    )


def check(d, **change) -> list[str]:
    """blocks_mcu.check on a design, with the ABS25 facts and the 5 % of the C0G load capacitors."""
    crystal = next(f for f in ratings.read_facts(FACTS) if f.data.get("match") == "ABS25-32.768KHZ-12*")
    args = {"stray": 1e-12, "crystal": crystal, "tolerance": 0.05} | change
    return blocks_mcu.check(d, "U1", blocks_mcu.chip_of("MSP430FR5720IRGE"), ("+3V3", "GND"), **args)


def built(**values) -> kicadgen.Design:
    """The fixture's block, with the parts named set to other values, or taken off for None."""
    d, _ = mcu()
    d.parts = [p for p in d.parts if values.get(p.ref, "") is not None]
    for p in d.parts:
        p.value = values.get(p.ref, p.value)
    return d


@needs_libs
def test_the_block_checks_the_board_it_built():
    """check() reads the parts back from the design: as built, nothing; with C2 taken off, XOUT has no
    load capacitor."""
    assert check(built()) == []
    assert check(built(C2=None)) == [f"U1_XOUT has no capacitor to GND, and XIN has 22p [{EQ3}]"]


@needs_libs
def test_check_finds_the_crystal_on_pads_that_are_not_its_terminals():
    """The reviewer's board: XOUT on pad 2, which Abracon marks floating, and pad 4 open."""
    d = built()
    next(p for p in d.parts if p.ref == "Y1").nets = {"1": "U1_XIN", "2": "U1_XOUT"}
    assert check(d) == [
        f"Y1: its terminals, pads 1 and 4, carry U1_XIN and none, not U1_XIN and U1_XOUT [{ABS25_PINS}]"
    ]
    assert check(built(Y1=None)) == [f"Y1: no crystal on the board [{EQ3}]"]


@needs_libs
def test_check_holds_the_load_capacitors_to_equation_3():
    """2 unequal ones; 2 of 100 nF: |100 nF - 21 pF| = 99.98 nF, over 0.05 x 100 nF = 5 nF, and
    CLoad = (100 nF + 3 pF) / 2 = 50.0015 nF, printed 50 nF, on a crystal of 12 pF."""
    assert check(built(C2="27p")) == [f"the 2 load capacitors differ: equation 3 takes 2 equal ones [{EQ3}]"]
    assert check(built(C1="100n", C2="100n")) == [
        "C1, C2: 100 nF is 100 nF from CL1 = 21 pF, over its 5 % (5 nF): CLoad = (100 nF + 3 pF) / 2 = "
        f"50 nF, not 12 pF [{EQ3}; {MATCH}]"
    ]


@needs_libs
def test_check_holds_vcore_and_the_ratio_at_vcc():
    """C6 off: VCORE holds 0 F, under 470 nF. C3 of 1 uF: 1 uF + 2 x 100 nF = 1.2 uF, and 1.2 / 0.47 =
    2.55, under 10."""
    assert check(built(C6=None)) == [
        f"U1_VCORE holds 0 F to GND, under 470 nF [{DS}, section 5.3, CVCORE, page 14]"
    ]
    assert check(built(C3="1u")) == [
        f"+3V3 holds 1.2 uF, under 10 x 470 nF [{DS}, section 5.3, CVCC / CVCORE, the column MIN, page 14]"
    ]


@needs_libs
def test_check_holds_the_reset_network_and_the_header():
    """R1 off; R1 of 0 ohm (not 47 kohm); C7 of 4.7 nF, over 2.2 nF; J2 off."""
    assert check(built(R1=None)) == [f"no pull-up from U1_RST to +3V3 [{RESET}]"]
    assert check(built(R1="0")) == [f"U1_RST is pulled up to +3V3 by 0 ohm, not 47 kohm [{RESET}]"]
    assert check(built(C7="4.7n")) == [
        "U1_RST holds 4.7 nF to GND, not 100 pF to 2.2 nF [SLAU278AH, figure 2-3, C1 and its note B: 1.1 nF "
        "typical, 0.1 nF to 2.2 nF, page 23; SLAU272D, table 1-4, note 2: not over 2.2 nF in Spy-Bi-Wire "
        "mode, page 40]"
    ]
    assert check(built(J2=None)) == [
        "J2 does not join {'1': 'U1_RST', '4': '+3V3', '7': 'U1_TEST', '9': 'GND'} [SLAU278AH, figure 2-3: "
        "pin 1 TDO/TDI to RST/NMI/SBWTDIO, pin 7 TCK to TEST/SBWTCK, pin 9 GND, and pin 4 VCC TARGET for a "
        "board with its own supply (connection J1, note A), page 23]"
    ]


@needs_libs
def test_each_value_is_cited_to_its_own_document():
    """The bulk and bypass capacitors and the reset come from SLAU278AH: no SLASE35C before them."""
    _, block = mcu()
    assert (
        "C3, C4, C5: 10 uF and 2 x 100 nF at DVCC and AVCC [SLAU278AH, figure 2-3, C2 at VCC/AVCC/DVCC, "
        "page 23; SLAU278AH, figure 2-3, C3 at VCC/AVCC/DVCC, page 23; the block puts 1 on each of the 2 "
        "supply pins the figure joins]" in block.sums
    )
    assert not any("SLASE35C, SLAU" in s for s in block.sums)


def test_the_committed_fixture_wires_y1_to_pads_1_and_4():
    """node.kicad_pcb of pass-block-mcu: Y1's pad 1 is on /U1_XIN, pad 4 on /U1_XOUT, pads 2 and 3 on
    no net of the oscillator (ABS25 page 2)."""
    text = (BOARDS / "pass-block-mcu" / "node.kicad_pcb").read_text(encoding="utf-8")
    at = text.find('(property "Reference" "Y1"')
    block = text[text.rfind("(footprint ", 0, at) : text.find("\n\t(footprint ", at)]
    pads = {}
    for m in re.finditer(r'\(pad "(\d+)".*?(?=\n\t\t\(pad |\Z)', block, re.S):
        net = re.search(r'\(net (?:\d+ )?"([^"]*)"\)', m.group(0))
        pads[m.group(1)] = net.group(1) if net else None
    assert (pads["1"], pads["4"]) == ("/U1_XIN", "/U1_XOUT")
    assert not {pads["2"], pads["3"]} & {"/U1_XIN", "/U1_XOUT"}


@needs_libs
def test_the_block_hands_its_supply_and_its_parts_to_ratings():
    """The supply range is the net's span in ratings.json; RST and TEST, which the programming tool drives
    at the board's own supply (SLAU278AH 2.1, page 20), span 0 V to the supply's 3.465 V; each part is a
    row of parts.csv."""
    _, block = mcu()
    tool = (
        "J2: SLAU278AH, section 2.1, page 20: the tool senses the board's own VCC on pin 4 and adjusts its "
        "output signals to it"
    )
    assert block.ratings == {
        "nets": {
            "+3V3": {
                "volts": [3.135, 3.465],
                "source": "the supply of the mcu block U1: mcu(vcc=(3.135, 3.465))",
            },
            "U1_RST": {"volts": [0, 3.465], "source": tool},
            "U1_TEST": {"volts": [0, 3.465], "source": tool},
        }
    }
    assert [(r.value, r.mpn, r.qty) for r in block.rows] == [
        ("MSP430FR5720", "MSP430FR5720IRGE", 1),
        ("32.768k ABS25", "ABS25-32.768KHZ-12-T", 1),
        ("22p", "VJ0603A220JXAAC", 2),
        ("10u 16V", "FIXTURE-10U-16V", 1),
        ("100n", "VJ0603Y104KXJAC", 2),
        ("470n", "VJ0805Y474KXJAC", 1),
        ("47k", "CRCW060347K0FKEA", 1),
        ("1n", "VJ0603Y102KXJAC", 1),
        ("SBW", "", 1),
    ]


def test_every_number_of_the_rules_names_where_it_stands():
    """Each value of rules/blocks/mcu.json has a `where` with a page, and each equation its page."""
    rules = json.loads((ROOT / "rules" / "blocks" / "mcu.json").read_text(encoding="utf-8"))
    for ic in rules["ics"]:
        for key, entry in ic.items():
            if isinstance(entry, dict) and ("value" in entry or "rows" in entry):
                assert "page " in entry["where"], (ic["mpn"], key)
    assert all(isinstance(e["page"], int) for e in rules["note"]["equations"].values())
    assert "page " in rules["note"]["sf_min"]["where"]


def test_the_fixture_whose_crystal_has_twice_the_esr_is_refused_by_workcenter_design(tmp_path):
    """fail-block-mcu-2x stocks the made-up crystal alone: `workcenter design` fails on the 1 line of
    equation 5 and writes no board."""
    run = subprocess.run(
        [sys.executable, str(CLI), "design", str(BOARDS / "fail-block-mcu-2x" / "design.py"), "--out",
         str(tmp_path / "out")],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert run.returncode != 0
    assert "SF = 300 kohm / 124 kohm = 2.424" in run.stdout + run.stderr
    assert not (tmp_path / "out" / "node.kicad_pcb").exists()


@needs_kicad
@needs_libs
def test_the_fixture_is_what_its_design_file_writes_and_passes_ratings_strict(tmp_path):
    """`workcenter design` writes the committed schematic, project, ratings.json and parts.csv; a strict
    `workcenter ratings` of the fixture passes."""
    out = tmp_path / "pass-block-mcu"
    made = subprocess.run(
        [sys.executable, str(CLI), "design", str(BOARDS / "pass-block-mcu" / "design.py"), "--out", str(out)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert made.returncode == 0, made.stdout + made.stderr
    for rel in ("node.kicad_sch", "node.kicad_pro", "ratings.json", "parts.csv"):
        assert (out / rel).read_bytes() == (BOARDS / "pass-block-mcu" / rel).read_bytes(), rel
    run = subprocess.run(
        [sys.executable, str(CLI), "ratings", str(BOARDS / "pass-block-mcu"), "--out", str(tmp_path / "r"),
         "--strict"],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout + run.stderr


@needs_kicad
def test_the_fixture_is_routed_and_its_gates_are_green(tmp_path):
    """ERC, DRC (0 unconnected: the router finished) and EXPORT pass; the block writes no deck."""
    run = subprocess.run(
        [sys.executable, str(CLI), "--json", "gates", str(BOARDS / "pass-block-mcu"), "--out", str(tmp_path)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout + run.stderr
    records = {r["gate"]: r for r in json.loads(run.stdout)}
    assert [records[g]["status"] for g in ("erc", "drc", "export")] == ["pass"] * 3
    assert records["drc"]["summary"].startswith("0 errors")
    assert "0 unconnected" in records["drc"]["summary"]
