"""The board of the I2C block's fixtures: 3.3 V on J1, the bus on J2 from a controller off the board, a
TCA9534 I/O expander on the bus, and the 2 pull-ups of tools/blocks_i2c.py.

`build(farads)` states the bus capacitance. pass-block-i2c states 100 pF, and the block takes 2.2k;
pass-block-i2c-2x states 200 pF, twice it, and the block takes 1.5k. tests/test_blocks_i2c.py works out
both by hand.
"""

from __future__ import annotations

import uuid
from pathlib import Path

# `workcenter design` puts the workcenter's tools/ on the import path before it loads a design file.
import blocks
import kicadgen

HERE = Path(__file__).resolve().parent
HEADER_2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
R_0603 = "Resistor_SMD:R_0603_1608Metric"
C_0603 = "Capacitor_SMD:C_0603_1608Metric"
SOIC16 = "Package_SO:SOIC-16W_7.5x10.3mm_P1.27mm"

# The resistors the designer can buy, in the order the block should try them: Vishay CRCW0603, 1 %.
STOCK = [
    blocks.Stock("Vishay", "CRCW06034K70FKEA", "4.7k", R_0603),
    blocks.Stock("Vishay", "CRCW06032K20FKEA", "2.2k", R_0603),
    blocks.Stock("Vishay", "CRCW06031K50FKEA", "1.5k", R_0603),
    blocks.Stock("Vishay", "CRCW06031K00FKEA", "1k", R_0603),
]


def build(farads: float) -> kicadgen.Design:
    d = kicadgen.Design(
        name="node",
        namespace=uuid.UUID("8c1f4b2e-6a3d-4e97-b0c5-2d7e9f1a3b64"),
        outline=(100.0, 100.0, 140.0, 125.0),
        sheet="A4",
    )
    d.power_nets = {"+3V3": "+3V3", "GND": "GND"}
    # +3V3 and GND arrive on J1: no power-output pin drives them.
    d.flagged_nets = ["+3V3", "GND"]
    d.add("J1", "Connector_Generic:Conn_01x02", "3V3 IN", HEADER_2, sch_at=(50.8, 76.2),
          pcb_at=(104.0, 105.0), nets={"1": "+3V3", "2": "GND"})  # fmt: skip
    d.add("J2", "Connector_Generic:Conn_01x02", "I2C", HEADER_2, sch_at=(50.8, 101.6),
          pcb_at=(104.0, 117.0), nets={"1": "SDA", "2": "SCL"})  # fmt: skip
    # The TCA9534 at address 0x20: A0 to A2 on GND (SCPS197D, section 8.6.1, table 2, page 19). P0 to P7
    # and INT are left open.
    d.add("U1", "Interface_Expansion:TCA9534", "TCA9534", SOIC16, sch_at=(152.4, 88.9), pcb_at=(126.0, 112.5),
          nets={"1": "GND", "2": "GND", "3": "GND", "8": "GND", "14": "SCL", "15": "SDA",
                "16": "+3V3"})  # fmt: skip
    d.add("C1", "Device:C", "100n", C_0603, sch_at=(177.8, 88.9), pcb_at=(134.0, 105.0),
          nets={"1": "+3V3", "2": "GND"})  # fmt: skip
    block = blocks.i2c(
        d,
        volts=(3.135, 3.465),
        speed="fast",
        nets=("SDA", "SCL", "+3V3"),
        devices={"U1": "TCA9534DWR"},
        stock=STOCK,
        facts=HERE / "library" / "facts",
        farads=farads,
        sch_at=(101.6, 63.5),
        pcb_at=(112.0, 104.0),
    )
    own = {
        "nets": {
            "+3V3": {
                "volts": [3.135, 3.465],
                "source": "the supply on J1: 3.3 V less and plus 5 %, this fixture's own",
            },
            "GND": {"volts": [0, 0], "source": "the reference: J1 pin 2"},
        }
    }
    # J2's facts (library/facts/made-up-i2c.json) say the controller's open drains stand behind it.
    rows = [
        blocks.Row("I2C", HEADER_2, 1, "made up", "FIXTURE-HEADER-I2C"),
        blocks.Row("TCA9534", SOIC16, 1, "Texas Instruments", "TCA9534DWR"),
        blocks.Row("100n", C_0603, 1, "Vishay", "VJ0603Y104KXJCW1BC"),
    ]
    d.files = {
        "ratings.json": blocks.ratings_json("nasa-eee-inst-002", block.ratings, own),
        "parts.csv": blocks.parts_csv(block.rows + rows),
        **block.files,
    }
    return d
