"""The USB-C port block (tools/blocks_usbc.py): a USB Type-C receptacle as a sink, added to a design in 1
call, its numbers from the USB Type-C specification R2.5, the USB 2.0 specification with its ECNs and the
datasheets of its parts (rules/blocks/usbc.json), each part's own ratings from library/facts.

The sums of the fixtures' port, by hand:

    current     1.5 A asks the 1.5A advertisement (Type-C 4.6.2.1, table 4-20, page 227); the design
                detects up to 1.5A, so it is taken. 3.0 A asks 3.0A, over what 1.5A allows: refused.
    thresholds  table 4-36 (page 254) sets the threshold between vRd-USB and vRd-1.5 within 0.613 to
                0.745 V and the one between vRd-1.5 and vRd-3.0 within 1.165 to 1.368 V; 0.746 and 1.369 V
                are the ranges' minimums, outside both bands.
    default     D+ and D- are wired, so the sink is a USB 2.0 device: 1 unit load, 100 mA, until it is
                configured (USB 2.0 7.2.1, page 171); a Power Sinking Device has no USB function (Type-C
                4.6.2.1, page 226).
    Rd          table 4-28 (page 245) asks 5.1 kohm +-10 % for a sink that detects the advertisement:
                5100 x 0.9 = 4590 to 5100 x 1.1 = 5610 ohm. CRCW06035K10FKEA, 1 %, is 5100 x 0.99 = 5049 to
                5100 x 1.01 = 5151 ohm: inside. A sink that detects none may take +-20 %: 4080 to 6120 ohm.
    VBUS        USB 2.0 table 7-7 (page 179): CRPB 1.0 to 10.0 uF; the Device Capacitance ECN (page 2): more
                than 1.0 uF up to 5.25 V. CL10A106KP8NNN, 10 uF +-10 %, is up to 10 x 1.1 = 11 uF: over 10.
                CL10A475KO8NNN, 4.7 uF +-10 %, is up to 4.7 x 1.1 = 5.17 uF; at 5.25 V it keeps, between
                its points (5.2344, 0.48048) and (5.35535, 0.47057), 0.48048 - 0.00991 x 0.0156 / 0.12095
                = 0.479202, and 4.7 x 0.9 x 0.479202 = 2.027 uF: within 1 to 10 uF.
    clamps      TPD2E2U06 stands off 5.5 V (SLLSEG9C 6.5, page 4); D+ and D- reach 3.6 V (USB 2.0 table 7-7,
                VOH and VIHZ), CC1 and CC2 2.04 V (Type-C table 4-28 for Rd +-10 %).
    CC deck     Rp to 4.75 to 5.5 V (table 4-27, page 245) into Rd 5049 to 5151 ohm:
                default, 56k +-20 %: 4.75 x 5049 / (5049 + 67200) = 0.33195 V to
                                     5.5 x 5151 / (5151 + 44800) = 0.56717 V, in vRd-USB 0.277 to 0.612 V
                1.5A, 22k +-5 %:     4.75 x 5049 / (5049 + 23100) = 0.85199 V to
                                     5.5 x 5151 / (5151 + 20900) = 1.08750 V, in vRd-1.5 0.746 to 1.164 V
                3.0A, 10k +-5 %:     4.75 x 5049 / (5049 + 10500) = 1.54240 V to
                                     5.5 x 5151 / (5151 + 9500) = 1.93369 V, in vRd-3.0 1.369 to 2.042 V
                (table 4-36, page 254). The pull-up is the .param vpu at (4.75 + 5.5) / 2 = 5.125 V
                +-0.375 / 5.125 = 7.3171 %.
"""

from __future__ import annotations

import dataclasses
import json
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
import blocks_usbc  # noqa: E402
import kicadgen  # noqa: E402

CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
FACTS = BOARDS / "library" / "facts"
RULES = ROOT / "rules" / "blocks" / "usbc.json"

needs_libs = pytest.mark.skipif(
    not (kicadgen.SYMBOL_DIR / "Device.kicad_sym").is_file(),
    reason="KiCad symbol libraries are not installed",
)
needs_kicad = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")

R_0603 = "Resistor_SMD:R_0603_1608Metric"
C_0603 = "Capacitor_SMD:C_0603_1608Metric"
RD = blocks.Stock("Vishay", "CRCW06035K10FKEA", "5.1k", R_0603)
C10 = blocks.Stock("Samsung", "CL10A106KP8NNN", "10u 10V", C_0603)
C47 = blocks.Stock("Samsung", "CL10A475KO8NNN", "4.7u 16V", C_0603)
STOCK = [RD, C10, C47]
NETS = ("VBUS", "GND", "D+", "D-", "CC1", "CC2")

TC = "USB Type-C R2.5"
T420_15 = f"{TC}, section 4.6.2.1, table 4-20, page 227: USB Type-C Current 1.5 A"
T420_30 = f"{TC}, section 4.6.2.1, table 4-20, page 227: USB Type-C Current 3.0 A"
DEFAULT = (
    f"{TC}, section 4.6.2.1, page 226: Default is the as-configured high-power current of the USB "
    "specification, 500 mA for USB 2.0 ports; table 4-20, page 227"
)
UNIT = (
    "USB 2.0, section 7.2.1, page 171: a unit load is 100 mA; a device draws at most 1 unit load until it is "
    f"configured; {TC}, section 4.6.2.1, page 226: a Power Sinking Device, which may draw 500 mA, shall not "
    "have a USB communications function"
)
ADJUST = (
    f"{TC}, section 4.6.2.1, page 227: a Sink that takes the additional current shall monitor the CC pins "
    "and adjust its current consumption within tSinkAdj to remain within the value advertised"
)
T436_15 = f"{TC}, section 4.11.3.2.2, table 4-36, page 254: the threshold between vRd-USB and vRd-1.5"
T436_30 = f"{TC}, section 4.11.3.2.2, table 4-36, page 254: the threshold between vRd-1.5 and vRd-3.0"
T428 = (
    f"{TC}, section 4.11.1, table 4-28, page 245: Rd is 5.1 kohm to GND; +-10 % can detect the power "
    "capability, +-20 % cannot; note 2: the total resistance into the CC pin"
)
T428_MAX = (
    f"{TC}, section 4.11.1, table 4-28, page 245: the max voltage on the pin, 2.04 V for Rd +-10 % and "
    "2.18 V for Rd +-20 %"
)
DATA = (
    "USB 2.0, section 7.3.2, table 7-7, pages 178 and 179: VOH at most 3.6 V and VIHZ at most 3.6 V on D+ "
    "and D-"
)
SIGNALS = (
    f"{TC}, section 3.2.3, table 3-5, page 77: GND, VBUS, CC1, CC2, Dp and Dn are each a signal of its own"
)
CRPB = (
    "USB 2.0, section 7.3.2, table 7-7, CRPB, page 179, and section 7.2.4.1, page 177: 1.0 uF to 10.0 uF on "
    "VBUS; Device Capacitance ECN, page 2: more than 1.0 uF from 0 V to 5.25 V"
)


def design() -> kicadgen.Design:
    d = kicadgen.Design(
        name="t", namespace=uuid.UUID(int=5), outline=(100.0, 100.0, 140.0, 130.0), sheet="A4"
    )
    d.power_nets = {"VBUS": "VBUS", "GND": "GND"}
    return d


def usbc(amps: float = 1.5, detects: str = "1.5A", stock=STOCK, facts=FACTS, nets=NETS, **kwargs):
    d = design()
    block = blocks.usbc(
        d,
        amps=amps,
        detects=detects,
        nets=nets,
        stock=stock,
        facts=facts,
        sch_at=(50.8, 88.9),
        pcb_at=(120.0, 121.0),
        **kwargs,
    )
    return d, block


def refused(**kwargs) -> str:
    with pytest.raises(blocks.Refused) as exc:
        usbc(**kwargs)
    return str(exc.value)


MADE_UP = {"document": "no datasheet: a part made up for tests/test_blocks_usbc.py", "read": "2026-11-17"}


def facts_with(tmp_path: Path, *parts: dict) -> Path:
    """The fixtures' facts folder and, beside it, parts made up for 1 test."""
    folder = tmp_path / "facts"
    shutil.copytree(FACTS, folder)
    entries = [{**part, "source": {**MADE_UP, "second_reader": "no"}} for part in parts]
    (folder / "zz-made-up.json").write_text(json.dumps({"parts": entries}), encoding="utf-8")
    return folder


@needs_libs
def test_1_5_a_with_the_1_5_a_advertisement_builds_the_port_and_its_sums():
    """The sums of the module's docstring: 1.5 A, Rd 5049 to 5151 ohm in 4590 to 5610, 2.03 to 5.17 uF
    on VBUS, the 10 uF part passed over."""
    d, block = usbc()
    assert {p.ref: p.value for p in d.parts} == {
        "J1": "USB4115",
        "R1": "5.1k",
        "R2": "5.1k",
        "U1": "TPD2E2U06",
        "U2": "TPD2E2U06",
        "C1": "4.7u 16V",
    }
    assert block.sums == [
        "J1: a load of 1.5 A needs the 1.5A advertisement, which allows 1.5 A; the design detects up to "
        f"1.5A [{T420_15}]",
        "CC1, CC2: draw over 500 mA only while CC1 or CC2 is over the threshold, which the part that reads "
        f"CC sets within 0.613 V to 0.745 V [{T436_15}; {ADJUST}]",
        "R1, R2: Rd of 5.1 kohm +-10 %, 4.59 kohm to 5.61 kohm; CRCW06035K10FKEA, 5.1k 1 %, is 5.05 kohm to "
        f"5.15 kohm [{T428}]",
        "U1, U2: TPD2E2U06DCKR stands off 5.5 V [TPD2E2U06 datasheet, SLLSEG9C, June 2013, revised "
        "December 2019]; D+ and D- reach 3.6 V [USB 2.0, section 7.3.2, table 7-7, pages 178 and 179: VOH at "
        f"most 3.6 V and VIHZ at most 3.6 V on D+ and D-], CC1 and CC2 2.04 V [{TC}, section 4.11.1, "
        "table 4-28, page 245: the max voltage on the pin, 2.04 V for Rd +-10 % and 2.18 V for Rd +-20 %]; "
        "each is placed 10.6 mm from J1's centre, and the length of copper from J1 to each after routing is "
        "not judged: the block runs before the router [TPD2E2U06 datasheet, SLLSEG9C, section 5, Pin "
        "Functions, page 3: connect IO1 and IO2 to the data line as close to the connector as possible]",
        "C1: CL10A475KO8NNN on VBUS: 4.7 uF x 0.9 x 0.4792 = 2.03 uF at 5.25 V to 4.7 uF x 1.1 = 5.17 uF, "
        "with the design's own 0 F to 0 F: 2.03 uF to 5.17 uF, within 1 uF to 10 uF "
        f"[{CRPB}; USB 2.0, Device Capacitance ECN, page 2: CRPB across the whole VBUS voltage range, 0 V to "
        "5.25 V; Samsung Electro-Mechanics component library, MLCC data sheet page of CL10A475KO8NNN, the "
        "page as fetched on 2026-11-17; it prints no revision]",
        "J1: the shell and the 4 GND pins on GND, the 4 VBUS pins on VBUS, A6 and B6 on D+, A7 and B7 on "
        f"D-, SBU1, SBU2 and the unused pins not connected [{TC}, section 3.2.1, note 11, page 47; section "
        "3.2.3, table 3-5, notes 1 to 5, page 77]; the length of the A6 to B6 and A7 to B7 shorts, at most "
        f"3.5 mm, is not judged: the block runs before the router [{TC}, section 3.2.3, table 3-5, note 2, "
        "page 77: the maximum shorting trace length should not exceed 3.5 mm]",
    ]


@needs_libs
def test_twice_the_current_is_refused_with_the_clause_of_the_advertisement():
    """3.0 A asks the 3.0A advertisement; the design detects up to 1.5A, which allows 1.5 A."""
    assert refused(amps=3.0) == (
        f"usbc J1: a load of 3 A is over the 1.5 A that 1.5A, the highest advertisement the design detects, "
        f"allows [{T420_15}]; 3.0A allows 3 A [{T420_30}]"
    )


@needs_libs
def test_3_a_is_taken_by_a_design_that_detects_3_a():
    """3.0 A is what 3.0A allows, at the limit. Its sums ask 2 thresholds of table 4-36 (page 254), each
    inside its band and not at a range's end: over 500 mA only over the one set within 0.613 to 0.745 V,
    over 1.5 A only over the one set within 1.165 to 1.368 V."""
    _, block = usbc(amps=3.0, detects="3.0A")
    assert block.sums[0] == (
        f"J1: a load of 3 A needs the 3.0A advertisement, which allows 3 A; the design detects up to 3.0A "
        f"[{T420_30}]"
    )
    assert block.sums[1:3] == [
        "CC1, CC2: draw over 500 mA only while CC1 or CC2 is over the threshold, which the part that reads "
        f"CC sets within 0.613 V to 0.745 V [{T436_15}; {ADJUST}]",
        "CC1, CC2: draw over 1.5 A only while CC1 or CC2 is over the threshold, which the part that reads "
        f"CC sets within 1.165 V to 1.368 V [{T436_30}; {ADJUST}]",
    ]


@needs_libs
def test_over_3_a_is_refused_as_usb_pd_which_the_block_does_not_build():
    """3.5 A is over 3.0 A, the highest advertisement of table 4-20; more is USB PD (table 4-19)."""
    assert refused(amps=3.5, detects="3.0A") == (
        f"usbc J1: a load of 3.5 A is over the 3 A of the highest advertisement [{T420_30}; {TC}, section "
        "4.6, table 4-19, page 225: over 3.0 A at 5 V is USB PD only, which this block does not build]"
    )


@needs_libs
def test_over_500_ma_is_refused_for_a_design_that_detects_no_advertisement():
    """0.6 A asks 1.5A; a design that reads no advertisement may draw the Default 500 mA."""
    assert refused(amps=0.6, detects="default") == (
        "usbc J1: a load of 600 mA is over the 500 mA that default, the highest advertisement the design "
        f"detects, allows [{DEFAULT}]; 1.5A allows 1.5 A [{T420_15}]"
    )


@needs_libs
def test_500_ma_at_default_asks_no_cc_reading():
    """0.5 A is the Default; no line asks the design to read CC."""
    _, block = usbc(amps=0.5, detects="default")
    assert not any(line.startswith("CC1, CC2:") for line in block.sums)


@needs_libs
def test_over_1_unit_load_at_default_says_the_wait_for_configuration_is_not_judged():
    """D+ and D- are wired, so the sink is a USB 2.0 device and no Power Sinking Device (Type-C 4.6.2.1,
    page 226). 0.5 A is over 1 unit load, 100 mA (USB 2.0 7.2.1, page 171): the sum says the wait for
    configuration is not judged. 0.1 A is 1 unit load, not over it: no such line."""
    _, block = usbc(amps=0.5, detects="default")
    assert block.sums[:2] == [
        "J1: a load of 500 mA needs the default advertisement, which allows 500 mA; the design detects up "
        f"to default [{DEFAULT}]",
        "J1: D+ and D- are wired, so the sink connects as a USB 2.0 device and draws at most 100 mA until it "
        "is configured; whether the design waits for its configuration is not judged: the block cannot see "
        f"the firmware [{UNIT}]",
    ]
    _, block = usbc(amps=0.1, detects="default")
    assert not any("not judged: the block cannot see the firmware" in line for line in block.sums)


@needs_libs
@pytest.mark.parametrize(("amps", "shown"), [(0.0, "0 A"), (-1.0, "-1 A")])
def test_a_load_of_0_or_less_is_refused(amps, shown):
    assert refused(amps=amps) == (
        f"usbc J1: a load of {shown}: the block sizes the port for a load over 0 A [{DEFAULT}]"
    )


@needs_libs
def test_an_advertisement_it_does_not_know_is_refused():
    assert refused(detects="2A") == "usbc J1: detects='2A': one of default, 1.5A, 3.0A is asked"


ROUGH = {"kind": "resistor", "mpn": "FIXTURE-5K1-20", "tolerance": 0.20, "watts": 0.1, "volts": 50}
ROUGH_STOCK = blocks.Stock("made up", "FIXTURE-5K1-20", "5.1k", R_0603)


@needs_libs
def test_a_20_percent_rd_is_passed_over_by_a_design_that_detects(tmp_path):
    """A made-up 5.1k +-20 % part first in the stock is 4080 to 6120 ohm, outside 4590 to 5610: the block
    takes the next, CRCW06035K10FKEA."""
    _, block = usbc(stock=[ROUGH_STOCK, *STOCK], facts=facts_with(tmp_path, ROUGH))
    assert "; CRCW06035K10FKEA, 5.1k 1 %, is 5.05 kohm to 5.15 kohm [" in block.sums[2]


@needs_libs
def test_a_20_percent_rd_is_taken_by_a_design_that_detects_nothing(tmp_path):
    """At default the span is 4080 to 6120 ohm (table 4-28, +-20 %); the made-up part is that span."""
    _, block = usbc(
        amps=0.5, detects="default", stock=[ROUGH_STOCK, *STOCK], facts=facts_with(tmp_path, ROUGH)
    )
    assert block.sums[2] == (
        "R1, R2: Rd of 5.1 kohm +-20 %, 4.08 kohm to 6.12 kohm; FIXTURE-5K1-20, 5.1k 20 %, is 4.08 kohm to "
        f"6.12 kohm [{T428}]"
    )


@needs_libs
def test_no_rd_in_the_stock_is_refused(tmp_path):
    """With the 20 % part alone a detecting design has no Rd."""
    assert refused(stock=[ROUGH_STOCK, C47], facts=facts_with(tmp_path, ROUGH)) == (
        "usbc J1: no stocked resistor with facts is Rd of 5.1 kohm +-10 %, 4.59 kohm to 5.61 kohm: "
        f"FIXTURE-5K1-20 is 4.08 kohm to 6.12 kohm [{T428}]"
    )


@needs_libs
def test_10_uf_on_vbus_is_passed_over_and_nothing_else_is_refused():
    """CL10A106KP8NNN alone: 10 uF x 1.1 = 11 uF, over the 10 uF of CRPB."""
    assert refused(stock=[RD, C10]) == (
        "usbc J1: no stocked capacitor keeps VBUS within 1 uF to 10 uF with the design's own 0 F to 0 F: "
        f"CL10A106KP8NNN: up to 11 uF, over 10 uF [{CRPB}]"
    )


@needs_libs
def test_the_designs_own_capacitance_counts_against_crpb():
    """With 5 uF of the design's own, the 4.7 uF part reaches 5.17 + 5 = 10.17 uF: over 10."""
    assert refused(farads=(4e-6, 5e-6)) == (
        "usbc J1: no stocked capacitor keeps VBUS within 1 uF to 10 uF with the design's own 4 uF to 5 uF: "
        f"CL10A106KP8NNN: up to 16 uF, over 10 uF; CL10A475KO8NNN: up to 10.2 uF, over 10 uF [{CRPB}]"
    )


@needs_libs
def test_the_designs_own_capacitance_over_crpb_is_refused_before_any_part():
    """12 uF of the design's own is over 10 uF whatever the block adds."""
    assert refused(farads=(12e-6, 12e-6)) == (
        "usbc J1: the design's own 12 uF to 12 uF on VBUS is over 10 uF before the block adds a part "
        f"[{CRPB}]"
    )


@needs_libs
def test_a_capacitor_with_no_kept_value_is_passed_over(tmp_path):
    """A made-up 2.2 uF capacitor with no DC bias data cannot be judged at 5.25 V."""
    flat = {
        "kind": "capacitor.ceramic",
        "mpn": "FIXTURE-2U2",
        "tolerance": 0.1,
        "volts": 16,
        "dielectric": "X5R",
    }
    cap = blocks.Stock("made up", "FIXTURE-2U2", "2.2u", C_0603)
    _, block = usbc(stock=[RD, cap, C47], facts=facts_with(tmp_path, flat))
    assert block.sums[4].startswith("C1: CL10A475KO8NNN on VBUS:")
    assert refused(stock=[RD, cap], facts=facts_with(tmp_path / "2", flat)) == (
        "usbc J1: no stocked capacitor keeps VBUS within 1 uF to 10 uF with the design's own 0 F to 0 F: "
        f"FIXTURE-2U2: its facts give no value it keeps at 5.25 V [{CRPB}]"
    )


@needs_libs
def test_the_block_hands_the_ports_nets_and_parts_to_ratings():
    """VBUS 4.75 to 5.5 V (the VBUS Max Limit ECN), D+ and D- 0 to 3.6 V (table 7-7), CC1 and CC2 0 to
    2.04 V (table 4-28); 1 row per part number, 2 Rd and 2 clamps."""
    _, block = usbc()
    nets = block.ratings["nets"]
    assert {n: e["volts"] for n, e in nets.items()} == {
        "VBUS": [4.75, 5.5],
        "D+": [0, 3.6],
        "D-": [0, 3.6],
        "CC1": [0, 2.04],
        "CC2": [0, 2.04],
    }
    assert nets["VBUS"]["source"].startswith(
        "USB 2.0, USB 2.0 ECN VBUS Max Limit, change (c) to section 7.3.2"
    )
    assert [(r.value, r.mpn, r.qty) for r in block.rows] == [
        ("USB4115", "USB4115-03-C", 1),
        ("5.1k", "CRCW06035K10FKEA", 2),
        ("TPD2E2U06", "TPD2E2U06DCKR", 2),
        ("4.7u 16V", "CL10A475KO8NNN", 1),
    ]


@needs_libs
def test_the_deck_holds_the_cc_pin_under_each_advertisement_to_table_4_36():
    """3 branches, Rp of 56k, 22k and 10k into the .param rd; bounds of table 4-36; the pull-up at
    5.125 V +-7.3171 %, each Rp at its table 4-27 tolerance and Rd at its facts' 1 %."""
    _, block = usbc()
    deck = block.files["sim/cc.cir"]
    for line in (
        "RP0 pu0 cc0 56000",
        "RP1 pu1 cc1 22000",
        "RP2 pu2 cc2 10000",
        ".param vpu=5.125",
        ".param rd=5100",
    ):
        assert line in deck.splitlines(), line
    expect = json.loads(block.files["sim/cc.expect.json"])
    assert {k: (v["min"], v["max"]) for k, v in expect.items()} == {
        "vrd_usb": (0.277, 0.612),
        "vrd_15": (0.746, 1.164),
        "vrd_30": (1.369, 2.042),
    }
    parts = json.loads(block.files["sim/corners.json"])["tolerance"]["parts"]
    assert parts == {"vpu": 0.073170732, "rd": 0.01, "RP0": 0.2, "RP1": 0.05, "RP2": 0.05}


@needs_libs
def test_a_design_that_detects_nothing_holds_each_advertisement_to_vrd_connected():
    """Table 4-35: vRd-connected, 0.249 to 2.181 V, for every advertisement."""
    _, block = usbc(amps=0.5, detects="default")
    expect = json.loads(block.files["sim/cc.expect.json"])
    assert {(v["min"], v["max"]) for v in expect.values()} == {(0.249, 2.181)}


@needs_libs
@pytest.mark.parametrize(
    ("ref", "nets", "says"),
    [
        ("R2", {"1": "CC2", "2": "VBUS"}, "usbc J1: Rd R2 on CC2 is on CC2, VBUS, not between CC2 and GND ["),
        (
            "U1",
            {"1": "D+", "2": "GND", "3": "D-"},
            "usbc J1: the clamp U1 of D+ and D- is pin 1 on D+, pin 2 on GND",
        ),
        ("J1", None, "usbc J1: SBU pins A8 on D+ ["),
        ("J1", "A2", "usbc J1: UNUSED pins A2 on D+ ["),
        ("C1", {"1": "VBUS", "2": "VBUS"}, "usbc J1: C1 is not between VBUS and GND ["),
    ],
)
def test_the_check_reads_back_what_was_built_and_names_a_planted_fault(ref, nets, says):
    """The port as built passes its check; each fault planted in it afterwards is 1 line."""
    d, block = usbc()
    assert blocks_usbc.check(d, block.port) == []
    part = next(p for p in d.parts if p.ref == ref)
    if nets is None:
        part.nets["A8"] = "D+"
    elif isinstance(nets, str):
        part.nets[nets] = "D+"
    else:
        part.nets = nets
    lines = blocks_usbc.check(d, block.port)
    assert len(lines) == 1 and lines[0].startswith(says), lines


@needs_libs
def test_the_check_holds_an_rd_value_to_table_4_28():
    """An Rd changed to 10k after the build: 10000 x 0.99 = 9900 to 10100 ohm, outside 4590 to 5610."""
    d, block = usbc()
    next(p for p in d.parts if p.ref == "R1").value = "10k"
    assert blocks_usbc.check(d, block.port) == [
        f"usbc J1: Rd R1 is 9.9 kohm to 10.1 kohm, outside 4.59 kohm to 5.61 kohm [{T428}]"
    ]


@needs_libs
def test_the_check_holds_the_load_to_the_receptacles_rating(tmp_path):
    """A copy of the rules whose receptacle carries 1 A on VBUS: 1.5 A is over it."""
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    rules["connectors"][0]["amps_vbus"]["value"] = 1.0
    (tmp_path / "usbc.json").write_text(json.dumps(rules), encoding="utf-8")
    assert refused(rules=tmp_path / "usbc.json") == (
        "usbc J1: 1.5 A on VBUS is over the receptacle's 1 A [GCT USB4115 drawing, Electrical, Current "
        "Rating, page 1: 5.00 A collectively for VBUS pins]"
    )


@needs_libs
@pytest.mark.parametrize(
    ("nets", "says"),
    [
        (
            ("VBUS", "GND", "D+", "D-", "CC", "CC"),
            "usbc J1: CC1 and CC2 are on 1 net, CC; each signal of the port asks a net of its own "
            f"[{SIGNALS}; {T428}]",
        ),
        (
            ("VBUS", "GND", "D", "D", "CC1", "CC2"),
            f"usbc J1: D+ and D- are on 1 net, D; each signal of the port asks a net of its own [{SIGNALS}]",
        ),
        (
            ("VBUS", "GND", "D+", "D-", "GND", "CC2"),
            "usbc J1: GND and CC1 are on 1 net, GND; each signal of the port asks a net of its own "
            f"[{SIGNALS}; {T428}]",
        ),
        (
            ("N",) * 6,
            "usbc J1: VBUS, GND, D+, D-, CC1 and CC2 are on 1 net, N; each signal of the port asks a net "
            f"of its own [{SIGNALS}; {T428}]",
        ),
    ],
)
def test_signals_on_1_net_are_refused(nets, says):
    """CC1 and CC2 on 1 net put the 2 Rd in parallel: 5151 / 2 = 2575.5 ohm at most, under 4590 (table 4-28,
    note 2, page 245: Rd is the total resistance into each CC pin). Any 2 signals on 1 net are a short."""
    assert refused(nets=nets) == says


@needs_libs
def test_the_check_reads_signals_on_1_net_back():
    """The port as built, then its CC2 read back as on CC1's net: the check names it."""
    d, block = usbc()
    port = dataclasses.replace(block.port, nets={**block.port.nets, "CC2": "CC1"})
    assert blocks_usbc.check(d, port) == [
        f"usbc J1: CC1 and CC2 are on 1 net, CC1; each signal of the port asks a net of its own [{SIGNALS}; "
        f"{T428}]"
    ]


@needs_libs
@pytest.mark.parametrize(
    ("nets", "shown"),
    [
        (("VBUS", "GND", "D+", "D-", "CC1"), "('VBUS', 'GND', 'D+', 'D-', 'CC1')"),
        (("VBUS", "GND", "D+", "D-", "CC1", 6), "('VBUS', 'GND', 'D+', 'D-', 'CC1', 6)"),
        (("VBUS", "GND", "D+", "D-", "CC1", ""), "('VBUS', 'GND', 'D+', 'D-', 'CC1', '')"),
    ],
)
def test_nets_not_6_names_are_refused(nets, shown):
    assert refused(nets=nets) == (
        f"usbc J1: nets={shown}: 6 net names are asked, for VBUS, GND, D+, D-, CC1 and CC2"
    )


@needs_libs
@pytest.mark.parametrize(
    ("amps", "shown"), [("1.5", "'1.5'"), (float("nan"), "nan"), (float("inf"), "inf"), (True, "True")]
)
def test_a_load_that_is_no_number_is_refused_as_such(amps, shown):
    """NaN is no load of 0 A: it is no number."""
    assert refused(amps=amps) == f"usbc J1: amps={shown}: a number of amperes is asked"


@needs_libs
@pytest.mark.parametrize(
    ("farads", "shown"),
    [((9e-6, 1e-6), "(9e-06, 1e-06)"), ((-5e-6, 0.0), "(-5e-06, 0.0)"), ((1e-6,), "(1e-06,)")],
)
def test_the_designs_own_capacitance_not_least_then_most_is_refused(farads, shown):
    """(9 uF, 1 uF) would let 9 uF + 5.17 uF = 14.17 uF through, over 10 uF; a negative capacitance is
    no part; 1 number is no span."""
    assert refused(farads=farads) == (
        f"usbc J1: farads={shown}: (least, most) is asked, in farads, each 0 or more, the least first"
    )


@needs_libs
def test_a_value_that_names_no_number_is_passed_over_and_said():
    """A resistor whose Value is 'Rd' and a capacitor whose Value is 'bulk' name no number to judge."""
    rd = blocks.Stock("Vishay", "CRCW06035K10FKEA", "Rd", R_0603)
    assert refused(stock=[rd, C47]) == (
        "usbc J1: no stocked resistor with facts is Rd of 5.1 kohm +-10 %, 4.59 kohm to 5.61 kohm: "
        f"CRCW06035K10FKEA: its Value 'Rd' names no resistance [{T428}]"
    )
    bulk = blocks.Stock("Samsung", "CL10A475KO8NNN", "bulk", C_0603)
    assert refused(stock=[RD, bulk]) == (
        "usbc J1: no stocked capacitor keeps VBUS within 1 uF to 10 uF with the design's own 0 F to 0 F: "
        f"CL10A475KO8NNN: its Value 'bulk' names no capacitance [{CRPB}]"
    )


@needs_libs
@pytest.mark.parametrize(
    ("standoff", "says"),
    [
        (
            3.0,
            [
                f"usbc J1: D+ reaches 3.6 V, over the 3 V U1 stands off [{DATA}]",
                f"usbc J1: D- reaches 3.6 V, over the 3 V U1 stands off [{DATA}]",
            ],
        ),
        (
            2.0,
            [
                f"usbc J1: D+ reaches 3.6 V, over the 2 V U1 stands off [{DATA}]",
                f"usbc J1: D- reaches 3.6 V, over the 2 V U1 stands off [{DATA}]",
                f"usbc J1: CC1 reaches 2.04 V, over the 2 V U2 stands off [{T428_MAX}]",
                f"usbc J1: CC2 reaches 2.04 V, over the 2 V U2 stands off [{T428_MAX}]",
            ],
        ),
    ],
)
def test_the_check_holds_each_line_to_the_clamps_standoff(standoff, says):
    """A clamp of 3 V: D+ and D- reach 3.6 V, over it; CC 2.04 V is not. A clamp of 2 V: all 4 are over."""
    d, block = usbc()
    assert blocks_usbc.check(d, dataclasses.replace(block.port, standoff=standoff)) == says


@needs_libs
@pytest.mark.parametrize(
    ("pin", "net", "says"),
    [
        ("A9", "GND", "usbc J1: VBUS pins A9 on GND, not VBUS ["),
        ("SH", "VBUS", "usbc J1: SHIELD pins SH on VBUS, not GND ["),
        ("B7", "D+", "usbc J1: D- pins B7 on D+, not D- ["),
        ("A5", "CC2", "usbc J1: CC1 pins A5 on CC2, not CC1 ["),
    ],
)
def test_the_check_reads_each_receptacle_pin_back(pin, net, says):
    """Each pin of table 3-5 moved to another net after the build is 1 line."""
    d, block = usbc()
    next(p for p in d.parts if p.ref == "J1").nets[pin] = net
    lines = blocks_usbc.check(d, block.port)
    assert len(lines) == 1 and lines[0].startswith(says), lines


CAP_KEPT = [[0.0, 1.0], [10.0, 0.5]]


@needs_libs
def test_a_capacitor_that_keeps_under_1_uf_at_5_25_v_is_passed_over(tmp_path):
    """A made-up 1 uF +-10 % part that keeps 1 - 0.5 x 5.25 / 10 = 0.7375 at 5.25 V:
    1 x 0.9 x 0.7375 = 0.66375 uF, under the 1 uF of CRPB."""
    small = {"kind": "capacitor.ceramic", "mpn": "FIXTURE-1U", "tolerance": 0.1, "volts": 16,
             "dielectric": "X5R", "kept": CAP_KEPT}  # fmt: skip
    cap = blocks.Stock("made up", "FIXTURE-1U", "1u", C_0603)
    assert refused(stock=[RD, cap], facts=facts_with(tmp_path, small)) == (
        "usbc J1: no stocked capacitor keeps VBUS within 1 uF to 10 uF with the design's own 0 F to 0 F: "
        f"FIXTURE-1U: 664 nF at 5.25 V, under 1 uF [{CRPB}]"
    )


@needs_libs
def test_a_capacitor_rated_under_the_vbus_maximum_is_passed_over(tmp_path):
    """A made-up 2.2 uF part rated 4 V: VBUS reaches 5.5 V (VBUS Max Limit ECN, page 4)."""
    low = {"kind": "capacitor.ceramic", "mpn": "FIXTURE-4V", "tolerance": 0.1, "volts": 4,
           "dielectric": "X5R", "kept": CAP_KEPT}  # fmt: skip
    cap = blocks.Stock("made up", "FIXTURE-4V", "2.2u", C_0603)
    assert refused(stock=[RD, cap], facts=facts_with(tmp_path, low)) == (
        "usbc J1: no stocked capacitor keeps VBUS within 1 uF to 10 uF with the design's own 0 F to 0 F: "
        f"FIXTURE-4V: rated 4 V, under 5.5 V [{CRPB}]"
    )


@needs_libs
def test_a_design_that_detects_nothing_hands_cc_up_to_2_18_v():
    """Rd +-20 %: the max voltage on the pin is 2.18 V (table 4-28, page 245), not the 2.04 V of +-10 %."""
    _, block = usbc(amps=0.5, detects="default")
    assert [block.ratings["nets"][n]["volts"] for n in ("CC1", "CC2")] == [[0, 2.18], [0, 2.18]]


@needs_libs
def test_the_deck_says_the_2_other_columns_of_table_4_27_are_not_judged():
    """Table 4-27 (page 245) allows Rp as a current source and as a pull-up to 3.3 V; the deck models the
    pull-up to 4.75 to 5.5 V alone, and says so."""
    _, block = usbc()
    assert (
        f"* Not judged: Rp as the 2 other columns of {TC}, section 4.11.1, table 4-27, page 245: a current "
        "source to 1.7 to 5.5 V of 80 uA +-20 %, 180 uA +-8 % or 330 uA +-8 %, and a resistor pull-up to "
        "3.3 V +-5 % of 36 kohm +-20 %, 12 kohm +-5 % or 4.7 kohm +-5 %; the deck models the resistor "
        "pull-up to 4.75 V to 5.5 V alone."
    ) in block.files["sim/cc.cir"].splitlines()


def test_every_number_of_the_rules_names_where_it_stands():
    """No number of rules/blocks/usbc.json stands without its clause and page."""
    rules = json.loads(RULES.read_text(encoding="utf-8"))
    for key in (
        "rd",
        "cc_max",
        "pullup_volts",
        "vbus_volts",
        "vbus_farads",
        "vbus_bias",
        "data_volts",
        "connected",
    ):
        assert re.search(r"pages? \d", rules[key]["where"]), key
    for ad in rules["advertisements"]:
        assert all("page " in ad[k] for k in ("where", "cc_where", "rp_where")), ad["name"]
        if ad["name"] != "default":
            assert "page " in ad["threshold_where"], ad["name"]
    for key in ("unit_load", "adjust", "short", "signals", "rp_not_modelled"):
        assert "page " in rules[key]["where"], key
    assert all("page " in text for key, text in rules["wiring"].items() if key != "doc")
    assert "page " in rules["connectors"][0]["amps_vbus"]["where"]


@needs_kicad
@needs_libs
def test_the_fixture_is_what_its_design_file_writes_and_passes_ratings_strict(tmp_path):
    """`workcenter design` writes the committed schematic, project, ratings.json, parts.csv and deck; a
    strict `workcenter ratings` of the fixture passes."""
    name = "pass-block-usbc"
    out = tmp_path / name
    made = subprocess.run(
        [sys.executable, str(CLI), "design", str(BOARDS / name / "design.py"), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert made.returncode == 0, made.stdout + made.stderr
    for rel in ("node.kicad_sch", "node.kicad_pro", "ratings.json", "parts.csv", "sim/cc.cir",
                "sim/cc.expect.json", "sim/corners.json"):  # fmt: skip
        assert (out / rel).read_bytes() == (BOARDS / name / rel).read_bytes(), rel
    run = subprocess.run(
        [sys.executable, str(CLI), "ratings", str(BOARDS / name), "--out", str(tmp_path / "r"), "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stdout.splitlines()[-1].startswith("RATINGS HELD: node "), run.stdout
    assert "0 fail, 0 accepted, 9 hold, 0 not judged" in run.stdout


@needs_kicad
@needs_libs
def test_the_fixture_at_twice_the_current_is_refused_with_the_clause(tmp_path):
    """`workcenter design` of fail-block-usbc-2x stops on the block's 1 line and writes no project."""
    made = subprocess.run(
        [sys.executable, str(CLI), "design", str(BOARDS / "fail-block-usbc-2x" / "design.py"), "--out",
         str(tmp_path / "x")],
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip
    assert made.returncode != 0
    said = made.stdout + made.stderr
    assert (
        f"usbc J1: a load of 3 A is over the 1.5 A that 1.5A, the highest advertisement the design detects, "
        f"allows [{T420_15}]; 3.0A allows 3 A [{T420_30}]"
    ) in said, said
    assert not (tmp_path / "x" / "node.kicad_sch").exists()


# The span of each measure over the deck's corner runs, by hand in the module's docstring.
SPANS = {
    "vrd_usb": (0.33195, 0.56717),
    "vrd_15": (0.85199, 1.08750),
    "vrd_30": (1.54240, 1.93369),
}


@needs_kicad
def test_the_fixture_is_routed_and_its_gates_are_green(tmp_path):
    """ERC, DRC (0 unconnected: the router finished), SIM and EXPORT pass with --strict. The CC deck's
    worst corners are the hand sums."""
    run = subprocess.run(
        [sys.executable, str(CLI), "--json", "gates", str(BOARDS / "pass-block-usbc"), "--out", str(tmp_path),
         "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout + run.stderr
    records = {r["gate"]: r for r in json.loads(run.stdout)}
    assert [records[g]["status"] for g in ("erc", "drc", "sim", "export")] == ["pass"] * 4
    assert records["drc"]["summary"] == "0 errors, 0 warnings (0 unconnected, 0 parity)"
    runs = json.loads((tmp_path / "sim" / "corners" / "cc" / "runs.json").read_text(encoding="utf-8"))
    for name, (low, high) in SPANS.items():
        values = [r["measures"][name] for r in runs]
        assert (min(values), max(values)) == pytest.approx((low, high), rel=1e-4), name
