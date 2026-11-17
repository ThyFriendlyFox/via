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

import importlib.util
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
REPO = "ThyFriendlyFox/via"

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


def test_spaces_inside_the_word_are_read_as_1(tmp_path):
    """`In   progress` (3 spaces) is the word `In progress`, so the option is In Progress, 47fc9ee4."""
    proc, found = run(tmp_path, event(action="edited", body="**Status:** In   progress"))
    assert proc.returncode == 0, proc.stderr
    assert_set(found, OPTION["In Progress"])


# A line that renders as an example (a code block) or not at all (an HTML comment) is not the card's.

FENCED = "Not started.\n\nWhen finished, change the line to:\n```\n**Status:** Done\n```"


def test_a_status_line_inside_a_code_fence_is_not_the_cards(tmp_path):
    """The reviewer's body: no line of its own, 1 example in a ``` fence. 0 lines count, 1 does not:
    added and left where it stands, 2 calls."""
    proc, found = run(tmp_path, event(action="edited", body=FENCED))
    assert proc.returncode == 0, proc.stderr
    assert len(found) == 2
    assert lines(proc) == [
        f"board: card #1347 is on {BOARD} and left where it stands: its body has no **Status:** line "
        "outside code and HTML comments (1 inside, which does not count)"
    ]


def test_the_cards_line_beside_an_example_in_a_fence_decides(tmp_path):
    """`In progress` outside, `Done` inside a fence: 1 line counts, so In Progress, 47fc9ee4."""
    body = "**Status:** In progress\n\nWhen finished:\n```\n**Status:** Done\n```\n"
    proc, found = run(tmp_path, event(action="edited", body=body))
    assert proc.returncode == 0, proc.stderr
    assert_set(found, OPTION["In Progress"])


def test_a_fence_closes_only_on_its_own_mark_at_its_own_length(tmp_path):
    """A ```` fence (4) holds a ``` line (3) and a ~~~ line: neither closes it (CommonMark 0.31.2,
    4.5 Fenced code blocks). The Done inside does not count; Todo after the ```` close does."""
    body = "````\n```\n**Status:** Done\n~~~\n````\n**Status:** Todo"
    proc, found = run(tmp_path, event(action="edited", body=body))
    assert proc.returncode == 0, proc.stderr
    assert_set(found, OPTION["Todo"])


def test_an_unclosed_fence_runs_to_the_end_of_the_body(tmp_path):
    """CommonMark 0.31.2, 4.5: a fence with no close runs to the end. 0 count, 1 inside."""
    proc, found = run(tmp_path, event(action="edited", body="Notes.\n~~~\n**Status:** Done"))
    assert proc.returncode == 0, proc.stderr
    assert len(found) == 2
    assert "(1 inside, which does not count)" in lines(proc)[0]


def test_a_line_indented_4_spaces_is_not_the_cards(tmp_path):
    """4 spaces start an indented code block (CommonMark 0.31.2, 4.4); 3 are still the line's own."""
    four, three = tmp_path / "four", tmp_path / "three"
    four.mkdir()
    three.mkdir()
    proc, found = run(four, event(action="edited", body="Notes.\n\n    **Status:** Done\n"))
    assert len(found) == 2 and "(1 inside, which does not count)" in lines(proc)[0]
    proc, found = run(three, event(action="edited", body="Notes.\n\n   **Status:** Done\n"))
    assert_set(found, OPTION["Done"])


def test_status_lines_inside_an_html_comment_do_not_count(tmp_path):
    """The reviewer's second body: 1 line in a fence and 1 in a <!-- --> block, none outside. 2 inside."""
    body = (
        "Status: in progress, not done yet.\n\nThe line to write when it is finished:\n```\n"
        "**Status:** Done\n```\n<!--\n**Status:** Done\n-->"
    )
    proc, found = run(tmp_path, event(action="edited", body=body))
    assert proc.returncode == 0, proc.stderr
    assert len(found) == 2
    assert lines(proc) == [
        f"board: card #1347 is on {BOARD} and left where it stands: its body has no **Status:** line "
        "outside code and HTML comments (2 inside, which do not count)"
    ]


def test_a_comment_after_the_word_on_the_same_line_is_not_part_of_it(tmp_path):
    """`**Status:** Todo <!-- was Done -->` renders as `**Status:** Todo`: Todo, f75ad846."""
    proc, found = run(tmp_path, event(action="edited", body="**Status:** Todo <!-- was Done -->"))
    assert proc.returncode == 0, proc.stderr
    assert_set(found, OPTION["Todo"])


def test_a_comment_that_does_not_close_is_not_judged(tmp_path):
    """`<!--` with no `-->`: which lines render is not judged, so the card is left where it stands."""
    proc, found = run(tmp_path, event(action="edited", body="**Status:** Todo\n<!-- notes\n**Status:** Done"))
    assert proc.returncode == 0, proc.stderr
    assert len(found) == 2
    assert lines(proc) == [
        f"board: card #1347 is on {BOARD} and left where it stands: its body opens an HTML comment "
        "(<!--) that does not close, so which lines render is not judged"
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


def test_a_graphql_errors_key_fails_even_beside_full_data(tmp_path):
    """gh exits 0 and prints data and errors side by side: 1 call, then the error's message."""
    proc, found = run(tmp_path, event(), BOARD_GH_PROJECT="project-errors.json")
    assert proc.returncode == 1
    assert len(found) == 1
    assert lines(proc) == [
        "board: FAIL: gh api graphql (find the project) answered with an error: "
        "stand-in error beside a full data answer"
    ]


def test_an_error_given_as_text_fails_in_1_line(tmp_path):
    """`{"errors": ["something went wrong"]}`: the entry is text, not an object with a message."""
    proc, found = run(tmp_path, event(), BOARD_GH_PROJECT="project-errors-text.json")
    assert proc.returncode == 1 and len(found) == 1
    assert lines(proc) == [
        "board: FAIL: gh api graphql (find the project) answered with an error: something went wrong"
    ]


def test_gh_printing_no_json_fails_in_1_line(tmp_path):
    proc, found = run(tmp_path, event(), BOARD_GH_PROJECT="not-json.txt")
    assert proc.returncode == 1 and len(found) == 1
    assert lines(proc) == [
        "board: FAIL: gh api graphql (find the project) printed no JSON: '502 Bad Gateway\\n'"
    ]


def test_a_status_field_with_no_options_list_fails_in_1_line(tmp_path):
    proc, found = run(tmp_path, event(), BOARD_GH_PROJECT="project-options-null.json")
    assert proc.returncode == 1 and len(found) == 1
    assert lines(proc) == [f"board: FAIL: the project {BOARD}'s field Status answered options None, no list"]


def test_the_status_field_is_found_by_its_name_not_its_place(tmp_path):
    """Priority (P1, P2) comes before Status: the field taken is Status, so Todo is f75ad846."""
    proc, found = run(tmp_path, event(), BOARD_GH_PROJECT="project-priority-first.json")
    assert proc.returncode == 0, proc.stderr
    assert_set(found, OPTION["Todo"])


def test_an_add_that_returns_no_item_fails_in_1_line(tmp_path):
    """add-no-item.json answers `item: null`: 2 calls, no third."""
    proc, found = run(tmp_path, event(), BOARD_GH_ADD="add-no-item.json")
    assert proc.returncode == 1 and len(found) == 2
    assert lines(proc) == ["board: FAIL: gh api graphql (add the issue) returned no item for card #1347"]


def test_gh_that_gives_no_answer_in_time_fails_in_1_line(tmp_path, monkeypatch, capsys):
    """The tool's limit set to 1 s, the stand-in waits 3 s: the call is cut at 1 s, 1 call logged."""
    spec = importlib.util.spec_from_file_location("board_tool", TOOL)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    monkeypatch.setattr(tool, "GH_TIMEOUT_S", 1)
    for key, value in stand_in(tmp_path).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("BOARD_GH_SLEEP", "3")
    path = tmp_path / "event.json"
    path.write_text(json.dumps(event()), encoding="utf-8")
    assert tool.main(["--event", str(path), "--board", BOARD]) == 1
    assert capsys.readouterr().err == "board: FAIL: gh api graphql (find the project) gave no answer in 1 s\n"


def run_file(tmp_path: Path, data: bytes, *flags: str):
    path = tmp_path / "event.json"
    path.write_bytes(data)
    env = stand_in(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(TOOL), *(flags or ("--event", str(path), "--board", BOARD))],
        capture_output=True,
        text=True,
        env=env,
    )
    return proc, calls(tmp_path)


def test_an_event_file_that_is_no_utf8_fails_in_1_line(tmp_path):
    proc, found = run_file(tmp_path, b'\xff\xfe{"issue": 1}')
    assert proc.returncode == 1 and found == []
    assert len(lines(proc)) == 1 and "Traceback" not in proc.stderr
    assert lines(proc)[0].startswith(f"board: FAIL: {tmp_path / 'event.json'} could not be read as JSON: ")


def test_a_body_that_is_no_text_fails_in_1_line(tmp_path):
    proc, found = run(tmp_path, event(body=5))
    assert proc.returncode == 1 and found == []
    assert lines(proc) == ["board: FAIL: issue #1347's body is 5, neither text nor null"]


USAGE = "(board.py --event <file> --board <url>, or board.py --all --repo <owner>/<name> --board <url>)"


def test_a_missing_flag_fails_in_1_line_with_exit_1(tmp_path):
    proc, found = run_file(tmp_path, b"{}", "--event", "x.json")
    assert proc.returncode == 1 and found == []
    assert lines(proc) == [f"board: FAIL: the following arguments are required: --board {USAGE}"]


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


def test_the_workflow_has_3_triggers_the_issue_events_by_hand_and_once_a_day():
    """The 4 issue events as before, a run by hand, and 1 schedule whose minute is not 0: GitHub delays
    scheduled runs at the start of every hour ("Events that trigger workflows", schedule)."""
    on = workflow()["on"]
    assert sorted(on) == ["issues", "schedule", "workflow_dispatch"]
    assert on["issues"] == {"types": ["opened", "edited", "closed", "reopened"]}
    assert on["workflow_dispatch"] is None
    [entry] = on["schedule"]
    minute, hour, day, month, weekday = entry["cron"].split()
    assert (day, month, weekday) == ("*", "*", "*")
    assert minute.isdigit() and 0 < int(minute) < 60
    assert hour.isdigit() and 0 <= int(hour) < 24


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


def test_every_run_of_the_board_waits_in_1_queue():
    """1 group for every run, whatever its trigger: a run of all cards and a run of 1 card never write
    at the same moment. The group is a word, not an expression, so it is never empty. `queue: max`
    keeps up to 100 runs waiting instead of 1, so no card's run is cancelled by the next one; it may
    not be combined with cancelling ("Control the concurrency of workflows and jobs")."""
    assert workflow()["concurrency"] == {"group": "board", "cancel-in-progress": False, "queue": "max"}
    assert all("concurrency" not in job for job in workflow()["jobs"].values())


def test_the_sparse_checkout_holds_the_file_the_step_runs():
    """The step runs `python3 tools/board.py`; the checkout takes that path and nothing else, read as a
    path (cone mode off), and the path is a file of the repository."""
    [checkout] = [s for s in steps() if s.get("uses", "").startswith("actions/checkout@")]
    paths = checkout["with"]["sparse-checkout"].split()
    assert paths == ["tools/board.py"]
    assert checkout["with"]["sparse-checkout-cone-mode"] is False
    assert f"python3 {paths[0]} " in card_step()["run"]
    assert (ROOT / paths[0]).resolve() == TOOL


def test_the_token_and_the_board_come_from_the_secret_and_the_variable():
    env = card_step()["env"]
    assert env["GH_TOKEN"] == "${{ secrets.BOARD_TOKEN }}"
    assert env["BOARD_URL"] == f"${{{{ vars.BOARD_URL || '{BOARD}' }}}}"


def run_step(tmp_path: Path, token: str, event_name: str = "issues", **extra: str):
    env = stand_in(tmp_path)
    env.update(extra)
    env["GH_TOKEN"] = token
    env["BOARD_URL"] = BOARD
    env["GITHUB_EVENT_NAME"] = event_name
    env["GITHUB_REPOSITORY"] = REPO
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


# A run of every card: `--all`. The canned pages take their shape from GitHub's public GraphQL schema
# (docs.github.com/public/fpt/schema.docs.graphql, fetched 2026-11-17): `Repository.issues` is an
# IssueConnection of Issue (number, id, title, body, state OPEN or CLOSED, authorAssociation),
# `ProjectV2.items` a connection of ProjectV2Item (id, content: DraftIssue | Issue | PullRequest,
# fieldValues), a single-select value has `name`, `optionId` and `field`, and every page has
# `pageInfo { hasNextPage endCursor }`. Ids and cursors are stand-ins; a page holds at most 100 nodes
# ("Using pagination in the GraphQL API": first is between 1 and 100).

PAGE = 100


def card(number, body="**Status:** Todo\n", state="OPEN", title=None, association="OWNER"):
    """An issue as `repository.issues` answers it."""
    return {
        "number": number,
        "id": f"I_stand-in-{number}",
        "title": f"Work card: item {number}" if title is None else title,
        "body": body,
        "state": state,
        "authorAssociation": association,
    }


def item(number, column=None, kind="Issue"):
    """A project item for issue `number` (or a pull request), standing in `column` or in none. A field
    value of another kind matches none of the query's fragments and comes back as {}."""
    values = [{}]
    if column:
        values.append({"name": column, "optionId": OPTION[column], "field": {"id": FIELD_ID}})
    prefix = "I" if kind == "Issue" else "PR"
    return {
        "id": f"PVTI_stand-in-{number}",
        "content": {"__typename": kind, "id": f"{prefix}_stand-in-{number}"},
        "fieldValues": {"nodes": values},
    }


def pages(nodes: list, wrap) -> dict:
    """The answers by cursor: "" for the first page, then `stand-in-cursor-<k>`."""
    chunks = [nodes[i : i + PAGE] for i in range(0, len(nodes), PAGE)] or [[]]
    answers = {}
    for k, chunk in enumerate(chunks):
        more = k + 1 < len(chunks)
        info = {"hasNextPage": more, "endCursor": f"stand-in-cursor-{k + 1}" if more or chunk else None}
        answers["" if k == 0 else f"stand-in-cursor-{k}"] = wrap({"pageInfo": info, "nodes": chunk})
    return answers


def run_all(tmp_path: Path, issues: list, items: list, *flags: str, **extra: str):
    env = stand_in(tmp_path)
    issues_file, items_file = tmp_path / "issues.json", tmp_path / "items.json"
    issues_file.write_text(
        json.dumps(pages(issues, lambda c: {"data": {"repository": {"issues": c}}})), encoding="utf-8"
    )
    items_file.write_text(
        json.dumps(pages(items, lambda c: {"data": {"node": {"items": c}}})), encoding="utf-8"
    )
    env.update(BOARD_GH_ISSUES=str(issues_file), BOARD_GH_ITEMS=str(items_file), BOARD_GH_ADD_ECHO="1")
    env.update(extra)
    proc = subprocess.run(
        [sys.executable, str(TOOL), *(flags or ("--all", "--repo", REPO, "--board", BOARD))],
        capture_output=True,
        text=True,
        env=env,
    )
    return proc, calls(tmp_path)


def kind(call: dict) -> str:
    query = call["query"][1]
    for name, mark in (
        ("issues", "issues(first"),
        ("items", "items(first"),
        ("add", "addProjectV2ItemById"),
        ("set", "updateProjectV2ItemFieldValue"),
        ("find", "projectV2(number"),
    ):
        if mark in query:
            return name
    raise AssertionError(f"a call of no known kind: {query[:60]}")


def writes(found: list[dict]) -> list[tuple]:
    """The writes in order: ("add", issue id) and ("set", item id, option id)."""
    out = []
    for call in found:
        if kind(call) == "add":
            assert call["project"] == ("-f", PROJECT_ID)
            out.append(("add", call["content"][1]))
        elif kind(call) == "set":
            assert call["project"] == ("-f", PROJECT_ID) and call["field"] == ("-f", FIELD_ID)
            out.append(("set", call["item"][1], call["option"][1]))
    return out


def summary(moved=0, added=0, there=0, not_moved=0, failed=0) -> str:
    cards = moved + added + there + not_moved + failed
    return (
        f"board: {cards} cards: {moved} moved, {added} added, {there} already there, "
        f"{not_moved} not moved, {failed} failed"
    )


def test_all_moves_a_card_that_stands_in_the_wrong_column(tmp_path):
    """#82 says In progress and stands in Todo: 1 write, the option In Progress (47fc9ee4) on its item.
    Calls: find 1 + issues 1 page + items 1 page + set 1 = 4."""
    proc, found = run_all(tmp_path, [card(82, "**Status:** In progress")], [item(82, "Todo")])
    assert proc.returncode == 0, proc.stderr
    assert [kind(c) for c in found] == ["find", "issues", "items", "set"]
    assert found[1]["owner"] == ("-f", "ThyFriendlyFox") and found[1]["name"] == ("-f", "via")
    assert "cursor" not in found[1] and "cursor" not in found[2]
    assert found[2]["project"] == ("-f", PROJECT_ID)
    assert writes(found) == [("set", "PVTI_stand-in-82", OPTION["In Progress"])]
    assert lines(proc) == ["#82 In Progress: moved from Todo", summary(moved=1)]


def test_all_does_not_write_a_card_in_the_right_column(tmp_path):
    """#64 says In progress and stands in In Progress: 3 reads, 0 writes."""
    proc, found = run_all(tmp_path, [card(64, "**Status:** In progress")], [item(64, "In Progress")])
    assert proc.returncode == 0, proc.stderr
    assert [kind(c) for c in found] == ["find", "issues", "items"]
    assert lines(proc) == ["#64 In Progress: already there", summary(there=1)]


def test_all_adds_and_places_a_card_that_is_not_on_the_project(tmp_path):
    """#77 says Todo and has no item: add it (the echo answers PVTI_for_I_stand-in-77), then set Todo
    (f75ad846) on that item. 3 reads + 2 writes = 5 calls."""
    proc, found = run_all(tmp_path, [card(77)], [])
    assert proc.returncode == 0, proc.stderr
    assert len(found) == 5
    assert writes(found) == [
        ("add", "I_stand-in-77"),
        ("set", "PVTI_for_I_stand-in-77", OPTION["Todo"]),
    ]
    assert lines(proc) == ["#77 Todo: added and placed", summary(added=1)]


def test_all_puts_a_closed_card_in_done(tmp_path):
    """#70 is closed and its body still says In progress; it stands in In Progress: Done, 98236657."""
    proc, found = run_all(
        tmp_path, [card(70, "**Status:** In progress", state="CLOSED")], [item(70, "In Progress")]
    )
    assert proc.returncode == 0, proc.stderr
    assert writes(found) == [("set", "PVTI_stand-in-70", OPTION["Done"])]
    assert lines(proc) == ["#70 Done: moved from In Progress (the issue is closed)", summary(moved=1)]


def test_all_reports_a_card_with_no_status_line_and_moves_the_others(tmp_path):
    """#90 (no line, in Todo) is reported and not written; #91 (no line, not on the project) is added
    and left in no column, as the event path does; #82 still moves. Lines in the order of the number."""
    issues = [
        card(91, "Route the charger."),
        card(90, "Route the charger."),
        card(82, "**Status:** In progress"),
    ]
    proc, found = run_all(tmp_path, issues, [item(90, "Todo"), item(82, "Todo")])
    assert proc.returncode == 0, proc.stderr
    assert writes(found) == [("set", "PVTI_stand-in-82", OPTION["In Progress"]), ("add", "I_stand-in-91")]
    no_line = "its body has no **Status:** line (Todo, In progress or Done)"
    assert lines(proc) == [
        "#82 In Progress: moved from Todo",
        f"#90 not moved: {no_line}",
        f"#91 not moved: {no_line}; added to the board",
        summary(moved=1, not_moved=2),
    ]


def test_all_leaves_an_issue_that_is_no_card_and_a_pull_request_alone(tmp_path):
    """#5 is an issue titled as no card, standing in Todo with `**Status:** Done`; #6 is a pull request
    on the project in Todo. `repository.issues` holds issues only (an IssueConnection), so a pull
    request is never read as a card. Only #82 is written, and only #82 is printed."""
    issues = [
        card(5, "**Status:** Done", title="Routing fails on v0.16"),
        card(82, "**Status:** In progress"),
    ]
    items = [item(5, "Todo"), item(6, "Todo", kind="PullRequest"), item(82, "Todo")]
    proc, found = run_all(tmp_path, issues, items)
    assert proc.returncode == 0, proc.stderr
    assert writes(found) == [("set", "PVTI_stand-in-82", OPTION["In Progress"])]
    assert lines(proc) == ["#82 In Progress: moved from Todo", summary(moved=1)]


def test_all_reads_2_pages_of_issues_and_of_items(tmp_path):
    """101 cards: 100 on the first page of each, 1 on the second. #101 says Todo and stands in Done;
    the other 100 stand in Todo. Calls: find 1 + issues 2 + items 2 + set 1 = 6; the second page of
    each is asked with the first page's endCursor."""
    issues = [card(n) for n in range(1, 102)]
    items = [item(n, "Todo") for n in range(1, 101)] + [item(101, "Done")]
    proc, found = run_all(tmp_path, issues, items)
    assert proc.returncode == 0, proc.stderr
    assert [kind(c) for c in found] == ["find", "issues", "issues", "items", "items", "set"]
    assert found[2]["cursor"] == ("-f", "stand-in-cursor-1")
    assert found[4]["cursor"] == ("-f", "stand-in-cursor-1")
    assert writes(found) == [("set", "PVTI_stand-in-101", OPTION["Todo"])]
    assert lines(proc)[-2:] == ["#101 Todo: moved from Done", summary(moved=1, there=100)]
    assert len(lines(proc)) == 102


def test_all_reports_a_failing_write_writes_the_rest_and_ends_non_zero(tmp_path):
    """#82 and #83 both stand in Todo and say In progress; the write of #82's item is refused. #83 is
    still written; the run prints 1 line for the failure and ends with exit 1."""
    issues = [card(82, "**Status:** In progress"), card(83, "**Status:** In progress")]
    proc, found = run_all(
        tmp_path, issues, [item(82, "Todo"), item(83, "Todo")], BOARD_GH_FAIL_ITEM="PVTI_stand-in-82"
    )
    assert proc.returncode == 1
    assert writes(found) == [
        ("set", "PVTI_stand-in-82", OPTION["In Progress"]),
        ("set", "PVTI_stand-in-83", OPTION["In Progress"]),
    ]
    assert lines(proc) == [
        "#82 FAIL: gh api graphql (set the Status) exited 1: stand-in gh: this write is refused on purpose",
        "#83 In Progress: moved from Todo",
        summary(moved=1, failed=1),
    ]


def test_all_stops_in_1_line_when_a_page_cannot_be_read(tmp_path):
    """The issues answer says a second page exists, but the stand-in has none for its cursor: no card
    is judged on half a list, so nothing is written and the run ends with exit 1."""
    env_issues = {"": pages([card(1)], lambda c: {"data": {"repository": {"issues": c}}})[""]}
    env_issues[""]["data"]["repository"]["issues"]["pageInfo"]["hasNextPage"] = True
    path = tmp_path / "broken-issues.json"
    path.write_text(json.dumps(env_issues), encoding="utf-8")
    proc, found = run_all(tmp_path, [card(1)], [], BOARD_GH_ISSUES=str(path))
    assert proc.returncode == 1
    assert writes(found) == []
    assert lines(proc) == [
        "board: FAIL: gh api graphql (list the issues, page 2) exited 1: "
        "stand-in gh: no page for the cursor 'stand-in-cursor-1'"
    ]


def test_all_stops_when_a_page_says_more_but_names_no_cursor(tmp_path):
    """hasNextPage true and endCursor null: asking again would read the first page forever."""
    broken = pages([card(1)], lambda c: {"data": {"repository": {"issues": c}}})
    broken[""]["data"]["repository"]["issues"]["pageInfo"] = {"hasNextPage": True, "endCursor": None}
    path = tmp_path / "broken-issues.json"
    path.write_text(json.dumps(broken), encoding="utf-8")
    proc, found = run_all(tmp_path, [card(1)], [], BOARD_GH_ISSUES=str(path))
    assert proc.returncode == 1 and writes(found) == []
    assert lines(proc) == [
        "board: FAIL: gh api graphql (list the issues, page 1) says another page follows but names no cursor"
    ]


def ask_stand_in(tmp_path: Path, query: str, **extra: str) -> dict:
    """1 call of the stand-in itself, as the tool makes it; its answer."""
    env = stand_in(tmp_path)
    env.update(extra)
    proc = subprocess.run(
        [sys.executable, str(STAND_IN), "api", "graphql", "-f", f"query={query}", "-f", "project=P"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_stand_in_answers_only_the_fields_and_states_an_issues_query_asks_for(tmp_path):
    """GitHub answers the fields a query names and no other, and `states` filters the issues. The
    canned page holds #1 (OPEN) and #2 (CLOSED) with all 6 keys and a pageInfo of 2 keys. The query
    names number and title, hasNextPage, and states [OPEN]: #2 goes, and of #1 2 keys of 6 stay."""
    path = tmp_path / "issues.json"
    canned = [card(1), card(2, state="CLOSED")]
    path.write_text(json.dumps(pages(canned, lambda c: {"data": {"repository": {"issues": c}}})), "utf-8")
    query = """query($owner: String!, $name: String!, $cursor: String) {
      repository(owner: $owner, name: $name) {
        issues(first: 100, after: $cursor, states: [OPEN], orderBy: {field: CREATED_AT, direction: ASC}) {
          pageInfo { hasNextPage }
          nodes { number title }
        }
      }
    }"""
    answer = ask_stand_in(tmp_path, query, BOARD_GH_ISSUES=str(path))
    assert answer == {
        "data": {
            "repository": {
                "issues": {
                    "pageInfo": {"hasNextPage": False},
                    "nodes": [{"number": 1, "title": "Work card: item 1"}],
                }
            }
        }
    }


def test_the_stand_in_answers_only_the_fields_an_items_query_asks_for(tmp_path):
    """Fragments (`... on X { }`) add their fields to the level they stand at. The query asks for the
    item's id, its content's id and each value's field id: __typename, name and optionId go."""
    path = tmp_path / "items.json"
    path.write_text(
        json.dumps(pages([item(82, "Todo")], lambda c: {"data": {"node": {"items": c}}})), "utf-8"
    )
    query = """query($project: ID!, $cursor: String) {
      node(id: $project) { ... on ProjectV2 { items(first: 100, after: $cursor) { nodes {
        id content { ... on Issue { id } }
        fieldValues(first: 50) { nodes { ... on ProjectV2ItemFieldSingleSelectValue {
          field { ... on ProjectV2FieldCommon { id } } } } }
      } } } }
    }"""
    answer = ask_stand_in(tmp_path, query, BOARD_GH_ITEMS=str(path))
    node = {
        "id": "PVTI_stand-in-82",
        "content": {"id": "I_stand-in-82"},
        "fieldValues": {"nodes": [{}, {"field": {"id": FIELD_ID}}]},
    }
    assert answer == {"data": {"node": {"items": {"nodes": [node]}}}}


@pytest.mark.parametrize("key", ["authorAssociation", "body", "state", "title"])
def test_all_fails_a_card_whose_node_lacks_a_key_and_moves_the_others(tmp_path, key):
    """A node without a key the decision reads is not judged: no owner is not a stranger, and no body
    is not an empty one. #82 lacks the key; #83 says In progress and stands in Todo. Lines: 1 FAIL,
    1 moved; counts 1 moved + 1 failed = 2 cards; exit 1; only #83's item is written."""
    broken = card(82, "**Status:** In progress")
    del broken[key]
    issues = [broken, card(83, "**Status:** In progress")]
    proc, found = run_all(tmp_path, issues, [item(82, "Todo"), item(83, "Todo")])
    assert proc.returncode == 1
    assert writes(found) == [("set", "PVTI_stand-in-83", OPTION["In Progress"])]
    assert lines(proc) == [
        f"#82 FAIL: GitHub answered no {key}",
        "#83 In Progress: moved from Todo",
        summary(moved=1, failed=1),
    ]


def test_all_reads_a_null_body_as_an_empty_one(tmp_path):
    """GitHub answers `body: null` for an issue opened with no text. That body is judged: it has no
    line, so #84 (in Todo) is not moved, nothing is written, and the run ends with exit 0."""
    proc, found = run_all(tmp_path, [card(84, None)], [item(84, "Todo")])
    assert proc.returncode == 0, proc.stderr
    assert writes(found) == []
    no_line = "its body has no **Status:** line (Todo, In progress or Done)"
    assert lines(proc) == [f"#84 not moved: {no_line}", summary(not_moved=1)]


def test_all_reads_the_status_field_only_not_another_single_select_value(tmp_path):
    """#64 says Todo; its item holds Todo in Status (FIELD_ID) and then P1 in a field Priority. The
    column is Status's value alone: already there, 3 reads, 0 writes, not 'moved from P1'."""
    standing = item(64, "Todo")
    priority = {"name": "P1", "optionId": "stand-in-p1", "field": {"id": "PVTSSF_stand-in-priority"}}
    standing["fieldValues"]["nodes"].append(priority)
    proc, found = run_all(tmp_path, [card(64)], [standing])
    assert proc.returncode == 0, proc.stderr
    assert [kind(c) for c in found] == ["find", "issues", "items"]
    assert lines(proc) == ["#64 Todo: already there", summary(there=1)]


@pytest.mark.parametrize(
    "flags, said",
    [
        (("--all", "--board", BOARD), f"--all needs --repo <owner>/<name> {USAGE}"),
        (("--all", "--repo", "via", "--board", BOARD), f'--repo "via" is no <owner>/<name> {USAGE}'),
        (("--repo", REPO, "--board", BOARD), f"one of the arguments --event --all is required {USAGE}"),
    ],
)
def test_all_with_a_wrong_flag_fails_in_1_line_before_any_call(tmp_path, flags, said):
    proc, found = run_all(tmp_path, [], [], *flags)
    assert proc.returncode == 1 and found == []
    assert lines(proc) == [f"board: FAIL: {said}"]


# The event path and `--all` decide with 1 function: for the same card they write the same column.
# The expected column of each case is the rule worked by hand: closed is Done; else the 1 line's word.
SAME = [
    ("Todo", "**Status:** Todo", "open", "OWNER", "Work card: x", "Todo"),
    ("In progress", "**Status:** In progress", "open", "OWNER", "Work card: x", "In Progress"),
    ("case and spaces", "**status:**   DONE  ", "open", "MEMBER", "Work card: x", "Done"),
    ("closed", "**Status:** Todo", "closed", "OWNER", "Work card: x", "Done"),
    ("closed with no line", "", "closed", "COLLABORATOR", "Work card: x", "Done"),
    ("no line", "Route the charger.", "open", "OWNER", "Work card: x", None),
    ("2 lines", "**Status:** Todo\n**Status:** Done", "open", "OWNER", "Work card: x", None),
    ("another word", "**Status:** Blocked", "open", "OWNER", "Work card: x", None),
    ("only in a fence", FENCED, "open", "OWNER", "Work card: x", None),
    ("a stranger's", "**Status:** Todo", "open", "NONE", "Work card: x", None),
    ("no card", "**Status:** Todo", "open", "OWNER", "Routing fails on v0.16", None),
]


@pytest.mark.parametrize("case, body, state, association, title, column", SAME, ids=[s[0] for s in SAME])
def test_the_event_path_and_all_write_the_same_column(
    tmp_path, case, body, state, association, title, column
):
    """The card is not on the project in the `--all` run, so both paths write whenever they decide a
    column: compare the option each sets (or that neither sets one) and whether each adds the card."""
    ev_dir, all_dir = tmp_path / "event", tmp_path / "all"
    ev_dir.mkdir()
    all_dir.mkdir()
    _, by_event = run(ev_dir, event(body=body, state=state, association=association, title=title))
    issue = card(1347, body, state=state.upper(), title=title, association=association)
    issue["id"] = ISSUE_ID
    _, by_all = run_all(all_dir, [issue], [])
    ev_writes, all_writes = writes(by_event), writes(by_all)
    assert [w[0] for w in ev_writes] == [w[0] for w in all_writes]
    ev_option = [w[2] for w in ev_writes if w[0] == "set"]
    all_option = [w[2] for w in all_writes if w[0] == "set"]
    assert ev_option == all_option == ([OPTION[column]] if column else [])


def test_on_a_schedule_or_by_hand_the_step_runs_all_cards(tmp_path):
    """GITHUB_EVENT_NAME schedule and workflow_dispatch run `--all --repo $GITHUB_REPOSITORY`."""
    for name in ("schedule", "workflow_dispatch"):
        here = tmp_path / name
        here.mkdir()
        issues, items = here / "issues.json", here / "items.json"
        issues.write_text(
            json.dumps(
                pages(
                    [card(82, "**Status:** In progress")], lambda c: {"data": {"repository": {"issues": c}}}
                )
            ),
            encoding="utf-8",
        )
        items.write_text(
            json.dumps(pages([item(82, "Todo")], lambda c: {"data": {"node": {"items": c}}})),
            encoding="utf-8",
        )
        proc = run_step(here, "stand-in-token", name, BOARD_GH_ISSUES=str(issues), BOARD_GH_ITEMS=str(items))
        assert proc.returncode == 0, proc.stderr
        found = calls(here)
        assert found[1]["owner"] == ("-f", "ThyFriendlyFox") and found[1]["name"] == ("-f", "via")
        assert lines(proc) == ["#82 In Progress: moved from Todo", summary(moved=1)]


def test_on_a_schedule_with_no_secret_the_step_says_so_and_ends_green(tmp_path):
    proc = run_step(tmp_path, "", "schedule")
    assert proc.returncode == 0, proc.stderr
    assert lines(proc) == ["board: no secret BOARD_TOKEN is set, so the board is not changed"]
    assert calls(tmp_path) == []
