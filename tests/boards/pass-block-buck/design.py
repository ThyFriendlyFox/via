"""pass-block-buck: the buck block of tests/boards/block_buck.py into 0.5 A; it takes SRN2010TA-2R2M."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True  # no __pycache__ beside block_buck.py: a test lists the folders there
import block_buck  # noqa: E402


def build():
    return block_buck.build(0.5)
