"""pass-creepage: the board of `tests/boards/creepage_board.py` with 3.3 mm between HV and GND."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import creepage_board  # noqa: E402


def build():
    return creepage_board.build("pass")
