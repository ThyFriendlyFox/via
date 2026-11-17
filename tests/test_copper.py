"""`workcenter copper`: the 2 solvers against cases worked by hand, and the 2 fixture boards.

The solvers run on grids built here, so their tests need numpy alone. The fixture boards are read with
KiCad's pcbnew module; those tests are skipped where it is not importable (PROCESSES.md P12).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

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
