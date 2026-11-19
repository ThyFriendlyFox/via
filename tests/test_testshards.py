"""`verify/testshards.py`: the health gate's tests in several processes, joined into 1 verdict.

The split and the join are judged on tables and logs written here. The runs start pytest on small test
folders written in tmp_path: no engine runs, and none of the repository's own tests.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from conftest import no_home

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "verify"))
import testshards  # noqa: E402

TABLE = """file,seconds,engine,alone
*,30,yes,
tests/test_a.py,10,yes,
tests/test_b.py,7,no,
tests/test_c.py,6,yes,
tests/test_d.py,5,no,
"""


def table(tmp_path: Path, text: str = TABLE) -> Path:
    path = tmp_path / "shards.csv"
    path.write_text(text, encoding="utf-8")
    return path


def test_each_file_goes_to_the_shard_with_the_least_time(tmp_path):
    """Longest first, each onto the lighter shard: a 10 -> 1 (10), b 7 -> 2 (7), c 6 -> 2 (7 + 6 = 13),
    d 5 -> 1 (10 + 5 = 15). Shard 1 holds a and d, 15 s; shard 2 holds b and c, 13 s."""
    files = ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py", "tests/test_d.py"]
    shards = testshards.plan(files, testshards.read_table(table(tmp_path)), jobs=2)
    assert [(s.name, sorted(s.files), s.seconds) for s in shards] == [
        ("1", ["tests/test_a.py", "tests/test_d.py"], 15.0),
        ("2", ["tests/test_b.py", "tests/test_c.py"], 13.0),
    ]


def test_a_file_the_table_does_not_know_takes_the_default_and_is_named(tmp_path):
    """The `*` row says 30 s. With 1 shard: 10 + 30 = 40 s, and the plan names the new file."""
    shards = testshards.plan(
        ["tests/test_a.py", "tests/test_new.py"], testshards.read_table(table(tmp_path)), jobs=1
    )
    assert shards[0].seconds == 40.0
    assert shards[0].unknown == ["tests/test_new.py"]


def test_a_table_with_no_default_row_is_refused(tmp_path):
    with pytest.raises(ValueError, match=r"no `\*` row"):
        testshards.read_table(table(tmp_path, "file,seconds,engine,alone\ntests/test_a.py,1,no,\n"))


def test_a_file_that_must_run_alone_goes_to_the_serial_shard_with_its_reason(tmp_path):
    text = TABLE + "tests/test_e.py,4,yes,holds the port 8080\n"
    shards = testshards.plan(
        ["tests/test_a.py", "tests/test_e.py"], testshards.read_table(table(tmp_path, text)), jobs=2
    )
    serial = [s for s in shards if s.serial]
    assert [(s.name, s.files) for s in serial] == [("serial", ["tests/test_e.py"])]
    assert serial[0].reasons == {"tests/test_e.py": "holds the port 8080"}
    assert all("tests/test_e.py" not in s.files for s in shards if not s.serial)


def test_in_a_shard_the_files_with_no_engine_run_first(tmp_path):
    """1 shard of all 4: b and d have no engine, so they lead; a and c follow."""
    files = ["tests/test_a.py", "tests/test_b.py", "tests/test_c.py", "tests/test_d.py"]
    (shard,) = testshards.plan(files, testshards.read_table(table(tmp_path)), jobs=1)
    assert set(shard.files[:2]) == {"tests/test_b.py", "tests/test_d.py"}
    assert set(shard.files[2:]) == {"tests/test_a.py", "tests/test_c.py"}


@pytest.mark.parametrize(
    "line",
    [
        "1658 passed, 1 skipped, 1 warning in 1290.61s (0:21:30)",
        "1 failed, 2 passed in 0.50s",
        "===== 3 passed in 0.12s =====",
        "no tests ran in 0.01s",
    ],
)
def test_a_summary_line_is_found(line):
    assert testshards.summary_line(f"....\n{line}\n") == line.strip("= ")


def test_a_log_cut_off_has_no_summary_line():
    assert testshards.summary_line("........................ [ 40%]\n.......") is None


def test_the_join_names_ids_missing_extra_and_run_twice():
    """Collected a, b, c. Shard 1 ran a and b, shard 2 ran b and x: c is missing, x was not collected,
    b ran 2 times."""
    missing, extra, twice = testshards.compare(["a", "b", "c"], {"1": ["a", "b"], "2": ["b", "x"]})
    assert (missing, extra, twice) == (["c"], ["x"], ["b"])


PASSING = "def test_one():\n    pass\n\n\ndef test_two():\n    pass\n"


def folder(tmp_path: Path, files: dict[str, str]) -> Path:
    """A project root with a tests/ folder of the given files and a table that knows each at 1 s."""
    root = tmp_path / "proj"
    (root / "tests").mkdir(parents=True)
    (root / "pytest.ini").write_text("[pytest]\ntestpaths = tests\n", encoding="utf-8")
    rows = ["file,seconds,engine,alone", "*,1,no,"]
    for name, text in files.items():
        (root / "tests" / name).write_text(text, encoding="utf-8")
        rows.append(f"tests/{name},1,no,")
    (root / "shards.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return root


def gate(root: Path, jobs: int = 2, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    args = ["run", "--root", str(root), "--table", str(root / "shards.csv"), "--jobs", str(jobs)]
    args += ["--python", sys.executable, "--work", str(root.parent / "work")]
    return subprocess.run(
        [sys.executable, str(ROOT / "verify" / "testshards.py"), *args],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env=env,
    )


FOUR = {f"test_{n}.py": PASSING for n in ("p", "q", "r", "s")}


def test_four_passing_files_in_2_shards_are_green_and_the_ids_match(tmp_path):
    """4 files of 2 tests: 8 ids collected in 1 process, 8 run across 2 shards of 2 files each."""
    proc = gate(folder(tmp_path, FOUR))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ids: 8 collected in 1 process, 8 run in 2 shards; 0 missing, 0 not collected, 0 run 2 times" in (
        proc.stdout
    )
    assert "TESTS GREEN" in proc.stdout


@pytest.mark.parametrize("shard", ["1", "2"])
def test_a_failing_test_in_either_shard_makes_the_gate_red(tmp_path, shard):
    """The plan puts each file in a shard; the failing test is planted in a file of the named shard."""
    root = folder(tmp_path, FOUR)
    shards = testshards.plan(
        sorted(f"tests/{n}" for n in FOUR), testshards.read_table(root / "shards.csv"), jobs=2
    )
    target = next(s for s in shards if s.name == shard).files[0]
    (root / target).write_text(PASSING + "\n\ndef test_planted():\n    assert 1 == 2\n", encoding="utf-8")
    proc = gate(root)
    assert proc.returncode == 1, proc.stdout
    assert re.search(rf"^FAILED {target}::test_planted \(shard {shard}\) at \d+ s$", proc.stdout, re.M)
    assert f"shard {shard}: exit 1" in proc.stdout
    assert "TESTS RED" in proc.stdout


def test_a_shard_killed_half_way_makes_the_gate_red(tmp_path):
    """The second test of the file kills its own pytest: the shard ends with no summary line, and the
    test after it is never run."""
    files = dict(FOUR)
    files["test_s.py"] = (
        "import os\nimport signal\n\n\ndef test_one():\n    pass\n\n\n"
        "def test_kill():\n    os.kill(os.getpid(), signal.SIGKILL)\n\n\ndef test_after():\n    pass\n"
    )
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 1, proc.stdout
    assert "no summary line" in proc.stdout
    assert "tests/test_s.py::test_after" in proc.stdout
    assert "TESTS RED" in proc.stdout


def test_a_test_the_shards_do_not_run_makes_the_gate_red(tmp_path):
    """The file defines a third test only outside a shard: 1 process collects 9 ids, the shards run 8."""
    files = dict(FOUR)
    files["test_s.py"] = PASSING + (
        "\n\nimport os\n\nif not os.environ.get('TESTSHARDS_SHARD'):\n\n"
        "    def test_only_alone():\n        pass\n"
    )
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 1, proc.stdout
    assert "ids: 9 collected in 1 process, 8 run in 2 shards; 1 missing" in proc.stdout
    assert "missing: tests/test_s.py::test_only_alone" in proc.stdout


def test_each_shard_has_its_own_kicad_configuration_and_temporary_folder(tmp_path):
    """2 shards: 2 KiCad configuration folders and 2 pytest base folders, none of them shared."""
    work = tmp_path / "work"
    envs = [testshards.shard_env(name, work, {}) for name in ("1", "2")]
    homes = {e["KICAD_CONFIG_HOME"] for e in envs}
    assert len(homes) == 2 and all(Path(h).is_relative_to(work) for h in homes)
    assert [e["TESTSHARDS_SHARD"] for e in envs] == ["1", "2"]
    args = [testshards.shard_args(name, work) for name in ("1", "2")]
    bases = {a[a.index("--basetemp") + 1] for a in args}
    assert len(bases) == 2 and all("-p" in a and "no:cacheprovider" in a for a in args)


def test_with_no_home_folder_known_the_shards_start_with_an_empty_kicad_configuration(tmp_path):
    """M299: HOME unset and a user id with no line in /etc/passwd (conftest.no_home), and no
    KICAD_CONFIG_HOME or XDG_CONFIG_HOME: there is no configuration to copy, and each shard starts
    with an empty folder of its own, as where ~/.config/kicad is not there."""
    root = folder(tmp_path, {"test_a.py": PASSING})
    env = {k: v for k, v in os.environ.items() if k not in ("KICAD_CONFIG_HOME", "XDG_CONFIG_HOME")}
    work = tmp_path / "work"
    args = ["run", "--root", root, "--table", root / "shards.csv", "--jobs", "1"]
    args += ["--python", sys.executable, "--work", work]
    ran = no_home(ROOT / "verify" / "testshards.py", *args, env=env, timeout=300)
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert "Traceback" not in ran.stdout + ran.stderr
    assert [p.name for p in work.glob("shard-*/kicad")] == ["kicad"]


def run_in_temp(root: Path, temp: Path) -> subprocess.CompletedProcess:
    """The gate with no --work: it makes its own folder under TMPDIR."""
    temp.mkdir()
    args = ["run", "--root", str(root), "--table", str(root / "shards.csv"), "--jobs", "2"]
    return subprocess.run(
        [sys.executable, str(ROOT / "verify" / "testshards.py"), *args, "--python", sys.executable],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
        env={**os.environ, "TMPDIR": str(temp)},
    )


def test_a_green_run_removes_its_own_folder_and_a_red_run_keeps_it(tmp_path):
    """A whole run of the gate left 607 MB of tmp_path folders (du, 2026-11-17); a green run deletes
    its folder, a red run keeps it for its logs and names it."""
    green = run_in_temp(folder(tmp_path / "g", FOUR), tmp_path / "tg")
    assert green.returncode == 0, green.stdout
    assert list((tmp_path / "tg").iterdir()) == []
    files = dict(FOUR)
    files["test_s.py"] = PASSING + "\n\ndef test_planted():\n    assert 1 == 2\n"
    red = run_in_temp(folder(tmp_path / "r", files), tmp_path / "tr")
    assert red.returncode == 1, red.stdout
    (kept,) = list((tmp_path / "tr").iterdir())
    assert f"logs kept: {kept}" in red.stdout


def shard_log(work: Path, shard: str, records: list[tuple[str, str, float]]) -> None:
    folder = work / f"shard-{shard}"
    folder.mkdir(parents=True)
    lines = [json.dumps({"id": i, "when": w, "outcome": "passed", "seconds": s}) for i, w, s in records]
    (folder / "log.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_the_table_is_written_from_the_logs_of_runs(tmp_path):
    """Run 1: a's test takes 1.0 + 2.0 + 0.5 = 3.5 s, b's 1.0 s. Run 2: a's takes 4.5 s, b is not run.
    a: (3.5 + 4.5) / 2 = 4.0 s; b: 1.0 s, its 1 run. `*`: (4.0 + 1.0) / 2 = 2.5 s. a and the `*` row keep
    their engine and alone columns; b, new to the table, takes the `*` row's engine."""
    one, two = tmp_path / "w1", tmp_path / "w2"
    shard_log(one, "1", [("tests/test_a.py::t", "setup", 1.0), ("tests/test_a.py::t", "call", 2.0)])
    shard_log(one, "2", [("tests/test_a.py::t", "teardown", 0.5), ("tests/test_b.py::u", "call", 1.0)])
    shard_log(two, "1", [("tests/test_a.py::t", "call", 4.5)])
    old = table(tmp_path, "file,seconds,engine,alone\n*,30,yes,\ntests/test_a.py,10,no,holds a port\n")
    rows = testshards.table_rows(testshards.read_table(old), [one, two])
    assert rows == [
        "file,seconds,engine,alone",
        "*,2.5,yes,",
        "tests/test_a.py,4.0,no,holds a port",
        "tests/test_b.py,1.0,yes,",
    ]


def test_the_gate_prints_each_shards_time_and_the_slowest_files(tmp_path):
    proc = gate(folder(tmp_path, FOUR))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for name in ("1", "2"):
        assert f"shard {name}: exit 0," in proc.stdout
    assert "slowest files:" in proc.stdout
    assert os.path.join("tests", "test_p.py") in proc.stdout


def red_line(stdout: str) -> str:
    (line,) = [line for line in stdout.splitlines() if line.startswith("TESTS RED: ")]
    return line


# -- each red condition of the join, end to end: removing the condition turns its test green -------------


def test_a_shard_that_exits_0_before_the_end_of_its_session_makes_the_gate_red(tmp_path):
    """The last test of test_s.py ends its pytest with os._exit(0): the shard exits 0, every id has its
    setup record, and only the missing end of session says that the shard was cut short."""
    files = dict(FOUR)
    files["test_s.py"] = PASSING + "\n\nimport os\n\n\ndef test_zz_ends_the_process():\n    os._exit(0)\n"
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 1, proc.stdout
    assert re.search(r"^shard \d: exit 0, ", proc.stdout, re.M)
    assert re.search(r"shard \d ended before pytest's end of session", red_line(proc.stdout))


def test_an_id_a_shard_runs_and_1_process_does_not_collect_makes_the_gate_red(tmp_path):
    """test_s.py defines a third test only inside a shard: 4 x 2 = 8 ids collected, 8 + 1 = 9 run, 1 not
    collected."""
    files = dict(FOUR)
    files["test_s.py"] = PASSING + (
        "\n\nimport os\n\nif os.environ.get('TESTSHARDS_SHARD'):\n\n"
        "    def test_only_in_a_shard():\n        pass\n"
    )
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 1, proc.stdout
    assert "ids: 8 collected in 1 process, 9 run in 2 shards; 0 missing, 1 not collected" in proc.stdout
    assert "not collected: tests/test_s.py::test_only_in_a_shard" in proc.stdout
    assert "the shards' ids are not the ids 1 process collects" in red_line(proc.stdout)


def test_an_id_run_2_times_makes_the_gate_red(tmp_path):
    """A test of test_s.py writes a second setup record for tests/test_p.py::test_one into its shard's
    log: 3 files of 2 tests and test_s.py with 3 give 6 + 3 = 9 ids collected, 9 + 1 = 10 records of a
    run, 1 id run 2 times."""
    files = dict(FOUR)
    files["test_s.py"] = PASSING + (
        "\n\nimport json\nimport os\n\n\ndef test_writes_a_second_record():\n"
        "    with open(os.environ['TESTSHARDS_LOG'], 'a', encoding='utf-8') as fh:\n"
        "        rec = {'id': 'tests/test_p.py::test_one', 'when': 'setup', 'outcome': 'passed',\n"
        "               'seconds': 0}\n"
        "        fh.write(json.dumps(rec) + '\\n')\n"
    )
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 1, proc.stdout
    assert "ids: 9 collected in 1 process, 10 run in 2 shards; 0 missing, 0 not collected, 1 run 2 times" in (
        proc.stdout
    )
    assert "run 2 times: tests/test_p.py::test_one" in proc.stdout
    assert "the shards' ids are not the ids 1 process collects" in red_line(proc.stdout)


def test_a_collection_that_fails_in_1_process_makes_the_gate_red(tmp_path):
    """test_s.py raises as it is imported outside a shard: pytest --collect-only exits 2 (an error in
    collection), whatever the shards do."""
    files = dict(FOUR)
    files["test_s.py"] = (
        "import os\n\nif not os.environ.get('TESTSHARDS_SHARD'):\n    raise RuntimeError('no')\n\n"
    )
    files["test_s.py"] += PASSING
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 1, proc.stdout
    assert "the collection in 1 process exited 2" in red_line(proc.stdout)


# -- the same verdict: a skip or an xfail that only a shard's environment gives -----------------------------


def test_a_test_skipped_by_its_mark_only_in_a_shard_makes_the_gate_red(tmp_path):
    """The skipif condition holds in a shard (TESTSHARDS_SHARD is set there) and not in 1 process, where
    the test fails. 3 files of 2 passing tests and test_s.py with 2 passing and the skipped one: 9 ids,
    8 passed and 1 skipped."""
    files = dict(FOUR)
    files["test_s.py"] = PASSING + (
        "\n\nimport os\n\nimport pytest\n\n\n"
        "@pytest.mark.skipif('TESTSHARDS_SHARD' in os.environ, reason='in a shard')\n"
        "def test_fails_in_1_process():\n    assert 1 == 2\n"
    )
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 1, proc.stdout
    assert "outcomes: 8 passed, 0 failed, 1 skipped, 0 xfailed, 0 xpassed" in proc.stdout
    assert re.search(
        r"^  marks differ: tests/test_s\.py::test_fails_in_1_process: skip 'in a shard' in shard \d, "
        r"none in 1 process$",
        proc.stdout,
        re.M,
    )
    assert "1 test whose skip or xfail marks differ between a shard and 1 process" in red_line(proc.stdout)


def test_a_test_that_skips_itself_is_named_not_judged(tmp_path):
    """pytest.skip() inside the test: what 1 process would do there is not known without running it. The
    gate stays green on the 8 tests it judged and names the 1 it did not."""
    files = dict(FOUR)
    files["test_s.py"] = PASSING + (
        "\n\nimport pytest\n\n\ndef test_skips_itself():\n    pytest.skip('no board here')\n"
    )
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 0, proc.stdout
    assert re.search(
        r"^  not judged: tests/test_s\.py::test_skips_itself: skipped inside the test in shard \d "
        r"\('no board here'\); 1 process did not run it$",
        proc.stdout,
        re.M,
    )
    assert "TESTS GREEN: 9 tests in 2 shards; 1 not judged (skipped inside the test)" in proc.stdout


# -- a stop by signal ends every shard ---------------------------------------------------------------------

WAITS = (
    "import os\nimport time\nfrom pathlib import Path\n\n\ndef test_waits():\n"
    "    Path(os.environ['SHARD_PIDS'], str(os.getpid())).touch()\n    time.sleep(60)\n"
)


def running(pid: int) -> bool:
    """A process that exists and is not a zombie (its state in /proc/<pid>/stat, after the name). A
    process reaped between the file's open and its read makes the read fail with ESRCH: not running."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except (FileNotFoundError, ProcessLookupError):
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGHUP], ids=["TERM", "HUP"])
def test_a_stop_by_signal_ends_every_shard(tmp_path, sig):
    """2 files of 1 test that waits 60 s, in 2 shards. The signal goes to the runner's process group, as
    `lead/gate-and-push.sh` stops make: the runner exits 128 + the signal (143 for TERM, 129 for HUP) and
    no shard's pytest is left."""
    root = folder(tmp_path, {"test_x.py": WAITS, "test_y.py": WAITS})
    pids = tmp_path / "pids"
    pids.mkdir()
    args = ["run", "--root", str(root), "--table", str(root / "shards.csv"), "--jobs", "2"]
    args += ["--python", sys.executable, "--work", str(tmp_path / "work")]
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "verify" / "testshards.py"), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "SHARD_PIDS": str(pids)},
        start_new_session=True,
    )
    try:
        deadline = time.monotonic() + 60
        while len(list(pids.iterdir())) < 2:
            assert time.monotonic() < deadline and proc.poll() is None, "the 2 shards did not start"
            time.sleep(0.1)
        os.killpg(proc.pid, sig)
        out, _ = proc.communicate(timeout=30)
        left = [int(p.name) for p in pids.iterdir() if running(int(p.name))]
        assert left == [], out
        assert proc.returncode == 128 + sig, out
        assert f"stopped by signal {int(sig)}: 3 pytest processes started, none left running" in out
        # A stop is often a CI time limit on a test that hangs: each shard names the test it was running.
        for name in ("test_x.py", "test_y.py"):
            shard = shard_of(root, name)
            assert f"why: shard {shard} was running tests/{name}::test_waits when stopped" in out, out
    finally:
        for p in pids.iterdir():
            try:
                os.kill(int(p.name), signal.SIGKILL)
            except ProcessLookupError:
                pass
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


# -- the engine lock that `make verify` holds ------------------------------------------------------------

LOCK = ROOT / "tools" / "enginelock.py"

# A test in a shard: the gate's lock lets it through, and a long command it starts runs at once.
INSIDE_THE_LOCK = (
    "import os\nimport subprocess\nimport sys\n\nLOCK = os.environ['LOCK_TOOL']\n\n\n"
    "def test_held():\n"
    "    assert subprocess.run([sys.executable, LOCK, 'held']).returncode == 0\n\n\n"
    "def test_a_long_command_runs_at_once():\n"
    "    argv = [sys.executable, LOCK, 'hold', '--what', 'engine', '--', sys.executable, '-c', 'pass']\n"
    "    run = subprocess.run(argv, capture_output=True, text=True, timeout=30)\n"
    "    assert run.returncode == 0 and 'waiting' not in run.stderr, run.stderr\n"
)


def under_the_lock(tmp_path: Path, root: Path) -> list[str]:
    """`testshards.py run` started as verify/verify.sh starts it: under `enginelock.py hold --what "make
    verify"`, in a lock folder of the test's own."""
    args = ["run", "--root", str(root), "--table", str(root / "shards.csv"), "--jobs", "2"]
    args += ["--python", sys.executable, "--work", str(tmp_path / "work")]
    hold = [sys.executable, str(LOCK), "hold", "--what", "make verify", "--"]
    return [*hold, sys.executable, str(ROOT / "verify" / "testshards.py"), *args]


def lock_env(tmp_path: Path) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("WORKCENTER_LOCK")}
    return {**env, "WORKCENTER_LOCK_DIR": str(tmp_path / "lock"), "LOCK_TOOL": str(LOCK)}


def test_the_shards_of_a_gate_that_holds_the_engine_lock_never_wait_for_it(tmp_path):
    """`make verify` holds the engine lock to its end, and each shard's tests start long `workcenter`
    commands. A shard runs in its own session, and is still a child of the holder: the lock lets it
    through. 2 files in 2 shards each ask `held` and run a command under `hold`: 4 passed, no waiting
    line, in well under the 30 s a wait would take each."""
    root = folder(tmp_path, {"test_x.py": INSIDE_THE_LOCK, "test_y.py": INSIDE_THE_LOCK})
    proc = subprocess.run(
        under_the_lock(tmp_path, root),
        capture_output=True,
        text=True,
        timeout=120,
        env=lock_env(tmp_path),
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "ids: 4 collected in 1 process, 4 run in 2 shards; 0 missing" in proc.stdout
    assert "waiting" not in proc.stdout + proc.stderr


def test_a_stop_by_signal_to_the_holders_group_ends_every_shard(tmp_path):
    """`lead/gate-and-push.sh` starts make with setsid and stops it with TERM to that process group:
    `enginelock.py hold`, verify.sh and the runner get the signal, the shards (each in its own session)
    do not. The runner ends them: no shard's pytest is left, and the hold dies of the signal.
    The hold passes its TERM on to the runner too, so the runner gets 2. It ends and waits for every
    shard before it exits, so once the output has ended no shard's pid is in /proc, not even a dead one
    that another process has yet to reap: nothing is left to wait for."""
    root = folder(tmp_path, {"test_x.py": WAITS, "test_y.py": WAITS})
    pids = tmp_path / "pids"
    pids.mkdir()
    proc = subprocess.Popen(
        under_the_lock(tmp_path, root),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**lock_env(tmp_path), "SHARD_PIDS": str(pids)},
        start_new_session=True,
    )
    try:
        # The hold leads its own group from the start (setsid runs before exec), and each shard has
        # written its pid, so the runner has its handlers set and both shards are up.
        assert os.getpgid(proc.pid) == proc.pid
        deadline = time.monotonic() + 60
        while len(list(pids.iterdir())) < 2:
            assert time.monotonic() < deadline and proc.poll() is None, "the 2 shards did not start"
            time.sleep(0.1)
        os.killpg(proc.pid, signal.SIGTERM)
        out, _ = proc.communicate(timeout=30)
        left = [p.name for p in pids.iterdir() if Path(f"/proc/{p.name}").exists()]
        assert left == [], out
        assert "stopped by signal 15: 3 pytest processes started, none left running" in out, out
        assert proc.returncode == -signal.SIGTERM, out
    finally:
        for p in pids.iterdir():
            try:
                os.kill(int(p.name), signal.SIGKILL)
            except ProcessLookupError:
                pass
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()


def test_a_stop_signal_during_the_clean_up_does_not_cut_it_short(tmp_path):
    """Under `enginelock.py hold` the runner gets 2 TERMs: 1 sent to the group and 1 the hold passes on,
    milliseconds apart. The second must not end the clean-up that the first began. TERM goes to the
    runner again and again until it exits: it still prints its stop line, and it waits for each shard
    before it exits, so no shard's pid is in /proc after it, not even a dead one not yet reaped."""
    root = folder(tmp_path, {"test_x.py": WAITS, "test_y.py": WAITS})
    pids = tmp_path / "pids"
    pids.mkdir()
    args = ["run", "--root", str(root), "--table", str(root / "shards.csv"), "--jobs", "2"]
    args += ["--python", sys.executable, "--work", str(tmp_path / "work")]
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "verify" / "testshards.py"), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "SHARD_PIDS": str(pids)},
    )
    try:
        deadline = time.monotonic() + 60
        while len(list(pids.iterdir())) < 2:
            assert time.monotonic() < deadline and proc.poll() is None, "the 2 shards did not start"
            time.sleep(0.1)
        # The runner kills its shards (each sleeps 60 s) and waits for them, so it exits in well under
        # 30 s. A runner that hangs, or that waits for shards it did not kill, fails here, not by a
        # timeout outside the test; the finally then kills it with SIGKILL, which it cannot ignore.
        deadline = time.monotonic() + 30
        while proc.poll() is None:
            assert time.monotonic() < deadline, "the runner did not exit within 30 s of repeated TERM"
            proc.send_signal(signal.SIGTERM)
            time.sleep(0.001)
        out = proc.stdout.read()
        left = [p.name for p in pids.iterdir() if Path(f"/proc/{p.name}").exists()]
        assert left == [], out
        assert "stopped by signal 15: 3 pytest processes started, none left running" in out, out
    finally:
        for p in pids.iterdir():
            try:
                os.kill(int(p.name), signal.SIGKILL)
            except ProcessLookupError:
                pass
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        proc.stdout.close()


def test_the_clean_up_kills_and_waits_for_every_shard_whoever_reaps_orphans():
    """The 2 stop tests above see a shard left unwaited only while it stays in /proc. Where a reaper
    takes orphans at once (a CI runner's init, a child subreaper), a runner that skipped the wait could
    pass them. Here the test itself is each child's parent, so no other process can reap it: `end_all`
    must kill each one's group and wait for it. 3 children that sleep 60 s, each in its own session as a
    shard is, and 1 that has already exited: each has a return code after, and the 3 died of SIGKILL."""
    sleeper = [sys.executable, "-c", "import time; time.sleep(60)"]
    procs = [subprocess.Popen(sleeper, start_new_session=True) for _ in range(3)]
    done = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
    done.wait()
    procs.insert(1, done)
    try:
        ended = threading.Thread(target=testshards.end_all, args=(procs,), daemon=True)
        ended.start()
        ended.join(timeout=30)
        assert not ended.is_alive(), "end_all did not return within 30 s: a shard was not killed"
        assert [p.returncode for p in procs] == [-signal.SIGKILL, 0, -signal.SIGKILL, -signal.SIGKILL]
    finally:
        for p in procs:
            if p.returncode is None:
                p.kill()
                p.wait()


# -- the work folder and the table ----------------------------------------------------------------------


def test_a_work_folder_with_the_logs_of_an_earlier_run_is_refused(tmp_path):
    """The first run is green; the second, into the same folder, would join the first run's ids with
    its own (8 ids twice): it is refused with exit 2 and the folder is named."""
    root = folder(tmp_path, FOUR)
    assert gate(root).returncode == 0
    again = gate(root)
    assert again.returncode == 2, again.stdout
    work = root.parent / "work"
    assert f"--work {work} holds the logs of an earlier run" in again.stderr
    assert "Traceback" not in again.stderr


@pytest.mark.parametrize(
    ("text", "where", "message"),
    [
        ("file,seconds,engine,alone\n*,1,no,\ntests/test_a.py,abc,no,\n", 3, "seconds is 'abc'"),
        ("file,seconds,engine,alone\n*,1,no,\ntests/test_a.py,-500,no,\n", 3, "seconds is '-500'"),
        ("file,seconds,engine,alone\n*,nan,no,\n", 2, "seconds is 'nan'"),
        ("file,engine,alone\n*,no,\n", 1, "no column seconds"),
        ("name,seconds,engine,alone\n*,1,no,\n", 1, "no column file"),
        ("", 1, "no header"),
    ],
    ids=["words", "negative", "nan", "no-seconds", "no-file", "empty"],
)
def test_a_wrong_table_is_refused_with_its_line_and_no_traceback(tmp_path, capsys, text, where, message):
    path = table(tmp_path, text)
    (tmp_path / "w").mkdir()
    assert testshards.main(["table", "--table", str(path), str(tmp_path / "w")]) == 2
    err = capsys.readouterr().err
    assert err.startswith(f"{path}:{where}: {message}"), err


# -- why a test failed: what pytest reported, in the gate's own output ----------------------------------
#
# CI run 44409635104 named its failed test and kept the report in a folder nobody could read after the
# run (inside the image it went with the container). The gate prints each report, bounded.


def reason(stdout: str, header: str) -> list[str]:
    """The lines of the reason block whose header line is `header`: the `  | ` lines under it."""
    lines = stdout.splitlines()
    at = lines.index(header)
    block = []
    for line in lines[at + 1 :]:
        if not line.startswith("  | "):
            break
        block.append(line[4:])
    return block


def shard_of(root: Path, name: str, jobs: int = 2) -> str:
    shards = testshards.plan(
        sorted(f"tests/{p.name}" for p in (root / "tests").glob("test_*.py")),
        testshards.read_table(root / "shards.csv"),
        jobs=jobs,
    )
    return next(s.name for s in shards if f"tests/{name}" in s.files)


def test_a_failing_assertions_message_its_line_and_its_output_are_in_the_gates_output(tmp_path):
    """The assertion's message, the line that raised it (tests/test_s.py:12) and what the test printed
    before it failed, under the FAILED line that existed before."""
    files = dict(FOUR)
    files["test_s.py"] = PASSING + (
        "\n\ndef test_planted():\n    print('the divider gave 3.1 V')\n    x = 3\n"
        "    assert x == 2, 'the planted message'\n"
    )
    root = folder(tmp_path, files)
    shard = shard_of(root, "test_s.py")
    proc = gate(root)
    assert proc.returncode == 1, proc.stdout
    failed = rf"^FAILED tests/test_s\.py::test_planted \(shard {shard}\) at \d+ s$"
    assert re.search(failed, proc.stdout, re.M)
    block = reason(proc.stdout, f"why: tests/test_s.py::test_planted, failed at call (shard {shard}):")
    assert "E       AssertionError: the planted message" in block, proc.stdout
    assert "tests/test_s.py:12: AssertionError" in block, proc.stdout
    assert ">       assert x == 2, 'the planted message'" in block, proc.stdout
    assert "the divider gave 3.1 V" in block, proc.stdout


def test_an_error_at_setup_and_an_error_at_teardown_after_a_pass_are_each_in_the_gates_output(tmp_path):
    """A fixture that raises before the test, and one that raises after a test that passed: pytest
    calls both errors, and the second test's call passed."""
    files = dict(FOUR)
    files["test_s.py"] = PASSING + (
        "\n\nimport pytest\n\n\n@pytest.fixture\ndef board():\n"
        "    raise RuntimeError('no board at setup')\n\n\n"
        "@pytest.fixture\ndef engine():\n    yield 1\n"
        "    raise RuntimeError('the engine did not close')\n\n\n"
        "def test_needs_board(board):\n    pass\n\n\n"
        "def test_passes_then_errors(engine):\n    assert engine == 1\n"
    )
    root = folder(tmp_path, files)
    shard = shard_of(root, "test_s.py")
    proc = gate(root)
    assert proc.returncode == 1, proc.stdout
    setup = reason(proc.stdout, f"why: tests/test_s.py::test_needs_board, an error at setup (shard {shard}):")
    assert "E       RuntimeError: no board at setup" in setup, proc.stdout
    down = f"why: tests/test_s.py::test_passes_then_errors, an error at teardown (shard {shard}):"
    assert "E       RuntimeError: the engine did not close" in reason(proc.stdout, down), proc.stdout


def test_an_error_at_collection_is_in_the_gates_output_once(tmp_path):
    """test_s.py raises as it is imported, in its shard and in 1 process: its shard stops with exit 2
    and runs nothing. The reason is printed once, from the shard."""
    files = dict(FOUR)
    files["test_s.py"] = "raise RuntimeError('cannot import the board')\n"
    root = folder(tmp_path, files)
    shard = shard_of(root, "test_s.py")
    proc = gate(root)
    assert proc.returncode == 1, proc.stdout
    block = reason(proc.stdout, f"why: tests/test_s.py could not be collected (shard {shard}):")
    assert any("RuntimeError: cannot import the board" in line for line in block), proc.stdout
    assert proc.stdout.count("could not be collected") == 1, proc.stdout


def test_an_error_at_collection_in_1_process_alone_is_in_the_gates_output(tmp_path):
    """test_s.py raises as it is imported outside a shard: only the collection in 1 process has it."""
    files = dict(FOUR)
    files["test_s.py"] = (
        "import os\n\nif not os.environ.get('TESTSHARDS_SHARD'):\n    raise RuntimeError('not here')\n\n"
    ) + PASSING
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 1, proc.stdout
    block = reason(proc.stdout, "why: tests/test_s.py could not be collected (the collection in 1 process):")
    assert any("RuntimeError: not here" in line for line in block), proc.stdout


def test_a_shard_killed_mid_run_names_the_test_it_was_running_and_the_end_of_its_output(tmp_path):
    """The test kills its own pytest with SIGKILL: no report, no end of session. The gate names the test
    the shard started last and did not end, and the last lines of the shard's output."""
    files = dict(FOUR)
    files["test_s.py"] = (
        "import os\nimport signal\n\n\ndef test_one():\n    pass\n\n\n"
        "def test_kill():\n    os.kill(os.getpid(), signal.SIGKILL)\n\n\ndef test_after():\n    pass\n"
    )
    root = folder(tmp_path, files)
    shard = shard_of(root, "test_s.py")
    proc = gate(root)
    assert proc.returncode == 1, proc.stdout
    log = root.parent / "work" / f"shard-{shard}" / "pytest.log"
    header = (
        f"why: shard {shard} ended with no report from pytest (exit -9, killed by signal 9); "
        f"the test it started last and did not end: tests/test_s.py::test_kill; "
        f"the last lines of its output, {log}:"
    )
    assert header in proc.stdout.splitlines(), proc.stdout


def test_a_shard_that_crashes_shows_the_crash_from_the_end_of_its_output(tmp_path):
    """A segmentation fault in a test: pytest's faulthandler writes the Python stack to the shard's
    output as the process dies, and the gate prints that end of the output."""
    files = dict(FOUR)
    files["test_s.py"] = (
        "import os\nimport signal\n\n\ndef test_one():\n    pass\n\n\n"
        "def test_crash():\n    os.kill(os.getpid(), signal.SIGSEGV)\n"
    )
    root = folder(tmp_path, files)
    shard = shard_of(root, "test_s.py")
    proc = gate(root)
    assert proc.returncode == 1, proc.stdout
    (header,) = [line for line in proc.stdout.splitlines() if line.startswith(f"why: shard {shard} ended")]
    assert "the test it started last and did not end: tests/test_s.py::test_crash" in header
    block = reason(proc.stdout, header)
    assert "Fatal Python error: Segmentation fault" in block, proc.stdout
    assert any('test_s.py", line 10 in test_crash' in line for line in block), proc.stdout


def test_a_shard_that_exits_non_zero_with_no_failed_test_shows_the_end_of_its_output(tmp_path):
    """test_q.py holds no test: its shard reaches its end of session and exits 5 (pytest's `no tests
    collected`), with no failure to show. The gate prints the end of its output."""
    root = folder(tmp_path, {"test_p.py": PASSING, "test_q.py": "VALUE = 1\n"})
    shard = shard_of(root, "test_q.py")
    proc = gate(root)
    assert proc.returncode == 1, proc.stdout
    log = root.parent / "work" / f"shard-{shard}" / "pytest.log"
    header = (
        f"why: shard {shard} exited 5 and no test failed; it ended no test; "
        f"the last lines of its output, {log}:"
    )
    assert any("no tests ran" in line for line in reason(proc.stdout, header)), proc.stdout


def test_many_failures_are_cut_at_the_bound_with_the_count_that_was_cut(tmp_path):
    """25 failing tests: 25 FAILED lines, the reasons of the first testshards.REASONS (10), and 1 line
    that says 25 - 10 = 15 were not printed and where the whole reports are."""
    files = dict(FOUR)
    files["test_s.py"] = (
        "import pytest\n\n\n@pytest.mark.parametrize('n', range(25))\n"
        "def test_planted(n):\n    assert n < 0\n"
    )
    root = folder(tmp_path, files)
    proc = gate(root)
    assert proc.returncode == 1, proc.stdout
    assert len(re.findall(r"^FAILED tests/test_s\.py::test_planted\[\d+\]", proc.stdout, re.M)) == 25
    assert testshards.REASONS == 10
    assert len(re.findall(r"^why: tests/test_s\.py::test_planted\[\d+\]", proc.stdout, re.M)) == 10
    work = root.parent / "work"
    assert (
        f"why: 15 more failed tests' reports are not printed here (the gate prints the first 10); "
        f"each shard's whole report is its pytest.log under {work}"
    ) in proc.stdout.splitlines(), proc.stdout
    assert proc.stdout.splitlines()[-2].startswith("TESTS RED: "), proc.stdout


def test_a_long_report_is_cut_to_its_first_and_last_lines_and_a_long_line_to_its_width(tmp_path):
    """A failure 80 calls deep, with a message of 1000 characters: the block keeps the first
    testshards.HEAD lines and the last testshards.TAIL, and says how many lines it cut; a line keeps
    testshards.WIDTH characters and says how many it cut."""
    files = dict(FOUR)
    files["test_s.py"] = (
        "def deep(n):\n    if n == 0:\n        raise ValueError('x' * 1000)\n    deep(n - 1)\n\n\n"
        "def test_deep():\n    deep(80)\n"
    )
    root = folder(tmp_path, files)
    shard = shard_of(root, "test_s.py")
    proc = gate(root)
    assert proc.returncode == 1, proc.stdout
    block = reason(proc.stdout, f"why: tests/test_s.py::test_deep, failed at call (shard {shard}):")
    assert len(block) == testshards.HEAD + 1 + testshards.TAIL, proc.stdout
    assert re.fullmatch(r"\[\.\.\. \d+ lines cut here\]", block[testshards.HEAD]), block
    assert "tests/test_s.py:3: ValueError" in block, block
    (long,) = [line for line in block if "xxxxxxxxxx" in line]
    assert re.fullmatch(rf".{{{testshards.WIDTH}}} \[\.\.\. \d+ characters cut\]", long), long


def test_a_report_that_holds_a_lone_surrogate_leaves_the_verdict_under_a_strict_stdout(tmp_path):
    """A string decoded with surrogateescape: pytest's diff prints its lone surrogate as it is. The gate's
    stdout is strict UTF-8, as Python's is under a full UTF-8 locale such as en_US.UTF-8. The reason is
    printed with the surrogate escaped, and the verdict follows."""
    files = dict(FOUR)
    files["test_s.py"] = PASSING + (
        "\n\ndef test_surrogate():\n"
        "    s = b'\\xff'.decode('utf-8', 'surrogateescape')\n    assert s == 'x'\n"
    )
    root = folder(tmp_path, files)
    shard = shard_of(root, "test_s.py")
    proc = gate(root, env={**os.environ, "PYTHONIOENCODING": "utf-8:strict"})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    block = reason(proc.stdout, f"why: tests/test_s.py::test_surrogate, failed at call (shard {shard}):")
    assert "E         + \\udcff" in block, proc.stdout
    assert "Traceback" not in proc.stderr, proc.stderr
    assert proc.stdout.splitlines()[-2].startswith("TESTS RED: "), proc.stdout


def test_a_green_run_prints_no_reason(tmp_path):
    """4 files that pass, 1 of them printing on stdout: no `why:` line and no `  | ` line."""
    files = dict(FOUR)
    files["test_s.py"] = PASSING + "\n\ndef test_says():\n    print('fine')\n"
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 0, proc.stdout
    assert not re.search(r"^(why|  \| )", proc.stdout, re.M), proc.stdout


def test_output_after_the_summary_line_leaves_a_green_shard_green(tmp_path):
    """A passing test registers a line that the interpreter prints to stderr as it ends, after pytest's
    summary. 1 process is green on it (exit 0); so are the shards."""
    files = dict(FOUR)
    files["test_s.py"] = PASSING + (
        "\n\nimport atexit\nimport sys\n\n\ndef test_says_goodbye():\n"
        "    atexit.register(lambda: print('closing the engine pool', file=sys.stderr))\n"
    )
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 0, proc.stdout
    assert "TESTS GREEN: 9 tests in 2 shards" in proc.stdout


# -- the tests a mark skips for the machine: named in groups by reason, the whole list in a file ----------
#
# On 2026-11-19 a test that needs root was skipped by its mark on GitHub and failed wherever it ran (M307).
# The run named only the 3 tests that skip inside themselves, not the 66 a mark skipped.


def not_judged(stdout: str) -> list[str]:
    return [line for line in stdout.splitlines() if line.startswith("  not judged: ")]


def skipped_by(reason: str, names: list[str], condition: str = "True") -> str:
    """A test file whose tests a skipif mark skips when `condition` holds, with that reason."""
    text = "import pytest\n"
    for name in names:
        text += f"\n\n@pytest.mark.skipif({condition}, reason={reason!r})\ndef {name}():\n    pass\n"
    return text


def test_a_mark_whose_condition_is_false_names_nothing(tmp_path):
    """The mark's condition is false: the test runs and passes, and no `not judged:` line, no file."""
    files = dict(FOUR)
    files["test_s.py"] = skipped_by("never here", ["test_runs"], condition="False")
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 0, proc.stdout
    # test_p, test_q and test_r hold 2 tests each, test_s 1: 7.
    assert "outcomes: 7 passed, 0 failed, 0 skipped" in proc.stdout
    assert not_judged(proc.stdout) == [], proc.stdout
    assert not (tmp_path / "work" / testshards.NOT_JUDGED).exists()


def test_tests_a_mark_skips_are_named_in_groups_with_a_count_and_the_first_3_ids(tmp_path):
    """4 tests skipped for 1 reason, 1 for another: 2 lines, the larger group first, each with its count
    and at most 3 ids; then 1 line that names the file with all 5. The verdict stays green."""
    files = dict(FOUR)
    files["test_s.py"] = skipped_by("no chip folder", [f"test_c{n}" for n in range(1, 5)])
    files["test_t.py"] = skipped_by("not root", ["test_r1"])
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 0, proc.stdout
    listed = tmp_path / "work" / testshards.NOT_JUDGED
    assert not_judged(proc.stdout) == [
        "  not judged: 4 tests skipped by a mark on this machine ('no chip folder'): "
        "tests/test_s.py::test_c1, tests/test_s.py::test_c2, tests/test_s.py::test_c3, and 1 more",
        "  not judged: 1 test skipped by a mark on this machine ('not root'): tests/test_t.py::test_r1",
        f"  not judged: the whole list of 5 is in {listed}",
    ], proc.stdout
    # test_p, test_q and test_r hold 2 tests each: 6 + 4 + 1 = 11.
    assert (
        "TESTS GREEN: 11 tests in 2 shards; 5 not judged (skipped by a mark on this machine)" in proc.stdout
    )
    text = listed.read_text(encoding="utf-8")
    for n in range(1, 5):
        assert f"  tests/test_s.py::test_c{n}\n" in text
    assert "  tests/test_t.py::test_r1\n" in text


def test_a_test_that_skips_itself_keeps_its_line_and_is_in_the_file(tmp_path):
    """pytest.skip() inside the test keeps the line it had; it is in no mark's group, and the file holds
    it under its own heading."""
    files = dict(FOUR)
    files["test_s.py"] = PASSING + (
        "\n\nimport pytest\n\n\ndef test_skips_itself():\n    pytest.skip('no board here')\n"
    )
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 0, proc.stdout
    lines = not_judged(proc.stdout)
    listed = tmp_path / "work" / testshards.NOT_JUDGED
    assert len(lines) == 2, proc.stdout
    assert re.fullmatch(
        r"  not judged: tests/test_s\.py::test_skips_itself: skipped inside the test in shard \d "
        r"\('no board here'\); 1 process did not run it",
        lines[0],
    )
    assert lines[1] == f"  not judged: the whole list of 1 is in {listed}"
    assert "1 test skipped inside the test ('no board here'):\n  tests/test_s.py::test_skips_itself\n" in (
        listed.read_text(encoding="utf-8")
    )


def test_a_test_the_run_deselects_is_not_named(tmp_path):
    """`-m "not engine"` leaves a test out on purpose (the fast lane's own line says so): it is not
    collected, so its true skip mark is never evaluated, and no line names it."""
    files = dict(FOUR)
    files["test_s.py"] = (
        "import pytest\n\n\n@pytest.mark.engine\n@pytest.mark.skipif(True, reason='left out')\n"
        "def test_deselected():\n    pass\n"
    ) + PASSING
    root = folder(tmp_path, files)
    (root / "pytest.ini").write_text(
        '[pytest]\ntestpaths = tests\nmarkers =\n    engine: starts an engine\naddopts = -m "not engine"\n',
        encoding="utf-8",
    )
    proc = gate(root)
    assert proc.returncode == 0, proc.stdout
    # test_p, test_q, test_r and test_s hold 2 tests each that run: 8.
    assert "ids: 8 collected in 1 process, 8 run in 2 shards" in proc.stdout
    assert not_judged(proc.stdout) == [], proc.stdout
    assert "left out" not in proc.stdout


def test_a_run_with_no_skip_prints_no_line_and_leaves_no_folder(tmp_path):
    proc = gate(folder(tmp_path, FOUR))
    assert proc.returncode == 0, proc.stdout
    assert not_judged(proc.stdout) == [], proc.stdout
    assert "not judged" not in proc.stdout
    green = run_in_temp(folder(tmp_path / "g", FOUR), tmp_path / "tg")
    assert green.returncode == 0, green.stdout
    assert list((tmp_path / "tg").iterdir()) == []


def test_500_tests_skipped_for_1_reason_are_1_line_of_3_ids_and_the_file_holds_all_500(tmp_path):
    files = dict(FOUR)
    files["test_s.py"] = (
        "import pytest\n\n\n@pytest.mark.skipif(True, reason='no chip folder')\n"
        "@pytest.mark.parametrize('n', range(500))\ndef test_c(n):\n    pass\n"
    )
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 0, proc.stdout
    listed = tmp_path / "work" / testshards.NOT_JUDGED
    assert not_judged(proc.stdout) == [
        "  not judged: 500 tests skipped by a mark on this machine ('no chip folder'): "
        "tests/test_s.py::test_c[0], tests/test_s.py::test_c[1], tests/test_s.py::test_c[2], and 497 more",
        f"  not judged: the whole list of 500 is in {listed}",
    ], proc.stdout
    ids = [line[2:] for line in listed.read_text(encoding="utf-8").splitlines() if line.startswith("  ")]
    assert sorted(ids) == sorted(f"tests/test_s.py::test_c[{n}]" for n in range(500))


def test_a_reason_with_a_newline_is_1_line_and_a_long_reason_is_cut_in_the_summary_not_in_the_file(tmp_path):
    """A newline is printed as `\\n`, so the group is 1 line. A reason of 1000 characters keeps its first
    testshards.REASON_WIDTH in the summary and says how many it cut; the file holds it whole."""
    files = dict(FOUR)
    files["test_s.py"] = skipped_by("first line\nsecond line", ["test_newline"])
    files["test_t.py"] = skipped_by("y" * 1000, ["test_long"])
    proc = gate(folder(tmp_path, files))
    assert proc.returncode == 0, proc.stdout
    lines = not_judged(proc.stdout)
    assert (
        "  not judged: 1 test skipped by a mark on this machine ('first line\\nsecond line'): "
        "tests/test_s.py::test_newline"
    ) in lines, proc.stdout
    cut = 1000 - testshards.REASON_WIDTH
    (long,) = [line for line in lines if "yyy" in line]
    assert long == (
        f"  not judged: 1 test skipped by a mark on this machine ('{'y' * testshards.REASON_WIDTH}' "
        f"[... {cut} characters cut]): tests/test_t.py::test_long"
    )
    text = (tmp_path / "work" / testshards.NOT_JUDGED).read_text(encoding="utf-8")
    assert f"('{'y' * 1000}')" in text
    assert "'first line\\nsecond line'" in text


def test_a_green_run_with_skips_keeps_only_the_list_in_its_own_folder(tmp_path):
    """A green run removes its tests' folders (607 MB once) but keeps the file the summary names."""
    files = dict(FOUR)
    files["test_s.py"] = skipped_by("no chip folder", ["test_c"])
    proc = run_in_temp(folder(tmp_path / "g", files), tmp_path / "tg")
    assert proc.returncode == 0, proc.stdout
    (kept,) = list((tmp_path / "tg").iterdir())
    assert [p.name for p in kept.iterdir()] == [testshards.NOT_JUDGED]
    assert f"  not judged: the whole list of 1 is in {kept / testshards.NOT_JUDGED}" in proc.stdout
    assert f"logs kept: {kept}, not-judged.txt alone" in proc.stdout.splitlines()


# -- the fast lane: 1 pytest with `-p testshards`, no shards ------------------------------------------------


def lane(root: Path, basetemp: Path, **more: str) -> subprocess.CompletedProcess:
    """pytest as `make verify-site` runs it: the tests that start no engine, the plugin loaded."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("TESTSHARDS_")}
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(ROOT / "verify"), env.get("PYTHONPATH", "")) if p)
    env.update(more)
    cmd = [sys.executable, "-m", "pytest", "-q", "-p", "testshards", "-p", "no:cacheprovider"]
    cmd += ["-m", "not engine", "--basetemp", str(basetemp), "tests"]
    return subprocess.run(cmd, cwd=root, env=env, capture_output=True, text=True, timeout=300, check=False)


def test_the_fast_lane_names_its_groups_and_leaves_the_deselected_test_out(tmp_path):
    """1 test a mark skips, 1 that skips itself, 1 that `-m "not engine"` deselects (its mark would skip
    it too): 2 groups, 1 line for the file in pytest's base folder, and nothing of the deselected test."""
    files = dict(FOUR)
    files["test_s.py"] = skipped_by("no chip folder", ["test_c"]) + (
        "\n\ndef test_inside():\n    pytest.skip('no board here')\n\n\n"
        "@pytest.mark.engine\n@pytest.mark.skipif(True, reason='left out')\n"
        "def test_deselected():\n    pass\n"
    )
    root = folder(tmp_path, files)
    (root / "pytest.ini").write_text(
        "[pytest]\ntestpaths = tests\nmarkers =\n    engine: starts an engine\n", encoding="utf-8"
    )
    base = tmp_path / "base"
    proc = lane(root, base)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not_judged(proc.stdout) == [
        "  not judged: 1 test skipped by a mark on this machine ('no chip folder'): tests/test_s.py::test_c",
        "  not judged: 1 test skipped inside the test ('no board here'): tests/test_s.py::test_inside",
        f"  not judged: the whole list of 2 is in {base / testshards.NOT_JUDGED}",
    ], proc.stdout
    assert "left out" not in proc.stdout
    assert "test_deselected" not in (base / testshards.NOT_JUDGED).read_text(encoding="utf-8")


def test_the_fast_lane_with_no_skip_prints_no_line(tmp_path):
    proc = lane(folder(tmp_path, FOUR), tmp_path / "base")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "not judged" not in proc.stdout
    assert not (tmp_path / "base" / testshards.NOT_JUDGED).exists()


def test_the_fast_gate_loads_the_plugin_that_names_the_groups():
    """`make verify-site` runs 1 pytest, not the shard runner: its line loads `-p testshards` with
    verify/ on PYTHONPATH."""
    text = (ROOT / "verify" / "verify.sh").read_text(encoding="utf-8")
    site = text.split('if [[ "$mode" == site ]]; then', 1)[1].split("\nfi\n", 1)[0]
    (pytest_line,) = [line for line in site.splitlines() if "-m pytest" in line]
    assert 'PYTHONPATH="verify${PYTHONPATH:+:$PYTHONPATH}"' in pytest_line
    assert " -p testshards " in pytest_line


def test_a_red_runs_kept_logs_copy_the_list():
    """tools/ci/kept_logs.py copies the files whose names end in its SUFFIXES from the kept folder."""
    sys.path.insert(0, str(ROOT / "tools" / "ci"))
    import kept_logs

    assert testshards.NOT_JUDGED.endswith(kept_logs.SUFFIXES)


def test_the_groups_are_ordered_by_size_then_reason():
    groups = testshards.skip_groups({"a": "r2", "b": "r1", "c": "r2", "d": "r0"})
    assert groups == [("r2", ["a", "c"]), ("r0", ["d"]), ("r1", ["b"])]


def test_a_reason_of_200_characters_is_whole_and_of_201_is_cut_by_1():
    assert testshards.shown_reason("y" * 200) == f"'{'y' * 200}'"
    assert testshards.shown_reason("y" * 201) == f"'{'y' * 200}' [... 1 characters cut]"


def test_a_group_of_exactly_3_names_its_3_ids_and_no_more():
    line = testshards.group_line(testshards.MARK, "r", ["a", "b", "c"])
    assert line == "  not judged: 3 tests skipped by a mark on this machine ('r'): a, b, c"


# -- a file skipped whole as it is collected: importorskip, or pytest.skip(allow_module_level=True) -------

IMPORTORSKIP = "import pytest\n\nnp = pytest.importorskip('nosuchmodule_xyz')\n\n\ndef test_i1():\n    pass\n"
MODULE_SKIP = (
    "import pytest\n\npytest.skip('no chip folder here', allow_module_level=True)\n\n\n"
    "def test_s1():\n    pass\n"
)


def test_a_file_an_importorskip_skips_whole_is_named_by_the_runner(tmp_path):
    """tests/test_copper.py calls `pytest.importorskip("numpy")` at its top level: on a machine with no
    numpy the whole file goes unjudged. It shares a shard with a passing file here."""
    proc = gate(folder(tmp_path, {"test_a.py": PASSING, "test_z.py": IMPORTORSKIP}), jobs=1)
    assert proc.returncode == 0, proc.stdout
    lines = not_judged(proc.stdout)
    listed = tmp_path / "work" / testshards.NOT_JUDGED
    assert len(lines) == 2, proc.stdout
    assert re.fullmatch(
        r"  not judged: tests/test_z\.py: skipped at collection "
        r"\(\"could not import 'nosuchmodule_xyz'.*\"\)",
        lines[0],
    ), lines
    assert lines[1] == f"  not judged: the whole list of 1 is in {listed}"
    assert "TESTS GREEN: 2 tests in 1 shards; 1 file not judged (skipped at collection)" in proc.stdout
    assert "  tests/test_z.py\n" in listed.read_text(encoding="utf-8")


def test_a_shard_whose_only_file_is_skipped_at_collection_is_not_red(tmp_path):
    """pytest exits 5 (no tests collected) for a shard that holds only a file skipped whole: a skip is
    not a failure. A shard with no test and no skip stays red."""
    proc = gate(folder(tmp_path, {"test_a.py": PASSING, "test_z.py": MODULE_SKIP}))
    assert proc.returncode == 0, proc.stdout
    assert "why:" not in proc.stdout
    assert "  not judged: tests/test_z.py: skipped at collection ('no chip folder here')" in proc.stdout
    assert "TESTS GREEN: 2 tests in 2 shards; 1 file not judged (skipped at collection)" in proc.stdout
    empty = gate(folder(tmp_path / "e", {"test_a.py": PASSING, "test_e.py": "X = 1\n"}))
    assert empty.returncode == 1, empty.stdout
    assert "TESTS RED: shard " in empty.stdout


def test_the_fast_lane_names_a_file_skipped_at_collection(tmp_path):
    files = dict(FOUR)
    files["test_z.py"] = MODULE_SKIP
    base = tmp_path / "base"
    proc = lane(folder(tmp_path, files), base)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not_judged(proc.stdout) == [
        "  not judged: tests/test_z.py: skipped at collection ('no chip folder here')",
        f"  not judged: the whole list of 1 is in {base / testshards.NOT_JUDGED}",
    ], proc.stdout


# -- what the lane hides on purpose is not the machine's ------------------------------------------------


def test_the_fast_lane_says_what_it_hides_and_does_not_blame_the_machine(tmp_path):
    """`make verify-site` empties KiCad's library folders and refuses engines: a mark that skips for
    that skips for the run. With TESTSHARDS_HIDES set, the first line says what the run hides, and the
    groups say `in this run`, not `on this machine`."""
    files = dict(FOUR)
    files["test_s.py"] = skipped_by("KiCad symbol libraries are not installed", ["test_c"])
    base = tmp_path / "base"
    proc = lane(folder(tmp_path, files), base, TESTSHARDS_HIDES="KiCad's libraries")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not_judged(proc.stdout) == [
        "  not judged: this run hides KiCad's libraries on purpose: a mark below may skip a test for the "
        "run, not for the machine",
        "  not judged: 1 test skipped by a mark in this run ('KiCad symbol libraries are not installed'): "
        "tests/test_s.py::test_c",
        f"  not judged: the whole list of 1 is in {base / testshards.NOT_JUDGED}",
    ], proc.stdout
    assert "on this machine" not in proc.stdout


def test_the_fast_gate_names_what_it_hides():
    text = (ROOT / "verify" / "verify.sh").read_text(encoding="utf-8")
    site = text.split('if [[ "$mode" == site ]]; then', 1)[1].split("\nfi\n", 1)[0]
    (pytest_line,) = [line for line in site.splitlines() if "-m pytest" in line]
    assert 'TESTSHARDS_HIDES="KiCad\'s symbol and footprint libraries and every engine"' in pytest_line


# -- what is not a skip for the machine, and a shard's own pytest ---------------------------------------


def test_the_fast_lane_does_not_name_an_xfail_by_mark_or_inside(tmp_path):
    files = dict(FOUR)
    files["test_x.py"] = (
        "import pytest\n\n\n@pytest.mark.xfail(reason='known')\ndef test_x():\n    assert 0\n\n\n"
        "def test_xi():\n    pytest.xfail('inside xfail')\n"
    )
    proc = lane(folder(tmp_path, files), tmp_path / "base")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "2 xfailed" in proc.stdout
    assert "not judged" not in proc.stdout
    assert not (tmp_path / "base" / testshards.NOT_JUDGED).exists()


def test_a_shards_pytest_prints_no_line_and_writes_no_file(tmp_path):
    """The runner joins its shards' logs and prints the lines once: a shard (TESTSHARDS_SHARD) prints none."""
    files = dict(FOUR)
    files["test_s.py"] = skipped_by("no chip folder", ["test_c"])
    base = tmp_path / "base"
    proc = lane(
        folder(tmp_path, files), base, TESTSHARDS_SHARD="1", TESTSHARDS_LOG=str(tmp_path / "log.jsonl")
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 skipped" in proc.stdout
    assert "not judged" not in proc.stdout
    assert not (base / testshards.NOT_JUDGED).exists()
