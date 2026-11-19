"""The board of the ratings fixtures: a 5 V to 3.3 V buck regulator, 2 logic buffers and their parts.

`build(fault)` returns the design with no fault, or with 1 planted. Each fixture's `design.py` names
its own, and `tests/boards/README.md` says what each makes `workcenter ratings` print.

    ""            every stress holds (pass-ratings-node, and fail-ratings-load: there the fault is the
                  1.9 A its ratings.json states for the load)
    pin           U3 and its capacitor stand on +5V: its output puts 5.25 V on U2's 4.6 V input
    decoupling    C1 is left out: U1's supply pin has no capacitor
    inductor      L1 is a 2.0 x 1.6 mm part that saturates at 1.26 A
    bias          C3 is left out: C2 alone keeps under half of its 10 uF at 3.4 V

The boards are not routed and not built: `workcenter ratings` reads the schematic.
"""

from __future__ import annotations

import uuid

# `workcenter design` puts Via's tools/ on the import path before it loads a design file.
import kicadgen

FAULTS = ("", "pin", "decoupling", "inductor", "bias")

HEADER_2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
HEADER_3 = "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"
SOT_23_5 = "Package_TO_SOT_SMD:SOT-23-5"
R_0603 = "Resistor_SMD:R_0603_1608Metric"
C_0603 = "Capacitor_SMD:C_0603_1608Metric"
C_0805 = "Capacitor_SMD:C_0805_2012Metric"
L_XAL4020 = "Inductor_SMD:L_Coilcraft_XAL4020-XXX"
L_0805 = "Inductor_SMD:L_0805_2012Metric"  # the nearest land pattern KiCad has for a 2.0 x 1.6 mm part


def build(fault: str = "") -> kicadgen.Design:
    if fault not in FAULTS:
        raise ValueError(f"{fault!r} is no fault of this board: {', '.join(FAULTS[1:])}")
    d = kicadgen.Design(
        name="node",
        namespace=uuid.UUID("3b0c6f1e-8a52-4d47-9c1b-6e2f0a9d5c34"),
        outline=(100.0, 100.0, 140.0, 130.0),
        sheet="A4",
    )
    d.power_nets = {"+5V": "+5V", "+3V3": "+3V3", "GND": "GND"}
    # +5V and GND arrive on J1, and +3V3 stands behind the inductor: no power-output pin drives them.
    d.flagged_nets = ["+5V", "+3V3", "GND"]
    d.defined_nets = {"IN": "the source on J3 pin 1 drives it"}
    logic_rail = "+5V" if fault == "pin" else "+3V3"

    d.add("J1", "Connector_Generic:Conn_01x02", "5V IN", HEADER_2, sch_at=(50.8, 76.2), pcb_at=(104.0, 108.0),
          nets={"1": "+5V", "2": "GND"})  # fmt: skip
    d.add("J2", "Connector_Generic:Conn_01x02", "LOAD", HEADER_2, sch_at=(203.2, 76.2), pcb_at=(136.0, 108.0),
          nets={"1": "+3V3", "2": "GND"})  # fmt: skip
    d.add("J3", "Connector_Generic:Conn_01x03", "SIGNAL", HEADER_3, sch_at=(50.8, 127), pcb_at=(104.0, 120.0),
          nets={"1": "IN", "2": "OUT", "3": "GND"})  # fmt: skip

    # The regulator: EN is tied to its input, and 453k over 100k under its 0.6 V sets 3.3 V.
    d.add("U1", "Regulator_Switching:TLV62569DBV", "TLV62569", SOT_23_5, sch_at=(101.6, 76.2),
          pcb_at=(114.0, 108.0), nets={"1": "+5V", "2": "GND", "3": "SW", "4": "+5V", "5": "FB"})  # fmt: skip
    if fault == "inductor":
        d.add("L1", "Device:L", "2.2u SRN2010TA", L_0805, sch_at=(127.0, 68.58), pcb_at=(121.0, 106.0),
              nets={"1": "SW", "2": "+3V3"})  # fmt: skip
    else:
        d.add("L1", "Device:L", "2.2u XAL4020", L_XAL4020, sch_at=(127.0, 68.58), pcb_at=(121.0, 106.0),
              nets={"1": "SW", "2": "+3V3"})  # fmt: skip
    d.add("R1", "Device:R", "453k", R_0603, sch_at=(142.24, 76.2), pcb_at=(126.0, 112.0),
          nets={"1": "+3V3", "2": "FB"})  # fmt: skip
    d.add("R2", "Device:R", "100k", R_0603, sch_at=(142.24, 91.44), pcb_at=(126.0, 115.0),
          nets={"1": "FB", "2": "GND"})  # fmt: skip
    if fault != "decoupling":
        d.add("C1", "Device:C", "10u 16V", C_0805, sch_at=(76.2, 83.82), pcb_at=(109.0, 112.0),
              nets={"1": "+5V", "2": "GND"})  # fmt: skip
    d.add("C2", "Device:C", "10u 6.3V", C_0603, sch_at=(160.02, 83.82), pcb_at=(130.0, 106.0),
          nets={"1": "+3V3", "2": "GND"})  # fmt: skip
    if fault != "bias":
        d.add("C3", "Device:C", "10u 6.3V", C_0603, sch_at=(172.72, 83.82), pcb_at=(130.0, 109.0),
              nets={"1": "+3V3", "2": "GND"})  # fmt: skip

    # 2 buffers in a row: the signal comes in on J3, through U3 and U2, and leaves on J3.
    d.add("U3", "74xGxx:74LVC1G17", "SN74LVC1G17", SOT_23_5, sch_at=(101.6, 127.0), pcb_at=(112.0, 122.0),
          nets={"2": "IN", "3": "GND", "4": "SIG", "5": logic_rail})  # fmt: skip
    d.add("U2", "74xGxx:74AUP1G17", "SN74AUP1G17", SOT_23_5, sch_at=(152.4, 127.0), pcb_at=(122.0, 122.0),
          nets={"2": "SIG", "3": "GND", "4": "OUT", "5": "+3V3"})  # fmt: skip
    d.add("C4", "Device:C", "100n", C_0603, sch_at=(172.72, 134.62), pcb_at=(127.0, 122.0),
          nets={"1": "+3V3", "2": "GND"})  # fmt: skip
    d.add("C5", "Device:C", "100n", C_0603, sch_at=(121.92, 134.62), pcb_at=(117.0, 122.0),
          nets={"1": logic_rail, "2": "GND"})  # fmt: skip
    return d
