"""pass-legend-dense: the board of tests/boards/legend_dense.py, its designators placed by the placer."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.dont_write_bytecode = True  # no __pycache__ beside legend_dense.py: a test lists the folders there
import legend_dense  # noqa: E402


def build():
    return legend_dense.build(place=True)
