"""`workcenter now`: the card of 1 piece of work in progress, for a maintainer to follow.

A card has 8 sections and no others (`SECTIONS`): the work, the branch and its last commit, the state,
what is being done now, the last health-gate verdict on the branch, what it is blocked on, what is left,
and when the card was written. The command reads the branch, the commit and a roadmap item's title from
the tree, and the gate's verdict from `build/verify.json`, which `verify/verify.sh` leaves on exit
(`python3 tools/now.py record <exit code> <step>`). The agent gives the rest as options.

The card goes into the body of 1 GitHub issue per piece of work, rewritten and never commented on; with
`--write` it goes into `now/<branch>.md` of a checkout of the branch `status` instead, and the command
prints the git commands that commit and push it and runs none of them.

Standard library only, as the CLI is (AGENTS.md invariant 3).
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

SECTIONS = ("Work", "Branch", "State", "Doing now", "Health gate", "Blocked on", "Left", "Updated")
STATES = ("working", "blocked", "landed", "dropped")
MAX_DOING = 3
# The labels of a card's issue, named in .claude/skills/now/SKILL.md; the stale run spares the open ones.
LABELS = ("working", "blocked on owner", "landed")
RECORD = Path("build") / "verify.json"
ROADMAPS = (Path("ee-agent-kit") / "ROADMAP.md", Path("ROADMAP.md"))
STATUS_BRANCH = "status"


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
        verdict, commit, when = record["verdict"], record["commit"], record["time"]
        moment = datetime.datetime.strptime(when, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=datetime.UTC)
    except (ValueError, KeyError, TypeError) as exc:
        raise Refused(f"{path} is not a gate record verify.sh writes: {exc}") from exc
    if verdict not in ("GREEN", "RED"):
        raise Refused(f"{path} holds the verdict {verdict!r}; verify.sh writes GREEN or RED")
    if record.get("branch") != branch:
        return None

    def git_out(*args: str) -> str | None:
        proc = subprocess.run(["git", "-C", str(tree), *args], capture_output=True, text=True, check=False)
        return proc.stdout.strip() if proc.returncode == 0 else None

    known = bool(re.fullmatch(r"[0-9a-f]{40}", str(commit))) and (
        git_out("cat-file", "-e", f"{commit}^{{commit}}") is not None
    )
    short = (git_out("rev-parse", "--short", commit) if known else None) or str(commit)[:7]
    line = "GREEN" if verdict == "GREEN" else f"RED at {record.get('step', 'an unnamed step')}"
    line += f" on `{short}`"
    if record.get("dirty"):
        line += " with uncommitted changes"
    line += f" at {utc_minute(moment)}"
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
    if args.state is None:
        raise Refused(f"--state is missing; it is 1 of {', '.join(STATES)}")
    if args.state not in STATES:
        raise Refused(f"--state {args.state!r} is not 1 of {', '.join(STATES)}")
    if len(doing) > MAX_DOING:
        raise Refused(f"{len(doing)} --doing lines; the card holds at most {MAX_DOING}")
    if args.state == "blocked" and not (args.blocked or "").strip():
        raise Refused("state blocked needs --blocked: who or what the work waits for")
    tree = Path(args.tree)
    branch = branch_of(tree)
    head = run_git(tree, "rev-parse", "HEAD")
    short, subject = run_git(tree, "log", "-1", "--format=%h%x00%s").split("\x00", 1)
    data = {
        "work": work_of(tree, args.item),
        "item": args.item if args.item.isdigit() else None,
        "branch": branch,
        "commit": head,
        "short": short,
        "subject": subject,
        "state": args.state,
        "doing": doing,
        "gate": gate_of(tree, branch, head),
        "blocked_on": (args.blocked or "").strip() or "nothing",
        "left": left,
        "updated": utc_minute(datetime.datetime.now(datetime.UTC)),
    }
    data["card"] = card(data)
    return data


def card(data: dict) -> str:
    def listed(lines: list[str]) -> str:
        return "\n".join(f"- {x}" for x in lines) if lines else "nothing"

    bodies = (
        data["work"],
        f"`{data['branch']}` at `{data['short']}` {data['subject']}",
        data["state"],
        listed(data["doing"]),
        data["gate"]["line"] if data["gate"] else "none yet",
        data["blocked_on"],
        listed(data["left"]),
        data["updated"],
    )
    return "\n".join(f"## {name}\n{body}\n" for name, body in zip(SECTIONS, bodies, strict=True))


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
    path.write_text(data["card"], encoding="utf-8")
    return [
        f"wrote {path}",
        f"git -C {checkout} add {rel}",
        f"git -C {checkout} commit -m 'now: {data['branch']} {data['state']}'",
        f"git -C {checkout} pull --rebase origin {STATUS_BRANCH}",
        f"git -C {checkout} push origin {STATUS_BRANCH}",
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
    elif lines:
        print("\n".join(lines))
    else:
        print(data["card"], end="")
    return 0


def record(code: int, step: str, tree: Path) -> Path:
    """The record `make verify` leaves on exit: its verdict, its last step, the commit and the time."""
    branch = subprocess.run(
        ["git", "-C", str(tree), "rev-parse", "--abbrev-ref", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    commit = subprocess.run(
        ["git", "-C", str(tree), "rev-parse", "HEAD"], capture_output=True, text=True
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", str(tree), "status", "--porcelain", "--untracked-files=no"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    data = {
        "gate": "make verify",
        "verdict": "GREEN" if code == 0 else "RED",
        "step": step,
        "commit": commit,
        "branch": branch,
        "dirty": bool(dirty),
        "time": datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    path = tree / RECORD
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


def register(sub, cli) -> None:
    """Add `now` to the workcenter's parser."""
    p = sub.add_parser(
        "now",
        help="print the card of 1 piece of work in progress: the work, its branch and last commit, its "
        "state, what is done now, the last health gate, what it waits for and what is left; with --write, "
        "put it in now/<branch>.md of a checkout of the status branch",
    )
    p.add_argument("tree", nargs="?", default=".", help="the work tree (default .)")
    p.add_argument("--item", help="the roadmap item's number, or 1 line for work with none")
    p.add_argument("--state", help=f"1 of {', '.join(STATES)}")
    p.add_argument(
        "--doing", action="append", help=f"what is done now, 1 line (repeatable, {MAX_DOING} at most)"
    )
    p.add_argument("--blocked", help="who or what the work waits for (needed with --state blocked)")
    p.add_argument("--left", action="append", help="1 thing left to do (repeatable)")
    p.add_argument(
        "--write",
        metavar="CHECKOUT",
        help="a checkout of the status branch: write the card into its now/ folder",
    )
    p.set_defaults(run=cmd_now)


def main(argv: list[str] | None = None) -> int:
    """`python3 tools/now.py record <exit code> <step>`: what verify/verify.sh runs on exit."""
    parser = argparse.ArgumentParser(prog="now.py")
    sub = parser.add_subparsers(dest="command", required=True)
    q = sub.add_parser("record", help="write build/verify.json for the gate that just ended")
    q.add_argument("code", type=int, help="the gate's exit code")
    q.add_argument("step", help="the step the gate was at")
    q.add_argument("--tree", default=".", help="the repository's root (default .)")
    args = parser.parse_args(argv)
    print(f"gate record {record(args.code, args.step, Path(args.tree))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
