"""Fabrication house rule sets (rules/*.kicad_dru): `workcenter drc|gates --fab` and `Design.fab`.

The fixture fail-fab-sierra is the passing divider with a 0.6/0.3 mm via (a 0.15 mm ring) and a legend
label stroked 0.10 mm: GREEN on the gates, RED with Sierra Circuits' Web PCB limits (6 mil ring, 5 mil
legend). KiCad-dependent tests skip when kicad-cli is absent.
"""

from __future__ import annotations

import argparse
import importlib.machinery
import json
import os
import shutil
import subprocess
import sys
import types
import uuid
from pathlib import Path

import pytest
from conftest import engine

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
sys.path.insert(0, str(ROOT / "tools"))
import kicadgen  # noqa: E402

SIERRA = "sierra-circuits-web"
# A design that writes its project loads KiCad's power symbols (tools/kicadgen.py SYMBOL_DIR).
needs_libs = pytest.mark.skipif(
    not (kicadgen.SYMBOL_DIR / "power.kicad_sym").is_file(), reason="KiCad symbol libraries are not installed"
)
needs_kicad = engine(
    pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
)


def run(*args: object) -> tuple[int, list[dict]]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", *map(str, args)], capture_output=True, text=True, check=False
    )
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else [])


def drc_types(out: Path) -> set[str]:
    data = json.loads((out / "drc.json").read_text(encoding="utf-8"))
    return {v["type"] for v in data["violations"]}


@needs_kicad
def test_fixture_is_green_without_the_fab_and_red_with_it(tmp_path):
    code, records = run("gates", BOARDS / "fail-fab-sierra", "--strict", "--out", tmp_path / "plain")
    assert code == 0, records
    code, records = run("gates", BOARDS / "fail-fab-sierra", "--fab", SIERRA, "--out", tmp_path / "fab")
    assert code == 1
    assert [r["gate"] for r in records] == ["erc", "drc"]
    drc = records[1]
    assert drc["status"] == "fail" and drc["details"]["fab"] == SIERRA
    assert {"annular_width", "text_thickness"} <= drc_types(tmp_path / "fab")
    rules = {v["description"] for v in drc["details"]["first"]}
    # the ring is a board-wide limit, so the copy's own minimum carries it (M62); the legend rule has
    # a condition and stays a rule
    assert any("board setup constraints min annular width 0.1524 mm" in r for r in rules), rules
    assert any("sierra-web: legend text stroke 5 mil" in r for r in rules), rules


@needs_kicad
def test_the_passing_divider_meets_the_fab_and_the_project_is_untouched(tmp_path):
    """Sierra's pages name no least text height, so the legend check leaves the divider's text height not
    judged (tools/legend.py): the board meets every limit Sierra names, and only `--strict` fails it, on
    that 1 line."""
    before = sorted(p.name for p in (BOARDS / "pass-rc-divider").iterdir())
    code, records = run("drc", BOARDS / "pass-rc-divider", "--fab", SIERRA, "--out", tmp_path / "plain")
    assert code == 0, records
    (drc,) = records
    assert drc["details"]["failures"] == [] and drc["summary"].startswith("0 errors, 0 warnings")
    (line,) = drc["details"]["warnings"]
    assert line.startswith("legend not judged: text height on ")
    assert f"fab {SIERRA} names no least height" in line
    code, records = run("drc", BOARDS / "pass-rc-divider", "--fab", SIERRA, "--strict", "--out", tmp_path)
    assert code == 1, records
    assert records[0]["details"]["failures"] == [line]
    assert not (BOARDS / "pass-rc-divider" / "rc_divider.kicad_dru").exists()
    assert sorted(p.name for p in (BOARDS / "pass-rc-divider").iterdir() if p.name != "build") == [
        n for n in before if n != "build"
    ]


def test_an_unknown_fab_is_refused_with_the_known_ones(tmp_path):
    code, records = run("drc", BOARDS / "pass-rc-divider", "--fab", "nofab", "--out", tmp_path)
    (record,) = records
    assert record["status"] == "error" and code != 0
    assert SIERRA in record["summary"]


def test_fab_minimums_are_the_board_wide_rules_only():
    mins = kicadgen.fab_minimums(kicadgen.fab_rules(SIERRA).read_text(encoding="utf-8"))
    assert mins == {
        "min_track_width": 0.1016,
        "min_clearance": 0.1016,
        "min_through_hole_diameter": 0.1524,
        "min_via_annular_width": 0.1524,
    }  # the inner-layer drill rule and the legend rule stay in the rule file


def test_design_fab_raises_the_board_rules_and_refuses_the_fabs_vias(tmp_path):
    d = kicadgen.Design(name="t", namespace=uuid.UUID(int=11), fab=SIERRA)
    rules = d.board_rules()
    assert rules["min_via_annular_width"] == 0.1524  # raised from Via's 0.1
    assert rules["min_through_hole_diameter"] == 0.3  # the board's own is stricter and stays
    assert any("annular ring 0.15 is below the board's minimum 0.1524" in p for p in d.check_via_rules())
    d.via_size, d.via_drill = 0.65, 0.3  # a 0.175 mm ring
    assert d.check_via_rules() == []
    d.rules = {"min_via_annular_width": 0.2}  # a design's own rule still wins
    assert d.board_rules()["min_via_annular_width"] == 0.2


@needs_libs
def test_design_fab_writes_the_rule_file_into_the_project(tmp_path):
    d = kicadgen.Design(name="t", namespace=uuid.UUID(int=12), fab=SIERRA)
    d.outline = (100.0, 100.0, 110.0, 110.0)
    written = d.write(tmp_path)
    dru = tmp_path / "t.kicad_dru"
    assert dru in written
    text = dru.read_text(encoding="utf-8")
    assert text.startswith("(version 1)") and "sierra-web: inner drill to copper 13 mil" in text
    assert "\n# Copied by Via from sierra-circuits-web.kicad_dru (Design.fab)" in text
    assert "the workcenter" not in text  # the product is Via (docs/STYLE.md, Terms)
    plain = kicadgen.Design(name="p", namespace=uuid.UUID(int=13))
    plain.outline = (100.0, 100.0, 110.0, 110.0)
    plain.write(tmp_path)
    assert not (tmp_path / "p.kicad_dru").exists()


def test_the_project_rule_file_never_loosens_the_boards_own_rules():
    text = kicadgen.fab_rules(SIERRA).read_text(encoding="utf-8")
    kept = kicadgen.fab_project_rules(text, {"min_hole_clearance": 0.25, "min_text_thickness": 0.1})
    # a board-wide rule would override every net class's clearance with the fab's 4 mil (M62)
    assert "(constraint clearance" not in kept and "(constraint track_width" not in kept
    assert "(constraint annular_width" not in kept and "(constraint hole_size" not in kept
    assert "is board-wide: carried as the board's own minimum (min_clearance 0.1016 mm)" in kept
    assert "(constraint hole_clearance (min 0.3302mm))" in kept  # the fab's is the stricter
    assert "(constraint text_thickness (min 0.127mm))" in kept
    stricter = kicadgen.fab_project_rules(text, {"min_hole_clearance": 0.4, "min_text_thickness": 0.13})
    assert "(constraint hole_clearance (min 0.4mm))" in stricter  # the board's own is the stricter
    assert "(constraint text_thickness (min 0.13mm))" in stricter


def narrow_pair(name: str, n: int, fab: str = "") -> kicadgen.Design:
    """Net A in a class with 0.3 mm clearance, and net B's track 0.25 mm beside it: wide enough for the
    board's 0.2 mm and the fab's 4 mil, too narrow for the class."""
    d = kicadgen.Design(name=name, namespace=uuid.UUID(int=n), outline=(100.0, 100.0, 112.0, 110.0), fab=fab)
    d.add(
        "R1",
        "Device:R",
        "10k",
        "Resistor_SMD:R_0603_1608Metric",
        sch_at=(50.8, 50.8),
        pcb_at=(103.0, 103.0),
        nets={"1": "A", "2": "B"},
    )
    d.net_classes = {"Wide": {"width": 0.2, "clearance": 0.3, "via": 0.6, "via_drill": 0.3, "nets": ["A"]}}
    d.track("A", [(102.225, 103.0), (102.225, 108.0)], "F.Cu", width=0.2)
    d.track("B", [(103.775, 103.0), (103.775, 106.0), (102.675, 106.0), (102.675, 108.0)], "F.Cu", width=0.2)
    return d


def class_clearances(out: Path) -> list[str]:
    data = json.loads((out / "drc.json").read_text(encoding="utf-8"))
    return [v["description"] for v in data["violations"] if v["type"] == "clearance"]


@needs_kicad
def test_a_net_class_clearance_holds_under_the_fab(tmp_path):
    """A fab rule file must add the fab's floors, never replace the board's own rules: under the
    Sierra rules a 0.25 mm gap next to a 0.3 mm net class is still a clearance error (M62)."""
    plain = tmp_path / "plain"
    narrow_pair("nc", 62).write(plain)
    run("drc", plain, "--out", plain / "build")
    assert any("clearance 0.3000 mm" in d for d in class_clearances(plain / "build"))

    with_fab = tmp_path / "fab"
    narrow_pair("nc", 62, fab=SIERRA).write(with_fab)
    assert "(constraint clearance" not in (with_fab / "nc.kicad_dru").read_text(encoding="utf-8")
    run("drc", with_fab, "--out", with_fab / "build")
    assert any("clearance 0.3000 mm" in d for d in class_clearances(with_fab / "build"))

    code, records = run("drc", plain, "--fab", SIERRA, "--out", tmp_path / "once")
    assert code == 1 and records[0]["details"]["fab"] == SIERRA
    assert any("clearance 0.3000 mm" in d for d in class_clearances(tmp_path / "once"))


def test_an_unknown_design_fab_is_refused():
    with pytest.raises(ValueError, match="no fab rule set 'nofab'"):
        kicadgen.Design(name="t", namespace=uuid.UUID(int=14), fab="nofab").board_rules()


# ------------------------------------------------- design --rules-only

# A design file the command line builds: a fab named, no parts; writing it still loads KiCad's power
# symbols, so every test that builds it needs the libraries.
RULES_DESIGN = """\
import uuid
import kicadgen


def build():
    d = kicadgen.Design(name="t", namespace=uuid.UUID(int=15){fab})
    d.outline = (100.0, 100.0, 110.0, 110.0)
    return d
"""
OLDER = "# Copied by the workcenter from "  # the header of a rule file written before 2026-11-19
TODAY = "# Copied by Via from "


def rules_project(tmp_path: Path, fab: str = SIERRA) -> Path:
    """A project as `workcenter design` writes it, then routed: the .kicad_pcb is no longer what
    the design writes, as on a committed board."""
    design = tmp_path / "design.py"
    design.write_text(RULES_DESIGN.format(fab=f", fab={fab!r}" if fab else ""), encoding="utf-8")
    kicadgen.load_design(design).write(tmp_path)
    pcb = tmp_path / "t.kicad_pcb"
    pcb.write_text(pcb.read_text(encoding="utf-8") + "# routed by hand for this test\n", encoding="utf-8")
    return design


def rules_only(design: Path, *more: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), "design", str(design), "--rules-only", *more],
        capture_output=True,
        text=True,
        check=False,
    )


def load_cli() -> types.ModuleType:
    """The command line as a module, to run `design --rules-only` in this process."""
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_fab", str(CLI))
    module = types.ModuleType("workcenter_cli_fab")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module  # dataclasses look the defining module up here
    loader.exec_module(module)
    return module


def project_bytes(folder: Path) -> dict[str, bytes]:
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir()) if p.is_file()}


@needs_libs
def test_rules_only_writes_the_older_header_again_and_nothing_else(tmp_path):
    design = rules_project(tmp_path)
    dru = tmp_path / "t.kicad_dru"
    written = dru.read_text(encoding="utf-8")
    assert written.count(TODAY) == 1
    dru.write_text(written.replace(TODAY, OLDER), encoding="utf-8")
    before = project_bytes(tmp_path)
    proc = rules_only(design)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert dru.read_text(encoding="utf-8") == written
    after = project_bytes(tmp_path)
    assert sorted(after) == sorted(before)  # no file added, none left behind by the atomic write
    assert {n: b for n, b in after.items() if n != "t.kicad_dru"} == {
        n: b for n, b in before.items() if n != "t.kicad_dru"
    }  # the routed .kicad_pcb, the .kicad_sch and the .kicad_pro are byte for byte as they were
    line = next(i for i, ln in enumerate(written.split("\n"), start=1) if ln.startswith(TODAY))
    assert proc.stdout.strip().split("\n") == [
        f"rules: wrote {dru}: its header, line {line}, only; every rule is as it was"
    ]


@needs_libs
def test_rules_only_writes_nothing_when_the_file_is_already_the_designs(tmp_path):
    design = rules_project(tmp_path)
    dru = tmp_path / "t.kicad_dru"
    inode, mtime = dru.stat().st_ino, dru.stat().st_mtime_ns
    before = project_bytes(tmp_path)
    proc = rules_only(design)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip() == f"rules: {dru} is already what the design writes; nothing written"
    assert project_bytes(tmp_path) == before
    assert (dru.stat().st_ino, dru.stat().st_mtime_ns) == (inode, mtime)  # not even written over


@needs_libs
def test_rules_only_refuses_a_rule_file_changed_beyond_its_header(tmp_path):
    design = rules_project(tmp_path)
    dru = tmp_path / "t.kicad_dru"
    text = dru.read_text(encoding="utf-8").replace(TODAY, OLDER)
    lines = text.split("\n")
    hole = next(i for i, ln in enumerate(lines) if "(constraint hole_clearance" in ln)
    lines[hole] = lines[hole].replace("(min ", "(min 0")  # a rule changed by hand: 0.33 -> 00.33
    dru.write_text("\n".join(lines), encoding="utf-8")
    before = project_bytes(tmp_path)
    proc = rules_only(design)
    assert proc.returncode == 1
    out = proc.stdout.strip().split("\n")
    assert len(out) == 1, proc.stdout
    assert out[0].startswith(f"design t red: {dru} differs from what the design writes in line {hole + 1},")
    assert "nothing written" in out[0]
    assert project_bytes(tmp_path) == before


@needs_libs
def test_rules_only_refuses_a_header_that_names_another_source(tmp_path):
    design = rules_project(tmp_path)
    dru = tmp_path / "t.kicad_dru"
    text = dru.read_text(encoding="utf-8")
    dru.write_text(text.replace("from sierra-circuits-web.kicad_dru", "from jlcpcb-2layer.kicad_dru"))
    before = project_bytes(tmp_path)
    proc = rules_only(design)
    assert proc.returncode == 1 and len(proc.stdout.strip().split("\n")) == 1, proc.stdout
    assert "differs from what the design writes in line" in proc.stdout
    assert project_bytes(tmp_path) == before


@needs_libs
def test_rules_only_refuses_a_design_without_a_fab_and_a_missing_rule_file(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    design = rules_project(plain, fab="")
    before = project_bytes(plain)
    proc = rules_only(design)
    assert proc.returncode == 1
    assert proc.stdout.strip() == (
        "design t red: the design names no fab (Design.fab), so it has no rule file; nothing written"
    )
    assert project_bytes(plain) == before

    missing = tmp_path / "missing"
    missing.mkdir()
    design = rules_project(missing)
    (missing / "t.kicad_dru").unlink()
    before = project_bytes(missing)
    proc = rules_only(design)
    assert proc.returncode == 1 and len(proc.stdout.strip().split("\n")) == 1, proc.stdout
    assert "has no t.kicad_dru: --rules-only writes a rule file again, never a first one" in proc.stdout
    assert project_bytes(missing) == before


@pytest.mark.parametrize("other", ["--route", "--check", "--seed", "--order"])
@needs_libs
def test_rules_only_goes_with_no_flag_that_writes_or_compares_the_board(tmp_path, other):
    design = rules_project(tmp_path)
    more = [other, str(tmp_path / "t.kicad_pcb")] if other == "--seed" else [other]
    before = project_bytes(tmp_path)
    proc = rules_only(design, *more)
    assert proc.returncode == 2 and f"design --rules-only cannot take {other}" in proc.stderr, proc.stderr
    assert project_bytes(tmp_path) == before


@needs_libs
def test_rules_only_json_names_the_state(tmp_path):
    design = rules_project(tmp_path)
    proc = rules_only(design, "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert data["state"] == "same" and data["rule_file"] == str(tmp_path / "t.kicad_dru")
    assert data["lines"] == [] and data["exit"] == 0


def test_the_rule_file_lines_that_differ_beyond_the_header():
    kept = f"(version 1)\n(rule a)\n\n{OLDER}x.kicad_dru (Design.fab); edit the source, not this file.\n"
    today = kept.replace(OLDER, TODAY)
    assert kicadgen.rule_file_changes(kept, today) == []
    assert kicadgen.rule_file_changes(today, today) == []
    assert kicadgen.rule_file_changes(kept.replace("(rule a)", "(rule b)"), today) == [2]
    assert kicadgen.rule_file_changes(kept.replace("x.kicad_dru", "y.kicad_dru"), today) == [4]
    # Split at each newline: the empty piece after the last one is a line, so a file cut short or
    # grown differs there too, and a lost final newline is no header change.
    assert kicadgen.rule_file_changes(kept + "(rule c)\n", today) == [5, 6]
    assert kicadgen.rule_file_changes("(version 1)\n", today) == [2, 3, 4, 5]
    assert kicadgen.rule_file_changes(kept.rstrip("\n"), today) == [5]
    # The header names a .kicad_dru file, and the whole line is the header: words before it differ.
    bare = kept.replace("x.kicad_dru", "x")
    assert kicadgen.rule_file_changes(bare, bare.replace(OLDER, TODAY)) == [4]
    assert kicadgen.rule_file_changes(kept, today.replace(TODAY, "; " + TODAY)) == [4]


def older_rule_file(folder: Path) -> tuple[Path, str]:
    """The project's rule file with the header written before 2026-11-19, and the text the design writes."""
    dru = folder / "t.kicad_dru"
    written = dru.read_text(encoding="utf-8")
    dru.write_text(written.replace(TODAY, OLDER), encoding="utf-8")
    return dru, written


@needs_libs
def test_rules_only_keeps_the_mode_of_the_file_it_writes_again(tmp_path):
    design = rules_project(tmp_path)
    dru, written = older_rule_file(tmp_path)
    dru.chmod(0o640)
    proc = rules_only(design)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert dru.read_text(encoding="utf-8") == written
    assert dru.stat().st_mode & 0o777 == 0o640  # a temporary file is made 0600; the old mode is kept


@needs_libs
def test_rules_only_writes_the_target_of_a_linked_rule_file(tmp_path):
    """A rule file may be a link to a shared one: `design` writes through the link, and so does this."""
    (tmp_path / "board").mkdir()
    design = rules_project(tmp_path / "board")
    dru, written = older_rule_file(tmp_path / "board")
    shared = tmp_path / "shared.kicad_dru"
    shared.write_text(dru.read_text(encoding="utf-8"), encoding="utf-8")
    dru.unlink()
    dru.symlink_to(shared)
    proc = rules_only(design)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert dru.is_symlink() and dru.resolve() == shared
    assert shared.read_text(encoding="utf-8") == written
    assert sorted(p.name for p in tmp_path.iterdir()) == ["board", "shared.kicad_dru"]


@needs_libs
def test_rules_only_leaves_the_file_and_no_other_when_the_rename_fails(tmp_path, monkeypatch, capsys):
    design = rules_project(tmp_path)
    dru, _ = older_rule_file(tmp_path)
    before = project_bytes(tmp_path)
    cli = load_cli()
    renamed = []

    def refuse(src, dst):
        renamed.append((Path(src), Path(dst)))
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(cli.os, "replace", refuse)
    args = argparse.Namespace(design=str(design), out=None, json=False)
    assert cli.rules_only_design(args) == 1
    # The temporary file was in the rule file's own folder, so the rename is 1 step on 1 file system.
    assert [(src.parent, dst) for src, dst in renamed] == [(dru.parent, dru)]
    assert project_bytes(tmp_path) == before  # the temporary file is gone, the rule file as it was
    out = capsys.readouterr().out.strip().split("\n")
    assert len(out) == 1 and out[0].startswith(f"design t red: {dru} could not be written:"), out
    assert out[0].endswith("No space left on device; it is as it was")


@needs_libs
def test_rules_only_refuses_an_unknown_fab_in_1_line(tmp_path):
    design = rules_project(tmp_path)
    design.write_text(design.read_text(encoding="utf-8").replace(SIERRA, "nofab"), encoding="utf-8")
    before = project_bytes(tmp_path)
    proc = rules_only(design)
    assert proc.returncode == 1 and proc.stderr == "", proc.stderr
    assert proc.stdout.strip().split("\n") == [
        f"design {tmp_path.name} red: no fab rule set 'nofab': rules/ holds "
        + ", ".join(sorted(p.stem for p in (ROOT / "rules").glob("*.kicad_dru")))
        + ", or name a .kicad_dru file; nothing written"
    ]
    assert project_bytes(tmp_path) == before


@needs_libs
def test_rules_only_json_names_the_lines_written_and_differing(tmp_path):
    design = rules_project(tmp_path)
    dru, written = older_rule_file(tmp_path)
    header = next(i for i, ln in enumerate(written.split("\n"), start=1) if ln.startswith(TODAY))
    proc = rules_only(design, "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    data = json.loads(proc.stdout)
    assert (data["state"], data["lines"], data["exit"]) == ("written", [header], 0)

    dru.write_text(written.replace("(min ", "(min 0", 1), encoding="utf-8")
    first = next(i for i, ln in enumerate(written.split("\n"), start=1) if "(min " in ln)
    proc = rules_only(design, "--json")
    data = json.loads(proc.stdout)
    assert (data["state"], data["lines"], data["exit"]) == ("differs", [first], 1)


@needs_libs
def test_rules_only_names_12_lines_and_the_json_names_them_all(tmp_path):
    design = rules_project(tmp_path)
    dru, written = older_rule_file(tmp_path)
    end = len(written.split("\n"))  # the empty piece after the final newline
    dru.write_text(dru.read_text(encoding="utf-8") + "(rule added)\n" * 14, encoding="utf-8")
    added = list(range(end, end + 15))  # the 14 lines, and the empty piece that moved past them
    proc = rules_only(design)
    assert proc.returncode == 1
    shown = ", ".join(map(str, added[:12])) + ", ..."
    assert f"differs from what the design writes in lines {shown}, not only in its header" in proc.stdout
    data = json.loads(rules_only(design, "--json").stdout)
    assert data["lines"] == added


# ------------------------------------------------- design --check holds the rule file

# A track the router would add: `--check` writes the board unrouted, and a board with more copper
# than that is a routed board, which a plain `design` would write over.
TRACK = '\t(segment (start 101 101) (end 102 101) (width 0.2) (layer "F.Cu") (net 0))\n'
# A fab whose rules the empty design's default via meets: under Sierra's the design step exits 1 on
# its annular ring, and `--check` fails on that exit (M85) whatever the files say.
CLEAN = "jlcpcb-2layer"


def check(design: Path, *before: str) -> subprocess.CompletedProcess:
    """`workcenter [before] design <design> --check`; bytecode beside the design would be a file
    written in the project."""
    return subprocess.run(
        [sys.executable, str(CLI), *before, "design", str(design), "--check"],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def check_json(design: Path) -> tuple[int, dict]:
    proc = check(design, "--json")
    return proc.returncode, json.loads(proc.stdout)


def entry(report: dict, name: str) -> dict:
    return next(f for f in report["files"] if f["file"] == name)


def routed(folder: Path) -> None:
    """Give the project's board 1 track more than the design writes, as the router would."""
    pcb = folder / "t.kicad_pcb"
    text = pcb.read_text(encoding="utf-8")
    end = text.rstrip().rfind(")")
    pcb.write_text(text[:end] + TRACK + text[end:], encoding="utf-8")


@needs_libs
def test_check_holds_the_rule_file_the_design_writes(tmp_path):
    """5 routed example boards kept the rule file's older header while `design --check` was green:
    it compared the .kicad_pro, the .kicad_sch and the library tables only (2026-11-19)."""
    design = rules_project(tmp_path, CLEAN)
    before = project_bytes(tmp_path)
    code, report = check_json(design)
    assert code == 0, report
    assert [f["file"] for f in report["files"]] == ["t.kicad_pro", "t.kicad_sch", "t.kicad_dru"]
    assert {f["state"] for f in report["files"]} == {"same"}
    assert report["step"] is None
    assert project_bytes(tmp_path) == before  # nothing written in the project


@needs_libs
def test_check_names_rules_only_when_only_the_rule_files_header_differs(tmp_path):
    design = rules_project(tmp_path, CLEAN)
    routed(tmp_path)
    dru, written = older_rule_file(tmp_path)
    header = next(i for i, ln in enumerate(written.split("\n"), start=1) if ln.startswith(TODAY))
    code, report = check_json(design)
    assert code == 1
    rule = entry(report, "t.kicad_dru")
    assert (rule["state"], rule["line"], rule["header_only"]) == ("differs", header, True)
    assert rule["project"].startswith(OLDER.strip()) and rule["design"].startswith(TODAY.strip())
    assert report["step"] == f"workcenter design {design} --rules-only"
    proc = check(design)
    assert proc.returncode == 1
    out = proc.stdout.splitlines()
    assert "check: differs  t.kicad_dru" in out
    assert f"         line {header}: project {rule['project']!r}" in out
    assert (
        f"         only its header line differs: `workcenter design {design} --rules-only` writes it again"
        in out
    )
    assert f"check: step: `workcenter design {design} --rules-only`" in out
    assert out[-1] == f"check: {tmp_path.name}: red, 1 of 3 files differ from design.py"


@needs_libs
def test_check_names_a_whole_design_run_when_a_rule_differs(tmp_path):
    """A rule that differs is a hand's edit or a moved source: `--rules-only` refuses it, so the step
    is the design run, with `--route` for a routed board, since a plain run writes it unrouted."""
    design = rules_project(tmp_path, CLEAN)
    dru = tmp_path / "t.kicad_dru"
    text = dru.read_text(encoding="utf-8")
    dru.write_text(text.replace("(min ", "(min 0", 1), encoding="utf-8")
    first = next(i for i, ln in enumerate(text.split("\n"), start=1) if "(min " in ln)
    code, report = check_json(design)
    assert code == 1
    rule = entry(report, "t.kicad_dru")
    assert (rule["state"], rule["line"], rule["header_only"]) == ("differs", first, False)
    assert report["step"] == f"workcenter design {design}"  # the project's board has no track
    routed(tmp_path)
    code, report = check_json(design)
    assert code == 1 and report["step"] == f"workcenter design {design} --route"
    assert f"check: step: `workcenter design {design} --route`" in check(design).stdout.splitlines()


@needs_libs
def test_check_names_a_rule_file_the_design_would_not_write(tmp_path):
    """A design with no fab writes no rule file; KiCad's DRC reads <name>.kicad_dru beside the project
    all the same, so one left from an earlier fab is a difference the design cannot write away."""
    design = rules_project(tmp_path, fab="")
    assert not (tmp_path / "t.kicad_dru").exists()
    code, report = check_json(design)
    assert code == 0, report
    assert [f["file"] for f in report["files"]] == ["t.kicad_pro", "t.kicad_sch"]
    (tmp_path / "t.kicad_dru").write_text("(version 1)\n", encoding="utf-8")
    (tmp_path / "other.kicad_dru").write_text("(version 1)\n", encoding="utf-8")  # KiCad does not read it
    code, report = check_json(design)
    assert code == 1
    assert entry(report, "t.kicad_dru")["state"] == "extra"
    assert [f["file"] for f in report["files"]] == ["t.kicad_pro", "t.kicad_sch", "t.kicad_dru"]
    assert report["step"] == f"rm {tmp_path / 't.kicad_dru'}"
    out = check(design).stdout.splitlines()
    assert "check: extra    t.kicad_dru" in out
    assert (
        "         the design names no fab (Design.fab), so it writes no rule file; KiCad's DRC reads this "
        "one all the same: remove it, or name its fab in Design.fab"
    ) in out
    # The step runs as written on a file git does not track: `git rm` refused it (a reviewer, 2026-11-20).
    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    ran = subprocess.run(report["step"], shell=True, capture_output=True, text=True, check=False)
    assert ran.returncode == 0, ran.stderr
    assert not (tmp_path / "t.kicad_dru").exists() and check_json(design)[0] == 0


@needs_libs
def test_check_holds_the_files_the_design_names(tmp_path):
    """Design.files: a file the design writes beside the KiCad files (a ratings.json, a parts.csv,
    a deck) is the design's output as much as the schematic is."""
    design = tmp_path / "design.py"
    body = RULES_DESIGN.format(fab="").replace(
        "    return d\n", "    d.files['notes/a.txt'] = 'one\\ntwo\\n'\n    return d\n"
    )
    design.write_text(body, encoding="utf-8")
    kicadgen.load_design(design).write(tmp_path)
    code, report = check_json(design)
    assert code == 0, report
    assert entry(report, "notes/a.txt")["state"] == "same"
    (tmp_path / "notes" / "a.txt").write_text("one\nTWO\n", encoding="utf-8")
    code, report = check_json(design)
    assert code == 1
    a = entry(report, "notes/a.txt")
    assert (a["state"], a["line"], a["project"], a["design"]) == ("differs", 2, "TWO", "two")
    assert report["step"] == f"workcenter design {design}"
    (tmp_path / "notes" / "a.txt").unlink()
    code, report = check_json(design)
    assert code == 1 and entry(report, "notes/a.txt")["state"] == "missing"


@needs_libs
def test_check_json_holds_a_design_file_that_prints(tmp_path):
    """Wyvern v0.2's design file prints its module's fan-out while it builds: `design --check --json`
    read that line as the start of the design step's JSON and stopped with a traceback (2026-11-19)."""
    design = tmp_path / "design.py"
    body = RULES_DESIGN.format(fab="").replace(
        "    return d\n",
        "    print('fan-out: 3 vias')\n    print('{not json')\n    print('{')\n    print('}')\n    return d\n",
    )
    design.write_text(body, encoding="utf-8")
    kicadgen.load_design(design).write(tmp_path)
    proc = check(design, "--json")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["printed"] == ["fan-out: 3 vias", "{not json", "{", "}"]  # the last `{` alone starts it
    assert report["design"]["name"] == "t" and report["exit"] == 0


@needs_libs
def test_check_says_the_board_is_not_compared_and_why(tmp_path):
    design = rules_project(tmp_path, CLEAN)
    proc = check(design)
    assert proc.returncode == 0, proc.stdout
    assert (
        "check: not compared: t.kicad_pcb: --check writes the board unrouted; the project's holds the "
        "router's tracks and vias, the vias it reserved for pour islands and KiCad's zone fill. "
        "The gates' DRC holds the board to the schematic; no check holds a part's place to design.py"
    ) in proc.stdout.splitlines()
    code, report = check_json(design)
    assert report["not_compared"] == ["t.kicad_pcb"]


# A via the router would add, and nothing else: the project's board is routed all the same.
VIA = '\t(via (at 101 101) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 0))\n'


def followed(step: str) -> subprocess.CompletedProcess:
    """The step the check names, run as written, `workcenter` being this worktree's."""
    command = step.replace("workcenter ", f"{sys.executable} {CLI} ", 1)
    return subprocess.run(command, shell=True, capture_output=True, text=True, check=False)


@needs_libs
def test_check_names_a_design_run_when_a_header_and_another_file_differ(tmp_path):
    """`--rules-only` writes the rule file alone: with another file behind as well, it would leave
    the check red. The step is the design run."""
    design = rules_project(tmp_path, CLEAN)
    routed(tmp_path)
    older_rule_file(tmp_path)
    pro = tmp_path / "t.kicad_pro"
    pro.write_text(pro.read_text(encoding="utf-8").replace("{", "{ ", 1), encoding="utf-8")
    code, report = check_json(design)
    assert code == 1 and entry(report, "t.kicad_dru")["header_only"] is True
    assert entry(report, "t.kicad_pro")["state"] == "differs"
    assert report["step"] == f"workcenter design {design} --route"


@needs_libs
def test_check_counts_a_via_as_routed_copper(tmp_path):
    design = rules_project(tmp_path, CLEAN)
    pcb = tmp_path / "t.kicad_pcb"
    text = pcb.read_text(encoding="utf-8")
    end = text.rstrip().rfind(")")
    pcb.write_text(text[:end] + VIA + text[end:], encoding="utf-8")
    pro = tmp_path / "t.kicad_pro"
    pro.write_text(pro.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    code, report = check_json(design)
    assert code == 1 and report["step"] == f"workcenter design {design} --route"


@needs_libs
def test_check_names_no_step_when_the_design_step_fails(tmp_path):
    """Under Sierra's rules the empty design's via fails its ring: the design step exits 1, and
    regenerating gives the same exit. Its own line says what to correct (M85)."""
    design = rules_project(tmp_path, SIERRA)
    pro = tmp_path / "t.kicad_pro"
    pro.write_text(pro.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    code, report = check_json(design)
    assert (code, report["design_exit"], report["step"]) == (1, 1, None)
    assert entry(report, "t.kicad_pro")["state"] == "differs"
    out = check(design).stdout.splitlines()
    assert "check: the design step exited 1; a board repository's CI fails on it (M85)" in out
    assert not [ln for ln in out if ln.startswith("check: step:")]


@needs_libs
def test_check_names_a_step_that_runs_as_written_for_a_project_that_keeps_no_board(tmp_path):
    """11 fixture designs keep no board (the ratings fixtures). The step was `--out <a scratch
    folder>, then copy in the files named above`: no command (a reviewer, 2026-11-20)."""
    design = rules_project(tmp_path, CLEAN)
    (tmp_path / "t.kicad_pcb").unlink()
    sch = tmp_path / "t.kicad_sch"
    sch.write_text(sch.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    kept = set(project_bytes(tmp_path))
    code, report = check_json(design)
    assert code == 1
    assert report["step"] == f"workcenter design {design} && rm {tmp_path / 't.kicad_pcb'}"
    ran = followed(report["step"])
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert set(project_bytes(tmp_path)) == kept  # the board written and removed again
    assert check_json(design)[0] == 0


@needs_libs
def test_check_shows_a_line_end_and_a_space_at_the_end_of_a_line(tmp_path):
    """The first differing line was stripped: a rule file with CRLF line ends printed `'(end)'` for
    both, and a space at the end printed the same text twice (a reviewer, 2026-11-20)."""
    design = rules_project(tmp_path, CLEAN)
    dru = tmp_path / "t.kicad_dru"
    written = dru.read_bytes()
    dru.write_bytes(written.replace(b"\n", b"\r\n"))
    rule = entry(check_json(design)[1], "t.kicad_dru")
    assert rule["line"] == 1 and rule["project"] == rule["design"] + "\r", rule
    lines = written.decode("utf-8").split("\n")
    at = next(i for i, ln in enumerate(lines) if "(min " in ln)
    dru.write_text("\n".join(lines[:at] + [lines[at] + " "] + lines[at + 1 :]), encoding="utf-8")
    rule = entry(check_json(design)[1], "t.kicad_dru")
    assert (rule["line"], rule["project"], rule["design"]) == (at + 1, lines[at] + " ", lines[at])
    assert f"         line {at + 1}: project {lines[at] + ' '!r}" in check(design).stdout.splitlines()


@needs_libs
def test_a_fab_via_does_not_know_refuses_the_design_file_in_1_line(tmp_path):
    """`design` and `design --check` ended in a ValueError's traceback (a reviewer, 2026-11-20)."""
    design = rules_project(tmp_path, CLEAN)
    design.write_text(design.read_text(encoding="utf-8").replace(CLEAN, "nofab"), encoding="utf-8")
    before = project_bytes(tmp_path)
    known = ", ".join(sorted(p.stem for p in (ROOT / "rules").glob("*.kicad_dru")))
    problem = f"no fab rule set 'nofab': rules/ holds {known}, or name a .kicad_dru file"
    for flags in ((), ("--check",)):
        proc = subprocess.run(
            [sys.executable, str(CLI), "design", str(design), *flags],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1 and proc.stderr == "", proc.stderr
        assert f"  file: {problem}" in proc.stdout.splitlines()
        assert (
            f"design {tmp_path.name} red: the design file is refused. Nothing is written: correct the file "
            "first."
        ) in proc.stdout.splitlines()
    assert project_bytes(tmp_path) == before
