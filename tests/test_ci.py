"""`workcenter ci`: a repository's GitHub workflow replayed here, step by step, as the runner runs it.

The repository is written by each test: a workflow whose jobs set $GITHUB_ENV and $GITHUB_PATH, read
`${{ env.X }}`, use a working directory, carry install and upload steps the replay skips by name, and
one job that fails half way through a step. PyYAML reads the workflow under the venv.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"

# `second` comes first in the file and needs `first`: the replay runs `first` before it.
WORKFLOW = """name: Gates
on: [push]
env:
  TOP: workflow
jobs:
  second:
    needs: first
    runs-on: ubuntu-24.04
    steps:
      - name: Fails half way
        run: |
          echo "about to fail"
          false
          echo never > never.txt
      - name: After the failure
        run: touch after.txt
  first:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v4
      - name: Install the toolchain
        run: exit 7
      - name: Find the versions
        run: |
          echo "LATEST=v0.2" >> "$GITHUB_ENV"
          {
            echo "NOTES<<END"
            echo "line one"
            echo "line two"
            echo "END"
          } >> "$GITHUB_ENV"
          mkdir -p tools-bin
          printf '#!/bin/sh\\necho tool ran\\n' > tools-bin/mytool
          chmod +x tools-bin/mytool
          echo "$PWD/tools-bin" >> "$GITHUB_PATH"
      - name: Use them
        env:
          STEP: ${{ env.LATEST }}-step
        run: |
          test "$LATEST" = v0.2
          test "$STEP" = v0.2-step
          test "$TOP" = workflow
          test "$NOTES" = "$(printf 'line one\\nline two')"
          mytool > tool.out
          echo "${{ env.LATEST }}" > latest.txt
      - name: In a folder
        working-directory: sub
        run: pwd > ../where.txt
      - name: Upload the pictures
        run: exit 9
"""


def repo_with(tmp_path: Path, workflow: str = WORKFLOW) -> Path:
    repo = tmp_path / "repo"
    (repo / ".github" / "workflows").mkdir(parents=True)
    (repo / "sub").mkdir()
    (repo / ".github" / "workflows" / "gates.yml").write_text(workflow, encoding="utf-8")
    return repo


def ci(*args: object, json_out: bool = False) -> tuple[int, str, dict]:
    cmd = [sys.executable, str(CLI), *(["--json"] if json_out else []), "ci", *map(str, args)]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=300)
    data = json.loads(proc.stdout) if json_out and proc.stdout.strip() else {}
    return proc.returncode, proc.stdout + proc.stderr, data


def test_a_job_replays_green_with_its_environment_carried_between_steps(tmp_path):
    pytest.importorskip("yaml")
    repo = repo_with(tmp_path)
    code, text, _ = ci(repo, "--job", "first")
    assert code == 0, text
    assert text.splitlines()[-1] == "CI REPLAY GREEN"
    assert (repo / "latest.txt").read_text() == "v0.2\n"  # ${{ env.X }} from an earlier step's $GITHUB_ENV
    assert (repo / "tool.out").read_text() == "tool ran\n"  # $GITHUB_PATH
    assert (repo / "where.txt").read_text().strip() == str(repo / "sub")
    assert "[first] skip  actions/checkout@v4  (uses actions/checkout@v4)" in text
    assert "[first] skip  Install the toolchain" in text and "[first] skip  Upload the pictures" in text
    logs = sorted(p.name for p in (repo / "build" / "ci" / "first").glob("*.log"))
    assert logs == ["03-Find_the_versions.log", "04-Use_them.log", "05-In_a_folder.log"]


def test_a_failing_step_turns_the_replay_red_and_stops_its_job(tmp_path):
    pytest.importorskip("yaml")
    repo = repo_with(tmp_path)
    code, text, data = ci(repo, "--out", tmp_path / "logs", json_out=True)
    assert code == 1
    assert data["verdict"] == "CI REPLAY RED: second: Fails half way"
    ran = [(s["job"], s["step"], s["state"]) for s in data["steps"]]
    assert ran.index(("first", "Use them", "ok")) < ran.index(("second", "Fails half way", "red"))
    assert ("second", "After the failure", "ok") not in ran
    assert (
        not (repo / "never.txt").exists() and not (repo / "after.txt").exists()
    )  # bash -e, then the job stops
    assert (tmp_path / "logs" / "second" / "01-Fails_half_way.log").read_text() == "about to fail\n"
    code, text, _ = ci(repo, "--job", "second")
    assert code == 1
    assert "       | about to fail" in text  # the failing step's last lines are printed
    assert text.splitlines()[-1] == "CI REPLAY RED: second: Fails half way"


def test_what_the_replay_cannot_run_is_red_or_skipped_by_name(tmp_path):
    pytest.importorskip("yaml")
    secret = "jobs:\n  deploy:\n    runs-on: x\n    steps:\n      - name: Publish\n"
    secret += "        run: echo ${{ secrets.TOKEN }}\n"
    repo = repo_with(tmp_path, secret)
    code, text, _ = ci(repo)
    assert code == 1
    assert "cannot replay ${{ secrets.TOKEN }}" in text
    code, text, _ = ci(repo, "--skip", "Publish")
    assert code == 2 and text.splitlines()[-1] == "CI REPLAY: no run step to replay"
    code, text, _ = ci(repo, "--job", "nope")
    assert code == 1 and "no job nope; the jobs are deploy" in text
    code, text, _ = ci(tmp_path / "empty")
    assert code == 2 and "no workflow" in text


def test_working_directories_from_the_step_the_job_and_the_workflow(tmp_path):
    pytest.importorskip("yaml")
    flow = "defaults:\n  run:\n    working-directory: sub\njobs:\n  a:\n    runs-on: x\n    steps:\n"
    flow += "      - run: pwd > flow.txt\n"
    flow += "      - run: pwd > step.txt\n        working-directory: .\n"
    flow += "  b:\n    runs-on: x\n    defaults:\n      run:\n        working-directory: job\n    steps:\n"
    flow += "      - run: pwd > job.txt\n"
    repo = repo_with(tmp_path, flow)
    (repo / "job").mkdir()
    code, text, _ = ci(repo)
    assert code == 0, text
    assert (repo / "sub" / "flow.txt").read_text().strip() == str(repo / "sub")
    assert (repo / "step.txt").read_text().strip() == str(repo)
    assert (repo / "job" / "job.txt").read_text().strip() == str(repo / "job")
