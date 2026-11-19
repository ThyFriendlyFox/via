"""The product is Via; `workcenter` is its command (docs/STYLE.md, Terms; the owner's words of 2026-11-19).

The documents a person reads say "Via". They do not write "EE Workcenter" or "the workcenter" in
prose. A code span and a fenced block are code: a command, a path or a printed line stays as the
program has it. History stays as it was written: the DEVLOG.md entries, the released sections of
CHANGELOG.md and the MISTAKES.md entries that stood when the product became Via. An entry written
after that is read. The website, the blog and the example projects have their own rules and are not
read here. Only the Markdown files are read: the program's strings, the JSON notes, the workflow
prompts and other files are not held by this test.

The program's strings say Via as well; the tests of each tool hold them. 4 tokens keep the old name on
purpose (docs/STYLE.md, Terms): the fetch client's name "EE-Workcenter/1", under which sites' answers
are recorded; the references cache ~/.cache/ee-workcenter; the comments of the Dockerfile, install.sh
and requirements.txt, whose change would move the image's content tag; and the doctor's line
"workcenter ee: ok". A rule file or a sources.csv row written before the change keeps its older words.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Folders whose text another rule governs, or that are not this repository's words.
OUTSIDE = ("examples/", "site/", "blog/", "third_party/")
# Between 2 words: spaces, tabs, a non-breaking space, a hyphen, and emphasis marks around a word.
GAP = r"[*_]*[ \t -]+[*_]*"
OLD_NAME = re.compile(rf"\bEE{GAP}Work(?:{GAP})?center\b|\bthe{GAP}workcenter\b", re.IGNORECASE)
FENCE = re.compile(r"^[ \t]*(```|~~~)")
# A code span ends at its closing backticks, and never past a blank line: Markdown makes no span
# across a paragraph break, so a stray backtick does not hide the prose after it.
SPAN = re.compile(r"(`+)(?:(?!\1)(?!\n[ \t]*\n).)+?\1", re.DOTALL)

# The history as it stood when the product became Via, which stays as it was written. An entry
# written after that is read like any other text, wherever it stands in its file.
DEVLOG_BEFORE = "2026-11-19"  # every DEVLOG entry dated before this day
DEVLOG_THAT_DAY = (  # and the entries of that day written before the change
    "The container image and its package are named via",
    "CI's install path asks Ubuntu's own archive",
)
CHANGELOG_RELEASED = ("0.1.0",)  # the released sections
MISTAKES_LAST = 272  # M1 to M272
DATED = re.compile(r"^## (\d{4}-\d{2}-\d{2}) — (.*)$")
RELEASE = re.compile(r"^## \[([^\]]+)\]")
MISTAKE = re.compile(r"^## M(\d+) ")


def is_history(rel: str, heading: str) -> bool:
    """Whether the section under this `## ` heading is history that stays as it was written."""
    if rel == "ee-agent-kit/DEVLOG.md":
        m = DATED.match(heading)
        if not m:
            return False
        day, title = m.groups()
        return day < DEVLOG_BEFORE or (day == DEVLOG_BEFORE and title in DEVLOG_THAT_DAY)
    if rel == "ee-agent-kit/CHANGELOG.md":
        m = RELEASE.match(heading)
        return bool(m) and m.group(1) in CHANGELOG_RELEASED
    if rel == "ee-agent-kit/MISTAKES.md":
        m = MISTAKE.match(heading)
        return bool(m) and int(m.group(1)) <= MISTAKES_LAST
    return False


def without_history(rel: str, lines: list[str]) -> list[str]:
    """The lines with each history section blanked, from its `## ` heading to the next; numbers stay."""
    kept, skipping, fenced = [], False, False
    for line in lines:
        if FENCE.match(line):
            fenced = not fenced
        if not fenced and line.startswith("## "):
            skipping = is_history(rel, line)
        kept.append("" if skipping else line)
    return kept


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
    shown = prose("\n".join(without_history(rel, text.split("\n"))))
    found = []
    for i, line in enumerate(shown):
        following = shown[i + 1] if i + 1 < len(shown) else ""
        split = re.search(r"\b(the|EE)[ \t]*$", line, re.I) and re.match(
            r"[ \t]*work[ \t]?center\b", following, re.I
        )
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
            "A lone ` here.",  # 11: a stray backtick opens no span past the paragraph
            "",
            "the workcenter ran.",  # 13
            "",
            "Then `x` here.",
            "The EE-Workcenter toolchain.",  # 16
            "*the* workcenter, **the workcenter**.",  # 17
            "the workcenter",  # 18: a non-breaking space
        ]
    )
    assert old_names(text) == [6, 7, 9, 13, 16, 17, 18]


def test_history_is_the_history_of_this_change_and_no_later_entry():
    devlog = (
        "# DEVLOG\n\nThe workcenter is the old name.\n\n"  # 3
        "## 2026-11-20 — A new entry, above the old ones\n\nthe workcenter ran today.\n\n"  # 7
        "## 2026-11-19 — CI's install path asks Ubuntu's own archive\n\nthe workcenter ran.\n\n"
        "## 2026-11-18 — An entry\n\nthe workcenter ran.\n\n"
        "## 2026-11-19 — An entry of today's date written after this change\n\nthe workcenter ran.\n"  # 19
    )
    assert old_names(devlog, "ee-agent-kit/DEVLOG.md") == [3, 7, 19]
    changelog = (
        "## [Unreleased]\n\nthe workcenter\n\n"  # 3
        "## [0.2.0] - 2026-12-01\n\nthe workcenter\n\n"  # 7
        "## [0.1.0] - 2026-11-19\n### Changed\n- the workcenter\n"
    )
    assert old_names(changelog, "ee-agent-kit/CHANGELOG.md") == [3, 7]
    mistakes = (
        "# MISTAKES.md\n\nthe workcenter\n\n"  # 3
        "## M272 — 2026-11-19 — An entry\nWhat happened: the workcenter\n\n"
        "## M273 — 2026-11-20 — A new entry\nWhat happened: the workcenter\n"  # 9
    )
    assert old_names(mistakes, "ee-agent-kit/MISTAKES.md") == [3, 9]
