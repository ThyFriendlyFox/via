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
import os, subprocess, sys
import pytest

CHILD = "import subprocess\\ntry:\\n    subprocess.run(['ngspice', '-v'])\\nexcept OSError:\\n    pass\\n"
EXEC = "import os\\ntry:\\n    os.execvp('ngspice', ['ngspice', '-v'])\\nexcept OSError:\\n    pass\\n"


def start(args):
    try:
        subprocess.run(args, capture_output=True)
    except OSError:
        pass


@pytest.fixture
def ngspice_in_setup():
    start(["ngspice", "-v"])


@pytest.fixture
def ngspice_in_teardown():
    yield
    start(["ngspice", "-v"])


def test_a_fixture_starts_ngspice_in_setup(ngspice_in_setup):
    pass


def test_a_fixture_starts_ngspice_in_teardown(ngspice_in_teardown):
    pass


def test_os_system_starts_ngspice():
    try:
        os.system("ngspice -v > /dev/null 2>&1")
    except OSError:
        pass


def test_posix_spawn_starts_ngspice():
    try:
        os.waitpid(os.posix_spawnp("ngspice", ["ngspice", "-v"], os.environ), 0)
    except OSError:
        pass


def test_a_child_execs_ngspice():
    subprocess.run([sys.executable, "-c", EXEC], capture_output=True)


def test_timeout_with_a_signal_option_starts_ngspice():
    start(["timeout", "-s", "KILL", "60", "ngspice", "-v"])


def test_env_with_an_unset_option_starts_ngspice():
    start(["env", "-u", "FOO", "ngspice", "-v"])


def test_flock_with_a_command_line_starts_ngspice(tmp_path):
    start(["flock", str(tmp_path / "lock"), "-c", "ngspice -v"])


def test_a_shell_line_that_only_says_an_engine_name():
    assert subprocess.run(["sh", "-c", "echo magic"], capture_output=True, text=True).stdout == "magic\\n"


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


def run_cases(tmp_path: Path, *args: str, files: dict[str, str] | None = None) -> tuple[int, str]:
    """pytest on the cases above (or on `files`), beside a copy of this repository's conftest, with
    engines refused."""
    folder = tmp_path / "cases"
    folder.mkdir()
    for name, text in (files or {"test_cases.py": CASES}).items():
        (folder / name).write_text(text, encoding="utf-8")
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
    """16 cases. 10 start an engine in their call without the marker: kicad-cli from the test, ngspice
    from a child Python, pcbnew imported in a child, yosys from a shell line, ngspice by os.system, by
    os.posix_spawnp, by a child's os.execvp, behind `timeout -s KILL 60`, behind `env -u FOO`, and in
    flock's -c line: 10 failed. 2 start it from a fixture: in setup (the test does not run) and in
    teardown (the call passes, the teardown errs): 2 errors. The marked case, the stand-in, the case
    that starts git, the teardown case's call and `echo magic` (a word, no program) pass: 5 passed."""
    code, text = run_cases(tmp_path, "-rfE")
    assert code == 1, text
    assert "10 failed, 5 passed, 2 errors" in text, text
    for name, engine in (
        ("test_starts_kicad_cli_without_the_marker", "kicad-cli"),
        ("test_a_child_process_starts_ngspice_without_the_marker", "ngspice"),
        ("test_a_child_imports_pcbnew_without_the_marker", "pcbnew"),
        ("test_a_shell_starts_yosys_without_the_marker", "yosys"),
        ("test_a_fixture_starts_ngspice_in_setup", "ngspice"),
        ("test_a_fixture_starts_ngspice_in_teardown", "ngspice"),
        ("test_os_system_starts_ngspice", "ngspice"),
        ("test_posix_spawn_starts_ngspice", "ngspice"),
        ("test_a_child_execs_ngspice", "ngspice"),
        ("test_timeout_with_a_signal_option_starts_ngspice", "ngspice"),
        ("test_env_with_an_unset_option_starts_ngspice", "ngspice"),
        ("test_flock_with_a_command_line_starts_ngspice", "ngspice"),
    ):
        line = f"test_cases.py::{name} started {engine} and has no engine marker (tools/ci/engine_marker.py)"
        assert line in text, text
    assert "test_a_shell_line_that_only_says_an_engine_name started" not in text, text


def test_the_fast_run_deselects_the_marked_tests(tmp_path):
    """-m "not engine" leaves the 15 cases without the marker: 10 fail, 4 pass, 2 err, 1 deselected."""
    code, text = run_cases(tmp_path, "-m", "not engine")
    assert code == 1
    assert "10 failed, 4 passed, 1 deselected, 2 errors" in text, text


COLLECTED = """
import subprocess

try:  # probes when the module is imported, as a skip mark's
    subprocess.run(["ngspice", "-v"], capture_output=True)
    NGSPICE_REFUSED = False
except OSError:
    NGSPICE_REFUSED = True
try:
    import pcbnew  # noqa: F401

    PCBNEW_REFUSED = False
except ImportError:
    PCBNEW_REFUSED = True


def test_the_probes_at_collection_were_refused():
    assert NGSPICE_REFUSED and PCBNEW_REFUSED
"""


def test_a_probe_at_collection_is_refused_in_the_fast_run_and_not_held(tmp_path):
    """A module's probe runs while it is collected, before any test: the fast run refuses it (the probe
    finds no engine), and no test is failed for it. 1 case, 1 passed."""
    code, text = run_cases(tmp_path, files={"test_probe.py": COLLECTED})
    assert code == 0, text
    assert "1 passed" in text, text


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


def test_a_wrapper_option_that_takes_a_value_is_skipped_with_its_value():
    """The options with a value, as each wrapper's --help on this machine lists them (coreutils timeout,
    env, nice, stdbuf; util-linux flock; xvfb-run). flock -c and env -S give a shell line."""
    found = engine_watch.engine_of
    assert found(["timeout", "-s", "KILL", "60", "ngspice", "-b", "x.cir"]) == "ngspice"
    assert found(["timeout", "-k", "5", "60", "ngspice"]) == "ngspice"
    assert found(["env", "-u", "FOO", "-C", "/tmp", "kicad-cli", "version"]) == "kicad-cli"
    assert found(["env", "-S", "ngspice -b x.cir"]) == "ngspice"
    assert found(["nice", "-n", "5", "yosys", "-V"]) == "yosys"
    assert found(["stdbuf", "-o", "L", "ngspice"]) == "ngspice"
    assert found(["flock", "/tmp/l", "-c", "ngspice -v"]) == "ngspice"
    assert found(["flock", "-w", "10", "/tmp/l", "ngspice"]) == "ngspice"
    assert found(["xvfb-run", "-s", "-screen 0 1x1x24", "kicad-cli", "pcb", "render"]) == "kicad-cli"
    assert found(["timeout", "60", "echo", "ngspice"]) is None


def test_only_a_word_in_command_position_of_a_shell_line_is_a_program():
    """A program is the first word of a command: at the start, after ; && || | & or a newline, after
    a reserved word (then, do) or `exec`, and after assignments. Any other word is an argument."""
    found = engine_watch.engine_of
    assert found(["sh", "-c", "echo magic"]) is None
    assert found("grep sta log.txt | wc -l") is None
    assert found("printf '%s' java") is None
    assert found("cd x; FOO=1 ngspice -b x.cir") == "ngspice"
    assert found("true && vvp a.out") == "vvp"
    assert found("make || exec magic -dnull") == "magic"
    assert found("if true; then yosys -V; fi") == "yosys"
    assert found("echo x\nsta flow.tcl") == "sta"
    assert found("echo x | timeout -s KILL 5 ngspice") == "ngspice"
