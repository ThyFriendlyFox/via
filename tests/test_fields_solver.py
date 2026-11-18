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


@needs_openems
def test_a_run_with_no_limit_judges_nothing_and_does_not_pass(tmp_path):
    """The line with its limits taken out: the run measures and writes its report, and says it judged
    nothing, exit 2, never PASS."""
    import shutil

    project = tmp_path / "line"
    shutil.copytree(ROOT / "tests" / "boards" / "pass-fields-microstrip", project)
    spec = json.loads((project / "fields.json").read_text(encoding="utf-8"))
    spec["groups"][0]["limits"] = []
    (project / "fields.json").write_text(json.dumps(spec), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CLI), "fields", str(project)], capture_output=True, text=True, timeout=3600
    )
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
def test_the_same_file_gives_the_same_numbers(stub, tmp_path):
    """openEMS stops on a check made every 4 s of the clock: 4 runs of the stub stopped after 7189 to
    8453 steps and gave 29.55 to 29.99 dB. The spectra end where the ports' energy has settled, a
    sample every run reaches the same way: a second run gives every measure to the last digit, while
    a busy machine slows it."""
    load = subprocess.Popen([sys.executable, "-c", "while True: pass"])
    try:
        _, again = run("fail-fields-stub", tmp_path)
    finally:
        load.kill()
        load.wait()
    assert again["details"]["measures"] == stub[1]["details"]["measures"]


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
    "against a margin of 30 % written before the run. The margin is not widened after the run.",
)
def test_lossy_copper_adds_the_closed_form_conductor_loss(tmp_path):
    """The line made 40 mm long, run with copper as a perfect sheet and as a conducting sheet of 58e6
    S/m and 0.035 mm (NIST Handbook 100, 1966, 1.2a, p. 2). The difference of their attenuations, read
    from S11 and S21 so that the mismatch is no part of it, is the conductor's. Hammerstad and Jensen
    (Qucs Technical Papers, 2014, eq. 11.80 to 11.83, p. 171) at 5 GHz with no roughness (Kr = 1):
    R = sqrt(rho pi f mu0) = sqrt(1.7241e-8 x pi x 5e9 x 4 pi e-7) = 0.018448 ohm,
    Ki = exp(-1.2 (51.337 / 376.73)^0.7) = 0.74279, alpha_c = 0.018448 / (51.337 x 0.36e-3) x 0.74279
    = 0.74145 Np/m. The margin, 30 %, was written before the run: 0.519 to 0.964 Np/m, the median over
    4.5 to 5.5 GHz."""
    sheet = line_copy(tmp_path, "sheet40", {}, length_mm=40)
    lossy = line_copy(tmp_path, "lossy40", {"copper": "lossy"}, length_mm=40)
    for project in (sheet, lossy):
        proc, _ = run_project(project)
        assert proc.returncode == 0, proc.stdout + proc.stderr
    a_sheet = attenuation_per_m(sheet, 0.04, 4.5e9, 5.5e9)
    a_lossy = attenuation_per_m(lossy, 0.04, 4.5e9, 5.5e9)
    assert 0.519 <= a_lossy - a_sheet <= 0.964, (a_sheet, a_lossy)


@needs_openems
def test_the_patch_resonates_where_its_length_says(tmp_path):
    """tests/boards/pass-fields-patch: a patch 12 mm by 12 mm over 0.8 mm of 4.5, fed at the middle of
    1 edge. eeff (Hammerstad and Jensen, u = 15) = 4.06762; each open end adds 0.42208 mm (Kirschning,
    Jansen and Koster, Qucs Technical Papers 2014, eq. 11.185 to 11.190, p. 181); half a wavelength in
    12.84416 mm: c / (2 x 12.84416 mm x sqrt(4.06762)) = 5.7865 GHz. The margin, 7 %, was written in
    fields.json before the run: 5.381 to 6.192 GHz. With --strict the fixture holds both its limits."""
    proc, report = run("pass-fields-patch", tmp_path, "--strict")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert report["summary"].startswith("2 held, 0 failed, 0 not judged")
    got = report["details"]["measures"]["patch"]["ANT"]["resonance_ghz"]["value"]
    assert 5.381 <= got <= 6.192
