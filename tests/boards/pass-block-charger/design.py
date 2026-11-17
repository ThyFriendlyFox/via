"""pass-block-charger: the charger block of tests/boards/block_charger.py at 0.15 A; RISET is 3.6k."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True  # no __pycache__ beside block_charger.py: a test lists the folders there
import block_charger  # noqa: E402


def build():
    return block_charger.build(0.15)
