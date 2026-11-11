"""The opt-in chip step of install.sh: every download pinned, off unless asked for, and the engines it
installs print the versions the workcenter was proven on.

The step itself needs root and the network, so no test runs it. The tests read the script and its lock
files, and, where the step has run, start each engine once.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "install.sh"
LOCKS = ROOT / "environment" / "chip"
CHIP = Path(os.environ.get("WORKCENTER_CHIP_TOOLS") or "/opt/workcenters/ee/chip")

needs_chip = pytest.mark.skipif(
    not (CHIP / "bin" / "openroad").exists(), reason="the chip engines are not installed (INSTALL_CHIP=1)"
)


def script() -> str:
    return INSTALL.read_text(encoding="utf-8")


def assigned(name: str) -> str:
    """The value install.sh gives a variable on a line of its own, as `NAME="value"`."""
    (value,) = re.findall(rf'^{name}="([^"]*)"$', script(), re.M)
    return value


@pytest.mark.parametrize("lock", ["openroad.explicit.txt", "layout.explicit.txt"])
def test_a_conda_environment_is_a_list_of_urls_each_with_its_md5(lock):
    lines = [ln for ln in (LOCKS / lock).read_text(encoding="utf-8").splitlines() if ln and ln[0] != "#"]
    assert lines[0] == "@EXPLICIT"
    packages = lines[1:]
    assert len(packages) >= 20
    for line in packages:
        assert re.fullmatch(r"https://conda\.anaconda\.org/[\w-]+/[\w-]+/[^#\s]+#[0-9a-f]{32}", line), line
    # only the 2 channels the step was proven with: Anaconda's `main` has other terms of service
    assert {line.split("/")[3] for line in packages} <= {"conda-forge", "litex-hub"}


def test_ciel_and_each_package_under_it_is_pinned_to_a_version():
    lines = (LOCKS / "ciel.requirements.txt").read_text(encoding="utf-8").split()
    assert "ciel==3.2.0" in lines and len(lines) == 16
    for line in lines:
        assert re.fullmatch(r"[\w.-]+==\d[\w.]*", line), line


def test_the_engines_the_locks_name_are_the_ones_the_flow_was_proven_on():
    names = {}
    for lock in ("openroad.explicit.txt", "layout.explicit.txt"):
        for line in (LOCKS / lock).read_text(encoding="utf-8").splitlines():
            if "/litex-hub/" in line:
                package = line.split("/")[-1].split("#")[0]
                names[package.split("-")[0]] = package
    assert names == {
        "openroad": "openroad-2.0_3175_gf12e2f474-20220317_162926.tar.bz2",
        "magic": "magic-8.3.465_0_g5477395-20240223_100318.tar.bz2",
        "netgen": "netgen-1.5.272_0_g178af5f-20240223_100318.tar.bz2",
    }


def test_micromamba_and_the_process_kit_are_pinned_in_the_script():
    assert assigned("MICROMAMBA_VERSION") == "2.10.0"
    assert re.fullmatch(r"[0-9a-f]{64}", assigned("MICROMAMBA_SHA256"))
    assert assigned("SKY130_COMMIT") == "6d4d11780c40b20ee63cc98e645307a9bf2b2ab8"
    text = script()
    # the archive is checked before it is unpacked, and the kit is asked for by its commit
    assert text.index('sha256sum -c - >/dev/null \\\n      || die "chip: checksum mismatch') < text.index(
        'tar -xjf "${root}/micromamba.tar.bz2"'
    )
    assert '-l sky130_fd_sc_hd "$SKY130_COMMIT"' in text


def test_the_chip_step_runs_only_when_it_is_asked_for():
    text = script()
    assert assigned("INSTALL_CHIP") == "${INSTALL_CHIP:-0}"
    main = text[text.index("\nmain() {") :]
    # 2 calls in main: behind --chip, and behind INSTALL_CHIP=1 after the steps every install runs
    assert main.count("step_chip") == 2
    assert 'if [[ "${1:-}" == "--chip" ]]; then\n    step_chip\n' in main
    assert 'if [[ "$INSTALL_CHIP" == "1" ]]; then\n    step_chip\n  fi' in main
    # a failure inside the step stops the script: every download and every engine check ends in `die`
    step = text[text.index("\nstep_chip() {") : text.index("\nmain() {")]
    assert step.count("|| die ") >= 8


def test_the_script_parses():
    proc = subprocess.run(["bash", "-n", str(INSTALL)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr


def said(*command: object) -> str:
    """What an engine prints with nothing on standard input: Magic and Netgen wait on a terminal."""
    proc = subprocess.run(
        [str(c) for c in command],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    return proc.stdout + proc.stderr


@needs_chip
def test_each_installed_engine_prints_the_version_the_locks_name():
    assert (
        said(CHIP / "bin" / "openroad", "-version").split()[0] == "f12e2f474102bfb875eeee57fb610d7d7de17770"
    )
    assert said(CHIP / "bin" / "sta", "-version").strip() == "2.3.1"
    assert said(CHIP / "bin" / "magic", "--version").strip() == "8.3.465"
    assert "Netgen 1.5.272 compiled on" in said(CHIP / "bin" / "netgen", "-batch", "quit")


@needs_chip
def test_the_installed_process_kit_is_the_pinned_one_and_its_magic_can_read_it():
    kit = CHIP / "pdk" / "sky130A"
    assert kit.resolve().parent.name == assigned("SKY130_COMMIT")
    tech = (kit / "libs.tech" / "magic" / "sky130A.tech").read_text(encoding="utf-8", errors="replace")
    version = re.search(r"^version\n\s*version (\S+)\n\s*description", tech, re.M)
    assert version and version.group(1) == "1.0.470-0-g6d4d117"
    # the kit states the Magic it needs; the installed one is at least that
    needed = re.search(r"requires magic-(\d+)\.(\d+)\.(\d+)", tech)
    assert needed and tuple(map(int, needed.groups())) <= (8, 3, 465)
    libs = sorted(p.name for p in (kit / "libs.ref" / "sky130_fd_sc_hd" / "lib").glob("*.lib"))
    assert len(libs) == 18 and "sky130_fd_sc_hd__tt_025C_1v80.lib" in libs
