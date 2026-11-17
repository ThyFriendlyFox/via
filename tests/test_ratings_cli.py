"""`workcenter ratings` on schematics: the fixture boards of tests/boards/ratings_node.py.

The board with no fault holds every stress. Each of the 5 others fails on the 1 rule its planted fault
breaks, and on no other. The numbers in the lines are worked out here and in tests/boards/README.md:

    the output    0.588 x (1 + 448470 / 101000) = 3.199 V to 0.612 x (1 + 457530 / 99000) = 3.440 V
    pin           the 5 V rail's 5.25 V on an input that takes 4.6 V
    load          1.9 A on a regulator that gives 2 A is 0.95, and the pack allows a linear part 0.70
    inductor      (5.25 - 3.199) x 3.199 / (5.25 x 0.9) / (1.35e6 x 1.76e-6) = 0.584 A of ripple at the
                  least output; 1.1 A of load and half of it is 1.392 A, over the 1.26 A it saturates at
    bias          10 uF less 20 % keeps 0.50 - 0.12 x 0.440 = 0.447 of its value at 3.440 V: 3.58 uF, and
                  the 2 capacitors with no curve give 0.11 uF each at the most: 3.80 uF, under 5 uF
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"

pytestmark = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")

AUP = "SN74AUP1G17 datasheet, SCES579J, June 2004, revised September 2017"
BUCK = "TLV62569 datasheet, SLVSDG1C, December 2016, revised October 2017"
FAULTS = {
    "fail-ratings-pin": f"fail U2 pin 2 (A) on SIG: 5.25 V can stand on it, its limit is 4.6 V [{AUP}, p 4]",
    "fail-ratings-load": (
        "fail +3V3: U1 pin 5 (FB) gives 2 A, its loads take 1.9 A: 0.95, the limit is 0.70 "
        "[EEE-INST-002 (NASA/TP-2003-212242), section M4, table 4, page 10 of 10, "
        "the column Linear/Mixed Signal]"
    ),
    "fail-ratings-decoupling": (
        f"fail U1 pin VIN (+5V) needs a capacitor to GND, and none stands there [{BUCK}, p 10]"
    ),
    "fail-ratings-inductor": (
        "fail L1 2.2u SRN2010TA: its peak current is 1.39 A: 1.1 A of load and half of 584 mA of ripple "
        "(5.25 V in, 3.2 V out, 1.76 uH, 1.35 MHz); it saturates at 1.26 A [Bourns SRN2010TA series "
        "datasheet, REV. 06/25: the part's own rating; TI SLVA477C, equations 1, 2 and 4]"
    ),
    "fail-ratings-bias": (
        "fail U1 pin FB (+3V3) needs 5 uF effective to GND: C2 gives 3.58 uF, "
        "C4 gives 110 nF at most (no data on the value it keeps), "
        f"C5 gives 110 nF at most (no data on the value it keeps) [{BUCK}, p 9]"
    ),
}
FIXTURES = ("pass-ratings-node", *FAULTS)


def say(*args: object) -> tuple[int, str]:
    """The command's exit code and what it prints."""
    proc = subprocess.run(
        [sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True, check=False
    )
    return proc.returncode, proc.stdout + proc.stderr


def copy(name: str, to: Path) -> Path:
    """A fixture in a folder of its own, with no library above it."""
    target = to / name
    shutil.copytree(
        BOARDS / name, target, ignore=shutil.ignore_patterns("build", "*.kicad_prl", "__pycache__")
    )
    return target


def test_the_board_with_no_fault_holds_every_stress_and_a_strict_run_passes(tmp_path):
    code, text = say("ratings", BOARDS / "pass-ratings-node", "--out", tmp_path, "--strict")
    assert code == 0, text
    assert (
        "PASS   ratings    0 fail, 0 accepted, " in text
        and " hold, 0 not judged; pack nasa-eee-inst-002" in text
    )
    assert text.rstrip().endswith(f"RATINGS HELD: node  report {tmp_path / 'ratings' / 'report.md'}")


@pytest.mark.parametrize("name", FAULTS)
def test_each_planted_fault_fails_on_its_own_rule_and_on_no_other(name, tmp_path):
    code, text = say("ratings", BOARDS / name, "--out", tmp_path)
    assert code == 1, text
    assert "FAIL   ratings    1 fail, 0 accepted, " in text and " hold, 0 not judged" in text
    assert f"       - {FAULTS[name]}\n" in text
    assert f"RATINGS NOT HELD (1 fail): node  report {tmp_path / 'ratings' / 'report.md'}" in text


def test_a_run_writes_the_netlist_the_page_and_the_record(tmp_path):
    say("ratings", BOARDS / "fail-ratings-pin", "--out", tmp_path)
    folder = tmp_path / "ratings"
    assert sorted(p.name for p in folder.iterdir()) == ["netlist.xml", "report.json", "report.md"]
    assert (folder / "netlist.xml").read_text(encoding="utf-8").startswith("<?xml")
    page = (folder / "report.md").read_text(encoding="utf-8")
    assert page.startswith("# Ratings\n\nratings: 1 fail, 0 accepted, ")
    assert "\nRATINGS NOT HELD (1 fail)\n" in page and "\n## Fail: 1\n" in page and "\n## Hold: " in page
    assert (
        f"- {FAULTS['fail-ratings-pin'].removeprefix('fail ')}\n"
        "  - to accept it, the owner names part `U2.2` and rule `pin.voltage`\n"
    ) in page
    assert "- U1 holds +3V3 at 3.2 to 3.44 V: its pin FB at 0.588 to 0.612 V, R1 over R2" in page
    record = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    assert (record["gate"], record["status"]) == ("ratings", "fail")
    assert record["details"]["verdict"] == "RATINGS NOT HELD (1 fail)"
    failed = [f for f in record["details"]["findings"] if f["status"] == "fail"]
    assert [(f["part"], f["rule"]) for f in failed] == [("U2.2", "pin.voltage")]


def test_json_output_is_the_record_and_no_other_line(tmp_path):
    proc = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--json",
            "ratings",
            str(BOARDS / "fail-ratings-load"),
            "--out",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    (record,) = json.loads(proc.stdout)
    assert proc.returncode == 1 and record["status"] == "fail"
    assert record["details"]["failures"] == [FAULTS["fail-ratings-load"]]


def test_a_project_with_no_ratings_file_is_skipped_and_told_how_to_start(tmp_path):
    code, text = say("ratings", BOARDS / "pass-rc-divider", "--out", tmp_path)
    assert code == 2, text
    assert "SKIP   ratings    no ratings.json beside the schematic: `workcenter ratings " in text
    assert "--init` writes one" in text
    assert not (tmp_path / "ratings").exists()


def test_init_writes_the_file_once_and_a_run_with_no_facts_judges_nothing(tmp_path):
    project = copy("pass-rc-divider", tmp_path)
    code, text = say("ratings", project, "--init")
    assert (
        code == 0 and f"wrote {project / 'ratings.json'}: pack nasa-eee-inst-002, no net stated yet" in text
    )
    assert json.loads((project / "ratings.json").read_text(encoding="utf-8")) == {
        "pack": "nasa-eee-inst-002",
        "nets": {},
    }
    (project / "ratings.json").write_text('{"pack": "nasa-eee-inst-002", "nets": {}}\n', encoding="utf-8")
    code, text = say("ratings", project, "--init")
    assert code == 0 and "is there already: nothing written" in text
    assert (project / "ratings.json").read_text(
        encoding="utf-8"
    ) == '{"pack": "nasa-eee-inst-002", "nets": {}}\n'
    code, text = say("ratings", project)
    assert code == 1, text
    assert "not judged R1 10k: no facts for a part with no part number (Device:R)" in text
    assert "NOTHING JUDGED (4 not judged): rc_divider  report " in text


def test_the_facts_are_found_in_a_library_above_the_project(tmp_path):
    """The fixture alone has no facts and judges nothing; with tests/boards/library beside it, it holds."""
    project = copy("pass-ratings-node", tmp_path / "boards")
    code, text = say("ratings", project)
    assert code == 1 and "NOTHING JUDGED (14 not judged)" in text
    shutil.copytree(BOARDS / "library", tmp_path / "boards" / "library")
    code, text = say("ratings", project, "--strict")
    assert code == 0 and "RATINGS HELD: node" in text, text


def test_a_capacitor_marked_dnp_meets_no_need(tmp_path):
    """The board with no fault, with its input capacitor C1 marked do-not-populate in the schematic:
    the capacitor is not on the board, so the run fails as the fixture with C1 left out does."""
    project = copy("pass-ratings-node", tmp_path / "boards")
    shutil.copytree(BOARDS / "library", tmp_path / "boards" / "library")
    sheet = project / "node.kicad_sch"
    text = sheet.read_text(encoding="utf-8")
    start = text.rindex("(symbol", 0, text.index('"Reference" "C1"'))
    marked = text[:start] + text[start:].replace("(dnp no)", "(dnp yes)", 1)
    assert marked != text
    sheet.write_text(marked, encoding="utf-8")
    code, said = say("ratings", project)
    assert code == 1 and f"- {FAULTS['fail-ratings-decoupling']}" in said, said
    page = (project / "build" / "ratings" / "report.md").read_text(encoding="utf-8")
    assert "- not fitted (DNP), and left out of every line: C1" in page


def test_a_file_the_command_does_not_take_fails_the_run_with_its_place(tmp_path):
    project = copy("pass-ratings-node", tmp_path)
    stated = json.loads((project / "ratings.json").read_text(encoding="utf-8"))
    (project / "ratings.json").write_text(json.dumps({**stated, "speed": 1}), encoding="utf-8")
    code, text = say("ratings", project)
    assert code == 1, text
    assert "- ratings.json: `speed` is no key here; the keys are pack, nets, ambient, parts, accepted" in text
    # the record holds the refusal too: `workcenter next` reads it there
    record = json.loads((project / "build" / "ratings" / "report.json").read_text(encoding="utf-8"))
    assert record["status"] == "fail"
    assert record["details"]["failures"][0].startswith("ratings.json: `speed` is no key here")
    (project / "ratings.json").write_text(json.dumps({**stated, "pack": "mil-hdbk"}), encoding="utf-8")
    code, text = say("ratings", project)
    assert code == 1, text
    assert (
        "- ratings.json: pack: `mil-hdbk` is no pack; the workcenter holds "
        "ecss-q-st-30-11c-rev2, nasa-eee-inst-002"
    ) in text


def test_facts_prints_an_entry_to_fill_with_the_part_s_number_and_pins(tmp_path):
    code, text = say("ratings", BOARDS / "pass-ratings-node", "--out", tmp_path, "--facts", "U1")
    assert code == 0, text
    entry = json.loads(text)
    assert entry["kind"] == "" and entry["mpn"] == "TLV62569DBVR"
    assert entry["source"]["second_reader"] == "no"
    assert {"numbers": ["5"], "name": "FB", "role": "", "page": 0} in entry["pins"]
    assert sorted(n for pin in entry["pins"] for n in pin["numbers"]) == ["1", "2", "3", "4", "5"]
    code, text = say("ratings", BOARDS / "pass-ratings-node", "--out", tmp_path, "--facts", "U9")
    assert code != 0 and "U9 is no part of the schematic" in text


@pytest.mark.parametrize("name", FIXTURES)
def test_each_fixture_s_schematic_is_what_its_design_file_writes(name):
    code, text = say("design", BOARDS / name / "design.py", "--check")
    assert code == 0, text
