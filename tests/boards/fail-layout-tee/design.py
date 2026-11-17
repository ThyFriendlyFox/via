"""fail-layout-tee: the board of `tests/boards/layout_board.py` whose VBUS branches at the connector, to C1
nearer than to its TVS D1: it breaks the rule `nearest` of the pack ti-slva680a-esd once."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import layout_board  # noqa: E402


def build():
    return layout_board.build("tee")
