"""The legend check and the designator placer of tools/legend.py, on boards written in each test.

A text's box is worked out by hand as tools/legend.py measures it, for KiCad's stroke font:

    width  = characters x 1.34 / 1.27 x the glyph width + the stroke   (kicadgen.TEXT_ADVANCE, 1.34 mm a
             character of 1.27 mm text, read off a plotted "R1")
    height = the glyph height + the stroke

so 2 characters of 1.0 mm text stroked 0.15 mm are 2 x 1.055118 + 0.15 = 2.260236 mm wide and 1.15 mm
high, and 1 more character adds 1.055118 mm. A footprint's courtyard and pads are written in its own
frame; at a rotation of 0 a point (px, py) of a footprint at (fx, fy) is (fx + px, fy + py) on the board.

The board names no fab unless a test says so: it is held to the least of the fabs in rules/ for each
size, PCBWay's 0.8 mm high (rules/pcbway-standard.kicad_dru: "Minimum Character Height (Legend) - 0.8mm")
and OSH Park's 0.0762 mm stroke (rules/oshpark-2layer.kicad_dru: "Silkscreen minimum line width ... 3 mil
(0.0762mm) (short lines, text, graphics)").
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

CITES = {
    "pcbway-capabilities": "Minimum Character Height (Legend), as rules/pcbway-standard.kicad_dru quotes it",
    "oshpark-two-layer": "Silkscreen minimum line width, as rules/oshpark-2layer.kicad_dru quotes it",
}

import kicadgen  # noqa: E402
import legend  # noqa: E402

PACK = legend.read_pack()


def txt(s, x, y, size=1.0, thick=0.15, layer="F.SilkS", angle=0, mirror=False, face="", just=""):
    """A gr_text; `thick=None` writes no (thickness); `just` adds words to its (justify)."""
    font = f'(face "{face}") ' if face else ""
    words = " ".join(w for w in (just, "mirror" if mirror else "") if w)
    justify = f" (justify {words})" if words else ""
    stroke = f" (thickness {thick})" if thick is not None else ""
    return (
        f'(gr_text "{s}" (at {x} {y} {angle}) (layer "{layer}") '
        f"(effects (font {font}(size {size} {size}){stroke}){justify}))"
    )


def fp(ref, x, y, crt, pads=(), ref_at=(0, -2, 0), size=1.0, thick=0.15, side="F", rot=0, just="", extra=""):
    """A footprint with a courtyard rectangle `crt` (x1, y1, x2, y2) or none (`crt=None`), pads (px, py, w,
    h, kind), its designator's (justify) words `just`, and `extra` S-expressions written inside it."""
    rot_s = f" {rot}" if rot else ""
    pad_s = ""
    for i, (px, py, w, h, kind) in enumerate(pads, 1):
        layers = f'"{side}.Cu" "{side}.Mask"' if kind == "smd" else '"*.Cu" "*.Mask"'
        drill = " (drill 0.8)" if kind != "smd" else ""
        pad_s += f'(pad "{i}" {kind} rect (at {px} {py}) (size {w} {h}){drill} (layers {layers}))'
    words = " ".join(w for w in (just, "mirror" if side == "B" else "") if w)
    justify = f" (justify {words})" if words else ""
    court = (
        f'(fp_rect (start {crt[0]} {crt[1]}) (end {crt[2]} {crt[3]}) (layer "{side}.CrtYd")) ' if crt else ""
    )
    return (
        f'(footprint "Test:{ref}" (layer "{side}.Cu") (at {x} {y}{rot_s}) '
        f'(property "Reference" "{ref}" (at {ref_at[0]} {ref_at[1]} {ref_at[2]}) (layer "{side}.SilkS") '
        f"(effects (font (size {size} {size}) (thickness {thick})){justify})) "
        f'(property "Value" "V" (at 0 0 0) (layer "{side}.Fab") '
        "(effects (font (size 1 1) (thickness 0.15)))) "
        f"{court}{pad_s}{extra})"
    )


def board(*items, outline=(100, 100, 140, 120)):
    """A board with `items`; its edge the rectangle `outline`, or none with `outline=None` (an item draws
    it)."""
    edge = ""
    if outline:
        x1, y1, x2, y2 = outline
        edge = f' (gr_rect (start {x1} {y1}) (end {x2} {y2}) (layer "Edge.Cuts"))'
    return (
        '(kicad_pcb (version 20241229) (generator "test") (setup (pad_to_mask_clearance 0)) '
        + " ".join(items)
        + edge
        + ")"
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
    """3 texts at 0, 90 and 45 degrees on F.SilkS: 3 directions, 1 line for the side. A gr_text at 180
    degrees is printed upside down by KiCad 10 (a plot of an "L" at 180 has its foot at the top), so it is a
    direction of its own: 0, 90, 180 is 3 as well. 0 and 360 are 1."""
    three = board(txt("A", 110, 110), txt("B", 120, 110, angle=90), txt("C", 130, 110, angle=45))
    assert fails(judge(three)) == [("direction", "F.SilkS")]
    upside = board(txt("A", 110, 110), txt("B", 120, 110, angle=90), txt("C", 130, 110, angle=180))
    assert fails(judge(upside)) == [("direction", "F.SilkS")]
    assert "180 degrees: 1" in next(f.line for f in judge(upside) if f.rule == "direction")
    same = board(txt("A", 110, 110), txt("B", 120, 110, angle=90), txt("C", 130, 110, angle=360))
    assert fails(judge(same)) == []


def test_a_footprint_text_at_180_is_drawn_upright():
    """pcbnew 10 read a footprint's designator written at 180 degrees (footprints at 0 and at 180) as keep
    upright, drawn at 0 (scratch probe, 2026-11-17). So U1's designator at 180, with texts at 0 and 90,
    makes 2 directions, not 3. U1's courtyard 112..118 by 110..116, its designator at local (0, -3.725):
    0.15 mm above it, as the placer would put it."""
    art = (txt("A", 130, 105), txt("B", 135, 105, angle=90))
    b = board(fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, -3.725, 180)), *art)
    assert fails(judge(b)) == []


def test_a_footprint_text_kicad_does_not_keep_upright_reads_at_180():
    """pcbnew 10 saved a designator whose keep upright it had turned off as (unlocked yes), and read it back
    drawn at 180 (scratch probe, 2026-11-18). So U1's designator at 180 with (unlocked yes), with texts at 0
    and 90, makes 3 directions: 0, 90 and 180, over the 2 of rules/legend.json."""
    art = (txt("A", 130, 105), txt("B", 135, 105, angle=90))
    upright = fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, -3.725, 180))
    unlocked = upright.replace("(at 0 -3.725 180)", "(at 0 -3.725 180) (unlocked yes)")
    assert unlocked != upright
    found = judge(board(unlocked, *art))
    assert fails(found) == [("direction", "F.SilkS")]
    assert "180 degrees: 1" in found[0].line


def test_an_upright_text_justified_left_at_180_runs_right_of_its_anchor():
    """KiCad keeps a footprint's text upright: written at 180 and justified left, it is drawn at 0, justified
    left, so it runs right of its anchor (kicad-cli 10.0.8 Gerber of F.SilkS, the second review's
    h5-upright-justify: U1's designator anchored at (130, 109.2) inked 130.262..131.983 by 108.58..109.73).
    U1 at (130, 113) turned 180, its designator at local (0, 3.8, 180): (130, 109.2) on the board; its box
    130..132.260236 by 108.625..109.775. U2's courtyard 131..135 by 105..109: the box is on it by
    132.260236 - 131 = 1.260236 by 109 - 108.625 = 0.375 mm."""
    u1 = fp("U1", 130, 113, (-3, -3, 3, 3), ref_at=(0, 3.8, 180), rot=180, just="left")
    u2 = fp("U2", 133, 107, (-2, -2, 2, 2), ref_at=(0, -2.8, 0))
    found = judge(board(u1, u2))
    hidden = [f.line for f in found if f.rule == "hidden"]
    assert hidden == [
        "legend hidden: designator U1 at (130, 109.2) mm on F.SilkS: under the courtyard of U2 by 1.26 x "
        "0.375 mm: hidden once assembled (rules/legend.json)"
    ]
    t = legend.read_board(kicadgen.parse(board(u1))).texts[0]
    assert t.box == pytest.approx((130, 108.625, 132.260236, 109.775))
    unlocked = u1.replace("(at 0 3.8 180)", "(at 0 3.8 180) (unlocked yes)")
    t = legend.read_board(kicadgen.parse(board(unlocked))).texts[0]
    assert t.box == pytest.approx((127.739764, 108.625, 130, 109.775))


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


R_PADS = ((-0.8, 0, 0.8, 0.95, "smd"), (0.8, 0, 0.8, 0.95, "smd"))


def field(name, value, at=(0, 0), layer="F.SilkS", size=0.5, thick=0.05, hide=""):
    hidden = " (hide yes)" if hide else ""
    return (
        f'(property "{name}" "{value}" (at {at[0]} {at[1]} 0) (layer "{layer}"){hidden} '
        f"(effects (font (size {size} {size}) (thickness {thick}))))"
    )


def test_a_parts_own_field_on_the_silkscreen_is_judged():
    """The second review's h1-field: R1 at (120, 110) shows its field MPN "RC0603" at its centre, 0.5 mm
    high stroked 0.05 mm. Its box 6 x 1.055118 x 0.5 + 0.05 = 3.215354 by 0.55 mm: 118.392323..121.607677
    by 109.725..110.275. Under 0.8 mm high and 0.0762 mm stroke, and on both pads' openings (118.8..119.6
    and 120.4..121.2 by 109.525..110.475): 0.8 x 0.55 mm each. Hidden, or on F.Fab, it is not printed."""
    shown = fp("R1", 120, 110, (-1.5, -0.8, 1.5, 0.8), R_PADS, extra=field("MPN", "RC0603"))
    found = judge(board(shown))
    what = 'field MPN of R1 "RC0603"'
    assert fails(found) == [("size", what), ("size", what), ("overlap", what), ("overlap", what)]
    assert "on the solder mask opening of R1 pad 1 by 0.8 x 0.55 mm" in found[2].line
    for unseen in (field("MPN", "RC0603", hide="yes"), field("MPN", "RC0603", layer="F.Fab")):
        assert judge(board(fp("R1", 120, 110, (-1.5, -0.8, 1.5, 0.8), R_PADS, extra=unseen))) == []


DIMENSION = (
    '(dimension (type aligned) (layer "{layer}") (pts (xy 95 110) (xy 105 110)) (height 0) '
    '(gr_text "10.00 mm" (at 100 110 0) (layer "{layer}") (effects (font (size 0.5 0.5) (thickness 0.05)))) '
    "(format (units 3) (units_format 1) (precision 2)) (style (thickness 0.1) (arrow_length 1)))"
)


def test_a_dimension_table_or_barcode_on_the_silkscreen_is_not_judged_by_name():
    """A dimension prints its number, a table its cells and a barcode its bars; the tool measures none of
    them, so each is printed as not judged, with where it is. On a layer that is not printed, nothing."""
    table = (
        '(table (column_count 1) (layer "F.SilkS") (cells (table_cell "Rev A" (start 110 105) (end 115 107) '
        '(layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))))'
    )
    barcode = '(barcode (at 130 105 0) (layer "F.SilkS") (size 3 3) (text "SN1") (type qr))'
    # A footprint's own dimension is written in the footprint's frame: (-5, 10) of U1 at (115, 113).
    own = DIMENSION.format(layer="F.SilkS").replace("(xy 95 110)", "(xy -5 10)")
    in_fp = fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, -3.725, 0), extra=own)
    found = judge(board(DIMENSION.format(layer="F.SilkS"), table, barcode, in_fp))
    assert fails(found) == []
    assert [f.line for f in found] == [
        'legend not judged: dimension "10.00 mm" at (95, 110) mm on F.SilkS: the tool does not measure what '
        "KiCad draws for it",
        'legend not judged: table "Rev A" at (110, 105) mm on F.SilkS: the tool does not measure what KiCad '
        "draws for it",
        'legend not judged: barcode "SN1" at (130, 105) mm on F.SilkS: the tool does not measure what KiCad '
        "draws for it",
        'legend not judged: dimension "10.00 mm" of U1 at (110, 123) mm on F.SilkS: the tool does not '
        "measure what KiCad draws for it",
    ]
    assert judge(board(DIMENSION.format(layer="Dwgs.User"))) == []


def test_a_text_on_a_custom_pads_shape_fails_overlap():
    """The second review's a3_custom: Q1's pad 3 at (120, 110) is a 0.5 mm anchor and a 4 x 1 mm polygon,
    118..122 by 109.5..110.5. "A" at (121.5, 110), 0.8 mm high: 1.055118 x 0.8 + 0.15 = 0.994094 wide,
    121.002953..121.997047 by 109.525..110.475, off the anchor and wholly on the polygon."""
    q1 = (
        '(footprint "X:Q1" (layer "F.Cu") (at 120 110) (property "Reference" "Q1" (at 0 -3 0) '
        '(layer "F.Fab") (effects (font (size 1 1) (thickness 0.15)))) '
        '(fp_rect (start -2.5 -1) (end 2.5 1) (layer "F.CrtYd")) '
        '(pad "3" smd custom (at 0 0) (size 0.5 0.5) (layers "F.Cu" "F.Mask") '
        "(options (clearance outline) (anchor rect)) "
        "(primitives (gr_poly (pts (xy -2 -0.5) (xy 2 -0.5) (xy 2 0.5) (xy -2 0.5)) (width 0) (fill yes)))))"
    )
    found = judge(board(q1, txt("A", 121.5, 110, size=0.8)))
    assert [f.line for f in found] == [
        'legend overlap: text "A" at (121.5, 110) mm on F.SilkS: on the solder mask opening of Q1 pad 3 by '
        "0.994 x 0.95 mm (rules/legend.json)"
    ]


def test_kicads_mask_clip_naming_only_a_pad_is_kept_where_a_text_is_on_it(tmp_path):
    """kicad-cli 10.0.8 on h1-field named only the pad in each silk_over_copper of the field on it
    ("Pad 1 [<no net>] of R1 on F.Cu" at (119.2, 110)): the text it clips is not named. The gate keeps it as
    a failure where a text of the board is on that pad's opening, and as not judged where none is."""
    report = {
        "violations": [
            {
                "type": "silk_over_copper",
                "severity": "warning",
                "description": "Silkscreen clipped by solder mask",
                "items": [{"description": "Pad 1 [<no net>] of R1 on F.Cu", "pos": {"x": 119.2, "y": 110.0}}],
            }
        ]
    }
    assert legend.kicad_findings(report) == []
    on = legend.read_board(
        kicadgen.parse(board(fp("R1", 120, 110, (-1.5, -0.8, 1.5, 0.8), R_PADS), txt("A", 119.2, 110)))
    )
    off = legend.read_board(kicadgen.parse(board(fp("R1", 120, 110, (-1.5, -0.8, 1.5, 0.8), R_PADS))))
    said = (
        "KiCad silk_over_copper at (119.2, 110) mm: Silkscreen clipped by solder mask: Pad 1 [<no net>] of "
        "R1 on F.Cu"
    )
    assert legend.kicad_unnamed(report, on) == (
        [f'legend overlap: {said}; on it: text "A" (KiCad\'s own check, warning in its report)'],
        [],
    )
    assert legend.kicad_unnamed(report, off) == (
        [],
        [
            f"legend not judged: {said}: KiCad names no silkscreen item and no text the tool reads is on it "
            "(KiCad's own check, warning in its report)"
        ],
    )
    # The gate takes both: the failure red, the not judged a warning (red with --strict).
    proj = project(tmp_path, board(fp("R1", 120, 110, (-1.5, -0.8, 1.5, 0.8), R_PADS)))
    loose, strict = legend.gate(proj, report, False, None), legend.gate(proj, report, True, None)
    assert (loose["red"], loose["failures"], len(loose["warnings"])) == (False, [], 1)
    assert (strict["red"], len(strict["failures"])) == (True, 1)
    (tmp_path / "x.kicad_pcb").write_text(
        board(fp("R1", 120, 110, (-1.5, -0.8, 1.5, 0.8), R_PADS), txt("A", 119.2, 110)), encoding="utf-8"
    )
    on_gate = legend.gate(proj, report, False, None)
    assert on_gate["red"] and on_gate["failures"][-1].startswith("legend overlap: KiCad silk_over_copper")


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


@pytest.mark.parametrize(
    "art",
    [
        # A text box above U1, 113..117 by 108..109.5 (the second review's a2_placer C1).
        '(gr_text_box "NOTE" (start 113 108) (end 117 109.5) (margins 0 0 0 0) (layer "F.SilkS") '
        "(effects (font (size 1 1) (thickness 0.15))) (border no))",
        # U1's own field "LM358" at local (0, -3.7): 5 x 1.055118 + 0.15 = 5.42559 by 1.15 mm, 112.287205..
        # 117.712795 by 108.725..109.875 (C2).
        "",
    ],
)
def test_the_placer_keeps_a_designator_off_a_text_box_and_off_its_parts_own_field(art):
    """Above U1 (113.869882..116.130118 by 108.7..109.85, as in the first placer test) is on either; the
    next place, right, is clear: x = 118 + 0.15 + 1.130118 = 119.280118, y = 113, local (4.280118, 0)."""
    own = field("MPN", "LM358", at=(0, -3.7), size=1, thick=0.15) if not art else ""
    root, lines = place(board(fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, 0, 0), extra=own), art))
    assert lines == []
    ref = kicadgen.children(kicadgen.children(root, "footprint")[0], "property")[0]
    assert kicadgen.atoms(kicadgen.child(ref, "at")) == ["4.280118", "0", "0"]
    assert fails(legend.judge(legend.read_board(root), legend.limits(None), PACK)) == []


def test_a_text_on_a_text_box_fails_overlap():
    """ "AB" at (115, 109): 113.869882..116.130118 by 108.425..109.575, on the text box 113..117 by
    108..109.5 by 2.260236 x 1.075 mm."""
    note = (
        '(gr_text_box "NOTE" (start 113 108) (end 117 109.5) (margins 0 0 0 0) (layer "F.SilkS") '
        "(effects (font (size 1 1) (thickness 0.15))) (border no))"
    )
    found = judge(board(note, txt("AB", 115, 109)))
    assert fails(found) == [("overlap", 'text "AB"')]
    assert 'on the area of text box "NOTE" at (113, 108) mm on F.SilkS by 2.26 x 1.075 mm' in found[1].line
    assert fails(judge(board(note, txt("AB", 115, 109, layer="B.SilkS", mirror=True)))) == []


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
    # No __pycache__ beside legend_dense.py: tests/test_docs.py holds every folder of tests/boards to a row.
    sys.dont_write_bytecode = True
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


def _dense_raw() -> tuple[str, ...]:
    """The 18 lines of the dense fixture as the library places its designators, worked out by hand.

    The KiCad 10 library's R_0603_1608Metric and C_0603_1608Metric put the designator at (0, -1.43), 1 mm
    text stroked 0.15 mm (2 characters: 2.260236 x 1.15 mm), and the courtyard at -1.48..1.48 by
    -0.73..0.73. R pads: (-+0.825, 0), 0.8 x 0.95; C pads: (-+0.775, 0), 0.9 x 0.95; the board's mask
    margin is 0. The rows are 1.5 mm apart (y = 107.5, 109, 110.5, 112), so the designator of the part in
    row k, at y_k - 1.43, box y_k - 2.005..y_k - 0.855, lies inside the courtyard of the part in row
    k - 1, y_(k-1) -+ 0.73 = y_k - 2.23..y_k - 0.77: under it by 2.260236 x 1.15 mm (x: R 108.069882..
    110.330118 inside 107.72..110.68; C 119.669882..121.930118 inside 119.32..122.28). It is on both pads
    of that part, by 0.95 mm in y (the pad's height, inside the box) and in x by
    R: 108.775 - 108.069882 = 0.705118 (pad 1, 107.975..108.775) and 110.330118 - 109.625 = 0.705118;
    C: 120.475 - 119.669882 = 0.805118 (pad 1, 119.575..120.475) and 121.930118 - 121.125 = 0.805118.
    Rows 2, 3, 4 of each column: 6 designators, each 1 hidden and 2 overlap lines: 6 hidden, 12 overlap.
    The designators of R1 and C1 are 106.77 - 106.645 = 0.125 mm above their own courtyards: no line.
    """
    out = []
    for kind, x, over in (("R", "109.2", "0.705"), ("C", "120.8", "0.805")):
        for row, y in ((2, "107.57"), (3, "109.07"), (4, "110.57")):
            where = f"designator {kind}{row} at ({x}, {y}) mm on F.SilkS"
            below = f"{kind}{row - 1}"
            hidden = f"under the courtyard of {below} by 2.26 x 1.15 mm: hidden once assembled"
            out.append(f"legend hidden: {where}: {hidden}")
            for pad in (1, 2):
                opening = f"on the solder mask opening of {below} pad {pad} by {over} x 0.95 mm"
                out.append(f"legend overlap: {where}: {opening}")
    return tuple(out)


DENSE_RAW = _dense_raw()


def test_the_dense_fixture_fails_as_the_library_places_it_and_holds_once_placed():
    """As the library places them, the designators break the rules on 18 lines: 12 overlap and 6 hidden
    (see DENSE_RAW for each, and why). Once placed, none."""
    raw = judge(dense(False).board())
    got = sorted(f.line.rsplit(" (", 1)[0] for f in raw if f.status == "fail")
    assert got == sorted(DENSE_RAW), got
    assert [f.status for f in raw].count("not judged") == 0
    rules = [line.split(":")[0] for line in got]
    assert (len(got), rules.count("legend overlap"), rules.count("legend hidden")) == (18, 12, 6)
    design = dense(True)
    placed = judge(design.board())
    assert [f.line for f in placed] == []


def test_kicads_own_legend_warnings_become_failures():
    """The violations as kicad-cli 10 wrote them for fail-legend and the dense fixture on 2026-11-17, each a
    warning by default: 2 texts in silk_overlap, a designator clipped by a pad's mask, the height. A
    designator on a footprint's silk line is KiCad's silk_overlap too, and not a text on a text: left out.
    A footprint's library is no legend matter."""
    report = {
        "violations": [
            {
                "type": "silk_overlap",
                "severity": "warning",
                "description": "Silkscreen clearance",
                "items": [
                    {"description": "PCB text 'AB' on F.Silkscreen", "pos": {"x": 110.0, "y": 105.0}},
                    {"description": "PCB text 'CD' on F.Silkscreen", "pos": {"x": 111.0, "y": 105.5}},
                ],
            },
            {
                "type": "text_height",
                "severity": "warning",
                "description": "Text height out of range (board setup constraints silk text height "
                "min height 0.8000 mm; actual 0.6000 mm)",
                "items": [{"description": "PCB text 'EF' on F.Silkscreen", "pos": {"x": 130.0, "y": 105.0}}],
            },
            {
                "type": "silk_over_copper",
                "severity": "warning",
                "description": "Silkscreen clipped by solder mask",
                "items": [
                    {"description": "Reference field of C3", "pos": {"x": 120.8, "y": 109.07}},
                    {
                        "description": "Pad 2 [unconnected-(C2--Pad2)] of C2 on F.Cu",
                        "pos": {"x": 121.575, "y": 109.0},
                    },
                ],
            },
            {
                "type": "silk_overlap",
                "severity": "warning",
                "description": "Silkscreen clearance",
                "items": [
                    {"description": "Reference field of C3", "pos": {"x": 120.8, "y": 109.07}},
                    {"description": "Segment of C2 on F.Silkscreen", "pos": {"x": 120.65942, "y": 109.51}},
                ],
            },
            {
                "type": "lib_footprint_issues",
                "severity": "warning",
                "description": "The current configuration does not include the footprint library 'Fixture'",
                "items": [{"description": "Footprint U1", "pos": {"x": 115.0, "y": 113.0}}],
            },
        ]
    }
    lines = legend.kicad_findings(report)
    assert [line.split(":")[0] for line in lines] == ["legend overlap", "legend size", "legend overlap"]
    assert "KiCad silk_overlap at (110, 105) mm" in lines[0] and "PCB text 'CD'" in lines[0]
    assert "warning in its report" in lines[1]


@pytest.mark.engine
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


# ---------------------------------------------------------------- the board's edge is its outline


def circle(cx, cy, r, layer="Edge.Cuts"):
    return f'(gr_circle (center {cx} {cy}) (end {cx + r} {cy}) (layer "{layer}"))'


def test_text_in_a_round_cutout_fails_overlap():
    """A cutout of radius 4 mm at (120, 110). "AB" there: 118.869882..121.130118 by 109.425..110.575; its
    far corner is hypot(1.130118, 0.575) = 1.268 mm from the centre, inside the hole: off the board.
    At (120, 106.5): 105.925..107.075; its corner (121.130118, 105.925) is hypot(1.13, 4.075) = 4.229 mm
    out and (121.13, 107.075) is hypot(1.13, 2.925) = 3.136 mm: across the cut. At (120, 104): the nearest
    point to the centre, (120, 104.575), is 5.425 mm off: clear of the hole."""
    hole = circle(120, 110, 4)
    assert fails(judge(board(hole, txt("AB", 120, 110)))) == [("overlap", 'text "AB"')]
    assert fails(judge(board(hole, txt("AB", 120, 106.5)))) == [("overlap", 'text "AB"')]
    assert fails(judge(board(hole, txt("AB", 120, 104)))) == []


def test_text_outside_a_round_board_fails_overlap():
    """A round board of radius 10 mm at (120, 110). "AB" at (128, 102): 126.869882..129.130118 by
    101.425..102.575; its nearest point to the centre, (126.869882, 102.575), is hypot(6.87, 7.425) =
    10.116 mm off: wholly outside the board, though inside its square 110..130 by 100..120. At (120, 110)
    it is inside."""
    edge = circle(120, 110, 10)
    assert fails(judge(board(edge, txt("AB", 128, 102), outline=None))) == [("overlap", 'text "AB"')]
    assert fails(judge(board(edge, txt("AB", 120, 110), outline=None))) == []


L_SHAPE = (
    "(gr_poly (pts (xy 100 100) (xy 140 100) (xy 140 110) (xy 120 110) (xy 120 120) (xy 100 120)) "
    '(layer "Edge.Cuts"))'
)


def test_text_in_the_notch_of_an_l_shaped_board_fails_overlap():
    """An L: 100..140 by 100..110, and 100..120 by 110..120; the notch 120..140 by 110..120 is cut away.
    "AB" at (130, 115): 128.869882..131.130118 by 114.425..115.575, in the notch. At (110, 115) it is on
    the board. At (120, 110) it lies across the notch's corner: the edge from (140, 110) to (120, 110)
    runs through it."""
    assert fails(judge(board(L_SHAPE, txt("AB", 130, 115), outline=None))) == [("overlap", 'text "AB"')]
    assert fails(judge(board(L_SHAPE, txt("AB", 110, 115), outline=None))) == []
    assert fails(judge(board(L_SHAPE, txt("AB", 120, 110), outline=None))) == [("overlap", 'text "AB"')]


def test_a_footprints_own_slot_is_part_of_the_edge():
    """J1 at (120, 110) cuts a slot of its own, fp_rect -2..2 by -0.5..0.5 on Edge.Cuts: 118..122 by
    109.5..110.5 on the board. "AB" at (120, 110), 118.869882..121.130118 by 109.425..110.575, lies over
    it. At (130, 105) it is clear. J1's courtyard is 117..123 by 107..113 and its designator at local
    (0, -4), (120, 106): 105.425..106.575, 0.425 mm above the courtyard."""
    slot = '(fp_rect (start -2 -0.5) (end 2 0.5) (layer "Edge.Cuts"))'
    part = fp("J1", 120, 110, (-3, -3, 3, 3), ref_at=(0, -4, 0), extra=slot)
    assert fails(judge(board(part, txt("AB", 120, 110)))) == [("overlap", 'text "AB"')]
    assert fails(judge(board(part, txt("AB", 130, 105)))) == []


def test_the_placer_keeps_a_designator_out_of_a_cutout():
    """U1 courtyard 112..118 by 110..116; a cutout 113..117.5 by 107..109.9 above it. The first place,
    above (box 113.869882..116.130118 by 108.7..109.85), is wholly in the hole. The next, right: x = 118 +
    0.15 + 1.130118 = 119.280118, y = 113; in U1's frame (4.280118, 0)."""
    hole = '(gr_rect (start 113 107) (end 117.5 109.9) (layer "Edge.Cuts"))'
    root, lines = place(board(fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, 0, 0)), hole))
    assert lines == []
    ref = kicadgen.children(kicadgen.children(root, "footprint")[0], "property")[0]
    assert kicadgen.atoms(kicadgen.child(ref, "at")) == ["4.280118", "0", "0"]


def test_a_board_with_no_outline_leaves_the_edge_not_judged():
    found = judge(board(txt("AB", 120, 110), outline=None))
    assert fails(found) == []
    assert [f.line for f in found if f.status == "not judged"] == [
        "legend not judged: the board's edge: it has no outline on Edge.Cuts"
    ]


# ---------------------------------------------------------------- a turned part is measured turned


def test_a_courtyard_turned_45_degrees_hides_a_designator_at_its_centre():
    """U1's courtyard -3..3 turned 45 degrees at (115, 113) is a diamond with its tips 3 x sqrt 2 = 4.243
    mm from the centre. Its designator at its centre is under it. Read by 2 written corners the courtyard
    was the line y = 113 and the designator 'too far' from it."""
    b = board(fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, 0, 0), rot=45))
    assert fails(judge(b)) == [("hidden", "designator U1")]


def test_a_designator_beside_a_turned_courtyard_is_not_under_it():
    """The diamond above: tips (115, 108.757), (119.243, 113). Its upper right side is x - y = 115 -
    108.757 = 6.243. U1's designator at (118.6, 109.4) (local (3.6 x sqrt 2, 0) = (5.091169, 0)): box
    117.469882..119.730118 by 108.825..109.975. Its corner nearest the side, (117.469882, 109.975), has
    x - y = 7.495: (7.495 - 6.243) / sqrt 2 = 0.885 mm off the side, within the 2.0 mm reach; the box lies
    inside the diamond's square 110.757..119.243 by 108.757..117.243, which is not the courtyard."""
    b = board(fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(5.091169, 0, 0), rot=45))
    assert fails(judge(b)) == []


def test_the_placer_keeps_a_designator_off_a_0603_turned_45_degrees():
    """R1 at (120, 110) turned 45 degrees with the KiCad 10 library's 0603 courtyard, -1.48..1.48 by
    -0.73..0.73 (Resistor_SMD.pretty/R_0603_1608Metric.kicad_mod). Its corners, (fx + px c + py s,
    fy - px s + py c) with c = s = 0.707107: (121.562706, 109.46967), (120.53033, 108.437294),
    (118.437294, 110.53033), (119.46967, 111.562706). The top tip is 108.437294; above it the designator's
    centre is 108.437294 - 0.15 - 0.575 = 107.712294, x = 120. In R1's frame: dx = 0, dy = -2.287706;
    (-dy s, dy c) = (1.617652, -1.617652)."""
    root, lines = place(board(fp("R1", 120, 110, (-1.48, -0.73, 1.48, 0.73), ref_at=(0, 0, 0), rot=45)))
    assert lines == []
    ref = kicadgen.children(kicadgen.children(root, "footprint")[0], "property")[0]
    assert kicadgen.atoms(kicadgen.child(ref, "at")) == ["1.617652", "-1.617652", "0"]
    assert fails(legend.judge(legend.read_board(root), legend.limits(None), PACK)) == []


def test_a_turned_pad_is_measured_turned():
    """J1 at (120, 110) turned 90 degrees; its pad 2 x 0.5 at (0, 0) written at 90 degrees, as KiCad writes
    a pad's angle on the board (the dense fixture's J1 pads read (at 0 2.54 90)): 0.5 wide and 2 high,
    119.75..120.25 by 109..111. "X" at (121, 110): 120.397441..121.602559, clear. Read unturned, the pad
    would be 119..121 wide, under the X."""
    pad = '(pad "1" smd rect (at 0 0 90) (size 2 0.5) (layers "F.Cu" "F.Mask"))'
    j1 = fp("J1", 120, 110, (-1.1, -0.3, 1.1, 0.3), rot=90, extra=pad)
    assert fails(judge(board(j1, txt("X", 121, 110)))) == []
    assert fails(judge(board(j1, txt("X", 120.6, 110)))) == [("overlap", 'text "X"')]


# ---------------------------------------------------------------- justify and the default stroke


def test_a_designator_justified_top_hangs_below_its_anchor():
    """U1's courtyard top is y = 110. Its designator at local (0, -3.6), (115, 109.4), justified top: the
    text hangs half its height lower than a centred one, its centre at 109.4 + 0.5 = 109.9; box 109.325..
    110.475, 0.475 mm into the courtyard (a plot by kicad-cli 10 of "AB" justified top at y = 110 has its
    glyphs from 110.04 to 111.04, all below the anchor)."""
    b = board(fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, -3.6, 0), just="top"))
    assert fails(judge(b)) == [("hidden", "designator U1")]
    assert "by 2.26 x 0.475 mm" in next(f.line for f in judge(b) if f.rule == "hidden")


def test_a_designator_justified_bottom_sits_above_its_anchor():
    """Its designator at local (0, -3.1), (115, 109.9), justified bottom: centre 109.9 - 0.5 = 109.4, box
    108.825..109.975, 0.025 mm clear of 110. Centred it would be 109.325..110.475, under the courtyard."""
    b = board(fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, -3.1, 0), just="bottom"))
    assert fails(judge(b)) == []


def test_justify_right_ends_the_text_at_its_anchor():
    """ "AB" at (101.5, 110) justified right: 101.5 - 2.260236 = 99.239764..101.5, over the edge at 100.
    Justified left it runs 101.5..103.760236, on the board. On the back and mirrored, left is the other way:
    99.239764..101.5."""
    assert fails(judge(board(txt("AB", 101.5, 110, just="right")))) == [("overlap", 'text "AB"')]
    assert fails(judge(board(txt("AB", 101.5, 110, just="left")))) == []
    back = txt("AB", 101.5, 110, layer="B.SilkS", mirror=True, just="left")
    assert fails(judge(board(back))) == [("overlap", 'text "AB"')]


def test_a_text_with_no_thickness_is_stroked_as_kicad_strokes_it():
    """kicad-cli 10 DRC on "AB" 1 mm high with no (thickness) read its stroke as 0.125 mm (1/8 of the
    height), under JLCPCB's least 0.15 mm (rules/jlcpcb-2layer.kicad_dru)."""
    found = judge(board(txt("AB", 120, 110, thick=None)), "jlcpcb-2layer")
    assert fails(found) == [("size", 'text "AB"')]
    assert "stroke 0.125 mm" in found[0].line and "least 0.15 mm" in found[0].line


def test_the_default_stroke_follows_the_glyph_width():
    """KiCad writes (size height width). pcbnew 10 read the stroke of texts with no (thickness) as 1/8 of the
    width: (size 1 2) 0.25 mm, (size 2 1) 0.125 mm, (size 2 2) 0.25 mm (scratch probe, 2026-11-17). So 1 mm
    high and 2 mm wide is stroked 0.25 mm, over JLCPCB's 0.15 mm; 2 mm high and 1 mm wide, 0.125 mm, under."""
    wide = '(gr_text "AB" (at 120 110 0) (layer "F.SilkS") (effects (font (size 1 2))))'
    tall = '(gr_text "AB" (at 120 110 0) (layer "F.SilkS") (effects (font (size 2 1))))'
    assert fails(judge(board(wide), "jlcpcb-2layer")) == []
    found = judge(board(tall), "jlcpcb-2layer")
    assert fails(found) == [("size", 'text "AB"')] and "stroke 0.125 mm" in found[0].line


def test_a_pad_written_with_no_angle_is_upright_on_the_board():
    """pcbnew 10 read a pad written (at 0 0) with no angle, in a footprint turned 90 degrees at (135, 105),
    as at 0 degrees: its box 134..136 by 104.75..105.25 for a pad 2 x 0.5 (scratch probe, 2026-11-17).
    KiCad writes the pad's angle on the board, so no angle is 0. Here J1 at (120, 110) turned 90: the pad
    119..121 by 109.75..110.25; "X" at (121, 110), 120.397441..121.602559, is on it."""
    pad = '(pad "1" smd rect (at 0 0) (size 2 0.5) (layers "F.Cu" "F.Mask"))'
    j1 = fp("J1", 120, 110, (-1.1, -1.1, 1.1, 1.1), rot=90, ref_at=(0, -2.5, 0), extra=pad)
    found = judge(board(j1, txt("X", 121, 110)))
    assert fails(found) == [("overlap", 'text "X"')]
    assert "opening of J1 pad 1 by 0.603 x 0.5 mm" in found[0].line


# ---------------------------------------------------------------- what the check cannot read is said


def test_a_text_box_is_not_judged_and_says_so():
    box = (
        '(gr_text_box "TINY" (start 99 110) (end 104 111) (layer "F.SilkS") '
        "(effects (font (size 0.3 0.3) (thickness 0.05))))"
    )
    found = judge(board(box))
    assert [(f.rule, f.status) for f in found] == [("text box", "not judged")]
    assert 'text box "TINY"' in found[0].line and "(99, 110)" in found[0].line


def test_a_title_variable_is_measured_as_its_value():
    """The title block's title is 26 characters: 26 x 1.055118 + 0.15 = 27.583068 mm wide. "${TITLE}" at
    (110, 110) runs 96.208..123.792, over the edge at 100. Read as its 8 written characters it would be
    8.590944 wide, 105.7..114.3, on the board."""
    tb = '(title_block (title "ABCDEFGHIJKLMNOPQRSTUVWXYZ"))'
    found = judge(board(tb, txt("${TITLE}", 110, 110)))
    assert fails(found) == [("overlap", 'text "ABCDEFGHIJKLMNOPQRSTUVWXYZ"')]


def test_a_variable_the_tool_cannot_resolve_is_not_judged():
    found = judge(board(txt("${PART_NO}", 120, 110)))
    assert fails(found) == []
    assert [f.line for f in found] == [
        'legend not judged: text "${PART_NO}" at (120, 110) mm on F.SilkS: it holds ${PART_NO}, a text '
        "variable the tool does not resolve"
    ]


def test_a_designator_whose_part_has_no_courtyard_body_or_pad_is_not_judged():
    """L1 has only a silk line; its designator 8 mm off cannot be judged hidden or nearest."""
    silk = '(fp_line (start -1 0) (end 1 0) (layer "F.SilkS"))'
    found = judge(board(fp("L1", 120, 110, None, ref_at=(0, -8, 0), extra=silk)))
    assert fails(found) == []
    assert [f.line for f in found] == [
        "legend not judged: designator L1 at (120, 102) mm on F.SilkS: its part has no courtyard, body or "
        "pad, so hidden and nearest are not judged"
    ]


# ---------------------------------------------------------------- the placer's own rules


def test_the_placer_keeps_a_designator_off_a_via():
    """A via at (115, 109.275), hole 0.3 mm: 114.85..115.15 by 109.125..109.425, inside the first place
    above U1 (113.869882..116.130118 by 108.7..109.85). The next place, right: (4.280118, 0)."""
    via = "(via (at 115 109.275) (size 0.6) (drill 0.3) (layers F.Cu B.Cu))"
    root, _ = place(board(fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, 0, 0)), via))
    ref = kicadgen.children(kicadgen.children(root, "footprint")[0], "property")[0]
    assert kicadgen.atoms(kicadgen.child(ref, "at")) == ["4.280118", "0", "0"]


def test_a_text_on_a_via_fails_overlap():
    via = "(via (at 120 110) (size 0.6) (drill 0.3) (layers F.Cu B.Cu))"
    found = judge(board(via, txt("AB", 120, 110)))
    assert fails(found) == [("overlap", 'text "AB"')]
    assert "via at (120, 110) by 0.3 x 0.3 mm" in found[0].line


def test_the_placer_keeps_a_designator_off_a_pads_opening():
    """U1's own pad 0.4 x 0.4 at local (0, -3.725), outside its courtyard: its opening 114.8..115.2 by
    109.075..109.475 is inside the first place above. The next place, right: (4.280118, 0)."""
    u1 = fp("U1", 115, 113, (-3, -3, 3, 3), [(0, -3.725, 0.4, 0.4, "smd")], ref_at=(0, 0, 0))
    root, _ = place(board(u1))
    ref = kicadgen.children(kicadgen.children(root, "footprint")[0], "property")[0]
    assert kicadgen.atoms(kicadgen.child(ref, "at")) == ["4.280118", "0", "0"]


def test_the_placer_does_not_put_a_designator_nearer_another_part():
    """R2 at (115, 108.1), courtyard 114..116 by 107.6..108.6, its designator fixed. The place above U1,
    108.7..109.85, is 0.1 mm from R2 and 0.15 mm from U1: nearer R2. The next place, right: (4.280118, 0)."""
    r2 = fp("R2", 115, 108.1, (-1, -0.5, 1, 0.5))
    root, _ = place(board(fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, 0, 0)), r2), fixed={"R2"})
    u1 = next(f for f in kicadgen.children(root, "footprint") if "U1" in f[1])
    ref = kicadgen.children(u1, "property")[0]
    assert kicadgen.atoms(kicadgen.child(ref, "at")) == ["4.280118", "0", "0"]


def _u1_at(root) -> list[str]:
    u1 = next(f for f in kicadgen.children(root, "footprint") if "U1" in f[1])
    return kicadgen.atoms(kicadgen.child(kicadgen.children(u1, "property")[0], "at"))


def test_the_placer_keeps_a_designator_off_a_design_text_of_its_layer_only():
    """ "XY" at (115, 109.275) on F.SilkS is on the place above U1 (113.869882..116.130118 by 108.7..109.85):
    the next place, right, (4.280118, 0). The same text on B.SilkS is on the other layer: above it goes."""
    u1 = fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, 0, 0))
    root, _ = place(board(u1, txt("XY", 115, 109.275)))
    assert _u1_at(root) == ["4.280118", "0", "0"]
    root, _ = place(board(u1, txt("XY", 115, 109.275, layer="B.SilkS", mirror=True)))
    assert _u1_at(root) == ["0", "-3.725", "0"]


def test_the_placer_keeps_a_designator_off_one_it_has_placed():
    """The board's top edge at y = 107.5. U1 (36 mm2) is placed first, above itself: 113.869882..116.130118
    by 108.7..109.85. U2 at (110.85, 109.2), courtyard 110.2..111.5 by 108.5..109.9, left of that place
    and clear of U1's courtyard (112..118 by 110..116). Above U2, y 107.2..108.35, is over the edge. Right,
    x = 111.5 + 0.15 + 1.130118 = 112.780118, box 111.649882..113.910236 by 108.625..109.775, is on U1's
    designator by 0.040354 mm. Below, 109.719882..111.980118 by 110.05..111.2, is 0.019882 mm from U1,
    nearer than 0.15 mm from U2. Left, x = 110.2 - 0.15 - 1.130118 = 108.919882, is clear: local
    (-1.930118, 0)."""
    u2 = fp("U2", 110.85, 109.2, (-0.65, -0.7, 0.65, 0.7), ref_at=(0, 0, 0))
    u1 = fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, 0, 0))
    root, lines = place(board(u1, u2, outline=(100, 107.5, 140, 120)))
    assert lines == []
    assert _ref_at(root, "U1") == ["0", "-3.725", "0"]
    assert _ref_at(root, "U2") == ["-1.930118", "0", "0"]


def test_the_placer_keeps_a_designator_from_under_another_part():
    """U2's courtyard 113..117 by 108..109.99 (its designator fixed) covers the place above U1 (113.869882..
    116.130118 by 108.7..109.85): the next place, right, (4.280118, 0)."""
    u2 = fp("U2", 115, 109, (-2, -1, 2, 0.99), ref_at=(0, -3, 0))
    root, _ = place(board(fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, 0, 0)), u2), fixed={"U2"})
    assert _u1_at(root) == ["4.280118", "0", "0"]


def test_the_placer_keeps_to_the_reach():
    """With a reach of 0.1 mm, under the placer's own gap of 0.15 mm, no place is near enough."""
    pack = dict(PACK, designator_reach_mm=0.1)
    root = kicadgen.parse(board(fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, 0, 0))))
    lines = legend.place(root, legend.limits(None), pack)
    assert lines == ["legend: U1 has no place on F.SilkS; its designator is kept on F.Fab"]


def test_the_placer_turns_a_designator_rather_than_add_a_third_direction():
    """The design's texts read at 90 and 45 degrees: an upright designator would be a third direction. Turned
    90, the box is 1.15 wide and 2.260236 high; above U1: y = 110 - 0.15 - 1.130118 = 108.719882, in U1's
    frame (0, -4.280118) at 90."""
    art = (txt("B", 130, 105, angle=90), txt("C", 135, 105, angle=45))
    root, lines = place(board(fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, 0, 0)), *art))
    assert lines == []
    ref = kicadgen.children(kicadgen.children(root, "footprint")[0], "property")[0]
    assert kicadgen.atoms(kicadgen.child(ref, "at")) == ["0", "-4.280118", "90"]


def test_a_designator_over_a_part_on_the_other_side_is_not_hidden():
    """U2 on the back at (120, 110), courtyard 114..126 by 106..114, its designator 0.425 mm above it. R1 on
    the front at (120, 110), courtyard 119..121 by 109.5..110.5; its designator at (120, 108.7), box
    108.125..109.275, 0.225 mm off R1 and over U2, which is on the other side."""
    u2 = fp("U2", 120, 110, (-6, -4, 6, 4), ref_at=(0, -5, 0), side="B")
    r1 = fp("R1", 120, 110, (-1, -0.5, 1, 0.5), ref_at=(0, -1.3, 0))
    assert fails(judge(board(u2, r1))) == []


def test_a_pads_own_mask_margin_widens_its_opening():
    """R1's pad 1 x 1 at (120, 110) with (solder_mask_margin 0.3): its opening 119.2..120.8 by 109.2..
    110.8. "X" at (120, 108.7): 119.397441..120.602559 by 108.125..109.275, inside the opening by
    1.205118 x 0.075 mm; the copper alone starts at 109.5. At (125, 108.7) it is clear."""
    pad = '(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask") (solder_mask_margin 0.3))'
    found = judge(
        board(fp("R1", 120, 110, (-3, -1, 3, 1), ref_at=(0, -1.6, 0), extra=pad), txt("X", 125, 108.7))
    )
    assert fails(found) == []
    found = judge(
        board(fp("R1", 120, 110, (-3, -1, 3, 1), ref_at=(0, 1.6, 0), extra=pad), txt("X", 120, 108.7))
    )
    assert ("overlap", 'text "X"') in fails(found)
    assert any("solder mask opening of R1 pad 1 by 1.205 x 0.075 mm" in f.line for f in found)


def test_a_pads_mask_margin_widens_its_opening_on_each_side_by_the_margin():
    """The same pad and margin: the opening reaches x = 120 + 0.5 + 0.3 = 120.8. "X" at (121.3, 110),
    120.697441..121.902559 by 109.425..110.575, is on it by 120.8 - 120.697441 = 0.102559 x 1.15 mm."""
    pad = '(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu" "F.Mask") (solder_mask_margin 0.3))'
    found = judge(
        board(fp("R1", 120, 110, (-3, -1, 3, 1), ref_at=(0, 1.6, 0), extra=pad), txt("X", 121.3, 110))
    )
    assert [f.line.split(": ", 2)[2].split(" (")[0] for f in found] == [
        "on the solder mask opening of R1 pad 1 by 0.103 x 1.15 mm"
    ]


# ---------------------------------------------------------------- KiCad's own checks, the gate, the fab


def test_kicads_edge_clearance_of_a_footprint_outline_is_not_a_legend_line():
    """examples/snapdragon-dev-board/v0.2/docs/gates.md, line 68: KiCad's silk_edge_clearance on J2's and
    J3's silk outlines. No text is in it: not a legend failure. On a designator, it is."""

    def report(item):
        return {
            "violations": [
                {
                    "type": "silk_edge_clearance",
                    "severity": "warning",
                    "description": "Silkscreen clipped by board edge",
                    "items": [
                        {"description": item, "pos": {"x": 100.1, "y": 110.0}},
                        {"description": "Rectangle on Edge.Cuts", "pos": {"x": 100.0, "y": 110.0}},
                    ],
                }
            ]
        }

    assert legend.kicad_findings(report("Segment of J1 on F.Silkscreen")) == []
    assert len(legend.kicad_findings(report("Reference field of J1"))) == 1


def test_kicads_mask_clip_of_a_footprint_outline_is_not_a_legend_line():
    report = {
        "violations": [
            {
                "type": "silk_over_copper",
                "severity": "warning",
                "description": "Silkscreen clipped by solder mask",
                "items": [
                    {"description": "Segment of C2 on F.Silkscreen", "pos": {"x": 1.0, "y": 1.0}},
                    {"description": "Pad 2 of C2 on F.Cu", "pos": {"x": 1.0, "y": 1.0}},
                ],
            }
        ]
    }
    assert legend.kicad_findings(report) == []


def project(tmp_path, pcb_text, dru=None):
    from types import SimpleNamespace

    (tmp_path / "x.kicad_pcb").write_text(pcb_text, encoding="utf-8")
    if dru is not None:
        (tmp_path / "x.kicad_dru").write_text(dru, encoding="utf-8")
    return SimpleNamespace(dir=tmp_path, name="x", pcb=tmp_path / "x.kicad_pcb")


def test_the_gate_fails_what_was_not_judged_only_when_strict(tmp_path):
    proj = project(tmp_path, board(txt("AB", 120, 110, face="Arial")))
    loose = legend.gate(proj, {}, False, None)
    strict = legend.gate(proj, {}, True, None)
    assert (loose["red"], len(loose["warnings"]), loose["failures"]) == (False, 1, [])
    assert (strict["red"], len(strict["failures"]), strict["warnings"]) == (True, 1, [])


def test_the_fab_is_read_from_the_project(tmp_path):
    """A project whose rule set says it was copied from rules/jlcpcb-2layer is held to JLCPCB: 1.0 mm, so
    0.9 mm text fails."""
    dru = "(version 1)\n# Copied by the workcenter from jlcpcb-2layer.kicad_dru (Design.fab)\n"
    proj = project(tmp_path, board(txt("AB", 120, 110, size=0.9)), dru)
    assert legend.fab_named(tmp_path, "x") == "jlcpcb-2layer"
    result = legend.gate(proj, {}, False, None)
    assert result["red"] and "fab jlcpcb-2layer" in result["summary"]


def test_a_fab_named_by_its_own_file_is_read_from_the_project(tmp_path):
    """A rule set copied from a fab file outside rules/ (Design.fab takes a path): its own text_height of
    1.2 mm holds, so 1.0 mm text fails."""
    dru = (
        "(version 1)\n"
        '(rule "Silkscreen text"\n'
        "\t(condition \"A.Layer == 'F.Silkscreen' || A.Layer == 'B.Silkscreen'\")\n"
        "\t(constraint text_thickness (min 0.15mm))\n"
        "\t(constraint text_height (min 1.2mm)))\n\n"
        "# Copied by the workcenter from myfab.kicad_dru (Design.fab); edit the source, not this file.\n"
    )
    proj = project(tmp_path, board(txt("AB", 120, 110)), dru)
    result = legend.gate(proj, {}, False, None)
    assert result["red"], result
    assert any("under the least 1.2 mm" in line for line in result["failures"])


# ---------------------------------------------------------------- a wrong file is refused, not a traceback


@pytest.mark.parametrize(
    "text, said",
    [
        ("", "unterminated S-expression"),
        (
            '(kicad_pcb (gr_text "AB" (layer "F.SilkS") (effects (font (size 1 1)))))',
            'gr_text "AB" has no (at)',
        ),
        (
            '(kicad_pcb (footprint "T:U" (layer "F.Cu") '
            '(property "Reference" "U1" (at 0 0) (layer "F.SilkS"))))',
            "footprint U1 has no (at)",
        ),
        (board(txt("AB", 120, 110, size=0)), 'gr_text "AB" at (120, 110): its size 0 x 0 mm is not a size'),
    ],
)
def test_a_wrong_board_is_refused_with_its_file_and_place(tmp_path, capsys, text, said):
    pcb = tmp_path / "bad.kicad_pcb"
    pcb.write_text(text, encoding="utf-8")
    assert legend.main([str(pcb)]) == 2
    out = capsys.readouterr().out
    assert out.startswith(f"legend: refused: {pcb}: ") and said in out, out
    result = legend.gate(project(tmp_path, text), {}, False, None)
    assert result["red"] and result["summary"] == "legend: not run"


def test_a_missing_board_is_refused(tmp_path, capsys):
    assert legend.main([str(tmp_path / "none.kicad_pcb")]) == 2
    assert capsys.readouterr().out.startswith("legend: refused: ")


def test_the_placer_leaves_a_designator_on_the_other_side_from_its_part(tmp_path, capsys):
    """The second review's h3-backref: R9 on B.Cu with its designator on F.SilkS. The placer has no side to
    place it on: it leaves it, says so, and the check prints it as not judged; exit code 0, not a
    traceback."""
    text = board(fp("R9", 120, 110, (-1.5, -0.8, 1.5, 0.8), side="B")).replace(
        '(layer "B.SilkS")', '(layer "F.SilkS")', 1
    )
    root, lines = place(text)
    assert lines == ["legend: R9 is on B.Cu and its designator on F.SilkS; the placer leaves it where it is"]
    assert kicadgen.dumps(root) == kicadgen.dumps(kicadgen.parse(text))
    pcb = tmp_path / "back.kicad_pcb"
    pcb.write_text(text, encoding="utf-8")
    assert legend.main([str(pcb), "--place", str(tmp_path / "placed.kicad_pcb")]) == 0
    out = capsys.readouterr().out
    assert "its part is on the other side" in out and "LEGEND HELD: 0 fail" in out


def test_a_fault_of_the_tool_is_a_refusal_not_red(tmp_path, capsys, monkeypatch):
    """Exit code 1 is a red board; a fault of the tool on a file it read must not look like one."""
    pcb = tmp_path / "x.kicad_pcb"
    pcb.write_text(board(txt("AB", 120, 110)), encoding="utf-8")

    def broken(*_args):
        raise RuntimeError("a fault")

    monkeypatch.setattr(legend, "judge", broken)
    assert legend.main([str(pcb)]) == 2
    assert capsys.readouterr().out == (
        f"legend: refused: {pcb}: the tool failed on it (RuntimeError: a fault)\n"
    )


def test_place_into_a_folder_is_refused(tmp_path, capsys):
    pcb = tmp_path / "x.kicad_pcb"
    pcb.write_text(board(txt("AB", 120, 110)), encoding="utf-8")
    (tmp_path / "out").mkdir()
    assert legend.main([str(pcb), "--place", str(tmp_path / "out")]) == 2
    assert "legend: refused: " in capsys.readouterr().out


# ---------------------------------------------------------------- the command's verdict and what it reads


def test_the_command_exits_1_on_a_failure_and_on_not_judged_only_with_strict(tmp_path, capsys):
    """ "AB" 0.6 mm high is under the least 0.8 mm: red, exit code 1. "AB" in Arial is not judged: held,
    0, and red, 1, with --strict. "AB" 1 mm high at (120, 110) keeps every rule: 0."""
    for name, text, strict, rc, said in (
        ("small", txt("AB", 120, 110, size=0.6), False, 1, "LEGEND RED: 1 fail (size 1, overlap 0,"),
        ("font", txt("AB", 120, 110, face="Arial"), False, 0, "LEGEND HELD: 0 fail"),
        ("font", txt("AB", 120, 110, face="Arial"), True, 1, "LEGEND RED: 0 fail"),
        ("fine", txt("AB", 120, 110), False, 0, "LEGEND HELD: 0 fail"),
    ):
        pcb = tmp_path / f"{name}.kicad_pcb"
        pcb.write_text(board(text), encoding="utf-8")
        assert legend.main([str(pcb)] + (["--strict"] if strict else [])) == rc, name
        assert said in capsys.readouterr().out


def test_json_prints_the_verdict_and_every_line_as_json(tmp_path):
    """`workcenter --help` gives every command `--json` ("machine-readable output", docs/CONFIGURATION.md);
    `workcenter legend --json` printed its text lines all the same. Exit codes stay 0, 1 and 2."""
    pcb = tmp_path / "x.kicad_pcb"
    pcb.write_text(board(txt("AB", 120, 110, size=0.6) + txt("CD", 120, 120, face="Arial")), encoding="utf-8")
    cli = [sys.executable, str(ROOT / "tools" / "workcenter")]
    for argv in (["legend", str(pcb), "--json"], ["--json", "legend", str(pcb)]):
        proc = subprocess.run(cli + argv, **RUN)
        assert proc.returncode == 1, proc.stdout + proc.stderr
        said = json.loads(proc.stdout)
        assert said["verdict"] == "LEGEND RED" and said["counts"]["size"] == 1
        assert [line[:13] for line in said["failures"]] == ["legend size: "]
        assert [line[:19] for line in said["not_judged"]] == ["legend not judged: "]
    proc = subprocess.run(cli + ["legend", str(tmp_path / "none.kicad_pcb"), "--json"], **RUN)
    assert proc.returncode == 2 and json.loads(proc.stdout)["verdict"] == "refused"


# `legend` is a long command: a run of the CLI here does not wait on another's engine lock.
RUN = {
    "capture_output": True,
    "text": True,
    "check": False,
    "timeout": 120,
    "env": {**os.environ, "WORKCENTER_LOCK": "off"},
}


def test_the_command_reads_the_projects_fab(tmp_path, capsys):
    """A project whose rule set was copied from rules/jlcpcb-2layer is held to its 1.0 mm: 0.9 mm text is
    red. With no rule set, the least of the fabs, 0.8 mm, holds it."""
    pcb = tmp_path / "x.kicad_pcb"
    pcb.write_text(board(txt("AB", 120, 110, size=0.9)), encoding="utf-8")
    assert legend.main([str(tmp_path)]) == 0
    capsys.readouterr()
    dru = "(version 1)\n# Copied by the workcenter from jlcpcb-2layer.kicad_dru (Design.fab)\n"
    (tmp_path / "x.kicad_dru").write_text(dru, encoding="utf-8")
    assert legend.main([str(tmp_path)]) == 1
    assert "under the least 1 mm of fab jlcpcb-2layer" in capsys.readouterr().out


@pytest.mark.parametrize(
    "hidden",
    [
        '(layer "F.SilkS") (hide yes) (effects',
        '(layer "F.SilkS") hide (effects',
        "(thickness 0.15)) (hide yes))",
        "(thickness 0.15)) hide)",
    ],
)
def test_a_hidden_text_on_the_silkscreen_is_not_printed_and_not_judged(hidden):
    """KiCad 10 writes (hide yes) on the item or in its effects; older files write a bare hide. Each form
    hides "AB" 0.5 mm high, which shown would fail size; (hide no) shows it."""
    shown = '(gr_text "AB" (at 120 110 0) (layer "F.SilkS") (effects (font (size 0.5 0.5) (thickness 0.15))))'
    assert fails(judge(board(shown))) == [("size", 'text "AB"')]
    old = '(layer "F.SilkS") (effects' if "layer" in hidden else "(thickness 0.15)))"
    assert judge(board(shown.replace(old, hidden))) == []
    assert fails(judge(board(shown.replace("(thickness 0.15)))", "(thickness 0.15)) (hide no))")))) == [
        ("size", 'text "AB"')
    ]


def test_a_hidden_designator_on_the_silkscreen_is_not_judged():
    """U1's designator at its centre is under its courtyard; hidden by (hide yes), it is not printed."""
    u1 = fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, 0, 0))
    assert fails(judge(board(u1))) == [("hidden", "designator U1")]
    assert judge(board(u1.replace('(layer "F.SilkS")', '(layer "F.SilkS") (hide yes)', 1))) == []


def test_a_footprints_own_text_on_the_silkscreen_is_judged():
    """U1's fp_text "X" 0.5 mm high is under the least 0.8 mm; an fp_text "${REFERENCE}" is U1's
    designator, at U1's centre under its courtyard. U1's own designator is above it, as placed in the first
    placer test: (0, -3.725), clear."""
    small = '(fp_text user "X" (at 0 0 0) (layer "F.SilkS") (effects (font (size 0.5 0.5) (thickness 0.15))))'
    u1 = fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, -3.725, 0), extra=small)
    assert fails(judge(board(u1))) == [("size", 'text "X"')]
    ref = (
        '(fp_text user "${REFERENCE}" (at 0 0 0) (layer "F.SilkS") '
        "(effects (font (size 1 1) (thickness 0.15))))"
    )
    u1 = fp("U1", 115, 113, (-3, -3, 3, 3), ref_at=(0, -3.725, 0), extra=ref)
    assert fails(judge(board(u1))) == [("hidden", "designator U1")]


@pytest.mark.parametrize(
    "just, layer, box",
    [
        # 2 x 1.055118 + 0.15 = 2.260236 mm wide, 1.15 mm high round (120, 110).
        ("right", "F.SilkS", (117.739764, 109.425, 120.0, 110.575)),
        ("left", "F.SilkS", (120.0, 109.425, 122.260236, 110.575)),
        ("left", "B.SilkS", (117.739764, 109.425, 120.0, 110.575)),
        ("right", "B.SilkS", (120.0, 109.425, 122.260236, 110.575)),
        ("", "B.SilkS", (118.869882, 109.425, 121.130118, 110.575)),
    ],
)
def test_a_justified_box_by_its_sum(just, layer, box):
    """Justified right a text ends at its anchor; left it starts there; mirrored on the back, the other
    way round."""
    (t,) = legend.read_board(kicadgen.parse(board(txt("AB", 120, 110, layer=layer, mirror=layer[0] == "B",
                                                         just=just)))).texts  # fmt: skip
    assert tuple(round(v, 6) for v in t.box) == box


def _ref_at(root, ref: str) -> list[str]:
    for f in kicadgen.children(root, "footprint"):
        for p in kicadgen.children(f, "property"):
            if str(p[1]) == "Reference" and str(p[2]) == ref:
                return kicadgen.atoms(kicadgen.child(p, "at"))
    raise AssertionError(ref)


def test_a_designator_fixed_in_the_design_is_written_where_it_says():
    """The dense fixture's U1 at (115, 110), not turned: its designator fixed at (115, 104) is at
    (0, -6) in its frame, with the placer off. A part the design does not have is refused."""
    d = dense(False)
    d.designator("U1", 115, 104, 0)
    assert _ref_at(kicadgen.parse(d.board()), "U1") == ["0", "-6", "0"]
    d = dense(False)
    d.designator("U9", 115, 104, 0)
    with pytest.raises(ValueError, match=r"designator\('U9'\): no part 'U9'"):
        d.board()


def test_a_fab_that_names_no_stroke_leaves_the_stroke_not_judged(tmp_path):
    """A fab's rule set with a least height of 1.0 mm and no stroke: a 0.01 mm stroke is not judged, and
    says so, as a fab with no height does for the height (the first review's A10)."""
    dru = tmp_path / "noline.kicad_dru"
    dru.write_text(
        "(version 1)\n"
        '(rule "Silkscreen text"\n'
        "\t(condition \"A.Layer == 'F.Silkscreen' || A.Layer == 'B.Silkscreen'\")\n"
        "\t(constraint text_height (min 1.0mm)))\n",
        encoding="utf-8",
    )
    found = judge(board(txt("AB", 120, 110, thick=0.01)), str(dru))
    assert fails(found) == []
    (line,) = [f.line for f in found if f.status == "not judged"]
    assert line.startswith("legend not judged: text stroke on 1 texts: fab noline names no least stroke")


def test_a_knocked_out_text_is_not_judged():
    """kicad-cli 10.0.8 plotted a knocked-out "AB" (1 mm, 0.15 mm) with its filled area from 103.269 to
    104.641 in y, 0.156 mm above and 0.066 mm below the box the tool measures, 103.425..104.575 (the second
    review's p1-probe, read from its F.SilkS Gerber). The tool does not measure that area: not judged."""
    found = judge(board(txt("AB", 120, 110).replace('(layer "F.SilkS")', '(layer "F.SilkS" knockout)')))
    assert [(f.rule, f.status) for f in found] == [("font", "not judged")]
    assert "knocked out" in found[0].line


@pytest.mark.parametrize("rule", ["size", "overlap", "hidden", "nearest", "direction", "not judged"])
def test_next_answers_a_legend_line_of_the_drc_gate_with_the_placer_and_the_legend_skill(rule):
    """`workcenter next` names the DRC gate's first failure and what to do about it (tools/guide.py). A
    legend line got the catch-all answer, which names neither the placer nor the legend skill."""
    import guide

    line = f"legend {rule}: designator R1 at (120, 110) mm on F.SilkS: the reason (rules/legend.json)"
    gates = [
        type("R", (), {"gate": "drc", "status": "fail", "summary": "", "details": {"failures": [line]}})()
    ]
    assert guide.trouble(None, gates) == ("drc", line, True)
    do, read = guide.hint("drc", line)
    assert "`d.place_designators = True`" in do
    assert read == '.claude/skills/legend/SKILL.md, "Steps"'
    assert "\n## Steps\n" in (ROOT / ".claude/skills/legend/SKILL.md").read_text(encoding="utf-8")


def test_the_engine_lock_names_legend_a_long_command():
    """A command is long when it ran over 3 s on the largest input measured (docs/CONFIGURATION.md).
    `workcenter legend` starts no engine, but it took 6.14 s on a copy of basalt v0.3 (179 parts) and
    14.95 s with `--show --place`, with the lock off (2026-11-18); 0.26 s on pass-legend-dense.
    tests/test_enginelock.py holds every command named long or short."""
    import enginelock

    assert enginelock.LONG.get("legend") == "always" and "legend" not in enginelock.SHORT


def test_each_fab_page_this_file_quotes_is_quoted_as_its_rule_file_holds_it():
    """The module's docstring quotes PCBWay's and OSH Park's pages as rules/ holds them; the second
    reading of the fab files changed PCBWay's quote to "(Legend) - 0.8mm". The numbers the check reads
    from each file stand: JLCPCB 1.0 mm high and 0.15 mm stroke, PCBWay 0.8 and 0.15, OSH Park and Sierra
    a stroke alone (0.0762 and 0.127 mm)."""
    import re

    for name, quote in re.findall(r"\((rules/[\w-]+\.kicad_dru): \"([^\"]+)\"", " ".join(__doc__.split())):
        assert quote in " ".join((ROOT / name).read_text(encoding="utf-8").split()), (name, quote)
    read = {
        p.stem: (f["height"], f["stroke"])
        for p in sorted((ROOT / "rules").glob("*.kicad_dru"))
        for f in [legend.read_fab(p)]
    }
    assert read == {
        "jlcpcb-2layer": (1.0, 0.15),
        "oshpark-2layer": (None, 0.0762),
        "pcbway-standard": (0.8, 0.15),
        "sierra-circuits-web": (None, 0.127),
    }
