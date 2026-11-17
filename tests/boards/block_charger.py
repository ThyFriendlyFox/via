"""The board of the charger block's fixtures: 4.75 V to 5.25 V in on J1, the block of
tools/blocks_charger.py, the cell on J2 and the system's supply on J3.

`build(amps)` returns the design with the fast charge current `amps`. pass-block-charger asks 0.15 A, and
the block takes 3.6k for RISET; refuse-block-charger-2x asks 0.3 A, and the block refuses it: 1.8k would
heat the charger to 160 C at 40 C. tests/test_blocks_charger.py works out both by hand.
"""

from __future__ import annotations

import uuid
from pathlib import Path

# `workcenter design` puts the workcenter's tools/ on the import path before it loads a design file.
import blocks
import kicadgen

HERE = Path(__file__).resolve().parent
HEADER_2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
HEADER_3 = "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"
R_0603 = "Resistor_SMD:R_0603_1608Metric"
C_0603 = "Capacitor_SMD:C_0603_1608Metric"
PACK = "ecss-q-st-30-11c-rev2"

# The parts the designer can buy, in the order the block should try them.
STOCK = [
    blocks.Stock("Vishay", "CRCW06031K80FKEA", "1.8k", R_0603),
    blocks.Stock("Vishay", "CRCW06033K60FKEA", "3.6k", R_0603),
    blocks.Stock("Vishay", "CRCW060310K0FKEA", "10k", R_0603),
    blocks.Stock("Vishay", "CRCW0603330RFKEA", "330", R_0603),
    blocks.Stock("Vishay", "CRCW06032K20FKEA", "2.2k", R_0603),
    blocks.Stock("Samsung", "CL10A106KP8NNN", "10u 10V", C_0603),
    blocks.Stock("Vishay", "VJ0603Y104KXJAC", "100n 16V", C_0603),
    blocks.Stock("Texas Instruments", "CSD17313Q2", "CSD17313Q2", "Package_SON:Texas_DQK"),
]
CELL = blocks.Cell(
    volts=(2.5, 4.3),
    charge_amps=0.5,
    discharge_amps=3.0,
    source="the fixture's cell, made up for tests/boards: 2.5 V to 4.3 V, 0.5 A in charge, 3 A in discharge",
)

# The row of the capacitors' maker's page, as tests/boards/block_buck.py holds it.
SOURCES = (
    "MPN,Kind,URL,File,Member,Revision,Dated,Subckt,Ngspice,SHA256,Checked,Note\n"
    "CL10A106KP8NNN,datasheet,https://weblib.samsungsem.com/mlcc/mlcc-ec-data-sheet.do?partNumber="
    "CL10A106KP8NNN,,,,,,,e7cb912bac00275e53505aa5870ec3543af75375920ac7fbb31cf92ebea3c182,2026-11-17,"
    "\"kept outside the workcenter's repository, whose fixtures hold no maker's file; the page's graph "
    "data (datasheetData) holds the DC bias and temperature curves, and each fetch differs in its session "
    'token and its time stamp"\n'
)


def build(amps: float) -> kicadgen.Design:
    d = kicadgen.Design(
        name="node",
        namespace=uuid.UUID("8b3f6c21-4d7e-4a90-b5c2-7e19d04f3a66"),
        outline=(100.0, 100.0, 140.0, 125.0),
        sheet="A4",
    )
    d.power_nets = {"+5V": "+5V", "+BATT": "+BATT", "-BATT": "-BATT", "GND": "GND"}
    # +5V and GND arrive on J1, and -BATT, the cell's negative, on J2: no power-output pin drives them.
    # U1's OUT drives +BATT.
    d.flagged_nets = ["+5V", "GND", "-BATT"]
    d.add("J1", "Connector_Generic:Conn_01x03", "5V IN", HEADER_3, sch_at=(30.48, 66.04),
          pcb_at=(103.0, 110.0), nets={"1": "+5V", "2": "GND", "3": "CHG"})  # fmt: skip
    d.add("J2", "Connector_Generic:Conn_01x02", "CELL", HEADER_2, sch_at=(185.42, 63.5),
          pcb_at=(137.0, 104.0), nets={"1": "+BATT", "2": "-BATT"})  # fmt: skip
    d.add("J3", "Connector_Generic:Conn_01x02", "SYSTEM", HEADER_2, sch_at=(185.42, 88.9),
          pcb_at=(137.0, 116.0), nets={"1": "+BATT", "2": "GND"})  # fmt: skip
    block = blocks.charger(
        d,
        ic="BQ21040DBVR",
        protector="BQ29700DSER",
        vin=(4.75, 5.25),
        amps=amps,
        cell=CELL,
        load=1.0,
        ambient=(0.0, 40.0),
        pack=PACK,
        nets={"in": "+5V", "bat": "+BATT", "gnd": "GND", "cell": "-BATT", "chg": "CHG"},
        stock=STOCK,
        facts=HERE / "library" / "facts",
        sch_at=(50.8, 63.5),
        pcb_at=(108.0, 104.0),
    )
    own = {
        "nets": {
            "GND": {"volts": [0, 0], "source": "the reference: J1 pin 2"},
            "CHG": {"volts": [0, 5.25], "source": "the host's pull-up on J1 pin 3, to the input at the most"},
        },
        "parts": {
            "J3.1": {"amps": 1.0, "source": "the system's load on J3: 1 A at the most, this fixture's own"}
        },
    }
    d.files = {
        "ratings.json": blocks.ratings_json(PACK, block.ratings, own),
        "parts.csv": blocks.parts_csv(block.rows),
        "library/sources.csv": SOURCES,
        **block.files,
    }
    return d
