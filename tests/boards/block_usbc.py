"""The board of the USB-C block's fixtures: a USB Type-C receptacle as a sink, the block of
tools/blocks_usbc.py, and 3 headers: J2 takes VBUS to the load, J3 D+ and D-, J4 CC1 and CC2 to the part
that reads the advertisement.

`build(amps)` returns the design with the load `amps` on J2, for a design that detects up to 1.5 A.
pass-block-usbc asks 1.5 A and the block builds the port; fail-block-usbc-2x asks 3.0 A, and the block
refuses it with table 4-20 of the USB Type-C specification. tests/test_blocks_usbc.py works out both.
"""

from __future__ import annotations

import uuid
from pathlib import Path

# `workcenter design` puts the workcenter's tools/ on the import path before it loads a design file.
import blocks
import kicadgen

HERE = Path(__file__).resolve().parent
R_0603 = "Resistor_SMD:R_0603_1608Metric"
C_0603 = "Capacitor_SMD:C_0603_1608Metric"

# The parts the designer can buy, in the order the block should try them.
STOCK = [
    blocks.Stock("Vishay", "CRCW06035K10FKEA", "5.1k", R_0603),
    blocks.Stock("Samsung", "CL10A106KP8NNN", "10u 10V", C_0603),
    blocks.Stock("Samsung", "CL10A475KO8NNN", "4.7u 16V", C_0603),
]


def build(amps: float) -> kicadgen.Design:
    d = kicadgen.Design(
        name="node",
        namespace=uuid.UUID("0b8f3c51-7a2e-4d96-b1c4-6e2a9f5d8c13"),
        outline=(100.0, 100.0, 140.0, 130.0),
        sheet="A4",
        # The library put J1's designator under its own courtyard, which the DRC gate's legend fails.
        place_designators=True,
    )
    d.power_nets = {"VBUS": "VBUS", "GND": "GND"}
    # VBUS and GND arrive on J1: no power-output pin drives them.
    d.flagged_nets = ["VBUS", "GND"]
    header = "Connector_PinHeader_2.54mm:PinHeader_1x0{}_P2.54mm_Vertical"
    d.add("J2", "Connector_Generic:Conn_01x02", "LOAD", header.format(2), sch_at=(152.4, 63.5),
          pcb_at=(105.0, 105.0), nets={"1": "VBUS", "2": "GND"})  # fmt: skip
    d.add("J3", "Connector_Generic:Conn_01x03", "DATA", header.format(3), sch_at=(152.4, 88.9),
          pcb_at=(135.0, 105.0), nets={"1": "D+", "2": "D-", "3": "GND"})  # fmt: skip
    d.add("J4", "Connector_Generic:Conn_01x02", "CC", header.format(2), sch_at=(152.4, 114.3),
          pcb_at=(112.0, 104.0), nets={"1": "CC1", "2": "CC2"})  # fmt: skip
    block = blocks.usbc(
        d,
        amps=amps,
        detects="1.5A",
        nets=("VBUS", "GND", "D+", "D-", "CC1", "CC2"),
        stock=STOCK,
        facts=HERE / "library" / "facts",
        sch_at=(50.8, 88.9),
        pcb_at=(120.0, 121.0),
    )
    own = {
        "nets": {"GND": {"volts": [0, 0], "source": "the reference: J1's GND pins and its shell"}},
        "parts": {
            "J2.1": {"amps": amps, "source": f"the load on J2: {amps:g} A at the most, this fixture's own"},
            "J3.1": {"amps": 0, "source": "the data lines carry no steady current, this fixture's own"},
            "J3.2": {"amps": 0, "source": "the data lines carry no steady current, this fixture's own"},
            "J4.1": {
                "amps": 0,
                "source": "the part that reads CC takes no steady current, this fixture's own",
            },
            "J4.2": {
                "amps": 0,
                "source": "the part that reads CC takes no steady current, this fixture's own",
            },
        },
    }
    d.files = {
        "ratings.json": blocks.ratings_json("nasa-eee-inst-002", block.ratings, own),
        "parts.csv": blocks.parts_csv(block.rows),
        **block.files,
    }
    return d
