"""fail-sim-bias: the board of tests/boards/ratings_node.py with C3 left out, and C2 a 10 uF 10 V part.

The schematic gives the SIM gate each deck part's Value and Footprint, and parts.csv its part number:
C2 is Samsung's CL10A106KP8NNN and L1 Coilcraft's XAL4020-222MEC, whose makers' data the fixture's
library/ holds.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True  # no __pycache__ beside ratings_node.py: a test lists the folders there
import ratings_node  # noqa: E402


def build():
    d = ratings_node.build("bias")
    next(p for p in d.parts if p.ref == "C2").value = "10u 10V"
    return d
