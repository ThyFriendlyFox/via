"""fail-layout-emi: the board of `tests/boards/layout_board.py` that breaks the rule of the pack
ti-szza009-emi once."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import layout_board  # noqa: E402


def build():
    return layout_board.build("emi")
