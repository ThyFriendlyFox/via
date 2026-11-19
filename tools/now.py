"""`workcenter now`: the card of 1 piece of work in progress, for a maintainer to follow.

A card's first line is `**Status:**` and 1 of the project board's own 3 words (`STATUSES`), the line
tools/board.py reads to put the card in its column. Then 6 sections and no others (`SECTIONS`): the
branch and its last commit, what is being done now, the last health-gate verdict on the branch, what it
is blocked on, what is left, and when the card was written. The card repeats nothing else the board
shows: the work (a roadmap item's title, or 1 line) is the issue's title, `Work card: <the work>`,
which `--title` prints. Work that waits on someone stays In progress and says so in its Blocked on line.
The command reads the branch, the commit and a roadmap item's title from the tree, and the gate's
verdict from `build/verify.json`, which `verify/verify.sh` leaves on exit
(`python3 tools/now.py record <exit code> <step>`). The agent gives the rest as options.

The card goes into the body of 1 GitHub issue per piece of work, rewritten and never commented on; with
`--write` it goes, under its title as a heading, into `now/<branch>.md` of a checkout of the branch
`status` instead, and the command prints the git commands that commit and push it and runs none of them.

Standard library only, as the CLI is (AGENTS.md invariant 3).
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

import clock

SECTIONS = ("Branch", "Doing now", "Health gate", "Blocked on", "Left", "Updated")
# The project board's own 3 words, as tools/board.py takes them (`WORDS`), matched without regard to case.
STATUSES = ("Todo", "In progress", "Done")
TITLE = "Work card:"  # tools/board.py takes an issue whose title starts so (`PREFIX`)
MAX_DOING = 3
# The repository's own labels a card's issue takes, named in .claude/skills/now/SKILL.md: a work card,
# 1 that needs something from outside, 1 that waits for the owner's decision, a document-only follow-up.
LABELS = ("enhancement", "help wanted", "question", "documentation")
STATUS_LINE = re.compile(r"\*\*Status:\*\*", re.I)
RECORD = Path("build") / "verify.json"
ROADMAPS = (Path("ee-agent-kit") / "ROADMAP.md", Path("ROADMAP.md"))
STATUS_BRANCH = "status"
HASH = re.compile(r"[0-9a-f]{40}")
# The card names no assistant, no model and no session: CLAUDE.md's rule for what the repository
# publishes. A file's name, `CLAUDE.md`, and the product's, `Claude Code`, are no such name, as
# tests/test_docs.py holds for commit messages.
NAMED = re.compile(
    r"\b(?:claude(?!\.md\b|[ -]code\b)|anthropic|opus|sonnet|haiku|gpt-?\d|gemini|copilot)"
    r"|session_[0-9a-z]{6,}",
    re.I,
)


class Refused(Exception):
    """A card the command will not print: 1 line, the reason."""


def run_git(tree: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise Refused(f"{tree} is not a git work tree, or git failed: git {' '.join(args)}")
    return proc.stdout.strip()


def branch_of(tree: Path) -> str:
    if not tree.is_dir():
        raise Refused(f"{tree} is not a folder, so not a git work tree")
    branch = run_git(tree, "rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        raise Refused(f"{tree} is on no branch (detached HEAD); a piece of work is known by its branch")
    return branch


def utc_minute(when: datetime.datetime) -> str:
    return when.astimezone(datetime.UTC).strftime("%Y-%m-%d %H:%M UTC")


def work_of(tree: Path, item: str | None) -> str:
    if item is None or not item.strip():
        raise Refused("--item is missing: a roadmap item's number, or 1 line for work with none")
    if not item.isdigit():
        return item
    for rel in ROADMAPS:
        path = tree / rel
        if path.is_file():
            found = re.search(rf"^### {item}\. (.+)$", path.read_text(encoding="utf-8"), re.M)
            if found:
                return f"Roadmap item {item}: {found.group(1).strip()}"
            raise Refused(f"item {item} has no heading '### {item}.' in {rel}")
    raise Refused(f"item {item} is a number and {tree} has no {' or '.join(map(str, ROADMAPS))}")


def gate_of(tree: Path, branch: str, head: str) -> dict | None:
    """The last `make verify` on this branch, from the record verify.sh leaves; None when there is none."""
    path = tree / RECORD
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
        verdict, commit, when, moved = record["verdict"], record["commit"], record["time"], record["moved_to"]
        moment = datetime.datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.UTC)
    except (ValueError, KeyError, TypeError) as exc:
        raise Refused(f"{path} is not a gate record verify.sh writes: {exc!r}") from exc
    shapes = (
        ("commit", isinstance(commit, str) and HASH.fullmatch(commit)),
        ("moved_to", moved is None or (isinstance(moved, str) and HASH.fullmatch(moved))),
        ("dirty", isinstance(record.get("dirty"), bool)),
        ("step", isinstance(record.get("step"), str)),
        ("branch", isinstance(record.get("branch"), str)),
    )
    for key, ok in shapes:
        if not ok:
            raise Refused(f"{path} is not a gate record verify.sh writes: {key} is {record.get(key)!r}")
    if verdict not in ("GREEN", "RED"):
        raise Refused(f"{path} holds the verdict {verdict!r}; verify.sh writes GREEN or RED")
    if record["branch"] != branch:
        return None

    def git_out(*args: str) -> str | None:
        proc = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None

    def short_of(sha: str) -> str:
        known = git_out("cat-file", "-e", f"{sha}^{{commit}}") is not None
        return (git_out("rev-parse", "--short", sha) if known else None) or sha[:7]

    known = git_out("cat-file", "-e", f"{commit}^{{commit}}") is not None
    short = short_of(commit)
    line = "GREEN" if verdict == "GREEN" else f"RED at {record['step']}"
    line += f" on `{short}`"
    if record["dirty"]:
        line += " with uncommitted changes"
    line += f" at {utc_minute(moment)}"
    if moved:
        # The gate read files while the branch moved: its verdict is of the commit it started on.
        line += f", the branch moved to `{short_of(moved)}` during the run"
    if commit != head:
        if known and git_out("merge-base", "--is-ancestor", commit, head) is not None:
            n = int(git_out("rev-list", "--count", f"{commit}..{head}"))
            line += f", {n} commit{'s' if n != 1 else ''} before the last"
        else:
            line += ", on a commit this branch no longer holds"
    return {**record, "short": short, "line": line}


def one_line(flag: str, values: list[str]) -> None:
    for value in values:
        if "\n" in value or "\r" in value:
            raise Refused(f"{flag} holds a line break; each value is 1 line")


def names_none(where: str, values: list[str]) -> None:
    for value in values:
        found = NAMED.search(value)
        if found:
            raise Refused(
                f"{where} names an assistant, a model or a session ({found.group(0)!r}); "
                "the card names none (CLAUDE.md)"
            )


def build(args: argparse.Namespace) -> dict:
    """The card's data from the tree and the options; Refused names the first thing wrong."""
    doing, left = args.doing or [], args.left or []
    for flag, values in (
        ("--item", [args.item or ""]),
        ("--doing", doing),
        ("--blocked", [args.blocked or ""]),
        ("--left", left),
    ):
        one_line(flag, values)
        names_none(flag, values)
        # The board reads the card's 1 **Status:** line; a second one would leave the card where it stands.
        if any(STATUS_LINE.search(v) for v in values):
            raise Refused(f"{flag} holds a **Status:** line; the card has 1, from --status")
    # --item and --blocked are printed bare under their heading; --doing and --left after `- `.
    for flag, value in (("--item", args.item or ""), ("--blocked", args.blocked or "")):
        if value.lstrip().startswith("#"):
            raise Refused(f"{flag} starts with '#', which would be a heading; the card has 6 and no others")
    if args.status is None:
        raise Refused(f"--status is missing; it is 1 of {', '.join(STATUSES)}")
    status = next((s for s in STATUSES if " ".join(args.status.split()).casefold() == s.casefold()), None)
    if status is None:
        raise Refused(f"--status {args.status!r} is not 1 of {', '.join(STATUSES)}")
    if len(doing) > MAX_DOING:
        raise Refused(f"{len(doing)} --doing lines; the card holds at most {MAX_DOING}")
    tree = Path(args.tree)
    branch = branch_of(tree)
    head = run_git(tree, "rev-parse", "HEAD")
    short, subject = run_git(tree, "log", "-1", "--format=%h%x00%s").split("\x00", 1)
    names_none(f"the branch {branch}", [branch])
    names_none("the last commit's subject", [subject])
    work = work_of(tree, args.item)
    names_none("the roadmap item's title", [work])
    data = {
        "title": f"{TITLE} {work}",
        "work": work,
        "item": args.item if args.item.isdigit() else None,
        "branch": branch,
        "commit": head,
        "short": short,
        "subject": subject,
        "status": status,
        "doing": doing,
        "gate": gate_of(tree, branch, head),
        "blocked_on": (args.blocked or "").strip() or "nothing",
        "left": left,
        "updated": utc_minute(clock.moment()),
    }
    data["card"] = card(data)
    return data


def card(data: dict) -> str:
    def listed(lines: list[str]) -> str:
        return "\n".join(f"- {x}" for x in lines) if lines else "nothing"

    bodies = (
        f"`{data['branch']}` at `{data['short']}` {data['subject']}",
        listed(data["doing"]),
        data["gate"]["line"] if data["gate"] else "none yet",
        data["blocked_on"],
        listed(data["left"]),
        data["updated"],
    )
    sections = "\n".join(f"## {name}\n{body}\n" for name, body in zip(SECTIONS, bodies, strict=True))
    return f"**Status:** {data['status']}\n\n{sections}"


def card_file(branch: str) -> str:
    return f"now/{branch.replace('/', '-')}.md"


def write(data: dict, checkout: Path) -> list[str]:
    """Write the card into the `status` checkout; return the lines to print. Touches no other file."""
    on = branch_of(checkout)
    if on != STATUS_BRANCH:
        raise Refused(f"{checkout} is on branch {on}, not {STATUS_BRANCH}; --write takes a checkout of it")
    others = [f for f in run_git(checkout, "ls-files").splitlines() if not f.startswith("now/")]
    if others:
        raise Refused(
            f"{checkout} holds {others[0]} outside now/; the {STATUS_BRANCH} branch holds cards only"
        )
    rel = card_file(data["branch"])
    path = checkout / rel
    if path.is_file():
        found = re.search(r"^## Branch\n`([^`]+)`", path.read_text(encoding="utf-8"), re.M)
        if found and found.group(1) != data["branch"]:
            raise Refused(f"{rel} is the card of {found.group(1)}, not of {data['branch']}; rename a branch")
    path.parent.mkdir(exist_ok=True)
    # No issue holds the title here, so the file starts with it.
    path.write_text(f"# {data['title']}\n\n{data['card']}", encoding="utf-8")
    # Quoted for a shell: a checkout's path may hold a space, a branch's name an apostrophe.
    at, message = shlex.quote(str(checkout)), shlex.quote(f"now: {data['branch']} {data['status']}")
    return [
        f"wrote {path}",
        f"git -C {at} add {shlex.quote(rel)}",
        f"git -C {at} commit -m {message}",
        f"git -C {at} pull --rebase origin {STATUS_BRANCH}",
        f"git -C {at} push origin {STATUS_BRANCH}",
    ]


def cmd_now(args: argparse.Namespace) -> int:
    try:
        data = build(args)
        lines = write(data, Path(args.write)) if args.write else None
    except Refused as why:
        print(f"now: refused: {why}", file=sys.stderr)
        return 1
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
    elif args.title:
        print(data["title"])
    elif lines:
        print("\n".join(lines))
    else:
        print(data["card"], end="")
    return 0


def record(code: int, step: str, tree: Path, head: str, dirty_at_start: bool) -> Path:
    """The record `make verify` leaves on exit: its verdict, its last step, the commit it started on
    (`head`, taken before step 1), the commit the branch moved to during the run if it moved, whether the
    tree differed from its commit at the start or at the end, and the time."""

    def git_out(*args: str) -> str:
        return subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True).stdout.strip()

    at_end = git_out("rev-parse", "HEAD")
    # Untracked files count: pytest and ruff read them. Ignored files do not.
    changed = git_out("status", "--porcelain", "--untracked-files=normal")
    data = {
        "gate": "make verify",
        "verdict": "GREEN" if code == 0 else "RED",
        "step": step,
        "commit": head,
        "branch": git_out("rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": dirty_at_start or bool(changed),
        "moved_to": at_end if at_end != head else None,
        "time": clock.moment().astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path = tree / RECORD
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def register(sub, cli) -> None:
    """Add `now` to Via's parser."""
    p = sub.add_parser(
        "now",
        help="print the card of 1 piece of work in progress: its **Status:** line for the project board, "
        "its branch and last commit, what is done now, the last health gate, what it waits for and what is "
        "left; with --title, the issue's title; with --write, put it in now/<branch>.md of a checkout of "
        "the status branch",
    )
    p.add_argument("tree", nargs="?", default=".", help="the work tree (default .)")
    p.add_argument("--item", help="the roadmap item's number, or 1 line for work with none")
    p.add_argument("--status", help=f"the board's word: 1 of {', '.join(STATUSES)}")
    p.add_argument(
        "--doing", action="append", help=f"what is done now, 1 line (repeatable, {MAX_DOING} at most)"
    )
    p.add_argument("--blocked", help="who or what the work waits for; it stays In progress")
    p.add_argument("--title", action="store_true", help="print the issue's title, `Work card: <the work>`")
    p.add_argument("--left", action="append", help="1 thing left to do (repeatable)")
    p.add_argument(
        "--write",
        metavar="CHECKOUT",
        help="a checkout of the status branch: write the card into its now/ folder",
    )
    p.set_defaults(run=cmd_now)


def main(argv: list[str] | None = None) -> int:
    """`python3 tools/now.py record <exit code> <step> --head <commit> --dirty yes|no`: what
    verify/verify.sh runs on exit, with the commit and the tree's state it noted before step 1."""
    parser = argparse.ArgumentParser(prog="now.py")
    sub = parser.add_subparsers(dest="command", required=True)
    q = sub.add_parser("record", help="write build/verify.json for the gate that just ended")
    q.add_argument("code", type=int, help="the gate's exit code")
    q.add_argument("step", help="the step the gate was at")
    q.add_argument("--tree", default=".", help="the repository's root (default .)")
    q.add_argument("--head", required=True, help="the commit the gate started on")
    q.add_argument(
        "--dirty", required=True, choices=("yes", "no"), help="whether the tree differed from it then"
    )
    with clock.run():
        args = parser.parse_args(argv)
        path = record(args.code, args.step, Path(args.tree), args.head, args.dirty == "yes")
    print(f"gate record {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
