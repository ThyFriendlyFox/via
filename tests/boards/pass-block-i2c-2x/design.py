"""pass-block-i2c-2x: the I2C block of tests/boards/block_i2c.py at 200 pF, twice the bus capacitance of
pass-block-i2c; 2.2k is over RP(max) at its tolerance, and the block takes 1.5k."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True  # no __pycache__ beside block_i2c.py: a test lists the folders there
import block_i2c  # noqa: E402


def build():
    return block_i2c.build(200e-12)
