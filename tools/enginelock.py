#!/usr/bin/env python3
"""The engine lock: long commands take turns on 1 machine, first come first served.

A long command (the table `LONG`) takes a ticket in the lock's folder and runs when no live ticket with
a lower number is left. A ticket is a file `<number>.ticket` whose process holds an exclusive flock on
it for as long as it lives; the kernel drops that flock when the process ends by any signal, SIGKILL
too. So a ticket is live while its flock is held, and nothing else is trusted: not a pid, which a
restart or a new process may reuse, and not the file being there. A dead ticket is removed by the next
process that looks.

Numbers come from `.seq` under its own flock, so 2 runs that come in the same millisecond get 2 numbers.
The kernel's flock on 1 file would serve waiters in no fixed order; the numbers keep the order they came.

A long command started by the holder, or by a process the holder started, runs at once: the live
holder's pid is the process itself or one of its ancestors (/proc/<pid>/stat). The holder hands its
children `WORKCENTER_LOCK_TICKET`, the path of its ticket; the variable alone opens nothing.

Standard library only, as the CLI is (AGENTS.md invariants 3 and 14). `python3 tools/enginelock.py hold
-- CMD` runs any command under the lock, `held` answers whether this process may run without waiting,
and `state` prints who holds it.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

ENV_DIR = "WORKCENTER_LOCK_DIR"
ENV_SWITCH = "WORKCENTER_LOCK"
ENV_TICKET = "WORKCENTER_LOCK_TICKET"
ENV_EVERY = "WORKCENTER_LOCK_EVERY"
OFF = {"0", "off", "no", "false"}
EVERY = 30.0
POLL = 0.1

# Which commands take the lock, and when. A command starts an engine (kicad-cli, ngspice, FreeRouting,
# openEMS, a compiler, the chip tools) for more than a few seconds on the fixtures; the times are
# measured in docs/CONFIGURATION.md's table. Every other command never takes it and never waits.
LONG = {
    "gates": "always",
    "sim": "always",
    "mutate": "always",
    "bench": "always",
    "fields": "always",
    "autoroute": "always",
    "render": "always",
    "pictures": "always",
    "ci": "always",
    "copper": "always",
    "highspeed": "always",
    "export": "always",
    "design": "with --route",
    "verify": "without --init",
    "chip": "except chip init",
    "inspect": "inspect map only",
}


def is_long(args: argparse.Namespace) -> bool:
    """True when this parsed command line takes the lock."""
    cmd = getattr(args, "command", None)
    if cmd == "design":
        return bool(getattr(args, "route", False))
    if cmd == "verify":
        return not getattr(args, "init", False)
    if cmd == "chip":
        return getattr(args, "chip_command", None) != "init"
    if cmd == "inspect":
        return getattr(args, "view", None) == "map"
    return LONG.get(cmd) == "always"


def lock_dir() -> Path:
    """`WORKCENTER_LOCK_DIR`, else 1 folder per machine and user in the system's temporary folder."""
    named = os.environ.get(ENV_DIR)
    return Path(named) if named else Path(tempfile.gettempdir()) / f"workcenter-lock-{os.getuid()}"


def enabled() -> bool:
    return os.environ.get(ENV_SWITCH, "").strip().lower() not in OFF


def every() -> float:
    try:
        return max(0.05, float(os.environ.get(ENV_EVERY, EVERY)))
    except ValueError:
        return EVERY


def _seq(name: str) -> int | None:
    stem, dot, ext = name.partition(".")
    return int(stem) if dot and ext == "ticket" and stem.isdigit() else None


def _alive(path: Path) -> bool:
    """True while a process holds the ticket's flock. A ticket that is gone is not alive."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    finally:
        os.close(fd)
    return False


def _remove(path: Path) -> None:
    for p in (path, path.with_suffix(".held")):
        with contextlib.suppress(FileNotFoundError):
            p.unlink()


def _read(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return data if isinstance(data, dict) else {}


def survey(folder: Path | None = None) -> list[dict]:
    """The live tickets in the order they came, each with its number, path, pid, command and the time
    it came and took the lock (`since`, absent while it waits). Dead tickets are removed on the way."""
    folder = folder or lock_dir()
    try:
        names = os.listdir(folder)
    except FileNotFoundError:
        return []
    live = []
    for name in sorted(n for n in names if _seq(n) is not None):
        path = folder / name
        if not _alive(path):
            _remove(path)
            continue
        info = _read(path)
        held = path.with_suffix(".held")
        with contextlib.suppress(OSError, ValueError):
            info["since"] = float(held.read_text(encoding="utf-8"))
        info.update(seq=_seq(name), path=str(path))
        live.append(info)
    names = set(os.listdir(folder)) if folder.is_dir() else set()
    for name in names:
        if name.endswith(".held") and name[: -len(".held")] + ".ticket" not in names:
            with contextlib.suppress(FileNotFoundError):
                (folder / name).unlink()
    return live


def state(folder: Path | None = None) -> dict:
    """The lock as `doctor` prints it: the folder, whether it is on, the holder and how many wait."""
    folder = folder or lock_dir()
    live = survey(folder)
    return {
        "dir": str(folder),
        "enabled": enabled(),
        "holder": live[0] if live else None,
        "waiting": max(0, len(live) - 1),
    }


def ancestors(pid: int | None = None) -> list[int] | None:
    """The process's parent, grandparent and so on, from /proc; None where /proc cannot be read."""
    chain: list[int] = []
    p = os.getpid() if pid is None else pid
    for _ in range(4096):
        try:
            stat = Path(f"/proc/{p}/stat").read_text(encoding="utf-8")
        except OSError:
            return chain or None
        ppid = int(stat.rsplit(")", 1)[1].split()[1])
        if ppid <= 0:
            break
        chain.append(ppid)
        p = ppid
    return chain


def inside(folder: Path | None = None) -> dict | None:
    """The live holder when it is this process or an ancestor of it, else None. Where /proc cannot be
    read, a `WORKCENTER_LOCK_TICKET` equal to the live holder's ticket stands in for the ancestry."""
    live = survey(folder)
    if not live:
        return None
    holder = live[0]
    if holder.get("since") is None:
        return None
    pid = holder.get("pid")
    chain = ancestors()
    if chain is None:
        return holder if os.environ.get(ENV_TICKET) == holder["path"] else None
    return holder if pid == os.getpid() or pid in chain else None


def _clock(t: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(t))


def _span(seconds: float) -> str:
    s = int(seconds)
    if s < 60:
        return f"{s} s"
    if s < 3600:
        return f"{s // 60} min {s % 60} s"
    return f"{s // 3600} h {s % 3600 // 60} min"


def _runs(n: int) -> str:
    return f"{n} run{'' if n == 1 else 's'} ahead"


def holder_text(holder: dict, now: float | None = None) -> str:
    now = time.time() if now is None else now
    what = holder.get("what") or "an unnamed run"
    since = holder.get("since")
    when = f"since {_clock(since)}, {_span(now - since)} ago" if since else "taking it now"
    return f"held by `{what}` (pid {holder.get('pid')}) {when}"


class Ticket:
    """1 run's place in the line. `wait()` returns when it is the first live ticket; `release()` frees
    it. A process that dies frees it as well, by the kernel."""

    def __init__(self, what: str, folder: Path | None = None):
        self.folder = folder or lock_dir()
        self.what = what
        self.came = time.time()
        self.fd: int | None = None
        self.path: Path | None = None
        self.seq = 0
        self.ahead = 0
        self.waited = 0.0
        self._take()

    def _take(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        seq_fd = os.open(self.folder / ".seq", os.O_RDWR | os.O_CREAT | os.O_CLOEXEC, 0o600)
        try:
            fcntl.flock(seq_fd, fcntl.LOCK_EX)
            raw = os.pread(seq_fd, 32, 0).strip()
            names = os.listdir(self.folder)
            last = max([_seq(n) or 0 for n in names] + [int(raw) if raw.isdigit() else 0])
            # A run that died between its file and its rename left `.new-*`; under `.seq` no one
            # else is making one, so each is dead.
            for name in names:
                if name.startswith(".new-"):
                    with contextlib.suppress(FileNotFoundError):
                        (self.folder / name).unlink()
            self.seq = last + 1
            tmp = self.folder / f".new-{os.getpid()}-{self.seq}"
            fd = os.open(tmp, os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            info = {"pid": os.getpid(), "what": self.what, "cwd": os.getcwd(), "came": self.came}
            os.write(fd, json.dumps(info).encode())
            self.path = self.folder / f"{self.seq:012d}.ticket"
            os.rename(tmp, self.path)
            self.fd = fd
            os.ftruncate(seq_fd, 0)
            os.pwrite(seq_fd, str(self.seq).encode(), 0)
        finally:
            os.close(seq_fd)

    def wait(self, stream=None) -> None:
        stream = sys.stderr if stream is None else stream
        start = time.monotonic()
        told = None
        while True:
            live = survey(self.folder)
            ahead = [t for t in live if t["seq"] < self.seq]
            self.ahead = len(ahead)
            self.waited = time.monotonic() - start
            if not ahead:
                break
            if told is None or time.monotonic() - told >= every():
                told = time.monotonic()
                line = f"workcenter: waiting on the engine lock: {_runs(len(ahead))}; {holder_text(ahead[0])}"
                print(f"{line}; lock folder {self.folder}", file=stream, flush=True)
            time.sleep(POLL)
        if told is not None:
            print(f"workcenter: took the engine lock after {_span(self.waited)}", file=stream, flush=True)
        held = self.path.with_suffix(".held")
        tmp = self.folder / f".held-{os.getpid()}-{self.seq}"
        tmp.write_text(repr(time.time()), encoding="utf-8")
        os.rename(tmp, held)

    def release(self) -> None:
        if self.fd is None:
            return
        _remove(self.path)
        os.close(self.fd)
        self.fd = None


_STOPS = (signal.SIGTERM, signal.SIGHUP)


@contextlib.contextmanager
def _told_on_stop(ticket: Ticket, stream):
    """A run stopped by SIGTERM or SIGHUP (a host's time limit) prints 1 line that says so, frees its
    ticket, and dies of the same signal. Only the main thread may set handlers."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    phase = {"held": None}

    def stop(signum, _frame):
        name = signal.Signals(signum).name
        if phase["held"] is None:
            doing = f"after waiting {_span(ticket.waited)} on the engine lock, {_runs(ticket.ahead)}"
        else:
            doing = f"after holding the engine lock for {_span(time.monotonic() - phase['held'])}"
        print(
            f"workcenter: stopped by signal {signum} ({name}) {doing}: {ticket.what}", file=stream, flush=True
        )
        ticket.release()
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    before = {s: signal.signal(s, stop) for s in _STOPS}
    try:
        yield phase
    finally:
        for s, h in before.items():
            signal.signal(s, h)


@contextlib.contextmanager
def take(what: str, stream=None):
    """Hold the lock for the body: at once when it is off or this process is inside the holder's tree,
    else after every run that came earlier. Yields the ticket, or None when none was taken."""
    stream = sys.stderr if stream is None else stream
    if not enabled() or inside() is not None:
        yield None
        return
    ticket = Ticket(what)
    before = os.environ.get(ENV_TICKET)
    try:
        with _told_on_stop(ticket, stream) as phase:
            ticket.wait(stream)
            if phase is not None:
                phase["held"] = time.monotonic()
            os.environ[ENV_TICKET] = str(ticket.path)
            yield ticket
    finally:
        ticket.release()
        if before is None:
            os.environ.pop(ENV_TICKET, None)
        else:
            os.environ[ENV_TICKET] = before


def for_command(args: argparse.Namespace, argv: list[str]):
    """The lock for 1 `workcenter` command line: taken when the command is long, else nothing."""
    if not is_long(args):
        return contextlib.nullcontext()
    return take(shlex.join(["workcenter", *argv]))


def status_line(st: dict) -> str:
    if not st["enabled"]:
        return f"off ({ENV_SWITCH}={os.environ.get(ENV_SWITCH)}); folder {st['dir']}"
    if st["holder"] is None:
        return f"free ({st['dir']})"
    return f"{holder_text(st['holder'])}, {st['waiting']} waiting ({st['dir']})"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="enginelock.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("hold", help="run 1 command under the engine lock; its exit code is the command's")
    p.add_argument("--what", help="the name the waiting line and doctor show (default: the command)")
    p.add_argument("cmd", nargs=argparse.REMAINDER, help="-- and the command")
    sub.add_parser("held", help="exit 0 when this process may run a long command without waiting")
    p = sub.add_parser("state", help="who holds the lock, since when, and how many wait")
    p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "held":
        return 0 if not enabled() or inside() is not None else 1
    if args.action == "state":
        st = state()
        print(json.dumps(st, indent=2) if args.json else f"engine lock: {status_line(st)}")
        return 0
    cmd = args.cmd[1:] if args.cmd[:1] == ["--"] else args.cmd
    if not cmd:
        parser.error("hold needs a command after --")
    with take(args.what or shlex.join(cmd)):
        try:
            code = subprocess.run(cmd).returncode
            # A command that died of a signal exits as a shell reports it: 128 and the signal.
            return 128 - code if code < 0 else code
        except FileNotFoundError:
            print(f"enginelock.py: no command {cmd[0]}", file=sys.stderr)
            return 127


if __name__ == "__main__":
    sys.exit(main())
