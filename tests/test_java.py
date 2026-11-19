"""The java the workcenter runs: the JVM install.sh installed, by the path it records, whatever java
stands first on PATH; the java on PATH only when no record is there.

CI run 44444183056 (2026-11-19): install.sh set up openjdk-21-jre-headless 21.0.13.1, and doctor then
read `absent   java         17.0.21`: the runner's own Java 17 stood first on PATH. Each test here runs
with stand-in java programs on a closed PATH, in 3 cases: a 17 first on PATH and a 21 where install.sh
records its own; only a 17; none. A stand-in writes its call to a log, so a test sees which one ran.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
sys.path.insert(0, str(ROOT / "tools"))
import routers  # noqa: E402

BOARD = ROOT / "tests" / "boards" / "pass-rc-divider"

# A stand-in java: `-version` prints the line a real JVM prints on stderr; any other call writes the
# session file named after -do, so the autoroute gate sees a route.
JAVA = """#!/bin/sh
echo "{name} $*" >> "{log}"
if [ "$1" = "-version" ]; then
  echo 'openjdk version "{version}" 2025-10-21' >&2
  exit 0
fi
while [ $# -gt 0 ]; do
  if [ "$1" = "-do" ]; then echo "(session x)" > "$2"; fi
  shift
done
exit 0
"""


def stand_in(folder: Path, name: str, version: str, log: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / "java"
    exe.write_text(JAVA.format(name=name, version=version, log=log), encoding="utf-8")
    exe.chmod(0o755)
    return exe


def case(tmp_path: Path, which: str) -> tuple[dict, dict]:
    """The environment of 1 case and the stand-ins' paths. `both`: a 17 first on PATH and a 21 at the
    path install.sh recorded in <root>/java.path; `old`: only a 17 on PATH, no record; `none`: no java
    on PATH and no record. PATH holds only the stand-ins' folder (or an empty one)."""
    root, log = tmp_path / "root", tmp_path / "java-calls.log"
    root.mkdir()
    log.write_text("", encoding="utf-8")
    path_dir = tmp_path / "path"
    path_dir.mkdir()
    javas = {}
    if which in ("both", "old"):
        javas["17"] = stand_in(path_dir, "java17", "17.0.21", log)
    if which == "both":
        javas["21"] = stand_in(tmp_path / "jvm" / "java-21-openjdk-amd64" / "bin", "java21", "21.0.13", log)
        (root / "java.path").write_text(f"{javas['21']}\n", encoding="utf-8")
    env = {
        k: v for k, v in os.environ.items() if k not in ("JAVA", "KICAD_CLI", "NGSPICE", "FREEROUTING_JAR")
    }
    env.update({"PATH": str(path_dir), "WORKCENTER_ROOT": str(root), "HOME": str(tmp_path), "DISPLAY": ":0"})
    # The autoroute command takes the machine's engine lock: this one is the test's own.
    env["WORKCENTER_LOCK_DIR"] = str(tmp_path / "lock")
    return env, {"log": log, "root": root, **javas}


def called(paths: dict) -> list[str]:
    return [line.split(" ", 1)[0] for line in paths["log"].read_text(encoding="utf-8").splitlines()]


def doctor(env: dict) -> tuple[dict, str, dict]:
    """The java row of doctor's --json, its java line, and the whole payload."""
    said = []
    for argv in (["--json", "doctor"], ["doctor"]):
        proc = subprocess.run(
            [sys.executable, str(CLI), *argv],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
            check=False,
        )
        said.append(proc.stdout)
    payload = json.loads(said[0])
    (line,) = [ln for ln in said[1].splitlines() if ln.split()[1:2] == ["java"]]
    return payload["checks"]["java"], line, payload


def test_the_recorded_jvm_is_the_one_doctor_reads_whatever_stands_first_on_path(tmp_path):
    """Case `both`, the runner of run 44444183056: doctor reads the 21 install.sh recorded, says ok, and
    its line names the path and the record. The 17 first on PATH is never asked."""
    env, paths = case(tmp_path, "both")
    row, line, payload = doctor(env)
    record = paths["root"] / "java.path"
    assert row["ok"] is True and row["version"] == "21.0.13"
    assert row["path"] == str(paths["21"])
    assert "java" not in payload["degraded"]
    assert line.split() == [
        "ok",
        "java",
        "21.0.13",
        "at",
        f"{paths['21']},",
        "recorded",
        "by",
        "install.sh",
        "in",
        str(record),
    ]
    assert "java17" not in called(paths)


def test_only_an_older_java_on_path_is_absent_and_named(tmp_path):
    """Case `old`: no record, so doctor reads the first java on PATH, a 17. FreeRouting's Java is 21
    (ee-agent-kit/docs/ENGINES.md): the row is absent, the workcenter degraded, and the line names the 17
    and where it was found."""
    env, paths = case(tmp_path, "old")
    row, line, payload = doctor(env)
    assert row["ok"] is False and row["version"] == "17.0.21"
    assert row["path"] == str(paths["17"])
    assert "java" in payload["degraded"]
    assert line.split() == [
        "absent",
        "java",
        "17.0.21",
        "at",
        f"{paths['17']},",
        "the",
        "first",
        "java",
        "on",
        "PATH",
    ]


def test_no_java_at_all_is_absent_and_said_so(tmp_path):
    """Case `none`: no record and no java on PATH. The line says there is none, and where it looked."""
    env, _ = case(tmp_path, "none")
    row, line, payload = doctor(env)
    assert row["ok"] is False and row["version"] is None
    assert "java" in payload["degraded"]
    assert line.split() == ["absent", "java", "none:", "no", "java", "on", "PATH"]


def test_a_record_whose_java_is_gone_is_named_and_not_replaced_by_paths(tmp_path):
    """A record that names a java no longer there: doctor says so and names the record. It does not fall
    back to the 17 on PATH, which install.sh did not choose."""
    env, paths = case(tmp_path, "both")
    paths["21"].unlink()
    row, line, _ = doctor(env)
    record = paths["root"] / "java.path"
    assert row["ok"] is False and row["version"] is None
    assert line.split() == [
        "absent",
        "java",
        "none:",
        "no",
        "java",
        "at",
        f"{paths['21']},",
        "recorded",
        "by",
        "install.sh",
        "in",
        str(record),
    ]
    assert called(paths) == []


def test_java_set_by_the_variable_comes_first(tmp_path):
    """JAVA, the override a test or a user sets, comes before the record, and the line says so."""
    env, paths = case(tmp_path, "both")
    env["JAVA"] = str(paths["17"])
    row, line, _ = doctor(env)
    assert row["path"] == str(paths["17"]) and row["ok"] is False
    assert line.split()[-3:] == ["set", "by", "JAVA"]


@pytest.mark.parametrize("which", ["both", "old", "none"])
def test_the_routers_java_is_the_one_the_workcenter_decides(tmp_path, monkeypatch, which):
    """The default router's command line starts with the java of routers.workcenter_java(): the recorded
    21 in case `both`, `java` from PATH otherwise."""
    env, paths = case(tmp_path, which)
    for name in ("JAVA", "FREEROUTING_JAR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("WORKCENTER_ROOT", env["WORKCENTER_ROOT"])
    monkeypatch.setenv("PATH", env["PATH"])
    monkeypatch.setenv("DISPLAY", ":0")
    want = str(paths["21"]) if which == "both" else "java"
    assert routers.workcenter_java()[0] == want
    cmd = routers.get(routers.DEFAULT).command(tmp_path / "a.dsn", tmp_path / "a.ses", 20, 0, tmp_path)
    assert cmd[0] == want


def test_the_autoroute_gate_runs_the_recorded_java(tmp_path):
    """`workcenter autoroute` on a board with a DSN, in case `both`: the recorded 21 routes, the 17 first
    on PATH is never started."""
    env, paths = case(tmp_path, "both")
    board = tmp_path / "board"
    shutil.copytree(BOARD, board, ignore=shutil.ignore_patterns("build"))
    dsn = tmp_path / "rc.dsn"
    dsn.write_text("(pcb x)\n", encoding="utf-8")
    jar = tmp_path / "freerouting.jar"
    jar.write_text("", encoding="utf-8")
    env["FREEROUTING_JAR"] = str(jar)
    proc = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--json",
            "autoroute",
            str(board),
            "--dsn",
            str(dsn),
            "--out",
            str(tmp_path / "out"),
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert called(paths) == ["java21"]
