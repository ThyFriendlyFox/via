"""EXPORT's files for a fab and an assembler, written by kicad-cli 10 (and KiKit for a panel) on a copy
of the fixture pass-first-design, and read back here by the test itself.

The board has 4 parts on its top, C1, J1, R1 and R2, none on its back; 3 nets, VCC, /OUT and GND; 2
copper layers; an outline 25 by 20 mm. A panel test needs a Python that imports KiKit: KIKIT_PYTHON,
else Via's venv's. It skips, and says so, when there is none.
"""

from __future__ import annotations

import csv
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from conftest import engine

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
FIXTURE = ROOT / "tests" / "boards" / "pass-first-design"
PANEL = ROOT / "tests" / "samples" / "fab" / "panel.json"
sys.path.insert(0, str(ROOT / "tools"))
import fabfiles  # noqa: E402

needs_kicad = engine(
    pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
)
PARTS = {"C1": "top", "J1": "top", "R1": "top", "R2": "top"}


def kikit_python() -> str | None:
    venv = Path(os.environ.get("WORKCENTER_ROOT", "/opt/workcenters/ee")) / "venv" / "bin" / "python"
    for py in (os.environ.get("KIKIT_PYTHON"), str(venv)):
        if py and Path(py).exists():
            probe = subprocess.run(
                [py, "-I", "-c", "import kikit.panelize_ui"], capture_output=True, check=False, cwd=ROOT
            )
            if probe.returncode == 0:
                return py
    return None


def project(tmp_path: Path, panel: bool = False) -> Path:
    folder = tmp_path / "board"
    shutil.copytree(FIXTURE, folder, ignore=shutil.ignore_patterns("build", "*.kicad_prl"))
    if panel:
        shutil.copy(PANEL, folder / "panel.json")
    return folder


def export(folder: Path, out: Path, env: dict | None = None, cwd: Path | None = None) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", "export", str(folder), "--out", str(out)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
        cwd=cwd,
    )
    return proc.returncode, json.loads(proc.stdout)[0]


def plant(folder: Path, marker: Path) -> None:
    """Python modules a board repository could carry, each writing 1 line to `marker` when imported."""
    line = f"open({str(marker)!r}, 'a').write(__name__ + ' ' + __file__ + '\\n')\n"
    (folder / "kikit").mkdir()
    for name in ("kikit/__init__.py", "kikit/panelize_ui.py", "pcbnew.py", "sitecustomize.py"):
        (folder / name).write_text(line, encoding="utf-8")


@needs_kicad
def test_export_writes_a_placement_file_ipc2581_and_an_assembly_drawing_that_agree_with_the_board(tmp_path):
    code, result = export(project(tmp_path), tmp_path / "out")
    assert code == 0 and result["status"] == "pass", result
    fab = tmp_path / "out" / "fab"
    with (fab / "placement.csv").open(encoding="utf-8") as f:
        assert {row["Ref"]: row["Side"] for row in csv.DictReader(f)} == PARTS
    root = ET.parse(fab / "divider.ipc2581.xml").getroot()
    conductors = {e.get("name") for e in root.iter() if e.get("layerFunction") == "CONDUCTOR"}
    assert conductors == {"F.Cu", "B.Cu"}
    assert {e.get("net") for e in root.iter() if e.get("net") is not None} == {"VCC", "/OUT", "GND"}
    page = (fab / "assembly-top.pdf").read_bytes()
    assert set(fabfiles.PDF_REF.findall(page)) == {b"C1", b"J1", b"R1", b"R2"}
    assert {"C1", "J1", "R1", "R2"} <= set(fabfiles.drawn_words(page))
    # no part on the back, so no page for it
    assert not (fab / "assembly-bottom.pdf").exists()
    assert result["details"]["failures"] == []
    assert "3 files read back" in result["summary"], result["summary"]


@needs_kicad
def test_a_placement_file_that_disagrees_with_the_board_fails_export_on_1_line(tmp_path):
    """kicad-cli stands behind a script that drops R2's row from the placement file it wrote: the gate
    reads the file back and names R2, the 1 part the file lost."""
    real = shutil.which("kicad-cli")
    wrapper = tmp_path / "kicad-cli"
    wrapper.write_text(
        "#!/bin/sh\n"
        f'"{real}" "$@" || exit $?\n'
        'case "$*" in *"export pos"*)\n'
        '  out=""; prev=""\n'
        '  for a in "$@"; do [ "$prev" = "--output" ] && out="$a"; prev="$a"; done\n'
        '  grep -v \'^"R2"\' "$out" > "$out.tmp" && mv "$out.tmp" "$out";;\n'
        "esac\n",
        encoding="utf-8",
    )
    wrapper.chmod(0o755)
    code, result = export(project(tmp_path), tmp_path / "out", {"KICAD_CLI": str(wrapper)})
    assert code == 1 and result["status"] == "fail", result
    assert result["details"]["failures"] == [
        "placement.csv: R2 is not in the file; the board places it on the top"
    ]


@needs_kicad
def test_a_part_not_fitted_is_in_no_placement_file_and_not_drawn_on_the_assembly_page(tmp_path):
    """R2 is set DNP in the copy's board: the placement file leaves it out and the top page hides it.
    Without --hide-DNP-footprints-on-fab-layers kicad-cli draws its designator (a run on 2026-11-17)."""
    folder = project(tmp_path)
    pcb = folder / "divider.kicad_pcb"
    head, tail = pcb.read_text(encoding="utf-8").split('(property "Reference" "R2"', 1)
    pcb.write_text(
        head + '(property "Reference" "R2"' + tail.replace("(attr smd)", "(attr smd dnp)", 1), "utf-8"
    )
    code, result = export(folder, tmp_path / "out")
    assert code == 0 and result["status"] == "pass", result
    fab = tmp_path / "out" / "fab"
    with (fab / "placement.csv").open(encoding="utf-8") as f:
        assert {row["Ref"] for row in csv.DictReader(f)} == {"C1", "J1", "R1"}
    drawn = set(fabfiles.drawn_words((fab / "assembly-top.pdf").read_bytes()))
    assert {"C1", "J1", "R1"} <= drawn and "R2" not in drawn


@needs_kicad
def test_a_panel_asked_for_without_kikit_is_not_judged(tmp_path):
    """A Python without KiKit stands in for Via's: the panel cannot be made, so EXPORT is
    SKIPPED with exit 2 and says why, and the board's own files are still written and read back."""
    code, result = export(
        project(tmp_path, panel=True), tmp_path / "out", {"KIKIT_PYTHON": "/usr/bin/python3"}
    )
    assert code == 2 and result["status"] == "skip", result
    assert "panel not judged: KiKit" in result["summary"], result["summary"]
    assert (tmp_path / "out" / "fab" / "placement.csv").is_file()


@needs_kicad
@pytest.mark.skipif(kikit_python() is None, reason="no Python here imports KiKit (set KIKIT_PYTHON)")
def test_a_panel_of_2_by_2_boards_is_made_and_read_back(tmp_path):
    """The preset asks for 2 by 2 boards 2 mm apart and 5 mm rails 2 mm off the top and bottom:
    2 x 25 + 2 = 52 mm wide, 2 x 20 + 2 + 2 x (5 + 2) = 56 mm high."""
    code, result = export(project(tmp_path, panel=True), tmp_path / "out", {"KIKIT_PYTHON": kikit_python()})
    assert code == 0 and result["status"] == "pass", result
    panel_dir = tmp_path / "out" / "fab" / "panel"
    text = (panel_dir / "divider-panel.kicad_pcb").read_text(encoding="utf-8")
    facts = fabfiles.board_facts((FIXTURE / "divider.kicad_pcb").read_text(encoding="utf-8"))
    lines, info = fabfiles.check_panel(text, facts, 2, 2, "panel")
    assert lines == [] and info == {"boards": 4, "width": 52.0, "height": 56.0}
    assert result["details"]["panel"]["boards"] == 4
    gerbers = sorted(p.name for p in (panel_dir / "gerbers").iterdir())
    assert any(n.endswith("Edge_Cuts.gm1") for n in gerbers) and any(n.endswith(".drl") for n in gerbers), (
        gerbers
    )
    assert "panel 2 x 2 boards, 52 x 56 mm" in result["summary"], result["summary"]


@needs_kicad
@pytest.mark.skipif(kikit_python() is None, reason="no Python here imports KiKit (set KIKIT_PYTHON)")
def test_export_imports_no_python_module_of_the_board_or_of_the_working_directory(tmp_path):
    """R16-N1 (a): the KiKit probe was `python -c "import kikit.panelize_ui"` in the caller's working
    directory, which `-c` puts first on the import path, so a `kikit/` folder there ran. `kikit/`,
    `pcbnew.py` and `sitecustomize.py` that write a marker sit in the working directory and in the
    project's folder: the panel is made by the real KiKit, and the marker is never written."""
    marker = tmp_path / "planted-ran.txt"
    folder = project(tmp_path, panel=True)
    plant(tmp_path, marker)
    plant(folder, marker)
    code, result = export(folder, tmp_path / "out", {"KIKIT_PYTHON": kikit_python()}, cwd=tmp_path)
    assert not marker.exists(), marker.read_text(encoding="utf-8")
    assert code == 0 and result["status"] == "pass", result
    assert "panel 2 x 2 boards, 52 x 56 mm" in result["summary"], result["summary"]


PRESET_CODE = {
    "tabs": {"type": "plugin", "code": "{evil}.Tabs"},
    "text": {"type": "simple", "text": "x", "plugin": "{evil}.Text"},
    "post": {"script": "{evil}"},
}


@pytest.mark.skipif(kikit_python() is None, reason="no Python here imports KiKit (set KIKIT_PYTHON)")
@pytest.mark.parametrize("section", sorted(PRESET_CODE))
def test_a_panel_preset_that_names_python_to_run_is_refused_before_kikit_reads_it(tmp_path, section):
    """R16-N1: a KiKit preset runs Python of its own: a section's `code` plugin and a text's `plugin`
    are loaded while KiKit reads the preset, and `post.script` after the panel is built. panel.json is
    the board repository's file, so tools/panel.py refuses such a preset on 1 line before KiKit reads it,
    and the file it names is never run. No board is loaded: the refusal comes first."""
    marker = tmp_path / "planted-ran.txt"
    evil = tmp_path / "evil.py"
    evil.write_text(
        f"open({str(marker)!r}, 'a').write('ran\\n')\nclass Tabs: ...\nclass Text: ...\n", "utf-8"
    )
    body = json.loads(json.dumps(PRESET_CODE[section]).replace("{evil}", str(evil)))
    preset = tmp_path / "panel.json"
    preset.write_text(json.dumps({"layout": {"type": "grid", "rows": 2, "cols": 2}, section: body}), "utf-8")
    key = {"tabs": "tabs.code", "text": "text.plugin", "post": "post.script"}[section]
    value = body[key.split(".")[1]]
    proc = subprocess.run(
        [kikit_python(), "-I", ROOT / "tools" / "panel.py", "no.kicad_pcb", "out.kicad_pcb", preset],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert not marker.exists()
    assert proc.returncode == 1, proc.stderr
    assert proc.stderr.strip().splitlines()[-1] == (
        f"{preset}: {key} names Python for KiKit to run ({value}): the gates run no code a "
        "board's panel.json names; use a built-in KiKit type"
    )
