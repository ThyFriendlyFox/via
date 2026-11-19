"""A red run on GitHub keeps the gate's logs (tools/ci/kept_logs.py and ci.yml's steps after each gate).

On 2026-11-19, 13 routing tests failed on GitHub, and the gate printed `see /tmp/ee-verify-.../
freerouting.log`: the file was gone with the runner, and the run had 0 artifacts. verify/testshards.py
keeps its folder (`logs kept: <folder>`) when a run is red; ci.yml now copies that folder's logs, bounded,
into an artifact when the gate's step failed, on both paths of `full` and in `fast`.

The script's tests run it on folders of their own; the workflow's tests read ci.yml as
tests/test_ci_scope.py and tests/test_image.py read it, and run the copy step's own line here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ci" / "kept_logs.py"
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
INTO = "kept-logs"


def keep(tmp_path: Path, *patterns: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / INTO), *patterns],
        capture_output=True,
        text=True,
        env={**os.environ, **(env or {})},
        check=False,
    )


def kept_folder(tmp_path: Path) -> Path:
    """A red run's folder as verify/testshards.py keeps it: the shards' logs, and a test's tmp_path with a
    router's log beside a board."""
    work = tmp_path / "tmp" / "ee-verify-abc123"
    shard = work / "shard-2"
    test = shard / "tmp" / "test_route_round_trip0"
    test.mkdir(parents=True)
    (work / "collect.jsonl").write_text('{"collected": 4082}\n', encoding="utf-8")
    (shard / "log.jsonl").write_text('{"outcome": "failed"}\n', encoding="utf-8")
    (shard / "pytest.log").write_text(
        "FAILED tests/test_kicadgen.py::test_route_round_trip\n", encoding="utf-8"
    )
    (test / "freerouting.log").write_text("Routing incomplete: 3 connections\n", encoding="utf-8")
    (test / "board.kicad_pcb").write_text("(kicad_pcb)\n" * 1000, encoding="utf-8")
    (test / "drc.rpt").write_text("** 2 DRC violations **\n", encoding="utf-8")
    (test / "render.png").write_bytes(b"\x89PNG" + b"\0" * 1000)
    return work


def test_the_logs_of_the_kept_folder_are_copied_and_the_boards_are_not(tmp_path):
    kept_folder(tmp_path)
    ran = keep(tmp_path, str(tmp_path / "tmp" / "ee-verify-*"))
    assert ran.returncode == 0, ran.stderr
    into = tmp_path / INTO
    got = sorted(p.relative_to(into).as_posix() for p in into.rglob("*") if p.is_file())
    assert got == [
        "KEPT.txt",
        "ee-verify-abc123/collect.jsonl",
        "ee-verify-abc123/shard-2/log.jsonl",
        "ee-verify-abc123/shard-2/pytest.log",
        "ee-verify-abc123/shard-2/tmp/test_route_round_trip0/drc.rpt",
        "ee-verify-abc123/shard-2/tmp/test_route_round_trip0/freerouting.log",
    ]
    log = into / "ee-verify-abc123/shard-2/tmp/test_route_round_trip0/freerouting.log"
    assert log.read_text(encoding="utf-8") == "Routing incomplete: 3 connections\n"
    # 20 + 22 + 51 + 24 + 35 bytes: the 5 logs, whole.
    assert ran.stdout.splitlines()[-1].startswith(f"kept_logs: 5 files, 152 bytes, into {into}")


def test_a_long_log_keeps_its_end_and_says_what_was_left_out(tmp_path):
    """A shard's pytest.log ends with its failures: a file over 2 MB keeps its last 2 MB, after 1 line
    that says how much of it is left out."""
    work = kept_folder(tmp_path)
    big = work / "shard-2" / "pytest.log"
    big.write_bytes(b"x" * 3_000_000 + b"\nFAILED the last line\n")
    assert keep(tmp_path, str(work)).returncode == 0
    copy = tmp_path / INTO / "ee-verify-abc123" / "shard-2" / "pytest.log"
    data = copy.read_bytes()
    first, rest = data.split(b"\n", 1)
    assert first == b"[kept_logs.py: the first 1000022 bytes of 3000022 are left out]"
    assert len(rest) == 2_000_000 and rest.endswith(b"FAILED the last line\n")


def test_the_artifact_stays_within_its_bound_and_names_what_it_left_out(tmp_path):
    """50 MB in all: the folder's top files first, then deeper ones; a file that does not fit is left
    out and named in KEPT.txt."""
    work = tmp_path / "tmp" / "ee-verify-big"
    for n in range(30):
        folder = work / f"shard-{n:02d}"
        folder.mkdir(parents=True)
        (folder / "pytest.log").write_bytes(b"y" * 1_900_000)
    ran = keep(tmp_path, str(work))
    assert ran.returncode == 0
    into = tmp_path / INTO
    sizes = [p.stat().st_size for p in into.rglob("pytest.log")]
    assert len(sizes) == 26 and sum(sizes) <= 50_000_000
    listing = (into / "KEPT.txt").read_text(encoding="utf-8").splitlines()
    left = [line for line in listing if line.startswith("left out ")]
    assert left == [
        f"left out ee-verify-big/shard-{n:02d}/pytest.log: 1900000 bytes; the artifact's 50000000 are full"
        for n in range(26, 30)
    ]
    assert ran.stdout.splitlines()[-1].endswith("; 4 left out (KEPT.txt names them)")


def test_no_kept_folder_keeps_nothing_and_does_not_fail_the_job(tmp_path):
    """A gate that failed before its tests ran (lint, the doctor) keeps no folder: 1 line, exit 0."""
    ran = keep(tmp_path, str(tmp_path / "tmp" / "ee-verify-*"))
    assert ran.returncode == 0
    assert (
        ran.stdout.strip()
        == f"kept_logs: no folder matches {tmp_path / 'tmp' / 'ee-verify-*'}: nothing to keep"
    )
    assert [p.name for p in (tmp_path / INTO).iterdir()] == ["KEPT.txt"]


def test_a_plain_file_that_matches_the_pattern_is_no_folder(tmp_path):
    """Only folders are kept: a file whose name matches the pattern is not named as one."""
    (tmp_path / "tmp").mkdir(exist_ok=True)
    (tmp_path / "tmp" / "ee-verify-note.txt").write_text("not a folder\n", encoding="utf-8")
    ran = keep(tmp_path, str(tmp_path / "tmp" / "ee-verify-*"))
    assert ran.returncode == 0
    assert (
        ran.stdout.strip()
        == f"kept_logs: no folder matches {tmp_path / 'tmp' / 'ee-verify-*'}: nothing to keep"
    )


def test_a_link_out_of_the_folder_is_not_followed(tmp_path):
    work = kept_folder(tmp_path)
    secret = tmp_path / "elsewhere"
    secret.mkdir()
    (secret / "other.log").write_text("not the gate's\n", encoding="utf-8")
    (work / "linked").symlink_to(secret)
    (work / "linked.log").symlink_to(secret / "other.log")
    assert keep(tmp_path, str(work)).returncode == 0
    assert not any("other" in p.name or "linked" in p.name for p in (tmp_path / INTO).rglob("*"))


def test_a_call_without_a_pattern_is_refused(tmp_path):
    ran = subprocess.run([sys.executable, str(SCRIPT)], capture_output=True, text=True, check=False)
    assert ran.returncode == 2 and "usage: kept_logs.py <into> <folder pattern>..." in ran.stderr


# ---------------------------------------------------------------- the workflow


def workflow() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


# Each gate step, by job and id: where its kept folder lands on the runner.
GATES = {
    ("full", "verify"): '"${TMPDIR:-/tmp}/ee-verify-*"',
    ("full", "inside"): '"$RUNNER_TEMP/image-tmp/ee-verify-*"',
    ("fast", "gate"): '"${TMPDIR:-/tmp}/pytest-of-*"',
}


def after(job: dict, gate: str) -> list[dict]:
    """The 2 steps right after the gate step `gate`."""
    steps = job["steps"]
    (i,) = [n for n, s in enumerate(steps) if s.get("id") == gate]
    return steps[i + 1 : i + 3]


@pytest.mark.parametrize(("job", "gate"), list(GATES))
def test_a_failed_gate_step_keeps_its_logs_as_an_artifact_and_a_passed_one_does_not(job, gate):
    """Right after each gate step: the copy, then the upload, both only when that step failed (never on
    success, never for a step that did not run), the action pinned as the repository pins its others,
    the artifact bounded in days and taken only from the copy's folder under the runner's temp."""
    jobs = workflow()["jobs"]
    copy, upload = after(jobs[job], gate)
    when = f"failure() && steps.{gate}.outcome == 'failure'"
    assert copy["if"] == when and upload["if"] == when
    assert copy["run"].strip() == f'python3 tools/ci/kept_logs.py "$RUNNER_TEMP/{INTO}" {GATES[(job, gate)]}'
    assert upload["uses"] == "actions/upload-artifact@v4"
    pinned = {s["uses"].split("@")[1] for j in jobs.values() for s in j["steps"] if "uses" in s}
    assert pinned <= {"v4", "v5"}
    assert upload["with"] == {
        "name": f"gate-logs-{job}-{gate}",
        "path": "${{ runner.temp }}/" + INTO,
        "retention-days": 7,
        "if-no-files-found": "ignore",
    }
    assert "env" not in copy and "env" not in upload


def test_the_image_path_puts_its_tmp_where_the_runner_keeps_it():
    """`docker run --rm` takes the container's /tmp with it: the image path mounts a folder of the
    runner's temp as /tmp, made first, so the gate's kept folder lands at $RUNNER_TEMP/image-tmp."""
    (step,) = [s for s in workflow()["jobs"]["full"]["steps"] if s.get("id") == "inside"]
    lines = [x.strip() for x in step["run"].strip().splitlines()]
    assert lines[0] == 'mkdir -p "$RUNNER_TEMP/image-tmp"'
    assert '-v "$RUNNER_TEMP/image-tmp":/tmp' in step["run"]


def test_no_step_that_keeps_or_uploads_logs_holds_a_secret():
    """The jobs' only secret is GITHUB_TOKEN, in the step that logs in to the registry; the gate steps,
    the copies and the uploads have none, and the copy reads only the gate's folders."""
    jobs = workflow()["jobs"]
    holding = [
        (name, s.get("id") or s.get("name"))
        for name, j in jobs.items()
        for s in j["steps"]
        if "secrets." in str(s)
    ]
    assert holding == [("full", "where")]
    for job, gate in GATES:
        (step,) = [s for s in jobs[job]["steps"] if s.get("id") == gate]
        assert "secrets." not in str(step)


def test_the_copy_step_finds_the_folder_where_the_gate_keeps_it(tmp_path):
    """The install path's copy line runs here as the step runs it: with TMPDIR unset it reads /tmp, so
    the test gives TMPDIR (verify/testshards.py's mkdtemp reads it too) and RUNNER_TEMP."""
    work = kept_folder(tmp_path)
    copy, _ = after(workflow()["jobs"]["full"], "verify")
    env = {**os.environ, "TMPDIR": str(work.parent), "RUNNER_TEMP": str(tmp_path / "runner")}
    line = copy["run"].replace("python3 ", f"{sys.executable} ", 1)
    ran = subprocess.run(["bash", "-e", "-c", line], env=env, capture_output=True, text=True, cwd=ROOT)
    assert ran.returncode == 0, ran.stderr
    assert (tmp_path / "runner" / INTO / "ee-verify-abc123" / "shard-2" / "pytest.log").is_file()
