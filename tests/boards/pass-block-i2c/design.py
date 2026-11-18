"""pass-block-i2c: the I2C block of tests/boards/block_i2c.py at 100 pF in fast mode; it takes 2.2k."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True  # no __pycache__ beside block_i2c.py: a test lists the folders there
import block_i2c  # noqa: E402


def build():
    return block_i2c.build(100e-12)
