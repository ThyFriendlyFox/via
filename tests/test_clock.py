"""tools/clock.py: a command reads the day once, at its start, and a test pins it through SOURCE_DATE_EPOCH.

The fault this holds (2026-11-18): a CI run of `main` started at 23:53 UTC and failed at 00:14 UTC.
tests/test_doctools.py read the day when it was loaded, and the command wrote its report after
midnight. Two clocks play that night here without waiting for it: a pytest plugin that moves the clock
from 2026-11-17 23:59 to 2026-11-18 00:01 once the files are collected, and a clock that moves 2
minutes on at each reading, for a command that reads the day more than once in 1 run.

The 2 moments as SOURCE_DATE_EPOCH, worked out by hand: 1970 to 2025 is 56 years with 14 leap years
(1972 to 2024), 56 x 365 + 14 = 20454 days; 2026-01-01 to 2026-11-18 is 31+28+31+30+31+30+31+31+30+31
= 304 days and 17 more, 321; 20454 + 321 = 20775 days, x 86400 = 1794960000 s at 2026-11-18 00:00 UTC.
00:01 is 1794960060, and 23:59 the day before is 1794960000 - 60 = 1794959940.
"""

from __future__ import annotations

import datetime
import http.server
import json
import os
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
sys.path.insert(0, str(ROOT / "tools"))
import clock  # noqa: E402

BEFORE = "2026-11-17T23:59:00+00:00"
AFTER = "2026-11-18T00:01:00+00:00"
BEFORE_EPOCH = "1794959940"
AFTER_EPOCH = "1794960060"
needs_kicad = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")

# A clock a test sets: datetime.date and datetime.datetime are swapped for subclasses whose today() and
# now() read `read()`, an aware UTC moment. The process runs with TZ=UTC, so its local day is the UTC day.
FAKE = """
import datetime

_DATE, _DATETIME = datetime.date, datetime.datetime


def install(read):
    class Day(_DATE):
        @classmethod
        def today(cls):
            return read().astimezone().date()

    class Moment(_DATETIME):
        @classmethod
        def now(cls, tz=None):
            t = read()
            return t.astimezone(tz) if tz is not None else t.astimezone().replace(tzinfo=None)

        @classmethod
        def today(cls):
            return cls.now()

        @classmethod
        def utcnow(cls):
            return read().replace(tzinfo=None)

    datetime.date, datetime.datetime = Day, Moment
"""
# The night of the fault for a pytest run: 23:59 while the files load, 00:01 once they are collected.
MIDNIGHT = f'''
import datetime
import fakeclock

state = {{"now": datetime.datetime.fromisoformat("{BEFORE}")}}
fakeclock.install(lambda: state["now"])


def pytest_collection_finish(session):
    state["now"] = datetime.datetime.fromisoformat("{AFTER}")
'''
# A command under a clock that moves on 2 minutes at each reading, from 23:59: its 1st reading is
# 2026-11-17 and its 2nd 2026-11-18.
TICKING = f'''
import datetime, runpy, sys
import fakeclock

start = datetime.datetime.fromisoformat("{BEFORE}")
count = [0]


def read():
    count[0] += 1
    return start + datetime.timedelta(minutes=2 * (count[0] - 1))


fakeclock.install(read)
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name="__main__")
'''


def clocked(tmp_path: Path) -> dict:
    """The environment of a process with the fake clock on its path: TZ=UTC, nothing pinned."""
    (tmp_path / "fakeclock.py").write_text(FAKE, encoding="utf-8")
    (tmp_path / "midnight.py").write_text(MIDNIGHT, encoding="utf-8")
    (tmp_path / "ticking.py").write_text(TICKING, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(tmp_path), "TZ": "UTC"}
    env.pop(clock.ENV, None)
    return env


def across_midnight(tmp_path: Path, test: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", "midnight", test],
        capture_output=True,
        text=True,
        check=False,
        cwd=tmp_path,
        env=clocked(tmp_path),
        timeout=300,
    )


def ticking(tmp_path: Path, *args: object) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(tmp_path / "ticking.py"), str(CLI), "--json", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        env=clocked(tmp_path),
        timeout=300,
    )


# ------------------------------------------------------------ the clock


def test_the_variable_pins_the_moment_and_the_day_in_utc(monkeypatch):
    """1794960060 s is 2026-11-18 00:01:00 UTC (the sum in the module's docstring)."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", AFTER_EPOCH)
    assert clock.moment() == datetime.datetime.fromisoformat(AFTER)
    assert clock.today() == datetime.date(2026, 11, 18)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", BEFORE_EPOCH)
    assert clock.today() == datetime.date(2026, 11, 17)


@pytest.mark.parametrize(
    "value", ["", "1.5", "17e8", " 1794960060", "1794960060s", "١٧٩", "99999999999999999"]
)
def test_a_malformed_variable_is_refused_on_1_line(monkeypatch, value):
    """The specification's own words: an integer, with no fractional component, as `date +%s` prints
    it; a malformed value SHOULD end the build with a non-zero code (SOURCE_DATE_EPOCH specification,
    revision 1.1, section SOURCE_DATE_EPOCH). The last value is past the year 9999 that Python dates
    reach."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", value)
    with pytest.raises(clock.Malformed, match="SOURCE_DATE_EPOCH") as caught:
        clock.today()
    assert "\n" not in str(caught.value)


def test_a_run_reads_the_clock_once_and_lets_go_at_its_end(monkeypatch):
    """A clock that moves 2 minutes at each reading from 23:59: 2 readings inside 1 run give 23:59
    both, and the day after the run is the clock's next reading, 00:01."""
    monkeypatch.delenv("SOURCE_DATE_EPOCH", raising=False)
    start = datetime.datetime.fromisoformat(BEFORE)
    readings = iter(start + datetime.timedelta(minutes=2 * n) for n in range(10))
    monkeypatch.setattr(clock, "_wall", lambda: next(readings))
    with clock.run():
        assert clock.today() == datetime.date(2026, 11, 17)
        assert clock.today() == datetime.date(2026, 11, 17)
        assert clock.moment() == start
    assert clock.moment() == datetime.datetime.fromisoformat(AFTER)


def test_a_command_with_a_malformed_variable_exits_1_and_says_why(tmp_path):
    env = {**os.environ, "SOURCE_DATE_EPOCH": "tomorrow"}
    proc = subprocess.run(
        [sys.executable, str(CLI), "now", str(tmp_path), "--item", "x", "--status", "Todo"],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    assert proc.returncode == 1
    assert proc.stderr.strip().splitlines() == [
        "SOURCE_DATE_EPOCH is 'tomorrow', not a whole number of seconds since 1970-01-01 00:00:00 UTC "
        "(SOURCE_DATE_EPOCH specification, revision 1.1, section SOURCE_DATE_EPOCH)"
    ]


def test_only_the_clock_module_reads_the_clock():
    """Every day or time a tool writes, prints or compares comes through tools/clock.py: no other file
    of tools/, verify/ or site/ calls date.today, datetime.now, time.time or their kin."""
    files = [*ROOT.glob("tools/*.py"), CLI, *ROOT.glob("site/*.py"), *ROOT.glob("verify/*.py")]
    found = [
        f"{path.relative_to(ROOT)}:{line}"
        for path in files
        if path.name != "clock.py"
        for line in clock.clock_calls(path.read_text(encoding="utf-8"))
    ]
    assert found == []
    shells = [p for p in ROOT.glob("verify/*.sh") if "$(date" in p.read_text(encoding="utf-8")]
    assert shells == []


def test_the_reader_of_calls_finds_each_spelling_and_tells_load_from_call():
    source = (
        "import datetime, time\n"
        "from datetime import date\n"
        "from time import time as now\n"
        "A = datetime.date.today()\n"  # 4: at load
        "B = date.today()\n"  # 5: at load
        "C = now()\n"  # 6: at load
        "def f(x=time.strftime('%Y')):\n"  # 7: a default is evaluated at load
        "    return datetime.datetime.now(datetime.UTC)\n"  # 8: at a call
        "class K:\n"
        "    D = time.time()\n"  # 10: a class body runs at load
        "    def g(self):\n"
        "        return time.monotonic()\n"  # a duration, no day or time of day
        "E = clock.today()\n"  # 13: at load, through this module: still the day of the load
        "def h():\n"
        "    return clock.moment()\n"  # the way a tool reads it
    )
    assert clock.clock_calls(source) == [4, 5, 6, 7, 8, 10]
    assert clock.clock_calls(source, at_load=True) == [4, 5, 6, 7, 10, 13]


# ------------------------------------------------------------ the fault of 2026-11-18


def test_the_gates_report_test_passes_when_midnight_falls_between_its_load_and_its_command(tmp_path):
    """The test that failed on CI, run with 2026-11-17 23:59 while its file loads and 2026-11-18 00:01
    when the command writes the report."""
    test = f"{ROOT / 'tests' / 'test_doctools.py'}::test_gates_report_writes_its_blocks_and_keeps_the_prose"
    proc = across_midnight(tmp_path, test)
    assert proc.returncode == 0, proc.stdout[-3000:]
    assert proc.stdout.strip().splitlines()[-1].startswith("1 passed")


def test_the_midnight_plugin_fails_a_test_that_reads_the_day_when_it_loads(tmp_path):
    """The plugin is no pass by itself: a file that keeps the day of its load, as test_doctools.py did,
    fails under it, 1 failed."""
    (tmp_path / "test_kept_day.py").write_text(
        "import datetime\n\nTODAY = datetime.date.today().isoformat()\n\n\n"
        "def test_the_day_is_the_day_of_the_load():\n"
        "    assert datetime.date.today().isoformat() == TODAY\n",
        encoding="utf-8",
    )
    proc = across_midnight(tmp_path, str(tmp_path / "test_kept_day.py"))
    assert proc.returncode == 1
    assert "assert '2026-11-18' == '2026-11-17'" in proc.stdout
    assert proc.stdout.strip().splitlines()[-1].startswith("1 failed")


class Site(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 (the handler's name is http.server's)
        body = f"%PDF-1.4 a note made up for the tests at {self.path}\n".encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def test_references_fetch_files_every_document_of_1_run_under_1_time(tmp_path):
    """2 documents fetched under a clock that moves 2 minutes at each reading: the run reads it once,
    at 23:59, and both ledger records say 2026-11-17T23:59Z, not 23:59 and 00:01."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    docs = [
        {
            "id": doc_id,
            "kind": "application note",
            "maker": "Acme, a maker made up for the tests",
            "number": doc_id.upper(),
            "title": "A note made up for the tests",
            "revision": "Rev. A",
            "url": f"{base}/{doc_id}.pdf",
            "sha256": digit * 64,
            "read": "2026-11-17",
        }
        for doc_id, digit in (("an-1", "1"), ("an-2", "2"))
    ]
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"documents": docs}), encoding="utf-8")
    try:
        proc = ticking(tmp_path, "references", "fetch", "--index", index, "--to", tmp_path / "refs")
    finally:
        server.shutdown()
    assert proc.returncode == 1, proc.stdout + proc.stderr  # both changed: the index names other hashes
    ledger = json.loads((tmp_path / "refs" / "ledger.json").read_text(encoding="utf-8"))["documents"]
    assert {doc_id: rec["at"] for doc_id, rec in ledger.items()} == {
        "an-1": "2026-11-17T23:59Z",
        "an-2": "2026-11-17T23:59Z",
    }


@needs_kicad
def test_costs_judges_every_board_of_1_run_on_1_day(tmp_path):
    """`costs` prices each board with its own procure run. Every price was checked STALE_DAYS (90) days
    before 2026-11-17: 2026-11-17 - 90 days = 2026-08-19 (Nov 17 to Oct 18, Oct 18 to Sep 18 and Sep 18
    to Aug 19 are 30 days each). On 2026-11-17 the age is 90 and no price is old; on 2026-11-18 it is 91
    and all 3 are. Under a clock that moves 2 minutes at each reading, both boards are judged on the day
    the run started: no price to check again on either."""
    cli = clock_cli()
    checked = (datetime.date(2026, 11, 17) - datetime.timedelta(days=cli.STALE_DAYS)).isoformat()
    assert checked == "2026-08-19"
    repo = tmp_path / "repo"
    for version in ("v0.1", "v0.2"):
        shutil.copytree(BOARDS / "pass-rc-divider", repo / version, ignore=shutil.ignore_patterns("sim"))
    head = "Value,Footprint,Qty,Manufacturer,MPN,Supplier,SKU,Pack,Breaks,Stock,Checked,URL,Note"
    rows = [
        "100n,Capacitor_SMD:C_0603_1608Metric,,Samsung,CL10B104KB8NNNC,Digi-Key,1276-1000-1-ND,,1:0.10,100",
        "Conn_01x03,Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical,,Sullins,PREC003SAAN-RC,"
        "Digi-Key,35-PREC003SAAN-RC-ND,,1:0.10,100",
        "10k,Resistor_SMD:R_0603_1608Metric,,Yageo,RC0603FR-0710KL,Digi-Key,311-10.0KHRCT-ND,,1:0.10,100",
    ]
    (repo / "parts").mkdir()
    (repo / "parts" / "catalog.csv").write_text(
        "\n".join([head, *(f"{row},{checked},," for row in rows)]) + "\n", encoding="utf-8"
    )
    proc = ticking(tmp_path, "costs", repo)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    (record,) = json.loads(proc.stdout)
    boards = record["details"]["boards"]
    assert [b.split(":")[0] for b in boards] == ["v0.1", "v0.2"]
    assert not any("prices to check again" in b for b in boards), boards


def clock_cli():
    import importlib.machinery
    import types

    loader = importlib.machinery.SourceFileLoader("workcenter_cli", str(CLI))
    module = types.ModuleType("workcenter_cli")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module  # dataclasses look the defining module up here
    loader.exec_module(module)
    return module
