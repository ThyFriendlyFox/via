"""tools/boardrules.py, what was left of roadmap item 6: vias held to a wall, the current of each stretch
of copper, parallel tracks (13.6.3g), and the outline's footprint lines and curves.

Every expected number is worked out by hand in the test's docstring from ECSS-Q-ST-70-12C Rev.1 as the
pack holds it (rules/board/ecss-q-st-70-12c-rev1.json). The model of annex D (D.1.2b, page 183; D.2d,
page 184), with k0 0.0756, k1 0.4375, m0 0.5, m1 0.0301 and c1 1550:

    I = k0 x dT^k1 x (c1 x A)^(m0 x dT^m1)        A = (I / (k0 x dT^k1))^(1 / (m0 x dT^m1)) / c1

On the 1.6 mm boards here the rise is 10 C / 1.2 = 8.3333 C (13.6.2a, page 112; 13.6.4.2b, page 115):
k0 x dT^k1 = 0.0756 x 8.3333^0.4375 = 0.191153, and m0 x dT^m1 = 0.5 x 8.3333^0.0301 = 0.532950.
"""

from __future__ import annotations

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


def board_text(vias: list[tuple[float, float]], extra: str = "", via_kind: str = "") -> str:
    """An 80 x 80 mm board, 1.6 mm, no stackup: /P runs on F.Cu from (110, 110) to (120, 110), then
    through the vias (drill 0.3 mm), and on B.Cu from (120, 110) to (130, 110), each track 3 mm."""
    out = [
        "(kicad_pcb (version 20241229) (general (thickness 1.6))",
        '(layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))',
        '(net 0 "") (net 1 "/P") (net 2 "/Q")',
        '(gr_rect (start 100 100) (end 180 180) (layer "Edge.Cuts"))',
        '(segment (start 110 110) (end 120 110) (width 3) (layer "F.Cu") (net 1))',
        '(segment (start 120 110) (end 130 110) (width 3) (layer "B.Cu") (net 1))',
    ]
    kind = f"{via_kind} " if via_kind else ""
    out += [
        f'(via {kind}(at {x} {y}) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))' for x, y in vias
    ]
    return "\n".join(out) + extra + ")"


MICRO_Q = '(via micro (at 150 150) (size 0.3) (drill 0.1) (layers "F.Cu" "B.Cu") (net 2))'


# ---------------------------------------------------------------- vias


def test_the_pack_gives_a_wall_for_hdi_boards_alone(pack):
    """Table 11-1, page 100: copper thickness core via >= 30 um (polyimide HDI), >= 25 um (high speed
    HDI); table 11-2, page 100: plated through hole >= 25 um. The lesser, 25 um, for HDI boards."""
    wall = pack.current["via_wall"]
    assert wall["um"] == 25 and wall["boards"] == "hdi"
    assert "table 11-1" in wall["where"] and "page 100" in wall["where"]


def test_a_board_with_no_microvia_has_its_vias_not_judged_with_the_clauses_read(pack):
    """No microvia: not HDI (3.2.40 NOTE 1, page 22). The standard states no wall for it, so the line
    names each clause read: 13.6.3f, 7.4.2c, table 7-1, 7.5.3i, tables 11-1 and 11-2, 11.6."""
    board = boardrules.read_board(board_text([(120, 110)]))
    assert not board.hdi
    (found,) = boardrules.via_findings(board, {"/P": 2.0}, pack)
    assert found.status == "not judged"
    assert "board-rules.json" in found.text and "via_wall" in found.text
    for clause in ("13.6.3f, page 114", "7.4.2c NOTE 2", "table 7-1", "7.5.3i", "table 11-2", "3.2.40"):
        assert clause in found.line, clause


def test_a_board_with_a_microvia_is_hdi_and_its_vias_take_25_um(pack):
    """A 0.3 mm drill with a 25 um wall: pi / 4 x (0.3^2 - 0.25^2) = 0.0215984 mm2 (13.6.3f, page 114);
    1550 x 0.0215984 = 33.4776 mils2; 33.4776^0.532950 = 6.4956; 0.191153 x 6.4956 = 1.2416 A a via.
    2 A / 1.2416 = 1.61: 2 vias. 1 via fails, 2 hold. /Q's microvia carries no current: no line."""
    one = boardrules.read_board(board_text([(120, 110)], extra=MICRO_Q))
    assert one.hdi
    (found,) = boardrules.via_findings(one, {"/P": 2.0}, pack)
    assert found.status == "fail"
    assert found.text.startswith("vias /P between F.Cu and B.Cu at (120, 110): 1, limit 2 for 2 A (1.24 A")
    assert f"[{DOC}: 13.6.3f, page 114" in found.line and "table 11-1" in found.line
    two = boardrules.read_board(board_text([(120, 110), (120, 111)], extra=MICRO_Q))
    assert boardrules.via_findings(two, {"/P": 2.0}, pack) == []


def test_a_microvia_with_a_current_is_not_judged(pack):
    """A microvia is copper filled (table 11-1, page 99): its section is no wall, and the pack rates it
    not. /P's own vias are microvias here."""
    board = boardrules.read_board(board_text([(120, 110)], via_kind="micro"))
    (found,) = boardrules.via_findings(board, {"/P": 2.0}, pack)
    assert found.status == "not judged" and "microvia" in found.text
    assert "table 11-1 (1 of 2), microvias plating, page 99" in found.line


def test_the_projects_stated_wall_judges_a_board_with_no_microvia(pack):
    """A wall of 20 um the project states: pi / 4 x (0.3^2 - 0.26^2) = 0.0175929 mm2; 1550 x 0.0175929
    = 27.2690 mils2; 27.2690^0.532950 = exp(0.532950 x 3.30577) = 5.8231; 0.191153 x 5.8231 = 1.1131 A.
    2 A / 1.1131 = 1.80: 2 vias. The source is the project's, after the standard's clauses."""
    wall = boardrules.Wall(20, "the fab's hole wall, its spec rev B, clause 4.2, page 3")
    one = boardrules.read_board(board_text([(120, 110)]))
    (found,) = boardrules.via_findings(one, {"/P": 2.0}, pack, wall)
    assert found.status == "fail"
    assert found.text.startswith("vias /P between F.Cu and B.Cu at (120, 110): 1, limit 2 for 2 A (1.11 A")
    assert "13.6.3f, page 114" in found.source
    assert "board-rules.json: via_wall 20 um: the fab's hole wall, its spec rev B" in found.source
    two = boardrules.read_board(board_text([(120, 110), (120, 111)]))
    assert boardrules.via_findings(two, {"/P": 2.0}, pack, wall) == []


def test_on_an_hdi_board_the_lesser_of_the_2_walls_is_taken(pack):
    """A stated 30 um wall and the pack's 25 um on an HDI board: 25 um, 1.2416 A a via (above)."""
    board = boardrules.read_board(board_text([(120, 110)], extra=MICRO_Q))
    (found,) = boardrules.via_findings(board, {"/P": 2.0}, pack, boardrules.Wall(30, "a test"))
    assert "(1.24 A each" in found.text


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({"pack": "ecss-q-st-70-12c-rev1", "via_wall": {"um": 0, "source": "x"}}, r"via_wall: um: 0 is"),
        ({"pack": "ecss-q-st-70-12c-rev1", "via_wall": {"um": 20}}, r"via_wall: `source` is missing"),
        ({"pack": "ecss-q-st-70-12c-rev1", "via_wall": {"um": 20, "source": ""}}, r"via_wall: source"),
    ],
)
def test_a_stated_wall_with_no_source_or_no_copper_is_refused(tmp_path, data, message):
    (tmp_path / "board-rules.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ratings.Refusal, match=r"board-rules.json: " + message):
        boardrules.read_project_file(tmp_path)


# ---------------------------------------------------------------- the current of each stretch


def pad(ref: str, pin: str, x: float, y: float, net: int, name: str) -> str:
    return (
        f'(footprint "t" (at {x} {y}) (property "Reference" "{ref}") '
        f'(pad "{pin}" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net {net} "{name}")))'
    )


def chain(w1: float, w2: float, extra: str = "") -> str:
    """/V on F.Cu: J1 pin 1 at (110, 110), R1 pin 1 at (130, 110), C1 pin 1 at (150, 110), joined by
    a track from 110 to 130 (`w1` wide) and one from 130 to 150 (`w2`). Pin 2 of each is on /G."""
    out = [
        "(kicad_pcb (version 20241229) (general (thickness 1.6))",
        '(layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))',
        '(net 0 "") (net 1 "/V") (net 2 "/G")',
        '(gr_rect (start 100 100) (end 180 180) (layer "Edge.Cuts"))',
        f'(segment (start 110 110) (end 130 110) (width {w1}) (layer "F.Cu") (net 1))',
        f'(segment (start 130 110) (end 150 110) (width {w2}) (layer "F.Cu") (net 1))',
    ]
    for ref, x in (("J1", 110), ("R1", 130), ("C1", 150)):
        out += [pad(ref, "1", x, 110, 1, "/V"), pad(ref, "2", x, 160, 2, "/G")]
    return "\n".join(out) + extra + ")"


STATED = {"J1.1": 1.0, "R1": 0.6, "C1": 0.4}


def stretches(text: str, stated: dict[str, float]):
    board = boardrules.read_board(text)
    return board, boardrules.stretch_amps(board, stated)


def test_a_source_and_its_loads_on_1_net_are_counted_once_on_each_stretch(pack):
    """J1 pin 1 gives 1 A; R1 draws 0.6 A and C1 0.4 A. The pins' sum is 2 A, each current counted
    twice. From J1 to R1 the track carries what R1 and C1 draw, 0.6 + 0.4 = 1 A; from R1 to C1, 0.4 A.
    1 A asks 0.752 mm on F.Cu (0.75140 mm, test_boardrules.py). 0.4 A: 0.4 / 0.9 = 0.44444 A;
    0.44444 / 0.191153 = 2.32507; 2.32507^(1 / 0.532950) = 4.8704 mils2; / 1550 = 0.0031422 mm2;
    / 0.025 = 0.125687 mm made; min(0.125687 / 0.8, 0.125687 + 0.05) = 0.15711 mm: printed 0.158."""
    board, (per_track, most) = stretches(chain(0.8, 0.2), STATED)
    assert per_track == pytest.approx({0: 1.0, 1: 0.4})
    assert most == pytest.approx({"/V": 1.0})
    assert boardrules.width_findings(board, {"/V": 2.0}, pack, per_track) == []
    board, (per_track, _) = stretches(chain(0.8, 0.15), STATED)
    (found,) = boardrules.width_findings(board, {"/V": 2.0}, pack, per_track)
    assert (
        found.text
        == "track width /V on F.Cu from (130, 110) to (150, 110): 0.15 mm, limit 0.158 mm for 0.4 A"
    )


def test_a_net_with_a_pin_of_no_stated_current_keeps_the_sum(pack):
    """C1 states nothing: Kirchhoff does not close on /V, so each track is held to the sum, 1.6 A."""
    _, (per_track, most) = stretches(chain(0.8, 0.2), {"J1.1": 1.0, "R1": 0.6})
    assert per_track == {} and most == {}


def test_a_stub_to_no_pin_carries_nothing_and_a_loop_carries_half(pack):
    """A stub from C1 to (150, 130) ends at no pin: 0 A. A second path from J1 to C1 on B.Cu through 2
    vias on their pads makes a loop: no track splits the pins, so each carries at most half the 2 A
    sum, 1 A."""
    stub = '(segment (start 150 110) (end 150 130) (width 0.2) (layer "F.Cu") (net 1))'
    _, (per_track, _) = stretches(chain(0.8, 0.2, stub), STATED)
    assert per_track[2] == 0
    loop = (
        '(via (at 110 110) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))'
        '(via (at 150 110) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))'
        '(segment (start 110 110) (end 150 110) (width 0.8) (layer "B.Cu") (net 1))'
    )
    _, (per_track, _) = stretches(chain(0.8, 0.2, loop), STATED)
    assert per_track == pytest.approx({0: 1.0, 1: 1.0, 2: 1.0})


def test_the_gate_reads_the_wall_board_rules_json_states_and_holds_vias_to_half_the_sum(tmp_path):
    """chain() with a via at (120, 110) from the F.Cu track to a B.Cu track. Every pad of /V is
    stated (J1 pin 1 1 A, R1 0.6 A, C1 0.4 A): the via is held to half the 2 A sum, 1 A. Both nets at
    0 V: no gap rule, so kicad-cli is not run. The wall board-rules.json states, 10 um: pi / 4 x
    (0.3^2 - 0.28^2) = 0.0091106 mm2; 1550 x 0.0091106 = 14.1215 mils2; 14.1215^0.532950 = 4.1005;
    0.191153 x 4.1005 = 0.7838 A a via. 1 A / 0.7838 = 1.28: 2 vias, and there is 1."""
    via = (
        '(via (at 120 110) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 1))'
        '(segment (start 120 110) (end 120 130) (width 0.8) (layer "B.Cu") (net 1))'
    )
    (tmp_path / "t.kicad_pcb").write_text(chain(0.8, 0.2, via), encoding="utf-8")
    wall = {"um": 10, "source": "a test's own wall"}
    (tmp_path / "board-rules.json").write_text(
        json.dumps({"pack": "ecss-q-st-70-12c-rev1", "via_wall": wall}), encoding="utf-8"
    )
    stated = {
        "pack": "nasa-eee-inst-002",
        "nets": {name: {"volts": [0, 0], "source": "a test"} for name in ("V", "G")},
        "parts": {key: {"amps": amps, "source": "a test"} for key, amps in STATED.items()},
    }
    (tmp_path / "ratings.json").write_text(json.dumps(stated), encoding="utf-8")

    class Project:
        dir = tmp_path
        pcb = tmp_path / "t.kicad_pcb"

    _, findings, notes = boardrules.judge(Project, tmp_path / "out", cli=None)
    (found,) = [f for f in findings if f.status == "fail"]
    assert found.text.startswith(
        "vias /V between F.Cu and B.Cu at (120, 110): 1, limit 2 for 1 A (0.784 A each"
    )
    assert found.source.endswith("board-rules.json: via_wall 10 um: a test's own wall")
    assert "every pad's current stated: /V" in notes[-1]


# ---------------------------------------------------------------- 13.6.3g: parallel tracks


def pair(width: float, q_y: float, q_end: tuple[float, float] = (130, 0)) -> str:
    """/P on F.Cu from (110, 110) to (130, 110) and /Q from (110, q_y) to (130, q_y), both `width`
    wide; `q_end` (x, y) other than (130, 0) ends /Q elsewhere."""
    end = f"{q_end[0]} {q_end[1] or q_y}"
    return (
        "(kicad_pcb (version 20241229) (general (thickness 1.6))"
        '(layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))'
        '(net 0 "") (net 1 "/P") (net 2 "/Q")'
        '(gr_rect (start 100 100) (end 180 180) (layer "Edge.Cuts"))'
        f'(segment (start 110 110) (end 130 110) (width {width}) (layer "F.Cu") (net 1))'
        f'(segment (start 110 {q_y}) (end {end}) (width {width}) (layer "F.Cu") (net 2)))'
    )


def test_2_parallel_tracks_closer_than_25_mm_are_held_as_1_conductor(pack):
    """13.6.3g, page 114: 1 A on each of 2 tracks 1 mm wide, 4 mm apart, are 2 A on the sum of their
    sections. 2 / 0.9 = 2.2222 A on F.Cu; (2.2222 / 0.191153)^(1 / 0.532950) = 99.787 mils2; / 1550 =
    0.064379 mm2. Each made: max(1 x 0.8, 1 - 0.05) = 0.95 mm (table 7-3, page 45) x 0.025 mm (table
    7-1, page 38) = 0.02375 mm2; the 2: 0.0475 mm2, under 0.064379: fails. Alone, 1 A asks 0.752 mm,
    and each 1 mm track holds. At 1.5 mm: 2 x 1.45 x 0.025 = 0.0725 mm2: holds."""
    board = boardrules.read_board(pair(1.0, 115))
    amps = {"/P": 1.0, "/Q": 1.0}
    assert boardrules.width_findings(board, amps, pack) == []
    (found,) = boardrules.parallel_findings(board, amps, pack)
    assert found.status == "fail"
    assert found.text == (
        "parallel tracks /P and /Q on F.Cu from (110, 110) and (110, 115), 4 mm apart: 0.0475 mm2 as "
        "manufactured, limit 0.06438 mm2 for 2 A"
    )
    assert found.source.startswith(f"{DOC}: 13.6.3g, page 114")
    wide = boardrules.read_board(pair(1.5, 115))
    assert boardrules.parallel_findings(wide, amps, pack) == []


def test_2_parallel_tracks_of_1_net_are_left_to_the_notes(pack):
    """/Q renamed /P: 2 tracks of 1 net side by side are 1 net's copper, whose current the net's own
    count already holds; 13.6.3g between them is named in the notes as not checked."""
    board = boardrules.read_board(pair(1.0, 115).replace("(net 2)))", "(net 1)))"))
    assert boardrules.parallel_findings(board, {"/P": 1.0}, pack) == []
    assert "13.6.3g between 2 tracks of 1 net" in boardrules.NOT_CHECKED


def test_tracks_25_mm_apart_or_not_parallel_are_held_each_alone(pack):
    """/Q at y = 136 with 1 mm tracks: 136 - 110 - 1 = 25 mm apart, not less than 25 mm. /Q turned to
    run from (110, 115) to (110, 135): not parallel to /P."""
    amps = {"/P": 1.0, "/Q": 1.0}
    assert boardrules.parallel_findings(boardrules.read_board(pair(1.0, 136)), amps, pack) == []
    assert boardrules.parallel_findings(boardrules.read_board(pair(1.0, 115, (110, 135))), amps, pack) == []


# ---------------------------------------------------------------- the fab files' second reading


@pytest.mark.parametrize(
    ("fab", "sha"),
    [
        # the pages as fetched again on 2026-11-17: JLCPCB's and OSH Park's bytes differ from the first
        # fetch (their pages are built per request); PCBWay's are the same
        ("jlcpcb-2layer", "1d7569a71a1677525122f60b6548a113b7b9cf9ab5ac2e01931cccc91e4e261c"),
        ("pcbway-standard", "d6623fcf6223e137831cd6b9855d16d7e1e18faa6c9d8fb44fe77ffafe6b6a88"),
        ("oshpark-2layer", "abd76a095e9b9d4c193b09d2d77a800180c105b27f9ee98e0916b954deb6dd4c"),
    ],
)
def test_each_fab_file_names_its_second_reading(fab, sha):
    """A second reader fetched each page again and compared every number of the file with it."""
    text = (ROOT / "rules" / f"{fab}.kicad_dru").read_text(encoding="utf-8")
    assert (
        f"# second_reader: 2026-11-17, every number compared; the page fetched again had SHA256 {sha}" in text
    )


# ---------------------------------------------------------------- the outline


def edge_board(edges: str) -> str:
    return (
        "(kicad_pcb (version 20241229) (general (thickness 1.6))"
        '(layers (0 "F.Cu" signal) (2 "B.Cu" signal) (25 "Edge.Cuts" user))'
        '(net 0 "")' + edges + ")"
    )


def fp_lines(at: str, *points: tuple[float, float]) -> str:
    """A footprint at `at` whose outline is fp_line on Edge.Cuts from point to point and back."""
    pairs = zip(points, points[1:] + points[:1], strict=True)
    body = "".join(
        f'(fp_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (layer "Edge.Cuts"))' for a, b in pairs
    )
    return f'(footprint "outline" (at {at}) (property "Reference" "B1") {body})'


def test_an_outline_drawn_inside_a_footprint_is_the_boards():
    """A footprint at (100, 100) with an 80 x 80 mm square of fp_line: 6400 mm2. Turned 90 degrees, an
    80 x 20 mm one is 1600 mm2."""
    square = fp_lines("100 100", (0, 0), (80, 0), (80, 80), (0, 80))
    assert boardrules.read_board(edge_board(square)).area_mm2 == pytest.approx(6400)
    turned = fp_lines("100 100 90", (0, 0), (80, 0), (80, 20), (0, 20))
    assert boardrules.read_board(edge_board(turned)).area_mm2 == pytest.approx(1600)


def test_a_footprints_circle_on_edge_cuts_is_a_hole_in_the_board():
    """The 80 x 80 mm board with a footprint at (140, 140) holding a circle of 5 mm radius on Edge.Cuts:
    6400 - pi x 5^2 = 6400 - 78.540 = 6321.46 mm2."""
    hole = '(footprint "hole" (at 140 140) (fp_circle (center 0 0) (end 5 0) (layer "Edge.Cuts")))'
    rect = '(gr_rect (start 100 100) (end 180 180) (layer "Edge.Cuts"))'
    assert boardrules.read_board(edge_board(rect + hole)).area_mm2 == pytest.approx(6321.46, abs=0.01)


def test_a_curve_on_edge_cuts_is_followed():
    """The square from (100, 100) to (180, 180) with its top side a cubic curve from (100, 100) to
    (180, 100) through control points (120, 90) and (160, 90). Relative to (100, 100), with h = 10:
    y(t) = 3h t(1 - t) and x(t) = 60t + 60t^2 - 40t^3, so dx = 60 + 120 t(1 - t). The area outside the
    chord is the integral of 3h f (60 + 120 f) over t, with f = t(1 - t): 180h / 6 + 360h / 30 =
    30h + 12h = 420 mm2. The board: 6400 + 420 = 6820 mm2, within the chords' 0.5 mm2."""
    curve = '(gr_curve (pts (xy 100 100) (xy 120 90) (xy 160 90) (xy 180 100)) (layer "Edge.Cuts"))'
    sides = "".join(
        f'(gr_line (start {a}) (end {b}) (layer "Edge.Cuts"))'
        for a, b in (("180 100", "180 180"), ("180 180", "100 180"), ("100 180", "100 100"))
    )
    assert boardrules.read_board(edge_board(curve + sides)).area_mm2 == pytest.approx(6820, abs=0.5)
