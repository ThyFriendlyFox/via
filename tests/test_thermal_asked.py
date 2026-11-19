"""Roadmap item 7, the parts the SIM gate asks for: every part of the board whose facts carry a thermal
figure, whether sim/thermal.json names it or not; and the record of a run that SPRA953D's equation 5
judged. No test here starts an engine.

The numbers are read from these documents:
- TLV755P datasheet SBVS320D, section 5.4, page 5: the JEDEC rows of the DBV column, RthetaJA 231.1,
  RthetaJC(top) 118.4, RthetaJB 64.4, psiJT 28.4 and psiJB 63.8 C/W; section 5.1, page 4: an operating
  junction of 150 C at the most (tests/boards/library/facts/ti-tlv755p.json).
- TI SPRA953D, section 1.1, equation 1, page 2: TJ = TA + RthetaJA x power; section 2.2, equation 4,
  page 7: TJ = TC + RthetaJC x power; equation 5: TJ = TA + (RthetaJC + Rtheta(CS) + Rtheta(SA)) x power.
- ECSS-Q-ST-30-11C Rev.2, clause 6.21.2, table 6-21, page 57: 110 C or Tjmax - 40 C, the lower.
"""

from __future__ import annotations

import importlib.machinery
import json
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
FACTS = BOARDS / "library" / "facts"
sys.path.insert(0, str(ROOT / "tools"))
import guide  # noqa: E402
import ratings  # noqa: E402
import thermal  # noqa: E402

# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {
    "ti-sbvs320": "sections 5.1 and 5.4, pages 4 and 5",
    "ti-spra953d": "section 1.1, equation 1, page 2; section 2.2, equations 4 and 5, page 7",
    "ecss-q-st-30-11c-rev2": "clause 6.21.2, table 6-21, page 57",
}

FACTS_LIST = ratings.read_facts(FACTS)
ECSS = ratings.read_pack(ROOT / "rules" / "ratings" / "ecss-q-st-30-11c-rev2.json")
TLV = next(f for f in FACTS_LIST if f.data.get("mpn") == "TLV75533PDBVR")
CAP = next(f for f in FACTS_LIST if "thermal" not in f.data)
U1_LINE = (
    "thermal: U1 (TLV75533PDBVR) not judged: its facts (ti-tlv755p.json) carry junction_max 150 C and "
    "theta_ja 231.1 C/W, theta_jc 118.4 C/W, theta_jb 64.4 C/W, psi_jt 28.4 C/W and psi_jb 63.8 C/W (p 4 "
    "and 5), and sim/thermal.json names no row for it: write its row under `parts` (the simulate skill, A "
    'part\'s temperature, step 3): "U1": {"mpn": "TLV75533PDBVR", "watts": "<deck>.<measure>", '
    '"source": "<how the deck gives its power>"}'
)


def load_cli() -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_thermal_asked", str(CLI))
    module = types.ModuleType("workcenter_cli_thermal_asked")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module  # dataclasses look the defining module up here
    loader.exec_module(module)
    return module


# ---------------------------------------------------------------- the parts asked for


def test_a_part_whose_facts_carry_a_thermal_figure_and_no_row_is_not_judged_and_named():
    """U1's facts carry junction_max 150 C and 5 figures; the plan names only U9, so U1 is asked for, on 1
    line that names the part, every figure its facts carry with their pages, and the row to write. C1's
    facts carry no `thermal`: it is not asked for."""
    entries = {"U1": ("TLV75533PDBVR", TLV), "C1": ("CL10A106KP8NNN", CAP), "R1": ("", None)}
    board = thermal.asked(entries, {"U9": "TLV75533PDBVR"})
    assert board["not_judged"] == [U1_LINE]
    assert board["asked"] == ["U1"] and board["unplanned"] == ["U1"]
    assert board["line"] == (
        "thermal: 1 part of the board carries a thermal figure in its facts: U1; sim/thermal.json names 0 "
        "of them"
    )


def test_the_same_part_named_in_the_plan_is_asked_for_and_not_named_again():
    """The same board with U1's row: nothing is left unjudged by the board's parts."""
    entries = {"U1": ("TLV75533PDBVR", TLV), "C1": ("CL10A106KP8NNN", CAP)}
    board = thermal.asked(entries, {"U1": "TLV75533PDBVR"})
    assert board["not_judged"] == [] and board["unplanned"] == [] and board["failures"] == []
    assert board["line"] == (
        "thermal: 1 part of the board carries a thermal figure in its facts: U1; sim/thermal.json names 1 "
        "of them"
    )


DRV = next(f for f in FACTS_LIST if f.data.get("mpn") == "TLV75533PDRVR")


def test_a_row_that_names_another_part_number_does_not_name_the_board_s_part_and_fails():
    """Finding L7B-1. parts.csv gives U1 the DBV part, TLV75533PDBVR (RthetaJA 231.1 C/W, SBVS320D
    section 5.4, page 5); the row names the WSON part, TLV75533PDRVR (RthetaJA 100.2 C/W, the DRV column
    of the same table). judge() would hold U1 on the DRV facts: the row does not name the board's part,
    so it fails, and the plan names 0 of the 1 part that carries a figure."""
    entries = {"U1": ("TLV75533PDBVR", TLV)}
    board = thermal.asked(entries, {"U1": "TLV75533PDRVR"}, parts="parts.csv")
    assert board["failures"] == [
        "thermal: U1 (TLV75533PDBVR) is judged on facts that are not its own: its row in sim/thermal.json "
        "names TLV75533PDRVR, and parts.csv gives TLV75533PDBVR: write the board's part number in its row "
        "(the simulate skill, A part's temperature, step 3)"
    ]
    assert board["mismatched"] == ["U1"] and board["not_judged"] == []
    assert board["line"].endswith("sim/thermal.json names 0 of them")


def test_a_row_for_a_part_with_no_number_must_name_the_facts_entry_of_the_board_s_part():
    """U1 has no part number and is matched by its facts entry (the DBV entry): a row naming the DRV
    part's number names facts that are not U1's entry, and fails."""
    board = thermal.asked({"U1": ("", TLV)}, {"U1": "TLV75533PDRVR"})
    assert board["failures"] == [
        "thermal: U1 (TLV75533PDBVR) is judged on facts that are not its own: its row in sim/thermal.json "
        "names TLV75533PDRVR, and the facts entry of the board's part (ti-tlv755p.json) does not name it: "
        "write the board's part number in its row (the simulate skill, A part's temperature, step 3)"
    ]
    assert thermal.asked({"U1": ("", TLV)}, {"U1": "TLV75533PDBVR"})["failures"] == []


def part(ref: str, pins: int) -> ratings.Part:
    return ratings.Part(ref, "x", "x:x", "x:x", True, pins={str(n): f"N{n}" for n in range(1, pins + 1)})


def test_a_part_could_be_an_entry_with_a_thermal_figure_only_when_it_has_every_pin_the_entry_names():
    """Finding L7B-2. The DBV entry names pins 1 to 5 (SBVS320D table 4-1, page 3); the DRV entry names
    pins 1 to 7, the pad 7 among them; BQ21040DBVR names 1 to 6. A part of 5 pins could be the DBV part
    alone, a part of 2 pins none of them, and a part of 7 pins any of the 3."""
    hot = [f for f in FACTS_LIST if "thermal" in f.data]
    assert [f.name for f in thermal.could_be(part("U1", 5), hot)] == ["TLV75533PDBVR"]
    assert thermal.could_be(part("R1", 2), hot) == []
    assert len(thermal.could_be(part("U2", 7), hot)) == 3


def test_a_part_with_no_number_that_could_carry_a_thermal_figure_is_not_judged_and_not_said_to_carry_none():
    """Finding L7B-2. The project has no parts.csv, so U1 has no part number and no facts entry; its
    pins are those of the DBV entry. The gate cannot say that no part carries a thermal figure: U1 is not
    judged, on 1 line that says why. R1 could be no entry with a figure: it is not named."""
    entries = {"U1": ("", None), "R1": ("", None)}
    board = thermal.asked(entries, None, maybe={"U1": [TLV]}, parts=None)
    assert board["not_judged"] == [
        "thermal: U1 not judged: the project has no parts.csv to give its part number and no facts entry "
        "names it by its symbol, and it has the pins of TLV75533PDBVR (ti-tlv755p.json), whose facts carry "
        "a thermal figure: give its part number in parts.csv beside the schematic, the file the gate reads "
        "it from"
    ]
    assert board["unplanned"] == ["U1"]
    assert board["line"] == (
        "thermal: no part of the board is known to carry a thermal figure in its facts; 1 part with no "
        "part number may: U1"
    )


def test_with_no_plan_every_part_with_a_thermal_figure_is_named():
    """No sim/thermal.json: U1 and U2 are both asked for, in the board's order (U2 before U10)."""
    entries = {"U10": ("TLV75533PDBVR", TLV), "U2": ("TLV75533PDBVR", TLV)}
    board = thermal.asked(entries, None)
    assert [line.split(" not judged")[0] for line in board["not_judged"]] == [
        "thermal: U2 (TLV75533PDBVR)",
        "thermal: U10 (TLV75533PDBVR)",
    ]


def test_a_board_with_no_part_that_carries_a_thermal_figure_says_so_in_1_line():
    """3 parts: C1's facts carry no thermal figure, R1 and R2 have no facts entry. Nothing is asked for,
    and the line counts the 2 parts with no facts, which `workcenter ratings` names."""
    entries = {"C1": ("CL10A106KP8NNN", CAP), "R1": ("", None), "R2": ("", None)}
    board = thermal.asked(entries, None)
    assert board["not_judged"] == [] and board["asked"] == []
    assert board["line"] == (
        "thermal: no part of the board carries a thermal figure in its facts, so no junction is asked for "
        "(3 parts; 2 with no facts entry, which `workcenter ratings` names)"
    )


SYMBOL_ONLY = ratings._facts(
    "sym.json", {**{k: v for k, v in TLV.data.items() if k != "mpn"}, "symbol": "Regulator_Linear:LDO"}
)
BY_SYMBOL = (
    "which no row of sim/thermal.json can name: a row names a part by its number, and judge() reads the "
    "facts by that number. Give the part its number in parts.csv beside the schematic, and a facts entry "
    "that names that number (the ratings skill)"
)


def test_a_part_named_by_its_symbol_is_told_it_needs_a_number_and_is_handed_no_row():
    """Finding L7B2-2. U1 has no part number; its facts entry names it by its symbol alone (the ratings
    skill's form for a part with no number). A row reads facts by its part number, so no row can name
    that entry: the line says what the part needs, and hands out no row the gate would refuse."""
    board = thermal.asked({"U1": ("", SYMBOL_ONLY)}, None)
    assert board["not_judged"] == [
        "thermal: U1 (Regulator_Linear:LDO) not judged: its facts (sym.json) carry junction_max 150 C and "
        "theta_ja 231.1 C/W, theta_jc 118.4 C/W, theta_jb 64.4 C/W, psi_jt 28.4 C/W and psi_jb 63.8 C/W (p 4 "
        "and 5) and name it by its symbol, " + BY_SYMBOL
    ]
    assert '"mpn"' not in board["not_judged"][0]


def test_a_row_for_a_part_named_by_its_symbol_says_what_the_part_needs():
    """Finding L7B2-2. The row names the symbol, as the line used to hand out: the row still fails, as
    judge() finds no facts entry by that number, and the line says what the part needs, not to write the
    board's part number in the row, which the board does not give."""
    board = thermal.asked({"U1": ("", SYMBOL_ONLY)}, {"U1": "Regulator_Linear:LDO"})
    assert board["failures"] == [
        "thermal: U1 (Regulator_Linear:LDO) is judged on facts that are not its own: its row in "
        "sim/thermal.json names Regulator_Linear:LDO, and the facts entry of the board's part (sym.json) "
        "names it by its symbol, " + BY_SYMBOL
    ]


def test_a_part_with_no_number_judged_by_its_row_is_counted_among_the_parts_with_a_figure():
    """Finding L7B2-3. No parts.csv gives U1 a number; its pins fit the DBV entry and its row names
    TLV75533PDBVR, so judge() judges it on that entry's figures. The board's line counts U1 among the
    parts that carry a figure, and says the number is its row's, not a parts file's."""
    entries = {"U1": ("", None), "R1": ("", None)}
    board = thermal.asked(entries, {"U1": "TLV75533PDBVR"}, maybe={"U1": [TLV]}, parts=None)
    assert board["not_judged"] == [] and board["failures"] == []
    assert board["asked"] == ["U1"]
    assert board["line"] == (
        "thermal: 1 part of the board carries a thermal figure in its facts: U1; sim/thermal.json names 1 "
        "of them; U1 has no part number from a parts file: TLV75533PDBVR is its row's in sim/thermal.json"
    )


def test_a_row_for_a_reference_that_is_no_fitted_part_of_the_board_is_named():
    """Finding L7B2-5. The board has U1; the plan has a row for U1 and one for U2, which the schematic
    does not carry (or marks not fitted): U2's row is named, as a warning, and is not judged. The record
    keeps what the row named. The line says what clears it: the row under the board's reference, the row
    taken out, or the file deleted when it is the only row (a file with no row is refused)."""
    board = thermal.asked({"U1": ("TLV75533PDBVR", TLV)}, {"U1": "TLV75533PDBVR", "U2": "TLV75533PDRVR"})
    assert board["strays"] == {
        "U2": {
            "mpn": "TLV75533PDRVR",
            "line": "thermal: U2 of sim/thermal.json is no fitted part of the board: the schematic has no "
            "U2, or marks it not fitted, so its row (TLV75533PDRVR) is not judged: write the row under the "
            "board part's reference, or take it out; if it is the only row, delete sim/thermal.json",
        }
    }
    assert board["asked"] == ["U1"] and board["failures"] == [] and board["not_judged"] == []
    assert thermal.asked({"U1": ("TLV75533PDBVR", TLV)}, {"U1": "TLV75533PDBVR"})["strays"] == {}


def test_a_row_for_a_fitted_part_whose_facts_could_not_be_read_is_no_stray():
    """U2 is on the board, but 2 facts entries speak of it as closely, so it has no entry (the gate says
    so on its own line). Its row is no stray: a stray is not judged, and U2 is fitted."""
    board = thermal.asked(
        {"U1": ("TLV75533PDBVR", TLV)}, {"U1": "TLV75533PDBVR", "U2": "TLV75533PDBVR"}, unread=("U2",)
    )
    assert board["strays"] == {}


# ---------------------------------------------------------------- the gate's reading of the board


def project_at(cli, folder: Path, sch: bool):
    folder.mkdir(parents=True, exist_ok=True)
    schematic = folder / "node.kicad_sch"
    if sch:
        schematic.write_text("(kicad_sch)", encoding="utf-8")
    return cli.Project(folder, "node", None, schematic if sch else None, None)


def test_a_project_with_no_facts_says_so_in_1_line_and_starts_no_engine(tmp_path, monkeypatch):
    """No library/facts: no part carries a thermal figure. kicad-cli is pointed at nothing, so a run that
    asked for it would say so: the 1 line is the whole answer."""
    cli = load_cli()
    monkeypatch.setattr(cli, "KICAD_CLI", "no-such-kicad-cli")
    project = project_at(cli, tmp_path / "board", sch=True)
    record, unjudged = cli.thermal_board(project, tmp_path / "out", None)
    assert unjudged == []
    assert record["line"] == (
        "thermal: the project has no library/facts, so no part of the board carries a thermal figure and "
        "none is asked for; `workcenter ratings` names the parts with no facts"
    )


def test_facts_with_no_thermal_figure_say_so_in_1_line_and_start_no_engine(tmp_path, monkeypatch):
    """A library whose 1 entry, a capacitor, carries no `thermal`: nothing is asked for."""
    cli = load_cli()
    monkeypatch.setattr(cli, "KICAD_CLI", "no-such-kicad-cli")
    (tmp_path / "library" / "facts").mkdir(parents=True)
    (tmp_path / "library" / "facts" / "c.json").write_text(json.dumps(CAP.data), encoding="utf-8")
    project = project_at(cli, tmp_path / "board", sch=True)
    record, unjudged = cli.thermal_board(project, tmp_path / "out", None)
    assert unjudged == []
    assert record["line"] == (
        "thermal: no facts entry of library/facts carries a thermal figure (1 entry), so no part of the "
        "board is asked for"
    )


def test_a_project_with_no_schematic_names_no_part_of_a_board(tmp_path):
    """Thermal facts and no schematic: the project names no part of a board, and the line says that only
    the plan's parts are judged."""
    cli = load_cli()
    (tmp_path / "library" / "facts").mkdir(parents=True)
    (tmp_path / "library" / "facts" / "u.json").write_text(json.dumps(TLV.data), encoding="utf-8")
    project = project_at(cli, tmp_path / "board", sch=False)
    record, unjudged = cli.thermal_board(project, tmp_path / "out", {"U1": "TLV75533PDBVR"})
    assert unjudged == []
    assert record["line"] == (
        "thermal: the project has no schematic, so it names no part of a board: only the parts "
        "sim/thermal.json names are judged"
    )


LDO_DECK = "* U1, a TLV75533PDBVR, takes 5 V to 3.3 V.\nVIN in 0 DC 5\n.end\n"


def test_with_no_schematic_a_part_number_a_deck_names_whose_facts_carry_a_figure_is_asked_for(tmp_path):
    """Finding L7B2-1. Decks, thermal facts and no schematic, the stage of simulating before layout. The
    deck names TLV75533PDBVR, whose facts carry a thermal figure; with no sim/thermal.json it is not
    judged, which fails --strict. The same project with the row is judged on it; a deck that names no such
    number leaves the 1 line as before."""
    cli = load_cli()
    (tmp_path / "library" / "facts").mkdir(parents=True)
    (tmp_path / "library" / "facts" / "u.json").write_text(json.dumps(TLV.data), encoding="utf-8")
    project = project_at(cli, tmp_path / "board", sch=False)
    (project.dir / "sim").mkdir()
    (project.dir / "sim" / "ldo.cir").write_text(LDO_DECK, encoding="utf-8")
    record, unjudged = cli.thermal_board(project, tmp_path / "out", None)
    assert unjudged == [
        "thermal: TLV75533PDBVR (named by ldo.cir) not judged: its facts (u.json) carry junction_max 150 C "
        "and theta_ja 231.1 C/W, theta_jc 118.4 C/W, theta_jb 64.4 C/W, psi_jt 28.4 C/W and psi_jb 63.8 C/W "
        "(p 4 and 5), and sim/thermal.json names no row for it: write its row under `parts`, under the "
        "reference the part will have on the board (the simulate skill, A part's temperature, step 3): "
        '"<reference>": {"mpn": "TLV75533PDBVR", "watts": "<deck>.<measure>", "source": "<how the deck '
        'gives its power>"}'
    ]
    assert record["line"] == (
        "thermal: the project has no schematic, so it names no part of a board; its decks name 1 part "
        "number whose facts carry a thermal figure: TLV75533PDBVR; sim/thermal.json names 0 of them"
    )
    record, unjudged = cli.thermal_board(project, tmp_path / "out", {"U1": "TLV75533PDBVR"})
    assert unjudged == [] and record["line"].endswith("sim/thermal.json names 1 of them")
    (project.dir / "sim" / "ldo.cir").write_text("VIN in 0 DC 5\n.end\n", encoding="utf-8")
    record, unjudged = cli.thermal_board(project, tmp_path / "out", None)
    assert unjudged == [] and record["line"] == thermal.NO_SCHEMATIC


def test_a_schematic_kicad_cli_cannot_read_leaves_the_board_s_parts_not_judged(tmp_path, monkeypatch):
    """Thermal facts and a schematic, and no kicad-cli: which parts carry a figure is not judged, 1 line
    with the reason; --strict fails on it as on every not-judged line."""
    cli = load_cli()
    monkeypatch.setattr(cli, "KICAD_CLI", "no-such-kicad-cli")
    (tmp_path / "library" / "facts").mkdir(parents=True)
    (tmp_path / "library" / "facts" / "u.json").write_text(json.dumps(TLV.data), encoding="utf-8")
    project = project_at(cli, tmp_path / "board", sch=True)
    record, unjudged = cli.thermal_board(project, tmp_path / "out", None)
    assert record["line"] is None
    assert unjudged == [
        "thermal: which parts of the board carry a thermal figure is not judged: no-such-kicad-cli is not "
        "on PATH to read the schematic's parts"
    ]


def test_the_row_of_a_fitted_part_whose_facts_are_refused_is_no_stray(tmp_path, monkeypatch):
    """The board fits U1 and U2; 2 facts entries speak of U2 as closely, so its facts are refused on 1
    line. U2 is fitted: its row is no stray, so gate_sim judges it by its number. Before, the gate also
    called the row no fitted part of the board, and left it out of judge()."""
    cli = load_cli()
    monkeypatch.setattr(cli, "KICAD_CLI", "sh")
    (tmp_path / "library" / "facts").mkdir(parents=True)
    (tmp_path / "library" / "facts" / "u.json").write_text(json.dumps(TLV.data), encoding="utf-8")
    project = project_at(cli, tmp_path / "board", sch=True)
    net = ratings.Netlist({"U1": part("U1", 5), "U2": part("U2", 5)}, {})
    monkeypatch.setattr(ratings, "export_netlist", lambda *a: (net, ""))

    def facts_of(facts, p, mpn):
        if p.ref == "U2":
            raise ratings.Refusal("2 entries speak of U2 as closely")
        return TLV

    monkeypatch.setattr(ratings, "facts_of", facts_of)
    named = {"U1": "TLV75533PDBVR", "U2": "TLV75533PDBVR"}
    record, unjudged = cli.thermal_board(project, tmp_path / "out", named)
    assert record["strays"] == {}
    assert unjudged == ["thermal: U2 not judged: 2 entries speak of U2 as closely"]


def test_a_stray_row_comes_before_the_part_it_leaves_out(tmp_path, monkeypatch):
    """The row of the board's U1 stands under U2. The stray line comes first, so `next` names its step:
    moving the row clears both lines."""
    cli = load_cli()
    monkeypatch.setattr(cli, "KICAD_CLI", "sh")
    (tmp_path / "library" / "facts").mkdir(parents=True)
    (tmp_path / "library" / "facts" / "u.json").write_text(json.dumps(TLV.data), encoding="utf-8")
    project = project_at(cli, tmp_path / "board", sch=True)
    net = ratings.Netlist({"U1": part("U1", 5)}, {})
    monkeypatch.setattr(ratings, "export_netlist", lambda *a: (net, ""))
    monkeypatch.setattr(ratings, "facts_of", lambda *a: TLV)
    record, unjudged = cli.thermal_board(project, tmp_path / "out", {"U2": "TLV75533PDBVR"})
    assert unjudged == [record["strays"]["U2"]["line"], *record["not_judged"]]
    assert len(unjudged) == 2 and unjudged[1].startswith("thermal: U1 (TLV75533PDBVR) not judged")


def test_a_project_with_no_deck_still_asks_for_the_parts_that_carry_a_thermal_figure(tmp_path, monkeypatch):
    """Finding L7B-3. A project with no sim/*.cir: the board's parts are asked for all the same, as no
    deck gives their power. A part not judged is a warning, and fails --strict; with nothing asked for
    the gate skips as before, with the board's line in the record."""
    cli = load_cli()
    project = project_at(cli, tmp_path / "board", sch=True)
    monkeypatch.setattr(cli, "deck_needs", lambda *a: ([], []))
    seen = []

    def board(project, folder, named):
        seen.append(named)
        return {"line": "thermal: x", "unplanned": ["U1"]}, ["thermal: U1 (BQ21040DBVR) not judged: y"]

    monkeypatch.setattr(cli, "thermal_board", board)
    strict = cli.gate_sim(project, tmp_path / "out", strict=True)
    assert strict.status == "fail" and seen == [None]
    assert strict.details["failures"] == ["thermal: U1 (BQ21040DBVR) not judged: y"]
    assert strict.details["thermal"]["board"] == {"line": "thermal: x", "unplanned": ["U1"]}
    loose = cli.gate_sim(project, tmp_path / "out", strict=False)
    assert loose.status == "skip" and loose.details["warnings"] == ["thermal: U1 (BQ21040DBVR) not judged: y"]
    monkeypatch.setattr(cli, "thermal_board", lambda *a: ({"line": "thermal: none"}, []))
    quiet = cli.gate_sim(project, tmp_path / "out", strict=True)
    assert quiet.status == "skip" and quiet.summary == "no sim/*.cir in project"
    assert quiet.details["thermal"]["board"] == {"line": "thermal: none"}


def test_the_record_carries_the_board_s_line_and_the_gate_prints_it():
    """`sim` and `gates` print the board's line from the record, after the line of no plan."""
    details = {"thermal": {"parts": {}, "unplanned": thermal.NO_PLAN, "board": {"line": "thermal: x"}}}
    assert thermal.lines(details) == [thermal.NO_PLAN, "thermal: x"]


# ---------------------------------------------------------------- workcenter next


def test_workcenter_next_sends_an_unplanned_part_to_step_3_of_the_skill():
    """The not-judged line of a part with no row asks for its row in sim/thermal.json."""
    do, read = guide.hint("sim", U1_LINE)
    assert do.startswith("Write the part's row in sim/thermal.json, as the line gives it (step 3).")
    assert read.endswith('"A part\'s temperature"')


def test_workcenter_next_names_the_step_each_new_thermal_line_asks_for():
    """Finding L7B2-4. Each of these lines asks for its own step: a part number in parts.csv beside the
    schematic, the board part's own number in its row, a number and a facts entry for a part named by its
    symbol, a row under the board's reference, and kicad-cli installed. None gets the generic hint."""
    maybe = thermal.asked({"U1": ("", None)}, None, maybe={"U1": [TLV]}, parts=None)["not_judged"][0]
    mismatch = thermal.asked({"U1": ("TLV75533PDBVR", TLV)}, {"U1": "TLV75533PDRVR"})["failures"][0]
    symbol = thermal.asked({"U1": ("", SYMBOL_ONLY)}, None)["not_judged"][0]
    stray = thermal.asked({}, {"U2": "TLV75533PDBVR"})["strays"]["U2"]["line"]
    unread = thermal.UNREAD.format(why="kicad-cli is not on PATH to read the schematic's parts")
    generic, _ = guide.hint("sim", "thermal: x")
    said = {
        name: guide.hint("sim", line)[0]
        for name, line in [
            ("maybe", maybe),
            ("mismatch", mismatch),
            ("symbol", symbol),
            ("stray", stray),
            ("unread", unread),
        ]
    }
    assert generic not in said.values()
    assert said["maybe"].startswith("Give the part its number in parts.csv beside the schematic")
    assert said["mismatch"].startswith("Write the board part's own number in its row")
    assert said["symbol"].startswith("Give the part a number in parts.csv beside the schematic. Write a")
    assert said["stray"] == (
        "Write the row under the reference the board gives the part. If the part is not fitted, take the "
        "row out. If it is the only row, delete sim/thermal.json."
    )
    assert said["unread"].startswith("Install the toolchain")


# ---------------------------------------------------------------- the record of equation 5


def plan_of(tmp_path: Path, parts: dict) -> thermal.Plan:
    (tmp_path / "thermal.json").write_text(
        json.dumps({"pack": "ecss-q-st-30-11c-rev2", "parts": parts}), encoding="utf-8"
    )
    plan, problems = thermal.read_plan(tmp_path, ["ldo"])
    assert problems == []
    return plan


U1 = {"mpn": "TLV75533PDBVR", "watts": "ldo.p_u1", "source": "input power less output power"}
SINK = {"name": "a sink made up for the test", "theta_cs": 0.5, "source": "made up for the test"}


def test_a_run_equation_5_judged_names_theta_jc_and_keeps_what_theta_ja_gave_beside_it(tmp_path):
    """A case stated at 25 C only, on a sink of theta_sa 120 C/W. At 85 C no case is stated, so theta_ja
    gives 85 + 231.1 x 0.17295 = 124.968745 C (equation 1) and equation 5 gives 85 + (118.4 + 0.5 + 120)
    x 0.17295 = 126.317755 C: equation 5 judges, so the row names theta_jc, not theta_ja."""
    case = {"figure": "theta_jc", "celsius": {"25": 27}, "source": "a thermocouple"}
    plan = plan_of(tmp_path, {"U1": {**U1, "from": {**case, "heat_sink": {**SINK, "theta_sa": 120}}}})
    runs = {"ldo": [("85 C", 85.0, {"p_u1": 0.17295})]}
    worst = thermal.judge(plan, runs, FACTS_LIST, ECSS)["parts"]["U1"]["worst"]
    assert worst["equation"] == "5" and worst["figure"] == "theta_jc"
    assert worst["junction"] == pytest.approx(126.317755)
    assert worst["beside"] == {"figure": "theta_ja", "equation": "1", "junction": pytest.approx(124.968745)}


def test_a_run_equation_5_judged_over_a_stated_case_starts_from_the_ambient(tmp_path):
    """A case 0.001 C above the air at 85 C on a sink of theta_sa 30 C/W: equation 4 gives 85.001 + 118.4
    x 0.17295 = 105.47828 C, equation 5 gives 85 + 148.9 x 0.17295 = 110.752255 C. The row names
    equation 5's start, the ambient, and keeps the case beside; the printed line names no case."""
    case = {"figure": "theta_jc", "celsius": {"85": 85.001}, "source": "a case 0.001 C above the air"}
    plan = plan_of(tmp_path, {"U1": {**U1, "from": {**case, "heat_sink": {**SINK, "theta_sa": 30}}}})
    runs = {"ldo": [("85 C", 85.0, {"p_u1": 0.17295})]}
    judged = thermal.judge(plan, runs, FACTS_LIST, ECSS)
    worst = judged["parts"]["U1"]["worst"]
    assert worst["figure"] == "theta_jc" and "from" not in worst
    assert worst["beside"] == {
        "figure": "theta_jc",
        "equation": "4",
        "from": 85.001,
        "junction": pytest.approx(105.47828),
    }
    assert judged["not_judged"] == []
    line = thermal.lines({"thermal": judged})[0]
    assert "from case" not in line and "the worst junction by SPRA953D, section 2.2, equation 5" in line
