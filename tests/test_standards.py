"""`workcenter standards`: a product kind's requirements from free documents, each held by a gate, held by
a named test, or not held (tools/standards.py, rules/products/).

The fixture `tests/products/last-hit` is Last Hit v0.16 (a vaping device with a lithium cell): its
`product.json` names 4 of its verification requirements, and its `verification/traceability.md` holds
those 4 rows as the project's v0.16 has them."""

from __future__ import annotations

import json
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
KIND = "vaping-device-lithium-cell"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CLI), "standards", *args], capture_output=True, text=True)


def test_kind_names_each_document_and_lab_standard():
    """10 requirements from 4 documents; the paid standards are named, with no number of theirs."""
    kind = standards.read_kind(KIND)
    assert len(kind["requirements"]) == 10
    assert sorted(kind["documents"]) == ["47-cfr-15-b", "49-cfr-173-185", "ti-slva680a", "ti-szza009"]
    assert [lab["standard"] for lab in kind["laboratory"]][:2] == ["UL 8139", "IEC 62133-2"]


def test_last_hit_list():
    """Last Hit names REQ-PRT-03 and REQ-PRT-06 (both PASS) for the external short: 1 held by a test.
    REQ-ENV-06 and REQ-ESD-01 are OPEN, and it names no layout pack: 10 - 1 = 9 not held, 0 by a gate."""
    rows = {r.id: r for r in standards.judge(LAST_HIT)}
    assert len(rows) == 10
    assert rows["external-short"].status == "held by a test"
    assert rows["external-short"].how == "REQ-PRT-03 PASS, REQ-PRT-06 PASS (verification/traceability.md)"
    assert rows["fcc-radiated"].status == "not held"
    assert rows["fcc-radiated"].how == "REQ-ENV-06 is OPEN (verification/traceability.md)"
    assert rows["esd-at-connector"].how == (
        "board-rules.json names no ti-slva680a-esd; REQ-ESD-01 is OPEN (verification/traceability.md)"
    )
    assert rows["un38.3-type"].how == "product.json names no test for it"
    assert [r.status for r in rows.values()].count("not held") == 9


def test_cli_prints_every_requirement_and_the_scope_guard():
    """1 line for each of the 10 requirements, the summary, the documents, the laboratory's standards and
    the documents that could not be had; exit 0, and 1 with --strict since 9 are not held."""
    proc = run(str(LAST_HIT))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert f"STANDARDS {KIND}: 0 held by a gate, 1 held by a test, 9 not held" in out
    assert "- held by a test: external-short [49 CFR 173.185 173.185(a)(4)(ii)]" in out
    assert "A list from free documents is not a certificate." in out
    assert "  UL 8139: " in out
    assert "not had: Directive 2014/40/EU" in out
    assert sum(line.startswith("- ") for line in out.splitlines()) == 10
    assert run(str(LAST_HIT), "--strict").returncode == 1


def test_a_named_pack_holds_by_the_gate(tmp_path):
    """board-rules.json naming both layout packs: the 2 requirements the packs hold are held by the DRC
    gate; the 8 others have no test named: 2 by a gate, 0 by a test, 8 not held."""
    (tmp_path / "product.json").write_text(json.dumps({"kind": KIND}))
    (tmp_path / "board-rules.json").write_text(json.dumps({"layout": ["ti-slva680a-esd", "ti-szza009-emi"]}))
    rows = {r.id: r for r in standards.judge(tmp_path)}
    assert rows["esd-at-connector"].status == "held by a gate"
    assert rows["esd-at-connector"].how == "drc, pack ti-slva680a-esd (board-rules.json)"
    assert [r.status for r in rows.values()].count("held by a gate") == 2
    assert [r.status for r in rows.values()].count("not held") == 8


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
            "kind: `toaster` is no product kind; the workcenter holds vaping-device-lithium-cell",
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
