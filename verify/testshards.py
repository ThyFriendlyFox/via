#!/usr/bin/env python3
"""The health gate's tests in several pytest processes at once, joined into 1 verdict.

`run` splits the test files into shards by the time `verify/shards.csv` gives each, starts 1 pytest per
shard side by side, then the files that must run alone, and joins the results. The gate is red when a
shard exits non-zero, when a shard's log ends with no summary line, or when the ids the shards ran are
not exactly the ids 1 pytest process collects. It prints each shard's time and the 10 slowest files.

Loaded into pytest with `-p testshards`, the same module writes each collected id and each test report
to the file `TESTSHARDS_LOG` names, 1 JSON object to a line. Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import json
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


# -- the pytest side: loaded with `-p testshards` ---------------------------------------------------


def _log(records: list[dict]) -> None:
    path = os.environ.get("TESTSHARDS_LOG")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def pytest_collection_finish(session) -> None:
    _log([{"collected": item.nodeid} for item in session.items])


def pytest_runtest_logreport(report) -> None:
    _log([{"id": report.nodeid, "when": report.when, "outcome": report.outcome, "seconds": report.duration}])


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
    with open(path, encoding="utf-8", newline="") as fh:
        for n, rec in enumerate(csv.DictReader(fh), start=2):
            engine = (rec.get("engine") or "").strip()
            if engine not in ("yes", "no"):
                raise ValueError(f"{path}:{n}: engine is {engine!r}; the column takes yes or no")
            rows[rec["file"].strip()] = Row(
                float(rec["seconds"]), engine == "yes", (rec["alone"] or "").strip()
            )
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
    """pytest's summary when it is the last line of the log, else None: a shard cut off has none."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None
    m = SUMMARY_RE.match(lines[-1])
    return m.group(1) if m else None


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


def kicad_config_source(env: dict) -> Path:
    """Where KiCad reads its configuration: $KICAD_CONFIG_HOME, else $XDG_CONFIG_HOME/kicad, else
    ~/.config/kicad. Each holds 1 folder per version (`10.0/`)."""
    if env.get("KICAD_CONFIG_HOME"):
        return Path(env["KICAD_CONFIG_HOME"])
    xdg = env.get("XDG_CONFIG_HOME", "")
    base = Path(xdg) if xdg and Path(xdg).is_absolute() else Path.home() / ".config"
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


def start(shard: Shard, root: Path, work: Path, python: str, base: dict) -> Started:
    folder = work / f"shard-{shard.name}"
    folder.mkdir(parents=True, exist_ok=True)
    env = shard_env(shard.name, work, base)
    source = kicad_config_source(base)
    if source.is_dir():
        shutil.copytree(source, env["KICAD_CONFIG_HOME"], dirs_exist_ok=True)
    else:
        Path(env["KICAD_CONFIG_HOME"]).mkdir(parents=True, exist_ok=True)
    log = folder / "pytest.log"
    cmd = [python, "-m", "pytest", *shard_args(shard.name, work), *shard.files]
    with open(log, "w", encoding="utf-8") as out:
        proc = subprocess.Popen(
            cmd, cwd=root, env=env, stdout=out, stderr=subprocess.STDOUT, start_new_session=True
        )
    return Started(shard, proc, log, Path(env["TESTSHARDS_LOG"]), time.monotonic())


def watch(running: list[Started], said: set[str]) -> None:
    """Wait for every shard; print each failure as it is logged and each shard as it ends."""
    while True:
        for r in running:
            for rec in read_log(r.jsonl):
                if rec.get("outcome") == "failed" and rec["id"] not in said:
                    said.add(rec["id"])
                    print(f"FAILED {rec['id']} (shard {r.shard.name})", flush=True)
            if r.code is None and r.proc.poll() is not None:
                r.code = r.proc.returncode
                r.seconds = time.monotonic() - r.start
                last = summary_line(r.log.read_text(encoding="utf-8", errors="replace"))
                code = f"{r.code} (killed by signal {-r.code})" if r.code < 0 else str(r.code)
                ran = sum(1 for rec in read_log(r.jsonl) if rec.get("when") == "setup")
                print(
                    f"shard {r.shard.name}: exit {code}, {ran} tests, {r.seconds:.0f} s: "
                    f"{last or 'no summary line'}",
                    flush=True,
                )
        if all(r.code is not None for r in running):
            return
        time.sleep(0.5)


def run(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    table = read_table(Path(args.table))
    files = find_files(root, args.tests)
    shards = plan(files, table, args.jobs)
    work = Path(args.work) if args.work else Path(tempfile.mkdtemp(prefix="ee-verify-"))
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
    with open(collect_out, "w", encoding="utf-8") as out:
        collect = subprocess.Popen(
            [
                args.python,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "testshards",
                "-p",
                "no:cacheprovider",
            ]
            + [args.tests],
            cwd=root,
            env=collect_env,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    started: list[Started] = []
    said: set[str] = set()
    try:
        parallel = [start(s, root, work, args.python, base) for s in shards if not s.serial]
        started += parallel
        watch(parallel, said)
        for s in shards:
            if s.serial:
                alone = start(s, root, work, args.python, base)
                started.append(alone)
                watch([alone], said)
        collect.wait()
    except BaseException:
        for r in started:
            if r.proc.poll() is None:
                os.killpg(r.proc.pid, signal.SIGKILL)
        if collect.poll() is None:
            os.killpg(collect.pid, signal.SIGKILL)
        raise
    wall = time.monotonic() - wall
    code = judge(started, collect.returncode, collect_log, collect_out, wall)
    # The shards' tmp_path folders of 1 whole run took 607 MB. A green run made its own folder and needs
    # nothing in it; a red run, or a folder the caller named, is kept for its logs.
    if code == 0 and not args.work:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"logs kept: {work}")
    return code


def judge(
    started: list[Started], collect_code: int, collect_log: Path, collect_out: Path, wall: float
) -> int:
    red: list[str] = []
    for r in started:
        if r.code != 0:
            red.append(f"shard {r.shard.name} exited {r.code}")
        if summary_line(r.log.read_text(encoding="utf-8", errors="replace")) is None:
            red.append(f"shard {r.shard.name} ended with no summary line (log: {r.log})")
    collected = [rec["collected"] for rec in read_log(collect_log) if "collected" in rec]
    if collect_code != 0:
        tail = collect_out.read_text(encoding="utf-8", errors="replace").splitlines()[-5:]
        red.append(f"the collection in 1 process exited {collect_code}: " + " | ".join(tail))
    ran = {
        r.shard.name: [rec["id"] for rec in read_log(r.jsonl) if rec.get("when") == "setup"] for r in started
    }
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
    if red:
        print("TESTS RED: " + "; ".join(red))
        return 1
    print(f"TESTS GREEN: {total} tests in {len(started)} shards")
    return 0


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
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    sys.exit(main())
