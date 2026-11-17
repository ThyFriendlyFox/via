"""`verify/testshards.py`: the health gate's tests in several processes, joined into 1 verdict.

The split and the join are judged on tables and logs written here. The runs start pytest on small test
folders written in tmp_path: no engine runs, and none of the repository's own tests.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

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


def gate(root: Path, jobs: int = 2) -> subprocess.CompletedProcess:
    args = ["run", "--root", str(root), "--table", str(root / "shards.csv"), "--jobs", str(jobs)]
    args += ["--python", sys.executable, "--work", str(root.parent / "work")]
    return subprocess.run(
        [sys.executable, str(ROOT / "verify" / "testshards.py"), *args],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
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
    assert f"FAILED {target}::test_planted (shard {shard})" in proc.stdout
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


def test_the_gate_prints_each_shards_time_and_the_slowest_files(tmp_path):
    proc = gate(folder(tmp_path, FOUR))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for name in ("1", "2"):
        assert f"shard {name}: exit 0," in proc.stdout
    assert "slowest files:" in proc.stdout
    assert os.path.join("tests", "test_p.py") in proc.stdout
