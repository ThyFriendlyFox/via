"""The legend check and the designator placer of tools/legend.py, on boards written in each test.

A text's box is worked out by hand as tools/legend.py measures it, for KiCad's stroke font:

    width  = characters x 1.34 / 1.27 x the glyph width + the stroke   (kicadgen.TEXT_ADVANCE, 1.34 mm a
             character of 1.27 mm text, read off a plotted "R1")
    height = the glyph height + the stroke

so 2 characters of 1.0 mm text stroked 0.15 mm are 2 x 1.055118 + 0.15 = 2.260236 mm wide and 1.15 mm
high, and 1 more character adds 1.055118 mm. A footprint's courtyard and pads are written in its own
frame; at a rotation of 0 a point (px, py) of a footprint at (fx, fy) is (fx + px, fy + py) on the board.

The board names no fab unless a test says so: it is held to the least of the fabs in rules/ for each
size, PCBWay's 0.8 mm high (rules/pcbway-standard.kicad_dru: "Minimum Character Height (Legend) 0.8mm")
and OSH Park's 0.0762 mm stroke (rules/oshpark-2layer.kicad_dru: "Silkscreen minimum line width ... 3 mil
(0.0762mm) (short lines, text, graphics)").
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import kicadgen  # noqa: E402
import legend  # noqa: E402

PACK = legend.read_pack()


def txt(s, x, y, size=1.0, thick=0.15, layer="F.SilkS", angle=0, mirror=False, face=""):
    font = f'(face "{face}") ' if face else ""
    just = " (justify mirror)" if mirror else ""
    return (
        f'(gr_text "{s}" (at {x} {y} {angle}) (layer "{layer}") '
        f"(effects (font {font}(size {size} {size}) (thickness {thick})){just}))"
    )


def fp(ref, x, y, crt, pads=(), ref_at=(0, -2, 0), size=1.0, thick=0.15, side="F", rot=0):
    """A footprint with a courtyard rectangle `crt` (x1, y1, x2, y2) and pads (px, py, w, h, kind)."""
    rot_s = f" {rot}" if rot else ""
    pad_s = ""
    for i, (px, py, w, h, kind) in enumerate(pads, 1):
        layers = f'"{side}.Cu" "{side}.Mask"' if kind == "smd" else '"*.Cu" "*.Mask"'
        drill = " (drill 0.8)" if kind != "smd" else ""
        pad_s += f'(pad "{i}" {kind} rect (at {px} {py}) (size {w} {h}){drill} (layers {layers}))'
    mirror = " (justify mirror)" if side == "B" else ""
    return (
        f'(footprint "Test:{ref}" (layer "{side}.Cu") (at {x} {y}{rot_s}) '
        f'(property "Reference" "{ref}" (at {ref_at[0]} {ref_at[1]} {ref_at[2]}) (layer "{side}.SilkS") '
        f"(effects (font (size {size} {size}) (thickness {thick})){mirror})) "
        f'(property "Value" "V" (at 0 0 0) (layer "{side}.Fab") '
        "(effects (font (size 1 1) (thickness 0.15)))) "
        f'(fp_rect (start {crt[0]} {crt[1]}) (end {crt[2]} {crt[3]}) (layer "{side}.CrtYd")) '
        f"{pad_s})"
    )


def board(*items, outline=(100, 100, 140, 120)):
    x1, y1, x2, y2 = outline
    return (
        '(kicad_pcb (version 20241229) (generator "test") (setup (pad_to_mask_clearance 0)) '
        + " ".join(items)
        + f' (gr_rect (start {x1} {y1}) (end {x2} {y2}) (layer "Edge.Cuts")))'
    )


def judge(text, fab=None):
    return legend.judge(legend.read_board(kicadgen.parse(text)), legend.limits(fab), PACK)


def fails(findings):
    return [(f.rule, f.what) for f in findings if f.status == "fail"]


# ---------------------------------------------------------------- the limits


def test_no_fab_is_held_to_the_least_of_the_known_fabs():
    """JLCPCB 1.0 mm and 0.15 mm, PCBWay 0.8 mm and 0.15 mm, OSH Park 0.0762 mm stroke and no height,
    Sierra 0.127 mm stroke and no height: the least are 0.8 mm high (PCBWay) and 0.0762 mm (OSH Park)."""
    lim = legend.limits(None)
    assert (lim.height, lim.stroke) == (0.8, 0.0762)
    assert "no fab named" in lim.label and "pcbway-standard" in lim.label and "oshpark-2layer" in lim.label
    assert lim.height_source.startswith("pcbway-standard: https://www.pcbway.com/capabilities.html")


def test_a_named_fab_gives_its_own_least_and_its_page():
    lim = legend.limits("pcbway-standard")
    assert (lim.height, lim.stroke) == (0.8, 0.15)
    assert "https://www.pcbway.com/capabilities.html" in lim.height_source


def test_a_fab_that_names_no_height_leaves_the_height_not_judged():
    """OSH Park's page names a 3 mil stroke (0.0762 mm) for text and no height."""
    lim = legend.limits("oshpark-2layer")
    assert lim.height is None and lim.stroke == 0.0762
    found = judge(board(txt("AB", 120, 110, size=0.5, thick=0.1)), "oshpark-2layer")
    assert fails(found) == []
    assert [f.rule for f in found if f.status == "not judged"] == ["size"]


# ---------------------------------------------------------------- the fixture of 3 faults


FIXTURE = ROOT / "tests" / "boards" / "fail-legend" / "legend.kicad_pcb"


def test_the_fixture_fails_each_fault_on_its_own_rule_and_on_no_other():
    """tests/boards/fail-legend: 3 faults, 1 rule each, and R1 that keeps every rule.

    overlap  "AB" at (110, 105): x 110 -+ 1.130118, y 105 -+ 0.575: 108.869882..111.130118, 104.425..105.575
             "CD" at (111, 105.5): 109.869882..112.130118, 104.925..106.075
             they share 111.130118 - 109.869882 = 1.260236 mm by 105.575 - 104.925 = 0.65 mm
    size     "EF" at (130, 105), 0.6 mm high: under 0.8 mm; its stroke 0.15 mm keeps 0.0762 mm
    hidden   U1 at (115, 113), courtyard -3..3 both ways: 112..118, 110..116; its designator at its centre,
             112.869882..117.130118 by 112.425..113.575, inside it. Its pads at x = -+2.5 (0.6 mm wide)
             reach in to 115 -+ 2.2: 112.8 and 117.2, clear of the box; so no overlap with an opening.
    R1       at (130, 113), courtyard 128.5..131.5 by 112.25..113.75; designator at (130, 111.5):
             128.869882..131.130118 by 110.925..112.075, 112.25 - 112.075 = 0.175 mm off its courtyard,
             under the 2.0 mm reach; U1's courtyard is 128.869882 - 118 = 10.87 mm away.
    """
    found = judge(FIXTURE.read_text(encoding="utf-8"))
    assert sorted(fails(found)) == sorted(
        [("overlap", 'text "AB"'), ("size", 'text "EF"'), ("hidden", "designator U1")]
    )
    assert [f for f in found if f.status != "fail"] == []
    over = next(f for f in found if f.rule == "overlap")
    assert 'text "CD"' in over.line and "1.26 x 0.65 mm" in over.line
    size = next(f for f in found if f.rule == "size")
    assert "height 0.6 mm" in size.line and "least 0.8 mm" in size.line
    assert "https://www.pcbway.com/capabilities.html" in size.line


# ---------------------------------------------------------------- overlap with what else is printed


def test_text_on_a_pad_opening_fails_overlap():
    """R1 at (120, 110), 1 smd pad 1 x 1 at (0, 0): the opening is 119.5..120.5 by 109.5..110.5. "X" at
    (120, 108.2): 1.055118 + 0.15 = 1.205118 wide, 119.397441..120.602559 by 107.625..108.775: clear.
    At (120, 109.2): 108.625..109.775 enters the opening by 0.275 mm."""
    pad = [(0, 0, 1, 1, "smd")]
    clear = board(fp("R1", 120, 110, (-3, -1, 3, 1), pad, ref_at=(0, -1.6, 0)), txt("X", 125, 103))
    assert fails(judge(clear)) == []
    hit = board(fp("R1", 120, 110, (-3, -1, 3, 1), pad, ref_at=(0, -1.6, 0)), txt("X", 120, 109.2))
    lines = [f.line for f in judge(hit) if f.status == "fail"]
    assert ("overlap", 'text "X"') in fails(judge(hit))
    assert any("solder mask opening of R1 pad 1" in line for line in lines)


def test_text_on_a_hole_fails_overlap():
    """A through pad of J1 at (120, 110), 2 x 2 mm with a 0.8 mm hole: the hole is 119.6..120.4 both ways.
    "X" at (120, 110): 119.397441..120.602559 by 109.425..110.575 covers it, and the opening too."""
    thru = [(0, 0, 2, 2, "thru_hole")]
    hit = board(fp("J1", 120, 110, (-3, -3, 3, 3), thru, ref_at=(0, -4, 0)), txt("X", 120, 110))
    lines = [f.line for f in judge(hit) if f.status == "fail"]
    assert any("hole of J1 pad 1" in line for line in lines)


def test_text_over_the_board_edge_fails_overlap():
    """ "AB" at (101, 110): 99.869882..102.130118, over the edge at x = 100 by 0.130118 mm."""
    assert fails(judge(board(txt("AB", 101, 110)))) == [("overlap", 'text "AB"')]
    line = judge(board(txt("AB", 101, 110)))[0].line
    assert "board edge" in line
    assert fails(judge(board(txt("AB", 101.2, 110)))) == []  # 100.069882: inside by 0.07 mm


def test_a_turned_text_is_measured_turned():
    """ "ABC" turned 90 degrees at (120, 101.7): 3.315354 mm along y, 101.7 -+ 1.657677 = 100.042..103.358,
    inside; at (120, 101.5) it reaches 99.842, over the edge."""
    assert fails(judge(board(txt("ABC", 120, 101.7, angle=90)))) == []
    assert fails(judge(board(txt("ABC", 120, 101.5, angle=90)))) == [("overlap", 'text "ABC"')]


# ---------------------------------------------------------------- designators


def test_a_designator_under_another_part_fails_hidden():
    """U1's courtyard 112..118 by 110..116 at (115, 113). R1 at (120, 113) has its designator at local
    (-4, 0): (116, 113), 114.869882..117.130118, inside U1's courtyard."""
    b = board(
        fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, -4, 0)),
        fp("R1", 120, 113, (-1, -0.5, 1, 0.5), ref_at=(-4, 0, 0)),
    )
    got = fails(judge(b))
    assert ("hidden", "designator R1") in got
    assert any("courtyard of U1" in f.line for f in judge(b) if f.rule == "hidden")


def test_a_designator_nearer_another_part_fails_nearest():
    """R1 at (110, 110), courtyard 109..111 by 109.5..110.5; R2 at (110, 113), 112.5..113.5.
    R1's designator at local (0, 1.6), (110, 111.6): box 111.025..112.175; 111.025 - 110.5 = 0.525 mm
    from R1 and 112.5 - 112.175 = 0.325 mm from R2: nearer R2. R2's designator, local (0, 1.6) at
    (110, 114.6), is 0.525 from R2 and far from R1."""
    b = board(
        fp("R1", 110, 110, (-1, -0.5, 1, 0.5), ref_at=(0, 1.6, 0)),
        fp("R2", 110, 113, (-1, -0.5, 1, 0.5), ref_at=(0, 1.6, 0)),
    )
    assert fails(judge(b)) == [("nearest", "designator R1")]
    line = judge(b)[0].line
    assert "0.325 mm from R2" in line and "0.525 mm from R1" in line


def test_a_designator_too_far_from_its_part_fails_nearest():
    """R1's courtyard bottom at 110.5; a designator at local (0, 3.2), (110, 113.2): box top 112.625,
    2.125 mm off, over the 2.0 mm reach of rules/legend.json; at (0, 3.0) it is 1.925 mm off."""
    far = board(fp("R1", 110, 110, (-1, -0.5, 1, 0.5), ref_at=(0, 3.2, 0)))
    assert fails(judge(far)) == [("nearest", "designator R1")]
    near = board(fp("R1", 110, 110, (-1, -0.5, 1, 0.5), ref_at=(0, 3.0, 0)))
    assert fails(judge(near)) == []


# ---------------------------------------------------------------- directions and mirroring


def test_three_directions_on_one_side_fail_direction():
    """3 texts at 0, 90 and 45 degrees on F.SilkS: 3 directions, 1 line for the side. A text at 180
    degrees reads in the same direction as one at 0 (KiCad keeps it upright): 0, 90, 180 is 2."""
    three = board(txt("A", 110, 110), txt("B", 120, 110, angle=90), txt("C", 130, 110, angle=45))
    assert fails(judge(three)) == [("direction", "F.SilkS")]
    two = board(txt("A", 110, 110), txt("B", 120, 110, angle=90), txt("C", 130, 110, angle=180))
    assert fails(judge(two)) == []


def test_back_text_that_is_not_mirrored_fails_direction():
    good = board(txt("A", 110, 110, layer="B.SilkS", mirror=True))
    bad = board(txt("A", 110, 110, layer="B.SilkS"))
    assert fails(judge(good)) == []
    assert fails(judge(bad)) == [("direction", 'text "A"')]


# ---------------------------------------------------------------- what is not judged


def test_a_text_in_a_font_the_tool_cannot_measure_is_not_judged():
    b = board(txt("AB", 110, 110, face="Arial"), txt("CD", 110.5, 110))
    found = judge(b)
    assert [(f.rule, f.what) for f in found if f.status == "not judged"] == [("font", 'text "AB"')]
    assert (
        fails(found) == []
    )  # "CD" overlaps "AB", which is not measured, and is not taken as clear: see the line
    assert "Arial" in found[0].line


def test_hidden_and_fab_layer_text_is_not_printed_and_not_judged():
    b = board(txt("AB", 101, 110, layer="F.Fab"))
    assert judge(b) == []


# ---------------------------------------------------------------- the placer


def place(text, fixed=(), fab=None):
    root = kicadgen.parse(text)
    lines = legend.place(root, legend.limits(fab), PACK, fixed=set(fixed))
    return root, lines


def test_the_placer_moves_a_hidden_designator_above_its_part():
    """U1 courtyard 112..118 by 110..116 at (115, 113), designator at its centre. The first place is
    above: 2 characters 2.260236 x 1.15 mm, its bottom 0.15 mm (the pack's gap) over 110: y = 110 - 0.15
    - 0.575 = 109.275, x = 115; in U1's frame (0, -3.725)."""
    root, lines = place(board(fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, 0, 0))))
    assert lines == []
    assert fails(legend.judge(legend.read_board(root), legend.limits(None), PACK)) == []
    ref = next(p for p in kicadgen.children(kicadgen.children(root, "footprint")[0], "property"))
    assert kicadgen.atoms(kicadgen.child(ref, "at")) == ["0", "-3.725", "0"]


def test_the_placer_turns_a_designator_where_upright_does_not_fit():
    """U1 courtyard 101..109 by 100.5..119.5 at (105, 110) on a board 100..140: above and below are off
    the board (100.5 - 0.15 - 1.15 < 100), right is the first place that fits, upright:
    x = 109 + 0.15 + 1.130118 = 110.280118, y = 110."""
    root, _ = place(board(fp("U1", 105, 110, (-4, -9.5, 4, 9.5), ref_at=(0, 0, 0))))
    ref = kicadgen.children(kicadgen.children(root, "footprint")[0], "property")[0]
    assert kicadgen.atoms(kicadgen.child(ref, "at")) == ["5.280118", "0", "0"]


def test_the_placer_leaves_a_fixed_designator_and_the_check_still_judges_it():
    text = board(fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, 0, 0)))
    root, lines = place(text, fixed={"U1"})
    assert kicadgen.dumps(root) == kicadgen.dumps(kicadgen.parse(text))
    assert fails(legend.judge(legend.read_board(root), legend.limits(None), PACK)) == [
        ("hidden", "designator U1")
    ]


def test_where_nothing_fits_the_designator_goes_to_the_fab_layer_with_a_line():
    """U1's courtyard fills the board but 0.5 mm each side: 100.5..139.5 by 100.5..119.5. No place
    around it is on the board, at any size down to 0.8 mm."""
    root, lines = place(board(fp("U1", 120, 110, (-19.5, -9.5, 19.5, 9.5), ref_at=(0, 0, 0))))
    assert lines == ["legend: U1 has no place on F.SilkS; its designator is kept on F.Fab"]
    ref = kicadgen.children(kicadgen.children(root, "footprint")[0], "property")[0]
    assert kicadgen.atoms(kicadgen.child(ref, "layer")) == ["F.Fab"]
    assert fails(legend.judge(legend.read_board(root), legend.limits(None), PACK)) == []


def test_the_placer_makes_a_designator_smaller_before_it_gives_up():
    """PCBWay's least is 0.8 mm high and 0.15 mm stroke. U1 at (120, 110), courtyard 100.6..139.4 by
    101.2..119.5: 1.2 mm above it, 0.6 mm left and right, 0.5 mm below. 1.0 mm text needs the gap and
    its box, 0.15 + 1.15 = 1.3 mm: no place. At 0.9 mm the stroke stays at the least, 0.15 mm (0.15 x
    0.9 = 0.135 is under it): 0.15 + 0.9 + 0.15 = 1.2 mm, which touches the edge and is not over it."""
    root, lines = place(
        board(fp("U1", 120, 110, (-19.4, -8.8, 19.4, 9.5), ref_at=(0, 0, 0))), fab="pcbway-standard"
    )
    ref = kicadgen.children(kicadgen.children(root, "footprint")[0], "property")[0]
    font = kicadgen.child(kicadgen.child(ref, "effects"), "font")
    assert kicadgen.atoms(kicadgen.child(font, "size")) == ["0.9", "0.9"]
    assert kicadgen.atoms(kicadgen.child(font, "thickness")) == ["0.15"]


def dense(placed: bool):
    sys.path.insert(0, str(ROOT / "tests" / "boards"))
    import legend_dense

    return legend_dense.build(place=placed)


def test_art_in_3_directions_does_not_keep_a_designator_off_the_board():
    """The design's own texts read at 0, 45 and 90 degrees: their own failure. The designator placed
    upright adds no direction, and goes above U1 as in the first placer test: local (0, -3.725)."""
    art = (txt("A", 130, 105), txt("B", 135, 105, angle=45), txt("C", 130, 115, angle=90))
    root, lines = place(board(fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, 0, 0)), *art))
    assert lines == []
    ref = kicadgen.children(kicadgen.children(root, "footprint")[0], "property")[0]
    assert kicadgen.atoms(kicadgen.child(ref, "at")) == ["0", "-3.725", "0"]


def test_show_puts_a_hidden_designator_back_on_its_side():
    text = board(fp("R5", 120, 110, (-1, -0.5, 1, 0.5), side="B")).replace(
        '(layer "B.SilkS")', '(layer "B.Fab") (hide yes)', 1
    )
    root = kicadgen.parse(text)
    assert legend.read_board(root).texts == []
    assert legend.show_designators(root) == 1
    (t,) = legend.read_board(root).texts
    assert (t.what, t.layer, t.mirrored) == ("designator R5", "B.SilkS", True)


def test_two_runs_of_the_placer_give_the_same_board():
    a, b = dense(True).board(), dense(True).board()
    assert a == b
    committed = ROOT / "tests" / "boards" / "pass-legend-dense" / "dense.kicad_pcb"
    assert committed.read_text(encoding="utf-8") == a


def test_the_dense_fixture_fails_as_the_library_places_it_and_holds_once_placed():
    raw = judge(dense(False).board())
    assert len(fails(raw)) > 0
    design = dense(True)
    placed = judge(design.board())
    assert [f.line for f in placed] == []


@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
def test_the_drc_gate_fails_the_fixture_on_its_3_rules_and_no_other(tmp_path):
    """`workcenter drc` on fail-legend: red, the 3 lines of the check above, and every legend line, KiCad's
    own included, on 1 of the 3 rules."""
    board = tmp_path / "fail-legend"
    shutil.copytree(ROOT / "tests" / "boards" / "fail-legend", board)
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "workcenter"),
            "--json",
            "drc",
            str(board),
            "--out",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    (result,) = json.loads(proc.stdout)
    lines = result["details"]["failures"]
    assert any(line.startswith('legend overlap: text "AB"') for line in lines), lines
    assert any(line.startswith('legend size: text "EF"') for line in lines), lines
    assert any(line.startswith("legend hidden: designator U1") for line in lines), lines
    rules = {line.split(":")[0] for line in lines}
    assert rules <= {"legend overlap", "legend size", "legend hidden"}, lines
    assert "legend (no fab named" in result["summary"]


@pytest.mark.parametrize("fab", ["jlcpcb-2layer", "pcbway-standard", "oshpark-2layer", "sierra-circuits-web"])
def test_each_fab_names_its_page(fab):
    lim = legend.limits(fab)
    assert lim.stroke_source.startswith(f"{fab}: https://")
