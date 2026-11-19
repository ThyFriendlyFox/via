#!/usr/bin/env python3
"""Copy the logs of a red gate's kept folder into 1 folder for an artifact, bounded in size.

    python3 tools/ci/kept_logs.py <into> <folder pattern>...

ci.yml runs it after a gate step that failed, then uploads <into>. On 2026-11-19, 13 routing tests failed
on GitHub and the gate printed `see /tmp/ee-verify-.../freerouting.log`: the file was gone with the
runner, and the run had 0 artifacts. verify/testshards.py keeps its folder on a red run (`logs kept:
<folder>`, a `mkdtemp` named ee-verify-* in $TMPDIR, else /tmp); the fast gate's pytest keeps its own
under pytest-of-<user>.

From each folder a pattern names, it copies the files whose names end in .log, .jsonl, .txt or .rpt
(the shards' logs, a router's log, a DRC report), not the boards and pictures of the tests' folders (1
whole run's folders took 607 MB). A file over PER_FILE bytes keeps its last PER_FILE, after 1 line that
says how much is left out: pytest writes its failures last. The copies stop at TOTAL bytes; the folders'
top files go first, and what does not fit is named in <into>/KEPT.txt. A link is not followed. It never
fails the job it serves: with nothing to keep it says so and ends with 0.
"""

from __future__ import annotations

import glob
import os
import sys
from pathlib import Path

SUFFIXES = (".log", ".jsonl", ".txt", ".rpt")
PER_FILE = 2_000_000
TOTAL = 50_000_000
USAGE = "usage: kept_logs.py <into> <folder pattern>..."


def files_of(folder: Path) -> list[Path]:
    """The log files under `folder`, links not followed, the top ones first, then by path."""
    found = []
    for top, _dirs, names in os.walk(folder, followlinks=False):
        for name in names:
            path = Path(top) / name
            if name.endswith(SUFFIXES) and path.is_file() and not path.is_symlink():
                found.append(path)
    return sorted(found, key=lambda p: (len(p.relative_to(folder).parts), p.as_posix()))


def copy(source: Path, target: Path) -> int:
    """Copy `source`, its last PER_FILE bytes when it is longer; return the bytes written."""
    size = source.stat().st_size
    target.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as read, target.open("wb") as write:
        if size > PER_FILE:
            read.seek(size - PER_FILE)
            write.write(
                f"[kept_logs.py: the first {size - PER_FILE} bytes of {size} are left out]\n".encode()
            )
        data = read.read(PER_FILE)
        write.write(data)
    return target.stat().st_size


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(USAGE, file=sys.stderr)
        return 2
    into, patterns = Path(argv[0]), argv[1:]
    into.mkdir(parents=True, exist_ok=True)
    folders = [Path(p) for pattern in patterns for p in sorted(glob.glob(pattern)) if Path(p).is_dir()]
    listing, total, count, left = [], 0, 0, 0
    for folder in folders:
        for path in files_of(folder):
            name = (Path(folder.name) / path.relative_to(folder)).as_posix()
            size = path.stat().st_size
            need = min(size, PER_FILE) + (100 if size > PER_FILE else 0)
            if total + need > TOTAL:
                listing.append(f"left out {name}: {size} bytes; the artifact's {TOTAL} are full")
                left += 1
                continue
            wrote = copy(path, into / name)
            total += wrote
            count += 1
            listing.append(f"kept {name}: {wrote} bytes of {size}")
    if not folders:
        said = f"kept_logs: no folder matches {' '.join(patterns)}: nothing to keep"
        listing.append(said)
    else:
        said = f"kept_logs: {count} files, {total} bytes, into {into} from {', '.join(map(str, folders))}"
        if left:
            said += f"; {left} left out (KEPT.txt names them)"
    (into / "KEPT.txt").write_text("\n".join(listing) + "\n", encoding="utf-8")
    print(said)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
