"""fail-highspeed-skew: the board of tests/boards/highspeed_pair.py; USB_D_N is 2 mm longer."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True  # no __pycache__ beside highspeed_pair.py: a test lists the folders there
import highspeed_pair  # noqa: E402


def build():
    return highspeed_pair.build("skew")
