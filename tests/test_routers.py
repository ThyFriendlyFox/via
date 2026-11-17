"""Tests for the routers behind `workcenter design --route` (ROADMAP item 5, "a second router").

Every rule around a route is the workcenter's, not the router's. Each test here runs the whole
`workcenter design --route` with a stand-in router (tests/routers/standin.py, called as Java is) that
writes a known output, and holds 1 rule of the list in .claude/skills/autoroute/SKILL.md ("The rules
around a route"). None of them needs a real router. The tests of a real FreeRouting 2.5.0 skip with its
name when it is absent; FreeRouting 1.9.0's own tests are in test_routing.py, test_routeorder.py,
test_routebench.py and test_kicadgen.py.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import kicadgen  # noqa: E402
import routers  # noqa: E402

CLI = ROOT / "tools" / "workcenter"
STANDIN = ROOT / "tests" / "routers" / "standin.py"
LIBS = kicadgen.SYMBOL_DIR / "Device.kicad_sym"
R0603 = "Resistor_SMD:R_0603_1608Metric"

needs_libs = pytest.mark.skipif(not LIBS.is_file(), reason="KiCad symbol libraries are not installed")
needs_kicad = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
FR2 = routers.ROUTERS["freerouting2"]
needs_freerouting2 = pytest.mark.skipif(
    bool(FR2.absent()), reason=f"FreeRouting 2.5.0 (freerouting2) is not installed: {FR2.absent()}"
)


def score_line(unrouted: int, violations: int, headless: bool = True) -> str:
    """A log line with FreeRouting 2.5.0's own count, in its own formats: the jar of install.sh (SHA256
    f6f51bb0...de3c7) read with `javap -c -p -constants`. `FRLogger.formatScore(float, int, int)` writes
    "<score> (<n> unrouted and <m> violation[s])", "violation" when m is 1. The headless job thread
    (`RoutingJobSchedulerActionThread$1`) logs "Auto-routing stage %s started with %d unrouted nets,
    completed in %.2f seconds, final score: %s, using %.2f total CPU seconds, %.2f GB total allocated, and
    %.1f MB peak heap usage."; the window's worker (`GuiRoutingJobWorker`) logs "Auto-routing was
    completed in %.2f seconds with the score of %s."."""
    score = f"812.34 ({unrouted} unrouted and {violations} violation{'' if violations == 1 else 's'})"
    if headless:
        return (
            f"Auto-routing stage autorouter started with 3 unrouted nets, completed in 0.10 seconds, final "
            f"score: {score}, using 0.20 total CPU seconds, 0.10 GB total allocated, and 50.0 MB peak heap "
            "usage."
        )
    return f"Auto-routing was completed in 0.10 seconds with the score of {score}."


# The log line of a route that left nothing open, as FreeRouting 2.5.0 writes it headless.
DONE = score_line(0, 0)


def board(track: bool = False, zone: bool = False) -> kicadgen.Design:
    """3 nets A, B and C, each from the right pad of R1, R3, R5 to the left pad of R2, R4, R6, 10 mm
    apart in rows 7 mm apart: 3 connections. The outer pads' nets P1 to P6 have 1 pad each and ask
    for none. `track`: A drawn by hand. `zone`: C poured on F.Cu."""
    import uuid

    d = kicadgen.Design(name="rows", namespace=uuid.UUID(int=6060), outline=(100.0, 100.0, 130.0, 125.0))
    for i, (net, y) in enumerate((("A", 105.0), ("B", 112.0), ("C", 119.0))):
        left, right = f"R{2 * i + 1}", f"R{2 * i + 2}"
        d.add(left, "Device:R", "1k", R0603, sch_at=(30, 30 + 20 * i), pcb_at=(110.0, y),
              nets={"1": f"P{2 * i + 1}", "2": net})  # fmt: skip
        d.add(right, "Device:R", "1k", R0603, sch_at=(60, 30 + 20 * i), pcb_at=(120.0, y),
              nets={"1": net, "2": f"P{2 * i + 2}"})  # fmt: skip
    if track:
        d.track("A", [d.pad_at("R1", "2"), d.pad_at("R2", "1")])
    if zone:
        d.zone("C", layers=("F.Cu",))
    return d


ENDS = {"A": ("R1", "R2"), "B": ("R3", "R4"), "C": ("R5", "R6")}


def session(nets: list[str], d: kicadgen.Design | None = None) -> str:
    """A Specctra session with 1 straight wire per net, from the left part's pad 2 to the right part's
    pad 1, on F.Cu at the board's track width, in units of 0.1 um with y up (resolution um 10)."""
    d = d or board()
    u = 10000
    wires = []
    for net in nets:
        a, b = (d.pad_at(ENDS[net][0], "2"), d.pad_at(ENDS[net][1], "1"))
        points = " ".join(str(round(v * u)) for v in (a[0], -a[1], b[0], -b[1]))
        path = f"F.Cu {round(d.track_width * u)} {points}"
        wires.append(f'(net "{d.pcb_net_name(net)}" (wire (path {path})))')
    return f'(session "rows" (routes (resolution um 10) (network_out {" ".join(wires)})))\n'


def standin(tmp_path: Path, java_version: str = "21.0.13", **plan) -> dict[str, str]:
    """The environment that makes the workcenter run the stand-in as FreeRouting 1.9.0 and 2.5.0: a
    `java` that runs standin.py, and a jar that holds the plan."""
    java = tmp_path / "java"
    java.write_text(
        f"#!{sys.executable}\nimport runpy\nrunpy.run_path({str(STANDIN)!r}, run_name='__main__')\n"
    )
    java.chmod(java.stat().st_mode | stat.S_IXUSR)
    jar = tmp_path / "standin.jar"
    plan.setdefault("record", str(tmp_path / "record.jsonl"))
    plan.setdefault("log", DONE)
    jar.write_text(json.dumps(plan), encoding="utf-8")
    env = dict(os.environ, JAVA=str(java), FREEROUTING_JAR=str(jar), DISPLAY=":0")
    env.update(FREEROUTING2_JAVA=str(java), FREEROUTING2_JAR=str(jar), STANDIN_JAVA_VERSION=java_version)
    return env


def calls(tmp_path: Path) -> list[dict]:
    path = tmp_path / "record.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def design_file(tmp_path: Path, **kw) -> Path:
    path = tmp_path / "rows" / "design.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "import sys\n"
        f"sys.path.insert(0, {str(ROOT / 'tests')!r})\n"
        "from test_routers import board\n"
        f"def build():\n    return board(**{kw!r})\n",
        encoding="utf-8",
    )
    return path


def route(tmp_path: Path, env: dict, *extra: object, design: Path | None = None) -> tuple[int, str]:
    design = design or design_file(tmp_path)
    proc = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "design",
            str(design),
            "--route",
            "--out",
            str(tmp_path / "out"),
            *map(str, extra),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=300,
    )
    return proc.returncode, proc.stdout + proc.stderr


def routed_line(text: str) -> str:
    return next((ln.strip() for ln in text.splitlines() if ln.startswith("  routed: ")), "")


# ------------------------------------------------------------------ before the route


@needs_libs
def test_the_router_is_handed_the_dsn_of_this_design_not_one_left_in_the_folder(tmp_path):
    """Rule 1. A DSN an earlier run left in build/route is written over: the router reads, byte for
    byte, the DSN of the design as this command built it. Every rule of the DSN (planes, fixed wiring,
    grown holes, net classes) reaches the router through it."""
    env = standin(tmp_path, ses=session(["A", "B", "C"]))
    stale = tmp_path / "out" / "build" / "route" / "rows.dsn"
    stale.parent.mkdir(parents=True)
    stale.write_text("(pcb stale)", encoding="utf-8")
    code, text = route(tmp_path, env)
    assert code == 0, text
    [call] = calls(tmp_path)
    assert call["dsn_path"] == str(stale)
    assert call["dsn"] == board().dsn()


@needs_libs
@pytest.mark.parametrize("router", ["freerouting", "freerouting2"])
def test_a_rules_file_beside_the_dsn_is_removed_before_the_router_runs(tmp_path, router):
    """Rule 1. FreeRouting 2.5.0 reads a `<board>.rules` beside the DSN when none is named, and its
    rules (clearances, net classes, vias) are applied over the DSN's: its command_line_arguments.md,
    the `-de` entry. A rows.rules left in build/route is removed before the router starts, for each
    router, so the DSN alone carries the rules."""
    env = standin(tmp_path, java_version="25.0.5", ses=session(["A", "B", "C"]))
    rules = tmp_path / "out" / "build" / "route" / "rows.rules"
    rules.parent.mkdir(parents=True)
    rules.write_text("(rules PCB rows (rule (clearance 1)))", encoding="utf-8")
    code, text = route(tmp_path, env, "--router", router)
    assert code == 0, text
    [call] = calls(tmp_path)
    assert call["rules_beside"] is False
    assert not rules.exists()


@needs_libs
def test_a_session_an_earlier_run_left_is_never_read(tmp_path):
    """Rule 2. The folder holds a session with all 3 wires; the router exits 0 and writes none. The
    old session is removed before the run, so the route fails: nothing is merged and no board is
    written."""
    env = standin(tmp_path, ses=None, exit=0)
    old = tmp_path / "out" / "build" / "route" / "rows.ses"
    old.parent.mkdir(parents=True)
    old.write_text(session(["A", "B", "C"]), encoding="utf-8")
    code, text = route(tmp_path, env)
    assert code == 1, text
    assert "route failed: FreeRouting exited 0; see" in text
    assert routed_line(text) == ""
    assert not (tmp_path / "out" / "rows.kicad_pcb").exists()


@needs_libs
def test_an_absent_router_skips_the_route_and_names_it(tmp_path):
    """Rule 3. No jar: the route is skipped as an absent engine, exit 2, and the line names the router
    and where its jar was looked for."""
    env = standin(tmp_path)
    env["FREEROUTING_JAR"] = str(tmp_path / "none.jar")
    code, text = route(tmp_path, env)
    assert code == 2, text
    assert f"route skipped: engine missing: freerouting: no jar at {tmp_path / 'none.jar'}" in text
    assert calls(tmp_path) == []


@needs_libs
def test_an_absent_router_writes_no_board_over_a_routed_one(tmp_path):
    """Rule 3. A first route writes A, B and C: 3 segments. The same command with `--router
    freerouting2` on Java 21 skips the route (exit 2) and writes nothing: the board still holds the
    3 segments of the first route."""
    env = standin(tmp_path, java_version="21.0.13", ses=session(["A", "B", "C"]))
    assert route(tmp_path, env)[0] == 0
    pcb = tmp_path / "out" / "rows.kicad_pcb"
    before = pcb.read_bytes()
    code, text = route(tmp_path, env, "--router", "freerouting2")
    assert code == 2, text
    assert pcb.read_bytes() == before
    assert len(kicadgen.board_copper(pcb)["segments"]) == 3


@needs_libs
def test_order_and_seed_are_refused_before_the_router_runs(tmp_path):
    """Rule 4. `--order` takes no `--seed`: the command stops at its arguments, exit 2, and the router
    is never called."""
    env = standin(tmp_path)
    (tmp_path / "old.kicad_pcb").write_text("", encoding="utf-8")
    code, text = route(tmp_path, env, "--order", "--seed", tmp_path / "old.kicad_pcb")
    assert code == 2, text
    assert "design --order cannot take --seed" in text
    assert calls(tmp_path) == []


# ------------------------------------------------------------------ what the router is handed


@needs_libs
@needs_kicad
def test_a_poured_net_goes_to_the_router_as_a_plane_and_not_as_a_net_to_route(tmp_path):
    """Rule 5. C is poured on F.Cu: the DSN names it as a plane, and the router routes A and B."""
    env = standin(tmp_path, ses=session(["A", "B"]))
    code, text = route(tmp_path, env, design=design_file(tmp_path, zone=True))
    assert code == 0, text
    [call] = calls(tmp_path)
    assert '(plane "/C" (polygon F.Cu' in call["dsn"]
    assert routed_line(text).startswith("routed: 2 segments, 0 vias, 0 unrouted")


@needs_libs
def test_hand_copper_goes_to_the_router_as_fixed_wiring(tmp_path):
    """Rule 6. A is drawn by hand: its track reaches the router typed `fix`, which the router may not
    move or remove."""
    env = standin(tmp_path, ses=session(["A", "B", "C"]))
    code, text = route(tmp_path, env, design=design_file(tmp_path, track=True))
    assert code == 0, text
    [call] = calls(tmp_path)
    fixed = [ln for ln in call["dsn"].splitlines() if "(type fix)" in ln]
    assert len(fixed) == 1 and '(net "/A")' in fixed[0], fixed


@needs_libs
def test_the_routers_echo_of_hand_copper_is_dropped(tmp_path):
    """Rule 7. The session echoes A's hand track and adds B and C: the merge keeps 2 segments, not 3,
    and the board holds A's track once (1 hand + 2 routed = 3 segments)."""
    env = standin(tmp_path, ses=session(["A", "B", "C"]))
    code, text = route(tmp_path, env, design=design_file(tmp_path, track=True))
    assert code == 0, text
    assert routed_line(text).startswith("routed: 2 segments, 0 vias")
    copper = kicadgen.board_copper(tmp_path / "out" / "rows.kicad_pcb")
    assert sorted(s[0] for s in copper["segments"]) == ["/A", "/B", "/C"]


@needs_libs
def test_a_seed_goes_to_the_router_held_as_shove_fixed(tmp_path):
    """Rule 8. A first route writes A, B and C; a second route seeded from that board hands the router
    the 3 tracks typed `shove_fixed`: pushed aside, never ripped up."""
    env = standin(tmp_path, ses=session(["A", "B", "C"]))
    assert route(tmp_path, env)[0] == 0
    first = tmp_path / "first.kicad_pcb"
    first.write_bytes((tmp_path / "out" / "rows.kicad_pcb").read_bytes())
    code, text = route(tmp_path, env, "--seed", first)
    assert code == 0, text
    seeded = [ln for ln in calls(tmp_path)[1]["dsn"].splitlines() if "(type shove_fixed)" in ln]
    assert sorted(re.search(r'\(net "([^"]+)"\)', ln).group(1) for ln in seeded) == ["/A", "/B", "/C"]
    assert "the new route kept" in text


@needs_libs
def test_an_ordered_route_runs_the_router_once_per_stage_with_the_nets_so_far(tmp_path):
    """Rule 9. With C poured, stage 1 (pours) is C; no part is fine pitch and no net ends in a pair's
    ending, so stage 2 is the rest: A and B. 2 router runs, each on its own DSN; the second DSN lists
    A, B and C's plane, the first does not list A or B."""
    env = standin(tmp_path, ses='(session "rows" (routes (resolution um 10) (network_out)))\n')
    code, text = route(tmp_path, env, "--order", design=design_file(tmp_path, zone=True))
    assert code == 0, text
    runs = calls(tmp_path)
    assert [Path(c["dsn_path"]).name for c in runs] == ["rows.1-pours.dsn", "rows.2-rest.dsn"]
    assert '(net "/A"' not in runs[0]["dsn"] and '(net "/A"' in runs[1]["dsn"]
    assert "stage 1 pours: 1 nets" in text and "stage 2 rest: 2 nets" in text


# ------------------------------------------------------------------ the run


@needs_libs
def test_the_passes_threads_and_dialog_wait_are_the_workcenters(tmp_path):
    """Rule 10. `--passes 7 --threads 3`: the router gets -mp 7, -mt 3 and -dct 0 (no 20 s wait on a
    dialog). Without --threads it gets no -mt and picks its own."""
    env = standin(tmp_path, ses=session(["A", "B", "C"]))
    assert route(tmp_path, env, "--passes", 7, "--threads", 3)[0] == 0
    assert route(tmp_path, env, "--passes", 7)[0] == 0
    first, second = (c["argv"] for c in calls(tmp_path))
    assert first[first.index("-mp") + 1] == "7" and first[first.index("-dct") + 1] == "0"
    assert first[first.index("-mt") + 1] == "3"
    assert "-mt" not in second


@needs_libs
def test_a_router_past_the_time_limit_is_stopped_with_its_children_and_nothing_is_read(tmp_path):
    """Rule 11. The router (and a child of it, as Java under xvfb-run) would run 60 s; the limit is
    2 s. The command ends well before 60 s, says so in 1 line, exits 1 and writes no board."""
    env = standin(tmp_path, ses=session(["A", "B", "C"]), sleep=60)
    t0 = time.monotonic()
    code, text = route(tmp_path, env, "--timeout", 2)
    took = time.monotonic() - t0
    assert code == 1, text
    assert took < 40, took
    assert "route failed: FreeRouting 1.9.0 stopped at the time limit (2 s)" in text
    assert not (tmp_path / "out" / "rows.kicad_pcb").exists()


@needs_libs
@pytest.mark.skipif(shutil.which("xvfb-run") is None, reason="xvfb-run is not installed")
def test_freerouting_1_9_runs_under_xvfb_without_a_display(tmp_path):
    """Rule 12. FreeRouting 1.9.0 draws a window even when it routes alone: with no DISPLAY the
    workcenter starts it under xvfb-run, which gives it one."""
    env = standin(tmp_path, ses=session(["A", "B", "C"]))
    env.pop("DISPLAY")
    assert route(tmp_path, env)[0] == 0
    assert calls(tmp_path)[0]["display"]


@needs_libs
def test_the_routers_output_is_kept_in_the_route_log(tmp_path):
    """Rule 13. What the router prints is in build/route/freerouting.log, and the routed line names it."""
    env = standin(tmp_path, ses=session(["A", "B", "C"]), log=f"standin says hello\n{DONE}")
    code, text = route(tmp_path, env)
    log = tmp_path / "out" / "build" / "route" / "freerouting.log"
    assert code == 0, text
    assert "standin says hello" in log.read_text(encoding="utf-8")
    assert routed_line(text).endswith(f"({log})")


@needs_libs
def test_a_router_that_fails_is_1_line_and_writes_nothing(tmp_path):
    """Rule 14. The router exits 3 after writing a session: the route failed, in 1 line that names
    the exit code and the log; nothing is merged and no board is written."""
    env = standin(tmp_path, ses=session(["A", "B", "C"]), exit=3)
    code, text = route(tmp_path, env)
    assert code == 1, text
    log = tmp_path / "out" / "build" / "route" / "freerouting.log"
    assert f"  route failed: FreeRouting exited 3; see {log}" in text.splitlines()
    assert "Traceback" not in text
    assert not (tmp_path / "out" / "rows.kicad_pcb").exists()


# ------------------------------------------------------------------ what is read back


@needs_libs
@pytest.mark.parametrize("headless", [True, False], ids=["headless", "window"])
def test_the_routers_own_count_of_open_connections_is_the_verdict(tmp_path, headless):
    """Rule 15. The router writes A only and logs its score with "(2 unrouted and 0 violations)", in
    either of FreeRouting 2.5.0's 2 lines (score_line): 3 connections less the 1 made is 2, which the
    log says. 1 segment, 2 unrouted, exit 1, and the last line says red with the 2."""
    env = standin(tmp_path, java_version="25.0.5", ses=session(["A"]), log=score_line(2, 0, headless))
    code, text = route(tmp_path, env, "--router", "freerouting2")
    assert code == 1, text
    assert routed_line(text).startswith("routed: 1 segments, 0 vias, 2 unrouted")
    assert "red: 2 unrouted" in text.splitlines()[-1]


@needs_libs
def test_the_last_stage_line_is_the_routers_count(tmp_path):
    """Rule 15. FreeRouting 2.5.0 logs a score line per stage it runs; the board it writes is the last
    stage's. A first line says 3 unrouted, the last 0: the count is 0 and the run exits 0."""
    log = f"{score_line(3, 0)}\n{score_line(0, 0)}"
    env = standin(tmp_path, java_version="25.0.5", ses=session(["A", "B", "C"]), log=log)
    code, text = route(tmp_path, env, "--router", "freerouting2")
    assert code == 0, text
    assert routed_line(text).startswith("routed: 3 segments, 0 vias, 0 unrouted")


@needs_libs
def test_the_routers_count_of_violations_is_printed_as_not_judged(tmp_path):
    """Rule 15. The log says "(0 unrouted and 1 violation)": the count of open connections is 0 and
    the run exits 0; the router's 1 violation is printed in 1 line as not judged, since the DRC judges
    clearances on the written board (rule 18)."""
    env = standin(tmp_path, java_version="25.0.5", ses=session(["A", "B", "C"]), log=score_line(0, 1))
    code, text = route(tmp_path, env, "--router", "freerouting2")
    assert code == 0, text
    assert (
        "  router violations: 1, counted by FreeRouting 2.5.0; not judged here: the DRC judges clearances"
        in text.splitlines()
    )


@needs_libs
def test_a_route_that_joined_nothing_counts_every_connection(tmp_path):
    """Rule 16. No count in the log and no wire in the session: A, B and C have 2 pads each, so
    3 connections are open (2 - 1 each), exit 1."""
    env = standin(tmp_path, ses='(session "rows" (routes (resolution um 10) (network_out)))\n', log="")
    code, text = route(tmp_path, env)
    assert code == 1, text
    assert routed_line(text).startswith("routed: 0 segments, 0 vias, 3 unrouted")


@needs_libs
def test_with_copper_and_no_count_the_drc_decides(tmp_path):
    """Rule 17. No count in the log, A routed: the command claims no count ("DRC decides") and exits
    0; the DRC is the judge of what is open."""
    env = standin(tmp_path, ses=session(["A"]), log="")
    code, text = route(tmp_path, env)
    assert code == 0, text
    assert routed_line(text).startswith("routed: 1 segments, 0 vias, DRC decides")


@needs_libs
@needs_kicad
def test_the_drc_decides_what_stayed_open(tmp_path):
    """Rule 18. On the board the stand-in left with A only, KiCad's DRC finds B and C open: 2
    unconnected items (3 connections less the 1 made)."""
    env = standin(tmp_path, ses=session(["A"]), log="")
    assert route(tmp_path, env)[0] == 0
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", "drc", str(tmp_path / "out")],
        capture_output=True,
        text=True,
        check=False,
    )
    gate = json.loads(proc.stdout)
    assert gate[0]["details"]["counts"]["unconnected_items"]["error"] == 2, gate


# ------------------------------------------------------------------ the second router


@needs_libs
def test_freerouting2_runs_headless_with_its_settings_in_the_route_folder(tmp_path):
    """Rule 19. `--router freerouting2` runs the jar of FREEROUTING2_JAR on the Java of
    FREEROUTING2_JAVA (here Java 25.0.5) with the same -de, -do, -mp and -dct, plus `-da` (no usage
    data), `--gui.enabled=false` (no window, so no xvfb-run even with no DISPLAY) and its settings and
    log in build/route/freerouting2. Every other rule is the same code: the route merges A, B, C."""
    env = standin(tmp_path, java_version="25.0.5", ses=session(["A", "B", "C"]))
    env.pop("DISPLAY")
    code, text = route(tmp_path, env, "--router", "freerouting2")
    assert code == 0, text
    [call] = calls(tmp_path)
    argv = call["argv"]
    assert argv[:2] == ["-jar", env["FREEROUTING2_JAR"]]
    assert "-da" in argv and "--gui.enabled=false" in argv
    assert f"--user_data_path={tmp_path / 'out' / 'build' / 'route' / 'freerouting2'}" in argv
    assert call["display"] is None
    assert routed_line(text).startswith("routed: 3 segments, 0 vias, 0 unrouted")


@needs_libs
def test_freerouting2_on_a_java_older_than_25_is_an_absent_engine(tmp_path):
    """Rule 20. FreeRouting 2.5.0's classes are of version 69, which Java 21 cannot read: on Java 21
    the route is skipped as an absent engine (exit 2) and the router is never started."""
    env = standin(tmp_path, java_version="21.0.13", ses=session(["A", "B", "C"]))
    code, text = route(tmp_path, env, "--router", "freerouting2")
    assert code == 2, text
    assert f"engine missing: freerouting2: needs Java 25; {env['FREEROUTING2_JAVA']} is Java 21" in text
    assert calls(tmp_path) == []


def test_a_router_the_workcenter_does_not_know_is_refused(tmp_path):
    """`--router` takes the names of the routers the workcenter knows, and nothing else."""
    proc = subprocess.run(
        [sys.executable, str(CLI), "design", str(tmp_path / "d.py"), "--route", "--router", "nope"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 2
    assert "invalid choice: 'nope'" in proc.stderr


def test_bench_names_a_router_by_its_name_and_does_not_run_an_absent_one(tmp_path):
    """`workcenter bench --router freerouting2` takes the router by name; absent, the run is not run,
    its line says why, and the bench exits 2."""
    design = tmp_path / "x" / "design.py"
    design.parent.mkdir()
    design.write_text("", encoding="utf-8")
    env = dict(os.environ, FREEROUTING2_JAR=str(tmp_path / "none.jar"))
    proc = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "bench",
            str(design),
            "--out",
            str(tmp_path / "b"),
            "--router",
            "freerouting2",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert f"freerouting2: not run: freerouting2: no jar at {tmp_path / 'none.jar'}" in proc.stdout


def test_doctor_has_a_row_for_the_second_router(tmp_path):
    """`workcenter doctor` names freerouting2 with its jar's path. Where install.sh never put it (no
    folder under WORKCENTER_ROOT) the row is advisory: a workcenter without it is not degraded."""
    env = dict(os.environ, WORKCENTER_ROOT=str(tmp_path))
    env.pop("FREEROUTING2_JAR", None)
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", "doctor"], capture_output=True, text=True, env=env, check=False
    )
    row = json.loads(proc.stdout)["checks"]["freerouting2"]
    assert row["ok"] is False and row["advisory"] is True, row
    assert row["path"] == str(tmp_path / "freerouting2" / "freerouting.jar")
    assert "freerouting2" not in json.loads(proc.stdout)["degraded"]


# ------------------------------------------------------------------ install.sh


def shell_function(text: str, name: str) -> str:
    """The body of a top-level bash function of install.sh, from `name() {` to the `}` at column 0."""
    m = re.search(rf"^{name}\(\) \{{\n(.*?)^\}}$", text, re.S | re.M)
    assert m, f"install.sh has no function {name}"
    return m.group(1)


def network_step_problems(text: str, step: str, sha_var: str, version_var: str) -> list[str]:
    """What a download step of install.sh breaks of the file's own rules for a network step (PROCESSES.md
    P2, and step_openems as written): every curl fails on an HTTP error (-f), retries (--retry), has a
    connect timeout and a whole-transfer limit (--max-time) and is not silenced by a redirect to
    /dev/null; a `log` line names each download before it; the file is checked against a pinned SHA256
    (64 hex digits in `sha_var`) before it is moved into place or unpacked; the version is pinned (no
    `latest`); a failure goes through freerouting2_fail, which warns, or dies with REQUIRE_FREEROUTING2=1."""
    body = shell_function(text, step)
    lines = body.splitlines()
    problems = []
    curls = [i for i, ln in enumerate(lines) if re.search(r"\bcurl\b", ln)]
    if not curls:
        problems.append(f"{step}: no download")
    for i in curls:
        ln = lines[i]
        flags = {
            "-f": r"\s-[a-zA-Z]*f[a-zA-Z]*\s",  # alone or in a cluster such as -fsSL
            "--retry": r"\s--retry\s",
            "--connect-timeout": r"\s--connect-timeout\s",
            "--max-time": r"\s--max-time\s",
        }
        for flag, pattern in flags.items():
            if not re.search(pattern, ln):
                problems.append(f"{step}: curl without {flag}")
        if "/dev/null" in ln:
            problems.append(f"{step}: curl output hidden")
        if not any(re.match(r"\s*log ", lines[k]) for k in range(max(0, i - 3), i)):
            problems.append(f"{step}: no log line before the download")
    check = next((i for i, ln in enumerate(lines) if f"${{{sha_var}}}" in ln and "sha256sum -c" in ln), None)
    use = next((i for i, ln in enumerate(lines) if re.match(r"\s*(mv|tar) ", ln)), None)
    if check is None:
        problems.append(f"{step}: no check against {sha_var}")
    elif use is not None and use < check:
        problems.append(f"{step}: the file is used before its checksum is checked")
    if "freerouting2_fail" not in body:
        problems.append(f"{step}: a failure does not go through freerouting2_fail")
    pins = dict(re.findall(r'^([A-Z0-9_]+)="([^"$]*)"$', text, re.M))
    if not re.fullmatch(r"[0-9a-f]{64}", pins.get(sha_var, "")):
        problems.append(f"{sha_var} is not a pinned SHA256")
    if not re.fullmatch(r"\d+(\.\d+)+(\+\d+)?", pins.get(version_var, "")):
        problems.append(f"{version_var} is not a pinned version")
    return problems


@pytest.mark.parametrize(
    ("step", "sha_var", "version_var"),
    [
        ("step_java25", "JAVA25_SHA256", "JAVA25_VERSION"),
        ("step_freerouting2", "FREEROUTING2_SHA256", "FREEROUTING2_VERSION"),
    ],
)
def test_each_new_install_step_keeps_the_files_rules_for_a_network_step(step, sha_var, version_var):
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert network_step_problems(text, step, sha_var, version_var) == []


def test_install_sh_reads_as_bash_and_installs_the_second_router_only_when_asked():
    """`bash -n` reads the file; the full install runs the 2 steps only under INSTALL_FREEROUTING2=1, and
    `--freerouting2` runs them alone, Java first: the jar is of no use without it."""
    text = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert subprocess.run(["bash", "-n", str(ROOT / "install.sh")], check=False).returncode == 0
    main = shell_function(text, "main")
    assert main.count("if step_java25; then step_freerouting2 || true; fi") == 2
    assert 'if [[ "$INSTALL_FREEROUTING2" == "1" ]]; then' in main
    assert 'if [[ "${1:-}" == "--freerouting2" ]]; then' in main


def test_the_install_rules_find_a_step_that_breaks_them():
    """The check itself: a step whose curl has no --max-time, no log line and no checksum is named for
    each of the 3."""
    text = (
        'FREEROUTING2_SHA256="abc"\nFREEROUTING2_VERSION="latest"\n'
        'step_x() {\n  curl -fsSL --retry 3 --connect-timeout 20 -o a "$U"\n  mv a b\n}\n'
    )
    assert network_step_problems(text, "step_x", "FREEROUTING2_SHA256", "FREEROUTING2_VERSION") == [
        "step_x: curl without --max-time",
        "step_x: no log line before the download",
        "step_x: no check against FREEROUTING2_SHA256",
        "step_x: a failure does not go through freerouting2_fail",
        "FREEROUTING2_SHA256 is not a pinned SHA256",
        "FREEROUTING2_VERSION is not a pinned version",
    ]


# ------------------------------------------------------------------ the real second router


@needs_libs
@needs_kicad
@needs_freerouting2
def test_freerouting2_routes_the_board_and_the_drc_finds_nothing_open(tmp_path):
    """The 3 rows with FreeRouting 2.5.0 itself: it joins the 3 connections, its log counts 0 open,
    and KiCad's DRC finds 0 unconnected items."""
    env = dict(os.environ)
    code, text = route(tmp_path, env, "--router", "freerouting2", "--passes", 10, "--timeout", 600)
    assert code == 0, text
    assert ", 0 unrouted," in routed_line(text)
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", "drc", str(tmp_path / "out")],
        capture_output=True,
        text=True,
        check=False,
    )
    gate = json.loads(proc.stdout)
    assert gate[0]["details"]["counts"]["unconnected_items"]["error"] == 0, gate
