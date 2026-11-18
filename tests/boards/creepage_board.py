"""The board of the creepage fixtures: `pass-creepage`, `fail-creepage` and `pass-creepage-slot`.

2 single pins, J1 on HV at (110, 107.5) and J2 on GND on the same row. Each pad is a 1.7 mm square on both
faces (PinHeader_1x01_P2.54mm_Vertical), so the gap is the distance between the centres less 1.7 mm. No
track: each net has 1 pad. Each fixture's own `design.py` calls `build()` with its variant; regenerate
with `workcenter design tests/boards/<fixture>/design.py`.

pass:  J2 at x 115: 3.3 mm.
fail:  J2 at x 113.7: 2 mm.
slot:  J2 at x 115, and a slot cut through the board from (112, 105) to (113, 110): 1 mm wide, 5 mm long.
clear: J2 at x 113: 1.3 mm.
narrow: J2 at x 115, and a slot from (112.1, 105) to (112.9, 110): 0.8 mm wide.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import kicadgen  # noqa: E402

PIN = "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical"
NAMESPACE = {
    "pass": "5c1e7a2d-4b6f-4e0a-9d3c-2f8b1a6e7c01",
    "fail": "5c1e7a2d-4b6f-4e0a-9d3c-2f8b1a6e7c02",
    "slot": "5c1e7a2d-4b6f-4e0a-9d3c-2f8b1a6e7c03",
    "clear": "5c1e7a2d-4b6f-4e0a-9d3c-2f8b1a6e7c04",
    "narrow": "5c1e7a2d-4b6f-4e0a-9d3c-2f8b1a6e7c05",
}
J2_X = {"pass": 115.0, "fail": 113.7, "slot": 115.0, "clear": 113.0, "narrow": 115.0}
CUTOUTS = {"slot": [(112.0, 105.0, 113.0, 110.0)], "narrow": [(112.1, 105.0, 112.9, 110.0)]}


def build(variant: str) -> kicadgen.Design:
    d = kicadgen.Design(
        name="creepage",
        namespace=uuid.UUID(NAMESPACE[variant]),
        outline=(100.0, 100.0, 125.0, 115.0),
        copper_layers=2,
    )
    d.power_nets = {"GND": "GND"}
    d.flagged_nets = ["GND"]
    d.add(
        "J1",
        "Connector_Generic:Conn_01x01",
        "HV",
        PIN,
        sch_at=(50.8, 50.8),
        pcb_at=(110.0, 107.5),
        nets={"1": "HV"},
    )
    d.add(
        "J2",
        "Connector_Generic:Conn_01x01",
        "RETURN",
        PIN,
        sch_at=(76.2, 50.8),
        pcb_at=(J2_X[variant], 107.5),
        nets={"1": "GND"},
    )
    if variant in CUTOUTS:
        d.cutouts = CUTOUTS[variant]
    return d
