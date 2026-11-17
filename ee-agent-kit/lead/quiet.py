#!/usr/bin/env python3
"""Print each process that is a helper's engine, test run or working script; nothing means quiet.

usage: quiet.py <pid whose tree is left out> [folder]...

Busy is: an engine (ENGINES), a Python that runs pytest or tools/workcenter, and any process whose
command line names 1 of the folders, except a shell script that only sleeps (it waits for the lock)
and `bash -c` lines. The process tree under the given pid (the gate itself) is left out, as are the
process names in the environment variable QUIET_IGNORE (',' between them): the lead's own host, whose
command line may name the scratch folder. Standard library and `ps` only.
"""

from __future__ import annotations

import os
import subprocess
import sys

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


def processes() -> dict[int, tuple[int, str, str]]:
    listing = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,comm=,args="], capture_output=True, text=True, check=True
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

    found = []
    for pid, (_, comm, args) in sorted(procs.items()):
        if pid == os.getpid() or under(pid) or comm == "ps" or comm in ignore:
            continue
        words = args.split()
        in_folder = any(folder and folder in args for folder in folders)
        if comm.startswith(ENGINES):
            found.append((pid, comm, args))
        elif comm.startswith("python") and ("pytest" in args or "tools/workcenter" in args):
            found.append((pid, comm, args))
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
    return found


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
