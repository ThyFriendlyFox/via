"""The board of the linear regulator block's fixtures: 5 V in on J1, the block of tools/blocks_ldo.py,
3.3 V out on J2.

`build(amps)` returns the design with the load `amps` on J2, at an ambient of 0 to 30 C. pass-block-ldo
asks 0.1 A, and the block takes the first stocked IC, TLV75533PDBVR (SOT-23-5); pass-block-ldo-2x asks
0.2 A, where that IC's junction would pass the pack's 85 C, and the block takes TLV75533PDRVR (WSON-6).
tests/test_blocks_ldo.py works out both by hand.
"""

from __future__ import annotations

import uuid
from pathlib import Path

# `workcenter design` puts Via's tools/ on the import path before it loads a design file.
import blocks
import kicadgen

CITES = {"ti-sbvs320": "table 4-1, page 3: the WSON-6's thermal pad on a large ground plane"}
HERE = Path(__file__).resolve().parent
HEADER_2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
C_0603 = "Capacitor_SMD:C_0603_1608Metric"
C_0805 = "Capacitor_SMD:C_0805_2012Metric"

# The parts the designer can buy, in the order the block should try them.
STOCK = [
    blocks.Stock("Texas Instruments", "TLV75533PDBVR", "TLV75533P", "Package_TO_SOT_SMD:SOT-23-5"),
    blocks.Stock(
        "Texas Instruments", "TLV75533PDRVR", "TLV75533P", "Package_SON:WSON-6-1EP_2x2mm_P0.65mm_EP1x1.6mm"
    ),
    blocks.Stock("made up", "FIXTURE-10U-16V", "10u 16V", C_0805),
    blocks.Stock("Samsung", "CL10A106KP8NNN", "10u 10V", C_0603),
]


def build(amps: float) -> kicadgen.Design:
    d = kicadgen.Design(
        name="node",
        namespace=uuid.UUID("8c1f4b2e-6a3d-4f7e-b905-2d4e6f8a1c37"),
        outline=(100.0, 100.0, 135.0, 120.0),
        sheet="A4",
    )
    d.power_nets = {"+5V": "+5V", "+3V3": "+3V3", "GND": "GND"}
    # +5V and GND arrive on J1; U1's OUT, a power output, drives +3V3.
    d.flagged_nets = ["+5V", "GND"]
    d.add("J1", "Connector_Generic:Conn_01x02", "5V IN", HEADER_2, sch_at=(50.8, 76.2), pcb_at=(104.0, 108.0),
          nets={"1": "+5V", "2": "GND"})  # fmt: skip
    d.add("J2", "Connector_Generic:Conn_01x02", "LOAD", HEADER_2, sch_at=(165.1, 76.2), pcb_at=(131.0, 108.0),
          nets={"1": "+3V3", "2": "GND"})  # fmt: skip
    block = blocks.ldo(
        d,
        vin=(4.75, 5.25),
        vout=3.3,
        amps=amps,
        ambient=(0, 30),
        pack="nasa-eee-inst-002",
        nets=("+5V", "+3V3", "GND"),
        stock=STOCK,
        facts=HERE / "library" / "facts",
        sch_at=(76.2, 76.2),
        pcb_at=(111.0, 108.0),
    )
    # A ground pour on both layers: SBVS320D asks the thermal pad of the WSON-6 on a large ground plane
    # (table 4-1, page 3), and the pour reaches the pad the router does not.
    d.zone("GND", layers=("F.Cu", "B.Cu"), connect="solid")
    own = {
        "nets": {"GND": {"volts": [0, 0], "source": "the reference: J1 pin 2"}},
        "parts": {
            "J2.1": {"amps": amps, "source": f"the load on J2: {amps:g} A at the most, this fixture's own"}
        },
    }
    d.files = {
        "ratings.json": blocks.ratings_json("nasa-eee-inst-002", block.ratings, own),
        "parts.csv": blocks.parts_csv(block.rows),
        **block.files,
    }
    return d
