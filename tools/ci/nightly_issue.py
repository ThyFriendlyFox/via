#!/usr/bin/env python3
"""nightly_issue — what the nightly run does with its `ci-failure` issue: open, comment, close or nothing.

The issue follows the nights. A failed night with no open issue opens one. A failed night with an open
issue adds 1 comment to it. A passed night closes each open issue with 1 comment that names its run. A
passed night with no open issue does nothing. With 2 or more open, the oldest is the one spoken to: it
holds the history. On a failed night each newer one is closed as its duplicate, so 1 stays open; on a
passed night each is closed.

The reason goes into the text, bounded, so a reader need not open the log: the workflow step that
failed, the gate's `FAILED` lines, its `why:` blocks and its `TESTS RED` line (verify/testshards.py
prints them). A log with no `why:` line (the gate stopped at lint, kit checks or doctor) gives the step
the gate stopped in and the end of its log. No log (the night stopped before `make verify`) says so.
The log's lines go inside a code fence longer than any run of backticks they hold, so a test's name
is never read as markdown, a mention or a link.

    nightly_issue.py --outcome success|failure --log L --issues I --run URL --date D [--step name=outcome ...]

L is the gate's log (absent: no log). I is GitHub's JSON list of the open issues with the label (a pull
request in it is left out). Each --step is a workflow step's outcome, in the job's order. Prints
{"actions": [...]} on stdout and 1 line per action on stderr. Standard library only: on a night whose
install failed there is no venv, and the runner's python3 runs it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

LABEL = "ci-failure"
FAILED_LINES, BLOCKS, BLOCK_LINES, TAIL, WIDTH, MAX_CHARS = 20, 10, 15, 40, 300, 20000
# The room for the `why:` blocks: MAX_CHARS less what the head of a text can take (its lines, the
# run's address, the FAILED lines and the TESTS RED line, each at most WIDTH and its cut note).
BUDGET = MAX_CHARS - (FAILED_LINES + 12) * (WIDTH + 40)


def cut(line: str) -> str:
    line = line.rstrip()
    return f"{line[:WIDTH]} [... {len(line) - WIDTH} characters cut]" if len(line) > WIDTH else line


def fenced(lines: list[str]) -> str:
    """The lines in a code fence longer than any run of backticks they hold."""
    longest = max((len(run) for line in lines for run in re.findall(r"`+", line)), default=0)
    fence = "`" * max(3, longest + 1)
    return "\n".join([fence, *lines, fence])


def why_blocks(lines: list[str]) -> list[list[str]]:
    """Each `why:` line with the `  | ` lines under it."""
    blocks: list[list[str]] = []
    inside = False
    for line in lines:
        if line.startswith("why: "):
            blocks.append([line])
            inside = True
        elif inside and line.startswith("  | "):
            blocks[-1].append(line)
        else:
            inside = False
    return blocks


def reason(log: str | None, steps: dict[str, str]) -> str:
    """The reason of a failed night, bounded."""
    failed = [name for name, outcome in steps.items() if outcome == "failure"]
    out = [f"the step that failed: {failed[0] if failed else 'none named (read the run)'}"]
    if log is None:
        out.append("the gate's log is absent: the night stopped before `make verify` wrote it.")
        return "\n\n".join(out)
    lines = log.splitlines()
    blocks = why_blocks(lines)
    # Only verify.sh's step() lines (`== 1/4 lint`) name a step: another `== ` line of the log stays
    # in the fence, and the name, of plain characters only, is put in backticks.
    gate = [m[1] for line in lines if (m := re.fullmatch(r"== (\d+/\d+ [\w ./-]+)", line))]
    if not blocks:
        where = f"the gate stopped in its step `{gate[-1]}`" if gate else "the gate printed no step"
        tail = lines[-TAIL:]
        out.append(f"no `why:` line in the gate's log; {where}; its last {len(tail)} lines:")
        out.append(fenced([cut(line) for line in tail]))
        return "\n\n".join(out)
    failed_lines = [line for line in lines if line.startswith("FAILED ")]
    red = [line for line in lines if line.startswith("TESTS RED")]
    if failed_lines:
        out.append(f"{len(failed_lines)} tests failed.")
    head = [cut(line) for line in red] + [cut(line) for line in failed_lines[:FAILED_LINES]]
    if len(failed_lines) > FAILED_LINES:
        head.append(f"[... and {len(failed_lines) - FAILED_LINES} more FAILED lines: read the log]")
    # The `why:` blocks in the room left by BUDGET, each whole or not at all; the rest are counted.
    shown: list[str] = []
    room = BUDGET - sum(len(line) + 1 for line in head)
    count = 0
    for block in blocks[:BLOCKS]:
        lines_ = [cut(line) for line in block[:BLOCK_LINES]]
        if len(block) > BLOCK_LINES:
            lines_.append(f"  | [... {len(block) - BLOCK_LINES} lines cut here]")
        size = sum(len(line) + 1 for line in lines_)
        if size > room:
            break
        shown += lines_
        room -= size
        count += 1
    if len(blocks) > count:
        shown.append(f"[... and {len(blocks) - count} more `why:` blocks: read the log]")
    out.append(fenced(head))
    if shown:
        out.append(fenced(shown))
    return "\n\n".join(out)


def bound(text: str) -> str:
    """The text cut to MAX_CHARS, its fence closed and the cut said."""
    if len(text) <= MAX_CHARS:
        return text
    note = "\n[... the rest is cut: read the log]"
    # The longest fence the text holds is room enough for any close; the kept part closes the fence
    # that is open where the cut falls, with that same fence, or adds none when no fence is open.
    longest = max((len(f) for f in re.findall(r"^(`{3,})$", text, re.M)), default=0)
    room = MAX_CHARS - len(note) - (longest + 1)
    kept = text[:room].rsplit("\n", 1)[0]
    fence = None
    for line in kept.splitlines():
        if fence is None and re.fullmatch(r"`{3,}", line):
            fence = line
        elif line == fence:
            fence = None
    return kept + (f"\n{fence}" if fence else "") + note


def plan(outcome: str, log: str | None, issues: list[dict], run: str, date: str, steps: dict[str, str]):
    """The actions for 1 night, in the order GitHub should get them."""
    if outcome not in ("success", "failure"):
        raise ValueError(f"outcome {outcome!r}: success or failure")
    open_ = sorted((i for i in issues if "pull_request" not in i), key=lambda i: i["number"])
    if outcome == "success":
        text = f"The night of {date} passed: {run}\n\nClosed by the nightly run: its health gate is green."
        return [{"do": "close", "issue": i["number"], "body": text, "reason": "completed"} for i in open_]
    why = reason(log, steps)
    if not open_:
        body = bound(f"The nightly health gate failed on {date}.\n\nRun: {run}\n\n{why}")
        return [{"do": "open", "title": f"Nightly verify failed - {date}", "labels": [LABEL], "body": body}]
    kept, rest = open_[0], open_[1:]
    acts = [
        {"do": "comment", "issue": kept["number"], "body": bound(f"Failed again on {date}: {run}\n\n{why}")}
    ]
    for i in rest:
        text = (
            f"Closed as a duplicate of #{kept['number']}: the nightly run keeps 1 open `{LABEL}` issue, "
            f"and speaks to the oldest. The night of {date} failed: {run}"
        )
        acts.append({"do": "close", "issue": i["number"], "body": text, "reason": "not_planned"})
    return acts


def say(act: dict) -> str:
    if act["do"] == "open":
        return f"nightly-issue: open {act['title']!r}"
    if act["do"] == "comment":
        return f"nightly-issue: comment on #{act['issue']}"
    return f"nightly-issue: close #{act['issue']} as {act['reason']}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--outcome", required=True)
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--issues", type=Path, required=True)
    ap.add_argument("--run", required=True)
    ap.add_argument("--date", required=True)
    ap.add_argument("--step", action="append", default=[], help="name=outcome, in the job's order")
    args = ap.parse_args(argv)
    steps = dict(s.split("=", 1) for s in args.step)
    log = args.log.read_text(encoding="utf-8", errors="replace") if args.log.is_file() else None
    issues = json.loads(args.issues.read_text(encoding="utf-8"))
    try:
        acts = plan(args.outcome, log, issues, args.run, args.date, steps)
    except ValueError as exc:
        print(f"nightly_issue.py: {exc}", file=sys.stderr)
        return 2
    for act in acts:
        print(say(act), file=sys.stderr)
    if not acts:
        print("nightly-issue: nothing to do", file=sys.stderr)
    print(json.dumps({"actions": acts}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
