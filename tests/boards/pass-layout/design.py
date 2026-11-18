"""pass-layout: the board of `tests/boards/layout_board.py` that holds every rule of the 2 layout packs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import layout_board  # noqa: E402


def build():
    return layout_board.build("pass")
