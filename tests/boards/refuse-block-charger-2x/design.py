"""refuse-block-charger-2x: the charger block of tests/boards/block_charger.py at 0.3 A, twice the current of
pass-block-charger. The block takes 1.8k for RISET, works out the charger's junction by its equation 8 and
refuses it: `workcenter design` writes nothing and prints the line."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True  # no __pycache__ beside block_charger.py: a test lists the folders there
import block_charger  # noqa: E402


def build():
    return block_charger.build(0.3)
