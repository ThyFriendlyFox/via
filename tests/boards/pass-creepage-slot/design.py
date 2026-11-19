"""pass-creepage-slot: the board of `tests/boards/creepage_board.py` with 3.3 mm between HV and GND and a
slot 1 mm wide between them, which makes the way along the face 5.022 mm."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import creepage_board  # noqa: E402


def build():
    return creepage_board.build("slot")
