"""pass-block-ldo: the linear regulator block of tests/boards/block_ldo.py into 0.1 A; it takes
TLV75533PDBVR."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True  # no __pycache__ beside block_ldo.py: a test lists the folders there
import block_ldo  # noqa: E402


def build():
    return block_ldo.build(0.1)
