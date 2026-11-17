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
