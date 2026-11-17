"""Tests for the fixed order of a route (ROADMAP item 5, "A routing benchmark and a second router"):
`workcenter design --route --order` routes the poured nets first, then the nets of each fine-pitch
part, then pairs, then the rest, each stage on the copper of the stages before it.

The engine test routes a small board with FreeRouting and skips when it or KiCad is absent.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import kicadgen  # noqa: E402

CLI = ROOT / "tools" / "workcenter"
LIBS = kicadgen.SYMBOL_DIR / "Device.kicad_sym"
JAR = Path("/opt/workcenters/ee/freerouting/freerouting.jar")

needs_libs = pytest.mark.skipif(not LIBS.is_file(), reason="KiCad symbol libraries are not installed")
needs_kicad = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
needs_router = pytest.mark.skipif(
    not JAR.is_file() or shutil.which("java") is None, reason="FreeRouting is not installed"
)

MSOP10 = "Package_SO:MSOP-10_3x3mm_P0.5mm"
TSSOP8 = "Package_SO:TSSOP-8_4.4x3mm_P0.65mm"
HDR4 = "Connector_PinHeader_2.54mm:PinHeader_1x04_P2.54mm_Vertical"


@needs_libs
def test_a_parts_pitch_is_the_least_distance_between_its_pad_centres():
    """MSOP-10_3x3mm_P0.5mm: 0.5 mm, its name's P0.5mm. TSSOP-8_4.4x3mm_P0.65mm: 0.65 mm. A
    1x04 header at 2.54 mm: 2.54 mm."""
    assert kicadgen.pad_pitch(kicadgen.load_footprint(MSOP10)) == pytest.approx(0.5)
    assert kicadgen.pad_pitch(kicadgen.load_footprint(TSSOP8)) == pytest.approx(0.65)
    assert kicadgen.pad_pitch(kicadgen.load_footprint(HDR4)) == pytest.approx(2.54)


def staged_board() -> kicadgen.Design:
    """U1, an MSOP at 0.5 mm, is fine pitch (P4 step 11: 0.5 mm or less); U2, a TSSOP at 0.65 mm, is
    not. GND is poured on B.Cu. Tracks of 0.15 mm at 0.1 mm clearance reach the MSOP's pads."""
    d = kicadgen.Design(
        name="staged",
        namespace=uuid.UUID(int=515),
        outline=(100.0, 100.0, 140.0, 125.0),
        clearance=0.1,
        track_width=0.15,
    )
    u1 = {"1": "GND", "2": "A", "3": "USB_D+", "4": "USB_D-", "5": "B"}
    u2 = {"1": "GND", "2": "A", "3": "USB_D+", "4": "USB_D-", "5": "C", "6": "TX_P", "7": "TX_N", "8": "B"}
    d.add("U1", "Connector_Generic:Conn_01x10", "U1", MSOP10, sch_at=(30, 30), pcb_at=(110.0, 112.0), nets=u1)
    d.add("U2", "Connector_Generic:Conn_01x08", "U2", TSSOP8, sch_at=(60, 30), pcb_at=(122.0, 112.0), nets=u2)
    j1 = {"1": "C", "2": "TX_P", "3": "TX_N", "4": "D"}
    d.add("J1", "Connector_Generic:Conn_01x04", "J1", HDR4, sch_at=(90, 30), pcb_at=(134.0, 108.0), nets=j1)
    d.zone("GND", layers=("B.Cu",))
    return d


@needs_libs
def test_the_stages_are_pours_then_fine_pitch_then_pairs_then_the_rest():
    """GND has a pour: stage 1. U1's other nets with 2 pads or more (A, B, USB_D+, USB_D-; its pins
    6 to 10 have none): stage 2. TX_P and TX_N are a pair by name and not on U1: stage 3. C is left:
    stage 4. D has 1 pad and is routed in no stage."""
    stages = staged_board().route_stages()
    assert stages == [
        ("pours", ["/GND"]),
        ("fan-out", ["/A", "/B", "/USB_D+", "/USB_D-"]),
        ("pairs", ["/TX_N", "/TX_P"]),
        ("rest", ["/C"]),
    ]


@needs_libs
def test_the_dsn_of_a_stage_lists_only_its_nets_and_the_ones_before():
    """Stage 2's network holds GND, A, B, USB_D+ and USB_D-; not TX_P, TX_N or C."""
    d = staged_board()
    dsn = d.dsn(nets={"/GND", "/A", "/B", "/USB_D+", "/USB_D-"})
    network = dsn.split("(network", 1)[1]
    named = sorted(line.split('"')[1] for line in network.splitlines() if line.strip().startswith("(net "))
    assert named == ["/A", "/B", "/GND", "/USB_D+", "/USB_D-"]


def test_order_and_seed_are_refused_together(tmp_path):
    (tmp_path / "design.py").write_text("", encoding="utf-8")
    (tmp_path / "old.kicad_pcb").write_text("", encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "design",
            str(tmp_path / "design.py"),
            "--route",
            "--order",
            "--seed",
            str(tmp_path / "old.kicad_pcb"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "design --order cannot take --seed" in proc.stderr


@needs_libs
@needs_kicad
@needs_router
def test_an_ordered_route_routes_each_stage_and_joins_every_connection(tmp_path):
    """The 4 stages run in order and each names its nets; the board's DRC finds 0 unconnected."""
    pytest.importorskip("pcbnew")
    (tmp_path / "design.py").write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT / 'tests')!r})\n"
        "from test_routeorder import staged_board as build\n",
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", "design", str(tmp_path / "design.py"), "--route", "--order"],
        capture_output=True,
        text=True,
        check=False,
    )
    summary = json.loads(proc.stdout)
    assert proc.returncode == 0, summary
    assert [s["stage"] for s in summary["route"]["stages"]] == ["pours", "fan-out", "pairs", "rest"]
    assert summary["route"]["stages"][2]["nets"] == ["/TX_N", "/TX_P"]
    drc = subprocess.run(
        [sys.executable, str(CLI), "--json", "drc", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    gate = json.loads(drc.stdout)
    assert gate[0]["details"]["counts"]["unconnected_items"]["error"] == 0, gate
