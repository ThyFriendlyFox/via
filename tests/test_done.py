"""One definition of done (user round 1, C): a project with a `ratings.json` is done when the gates are
GREEN and its ratings are held. `workcenter gates` says on 1 line whether they are, `--strict` does not
end GREEN while they are not, and `workcenter next` says nothing is left only when both hold.

Held: `build/ratings/report.json` says exactly `RATINGS HELD`, and no input of that run (the schematic,
`ratings.json`, `parts.csv`, the facts) is newer than the record. A stale record is not held.

Most tests run `cmd_gates` with the 4 gates replaced by functions that return a pass, so they need no
engine; the ratings record is written by hand as a ratings run leaves it. 1 test runs the real gates
and the real `ratings` on the fixture `pass-ratings-node`, and skips without kicad-cli.
"""

from __future__ import annotations

import argparse
import importlib.machinery
import json
import os
import shutil
import subprocess
import sys
import time
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
sys.path.insert(0, str(ROOT / "tools"))
import guide  # noqa: E402

needs_kicad = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
GATES = ("erc", "drc", "sim", "export")
NOT_ASKED = "RATINGS not asked for: no ratings.json beside the schematic"


def load_cli():
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_done", str(CLI))
    module = types.ModuleType("workcenter_cli_done")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module  # dataclasses look the defining module up here
    loader.exec_module(module)
    return module


def node(tmp_path: Path) -> Path:
    """The fixture `pass-ratings-node` without its build folder: a schematic, ratings.json, parts.csv."""
    proj = tmp_path / "node"
    shutil.copytree(BOARDS / "pass-ratings-node", proj, ignore=shutil.ignore_patterns("build"))
    return proj


def rated(proj: Path, verdict: str | None, status: str = "pass", summary: str = "") -> None:
    """The record a ratings run leaves, a moment after the project's files."""
    folder = proj / "build" / "ratings"
    folder.mkdir(parents=True, exist_ok=True)
    details = {"failures": [], "warnings": [], **({"verdict": verdict} if verdict else {})}
    record = {"gate": "ratings", "status": status, "summary": summary, "details": details}
    (folder / "report.json").write_text(json.dumps({**record, "artifacts": [], "seconds": 0.0}), "utf-8")
    later = time.time() + 5
    os.utime(folder / "report.json", (later, later))


def gates(proj: Path, capsys, *, strict: bool = False, fail: str = "", report: Path | None = None):
    """`workcenter gates` with each gate a pass (or `fail` failing): the exit code and the lines."""
    cli = load_cli()

    def gate(name):
        def run(project, out, **_kw):
            status = "fail" if name == fail else "pass"
            return cli.Result(name, status, "made up", {"failures": [], "warnings": []})

        return run

    for name in GATES:
        setattr(cli, f"gate_{name}", gate(name))
    cli.tool_version = lambda *_a, **_k: "10.0.7"
    args = argparse.Namespace(
        project=str(proj), out=None, strict=strict, step=False, fab=None, report=report, json=False
    )
    code = cli.cmd_gates(args)
    return code, capsys.readouterr().out.splitlines()


# ------------------------------------------------------------- the acceptance test


def test_gates_strict_on_open_ratings_is_not_green_and_names_ratings(tmp_path, capsys):
    """The medium user's board: every gate passes, and `ratings` left 3 parts not judged. `gates
    --strict` ends RED with exit 1, and the line above the verdict names `workcenter ratings`."""
    proj = node(tmp_path)
    rated(proj, "RATINGS HELD, 3 NOT JUDGED")
    code, lines = gates(proj, capsys, strict=True)
    assert code == 1
    assert lines[-2] == f"RATINGS not held: 3 not judged (workcenter ratings {proj})"
    assert lines[-1].startswith("RED (ratings not held): node  report ")
    assert not any(line.startswith("GREEN") for line in lines)
    # without --strict the run is GREEN with the open ratings counted as its 1 warning, never bare
    code, lines = gates(proj, capsys)
    assert code == 0 and lines[-1].startswith("GREEN with 1 warning: node  report ")
    assert lines[-2] == f"RATINGS not held: 3 not judged (workcenter ratings {proj})"


# ------------------------------------------------------------- each kind of record


@pytest.mark.parametrize(
    ("verdict", "status", "summary", "why"),
    [
        ("RATINGS NOT HELD (1 fail)", "fail", "", "1 fail"),
        ("RATINGS NOT HELD (2 fail, 1 not judged)", "fail", "", "2 fail, 1 not judged"),
        ("NOTHING JUDGED (18 not judged)", "fail", "", "nothing judged (18 not judged)"),
        (
            None,
            "error",
            "ratings.json: `speed` is no key here",
            "the last run judged nothing: ratings.json: `speed` is no key here",
        ),
    ],
)
def test_every_record_short_of_held_is_not_held(tmp_path, capsys, verdict, status, summary, why):
    proj = node(tmp_path)
    rated(proj, verdict, status, summary)
    code, lines = gates(proj, capsys, strict=True)
    assert code == 1 and lines[-2] == f"RATINGS not held: {why} (workcenter ratings {proj})"
    assert lines[-1].startswith("RED (ratings not held)")


def test_held_ratings_leave_the_verdict_green(tmp_path, capsys):
    proj = node(tmp_path)
    rated(proj, "RATINGS HELD")
    code, lines = gates(proj, capsys, strict=True)
    assert code == 0 and lines[-1].startswith("GREEN: node  report ")
    assert lines[-2] == "RATINGS held: build/ratings/report.json says RATINGS HELD"


def test_a_stale_record_is_not_held(tmp_path, capsys):
    """The schematic or the facts changed after the ratings ran: the record speaks of other files."""
    proj = node(tmp_path)
    rated(proj, "RATINGS HELD")
    later = time.time() + 60
    os.utime(proj / "parts.csv", (later, later))
    code, lines = gates(proj, capsys, strict=True)
    assert code == 1
    assert lines[-2] == f"RATINGS not held: parts.csv changed after the last run (workcenter ratings {proj})"
    rated(proj, "RATINGS HELD")  # a new run, after the change
    os.utime(proj / "build" / "ratings" / "report.json", (later + 5, later + 5))
    code, lines = gates(proj, capsys, strict=True)
    assert code == 0 and lines[-2].startswith("RATINGS held:")


def test_no_record_yet_is_not_held(tmp_path, capsys):
    proj = node(tmp_path)
    code, lines = gates(proj, capsys, strict=True)
    assert code == 1
    assert lines[-2] == f"RATINGS not held: no build/ratings/report.json yet (workcenter ratings {proj})"


def test_a_project_without_ratings_json_keeps_its_verdict(tmp_path, capsys):
    proj = node(tmp_path)
    (proj / "ratings.json").unlink()
    code, lines = gates(proj, capsys, strict=True)
    assert code == 0 and lines[-2] == NOT_ASKED and lines[-1].startswith("GREEN: node  report ")


def test_a_red_run_stays_red_and_still_says_the_ratings(tmp_path, capsys):
    proj = node(tmp_path)
    rated(proj, "RATINGS HELD, 3 NOT JUDGED")
    code, lines = gates(proj, capsys, fail="drc")
    assert code == 1 and lines[-1].startswith("RED: node  report ")
    assert lines[-2] == f"RATINGS not held: 3 not judged (workcenter ratings {proj})"


def test_the_gates_report_carries_the_same_verdict_and_the_ratings_line(tmp_path, capsys):
    proj = node(tmp_path)
    rated(proj, "RATINGS HELD, 3 NOT JUDGED")
    report = tmp_path / "docs" / "gates.md"
    code, lines = gates(proj, capsys, strict=True, report=report)
    text = report.read_text(encoding="utf-8")
    assert f"RATINGS not held: 3 not judged (workcenter ratings {proj})" in text
    assert "RED (ratings not held) on " in text and "GREEN" not in text


# ------------------------------------------------------------- next reads the same definition


def test_next_is_done_only_when_the_gates_line_says_held(tmp_path, capsys):
    """For each record, `next` says Nothing exactly when `gates` prints `RATINGS held`."""
    proj = node(tmp_path)
    env = {**os.environ, "NGSPICE": sys.executable, "KICAD_CLI": sys.executable}
    for verdict in ("RATINGS HELD", "RATINGS HELD, 3 NOT JUDGED", "RATINGS NOT HELD (1 fail)"):
        rated(proj, verdict, "pass" if verdict.startswith("RATINGS HELD") else "fail")
        records = [
            {"gate": g, "status": "pass", "summary": "", "details": {}, "artifacts": [], "seconds": 0.0}
            for g in GATES
        ]
        (proj / "build" / "gates.json").write_text(json.dumps(records), encoding="utf-8")
        later = time.time() + 10
        os.utime(proj / "build" / "gates.json", (later, later))
        proc = subprocess.run(
            [sys.executable, str(CLI), "--json", "next", str(proj), "--trust-design"],
            capture_output=True,
            text=True,
            check=False,
            env=env,
        )
        step = json.loads(proc.stdout)
        state = guide.ratings_state(load_cli(), load_cli().find_project(str(proj)))
        assert step["done"] is state.held, (verdict, step)
        assert state.held is (verdict == "RATINGS HELD")


# ------------------------------------------------------------- real runs


def run(*args: object) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True, check=False
    )


@needs_kicad
def test_the_real_gates_follow_the_real_ratings(tmp_path):
    """`pass-ratings-node` is held whole (`ratings --strict` prints RATINGS HELD), so `gates --strict`
    keeps its verdict and says the ratings are held. With the 453k resistor's row taken out of
    parts.csv the ratings run again leaves something not judged, and `gates --strict` is not GREEN."""
    proj = node(tmp_path / "a")
    shutil.copytree(BOARDS / "library", tmp_path / "a" / "library")  # the facts, above the project
    held = run("ratings", proj, "--strict")
    assert held.stdout.splitlines()[-1].startswith("RATINGS HELD: node"), held.stdout
    green = run("gates", proj, "--strict")
    lines = green.stdout.splitlines()
    assert lines[-2] == "RATINGS held: build/ratings/report.json says RATINGS HELD", green.stdout
    assert green.returncode == 0 and lines[-1].startswith("GREEN"), green.stdout
    rows = (proj / "parts.csv").read_text(encoding="utf-8").splitlines(keepends=True)
    (proj / "parts.csv").write_text("".join(r for r in rows if not r.startswith("453k,")), "utf-8")
    stale = run("gates", proj, "--strict")
    assert stale.returncode == 1, stale.stdout
    assert stale.stdout.splitlines()[-2] == (
        f"RATINGS not held: parts.csv changed after the last run (workcenter ratings {proj})"
    )
    run("ratings", proj)
    said = json.loads((proj / "build" / "ratings" / "report.json").read_text(encoding="utf-8"))
    assert said["details"]["verdict"] != "RATINGS HELD", said["details"]
    red = run("gates", proj, "--strict")
    lines = red.stdout.splitlines()
    assert red.returncode == 1 and lines[-1].startswith("RED (ratings not held): node"), red.stdout
    assert lines[-2].startswith("RATINGS not held: ") and lines[-2].endswith(f"(workcenter ratings {proj})")
