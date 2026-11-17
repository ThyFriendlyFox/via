"""fail-ratings-inductor: the board of tests/boards/ratings_node.py; L1 saturates at 1.26 A."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True  # no __pycache__ beside ratings_node.py: a test lists the folders there
import ratings_node  # noqa: E402


def build():
    return ratings_node.build("inductor")
