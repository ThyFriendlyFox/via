"""`workcenter design --route` counts the connections its route left open (user round 1, C;
ROADMAP "Later": a route's open connections counted by the command that routed).

FreeRouting 1.9.0 logs no count, so a route that leaves 1 net open printed `DRC decides` and exited 0;
only a gates run, 20 to 30 minutes later, named the net. The command now reads KiCad's DRC of the board
it wrote (the zone fill's report, or 1 DRC run for a board with no pour): with an unconnected item it
prints the count, the first open net with its 2 ends and the `inspect net` command, and exits 1.

The parser is held to a KiCad 10 report's unconnected item (a user's board of round 1). 3 boards are
routed and skip without FreeRouting: a wall of copper keepout that no net crosses, the same board with a
pour (the count then comes from the fill's report), and the board without the wall.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import kicadgen  # noqa: E402

CLI = ROOT / "tools" / "workcenter"
LIBS = kicadgen.SYMBOL_DIR / "Device.kicad_sym"
JAR = Path("/opt/workcenters/ee/freerouting/freerouting.jar")
needs_engines = pytest.mark.skipif(
    not LIBS.is_file() or shutil.which("kicad-cli") is None or not JAR.is_file() or not shutil.which("java"),
    reason="the KiCad libraries, kicad-cli and FreeRouting are needed",
)

# The first unconnected item of a KiCad 10.0 DRC report (`kicad-cli pcb drc --format json`), from the
# large user's board of round 1, 2026-11-17: J3 pin 1 and R3 pin 1, both on +3V3.
ITEM = {
    "description": "Missing connection between items",
    "items": [
        {"description": "PTH pad 1 [+3V3] of J3", "pos": {"x": 108.9, "y": 103.5}, "uuid": "6b49940e"},
        {"description": "Pad 1 [+3V3] of R3 on F.Cu", "pos": {"x": 106.175, "y": 110.0}, "uuid": "f22a8ae3"},
    ],
    "severity": "error",
    "type": "unconnected_items",
}


def test_the_first_open_net_and_its_two_ends_are_read_from_the_report():
    report = {"violations": [], "unconnected_items": [ITEM, {**ITEM, "items": ITEM["items"][::-1]}]}
    count, first = kicadgen.open_connections(report)
    assert count == 2
    assert first == {
        "net": "+3V3",
        "ends": ["PTH pad 1 [+3V3] of J3 at (108.9, 103.5)", "Pad 1 [+3V3] of R3 on F.Cu at (106.175, 110)"],
    }
    # a local net is written /NAME by KiCad, and `inspect net` takes the name the design gives it
    local = {
        **ITEM,
        "items": [{**i, "description": i["description"].replace("+3V3", "/SDA")} for i in ITEM["items"]],
    }
    assert kicadgen.open_connections({"unconnected_items": [local]})[1]["net"] == "SDA"
    assert kicadgen.open_connections({"violations": [], "unconnected_items": []}) == (0, None)


R0603 = "Resistor_SMD:R_0603_1608Metric"


def walled(wall: bool, pour: bool = False) -> str:
    """R1 and R3 on the left joined by A; R1 and R2 across the board joined by B. With the wall, a copper
    keepout on both faces from the top edge to the bottom between them, B cannot be routed: 1 open
    connection, R1 pad 2 to R2 pad 2. A is 2 pads on the left: routed. `pour`: a pour of net C on B.Cu,
    so the count is read from the zone fill's report and not from a DRC run of its own."""
    keepout = (
        "    d.keepout([(114.0, 99.0), (116.0, 99.0), (116.0, 121.0), (114.0, 121.0)],\n"
        "              layers=('F.Cu', 'B.Cu'), name='wall')\n"
        if wall
        else ""
    )
    return (
        "import sys, uuid\n"
        f"sys.path.insert(0, {str(ROOT / 'tools')!r})\n"
        "import kicadgen\n"
        "def build():\n"
        "    d = kicadgen.Design(name='walled', namespace=uuid.UUID(int=4343),\n"
        "                        outline=(100.0, 100.0, 130.0, 120.0))\n"
        f"    d.add('R1', 'Device:R', '1k', {R0603!r}, sch_at=(30, 30), pcb_at=(105.0, 110.0),\n"
        "          nets={'1': 'A', '2': 'B'})\n"
        f"    d.add('R3', 'Device:R', '1k', {R0603!r}, sch_at=(30, 60), pcb_at=(105.0, 104.0),\n"
        "          nets={'1': 'A', '2': 'C'})\n"
        f"    d.add('R2', 'Device:R', '1k', {R0603!r}, sch_at=(90, 30), pcb_at=(125.0, 110.0),\n"
        "          nets={'1': 'D', '2': 'B'})\n"
        f"{keepout}" + ("    d.zone('C', layers=('B.Cu',))\n" if pour else "") + "    return d\n"
    )


def design(folder: Path, wall: bool, pour: bool = False) -> subprocess.CompletedProcess:
    folder.mkdir()
    (folder / "design.py").write_text(walled(wall, pour), encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(CLI), "design", str(folder / "design.py"), "--route", "--passes", "10"],
        capture_output=True,
        text=True,
        check=False,
    )


@needs_engines
def test_a_route_that_leaves_a_net_open_says_so_and_exits_1(tmp_path):
    proc = design(tmp_path / "wall", wall=True)
    lines = proc.stdout.splitlines()
    assert proc.returncode == 1, proc.stdout
    (said,) = [ln for ln in lines if ln.startswith("  route: ")]
    assert said.startswith("  route: 1 unconnected; first B: "), said
    assert "Pad 2 [/B] of R1" in said and "Pad 2 [/B] of R2" in said, said
    pcb = tmp_path / "wall" / "walled.kicad_pcb"
    assert f"  inspect: workcenter inspect net {pcb} B" in lines, proc.stdout
    assert lines[-1].startswith("design walled red: 1 unconnected."), lines[-1]


@needs_engines
def test_a_board_with_a_pour_counts_from_the_fill_report(tmp_path):
    """The walled board with a pour of C on B.Cu: `design --route` reads the fill's DRC report
    (design.filled). The pour joins nothing across the wall, so B stays open: 1, as on the bare board."""
    proc = design(tmp_path / "poured", wall=True, pour=True)
    assert proc.returncode == 1, proc.stdout
    (said,) = [ln for ln in proc.stdout.splitlines() if ln.startswith("  route: ")]
    assert said.startswith("  route: 1 unconnected; first B: "), said
    assert "Pad 2 [/B] of R1" in said and "Pad 2 [/B] of R2" in said, said


@needs_engines
def test_a_route_that_joins_every_net_says_0_and_exits_0(tmp_path):
    proc = design(tmp_path / "open", wall=False)
    assert proc.returncode == 0, proc.stdout
    assert "  route: 0 unconnected" in proc.stdout.splitlines(), proc.stdout
    summary = subprocess.run(
        [sys.executable, str(CLI), "--json", "design", str(tmp_path / "open" / "design.py"), "--route"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert json.loads(summary.stdout)["route"]["unconnected"] == 0


@pytest.mark.skipif(
    not LIBS.is_file() or shutil.which("kicad-cli") is None,
    reason="the KiCad libraries and kicad-cli are needed",
)
def test_next_counts_an_unrouted_board_as_design_route_does(tmp_path):
    """`next` names the route step on a board generated without --route, and `design --route` prints
    KiCad's count of unconnected items: both say `N unconnected`, and for 1 board N is 1 number. A net of
    k pads and no copper is k - 1 connections to KiCad's DRC. The walled board without the wall and
    without a route: A (R1.1, R3.1) and B (R1.2, R2.2) are 4 pads on 2 nets, 2 unconnected; C and D hold
    1 pad each. The step is done when the route prints `route: 0 unconnected`."""
    folder = tmp_path / "bare"
    folder.mkdir()
    (folder / "design.py").write_text(walled(False), encoding="utf-8")
    made = subprocess.run(
        [sys.executable, str(CLI), "design", str(folder / "design.py")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert made.returncode == 0, made.stdout + made.stderr
    count, _ = kicadgen.open_connections(kicadgen.drc_report(folder / "walled.kicad_pcb"))
    asked = subprocess.run(
        [sys.executable, str(CLI), "--json", "next", str(folder)], capture_output=True, text=True, check=False
    )
    step = json.loads(asked.stdout)
    assert step["next"] == "Route the board before the gates: nets on it have no copper yet.", step
    assert count == 2
    assert step["why"].startswith(f"4 pads on 2 nets have no track, via or pour, {count} unconnected: "), step
    assert "prints `route: 0 unconnected`" in step["done_when"], step


@pytest.mark.skipif(not LIBS.is_file(), reason="the KiCad symbol libraries are not installed")
def test_without_kicad_cli_the_count_is_not_judged_and_the_route_stands(tmp_path, monkeypatch, capsys):
    """No kicad-cli: the route's open connections are printed as not counted, never as 0, and the exit
    code is the route's own. The router is replaced by a summary of 1 segment and no count."""
    import argparse
    import importlib.machinery
    import types

    loader = importlib.machinery.SourceFileLoader("workcenter_cli_route_open", str(CLI))
    cli = types.ModuleType(loader.name)
    cli.__file__ = str(CLI)
    sys.modules[cli.__name__] = cli
    loader.exec_module(cli)
    routed = {"dsn": "d", "ses": "s", "log": "l", "segments": 1, "vias": 0, "unrouted": None}
    monkeypatch.setattr(kicadgen, "route", lambda *_a, **_k: dict(routed))

    def absent(*_a, **_k):
        raise FileNotFoundError("kicad-cli")

    monkeypatch.setattr(kicadgen, "drc_report", absent)
    (tmp_path / "design.py").write_text(walled(False), encoding="utf-8")
    args = argparse.Namespace(
        design=str(tmp_path / "design.py"),
        out=None,
        route=True,
        seed=None,
        rounds=1,
        passes=10,
        timeout=60,
        threads=0,
        order=False,
        json=False,
    )
    code = cli.cmd_design(args)
    lines = capsys.readouterr().out.splitlines()
    assert code == 0, lines
    assert "  route: unconnected not counted: kicad-cli is not installed" in lines, lines
