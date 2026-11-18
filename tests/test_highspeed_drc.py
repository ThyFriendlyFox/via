"""The KiCad rules `workcenter highspeed` writes, read by KiCad's own DRC (`workcenter drc --fab <file>`).

KiCad applies `diff_pair_gap` only to nets it reads as a pair (names ending _P/_N or +/-); the command
judges the gap itself (tests/test_highspeed.py).

The pass board passes with them. The width board fails on `track_width` alone: 3 segments a net, 2 nets,
6 violations. The skew board fails on `skew_out_of_range` alone, with KiCad's own count of the 2 lengths:
30.1136 and 32.1136 mm (tests/boards/highspeed_pair.py works them out).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BOARDS = ROOT / "tests" / "boards"
CLI = ROOT / "tools" / "workcenter"

pytestmark = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")


def drc(fixture: str, tmp: Path) -> list[dict]:
    rules = tmp / fixture
    subprocess.run(
        [sys.executable, str(CLI), "highspeed", str(BOARDS / fixture), "--out", str(rules)],
        capture_output=True,
        text=True,
        check=False,
    )
    dru = rules / "highspeed" / "highspeed.kicad_dru"
    assert dru.is_file()
    out = tmp / f"{fixture}-drc"
    proc = subprocess.run(
        [sys.executable, str(CLI), "drc", str(BOARDS / fixture), "--fab", str(dru), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    data = json.loads((out / "drc.json").read_text())
    assert proc.returncode in (0, 1), proc.stdout + proc.stderr
    return data["violations"] + data["unconnected_items"] + data["schematic_parity"]


def test_kicad_reads_the_rules(tmp_path):
    assert drc("pass-highspeed", tmp_path) == []
    width = drc("fail-highspeed-width", tmp_path)
    assert {v["type"] for v in width} == {"track_width"} and len(width) == 6
    # The width board's band is solved at its own 0.31 mm gap: `workcenter highspeed` gave 0.2971 to 0.4368.
    assert all("min width 0.2971 mm; actual 0.2000 mm" in v["description"] for v in width)
    skew = drc("fail-highspeed-skew", tmp_path)
    assert [v["type"] for v in skew] == ["skew_out_of_range"]
    assert "max skew 1.2700 mm" in skew[0]["description"]
    assert "32.1136 mm" in skew[0]["description"] and "30.1136 mm" in skew[0]["description"]
