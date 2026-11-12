"""The fixture chips under tests/chips: the tests of the whole chip flow.

Each fixture is copied to a temporary folder and run through `workcenter chip gates`. A passing fixture
ends GREEN with --strict. A failing one ends RED at the gate its name states, for 1 reason, with every
gate before that one passing. The exit code, the last line and each failure line here are copied from
runs of 2026-11-12 with Verilator 5.020, Icarus Verilog 12.0, Yosys 0.33, OpenROAD f12e2f47, OpenSTA
2.3.1, Magic 8.3.465, Netgen 1.5.272, KLayout 0.28.16 and sky130A 1.0.470-0-g6d4d117. A test skips by
name where an engine or the process kit is absent.

Every run takes the default of `--jobs`: the machine's processors, 8 at most. The count changes the
seconds and not the layout: 5 builds of the processor at 1, 2, 4 and 8 jobs wrote the same GDS.
"""

from __future__ import annotations

import json
import re
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
from test_chipflow import CHIP, KIT, command  # noqa: E402

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
            "utilisation 0.6451 is over the limit 0.5 of chip.json after the floorplan, before the clock "
            "tree adds cells: take a larger die, or cut logic. Do not raise the limit"
        ],
    ),
    "fail-sta-corner": (
        STA,
        "sta",
        [
            "max_ss_n40C_1v60: setup slack -0.3277 ns, from _49_ to count[3]",
            "max_ss_100C_1v60: setup slack -0.3229 ns, from en to _45_",
            "min_ss_n40C_1v60: setup slack -0.2887 ns, from _49_ to count[3]",
            "min_ss_100C_1v60: setup slack -0.3113 ns, from en to _45_",
            "nom_ss_n40C_1v60: setup slack -0.3070 ns, from _49_ to count[3]",
            "nom_ss_100C_1v60: setup slack -0.3184 ns, from en to _45_",
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
# The checks each bench of the processor makes: 3 a program run, 2 for the run that is left in its
# middle, 1 a word of the random stream.
ACC8_CHECKS = {"tb_crc": 15, "tb_gcd": 24, "tb_mul": 18, "tb_random": 1024, "tb_sum": 17}
# The processor's layout of 2026-11-12, the same at 1, 2, 4 and 8 jobs: the first 16 digits of its GDS hash.
ACC8_GDS = "0c51debe623a0a18"


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
    ran = command("chip", "gates", project, *flags)
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
        verdict = "RED" if name in FAILING else "GREEN"
        assert ends == f"{verdict}: {name}  report <project>/build/gates.json", name
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
    if name == "fail-sta-corner":
        # the build's repair names the period first, as a warning: LAYOUT passes and STA is the judge
        assert records[3]["details"]["warnings"] == [
            "[WARNING RSZ-0062] Unable to repair all setup violations."
        ]


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
    assert (by_gate["synth"]["cells"], by_gate["synth"]["flops"]) == (29, 8)
    out = tmp_path.resolve() / "pass-counter" / "build" / "chip"
    manifest = json.loads((out / "tapeout" / "manifest.json").read_text(encoding="utf-8"))
    built = chipflow.sha256(out / "layout" / "counter.gds")
    assert manifest["files"]["counter.gds"] == built == chipflow.sha256(out / "tapeout" / "counter.gds")
    assert by_gate["drc"]["gds_sha256"] == built


@needs(SYNTH)
def test_the_processor_passes_lint_sim_and_synth_with_strict(tmp_path):
    project = copy_of("pass-acc8", tmp_path)
    details, summary = {}, {}
    for gate in ("lint", "sim", "synth"):
        ran = command("--json", "chip", gate, project, "--strict")
        assert ran.returncode == 0, ran.stdout
        record = json.loads(ran.stdout)[0]
        details[gate], summary[gate] = record["details"], record["summary"]
    assert details["sim"]["benches"] == {
        bench: {"errors": 0, "checks": checks, "x_outputs": 0} for bench, checks in ACC8_CHECKS.items()
    }
    synth = details["synth"]
    # the 2 top bits of the program counter take the boot pins at reset: chip.json answers for both
    assert synth["flops_without_reset"] == ["rom_addr[6]", "rom_addr[7]"]
    # With these 4 programs in the ROM nothing reads r6, r9 and r10: the mapping proves it and removes
    # their 24 flops. The count is the netlist's, and the line says where the others went.
    assert (synth["cells"], synth["flops"], synth["flops_before_mapping"]) == (760, 132, 156)
    assert synth["flops_removed_by_mapping"] == [
        f"u_core.u_regfile.q[{bit}]" for bit in (*range(48, 56), *range(72, 88))
    ]
    assert summary["synth"] == (
        "760 cells, 132 flops, 8530.7 um2, the mapping removed 24 flops that nothing reads "
        "(--json names each), 0 failures"
    )


@needs(EVERY)
def test_the_processor_is_green_with_strict_and_its_layout_is_the_one_of_the_readme(tmp_path):
    code, last, records = run_fixture("pass-acc8", tmp_path, "--strict")
    all_pass(records)
    assert code == 0
    assert last == last_line("GREEN", "pass-acc8", tmp_path)
    by_gate = {r["gate"]: r["details"] for r in records}
    checks = {bench: {"errors": 0, "checks": n, "x_outputs": 0} for bench, n in ACC8_CHECKS.items()}
    assert by_gate["sim"]["benches"] == checks
    # tb_random drives the core alone: chip.json keeps it on the RTL, and the 4 others run on the netlist
    assert sorted(by_gate["glsim"]["rtl_only"]) == ["tb_random"]
    assert by_gate["glsim"]["benches"] == {b: m for b, m in checks.items() if b != "tb_random"}
    assert (by_gate["synth"]["cells"], by_gate["synth"]["flops"]) == (760, 132)
    layout = by_gate["layout"]
    assert (layout["area_um2"], layout["utilization"]) == (8379.29, 0.493)
    assert (layout["router_violations"], layout["open_pins"], layout["dont_use_cells"]) == (0, 0, 0)
    # the build repaired what round 1 left: no corner has a pin over a limit, and the least slacks are
    # the README's
    corners = by_gate["sta"]["corners"]
    assert len(corners) == 15
    assert min(c["setup_slack_ns"] for c in corners.values()) == corners["max_ss_n40C_1v60"]["setup_slack_ns"]
    assert corners["max_ss_n40C_1v60"]["setup_slack_ns"] == 25.1717
    assert min(c["hold_slack_ns"] for c in corners.values()) == corners["min_ff_n40C_1v95"]["hold_slack_ns"]
    assert corners["min_ff_n40C_1v95"]["hold_slack_ns"] == 0.2974
    assert by_gate["drc"]["decks"] == {"magic": 0, "klayout-mr": 0}
    assert (by_gate["antenna"]["net_violations"], by_gate["antenna"]["pin_violations"]) == (0, 0)
    assert by_gate["lvs"]["devices"] == {"layout": 792, "netlist": 792}
    # 1 layout from these files on any count of jobs: the hash every judge passed is the hash handed out
    out = tmp_path.resolve() / "pass-acc8" / "build" / "chip"
    manifest = json.loads((out / "tapeout" / "manifest.json").read_text(encoding="utf-8"))
    built = chipflow.sha256(out / "layout" / "acc8.gds")
    assert built.startswith(ACC8_GDS)
    assert manifest["files"]["acc8.gds"] == built == chipflow.sha256(out / "tapeout" / "acc8.gds")
    assert by_gate["drc"]["gds_sha256"] == built


@pytest.mark.parametrize(
    ("name", "benches", "checks", "changes"), [("pass-counter", 1, 8, 5), ("pass-acc8", 5, 1098, 18)]
)
@needs(SIM)
def test_sim_proves_each_change_of_a_passing_fixtures_list(name, benches, checks, changes, tmp_path):
    """SIM makes each change of rtl/mutations.json in a copy of the RTL and runs the benches on it. Each
    change here compiles, and a bench's own measure catches it: a count of errors, and for the change
    that leaves the output port out of the reset a count of unknown outputs. No compile failed, and no
    bench was stopped."""
    project = copy_of(name, tmp_path)
    ran = command("--json", "chip", "sim", project, "--strict")
    record = json.loads(ran.stdout)[0]
    assert ran.returncode == 0, record["details"]["failures"]
    assert record["summary"] == (
        f"{benches} benches, {checks} checks, {changes} of {changes} changes of the RTL caught, 0 failures"
    )
    proven = record["details"]["mutations"]
    listed = json.loads((project / "rtl" / "mutations.json").read_text(encoding="utf-8"))["mutations"]
    assert list(proven) == [change["name"] for change in listed] and len(proven) == changes
    assert {entry["state"] for entry in proven.values()} == {"caught"}
    by = {change: entry["by"] for change, entry in proven.items()}
    unknown = by.pop("reset-leaves-out-port", None)
    assert unknown == (None if name == "pass-counter" else "tb_crc: x_outputs=73 not in [None, 0]")
    assert all(re.fullmatch(r"tb_\w+: errors=\d+ not in \[None, 0\]", line) for line in by.values()), by
    # the copies are under the output folder, and the project is as it was
    assert sorted(p.name for p in (project / "build" / "chip" / "sim" / "mutants").iterdir()) == [
        f"{n:03d}" for n in range(1, changes + 1)
    ]
