#!/usr/bin/env python3
"""harvest — what the projects taught the workcenter, read from the repository itself.

Every project built with the workcenter leaves findings behind: commits on a branch that never
reached main, a script the project wrote because the workcenter had no tool, a mistake made again
under a step that already forbade it. Each of the 3 listings here finds 1 kind, from git objects and
tracked files alone. No engine runs and nothing is written.

    python3 tools/harvest.py branches   every branch: its own commits, and how much of what they
                                        added to the workcenter itself main holds today
    python3 tools/harvest.py scripts    the scripts the projects wrote for themselves, by name, with
                                        the projects that wrote each and the functions they share
    python3 tools/harvest.py mistakes   the mistakes log by process: its entries, and the entries
                                        that name an earlier entry of the same process

`--json` prints the listing as data. `ee-agent-kit/PROCESSES.md` P35 says when to run them, how a
finding is rated and where it goes.

How `branches` reads a branch. Its base is the last state it shares with main: the merge base, or for
a branch from before main's history was rewritten the newest commit whose tree is a tree of main's
history. Its own commits are the ones after the base. For each file of the workcenter itself that
they change, a line the branch added counts as on main when main's file of that path holds it. A
line is compared without the number of a mistake, a process or a list step: `M162` becomes `M167`
when 2 branches land, and step 7 becomes step 8. A branch at 100 % has landed, whatever its commits
are called on main.

Standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# Where a path of the repository belongs. The first 6 areas are the workcenter itself: what a branch
# added there and main lacks is a finding. A project's own files, the site and vendored code are not.
AREAS = (
    (
        "tools",
        ("tools/", "verify/", "install.sh", "Makefile", "environment/", "Dockerfile", "requirements.txt"),
    ),
    ("tests", ("tests/",)),
    ("skills", (".claude/skills/", "ee-agent-kit/skills/")),
    ("templates", ("templates/", "pdks/")),
    ("kit", ("ee-agent-kit/", "WORKCENTER.md", "CLAUDE.md", "AGENTS.md")),
    ("ci", (".github/",)),
    ("front", ("README.md", "LICENSE", "NOTICE")),
    ("examples", ("examples/",)),
    ("site", ("site/",)),
    ("vendored", ("third_party/",)),
)
OWN = ("tools", "tests", "skills", "templates", "kit", "ci")
NUMBER_RE = re.compile(r"\b([MP])\d{1,3}\b")
STEP_RE = re.compile(r"^\d{1,2}\. ")
# A line shorter than this says too little to be told from any other: a brace, a blank, `else:`.
LEAST = 14
TEXT_SUFFIXES = (
    ".py",
    ".md",
    ".sh",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".txt",
    ".tcl",
    ".ys",
    ".csv",
    ".cfg",
    "",
)
SCRIPT_SUFFIXES = (".py", ".mjs", ".sh")
# A project's files that every project has, or that are no tool of its own.
NOT_A_SCRIPT = ("design.py",)
NOT_SCRIPT_FOLDERS = ("firmware", "sim", "build")
ENTRY_RE = re.compile(r"^## M(\d+) — (?:(\d{4}-\d{2}-\d{2}) — )?(.+)$", re.M)


def git(repo: Path | str, *args: str, check: bool = True) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, errors="replace", check=False
    )
    if check and done.returncode != 0:
        raise SystemExit(f"harvest: git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def area(path: str) -> str:
    for name, starts in AREAS:
        if any(path == start or path.startswith(start) for start in starts):
            return name
    return "other"


def plain(line: str) -> str:
    """A line without what moves when another branch lands first: the number of a mistake or a
    process, and the number of a step at its start."""
    return NUMBER_RE.sub(r"\1#", STEP_RE.sub("#. ", line.strip()))


def lines_of(repo: Path | str, ref: str, path: str) -> set[str] | None:
    done = subprocess.run(["git", "-C", str(repo), "show", f"{ref}:{path}"], capture_output=True, check=False)
    if done.returncode != 0:
        return None
    return {plain(line) for line in done.stdout.decode("utf-8", "replace").splitlines()}


def base_of(repo: Path | str, main: str, tip: str, main_trees: dict[str, str]) -> tuple[str | None, str]:
    """(the last state a branch shares with main, how it was found)."""
    merged = git(repo, "merge-base", main, tip, check=False).strip()
    if merged:
        return merged, "merge base"
    # A branch from before main's history was rewritten: no commit of it is main's, and a tree is.
    for line in git(repo, "log", "--first-parent", "--format=%H %T", tip).splitlines():
        commit, tree = line.split()
        if tree in main_trees:
            return commit, f"the tree of main's {main_trees[tree][:8]}"
    return None, "no state shared with main"


def lacking_of(repo: Path | str, main: str, base: str, tip: str, paths: list[str], by_name: dict) -> tuple:
    """(lines the branch added, lines of those on main, the files with lines main lacks).

    A short line (`else:`, `return x`, a brace) that main's file holds proves nothing: the file may
    hold it anywhere. So a line under `LEAST` characters is counted only when main's file does not
    hold it at all: then it is missing for sure, as a version pin or a 1-line fix is."""
    added_total = held_total = 0
    lacking = []
    for path in paths:
        diff = git(repo, "diff", "--no-renames", "-U0", base, tip, "--", path)
        every = [
            plain(line[1:])
            for line in diff.splitlines()
            if line.startswith("+") and not line.startswith("+++") and line[1:].strip()
        ]
        if not every:
            continue
        there = lines_of(repo, main, path)
        on_main = there is not None
        if there is None:
            # main has no file of that path: a file of that name elsewhere may hold the lines
            others = by_name.get(Path(path).name, [])
            there = set().union(*((lines_of(repo, main, other) or set()) for other in others[:3]))
        added = [line for line in every if len(line) >= LEAST or line not in there]
        if not added:
            continue
        missing = [line for line in added if line not in there]
        added_total += len(added)
        held_total += len(added) - len(missing)
        if missing:
            lacking.append(
                {
                    "path": path,
                    "area": area(path),
                    "file_on_main": on_main,
                    "added": len(added),
                    "missing": len(missing),
                    "first": missing[:6],
                }
            )
    return added_total, held_total, sorted(lacking, key=lambda f: (-f["missing"], f["path"]))


def branches(repo: Path | str, main: str, prefix: str) -> list[dict]:
    """1 entry for each ref under `prefix`: what the branch holds of its own and what main lacks."""
    main_tip = git(repo, "rev-parse", main).strip()
    main_trees: dict[str, str] = {}
    for line in git(repo, "log", "--format=%H %T", main).splitlines():
        commit, tree = line.split()
        main_trees.setdefault(tree, commit)
    by_name: dict[str, list[str]] = {}
    for path in git(repo, "ls-tree", "-r", "--name-only", main).splitlines():
        by_name.setdefault(Path(path).name, []).append(path)
    out = []
    refs = git(repo, "for-each-ref", "--format=%(refname) %(objectname) %(committerdate:short)", prefix)
    for ref_line in refs.splitlines():
        ref, tip, date = ref_line.split()
        entry: dict = {
            "branch": ref[len(prefix) :].lstrip("/"),
            "tip": tip[:8],
            "date": date,
            "own_commits": 0,
        }
        out.append(entry)
        if tip == main_tip:
            entry["state"] = "is main"
            continue
        if (
            subprocess.run(
                ["git", "-C", str(repo), "merge-base", "--is-ancestor", tip, main], check=False
            ).returncode
            == 0
        ):
            entry["state"] = "in main's history"
            continue
        base, how = base_of(repo, main, tip, main_trees)
        entry["base"] = (base or "")[:8]
        entry["base_found_by"] = how
        subjects = git(
            repo,
            "log",
            "--first-parent",
            "--format=%h %ad %s",
            "--date=short",
            f"{base}..{tip}" if base else tip,
        ).splitlines()
        entry["own_commits"] = len(subjects)
        entry["subjects"] = subjects[:40]
        if not subjects:
            entry["state"] = "a state main had: nothing of its own"
            continue
        if base is None:
            entry["state"] = "no state shared with main: read it by hand"
            continue
        areas: dict[str, dict] = {}
        files = []
        for row in git(repo, "diff", "--numstat", "--no-renames", base, tip).splitlines():
            added, _, path = row.split("\t")
            total = areas.setdefault(area(path), {"files": 0, "added": 0})
            total["files"] += 1
            total["added"] += int(added) if added.isdigit() else 0
            if area(path) in OWN and added.isdigit() and int(added) and Path(path).suffix in TEXT_SUFFIXES:
                files.append(path)
        entry["areas"] = areas
        added_total, held_total, lacking = lacking_of(repo, main, base, tip, files, by_name)
        entry["own_lines_added"] = added_total
        entry["own_lines_on_main"] = held_total
        entry["share_on_main"] = round(held_total / added_total, 3) if added_total else None
        entry["lacking"] = lacking
        missing = added_total - held_total
        if not added_total:
            entry["state"] = "its own commits change nothing of the workcenter itself"
        elif not missing:
            entry["state"] = "landed: every line it added to the workcenter is on main"
        else:
            entry["state"] = f"{missing} of {added_total} lines it added to the workcenter are not on main"
    return out


def scripts(repo: Path | str, ref: str, root: str = "examples") -> list[dict]:
    """The scripts the projects under `root` wrote for themselves, by file name. A name that 2 or more
    projects wrote is a tool the workcenter lacks; the functions their newest files share are its
    first calls."""
    found: dict[str, dict[str, list[str]]] = {}
    for path in git(repo, "ls-tree", "-r", "--name-only", ref, "--", root).splitlines():
        parts = Path(path).parts
        if len(parts) < 3 or Path(path).suffix not in SCRIPT_SUFFIXES or parts[-1] in NOT_A_SCRIPT:
            continue
        if any(folder in NOT_SCRIPT_FOLDERS for folder in parts[2:-1]):
            continue
        found.setdefault(parts[-1], {}).setdefault(parts[1], []).append(path)
    out = []
    for name, projects in found.items():
        shared: dict[str, int] = {}
        for paths in projects.values():
            # the newest version of a project stands for it: its last path in the tree's order
            text = git(repo, "show", f"{ref}:{sorted(paths)[-1]}", check=False)
            for function in set(re.findall(r"^def ([A-Za-z_]\w*)\(", text, re.M)):
                shared[function] = shared.get(function, 0) + 1
        out.append(
            {
                "script": name,
                "projects": len(projects),
                "files": sum(len(paths) for paths in projects.values()),
                "where": {project: sorted(paths) for project, paths in sorted(projects.items())},
                "functions_in_2_or_more": dict(
                    sorted(
                        ((f, n) for f, n in shared.items() if n >= 2), key=lambda item: (-item[1], item[0])
                    )
                ),
            }
        )
    return sorted(out, key=lambda entry: (-entry["projects"], -entry["files"], entry["script"]))


def mistakes(log: str, processes: str) -> list[dict]:
    """The mistakes log by process: its entries, and the entries that name an earlier entry of the same
    process. Such an entry is a step that did not hold: the mistake was made again under it, and a
    machine check holds where a step did not."""
    names = dict(re.findall(r"^## (P\d+) — (.+)$", processes, re.M))
    found = list(ENTRY_RE.finditer(log))
    process_of: dict[int, str] = {}
    entries = []
    for i, match in enumerate(found):
        body = log[match.end() : found[i + 1].start() if i + 1 < len(found) else len(log)]
        process = re.search(r"^Process: (P\d+)\s*$", body, re.M)
        number = int(match.group(1))
        process_of[number] = process.group(1) if process else "none"
        cited = sorted(
            {int(n) for n in re.findall(r"\bM(\d{1,3})\b", match.group(3) + body) if int(n) < number}
        )
        entries.append((number, match.group(3).strip(), cited))
    by: dict[str, dict] = {}
    for number, title, cited in entries:
        process = process_of[number]
        row = by.setdefault(
            process, {"process": process, "name": names.get(process, ""), "entries": [], "again": []}
        )
        row["entries"].append(number)
        earlier = [n for n in cited if process_of.get(n) == process]
        if earlier:
            row["again"].append({"entry": number, "title": title, "names": earlier})
    return sorted(by.values(), key=lambda row: (-len(row["again"]), -len(row["entries"]), row["process"]))


# ------------------------------------------------------------------ the command


def print_branches(found: list[dict]) -> None:
    order = sorted(
        found, key=lambda e: (e.get("share_on_main") is None, e.get("share_on_main") or 0, e["branch"])
    )
    for entry in order:
        share = entry.get("share_on_main")
        on_main = "" if share is None else f"{share:.0%} on main"
        own = f"{entry['own_commits']:3} own commits"
        print(f"{entry['branch']:46} {entry['date']}  {own}  {on_main:13} {entry['state']}")
        for lack in entry.get("lacking", []):
            where = "" if lack["file_on_main"] else " (main has no file of this path)"
            print(f"    {lack['path']}: {lack['missing']} of {lack['added']} lines{where}")
            for line in lack["first"][:3]:
                print(f"        | {line[:120]}")
    states = [entry["state"] for entry in found]
    held = sum("are not on main" in state for state in states)
    landed = sum(state.startswith("landed") for state in states)
    beside = sum("nothing of the workcenter" in state for state in states)
    empty = sum(
        state in ("is main", "in main's history") or "nothing of its own" in state for state in states
    )
    print(
        f"{len(found)} branches: {held} hold lines of the workcenter that main lacks, {landed} landed, "
        f"{beside} change nothing of the workcenter itself, {empty} hold nothing of their own"
    )


def print_scripts(found: list[dict]) -> None:
    for entry in found:
        counts = f"{entry['projects']} projects, {entry['files']} files"
        print(f"{entry['script']:28} {counts}: {', '.join(entry['where'])}")
        shared = entry["functions_in_2_or_more"]
        if shared:
            said = ", ".join(f"{name} ({count})" for name, count in list(shared.items())[:12])
            print(f"    functions written in 2 or more projects: {said}{' ...' if len(shared) > 12 else ''}")
    twice = sum(entry["projects"] >= 2 for entry in found)
    print(f"{len(found)} script names; {twice} written by 2 or more projects")


def print_mistakes(found: list[dict]) -> None:
    for row in found:
        again = ", ".join(
            f"M{a['entry']} (after {', '.join(f'M{n}' for n in a['names'][:3])})" for a in row["again"]
        )
        print(
            f"{row['process']:5} {len(row['entries']):3} entries, {len(row['again']):2} again  {row['name']}"
        )
        if again:
            print(f"    {again}")
    entries = sum(len(row["entries"]) for row in found)
    again = sum(len(row["again"]) for row in found)
    print(
        f"{entries} entries under {len(found)} processes; {again} name an earlier entry of their own process"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="harvest", description=__doc__.split("\n\n")[0])
    parser.add_argument("--repo", default=str(ROOT), help="the repository to read (default: this checkout)")
    parser.add_argument("--json", action="store_true", help="print the listing as JSON")
    parts = parser.add_subparsers(dest="listing", required=True)
    p = parts.add_parser("branches", help="every branch, and what it added to the workcenter that main lacks")
    p.add_argument("--main", default="origin/main", help="the ref of main (default origin/main)")
    p.add_argument(
        "--refs", default="refs/remotes/origin", help="where the branches are (default refs/remotes/origin)"
    )
    p = parts.add_parser("scripts", help="the scripts the projects wrote for themselves, by name")
    p.add_argument("--ref", default="HEAD", help="the tree to read (default HEAD)")
    p.add_argument("--root", default="examples", help="the folder that holds the projects (default examples)")
    p = parts.add_parser("mistakes", help="the mistakes log by process, with the mistakes made again")
    p.add_argument("--ref", default="HEAD", help="the tree to read (default HEAD)")
    args = parser.parse_args(argv)
    if args.listing == "branches":
        found, show = branches(args.repo, args.main, args.refs), print_branches
    elif args.listing == "scripts":
        found, show = scripts(args.repo, args.ref, args.root), print_scripts
    else:
        log = git(args.repo, "show", f"{args.ref}:ee-agent-kit/MISTAKES.md")
        steps = git(args.repo, "show", f"{args.ref}:ee-agent-kit/PROCESSES.md")
        found, show = mistakes(log, steps), print_mistakes
    if args.json:
        print(json.dumps(found, indent=1))
    else:
        show(found)
    return 0


if __name__ == "__main__":
    try:
        code = main()
        sys.stdout.flush()
    except BrokenPipeError:
        # `harvest.py mistakes | head -4`: the reader has what it asked for and closed the pipe. Point
        # the stream at nothing, so that Python's own flush at exit has nowhere to fail.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        code = 0
    sys.exit(code)
