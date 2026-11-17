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


def witnesses(rules) -> list[dict]:
    """The violations KiCad reports for each net's witness, as kicad-cli 10 wrote them for an item of
    /VIN: `{"type": "assertion_failure", "description": "Assertion failure (rule 'p read /VIN')"}`."""
    names = sorted({boardrules.witness(r.pack, n) for r in rules.values() for n in r.nets})
    return [{"type": "assertion_failure", "description": f"Assertion failure (rule '{n}')"} for n in names]


def test_the_rule_file_holds_a_witness_for_each_net_that_fails_on_its_every_item(pack):
    board = boardrules.read_board(board_text([(120, 110)], extra=Q_TRACK))
    text, _, _ = boardrules.clearance_rules(board, {"/P": (0, 5.25), "/Q": (0, 0)}, pack)
    assert (
        '(rule "ecss-q-st-70-12c-rev1 reads /P"\n\t(condition "A.NetName == \'/P\'")\n'
        "\t(constraint assertion \"A.NetName != '/P'\"))"
    ) in text
    assert '(rule "ecss-q-st-70-12c-rev1 reads /Q"' in text


def test_a_report_without_a_nets_witness_is_no_pass(pack):
    """KiCad read no rule of /Q: its witness is not in the report, and the run stops."""
    board = boardrules.read_board(board_text([(120, 110)], extra=Q_TRACK))
    _, rules, _ = boardrules.clearance_rules(board, {"/P": (0, 5.25), "/Q": (0, 0)}, pack)
    report = {"violations": witnesses(rules)[:1]}
    with pytest.raises(RuntimeError, match=r"did not read the pack's rules: no violation of \S+ reads /Q$"):
        boardrules.clearance_findings(report, rules)


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
            *witnesses(rules),
        ]
    }
    (found,) = boardrules.clearance_findings(report, rules)
    assert found.text == "clearance /P to /Q on B.Cu at (103.93, 105): 0.22 mm, limit 0.25 mm at 5.25 V"
    assert found.source.startswith(f"{DOC}: 13.8.2d page 117; table 13-7 (2 of 4)")


# ---------------------------------------------------------------- a net name KiCad's rules cannot hold


@pytest.mark.parametrize("name", ["/P'A", '/P"A', "/P\\A", "/P*", "/P?"])
def test_a_net_name_a_kicad_rule_cannot_hold_is_not_judged(pack, name):
    """A rule's condition quotes a net name in '...' inside "...": a quote ends it, a backslash escapes,
    and * and ? match other nets. Such a net gets no rule, and its gaps are not judged."""
    text = board_text([(120, 110)], extra=Q_TRACK).replace('(net 1 "/P")', f"(net 1 {json.dumps(name)})")
    board = boardrules.read_board(text)
    assert name in board.nets
    rule_text, rules, missing = boardrules.clearance_rules(board, {name: (0, 5.25), "/Q": (0, 0)}, pack)
    assert rules == {} and "NetName == '/Q'" not in rule_text
    (found,) = missing
    assert found.status == "not judged"
    assert found.text.startswith(f"spacing of {name}: its name holds ")


def test_2_net_names_that_differ_in_case_alone_are_not_judged(pack):
    """KiCad compares net names in a rule without case: a rule for /p would hold /P too."""
    extra = Q_TRACK + '(segment (start 110 130) (end 130 130) (width 0.25) (layer "F.Cu") (net 3))'
    text = board_text([(120, 110)], extra=extra).replace('(net 2 "/Q")', '(net 2 "/Q") (net 3 "/p")')
    board = boardrules.read_board(text)
    _, rules, missing = boardrules.clearance_rules(board, {"/P": (0, 5), "/p": (0, 0), "/Q": (0, 3)}, pack)
    assert sorted({r.nets for r in rules.values()}) == []
    assert sorted(f.text.split(":")[0] for f in missing) == ["spacing of /P", "spacing of /p"]


# ---------------------------------------------------------------- the current on a net


def test_the_current_on_a_net_is_the_sum_of_the_currents_its_pins_carry(tmp_path):
    """pass-board-ecss with R2 and C1 each stated 0.6 A, both from VOUT to GND: a track of GND or VOUT
    that feeds both carries 0.6 + 0.6 = 1.2 A (Kirchhoff's current law), not the greater of the 2."""
    pcb = (ROOT / "tests" / "boards" / "pass-board-ecss" / "rc_divider.kicad_pcb").read_text(encoding="utf-8")
    net = boardrules.netlist(boardrules.read_board(pcb))
    stated = json.loads(
        (ROOT / "tests" / "boards" / "pass-board-ecss" / "ratings.json").read_text(encoding="utf-8")
    )
    stated["parts"] = {
        "R2": {"amps": 0.6, "source": "a test: R2 from VOUT to GND"},
        "C1": {"amps": 0.6, "source": "a test: C1 from VOUT to GND"},
    }
    (tmp_path / "ratings.json").write_text(json.dumps(stated), encoding="utf-8")
    project = ratings.read_project(tmp_path / "ratings.json", net)
    assert boardrules.net_amps(project, net) == pytest.approx({"/VOUT": 1.2, "/GND": 1.2})


# ---------------------------------------------------------------- the area of the outline


def outline(text: str) -> str:
    """board_text with its 80 x 80 mm rectangle replaced by `text`, on Edge.Cuts."""
    return board_text([(120, 110)]).replace(
        '(gr_rect (start 100 100) (end 180 180) (layer "Edge.Cuts"))', text
    )


def lines(*points: tuple[float, float]) -> str:
    """A closed outline of gr_line from point to point and back to the first."""
    pairs = zip(points, points[1:] + points[:1], strict=True)
    return "".join(
        f'(gr_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (layer "Edge.Cuts"))' for a, b in pairs
    )


L_POINTS = ((100, 100), (180, 100), (180, 120), (120, 120), (120, 180), (100, 180))


def test_an_l_shaped_outline_has_its_own_area_not_its_box(pack):
    """The L of (100,100) (180,100) (180,120) (120,120) (120,180) (100,180): 80 x 20 + 20 x 60
    = 1600 + 1200 = 2800 mm2; its box is 80 x 80 = 6400 mm2. 2800 is not over 75 x 75 = 5625 mm2
    (13.6.3c, page 113), so no width is judged."""
    pts = "".join(f"(xy {x} {y})" for x, y in L_POINTS)
    board = boardrules.read_board(outline(f'(gr_poly (pts {pts}) (layer "Edge.Cuts"))'))
    assert board.area_mm2 == pytest.approx(2800)
    (found,) = boardrules.width_findings(board, {"/P": 2.0}, pack)
    assert found.status == "not judged" and "2800 mm2" in found.text


def test_an_outline_of_lines_is_joined_into_its_polygon():
    """The same L drawn as 6 gr_line, in order, then shuffled with 2 of them drawn backwards: 2800 mm2."""
    assert boardrules.read_board(outline(lines(*L_POINTS))).area_mm2 == pytest.approx(2800)
    p = L_POINTS
    edges = [(p[3], p[4]), (p[1], p[0]), (p[5], p[0]), (p[1], p[2]), (p[5], p[4]), (p[2], p[3])]
    shuffled = "".join(
        f'(gr_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (layer "Edge.Cuts"))' for a, b in edges
    )
    assert boardrules.read_board(outline(shuffled)).area_mm2 == pytest.approx(2800)


def test_a_hole_in_the_outline_is_taken_out_of_its_area():
    """The 80 x 80 mm rectangle less a circle of radius 10 mm: 6400 - pi x 100 = 6085.84 mm2; less a
    rectangle of 10 x 10 mm in place of the circle: 6300 mm2."""
    rect = '(gr_rect (start 100 100) (end 180 180) (layer "Edge.Cuts"))'
    circle = '(gr_circle (center 140 140) (end 150 140) (layer "Edge.Cuts"))'
    assert boardrules.read_board(outline(rect + circle)).area_mm2 == pytest.approx(6085.84, abs=0.01)
    small = '(gr_rect (start 130 130) (end 140 140) (layer "Edge.Cuts"))'
    assert boardrules.read_board(outline(rect + small)).area_mm2 == pytest.approx(6300)


def test_a_rounded_corner_is_an_arc_and_not_its_chord():
    """An 80 x 80 mm square whose corner at (180, 180) is a quarter circle of radius 10 mm: 6400 less
    the corner's 10 x 10 square plus the quarter circle, pi x 100 / 4 = 78.54: 6400 - 100 + 78.54 =
    6378.54 mm2. The chord alone would give 6400 - 50 = 6350 mm2."""
    r = 10 / 2**0.5
    drawn = (
        '(gr_line (start 100 100) (end 180 100) (layer "Edge.Cuts"))'
        '(gr_line (start 180 100) (end 180 170) (layer "Edge.Cuts"))'
        f'(gr_arc (start 180 170) (mid {170 + r} {170 + r}) (end 170 180) (layer "Edge.Cuts"))'
        '(gr_line (start 170 180) (end 100 180) (layer "Edge.Cuts"))'
        '(gr_line (start 100 180) (end 100 100) (layer "Edge.Cuts"))'
    )
    assert boardrules.read_board(outline(drawn)).area_mm2 == pytest.approx(6378.54, abs=0.05)


def test_an_outline_that_does_not_close_has_no_area(pack):
    """5 of the L's 6 lines: no closed outline, so no area, and no width is judged."""
    drawn = lines(*L_POINTS)
    open_l = drawn[: drawn.rindex("(gr_line")]
    board = boardrules.read_board(outline(open_l))
    assert board.area_mm2 is None
    (found,) = boardrules.width_findings(board, {"/P": 2.0}, pack)
    assert found.status == "not judged" and "does not close" in found.text


# ---------------------------------------------------------------- the plating of an outer layer


def test_an_outer_layer_of_70_um_foil_is_95_um_with_its_plating(pack):
    """7.4.2c NOTE 2, page 44: plated copper as designed is 25 um; table 7-3, page 45, and table 7-4,
    page 46: an outer layer's thickness category is basic plus plated copper. 70 + 25 = 95 um, so
    Th > 70 um: table 13-7 (2 of 4), page 130, asks 350 um to 10 V, not 250 um. 35 + 25 = 60 um is
    Th <= 70 um: 250 um. An inner layer of 70 um is not plated: 70 < Th <= 95 is not it, 60 < Th <= 70
    asks 200 um (table 13-7 (3 of 4), page 131)."""
    outer70 = boardrules.spacing_need(pack, "outer", 70, 5)
    assert outer70.mm == pytest.approx(0.35) and "7.4.2c NOTE 2, page 44" in outer70.where
    assert boardrules.spacing_need(pack, "outer", 35, 5).mm == pytest.approx(0.25)
    assert boardrules.spacing_need(pack, "inner", 70, 5).mm == pytest.approx(0.2)


def test_a_track_on_70_um_outer_foil_takes_the_tolerance_of_95_um(pack):
    """1 A on F.Cu of 70 um, a 1.6 mm board. The model as for 35 um: 0.017535 mm2 (test above). Copper
    as manufactured 56 um (table 7-1, page 38): 0.017535 / 0.056 = 0.31312 mm. Th = 70 + 25 = 95 um:
    table 7-3, page 45, 20 % or at most 70 um: min(0.31312 / 0.8, 0.31312 + 0.07) = min(0.39140,
    0.38312) = 0.38312 mm. Without the plating, 50 um: 0.36312 mm."""
    need = boardrules.track_need(pack, 1.0, outer=True, cu_um=70, board_mm=1.6)
    assert need.mm == pytest.approx(0.38312, rel=1e-4)
    assert "7.4.2c NOTE 2, page 44" in need.where


# ---------------------------------------------------------------- a project's own pack


def broken(tmp_path: Path, change) -> Path:
    data = json.loads(PACK.read_text(encoding="utf-8"))
    change(data)
    path = tmp_path / "own.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda d: d["current"]["thin_board"].pop("rise_factor"),
            r"current: thin_board: `rise_factor` is missing",
        ),
        (
            lambda d: d["current"]["thin_board"].update(rise_factor=0),
            r"current: thin_board: rise_factor: 0 is",
        ),
        (lambda d: d["current"]["tolerance"].pop("rows"), r"current: tolerance: `rows` is missing"),
        (lambda d: d["current"]["tolerance"].update(rows=[[17]]), r"current: tolerance: rows 1: \[up to"),
        (lambda d: d["current"]["tolerance"].update(share=1), r"current: tolerance: share: 1 is"),
        (lambda d: d["current"]["copper"].update(rows=[[35]]), r"current: copper: rows 1: \[designed"),
        (lambda d: d["current"]["copper"].update(rows=[]), r"current: copper: rows: a list of rows"),
        (lambda d: d["current"]["valid"].pop("area_over_mm2"), r"current: valid: `area_over_mm2` is missing"),
        (lambda d: d["current"].update(outer_share=0), r"current: outer_share: 0 is"),
        (lambda d: d["current"].update(outer_share="0.9"), r"current: outer_share: '0.9' is no number"),
        (lambda d: d["current"].update(outer_share=1.5), r"current: outer_share: 1.5 is over 1"),
        (lambda d: d["current"].update(rise_c=-10), r"current: rise_c: -10 is"),
        (lambda d: d["current"]["model"].update(c1=0), r"current: model: c1: 0 is"),
        (
            lambda d: d["current"].update(via_wall={"um": 0, "where": "page 1"}),
            r"current: via_wall: um: 0 is",
        ),
        (lambda d: d["spacing"][0].update(steps=[]), r"spacing 1: steps: a list of steps"),
        (lambda d: d.pop("plating"), r"`plating` is missing"),
        (lambda d: d["plating"].update(um=-1), r"plating: um: -1 is under 0"),
    ],
)
def test_a_pack_of_the_projects_own_is_refused_at_the_place_it_is_wrong(tmp_path, change, message):
    """A pack may be a project's own file: each key the check reads later is held here, so a wrong one
    is a refusal that names the file and the place, never a traceback."""
    with pytest.raises(ratings.Refusal, match=r"own\.json: " + message):
        boardrules.read_pack(broken(tmp_path, change))


# ---------------------------------------------------------------- each boundary of the pack


def test_a_track_just_under_its_limit_fails_and_one_at_it_holds(pack):
    """1 A on F.Cu of the 1.6 mm board asks 0.75140 mm (test above): 0.751 mm fails, 0.7515 mm holds."""
    under = boardrules.read_board(board_text([(120, 110), (120, 111)], f_width=0.751))
    (found,) = boardrules.width_findings(under, {"/P": 1.0}, pack)
    assert found.status == "fail" and "0.751 mm, limit 0.752 mm for 1 A" in found.text
    at = boardrules.read_board(board_text([(120, 110), (120, 111)], f_width=0.7515))
    assert boardrules.width_findings(at, {"/P": 1.0}, pack) == []


@pytest.mark.parametrize(
    ("layers", "cu_um", "volts", "mm"),
    [
        ("outer", 35, 10, 0.25),  # 0 < V <= 10: 250 um (table 13-7 (2 of 4), page 130)
        ("outer", 35, 10.001, 0.35),  # 10 < V <= 30: 350 um
        ("outer", 35, 30, 0.35),
        ("outer", 35, 30.001, None),  # not permitted above 30 V
        ("inner", 35, 500, 0.55),  # 1 x 500 + 50 = 550 um (table 13-7 (3 of 4), page 131)
        ("inner", 35, 500.5, None),  # 13.8.2l, page 119: above 500 V
        ("inner", 17, 5, 0.13),  # Th <= 17: 130 um
        ("inner", 17.001, 5, 0.15),  # 17 < Th <= 60: 150 um
        ("inner", 60, 5, 0.15),
        ("inner", 60.001, 5, 0.2),  # 60 < Th <= 70: 200 um
        ("inner", 95, 5, 0.3),  # 70 < Th <= 95: 300 um
        ("inner", 95.001, 5, None),  # over every inner row
    ],
)
def test_table_13_7_on_each_side_of_each_step(pack, layers, cu_um, volts, mm):
    assert boardrules.spacing_need(pack, layers, cu_um, volts).mm == (
        None if mm is None else pytest.approx(mm)
    )


def test_just_over_500_v_is_not_judged_for_13_8_2l(pack):
    """13.8.2l, page 119: 500.5 V is above 500 V, and the reason names that clause."""
    need = boardrules.spacing_need(pack, "inner", 35, 500.5)
    assert need.mm is None and need.why.startswith("500.5 V is over 500 V: 13.8.2l, page 119")


def test_the_rows_of_a_pack_hold_in_any_order(pack):
    """The inner rows turned round: 17 um is still Th <= 17 (130 um), and not 17 < Th <= 60."""
    turned = copy.deepcopy(pack)
    turned.spacing = list(reversed(turned.spacing))
    assert boardrules.spacing_need(turned, "inner", 17, 5).mm == pytest.approx(0.13)
    assert boardrules.spacing_need(turned, "inner", 60, 5).mm == pytest.approx(0.15)


@pytest.mark.parametrize(
    ("cu_um", "drawn"),
    [
        (17, 1.03),  # Th <= 17: 20 % or at most 30 um: min(1 / 0.8, 1 + 0.03) = 1.03
        (17.001, 1.05),  # 17 < Th <= 60: at most 50 um
        (95, 1.07),  # 70 < Th <= 95: at most 70 um
        (95.001, None),  # over every row of table 7-3
    ],
)
def test_table_7_3_on_each_side_of_each_row(pack, cu_um, drawn):
    """1 mm as manufactured, drawn wider by table 7-3, page 45."""
    got = boardrules.designed_width(1.0, cu_um, pack)
    assert got == (None if drawn is None else pytest.approx(drawn))


@pytest.mark.parametrize(
    ("end", "thickness", "judged"),
    [
        ("(end 175 175)", 1.6, False),  # 75 x 75 = 5625 mm2: not over it (13.6.3c, page 113)
        ("(end 175.01 175)", 1.6, True),  # 75.01 x 75 = 5625.75 mm2
        ("(end 180 180)", 1.5, False),  # 1.5 mm: not thicker than it (13.6.3d, page 113)
        ("(end 180 180)", 1.51, True),
    ],
)
def test_the_model_holds_only_over_its_area_and_its_thickness(pack, end, thickness, judged):
    text = board_text([(120, 110)], f_width=3).replace("(end 180 180)", end)
    text = text.replace("(thickness 1.6)", f"(thickness {thickness})")
    found = boardrules.width_findings(boardrules.read_board(text), {"/P": 1.0}, pack)
    assert (found == []) is judged, found


@pytest.mark.parametrize(("board_mm", "rise"), [(1.5, 10), (1.51, 10 / 1.2), (1.8, 10 / 1.2), (1.81, 10)])
def test_a_board_of_1_5_to_1_8_mm_rises_1_2_times(pack, board_mm, rise):
    """13.6.4.2b, page 115: over 1.5 mm and up to 1.8 mm, 10 C / 1.2 = 8.3333 C in the model."""
    assert boardrules._rise(pack, board_mm)[0] == pytest.approx(rise)


def test_a_via_that_joins_copper_on_1_layer_alone_carries_nothing(pack):
    """2 vias at (120, 110) and (120, 111) carry 2 A (test above). A third at (112, 110) touches the
    F.Cu track alone: it is in no path, and no group of 1 is asked to carry 2 A."""
    board = boardrules.read_board(board_text([(120, 110), (120, 111), (112, 110)]))
    assert boardrules.via_findings(board, {"/P": 2.0}, with_wall(pack)) == []


def test_a_kicad_violation_of_a_rule_not_of_the_pack_is_not_its_finding(pack):
    board = boardrules.read_board(board_text([(120, 110)], extra=Q_TRACK))
    _, rules, _ = boardrules.clearance_rules(board, {"/P": (0, 5.25), "/Q": (0, 0)}, pack)
    report = {
        "violations": [
            {
                "type": "clearance",
                "description": "Clearance violation (rule 'own 1' clearance 0.3 mm; actual 0.1 mm)",
            }
        ]
        + witnesses(rules)
    }
    assert boardrules.clearance_findings(report, rules) == []
