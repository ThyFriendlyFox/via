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
as it was before this module. The pin is for what a command writes. A judgement of age against now (a
price's `Checked` day in `procure` and `costs`) and the day a check is recorded (`fetch`'s `Checked`)
read `wall_today()`, the same run's reading of the machine's clock, pinned or not: a value set as the
specification asks is a past day, and a 2-year-old price judged against it would pass as fresh.

`clock_calls` names the lines of a Python file that read the clock: tests/test_clock.py holds every
other tool to calling none, and tests/test_docs.py holds every test file to calling none at load. It
resolves a module or class imported under another name and a reader bound to a name, counts the
shell's `date` run through a call, and, at load, follows a call into a function of the same file. It
does not follow a call into another module, or into a method of a class.

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
_held_wall: datetime.datetime | None = None


class Malformed(ValueError):
    """SOURCE_DATE_EPOCH holds no integer of seconds a date can be made of."""


def _wall() -> datetime.datetime:
    """The machine's clock, as an aware moment in its local zone: the 1 place a tool reads it."""
    return datetime.datetime.now().astimezone()


def _pinned() -> datetime.datetime | None:
    """SOURCE_DATE_EPOCH's moment in UTC, or None when it is unset."""
    value = os.environ.get(ENV)
    if value is None:
        return None
    if not INTEGER.fullmatch(value):
        raise Malformed(
            f"{ENV} is {value!r}, not a whole number of seconds since 1970-01-01 00:00:00 UTC ({SOURCE})"
        )
    try:
        return datetime.datetime.fromtimestamp(int(value), datetime.UTC)
    except (ValueError, OverflowError, OSError):
        raise Malformed(
            f"{ENV} is {value!r}, a moment outside the years {datetime.MINYEAR} to {datetime.MAXYEAR} a "
            "date holds (Python datetime.MINYEAR, datetime.MAXYEAR)"
        ) from None


@contextlib.contextmanager
def run():
    """Hold 1 reading for the command inside; the reading before it comes back at the end."""
    global _held, _held_wall
    before = _held, _held_wall
    try:
        pinned = _pinned()
    except Malformed as why:
        raise SystemExit(str(why)) from None
    _held_wall = _wall()
    _held = pinned or _held_wall
    try:
        yield _held
    finally:
        _held, _held_wall = before


def moment() -> datetime.datetime:
    """The command's moment, an aware datetime: the run's reading, else the clock now. SOURCE_DATE_EPOCH
    pins it: it is the time a command writes into a file."""
    if _held is not None:
        return _held
    return _pinned() or _wall()


def today() -> datetime.date:
    """The command's day: UTC when pinned, the machine's local day when not."""
    return moment().date()


def wall_today() -> datetime.date:
    """The machine's local day at the run's start, whatever SOURCE_DATE_EPOCH says: the day a judgement
    of age is made on and a check is recorded on. The specification asks the variable for "embedded
    timestamps" (section SOURCE_DATE_EPOCH), and its value is in the past: a price judged against it
    would pass as fresh."""
    return (_held_wall if _held_wall is not None else _wall()).date()


def wall_utc_today() -> datetime.date:
    """The day in UTC of the same reading as `wall_today()`: the day a date written in any zone is
    judged against, whatever the machine's own zone is."""
    return (_held_wall if _held_wall is not None else _wall()).astimezone(datetime.UTC).date()


def stamp() -> float:
    """The machine's clock now, in seconds since 1970-01-01 00:00:00 UTC, read at each call, whatever
    SOURCE_DATE_EPOCH says and inside a run too: a time that other processes read and compare, as the
    engine lock's tickets are. A pinned or held reading would make a wait of minutes take none."""
    return _wall().timestamp()


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
OWN = {
    ("clock", "moment"),
    ("clock", "today"),
    ("clock", "wall_today"),
    ("clock", "wall_utc_today"),
    ("clock", "stamp"),
}


# The shell's clock, run through subprocess or os: `date`, or a path that ends in it, as a command's 1st word.
SHELL = re.compile(r"(\S*/)?date(\s|$)")
RUNNERS = {"run", "call", "check_call", "check_output", "Popen", "system", "popen", "getoutput"}


def clock_calls(source: str, at_load: bool = False) -> list[int]:
    """The lines of `source` that read the clock other than through this module. With `at_load`, the
    calls that run when the file is imported, this module's own readers among them: a module's
    statements, class bodies, decorators and default values, not the bodies of functions, and a call
    there into a function of the same file that reads the clock, however deep."""
    readers = READERS | OWN if at_load else READERS
    owners = {owner for owner, _ in readers}
    tree = ast.parse(source)
    # What a name stands for: a module or a class by its own name (`import time as t`: t -> "time"), or
    # a reader (`from time import time as now`, `now = datetime.datetime.now`: now -> ("time", "time")).
    names: dict[str, str | tuple[str, str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in owners:
                    names[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module in owners:
            for alias in node.names:
                if (node.module, alias.name) in readers:
                    names[alias.asname or alias.name] = (node.module, alias.name)
                elif node.module == "datetime" and alias.name in owners:
                    names[alias.asname or alias.name] = alias.name

    def owner_of(node: ast.expr) -> str | None:
        if isinstance(node, ast.Attribute):
            return node.attr
        if isinstance(node, ast.Name):
            meant = names.get(node.id, node.id)
            return meant if isinstance(meant, str) else None
        return None

    def reader(node: ast.expr) -> bool:
        if isinstance(node, ast.Name):
            return isinstance(names.get(node.id), tuple)
        return isinstance(node, ast.Attribute) and (owner_of(node.value), node.attr) in readers

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and reader(node.value):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names[target.id] = ("bound", target.id)

    def shell(call: ast.Call) -> bool:
        name = call.func.attr if isinstance(call.func, ast.Attribute) else getattr(call.func, "id", "")
        if name not in RUNNERS or not call.args:
            return False
        first = call.args[0]
        if isinstance(first, (ast.List, ast.Tuple)) and first.elts:
            first = first.elts[0]
        return (
            isinstance(first, ast.Constant)
            and isinstance(first.value, str)
            and bool(SHELL.match(first.value))
        )

    def reads(call: ast.Call) -> bool:
        return reader(call.func) or shell(call)

    # At load, a call into a function of this file reads the clock when its body does, or calls one that
    # does: the set grows until it holds still.
    functions = {
        node.name: node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    reading: set[str] = set()
    while at_load:
        more = {
            name
            for name, node in functions.items()
            if name not in reading
            and any(
                isinstance(sub, ast.Call)
                and (reads(sub) or (isinstance(sub.func, ast.Name) and sub.func.id in reading))
                for sub in ast.walk(node)
            )
        }
        if not more:
            break
        reading |= more
    found: list[int] = []

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Call) and (
            reads(node) or (isinstance(node.func, ast.Name) and node.func.id in reading)
        ):
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
