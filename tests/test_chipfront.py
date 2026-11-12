"""The front chip gates (tools/chipfront.py): LINT, SIM, SYNTH and GLSIM.

First the judges, on real reports of the engines kept in tests/chips/samples/front/ (paths rewritten to
/work and /kit): these run on every machine. Then each gate on a project made from the template, with
the engine itself; those skip by name where the engine is absent.
"""

from __future__ import annotations

import json
import re
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
        data("mapped.json"),
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
    assert (details["flops_before_mapping"], details["flops_removed_by_mapping"]) == (8, [])
    # the mapping was offered no cell of the kit's 2 lists: the weakest flop and gates are on 1 of them
    assert details["cells_by_type"] == {
        "sky130_fd_sc_hd__and2b_2": 8,
        "sky130_fd_sc_hd__dfxtp_2": 8,
        "sky130_fd_sc_hd__mux2_1": 8,
    }
    assert details["area_um2"] == pytest.approx(330.3168)


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


def test_the_flops_counted_are_the_netlists_and_a_flop_the_mapping_removed_is_named():
    """The mapping proves more than `synth` does: a flop that nothing reads after it is removed by the
    script's last pass. On the acceptance processor that is 24 of 156 flops, and the gate printed 156.
    The judge counts the netlist's flops and names each flop the netlist no longer holds."""
    folder = SAMPLES / "yosys-ok"
    parts = {
        name: json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
        for name in ("stat", "generic", "mapped")
    }
    texts = [(folder / name).read_text(encoding="utf-8") for name in ("check_generic.txt", "check.txt")]
    netlist = (folder / "reg8.v").read_text(encoding="utf-8")

    def judged() -> dict:
        got = chipfront.judge_synth(
            "", *texts, parts["stat"], parts["generic"], parts["mapped"], netlist, "reg8", cells(), []
        )
        assert got[:2] == ([], [])
        return got[2]

    flop = "sky130_fd_sc_hd__dfxtp_2"
    assert (judged()["flops"], judged()["flops_before_mapping"]) == (8, 8)
    # as if the mapping had found that nothing reads q[3]: its flop is in neither the netlist nor the counts
    built = parts["mapped"]["modules"]["reg8"]["cells"]
    before = parts["generic"]["modules"]["reg8"]["cells"]
    q3 = parts["generic"]["modules"]["reg8"]["netnames"]["q"]["bits"][3]
    gone = [name for name, cell in before.items() if cell["connections"].get("Q") == [q3]]
    assert len(gone) == 1 and built[gone[0]]["type"] == flop
    del built[gone[0]]
    for counts in (parts["stat"]["modules"]["\\reg8"], parts["stat"]["design"]):
        counts["num_cells_by_type"][flop] -= 1
    details = judged()
    assert (details["flops"], details["flops_before_mapping"]) == (7, 8)
    assert details["flops_removed_by_mapping"] == ["q[3]"]


def test_yosys_stopping_before_its_reports_is_a_failure_not_an_empty_pass():
    failures, _, details = chipfront.judge_synth(
        "ERROR: Module `\\reg9' not found!\n", "", "", None, None, None, None, "reg8", cells(), []
    )
    assert failures == [
        "ERROR: Module `\\reg9' not found!",
        "check wrote no count before the library's cells: Yosys stopped before it",
        "check wrote no count after them: Yosys stopped before it",
    ]
    assert details == {}
    # with no error named and no netlist either, the absence is the failure
    console = "Found and reported 0 problems.\n"
    assert chipfront.judge_synth("", console, console, None, None, None, None, "reg8", cells(), [])[0] == [
        "Yosys wrote no netlist: its log says where it stopped"
    ]


def liberty_cells(text: str) -> list[str]:
    return re.findall(r'^\s*cell \("([^"]+)"\) \{', text, re.M)


def test_the_mapping_reads_a_liberty_file_without_the_cells_kept_out_of_it():
    """Yosys 0.33 has no flag that keeps a cell out of the mapping. So the mapping reads a copy of the
    liberty file without the cells the kit lists. The sample is the head of the kit's own file with 5
    of its cells, each as the kit writes it."""
    text = sample("liberty-5-cells.lib")
    prefix = "sky130_fd_sc_hd__"
    assert liberty_cells(text) == [
        f"{prefix}{name}" for name in ("conb_1", "decap_3", "inv_1", "inv_2", "or2_0")
    ]
    out = {f"{prefix}{name}" for name in ("decap_3", "inv_1", "or2_0", "nothere_1")}
    kept, left = chipfront.liberty_without(text, out)
    assert left == [f"{prefix}decap_3", f"{prefix}inv_1", f"{prefix}or2_0"]
    assert liberty_cells(kept) == [f"{prefix}conb_1", f"{prefix}inv_2"]
    # what stays is the file's own text, line for line, and every group of it still closes
    assert (len(text.splitlines()), len(kept.splitlines())) == (733, 340)
    assert kept.count("{") == kept.count("}") == 37
    rest = iter(text.splitlines())
    assert all(line in rest for line in kept.splitlines())
    assert kept.startswith('library ("sky130_fd_sc_hd__tt_025C_1v80") {\n') and kept.endswith("\n}\n")
    # a name the file does not hold, and no name at all, leave it as it is
    assert chipfront.liberty_without(text, {f"{prefix}nothere_1"}) == (text, [])
    assert chipfront.liberty_without(text, set()) == (text, [])
    # a cell on 1 line, a name with no quotes, a brace inside quoted text that closes nothing
    tiny = 'library (l) {\n  cell (a) { area : 1; }\n  cell(b) {\n    pin (Y) { function : "A}"; }\n  }\n'
    tiny += '  cell ( "c" ) {\n  }\n}\n'
    assert chipfront.liberty_without(tiny, {"a", "b"}) == (
        'library (l) {\n  cell ( "c" ) {\n  }\n}\n',
        ["a", "b"],
    )


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


def a_run(folder: Path) -> chipflow.Run:
    chip, problems = chipflow.read_chip(folder)
    assert problems == []
    return chipflow.Run(cli=None, project=folder, out=folder / "build", chip=chip)


def test_a_gates_inputs_are_its_sources_and_every_file_they_name(tmp_path):
    """A gate's record of a pass names each of the project's files the gate read. Until 2026-11-12 it
    named the RTL and the benches alone: a header, a memory's contents and a bench's bounds could
    change after the gate passed, and EXPORT handed the layout out. No engine runs here."""
    folder = a_project(tmp_path)
    rtl, tb = folder / "rtl", folder / "tb"
    swap(rtl / "reg8.v", "module reg8 (", '`include "widths.vh"\n`include "nowhere.vh"\nmodule reg8 (')
    swap(rtl / "reg8.v", "endmodule", '    initial $readmemh("rom.hex", q);\nendmodule')
    (rtl / "widths.vh").write_text('`include "deep.vh"\n', encoding="utf-8")
    (rtl / "deep.vh").write_text("// the last of 3\n", encoding="utf-8")
    (rtl / "rom.hex").write_text("00\n", encoding="utf-8")
    swap(tb / "tb_reg8.v", "module tb_reg8;", '`include "common.vh"\nmodule tb_reg8;')
    (tb / "common.vh").write_text("// shared by the benches\n", encoding="utf-8")
    run = a_run(folder)

    def names(gate: str) -> list[str]:
        return [run.name_of(path) for path in chipfront.project_inputs(run, gate)]

    # a file, then each file it names, in the order it names them; the name with no file is left out
    sources = ["rtl/reg8.v", "rtl/widths.vh", "rtl/deep.vh", "rtl/rom.hex"]
    assert names("lint") == [*sources, "constraints.sdc", "chip.json"]
    assert names("synth") == [*sources, "chip.json"]
    # a file that is not there yet is named too: EXPORT sees it come
    assert names("sim") == [
        *sources,
        "tb/tb_reg8.v",
        "tb/common.vh",
        "tb/tb_reg8.expect.json",
        "rtl/mutations.json",
        "chip.json",
    ]
    assert names("glsim") == ["tb/tb_reg8.v", "tb/common.vh", "tb/tb_reg8.expect.json", "chip.json"]
    assert names("layout") == ["constraints.sdc", "chip.json"]
    # a header of 1 name in 2 folders of the engines' list: both are named, whichever an engine takes
    (tb / "widths.vh").write_text("// another file of that name\n", encoding="utf-8")
    assert names("lint") == [*sources[:3], "tb/widths.vh", sources[3], "constraints.sdc", "chip.json"]
    (tb / "widths.vh").unlink()
    # the hashes are taken before the engines start and again after: a file that is other bytes, new
    # or gone between the 2 is a failure, and the gate writes no record of a pass
    taken = chipfront.inputs_taken(run, "sim")
    assert sorted(taken) == sorted([*sources, "tb/tb_reg8.v", "tb/common.vh", "chip.json"])
    assert chipfront.inputs_moved(run, "sim", taken) == []
    (rtl / "deep.vh").write_text("// edited while the bench ran\n", encoding="utf-8")
    (tb / "tb_reg8.expect.json").write_text("{}", encoding="utf-8")
    (rtl / "rom.hex").unlink()
    assert chipfront.inputs_moved(run, "sim", taken) == [
        "rtl/deep.vh changed while the gate ran: its hash differs",
        "rtl/rom.hex changed while the gate ran: its hash differs",
        "tb/tb_reg8.expect.json changed while the gate ran: its hash differs",
    ]


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
    # A list with nothing in it shows as little as no list: `[]` passed --strict until 2026-11-12. With
    # 1 change that the bench catches the warning is gone, and --strict passes.
    listed = folder / "rtl" / "mutations.json"
    listed.write_text("[]", encoding="utf-8")
    code, record = gate("sim", folder, "--strict")
    assert code == 1 and record["details"]["failures"] == [
        "rtl/mutations.json lists no change: nothing shows that the benches can fail"
    ]
    change = {"name": "enable-ignored", "file": "rtl/reg8.v", "old": "else if (en) q", "new": "else q"}
    listed.write_text(json.dumps([change]), encoding="utf-8")
    code, record = gate("sim", folder, "--strict")
    assert code == 0
    assert record["summary"] == "1 benches, 4 checks, 1 of 1 changes of the RTL caught, 0 failures"
    listed.unlink()
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
def test_sim_proves_the_benches_with_the_list_of_changes_and_holds_the_list_itself(tmp_path):
    """A bench that passes on every wrong design proves nothing about the right one. SIM makes each
    change of rtl/mutations.json in a copy of the RTL and runs the benches there. Before 2026-11-12 the
    gate only asked that the file be there, and `workcenter mutate` counted a change that does not
    compile as caught."""
    folder = a_project(tmp_path)
    listed = folder / "rtl" / "mutations.json"
    mutants = folder / "build" / "chip" / "sim" / "mutants"

    def sim(*changes: tuple[str, str, str, str]) -> tuple[int, dict]:
        keys = ("name", "file", "old", "new")
        text = json.dumps({"mutations": [dict(zip(keys, change, strict=True)) for change in changes]})
        listed.write_text(text, encoding="utf-8")
        return gate("sim", folder)

    enable = ("enable-ignored", "rtl/reg8.v", "else if (en) q", "else q")
    code, record = sim(enable)
    assert code == 0 and record["details"]["mutations"] == {
        "enable-ignored": {"state": "caught", "by": "tb_reg8: errors=1 not in [None, 0]"}
    }
    # the change is made in a copy under the output folder: the project's RTL is as it was
    changed = mutants / "001" / "src" / "rtl" / "reg8.v"
    assert "else q <= d;" in changed.read_text(encoding="utf-8")
    assert "else if (en) q <= d;" in (folder / "rtl" / "reg8.v").read_text(encoding="utf-8")
    assert json.loads((folder / "build" / "chip" / "sim" / "passed.json").read_text(encoding="utf-8"))
    # a change that no check of the bench sees: the bench loads A5 and 3C, never FF
    blind = ("ff-loads-0", "rtl/reg8.v", "q <= d;", "q <= (d == 8'hFF) ? 8'h00 : d;")
    code, record = sim(enable, blind)
    assert code == 1 and record["details"]["failures"] == [
        "the benches pass with the change ff-loads-0 in rtl/reg8.v: add the check that fails on it"
    ]
    assert record["summary"] == "1 benches, 4 checks, 1 of 2 changes of the RTL caught, 1 failures"
    assert record["details"]["mutations"]["ff-loads-0"] == {"state": "survived", "by": ""}
    assert not (folder / "build" / "chip" / "sim" / "passed.json").exists()
    # a change that does not compile shows nothing: it is a failure of the list, not a catch
    broken = ("no-semicolon", "rtl/reg8.v", "q <= d;", "q <= d")
    code, record = sim(enable, broken)
    assert code == 1 and len(record["details"]["failures"]) == 1
    assert record["details"]["failures"][0].startswith(
        "rtl/mutations.json: the change no-semicolon does not compile, so it shows nothing: tb_reg8: does "
        "not compile: "
    )
    assert record["details"]["mutations"]["no-semicolon"]["state"] == "no build"
    # each change names 1 place of a file the RTL is read from; a list that does not is not run at all
    twice = ("vague", "rtl/reg8.v", "q <= ", "q <= ~")
    absent = ("gone", "rtl/reg8.v", "no such text", "x")
    bench = ("in-the-bench", "tb/tb_reg8.v", "expect_q(8'h3C);", "expect_q(8'h3D);")
    code, record = sim(enable, twice, absent, bench)
    assert code == 1 and record["details"]["failures"] == [
        "rtl/mutations.json: vague: rtl/reg8.v holds the old text 2 times: it must name 1 place",
        "rtl/mutations.json: gone: rtl/reg8.v holds the old text 0 times: it must name 1 place",
        "rtl/mutations.json: in-the-bench: tb/tb_reg8.v is no file the RTL is read from: a change is made in "
        "the RTL, and the benches stay as they are",
    ]
    assert "mutations" not in record["details"] and not mutants.exists()
    # a list the gate cannot read
    listed.write_text('{"mutations": [{"name": "half"}]}', encoding="utf-8")
    code, record = gate("sim", folder)
    assert code == 1 and record["details"]["failures"] == [
        "rtl/mutations.json: mutations.json: mutation 1 needs name, file, old and new, each as text"
    ]


@needs_iverilog
def test_a_change_that_makes_a_bench_wait_for_ever_is_stopped_and_caught(tmp_path):
    """A bench with no count of cycles waits for a value. With a change that never gives the value the
    simulation never ends. SIM stops a changed copy at 10 times the bench's own run, 20 s at least,
    whatever --timeout says: the wait is what caught the change."""
    folder = a_project(tmp_path)
    first = "expect_q(8'h00);  //"
    swap(folder / "tb" / "tb_reg8.v", first, f"wait (q === 8'h00);\n        {first}")
    change = {"name": "reset-to-1", "file": "rtl/reg8.v", "old": "q <= 8'd0", "new": "q <= 8'd1"}
    (folder / "rtl" / "mutations.json").write_text(json.dumps([change]), encoding="utf-8")
    code, record = gate("sim", folder, "--timeout", 3600)
    assert code == 0, record["details"]["failures"]
    caught = record["details"]["mutations"]["reset-to-1"]
    assert caught["state"] == "caught"
    assert caught["by"].startswith("tb_reg8: vvp passed its time limit of 20 s and was stopped (log ")
    assert 20 <= record["seconds"] < 40


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
    assert record["summary"] == "24 cells, 8 flops, 330.3 um2, 0 failures"
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
    # the mapping reads the gate's own copy of the liberty file, without the 236 cells of the kit's 2
    # lists; the cells' areas and the black boxes come from the kit's file as it is
    mapping = folder / "build" / "chip" / "synth" / "mapping.lib"
    assert f"dfflibmap -liberty {mapping}\nabc -liberty {mapping}\n" in script
    assert f"read_liberty -lib {details['liberty']}\n" in script
    assert details["cells_not_offered"] == 236
    offered = liberty_cells(mapping.read_text(encoding="utf-8"))
    kept_out = {
        name
        for listed in cells()["dont_use"].values()
        for file in listed
        for name in (KIT / file).read_text(encoding="utf-8").split()
    }
    assert len(offered) == 192 and len(kept_out) == 236 and not kept_out & set(offered)
    assert not kept_out & set(details["cells_by_type"])
    assert set(details["cells_by_type"]) <= set(offered) and "sky130_fd_sc_hd__dfxtp_1" in kept_out


@needs_synth
def test_synth_fails_a_cell_the_rtl_names_itself_when_the_kit_lists_it_as_not_to_use(tmp_path):
    """The mapping is offered no cell of the kit's lists, so one in the netlist is there by name: here
    an OR gate of the list of cells that break a rule deck, in place of the register's reset."""
    folder = a_project(tmp_path)
    swap(
        folder / "rtl" / "reg8.v",
        "    always @(posedge clk) begin",
        "    wire both;\n    sky130_fd_sc_hd__or2_0 named (.A(rst), .B(en), .X(both));\n"
        "    always @(posedge clk) begin",
    )
    swap(folder / "rtl" / "reg8.v", "        if (rst) q <= 8'd0;", "        if (both & rst) q <= 8'd0;")
    code, record = gate("synth", folder)
    assert code == 1 and record["details"]["failures"] == [
        "the netlist holds sky130_fd_sc_hd__or2_0: the process kit lists it as not to use "
        "(libs.tech/openlane/sky130_fd_sc_hd/no_synth.cells, "
        "libs.tech/openlane/sky130_fd_sc_hd/drc_exclude.cells). Name another cell in the RTL, or none"
    ]
    assert record["details"]["cells_by_type"]["sky130_fd_sc_hd__or2_0"] == 1
    # a cell of neither list may be named
    swap(folder / "rtl" / "reg8.v", "sky130_fd_sc_hd__or2_0 named", "sky130_fd_sc_hd__or2_2 named")
    code, record = gate("synth", folder)
    assert code == 0 and record["details"]["cells_by_type"]["sky130_fd_sc_hd__or2_2"] == 1


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
    for front in ("lint", "sim", "synth"):  # each by its own command: `chip gates` would go on to LAYOUT
        assert command("chip", front, folder).returncode == 0, front
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


def test_an_open_supply_port_is_no_warning_and_an_open_logic_port_is_one():
    """The layout build gives the netlist's top module its supply ports. A bench drives the logic ports
    only, so Icarus notes VPWR and VGND as open on every netlist run. The same note on a logic port is
    the bench's fault, and it stays."""
    notes = sample("iverilog-open-supply.log").splitlines()
    assert len(notes) == 2 and "(VPWR)" in notes[0] and "(VGND)" in notes[1]
    supply = {"VPWR", "VGND"}
    assert chipfront.netlist_warnings(notes, "/kit", supply) == []
    logic = notes[0].replace("(VPWR)", "(en)")
    assert chipfront.netlist_warnings([*notes, logic], "/kit", supply) == [logic]
    assert chipfront.netlist_warnings(notes, "/kit", {"VPWR"}) == [notes[1]]
    inside = (
        "/kit/libs.ref/sky130_fd_sc_hd/verilog/primitives.v:12: warning: a note in the library's own model"
    )
    assert chipfront.netlist_warnings([inside, logic], "/kit", supply) == [logic]


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
