"""The front chip gates (tools/chipfront.py): LINT, SIM, SYNTH and GLSIM.

First the judges, on real reports of the engines kept in tests/chips/samples/front/ (paths rewritten to
/work and /kit): these run on every machine. Then each gate on a project made from the template, with
the engine itself; those skip by name where the engine is absent.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "tests" / "chips" / "samples" / "front"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import chipflow  # noqa: E402
import chipfront  # noqa: E402
from test_chipflow import KIT, command, fill  # noqa: E402

needs_verilator = pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator is not installed")
needs_iverilog = pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog is not installed")
needs_synth = pytest.mark.skipif(
    shutil.which("yosys") is None or not KIT.is_dir(),
    reason="yosys or the sky130A process kit is not installed",
)
NO_RESET = (
    "reset each, or name it in chip.json's answers.flops_without_reset with why and the bench that proves it"
)
PRINT_THEM = "print errors, checks and x_outputs as `name = value`"


def sample(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


def started(text: str, code: int | None = 0, engine: str = "vvp") -> chipflow.Started:
    return chipflow.Started([engine], code, False, 0.1, 600, Path("run.log"), text)


def cells() -> dict:
    return chipflow.read_table("sky130A")[0]["libraries"]["sky130_fd_sc_hd"]["cells"]


# ------------------------------------------------------------- the judges: LINT


def test_verilator_classes_that_silicon_reads_another_way_fail_and_an_error_fails():
    failures, warnings = chipfront.judge_lint(sample("verilator-latch-width-undriven.log"))
    assert failures == [
        "WIDTHTRUNC: /work/reg8/rtl/reg8.v:16:16: Operator ASSIGNDLY expects 4 bits on the Assign RHS, but "
        "Assign RHS's VARREF 'd' generates 8 bits.",
        "UNDRIVEN: /work/reg8/rtl/reg8.v:7:23: Signal is not driven: 'loose'",
        "LATCH: /work/reg8/rtl/reg8.v:11:5: Latch inferred for signal 'reg8.held' (not all control paths of "
        "combinational always assign a value)",
    ]
    assert warnings == []
    assert chipfront.judge_lint(sample("verilator-clean.log")) == ([], [])
    # an error has no class; the line that only counts the errors is left out
    assert chipfront.judge_lint(sample("verilator-syntax-error.log")) == (
        ["/work/reg8/rtl/reg8.v:2:3: syntax error, unexpected assign, expecting ';'"],
        [],
    )
    # a class outside the list is a warning, with its class first
    other = "%Warning-UNUSEDSIGNAL: /work/reg8/rtl/reg8.v:9:10: Signal is not used: 'spare'\n"
    assert chipfront.judge_lint(other) == (
        [],
        ["UNUSEDSIGNAL: /work/reg8/rtl/reg8.v:9:10: Signal is not used: 'spare'"],
    )
    assert set(chipfront.LINT_FAIL) >= {
        "LATCH",
        "MULTIDRIVEN",
        "UNOPTFLAT",
        "UNDRIVEN",
        "WIDTHTRUNC",
        "BLKANDNBLK",
    }


def test_the_top_modules_ports_are_read_from_verilators_xml():
    assert chipfront.top_ports(sample("verilator-ports.xml"), "reg8") == {
        "clk": "input",
        "rst": "input",
        "en": "input",
        "d": "input",
        "q": "output",
    }
    assert chipfront.top_ports("<not xml", "reg8") is None


def test_a_comment_that_turns_off_a_failing_class_is_a_failure(tmp_path):
    """Verilator obeys `lint_off` and prints nothing: a latch behind one passes its report."""
    (tmp_path / "rtl").mkdir()
    rtl = tmp_path / "rtl" / "a.v"
    rtl.write_text(
        "module a;\n  /* verilator lint_off LATCH */\n  // verilator lint_off UNUSEDSIGNAL\nendmodule\n",
        encoding="utf-8",
    )
    assert chipfront.lint_off([rtl], tmp_path) == [
        "rtl/a.v:2: lint_off LATCH turns off a class this gate fails on: remove the comment and change the "
        "code"
    ]


# ------------------------------------------------------------- the judges: a bench


def test_a_bench_passes_with_its_3_measures_and_fails_on_each_of_them():
    ok = started("", engine="iverilog")
    assert chipfront.judge_bench("tb_reg8", ok, started(sample("vvp-pass.log")), {}) == (
        [],
        [],
        {"errors": 0.0, "checks": 4.0, "x_outputs": 0.0},
    )
    assert chipfront.judge_bench("tb_reg8", ok, started(sample("vvp-errors.log")), {})[0] == [
        "tb_reg8: errors=1 not in [None, 0]"
    ]
    # a flop with no reset drives the output: 1 clock edge after reset release shows an unknown value
    assert chipfront.judge_bench("tb_reg8", ok, started(sample("vvp-x-output.log")), {})[0] == [
        "tb_reg8: errors=1 not in [None, 0]",
        "tb_reg8: x_outputs=1 not in [None, 0]",
    ]
    assert chipfront.judge_bench("tb_reg8", ok, started(sample("vvp-no-finish.log")), {})[0] == [
        "tb_reg8: does not reach $finish: end the bench with $finish after its last check"
    ]
    assert chipfront.judge_bench("tb_reg8", ok, started(sample("vvp-no-measures.log")), {})[0] == [
        f"tb_reg8: does not print checks: {PRINT_THEM}",
        f"tb_reg8: does not print x_outputs: {PRINT_THEM}",
    ]
    # a bench that checks nothing proves nothing
    idle = "errors = 0\nchecks = 0\nx_outputs = 0\ntb.v:9: $finish called at 10 (1ps)\n"
    assert chipfront.judge_bench("tb_reg8", ok, started(idle), {})[0] == [
        "tb_reg8: checks=0 not in [1, None]"
    ]


def test_a_bench_that_does_not_compile_or_ends_with_stop_fails():
    no_root = chipflow.Started(
        ["iverilog"], 1, False, 0.1, 600, Path("compile.log"), sample("iverilog-no-root.log")
    )
    assert chipfront.judge_bench("tb_reg8", no_root, None, {}) == (
        [
            'tb_reg8: does not compile: error: Unable to find the root module "tb_reg8" in the Verilog '
            "source.: name the bench's module as its file, tb_reg8"
        ],
        [],
        {},
    )
    ok = started("", engine="iverilog")
    # vvp -N ends with exit code 1 on a $stop
    assert chipfront.judge_bench("tb_reg8", ok, started("errors = 0\n", 1), {})[0] == [
        "tb_reg8: vvp exit 1 (log run.log)"
    ]
    warned = started(
        "/work/reg8/tb/tb_reg8.v:9: warning: implicit definition of wire 'x'.\n", engine="iverilog"
    )
    assert chipfront.judge_bench("tb_reg8", warned, started(sample("vvp-pass.log")), {})[1] == [
        "tb_reg8: /work/reg8/tb/tb_reg8.v:9: warning: implicit definition of wire 'x'."
    ]


def test_a_benchs_own_bounds_hold_at_every_value_it_prints():
    ok = started("", engine="iverilog")
    text = sample("vvp-pass.log") + "last_q = 61\nlast_q = 60\n"
    expect = {"last_q": {"min": 60, "max": 60, "source": "0x3C"}, "other": {"max": 1}}
    failures, _, measures = chipfront.judge_bench("tb_reg8", ok, started(text), expect)
    # The first value misses and the last holds. A name printed 2 times with 2 values is judged on
    # each: a bench that prints a good value last does not hide the one before it.
    assert failures == [
        "tb_reg8: last_q=61 not in [60, 60] (0x3C)",
        "tb_reg8: other has a bound in tb_reg8.expect.json and the bench does not print it",
    ]
    assert measures["last_q"] == 60.0
    assert chipfront.bench_measures("a = 1\n b = -2.5e3 \nc = x\nnot a measure\n") == {
        "a": [1.0],
        "b": [-2500.0],
    }


# ----------------------------------------------------------- the judges: SYNTH


def synth(name: str, answers: tuple = ()) -> tuple[list[str], list[str], dict]:
    folder = SAMPLES / name

    def text(part: str) -> str:
        return (folder / part).read_text(encoding="utf-8") if (folder / part).is_file() else ""

    def data(part: str) -> dict | None:
        return json.loads(text(part)) if text(part) else None

    return chipfront.judge_synth(
        text("console.log"),
        text("check_generic.txt"),
        text("check.txt"),
        data("stat.json"),
        data("generic.json"),
        text("reg8.v") or None,
        "reg8",
        cells(),
        list(answers),
    )


def test_a_design_that_maps_onto_the_library_passes_with_its_counts():
    """The template's register: 8 flops with a synchronous reset and an enable. The library has no flop
    with a synchronous reset, so each is a plain flop and 2 gates; Yosys still names it by its reset
    before the library's cells replace it, and the judge reads it there."""
    failures, warnings, details = synth("yosys-ok")
    assert (failures, warnings) == ([], [])
    assert (details["cells"], details["flops"], details["flops_without_reset"]) == (24, 8, [])
    assert details["cells_by_type"] == {
        "sky130_fd_sc_hd__dfxtp_1": 8,
        "sky130_fd_sc_hd__mux2i_1": 8,
        "sky130_fd_sc_hd__nor2_1": 8,
    }
    assert details["area_um2"] == pytest.approx(270.2592)


def test_a_latch_an_open_net_a_loop_and_2_drivers_each_fail_synthesis():
    failures, warnings, details = synth("yosys-latch")
    assert warnings == []
    assert failures == [
        "check: Cell reg8.$auto$ff.cc:266:slice$100 is an unmapped internal cell of type $_DLATCH_P_. (and 7 "
        "more like it)",
        "check: Wire reg8.\\loose is used but has no driver.",
        "8 cells are not of the library: $_DLATCH_P_",
        "8 latch bits: held[0], held[1], held[2], held[3], held[4], held[5] ...: assign the signal in every "
        "branch",
        f"12 flops have no reset: narrow[0], narrow[1], narrow[2], narrow[3], q[0], q[1] ...: {NO_RESET}",
        "the netlist ties inputs to 1'bx with no tie cell: a net there has no driver, or holds an unknown "
        "value",
    ]
    assert details["flops"] == 12
    # the mapping hides a loop inside 1 cell: only the check before it sees the loop
    assert "Found and reported 0 problems." in (SAMPLES / "yosys-loop" / "check.txt").read_text(
        encoding="utf-8"
    )
    assert synth("yosys-loop")[0] == [
        "check: found logic loop in module reg8: cell $abc$82$auto$blifparse.cc:386:parse_blif$84 ($_NOR_); "
        "cell $abc$82$auto$blifparse.cc:386:parse_blif$85 ($_ANDNOT_); wire $abc$82$new_n5_"
    ]
    assert synth("yosys-two-drivers")[0] == [
        "check: multiple conflicting drivers for reg8.\\a: module input a[0]; module input b[0]"
    ]


def test_a_flop_with_no_reset_needs_an_answer_and_an_answer_needs_a_flop():
    assert synth("yosys-no-reset")[0] == [f"1 flops have no reset: q: {NO_RESET}"]
    answer = {"match": "q", "why": "loaded before it is read", "evidence": "tb_reg8"}
    assert synth("yosys-no-reset", (answer,))[0] == []
    spare = {"match": "sr_*", "why": "a shift register", "evidence": "tb_reg8"}
    assert synth("yosys-no-reset", (answer, spare))[0] == [
        "chip.json: answers.flops_without_reset: 'sr_*' matches no flop without a reset: remove it"
    ]
    # a pattern reads as it looks: brackets are brackets, and a name with no index is every bit of it
    pairs = [("q[*]", "q[0]"), ("q", "q[7]"), ("core.pc*", "core.pc[3]"), ("q?", "q1")]
    assert all(chipfront.names(pattern, bit) for pattern, bit in pairs)
    assert not any(chipfront.names(p, b) for p, b in [("q", "qq[0]"), ("q[1]", "q[11]"), ("sr_*", "q[0]")])


def test_yosys_stopping_before_its_reports_is_a_failure_not_an_empty_pass():
    failures, _, details = chipfront.judge_synth(
        "ERROR: Module `\\reg9' not found!\n", "", "", None, None, None, "reg8", cells(), []
    )
    assert failures == [
        "ERROR: Module `\\reg9' not found!",
        "check wrote no count before the library's cells: Yosys stopped before it",
        "check wrote no count after them: Yosys stopped before it",
    ]
    assert details == {}
    # with no error named and no netlist either, the absence is the failure
    console = "Found and reported 0 problems.\n"
    assert chipfront.judge_synth("", console, console, None, None, None, "reg8", cells(), [])[0] == [
        "Yosys wrote no netlist: its log says where it stopped"
    ]


# -------------------------------------------------------- the gates, with engines


def a_project(tmp_path: Path, name: str = "reg8") -> Path:
    folder = tmp_path / name
    assert command("chip", "init", folder, "--top", "reg8").returncode == 0
    fill(folder)
    return folder


def gate(name: str, folder: Path, *flags: object) -> tuple[int, dict]:
    ran = command("--json", "chip", name, folder, *flags)
    return ran.returncode, json.loads(ran.stdout)[0]


def swap(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new), encoding="utf-8")


LATCHED = """module reg8 (
    input  wire       clk,
    input  wire       sel,
    input  wire [7:0] d,
    output reg  [7:0] q,
    output wire       loose
);
    reg [7:0] held;
    always @(*) begin
        if (sel) held = d;
    end
    always @(posedge clk) q <= held;
endmodule
"""


@needs_verilator
def test_lint_passes_the_template_and_fails_a_latch_a_lint_off_and_an_open_port(tmp_path):
    folder = a_project(tmp_path)
    code, record = gate("lint", folder)
    assert (code, record["status"], record["summary"]) == (0, "pass", "1 RTL files, top reg8, 0 failures")
    assert record["details"]["clock"] == {"port": "clk", "name": "clk", "period_ns": 20.0}
    assert record["details"]["ports"] == {
        "clk": "input",
        "rst": "input",
        "en": "input",
        "d": "input",
        "q": "output",
    }
    # nothing is written into the project
    assert sorted(p.name for p in folder.iterdir()) == [
        ".gitignore",
        "README.md",
        "build",
        "chip.json",
        "constraints.sdc",
        "rtl",
        "tb",
    ]
    (folder / "rtl" / "reg8.v").write_text(LATCHED, encoding="utf-8")
    code, record = gate("lint", folder)
    assert code == 1 and record["details"]["failures"] == [
        "UNDRIVEN: rtl/reg8.v:6:23: Signal is not driven: 'loose'",
        "LATCH: rtl/reg8.v:9:5: Latch inferred for signal 'reg8.held' (not all control paths of "
        "combinational always assign a value)",
    ]
    swap(
        folder / "rtl" / "reg8.v",
        "    always @(*) begin",
        "    /* verilator lint_off LATCH */\n    always @(*) begin",
    )
    swap(folder / "rtl" / "reg8.v", "    output wire       loose\n", "    output wire       loose\n")
    code, record = gate("lint", folder)
    assert code == 1 and (
        "rtl/reg8.v:9: lint_off LATCH turns off a class this gate fails on: remove the comment and change "
        "the code" in record["details"]["failures"]
    )
    assert not any(line.startswith("LATCH") for line in record["details"]["failures"])


@needs_verilator
def test_lint_holds_the_constraints_to_the_ports_and_skips_with_no_rtl(tmp_path):
    folder = a_project(tmp_path)
    swap(folder / "constraints.sdc", "{rst en d[*]}", "{rst en}")
    code, record = gate("lint", folder)
    assert code == 1 and record["details"]["failures"] == [
        "constraints.sdc: input d has no set_input_delay: STA cannot judge a path through it"
    ]
    swap(folder / "constraints.sdc", "[get_ports clk] ;#", "[get_ports clock] ;#")
    code, record = gate("lint", folder)
    assert (
        "constraints.sdc: create_clock names the port clock, and reg8 has no input of that name"
        in (record["details"]["failures"])
    )
    (folder / "rtl" / "reg8.v").unlink()
    ran = command("chip", "lint", folder)
    assert ran.returncode == 2
    assert ran.stdout.splitlines()[-1] == (
        "SKIPPED (LINT: chip.json names top reg8 and no file matches its rtl patterns: write the RTL): reg8"
    )


@needs_iverilog
def test_sim_passes_the_template_and_names_what_a_bench_shows(tmp_path):
    folder = a_project(tmp_path)
    code, record = gate("sim", folder)
    assert (code, record["status"]) == (0, "pass")
    assert record["summary"] == "1 benches, 4 checks, 0 failures, 1 warnings"
    assert record["details"]["benches"] == {"tb_reg8": {"errors": 0.0, "checks": 4.0, "x_outputs": 0.0}}
    assert record["details"]["warnings"][0].startswith(
        "no rtl/mutations.json: nothing shows that the benches can fail"
    )
    measures = folder / "build" / "chip" / "sim" / "tb_reg8" / "measures.json"
    assert json.loads(measures.read_text(encoding="utf-8")) == {
        "checks": 4.0,
        "errors": 0.0,
        "x_outputs": 0.0,
    }
    # with a mutation list the warning is gone, and --strict passes
    (folder / "rtl" / "mutations.json").write_text("[]", encoding="utf-8")
    assert gate("sim", folder, "--strict")[0] == 0
    # the RTL ignores its enable: 1 comparison fails
    swap(folder / "rtl" / "reg8.v", "else if (en) q <= d;", "else q <= d;")
    code, record = gate("sim", folder)
    assert code == 1 and record["details"]["failures"] == ["tb_reg8: errors=1 not in [None, 0]"]
    # with the enable back, the reset no longer resets: the register keeps its unknown start, and the
    # output is unknown at the first edge after the reset's release
    swap(folder / "rtl" / "reg8.v", "else q <= d;", "else if (en) q <= d;")
    swap(folder / "rtl" / "reg8.v", "if (rst) q <= 8'd0;", "if (rst) q <= q;")
    code, record = gate("sim", folder)
    assert record["details"]["failures"] == [
        "tb_reg8: errors=1 not in [None, 0]",
        "tb_reg8: x_outputs=1 not in [None, 0]",
    ]


@needs_iverilog
def test_sim_fails_a_bench_that_never_ends_or_is_not_there(tmp_path):
    stopped = a_project(tmp_path, "stopped")
    swap(stopped / "tb" / "tb_reg8.v", "        $finish;\n", "        $stop;\n")
    code, record = gate("sim", stopped)
    # a $stop is no $finish: the run ends with exit code 1, where `vvp -n` would call it finished
    assert code == 1 and record["details"]["failures"] == [
        "tb_reg8: vvp exit 1 (log build/chip/sim/tb_reg8/run.log)"
    ]
    folder = a_project(tmp_path)
    swap(folder / "tb" / "tb_reg8.v", "        $finish;\n", "")
    code, record = gate("sim", folder, "--timeout", 2)
    log = folder / "build" / "chip" / "sim" / "tb_reg8" / "run.log"
    assert code == 1 and record["details"]["failures"] == [
        f"tb_reg8: vvp passed its time limit of 2 s and was stopped (log {log.relative_to(folder)})"
    ]
    swap(folder / "tb" / "tb_reg8.v", "module tb_reg8;", "module bench;")
    code, record = gate("sim", folder)
    assert record["details"]["failures"][0].endswith("name the bench's module as its file, tb_reg8")
    (folder / "tb" / "tb_reg8.v").unlink()
    ran = command("chip", "sim", folder)
    assert ran.returncode == 2 and ran.stdout.splitlines()[0].startswith(
        "SKIP   sim        tb/ holds no bench: write a bench that prints errors, checks and x_outputs"
    )


@needs_iverilog
def test_sim_holds_a_benchs_own_bounds_and_refuses_an_expect_file_it_cannot_read(tmp_path):
    folder = a_project(tmp_path)
    swap(
        folder / "tb" / "tb_reg8.v",
        '$display("errors = %0d", errors);',
        '$display("errors = %0d", errors);\n        $display("last_q = %0d", q);',
    )
    expect = folder / "tb" / "tb_reg8.expect.json"
    expect.write_text(
        json.dumps({"last_q": {"min": 60, "max": 60, "source": "0x3C is 60"}}), encoding="utf-8"
    )
    code, record = gate("sim", folder)
    assert code == 0 and record["details"]["benches"]["tb_reg8"]["last_q"] == 60.0
    expect.write_text(
        json.dumps({"last_q": {"min": 61, "max": 61, "source": "a wrong bound"}}), encoding="utf-8"
    )
    code, record = gate("sim", folder)
    assert code == 1 and record["details"]["failures"] == [
        "tb_reg8: last_q=60 not in [61, 61] (a wrong bound)"
    ]
    expect.write_text(json.dumps({"last_q": {"mx": 61}}), encoding="utf-8")
    code, record = gate("sim", folder)
    assert code == 1 and record["details"]["failures"][0].startswith("tb_reg8.expect.json: last_q: ")


@needs_synth
def test_synth_maps_the_template_and_hands_its_netlist_on_with_its_hash(tmp_path):
    folder = a_project(tmp_path)
    code, record = gate("synth", folder)
    assert (code, record["status"]) == (0, "pass")
    assert record["summary"] == "24 cells, 8 flops, 270.3 um2, 0 failures"
    details = record["details"]
    assert details["liberty"].endswith("sky130_fd_sc_hd__tt_025C_1v80.lib")
    netlist = folder / "build" / "chip" / "synth" / "reg8.v"
    assert netlist.is_file() and details["sha256"] == chipflow.sha256(netlist)
    ledger = json.loads((folder / "build" / "chip" / "hashes.json").read_text(encoding="utf-8"))
    assert ledger["chip/synth/reg8.v"] == {"gate": "synth", "sha256": details["sha256"]}
    # the script the gate ran names no cell of the process but through the table
    script = (folder / "build" / "chip" / "synth" / "synth.ys").read_text(encoding="utf-8")
    assert "@" not in script and "hilomap -singleton -hicell sky130_fd_sc_hd__conb_1 HI" in script
    assert "sky130" not in (ROOT / "tools" / "chipscripts" / "synth.ys").read_text(encoding="utf-8")
    assert "sky130" not in (ROOT / "tools" / "chipfront.py").read_text(encoding="utf-8")


@needs_synth
def test_synth_fails_a_flop_with_no_reset_until_chip_json_answers_for_it(tmp_path):
    folder = a_project(tmp_path)
    swap(
        folder / "rtl" / "reg8.v",
        "        if (rst) q <= 8'd0;\n        else if (en) q <= d;",
        "        if (en) q <= d;",
    )
    swap(
        folder / "rtl" / "reg8.v",
        "    always @(posedge clk) begin",
        "    wire unused = rst;\n    always @(posedge clk) begin",
    )
    code, record = gate("synth", folder)
    assert code == 1 and record["details"]["failures"] == [
        f"8 flops have no reset: q[0], q[1], q[2], q[3], q[4], q[5] ...: {NO_RESET}"
    ]
    data = json.loads((folder / "chip.json").read_text(encoding="utf-8"))
    data["answers"] = {
        "flops_without_reset": [{"match": "q[*]", "why": "loaded before it is read", "evidence": "tb_reg8"}]
    }
    (folder / "chip.json").write_text(json.dumps(data), encoding="utf-8")
    code, record = gate("synth", folder)
    assert code == 0 and len(record["details"]["flops_without_reset"]) == 8


def hand_on_as_final(folder: Path) -> None:
    """Stand in for LAYOUT: the mapped netlist as the final one, with its hash recorded."""
    chip, problems = chipflow.read_chip(folder)
    assert problems == []
    run = chipflow.Run(cli=None, project=folder, out=folder / "build", chip=chip)
    run.final_netlist().parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(run.mapped_netlist(), run.final_netlist())
    run.record("layout", run.final_netlist())


@needs_synth
@needs_iverilog
@needs_verilator
def test_glsim_runs_the_benches_on_the_netlist_and_only_on_the_file_layout_recorded(tmp_path):
    folder = a_project(tmp_path)
    command("chip", "gates", folder)  # LINT, SIM and SYNTH pass; LAYOUT is another module's
    ran = command("chip", "glsim", folder)
    assert ran.returncode == 2 and ran.stdout.splitlines()[0].startswith(
        "SKIP   glsim      chip/layout/reg8.v is not there: the gate that writes it has not run"
    )
    hand_on_as_final(folder)
    code, record = gate("glsim", folder)
    assert (code, record["summary"]) == (0, "1 benches on the final netlist, 0 failures")
    assert record["details"]["benches"] == {"tb_reg8": {"errors": 0.0, "checks": 4.0, "x_outputs": 0.0}}
    with (folder / "build" / "chip" / "layout" / "reg8.v").open("a", encoding="utf-8") as fh:
        fh.write("// edited by hand\n")
    code, record = gate("glsim", folder)
    assert code == 1 and record["details"]["failures"] == [
        "chip/layout/reg8.v changed after LAYOUT recorded it: its hash differs"
    ]


@needs_synth
@needs_iverilog
@needs_verilator
def test_glsim_shows_an_unknown_output_that_the_rtl_run_hides(tmp_path):
    """An `initial` block stands where a reset should be, and chip.json answers for the flops. The RTL
    simulation obeys the block and passes; synthesis drops it; on the netlist every flop starts unknown
    and the first comparison sees it."""
    folder = a_project(tmp_path)
    swap(
        folder / "rtl" / "reg8.v",
        "        if (rst) q <= 8'd0;\n        else if (en) q <= d;",
        "        if (en) q <= d;",
    )
    swap(
        folder / "rtl" / "reg8.v",
        "    always @(posedge clk) begin",
        "    initial q = 8'd0;\n    wire unused = rst;\n    always @(posedge clk) begin",
    )
    data = json.loads((folder / "chip.json").read_text(encoding="utf-8"))
    data["answers"] = {
        "flops_without_reset": [{"match": "q[*]", "why": "loaded before it is read", "evidence": "tb_reg8"}]
    }
    (folder / "chip.json").write_text(json.dumps(data), encoding="utf-8")
    ran = command("--json", "chip", "gates", folder)
    passed = {r["gate"]: r["status"] for r in json.loads(ran.stdout)}
    assert (
        passed == {"lint": "pass", "sim": "pass", "synth": "pass", "layout": "skip"}
        or passed["synth"] == "pass"
    )
    hand_on_as_final(folder)
    code, record = gate("glsim", folder)
    assert code == 1 and record["details"]["failures"] == [
        "tb_reg8: errors=1 not in [None, 0]",
        "tb_reg8: x_outputs=1 not in [None, 0]",
    ]
