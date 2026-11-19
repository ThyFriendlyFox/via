"""The routers Via can run, behind 1 interface.

ROADMAP item 5, "A routing benchmark and a second router".

A router here is a program that reads the Specctra DSN Via writes and writes a Specctra
session (.ses) Via reads back. Every rule around a route is Via's, not the
router's: the DSN's content (planes, hand copper, seed, stages, grown holes), the passes, the threads,
the time limit, the log, the reading back, the count of open connections and the DRC after. The
autoroute skill lists them; tests/test_routers.py holds each with a stand-in router.

Each router names:
- how its presence is found (`absent()`: "" when it can run, else why not),
- its version (`version()`: the jar's file name and its manifest's build),
- how it is run on Via's DSN (`command()`, `run()`),
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
# A Java exception's line: `java.awt.HeadlessException: ...`, as FreeRouting 1.9.0 logs it on a JVM
# that cannot draw (its log on this machine, with a JVM without lib/libawt_xawt.so).
JAVA_THROWN = re.compile(r"^\s*((?:[a-z_$][\w$]*\.)+[A-Z][\w$]*(?:Exception|Error)\b.*)$", re.MULTILINE)
# The Java FreeRouting 1.9.0 is held to: ee-agent-kit/docs/ENGINES.md, "Needs Java 21". It is the Java
# install.sh installs (openjdk-21-jre-headless and openjdk-21-jre) and records; install.sh's JAVA_MIN is
# the same number.
JAVA_MIN = 21
# FreeRouting 1.9.0 draws a window even when it routes alone (it runs under xvfb-run), so its JVM needs
# AWT's X11 library. Ubuntu's openjdk-21-jre-headless has none (its file list names lib/libawt.so and
# lib/libawt_headless.so); openjdk-21-jre adds lib/libawt_xawt.so. In CI run 44515796762 install.sh
# recorded the headless JVM, and every route there ended in "FreeRouting exited 1".
AWT_X11 = Path("lib") / "libawt_xawt.so"


def java_major(exe: str) -> int | None:
    """The major version `exe -version` prints, or None when it does not run or prints none."""
    found = shutil.which(exe)
    if found is None:
        return None
    try:
        proc = subprocess.run([found, "-version"], capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    m = JAVA_VERSION_RE.search((proc.stderr or "") + (proc.stdout or ""))
    if m is None:
        return None
    major = int(m.group(1))
    return int(m.group(2) or 0) if major == 1 else major  # "1.8.0" is Java 8


RELEASE_VERSION_RE = re.compile(r'^JAVA_VERSION="(\d+)(?:\.(\d+))?', re.MULTILINE)


def release_major(jvm: Path) -> int | None:
    """The major version a JVM states in its `release` file (`JAVA_VERSION="21.0.13.0.3"` in Ubuntu's
    /usr/lib/jvm/java-21-openjdk-amd64/release), or None when it has none. Read so that the check
    starts no java: a routing test module asks it when it is imported, also inside `workcenter
    design` for a design file that imports that module, in a test that starts no engine."""
    try:
        m = RELEASE_VERSION_RE.search((jvm / "release").read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    if m is None:
        return None
    major = int(m.group(1))
    return int(m.group(2) or 0) if major == 1 else major


def java_refusal(exe: str) -> str:
    """Why FreeRouting 1.9.0 cannot run on `exe`, or "" when nothing here stops it: the java is there,
    its JVM (the folder above its bin/, links resolved) has lib/libawt_xawt.so, and it is Java JAVA_MIN
    or newer. Doctor's java row holds it to the same: the router and doctor never disagree."""
    found = shutil.which(exe)
    if found is None:
        return "no java on PATH" if exe == "java" else f"no java at {exe}"
    home = Path(found).resolve().parent.parent
    lib = home / AWT_X11.parent
    if not (lib / AWT_X11.name).is_file():
        return (
            f"{lib} has no {AWT_X11.name}: a headless Java runtime cannot draw FreeRouting 1.9.0's window "
            "(openjdk-21-jre adds the library)"
        )
    # The JVM's release file when it has one; else its java is asked (`-version`).
    major = release_major(home)
    if major is None:
        major = java_major(found)
    if major is None:
        return f"{found} -version names no version"
    if major < JAVA_MIN:
        return f"{found} is Java {major}; FreeRouting 1.9.0 needs Java {JAVA_MIN}"
    return ""


def java_choice(refuse: bool = True) -> tuple[str, str, str]:
    """The java Via runs, where it came from, and why FreeRouting 1.9.0 cannot run on it ("" when it can).
    This is the 1 place that decides it; every java is held to java_refusal.

    1. `JAVA`, when set: a test's stand-in or a user's choice ("set by JAVA"). Nothing replaces it.
    2. Else the JVM install.sh installed, by the path it recorded in <WORKCENTER_ROOT>/java.path, whatever
       java stands first on PATH. On GitHub's runner that is the runner's own Java 17 (CI run
       44444183056: doctor read 17.0.21 after apt had set up openjdk-21-jre-headless 21.0.13.1).
       When the record cannot be read, holds more than 1 line, or names a java that is gone, cannot
       draw or is older than JAVA_MIN, and the first java on PATH passes, that one, named with the
       reason the record was passed over.
    3. Else `java` on PATH: no record, so install.sh installed none here.

    Without `refuse`, the reason is "" wherever the pick does not rest on it (JAVA, no record): a
    command line is built without starting a java."""
    named = os.environ.get("JAVA")

    def refusal(exe: str) -> str:
        return java_refusal(exe) if refuse else ""

    if named:
        return named, "set by JAVA", refusal(named)
    record = Path(os.environ.get("WORKCENTER_ROOT", "/opt/workcenters/ee")) / "java.path"
    try:
        lines = record.read_text(encoding="utf-8").strip().splitlines()
    except FileNotFoundError:
        lines = []
    except OSError as err:
        # A record that is there but cannot be read (a folder, no permission) is named, not skipped.
        unread = f"{record} cannot be read ({err.strerror or type(err).__name__})"
        return "java", f"the first java on PATH: {unread}", refusal("java")
    if not lines:
        return "java", "the first java on PATH", refusal("java")
    # install.sh writes 1 path. The first line stands for the record in every line Via prints, so that
    # no line of doctor or of a route holds a raw line break.
    recorded = lines[0].strip()
    how = f"recorded by install.sh in {record}"
    many = f"{record} holds {len(lines)} lines; install.sh writes 1 path"
    why = many if len(lines) > 1 else java_refusal(recorded)
    if why and not java_refusal("java"):
        return "java", f"the first java on PATH: the java {how}, {recorded}, cannot run: {why}", ""
    return recorded, how, why


def workcenter_java() -> tuple[str, str]:
    """The java Via runs and where it came from (java_choice, without the reason it cannot run)."""
    exe, how, _ = java_choice(refuse=False)
    return exe, how


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
        """The router's own Java when it names one; else Via's (`workcenter_java`)."""
        return os.environ.get(self.java_env) or self.java_default or workcenter_java()[0]

    def java_major(self) -> int | None:
        """The major version `java -version` prints, or None when it does not run or prints none."""
        return java_major(self.java())

    def absent(self) -> str:
        """Why the router cannot run here, or "" when it can. FreeRouting 1.9.0 is held to its jar and to
        Via's java (java_choice), JAVA's too: a java that is not there, cannot draw its window or is
        older than JAVA_MIN is named with where it came from and why (CI run 44515796762). A java the
        router names of its own (FreeRouting 2.5.0's) is held to `java_min`."""
        jar = self.jar()
        if not jar.is_file():
            return f"{self.name}: no jar at {jar}"
        if not self.java_env and not self.java_default:
            exe, how, why = java_choice()
            if why:
                return f"{self.name}: {exe} ({how}) cannot run {self.label}: {why}"
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
            # The first words stay "FreeRouting exited N", as before this interface. Then the java that
            # ran and what the router threw (its first Java exception line, which FreeRouting 1.9.0
            # logs on stdout), else its last line on stderr: the reports of CI run 44515796762 showed
            # only the exit code, and the log they named stayed on GitHub's runner.
            thrown = JAVA_THROWN.search(text)
            last = next((ln.strip() for ln in reversed((err or "").splitlines()) if ln.strip()), "")
            said = thrown.group(1).strip() if thrown else last
            said = f"; it said: {said}" if said else ""
            raise RuntimeError(f"FreeRouting exited {proc.returncode} (java {self.java()}){said}; see {log}")
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
        # No Java of its own: Via's, which `JAVA` overrides (workcenter_java).
        java_env="",
        java_default="",
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
