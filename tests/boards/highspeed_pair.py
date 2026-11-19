"""The board of the high-speed fixtures: a USB 2.0 pair on F.Cu between 2 headers, over a ground plane.

`build(fault)` returns the design with no fault, or with 1 planted. Each fixture's `design.py` names
its own, and `tests/boards/README.md` says what each makes `workcenter highspeed` print.

    ""       the pair is 0.31 mm wide, 0.2 mm apart, its 2 tracks 30.112 mm long each, over 1 plane
    width    both tracks are 0.2 mm wide
    skew     USB_D_N steps 1 mm aside and back near the middle: 2 mm longer than USB_D_P
    plane    the plane on In1.Cu is 2 pours with a 1 mm gap at x = 120 to 121 mm, under the pair

The pair's centre line runs at y = 108 mm; each track leaves its pad at 0.5 mm in x and 0.245 mm in y,
so each end adds sqrt(0.5^2 + 0.245^2) = 0.5568 mm to the 29 mm between: 30.1136 mm a track. The
boards are written with `workcenter design`, not routed: every track is drawn here.
"""

from __future__ import annotations

import uuid

# `workcenter design` puts Via's tools/ on the import path before it loads a design file.
import kicadgen

FAULTS = ("", "width", "skew", "plane")

HEADER_3 = "Connector_PinHeader_1.00mm:PinHeader_1x03_P1.00mm_Vertical"


def build(fault: str = "") -> kicadgen.Design:
    if fault not in FAULTS:
        raise ValueError(f"{fault!r} is no fault of this board: {', '.join(FAULTS[1:])}")
    d = kicadgen.Design(
        name="pair",
        namespace=uuid.UUID("8c2d4e6f-1a3b-4c5d-9e7f-0a1b2c3d4e5f"),
        outline=(100.0, 100.0, 140.0, 116.0),
        copper_layers=4,
        plane_layers=("In1.Cu",),
        track_width=0.2,
        clearance=0.15,
    )
    d.power_nets = {"GND": "GND"}
    d.flagged_nets = ["GND"]
    for ref, x, sch_x in (("J1", 105.0, 50.8), ("J2", 135.0, 101.6)):
        d.add(
            ref,
            "Connector_Generic:Conn_01x03",
            "USB",
            HEADER_3,
            sch_at=(sch_x, 50.8),
            pcb_at=(x, 107.5),
            nets={"1": "USB_D_P", "2": "USB_D_N", "3": "GND"},
        )
    width = 0.2 if fault == "width" else 0.31
    p, n = 108.0 - 0.255, 108.0 + 0.255
    d.track("USB_D_P", [(105.0, 107.5), (105.5, p), (134.5, p), (135.0, 107.5)], "F.Cu", width=width)
    if fault == "skew":
        middle = [(119.5, n), (119.5, n + 1.0), (120.5, n + 1.0), (120.5, n)]
    else:
        middle = []
    d.track("USB_D_N", [(105.0, 108.5), (105.5, n), *middle, (134.5, n), (135.0, 108.5)], "F.Cu", width=width)
    if fault == "plane":
        d.zone(
            "GND",
            layers=("In1.Cu",),
            polygon=[(100.3, 100.3), (120.0, 100.3), (120.0, 115.7), (100.3, 115.7)],
        )
        d.zone(
            "GND",
            layers=("In1.Cu",),
            polygon=[(121.0, 100.3), (139.7, 100.3), (139.7, 115.7), (121.0, 115.7)],
        )
    else:
        d.zone("GND", layers=("In1.Cu",))
    return d
