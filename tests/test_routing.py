"""Tests for the router's inputs and the design command's report: the hole clearance each layer
asks (M79), a previous route as the router's starting wiring (`design --route --seed`), the island
each stitching via ties, and the last line of a red design run (M85). Then what `design --route`
does before it starts the router and when the router does not end: KiCad's ERC and DRC of the
unrouted project (M127, M152, M155), the route's passes and its limit (M128, M147), and a route the
limit stops.

Routing tests skip when FreeRouting is absent; library tests when the KiCad libraries are. A test
that puts a script in the router's place needs neither FreeRouting nor Java.
"""

from __future__ import annotations

import ast
import importlib.machinery
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import types
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import kicadgen  # noqa: E402
from test_designfile import board, design_file  # noqa: E402

CLI = ROOT / "tools" / "workcenter"
LIBS = kicadgen.SYMBOL_DIR / "Device.kicad_sym"
JAR = Path("/opt/workcenters/ee/freerouting/freerouting.jar")

needs_libs = pytest.mark.skipif(not LIBS.is_file(), reason="KiCad symbol libraries are not installed")
needs_kicad = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
needs_router = pytest.mark.skipif(
    not JAR.is_file() or shutil.which("java") is None, reason="FreeRouting is not installed"
)
needs_xvfb = pytest.mark.skipif(shutil.which("xvfb-run") is None, reason="xvfb-run is not installed")

R0402 = "Resistor_SMD:R_0402_1005Metric"
R0603 = "Resistor_SMD:R_0603_1608Metric"
HDR1 = "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical"
SIERRA_INNER = 0.3302  # Sierra's "Minimum Inner Layer Drill-to-Copper Spacing 13 mil"


def run_cli(*args: object, json_out: bool = True, env: dict | None = None) -> tuple[int, object]:
    cmd = [sys.executable, str(CLI), *(["--json"] if json_out else []), *map(str, args)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
    if not json_out:
        return proc.returncode, proc.stdout
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else [])


# ------------------------------------------------------------- hole clearance per layer


def four_layer(fab: str = "sierra-circuits-web") -> kicadgen.Design:
    """Last Hit's stack: In1.Cu a ground plane, In2.Cu routed, 0.6/0.25 mm vias, 0.15 mm clearance."""
    d = kicadgen.Design(
        name="inner",
        namespace=uuid.UUID(int=77),
        outline=(100.0, 100.0, 120.0, 112.0),
        clearance=0.15,
        via_size=0.6,
        via_drill=0.25,
        copper_layers=4,
        plane_layers=("In1.Cu",),
    )
    d.fab = fab
    d.rules = {"min_through_hole_diameter": 0.25}
    return d


def test_hole_clearances_read_the_fabs_layer_rules():
    d = four_layer(fab="")
    assert d.hole_clearances() == {"F.Cu": 0.25, "In1.Cu": 0.25, "In2.Cu": 0.25, "B.Cu": 0.25}
    d.fab = "sierra-circuits-web"
    holes = d.hole_clearances()
    assert holes["In1.Cu"] == holes["In2.Cu"] == SIERRA_INNER and holes["F.Cu"] == holes["B.Cu"] == 0.25
    d.rules["min_hole_clearance"] = 0.4  # the board's own minimum, on every layer
    assert set(d.hole_clearances().values()) == {0.4}
    copper = ["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"]
    text = (
        '(rule "a" (layer outer) (constraint hole_clearance (min 0.3mm)))\n'
        '(rule "b" (layer "In2.Cu") (constraint hole_clearance (min 0.35mm)))\n'
        '(rule "c" (layer inner) (condition "A.NetClass == \'HV\'") (constraint hole_clearance (min 1mm)))\n'
        '(rule "d" (constraint hole_clearance (min 0.5mm)))\n'
    )
    assert kicadgen.fab_layer_minimums(text, "hole_clearance", copper) == [
        (["F.Cu", "B.Cu"], 0.3),
        (["In2.Cu"], 0.35),
    ]


@needs_libs
def test_dsn_grows_drilled_copper_by_each_layers_hole_clearance():
    """FreeRouting 1.9.0 keeps copper clearances only, so a hole's inner-layer rule reaches it as the
    hole's copper grown on that layer: hole/2 + 0.3302 - 0.15 round its centre (M79)."""
    d = four_layer()
    d.add(
        "J1",
        "Connector_Generic:Conn_01x02",
        "J",
        "Connector_PinHeader_1.00mm:PinHeader_1x02_P1.00mm_Vertical",
        sch_at=(20, 20),
        pcb_at=(104.0, 104.0),
        nets={"1": "A", "2": "B"},
    )
    d.add(
        "H1",
        "Mechanical:MountingHole",
        "M2",
        "MountingHole:MountingHole_2.2mm_M2",
        sch_at=(20, 40),
        pcb_at=(114.0, 106.0),
        nets={},
    )
    dsn = d.dsn()
    via = dsn.split('(padstack "Via[0-2]_600:250_um"')[1].split("(attach")[0]
    grown = round((0.25 + 2 * (SIERRA_INNER - 0.15)) * 10000)  # 0.6104 mm
    assert "(circle F.Cu 6000)" in via and f"(circle In2.Cu {grown})" in via and "(circle B.Cu 6000)" in via
    # A 0.85 mm pad round a 0.5 mm hole: its 0.175 mm ring is short of 0.3302 - 0.15 on In2 only.
    pin = next(ps for ps in dsn.split("(padstack ")[1:] if ps.startswith('"Pad_circle_0.85x0.85_TH'))
    assert "(circle F.Cu 8500)" in pin and "(circle In2.Cu 8604)" in pin and "(circle B.Cu 8500)" in pin
    # A non-plated hole: the 0.3 mm edge clearance outside, the 13 mil inside (M33).
    hole = next(ps for ps in dsn.split("(padstack ")[1:] if '"NPTH' not in ps and "2.5x2.5_TH" in ps)
    assert "(circle F.Cu 25000)" in hole and "(circle In2.Cu 25604)" in hole
    # Without the fab every shape is its own copper, as before.
    d.fab = ""
    plain = d.dsn()
    assert "(circle In2.Cu 6000)" in plain and "8604" not in plain and "25604" not in plain


@needs_libs
def test_via_checks_hold_the_inner_hole_clearance():
    """Every path that places a via keeps the inner hole clearance: the hand-via check, the via
    placers (P17) and island stitching. A via whose copper clears an In2 track by 0.155 mm still has
    its hole 0.3302 - 0.0002 mm from it."""
    d = four_layer()
    d.add(
        "J1",
        "Connector_Generic:Conn_01x01",
        "A",
        HDR1,
        sch_at=(20, 20),
        pcb_at=(102.0, 106.0),
        nets={"1": "A"},
    )
    d.track("A", [(102.0, 106.0), (118.0, 106.0)], "In2.Cu")
    boxes = d.pad_boxes()
    edge = 106.0 + 0.125  # the track's edge
    inside = edge + 0.125 + SIERRA_INNER - 0.0002  # the hole 0.2 um short of 13 mil
    outside = edge + 0.125 + SIERRA_INNER + 0.0002
    assert edge + 0.3 + 0.15 < inside  # the copper clearance alone would take it
    assert not d._via_fits(110.0, inside, 0.3, 0.25, "GND", boxes)
    assert d._via_fits(110.0, outside, 0.3, 0.25, "GND", boxes)
    d.via("B", 110.0, inside)
    assert d.check_vias() == ["/B via at (110, 106.58): on a /A track (In2.Cu)"]
    blocked = kicadgen._via_blocker(None, d, [], boxes, "GND", 0.3, ["In2.Cu"], 0.25)
    assert blocked(110.0, inside) and not blocked(110.0, outside)
    # Two vias of different nets: one's hole keeps 13 mil from the other's inner copper.
    d2 = four_layer()
    d2.via("A", 110.0, 106.0)
    gap = 0.125 + SIERRA_INNER + 0.3
    d2.via("B", 110.0 + gap - 0.0002, 106.0)
    assert any("on the /A via" in p for p in d2.check_vias())
    d2.vias[-1] = ("/B", (110.0 + gap + 0.0002, 106.0), 0.6, 0.25)
    assert d2.check_vias() == []
    # A two-layer board keeps the board's 0.25 mm: the copper clearance is the larger rule there.
    d3 = four_layer(fab="")
    d3.copper_layers, d3.plane_layers = 2, ()
    d3.track("A", [(102.0, 106.0), (118.0, 106.0)], "F.Cu")
    assert d3._via_fits(110.0, edge + 0.3 + 0.15 + 0.0002, 0.3, 0.25, "GND", d3.pad_boxes())


def inner_drill_board() -> kicadgen.Design:
    """M79 as a fixture: an In2 track between two pins, and five nets whose top and bottom pads
    stand 0.3 mm either side of it, so the router puts a via right against the track. With the
    copper clearance alone FreeRouting 1.9.0 lands one hole 0.3281 mm from it, under 13 mil."""
    d = four_layer()
    d.power_nets = {"GND": "GND"}
    d.add(
        "J1",
        "Connector_Generic:Conn_01x01",
        "A",
        HDR1,
        sch_at=(20, 20),
        pcb_at=(102.0, 106.0),
        nets={"1": "A"},
    )
    d.add(
        "J2",
        "Connector_Generic:Conn_01x01",
        "A",
        HDR1,
        sch_at=(20, 30),
        pcb_at=(118.0, 106.0),
        nets={"1": "A"},
    )
    d.track("A", [(102.0, 106.0), (118.0, 106.0)], "In2.Cu")
    for i, x in enumerate((105.0, 107.5, 110.0, 112.5, 115.0)):
        d.add(
            f"RT{i}",
            "Device:R",
            "1k",
            R0402,
            sch_at=(40 + 10 * i, 20),
            pcb_at=(x, 106.0 - 0.3 - 0.51),
            pcb_rot=90,
            nets={"1": f"N{i}"},
        )
        d.add(
            f"RB{i}",
            "Device:R",
            "1k",
            R0402,
            sch_at=(40 + 10 * i, 40),
            pcb_at=(x, 106.0 + 0.3 + 0.51),
            pcb_rot=270,
            pcb_layer="B.Cu",
            nets={"1": f"N{i}"},
        )
    d.add(
        "J3",
        "Connector_Generic:Conn_01x01",
        "G",
        HDR1,
        sch_at=(20, 40),
        pcb_at=(102.0, 102.0),
        nets={"1": "GND"},
    )
    d.zone("GND", layers=("In1.Cu",), connect="solid")
    return d


def hole_clearance_errors(project: Path) -> list[dict]:
    code, gates = run_cli("drc", project)
    report = json.loads((project / "build" / "drc.json").read_text(encoding="utf-8"))
    return [v for v in report["violations"] if v["type"] == "hole_clearance"]


@needs_libs
@needs_kicad
@needs_router
def test_router_vias_keep_the_inner_hole_clearance(tmp_path, monkeypatch):
    """The fixture routed twice: with the DSN as it was (the board's own 0.25 mm on every layer) the
    DRC finds a router via inside Sierra's 13 mil; with each layer's hole clearance it finds none."""
    pytest.importorskip("pcbnew")
    old = inner_drill_board()
    with monkeypatch.context() as m:
        m.setattr(kicadgen.Design, "hole_clearances", lambda self: dict.fromkeys(self.copper_names(), 0.25))
        kicadgen.route(old, tmp_path / "old" / "build" / "route", passes=20, timeout=600)
    old.write(tmp_path / "old")
    assert hole_clearance_errors(tmp_path / "old"), "the fixture no longer puts a via inside the rule"
    new = inner_drill_board()
    kicadgen.route(new, tmp_path / "new" / "build" / "route", passes=20, timeout=600)
    new.write(tmp_path / "new")
    assert hole_clearance_errors(tmp_path / "new") == []
    code, gates = run_cli("drc", tmp_path / "new")
    assert code == 0, gates
    gaps = [abs(y - 106.0) - 0.125 - drill / 2 for net, (x, y), size, drill in new.vias if net != "/A"]
    assert gaps and min(gaps) >= SIERRA_INNER - 1e-4, gaps


# ------------------------------------------------------------- a previous route as the seed


def bus_design(r5_at: tuple[float, float]) -> str:
    """Six nets straight across between two headers, and R5 tied to J3 above them."""
    return (
        "import sys, uuid\n"
        f"sys.path.insert(0, {str(ROOT / 'tools')!r})\n"
        "import kicadgen\n"
        "H6 = 'Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical'\n"
        "H2 = 'Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical'\n"
        "def build():\n"
        "    d = kicadgen.Design(name='bus', namespace=uuid.UUID(int=4242),\n"
        "                        outline=(100.0, 100.0, 130.0, 122.0))\n"
        "    pins = {str(i + 1): f'S{i}' for i in range(6)}\n"
        "    d.add('J1', 'Connector_Generic:Conn_01x06', 'L', H6, sch_at=(30, 30),\n"
        "          pcb_at=(103.0, 106.0), nets=pins)\n"
        "    d.add('J2', 'Connector_Generic:Conn_01x06', 'R', H6, sch_at=(90, 30),\n"
        "          pcb_at=(127.0, 106.0), nets=pins)\n"
        "    d.add('J3', 'Connector_Generic:Conn_01x02', 'E', H2, sch_at=(60, 80), pcb_at=(113.73, 101.9),\n"
        "          pcb_rot=90, nets={'1': 'E1', '2': 'E2'})\n"
        f"    d.add('R5', 'Device:R', '1k', {R0603!r}, sch_at=(60, 60), pcb_at={r5_at!r},\n"
        "          nets={'1': 'E1', '2': 'E2'})\n"
        "    return d\n"
    )


@needs_libs
@needs_kicad
@needs_router
def test_design_route_with_a_seed_keeps_the_paths_that_still_fit(tmp_path):
    """Route the bus, move R5 onto the top line's track, route again from the old board: the line
    under R5 is dropped from the seed and rerouted, the other five come back as they were, and every
    net connects."""
    first, second = tmp_path / "v1", tmp_path / "v2"
    for folder, at in ((first, (115.0, 104.45)), (second, (115.0, 106.0))):
        folder.mkdir()
        (folder / "design.py").write_text(bus_design(at), encoding="utf-8")
    code, summary = run_cli("design", first / "design.py", "--route", "--passes", "10")
    assert code == 0, summary
    old = kicadgen.board_copper(first / "bus.kicad_pcb")
    lines = {s[0]: s for s in old["segments"] if s[0].startswith("/S")}
    assert sorted(lines) == [f"/S{i}" for i in range(6)], old["segments"]
    code, summary = run_cli(
        "design", second / "design.py", "--route", "--passes", "10", "--seed", first / "bus.kicad_pcb"
    )
    assert code == 0, summary
    seed = summary["seed"]
    assert seed["tracks"] == len(old["segments"]) and seed["left"] == {"on a pad": 1}, seed
    assert seed["loose"] == [6, 0], seed  # R5's old tracks end where it stood
    assert seed["kept"] >= 6 and seed["kept"] > seed["seeded"][0] / 2, seed
    new = kicadgen.board_copper(second / "bus.kicad_pcb")["segments"]
    for i in range(1, 6):
        assert lines[f"/S{i}"] in new, (lines[f"/S{i}"], new)
    assert lines["/S0"] not in new
    code, gates = run_cli("drc", second)
    assert code == 0, gates
    assert gates[0]["details"]["counts"]["unconnected_items"]["error"] == 0


@needs_libs
def test_seed_wiring_keeps_router_copper_that_still_fits():
    d = kicadgen.Design(name="s", namespace=uuid.UUID(int=5), outline=(100.0, 100.0, 120.0, 110.0))
    d.add("R1", "Device:R", "1k", R0603, sch_at=(20, 20), pcb_at=(105.0, 105.0), nets={"1": "A", "2": "B"})
    d.add("R2", "Device:R", "1k", R0603, sch_at=(20, 40), pcb_at=(115.0, 105.0), nets={"1": "A", "2": "B"})
    d.track("B", [(105.825, 105.0), (105.825, 108.0)], "F.Cu")
    d.keepout([(110.0, 101.0), (112.0, 101.0), (112.0, 102.0), (110.0, 102.0)], layers=("B.Cu",), name="peg")
    copper = {
        "segments": [
            ("/A", (104.175, 105.0), (104.175, 103.0), 0.25, "F.Cu"),  # fits
            ("/A", (104.175, 103.0), (114.175, 103.0), 0.25, "B.Cu"),  # fits
            ("/A", (114.175, 103.0), (114.175, 105.0), 0.25, "F.Cu"),  # fits: R1.1 to R2.1 through two vias
            ("/A", (110.0, 108.0), (112.0, 108.0), 0.25, "F.Cu"),  # fits, but hangs from nothing
            ("/B", (105.825, 105.0), (105.825, 107.0), 0.25, "F.Cu"),  # the hand track's own copper
            ("/A", (106.0, 106.0), (106.0, 109.0), 0.25, "F.Cu"),  # across the hand B track
            ("/A", (115.825, 104.0), (115.825, 106.0), 0.25, "F.Cu"),  # on R2's B pad
            ("/A", (109.0, 101.5), (113.0, 101.5), 0.25, "B.Cu"),  # through the keepout
            ("/A", (101.0, 100.1), (103.0, 100.1), 0.25, "F.Cu"),  # past the edge
            ("/GONE", (101.0, 108.0), (103.0, 108.0), 0.25, "F.Cu"),  # a net the design lost
        ],
        "vias": [
            ("/A", (104.175, 103.0), 0.6, 0.3),  # where two kept tracks meet
            ("/A", (114.175, 103.0), 0.6, 0.3),
            ("/A", (118.0, 108.0), 0.6, 0.3),  # no track ends on it: a stitching via
        ],
        "arcs": 1,
    }
    seed = d.seed_wiring(copper)
    assert [s[2] for s in seed["segments"]] == [
        (104.175, 103.0),
        (114.175, 103.0),
        (114.175, 105.0),
        (112.0, 108.0),
    ]
    assert seed["vias"] == [("/A", (104.175, 103.0), 0.6, 0.3), ("/A", (114.175, 103.0), 0.6, 0.3)]
    assert seed["loose"] == [[("/A", (110.0, 108.0), (112.0, 108.0), 0.25, "F.Cu")], []]
    assert seed["given"] == [10, 3]
    assert seed["left"] == {
        "arc": 1,
        "hand copper": 1,
        "on other copper": 1,
        "on a pad": 1,
        "in a keepout": 1,
        "past the edge": 1,
        "net gone": 1,
        "stitching via": 1,
    }
    # A keepout for footprints only (`copper=False`) does not stop a track.
    d.keepouts[0]["copper"] = False
    assert "in a keepout" not in d.seed_wiring(copper)["left"]
    d.keepouts[0]["copper"] = True
    # Without the second via the chain hangs from R1 only, and every piece of it is loose.
    without = {**copper, "vias": [v for v in copper["vias"] if v[1] != (114.175, 103.0)]}
    assert len(d.seed_wiring(without)["loose"][0]) == 4
    # Held seed copper may be pushed aside but not ripped up; loose ends are the router's to reuse
    # or remove; hand copper stays fixed.
    dsn = d.dsn(seed)
    assert '(wire (path B.Cu 2500 1041750 -1030000 1141750 -1030000) (net "/A") (type shove_fixed))' in dsn
    assert '(via "Via[0-1]_600:300_um" 1041750 -1030000 (net "/A") (type shove_fixed))' in dsn
    assert '(wire (path F.Cu 2500 1100000 -1080000 1120000 -1080000) (net "/A"))' in dsn
    assert '(net "/B") (type fix))' in dsn
    assert d.dsn() == d.dsn({"segments": [], "vias": []})


@needs_libs
@needs_kicad
def test_board_copper_reads_kicadgens_numbered_nets_and_kicad_10s_named_ones(tmp_path):
    d = kicadgen.Design(name="c", namespace=uuid.UUID(int=6), outline=(100.0, 100.0, 120.0, 110.0))
    d.add("R1", "Device:R", "1k", R0603, sch_at=(20, 20), pcb_at=(105.0, 105.0), nets={"1": "A", "2": "B"})
    d.track("A", [(104.175, 105.0), (104.175, 103.0)], "F.Cu")
    d.via("A", 104.175, 103.0)
    d.write(tmp_path)
    pcb = tmp_path / "c.kicad_pcb"
    assert '(net "/A")' not in pcb.read_text(encoding="utf-8")  # kicadgen numbers its nets
    want = {
        "segments": [("/A", (104.175, 105.0), (104.175, 103.0), 0.25, "F.Cu")],
        "vias": [("/A", (104.175, 103.0), 0.6, 0.3)],
        "arcs": 0,
    }
    assert kicadgen.board_copper(pcb) == want
    kicadgen.fill_zones(pcb)  # KiCad saves the board in its own format: nets by name
    assert '(net "/A")' in pcb.read_text(encoding="utf-8")
    assert kicadgen.board_copper(pcb) == want


def test_design_seed_needs_route_and_a_board(tmp_path):
    code, out = run_cli(
        "design", tmp_path / "design.py", "--seed", tmp_path / "old.kicad_pcb", json_out=False
    )
    assert code == 2
    (tmp_path / "design.py").write_text("", encoding="utf-8")
    code, out = run_cli(
        "design", tmp_path / "design.py", "--route", "--seed", tmp_path / "old.kicad_pcb", json_out=False
    )
    assert code == 2


# ------------------------------------------------------------- the design command's report


def walled_divider(extra: str = "") -> str:
    """The divider with a ground pour on both faces and OUT hand-routed round R2's ground pad, so
    R2.2 sits on an island of the top pour that one via ties to the bottom pour."""
    return (
        "import sys, uuid\n"
        f"sys.path.insert(0, {str(ROOT / 'tools')!r})\n"
        "import kicadgen\n"
        "def build():\n"
        "    d = kicadgen.Design(name='gen_divider', namespace=uuid.UUID(int=9),\n"
        "                        outline=(100.0, 100.0, 112.0, 110.0))\n"
        "    d.power_nets = {'GND': 'GND', 'VIN': 'VBUS'}\n"
        "    d.flagged_nets = ['GND', 'VIN']\n"
        f"    r = {R0603!r}\n"
        "    hdr = 'Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical'\n"
        "    d.add('J1', 'Connector_Generic:Conn_01x03', 'IN', hdr, sch_at=(50.8, 50.8),\n"
        "          pcb_at=(103.0, 102.5), nets={'1': 'VIN', '2': 'OUT', '3': 'GND'})\n"
        "    d.add('R1', 'Device:R', '10k', r, sch_at=(71.12, 45.72), pcb_at=(108.5, 102.5),\n"
        "          nets={'1': 'VIN', '2': 'OUT'})\n"
        "    d.add('R2', 'Device:R', '10k', r, sch_at=(71.12, 58.42), pcb_at=(108.5, 106.5),\n"
        "          nets={'1': 'OUT', '2': 'GND'})\n"
        "    d.zone('GND', layers=('F.Cu', 'B.Cu'), connect='solid')\n"
        "    d.track('VIN', [(103.0, 102.5), (107.675, 102.5)], 'F.Cu')\n"
        "    d.track('OUT', [(103.0, 105.04), (106.5, 105.04), (107.675, 106.5)], 'F.Cu')\n"
        "    d.track('OUT', [(109.325, 102.5), (109.325, 103.8), (110.3, 104.6), (110.3, 105.5)], 'F.Cu')\n"
        "    d.track('OUT', [(107.675, 106.5), (108.4, 106.5), (108.4, 105.5), (110.3, 105.5),\n"
        "                    (110.3, 107.5), (108.4, 107.5), (108.4, 106.5)], 'F.Cu')\n"
        f"{extra}"
        "    return d\n"
    )


@needs_libs
@needs_kicad
def test_design_command_names_the_island_each_stitching_via_ties(tmp_path):
    pytest.importorskip("pcbnew")
    (tmp_path / "design.py").write_text(walled_divider(), encoding="utf-8")
    code, summary = run_cli("design", tmp_path / "design.py")
    assert code == 0, summary
    (stitch,) = summary["stitches"]
    assert (stitch["net"], stitch["layer"], stitch["to"], stitch["pads"]) == ("GND", "F.Cu", "B.Cu", ["R2.2"])
    x, y = stitch["at"]
    assert ("GND", (x, y)) in [
        (v[0], v[1]) for v in kicadgen.board_copper(tmp_path / "gen_divider.kicad_pcb")["vias"]
    ]
    code, out = run_cli("design", tmp_path / "design.py", json_out=False)
    assert f"  stitch: GND via at ({x:g}, {y:g}) ties the F.Cu island of R2.2 to B.Cu\n" in out, out
    assert "red" not in out.splitlines()[-1]


@needs_libs
@needs_kicad
def test_a_red_design_run_says_so_on_its_last_line(tmp_path):
    """M85: the files are written, so the verdict is the exit code; the last line says it."""
    pytest.importorskip("pcbnew")
    (tmp_path / "design.py").write_text(
        walled_divider("    d.via('VIN', 109.325, 106.5)\n"), encoding="utf-8"
    )
    code, out = run_cli("design", tmp_path / "design.py", json_out=False)
    assert code == 1
    assert out.splitlines()[-1] == (
        "design gen_divider red: 1 via problem(s). The files are written for inspection only; "
        "a CI regenerate check fails on this exit code (1)."
    ), out
    code, summary = run_cli("design", tmp_path / "design.py")
    assert code == 1 and summary["red"] == ["1 via problem(s)"], summary


@needs_libs
def test_merge_keeps_the_short_link_of_a_t_onto_a_hand_track():
    """Last Hit v0.16's HS_IN: the router left a 0.6 mm hand track mid-length through a 0.0226 mm
    diagonal link. The merge took the link for an echo, both its ends being within 0.03 mm of the
    track, and the wire after it ended off the track's centre line: KiCad called it dangling."""
    d = kicadgen.Design(name="t", namespace=uuid.UUID(int=8), outline=(100.0, 100.0, 112.0, 110.0))
    d.add("R1", "Device:R", "1k", R0603, sch_at=(20, 20), pcb_at=(105.0, 105.0), nets={"1": "A", "2": "B"})
    d.track("A", [(104.0, 103.0), (108.0, 103.0)], "F.Cu", width=0.6)
    ses = """(session t (placement (resolution um 10)
      (component "Resistor_SMD:R_0603_1608Metric" (place R1 10500000 -10500000 front 0)))
      (routes (resolution um 10) (network_out
        (net "/A"
          (wire (path F.Cu 25000 10600000 -10300000 10601600 -10301600 10900000 -10301600))
          (wire (path F.Cu 60000 10500000 -10300000 10700000 -10300000))))))"""
    assert d.merge_ses(ses) == (2, 0)  # the link and the wire after it; the echo of the track is dropped
    ends = sorted((s, e) for n, s, e, _, _ in d.segments)
    assert ((106.0, 103.0), (106.016, 103.016)) in ends
    assert ((104.0, 103.0), (106.0, 103.0)) in ends and ((106.0, 103.0), (108.0, 103.0)) in ends
    # v0.16's +BATT_SYS: a wire that only echoes a hand track, with the same kind of step in it, keeps
    # nothing; kept alone, the step would dangle.
    d.segments = []
    d.track("A", [(104.0, 103.0), (108.0, 103.0)], "F.Cu", width=0.6)
    echo = ses.replace("10900000 -10301600", "10750000 -10301600")
    assert d.merge_ses(echo) == (0, 0)


# ------------------------------------------------------------- the checks before a route
#
# Each design is test_designfile's board with 1 line more. The lines KiCad's DRC and ERC give for
# them are from runs of kicad-cli 10.0.8 on 2026-11-13.

# R2 moved up to 1.2 mm under R1: its courtyard (1.46 mm high) is 0.26 mm into R1's, and the pads,
# 0.95 mm high, keep 0.25 mm, which is over the 0.2 mm clearance.
OVERLAP = "d.parts[2].pcb_at = (110.0, 107.2)"
# A GND track from J1's pad 3 to R2's pad 2 at (110.825, 110), along y = 110 across R2's pad 1, on OUT.
CROSSING = 'd.track("GND", [(104.0, 112.58), (108.0, 110.0), (110.825, 110.0)])'
# An area the design keeps parts out of, over R1.
STRIP = (
    "d.keepout([(108, 104), (112, 104), (112, 108), (108, 108)], "
    'layers=("F.Cu",), name="strip", parts=True, copper=False)'
)
ON_DISK = (
    " The board on disk is the unrouted one. The files are written for inspection only; a CI regenerate "
    "check fails on this exit code (1)."
)
NO_ROUTE_MENDS = "no route mends an ERC or a DRC error (PROCESSES.md P3)"
NOT_STARTED = f" The router was not started: {NO_ROUTE_MENDS}." + ON_DISK
SMALL_BOARD = {
    "passes": {"value": 60, "from": "default"},
    "timeout": {"value": 900, "from": "default"},
    "rounds": {"value": 4, "from": "default"},
}


def design_run(*args: object, env: dict | None = None) -> subprocess.CompletedProcess:
    """`workcenter <args>` as a reader runs it: its exit code, its lines and what it left on stderr."""
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True, check=False, env=env
    )


def route_lines(printed: str) -> list[str]:
    """The lines of a design run that speak of the checks before the route and of the route."""
    kinds = ("  erc: ", "  drc: ", "  route", "  routed: ")
    return [line for line in printed.splitlines() if line.startswith(kinds)]


def stub_router(folder: Path, body: str, display: bool = True) -> dict[str, str]:
    """The environment of a run whose `java` is a shell script of `body` and whose FreeRouting JAR is
    an empty file: `design --route` starts the script where it starts the router. With `display` the
    environment names a display, so no `xvfb-run` stands between the command and the script. Without,
    it names none, and `xvfb-run` keeps its display server's files under `folder`."""
    bin_dir = folder / "bin"
    bin_dir.mkdir(exist_ok=True)
    java = bin_dir / "java"
    java.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    java.chmod(0o755)
    jar = folder / "freerouting.jar"
    jar.write_bytes(b"")
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "FREEROUTING_JAR": str(jar)}
    env.pop("DISPLAY", None)
    return {**env, "DISPLAY": ":0"} if display else {**env, "TMPDIR": str(folder)}


# A router that prints 2 lines, starts a child and waits past any limit of a test.
SLEEPS = 'echo "stub: $*"\necho "pass 1 of many"\nsleep 30 &\necho $! > child.pid\nwait\n'
# A router that ends with exit code 3 and no session.
GIVES_UP = 'echo "stub: $*"\necho "the router gave up" >&2\nexit 3\n'


def runs(pid: int) -> bool:
    """True for a process that runs. One that ended and waits to be collected does not."""
    try:
        return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def left_running(mark: str, pids: tuple[int, ...] = (), wait: float = 5.0) -> list[str]:
    """The processes that still run after `wait` seconds at most: each of `pids`, and each whose command
    line holds `mark`."""
    end = time.monotonic() + wait
    while True:
        found = [f"pid {pid}" for pid in pids if runs(pid)]
        for stat in Path("/proc").glob("[0-9]*/stat"):
            pid = int(stat.parent.name)
            try:
                words = (stat.parent / "cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            line = " ".join(word.decode(errors="replace") for word in words if word)
            if mark in line and pid != os.getpid() and runs(pid):
                found.append(line)
        if not found or time.monotonic() > end:
            return found
        time.sleep(0.1)


@needs_libs
@needs_kicad
def test_two_parts_placed_on_each_other_are_not_routed(tmp_path):
    """M155: 11 courtyards on each other, 4 routes that failed links near them, and the failures read
    as routing problems. KiCad's DRC of the unrouted board names the 2 parts, and the router is not
    started."""
    r = design_run("design", design_file(tmp_path, OVERLAP), "--route")
    assert r.returncode == 1 and r.stderr == "", r.stdout + r.stderr
    assert route_lines(r.stdout) == [
        "  drc: courtyards_overlap: Courtyards overlap: Footprint R1 at (110, 106); "
        "Footprint R2 at (110, 107.2)"
    ]
    assert r.stdout.splitlines()[-1] == "design t red: 1 DRC error(s) on the unrouted board." + NOT_STARTED
    # nothing was written for the router, and it left nothing
    route = tmp_path / "build" / "route"
    assert sorted(f.name for f in route.iterdir()) == ["design.json", "drc.json", "erc.json"]
    # the board on disk is the unrouted one, so the DRC gate names the same error
    assert kicadgen.board_copper(tmp_path / "t.kicad_pcb")["segments"] == []
    code, gates = run_cli("drc", tmp_path)
    assert code == 1, gates
    report = json.loads((tmp_path / "build" / "drc.json").read_text(encoding="utf-8"))
    assert [v["type"] for v in report["violations"] if v["severity"] == "error"] == ["courtyards_overlap"]


@needs_libs
@needs_kicad
def test_a_hand_track_across_another_nets_pad_is_not_routed(tmp_path):
    """M152 and M11: a hand track that shorts 2 nets, found by the DRC a round later. The lines are
    sorted: KiCad's own order of 2 errors, and of the 2 items of 1 error, changed between runs of 1
    board."""
    r = design_run("design", design_file(tmp_path, CROSSING), "--route")
    assert r.returncode == 1 and r.stderr == "", r.stdout + r.stderr
    items = (
        "Pad 1 [/OUT] of R2 on F.Cu at (109.175, 110); Track [GND] on F.Cu, length 2.8250 mm at (108, 110)"
    )
    assert route_lines(r.stdout) == [
        f"  drc: shorting_items: Items shorting two nets (nets /OUT and GND): {items}",
        f"  drc: solder_mask_bridge: Front solder mask aperture bridges items with different nets: {items}",
    ]
    assert r.stdout.splitlines()[-1] == "design t red: 2 DRC error(s) on the unrouted board." + NOT_STARTED
    assert list((tmp_path / "build" / "route").glob("*.ses")) == []
    assert not (tmp_path / "build" / "route" / "freerouting.log").exists()
    # the hand track is on the board that is left, and no track of a router
    assert len(kicadgen.board_copper(tmp_path / "t.kicad_pcb")["segments"]) == 2


@needs_libs
@needs_kicad
def test_a_design_that_is_red_before_the_route_is_not_routed(tmp_path):
    """A part in a keep-out was a `part:` line and exit 1 after the router had run all the same."""
    r = design_run("design", design_file(tmp_path / "routed", STRIP), "--route")
    assert r.returncode == 1 and r.stderr == "", r.stdout + r.stderr
    lines = r.stdout.splitlines()
    assert "  part: R1 (courtyard 108.52..111.48, 105.27..106.73) in keepout 'strip'" in lines
    assert route_lines(r.stdout) == []
    assert lines[-1] == (
        "design t red: 1 part(s) in a keep-out or off the board. The router was not started: the design "
        "was red before the route." + ON_DISK
    )
    assert sorted(f.name for f in (tmp_path / "routed" / "build" / "route").iterdir()) == ["design.json"]
    # the files are those of `design` without --route, and so is every line but the last
    plain = design_run("design", design_file(tmp_path / "plain", STRIP))
    assert plain.returncode == 1
    for name in ("t.kicad_pro", "t.kicad_sch", "t.kicad_pcb"):
        assert (tmp_path / "routed" / name).read_bytes() == (tmp_path / "plain" / name).read_bytes(), name
    said = [re.sub(r"\[[\d.]+s\]", "[s]", ln.replace("/routed/", "/plain/")) for ln in lines[:-1]]
    assert said == [re.sub(r"\[[\d.]+s\]", "[s]", ln) for ln in plain.stdout.splitlines()[:-1]]


@needs_libs
@needs_kicad
def test_the_summary_says_why_the_router_was_not_started(tmp_path):
    code, summary = run_cli("design", design_file(tmp_path / "a", OVERLAP), "--route")
    assert code == 1 and isinstance(summary, dict), summary
    assert summary["route"] == {"refused": NO_ROUTE_MENDS}
    assert summary["erc_problems"] == []
    assert summary["drc_problems"] == [
        "courtyards_overlap: Courtyards overlap: Footprint R1 at (110, 106); Footprint R2 at (110, 107.2)"
    ]
    assert summary["red"] == ["1 DRC error(s) on the unrouted board"]
    assert summary["route_numbers"] == SMALL_BOARD
    # the run leaves its summary for `workcenter next`
    record = tmp_path / "a" / "build" / "route" / "design.json"
    assert json.loads(record.read_text(encoding="utf-8")) == summary
    code, summary = run_cli("design", design_file(tmp_path / "b", STRIP), "--route")
    assert code == 1 and isinstance(summary, dict), summary
    assert summary["route"] == {"refused": "the design was red before the route"}
    assert summary["red"] == ["1 part(s) in a keep-out or off the board"]
    # KiCad's checks did not run on it
    assert "erc_problems" not in summary and "drc_problems" not in summary
    record = tmp_path / "b" / "build" / "route" / "design.json"
    assert json.loads(record.read_text(encoding="utf-8")) == summary
    # a run without --route says nothing of a route, and leaves no record
    code, summary = run_cli("design", design_file(tmp_path / "c", OVERLAP))
    assert code == 0 and isinstance(summary, dict), summary
    assert not {"route", "route_numbers", "erc_problems", "drc_problems"} & set(summary)
    assert not (tmp_path / "c" / "build").exists()


@needs_libs
@needs_kicad
def test_an_erc_error_of_the_generated_schematic_is_not_routed(tmp_path):
    """P3's "Done when" starts with the ERC. 2 power nets with no PWR_FLAG are 2 errors of KiCad's ERC
    on the generated schematic, and no route gives a net its flag."""
    r = design_run("design", design_file(tmp_path, "d.flagged_nets = []"), "--route")
    assert r.returncode == 1 and r.stderr == "", r.stdout + r.stderr
    said = "power_pin_not_driven: Input Power pin not driven by any Output Power pins: Symbol #PWR0"
    assert route_lines(r.stdout) == [
        f"  erc: {said}1 Pin 1 [Power input, Line] at (132.08, 81.28)",
        f"  erc: {said}2 Pin 1 [Power input, Line] at (132.08, 86.36)",
    ]
    assert r.stdout.splitlines()[-1] == "design t red: 2 ERC error(s) on the schematic." + NOT_STARTED
    assert list((tmp_path / "build" / "route").glob("*.ses")) == []


@needs_libs
@needs_kicad
def test_a_warning_of_the_erc_does_not_stop_the_route(tmp_path):
    """M127's net on 1 pin: KiCad's ERC names its label (`isolated_pin_label`) at severity warning, on
    a sheet of labels and on a wired sheet alike. A warning is no error, so the router is started; an
    input pin alone on its net is an error (`pin_not_driven`), and it is not."""
    env = stub_router(tmp_path, GIVES_UP)
    for folder, wired in (("labels", "d.sch_wires = False"), ("wired", "d.sch_wires = True")):
        src = design_file(tmp_path / folder, "d.parts[3].nets['1'] = 'OUTX'", wired)
        r = design_run("design", src, "--route", env=env)
        (line,) = route_lines(r.stdout)
        assert line.startswith("  route: FreeRouting exited 3 and wrote no session."), r.stdout
        report = json.loads((tmp_path / folder / "build" / "route" / "erc.json").read_text(encoding="utf-8"))
        found = [(v["type"], v["severity"]) for sheet in report["sheets"] for v in sheet["violations"]]
        assert found == [("isolated_pin_label", "warning")]
    inverter = (
        "d.add('U1', '74xGxx:74LVC1G04', 'INV', 'Package_TO_SOT_SMD:SOT-23-5', sch_at=(152.4, 114.3), "
        "pcb_at=(118.0, 110.0), nets={'2': 'BTN_L3', '3': 'GND', '4': 'OUT', '5': 'VCC'})"
    )
    r = design_run("design", design_file(tmp_path / "input", inverter), "--route", env=env)
    assert route_lines(r.stdout) == [
        "  erc: pin_not_driven: Input pin not driven by any Output pins: "
        "Symbol U1 Pin 2 [Input, Line] at (137.16, 114.3)"
    ]


@needs_libs
@needs_kicad
def test_more_than_20_errors_are_20_lines_and_a_count(tmp_path):
    """8 resistors on 1 spot: every 2 of them are a courtyard error, a short and more."""
    body = (
        "d = kicadgen.Design(name='t', namespace=__import__('uuid').UUID(int=88))",
        "for i in range(8):",
        f"    d.add(f'R{{i + 1}}', 'Device:R', '1k', {R0603!r}, sch_at=(25.4 + 12.7 * i, 50.8),",
        "          pcb_at=(110.0, 110.0), nets={'1': f'A{i}', '2': f'B{i}'})",
    )
    code, summary = run_cli("design", design_file(tmp_path, *body), "--route")
    assert code == 1 and isinstance(summary, dict), summary
    problems = summary["drc_problems"]
    assert len(problems) > 20 and problems == sorted(problems)
    assert summary["red"] == [f"{len(problems)} DRC error(s) on the unrouted board"]
    r = design_run("design", tmp_path / "design.py", "--route")
    lines = route_lines(r.stdout)
    assert lines[:20] == [f"  drc: {problem}" for problem in problems[:20]]
    report = tmp_path / "build" / "route" / "drc.json"
    assert lines[20:] == [f"  drc: {len(problems) - 20} more in {report}"]


@needs_libs
@needs_kicad
def test_a_project_written_elsewhere_is_not_refused_for_a_model_it_names_from_there(tmp_path):
    """A design names a model file from its own folder. Written into another folder (`--out`, as P4
    step 5 asks of a route that only evaluates), the schematic names the file from there, and KiCad's
    ERC finds none: `simulation_model_issue`, an error in a design that simulates. The design's own
    check has read the file, so that rule does not stop a route into another folder."""
    sim = "d.sim('R1', library='models/r.lib', name='RX', pins={'1': 'A', '2': 'B'})"
    src = design_file(tmp_path / "p", sim)
    (tmp_path / "p" / "models").mkdir()
    (tmp_path / "p" / "models" / "r.lib").write_text(".subckt RX A B\nR1 A B 10k\n.ends\n", encoding="utf-8")
    env = stub_router(tmp_path, GIVES_UP)
    for out in ((), ("--out", tmp_path / "scratch")):
        r = design_run("design", src, "--route", *out, env=env)
        (line,) = route_lines(r.stdout)
        assert line.startswith("  route: FreeRouting exited 3 and wrote no session."), r.stdout

    def found(folder: str) -> list[tuple[str, str]]:
        report = json.loads((tmp_path / folder / "build" / "route" / "erc.json").read_text(encoding="utf-8"))
        return [(v["type"], v["severity"]) for sheet in report["sheets"] for v in sheet["violations"]]

    assert found("p") == [] and found("scratch") == [("simulation_model_issue", "error")]


@needs_libs
def test_the_route_is_skipped_when_kicad_is_absent_and_red_when_its_check_does_not_run(tmp_path):
    """Without kicad-cli nothing can say whether the unrouted board has an error: the route is skipped
    as for an absent router, exit 2, and not refused. A kicad-cli that ends with another exit code
    than 0 or 5 is an engine's error: 1 `route:` line and exit 1."""
    absent = str(tmp_path / "no-kicad-cli")
    env = {**os.environ, "KICAD_CLI": absent}
    r = design_run("design", design_file(tmp_path / "absent"), "--route", env=env)
    assert r.returncode == 2 and r.stderr == "", r.stdout + r.stderr
    assert route_lines(r.stdout) == [f"  route skipped: engine missing: {absent}"]
    assert " red: " not in r.stdout.splitlines()[-1]
    assert (tmp_path / "absent" / "t.kicad_pcb").is_file()
    broken = tmp_path / "kicad-cli"
    broken.write_text('#!/bin/sh\necho "no such command" >&2\nexit 3\n', encoding="utf-8")
    broken.chmod(0o755)
    env = {**os.environ, "KICAD_CLI": str(broken)}
    r = design_run("design", design_file(tmp_path / "broken"), "--route", env=env)
    assert r.returncode == 1 and r.stderr == "", r.stdout + r.stderr
    assert route_lines(r.stdout) == [
        "  route: KiCad's ERC of the schematic did not run: kicad-cli exited 3: no such command"
    ]
    assert r.stdout.splitlines()[-1] == "design t red: the checks before the route did not run." + ON_DISK
    # an ERC that runs and a DRC that does not: no report says the board has no error ($4 is the report)
    half = tmp_path / "kicad-cli-half"
    half.write_text(
        '#!/bin/sh\nif [ "$1" = "sch" ]; then echo \'{"sheets": []}\' > "$4"; exit 0; fi\n'
        'echo "boom: the DRC broke" >&2\nexit 3\n',
        encoding="utf-8",
    )
    half.chmod(0o755)
    env = {**os.environ, "KICAD_CLI": str(half)}
    r = design_run("design", design_file(tmp_path / "half"), "--route", env=env)
    assert r.returncode == 1 and r.stderr == "", r.stdout + r.stderr
    assert route_lines(r.stdout) == [
        "  route: KiCad's DRC of the unrouted board did not run: kicad-cli exited 3: boom: the DRC broke"
    ]
    assert r.stdout.splitlines()[-1] == "design t red: the checks before the route did not run." + ON_DISK


@needs_libs
@needs_kicad
@needs_router
def test_a_design_with_no_error_routes_to_the_board_it_routed_before(tmp_path):
    """The checks change nothing in what is routed. The command's board, schematic and project are,
    byte for byte, those of the route and the write alone, which is all the command did before it
    checked. A pour with hand tracks is the hard case: the unrouted board is written first, that write
    ties a pour's island with a via, and the route must not take that via for hand copper."""
    pytest.importorskip("pcbnew")
    plain = design_file(tmp_path / "plain" / "new").read_text(encoding="utf-8")
    for name, text, stitches in (("plain", plain, 0), ("poured", walled_divider(), 1)):
        new, old = tmp_path / name / "new", tmp_path / name / "old"
        for folder in (new, old):
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "design.py").write_text(text, encoding="utf-8")
        r = design_run("design", new / "design.py", "--route")
        assert r.returncode == 0, r.stdout + r.stderr
        d = kicadgen.load_design(old / "design.py")
        route = kicadgen.route(d, old / "build" / "route", passes=60, timeout=900)
        d.write(old)
        assert (len(d.stitches), d.islands) == (stitches, [])
        # the lines of a route with a small board's numbers are the lines of before
        assert route_lines(r.stdout) == [
            f"  routed: {route['segments']} segments, {route['vias']} vias, DRC decides, 1 round(s)  "
            f"({new / 'build' / 'route' / 'freerouting.log'})"
        ]
        assert " red: " not in r.stdout.splitlines()[-1]
        for suffix in (".kicad_pcb", ".kicad_sch", ".kicad_pro"):
            assert (new / f"{d.name}{suffix}").read_bytes() == (old / f"{d.name}{suffix}").read_bytes(), (
                name,
                suffix,
            )


# ------------------------------------------------------------- the route's numbers


def many_parts(n: int) -> str:
    """`n` resistors in rows of 10, 4 mm by 3 mm apart, each between the nets A and B."""
    return (
        "import sys, uuid\n"
        f"sys.path.insert(0, {str(ROOT / 'tools')!r})\n"
        "import kicadgen\n"
        "def build():\n"
        "    d = kicadgen.Design(name='many', namespace=uuid.UUID(int=5150),\n"
        "                        outline=(100.0, 100.0, 144.0, 122.0))\n"
        f"    for i in range({n}):\n"
        "        col, row = i % 10, i // 10\n"
        f"        d.add(f'R{{i + 1}}', 'Device:R', '1k', {R0603!r},\n"
        "              sch_at=(25.4 + 12.7 * col, 25.4 + 25.4 * row),\n"
        "              pcb_at=(104.0 + 4.0 * col, 103.0 + 3.0 * row), nets={'1': 'A', '2': 'B'})\n"
        "    return d\n"
    )


def numbers(passes: tuple[int, str], timeout: tuple[int, str], rounds: tuple[int, str]) -> dict:
    """A summary's `route_numbers`: each number with where it came from."""
    given = {"passes": passes, "timeout": timeout, "rounds": rounds}
    return {key: {"value": value, "from": source} for key, (value, source) in given.items()}


def passes_given(folder: Path) -> list[str]:
    """The `-mp` each start of the router was given, from the log the stub writes its arguments to."""
    log = (folder / "build" / "route" / "freerouting.log").read_text(encoding="utf-8")
    return re.findall(r" -mp (\d+) -dct 0", log)


@needs_libs
@needs_kicad
def test_a_design_carries_its_routes_numbers_and_a_flag_wins(tmp_path):
    env = stub_router(tmp_path, GIVES_UP)
    src = design_file(tmp_path / "p", 'd.route = {"passes": 7, "timeout": 30}')
    code, summary = run_cli("design", src, "--route", env=env)
    assert code == 1 and isinstance(summary, dict), summary
    assert summary["route_numbers"] == numbers((7, "design"), (30, "design"), (4, "default"))
    assert passes_given(tmp_path / "p") == ["7"]
    code, summary = run_cli("design", src, "--route", "--passes", "9", "--rounds", "2", env=env)
    assert code == 1 and isinstance(summary, dict), summary
    assert summary["route_numbers"] == numbers((9, "flag"), (30, "design"), (2, "flag"))
    assert passes_given(tmp_path / "p") == ["9"]
    # with no record and no flag, a board of 4 parts routes with the numbers of every route before
    code, summary = run_cli("design", design_file(tmp_path / "q"), "--route", env=env)
    assert code == 1 and isinstance(summary, dict), summary
    assert summary["route_numbers"] == SMALL_BOARD and passes_given(tmp_path / "q") == ["60"]


@needs_libs
def test_a_route_record_with_a_key_or_a_value_it_does_not_know_is_refused(tmp_path):
    keys = 'Write d.route = {"passes": 12, "timeout": 3600, "rounds": 4}, or any of the 3.'
    r = design_run("design", design_file(tmp_path, 'd.route = {"pases": 12}'), "--route")
    assert r.returncode == 1 and r.stderr == "", r.stdout + r.stderr
    refused = "the design file is refused. Nothing is written: correct the file first."
    assert r.stdout.splitlines() == [
        f"  file: route has the key 'pases', which is none of passes, timeout, rounds. {keys}",
        f"design {tmp_path.name} red: {refused}",
    ]
    assert list(tmp_path.glob("*.kicad_*")) == [] and not (tmp_path / "build").exists()
    number = "not a whole number of 1 or more. Write d.route = "
    for value, said in (
        (["passes"], f"route is a list, not a dict. {keys}"),
        ({"passes": "12"}, f"route[\"passes\"] is '12', {number}" + '{"passes": 12}.'),
        ({"timeout": 0}, f'route["timeout"] is 0, {number}' + '{"timeout": 3600}.'),
        ({"rounds": True}, f'route["rounds"] is True, {number}' + '{"rounds": 4}.'),
        ({"passes": 12.5}, f'route["passes"] is 12.5, {number}' + '{"passes": 12}.'),
    ):
        d = board()
        d.route = value
        with pytest.raises((TypeError, ValueError)) as e:
            d.check_route()
        assert str(e.value) == said
    whole = board()
    whole.route = {"passes": 12, "timeout": 3600, "rounds": 4}
    whole.check_route()
    assert board().route == {}


@needs_libs
@needs_kicad
def test_a_board_of_more_than_50_parts_routes_with_12_passes_and_an_hour(tmp_path):
    """M128 and M147: 60 passes and 15 minutes on 140 and on 76 parts, the numbers of a board of 4.
    P4 step 6's numbers are the command's own for a board of more than 50 parts."""
    env = stub_router(tmp_path, GIVES_UP)
    for n, passes, timeout in ((50, 60, 900), (51, 12, 3600)):
        folder = tmp_path / str(n)
        folder.mkdir()
        (folder / "design.py").write_text(many_parts(n), encoding="utf-8")
        code, summary = run_cli("design", folder / "design.py", "--route", env=env)
        assert code == 1 and isinstance(summary, dict), summary
        assert summary["parts"] == n and summary["erc_problems"] == summary["drc_problems"] == []
        assert summary["route_numbers"] == numbers((passes, "default"), (timeout, "default"), (4, "default"))
        assert passes_given(folder) == [str(passes)]
    # a part with no footprint is not on the board, and the board is what the router gets
    d = kicadgen.load_design(tmp_path / "51" / "design.py")
    assert kicadgen.route_numbers(d, {})["passes"] == (12, "default")
    d.parts[0].footprint = None
    assert kicadgen.route_numbers(d, {}) == {
        "passes": (60, "default"),
        "timeout": (900, "default"),
        "rounds": (4, "default"),
    }
    assert kicadgen.route_numbers(d, {"passes": None, "timeout": 120})["timeout"] == (120, "flag")
    # nor is a part with a footprint and no place
    d = kicadgen.load_design(tmp_path / "51" / "design.py")
    d.parts[0].pcb_at = None
    assert kicadgen.route_numbers(d, {})["passes"] == (60, "default")


@needs_libs
@needs_kicad
@needs_router
def test_the_routed_line_names_numbers_that_are_not_a_small_boards(tmp_path):
    r = design_run("design", design_file(tmp_path, 'd.route = {"passes": 10}'), "--route", "--timeout", "600")
    assert r.returncode == 0, r.stdout + r.stderr
    log = tmp_path / "build" / "route" / "freerouting.log"
    (line,) = route_lines(r.stdout)
    assert re.fullmatch(
        r"  routed: [1-9]\d* segments, 0 vias, DRC decides, 1 round\(s\), 10 passes \(design\), "
        r"600 s limit \(flag\), 4 rounds at most \(default\)  \(" + re.escape(str(log)) + r"\)",
        line,
    ), line


# ------------------------------------------------------------- a route that does not end


@needs_libs
@needs_kicad
def test_a_route_the_limit_stops_is_one_line_and_leaves_the_unrouted_project(tmp_path):
    """M128: FreeRouting writes its session only when it ends, so a route the limit stops leaves
    nothing. It ended in Python's traceback of `subprocess.TimeoutExpired`, with the router's child
    still running."""
    src = design_file(tmp_path / "p")
    assert design_run("design", src).returncode == 0
    written = ("t.kicad_pro", "t.kicad_sch", "t.kicad_pcb")
    before = {name: (tmp_path / "p" / name).read_bytes() for name in written}
    started = time.monotonic()
    r = design_run("design", src, "--route", "--timeout", "1", env=stub_router(tmp_path, SLEEPS))
    assert r.returncode == 1 and "Traceback" not in r.stderr, r.stdout + r.stderr
    # the limit ends the router's whole session at once: the stub's child would sleep 30 s
    assert time.monotonic() - started < 20
    log = tmp_path / "p" / "build" / "route" / "freerouting.log"
    assert route_lines(r.stdout) == [
        "  route: FreeRouting was stopped after 1 s, its limit, at 60 passes, and wrote no session: it "
        f'writes one only when it ends. Its last line: "pass 1 of many" ({log}). Route again with fewer '
        "passes or a longer limit, in the background (PROCESSES.md P4 step 6). Give them as --passes and "
        "--timeout, or as d.route in the design file."
    ]
    assert r.stdout.splitlines()[-1] == "design t red: the router left no route." + ON_DISK
    assert log.read_text(encoding="utf-8").splitlines()[-1] == "pass 1 of many"
    # the project's files are the unrouted ones, as they were (kicad-cli leaves a .kicad_prl beside them)
    assert {name: (tmp_path / "p" / name).read_bytes() for name in written} == before
    # the router's child went with it
    child = int((log.parent / "child.pid").read_text(encoding="utf-8"))
    assert left_running(str(tmp_path), (child,)) == []
    code, summary = run_cli("design", src, "--route", "--timeout", "1", env=stub_router(tmp_path, SLEEPS))
    assert code == 1 and isinstance(summary, dict), summary
    assert summary["route"]["log"] == str(log)
    assert summary["route"]["error"].startswith("FreeRouting was stopped after 1 s, its limit, at 60 passes")
    assert summary["red"] == ["the router left no route"]
    assert summary["route_numbers"] == numbers((60, "default"), (1, "flag"), (4, "default"))


@needs_libs
@needs_kicad
@needs_xvfb
def test_a_stopped_route_takes_its_display_server_with_it(tmp_path):
    """With no display the router runs under `xvfb-run`. The limit ended `xvfb-run` alone: its display
    server and the router ran on."""
    env = stub_router(tmp_path, SLEEPS, display=False)
    r = design_run("design", design_file(tmp_path / "p"), "--route", "--timeout", "2", env=env)
    assert r.returncode == 1 and "Traceback" not in r.stderr, r.stdout + r.stderr
    (line,) = route_lines(r.stdout)
    assert line.startswith("  route: FreeRouting was stopped after 2 s, its limit, at 60 passes"), line
    child = tmp_path / "p" / "build" / "route" / "child.pid"  # written once the display server is up
    pids = (int(child.read_text(encoding="utf-8")),) if child.is_file() else ()
    assert left_running(str(tmp_path), pids) == []


@needs_libs
@needs_kicad
def test_a_router_that_ends_without_a_session_is_one_line(tmp_path):
    src = design_file(tmp_path / "p")
    log = tmp_path / "p" / "build" / "route" / "freerouting.log"
    r = design_run("design", src, "--route", env=stub_router(tmp_path, GIVES_UP))
    assert r.returncode == 1 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert route_lines(r.stdout) == [
        '  route: FreeRouting exited 3 and wrote no session. Its last line: "the router gave up" '
        f"({log}). Read that log before the next route."
    ]
    assert r.stdout.splitlines()[-1] == "design t red: the router left no route." + ON_DISK
    # exit code 0 and no session is no route either
    r = design_run("design", src, "--route", env=stub_router(tmp_path, 'echo "done"\n'))
    assert r.returncode == 1 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert route_lines(r.stdout) == [
        f'  route: FreeRouting exited 0 and wrote no session. Its last line: "done" ({log}). '
        "Read that log before the next route."
    ]
    # a session beside an exit code that is not 0 is not merged: the line does not say there is none
    crashed = 'echo "(session cut short" > "$6"\necho "crashed"\nexit 3\n'  # $6 follows -do
    r = design_run("design", src, "--route", env=stub_router(tmp_path, crashed))
    assert r.returncode == 1 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert route_lines(r.stdout) == [
        f'  route: FreeRouting exited 3 and its session is not merged. Its last line: "crashed" ({log}). '
        "Read that log before the next route."
    ]
    assert kicadgen.board_copper(tmp_path / "p" / "t.kicad_pcb")["segments"] == []


@needs_libs
@needs_kicad
def test_a_seed_that_is_the_projects_own_board_is_kept_when_the_route_leaves_none(tmp_path):
    """`design --route --seed <the project's own board>` reads the seed, then writes the unrouted board
    over it. A route that is then not started, or leaves no route, left no copy of the seed: a second
    run of the same command was seeded from a board with no track."""
    src = design_file(tmp_path, 'd.track("VCC", [(104.0, 107.5), (109.175, 106.0)])')
    assert design_run("design", src).returncode == 0
    board_file = tmp_path / "t.kicad_pcb"
    seed = board_file.read_bytes()  # the board of an earlier design: 1 track, J1.1 to R1.1
    assert len(kicadgen.board_copper(board_file)["segments"]) == 1
    design_file(tmp_path)  # the design of this run draws no track
    copy = tmp_path / "build" / "route" / "t.seed.kicad_pcb"
    env = stub_router(tmp_path, GIVES_UP)
    r = design_run("design", src, "--route", "--seed", board_file, env=env)
    assert r.returncode == 1 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert r.stdout.splitlines()[-1] == (
        "design t red: the router left no route. The board on disk is the unrouted one. The seed was that "
        f"board: it is kept as {copy}. The files are written for inspection only; a CI regenerate check "
        "fails on this exit code (1)."
    )
    assert copy.read_bytes() == seed and kicadgen.board_copper(board_file)["segments"] == []
    code, summary = run_cli("design", src, "--route", "--seed", copy, env=env)
    assert code == 1 and isinstance(summary, dict), summary
    assert "seed_copy" not in summary and copy.read_bytes() == seed  # a seed elsewhere is only read
    # a route that is not started keeps its seed the same way
    design_file(tmp_path, OVERLAP)
    board_file.write_bytes(seed)
    r = design_run("design", src, "--route", "--seed", board_file, env=env)
    assert r.returncode == 1 and "  drc: courtyards_overlap: " in r.stdout, r.stdout + r.stderr
    assert f" The seed was that board: it is kept as {copy}. " in r.stdout.splitlines()[-1]
    assert copy.read_bytes() == seed


@needs_libs
@needs_kicad
def test_the_same_seeded_command_run_again_starts_from_the_copy_the_last_run_kept(tmp_path):
    """The run above leaves the unrouted board where its seed was. The same command, run again, read
    that board as its seed and wrote it over the copy: after 2 runs the route's copper was in no file
    (a reviewer's case: `board 0, kept copy 0`). A board that holds no route is not written over a
    copy that does, and the copy is the seed."""
    src = design_file(tmp_path, 'd.track("VCC", [(104.0, 107.5), (109.175, 106.0)])')
    assert design_run("design", src).returncode == 0
    board_file = tmp_path / "t.kicad_pcb"
    seed = board_file.read_bytes()
    design_file(tmp_path)  # the design of these runs draws no track
    copy = tmp_path / "build" / "route" / "t.seed.kicad_pcb"
    dsn = tmp_path / "build" / "route" / "t.dsn"
    env = stub_router(tmp_path, GIVES_UP)
    r = design_run("design", src, "--route", "--seed", board_file, env=env)
    assert r.returncode == 1 and copy.read_bytes() == seed, r.stdout + r.stderr
    assert "  seed: " not in r.stdout and "(wire (path" in dsn.read_text(encoding="utf-8")
    assert kicadgen.board_copper(board_file)["segments"] == []
    dsn.unlink()
    r = design_run("design", src, "--route", "--seed", board_file, env=env)
    assert r.returncode == 1 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert copy.read_bytes() == seed
    assert (
        f"  seed: {board_file} holds no route: the route starts from the copy the last run kept, {copy}"
        in r.stdout.splitlines()
    )
    assert "(wire (path" in dsn.read_text(encoding="utf-8")  # the router was given the seed's track
    assert f" The seed was that board: it is kept as {copy}. " in r.stdout.splitlines()[-1]
    # a board with a route of its own takes the copy's place
    board_file.write_bytes(seed.replace(b"109.175", b"109.176"))
    r = design_run("design", src, "--route", "--seed", board_file, env=env)
    assert r.returncode == 1 and "  seed: " not in r.stdout, r.stdout + r.stderr
    assert copy.read_bytes() == seed.replace(b"109.175", b"109.176")


@needs_libs
@needs_kicad
def test_a_command_that_is_ended_from_outside_takes_its_router_with_it(tmp_path):
    """The router runs in a session of its own, so that its limit can end it with its display server.
    A SIGTERM sent to the command, or to the command's group as `timeout 4 workcenter design ...`
    sends it, then reached the command alone: the router ran on with no limit left to stop it (a
    reviewer's case; on the code before, the group's signal reached the router too)."""
    src = design_file(tmp_path / "p")
    child = tmp_path / "p" / "build" / "route" / "child.pid"
    command = subprocess.Popen(
        [sys.executable, str(CLI), "design", str(src), "--route"],
        env=stub_router(tmp_path, SLEEPS),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        end = time.monotonic() + 60
        while not child.is_file() and time.monotonic() < end and command.poll() is None:
            time.sleep(0.1)
        assert child.is_file(), command.communicate(timeout=5)
        time.sleep(0.2)  # the stub has written its child's number by now
        command.send_signal(signal.SIGTERM)
        out, err = command.communicate(timeout=30)
    finally:
        command.kill()
    assert command.returncode == 128 + signal.SIGTERM and "Traceback" not in err, out + err
    assert left_running(str(tmp_path), (int(child.read_text(encoding="utf-8")),)) == []


@needs_libs
def test_a_route_number_given_as_a_flag_is_1_or_more(tmp_path):
    """`d.route` refuses a number under 1. The flags took one: `--rounds 0` ended in a KeyError's
    traceback, and `--timeout 0` stopped the router before it started (a reviewer's case)."""
    src = design_file(tmp_path)
    for flag in ("--passes", "--timeout", "--rounds"):
        for value in ("0", "-3", "2.5"):
            r = design_run("design", src, "--route", flag, value)
            assert r.returncode == 2 and "Traceback" not in r.stderr, (flag, value, r.stdout + r.stderr)
            assert r.stderr.splitlines()[-1] == (
                f"workcenter design: error: argument {flag}: {value} is not a whole number of 1 or more"
            )
    assert not (tmp_path / "t.kicad_pcb").exists()  # refused before anything is written


@needs_libs
def test_a_check_before_the_route_that_does_not_end_is_one_line(tmp_path, monkeypatch, capsys):
    """KiCad's DRC of a large unrouted board takes minutes (204 s on the largest example). A kicad-cli
    that does not end ran into the runner's limit, and the command ended in Python's traceback of
    `subprocess.TimeoutExpired` (a reviewer's case, after 902 s). The limit is the route's own when
    that is longer."""
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_slow_check", str(CLI))
    cli = types.ModuleType("workcenter_cli_slow_check")
    cli.__file__ = str(CLI)
    monkeypatch.setitem(sys.modules, cli.__name__, cli)
    loader.exec_module(cli)
    asked = []

    def run(cmd, cwd=None, timeout=900, env=None):
        asked.append((str(cmd[1]), str(cmd[2]), timeout))
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(cli, "run", run)
    monkeypatch.setattr(kicadgen.Design, "write", lambda self, out_dir: [Path(out_dir) / "t.kicad_pcb"])
    code = cli.main(["design", str(design_file(tmp_path)), "--route"])
    lines = capsys.readouterr().out.splitlines()
    assert code == 1 and asked == [("sch", "erc", 900)]
    assert route_lines("\n".join(lines)) == [
        "  route: KiCad's ERC of the schematic did not end within 900 s. Run `workcenter doctor`; a "
        "board whose checks take longer names a longer limit as --timeout or as d.route."
    ]
    assert lines[-1] == "design t red: the checks before the route did not run." + ON_DISK
    asked.clear()
    assert cli.main(["design", str(design_file(tmp_path)), "--route", "--timeout", "2400"]) == 1
    assert asked == [("sch", "erc", 2400)]


def cli_module(monkeypatch, name: str) -> types.ModuleType:
    """The `workcenter` command loaded as a module of its own, for a test that stands in for 1 part of
    it."""
    loader = importlib.machinery.SourceFileLoader(name, str(CLI))
    cli = types.ModuleType(name)
    cli.__file__ = str(CLI)
    monkeypatch.setitem(sys.modules, name, cli)  # dataclasses look the defining module up here
    loader.exec_module(cli)
    return cli


def test_the_check_before_a_route_asks_for_parity_and_reads_it(tmp_path, monkeypatch):
    """A footprint whose pad is on another net than its symbol's pin is a parity error, and no route
    mends it. A generated project has none unless the generator is wrong, so KiCad's 2 reports are
    stood in for here: the check asks the DRC for parity, reads its list, and takes an unconnected
    item for what the route joins."""
    cli = cli_module(monkeypatch, "workcenter_cli_parity")
    asked = {}

    def drc(board, report, parity, timeout=900):
        asked["parity"] = parity
        pad = {"description": "PTH pad 1 [GND] of R1", "pos": {"x": 110.0, "y": 106.0}}
        conflict = "Pad net (GND) doesn't match net given by schematic (VCC)."
        return None, {
            "violations": [],
            "unconnected_items": [{"severity": "error", "type": "unconnected_items", "items": []}],
            "schematic_parity": [
                {"severity": "error", "type": "net_conflict", "description": conflict, "items": [pad]},
                {"severity": "warning", "type": "duplicate_footprints", "description": "x", "items": []},
            ],
        }

    monkeypatch.setattr(cli, "kicad_erc", lambda sch, report, timeout=900: (None, []))
    monkeypatch.setattr(cli, "kicad_drc", drc)
    found = cli.unrouted_errors(tmp_path / "t.kicad_sch", tmp_path / "t.kicad_pcb", tmp_path / "out")
    assert asked == {"parity": True}
    assert found == {
        "erc": [],
        "drc": [
            "net_conflict: Pad net (GND) doesn't match net given by schematic (VCC).: "
            "PTH pad 1 [GND] of R1 at (110, 106)"
        ],
    }


@needs_libs
def test_exactly_20_errors_are_20_lines_and_no_count(tmp_path, monkeypatch, capsys):
    cli = cli_module(monkeypatch, "workcenter_cli_count")
    monkeypatch.setattr(kicadgen.Design, "write", lambda self, out_dir: [Path(out_dir) / "t.kicad_pcb"])
    report = tmp_path / "build" / "route" / "drc.json"
    for n in (20, 21):
        found = {"erc": [], "drc": [f"rule: error {i:02}" for i in range(n)]}
        monkeypatch.setattr(cli, "unrouted_errors", lambda *args, found=found, **kwargs: found)
        assert cli.main(["design", str(design_file(tmp_path)), "--route"]) == 1
        lines = route_lines(capsys.readouterr().out)
        assert lines[:20] == [f"  drc: rule: error {i:02}" for i in range(20)]
        assert lines[20:] == ([f"  drc: 1 more in {report}"] if n == 21 else [])


@needs_libs
@needs_kicad
def test_a_run_that_makes_no_check_leaves_no_report_of_the_run_before(tmp_path):
    """`workcenter next` and a reader open build/route for what the last run found. A design that is
    red before the route asks KiCad nothing, so the 2 reports there would be an earlier run's."""
    src = design_file(tmp_path, OVERLAP)
    route_dir = tmp_path / "build" / "route"
    assert design_run("design", src, "--route").returncode == 1
    assert sorted(f.name for f in route_dir.iterdir()) == ["design.json", "drc.json", "erc.json"]
    design_file(tmp_path, STRIP)
    assert design_run("design", src, "--route").returncode == 1
    assert sorted(f.name for f in route_dir.iterdir()) == ["design.json"]


# A router that answers a SIGTERM by writing a file, as a display server answers it by removing its lock.
ANSWERS = "trap 'echo asked > asked.txt; exit 0' TERM\necho \"pass 1 of many\"\nsleep 30 &\nwait\n"
# A router that does not answer a SIGTERM at all.
DEAF = "trap '' TERM\necho \"deaf to SIGTERM\"\nsleep 30\n"
# A router that writes a session and then does not end: $6 follows -do.
SAVES_AND_STAYS = 'echo "(session" > "$6"\necho "session saved"\nsleep 30 &\nwait\n'


@needs_libs
@needs_kicad
def test_a_stopped_router_is_asked_first_then_ended_and_its_cut_session_is_no_session(tmp_path):
    """The limit sends SIGTERM first: a display server removes its lock and its socket on it, and a
    SIGKILL alone left a stale lock in /tmp (a reviewer's run). A router that does not answer is ended
    after the grace. A session file that is there when the limit stops the router was cut short: it is
    removed, so that no later step merges it."""
    route_dir = tmp_path / "p" / "build" / "route"
    src = design_file(tmp_path / "p")
    r = design_run("design", src, "--route", "--timeout", "1", env=stub_router(tmp_path, ANSWERS))
    assert r.returncode == 1 and "Traceback" not in r.stderr, r.stdout + r.stderr
    assert (route_dir / "asked.txt").read_text(encoding="utf-8") == "asked\n"
    started = time.monotonic()
    r = design_run("design", src, "--route", "--timeout", "1", env=stub_router(tmp_path, DEAF))
    assert r.returncode == 1 and time.monotonic() - started < 20, r.stdout + r.stderr
    assert '"deaf to SIGTERM"' in r.stdout and left_running(str(tmp_path)) == []
    r = design_run("design", src, "--route", "--timeout", "1", env=stub_router(tmp_path, SAVES_AND_STAYS))
    assert r.returncode == 1 and '"session saved"' in r.stdout, r.stdout + r.stderr
    assert not (route_dir / "t.ses").exists()
    # a router that prints nothing has no last line to quote
    r = design_run("design", src, "--route", env=stub_router(tmp_path, "exit 3\n"))
    log = route_dir / "freerouting.log"
    assert route_lines(r.stdout) == [
        f"  route: FreeRouting exited 3 and wrote no session. It printed nothing ({log}). "
        "Read that log before the next route."
    ]


ROUTED_AS = {
    "examples/anc-speaker/v0.1": {"passes": 20, "timeout": 900},
    "examples/fire-alarm-communicator/v0.1": {"passes": 60, "timeout": 900},
    "examples/snapdragon-dev-board/v0.2": {"passes": 100, "timeout": 3600, "rounds": 2},
}


def test_an_example_whose_readme_routes_with_no_number_names_its_numbers_in_its_design():
    """The bare command's passes and limit follow a board's size now: 12 and an hour above 50 parts,
    where every board had 60 and 900 s. 3 examples give a route command with no passes in their
    README, for boards of 62, 127 and 94 parts. Each design file names the numbers its committed
    board was routed with, so the README's command still does what it says."""
    for folder, numbers_of in ROUTED_AS.items():
        source = (ROOT / folder / "design.py").read_text(encoding="utf-8")
        (written,) = re.findall(r"^    d\.route = (\{.*\})$", source, re.M)
        assert ast.literal_eval(written) == numbers_of, folder
        readme = (ROOT / folder / "README.md").read_text(encoding="utf-8")
        commands = [ln for ln in readme.splitlines() if ln.startswith("workcenter design design.py --route")]
        assert commands and not any("--passes" in line for line in commands), folder


@needs_libs
def test_a_route_that_stops_in_a_later_round_leaves_the_last_rounds_board(tmp_path, monkeypatch, capsys):
    """M147: the command routes again when a pour loses a pad, and that second round ran into the
    limit. The first round's board is written by then, so the red line names it, not an unrouted
    board. The router, the write and the checks are stood in for: the rounds are the command's own."""
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_routing", str(CLI))
    cli = types.ModuleType("workcenter_cli_routing")
    cli.__file__ = str(CLI)
    monkeypatch.setitem(sys.modules, cli.__name__, cli)  # dataclasses look the defining module up here
    loader.exec_module(cli)
    stopped = "FreeRouting was stopped after 900 s, its limit, at 60 passes, and wrote no session."
    rounds = []

    def route(design, build_dir, passes, timeout, seed):
        rounds.append((passes, timeout, len(design.vias)))
        if len(rounds) == 2:
            raise kicadgen.RouteError(stopped, Path(build_dir) / "freerouting.log", True, None)
        return {"dsn": "", "ses": "", "log": "x.log", "segments": 3, "vias": 0, "unrouted": None}

    def write(self, out_dir):
        self.islands = [["R2.2"]]  # every write leaves a pad cut off from its pour
        return [Path(out_dir) / "t.kicad_pcb"]

    def reserve(self, pads):
        self.vias.append(("GND", (110.0, 111.0), 0.6, 0.3))
        return 1

    monkeypatch.setattr(kicadgen, "route", route)
    monkeypatch.setattr(kicadgen.Design, "write", write)
    monkeypatch.setattr(kicadgen.Design, "reserve_vias", reserve)
    monkeypatch.setattr(cli, "unrouted_errors", lambda *args, **kwargs: {"erc": [], "drc": []})
    code = cli.main(["design", str(design_file(tmp_path)), "--route"])
    lines = capsys.readouterr().out.splitlines()
    assert code == 1 and rounds == [(60, 900, 0), (60, 900, 1)]
    assert route_lines("\n".join(lines)) == [
        f"  route: {stopped} Route again with fewer passes or a longer limit, in the background "
        "(PROCESSES.md P4 step 6). Give them as --passes and --timeout, or as d.route in the design file."
    ]
    assert "  island: R2.2 cut off from their pour; the DRC will report it" in lines
    assert lines[-1] == (
        "design t red: the router left no route. The board on disk is the route of round 1. The files "
        "are written for inspection only; a CI regenerate check fails on this exit code (1)."
    )
    record = json.loads((tmp_path / "build" / "route" / "design.json").read_text(encoding="utf-8"))
    assert record["rounds"] == 1 and record["red"] == ["the router left no route"]


@needs_libs
@needs_kicad
def test_a_java_that_is_not_there_is_an_absent_engine(tmp_path):
    """Under `xvfb-run` a `java` that is not on PATH was exit code 127 of the wrapper, read as a
    router's failure. It is an absent engine: the command skips the route with exit 2."""
    jar = tmp_path / "freerouting.jar"
    jar.write_bytes(b"")
    with pytest.raises(FileNotFoundError) as e:
        kicadgen.route(board(), tmp_path / "build" / "route", jar=jar, java="no-such-java")
    assert str(e.value) == "no-such-java"
    assert not (tmp_path / "build").exists()
    # through the command, on a PATH that holds no java: kicad-cli is named by its own path
    (tmp_path / "empty").mkdir()
    env = {**os.environ, "PATH": str(tmp_path / "empty"), "FREEROUTING_JAR": str(jar)}
    env["KICAD_CLI"] = shutil.which("kicad-cli")
    r = design_run("design", design_file(tmp_path / "p"), "--route", env=env)
    assert r.returncode == 2 and r.stderr == "", r.stdout + r.stderr
    assert route_lines(r.stdout) == ["  route skipped: engine missing: java"]
    assert " red: " not in r.stdout.splitlines()[-1]
