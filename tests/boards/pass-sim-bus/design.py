"""pass-sim-bus: the board of tests/boards/sim_bus.py; its 2 decks answer the I2C bus and the regulator."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True  # no __pycache__ beside sim_bus.py: a test lists the folders there
import sim_bus  # noqa: E402


def build():
    return sim_bus.build()
