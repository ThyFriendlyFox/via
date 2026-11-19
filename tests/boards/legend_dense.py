"""The board of the dense legend fixture: parts packed so close that the library's own designator places
break the legend's rules, and the placer of tools/legend.py finds each a place.

`build(place)` returns the design; with `place` the design sets `place_designators`. On a board 30 x 20 mm:

    U1  SOIC-8 at (115, 110)
    R1..R4  0603 left of U1 at x = 109.2, y = 107.5, 109, 110.5, 112: their courtyards 0.04 mm apart
    C1..C4  0603 right of U1 at x = 120.8, the same rows
    J1  a 1x4 header turned 90 degrees along the top edge at (104, 101.6): the library's designator is
        over the edge
    R5  0603 on the back at (125, 104)
    "DENSE"  the design's own text at (122, 117), which the placer does not move

No pin is on a net: the fixture is for the legend alone. `workcenter design tests/boards/<fixture>/
design.py` writes the KiCad files again, and a test compares the board.
"""

from __future__ import annotations

import uuid

# `workcenter design` puts Via's tools/ on the import path before it loads a design file.
import kicadgen

R_0603 = "Resistor_SMD:R_0603_1608Metric"
C_0603 = "Capacitor_SMD:C_0603_1608Metric"
SOIC_8 = "Package_SO:SOIC-8_3.9x4.9mm_P1.27mm"
HEADER_4 = "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"
ROWS = (107.5, 109.0, 110.5, 112.0)


def build(place: bool = True) -> kicadgen.Design:
    d = kicadgen.Design(
        name="dense",
        namespace=uuid.UUID("3c7f2a91-5e4b-4d08-a6c1-8b2e9f0d7a35"),
        outline=(100.0, 100.0, 130.0, 120.0),
        sheet="A4",
        place_designators=place,
    )
    d.add("U1", "Connector_Generic:Conn_01x08", "IC", SOIC_8, sch_at=(101.6, 76.2), pcb_at=(115.0, 110.0),
          nets={})  # fmt: skip
    for i, y in enumerate(ROWS, 1):
        d.add(f"R{i}", "Device:R", "10k", R_0603, sch_at=(50.8, 50.8 + 10.16 * i), pcb_at=(109.2, y), nets={})
        d.add(
            f"C{i}", "Device:C", "100n", C_0603, sch_at=(152.4, 50.8 + 10.16 * i), pcb_at=(120.8, y), nets={}
        )
    d.add("J1", "Connector_Generic:Conn_01x04", "IO", HEADER_4, sch_at=(25.4, 76.2), pcb_at=(104.0, 101.6),
          pcb_rot=90.0, nets={})  # fmt: skip
    d.add("R5", "Device:R", "1k", R_0603, sch_at=(50.8, 101.6), pcb_at=(125.0, 104.0), pcb_layer="B.Cu",
          nets={})  # fmt: skip
    d.text("DENSE", 122.0, 117.0, size=1.0, thickness=0.15)
    return d
