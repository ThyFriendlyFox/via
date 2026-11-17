"""The `engine` marker: every test that starts an engine carries it, and the fast run deselects it.

`tools/ci/guard/` is put first on PYTHONPATH by `tests/conftest.py`, so every Python process a test
starts, the CLI among them, loads its `sitecustomize.py`. It writes a line for each engine started and
each import of KiCad's `pcbnew`. With WORKCENTER_NO_ENGINES=1 (the fast run) it refuses the start as
well. The conftest fails a test without the marker that wrote a line. These tests run pytest on a
test file made here, with this repository's conftest.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "ci" / "guard"))
sys.path.insert(0, str(ROOT / "tools"))

import chipflow  # noqa: E402
import engine_watch  # noqa: E402

CASES = """
import subprocess, sys
import pytest

CHILD = "import subprocess\\ntry:\\n    subprocess.run(['ngspice', '-v'])\\nexcept OSError:\\n    pass\\n"


def test_starts_kicad_cli_without_the_marker():
    with pytest.raises(OSError):
        subprocess.run(["kicad-cli", "version"], capture_output=True)


@pytest.mark.engine
def test_starts_kicad_cli_with_the_marker():
    with pytest.raises(OSError):
        subprocess.run(["kicad-cli", "version"], capture_output=True)


def test_a_child_process_starts_ngspice_without_the_marker():
    subprocess.run([sys.executable, "-c", CHILD], check=True)


def test_a_child_imports_pcbnew_without_the_marker():
    subprocess.run([sys.executable, "-c", "import pcbnew"], capture_output=True)


def test_a_shell_starts_yosys_without_the_marker():
    subprocess.run(["bash", "-c", "yosys -V || true"], capture_output=True)


def test_a_stand_in_written_by_the_test_is_no_engine(tmp_path):
    fake = tmp_path / "ngspice"
    fake.write_text("#!/bin/sh\\necho stand-in\\n")
    fake.chmod(0o755)
    assert subprocess.run([str(fake)], capture_output=True, text=True).stdout == "stand-in\\n"


def test_starts_git_and_python_only():
    subprocess.run(["git", "--version"], capture_output=True, check=True)
"""


def run_cases(tmp_path: Path, *args: str) -> tuple[int, str]:
    """pytest on the cases above, beside a copy of this repository's conftest, with engines refused."""
    folder = tmp_path / "cases"
    folder.mkdir()
    (folder / "test_cases.py").write_text(CASES, encoding="utf-8")
    # The repository's conftest, with the folder of the plugin named from this checkout.
    conftest = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    plugin = 'Path(__file__).resolve().parents[1] / "tools" / "ci"'
    assert conftest.count(plugin) == 1
    conftest = conftest.replace(plugin, f"Path({str(ROOT / 'tools' / 'ci')!r})")
    (folder / "conftest.py").write_text(conftest, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k not in ("WORKCENTER_ENGINE_LOG", "PYTHONPATH")}
    env["WORKCENTER_NO_ENGINES"] = "1"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--rootdir", str(folder), *args],
        cwd=folder,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def test_a_test_without_the_marker_that_starts_an_engine_fails(tmp_path):
    """4 of the 7 cases start an engine without the marker: kicad-cli from the test, ngspice from a
    child Python, pcbnew imported in a child, yosys from a shell. The marked case, the stand-in under
    the test's own folder and the case that starts git pass: 3 passed, 4 failed."""
    code, text = run_cases(tmp_path, "-rf")
    assert code == 1, text
    assert "4 failed, 3 passed" in text, text
    for name, engine in (
        ("test_starts_kicad_cli_without_the_marker", "kicad-cli"),
        ("test_a_child_process_starts_ngspice_without_the_marker", "ngspice"),
        ("test_a_child_imports_pcbnew_without_the_marker", "pcbnew"),
        ("test_a_shell_starts_yosys_without_the_marker", "yosys"),
    ):
        line = f"test_cases.py::{name} started {engine} and has no engine marker (tools/ci/engine_marker.py)"
        assert line in text, text


def test_the_fast_run_deselects_the_marked_tests(tmp_path):
    """-m "not engine" leaves the 6 cases without the marker: 4 fail, 2 pass, 1 deselected."""
    code, text = run_cases(tmp_path, "-m", "not engine")
    assert code == 1
    assert "4 failed, 2 passed, 1 deselected" in text, text


FULL_RUN_CASE = """
import subprocess


def test_starts_ngspice_in_a_full_run():
    try:
        subprocess.run(["ngspice", "--version"], capture_output=True, timeout=60)
    except OSError:
        pass
"""


@pytest.mark.engine
def test_a_full_run_starts_the_engine_and_still_fails_the_test_without_the_marker(tmp_path):
    """Without WORKCENTER_NO_ENGINES the start is not refused, only written down: `make verify` holds
    the marker too. The case starts ngspice (or finds it absent: the start is written before)."""
    folder = tmp_path / "full"
    folder.mkdir()
    (folder / "test_case.py").write_text(FULL_RUN_CASE, encoding="utf-8")
    conftest = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    plugin = 'Path(__file__).resolve().parents[1] / "tools" / "ci"'
    (folder / "conftest.py").write_text(
        conftest.replace(plugin, f"Path({str(ROOT / 'tools' / 'ci')!r})"), encoding="utf-8"
    )
    env = {k: v for k, v in os.environ.items() if k not in ("WORKCENTER_ENGINE_LOG", "PYTHONPATH")}
    env.pop("WORKCENTER_NO_ENGINES", None)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--rootdir", str(folder)],
        cwd=folder,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    text = proc.stdout + proc.stderr
    assert proc.returncode == 1 and "1 failed" in text, text
    assert "test_case.py::test_starts_ngspice_in_a_full_run started ngspice and has no engine marker" in text


def test_the_guard_names_every_chip_engine_and_the_board_engines():
    """The chip flow's own table of engines (tools/chipflow.py ENGINES) and the board engines of
    tools/workcenter (KICAD_CLI, NGSPICE, JAVA for FreeRouting) and tools/fields.py (openEMS)."""
    assert set(chipflow.ENGINES) <= engine_watch.ENGINES
    assert {"kicad-cli", "ngspice", "java", "openEMS"} <= engine_watch.ENGINES
    assert engine_watch.MODULES == {"pcbnew"}


def test_an_engine_is_found_behind_a_wrapper_and_in_a_shell_line():
    found = engine_watch.engine_of
    assert found(["/usr/bin/kicad-cli", "sch", "erc"]) == "kicad-cli"
    assert found(["xvfb-run", "-a", "kicad-cli", "pcb", "render"]) == "kicad-cli"
    assert found(["timeout", "60", "ngspice", "-b", "x.cir"]) == "ngspice"
    assert found(["sh", "-c", "cd x && yosys -s synth.ys > log"]) == "yosys"
    assert found("openroad -exit layout.tcl") == "openroad"
    assert found(["git", "status"]) is None
    assert found([sys.executable, "tools/workcenter", "gates", "x"]) is None
    assert found(["bash", "-c", "echo ngspice-not-installed"]) is None
