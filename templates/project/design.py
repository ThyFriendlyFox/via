"""divider: a voltage divider and a filter capacitor behind a 3-pin header.

The smallest complete design file. Copy it into a project as `design.py`. Then change the name, the
namespace, the parts, the nets and the places.

    workcenter design design.py --route    writes the KiCad project beside this file and routes it
    workcenter gates . --strict            runs ERC, DRC, simulation and the fabrication export

The `.kicad_*` files are output. Change this file and run the command again; never edit them.
"""

from __future__ import annotations

import uuid

# `workcenter design` puts the workcenter's tools/ on the import path before it loads this file.
import kicadgen

# Read each part before it goes in. From the workcenter's folder:
#   python3 tools/kicadgen.py pins Device:R Connector_Generic:Conn_01x03    each pin: number, name, type
#   python3 tools/kicadgen.py footprint Resistor_SMD:R_0603_1608Metric      each pad, and the courtyard
R_0603 = "Resistor_SMD:R_0603_1608Metric"
C_0603 = "Capacitor_SMD:C_0603_1608Metric"
HEADER = "Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical"


def build() -> kicadgen.Design:
    """`workcenter design` calls this and writes the design it returns."""
    d = kicadgen.Design(
        # The generated files take this name: divider.kicad_pro, divider.kicad_sch, divider.kicad_pcb.
        name="divider",
        # A uuid.UUID, never a string. Every UUID in the generated files comes from it, so the same
        # design writes the same bytes each time. Make 1 for each design and keep it:
        #   python3 -c "import uuid; print(uuid.uuid4())"
        namespace=uuid.UUID("7c1d9a52-3e4b-4f6a-8b0d-2a5e6f7c8d91"),
        # The board's edge in mm: (left, top, right, bottom). y grows downward. This board is
        # 25 x 20 mm, and its top left corner is at (100, 100), not at (0, 0).
        outline=(100.0, 100.0, 125.0, 120.0),
        sheet="A4",
    )
    # A dict, never a list: each power net, then the symbol of KiCad's `power` library that draws it.
    # A net with no symbol of its own name takes another: {"VIN": "VBUS"}.
    d.power_nets = {"VCC": "VCC", "GND": "GND"}
    # A list: the power nets that no power-output pin drives. Each gets a PWR_FLAG for the ERC. Both
    # rails arrive through J1, so both are here. Leave out a net that a regulator's output drives.
    d.flagged_nets = ["VCC", "GND"]
    # The schematic gets a wire between the pins of each net. Without this line each pin gets a label.
    d.sch_wires = True
    # Every part says how it simulates, or why it does not. With this line `workcenter design` fails
    # until each part has a d.sim() or a d.no_sim(); a plain R, C or L needs neither. An IC, a
    # transistor or a diode gets its maker's model: `workcenter fetch` puts the file in library/, and
    #   d.sim("U1", library="library/<maker>/<file>", name="<subcircuit>", pins={"1": "<node>", ...})
    # names it. A deck that stands in for such a part with a source of its own proves another part.
    d.check_sim = True

    # 1 d.add() for each part: reference, "Library:Symbol", value, "Library:Footprint", then
    #   sch_at  the symbol's place on the sheet in mm. Use multiples of 2.54: each pin then sits on
    #           KiCad's 1.27 mm grid.
    #   pcb_at  the footprint's place in board coordinates, the same as the outline's: between
    #           (100, 100) and (125, 120) on this board.
    #   nets    {pin number: net name}. A pin number is a string, as the `pins` command prints it.
    #           1 name on 2 pins joins them. Leave an unused pin out: it gets a no-connect mark.
    d.add(
        "J1",
        "Connector_Generic:Conn_01x03",
        "IN",
        HEADER,
        sch_at=(139.7, 83.82),
        pcb_at=(104.0, 107.5),
        nets={"1": "VCC", "2": "OUT", "3": "GND"},
    )
    d.no_sim("J1", "a connector: the header's pins are the circuit's terminals")
    d.add(
        "R1",
        "Device:R",
        "10k",
        R_0603,
        sch_at=(101.6, 76.2),
        pcb_at=(110.0, 106.0),
        nets={"1": "VCC", "2": "OUT"},
    )
    d.add(
        "R2",
        "Device:R",
        "10k",
        R_0603,
        sch_at=(101.6, 91.44),
        pcb_at=(110.0, 110.0),
        nets={"1": "OUT", "2": "GND"},
    )
    d.add(
        "C1",
        "Device:C",
        "100n",
        C_0603,
        sch_at=(114.3, 91.44),
        pcb_at=(110.0, 114.0),
        nets={"1": "OUT", "2": "GND"},
    )
    return d
