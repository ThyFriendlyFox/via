"""Tests for `workcenter bench`, the routing benchmark (ROADMAP item 5, "A routing benchmark and a
second router"): the connections a board asks for, the share a route joined, the DRC's count, the
router each board takes, the table, and the command's exit codes.

The engine tests route a 4-part board with FreeRouting and skip when it or KiCad is absent.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import kicadgen  # noqa: E402
import routebench  # noqa: E402

CLI = ROOT / "tools" / "workcenter"
LIBS = kicadgen.SYMBOL_DIR / "Device.kicad_sym"
JAR = Path("/opt/workcenters/ee/freerouting/freerouting.jar")

needs_libs = pytest.mark.skipif(not LIBS.is_file(), reason="KiCad symbol libraries are not installed")
needs_kicad = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
needs_router = pytest.mark.skipif(
    not JAR.is_file() or shutil.which("java") is None, reason="FreeRouting is not installed"
)


def run_cli(*args: object) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout + proc.stderr


BOARD = """(kicad_pcb (version 20241229) (generator "kicadgen")
  (net 0 "")
  (net 1 "/A")
  (net 2 "/B")
  (net 3 "/C")
  (footprint "R" (at 1 1)
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "/A"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net 2 "/B")))
  (footprint "U" (at 5 5)
    (pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net 1 "/A"))
    (pad "2" smd rect (at 1 0) (size 1 1) (layers "F.Cu") (net 1 "/A"))
    (pad "3" smd rect (at 2 0) (size 1 1) (layers "F.Cu") (net 2 "/B"))
    (pad "4" smd rect (at 3 0) (size 1 1) (layers "F.Cu") (net 3 "/C"))
    (pad "5" smd rect (at 4 0) (size 1 1) (layers "F.Cu") (net 0 ""))
    (pad "6" smd rect (at 5 0) (size 1 1) (layers "F.Cu") (net 4 "unconnected-(U-NC-Pad6)"))
    (pad "" np_thru_hole circle (at 6 0) (size 1 1) (drill 1) (layers "*.Cu")))
)
"""


def test_board_connections_are_each_nets_pads_less_one(tmp_path):
    """/A has 3 pads (R.1, U.1, U.2): 2 connections. /B has 2 (R.2, U.3): 1. /C has 1 pad, the empty
    net and the unconnected pad's net 1 each, the hole none: 0. Total 2 + 1 = 3."""
    pcb = tmp_path / "x.kicad_pcb"
    pcb.write_text(BOARD, encoding="utf-8")
    assert routebench.board_connections(pcb) == 3


def test_drc_counts_read_errors_warnings_and_unconnected(tmp_path):
    """2 violations of severity error, 1 warning, 3 unconnected items (errors), 1 parity warning:
    errors 2 + 3 = 5, warnings 1 + 1 = 2, unconnected 3."""
    report = tmp_path / "drc.json"
    report.write_text(
        json.dumps(
            {
                "violations": [{"severity": "error"}, {"severity": "error"}, {"severity": "warning"}],
                "unconnected_items": [{"severity": "error"}] * 3,
                "schematic_parity": [{"severity": "warning"}],
            }
        ),
        encoding="utf-8",
    )
    assert routebench.drc_counts(report) == {"errors": 5, "warnings": 2, "unconnected": 3}


def test_routed_share_is_the_connections_the_drc_finds_joined():
    """8 connections, 2 unconnected: 8 - 2 = 6 joined, 6 / 8 = 75.0 %."""
    run = {"status": "judged", "connections": 8, "unconnected": 2}
    assert routebench.routed(run) == (6, 8)
    assert routebench.share_text(run) == "6/8 (75.0 %)"


def judged(router: str, seconds: float, unconnected: int, errors: int | None = None) -> dict:
    return {
        "board": "b",
        "router": router,
        "status": "judged",
        "seconds": seconds,
        "connections": 10,
        "unconnected": unconnected,
        "drc_errors": unconnected if errors is None else errors,
    }


def test_the_default_router_stays_when_it_is_the_only_one_run():
    router, why = routebench.choose([judged("fr-a", 100.0, 0)], "fr-a")["b"]
    assert router == "fr-a"
    assert why == "the only router run on this board"


def test_a_slower_router_does_not_become_the_default():
    """Both join 10 of 10; the other takes 120 s where the default takes 100 s: 120 > 100."""
    router, why = routebench.choose([judged("fr-a", 100.0, 0), judged("fr-b", 120.0, 0)], "fr-a")["b"]
    assert router == "fr-a"
    assert why == "no other router joined as many connections with as few DRC errors in as little time"


def test_a_router_that_leaves_more_unrouted_does_not_become_the_default():
    """The other is faster, 50 s against 100 s, but leaves 1 of 10 open where the default leaves 0."""
    router, _ = routebench.choose([judged("fr-a", 100.0, 0), judged("fr-b", 50.0, 1)], "fr-a")["b"]
    assert router == "fr-a"


def test_a_router_that_is_no_worse_and_faster_takes_the_board():
    """The other joins 10 of 10 with 0 DRC errors in 80 s; the default the same in 100 s."""
    router, why = routebench.choose([judged("fr-a", 100.0, 0), judged("fr-b", 80.0, 0)], "fr-a")["b"]
    assert router == "fr-b"
    assert why == "joins 10/10 (100.0 %) with 0 DRC errors in 80.0 s; fr-a 10/10 (100.0 %), 0 in 100.0 s"


def test_no_judged_run_keeps_the_default_and_says_so():
    stopped = {"board": "b", "router": "fr-a", "status": "time limit", "seconds": 300.0}
    router, why = routebench.choose([stopped], "fr-a")["b"]
    assert router == "fr-a"
    assert why == "no run finished: the workcenter's router stays"


def test_a_table_row_names_every_number_of_its_run():
    run = {
        **judged("fr-a", 41.25, 2, errors=5),
        "commands": ["workcenter design d.py --route", "workcenter drc ."],
        "output_bytes": 3120,
    }
    assert routebench.table_row(run) == "| b | fr-a | 41.2 | 8/10 (80.0 %) | 5 | 2 | 3120 | judged |"


def test_a_stopped_run_is_not_judged_in_the_table():
    run = {"board": "b", "router": "fr-a", "status": "time limit", "seconds": 300.0, "why": "300 s"}
    assert (
        routebench.table_row(run)
        == "| b | fr-a | 300.0 | not judged | not judged | - | - | time limit: 300 s |"
    )


def test_bench_refuses_a_design_file_that_is_not_there(tmp_path):
    code, out = run_cli("bench", tmp_path / "missing.py", "--out", tmp_path / "bench")
    assert code == 1
    assert out.strip().splitlines()[-1] == f"bench: no design file {tmp_path / 'missing.py'}"


def test_bench_with_no_design_rebuilds_the_table_from_the_runs_in_its_folder(tmp_path):
    out = tmp_path / "bench"
    (out / "b" / "fr-a").mkdir(parents=True)
    run = {**judged("fr-a", 41.25, 0), "commands": ["x", "y"], "output_bytes": 100}
    (out / "b" / "fr-a" / "run.json").write_text(json.dumps(run), encoding="utf-8")
    code, text = run_cli("bench", "--out", out, "--router", f"fr-a={JAR}")
    assert code == 0, text
    table = (out / "bench.md").read_text(encoding="utf-8")
    assert "| b | fr-a | 41.2 | 10/10 (100.0 %) | 0 | 2 | 100 | judged |" in table
    assert "- b: fr-a, the only router run on this board" in table
    assert f"wrote {out / 'bench.md'}" in text


def test_a_router_whose_jar_is_not_there_is_not_run(tmp_path):
    design = tmp_path / "design.py"
    design.write_text("", encoding="utf-8")
    missing = tmp_path / "none.jar"
    code, out = run_cli("bench", design, "--out", tmp_path / "bench", "--router", f"fr-x={missing}")
    assert code == 2, out
    assert f"bench {tmp_path.parent.name}/{tmp_path.name} fr-x: not run: no router at {missing}" in out


def bus_design() -> str:
    """Six nets straight across between 2 headers, and R5 beside J3 on the 2 nets E1 and E2."""
    return (
        "import sys, uuid\n"
        f"sys.path.insert(0, {str(ROOT / 'tools')!r})\n"
        "import kicadgen\n"
        "H6 = 'Connector_PinHeader_2.54mm:PinHeader_1x06_P2.54mm_Vertical'\n"
        "H2 = 'Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical'\n"
        "def build():\n"
        "    d = kicadgen.Design(name='bus', namespace=uuid.UUID(int=4242),\n"
        "                        outline=(100.0, 100.0, 130.0, 122.0))\n"
        "    pins = {str(i + 1): f'S{i}' for i in range(6)}\n"
        "    d.add('J1', 'Connector_Generic:Conn_01x06', 'L', H6, sch_at=(30, 30),\n"
        "          pcb_at=(103.0, 106.0), nets=pins)\n"
        "    d.add('J2', 'Connector_Generic:Conn_01x06', 'R', H6, sch_at=(90, 30),\n"
        "          pcb_at=(127.0, 106.0), nets=pins)\n"
        "    d.add('J3', 'Connector_Generic:Conn_01x02', 'E', H2, sch_at=(60, 80), pcb_at=(113.73, 101.9),\n"
        "          pcb_rot=90, nets={'1': 'E1', '2': 'E2'})\n"
        "    d.add('R5', 'Device:R', '1k', 'Resistor_SMD:R_0603_1608Metric', sch_at=(60, 60),\n"
        "          pcb_at=(115.0, 110.0), nets={'1': 'E1', '2': 'E2'})\n"
        "    return d\n"
    )


@needs_libs
@needs_kicad
@needs_router
def test_bench_routes_a_board_and_records_its_numbers(tmp_path):
    """6 nets S0 to S5 with 2 pads each: 6 connections; E1 and E2 with 2 pads each: 2. Total 8. The
    route joins all 8, so the DRC finds 0 unconnected and 8/8 is 100.0 %. The commands are 2: the
    route and the DRC."""
    folder = tmp_path / "bus" / "v1"
    folder.mkdir(parents=True)
    (folder / "design.py").write_text(bus_design(), encoding="utf-8")
    out = tmp_path / "bench"
    code, text = run_cli(
        "bench", folder / "design.py", "--out", out, "--time-limit", 200, "--threads", 1, "--passes", 10
    )
    assert code == 0, text
    run = json.loads((out / "bus-v1" / "freerouting-1.9.0" / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "judged", run
    assert (run["connections"], run["unconnected"], run["drc_errors"]) == (8, 0, 0), run
    assert len(run["commands"]) == 2 and run["output_bytes"] > 0, run
    assert "| bus/v1 | freerouting-1.9.0 |" in (out / "bench.md").read_text(encoding="utf-8")


@needs_libs
@needs_router
def test_a_route_past_the_time_limit_is_stopped_and_not_judged(tmp_path):
    folder = tmp_path / "bus" / "v1"
    folder.mkdir(parents=True)
    (folder / "design.py").write_text(bus_design(), encoding="utf-8")
    out = tmp_path / "bench"
    code, text = run_cli("bench", folder / "design.py", "--out", out, "--time-limit", 1)
    assert code == 2, text
    assert "bus/v1 freerouting-1.9.0: stopped at the time limit (1 s); not judged" in text
    run = json.loads((out / "bus-v1" / "freerouting-1.9.0" / "run.json").read_text(encoding="utf-8"))
    assert run["status"] == "time limit"
