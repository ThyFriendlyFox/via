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
    with pytest.raises(ValueError, match=r"Edge\.Cuts: 1 gr_poly: no rectangle"):
        boardroute.read_board(copy_fixture(tmp_path, text))


RECT = "(gr_rect (start 100 100) (end 125 120)"
# The fixture's outline node, its 2 lines whole.
RECT_LINE = (
    "\t(gr_rect (start 100 100) (end 125 120)\n"
    '\t\t(stroke (width 0.1) (type default)) (fill no) (layer "Edge.Cuts") '
    '(uuid "e7ba35df-4f74-5324-a7c8-565e645a9388"))\n'
)
assert PCB.read_text(encoding="utf-8").count(RECT_LINE) == 1


def edge_line(a: tuple[float, float], b: tuple[float, float]) -> str:
    return (
        f"\t(gr_line (start {a[0]} {a[1]}) (end {b[0]} {b[1]}) (stroke (width 0.05) (type default)) "
        '(layer "Edge.Cuts"))\n'
    )


def test_gr_lines_that_close_a_rectangle_are_the_outline(tmp_path):
    """The outline drawn as 4 gr_lines, one of them end to start, as KiCad's line tool leaves them:
    (100,100)-(125,100), (125,120)-(125,100), (125,120)-(100,120), (100,120)-(100,100). They close the
    same box as the fixture's gr_rect: (100, 100, 125, 120)."""
    lines = (
        edge_line((100, 100), (125, 100))
        + edge_line((125, 120), (125, 100))
        + edge_line((125, 120), (100, 120))
        + edge_line((100, 120), (100, 100))
    )
    text = PCB.read_text(encoding="utf-8").replace(RECT_LINE, lines)
    d, _ = boardroute.read_board(copy_fixture(tmp_path, text))
    assert d.outline == (100.0, 100.0, 125.0, 120.0)


def test_gr_lines_with_an_open_side_are_refused(tmp_path):
    """3 sides of the box and no 4th: the corners are those of a rectangle, but the left side
    (100,120)-(100,100) is missing, so the lines close nothing."""
    lines = (
        edge_line((100, 100), (125, 100))
        + edge_line((125, 100), (125, 120))
        + edge_line((125, 120), (100, 120))
    )
    text = PCB.read_text(encoding="utf-8").replace(RECT_LINE, lines)
    with pytest.raises(ValueError, match=r"Edge\.Cuts: 3 gr_line: they close no rectangle"):
        boardroute.read_board(copy_fixture(tmp_path, text))


def test_a_cutout_inside_the_outline_is_refused_by_what_it_is(tmp_path):
    """F5: an outline and a slot drawn as 2 gr_rects. The refusal names what is drawn, 2 gr_rect, and
    says why, a cutout inside the outline; it does not say a gr_rect is no rectangle."""
    slot = (
        "\t(gr_rect (start 110 112) (end 112 114) (stroke (width 0.05) (type default)) (fill no) "
        '(layer "Edge.Cuts"))\n'
    )
    text = PCB.read_text(encoding="utf-8").replace(RECT_LINE, RECT_LINE + slot)
    with pytest.raises(ValueError, match=r"Edge\.Cuts: 2 gr_rect: a cutout") as caught:
        boardroute.read_board(copy_fixture(tmp_path, text))
    assert "no rectangle" not in str(caught.value)


PASTE = '(pad "" smd rect (at 0 0) (size 0.3 0.3) (layers "F.Paste"))\n\t\t'
R1_PAD1 = '(pad "1" smd roundrect (at -0.825 0) (size 0.8 0.95) (layers "F.Cu" "F.Mask" "F.Paste")'


def test_a_paste_only_pad_carries_nothing_for_the_router(tmp_path):
    """F2: a paste window with no number and no copper layer, as KiCad's QFN and LDO footprints draw
    them, on R1 (a front part). It is on its footprint's side and holds no copper: it is skipped, and R1
    keeps its 2 copper pads."""
    text = PCB.read_text(encoding="utf-8").replace(R1_PAD1, PASTE + R1_PAD1, 1)
    d, notes = boardroute.read_board(copy_fixture(tmp_path, text))
    r1 = d.parts[1]
    assert (r1.ref, [p.number for p in r1.footprint.pads]) == ("R1", ["1", "2"])
    assert notes == []


def write_pro(pcb: Path, edit) -> None:
    """The fixture's .kicad_pro beside `pcb`, changed by `edit(data)`."""
    data = json.loads((FIXTURE / "rc_divider.kicad_pro").read_text(encoding="utf-8"))
    edit(data)
    pcb.with_suffix(".kicad_pro").write_text(json.dumps(data, indent=2), encoding="utf-8")


def test_net_classes_take_their_nets_by_pattern_and_by_assignment(tmp_path):
    """A class Power (0.5 mm track, 0.3 mm clearance, 0.8/0.4 mm via) takes the nets that match the
    pattern /V*: /VIN and /VOUT. A class Gnd with only a 0.4 mm track takes /GND by assignment; the rest
    of its rules are the Default class's: 0.2 mm clearance, 0.6/0.3 mm via."""
    pcb = copy_fixture(tmp_path)

    def edit(data: dict) -> None:
        ns = data["net_settings"]
        ns["classes"] += [
            {"name": "Power", "track_width": 0.5, "clearance": 0.3, "via_diameter": 0.8, "via_drill": 0.4},
            {"name": "Gnd", "track_width": 0.4},
        ]
        ns["netclass_patterns"] = [{"netclass": "Power", "pattern": "/V*"}]
        ns["netclass_assignments"] = {"/GND": ["Gnd"]}

    write_pro(pcb, edit)
    d, _ = boardroute.read_board(pcb)
    assert d.net_classes == {
        "Power": {"width": 0.5, "clearance": 0.3, "via": 0.8, "via_drill": 0.4, "nets": ["/VIN", "/VOUT"]},
        "Gnd": {"width": 0.4, "clearance": 0.2, "via": 0.6, "via_drill": 0.3, "nets": ["/GND"]},
    }


def test_an_assignment_beats_a_pattern_and_default_is_no_class_of_its_own(tmp_path):
    """/VOUT is assigned to Gnd and matches Power's pattern /V*: the assignment wins. /VIN is assigned to
    Default: it stays on the design's own rules, and Default is no entry among the net classes."""
    pcb = copy_fixture(tmp_path)

    def edit(data: dict) -> None:
        ns = data["net_settings"]
        ns["classes"] += [{"name": "Power", "track_width": 0.5}, {"name": "Gnd", "track_width": 0.4}]
        ns["netclass_patterns"] = [{"netclass": "Power", "pattern": "/V*"}]
        ns["netclass_assignments"] = {"/VOUT": ["Gnd"], "/VIN": "Default"}

    write_pro(pcb, edit)
    d, _ = boardroute.read_board(pcb)
    assert {name: spec["nets"] for name, spec in d.net_classes.items()} == {"Gnd": ["/VOUT"]}


def test_copper_layers_out_of_kicads_order_are_refused(tmp_path):
    """B.Cu listed before F.Cu: the count is right, the order is not, and the reader refuses it."""
    text = PCB.read_text(encoding="utf-8").replace(
        '\t\t(0 "F.Cu" signal)\n\t\t(2 "B.Cu" signal)\n', '\t\t(2 "B.Cu" signal)\n\t\t(0 "F.Cu" signal)\n'
    )
    with pytest.raises(ValueError, match=r"copper layers \['B\.Cu', 'F\.Cu'\]"):
        boardroute.read_board(copy_fixture(tmp_path, text))


def test_board_rules_and_the_fab_file_beside_the_board_are_read(tmp_path):
    """The .kicad_pro's rules go to the design: min_hole_clearance 0.25 and min_via_diameter 0.5 as the
    fixture's file holds them, and min_copper_edge_clearance changed here to 0.7. A rc_divider.kicad_dru
    beside the board is the fab's rules; with none, the design names no fab."""
    pcb = copy_fixture(tmp_path)
    d, _ = boardroute.read_board(pcb)
    assert d.fab == ""
    write_pro(
        pcb, lambda data: data["board"]["design_settings"]["rules"].update(min_copper_edge_clearance=0.7)
    )
    dru = pcb.with_suffix(".kicad_dru")
    dru.write_text("(version 1)\n", encoding="utf-8")
    d, _ = boardroute.read_board(pcb)
    assert (d.rules["min_hole_clearance"], d.rules["min_via_diameter"], d.edge_clearance) == (0.25, 0.5, 0.7)
    assert d.fab == str(dru)


KEEPOUT = (
    '\t(zone (net 0) (net_name "") (layers "F.Cu" "B.Cu") (uuid "00000000-0000-0000-0000-000000000003")\n'
    "\t\t(keepout (tracks not_allowed) (vias not_allowed) (pads allowed) (copperpour not_allowed) "
    "(footprints allowed))\n"
    "\t\t(polygon (pts (xy 120 101) (xy 124 101) (xy 124 104) (xy 120 104)))\n\t)\n"
)
LOOSE = (
    '\t(segment (start 121 115) (end 123 115) (width 0.25) (layer "F.Cu") (net 0) '
    '(uuid "00000000-0000-0000-0000-000000000004"))\n'
)
FP_EDGE = (
    '\t\t(fp_line (start -0.5 -0.2) (end 0.5 -0.2) (stroke (width 0.05) (type solid)) (layer "Edge.Cuts") '
    '(uuid "00000000-0000-0000-0000-000000000005"))\n\t\t'
)


def test_a_keepout_edge_cuts_in_a_footprint_and_tracks_on_no_net_are_reported(tmp_path):
    """The scope guard's other 3 notes, in the reader's order (footprints, tracks, zones): 1 Edge.Cuts
    line drawn in R1, 1 segment on net 0 (no pad's net), and a keepout on F.Cu and B.Cu, which is named
    a keepout, not a zone of a net."""
    text = PCB.read_text(encoding="utf-8").replace(R1_PAD1, FP_EDGE + R1_PAD1, 1)
    text = text.replace("\t(embedded_fonts no)\n)", LOOSE + KEEPOUT + "\t(embedded_fonts no)\n)")
    _, notes = boardroute.read_board(copy_fixture(tmp_path, text))
    assert notes == [
        "not handed to the router: Edge.Cuts drawn in footprint R1 (1 shapes; the DRC judges them)",
        "not handed to the router: 1 tracks and vias on no net of a pad (the DRC judges them)",
        "not handed to the router: keepout zone on F.Cu, B.Cu (zones are out of this first cut; the DRC "
        "judges it)",
    ]


def test_write_board_cuts_a_hand_track_the_route_dropped():
    """The route holds 2 of the 3 VIN tracks: the 3rd, (109,103)-(111.175,103), uuid cf87de58..., goes
    with its line, and nothing else changes: 3 segments in, 2 out."""
    text = PCB.read_text(encoding="utf-8")
    d, _ = boardroute.read_board(PCB)
    d.segments = d.segments[:2]
    out = boardroute.write_board(text, d)
    dropped = next(ln for ln in text.splitlines(keepends=True) if "cf87de58" in ln)
    assert out == text.replace(dropped, "")
    assert out.count("(segment") == 2


def test_write_board_puts_new_copper_before_embedded_fonts():
    """KiCad writes (embedded_fonts no) last in the board: the 1 new GND segment goes on the line before
    it, at the root's depth."""
    text = PCB.read_text(encoding="utf-8")
    d, _ = boardroute.read_board(PCB)
    d.segments.append(("/GND", (105.0, 110.08), (110.0, 110.08), 0.25, "F.Cu"))
    out = boardroute.write_board(text, d)
    lines = out.splitlines()
    assert lines[-3].startswith("\t(segment (start 105 110.08) (end 110 110.08)")
    assert lines[-2:] == ["\t(embedded_fonts no)", ")"]


@pytest.mark.parametrize(
    ("pro_text", "said"),
    [
        (
            (FIXTURE / "rc_divider.kicad_pro")
            .read_text(encoding="utf-8")
            .replace('"track_width": 0.25', '"track_width": null', 1),
            r"rc_divider\.kicad_pro: net_settings\.classes\[Default\]\.track_width: null",
        ),
        ("[]", r"rc_divider\.kicad_pro: the file holds a list, not a JSON object"),
        ("{", r"rc_divider\.kicad_pro: not JSON"),
    ],
    ids=["null-track-width", "a-list", "not-json"],
)
def test_a_wrong_project_file_is_refused_by_name(tmp_path, pro_text, said):
    """F4: a wrong .kicad_pro is a refusal (ValueError) that names the file and the place, never a
    traceback from inside the reader."""
    pcb = copy_fixture(tmp_path)
    pcb.with_suffix(".kicad_pro").write_text(pro_text, encoding="utf-8")
    with pytest.raises(ValueError, match=said):
        boardroute.read_board(pcb)


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


def load_cli():
    """tools/workcenter as a module, to call autoroute_apply with the DRC stood in for."""
    import importlib.machinery
    import types

    cli = ROOT / "tools" / "workcenter"
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_r15", str(cli))
    module = types.ModuleType("workcenter_cli_r15")
    module.__file__ = str(cli)
    sys.modules[module.__name__] = module
    loader.exec_module(module)
    return module


# Only 1 GND track: VOUT's 4 pads and 1 of GND's 2 links stay open.
GND_ONLY = (
    '(session "rc_divider" (routes (resolution um 10) (network_out '
    '(net "/GND" (wire (path F.Cu 2500 1050000 -1100800 1100000 -1100800))))))\n'
)


@pytest.mark.parametrize(("severity", "status"), [("error", "pass"), ("warning", "pass"), ("ignore", "skip")])
def test_apply_passes_only_when_the_drc_can_list_open_connections(tmp_path, monkeypatch, severity, status):
    """F1. FreeRouting 1.9.0 logs no count of open connections, so the DRC's unconnected list is the only
    judge, and a .kicad_pro that sets unconnected_items to "ignore" empties it. The DRC is stood in for
    by one that lists nothing, as KiCad does then. With the setting at "error" an empty list is a pass;
    at "ignore" the open connections are not judged: no pass, and the line says why."""
    cli = load_cli()
    pcb = copy_fixture(tmp_path)
    write_pro(pcb, lambda data: data["board"]["design_settings"]["rule_severities"].update(
        unconnected_items=severity
    ))  # fmt: skip
    for key, value in standin_env(tmp_path, GND_ONLY).items():
        monkeypatch.setenv(key, value)
    clean = {"error": 0, "warning": 0, "other": 0}
    drc = cli.Result(
        "drc",
        "pass",
        "0 errors, 0 warnings (0 unconnected, 0 parity)",
        {"counts": {"violations": clean, "unconnected_items": clean, "schematic_parity": clean}},
    )
    monkeypatch.setattr(cli, "gate_drc", lambda project, out: drc)
    project = cli.Project(pcb.parent, "rc_divider", pcb.with_suffix(".kicad_pro"), None, pcb)
    result = cli.autoroute_apply(project, tmp_path / "out", None, 1, 0, 60)
    assert result.status == status, result
    if severity == "ignore":
        assert (
            "open connections not judged: rc_divider.kicad_pro sets unconnected_items to ignore"
            in result.summary
        )


# ---- the write into the person's board file (review W1, W3, L1)

GND_TRACK = ("/GND", (105.0, 110.08), (110.0, 110.08), 0.25, "F.Cu")


def stand_in_route(monkeypatch, during=None) -> list[int]:
    """kicadgen.route stood in for: it adds GND_TRACK, after running `during()` when given. Returns the
    list each call appends to, so a test can say the router never ran."""
    calls: list[int] = []

    def route(d, build_dir, **_):
        calls.append(1)
        Path(build_dir).mkdir(parents=True, exist_ok=True)
        if during:
            during()
        d.segments.append(GND_TRACK)
        return {"segments": 1, "vias": 0, "unrouted": None, "dsn": "", "ses": "", "log": ""}

    monkeypatch.setattr(boardroute.kicadgen, "route", route)
    return calls


def test_a_read_only_board_is_refused_before_the_route(tmp_path, monkeypatch):
    """W1: a board file with no write bit (chmod 0444) is the person's to keep as it is, root or not: it
    is refused by name before the router runs, and the file is untouched, its mode too."""
    pcb = copy_fixture(tmp_path)
    before = pcb.read_bytes()
    pcb.chmod(0o444)
    calls = stand_in_route(monkeypatch)
    with pytest.raises(boardroute.NotWritten, match=r"rc_divider\.kicad_pcb is read-only; nothing written"):
        boardroute.apply(pcb, tmp_path / "build")
    assert (pcb.read_bytes(), stat.S_IMODE(pcb.stat().st_mode), calls) == (before, 0o444, [])


def test_the_board_keeps_its_mode_and_no_routing_file_is_left(tmp_path, monkeypatch):
    """W1 and the atomic write: a board at mode 0640 is still 0640 after the route, holds the new GND
    track, and nothing but the project's own files is left beside it (the .routing file was renamed
    over the board, not copied into it)."""
    pcb = copy_fixture(tmp_path)
    pcb.chmod(0o640)
    stand_in_route(monkeypatch)
    boardroute.apply(pcb, tmp_path / "build")
    assert stat.S_IMODE(pcb.stat().st_mode) == 0o640
    assert "(segment (start 105 110.08) (end 110 110.08)" in pcb.read_text(encoding="utf-8")
    assert sorted(os.listdir(pcb.parent)) == [
        "rc_divider.kicad_pcb",
        "rc_divider.kicad_pro",
        "rc_divider.kicad_sch",
    ]


def test_a_symlinked_board_is_written_through_to_its_target(tmp_path, monkeypatch):
    """W1: the board is a symbolic link to real.kicad_pcb. The link stays a link, and the route goes
    into the file it names."""
    pcb = copy_fixture(tmp_path)
    real = pcb.with_name("real.kicad_pcb")
    pcb.rename(real)
    pcb.symlink_to(real.name)
    stand_in_route(monkeypatch)
    boardroute.apply(pcb, tmp_path / "build")
    assert pcb.is_symlink()
    assert "(segment (start 105 110.08) (end 110 110.08)" in real.read_text(encoding="utf-8")


def test_a_board_open_in_kicad_is_refused(tmp_path, monkeypatch):
    """W1: KiCad's lock file ~rc_divider.kicad_pcb.lck beside the board says the editor has it open; a
    save there would undo the route, or the route the person's edits. Refused before the route."""
    pcb = copy_fixture(tmp_path)
    before = pcb.read_bytes()
    (pcb.parent / "~rc_divider.kicad_pcb.lck").write_text('{"hostname":"h","username":"u"}')
    calls = stand_in_route(monkeypatch)
    with pytest.raises(boardroute.NotWritten, match=r"~rc_divider\.kicad_pcb\.lck.*nothing written"):
        boardroute.apply(pcb, tmp_path / "build")
    assert (pcb.read_bytes(), calls) == (before, [])


def test_an_edit_saved_during_the_route_is_kept_and_the_route_refused(tmp_path, monkeypatch):
    """W1: the person saves the board while the router runs (here: a comment line appended). The route
    was made from the old text, so it is refused and the person's save stays as they made it."""
    pcb = copy_fixture(tmp_path)

    def save():
        pcb.write_text(pcb.read_text(encoding="utf-8") + ";saved\n", encoding="utf-8")

    stand_in_route(monkeypatch, during=save)
    with pytest.raises(boardroute.NotWritten, match=r"rc_divider\.kicad_pcb changed while the router ran"):
        boardroute.apply(pcb, tmp_path / "build")
    text = pcb.read_text(encoding="utf-8")
    assert text.endswith(";saved\n") and "110.08) (end 110 110.08)" not in text
    assert not pcb.with_name(pcb.name + ".routing").exists()


def test_a_failing_write_leaves_the_board_whole_and_nothing_beside_it(tmp_path, monkeypatch):
    """L1: the disk fills while the .routing file is written (OSError 28 after half the text). The
    refusal says the board is as it was, the board is byte for byte the same, and the half-written
    .routing file is gone."""
    pcb = copy_fixture(tmp_path)
    before = pcb.read_bytes()
    stand_in_route(monkeypatch)
    real_write = Path.write_text

    def full(self, data, *args, **kwargs):
        if self.name.endswith(".routing"):
            real_write(self, data[: len(data) // 2], *args, **kwargs)
            raise OSError(28, "No space left on device")
        return real_write(self, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", full)
    with pytest.raises(boardroute.NotWritten, match=r"No space left on device.*is as it was"):
        boardroute.apply(pcb, tmp_path / "build")
    assert pcb.read_bytes() == before
    assert not pcb.with_name(pcb.name + ".routing").exists()


def test_a_second_route_keeps_the_first_before_file(tmp_path, monkeypatch):
    """W3: the .before file is the way back. A second run keeps the first one (the board as the person
    drew it) and puts the board before the second run in rc_divider.before-2.kicad_pcb."""
    pcb = copy_fixture(tmp_path)
    drawn = pcb.read_text(encoding="utf-8")
    stand_in_route(monkeypatch)
    first = boardroute.apply(pcb, tmp_path / "build")
    once = pcb.read_text(encoding="utf-8")
    second = boardroute.apply(pcb, tmp_path / "build")
    assert (tmp_path / "build" / "rc_divider.before.kicad_pcb").read_text(encoding="utf-8") == drawn
    assert (tmp_path / "build" / "rc_divider.before-2.kicad_pcb").read_text(encoding="utf-8") == once
    assert (Path(first["before"]).name, Path(second["before"]).name) == (
        "rc_divider.before.kicad_pcb",
        "rc_divider.before-2.kicad_pcb",
    )


# ---- the person's own tracks (review W2, L2)

LOCKED_LINE = (
    '\t(segment (start 105 105) (end 109 105) (width 0.25) (locked yes) (layer "F.Cu") (net 1) '
    '(uuid "9fb782b0-88c2-588c-a766-3541cf77e007"))\n'
)
# The router's T onto the middle of the first VIN track, (107, 105) down to (107, 108).
T_SESSION = (
    '(session "rc_divider" (routes (resolution um 10) (network_out '
    '(net "/VIN" (wire (path F.Cu 2500 1070000 -1050000 1070000 -1080000))))))\n'
)


def locked_fixture(tmp_path: Path) -> Path:
    text = PCB.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines(keepends=True) if "9fb782b0" in ln)
    return copy_fixture(tmp_path, text.replace(line, LOCKED_LINE))


def test_a_locked_hand_track_under_a_T_keeps_its_lock_and_uuid(tmp_path, monkeypatch):
    """W2: the person's first VIN track is locked; the router (the stand-in, through the real session
    merge) draws a T onto its middle. The locked track stays byte for byte, the other 2 hand tracks
    too, and only the router's T is added: 3 + 1 segments. KiCad joins a track end that lies on another
    track, so the hand track need not be cut at the T."""
    pcb = locked_fixture(tmp_path)
    before = pcb.read_text(encoding="utf-8")
    for key, value in standin_env(tmp_path, T_SESSION).items():
        monkeypatch.setenv(key, value)
    summary = boardroute.apply(pcb, tmp_path / "build", passes=1)
    after = pcb.read_text(encoding="utf-8")
    assert LOCKED_LINE in after
    old = [ln for ln in before.splitlines() if ln.strip().startswith("(segment")]
    new = [ln for ln in after.splitlines() if ln.strip().startswith("(segment")]
    assert new[:3] == old and len(new) == 4
    assert new[3].startswith('\t(segment (start 107 105) (end 107 108) (width 0.25) (layer "F.Cu") (net 1)')
    assert (summary["segments"], summary["notes"]) == (1, [])


def test_write_board_never_cuts_a_locked_track():
    """W2: a design that no longer holds the locked track is refused by the track's uuid, not written
    without it."""
    text = PCB.read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines(keepends=True) if "9fb782b0" in ln)
    text = text.replace(line, LOCKED_LINE)
    d, _ = boardroute.read_board(PCB)
    d.segments = d.segments[1:]
    with pytest.raises(ValueError, match=r"locked hand track 9fb782b0-88c2-588c-a766-3541cf77e007 on /VIN"):
        boardroute.write_board(text, d)


def test_write_board_says_each_hand_track_it_removes():
    """W2: the line for the 3rd VIN track the design dropped: its uuid, its net, and why."""
    text = PCB.read_text(encoding="utf-8")
    d, _ = boardroute.read_board(PCB)
    d.segments = d.segments[:2]
    said: list[str] = []
    boardroute.write_board(text, d, said)
    assert said == [
        "removed hand track cf87de58-1965-564d-98b7-e3b5cd6f9614 on /VIN: the route holds it no more"
    ]


EMPTY_SESSION = '(session "rc_divider" (routes (resolution um 10) (network_out)))\n'


def test_a_route_that_adds_nothing_leaves_a_board_with_a_T_byte_for_byte(tmp_path, monkeypatch):
    """W2: pass-rc-divider holds hand tracks that end on another track's middle (a T at (115, 107.54)
    and at (121, 107.54)). The stand-in's session adds nothing: the board file is byte for byte as it
    was, no track cut, none moved to 107.539996."""
    src = ROOT / "tests" / "boards" / "pass-rc-divider"
    folder = tmp_path / "rc"
    folder.mkdir()
    for f in src.glob("rc_divider.kicad_p[cr]*"):
        (folder / f.name).write_bytes(f.read_bytes())
    pcb = folder / "rc_divider.kicad_pcb"
    before = pcb.read_bytes()
    for key, value in standin_env(tmp_path, EMPTY_SESSION).items():
        monkeypatch.setenv(key, value)
    boardroute.apply(pcb, tmp_path / "build", passes=1)
    assert pcb.read_bytes() == before


# The router's wire ends 0.4 um right of the hand track's end at (109, 105), then runs down to y 108.
NEAR_SESSION = (
    '(session "rc_divider" (routes (resolution um 10) (network_out '
    '(net "/VIN" (wire (path F.Cu 2500 1090004 -1050000 1090004 -1080000))))))\n'
)


def test_a_router_end_within_1_um_of_a_hand_end_is_written_on_it(tmp_path, monkeypatch):
    """L2: the router's end at (109.0004, 105) is 0.4 um from the hand tracks' corner (109, 105): it is
    written at the corner, so the 2 ends meet in the file; its other end, 3 mm away from any, stays."""
    pcb = copy_fixture(tmp_path)
    for key, value in standin_env(tmp_path, NEAR_SESSION).items():
        monkeypatch.setenv(key, value)
    boardroute.apply(pcb, tmp_path / "build", passes=1)
    assert "\t(segment (start 109 105) (end 109.0004 108) (width 0.25)" in pcb.read_text(encoding="utf-8")


# ---- the reader's guards and the flip (review T1)

R2_AT = '(layer "B.Cu") (uuid "13de3444-70c1-502f-8221-dd68243c2678") (at 118 107.54)'
R2_PAD1 = '(pad "1" smd roundrect (at -0.825 0) (size 0.8 0.95) (layers "B.Cu"'
R2_PAD2 = '(pad "2" smd roundrect (at 0.825 0) (size 0.8 0.95) (layers "B.Cu"'


def dsn_pins(dsn: str) -> dict[str, tuple[float, float]]:
    """Each pin's place on the board, in mm with y down, from the DSN: the image's pin, mirrored about
    the Y axis on the back side, turned by the placement, moved to it."""
    import math
    import re

    images: dict[str, dict[str, tuple[float, float]]] = {}
    current: dict[str, tuple[float, float]] = {}
    for line in dsn.splitlines():
        m = re.match(r'\s*\(image "([^"]+)"', line)
        if m:
            current = images.setdefault(m.group(1), {})
        m = re.match(r'\s*\(pin \S+ "([^"]+)" (-?\d+) (-?\d+)\)', line)
        if m:
            current[m.group(1)] = (int(m.group(2)) / 1e4, int(m.group(3)) / 1e4)
    out = {}
    for m in re.finditer(r'\(component "([^"]+)"\s*\(place "([^"]+)" (-?\d+) (-?\d+) (\w+) ([-\d.]+)\)', dsn):
        image, ref, x, y, side, rot = m.groups()
        a = math.radians(float(rot))
        for number, (ix, iy) in images[image].items():
            ix = -ix if side == "back" else ix
            dx, dy = ix * math.cos(a) - iy * math.sin(a), ix * math.sin(a) + iy * math.cos(a)
            out[f"{ref}-{number}"] = (round(int(x) / 1e4 + dx, 4), round(-(int(y) / 1e4 + dy), 4))
    return out


def test_a_back_part_turned_with_pads_off_its_axis_reaches_the_router_where_the_file_has_it(tmp_path):
    """T1: R2 on the back, turned 30 degrees, its pads moved off its axis to (-0.825, 0.3) and (0.825,
    -0.2) and written at 345 degrees, as KiCad writes a back pad of library angle 45 (30 - 45). The
    reader gives the library frame: y negated, angle 45. Every pin of the DSN lands where the file puts
    its pad: x = 118 + px cos 30 + py sin 30, y = 107.54 - px sin 30 + py cos 30 (KiCad's turn, y down)."""
    import math

    text = PCB.read_text(encoding="utf-8").replace(R2_AT, R2_AT[:-1] + " 30)")
    text = text.replace(R2_PAD1, R2_PAD1.replace("(at -0.825 0)", "(at -0.825 0.3 345)"))
    text = text.replace(R2_PAD2, R2_PAD2.replace("(at 0.825 0)", "(at 0.825 -0.2 345)"))
    d, _ = boardroute.read_board(copy_fixture(tmp_path, text))
    r2 = d.parts[2]
    assert [(p.number, p.x, p.y, p.angle) for p in r2.footprint.pads] == [
        ("1", -0.825, -0.3, 45.0),
        ("2", 0.825, 0.2, 45.0),
    ]
    a = math.radians(30)
    pins = dsn_pins(d.dsn())
    for number, (px, py) in (("1", (-0.825, 0.3)), ("2", (0.825, -0.2))):
        want = (118 + px * math.cos(a) + py * math.sin(a), 107.54 - px * math.sin(a) + py * math.cos(a))
        got = pins[f"R2-{number}"]
        assert math.hypot(got[0] - want[0], got[1] - want[1]) < 0.001, (number, got, want)


def test_a_surface_pad_on_the_far_side_of_its_footprint_is_refused(tmp_path):
    """T1: R1 is on the front and its pad 1 is a surface pad on B.Cu: this first cut refuses it by the
    part and the pad, rather than hand the router a pad on the wrong side."""
    text = PCB.read_text(encoding="utf-8").replace(
        R1_PAD1, R1_PAD1.replace('(layers "F.Cu" "F.Mask" "F.Paste")', '(layers "B.Cu" "B.Mask")'), 1
    )
    with pytest.raises(ValueError, match=r"R1 pad 1: a surface pad on \['B\.Cu', 'B\.Mask'\]"):
        boardroute.read_board(copy_fixture(tmp_path, text))


VIA = (
    '\t(via (at 110 110.08) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 3) '
    '(uuid "00000000-0000-0000-0000-000000000006"))\n'
)


def test_a_hand_via_is_handed_to_the_router(tmp_path):
    """T1: a GND via drawn by hand goes to the design as fixed copper, like the hand tracks."""
    text = PCB.read_text(encoding="utf-8").replace(
        "\t(embedded_fonts no)\n)", VIA + "\t(embedded_fonts no)\n)"
    )
    d, _ = boardroute.read_board(copy_fixture(tmp_path, text))
    assert d.vias == [("/GND", (110.0, 110.08), 0.6, 0.3)]


def test_write_board_leaves_a_track_on_no_net_of_a_pad_alone():
    """T1: a track on net 0 was never handed to the router; writing the design back keeps it."""
    text = PCB.read_text(encoding="utf-8").replace(
        "\t(embedded_fonts no)\n)", LOOSE + "\t(embedded_fonts no)\n)"
    )
    d, _ = boardroute.read_board(PCB)
    assert boardroute.write_board(text, d) == text


def test_a_pad_with_no_number_is_no_pin_and_its_net_is_the_last_name(tmp_path):
    """T1: on R1, a copper pad with no number but a net is in the router's way and on no net's pin
    list; and a pad net written with its number quoted too, (net "2" "/VOUT"), is /VOUT, the last
    name."""
    extra = '(pad "" smd rect (at 0 0.6) (size 0.3 0.3) (layers "F.Cu") (net 2 "/VOUT"))\n\t\t'
    text = PCB.read_text(encoding="utf-8").replace(R1_PAD1, extra + R1_PAD1, 1)
    text = text.replace('(net 2 "/VOUT")', '(net "2" "/VOUT")')
    d, _ = boardroute.read_board(copy_fixture(tmp_path, text))
    r1 = d.parts[1]
    assert [p.number for p in r1.footprint.pads] == ["@0", "1", "2"]
    assert r1.nets == {"2": "/VOUT", "1": "/VIN"}


def stood_in_cli(monkeypatch, tmp_path, route: dict, drc_status: str, unconnected: int, failures=()):
    """tools/workcenter with boardroute.apply and the DRC stood in for: `route` is the router's summary,
    the DRC says `drc_status` with `unconnected` open connections and `failures`."""
    cli = load_cli()
    pcb = copy_fixture(tmp_path)
    summary = {"segments": 1, "vias": 0, "unrouted": None, "dsn": "d", "ses": "s", "log": "l", "notes": []}
    monkeypatch.setattr(boardroute, "apply", lambda *a, **k: {**summary, **route})
    counts = {
        "violations": {"error": 0, "warning": 0, "other": 0},
        "unconnected_items": {"error": unconnected, "warning": 0, "other": 0},
        "schematic_parity": {"error": 0, "warning": 0, "other": 0},
    }
    drc = cli.Result("drc", drc_status, "the DRC", {"counts": counts, "failures": list(failures)})
    monkeypatch.setattr(cli, "gate_drc", lambda project, out: drc)
    return cli, cli.Project(pcb.parent, "rc_divider", pcb.with_suffix(".kicad_pro"), None, pcb)


def test_apply_fails_on_the_routers_own_count_of_open_connections(tmp_path, monkeypatch):
    """T1: the router's log says 2 connections are open; the DRC is clean. That is a fail, and says so."""
    cli, project = stood_in_cli(monkeypatch, tmp_path, {"unrouted": 2}, "pass", 0)
    result = cli.autoroute_apply(project, tmp_path / "out", None, 1, 0, 60)
    assert result.status == "fail"
    assert result.details["failures"] == ["route: the router left 2 connections open (l)"]


def test_apply_names_the_drcs_count_of_unconnected_items(tmp_path, monkeypatch):
    """T1: the DRC lists 3 unconnected items: the first failure line says 3 and whose DRC."""
    cli, project = stood_in_cli(monkeypatch, tmp_path, {}, "fail", 3)
    result = cli.autoroute_apply(project, tmp_path / "out", None, 1, 0, 60)
    assert result.status == "fail"
    assert result.details["failures"][0] == "route: 3 unconnected (KiCad DRC of rc_divider.kicad_pcb)"


def test_apply_fails_when_the_drc_fails_with_no_line_of_its_own(tmp_path, monkeypatch):
    """T1: a DRC that fails and lists no failure line is still a fail, never a pass."""
    cli, project = stood_in_cli(monkeypatch, tmp_path, {}, "fail", 0)
    result = cli.autoroute_apply(project, tmp_path / "out", None, 1, 0, 60)
    assert (result.status, result.details["failures"]) == ("fail", [])


def test_apply_takes_no_dsn(tmp_path, monkeypatch):
    """T1: --apply writes its own DSN from the board; a --dsn beside it is an error, and nothing runs."""
    cli, project = stood_in_cli(monkeypatch, tmp_path, {}, "pass", 0)
    monkeypatch.setattr(boardroute, "apply", lambda *a, **k: pytest.fail("the route ran"))
    result = cli.autoroute_apply(project, tmp_path / "out", "x.dsn", 1, 0, 60)
    assert (result.status, result.summary) == (
        "error",
        "--apply writes the DSN from the board itself; it takes no --dsn",
    )


def test_a_board_not_written_is_an_error_that_says_the_board_is_as_it_was(tmp_path, monkeypatch):
    """W1 and L1 at the command: the write refused (here a read-only board) is an error result, not a
    traceback and not 'engine missing'."""
    cli = load_cli()
    pcb = copy_fixture(tmp_path)
    pcb.chmod(0o444)
    stand_in_route(monkeypatch)
    monkeypatch.setattr(cli, "gate_drc", lambda project, out: pytest.fail("the DRC ran"))
    project = cli.Project(pcb.parent, "rc_divider", pcb.with_suffix(".kicad_pro"), None, pcb)
    result = cli.autoroute_apply(project, tmp_path / "out", None, 1, 0, 60)
    assert result.status == "error"
    assert result.summary == "rc_divider.kicad_pcb is read-only; nothing written"
