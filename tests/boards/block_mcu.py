"""The board of the mcu block's fixtures: 3.3 V in on J1, the block of tools/blocks_mcu.py beside it.

`build(crystals)` returns the design with the crystals stocked in that order. pass-block-mcu stocks
Abracon ABS07-32.768KHZ-6-T and ABS25-32.768KHZ-12-T: the block passes over the first on its shunt
capacitance and takes the second. fail-block-mcu-2x stocks a made-up crystal with twice ABS25's ESR, and
the block refuses it by equation 5 of TI SLAA322D. tests/test_blocks_mcu.py works out both by hand.
"""

from __future__ import annotations

import uuid
from pathlib import Path

# `workcenter design` puts the workcenter's tools/ on the import path before it loads a design file.
import blocks
import kicadgen

HERE = Path(__file__).resolve().parent
C_0603 = "Capacitor_SMD:C_0603_1608Metric"
C_0805 = "Capacitor_SMD:C_0805_2012Metric"
ABS07 = blocks.Stock(
    "Abracon", "ABS07-32.768KHZ-6-T", "32.768k ABS07", "Crystal:Crystal_SMD_3215-2Pin_3.2x1.5mm"
)
ABS25 = blocks.Stock(
    "Abracon", "ABS25-32.768KHZ-12-T", "32.768k ABS25", "Crystal:Crystal_SMD_Abracon_ABS25-4Pin_8.0x3.8mm"
)
TWICE = blocks.Stock(
    "made up", "FIXTURE-32K768-100K", "32.768k 100k", "Crystal:Crystal_SMD_Abracon_ABS25-4Pin_8.0x3.8mm"
)

# The parts the designer can buy beside the crystals, in the order the block should try them.
OTHERS = [
    blocks.Stock("Vishay", "VJ0603A180JXAAC", "18p", C_0603),
    blocks.Stock("Vishay", "VJ0603A220JXAAC", "22p", C_0603),
    blocks.Stock("Vishay", "VJ0603A270JXAAC", "27p", C_0603),
    blocks.Stock("made up", "FIXTURE-10U-16V", "10u 16V", C_0805),
    blocks.Stock("Vishay", "VJ0603Y104KXJAC", "100n", C_0603),
    blocks.Stock("Vishay", "VJ0805Y474KXJAC", "470n", C_0805),
    blocks.Stock("Vishay", "VJ0603Y102KXJAC", "1n", C_0603),
    blocks.Stock("Vishay", "CRCW060347K0FKEA", "47k", "Resistor_SMD:R_0603_1608Metric"),
]
# The board's own capacitance on each crystal pin: this fixture's estimate of its short traces, 1 pF.
STRAY = 1e-12
# The supply: the output a TLV755P of 3.3 V holds, 3.2505 V to 3.3495 V (library/facts/ti-tlv755p.json). The
# programming tool drives RST and TEST at the board's own supply, and `workcenter ratings` judges each net
# at its own worst end: a supply 0.3 V wide or wider would put the top of it on RST beside DVCC at its
# bottom, over the datasheet's DVCC + 0.3 V.
VCC = (3.2505, 3.3495)


def build(crystals: list[blocks.Stock]) -> kicadgen.Design:
    d = kicadgen.Design(
        name="node",
        namespace=uuid.UUID("8f4c2a61-3d7e-4b19-a5c0-6e2d9b7f1a34"),
        outline=(100.0, 100.0, 140.0, 130.0),
        sheet="A4",
    )
    d.power_nets = {"+3V3": "+3V3", "GND": "GND"}
    # +3V3 and GND arrive on J1: no power-output pin drives them.
    d.flagged_nets = ["+3V3", "GND"]
    header = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
    d.add("J1", "Connector_Generic:Conn_01x02", "3V3 IN", header,
          sch_at=(25.4, 63.5), pcb_at=(104.0, 126.0), nets={"1": "+3V3", "2": "GND"})  # fmt: skip
    block = blocks.mcu(
        d,
        ic="MSP430FR5720IRGE",
        vcc=VCC,
        stray=STRAY,
        nets=("+3V3", "GND"),
        stock=[*crystals, *OTHERS],
        facts=HERE / "library" / "facts",
        sch_at=(50.8, 63.5),
        pcb_at=(105.0, 102.0),
    )
    own = {"nets": {"GND": {"volts": [0, 0], "source": "the reference: J1 pin 2"}}}
    d.files = {
        "ratings.json": blocks.ratings_json("nasa-eee-inst-002", block.ratings, own),
        "parts.csv": blocks.parts_csv(block.rows),
    }
    return d
