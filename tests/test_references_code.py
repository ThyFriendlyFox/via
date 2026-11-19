"""`workcenter references rules` on tool code: each document a tool or a test cites is in the index.

A file declares the documents it cites as `CITES = {"<index id>": "<where in it>"}`. The command finds
every document's name in the file (an entry's `names`, or a number of a family the index's `numbers`
lists). A name with a section, table, page, clause, equation, annex, figure or chapter after it is a
citation: the index must hold it and the file's CITES must name it. A name with none beside it is a
mention, printed as not judged. The fixtures of tests/boards/references/code/ each plant 1 fault; their
index holds 1 note and 1 paper made up for the tests.

The made-up numbers are written in 2 pieces in this file ("ACME-" "AN-99A") so that this file names no
document itself.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
CODE = ROOT / "tests" / "boards" / "references" / "code"
FAB = ROOT / "tests" / "boards" / "references" / "fab"
INDEX = ROOT / "rules" / "references" / "index.json"

CITES = {}


def rules(*paths: Path, index: Path = CODE / "index.json") -> tuple[int, list[str]]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "references", "rules", *map(str, paths), "--index", str(index)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    return proc.returncode, (proc.stdout + proc.stderr).splitlines()


def test_a_file_that_declares_each_document_it_cites_passes():
    """pass/tool.py cites ACME-AN-17B (equation 4) and Zed and Yew (equation (2)) and its CITES names
    both: 2 named, 2 in the index, 0 not."""
    code, lines = rules(CODE / "pass")
    assert code == 0, lines
    assert lines == ["references rules: 2 documents named in 1 files, 2 in the index, 0 not; 0 not judged"]


@pytest.mark.parametrize(
    ("fixture", "fault", "summary"),
    [
        (
            "fail-undeclared",
            "fail tests/boards/references/code/fail-undeclared/tool.py:5: " + "ACME-" + "AN-17B, equation 4: "
            'the file\'s CITES does not name acme-an-17b; add "acme-an-17b": "<where in it>" to it',
            # CITES names zed-yew-1999 (held); the note is cited and not declared: 2 named, 1 held.
            "2 documents named in 1 files, 1 in the index, 1 not",
        ),
        (
            "fail-unknown",
            "fail tests/boards/references/code/fail-unknown/tool.py:5: " + "ACME-" + "AN-99A, section 2: "
            "the index has no document by that name; fetch it and add its entry "
            "(rules/references/README.md, An entry), then name its id in the file's CITES",
            # CITES names acme-an-17b (held); the unknown note is 1 more: 2 named, 1 held.
            "2 documents named in 1 files, 1 in the index, 1 not",
        ),
        (
            "fail-cites",
            "fail tests/boards/references/code/fail-cites/tool.py:3: CITES names acme-an-18a, which the "
            "index lacks",
            "1 documents named in 1 files, 0 in the index, 1 not",
        ),
    ],
)
def test_a_citation_the_index_or_the_file_lacks_fails_on_1_line(fixture, fault, summary):
    code, lines = rules(CODE / fixture)
    assert code == 1
    assert lines == [fault, f"references rules: {summary}; 0 not judged"]


def test_a_name_with_no_place_beside_it_is_a_mention_and_not_judged():
    code, lines = rules(CODE / "mention")
    assert code == 0
    assert lines == [
        "not judged tests/boards/references/code/mention/tool.py:3: " + "ACME-" + "AN-99A has no section, "
        "table, page, clause or equation beside it: a mention, not a citation",
        "references rules: 0 documents named in 1 files, 0 in the index, 0 not; 1 not judged",
    ]


@pytest.mark.parametrize(
    ("text", "fault"),
    [
        (
            "CITES = dict(a='b')\n",
            'CITES: a dict of index ids to where in each, as {"ti-slva477c": "equation 1"}',
        ),
        ('CITES = {"acme-an-17b": ""}\n', 'CITES acme-an-17b: where in it is asked, as "equation 1"'),
        ('CITES = {"acme-an-17b": 4}\n', 'CITES acme-an-17b: where in it is asked, as "equation 1"'),
        ("def broken(:\n", "not read as Python (invalid syntax"),
        # A list as a key: ast.literal_eval raises TypeError (unhashable), not ValueError.
        (
            'CITES = {["acme-an-17b"]: "equation 1"}\n',
            'CITES: a dict of index ids to where in each, as {"ti-slva477c": "equation 1"}',
        ),
    ],
)
def test_a_cites_that_is_not_a_dict_of_places_is_refused(tmp_path, text, fault):
    tool = tmp_path / "tool.py"
    tool.write_text(text, encoding="utf-8")
    code, lines = rules(tool)
    assert code == 1
    assert fault in lines[0], lines


def test_a_tool_of_the_repository_that_drops_its_cites_fails(tmp_path):
    """tools/ratings.py cites TI's note on a buck's power stage (equations 1, 2, 4 and 11, section 2).
    The same text with its CITES renamed declares nothing, so the citation fails, on the first place the
    file names beside it: its comment's "section 2"."""
    text = (ROOT / "tools" / "ratings.py").read_text(encoding="utf-8")
    assert "\nCITES = {" in text
    dropped = tmp_path / "ratings.py"
    dropped.write_text(text.replace("\nCITES = {", "\nNOT_CITES = {"), encoding="utf-8")
    code, lines = rules(dropped, index=INDEX)
    assert code == 1
    said = "SLVA" + "477C, section 2: the file's CITES does not name ti-slva477c"
    assert [line for line in lines if said in line and line.startswith(f"fail {dropped}:")], lines


def test_every_citation_in_the_tools_and_tests_is_in_the_index():
    """`make verify` runs this through the default globs (the next test names them). With no CITES in
    tools/ratings.py, tools/thermal.py or tests/test_copper.py this failed on each note and book those
    files cite."""
    code, lines = rules(index=INDEX)
    assert code == 0, "\n".join(lines)
    assert not [line for line in lines if line.startswith("fail")]


def test_the_index_globs_read_the_tools_and_the_tests():
    """The lead's tools in ee-agent-kit/lead/ landed after the check: before, no glob read them."""
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    globs = {"tools/*.py", "tools/workcenter", "tests/*.py", "tests/boards/*.py", "ee-agent-kit/lead/*.py"}
    assert globs <= set(data["code"])


def test_a_fab_rule_file_that_names_a_page_the_index_lacks_fails():
    """fab/fail-url.kicad_dru names 2 pages: 1 the fixture index holds, 1 it lacks."""
    code, lines = rules(FAB / "fail-url.kicad_dru", index=FAB / "index.json")
    assert code == 1
    assert lines == [
        "fail tests/boards/references/fab/fail-url.kicad_dru:4: https://fab.example/specs-old/ is not the "
        "URL "
        "of an entry of the index; add the page as a web page entry with the values the rules take from it",
        "references rules: 2 documents named in 1 files, 1 in the index, 1 not; 0 not judged",
    ]


def test_a_fab_rule_file_whose_pages_are_in_the_index_passes():
    code, lines = rules(FAB / "pass.kicad_dru", index=FAB / "index.json")
    assert code == 0, lines
    assert lines == ["references rules: 1 documents named in 1 files, 1 in the index, 0 not; 0 not judged"]


# ------------------------------------------------------------------ the second review's findings

UNKNOWN = (
    "the index has no document by that name; fetch it and add its entry (rules/references/README.md, "
    "An entry)"
)
IN_CITES = ", then name its id in the file's CITES"


def undeclared(doc_id: str) -> str:
    return f'the file\'s CITES does not name {doc_id}; add "{doc_id}": "<where in it>" to it'


def test_a_capitalised_or_abbreviated_place_makes_a_citation():
    """code/places/tool.py: 6 citations on lines 8 to 13, CITES empty. 2 name documents the index lacks
    and 4 name entries CITES does not declare: 6 fail lines; 0 + 6 = 6 named, 0 in the index. Before
    the fix the 6 places (Table, Section, Equation, Fig., p., §) were not read as places: 6 mentions."""
    path = "tests/boards/references/code/places/tool.py"
    code, lines = rules(CODE / "places", index=INDEX)
    assert code == 1
    assert lines == [
        f"fail {path}:8: " + "IPC-" + f"2221B, Table 6-1: {UNKNOWN}{IN_CITES}",
        f"fail {path}:9: " + "JESD" + f"51-7, Section 4: {UNKNOWN}{IN_CITES}",
        f"fail {path}:10: " + "SLVA" + f"477C, Equation 11: {undeclared('ti-slva477c')}",
        f"fail {path}:11: " + "SPRA" + f"953D, Fig. 3: {undeclared('ti-spra953d')}",
        f"fail {path}:12: " + "SNVA" + f"419C, p. 12: {undeclared('ti-snva419c')}",
        f"fail {path}:13: " + "SBVS" + f"320D, §7.3: {undeclared('ti-sbvs320')}",
        "references rules: 6 documents named in 1 files, 0 in the index, 6 not; 0 not judged",
    ]


def test_documents_of_the_families_first_missed_are_found_and_fail():
    """code/families/tool.py: 9 citations on lines 8 to 16 (TI's SLAA, SLVAE and SPRAC numbers, J-STD,
    IPC-TM, IEC with a hyphen, MIL-STD, Analog Devices' AN and IEEE), none in the index: 9 fail lines,
    9 named, 0 in the index. Before the fix no family found them: 0 named, exit 0. The SLAA number is
    390B, which the index lacks; the number it had first is the MCU block's note, which joined the index
    on 2026-11-18."""
    path = "tests/boards/references/code/families/tool.py"
    code, lines = rules(CODE / "families", index=INDEX)
    cited = [
        ("SLAA" + "390B", "section 2"),
        ("SLVA" + "E57", "equation 3"),
        ("SPRA" + "CN0", "table 2"),
        ("J-STD-" + "020E", "table 4-1"),
        ("IPC-" + "TM-650", "section 2.4.8"),
        ("IEC-" + "61000-4-5", "clause 7"),
        ("MIL-" + "STD-883", "section 3015"),
        ("Analog Devices AN-" + "1368", "page 4"),
        ("IEEE " + "1149.1", "clause 4"),
    ]
    assert code == 1
    assert lines == [
        *(
            f"fail {path}:{8 + n}: {name}, {place}: {UNKNOWN}{IN_CITES}"
            for n, (name, place) in enumerate(cited)
        ),
        "references rules: 9 documents named in 1 files, 0 in the index, 9 not; 0 not judged",
    ]


def test_another_revision_or_edition_of_a_declared_document_fails():
    """code/revision/tool.py declares 4 entries (4 named, 4 in the index) and cites, on lines 14 to 17,
    Rev.1 of the ECSS standard the index holds as Rev.2, the 2nd edition of the microwave book (the
    index: 4th), version 0.6 of the XDG specification (the index: 0.8) and the 8th edition of the BIPM's
    brochure (the index: 9th). Each is 1 more document named and not held: 4 + 4 = 8 named, 4 in the
    index, 4 not. Before the fix the 4 passed as the entries CITES declares."""
    path = "tests/boards/references/code/revision/tool.py"
    code, lines = rules(CODE / "revision", index=INDEX)
    held = [
        (14, "ECSS-Q-ST-" + "30-11C", "table 6-1", "Rev.1", "ecss-q-st-30-11c-rev2"),
        (15, "Poz" + "ar", "equation 3.195", "2nd edition", "pozar-microwave-engineering-4"),
        (16, "XDG Base Directory " + "Specification", "section 2", "0.6", "freedesktop-basedir-0.8"),
        (17, "SI " + "Brochure", "table 1", "8th edition", "bipm-si-brochure-9"),
    ]
    assert code == 1
    assert [line.split(" the index holds ")[0] for line in lines[:-1]] == [
        f"fail {path}:{n}: {name}, {place}: {marker} is named beside it;"
        for n, name, place, marker, _ in held
    ]
    for line, (_, _, _, marker, doc_id) in zip(lines, held, strict=False):
        assert f" the index holds {doc_id} (" in line and line.endswith(
            f"): cite that copy, or fetch {marker} and add its entry"
        )
    assert lines[-1] == "references rules: 8 documents named in 1 files, 4 in the index, 4 not; 0 not judged"


def test_a_number_written_another_way_names_the_same_entry():
    """code/alias/tool.py declares ietf-rfc6585 and cites it as its number with no space (line 10): held.
    It cites TI's note with a lower-case revision letter (line 11) and does not declare it: 1 fail. 1 +
    1 = 2 named, 1 in the index. Before the fix the RFC failed as a name the index lacks, and the note was
    not found at all."""
    code, lines = rules(CODE / "alias", index=INDEX)
    assert code == 1
    assert lines == [
        "fail tests/boards/references/code/alias/tool.py:11: "
        + "SLVA"
        + f"477c, equation 1: {undeclared('ti-slva477c')}",
        "references rules: 2 documents named in 1 files, 1 in the index, 1 not; 0 not judged",
    ]


def test_a_fab_rule_file_that_cites_a_standard_by_name_fails():
    """fab/names.kicad_dru cites a standard the index lacks by number and table, on line 3, with no URL:
    1 named, 0 in the index. Before the fix only URLs were read: 0 named, exit 0."""
    code, lines = rules(FAB / "names.kicad_dru", index=INDEX)
    assert code == 1
    assert lines == [
        "fail tests/boards/references/fab/names.kicad_dru:3: " + "IPC-" + f"2221B, table 6-1: {UNKNOWN}",
        "references rules: 1 documents named in 1 files, 0 in the index, 1 not; 0 not judged",
    ]


def test_a_standard_a_fab_rule_file_of_the_repository_names_is_not_skipped_in_silence():
    """rules/sierra-circuits-web.kicad_dru names IPC's class on line 2 with no place beside it: a mention,
    not judged. Its 2 URLs are entries: 2 named, 2 in the index."""
    code, lines = rules(ROOT / "rules" / "sierra-circuits-web.kicad_dru", index=INDEX)
    assert code == 0, lines
    assert lines == [
        "not judged rules/sierra-circuits-web.kicad_dru:2: " + "IPC-" + "6012 has no section, table, page, "
        "clause or equation beside it: a mention, not a citation",
        "references rules: 2 documents named in 1 files, 2 in the index, 0 not; 1 not judged",
    ]


def test_a_url_with_parentheses_in_a_fab_rule_file_is_read_whole():
    """fab/paren.kicad_dru names the URL of ecss-q-st-30-11c-rev2, which holds '(' and ')': 1 named, 1 in
    the index. Before the fix the URL was cut at '(' and failed."""
    code, lines = rules(FAB / "paren.kicad_dru", index=INDEX)
    assert code == 0, lines
    assert lines == ["references rules: 1 documents named in 1 files, 1 in the index, 0 not; 0 not judged"]


def test_a_json_rule_that_names_a_document_in_a_text_fails():
    """json-text/rule.json: rules[0].source is a text that names a standard by number and table, and
    rules[1].note cites a revision of a TI note the index lacks (it holds revision C). 2 named, 0 in the
    index. Before the fix a source that is a text and a note were not read: 0 named, exit 0."""
    path = "tests/boards/references/json-text/rule.json"
    code, lines = rules(ROOT / path, index=INDEX)
    assert code == 1
    assert lines == [
        f"fail {path} rules[0].source: " + "IPC-" + "2221B, table 6-1 names a document by name alone: write "
        "it as an object with its URL and SHA256, or `no datasheet: <why>`",
        f"fail {path} rules[1].note: " + "SLVA" + f"477B, equation 1: {UNKNOWN}",
        "references rules: 2 documents named in 1 files, 0 in the index, 2 not; 0 not judged",
    ]


def test_the_interface_rules_and_their_tests_hold_their_documents():
    """The high-speed pieces landed beside this check. rules/interfaces/constants.json named NIST's 2
    CODATA pages in a `source` that was a text, and tests/test_highspeed.py cited TI's USB layout note by
    table and page with no CITES: 3 fails. The 2 pages are web page entries now, each source an object
    with its page's URL, and the test's CITES names the note and the 3 USB specifications it speaks of:
    2 sources and 4 ids, 6 named."""
    paths = (ROOT / "rules" / "interfaces" / "constants.json", ROOT / "tests" / "test_highspeed.py")
    code, lines = rules(*paths, index=INDEX)
    assert code == 0, lines
    assert lines == ["references rules: 6 documents named in 2 files, 6 in the index, 0 not; 0 not judged"]


def test_the_cross_section_solver_and_its_test_declare_the_works_they_are_held_to():
    """tests/test_xsection.py holds tools/xsection.py to 2 publications, a page of DLMF and NIST's page of
    the impedance of vacuum; the tool names the 2 works whose equations its test takes. Each is an entry,
    and each file's CITES names it: 4 ids and 2 ids, 6 named. The 2 publications are held copies that are
    no standard, note or datasheet: the index holds them as `report`. Before, the index named none of
    them: 0 named, and the tool's name of the microstrip paper was printed as not judged."""
    paths = (ROOT / "tests" / "test_xsection.py", ROOT / "tools" / "xsection.py")
    code, lines = rules(*paths, index=INDEX)
    assert code == 0, lines
    assert lines == ["references rules: 6 documents named in 2 files, 6 in the index, 0 not; 0 not judged"]
    kinds = {d["id"]: d["kind"] for d in json.loads(INDEX.read_text(encoding="utf-8"))["documents"]}
    assert kinds["qucs-technical-papers"] == kinds["matthaei-ad0402852"] == "report"


def test_the_citation_of_the_qucs_papers_without_cites_fails(tmp_path):
    """The names of the 2 publications find them: tests/test_xsection.py with its CITES renamed fails on
    the first, at the place its docstring gives beside it."""
    text = (ROOT / "tests" / "test_xsection.py").read_text(encoding="utf-8")
    assert "\nCITES = {" in text
    dropped = tmp_path / "test_xsection.py"
    dropped.write_text(text.replace("\nCITES = {", "\nNOT_CITES = {"), encoding="utf-8")
    code, lines = rules(dropped, index=INDEX)
    assert code == 1
    said = "Qucs " + "Technical Papers, section 11.1: the file's CITES does not name qucs-technical-papers"
    assert [line for line in lines if said in line], lines
    said = "AD" + "0402852, section 5.05: the file's CITES does not name matthaei-ad0402852"
    assert [line for line in lines if said in line], lines


def test_the_frequency_plan_and_its_test_hold_the_i2c_specification():
    """tools/freqplan.py and tests/test_freqplan.py give NXP's I2C-bus specification as the source of the
    I2C clock in their example plan, by table. No family read NXP's numbers and the index had no entry,
    so the check passed both files in silence: 0 named. Rev. 7.0 gives the SCL clock in table 11, page
    44; the files said table 10, the I/O stages. Each file's CITES names the entry now: 2 named."""
    paths = (ROOT / "tools" / "freqplan.py", ROOT / "tests" / "test_freqplan.py")
    code, lines = rules(*paths, index=INDEX)
    assert code == 0, lines
    assert lines == ["references rules: 2 documents named in 2 files, 2 in the index, 0 not; 0 not judged"]


def test_the_frequency_plan_without_cites_fails(tmp_path):
    """The entry's name finds the citation: tools/freqplan.py with its CITES renamed fails on it."""
    text = (ROOT / "tools" / "freqplan.py").read_text(encoding="utf-8")
    assert "\nCITES = {" in text
    dropped = tmp_path / "freqplan.py"
    dropped.write_text(text.replace("\nCITES = {", "\nNOT_CITES = {"), encoding="utf-8")
    code, lines = rules(dropped, index=INDEX)
    assert code == 1
    said = "UM" + "10204, Table 11: the file's CITES does not name nxp-um10204"
    assert [line for line in lines if said in line], lines


def test_an_nxp_number_the_index_lacks_is_found_by_its_family(tmp_path):
    """A user manual or an application note of NXP is a family of `numbers`: a citation of 1 the index
    lacks fails. Before the family it was not named: 0 named, exit 0."""
    tool = tmp_path / "tool.py"
    tool.write_text('"""The bus waits for its clock (' + "AN" + '10441, section 3)."""\n', encoding="utf-8")
    code, lines = rules(tool, index=INDEX)
    assert code == 1
    assert lines == [
        f"fail {tool}:1: " + "AN" + f"10441, section 3: {UNKNOWN}{IN_CITES}",
        "references rules: 1 documents named in 1 files, 0 in the index, 1 not; 0 not judged",
    ]


def test_the_linear_regulator_block_its_builder_and_its_tests_declare_their_documents():
    """tools/blocks_ldo.py, tests/test_blocks_ldo.py and tests/boards/block_ldo.py cite the block's note
    (ti-slva079) and the TLV755P datasheet (ti-sbvs320) by equation, section and page, and the test the
    thermal metrics note (ti-spra953d), as tools/thermal.py does. The block was built before the check
    read code: the note's entry had no `names`, so the note was not found by name, and no file had a
    CITES: 7 fails. Each file's CITES names its documents now: 1 + 3 + 1 = 5 named."""
    paths = (
        ROOT / "tools" / "blocks_ldo.py",
        ROOT / "tests" / "test_blocks_ldo.py",
        ROOT / "tests" / "boards" / "block_ldo.py",
    )
    code, lines = rules(*paths, index=INDEX)
    assert code == 0, lines
    assert lines == ["references rules: 5 documents named in 3 files, 5 in the index, 0 not; 0 not judged"]


def test_the_board_rules_tool_declares_the_pack_whose_tables_it_reads():
    """tools/boardrules.py reads tables 7-1 and 7-3 of the board pack's standard by number alone, with no
    name beside them, so no check can find them: its CITES names the standard of every pack in
    rules/board. Before, it had none: 0 named. The layout packs of roadmap item 11 (`"kind": "layout"`)
    are read by tools/layoutrules.py, and the creepage packs of item 11 (`"kind": "creepage"`) by
    tools/creepage.py; the CITES of each names each of its packs' documents by its index id."""
    code, lines = rules(ROOT / "tools" / "boardrules.py", index=INDEX)
    assert code == 0, lines
    assert lines == ["references rules: 1 documents named in 1 files, 1 in the index, 0 not; 0 not judged"]
    sys.path.insert(0, str(ROOT / "tools"))
    import boardrules
    import creepage
    import layoutrules

    data = [json.loads(p.read_text(encoding="utf-8")) for p in (ROOT / "rules" / "board").glob("*.json")]
    packs = {d["pack"] for d in data if d.get("kind") not in ("layout", "creepage")}
    assert packs and packs <= set(boardrules.CITES)
    entries = json.loads(INDEX.read_text(encoding="utf-8"))["documents"]
    by_number = {e["number"]: e["id"] for e in entries if "number" in e}
    layout = {by_number[d["document"]["number"]] for d in data if d.get("kind") == "layout"}
    assert layout == {"ti-slva680a", "ti-szza009"}
    assert layout <= set(layoutrules.CITES)
    spacing = {by_number[d["document"]["number"]] for d in data if d.get("kind") == "creepage"}
    assert spacing == {"mil-hdbk-454c", "ti-slup419"}
    assert spacing <= set(creepage.CITES)
