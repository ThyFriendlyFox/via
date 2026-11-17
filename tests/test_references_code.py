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
    data = json.loads(INDEX.read_text(encoding="utf-8"))
    assert {"tools/*.py", "tools/workcenter", "tests/*.py", "tests/boards/*.py"} <= set(data["code"])


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
