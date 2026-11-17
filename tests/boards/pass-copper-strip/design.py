"""pass-copper-strip: the board of tests/boards/copper_strip.py, its supply track 1.5 mm all the way."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True  # no __pycache__ beside copper_strip.py: a test lists the folders there
import copper_strip  # noqa: E402


def build():
    return copper_strip.build(neck=False)
