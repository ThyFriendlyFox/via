"""fail-block-usbc-2x: the USB-C block of tests/boards/block_usbc.py into 3.0 A, twice the load of
pass-block-usbc. The design detects up to 1.5 A, and the block refuses 3.0 A with table 4-20 of the USB
Type-C specification: `workcenter design` writes nothing."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True  # no __pycache__ beside block_usbc.py: a test lists the folders there
import block_usbc  # noqa: E402


def build():
    return block_usbc.build(3.0)
