"""fail-creepage-slot: the board of `tests/boards/creepage_board.py` with 3.3 mm between HV and GND and a
slot 0.8 mm wide between them. SLUP419 table 7 counts a slot from 1.0 mm at pollution degree 2, so the
way crosses it: 3.3 mm, under the 4.0 mm of table 3 at 400 V. It breaks both rules of the pack."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import creepage_board  # noqa: E402


def build():
    return creepage_board.build("narrow")
