"""pass-block-usbc: the USB-C block of tests/boards/block_usbc.py into 1.5 A, which the 1.5 A advertisement
allows."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True  # no __pycache__ beside block_usbc.py: a test lists the folders there
import block_usbc  # noqa: E402


def build():
    return block_usbc.build(1.5)
