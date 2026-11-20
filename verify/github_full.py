"""A pytest process that looks like a runner of GitHub's `full` job, for a collection that runs no test.

    PYTHONPATH=verify TESTSHARDS_LOG=<file> \\
        python -m pytest --collect-only -q -p github_full -p testshards tests

With `-p testshards`, each collected test's record in <file> holds its skip marks' reason as evaluated
here (`skip`). The tests a mark skips on GitHub's `full` job are those with a reason;
tests/test_ci_notjudged.py holds ee-agent-kit/CI.md's section "What GitHub does not judge" to their
count, file by file (M307).

Both paths of `full` run as user id 1001 with no chip folder and none of the chip engines, no FreeRouting
2.5.0 (opt-in, `install.sh --freerouting2`), and none of the variable that asks tests/test_image.py for
the image build (tests/test_image.py's scan of verify/ takes a line that names it for asking, unless
the line only takes it away, as this file does below). As pytest is configured,
before any test file is imported (a mark's condition is often evaluated as its file is imported), this
process's user id reads 1001 (os.geteuid, os.getuid), its user name reads `runner` (USER and LOGNAME,
which getpass.getuser reads first), WORKCENTER_CHIP_TOOLS and FREEROUTING2_JAR name paths that are not
there, and shutil.which finds no chip engine, by name or by path.

Only those conditions are faked. Everything else is this machine's: it must have what `full` installs
(KiCad, its libraries, ngspice, FreeRouting 1.9.0 and its Java). A skipif on any other condition is
evaluated as on this machine, and the count it gives may be wrong for GitHub: a fixed path such as
/opt/workcenters/ee/chip named without WORKCENTER_CHIP_TOOLS, os.access on a file root owns,
pwd.getpwuid, the real user id read some other way. tests/ holds none today. Importing the module changes
nothing.
"""

from __future__ import annotations

import os
import shutil

UID, USER = 1001, "runner"
# The chip engines, as tools/chipflow.py ENGINES names them.
CHIP_ENGINES = ("verilator", "iverilog", "vvp", "yosys", "klayout", "openroad", "sta", "magic", "netgen")
NOWHERE = "/nonexistent/github-full"


def look_like_full() -> None:
    os.environ["WORKCENTER_CHIP_TOOLS"] = f"{NOWHERE}/chip"
    os.environ["FREEROUTING2_JAR"] = f"{NOWHERE}/freerouting2/freerouting.jar"
    os.environ.pop("WORKCENTER_TEST_IMAGE_BUILD", None)
    os.environ["USER"] = os.environ["LOGNAME"] = USER
    os.geteuid = os.getuid = lambda: UID
    found = shutil.which

    def which(cmd, mode=os.F_OK | os.X_OK, path=None):
        if os.path.basename(os.fspath(cmd)) in CHIP_ENGINES:
            return None
        return found(cmd, mode, path)

    shutil.which = which


def pytest_configure(config) -> None:
    if not config.option.collectonly:
        raise SystemExit("github_full: only for `pytest --collect-only`; it runs no test")
    look_like_full()
