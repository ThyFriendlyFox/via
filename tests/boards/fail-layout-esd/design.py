"""fail-layout-esd: the board of `tests/boards/layout_board.py` that breaks each of the 3 rules of the
pack ti-slva680a-esd once."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import layout_board  # noqa: E402


def build():
    return layout_board.build("esd")
