"""The java Via runs: the JVM install.sh installed, by the path it records, whatever java
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


def draws(exe: Path) -> Path:
    """Give the stand-in's JVM the X11 library of AWT, lib/libawt_xawt.so, as openjdk-21-jre does."""
    lib = exe.parent.parent / "lib"
    lib.mkdir(parents=True, exist_ok=True)
    (lib / "libawt_xawt.so").write_text("", encoding="utf-8")
    return exe


def case(tmp_path: Path, which: str) -> tuple[dict, dict]:
    """The environment of 1 case and the stand-ins' paths. `both`: a 17 first on PATH and a 21 at the
    path install.sh recorded in <root>/java.path; `old`: only a 17 on PATH, no record; `none`: no java
    on PATH and no record. `headless`: the record names a 21 whose JVM has no lib/libawt_xawt.so (Ubuntu's
    openjdk-21-jre-headless alone, as on GitHub's runner in CI run 44515796762), and a 21 that has it
    stands first on PATH; `headless-old`: the same record, a 17 first on PATH. PATH holds only the
    stand-ins' folder (or an empty one). Every stand-in but the headless one has the library."""
    root, log = tmp_path / "root", tmp_path / "java-calls.log"
    root.mkdir()
    log.write_text("", encoding="utf-8")
    path_dir = tmp_path / "path"
    path_dir.mkdir()
    javas = {}
    if which in ("both", "old", "headless-old"):
        javas["17"] = draws(stand_in(path_dir, "java17", "17.0.21", log))
    if which == "headless":
        javas["path21"] = draws(stand_in(path_dir, "javapath21", "21.0.9", log))
    if which in ("headless", "headless-old"):
        javas["21"] = stand_in(tmp_path / "jvm" / "java-21-openjdk-amd64" / "bin", "java21", "21.0.13", log)
        (root / "java.path").write_text(f"{javas['21']}\n", encoding="utf-8")
    if which == "both":
        javas["21"] = draws(
            stand_in(tmp_path / "jvm" / "java-21-openjdk-amd64" / "bin", "java21", "21.0.13", log)
        )
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
    (ee-agent-kit/docs/ENGINES.md): the row is absent, Via degraded, and the line names the 17,
    where it was found and why FreeRouting cannot run on it."""
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
        *"the first java on PATH; FreeRouting cannot run on it:".split(),
        str(paths["17"]),
        *"is Java 17; FreeRouting 1.9.0 needs Java 21".split(),
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
    back to the 17 on PATH, which FreeRouting 1.9.0 is not held to: the 17 is asked its version only."""
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
    asked = paths["log"].read_text(encoding="utf-8").splitlines()
    assert set(asked) <= {"java17 -version"}, asked


def test_java_set_by_the_variable_comes_first(tmp_path):
    """JAVA, the override a test or a user sets, comes before the record, and the line says so."""
    env, paths = case(tmp_path, "both")
    env["JAVA"] = str(paths["17"])
    row, line, _ = doctor(env)
    assert row["path"] == str(paths["17"]) and row["ok"] is False
    assert f"{paths['17']}, set by JAVA; FreeRouting cannot run on it: " in line, line


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
    # The 21 is asked its version (the router's check), then routes; the 17 is never started.
    asked = paths["log"].read_text(encoding="utf-8").splitlines()
    assert [ln.split(" ", 2)[:2] for ln in asked] == [["java21", "-version"], ["java21", "-jar"]], asked


# CI run 44515796762 (job 135531488086, 2026-11-19): install.sh recorded
# /usr/lib/jvm/java-21-openjdk-amd64/bin/java, the JVM of openjdk-21-jre-headless, and 13 routing tests
# ended in "FreeRouting exited 1". FreeRouting 1.9.0 draws a window under xvfb-run; the headless runtime
# has no lib/libawt_xawt.so (this machine's /var/lib/dpkg/info/openjdk-21-jre-headless:amd64.list names
# libawt.so and libawt_headless.so only; openjdk-21-jre's list names libawt_xawt.so).


def routers_env(monkeypatch, env: dict, tmp_path: Path) -> None:
    """The case's environment in this process, with a jar of the test's own so that only Java decides."""
    jar = tmp_path / "freerouting.jar"
    jar.write_text("", encoding="utf-8")
    for name in ("JAVA", "FREEROUTING_JAR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FREEROUTING_JAR", str(jar))
    for name in ("WORKCENTER_ROOT", "PATH", "DISPLAY"):
        monkeypatch.setenv(name, env[name])


def test_a_recorded_jvm_that_cannot_draw_gives_way_to_a_java_on_path_that_can(tmp_path, monkeypatch):
    """Case `headless`: the record names a 21 without lib/libawt_xawt.so, a 21 with it stands first on
    PATH. Via runs the one on PATH: the pick, the router's command line and doctor's row agree, and
    the pick says why the record was passed over."""
    env, paths = case(tmp_path, "headless")
    routers_env(monkeypatch, env, tmp_path)
    record = paths["root"] / "java.path"
    exe, how = routers.workcenter_java()
    assert exe == "java"
    assert str(paths["21"]) in how and str(record) in how and "libawt_xawt.so" in how
    router = routers.get(routers.DEFAULT)
    assert router.absent() == ""
    assert router.command(tmp_path / "a.dsn", tmp_path / "a.ses", 20, 0, tmp_path)[0] == "java"
    env["FREEROUTING_JAR"] = str(tmp_path / "freerouting.jar")
    row, line, payload = doctor(env)
    assert row["ok"] is True and row["path"] == str(paths["path21"]), line
    assert "java" not in payload["degraded"]
    assert line.split()[:4] == ["ok", "java", "21.0.9", "at"]


def test_a_route_with_no_java_that_can_draw_is_refused_with_the_java_and_why(tmp_path, monkeypatch):
    """Case `headless-old`: the record's 21 cannot draw and the 17 on PATH is older than FreeRouting's
    Java. The record stays the pick; the router is absent, and its reason names the java, where it came
    from and why it was refused; doctor's row names the same java and says absent."""
    env, paths = case(tmp_path, "headless-old")
    routers_env(monkeypatch, env, tmp_path)
    record = paths["root"] / "java.path"
    assert routers.workcenter_java()[0] == str(paths["21"])
    why = routers.get(routers.DEFAULT).absent()
    assert why.startswith(f"freerouting: {paths['21']} (recorded by install.sh in {record}) cannot run ")
    assert f"{paths['21'].parent.parent / 'lib'} has no libawt_xawt.so" in why, why
    with pytest.raises(FileNotFoundError, match="libawt_xawt.so"):
        routers.get(routers.DEFAULT).run(
            tmp_path / "a.dsn", tmp_path / "a.ses", tmp_path / "a.log", 20, 0, 60, tmp_path
        )
    assert "java21" not in called(paths)
    row, line, payload = doctor(env)
    assert row["ok"] is False and row["path"] == str(paths["21"])
    assert "java" in payload["degraded"]
    assert "libawt_xawt.so" in line, line


def test_a_record_whose_java_is_gone_gives_way_to_a_21_on_path_that_can_draw(tmp_path, monkeypatch):
    """The record names a java that was removed, and a 21 that can draw stands first on PATH: Via runs
    the 21 on PATH, and the pick names the record it passed over."""
    env, paths = case(tmp_path, "headless")
    paths["21"].unlink()
    routers_env(monkeypatch, env, tmp_path)
    exe, how = routers.workcenter_java()
    assert exe == "java" and f"no java at {paths['21']}" in how


def failing_router(tmp_path: Path, monkeypatch, said: str) -> str:
    """Run the default router on a java given by JAVA that answers `-version` as a 21, has its JVM's
    lib/libawt_xawt.so, and on a route runs `said` (shell lines) and exits 1. The error's text."""
    java = draws(tmp_path / "jvm" / "bin" / "java")
    java.parent.mkdir(parents=True, exist_ok=True)
    java.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-version" ]; then echo \'openjdk version "21.0.13" 2025-10-21\' >&2; exit 0; fi\n'
        f"{said}exit 1\n",
        encoding="utf-8",
    )
    java.chmod(0o755)
    jar = tmp_path / "freerouting.jar"
    jar.write_text("", encoding="utf-8")
    monkeypatch.setenv("JAVA", str(java))
    monkeypatch.setenv("FREEROUTING_JAR", str(jar))
    monkeypatch.setenv("DISPLAY", ":0")
    with pytest.raises(RuntimeError) as caught:
        routers.get(routers.DEFAULT).run(
            tmp_path / "a.dsn", tmp_path / "a.ses", tmp_path / "a.log", 20, 0, 60, tmp_path
        )
    return str(caught.value)


def test_a_router_that_fails_names_its_java_and_its_last_words(tmp_path, monkeypatch):
    """A router that ends with exit 1: the error names the java that ran and the Java exception it
    threw, not only the exit code. The 13 reports of run 44515796762 showed `FreeRouting exited 1; see
    <log>` and nothing of what the router said. FreeRouting 1.9.0 logs it on stdout; these lines are its
    log's on this machine with a JVM without lib/libawt_xawt.so."""
    said = failing_router(
        tmp_path,
        monkeypatch,
        "echo '2026-11-19 12:25:38.683 [main] INFO  Freerouting v1.9.0 (build-date: 2023-10-30)'\n"
        "echo '2026-11-19 12:25:38.761 [main] ERROR '\necho 'No X11 DISPLAY variable was set,'\n"
        "echo 'java.awt.HeadlessException: '\n"
        "echo '\tat sun.awt.HeadlessToolkit.getScreenSize(HeadlessToolkit.java:186) ~[?:?]'\n"
        "echo 'a last word' >&2\n",
    )
    java = tmp_path / "jvm" / "bin" / "java"
    assert said.startswith("FreeRouting exited 1 "), said
    assert f"(java {java}); it said: java.awt.HeadlessException:; see " in said, said


def test_a_router_that_throws_an_error_names_the_error(tmp_path, monkeypatch):
    """A Java Error counts as what the router threw, as an Exception does: a JVM whose X11 library does
    not load throws `java.lang.UnsatisfiedLinkError`, not an exception."""
    said = failing_router(
        tmp_path,
        monkeypatch,
        "echo 'java.lang.UnsatisfiedLinkError: /x/lib/libawt_xawt.so: libXrender.so.1: cannot open'\n"
        "echo 'another last word' >&2\n",
    )
    assert "; it said: java.lang.UnsatisfiedLinkError: /x/lib/libawt_xawt.so: " in said, said


def test_a_router_that_throws_nothing_names_its_last_line_on_stderr(tmp_path, monkeypatch):
    """A router that throws nothing: the error ends with its last line on stderr."""
    said = failing_router(tmp_path, monkeypatch, "echo 'routing' \necho 'a last word' >&2\necho '' >&2\n")
    assert "; it said: a last word; see " in said, said


# The review of 2026-11-19 (attack-pr116-full): the autoroute command ran a java the router refused;
# no test noticed a pick that never refused the first java on PATH, nor one that read a link's folder
# instead of its JVM's; a recorded 17 that draws was run by the router and called absent by doctor; a
# java given by JAVA was never checked; a record that cannot be read was not named.


def jvm(tmp_path: Path, name: str, version: str, log: Path, can_draw: bool = True) -> Path:
    """A stand-in JVM at <tmp>/jvm/<name>, its java at bin/java; with `can_draw`, its lib/libawt_xawt.so."""
    exe = stand_in(tmp_path / "jvm" / name / "bin", name, version, log)
    return draws(exe) if can_draw else exe


def no_record_env(tmp_path: Path, monkeypatch, java: Path | None) -> dict:
    """No record of install.sh's; PATH holds only <tmp>/usr/bin, where `java` links to `java` when given
    (as /usr/bin/java links into /usr/lib/jvm on Ubuntu). <tmp>/usr/lib has no libawt_xawt.so."""
    env, paths = case(tmp_path, "none")
    usr_bin = tmp_path / "usr" / "bin"
    usr_bin.mkdir(parents=True)
    if java is not None:
        (usr_bin / "java").symlink_to(java)
    env["PATH"] = str(usr_bin)
    routers_env(monkeypatch, env, tmp_path)
    env["FREEROUTING_JAR"] = str(tmp_path / "freerouting.jar")
    return env


def test_no_record_and_a_java_on_path_that_links_to_a_jvm_that_draws_runs(tmp_path, monkeypatch):
    """No record, and PATH's java is a link into a Java 21 JVM that has lib/libawt_xawt.so, as on every
    Ubuntu machine with openjdk-21-jre: the router runs it and doctor says ok. The library is looked
    for in the JVM the link leads to, not beside the link."""
    log = tmp_path / "calls.log"
    java = jvm(tmp_path, "java-21-openjdk-amd64", "21.0.13", log)
    env = no_record_env(tmp_path, monkeypatch, java)
    assert routers.get(routers.DEFAULT).absent() == ""
    row, line, _ = doctor(env)
    assert row["ok"] is True and row["path"] == str(tmp_path / "usr" / "bin" / "java"), line
    on_path = tmp_path / "usr" / "bin" / "java"
    assert line.split() == ["ok", "java", "21.0.13", "at", f"{on_path},", *"the first java on PATH".split()]


def test_no_record_and_a_java_on_path_that_cannot_draw_is_refused(tmp_path, monkeypatch):
    """No record, and PATH's java is a 21 whose JVM has no lib/libawt_xawt.so: the router is absent and
    names the first java on PATH and the library; doctor says absent with the same reason."""
    log = tmp_path / "calls.log"
    java = jvm(tmp_path, "java-21-openjdk-amd64", "21.0.13", log, can_draw=False)
    env = no_record_env(tmp_path, monkeypatch, java)
    why = routers.get(routers.DEFAULT).absent()
    assert why.startswith("freerouting: java (the first java on PATH) cannot run FreeRouting 1.9.0: "), why
    assert f"{java.parent.parent / 'lib'} has no libawt_xawt.so" in why, why
    row, line, _ = doctor(env)
    assert row["ok"] is False and "libawt_xawt.so" in line, line


@pytest.mark.parametrize(
    "version, reason",
    [
        ("17.0.21", "is Java 17; FreeRouting 1.9.0 needs Java 21"),
        ("1.8.0_402", "is Java 8; FreeRouting 1.9.0 needs Java 21"),
        ("", "-version names no version"),
    ],
)
def test_no_record_and_a_java_on_path_older_than_21_is_refused_as_doctor_says(
    tmp_path, monkeypatch, version, reason
):
    """No record, and PATH's java draws but is older than Java 21, or names no version: doctor says
    absent, and the router says so too and does not run it (they disagreed: the router ran it)."""
    log = tmp_path / "calls.log"
    java = jvm(tmp_path, "old", version, log)
    if not version:
        java.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    env = no_record_env(tmp_path, monkeypatch, java)
    why = routers.get(routers.DEFAULT).absent()
    assert why.startswith("freerouting: java (the first java on PATH) cannot run FreeRouting 1.9.0: "), why
    assert reason in why, why
    row, _, _ = doctor(env)
    assert row["ok"] is False


def test_a_recorded_17_that_draws_gives_way_to_a_21_on_path_that_draws(tmp_path, monkeypatch):
    """The record names a Java 17 that draws, and a 21 that draws stands first on PATH. FreeRouting's
    Java is 21 for the router as for doctor: Via runs the 21 on PATH, the router is not absent, and
    doctor says ok at the same java (they disagreed: the router ran the 17, doctor said absent)."""
    env, paths = case(tmp_path, "headless")
    paths["21"].unlink()
    rec17 = jvm(tmp_path, "java-17-openjdk-amd64", "17.0.21", paths["log"])
    (paths["root"] / "java.path").write_text(f"{rec17}\n", encoding="utf-8")
    routers_env(monkeypatch, env, tmp_path)
    exe, how = routers.workcenter_java()
    assert exe == "java" and f"{rec17} is Java 17" in how, how
    assert routers.get(routers.DEFAULT).absent() == ""
    env["FREEROUTING_JAR"] = str(tmp_path / "freerouting.jar")
    row, line, _ = doctor(env)
    assert row["ok"] is True and row["path"] == str(paths["path21"]), line


def test_java_set_by_the_variable_is_checked_as_the_record_is(tmp_path, monkeypatch):
    """JAVA set to a java that is not there, to a 21 without lib/libawt_xawt.so, or to a 17: the router
    is absent and says why, as doctor does. JAVA is still taken over the record and PATH."""
    env, paths = case(tmp_path, "headless")
    routers_env(monkeypatch, env, tmp_path)
    env["FREEROUTING_JAR"] = str(tmp_path / "freerouting.jar")
    lib = paths["21"].parent.parent / "lib"
    for java, reason in (
        ("nonsense", "no java at nonsense"),
        (str(paths["21"]), f"{lib} has no libawt_xawt.so"),
        (str(jvm(tmp_path, "j17", "17.0.21", paths["log"])), "is Java 17"),
    ):
        monkeypatch.setenv("JAVA", java)
        env["JAVA"] = java
        why = routers.get(routers.DEFAULT).absent()
        assert why.startswith(f"freerouting: {java} (set by JAVA) cannot run FreeRouting 1.9.0: "), why
        assert reason in why, why
        row, _, _ = doctor(env)
        assert row["ok"] is False and row["path"] in (java, "nonsense"), row


def test_a_record_that_cannot_be_read_is_named(tmp_path, monkeypatch):
    """A record that cannot be read (here a folder, which root cannot read either) gives way to the 21
    on PATH, and the pick names the record and that it could not be read."""
    env, paths = case(tmp_path, "headless")
    record = paths["root"] / "java.path"
    record.unlink()
    record.mkdir()
    routers_env(monkeypatch, env, tmp_path)
    exe, how = routers.workcenter_java()
    assert exe == "java" and f"{record} cannot be read" in how, how


def test_a_record_of_2_lines_is_refused_without_a_line_break_in_any_line(tmp_path, monkeypatch):
    """install.sh writes 1 path. A record of 2 lines is passed over for the 21 on PATH; the pick, the
    router's reason and doctor's line hold no raw line break, and name the record's lines."""
    env, paths = case(tmp_path, "headless")
    record = paths["root"] / "java.path"
    record.write_text(f"{paths['path21']}\n{paths['21']}\n", encoding="utf-8")
    routers_env(monkeypatch, env, tmp_path)
    exe, how = routers.workcenter_java()
    assert exe == "java" and "\n" not in how and f"{record} holds 2 lines" in how, how
    record.write_text(f"{paths['21']}\n{paths['21']}\n", encoding="utf-8")
    (tmp_path / "path" / "java").unlink()
    exe, how, why = routers.java_choice()
    assert "\n" not in exe + how + why and f"{record} holds 2 lines" in why, (exe, how, why)
    assert "\n" not in routers.get(routers.DEFAULT).absent()
    env["FREEROUTING_JAR"] = str(tmp_path / "freerouting.jar")
    row, line, _ = doctor(env)
    assert row["ok"] is False and "\n" not in row["line"] and f"{record} holds 2 lines" in line, line


def test_the_autoroute_gate_refuses_a_java_the_router_refuses(tmp_path):
    """`workcenter autoroute` in case `headless-old`: the record's 21 cannot draw and the 17 on PATH is too
    old. The gate skips, names the java, where it came from and why, and starts no java route; before,
    it ran the 21, and a real headless JVM there gave `FreeRouting exited 1` with no word of why."""
    env, paths = case(tmp_path, "headless-old")
    board = tmp_path / "board"
    shutil.copytree(BOARD, board, ignore=shutil.ignore_patterns("build"))
    dsn = tmp_path / "rc.dsn"
    dsn.write_text("(pcb x)\n", encoding="utf-8")
    jar = tmp_path / "freerouting.jar"
    jar.write_text("", encoding="utf-8")
    env["FREEROUTING_JAR"] = str(jar)
    argv = [sys.executable, str(CLI), "--json", "autoroute", str(board), "--dsn", str(dsn)]
    proc = subprocess.run(
        [*argv, "--out", str(tmp_path / "out")],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=False,
    )
    [result] = json.loads(proc.stdout)
    record = paths["root"] / "java.path"
    assert proc.returncode == 2 and result["status"] == "skip", proc.stdout + proc.stderr
    assert result["summary"].startswith(
        f"engine missing: {paths['21']} (recorded by install.sh in {record}) cannot run FreeRouting 1.9.0: "
    ), result["summary"]
    assert "libawt_xawt.so" in result["summary"]
    assert [c for c in called(paths) if c == "java21"] == [], called(paths)
    assert not any(" -jar " in ln for ln in paths["log"].read_text(encoding="utf-8").splitlines())


@pytest.mark.parametrize(
    "release, reason", [("21.0.13.0.3", ""), ("17.0.21", "is Java 17"), ("1.8.0_402", "is Java 8")]
)
def test_a_jvm_with_a_release_file_is_checked_without_starting_its_java(
    tmp_path, monkeypatch, release, reason
):
    """A JVM states its version in its `release` file (JAVA_VERSION="21.0.13.0.3" in this machine's
    /usr/lib/jvm/java-21-openjdk-amd64/release). The router's check reads it and starts no java: a
    routing test module asks the check when it is imported, and a design file of tests/test_designfile.py
    imports that module inside `workcenter design`, in tests that start no engine (with a record of a
    real JVM, 4 of them failed the engine marker on this branch). The file wins over what java says."""
    env, paths = case(tmp_path, "both")
    jvm_home = paths["21"].parent.parent
    (jvm_home / "release").write_text(f'IMPLEMENTOR="x"\nJAVA_VERSION="{release}"\n', encoding="utf-8")
    routers_env(monkeypatch, env, tmp_path)
    why = routers.get(routers.DEFAULT).absent()
    assert (why == "") if not reason else (reason in why), why
    assert "java21" not in called(paths), called(paths)


def test_no_test_decides_on_the_first_java_on_path():
    """A routing test skips on the same pick as the product (routers.workcenter_java, through the
    router's absent()), not on `shutil.which("java")`: in run 44515796762 the tests saw a java on PATH,
    did not skip, and ran a java the product picked elsewhere."""
    found = [
        f"{p.name}:{n}"
        for p in sorted((ROOT / "tests").glob("*.py"))
        for n, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1)
        if 'which("java")' in ln and p.name != Path(__file__).name
    ]
    assert found == []
