"""engine_watch — a line for each engine a Python process starts, and a refusal in the fast run.

`sitecustomize.py` beside this file installs it in every Python process that has this folder on
PYTHONPATH and WORKCENTER_ENGINE_LOG or WORKCENTER_NO_ENGINES set; `tools/ci/engine_marker.py` sets
both for a pytest run. An engine is started when `subprocess.Popen` runs one of ENGINES, directly,
behind a wrapper (`xvfb-run`, `timeout`) or in a shell's line, and when KiCad's Python module is
imported. Each start appends `<engine>\t<pid>\t<program>` to the file WORKCENTER_ENGINE_LOG names.
With WORKCENTER_NO_ENGINES=1 the start is refused with a FileNotFoundError, which the commands read
as an engine that is absent.

A program under the temporary folder is a test's stand-in, not an engine. A process started with
`python -I`, or with an environment that drops PYTHONPATH, is not watched. Standard library only.
"""

from __future__ import annotations

import errno
import importlib.machinery
import os
import re
import shutil
import subprocess
import sys
import tempfile

LOG_VAR = "WORKCENTER_ENGINE_LOG"
REFUSE_VAR = "WORKCENTER_NO_ENGINES"

# The board engines (tools/workcenter: KICAD_CLI, NGSPICE, JAVA for FreeRouting; tools/fields.py:
# openEMS) and the chip engines (tools/chipflow.py ENGINES; tests/test_engine_marker.py holds the 2
# lists together).
ENGINES = frozenset(
    {
        "kicad-cli",
        "ngspice",
        "java",
        "openEMS",
        "verilator",
        "iverilog",
        "vvp",
        "yosys",
        "klayout",
        "openroad",
        "sta",
        "magic",
        "netgen",
    }
)
MODULES = frozenset({"pcbnew"})  # KiCad's own Python module
WRAPPERS = frozenset({"xvfb-run", "timeout", "env", "nice", "nohup", "stdbuf", "flock"})
SHELLS = frozenset({"sh", "bash", "dash", "zsh"})
SHELL_WORD = re.compile(r"[\s;&|()<>`'\"]+")
SKIPPED = re.compile(r"-.*|[\d.]+[smhd]?|\w+=.*")  # a wrapper's option, duration or assignment


class EngineRefused(FileNotFoundError):
    """An engine started while WORKCENTER_NO_ENGINES=1."""


def stand_in(word: str, path: str | None) -> bool:
    """Whether a program is a test's own stand-in: a file under the temporary folder."""
    found = word if "/" in word else shutil.which(word, path=path)
    if not found:
        return False
    return os.path.realpath(found).startswith(os.path.realpath(tempfile.gettempdir()) + os.sep)


def engine_of(args: object, path: str | None = None) -> str | None:
    """The engine a command line starts, or None. `args` is Popen's: a list, or a shell's line."""
    if isinstance(args, (str, bytes)):
        return in_shell_line(os.fsdecode(args), path)
    words = words_of(args)
    while words:
        name = os.path.basename(words[0])
        if name in ENGINES:
            return None if stand_in(words[0], path) else name
        if name in SHELLS and "-c" in words[:-1]:
            return in_shell_line(words[words.index("-c") + 1], path)
        if name not in WRAPPERS:
            return None
        rest = words[1:]
        while rest and SKIPPED.fullmatch(rest[0]) and os.path.basename(rest[0]) not in ENGINES:
            rest = rest[1:]
        if name == "flock" and rest:
            rest = rest[1:]  # the lock file
        words = rest
    return None


def words_of(args: object) -> list[str]:
    """Popen's list of arguments as text; a single path is a list of 1."""
    if isinstance(args, os.PathLike):
        args = [args]
    return [os.fsdecode(a) if isinstance(a, (bytes, os.PathLike)) else str(a) for a in args]  # type: ignore[attr-defined]


def in_shell_line(line: str, path: str | None) -> str | None:
    for word in SHELL_WORD.split(line):
        if os.path.basename(word) in ENGINES and not stand_in(word, path):
            return os.path.basename(word)
    return None


def record(engine: str, program: str) -> None:
    """Append the start to the log, and refuse it in the fast run."""
    log = os.environ.get(LOG_VAR)
    if log:
        with open(log, "a", encoding="utf-8") as out:
            out.write(f"{engine}\t{os.getpid()}\t{program}\n")
    if os.environ.get(REFUSE_VAR) == "1":
        raise EngineRefused(errno.ENOENT, f"engine refused: {REFUSE_VAR}=1 (the fast run)", program)


class RefusedLoader:
    """The loader of a refused module: `importlib.util.find_spec` finds it, and the import fails as the
    import of an absent module does."""

    @staticmethod
    def create_module(spec):
        raise ModuleNotFoundError(
            f"{spec.name}: engine refused: {REFUSE_VAR}=1 (the fast run)", name=spec.name
        )

    @staticmethod
    def exec_module(module):
        return None


class ModuleWatch:
    """Goes first on sys.meta_path: a first import of a module of MODULES is an engine start."""

    @staticmethod
    def find_spec(name, path=None, target=None):
        if name in MODULES:
            try:
                record(name, name)
            except EngineRefused:
                return importlib.machinery.ModuleSpec(name, RefusedLoader())
        return None


_installed = False


def install() -> None:
    global _installed
    if _installed or not (os.environ.get(LOG_VAR) or os.environ.get(REFUSE_VAR)):
        return
    _installed = True
    original = subprocess.Popen.__init__

    def watched(self, args, *more, **kw):
        started = [kw["executable"]] if kw.get("executable") else args
        found = engine_of(started, (kw.get("env") or os.environ).get("PATH"))
        if found:
            self._child_created = False  # Popen.__del__ reads it
            shown = os.fsdecode(started) if isinstance(started, (str, bytes)) else words_of(started)[0]
            record(found, shown)
        original(self, args, *more, **kw)

    subprocess.Popen.__init__ = watched
    sys.meta_path.insert(0, ModuleWatch())
