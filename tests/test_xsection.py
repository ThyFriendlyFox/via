"""The cross-section solver (tools/xsection.py) against closed forms from 2 publications.

Microstrip: Qucs Technical Papers (S. Jahn, M. Margraf, V. Habchi, R. Jacob; PDF of 2014-10-18,
qucs.sourceforge.net/docs/technical/technical.pdf, SHA256 4136c97c...c300), section 11.1, the equations of
E. Hammerstad and O. Jensen: (11.4) to (11.6) on page 162, (11.15) to (11.18) on page 164, and (11.24) on
page 165 with t = 0 (W_r = W). The paper gives the impedance within 0.03 % and eps_eff within 0.2 %.

Stripline and the edge-coupled stripline pair: G. L. Matthaei, L. Young, E. M. T. Jones, "Design of
Microwave Filters, Impedance-Matching Networks, and Coupling Structures", Volume 1, Stanford Research
Institute, 1963 (DTIC AD0402852, archive.org/download/DTIC_AD0402852, SHA256 b6b32755...3a2c), section
5.05, S. B. Cohn's exact zero-thickness forms: (5.05-1) to (5.05-3) on page 170, (5.05-4) to (5.05-6) on
page 172. (5.05-2) is printed with (w + s)/2 in its second tanh; (5.05-5) beside it has (w + s)/b, and
only that form has no unit, so the test reads (w + s)/b in both. The book writes 30 pi ohms, which is
Z_F0 / 4 with its Z_F0 = 120 pi; the test compares Z / Z_F0, so the book's 120 pi does not enter.

K(k) = pi / (2 M(1, k')), M the arithmetic-geometric mean: DLMF 19.8.5 (dlmf.nist.gov/19.8).
The solver is held to 1 % of each closed form.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import xsection  # noqa: E402

TOL = 0.01


def agm(a: float, b: float) -> float:
    while abs(a - b) > 1e-15 * a:
        a, b = (a + b) / 2, math.sqrt(a * b)
    return a


def ellipk(k: float) -> float:
    """DLMF 19.8.5."""
    return math.pi / (2 * agm(1.0, math.sqrt(1 - k * k)))


def hammerstad_jensen(u: float, er: float) -> tuple[float, float]:
    """(Z / Z_F0, eps_eff) of a zero-thickness microstrip, W/h = u: Qucs (11.4), (11.6), (11.15) to
    (11.18), (11.24)."""
    fu = 6 + (2 * math.pi - 6) * math.exp(-((30.666 / u) ** 0.7528))
    zl1 = math.log(fu / u + math.sqrt(1 + (2 / u) ** 2)) / (2 * math.pi)
    a = 1 + math.log((u**4 + (u / 52) ** 2) / (u**4 + 0.432)) / 49 + math.log(1 + (u / 18.1) ** 3) / 18.7
    b = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
    eps = (er + 1) / 2 + (er - 1) / 2 * (1 + 10 / u) ** (-a * b)
    return zl1 / math.sqrt(eps), eps


def cohn(k: float) -> float:
    """Z / Z_F0 in air for a modulus k: (5.05-1) and (5.05-4), 30 pi / Z_F0 = 1/4."""
    return ellipk(math.sqrt(1 - k * k)) / ellipk(k) / 4


def test_closed_forms_as_worked_by_hand():
    """The transcriptions give the numbers worked out by hand for the cases below.

    u = 1, er = 4.5: fu = 6 + 0.2832 exp(-30.666^0.7528) = 6.0000005; Z_L1/Z_F0 = ln(6 + sqrt(5)) / 2 pi
    = 0.33558; a = 1 + ln((1 + 1/2704)/1.432)/49 + ln(1 + 1/5929.7)/18.7 = 0.99269; b = 0.564 (3.6/7.5)^0.053
    = 0.54248; eps_eff = 2.75 + 1.75 x 11^(-0.53852) = 3.23110; Z = 0.33558 / sqrt(3.23110) = 0.18669 Z_F0.
    Stripline, w/b = 0.5, s infinite: k = tanh(pi/4) = 0.65579, Z = K(k')/K(k)/4 = 0.26659 Z_F0.
    Pair, w/b = 0.5, s/b = 0.25: k_o = tanh(pi/4)/tanh(3 pi/8) = 0.79312, Z_odd = 0.22170 Z_F0;
    k_e = tanh(pi/4) tanh(3 pi/8) = 0.54224, Z_even = 0.30464 Z_F0.
    """
    z, eps = hammerstad_jensen(1.0, 4.5)
    assert eps == pytest.approx(3.23110, abs=1e-5)
    assert z == pytest.approx(0.18669, abs=1e-5)
    assert cohn(math.tanh(math.pi / 4)) == pytest.approx(0.26659, abs=1e-5)
    t1, t2 = math.tanh(math.pi / 4), math.tanh(3 * math.pi / 8)
    assert cohn(t1 / t2) == pytest.approx(0.22170, abs=1e-5)
    assert cohn(t1 * t2) == pytest.approx(0.30464, abs=1e-5)


@pytest.mark.parametrize("u", [0.5, 1.0, 2.0])
def test_microstrip_against_hammerstad_jensen(u):
    """h = 0.2 mm of er 4.5 under a zero-thickness strip u x 0.2 mm wide, air above."""
    h = 0.2
    line = xsection.solve(xsection.Section(slabs=[(h, 4.5)], top_plane=False, y=h, t=0.0, widths=[u * h]))
    z, eps = hammerstad_jensen(u, 4.5)
    assert line.eps_eff == pytest.approx(eps, rel=TOL)
    assert line.z0 / xsection.Z_F0 == pytest.approx(z, rel=TOL)


@pytest.mark.parametrize("wb", [0.5, 1.0])
def test_stripline_against_cohn(wb):
    """A zero-thickness strip midway between planes b = 0.4 mm apart, er 1: (5.05-4) as s grows without
    end, k = tanh(pi w / 2b). The solver's er 4.5 run gives the same Z times 1/sqrt(4.5)."""
    b = 0.4
    k = math.tanh(math.pi / 2 * wb)
    for er in (1.0, 4.5):
        sec = xsection.Section(
            slabs=[(b / 2, er), (b / 2, er)], top_plane=True, y=b / 2, t=0.0, widths=[wb * b]
        )
        line = xsection.solve(sec)
        assert line.z0 / xsection.Z_F0 == pytest.approx(cohn(k) / math.sqrt(er), rel=TOL)
        assert line.eps_eff == pytest.approx(er, rel=1e-6)


def test_edge_coupled_stripline_against_cohn():
    """2 strips w = 0.5 b, gap s = 0.25 b, midway between planes b = 0.4 mm apart, er 1: Z_odd from
    (5.05-4) to (5.05-6), Z_even from (5.05-1) to (5.05-3), and Z_diff = 2 Z_odd."""
    b, w, s = 0.4, 0.2, 0.1
    sec = xsection.Section(
        slabs=[(b / 2, 1.0), (b / 2, 1.0)], top_plane=True, y=b / 2, t=0.0, widths=[w, w], gap=s
    )
    pair = xsection.solve(sec)
    t1, t2 = math.tanh(math.pi / 2 * w / b), math.tanh(math.pi / 2 * (w + s) / b)
    assert pair.z_odd / xsection.Z_F0 == pytest.approx(cohn(t1 / t2), rel=TOL)
    assert pair.z_even / xsection.Z_F0 == pytest.approx(cohn(t1 * t2), rel=TOL)
    assert pair.z_diff == pytest.approx(2 * pair.z_odd)


def test_width_for_a_target_comes_back_to_the_target():
    """width_for() finds the width whose solved impedance is the target, within its 0.2 % stop."""
    sec = xsection.Section(slabs=[(0.2104, 4.5)], top_plane=False, y=0.2104, t=0.035, widths=[0.3])
    w = xsection.width_for(sec, 50.0)
    line = xsection.solve(xsection.replace_widths(sec, w))
    assert line.z0 == pytest.approx(50.0, rel=0.002)


def test_z_f0_is_codata_2022():
    """376.730313412 ohm: NIST, CODATA 2022, 'characteristic impedance of vacuum'
    (physics.nist.gov/cgi-bin/cuu/Value?z0), held in rules/interfaces/constants.json."""
    assert xsection.Z_F0 == 376.730313412
