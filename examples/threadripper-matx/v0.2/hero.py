"""The README's headline pictures: the board in perspective on a dark ground.

    /opt/workcenters/ee/venv/bin/python hero.py    # from this folder; `workcenter pictures .` runs it

`workcenter render` draws the stills every version keeps; this adds 3 views it does not: a three-quarter
view from the slots' corner, one from the 24-pin's corner and a top view, in the board's own colours
(black mask, white legend, silver pads). KiCad renders each with a transparent background, and Pillow
(in the workcenter's venv) lays it on a dark gradient. The images land in build/hero/.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

HERE = Path(__file__).resolve().parent
OUT = HERE / "build" / "hero"
WIDTH, HEIGHT = 2400, 1500
VIEWS = {
    "hero-iso.png": ["--rotate", "-48,0,-38", "--perspective", "--zoom", "0.92"],
    "hero-right.png": ["--rotate", "-50,0,142", "--perspective", "--zoom", "0.92"],
    "hero-top.png": ["--zoom", "0.95"],
}
TOP, BOTTOM = (34, 37, 44), (10, 11, 14)  # the ground's gradient


def ground(w: int, h: int) -> Image.Image:
    bg = Image.new("RGBA", (w, h))
    for y in range(h):
        t = y / (h - 1)
        bg.paste(tuple(round(TOP[i] + (BOTTOM[i] - TOP[i]) * t) for i in range(3)) + (255,), (0, y, w, y + 1))
    return bg


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    pcb = next(HERE.glob("*.kicad_pcb"))
    for name, extra in VIEWS.items():
        raw = OUT / f"raw-{name}"
        cmd = ["kicad-cli", "pcb", "render", "--output", str(raw), "--width", str(WIDTH), "--height", str(HEIGHT),
               "--quality", "high", "--use-board-stackup-colors", "--background", "transparent",
               "--light-top", "0.55", "--light-camera", "0.35", "--light-side", "0.35", *extra, str(pcb)]
        if not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
            cmd = ["xvfb-run", "-a", *cmd]
        proc = subprocess.run(cmd, cwd=HERE, capture_output=True, text=True, timeout=900, check=False)
        if proc.returncode != 0 or not raw.is_file():
            print(f"hero: {name} failed: {(proc.stderr or proc.stdout).strip().splitlines()[-1:]}", file=sys.stderr)
            return 1
        board = Image.open(raw).convert("RGBA")
        image = ground(*board.size)
        image.alpha_composite(board)
        image.convert("RGB").save(OUT / name)
        raw.unlink()
        print(f"hero: {OUT / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
