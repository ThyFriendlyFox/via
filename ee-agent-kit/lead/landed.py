#!/usr/bin/env python3
"""Which pieces of work have finished their build, their reviews and their fixes, read from journals.

usage: landed.py <state file> <journal>...

A journal is a file of JSON lines, 1 per event (ee-agent-kit/lead/README.md, "The journal"):
`{"type": "started", "agentId": ..., "label": ...}` when a helper starts and
`{"type": "result", "agentId": ..., "result": {...}}` when it reports. A label is `<stage>:<branch>`,
the stages `build`, `attack`, `fix`, `attack2` and `fix2`. A result may be an object, the same as JSON
text, or null for a helper that ended with no result. Lines that are no JSON are passed over.

A piece has finished when it has a build result, a review result, a fix result if the review had
findings, and, when the first review's verdict starts with `not sound`, a second review and its fix
in the same way. Each finished piece that the state file (a JSON list of branches) does not hold yet
is printed as 1 block and added to the file. Every other piece is printed as 1 `waiting` line that
says what it waits for.

Exit 0: at least 1 piece finished since the last run. Exit 1: nothing new. Exit 2: a bad call or a
state file that is not a JSON list, in 1 line on stderr. Standard library only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

USAGE = "usage: landed.py <state file> <journal>..."
NO_RESULT = object()


def as_object(value):
    """A result as an object; NO_RESULT for a helper that ended with none."""
    if value is None:
        return NO_RESULT
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {"text": value[:400]}
    return value if isinstance(value, dict) else {"text": str(value)[:400]}


def read_journals(paths: list[str]) -> tuple[dict[str, object], set[str]]:
    """The result of each label, and the labels that started."""
    label_of, result_of = {}, {}
    for journal in paths:
        path = Path(journal)
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            if entry.get("type") == "started" and entry.get("label"):
                label_of[entry.get("agentId")] = entry["label"]
            elif entry.get("type") == "result":
                result_of[entry.get("agentId")] = as_object(entry.get("result"))
    results = {label_of[a]: r for a, r in result_of.items() if a in label_of}
    return results, set(label_of.values())


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def review_state(results: dict, branch: str, n: int, attack: str, fix: str) -> tuple[str | None, list]:
    """Why review n of a piece is not done (None when it is), and its (review, fix) pair."""
    review = results.get(f"{attack}:{branch}")
    if review is None:
        return ("no review yet" if n == 1 else "a second review is needed before it lands"), []
    if review is NO_RESULT:
        return f"review {n} ended with no result; start a new review", []
    findings = review.get("findings") or []
    fixed = results.get(f"{fix}:{branch}")
    if findings and fixed is None:
        return f"review {n} has {plural(len(findings), 'finding')} and no fix yet", []
    if findings and fixed is NO_RESULT:
        return f"the fix of review {n} ended with no result; start a new fix", []
    return None, [(review, fixed if findings else None)]


def status(results: dict, started: set[str], branch: str) -> tuple[str | None, list]:
    """(what the piece waits for, or None) and its reviews with their fixes."""
    built = results.get(f"build:{branch}")
    if built is None:
        return "no build result yet", []
    if built is NO_RESULT:
        return "the build ended with no result; read its journal before starting it again", []
    waiting, rounds = review_state(results, branch, 1, "attack", "fix")
    if waiting:
        return waiting, []
    first = str(rounds[0][0].get("verdict", "")).strip().lower()
    if first.startswith("not sound") or f"attack2:{branch}" in started:
        waiting, second = review_state(results, branch, 2, "attack2", "fix2")
        if waiting:
            if waiting.startswith("a second review"):
                waiting = "review 1 said not sound; " + waiting
            return waiting, []
        rounds += second
    return None, rounds


def block(branch: str, built: dict, rounds: list) -> list[str]:
    last = built
    lines = []
    for n, (review, fixed) in enumerate(rounds, start=1):
        verdict, findings = str(review.get("verdict", ""))[:300], len(review.get("findings") or [])
        lines.append(f"review {n}: {verdict} | findings: {findings}")
        if n == 1:
            lines.append(f"evidence_holds: {str(review.get('evidence_holds', ''))[:300]}")
        if fixed:
            last = fixed
            not_fixed = json.dumps(fixed.get("not_fixed", []))[:700]
            lines.append(f"fix {n}: fixed {len(fixed.get('fixed', []))} | not_fixed: {not_fixed}")
    tests = last.get("tests_last_line") or built.get("tests_last_line", "")
    return [
        f"=== LANDED {branch}  head {str(last.get('head', '?'))[:12]}",
        f"summary: {str(built.get('summary', ''))[:900]}",
        f"evidence: {str(built.get('evidence', ''))[:700]}",
        f"not_done: {json.dumps(built.get('not_done', []))[:900]}",
        f"reviews: {len(rounds)}",
        *lines,
        f"tests: {tests}",
    ]


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(USAGE, file=sys.stderr)
        return 2
    state_path = Path(argv[0])
    seen: list = []
    if state_path.exists():
        try:
            seen = json.loads(state_path.read_text(encoding="utf-8"))
        except ValueError:
            seen = None
        if not isinstance(seen, list):
            print(f"landed: {state_path} is not a JSON list of branches", file=sys.stderr)
            return 2
    results, started = read_journals(argv[1:])
    branches = sorted({label.split(":", 1)[1] for label in started if label.startswith("build:")})
    new = []
    for branch in branches:
        waiting, rounds = status(results, started, branch)
        if waiting:
            print(f"waiting {branch}: {waiting}")
        elif branch not in seen:
            new.append(branch)
            print("\n".join(block(branch, results[f"build:{branch}"], rounds)))
    if not new:
        print("landed: nothing new")
        return 1
    state_path.write_text(json.dumps(seen + new), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
