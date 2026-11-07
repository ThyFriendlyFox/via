"""Tests for the router's inputs and the design command's report: the hole clearance each layer
asks (M79), a previous route as the router's starting wiring (`design --route --seed`), the island
each stitching via ties, and the last line of a red design run (M85).

Routing tests skip when FreeRouting is absent; library tests when the KiCad libraries are.
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

R0402 = "Resistor_SMD:R_0402_1005Metric"
R0603 = "Resistor_SMD:R_0603_1608Metric"
HDR1 = "Connector_PinHeader_2.54mm:PinHeader_1x01_P2.54mm_Vertical"
SIERRA_INNER = 0.3302  # Sierra's "Minimum Inner Layer Drill-to-Copper Spacing 13 mil"


def run_cli(*args: object, json_out: bool = True) -> tuple[int, object]:
    cmd = [sys.executable, str(CLI), *(["--json"] if json_out else []), *map(str, args)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
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
