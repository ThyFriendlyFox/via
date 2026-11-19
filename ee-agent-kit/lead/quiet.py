#!/usr/bin/env python3
"""Print each process that is a helper's engine, test run or working script; nothing means quiet.

usage: quiet.py <pid whose tree is left out> [folder]...

Busy is: an engine (ENGINES), a test run or a workcenter run (RUNNERS: the script `pytest`, `py.test`
or `workcenter`, as ps names it or as a python runs it, or `python -m pytest`), and any process whose
command line names 1 of the folders, except a script that only waits: a shell script whose processes
below it are shells and a `sleep`, a Python script with nothing below it that sleeps and used no
processor time for IDLE_S seconds (`time.sleep` starts no `sleep` process, M277), and `bash -c` lines.
The process tree under the given pid (the gate itself) is left out, as are the
process names in the environment variable QUIET_IGNORE (',' between them): the lead's own host, whose
command line may name the scratch folder. Standard library and `ps` only.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

USAGE = "usage: quiet.py <pid whose tree is left out> [folder]..."
ENGINES = (
    "kicad-cli",
    "ngspice",
    "java",
    "ffmpeg",
    "rsvg-convert",
    "chrome",
    "chromium",
    "headless_shell",
    "Xvfb",
)
SHELLS = ("bash", "sh", "sleep")
# A test run or a workcenter run, by the name of the script that starts it: ps gives an entry-point
# script's own name as the command (`pytest`, `workcenter`), and a python that runs it names it.
RUNNERS = ("pytest", "py.test", "workcenter")
# How long a Python script with nothing below it must sleep with no processor time to count as waiting.
IDLE_S = 2.0


def runs_tests(comm: str, args: str) -> bool:
    if comm in RUNNERS:
        return True
    if not comm.startswith("python"):
        return False
    words = args.split()
    return (
        "pytest" in args or "tools/workcenter" in args or any(w.rsplit("/", 1)[-1] in RUNNERS for w in words)
    )


def processor_time(pid: int) -> tuple[str, int] | None:
    """The state letter and the ticks of processor time (user and system) in /proc/<pid>/stat."""
    try:
        with open(f"/proc/{pid}/stat", encoding="ascii", errors="replace") as stat:
            fields = stat.read().rsplit(")", 1)[1].split()
        return fields[0], int(fields[11]) + int(fields[12])
    except (OSError, IndexError, ValueError):
        return None


def still_working(candidates: list[tuple[int, str, str]]) -> list[tuple[int, str, str]]:
    """The candidates that are not asleep with the same processor time before and after IDLE_S."""
    first = {pid: processor_time(pid) for pid, _, _ in candidates}
    if any(seen is not None and seen[0] == "S" for seen in first.values()):
        time.sleep(IDLE_S)
    working = []
    for pid, comm, args in candidates:
        before = first[pid]
        if before is None or before[0] != "S" or processor_time(pid) != before:
            working.append((pid, comm, args))
    return working


def processes() -> dict[int, tuple[int, str, str]]:
    # -ww: unlimited width. Without it `ps` cuts each line to COLUMNS (or a terminal's width), and a
    # folder at the end of a long command line is lost with the rest of it (M281).
    listing = subprocess.run(
        ["ps", "-ww", "-eo", "pid=,ppid=,comm=,args="], capture_output=True, text=True, check=True
    ).stdout
    procs = {}
    for line in listing.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3 or not parts[0].isdigit() or not parts[1].isdigit():
            continue
        procs[int(parts[0])] = (int(parts[1]), parts[2], parts[3] if len(parts) > 3 else "")
    return procs


def busy(root: int, folders: list[str], ignore: set[str]) -> list[tuple[int, str, str]]:
    procs = processes()
    children: dict[int, list[int]] = {}
    for pid, (ppid, _, _) in procs.items():
        children.setdefault(ppid, []).append(pid)

    def under(pid: int) -> bool:
        seen = set()
        while pid in procs and pid not in seen:
            if pid == root:
                return True
            seen.add(pid)
            pid = procs[pid][0]
        return False

    def only_sleeps(pid: int) -> bool:
        below, stack = [], list(children.get(pid, []))
        while stack:
            child = stack.pop()
            below.append(child)
            stack.extend(children.get(child, []))
        return (
            bool(below)
            and all(procs[p][1] in SHELLS for p in below)
            and any(procs[p][1] == "sleep" for p in below)
        )

    found, sleepers = [], []
    for pid, (_, comm, args) in sorted(procs.items()):
        if pid == os.getpid() or under(pid) or comm == "ps" or comm in ignore:
            continue
        words = args.split()
        in_folder = any(folder and folder in args for folder in folders)
        if comm.startswith(ENGINES):
            found.append((pid, comm, args))
        elif runs_tests(comm, args):
            found.append((pid, comm, args))
        elif in_folder and comm.startswith("python") and not children.get(pid):
            sleepers.append((pid, comm, args))
        elif in_folder and comm not in SHELLS:
            found.append((pid, comm, args))
        elif (
            in_folder
            and comm in ("bash", "sh")
            and len(words) > 1
            and words[1] != "-c"
            and not only_sleeps(pid)
        ):
            found.append((pid, comm, args))
    return sorted(found + still_working(sleepers))


def main(argv: list[str]) -> int:
    if not argv or not argv[0].isdigit():
        print(USAGE, file=sys.stderr)
        return 2
    ignore = {name for name in os.environ.get("QUIET_IGNORE", "").split(",") if name}
    for pid, comm, args in busy(int(argv[0]), argv[1:], ignore):
        print(pid, comm, args[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
