"""tools/boardrules.py without an engine: the pack of ECSS-Q-ST-70-12C Rev.1, the current model of its
annex D, the spacing of its table 13-7, and the board reader's tracks, vias and copper.

Every expected number is worked out by hand in the test's docstring from the pack's numbers, each of
which names its clause, table and page in rules/board/ecss-q-st-70-12c-rev1.json. The model of annex D
(D.1.2b, page 183; D.2d, page 184), with k0 0.0756, k1 0.4375, m0 0.5, m1 0.0301 and c1 1550:

    I = k0 x dT^k1 x (c1 x A)^(m0 x dT^m1)        A = (I / (k0 x dT^k1))^(1 / (m0 x dT^m1)) / c1
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "rules" / "board" / "ecss-q-st-70-12c-rev1.json"
sys.path.insert(0, str(ROOT / "tools"))
import boardrules  # noqa: E402
import ratings  # noqa: E402

DOC = "ECSS-Q-ST-70-12C Rev.1"


@pytest.fixture(scope="module")
def pack():
    return boardrules.read_pack(PACK)


# ---------------------------------------------------------------- the pack


def test_the_pack_names_its_document_and_every_number_its_place(pack):
    """The pack holds numbers with their clause and page, never the standard's text: its document
    has a URL and a SHA256, and each group of numbers a `where` that names a page."""
    assert pack.name == "ecss-q-st-70-12c-rev1"
    assert pack.document["number"] == DOC
    assert len(pack.document["sha256"]) == 64
    wheres = [row["where"] for row in pack.spacing] + [
        pack.current[k]["where"] for k in ("model", "valid", "thin_board", "copper", "tolerance")
    ]
    assert all("page" in w for w in wheres), wheres


def test_a_pack_with_a_number_and_no_page_is_refused(tmp_path):
    """A spacing row whose `where` names no page is a number with no place, and is refused."""
    data = json.loads(PACK.read_text(encoding="utf-8"))
    data["spacing"][0]["where"] = "table 13-7"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ratings.Refusal, match=r"bad.json: spacing 1: where: name the page"):
        boardrules.read_pack(bad)


@pytest.mark.parametrize(
    ("fab", "minimums"),
    [
        # jlcpcb.com/capabilities/pcb-capabilities: 0.10 / 0.10 mm (1 oz), via 0.15 / 0.25 mm, so a
        # ring of (0.25 - 0.15) / 2 = 0.05 mm, via hole to hole 0.2 mm, 0.2 mm from a routed edge
        (
            "jlcpcb-2layer",
            {
                "min_track_width": 0.1,
                "min_clearance": 0.1,
                "min_through_hole_diameter": 0.15,
                "min_via_annular_width": 0.05,
                "min_hole_to_hole": 0.2,
                "min_copper_edge_clearance": 0.2,
            },
        ),
        # pcbway.com/capabilities.html: trace 0.1 mm, spacing 0.1 mm, drill 0.15 mm, ring 0.15 mm
        (
            "pcbway-standard",
            {
                "min_track_width": 0.1,
                "min_clearance": 0.1,
                "min_through_hole_diameter": 0.15,
                "min_via_annular_width": 0.15,
            },
        ),
        # docs.oshpark.com/services/two-layer: 6 mil trace and space, 10 mil drill, 5 mil ring, 15 mil edge
        (
            "oshpark-2layer",
            {
                "min_track_width": 0.1524,
                "min_clearance": 0.1524,
                "min_through_hole_diameter": 0.254,
                "min_via_annular_width": 0.127,
                "min_copper_edge_clearance": 0.381,
            },
        ),
    ],
)
def test_each_fab_pack_raises_the_board_minimums_it_publishes(fab, minimums):
    import kicadgen

    text = kicadgen.fab_rules(fab).read_text(encoding="utf-8")
    assert kicadgen.fab_minimums(text) == minimums
    assert "ee-workcenter" not in text and "read 2026-11-17" in text


# ---------------------------------------------------------------- annex D


def test_the_annex_worked_example_gives_1_a(pack):
    """D.1.3, page 184: 925 um wide and 25 um thick as manufactured, 5 C of rise, carries 1 A.

    A = 0.925 x 0.025 = 0.023125 mm2; c1 x A = 35.84 mils2
    5^0.4375 = 2.0222; 5^0.0301 = 1.04964, x 0.5 = 0.52482
    35.84^0.52482 = exp(0.52482 x 3.5791) = exp(1.87839) = 6.5432
    I = 0.0756 x 2.0222 x 6.5432 = 1.0002 A
    """
    assert boardrules.amps_for(0.925 * 0.025, 5, pack.current["model"]) == pytest.approx(1.0002, abs=5e-4)


def test_the_annex_worked_example_backwards_gives_its_975_um(pack):
    """D.1.3, page 184: 1 A at 5 C of rise on 35 um copper (25 um as manufactured, table 7-1) asks 925 um
    as manufactured and 975 um as designed (table 7-3).

    1 / (0.0756 x 2.0222) = 6.5411; 6.5411^(1 / 0.52482) = 35.826 mils2; / 1550 = 0.023114 mm2
    0.023114 / 0.025 = 0.92457 mm as manufactured
    table 7-3, 17 < Th <= 60 um: 20 % or at most 50 um; min(0.92457 / 0.8, 0.92457 + 0.05) = 0.97457 mm
    """
    area = boardrules.area_for(1.0, 5, pack.current["model"])
    assert area == pytest.approx(0.023114, rel=1e-4)
    assert area / 0.025 == pytest.approx(0.92457, rel=1e-4)
    assert boardrules.designed_width(area / 0.025, 35, pack) == pytest.approx(0.97457, rel=1e-4)


def test_1_a_on_an_outer_layer_of_a_16_mm_board_asks_0_752_mm(pack):
    """The fixture boards' VIN: 1 A on F.Cu of 35 um, a 1.6 mm board.

    13.6.4.2a, page 114: an outer conductor carries 0.9 of the model: 1 / 0.9 = 1.1111 A
    13.6.4.2b, page 115: a board of 1.5 to 1.8 mm rises 1.2 times: 10 C / 1.2 = 8.3333 C in the model
    8.3333^0.4375 = 2.52844; 0.0756 x 2.52844 = 0.191153; 8.3333^0.0301 = 1.06590, x 0.5 = 0.532950
    1.1111 / 0.191153 = 5.81269; 5.81269^(1 / 0.532950) = 27.179 mils2; / 1550 = 0.017535 mm2
    / 0.025 mm = 0.70140 mm as manufactured; min(0.70140 / 0.8, 0.70140 + 0.05) = 0.75140 mm
    """
    need = boardrules.track_need(pack, 1.0, outer=True, cu_um=35, board_mm=1.6)
    assert need.mm == pytest.approx(0.75140, rel=1e-4)
    assert "13.6.4.2a, page 114" in need.where and "13.6.4.2b, page 115" in need.where


def test_an_inner_layer_is_not_reduced_and_a_thick_board_not_raised(pack):
    """1 A on an inner layer of 35 um, a 2.0 mm board: 10 C of rise and the whole current.

    10^0.4375 = 2.73842; 0.0756 x 2.73842 = 0.207025; 10^0.0301 = 1.07177, x 0.5 = 0.535883
    1 / 0.207025 = 4.83035; 4.83035^(1 / 0.535883) = 18.895 mils2; / 1550 = 0.012191 mm2
    / 0.025 = 0.48762 mm as manufactured; min(0.48762 / 0.8, 0.48762 + 0.05) = 0.53762 mm
    """
    need = boardrules.track_need(pack, 1.0, outer=False, cu_um=35, board_mm=2.0)
    assert need.mm == pytest.approx(0.53762, rel=1e-4)
    assert "13.6.4.2a" not in need.where and "13.6.4.2b" not in need.where


def test_copper_table_7_1_does_not_hold_is_not_judged(pack):
    """Table 7-1, page 38, names 9, 12, 17, 35 and 70 um. 18 um is none of them: no as-manufactured
    thickness, so no width is judged."""
    need = boardrules.track_need(pack, 1.0, outer=True, cu_um=18, board_mm=1.6)
    assert need.mm is None and "18 um" in need.why and "table 7-1" in need.why


def test_over_30_a_is_outside_the_model(pack):
    """D.2c, page 184: the model holds up to 30 A. 30 A on an outer layer is 33.3 A in the model."""
    need = boardrules.track_need(pack, 30.0, outer=True, cu_um=35, board_mm=1.6)
    assert need.mm is None and "D.2c" in need.why


# ---------------------------------------------------------------- table 13-7


@pytest.mark.parametrize(
    ("layers", "cu_um", "volts", "mm"),
    [
        ("outer", 35, 5.25, 0.25),  # 0 < V <= 10, Th <= 70: 250 um (page 130)
        ("outer", 35, 12, 0.35),  # 10 < V <= 30: 350 um
        ("outer", 105, 5, 0.35),  # Th > 70: 350 um
        ("inner", 35, 40, 0.188),  # 17 < Th <= 60, 30 < V <= 50: 188 um (page 131)
        ("inner", 35, 200, 0.25),  # 100 < V <= 500: 1 um/V + 50 um = 250 um, and at least 188 um
        ("inner", 35, 120, 0.188),  # 1 x 120 + 50 = 170 um, under 188 um: 188 um
        ("inner", 15.2, 5, 0.13),  # Th <= 17: 130 um
    ],
)
def test_table_13_7_gives_the_spacing_as_designed(pack, layers, cu_um, volts, mm):
    need = boardrules.spacing_need(pack, layers, cu_um, volts)
    assert need.mm == pytest.approx(mm)
    assert "table 13-7" in need.where


def test_an_outer_conductor_over_30_v_is_not_judged(pack):
    """Table 13-7 (2 of 4), page 130: without coating, not permitted over 30 V but on a connector's
    pads (13.8.4d). The check does not tell a connector's pad, so it says so."""
    need = boardrules.spacing_need(pack, "outer", 35, 31)
    assert need.mm is None and "not permitted above 30 V" in need.why


def test_over_500_v_is_not_judged(pack):
    """13.8.2l, page 119: above 500 V the design is qualified on its own."""
    need = boardrules.spacing_need(pack, "inner", 35, 600)
    assert need.mm is None and "13.8.2l" in need.why


def test_the_voltage_between_2_nets_is_the_most_their_spans_allow():
    """VIN 0 to 5.25 V and VOUT 0 to 2.625 V: 5.25 - 0 = 5.25 V. -12 to 0 V and 0 to 5 V: 17 V."""
    assert boardrules.between((0, 5.25), (0, 2.625)) == 5.25
    assert boardrules.between((-12, 0), (0, 5)) == 17


# ---------------------------------------------------------------- a board


def board_text(vias: list[tuple[float, float]], f_width: float = 3, extra: str = "") -> str:
    """An 80 x 80 mm board, 1.6 mm, no stackup: /P runs on F.Cu from (110, 110) to (120, 110), then
    through the vias, and on B.Cu from (120, 110) to (130, 110)."""
    out = [
        "(kicad_pcb (version 20241229) (general (thickness 1.6))",
        '(layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))',
        '(net 0 "") (net 1 "/P") (net 2 "/Q")',
        '(gr_rect (start 100 100) (end 180 180) (layer "Edge.Cuts"))',
        f'(segment (start 110 110) (end 120 110) (width {f_width}) (layer "F.Cu") (net 1))',
        '(segment (start 120 110) (end 130 110) (width 3) (layer "B.Cu") (net 1))',
    ]
    out += [f'(via (at {x} {y}) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))' for x, y in vias]
    return "\n".join(out) + extra + ")"


def test_the_board_reader_takes_tracks_vias_and_the_outline():
    board = boardrules.read_board(board_text([(120, 110), (120, 111)]))
    assert board.copper == ["F.Cu", "B.Cu"]
    assert board.thickness == 1.6
    assert board.cu_um == {"F.Cu": 35.0, "B.Cu": 35.0} and not board.stated_stackup
    assert board.area_mm2 == 6400
    assert [(t.net, t.layer, t.width) for t in board.tracks] == [("/P", "F.Cu", 3.0), ("/P", "B.Cu", 3.0)]
    assert [(v.net, v.at) for v in board.vias] == [("/P", (120.0, 110.0)), ("/P", (120.0, 111.0))]


def with_wall(pack):
    """The pack with a via's wall of 25 um: table 11-2, page 100, gives it for HDI boards alone, so the
    shipped pack leaves vias not judged. These tests take it to hold the counting."""
    walled = copy.deepcopy(pack)
    walled.current["via_wall"] = {"um": 25, "where": "table 11-2, page 100 (HDI)"}
    return walled


def test_2_a_through_vias_of_0_3_mm_asks_2_of_them(pack):
    """A 0.3 mm drill with a 25 um wall: pi / 4 x (0.3^2 - 0.25^2) = 0.0215984 mm2, a track of that
    section (13.6.3f, page 114). At 8.3333 C (13.6.4.2b): 1550 x 0.0215984 = 33.4776 mils2;
    33.4776^0.532950 = 6.4956; 0.191153 x 6.4956 = 1.2416 A a via. 2 A / 1.2416 = 1.61: 2 vias."""
    walled = with_wall(pack)
    assert boardrules.via_amps(walled, 0.3, board_mm=1.6) == pytest.approx(1.2417, rel=1e-3)
    two = boardrules.read_board(board_text([(120, 110), (120, 111)]))
    assert boardrules.via_findings(two, {"/P": 2.0}, walled) == []
    one = boardrules.read_board(board_text([(120, 110)]))
    (found,) = boardrules.via_findings(one, {"/P": 2.0}, walled)
    assert found.status == "fail"
    assert found.text.startswith("vias /P between F.Cu and B.Cu at (120, 110): 1, limit 2 for 2 A")
    assert f"[{DOC}: 13.6.3f, page 114" in found.line


def test_vias_far_apart_carry_the_current_each_alone(pack):
    """2 vias that join other pieces of copper are not in parallel: each is held to the whole 2 A."""
    walled = with_wall(pack)
    extra = (
        '(segment (start 140 110) (end 150 110) (width 3) (layer "F.Cu") (net 1))'
        '(segment (start 150 110) (end 160 110) (width 3) (layer "B.Cu") (net 1))'
        '(via (at 150 110) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))'
    )
    board = boardrules.read_board(board_text([(120, 110)], extra=extra))
    found = boardrules.via_findings(board, {"/P": 2.0}, walled)
    assert [f.status for f in found] == ["fail", "fail"]


def test_without_a_wall_in_the_pack_vias_are_not_judged(pack):
    board = boardrules.read_board(board_text([(120, 110)]))
    (found,) = boardrules.via_findings(board, {"/P": 2.0}, pack)
    assert found.status == "not judged" and "13.6.3f, page 114" in found.line


def test_a_narrow_track_fails_with_its_clauses(pack):
    """/P carries 2 A: 2.6252 mm on an outer layer of the 1.6 mm board (2 / 0.9 = 2.2222 A in the model,
    99.79 mils2, 0.064379 mm2, 2.5752 mm as manufactured, + 0.05 mm). The F.Cu track is 1 mm."""
    board = boardrules.read_board(board_text([(120, 110), (120, 111)], f_width=1))
    found = boardrules.width_findings(board, {"/P": 2.0}, pack)
    assert [f.status for f in found] == ["fail"]
    assert (
        found[0].text == "track width /P on F.Cu from (110, 110) to (120, 110): 1 mm, limit 2.626 mm for 2 A"
    )
    assert found[0].source.startswith(f"{DOC}: 13.6.2a, page 112; 13.6.4.2a, page 114; 13.6.4.2b, page 115")


def test_a_small_board_is_outside_the_model(pack):
    """13.6.3c, page 113: a board of 75 x 75 mm or less is outside the model. 25 x 20 mm is 500 mm2."""
    text = board_text([(120, 110)]).replace("(end 180 180)", "(end 125 120)")
    found = boardrules.width_findings(boardrules.read_board(text), {"/P": 2.0}, pack)
    assert [f.status for f in found] == ["not judged"]
    assert "500 mm2" in found[0].text and "13.6.3c and d, page 113" in found[0].line


def test_a_net_with_no_current_is_not_judged_and_0_a_holds(pack):
    board = boardrules.read_board(board_text([(120, 110)]))
    assert boardrules.width_findings(board, {"/P": 0.0}, pack) == []
    (found,) = boardrules.width_findings(board, {}, pack)
    assert found.status == "not judged" and "/P" in found.text and "ratings.json" in found.text


Q_TRACK = '(segment (start 110 120) (end 130 120) (width 0.25) (layer "F.Cu") (net 2))'


def test_the_rules_kicad_checks_are_1_for_each_pair_and_layer(pack):
    """2 nets 5.25 V apart on a 2-layer board of 35 um: 1 rule on F.Cu and 1 on B.Cu, each 0.25 mm."""
    board = boardrules.read_board(board_text([(120, 110)], extra=Q_TRACK))
    text, rules, missing = boardrules.clearance_rules(board, {"/P": (0, 5.25), "/Q": (0, 0)}, pack)
    assert missing == []
    assert sorted((r.layer, r.mm, r.volts) for r in rules.values()) == [
        ("B.Cu", 0.25, 5.25),
        ("F.Cu", 0.25, 5.25),
    ]
    assert text.count("(constraint clearance (min 0.25mm))") == 2
    assert "A.NetName == '/P' && B.NetName == '/Q'" in text


def test_a_kicad_violation_of_a_pack_rule_is_1_line_with_its_clause(pack):
    board = boardrules.read_board(board_text([(120, 110)], extra=Q_TRACK))
    _, rules, _ = boardrules.clearance_rules(board, {"/P": (0, 5.25), "/Q": (0, 0)}, pack)
    name = next(n for n, r in rules.items() if r.layer == "B.Cu")
    report = {
        "violations": [
            {
                "type": "clearance",
                "severity": "error",
                "description": f"Clearance violation (rule '{name}' clearance 0.2500 mm; actual 0.2200 mm)",
                "items": [{"pos": {"x": 103.93, "y": 105.0}}],
            },
            {"type": "clearance", "description": "Clearance violation (netclass 'Default' clearance 0.2 mm)"},
        ]
    }
    (found,) = boardrules.clearance_findings(report, rules)
    assert found.text == "clearance /P to /Q on B.Cu at (103.93, 105): 0.22 mm, limit 0.25 mm at 5.25 V"
    assert found.source.startswith(f"{DOC}: 13.8.2d page 117; table 13-7 (2 of 4)")
