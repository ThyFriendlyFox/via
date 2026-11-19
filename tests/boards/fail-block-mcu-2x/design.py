"""fail-block-mcu-2x: the mcu block with 1 crystal of twice ABS25's ESR; refused by equation 5."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True  # no __pycache__ beside block_mcu.py: a test lists the folders there
import block_mcu  # noqa: E402


def build():
    return block_mcu.build([block_mcu.TWICE])
