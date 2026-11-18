"""The routers the workcenter can run, behind 1 interface.

ROADMAP item 5, "A routing benchmark and a second router".

A router here is a program that reads the Specctra DSN the workcenter writes and writes a Specctra
session (.ses) the workcenter reads back. Every rule around a route is the workcenter's, not the
router's: the DSN's content (planes, hand copper, seed, stages, grown holes), the passes, the threads,
the time limit, the log, the reading back, the count of open connections and the DRC after. The
autoroute skill lists them; tests/test_routers.py holds each with a stand-in router.

Each router names:
- how its presence is found (`absent()`: "" when it can run, else why not),
- its version (`version()`: the jar's file name and its manifest's build),
- how it is run on the workcenter's DSN (`command()`, `run()`),
- how its output is read back (the session file; `unrouted()` reads its log's count).

Standard library only, as the CLI is.
"""

from __future__ import annotations

import os
import re
import shutil
import signal
import subprocess
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

WC_ROOT = Path(os.environ.get("WORKCENTER_ROOT", "/opt/workcenters/ee"))
# FreeRouting 2.5.0's count of what it left open and of its clearance violations, read with `javap -c -p`
# from the jar install.sh pins: FRLogger.formatScore(float, int, int) writes "<score> (<n> unrouted and
# <m> violation[s])"; the headless job logs it after "final score: ", the window's worker after "with the
# score of ". 1 line per stage; the last is the board it writes. FreeRouting 1.9.0 logs no count.
SCORE_RE = re.compile(r"(?:final score: |with the score of )[^()\n]*\((\d+) unrouted and (\d+) violations?\)")
JAVA_VERSION_RE = re.compile(r'version "(\d+)(?:\.(\d+))?')


class RouterTimeout(RuntimeError):
    """The router ran past the time limit and was stopped with every process it started."""


@dataclass(frozen=True)
class Router:
    """1 router: a jar run by a Java of at least `java_min` (None: the Java's version is not checked).

    `jar_env` and `java_env` name the environment variables that point at another jar or Java (a test's
    stand-in, a jar the benchmark compares). `display`: the router draws a window even when it routes
    alone, so it runs under xvfb-run where there is no display. `args` follow the common ones."""

    name: str
    label: str
    jar_env: str
    jar_default: Path
    java_env: str
    java_default: str
    java_min: int | None
    display: bool
    args: tuple[str, ...] = field(default=())
    user_data: bool = False

    def jar(self) -> Path:
        return Path(os.environ.get(self.jar_env) or self.jar_default)

    def java(self) -> str:
        return os.environ.get(self.java_env) or self.java_default

    def java_major(self) -> int | None:
        """The major version `java -version` prints, or None when it does not run or prints none."""
        exe = shutil.which(self.java())
        if exe is None:
            return None
        try:
            proc = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=60, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        m = JAVA_VERSION_RE.search((proc.stderr or "") + (proc.stdout or ""))
        if m is None:
            return None
        major = int(m.group(1))
        return int(m.group(2) or 0) if major == 1 else major  # "1.8.0" is Java 8

    def absent(self) -> str:
        """Why the router cannot run here, or "" when it can. FreeRouting 1.9.0 is held to its jar alone,
        as before this interface: a missing Java then fails the run as an absent engine
        (FileNotFoundError)."""
        jar = self.jar()
        if not jar.is_file():
            return f"{self.name}: no jar at {jar}"
        if self.java_min is not None:
            major = self.java_major()
            if major is None:
                return f"{self.name}: no Java at {self.java()}"
            if major < self.java_min:
                return f"{self.name}: needs Java {self.java_min}; {self.java()} is Java {major}"
        return ""

    def version(self) -> str:
        """The jar's file name (a link resolved) and its manifest's Build-Revision, for the record."""
        jar = self.jar()
        build = ""
        try:
            with zipfile.ZipFile(jar) as z:
                text = z.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
            build = next(
                (ln.split(":", 1)[1].strip() for ln in text.splitlines() if ln.startswith("Build-Revision:")),
                "",
            )
        except (OSError, KeyError, zipfile.BadZipFile):
            pass
        return jar.resolve().stem + (f" ({build})" if build else "")

    def command(self, dsn: Path, ses: Path, passes: int, threads: int, workdir: Path) -> list[str]:
        """The command line that routes `dsn` into `ses`."""
        # -de, -do, -mp and -dct are FreeRouting's from 1.9.0 to 2.5.0. Without `-dct 0` it waits 20 s for
        # a click on a dialog that asks to confirm the start, and nobody sees a dialog here.
        cmd = [self.java(), "-jar", str(self.jar()), "-de", str(dsn), "-do", str(ses), "-mp", str(passes)]
        cmd += ["-dct", "0", *self.args]
        if self.user_data:
            # Its settings file and its log in the route's own folder, not in the home folder.
            cmd.append(f"--user_data_path={workdir / self.name}")
        if threads > 0:
            cmd += ["-mt", str(threads)]
        if self.display and not os.environ.get("DISPLAY") and shutil.which("xvfb-run"):
            cmd = ["xvfb-run", "-a", *cmd]
        return cmd

    def run(self, dsn: Path, ses: Path, log: Path, passes: int, threads: int, timeout: int, cwd: Path) -> str:
        """Route `dsn` into `ses`; the router's output goes to `log` and is returned. A session left by an
        earlier run is removed first, so it is never read as this run's. Raises FileNotFoundError when the
        router is absent, RouterTimeout past `timeout` seconds (the router and every process it started
        are stopped: a session is written only at the end, so nothing is read), RuntimeError when it
        fails or writes no session."""
        why = self.absent()
        if why:
            raise FileNotFoundError(why)
        ses.unlink(missing_ok=True)
        # FreeRouting 2.5.0 reads a <board>.rules beside the DSN when none is named, and applies its
        # clearances, net classes and vias over the DSN's (its command_line_arguments.md, `-de`): the DSN
        # alone carries the rules.
        dsn.with_suffix(".rules").unlink(missing_ok=True)
        cmd = self.command(dsn, ses, passes, threads, cwd)
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            out, err = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # xvfb-run starts Java as its child: stopping xvfb-run alone left Java running and holding
            # the output, and the route waited for it.
            os.killpg(proc.pid, signal.SIGKILL)
            out, err = proc.communicate()
            log.write_text((out or "") + "\n" + (err or ""), encoding="utf-8")
            raise RouterTimeout(
                f"{self.label} stopped at the time limit ({timeout} s); it writes its session only when it "
                f"ends, so nothing is read; see {log}"
            ) from None
        text = (out or "") + "\n" + (err or "")
        log.write_text(text, encoding="utf-8")
        if proc.returncode != 0 or not ses.is_file():
            # The first word stays "FreeRouting exited N", as before this interface.
            raise RuntimeError(f"FreeRouting exited {proc.returncode}; see {log}")
        return text

    def score(self, text: str) -> tuple[int, int] | None:
        """The router's own count of open connections and of clearance violations, from the last score
        line of its log, or None when the log has none."""
        found = SCORE_RE.findall(text)
        return (int(found[-1][0]), int(found[-1][1])) if found else None

    def unrouted(self, text: str) -> int | None:
        """The router's own count of open connections from its log, or None when the log has none."""
        score = self.score(text)
        return score[0] if score else None

    def violations(self, text: str) -> int | None:
        """The router's own count of clearance violations from its log, or None when the log has none."""
        score = self.score(text)
        return score[1] if score else None


ROUTERS = {
    "freerouting": Router(
        name="freerouting",
        label="FreeRouting 1.9.0",
        jar_env="FREEROUTING_JAR",
        jar_default=WC_ROOT / "freerouting" / "freerouting.jar",
        java_env="JAVA",
        java_default="java",
        java_min=None,  # held to its jar alone, as before this interface
        display=True,
    ),
    # FreeRouting 2.5.0: its classes are of version 69, which Java 25 reads and Java 21 (65) does not.
    # `--gui.enabled=false` routes with no window, so it needs no display; `-da` sends no usage data. No
    # flag stops its version check: each run asks api.github.com for the latest release, under its own
    # User-Agent "Freerouting-Version-Checker", on a daemon thread that does not hold the route.
    "freerouting2": Router(
        name="freerouting2",
        label="FreeRouting 2.5.0",
        jar_env="FREEROUTING2_JAR",
        jar_default=WC_ROOT / "freerouting2" / "freerouting.jar",
        java_env="FREEROUTING2_JAVA",
        java_default=str(WC_ROOT / "java25" / "bin" / "java"),
        java_min=25,
        display=False,
        args=("-da", "--gui.enabled=false"),
        user_data=True,
    ),
}
DEFAULT = "freerouting"


def get(name: str) -> Router:
    """The router of that name; KeyError names the routers there are."""
    try:
        return ROUTERS[name]
    except KeyError:
        raise KeyError(f"no router {name!r}; the routers are {', '.join(ROUTERS)}") from None
