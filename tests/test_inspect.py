"""Tests for `workcenter inspect` and `tools/stretch.py`.

`inspect` reads a board with KiCad's own geometry (pcbnew, under the venv's Python). Its fixture board
is tests/boards/inspect-four-layer, generated from the design.py beside it: four layers, VIN's 10 mm
run of 0.2 mm track on In2.Cu between two vias, a T-junction, a copper keep-out ("pocket") over a
pour island on purpose (C1.2), a parts keep-out ("strip"), and Sierra's rule file with its 13 mil
inner drill rule. The two-layer divider (pass-rc-divider) has no stackup.
"""

from __future__ import annotations

import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import kicadgen  # noqa: E402

CLI = ROOT / "tools" / "workcenter"
ENGINE = ROOT / "tools" / "inspect_board.py"
STRETCH = ROOT / "tools" / "stretch.py"
FIXTURE = ROOT / "tests" / "boards" / "inspect-four-layer"
BOARD = FIXTURE / "four_layer.kicad_pcb"
DIVIDER = ROOT / "tests" / "boards" / "pass-rc-divider"
RHO = 1.72e-8  # copper at 20 °C, Ohm m

needs_pcbnew = pytest.mark.skipif(
    importlib.util.find_spec("pcbnew") is None, reason="KiCad's pcbnew module is not importable"
)
needs_kicad = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
needs_libs = pytest.mark.skipif(
    not (kicadgen.SYMBOL_DIR / "Device.kicad_sym").is_file(),
    reason="KiCad symbol libraries are not installed",
)


def inspect(*args: object) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "inspect", *map(str, args)], capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout, proc.stderr


def inspect_json(*args: object) -> tuple[int, dict]:
    code, out, err = inspect(*args, "--json")
    assert out.strip(), err
    return code, json.loads(out)


def cut_board(tmp_path: Path) -> Path:
    """The fixture with VIN's In2.Cu run taken out: VIN's two halves no longer meet."""
    text = BOARD.read_text(encoding="utf-8")
    runs = [b for b in re.findall(r"\t\(segment\n.*?\n\t\)\n", text, re.S) if '(layer "In2.Cu")' in b]
    assert len(runs) == 1, runs
    out = tmp_path / "cut" / BOARD.name
    out.parent.mkdir()
    out.write_text(text.replace(runs[0], ""), encoding="utf-8")
    return out


def strip_resistance(length_mm: float, width_mm: float, copper_mm: float) -> float:
    return RHO * length_mm * 1e-3 / (width_mm * 1e-3 * copper_mm * 1e-3)


# ------------------------------------------------------------------ engines


@needs_kicad
def test_pillow_imports_where_kicad_is_installed():
    """`inspect map` draws with Pillow under the venv's Python (requirements.txt); a missing Pillow
    would only skip, so this test turns that into a red run (P12)."""
    import PIL  # noqa: F401


@needs_pcbnew
def test_the_engine_skips_without_pcbnew():
    spec = json.dumps({"what": "net", "board": str(BOARD), "net": "VIN"})
    proc = subprocess.run(
        [sys.executable, "-S", str(ENGINE), spec], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 2, proc.stderr
    assert "pcbnew" in proc.stderr


# ------------------------------------------------------------------ resistance (M93)


@needs_pcbnew
def test_resistance_of_a_known_run_counts_each_layer_and_both_vias():
    """VIN: 3 mm of 0.3 mm on F.Cu, a via down, 10 mm of 0.2 mm on In2.Cu (15.2 µm, kicadgen's
    stackup), a via up, 3.0875 mm of 0.3 mm on F.Cu."""
    code, rep = inspect_json(
        "resistance", FIXTURE, "VIN", "--from", "J1.1", "--to", "R1.1", "--plating", "0.025"
    )
    assert code == 0, rep
    assert rep["stackup"] == {"F.Cu": 35.0, "In1.Cu": 15.2, "In2.Cu": 15.2, "B.Cu": 35.0}
    assert rep["stackup_from_board"] is True
    kinds = [(s["kind"], s.get("layer") or f"{s['from']}-{s['to']}") for s in rep["path"]]
    assert kinds == [
        ("track", "F.Cu"),
        ("via", "F.Cu-In2.Cu"),
        ("track", "In2.Cu"),
        ("via", "In2.Cu-F.Cu"),
        ("track", "F.Cu"),
    ], kinds
    inner = rep["path"][2]
    assert inner["length"] == pytest.approx(10.0)
    assert inner["ohm"] == pytest.approx(strip_resistance(10.0, 0.2, 0.0152), rel=1e-5)  # 56.58 mOhm
    # A barrel from F.Cu's middle to In2.Cu's: 0.035/2 + 0.2104 + 0.0152 + 1.0788 + 0.0152/2 mm.
    barrel_mm = 0.035 / 2 + 0.2104 + 0.0152 + 1.0788 + 0.0152 / 2
    ring = math.pi * ((0.15 + 0.025) ** 2 - 0.15**2) * 1e-6  # m², a 0.3 mm hole plated 25 µm
    via = RHO * barrel_mm * 1e-3 / ring
    assert rep["path"][1]["length"] == pytest.approx(barrel_mm, abs=1e-4)
    assert rep["path"][1]["ohm"] == pytest.approx(via, rel=1e-3)
    total = strip_resistance(3.0, 0.3, 0.035) + strip_resistance(10.0, 0.2, 0.0152)
    total += strip_resistance(3.0875, 0.3, 0.035) + 2 * via
    assert rep["ohm"] == pytest.approx(total, rel=1e-4)  # 68.34 mOhm
    code, warm = inspect_json("resistance", FIXTURE, "VIN", "--from", "R1.1", "--to", "J1.1", "--temp", "70")
    assert code == 0
    assert warm["path"][2]["ohm"] == pytest.approx(inner["ohm"] * (1 + 0.00393 * 50), rel=1e-5)


@needs_pcbnew
def test_resistance_follows_a_t_junction_on_a_board_without_a_stackup():
    """The divider: J1.2's run ends on the middle of the VOUT track down to C1, 10 + 4.46 + 2.225 mm of
    0.25 mm track, at KiCad's default 35 µm since the board has no stackup."""
    code, out, _ = inspect("resistance", DIVIDER, "VOUT", "--from", "J1.2", "--to", "C1.1")
    assert code == 0, out
    assert "no stackup on the board" in out
    expected = strip_resistance(10.0 + (112.0 - 107.54) + 2.225, 0.25, 0.035)  # 32.80 mOhm
    assert f"total {expected * 1000:.2f} mOhm" in out, out


@needs_pcbnew
def test_resistance_says_when_no_track_joins_the_pads():
    code, out, _ = inspect("resistance", FIXTURE, "GND", "--from", "J1.3", "--to", "R2.2")
    assert code == 1
    assert "no track path from J1.3 to R2.2" in out
    code, _, err = inspect("resistance", FIXTURE, "VIN", "--from", "J1.1", "--to", "R9.1")
    assert code == 1 and "no pad R9.1 on net VIN" in err


# ------------------------------------------------------------------ probe (M90, M91)


@needs_pcbnew
def test_probe_names_the_keepout_a_via_lands_in():
    code, rep = inspect_json("probe", FIXTURE, "--via", "113.95,110", "--net", "GND")
    assert code == 1
    assert [(c["kind"], c["item"]) for c in rep["conflicts"]] == [("keep-out", "keep-out 'pocket' (no vias)")]


@needs_pcbnew
def test_probe_holds_an_inner_layer_hole_to_the_project_rule_file(tmp_path):
    """A 0.65/0.3 mm GND via beside VIN's 0.2 mm In2.Cu run: at 0.578 mm from its centreline the copper
    clears by 0.153 mm (0.15 needed) and the hole by 0.328 mm, under Sierra's 13 mil (0.3302 mm);
    at 0.582 mm both clear. Without the rule file the board's own 0.25 mm hole clearance holds."""
    code, rep = inspect_json("probe", FIXTURE, "--via", "111,104.578", "--net", "GND")
    assert code == 1
    assert len(rep["conflicts"]) == 1, rep["conflicts"]
    hit = rep["conflicts"][0]
    assert (hit["kind"], hit["layer"], hit["net"]) == ("hole", "In2.Cu", "VIN")
    assert hit["need"] == pytest.approx(0.3302) and hit["gap"] == pytest.approx(0.328, abs=0.001)
    assert "inner drill to copper 13 mil" in hit["rule"]
    code, rep = inspect_json("probe", FIXTURE, "--via", "111,104.582", "--net", "GND")
    assert code == 0, rep["conflicts"]
    bare = tmp_path / "bare"
    bare.mkdir()
    shutil.copy(BOARD, bare)
    shutil.copy(FIXTURE / "four_layer.kicad_pro", bare)
    code, rep = inspect_json("probe", bare, "--via", "111,104.578", "--net", "GND")
    assert code == 0, rep["conflicts"]
    assert rep["rules_file"] is None


@needs_pcbnew
def test_probe_finds_a_courtyard_overlap_of_a_moved_part():
    """R2's 0805 courtyard (±1.68 mm drawn) 0.05 mm into R1's at x = 123.31, 0.05 mm clear at 123.41."""
    code, rep = inspect_json("probe", FIXTURE, "--part", "R2", "--at", "123.31,104")
    assert code == 1
    assert [(c["kind"], c["item"].split(" (")[0]) for c in rep["conflicts"]] == [
        ("courtyard", "R1 courtyard")
    ]
    code, rep = inspect_json("probe", FIXTURE, "--part", "R2", "--at", "123.41,104")
    assert code == 0, rep["conflicts"]


@needs_pcbnew
def test_probe_puts_a_part_against_copper_and_the_parts_keepout():
    code, rep = inspect_json("probe", FIXTURE, "--part", "R2", "--at", "121.5,104")
    kinds = {(c["kind"], c["by"]) for c in rep["conflicts"]}
    assert code == 1
    assert ("courtyard", "R2") in kinds and ("clearance", "R2.2") in kinds, kinds  # GND pad on OUT's track
    code, rep = inspect_json("probe", FIXTURE, "--part", "R2", "--at", "118.2,111")
    assert code == 1
    assert [c["item"] for c in rep["conflicts"]] == ["keep-out 'strip' (no footprints)"]


@needs_pcbnew
@needs_libs
def test_probe_places_a_part_the_board_does_not_have_yet():
    """A new 0805 where R1 and R2 stand: both courtyards, and its GND pad on OUT's copper. On the
    bottom face nothing is in the way. Without --footprint the probe says what it needs."""
    new = ("--part", "F9", "--footprint", "Resistor_SMD:R_0805_2012Metric", "--at", "121.5,104")
    code, rep = inspect_json("probe", FIXTURE, *new, "--nets", "1=OUT,2=GND")
    assert code == 1
    found = {(c["kind"], c["item"].split(" (")[0], c["by"]) for c in rep["conflicts"]}
    assert {("courtyard", "R1 courtyard", "F9"), ("courtyard", "R2 courtyard", "F9")} <= found, found
    assert ("clearance", "R2.1", "F9.2") in found and all(c["by"] != "F9.1" for c in rep["conflicts"])
    code, rep = inspect_json("probe", FIXTURE, *new, "--back")
    assert code == 0, rep["conflicts"]
    assert "bottom" in rep["probe"]
    code, _, err = inspect("probe", FIXTURE, "--part", "F9", "--at", "121.5,104")
    assert code == 1 and "--footprint" in err


@needs_pcbnew
def test_probe_a_track_and_a_clear_via():
    code, out, _ = inspect("probe", FIXTURE, "--track", "117,102 117,106", "--layer", "F.Cu", "--net", "OUT")
    assert code == 1
    assert "clearance  F.Cu    track F.Cu (116.000, 104.000)-(119.088, 104.000) w0.30 (VIN)" in out, out
    code, out, _ = inspect("probe", FIXTURE, "--via", "126,112", "--net", "GND")
    assert code == 0 and out.rstrip().endswith("probe: clear"), out


@needs_pcbnew
def test_probe_refuses_an_incomplete_question():
    code, _, err = inspect("probe", FIXTURE, "--via", "126,112")
    assert code == 1 and "--net" in err
    code, _, err = inspect("probe", FIXTURE, "--part", "R2")
    assert code == 1 and "--at" in err
    code, _, err = inspect("probe", FIXTURE, "--via", "126,112", "--net", "NOPE")
    assert code == 1 and "no net 'NOPE'" in err


# ------------------------------------------------------------------ net and islands (M88)


@needs_pcbnew
def test_net_lists_its_groups_and_the_one_cut_off(tmp_path):
    code, rep = inspect_json("net", FIXTURE, "GND")
    assert code == 1
    assert [g["pads"] for g in rep["groups"]] == [["J1.3", "R2.2"], ["C1.2"]]
    assert rep["unconnected"] == 1
    code, rep = inspect_json("net", FIXTURE, "OUT")  # local label: KiCad's /OUT
    assert code == 0 and rep["net"] == "/OUT" and rep["unconnected"] == 0
    assert rep["groups"][0]["pads"] == ["J1.2", "R1.2", "R2.1", "C1.1"]  # through the T and both vias
    code, rep = inspect_json("net", cut_board(tmp_path), "VIN")
    assert code == 1
    assert [g["pads"] for g in rep["groups"]] == [["J1.1"], ["R1.1"]]


@needs_pcbnew
def test_islands_names_the_pour_piece_no_via_reaches():
    code, rep = inspect_json("islands", FIXTURE)
    assert code == 1
    assert rep["islands"] == [{"pads": ["C1.2"], "vias": [], "pieces": ["pour F.Cu #1"]}]
    states = {p["piece"]: (p["state"], p["holds"]) for pieces in rep["layers"].values() for p in pieces}
    assert states["pour F.Cu #1"] == ("island", ["C1.2"])
    assert states["pour In1.Cu #1"] == ("main", ["J1.3"])
    code, rep = inspect_json("islands", FIXTURE, "--net", "VIN")
    assert code == 0 and rep["note"] == "VIN has no filled pour"


# ------------------------------------------------------------------ crossed (M89)


@needs_pcbnew
def test_crossed_lists_the_nets_and_the_one_the_new_board_leaves_open(tmp_path):
    box = ("--box", "108", "114", "103", "105")
    code, rep = inspect_json("crossed", FIXTURE, *box)
    assert code == 0
    assert [(n["net"], n["tracks"], n["layers"]) for n in rep["nets"]] == [("VIN", 1, ["In2.Cu"])]
    code, rep = inspect_json("crossed", FIXTURE, *box, "--new", FIXTURE)
    assert code == 0 and rep["nets"][0]["new"] == "connected"
    code, out, _ = inspect("crossed", FIXTURE, *box, "--new", cut_board(tmp_path))
    assert code == 1
    assert "VIN" in out and "open: 1 unconnected, groups J1.1 | R1.1, no longer crosses" in out, out
    assert out.rstrip().endswith("open on cut/four_layer.kicad_pcb: VIN"), out


# ------------------------------------------------------------------ list and map


@needs_pcbnew
def test_list_gives_what_lies_in_a_window():
    code, rep = inspect_json("list", FIXTURE, "--box", "115", "122", "103", "105")
    assert code == 0
    assert [(p["pad"], p["net"]) for p in rep["pads"]] == [("R1.1", "VIN"), ("R1.2", "/OUT")]
    assert {(t["net"], t["layer"]) for t in rep["tracks"]} == {
        ("VIN", "F.Cu"),
        ("/OUT", "F.Cu"),
        ("VIN", "In2.Cu"),
    }
    assert [v["at"] for v in rep["vias"]] == [[116.0, 104.0]]
    assert [c["ref"] for c in rep["courtyards"]] == ["R1"]
    # KiCad's own courtyard polygon, 5 µm inside the drawn ±1.68 x ±0.95 mm; SHAPE_POLY_SET.BBox() pads it.
    assert rep["courtyards"][0]["box"] == [118.325, 121.675, 103.055, 104.945] and rep["keepouts"] == []
    code, rep = inspect_json("list", FIXTURE, "--box", "115", "122", "103", "105", "--layer", "In2.Cu")
    assert [(t["net"], t["layer"]) for t in rep["tracks"]] == [("VIN", "In2.Cu")] and rep["pads"] == []
    code, rep = inspect_json("list", FIXTURE, "--box", "116", "120", "108", "114")
    assert [(k["name"], k["no"]) for k in rep["keepouts"]] == [("strip", ["footprints"])]
    code, out, _ = inspect("list", FIXTURE, "--box", "112", "116", "108", "112", "--net", "GND")
    assert code == 0 and "C1.2     GND" in out and "keep-outs: 0" in out, out


@needs_pcbnew
def test_map_writes_one_picture_per_copper_layer(tmp_path):
    pytest.importorskip("PIL")
    out = tmp_path / "maps"
    code, rep = inspect_json("map", FIXTURE, "--box", "100", "130", "100", "116", "--out", out)
    assert code == 0, rep
    assert sorted(p.name for p in out.iterdir()) == ["B-Cu.png", "F-Cu.png", "In1-Cu.png", "In2-Cu.png"]
    from PIL import Image

    with Image.open(out / "F-Cu.png") as img:
        assert img.format == "PNG"
        assert img.width >= 30 * 60 and img.height >= 16 * 60  # the window at 60 px/mm, with its frame
    code, rep = inspect_json(
        "map", FIXTURE, "--box", "110", "118", "102", "106", "--layers", "In2.Cu", "--out", out
    )
    assert code == 0 and [Path(f).name for f in rep["files"]] == ["In2-Cu.png"]
    code, _, err = inspect("map", FIXTURE, "--box", "110", "100", "102", "106", "--out", out)
    assert code == 1 and "X0 < X1" in err


@needs_libs
@needs_kicad
@needs_pcbnew
def test_the_inspect_fixture_is_what_its_design_writes(tmp_path):
    """The committed board is the generator's output (AGENTS.md invariant 12): regenerate and compare."""
    proc = subprocess.run(
        [sys.executable, str(CLI), "design", str(FIXTURE / "design.py"), "--out", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "island: C1.2 cut off" in proc.stdout  # the island the fixture keeps on purpose
    for suffix in (".kicad_pro", ".kicad_sch", ".kicad_pcb", ".kicad_dru"):
        name = f"four_layer{suffix}"
        assert (tmp_path / name).read_bytes() == (FIXTURE / name).read_bytes(), name


# ------------------------------------------------------------------ stretch


DESIGN = """\
import uuid
import kicadgen

CY = 104.0  # the axis, (124.0, 105.0) in a comment never moves
X0, Y0, X1, Y1 = 100.0, 100.0, 130.0, 116.0
NOTE = "at (124.0, 105.0)"


def build():
    d = kicadgen.Design(name="t", namespace=uuid.UUID(int=1), outline=(X0, Y0, X1, Y1))
    d.add("R1", "Device:R", "10k", "R:R", sch_at=(121.92, 104.14), pcb_at=(120.0, 104.0))
    d.add("R2", "Device:R", "10k", "R:R", descr="Ω (127.5, 105)", sch_at=(127.0, 104.14), pcb_at=(126, CY))
    d.via("GND", 125.5, 104.25)
    d.track("VIN", [(103.0, 104.0), (126.0, 104.0)], "F.Cu")
    d.text("v1", 128.0, 101.0, "F.SilkS", 0.6, 0.13)
    d.keepout(d.circle(127.0, 110.0, 2.0), name="collar")
    size = (0.6, 0.13)
    corner = 129.0
    return d
"""

STRETCHED = """\
import uuid
import kicadgen

CY = 104.0  # the axis, (124.0, 105.0) in a comment never moves
X0, Y0, X1, Y1 = 100.0, 100.0, 131.5, 116.0
NOTE = "at (124.0, 105.0)"


def build():
    d = kicadgen.Design(name="t", namespace=uuid.UUID(int=1), outline=(X0, Y0, X1, Y1))
    d.add("R1", "Device:R", "10k", "R:R", sch_at=(121.92, 104.14), pcb_at=(120.0, 104.0))
    d.add("R2", "Device:R", "10k", "R:R", descr="Ω (127.5, 105)", sch_at=(127.0, 104.14), pcb_at=(127.5, CY))
    d.via("GND", 127.0, 104.25)
    d.track("VIN", [(103.0, 104.0), (127.5, 104.0)], "F.Cu")
    d.text("v1", 129.5, 101.0, "F.SilkS", 0.6, 0.13)
    d.keepout(d.circle(128.5, 110.0, 2.0), name="collar")
    size = (0.6, 0.13)
    corner = 129.0
    return d
"""


def stretch(*args: object) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(STRETCH), *map(str, args)], capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_stretch_moves_board_coordinates_in_code_and_nothing_else(tmp_path):
    """East of x = 125 by 1.5 mm: pairs, a pair whose y is a name, the via, the text, the circle and the
    outline's east edge (bound to a name); not the schematic, a comment, a string, x west of the cut,
    or a bare number, which is listed for a look by hand."""
    design = tmp_path / "design.py"
    design.write_text(DESIGN, encoding="utf-8")
    code, out, err = stretch(design, "--cut", "125", "--grow", "1.5")
    assert code == 0, err
    assert design.read_text(encoding="utf-8") == STRETCHED
    assert "moved 6, left 1" in out, out
    assert "line 18: 129.0" in out  # corner = 129.0
    assert not list(tmp_path.glob("*.stretch-new"))


def test_stretch_dry_run_and_out_leave_the_design_alone(tmp_path):
    design = tmp_path / "design.py"
    design.write_text(DESIGN, encoding="utf-8")
    code, out, _ = stretch(design, "--cut", "125", "--grow", "1.5", "--dry-run")
    assert code == 0 and "line 13: 125.5 -> 127.0" in out, out
    assert design.read_text(encoding="utf-8") == DESIGN
    code, _, _ = stretch(design, "--cut", "125", "--grow", "1.5", "--out", tmp_path / "wide.py")
    assert code == 0
    assert design.read_text(encoding="utf-8") == DESIGN
    assert (tmp_path / "wide.py").read_text(encoding="utf-8") == STRETCHED


def test_stretch_needs_the_boards_extent(tmp_path):
    design = tmp_path / "design.py"
    design.write_text("def build():\n    return make((126.0, 104.0))\n", encoding="utf-8")
    code, _, err = stretch(design, "--cut", "125", "--grow", "1")
    assert code == 1 and "--outline" in err
    code, out, _ = stretch(design, "--cut", "125", "--grow", "1", "--outline", "100", "100", "130", "116")
    assert code == 0 and "(127.0, 104.0)" in design.read_text(encoding="utf-8"), out
