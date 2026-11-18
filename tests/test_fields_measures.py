"""`workcenter fields`: the measures and models added to item 9 after its 2 reviews, with no solver.

A limit that says why it is not judged, a measure no limit names, the differential measures of a pair
from the 4-port result, the propagation constant of a line, the resonance of an antenna, copper with
its thickness or its loss, and a zone of the group's own net. Every expected value is worked out by
hand; the docstring shows the sum. The runs of openEMS are in tests/test_fields_solver.py.
"""

import cmath
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import fields  # noqa: E402

LINE = ROOT / "tests" / "boards" / "pass-fields-microstrip"


def write_spec(tmp_path, spec: dict) -> Path:
    path = tmp_path / "fields.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def group(limits, nets=("P", "N")):
    return {"groups": [{"name": "g", "nets": list(nets), "band_ghz": [0.1, 1], "limits": limits}]}


# ---------------------------------------------------------------- what is not judged


def test_a_limit_may_say_why_the_document_gives_none(tmp_path):
    """A limit with `unstated` in place of min and max is read, and the run prints its reason as a line
    that is not judged; it never passes."""
    why = "Doc rev 1, 6.2.1, p. 55: the channel is left to the maker"
    spec = fields.read_spec(
        write_spec(tmp_path, group([{"measure": "impedance_ohm", "net": "P", "unstated": why}], ("P",)))
    )
    limits = spec["groups"][0]["limits"]
    fails, held, unjudged = fields.judge(limits, {"P": {"impedance_ohm": {"value": 50.0, "at_hz": None}}})
    assert fails == [] and held == []
    assert unjudged == [f"P impedance_ohm 50.00: not judged, {why}"]


def test_unstated_takes_no_min_or_max(tmp_path):
    """A limit is a bound or the reason there is none, not both."""
    path = write_spec(
        tmp_path,
        group([{"measure": "impedance_ohm", "net": "P", "unstated": "d", "max": 3, "source": "d"}], ("P",)),
    )
    with pytest.raises(fields.Refusal, match=r"impedance_ohm of P: `unstated` takes no min, max or source"):
        fields.read_spec(path)


def test_a_measure_no_limit_names_is_said():
    """The run measured return loss and insertion loss of P; the 1 limit names insertion loss. Return
    loss is printed as not judged with its value, never left out."""
    limits = [{"measure": "insertion_loss_db", "net": "P", "max": 3, "source": "d"}]
    measures = {
        "P": {
            "insertion_loss_db": {"value": 1.0, "at_hz": 1e9},
            "return_loss_db": {"value": 20.0, "at_hz": 2e9},
        }
    }
    fails, held, unjudged = fields.judge(limits, measures)
    assert fails == [] and len(held) == 1
    assert unjudged == ["P return_loss_db 20.00 at 2 GHz: not judged, fields.json states no limit for it"]


# ---------------------------------------------------------------- a differential pair


def four_ports():
    return {
        "frequencies_hz": [1e9],
        "settings": {"port_ohm": 50.0},
        "nets": ["P", "N"],
        "ports": [{"n": 1, "net": "P"}, {"n": 2, "net": "P"}, {"n": 3, "net": "N"}, {"n": 4, "net": "N"}],
    }


# Port 1 is P's near end, 2 its far end, 3 N's near end, 4 its far end. Column 1 (port 1 driven):
# S11 0.1, S21 0.9, S31 0.02, S41 0.05. Column 3 (port 3 driven): S13 0.02, S23 0.05, S33 0.1, S43 0.9.
PAIR = {1: [[0.1], [0.9], [0.02], [0.05]], 3: [[0.02], [0.05], [0.1], [0.9]]}


def test_sdd11_and_sdd21_of_a_4_port_worked_by_hand():
    """Sdd11 = (S11 - S13 - S31 + S33) / 2 = (0.1 - 0.02 - 0.02 + 0.1) / 2 = 0.08;
    Sdd21 = (S21 - S23 - S41 + S43) / 2 = (0.9 - 0.05 - 0.05 + 0.9) / 2 = 0.85. A sign the other way on
    the coupling terms gives 0.12 and 0.95."""
    sdd11, sdd21 = fields.mixed_mode(PAIR[1], PAIR[3])
    assert sdd11 == [pytest.approx(0.08)]
    assert sdd21 == [pytest.approx(0.85)]


def test_the_differential_measures_of_a_pair():
    """From Sdd11 0.08 and Sdd21 0.85: return loss -20 log10 0.08 = 21.9382 dB; insertion loss
    -20 log10 0.85 = 1.41162 dB; the differential impedance, the symmetric 2-port's formula with a
    reference of 2 x 50 = 100 ohm: 100 sqrt((1.08^2 - 0.85^2) / (0.92^2 - 0.85^2)) = 100 sqrt(0.4439 /
    0.1239) = 100 x 1.892810 = 189.281 ohm."""
    out = fields.group_measures(four_ports(), PAIR)
    assert out["P"]["diff_return_loss_db with N"]["value"] == pytest.approx(21.9382, abs=1e-4)
    assert out["P"]["diff_insertion_loss_db with N"]["value"] == pytest.approx(1.41162, abs=1e-5)
    assert out["P"]["diff_impedance_ohm with N"]["value"] == pytest.approx(189.281, abs=1e-3)


def test_an_uncoupled_pair_of_50_ohm_lines_is_100_ohm():
    """2 matched lossless 50 ohm lines with no coupling: S21 = S43 = e^(-j 1), every other S 0. Then
    Sdd21 = e^(-j 1), Sdd11 = 0, so nothing reflects (its return loss is no measure, |S| = 0) and the
    insertion loss is 0 dB. The impedance: 100 sqrt((1 - t^2) / (1 - t^2)) = 100 ohm."""
    t = cmath.exp(-1j)
    out = fields.group_measures(four_ports(), {1: [[0], [t], [0], [0]], 3: [[0], [0], [0], [t]]})
    assert out["P"]["diff_insertion_loss_db with N"]["value"] == pytest.approx(0.0, abs=1e-9)
    assert out["P"]["diff_return_loss_db with N"]["value"] is None
    assert out["P"]["diff_impedance_ohm with N"]["value"] == pytest.approx(100.0)


def test_a_pair_that_is_not_uniform_has_no_differential_impedance():
    """The differential impedance is a uniform pair's: a net the model names in `no_impedance` makes
    its limit not judged, with the reason."""
    model = four_ports()
    model["no_impedance"] = {"N": "N has 2 widths (0.1, 0.2 mm): the impedance is a uniform line's"}
    out = fields.group_measures(model, PAIR)
    got = out["P"]["diff_impedance_ohm with N"]
    assert got["value"] is None and "N has 2 widths" in got["why"]


def test_a_differential_limit_names_its_pair(tmp_path):
    """A differential limit names the 2 nets: `net` and `pair`, both of the group, not the same."""
    lim = {"measure": "diff_insertion_loss_db", "net": "P", "max": 8.5, "source": "d"}
    with pytest.raises(fields.Refusal, match=r"diff_insertion_loss_db of P names `pair`, the other net"):
        fields.read_spec(write_spec(tmp_path, group([lim])))
    lim["pair"] = "N"
    spec = fields.read_spec(write_spec(tmp_path, group([lim])))
    out = fields.group_measures(four_ports(), PAIR)
    fails, held, _ = fields.judge(spec["groups"][0]["limits"], out)
    assert fails == [] and held == ["P diff_insertion_loss_db with N 1.41 at 1 GHz within ..8.5 (d)"]


# ---------------------------------------------------------------- the loss of a line


def abcd_line_s(z: float, gl: complex, z0: float = 50.0) -> tuple[complex, complex]:
    """S11 and S21 of a line of impedance z and propagation gl (gamma times length) between 2 ports of
    z0: A = D = cosh gl, B = z sinh gl, C = sinh gl / z; the denominator A + B / z0 + C z0 + D."""
    a, b, c = cmath.cosh(gl), z * cmath.sinh(gl), cmath.sinh(gl) / z
    den = a + b / z0 + c * z0 + a
    return (a + b / z0 - c * z0 - a) / den, 2 / den


def test_the_attenuation_of_a_matched_line():
    """A matched line: S11 = 0, S21 = e^-(0.1 + 1j). cosh(gl) = (1 - S11^2 + S21^2) / (2 S21)
    = (e^gl + e^-gl) / 2, so its attenuation is Re(gl) = 0.1 Np."""
    assert fields.attenuation_np([0j], [cmath.exp(-(0.1 + 1j))]) == [pytest.approx(0.1)]


def test_the_attenuation_of_a_mismatched_line_is_its_own():
    """A 60 ohm line between 50 ohm ports, gl = 0.1 + 1j: its S11 is not 0, and the attenuation read
    back from S11 and S21 is still 0.1 Np, where -ln |S21| would add the mismatch."""
    s11, s21 = abcd_line_s(60.0, 0.1 + 1j)
    assert abs(s11) > 0.05
    assert fields.attenuation_np([s11], [s21]) == [pytest.approx(0.1, abs=1e-9)]
    assert -math.log(abs(s21)) > 0.1 + 1e-3


# ---------------------------------------------------------------- copper with thickness or loss


def line_model(**settings):
    board = fields.read_board(LINE / "line.kicad_pcb")
    spec = fields.read_spec(LINE / "fields.json")
    spec["settings"].update(settings)
    return fields.build_model(board, spec["groups"][0], spec)


def test_the_copper_thickness_comes_from_the_stackup():
    """The line fixture's stack-up gives F.Cu and B.Cu 0.035 mm each."""
    board = fields.read_board(LINE / "line.kicad_pcb")
    assert board.copper_t == {"F.Cu": pytest.approx(0.035), "B.Cu": pytest.approx(0.035)}


def test_copper_is_a_sheet_unless_a_setting_says_otherwise():
    """The default is the model as it was: a sheet, a perfect conductor."""
    model = line_model()
    assert model["copper"] == {"kind": "sheet"}
    assert '<Metal Name="net_1">' in fields.OpenEMS.xml(model, driven=1)


def test_thick_copper_stands_on_the_top_layer():
    """`copper` thick: the track on F.Cu, at 0.2 mm, is a body 0.035 mm thick away from the dielectric:
    0.2 to 0.235 mm. The mesh holds a line at 0.235, and openEMS gets a LinPoly of that length."""
    model = line_model(copper="thick")
    (poly,) = model["metals"][0]["polygons"]
    assert poly["z"] == pytest.approx(0.2) and poly["t"] == pytest.approx(0.035)
    assert any(abs(z - 0.235) < 1e-9 for z in model["mesh"]["z"])
    text = fields.OpenEMS.xml(model, driven=1)
    assert '<LinPoly Priority="10" Elevation="0.2" NormDir="2" Length="0.035">' in text


def test_thick_copper_on_an_inner_layer_is_refused():
    """On an inner layer the copper's side is not known from the stack-up: refused, with the layer."""
    board = fields.read_board(LINE / "line.kicad_pcb")
    board.copper_z["In1.Cu"], board.copper_t["In1.Cu"] = 0.1, 0.035
    board.copper_z["F.Cu"] = 0.3
    board.dielectrics = [(0.0, 0.1, 4.5, 0.02), (0.1, 0.3, 4.5, 0.02)]
    board.tracks[0].layer = "In1.Cu"
    board.zones.append(("GND", ("F.Cu",), {"F.Cu": [[(95, 95), (115, 95), (115, 105), (95, 105)]]}))
    spec = fields.read_spec(LINE / "fields.json")
    spec["settings"]["copper"] = "thick"
    with pytest.raises(fields.Refusal, match=r"thick copper is modelled on an outer layer only: In1.Cu"):
        fields.build_model(board, spec["groups"][0], spec)


def test_lossy_copper_is_a_conducting_sheet_of_copper():
    """`copper` lossy: the track and the plane are openEMS conducting sheets of 58e6 S/m (the
    International Annealed Copper Standard, NIST Handbook 100, 1966, 1.2a, p. 2: 58 m/(ohm mm2) at
    20 C) and of their layers' thickness, 0.035 mm = 3.5e-5 m. No perfect metal is left."""
    text = fields.OpenEMS.xml(line_model(copper="lossy"), driven=1)
    assert '<ConductingSheet Name="net_1" Conductivity="58000000" Thickness="3.5e-05">' in text
    assert '<ConductingSheet Name="plane_B.Cu" Conductivity="58000000" Thickness="3.5e-05">' in text
    assert "<Metal" not in text


@pytest.mark.parametrize(
    "settings, says",
    [
        ({"copper": "gold"}, r"setting `copper` is 'gold', none of sheet, thick, lossy"),
        ({"conductivity_s_m": 0}, r"setting `conductivity_s_m` is 0, not a number above 0"),
    ],
)
def test_a_wrong_copper_setting_is_refused(tmp_path, settings, says):
    spec = json.loads((LINE / "fields.json").read_text(encoding="utf-8"))
    spec["settings"] = settings
    with pytest.raises(fields.Refusal, match=says):
        fields.read_spec(write_spec(tmp_path, spec))


# ---------------------------------------------------------------- an antenna: a zone and its resonance

PATCH = ROOT / "tests" / "boards" / "pass-fields-patch"


def patch_model():
    board = fields.read_board(PATCH / "patch.kicad_pcb")
    spec = fields.read_spec(PATCH / "fields.json")
    return fields.build_model(board, spec["groups"][0], spec)


def test_a_zone_of_the_groups_net_is_its_copper():
    """The patch is a zone of ANT on F.Cu, x 100 to 112 and y 94 to 106, at F.Cu's height 0.8 mm; the
    feed is the track from (95, 100) to (101, 100), 1.5 mm wide."""
    (metal,) = patch_model()["metals"]
    rects = [sorted((round(x, 6), round(y, 6)) for x, y in p["points"]) for p in metal["polygons"]]
    assert [(100, 94), (100, 106), (112, 94), (112, 106)] in rects
    assert all(p["z"] == pytest.approx(0.8) for p in metal["polygons"])


def test_a_zones_straight_edges_lie_between_mesh_lines():
    """The largest cell at 8 GHz in 4.5 is 299792458 / (8e9 x 2.1213203) / 20 m = 0.883271 mm, and a
    zone's edge cell d is a third of it, 0.294424 mm. As a track's edges, a straight edge of the zone
    lies a third of d inside the metal and two thirds outside: x 112 - 0.098141 = 111.901859 and
    112 + 0.196283 = 112.196283; y 94 + 0.098141 = 94.098141 and 94 - 0.196283 = 93.803717. The edge
    itself is no line."""
    mesh = patch_model()["mesh"]
    for axis, want in (("x", (111.901859, 112.196283)), ("y", (94.098141, 93.803717))):
        for w in want:
            assert min(abs(v - w) for v in mesh[axis]) < 1e-5, (axis, w)
    assert min(abs(v - 112) for v in mesh["x"]) > 0.05


def test_a_zone_of_the_group_with_a_hole_is_refused():
    """A zone of the group's net with a hole is not modelled: refused, with the net and the layer."""
    board = fields.read_board(PATCH / "patch.kicad_pcb")
    net, layers, shapes = board.zones[0]
    ring = shapes["F.Cu"][0]
    shapes["F.Cu"] = [ring + [None, (105, 99), (107, 99), (107, 101), (105, 101)]]
    spec = fields.read_spec(PATCH / "fields.json")
    with pytest.raises(fields.Refusal, match=r"a zone of ANT on F.Cu has a hole"):
        fields.build_model(board, spec["groups"][0], spec)


def test_a_zone_of_the_group_off_the_pour_is_refused():
    """A corner of the patch with no GND pour under it: the model would put a plane there."""
    board = fields.read_board(PATCH / "patch.kicad_pcb")
    gnd = next(z for z in board.zones if z[0] == "GND")
    gnd[2]["B.Cu"] = [[(85, 86), (110, 86), (110, 114), (85, 114)]]
    spec = fields.read_spec(PATCH / "fields.json")
    with pytest.raises(
        fields.Refusal, match=r"the zone of ANT on F.Cu has no GND pour on B.Cu under \(112, 94\)"
    ):
        fields.build_model(board, spec["groups"][0], spec)


def test_an_antennas_resonance_is_where_its_return_loss_is_most():
    """|S11| 0.9, 0.3 and 0.8 at 5, 6 and 7 GHz: the resonance is 6 GHz, where the least is."""
    model = {
        "frequencies_hz": [5e9, 6e9, 7e9],
        "settings": {"port_ohm": 50.0},
        "nets": ["ANT"],
        "kind": "antenna",
        "ports": [{"n": 1, "net": "ANT"}],
    }
    out = fields.group_measures(model, {1: [[0.9, 0.3j, -0.8]]})
    assert out["ANT"]["resonance_ghz"] == {"value": 6.0, "at_hz": 6e9}


def test_a_line_has_no_resonance():
    """A line's least |S11| is no resonance: only an antenna is measured so."""
    model = {
        "frequencies_hz": [5e9],
        "settings": {"port_ohm": 50.0},
        "nets": ["S"],
        "ports": [{"n": 1, "net": "S"}],
    }
    assert "resonance_ghz" not in fields.group_measures(model, {1: [[0.5]]})["S"]
