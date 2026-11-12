"""Take KiCad's backdrop out of a 3D render, so the board sits on the page's own paper.

    python3 site/showcase/key.py IN OUT [--frame N] [--crop]

KiCad renders a board on a vertical gradient, lavender to grey, and casts the board's shadow on it.
Each row's backdrop colour is read from the picture's left and right edges. A pixel near that
colour, or lavender (blue over red and green, red and green alike: the backdrop, its shadow and a
GIF's dither of both), and joined to the border through pixels like it, is backdrop. It becomes
clear, or, where it is darker than its row, a neutral shadow as dark. No board colour is lavender:
green, black, white, grey, gold. A hole in the board keeps its backdrop: only what the border
reaches is taken out. --frame N takes frame N of an animated GIF; --crop trims the clear margin.
Needs numpy and Pillow, both in the workcenter's venv.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

NEAR = 14.0  # a channel this close to the row's backdrop is backdrop, if the border reaches it
LAVENDER = 7.0  # blue this far over red and green, with red and green within RG of each other
RG = 12.0
SHADOW = 0.65  # the darkest a shadow gets, as an opacity


def grow(mask: np.ndarray) -> np.ndarray:
    """The mask and its 4 neighbours of each pixel."""
    out = mask.copy()
    out[1:, :] |= mask[:-1, :]
    out[:-1, :] |= mask[1:, :]
    out[:, 1:] |= mask[:, :-1]
    out[:, :-1] |= mask[:, 1:]
    return out


def key(picture: Image.Image) -> Image.Image:
    rgb = np.asarray(picture.convert("RGB"), dtype=np.float32)
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    edges = np.concatenate([rgb[:, :4], rgb[:, -4:]], axis=1)
    backdrop = np.median(edges, axis=1)[:, None, :]  # 1 colour per row
    near = np.abs(rgb - backdrop).max(axis=2) < NEAR
    lavender = (b - np.maximum(r, g) >= LAVENDER) & (np.abs(r - g) < RG)
    like = near | lavender

    # Flood from the border through pixels like the backdrop.
    clear = np.zeros_like(like)
    clear[0, :], clear[-1, :], clear[:, 0], clear[:, -1] = like[0, :], like[-1, :], like[:, 0], like[:, -1]
    while True:
        grown = grow(clear) & like
        if (grown == clear).all():
            break
        clear = grown

    # Backdrop as bright as its row is clear; darker, it is the board's shadow, in grey.
    weights = np.array([0.3, 0.59, 0.11], dtype=np.float32)
    luma = rgb @ weights
    row = backdrop @ weights  # 1 brightness per row, as a column
    shade = np.clip((row - luma) / np.maximum(row, 1.0) * 1.3, 0.0, SHADOW)
    alpha = np.where(clear, shade, 1.0).astype(np.float32)
    colour = np.where(clear[..., None], 0.0, rgb)
    out = np.concatenate([colour, alpha[..., None] * 255], axis=2)
    return Image.fromarray(out.round().astype(np.uint8), "RGBA")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("source", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--frame", type=int, default=0, help="the frame of an animated GIF to take")
    parser.add_argument("--crop", action="store_true", help="trim the clear margin round the board")
    args = parser.parse_args()
    picture = Image.open(args.source)
    picture.seek(args.frame)
    keyed = key(picture)
    if args.crop:
        box = keyed.getchannel("A").getbbox()
        if box:
            keyed = keyed.crop(box)
    keyed.save(args.out, optimize=True)
    print(f"{args.out}: {keyed.width} x {keyed.height}, backdrop taken out")
    return 0


if __name__ == "__main__":
    sys.exit(main())
