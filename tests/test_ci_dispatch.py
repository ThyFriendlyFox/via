"""A run of CI by hand: the gate of a candidate branch with no pull request.

The owner's decision of 2026-11-19: `main` takes no commit that `make verify` did not pass on that
exact commit, and the gate runs on GitHub. A work branch with no pull request asks for it with
`gh workflow run ci.yml --ref <branch>` (`workflow_dispatch`). Such a run has no base to compare
with, so it must be `full`, and its `verdict` green only when `full` passed. The workflow is held
here by its parsed structure and by its own steps run in a shell: GitHub Actions does not run on
this machine. The helpers come from `tests/test_ci_scope.py`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from test_ci_scope import README, SCOPE, commit, git, workflow


def test_a_run_by_hand_gates_any_branch_and_is_full(tmp_path: Path):
    """The scope job names the event and gives it no base, so the run is full; the verdict is green
    only when `full` passed. The scope step is run here as the runner runs it, on a change of prose
    that a pull request calls fast."""
    flow = workflow()
    assert "workflow_dispatch" in flow[True]
    (step,) = [s for s in flow["jobs"]["scope"]["steps"] if "scope.py" in s.get("run", "")]
    assert step["env"]["EVENT"] == "${{ github.event_name }}"
    assert 'workflow_dispatch) base="" ;;' in step["run"], "the scope step names a run by hand"
    call = "python3 tools/ci/scope.py"
    assert call in step["run"]
    script = tmp_path / "scope.sh"
    script.write_text(step["run"].replace(call, f"{sys.executable} {SCOPE}"), encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    commit(repo, {"README.md": README}, "base")
    commit(
        repo, {"README.md": README.replace("Each line names its gate.", "Each line names 1 gate.")}, "prose"
    )
    answers = {}
    for event in ("pull_request", "workflow_dispatch"):
        out = tmp_path / f"output-{event}"
        env = {**os.environ, "EVENT": event, "BEFORE": "", "GITHUB_OUTPUT": str(out)}
        ran = subprocess.run(["bash", "-e", str(script)], cwd=repo, env=env, capture_output=True, text=True)
        assert ran.returncode == 0, ran.stderr
        answers[event] = out.read_text(encoding="utf-8")
    assert answers == {"pull_request": "scope=fast\n", "workflow_dispatch": "scope=full\n"}
    (check,) = flow["jobs"]["verdict"]["steps"]
    verdict = tmp_path / "verdict.sh"
    verdict.write_text(check["run"], encoding="utf-8")
    for full, code in (("success", 0), ("skipped", 1), ("failure", 1), ("cancelled", 1)):
        env = {**os.environ, "SCOPE": "full", "FAST": "skipped", "FULL": full}
        ran = subprocess.run(["bash", "-e", str(verdict)], env=env, capture_output=True, text=True)
        assert ran.returncode == code, (full, ran.stdout)
