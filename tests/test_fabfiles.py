"""The files EXPORT writes for a fab and an assembler, read back against the board (tools/fabfiles.py).

Each check is held here on text written for it: a board of 4 parts, and for each output file 1 that
agrees with the board and 1 with a single fault planted. No engine runs here; tests/test_fabexport.py
runs kicad-cli and KiKit on a fixture.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import fabfiles  # noqa: E402


def pad(number: str, net: str) -> str:
    code = {"": 0, "VCC": 1, "/OUT": 2, "GND": 3}[net]
    return f'(pad "{number}" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net {code} "{net}"))'


def outline(x0: float, y0: float, x1: float, y1: float, skip: int = -1) -> str:
    corners = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    lines = []
    for i in range(4):
        if i == skip:
            continue
        (ax, ay), (bx, by) = corners[i], corners[(i + 1) % 4]
        lines.append(f'(gr_line (start {ax} {ay}) (end {bx} {by}) (layer "Edge.Cuts"))')
    return "\n".join(lines)


def footprint(ref: str, layer: str, attr: str, *pads: str, at: str = "10 10") -> str:
    return (
        f'(footprint "Lib:{ref}" (layer "{layer}") (at {at}) (property "Reference" "{ref}") '
        f"(attr {attr}) {' '.join(pads)})"
    )


# R1 on the top, R2 on the back, H1 a hole kept out of the placement file, C9 not fitted.
PARTS = [
    footprint("R1", "F.Cu", "smd", pad("1", "VCC"), pad("2", "/OUT")),
    footprint("R2", "B.Cu", "smd", pad("1", "/OUT"), pad("2", "GND")),
    footprint("H1", "F.Cu", "exclude_from_pos_files", '(pad "" np_thru_hole circle (at 0 0) (size 3 3))'),
    footprint("C9", "F.Cu", "smd dnp", pad("1", "GND"), pad("2", "")),
]
BOARD = f"""(kicad_pcb (version 20241229) (generator "test")
  (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))
  (net 0 "") (net 1 "VCC") (net 2 "/OUT") (net 3 "GND")
  {" ".join(PARTS)}
  {outline(0, 0, 25, 20)}
)"""


def facts():
    return fabfiles.board_facts(BOARD)


# ------------------------------------------------------------ the board


def test_the_board_names_its_placed_parts_sides_nets_and_copper():
    """2 of the 4 parts are placed: H1 is kept out of the placement file and C9 is not fitted."""
    got = facts()
    assert got["placed"] == {"R1": "top", "R2": "bottom"}
    assert got["not_placed"] == {"H1": "excluded from the placement file", "C9": "not fitted (DNP)"}
    assert got["nets"] == {
        "VCC": ["R1 pad 1"],
        "/OUT": ["R1 pad 2", "R2 pad 1"],
        "GND": ["R2 pad 2", "C9 pad 1"],
    }
    assert got["copper"] == ["F.Cu", "B.Cu"]


def test_the_outline_of_the_board_is_measured_and_closed():
    """The 4 lines run from (0, 0) to (25, 20): 25 by 20 mm, no open end."""
    width, height, open_ends = fabfiles.outline(fabfiles.kicadgen().parse(BOARD))
    assert (width, height, open_ends) == (25.0, 20.0, [])


# ------------------------------------------------------------ the placement file

POS_HEAD = "Ref,Val,Package,PosX,PosY,Rot,Side\n"
R1 = '"R1","10k","R_0603",10.000000,-10.000000,0.000000,top\n'
R2 = '"R2","10k","R_0603",10.000000,-10.000000,180.000000,bottom\n'


def test_a_placement_file_that_agrees_with_the_board_passes():
    assert fabfiles.check_placement(POS_HEAD + R1 + R2, facts(), "placement.csv") == []


def test_a_part_left_out_of_the_placement_file_fails_on_1_line():
    lines = fabfiles.check_placement(POS_HEAD + R1, facts(), "placement.csv")
    assert lines == ["placement.csv: R2 is not in the file; the board places it on the bottom"]


def test_a_part_on_the_wrong_side_fails_on_1_line():
    lines = fabfiles.check_placement(POS_HEAD + R1 + R2.replace("bottom", "top"), facts(), "placement.csv")
    assert lines == ["placement.csv: R2 is on the top; the board places it on the bottom"]


def test_a_part_the_board_keeps_out_fails_on_1_line():
    extra = '"H1","","MountingHole",5.0,-5.0,0.0,top\n'
    lines = fabfiles.check_placement(POS_HEAD + R1 + R2 + extra, facts(), "placement.csv")
    assert lines == ["placement.csv: H1 is in the file; the board says excluded from the placement file"]


def test_a_part_written_2_times_fails_on_1_line():
    lines = fabfiles.check_placement(POS_HEAD + R1 + R1 + R2, facts(), "placement.csv")
    assert lines == ["placement.csv: R1 is in the file 2 times; the board has it once"]


def test_a_placement_file_without_its_columns_fails_on_1_line():
    lines = fabfiles.check_placement("Designator,X,Y\n", facts(), "placement.csv")
    assert lines == ["placement.csv: no Ref and Side columns in the header 'Designator,X,Y'"]


# ------------------------------------------------------------ IPC-2581

LAYERS = (
    '<Layer name="F.Cu" layerFunction="CONDUCTOR" side="TOP"/>'
    '<Layer name="B.Cu" layerFunction="CONDUCTOR" side="BOTTOM"/>'
)
NETS = '<Set net="VCC"/><Set net="/OUT"/><Set net="GND"/>'
COMPONENTS = '<Component refDes="R1" layerRef="F.Cu"/><Component refDes="R2" layerRef="B.Cu"/>'


def ipc(layers: str = LAYERS, nets: str = NETS, components: str = COMPONENTS) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?><IPC-2581 revision="C" xmlns="http://webstds.ipc.org/2581">'
        f"<Ecad><CadData>{layers}<Step name='b'>{nets}{components}</Step></CadData></Ecad></IPC-2581>"
    )


def test_an_ipc2581_file_that_agrees_with_the_board_passes():
    assert fabfiles.check_ipc2581(ipc(), facts(), "b.xml") == []


def test_an_ipc2581_file_that_is_not_xml_fails_on_1_line():
    lines = fabfiles.check_ipc2581(ipc()[:-5], facts(), "b.xml")
    assert len(lines) == 1 and lines[0].startswith("b.xml: not well-formed XML: "), lines


def test_an_ipc2581_file_without_a_net_fails_on_1_line():
    lines = fabfiles.check_ipc2581(ipc(nets=NETS.replace('<Set net="GND"/>', "")), facts(), "b.xml")
    assert lines == ["b.xml: net GND is not named; the board has it on R2 pad 2"]


def test_an_ipc2581_file_without_a_copper_layer_fails_on_1_line():
    lines = fabfiles.check_ipc2581(ipc(layers=LAYERS.split("/>")[0] + "/>"), facts(), "b.xml")
    assert lines == ["b.xml: copper layer B.Cu is not a CONDUCTOR layer of the file"]


def test_an_ipc2581_file_with_a_part_on_the_wrong_side_fails_on_1_line():
    lines = fabfiles.check_ipc2581(ipc(components=COMPONENTS.replace("B.Cu", "F.Cu")), facts(), "b.xml")
    assert lines == ["b.xml: R2 is on the top; the board places it on the bottom"]


def test_an_ipc2581_file_without_a_part_fails_on_1_line():
    lines = fabfiles.check_ipc2581(ipc(components=COMPONENTS.split("/>")[0] + "/>"), facts(), "b.xml")
    assert lines == ["b.xml: R2 is not a Component; the board places it on the bottom"]


# ------------------------------------------------------------ the assembly drawing


def pdf(*refs: str) -> bytes:
    popups = "".join(f'<< /JS (ShM\\([["Reference designator = {r}"],]\\);) >>' for r in refs)
    return f"%PDF-1.5\n{popups}\n%%EOF\n".encode()


def test_an_assembly_page_that_names_each_part_of_its_side_passes():
    assert fabfiles.check_assembly(pdf("R1"), facts(), "top", "assembly-top.pdf") == []
    assert fabfiles.check_assembly(pdf("R2"), facts(), "bottom", "assembly-bottom.pdf") == []


def test_an_assembly_page_without_a_part_fails_on_1_line():
    lines = fabfiles.check_assembly(pdf(), facts(), "bottom", "assembly-bottom.pdf")
    assert lines == ["assembly-bottom.pdf: R2 is not named; the board places it on the bottom"]


def test_an_assembly_file_that_is_no_pdf_fails_on_1_line():
    lines = fabfiles.check_assembly(b"<svg/>", facts(), "top", "assembly-top.pdf")
    assert lines == ["assembly-top.pdf: not a PDF (it starts '<svg/>')"]


# ------------------------------------------------------------ the panel


def panel(copies: dict[str, int], skip: int = -1) -> str:
    """A 2 by 2 panel of the 25 by 20 mm board: 2 x 25 + 2 = 52 mm wide, and 2 x 20 + 2 between the
    boards + 2 x (5 rail + 2 gap) = 56 mm high, as KiKit wrote it for tests/test_fabexport.py."""
    parts = []
    for ref, n in copies.items():
        parts += [
            footprint(ref, "F.Cu", "smd", at=f"{10 + 27 * (i % 2)} {17 + 22 * (i // 2)}") for i in range(n)
        ]
    parts.append(footprint("KiKit_MB_1_1", "F.Cu", "board_only", '(pad "" np_thru_hole circle (at 0 0))'))
    return f"(kicad_pcb (version 20241229) {' '.join(parts)} {outline(122.5, 20, 174.5, 76, skip)})"


def test_a_panel_of_4_boards_with_a_closed_outline_passes():
    lines, info = fabfiles.check_panel(panel({"R1": 4, "R2": 4}), facts(), 2, 2, "panel.kicad_pcb")
    assert lines == []
    assert info == {"boards": 4, "width": 52.0, "height": 56.0}


def test_a_panel_with_a_board_short_fails_on_1_line():
    lines, info = fabfiles.check_panel(panel({"R1": 4, "R2": 3}), facts(), 2, 2, "panel.kicad_pcb")
    assert lines == ["panel.kicad_pcb: R2 is on 3 boards; the preset asks for 2 x 2 = 4"]


def test_a_panel_whose_outline_is_open_fails_on_1_line():
    """The line from (122.5, 76) to (122.5, 20) is left out: its 2 ends are each held by 1 line."""
    lines, _ = fabfiles.check_panel(panel({"R1": 4, "R2": 4}, skip=3), facts(), 2, 2, "panel.kicad_pcb")
    assert lines == ["panel.kicad_pcb: the outline is open at (122.5, 20), (122.5, 76)"]
