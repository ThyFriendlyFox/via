"""The product is Via; `workcenter` is its command (docs/STYLE.md, Terms; the owner's words of 2026-11-19).

The documents a person reads say "Via". They do not write "EE Workcenter" or "the workcenter" in
prose. A code span and a fenced block are code: a command, a path or a printed line stays as the
program has it. History stays as it was written: the dated entries of DEVLOG.md, the released
sections of CHANGELOG.md and every entry of MISTAKES.md. The website, the blog and the example
projects have their own rules and are not read here.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Folders whose text another rule governs, or that are not this repository's words.
OUTSIDE = ("examples/", "site/", "blog/", "third_party/")
OLD_NAME = re.compile(r"\bEE[ \t]+Work[ \t]?center\b|\bthe[ \t]+workcenter\b", re.IGNORECASE)
FENCE = re.compile(r"^[ \t]*(```|~~~)")
SPAN = re.compile(r"(`+)(?:(?!\1).)+?\1", re.DOTALL)


def history_start(rel: str, lines: list[str]) -> int | None:
    """The index of the first line of a file's history, which stays as it was written; None for a
    file with no history. DEVLOG.md's entries start at its first dated heading, CHANGELOG.md's
    released sections at the first heading after `## [Unreleased]`, and MISTAKES.md is all history."""
    if rel == "ee-agent-kit/MISTAKES.md":
        return 0
    if rel == "ee-agent-kit/DEVLOG.md":
        pattern = re.compile(r"^## \d{4}-\d{2}-\d{2}\b")
    elif rel == "ee-agent-kit/CHANGELOG.md":
        pattern = re.compile(r"^## \[(?!Unreleased\])")
    else:
        return None
    return next((i for i, line in enumerate(lines) if pattern.match(line)), None)


def prose(text: str) -> list[str]:
    """The text's lines with each fenced block and each code span blanked; line numbers stay."""
    lines = text.split("\n")
    fenced = None
    for i, line in enumerate(lines):
        mark = FENCE.match(line)
        if fenced is None and mark:
            fenced = mark.group(1)
            lines[i] = ""
        elif fenced is not None:
            if mark and mark.group(1) == fenced:
                fenced = None
            lines[i] = ""
    joined = "\n".join(lines)
    joined = SPAN.sub(lambda m: "\n" * m.group(0).count("\n") or " ", joined)
    return joined.split("\n")


def old_names(text: str, rel: str = "") -> list[int]:
    """The 1-based numbers of the lines that write the old name in prose, a name split over 2 lines
    counted on its first line."""
    lines = text.split("\n")
    end = history_start(rel, lines)
    shown = prose("\n".join(lines[:end] if end is not None else lines))
    found = []
    for i, line in enumerate(shown):
        following = shown[i + 1] if i + 1 < len(shown) else ""
        split = re.search(r"\b(the|EE)[ \t]*$", line, re.I) and re.match(r"[ \t]*work[ \t]?center\b", following, re.I)
        if OLD_NAME.search(line) or split:
            found.append(i + 1)
    return found


def documents() -> list[str]:
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "*.md"], capture_output=True, text=True, check=True
    ).stdout.split("\n")
    return [rel for rel in tracked if rel and not rel.startswith(OUTSIDE)]


def test_no_document_calls_the_product_by_its_old_name():
    found = []
    for rel in documents():
        path = ROOT / rel
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            found += [f"{rel}:{n}: {text.split(chr(10))[n - 1].strip()}" for n in old_names(text, rel)]
    assert found == []


def test_the_reader_leaves_code_and_history_alone():
    text = "\n".join(
        [
            "Run `workcenter doctor`; it prints `workcenter ee: ok`.",  # 1: the command, in a span
            "```",
            "the workcenter's own line, as a program prints it",  # 3: in a fenced block
            "```",
            "Via turns a project into fabrication outputs.",  # 5
            "The workcenter turns a project into outputs.",  # 6: the old name
            "A sentence that ends with the",  # 7: the old name over 2 lines
            "workcenter's image.",
            "The EE Workcenter toolchain.",  # 9
            "A path `/opt/workcenters/ee`, a variable `WORKCENTER_ROOT`.",  # 10
        ]
    )
    assert old_names(text) == [6, 7, 9]


def test_history_is_not_read():
    devlog = "# DEVLOG\n\nThe workcenter is the old name.\n\n## 2026-11-18 — An entry\n\nthe workcenter ran.\n"
    assert old_names(devlog, "ee-agent-kit/DEVLOG.md") == [3]
    changelog = "## [Unreleased]\n\nthe workcenter\n\n## [0.1.0] - 2026-11-19\n\nthe workcenter\n"
    assert old_names(changelog, "ee-agent-kit/CHANGELOG.md") == [3]
    assert old_names("the workcenter\n", "ee-agent-kit/MISTAKES.md") == []
