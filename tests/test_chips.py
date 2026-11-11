"""The fixture chips under tests/chips: the tests of the whole chip flow.

Each fixture is copied to a temporary folder and run through `workcenter chip gates`. A passing fixture
ends GREEN with --strict. A failing one ends RED at the gate its name states, for 1 reason, with every
gate before that one passing. The exit code, the last line and each failure line here are copied from
runs of 2026-11-11 with Verilator 5.020, Icarus Verilog 12.0, Yosys 0.33, OpenROAD f12e2f47, OpenSTA
2.3.1, Magic 8.3.465, Netgen 1.5.272, KLayout 0.28.16 and sky130A 1.0.470-0-g6d4d117. A test skips by
name where an engine or the process kit is absent.

Every run takes `--jobs 1`. With more jobs the benches of SIM write the ledger of hashes from several
threads at once, and entries are lost: of 30 runs of `chip sim --jobs 4` on pass-acc8 on 2026-11-11, 4
kept 2 or 4 of the 5 benches' entries and 1 left a ledger that is no JSON.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CHIPS = ROOT / "tests" / "chips"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import chipflow  # noqa: E402
from test_chipflow import CHIP, CLI, KIT, command  # noqa: E402

# What a run needs, by the last gate it reaches: each engine by its name, the process kit as "kit".
LINT = ("verilator",)
SIM = (*LINT, "iverilog", "vvp")
SYNTH = (*SIM, "yosys", "kit")
LAYOUT = (*SYNTH, "openroad", "magic")
STA = (*LAYOUT, "sta")
EVERY = (*STA, "klayout", "netgen")

NO_RESET = (
    "reset each, or name it in chip.json's answers.flops_without_reset with why and the bench that proves it"
)
# fixture: (what its run needs, the gate that fails, that gate's failure lines). 1 reason each: the 6
# lines of fail-sta-corner are the 6 slow corners, with no line for a typical or a fast corner, and the
# 2 of fail-glsim-x are the 2 measures that see a count that stays unknown.
FAILING = {
    "fail-lint-latch": (
        LINT,
        "lint",
        [
            "LATCH: rtl/counter.v:11:5: Latch inferred for signal 'counter.next' (not all control paths of "
            "combinational always assign a value)"
        ],
    ),
    "fail-lint-second-clock": (
        LINT,
        "lint",
        ["constraints.sdc: line 4: a second clock: the first flow takes 1 clock. Use 1 clock and an enable"],
    ),
    "fail-sim-spec": (SIM, "sim", ["tb_counter: errors=5 not in [None, 0]"]),
    "fail-synth-noreset": (SYNTH, "synth", [f"1 flops have no reset: en_q: {NO_RESET}"]),
    "fail-layout-area": (
        LAYOUT,
        "layout",
        [
            "utilisation 0.5223 is over the limit 0.5 of chip.json after the floorplan, before the clock "
            "tree adds cells: take a larger die, or cut logic. Do not raise the limit"
        ],
    ),
    "fail-sta-corner": (
        STA,
        "sta",
        [
            "max_ss_n40C_1v60: setup slack -0.5704 ns, from en to _49_",
            "max_ss_100C_1v60: setup slack -0.4918 ns, from en to _49_",
            "min_ss_n40C_1v60: setup slack -0.5220 ns, from en to _49_",
            "min_ss_100C_1v60: setup slack -0.4476 ns, from en to _49_",
            "nom_ss_n40C_1v60: setup slack -0.5473 ns, from en to _49_",
            "nom_ss_100C_1v60: setup slack -0.4704 ns, from en to _49_",
        ],
    ),
    "fail-glsim-x": (
        STA,
        "glsim",
        ["tb_counter: errors=8 not in [None, 0]", "tb_counter: x_outputs=266 not in [None, 0]"],
    ),
}
# The files in which a failing fixture differs from pass-counter: the ones that hold its fault, and for
# 2 of them the bench, which follows a counter that acts in another way.
DIFFERS = {
    "fail-lint-latch": ["rtl/counter.v"],
    "fail-lint-second-clock": ["constraints.sdc"],
    "fail-sim-spec": ["rtl/counter.v"],
    "fail-synth-noreset": ["rtl/counter.v", "tb/tb_counter.v"],
    "fail-layout-area": ["chip.json"],
    "fail-sta-corner": ["constraints.sdc"],
    "fail-glsim-x": ["chip.json", "rtl/counter.v", "tb/tb_counter.v"],
}
PASSING = ("pass-acc8", "pass-counter")
# Why the processor's run does not end GREEN yet; empty when it does. While this says something, the
# GREEN run is an expected failure and the README's row for pass-acc8 ends with RED.
ACC8_BLOCKED = (
    "the layout build repairs no slew: STA fails pass-acc8 at 13 of its 15 corners, the first with 477 "
    "pins over a limit of the library at max_ss_n40C_1v60 (2026-11-11: tools/chipscripts/layout.tcl holds "
    "no repair_design)"
)
# The checks each bench of the processor makes: 3 a program run, 2 for the run that is left in its
# middle, 1 a word of the random stream.
ACC8_CHECKS = {"tb_crc": 15, "tb_gcd": 24, "tb_mul": 18, "tb_random": 1024, "tb_sum": 17}


def absent(names: tuple[str, ...]) -> list[str]:
    """What a run needs and this machine does not have."""
    out = []
    for name in names:
        if name == "kit":
            if not KIT.is_dir():
                out.append("the sky130A process kit")
        elif not (CHIP / "bin" / name).exists() and shutil.which(name) is None:
            out.append(name)
    return out


def needs(names: tuple[str, ...]):
    missing = absent(names)
    return pytest.mark.skipif(bool(missing), reason=f"not installed: {', '.join(missing)}")


def copy_of(name: str, tmp_path: Path) -> Path:
    """A fresh copy of a fixture: what an earlier run in place left beside it stays behind."""
    project = tmp_path.resolve() / name
    shutil.copytree(CHIPS / name, project, ignore=shutil.ignore_patterns("build", "__pycache__"))
    return project


def run_fixture(name: str, tmp_path: Path, *flags: str) -> tuple[int, str, list[dict]]:
    """A copy of a fixture through `chip gates`: (the exit code, the last line, the gates' records)."""
    project = copy_of(name, tmp_path)
    ran = command("chip", "gates", project, "--jobs", 1, *flags)
    lines = ran.stdout.splitlines()
    assert lines, ran.stderr
    records = json.loads((project / "build" / "gates.json").read_text(encoding="utf-8"))
    return ran.returncode, lines[-1], records


def last_line(verdict: str, name: str, tmp_path: Path) -> str:
    return f"{verdict}: {name}  report {tmp_path.resolve() / name / 'build' / 'gates.json'}"


def all_pass(records: list[dict]) -> None:
    failed = [f"{r['gate']}: {line}" for r in records for line in r["details"].get("failures", [])]
    assert failed == []
    assert [(r["gate"], r["status"]) for r in records] == [(gate, "pass") for gate in chipflow.GATE_NAMES]
    assert [r["details"]["warnings"] for r in records] == [[]] * len(chipflow.GATE_NAMES)


# ------------------------------------------------------------ with no engine


def test_every_fixture_has_its_row_in_the_readme_and_its_test_here():
    names = sorted(p.name for p in CHIPS.iterdir() if p.is_dir() and p.name != "samples")
    assert names == sorted([*PASSING, *FAILING]), "a fixture folder with no test, or a test with no folder"
    for name, (_, gate, _) in FAILING.items():
        assert name.split("-")[1] == gate and gate in chipflow.GATE_NAMES, name
    text = (CHIPS / "README.md").read_text(encoding="utf-8")
    rows = re.findall(r"^\| `((?:pass|fail)-[a-z0-9-]+)` \| (.*) \| `([^`]+)` \|$", text, re.M)
    assert sorted(name for name, _, _ in rows) == names, "1 row for each fixture, its name as code"
    for name, proves, ends in rows:
        red = name in FAILING or (name == "pass-acc8" and bool(ACC8_BLOCKED))
        assert ends == f"{'RED' if red else 'GREEN'}: {name}  report <project>/build/gates.json", name
        if name in FAILING:
            # the row quotes the gate's first failure line as the run prints it
            assert f"`{FAILING[name][2][0]}`" in proves, name


def test_a_failing_fixture_is_the_passing_counter_but_for_the_files_of_its_fault():
    def files(name: str) -> dict[str, bytes]:
        folder = CHIPS / name
        found = [p for p in folder.rglob("*") if p.is_file() and "build" not in p.parts]
        return {str(p.relative_to(folder)): p.read_bytes() for p in found}

    passing = files("pass-counter")
    assert sorted(DIFFERS) == sorted(FAILING)
    for name, changed in DIFFERS.items():
        failing = files(name)
        # no failing fixture has a mutation list: SIM names its absence as a warning
        assert sorted(set(passing) ^ set(failing)) == ["rtl/mutations.json"], name
        assert sorted(f for f in failing if failing[f] != passing[f]) == changed, name


def test_the_processors_generated_files_are_what_its_programs_and_model_give(tmp_path):
    def check(folder: Path, what: str) -> tuple[int, str]:
        ran = subprocess.run(
            [sys.executable, "-B", str(folder / "acc8.py"), what, "--check"],
            capture_output=True,
            text=True,
            check=False,
        )
        return ran.returncode, ran.stdout.strip()

    fixture = CHIPS / "pass-acc8"
    assert check(fixture, "rom") == (0, "PASS rom: acc8_rom.v is what programs/rom.list gives")
    assert check(fixture, "stim") == (0, "PASS stim: random_stim.vh is what the model gives")
    # each check can fail: a program changed after the ROM was written, a stream edited by hand
    project = copy_of("pass-acc8", tmp_path)
    program = project / "programs" / "sum.asm"
    text = program.read_text(encoding="utf-8")
    assert "ADD  #1" in text
    program.write_text(text.replace("ADD  #1", "ADD  #2"), encoding="utf-8")
    assert check(project, "rom") == (
        1,
        "FAIL rom: acc8_rom.v is not what programs/rom.list gives; run `python3 acc8.py rom`",
    )
    with (project / "tb" / "random_stim.vh").open("a", encoding="utf-8") as fh:
        fh.write("        step(21'h000000, 18'h00000);\n")
    assert check(project, "stim") == (
        1,
        "FAIL stim: random_stim.vh is not what the model gives; run `python3 acc8.py stim`",
    )


# ------------------------------------------------------- the failing fixtures


@pytest.mark.parametrize("name", [pytest.param(name, marks=needs(FAILING[name][0])) for name in FAILING])
def test_a_failing_fixture_fails_its_1_gate_with_every_gate_before_it_passing(name, tmp_path):
    _, gate, lines = FAILING[name]
    code, last, records = run_fixture(name, tmp_path)
    before = chipflow.GATE_NAMES[: chipflow.GATE_NAMES.index(gate)]
    assert [(r["gate"], r["status"]) for r in records] == [*[(g, "pass") for g in before], (gate, "fail")]
    assert records[-1]["details"]["failures"] == lines
    assert code == 1
    assert last == last_line("RED", name, tmp_path)
    if name == "fail-glsim-x":
        # the RTL run hides it: the same bench passes in SIM with the same count of checks
        assert records[1]["details"]["benches"] == {"tb_counter": {"errors": 0, "checks": 8, "x_outputs": 0}}


# ------------------------------------------------------- the passing fixtures


@needs(EVERY)
def test_the_passing_counter_is_green_with_strict_and_hands_on_the_gds_its_gates_judged(tmp_path):
    code, last, records = run_fixture("pass-counter", tmp_path, "--strict")
    all_pass(records)
    assert code == 0
    assert last == last_line("GREEN", "pass-counter", tmp_path)
    by_gate = {r["gate"]: r["details"] for r in records}
    measures = {"tb_counter": {"errors": 0, "checks": 8, "x_outputs": 0}}
    assert by_gate["sim"]["benches"] == by_gate["glsim"]["benches"] == measures
    assert (by_gate["synth"]["cells"], by_gate["synth"]["flops"]) == (31, 8)
    out = tmp_path.resolve() / "pass-counter" / "build" / "chip"
    manifest = json.loads((out / "tapeout" / "manifest.json").read_text(encoding="utf-8"))
    built = chipflow.sha256(out / "layout" / "counter.gds")
    assert manifest["files"]["counter.gds"] == built == chipflow.sha256(out / "tapeout" / "counter.gds")
    assert by_gate["drc"]["gds_sha256"] == built


@needs(SYNTH)
def test_the_processor_passes_lint_sim_and_synth_with_strict(tmp_path):
    project = copy_of("pass-acc8", tmp_path)
    details = {}
    for gate in ("lint", "sim", "synth"):
        ran = command("--json", "chip", gate, project, "--jobs", 1, "--strict")
        assert ran.returncode == 0, ran.stdout
        details[gate] = json.loads(ran.stdout)[0]["details"]
    assert details["sim"]["benches"] == {
        bench: {"errors": 0, "checks": checks, "x_outputs": 0} for bench, checks in ACC8_CHECKS.items()
    }
    synth = details["synth"]
    # the 2 top bits of the program counter take the boot pins at reset: chip.json answers for both
    assert (synth["cells"], synth["flops"]) == (770, 156)
    assert synth["flops_without_reset"] == ["rom_addr[6]", "rom_addr[7]"]


@needs(EVERY)
def test_the_processor_is_green_with_strict(tmp_path):
    code, last, records = run_fixture("pass-acc8", tmp_path, "--strict")
    if ACC8_BLOCKED:
        # Only the fault ACC8_BLOCKED names is excused: the run reaches STA with every gate before it
        # passing, and each of STA's 13 lines is a count of pins over a slew or a capacitance limit. A
        # run that stops elsewhere, or that goes on, fails here; when it goes on to GREEN, empty
        # ACC8_BLOCKED and change the row.
        assert [(r["gate"], r["status"]) for r in records] == [
            ("lint", "pass"),
            ("sim", "pass"),
            ("synth", "pass"),
            ("layout", "pass"),
            ("sta", "fail"),
        ]
        failures = records[-1]["details"]["failures"]
        over = " pins break a limit of the library or the constraints "
        kinds = ("(max slew, max capacitance): ", "(max capacitance): ")
        assert len(failures) == 13, failures
        assert all(line.partition(over)[2].startswith(kinds) for line in failures), failures
        assert failures[0].startswith(f"max_ss_n40C_1v60: 477{over}{kinds[0]}_1013_/Y ")
        assert (code, last) == (1, last_line("RED", "pass-acc8", tmp_path))
        pytest.xfail(ACC8_BLOCKED)
    all_pass(records)
    assert code == 0
    assert last == last_line("GREEN", "pass-acc8", tmp_path)


@pytest.mark.parametrize(("name", "mutations", "checks"), [("pass-counter", 5, 8), ("pass-acc8", 18, 1098)])
@needs(SIM)
def test_every_mutation_of_a_passing_fixture_is_caught_by_a_comparison(name, mutations, checks):
    fixture = CHIPS / name
    sim = shlex.join([sys.executable, str(CLI), "chip", "sim", ".", "--jobs", "1"])
    ran = command("mutate", fixture, "--mutations", fixture / "rtl" / "mutations.json", "--test", sim)
    lines = ran.stdout.splitlines()
    assert ran.returncode == 0, ran.stdout + ran.stderr
    assert lines[-1].startswith(f"mutate: {mutations} mutations, {mutations} caught, 0 survived, 0 did not ")
    # A mutant that does not compile fails the gate too, and `mutate` counts it as caught. Each of these
    # ran every check of every bench: a comparison caught it.
    caught = [line for line in lines if line.startswith("caught ")]
    assert len(caught) == mutations and all(f" {checks} checks, " in line for line in caught), caught
