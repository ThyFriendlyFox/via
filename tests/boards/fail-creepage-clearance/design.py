"""fail-creepage-clearance: the board of `tests/boards/creepage_board.py` with 1.3 mm between HV and GND,
where MIL-HDBK-454C table 69-I asks 1.5 mm of clearance and 3 mm of leakage distance at 400 V
(condition A, enclosure I). It breaks both rules of the pack."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import creepage_board  # noqa: E402


def build():
    return creepage_board.build("clear")
