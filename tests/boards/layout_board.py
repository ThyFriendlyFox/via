"""The board of the layout pack fixtures: `pass-layout`, `fail-layout-esd` and `fail-layout-emi`.

A 4-pin header J1 (VBUS, DA, DB, GND) where a cable enters the device, a TVS diode (D1 to D3) from each
of its 3 other pins to GND, a 100 nF capacitor C1 on VBUS and a resistor (R1, R2) on each data line for
the part the TVS protects. GND is poured on both faces. 2 copper layers, so the 3:1 rule of TI SZZA009
section 2.1.1 applies. Each fixture's own `design.py` calls `build()` with its variant; regenerate with
`workcenter design tests/boards/<fixture>/design.py`.

pass:  J1.1 to D1.1 2.55 mm of 1.2 mm track (2.125 to 1), D1.1 to C1.1 2.8875 mm (2.41 to 1). Each data
       line runs on F.Cu from J1 to its TVS, then by a via to B.Cu and on to its resistor 6.54 mm away.
esd:   VBUS reaches D1 from J1 by B.Cu and a via (rule no-via), 4.67 mm of copper, while C1.1 lies 2.89 mm
       of copper from D1.1 (rule nearest); D2 stands at x 108.4, 4.35 mm from J1.2, and R1.1 3.94 mm
       from D2.1 (rule nearest); DB has no TVS (rule protector).
emi:   C1 stands 0.8 mm further: D1.1 to C1.1 is 3.6875 mm of 1.2 mm track, 3.07 to 1 (rule power-ratio).
tee:   VBUS branches at J1.1: 107.35 - 103 = 4.35 mm across to D1.1 (D1 at x 108.4), and 104 - 101.1125 =
       2.8875 mm up to C1.1 (C1 above J1 at (103, 100.2)), both 1.5 mm wide. C1.1 stands further from D1.1
       than D1.1 from J1.1, but nearer J1.1 than D1.1 (rule nearest, SLVA680A section 2.3, Case 2).
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import kicadgen  # noqa: E402

CITES = {"ti-slva680a": "section 2.3, Case 2", "ti-szza009": "section 2.1.1"}

HEADER = "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
TVS = "Diode_SMD:D_SOD-323"
C0805 = "Capacitor_SMD:C_0805_2012Metric"
R0805 = "Resistor_SMD:R_0805_2012Metric"
NAMESPACE = {
    "pass": "3b0d6c1e-8f2a-4c55-9e1d-7a4b2c6d8e01",
    "esd": "3b0d6c1e-8f2a-4c55-9e1d-7a4b2c6d8e02",
    "emi": "3b0d6c1e-8f2a-4c55-9e1d-7a4b2c6d8e03",
    "tee": "3b0d6c1e-8f2a-4c55-9e1d-7a4b2c6d8e04",
}
ROWS = {"VBUS": 104.0, "DA": 106.54, "DB": 109.08}
WIDE = 1.2  # VBUS


def build(variant: str) -> kicadgen.Design:
    d = kicadgen.Design(
        name="layout",
        namespace=uuid.UUID(NAMESPACE[variant]),
        outline=(100.0, 96.5, 116.0, 114.0),
        copper_layers=2,
        track_width=0.3,
        clearance=0.2,
    )
    d.power_nets = {"GND": "GND", "VBUS": "VBUS"}
    d.flagged_nets = ["GND", "VBUS"]
    d.add(
        "J1",
        "Connector_Generic:Conn_01x04",
        "CABLE",
        HEADER,
        sch_at=(50.8, 50.8),
        pcb_at=(103.0, 104.0),
        nets={"1": "VBUS", "2": "DA", "3": "DB", "4": "GND"},
    )
    tvs_x = {
        "VBUS": 108.4 if variant == "tee" else 106.6,
        "DA": 108.4 if variant == "esd" else 106.6,
        "DB": 106.6,
    }
    for i, net in enumerate(("VBUS", "DA", "DB"), start=1):
        if variant == "esd" and net == "DB":
            continue
        d.add(
            f"D{i}",
            "Device:D_TVS",
            "TVS",
            TVS,
            sch_at=(50.8 + 25.4 * i, 50.8),
            pcb_at=(tvs_x[net], ROWS[net]),
            nets={"1": net, "2": "GND"},
        )
    c1_y = 99.4 if variant == "emi" else 100.2
    c1_x = 103.0 if variant == "tee" else 105.55
    d.add(
        "C1",
        "Device:C",
        "100n",
        C0805,
        sch_at=(152.4, 50.8),
        pcb_at=(c1_x, c1_y),
        pcb_rot=90,
        nets={"1": "VBUS", "2": "GND"},
    )
    r1_x = 112.2 if variant == "esd" else 113.0
    for ref, net, x in (("R1", "DA", r1_x), ("R2", "DB", 113.0)):
        d.add(
            ref,
            "Device:R",
            "10k",
            R0805,
            sch_at=(152.4 + 25.4 * int(ref[1]), 50.8),
            pcb_at=(x, ROWS[net]),
            nets={"1": net, "2": "GND"},
        )
    for part in d.parts:  # rows 2.54 mm apart leave no room for a designator between them
        part.hide_ref = True
    d.zone("GND", layers=("F.Cu", "B.Cu"), connect="solid")
    # VBUS: J1.1 to D1.1, D1.1 to C1.1 (C1's pad 1 stands 0.9125 mm below its centre, turned 90 degrees).
    d1 = (tvs_x["VBUS"] - 1.05, ROWS["VBUS"])
    c1 = (c1_x, c1_y + 0.9125)
    if variant == "tee":
        d.track("VBUS", [(103.0, 104.0), d1], "F.Cu", width=1.5)
        d.track("VBUS", [(103.0, 104.0), c1], "F.Cu", width=1.5)
    elif variant == "esd":
        d.track("VBUS", [(103.0, 104.0), (104.5, 102.5)], "B.Cu", width=0.6)
        d.via("VBUS", 104.5, 102.5)
        d.track("VBUS", [(104.5, 102.5), (105.55, 102.5), d1], "F.Cu", width=0.6)
    else:
        d.track("VBUS", [(103.0, 104.0), d1], "F.Cu", width=WIDE)
    if variant != "tee":
        d.track("VBUS", [d1, c1], "F.Cu", width=WIDE)
    # DA: F.Cu from J1.2 to D2.1, a via above D2.1, B.Cu, a via above R1.1, F.Cu down to R1.1.
    da = (tvs_x["DA"] - 1.05, ROWS["DA"])
    r1 = (r1_x - 0.9125, ROWS["DA"])
    d.track("DA", [(103.0, ROWS["DA"]), da, (da[0], 105.5)], "F.Cu")
    d.via("DA", da[0], 105.5)
    d.track("DA", [(da[0], 105.5), (r1[0], 105.5)], "B.Cu")
    d.via("DA", r1[0], 105.5)
    d.track("DA", [(r1[0], 105.5), r1], "F.Cu")
    # DB: through D3.1 and down under it; without D3 (esd), straight along F.Cu to R2.1.
    r2 = (113.0 - 0.9125, ROWS["DB"])
    if variant == "esd":
        d.track("DB", [(103.0, ROWS["DB"]), r2], "F.Cu")
    else:
        db = (tvs_x["DB"] - 1.05, ROWS["DB"])
        d.track("DB", [(103.0, ROWS["DB"]), db, (db[0], 110.3)], "F.Cu")
        d.via("DB", db[0], 110.3)
        d.track("DB", [(db[0], 110.3), (111.0, 110.3)], "B.Cu")
        d.via("DB", 111.0, 110.3)
        d.track("DB", [(111.0, 110.3), (111.0, ROWS["DB"]), r2], "F.Cu")
    return d
