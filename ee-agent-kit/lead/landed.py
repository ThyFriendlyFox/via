#!/usr/bin/env python3
"""Which pieces of work have finished their build, their reviews and their fixes, read from journals.

usage: landed.py <state file> <journal>...

A journal is a file of JSON lines, 1 per event (ee-agent-kit/lead/README.md, "The journal"):
`{"type": "started", "agentId": ..., "label": ...}` when a helper starts and
`{"type": "result", "agentId": ..., "result": {...}}` when it reports. A label is `<stage>:<branch>`,
the stages `build`, `attack`, `fix`, `attack2` and `fix2`. A result may be an object, the same as JSON
text, or null for a helper that ended with no result. Lines that are no JSON are passed over. An agent
id names 1 helper within 1 journal: 2 journals may use the same ids.

A review has finished when its result gives a verdict (a string that is not empty) and a list of
findings; a fix, when it gives a list `fixed` and, if it gives `not_fixed`, a list. A review started
more than once counts every result: its findings are added up, and it is `not sound` when 1 of them
says so. A build or a fix with 2 results lands on neither. A null result counts only when no other
helper of its label reported or still runs.

A piece has finished when it has a build result, a review result, a fix result if the review had
findings, and, when the first review's verdict starts with `not sound`, a second review and its fix
in the same way. Each finished piece that the state file (a JSON list of branches) does not hold yet
is printed as 1 block and added to the file. Every other piece is printed as 1 `waiting` line that
says what it waits for.

Exit 0: at least 1 piece finished since the last run. Exit 1: nothing new. Exit 2: a bad call, a
journal that cannot be read, 1 agent id started under 2 labels in 1 journal, or a state file that is
not a JSON list, in 1 line on stderr. Standard library only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

USAGE = "usage: landed.py <state file> <journal>..."
NO_RESULT = object()
PENDING = object()
REVIEWS = ("attack", "attack2")


class BadCall(Exception):
    """A call landed.py cannot judge: 1 line, the reason."""


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


def read_journals(paths: list[str]) -> dict[str, list]:
    """The results of each label, 1 per helper started under it: an object, NO_RESULT or PENDING."""
    runs: dict[str, list] = {}
    for journal in paths:
        path = Path(journal)
        if path.is_dir():
            raise BadCall(f"cannot read the journal {journal}: a folder")
        if not path.exists():
            raise BadCall(f"cannot read the journal {journal}: no such file")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise BadCall(f"cannot read the journal {journal}: {exc}") from exc
        label_of, result_of = {}, {}
        for line in text.splitlines():
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if not isinstance(entry, dict):
                continue
            agent = entry.get("agentId")
            if entry.get("type") == "started" and isinstance(entry.get("label"), str) and entry["label"]:
                label = entry["label"]
                if label_of.get(agent, label) != label:
                    first = label_of[agent]
                    raise BadCall(
                        f"{journal} starts agent {agent} as {first} and as {label}; 1 id is 1 helper"
                    )
                label_of[agent] = label
            elif entry.get("type") == "result":
                result_of[agent] = as_object(entry.get("result"))
        for agent, label in label_of.items():
            runs.setdefault(label, []).append(result_of.get(agent, PENDING))
    return runs


def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def outcome(runs: dict, label: str) -> tuple[str, object]:
    """("none" | "null" | "again" | "many" | "done", the result or the results)."""
    found = runs.get(label, [])
    real = [r for r in found if isinstance(r, dict)]
    pending = sum(1 for r in found if r is PENDING)
    if not found or (pending and not real):
        return "none", None
    if pending:
        return "again", None
    if not real:
        return "null", None
    return ("done", real[0]) if len(real) == 1 else ("many", real)


def review_fault(review: dict, n: int) -> str | None:
    verdict = review.get("verdict")
    if not isinstance(verdict, str) or not verdict.strip():
        return f"review {n} has no verdict"
    if not isinstance(review.get("findings"), list):
        return f"review {n} has no list of findings"
    return None


def fix_fault(fixed: dict, n: int) -> str | None:
    if not isinstance(fixed.get("fixed"), list):
        return f"the fix of review {n} has no list fixed"
    if not isinstance(fixed.get("not_fixed", []), list):
        return f"the fix of review {n} has no list not_fixed"
    return None


def not_sound(review: dict) -> bool:
    return any(v.strip().lower().startswith("not sound") for v in review["verdicts"])


def heads(results: list) -> str:
    return ", ".join(str(r.get("head", "?"))[:12] for r in results)


def review_state(runs: dict, branch: str, n: int, attack: str, fix: str) -> tuple[str | None, list]:
    """Why review n of a piece is not done (None when it is), and its (review, fix) pair."""
    kind, got = outcome(runs, f"{attack}:{branch}")
    if kind == "none":
        return ("no review yet" if n == 1 else "a second review is needed before it lands"), []
    if kind == "null":
        return f"review {n} ended with no result; start a new review", []
    if kind == "again":
        return f"review {n} was started again and has not reported yet", []
    results = [got] if kind == "done" else got
    for result in results:
        fault = review_fault(result, n)
        if fault:
            return fault, []
    review = {
        "verdicts": [r["verdict"] for r in results],
        "findings": [f for r in results for f in r["findings"]],
        "evidence_holds": results[0].get("evidence_holds", ""),
    }
    findings = review["findings"]
    if not findings:
        return None, [(review, None)]
    kind, fixed = outcome(runs, f"{fix}:{branch}")
    if kind == "none":
        return f"review {n} has {plural(len(findings), 'finding')} and no fix yet", []
    if kind == "null":
        return f"the fix of review {n} ended with no result; start a new fix", []
    if kind == "again":
        return f"the fix of review {n} was started again and has not reported yet", []
    if kind == "many":
        return f"{len(fixed)} results for {fix}:{branch} (heads {heads(fixed)}); it lands on neither", []
    fault = fix_fault(fixed, n)
    if fault:
        return fault, []
    return None, [(review, fixed)]


def status(runs: dict, branch: str) -> tuple[str | None, list]:
    """(what the piece waits for, or None) and its reviews with their fixes."""
    kind, built = outcome(runs, f"build:{branch}")
    if kind == "none":
        return "no build result yet", []
    if kind == "null":
        return "the build ended with no result; read its journal before starting it again", []
    if kind == "again":
        return "the build was started again and has not reported yet", []
    if kind == "many":
        return f"{len(built)} results for build:{branch} (heads {heads(built)}); it lands on neither", []
    waiting, rounds = review_state(runs, branch, 1, "attack", "fix")
    if waiting:
        return waiting, []
    if not_sound(rounds[0][0]) or f"attack2:{branch}" in runs:
        waiting, second = review_state(runs, branch, 2, "attack2", "fix2")
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
        verdict = " / ".join(review["verdicts"])[:300]
        lines.append(f"review {n}: {verdict} | findings: {len(review['findings'])}")
        if n == 1:
            lines.append(f"evidence_holds: {str(review['evidence_holds'])[:300]}")
        if fixed:
            last = fixed
            not_fixed = json.dumps(fixed.get("not_fixed", []))[:700]
            lines.append(f"fix {n}: fixed {len(fixed['fixed'])} | not_fixed: {not_fixed}")
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
    try:
        runs = read_journals(argv[1:])
    except BadCall as why:
        print(f"landed: {why}", file=sys.stderr)
        return 2
    branches = sorted({label.split(":", 1)[1] for label in runs if label.startswith("build:")})
    new = []
    for branch in branches:
        waiting, rounds = status(runs, branch)
        if waiting:
            print(f"waiting {branch}: {waiting}")
        elif branch not in seen:
            new.append(branch)
            print("\n".join(block(branch, outcome(runs, f"build:{branch}")[1], rounds)))
    if not new:
        print("landed: nothing new")
        return 1
    state_path.write_text(json.dumps(seen + new), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
