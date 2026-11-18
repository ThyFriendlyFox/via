"""engine_watch — a line for each engine a Python process starts, and a refusal in the fast run.

`sitecustomize.py` beside this file installs it in every Python process that has this folder on
PYTHONPATH and WORKCENTER_ENGINE_LOG or WORKCENTER_NO_ENGINES set; `tools/ci/engine_marker.py` sets
both for a pytest run. An engine is started when `subprocess.Popen`, `os.system`, `os.posix_spawn`,
`os.posix_spawnp`, `os.execv` or `os.execve` runs one of ENGINES, directly, behind a wrapper
(`xvfb-run`, `timeout -s KILL 60`, `flock f -c line`) or as a command of a shell's line, and when
KiCad's Python module is imported. Each start appends `<engine>\t<pid>\t<program>` to the file
WORKCENTER_ENGINE_LOG names. With WORKCENTER_NO_ENGINES=1 the start is refused with a
FileNotFoundError, which the commands read as an engine that is absent.

A program under the temporary folder is a test's stand-in, not an engine. A process started with
`python -I`, or with an environment that drops PYTHONPATH, is not watched. Standard library only.
"""

from __future__ import annotations

import errno
import importlib.machinery
import os
import re
import shlex
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
# A wrapper's options that take the next word as their value, as each one's --help on this machine
# lists them (coreutils timeout, env, nice, stdbuf; util-linux flock; xvfb-run).
VALUED = {
    "timeout": {"-s", "--signal", "-k", "--kill-after"},
    "env": {"-u", "--unset", "-C", "--chdir"},
    "nice": {"-n", "--adjustment"},
    "stdbuf": {"-i", "--input", "-o", "--output", "-e", "--error"},
    "flock": {"-w", "--timeout", "-E", "--conflict-exit-code"},
    "xvfb-run": {"-e", "--error-file", "-f", "--auth-file", "-n", "--server-num", "-p", "--xauth-protocol"}
    | {"-s", "--server-args"},
}
# The options whose value is the command itself, as a line: `flock f -c 'line'`, `env -S 'line'`.
LINE_OPTIONS = {"flock": ("-c", "--command"), "env": ("-S", "--split-string")}
SHELLS = frozenset({"sh", "bash", "dash", "zsh"})
SHELL_WORD = re.compile(r"[\s;&|()<>`'\"]+")
SKIPPED = re.compile(r"-.*|[\d.]+[smhd]?|\w+=.*")  # a wrapper's option, duration or assignment
# Words before a shell command's program: reserved words (if, then, do, ...) and `exec`, `command`.
SHELL_PREFIX = frozenset(
    {"if", "then", "else", "elif", "do", "while", "until", "!", "{", "time", "exec", "command"}
)


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
        rest = past_options(name, words[1:])
        if name == "flock" and rest and not isinstance(rest, str):
            rest = past_options(name, rest[1:])  # the lock file, then more options
        if isinstance(rest, str):
            return in_shell_line(rest, path)
        words = rest
    return None


def past_options(wrapper: str, rest: list[str]) -> list[str] | str:
    """The words after a wrapper's options and their values, or the command line an option gives."""
    while rest:
        word = rest[0]
        for option in LINE_OPTIONS.get(wrapper, ()):
            if word == option and len(rest) > 1:
                return rest[1]
            if word.startswith(option + "=") and option.startswith("--"):
                return word.split("=", 1)[1]
        if word in VALUED.get(wrapper, ()):
            rest = rest[2:]
        elif SKIPPED.fullmatch(word) and os.path.basename(word) not in ENGINES:
            rest = rest[1:]
        else:
            break
    return rest


def words_of(args: object) -> list[str]:
    """Popen's list of arguments as text; a single path is a list of 1."""
    if isinstance(args, os.PathLike):
        args = [args]
    return [os.fsdecode(a) if isinstance(a, (bytes, os.PathLike)) else str(a) for a in args]  # type: ignore[attr-defined]


def in_shell_line(line: str, path: str | None) -> str | None:
    """The engine a shell line starts. A program is the first word of a command: at the start, after
    ; && || | & ( ` or a newline, after SHELL_PREFIX words and assignments. A line shlex cannot split
    (an open quote) is read word by word, each word a program."""
    lexer = shlex.shlex(line.replace("\n", " ; ").replace("`", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        for word in SHELL_WORD.split(line):
            if os.path.basename(word) in ENGINES and not stand_in(word, path):
                return os.path.basename(word)
        return None
    command: list[str] = []
    for token in [*tokens, ";"]:
        if token and set(token) <= set(";&|()"):
            found = engine_of(command, path) if command else None
            if found:
                return found
            command = []
        elif not command and (token in SHELL_PREFIX or SKIPPED.fullmatch(token) and "=" in token):
            continue
        else:
            command.append(token)
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
    watch_os()


def _path_of(env: object) -> str | None:
    """PATH of an environment os.posix_spawn or os.execve is given (str or bytes keys), else ours."""
    if isinstance(env, dict):
        for key in ("PATH", b"PATH"):
            if key in env:
                return os.fsdecode(env[key])
    return os.environ.get("PATH")


def watch_os() -> None:
    """The starts that pass by subprocess: os.system (a shell line), os.posix_spawn and os.posix_spawnp,
    and os.execv and os.execve, which os.execvp, os.execl* and os.spawn* call by these names."""

    def checked(program: str, args: object, env: object, run, *call, **kw):
        argv = [program, *words_of(args)[1:]]
        found = engine_of(argv, _path_of(env))
        if found:
            record(found, os.fsdecode(program))
        return run(*call, **kw)

    system = os.system

    def watched_system(command):
        found = in_shell_line(os.fsdecode(command), os.environ.get("PATH"))
        if found:
            record(found, os.fsdecode(command))
        return system(command)

    os.system = watched_system
    for name, has_env in (("posix_spawn", True), ("posix_spawnp", True), ("execv", False), ("execve", True)):
        original = getattr(os, name, None)
        if original is None:
            continue

        def watched_call(program, args, *more, _run=original, _has_env=has_env, **kw):
            env = more[0] if _has_env and more else kw.get("env")
            return checked(os.fsdecode(program), args, env, _run, program, args, *more, **kw)

        setattr(os, name, watched_call)
