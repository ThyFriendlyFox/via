#!/usr/bin/env python3
"""scope — what a change needs: `fast` when it touches only what no engine reads, `full` otherwise.

A path is judged by its folder and its kind (RULES). A document is judged by its text too: the runs it
shows and the README's quick start are run by tests/test_docs.py with the engines, so a change inside
one makes the change full. `runs_in`, `document_text` and `quick_start` are the readers that
tests/test_docs.py uses; it imports them from here, so the 2 cannot read a block differently.

    scope.py --base B [--head H]   the diff from commit B to commit H (to the working tree without H)
    scope.py --paths P [P ...]     a list of paths, read from the working tree

Each judged path prints 1 line, `<answer>  <path>: <why>`; the last line is the answer alone. A path
no rule names is full; a diff git cannot read is full. Exit code 0 for either answer, 2 for misuse.
The GitHub workflow and the Makefile both call this script. Standard library only.
"""

from __future__ import annotations

import argparse
import html
import os
import re
import subprocess
import sys
from pathlib import Path

FAST, FULL = "fast", "full"

# Folders whose documents a command or a gate reads: a fixture's or an example's files, the templates
# `workcenter verify init` copies, the skills `workcenter next` names by heading, vendored skills.
ENGINE_FOLDERS = ("tests", "examples", "templates", "third_party", ".claude")
DOCUMENT_SUFFIXES = (".md", ".html")
UNKNOWN = "no rule names this path, so it needs the full gate"


# ---------------------------------------------------------------- the readers test_docs.py uses


def document_text(name: str, text: str) -> str:
    """A file's text as the document tests read it. A page of the site gives each `<code>` span as
    code, with its tags left out and its entities read."""
    if not name.endswith(".html"):
        return text
    return html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"</?code>", "`", text)))


def runs_in(text: str) -> list[tuple[tuple[str, ...], list[str]]]:
    """Each `$ workcenter ...` line of a document, with the lines printed under it up to the next
    blank line or the end of its block."""
    runs: list[tuple[tuple[str, ...], list[str]]] = []
    in_run = False
    for line in text.splitlines():
        if line.startswith("$ workcenter "):
            runs.append((tuple(line.split()[2:]), []))
            in_run = True
        elif not line.strip() or line.startswith("```"):
            in_run = False
        elif in_run:
            runs[-1][1].append(line.rstrip())
    return runs


def quick_start(text: str) -> list[str]:
    """The lines of the `sh` blocks under a document's `## Quick start` heading, up to the next
    heading of that level. A document without the heading has none."""
    if "\n## Quick start\n" not in text:
        return []
    section = text.split("\n## Quick start\n", 1)[1].split("\n## ", 1)[0]
    return [line for block in re.findall(r"```sh\n(.*?)```", section, re.S) for line in block.splitlines()]


# ---------------------------------------------------------------- judging a path


def rule_of(path: str) -> tuple[str, str]:
    """The answer for a path by its folder and kind, before its text is read."""
    top = path.split("/", 1)[0]
    if top == "site":
        return FAST, "the site"
    if path.endswith(".md"):
        if top in ENGINE_FOLDERS and "/" in path:
            return FULL, f"a command reads the files under {top}/"
        return FAST, "a document"
    return FULL, UNKNOWN


def judge(path: str, old: str | None, new: str | None, texts: bool) -> tuple[str, str]:
    """The answer for 1 changed path. With `texts`, `old` and `new` are its text before and after (None
    where the file is absent); without, `new` is the text on disk and nothing is compared."""
    answer, why = rule_of(path)
    if answer == FULL or not path.endswith(DOCUMENT_SUFFIXES):
        return answer, why
    before = document_text(path, old or "")
    after = document_text(path, new or "")
    if not texts:
        if runs_in(after) or quick_start(after):
            return FULL, "a list of paths cannot show whether its shown runs changed"
        return answer, why
    was, now = runs_in(before), runs_in(after)
    if was != now:
        changed = [argv for argv, lines in now if (argv, lines) not in was]
        changed += [argv for argv, lines in was if (argv, lines) not in now and argv not in changed]
        return FULL, f"a shown run changed: workcenter {' '.join(changed[0])}"
    if quick_start(before) != quick_start(after):
        return FULL, "the quick start changed: its commands run with the engines"
    return answer, f"{why}; its shown runs are as they were"


# ---------------------------------------------------------------- reading the change from git


def git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, check=False)


def text_at(repo: Path, ref: str | None, path: str) -> str | None:
    """A file's text at a commit, or in the working tree without one; None where it is absent."""
    if ref is None:
        file = repo / path
        return file.read_text(encoding="utf-8", errors="replace") if file.is_file() else None
    shown = git(repo, "show", f"{ref}:{path}")
    return shown.stdout.decode("utf-8", errors="replace") if shown.returncode == 0 else None


def changed_paths(repo: Path, base: str, head: str | None) -> tuple[list[str] | None, str]:
    """The paths that differ between the 2 commits (or base and the working tree with the files git does
    not track yet), each rename as its 2 paths; None and git's message where git cannot read them."""
    diff = git(repo, "diff", "--name-only", "--no-renames", "-z", base, *([head] if head else []))
    if diff.returncode != 0:
        said = diff.stderr.decode("utf-8", errors="replace").strip().splitlines()
        return None, said[0] if said else f"git diff exit code {diff.returncode}"
    paths = [p for p in diff.stdout.decode("utf-8").split("\0") if p]
    if head is None:
        new = git(repo, "ls-files", "--others", "--exclude-standard", "-z")
        paths += [p for p in new.stdout.decode("utf-8").split("\0") if p]
    return sorted(set(paths)), ""


def decide(repo: Path, base: str | None, head: str | None, paths: list[str] | None) -> list[tuple[str, str]]:
    """The judged lines as (answer, `<path>: <why>`), in the order of answer and path, the widest
    answer last on its own."""
    lines: list[tuple[str, str, str]] = []
    if paths is not None:
        lines = [(*judge(p, None, text_at(repo, None, p), texts=False), p) for p in paths]
    elif not base:
        lines = [(FULL, "no base to compare with", "(no base)")]
    else:
        found, said = changed_paths(repo, base, head)
        if found is None:
            lines = [(FULL, f"git cannot read the change from {base}: {said}", "(diff)")]
        elif not found:
            lines = [(FAST, "the 2 commits hold the same files", "(no path)")]
        else:
            ref = head or None
            lines = [(*judge(p, text_at(repo, base, p), text_at(repo, ref, p), texts=True), p) for p in found]
    judged = [(answer, f"{path}: {why}") for answer, why, path in sorted(lines, key=lambda x: (x[0], x[2]))]
    answer = FULL if any(a == FULL for a, _ in judged) else FAST
    return [*judged, (answer, "")]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="scope.py", description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="the checkout (default: here)")
    parser.add_argument("--base", help="the commit the change starts from; empty: no base, so full")
    parser.add_argument("--head", help="the commit the change ends at (default: the working tree)")
    parser.add_argument("--paths", nargs="+", help="judge these paths by their rules, without a diff")
    parser.add_argument(
        "--github-output", action="store_true", help="also append scope=<answer> to $GITHUB_OUTPUT"
    )
    args = parser.parse_args(argv)
    if (args.base is None) == (args.paths is None):
        parser.error("give --base (with or without --head) or --paths")
    output = os.environ.get("GITHUB_OUTPUT", "")
    if args.github_output and not output:
        print("scope.py: --github-output needs $GITHUB_OUTPUT, the file GitHub reads", file=sys.stderr)
        return 2
    lines = decide(args.repo, args.base, args.head, args.paths)
    for answer, line in lines[:-1]:
        print(f"{answer}  {line}")
    answer = lines[-1][0]
    print(answer)
    if args.github_output:
        with open(output, "a", encoding="utf-8") as out:
            out.write(f"scope={answer}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
