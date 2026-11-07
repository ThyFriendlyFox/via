"""The fixture board of `workcenter inspect` (tests/test_inspect.py).

A divider on four layers with what the inspection commands look at: a ground plane on In1.Cu and a
ground pour on F.Cu, a 10 mm run of 0.2 mm track on In2.Cu between two vias, a T-junction, a
copper keep-out, a parts keep-out, Sierra Circuits' rule file with its 13 mil inner drill rule, and
one pour island on purpose: C1's ground pad ringed by OUT on the top face, with the keep-out
"pocket" over the ring's inside so the generator can drop no via into it.

Regenerate with `workcenter design tests/boards/inspect-four-layer/design.py`; the KiCad files
beside this one are its output.

    J1.1 VIN  F.Cu 3 mm x 0.3 mm, via, In2.Cu 10 mm x 0.2 mm, via, F.Cu 3.0875 mm x 0.3 mm  R1.1

The In2.Cu run stops 0.2 mm short of the second via's centre, inside its ring: `inspect resistance`
measures a track on to the centre of the via or pad it enters, as a hand calculation does.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
import kicadgen  # noqa: E402

R0805 = "Resistor_SMD:R_0805_2012Metric"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
HEADER = "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"


def build() -> kicadgen.Design:
    d = kicadgen.Design(
        name="four_layer",
        namespace=uuid.UUID("5f0e2b7c-3a41-4d8e-9c6b-1e2f3a4b5c6d"),
        outline=(100.0, 100.0, 130.0, 116.0),
        copper_layers=4,
        plane_layers=("In1.Cu",),
        track_width=0.2,
        clearance=0.15,
        via_size=0.65,  # Sierra's 6 mil ring on the board's own 0.3 mm minimum hole
        via_drill=0.3,
        fab="sierra-circuits-web",
    )
    d.power_nets = {"GND": "GND", "VIN": "VBUS"}
    d.flagged_nets = ["GND", "VIN"]
    d.add(
        "J1",
        "Connector_Generic:Conn_01x03",
        "IN",
        HEADER,
        sch_at=(50.8, 50.8),
        pcb_at=(103.0, 104.0),
        nets={"1": "VIN", "2": "OUT", "3": "GND"},
    )
    d.add(
        "R1",
        "Device:R",
        "10k",
        R0805,
        sch_at=(71.12, 45.72),
        pcb_at=(120.0, 104.0),
        nets={"1": "VIN", "2": "OUT"},
    )
    d.add(
        "R2",
        "Device:R",
        "10k",
        R0805,
        sch_at=(71.12, 58.42),
        pcb_at=(124.0, 104.0),
        nets={"1": "OUT", "2": "GND"},
    )
    d.add(
        "C1",
        "Device:C",
        "100n",
        C0805,
        sch_at=(83.82, 58.42),
        pcb_at=(113.0, 110.0),
        nets={"1": "OUT", "2": "GND"},
    )
    d.zone("GND", layers=("In1.Cu",), connect="solid")
    d.zone("GND", layers=("F.Cu",), connect="solid")
    # VIN: a known path for `inspect resistance`, its middle 10 mm on In2.Cu (9.8 mm drawn).
    d.track("VIN", [(103.0, 104.0), (106.0, 104.0)], "F.Cu", width=0.3)
    d.via("VIN", 106.0, 104.0)
    d.track("VIN", [(106.0, 104.0), (115.8, 104.0)], "In2.Cu", width=0.2)
    d.via("VIN", 116.0, 104.0)
    d.track("VIN", [(116.0, 104.0), (119.0875, 104.0)], "F.Cu", width=0.3)
    # OUT: R1 to R2 on the top face; from J1 along the bottom face, up a via into that track at a T.
    d.track("OUT", [(120.9125, 104.0), (123.0875, 104.0)], "F.Cu")
    d.track("OUT", [(103.0, 106.54), (122.0, 106.54)], "B.Cu")
    d.via("OUT", 122.0, 106.54)
    d.track("OUT", [(122.0, 106.54), (122.0, 104.0)], "F.Cu")
    # OUT to C1, then round C1's ground pad on the top face: that pad's pour is an island.
    d.via("OUT", 112.05, 106.54)
    d.track("OUT", [(112.05, 106.54), (112.05, 110.0)], "F.Cu")
    d.track(
        "OUT", [(112.05, 108.6), (115.4, 108.6), (115.4, 111.4), (112.05, 111.4), (112.05, 110.0)], "F.Cu"
    )
    pocket = [(112.6, 108.8), (115.2, 108.8), (115.2, 111.2), (112.6, 111.2)]
    d.keepout(pocket, layers=("F.Cu",), name="pocket")
    # A body resting on the top face: no part under it, tracks and vias allowed.
    strip = [(117.0, 109.0), (119.5, 109.0), (119.5, 113.0), (117.0, 113.0)]
    d.keepout(strip, layers=("F.Cu",), name="strip", parts=True, copper=False)
    return d
