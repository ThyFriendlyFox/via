"""The `engine` marker and its guard, for every test of this folder (tools/ci/engine_marker.py), and
the session's notice file of the engine lock.

A test file takes `engine` from here (`from conftest import engine`): a design file a test writes
imports its test file in a child process, where only this folder is on sys.path.

The engine lock is shared by every run on the machine, test sessions too (tools/enginelock.py): a
session's long commands wait while another session's run holds it. A waiting run prints 2 lines, and
a test that compares the whole of stderr would fail on them. So the session names 1 file for those
lines (`WORKCENTER_LOCK_LOG`), once, before any test, and every process a test starts inherits it. The
summary prints what the file holds; the lock's own tests take the variable out and read stderr.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "ci"))

import engine_marker  # noqa: E402
from engine_marker import (  # noqa: E402, F401
    engine,
    pytest_runtest_call,
    pytest_runtest_setup,
    pytest_runtest_teardown,
)

LOCK_LOG = "WORKCENTER_LOCK_LOG"
_made: list[str] = []


def router_absent() -> str:
    """Why Via's default router cannot run here, "" when it can: the router's own absent(), which rests
    on the java the product picks (routers.workcenter_java). A routing test skips on this, never on
    the first java on PATH: in CI run 44515796762 a java stood on PATH, so 13 tests ran, and the product
    ran another java, which could not draw FreeRouting's window."""
    tools = str(Path(__file__).resolve().parents[1] / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import routers

    return routers.get(routers.DEFAULT).absent()


# A process that knows no home folder: HOME unset, and a user id with no line in /etc/passwd, as in a
# container run as a user id its image never named (M299). Path.home() raises RuntimeError there. A
# test cannot change its user id, so Python starts with pwd.getpwuid raising KeyError, as it does for
# an unknown id, then runs the script named first with the rest as its arguments.
NO_HOME = (
    "import pwd, runpy, sys\n"
    "def unknown(uid):\n"
    "    raise KeyError(f'getpwuid(): uid not found: {uid}')\n"
    "pwd.getpwuid = unknown\n"
    "sys.argv = sys.argv[1:]\n"
    "runpy.run_path(sys.argv[0], run_name='__main__')\n"
)


def no_home(script, *args, env: dict | None = None, **kwargs) -> subprocess.CompletedProcess:
    """Run `script args` under NO_HOME, with `env` (else this process's environment) less HOME."""
    bare = {k: v for k, v in (os.environ if env is None else env).items() if k != "HOME"}
    cmd = [sys.executable, "-c", NO_HOME, str(script), *map(str, args)]
    return subprocess.run(cmd, env=bare, capture_output=True, text=True, check=False, **kwargs)


def pytest_configure(config):
    engine_marker.pytest_configure(config)
    if not os.environ.get(LOCK_LOG):
        handle, log = tempfile.mkstemp(prefix="engine-lock-", suffix=".log")
        os.close(handle)
        os.environ[LOCK_LOG] = log
        _made.append(log)


def pytest_terminal_summary(terminalreporter):
    """The lines of the runs that waited for the lock in this session, so a slow session says why."""
    log = Path(os.environ.get(LOCK_LOG, ""))
    lines = log.read_text(encoding="utf-8").splitlines() if _made and log.is_file() else []
    if lines:
        terminalreporter.write_sep("-", f"engine lock: {len(lines)} lines in {log}")
        for line in lines:
            terminalreporter.write_line(line)


def pytest_unconfigure(config):
    engine_marker.pytest_unconfigure(config)
    for log in _made:
        Path(log).unlink(missing_ok=True)
