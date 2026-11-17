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
import os
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


def say(*args: object, env: dict[str, str] | None = None) -> tuple[int, str]:
    """The command's exit code and what it prints. `env` adds variables to the environment it runs in."""
    proc = subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **env} if env else None,
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


# ---------------------------------------------------------------- files and flags the command does not take
#
# Each case is the board that holds every stress with 1 file changed, as a project would hold it: its
# facts in a library above it. The command answers with the file, the place and the fault, exits 1 and
# leaves its record. No case ends in a traceback.

HEAD = "Value,Footprint,Qty,Manufacturer,MPN,Supplier,SKU,Pack,Breaks\n"
REFUSED = "FAIL   ratings    a file is not as the command reads it"


def node(tmp_path: Path) -> Path:
    """The board that holds every stress, in a folder of its own with the facts' library above it."""
    project = copy("pass-ratings-node", tmp_path / "boards")
    shutil.copytree(BOARDS / "library", tmp_path / "boards" / "library")
    return project


def rewrite(path: Path, change) -> None:
    """A JSON file with 1 change made to what it holds."""
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def put(file: str, *keys: object, to: object):
    """A change to 1 file of the project or of its library: the value at a path of keys is set."""

    def change(project: Path) -> None:
        def at(data: object) -> None:
            for key in keys[:-1]:
                data = data[key]
            data[keys[-1]] = to

        rewrite(project / file, at)

    return change


def own_pack(change):
    """A change that gives the project a pack of its own, house.json: the NASA pack with 1 change."""

    def write(project: Path) -> None:
        data = json.loads((ROOT / "rules" / "ratings" / "nasa-eee-inst-002.json").read_text(encoding="utf-8"))
        change(data)
        (project / "house.json").write_text(json.dumps(data), encoding="utf-8")
        rewrite(project / "ratings.json", lambda stated: stated.update(pack="house.json"))

    return write


def accepts(why: str, day: str) -> dict:
    """An entry of `accepted` for the regulator's load, by a decision of a day of 2026."""
    by = f"the owner's decision of 2026-{day}"
    return {"part": "U1", "rule": "output.current.linear", "why": why, "by": by}


TLV = "../library/facts/ti-tlv62569.json"
SET_BY_A_LIST = {
    "numbers": ["3"],
    "name": "SW",
    "role": "regulated",
    "abs": [-0.3, 6],
    "set_by": ["FB"],
    "page": 3,
}
SECOND_EN = {"numbers": ["1"], "name": "EN2", "role": "input", "abs": [-0.3, 9.0], "page": 3}  # pin 1 is EN
RISES = {"temperature": "ambient", "celsius": 70, "falls_to": 1.0, "at": 112.5}  # the rule's max is 0.50
WRONG = {
    "nets is a number": (
        put("ratings.json", "nets", to=5),
        "ratings.json: nets: an object is asked, with 1 key for each net it states",
    ),
    "nets is null": (
        put("ratings.json", "nets", to=None),
        "ratings.json: nets: an object is asked, with 1 key for each net it states",
    ),
    "parts is a number": (
        put("ratings.json", "parts", to=7),
        "ratings.json: parts: an object is asked, with 1 key for each part or pin it states",
    ),
    "a kind is a list": (
        put(TLV, "kind", to=["ic"]),
        "ti-tlv62569.json: kind: one of resistor, capacitor.ceramic, ",
    ),
    "a role is a list": (
        put(TLV, "pins", 0, "role", to=["input"]),
        "ti-tlv62569.json: pin 1: role: one of supply, ground, input, ",
    ),
    "a pin's name is a list": (
        put(TLV, "pins", 0, "name", to=["EN"]),
        "ti-tlv62569.json: pin 1: name: text is asked, and there is none",
    ),
    "set_by is a list": (
        put(TLV, "pins", 2, to=SET_BY_A_LIST),
        "ti-tlv62569.json: pin SW: set_by: text is asked, and there is none",
    ),
    "a capacitor rated 0 V": (
        put("../library/facts/made-up.json", "parts", 0, "volts", to=0),
        "made-up.json: part 1: volts: 0 is not above 0",
    ),
    "a resistor rated 0 W": (
        put("../library/facts/passives.json", "parts", 0, "watts", to=0),
        "passives.json: part 1: watts: 0 is not above 0",
    ),
    "a regulator that gives 0 A": (
        put(TLV, "pins", 4, "amps", to=0),
        "ti-tlv62569.json: pin FB: amps: 0 is not above 0",
    ),
    "a pack's rule id is a list": (
        own_pack(lambda pack: pack["rules"][0].update(id=["x"])),
        "house.json: rule 1: id: text is asked, and there is none",
    ),
    "a parts row of 3 fields": (
        lambda project: (project / "parts.csv").write_text(
            HEAD + "TLV62569,Package_TO_SOT_SMD:SOT-23-5,1\n", encoding="utf-8"
        ),
        "parts.csv:2: 3 fields, and the header names 9",
    ),
    "a parts file that is no UTF-8": (
        lambda project: (project / "parts.csv").write_bytes(
            HEAD.encode() + b"10k\xff,Resistor_SMD:R_0603_1608Metric,1,V,X,,,,\n"
        ),
        "parts.csv: not UTF-8: ",
    ),
    # files that were taken without a word, each with a judgement on what it did not say
    "a pin number in 2 entries": (
        lambda project: rewrite(project / TLV, lambda facts: facts["pins"].append(SECOND_EN)),
        "ti-tlv62569.json: pin EN2: numbers: `1` stands in pin EN too",
    ),
    "limits the wrong way round": (
        put("../library/facts/ti-sn74aup1g17.json", "pins", 1, "abs", to=[4.6, -0.5]),
        "ti-sn74aup1g17.json: pin A: abs: the span's first number, 4.6, is above its second, -0.5",
    ),
    "a second reader that is a word": (
        put("../library/facts/made-up.json", "parts", 0, "source", "second_reader", to="No"),
        "made-up.json: part 1: source: second_reader: write `no`, or the date as YYYY-MM-DD",
    ),
    "a net stated 2 times": (
        put("ratings.json", "nets", "/GND", to={"volts": [0, 5], "source": "x"}),
        "ratings.json: nets: /GND: this net stands 2 times, as GND and as /GND",
    ),
    "a pack whose share rises with temperature": (
        own_pack(lambda pack: pack["rules"][3].update(above=RISES)),
        "house.json: rule 4: above: `falls_to` is above `max`",
    ),
    "a pack whose document is a word": (
        own_pack(lambda pack: pack["document"].update(url="x", sha256="x", read="x", second_reader="x")),
        "house.json: document: url: a whole URL is asked, as https://example.com/file.pdf",
    ),
    # a number for a part the command reads none for: U2 is a buffer, J2 a header, U1.3 the switched pin
    "a current through an IC": (
        put("ratings.json", "parts", "U2", to={"amps": 9, "source": "x"}),
        "ratings.json: parts: U2: amps: U2 is of kind ic: the command reads no current through one",
    ),
    "a connector's load with no pin": (
        put("ratings.json", "parts", "J2", to={"amps": 9, "source": "x"}),
        "ratings.json: parts: J2: amps: J2 is a connector: its load is stated for 1 pin, as J2.1",
    ),
    "a load behind a switched pin": (
        put("ratings.json", "parts", "U1.3", to={"amps": 9, "source": "x"}),
        "ratings.json: parts: U1.3: amps: pin 3 of U1 is of role switched: "
        "the command reads no load behind one",
    ),
    "a voltage across an inductor": (
        put("ratings.json", "parts", "L1", to={"volts": 99, "source": "x"}),
        "ratings.json: parts: L1: volts: L1 is of kind inductor: the command reads no voltage across one",
    ),
    "1 failure accepted 2 times": (
        put(
            "ratings.json",
            "accepted",
            to=[accepts("first reason", "11-17"), accepts("second reason", "11-18")],
        ),
        "ratings.json: accepted: entry 2: the part U1 and the rule output.current.linear "
        "stand in entry 1 too",
    ),
    "a decision on a day the calendar lacks": (
        put("ratings.json", "accepted", to=[accepts("a reason", "99-99")]),
        "ratings.json: accepted: entry 1: by: `2026-99-99` is no date: "
        "write `the owner's decision of YYYY-MM-DD`",
    ),
}


@pytest.mark.parametrize("case", WRONG)
def test_a_wrong_file_is_refused_with_its_place_and_leaves_its_record(case, tmp_path):
    change, line = WRONG[case]
    project = node(tmp_path)
    change(project)
    code, text = say("ratings", project)
    assert code == 1 and "Traceback" not in text, text
    assert text.startswith(REFUSED), text
    assert f"\n       - {line}" in text, text
    record = json.loads((project / "build" / "ratings" / "report.json").read_text(encoding="utf-8"))
    assert record["status"] == "fail" and record["details"]["failures"][0].startswith(line)


def test_a_pack_of_the_project_s_own_is_named_by_its_file_and_as_the_project_s_own(tmp_path):
    """house.json is the NASA pack cut down to its 2 rules of a rail's load, with NASA's name left
    inside. It holds what NASA's pack holds on this board, and it would hold a capacitor NASA's fails.
    The first line, the record and the page say which file judged."""
    project = node(tmp_path)
    own_pack(lambda pack: pack.update(rules=[r for r in pack["rules"] if r["stress"] == "rail.load"]))(
        project
    )
    code, text = say("ratings", project, "--strict")
    assert code == 0, text
    first = text.splitlines()[0]
    assert first.startswith("PASS   ratings    0 fail, 0 accepted, ")
    assert " hold, 0 not judged; pack house.json (the project's own)" in first
    assert "nasa-eee-inst-002" not in first
    folder = project / "build" / "ratings"
    record = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    assert record["details"]["pack"] == "house.json (the project's own)"
    page = (folder / "report.md").read_text(encoding="utf-8").splitlines()
    assert " hold, 0 not judged; pack house.json (the project's own)" in page[2]
    # a pack of the workcenter is the workcenter's by whatever path the project names its file
    packs = ROOT / "rules" / "ratings"
    rewrite(
        project / "ratings.json", lambda stated: stated.update(pack=str(packs / "nasa-eee-inst-002.json"))
    )
    code, text = say("ratings", project, "--strict")
    first = text.splitlines()[0]
    assert code == 0 and " hold, 0 not judged; pack nasa-eee-inst-002" in first, text
    assert "the project's own" not in first


def test_a_run_that_judged_nothing_leaves_its_own_page_and_none_of_an_earlier_run(tmp_path):
    """A run that holds writes `RATINGS HELD` into its page. The next run refuses a file, and the one
    after exports no netlist: each leaves a page that says nothing was judged, and why, beside its
    record. A page of the first run would show the verdict of other files."""
    project = node(tmp_path)
    folder = project / "build" / "ratings"
    code, text = say("ratings", project)
    assert code == 0, text
    assert "\nRATINGS HELD\n" in (folder / "report.md").read_text(encoding="utf-8")
    rewrite(project / "ratings.json", lambda stated: stated.update(speed=1))
    code, text = say("ratings", project)
    assert code == 1 and text.startswith(REFUSED), text
    line = "ratings.json: `speed` is no key here; the keys are pack, nets, ambient, parts, accepted"
    assert (folder / "report.md").read_text(encoding="utf-8") == (
        f"# Ratings\n\nratings: a file is not as the command reads it\n\nNothing was judged.\n\n- {line}\n"
    )
    record = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    assert (record["status"], record["details"]["failures"]) == ("fail", [line])
    assert record["artifacts"] == [str(folder / "report.md")]
    # a schematic cut short: kicad-cli loads none, and the netlist of the run before is gone too
    assert (folder / "netlist.xml").is_file()
    sch = project / "node.kicad_sch"
    sch.write_text(sch.read_text(encoding="utf-8")[:40000], encoding="utf-8")
    code, text = say("ratings", project)
    assert code == 1 and text.startswith("ERROR  ratings    kicad-cli wrote no netlist"), text
    page = (folder / "report.md").read_text(encoding="utf-8")
    assert page.startswith("# Ratings\n\nratings: kicad-cli wrote no netlist\n\nNothing was judged.\n")
    assert "RATINGS HELD" not in page and "speed" not in page
    record = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    assert (record["status"], record["artifacts"]) == ("error", [str(folder / "report.md")])
    assert sorted(p.name for p in folder.iterdir()) == ["report.json", "report.md"]


def test_a_parts_file_that_is_not_there_is_refused_by_its_path(tmp_path):
    project = node(tmp_path)
    code, text = say("ratings", project, "--parts", tmp_path / "none.csv")
    assert code == 1 and text.startswith(REFUSED), text
    assert f"\n       - {tmp_path / 'none.csv'}: No such file or directory\n" in text


def test_facts_with_a_parts_file_the_command_does_not_take_is_refused_and_leaves_no_record(tmp_path):
    """`--facts` judges nothing, so it leaves no record of a run. It answers a wrong file as a run does."""
    project = node(tmp_path)
    code, text = say("ratings", project, "--facts", "U1", "--parts", tmp_path / "none.csv")
    assert code == 1 and "Traceback" not in text and text.startswith(REFUSED), text
    assert f"\n       - {tmp_path / 'none.csv'}: No such file or directory\n" in text
    (project / "parts.csv").write_text("Value,Footprint,Qty\n10k,x,1\n", encoding="utf-8")
    code, text = say("ratings", project, "--facts", "U1")
    assert code == 1 and "Traceback" not in text and text.startswith(REFUSED), text
    columns = "Manufacturer, MPN, Supplier, SKU, Pack, Breaks"
    assert f"\n       - {project / 'parts.csv'}: no column {columns}\n" in text
    (project / "parts.csv").write_text(HEAD + "TLV62569,Package_TO_SOT_SMD:SOT-23-5,1\n", encoding="utf-8")
    code, text = say("ratings", project, "--facts", "U1")
    assert code == 1 and "Traceback" not in text and text.startswith(REFUSED), text
    assert "\n       - parts.csv:2: 3 fields, and the header names 9\n" in text
    assert not (project / "build" / "ratings" / "report.json").exists()


def test_out_that_names_a_file_is_refused_and_nothing_is_written_over_it(tmp_path):
    project = node(tmp_path)
    (tmp_path / "outfile").write_text("x", encoding="utf-8")
    for more in ((), ("--facts", "U1")):
        code, text = say("ratings", project, "--out", tmp_path / "outfile", *more)
        assert code == 1 and "Traceback" not in text and text.startswith(REFUSED), text
        assert (
            f"\n       - --out {tmp_path / 'outfile'}: a file stands there, and a folder is asked\n" in text
        )
    assert (tmp_path / "outfile").read_text(encoding="utf-8") == "x"
    # --init judges nothing and writes 1 file beside the schematic: it does not look at --out
    (project / "ratings.json").unlink()
    code, text = say("ratings", project, "--init", "--out", tmp_path / "outfile")
    assert code == 0 and f"wrote {project / 'ratings.json'}" in text, text
    assert not (project / "build").exists()


def test_a_schematic_with_2_parts_of_1_reference_is_refused_by_the_schematic_s_name(tmp_path):
    """kicad-cli writes 1 part for the 2, with each pin on 2 nets. The netlist's reader refuses it, and
    the line names the file the fault is in. `--facts` reads the same netlist."""
    project = node(tmp_path)
    sch = project / "node.kicad_sch"
    text = sch.read_text(encoding="utf-8")
    assert text.count('"Reference" "R2"') == 1 and text.count('(reference "R2")') == 1
    twice = text.replace('"Reference" "R2"', '"Reference" "R1"').replace(
        '(reference "R2")', '(reference "R1")'
    )
    sch.write_text(twice, encoding="utf-8")
    for more in ((), ("--facts", "R1")):
        code, text = say("ratings", project, *more)
        assert code == 1 and "Traceback" not in text and text.startswith(REFUSED), text
        assert "\n       - node.kicad_sch: " in text, text


def test_an_engine_that_is_missing_is_named_with_and_without_facts(tmp_path):
    """kicad-cli that is not installed is no file to refuse: the run is skipped, exit 2, with its name."""
    project = node(tmp_path)
    absent = str(tmp_path / "no-kicad-cli")
    for more in ((), ("--facts", "U1")):
        code, text = say("ratings", project, *more, env={"KICAD_CLI": absent})
        assert code == 2 and "Traceback" not in text, text
        assert text.startswith(f"SKIP   ratings    engine missing: {absent}"), text


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
