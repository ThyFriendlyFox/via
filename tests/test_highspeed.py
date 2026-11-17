"""`workcenter highspeed`: the interface rules of a board, from its interfaces.json and rules/interfaces/.

The 4 fixtures are tests/boards/highspeed_pair.py with no fault and with 1 planted in each of 3. Each
names 1 interface, `ti-am57xx-usb2` (TI SPRAAR7J, Table A-2, page 16): 81 to 99 ohm differential, 50 mil
(1.27 mm) of skew, 12000 mil (304.8 mm) of length, and section 2.4 (page 6) for the plane.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import highspeed  # noqa: E402
import xsection  # noqa: E402

BOARDS = ROOT / "tests" / "boards"
SPECS = ROOT / "rules" / "interfaces"


def run(fixture: str, interfaces: list[dict] | None = None) -> highspeed.Report:
    project = BOARDS / fixture
    return highspeed.check(
        project / "pair.kicad_pcb", interfaces or highspeed.read_interfaces(project), xsection.answer
    )


@pytest.fixture(scope="module")
def reports():
    return {
        f: run(f)
        for f in ("pass-highspeed", "fail-highspeed-width", "fail-highspeed-skew", "fail-highspeed-plane")
    }


def test_every_limit_names_its_document():
    """Each limit of each interface file has a document with a URL and a SHA256 and a place in it, or
    says why the documents set none."""
    files = sorted(p for p in SPECS.glob("*.json") if p.name != "constants.json")
    assert [p.stem for p in files] == ["ti-am57xx-usb2", "ti-am57xx-usb3", "usb2", "usb3"]
    for path in files:
        spec = json.loads(path.read_text())
        assert spec["interface"] == path.stem
        for name, limit in spec["limits"].items():
            if "not_stated" in limit:
                continue
            doc = spec["documents"][limit["doc"]]
            assert doc["url"].startswith("https://"), (path.name, name)
            assert doc.get("sha256") or doc.get("zip_sha256"), (path.name, name)
            assert "page" in limit["where"], (path.name, name)


def test_the_stack_under_a_top_track():
    """The fixtures' stackup (kicadgen's 4 layers): F.Cu 0.035 mm on 0.2104 mm of er 4.5 prepreg over
    In1.Cu, which holds the plane. A track on F.Cu is a microstrip: 1 slab, the strip on top of it, air
    above."""
    board = highspeed.read_board((BOARDS / "pass-highspeed" / "pair.kicad_pcb").read_text())
    section, refs = highspeed.section_for(board, "F.Cu")
    assert refs == ["In1.Cu"]
    assert section == {"slabs": [[0.2104, 4.5]], "top_plane": False, "y": 0.2104, "t": 0.035}


def test_track_lengths():
    """Each track of the pass board: 29 mm between 2 ends of sqrt(0.5^2 + 0.245^2) = 0.5568 mm, 30.1136 mm.
    The skew board's USB_D_N steps 1 mm aside and back: 2 mm more, 32.1136 mm."""
    board = highspeed.read_board((BOARDS / "pass-highspeed" / "pair.kicad_pcb").read_text())
    assert highspeed.net_length(board, "/USB_D_P") == pytest.approx(30.1136, abs=1e-4)
    assert highspeed.net_length(board, "/USB_D_N") == pytest.approx(30.1136, abs=1e-4)
    skew = highspeed.read_board((BOARDS / "fail-highspeed-skew" / "pair.kicad_pcb").read_text())
    assert highspeed.net_length(skew, "/USB_D_N") == pytest.approx(32.1136, abs=1e-4)


def test_pass_board_holds_every_rule(reports):
    report = reports["pass-highspeed"]
    assert report.fails() == []
    assert report.not_judged() == []
    assert {f.rule for f in report.findings if f.status == "held"} == {"width", "length", "skew", "plane"}


@pytest.mark.parametrize(
    "fixture, rule",
    [("fail-highspeed-width", "width"), ("fail-highspeed-skew", "skew"), ("fail-highspeed-plane", "plane")],
)
def test_each_fault_fails_its_own_rule_alone(reports, fixture, rule):
    fails = reports[fixture].fails()
    assert fails, fixture
    assert {f.rule for f in fails} == {rule}


def test_width_line(reports):
    """Both tracks are 0.2 mm wide; the solver's narrowest width for 99 ohm at a 0.2 mm gap is wider."""
    fails = reports["fail-highspeed-width"].fails()
    assert len(fails) == 2
    assert "0.2 mm wide" in fails[0].text and "SPRAAR7J" in fails[0].text and "page 16" in fails[0].text


def test_skew_line(reports):
    """32.1136 - 30.1136 = 2 mm of skew against 1.27 mm (50 mil)."""
    (fail,) = reports["fail-highspeed-skew"].fails()
    assert "2 mm" in fail.text and "1.27 mm" in fail.text and "page 16" in fail.text


def test_plane_line(reports):
    """Each track crosses the 1 mm gap between the 2 pours at x = 120 to 121 mm."""
    fails = reports["fail-highspeed-plane"].fails()
    assert len(fails) == 2
    assert all("In1.Cu" in f.text and "section 2.4" in f.text for f in fails)


def test_rules_file_holds_the_limits(reports):
    """The KiCad rules hold the width band the solver gave, the gap band, 304.8 mm and 1.27 mm."""
    report = reports["pass-highspeed"]
    text = report.rules
    band = report.bands["F.Cu"]
    assert f"(min {band['width_min']:.4f}mm)" in text
    assert f"(max {band['width_max']:.4f}mm)" in text
    assert "(constraint diff_pair_gap" in text
    assert "(constraint length (max 304.8000mm))" in text
    assert "(constraint skew (max 1.2700mm))" in text
    assert band["width_min"] < 0.31 < band["width_max"]
    assert band["width_min"] > 0.2


def test_what_the_spec_does_not_state_is_not_judged():
    """USB 2.0 itself names no board skew and no plane; USB 3.x names no band for a board's impedance."""
    nets = ["USB_D_P", "USB_D_N"]
    usb2 = run("pass-highspeed", [{"interface": "usb2", "nets": nets, "gap": 0.2}])
    assert {f.rule for f in usb2.not_judged()} == {"skew", "plane"}
    assert usb2.fails() == []
    usb3 = run("pass-highspeed", [{"interface": "usb3", "nets": nets, "gap": 0.2}])
    assert {f.rule for f in usb3.not_judged()} == {"width", "length", "skew", "plane"}


def test_unknown_interface_and_net_are_refused():
    with pytest.raises(ValueError, match="no interface 'usb9'"):
        run("pass-highspeed", [{"interface": "usb9", "nets": ["USB_D_P", "USB_D_N"]}])
    with pytest.raises(ValueError, match="no net 'D9' on the board"):
        run("pass-highspeed", [{"interface": "usb2", "nets": ["D9", "USB_D_N"]}])


def test_command_line(tmp_path):
    """The command runs the solver under the venv, writes its rules and exits 1 on the skew board."""
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "workcenter"),
            "highspeed",
            str(BOARDS / "fail-highspeed-skew"),
            "--out",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    lines = [ln for ln in proc.stdout.splitlines() if ln.startswith("FAIL")]
    assert len(lines) == 1 and lines[0].startswith("FAIL highspeed.skew")
    assert (tmp_path / "highspeed" / "highspeed.kicad_dru").is_file()
