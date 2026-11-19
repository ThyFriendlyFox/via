#!/usr/bin/env python3
"""The health gate's tests in several pytest processes at once, joined into 1 verdict.

`run` splits the test files into shards by the time `verify/shards.csv` gives each, starts 1 pytest per
shard side by side, then the files that must run alone, and joins the results. The gate is red when a
shard exits non-zero, when a shard's log ends with no summary line, or when the ids the shards ran are
not exactly the ids 1 pytest process collects. It prints each shard's time and the 10 slowest files.
For a failed test, an error at setup or teardown, or a file that could not be collected, it prints what
pytest reported (a `why:` line, then the report under `  | `), bounded; for a shard that ended with no
report to show, the test it started last and the end of its output.

Loaded into pytest with `-p testshards`, the same module writes each collected id and each test report
to the file `TESTSHARDS_LOG` names, 1 JSON object to a line, with a failure's report bounded. Standard
library only.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The last line pytest prints: "1658 passed, 1 skipped, 1 warning in 1290.61s (0:21:30)", with or
# without the rule of `=` around it, or "no tests ran in 0.01s".
SUMMARY_RE = re.compile(
    r"^=*\s*((?:\d+ (?:passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?|rerun)(?:, )?)+"
    r" in [0-9.]+s(?: \([0-9:]+\))?|no tests ran in [0-9.]+s)\s*=*$"
)
OUTCOMES = ("passed", "failed", "skipped", "xfailed", "xpassed")

# Why a test failed, in the gate's own output: after a CI run, and inside the image, the shards' logs are
# gone. The bounds keep 300 failures from printing 300 pages; each cut says what it cut and where the whole
# report is. A report keeps its first HEAD lines (the test's own frame) and its last TAIL (the line that
# raised and the exception); each captured output keeps its last SECTION lines; a line keeps WIDTH
# characters. The gate prints the reports of the first REASONS failures. Of a shard with no report to show
# it prints the last TAIL lines of output, or a crash's stack: its first HEAD and last TAIL lines.
HEAD, TAIL, SECTION, WIDTH, REASONS = 10, 30, 10, 300, 10


# -- the pytest side: loaded with `-p testshards` ---------------------------------------------------


def printable(text: str) -> str:
    """The text with each character UTF-8 cannot write escaped, as `\\udcff`: a test's output decoded with
    surrogateescape holds lone surrogates, and a strict stdout (a full UTF-8 locale) refuses them. A
    reason's text must never stop the gate before its verdict."""
    return text.encode("utf-8", "backslashreplace").decode("utf-8")


def bounded(lines: list[str], head: int, tail: int) -> list[str]:
    """The first `head` and the last `tail` lines, with 1 line that says how many were cut between; each
    line cut to WIDTH characters, with what it cut, and made printable."""
    out = []
    for line in lines:
        line = printable(line.rstrip())
        if len(line) > WIDTH:
            line = f"{line[:WIDTH]} [... {len(line) - WIDTH} characters cut]"
        out.append(line)
    if len(out) > head + tail:
        out = [*out[:head], f"[... {len(out) - head - tail} lines cut here]", *out[len(out) - tail :]]
    return out


def why(report) -> list[str]:
    """What pytest reports for a failed phase or a failed collection, as its failure's section of the
    report has it: the traceback with the line that raised and the exception, then each captured output."""
    out = bounded(str(report.longreprtext).splitlines(), HEAD, TAIL)
    for title, content in getattr(report, "sections", []):
        if title.startswith("Captured"):
            out.append(f"----- {title} -----")
            out += bounded(content.splitlines(), 0, SECTION)
    return out


def _log(records: list[dict]) -> None:
    path = os.environ.get("TESTSHARDS_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def _marks(item) -> dict:
    """What the item's skip, skipif and xfail marks say in this process's environment: the reason of
    the skip or the xfail they give, or None. pytest evaluates the same marks as each test starts."""
    try:
        from _pytest.skipping import evaluate_skip_marks, evaluate_xfail_marks
    except ImportError:
        return {"marks": None}
    try:
        skip, xfail = evaluate_skip_marks(item), evaluate_xfail_marks(item)
    except Exception as exc:  # a condition that raises: pytest errors the test as it starts
        return {"skip": f"error: {exc}", "xfail": None}
    return {"skip": None if skip is None else skip.reason, "xfail": None if xfail is None else xfail.reason}


def pytest_collection_finish(session) -> None:
    _log([{"collected": item.nodeid, **_marks(item)} for item in session.items])


def pytest_runtest_logreport(report) -> None:
    record = {"id": report.nodeid, "when": report.when, "outcome": report.outcome, "seconds": report.duration}
    if hasattr(report, "wasxfail"):
        record["xfail"] = True
    if report.skipped and isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
        record["reason"] = str(report.longrepr[2]).removeprefix("Skipped: ")
    if report.failed:
        record["why"] = why(report)
    _log([record])


def pytest_collectreport(report) -> None:
    """A file or a class that could not be collected: its record, with what pytest reports."""
    if report.failed:
        _log([{"collect_error": report.nodeid or ".", "why": why(report)}])


def pytest_sessionfinish(session, exitstatus) -> None:
    """The record that pytest reached its end of session: a process cut short, even with exit 0, has none."""
    _log([{"finished": int(exitstatus)}])


# -- the plan ---------------------------------------------------------------------------------------


@dataclass
class Row:
    seconds: float
    engine: bool
    alone: str


@dataclass
class Table:
    default: Row
    rows: dict[str, Row]

    def row(self, name: str) -> Row:
        return self.rows.get(name, self.default)


@dataclass
class Shard:
    name: str
    files: list[str] = field(default_factory=list)
    seconds: float = 0.0
    serial: bool = False
    unknown: list[str] = field(default_factory=list)
    reasons: dict[str, str] = field(default_factory=dict)


def read_table(path: Path) -> Table:
    """`file,seconds,engine,alone`: a file's measured seconds, whether it starts an engine (yes/no), and
    why it must run alone (empty when it need not). The row `*` is the default for a file not listed."""
    rows: dict[str, Row] = {}
    header = "the header is file,seconds,engine,alone"
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"{path}:1: no header; {header}")
        for column in ("file", "seconds", "engine", "alone"):
            if column not in reader.fieldnames:
                raise ValueError(f"{path}:1: no column {column}; {header}")
        for n, rec in enumerate(reader, start=2):
            engine = (rec.get("engine") or "").strip()
            if engine not in ("yes", "no"):
                raise ValueError(f"{path}:{n}: engine is {engine!r}; the column takes yes or no")
            text = (rec["seconds"] or "").strip()
            try:
                seconds = float(text)
            except ValueError:
                seconds = -1.0
            if not (math.isfinite(seconds) and seconds >= 0):
                raise ValueError(f"{path}:{n}: seconds is {text!r}; a number of seconds >= 0")
            rows[(rec["file"] or "").strip()] = Row(seconds, engine == "yes", (rec["alone"] or "").strip())
    if "*" not in rows:
        raise ValueError(f"{path}: no `*` row, the default for a file the table does not list")
    default = rows.pop("*")
    return Table(default, rows)


def plan(files: list[str], table: Table, jobs: int) -> list[Shard]:
    """Longest file first, each onto the shard with the least time so far. A file the table says must
    run alone goes to the shard `serial`, which runs after the others. In each shard the files that
    start no engine run first, so that their failures show early."""
    shards = [Shard(str(n + 1)) for n in range(max(1, jobs))]
    serial = Shard("serial", serial=True)
    for name in sorted(files, key=lambda f: (-table.row(f).seconds, f)):
        row = table.row(name)
        if row.alone:
            target = serial
            serial.reasons[name] = row.alone
        else:
            target = min(shards, key=lambda s: s.seconds)
        target.files.append(name)
        target.seconds += row.seconds
        if name not in table.rows:
            target.unknown.append(name)
    out = [s for s in shards if s.files] + ([serial] if serial.files else [])
    for shard in out:
        shard.files.sort(key=lambda f: (table.row(f).engine, table.row(f).seconds, f))
    return out


def find_files(root: Path, tests: str) -> list[str]:
    """pytest's own default, `python_files = test_*.py *_test.py`, under the tests folder."""
    base = root / tests
    found = {p for pattern in ("test_*.py", "*_test.py") for p in base.rglob(pattern)}
    return sorted(p.relative_to(root).as_posix() for p in found if "__pycache__" not in p.parts)


# -- the run ----------------------------------------------------------------------------------------


def summary_line(text: str) -> str | None:
    """pytest's summary, the last line of the log that is one, else None: a shard cut off has none. It is
    shown; whether the shard ended normally is judged on its end-of-session record (`ended`)."""
    for line in reversed(text.splitlines()):
        m = SUMMARY_RE.match(line.strip())
        if m:
            return m.group(1)
    return None


def ended(log: list[dict]) -> bool:
    """Whether pytest reached its end of session: the record `pytest_sessionfinish` writes."""
    return any("finished" in rec for rec in log)


def outcomes(logs: list[list[dict]]) -> dict[str, str]:
    """Each id's outcome from its reports, as pytest counts it: failed when a phase failed, xfailed or
    skipped when a phase was skipped, xpassed when its call passed under an xfail mark, else passed."""
    phases: dict[str, list[dict]] = {}
    for log in logs:
        for rec in log:
            if "id" in rec:
                phases.setdefault(rec["id"], []).append(rec)
    out = {}
    for i, recs in phases.items():
        if any(r.get("outcome") == "failed" for r in recs):
            out[i] = "failed"
        elif any(r.get("outcome") == "skipped" for r in recs):
            out[i] = "xfailed" if any(r.get("xfail") for r in recs) else "skipped"
        elif any(r.get("xfail") and r.get("when") == "call" for r in recs):
            out[i] = "xpassed"
        else:
            out[i] = "passed"
    return out


def compare(collected: list[str], ran: dict[str, list[str]]) -> tuple[list[str], list[str], list[str]]:
    """The ids 1 process collected against the ids the shards ran: missing, not collected, run 2 times."""
    counts: dict[str, int] = {}
    for ids in ran.values():
        for i in ids:
            counts[i] = counts.get(i, 0) + 1
    wanted = set(collected)
    missing = sorted(wanted - counts.keys())
    extra = sorted(counts.keys() - wanted)
    twice = sorted(i for i, n in counts.items() if n > 1)
    return missing, extra, twice


def kicad_config_source(env: dict) -> Path | None:
    """Where KiCad reads its configuration: $KICAD_CONFIG_HOME, else $XDG_CONFIG_HOME/kicad, else
    ~/.config/kicad. Each holds 1 folder per version (`10.0/`). None with no home folder (M299): there
    is nothing to copy, as where ~/.config/kicad is not there."""
    if env.get("KICAD_CONFIG_HOME"):
        return Path(env["KICAD_CONFIG_HOME"])
    xdg = env.get("XDG_CONFIG_HOME", "")
    try:
        base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".config"
    except (RuntimeError, KeyError):
        return None
    return base / "kicad"


def shard_env(name: str, work: Path, base: dict) -> dict:
    """A shard's environment: its own KiCad configuration folder (every kicad-cli run rewrites
    kicad_common.json there), its own log, and its name for the tests."""
    env = dict(base)
    folder = work / f"shard-{name}"
    env["KICAD_CONFIG_HOME"] = str(folder / "kicad")
    env["TESTSHARDS_LOG"] = str(folder / "log.jsonl")
    env["TESTSHARDS_SHARD"] = name
    env["PYTHONPATH"] = os.pathsep.join(p for p in (str(HERE), base.get("PYTHONPATH", "")) if p)
    return env


def shard_args(name: str, work: Path) -> list[str]:
    """pytest's options for a shard (a name that starts `pytest_` is a hook to pytest, which refuses
    one it does not know). Its own base folder for tmp_path, and no .pytest_cache: both are folders
    every pytest process would otherwise share (/tmp/pytest-of-<user>, whose old runs each process
    deletes as it starts, and .pytest_cache under the repository)."""
    return [
        "-q",
        "-p",
        "testshards",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        str(work / f"shard-{name}" / "tmp"),
    ]


def read_log(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # a line cut off by a kill; the ids it would name show as missing
    return out


@dataclass
class Started:
    shard: Shard
    proc: subprocess.Popen
    log: Path
    jsonl: Path
    start: float
    seconds: float = 0.0
    code: int | None = None


class Stopped(SystemExit):
    """A stop by SIGTERM or SIGHUP, raised in the runner so that its clean-up ends every shard: each shard
    runs in its own process group, which a signal to the runner's group does not reach."""

    def __init__(self, signum: int) -> None:
        super().__init__(128 + signum)
        self.signum = signum


STOPS = (signal.SIGTERM, signal.SIGHUP)


def _stop(signum, frame) -> None:
    """The first stop. Every later one is ignored: under `enginelock.py hold` the runner gets the signal
    twice, from its group and from the hold, and a second Stopped raised inside the clean-up would end it
    before it had ended and waited for every shard."""
    for s in STOPS:
        signal.signal(s, signal.SIG_IGN)
    raise Stopped(signum)


def start(shard: Shard, root: Path, work: Path, python: str, base: dict, procs: list) -> Started:
    folder = work / f"shard-{shard.name}"
    folder.mkdir(parents=True, exist_ok=True)
    env = shard_env(shard.name, work, base)
    source = kicad_config_source(base)
    if source is not None and source.is_dir():
        shutil.copytree(source, env["KICAD_CONFIG_HOME"], dirs_exist_ok=True)
    else:
        Path(env["KICAD_CONFIG_HOME"]).mkdir(parents=True, exist_ok=True)
    log = folder / "pytest.log"
    cmd = [python, "-m", "pytest", *shard_args(shard.name, work), *shard.files]
    with open(log, "w", encoding="utf-8") as out:
        proc = subprocess.Popen(
            cmd, cwd=root, env=env, stdout=out, stderr=subprocess.STDOUT, start_new_session=True
        )
        procs.append(proc)
    return Started(shard, proc, log, Path(env["TESTSHARDS_LOG"]), time.monotonic())


@dataclass
class Told:
    """What the gate has printed: the ids of its FAILED lines, and each reason by its shard, id and phase.
    The reasons past REASONS are counted in `cut`, not printed. `collected` holds the files whose error at
    collection a shard told, so that the collection in 1 process does not tell it again."""

    ids: set[str] = field(default_factory=set)
    reasons: set[tuple[str, str, str]] = field(default_factory=set)
    collected: set[str] = field(default_factory=set)
    shown: int = 0
    cut: int = 0


PHASES = {"setup": "an error at setup", "call": "failed at call", "teardown": "an error at teardown"}


def tell(told: Told, key: tuple[str, str, str], header: str, lines: list[str]) -> None:
    """Print 1 reason, its header and then its lines under `  | `, unless it was told or REASONS were."""
    if key in told.reasons:
        return
    told.reasons.add(key)
    if told.shown >= REASONS:
        told.cut += 1
        return
    told.shown += 1
    print(printable("\n".join([header, *(f"  | {line}" for line in lines)])), flush=True)


def open_test(log: list[dict]) -> str | None:
    """The test the shard started last and did not end (a setup record with no teardown), or None."""
    ends = {rec["id"] for rec in log if rec.get("when") == "teardown"}
    left = [rec["id"] for rec in log if rec.get("when") == "setup" and rec["id"] not in ends]
    return left[-1] if left else None


def ending(r: Started, log: list[dict]) -> str:
    """The reason block of a shard that has no failure's report to show: it ended before pytest's end of
    session (killed, crashed, cut off), or exited non-zero with no failed test. The test it started last
    and did not end, and the last TAIL lines of its output, where a crash writes its stack."""
    killed = r.code is not None and r.code < 0
    code = f"exit {r.code}, killed by signal {-r.code}" if killed else f"exit {r.code}"
    if ended(log):
        what = f"exited {r.code} and no test failed"
    else:
        what = f"ended with no report from pytest ({code})"
    left, done = open_test(log), [rec["id"] for rec in log if rec.get("when") == "teardown"]
    if left:
        where = f"the test it started last and did not end: {left}"
    elif done:
        where = f"the last test it ended: {done[-1]}"
    else:
        where = "it ended no test"
    text = r.log.read_text(encoding="utf-8", errors="replace").splitlines()
    # A crash's stack, as pytest's faulthandler writes it, starts at its `Fatal Python error` and puts the
    # test's own frame first: from there, its first HEAD and last TAIL lines.
    crash = [n for n, line in enumerate(text) if "Fatal Python error" in line]
    if crash:
        text = text[crash[-1] :]
        text[0] = text[0][text[0].index("Fatal Python error") :]
    lines = [f"  | {line}" for line in bounded(text, HEAD if crash else 0, TAIL)]
    header = f"why: shard {r.shard.name} {what}; {where}; the last lines of its output, {r.log}:"
    return "\n".join([header, *lines])


def scan(r: Started, told: Told) -> list[dict]:
    """Print what the shard's log holds that was not printed yet: each failed id's FAILED line, and each
    failure's or collection error's reason. Returns the log."""
    log = read_log(r.jsonl)
    for rec in log:
        if rec.get("outcome") == "failed" and rec["id"] not in told.ids:
            told.ids.add(rec["id"])
            at = time.monotonic() - r.start
            print(printable(f"FAILED {rec['id']} (shard {r.shard.name}) at {at:.0f} s"), flush=True)
        if rec.get("outcome") == "failed" and "why" in rec:
            when = rec.get("when", "")
            phase = PHASES.get(when, f"failed at {when}")
            header = f"why: {rec['id']}, {phase} (shard {r.shard.name}):"
            tell(told, (r.shard.name, rec["id"], when), header, rec["why"])
        if "collect_error" in rec:
            told.collected.add(rec["collect_error"])
            header = f"why: {rec['collect_error']} could not be collected (shard {r.shard.name}):"
            tell(told, (r.shard.name, rec["collect_error"], "collect"), header, rec.get("why", []))
    return log


def watch(running: list[Started], told: Told) -> None:
    """Wait for every shard; print each failure as it is logged, with what pytest reported for it, and each
    shard as it ends, with the end of its output when it has no failure's report to show."""
    while True:
        for r in running:
            scan(r, told)
            if r.code is None and r.proc.poll() is not None:
                r.code = r.proc.returncode
                r.seconds = time.monotonic() - r.start
                # Read again: the records the shard wrote between the scan and its exit.
                log = scan(r, told)
                last = summary_line(r.log.read_text(encoding="utf-8", errors="replace"))
                code = f"{r.code} (killed by signal {-r.code})" if r.code < 0 else str(r.code)
                ran = sum(1 for rec in log if rec.get("when") == "setup")
                print(
                    f"shard {r.shard.name}: exit {code}, {ran} tests, {r.seconds:.0f} s: "
                    f"{last or 'no summary line'}",
                    flush=True,
                )
                if not ended(log) or (r.code != 0 and not any("why" in rec for rec in log)):
                    print(ending(r, log), flush=True)
        if all(r.code is not None for r in running):
            return
        time.sleep(0.5)


def end_all(procs: list[subprocess.Popen]) -> None:
    """Kill the process group of each pytest still running (its engines are in it) and wait for it."""
    for proc in procs:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        proc.wait()


def earlier_logs(work: Path) -> list[Path]:
    """The logs a run appends to, when a folder already holds them."""
    if not work.is_dir():
        return []
    return [p for p in [work / "collect.jsonl", *work.glob("shard-*/log.jsonl")] if p.is_file()]


def run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    table = read_table(Path(args.table))
    files = find_files(root, args.tests)
    shards = plan(files, table, args.jobs)
    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="ee-verify-"))
    old = sorted(p.relative_to(work).as_posix() for p in earlier_logs(work))
    if old:
        # The logs are appended to: a second run would join the first run's ids with its own.
        print(
            f"--work {work} holds the logs of an earlier run ({', '.join(old[:3])}): name an empty "
            "folder, or remove that one",
            file=sys.stderr,
        )
        return 2
    work.mkdir(parents=True, exist_ok=True)
    base = dict(os.environ)

    print(f"tests: {len(files)} files in {len([s for s in shards if not s.serial])} shards, by {args.table}")
    for s in shards:
        print(f"  shard {s.name}: {len(s.files)} files, {s.seconds:.0f} s by the table")
        for name, why in s.reasons.items():
            print(f"    alone: {name}: {why}")
        for name in s.unknown:
            print(f"    not in the table: {name}, given the default {table.default.seconds:.0f} s")
    print(f"  logs: {work}", flush=True)

    wall = time.monotonic()
    collect_log = work / "collect.jsonl"
    collect_env = dict(base, TESTSHARDS_LOG=str(collect_log))
    collect_env["PYTHONPATH"] = os.pathsep.join(p for p in (str(HERE), base.get("PYTHONPATH", "")) if p)
    collect_env.pop("TESTSHARDS_SHARD", None)
    collect_out = work / "collect.log"
    collect_cmd = [args.python, "-m", "pytest", "--collect-only", "-q", "-p", "testshards"]
    collect_cmd += ["-p", "no:cacheprovider", args.tests]
    started: list[Started] = []
    told = Told()
    procs: list[subprocess.Popen] = []
    handlers = {s: signal.signal(s, _stop) for s in STOPS}
    try:
        with open(collect_out, "w", encoding="utf-8") as out:
            collect = subprocess.Popen(
                collect_cmd,
                cwd=root,
                env=collect_env,
                stdout=out,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            procs.append(collect)
        parallel = []
        for s in shards:
            if not s.serial:
                parallel.append(start(s, root, work, args.python, base, procs))
        started += parallel
        watch(parallel, told)
        for s in shards:
            if s.serial:
                alone = start(s, root, work, args.python, base, procs)
                started.append(alone)
                watch([alone], told)
        collect.wait()
    except BaseException as exc:
        end_all(procs)
        if isinstance(exc, Stopped):
            # A stop is often a CI time limit on a test that hangs: name the test each shard was running.
            for r in started:
                if r.code is None:
                    test = open_test(read_log(r.jsonl))
                    doing = f"was running {test}" if test else "was between tests"
                    print(printable(f"why: shard {r.shard.name} {doing} when stopped"), flush=True)
            print(
                f"stopped by signal {exc.signum}: {len(procs)} pytest processes started, none left running",
                flush=True,
            )
        raise
    finally:
        for s, h in handlers.items():
            signal.signal(s, h)
    wall = time.monotonic() - wall
    code = judge(started, collect.returncode, collect_log, collect_out, wall, told=told, work=work)
    # The shards' tmp_path folders of 1 whole run took 607 MB. A green run made its own folder and needs
    # nothing in it; a red run, or a folder the caller named, is kept for its logs.
    if code == 0 and not args.work:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"logs kept: {work}")
    return code


def judge(
    started: list[Started],
    collect_code: int,
    collect_log: Path,
    collect_out: Path,
    wall: float,
    told: Told | None = None,
    work: Path | None = None,
) -> int:
    told = told if told is not None else Told()
    red: list[str] = []
    logs = {r.shard.name: read_log(r.jsonl) for r in started}
    for r in started:
        if r.code != 0:
            red.append(f"shard {r.shard.name} exited {r.code}")
        if not ended(logs[r.shard.name]):
            red.append(f"shard {r.shard.name} ended before pytest's end of session (log: {r.log})")
    collect_records = read_log(collect_log)
    collected = [rec["collected"] for rec in collect_records if "collected" in rec]
    if collect_code != 0:
        tail = collect_out.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]
        red.append(f"the collection in 1 process exited {collect_code}: " + " | ".join(tail))
    for rec in collect_records:
        if "collect_error" in rec and rec["collect_error"] not in told.collected:
            header = f"why: {rec['collect_error']} could not be collected (the collection in 1 process):"
            tell(told, ("1 process", rec["collect_error"], "collect"), header, rec.get("why", []))
    ran = {name: [rec["id"] for rec in log if rec.get("when") == "setup"] for name, log in logs.items()}
    missing, extra, twice = compare(collected, ran)
    total = sum(len(v) for v in ran.values())
    print(
        f"ids: {len(collected)} collected in 1 process, {total} run in {len(started)} shards; "
        f"{len(missing)} missing, {len(extra)} not collected, {len(twice)} run 2 times"
    )
    for label, ids in (("missing", missing), ("not collected", extra), ("run 2 times", twice)):
        for i in ids[:20]:
            print(f"  {label}: {i}")
        if len(ids) > 20:
            print(f"  {label}: and {len(ids) - 20} more")
    if missing or extra or twice:
        red.append("the shards' ids are not the ids 1 process collects")

    # The same verdict, not only the same ids: a shard's environment (KICAD_CONFIG_HOME, PYTHONPATH,
    # TESTSHARDS_*) can turn a skipif or an xfail mark on that 1 process leaves off.
    alone = {rec["collected"]: rec for rec in collect_records if "collected" in rec}
    differ: list[str] = []
    for name, log in logs.items():
        for rec in log:
            mine = alone.get(rec.get("collected", ""))
            if mine is None or "marks" in rec or "marks" in mine:
                continue
            for kind in ("skip", "xfail"):
                if rec.get(kind) != mine.get(kind):
                    there = "none" if rec.get(kind) is None else f"{kind} {rec[kind]!r}"
                    here = "none" if mine.get(kind) is None else f"{kind} {mine[kind]!r}"
                    differ.append(f"{rec['collected']}: {there} in shard {name}, {here} in 1 process")
    for line in differ:
        print(f"  marks differ: {line}")
    if differ:
        word = "test whose" if len(differ) == 1 else "tests whose"
        red.append(f"{len(differ)} {word} skip or xfail marks differ between a shard and 1 process")
    unknown = any("marks" in rec for rec in collect_records)
    if unknown:
        print("  not judged: the skip and xfail marks (this pytest has no _pytest.skipping to evaluate them)")

    result = outcomes(list(logs.values()))
    counts = {k: sum(1 for v in result.values() if v == k) for k in OUTCOMES}
    print("outcomes: " + ", ".join(f"{counts[k]} {k}" for k in OUTCOMES))
    # A skip inside the test (pytest.skip, importorskip) is not in its marks: whether 1 process skips it
    # too is not known without running it there.
    by_shard = {i: name for name, ids in ran.items() for i in ids}
    reasons = {rec["id"]: rec.get("reason", "") for log in logs.values() for rec in log if "reason" in rec}
    marked = {rec["collected"] for log in logs.values() for rec in log if rec.get("skip") is not None}
    inside = sorted(i for i, v in result.items() if v == "skipped" and i not in marked)
    for i in inside:
        print(
            f"  not judged: {i}: skipped inside the test in shard {by_shard.get(i, '?')} "
            f"({reasons.get(i, '')!r}); 1 process did not run it"
        )

    per_file: dict[str, float] = {}
    where: dict[str, str] = {}
    for r in started:
        for rec in read_log(r.jsonl):
            if "id" in rec:
                f = rec["id"].split("::")[0]
                per_file[f] = per_file.get(f, 0.0) + float(rec.get("seconds") or 0.0)
                where[f] = r.shard.name
    print("slowest files:")
    for f, s in sorted(per_file.items(), key=lambda kv: -kv[1])[:10]:
        print(f"  {s:8.1f} s  {f} (shard {where[f]})")
    for r in started:
        print(f"shard {r.shard.name}: {r.seconds:.0f} s for {len(r.shard.files)} files")
    print(f"tests: {wall:.0f} s on the wall clock, {sum(per_file.values()):.0f} s of test time")
    if told.cut:
        where = f" under {work}" if work is not None else ""
        print(
            f"why: {told.cut} more failed tests' reports are not printed here (the gate prints the first "
            f"{REASONS}); each shard's whole report is its pytest.log{where}"
        )
    if red:
        print("TESTS RED: " + "; ".join(red))
        return 1
    tail = f"; {len(inside)} not judged (skipped inside the test)" if inside else ""
    print(f"TESTS GREEN: {total} tests in {len(started)} shards{tail}")
    return 0


def table_rows(table: Table, works: list[Path]) -> list[str]:
    """The table again, its seconds from the shards' logs of 1 or more runs: each file's mean over the
    runs that ran it, and `*` the mean of the files. Engine and alone stay as the table has them; a file
    new to the table takes the `*` row's engine."""
    runs: dict[str, list[float]] = {}
    for work in works:
        per: dict[str, float] = {}
        for log in sorted(Path(work).glob("shard-*/log.jsonl")):
            for rec in read_log(log):
                if "id" in rec:
                    f = rec["id"].split("::")[0]
                    per[f] = per.get(f, 0.0) + float(rec.get("seconds") or 0.0)
        for f, s in per.items():
            runs.setdefault(f, []).append(s)
    means = {f: sum(v) / len(v) for f, v in runs.items()}
    default = sum(means.values()) / len(means) if means else table.default.seconds
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["file", "seconds", "engine", "alone"])
    w.writerow(["*", f"{default:.1f}", "yes" if table.default.engine else "no", table.default.alone])
    for f in sorted(means, key=lambda f: (-round(means[f], 1), f)):
        row = table.rows.get(f, Row(0.0, table.default.engine, ""))
        w.writerow([f, f"{means[f]:.1f}", "yes" if row.engine else "no", row.alone])
    return out.getvalue().splitlines()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="testshards.py", description=(__doc__ or "").splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="run the tests in shards and join the verdict")
    p.add_argument("--root", default=".", help="the folder pytest runs in (the repository)")
    p.add_argument("--tests", default="tests", help="the tests folder, under the root")
    p.add_argument("--table", default="verify/shards.csv")
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 1, help="parallel shards (processors)")
    p.add_argument("--python", default=sys.executable, help="the Python that has pytest")
    p.add_argument("--work", help="folder for the shards' logs (default: a new temporary folder)")
    t = sub.add_parser("table", help="print the table with the seconds of the runs whose logs are named")
    t.add_argument("--table", default="verify/shards.csv")
    t.add_argument("works", nargs="+", help="the --work folders of 1 or more runs")
    args = ap.parse_args(argv)
    try:
        table = read_table(Path(args.table))
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    if args.cmd == "table":
        print("\n".join(table_rows(table, [Path(w) for w in args.works])))
        return 0
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
