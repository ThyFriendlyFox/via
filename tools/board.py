"""Put a work card in the column of the project board that its body names.

A work card is a GitHub issue whose title starts with `Work card:`. Its body carries 1 line
`**Status:** Todo`, `**Status:** In progress` or `**Status:** Done`, the board's own 3 words, matched
without regard to case. A closed issue is Done whatever its body says. A card with no such line, with
2, or with another word is put on the board and left where it stands, and the run says so in 1 line.
A line that renders as an example is not the card's: in a fenced code block, indented 4 spaces (an
indented code block), or inside an HTML comment (CommonMark 0.31.2, 4.4, 4.5, 4.6). A body whose
`<!--` does not close is not judged: the card is left where it stands, and the line says why.

The tool reads the issue from the event file a workflow gets as GITHUB_EVENT_PATH, never from a shell
line: a title and a body are text from anyone. A card is touched only when its author is the
repository's owner, a member or a collaborator (`author_association`): a stranger can edit only the
issues they opened, so a stranger's text never reaches the board.

For a card it asks GitHub through `gh api graphql` (GH_TOKEN, a token with the `project` scope):
the project by its URL with its single-select field Status and that field's options, then
`addProjectV2ItemById` (which returns the existing item when the issue is on the board already), then
`updateProjectV2ItemFieldValue` with the option whose name matches. Option ids and their case are read
from the project, never assumed. The calls follow GitHub's guide "Using the API to manage Projects"
and its GraphQL reference (Projects, Users), read on 2026-11-17.

Exit 0: the card stands in its column, or nothing was to be done (no card, a stranger's card, no
Status line). Exit 1: a failure, in 1 line. Standard library only, as the CLI is.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

PREFIX = "Work card:"
WORDS = ("Todo", "In progress", "Done")
TRUSTED = ("OWNER", "MEMBER", "COLLABORATOR")
# CommonMark 0.31.2: 0 to 3 spaces of indent keep a line its own; 4 make an indented code block (4.4).
# A fence is 3 or more ` or ~ and closes on the same mark, at least as long (4.5).
STATUS_LINE = re.compile(r"^ {0,3}\*\*Status:\*\*[ \t]*(.*?)[ \t]*$", re.I)
STATUS_ANYWHERE = re.compile(r"^[ \t]*\*\*Status:\*\*", re.I)
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
COMMENT = re.compile(r"<!--.*?-->", re.S)
BOARD_URL = re.compile(r"^https://github\.com/(users|orgs)/([A-Za-z0-9-]+)/projects/(\d+)(?:/.*)?$")
GH_TIMEOUT_S = 60

FIND = """query($login: String!, $number: Int!) {
  %s(login: $login) {
    projectV2(number: $number) {
      id
      fields(first: 50) {
        nodes { ... on ProjectV2SingleSelectField { id name options { id name } } }
      }
    }
  }
}"""
ADD = """mutation($project: ID!, $content: ID!) {
  addProjectV2ItemById(input: {projectId: $project, contentId: $content}) { item { id } }
}"""
SET = """mutation($project: ID!, $item: ID!, $field: ID!, $option: String!) {
  updateProjectV2ItemFieldValue(
    input: {projectId: $project, itemId: $item, fieldId: $field, value: {singleSelectOptionId: $option}}
  ) { projectV2Item { id } }
}"""


class Failure(Exception):
    """A failure the run prints as 1 line."""


def status_lines(body: str) -> tuple[list[str], int]:
    """The words of the **Status:** lines that render as the body's own lines, and how many such lines
    are examples: in a fenced or an indented code block, or in an HTML comment. Raises ValueError for a
    comment that does not close."""
    shown = COMMENT.sub("", body)
    if "<!--" in shown:
        raise ValueError("its body opens an HTML comment (<!--) that does not close")
    hidden = sum(1 for ln in body.split("\n") if STATUS_ANYWHERE.match(ln)) - sum(
        1 for ln in shown.split("\n") if STATUS_ANYWHERE.match(ln)
    )
    found, fence = [], ""
    for line in shown.split("\n"):
        line = line.rstrip("\r")
        mark = FENCE.match(line)
        if fence:
            if mark and mark.group(1)[0] == fence[0] and len(mark.group(1)) >= len(fence):
                if not line[mark.end() :].strip():
                    fence = ""
                    continue
            hidden += bool(STATUS_ANYWHERE.match(line))
        elif mark and not (mark.group(1)[0] == "`" and "`" in line[mark.end() :]):
            fence = mark.group(1)
        elif own := STATUS_LINE.match(line):
            found.append(own.group(1))
        else:
            hidden += bool(STATUS_ANYWHERE.match(line))
    return found, hidden


def status_of(body: str | None) -> tuple[str | None, str]:
    """The board's word the body names, or None and the reason it names none."""
    try:
        found, hidden = status_lines(body or "")
    except ValueError as err:
        return None, f"{err}, so which lines render is not judged"
    if not found and hidden:
        does = "does" if hidden == 1 else "do"
        return None, (
            "its body has no **Status:** line outside code and HTML comments "
            f"({hidden} inside, which {does} not count)"
        )
    if not found:
        return None, "its body has no **Status:** line (Todo, In progress or Done)"
    if len(found) > 1:
        return None, f"its body has {len(found)} **Status:** lines"
    word = " ".join(found[0].split())
    for known in WORDS:
        if word.casefold() == known.casefold():
            return known, ""
    return None, f'its **Status:** line says "{word}", not Todo, In progress or Done'


def parse_board(url: str) -> tuple[str, str, int]:
    match = BOARD_URL.match(url)
    if not match:
        raise Failure(
            f'--board "{url}" is no project URL '
            "(https://github.com/users/<login>/projects/<number> or https://github.com/orgs/...)"
        )
    owner = "user" if match.group(1) == "users" else "organization"
    return owner, match.group(2), int(match.group(3))


def gh(what: str, query: str, strings: dict[str, str], numbers: dict[str, int] | None = None) -> dict:
    """1 `gh api graphql` call. Strings go as `-f` (no `@file` or placeholder reading), numbers as `-F`."""
    args = ["gh", "api", "graphql", "-f", f"query={query}"]
    for key, value in strings.items():
        args += ["-f", f"{key}={value}"]
    for key, value in (numbers or {}).items():
        args += ["-F", f"{key}={int(value)}"]
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=GH_TIMEOUT_S)
    except FileNotFoundError:
        raise Failure("gh is not on PATH") from None
    except subprocess.TimeoutExpired:
        raise Failure(f"gh api graphql ({what}) gave no answer in {GH_TIMEOUT_S} s") from None
    if proc.returncode != 0:
        said = next((ln.strip() for ln in proc.stderr.splitlines() if ln.strip()), "nothing on stderr")
        raise Failure(f"gh api graphql ({what}) exited {proc.returncode}: {said}")
    try:
        answer = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise Failure(f"gh api graphql ({what}) printed no JSON: {proc.stdout[:80]!r}") from None
    if not isinstance(answer, dict) or answer.get("errors") or not isinstance(answer.get("data"), dict):
        errors = answer.get("errors") if isinstance(answer, dict) else None
        said = errors[0] if isinstance(errors, list) and errors else answer
        said = said.get("message", said) if isinstance(said, dict) else said
        raise Failure(f"gh api graphql ({what}) answered with an error: {said}")
    return answer["data"]


def dig(data, *keys):
    """data[k1][k2]..., or None where a level is no object or lacks the key."""
    for key in keys:
        data = data.get(key) if isinstance(data, dict) else None
    return data


def find_project(url: str) -> tuple[str, str, list[dict]]:
    """The project's id, its Status field's id and that field's options."""
    owner, login, number = parse_board(url)
    data = gh("find the project", FIND % owner, {"login": login}, {"number": number})
    project = dig(data, owner, "projectV2")
    if not isinstance(project, dict) or not isinstance(project.get("id"), str):
        raise Failure(f"no project {number} of {login} at {url}")
    nodes = dig(project, "fields", "nodes")
    fields = [f for f in nodes if isinstance(f, dict) and "options" in f] if isinstance(nodes, list) else []
    status = [f for f in fields if str(f.get("name", "")).casefold() == "status"]
    if not status:
        raise Failure(f"the project {url} has no single-select field Status")
    options = status[0]["options"]
    if not isinstance(options, list) or not isinstance(status[0].get("id"), str):
        raise Failure(f"the project {url}'s field Status answered options {options!r}, no list")
    return project["id"], status[0]["id"], [o for o in options if isinstance(o, dict)]


def read_event(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            ev = json.load(fh)
    except (OSError, ValueError) as err:
        raise Failure(f"{path} could not be read as JSON: {err}") from None
    issue = ev.get("issue") if isinstance(ev, dict) else None
    keys = ("number", "node_id", "title", "state", "author_association")
    if not isinstance(issue, dict) or any(k not in issue for k in keys):
        raise Failure(f"{path} is no issues event: it has no issue with {', '.join(keys)}")
    if not isinstance(issue.get("body"), (str, type(None))):
        raise Failure(f"issue #{issue['number']}'s body is {issue['body']!r}, neither text nor null")
    return issue


def place(event_path: str, url: str) -> str:
    """Do what the event asks of the board and return the 1 line that says what was done."""
    issue = read_event(event_path)
    parse_board(url)
    number = issue["number"]
    if not str(issue["title"]).startswith(PREFIX):
        return (
            f'issue #{number} is no work card (its title does not start with "{PREFIX}"); '
            "the board is not changed"
        )
    if issue["author_association"] not in TRUSTED:
        return (
            f"card #{number} is not from the owner, a member or a collaborator "
            f"(author_association {issue['author_association']}); the board is not changed"
        )
    closed = issue["state"] == "closed"
    word, why = ("Done", "") if closed else status_of(issue.get("body"))
    project, field, options = find_project(url)
    added = gh("add the issue", ADD, {"project": project, "content": issue["node_id"]})
    item = dig(added, "addProjectV2ItemById", "item", "id")
    if not isinstance(item, str) or not item:
        raise Failure(f"gh api graphql (add the issue) returned no item for card #{number}")
    if word is None:
        return f"card #{number} is on {url} and left where it stands: {why}"
    match = [o for o in options if str(o.get("name", "")).casefold() == word.casefold()]
    if not match:
        names = ", ".join(str(o.get("name")) for o in options) or "none"
        raise Failure(f'the project {url} has no Status option "{word}"; its options are {names}')
    gh("set the Status", SET, {"project": project, "item": item, "field": field, "option": match[0]["id"]})
    return f"card #{number} stands in {match[0]['name']} on {url}" + (
        " (the issue is closed)" if closed else ""
    )


class Parser(argparse.ArgumentParser):
    """A wrong or missing flag is a failure like any other: 1 line, exit 1."""

    def error(self, message: str):
        raise Failure(f"{message} (board.py --event <file> --board <url>)")


def main(argv: list[str] | None = None) -> int:
    parser = Parser(
        prog="board.py",
        description="Put a work card (an issue titled `Work card: ...`) in the column of the project "
        "board its `**Status:**` line names; a closed card is Done. Writes nothing on disk; changes "
        "the project through `gh api graphql` (GH_TOKEN). Exit 0 done or nothing to do, 1 a failure.",
    )
    parser.add_argument("--event", required=True, help="the issues event's JSON file (GITHUB_EVENT_PATH)")
    parser.add_argument(
        "--board", required=True, help="the project's URL, https://github.com/users/<login>/projects/<n>"
    )
    try:
        args = parser.parse_args(argv)
        print(f"board: {place(args.event, args.board)}")
    except Failure as err:
        print(f"board: FAIL: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
