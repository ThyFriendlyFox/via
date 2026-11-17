"""`tools/board.py` and `.github/workflows/board.yml`: a work card stands in the column its body names.

No test reaches the network. The tool runs against a stand-in `gh` (`tests/board/gh.py`), first on
PATH, that records each call and answers from canned JSON. The canned answers take their shape and
their ids from GitHub's guide "Using the API to manage Projects" (docs.github.com, fetched
2026-11-17): the Status field `PVTSSF_lADOANN5s84ACbL0zgBZrZg` with the options `f75ad846` Todo,
`47fc9ee4` In Progress and `98236657` Done ("Finding the node ID of a field"), and the item
`PVTI_lADOANN5s84ACbL0zgBVd94` ("Adding an item to a project"). The issue's `node_id` `MDU6SXNzdWUx`
and number 1347 are those of the example in GitHub's REST reference "REST API endpoints for issues".
The project's own id is a stand-in: the guide prints none for a user's project.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "board.py"
STAND_IN = ROOT / "tests" / "board" / "gh.py"
WORKFLOW = ROOT / ".github" / "workflows" / "board.yml"
BOARD = "https://github.com/users/ThyFriendlyFox/projects/2"

PROJECT_ID = "PVT_stand-in-project"
FIELD_ID = "PVTSSF_lADOANN5s84ACbL0zgBZrZg"
ITEM_ID = "PVTI_lADOANN5s84ACbL0zgBVd94"
ISSUE_ID = "MDU6SXNzdWUx"
OPTION = {"Todo": "f75ad846", "In Progress": "47fc9ee4", "Done": "98236657"}


def event(
    action="opened",
    title="Work card: route the charger",
    body="**Status:** Todo\n",
    state="open",
    association="OWNER",
):
    return {
        "action": action,
        "issue": {
            "number": 1347,
            "node_id": ISSUE_ID,
            "title": title,
            "body": body,
            "state": state,
            "author_association": association,
            "html_url": "https://github.com/ThyFriendlyFox/via/issues/1347",
        },
        "repository": {"full_name": "ThyFriendlyFox/via"},
        "sender": {"login": "octocat"},
    }


def stand_in(tmp_path: Path) -> dict:
    """A PATH whose first folder holds `gh`, which runs the stand-in; the environment that names its log."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{STAND_IN}" "$@"\n', encoding="utf-8")
    gh.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if not k.startswith("BOARD_")}
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    env["BOARD_GH_LOG"] = str(tmp_path / "calls.jsonl")
    return env


def run(tmp_path: Path, ev: dict, board: str = BOARD, **extra: str):
    env = stand_in(tmp_path)
    env.update(extra)
    path = tmp_path / "event.json"
    path.write_text(json.dumps(ev), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--event", str(path), "--board", board],
        capture_output=True,
        text=True,
        env=env,
    )
    return proc, calls(tmp_path)


def calls(tmp_path: Path) -> list[dict]:
    """Each recorded call as its query and its variables (`-f`/`-F` key=value)."""
    log = tmp_path / "calls.jsonl"
    found = []
    for line in log.read_text(encoding="utf-8").splitlines() if log.exists() else []:
        args = json.loads(line)
        assert args[:2] == ["api", "graphql"]
        fields = {}
        for flag, value in zip(args[2::2], args[3::2], strict=True):
            assert flag in ("-f", "-F")
            key, _, val = value.partition("=")
            fields[key] = (flag, val)
        found.append(fields)
    return found


def lines(proc) -> list[str]:
    return [ln for ln in (proc.stdout + proc.stderr).splitlines() if ln.strip()]


def assert_set(found: list[dict], option: str):
    """3 calls: find the project, add the issue, set its Status to the option."""
    assert len(found) == 3
    assert found[0]["login"] == ("-f", "ThyFriendlyFox") and found[0]["number"] == ("-F", "2")
    assert "user(login:" in found[0]["query"][1]
    assert found[1]["project"] == ("-f", PROJECT_ID) and found[1]["content"] == ("-f", ISSUE_ID)
    assert found[2]["project"] == ("-f", PROJECT_ID)
    assert found[2]["item"] == ("-f", ITEM_ID)
    assert found[2]["field"] == ("-f", FIELD_ID)
    assert found[2]["option"] == ("-f", option)


def test_a_card_opened_stands_in_todo(tmp_path):
    """Body `**Status:** Todo`; the project's option named Todo has the id f75ad846 (project.json)."""
    proc, found = run(tmp_path, event())
    assert proc.returncode == 0, proc.stderr
    assert_set(found, OPTION["Todo"])
    assert lines(proc) == [f"board: card #1347 stands in Todo on {BOARD}"]


def test_a_card_edited_to_in_progress_takes_the_option_in_another_case(tmp_path):
    """The card says `In progress`, the project's option is `In Progress` (GitHub's own sample): the
    words match without regard to case, so the option is 47fc9ee4 and the line names the project's
    spelling."""
    proc, found = run(tmp_path, event(action="edited", body="Some text.\n**Status:** In progress\nMore."))
    assert proc.returncode == 0, proc.stderr
    assert_set(found, OPTION["In Progress"])
    assert lines(proc) == [f"board: card #1347 stands in In Progress on {BOARD}"]


def test_the_word_is_matched_without_regard_to_case(tmp_path):
    proc, found = run(tmp_path, event(action="edited", body="**status:**   DONE  "))
    assert proc.returncode == 0, proc.stderr
    assert_set(found, OPTION["Done"])


def test_a_closed_card_is_done_whatever_its_body_says(tmp_path):
    """Closed with `**Status:** Todo` in its body: Done, option 98236657."""
    proc, found = run(tmp_path, event(action="closed", state="closed", body="**Status:** Todo"))
    assert proc.returncode == 0, proc.stderr
    assert_set(found, OPTION["Done"])
    assert lines(proc) == [f"board: card #1347 stands in Done on {BOARD} (the issue is closed)"]


def test_a_closed_card_with_no_status_line_is_done(tmp_path):
    proc, found = run(tmp_path, event(action="closed", state="closed", body=None))
    assert proc.returncode == 0, proc.stderr
    assert_set(found, OPTION["Done"])


def test_a_reopened_card_takes_its_body_again(tmp_path):
    proc, found = run(tmp_path, event(action="reopened", body="**Status:** In progress"))
    assert proc.returncode == 0, proc.stderr
    assert_set(found, OPTION["In Progress"])


def test_a_card_with_no_status_line_is_put_on_the_board_and_left_where_it_stands(tmp_path):
    """2 calls (find, add) and no third: no column is set."""
    proc, found = run(tmp_path, event(body="Route the charger.\nStatus: Todo"))
    assert proc.returncode == 0, proc.stderr
    assert len(found) == 2 and "addProjectV2ItemById" in found[1]["query"][1]
    assert lines(proc) == [
        f"board: card #1347 is on {BOARD} and left where it stands: "
        "its body has no **Status:** line (Todo, In progress or Done)"
    ]


def test_a_card_with_another_word_is_left_where_it_stands(tmp_path):
    proc, found = run(tmp_path, event(action="edited", body="**Status:** Blocked"))
    assert proc.returncode == 0, proc.stderr
    assert len(found) == 2
    assert lines(proc) == [
        f"board: card #1347 is on {BOARD} and left where it stands: "
        'its **Status:** line says "Blocked", not Todo, In progress or Done'
    ]


def test_a_card_with_2_status_lines_is_left_where_it_stands(tmp_path):
    proc, found = run(tmp_path, event(body="**Status:** Todo\n**Status:** Done"))
    assert proc.returncode == 0, proc.stderr
    assert len(found) == 2
    assert lines(proc) == [
        f"board: card #1347 is on {BOARD} and left where it stands: its body has 2 **Status:** lines"
    ]


def test_an_issue_that_is_no_card_is_not_touched(tmp_path):
    proc, found = run(tmp_path, event(title="Routing fails on v0.16"))
    assert proc.returncode == 0, proc.stderr
    assert found == []
    assert lines(proc) == [
        'board: issue #1347 is no work card (its title does not start with "Work card:"); '
        "the board is not changed"
    ]


@pytest.mark.parametrize(
    "association", ["NONE", "CONTRIBUTOR", "FIRST_TIMER", "FIRST_TIME_CONTRIBUTOR", "MANNEQUIN"]
)
def test_a_card_from_a_stranger_is_never_added(tmp_path, association):
    """The 5 values of `author_association` (REST reference, issues) that are not the owner, a member
    or a collaborator."""
    proc, found = run(tmp_path, event(association=association))
    assert proc.returncode == 0, proc.stderr
    assert found == []
    assert lines(proc) == [
        f"board: card #1347 is not from the owner, a member or a collaborator "
        f"(author_association {association}); the board is not changed"
    ]


@pytest.mark.parametrize("association", ["OWNER", "MEMBER", "COLLABORATOR"])
def test_a_card_from_the_owner_a_member_or_a_collaborator_is_moved(tmp_path, association):
    proc, found = run(tmp_path, event(association=association))
    assert proc.returncode == 0, proc.stderr
    assert len(found) == 3


def test_a_project_with_no_such_column_fails_in_1_line(tmp_path):
    """project-two-columns.json has Todo and Done: a card that says In progress has no column."""
    proc, found = run(
        tmp_path, event(body="**Status:** In progress"), BOARD_GH_PROJECT="project-two-columns.json"
    )
    assert proc.returncode == 1
    assert len(found) == 2
    assert lines(proc) == [
        f'board: FAIL: the project {BOARD} has no Status option "In progress"; its options are Todo, Done'
    ]


def test_gh_failing_fails_the_tool_in_1_line_with_no_traceback(tmp_path):
    """gh with no token: exit 4 and 2 lines on stderr (gh-no-auth.txt, gh 2.89.0 run on 2026-11-17)."""
    proc, found = run(tmp_path, event(), BOARD_GH_FAIL="gh-no-auth.txt", BOARD_GH_FAIL_CODE="4")
    assert proc.returncode == 1
    assert len(found) == 1
    assert "Traceback" not in proc.stderr
    assert lines(proc) == [
        "board: FAIL: gh api graphql (find the project) exited 4: "
        "To get started with GitHub CLI, please run:  gh auth login"
    ]


def test_gh_missing_fails_in_1_line(tmp_path):
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path)}
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event()), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(TOOL), "--event", str(path), "--board", BOARD],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 1
    assert lines(proc) == ["board: FAIL: gh is not on PATH"]


def test_an_organization_board_is_found_under_organization(tmp_path):
    """An org's project URL asks `organization(login:)`; the canned answer is a user's, so the tool
    finds no project under `organization` and says so."""
    url = "https://github.com/orgs/acme/projects/7"
    proc, found = run(tmp_path, event(), board=url)
    assert len(found) == 1
    assert "organization(login:" in found[0]["query"][1]
    assert found[0]["login"] == ("-f", "acme") and found[0]["number"] == ("-F", "7")
    assert proc.returncode == 1
    assert lines(proc) == [f"board: FAIL: no project 7 of acme at {url}"]


@pytest.mark.parametrize(
    "url", ["https://github.com/ThyFriendlyFox/via", "https://github.com/users/x/projects/two", ""]
)
def test_a_board_that_is_no_project_url_fails_before_any_call(tmp_path, url):
    proc, found = run(tmp_path, event(), board=url)
    assert proc.returncode == 1
    assert found == []
    assert len(lines(proc)) == 1 and lines(proc)[0].startswith(
        f'board: FAIL: --board "{url}" is no project URL'
    )


def test_an_event_that_is_no_issue_fails_in_1_line(tmp_path):
    proc, found = run(tmp_path, {"action": "created", "comment": {}})
    assert proc.returncode == 1
    assert found == []
    assert len(lines(proc)) == 1 and lines(proc)[0].startswith("board: FAIL: ")
    assert "no issues event" in lines(proc)[0]


def test_the_tool_runs_on_the_standard_library_alone(tmp_path):
    """`-S` leaves site-packages out: an import from outside the standard library would fail."""
    proc = subprocess.run([sys.executable, "-I", "-S", str(TOOL), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert "--event" in proc.stdout and "--board" in proc.stdout


# The workflow.


def workflow() -> dict:
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    # PyYAML reads the key `on` as True (YAML 1.1).
    data["on"] = data.pop(True)
    return data


def steps() -> list[dict]:
    return [s for job in workflow()["jobs"].values() for s in job["steps"]]


def card_step() -> dict:
    [step] = [s for s in steps() if "tools/board.py" in s.get("run", "")]
    return step


def test_the_workflow_runs_on_the_4_issue_events_and_no_other():
    assert workflow()["on"] == {"issues": {"types": ["opened", "edited", "closed", "reopened"]}}


def test_the_workflow_asks_for_no_permission_but_to_read_the_code():
    """The token GitHub gives the job reads the repository to check out the tool; it writes nothing.
    The project is changed with BOARD_TOKEN alone."""
    flow = workflow()
    assert flow["permissions"] == {}
    for job in flow["jobs"].values():
        assert job["permissions"] == {"contents": "read"}
        assert job["timeout-minutes"] <= 10
    checkout = [s for s in steps() if s.get("uses", "").startswith("actions/checkout@")]
    assert len(checkout) == 1 and checkout[0]["with"]["persist-credentials"] is False


def test_no_run_step_holds_an_expression():
    """An issue's title and body are text from anyone. No `run:` holds `${{ ... }}`, so none can be
    written into a shell line; the tool reads them from the event file."""
    found = [s for s in steps() if "run" in s]
    assert found
    assert [s.get("name") for s in found if "${{" in s["run"] or "github.event" in s["run"]] == []
    assert "github.event.issue" not in "".join(s["run"] for s in found)


def test_the_token_and_the_board_come_from_the_secret_and_the_variable():
    env = card_step()["env"]
    assert env["GH_TOKEN"] == "${{ secrets.BOARD_TOKEN }}"
    assert env["BOARD_URL"] == f"${{{{ vars.BOARD_URL || '{BOARD}' }}}}"


def run_step(tmp_path: Path, token: str):
    env = stand_in(tmp_path)
    env["GH_TOKEN"] = token
    env["BOARD_URL"] = BOARD
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event()), encoding="utf-8")
    env["GITHUB_EVENT_PATH"] = str(path)
    return subprocess.run(
        ["bash", "-e", "-c", card_step()["run"]], cwd=ROOT, capture_output=True, text=True, env=env
    )


def test_with_no_secret_the_step_says_so_in_1_line_and_ends_green(tmp_path):
    proc = run_step(tmp_path, "")
    assert proc.returncode == 0, proc.stderr
    assert lines(proc) == ["board: no secret BOARD_TOKEN is set, so the board is not changed"]
    assert calls(tmp_path) == []


def test_with_the_secret_the_step_runs_the_tool_on_the_event_file(tmp_path):
    proc = run_step(tmp_path, "stand-in-token")
    assert proc.returncode == 0, proc.stderr
    assert_set(calls(tmp_path), OPTION["Todo"])
    assert lines(proc) == [f"board: card #1347 stands in Todo on {BOARD}"]
