"""ROADMAP item 15, "Headless autoroute for hand-drawn boards": tools/boardroute.py reads a .kicad_pcb
into kicadgen's DSN writer and writes the router's copper back into the board file.

The board is the fixture tests/boards/route-me: the RC divider of pass-rc-divider with R2 on the back,
C1 turned 90 degrees, and only the VIN net drawn by hand (3 tracks). No test here runs an engine: the
router is the stand-in of tests/routers/standin.py, and the DRC is test_gates.py's
test_autoroute_apply_routes_fixture.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import boardroute  # noqa: E402

FIXTURE = ROOT / "tests" / "boards" / "route-me"
PCB = FIXTURE / "rc_divider.kicad_pcb"
STANDIN = ROOT / "tests" / "routers" / "standin.py"


def copy_fixture(tmp_path: Path, text: str | None = None) -> Path:
    """The fixture's board and project file in tmp_path, the board replaced by `text` when given."""
    folder = tmp_path / "route-me"
    folder.mkdir()
    for name in ("rc_divider.kicad_pro", "rc_divider.kicad_sch"):
        (folder / name).write_text((FIXTURE / name).read_text(encoding="utf-8"), encoding="utf-8")
    pcb = folder / "rc_divider.kicad_pcb"
    pcb.write_text(text if text is not None else PCB.read_text(encoding="utf-8"), encoding="utf-8")
    return pcb


def test_read_board_takes_parts_nets_and_rules_from_the_files():
    """4 footprints in the file's order. R2 is on the back: its pads go back to the library frame, y
    negated, so pad 1 is at (-0.825, -0) = (-0.825, 0) as in R_0603_1608Metric. C1 is turned 90 degrees:
    its pads are written at 90 in the file, the footprint's 90 plus the library's 0, so each pad's own
    angle is 90 - 90 = 0. The rules are the .kicad_pro's Default class (0.25 mm track, 0.2 mm clearance,
    0.6/0.3 mm via) and its min_copper_edge_clearance 0.5 mm; the outline is the gr_rect 100,100 to
    125,120."""
    d, notes = boardroute.read_board(PCB)
    assert [p.ref for p in d.parts] == ["J1", "R1", "R2", "C1"]
    r2 = d.parts[2]
    assert (r2.pcb_layer, r2.pcb_at, r2.pcb_rot) == ("B.Cu", (118.0, 107.54), 0.0)
    assert [(p.number, p.x, p.y, p.angle) for p in r2.footprint.pads] == [
        ("1", -0.825, 0.0, 0.0),
        ("2", 0.825, 0.0, 0.0),
    ]
    assert r2.nets == {"1": "/VOUT", "2": "/GND"}
    c1 = d.parts[3]
    assert (c1.pcb_rot, [p.angle for p in c1.footprint.pads]) == (90.0, [0.0, 0.0])
    assert d.net_ids() == {"/VIN": 1, "/VOUT": 2, "/GND": 3}
    assert (d.track_width, d.clearance, d.via_size, d.via_drill, d.edge_clearance) == (
        0.25,
        0.2,
        0.6,
        0.3,
        0.5,
    )
    assert d.outline == (100.0, 100.0, 125.0, 120.0)
    assert len(d.segments) == 3 and {s[0] for s in d.segments} == {"/VIN"}
    assert notes == []


def test_dsn_of_the_board_lists_its_nets_parts_and_hand_tracks():
    """The network: VOUT on J1-2, R1-2, R2-1, C1-1 and GND on J1-3, R2-2, C1-2, in the file's order of
    footprints; VIN on J1-1 and R1-1. R2 goes in on the back side at 0 + 180 = 180 degrees (Specctra
    mirrors about the Y axis, KiCad flips about the X axis). The 3 VIN tracks are fixed wiring. The
    boundary is the outline shrunk by edge clearance less clearance, 0.5 - 0.2 = 0.3 mm: 100.3 to 124.7
    and 100.3 to 119.7, in 0.1 um with y up: 1003000 to 1247000 and -1003000 to -1197000."""
    d, _ = boardroute.read_board(PCB)
    dsn = d.dsn()
    assert '(net "/VOUT"\n      (pins J1-2 R1-2 R2-1 C1-1)' in dsn
    assert '(net "/GND"\n      (pins J1-3 R2-2 C1-2)' in dsn
    assert '(net "/VIN"\n      (pins J1-1 R1-1)' in dsn
    assert '(place "R2" 1180000 -1075400 back 180)' in dsn
    assert '(place "C1" 1180000 -1120000 front 90)' in dsn
    assert dsn.count("(type fix)") == 3
    assert (
        "(path pcb 0 1247000 -1003000 1247000 -1197000 1003000 -1197000 1003000 -1003000 1247000 -1003000)"
        in dsn
    )


ZONE = (
    '\t(zone (net 3) (net_name "/GND") (layer "B.Cu") (uuid "00000000-0000-0000-0000-000000000001")\n'
    "\t\t(connect_pads (clearance 0.2)) (min_thickness 0.25)\n"
    "\t\t(fill (thermal_gap 0.5) (thermal_bridge_width 0.5))\n"
    "\t\t(polygon (pts (xy 101 101) (xy 124 101) (xy 124 119) (xy 101 119)))\n\t)\n"
)
ARC = (
    '\t(arc (start 112.825 103) (mid 114 104) (end 115 105) (width 0.25) (layer "F.Cu") (net 2) '
    '(uuid "00000000-0000-0000-0000-000000000002"))\n'
)


def test_zones_and_arcs_are_reported_not_dropped(tmp_path):
    """The scope guard: zones and arcs are out of the first cut and must be reported. A board with 1 zone
    (GND on B.Cu) and 1 arc (VOUT on F.Cu) gives 2 notes, 1 each, and the router gets neither: no plane
    and no wire of VOUT in the DSN."""
    text = PCB.read_text(encoding="utf-8").replace(
        "\t(embedded_fonts no)\n)", ZONE + ARC + "\t(embedded_fonts no)\n)"
    )
    d, notes = boardroute.read_board(copy_fixture(tmp_path, text))
    assert notes == [
        "not handed to the router: zone of /GND on B.Cu (zones are out of this first cut; the DRC judges it)",
        "not handed to the router: 1 arc track (arcs are out of this first cut; the DRC judges them)",
    ]
    dsn = d.dsn()
    assert "(plane" not in dsn
    assert '(net "/VOUT") (type fix)' not in dsn


def test_an_outline_that_is_no_rectangle_is_refused(tmp_path):
    """An Edge.Cuts gr_poly of 3 corners is not a rectangle: the reader refuses it and names it, rather
    than route inside a box the board does not have."""
    rect = "(gr_rect (start 100 100) (end 125 120)"
    poly = "(gr_poly (pts (xy 100 100) (xy 125 100) (xy 100 120))"
    text = PCB.read_text(encoding="utf-8").replace(rect, poly)
    with pytest.raises(ValueError, match=r"Edge\.Cuts: gr_poly"):
        boardroute.read_board(copy_fixture(tmp_path, text))


def standin_env(tmp_path: Path, ses: str) -> dict[str, str]:
    """A `java` that runs the stand-in router and a jar that holds its plan: it writes `ses`."""
    java = tmp_path / "java"
    java.write_text(
        f"#!{sys.executable}\nimport runpy\nrunpy.run_path({str(STANDIN)!r}, run_name='__main__')\n"
    )
    java.chmod(java.stat().st_mode | stat.S_IXUSR)
    jar = tmp_path / "standin.jar"
    jar.write_text(json.dumps({"ses": ses, "log": "", "exit": 0}), encoding="utf-8")
    return {"JAVA": str(java), "FREEROUTING_JAR": str(jar), "DISPLAY": ":0"}


# 1 GND track from J1-3 (105, 110.08) to (110, 110.08) on F.Cu, 0.25 mm wide, a via at its end, and the
# router's echo of the first fixed VIN track, all in 0.1 um with y up (resolution um 10).
SESSION = (
    '(session "rc_divider" (routes (resolution um 10) (network_out '
    '(net "/GND" (wire (path F.Cu 2500 1050000 -1100800 1100000 -1100800)) '
    '(via "Via[0-1]_600:300_um" 1100000 -1100800)) '
    '(net "/VIN" (wire (path F.Cu 2500 1050000 -1050000 1090000 -1050000))))))\n'
)


def test_apply_writes_the_route_into_the_board_file(tmp_path, monkeypatch):
    """The stand-in's session adds 1 track and 1 via of GND (net 3 in the file's table) and echoes 1 VIN
    track. The board keeps its 3 VIN tracks byte for byte (their uuids stay), gains 1 segment and 1 via,
    and the echo adds nothing: 3 + 1 = 4 segments. The board before the route is kept in the build
    folder."""
    pcb = copy_fixture(tmp_path)
    before = pcb.read_text(encoding="utf-8")
    for key, value in standin_env(tmp_path, SESSION).items():
        monkeypatch.setenv(key, value)
    summary = boardroute.apply(pcb, tmp_path / "build" / "route", passes=1)
    after = pcb.read_text(encoding="utf-8")
    assert (summary["segments"], summary["vias"]) == (1, 1)
    old = [ln.strip() for ln in before.splitlines() if ln.strip().startswith("(segment")]
    new = [ln.strip() for ln in after.splitlines() if ln.strip().startswith("(segment")]
    assert len(new) == 4 and new[:3] == old
    assert '(segment (start 105 110.08) (end 110 110.08) (width 0.25) (layer "F.Cu") (net 3)' in new[3]
    assert '(via (at 110 110.08) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 3)' in after
    assert (tmp_path / "build" / "route" / "rc_divider.before.kicad_pcb").read_text(
        encoding="utf-8"
    ) == before
    assert after.rstrip().endswith(")") and after.count("(kicad_pcb") == 1


def test_apply_on_named_nets_writes_named_nets(tmp_path, monkeypatch):
    """KiCad 10 saves a pad's net by its name alone, with no table of numbered nets. The board's own
    form is kept: the new segment says (net "/GND")."""
    text = PCB.read_text(encoding="utf-8")
    for i, name in ((1, "/VIN"), (2, "/VOUT"), (3, "/GND")):
        text = text.replace(f'\t(net {i} "{name}")\n', "").replace(f'(net {i} "{name}")', f'(net "{name}")')
        text = text.replace(f"(net {i}) (uuid", f'(net "{name}") (uuid')
    text = text.replace('\t(net 0 "")\n', "")
    pcb = copy_fixture(tmp_path, text)
    for key, value in standin_env(tmp_path, SESSION).items():
        monkeypatch.setenv(key, value)
    boardroute.apply(pcb, tmp_path / "build" / "route", passes=1)
    after = pcb.read_text(encoding="utf-8")
    assert '(layer "F.Cu") (net "/GND") (uuid' in after
    assert "(net 3)" not in after


def test_a_router_that_fails_leaves_the_board_as_it_was(tmp_path, monkeypatch):
    """No session from the router: the route raises and the board file is not touched."""
    pcb = copy_fixture(tmp_path)
    before = pcb.read_text(encoding="utf-8")
    env = standin_env(tmp_path, "")
    plan = json.loads(Path(env["FREEROUTING_JAR"]).read_text(encoding="utf-8"))
    plan.update(ses=None, exit=1)
    Path(env["FREEROUTING_JAR"]).write_text(json.dumps(plan), encoding="utf-8")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    with pytest.raises(RuntimeError):
        boardroute.apply(pcb, tmp_path / "build" / "route", passes=1)
    assert pcb.read_text(encoding="utf-8") == before
    assert sorted(os.listdir(pcb.parent)) == [
        "rc_divider.kicad_pcb",
        "rc_divider.kicad_pro",
        "rc_divider.kicad_sch",
    ]
