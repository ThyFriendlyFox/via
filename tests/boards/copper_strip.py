"""The board of the copper fixtures: a 5 V supply carried 44 mm on a 1.5 mm track to a load header.

`build(neck)` returns the design; with `neck` the supply track narrows to 0.3 mm for 4 mm in its
middle. `tests/boards/README.md` says what each fixture makes `workcenter copper` print.

    J1.1 +5V  F.Cu 1.5 mm, x 103 to 147 (with the neck: 0.3 mm from x 123 to 127)  J2.1
    J1.2 GND  B.Cu 1.5 mm, x 103 to 147                                              J2.2
    R1 220R from +5V to GND, tapped off the supply at x 117.04, before the neck

The boards are not routed by FreeRouting: every track is drawn here. `workcenter copper` reads the board.
"""

from __future__ import annotations

import uuid

# `workcenter design` puts the workcenter's tools/ on the import path before it loads a design file.
import kicadgen

HEADER_2 = "Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical"
R_2512 = "Resistor_SMD:R_2512_6332Metric"


def build(neck: bool = False) -> kicadgen.Design:
    d = kicadgen.Design(
        name="strip",
        namespace=uuid.UUID("9a4e1c2b-7d35-4f60-8b19-2c5e7f3a6d41"),
        outline=(100.0, 100.0, 150.0, 130.0),
        sheet="A4",
    )
    d.power_nets = {"+5V": "+5V", "GND": "GND"}
    d.flagged_nets = ["+5V", "GND"]
    d.add("J1", "Connector_Generic:Conn_01x02", "5V IN", HEADER_2, sch_at=(50.8, 76.2), pcb_at=(103.0, 110.0),
          nets={"1": "+5V", "2": "GND"})  # fmt: skip
    d.add("J2", "Connector_Generic:Conn_01x02", "LOAD", HEADER_2, sch_at=(127.0, 76.2), pcb_at=(147.0, 110.0),
          nets={"1": "+5V", "2": "GND"})  # fmt: skip
    d.add("R1", "Device:R", "220R", R_2512, sch_at=(88.9, 76.2), pcb_at=(120.0, 120.0),
          nets={"1": "+5V", "2": "GND"})  # fmt: skip

    def centre(ref: str, number: str) -> tuple[float, float]:
        box = d.pad_box(ref, number)
        return ((box.x1 + box.x2) / 2, (box.y1 + box.y2) / 2)

    (j1x, y), (j2x, _) = centre("J1", "1"), centre("J2", "1")
    g1, g2 = centre("J1", "2"), centre("J2", "2")
    (r1x, ry), (r2x, _) = centre("R1", "1"), centre("R1", "2")
    if neck:
        d.track("+5V", [(j1x, y), (123.0, y)], "F.Cu", width=1.5)
        d.track("+5V", [(123.0, y), (127.0, y)], "F.Cu", width=0.3)
        d.track("+5V", [(127.0, y), (j2x, y)], "F.Cu", width=1.5)
    else:
        d.track("+5V", [(j1x, y), (j2x, y)], "F.Cu", width=1.5)
    d.track("GND", [g1, g2], "B.Cu", width=1.5)
    d.track("+5V", [(r1x, ry), (r1x, y)], "F.Cu", width=0.5)
    d.track("GND", [(r2x, ry), (125.0, ry)], "F.Cu", width=0.5)
    d.via("GND", 125.0, ry, size=0.8, drill=0.4)
    d.track("GND", [(125.0, ry), (125.0, g1[1])], "B.Cu", width=0.5)
    return d
