"""The engine lock (`tools/enginelock.py`): long commands take turns on 1 machine, first come first served.

Every test runs real processes against a lock folder of its own (`WORKCENTER_LOCK_DIR`). The engine is a
stand-in that writes `start <tag>` to a log, waits until the file `release-<tag>` exists, then writes
`end <tag>`: a test lets each run go by making its file. No test sleeps longer than 0.8 s; a wait for a
state polls and gives up after 5 s.

The counts the tests expect are worked out by hand:

    3 runs, A holding, B and C waiting: C has 2 runs ahead (A and B), B has 1 (A); doctor counts 2
    waiting (B and C) and names A as the holder
    A holding, waiters B, C, D in the order they came: B, C, D start in that order, 1 after the other
    a run killed with SIGKILL: its ticket stays on disk with no process holding its flock; while a
    process it started (its engine) runs, the ticket still counts; when the last one ends the next survey
    removes it, so the run behind it starts within 1 poll (0.1 s) of that end
    the waiting line every 0.25 s (`WORKCENTER_LOCK_EVERY`): in 0.8 s at least 1 + 2 = 3 lines
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "tools" / "enginelock.py"
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
PY = sys.executable

ENGINE = """\
import sys, time
from pathlib import Path
tag, folder = sys.argv[1], Path(sys.argv[2])
log = folder / "log"
with log.open("a") as f:
    f.write(f"start {tag}\\n")
end = time.monotonic() + 20
while not (folder / f"release-{tag}").exists() and time.monotonic() < end:
    time.sleep(0.02)
with log.open("a") as f:
    f.write(f"end {tag}\\n")
"""

# The stand-in ngspice of `workcenter sim`: the same engine, its tag from the environment. It prints
# nothing, so the deck fails; the tests judge only when it ran.
NGSPICE = """\
import os, sys, time
from pathlib import Path
tag, folder = os.environ["ENGINE_TAG"], Path(os.environ["ENGINE_DIR"])
with (folder / f"pids-{tag}").open("a") as f:
    f.write(f"{os.getpid()}\\n")
with (folder / "log").open("a") as f:
    f.write(f"start {tag}\\n")
end = time.monotonic() + 20
while not (folder / f"release-{tag}").exists() and time.monotonic() < end:
    time.sleep(0.02)
with (folder / "log").open("a") as f:
    f.write(f"end {tag}\\n")
"""


class Bench:
    """A lock folder, the stand-in engine and every process a test starts; all stopped at the end."""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.dir = tmp / "lock"
        self.engine = tmp / "engine.py"
        self.engine.write_text(ENGINE, encoding="utf-8")
        ngspice = tmp / "ngspice"
        ngspice.write_text(f"#!{PY}\n{NGSPICE}", encoding="utf-8")
        ngspice.chmod(0o755)
        self.ngspice = ngspice
        self.procs: list[subprocess.Popen] = []

    def env(self, **extra: str) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if not k.startswith("WORKCENTER_LOCK")}
        env["WORKCENTER_LOCK_DIR"] = str(self.dir)
        env.update(extra)
        return env

    def start(self, argv: list[str], tag: str, **extra: str) -> subprocess.Popen:
        err = (self.tmp / f"err-{tag}").open("w")
        proc = subprocess.Popen(argv, env=self.env(**extra), stdout=subprocess.DEVNULL, stderr=err)
        self.procs.append(proc)
        return proc

    def hold(self, tag: str, **extra: str) -> subprocess.Popen:
        """`enginelock.py hold`, the lock's own command, in front of the stand-in engine."""
        cmd = [
            PY,
            str(LOCK),
            "hold",
            "--what",
            f"engine {tag}",
            "--",
            PY,
            str(self.engine),
            tag,
            str(self.tmp),
        ]
        return self.start(cmd, tag, **extra)

    def release(self, tag: str) -> None:
        (self.tmp / f"release-{tag}").touch()

    def log(self) -> list[str]:
        path = self.tmp / "log"
        return path.read_text(encoding="utf-8").split("\n")[:-1] if path.is_file() else []

    def err(self, tag: str) -> str:
        return (self.tmp / f"err-{tag}").read_text(encoding="utf-8")

    def tickets(self) -> list[str]:
        return sorted(p.name for p in self.dir.glob("*.ticket")) if self.dir.is_dir() else []

    def stop(self) -> None:
        for tag in "ABCDEFGHMPQ":
            self.release(tag)
        for proc in self.procs:
            if proc.poll() is None:
                proc.kill()
            proc.wait(5)


def until(what: str, check, timeout: float = 5.0) -> None:
    end = time.monotonic() + timeout
    while not check():
        if time.monotonic() > end:
            raise AssertionError(f"waited {timeout} s for {what}")
        time.sleep(0.02)


@pytest.fixture
def bench(tmp_path):
    b = Bench(tmp_path)
    yield b
    b.stop()


def started(b: Bench, tag: str) -> bool:
    return f"start {tag}" in b.log()


def test_two_long_commands_take_turns(bench):
    """A holds; B comes second and runs only after A's engine ended: start A, end A, start B."""
    a = bench.hold("A")
    until("A to start", lambda: started(bench, "A"))
    bench.hold("B")
    until("B's ticket", lambda: len(bench.tickets()) == 2)
    time.sleep(0.4)
    assert not started(bench, "B")
    bench.release("A")
    until("B to start", lambda: started(bench, "B"))
    assert a.wait(5) == 0
    assert bench.log() == ["start A", "end A", "start B"]


def test_three_waiters_are_served_in_the_order_they_came(bench):
    """A holds; B, C and D come in that order, each after the last one's ticket is on disk."""
    bench.hold("A")
    until("A to start", lambda: started(bench, "A"))
    for n, tag in enumerate("BCD", start=2):
        bench.hold(tag)
        until(f"{tag}'s ticket", lambda n=n: len(bench.tickets()) == n)
    for tag in "ABC":
        bench.release(tag)
        nxt = chr(ord(tag) + 1)
        until(f"{nxt} to start", lambda nxt=nxt: started(bench, nxt))
    bench.release("D")
    until("D to end", lambda: "end D" in bench.log())
    assert bench.log() == ["start A", "end A", "start B", "end B", "start C", "end C", "start D", "end D"]


def test_two_commands_wait_for_a_gate_and_the_first_starts_within_a_second_of_its_end(bench):
    """ROADMAP's Evidence: a gate (`hold --what "make verify"`, engine G) holds; B and C come while it
    runs and wait; G ends and B's engine starts within 1 s: 1 poll of 0.1 s plus the start of B's engine
    process (about 0.1 s here), 0.2 s, under the 1 s bar with room for a busy machine. C starts after B."""
    gate = [PY, str(LOCK), "hold", "--what", "make verify", "--", PY, str(bench.engine), "G", str(bench.tmp)]
    bench.start(gate, "G")
    until("the gate to start", lambda: started(bench, "G"))
    bench.hold("B")
    until("B's ticket", lambda: len(bench.tickets()) == 2)
    bench.hold("C")
    until("C's ticket", lambda: len(bench.tickets()) == 3)
    time.sleep(0.3)
    assert bench.log() == ["start G"]
    assert "held by `make verify`" in bench.err("C")
    bench.release("G")
    until("the gate to end", lambda: "end G" in bench.log())
    ended = time.monotonic()
    until("B to start", lambda: started(bench, "B"))
    assert time.monotonic() - ended < 1.0
    bench.release("B")
    until("C to start", lambda: started(bench, "C"))
    assert bench.log() == ["start G", "end G", "start B", "end B", "start C"]


def test_a_gate_that_comes_while_runs_wait_starts_within_a_second_of_the_last_ones_end(bench):
    """ROADMAP's Evidence, its 2nd half: A runs and B waits; then a gate comes (`hold --what "make
    verify"`, engine G). It takes its turn after A and B, and starts within 1 s of B's end: 1 poll of
    0.1 s plus the start of G's engine process (about 0.1 s here), 0.2 s, under the 1 s bar."""
    bench.hold("A")
    until("A to start", lambda: started(bench, "A"))
    bench.hold("B")
    until("B's ticket", lambda: len(bench.tickets()) == 2)
    gate = [PY, str(LOCK), "hold", "--what", "make verify", "--", PY, str(bench.engine), "G", str(bench.tmp)]
    bench.start(gate, "G")
    until("the gate's ticket", lambda: len(bench.tickets()) == 3)
    until("the gate's waiting line", lambda: "2 runs ahead" in bench.err("G"))
    bench.release("A")
    until("B to start", lambda: started(bench, "B"))
    time.sleep(0.3)
    assert not started(bench, "G")
    bench.release("B")
    until("B to end", lambda: "end B" in bench.log())
    ended = time.monotonic()
    until("the gate to start", lambda: started(bench, "G"))
    assert time.monotonic() - ended < 1.0
    assert bench.log() == ["start A", "end A", "start B", "end B", "start G"]


def test_tickets_taken_at_the_same_moment_get_distinct_numbers(tmp_path, monkeypatch):
    """8 threads take a ticket in 1 folder at the same moment (a barrier). The read of `.seq` is slowed by
    0.05 s, so without the `.seq` flock each thread reads the counter (empty) and the folder (no ticket)
    before any other writes, and all 8 would take number 0 + 1 = 1. Under the flock they read in turn:
    numbers 1 to 8, 8 ticket files, no error."""
    sys.path.insert(0, str(ROOT / "tools"))
    import enginelock

    real = os.pread

    def slow(*a):
        value = real(*a)
        time.sleep(0.05)
        return value

    monkeypatch.setattr(enginelock.os, "pread", slow)
    folder = tmp_path / "lock"
    barrier = threading.Barrier(8)
    tickets, errors = [], []

    def take():
        barrier.wait()
        try:
            tickets.append(enginelock.Ticket("t", folder))
        except Exception as exc:  # noqa: BLE001 - every failure is the finding
            errors.append(repr(exc))

    threads = [threading.Thread(target=take) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    try:
        assert errors == []
        assert sorted(t.seq for t in tickets) == list(range(1, 9))
        assert len(list(folder.glob("*.ticket"))) == 8
    finally:
        for t in tickets:
            t.release()


def test_a_holder_killed_with_sigkill_frees_the_lock_when_its_engine_ends(bench):
    """A's lock process dies by SIGKILL; its engine, A's child, runs on. B, waiting behind it, does not
    start beside that engine, and its line (every 0.25 s) says the holder ended and its engine still runs.
    A's engine ends; B starts, and A's ticket is gone: start A, end A, start B."""
    a = bench.hold("A")
    until("A to start", lambda: started(bench, "A"))
    bench.hold("B", WORKCENTER_LOCK_EVERY="0.25")
    until("B's ticket", lambda: len(bench.tickets()) == 2)
    a.send_signal(signal.SIGKILL)
    a.wait(5)
    until("B's line about A's engine", lambda: "still run" in bench.err("B"))
    assert bench.log() == ["start A"]
    bench.release("A")
    until("B to start", lambda: started(bench, "B"))
    assert bench.log() == ["start A", "end A", "start B"]
    assert len(bench.tickets()) == 1


def test_a_waiter_killed_while_waiting_does_not_block_those_behind_it(bench):
    """A holds, B and C wait; B dies by SIGKILL; when A ends, C starts."""
    bench.hold("A")
    until("A to start", lambda: started(bench, "A"))
    b = bench.hold("B")
    until("B's ticket", lambda: len(bench.tickets()) == 2)
    bench.hold("C")
    until("C's ticket", lambda: len(bench.tickets()) == 3)
    b.send_signal(signal.SIGKILL)
    b.wait(5)
    bench.release("A")
    until("C to start", lambda: started(bench, "C"))
    assert "start B" not in bench.log()


def test_the_waiting_line_names_the_holder_and_the_count(bench):
    """A holds, B waits, C waits with a line every 0.25 s: its first line says 2 runs ahead, names
    `engine A` and A's process, and when A took the lock; in 0.8 s it prints at least 3 lines."""
    a = bench.hold("A")
    until("A to start", lambda: started(bench, "A"))
    bench.hold("B")
    until("B's ticket", lambda: len(bench.tickets()) == 2)
    bench.hold("C", WORKCENTER_LOCK_EVERY="0.25")
    until("C's first line", lambda: "waiting" in bench.err("C"))
    time.sleep(0.8)
    lines = bench.err("C").splitlines()
    assert len(lines) >= 3, lines
    first = lines[0]
    assert "waiting on the engine lock: 2 runs ahead" in first, first
    assert "held by `engine A`" in first and f"pid {a.pid}" in first and "since " in first, first


def test_a_child_and_a_grandchild_of_the_holder_run_at_once(bench):
    """A holds and starts its own long command (`hold` again) as a child, and through a shell as a
    grandchild; both run while A holds. B, a stranger, still waits."""
    child = [PY, str(LOCK), "hold", "--what", "child", "--", PY, str(bench.engine), "C", str(bench.tmp)]
    grand = " ".join(
        [PY, str(LOCK), "hold", "--what", "grandchild", "--", PY, str(bench.engine), "G", str(bench.tmp)]
    )
    script = (
        "import subprocess, sys; "
        f"subprocess.run({child!r}, check=True); "
        f"subprocess.run(['sh', '-c', 'sh -c \"{grand}\"'], check=True)"
    )
    cmd = [PY, str(LOCK), "hold", "--what", "engine A", "--", PY, "-c", script]
    bench.start(cmd, "A")
    until("the child to start", lambda: started(bench, "C"))
    bench.hold("B")
    until("B's ticket", lambda: len(bench.tickets()) == 2)
    bench.release("C")
    until("the grandchild to start", lambda: started(bench, "G"))
    assert not started(bench, "B")
    bench.release("G")
    until("B to start", lambda: started(bench, "B"))
    assert bench.log() == ["start C", "end C", "start G", "end G", "start B"]


def test_a_stranger_with_a_copied_variable_waits(bench):
    """A holds and hands its children `WORKCENTER_LOCK_TICKET`; a process that is not A's child but
    carries the same value waits like any other."""
    script = (
        "import os, subprocess, sys; "
        f"open({str(bench.tmp / 'ticket')!r}, 'w').write(os.environ['WORKCENTER_LOCK_TICKET']); "
        f"subprocess.run([sys.executable, {str(bench.engine)!r}, 'A', {str(bench.tmp)!r}])"
    )
    bench.start([PY, str(LOCK), "hold", "--what", "engine A", "--", PY, "-c", script], "A")
    until("A to start", lambda: started(bench, "A"))
    ticket = (bench.tmp / "ticket").read_text(encoding="utf-8")
    assert Path(ticket).parent == bench.dir
    bench.hold("B", WORKCENTER_LOCK_TICKET=ticket)
    until("B's waiting line", lambda: "waiting on the engine lock" in bench.err("B"))
    assert not started(bench, "B")
    bench.release("A")
    until("B to start", lambda: started(bench, "B"))


def test_the_lock_turned_off_never_waits(bench):
    """`WORKCENTER_LOCK=off`: B runs while A holds, takes no ticket and prints nothing."""
    bench.hold("A")
    until("A to start", lambda: started(bench, "A"))
    bench.hold("B", WORKCENTER_LOCK="off")
    until("B to start", lambda: started(bench, "B"))
    assert len(bench.tickets()) == 1
    assert bench.err("B") == ""


def test_two_runs_that_come_in_the_same_millisecond_get_2_tickets_and_take_turns(bench):
    """P and Q wait on 1 file and then both become the lock's command; 1 of them runs, then the other,
    never both: the log is start X, end X, start Y, end Y."""
    go = bench.tmp / "go"
    for tag in "PQ":
        script = (
            "import os, sys, time\n"
            f"while not os.path.exists({str(go)!r}): time.sleep(0.001)\n"
            f"os.execv(sys.executable, [sys.executable, {str(LOCK)!r}, 'hold', '--what', 'engine {tag}', "
            f"'--', sys.executable, {str(bench.engine)!r}, '{tag}', {str(bench.tmp)!r}])\n"
        )
        bench.start([PY, "-c", script], tag)
    time.sleep(0.3)
    go.touch()
    until("2 tickets", lambda: len(bench.tickets()) == 2 or len(bench.log()) > 0)
    until("1 run to start", lambda: len(bench.log()) == 1)
    first = bench.log()[0].split()[1]
    other = "Q" if first == "P" else "P"
    until("2 tickets", lambda: len(bench.tickets()) == 2)
    time.sleep(0.3)
    assert bench.log() == [f"start {first}"]
    bench.release(first)
    until(f"{other} to start", lambda: started(bench, other))
    bench.release(other)
    until(f"{other} to end", lambda: f"end {other}" in bench.log())
    assert bench.log() == [f"start {first}", f"end {first}", f"start {other}", f"end {other}"]


def test_tickets_left_by_a_restart_block_nothing(bench):
    """A folder as a restart leaves it: ticket 5, whose process is gone, and a counter at 5. The ticket
    names pid 1, which lives, so a pid is not taken as proof; no process holds the ticket's flock, so A
    runs at once, the old ticket is removed, and A's ticket is number 6."""
    bench.dir.mkdir()
    old = {"pid": 1, "what": "engine before the restart", "came": 0}
    (bench.dir / "000000000005.ticket").write_text(json.dumps(old), encoding="utf-8")
    (bench.dir / "000000000005.held").write_text("0", encoding="utf-8")
    (bench.dir / ".seq").write_text("5", encoding="utf-8")
    bench.hold("A")
    until("A to start", lambda: started(bench, "A"))
    assert bench.tickets() == ["000000000006.ticket"]
    assert not (bench.dir / "000000000005.held").exists()
    assert bench.err("A") == ""


def test_a_waiter_stopped_by_sigterm_says_so(bench):
    """B waits and gets SIGTERM, as a host's time limit sends it: its last line says it was stopped
    while waiting, after how long and behind how many runs; it exits as a SIGTERM does."""
    bench.hold("A")
    until("A to start", lambda: started(bench, "A"))
    b = bench.hold("B")
    until("B's waiting line", lambda: "waiting" in bench.err("B"))
    b.send_signal(signal.SIGTERM)
    assert b.wait(5) == -signal.SIGTERM
    last = bench.err("B").splitlines()[-1]
    assert "stopped by signal 15 (SIGTERM) after waiting" in last and "1 run ahead" in last, last
    assert len(bench.tickets()) == 1


def test_held_answers_for_a_holders_child_and_for_a_stranger(bench):
    """`enginelock.py held` exits 0 inside a holder's tree and when the lock is off, 1 elsewhere: the
    test `verify/verify.sh` makes before it takes the lock for the whole gate."""
    held = [PY, str(LOCK), "held"]
    assert subprocess.run(held, env=bench.env()).returncode == 1
    assert subprocess.run(held, env=bench.env(WORKCENTER_LOCK="off")).returncode == 0
    script = f"import subprocess, sys; sys.exit(subprocess.run({held!r}).returncode)"
    inner = subprocess.run([PY, str(LOCK), "hold", "--", PY, "-c", script], env=bench.env())
    assert inner.returncode == 0


def test_verify_takes_the_lock_for_the_whole_gate():
    """verify/verify.sh asks `held` and, outside a holder, runs itself again under `hold` before its
    first step: the gate runs alone with no lock file of a lead's."""
    text = (ROOT / "verify" / "verify.sh").read_text(encoding="utf-8")
    head = text[: text.index('step "1/4 lint"')]
    assert "python3 tools/enginelock.py held" in head
    # `make verify-site` (verify.sh site) is named by its mode (tests/test_ci_scope.py).
    assert (
        'exec python3 tools/enginelock.py hold --what "make verify${1:+-$1}" -- bash verify/verify.sh "$@"'
        in head
    )


# --- the workcenter's own commands -------------------------------------------------------------------


def sim_project(bench: Bench) -> Path:
    project = bench.tmp / "board"
    shutil.copytree(BOARDS / "pass-rc-divider", project)
    return project


def workcenter(bench: Bench, tag: str, *argv: str, **extra: str) -> subprocess.Popen:
    env = {"NGSPICE": str(bench.ngspice), "ENGINE_TAG": tag, "ENGINE_DIR": str(bench.tmp), **extra}
    return bench.start([PY, str(CLI), *argv], tag, **env)


def test_two_sim_runs_take_turns_and_the_second_names_the_first(bench):
    """`workcenter sim` takes the lock: a second run waits, names `workcenter sim <project>` as the
    holder, and starts its engine after the first one's ended."""
    project = sim_project(bench)
    a = workcenter(bench, "A", "sim", str(project), "--out", str(bench.tmp / "out-a"))
    until("A's engine", lambda: started(bench, "A"))
    workcenter(bench, "B", "sim", str(project), "--out", str(bench.tmp / "out-b"))
    until("B's waiting line", lambda: "waiting" in bench.err("B"))
    assert f"held by `workcenter sim {project} --out {bench.tmp / 'out-a'}` (pid {a.pid})" in bench.err("B")
    assert not started(bench, "B")
    bench.release("A")
    until("B's engine", lambda: started(bench, "B"), timeout=20)
    assert bench.log().index("start B") > bench.log().index("start A")
    assert all(line != "start A" for line in bench.log()[bench.log().index("start B") :])


def test_a_short_command_returns_while_a_long_one_holds(bench):
    """`workcenter next` and `workcenter design` with no --route never take the lock: each ends while
    `workcenter sim` holds it and 5 more runs wait behind it (6 tickets: A, then B to F), and neither
    prints a waiting line. `next` gives its NEXT line in under 5 s, the bar of user round 1's candidate 3
    (`done_when`: "under 5 s" with 6 routes queued); it took 0.18 s alone on 2026-11-18."""
    project = sim_project(bench)
    workcenter(bench, "A", "sim", str(project), "--out", str(bench.tmp / "out-a"))
    until("A's engine", lambda: started(bench, "A"))
    assert len(bench.tickets()) == 1
    for n, tag in enumerate("BCDEF", start=2):
        bench.hold(tag)
        until(f"{tag}'s ticket", lambda n=n: len(bench.tickets()) == n)
    env = bench.env()
    began = time.monotonic()
    nxt = subprocess.run(
        [PY, str(CLI), "next", str(project)], env=env, capture_output=True, text=True, timeout=10
    )
    assert time.monotonic() - began < 5
    assert "engine lock" not in nxt.stderr
    assert "NEXT" in nxt.stdout or "DONE" in nxt.stdout, nxt.stdout
    first = bench.tmp / "first"
    shutil.copytree(BOARDS / "pass-first-design", first)
    design = subprocess.run(
        [PY, str(CLI), "design", str(first / "design.py"), "--out", str(bench.tmp / "first-out")],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "engine lock" not in design.stderr, design.stderr
    assert not started(bench, "B")
    assert bench.log() == ["start A"]


def test_a_child_of_a_holder_runs_the_workcenter_at_once(bench):
    """`hold` in front of a shell that runs `workcenter sim`, as `make verify` runs the suite: the sim
    is the holder's grandchild and runs while the holder holds."""
    project = sim_project(bench)
    shell = f"{PY} {CLI} sim {project} --out {bench.tmp / 'out-c'}"
    env = {"NGSPICE": str(bench.ngspice), "ENGINE_TAG": "C", "ENGINE_DIR": str(bench.tmp)}
    bench.start([PY, str(LOCK), "hold", "--what", "make verify", "--", "sh", "-c", shell], "H", **env)
    until("the sim's engine", lambda: started(bench, "C"))
    assert "waiting" not in bench.err("H")


def test_measure_waits_behind_a_sim(bench):
    """`workcenter measure` runs the project's sim, every deck and corner, as `sim` does: it waits while
    `workcenter sim` holds the lock, names it, and starts its engine only after the holder's ended."""
    project = sim_project(bench)
    workcenter(bench, "A", "sim", str(project), "--out", str(bench.tmp / "out-a"))
    until("A's engine", lambda: started(bench, "A"))
    workcenter(bench, "M", "measure", str(project), "--out", str(bench.tmp / "out-m"))
    until("measure's waiting line", lambda: "waiting on the engine lock" in bench.err("M"))
    assert "held by `workcenter sim" in bench.err("M")
    assert not started(bench, "M")
    bench.release("A")
    until("measure's engine", lambda: started(bench, "M"), timeout=20)
    log = bench.log()
    assert all(line != "start A" for line in log[log.index("start M") :])


def alive(pid: int) -> bool:
    """True while the process runs; a zombie (state Z) has ended."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def test_a_holder_stopped_by_sigterm_stops_its_engine_before_the_next_run_starts(bench):
    """A host's time limit sends SIGTERM to a holding `workcenter sim`. It passes the signal to the
    engine it started, says so in its last line, and B's engine starts only when no engine of A's runs."""
    project = sim_project(bench)
    a = workcenter(bench, "A", "sim", str(project), "--out", str(bench.tmp / "out-a"))
    until("A's engine", lambda: started(bench, "A"))
    workcenter(bench, "B", "sim", str(project), "--out", str(bench.tmp / "out-b"))
    until("B's waiting line", lambda: "waiting" in bench.err("B"))
    a.send_signal(signal.SIGTERM)
    assert a.wait(5) == -signal.SIGTERM
    until("B's engine", lambda: started(bench, "B"), timeout=10)
    pids = [int(p) for p in (bench.tmp / "pids-A").read_text(encoding="utf-8").split()]
    assert pids and not any(alive(p) for p in pids), pids
    last = bench.err("A").splitlines()[-1]
    assert "stopped by signal 15 (SIGTERM) after holding the engine lock" in last, last
    assert "passed it to 1 process it started" in last, last


def test_a_lock_folder_that_is_a_file_is_refused_in_1_line(bench):
    """`WORKCENTER_LOCK_DIR` names a file: `hold`, `held`, `state` and `workcenter sim` each refuse in 1
    line that names the variable, the path and why, exit 2, and print no traceback; the sim's engine never
    starts."""
    afile = bench.tmp / "afile"
    afile.write_text("", encoding="utf-8")
    env = {"WORKCENTER_LOCK_DIR": str(afile)}
    project = sim_project(bench)
    runs = {
        "hold": [PY, str(LOCK), "hold", "--", "true"],
        "held": [PY, str(LOCK), "held"],
        "state": [PY, str(LOCK), "state"],
        "sim": [PY, str(CLI), "sim", str(project), "--out", str(bench.tmp / "out-s")],
    }
    for name, argv in runs.items():
        extra = {"NGSPICE": str(bench.ngspice), "ENGINE_TAG": "S", "ENGINE_DIR": str(bench.tmp), **env}
        done = subprocess.run(argv, env=bench.env(**extra), capture_output=True, text=True, timeout=60)
        lines = done.stderr.splitlines()
        assert done.returncode == 2, (name, done.returncode, done.stderr)
        assert len(lines) == 1 and "Traceback" not in done.stderr, (name, done.stderr)
        assert f"WORKCENTER_LOCK_DIR={afile}" in lines[0] and "is not a folder" in lines[0], lines[0]
    assert not started(bench, "S")


# doctor asks every engine for its version: the 2 doctor tests start them (tools/ci/engine_marker.py).
@pytest.mark.engine
def test_doctor_with_a_lock_folder_that_is_a_file_says_not_judged(bench):
    """doctor is the diagnostic command: with `WORKCENTER_LOCK_DIR` naming a file it prints its tool
    table, the lock as not judged with the reason, and no traceback; `--json` carries the reason."""
    afile = bench.tmp / "afile"
    afile.write_text("", encoding="utf-8")
    env = bench.env(WORKCENTER_LOCK_DIR=str(afile))
    done = subprocess.run([PY, str(CLI), "doctor"], env=env, capture_output=True, text=True, timeout=120)
    assert "Traceback" not in done.stderr, done.stderr
    assert "ngspice" in done.stdout, done.stdout
    line = next(ln for ln in done.stdout.splitlines() if "engine lock" in ln)
    assert "not judged" in line and "is not a folder" in line, line
    data = json.loads(
        subprocess.run([PY, str(CLI), "--json", "doctor"], env=env, capture_output=True, text=True).stdout
    )
    assert "is not a folder" in data["engine_lock"]["not_judged"]


def test_the_lock_folder_does_not_follow_tmpdir(bench):
    """2 runs of 1 user whose TMPDIR differ share 1 lock: with no `WORKCENTER_LOCK_DIR`, the folder is
    /tmp/workcenter-lock-<uid> whatever TMPDIR says."""
    tools = str(ROOT / "tools")
    code = f"import sys; sys.path.insert(0, {tools!r}); import enginelock; print(enginelock.lock_dir())"
    env = {k: v for k, v in bench.env().items() if k != "WORKCENTER_LOCK_DIR"}
    seen = set()
    for tmp in ("tA", "tB"):
        (bench.tmp / tmp).mkdir()
        env["TMPDIR"] = str(bench.tmp / tmp)
        seen.add(subprocess.run([PY, "-c", code], env=env, capture_output=True, text=True).stdout.strip())
    assert seen == {f"/tmp/workcenter-lock-{os.getuid()}"}


@pytest.mark.engine
def test_doctor_prints_the_state_of_the_lock(bench):
    """Free, `workcenter doctor` says so with the folder. With A holding and B waiting it names A,
    since when, and 1 waiting; `--json` carries the same."""
    env = bench.env()
    free = subprocess.run([PY, str(CLI), "doctor"], env=env, capture_output=True, text=True, timeout=120)
    assert f"engine lock  free ({bench.dir})" in free.stdout, free.stdout
    a = bench.hold("A")
    until("A to start", lambda: started(bench, "A"))
    bench.hold("B")
    until("B's ticket", lambda: len(bench.tickets()) == 2)
    held = subprocess.run([PY, str(CLI), "doctor"], env=env, capture_output=True, text=True, timeout=120)
    line = next(ln for ln in held.stdout.splitlines() if "engine lock" in ln)
    assert f"held by `engine A` (pid {a.pid}) since " in line and "1 waiting" in line, line
    data = json.loads(
        subprocess.run(
            [PY, str(CLI), "--json", "doctor"], env=env, capture_output=True, text=True, timeout=120
        ).stdout
    )
    lock = data["engine_lock"]
    assert lock["holder"]["what"] == "engine A" and lock["holder"]["pid"] == a.pid
    assert lock["waiting"] == 1 and lock["dir"] == str(bench.dir)


# --- which commands are long -------------------------------------------------------------------------


def ns(command: str, **kw) -> argparse.Namespace:
    return argparse.Namespace(command=command, **kw)


def test_the_long_commands_are_the_measured_ones():
    """The table of docs/CONFIGURATION.md: these take the lock, and only these. Measured on 2026-11-18 with
    the lock off: `copper` 16.45 s on pass-copper-strip, `highspeed` 10.58 s on pass-highspeed, `export`
    4.98 s on Last Hit v0.16, each over the 3 s line; `erc` 0.60 s and `drc` 1.21 s on the same board, and
    `design` without --route 1.51 s, stay under it."""
    sys.path.insert(0, str(ROOT / "tools"))
    import enginelock

    long_ = ["gates", "sim", "mutate", "bench", "fields", "autoroute", "render", "pictures", "chip", "ci"]
    long_ += ["copper", "highspeed", "export"]
    # `measure` runs the project's whole sim, every deck and corner (tools/measureplan.py, gate_sim).
    long_ += ["measure"]
    for name in long_:
        assert enginelock.is_long(ns(name)), name
    assert enginelock.is_long(ns("design", route=True))
    assert not enginelock.is_long(ns("design", route=False))
    assert enginelock.is_long(ns("verify", init=False))
    assert not enginelock.is_long(ns("verify", init=True))
    # `inspect map` drew Last Hit v0.16 in 7.00 s; `inspect list` read it in 0.47 s.
    assert enginelock.is_long(ns("inspect", view="map"))
    assert not enginelock.is_long(ns("inspect", view="list"))
    short = ["next", "ratings", "fetch", "doctor", "now", "references", "curve", "procure"]
    short += ["erc", "drc", "placement", "inspect", "sources", "docs", "costs", "version", "diagram"]
    for name in short:
        assert not enginelock.is_long(ns(name)), name


def test_every_command_of_the_cli_is_named_long_or_short():
    """A command added to `tools/workcenter` after the lock was built (`new` and `standards` came so)
    would be short by default and never measured. Each command `workcenter --help` lists is a key of
    `LONG` or a name in `SHORT`, never both. `new` wrote a project in 0.17 s and `standards` judged
    pass-layout in 0.24 s on 2026-11-18, with the lock off."""
    sys.path.insert(0, str(ROOT / "tools"))
    import enginelock

    usage = subprocess.run([PY, str(CLI), "--help"], capture_output=True, text=True, timeout=60).stdout
    commands = set(usage[usage.index("{") + 1 : usage.index("}")].split(","))
    short = set(getattr(enginelock, "SHORT", ()))
    assert not set(enginelock.LONG) & short, set(enginelock.LONG) & short
    assert commands - set(enginelock.LONG) - short == set(), "not named long or short"
    assert set(enginelock.LONG) | short <= commands, "named but not a command"
