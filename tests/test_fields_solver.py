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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import fields  # noqa: E402

CLI = ROOT / "tools" / "workcenter"
needs_openems = pytest.mark.skipif(fields.OpenEMS.binary() is None, reason="not installed: openEMS")


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
