"""The day and the time a command runs at: read once, at its start, through 1 function.

`tools/workcenter` and `tools/now.py` enter `run()` before they do anything else, and every day or time
the command writes, prints or compares in that run is `moment()` or `today()`: a run that crosses
midnight writes the day it started on, in every file. Outside a run each call reads the clock.

SOURCE_DATE_EPOCH pins the reading, as reproducible builds do (SOURCE_DATE_EPOCH specification,
revision 1.1 of 2017-11-27, section SOURCE_DATE_EPOCH: "Build processes MUST use this variable for
embedded timestamps in place of the current date and time"). Its value is an integer of seconds since
1970-01-01 00:00:00 UTC with no fractional part, as `date +%s` prints it; the pinned day is that
moment's day in UTC. A malformed value ends the command with exit code 1 and 1 line, as the same
section asks ("SHOULD exit with a non-zero error code"). Unpinned, the day is the machine's local day,
as it was before this module.

`clock_calls` names the lines of a Python file that read the clock: tests/test_clock.py holds every
other tool to calling none, and tests/test_docs.py holds every test file to calling none at load.

Standard library only, as the CLI is (AGENTS.md invariant 3).
"""

from __future__ import annotations

import ast
import contextlib
import datetime
import os
import re

ENV = "SOURCE_DATE_EPOCH"
SOURCE = "SOURCE_DATE_EPOCH specification, revision 1.1, section SOURCE_DATE_EPOCH"
INTEGER = re.compile(r"-?[0-9]+", re.ASCII)

_held: datetime.datetime | None = None


class Malformed(ValueError):
    """SOURCE_DATE_EPOCH holds no integer of seconds a date can be made of."""


def _wall() -> datetime.datetime:
    """The machine's clock, as an aware moment in its local zone: the 1 place a tool reads it."""
    return datetime.datetime.now().astimezone()


def _read() -> datetime.datetime:
    value = os.environ.get(ENV)
    if value is None:
        return _wall()
    try:
        if not INTEGER.fullmatch(value):
            raise ValueError
        return datetime.datetime.fromtimestamp(int(value), datetime.UTC)
    except (ValueError, OverflowError, OSError):
        raise Malformed(
            f"{ENV} is {value!r}, not a whole number of seconds since 1970-01-01 00:00:00 UTC ({SOURCE})"
        ) from None


@contextlib.contextmanager
def run():
    """Hold 1 reading for the command inside; the reading before it comes back at the end."""
    global _held
    before = _held
    try:
        _held = _read()
    except Malformed as why:
        raise SystemExit(str(why)) from None
    try:
        yield _held
    finally:
        _held = before


def moment() -> datetime.datetime:
    """The command's moment, an aware datetime: the run's reading, else the clock now."""
    return _held if _held is not None else _read()


def today() -> datetime.date:
    """The command's day: UTC when pinned, the machine's local day when not."""
    return moment().date()


# ------------------------------------------------------------ who reads the clock

# (owner, name) of a call that reads the wall clock. time.monotonic and time.perf_counter measure a
# duration and land in no file as a day or a time of day.
READERS = {
    ("date", "today"),
    ("datetime", "now"),
    ("datetime", "utcnow"),
    ("datetime", "today"),
    ("time", "time"),
    ("time", "time_ns"),
    ("time", "localtime"),
    ("time", "gmtime"),
    ("time", "strftime"),
    ("time", "ctime"),
    ("time", "asctime"),
}
# This module's own readers: the way a tool reads the clock, and still a reading when a file is loaded.
OWN = {("clock", "moment"), ("clock", "today")}


def clock_calls(source: str, at_load: bool = False) -> list[int]:
    """The lines of `source` that read the clock other than through this module. With `at_load`, the
    calls that run when the file is imported, this module's own readers among them: a module's
    statements, class bodies, decorators and default values, not the bodies of functions."""
    readers = READERS | OWN if at_load else READERS
    tree = ast.parse(source)
    bare = {}  # a name bound by `from time import time as now`, and the like: now -> ("time", "time")
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in ("time", "datetime"):
            for alias in node.names:
                for owner, name in READERS:
                    if owner == node.module and name == alias.name:
                        bare[alias.asname or alias.name] = (owner, name)
    found: list[int] = []

    def reads(call: ast.Call) -> bool:
        func = call.func
        if isinstance(func, ast.Name):
            return func.id in bare
        if not isinstance(func, ast.Attribute):
            return False
        owner = func.value
        name = owner.attr if isinstance(owner, ast.Attribute) else getattr(owner, "id", None)
        return (name, func.attr) in readers

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Call) and reads(node):
            found.append(node.lineno)
        if at_load and isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            args = node.args
            loaded = [*args.defaults, *(d for d in args.kw_defaults if d is not None)]
            if not isinstance(node, ast.Lambda):
                loaded += node.decorator_list
            for child in loaded:
                visit(child)
            return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return sorted(set(found))
