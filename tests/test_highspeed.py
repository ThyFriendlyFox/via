"""`workcenter highspeed`: the interface rules of a board, from its interfaces.json and rules/interfaces/.

The 4 fixtures are tests/boards/highspeed_pair.py with no fault and with 1 planted in each of 3. Each
names 1 interface, `ti-am57xx-usb2` (TI SPRAAR7J, Table A-2, page 16): 81 to 99 ohm differential, 50 mil
(1.27 mm) of skew, 12000 mil (304.8 mm) of length, and section 2.4 (page 6) for the plane.
"""

from __future__ import annotations

import json
import re
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
USB2TI = [{"interface": "ti-am57xx-usb2", "nets": ["USB_D_P", "USB_D_N"], "gap": 0.2}]
_ANSWERS: dict[str, dict] = {}


def solver(req: dict) -> dict:
    """xsection.answer, kept for each request: many boards below share a stack and a gap."""
    key = json.dumps(req, sort_keys=True)
    if key not in _ANSWERS:
        _ANSWERS[key] = xsection.answer(req)
    return _ANSWERS[key]


def run(fixture: str, interfaces: list[dict] | None = None) -> highspeed.Report:
    project = BOARDS / fixture
    return highspeed.check(
        project / "pair.kicad_pcb", interfaces or highspeed.read_interfaces(project), solver
    )


def text_of(fixture: str) -> str:
    return (BOARDS / fixture / "pair.kicad_pcb").read_text()


def judge(tmp: Path, text: str, interfaces: list[dict] | None = None) -> highspeed.Report:
    """A fixture's board changed in a test: written to the test's own folder and judged there."""
    path = tmp / "board.kicad_pcb"
    path.write_text(text)
    return highspeed.check(path, interfaces or USB2TI, solver)


def drop_segments(text: str, net: str | None = None) -> str:
    """The board with every segment of `net` taken out (of every net when None)."""
    return re.sub(
        r"\t\(segment\n.*?\n\t\)\n",
        lambda m: "" if net is None or f'(net "{net}")' in m.group(0) else m.group(0),
        text,
        flags=re.S,
    )


VIA = (
    '\t(via\n\t\t(at {x} {y})\n\t\t(size 0.6)\n\t\t(drill 0.3)\n\t\t(layers "F.Cu" "B.Cu")\n'
    '\t\t(net "{net}")\n\t)\n'
)


def add_vias(text: str, vias: list[tuple[float, float, str]]) -> str:
    return text.replace(
        "\t(zone\n", "".join(VIA.format(x=x, y=y, net=n) for x, y, n in vias) + "\t(zone\n", 1
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
    """14 lines hold: width 2, gap 1, length 2, skew 1, vias 2, plane 2, coupling 2 (the fan-out at the
    pads is break-out), spacing 2. SPRAAR7J also sets 6 limits the command does not judge: the
    single-ended impedance, the stubs, the test points, the 50 mil to a clock, the 90 mil from the
    plane's edge and the 1.5 W from its voids: 6 lines, not judged."""
    report = reports["pass-highspeed"]
    assert report.fails() == []
    assert sorted(f.rule for f in report.not_judged()) == sorted(
        ["single_ended", "stubs", "test_points", "clock_spacing", "plane_edge", "voids"]
    )
    held = [f.rule for f in report.findings if f.status == "held"]
    assert sorted(held) == sorted(
        ["width"] * 2
        + ["gap"]
        + ["length"] * 2
        + ["skew"]
        + ["vias"] * 2
        + ["plane"] * 2
        + ["coupling"] * 2
        + ["spacing"] * 2
    )


@pytest.mark.parametrize(
    "fixture, rules",
    [
        ("fail-highspeed-width", {"width"}),
        # The skew board's bump runs 1 mm of the pair 1.2 mm apart, not the 0.2 mm interfaces.json gives.
        ("fail-highspeed-skew", {"skew", "gap"}),
        ("fail-highspeed-plane", {"plane"}),
    ],
)
def test_each_fault_fails_its_own_rules_alone(reports, fixture, rules):
    fails = reports[fixture].fails()
    assert fails, fixture
    assert {f.rule for f in fails} == rules


def test_width_line(reports):
    """Both tracks are 0.2 mm wide, their centres 108.255 - 107.745 = 0.51 mm apart: 0.51 - 0.2 = 0.31 mm
    edge to edge, the gap its interfaces.json gives. The solver's narrowest width for 99 ohm at a 0.31 mm
    gap is wider."""
    fails = reports["fail-highspeed-width"].fails()
    assert len(fails) == 2
    assert "0.2 mm wide" in fails[0].text and "SPRAAR7J" in fails[0].text and "page 16" in fails[0].text


def test_skew_line(reports):
    """32.1136 - 30.1136 = 2 mm of skew against 1.27 mm (50 mil)."""
    (fail,) = [f for f in reports["fail-highspeed-skew"].fails() if f.rule == "skew"]
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
    """USB 2.0 itself names no board skew and no plane; USB 3.x names no band for a board's impedance.
    Neither says where a pair may part, so the fan-out at the pads is not judged under either."""
    nets = ["USB_D_P", "USB_D_N"]
    usb2 = run("pass-highspeed", [{"interface": "usb2", "nets": nets, "gap": 0.2}])
    assert {f.rule for f in usb2.not_judged()} == {"skew", "plane", "coupling"}
    assert usb2.fails() == []
    usb3 = run("pass-highspeed", [{"interface": "usb3", "nets": nets, "gap": 0.2}])
    assert {f.rule for f in usb3.not_judged()} == {"width", "length", "skew", "plane", "coupling"}


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
    lines = sorted(ln.split(":")[0] for ln in proc.stdout.splitlines() if ln.startswith("FAIL"))
    assert lines == ["FAIL highspeed.gap", "FAIL highspeed.skew"]
    assert (tmp_path / "highspeed" / "highspeed.kicad_dru").is_file()


# ---- the review's findings R8-01 to R8-11: each a board that broke a rule and still held


def test_gap_is_measured_on_the_board(tmp_path):
    """R8-01. The width board's tracks are 0.51 - 0.2 = 0.31 mm apart. A gap of 0.1 mm in interfaces.json
    is not the board's: the gap fails, and the width is judged at 0.31 mm, where 0.2 mm fails."""
    report = judge(tmp_path, text_of("fail-highspeed-width"), [{**USB2TI[0], "gap": 0.1}])
    gaps = [f for f in report.fails() if f.rule == "gap"]
    assert len(gaps) == 1
    assert "0.31 mm apart" in gaps[0].text and "0.1 mm" in gaps[0].text
    assert [f.rule for f in report.fails()].count("width") == 2
    assert all("0.31 mm gap" in f.text for f in report.fails() if f.rule == "width")


def test_gap_without_a_key_is_the_boards(tmp_path):
    """R8-01. With no gap in interfaces.json the board's own gap is the one judged: 0.31 mm on the width
    board, never the Default class's 0.15 mm clearance."""
    report = judge(
        tmp_path, text_of("fail-highspeed-width"), [{k: v for k, v in USB2TI[0].items() if k != "gap"}]
    )
    assert all("0.31 mm gap" in f.text for f in report.fails() if f.rule == "width")
    assert not [f for f in report.findings if f.rule == "gap"]


@pytest.mark.parametrize("names", [("USB_D_P", "USB_D_N"), ("USB_DP", "USB_DM")])
def test_gap_fails_whatever_the_nets_are_named(tmp_path, names):
    """R8-02. USB_D_N moved 0.3 mm away: centres 108.555 - 107.745 = 0.81 mm apart, 0.81 - 0.31 = 0.5 mm
    edge to edge against 0.2 mm. KiCad's DRC reads no pair in USB_DP/USB_DM; the command judges it."""
    text = text_of("pass-highspeed").replace("108.255", "108.555")
    text = text.replace("/USB_D_P", f"/{names[0]}").replace("/USB_D_N", f"/{names[1]}")
    report = judge(tmp_path, text, [{**USB2TI[0], "nets": list(names)}])
    gaps = [f for f in report.fails() if f.rule == "gap"]
    assert len(gaps) == 1 and "0.5 mm apart" in gaps[0].text


def test_the_plane_above_is_judged_too(tmp_path):
    """R8-03. The pair on In1.Cu: the 2 split pours of the plane board on F.Cu, 0.2104 mm above, and a
    solid pour on In2.Cu, 1.0788 mm below. Both planes bound the stripline; both tracks cross the split."""
    text = text_of("fail-highspeed-plane")
    text = re.sub(
        r"\t\(segment\n.*?\n\t\)\n",
        lambda m: m.group(0).replace('"F.Cu"', '"In1.Cu"').replace("(width 0.31)", "(width 0.2)"),
        text,
        flags=re.S,
    )
    text = re.sub(
        r"\t\(zone\n.*?\n\t\)\n", lambda m: m.group(0).replace('"In1.Cu"', '"F.Cu"'), text, flags=re.S
    )
    corners = "(xy 100.3 100.3) (xy 139.7 100.3) (xy 139.7 115.7) (xy 100.3 115.7)"
    solid = (
        f'\t(zone\n\t\t(net "GND")\n\t\t(layer "In2.Cu")\n\t\t(polygon\n\t\t\t(pts {corners})\n\t\t)\n'
        f'\t\t(filled_polygon\n\t\t\t(layer "In2.Cu")\n\t\t\t(pts {corners})\n\t\t)\n\t)\n'
    )
    report = judge(tmp_path, text.replace("\t(zone\n", solid + "\t(zone\n", 1))
    planes = [f for f in report.fails() if f.rule == "plane"]
    assert len(planes) == 2 and all("plane on F.Cu" in f.text for f in planes)


def test_an_unrouted_pair_is_not_judged(tmp_path):
    """R8-04. No segment on the board: nothing holds; each rule is not judged, naming the net."""
    report = judge(tmp_path, drop_segments(text_of("pass-highspeed")))
    assert not [f for f in report.findings if f.status == "held"]
    assert report.fails() == []
    assert {"width", "length", "skew", "plane", "vias"} <= {f.rule for f in report.not_judged()}
    assert all("no track of USB_D_P on the board" in f.text for f in report.not_judged() if f.rule == "width")


def test_one_net_unrouted_does_not_crash(tmp_path):
    """R8-10 (b). USB_D_N has no track: a line that names it, no traceback."""
    report = judge(tmp_path, drop_segments(text_of("pass-highspeed"), "/USB_D_N"))
    assert report.fails() == []
    assert any("no track of USB_D_N on the board" in f.text for f in report.not_judged())


def test_a_pair_split_over_2_layers(tmp_path):
    """R8-10 (b). USB_D_N on B.Cu, USB_D_P on F.Cu: each net's width is not judged on its layer, with the
    other net's absence there as the reason."""
    text = text_of("pass-highspeed").replace(
        '(layer "F.Cu")\n\t\t(net "/USB_D_N")', '(layer "B.Cu")\n\t\t(net "/USB_D_N")'
    )
    report = judge(tmp_path, text)
    widths = [f.text for f in report.not_judged() if f.rule == "width"]
    assert len(widths) == 2
    assert any(t.startswith("USB_D_P on F.Cu") for t in widths)
    assert any(t.startswith("USB_D_N on B.Cu") for t in widths)


@pytest.mark.parametrize("content", ["{}", '{"interfaces": []}', "[]", '{"interfaces": [3]}'])
def test_interfaces_file_of_the_wrong_shape_is_refused(tmp_path, content):
    """R8-05 and R8-10 (a). A file that names no interface is refused with its name, not held."""
    (tmp_path / "interfaces.json").write_text(content)
    with pytest.raises(ValueError, match=r'interfaces.json: expected \{"interfaces": \[\.\.\.\]\}'):
        highspeed.read_interfaces(tmp_path)


def test_no_interface_is_refused():
    """R8-05. check() given no interface judges nothing: it refuses."""
    with pytest.raises(ValueError, match="names no interface"):
        highspeed.check(BOARDS / "pass-highspeed" / "pair.kicad_pcb", [], solver)


def test_power_pour_is_no_ground_plane(tmp_path):
    """R8-06. The pass board's In1.Cu pour on VBUS: SPRAAR7J section 2.4, page 6, asks for a GND plane."""
    text = text_of("pass-highspeed")
    i = text.index("\t(zone\n")
    report = judge(tmp_path, text[:i] + text[i:].replace('(net "GND")', '(net "VBUS")', 1))
    planes = [f for f in report.fails() if f.rule == "plane"]
    assert len(planes) == 2 and all("VBUS" in f.text and "In1.Cu" in f.text for f in planes)
    assert not [f for f in report.findings if f.rule == "width" and f.status == "held"]


def test_a_via_in_a_split_does_not_hide_it(tmp_path):
    """R8-07. 1 via of each net (0.6 mm) at x = 120.5, the middle of the 1 mm split: no fill closes round
    either via, so the split still fails under both tracks."""
    text = add_vias(
        text_of("fail-highspeed-plane"), [(120.5, 107.745, "/USB_D_P"), (120.5, 108.255, "/USB_D_N")]
    )
    planes = [f for f in judge(tmp_path, text).fails() if f.rule == "plane"]
    assert len(planes) == 2


def test_no_epsilon_r_is_not_judged(tmp_path):
    """R8-08. A stackup with no epsilon_r: the width is not judged, never solved in air."""
    report = judge(tmp_path, re.sub(r"\n\t*\(epsilon_r [0-9.]+\)", "", text_of("pass-highspeed")))
    assert not [f for f in report.findings if f.rule == "width" and f.status != "not judged"]
    assert any("epsilon_r" in f.text for f in report.not_judged() if f.rule == "width")


@pytest.mark.parametrize("gap", [0, -0.1, "0.2", True])
def test_a_gap_that_is_no_length_is_refused(gap):
    """R8-09 and R8-10 (c). Refused before the solver runs, naming interfaces.json and the entry."""
    with pytest.raises(ValueError, match=r"interfaces.json: ti-am57xx-usb2 USB_D_P/USB_D_N: gap must be"):
        highspeed.check(BOARDS / "pass-highspeed" / "pair.kicad_pcb", [{**USB2TI[0], "gap": gap}], solver)


def test_a_slab_of_no_thickness_is_refused(tmp_path):
    """R8-09. A dielectric 0 mm thick: refused, naming the stackup layer."""
    text = text_of("pass-highspeed").replace("(thickness 0.2104)", "(thickness 0)", 1)
    with pytest.raises(ValueError, match="dielectric 1"):
        judge(tmp_path, text)


@pytest.mark.parametrize(
    "field, value", [("gap", 0.0), ("widths", [0.3, 0.0]), ("t", 0.0), ("slabs", [[0.0, 4.5]])]
)
def test_solver_refuses_a_size_of_0(field, value):
    """R8-09. answer() returns an error at once for a size of 0, where its grid would have no end."""
    section = {"slabs": [[0.2104, 4.5]], "top_plane": False, "y": 0.2104, "t": 0.035, "widths": [0.3, 0.3]}
    section["gap"] = 0.2
    section[field] = value
    answer = xsection.answer({"section": section, "target": 90, "low": 81, "high": 99})
    assert "error" in answer and "above 0" in answer["error"]


def test_via_count(tmp_path):
    """R8-11. Table A-2, page 16: 4 vias on each USB2.0 trace. 5 vias on USB_D_P: 5 > 4 fails."""
    vias = [(110.0 + i, 107.745, "/USB_D_P") for i in range(5)]
    report = judge(tmp_path, add_vias(text_of("pass-highspeed"), vias))
    (fail,) = [f for f in report.fails() if f.rule == "vias"]
    assert "USB_D_P has 5 vias" in fail.text and "limit 4" in fail.text and "page 16" in fail.text


# ---- the second review's findings F1 to F7: boards drawn here on the pass board's stack and pads

P, N = "/USB_D_P", "/USB_D_N"
YP, YN = 107.745, 108.255  # the fixtures' centre lines


def tracks(points: list[tuple[float, float]], net: str, width: float = 0.31, layer: str = "F.Cu") -> str:
    return "".join(
        f"\t(segment\n\t\t(start {a[0]:.6f} {a[1]:.6f})\n\t\t(end {b[0]:.6f} {b[1]:.6f})\n"
        f'\t\t(width {width})\n\t\t(layer "{layer}")\n\t\t(net "{net}")\n\t)\n'
        for a, b in zip(points, points[1:], strict=False)
    )


def rect(x1: float, y1: float, x2: float, y2: float) -> list[tuple[float, float]]:
    return [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]


def ground(layer: str, fills: list[list[tuple[float, float]]], net: str = "GND") -> str:
    """A pour whose fill is the polygons given, 1 filled_polygon each, as KiCad writes a fill."""
    outline = " ".join(f"(xy {x} {y})" for x, y in rect(100.3, 100.3, 139.7, 115.7))
    points = [" ".join(f"(xy {x} {y})" for x, y in p) for p in fills]
    filled = "".join(
        f'\t\t(filled_polygon\n\t\t\t(layer "{layer}")\n\t\t\t(pts {p})\n\t\t)\n' for p in points
    )
    return (
        f'\t(zone\n\t\t(net "{net}")\n\t\t(layer "{layer}")\n'
        "\t\t(connect_pads\n\t\t\t(clearance 0.15)\n\t\t)\n"
        f"\t\t(min_thickness 0.25)\n\t\t(polygon\n\t\t\t(pts {outline})\n\t\t)\n{filled}\t)\n"
    )


def drawn(items: str, base: str = "pass-highspeed") -> str:
    """The base board with its segments taken out and `items` put in; its pour on In1.Cu stays."""
    return drop_segments(text_of(base)).replace("\t(zone\n", items + "\t(zone\n", 1)


STRAIGHT_P = [(105.0, 107.5), (105.5, YP), (134.5, YP), (135.0, 107.5)]
NO_GAP = [{k: v for k, v in USB2TI[0].items() if k != "gap"}]


def two_sublayers(text: str, er: float = 4.5) -> str:
    """dielectric 1 (0.2104 mm) as 2 sublayers of 0.1052 mm in the form pcbnew 10.0.8 saves: the first
    sublayer's last child is followed by the bare word `addsublayer`. The second sublayer's er is `er`."""
    old = (
        '(thickness 0.2104)\n\t\t\t\t(material "FR4")\n\t\t\t\t(epsilon_r 4.5)\n\t\t\t\t(loss_tangent 0.02)\n'
    )
    new = (
        '(thickness 0.1052)\n\t\t\t\t(material "FR4")\n\t\t\t\t(epsilon_r 4.5)\n\t\t\t\t(loss_tangent 0.02) '
        f'addsublayer\n\t\t\t\t(thickness 0.1052)\n\t\t\t\t(material "FR4")\n\t\t\t\t(epsilon_r {er})\n'
        "\t\t\t\t(loss_tangent 0.02)\n"
    )
    assert old in text
    return text.replace(old, new, 1)


def test_a_dielectric_of_2_sublayers_is_read_whole():
    """F1. Each sublayer is a slab of its own: 0.1052 mm of er 3.8 next to In1.Cu, then 0.1052 mm of er
    4.5 under F.Cu (the sublayers are listed top down). The strip stands 0.2104 mm over its plane."""
    board = highspeed.read_board(two_sublayers(text_of("pass-highspeed"), er=3.8))
    section, refs = highspeed.section_for(board, "F.Cu")
    assert refs == ["In1.Cu"]
    assert section["slabs"] == [[0.1052, 3.8], [0.1052, 4.5]] and section["y"] == 0.2104


def test_sublayers_of_one_er_are_one_slab(tmp_path):
    """F1. The width board with dielectric 1 in 2 sublayers of er 4.5: the same 0.2104 mm slab, so the
    same band at its 0.31 mm gap, 0.2971 to 0.4368 mm, and both 0.2 mm tracks fail."""
    report = judge(tmp_path, two_sublayers(text_of("fail-highspeed-width")), [{**USB2TI[0], "gap": 0.31}])
    widths = [f for f in report.findings if f.rule == "width"]
    assert [f.status for f in widths] == ["fail", "fail"]
    assert all("0.2971 to 0.4368" in f.text for f in widths)


@pytest.mark.parametrize("sublayers", [False, True])
def test_a_dielectric_with_no_thickness_is_refused(tmp_path, sublayers):
    """F1. A dielectric (or a sublayer of one) with no thickness: refused, naming it."""
    text = text_of("pass-highspeed")
    if sublayers:
        text = two_sublayers(text).replace("addsublayer\n\t\t\t\t(thickness 0.1052)\n", "addsublayer\n")
    else:
        text = text.replace("(thickness 0.2104)\n\t\t\t\t", "", 1)
    with pytest.raises(ValueError, match="dielectric 1"):
        judge(tmp_path, text)


def test_every_run_at_another_gap_than_the_declared_fails(tmp_path):
    """F2. USB_D_N runs 14.8 mm at the 0.2 mm gap, then 13 mm 0.6 mm further out: 0.8 mm apart, clear of
    the 0.15 mm clearance rule. interfaces.json gives 0.2 mm: the 13 mm fail."""
    yn = YP + 0.31 + 0.8
    n = [(105.0, 108.5), (105.5, YN), (120.3, YN), (120.9, yn), (133.9, yn), (134.5, YN), (135.0, 108.5)]
    report = judge(tmp_path, drawn(tracks(STRAIGHT_P, P) + tracks(n, N)))
    (gap,) = [f for f in report.fails() if f.rule == "gap"]
    assert "13 mm of the pair runs 0.8 mm apart" in gap.text and "limit 0.2 mm" in gap.text


def test_with_no_declared_gap_each_gap_is_solved(tmp_path):
    """F2. No gap in interfaces.json; USB_D_N comes 0.12 mm nearer for 13.96 mm: 0.08 mm apart, where the
    solver gives 73.58 ohm at the tracks' 0.31 mm (the review's run), under 81 ohm."""
    yn = YP + 0.31 + 0.08
    n = [(105.0, 108.5), (105.5, YN), (120.3, YN), (120.42, yn), (134.38, yn), (134.5, YN), (135.0, 108.5)]
    report = judge(tmp_path, drawn(tracks(STRAIGHT_P, P) + tracks(n, N)), NO_GAP)
    (gap,) = [f for f in report.fails() if f.rule == "gap"]
    assert "13.96 mm of the pair runs 0.08 mm apart" in gap.text
    assert "73.6 ohm" in gap.text and "81 to 99 ohm" in gap.text


def test_a_stretch_with_no_partner_is_counted(tmp_path):
    """F3. USB_D_N leaves USB_D_P in a V from x = 112 to 128, 3 mm out at x = 120. USB_D_P: 30.1136 mm,
    13 mm of it beside USB_D_N, 1.1136 mm at its pads (break-out, within 6.35 mm of them, SPRAAR7J 3.3),
    16 mm from x = 112 to 128 with no partner. USB_D_N: 31.2491 mm, 2 legs of sqrt(8^2 + 3^2) = 8.544 mm
    with no partner."""
    w = 0.26
    yn = YP + w + 0.2
    n = [
        (105.0, 108.5),
        (105.5, yn),
        (112.0, yn),
        (120.0, yn + 3.0),
        (128.0, yn),
        (134.5, yn),
        (135.0, 108.5),
    ]
    p = tracks(STRAIGHT_P, P, width=w)
    report = judge(tmp_path, drawn(p + tracks(n, N, width=w)))
    coupling = {f.text.split(":")[0]: f for f in report.findings if f.rule == "coupling"}
    assert {k: f.status for k, f in coupling.items()} == {
        "USB_D_P on F.Cu": "not judged",
        "USB_D_N on F.Cu": "not judged",
    }
    text = coupling["USB_D_P on F.Cu"].text
    assert (
        "17.11 mm of its 30.11 mm" in text and "16 mm" in text and "(112, 107.745) to (128, 107.745)" in text
    )
    assert "17.09 mm" in coupling["USB_D_N on F.Cu"].text


def test_break_out_at_the_pads_holds(reports):
    """F3. The pass board: each track's 2 ends at its pads, 2 x 0.5568 = 1.1136 mm, are its only
    stretches with no partner, within 6.35 mm (0.25 in) of its pads: SPRAAR7J section 3.3, page 10."""
    coupling = [f for f in reports["pass-highspeed"].findings if f.rule == "coupling"]
    assert [f.status for f in coupling] == ["held", "held"]
    assert all("1.114 mm" in f.text and "page 10" in f.text for f in coupling)


def test_ground_on_the_tracks_own_layer_is_not_judged(tmp_path):
    """F4. GND poured on F.Cu 0.15 mm from the pair's outer edges, from x = 106 to 134 (clear of the
    fan-out to the pads): the solver has no coplanar ground, so the width is not judged, with the pour,
    its layer and its distance named."""
    top = rect(106.0, 100.3, 134.0, YP - 0.155 - 0.15)
    bottom = rect(106.0, YN + 0.155 + 0.15, 134.0, 115.7)
    text = drawn(tracks(STRAIGHT_P, P) + tracks(NORMAL_N, N) + ground("F.Cu", [top, bottom]))
    report = judge(tmp_path, text)
    widths = [f for f in report.findings if f.rule == "width"]
    assert [f.status for f in widths] == ["not judged", "not judged"]
    assert all("GND" in f.text and "F.Cu" in f.text and "0.15 mm" in f.text for f in widths)
    # 1 mm out, past 3 x 0.2104 = 0.6312 mm, the pour is no longer near: the width is judged.
    top = rect(106.0, 100.3, 134.0, YP - 0.155 - 1.0)
    bottom = rect(106.0, YN + 0.155 + 1.0, 134.0, 115.7)
    text = drawn(tracks(STRAIGHT_P, P) + tracks(NORMAL_N, N) + ground("F.Cu", [top, bottom]))
    widths = [f for f in judge(tmp_path, text).findings if f.rule == "width"]
    assert [f.status for f in widths] == ["held", "held"]


NORMAL_N = [(105.0, 108.5), (105.5, YN), (134.5, YN), (135.0, 108.5)]


def test_a_half_routed_pair_is_not_judged(tmp_path):
    """F6. Both nets stop at x = 120; nothing reaches J2. Length, skew and plane are not judged, each
    naming the pad its net does not reach."""
    p = tracks([(105.0, 107.5), (105.5, YP), (120.0, YP)], P)
    n = tracks([(105.0, 108.5), (105.5, YN), (120.0, YN)], N)
    report = judge(tmp_path, drawn(p + n))
    rules = ("length", "skew", "plane")
    assert not [f for f in report.findings if f.rule in rules and f.status != "not judged"]
    lengths = [f.text for f in report.not_judged() if f.rule == "length"]
    assert len(lengths) == 2 and all("J2" in t for t in lengths)


def test_ti_files_name_every_limit_of_their_note():
    """F5. SPRAAR7J sets these besides Table A-2's impedance, length, skew, vias and stubs: the plane's
    edge and its voids (3.2, page 9), the GND reference kept through a via (2.4, page 8), test points and
    the spacing to other signals (Table A-2, page 16). Each is judged or names why not."""
    for name in ("ti-am57xx-usb2", "ti-am57xx-usb3"):
        limits = json.loads((SPECS / f"{name}.json").read_text())["limits"]
        for key in (
            "plane_edge",
            "voids",
            "stitching",
            "test_points",
            "spacing",
            "clock_spacing",
            "coupling",
        ):
            assert key in limits, (name, key)
            assert "page" in limits[key]["where"], (name, key)


def test_a_via_that_changes_the_plane_needs_a_ground_via(tmp_path):
    """F5. F.Cu over In1.Cu to a via, then B.Cu over In2.Cu: the reference changes. No GND via within
    200 mil (5.08 mm) fails; one 1 mm away holds. SPRAAR7J section 2.4, page 8."""
    p = tracks([(105.0, 107.5), (105.5, YP), (120.0, YP)], P)
    p += tracks([(120.0, YP), (134.5, YP), (135.0, 107.5)], P, layer="B.Cu")
    n = tracks([(105.0, 108.5), (105.5, YN), (121.0, YN)], N)
    n += tracks([(121.0, YN), (134.5, YN), (135.0, 108.5)], N, layer="B.Cu")
    corners = rect(100.3, 100.3, 139.7, 115.7)
    text = add_vias(drawn(p + n + ground("In2.Cu", [corners])), [(120.0, YP, P), (121.0, YN, N)])
    fails = [f for f in judge(tmp_path, text).fails() if f.rule == "stitching"]
    assert len(fails) == 2 and all("5.08 mm" in f.text and "page 8" in f.text for f in fails)
    stitched = add_vias(text, [(120.5, 110.0, "GND")])
    held = [f for f in judge(tmp_path, stitched).findings if f.rule == "stitching"]
    assert [f.status for f in held] == ["held", "held"]


def test_another_signal_near_the_pair_fails(tmp_path):
    """F5. A track of another net on F.Cu 0.5 mm from USB_D_P's edge: Table A-2 (page 16) sets 30 mil,
    0.762 mm."""
    y = YP - 0.155 - 0.5 - 0.1
    other = tracks([(110.0, y), (130.0, y)], "/OTHER", width=0.2)
    report = judge(tmp_path, drawn(tracks(STRAIGHT_P, P) + tracks(NORMAL_N, N) + other))
    (fail,) = [f for f in report.fails() if f.rule == "spacing"]
    assert "USB_D_P" in fail.text and "OTHER" in fail.text and "0.5 mm" in fail.text and "0.762" in fail.text


def test_a_gap_with_no_solution_keeps_the_width_band(tmp_path):
    """F7. USB_D_N 0.3 mm further out: 0.5 mm apart, where no gap gives 99 ohm at the nominal width. The
    width band is still judged, and the gap rule is written without the bound that has no solution."""
    text = text_of("pass-highspeed").replace("108.255", "108.555")
    report = judge(tmp_path, text, NO_GAP)
    widths = [f for f in report.findings if f.rule == "width"]
    assert len(widths) == 2 and all(f.status != "not judged" for f in widths), widths
    band = report.bands["F.Cu"]
    assert band["width_min"] < band["width_max"]
    assert "diff_pair_gap (min" in report.rules
