"""Roadmap item 7, the planted fault of the parts the SIM gate asks for, on a whole board: kicad-cli reads
the schematic's parts and ngspice runs the deck, so this file starts both engines.

tests/boards/pass-block-ldo is the linear regulator block's board: U1, a TLV75533PDBVR (parts.csv), whose
facts (tests/boards/library/facts/ti-tlv755p.json) carry junction_max 150 C (TLV755P datasheet SBVS320D,
section 5.1, page 4) and RthetaJA 231.1 C/W with 4 more figures (section 5.4, page 5). Without its row in
sim/thermal.json U1 is not judged and `--strict` fails; with the row it is held.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import engine

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"

# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {"ti-sbvs320": "sections 5.1 and 5.4, pages 4 and 5"}

needs_engines = engine(
    pytest.mark.skipif(
        shutil.which("ngspice") is None or shutil.which("kicad-cli") is None,
        reason="ngspice or kicad-cli is not installed",
    )
)
UNPLANNED = (
    "thermal: U1 (TLV75533PDBVR) not judged: its facts (ti-tlv755p.json) carry junction_max 150 C and "
    "theta_ja 231.1 C/W, theta_jc 118.4 C/W, theta_jb 64.4 C/W, psi_jt 28.4 C/W and psi_jb 63.8 C/W (p 4 "
    "and 5), and sim/thermal.json names no row for it"
)


def copy_of(tmp_path: Path) -> Path:
    shutil.copytree(BOARDS / "library", tmp_path / "boards" / "library")
    project = tmp_path / "boards" / "ldo"
    shutil.copytree(BOARDS / "pass-block-ldo", project, ignore=shutil.ignore_patterns("build"))
    return project


def sim(project: Path, out: Path) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", "sim", str(project), "--out", str(out), "--strict"],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, json.loads(proc.stdout)[0]


@needs_engines
def test_a_part_with_thermal_facts_and_no_row_is_not_judged_and_the_same_board_with_the_row_is_held(tmp_path):
    """The planted fault: pass-block-ldo with no sim/thermal.json. U1's facts carry a thermal figure, so
    the gate asks for it: 1 not-judged line, a failure under --strict. The same board with its row: U1
    held, and the board's line says the plan names the 1 part that carries a figure. pass-block-ldo is
    not GREEN under --strict today for 2 lines of its own (its regulator's load deck, its capacitors'
    data). Taking the file out adds 2 lines to them: U1's, and the gate's older warning that no measure
    of `ldo` moves with temperature, which a deck the file names is spared (the simulate skill, Corners,
    step 3). The row takes both away."""
    project = copy_of(tmp_path)
    plan = (project / "sim" / "thermal.json").read_text(encoding="utf-8")
    (project / "sim" / "thermal.json").unlink()
    code, bare = sim(project, tmp_path / "bare")
    assert code == 1
    asked = [f for f in bare["details"]["failures"] if f.startswith("thermal: ")]
    assert len(asked) == 1 and asked[0].startswith(UNPLANNED), bare["details"]["failures"]
    assert bare["details"]["thermal"]["board"]["unplanned"] == ["U1"]
    (project / "sim" / "thermal.json").write_text(plan, encoding="utf-8")
    code, record = sim(project, tmp_path / "planned")
    assert not [f for f in record["details"]["failures"] if f.startswith("thermal")]
    still = "ldo: no measure moves with temperature: nothing in the deck or its models carries one"
    assert sorted(bare["details"]["failures"]) == sorted([*asked, still, *record["details"]["failures"]])
    assert len(record["details"]["failures"]) == 2, record["details"]["failures"]
    heated = record["details"]["thermal"]
    assert heated["parts"]["U1"]["held"] is True
    assert heated["board"]["line"] == (
        "thermal: 1 part of the board carries a thermal figure in its facts: U1; sim/thermal.json names 1 "
        "of them"
    )
