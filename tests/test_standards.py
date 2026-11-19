"""`workcenter standards`: a product kind's requirements from free documents, each held by a gate, held by
a named test, or not held (tools/standards.py, rules/products/).

The fixture `tests/products/last-hit` is Last Hit v0.16 (a vaping device with a lithium cell): its
`product.json` names 4 of its verification requirements, and its `verification/traceability.md` holds
those 4 rows as the project's v0.16 has them."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import standards  # noqa: E402
from ratings import Refusal  # noqa: E402

CLI = ROOT / "tools" / "workcenter"
LAST_HIT = ROOT / "tests" / "products" / "last-hit"
BOARDS = ROOT / "tests" / "boards"
KIND = "vaping-device-lithium-cell"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), "standards", *args], capture_output=True, text=True)


def test_kind_names_each_document_and_lab_standard():
    """17 requirements from 4 documents; the paid standards are named, with no number of theirs."""
    kind = standards.read_kind(KIND)
    assert len(kind["requirements"]) == 17
    assert sorted(kind["documents"]) == ["47-cfr-15-b", "49-cfr-173-185", "ti-slva680a", "ti-szza009"]
    assert [lab["standard"] for lab in kind["laboratory"]][:2] == ["UL 8139", "IEC 62133-2"]


def test_last_hit_list():
    """Last Hit names REQ-PRT-03 and REQ-PRT-06 (both PASS) for the external short: 1 held by a test.
    REQ-ENV-06 and REQ-ESD-01 are OPEN, and it names no layout pack: 17 - 1 = 16 not held, 0 by a gate."""
    rows = {r.id: r for r in standards.judge(LAST_HIT)}
    assert len(rows) == 17
    assert rows["external-short"].status == "held by a test"
    assert rows["external-short"].how == "REQ-PRT-03 PASS, REQ-PRT-06 PASS (verification/traceability.md)"
    assert rows["fcc-radiated"].status == "not held"
    assert rows["fcc-radiated"].how == "REQ-ENV-06 is OPEN (verification/traceability.md)"
    assert rows["esd-at-connector"].how == (
        "board-rules.json names no ti-slva680a-esd; REQ-ESD-01 is OPEN (verification/traceability.md)"
    )
    assert rows["un38.3-type"].how == "product.json names no test for it"
    assert [r.status for r in rows.values()].count("not held") == 16


def test_cli_prints_every_requirement_and_the_scope_guard():
    """1 line for each of the 17 requirements, the summary, the documents, the clauses left out, the
    laboratory's standards and the documents that could not be had; exit 0, and 1 with --strict since 16
    are not held."""
    proc = run(str(LAST_HIT))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert f"STANDARDS {KIND}: 0 held by a gate, 1 held by a test, 16 not held" in out
    assert "left out: 49 CFR 173.185 173.185(g): " in out
    assert "- held by a test: external-short [49 CFR 173.185 173.185(a)(4)(ii)]" in out
    assert "A list from free documents is not a certificate." in out
    assert "  UL 8139: " in out
    assert "not had: Directive 2014/40/EU" in out
    assert sum(line.startswith("- ") for line in out.splitlines()) == 17
    assert run(str(LAST_HIT), "--strict").returncode == 1


def board_project(tmp_path: Path, fixture: str) -> Path:
    """A copy of a layout fixture of tests/boards with a product.json of the kind."""
    folder = tmp_path / fixture
    folder.mkdir()
    for name in ("layout.kicad_pcb", "board-rules.json"):
        shutil.copy(BOARDS / fixture / name, folder / name)
    (folder / "product.json").write_text(json.dumps({"kind": KIND}))
    return folder


def test_a_pack_that_holds_on_the_board_holds_by_the_gate(tmp_path):
    """pass-layout names both layout packs and breaks neither: the 2 requirements they hold are held by
    the gate; the other 17 - 2 = 15 have no test named."""
    rows = {r.id: r for r in standards.judge(board_project(tmp_path, "pass-layout"))}
    assert rows["esd-at-connector"].status == "held by a gate"
    assert rows["esd-at-connector"].how == (
        "drc, pack ti-slva680a-esd: 0 fail, 0 not judged (board-rules.json, layout.kicad_pcb)"
    )
    assert [r.status for r in rows.values()].count("held by a gate") == 2
    assert [r.status for r in rows.values()].count("not held") == 15


def test_a_pack_the_board_breaks_is_not_held(tmp_path):
    """fail-layout-esd breaks its pack on 4 lines, fail-layout-emi on 1 (tests/test_layoutrules.py):
    the requirement is not held, and the line says why."""
    rows = {r.id: r for r in standards.judge(board_project(tmp_path, "fail-layout-esd"))}
    assert rows["esd-at-connector"].status == "not held"
    assert rows["esd-at-connector"].how == "drc, pack ti-slva680a-esd: 4 fail, 0 not judged"
    rows = {r.id: r for r in standards.judge(board_project(tmp_path, "fail-layout-emi"))}
    assert rows["power-trace-ratio"].status == "not held"
    assert rows["power-trace-ratio"].how == "drc, pack ti-szza009-emi: 1 fail, 0 not judged"


def test_a_rule_left_aside_on_the_board_is_not_held(tmp_path):
    """pass-layout given 2 inner copper layers: the 3:1 rule is for a board of 2, so on 4 it judges nothing
    and the requirement it holds is not held; the ESD pack still holds."""
    folder = board_project(tmp_path, "pass-layout")
    pcb = folder / "layout.kicad_pcb"
    two = '\t\t(2 "B.Cu" signal)\n'
    pcb.write_text(pcb.read_text().replace(two, two + '\t\t(4 "In1.Cu" signal)\n\t\t(6 "In2.Cu" signal)\n'))
    rows = {r.id: r for r in standards.judge(folder)}
    assert rows["power-trace-ratio"].status == "not held"
    assert rows["power-trace-ratio"].how == (
        "drc, pack ti-szza009-emi: 0 fail, 0 not judged; ti-szza009-emi power-ratio: the rule is for a board "
        "of 2 copper layers, and this one has 4"
    )
    assert rows["esd-at-connector"].status == "held by a gate"


def nested(tmp_path: Path, inner: str) -> Path:
    """pass-layout with product.json, and a second board `inner` of tests/boards nested in it as display/,
    as Last Hit v0.16 holds v0.16/display/."""
    folder = board_project(tmp_path, "pass-layout")
    (folder / "display").mkdir()
    for name in ("layout.kicad_pcb", "board-rules.json"):
        shutil.copy(BOARDS / inner / name, folder / "display" / name)
    return folder


def test_a_nested_board_that_breaks_the_pack_is_not_held(tmp_path):
    """display/ is fail-layout-esd, which breaks ti-slva680a-esd on 4 lines and names no ti-szza009-emi:
    neither requirement is held, and each line names display/."""
    rows = {r.id: r for r in standards.judge(nested(tmp_path, "fail-layout-esd"))}
    assert rows["esd-at-connector"].status == "not held"
    assert rows["esd-at-connector"].how == "display: drc, pack ti-slva680a-esd: 4 fail, 0 not judged"
    assert rows["power-trace-ratio"].status == "not held"
    assert rows["power-trace-ratio"].how == "display: board-rules.json names no ti-szza009-emi"


def test_a_pack_held_on_every_board_is_held(tmp_path):
    """display/ is a second copy of pass-layout: both boards hold both packs."""
    rows = {r.id: r for r in standards.judge(nested(tmp_path, "pass-layout"))}
    assert rows["esd-at-connector"].status == "held by a gate"
    assert rows["esd-at-connector"].how == (
        "drc, pack ti-slva680a-esd: 0 fail, 0 not judged on each of 2 boards (layout.kicad_pcb, "
        "display/layout.kicad_pcb)"
    )


def test_a_board_that_is_not_kicad_is_refused(tmp_path):
    """An empty layout.kicad_pcb: the CLI prints 1 refusal line that names the file, exit 1."""
    folder = board_project(tmp_path, "pass-layout")
    (folder / "layout.kicad_pcb").write_text("")
    proc = run(str(folder))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert proc.stdout == "standards: layout.kicad_pcb: not a KiCad board (unterminated S-expression)\n"
    assert proc.stderr == ""


def test_a_traceability_table_not_in_utf8_is_refused(tmp_path):
    """A traceability.md with a micro sign in Latin-1 (byte 0xb5): 1 refusal line, exit 1."""
    (tmp_path / "product.json").write_text(json.dumps({"kind": KIND, "tests": {"external-short": ["REQ-1"]}}))
    (tmp_path / "verification").mkdir()
    (tmp_path / "verification" / "traceability.md").write_bytes(
        b"| ID | Check | Evidence | Measured | Verdict |\n|---|---|---|---|---|\n"
        b"| REQ-1 | test | x | 5 \xb5A | PASS |\n"
    )
    proc = run(str(tmp_path))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert proc.stdout.startswith("standards: verification/traceability.md: not UTF-8")
    assert proc.stderr == ""


@pytest.mark.parametrize("verdicts", [("FAIL", "PASS"), ("PASS", "FAIL"), ("PASS", "PASS")])
def test_an_id_in_2_rows_is_not_held(tmp_path, verdicts):
    """REQ-1 stands in 2 rows: the package holds 1 row per requirement, so the test holds nothing, whatever
    the rows say and in whichever order."""
    (tmp_path / "product.json").write_text(json.dumps({"kind": KIND, "tests": {"external-short": ["REQ-1"]}}))
    (tmp_path / "verification").mkdir()
    rows = "".join(f"| REQ-1 | test | x | y | {v} |\n" for v in verdicts)
    (tmp_path / "verification" / "traceability.md").write_text(
        "| ID | Check | Evidence | Measured | Verdict |\n|---|---|---|---|---|\n" + rows
    )
    got = {r.id: r for r in standards.judge(tmp_path)}["external-short"]
    assert got.status == "not held"
    assert got.how == f"REQ-1 stands in 2 rows ({', '.join(verdicts)}) of verification/traceability.md"


def test_a_named_pack_with_no_board_is_not_held(tmp_path):
    """board-rules.json names both packs and there is no board to judge: nothing is held by a gate."""
    (tmp_path / "product.json").write_text(json.dumps({"kind": KIND}))
    (tmp_path / "board-rules.json").write_text(json.dumps({"layout": ["ti-slva680a-esd", "ti-szza009-emi"]}))
    rows = {r.id: r for r in standards.judge(tmp_path)}
    assert rows["esd-at-connector"].status == "not held"
    assert rows["esd-at-connector"].how == "drc, pack ti-slva680a-esd: no .kicad_pcb in the project to judge"
    assert [r.status for r in rows.values()].count("held by a gate") == 0


def test_every_paragraph_of_173_185_is_listed_or_left_out():
    """49 CFR 173.185 (eCFR as of 2026-11-01) has the paragraphs (a) to (h). Each is a requirement of the
    kind or is left out with a reason; (a)(4)(i), (a)(4)(iii) and (a)(5) are requirements."""
    kind = standards.read_kind(KIND)
    clauses = [r["clause"] for r in kind["requirements"] if r["document"] == "49-cfr-173-185"]
    clauses += [g["clause"] for g in kind["left_out"] if g["document"] == "49-cfr-173-185"]
    assert {c.split("(")[1][0] for c in clauses} == set("abcdefgh")
    for clause in ("173.185(a)(4)(i)", "173.185(a)(4)(iii)", "173.185(a)(5)"):
        assert any(r["clause"].startswith(clause) for r in kind["requirements"]), clause


def test_a_test_not_in_the_package_is_not_held(tmp_path):
    (tmp_path / "product.json").write_text(
        json.dumps({"kind": KIND, "tests": {"external-short": ["REQ-X-01"]}})
    )
    rows = {r.id: r for r in standards.judge(tmp_path)}
    assert rows["external-short"].how == "REQ-X-01 is not in verification/traceability.md"


@pytest.mark.parametrize(
    ("data", "match"),
    [
        (
            {"kind": "toaster"},
            "kind: `toaster` is no product kind; Via holds vaping-device-lithium-cell",
        ),
        ({"kind": KIND, "tests": {"no-such": ["REQ-A-01"]}}, "tests: `no-such` is no requirement of"),
        ({"kind": KIND, "extra": 1}, "`extra` is no key here"),
    ],
)
def test_refusals(tmp_path, data, match):
    (tmp_path / "product.json").write_text(json.dumps(data))
    with pytest.raises(Refusal, match=match):
        standards.judge(tmp_path)


def test_no_product_file_is_refused_by_the_cli(tmp_path):
    proc = run(str(tmp_path))
    assert proc.returncode == 1
    assert "product.json: there is none" in proc.stdout
