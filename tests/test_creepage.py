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


def test_ti_passes_the_slot_and_fails_without_it():
    """Pollution degree 2, group III, 400 V: 4.0 mm. 3.3 mm straight fails; round the 1 mm slot 5.022 mm
    passes."""
    pack = creepage.read_pack(TI)
    cond = {"pollution_degree": "2", "material_group": "III"}
    bare = creepage.findings(copper(5.0), SPANS, pack, cond)
    assert [f.line for f in bare] == [
        "fail creepage HV to GND on F.Cu at (110.85, 106.65): 3.3 mm along the surface at 400 V, at least "
        "4 mm (pollution degree 2, material group III) [SLUP419: table 3, page 7]"
    ]
    assert creepage.findings(copper(5.0, [rect(112, 105, 113, 110)]), SPANS, pack, cond) == []


def test_ti_fails_a_slot_narrower_than_table_7_asks():
    """A slot 0.8 mm wide (x 112.1 to 112.9) on the straight way: SLUP419 table 7, page 11, counts a slot
    from 1.0 mm at pollution degree 2, so the way is crossed, 3.3 mm, under 4.0 mm (table 3, page 7):
    the creepage fails, and so does the slot, on 1 line each."""
    pack = creepage.read_pack(TI)
    cond = {"pollution_degree": "2", "material_group": "III"}
    found = creepage.findings(copper(5.0, [rect(112.1, 105, 112.9, 110)]), SPANS, pack, cond)
    assert [f.line for f in found] == [
        "fail creepage HV to GND on F.Cu at (110.85, 106.65): 3.3 mm along the surface at 400 V, at least "
        "4 mm (pollution degree 2, material group III) [SLUP419: table 3, page 7]",
        "fail slot HV to GND on F.Cu at (112.1, 105): 0.8 mm wide, at least 1 mm to lengthen the way "
        "(pollution degree 2) [SLUP419: table 7 and figure 9, page 11: the least width of a slot cut into a "
        "PCB to increase creepage]",
    ]


def test_ti_between_rows_is_not_judged():
    """200 V between the 63 and 400 V rows: 3.3 mm lies between 1.25 and 4.0 mm."""
    pack = creepage.read_pack(TI)
    spans = {"HV": (0.0, 200.0), "GND": (0.0, 0.0)}
    found = creepage.findings(copper(5.0), spans, pack, {"pollution_degree": "2", "material_group": "III"})
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
