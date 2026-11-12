"""Fetch the KiCad 3D library bodies a board names into a folder, for `workcenter render`.

    python3 models/fetch_library_bodies.py basalt.kicad_pcb ~/kicad-bodies
    export KICAD10_3DMODEL_DIR=~/kicad-bodies

KiCad's 3D package (kicad-packages3d) is 3.3 GB installed; a board names a few dozen of its files.
Each file named as ${KICAD10_3DMODEL_DIR}/... is fetched from the library's repository unless it is
already there. The project's own bodies (${KIPRJMOD}/models/) are drawn by make_models.py.
"""

from __future__ import annotations

import re
import sys
import urllib.request
from pathlib import Path

BASE = "https://gitlab.com/kicad/libraries/kicad-packages3D/-/raw/master/"


def main(board: str, out: str) -> int:
    paths = sorted(set(re.findall(r'\(model "\$\{KICAD10_3DMODEL_DIR\}/([^"]+)"', Path(board).read_text(encoding="utf-8"))))
    root = Path(out).expanduser()
    fetched, missing = 0, []
    for rel in paths:
        dest = root / rel
        if dest.is_file() and dest.stat().st_size:
            continue
        try:
            with urllib.request.urlopen(BASE + rel, timeout=60) as resp:
                data = resp.read()
        except urllib.error.HTTPError as exc:
            missing.append(f"{rel} ({exc.code})")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        fetched += 1
    print(f"{len(paths)} bodies named, {fetched} fetched into {root}")
    for m in missing:
        print(f"  not in the library: {m}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
