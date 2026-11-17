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


def footprint(ref: str, layer: str, attr: str, *pads: str, at: str = "10 10", fab: bool = True) -> str:
    """A footprint; `fab` gives it the `${REFERENCE}` text on its Fab layer that KiCad's libraries hold."""
    text = f'(fp_text user "${{REFERENCE}}" (at 0 0) (layer "{layer[0]}.Fab"))' if fab else ""
    return (
        f'(footprint "Lib:{ref}" (layer "{layer}") (at {at}) (property "Reference" "{ref}") '
        f"(attr {attr}) {text} {' '.join(pads)})"
    )


# R1 on the top, R2 on the back turned 180 degrees, H1 a hole kept out of the placement file, C9 not
# fitted.
PARTS = [
    footprint("R1", "F.Cu", "smd", pad("1", "VCC"), pad("2", "/OUT")),
    footprint("R2", "B.Cu", "smd", pad("1", "/OUT"), pad("2", "GND"), at="10 10 180"),
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


def test_a_part_at_another_place_fails_on_1_line():
    """The board puts R1 at (10, 10) rotated 0; kicad-cli writes that as PosX 10, PosY -10, Rot 0. A row
    at (0, 0) rotated 90 is 10 mm off in x and y and a quarter turn off."""
    moved = '"R1","10k","R_0603",0.000000,0.000000,90.000000,top\n'
    lines = fabfiles.check_placement(POS_HEAD + moved + R2, facts(), "placement.csv")
    assert lines == ["placement.csv: R1 is at (0, 0) rotated 90; the board puts it at (10, -10) rotated 0"]


def test_a_rotation_of_minus_90_is_the_same_as_270():
    """-90 + 360 = 270: the same rotation, written 2 ways."""
    board = BOARD.replace(
        '(at 10 10) (property "Reference" "R1")', '(at 10 10 -90) (property "Reference" "R1")'
    )
    row = '"R1","10k","R_0603",10.000000,-10.000000,270.000000,top\n'
    assert fabfiles.check_placement(POS_HEAD + row + R2, fabfiles.board_facts(board), "p.csv") == []


def test_2_footprints_with_1_reference_are_named_as_the_board_s_fault():
    """R1 on the top and R1 again on the back: the placement file kicad-cli writes holds both rows,
    and the fault is the board's reference, not the file."""
    board = BOARD.replace('(property "Reference" "R2")', '(property "Reference" "R1")')
    got = fabfiles.board_facts(board)
    assert got["count"]["R1"] == 2
    both = R1 + R1.replace("top", "bottom")
    lines = fabfiles.check_placement(POS_HEAD + both, got, "placement.csv")
    assert lines == ["placement.csv: the board has 2 footprints called R1; each part needs its own"]


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


def pdf(*words: str, popups: tuple[str, ...] = (), whole: bool = False) -> bytes:
    """A page as KiCad 10's PDF plotter writes it: a Type 3 stroke font with its ToUnicode map, and
    each glyph drawn at its own place (`q 1 0 0 1 x y cm BT /KiCadStroke0 100 Tf (\\001) Tj ET Q`),
    90 apart within a word and 2000 apart between words; `whole` draws each word in 1 Tj, as the Last
    Hit pages do. `popups` are the property popups KiCad adds per footprint plotted."""
    chars = sorted(set("".join(words)))
    code = {c: i + 1 for i, c in enumerate(chars)}
    cmap = "".join(f"<{code[c]:02X}> <{ord(c):04X}>\n" for c in chars)
    glyphs = []
    for n, word in enumerate(words):
        parts = [word] if whole else list(word)
        for i, part in enumerate(parts):
            octal = "".join(f"\\{code[c]:03o}" for c in part)
            glyphs.append(
                f"q 1.000000 0.000000 -0.000000 1.000000 {1000 + 90 * i} {1000 + 2000 * n} cm "
                f"BT 0 Tr 100 Tz /KiCadStroke0 100 Tf ({octal}) Tj ET\nQ"
            )
    js = "".join(f'<< /JS (ShM\\([["Reference designator = {r}"],]\\);) >>' for r in popups)
    return (
        "%PDF-1.5\n1 0 obj\n<< /Type /Font /Subtype /Type3 /Name /KiCadStroke0 /ToUnicode 2 0 R >>\nendobj\n"
        f"2 0 obj\n<< >>\nstream\n{len(chars)} beginbfchar\n{cmap}endbfchar\nendstream\nendobj\n"
        f"3 0 obj\n<< >>\nstream\n{chr(10).join(glyphs)}\nendstream\nendobj\n{js}\n%%EOF\n"
    ).encode()


def test_the_words_a_page_draws_are_read_glyph_by_glyph_and_word_by_word():
    assert fabfiles.drawn_words(pdf("R1", "10k")) == ["R1", "10k"]
    assert fabfiles.drawn_words(pdf("R1", "10k", whole=True)) == ["R1", "10k"]


def test_an_assembly_page_that_draws_each_part_of_its_side_passes():
    assert fabfiles.check_assembly(pdf("R1", "10k"), facts(), "top", "assembly-top.pdf") == []
    assert fabfiles.check_assembly(pdf("R2"), facts(), "bottom", "assembly-bottom.pdf") == []


def test_an_assembly_page_without_a_part_fails_on_1_line():
    lines = fabfiles.check_assembly(pdf(), facts(), "bottom", "assembly-bottom.pdf")
    assert lines == ["assembly-bottom.pdf: R2 is not drawn; the board places it on the bottom"]


def test_a_popup_is_not_a_drawn_designator():
    """kicad-cli's --exclude-refdes leaves the popups and draws no designator (a run on 2026-11-17)."""
    lines = fabfiles.check_assembly(pdf(popups=("R1",)), facts(), "top", "assembly-top.pdf")
    assert lines == ["assembly-top.pdf: R1 is not drawn; the board places it on the top"]


def test_a_page_that_draws_a_part_of_the_other_side_fails_on_1_line():
    lines = fabfiles.check_assembly(pdf("R1", "R2"), facts(), "top", "assembly-top.pdf")
    assert lines == ["assembly-top.pdf: R2 is drawn; the board places it on the bottom"]


def test_a_page_that_draws_a_part_not_fitted_fails_on_1_line():
    lines = fabfiles.check_assembly(pdf("R1", "C9"), facts(), "top", "assembly-top.pdf")
    assert lines == ["assembly-top.pdf: C9 is drawn; the board says not fitted (DNP)"]


def test_a_part_whose_footprint_draws_no_designator_is_named_with_the_reason():
    """Last Hit v0.16's R24 holds its Reference on B.SilkS, hidden, and no ${REFERENCE} text on B.Fab."""
    board = BOARD.replace(PARTS[0], footprint("R1", "F.Cu", "smd", fab=False))
    got = fabfiles.board_facts(board)
    assert "R1" not in got["fab_ref"] and "R2" in got["fab_ref"]
    lines = fabfiles.check_assembly(pdf(), got, "top", "assembly-top.pdf")
    assert lines == [
        "assembly-top.pdf: R1 is not drawn; the board places it on the top, and its footprint holds no "
        "${REFERENCE} text on a Fab layer"
    ]


def test_an_assembly_file_that_is_no_pdf_fails_on_1_line():
    lines = fabfiles.check_assembly(b"<svg/>", facts(), "top", "assembly-top.pdf")
    assert lines == ["assembly-top.pdf: not a PDF (it starts '<svg/>')"]


# ------------------------------------------------------------ the panel


def panel(copies: dict[str, int], skip: int = -1, edges: str | None = None) -> str:
    """A 2 by 2 panel of the 25 by 20 mm board: 2 x 25 + 2 = 52 mm wide, and 2 x 20 + 2 between the
    boards + 2 x (5 rail + 2 gap) = 56 mm high, as KiKit wrote it for tests/test_fabexport.py."""
    parts = []
    for ref, n in copies.items():
        parts += [
            footprint(ref, "F.Cu", "smd", at=f"{10 + 27 * (i % 2)} {17 + 22 * (i // 2)}") for i in range(n)
        ]
    parts.append(footprint("KiKit_MB_1_1", "F.Cu", "board_only", '(pad "" np_thru_hole circle (at 0 0))'))
    edges = outline(122.5, 20, 174.5, 76, skip) if edges is None else edges
    return f"(kicad_pcb (version 20241229) {' '.join(parts)} {edges})"


def rounded(x0: float, y0: float, x1: float, y1: float, skip: int = -1) -> str:
    """A box with corners rounded by 1 mm: 4 lines and 4 arcs (start, mid, end); `skip` leaves out
    arc number skip."""
    lines = [
        ((x0 + 1, y0), (x1 - 1, y0)),
        ((x1, y0 + 1), (x1, y1 - 1)),
        ((x1 - 1, y1), (x0 + 1, y1)),
        ((x0, y1 - 1), (x0, y0 + 1)),
    ]
    out = [f'(gr_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (layer "Edge.Cuts"))' for a, b in lines]
    for i in range(4):
        if i == skip:
            continue
        a, b = lines[i][1], lines[(i + 1) % 4][0]
        out.append(
            f'(gr_arc (start {a[0]} {a[1]}) (mid {a[0]} {b[1]}) (end {b[0]} {b[1]}) (layer "Edge.Cuts"))'
        )
    return "\n".join(out)


def test_a_panel_whose_outline_has_rounded_corners_is_closed():
    """Each line ends where an arc starts: no open end. The box is still 174.5 - 122.5 = 52 by
    76 - 20 = 56 mm."""
    lines, info = fabfiles.check_panel(
        panel({"R1": 4, "R2": 4}, edges=rounded(122.5, 20, 174.5, 76)), facts(), 2, 2, "panel.kicad_pcb"
    )
    assert lines == [] and (info["width"], info["height"]) == (52.0, 56.0)


def test_a_panel_whose_rounded_outline_lacks_an_arc_is_open():
    """Arc 0 would run from (173.5, 20) to (174.5, 21): those 2 ends are each held by 1 line."""
    edges = rounded(122.5, 20, 174.5, 76, skip=0)
    lines, _ = fabfiles.check_panel(panel({"R1": 4, "R2": 4}, edges=edges), facts(), 2, 2, "panel.kicad_pcb")
    assert lines == ["panel.kicad_pcb: the outline is open at (173.5, 20), (174.5, 21)"]


def test_a_panel_whose_outline_is_1_rectangle_passes():
    edges = '(gr_rect (start 122.5 20) (end 174.5 76) (layer "Edge.Cuts"))'
    lines, info = fabfiles.check_panel(
        panel({"R1": 4, "R2": 4}, edges=edges), facts(), 2, 2, "panel.kicad_pcb"
    )
    assert lines == [] and (info["width"], info["height"]) == (52.0, 56.0)


def test_a_panel_without_an_outline_fails_on_1_line():
    lines, _ = fabfiles.check_panel(panel({"R1": 4, "R2": 4}, edges=""), facts(), 2, 2, "panel.kicad_pcb")
    assert lines == ["panel.kicad_pcb: no outline on Edge.Cuts (its box is 0 x 0 mm)"]


def test_a_panel_smaller_than_its_boards_fails_on_1_line():
    """2 x 2 boards of 25 x 20 mm need at least 2 x 25 = 50 by 2 x 20 = 40 mm, either way round; a
    panel of 40 x 30 mm holds neither."""
    edges = '(gr_rect (start 0 0) (end 40 30) (layer "Edge.Cuts"))'
    lines, _ = fabfiles.check_panel(panel({"R1": 4, "R2": 4}, edges=edges), facts(), 2, 2, "panel.kicad_pcb")
    assert lines == [
        "panel.kicad_pcb: the panel is 40 x 30 mm; 2 x 2 boards of 25 x 20 mm need at least 50 x 40 mm"
    ]


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
