"""`workcenter copper`: the 2 solvers against cases worked by hand, and the 2 fixture boards.

The solvers run on grids built here, so their tests need numpy alone. The fixture boards are read with
KiCad's pcbnew module; those tests are skipped where it is not importable (PROCESSES.md P12).
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
np = pytest.importorskip("numpy")
import copper  # noqa: E402

BOARDS = ROOT / "tests" / "boards"
CLI = ROOT / "tools" / "workcenter"

try:
    import pcbnew  # noqa: F401

    HAS_PCBNEW = True
except ImportError:
    HAS_PCBNEW = False
needs_pcbnew = pytest.mark.skipif(not HAS_PCBNEW, reason="KiCad's pcbnew module is not importable")


# ---------------------------------------------------------------- the drop


def test_strip_drop_and_density_match_a_strip_worked_by_hand():
    """A strip's resistance is R = rho L / A (Halliday, Resnick and Walker, Fundamentals of Physics,
    the chapter "Current and Resistance": the resistance of a uniform wire from its resistivity).

    The strip: 1 layer of 35 um copper, 1.0 mm wide (20 cells of 0.05 mm), 20 mm between the centres
    of its 2 end columns (401 cells). rho = 1.7241e-8 Ohm m at 20 C (NBS Handbook 100, section 2a,
    page 3; rules/copper/materials.json).

        R = 1.7241e-8 x 0.020 / (1.0e-3 x 35e-6) = 3.4482e-10 / 3.5e-8 = 9.852e-3 Ohm
        2 A through it: V = 2 x 9.852e-3 = 19.704 mV
        J = I / (w t) = 2 / (1.0 mm x 0.035 mm) = 57.143 A/mm2

    The first column is held at 0 V and the last draws 2 A. The current in a uniform strip is uniform,
    and the solver's sum over cells is the same sum: it is held to 1e-6 of it."""
    a, t = 0.05, 0.035
    mask = np.ones((1, 20, 401), dtype=bool)
    fixed = np.zeros_like(mask)
    fixed[0, :, 0] = True
    amps = np.zeros(mask.shape)
    amps[0, :, -1] = -2.0 / 20
    sheet = np.array([t * 1e-3 / 1.7241e-8])  # siemens per square
    volts = copper.solve_drop(mask, sheet, [], fixed, amps)
    assert -volts[0, :, -1].mean() == pytest.approx(19.704e-3, rel=1e-6)
    j = copper.density(volts, mask, sheet, np.array([t]), a)
    assert j[0, 10, 200] == pytest.approx(57.143, rel=1e-4)


def test_two_layers_through_a_via_add_the_barrel_in_series():
    """2 strips of the first test's size, 1 on each layer, joined at their far ends by 1 barrel of
    conductance 100 S (0.01 Ohm). Series resistances add: 9.852e-3 + 0.01 + 9.852e-3 = 29.704 mOhm,
    and 1 A drops 29.704 mV."""
    t = 0.035
    mask = np.zeros((2, 1, 401), dtype=bool)
    mask[:, 0, :] = True
    fixed = np.zeros_like(mask)
    fixed[0, 0, 0] = True
    amps = np.zeros(mask.shape)
    amps[1, 0, 0] = -1.0
    # 1 cell stands for the 1.0 mm width: each side between 2 cells of 0.05 mm is 1.0 / 0.05 = 20
    # squares in parallel, and 400 sides in series give 400 / 20 = 20 squares, 20 mm by 1.0 mm.
    sheet = np.array([t * 1e-3 / 1.7241e-8] * 2) * (1.0 / 0.05)
    volts = copper.solve_drop(mask, sheet, [(0, 1, 0, 400, 100.0)], fixed, amps)
    assert -volts[1, 0, 0] == pytest.approx(29.704e-3, rel=1e-6)


# ---------------------------------------------------------------- the heat


def test_plate_temperature_matches_a_fin_worked_by_hand():
    """A plate heated at 1 end and cooled by the air on its 2 faces is a fin of uniform section with an
    adiabatic tip: q = M tanh(m L), M = sqrt(h P k Ac) theta_b, m = sqrt(h P / (k Ac)) (Incropera,
    DeWitt, Bergman and Lavine, Fundamentals of Heat and Mass Transfer, section 3.6, table 3.4, case B).

    The plate: 35 um of copper (k = 400 W/m K, TI SNVA419C table 1, page 4), w = 2 mm (20 cells of
    0.1 mm), L = 100 mm (1000 cells), h = 10 W/m2 K on each face and none on the edges, so P = 2 w.
    0.01 W comes in at the first column.

        m = sqrt(2 h / (k t)) = sqrt(20 / (400 x 35e-6)) = sqrt(1428.57) = 37.796 1/m; m L = 3.7796
        tanh(3.7796) = 0.998958
        sqrt(h P k Ac) = sqrt(10 x 4e-3 x 400 x 7e-8) = sqrt(1.12e-6) = 1.05830e-3 W/K
        theta_b = q / (sqrt(h P k Ac) tanh(m L)) = 0.01 / (1.05830e-3 x 0.998958) = 9.459 K

    The first column's centre stands 0.05 mm from the base, where the fin is cosh(m (L - a/2)) /
    cosh(m L) = 0.99811 of theta_b: 9.441 K. The solver is held to 0.1 % of 9.441 K there, and to 2 %
    of theta_b / cosh(m L) = 9.459 / 21.92 = 0.4316 K at the tip."""
    a = 0.1e-3
    shape = (1, 20, 1000)
    lateral = np.full(shape, 400 * 35e-6)  # W/K per square
    air = np.full(shape, 2 * 10 * a * a)  # W/K to the air, both faces
    watts = np.zeros(shape)
    watts[0, :, 0] = 0.01 / 20
    rise = copper.solve_heat(lateral, np.zeros((0, 20, 1000)), air, watts, [])
    assert rise[0, :, 0].mean() == pytest.approx(9.441, rel=1e-3)
    assert rise[0, :, -1].mean() == pytest.approx(0.4316, rel=2e-2)


def test_heat_balance_holds_on_a_plate_heated_evenly():
    """Heat in equals heat out: a plate of N cells, each losing g to the air and each given P, stands
    P / g above the air everywhere. 1e-3 W over 2e-6 W/K is 500 K."""
    shape = (2, 5, 7)
    rise = copper.solve_heat(
        np.full(shape, 0.01), np.full((1, 5, 7), 1e-3), np.full(shape, 2e-6), np.full(shape, 1e-3), []
    )
    assert np.allclose(rise, 500.0, rtol=1e-6)


# ---------------------------------------------------------------- the fixture boards


def run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        timeout=600,
    )


@pytest.mark.parametrize("fixture", ["pass-copper-strip", "fail-copper-neck"])
def test_fixture_is_what_its_design_writes(fixture, tmp_path):
    proc = run_cli("design", str(BOARDS / fixture / "design.py"), "--check", "--out", str(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    board = (BOARDS / fixture / "strip.kicad_pcb").read_text(encoding="utf-8")
    assert board == (tmp_path / "strip.kicad_pcb").read_text(encoding="utf-8")


# ---------------------------------------------------------------- boards built in the test


class Stub(copper.BoardCopper):
    """A board built here, with no KiCad file: its copper layers by depth (mm), 35 um each, and shapes."""

    def __init__(self, depths: dict[str, float], shapes: list, plating: float = 0.02, thickness: float = 1.6):
        self.layers = list(depths)
        self.cu = {name: SimpleNamespace(z=z, thickness=0.035) for name, z in depths.items()}
        self.shapes, self.plating, self.thickness = shapes, plating, thickness
        self.outline, self.stackup, self.parts, self.where = [], True, {}, {}


def rect(x0: float, y0: float, x1: float, y1: float) -> list:
    return [([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], [])]


def disk(x: float, y: float, r: float, n: int = 64) -> list:
    return [
        (
            [
                (x + r * math.cos(2 * math.pi * k / n), y + r * math.sin(2 * math.pi * k / n))
                for k in range(n)
            ],
            [],
        )
    ]


TWO = {"F.Cu": 0.0, "B.Cu": 1.6}


def test_cover_gives_each_cell_its_share_of_copper():
    """A square of 1 mm side turned 30 degrees has an area of 1 mm2; on cells of 0.05 mm the shares sum
    to 1 / 0.05^2 = 400 cells. A track 0.152 mm wide covers 0.152 / 0.05 = 3.04 cells of each column."""
    grid = copper.Grid(100.0, 100.0, 0.05, 80, 80)
    c, s = math.cos(math.pi / 6), math.sin(math.pi / 6)
    square = [
        (101.7 + 0.5 * (c * x - s * y), 101.9 + 0.5 * (s * x + c * y))
        for x, y in ((-1, -1), (1, -1), (1, 1), (-1, 1))
    ]
    assert copper.cover(grid, [(square, [])]).sum() == pytest.approx(400.0, rel=1e-9)
    track = copper.cover(grid, rect(100.5, 101.924, 103.0, 102.076))
    assert np.allclose(track[:, 10:60].sum(axis=0), 3.04, rtol=1e-9)
    assert track.max() == pytest.approx(1.0)


def test_a_track_narrower_than_whole_cells_drops_what_its_width_gives():
    """A 0.152 mm track (6 mil), 30 mm long on 1 layer of 35 um, 1 A from J1.1 to J2.1, each pad the end
    column of 0.05 mm. Between the 2 columns' centres L = 29.95 mm. R = rho L / (w t) (the strip test's
    law): 1.7241e-8 x 29.95e-3 / (0.152e-3 x 35e-6) = 5.16368e-10 / 5.32e-9 = 0.097062 Ohm, so 1 A drops
    97.062 mV, and J = 1 / (0.152 x 0.035) = 187.97 A/mm2. A cell whose centre decides puts 4 cells,
    0.2 mm, under it and reads 24 % low. With each cell weighted by its copper the straight track is
    exact: each is held to 1e-4, the rounding of the hand's last digit."""
    shapes = [
        copper.Shape("track", "+5V", ["F.Cu"], {"F.Cu": rect(105.0, 109.924, 135.0, 110.076)}, width=0.152),
        copper.Shape(
            "pad", "+5V", ["F.Cu"], {"F.Cu": rect(105.0, 109.924, 105.05, 110.076)}, ref="J1", pad="1"
        ),
        copper.Shape(
            "pad", "+5V", ["F.Cu"], {"F.Cu": rect(134.95, 109.924, 135.0, 110.076)}, ref="J2", pad="1"
        ),
    ]
    bc = Stub({"F.Cu": 0.0}, shapes)
    grid = copper.Grid(100.0, 100.0, 0.05, 800, 400)
    drop = copper.net_drop(bc, grid, "+5V", "J1.1", {"J2.1": 1.0}, 1.7241e-8)
    assert drop.drops["J2.1"] == pytest.approx(97.062e-3, rel=1e-4)
    assert np.nanmax(drop.density) == pytest.approx(187.97, rel=1e-4)


def via_board(plating: float) -> Stub:
    """+5V on F.Cu, 1.5 mm, from J1.1 to 1 via (0.3 mm drill, 0.6 mm pad) at x 125, then on B.Cu to J2.1."""
    via = copper.Shape(
        "via",
        "+5V",
        ["F.Cu", "B.Cu"],
        {ly: disk(125.0, 110.0, 0.3) for ly in TWO},
        at=(125.0, 110.0),
        drill=0.3,
    )
    return Stub(
        TWO,
        [
            copper.Shape("track", "+5V", ["F.Cu"], {"F.Cu": rect(105.0, 109.25, 125.0, 110.75)}, width=1.5),
            copper.Shape("track", "+5V", ["B.Cu"], {"B.Cu": rect(125.0, 109.25, 145.0, 110.75)}, width=1.5),
            via,
            copper.Shape(
                "pad", "+5V", ["F.Cu"], {"F.Cu": rect(105.0, 109.25, 105.5, 110.75)}, ref="J1", pad="1"
            ),
            copper.Shape(
                "pad", "+5V", ["B.Cu"], {"B.Cu": rect(144.5, 109.25, 145.0, 110.75)}, ref="J2", pad="1"
            ),
        ],
        plating=plating,
    )


def test_a_via_barrel_carries_its_current_density():
    """All of J2.1's 1 A goes through the 1 via. Its barrel, 0.3 mm drill and 0.02 mm plating, is
    pi x (0.17^2 - 0.15^2) = pi x 0.0064 = 0.020106 mm2 of copper: 1 / 0.020106 = 49.736 A/mm2. Against
    45 A/mm2 it fails, where the tracks (1.5 mm, 19.05 A/mm2) hold."""
    grid = copper.Grid(100.0, 100.0, 0.05, 1000, 400)
    drop = copper.net_drop(via_board(0.02), grid, "+5V", "J1.1", {"J2.1": 1.0}, 1.7241e-8)
    (barrel,) = drop.barrels
    assert barrel.amps == pytest.approx(1.0, rel=1e-6)
    assert barrel.density == pytest.approx(49.736, rel=1e-4)
    ask = copper.NetAsk(
        "+5V", "J1.1", None, copper.Limit(45.0, "the project's rule", "copper.json: nets: +5V: amps_per_mm2")
    )
    found = copper.barrel_finding(ask, barrel, "J1")
    assert found.status == "fail"
    assert found.line == (
        "copper: fail +5V barrel current density 49.74 A/mm2, 1 A in the via at (125.00, 110.00) F.Cu to "
        "B.Cu, near J1, limit 45 A/mm2 (copper.json: nets: +5V: amps_per_mm2: the project's rule)"
    )


def test_a_track_wider_than_the_grid_is_asked_for_and_a_narrower_one_refused():
    """A cell of the drop must not be wider than the narrowest track of a judged net: on 0.4 mm cells a
    0.3 mm neck is less than 1 cell, and its copper can fall between cells."""
    bc = Stub(
        {"F.Cu": 0.0},
        [copper.Shape("track", "+5V", ["F.Cu"], {"F.Cu": rect(105, 110, 135, 110.3)}, width=0.3)],
    )
    copper.check_grid(bc, ["+5V"], 0.3)
    with pytest.raises(copper.ratings.Refusal) as caught:
        copper.check_grid(bc, ["+5V"], 0.4)
    assert str(caught.value) == (
        "copper.json: grid: drop: 0.4 mm is wider than +5V's narrowest track, 0.3 mm; a cell of at most "
        "0.3 mm is asked"
    )


def test_an_ambient_where_copper_would_have_no_resistance_is_refused(tmp_path):
    """rho = rho20 (1 + a (T - 20)) with a = 0.00393 (NBS Handbook 100, section 2b, page 3) reaches 0 at
    T = 20 - 1 / 0.00393 = -234.45 C; an ambient at or below it is refused, naming the key."""
    path = tmp_path / "copper.json"
    path.write_text(json.dumps({"air": {"ambient": -250, "source": "s"}, "nets": {}}), encoding="utf-8")
    with pytest.raises(copper.ratings.Refusal) as caught:
        copper.read_copper(path, set(), {}, copper.read_materials())
    assert str(caught.value).startswith("copper.json: air: ambient: -250 C is not above -234.5 C")


def test_a_resistors_current_on_its_pin_gives_its_heat():
    """R1, 220 ohms, 2 pins, with 0.024 A stated on R1.1: 0.024^2 x 220 = 0.12672 W, as when it is stated
    on R1."""
    bc = Stub({"F.Cu": 0.0}, [])
    bc.parts = {"R1": copper.ratings.Part("R1", "220", "", "", True, pins={"1": "+5V", "2": "GND"})}
    for key in ("R1", "R1.1", "R1.2"):
        watts, how = copper.dissipation(bc, SimpleNamespace(watts={}, amps={key: 0.024}))
        assert watts == {"R1": pytest.approx(0.12672, rel=1e-9)}, key


def test_a_resistor_with_a_current_and_no_ohms_is_not_judged():
    bc = Stub({"F.Cu": 0.0}, [])
    bc.parts = {"R1": copper.ratings.Part("R1", "DNP", "", "", True, pins={"1": "+5V", "2": "GND"})}
    watts, how = copper.dissipation(bc, SimpleNamespace(watts={}, amps={"R1": 0.024}))
    assert watts == {}
    assert how == []
    notes = copper.dissipation_notes(bc, SimpleNamespace(watts={}, amps={"R1": 0.024}))
    assert [n.line for n in notes] == [
        "copper: not judged R1: ratings.json states 0.024 A through it and its Value DNP gives no ohms; "
        "state its `watts`"
    ]


# ---------------------------------------------------------------- the board's heat network, by hand

MATERIALS = copper.read_materials()


def heat_of(bc: Stub, watts: np.ndarray, fine: copper.Grid, f: int) -> np.ndarray:
    asked = copper.Asked(
        [], 25.0, MATERIALS["air_natural_convection"], "still air", None, fine.pitch, fine.pitch * f
    )
    temp, _ = copper.board_heat(bc, asked, MATERIALS, watts, fine, f)
    return temp - 25.0


def test_board_heat_2_faces_and_the_fr4_between_2_layers():
    """2 layers 1.6 mm apart, 4 x 4 cells of 0.25 mm, no copper; 1e-5 W into each cell of F.Cu. Each face
    takes h a^2 = 10 x (0.25e-3)^2 = 6.25e-7 W/K (h: TI SNVA419C table 1, page 4); the FR-4 between
    gives k a^2 / d = 0.23 x 6.25e-8 / 1.6e-3 = 8.984375e-6 W/K. The heat is even, so no cell gives
    to its neighbour:

        q = h' T1 + g (T1 - T2), 0 = h' T2 - g (T1 - T2)
        sum: T1 + T2 = q / h' = 1e-5 / 6.25e-7 = 16 K
        difference: T1 - T2 = q / (h' + 2 g) = 1e-5 / 1.859375e-5 = 0.537815 K
        T1 = 8.268908 K, T2 = 7.731092 K"""
    fine = copper.Grid(0.0, 0.0, 0.05, 20, 20)
    watts = np.zeros((2, 20, 20))
    watts[0] = 1e-5 / 25
    rise = heat_of(Stub(TWO, []), watts, fine, 5)
    assert np.allclose(rise[0], 8.268908, rtol=1e-6)
    assert np.allclose(rise[1], 7.731092, rtol=1e-6)


def test_board_heat_a_via_barrel_joins_the_2_layers():
    """1 cell of 0.25 mm, 2 layers 1.6 mm apart, 1 via of 0.3 mm drill and 0.025 mm plating at its centre;
    1e-5 W into F.Cu. The barrel: pi x (0.175^2 - 0.15^2) = 0.0255254 mm2 of copper, k A / d = 400 x
    0.0255254e-6 / 1.6e-3 = 6.381360e-3 W/K, beside the FR-4's 8.984375e-6 W/K: g = 6.390344e-3 W/K.

        T1 + T2 = 16 K, T1 - T2 = 1e-5 / (6.25e-7 + 2 x 6.390344e-3) = 7.8239e-4 K
        T1 = 8.000391 K, T2 = 7.999609 K"""
    fine = copper.Grid(0.0, 0.0, 0.05, 5, 5)
    via = copper.Shape("via", "X", ["F.Cu", "B.Cu"], {}, at=(0.125, 0.125), drill=0.3)
    watts = np.zeros((2, 5, 5))
    watts[0] = 1e-5 / 25
    rise = heat_of(Stub(TWO, [via], plating=0.025), watts, fine, 5)
    assert rise[0, 0, 0] == pytest.approx(8.000391, rel=1e-6)
    assert rise[1, 0, 0] == pytest.approx(7.999609, rel=1e-6)


def test_board_heat_copper_and_fr4_spread_along_the_sheet():
    """1 layer of 35 um copper over the whole of a 1.6 mm board, 100 mm x 0.25 mm (400 cells of 0.25 mm),
    1e-3 W into the first column. The sheet is k t of the copper and of the FR-4, per square:
    400 x 35e-6 + 0.23 x 1.565e-3 = 0.014 + 3.59950e-4 = 0.01435995 W/K. Both faces cool the 1 layer.
    It is the fin of the plate test (Incropera table 3.4 case B):

        m = sqrt(2 h / G) = sqrt(20 / 0.01435995) = 37.31973 1/m, m L = 3.731973, tanh = 0.998854
        sqrt(2 h G) w = sqrt(0.287199) x 0.25e-3 = 1.339774e-4 W/K
        theta_b = 1e-3 / (1.339774e-4 x 0.998854) = 7.47251 K
        first cell's centre, 0.125 mm in: cosh(m (L - 0.125e-3)) / cosh(m L) = 0.995351: 7.43777 K

    Without the FR-4 it reads 7.5315 K (0.013 W/K); without the copper, 10 times more. Held to 0.2 %."""
    fine = copper.Grid(0.0, 0.0, 0.05, 2000, 5)
    sheet = copper.Shape("pour", "X", ["F.Cu"], {"F.Cu": rect(0.0, 0.0, 100.0, 0.25)})
    watts = np.zeros((1, 5, 2000))
    watts[0, :, :5] = 1e-3 / 25
    rise = heat_of(Stub({"F.Cu": 0.0}, [sheet]), watts, fine, 5)
    assert rise[0, 0, 0] == pytest.approx(7.43777, rel=2e-3)


def test_joule_heat_of_a_strip_is_its_i_squared_r():
    """The strip of the first test, 2 A over 9.852e-3 Ohm: I^2 R = 4 x 9.852e-3 = 0.039408 W, cell by
    cell summed."""
    mask = np.ones((1, 20, 401), dtype=bool)
    fixed = np.zeros_like(mask)
    fixed[0, :, 0] = True
    amps = np.zeros(mask.shape)
    amps[0, :, -1] = -2.0 / 20
    sheet = np.array([0.035e-3 / 1.7241e-8])
    volts = copper.solve_drop(mask, sheet, [], fixed, amps)
    assert copper.joule(volts, mask, sheet, []).sum() == pytest.approx(0.039408, rel=1e-4)


@needs_pcbnew
def test_the_board_heat_is_the_parts_and_the_nets(tmp_path, monkeypatch):
    """pass-copper-strip: the heat that goes into the board's network is R1's 0.024^2 x 220 = 0.12672 W
    and each judged net's own I^2 R, as the report gives it."""
    given = []
    real = copper.board_heat

    def spy(bc, asked, materials, watts, fine, f):
        given.append(float(watts.sum()))
        return real(bc, asked, materials, watts, fine, f)

    monkeypatch.setattr(copper, "board_heat", spy)
    report = copper.run(BOARDS / "pass-copper-strip" / "strip.kicad_pcb", tmp_path)
    nets = sum(r.watts for r in report.nets)
    assert nets > 0
    assert given == [pytest.approx(0.12672 + nets, rel=1e-9)]


def copy_strip(tmp_path: Path, change) -> Path:
    shutil.copytree(BOARDS / "pass-copper-strip", tmp_path / "strip", ignore=shutil.ignore_patterns("build"))
    asked = json.loads((tmp_path / "strip" / "copper.json").read_text(encoding="utf-8"))
    stated = json.loads((tmp_path / "strip" / "ratings.json").read_text(encoding="utf-8"))
    change(asked, stated)
    (tmp_path / "strip" / "copper.json").write_text(json.dumps(asked), encoding="utf-8")
    (tmp_path / "strip" / "ratings.json").write_text(json.dumps(stated), encoding="utf-8")
    return tmp_path / "strip"


@needs_pcbnew
def test_a_pin_with_no_stated_current_is_not_judged(tmp_path):
    """ratings.json keeps R1 alone: J2.1 on +5V and J2.2 on GND are taken as 0 A, and each net says so."""

    def change(asked, stated):
        stated["parts"] = {"R1": stated["parts"]["R1"]}

    proc = run_cli("copper", str(copy_strip(tmp_path, change)), "--strict")
    left = [ln for ln in proc.stdout.splitlines() if ln.startswith("copper: not judged")]
    assert left == [
        "copper: not judged +5V: ratings.json states no current at J2.1; taken as 0 A",
        "copper: not judged GND: ratings.json states no current at J2.2; taken as 0 A",
    ], proc.stdout
    assert proc.returncode == 1


@needs_pcbnew
def test_a_supply_net_of_ratings_json_that_copper_json_leaves_out_is_not_judged(tmp_path):
    """copper.json without GND, and no current stated on GND: ratings.json still names GND as a net."""

    def change(asked, stated):
        del asked["nets"]["GND"]
        stated["parts"] = {"J2.1": stated["parts"]["J2.1"]}

    proc = run_cli("copper", str(copy_strip(tmp_path, change)), "--strict")
    assert (
        "copper: not judged GND: ratings.json names this net and copper.json names no entry for it"
        in proc.stdout.splitlines()
    ), proc.stdout
    assert proc.returncode == 1


@needs_pcbnew
def test_neck_fails_on_current_density_at_the_neck_alone(tmp_path):
    """1 A through the neck, 0.3 mm of 35 um copper (KiCad's thickness on a board with no stackup):
    1 / (0.3 x 0.035) = 95.24 A/mm2, against the fixture's 50. Everything else holds. The 1.5 mm
    track's round ends reach 0.75 mm into the 4 mm, so 2.5 mm stand at 0.3 mm: 2.5 / 0.3 - 2.5 / 1.5 =
    6.667 squares more than the pass fixture, of 5.0228e-4 Ohm, at 1 A: 14.27 + 3.35 = 17.6 mV and
    some for the round ends, against 50. The heat is the pass fixture's.

    95.24 A/mm2 is the density where the neck runs straight; where the 1.5 mm track's round end meets
    it the current crowds into the corner and stands higher. The greatest density is held to be at
    least 95.24 less 2 %, at the neck."""
    proc = run_cli("copper", str(BOARDS / "fail-copper-neck"), "--out", str(tmp_path))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    fails = [ln for ln in proc.stdout.splitlines() if ln.startswith("copper: fail")]
    assert len(fails) == 1, proc.stdout
    assert fails[0].startswith("copper: fail +5V current density ")
    assert "limit 50 A/mm2 (copper.json: nets: +5V: amps_per_mm2:" in fails[0]
    record = json.loads((tmp_path / "copper" / "report.json").read_text(encoding="utf-8"))
    supply = next(n for n in record["nets"] if n["name"] == "+5V")
    x, y, layer = supply["density_at"]
    assert 123.0 <= x <= 127.0 and abs(y - 110.0) < 0.2 and layer == "F.Cu"
    assert supply["density"] >= 95.24 * 0.98
    assert not [ln for ln in proc.stdout.splitlines() if ln.startswith("copper: not judged")]
    assert "COPPER NOT HELD (1 fail)" in proc.stdout


@needs_pcbnew
def test_strip_holds_every_limit_with_strict(tmp_path):
    """The same board with 1.5 mm all the way. Copper at the air's 25 C: 1.7241e-8 x (1 + 0.00393 x 5)
    = 1.75798e-8 Ohm m; over 35 um, 5.0228e-4 Ohm a square.

        J1.1's pad edge (103.85) to R1's tap (117.04): 13.19 mm / 1.5 mm = 8.793 squares, 1.024 A: 4.523 mV
        the tap to J2.1's pad edge (146.15): 29.11 mm / 1.5 mm = 19.407 squares, 1 A: 9.748 mV
        +5V: 14.27 mV, held to 5 % (the pads' own copper and the barrels add a little)

    1 A in 1.5 mm x 0.035 mm is 19.05 A/mm2. The heat: R1's 0.024^2 x 220 = 0.1267 W leaves by 2 faces of
    50 x 30 mm at 10 W/m2 K, 0.03 W/K: a mean rise of 4.224 K, so the hottest cell stands above
    25 + 4.224 = 29.22 C and, by the fixture's limit, under 105 C."""
    proc = run_cli("copper", str(BOARDS / "pass-copper-strip"), "--out", str(tmp_path), "--strict")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "COPPER HELD: pass-copper-strip" in proc.stdout
    assert not [
        ln for ln in proc.stdout.splitlines() if ln.startswith(("copper: fail", "copper: not judged"))
    ]
    record = json.loads((tmp_path / "copper" / "report.json").read_text(encoding="utf-8"))
    supply = next(n for n in record["nets"] if n["name"] == "+5V")
    assert supply["drop"] == pytest.approx(14.27e-3, rel=5e-2)
    assert supply["drop_at"] == "J2.1"
    hot = record["hottest"][0]
    assert 29.22 < hot < 105
    page = (tmp_path / "copper" / "report.md").read_text(encoding="utf-8")
    for picture in ("+5V-drop-F-Cu.png", "+5V-density-F-Cu.png", "heat-F-Cu.png", "heat-B-Cu.png"):
        assert f"]({picture})" in page and (tmp_path / "copper" / picture).is_file()
    assert "No enclosure and no air flow" in page


@needs_pcbnew
def test_a_net_with_a_current_and_no_entry_is_not_judged(tmp_path):
    """copper.json without GND: ratings.json still states 1 A at J2.2 and 0.024 A through R1 on it, and
    the run names GND as not judged; --strict fails on it."""
    shutil.copytree(BOARDS / "pass-copper-strip", tmp_path / "strip", ignore=shutil.ignore_patterns("build"))
    asked = json.loads((tmp_path / "strip" / "copper.json").read_text(encoding="utf-8"))
    del asked["nets"]["GND"]
    (tmp_path / "strip" / "copper.json").write_text(json.dumps(asked), encoding="utf-8")
    proc = run_cli("copper", str(tmp_path / "strip"), "--strict")
    assert proc.returncode == 1
    left = [ln for ln in proc.stdout.splitlines() if ln.startswith("copper: not judged")]
    assert left == [
        "copper: not judged GND: ratings.json states J2.2 1 A, R1.2 0.024 A "
        "and copper.json names no entry for it"
    ]
    assert "COPPER HELD, 1 NOT JUDGED" in proc.stdout
    assert run_cli("copper", str(tmp_path / "strip")).returncode == 0


@needs_pcbnew
def test_an_entry_on_another_net_is_refused(tmp_path):
    shutil.copytree(BOARDS / "pass-copper-strip", tmp_path / "strip", ignore=shutil.ignore_patterns("build"))
    asked = json.loads((tmp_path / "strip" / "copper.json").read_text(encoding="utf-8"))
    asked["nets"]["+5V"]["from"] = "J1.2"
    (tmp_path / "strip" / "copper.json").write_text(json.dumps(asked), encoding="utf-8")
    proc = run_cli("copper", str(tmp_path / "strip"))
    assert proc.returncode == 1
    assert proc.stdout.strip() == "copper: copper.json: nets: +5V: from: J1.2 is on GND, not on +5V"


def test_ratings_json_states_a_parts_heat_and_refuses_it_on_a_pin(tmp_path):
    """`watts` in ratings.json is the heat of a whole part; on 1 pin it is refused."""
    import ratings

    net = ratings.Netlist(
        {"U1": ratings.Part("U1", "X", "", "", True, pins={"1": "A", "2": "B"})},
        {
            "A": [ratings.Node("U1", "1", "", "passive", False)],
            "B": [ratings.Node("U1", "2", "", "passive", False)],
        },
    )
    stated = tmp_path / "ratings.json"
    stated.write_text(
        json.dumps({"pack": "p", "nets": {}, "parts": {"U1": {"watts": 0.4, "source": "s"}}}),
        encoding="utf-8",
    )
    assert ratings.read_project(stated, net).watts == {"U1": 0.4}
    stated.write_text(
        json.dumps({"pack": "p", "nets": {}, "parts": {"U1.1": {"watts": 0.4, "source": "s"}}}),
        encoding="utf-8",
    )
    with pytest.raises(ratings.Refusal, match=r"U1\.1: watts: the heat of a whole part is asked, `U1`"):
        ratings.read_project(stated, net)
