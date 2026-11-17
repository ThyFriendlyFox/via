"""The DRC gate on the 2 fixture boards that name ECSS-Q-ST-70-12C Rev.1 in board-rules.json.

Both are the divider of tests/boards/generate.py on an 80 x 80 mm outline, 1.6 mm thick, with no
stackup: KiCad's 35 um on F.Cu and B.Cu. Their ratings.json states VIN 0 to 5.25 V, VOUT 0 to 2.625 V,
GND 0 V, 1 A on J1 pin 1 (VIN) and on J1 pin 3 (GND), 0 A on J1 pin 2 (VOUT).

    gap     every pair is 5.25 V apart at the most, 0 < V <= 10: 250 um as designed on an outer layer
            of Th <= 70 um (table 13-7 (2 of 4), page 130)
    width   1 A on an outer layer of a 1.6 mm board: 1 / 0.9 = 1.1111 A at 10 / 1.2 = 8.3333 C,
            0.017535 mm2, 0.70140 mm on 25 um as manufactured, 0.75140 mm as designed: printed 0.752 mm

pass-board-ecss draws VIN and GND 0.8 mm. fail-board-ecss leaves 1 VIN segment 0.25 mm, and puts a GND
stub on B.Cu whose end stands 103.53 + 0.4 = 103.93 mm, 104.15 - 103.93 = 0.22 mm from J1 pin 1's
1.7 mm pad at x = 105.
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
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
DOC = "ECSS-Q-ST-70-12C Rev.1"

pytestmark = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")


def say(*args: object) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        env=os.environ,
    )
    return proc.returncode, proc.stdout + proc.stderr


def copy(name: str, to: Path) -> Path:
    target = to / name
    shutil.copytree(BOARDS / name, target, ignore=shutil.ignore_patterns("build", "*.kicad_prl"))
    return target


def test_the_board_that_keeps_the_pack_passes_strict(tmp_path):
    code, text = say("drc", BOARDS / "pass-board-ecss", "--out", tmp_path, "--strict")
    assert code == 0, text
    assert "PASS   drc        0 errors, 0 warnings (0 unconnected, 0 parity), " in text
    assert "board rules ecss-q-st-70-12c-rev1: 0 fail, 0 not judged" in text


def test_1_gap_and_1_track_fail_each_with_its_clause_and_nothing_else(tmp_path):
    code, text = say("drc", BOARDS / "fail-board-ecss", "--out", tmp_path)
    assert code == 1, text
    assert "board rules ecss-q-st-70-12c-rev1: 2 fail, 0 not judged" in text
    lines = [
        line.removeprefix("       - ") for line in text.splitlines() if line.startswith("       - fail ")
    ]
    assert len(lines) == 2, text
    gap, width = sorted(lines)
    assert gap.startswith("fail clearance /GND to /VIN on B.Cu at (")
    assert gap.endswith(
        "): 0.22 mm, limit 0.25 mm at 5.25 V [ECSS-Q-ST-70-12C Rev.1: 13.8.2d page 117; table 13-7 (2 of 4), "
        "X,Y external without conformal coating, standard, normal pitch, Th <= 70 um, as-designed, page 130]"
    )
    assert width == (
        "fail track width /VIN on F.Cu from (109, 105) to (109, 103): 0.25 mm, limit 0.752 mm for 1 A "
        f"[{DOC}: 13.6.2a, page 112; 13.6.4.2a, page 114; 13.6.4.2b, page 115; annex D: D.1.2b page 183, "
        "D.2c and D.2d page 184; 7.1.2j, table 7-1, the column for non-plated inner layers, page 38; "
        "7.4.2a and b, table 7-3, page 45]"
    )
    # KiCad's own rules hold the board: the 2 failures are the pack's alone
    assert "0 errors" in text.splitlines()[0]


def test_the_report_names_the_pack_it_held_the_board_to(tmp_path):
    say("drc", BOARDS / "fail-board-ecss", "--out", tmp_path)
    code, text = say("--json", "drc", BOARDS / "fail-board-ecss", "--out", tmp_path)
    assert code == 1
    assert '"pack": "ecss-q-st-70-12c-rev1"' in text
    assert f"board rules: ecss-q-st-70-12c-rev1, {DOC} (30 April 2025)" in text


def test_a_board_without_board_rules_json_is_not_held_to_a_pack(tmp_path):
    board = copy("fail-board-ecss", tmp_path)
    (board / "board-rules.json").unlink()
    code, text = say("drc", board, "--out", tmp_path / "out")
    assert code == 0, text
    assert "board rules" not in text


def test_a_pack_with_no_ratings_json_is_refused_in_1_line(tmp_path):
    board = copy("pass-board-ecss", tmp_path)
    (board / "ratings.json").unlink()
    code, text = say("drc", board, "--out", tmp_path / "out")
    assert code == 1, text
    assert "board rules: not run" in text
    assert "- board-rules.json: the voltage of each net and the current on it come from ratings.json" in text
    assert "Traceback" not in text


@pytest.mark.parametrize(
    ("fab", "broken"),
    [
        # fail-fab-sierra's legend label is stroked 0.10 mm and 0.8 mm high: JLCPCB asks 0.15 mm and
        # 1.0 mm, PCBWay 0.15 mm and 0.8 mm, OSH Park 0.0762 mm. Its via ring is 0.15 mm: JLCPCB asks
        # 0.05 mm, PCBWay 0.15 mm, OSH Park 0.127 mm.
        ("jlcpcb-2layer", ["text_height", "text_thickness"]),
        ("pcbway-standard", ["text_thickness"]),
        ("oshpark-2layer", []),
    ],
)
def test_kicad_reads_each_fab_rule_set_and_fails_on_its_own_rules(fab, broken, tmp_path):
    code, text = say("--json", "drc", BOARDS / "fail-fab-sierra", "--fab", fab, "--out", tmp_path)
    assert code == (1 if broken else 0), text
    (result,) = json.loads(text)
    assert result["status"] == ("fail" if broken else "pass"), text
    found = sorted({v["type"] for v in result["details"]["first"] if f"rule '{fab}: " in v["description"]})
    assert found == broken, text


def test_a_net_with_no_voltage_is_not_judged_and_strict_fails_on_it(tmp_path):
    board = copy("pass-board-ecss", tmp_path)
    stated = (board / "ratings.json").read_text(encoding="utf-8")
    start = stated.index('    "VOUT"')
    end = stated.index("\n", start) + 1
    (board / "ratings.json").write_text(stated[:start] + stated[end:], encoding="utf-8")
    code, text = say("drc", board, "--out", tmp_path / "out")
    assert code == 0, text
    assert "- warning: not judged spacing of /VOUT: ratings.json states no voltage for it" in text
    code, text = say("drc", board, "--out", tmp_path / "out", "--strict")
    assert code == 1, text
    assert "- not judged spacing of /VOUT: ratings.json states no voltage for it" in text
