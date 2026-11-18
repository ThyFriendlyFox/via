"""The DRC gate on the 3 creepage fixtures of tests/boards/creepage_board.py. Each board holds 2 pin pads,
J1 on HV and J2 on GND, 1.7 mm squares on both faces; `ratings.json` puts HV at 0 to 400 V and GND at 0 V,
so 400 V stands between them (boardrules.between: the most the 2 spans allow).

pass-creepage:      centres 5 mm apart, a gap of 5 - 1.7 = 3.3 mm. MIL-HDBK-454C table 69-I, page 69-2,
                    300 to 600 V, condition A, enclosure I: clearance 1.5 mm, leakage 3 mm. Both hold.
fail-creepage:      centres 3.7 mm apart, a gap of 2 mm: leakage 3 mm fails, clearance 1.5 mm holds. 1 line
                    on each face: F.Cu and B.Cu.
pass-creepage-slot: centres 5 mm apart, 3.3 mm straight, and a slot 1 mm wide and 5 mm long between them.
                    SLUP419 table 3, page 7, pollution degree 2, group III, 400 V: 4.0 mm; table 7, page 11:
                    a slot counts from 1.0 mm. Round the slot: 2 x sqrt(1.15^2 + 1.65^2) + 1 = 5.022 mm.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
sys.path.insert(0, str(ROOT / "tools"))

import creepage  # noqa: E402

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


def test_pass_creepage_passes_strict(tmp_path):
    code, text = say("drc", BOARDS / "pass-creepage", "--out", tmp_path, "--strict")
    assert code == 0, text
    assert "board rules mil-hdbk-454c-g69: 0 fail, 0 not judged" in text


def test_fail_creepage_fails_on_creepage_alone(tmp_path):
    code, text = say("drc", BOARDS / "fail-creepage", "--out", tmp_path, "--strict")
    assert code == 1, text
    assert "0 errors, 0 warnings" in text
    assert "board rules mil-hdbk-454c-g69: 2 fail, 0 not judged" in text
    fails = [line.strip() for line in text.splitlines() if line.strip().startswith("- fail")]
    assert fails == [
        f"- fail creepage /HV to GND on {layer} at (110.85, 106.65): 2 mm along the surface at 400 V, at "
        "least 3 mm (condition A, enclosure I) [MIL-HDBK-454C: guideline 69, 4.1 page 69-1; table 69-I, "
        "leakage distances, page 69-2]"
        for layer in ("F.Cu", "B.Cu")
    ]


def test_pass_creepage_slot_holds_its_creepage_round_its_slot(tmp_path):
    """The creepage holds round the slot; SLUP419 gives no clearance by working voltage (page 7), so each
    face's pair is `not judged` for clearance: the default gate passes with 2 warnings, --strict fails."""
    code, text = say("drc", BOARDS / "pass-creepage-slot", "--out", tmp_path)
    assert code == 0, text
    assert "board rules ti-slup419-creepage: 0 fail, 2 not judged" in text
    assert [line.strip() for line in text.splitlines() if "not judged clearance" in line] == [
        f"- warning: not judged clearance on {layer}: 1 pair of nets with a voltage between them, and "
        "ti-slup419-creepage holds no clearance table [SLUP419: page 7 and table 3, page 7: clearance, "
        "which this note takes from an impulse voltage (table 4 and table 5, page 8), not from the working "
        "voltage]"
        for layer in ("F.Cu", "B.Cu")
    ]
    assert say("drc", BOARDS / "pass-creepage-slot", "--out", tmp_path, "--strict")[0] == 1


MIL_CREEP = "[MIL-HDBK-454C: guideline 69, 4.1 page 69-1; table 69-I, leakage distances, page 69-2]"
MIL_CLEAR = "[MIL-HDBK-454C: guideline 69, 4.1 page 69-1; table 69-I, clearance, page 69-2]"
TI_CREEP = "[SLUP419: table 3, page 7]"
TI_SLOT = (
    "[SLUP419: table 7 and figure 9, page 11: the least width of a slot cut into a PCB to increase creepage]"
)


def fails(text: str) -> list[str]:
    return [line.strip()[2:] for line in text.splitlines() if line.strip().startswith("- fail")]


def test_fail_creepage_clearance_breaks_both_rules_of_the_mil_pack(tmp_path):
    """Centres 3 mm apart: 3 - 1.7 = 1.3 mm, under the 1.5 mm of clearance and the 3 mm of leakage of
    table 69-I, page 69-2 (300 to 600 V, condition A, enclosure I). 2 lines on each face."""
    code, text = say("drc", BOARDS / "fail-creepage-clearance", "--out", tmp_path, "--strict")
    assert code == 1, text
    assert "board rules mil-hdbk-454c-g69: 4 fail, 0 not judged" in text
    at = "/HV to GND on {} at (110.85, 106.65)"
    assert fails(text) == [
        line
        for layer in ("F.Cu", "B.Cu")
        for line in (
            f"fail clearance {at.format(layer)}: 1.3 mm through air at 400 V, at least 1.5 mm (condition A) "
            + MIL_CLEAR,
            f"fail creepage {at.format(layer)}: 1.3 mm along the surface at 400 V, at least 3 mm (condition "
            "A, enclosure I) " + MIL_CREEP,
        )
    ]


def test_fail_creepage_slot_breaks_both_rules_of_the_ti_pack(tmp_path):
    """3.3 mm straight and a slot 0.8 mm wide between: table 7, page 11, counts a slot from 1.0 mm at
    pollution degree 2, so the way crosses it, 3.3 mm, under the 4.0 mm of table 3, page 7, at 400 V.
    The creepage and the slot fail on each face."""
    code, text = say("drc", BOARDS / "fail-creepage-slot", "--out", tmp_path, "--strict")
    assert code == 1, text
    assert "board rules ti-slup419-creepage: 4 fail, 2 not judged" in text  # 2: no clearance table
    assert fails(text) == [
        line
        for layer in ("F.Cu", "B.Cu")
        for line in (
            f"fail creepage /HV to GND on {layer} at (110.85, 106.65): 3.3 mm along the surface at 400 V, at "
            "least 4 mm (pollution degree 2, material group III) " + TI_CREEP,
            f"fail slot /HV to GND on {layer} at (112.1, 105): 0.8 mm wide, at least 1 mm to lengthen the "
            "way (pollution degree 2) " + TI_SLOT,
        )
    ]


def test_the_slot_fixture_holds_its_slot_and_measures_5_022_mm():
    board = next((BOARDS / "pass-creepage-slot").glob("*.kicad_pcb"))
    cu = creepage.read_copper(board.read_text(encoding="utf-8"))
    assert [c.polygon for c in cu.cuts] == [[(112.0, 105.0), (113.0, 105.0), (113.0, 110.0), (112.0, 110.0)]]
    got = creepage.measure(cu, "F.Cu", "/HV", "GND", 10.0, 1.0)  # a label's net: KiCad names it /HV
    assert round(got.clearance, 3) == 3.3
    assert round(got.creepage, 3) == 5.022
