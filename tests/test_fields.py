"""`workcenter fields`: the parts that need no field solver.

The model a run hands its engine is written from the board file: the copper of the named nets, the
reference planes, the dielectrics of the stack-up, a lumped port at each end and the mesh. Every
expected value here is worked out by hand from the fixture boards under tests/boards/*-fields-*/; the
docstring shows the sum. The runs of the solver itself are in tests/test_fields_solver.py.
"""

import cmath
import json
import math
import subprocess
import sys
from itertools import pairwise
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import fields  # noqa: E402

# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {"hammerstad-jensen-1980": "pp. 407-409, equations (1) to (4), and the thickness correction"}

LINE = ROOT / "tests" / "boards" / "pass-fields-microstrip"
STUB = ROOT / "tests" / "boards" / "fail-fields-stub"
CLI = ROOT / "tools" / "workcenter"


def pour(net, *layers, square=(90, 90, 130, 140)):
    """A zone of `net` on `layers`, its outline the rectangle x0, y0 to x1, y1 on each."""
    x0, y0, x1, y1 = square
    return (net, layers, {ly: [[(x0, y0), (x1, y0), (x1, y1), (x0, y1)]] for ly in layers})


def line_model():
    board = fields.read_board(LINE / "line.kicad_pcb")
    spec = fields.read_spec(LINE / "fields.json")
    return fields.build_model(board, spec["groups"][0], spec)


def test_copper_heights_come_from_the_stackup():
    """The fixture's stack-up is F.Cu, 0.2 mm of dielectric, B.Cu. z is 0 at the bottom copper and
    copper is a sheet: B.Cu at 0, F.Cu at 0 + 0.2 = 0.2 mm."""
    board = fields.read_board(LINE / "line.kicad_pcb")
    assert board.copper_z == {"F.Cu": pytest.approx(0.2), "B.Cu": pytest.approx(0.0)}
    assert board.dielectrics == [(pytest.approx(0.0), pytest.approx(0.2), 4.5, 0.02)]


def test_a_track_is_a_rectangle_of_its_width():
    """The track runs from (100, 100) to (110, 100), 0.36 mm wide: its edges are 100 - 0.18 = 99.82 and
    100 + 0.18 = 100.18, at F.Cu's height 0.2 mm."""
    model = line_model()
    (metal,) = model["metals"]
    assert metal["net"] == "SIG"
    (poly,) = metal["polygons"]
    assert poly["z"] == pytest.approx(0.2)
    got = sorted((round(x, 6), round(y, 6)) for x, y in poly["points"])
    assert got == [(100, 99.82), (100, 100.18), (110, 99.82), (110, 100.18)]


def test_a_port_stands_at_each_end_from_the_plane_to_the_track():
    """The 2 ends of the track are (100, 100) and (110, 100). The plane under it is the GND zone on B.Cu
    at z 0, so each port runs from z 0 to z 0.2, at the end's x, with 50 ohm, across the track between
    its first and last mesh line inside the metal: the cell across is 0.36 / (3 + 2/3) = 0.0981818, and
    those lines are a third of it, 0.0327273, inside the edges: y 99.8527273 to 100.1472727."""
    ports = line_model()["ports"]
    assert [p["n"] for p in ports] == [1, 2]
    for port, x in zip(ports, (100, 110), strict=True):
        assert port["net"] == "SIG"
        assert port["r"] == 50
        assert port["start"] == pytest.approx([x, 99.8527273, 0.0])
        assert port["stop"] == pytest.approx([x, 100.1472727, 0.2])


def test_the_plane_and_the_dielectric_fill_the_box():
    """The copper spans x 100 to 110 and y 99.82 to 100.18; the box adds the 3 mm margin on each side:
    x 97 to 113, y 96.82 to 103.18. Above the top copper and below the bottom one it adds 3 mm of air:
    z -3 to 3.2. The GND plane is a sheet at z 0 over the box; the dielectric fills z 0 to 0.2."""
    model = line_model()
    assert model["box"] == pytest.approx([97, 96.82, -3.0, 113, 103.18, 3.2])
    assert model["planes"] == [{"layer": "B.Cu", "net": "GND", "z": 0.0}]
    (diel,) = model["dielectrics"]
    assert diel["z"] == pytest.approx([0.0, 0.2])
    assert (diel["er"], diel["tand"]) == (4.5, 0.02)


def test_the_largest_cell_is_a_twentieth_of_the_shortest_wavelength():
    """At 10 GHz in a dielectric of 4.5 the wavelength is 299792458 / (10e9 x sqrt(4.5)) m
    = 0.0299792458 / 2.1213203 = 14.13235 mm, and a twentieth of it is 0.706618 mm."""
    assert fields.max_cell_mm(10e9, 4.5, 20) == pytest.approx(0.706618, abs=1e-6)


def test_a_gap_wider_than_the_largest_cell_is_cut_in_equal_cells():
    """Lines 0, 1 and 3.1 with cells of 1 at most: the gap of 2.1 needs ceil(2.1 / 1) = 3 cells of 0.7:
    0, 1, 1.7, 2.4, 3.1. Neighbours 1 and 0.7 differ by 1.43 times, under 1.5."""
    assert fields.mesh_lines([0, 1, 3.1], 1.0) == pytest.approx([0, 1, 1.7, 2.4, 3.1])


def test_cells_grow_by_1_5_times_from_a_small_gap():
    """Lines 0, 0.2 and 1 with cells of 1 at most. The gap 0 to 0.2 is 1 cell. In the gap 0.2 to 1 the
    cells grow from the 0.2 beside it: 0.3, then 0.45 (0.75 in all; the next, 0.675, does not fit).
    0.05 is left, less than 0.45 / 1.5 = 0.3, so the 0.45 is taken back: 0.5 is left, cut in cells of
    0.3 x 1.5 = 0.45 at most: 2 of 0.25. Lines 0, 0.2, 0.5, 0.75, 1."""
    assert fields.mesh_lines([0, 0.2, 1.0], 1.0) == pytest.approx([0, 0.2, 0.5, 0.75, 1.0])


def test_a_long_gap_grows_then_stays_at_the_largest_cell():
    """Lines 0, 0.1 and 5 with cells of 1 at most: from the 0.1 the cells grow 0.15, 0.225, 0.3375,
    0.50625, 0.759375 (1.978125 in all; the next, 1.139, is over 1). 4.9 - 1.978125 = 2.921875 is
    left, cut in ceil(2.921875 / 1) = 3 cells of 0.973958: 0.973958 / 0.759375 = 1.28 times."""
    lines = fields.mesh_lines([0, 0.1, 5.0], 1.0)
    cells = [b - a for a, b in pairwise(lines)]
    assert cells[:6] == pytest.approx([0.1, 0.15, 0.225, 0.3375, 0.50625, 0.759375])
    assert cells[6:] == pytest.approx([2.921875 / 3] * 3)
    assert len(lines) == 10


def test_lines_closer_than_the_least_cell_are_one_line():
    """A slanted track's corners put lines 0.0002 apart (Wyvern's TX1 pair: 134.1248 and 134.125), and
    the time step falls with the least cell: 4.4e-16 s, 200000 steps for 87 ps. With a least cell of
    0.01, 0.1002 joins 0.1. Then 0.1 to 1 grows 0.15, 0.225, 0.3375 (0.7125); 0.1875 is left, under
    0.3375 / 1.5 = 0.225, so 0.3375 is taken back and 0.525 cut in ceil(0.525 / 0.3375) = 2 cells of
    0.2625. Lines 0, 0.1, 0.25, 0.475, 0.7375, 1."""
    lines = fields.mesh_lines([0, 0.1, 0.1002, 1.0], 1.0, min_cell=0.01)
    assert lines == pytest.approx([0, 0.1, 0.25, 0.475, 0.7375, 1.0])


def test_a_line_a_port_stands_on_is_never_dropped():
    """Wyvern's J1.A3 port stands at x 109.25; a slanted track's corner put a line at 109.245011, and
    the merge kept that one: the port's excitation, a sheet at 109.25, lay on no line, openEMS dropped it
    (`Unused primitive ... port_excite_1`) and ran with 0 energy. A kept line wins: with a least cell of
    0.025, 0.995 goes and 1 stays."""
    lines = fields.mesh_lines([0, 0.995, 2.0], 1.0, min_cell=0.025, keep=[1.0])
    assert 1.0 in lines and 0.995 not in lines


def test_every_port_lies_on_mesh_lines():
    """Each port's x, y and z bounds are lines of the mesh, to the digit, on the stub fixture."""
    board = fields.read_board(STUB / "stub.kicad_pcb")
    spec = fields.read_spec(STUB / "fields.json")
    model = fields.build_model(board, spec["groups"][0], spec)
    for port in model["ports"]:
        for k, axis in enumerate("xyz"):
            assert port["start"][k] in model["mesh"][axis] and port["stop"][k] in model["mesh"][axis]


def test_a_slanted_track_gets_no_cell_under_half_a_cell_across_its_width():
    """Wyvern's TX1 pair runs on F.Cu with slanted pieces 0.15 to 0.25 mm wide. The least cell is half
    the cell across the narrowest track: 0.15 / (3 + 2/3) / 2 = 0.0204545 mm."""
    t = fields.Track
    board = fields.Board(
        path=Path("s.kicad_pcb"),
        copper_z={"F.Cu": 0.2, "B.Cu": 0.0},
        dielectrics=[(0.0, 0.2, 4.5, 0.02)],
        tracks=[
            t("S", "F.Cu", (110.0, 134.0), (109.25, 134.05), 0.15),
            t("S", "F.Cu", (110.3172, 134.0), (110.0, 134.0), 0.25),
        ],
        zones=[pour("GND", "B.Cu")],
    )
    group = {"name": "s", "nets": ["S"], "band_ghz": [0.1, 10]}
    model = fields.build_model(board, group, {"reference": "GND", "settings": dict(fields.SETTINGS)})
    for axis in "xy":
        lines = model["mesh"][axis]
        assert min(b - a for a, b in pairwise(lines)) >= 0.0204545 - 1e-7, axis


def test_a_fixed_line_is_a_line_to_the_digit():
    """Cells summed one by one drift in the last digits: 0 is held as 0, not 1.5e-15, or a sheet at 0
    lies on no line of the mesh and the solver leaves it out."""
    lines = fields.mesh_lines([-3, 0, 0.05, 0.2, 3.2], 0.7)
    assert 0.0 in lines and 0.05 in lines and 0.2 in lines


def test_the_mesh_holds_every_edge_and_its_own_bounds():
    """The mesh is written from the geometry: x holds the box (97, 113) and the ports (100, 110); z holds
    the air (-3, 3.2), the plane (0) and the track (0.2). y holds the box (96.82, 103.18) and, across
    the track, the thirds rule: the cell d is 0.36 / (3 + 2/3) = 0.0981818; 4 lines inside the metal
    from 99.82 + d/3 = 99.8527273 in steps of d, and 1 line 2d/3 = 0.0654545 outside each edge,
    99.7545455 and 100.2454545. The edges 99.82 and 100.18 are no lines: a sheet's edge on a line
    made the line fixture read 43.14 ohm against Hammerstad and Jensen's 51.34. No cell is larger than
    0.706618 mm (10 GHz in 4.5) and no 2 neighbours differ by more than 2 times (`mesh_lines`: 1.5
    within a run, 2 where 2 runs meet)."""
    mesh = line_model()["mesh"]
    for axis, must in (
        ("x", [97, 100, 110, 113]),
        ("y", [96.82, 99.7545455, 99.8527273, 99.9509091, 100.0490909, 100.1472727, 100.2454545, 103.18]),
        ("z", [-3, 0, 0.2, 3.2]),
    ):
        lines = mesh[axis]
        for value in must:
            assert min(abs(v - value) for v in lines) < 1e-7, (axis, value)
        if axis == "y":
            assert min(abs(v - e) for v in lines for e in (99.82, 100.18)) > 0.03
        cells = [b - a for a, b in pairwise(lines)]
        assert max(cells) <= 0.706618 + 1e-6
        assert all(max(a, b) / min(a, b) <= 2 + 1e-9 for a, b in pairwise(cells))


def test_a_port_named_by_a_pad_is_the_end_nearest_that_pad():
    """J1 stands at (100, 100) with its pad 1 at (0, 0): (100, 100). J2 stands at (110, 101) turned 90
    degrees with its pad 1 at (1, 0): x = 1 cos 90 + 0 sin 90 = 0 and y = -1 sin 90 + 0 cos 90 = -1, so
    (110, 100). The stub's open end (105, 107) is no port."""
    board = fields.read_board(STUB / "stub.kicad_pcb")
    assert board.pads["J1.1"][:2] == pytest.approx((100, 100))
    assert board.pads["J2.1"][:2] == pytest.approx((110, 100))
    spec = fields.read_spec(STUB / "fields.json")
    ports = fields.build_model(board, spec["groups"][0], spec)["ports"]
    assert [p["start"][0] for p in ports] == pytest.approx([100, 110])


def test_a_joint_the_rectangles_cover_gets_no_octagon():
    """The stub meets the line at (105, 100) in a T: the octagon there, its flats 0.18 mm from the
    centre, lies inside the line's rectangle (y 99.82 to 100.18) and the stub's (x 104.82 to 105.18, y
    from 100). openEMS would warn of a primitive that fills no cell, so the copper is 3 rectangles."""
    board = fields.read_board(STUB / "stub.kicad_pcb")
    spec = fields.read_spec(STUB / "fields.json")
    polys = fields.build_model(board, spec["groups"][0], spec)["metals"][0]["polygons"]
    assert sorted(len(p["points"]) for p in polys) == [4, 4, 4]


WYVERN = ROOT / "examples" / "snapdragon-dev-board" / "v0.2"


@pytest.mark.skipif(not (WYVERN / "wyvern.kicad_pcb").is_file(), reason="the Wyvern example is not here")
def test_every_polygon_holds_a_mesh_node_no_later_one_holds():
    """openEMS drops a primitive that wins no point of the mesh (`Unused primitive`), a fault to the
    command. With a track's edges a third of a cell inside, the run of Wyvern's USB 3 TX1 pair dropped
    a polygon of /SS_TX1_N: a piece 0.0586 mm long, x 113.8414 to 113.9, under the octagons at its 2
    ends but for its corners. Taking out that piece, or either octagon, stopped the warning: the later
    of 2 of 1 priority wins, and a point on the piece's own edge is not its own. Every polygon of the
    model holds, strictly inside, a node or edge centre no later polygon of its net holds."""
    board = fields.read_board(WYVERN / "wyvern.kicad_pcb")
    group = {
        "name": "usb3-tx1",
        "nets": ["/SS_TX1_P", "/SS_TX1_N"],
        "ports": ["J1.A3", "U2.17", "J1.A2", "U2.16"],
        "band_ghz": [0.1, 10],
    }
    spec = {"reference": "GND", "settings": dict(fields.SETTINGS), "file": "fields.json"}
    model = fields.build_model(board, group, spec)
    mx, my = model["mesh"]["x"], model["mesh"]["y"]
    points = [(x, y) for x in mx for y in my]
    points += [((a + b) / 2, y) for a, b in pairwise(mx) for y in my]
    points += [(x, (a + b) / 2) for x in mx for a, b in pairwise(my)]
    for metal in model["metals"]:
        polys = metal["polygons"]
        for k, poly in enumerate(polys):
            xs, ys = [p[0] for p in poly["points"]], [p[1] for p in poly["points"]]
            nodes = [
                q
                for q in points
                if min(xs) <= q[0] <= max(xs)
                and min(ys) <= q[1] <= max(ys)
                and fields._in_polygon(q, poly["points"], tol=-1e-7)
            ]
            own = [
                q
                for q in nodes
                if not any(e["z"] == poly["z"] and fields._in_polygon(q, e["points"]) for e in polys[k + 1 :])
            ]
            assert own, (metal["net"], poly["points"])


def test_a_corner_of_a_track_is_closed():
    """An L: (100, 100) to (105, 100), then up to (105, 105), 0.36 mm wide. The outer corner (105.18,
    99.82) is on neither rectangle: the first ends at x 105, the second starts at y 100. The joint gets
    an octagon of 8 points."""
    t = fields.Track
    board = fields.Board(
        path=Path("l.kicad_pcb"),
        copper_z={"F.Cu": 0.2, "B.Cu": 0.0},
        dielectrics=[(0.0, 0.2, 4.5, 0.02)],
        tracks=[t("S", "F.Cu", (100, 100), (105, 100), 0.36), t("S", "F.Cu", (105, 100), (105, 105), 0.36)],
        zones=[pour("GND", "B.Cu")],
    )
    group = {"name": "l", "nets": ["S"], "band_ghz": [0.1, 10]}
    spec = {"reference": "GND", "settings": dict(fields.SETTINGS)}
    polys = fields.build_model(board, group, spec)["metals"][0]["polygons"]
    assert sorted(len(p["points"]) for p in polys) == [4, 4, 8]


def test_a_pour_beside_the_tracks_is_no_plane():
    """GND is poured on F.Cu, around the track, and on B.Cu under it. As a sheet over the box the F.Cu
    pour would short the track, so the plane is B.Cu alone, and the report says the F.Cu pour is left
    out."""
    t = fields.Track
    board = fields.Board(
        path=Path("p.kicad_pcb"),
        copper_z={"F.Cu": 0.2, "B.Cu": 0.0},
        dielectrics=[(0.0, 0.2, 4.5, 0.02)],
        tracks=[t("S", "F.Cu", (100, 100), (110, 100), 0.36)],
        zones=[pour("GND", "F.Cu", "B.Cu")],
    )
    group = {"name": "p", "nets": ["S"], "band_ghz": [0.1, 10]}
    model = fields.build_model(board, group, {"reference": "GND", "settings": dict(fields.SETTINGS)})
    assert [p["layer"] for p in model["planes"]] == ["B.Cu"]
    assert "the GND pour on F.Cu, the layer of the group's own tracks" in model["left_out"]


def write_spec(tmp_path, text):
    path = tmp_path / "fields.json"
    path.write_text(text, encoding="utf-8")
    return path


def test_a_limit_without_its_source_is_refused(tmp_path):
    """No limit is taken without the document it comes from: the refusal names the file, the group and
    the measure."""
    path = write_spec(
        tmp_path,
        '{"groups": [{"name": "a", "nets": ["X"], "band_ghz": [0.1, 1],'
        ' "limits": [{"measure": "insertion_loss_db", "net": "X", "max": 3}]}]}',
    )
    with pytest.raises(fields.Refusal, match=r"fields.json: group a: insertion_loss_db of X has no source"):
        fields.read_spec(path)


def test_a_measure_the_command_does_not_know_is_refused(tmp_path):
    path = write_spec(
        tmp_path,
        '{"groups": [{"name": "a", "nets": ["X"], "band_ghz": [0.1, 1],'
        ' "limits": [{"measure": "loss", "net": "X", "max": 3, "source": "d"}]}]}',
    )
    with pytest.raises(fields.Refusal, match=r"group a: measure `loss` is none of"):
        fields.read_spec(path)


def test_an_engine_the_command_does_not_know_is_refused(tmp_path):
    path = write_spec(tmp_path, '{"engine": "hfss", "groups": []}')
    with pytest.raises(fields.Refusal, match=r"engine `hfss` is none of openems"):
        fields.read_spec(path)


def test_the_measures_of_a_line_from_its_s_parameters():
    """S11 = 0.1 and S21 = -0.9j at every frequency. Return loss -20 log10 0.1 = 20 dB; insertion loss
    -20 log10 0.9 = 0.91515 dB; the line's impedance from a symmetric 2-port is
    50 sqrt(((1 + S11)^2 - S21^2) / ((1 - S11)^2 - S21^2)) = 50 sqrt((1.21 + 0.81) / (0.81 + 0.81))
    = 50 sqrt(1.246914) = 55.8326 ohm."""
    freqs = [1e9, 2e9, 3e9]
    m = fields.line_measures(freqs, [0.1 + 0j] * 3, [-0.9j] * 3)
    assert m["return_loss_db"]["value"] == pytest.approx(20.0)
    assert m["insertion_loss_db"]["value"] == pytest.approx(0.91515, abs=1e-5)
    assert m["impedance_ohm"]["value"] == pytest.approx(55.8326, abs=1e-4)


def test_the_worst_frequency_is_the_one_judged():
    """Return loss is the least over the band and insertion loss the most: |S11| 0.1, 0.5, 0.2 gives
    -20 log10 0.5 = 6.0206 dB at 2 GHz; |S21| 0.9, 0.8, 0.5 gives -20 log10 0.5 = 6.0206 dB at 3 GHz."""
    freqs = [1e9, 2e9, 3e9]
    m = fields.line_measures(freqs, [0.1, 0.5, 0.2], [0.9, 0.8, 0.5])
    assert m["return_loss_db"]["value"] == pytest.approx(6.0206, abs=1e-4)
    assert m["return_loss_db"]["at_hz"] == 2e9
    assert m["insertion_loss_db"]["value"] == pytest.approx(6.0206, abs=1e-4)
    assert m["insertion_loss_db"]["at_hz"] == 3e9


def test_a_failure_is_one_line_with_value_limit_and_source():
    """55.8326 ohm against a 45 to 55 ohm window fails above its max; the line names the net, the
    measure, the value, the limit and the source. The impedance is a median over the band, and the
    line says so and over how many frequencies."""
    limits = [{"measure": "impedance_ohm", "net": "X", "min": 45, "max": 55, "source": "Doc rev 1, 3.2, p 7"}]
    measures = {"X": {"impedance_ohm": {"value": 55.8326, "at_hz": None, "median_of": 3}}}
    fails, held, unjudged = fields.judge(limits, measures)
    assert fails == [
        "X impedance_ohm 55.83 (the median over 3 frequencies) above max 55 (Doc rev 1, 3.2, p 7)"
    ]
    assert held == [] and unjudged == []


def test_a_limit_with_no_measure_is_not_judged():
    """A limit on a net the run has no measure for is said, with the reason; it never passes."""
    limits = [{"measure": "next_db", "net": "Y", "from": "X", "max": -30, "source": "d"}]
    fails, held, unjudged = fields.judge(limits, {"X": {}})
    assert fails == [] and held == []
    assert unjudged == ["Y next_db from X: not judged, the run gave no such measure"]


def test_the_dft_of_a_cosine_finds_its_amplitude():
    """v(t) = cos(2 pi 1e9 t) over 100 whole periods sampled every 1e-11 s. Its transform at 1 GHz is
    sum(v e^(-j 2 pi f t)) dt = (N dt) / 2 = (10000 x 1e-11) / 2 = 5e-8, and at 2 GHz it is 0."""
    dt = 1e-11
    t = [k * dt for k in range(10000)]
    v = [math.cos(2 * math.pi * 1e9 * x) for x in t]
    one, two = fields.dft(t, v, [1e9, 2e9])
    assert abs(one) == pytest.approx(5e-8, rel=1e-6)
    assert abs(two) < 1e-15


def test_s_parameters_from_port_voltages_and_currents():
    """A matched port: u = 50 i, so the wave into it is 0.5 (u + 50 i) = u and the wave out is 0: S11 = 0.
    A far port with u2 = -50 i2 carries only a wave out, u2: S21 = u2 / u1."""
    u1, i1 = 2 + 0j, (2 + 0j) / 50
    u2, i2 = 1j, -1j / 50
    s = fields.s_column([(u1, i1), (u2, i2)], 50, driven=0)
    assert abs(s[0]) < 1e-12
    assert s[1] == pytest.approx(0.5j)


def test_the_openems_file_holds_the_model():
    """The file openEMS reads: the track as a polygon at elevation 0.2, the dielectric as a box with
    epsilon 4.5, port 1 as a 50 ohm lumped element along z (direction 2). Its start z 0 is under its stop
    z 0.2, so the excitation points down, 0,0,-1, the voltage probe weighs -1 and the current probe 1
    with its normal along z."""
    text = fields.OpenEMS.xml(line_model(), driven=1)
    assert '<Polygon Priority="10" Elevation="0.2" NormDir="2">' in text
    assert '<Property Epsilon="4.5"' in text
    assert '<LumpedElement Name="port_resist_1" Direction="2" Caps="1" R="50">' in text
    assert '<Excitation Name="port_excite_1" Type="0" Excite="0,0,-1">' in text
    assert '<ProbeBox Name="port_ut1" Type="0" Weight="-1">' in text
    assert '<ProbeBox Name="port_it1" Type="1" Weight="1" NormDir="2">' in text
    assert "port_excite_2" not in text


def test_the_faults_openems_states_with_exit_0():
    """3 lines of openEMS's log, each met on a run, end with exit 0 and a result of another structure:
    each is a fault; a log without them is none."""
    fault = fields.OpenEMS.fault
    assert fault("Warning: Unused primitive (type: Box) detected in property: port_excite_1!") == (
        "Unused primitive (type: Box) detected in property: port_excite_1!"
    )
    cut = "Operator::CalcGaussianPulsExcitation: ... Cutting to max number of timesteps!"
    assert "a cell is too small" in fault(cut)
    late = "RunFDTD: Warning: Max. number of timesteps was reached before the end-criteria of -40dB"
    assert "did not fall to the end criterion" in fault(late)
    assert fault("Time for 3604 iterations with 55692.00 cells : 8.22 sec") is None


def run_cli(*args, env=None):
    return subprocess.run(
        [sys.executable, str(CLI), *args], capture_output=True, text=True, env=env, timeout=600
    )


def test_an_absent_engine_skips_and_says_which(tmp_path):
    """With no openEMS the run is SKIP, exit code 2, and the line names the engine: never a pass."""
    import os

    env = {**os.environ, "OPENEMS": str(tmp_path / "no-openEMS")}
    proc = run_cli("fields", str(LINE), "--out", str(tmp_path / "out"), env=env)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "SKIP   fields" in proc.stdout
    assert "engine missing: openEMS" in proc.stdout


def test_model_only_writes_the_model_and_the_engine_file(tmp_path):
    """`--model` writes each group's model.json and the engine's input, runs nothing and judges nothing."""
    proc = run_cli("fields", str(LINE), "--out", str(tmp_path), "--model")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    folder = tmp_path / "fields" / "sig"
    model = json.loads((folder / "model.json").read_text(encoding="utf-8"))
    assert [p["n"] for p in model["ports"]] == [1, 2]
    assert (folder / "openems" / "port1" / "model.xml").is_file()
    assert "judged nothing" in proc.stdout


def test_a_wrong_checksum_of_openems_warns_unless_it_is_required():
    """ENGINES.md: a failed openEMS step warns, and REQUIRE_OPENEMS=1 makes it fatal. A checksum
    mismatch went straight to `die` and ended the default install. It goes through `openems_fail`,
    and the step returns before the file is unpacked."""
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    step = text[text.index("step_openems() {") :]
    step = step[: step.index("\n}\n")]
    check = step.index("sha256sum -c -")
    assert "die" not in step[check : step.index("\n", check)]
    failed = step.index('openems_fail "checksum mismatch', check)
    assert check < failed < step.index("return", failed) < step.index("dpkg-deb -x")


def test_doctor_names_openems():
    proc = run_cli("--json", "doctor")
    checks = json.loads(proc.stdout)["checks"]
    assert "openems" in checks
    assert checks["openems"]["required"] is False


def test_cmath_is_the_only_math_a_measure_needs():
    """The command runs on a bare python3: the module imports nothing outside the standard library."""
    text = (ROOT / "tools" / "fields.py").read_text(encoding="utf-8")
    imports = {ln.split()[1].split(".")[0] for ln in text.splitlines() if ln.startswith(("import ", "from "))}
    assert imports <= {
        "__future__",
        "bisect",
        "cmath",
        "json",
        "math",
        "os",
        "re",
        "shutil",
        "subprocess",
        "sys",
        "dataclasses",
        "itertools",
        "pathlib",
        "kicadgen",
        "time",
    }
    assert cmath.pi == math.pi


# ---------------------------------------------------------------- what the model must refuse


def line_board(zones):
    """The microstrip: S from (100, 100) to (110, 100) on F.Cu, 0.36 mm wide, 0.2 mm over B.Cu."""
    return fields.Board(
        path=Path("m.kicad_pcb"),
        copper_z={"F.Cu": 0.2, "B.Cu": 0.0},
        dielectrics=[(0.0, 0.2, 4.5, 0.02)],
        tracks=[fields.Track("S", "F.Cu", (100, 100), (110, 100), 0.36)],
        zones=zones,
    )


def model_of(board, **group):
    spec = {"reference": "GND", "settings": dict(fields.SETTINGS), "file": "fields.json"}
    return fields.build_model(board, {"name": "g", "nets": ["S"], "band_ghz": [0.1, 10], **group}, spec)


def test_a_pour_that_is_not_under_the_track_is_refused():
    """The GND pour on B.Cu is a 1 mm square, x 95 to 96 and y 95 to 96, 4 mm from the track. A plane
    whole over the box would stand under the track where the board has none: refused, naming the track
    and its first point with no pour under it, its start (100, 100)."""
    board = line_board([pour("GND", "B.Cu", square=(95, 95, 96, 96))])
    with pytest.raises(fields.Refusal) as caught:
        model_of(board)
    assert str(caught.value) == (
        "group g: the track of S from (100, 100) to (110, 100) on F.Cu has no GND pour on B.Cu under "
        "(100, 100): the model would put a plane where the board has none"
    )


def test_a_pour_under_the_whole_track_is_a_plane():
    """The pour runs x 99 to 111 and y 99 to 101: the track, x 100 to 110 and y 99.82 to 100.18, lies on
    it everywhere, and B.Cu is the plane."""
    board = line_board([pour("GND", "B.Cu", square=(99, 99, 111, 101))])
    assert [p["layer"] for p in model_of(board)["planes"]] == ["B.Cu"]


def test_a_pour_flush_with_both_ends_is_under_the_track():
    """The pour runs x 100 to 110, y 95 to 105: flush with the track's 2 ends. The even-odd test counted
    a point on the left edge as inside and one on the right edge as outside, so the track was taken
    with the pour flush at its start and refused with it flush at its end. A point on any edge of a
    pour is on copper; 1 nm outside it is not."""
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    for q in ((0, 5), (10, 5), (5, 0), (5, 10), (10, 10), (0, 0)):
        assert fields._in_polygon(q, square), q
    assert not fields._in_polygon((10 + 1e-6, 5), square)
    board = line_board([pour("GND", "B.Cu", square=(100, 95, 110, 105))])
    assert [p["layer"] for p in model_of(board)["planes"]] == ["B.Cu"]


def test_a_zone_is_read_as_its_fill_where_it_is_filled(tmp_path):
    """The line fixture's GND zone has the outline x 95 to 115, y 95 to 105 and no fill: the outline is
    its shape. Given a fill on B.Cu of the square 95 to 96, that fill is its shape, and the track over
    it is refused."""
    text = (LINE / "line.kicad_pcb").read_text(encoding="utf-8")
    board = fields.read_board(LINE / "line.kicad_pcb")
    ((net, layers, shapes),) = board.zones
    assert (net, layers) == ("GND", ("B.Cu",))
    assert shapes == {"B.Cu": [[(95, 95), (115, 95), (115, 105), (95, 105)]]}
    end = "(xy 95 95) (xy 115 95) (xy 115 105) (xy 95 105)\n\t\t\t)\n\t\t)\n"
    assert end in text
    filled = '\t\t(filled_polygon (layer "B.Cu") (pts (xy 95 95) (xy 96 95) (xy 96 96) (xy 95 96)))\n'
    (tmp_path / "f.kicad_pcb").write_text(text.replace(end, end + filled), encoding="utf-8")
    board = fields.read_board(tmp_path / "f.kicad_pcb")
    assert board.zones[0][2] == {"B.Cu": [[(95, 95), (96, 95), (96, 96), (95, 96)]]}
    spec = fields.read_spec(LINE / "fields.json")
    with pytest.raises(fields.Refusal, match=r"has no GND pour on B\.Cu under \(100, 100\)"):
        fields.build_model(board, spec["groups"][0], spec)


def test_a_cutout_of_a_zone_is_a_hole(tmp_path):
    """KiCad writes a zone's cutout as its second `polygon`: the first is the outline, each later one a
    hole of it (KiCad 10.0.8's pcbnew loads such a zone as 1 outline with 1 hole, and saves a zone of 1
    outline and 1 hole the same way). The line fixture's GND zone, x 95 to 115 and y 95 to 105, gets the
    cutout x 104.5 to 105.5, y 97 to 103, under the track: (105, 100) has no copper, and the track is
    refused at its first point over the cutout. The track is sampled every 10 / ceil(10 / 0.18) =
    0.178571 mm: the first sample past 104.5 is 100 + 26 x 0.178571 = 104.643. Read as 2 outlines, the
    slot was solid copper."""
    text = (LINE / "line.kicad_pcb").read_text(encoding="utf-8")
    end = "(xy 95 95) (xy 115 95) (xy 115 105) (xy 95 105)\n\t\t\t)\n\t\t)\n"
    cut = "\t\t(polygon (pts (xy 104.5 97) (xy 105.5 97) (xy 105.5 103) (xy 104.5 103)))\n"
    (tmp_path / "c.kicad_pcb").write_text(text.replace(end, end + cut), encoding="utf-8")
    board = fields.read_board(tmp_path / "c.kicad_pcb")
    (poly,) = board.zones[0][2]["B.Cu"]
    assert not fields._in_polygon((105, 100), poly)
    assert fields._in_polygon((102, 100), poly)
    spec = fields.read_spec(LINE / "fields.json")
    with pytest.raises(fields.Refusal, match=r"has no GND pour on B\.Cu under \(104\.643, 100\)"):
        fields.build_model(board, spec["groups"][0], spec)


@pytest.mark.parametrize(
    ("old", "new", "says"),
    [
        ('\t\t(layer "F.Cu")\n\t\t(net "SIG")', '\t\t(net "SIG")', "segment 1: no `layer`"),
        (
            "(epsilon_r 4.5)",
            "(epsilon_r FR4)",
            "stack-up layer dielectric 1: `epsilon_r` is 'FR4', not a number",
        ),
        ("(width 0.36)", "(width wide)", "segment 1: `width` is 'wide', not a number"),
    ],
)
def test_a_mistake_in_the_board_file_is_refused_with_its_place(tmp_path, old, new, says):
    """A segment with no layer ended in a TypeError, a word for a number in a ValueError: each a
    traceback, exit 1. Each is a refusal naming the file and the item."""
    text = (LINE / "line.kicad_pcb").read_text(encoding="utf-8")
    assert text.count(old) == 1
    (tmp_path / "x.kicad_pcb").write_text(text.replace(old, new), encoding="utf-8")
    with pytest.raises(fields.Refusal) as caught:
        fields.read_board(tmp_path / "x.kicad_pcb")
    assert str(caught.value) == f"x.kicad_pcb: {says}"


def test_a_hole_in_a_fill_is_a_hole():
    """A fill of the square 0 to 10 with a hole 4 to 6 joined to its outline by a slit along y 5, as
    KiCad writes a fill: (5, 5) is in the hole, (8, 5) and (2, 2) are on copper. A ray from (5, 5) to +x
    crosses x 6 and x 10, 2 edges: outside; from (8, 5) only x 10: inside."""
    fill = [
        (0, 0),
        (10, 0),
        (10, 10),
        (0, 10),
        (0, 5),
        (4, 5),
        (4, 6),
        (6, 6),
        (6, 4),
        (4, 4),
        (4, 5),
        (0, 5),
    ]
    assert not fields._in_polygon((5, 5), fill)
    assert fields._in_polygon((8, 5), fill)
    assert fields._in_polygon((2, 2), fill)


def test_a_pour_of_another_net_between_a_track_and_its_plane_is_refused():
    """4 layers: B.Cu at 0, In2.Cu at 0.1, In1.Cu at 1.1, F.Cu at 1.2 mm. S runs on B.Cu; 3V3 is poured
    on In2.Cu, 0.1 mm over it, and GND on In1.Cu, 1.1 mm over it. The 3V3 pour carries the return
    current; the model left it out and put the reference 11 times farther away (Hammerstad and Jensen:
    134.68 ohm for 0.18 mm over 1.1 mm against 51.34 ohm over 0.1 mm). Refused, naming the pour and the
    plane."""
    t = fields.Track
    board = fields.Board(
        path=Path("p.kicad_pcb"),
        copper_z={"F.Cu": 1.2, "In1.Cu": 1.1, "In2.Cu": 0.1, "B.Cu": 0.0},
        dielectrics=[(0.0, 0.1, 4.5, 0.02), (0.1, 1.1, 4.5, 0.02), (1.1, 1.2, 4.5, 0.02)],
        tracks=[t("S", "B.Cu", (100, 100), (110, 100), 0.18)],
        zones=[pour("GND", "In1.Cu"), pour("3V3", "In2.Cu")],
    )
    with pytest.raises(fields.Refusal) as caught:
        model_of(board)
    assert str(caught.value) == (
        "group g: the track of S from (100, 100) to (110, 100) on B.Cu has a 3V3 pour on In2.Cu at "
        "(100, 100), between it and the GND plane on In1.Cu: the model leaves every other net out, so "
        "its return path would be the plane's"
    )


def test_a_via_that_crosses_a_plane_is_refused():
    """4 layers: F.Cu at 1.4, In1.Cu at 1.2, In2.Cu at 0.2, B.Cu at 0 mm. S runs on F.Cu to a via at
    (105, 100) and on B.Cu from it; GND is poured on In1.Cu and In2.Cu. The via spans z 0 to 1.4 and
    passes both planes; the model cuts no antipad, so it would short S to GND (the run gave 600 dB and
    0.6 ohm). Refused at the first plane by height, In2.Cu at 0.2."""
    t = fields.Track
    board = fields.Board(
        path=Path("v.kicad_pcb"),
        copper_z={"F.Cu": 1.4, "In1.Cu": 1.2, "In2.Cu": 0.2, "B.Cu": 0.0},
        dielectrics=[(0.0, 0.2, 4.5, 0.02), (0.2, 1.2, 4.5, 0.02), (1.2, 1.4, 4.5, 0.02)],
        tracks=[t("S", "F.Cu", (100, 100), (105, 100), 0.36), t("S", "B.Cu", (105, 100), (110, 100), 0.36)],
        vias=[fields.Via("S", (105, 100), 0.3, ("F.Cu", "B.Cu"))],
        zones=[pour("GND", "In1.Cu", "In2.Cu")],
    )
    with pytest.raises(fields.Refusal) as caught:
        model_of(board)
    assert str(caught.value) == (
        "group g: the via of S at (105, 100) crosses the GND plane on In2.Cu: the model cuts no antipad, "
        "so the via would short the net to the plane"
    )


def test_a_wave_that_never_arrives_is_no_measure():
    """|S21| is 0 at 1 GHz: -20 log10 of it is the arithmetic's floor (600 dB), not a loss. The
    insertion loss is not measured, with the reason, and its limit is not judged; it never fails or
    holds on that number."""
    m = fields.line_measures([1e9, 2e9, 3e9], [0.1, 0.1, 0.1], [0.0, 0.5, 0.5])
    assert m["insertion_loss_db"]["value"] is None
    assert "impedance_ohm" not in m
    limits = [{"measure": "insertion_loss_db", "net": "X", "max": 3, "source": "d"}]
    fails, held, unjudged = fields.judge(limits, {"X": m})
    assert fails == [] and held == []
    assert unjudged == [
        "X insertion_loss_db: not judged, |S| is 0 at 1 GHz: no wave reached the port, "
        "so nothing was measured"
    ]


def stub_spec(**group):
    spec = fields.read_spec(STUB / "fields.json")
    spec["groups"][0].update(group)
    return spec


def test_a_pad_carries_its_reach():
    """The stub fixture's pads are 0.36 x 0.36 mm: half the diagonal is sqrt(0.36^2 + 0.36^2) / 2 =
    0.50912 / 2 = 0.254558 mm."""
    board = fields.read_board(STUB / "stub.kicad_pcb")
    assert board.pads["J1.1"][2:] == ("SIG", pytest.approx(0.254558, abs=1e-6))


def test_a_port_on_a_pad_of_another_net_is_refused():
    """J9.1 stands at (140, 140) on GND. Its port went to the nearest free end of the group, the stub's
    open end, and the stub passed: refused, naming the pad and its net."""
    board = fields.read_board(STUB / "stub.kicad_pcb")
    board.pads["J9.1"] = (140.0, 140.0, "GND", 0.254558)
    spec = stub_spec(ports=["J1.1", "J9.1"])
    with pytest.raises(fields.Refusal) as caught:
        fields.build_model(board, spec["groups"][0], spec)
    assert str(caught.value) == (
        "group sig, `ports` of fields.json: pad J9.1 is on net GND, not a net of the group"
    )


def test_a_pad_named_twice_is_refused():
    board = fields.read_board(STUB / "stub.kicad_pcb")
    spec = stub_spec(ports=["J1.1", "J1.1"])
    with pytest.raises(fields.Refusal, match=r"`ports` of fields.json: pad J1.1 is named 2 times$"):
        fields.build_model(board, spec["groups"][0], spec)


def test_a_pad_far_from_every_end_is_refused():
    """J2.1 moved to (110, 103). The free ends of SIG are (100, 100), (110, 100) and (105, 107): the
    nearest is (110, 100), 3 mm away, and the pad reaches 0.255 mm."""
    board = fields.read_board(STUB / "stub.kicad_pcb")
    board.pads["J2.1"] = (110.0, 103.0, "SIG", 0.254558)
    spec = fields.read_spec(STUB / "fields.json")
    with pytest.raises(fields.Refusal) as caught:
        fields.build_model(board, spec["groups"][0], spec)
    assert str(caught.value) == (
        "group sig, `ports` of fields.json: pad J2.1 at (110, 103): the nearest free end of SIG, (110, 100), "
        "is 3.000 mm away and the pad reaches 0.255 mm"
    )


def test_2_pads_on_1_end_are_refused():
    """J3.1 at (110, 100.1) lies 0.1 mm from the end (110, 100), J2.1's port already."""
    board = fields.read_board(STUB / "stub.kicad_pcb")
    board.pads["J3.1"] = (110.0, 100.1, "SIG", 0.254558)
    spec = stub_spec(ports=["J1.1", "J2.1", "J3.1"])
    with pytest.raises(fields.Refusal, match=r"pad J3.1 gives the end at \(110, 100\), a port already$"):
        fields.build_model(board, spec["groups"][0], spec)


def test_an_open_end_is_never_made_a_port():
    """Without `ports` the stub's net has 3 free ends: (100, 100), (105, 107) and (110, 100). The open
    end of the stub is part of what is judged; a port there terminates the fault in 50 ohm (the run
    gave 4.06 dB where the named ports give 29.55). Refused: name the pads."""
    board = fields.read_board(STUB / "stub.kicad_pcb")
    spec = fields.read_spec(STUB / "fields.json")
    del spec["groups"][0]["ports"]
    with pytest.raises(fields.Refusal) as caught:
        fields.build_model(board, spec["groups"][0], spec)
    assert str(caught.value) == (
        "group sig: net SIG has 3 free track ends ((100, 100), (105, 107), (110, 100)) and fields.json "
        "names no `ports`: an open end is part of the structure, never a port; name the pads"
    )


def four_ports(by_net):
    ports, n = [], 0
    for net, count in by_net:
        for _ in range(count):
            n += 1
            ports.append({"n": n, "net": net})
    return {
        "frequencies_hz": [1e9],
        "settings": {"port_ohm": 50.0},
        "nets": [net for net, _ in by_net],
        "ports": ports,
    }


def test_next_is_taken_at_the_other_nets_first_port_and_fext_at_its_last():
    """Nets A (ports 1, 2) and B (ports 3, 4). Port 1 driven: S31 = 0.2 and S41 = 0.05, so NEXT into B is
    20 log10 0.2 = -13.979 dB and FEXT 20 log10 0.05 = -26.021 dB. Port 3 driven: S13 = 0.01 and S23 =
    0.02, so NEXT into A is 20 log10 0.01 = -40 dB and FEXT 20 log10 0.02 = -33.979 dB."""
    model = four_ports([("A", 2), ("B", 2)])
    columns = {1: [[0.1], [0.9], [0.2], [0.05]], 3: [[0.01], [0.02], [0.1], [0.9]]}
    out = fields.group_measures(model, columns)
    assert out["B"]["next_db from A"]["value"] == pytest.approx(-13.9794, abs=1e-4)
    assert out["B"]["fext_db from A"]["value"] == pytest.approx(-26.0206, abs=1e-4)
    assert out["A"]["next_db from B"]["value"] == pytest.approx(-40.0, abs=1e-4)
    assert out["A"]["fext_db from B"]["value"] == pytest.approx(-33.9794, abs=1e-4)


def test_a_net_of_3_ports_has_no_impedance():
    """The impedance formula is a symmetric 2-port's. A net with 3 ports (a T) gets its return and
    insertion loss and no impedance: a limit on it is not judged."""
    model = four_ports([("A", 3)])
    out = fields.group_measures(model, {1: [[0.1], [0.5], [0.5]]})
    assert set(out["A"]) == {"return_loss_db", "insertion_loss_db"}


def test_the_impedance_is_judged_on_a_uniform_line_alone():
    """The formula gives the image impedance of whatever 2-port it is handed: 2.5 mm of 30 ohm, 5 mm of
    80 ohm and 2.5 mm of 30 ohm read 49.32 ohm, inside 45 to 55. It is a track's impedance only on a
    net of 1 width, on 1 layer, with no branch. The stub fixture's SIG branches at (105, 100), where 3
    track ends meet; a net of a 0.3 mm and a 0.5 mm piece has 2 widths; the line fixture is uniform.
    A limit on a net that is not is not judged, with the reason."""
    stub_board = fields.read_board(STUB / "stub.kicad_pcb")
    spec = fields.read_spec(STUB / "fields.json")
    stub = fields.build_model(stub_board, spec["groups"][0], spec)
    assert stub["no_impedance"] == {"SIG": "SIG branches at (105, 100): the impedance is a uniform line's"}
    assert line_model()["no_impedance"] == {}
    t = fields.Track
    board = line_board([pour("GND", "B.Cu")])
    board.tracks = [t("S", "F.Cu", (100, 100), (105, 100), 0.3), t("S", "F.Cu", (105, 100), (110, 100), 0.5)]
    model = model_of(board)
    assert model["no_impedance"] == {"S": "S has 2 widths (0.3, 0.5 mm): the impedance is a uniform line's"}
    model["frequencies_hz"] = [1e9, 2e9, 3e9]
    out = fields.group_measures(model, {1: [[0.1 + 0j] * 3, [-0.9j] * 3]})
    limits = [{"measure": "impedance_ohm", "net": "S", "min": 45, "max": 55, "source": "d"}]
    fails, held, unjudged = fields.judge(limits, out)
    assert fails == [] and held == []
    assert unjudged == [
        "S impedance_ohm: not judged, S has 2 widths (0.3, 0.5 mm): the impedance is a uniform line's"
    ]


def test_a_net_on_2_layers_has_no_impedance():
    """S runs on F.Cu to a blind via at (105, 100), then on In1.Cu, both over a GND plane on B.Cu."""
    t = fields.Track
    board = fields.Board(
        path=Path("v.kicad_pcb"),
        copper_z={"F.Cu": 0.4, "In1.Cu": 0.2, "B.Cu": 0.0},
        dielectrics=[(0.0, 0.2, 4.5, 0.02), (0.2, 0.4, 4.5, 0.02)],
        tracks=[t("S", "F.Cu", (100, 100), (105, 100), 0.36), t("S", "In1.Cu", (105, 100), (110, 100), 0.36)],
        vias=[fields.Via("S", (105, 100), 0.3, ("F.Cu", "In1.Cu"))],
        zones=[pour("GND", "B.Cu")],
    )
    model = model_of(board)
    assert model["no_impedance"] == {
        "S": "S is on 2 layers (F.Cu, In1.Cu): the impedance is a uniform line's"
    }


@pytest.mark.parametrize(
    ("settings", "says"),
    [
        ([1], "`settings` is an object of names and numbers, not [1]"),
        ("x", "`settings` is an object of names and numbers, not 'x'"),
        ({"frequencies": 1}, "setting `frequencies` is 1, not a whole number of 2 or more"),
        (
            {"cells_per_dielectric": 0.5},
            "setting `cells_per_dielectric` is 0.5, not a whole number of 1 or more",
        ),
        ({"max_timesteps": 1.5}, "setting `max_timesteps` is 1.5, not a whole number of 1 or more"),
        ({"end_criteria_db": 3}, "setting `end_criteria_db` is 3, not a number below 0"),
    ],
)
def test_a_wrong_setting_is_refused(tmp_path, settings, says):
    """Each of these ended in a traceback (no `.items` on a list or a str, a division by 0 for 1
    frequency or int(0.5) cells)."""
    path = write_spec(tmp_path, json.dumps({"settings": settings, "groups": []}))
    with pytest.raises(fields.Refusal) as caught:
        fields.read_spec(path)
    assert str(caught.value) == f"fields.json: {says}"


def test_the_end_criterion_takes_its_own_sign(tmp_path):
    """The end criterion is a fall in energy, -40 dB by default: -30 is taken."""
    path = write_spec(tmp_path, json.dumps({"settings": {"end_criteria_db": -30}, "groups": []}))
    assert fields.read_spec(path)["settings"]["end_criteria_db"] == -30


def test_a_min_above_its_max_is_refused(tmp_path):
    path = write_spec(
        tmp_path,
        '{"groups": [{"name": "a", "nets": ["X"], "band_ghz": [0.1, 1],'
        ' "limits": [{"measure": "impedance_ohm", "net": "X", "min": 80, "max": 20, "source": "d"}]}]}',
    )
    with pytest.raises(fields.Refusal, match=r"group a: impedance_ohm of X: min 80 is above max 20$"):
        fields.read_spec(path)


# ---------------------------------------------------------------- a result that does not hang on the clock


def test_the_ports_settle_where_5_samples_lie_40_db_under_the_peak():
    """Port energy 0, 1, 100, 10, then 0.001, 0.005, 0.001, 0.001, 0.001, 0.001, 0.001, 1. The peak is
    100 at sample 2; 40 dB under it is 100 x 1e-4 = 0.01. Up to sample 8 the last sample above 0.01 is
    10, sample 3, and samples 4 to 8 lie under it: settled at 8. A series that ends before has not
    settled. Sample 11, 1, is a wave that came late, a far port's on a long line: the cut waits for 5
    quiet samples after it, 16, and a series that ends before that has not settled."""
    e = [0, 1, 100, 10, 0.001, 0.005, 0.001, 0.001, 0.001, 0.001, 0.001, 1]
    assert fields.settled(e[:9], -40.0) == 8
    assert fields.settled(e[:8], -40.0) is None
    assert fields.settled(e, -40.0) is None
    assert fields.settled(e + [0.001] * 5, -40.0) == 16


def write_probe(folder, name, values, dt=1e-11):
    rows = "".join(f"{k * dt:.6e}\t{v:.9e}\n" for k, v in enumerate(values))
    (folder / name).write_text(f"% t/s\tvalue\n{rows}", encoding="utf-8")


def test_where_openems_stops_does_not_change_the_result(tmp_path):
    """openEMS checks its end criterion every 4 s of the clock, so 2 runs of 1 file stop at different
    steps (the stub: 7189 to 8453) and gave 29.55 to 29.99 dB. Both runs here hold the same samples
    up to where they stop: u1 = 0, 1, 0.5, then 0.001; u2 = 0, 0.5, 0.25, then 0.001; each i = u / 50.
    The port energy is 2 (u1^2 + u2^2): peak 2 x 1.25 = 2.5 at sample 1, 40 dB under it 2.5e-4. From
    sample 3 every sample is 2 x 2e-6 = 4e-6, so the ports settle at sample 2 + 5 = 7. Run A goes on
    with 0.005 to sample 12 (2 x 2.5e-5 = 5e-5, quiet: openEMS stops 10 dB under the criterion), run
    B ends at sample 8: both columns are read from samples 0 to 7 and are the same. Run C ends at
    sample 5, before the ports settle: a fault, not a result."""
    tail = [0.001] * 6
    runs = {"a": tail + [0.005] * 4, "b": tail, "c": tail[:3]}
    model = {
        "frequencies_hz": [1e9, 2e9],
        "settings": {"port_ohm": 50.0, "end_criteria_db": -40.0},
        "ports": [{"n": 1, "net": "S"}, {"n": 2, "net": "S"}],
    }
    cols = {}
    for name, rest in runs.items():
        run = tmp_path / name
        run.mkdir()
        u1, u2 = [0.0, 1.0, 0.5] + rest, [0.0, 0.5, 0.25] + rest
        for n, u in ((1, u1), (2, u2)):
            write_probe(run, f"port_ut{n}", u)
            write_probe(run, f"port_it{n}", [x / 50 for x in u])
        if name == "c":
            with pytest.raises(fields.EngineFault, match="did not settle 40 dB under their peak"):
                fields.OpenEMS.column(run, model, 1)
        else:
            cols[name] = fields.OpenEMS.column(run, model, 1)
    assert cols["a"] == cols["b"]


def test_the_cut_waits_for_the_wave_to_cross_and_come_back(tmp_path):
    """A line longer than the pulse: between the driven pulse and its arrival at the far port, every
    port is quiet. Port 1 carries 0, 1, 0.5, then 0; port 2 carries the same wave 0.9 times as large
    19 samples later, at samples 20 and 21; i1 = u1 / 50 (a wave in) and i2 = -u2 / 50 (a wave out).
    The energy's peak is 2 x 1.25 = 2.5 at sample 1, and 40 dB under it is 2.5e-4; samples 3 to 7 are 0:
    the cut fell at sample 7, before port 2 heard anything, and |S21| was 0 (on the z57 run's probes
    delayed by 40 samples, -85 to -66 dB). The last sample above 2.5e-4 is 21 (2 x 0.45^2 = 0.405):
    the cut falls 5 quiet samples later, at 26, and |S21| = 0.9, |S11| = 0."""
    u1 = [0.0, 1.0, 0.5] + [0.0] * 40
    u2 = [0.0] * 20 + [0.9, 0.45] + [0.0] * 21
    for name, values in (
        ("ut1", u1),
        ("it1", [u / 50 for u in u1]),
        ("ut2", u2),
        ("it2", [-u / 50 for u in u2]),
    ):
        write_probe(tmp_path, f"port_{name}", values)
    model = {
        "frequencies_hz": [1e9, 2e9],
        "settings": {"port_ohm": 50.0, "end_criteria_db": -40.0},
        "ports": [{"n": 1, "net": "S"}, {"n": 2, "net": "S"}],
    }
    s11, s21 = fields.OpenEMS.column(tmp_path, model, 1)
    assert [abs(x) for x in s21] == pytest.approx([0.9, 0.9])
    assert [abs(x) for x in s11] == pytest.approx([0.0, 0.0], abs=1e-12)
    energy = [2 * (a * a + b * b) for a, b in zip(u1, u2, strict=True)]
    assert fields.settled(energy, -40.0) == 26


class StopsEarly:
    """openEMS as the Wyvern lane's port 3 ran it on 2026-11-17: on a busy machine its check of the end
    criterion, every 4 s of the clock, fell at step 13410 and the ports had not settled; at 13708 and
    later they had. Here a run settles from the run whose box energy falls `settles_at` dB under the
    end criterion."""

    program = "openEMS"

    def __init__(self, settles_at: float):
        self.settles_at, self.margins = settles_at, []

    def xml(self, model, driven, margin_db):
        self.margins.append(margin_db)
        return f"<openEMS margin='{margin_db}'/>"

    def run(self, run, timeout):
        return True, "Time for 13410 iterations"

    def column(self, run, model, driven):
        if self.margins[-1] < self.settles_at:
            raise fields.NotSettled("the port signals did not settle 40 dB under their peak")
        return [[0.5]]


def test_a_run_that_stopped_before_the_ports_settled_runs_again_deeper(tmp_path):
    """The first run stops 10 dB under the criterion (ENGINE_MARGIN_DB) and has not settled: it runs again
    20 dB under it, settles, and gives its column, with no fault. Margins: 10, then 20."""
    engine = StopsEarly(settles_at=20.0)
    model = {"settings": {"timeout_s": 60}}
    (tmp_path / "model.xml").write_text(engine.xml(model, 1, fields.ENGINE_MARGIN_DB), encoding="utf-8")
    column, error = fields.run_port(engine, model, tmp_path, 1)
    assert (column, error) == ([[0.5]], None)
    assert engine.margins == [10.0, 20.0]
    assert "margin='20.0'" in (tmp_path / "model.xml").read_text(encoding="utf-8")


def test_a_run_that_never_settles_is_a_fault_after_the_deepest_run(tmp_path):
    """Margins 10, 20 and 30 dB: none settles, and the fault names the deepest, 30 dB."""
    engine = StopsEarly(settles_at=99.0)
    model = {"settings": {"timeout_s": 60}}
    (tmp_path / "model.xml").write_text(engine.xml(model, 3, fields.ENGINE_MARGIN_DB), encoding="utf-8")
    column, error = fields.run_port(engine, model, tmp_path, 3)
    assert column is None and engine.margins == [10.0, 20.0, 30.0]
    assert error == (
        "openEMS on port 3 ended without a result: the port signals did not settle 40 dB under their peak"
        " (run 3 times, the last to 30 dB under the end criterion)"
    )
