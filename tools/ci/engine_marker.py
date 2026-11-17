"""engine_marker — the pytest plugin that holds the `engine` marker. tests/conftest.py loads it.

A test that starts kicad-cli, ngspice, FreeRouting, openEMS, a chip engine or KiCad's Python module
carries `@pytest.mark.engine`. The fast run (`make verify-site`) runs `-m "not engine"` with
WORKCENTER_NO_ENGINES=1. In every run this plugin puts `guard/` first on PYTHONPATH, so each Python
process a test starts writes its engine starts to 1 log (guard/engine_watch.py), and it fails a test
without the marker that wrote a line, in its setup or in its call.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parent / "guard"
sys.path.insert(0, str(GUARD))

import engine_watch  # noqa: E402

_made: list[str] = []


class Marks(tuple):
    """Marks that decorate a test together, and that `pytest.param(..., marks=)` takes as they are."""

    def __call__(self, test):
        for mark in self:
            test = mark(test)
        return test


def engine(*marks) -> Marks:
    """The `engine` marker with a test file's own marks: `needs_x = engine(pytest.mark.skipif(...))`."""
    return Marks((pytest.mark.engine, *marks))


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "engine: the test starts kicad-cli, ngspice, FreeRouting, openEMS, a chip engine or pcbnew; "
        "the fast run (make verify-site) leaves it out",
    )
    if not os.environ.get(engine_watch.LOG_VAR):
        handle, log = tempfile.mkstemp(prefix="engine-starts-", suffix=".log")
        os.close(handle)
        os.environ[engine_watch.LOG_VAR] = log
        _made.append(log)
    paths = [p for p in os.environ.get("PYTHONPATH", "").split(os.pathsep) if p]
    if str(GUARD) not in paths:
        os.environ["PYTHONPATH"] = os.pathsep.join([str(GUARD), *paths])
    engine_watch.install()


def pytest_unconfigure(config):
    for log in _made:
        Path(log).unlink(missing_ok=True)


def _size() -> int:
    log = Path(os.environ.get(engine_watch.LOG_VAR, ""))
    return log.stat().st_size if log.is_file() else 0


def _hold(item, start: int) -> None:
    """Fail a test without the marker that started an engine since `start`."""
    if item.get_closest_marker("engine") or _size() <= start:
        return
    with open(os.environ[engine_watch.LOG_VAR], encoding="utf-8") as log:
        log.seek(start)
        started = [line.split("\t")[0] for line in log.read().splitlines() if line]
    names = ", ".join(dict.fromkeys(started))
    pytest.fail(
        f"{item.nodeid} started {names} and has no engine marker (tools/ci/engine_marker.py)", pytrace=False
    )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_setup(item):
    start = _size()
    try:
        return (yield)
    finally:
        _hold(item, start)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    start = _size()
    try:
        return (yield)
    finally:
        _hold(item, start)
