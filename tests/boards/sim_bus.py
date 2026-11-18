"""The board of the deck-need fixtures: a 3.3 V regulator and an I2C header with its 2 pull-ups.

`build()` returns the design. `pass-sim-bus/design.py` names it, and `tests/boards/README.md` says what
the SIM gate and `workcenter next` make of it. The board asks for 2 decks: the I2C lines SDA and SCL
are pulled up by R1 and R2 to +3V3, and U1, a regulator of KiCad's `Regulator_Linear` library, feeds
the 100 mA its `ratings.json` states for J2 pin 1.

The board is not routed: the SIM gate and `next` read the schematic.
"""

from __future__ import annotations

import uuid

# `workcenter design` puts the workcenter's tools/ on the import path before it loads a design file.
import kicadgen

HEADER_2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
HEADER_4 = "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
SOT_23_5 = "Package_TO_SOT_SMD:SOT-23-5"
R_0603 = "Resistor_SMD:R_0603_1608Metric"
C_0603 = "Capacitor_SMD:C_0603_1608Metric"


def build() -> kicadgen.Design:
    d = kicadgen.Design(
        name="bus",
        namespace=uuid.UUID("5e2f7a90-1c3d-4b8e-a6f2-9d04c1b7e3a8"),
        outline=(100.0, 100.0, 130.0, 120.0),
        sheet="A4",
    )
    d.power_nets = {"+5V": "+5V", "+3V3": "+3V3", "GND": "GND"}
    # +5V and GND arrive on J1; U1's output pin drives +3V3.
    d.flagged_nets = ["+5V", "GND"]

    d.add("J1", "Connector_Generic:Conn_01x02", "5V IN", HEADER_2, sch_at=(50.8, 76.2), pcb_at=(104.0, 106.0),
          nets={"1": "+5V", "2": "GND"})  # fmt: skip
    # The regulator: EN is tied to its input.
    d.add("U1", "Regulator_Linear:TLV75533PDBV", "TLV75533", SOT_23_5, sch_at=(101.6, 76.2),
          pcb_at=(112.0, 106.0), nets={"1": "+5V", "2": "GND", "3": "+5V", "5": "+3V3"})  # fmt: skip
    d.add("C1", "Device:C", "1u", C_0603, sch_at=(76.2, 83.82), pcb_at=(108.0, 110.0),
          nets={"1": "+5V", "2": "GND"})  # fmt: skip
    d.add("C2", "Device:C", "1u", C_0603, sch_at=(127.0, 83.82), pcb_at=(116.0, 110.0),
          nets={"1": "+3V3", "2": "GND"})  # fmt: skip

    # The I2C header: 3.3 V, the 2 lines and ground; a pull-up on each line.
    d.add("J2", "Connector_Generic:Conn_01x04", "I2C", HEADER_4, sch_at=(203.2, 76.2), pcb_at=(126.0, 108.0),
          nets={"1": "+3V3", "2": "SDA", "3": "SCL", "4": "GND"})  # fmt: skip
    d.add("R1", "Device:R", "4.7k", R_0603, sch_at=(160.02, 68.58), pcb_at=(120.0, 104.0),
          nets={"1": "+3V3", "2": "SDA"})  # fmt: skip
    d.add("R2", "Device:R", "4.7k", R_0603, sch_at=(172.72, 68.58), pcb_at=(120.0, 108.0),
          nets={"1": "+3V3", "2": "SCL"})  # fmt: skip
    return d
