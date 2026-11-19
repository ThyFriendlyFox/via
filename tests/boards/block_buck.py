"""The board of the buck block's fixtures: 5 V in on J1, the block of tools/blocks.py, 3.3 V out on J2.

`build(amps)` returns the design with the load `amps` on J2. pass-block-buck asks 0.5 A, and the block
takes the first stocked inductor, Bourns SRN2010TA-2R2M; pass-block-buck-2x asks 1.0 A, and the block
takes Coilcraft XAL4020-222MEC. tests/test_blocks.py works out both by hand.
"""

from __future__ import annotations

import uuid
from pathlib import Path

# `workcenter design` puts Via's tools/ on the import path before it loads a design file.
import blocks
import kicadgen

HERE = Path(__file__).resolve().parent
HEADER_2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
R_0603 = "Resistor_SMD:R_0603_1608Metric"
C_0603 = "Capacitor_SMD:C_0603_1608Metric"
C_0805 = "Capacitor_SMD:C_0805_2012Metric"

# The parts the designer can buy, in the order the block should try them.
STOCK = [
    blocks.Stock("Bourns", "SRN2010TA-2R2M", "2.2u SRN2010TA", "Inductor_SMD:L_0805_2012Metric"),
    blocks.Stock("Coilcraft", "XAL4020-222MEC", "2.2u XAL4020", "Inductor_SMD:L_Coilcraft_XAL4020-XXX"),
    blocks.Stock("Vishay", "CRCW0603100KFKEA", "100k", R_0603),
    blocks.Stock("Vishay", "CRCW0603453KFKEA", "453k", R_0603),
    blocks.Stock("Vishay", "CRCW0603470KFKEA", "470k", R_0603),
    blocks.Stock("made up", "FIXTURE-10U-16V", "10u 16V", C_0805),
    blocks.Stock("Samsung", "CL10A106KP8NNN", "10u 10V", C_0603),
]

# The row of the output capacitors' maker's page, as tests/boards/fail-sim-bias/library/sources.csv holds
# it: the SIM gate runs C2 and C3 on the curves of their facts only when this row names its SHA256.
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
        namespace=uuid.UUID("5d0e3a7c-2b41-4c8e-9f6a-1e7b3c9d2a58"),
        outline=(100.0, 100.0, 140.0, 125.0),
        sheet="A4",
    )
    d.power_nets = {"+5V": "+5V", "+3V3": "+3V3", "GND": "GND"}
    # +5V and GND arrive on J1, and +3V3 stands behind the inductor: no power-output pin drives them.
    d.flagged_nets = ["+5V", "+3V3", "GND"]
    d.add("J1", "Connector_Generic:Conn_01x02", "5V IN", HEADER_2, sch_at=(50.8, 76.2), pcb_at=(104.0, 112.0),
          nets={"1": "+5V", "2": "GND"})  # fmt: skip
    d.add("J2", "Connector_Generic:Conn_01x02", "LOAD", HEADER_2, sch_at=(203.2, 76.2), pcb_at=(136.0, 112.0),
          nets={"1": "+3V3", "2": "GND"})  # fmt: skip
    block = blocks.buck(
        d,
        ic="TLV62569DBVR",
        vin=(4.75, 5.25),
        vout=3.3,
        amps=amps,
        nets=("+5V", "+3V3", "GND"),
        stock=STOCK,
        facts=HERE / "library" / "facts",
        sch_at=(76.2, 76.2),
        pcb_at=(108.0, 106.0),
    )
    own = {
        "nets": {"GND": {"volts": [0, 0], "source": "the reference: J1 pin 2"}},
        "parts": {
            "J2.1": {"amps": amps, "source": f"the load on J2: {amps:g} A at the most, this fixture's own"}
        },
    }
    d.files = {
        "ratings.json": blocks.ratings_json("nasa-eee-inst-002", block.ratings, own),
        "parts.csv": blocks.parts_csv(block.rows),
        "library/sources.csv": SOURCES,
        **block.files,
    }
    return d
