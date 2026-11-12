"""The document commands: docs, costs, pictures, version new, diagram, the gates report, and scenes.

Each runs the worktree's own tools/workcenter on a repository the test builds in tmp_path, laid out
the way a project keeps its versions: version folders, library/sources.csv, parts/ with its catalog,
version and offboard files, and the lists `costs` writes.
"""

from __future__ import annotations

import datetime
import importlib.machinery
import json
import shutil
import subprocess
import sys
import types
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
sys.path.insert(0, str(ROOT / "tools"))
import doctools  # noqa: E402

needs_kicad = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
needs_ngspice = pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice is not installed")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
needs_rsvg = pytest.mark.skipif(shutil.which("rsvg-convert") is None, reason="rsvg-convert is not installed")
TODAY = datetime.date.today().isoformat()
LIST_HEAD = "Refs,Qty,Value,Footprint,Manufacturer,MPN,Supplier,SKU,Stock,Checked,URL,Note"
LIST_HEAD += ",Order for 1,Cost for 1,Order for 10,Cost for 10"
PARTS_HEAD = "Value,Footprint,Qty,Manufacturer,MPN,Supplier,SKU,Pack,Breaks,Stock,Checked,URL,Note"


def run(*args: object) -> tuple[int, list[dict]]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", *map(str, args)], capture_output=True, text=True, check=False
    )
    payload = json.loads(proc.stdout) if proc.stdout.strip() else []
    return proc.returncode, payload


def write(path: Path, text: str | bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(text, bytes):
        path.write_bytes(text)
    else:
        path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------ shared logic


def test_a_marker_named_in_a_sentence_is_no_block():
    """A board repository's CLAUDE.md says `costs` writes between the `<!-- workcenter costs -->`
    markers; `workcenter costs` took that for a block with no end and failed (M163)."""
    prose = "- writes the totals between the `<!-- workcenter costs -->`\n  markers (README.md)\n"
    assert not doctools.unclosed(prose, "costs")
    block = "<!-- workcenter costs -->\nold\n<!-- /workcenter costs -->\n"
    assert doctools.fill_block(prose + block, "costs", "new") == (prose + block.replace("old", "new"), 1)
    named = "say `<!-- workcenter costs -->`\nold\n<!-- /workcenter costs -->\n"
    assert doctools.fill_block(named, "costs", "x") == (named, 0)


def test_fill_block_rewrites_only_between_its_markers():
    text = (
        "intro\n<!-- workcenter costs -->\nold\n<!-- /workcenter costs -->\nmiddle\n"
        "<!-- workcenter costs lists -->\nx\n<!-- /workcenter costs lists -->\nend\n"
    )
    new, n = doctools.fill_block(text, "costs", "| a |\n")
    assert n == 1
    assert new == text.replace("old\n", "| a |\n")  # the lists block, a longer name, is not touched
    new, n = doctools.fill_block(new, "costs lists", "y")
    assert n == 1 and "\ny\n<!-- /workcenter costs lists -->" in new and "intro\n" in new and "end\n" in new
    assert doctools.fill_block("no markers here", "costs", "x") == ("no markers here", 0)
    assert doctools.unclosed("<!-- workcenter costs -->\nno end\n", "costs")
    assert not doctools.unclosed(text, "costs") and not doctools.unclosed("plain", "costs")


def test_versions_sort_by_number_and_move_in_one_pass():
    assert doctools.version_key("v0.10") > doctools.version_key("v0.9")
    assert doctools.next_version("v0.16") == "v0.17" and doctools.next_version("v1") == "v2"
    text = "`v0.1/` to `v0.16/` (`v0.17/` from `v0.16/`); v0.161 and v0.1.6 stay; v0.16."
    moved, n = doctools.move_versions(text, "v0.16", "v0.17")
    assert moved == "`v0.1/` to `v0.17/` (`v0.18/` from `v0.17/`); v0.161 and v0.1.6 stay; v0.17."
    assert n == 4  # three mentions of v0.16 and one of v0.17; v0.1, v0.161 and v0.1.6 stay


# -------------------------------------------------------------------- docs

SOURCES = "\n".join(
    [
        "MPN,Kind,URL,File,Member,Revision,Dated,Subckt,Ngspice,SHA256,Checked,Note",
        "U1PART,datasheet,https://example.com/u1.pdf,maker/u1.pdf,,Rev 3,2026-01,,,,2026-11-01,",
        "U1PART,spice,,,,,,,,,2026-11-01,a digital part",
        "R0402-10K,datasheet,https://example.com/rc.pdf,maker/rc.pdf,,V.14,2025-11,,,,2026-11-01,the series",
        "C100N,datasheet,,,,,,,,,2026-11-01,the maker refused the fetch",
        "",
    ]
)
BASE_LIST = "\n".join(
    [
        LIST_HEAD,
        "U1,1,MCU,Package_DFN:X,Maker,U1PART,Digi-Key,1,5,2026-11-01,,,1,1.00,10,9.00",
        "R1,1,10k,Resistor_SMD:R_0402,Yageo,R0402-10K,Digi-Key,2,5,2026-11-01,,,1,0.10,10,0.20",
        "R2,1,5k,Resistor_SMD:R_0201,Yageo,R0201-5K,Digi-Key,3,5,2026-11-01,,,1,0.10,10,0.20",
        "C1,1,100n,Capacitor_SMD:C_0402,Murata,C100N,Digi-Key,4,5,2026-11-01,,,1,0.10,10,0.20",
        "J1,1,CONN,Lib:J,,,Digi-Key,,,,,no part chosen,,,,",
        "X1,1,ODD,Lib:X,Acme,ACME-1,Digi-Key,5,5,2026-11-01,,,1,0.10,10,0.20",
        "TP1,1,PAD,Lib:TP,,,none,,,,,copper,,,,",
        ",1,PCB 10 x 10 mm,,OSH Park,bare board to this version's gerbers,OSH Park,,,,,,3,6.00,12,24.00",
        "",
    ]
)
DISPLAY_LIST = LIST_HEAD + "\nU1,1,MCU,Package_DFN:X,Maker,U1PART,Digi-Key,1,5,2026-11-01,,,1,1.00,10,9.00\n"


def docs_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    write(repo / "library" / "sources.csv", SOURCES)
    write(repo / "library" / "series.csv", "Pattern,MPN\n^R0201-,R0402-10K\n")
    for name in ("u1.pdf", "rc.pdf", "old.pdf"):
        write(repo / "library" / "maker" / name, f"%PDF {name}")
    write(repo / "parts" / "lists" / "v0.2.csv", BASE_LIST)
    write(repo / "parts" / "lists" / "v0.2-display.csv", DISPLAY_LIST)
    write(repo / "parts" / "lists" / "v0.2.md", "# list\n")
    write(repo / "parts" / "lists" / "v0.2-display.md", "# list\n")
    v = repo / "v0.2"
    write(v / "README.md", "# Board v0.2\n\n> banner\n\n## What changed in v0.2\n\ntext\n\n## Pin plan\n")
    for name in ("design.py", "board.kicad_pro", "board.kicad_sch", "board.kicad_pcb", "fp-lib-table"):
        write(v / name, "")
    write(v / "footprints" / "Lib.pretty" / "J.kicad_mod", "")
    write(v / "assembly.py", '"""The assembly: the board in its case. More text."""\n')
    write(v / "sim" / "rc.cir", "* An RC divider. Checks the ratio.\n.end\n")
    write(v / "sim" / "rc.expect.json", "{}")
    write(v / "docs" / "board-top.png", b"\x89PNG")
    write(v / "docs" / "gates.md", "# Gates\n")
    write(v / "docs" / "layers" / "base-F-Cu.png", b"\x89PNG")
    write(v / "firmware" / "Makefile", "all: app\n\ntest: unit\n\nclean:\n\trm -rf build\n")
    write(v / "firmware" / "src" / "core" / "a.c", "")
    write(v / "firmware" / "src" / "board" / "b.c", "")
    write(v / "firmware" / "tests" / "t.c", "")
    write(v / "firmware" / "build" / "app.elf", "")  # build output is not content
    write(v / "firmware" / "mutations.py", "MUTATIONS = []\n")
    write(v / "pictures.json", "{}\n")
    write(v / "verification" / "README.md", "# Package\n")
    write(v / "verification" / "simulations" / "rc" / "README.md", "# RC divider\n")
    write(v / "display" / "design.py", "")
    write(v / "display" / "display.kicad_pro", "")
    write(v / "display" / "display.kicad_sch", "")
    write(v / "datasheets" / "maker" / "old.pdf", "%PDF old.pdf")  # a copy no part names any more
    write(v / "datasheets" / "notes.txt", "kept by hand")
    return repo


def test_docs_writes_contents_and_copies_each_datasheet(tmp_path):
    repo = docs_repo(tmp_path)
    v = repo / "v0.2"
    code, records = run("docs", v)
    assert code == 0, records
    details = records[0]["details"]
    assert (v / "datasheets" / "maker" / "u1.pdf").read_text() == "%PDF u1.pdf"
    assert (v / "datasheets" / "maker" / "rc.pdf").is_file()
    assert details["removed"] == ["maker/old.pdf"] and not (v / "datasheets" / "maker" / "old.pdf").exists()
    assert (v / "datasheets" / "notes.txt").is_file()  # not a library file: put there by hand, kept
    assert details["no_row"] == ["ACME-1"] and details["boards"] == ["v0.2", "v0.2-display"]
    text = (v / "CONTENTS.md").read_text(encoding="utf-8")
    for line in (
        "What this folder holds, for Board v0.2. Made by `workcenter docs v0.2` from the folder itself, "
        "the version's parts lists and `library/sources.csv`; run it again after a change.",
        "  - [What changed in v0.2](README.md#what-changed-in-v02)",
        "- [docs/gates.md](docs/gates.md): the gates report: ERC, DRC, simulation, export.",
        "- The base board:",
        "  - [design.py](design.py): the source of truth; the KiCad files are generated from it",
        "  - [board.kicad_pcb](board.kicad_pcb): board",
        "  - [footprints/](footprints/): project footprints, 1 file",
        "- The display board:",
        "  - [display/display.kicad_pro](display/display.kicad_pro): KiCad project",
        "- [assembly.py](assembly.py): The assembly: the board in its case.",
        "- [sim/rc.cir](sim/rc.cir), bounds in [sim/rc.expect.json](sim/rc.expect.json): An RC divider",
        "- [verification/simulations/rc/README.md](verification/simulations/rc/README.md): "
        "the simulation writeup, RC divider",
        "- [firmware/src/board/](firmware/src/board/): 1 file",
        "- [firmware/src/core/](firmware/src/core/): 1 file",
        "- [firmware/tests/](firmware/tests/): host tests, 1 file",
        "- [firmware/Makefile](firmware/Makefile): `make`, `make test`",
        "- [firmware/mutations.py](firmware/mutations.py): the mutation list `workcenter mutate` runs; "
        "every mutation must fail a host test",
        "- [pictures.json](pictures.json): what `workcenter pictures` draws and copies into docs/",
        "- [docs/board-top.png](docs/board-top.png)",
        "- [docs/layers/](docs/layers/): every copper and technical layer, 1 image",
        "- The display board's priced parts list: "
        "[../parts/lists/v0.2-display.md](../parts/lists/v0.2-display.md)",
        "| base | U1 | Maker U1PART | [maker/u1.pdf](datasheets/maker/u1.pdf) | Rev 3 |",
        "| base | R2 | Yageo R0201-5K | [maker/rc.pdf](datasheets/maker/rc.pdf) (series sheet) | V.14 |",
        "| base | C1 | Murata C100N | none kept: the maker refused the fetch |  |",
        "| base | J1 |  | none: no part number chosen yet (the parts list's note says why) |  |",
        "| base | X1 | Acme ACME-1 | none kept: no row in `../library/sources.csv` |  |",
        "| display | U1 | Maker U1PART | [maker/u1.pdf](datasheets/maker/u1.pdf) | Rev 3 |",
    ):
        assert line in text.splitlines(), line
    assert "TP1" not in text and "bare board" not in text and "app.elf" not in text and "build" not in text


def test_docs_without_a_parts_list_leaves_the_datasheets_alone(tmp_path):
    repo = docs_repo(tmp_path)
    (repo / "parts" / "lists" / "v0.2-display.csv").unlink()
    code, records = run("docs", repo / "v0.2")
    assert (
        code == 1 and "v0.2-display" in records[0]["summary"] and "workcenter costs" in records[0]["summary"]
    )
    assert (repo / "v0.2" / "datasheets" / "maker" / "old.pdf").is_file()
    assert not (repo / "v0.2" / "datasheets" / "maker" / "u1.pdf").exists()
    assert (repo / "v0.2" / "CONTENTS.md").is_file()


def test_docs_without_a_library_skips(tmp_path):
    write(tmp_path / "v0.1" / "README.md", "# v0.1\n")
    code, records = run("docs", tmp_path / "v0.1")
    assert code == 2 and records[0]["status"] == "skip" and "sources.csv" in records[0]["summary"]
    assert not (tmp_path / "v0.1" / "CONTENTS.md").exists()


# ------------------------------------------------------------------- costs

CATALOG = "\n".join(
    [
        PARTS_HEAD,
        "100n,Capacitor_SMD:C_0603_1608Metric,,Samsung,CL10B104KB8NNNC,Digi-Key,1276-1000-1-ND,,"
        "1:0.10 10:0.032 50:0.0216,0,{today},,",
        "Conn_01x03,Connector_PinHeader_2.54mm:PinHeader_1x03_P2.54mm_Vertical,,Sullins,PREC003SAAN-RC,"
        "Digi-Key,35-PREC003SAAN-RC-ND,,1:0.10 10:0.04,40331,{today},,",
        "10k,Resistor_SMD:R_0603_1608Metric,,Yageo,RC0603FR-0710KL,Digi-Key,311-10.0KHRCT-ND,,"
        "1:0.10 10:0.025 25:0.0188,0,{today},,",
        "",
    ]
).format(today=TODAY)


def costs_repo(tmp_path: Path) -> Path:
    """v0.1: the RC fixture and a bare board off it. v0.2: the fixture with its own 10k price, a nested
    display board (the fixture again), and a cell with no price."""
    repo = tmp_path / "repo"
    shutil.copytree(BOARDS / "pass-rc-divider", repo / "v0.1", ignore=shutil.ignore_patterns("sim"))
    shutil.copytree(BOARDS / "pass-rc-divider", repo / "v0.2", ignore=shutil.ignore_patterns("sim"))
    shutil.copytree(
        BOARDS / "pass-rc-divider", repo / "v0.2" / "display", ignore=shutil.ignore_patterns("sim")
    )
    write(repo / "parts" / "catalog.csv", CATALOG)
    write(
        repo / "parts" / "version" / "v0.2.csv",
        f"{PARTS_HEAD}\n10k,Resistor_SMD:R_0603_1608Metric,,Yageo,RC0603FR-0710KL,Digi-Key,X,,1:0.50,100,{TODAY},,\n",
    )
    write(
        repo / "parts" / "offboard" / "v0.1.csv",
        f"{PARTS_HEAD}\nPCB,,1,OSH Park,bare board to this version's gerbers,OSH Park,,3,3:2.00,,"
        f"{TODAY},,sets of 3\n",
    )
    write(repo / "parts" / "offboard" / "v0.2.csv", f"{PARTS_HEAD}\nCell,,1,,,,,,,,,,no part chosen\n")
    write(
        repo / "README.md",
        "# Series\n\nTotals:\n\n<!-- workcenter costs -->\nstale\n<!-- /workcenter costs -->\n\n"
        "Made by hand.\n",
    )
    write(
        repo / "parts" / "README.md",
        "# Parts\n\n<!-- workcenter costs lists -->\n<!-- /workcenter costs lists -->\n\n"
        "<!-- workcenter costs -->\n<!-- /workcenter costs -->\n",
    )
    write(repo / "v0.2" / "README.md", "# v0.2\n\nno markers here\n")
    return repo


@needs_kicad
def test_costs_prices_every_board_and_fills_every_marked_table(tmp_path):
    repo = costs_repo(tmp_path)
    code, records = run("costs", repo)
    assert code == 0, records
    assert records[0]["details"]["files"] == ["README.md", "parts/README.md"]
    lists = repo / "parts" / "lists"
    assert sorted(p.name for p in lists.iterdir()) == [
        "v0.1.csv",
        "v0.1.md",
        "v0.2-display.csv",
        "v0.2-display.md",
        "v0.2.csv",
        "v0.2.md",
    ]
    # v0.1: 0.40 of parts and a set of 3 bare boards (6.00) for one unit; 1.19 and 4 sets (24.00) for
    # ten. v0.2: its own 10k at 0.50 (1.00 and 10.00 for the pair), the display board's 0.40 and 1.19.
    table = [
        "| Version | 1 unit | 10 units | Per unit at 10 | Not priced | Short of stock |",
        "|---|---|---|---|---|---|",
        "| v0.1 | $6.40 | $25.19 | $2.52 | none | C1; R1,R2 |",
        "| v0.2 | $1.60 | $11.91 | $1.19 | Cell | C1; display C1; display R1,R2 |",
    ]
    readme = (repo / "README.md").read_text(encoding="utf-8")
    assert readme == (
        "# Series\n\nTotals:\n\n<!-- workcenter costs -->\n"
        + "\n".join(table)
        + "\n<!-- /workcenter costs -->\n\nMade by hand.\n"
    )
    parts = (repo / "parts" / "README.md").read_text(encoding="utf-8")
    assert "\n".join(table) in parts
    assert (
        "| v0.2 | [base](lists/v0.2.md) ([csv](lists/v0.2.csv)), "
        "[display](lists/v0.2-display.md) ([csv](lists/v0.2-display.csv)) |" in parts
    )
    assert "| v0.1 | [base](lists/v0.1.md) ([csv](lists/v0.1.csv)) |" in parts
    assert (repo / "v0.2" / "README.md").read_text() == "# v0.2\n\nno markers here\n"


@needs_kicad
def test_costs_names_a_block_with_no_closing_marker(tmp_path):
    repo = costs_repo(tmp_path)
    write(repo / "notes.md", "<!-- workcenter costs -->\nstale\n")
    code, records = run("costs", repo)
    assert code == 1
    assert "notes.md: `<!-- workcenter costs -->` has no closing marker" in records[0]["details"]["failures"]
    assert (repo / "notes.md").read_text() == "<!-- workcenter costs -->\nstale\n"


def test_costs_without_a_catalog_skips(tmp_path):
    write(tmp_path / "v0.1" / "README.md", "# v0.1\n")
    code, records = run("costs", tmp_path)
    assert code == 2 and "catalog" in records[0]["summary"]


# ------------------------------------------------------------ gates report


def load_cli():
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_doctools", str(CLI))
    module = types.ModuleType("workcenter_cli_doctools")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module  # dataclasses look the defining module up here
    loader.exec_module(module)
    return module


def fake_cli() -> types.SimpleNamespace:
    """The engines' versions made up, the verdict the command line's own."""
    return types.SimpleNamespace(
        tool_version=lambda *_a, **_k: "10.0.7",
        KICAD_CLI="kicad-cli",
        NGSPICE="ngspice",
        GATE_ORDER=("erc", "drc", "sim", "export"),
        gates_verdict=load_cli().gates_verdict,
    )


def result(gate: str, status: str, summary: str, details: dict | None = None) -> types.SimpleNamespace:
    return types.SimpleNamespace(gate=gate, status=status, summary=summary, details=details or {})


def test_gates_report_writes_its_blocks_and_keeps_the_prose(tmp_path):
    project_dir = tmp_path / "rc"
    shutil.copytree(BOARDS / "pass-rc-divider", project_dir)
    project = types.SimpleNamespace(name="rc_divider", dir=project_dir)
    report = tmp_path / "docs" / "gates.md"
    green = [
        result("erc", "pass", "0 errors, 0 warnings"),
        result("drc", "pass", "0 errors"),
        result(
            "sim",
            "pass",
            "1 decks, 0 failures",
            {"decks": {"rc_divider": {}}, "failures": [], "warnings": []},
        ),
        result("export", "pass", "4/4 outputs"),
    ]
    assert doctools.gates_report(report, project, green, fake_cli()) == [
        "gates rc_divider",
        "decks rc_divider",
    ]
    text = report.read_text(encoding="utf-8")
    assert text.startswith(
        "# Gates report: rc_divider\n\n## rc_divider\n\n<!-- workcenter gates rc_divider -->\n"
    )
    assert "| ERC | pass | 0 errors, 0 warnings |" in text and "\n## Simulation: rc_divider\n" in text
    assert f"GREEN on {TODAY}: `workcenter gates` with KiCad 10.0.7, ngspice 10.0.7." in text
    deck = (
        "| `sim/rc_divider.cir` | RC divider fixture: 5 V through 10k into 10k to ground | 1 | none | pass |"
    )
    assert deck in text
    # A warning a gate names stands beside the word, and the deck's corner runs in their column.
    warned = green[:2] + [
        result(
            "sim",
            "pass",
            "1 decks, 18 corner runs, 0 failures, 1 warnings",
            {
                "decks": {"rc_divider": {"corners": {"runs": 18}}},
                "failures": [],
                "warnings": ["rc_divider: ngspice: Warning: singular matrix:  check node mid"],
            },
        ),
        green[3],
    ]
    doctools.gates_report(tmp_path / "warned.md", project, warned, fake_cli())
    text_warned = (tmp_path / "warned.md").read_text(encoding="utf-8")
    assert f"GREEN with 1 warning on {TODAY}: `workcenter gates`" in text_warned
    assert "to ground | 1 | 18 | 1 warning |" in text_warned
    # A deck the project keeps out of the corners carries the project's reason.
    skipped = green[:2] + [
        result(
            "sim",
            "pass",
            "1 decks, 0 failures",
            {"decks": {"rc_divider": {"corners": {"skip": "a model check"}}}, "failures": [], "warnings": []},
        )
    ]
    doctools.gates_report(tmp_path / "skipped.md", project, skipped, fake_cli())
    assert "| 1 | none: a model check | pass |" in (tmp_path / "skipped.md").read_text(encoding="utf-8")
    # Prose written by hand round and between the blocks survives a refresh; the tables change.
    text = text.replace("## rc_divider\n\n", "## rc_divider\n\nWritten by hand.\n\n")
    report.write_text(text + "\nClosing words.\n", encoding="utf-8")
    red = green[:2] + [
        result(
            "sim",
            "fail",
            "1 decks, 1 failures",
            {
                "decks": {"rc_divider": {}},
                "failures": ["rc_divider:vout=3 not in [2.45, 2.55]"],
                "warnings": [],
            },
        )
    ]
    doctools.gates_report(report, project, red, fake_cli())
    text = report.read_text(encoding="utf-8")
    assert "Written by hand.\n" in text and text.endswith("Closing words.\n")
    assert (
        text.count("<!-- workcenter gates rc_divider -->") == 1 and text.count("<!-- workcenter decks") == 1
    )
    assert "| EXPORT | not run | an earlier gate was red |" in text and f"RED on {TODAY}" in text
    assert "5 V through 10k into 10k to ground | 1 | none | 1 failure |" in text
    report.write_text("<!-- workcenter gates rc_divider -->\nno end\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="no closing marker"):
        doctools.gates_report(report, project, green, fake_cli())


@needs_kicad
@needs_ngspice
def test_gates_with_report_fills_the_report_and_keeps_its_exit_code(tmp_path):
    report = tmp_path / "docs" / "gates.md"
    code, records = run("gates", BOARDS / "pass-rc-divider", "--out", tmp_path / "out", "--report", report)
    assert code == 0 and [r["status"] for r in records] == ["pass"] * 4
    text = report.read_text(encoding="utf-8")
    assert "| ERC | pass | 0 errors, 0 warnings |" in text and "GREEN on" in text
    # the fixture's corners: 2 temperatures, 3 parts alone at 4 points each, the 8 combinations of
    # their ends at 3 temperatures, 8 Monte Carlo draws: 2 + 12 + 24 + 8
    assert "| `sim/rc_divider.cir` |" in text and "| 1 | 46 | pass |" in text
    assert not (BOARDS / "pass-rc-divider" / "docs").exists()


# ----------------------------------------------------------------- version


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


ROOT_README = "\n".join(
    [
        "# Board series",
        "",
        "| Version | Board | Firmware | Commit |",
        "|---|---|---|---|",
        "| [v0.2](v0.2/) (current) | 20 mm | yes | in work |",
        "| [v0.1](v0.1/) | 10 mm | yes | `abc1234` |",
        "",
        "The latest version, [v0.2](v0.2/).",
        "",
    ]
)


def series_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    write(repo / ".gitignore", "build/\n")
    write(repo / "README.md", ROOT_README)
    write(
        repo / "CLAUDE.md",
        "Folders `v0.1/` to `v0.2/`; copy the latest (`v0.3/` from `v0.2/`). Run `gates v0.2`.\n",
    )
    write(
        repo / "v0.1" / "README.md",
        "# Board v0.1\n\n> Archived: v0.1 of the [Board series](../README.md), as of commit `abc1234`. "
        "Run the commands below from this folder. The next version, [`../v0.2/`](../v0.2/), is bigger.\n\n"
        "Body\n",
    )
    write(
        repo / "v0.2" / "README.md",
        "# Board v0.2\n\n> The current version of the [Board series](../README.md), started as a copy of "
        "[`../v0.1/`](../v0.1/). The earlier versions are the sibling folders, [`../v0.1/`](../v0.1/) to "
        "[`../v0.1/`](../v0.1/).\n\n## What changed in v0.2\n",
    )
    write(repo / "v0.2" / "design.py", 'LABEL = "v0.2"\n')
    write(repo / "v0.2" / "board.kicad_pro", "{}\n")
    write(repo / "v0.2" / "display" / "display.kicad_pro", "{}\n")
    write(repo / "v0.2" / "build" / "junk.txt", "build output\n")
    write(repo / "parts" / "version" / "v0.2.csv", "x\n")
    write(repo / "parts" / "offboard" / "v0.2-display.csv", "y\n")
    git(repo, "init", "-q")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "v0.2")
    return repo, git(repo, "log", "-1", "--format=%h").strip()


def test_version_new_does_p22s_mechanical_steps(tmp_path):
    repo, commit = series_repo(tmp_path)
    code, records = run("version", "new", repo, "v0.3")
    assert code == 0, records
    new = repo / "v0.3"
    assert (new / "design.py").read_text() == 'LABEL = "v0.2"\n' and (
        new / "display" / "display.kicad_pro"
    ).is_file()
    assert not (new / "build").exists()
    lines = (new / "README.md").read_text().splitlines()
    assert lines[0] == "# Board v0.3"
    assert lines[2] == (
        "> The current version of the [Board series](../README.md), started as a copy of "
        "[`../v0.2/`](../v0.2/). The earlier versions are the sibling folders, "
        "[`../v0.1/`](../v0.1/) to [`../v0.2/`](../v0.2/)."
    )
    assert (repo / "v0.2" / "README.md").read_text().splitlines()[2] == (
        f"> Archived: v0.2 of the [Board series](../README.md), as of commit `{commit}`. "
        "Run the commands below from this folder. The next version, [`../v0.3/`](../v0.3/), is in work."
    )
    rows = (repo / "README.md").read_text().splitlines()
    assert rows[4:7] == [
        "| [v0.3](v0.3/) (current) | as v0.2 | yes | in work |",
        f"| [v0.2](v0.2/) | 20 mm | yes | `{commit}` |",
        "| [v0.1](v0.1/) | 10 mm | yes | `abc1234` |",
    ]
    assert (repo / "CLAUDE.md").read_text() == (
        "Folders `v0.1/` to `v0.3/`; copy the latest (`v0.4/` from `v0.3/`). Run `gates v0.3`.\n"
    )
    assert (repo / "parts" / "version" / "v0.3.csv").read_text() == "x\n"
    assert (repo / "parts" / "offboard" / "v0.3-display.csv").read_text() == "y\n"
    todo = records[0]["details"]["todo"]
    assert "v0.3/design.py names v0.2 on lines 1: labels and notes" in todo
    assert "    README.md:9: The latest version, [v0.2](v0.2/)." in todo
    # P22 step 4: the previous folder differs from its commit by its banner alone.
    assert git(repo, "diff", "--numstat", commit, "--", "v0.2/").split() == ["1", "1", "v0.2/README.md"]


def test_version_new_refuses_an_existing_or_earlier_version(tmp_path):
    repo, _ = series_repo(tmp_path)
    for name, message in (
        ("v0.2", "exists already"),
        ("v0.1.5", "is not after v0.2, the latest version"),
        ("v0.17x", "is not a version name"),
    ):
        proc = subprocess.run(
            [sys.executable, str(CLI), "version", "new", str(repo), name],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1 and message in proc.stderr, (name, proc.stderr)
    assert sorted(p.name for p in repo.iterdir() if p.name.startswith("v")) == ["v0.1", "v0.2"]


# ----------------------------------------------------------------- diagram

SPEC = {
    "title": "Test: blocks and paths",
    "subtitle": "a subtitle",
    "blocks": [
        {"id": "A", "x": 20, "y": 80, "w": 100, "style": "power", "title": "U1 charger", "lines": ["4.2 V"]},
        {"id": "B", "x": 200, "y": 80, "w": 100, "title": "U2", "lines": ["LDO"]},
        {"id": "C", "x": 200, "y": 200, "w": 100, "dash": True, "title": "R1 R2", "notes": ["divider"]},
    ],
    "rails": [{"id": "VBAT", "label": "+BATT", "style": "power", "x": 400, "y": 60, "h": 200}],
    "groups": [{"label": "Display board", "x": 190, "y": 70, "w": 130, "h": 80}],
    "arrows": [
        {"from": "A", "to": "B", "style": "power", "y": 100, "label": "VBUS"},
        {"from": "A", "to": "C", "style": "sense"},
        {"from": "B", "to": "VBAT", "style": "power"},
    ],
    "dots": [[160, 100]],
}


def test_diagram_draws_blocks_rails_arrows_and_a_legend(tmp_path):
    spec = write(tmp_path / "spec.json", json.dumps(SPEC))
    code, records = run("diagram", spec, "--out", tmp_path / "out" / "d.svg")
    assert code == 0, records
    svg = (tmp_path / "out" / "d.svg").read_text(encoding="utf-8")
    root = ET.fromstring(svg)
    ns = "{http://www.w3.org/2000/svg}"
    texts = [t.text for t in root.iter(f"{ns}text")]
    assert root.find(f"{ns}title").text == "Test: blocks and paths"
    assert {"U1 charger", "4.2 V", "U2", "LDO", "R1 R2", "divider", "+BATT", "Display board", "VBUS"} <= set(
        texts
    )
    # The legend names the styles lines use, not a style only a block uses, nor one nothing uses.
    assert {"Legend", "power", "sensing", "a junction", "a board or an assembly"} <= set(texts)
    assert "data" not in texts and "logic and control" not in texts
    assert sorted(m.get("id") for m in root.iter(f"{ns}marker")) == ["m-power", "m-sense"]
    paths = [p.get("d") for p in root.iter(f"{ns}path") if p.get("stroke")]
    assert "M120,100 L198,100" in paths  # the y the spec gives, ending 2 px short of B for the head
    # A to C overlap in neither x nor y: out of A's side at its middle (80 + 47.5 / 2), along to
    # halfway, down to C's middle, into C.
    assert "M120,103.8 L159,103.8 L159,223.8 L198,223.8" in paths
    assert "M300,103.8 L398,103.8" in paths  # B into the rail at the middle of their overlap


def test_diagram_refuses_an_unknown_block_and_writes_nothing(tmp_path):
    spec = dict(
        SPEC, arrows=[{"from": "A", "to": "NOPE", "style": "power"}, {"from": "A", "to": "B", "style": "x"}]
    )
    path = write(tmp_path / "spec.json", json.dumps(spec))
    code, records = run("diagram", path, "--out", tmp_path / "d.svg")
    assert code == 1 and not (tmp_path / "d.svg").exists()
    failures = records[0]["details"]["failures"]
    assert any("'NOPE'" in f for f in failures) and any("style 'x'" in f for f in failures)


@needs_rsvg
def test_diagram_png(tmp_path):
    spec = write(tmp_path / "spec.json", json.dumps(SPEC))
    code, records = run("diagram", spec, "--out", tmp_path / "d.svg", "--png")
    assert code == 0, records
    assert (tmp_path / "d.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"


def test_the_starter_spec_draws():
    spec = ROOT / "templates" / "verification" / "system" / "block-diagram.json"
    svg = doctools.Diagram(json.loads(spec.read_text(encoding="utf-8")))
    svg.render()
    assert svg.problems == []


# ---------------------------------------------------------------- pictures


def test_default_manifest_names_each_board_and_each_scene(tmp_path):
    v = tmp_path / "v0.1"
    shutil.copytree(BOARDS / "pass-rc-divider", v)
    shutil.copytree(BOARDS / "pass-rc-divider", v / "display")
    write(v / "assembly.py", '"""The assembly."""\nimport scene\n')
    write(v / "helper.py", '"""Not a scene."""\n')
    manifest = doctools.default_manifest(v)
    assert [(b["path"], b["name"], b["prefix"], b["layers"]) for b in manifest["boards"]] == [
        (".", "base", "", "layers-base.png"),
        ("display", "display", "display-", "layers-display.png"),
    ]
    # The fixture has parts on its top face only: one GIF from above.
    assert [s["as"] for s in manifest["boards"][1]["spins"]] == ["display-board-spin.gif"]
    assert manifest["scenes"] == [{"script": "assembly.py", "what": "The assembly", "copy": {}}]
    write(tmp_path / "both.kicad_pcb", '(footprint "A" (layer "F.Cu"))\n(footprint "B" (layer "B.Cu"))\n')
    assert doctools.both_faces(tmp_path / "both.kicad_pcb")


def test_pictures_refuses_a_manifest_naming_what_is_not_there(tmp_path):
    v = tmp_path / "v0.1"
    shutil.copytree(BOARDS / "pass-rc-divider", v)
    write(v / "pictures.json", json.dumps({"boards": [], "scenes": [{"script": "gone.py"}]}))
    code, records = run("pictures", v)
    assert code == 1 and "no script gone.py" in records[0]["summary"]
    assert not (v / "docs").exists()


SCENE_STUB = """import os, sys
from pathlib import Path
import doctools  # on PYTHONPATH from `workcenter pictures`
out = Path("build/stub").resolve()
out.mkdir(parents=True, exist_ok=True)
(out / "pic.txt").write_text(os.environ["WORKCENTER_SRC"])
if os.environ.get("WORKCENTER_PICTURES_CHECK"):
    print(f"frames: {out / 'pic.txt'}")
"""


@needs_kicad
@needs_ffmpeg
def test_pictures_draws_copies_and_checks_the_framing(tmp_path):
    v = tmp_path / "v0.1"
    shutil.copytree(BOARDS / "pass-rc-divider", v)
    write(v / "stub.py", SCENE_STUB)
    manifest = {
        "boards": [
            {
                "path": ".",
                "name": "base",
                "prefix": "",
                "strict": False,  # the fixture's library bodies are not installed everywhere
                "stills": ["board-top.png", "schematic.png"],
                "layers": "layers-base.png",
                "spins": [{"as": "board-spin.gif", "tilt": -55, "zoom": 0.9, "frames": 2}],
            }
        ],
        "scenes": [{"script": "stub.py", "copy": {"build/stub/pic.txt": "pic.txt"}}],
    }
    write(v / "pictures.json", json.dumps(manifest))
    code, records = run("pictures", v, "--frames", "2")
    assert code == 0, records
    assert not (v / "docs").exists()  # the framing check writes into build/ only
    sheet = v / "build" / "pictures" / "check" / "board-spin" / "board-spin-frames.png"
    assert records[0]["artifacts"] == [str(sheet), str(v / "build" / "stub" / "pic.txt")]
    assert sheet.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    code, records = run("pictures", v)
    assert code == 0, records
    docs = v / "docs"
    assert (docs / "board-top.png").read_bytes()[:4] == b"\x89PNG" and (docs / "schematic.png").is_file()
    assert (docs / "layers-base.png").is_file() and (docs / "layers" / "base-F-Cu.png").is_file()
    assert (docs / "board-spin.gif").read_bytes()[:6] == b"GIF89a"
    assert (docs / "pic.txt").read_text() == str(ROOT)
    assert "board-bottom.png" not in records[0]["details"]["copied"]


# ------------------------------------------------------------------- scene

SCENE_SCRIPT = """import scene
s = scene.Scene("board/rc_divider.kicad_pcb", out="build/scene", name="rc_scene")
box = s.box("box.wrl", (4.0, 3.0, 2.0))
can = s.cylinder("can.wrl", d=5.0, length=8.0, caps=(0.8, 0.8, 0.8))
x, y = s.position("R1")
s.place(box, (x, y, 1.6))
s.place(can, (x + 5.0, y, 0.0), rotate=(0, 0, 90))
print("saved", s.save())
s.stills({"iso": {"rotate": "-45,0,30", "zoom": 0.8, "width": 320, "height": 200}})
s.spin("turn.gif", zoom=0.8, frames=2)
"""


@needs_kicad
@needs_ffmpeg
def test_a_scene_places_bodies_renders_and_turns(tmp_path):
    import os

    shutil.copytree(BOARDS / "pass-rc-divider", tmp_path / "board")
    # A body the project keeps beside its board, named the way a generated board names it.
    pcb_file = tmp_path / "board" / "rc_divider.kicad_pcb"
    footprint = '(footprint "Resistor_SMD:R_0603_1608Metric" (layer "F.Cu")'
    text = pcb_file.read_text(encoding="utf-8")
    pcb_file.write_text(
        text.replace(footprint, footprint + ' (model "${KIPRJMOD}/models/body.wrl")', 1), encoding="utf-8"
    )
    write(tmp_path / "board" / "models" / "body.wrl", "#VRML V2.0 utf8\n")
    script = write(tmp_path / "scene_test.py", SCENE_SCRIPT)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "tools"), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("WORKCENTER_PICTURES_CHECK", None)
    venv = Path("/opt/workcenters/ee/venv/bin/python")
    python = str(venv) if venv.exists() else sys.executable  # where `workcenter pictures` runs a scene
    proc = subprocess.run([python, str(script)], capture_output=True, text=True, env=env, check=False)
    if "No module named 'pcbnew'" in proc.stderr:
        pytest.skip("KiCad's pcbnew module is not importable")
    assert proc.returncode == 0, proc.stderr[-2000:]
    out = tmp_path / "build" / "scene"
    assert (out / "bodies" / "box.wrl").is_file() and (out / "bodies" / "can.wrl").is_file()
    pcb = (out / "rc_scene.kicad_pcb").read_text(encoding="utf-8")
    assert '"SCENE1"' in pcb and '"SCENE2"' in pcb and str(out / "bodies" / "box.wrl") in pcb
    # The project's body resolves beside the scene's board, where ${KIPRJMOD} points once it is saved.
    assert '"${KIPRJMOD}/models/body.wrl"' in pcb and (out / "models" / "body.wrl").read_text().startswith(
        "#VRML"
    )
    assert "(xyz 0 0 1.6)" in pcb and "(xyz 0 0 90)" in pcb
    assert (out / "iso.png").read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert (out / "turn.gif").read_bytes()[:6] == b"GIF89a"
    # The framing check: no stills, a sheet of the GIF's frames, named for `workcenter pictures`.
    (out / "iso.png").unlink()
    env["WORKCENTER_PICTURES_CHECK"] = "1"
    proc = subprocess.run([python, str(script)], capture_output=True, text=True, env=env, check=False)
    assert proc.returncode == 0, proc.stderr[-2000:]
    assert not (out / "iso.png").exists()
    assert f"frames: {out / 'turn-frames.png'}" in proc.stdout.splitlines()
