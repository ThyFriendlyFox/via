"""The DRC gate on the 3 fixture boards of tests/boards/layout_board.py, whose board-rules.json names the
layout packs ti-slva680a-esd and ti-szza009-emi. Each sum is in the docstring of tests/test_layoutrules.py
for the same fixture."""

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


def test_pass_layout_passes_strict(tmp_path):
    code, text = say("drc", BOARDS / "pass-layout", "--out", tmp_path, "--strict")
    assert code == 0, text
    assert (
        "PASS   drc        0 errors, 0 warnings (0 unconnected, 0 parity), board rules ti-slva680a-esd + "
        "ti-szza009-emi: 0 fail, 0 not judged"
    ) in text


def test_fail_layout_esd_fails_on_its_3_rules_alone(tmp_path):
    code, text = say("drc", BOARDS / "fail-layout-esd", "--out", tmp_path, "--strict")
    assert code == 1, text
    assert (
        "0 errors, 0 warnings (0 unconnected, 0 parity), board rules ti-slva680a-esd: 3 fail, 0 not judged"
        in text
    )
    fails = [line.strip() for line in text.splitlines() if line.strip().startswith("- fail")]
    assert [f.split(":")[0] for f in fails] == [
        "- fail esd J1.1 VBUS",
        "- fail esd J1.2 /DA",
        "- fail esd J1.3 /DB",
    ]
    assert all("[SLVA680A: section " in f for f in fails)


def test_fail_layout_emi_fails_on_its_rule_alone(tmp_path):
    code, text = say("drc", BOARDS / "fail-layout-emi", "--out", tmp_path, "--strict")
    assert code == 1, text
    assert (
        "0 errors, 0 warnings (0 unconnected, 0 parity), board rules ti-szza009-emi: 1 fail, 0 not judged"
        in text
    )
    assert (
        "- fail length to width VBUS on F.Cu from (105.55, 104) to (105.55, 100.312): 3.69 mm by 1.2 mm"
        in text
    )
    assert "[SZZA009: section 2.1.1, page 4" in text
