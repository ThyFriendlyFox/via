#!/usr/bin/env python3
"""changes — a change's changelog line in a file of its own, and the release step that folds them.

A change no longer edits `ee-agent-kit/CHANGELOG.md`. It adds 1 file, `ee-agent-kit/changes/<yyyy-mm-dd>-
<slug>.md`: its first line 1 of Keep a Changelog's headings (`### Added`, `### Changed`, ...), then 1 or
more `- ` lines as they will stand in CHANGELOG.md, and nothing else. 2 changes with 2 slugs then never
write the same place: on 2026-11-19 an open pull request conflicted in CHANGELOG.md alone each time `main`
moved (M279). 1 name in 2 branches is git's add/add conflict, as for any file. A `- ` line stands once:
check refuses one that CHANGELOG.md, another change file or the same file holds, or that ends in white
space. A line written straight under `## [Unreleased]` stays valid; every action reads both places.

    changes.py [--root DIR] check                  every change file well formed; exit 1 with file:line
    changes.py [--root DIR] show                   what ## [Unreleased] holds today, from both places
    changes.py [--root DIR] fold <X.Y.Z> <date>    the release step: ## [X.Y.Z] - <date>, files deleted

The order under a heading: the change files newest first (by the date in the name, then the name),
then CHANGELOG.md's own Unreleased lines as they stand. Standard library only: the kit checks run it
with the system's python3 in `make verify` and `make verify-site`.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CHANGELOG = "ee-agent-kit/CHANGELOG.md"
FOLDER = "ee-agent-kit/changes"
# Keep a Changelog 1.1.0's kinds of change, in its order (https://keepachangelog.com/en/1.1.0/).
HEADINGS = ("Added", "Changed", "Deprecated", "Removed", "Fixed", "Security")
KNOWN = ", ".join(f"### {h}" for h in HEADINGS)
NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})-([a-z0-9]+(?:-[a-z0-9]+)*)\.md$")
FORM = "the name is not <yyyy-mm-dd>-<slug>.md (slug: a-z, 0-9 and -)"
UNRELEASED = "## [Unreleased]"
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


class Section:
    """CHANGELOG.md's Unreleased section: where it starts and ends, and its lines under their headings."""

    def __init__(self, lines: list[str], start: int, end: int, entries: list[tuple[str, str]]):
        self.lines, self.start, self.end, self.entries = lines, start, end, entries


def read_unreleased(text: str) -> tuple[Section | None, list[tuple[int, str]]]:
    """The Unreleased section, and each fault as (line number, why)."""
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == UNRELEASED]
    if not starts:
        return None, [(1, f"no '{UNRELEASED}' line")]
    start = starts[0]
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    # heading: None before the first heading; "" under a heading already faulted (its lines are not
    # faulted again).
    entries, faults, heading = [], [], None
    for i in range(start + 1, end):
        line = lines[i]
        if not line.strip():
            continue
        if line.startswith("### "):
            heading = line[4:].strip()
            if heading not in HEADINGS:
                faults.append((i + 1, f"'{line}' is not 1 of {KNOWN}"))
                heading = ""
        elif line.startswith("- "):
            if heading is None:
                faults.append((i + 1, f"a '- ' line under no heading of {UNRELEASED}"))
            elif heading:
                entries.append((heading, line))
        else:
            faults.append((i + 1, f"not a heading or a '- ' line: {line!r}"))
    return Section(lines, start, end, entries), faults


def newest_first(paths: list[Path]) -> list[Path]:
    """Change files by the date in their name, newest first; on 1 day, by name."""
    by_name = sorted(paths, key=lambda p: p.name)
    return sorted(by_name, key=lambda p: p.name[:10], reverse=True)


def change_files(root: Path) -> list[Path]:
    """Every file of the folder but its README, in name order."""
    folder = root / FOLDER
    if not folder.is_dir():
        return []
    return sorted(
        (p for p in folder.iterdir() if p.is_file() and p.name != "README.md"), key=lambda p: p.name
    )


def read_change(
    path: Path, rel: str, seen: dict[str, str]
) -> tuple[str | None, list[str], list[tuple[int, str]]]:
    """A change file's heading, its lines and its faults as (line number, why). `seen` maps each '- '
    line read so far (CHANGELOG.md's, then the change files', end white space cut) to where it stands;
    this file's lines are added, so a line in 2 files, or 2 times in 1, is a fault."""
    match = NAME.match(path.name)
    if not match:
        return None, [], [(1, FORM)]
    try:
        datetime.date.fromisoformat(match.group(1))
    except ValueError:
        return None, [], [(1, f"the name's date {match.group(1)} is not a day")]
    try:
        lines = path.read_text(encoding="utf-8").rstrip("\n").split("\n")
    except UnicodeDecodeError:
        return None, [], [(1, "the file is not UTF-8 text")]
    faults = []
    heading = lines[0][4:].strip() if lines[0].startswith("### ") else None
    if heading not in HEADINGS:
        faults.append((1, f"the first line is {lines[0]!r}; it must be 1 of {KNOWN}"))
    body = lines[1:]
    if not body:
        faults.append((1, "no '- ' line under the heading"))
    for n, line in enumerate(body, start=2):
        if not line.startswith("- "):
            faults.append((n, f"not a '- ' line: {line!r}"))
        elif not line[2:].strip():
            faults.append((n, "a '- ' line with no words"))
        else:
            if line != line.rstrip():
                faults.append((n, "the line ends in white space"))
            key = line.rstrip()
            if key in seen:
                faults.append((n, f"this line is already in {seen[key]}"))
            else:
                seen[key] = f"{rel}, line {n}"
    return heading, body, faults


def gather(root: Path) -> tuple[Section | None, list[tuple[Path, str, list[str]]], list[str]]:
    """The Unreleased section, each well-formed change file (path, heading, lines), and every fault."""
    text = (root / CHANGELOG).read_text(encoding="utf-8")
    section, faults = read_unreleased(text)
    out = [f"{CHANGELOG}:{n}: {why}" for n, why in faults]
    seen: dict[str, str] = {}
    for n, line in enumerate(text.splitlines(), start=1):
        if line.startswith("- "):
            seen.setdefault(line.rstrip(), f"{CHANGELOG}, line {n}")
    files = []
    for path in change_files(root):
        rel = f"{FOLDER}/{path.name}"
        heading, body, faults = read_change(path, rel, seen)
        out += [f"{rel}:{n}: {why}" for n, why in sorted(faults)]
        if not faults:
            files.append((path, heading, body))
    return section, files, out


def unreleased_lines(section: Section, files: list[tuple[Path, str, list[str]]]) -> dict[str, list[str]]:
    """Each heading's lines: the change files newest first, then CHANGELOG.md's own."""
    grouped: dict[str, list[str]] = {h: [] for h in HEADINGS}
    order = {path: i for i, path in enumerate(newest_first([f[0] for f in files]))}
    for _path, heading, body in sorted(files, key=lambda f: order[f[0]]):
        grouped[heading] += body
    for heading, line in section.entries:
        grouped[heading].append(line)
    return grouped


def as_text(grouped: dict[str, list[str]]) -> list[str]:
    return [line for h in HEADINGS if grouped[h] for line in (f"### {h}", *grouped[h])]


def unreleased_texts(root: Path) -> list[tuple[str, str]]:
    """CHANGELOG.md's text, then each change file's, newest first: what a reader of the Unreleased
    lines reads (tests/test_docs.py reads their roadmap pointers)."""
    texts = [(CHANGELOG, (root / CHANGELOG).read_text(encoding="utf-8"))]
    for path in newest_first(change_files(root)):
        texts.append((f"{FOLDER}/{path.name}", path.read_text(encoding="utf-8")))
    return texts


def count(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def cmd_check(root: Path) -> int:
    _section, files, faults = gather(root)
    if faults:
        print("\n".join(faults))
        where = {f.split(":", 1)[0] for f in faults}
        print(
            f"changes: {count(len(faults), 'fault')} in {count(len(where), 'file')} "
            f"({FOLDER}/README.md says the form)"
        )
        return 1
    lines = sum(len(body) for _p, _h, body in files)
    print(f"changes: {count(len(files), 'file')}, {count(lines, 'line')}; ok")
    return 0


def cmd_show(root: Path) -> int:
    section, files, faults = gather(root)
    if section is None:
        print("\n".join(faults))
        return 1
    print("\n".join([UNRELEASED, *as_text(unreleased_lines(section, files))]))
    if faults:
        print(f"changes: {len(faults)} faults left out; run check", file=sys.stderr)
    return 0


def cmd_fold(root: Path, version: str, date: str) -> int:
    if not VERSION.match(version):
        print(f"fold: the version {version!r} is not X.Y.Z; nothing changed")
        return 1
    try:
        datetime.date.fromisoformat(date)
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            raise ValueError(date)
    except ValueError:
        print(f"fold: the date {date!r} is not a day; nothing changed")
        return 1
    section, files, faults = gather(root)
    if faults or section is None:
        print("\n".join(faults))
        print("fold: check failed; nothing changed")
        return 1
    pending = sum(len(body) for _p, _h, body in files) + len(section.entries)
    there = any(line.startswith(f"## [{version}]") for line in section.lines)
    if there and not pending:
        print(f"fold: ## [{version}] is there and nothing is unreleased; nothing changed")
        return 0
    if there:
        print(f"fold: {CHANGELOG} already has ## [{version}]; nothing changed")
        return 1
    if not pending:
        print("fold: nothing is unreleased; nothing changed")
        return 1
    lines = section.lines
    after = lines[section.end :]
    release = [
        f"## [{version}] - {date}",
        *as_text(unreleased_lines(section, files)),
        *([""] if after else []),
    ]
    new = [*lines[: section.start + 1], "", *release, *after]
    (root / CHANGELOG).write_text("\n".join(new) + "\n", encoding="utf-8")
    from_files = pending - len(section.entries)
    print(
        f"fold: ## [{version}] - {date} holds {count(pending, 'line')}, {len(section.entries)} from "
        f"CHANGELOG.md and {from_files} from {count(len(files), 'change file')}"
    )
    for path, _h, _b in files:
        path.unlink()
        print(f"fold: deleted {FOLDER}/{path.name}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--root", type=Path, default=ROOT, help="the repository (default: this one)")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("check", help="every change file is well formed")
    sub.add_parser("show", help="what ## [Unreleased] holds today")
    fold = sub.add_parser("fold", help="the release step")
    fold.add_argument("version")
    fold.add_argument("date")
    args = parser.parse_args(argv)
    if args.action == "check":
        return cmd_check(args.root)
    if args.action == "show":
        return cmd_show(args.root)
    return cmd_fold(args.root, args.version, args.date)


if __name__ == "__main__":
    sys.exit(main())
