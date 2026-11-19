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


@needs_openems
@pytest.mark.skipif(not (WYVERN / "wyvern.kicad_pcb").is_file(), reason="the Wyvern example is not here")
def test_the_wyvern_usb3_lane_runs_through_the_command(tmp_path):
    """The USB 3 TX1 pair of the Wyvern example, from J1's A3 and A2 to U2's 17 and 16 on F.Cu over
    In1.Cu, copied out of the example (the command writes into its project's build folder). 4 ports,
    2 runs, each ending without a fault: each net gets its impedance, return and insertion loss, and
    NEXT and FEXT from the other, 10 measures. The README names no limit with its document yet, so the
    run judges nothing and says so (exit 2)."""
    import shutil

    project = tmp_path / "wyvern"
    shutil.copytree(WYVERN, project, ignore=shutil.ignore_patterns("build"))
    spec = {
        "groups": [
            {
                "name": "usb3-tx1",
                "nets": ["/SS_TX1_P", "/SS_TX1_N"],
                "ports": ["J1.A3", "U2.17", "J1.A2", "U2.16"],
                "band_ghz": [0.1, 10],
                "limits": [],
            }
        ]
    }
    (project / "fields.json").write_text(json.dumps(spec), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CLI), "fields", str(project)], capture_output=True, text=True, timeout=3600
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "no limit stated: nothing judged" in proc.stdout
    report = json.loads((project / "build" / "fields" / "report.json").read_text(encoding="utf-8"))
    measures = report["details"]["measures"]["usb3-tx1"]
    assert sum(len(m) for m in measures.values()) == 10
    assert report["details"]["failures"] == []


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
