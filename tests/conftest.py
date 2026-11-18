"""The `engine` marker and its guard, for every test of this folder (tools/ci/engine_marker.py).

A test file takes `engine` from here (`from conftest import engine`): a design file a test writes
imports its test file in a child process, where only this folder is on sys.path.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "ci"))

from engine_marker import (  # noqa: E402, F401
    engine,
    pytest_configure,
    pytest_runtest_call,
    pytest_runtest_setup,
    pytest_runtest_teardown,
    pytest_unconfigure,
)
