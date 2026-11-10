"""`workcenter verify`: a project's verification package checked against a fresh ngspice run (P28).

Each test copies the passing RC divider fixture into tmp_path and writes a small package beside it: two
requirements, one measured by the divider's deck (vout = 2.5 V) and one left OPEN, a writeup of the deck,
a block diagram, a calculation and a traceability table. Tests that run ngspice skip when it is absent.
"""

from __future__ import annotations

import importlib.machinery
import json
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"

needs_ngspice = pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice is not installed")


def load_cli():
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_verify", str(CLI))
    module = types.ModuleType("workcenter_cli_verify")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module
    loader.exec_module(module)
    return module


def run(*args: object, env: dict | None = None) -> tuple[int, list[dict]]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
    )
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else [])


REQUIREMENTS = """# Requirements

| ID | Requirement | Limit | Source | Method | Inspection |
|---|---|---|---|---|---|
| REQ-OUT-01 | The divider's output | 2.45 to 2.55 V | the fixture's spec | Simulation | none |
| REQ-OUT-02 | Its resistors are 1 % parts | 1 % | the fixture's spec | Examination | none |
"""

WRITEUP = """# rc_divider

Deck: [`sim/rc_divider.cir`](../../../sim/rc_divider.cir). Requirements: REQ-OUT-01.

## Purpose
The divider's output.
## Circuit
5 V through 10k into 10k.
## Inputs
5 V.
## Outputs
| Measure | What |
|---|---|
| `rc_divider.vout` | the output |
## Expected
2.5 V.
## Results
| Measure | Value | Limit | Verdict |
|---|---|---|---|
| `rc_divider.vout` | VALUE | 2.45 to 2.55 V | PASS |
## Why it is required, and what is not
The output feeds an ADC.
## Nodal analysis
(1) KCL at out: (5 - v)/10k = v/10k, so v = 2.5 V.
## Sources
Kirchhoff's current law.
## Re-run
workcenter verify .
"""

TRACE = """# Traceability

| ID | Check | Evidence | Measured | Verdict |
|---|---|---|---|---|
| REQ-OUT-01 | `2.45 V<=rc_divider.vout<=2.55 V` | [w](simulations/rc_divider/README.md) | 2.500 V | VERDICT |
| REQ-OUT-02 | — | [calc](calculations/README.md) | — | OPEN |
"""


def project_with_package(tmp_path: Path, value: str = "2.50 V", verdict: str = "PASS") -> Path:
    project = tmp_path / "rc"
    shutil.copytree(BOARDS / "pass-rc-divider", project)
    pkg = project / "verification"
    files = {
        "README.md": "# Package\n\n[Requirements](requirements/README.md), [trace](traceability.md).\n",
        "requirements/README.md": REQUIREMENTS,
        "system/README.md": "# System\n\n![Block diagram](block.svg)\n",
        "system/block.svg": '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>\n',
        "simulations/rc_divider/README.md": WRITEUP.replace("VALUE", value),
        "calculations/README.md": "# Calculations\n\nThe resistors' tolerance is read from the BOM.\n",
        "traceability.md": TRACE.replace("VERDICT", verdict),
    }
    for rel, text in files.items():
        (pkg / rel).parent.mkdir(parents=True, exist_ok=True)
        (pkg / rel).write_text(text, encoding="utf-8")
    return project


def failures(results: list[dict]) -> list[str]:
    return results[0]["details"].get("failures", [])


@needs_ngspice
def test_complete_package_passes_and_writes_its_report(tmp_path):
    project = project_with_package(tmp_path)
    code, results = run("verify", project)
    assert code == 0, failures(results)
    r = results[0]
    assert r["gate"] == "verify" and r["status"] == "pass"
    assert r["details"]["requirements"] == 2
    assert r["details"]["verdicts"] == {"PASS": ["REQ-OUT-01"], "FAIL": [], "OPEN": ["REQ-OUT-02"]}
    assert r["details"]["quoted"] == 2  # the writeup's table and the traceability row
    report = json.loads((project / "build" / "verify.json").read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert (project / "build" / "sim" / "rc_divider.log").is_file()


@needs_ngspice
def test_strict_fails_on_an_open_requirement(tmp_path):
    code, results = run("verify", project_with_package(tmp_path), "--strict")
    assert code == 1
    assert "REQ-OUT-02: OPEN" in failures(results)


@needs_ngspice
def test_a_quoted_number_that_is_not_the_run_fails(tmp_path):
    code, results = run("verify", project_with_package(tmp_path, value="2.60 V"))
    assert code == 1
    assert any("rc_divider.vout quoted as 2.60 V" in f for f in failures(results)), failures(results)


@needs_ngspice
def test_a_quote_rounded_to_fewer_digits_still_matches(tmp_path):
    code, results = run("verify", project_with_package(tmp_path, value="2.5 V"))
    assert code == 0, failures(results)


@needs_ngspice
def test_a_verdict_must_be_the_checks(tmp_path):
    code, results = run("verify", project_with_package(tmp_path, verdict="FAIL"))
    assert code == 1
    assert any("REQ-OUT-01 says FAIL" in f and "is PASS" in f for f in failures(results)), failures(results)


@needs_ngspice
def test_a_requirement_without_a_row_fails(tmp_path):
    project = project_with_package(tmp_path)
    trace = project / "verification" / "traceability.md"
    trace.write_text("\n".join(ln for ln in trace.read_text().splitlines() if "REQ-OUT-02" not in ln) + "\n")
    code, results = run("verify", project)
    assert code == 1
    assert "traceability: REQ-OUT-02 has no row" in failures(results)


@needs_ngspice
def test_a_deck_without_a_writeup_fails(tmp_path):
    project = project_with_package(tmp_path)
    (project / "sim" / "extra.cir").write_text("* extra\nV1 a 0 1\nR1 a 0 1k\n.control\nop\n.endc\n.end\n")
    code, results = run("verify", project)
    assert code == 1
    assert "sim/extra.cir: no writeup in simulations/ explains it" in failures(results)


@needs_ngspice
def test_a_writeup_without_its_nodal_analysis_fails(tmp_path):
    project = project_with_package(tmp_path)
    md = project / "verification" / "simulations" / "rc_divider" / "README.md"
    md.write_text(md.read_text().replace("## Nodal analysis", "## Notes"))
    code, results = run("verify", project)
    assert code == 1
    assert any("no section for nodal analysis" in f for f in failures(results)), failures(results)


@needs_ngspice
def test_a_link_that_leads_nowhere_fails(tmp_path):
    project = project_with_package(tmp_path)
    (project / "verification" / "system" / "block.svg").unlink()
    code, results = run("verify", project)
    assert code == 1
    assert any("link to block.svg leads nowhere" in f for f in failures(results)), failures(results)


@needs_ngspice
def test_a_requirement_without_a_source_fails(tmp_path):
    project = project_with_package(tmp_path)
    md = project / "verification" / "requirements" / "README.md"
    md.write_text(md.read_text().replace("| the fixture's spec | Simulation", "| — | Simulation"))
    code, results = run("verify", project)
    assert code == 1
    assert "requirements: REQ-OUT-01 has no source" in failures(results)


def test_without_a_package_it_skips(tmp_path):
    project = tmp_path / "rc"
    shutil.copytree(BOARDS / "pass-rc-divider", project)
    code, results = run("verify", project)
    assert code == 2
    assert results[0]["status"] == "skip" and "--init" in results[0]["summary"]
    assert (project / "build" / "verify.json").is_file()


def test_without_ngspice_it_skips(tmp_path):
    code, results = run("verify", project_with_package(tmp_path), env={"NGSPICE": "ngspice-not-installed"})
    assert code == 2
    assert results[0]["status"] == "skip" and "ngspice-not-installed" in results[0]["summary"]


@needs_ngspice
def test_init_writes_the_skeleton_and_never_overwrites(tmp_path):
    project = tmp_path / "rc"
    shutil.copytree(BOARDS / "pass-rc-divider", project)
    code, results = run("verify", project, "--init")
    assert code == 1  # every template section says <!-- fill ... --> until it is written
    pkg = project / "verification"
    for rel in (
        "README.md",
        "requirements/README.md",
        "system/README.md",
        "system/block-diagram.json",  # the starter spec for `workcenter diagram`
        "calculations/README.md",
        "traceability.md",
        "simulations/rc_divider/README.md",
    ):
        assert (pkg / rel).is_file(), rel
    assert not (pkg / "simulations" / "_deck").exists()
    assert "sim/rc_divider.cir" in (pkg / "simulations" / "rc_divider" / "README.md").read_text()
    assert len(results[0]["details"]["created"]) == 7
    (pkg / "README.md").write_text("# Mine\n")
    code, results = run("verify", project, "--init")
    assert (pkg / "README.md").read_text() == "# Mine\n"
    assert results[0]["details"]["created"] == []


def test_quantity_reads_si_prefixes_and_the_last_digit():
    cli = load_cli()
    assert cli.quantity("4.7 mV") == pytest.approx((0.0047, 0.00005))
    assert cli.quantity("125 ns")[0] == pytest.approx(125e-9)
    assert cli.quantity("10 kΩ")[0] == pytest.approx(10e3)
    assert cli.quantity("−3.0 V")[0] == pytest.approx(-3.0)
    assert cli.quantity("70 °C") == pytest.approx((70.0, 0.5))
    assert cli.quantity("7.22 nC") == pytest.approx((7.22e-9, 0.005e-9))
    assert cli.quantity("about 3 V") is None


@needs_ngspice
def test_a_deck_file_named_in_a_table_is_not_a_measure(tmp_path):
    project = project_with_package(tmp_path)
    md = project / "verification" / "calculations" / "README.md"
    md.write_text(md.read_text() + "\n| Deck | What |\n|---|---|\n| `rc_divider.cir` | the divider |\n")
    code, results = run("verify", project)
    assert code == 0, failures(results)


WITHDRAWN = """
## Withdrawn

| ID | Date | Decision | By |
|---|---|---|---|
| REQ-OUT-02 | DATE | the resistors' tolerance is the BOM's business, not the package's | BY |
"""


def withdraw(
    project: Path, date: str = "2026-11-06", by: str = "the owner", keep_row=False, keep_trace=False
):
    """REQ-OUT-02 moved from the requirements table to a Withdrawn table, its traceability row removed."""
    req = project / "verification" / "requirements" / "README.md"
    lines = req.read_text().splitlines()
    if not keep_row:
        lines = [ln for ln in lines if not ln.startswith("| REQ-OUT-02 ")]
    req.write_text("\n".join(lines) + "\n" + WITHDRAWN.replace("DATE", date).replace("BY", by))
    if not keep_trace:
        trace = project / "verification" / "traceability.md"
        kept = [ln for ln in trace.read_text().splitlines() if "REQ-OUT-02" not in ln]
        trace.write_text("\n".join(kept) + "\n")


@needs_ngspice
def test_a_withdrawn_requirement_leaves_the_counts_and_is_named(tmp_path):
    project = project_with_package(tmp_path)
    withdraw(project)
    code, results = run("verify", project, "--strict")
    assert code == 0, failures(results)  # REQ-OUT-02 was OPEN; withdrawn, --strict no longer sees it
    r = results[0]
    assert r["details"]["requirements"] == 1
    assert r["details"]["verdicts"] == {"PASS": ["REQ-OUT-01"], "FAIL": [], "OPEN": []}
    assert r["details"]["withdrawn"] == {
        "REQ-OUT-02": {
            "date": "2026-11-06",
            "decision": "the resistors' tolerance is the BOM's business, not the package's",
            "by": "the owner",
        }
    }
    summary = r["summary"]
    assert summary.startswith("1 requirements: 1 pass, 0 fail, 0 open; withdrawn REQ-OUT-02;"), summary


@needs_ngspice
def test_a_withdrawn_requirement_in_the_traceability_table_fails(tmp_path):
    project = project_with_package(tmp_path)
    withdraw(project, keep_trace=True)
    code, results = run("verify", project)
    assert code == 1
    found = failures(results)
    assert "traceability: REQ-OUT-02 was withdrawn on 2026-11-06 (the owner); remove its row" in found, found
    assert results[0]["details"]["verdicts"]["OPEN"] == []


@needs_ngspice
def test_a_withdrawn_requirement_still_in_the_requirements_fails(tmp_path):
    project = project_with_package(tmp_path)
    withdraw(project, keep_row=True, keep_trace=True)
    code, results = run("verify", project)
    assert code == 1
    assert "requirements: REQ-OUT-02 is withdrawn and still in a requirements table" in failures(results)


@needs_ngspice
def test_a_withdrawal_names_its_date_and_who_made_it(tmp_path):
    project = project_with_package(tmp_path)
    withdraw(project, date="6 November", by="—")
    code, results = run("verify", project)
    assert code == 1
    found = failures(results)
    assert "requirements: withdrawn REQ-OUT-02 is dated '6 November', not like 2026-11-06" in found, found
    assert "requirements: withdrawn REQ-OUT-02 has no by" in found, found


@needs_ngspice
def test_a_bound_naming_a_withdrawn_requirement_fails(tmp_path):
    project = project_with_package(tmp_path)
    withdraw(project)
    expect = project / "sim" / "rc_divider.expect.json"
    expect.write_text('{ "vout": { "min": 2.45, "max": 2.55, "req": "REQ-OUT-02" } }\n')
    code, results = run("verify", project)
    assert code == 1
    assert "rc_divider.expect.json: vout names REQ-OUT-02, withdrawn on 2026-11-06" in failures(results)


@needs_ngspice
def test_a_requirement_the_owner_restated_names_the_decisions_date(tmp_path):
    project = project_with_package(tmp_path)
    md = project / "verification" / "requirements" / "README.md"
    restated = "| the owner's decision of 2026-11-06; the fixture's spec | Examination"
    md.write_text(md.read_text().replace("| the fixture's spec | Examination", restated))
    code, results = run("verify", project)
    assert code == 0, failures(results)
    assert results[0]["details"]["owner_decisions"] == {"REQ-OUT-02": "2026-11-06"}
    md.write_text(md.read_text().replace("decision of 2026-11-06;", "decision of Friday;"))
    code, results = run("verify", project)
    assert code == 1
    assert (
        "requirements: REQ-OUT-02 names the owner's decision of 'Friday', not a date like 2026-11-06"
        in failures(results)
    )


@needs_ngspice
def test_init_leaves_the_helpers_brief_and_facts_out(tmp_path):
    templates = ROOT / "templates" / "verification"
    assert (templates / "BRIEF.md").is_file() and (templates / "FACTS.md").is_file()
    project = tmp_path / "rc"
    shutil.copytree(BOARDS / "pass-rc-divider", project)
    run("verify", project, "--init")
    assert (project / "verification" / "traceability.md").is_file()
    assert not (project / "verification" / "BRIEF.md").exists()
    assert not (project / "verification" / "FACTS.md").exists()


def test_iso_date_takes_a_real_day_written_year_first():
    cli = load_cli()
    assert cli.iso_date("2026-11-06")
    assert not cli.iso_date("2026-02-30")
    assert not cli.iso_date("20261106")
    assert not cli.iso_date("6 November 2026")


def test_parse_check_reads_one_and_two_sided_bounds():
    cli = load_cli()
    name, comparisons = cli.parse_check("vbus_hotplug.hp_worst <= 30 V")
    assert name == "vbus_hotplug.hp_worst"
    assert cli.check_holds(comparisons, 10.04) and not cli.check_holds(comparisons, 30.5)
    name, comparisons = cli.parse_check("3.0 V ≤ ldo.vout ≤ 3.6 V")
    assert name == "ldo.vout"
    assert cli.check_holds(comparisons, 3.3) and not cli.check_holds(comparisons, 2.9)
    assert cli.parse_check("a.b <= c.d") is None


# ----------------------------------------------------------------- corners


@needs_ngspice
def test_a_requirement_that_fails_at_a_corner_is_not_a_pass(tmp_path):
    # The divider reads 2.5 V as written. With 5 % resistors it reads 5 x 9.5/(10.5 + 9.5) = 2.375 V
    # at one corner, under the requirement's 2.45 V: the row that says PASS is wrong.
    project = project_with_package(tmp_path)
    corners = {"tolerance": {"R": 0.05, "source": "5 % parts"}}
    (project / "sim" / "corners.json").write_text(json.dumps(corners), encoding="utf-8")
    code, results = run("verify", project)
    assert code == 1
    said = [f for f in failures(results) if f.startswith("traceability: REQ-OUT-01")]
    assert said == [
        "traceability: REQ-OUT-01 says PASS, `2.45 V<=rc_divider.vout<=2.55 V` with 2.5 is FAIL at "
        "R1 +5 %, R2 -5 % (2.375)"
    ]
    # the row that says FAIL agrees with the corner; the deck's own bound still fails the SIM gate
    project2 = project_with_package(tmp_path / "2", verdict="FAIL")
    (project2 / "sim" / "corners.json").write_text(json.dumps(corners), encoding="utf-8")
    code, results = run("verify", project2)
    assert not [f for f in failures(results) if f.startswith("traceability:")]
    assert any(f.startswith("sim: rc_divider:vout=2.375 at R1 +5 %, R2 -5 %") for f in failures(results))


@needs_ngspice
def test_a_check_on_a_measure_no_bound_holds_is_judged_at_both_ends_of_its_corners(tmp_path):
    # Without an expect bound on vout the SIM gate has no worst case to look for on its own account;
    # the traceability check names the measure, so the run looks for both ends all the same.
    project = project_with_package(tmp_path)
    (project / "sim" / "rc_divider.expect.json").write_text('{"vout": {"max": 9}}', encoding="utf-8")
    corners = {"tolerance": {"R": 0.05, "source": "5 % parts"}}
    (project / "sim" / "corners.json").write_text(json.dumps(corners), encoding="utf-8")
    code, results = run("verify", project)
    assert code == 1
    assert [f for f in failures(results) if f.startswith("traceability: REQ-OUT-01")] == [
        "traceability: REQ-OUT-01 says PASS, `2.45 V<=rc_divider.vout<=2.55 V` with 2.5 is FAIL at "
        "R1 +5 %, R2 -5 % (2.375)"
    ]


@needs_ngspice
def test_verify_says_whether_the_requirements_are_met_apart_from_the_package(tmp_path):
    project = project_with_package(tmp_path)
    out = tmp_path / "out"
    proc = subprocess.run(
        [sys.executable, str(CLI), "verify", str(project), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
    )
    # the package agrees with the run, so the gate passes; one requirement is still OPEN
    assert proc.returncode == 0 and proc.stdout.startswith("PASS   verify")
    assert proc.stdout.splitlines()[-1] == (
        f"REQUIREMENTS NOT MET (1 of 2 pass; 1 open): rc_divider  report {out / 'verify.json'}"
    )


@needs_ngspice
def test_strict_verify_fails_verdicts_that_rest_on_decks_run_as_written_only(tmp_path):
    project = project_with_package(tmp_path)
    (project / "sim" / "corners.json").unlink()
    code, results = run("verify", project)
    assert (
        code == 0 and "2 requirements: 1 pass, 0 fail, 1 open as written, no corners" in results[0]["summary"]
    )
    assert results[0]["details"]["corners"] is False
    code, results = run("verify", project, "--strict")
    assert code == 1
    assert "sim: no sim/corners.json: every verdict rests on one run of each deck as written" in failures(
        results
    )
