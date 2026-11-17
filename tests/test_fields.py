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

LINE = ROOT / "tests" / "boards" / "pass-fields-microstrip"
STUB = ROOT / "tests" / "boards" / "fail-fields-stub"
CLI = ROOT / "tools" / "workcenter"


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
    at z 0, so each port runs from z 0 to z 0.2, across the track's width (y 99.82 to 100.18), at the
    end's x, with 50 ohm."""
    ports = line_model()["ports"]
    assert [p["n"] for p in ports] == [1, 2]
    for port, x in zip(ports, (100, 110), strict=True):
        assert port["net"] == "SIG"
        assert port["r"] == 50
        assert port["start"] == pytest.approx([x, 99.82, 0.0])
        assert port["stop"] == pytest.approx([x, 100.18, 0.2])


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


def test_a_fixed_line_is_a_line_to_the_digit():
    """Cells summed one by one drift in the last digits: 0 is held as 0, not 1.5e-15, or a sheet at 0
    lies on no line of the mesh and the solver leaves it out."""
    lines = fields.mesh_lines([-3, 0, 0.05, 0.2, 3.2], 0.7)
    assert 0.0 in lines and 0.05 in lines and 0.2 in lines


def test_the_mesh_holds_every_edge_and_its_own_bounds():
    """The mesh is written from the geometry: x holds the box (97, 113) and the ports (100, 110); y holds
    the box (96.82, 103.18), the track's edges (99.82, 100.18) and 2 lines inside its width at its
    thirds: 99.82 + 0.12 = 99.94 and 99.82 + 0.24 = 100.06; z holds the air (-3, 3.2), the plane (0)
    and the track (0.2). No cell is larger than 0.706618 mm (10 GHz in 4.5) and no 2 neighbours differ
    by more than 2 times (`mesh_lines`: 1.5 within a run, 2 where 2 runs meet)."""
    mesh = line_model()["mesh"]
    for axis, must in (
        ("x", [97, 100, 110, 113]),
        ("y", [96.82, 99.82, 99.94, 100.06, 100.18, 103.18]),
        ("z", [-3, 0, 0.2, 3.2]),
    ):
        lines = mesh[axis]
        for value in must:
            assert min(abs(v - value) for v in lines) < 1e-9, (axis, value)
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
        zones=[("GND", ("B.Cu",))],
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
        zones=[("GND", ("F.Cu", "B.Cu"))],
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
    measure, the value, the limit and the source."""
    limits = [{"measure": "impedance_ohm", "net": "X", "min": 45, "max": 55, "source": "Doc rev 1, 3.2, p 7"}]
    measures = {"X": {"impedance_ohm": {"value": 55.8326, "at_hz": None}}}
    fails, held, unjudged = fields.judge(limits, measures)
    assert fails == ["X impedance_ohm 55.83 above max 55 (Doc rev 1, 3.2, p 7)"]
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
