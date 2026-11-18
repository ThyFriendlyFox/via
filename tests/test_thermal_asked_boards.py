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


def copy_of(tmp_path: Path, board: str = "pass-block-ldo") -> Path:
    shutil.copytree(BOARDS / "library", tmp_path / "boards" / "library")
    project = tmp_path / "boards" / "ldo"
    shutil.copytree(BOARDS / board, project, ignore=shutil.ignore_patterns("build"))
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


@needs_engines
def test_a_row_that_names_the_wson_part_for_the_board_s_sot_23_part_fails(tmp_path):
    """Finding L7B-1. parts.csv gives U1 the DBV part, TLV75533PDBVR (RthetaJA 231.1 C/W, SBVS320D
    section 5.4, page 5); the row names the DRV part, TLV75533PDRVR (100.2 C/W, the same table). The gate
    judged U1 on the DRV facts and held it: now the row fails, and U1 is not held."""
    project = copy_of(tmp_path)
    plan = json.loads((project / "sim" / "thermal.json").read_text(encoding="utf-8"))
    plan["parts"]["U1"]["mpn"] = "TLV75533PDRVR"
    (project / "sim" / "thermal.json").write_text(json.dumps(plan), encoding="utf-8")
    code, record = sim(project, tmp_path / "out")
    assert code == 1
    assert (
        "thermal: U1 (TLV75533PDBVR) is judged on facts that are not its own: its row in sim/thermal.json "
        "names TLV75533PDRVR, and parts.csv gives TLV75533PDBVR: write the board's part number in its row "
        "(the simulate skill, A part's temperature, step 3)"
    ) in record["details"]["failures"]
    assert record["details"]["thermal"]["parts"]["U1"]["held"] is False
    assert record["details"]["thermal"]["board"]["line"].endswith("sim/thermal.json names 0 of them")


@needs_engines
def test_with_the_parts_list_elsewhere_the_regulator_is_not_judged_and_no_part_is_said_to_carry_none(
    tmp_path,
):
    """Finding L7B-2. pass-block-ldo with parts.csv moved to ../parts/catalog.csv (Last Hit's layout) and
    no sim/thermal.json: U1 has no part number, so no facts entry; its 5 pins are the DBV entry's. The gate
    cannot say that no part carries a thermal figure: U1 is not judged, a failure under --strict."""
    project = copy_of(tmp_path)
    (project / "sim" / "thermal.json").unlink()
    (tmp_path / "boards" / "parts").mkdir()
    (project / "parts.csv").rename(tmp_path / "boards" / "parts" / "catalog.csv")
    code, record = sim(project, tmp_path / "out")
    assert code == 1
    asked = [f for f in record["details"]["failures"] if f.startswith("thermal: U1")]
    assert asked == [
        "thermal: U1 not judged: the project has no parts.csv to give its part number and no facts entry "
        "names it by its symbol, and it has the pins of TLV75533PDBVR (ti-tlv755p.json), whose facts carry "
        "a thermal figure: give its part number in parts.csv beside the schematic, the file the gate reads "
        "it from"
    ]
    assert "no part of the board carries" not in record["details"]["thermal"]["board"]["line"]


@needs_engines
def test_a_board_with_no_deck_still_asks_for_its_charger_s_junction(tmp_path):
    """Finding L7B-3. pass-block-charger with its sim/ folder taken away: U1, BQ21040DBVR, whose facts
    carry junction_max 150 C and RthetaJA 130.8 C/W (BQ21040 datasheet, sections 7.1 and 7.4, pages 3 and
    4), is not judged, and --strict fails where the gate skipped before."""
    project = copy_of(tmp_path, "pass-block-charger")
    shutil.rmtree(project / "sim")
    code, record = sim(project, tmp_path / "out")
    assert code == 1 and record["status"] == "fail"
    assert [f[:46] for f in record["details"]["failures"]] == [
        "thermal: U1 (BQ21040DBVR) not judged: its fact"
    ]
