"""The SIM gate's own soundness, the verdict words, and the bundle a deck leaves the gate's machine in.

Each test builds its project in tmp_path. The decks are the cases the gate once let through: an
analysis ngspice gives up on while a later one completes (M103), an expect file whose key is misspelt
(M104), a value that is complex, a node that floats, a ~/.spiceinit of the user's. The bundle tests use
a vendor's model written the PSpice way, which a bare run reads as another circuit (M105). Tests that
run ngspice skip when it is absent.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import json
import os
import re
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"

needs_ngspice = pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice is not installed")
needs_kicad = pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")

DIVIDER = """* a divider: 5 V through 10k into 10k
V1 in 0 DC 5
R1 in out 10k
R2 out 0 10k
.control
op
let vout = v(out)
print vout
.endc
.end
"""

# The first transient stops at 5 us, where the source B1 has no solution; the second, shorter one
# completes, so ngspice exits 0. ngspice 42 prints `doAnalyses: TRAN:  Timestep too small; ...` and
# `tran simulation(s) aborted` for the first (PROCESSES.md P7 step 3: the lines are from a run).
ABORTED = """* the first transient stops at 5 us; a second, shorter one completes
V1 in 0 PULSE(0 1 1u 1n 1n 10u)
R1 in out 1k
C1 out 0 1n
RB b 0 1k
B1 b 0 V = time > 5u ? (v(b) > 0.5 ? 0 : 1) : 0
.control
tran 0.1u 30u
meas tran vmax max v(out)
tran 0.1u 4u
meas tran v4u max v(out)
.endc
.end
"""

FLOATING = """* a node between two capacitors has no path to ground
V1 in 0 DC 5
C1 in mid 1n
C2 mid 0 1n
R1 in out 10k
R2 out 0 10k
.control
op
let vout = v(out)
let vmid = v(mid)
print vout vmid
.endc
.end
"""

# 1 kOhm into 100 nF at 1 kHz: |H| = 1/sqrt(1 + (1000/1591.5)^2) = 0.8467; H itself is complex.
COMPLEX = """* an .ac deck that prints a complex value and its magnitude
V1 in 0 AC 1
R1 in out 1k
C1 out 0 100n
.control
ac lin 1 1k 1k
let h = v(out)
let hm = vm(out)
print h hm
.endc
.end
"""

# A vendor's divider written the PSpice way: R1 names a RES model whose R is 99.5, so PSpice makes it
# 99.5 Ohm where ngspice, reading the value alone, makes it 1 Ohm. From 1 V: 100/199.5 = 0.5013 V read
# the PSpice way, 100/101 = 0.9901 V read bare.
MODEL = """* Test divider model, rev 1
.SUBCKT RDIV IN OUT GND
R1 IN OUT Rmod 1
R2 OUT GND 100
.MODEL Rmod RES (R=99.5)
.ENDS
"""
VENDOR_DECK = """* a divider from a vendor's model
.include "../../library/maker/rdiv.lib"
V1 in 0 DC 1
X1 in out 0 RDIV
.control
op
let vout = v(out)
print vout
.endc
.end
"""


def load_cli():
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_simgate", str(CLI))
    module = types.ModuleType("workcenter_cli_simgate")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module  # dataclasses look the defining module up here
    loader.exec_module(module)
    return module


def run(*args: object, env: dict | None = None) -> tuple[int, list[dict]]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
    )
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else [])


def text_of(*args: object, env: dict | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
    )
    return proc.returncode, proc.stdout


def project(tmp_path: Path, decks: dict[str, str], expects: dict[str, object] | None = None) -> Path:
    proj = tmp_path / "proj"
    (proj / "sim").mkdir(parents=True)
    for name, text in decks.items():
        (proj / "sim" / f"{name}.cir").write_text(text, encoding="utf-8")
    for name, bounds in (expects or {}).items():
        body = bounds if isinstance(bounds, str) else json.dumps(bounds)
        (proj / "sim" / f"{name}.expect.json").write_text(body, encoding="utf-8")
    return proj


def vendor_project(tmp_path: Path, ngspice: str = "ps res-model") -> Path:
    """A project whose deck includes a library model that needs the gate: a mode and a translation."""
    lib = tmp_path / "library" / "maker"
    lib.mkdir(parents=True)
    (lib / "rdiv.lib").write_text(MODEL, encoding="utf-8")
    digest = hashlib.sha256((lib / "rdiv.lib").read_bytes()).hexdigest()
    (tmp_path / "library" / "sources.csv").write_text(
        "MPN,Kind,URL,File,Member,Revision,Dated,Subckt,Ngspice,SHA256,Checked,Note\n"
        f"RDIV-1,spice,https://example.com/rdiv.lib,maker/rdiv.lib,,rev 1,2020,RDIV,{ngspice},{digest},"
        "2026-11-10,\n",
        encoding="utf-8",
    )
    return project(tmp_path, {"rdiv": VENDOR_DECK}, {"rdiv": {"vout": {"min": 0.49, "max": 0.51}}})


# ------------------------------------------------------------- pure logic


def test_a_measure_is_a_name_and_a_whole_number_never_the_real_part_of_a_complex_one():
    cli = load_cli()
    found = {}
    for line in (
        "vpk                 =  1.992968e+01 at=  1.594043e+05",  # a `meas` line of ngspice 42
        "vout = 2.500000e+00",  # a `print` line
        "h = 8.467330e-01,-5.32021e-01",  # a complex value: no measure
        "v(out) = 2.5",  # no name
        "TEMP=27",
    ):
        m = cli.MEASURE_RE.match(line)
        if m:
            found[m.group(1)] = float(m.group(2))
    assert found == {"vpk": 19.92968, "vout": 2.5, "TEMP": 27.0}


def test_the_lines_of_an_analysis_ngspice_gave_up_on_are_errors():
    cli = load_cli()
    for line in (
        'doAnalyses: TRAN:  Timestep too small; time = 5e-06, timestep = 1.25e-19: trouble with node "b"',
        "tran simulation(s) aborted",
        "Error: no such function 'if'",
    ):
        assert cli.NGSPICE_ERROR_RE.match(line), line
    for line in ("No. of Data Rows : 74", "Note: Simulation executed from .control section"):
        assert not cli.NGSPICE_ERROR_RE.match(line), line
    assert cli.NGSPICE_UNSOUND_RE.match("Warning: singular matrix:  check node mid")
    assert cli.NGSPICE_UNSOUND_RE.match("Warning: source stepping failed")
    assert not cli.NGSPICE_UNSOUND_RE.match(
        "Warning: Dynamic gmin stepping failed"
    )  # the next method may work


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ('{"vout": {"mx": 3.0}}', ["vout: unknown key 'mx'", "vout: neither min nor max"]),
        ('{"vout": {"req": "REQ-X-01"}}', ["vout: neither min nor max"]),
        ('{"vout": {"min": null, "max": 3}}', ["vout: min None is not a number"]),
        ('{"vout": {"min": "2", "max": 3}}', ["vout: min '2' is not a number"]),
        ('{"vout": {"min": true}}', ["vout: min True is not a number"]),
        ('{"vout": 2.5}', ["vout: not an object with min or max"]),
        ('{"vout": {"min": 2.6, "max": 2.4}}', ["vout: min 2.6 is above max 2.4"]),
        (
            '{"VOUT": {"min": 2.4}}',
            ["VOUT: ngspice prints a name in lower case, so this one is never measured"],
        ),
        ('{"vout": {"max": 3, "at": "hot"}}', ["vout: at 'hot' is not \"nominal\""]),
        ('{"vout": {"max": 3, "source": 7}}', ["vout: source is not text"]),
        ('{"vout": {"max": 3},}', None),  # a trailing comma: not JSON
        ("[1, 2]", ["not an object of measure: bound"]),
    ],
)
def test_an_expect_file_is_read_against_its_keys(tmp_path, body, said):
    cli = load_cli()
    path = tmp_path / "d.expect.json"
    path.write_text(body, encoding="utf-8")
    bounds, problems = cli.read_expect(path)
    assert bounds == {}
    if said is None:
        assert len(problems) == 1 and problems[0].startswith("not JSON: ")
    else:
        assert problems == said


def test_a_sound_expect_file_gives_its_bounds_and_an_absent_one_none(tmp_path):
    cli = load_cli()
    path = tmp_path / "d.expect.json"
    entry = {"min": 2.4, "max": 2.6, "source": "the spec", "req": "REQ-A-01", "at": "nominal"}
    path.write_text(json.dumps({"vout": entry, "i": {"max": 1, "warn": "its datasheet"}}), encoding="utf-8")
    assert cli.read_expect(path) == ({"vout": entry, "i": {"max": 1, "warn": "its datasheet"}}, [])
    assert cli.read_expect(tmp_path / "none.expect.json") == ({}, [])


def test_the_verdict_names_the_warnings_and_never_calls_a_missing_engine_green():
    cli = load_cli()
    erc = cli.Result("erc", "pass", "", {"counts": {"error": 0, "warning": 2, "other": 0}})
    drc = cli.Result("drc", "pass", "", {"counts": {"violations": {"error": 0, "warning": 4, "other": 0}}})
    sim = cli.Result("sim", "pass", "", {"warnings": ["a", "b", "c"]})
    assert cli.gates_verdict([erc, drc, sim]) == ("GREEN with 9 warnings", 0)
    assert cli.gates_verdict([cli.Result("erc", "pass", "", {"counts": {"error": 0, "warning": 1}})]) == (
        "GREEN with 1 warning",
        0,
    )
    clean = cli.Result("export", "pass", "")
    assert cli.gates_verdict([clean]) == ("GREEN", 0)
    # a gate with nothing to run (no decks) leaves the run GREEN and is named beside the word, so a
    # project with decks and no board is not read as a finished board; one whose engine is absent
    # is never GREEN
    nothing = cli.Result("sim", "skip", "no sim/*.cir in project")
    absent = cli.Result("sim", "skip", "engine missing: ngspice", {"engine_missing": "ngspice"})
    assert cli.gates_verdict([clean, nothing]) == ("GREEN (nothing to run for: sim)", 0)
    idle = [cli.Result(g, "skip", "nothing") for g in ("erc", "drc")]
    assert cli.gates_verdict([*idle, sim, cli.Result("export", "skip", "no board")]) == (
        "GREEN with 3 warnings (nothing to run for: erc, drc, export)",
        0,
    )
    assert cli.gates_verdict([clean, absent]) == ("SKIPPED (SIM: engine missing)", 2)
    assert cli.gates_verdict([nothing]) == ("SKIPPED", 2)
    assert cli.gates_verdict([clean, absent, cli.Result("drc", "fail", "")]) == ("RED", 1)
    assert cli.gates_verdict([cli.Result("drc", "error", "")]) == ("RED", 1)


def test_requirements_are_met_only_when_every_one_passes_at_its_corners():
    cli = load_cli()

    def said(verdicts: dict, problems: int = 0, corners: bool = True, as_written: dict | None = None) -> str:
        total = sum(len(v) for v in verdicts.values())
        details = {"verdicts": verdicts, "requirements": total, "problems": problems, "corners": corners}
        if as_written is not None:
            details["as_written"] = as_written
        return cli.requirements_verdict(cli.Result("verify", "pass", "", details))

    assert said({"PASS": ["A", "B"], "FAIL": [], "OPEN": []}) == "REQUIREMENTS MET (2 of 2 pass)"
    assert (
        said({"PASS": ["A"], "FAIL": ["B", "C"], "OPEN": ["D"]})
        == "REQUIREMENTS NOT MET (1 of 4 pass; 2 fail: B, C; 1 open)"
    )
    assert said({"PASS": ["A"], "FAIL": [], "OPEN": []}, problems=3) == (
        "REQUIREMENTS NOT MET (1 of 1 pass; 3 problems in the package)"
    )
    assert said({"PASS": ["A"], "FAIL": [], "OPEN": []}, corners=False) == (
        "REQUIREMENTS NOT MET (1 of 1 pass; no corners run)"
    )
    assert said({"PASS": [], "FAIL": [], "OPEN": []}) == "REQUIREMENTS NOT MET (0 of 0 pass)"
    # every requirement PASS, and 1 of them rests on a deck that ran no corner: not met
    assert said({"PASS": ["A", "B"], "FAIL": [], "OPEN": []}, as_written={"B": "d"}) == (
        "REQUIREMENTS NOT MET (2 of 2 pass; 1 judged as written only)"
    )
    assert (
        said({"PASS": ["A", "B"], "FAIL": [], "OPEN": []}, as_written={}) == "REQUIREMENTS MET (2 of 2 pass)"
    )
    seven = [f"R{n}" for n in range(7)]
    assert "7 fail: R0, R1, R2, R3, R4, R5 ..." in said({"PASS": [], "FAIL": seven, "OPEN": []})


# ------------------------------------------------------------- the gate


@needs_ngspice
def test_an_analysis_that_aborted_fails_its_deck_though_a_later_one_completed(tmp_path):
    # Its measure on the cut vector, 0.98 V, is inside the bound: only the aborted analysis fails it.
    proj = project(tmp_path, {"abort": ABORTED}, {"abort": {"vmax": {"min": 0.9, "max": 1.1}}})
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1
    deck = records[0]["details"]["decks"]["abort"]
    assert deck["exit"] == 0 and deck["checks"]["vmax"]["ok"] is True
    assert [e.split(":")[0] for e in deck["errors"]] == ["doAnalyses", "tran simulation(s) aborted"]
    # the failure names the first error line and the one log to open
    (line,) = records[0]["details"]["failures"]
    assert line.startswith("abort: ngspice exit 0, 2 error lines: doAnalyses: TRAN:  Timestep too small")
    assert line.endswith(f"(log {tmp_path / 'o' / 'sim' / 'abort.log'})")
    assert (tmp_path / "o" / "sim" / "abort.log").is_file()


CROSSING = """* a crossing that exists as written and not with a resistor 5 % off
V1 in 0 DC 0
R1 in out 10k
R2 out 0 10k
.control
dc V1 0 5 0.01
meas dc v_at when v(out)=2.49
print v_at
.endc
.end
"""


@needs_ngspice
def test_a_corner_ngspice_does_not_finish_fails_and_names_its_error_and_its_log(tmp_path):
    """The output reaches 2.49 V at 4.98 V in as written. With R1 5 % high or R2 5 % low it never does:
    the `meas` fails, ngspice exits 0, and the corner fails with the error and the one log to open."""
    proj = project(tmp_path, {"cross": CROSSING}, {"cross": {"v_at": {"min": 4.5, "max": 5.0}}})
    (proj / "sim" / "corners.json").write_text(
        json.dumps({"tolerance": {"R": 0.05, "source": "the test"}}), encoding="utf-8"
    )
    code, records = run("sim", proj, "--out", tmp_path / "o")
    details = records[0]["details"]
    assert code == 1 and details["decks"]["cross"]["measures"] == {"v_at": 4.98}
    corners = tmp_path / "o" / "sim" / "corners" / "cross"
    error = "ngspice exit 0, 1 error lines: Error: measure  v_at  when(WHEN) : out of interval"
    # each part alone at its end and half-way to it, then both at their ends together
    assert details["failures"] == [
        f"cross: at R1 +5 %: {error} (log {corners / 'R1+' / 'ngspice.log'})",
        f"cross: at R1 +2.5 %: {error} (log {corners / 'R1+h' / 'ngspice.log'})",
        f"cross: at R2 -5 %: {error} (log {corners / 'R2-' / 'ngspice.log'})",
        f"cross: at R2 -2.5 %: {error} (log {corners / 'R2-h' / 'ngspice.log'})",
        f"cross: at R1 +5 %, R2 -5 %: {error} (log {corners / 'e003' / 'ngspice.log'})",
    ]
    assert "out of interval" in (corners / "R2-" / "ngspice.log").read_text(encoding="utf-8")


RKM = """* a divider with a value written the way a schematic writes 4.7 k
V1 in 0 DC 5
R1 in out 4k7
R2 out 0 4.7k
.control
op
let vout = v(out)
print vout
.endc
.end
"""


@needs_ngspice
def test_a_value_ngspice_reads_as_another_number_fails_its_deck(tmp_path):
    """ngspice takes `4k7` for 4k and says nothing: the output is 5 x 4.7 / 8.7 = 2.7011 V where the
    author meant 2.5 V. The bound here is wide enough to hold either; the deck fails on the value."""
    proj = project(tmp_path, {"rkm": RKM}, {"rkm": {"vout": {"min": 2.0, "max": 3.0}}})
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1
    assert records[0]["details"]["decks"]["rkm"]["measures"]["vout"] == pytest.approx(2.701149, abs=1e-6)
    assert records[0]["details"]["failures"] == [
        "rkm: R1: ngspice reads the value 4k7 as 4k: it drops a digit after the scale letter. Write 4.7k"
    ]


@needs_ngspice
def test_a_node_that_floats_is_a_warning_and_fails_a_strict_run(tmp_path):
    proj = project(tmp_path, {"floating": FLOATING}, {"floating": {"vout": {"min": 2.4, "max": 2.6}}})
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 0
    assert [w for w in records[0]["details"]["warnings"] if w.startswith("floating: ngspice: ")] == [
        "floating: ngspice: Warning: singular matrix:  check node mid",
        "floating: ngspice: Warning: source stepping failed",
    ]
    code, records = run("sim", proj, "--out", tmp_path / "o", "--strict")
    assert code == 1


@needs_ngspice
def test_a_complex_value_is_not_measured_and_its_magnitude_is(tmp_path):
    bounds = {"h": {"min": 0.5, "max": 0.9}, "hm": {"min": 0.84, "max": 0.85}}
    proj = project(tmp_path, {"ac": COMPLEX}, {"ac": bounds})
    code, records = run("sim", proj, "--out", tmp_path / "o")
    deck = records[0]["details"]["decks"]["ac"]
    assert code == 1 and deck["measures"] == {"hm": pytest.approx(0.8467, abs=1e-4)}
    assert records[0]["details"]["failures"] == ["ac:h=None not in [0.5, 0.9]"]


@needs_ngspice
def test_a_malformed_expect_file_is_a_failure_of_the_gate_not_a_traceback(tmp_path):
    decks = {name: DIVIDER for name in ("typo", "comma", "none")}
    proj = project(tmp_path, decks, {"typo": {"vout": {"minimum": 2.4}}, "comma": '{"vout": {"min": 2.4},}'})
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1 and records[0]["status"] == "fail"
    failures = records[0]["details"]["failures"]
    assert "typo.expect.json: vout: unknown key 'minimum'" in failures
    assert "typo.expect.json: vout: neither min nor max" in failures
    assert any(f.startswith("comma.expect.json: not JSON: ") for f in failures)
    # a deck with no expect file at all is named, and fails only a strict run
    assert "none: no bound in an expect file holds any of its measures" in records[0]["details"]["warnings"]


@needs_ngspice
def test_the_users_own_spiceinit_does_not_reach_a_deck(tmp_path):
    proj = project(tmp_path, {"d": DIVIDER}, {"d": {"vout": {"min": 2.4, "max": 2.6}}})
    home = tmp_path / "home"
    home.mkdir()
    # were it read, this line would print one more measure
    (home / ".spiceinit").write_text('echo "home_init = 1"\n', encoding="utf-8")
    code, records = run("sim", proj, "--out", tmp_path / "o", env={"HOME": str(home)})
    assert code == 0 and records[0]["details"]["decks"]["d"]["measures"] == {"vout": 2.5}
    # the trap the gate closes: a bare run in the same place reads the file
    bare = subprocess.run(
        ["ngspice", "-b", "d.cir"],
        cwd=proj / "sim",
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "HOME": str(home)},
    )
    assert "home_init = 1" in bare.stdout


def test_a_gate_whose_engine_is_absent_is_never_part_of_a_green_run(tmp_path):
    proj = project(tmp_path, {"d": DIVIDER}, {"d": {"vout": {"min": 2.4, "max": 2.6}}})
    absent = {"NGSPICE": str(tmp_path / "no-such-ngspice")}
    code, records = run("sim", proj, "--out", tmp_path / "o", env=absent)
    assert code == 2 and records[0]["status"] == "skip"
    assert records[0]["details"] == {"engine_missing": absent["NGSPICE"]}
    code, text = text_of("gates", proj, "--out", tmp_path / "o", env=absent)
    assert code == 2
    assert text.splitlines()[-1].startswith("SKIPPED (SIM: engine missing): proj  report ")


@needs_kicad
@needs_ngspice
def test_the_gates_verdict_line_carries_the_warnings(tmp_path):
    code, text = text_of("gates", BOARDS / "pass-rc-divider", "--out", tmp_path / "o")
    assert code == 0 and text.splitlines()[-1].startswith("GREEN: rc_divider  report ")
    # the same board without its corners: still GREEN, and the line says what GREEN leaves open
    proj = tmp_path / "rc"
    shutil.copytree(BOARDS / "pass-rc-divider", proj, ignore=shutil.ignore_patterns("build"))
    (proj / "sim" / "corners.json").unlink()
    code, text = text_of("gates", proj, "--out", tmp_path / "o2")
    assert code == 0 and text.splitlines()[-1].startswith("GREEN with 1 warning: rc_divider  report ")
    assert "       - warning: no sim/corners.json: each deck ran once, at 27 C" in text
    code, text = text_of("gates", proj, "--out", tmp_path / "o3", "--strict")
    assert code == 1 and text.splitlines()[-1].startswith("RED: rc_divider  report ")


# ------------------------------------------------------------- the bundle


@needs_ngspice
def test_a_bundle_runs_from_anywhere_and_gives_the_gates_numbers(tmp_path):
    proj = vendor_project(tmp_path)
    bundle = tmp_path / "bundle"
    code, records = run("sim", proj, "--out", tmp_path / "o", "--bundle", bundle)
    assert code == 0, records
    deck = records[0]["details"]["decks"]["rdiv"]
    assert deck["measures"]["vout"] == pytest.approx(100 / 199.5, abs=1e-4)
    folder = Path(deck["bundle"])
    assert folder == bundle / "rdiv"
    files = sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())
    assert files == [
        "README.md",
        "expect.json",
        "measures.json",
        "models/rdiv.ngspice.lib",
        "rdiv.cir",
        "run.sp",
    ]
    # nothing in it names a path of this machine
    for name in files:
        assert str(tmp_path) not in (folder / name).read_text(encoding="utf-8"), name
    assert '.include "models/rdiv.ngspice.lib"' in (folder / "rdiv.cir").read_text(encoding="utf-8")
    wrapper = (folder / "run.sp").read_text(encoding="utf-8").splitlines()
    # the deck is read from its own folder, so a file it names beside it is found from anywhere
    assert wrapper[2:] == [
        ".control",
        "set ngbehavior=ps",
        "cd $inputdir",
        "source rdiv.cir",
        ".endc",
        ".end",
    ]
    assert json.loads((folder / "measures.json").read_text(encoding="utf-8")) == deck["measures"]
    assert json.loads((folder / "expect.json").read_text(encoding="utf-8")) == {
        "vout": {"min": 0.49, "max": 0.51}
    }
    readme = (folder / "README.md").read_text(encoding="utf-8")
    assert (
        "    ngspice -b run.sp" in readme
        and "| `models/rdiv.ngspice.lib` | RDIV-1 | rev 1 | res-model |" in readme
    )
    # the receiver's run: the folder moved, another working directory, an empty home folder
    moved = tmp_path / "elsewhere" / "rdiv"
    shutil.copytree(folder, moved)
    shutil.rmtree(tmp_path / "library")
    home = tmp_path / "home"
    home.mkdir()
    proc = subprocess.run(
        ["ngspice", "-b", str(moved / "run.sp")],
        cwd=home,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "HOME": str(home)},
    )
    vout = float(re.search(r"^vout = (\S+)", proc.stdout, re.M).group(1))
    assert vout == pytest.approx(100 / 199.5, abs=1e-4)


@needs_ngspice
def test_the_deck_alone_is_the_trap_the_bundle_closes(tmp_path):
    proj = vendor_project(tmp_path, ngspice="res-model")
    proc = subprocess.run(
        ["ngspice", "-b", "rdiv.cir"], cwd=proj / "sim", capture_output=True, text=True, check=False
    )
    vout = float(re.search(r"^vout = (\S+)", proc.stdout, re.M).group(1))
    assert proc.returncode == 0 and vout == pytest.approx(100 / 101, abs=1e-4)  # exit 0 and another circuit
    # a row with no mode writes a run.sp that sets none
    code, records = run("sim", proj, "--out", tmp_path / "o", "--bundle", tmp_path / "b", "--deck", "rdiv")
    assert code == 0, records
    assert (tmp_path / "b" / "rdiv" / "run.sp").read_text(encoding="utf-8").splitlines()[2:] == [
        ".control",
        "cd $inputdir",
        "source rdiv.cir",
        ".endc",
        ".end",
    ]


@needs_ngspice
def test_a_bundle_that_gives_another_number_than_the_gate_is_named(tmp_path):
    cli = load_cli()
    proj = vendor_project(tmp_path)
    code, records = run("sim", proj, "--out", tmp_path / "o", "--bundle", tmp_path / "b")
    assert code == 0, records
    folder = tmp_path / "b" / "rdiv"
    # the gate's own measures are what a bundle must print, digit for digit
    assert cli.check_bundle(folder, "rdiv", records[0]["details"]["decks"]["rdiv"]["measures"]) == []
    problems = cli.check_bundle(folder, "rdiv", {"vout": 0.9, "gone": 1.0})
    assert len(problems) == 2
    assert problems[0] == "rdiv: the bundle gives gone=None, the gate 1.0"
    assert re.fullmatch(r"rdiv: the bundle gives vout=0\.501\d*, the gate 0\.9", problems[1]), problems
    # a bundle whose model is gone does not run, and the line carries ngspice's own first error
    (folder / "models" / "rdiv.ngspice.lib").unlink()
    assert cli.check_bundle(folder, "rdiv", {})[0] == (
        "rdiv: the bundle does not run from another folder: ngspice exit 1, 1 error lines: Error: Could "
        "not find include file models/rdiv.ngspice.lib"
    )


@needs_ngspice
def test_a_model_that_includes_another_file_takes_it_into_the_bundle(tmp_path):
    proj = project(
        tmp_path, {"d": DIVIDER.replace("R2 out 0 10k", 'X2 out 0 RLOW\n.include "models/outer.lib"')}
    )
    (proj / "sim" / "d.expect.json").write_text('{"vout": {"min": 2.4, "max": 2.6}}', encoding="utf-8")
    models = proj / "sim" / "models"
    models.mkdir()
    (models / "outer.lib").write_text('* outer\n.include "inner.lib"\n', encoding="utf-8")
    (models / "inner.lib").write_text("* inner\n.subckt RLOW a b\nR1 a b 10k\n.ends\n", encoding="utf-8")
    code, records = run("sim", proj, "--out", tmp_path / "o", "--bundle", tmp_path / "b")
    assert code == 0, records
    folder = tmp_path / "b" / "d"
    assert sorted(p.name for p in (folder / "models").iterdir()) == ["inner.lib", "outer.lib"]
    assert '.include "inner.lib"' in (folder / "models" / "outer.lib").read_text(encoding="utf-8")


# ------------------------------------------------- what 2 reviews of the gate found


def test_a_bound_that_is_no_number_or_leaves_the_corners_with_no_reason_is_refused(tmp_path):
    """Python's json reads NaN and Infinity, and every comparison with NaN is false: such a bound would
    hold at any value. `"at": "nominal"` takes a bound out of every corner, so it says why."""
    cli = load_cli()
    path = tmp_path / "d.expect.json"
    path.write_text('{"a": {"max": NaN}, "b": {"min": -Infinity, "max": 1}}', encoding="utf-8")
    assert cli.read_expect(path) == (
        {},
        ["a: max nan is not a number", "b: min -inf is not a number"],
    )
    path.write_text('{"vout": {"min": 2.4, "max": 2.6, "at": "nominal"}}', encoding="utf-8")
    assert cli.read_expect(path) == (
        {},
        ['vout: "at": "nominal" needs a source that says why the bound holds as written only'],
    )
    entry = {"min": 2.4, "max": 2.6, "at": "nominal", "source": "the model's 25 C row, datasheet table 6.5"}
    path.write_text(json.dumps({"vout": entry}), encoding="utf-8")
    assert cli.read_expect(path) == ({"vout": entry}, [])


TWICE = """* 1 name printed by 2 analyses
V1 in 0 DC 5
R1 in out 10k
R2 out 0 90k
.control
op
let vout = v(out)
print vout
alter r2 10k
op
let vout = v(out)
print vout
.endc
.end
"""


@needs_ngspice
def test_a_name_printed_twice_is_held_to_its_bound_each_time(tmp_path):
    """5 x 90 / 100 = 4.5 V first, 2.5 V after the alter. The last value is the measure; the first is
    outside the bound too and was never judged."""
    proj = project(tmp_path, {"twice": TWICE}, {"twice": {"vout": {"min": 2.3, "max": 2.7}}})
    code, records = run("sim", proj, "--out", tmp_path / "o")
    assert code == 1
    assert records[0]["details"]["decks"]["twice"]["measures"] == {"vout": 2.5}
    assert records[0]["details"]["failures"] == [
        "twice:vout=4.5 not in [2.3, 2.7]: the deck prints vout more than once, and this value came "
        "before its last"
    ]
    # 1 value printed 2 times, as `meas` and then `print` do, is 1 value
    same = DIVIDER.replace("print vout", "print vout\nprint vout")
    proj = project(tmp_path / "2", {"d": same}, {"d": {"vout": {"min": 2.4, "max": 2.6}}})
    code, records = run("sim", proj, "--out", tmp_path / "o2")
    assert code == 0 and records[0]["details"]["failures"] == []


SOURCED = """* a file read inside .control
V1 in 0 DC 5
R1 in out 10k
R2 out 0 10k tc1=100u
.control
op
let vout = v(out)
source print_it.sp
.endc
.end
"""


@needs_ngspice
def test_a_deck_that_reads_a_file_beside_it_runs_at_its_corners_and_in_its_bundle(tmp_path):
    """A corner is a copy of the deck in a folder of its own. `source print_it.sp` names a file of the
    deck's folder, which the copy must still find. At 85 C: 5 x 10058 / 20058 = 2.5072 V."""
    proj = project(tmp_path, {"d": SOURCED}, {"d": {"vout": {"min": 2.4, "max": 2.6}}})
    (proj / "sim" / "print_it.sp").write_text(
        "* helper: prints the output\n.control\nprint vout\n.endc\n", encoding="utf-8"
    )
    (proj / "sim" / "corners.json").write_text(
        json.dumps({"temperature": {"values": [85], "source": "x"}}), encoding="utf-8"
    )
    before = sorted(str(p.relative_to(proj)) for p in proj.rglob("*"))
    code, records = run("sim", proj, "--out", tmp_path / "o", "--bundle", tmp_path / "b")
    assert code == 0, records
    span = records[0]["details"]["decks"]["d"]["corners"]["envelope"]["vout"]
    assert span["max"] == pytest.approx(2.507229, abs=1e-6) and span["max_at"] == "85 C"
    # nothing is written into the project, and the bundle carries the file and runs from elsewhere
    assert sorted(str(p.relative_to(proj)) for p in proj.rglob("*")) == before
    assert (tmp_path / "b" / "d" / "print_it.sp").is_file()
    assert "cd $inputdir" in (tmp_path / "b" / "d" / "run.sp").read_text(encoding="utf-8")


@needs_ngspice
def test_a_path_with_a_space_runs_at_a_corner_and_in_a_bundle(tmp_path):
    """The gate writes a deck's includes as whole paths. Written without quotes, a path with a space
    is cut at the space, and every corner fails on a deck that runs in place."""
    proj = tmp_path / "my board" / "p"
    (proj / "sim" / "models").mkdir(parents=True)
    (proj / "sim" / "my models").mkdir()
    sim, out = proj / "sim", tmp_path / "my board" / "o"
    (sim / "models" / "rsub.lib").write_text(".subckt rsub a b\nRLOW a b 10k\n.ends\n", encoding="utf-8")
    (sim / "my models" / "rsub2.lib").write_text(".subckt rsub2 a b\nRLOW a b 30k\n.ends\n", encoding="utf-8")
    bare = "V1 in 0 DC 5\nR1 in out 10k tc1=100u\n.include models/rsub.lib\nXLOW out 0 rsub\n"
    quoted = 'V1 in 0 DC 5\nR1 in out 10k\n.include "my models/rsub2.lib"\nXLOW out 0 rsub2\n'
    tail = ".control\nop\nlet vout = v(out)\nprint vout\n.endc\n.end\n"
    (sim / "q.cir").write_text("* an include without quotes\n" + bare + tail, encoding="utf-8")
    (sim / "space.cir").write_text("* a quoted include with a space\n" + quoted + tail, encoding="utf-8")
    (sim / "corners.json").write_text(
        json.dumps({"temperature": {"values": [85], "source": "x"}}), encoding="utf-8"
    )
    code, text = text_of("sim", proj, "--out", out, "--bundle", tmp_path / "my board" / "b")
    assert code == 0, text
    code, records = run("sim", proj, "--out", tmp_path / "my board" / "o2")
    decks = records[0]["details"]["decks"]
    # 5 x 10000 / 20058 = 2.4928 V hot; 5 x 30 / 40 = 3.75 V
    assert decks["q"]["corners"]["envelope"]["vout"]["min"] == pytest.approx(2.492771, abs=1e-6)
    assert decks["space"]["measures"]["vout"] == pytest.approx(3.75)
    bundle = tmp_path / "my board" / "b"
    assert '.include "models/rsub.lib"' in (bundle / "q" / "q.cir").read_text(encoding="utf-8")
    assert '.include "models/rsub2.lib"' in (bundle / "space" / "space.cir").read_text(encoding="utf-8")
    assert str(tmp_path) not in (bundle / "q" / "q.cir").read_text(encoding="utf-8")
    # the command it prints is one a shell takes as written
    assert f"bundle q: ngspice -b '{bundle / 'q' / 'run.sp'}'" in text


@needs_ngspice
def test_a_bundle_never_replaces_a_folder_that_is_no_bundle(tmp_path):
    proj = project(tmp_path, {"d": DIVIDER}, {"d": {"vout": {"min": 2.4, "max": 2.6}}})
    mine = tmp_path / "b" / "d"
    mine.mkdir(parents=True)
    (mine / "notes.txt").write_text("my own\n", encoding="utf-8")
    code, records = run("sim", proj, "--out", tmp_path / "o", "--bundle", tmp_path / "b")
    assert code == 1
    assert records[0]["details"]["failures"] == [
        f"d: {mine} is there and is no bundle (it holds no run.sp): name another folder, or remove it"
    ]
    assert sorted(p.name for p in mine.iterdir()) == ["notes.txt"]
    # an earlier bundle is replaced, and the README lists only what the folder holds
    code, _ = run("sim", proj, "--out", tmp_path / "o", "--bundle", tmp_path / "b2")
    (tmp_path / "b2" / "d" / "stale.txt").write_text("from the run before\n", encoding="utf-8")
    (proj / "sim" / "d.expect.json").unlink()
    code, _ = run("sim", proj, "--out", tmp_path / "o", "--bundle", tmp_path / "b2")
    assert code == 0
    assert sorted(p.name for p in (tmp_path / "b2" / "d").iterdir()) == [
        "README.md",
        "d.cir",
        "measures.json",
        "models",
        "run.sp",
    ]
    assert "expect.json" not in (tmp_path / "b2" / "d" / "README.md").read_text(encoding="utf-8")


@needs_ngspice
def test_every_warning_is_printed_and_the_verdict_is_the_last_line(tmp_path):
    decks = {f"d{n}": DIVIDER for n in range(1, 8)}
    proj = project(tmp_path, decks)
    code, text = text_of("gates", proj, "--out", tmp_path / "o")
    lines = text.splitlines()
    # 7 decks with no bound, and no corners.json: 8 things named, each on its own line
    assert code == 0 and sum(ln.startswith("       - warning: ") for ln in lines) == 8
    assert lines[-1].startswith("GREEN with 8 warnings (nothing to run for: erc, drc, export): proj  report ")
    # with --report the line about the report comes first: a reader takes the verdict from the end
    code, text = text_of("gates", proj, "--out", tmp_path / "o", "--report", tmp_path / "docs" / "gates.md")
    lines = text.splitlines()
    assert lines[-2].startswith("wrote ") and lines[-1].startswith("GREEN with 8 warnings")
    assert "GREEN with 8 warnings (nothing to run for: erc, drc, export) on" in (
        tmp_path / "docs" / "gates.md"
    ).read_text(encoding="utf-8")


def test_a_count_of_jobs_under_zero_is_a_usage_error(tmp_path):
    proj = project(tmp_path, {"d": DIVIDER})
    command = [sys.executable, str(CLI), "sim", str(proj), "--jobs", "-1"]
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    assert proc.returncode == 2 and "Traceback" not in proc.stderr
    assert "argument --jobs: '-1' is not a count of jobs: a whole number, 0 or more" in proc.stderr


@needs_ngspice
def test_the_users_own_spiceinit_does_not_reach_a_corner(tmp_path):
    proj = project(tmp_path, {"d": DIVIDER}, {"d": {"vout": {"min": 2.4, "max": 2.6}}})
    (proj / "sim" / "corners.json").write_text(
        json.dumps({"tolerance": {"R": 0.01, "source": "x"}}), encoding="utf-8"
    )
    home = tmp_path / "home"
    home.mkdir()
    # were it read at a corner, the corner would print one more measure than the deck as written
    (home / ".spiceinit").write_text('echo "home_init = 1"\n', encoding="utf-8")
    code, records = run("sim", proj, "--out", tmp_path / "o", env={"HOME": str(home)})
    assert code == 0, records
    rows = json.loads((tmp_path / "o" / "sim" / "corners" / "d" / "runs.json").read_text(encoding="utf-8"))
    assert len(rows) == 12 and all(set(r["measures"]) == {"vout"} for r in rows)
