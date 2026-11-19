"""The nightly's `ci-failure` issue follows the nights by itself (tools/ci/nightly_issue.py).

The issue of the failed night of 2026-11-17 stayed open after the next night passed, until it was
closed by hand on 2026-11-18. The old step opened an issue only when none was open and never closed
one, so while it stood open a new failure said nothing. The script now decides, from the night's
outcome, the gate's log and the open issues, to open, comment, close or do nothing, with the text;
the workflow's step only carries the answer to GitHub. No GitHub run can be made from a test: the
workflow's script runs here under node with a stand-in `github` that records each call.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ci" / "nightly_issue.py"
NIGHTLY = ROOT / ".github" / "workflows" / "nightly.yml"
RUN = "https://github.com/o/r/actions/runs/7"
STEPS = {"archive": "success", "install": "success", "verify": "failure"}


def load():
    spec = importlib.util.spec_from_file_location("nightly_issue", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def issue(number: int, **more) -> dict:
    return {"number": number, "title": f"Nightly verify failed - #{number}", **more}


RED_LOG = """\
== 1/4 lint
== 2/4 kit checks
kit checks ok
== 3/4 doctor
== 4/4 tests
FAILED tests/test_a.py::test_one (shard 2) at 41 s
why: tests/test_a.py::test_one, failed at call (shard 2):
  | def test_one():
  | >       assert 1 == 2
  | E       assert 1 == 2
tests: 300 s on the wall clock, 900 s of test time
TESTS RED: shard 2: 1 failed
"""


def plan(outcome="failure", log=RED_LOG, issues=(), steps=None, date="2026-11-19"):
    return load().plan(outcome, log, list(issues), RUN, date, dict(steps or STEPS))


# ---------------------------------------------------------------- the 4 cases


def test_a_failed_night_with_no_open_issue_opens_one_with_the_run_and_the_reason():
    (act,) = plan()
    assert act["do"] == "open" and act["labels"] == ["ci-failure"]
    assert act["title"] == "Nightly verify failed - 2026-11-19"
    assert RUN in act["body"]
    assert "the step that failed: verify" in act["body"]
    assert "why: tests/test_a.py::test_one, failed at call (shard 2):" in act["body"]
    assert "E       assert 1 == 2" in act["body"]
    assert "TESTS RED: shard 2: 1 failed" in act["body"]


def test_a_failed_night_with_an_open_issue_adds_1_comment_with_the_run_and_the_reason():
    (act,) = plan(issues=[issue(12)])
    assert act["do"] == "comment" and act["issue"] == 12
    assert RUN in act["body"] and "2026-11-19" in act["body"]
    assert "why: tests/test_a.py::test_one" in act["body"]


def test_a_passed_night_with_an_open_issue_closes_it_with_1_comment_naming_the_run():
    (act,) = plan("success", "VERIFY GREEN\n", [issue(12)], {k: "success" for k in STEPS})
    assert act["do"] == "close" and act["issue"] == 12
    assert RUN in act["body"] and "passed" in act["body"]


def test_a_passed_night_with_no_open_issue_does_nothing():
    assert plan("success", "VERIFY GREEN\n", [], {k: "success" for k in STEPS}) == []


def test_a_pull_request_with_the_label_is_not_an_issue():
    """GitHub's list of a repository's issues holds its pull requests too, each with `pull_request`."""
    assert plan("success", "", [issue(5, pull_request={"url": "x"})], {k: "success" for k in STEPS}) == []
    (act,) = plan(issues=[issue(5, pull_request={"url": "x"})])
    assert act["do"] == "open"


# ---------------------------------------------------------------- the reason


def test_a_gate_stopped_at_lint_names_its_step_and_shows_the_end_of_its_log():
    log = "== 1/4 lint\n" + "".join(f"line {n}\n" for n in range(100)) + "install.sh:12:1: SC2086 quote it\n"
    (act,) = plan(log=log)
    body = act["body"]
    assert "no `why:` line" in body
    assert "the gate stopped in its step 1/4 lint" in body
    assert "install.sh:12:1: SC2086 quote it" in body
    assert "line 99" in body and "line 0\n" not in body


def test_a_night_stopped_at_install_has_no_log_and_says_so():
    steps = {"archive": "success", "install": "failure", "verify": "skipped"}
    (act,) = plan(log=None, steps=steps)
    assert "the step that failed: install" in act["body"]
    assert "the gate's log is absent" in act["body"]


def test_300_failures_are_bounded_and_the_rest_counted():
    lines = ["== 4/4 tests"]
    for n in range(300):
        lines.append(f"FAILED tests/test_b.py::test_{n} (shard 1) at {n} s")
        lines += [f"why: tests/test_b.py::test_{n}, failed at call (shard 1):"]
        lines += [f"  | line {k} of {n}" + "x" * 400 for k in range(40)]
    lines.append("TESTS RED: shard 1: 300 failed")
    (act,) = plan(log="\n".join(lines) + "\n")
    body = act["body"]
    mod = load()
    assert len(body) <= mod.MAX_CHARS
    assert "300 tests failed" in body
    assert f"and {300 - mod.FAILED_LINES} more FAILED lines" in body
    shown = sum(1 for line in body.splitlines() if line.startswith("why: "))
    assert 1 <= shown <= mod.BLOCKS
    assert f"and {300 - shown} more `why:` blocks" in body
    assert "lines cut here]" in body and "characters cut]" in body
    assert "TESTS RED: shard 1: 300 failed" in body
    assert max(len(line) for line in body.splitlines()) <= mod.WIDTH + 40


def test_markdown_in_a_tests_name_stays_inside_a_fence_longer_than_any_it_holds():
    name = "tests/test_c.py::test_x[**bold** | <details> @owner #1 ```code```]"
    log = (
        f"== 4/4 tests\nFAILED {name} (shard 1) at 1 s\nwhy: {name}, failed at call (shard 1):\n  | E boom\n"
    )
    (act,) = plan(log=log)
    body = act["body"]
    fences = [n for n, line in enumerate(body.splitlines()) if line.startswith("`")]
    assert {body.splitlines()[n] for n in fences} == {"````"} and len(fences) % 2 == 0
    inside = set()
    for a, b in zip(fences[::2], fences[1::2], strict=True):
        inside |= set(range(a + 1, b))
    holding = [n for n, line in enumerate(body.splitlines()) if name in line]
    assert len(holding) == 2 and set(holding) <= inside


def test_2_open_issues_the_oldest_is_spoken_to_the_other_closed_as_its_duplicate():
    acts = plan(issues=[issue(30), issue(12)])
    assert [(a["do"], a["issue"]) for a in acts] == [("comment", 12), ("close", 30)]
    assert "duplicate of #12" in acts[1]["body"]


def test_a_passed_night_closes_every_open_issue():
    acts = plan("success", "", [issue(30), issue(12)], {k: "success" for k in STEPS})
    assert [(a["do"], a["issue"]) for a in acts] == [("close", 12), ("close", 30)]


def test_an_outcome_other_than_success_or_failure_is_refused():
    with pytest.raises(ValueError):
        plan("cancelled")


# ---------------------------------------------------------------- the command line


def test_the_command_reads_files_and_prints_the_plan_as_json(tmp_path):
    (tmp_path / "log").write_text(RED_LOG, encoding="utf-8")
    (tmp_path / "issues.json").write_text(json.dumps([issue(4)]), encoding="utf-8")
    args = ["--outcome", "failure", "--log", str(tmp_path / "log"), "--issues", str(tmp_path / "issues.json")]
    args += ["--run", RUN, "--date", "2026-11-19", "--step", "install=success", "--step", "verify=failure"]
    ran = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    assert ran.returncode == 0, ran.stderr
    (act,) = json.loads(ran.stdout)["actions"]
    assert (act["do"], act["issue"]) == ("comment", 4)
    assert "nightly-issue: comment on #4" in ran.stderr


def test_the_command_takes_an_absent_log_as_no_log(tmp_path):
    (tmp_path / "issues.json").write_text("[]", encoding="utf-8")
    args = [
        "--outcome",
        "failure",
        "--log",
        str(tmp_path / "none"),
        "--issues",
        str(tmp_path / "issues.json"),
    ]
    args += ["--run", RUN, "--date", "2026-11-19", "--step", "install=failure"]
    ran = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True)
    assert ran.returncode == 0, ran.stderr
    (act,) = json.loads(ran.stdout)["actions"]
    assert "the gate's log is absent" in act["body"]


# ---------------------------------------------------------------- the workflow's step


def nightly() -> dict:
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(NIGHTLY.read_text(encoding="utf-8"))["jobs"]["verify"]


def issue_step(job: dict) -> dict:
    (step,) = [s for s in job["steps"] if "nightly_issue.py" in s.get("with", {}).get("script", "")]
    return step


def test_the_step_runs_on_a_passed_and_a_failed_night_and_after_every_other_step():
    job = nightly()
    step = issue_step(job)
    assert job["steps"][-1] is step
    assert step["if"] == "success() || failure()"
    ids = [s.get("id") for s in job["steps"][:-1] if s.get("id")]
    assert ids == ["archive", "install", "verify"]
    assert all(f"steps.{i}.outcome" in step["env"][i.upper()] for i in ids)
    verify = [s for s in job["steps"] if s.get("id") == "verify"][0]
    assert "set -o pipefail" in verify["run"]
    assert "make verify 2>&1 | tee build/nightly-verify.log" in verify["run"]


class Recorder:
    """The workflow's script under node, with stand-ins for github-script's `github`, `context` and `core`."""

    HARNESS = r"""
const fs = require('fs');
const [script, issuesPath, outPath] = process.argv.slice(2);
const calls = [];
const open = JSON.parse(fs.readFileSync(issuesPath, 'utf8'));
const rec = (name) => async (args) => { calls.push([name, args]); return { data: {} }; };
const github = {
  paginate: async (fn, args) => { calls.push(['list', args]); return open; },
  rest: { issues: { listForRepo: 'listForRepo', create: rec('create'),
                    createComment: rec('createComment'), update: rec('update') } },
};
const context = { repo: { owner: 'o', repo: 'r' }, runId: 7, serverUrl: 'https://github.com' };
const core = { info: (m) => calls.push(['info', m]), setFailed: (m) => calls.push(['failed', m]) };
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
new AsyncFunction('github', 'context', 'core', 'require', fs.readFileSync(script, 'utf8'))(
  github, context, core, require
).then(() => fs.writeFileSync(outPath, JSON.stringify(calls)),
       (e) => { fs.writeFileSync(outPath, JSON.stringify([['error', String(e)]])); process.exit(1); });
"""

    def __init__(self, tmp_path: Path):
        self.tmp = tmp_path
        step = issue_step(nightly())
        self.step = step
        (tmp_path / "script.js").write_text(step["with"]["script"], encoding="utf-8")
        (tmp_path / "harness.js").write_text(self.HARNESS, encoding="utf-8")

    def run(self, status: str, outcomes: dict, open_issues: list, log: str | None) -> list:
        work = self.tmp / "work"
        shutil.rmtree(work, ignore_errors=True)
        (work / "tools" / "ci").mkdir(parents=True)
        shutil.copy(SCRIPT, work / "tools" / "ci" / SCRIPT.name)
        if log is not None:
            (work / "build").mkdir()
            (work / "build" / "nightly-verify.log").write_text(log, encoding="utf-8")
        (self.tmp / "open.json").write_text(json.dumps(open_issues), encoding="utf-8")
        env = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "JOB_STATUS": status}
        for key in self.step["env"]:
            if key != "JOB_STATUS":
                env[key] = outcomes[key.lower()]
        node = shutil.which("node")
        out = self.tmp / "calls.json"
        ran = subprocess.run(
            [
                node,
                str(self.tmp / "harness.js"),
                str(self.tmp / "script.js"),
                str(self.tmp / "open.json"),
                str(out),
            ],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
        )
        assert ran.returncode == 0, (ran.stdout, ran.stderr, out.read_text() if out.exists() else "")
        return json.loads(out.read_text(encoding="utf-8"))


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not on PATH")


@needs_node
def test_the_workflow_script_carries_each_answer_to_github(tmp_path):
    """python3 in the script is the runner's: a stand-in python3 first on PATH is this interpreter."""
    rec = Recorder(tmp_path)
    passed = {"archive": "success", "install": "success", "verify": "success"}
    failed = {"archive": "success", "install": "success", "verify": "failure"}

    calls = rec.run("failure", failed, [], RED_LOG)
    made = [c for c in calls if c[0] not in ("list", "info")]
    assert [c[0] for c in made] == ["create"]
    assert made[0][1]["labels"] == ["ci-failure"] and made[0][1]["owner"] == "o"
    assert "https://github.com/o/r/actions/runs/7" in made[0][1]["body"]
    assert calls[0] == ["list", {"owner": "o", "repo": "r", "labels": "ci-failure", "state": "open"}]

    calls = rec.run("failure", failed, [issue(12)], RED_LOG)
    made = [c for c in calls if c[0] not in ("list", "info")]
    assert [(c[0], c[1]["issue_number"]) for c in made] == [("createComment", 12)]

    calls = rec.run("success", passed, [issue(12)], "VERIFY GREEN\n")
    made = [c for c in calls if c[0] not in ("list", "info")]
    assert [(c[0], c[1]["issue_number"]) for c in made] == [("createComment", 12), ("update", 12)]
    assert made[1][1]["state"] == "closed" and made[1][1]["state_reason"] == "completed"

    calls = rec.run("success", passed, [], "VERIFY GREEN\n")
    assert [c for c in calls if c[0] not in ("list", "info")] == []


@needs_node
def test_the_workflow_script_closes_a_duplicate_as_not_planned(tmp_path):
    rec = Recorder(tmp_path)
    failed = {"archive": "success", "install": "success", "verify": "failure"}
    calls = rec.run("failure", failed, [issue(30), issue(12)], RED_LOG)
    made = [
        (c[0], c[1]["issue_number"], c[1].get("state_reason")) for c in calls if c[0] not in ("list", "info")
    ]
    assert made == [("createComment", 12, None), ("createComment", 30, None), ("update", 30, "not_planned")]


@needs_node
def test_a_night_stopped_at_install_still_files_its_issue(tmp_path):
    rec = Recorder(tmp_path)
    calls = rec.run("failure", {"archive": "success", "install": "failure", "verify": "skipped"}, [], None)
    (made,) = [c for c in calls if c[0] == "create"]
    assert "the step that failed: install" in made[1]["body"]
