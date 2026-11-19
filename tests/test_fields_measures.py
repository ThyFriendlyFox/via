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

CITES = {"qucs-technical-papers": "eq. 11.79, p. 170 (dielectric loss)"}


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


def test_a_differential_limit_is_on_the_groups_first_net(tmp_path):
    """The nets listed N, P and a limit on P with pair N: the measures go under the first net, N, so
    the limit was never judged and the pair's loss was printed as no limit's. Refused, with the order
    to write."""
    lim = {"measure": "diff_insertion_loss_db", "net": "P", "pair": "N", "max": 8.5, "source": "d"}
    with pytest.raises(
        fields.Refusal,
        match=r"diff_insertion_loss_db of P: `net` is the group's first net, N, and `pair` its second",
    ):
        fields.read_spec(write_spec(tmp_path, group([lim], ("N", "P"))))


def test_a_differential_limit_is_of_a_group_of_2_nets(tmp_path):
    """A pair's measures are made for a group of 2 nets alone: on 3 nets the limit could never be
    judged."""
    lim = {"measure": "diff_return_loss_db", "net": "P", "pair": "N", "min": 10, "source": "d"}
    with pytest.raises(
        fields.Refusal, match=r"diff_return_loss_db of P: a pair's measure is of a group of 2 nets"
    ):
        fields.read_spec(write_spec(tmp_path, group([lim], ("P", "N", "Q"))))


def pair_board(n_from, n_to) -> "fields.Board":
    """P straight from (100, 90) to (100, 100), N from n_from to n_to, both 0.2 mm on F.Cu over a GND
    pour on B.Cu, 0.2 mm of 4.5 between."""
    gnd = [(90, 80), (110, 80), (110, 110), (90, 110)]
    return fields.Board(
        path=Path("pair.kicad_pcb"),
        copper_z={"F.Cu": 0.2, "B.Cu": 0.0},
        dielectrics=[(0.0, 0.2, 4.5, 0.02)],
        copper_t={"F.Cu": 0.035, "B.Cu": 0.035},
        tracks=[
            fields.Track("P", "F.Cu", (100, 90), (100, 100), 0.2),
            fields.Track("N", "F.Cu", n_from, n_to, 0.2),
        ],
        zones=[("GND", ("B.Cu",), {"B.Cu": [gnd]})],
    )


def pair_spec(ports=None):
    g = {"name": "pair", "nets": ["P", "N"], "band_ghz": [0.1, 10], "kind": "lines", "limits": []}
    if ports:
        g["ports"] = ports
    return g, {"reference": "GND", "settings": dict(fields.SETTINGS), "groups": [g]}


def test_a_pairs_near_ends_sit_together_when_no_ports_are_named():
    """N slants from (100.5, 90) to (100.4, 100): its free ends sort by x, (100.4, 100) first, so N's
    near end was the one by P's far end, (100, 100): Sdd21, NEXT and FEXT came from the wrong ports.
    N's ports go in the order that puts each by its P partner: 0.5 + 0.4 mm, against 10.0 + 10.0."""
    g, spec = pair_spec()
    model = fields.build_model(pair_board((100.5, 90), (100.4, 100)), g, spec)
    ys = [(p["net"], p["start"][1]) for p in model["ports"]]
    assert ys == [("P", 90), ("P", 100), ("N", 90), ("N", 100)]


def test_a_pairs_named_ports_must_put_near_ends_together():
    """Ports named P near, P far, N far, N near, or P far, P near, N near, N far: refused, with the 4
    ends and the order to name. Names alone do not say which end is near, so the refusal says the 2 nets
    are named in opposite orders; it blamed N when P was the one named far end first (a review's run)."""
    board = pair_board((100.5, 90), (100.5, 100))
    board.pads = {
        "J1.1": (100, 90, "P", 0.1),
        "J2.1": (100, 100, "P", 0.1),
        "J1.2": (100.5, 90, "N", 0.1),
        "J2.2": (100.5, 100, "N", 0.1),
    }
    for ports, first in (
        (["J1.1", "J2.1", "J2.2", "J1.2"], "J2.2"),
        (["J2.1", "J1.1", "J1.2", "J2.2"], "J1.2"),
    ):
        g, spec = pair_spec(ports)
        with pytest.raises(fields.Refusal) as caught:
            fields.build_model(board, g, spec)
        said = str(caught.value)
        assert "P and N are named in opposite orders: " in said
        assert f"N's first port, {first}, lies by P's second" in said
        assert "far end first" not in said
        assert "name P's near end, its far end, then N's by the near end and by the far end" in said
    g, spec = pair_spec(["J1.1", "J2.1", "J1.2", "J2.2"])
    assert [p["start"][1] for p in fields.build_model(board, g, spec)["ports"]] == [90, 100, 90, 100]


WYVERN = ROOT / "examples" / "snapdragon-dev-board" / "v0.2"


@pytest.mark.skipif(not (WYVERN / "wyvern.kicad_pcb").is_file(), reason="the Wyvern example is not here")
def test_the_wyvern_pair_with_n_named_far_end_first_is_refused():
    """The Wyvern USB 3 TX1 pair with ports J1.A3, U2.17, U2.16, J1.A2: the command took it and gave
    0.265 dB of differential insertion loss and the NEXT and FEXT of each other (a review's run; the
    right order gave 0.113 dB). Refused."""
    board = fields.read_board(WYVERN / "wyvern.kicad_pcb")
    g = {
        "name": "usb3-tx1",
        "nets": ["/SS_TX1_P", "/SS_TX1_N"],
        "ports": ["J1.A3", "U2.17", "U2.16", "J1.A2"],
        "band_ghz": [0.1, 10],
        "kind": "lines",
        "limits": [],
    }
    spec = {"reference": "GND", "settings": dict(fields.SETTINGS), "groups": [g]}
    with pytest.raises(
        fields.Refusal,
        match=r"/SS_TX1_P and /SS_TX1_N are named in opposite orders: /SS_TX1_N's first port, "
        r"U2\.16, lies by /SS_TX1_P's second, U2\.17",
    ):
        fields.build_model(board, g, spec)


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


@pytest.mark.parametrize("kind", ["lossy", "thick"])
def test_copper_with_no_thickness_in_the_stackup_is_refused(kind):
    """A stack-up with no thickness on F.Cu: lossy copper wrote a perfect metal there and thick copper
    a sheet, while model.json said lossy or thick. Refused, with the layer."""
    board = fields.read_board(LINE / "line.kicad_pcb")
    board.copper_t["F.Cu"] = 0.0
    spec = fields.read_spec(LINE / "fields.json")
    spec["settings"]["copper"] = kind
    with pytest.raises(fields.Refusal, match=rf"copper {kind} takes each copper layer's thickness: F\.Cu"):
        fields.build_model(board, spec["groups"][0], spec)


def test_lossy_copper_takes_the_planes_thickness_too():
    """The plane on B.Cu is a conducting sheet with lossy copper: no thickness there is refused too."""
    board = fields.read_board(LINE / "line.kicad_pcb")
    del board.copper_t["B.Cu"]
    spec = fields.read_spec(LINE / "fields.json")
    spec["settings"]["copper"] = "lossy"
    with pytest.raises(fields.Refusal, match=r"copper lossy takes each copper layer's thickness: B\.Cu"):
        fields.build_model(board, spec["groups"][0], spec)
    spec["settings"]["copper"] = "thick"  # thick grows the track alone; the plane stays a sheet
    assert fields.build_model(board, spec["groups"][0], spec)["copper"] == {"kind": "thick"}


# ---------------------------------------------------------------- the loss tangent over the band


def eps(terms: dict, f: float) -> complex:
    """eps(f) = eps_inf + sum(delta / (1 + j 2 pi f tau)); its imaginary part, negated, is eps''."""
    w = 2 * math.pi * f
    return terms["eps_inf"] + sum(d / (1 + 1j * w * tau) for d, tau in terms["poles"])


def test_the_loss_tangent_holds_over_the_band():
    """A fixed conductivity Kappa = 2 pi f0 eps0 er tand is right at f0 alone: the 40 mm line read
    1.74 Np/m at 1 GHz and 1.64 at 10 GHz, where Qucs eq. 11.79 (p. 170) gives 0.3458 and 3.4898. The
    Debye terms hold eps'' to er tand = 4.5 x 0.02 = 0.09 within 1 % over 0.1 to 10 GHz, every weight
    above 0, and eps' at f0 = 5 GHz is er, 4.5."""
    terms = fields.debye_terms(4.5, 0.02, 0.1e9, 10e9, 5e9)
    assert all(d > 0 and tau > 0 for d, tau in terms["poles"])
    for i in range(101):
        f = 0.1e9 * 100 ** (i / 100)
        assert -eps(terms, f).imag == pytest.approx(0.09, rel=0.01), f
    assert eps(terms, 5e9).real == pytest.approx(4.5, abs=1e-9)
    assert terms["eps_inf"] >= 1


def test_a_loss_tangent_too_large_for_the_terms_is_refused_with_the_largest_that_models():
    """tan d 0.3 on er 4.5 over 0.1 to 10 GHz leaves eps_inf 0.436, under the vacuum's 1 (a review's
    run): refused, with what to change. eps_inf falls in proportion to tan d, so the largest that
    models is (er - 1) / (er - eps_inf) x tan d."""
    board = fields.read_board(LINE / "line.kicad_pcb")
    board.dielectrics[:] = [(a, b, er, 0.3) for a, b, er, _ in board.dielectrics]
    spec = fields.read_spec(LINE / "fields.json")
    eps_inf = fields.debye_terms(4.5, 0.3, 0.1e9, 10e9, 5e9)["eps_inf"]
    largest = 3.5 / (4.5 - eps_inf) * 0.3
    with pytest.raises(fields.Refusal) as caught:
        fields.build_model(board, spec["groups"][0], spec)
    said = str(caught.value)
    assert f"leave eps_inf {eps_inf:.3f}, under 1" in said
    assert f"the loss tangent is too large to model over 0.1 to 10 GHz: {largest:.3f} at most" in said
    board.dielectrics[:] = [(a, b, er, round(largest, 3) - 0.001) for a, b, er, _ in board.dielectrics]
    fields.build_model(board, spec["groups"][0], spec)


def test_the_dielectric_is_a_debye_material():
    """openEMS gets the line's dielectric as a DebyeMaterial: Epsilon is eps_inf, no conductivity, and
    each term's EpsilonDelta_k and EpsilonRelaxTime_k in seconds."""
    model = line_model()
    text = fields.OpenEMS.xml(model, driven=1)
    terms = fields.debye_terms(4.5, 0.02, 0.1e9, 10e9, 5e9)
    assert '<DebyeMaterial Name="dielectric_1">' in text
    assert f'Epsilon="{fields._n(terms["eps_inf"])}" Kappa="0"' in text
    k = len(terms["poles"])
    d, tau = terms["poles"][-1]
    assert f'EpsilonDelta_{k}="{fields._n(d)}" EpsilonRelaxTime_{k}="{fields._n(tau)}"' in text
    assert 'Kappa="0.02' not in text


def test_left_out_gives_the_known_error_of_a_debye_dielectric():
    """The report's left_out line on a lossy dielectric gave eps' and the Debye terms, and no word that
    the loss reads high or that the terms move eeff (a review): the 40 mm line read 1.05 to 1.10 times
    Qucs eq. 11.79 from 2 to 20 GHz and 0.95 to 2.1 times under 2 GHz, eeff 3.3954 against 3.3742 with
    the plain material at 5.05 GHz, and the patch fixture 5.80 GHz against 5.74."""
    (line,) = [x for x in line_model()["left_out"] if "Debye terms" in x]
    assert "the run reads the dielectric's loss high" in line
    assert "1.05 to 1.10 times Qucs Technical Papers (2014) eq. 11.79 from 2 to 20 GHz" in line
    assert "0.95 to 2.1 times under 2 GHz" in line
    assert "eeff 0.6 % over the plain material's at 5.05 GHz" in line
    assert "5.80 GHz against 5.74" in line


def test_a_lossless_dielectric_is_a_plain_material():
    """A loss tangent of 0 stated in the stack-up: a plain material of er, no Debye term."""
    model = line_model()
    model["dielectrics"][0]["tand"] = 0.0
    text = fields.OpenEMS.xml(model, driven=1)
    assert '<Material Name="dielectric_1"><Property Epsilon="4.5" Kappa="0"/>' in text
    assert "DebyeMaterial" not in text


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
    """|S11| 0.9, 0.3 and 0.8 at 5, 6 and 7 GHz: the resonance is 6 GHz, where the least is, 20 log10
    (0.8 / 0.3) = 8.5 dB under the most on its right."""
    model = {
        "frequencies_hz": [5e9, 6e9, 7e9],
        "settings": {"port_ohm": 50.0},
        "nets": ["ANT"],
        "kind": "antenna",
        "ports": [{"n": 1, "net": "ANT"}],
    }
    out = fields.group_measures(model, {1: [[0.9, 0.3j, -0.8]]})
    assert out["ANT"]["resonance_ghz"] == {"value": 6.0, "at_hz": 6e9}


def antenna(freqs_ghz):
    return {
        "frequencies_hz": [f * 1e9 for f in freqs_ghz],
        "settings": {"port_ohm": 50.0},
        "nets": ["ANT"],
        "kind": "antenna",
        "ports": [{"n": 1, "net": "ANT"}],
    }


@pytest.mark.parametrize("s11", [[0.3, 0.5, 0.8, 0.9], [0.9, 0.8, 0.5, 0.3]])
def test_a_least_at_the_bands_edge_is_no_resonance(s11):
    """The patch fixture run over 6 to 8 GHz read its resonance as 6.00 GHz, the band's first
    frequency, and held a limit of 6.0 to 6.5 GHz; the patch resonates at 5.74 GHz (its own run over
    4 to 8 GHz). The least |S11| on the first or the last frequency is no resonance."""
    got = fields.group_measures(antenna([6, 6.5, 7, 7.5]), {1: [s11]})["ANT"]["resonance_ghz"]
    assert got["value"] is None
    assert "the least |S11| is at the band's edge" in got["why"]
    assert "the resonance is not in the band" in got["why"]


def test_a_shallow_dip_is_no_resonance():
    """|S11| 0.9, 0.8, 0.75, 0.85: the least, 0.75, lies 20 log10(0.85 / 0.75) = 1.09 dB under the most
    on its right, under the 3 dB (half the power) a resonance takes."""
    got = fields.group_measures(antenna([5, 6, 7, 8]), {1: [[0.9, 0.8, 0.75, 0.85]]})["ANT"]
    assert got["resonance_ghz"]["value"] is None
    assert "1.09 dB" in got["resonance_ghz"]["why"]


def test_a_line_has_no_resonance():
    """A line's least |S11| is no resonance: only an antenna is measured so."""
    model = {
        "frequencies_hz": [5e9],
        "settings": {"port_ohm": 50.0},
        "nets": ["S"],
        "ports": [{"n": 1, "net": "S"}],
    }
    assert "resonance_ghz" not in fields.group_measures(model, {1: [[0.5]]})["S"]
