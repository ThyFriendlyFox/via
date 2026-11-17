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
