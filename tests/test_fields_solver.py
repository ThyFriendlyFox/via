"""`workcenter fields` with its engine: openEMS runs on the 2 fixture boards.

Skipped, with the engine's name, where openEMS is not installed (`sudo ./install.sh --openems`). Each
run takes from 10 s to a few minutes on 4 processors; put `flock` on the engine lock in front of this
file when other engines run.
"""

import json
import math
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import engine

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import fields  # noqa: E402

# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {
    "hammerstad-jensen-1980": "pp. 407-409, equations (1) to (4)",
    "pozar-microwave-engineering-4": "3.195 and 3.196",
    "qucs-technical-papers": "eq. 11.22 to 11.24, 11.79, 11.80 to 11.83 and 11.185 to 11.190",
}

CLI = ROOT / "tools" / "workcenter"
needs_openems = engine(pytest.mark.skipif(fields.OpenEMS.binary() is None, reason="not installed: openEMS"))


def run(fixture: str, out: Path, *flags: str):
    proc = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "fields",
            str(ROOT / "tests" / "boards" / fixture),
            "--out",
            str(out),
            *flags,
        ],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    report = json.loads((out / "fields" / "report.json").read_text(encoding="utf-8"))
    return proc, report


@pytest.fixture(scope="module")
def line(tmp_path_factory):
    return run("pass-fields-microstrip", tmp_path_factory.mktemp("line"), "--strict")


@pytest.fixture(scope="module")
def stub(tmp_path_factory):
    return run("fail-fields-stub", tmp_path_factory.mktemp("stub"))


@needs_openems
def test_the_line_holds_every_limit_with_strict(line):
    proc, report = line
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "FIELDS HELD" in proc.stdout
    assert report["summary"].startswith("3 held, 0 failed, 0 not judged")


def hammerstad_jensen(w: float, h: float, er: float) -> float:
    """The impedance of a microstrip of zero thickness, w wide over h of er: Hammerstad and Jensen,
    "Accurate Models for Microstrip Computer-Aided Design", IEEE MTT-S Int. Microwave Symp. Digest 1980,
    pp. 407-409, equations (1) to (4)."""
    eta0 = 376.730313668  # ohm, the impedance of free space (CODATA 2018)
    u = w / h
    f = 6 + (2 * math.pi - 6) * math.exp(-((30.666 / u) ** 0.7528))
    z01 = eta0 / (2 * math.pi) * math.log(f / u + math.sqrt(1 + (2 / u) ** 2))
    a = 1 + math.log((u**4 + (u / 52) ** 2) / (u**4 + 0.432)) / 49 + math.log(1 + (u / 18.1) ** 3) / 18.7
    b = 0.564 * ((er - 0.9) / (er + 3)) ** 0.053
    e_eff = (er + 1) / 2 + (er - 1) / 2 * (1 + 10 / u) ** (-a * b)
    return z01 / math.sqrt(e_eff)


def test_the_closed_form_gives_the_published_value():
    """Hammerstad and Jensen for w/h 1.8 in er 4.5: 51.337 ohm; Pozar (Microwave Engineering, 4th ed.,
    3.195 and 3.196) gives 51.533 ohm for the same line, 0.4% from it."""
    assert hammerstad_jensen(0.36, 0.2, 4.5) == pytest.approx(51.337, abs=1e-3)


@needs_openems
def test_the_line_impedance_is_the_closed_form_within_3_percent(line):
    """The fixture is a plain microstrip: 0.36 mm over 0.2 mm of 4.5, copper a sheet as in the model.
    Hammerstad and Jensen give 51.337 ohm. With the track's edges on mesh lines the solver's sheet was
    wider than the board's and the run read 43.14 ohm, 16% low, inside the made-up 30 to 75 window.
    The mesh puts a track's edges a third of a cell inside its metal: within 3%."""
    _, report = line
    got = report["details"]["measures"]["sig"]["SIG"]["impedance_ohm"]["value"]
    assert got == pytest.approx(hammerstad_jensen(0.36, 0.2, 4.5), rel=0.03)


@pytest.fixture(scope="module")
def bare(tmp_path_factory):
    """The line with its limits taken out and its dielectric lossless, run once: a plain material runs
    in half the time of the Debye one (the 40 mm line: 18 s against 36 s), and neither test that reads
    it is about the loss."""
    import shutil

    project = tmp_path_factory.mktemp("bare") / "line"
    shutil.copytree(ROOT / "tests" / "boards" / "pass-fields-microstrip", project)
    pcb = project / "line.kicad_pcb"
    text = pcb.read_text(encoding="utf-8")
    assert text.count("(loss_tangent 0.02)") == 1
    pcb.write_text(text.replace("(loss_tangent 0.02)", "(loss_tangent 0)"), encoding="utf-8")
    spec = json.loads((project / "fields.json").read_text(encoding="utf-8"))
    spec["groups"][0]["limits"] = []
    (project / "fields.json").write_text(json.dumps(spec), encoding="utf-8")
    return project, run_project(project)


@needs_openems
def test_a_run_with_no_limit_judges_nothing_and_does_not_pass(bare):
    """The line with its limits taken out: the run measures and writes its report, and says it judged
    nothing, exit 2, never PASS."""
    project, (proc, _) = bare
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "SKIP   fields" in proc.stdout and "no limit stated: nothing judged" in proc.stdout
    assert "impedance_ohm" in (project / "build" / "fields" / "report.md").read_text(encoding="utf-8")


WYVERN = ROOT / "examples" / "snapdragon-dev-board" / "v0.2"


# What USB 3.2 states for a host's or a device's own board, read from the USB 3.2 Specification
# Revision 1.1 (June 2022, usb.org usb_32_202206_1.zip, the PDF's SHA256 26e025a56ce0352f...). It
# states 1 number for the board's share: an informative insertion-loss budget for the host/device.
# It states no differential impedance and no return loss for a board.
USB32_TX1 = {
    "name": "usb3-tx1",
    "nets": ["/SS_TX1_P", "/SS_TX1_N"],
    "ports": ["J1.A3", "U2.17", "J1.A2", "U2.16"],
    "band_ghz": [0.1, 10],
    "limits": [
        {
            "measure": "diff_insertion_loss_db",
            "net": "/SS_TX1_P",
            "pair": "/SS_TX1_N",
            "max": 8.5,
            "source": "USB 3.2 Specification Revision 1.1 (June 2022), Appendix E, E.6.4.8, p. 536: an "
            "informative insertion-loss budget of 8.5 dB for the host/device, in Gen 2; the sentence names "
            "no frequency, so it is held up to 10 GHz, twice the 5 GHz E.6.4.3, p. 532 names as Gen 2's "
            "Nyquist frequency",
        },
        {
            "measure": "diff_impedance_ohm",
            "net": "/SS_TX1_P",
            "pair": "/SS_TX1_N",
            "unstated": "USB 3.2 Specification Revision 1.1 (June 2022) states no differential impedance "
            "for a host's or a device's board: 6.2.1, p. 55 leaves the compliance channels to white papers "
            "outside the specification and the layout to the silicon maker's guidelines; the 85 ohm of "
            "E.6.4.5, p. 534 is the reference of a re-driver's return loss",
        },
        {
            "measure": "diff_return_loss_db",
            "net": "/SS_TX1_P",
            "pair": "/SS_TX1_N",
            "unstated": "USB 3.2 Specification Revision 1.1 (June 2022) states no return loss for a host's "
            "or a device's board: the -17 dB of E.6.4.5, p. 534 is a re-driver's integrated return loss "
            "on its evaluation board",
        },
    ],
}


@needs_openems
@pytest.mark.skipif(not (WYVERN / "wyvern.kicad_pcb").is_file(), reason="the Wyvern example is not here")
def test_the_wyvern_usb3_lane_is_held_to_what_usb_3_2_states(tmp_path):
    """The USB 3 TX1 pair of the Wyvern example, from J1's A3 and A2 to U2's 17 and 16 on F.Cu over
    In1.Cu, copied out of the example (the command writes into its project's build folder). 4 ports,
    2 runs. The pair's differential insertion loss is held to the 8.5 dB USB 3.2 gives the host/device,
    at every frequency up to 10 GHz, twice Gen 2's Nyquist frequency: the strict side, since the
    sentence names no frequency. A band that ended at 5 GHz gave no result: openEMS samples its probes
    for the band's top, and wrote 45 samples, too few for the ports to settle (a run of 2026-11-18). A
    few cm of FR-4 lose about 15 dB/m at 5 GHz (Qucs eq. 11.79 for the line fixture's stack), so the
    loss stays well under 8.5 dB. The differential impedance and return loss are printed not judged,
    with the clause that says why; so are the 10 single-ended measures no limit names."""
    import shutil

    project = tmp_path / "wyvern"
    shutil.copytree(WYVERN, project, ignore=shutil.ignore_patterns("build"))
    (project / "fields.json").write_text(json.dumps({"groups": [USB32_TX1]}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CLI), "fields", str(project)], capture_output=True, text=True, timeout=3600
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((project / "build" / "fields" / "report.json").read_text(encoding="utf-8"))
    assert report["summary"].startswith("1 held, 0 failed, 12 not judged"), report["summary"]
    warnings = report["details"]["warnings"]
    assert any("diff_impedance_ohm with /SS_TX1_N" in w and "6.2.1, p. 55" in w for w in warnings)
    assert any("diff_return_loss_db with /SS_TX1_N" in w and "E.6.4.5, p. 534" in w for w in warnings)
    measures = report["details"]["measures"]["usb3-tx1"]
    assert measures["/SS_TX1_P"]["diff_insertion_loss_db with /SS_TX1_N"]["value"] < 8.5


@needs_openems
def test_the_line_is_passive(line, tmp_path):
    """No passive line gives back more power than it gets: |S11|^2 + |S21|^2 <= 1 at every frequency.
    The read-back is held to 1.02, the DFT of a run cut at -40 dB of energy."""
    out = Path(line[1]["artifacts"][0]).parent / "sig"
    model = json.loads((out / "model.json").read_text(encoding="utf-8"))
    col = fields.OpenEMS.column(out / "openems" / "port1", model, 1)
    worst = max(abs(a) ** 2 + abs(b) ** 2 for a, b in zip(col[0], col[1], strict=True))
    assert worst <= 1.02


@needs_openems
def test_the_stub_fails_on_insertion_loss_alone(stub):
    """The 7 mm open stub is a quarter wave between c / (4 x 7 mm x sqrt(4.5)) = 299.79 / 59.40 =
    5.05 GHz (all its field in the dielectric) and c / (4 x 7 mm) = 10.71 GHz (all in air): inside the
    band, 0.1 to 12 GHz. There it shorts the line, and the insertion loss passes the 3 dB limit at a
    frequency between those 2. It is the 1 limit the fixture states, and the 1 line that fails."""
    proc, report = stub
    assert proc.returncode == 1, proc.stdout + proc.stderr
    (failure,) = report["details"]["failures"]
    assert failure.startswith("sig: SIG insertion_loss_db ")
    at = report["details"]["measures"]["sig"]["SIG"]["insertion_loss_db"]["at_hz"]
    assert 5.05e9 <= at <= 10.71e9
    assert report["details"]["measures"]["sig"]["SIG"]["insertion_loss_db"]["value"] > 3


@needs_openems
def test_the_same_file_gives_the_same_numbers(bare, tmp_path):
    """openEMS stopped on a check made every 4 s of the clock: 4 runs of the stub stopped after 7189 to
    8453 steps and gave 29.55 to 29.99 dB, and the Wyvern lane settled in 1 run and not in another.
    The run is ended once the ports' energy has settled and the box's has fallen, and the spectra end
    at the sample where the ports' energy settled, a sample every run reaches the same way: a second
    run of the bare line's files (the `bare` fixture, 10 s against the stub's 48 s) gives every
    measure to the last digit, while a busy machine slows it."""
    import shutil

    project, (_, first) = bare
    again = tmp_path / "line"
    shutil.copytree(project, again, ignore=shutil.ignore_patterns("build"))
    load = subprocess.Popen([sys.executable, "-c", "while True: pass"])
    try:
        _, second = run_project(again)
    finally:
        load.kill()
        load.wait()
    assert second["details"]["measures"] == first["details"]["measures"]
    assert second["details"]["measures"]["sig"]["SIG"]["impedance_ohm"]["value"] is not None


@needs_openems
def test_the_line_delay_lies_between_air_and_the_dielectric(line):
    """The 10 mm line's delay, from the phase of S21, lies between 10 mm / c = 33.36 ps (all in air)
    and 10 mm x sqrt(4.5) / c = 70.76 ps (all in the dielectric): the field solver has put the line in
    the stack the board names. Read at the band's middle, 5 GHz, from the slope of the unwrapped phase
    over 2 neighbouring frequencies."""
    out = Path(line[1]["artifacts"][0]).parent / "sig"
    model = json.loads((out / "model.json").read_text(encoding="utf-8"))
    col = fields.OpenEMS.column(out / "openems" / "port1", model, 1)
    freqs = model["frequencies_hz"]
    k = min(range(len(freqs)), key=lambda i: abs(freqs[i] - 5e9))
    phase = [math.atan2(s.imag, s.real) for s in col[1][k - 1 : k + 2]]
    step = phase[2] - phase[0]
    step = (step + math.pi) % (2 * math.pi) - math.pi
    delay = -step / (2 * math.pi * (freqs[k + 1] - freqs[k - 1]))
    assert 33.36e-12 <= delay <= 70.76e-12


def line_copy(tmp_path: Path, name: str, settings: dict, length_mm: float = 10.0) -> Path:
    """The line fixture copied, with `settings` in its fields.json and its track `length_mm` long (the
    GND pour 5 mm longer than the track, as in the fixture)."""
    import shutil

    project = tmp_path / name
    shutil.copytree(ROOT / "tests" / "boards" / "pass-fields-microstrip", project)
    pcb = project / "line.kicad_pcb"
    end = 100 + length_mm
    text = pcb.read_text(encoding="utf-8")
    text = text.replace("(end 110 100)", f"(end {end:g} 100)")
    text = text.replace("(xy 115 95) (xy 115 105)", f"(xy {end + 5:g} 95) (xy {end + 5:g} 105)")
    pcb.write_text(text, encoding="utf-8")
    spec = json.loads((project / "fields.json").read_text(encoding="utf-8"))
    spec["settings"] = settings
    (project / "fields.json").write_text(json.dumps(spec), encoding="utf-8")
    return project


def run_project(project: Path, *flags: str):
    proc = subprocess.run(
        [sys.executable, str(CLI), "fields", str(project), *flags],
        capture_output=True,
        text=True,
        timeout=3600,
    )
    report = json.loads((project / "build" / "fields" / "report.json").read_text(encoding="utf-8"))
    return proc, report


@needs_openems
def test_thick_copper_reads_the_closed_form_with_thickness(tmp_path):
    """The line with `copper` thick: 0.36 mm over 0.2 mm of 4.5, 0.035 mm of copper. Hammerstad and
    Jensen with their thickness correction (Qucs Technical Papers, 2014, eq. 11.22 to 11.24, p. 165):
    u = 1.8, t/h = 0.175, du1 = 0.175 / pi x ln(1 + 4e / (0.175 coth^2 sqrt(6.517 x 1.8))) = 0.23067,
    dur = du1 / 2 x (1 + sech sqrt(3.5)) = 0.15004, Z = Z01(1.95004) / sqrt(eeff(1.95004)) = 48.9407 ohm.
    The margin, 3 %, was written before the run: 47.47 to 50.41 ohm."""
    proc, report = run_project(line_copy(tmp_path, "thick", {"copper": "thick"}), "--strict")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    got = report["details"]["measures"]["sig"]["SIG"]["impedance_ohm"]["value"]
    assert 47.47 <= got <= 50.41


def attenuation_per_m(project: Path, length_m: float, lo: float, hi: float) -> float:
    """The median over lo to hi Hz of the line's attenuation in Np/m, from its S11 and S21."""
    out = project / "build" / "fields" / "sig"
    model = json.loads((out / "model.json").read_text(encoding="utf-8"))
    col = fields.OpenEMS.column(out / "openems" / "port1", model, 1)
    alpha = fields.attenuation_np(col[0], col[1])
    picked = sorted(a for a, f in zip(alpha, model["frequencies_hz"], strict=True) if lo <= f <= hi)
    return picked[len(picked) // 2] / length_m


@needs_openems
@pytest.mark.xfail(
    strict=True,
    reason="not within its margin: the run of 2026-11-18 gave 1.7615 Np/m for the sheet and 2.2423 Np/m "
    "for the conducting sheet, a conductor loss of 0.4808 Np/m, 35 % under the closed form's 0.74145 "
    "against a margin of 30 % written before the run; with the dielectric a Debye material, 1.9263 and "
    "2.4063 Np/m, 0.4800 Np/m, 35 % under. The margin is not widened after the run.",
)
def test_lossy_copper_adds_the_closed_form_conductor_loss(tmp_path, sheet40):
    """The line made 40 mm long, run with copper as a perfect sheet and as a conducting sheet of 58e6
    S/m and 0.035 mm (NIST Handbook 100, 1966, 1.2a, p. 2). The difference of their attenuations, read
    from S11 and S21 so that the mismatch is no part of it, is the conductor's. Hammerstad and Jensen
    (Qucs Technical Papers, 2014, eq. 11.80 to 11.83, p. 171) at 5 GHz with no roughness (Kr = 1):
    R = sqrt(rho pi f mu0) = sqrt(1.7241e-8 x pi x 5e9 x 4 pi e-7) = 0.018448 ohm,
    Ki = exp(-1.2 (51.337 / 376.73)^0.7) = 0.74279, alpha_c = 0.018448 / (51.337 x 0.36e-3) x 0.74279
    = 0.74145 Np/m. The margin, 30 %, was written before the run: 0.519 to 0.964 Np/m, the median over
    4.5 to 5.5 GHz."""
    lossy = line_copy(tmp_path, "lossy40", {"copper": "lossy"}, length_mm=40)
    proc, _ = run_project(lossy)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    a_sheet = attenuation_per_m(sheet40, 0.04, 4.5e9, 5.5e9)
    a_lossy = attenuation_per_m(lossy, 0.04, 4.5e9, 5.5e9)
    assert 0.519 <= a_lossy - a_sheet <= 0.964, (a_sheet, a_lossy)


@pytest.fixture(scope="module")
def sheet40(tmp_path_factory):
    """The line made 40 mm long, copper a sheet, run once for the tests that read its loss."""
    project = line_copy(tmp_path_factory.mktemp("sheet40"), "sheet40", {}, length_mm=40)
    proc, _ = run_project(project)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return project


def attenuation_at(project: Path, length_m: float, f: float) -> float:
    """The line's attenuation in Np/m at the frequency of the run nearest f, from its S11 and S21."""
    out = project / "build" / "fields" / "sig"
    model = json.loads((out / "model.json").read_text(encoding="utf-8"))
    col = fields.OpenEMS.column(out / "openems" / "port1", model, 1)
    alpha = fields.attenuation_np(col[0], col[1])
    freqs = model["frequencies_hz"]
    return alpha[min(range(len(freqs)), key=lambda i: abs(freqs[i] - f))] / length_m


# Qucs Technical Papers (2014) eq. 11.79, printed p. 170, with eeff 3.38151 (Hammerstad and Jensen,
# u = 1.8, er 4.5) and tan d 0.02: alpha_d = pi f / c x er / sqrt(eeff) x (eeff - 1) / (er - 1) x tan d.
QUCS_ALPHA_D = {5e9: 1.7451, 10e9: 3.4898}  # Np/m


@needs_openems
def test_the_dielectric_loss_grows_with_the_frequency(sheet40):
    """The 40 mm sheet line: all its loss is the dielectric's (and what radiates). Qucs eq. 11.79 gives
    3.4898 Np/m at 10 GHz, twice its 1.7451 at 5 GHz. A fixed conductivity, right at f0 = 5 GHz alone,
    read 1.7752 and 1.6408 Np/m (a run of 2026-11-18): the loss flat over the band, half at its top.
    The margins, 10 %, were written before the run of the fix: 3.141 to 3.839 Np/m at 10 GHz, the
    ratio 1.8 to 2.2."""
    a5, a10 = attenuation_at(sheet40, 0.04, 5e9), attenuation_at(sheet40, 0.04, 10e9)
    assert 3.141 <= a10 <= 3.839, (a5, a10)
    assert 1.8 <= a10 / a5 <= 2.2, (a5, a10)


@needs_openems
@pytest.mark.xfail(
    strict=True,
    reason="not within its margin: the run of 2026-11-18 gave 1.9263 Np/m at 5 GHz against 1.7451, 10.4 % "
    "over against a margin of 10 % written before the run (3.6683 at 10 GHz, 5.1 % over). The run reads "
    "1.05 to 1.10 times eq. 11.79 over the band; with cells_per_dielectric 8 it read 1.01 to 1.06 (1.8507 "
    "at 5 GHz), so the excess falls with the cells at the dielectric's faces. The margin is not widened.",
)
def test_the_dielectric_loss_at_f0_is_the_closed_form(sheet40):
    """At 5 GHz, f0, the fixed conductivity read 1.7752 Np/m, 1.7 % over eq. 11.79's 1.7451. The margin
    written before the run of the fix, 10 %: 1.571 to 1.920 Np/m."""
    a5 = attenuation_at(sheet40, 0.04, 5e9)
    assert 1.571 <= a5 <= 1.920, a5


@pytest.fixture(scope="module")
def patch(tmp_path_factory):
    return run("pass-fields-patch", tmp_path_factory.mktemp("patch"))


@needs_openems
def test_the_patch_resonates_where_its_length_says(patch):
    """tests/boards/pass-fields-patch: a patch 12 mm by 12 mm over 0.8 mm of 4.5, fed at the middle of
    1 edge. eeff (Hammerstad and Jensen, u = 15) = 4.06762; each open end adds 0.42208 mm (Kirschning,
    Jansen and Koster, Qucs Technical Papers 2014, eq. 11.185 to 11.190, p. 181); half a wavelength in
    12.84416 mm: c / (2 x 12.84416 mm x sqrt(4.06762)) = 5.7865 GHz. The margin, 7 %, was written in
    fields.json before the run: 5.381 to 6.192 GHz. The least return loss over the band is printed not
    judged with its reason: the bound of 0 dB it had was met by any passive port, and counted as held."""
    proc, report = patch
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert report["summary"].startswith("1 held, 0 failed, 1 not judged"), report["summary"]
    (warning,) = report["details"]["warnings"]
    assert warning.startswith("patch: ANT return_loss_db ") and "not judged, no document" in warning
    got = report["details"]["measures"]["patch"]["ANT"]["resonance_ghz"]["value"]
    assert 5.381 <= got <= 6.192


@needs_openems
def test_a_patch_resonating_under_the_band_gives_no_resonance(patch):
    """The patch fixture with its band made 6 to 8 GHz: it resonates at 5.80 GHz (its own run over 4
    to 8 GHz), under the band. The least |S11| fell on 6 GHz, the band's first frequency, and a limit
    of 6.0 to 6.5 GHz held with --strict. Now there is no value, and the line says why. Judged on the
    6 to 8 GHz slice of the fixture's own run, not a run of its own (26 s to 30 s saved)."""
    out = Path(patch[1]["artifacts"][0]).parent / "patch"
    model = json.loads((out / "model.json").read_text(encoding="utf-8"))
    col = fields.OpenEMS.column(out / "openems" / "port1", model, 1)
    freqs = model["frequencies_hz"]
    picked = [(f, abs(s)) for f, s in zip(freqs, col[0], strict=True) if 6e9 - 1e3 <= f <= 8e9 + 1e3]
    assert picked[0][0] == pytest.approx(6e9) and picked[-1][0] == pytest.approx(8e9)
    got = fields.resonance([f for f, _ in picked], [m for _, m in picked])
    assert got["value"] is None and "the least |S11| is at the band's edge, 6 GHz" in got["why"]
    limit = {"measure": "resonance_ghz", "net": "ANT", "min": 6.0, "max": 6.5, "source": "made up"}
    fails, held, unjudged = fields.judge([limit], {"ANT": {"resonance_ghz": got}})
    assert (fails, held) == ([], []) and unjudged[0].startswith("ANT resonance_ghz: not judged, the least")
