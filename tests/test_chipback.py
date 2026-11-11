"""The back chip gates (tools/chipback.py): LAYOUT, STA, DRC, ANTENNA, LVS, EXPORT and `chip render`.

First the judges, on real reports of the engines kept in tests/chips/samples/back/ (its README says
how each was made): these run on every machine. Then each gate on a project made from the template,
with the engines themselves. The whole flow runs once in a session, about 50 s, and each test works on
a copy of it; those tests skip by name where an engine or the process kit is absent.
"""

from __future__ import annotations

import itertools
import json
import re
import shutil
import struct
import subprocess
import sys
import threading
import types
import zlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SAMPLES = ROOT / "tests" / "chips" / "samples" / "back"
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tests"))
import chipback  # noqa: E402
import chipflow  # noqa: E402
from test_chipflow import CHIP, KIT, command, fill, load_cli  # noqa: E402

SUPPLY = ("VPWR", "VGND")
CORNER = "nom_tt_025C_1v80"
OVER = "take a larger die, or cut logic. Do not raise the limit"
FLOW = ("verilator", "iverilog", "vvp", "yosys", "openroad", "sta", "magic", "netgen", "klayout")
ABSENT = [name for name in FLOW if chipflow.find_engine(load_cli(), name) is None]
ABSENT += [] if KIT.is_dir() else ["the sky130A process kit"]
needs_flow = pytest.mark.skipif(bool(ABSENT), reason=f"not installed: {', '.join(ABSENT)}")


def sample(name: str) -> str:
    return (SAMPLES / name).read_text(encoding="utf-8")


def without(text: str, mark: str) -> str:
    """A report with each line that holds `mark` taken out: what an engine prints when a script stops
    short of that line, or never asks for it."""
    kept = [line for line in text.splitlines(keepends=True) if mark not in line]
    assert len(kept) < len(text.splitlines()), mark
    return "".join(kept)


def physical() -> tuple[str, ...]:
    cells = chipflow.read_table("sky130A")[0]["libraries"]["sky130_fd_sc_hd"]["cells"]
    return (cells["tap"], *cells["fill"], *cells["decap"])


# ----------------------------------------------------------- the judges: LAYOUT


def test_a_layout_that_was_built_passes_with_its_numbers():
    built = {"router_violations": 0, "open_pins": 0, "utilization": 0.5975, "area_um2": 299.04}
    assert chipback.judge_layout(sample("layout-pass.log"), 0.6, SUPPLY) == ([], [], built)
    # no limit named: the number is reported and held to nothing
    assert chipback.judge_layout(sample("layout-pass.log"), None, SUPPLY) == ([], [], built)
    failures, warnings, details = chipback.judge_layout(sample("layout-slow-clock.log"), 0.6, SUPPLY)
    # the build could not repair every path: STA judges that, and LAYOUT names it
    assert (failures, warnings) == ([], ["[WARNING RSZ-0062] Unable to repair all setup violations."])
    assert (details["utilization"], details["area_um2"]) == (0.6, 300.29)


def test_a_core_the_cells_do_not_fit_or_fill_over_the_limit_fails():
    assert chipback.judge_layout(sample("layout-does-not-fit.log"), 0.6, SUPPLY) == (
        [
            "the cells take 3.4286 times the core's area after the floorplan: they do not fit. Take a "
            "larger die, or cut logic"
        ],
        [],
        {"utilization": 3.4286},
    )
    # the script stops before its long steps on a netlist that is over the limit already
    assert chipback.judge_layout(sample("layout-over-limit.log"), 0.6, SUPPLY) == (
        [
            "utilisation 0.6687 is over the limit 0.6 of chip.json after the floorplan, before the clock "
            f"tree adds cells: {OVER}"
        ],
        [],
        {"utilization": 0.6687, "over_limit": True},
    )
    # under the limit after the floorplan, over it once the clock tree is built
    late = sample("layout-over-limit-after-build.log")
    failures, _, details = chipback.judge_layout(late, 0.7, SUPPLY)
    assert failures == [f"utilisation 0.7234 is over the limit 0.7 of chip.json: {OVER}"]
    assert details == {
        "router_violations": 0,
        "open_pins": 0,
        "utilization": 0.7234,
        "area_um2": 297.79,
        "over_limit": True,
    }
    assert chipback.judge_layout(late, 0.75, SUPPLY)[0] == []
    # the engine's own line rounds to 1 %: 0.5975 reads `60%`, and so would 0.604
    assert "Design area 299 u^2 60% utilization." in sample("layout-pass.log")
    assert chipback.judge_layout(sample("layout-pass.log"), 0.597, SUPPLY)[0] == [
        f"utilisation 0.5975 is over the limit 0.597 of chip.json: {OVER}"
    ]


def test_what_openroad_leaves_wrong_in_a_layout_fails_it():
    assert chipback.judge_layout(sample("layout-router-violations.log"), 0.6, SUPPLY)[0] == [
        "the router left 8 violations: shorts or spacing errors between wires. Give the design more room"
    ]
    assert chipback.judge_layout(sample("layout-grid-open.log"), 0.6, SUPPLY)[0] == [
        "[ERROR PSM-0069] Check connectivity failed.",
        "the supply grid leaves parts of VPWR unconnected: its rails do not all reach a stripe",
    ]
    assert chipback.judge_layout(sample("layout-open-pin.log"), 0.6, SUPPLY)[0] == [
        "1 pins of cells are on no net: _17_/A: an open input floats"
    ]
    # OpenROAD warns about a cell the library lacks, builds the layout without it and exits 0
    failures, _, details = chipback.judge_layout(sample("layout-unknown-cell.log"), 0.7, SUPPLY)
    assert failures == [
        "the library has no cell sky130_fd_sc_hd__nor2_99: OpenROAD built the layout without _17_, so the "
        "layout is not the netlist SYNTH wrote"
    ]
    assert details["router_violations"] == 0
    assert chipback.judge_layout(sample("openroad-crash.log"), 0.6, SUPPLY)[0] == [
        "OpenROAD crashed: its log ends with the stack trace",
        "OpenROAD stopped before the floorplan was made",
    ]


def test_a_mark_the_layout_script_did_not_print_is_a_failure_never_a_pass():
    """Each number the gate holds is a line the script prints. A build that printed no such line was
    not judged on it: the limit, the open pins, the supply grid and the router's count each fail by
    their absence."""
    log = sample("layout-pass.log")
    assert chipback.judge_layout(without(log, "WORKCENTER utilization 0.5975 of the core"), 0.6, SUPPLY)[
        0
    ] == ["OpenROAD stopped before the layout was written"]
    assert chipback.judge_layout(without(log, "WORKCENTER layout written"), 0.6, SUPPLY)[0] == [
        "OpenROAD stopped before the layout was written"
    ]
    assert chipback.judge_layout(without(log, "WORKCENTER open pins"), 0.6, SUPPLY)[0] == [
        "OpenROAD stopped before the open pins were counted"
    ]
    assert chipback.judge_layout(without(log, "WORKCENTER grid VGND"), 0.6, SUPPLY)[0] == [
        "OpenROAD stopped before the supply grid of VGND was checked"
    ]
    assert chipback.judge_layout(without(log, "Number of violations ="), 0.6, SUPPLY)[0] == [
        "the router printed no count of violations"
    ]
    assert chipback.judge_layout(without(log, "WORKCENTER utilization 0.5525 after"), 0.6, SUPPLY)[0] == [
        "OpenROAD stopped before the floorplan was made"
    ]
    # the router's last count is the one that stands: the passes before it count what it then repairs
    counts = [int(n) for n in chipback.ROUTER_RE.findall(log)]
    assert max(counts) > 0 and counts[-1] == 0
    assert chipback.judge_layout("", 0.6, SUPPLY)[0] == ["OpenROAD stopped before the floorplan was made"]


# -------------------------------------------------------------- the judges: STA


def sta(name: str, skew_limit: float | None = None, **more) -> tuple[list[str], dict]:
    """Judge 1 sample as the gate does: with the nets the script named and the nets of the SPEF. Each
    sample but 2 is a run on the template's layout, whose nets are `sta-pass.nets.txt` and whose SPEF
    is `reg8.nom.spef`; the 2 runs on another netlist keep their own list of nets."""
    own = SAMPLES / name.replace(".log", ".nets.txt")
    nets = (own.read_text(encoding="utf-8") if own.is_file() else sample("sta-pass.nets.txt")).split()
    wired = (
        set(nets) if own.is_file() and name != "sta-pass.log" else chipback.spef_nets(sample("reg8.nom.spef"))
    )
    values = {"nets": nets, "wired": wired, "physical": physical(), "supply": SUPPLY, **more}
    return chipback.judge_sta(
        sample(name),
        CORNER,
        values["nets"],
        values["wired"],
        skew_limit,
        values["supply"],
        values["physical"],
    )


def test_a_corner_that_holds_passes_with_its_slack_its_nets_and_its_skew():
    assert sta("sta-pass.log") == (
        [],
        {
            "setup_slack_ns": 15.4204,
            "hold_slack_ns": 0.4965,
            "tns_ns": 0.0,
            "nets": 38,
            "nets_without_parasitics": 0,
            "clock_skew_ns": 0.0,
        },
    )
    assert sta("sta-pass.log", skew_limit=0.1)[0] == []
    nets = chipback.spef_nets(sample("reg8.nom.spef"))
    assert len(nets) == 38 and {"clk", "d[0]", "q[7]", "_00_", "clknet_0_clk"} <= nets
    # a name map entry is `*17 clk`; a net is never named by its number
    assert not any(name.startswith("*") for name in nets)
    assert chipback.spef_nets("*D_NET clk 0.1\n*CONN\n*END\n") == {"clk"}


def test_a_path_too_slow_a_path_too_fast_and_a_broken_limit_each_fail_their_corner():
    failures, details = sta("sta-setup.log")
    assert failures == [f"{CORNER}: setup slack -4.7112 ns, from _33_ to q[1]"]
    assert details["setup_slack_ns"] == -4.7112 and details["tns_ns"] < 0
    assert sta("sta-hold.log")[0] == [f"{CORNER}: hold slack -0.7012 ns, from _39_ to _39_"]
    assert sta("sta-load.log")[0] == [
        f"{CORNER}: setup slack -16.8628 ns, from _33_ to q[1]",
        f"{CORNER}: 40 pins break a limit of the library or the constraints (max slew, max capacitance): "
        "_33_/Q 1.50 46.02 -44.53 (VIOLATED)",
    ]
    assert sta("sta-fanout.log")[0] == [
        f"{CORNER}: 5 pins break a limit of the library or the constraints (max fanout): en 1 8 -7 (VIOLATED)"
    ]


def test_constraints_that_leave_a_port_open_or_name_nothing_fail_their_corner():
    assert sta("sta-open-constraints.log")[0] == [
        f"{CORNER}: There are 10 input ports missing set_input_delay. d[0], d[1], d[2], d[3], d[4], d[5] ...",
        f"{CORNER}: There are 8 output ports missing set_output_delay. q[0], q[1], q[2], q[3], q[4], q[5] "
        "...",
        f"{CORNER}: There are 8 unconstrained endpoints. q[0], q[1], q[2], q[3], q[4], q[5] ...",
    ]
    # the supply ports of the routed netlist need no delay: check_setup names them in every run, and
    # the judge leaves out the nets the process table calls the supply
    assert "  VGND\n  VPWR\n" in sample("sta-pass.log")
    assert sta("sta-pass.log", supply=())[0] == [
        f"{CORNER}: There are 2 input ports missing set_input_delay. VGND, VPWR"
    ]
    # OpenSTA warns about a constraint that names no port, drops it and exits 0
    assert sta("sta-port-not-there.log")[0] == [
        f"{CORNER}: OpenSTA did not take all it read: constraints.sdc line 5, port 'nothere' not found.",
        f"{CORNER}: OpenSTA did not take all it read: constraints.sdc line 5, no valid objects specified "
        "for -from.",
    ]


def test_a_net_the_spef_leaves_out_fails_and_so_does_a_spef_opensta_read_in_part():
    """OpenSTA gives a net with no parasitics an estimate from the library and prints nothing. So the
    gate holds the SPEF's own names to the nets the script lists."""
    whole = chipback.spef_nets(sample("reg8.nom.spef"))
    assert sta("sta-pass.log", wired=whole - {"_00_", "clk"})[0] == [
        f"{CORNER}: 2 of 38 nets have no parasitics in the SPEF (_00_, clk): OpenSTA gives their wires an "
        "estimate"
    ]
    # a SPEF cut short: OpenSTA names a syntax error as a warning, goes on and exits 0
    cut = chipback.spef_nets(sample("reg8.cut-short.spef"))
    assert len(cut) == 21
    assert sta("sta-spef-cut-short.log", wired=cut)[0] == [
        f"{CORNER}: OpenSTA did not take all it read: /work/reg8/build/chip/layout/reg8.nom.spef line 516, "
        "syntax error.",
        f"{CORNER}: 17 of 38 nets have no parasitics in the SPEF (clknet_0_clk, clknet_1_0__leaf_clk, "
        "clknet_1_1__leaf_clk, d[4] ...): OpenSTA gives their wires an estimate",
    ]
    # a name with its brackets escaped in 1 file and bare in the other is the same net
    assert (
        sta("sta-pass.log", wired={name.replace("[", "\\[").replace("]", "\\]") for name in whole})[0] == []
    )


def test_a_line_of_the_timing_report_that_is_not_there_fails_and_never_passes():
    log = sample("sta-pass.log")
    nets, wired = sample("sta-pass.nets.txt").split(), chipback.spef_nets(sample("reg8.nom.spef"))

    def judge(text: str, names=nets, spef=wired, skew=None) -> list[str]:
        return chipback.judge_sta(text, CORNER, names, spef, skew, SUPPLY, physical())[0]

    held = f"{CORNER}: the nets were not held to the SPEF: the parasitics are not judged"
    assert judge(without(log, "WORKCENTER nets")) == [held]
    assert judge(log, names=None) == [held] and judge(log, spef=None) == [held]
    assert judge(log, names=nets[:-1]) == [
        f"{CORNER}: nets.txt names 37 nets and the log counts 38: the list is not this run's"
    ]
    assert judge(log.replace("WORKCENTER nets 38", "WORKCENTER nets 0"), names=[]) == [
        f"{CORNER}: the script named no net that joins 2 pins: the parasitics are not judged"
    ]
    assert judge(without(log, "worst slack 15.4204")) == [
        f"{CORNER}: no setup slack was reported: no path is constrained"
    ]
    assert judge(without(log, "tns 0.0000")) == [f"{CORNER}: no total negative slack was reported"]
    assert judge(without(log, "WORKCENTER violators end")) == [
        f"{CORNER}: OpenSTA's output has no part for violators: nothing of it is judged"
    ]
    assert judge(without(log, "WORKCENTER sta done")) == [
        f"{CORNER}: OpenSTA stopped before its end: its log says where"
    ]
    assert judge(sample("sta-stopped.log")) == [
        f"{CORNER}: OpenSTA stopped before its end: Error: cannot read file "
        "/kit/libs.ref/sky130_fd_sc_hd/lib/nothere.lib."
    ]


def test_the_skew_is_held_to_the_projects_limit_and_a_limit_with_no_skew_fails():
    assert sta("sta-skew.log")[1]["clock_skew_ns"] == 0.001
    assert sta("sta-skew.log", skew_limit=0.0005)[0] == [
        f"{CORNER}: clock skew 0.001 ns is over the limit 0.0005 ns of chip.json"
    ]
    assert sta("sta-skew.log", skew_limit=0.002)[0] == []
    # no path from a flop to a flop: OpenSTA reports no skew, and a limit then holds nothing
    assert "No launch/capture paths found." in sample("sta-no-flop-to-flop.log")
    failures, details = sta("sta-no-flop-to-flop.log", skew_limit=0.5)
    assert "clock_skew_ns" not in details and failures == [
        f"{CORNER}: no clock skew was reported, so the limit 0.5 ns of chip.json holds nothing: no path runs "
        "from 1 flop to another"
    ]
    assert sta("sta-no-flop-to-flop.log")[0] == []
    # the pass sample's skew is 0: every flop of the template feeds only itself
    assert sta("sta-pass.log", skew_limit=0.0001)[0] == []


def test_a_clock_left_ideal_and_a_cell_with_no_timing_model_fail_their_corner():
    assert sta("sta-ideal-clock.log")[0] == [
        f"{CORNER}: a clock is ideal in the timing: hold and skew mean nothing without the clock tree"
    ]
    assert "clock network delay (propagated)" in sample("sta-pass.log")
    # the tap and fill cells have no timing model and no logic: OpenSTA makes a black box of each. The
    # same line for any other cell means its paths are gone from the timing.
    assert sta("sta-pass.log", physical=("sky130_fd_sc_hd__tapvpwrvgnd_1",))[0] == [
        f"{CORNER}: the liberty file has no cell sky130_fd_sc_hd__fill_1, sky130_fd_sc_hd__fill_2, "
        "sky130_fd_sc_hd__fill_4, sky130_fd_sc_hd__fill_8: OpenSTA made a black box of each, and no path "
        "through one is judged"
    ]


# -------------------------------------------------------------- the judges: DRC


def test_magics_count_passes_at_0_and_fails_on_a_box_or_on_a_layout_read_in_part():
    assert chipback.judge_magic_drc(sample("magic-drc-pass.log"), sample("magic-drc-pass.rpt")) == ([], 0)
    assert chipback.judge_magic_drc(sample("magic-drc-spacing.log"), sample("magic-drc-spacing.rpt")) == (
        ["2 boxes break a rule; the first rule: Metal3 spacing < 0.3um (met3.2)"],
        2,
    )
    # Magic goes on after a layout file it could not read to its end, counts what it read and exits 0
    cut = sample("magic-drc-cut-short.log")
    assert "WORKCENTER drc count" in cut
    assert chipback.judge_magic_drc(cut, sample("magic-drc-cut-short.rpt")) == (
        [
            'Magic did not read the layout whole: Error while reading cell "reg8" (byte position 60000): '
            "Error while reading path for boundary/box; ignored."
        ],
        None,
    )
    none = ["Magic wrote no count of the boxes that break a rule"]
    assert chipback.judge_magic_drc(sample("magic-drc-no-top-cell.log"), None) == (none, None)
    # a report that is not there, or that is another run's, is no count of 0
    assert chipback.judge_magic_drc(sample("magic-drc-pass.log"), None) == (none, None)
    assert chipback.judge_magic_drc(sample("magic-drc-pass.log"), "") == (none, None)
    assert chipback.judge_magic_drc(sample("magic-drc-pass.log"), sample("magic-drc-spacing.rpt")) == (
        ["Magic's report counts 2 and its log 0"],
        None,
    )


def test_a_klayout_report_database_is_counted_and_what_is_no_report_is_no_count():
    assert chipback.lyrdb_items(sample("klayout-drc-pass.lyrdb"), "reg8") == (0, [])
    assert chipback.lyrdb_items(sample("klayout-drc-spacing.lyrdb"), "reg8") == (1, ["m3.2"])
    # the report of another top cell, a file that is no XML, and XML that is no report database
    assert chipback.lyrdb_items(sample("klayout-drc-pass.lyrdb"), "cpu8") == (None, [])
    assert chipback.lyrdb_items("", "reg8") == (None, [])
    assert chipback.lyrdb_items(sample("klayout-drc-cut-short.log"), "reg8") == (None, [])
    front = ROOT / "tests" / "chips" / "samples" / "front" / "verilator-ports.xml"
    assert chipback.lyrdb_items(front.read_text(encoding="utf-8"), "reg8") == (None, [])
    whole = sample("klayout-drc-pass.lyrdb")
    assert chipback.lyrdb_items(whole.replace(" <items>\n </items>\n", ""), "reg8") == (None, [])


# ---------------------------------------------------------- the judges: ANTENNA


def test_antennas_pass_at_0_and_fail_on_1_and_on_a_count_that_is_not_there():
    log, report = sample("antenna-pass.log"), sample("antenna-pass.rpt")
    assert chipback.judge_antenna(log, report) == ([], {"net_violations": 0, "pin_violations": 0})
    assert chipback.judge_antenna(sample("antenna-violations.log"), sample("antenna-violations.rpt")) == (
        [
            "38 nets and 58 pins collect more charge than their gates take: build again with diodes or "
            "more repair"
        ],
        {"net_violations": 38, "pin_violations": 58},
    )
    assert chipback.judge_antenna(log, None)[0] == ["OpenROAD wrote no antenna report with its counts"]
    assert chipback.judge_antenna(log, "")[0] == ["OpenROAD wrote no antenna report with its counts"]
    # a report of another run: its counts are not the log's
    assert chipback.judge_antenna(log, sample("antenna-violations.rpt"))[0] == [
        "the antenna report counts 38 nets and 58 pins, and the log 0 and 0"
    ]
    none = (["OpenROAD wrote no antenna counts: its log says where"], {})
    assert chipback.judge_antenna(without(log, "WORKCENTER antenna done"), report) == none
    assert chipback.judge_antenna(without(log, "net violations"), report) == none
    assert chipback.judge_antenna(sample("openroad-crash.log"), report) == none


# -------------------------------------------------------------- the judges: LVS


def test_an_extraction_passes_clean_and_fails_on_an_overlap_magic_exits_0_with():
    assert chipback.judge_extract(sample("extract-pass.log"), "") == []
    assert "Total of 69 errors (check feedback entries)." in sample("extract-overlap.log")
    assert chipback.judge_extract(sample("extract-overlap.log"), sample("extract-overlap.feedback.txt")) == [
        "the extraction names 69 errors: Illegal overlap between ndiff and poly (types do not connect)"
    ]
    assert chipback.judge_extract(sample("extract-pass.log"), None) == [
        "Magic wrote no list of what it found while extracting"
    ]
    assert chipback.judge_extract(without(sample("extract-pass.log"), "WORKCENTER extracted"), "") == [
        "Magic stopped before it wrote the layout's netlist"
    ]
    assert chipback.judge_extract(sample("magic-drc-cut-short.log"), "") == [
        'Magic did not read the layout whole: Error while reading cell "reg8" (byte position 60000): '
        "Error while reading path for boundary/box; ignored."
    ]


def test_netgens_report_passes_only_on_a_unique_match_of_the_top_cells():
    assert chipback.judge_lvs(sample("lvs-pass.rpt")) == (
        [],
        {
            "result": "Circuits match uniquely.",
            "comparisons": 5,
            "devices": {"layout": 27, "netlist": 27},
        },
    )
    assert chipback.judge_lvs(sample("lvs-nets-swapped.rpt"))[0] == [
        "the layout is not the netlist: Netgen says: Netlists do not match."
    ]
    assert chipback.judge_lvs(sample("lvs-wire-cut.rpt"))[0] == [
        "the layout is not the netlist: Netgen says: Top level cell failed pin matching."
    ]
    assert chipback.judge_lvs("") == (["Netgen wrote no final result"], {})
    cut = sample("lvs-pass.rpt").split("Final result:")[0]
    assert chipback.judge_lvs(cut) == (["Netgen wrote no final result"], {})


def test_netgens_final_result_does_not_pass_a_report_that_says_otherwise_above_or_below_it():
    """Netgen ends a report with `Final result: Circuits match uniquely.` for a layout whose transistor
    is 139 times wider than the netlist's. The comparison of that cell reads `Netlists match uniquely
    with property errors.` far above the final result, and the cell is named under it."""
    report = sample("lvs-property-error.rpt")
    assert "Final result: Circuits match uniquely." in report
    assert "Property errors were found." not in report
    assert chipback.judge_lvs(report)[0] == [
        "1 of the report's 5 comparisons do not read `Netlists match uniquely.`, under a final result "
        "that does: Netlists match uniquely with property errors.",
        "a device's size in the layout differs from the netlist's: Netgen names property errors in "
        "sky130_fd_sc_hd__nor2_1",
    ]
    # 1 report is 1 comparison of the top cells: Netgen starts its report file anew for each, so each
    # sample holds 1 final result. 2 reports in 1 file are no such report, whichever comes first.
    for name in ("lvs-pass.rpt", "lvs-nets-swapped.rpt", "lvs-wire-cut.rpt", "lvs-property-error.rpt"):
        assert len(re.findall("^Final result:", sample(name), re.M)) == 1, name
    both = sample("lvs-pass.rpt") + sample("lvs-nets-swapped.rpt")
    assert chipback.judge_lvs(both)[0] == [
        "Netgen's report holds 2 final results (Circuits match uniquely.; Netlists do not match.): it is "
        "not the report of 1 comparison"
    ]


# ------------------------------------------------------------ small helpers


def test_a_gds_stream_names_its_top_cells_and_a_value_is_1_tcl_word(tmp_path):
    def record(kind: int, data: bytes = b"") -> bytes:
        data += b"\0" * (len(data) % 2)
        return struct.pack(">HBB", 4 + len(data), kind, 6 if data else 0) + data

    # 2 cells, `top` places `leaf`: STRNAME is record 0x06, SNAME 0x12 and ENDLIB 0x04
    stream = record(0x05) + record(0x06, b"leaf") + record(0x07) + record(0x05) + record(0x06, b"top")
    stream += record(0x0A) + record(0x12, b"leaf") + record(0x11) + record(0x07) + record(0x04)
    assert chipback.gds_top_cells(stream) == ["top"]
    # a stream cut inside a record, or before its ENDLIB, is not whole: it has no top cell to hold
    assert chipback.gds_top_cells(b"") == [] and chipback.gds_top_cells(stream[:10]) == []
    assert chipback.gds_top_cells(stream[:-4]) == []
    assert chipback.tcl_word("a b") == "{a b}" and chipback.tcl_word(["met1", 0.48]) == "{met1 0.48}"
    path = chipback.write_vars(tmp_path, {"top": "reg8", "pins": ["VPWR", "VPB"], "die_area": ""})
    assert path.read_text(encoding="utf-8") == "set top {reg8}\nset pins {VPWR VPB}\nset die_area {}\n"
    assert chipback.time_limit("layout") == chipflow.TIME_LIMITS["layout"] == 7200
    assert [chipback.time_limit(g) for g in ("drc", "antenna", "lvs", "render")] == [3600, 900, 3600, 600]


def test_the_scripts_and_the_gates_name_no_file_cell_or_layer_of_a_process():
    for path in [ROOT / "tools" / "chipback.py", *sorted((ROOT / "tools" / "chipscripts").glob("*.tcl"))]:
        text = path.read_text(encoding="utf-8")
        assert not re.search(r"sky130|met[1-5]\b|VPWR|VGND|unithd", text), path.name


# -------------------------------------------------------- the gates, with engines


@pytest.fixture(scope="session")
def built(tmp_path_factory) -> Path:
    """The template project with the whole flow run on it once. A test never changes it: it copies."""
    folder = tmp_path_factory.mktemp("chipback") / "reg8"
    assert command("chip", "init", folder, "--top", "reg8").returncode == 0
    fill(folder)
    ran = command("chip", "gates", folder)
    assert ran.returncode == 0, ran.stdout[-3000:]
    return folder


@pytest.fixture
def project(built, tmp_path) -> Path:
    """A copy of the built project. The ledger names files under the output folder, so a copy keeps it."""
    folder = tmp_path / "reg8"
    shutil.copytree(built, folder)
    return folder


def gate(name: str, folder: Path, *flags: object) -> tuple[int, dict]:
    ran = command("--json", "chip", name, folder, *flags)
    return ran.returncode, json.loads(ran.stdout)[0]


def last_line(name: str, folder: Path, *flags: object) -> tuple[int, str]:
    ran = command("chip", name, folder, *flags)
    return ran.returncode, ran.stdout.splitlines()[-1]


def a_run(folder: Path, **flags) -> chipflow.Run:
    """The Run a gate receives for this project, to call a gate in this process."""
    args = types.SimpleNamespace(strict=False, jobs=4, corner=None, timeout=None, **flags)
    run, problems = chipflow.prepare(load_cli(), folder, folder / "build", args)
    assert problems == []
    return run


def hand_on(folder: Path, *names: str) -> None:
    """Stand in for LAYOUT: keep the hash each file has now as the one LAYOUT recorded, in the ledger
    and in LAYOUT's record of its pass. A gate takes a file only with that hash, so a test that changes
    a layout or a netlist says with this that the build wrote it so."""
    run = a_run(folder)
    record = run.base / "layout" / "passed.json"
    data = json.loads(record.read_text(encoding="utf-8"))
    for name in names:
        data["judged"][name] = run.record("layout", run.out / name)
    record.write_text(json.dumps(data), encoding="utf-8")
    run.record("layout", record)


def ledger(folder: Path) -> dict:
    return json.loads((folder / "build" / "chip" / "hashes.json").read_text(encoding="utf-8"))


def passed(folder: Path, name: str) -> dict | None:
    path = folder / "build" / "chip" / name / "passed.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def change(folder: Path, edit) -> None:
    data = json.loads((folder / "chip.json").read_text(encoding="utf-8"))
    edit(data)
    (folder / "chip.json").write_text(json.dumps(data), encoding="utf-8")


def swap(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    assert old in text, old
    path.write_text(text.replace(old, new), encoding="utf-8")


# KLayout's own Python, in batch mode: 2 squares of met3 0.1 um apart in a free corner, where the rule
# asks for 0.3 um; or 1 bar of poly across the cells' transistors.
EDIT_GDS = """import pya
layout = pya.Layout()
layout.read(gds)
top = layout.cell("reg8")
box = top.dbbox()
if mode == "spacing":
    layer = layout.layer(70, 20)
    top.shapes(layer).insert(pya.DBox(box.left + 3.0, box.bottom + 3.0, box.left + 4.0, box.bottom + 4.0))
    top.shapes(layer).insert(pya.DBox(box.left + 4.1, box.bottom + 3.0, box.left + 5.1, box.bottom + 4.0))
else:
    middle = (box.bottom + box.top) / 2
    bar = pya.DBox(box.left + 10.0, middle - 0.075, box.right - 10.0, middle + 0.075)
    top.shapes(layout.layer(66, 20)).insert(bar)
layout.write(gds)
"""


def edit_gds(folder: Path, mode: str) -> Path:
    gds = folder / "build" / "chip" / "layout" / "reg8.gds"
    script = folder / "edit_gds.py"
    script.write_text(EDIT_GDS, encoding="utf-8")
    ran = subprocess.run(
        ["klayout", "-b", "-r", str(script), "-rd", f"gds={gds}", "-rd", f"mode={mode}"],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert ran.returncode == 0, ran.stderr
    script.unlink()
    return gds


def test_where_the_chip_step_ran_every_engine_of_the_flow_is_there():
    """A machine with the chip folder is one where these tests are meant to run: an engine that is
    absent there is a failure, not a skip nobody reads."""
    if not CHIP.is_dir():
        pytest.skip(f"no chip folder {CHIP}: the chip step of install.sh did not run here")
    assert ABSENT == []


@needs_flow
def test_the_flow_is_green_and_each_back_gate_keeps_the_record_of_its_pass(built):
    records = {r["gate"]: r for r in json.loads((built / "build" / "gates.json").read_text(encoding="utf-8"))}
    assert [r["status"] for r in records.values()] == ["pass"] * 10
    layout, timing = records["layout"], records["sta"]
    assert layout["summary"] == "299.04 um2 of cells, utilisation 0.5975, 0 failures"
    assert {k: layout["details"][k] for k in ("router_violations", "open_pins", "floorplans")} == {
        "router_violations": 0,
        "open_pins": 0,
        "floorplans": 1,
    }
    assert layout["details"]["gds_top_cells"] == ["reg8"]
    corners = timing["details"]["corners"]
    assert len(corners) == 15 and timing["summary"].startswith("15 corners, least setup slack ")
    assert all(
        c["setup_slack_ns"] > 0 and c["hold_slack_ns"] > 0 and c["tns_ns"] == 0 for c in corners.values()
    )
    assert all((c["nets"], c["nets_without_parasitics"]) == (38, 0) for c in corners.values())
    assert timing["details"]["warnings"] == [
        "chip.json names no limits.clock_skew_ns: the skew is reported and held to nothing"
    ]
    assert records["drc"]["summary"] == "2 decks: magic 0, klayout-mr 0, 0 failures"
    assert records["antenna"]["details"] == {
        "net_violations": 0,
        "pin_violations": 0,
        "failures": [],
        "warnings": [],
    }
    assert records["lvs"]["summary"] == (
        "the layout against the netlist with its supply pins: 27 devices against 27, 0 failures"
    )
    assert records["export"]["summary"] == (
        "22 files, 20 reports and manifest.json in chip/tapeout, 0 failures"
    )
    # each gate's record names the hash of what it judged, and a judge records no input as its own
    kept, base = ledger(built), built / "build"
    gds = "chip/layout/reg8.gds"
    assert kept[gds] == {"gate": "layout", "sha256": chipflow.sha256(base / gds)}
    assert passed(built, "layout")["judged"] == layout["details"]["sha256"]
    assert sorted(layout["details"]["sha256"]) == [
        "chip/layout/reg8.def",
        "chip/layout/reg8.gds",
        "chip/layout/reg8.max.spef",
        "chip/layout/reg8.min.spef",
        "chip/layout/reg8.nom.spef",
        "chip/layout/reg8.odb",
        "chip/layout/reg8.pwr.v",
        "chip/layout/reg8.v",
    ]
    assert passed(built, "drc")["judged"] == {gds: kept[gds]["sha256"]}
    assert passed(built, "drc")["decks"] == {"magic": 0, "klayout-mr": 0}
    assert sorted(passed(built, "lvs")["judged"]) == [gds, "chip/layout/reg8.pwr.v"]
    assert sorted(passed(built, "antenna")["judged"]) == ["chip/layout/reg8.odb"]
    assert len(passed(built, "sta")["corners"]) == 15 and len(passed(built, "sta")["judged"]) == 4
    for name in ("layout", "sta", "drc", "antenna", "lvs"):
        assert kept[f"chip/{name}/passed.json"]["gate"] == name
    # nothing is written into the project, and the values of the process reach a script from the table
    assert sorted(p.name for p in built.iterdir()) == [
        ".gitignore",
        "README.md",
        "build",
        "chip.json",
        "constraints.sdc",
        "rtl",
        "tb",
    ]
    variables = (base / "chip" / "layout" / "vars.tcl").read_text(encoding="utf-8")
    assert "set tap_cell {sky130_fd_sc_hd__tapvpwrvgnd_1}\n" in variables
    assert "set utilization_limit {0.6}\n" in variables and "set density {0.6}\n" in variables
    # with no die named the gate aims at the limit less its headroom
    assert "set die_area {}\n" in variables and variables.endswith("set utilization {50.0}\n")


@needs_flow
def test_layout_stops_on_a_die_the_cells_overfill_and_hands_nothing_on(project):
    assert command("chip", "render", project).returncode == 0  # pictures of the layout that is replaced
    change(project, lambda d: d.update(floorplan={"die_um": [30, 30], "source": "a die too small"}))
    code, record = gate("layout", project)
    assert code == 1 and record["details"]["failures"] == [
        "the cells take 3.4286 times the core's area after the floorplan: they do not fit. Take a larger "
        "die, or cut logic"
    ]
    change(project, lambda d: d.update(floorplan={"die_um": [42, 42], "source": "a die a little small"}))
    code, record = gate("layout", project)
    assert code == 1 and record["summary"] == "the layout, 1 failures"
    assert record["details"]["failures"] == [
        "utilisation 0.6687 is over the limit 0.6 of chip.json after the floorplan, before the clock tree "
        f"adds cells: {OVER}"
    ]
    assert record["seconds"] < 20  # the script stops before the clock tree, the longest step
    # a build that failed hands nothing on: no hash of its folder, no record of a pass, no hand-off
    chip = project / "build" / "chip"
    assert not [name for name in ledger(project) if name.startswith("chip/layout/")]
    assert passed(project, "layout") is None
    assert not (chip / "tapeout").exists() and not (chip / "render").exists()
    out = project / "build"
    for name in ("sta", "drc", "antenna", "lvs"):
        assert last_line(name, project) == (
            2,
            f"SKIPPED ({name.upper()}: LAYOUT did not pass in {out}: {name.upper()} judges only a layout "
            "that LAYOUT passed): reg8",
        )
    assert last_line("export", project) == (
        2,
        f"SKIPPED (EXPORT: LAYOUT did not pass in {out}: EXPORT hands out only a layout that every gate "
        "passed): reg8",
    )
    ran = command("chip", "render", project)
    assert (ran.returncode, ran.stdout.strip()) == (
        2,
        f"chip render: chip/layout/reg8.gds is not there: the gate that writes it has not run in {out}: a "
        "picture is drawn of the layout LAYOUT recorded",
    )
    # the netlist SYNTH recorded, changed by hand: LAYOUT builds only what SYNTH wrote
    with (chip / "synth" / "reg8.v").open("a", encoding="utf-8") as fh:
        fh.write("// edited by hand\n")
    code, record = gate("layout", project)
    assert code == 1 and record["details"]["failures"] == [
        "chip/synth/reg8.v changed after SYNTH recorded it: its hash differs"
    ]


@needs_flow
def test_layout_builds_on_a_core_fuller_than_the_tables_density_and_holds_the_limit_at_the_end(project):
    """A die on which the cells take 0.67 of the core. The placer stops with an error at the table's
    density of 0.6, so the script raises it; the clock tree then takes the build over the limit."""

    def fuller(data: dict) -> None:
        data["floorplan"] = {"die_um": [42, 42], "source": "a die a little small"}
        data["limits"]["utilization"]["max"] = 0.7

    change(project, fuller)
    code, record = gate("layout", project)
    assert code == 1 and record["details"]["failures"] == [
        f"utilisation 0.7234 is over the limit 0.7 of chip.json: {OVER}"
    ]
    assert record["summary"] == "297.79 um2 of cells, utilisation 0.7234, 1 failures"
    assert (record["details"]["router_violations"], record["details"]["floorplans"]) == (0, 1)
    log = (project / "build" / "chip" / "layout" / "openroad.log").read_text(encoding="utf-8")
    assert "WORKCENTER utilization 0.6687 after the floorplan\nWORKCENTER density 0.7687\n" in log
    assert "[ERROR GPL-" not in log


def fake_start(run, texts: dict[str, list[str]], seen: list) -> None:
    """Replace the 1 function that starts an engine: each start is noted with its time limit and the
    vars.tcl beside it, and answers with the next text kept for that engine."""

    def start(command, cwd, log, timeout=None, env=None):
        engine = Path(str(command[0])).name
        variables = Path(cwd) / "vars.tcl"
        seen.append((engine, timeout, variables.read_text(encoding="utf-8") if variables.is_file() else ""))
        text = texts[engine].pop(0) if texts.get(engine) else ""
        Path(log).parent.mkdir(parents=True, exist_ok=True)
        Path(log).write_text(text, encoding="utf-8")
        return chipflow.Started([str(c) for c in command], 0, False, 0.1, timeout or 0, Path(log), text)

    run.start = start


@needs_flow
def test_layout_makes_its_own_floorplan_again_with_more_room_when_it_ends_over_the_limit(project):
    """With a limit and no die the floorplan is the gate's own. The engine's answers here are 2 real
    reports: a build that ends at 0.7234, then one that ends at 0.5975."""
    run, seen = a_run(project), []
    over, good = sample("layout-over-limit-after-build.log"), sample("layout-pass.log")
    fake_start(run, {"openroad": [over, good]}, seen)
    result = chipback.gate_layout(run)
    aims = [
        re.search(r"^set utilization \{(\S+)\}$", v, re.M).group(1) for e, _, v in seen if e == "openroad"
    ]
    assert aims == ["50.0", "39.4"]  # 0.6 less the headroom, then 0.5 * 0.6 / 0.7234 * 0.95
    assert result.details["floorplans"] == 2
    assert (run.base / "layout" / "openroad.1.log").read_text(encoding="utf-8") == over
    # the stand-in for Magic prints nothing, so the gate fails there: the 2 floorplans are what is held
    assert result.details["failures"] == ["Magic wrote no GDS (log build/chip/layout/magic.log)"]
    # 3 floorplans that each end over the limit: the gate says so and builds no 4th
    run, seen = a_run(project), []
    fake_start(run, {"openroad": [over, over, over, good]}, seen)
    result = chipback.gate_layout(run)
    assert [engine for engine, _, _ in seen] == ["openroad"] * 3
    assert result.details["failures"] == [
        f"utilisation 0.7234 is over the limit 0.6 of chip.json: {OVER}",
        "3 floorplans of the gate's own were each over the limit: name floorplan.die_um",
    ]
    # a die the project names is never changed: 1 build, and the failure
    change(project, lambda d: d.update(floorplan={"die_um": [45.01, 45.01], "source": "the same die"}))
    run, seen = a_run(project), []
    fake_start(run, {"openroad": [over, good]}, seen)
    assert chipback.gate_layout(run).details["floorplans"] == 1 and len(seen) == 1


@needs_flow
def test_sta_at_1_corner_is_named_as_such_and_is_never_taken_for_the_full_run(project):
    ran = command("chip", "sta", project, "--corner", CORNER)
    lines = ran.stdout.splitlines()
    assert ran.returncode == 0 and lines[0].startswith("PASS   sta        1 corners, least setup slack ")
    assert lines[1:3] == [
        "       - warning: chip.json names no limits.clock_skew_ns: the skew is reported and held to nothing",
        f"       - warning: --corner {CORNER}: 1 corner ran of the 15 the project's ranges select",
    ]
    assert lines[-1] == "GREEN with 2 warnings: reg8"
    assert passed(project, "sta")["corners"] == [CORNER]
    # the hand-off of the full run is gone, and EXPORT makes no new one from 1 corner
    assert not (project / "build" / "chip" / "tapeout").exists()
    code, line = last_line("export", project)
    assert code == 2 and line.startswith(
        "SKIPPED (EXPORT: STA passed at 1 of the 15 corners the project's ranges select (max_ss_n40C_1v60, "
        "max_ss_100C_1v60, max_ff_n40C_1v95 ... did not run): EXPORT hands out only a layout whose timing "
        "every corner judged)"
    )
    # with --strict a warning fails the gate, and a gate that failed keeps no record of a pass
    code, record = gate("sta", project, "--corner", CORNER, "--strict")
    assert code == 1 and record["details"]["failures"] == [
        "chip.json names no limits.clock_skew_ns: the skew is reported and held to nothing"
    ]
    assert passed(project, "sta") is None
    code, record = gate("sta", project, "--corner", "nom_tt_125C_1v80")
    assert code == 1 and record["details"]["failures"][0].startswith(
        "--corner nom_tt_125C_1v80 is not a corner of this project (it has: max_ss_n40C_1v60, "
    )
    # with a limit on the skew the 1 warning left is the corner's, and --strict fails on it too
    change(project, lambda d: d["limits"].update(clock_skew_ns={"max": 0.5, "source": "REQ-CLK-02"}))
    code, record = gate("sta", project, "--corner", CORNER, "--strict")
    assert code == 1 and record["details"]["failures"] == [
        f"--corner {CORNER}: 1 corner ran of the 15 the project's ranges select"
    ]
    # every corner, a limit on the skew: no warning, and --strict passes
    code, record = gate("sta", project, "--strict")
    assert (code, record["status"], record["details"]["warnings"]) == (0, "pass", [])
    assert max(c["clock_skew_ns"] for c in record["details"]["corners"].values()) <= 0.5


@needs_flow
def test_sta_fails_a_path_that_is_too_slow_and_a_path_that_is_too_fast(project):
    swap(project / "constraints.sdc", "-period 20 ", "-period 0.5 ")
    code, record = gate("sta", project, "--corner", "max_ss_n40C_1v60")
    assert code == 1 and record["details"]["failures"] == [
        "max_ss_n40C_1v60: setup slack -4.7112 ns, from _33_ to q[1]"
    ]
    swap(project / "constraints.sdc", "-period 0.5 ", "-period 20 ")
    with (project / "constraints.sdc").open("a", encoding="utf-8") as fh:
        fh.write("set_clock_uncertainty -hold 1 [get_clocks clk] ;# source: the test's premise\n")
    code, record = gate("sta", project, "--corner", "min_ff_n40C_1v95")
    assert code == 1 and record["details"]["failures"] == [
        "min_ff_n40C_1v95: hold slack -0.7012 ns, from _39_ to _39_"
    ]
    assert record["details"]["corners"]["min_ff_n40C_1v95"]["setup_slack_ns"] > 0
    sdf = "chip/sta/min_ff_n40C_1v95/reg8.sdf"
    assert (project / "build" / sdf).is_file() and sdf not in ledger(project)


@needs_flow
def test_sta_takes_only_the_spef_layout_recorded_and_holds_every_net_to_it(project):
    spef = project / "build" / "chip" / "layout" / "reg8.nom.spef"
    text = spef.read_text(encoding="utf-8")
    number = re.search(r"^(\*\d+) _00_$", text, re.M).group(1)
    blocks = text.split("*D_NET ")
    kept = [block for block in blocks if not block.startswith(f"{number} ")]
    assert len(kept) == len(blocks) - 1
    spef.write_text("*D_NET ".join(kept), encoding="utf-8")
    code, record = gate("sta", project, "--corner", CORNER)
    assert code == 1 and record["details"]["failures"] == [
        "chip/layout/reg8.nom.spef changed after LAYOUT recorded it: its hash differs"
    ]
    # as if the build had written the SPEF so: OpenSTA exits 0 and warns of nothing
    hand_on(project, "chip/layout/reg8.nom.spef")
    code, record = gate("sta", project, "--corner", CORNER)
    assert code == 1 and record["details"]["failures"] == [
        f"{CORNER}: 1 of 38 nets have no parasitics in the SPEF (_00_): OpenSTA gives their wires an estimate"
    ]
    log = (project / "build" / "chip" / "sta" / CORNER / "sta.log").read_text(encoding="utf-8")
    assert "WORKCENTER sta done" in log and "syntax error" not in log and "Error:" not in log


@needs_flow
def test_sta_keeps_the_ledger_whole_while_its_corners_run_at_once(project):
    """The ledger of hashes is 1 file. Corners that read and wrote it while others ran lost entries:
    a corner then found no hash for its SPEF. Every read and write is now in the main thread."""
    run = a_run(project)
    threads: list[bool] = []
    take, record = run.take, run.record

    def noted(function):
        def call(*args):
            threads.append(threading.current_thread() is threading.main_thread())
            return function(*args)

        return call

    run.take, run.record = noted(take), noted(record)
    result = chipback.gate_sta(run)
    assert result.status == "pass", result.details["failures"]
    assert len(threads) >= 20 and all(threads)
    kept = ledger(project)
    assert len([name for name in kept if name.startswith("chip/sta/") and name.endswith(".sdf")]) == 15
    assert len([name for name in kept if name.startswith("chip/layout/")]) == 9


@needs_flow
def test_a_gate_with_no_layout_to_judge_is_a_skip_with_the_reason(tmp_path):
    folder = tmp_path / "reg8"
    assert command("chip", "init", folder, "--top", "reg8").returncode == 0
    fill(folder)
    out = folder / "build"
    assert last_line("layout", folder) == (
        2,
        "SKIPPED (LAYOUT: chip/synth/reg8.v is not there: the gate that writes it has not run in "
        f"{out}): reg8",
    )
    for name in ("sta", "drc", "antenna", "lvs"):
        code, record = gate(name, folder)
        assert (code, record["status"], record["details"]["engine_missing"]) == (2, "skip", False)
        assert record["summary"] == (
            f"LAYOUT has not run in {out}: {name.upper()} judges only a layout that LAYOUT passed"
        )
    assert last_line("export", folder) == (
        2,
        f"SKIPPED (EXPORT: LAYOUT has not run in {out}: EXPORT hands out only a layout that every gate "
        "passed): reg8",
    )


@needs_flow
def test_drc_counts_each_decks_items_and_export_refuses_the_layout_whatever_passes_after(project):
    edit_gds(project, "spacing")
    hand_on(project, "chip/layout/reg8.gds")
    # as if the build had written the layout so: the gates that passed before did not pass on this one
    code, record = gate("export", project)
    assert code == 1 and record["details"]["failures"] == [
        "chip/layout/reg8.gds is not the file DRC passed: its hash differs. Run DRC again",
        "chip/layout/reg8.gds is not the file LVS passed: its hash differs. Run LVS again",
    ]
    code, record = gate("drc", project)
    assert code == 1 and record["summary"] == "2 decks: magic 2, klayout-mr 1, 2 failures"
    assert record["details"]["failures"] == [
        "magic: 2 boxes break a rule; the first rule: Metal3 spacing < 0.3um (met3.2)",
        "klayout-mr: 1 items break a rule: m3.2",
    ]
    assert passed(project, "drc") is None
    # the 2 squares touch no net: ANTENNA and LVS pass on this layout, and DRC did not
    assert gate("antenna", project)[0] == 0 and gate("lvs", project)[0] == 0
    assert ledger(project)["chip/layout/reg8.gds"]["gate"] == "layout"
    out = project / "build"
    assert last_line("export", project) == (
        2,
        f"SKIPPED (EXPORT: DRC did not pass in {out}: EXPORT hands out only a layout that every gate "
        "passed): reg8",
    )
    assert not (out / "chip" / "tapeout").exists()


@needs_flow
def test_drc_stops_an_engine_at_its_time_limit_and_reads_no_report_of_an_earlier_run(project):
    drc = project / "build" / "chip" / "drc"
    earlier = drc / "klayout-mr.lyrdb"
    assert chipback.lyrdb_items(earlier.read_text(encoding="utf-8"), "reg8") == (0, [])
    code, record = gate("drc", project, "--timeout", 1)
    assert code == 1 and (
        "klayout-mr: klayout passed its time limit of 1 s and was stopped (log build/chip/drc/klayout-mr.log)"
        in record["details"]["failures"]
    )
    # the report of 0 items that the run before left is gone, and so is that run's record of a pass
    assert not earlier.exists() and passed(project, "drc") is None
    assert "klayout-mr" not in record["details"]["decks"]
    # a layout that changed after LAYOUT recorded it is not judged at all: no engine starts on it
    with (project / "build" / "chip" / "layout" / "reg8.gds").open("ab") as fh:
        fh.write(b"\0\0\0\0")
    code, record = gate("drc", project)
    assert code == 1 and record["details"]["failures"] == [
        "chip/layout/reg8.gds changed after LAYOUT recorded it: its hash differs"
    ]
    assert list(drc.iterdir()) == []


@needs_flow
def test_every_engine_of_a_back_gate_starts_with_a_time_limit_of_its_gate(project):
    """`run.start` with no limit takes the spine's default of 1800 s. Each back gate names its own."""
    run = a_run(project)
    quick = run.start(["true"], cwd=project, log=project / "build" / "true.log")
    assert quick.limit == chipflow.DEFAULT_LIMIT == 1800
    for name, function, engines in (
        ("drc", chipback.gate_drc, ["magic", "klayout"]),
        ("antenna", chipback.gate_antenna, ["openroad"]),
        ("lvs", chipback.gate_lvs, ["magic"]),
        ("sta", chipback.gate_sta, ["sta"] * 15),
        ("layout", chipback.gate_layout, ["openroad"]),
    ):
        run, seen = a_run(project), []
        fake_start(run, {}, seen)
        result = function(run)
        assert result.status == "fail", name  # an engine that printed nothing passed nothing
        assert [(engine, limit) for engine, limit, _ in seen] == [
            (engine, chipback.time_limit(name)) for engine in engines
        ], name


@needs_flow
def test_a_rule_deck_or_a_cell_view_the_kit_lacks_is_a_skip_and_never_a_pass(project):
    run, seen = a_run(project), []
    fake_start(run, {}, seen)
    run.pdk.table["drc"][1]["file"] = "libs.tech/klayout/drc/nothere.drc"
    result = chipback.gate_drc(run)
    assert (result.status, result.details["engine_missing"]) == ("skip", True)
    assert result.summary == "the process kit sky130A has no libs.tech/klayout/drc/nothere.drc"
    run.pdk.table["lvs"]["setup"] = "libs.tech/netgen/nothere.tcl"
    result = chipback.gate_lvs(run)
    assert (result.status, result.summary) == (
        "skip",
        "the process kit sky130A has no libs.tech/netgen/nothere.tcl",
    )
    assert seen == []  # no engine started


@needs_flow
def test_lvs_fails_a_netlist_and_a_layout_that_differ_and_export_refuses_them(project):
    out = project / "build"
    netlist = out / "chip" / "layout" / "reg8.pwr.v"
    text = netlist.read_text(encoding="utf-8")
    first, second = re.findall(r"\.D\((\w+)\)", text)[:2]
    netlist.write_text(
        text.replace(f".D({first})", ".D(@)")
        .replace(f".D({second})", f".D({first})")
        .replace(".D(@)", f".D({second})"),
        encoding="utf-8",
    )
    code, record = gate("lvs", project)
    assert code == 1 and record["details"]["failures"] == [
        "chip/layout/reg8.pwr.v changed after LAYOUT recorded it: its hash differs"
    ]
    # as if the build had written the netlist with the D pins of 2 flops swapped
    hand_on(project, "chip/layout/reg8.pwr.v")
    code, record = gate("lvs", project)
    assert code == 1 and record["details"]["failures"] == [
        "the layout is not the netlist: Netgen says: Netlists do not match."
    ]
    assert passed(project, "lvs") is None
    assert ledger(project)["chip/layout/reg8.gds"]["gate"] == "layout"
    assert last_line("export", project) == (
        2,
        f"SKIPPED (EXPORT: LVS did not pass in {out}: EXPORT hands out only a layout that every gate "
        "passed): reg8",
    )
    assert not (out / "chip" / "tapeout").exists()
    # a netlist with no supply pins is not what LVS compares
    shutil.copyfile(out / "chip" / "layout" / "reg8.v", netlist)
    hand_on(project, "chip/layout/reg8.pwr.v")
    code, record = gate("lvs", project)
    assert code == 1 and record["details"]["failures"] == [
        "the netlist has no VPWR, VGND pins: LVS compares the supply too, so it takes the netlist written "
        "with them"
    ]
    # the netlist as it was, and a bar of poly across the cells of the layout: Magic names 69 errors,
    # exits 0 and writes a netlist all the same
    netlist.write_text(text, encoding="utf-8")
    edit_gds(project, "poly")
    hand_on(project, "chip/layout/reg8.gds", "chip/layout/reg8.pwr.v")
    code, record = gate("lvs", project)
    assert code == 1 and record["summary"] == "the extraction, 1 failures"
    assert record["details"]["failures"] == [
        "the extraction names 69 errors: Illegal overlap between ndiff and poly (types do not connect) "
        "(log build/chip/lvs/extract.log)"
    ]
    assert (out / "chip" / "lvs" / "reg8.lvs.spice").is_file()


@needs_flow
def test_export_copies_what_every_gate_passed_and_its_manifest_names_each_hash(project):
    out = project / "build"
    tapeout = out / "chip" / "tapeout"
    manifest = json.loads((tapeout / "manifest.json").read_text(encoding="utf-8"))
    files = sorted(p.name for p in tapeout.iterdir() if p.is_file())
    assert files == sorted([*manifest["files"], "manifest.json"]) and len(manifest["files"]) == 22
    assert {name: chipflow.sha256(tapeout / name) for name in manifest["files"]} == manifest["files"]
    assert {name: chipflow.sha256(tapeout / name) for name in manifest["reports"]} == manifest["reports"]
    assert sorted(manifest["reports"]) == sorted(
        str(p.relative_to(tapeout)) for p in (tapeout / "reports").rglob("*") if p.is_file()
    )
    # the layout that leaves is the one DRC, ANTENNA and LVS each passed, and the one LAYOUT wrote
    gds = "chip/layout/reg8.gds"
    assert manifest["files"]["reg8.gds"] == chipflow.sha256(out / gds)
    judged = manifest["judged"]
    assert judged["drc"][gds] == judged["lvs"][gds] == judged["layout"][gds] == manifest["files"]["reg8.gds"]
    assert judged["antenna"] == {"chip/layout/reg8.odb": chipflow.sha256(out / "chip/layout/reg8.odb")}
    assert judged["sta"]["chip/layout/reg8.v"] == manifest["files"]["reg8.v"]
    assert judged["lvs"]["chip/layout/reg8.pwr.v"] == manifest["files"]["reg8.pwr.v"]
    assert manifest["files"]["max_ss_n40C_1v60.sdf"] == chipflow.sha256(
        out / "chip" / "sta" / "max_ss_n40C_1v60" / "reg8.sdf"
    )
    assert len(manifest["corners"]) == 15 and manifest["top"] == "reg8"
    assert manifest["pdk"] == {
        "name": "sky130A",
        "version": "1.0.470-0-g6d4d117",
        "library": "sky130_fd_sc_hd",
    }
    assert manifest["decks"] == [
        {"name": "magic", "origin": "community"},
        {"name": "klayout-mr", "origin": "community"},
    ]
    assert sorted(manifest["engines"]) == sorted(chipflow.ENGINES) and all(manifest["engines"].values())
    assert manifest["scope"].endswith("no foundry deck ran; no shuttle's limits were checked")
    for report in ("drc/magic.rpt", "drc/klayout-mr.lyrdb", "antenna/antenna.rpt", "lvs/lvs.rpt"):
        assert f"reports/{report}" in manifest["reports"]
    assert f"reports/sta/{CORNER}-sta.log" in manifest["reports"]
    constraints = project / "constraints.sdc"
    assert manifest["constraints"] == {"file": "constraints.sdc", "sha256": chipflow.sha256(constraints)}
    # a gate that runs again takes the hand-off away until EXPORT runs after it
    assert gate("antenna", project)[0] == 0 and not tapeout.exists()
    code, record = gate("export", project)
    assert (code, record["details"]["files"]) == (0, manifest["files"])
    # the constraints changed after STA judged the timing under them
    written = constraints.read_text(encoding="utf-8")
    constraints.write_text(written + "set_max_fanout 4 [current_design] ;# source: REQ-7\n", encoding="utf-8")
    code, record = gate("export", project)
    assert code == 1 and record["details"]["failures"] == [
        "constraints.sdc changed after STA passed: its hash differs. Run STA again"
    ]
    assert not tapeout.exists()
    constraints.write_text(written, encoding="utf-8")
    assert gate("export", project)[0] == 0 and (tapeout / "manifest.json").is_file()
    # the routed database changed after ANTENNA passed on it
    with (out / "chip" / "layout" / "reg8.odb").open("ab") as fh:
        fh.write(b"\0")
    code, record = gate("export", project)
    assert code == 1 and record["details"]["failures"] == [
        "chip/layout/reg8.odb changed after LAYOUT recorded it: its hash differs"
    ]
    assert not tapeout.exists()
    # the layout changed after every gate passed
    with (out / gds).open("ab") as fh:
        fh.write(b"\0\0\0\0")
    code, record = gate("export", project)
    assert code == 1 and record["details"]["failures"] == [
        "chip/layout/reg8.gds changed after LAYOUT recorded it: its hash differs",
        "chip/layout/reg8.odb changed after LAYOUT recorded it: its hash differs",
    ]
    # the gate that judges a file refuses it the same way, and starts no engine on it
    code, record = gate("antenna", project)
    assert code == 1 and record["details"]["failures"] == [
        "chip/layout/reg8.odb changed after LAYOUT recorded it: its hash differs"
    ]
    assert not (out / "chip" / "antenna" / "openroad.log").exists()


def picture(path: Path) -> tuple[int, int, int]:
    """A PNG file as (width, height, the count of its rows that hold more than 1 colour). A picture of
    nothing has 0 such rows. The file is decoded here, row by row: each row names 1 of the 5 filters
    of the PNG format, and its bytes are differences to the pixel before or the row above."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path.name
    at, packed, header = 8, b"", None
    while at < len(data):
        length, kind = struct.unpack(">I4s", data[at : at + 8])
        body = data[at + 8 : at + 8 + length]
        if kind == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            packed += body
        at += 12 + length
    width, height, depth, colour, _, _, interlace = header
    assert (depth, interlace) == (8, 0) and colour in (2, 6), header
    size = 3 if colour == 2 else 4
    stride = width * size
    raw = zlib.decompress(packed)
    assert len(raw) == (stride + 1) * height
    low, high = int.from_bytes(b"\x7f" * stride, "big"), int.from_bytes(b"\x80" * stride, "big")
    above, mixed = bytes(stride), 0
    for n in range(height):
        kind, line = raw[n * (stride + 1)], raw[n * (stride + 1) + 1 : (n + 1) * (stride + 1)]
        if kind == 1:  # Sub: every byte adds the same byte of the pixel to its left
            row = bytearray(stride)
            for channel in range(size):
                row[channel::size] = bytes(v & 255 for v in itertools.accumulate(line[channel::size]))
            line = bytes(row)
        elif kind == 2:  # Up: every byte adds the byte above it, with no carry into the next byte
            x, y = int.from_bytes(line, "big"), int.from_bytes(above, "big")
            line = (((x & low) + (y & low)) ^ ((x ^ y) & high)).to_bytes(stride, "big")
        elif kind in (3, 4):  # Average and Paeth: a guess from the pixels left, above and above left
            row = bytearray(line)
            for i in range(stride):
                left, up = (row[i - size] if i >= size else 0), above[i]
                guess = (left + up) // 2
                if kind == 4:
                    corner = above[i - size] if i >= size else 0
                    a, b, c = abs(up - corner), abs(left - corner), abs(left + up - 2 * corner)
                    guess = left if a <= b and a <= c else up if b <= c else corner
                row[i] = (row[i] + guess) & 255
            line = bytes(row)
        else:
            assert kind == 0, kind
        mixed += line != line[:size] * width
        above = line
    return width, height, mixed


@needs_flow
def test_render_draws_the_layout_the_gates_recorded_whole_and_layer_by_layer(project):
    folder = project / "build" / "chip" / "render"
    ran = command("chip", "render", project)
    names = ["reg8.png", "reg8.met1.png", "reg8.met2.png", "reg8.met3.png", "reg8.met4.png"]
    assert ran.returncode == 0 and ran.stdout.splitlines() == [
        *[f"wrote {folder / name}" for name in names],
        "no picture of met5: the layout holds no shape on it",
        f"chip render: 5 pictures of reg8 in {folder}",
    ]
    assert sorted(p.name for p in folder.glob("*.png")) == sorted(names)
    drawn = {name: picture(folder / name) for name in names}
    assert all((width, height) == (1600, 1600) for width, height, _ in drawn.values())
    # a picture of nothing has no row with 2 colours: the least of these, met3, has 123
    assert all(rows > 50 for _, _, rows in drawn.values()), drawn
    assert drawn["reg8.png"][2] >= max(drawn[name][2] for name in names[1:])
    # each picture is of its own layer: no 2 are the same bytes
    assert len({(folder / name).read_bytes() for name in names}) == 5
    said = json.loads(command("--json", "chip", "render", project).stdout)
    assert said == {"pictures": [str(folder / name) for name in names], "empty": ["met5"]}
    # the layer properties and the layers' numbers come from the table's files
    script = (folder / "render.py").read_text(encoding="utf-8")
    assert "sky130" not in script and "met1" not in script
    log = (folder / "klayout.log").read_text(encoding="utf-8")
    assert log.splitlines()[-1] == "WORKCENTER render done"
    # a layout the gates did not record is not drawn
    with (project / "build" / "chip" / "layout" / "reg8.gds").open("ab") as fh:
        fh.write(b"\0\0\0\0")
    ran = command("chip", "render", project)
    assert (ran.returncode, ran.stdout.strip()) == (
        1,
        "chip render: chip/layout/reg8.gds changed after LAYOUT recorded it: its hash differs: a picture is "
        "drawn of the layout LAYOUT recorded",
    )


@pytest.mark.skipif(not KIT.is_dir(), reason="the sky130A process kit is not installed")
def test_the_routing_layers_and_their_gds_numbers_are_read_from_the_kits_own_files():
    table = chipflow.read_table("sky130A")[0]
    plan = table["libraries"]["sky130_fd_sc_hd"]["floorplan"]
    layers = chipback.routing_layers(
        (KIT / plan["tracks"]).read_text(encoding="utf-8"),
        (KIT / table["klayout"]["layer_map"]).read_text(encoding="utf-8"),
        plan["routing_layers"]["bottom"],
        plan["routing_layers"]["top"],
    )
    assert [name for name, _ in layers] == ["met1", "met2", "met3", "met4", "met5"]
    assert dict(layers)["met1"] == ["68/20", "68/16", "68/4"]
    assert (
        chipback.routing_layers("met1 X 0.23 0.46\nmet1 Y 0.17 0.34\n", "met1 NET 68 20\n", "met1", "met9")
        == []
    )
