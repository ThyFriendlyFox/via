"""tools/creepage.py: the creepage packs of rules/board/, the gap through air and the way along the board's
face between 2 nets' copper, and the findings. No engine: each board here is drawn in the test.

The 2 pin pads of the fixtures are 1.7 mm squares (KiCad's PinHeader_1x01_P2.54mm_Vertical, pad 1:
`(size 1.7 1.7)`). With their centres D apart on 1 row the gap between them is D - 1.7 mm.
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import creepage  # noqa: E402
from ratings import Refusal  # noqa: E402

# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {
    "mil-hdbk-454c": "guideline 69, 4.1, page 69-1; table 69-I, page 69-2",
    "ti-slup419": "page 3; table 3, page 7; table 7 and figure 9, page 11",
}

PACKS = ROOT / "rules" / "board"
MIL = PACKS / "mil-hdbk-454c-g69.json"
TI = PACKS / "ti-slup419-creepage.json"


def square(cx: float, cy: float, side: float = 1.7) -> list[tuple[float, float]]:
    h = side / 2
    return [(cx - h, cy - h), (cx + h, cy - h), (cx + h, cy + h), (cx - h, cy + h)]


def rect(x1: float, y1: float, x2: float, y2: float) -> list[tuple[float, float]]:
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def copper(gap_centres: float, slots: list | None = None) -> creepage.Copper:
    """HV's pad at (110, 107.5) and GND's `gap_centres` mm to its right, on F.Cu alone."""
    return creepage.Copper(
        layers=["F.Cu", "B.Cu"],
        shapes={"F.Cu": [("HV", square(110, 107.5)), ("GND", square(110 + gap_centres, 107.5))]},
        cuts=[creepage.Cut(p, "") for p in (slots or [])],
    )


SPANS = {"HV": (0.0, 400.0), "GND": (0.0, 0.0)}


# ---------------------------------------------------------------- the packs


def test_mil_pack_reads_table_69_i_by_its_range():
    """MIL-HDBK-454C table 69-I, page 69-2: 300 to 600 V, condition A, enclosure I: 1.5 mm clearance, 3 mm
    leakage. At 150 V, the boundary of 2 rows, condition C enclosure I: the rows say 9.5 and 12.5 mm; the
    stricter, 12.5, is taken."""
    pack = creepage.read_pack(MIL)
    cond = {"condition": "A", "enclosure": "I"}
    assert pack.limit("creepage", 400, cond).at_least == 3
    assert pack.limit("creepage", 400, cond).fails_under == 3
    assert pack.limit("clearance", 400, cond).at_least == 1.5
    assert pack.limit("creepage", 150, {"condition": "C", "enclosure": "I"}).at_least == 12.5
    over = pack.limit("creepage", 1200, cond)
    assert over.at_least is None and over.fails_under is None and "1000 V" in over.why


def test_ti_pack_reads_table_3_by_its_points():
    """SLUP419 table 3, page 7, pollution degree 2, material group III: 63 V 1.25 mm, 400 V 4.0 mm.
    At 400 V: 4.0 mm. At 200 V, between the 2 rows: a gap of 4.0 mm or more passes, one under 1.25 mm
    fails. At 50 V, under the first row: 1.25 mm or more passes, and nothing fails. Over 1000 V: no
    limit."""
    pack = creepage.read_pack(TI)
    cond = {"pollution_degree": "2", "material_group": "III"}
    exact = pack.limit("creepage", 400, cond)
    assert (exact.at_least, exact.fails_under) == (4.0, 4.0)
    mid = pack.limit("creepage", 200, cond)
    assert (mid.at_least, mid.fails_under) == (4.0, 1.25)
    low = pack.limit("creepage", 50, cond)
    assert (low.at_least, low.fails_under) == (1.25, None)
    assert pack.limit("creepage", 1001, cond).at_least is None
    assert pack.tables.get("clearance") is None


def test_a_pack_with_a_column_that_falls_is_refused(tmp_path):
    """The points rule (a gap under the lower row fails) holds only if no column falls as the voltage
    rises: a pack that has one is refused, with the file and the place."""
    data = json.loads(TI.read_text(encoding="utf-8"))
    data["creepage"]["rows"][1]["mm"]["2 III"] = 1.0
    bad = tmp_path / "falls.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(Refusal, match=r"falls.json: creepage rows 2: 2 III: 1 mm is under 1.25 mm"):
        creepage.read_pack(bad)


@pytest.mark.parametrize(
    ("cond", "message"),
    [
        ({"condition": "A"}, r"`enclosure` is missing; the pack mil-hdbk-454c-g69 asks it"),
        ({"condition": "D", "enclosure": "I"}, r"condition: `D` is none of A, B, C"),
    ],
)
def test_a_project_that_does_not_state_the_conditions_is_refused(cond, message):
    pack = creepage.read_pack(MIL)
    with pytest.raises(Refusal, match=message):
        pack.conditions_of({"pack": "mil-hdbk-454c-g69", **cond})


# ---------------------------------------------------------------- the geometry


def test_gap_between_2_squares_is_the_straight_gap():
    """Centres 5 mm apart: 5 - 1.7 = 3.3 mm, through air and along the face."""
    cu = copper(5.0)
    got = creepage.measure(cu, "F.Cu", "HV", "GND", 10.0, None)
    assert got.clearance == pytest.approx(3.3, abs=1e-9)
    assert got.creepage == pytest.approx(3.3, abs=1e-9)


def test_a_slot_lengthens_the_way_round_its_corners():
    """A slot 1 mm wide from x 112 to 113 and y 105 to 110, between pads whose edges stand at x 110.85
    and 114.15, y 106.65 to 108.35. The way: from (110.85, 108.35) to (112, 110), across the slot's end
    to (113, 110), down to (114.15, 108.35): 2 x sqrt(1.15^2 + 1.65^2) + 1 = 2 x 2.011218 + 1 = 5.022437
    mm. Through air the gap stays 3.3 mm."""
    cu = copper(5.0, [rect(112, 105, 113, 110)])
    got = creepage.measure(cu, "F.Cu", "HV", "GND", 10.0, 1.0)
    assert got.clearance == pytest.approx(3.3, abs=1e-9)
    assert got.creepage == pytest.approx(2 * math.hypot(1.15, 1.65) + 1, abs=1e-6)
    assert got.creepage == pytest.approx(5.022437, abs=1e-6)


def test_a_slot_narrower_than_the_least_width_is_crossed():
    """SLUP419 table 7, page 11: at pollution degree 2 a slot counts from 1.0 mm. A slot 0.8 mm wide (x
    112.1 to 112.9) is crossed: the way stays 3.3 mm."""
    cu = copper(5.0, [rect(112.1, 105, 112.9, 110)])
    got = creepage.measure(cu, "F.Cu", "HV", "GND", 10.0, 1.0)
    assert got.creepage == pytest.approx(3.3, abs=1e-9)


def test_a_slot_with_no_least_width_in_the_pack_is_not_judged():
    """A pack that states no least width (MIL-HDBK-454C): the slot is measured, 5.022437 mm, and named,
    so the caller can say that only the slot made the way long."""
    cu = copper(5.0, [rect(112, 105, 113, 110)])
    got = creepage.measure(cu, "F.Cu", "HV", "GND", 10.0, None)
    assert got.creepage == pytest.approx(5.022437, abs=1e-6)
    assert got.slots_used


def test_a_round_cut_near_the_pair_is_not_judged():
    cu = creepage.Copper(
        layers=["F.Cu", "B.Cu"],
        shapes={"F.Cu": [("HV", square(110, 107.5)), ("GND", square(115, 107.5))]},
        cuts=[creepage.Cut(None, "a circle on Edge.Cuts at (112.5, 107.5)")],
    )
    got = creepage.measure(cu, "F.Cu", "HV", "GND", 10.0, 1.0)
    assert got.creepage is None
    assert "a circle on Edge.Cuts at (112.5, 107.5)" in got.why


def test_a_round_cut_far_from_a_failing_pair_leaves_the_fail():
    """The second review's board M1: 2 mm between HV and GND (centres 3.7 mm apart), 3 mm asked at 400
    V, and a 3.2 mm round hole on Edge.Cuts at (122, 112), 10.2 mm and more from both pads. A cut only
    lengthens a way it stands on, and a way under 3 mm + 1 mm stays within 4 mm of both nets: the
    straight 2 mm stands, and fails."""
    text = (
        HEAD
        + smd("HVPAD", "110 107.5", "1.7 1.7", "HV")
        + smd("GNDPAD", "113.7 107.5", "1.7 1.7", "GND")
        + '  (gr_circle (center 122 112) (end 123.6 112) (layer "Edge.Cuts"))\n'
        + ")\n"
    )
    cu = creepage.read_copper(text)
    assert [c.what for c in cu.cuts] == ["a circle on Edge.Cuts at (122, 112)"]
    assert [f.line.split(":")[0] for f in judged(text)] == [
        "fail creepage HV to GND on F.Cu at (110.85, 106.65)"
    ]
    near = text.replace("(center 122 112) (end 123.6 112)", "(center 111.85 111) (end 113.45 111)")
    assert [f.status for f in judged(near)] == ["not judged"]
    # The same hole drawn in a footprint turned 90 degrees, as a mounting hole's footprint draws it.
    hole = (
        '  (footprint "x:MH" (layer "F.Cu") (at 122 112 90)\n'
        '    (fp_circle (center 0 0) (end 1.6 0) (layer "Edge.Cuts")))\n'
    )
    in_fp = text.replace('  (gr_circle (center 122 112) (end 123.6 112) (layer "Edge.Cuts"))\n', hole)
    cut = creepage.read_copper(in_fp).cuts[0]
    assert cut.polygon is None and cut.box == pytest.approx((120.4, 110.4, 123.6, 113.6), abs=1e-9)
    assert [f.status for f in judged(in_fp)] == ["fail"]


def test_an_unread_cut_with_a_box_counts_only_near_both_nets():
    """A cut this module does not measure, with a box round it: near only when the box is within reach of
    both nets. Far (box from x 130): the 2 mm straight gap stands. Within reach (box over the gap): not
    judged. With no box: near, as before."""
    far = creepage.Cut(None, "a curve on Edge.Cuts", (130.0, 100.0, 131.0, 101.0))
    over = creepage.Cut(None, "a curve on Edge.Cuts", (111.0, 109.0, 113.0, 110.0))
    # Within reach of HV alone: from HV's left side at x 109.15, 109.15 - 106 = 3.15 mm; from GND's at
    # x 112.85, 6.85 mm. A way under 4 mm cannot reach it.
    one = creepage.Cut(None, "a curve on Edge.Cuts", (105.5, 107.0, 106.0, 108.0))
    cu = copper(3.7)
    for cut in (far, one):
        cu.cuts = [cut]
        assert creepage.measure(cu, "F.Cu", "HV", "GND", 4.0, None).creepage == pytest.approx(2.0, abs=1e-9)
    for cut in (over, creepage.Cut(None, "a circle on Edge.Cuts")):
        cu.cuts = [cut]
        got = creepage.measure(cu, "F.Cu", "HV", "GND", 4.0, None)
        assert got.creepage is None and cut.what in got.why


def test_a_track_is_drawn_outside_its_copper():
    """A track 0.5 mm wide from (100, 100) to (104, 100) and a pad 2 mm right of its end: the round end
    is drawn as a polygon round the circle, never inside it, so the gap read is at most the true 2 mm
    and at least 2 mm less 0.25 x (1 / cos(pi / 16) - 1) = 0.004901 mm."""
    track = creepage.capsule((100, 100), (104, 100), 0.5)
    cu = creepage.Copper(
        layers=["F.Cu", "B.Cu"],
        shapes={"F.Cu": [("A", track), ("B", square(104.25 + 2 + 0.85, 100))]},
        cuts=[],
    )
    got = creepage.measure(cu, "F.Cu", "A", "B", 10.0, None)
    assert 2 - 0.004901 <= got.clearance <= 2 + 1e-9


# ---------------------------------------------------------------- the findings


def test_mil_fails_a_gap_too_small_for_400_v_on_creepage_alone():
    """Centres 3.7 mm apart: a 2 mm gap at 400 V. Condition A, enclosure I: leakage 3 mm fails, clearance
    1.5 mm holds. 1 line."""
    pack = creepage.read_pack(MIL)
    found = creepage.findings(copper(3.7), SPANS, pack, {"condition": "A", "enclosure": "I"})
    assert [f.line for f in found] == [
        "fail creepage HV to GND on F.Cu at (110.85, 106.65): 2 mm along the surface at 400 V, at least 3 mm "
        "(condition A, enclosure I) [MIL-HDBK-454C: guideline 69, 4.1 page 69-1; table 69-I, leakage "
        "distances, page 69-2]"
    ]


def test_mil_fails_clearance_where_the_gap_is_under_it():
    """Centres 3 mm apart: a 1.3 mm gap at 400 V fails clearance 1.5 mm and leakage 3 mm: 2 lines."""
    pack = creepage.read_pack(MIL)
    found = creepage.findings(copper(3.0), SPANS, pack, {"condition": "A", "enclosure": "I"})
    assert [f.line.split(":")[0] for f in found] == [
        "fail clearance HV to GND on F.Cu at (110.85, 106.65)",
        "fail creepage HV to GND on F.Cu at (110.85, 106.65)",
    ]
    assert "1.3 mm through air at 400 V, at least 1.5 mm (condition A)" in found[0].line


def test_mil_passes_3_3_mm_at_400_v():
    pack = creepage.read_pack(MIL)
    assert creepage.findings(copper(5.0), SPANS, pack, {"condition": "A", "enclosure": "I"}) == []


def test_mil_prints_not_judged_when_only_a_slot_makes_the_way_long():
    """3.3 mm straight, 5.022 mm round the slot, 3 mm asked at 400 V: only the slot passes it, and the
    handbook states no least width for a slot."""
    pack = creepage.read_pack(MIL)
    cu = copper(5.0 - 0.5, [rect(111.75, 105, 112.75, 110)])  # 2.8 mm straight
    found = creepage.findings(cu, SPANS, pack, {"condition": "A", "enclosure": "I"})
    assert len(found) == 1 and found[0].status == "not judged"
    assert "the pack states no least width for a slot" in found[0].text


def ti(cu: creepage.Copper, spans: dict = SPANS) -> list:
    """The findings of the TI pack, pollution degree 2, group III, but its `not judged clearance` lines
    (the pack holds no clearance table: test_a_pack_with_no_clearance_table_prints_clearance_not_judged)."""
    found = creepage.findings(
        cu, spans, creepage.read_pack(TI), {"pollution_degree": "2", "material_group": "III"}
    )
    assert [f.text.startswith("clearance on ") for f in found].count(True) <= 2
    return [f for f in found if not f.text.startswith("clearance on ")]


def test_ti_passes_the_slot_and_fails_without_it():
    """Pollution degree 2, group III, 400 V: 4.0 mm. 3.3 mm straight fails; round the 1 mm slot 5.022 mm
    passes."""
    assert [f.line for f in ti(copper(5.0))] == [
        "fail creepage HV to GND on F.Cu at (110.85, 106.65): 3.3 mm along the surface at 400 V, at least "
        "4 mm (pollution degree 2, material group III) [SLUP419: table 3, page 7]"
    ]
    assert ti(copper(5.0, [rect(112, 105, 113, 110)])) == []


TI_NO_CLEARANCE = (
    "not judged clearance on {}: {} with a voltage between them, and ti-slup419-creepage holds no "
    "clearance table [SLUP419: page 7 and table 3, page 7: clearance, which this note takes from an "
    "impulse voltage (table 4 and table 5, page 8), not from the working voltage]"
)


def test_a_pack_with_no_clearance_table_prints_clearance_not_judged():
    """The second review's case S2: TI, a 1.01 mm slot, 3.3 mm straight, 5.027 mm round the slot. The
    creepage holds, but SLUP419 gives no clearance by working voltage (page 7): a line says so for the
    pairs on each layer, never only a note. HV on F.Cu alone and GND on B.Cu alone: 1 line for the 2
    faces."""
    pack = creepage.read_pack(TI)
    cond = {"pollution_degree": "2", "material_group": "III"}
    found = creepage.findings(copper(5.0, [rect(112, 105, 113.01, 110)]), SPANS, pack, cond)
    assert [f.line for f in found] == [TI_NO_CLEARANCE.format("F.Cu", "1 pair of nets")]
    faces = creepage.Copper(
        layers=["F.Cu", "B.Cu"],
        shapes={"F.Cu": [("HV", square(110, 107.5))], "B.Cu": [("GND", square(118, 107.5))]},
        cuts=[],
    )
    assert [f.line for f in creepage.findings(faces, SPANS, pack, cond)] == [
        TI_NO_CLEARANCE.format("F.Cu and B.Cu", "1 pair of nets")
    ]


def test_ti_fails_a_slot_narrower_than_table_7_asks():
    """A slot 0.8 mm wide (x 112.1 to 112.9) on the straight way: SLUP419 table 7, page 11, counts a slot
    from 1.0 mm at pollution degree 2, so the way is crossed, 3.3 mm, under 4.0 mm (table 3, page 7):
    the creepage fails, and so does the slot, on 1 line each."""
    found = ti(copper(5.0, [rect(112.1, 105, 112.9, 110)]))
    assert [f.line for f in found] == [
        "fail creepage HV to GND on F.Cu at (110.85, 106.65): 3.3 mm along the surface at 400 V, at least "
        "4 mm (pollution degree 2, material group III) [SLUP419: table 3, page 7]",
        "fail slot HV to GND on F.Cu at (112.1, 105): 0.8 mm wide, at least 1 mm to lengthen the way "
        "(pollution degree 2) [SLUP419: table 7 and figure 9, page 11: the least width of a slot cut into a "
        "PCB to increase creepage]",
    ]


def test_ti_between_rows_is_not_judged():
    """200 V between the 63 and 400 V rows: 3.3 mm lies between 1.25 and 4.0 mm."""
    found = ti(copper(5.0), {"HV": (0.0, 200.0), "GND": (0.0, 0.0)})
    assert [f.status for f in found] == ["not judged"]
    assert "3.3 mm at 200 V lies between 1.25 mm (63 V) and 4 mm (400 V)" in found[0].text


def test_a_net_with_no_voltage_is_not_judged():
    pack = creepage.read_pack(MIL)
    found = creepage.findings(copper(5.0), {"HV": (0.0, 400.0)}, pack, {"condition": "A", "enclosure": "I"})
    assert [f.line for f in found] == ["not judged creepage of GND: ratings.json states no voltage for it"]


def test_an_inner_layer_with_2_nets_is_not_judged():
    cu = creepage.Copper(
        layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
        shapes={"In1.Cu": [("HV", square(110, 107.5)), ("GND", square(120, 107.5))]},
        cuts=[],
    )
    found = creepage.findings(cu, SPANS, creepage.read_pack(MIL), {"condition": "A", "enclosure": "I"})
    assert [f.line for f in found] == [
        "not judged creepage on In1.Cu: 1 pair of nets with a voltage between them inside the laminate, "
        "where there is no surface"
    ]


LAMINATE = (
    "not judged creepage between {} and {}: 1 pair of nets with a voltage between them within the pack's "
    "distance of each other through the laminate, solid insulation that no table here judges ({})"
)


def test_copper_over_copper_on_2_layers_is_not_judged():
    """The second review's case 2: on 4 layers, an HV zone on In1.Cu from (110, 100) to (120, 115) lies
    right under GND's pad on F.Cu at (115, 107.5); HV comes out by a via 0.8 mm across at (135, 125). The
    way between them runs through the laminate, which neither pack judges: 1 line for the 2 layers.
    HV's via and GND's pad on F.Cu stand 18 mm and more apart: no line."""
    cu = creepage.Copper(
        layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
        shapes={
            "F.Cu": [("GND", square(115, 107.5)), ("HV", creepage.circle((135, 125), 0.4))],
            "In1.Cu": [("HV", rect(110, 100, 120, 115))],
        },
        cuts=[],
    )
    found = creepage.findings(cu, SPANS, creepage.read_pack(MIL), MIL_AI)
    assert [f.line for f in found] == [
        LAMINATE.format("F.Cu", "In1.Cu", "HV on In1.Cu to GND on F.Cu at (114.15, 106.65)")
    ]


def test_copper_over_copper_on_2_inner_layers_is_not_judged():
    """The second review's case Z1: an HV zone on In1.Cu over a GND zone on In2.Cu, the same square. 1
    line for In1.Cu and In2.Cu. A GND zone on In2.Cu 10 mm aside (from x 130) is out of reach: no line."""
    zone = rect(110, 110, 120, 120)
    cu = creepage.Copper(
        layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
        shapes={"In1.Cu": [("HV", zone)], "In2.Cu": [("GND", zone)]},
        cuts=[],
    )
    found = creepage.findings(cu, SPANS, creepage.read_pack(MIL), MIL_AI)
    assert [f.line for f in found] == [
        LAMINATE.format("In1.Cu", "In2.Cu", "HV on In1.Cu to GND on In2.Cu at (110, 110)")
    ]
    cu.shapes["In2.Cu"] = [("GND", rect(130, 110, 140, 120))]
    cu._by.clear()
    assert creepage.findings(cu, SPANS, creepage.read_pack(MIL), MIL_AI) == []


def test_a_pair_of_nets_crossed_twice_through_the_laminate_counts_once():
    """HV over GND at x 110 to 120 and GND over HV at x 130 to 140, on In1.Cu and In2.Cu: 1 pair of nets,
    met twice. Each inner layer also holds both nets (20 mm apart): its own line."""
    left, right = rect(110, 110, 120, 120), rect(130, 110, 140, 120)
    cu = creepage.Copper(
        layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
        shapes={"In1.Cu": [("HV", left), ("GND", right)], "In2.Cu": [("GND", left), ("HV", right)]},
        cuts=[],
    )
    found = [f.text for f in creepage.findings(cu, SPANS, creepage.read_pack(MIL), MIL_AI)]
    laminate = [t for t in found if t.startswith("creepage between")]
    assert len(laminate) == 1 and ": 1 pair of nets with a voltage" in laminate[0], found


# ---------------------------------------------------------------- the board file


BOARD = """(kicad_pcb (version 20241229) (generator "pcbnew")
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))
  (net 0 "") (net 1 "HV") (net 2 "GND")
  (footprint "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical" (layer "F.Cu") (at 110 107.5)
    (property "Reference" "J1")
    (pad "1" thru_hole rect (at 0 0) (size 1.7 1.7) (drill 1) (layers "*.Cu" "*.Mask") (net 1 "HV")))
  (footprint "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical" (layer "F.Cu") (at 115 107.5)
    (property "Reference" "J2")
    (pad "1" thru_hole circle (at 0 0) (size 1.7 1.7) (drill 1) (layers "*.Cu" "*.Mask") (net 2 "GND")))
  (gr_rect (start 100 100) (end 125 115) (layer "Edge.Cuts"))
  (gr_rect (start 112 105) (end 113 110) (layer "Edge.Cuts"))
)
"""


def test_read_copper_takes_pads_on_both_faces_and_the_inner_cut():
    """2 pads on *.Cu land on F.Cu and B.Cu; the board's outline is the greater rectangle, the other is
    a cut of 4 corners."""
    cu = creepage.read_copper(BOARD)
    assert cu.layers == ["F.Cu", "B.Cu"]
    assert sorted(n for n, _ in cu.shapes["F.Cu"]) == ["GND", "HV"]
    assert sorted(n for n, _ in cu.shapes["B.Cu"]) == ["GND", "HV"]
    assert len(cu.cuts) == 1 and len(cu.cuts[0].polygon) == 4
    # GND's round pad, 1.7 mm across at x 115: its polygon reaches x 115 - 0.85 / cos(pi / 16) at most.
    gnd = next(p for n, p in cu.shapes["F.Cu"] if n == "GND")
    assert min(x for x, _ in gnd) == pytest.approx(115 - 0.85 / math.cos(math.pi / 16), abs=1e-9)


# ---------------------------------------------------------------- the review's boards

HEAD = """(kicad_pcb (version 20241229) (generator "test")
  (general (thickness 1.6))
  (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))
  (net 0 "") (net 1 "HV") (net 2 "GND")
  (gr_rect (start 100 100) (end 125 115) (layer "Edge.Cuts"))
"""
MIL_AI = {"condition": "A", "enclosure": "I"}


def smd(name: str, at: str, size: str, net: str, layer: str = "F.Cu") -> str:
    net_s = f' (net "{net}")' if net else ""
    return (
        f'  (footprint "x:{name}" (layer "{layer}") (at {at})\n'
        f'    (pad "1" smd rect (at 0 0) (size {size}) (layers "{layer}"){net_s}))\n'
    )


def judged(text: str, spans: dict = SPANS) -> list:
    return creepage.findings(creepage.read_copper(text), spans, creepage.read_pack(MIL), MIL_AI)


# A GND arc of radius 3 mm, width 0.3 mm, centre (115, 107.5), from 270 through 180 to 90 degrees (y down),
# and an HV via of 1 mm on the 225 degree ray, 6.15 mm from the centre: 4.348701 x sqrt(2) = 6.15.
ARC = (
    HEAD
    + """  (via (at 110.651299 103.151299) (size 1) (drill 0.5) (layers "F.Cu" "B.Cu") (net 1))
  (arc (start 115 104.5) (mid 112 107.5) (end 115 110.5) (width 0.3) (layer "F.Cu") (net 2))
)
"""
)


def test_an_arc_track_is_drawn_outside_its_copper():
    """Every point of the arc's copper, at radius 3 - 0.15 and 3 + 0.15 mm from 90 to 270 degrees and
    round each end, lies in the polygons; no corner of them stands more than 0.0049 mm off the copper:
    the band's outer corners stand at 3.15 / cos(pi / 128) - 3.15 = 0.00095 mm, the ends' at
    0.15 x (1 / cos(pi / 16) - 1) = 0.0029 mm."""
    polys = creepage.arc_track((115, 104.5), (112, 107.5), (115, 110.5), 0.3)
    c = (115.0, 107.5)
    for k in range(361):
        t = math.radians(90 + k / 2)
        for r in (2.85, 3.0, 3.15):
            q = (c[0] + r * math.cos(t), c[1] + r * math.sin(t))
            assert creepage.nearest(polys, q)[0] <= 1e-9, (k, r)
    for end in ((115, 104.5), (115, 110.5)):
        for k in range(36):
            t = math.radians(10 * k)
            q = (end[0] + 0.15 * math.cos(t), end[1] + 0.15 * math.sin(t))
            assert creepage.nearest(polys, q)[0] <= 1e-9
    for poly in polys:
        for p in poly:
            off_band = abs(math.hypot(p[0] - c[0], p[1] - c[1]) - 3) - 0.15
            in_sweep = p[0] <= c[0] + 1e-9
            off_ends = min(math.hypot(p[0] - e[0], p[1] - e[1]) for e in ((115, 104.5), (115, 110.5))) - 0.15
            assert min(off_band if in_sweep else math.inf, off_ends) <= 0.0049


def test_an_arc_track_is_not_read_as_2_chords():
    """The review's board C1: the true gap is 6.15 - 3 - 0.15 - 0.5 = 2.5 mm, under the 3 mm of table
    69-I, page 69-2 (300 to 600 V, condition A, enclosure I). Read as 2 chords it read 3.379 mm and passed.
    The polygons stand at most 0.5 x (1 / cos(pi / 16) - 1) = 0.0098 mm (the via) + 0.00095 mm (the arc)
    outside the copper, so the gap read lies from 2.5 - 0.0108 to 2.5 mm."""
    found = judged(ARC)
    fails = [f for f in found if f.status == "fail" and f.text.startswith("creepage HV to GND on F.Cu")]
    assert len(fails) == 1, [f.line for f in found]
    read = float(fails[0].text.split(": ")[1].split(" mm")[0])
    assert 2.5 - 0.0108 - 0.001 <= read <= 2.5


FACES = (
    HEAD + smd("HVPAD", "110 100.8", "2 1", "HV") + smd("GNDPAD", "110 100.8", "2 1", "GND", "B.Cu") + ")\n"
)


def test_copper_on_the_2_faces_near_the_edge_is_not_judged():
    """The review's board C2: HV's pad on F.Cu and GND's on B.Cu, each 2 x 1 mm at y 100.8, from y
    100.3: 0.3 mm from the edge at y 100. The way round the edge is at least 0.3 + 1.6 + 0.3 = 2.2 mm,
    under 3 mm: not judged, 1 line. Through air, at least sqrt((0.3 + 0.3)^2 + 1.6^2) = 1.709 mm, over the
    1.5 mm of clearance: no line."""
    found = judged(FACES)
    assert [f.line for f in found] == [
        "not judged creepage HV on F.Cu to GND on B.Cu at (109, 100.3): at least 2.2 mm round the board's "
        "edge or through a hole, 3 mm asked at 400 V: this check does not measure a way between the 2 "
        "faces [MIL-HDBK-454C: guideline 69, 4.1 page 69-1; table 69-I, leakage distances, page 69-2]"
    ]


def test_copper_on_the_2_faces_far_enough_from_the_edge_holds():
    """The same pads at y 101.5, from y 101: 1 mm from the edge. At least 1 + 1.6 + 1 = 3.6 mm round the
    edge, over 3 mm: no line."""
    far = FACES.replace("110 100.8", "110 101.5")
    assert judged(far) == []


def test_copper_with_no_net_shortens_the_way_to_the_edge():
    """The pads 1 mm from the edge (3.6 mm round it), and a pad with no net on F.Cu, 2 x 0.8 mm at y
    100.5, from y 100.1 to 100.9: 0.1 mm from HV's pad and 0.1 mm from the edge. Across it the way is at
    least 0.1 + 0.1 + 1.6 + 1 = 2.8 mm, under 3 mm."""
    far = FACES.replace("110 100.8", "110 101.5")
    text = far[: far.rindex(")")] + smd("FLOAT", "110 100.5", "2 0.8", "") + ")\n"
    assert [f.line for f in judged(text)] == [
        "not judged creepage HV on F.Cu to GND on B.Cu at (109, 101): at least 2.8 mm round the board's "
        "edge or through a hole, 3 mm asked at 400 V: this check does not measure a way between the 2 "
        "faces [MIL-HDBK-454C: guideline 69, 4.1 page 69-1; table 69-I, leakage distances, page 69-2]"
    ]


def _faces_lines(text: str) -> list[str]:
    return [f.line for f in judged(text) if " on F.Cu to GND on B.Cu" in f.text]


BARREL = (
    HEAD
    + smd("HVPAD", "110 107.5", "1.7 1.7", "HV")
    + smd("GNDPAD", "115 107.5", "1.7 1.7", "GND", "B.Cu")
    + "{}"
    + ")\n"
)


@pytest.mark.parametrize(
    ("joint", "what"),
    [
        ('  (via (at 112.5 107.5) (size 2) (drill 1) (layers "F.Cu" "B.Cu"))\n', "a via with no net"),
        (
            '  (footprint "x:TP" (layer "F.Cu") (at 112.5 107.5)\n'
            '    (pad "" thru_hole circle (at 0 0) (size 2 2) (drill 1) (layers "*.Cu" "*.Mask")))\n',
            "a plated hole with no net",
        ),
    ],
)
def test_a_plated_hole_with_no_net_joins_the_2_faces(joint, what):
    """The second review's board F1: HV's pad on F.Cu to x 110.85, GND's on B.Cu from x 114.15, and a
    plated barrel with no net, 2 mm across at x 112.5 (111.5 to 113.5), between them. Along the
    surface: 111.5 - 110.85 = 0.65 mm on F.Cu, the barrel (a conductor), 114.15 - 113.5 = 0.65 mm on
    B.Cu: 1.3 mm, under the 3 mm of leakage; through air 1.3 mm too, under the 1.5 mm of clearance
    (table 69-I, page 69-2). The ring (radius 1) is drawn outside its circle on each face, so the
    bound read lies from 1.3 - 2 x 1 x (1 / cos(pi / 16) - 1) = 1.2608 to 1.3 mm. Both lines are `not
    judged`, never nothing."""
    lines = _faces_lines(BARREL.format(joint))
    assert [line.split(" HV")[0] for line in lines] == ["not judged clearance", "not judged creepage"], lines
    for line in lines:
        assert f"through {what} at (112.5, 107.5)" in line, line
        read = float(line.split("at least ")[1].split(" mm")[0])
        assert 1.2608 - 0.001 <= read <= 1.3, line


def test_a_plated_mounting_hole_with_no_net_joins_the_2_faces():
    """The common form: HV's pad on F.Cu to x 106.85, an M3 mounting hole with no net (pad 6.4, drill
    3.2) at x 112 (ring from 108.8 to 115.2) and a GND pour on B.Cu that keeps 0.5 mm from the ring
    (from x 115.7). 108.8 - 106.85 = 1.95 mm + 0.5 mm = 2.45 mm along the surface, under 3 mm: `not
    judged`. Through air 2.45 mm, over the 1.5 mm of clearance: no line."""
    ring = [(108.3, 107.5), (108.3, 111.2), (115.7, 111.2), (115.7, 103.8), (108.3, 103.8), (108.3, 107.5)]
    pour = [(101, 101), (124, 101), (124, 114), (101, 114), (101, 107.5), *ring, (101, 107.5)]
    pts = " ".join(f"(xy {x} {y})" for x, y in pour)
    text = (
        HEAD
        + smd("HVPAD", "106 107.5", "1.7 1.7", "HV")
        + '  (footprint "x:MH" (layer "F.Cu") (at 112 107.5)\n'
        + '    (pad "1" thru_hole circle (at 0 0) (size 6.4 6.4) (drill 3.2) (layers "*.Cu" "*.Mask")))\n'
        + f'  (zone (net "GND") (layer "B.Cu") (filled_polygon (layer "B.Cu") (pts {pts})))\n'
        + ")\n"
    )
    lines = _faces_lines(text)
    assert len(lines) == 1 and lines[0].startswith("not judged creepage HV on F.Cu to GND on B.Cu"), lines
    assert "through a plated hole with no net at (112, 107.5)" in lines[0]
    read = float(lines[0].split("at least ")[1].split(" mm")[0])
    assert 2.45 - 2 * 3.2 * (1 / math.cos(math.pi / 16) - 1) - 0.001 <= read <= 2.45


FLOATING = (
    HEAD
    + smd("HVPAD", "110 107.5", "1.7 1.7", "HV")
    + smd("GNDPAD", "115 107.5", "1.7 1.7", "GND")
    + smd("FLOAT", "112.5 107.5", "1.7 1.7", "")
    + ")\n"
)


def test_a_pad_with_no_net_between_2_nets_is_not_judged():
    """The review's board C3: 3.3 mm straight, but a pad with no net stands between, 1.7 mm square at x
    112.5: 111.65 - 110.85 = 0.8 mm from HV and 114.15 - 113.35 = 0.8 mm from GND. 0.8 + 0.8 = 1.6 mm,
    under 3 mm."""
    found = judged(FLOATING)
    assert [f.line for f in found] == [
        "not judged creepage HV to GND on F.Cu at (110.85, 106.65): 1.6 mm across copper with no net (a pad "
        "with no net at (112.5, 107.5)), under the 3 mm asked at 400 V: this check does not judge a way "
        "across a conductor with no net [MIL-HDBK-454C: guideline 69, 4.1 page 69-1; table 69-I, leakage "
        "distances, page 69-2]"
    ]


def test_2_pads_with_no_net_in_a_row_are_not_judged():
    """HV's pad at x 110 (to 110.85), GND's at x 116 (from 115.15): 4.3 mm straight. 2 pads with no net,
    0.8 mm squares at x 112.05 (111.65 to 112.45) and 113.95 (113.55 to 114.35). The first alone leaves
    0.8 + (115.15 - 112.45) = 3.5 mm, the second (113.55 - 110.85) + 0.8 = 3.5 mm, both over 3 mm. The
    2 in a row leave 0.8 + (113.55 - 112.45) + 0.8 = 2.7 mm, under 3 mm."""
    text = (
        HEAD
        + smd("HVPAD", "110 107.5", "1.7 1.7", "HV")
        + smd("GNDPAD", "116 107.5", "1.7 1.7", "GND")
        + smd("F1", "112.05 107.5", "0.8 0.8", "")
        + smd("F2", "113.95 107.5", "0.8 0.8", "")
        + ")\n"
    )
    found = judged(text)
    assert len(found) == 1 and found[0].status == "not judged", [f.line for f in found]
    assert "2.7 mm across copper with no net" in found[0].text


def test_a_pad_with_no_net_out_of_the_way_holds():
    """The pad with no net at (112.5, 112): from y 111.15, 111.15 - 108.35 = 2.8 mm below the 2 pads and
    0.8 mm to the side of each: sqrt(0.8^2 + 2.8^2) = 2.912 mm to each, 5.824 mm across it, over 3 mm."""
    assert judged(FLOATING.replace("112.5 107.5", "112.5 112")) == []


PADANGLE = (
    HEAD
    + """  (footprint "x:HVPAD" (layer "F.Cu") (at 110 107.5 90)
    (pad "1" smd rect (at 0 0) (size 4 1) (layers "F.Cu") (net "HV")))
"""
    + smd("GNDPAD", "114 107.5", "1 1", "GND")
    + ")\n"
)


def test_a_pad_whose_file_gives_no_angle_stands_at_0_degrees():
    """The review's board C4. A pad's angle in a board file is the board's, and KiCad leaves it out at 0:
    the HV pad, 4 x 1 mm at (110, 107.5), spans x 108 to 112, though its footprint is turned 90 degrees.
    GND's 1 mm pad at x 114 starts at 113.5: 1.5 mm, at least the 1.5 mm of clearance, under the 3 mm of
    leakage."""
    cu = creepage.read_copper(PADANGLE)
    hv = next(p for n, p in cu.shapes["F.Cu"] if n == "HV")
    assert (min(x for x, _ in hv), max(x for x, _ in hv)) == pytest.approx((108, 112), abs=1e-9)
    assert [f.line for f in judged(PADANGLE)] == [
        "fail creepage HV to GND on F.Cu at (112, 107): 1.5 mm along the surface at 400 V, at least 3 mm "
        "(condition A, enclosure I) [MIL-HDBK-454C: guideline 69, 4.1 page 69-1; table 69-I, leakage "
        "distances, page 69-2]"
    ]


def test_a_pad_whose_shape_is_offset_from_its_hole_is_read_round_both():
    """KiCad's pad `(drill 0.5 (offset 1 0))` moves the pad's copper 1 mm from its hole, from x 109.5 to
    110.5 to x 110.5 to 111.5. The pad is read as a 3 x 3 mm square round its hole, which holds the
    copper wherever the offset turns: to x 111.5. GND's 1 mm pad at x 114 starts at 113.5: 2 mm, under
    3 mm. Read without the offset it is 3 mm, and passes."""
    text = (
        HEAD
        + """  (footprint "x:HVPIN" (layer "F.Cu") (at 110 107.5)
    (pad "1" thru_hole rect (at 0 0) (size 1 1) (drill 0.5 (offset 1 0)) (layers "*.Cu") (net "HV")))
"""
        + smd("GNDPAD", "114 107.5", "1 1", "GND")
        + ")\n"
    )
    fails = [f.text for f in judged(text) if f.status == "fail"]
    assert len(fails) == 1 and ": 2 mm along the surface at 400 V" in fails[0], fails


def test_a_trapezoid_pad_is_read_round_its_widened_side():
    """A trapezoid pad 1 x 1 mm with `(rect_delta 0 1)` at (110, 107.5): its delta widens 1 side past
    the 1 mm rectangle. The pad is read as a box of 1 + 0 + 1 = 2 mm a side, which holds the trapezoid
    whichever side the delta widens: to x 111. GND's 1 mm pad at x 114 starts at 113.5: 2.5 mm, under
    the 3 mm of table 69-I. Read as its 1 mm rectangle it is 3 mm, and passes."""
    text = (
        HEAD
        + """  (footprint "x:HVPAD" (layer "F.Cu") (at 110 107.5)
    (pad "1" smd trapezoid (at 0 0) (size 1 1) (rect_delta 0 1) (layers "F.Cu") (net "HV")))
"""
        + smd("GNDPAD", "114 107.5", "1 1", "GND")
        + ")\n"
    )
    fails = [f.text for f in judged(text) if f.status == "fail"]
    assert len(fails) == 1 and ": 2.5 mm along the surface at 400 V" in fails[0], fails


def test_a_pad_with_a_padstack_is_not_judged():
    """KiCad 10 can give a pad another size on another layer, in `(padstack ...)`: the size read is the
    first layer's only, so the pad is named as copper not read."""
    text = (
        HEAD
        + """  (footprint "x:HVPAD" (layer "F.Cu") (at 110 107.5)
    (pad "1" smd rect (at 0 0) (size 1.7 1.7) (layers "F.Cu") (net "HV")
      (padstack (mode front_inner_back) (layer "Inner" (size 1 1)))))
"""
        + smd("GNDPAD", "115 107.5", "1.7 1.7", "GND")
        + ")\n"
    )
    found = judged(text)
    assert [f.line for f in found] == [
        "not judged creepage on F.Cu: 1 shape drawn on the copper is not read (a pad with a padstack of "
        "x:HVPAD at (110, 107.5))"
    ]


def test_copper_drawn_as_a_shape_is_not_judged():
    """A line drawn on F.Cu is copper this module does not read: 1 line for the layer."""
    text = FLOATING.replace(
        smd("FLOAT", "112.5 107.5", "1.7 1.7", ""),
        '  (gr_line (start 112.5 105) (end 112.5 110) (width 0.2) (layer "F.Cu"))\n',
    )
    found = judged(text)
    assert [f.line for f in found] == [
        "not judged creepage on F.Cu: 1 shape drawn on the copper is not read (a gr_line at (112.5, 105))"
    ]


@pytest.mark.parametrize(
    ("item", "what"),
    [
        (
            '  (dimension (type aligned) (layer "F.Cu") (pts (xy 111 107.5) (xy 114 107.5)) (height 0))\n',
            "a dimension at (111, 107.5)",
        ),
        ('  (image (at 112.5 107.5) (layer "F.Cu") (scale 1))\n', "an image at (112.5, 107.5)"),
        (
            '  (footprint "x:T" (layer "F.Cu") (at 112.5 107.5)\n'
            '    (property "Value" "BIG" (at 0 0) (layer "F.Cu")\n'
            "      (effects (font (size 3 3) (thickness 0.6)))))\n",
            "a property of x:T at (112.5, 107.5)",
        ),
    ],
)
def test_every_other_node_on_copper_is_not_judged(item, what):
    """The second review's cases 5b and 5d: a footprint's property text on F.Cu, a dimension on F.Cu; and
    an image on F.Cu. Each is copper this module does not read: 1 line for the layer."""
    text = FLOATING.replace(smd("FLOAT", "112.5 107.5", "1.7 1.7", ""), item)
    assert [f.line for f in judged(text)] == [
        f"not judged creepage on F.Cu: 1 shape drawn on the copper is not read ({what})"
    ]


def test_a_hidden_property_on_copper_is_no_copper():
    """A property with `(hide yes)`, or `hide` in its effects as older files write it, is not drawn."""
    for hide in ("(hide yes) (effects (font (size 3 3)))", "(effects (font (size 3 3)) hide)"):
        item = (
            '  (footprint "x:T" (layer "F.Cu") (at 112.5 107.5)\n'
            f'    (property "Value" "BIG" (at 0 0) (layer "F.Cu") {hide}))\n'
        )
        assert judged(FLOATING.replace(smd("FLOAT", "112.5 107.5", "1.7 1.7", ""), item)) == []


# ---------------------------------------------------------------- a board file KiCad would not write

GOOD = smd("GNDPAD", "120 107.5", "1.7 1.7", "GND")
FP_A = '  (footprint "x:A" (layer "F.Cu") (at 110 107.5)\n'


@pytest.mark.parametrize(
    ("item", "message"),
    [
        (
            FP_A + '    (pad "1" smd rect (at 0 0) (layers "F.Cu")))\n',
            r"b.kicad_pcb: pad 1 of x:A at \(110, 107.5\): `\(size \.\.\.\)` is missing",
        ),
        (
            FP_A + '    (pad "1" smd rect (size 1 1) (layers "F.Cu")))\n',
            r"b.kicad_pcb: pad 1 of x:A at \(110, 107.5\): `\(at \.\.\.\)` is missing",
        ),
        (
            '  (segment (start 110 107.5) (end 112 107.5) (layer "F.Cu") (net "HV"))\n',
            r"b.kicad_pcb: segment at \(110, 107.5\): `\(width \.\.\.\)` is missing",
        ),
        (
            '  (arc (start 110 107.5) (end 112 107.5) (width 0.2) (layer "F.Cu") (net "HV"))\n',
            r"b.kicad_pcb: arc at \(110, 107.5\): `\(mid \.\.\.\)` is missing",
        ),
        (
            '  (footprint "x:A" (layer "F.Cu")\n'
            '    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu")))\n',
            r"b.kicad_pcb: footprint x:A, number 1 in the file: `\(at \.\.\.\)` is missing",
        ),
        (
            '  (gr_rect (start 112 110) (layer "Edge.Cuts"))\n',
            r"b.kicad_pcb: gr_rect at \(112, 110\): `\(end \.\.\.\)` is missing",
        ),
        (
            '  (via (at 112 110) (size a) (drill 0.4) (layers "F.Cu" "B.Cu"))\n',
            r"b.kicad_pcb: via at \(112, 110\): `\(size a\)` is no number",
        ),
    ],
)
def test_a_node_that_lacks_a_part_kicad_writes_is_refused_with_its_place(tmp_path, item, message):
    """The second review's crash2.py: each board ended in a TypeError or a KeyError inside
    boardrules.read_board, which the DRC gate does not catch. Each is refused, with the file and the
    node, on the gate's own way (boardrules.judge)."""
    import boardrules

    (tmp_path / "board-rules.json").write_text(
        json.dumps({"creepage": {"pack": "mil-hdbk-454c-g69", **MIL_AI}})
    )
    pcb = tmp_path / "b.kicad_pcb"
    pcb.write_text(HEAD + item + GOOD + ")\n", encoding="utf-8")
    project = type("Project", (), {"dir": tmp_path, "pcb": pcb})()
    with pytest.raises(Refusal, match=message):
        boardrules.judge(project, tmp_path / "out", None)


def test_a_board_with_no_copper_layer_is_refused(tmp_path):
    """A board whose `(layers ...)` names no copper layer read `0 fail, 0 not judged`."""
    import boardrules

    (tmp_path / "board-rules.json").write_text(
        json.dumps({"creepage": {"pack": "mil-hdbk-454c-g69", **MIL_AI}})
    )
    pcb = tmp_path / "b.kicad_pcb"
    pcb.write_text("(kicad_pcb (version 20241229) (general (thickness 1.6)))\n", encoding="utf-8")
    project = type("Project", (), {"dir": tmp_path, "pcb": pcb})()
    with pytest.raises(Refusal, match=r"b.kicad_pcb: `\(layers \.\.\.\)` names no copper layer"):
        boardrules.judge(project, tmp_path / "out", None)
    with pytest.raises(Refusal, match=r"b.kicad_pcb: `\(layers \.\.\.\)` names no copper layer"):
        creepage.judge(project, {"pack": "mil-hdbk-454c-g69", **MIL_AI}, pcb.read_text(encoding="utf-8"), {})


# ---------------------------------------------------------------- a project's own pack


def _bad(tmp_path, base: Path, change) -> Path:
    data = json.loads(base.read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("base", "change", "message"),
    [
        (TI, lambda d: d.update(not_judged=[]), r"bad.json: not_judged: a pack with no clearance table"),
        (
            TI,
            lambda d: d["slot"].update(least_mm=[1.0]),
            r"bad.json: slot: least_mm: an object of each value of pollution_degree",
        ),
        (
            MIL,
            lambda d: [d[t]["rows"][0].update(volts=[10, 150]) for t in ("creepage", "clearance")],
            r"bad.json: creepage rows 1: volts: a table of ranges starts at 0 V, not 10 V",
        ),
        (
            TI,
            lambda d: d["conditions"]["pollution_degree"]["values"].append("2 I"),
            r"bad.json: conditions: pollution_degree: values: `2 I` holds a space",
        ),
    ],
)
def test_a_project_pack_with_a_fault_is_refused_with_its_place(tmp_path, base, change, message):
    with pytest.raises(Refusal, match=message):
        creepage.read_pack(_bad(tmp_path, base, change))


def test_each_pack_says_what_it_takes_of_solder_mask_and_coating():
    """MIL-HDBK-454C guideline 69, 4.1, page 69-1, speaks of bare conductors; SLUP419 page 3 counts a
    board under conformal coating as pollution degree 1. Each pack's scope says the distances are held
    between bare copper, and the TI pack that degree 1 for a coated board is the project's word."""
    for path in (MIL, TI):
        scope = json.loads(path.read_text(encoding="utf-8"))["scope"]
        assert "between bare copper: solder mask" in scope and "not counted" in scope, path.name
    ti_scope = json.loads(TI.read_text(encoding="utf-8"))["scope"]
    assert "Page 3 counts a board under conformal coating as pollution degree 1" in ti_scope


def test_the_mil_pack_holds_a_hash_of_its_table_s_text():
    """Each download of MIL-HDBK-454C carries its own time stamp, so the file's SHA256 is the copy's
    alone. The text of PDF pages 129 and 130 (69-1 and 69-2) with the stamp's line removed gave
    b2547e85... from both copies fetched on 2026-11-17."""
    pack = creepage.read_pack(MIL)
    assert pack.text["sha256"] == "b2547e850a43bac8d44067a19a5e2804cc91c5e2f3682a0ad0dc585b13ce8a73"
    assert "129" in pack.text["pages"] and "Downloaded" in pack.text["how"]


# ---------------------------------------------------------------- a board of many nets


def test_a_board_of_150_nets_and_a_zone_is_judged_in_seconds():
    """150 nets of 1 pad and 1 track each, 24 V, round a GND zone of 4000 corners, on F.Cu. Every pair
    carries 24 V (boardrules.between of 0 to 24 and 0 to 24). The review's real board of 165 nets did not
    finish in 110 s; this one must finish in 20."""
    import signal

    zone = [(100 + 50 * k / 1000, 100.0) for k in range(1000)]
    zone += [(150.0, 100 + 50 * k / 1000) for k in range(1000)]
    zone += [(150 - 50 * k / 1000, 150.0) for k in range(1000)]
    zone += [(100.0, 150 - 50 * k / 1000) for k in range(1000)]
    shapes = [("GND", zone)]
    spans = {"GND": (0.0, 0.0)}
    for i in range(150):
        x, y = 153 + (i % 15) * 6, 100 + (i // 15) * 6  # the first column 153 - 0.5 - 150 = 2.5 mm off
        shapes.append((f"N{i}", square(x, y, 1)))
        shapes.append((f"N{i}", creepage.capsule((x, y), (x + 3, y + 3), 0.25)))
        spans[f"N{i}"] = (0.0, 24.0)
    cu = creepage.Copper(layers=["F.Cu", "B.Cu"], shapes={"F.Cu": shapes, "B.Cu": []}, cuts=[])

    def late(*_):
        raise TimeoutError("not done in 20 s")

    old = signal.signal(signal.SIGALRM, late)
    signal.alarm(20)
    try:
        found = creepage.findings(cu, spans, creepage.read_pack(MIL), MIL_AI)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)
    assert found == []


# ---------------------------------------------------------------- each limit, at the limit

EPS = creepage.EPS


def apart(gap: float) -> creepage.Copper:
    """HV's copper to x 0 and GND's from x `gap`, each 1 mm square, on F.Cu: the gap read is `gap` to
    the last bit (a distance along x from 0)."""
    return creepage.Copper(
        layers=["F.Cu", "B.Cu"],
        shapes={"F.Cu": [("HV", rect(-1, 0, 0, 1)), ("GND", rect(gap, 0, gap + 1, 1))]},
        cuts=[],
    )


def test_a_gap_at_the_clearance_less_eps_holds_it():
    """MIL table 69-I, page 69-2, 300 to 600 V, condition A: clearance 1.5 mm. A gap of 1.5 mm less EPS
    holds it: 1 line, the creepage's (3 mm leakage)."""
    found = creepage.findings(apart(1.5 - EPS), SPANS, creepage.read_pack(MIL), MIL_AI)
    assert [f.line.split(" HV")[0] for f in found] == ["fail creepage"]


def test_a_gap_at_the_leakage_less_eps_holds_it():
    """3 mm less EPS holds the 3 mm of leakage: no line."""
    assert creepage.findings(apart(3 - EPS), SPANS, creepage.read_pack(MIL), MIL_AI) == []


def test_a_gap_at_the_lower_row_less_eps_is_between_rows():
    """SLUP419 table 3, page 7, pollution degree 2, group III: 63 V 1.25 mm, 400 V 4.0 mm. At 200 V a
    gap of 1.25 mm less EPS holds the lower row: `not judged` between the rows, not `fail`."""
    spans = {"HV": (0.0, 200.0), "GND": (0.0, 0.0)}
    found = ti(apart(1.25 - EPS), spans)
    assert [f.status for f in found] == ["not judged"] and "lies between" in found[0].text


def test_a_slot_at_the_least_width_less_eps_counts():
    """SLUP419 table 7, page 11: a slot counts from 1.0 mm at pollution degree 2. HV's pad from x -3.35
    to -1.65, GND's from 1.65 to 3.35, both y -0.85 to 0.85: 3.3 mm straight. A slot from x 0 to 1 mm
    less EPS, y -1 to 1, counts: the way runs round its end, sqrt(1.65^2 + 0.15^2) + 1 +
    sqrt(0.65^2 + 0.15^2) = 1.656804 + 1 + 0.667083 = 3.323887 mm, under the 4.0 mm of table 3, page 7,
    at 400 V: 1 line at 3.324 mm, and the slot does not fail."""
    w = 1 - EPS
    slot = rect(0, -1, w, 1)
    assert creepage._width(slot) == w
    cu = creepage.Copper(
        layers=["F.Cu", "B.Cu"],
        shapes={"F.Cu": [("HV", square(-2.5, 0)), ("GND", square(2.5, 0))]},
        cuts=[creepage.Cut(slot, "")],
    )
    found = ti(cu)
    assert [f.text.split(": ")[1].split(" along")[0] for f in found] == ["3.324 mm"], [f.line for f in found]


def test_a_voltage_over_the_last_row_on_1_layer_is_not_judged():
    """1200 V, over the 1000 V of table 69-I's last row (page 69-2): both tables say nothing."""
    spans = {"HV": (0.0, 1200.0), "GND": (0.0, 0.0)}
    found = creepage.findings(copper(5.0), spans, creepage.read_pack(MIL), MIL_AI)
    assert [f.line.split(" [")[0] for f in found] == [
        "not judged clearance HV to GND on F.Cu: 1200 V is over 1000 V, the table's last row",
        "not judged creepage HV to GND on F.Cu: 1200 V is over 1000 V, the table's last row",
    ]


def test_a_pair_that_fails_its_clearance_gets_no_line_for_copper_with_no_net(tmp_path):
    """A pack of a project's own: MIL's tables with a least slot width of 1 mm. HV and GND 1.3 mm apart
    (centres 3 mm) fail the 1.5 mm of clearance; a slot 1 mm wide from y 104 to 111 lengthens the way to
    2 x sqrt(0.15^2 + 2.65^2) + 1 = 6.309 mm, over the 3 mm of leakage. A speck with no net in the gap:
    the pair already fails, so it gets no `not judged` line for it."""
    data = json.loads(MIL.read_text(encoding="utf-8"))
    data["slot"] = {"key": "condition", "least_mm": {"A": 1, "B": 1, "C": 1}, "where": "a test, page 1"}
    path = tmp_path / "slotted.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    cu = copper(3.0, [rect(111.0, 104, 112.0, 111)])
    cu.floating = {"F.Cu": [("a pad with no net at (111.5, 107.5)", square(111.5, 107.5, 0.1))]}
    found = creepage.findings(cu, SPANS, creepage.read_pack(path), MIL_AI)
    assert [f.line.split(":")[0] for f in found] == ["fail clearance HV to GND on F.Cu at (110.85, 106.65)"]


TWO_FACES = """(kicad_pcb (version 20241229) (generator "test")
  (general (thickness {thick}))
  (layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))
  (gr_rect (start 100 100) (end 125 115) (layer "Edge.Cuts"))
{items})
"""


def pin(name: str, at: str, net: str) -> str:
    return (
        f'  (footprint "x:{name}" (layer "F.Cu") (at {at})\n'
        f'    (pad "1" thru_hole rect (at 0 0) (size 1.7 1.7) (drill 1) (layers "*.Cu") (net "{net}")))\n'
    )


def test_a_pair_that_fails_on_a_face_gets_no_line_between_the_faces():
    """2 pins 2 mm apart (centres 3.7 mm), 0.3 mm from the board's edge (y 100.3), on both faces: each
    face fails the 3 mm of leakage. Between the faces the way round the edge is at least 0.3 + 1.6 + 0.3
    = 2.2 mm, but the pair already fails: 2 lines, no more."""
    text = TWO_FACES.format(thick=1.6, items=pin("J1", "110 101.15", "HV") + pin("J2", "113.7 101.15", "GND"))
    assert [f.line.split(" at ")[0] for f in judged(text)] == [
        "fail creepage HV to GND on F.Cu",
        "fail creepage HV to GND on B.Cu",
    ]


def test_2_nets_with_no_voltage_between_them_get_no_line_between_the_faces():
    """GND on F.Cu and GND2 on B.Cu, both 0 V, 1 over the other 0.1 mm from the edge of a 0.4 mm board:
    the way round the edge is 0.6 mm, but no voltage stands between them: no line."""
    items = smd("A", "110 100.95", "1.7 1.7", "GND") + smd("B", "110 100.95", "1.7 1.7", "GND2", "B.Cu")
    spans = {"GND": (0.0, 0.0), "GND2": (0.0, 0.0)}
    assert judged(TWO_FACES.format(thick=0.4, items=items), spans) == []


NPTH = (
    '  (footprint "x:H" (layer "F.Cu") (at 112.5 107.5)\n'
    '    (pad "" np_thru_hole circle (at 0 0) (size 2 2) (drill 2) (layers "*.Cu")))\n'
)


def test_a_hole_with_no_plating_is_a_wall_between_the_faces():
    """HV's pad on F.Cu and GND's right under it on B.Cu, both to x 110.85, and a hole with no plating,
    2 mm across at x 112.5 (from x 111.5): the way through it is at least 0.65 + 1.6 + 0.65 = 2.9 mm,
    under 3 mm. The hole is drawn as 16 sides round it, so the bound read lies from 2.9 - 2 x
    (1 / cos(pi / 16) - 1) = 2.8608 to 2.9 mm. A hole with no plating is no copper: on 1 face it does
    not cross the gap."""
    text = BARREL.format(NPTH).replace(
        '"x:GNDPAD" (layer "B.Cu") (at 115 107.5)', '"x:GNDPAD" (layer "B.Cu") (at 110 107.5)'
    )
    assert '"x:GNDPAD" (layer "B.Cu") (at 110 107.5)' in text
    lines = _faces_lines(text)
    assert len(lines) == 1 and "round the board's edge or through a hole" in lines[0], lines
    read = float(lines[0].split("at least ")[1].split(" mm")[0])
    assert 2.8608 - 0.001 <= read <= 2.9
    one_face = FLOATING.replace(smd("FLOAT", "112.5 107.5", "1.7 1.7", ""), NPTH)
    assert judged(one_face) == []


def test_an_arc_on_a_line_is_read_as_a_straight_track():
    """An arc whose middle stands on the line from its start to its end is a straight track: 1 polygon,
    the track's capsule."""
    polys = creepage.arc_track((100, 100), (102, 100), (104, 100), 0.5)
    assert polys == [creepage.capsule((100, 100), (104, 100), 0.5)]


def test_an_arc_narrower_than_its_width_is_read_as_a_disc():
    """An arc of radius 0.1 mm and width 0.4 mm: its copper fills a disc of 0.1 + 0.2 = 0.3 mm round its
    centre, and the polygons hold every point of it."""
    polys = creepage.arc_track((100.1, 100), (100, 100.1), (99.9, 100), 0.4)
    for k in range(72):
        for r in (0.0, 0.1, 0.2, 0.29):
            t = math.radians(5 * k)
            assert creepage.nearest(polys, (100 + r * math.cos(t), 100 + r * math.sin(t)))[0] <= 1e-9


def test_a_round_oval_pad_is_read_as_a_circle():
    """An oval pad of equal sides is a circle: 1.7 mm at x 110 reaches x 110 - 0.85 / cos(pi / 16), not
    the 110 - 0.85 of a square."""
    text = FLOATING.replace(
        smd("FLOAT", "112.5 107.5", "1.7 1.7", ""),
        '  (footprint "x:O" (layer "F.Cu") (at 120 107.5)\n'
        '    (pad "1" smd oval (at 0 0) (size 1.7 1.7) (layers "F.Cu") (net "HV")))\n',
    )
    oval = [p for n, p in creepage.read_copper(text).shapes["F.Cu"] if n == "HV"][1]
    assert min(x for x, _ in oval) == pytest.approx(120 - 0.85 / math.cos(math.pi / 16), abs=1e-9)


# ---------------------------------------------------------------- the mutants the rerun left


def test_an_unread_cut_beside_a_pair_that_holds_leaves_it_held():
    """3.3 mm straight, over the 3 mm of leakage, and a cut the check does not measure over the gap: a
    cut only lengthens a way, so the pair holds and no line is printed."""
    cu = copper(5.0)
    cu.cuts = [creepage.Cut(None, "a circle on Edge.Cuts", (111.0, 109.0, 113.0, 110.0))]
    assert creepage.findings(cu, SPANS, creepage.read_pack(MIL), MIL_AI) == []


def test_a_voltage_over_the_last_row_between_the_2_faces_is_not_judged():
    """HV on F.Cu alone and GND on B.Cu alone at 1200 V, over the 1000 V of table 69-I's last row."""
    cu = creepage.Copper(
        layers=["F.Cu", "B.Cu"],
        shapes={"F.Cu": [("HV", square(110, 107.5))], "B.Cu": [("GND", square(115, 107.5))]},
        cuts=[],
    )
    found = creepage.findings(cu, {"HV": (0.0, 1200.0), "GND": (0.0, 0.0)}, creepage.read_pack(MIL), MIL_AI)
    assert [f.line.split(" [")[0] for f in found] == [
        "not judged creepage HV on F.Cu to GND on B.Cu: 1200 V is over 1000 V, the table's last row"
    ]


def test_a_gap_under_the_first_row_of_points_is_not_judged():
    """SLUP419 table 3, page 7: its first row is 63 V, 1.25 mm (degree 2, group III). At 50 V a gap of 1
    mm is under it, and the table says nothing below 63 V."""
    found = ti(apart(1.0), {"HV": (0.0, 50.0), "GND": (0.0, 0.0)})
    assert [f.status for f in found] == ["not judged"]
    assert "1 mm at 50 V, under 63 V, the table's first row, under its 1.25 mm" in found[0].text


@pytest.mark.parametrize(
    ("prims", "named"),
    [
        (" (primitives (gr_poly (pts (xy 0 0) (xy 1 0) (xy 1 1)) (width 0) (fill yes)))", True),
        (" (primitives)", False),
        ("", False),
    ],
)
def test_a_custom_pad_is_named_only_with_primitives(prims, named):
    """A custom pad is read as a square of its anchor's side; 1 primitive or more is copper not read."""
    text = (
        HEAD
        + '  (footprint "x:C" (layer "F.Cu") (at 110 107.5)\n'
        + f'    (pad "1" smd custom (at 0 0) (size 0.5 0.5) (layers "F.Cu") (net "HV"){prims}))\n'
        + smd("GNDPAD", "115 107.5", "1.7 1.7", "GND")
        + ")\n"
    )
    line = (
        "not judged creepage on F.Cu: 1 shape drawn on the copper is not read (a custom pad of x:C at "
        "(110, 107.5))"
    )
    assert [f.line for f in judged(text)] == ([line] if named else [])


def test_a_trapezoid_pad_with_no_delta_is_its_rectangle():
    """A trapezoid pad 1 x 1 mm with no `rect_delta` at x 110 reaches x 110.5; GND's 1 mm pad at x 114
    starts at 113.5: 3 mm, the 3 mm of leakage: no line."""
    text = (
        HEAD
        + '  (footprint "x:T" (layer "F.Cu") (at 110 107.5)\n'
        + '    (pad "1" smd trapezoid (at 0 0) (size 1 1) (layers "F.Cu") (net "HV")))\n'
        + smd("GNDPAD", "114 107.5", "1 1", "GND")
        + ")\n"
    )
    assert judged(text) == []


def test_a_plated_hole_of_a_net_with_a_voltage_is_no_way_between_the_faces():
    """HV's pad on F.Cu, GND's on B.Cu, and a plated pad of MID (0 to 400 V) between them: the way through
    its barrel crosses MID's copper, so it is judged as HV to MID and MID to GND (both fail at 0.65 mm),
    never as a way from HV to GND, and its hole is no wall."""
    joint = (
        '  (footprint "x:TP" (layer "F.Cu") (at 112.5 107.5)\n'
        '    (pad "1" thru_hole circle (at 0 0) (size 2 2) (drill 1) (layers "*.Cu") (net "MID")))\n'
    )
    spans = {**SPANS, "MID": (0.0, 400.0)}
    found = judged(BARREL.format(joint), spans)
    assert not [f.line for f in found if "HV on F.Cu to GND on B.Cu" in f.text]
    assert {f.text.split(" at ")[0] for f in found if f.status == "fail"} == {
        "clearance HV to MID on F.Cu",
        "creepage HV to MID on F.Cu",
        "clearance MID to GND on B.Cu",
        "creepage MID to GND on B.Cu",
    }


# ---------------------------------------------------------------- the mutants of the third rerun

# HV's pad and GND's, 1.7 mm squares 3.7 mm apart on F.Cu: a gap of 2 mm, under the 3 mm of leakage and
# over the 1.5 mm of clearance (table 69-I, page 69-2, 300 to 600 V, condition A, enclosure I), and a
# rectangle 1.1 x 8 mm across the gap, from x 111.3 to 112.4.
ACROSS = (
    HEAD
    + smd("HVPAD", "110 107.5", "1.7 1.7", "HV")
    + smd("GNDPAD", "113.7 107.5", "1.7 1.7", "GND")
    + '  (gr_rect (start 111.3 103.5) (end 112.4 111.5) (layer "{}"))\n'
    + ")\n"
)


@pytest.mark.parametrize("layer", ["F.SilkS", "Dwgs.User", "F.Fab"])
def test_a_shape_on_a_layer_other_than_edge_cuts_is_no_cut(layer):
    """The rectangle on a drawing layer is ink, not a slot: the 2 mm gap fails on creepage, 1 line."""
    found = judged(ACROSS.format(layer))
    assert [f.text.split(" at ")[0] for f in found] == ["creepage HV to GND on F.Cu"]
    assert all(f.status == "fail" for f in found)


def test_the_same_rectangle_on_edge_cuts_is_a_slot():
    """The control: on Edge.Cuts the rectangle is a slot across the straight way, which this pack does
    not hold by a least width, so the 2 mm pair no longer fails."""
    found = judged(ACROSS.format("Edge.Cuts"))
    assert not [f for f in found if f.status == "fail"]
    assert found


# The pads of test_copper_on_the_2_faces_far_enough_from_the_edge_holds (HV on F.Cu, GND on B.Cu, 2 x 1
# mm at (110, 101.5), from y 101 to 102: 1 mm from the edge, 3.6 mm round it), and a line at y 100.8,
# 0.2 mm from both pads: as a wall it would bound the way at 0.2 + 1.6 + 0.2 = 2 mm, under 3 mm.
FACES_LINE = (
    FACES.replace("110 100.8", "110 101.5").removesuffix(")\n")
    + '  (gr_line (start 105 100.8) (end 115 100.8) (layer "{}") (width 0.1))\n)\n'
)


@pytest.mark.parametrize("layer", ["F.SilkS", "B.SilkS", "Dwgs.User"])
def test_a_line_on_a_layer_other_than_edge_cuts_is_no_wall_between_the_faces(layer):
    """The line is ink: the pads stay 3.6 mm round the edge, and no line is printed."""
    assert judged(FACES_LINE.format(layer)) == []


def test_the_same_line_on_edge_cuts_is_a_wall_between_the_faces():
    """The control: on Edge.Cuts the line is a wall 0.2 mm from both pads, and the pair is not judged."""
    found = judged(FACES_LINE.format("Edge.Cuts"))
    assert [f.status for f in found if "HV on F.Cu to GND on B.Cu" in f.text] == ["not judged"]


ONE_VOLT = {"HV": (0.0, 1.0), "GND": (0.0, 0.0)}


def test_1_v_between_2_nets_is_a_voltage_on_every_way():
    """1 V is a voltage: table 69-I's first row (0 to 50 V, condition A, enclosure I, page 69-2) asks
    1.5 mm of each. HV on F.Cu over GND on B.Cu, 0.8 mm apart side by side, with no wall read: not judged
    between the faces. The copper of test_copper_over_copper_on_2_layers_is_not_judged: not judged
    through the laminate. TI at 1 V (no clearance table): the clearance line for the pair."""
    mil = creepage.read_pack(MIL)
    faces = creepage.Copper(
        layers=["F.Cu", "B.Cu"],
        shapes={"F.Cu": [("HV", square(110, 107.5))], "B.Cu": [("GND", square(112.5, 107.5))]},
        cuts=[],
    )
    found = creepage.findings(faces, ONE_VOLT, mil, MIL_AI)
    assert [f.status for f in found if f.text.startswith("creepage HV on F.Cu to GND on B.Cu")] == [
        "not judged"
    ]
    laminate = creepage.Copper(
        layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
        shapes={
            "F.Cu": [("GND", square(115, 107.5)), ("HV", creepage.circle((135, 125), 0.4))],
            "In1.Cu": [("HV", rect(110, 100, 120, 115))],
        },
        cuts=[],
    )
    assert [f.line for f in creepage.findings(laminate, ONE_VOLT, mil, MIL_AI)] == [
        LAMINATE.format("F.Cu", "In1.Cu", "HV on In1.Cu to GND on F.Cu at (114.15, 106.65)")
    ]
    ti_found = creepage.findings(
        copper(5.0), ONE_VOLT, creepage.read_pack(TI), {"pollution_degree": "2", "material_group": "III"}
    )
    assert TI_NO_CLEARANCE.format("F.Cu", "1 pair of nets") in [f.line for f in ti_found]
