"""The Vantron VOSM6490: a Qualcomm QCS6490 on an OSM Size-L module, 45 x 45 mm, 662 LGA pads.

OSM (Open Standard Module) is SGET's standard for modules soldered straight onto the board: no
connector, a grid of round pads underneath. Size-L is 45 x 45 mm.

The land pattern is the standard's (SGET OSM v1.2, section 6, the Size-L contact map): a 35 x 35
grid at 1.25 mm pitch, rows A to AR (no I, O, Q, S, X or Z) and columns 1 to 35, pad A1's corner at
the module's top left seen from above; 0.80 mm round pads. Not every place on the grid has a pad:
`populated` lists the 662 that do. The pattern equals the open footprint Antmicro publishes for
OSM-L (its `OSM-L_Carrier-side`, Apache-2.0), pad for pad.

`osm_l_pins.csv` names every pad:
- `osm`, the standard's signal name, as Antmicro's open OSM-L carrier schematic draws it
  (openhardware.antmicro.com/boards/bmc-reference-carrier-board, Apache-2.0);
- `vosm6490`, Vantron's name for the pads this board uses, read by hand from the VOSM6490
  datasheet's pin tables (vantrontech.com, read 2026-11-12). Where Vantron uses a pad for something
  the standard leaves to the vendor, its name rules: AA30 and AA31 are EXT_GPIO_1 and EXT_GPIO_2,
  and D9 and C8 are the CC pins of the module's own Type-C controller (in its PM7250B PMIC), where
  the standard has USB_C_ID and USB_C_OC#.

The module's supply (VCC_IN_5V, 17 pads) is 4.8 to 5.2 V, 5 V / 3 A (VOSM6490 datasheet); its
VCC_OUT_IO (U18) is a 1.8 V output for the board's own 1.8 V parts, under 100 mA.
"""

from __future__ import annotations

import csv
from pathlib import Path

HERE = Path(__file__).resolve().parent

SIZE = 45.0  # mm, square
PITCH = 1.25
PAD = 0.80  # round pad, copper; the stencil opens it 1:1
# mm above the board: Vantron's datasheet gives no height, so the body is drawn at the 2.5 mm that
# Advantech gives for its QCS6490 OSM module (AOM-2721) and Kontron for its OSM-S. A stand-in.
HEIGHT = 2.5
ROWS = "A B C D E F G H J K L M N P R T U V W Y AA AB AC AD AE AF AG AH AJ AK AL AM AN AP AR".split()


def populated(row: str) -> list[int]:
    """The columns that carry a pad in `row` (SGET OSM v1.2, Size-L contact map)."""
    if row in ("A", "AC", "AR"):
        return [*range(2, 11), *range(14, 23), *range(26, 35)]
    if row == "B":
        return [*range(1, 12), 13, *range(15, 24), *range(25, 36)]
    if row in ("C", "D", "Y", "AA", "AB"):
        return [*range(1, 12), *range(13, 24), *range(25, 36)]
    if row in ROWS[ROWS.index("E") : ROWS.index("W") + 1]:
        return [1, 2, 3, 4, *range(15, 22), 32, 33, 34, 35]
    if row == "AD":
        return []
    if row == "AE":
        return [2, 3, 4, 32, 33, 34]
    if row in ("AF", "AG", "AH", "AJ", "AK", "AL"):
        return [1, 2, 3, 4, 32, 33, 34, 35]
    return list(range(1, 36))  # AM, AN, AP


def pad_xy(pad: str) -> tuple[float, float]:
    """A pad's centre from the module's centre, seen from above: x to the right (column 1 at the
    left), y down (row A at the top), mm."""
    row = pad.rstrip("0123456789")
    col = int(pad[len(row) :])
    return (round(PITCH * col - SIZE / 2, 4), round(PITCH * (ROWS.index(row) + 1) - SIZE / 2, 4))


PADS = [f"{r}{c}" for r in ROWS for c in populated(r)]


def _names() -> tuple[dict[str, str], dict[str, str]]:
    osm: dict[str, str] = {}
    vosm: dict[str, str] = {}
    with (HERE / "osm_l_pins.csv").open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            osm[row["pad"]] = row["osm"]
            if row["vosm6490"]:
                vosm[row["pad"]] = row["vosm6490"]
    if sorted(osm) != sorted(PADS):
        raise SystemExit("osm_l_pins.csv does not name the 662 pads of the Size-L pattern")
    return osm, vosm


OSM, VOSM6490 = _names()


def name(pad: str) -> str:
    """The pad's name on this board's symbol: Vantron's where read, else the standard's."""
    return VOSM6490.get(pad, OSM[pad])


if __name__ == "__main__":
    print(len(PADS), "pads;", sum(1 for p in PADS if OSM[p] == "GND"), "GND;", len(VOSM6490), "named by Vantron")
