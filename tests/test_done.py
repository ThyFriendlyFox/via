"""One definition of done (user round 1, C): a project with a `ratings.json` is done when the gates are
GREEN and its ratings are held. `workcenter gates` says on 1 line whether they are, `--strict` does not
end GREEN while they are not, and `workcenter next` says nothing is left only when both hold.

Held: `build/ratings/report.json` says exactly `RATINGS HELD`, and the files that run read are the files
there now, each with the same SHA256: the schematic, `ratings.json`, the parts files it was given, the
pack `ratings.json` names, and every facts file. A file changed, gone or new since the run makes the
record stale, and a stale record is not held. A record that names no file it read is not held either.

Most tests run `cmd_gates` with the 4 gates replaced by functions that return a pass, so they need no
engine; the ratings record is written by hand as a ratings run leaves it. 2 tests run the real gates
and the real `ratings` on the fixture `pass-ratings-node`, and skip without kicad-cli.
"""

from __future__ import annotations

import argparse
import hashlib
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
from conftest import engine

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
sys.path.insert(0, str(ROOT / "tools"))
import guide  # noqa: E402

needs_kicad = engine(
    pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
)
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


PACK = ROOT / "rules" / "ratings" / "nasa-eee-inst-002.json"  # the pack the fixture's ratings.json names


def read_by_run(proj: Path, parts: tuple[str, ...] = ("parts.csv",), more: tuple[Path, ...] = ()) -> dict:
    """The files a ratings run of the fixture reads, as its record names them: each path from the
    project's folder with its SHA256. The schematic, ratings.json, the parts files, the pack, and the
    facts in `more` (a test's folder has no library/facts above it unless the test puts one there)."""
    files = [proj / "node.kicad_sch", proj / "ratings.json", *(proj / p for p in parts), PACK, *more]
    return {
        "parts": list(parts),
        "files": {os.path.relpath(f, proj): hashlib.sha256(f.read_bytes()).hexdigest() for f in files},
    }


def rated(
    proj: Path,
    verdict: str | None,
    status: str = "pass",
    summary: str = "",
    inputs: dict | None = None,
    named: bool = True,
) -> None:
    """The record a ratings run leaves, a moment after the project's files. A run with a verdict names
    the files it read (`inputs`, by default those of `read_by_run`); a refusal names none."""
    folder = proj / "build" / "ratings"
    folder.mkdir(parents=True, exist_ok=True)
    details = {"failures": [], "warnings": [], **({"verdict": verdict} if verdict else {})}
    if verdict and named:
        details["inputs"] = inputs or read_by_run(proj)
    record = {"gate": "ratings", "status": status, "summary": summary, "details": details}
    (folder / "report.json").write_text(json.dumps({**record, "artifacts": [], "seconds": 0.0}), "utf-8")
    later = time.time() + 5
    os.utime(folder / "report.json", (later, later))


def gates(
    proj: Path, capsys, *, strict: bool = False, fail: str = "", report: Path | None = None, as_json=False
):
    """`workcenter gates` with each gate a pass (or `fail` failing): the exit code and the lines; with
    `as_json`, the lines of stdout and the lines of stderr."""
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
        project=str(proj), out=None, strict=strict, step=False, fab=None, report=report, json=as_json
    )
    code = cli.cmd_gates(args)
    said = capsys.readouterr()
    if as_json:
        return code, said.out.splitlines(), said.err.splitlines()
    return code, said.out.splitlines()


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


# The fixtures whose ratings.json is there for another command, which reads its volts and amps, and not
# for `ratings`: they hold no parts file, so `ratings` judges nothing of their parts (NOTHING JUDGED), and
# a record that judged nothing is not held. Their gates are not GREEN under --strict, and they stay so:
# their `pass-` or `fail-` is the other command's verdict, which the definition of done does not change.
# A fixture that should end GREEN under `gates --strict` needs facts for every part, as `pass-ratings-node`.
FOR_ANOTHER_COMMAND = {
    "pass-copper-strip": "`copper --strict` reads the amps at J2 and through R1",
    "fail-copper-neck": "`copper` reads the amps at J2 and through R1",
    "pass-board-ecss": "the ECSS pack's DRC reads the volts of VIN and the amps of J1",
    "fail-board-ecss": "the ECSS pack's DRC reads the volts of VIN and the amps of J1",
}


def test_a_fixture_with_ratings_json_is_a_ratings_fixture_or_named_for_another_command(tmp_path, capsys):
    """Every fixture with a ratings.json asks for the ratings. One named `*-ratings-*` is judged by
    `ratings`, and so is a circuit block's `pass-block-*`, which its block's tests hold to
    `ratings --strict` and to `gates --strict` after a ratings run (tests/test_blocks*.py). Any other is
    in FOR_ANOTHER_COMMAND, holds no parts file, and its gates under --strict say `RATINGS not held` and
    end `RED (ratings not held)`, with no record and with a record of NOTHING JUDGED, as on any board
    whose ratings judged nothing."""
    cli = load_cli()
    asked = sorted(p.parent.name for p in BOARDS.glob("*/ratings.json"))
    judged = [n for n in asked if "-ratings-" in n or n.startswith("pass-block-")]
    assert sorted(set(asked) - set(judged)) == sorted(FOR_ANOTHER_COMMAND)
    for name in FOR_ANOTHER_COMMAND:
        proj = tmp_path / name
        shutil.copytree(BOARDS / name, proj, ignore=shutil.ignore_patterns("build"))
        assert not list(proj.glob("*.csv")), name
        code, lines = gates(proj, capsys, strict=True)
        assert code == 1 and lines[-2].startswith("RATINGS not held: no build/ratings/report.json yet"), lines
        project = cli.find_project(str(proj))
        files = cli.ratings().read_by_run(project, [], cli)
        sums = {rel: hashlib.sha256(f.read_bytes()).hexdigest() for rel, f in files.items()}
        rated(proj, "NOTHING JUDGED (1 not judged)", "fail", inputs={"parts": [], "files": sums})
        code, lines = gates(proj, capsys, strict=True)
        assert code == 1, lines
        assert lines[-2] == f"RATINGS not held: nothing judged (1 not judged) (workcenter ratings {proj})"
        assert lines[-1].startswith("RED (ratings not held)"), lines


def test_held_ratings_leave_the_verdict_green(tmp_path, capsys):
    proj = node(tmp_path)
    rated(proj, "RATINGS HELD")
    code, lines = gates(proj, capsys, strict=True)
    assert code == 0 and lines[-1].startswith("GREEN: node  report ")
    assert lines[-2] == "RATINGS held: build/ratings/report.json says RATINGS HELD"


def test_a_stale_record_is_not_held(tmp_path, capsys):
    """parts.csv changed after the ratings ran, and was put back with an old time (as `cp -p`, `tar`
    and `rsync -a` keep it): the record speaks of other files. A file touched and not changed is the
    file the run read."""
    proj = node(tmp_path)
    rated(proj, "RATINGS HELD")
    earlier = time.time() - 600
    with (proj / "parts.csv").open("a", encoding="utf-8") as fh:
        fh.write("1k,R_0603,1,Yageo,RC0603FR-071KL,,,,\n")
    os.utime(proj / "parts.csv", (earlier, earlier))
    code, lines = gates(proj, capsys, strict=True)
    assert code == 1
    assert lines[-2] == f"RATINGS not held: parts.csv changed after the last run (workcenter ratings {proj})"
    rated(proj, "RATINGS HELD")  # a new run, after the change
    later = time.time() + 60
    os.utime(proj / "ratings.json", (later, later))
    code, lines = gates(proj, capsys, strict=True)
    assert code == 0 and lines[-2].startswith("RATINGS held:")


def with_facts(tmp_path: Path) -> tuple[Path, Path]:
    """The fixture with 1 facts file in a library above it, where `ratings` finds it."""
    proj = node(tmp_path)
    facts = tmp_path / "library" / "facts"
    facts.mkdir(parents=True)
    shutil.copy(BOARDS / "library" / "facts" / "passives.json", facts / "passives.json")
    return proj, facts


def test_a_facts_file_deleted_after_the_run_makes_the_record_stale(tmp_path, capsys):
    """F1 of the review: passives.json taken away after a HELD run. A fresh run then says RATINGS NOT
    HELD (1 fail, 18 not judged); the record speaks of a file that is gone."""
    proj, facts = with_facts(tmp_path)
    rated(proj, "RATINGS HELD", inputs=read_by_run(proj, more=(facts / "passives.json",)))
    (facts / "passives.json").unlink()
    code, lines = gates(proj, capsys, strict=True)
    assert code == 1 and lines[-1].startswith("RED (ratings not held)")
    assert lines[-2] == (
        f"RATINGS not held: ../library/facts/passives.json is gone since the last run "
        f"(workcenter ratings {proj})"
    )


def test_a_facts_file_added_after_the_run_makes_the_record_stale(tmp_path, capsys):
    proj, facts = with_facts(tmp_path)
    rated(proj, "RATINGS HELD", inputs=read_by_run(proj, more=(facts / "passives.json",)))
    shutil.copy(BOARDS / "library" / "facts" / "ti-tlv755p.json", facts / "ti-tlv755p.json")
    code, lines = gates(proj, capsys, strict=True)
    assert code == 1
    assert lines[-2] == (
        f"RATINGS not held: ../library/facts/ti-tlv755p.json is new since the last run "
        f"(workcenter ratings {proj})"
    )


def test_a_parts_file_outside_the_project_is_watched(tmp_path, capsys):
    """F2 of the review: `ratings --parts ../parts/catalog.csv`, then the catalog edited. The record
    names the file it was given, and the gates check that file."""
    proj = node(tmp_path)
    (tmp_path / "parts").mkdir()
    catalog = tmp_path / "parts" / "catalog.csv"
    shutil.move(proj / "parts.csv", catalog)
    rated(proj, "RATINGS HELD", inputs=read_by_run(proj, parts=("../parts/catalog.csv",)))
    code, lines = gates(proj, capsys, strict=True)
    assert code == 0 and lines[-2].startswith("RATINGS held:"), lines
    rows = catalog.read_text(encoding="utf-8").splitlines(keepends=True)
    catalog.write_text("".join(r for r in rows if not r.startswith("453k,")), encoding="utf-8")
    code, lines = gates(proj, capsys, strict=True)
    assert code == 1
    assert lines[-2] == (
        f"RATINGS not held: ../parts/catalog.csv changed after the last run (workcenter ratings {proj})"
    )


def test_a_project_parts_csv_new_since_a_run_without_one_is_seen(tmp_path, capsys):
    """A run with no parts file; then parts.csv appears, which the next run would read."""
    proj = node(tmp_path)
    kept = (proj / "parts.csv").read_bytes()
    (proj / "parts.csv").unlink()
    rated(proj, "RATINGS HELD", inputs=read_by_run(proj, parts=()))
    (proj / "parts.csv").write_bytes(kept)
    code, lines = gates(proj, capsys, strict=True)
    assert code == 1
    assert lines[-2] == f"RATINGS not held: parts.csv is new since the last run (workcenter ratings {proj})"


def test_a_project_pack_is_watched(tmp_path, capsys):
    """F2 of the review: ratings.json names a pack of the project's own, mine.json, changed after the
    run."""
    proj = node(tmp_path)
    shutil.copy(PACK, proj / "mine.json")
    stated = json.loads((proj / "ratings.json").read_text(encoding="utf-8"))
    (proj / "ratings.json").write_text(json.dumps({**stated, "pack": "mine.json"}), encoding="utf-8")
    files = [proj / "node.kicad_sch", proj / "ratings.json", proj / "parts.csv", proj / "mine.json"]
    inputs = {
        "parts": ["parts.csv"],
        "files": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files},
    }
    rated(proj, "RATINGS HELD", inputs=inputs)
    code, lines = gates(proj, capsys, strict=True)
    assert code == 0 and lines[-2].startswith("RATINGS held:"), lines
    with (proj / "mine.json").open("a", encoding="utf-8") as fh:
        fh.write("\n")
    code, lines = gates(proj, capsys, strict=True)
    assert code == 1
    assert lines[-2] == f"RATINGS not held: mine.json changed after the last run (workcenter ratings {proj})"


def test_a_held_record_that_names_no_file_it_read_is_not_held(tmp_path, capsys):
    """A record of a run that kept no list of its files cannot say they are the files there now."""
    proj = node(tmp_path)
    rated(proj, "RATINGS HELD", named=False)
    code, lines = gates(proj, capsys, strict=True)
    assert code == 1
    assert lines[-2] == (
        f"RATINGS not held: build/ratings/report.json names no file its run read (workcenter ratings {proj})"
    )


@pytest.mark.parametrize(
    ("details", "why"),
    [
        ([], "build/ratings/report.json: details is no object"),
        ({"verdict": 5}, "build/ratings/report.json: details.verdict is no text"),
        (
            {"verdict": "RATINGS HELD", "failures": "x"},
            "build/ratings/report.json: details.failures is no list",
        ),
        (
            {"verdict": "RATINGS HELD", "inputs": {"files": []}},
            "build/ratings/report.json: details.inputs is no object of parts and files",
        ),
    ],
)
def test_a_record_that_is_no_record_of_a_run_is_refused_in_1_line(tmp_path, capsys, details, why):
    """F3 of the review: these gave a traceback. Each is 1 line naming the file and the key."""
    proj = node(tmp_path)
    folder = proj / "build" / "ratings"
    folder.mkdir(parents=True)
    record = {"gate": "ratings", "status": "pass", "summary": "", "details": details, "artifacts": []}
    (folder / "report.json").write_text(json.dumps({**record, "seconds": 0.0}), encoding="utf-8")
    code, lines = gates(proj, capsys, strict=True)
    assert code == 1 and lines[-2] == f"RATINGS not held: {why} (workcenter ratings {proj})"
    assert lines[-1].startswith("RED (ratings not held)")


def test_gates_json_says_the_ratings_and_the_verdict(tmp_path, capsys):
    """F4 of the review: `--json --strict` exited 1 with 4 passing gates and no reason. stdout keeps
    the 4 gates' records alone (the board-gates skill: 1 record per gate), and stderr carries the 2
    lines a run without --json ends with: the ratings line and the verdict."""
    proj = node(tmp_path)
    rated(proj, "RATINGS HELD, 3 NOT JUDGED")
    code, lines, err = gates(proj, capsys, strict=True, as_json=True)
    said = json.loads("\n".join(lines))
    assert code == 1
    assert [r["gate"] for r in said] == list(GATES)
    assert err[-2] == f"RATINGS not held: 3 not judged (workcenter ratings {proj})"
    assert err[-1].startswith("RED (ratings not held): node  report ")


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
    """For each record, `next` says Nothing exactly when `gates` prints `RATINGS held`. The last 3
    records are where `next`'s check before this item (the verdict alone, and inputs newer than the
    record) said done: a facts file gone since a HELD run, a HELD record that names no file it read,
    and a record whose details are no object (a traceback then)."""
    proj, facts = with_facts(tmp_path)
    env = {**os.environ, "NGSPICE": sys.executable, "KICAD_CLI": sys.executable}
    whole = read_by_run(proj, more=(facts / "passives.json",))
    gone = {**whole, "files": {**whole["files"], "../library/facts/gone.json": "0" * 64}}
    cases = [
        ("RATINGS HELD", whole, True, True),
        ("RATINGS HELD, 3 NOT JUDGED", whole, True, False),
        ("RATINGS NOT HELD (1 fail)", whole, True, False),
        ("RATINGS HELD", gone, True, False),
        ("RATINGS HELD", None, False, False),
        ("details []", None, True, False),
    ]
    for verdict, inputs, named, held in cases:
        rated(proj, verdict, "fail" if "NOT" in verdict else "pass", inputs=inputs, named=named)
        if verdict == "details []":
            record = proj / "build" / "ratings" / "report.json"
            raw = json.loads(record.read_text(encoding="utf-8"))
            record.write_text(json.dumps({**raw, "details": []}), encoding="utf-8")
            later = time.time() + 5
            os.utime(record, (later, later))
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
        assert proc.returncode in (0, 1) and "Traceback" not in proc.stderr, (verdict, proc.stderr)
        step = json.loads(proc.stdout)
        state = guide.ratings_state(load_cli(), load_cli().find_project(str(proj)))
        assert step["done"] is state.held, (verdict, step)
        assert state.held is held, (verdict, state)


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


@needs_kicad
def test_the_real_record_names_the_files_its_run_read(tmp_path):
    """F1 and F2 of the review on real runs. `ratings --strict --parts ../parts/catalog.csv` holds the
    fixture; its record names the catalog and the facts. The catalog without its 453k row, then the
    catalog put back as it was, then passives.json taken away: RED, GREEN, RED."""
    proj = node(tmp_path / "a")
    shutil.copytree(BOARDS / "library", tmp_path / "a" / "library")
    (tmp_path / "a" / "parts").mkdir()
    catalog = tmp_path / "a" / "parts" / "catalog.csv"
    shutil.move(proj / "parts.csv", catalog)
    held = run("ratings", proj, "--strict", "--parts", catalog)
    assert held.stdout.splitlines()[-1].startswith("RATINGS HELD: node"), held.stdout
    said = json.loads((proj / "build" / "ratings" / "report.json").read_text(encoding="utf-8"))
    inputs = said["details"]["inputs"]
    assert inputs["parts"] == ["../parts/catalog.csv"]
    assert {
        "node.kicad_sch",
        "ratings.json",
        "../parts/catalog.csv",
        "../library/facts/passives.json",
    } <= set(inputs["files"])
    kept = catalog.read_bytes()
    rows = kept.decode("utf-8").splitlines(keepends=True)
    catalog.write_text("".join(r for r in rows if not r.startswith("453k,")), encoding="utf-8")
    stale = run("gates", proj, "--strict")
    assert stale.returncode == 1, stale.stdout
    assert stale.stdout.splitlines()[-2] == (
        f"RATINGS not held: ../parts/catalog.csv changed after the last run (workcenter ratings {proj})"
    )
    catalog.write_bytes(kept)
    green = run("gates", proj, "--strict")
    assert green.returncode == 0 and green.stdout.splitlines()[-2].startswith("RATINGS held:"), green.stdout
    (tmp_path / "a" / "library" / "facts" / "passives.json").unlink()
    gone = run("gates", proj, "--strict")
    assert gone.returncode == 1, gone.stdout
    assert gone.stdout.splitlines()[-2] == (
        f"RATINGS not held: ../library/facts/passives.json is gone since the last run "
        f"(workcenter ratings {proj})"
    )
