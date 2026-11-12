"""The spine of the chip gates (tools/chipflow.py): what every chip gate shares.

The readers of chip.json, of the constraints and of a process table; the timing corners a project's
ranges select; the 1 function that starts an engine; the ledger of hashes; the driver and its verdict;
`chip init`. No test here needs a chip engine but the 2 that say so, and the gates themselves have
tests of their own.
"""

from __future__ import annotations

import importlib.machinery
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
sys.path.insert(0, str(ROOT / "tools"))
import chipflow  # noqa: E402

CHIP = Path(os.environ.get("WORKCENTER_CHIP_TOOLS") or "/opt/workcenters/ee/chip")
KIT = CHIP / "pdk" / "sky130A"
VERSION = "1.0.470-0-g6d4d117"

needs_kit = pytest.mark.skipif(not KIT.is_dir(), reason="the sky130A process kit is not installed")
needs_verilator = pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator is not installed")
needs_iverilog = pytest.mark.skipif(shutil.which("iverilog") is None, reason="iverilog is not installed")

GOOD = {
    "top": "reg8",
    "pdk": {
        "name": "sky130A",
        "library": "sky130_fd_sc_hd",
        "version": VERSION,
        "source": "doctor, 2026-11-11",
    },
    "corners": {
        "temperature": {"values": [0, 70], "source": "REQ-ENV-01"},
        "supply": {"nominal": 1.8, "tolerance": 0.05, "source": "the regulator's row"},
    },
}


def load_cli():
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_chipflow", str(CLI))
    module = types.ModuleType("workcenter_cli_chipflow")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module  # dataclasses look the defining module up here
    loader.exec_module(module)
    return module


def command(*args: object, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, **(env or {})},
    )


def project(folder: Path, change=None) -> Path:
    """A chip project that holds a sound chip.json, changed by `change(data)`, and 1 RTL file."""
    (folder / "rtl").mkdir(parents=True, exist_ok=True)
    (folder / "rtl" / "reg8.v").write_text("module reg8; endmodule\n", encoding="utf-8")
    data = json.loads(json.dumps(GOOD))
    if change:
        change(data)
    (folder / "chip.json").write_text(json.dumps(data), encoding="utf-8")
    return folder


def a_chip(**changes) -> chipflow.Chip:
    values = {
        "top": "reg8",
        "rtl": [],
        "constraints": Path("constraints.sdc"),
        "pdk_name": "sky130A",
        "library": "sky130_fd_sc_hd",
        "pdk_version": VERSION,
        "temperature": (0.0, 70.0),
        "supply": 1.8,
        "supply_tolerance": 0.05,
    }
    return chipflow.Chip(**{**values, **changes})


def table_pdk() -> chipflow.Pdk:
    """The committed table with a folder that need not exist: corner selection reads the table alone."""
    table, problems = chipflow.read_table("sky130A")
    assert problems == []
    library = table["libraries"]["sky130_fd_sc_hd"]
    return chipflow.Pdk("sky130A", Path("/kit"), table, "sky130_fd_sc_hd", library, VERSION)


# ------------------------------------------------------------------- chip.json


def test_a_sound_chip_json_is_read_with_its_defaults(tmp_path):
    def more(data):
        data["limits"] = {"utilization": {"max": 0.6, "source": "a routed fixture"}}
        data["floorplan"] = {"die_um": [80.04, 81.6], "source": "the fixture's size"}
        data["benches"] = {"tb_probe": {"rtl_only": "it reads inside the design"}}
        data["answers"] = {
            "flops_without_reset": [{"match": "sr_*", "why": "flushed before use", "evidence": "tb_flush"}]
        }

    chip, problems = chipflow.read_chip(project(tmp_path, more))
    assert problems == []
    assert (chip.top, [p.name for p in chip.rtl], chip.constraints.name) == (
        "reg8",
        ["reg8.v"],
        "constraints.sdc",
    )
    assert (chip.temperature, chip.supply, chip.supply_tolerance) == ((0.0, 70.0), 1.8, 0.05)
    assert (chip.die_um, chip.utilization_max, chip.clock_skew_max_ns) == ((80.04, 81.6), 0.6, None)
    assert chip.rtl_only == {"tb_probe": "it reads inside the design"}
    assert chip.flops_without_reset == [
        {"match": "sr_*", "why": "flushed before use", "evidence": "tb_flush"}
    ]


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (
            lambda d: d.update(target={"name": "x"}),
            "chip.json: top level: unknown key 'target' (it takes: top, rtl, constraints, pdk, corners, "
            "floorplan, limits, benches, answers)",
        ),
        (
            lambda d: d["corners"]["supply"].pop("source"),
            "chip.json: corners.supply: no source: write where the numbers come from",
        ),
        (
            lambda d: d["corners"]["supply"].update(source="fill: the regulator's row"),
            "chip.json: corners.supply: the source still starts with fill: write where the numbers come from",
        ),
        (
            lambda d: d["pdk"].update(version="fill: the version"),
            "chip.json: pdk.version: not written (the text still starts with fill:)",
        ),
        (lambda d: d.update(top="8bit"), "chip.json: top: '8bit' is not a module name"),
        (
            lambda d: d.update(rtl=["../other/*.v"]),
            "chip.json: rtl: '../other/*.v' leaves the project's folder",
        ),
        # a list with no pattern names no RTL: `workcenter next` names the first pattern for the file
        (lambda d: d.update(rtl=[]), "chip.json: rtl: not a list of file patterns"),
        (
            lambda d: d["corners"]["supply"].update(tolerance=5),
            "chip.json: corners.supply.tolerance: 5 is not a fraction from 0 to under 1 (0.05 is 5 %)",
        ),
        (
            lambda d: d.pop("corners"),
            "chip.json: corners: not an object with temperature and supply: STA runs at the ranges it names",
        ),
        (
            lambda d: d["corners"]["temperature"].update(values=[70, 0]),
            "chip.json: corners.temperature.values: [70, 0] is not [least, greatest] in C",
        ),
        (
            lambda d: d.update(limits={"utilization": {"max": 60, "source": "x"}}),
            "chip.json: limits.utilization.max: 60 is over 1 (0.6 is 60 %)",
        ),
        (
            lambda d: d.update(limits={"clock_skew_ns": {"max": 0.5}}),
            "chip.json: limits.clock_skew_ns: no source: write where the numbers come from",
        ),
        (
            lambda d: d.update(
                answers={"flops_without_reset": [{"match": "sr_*", "why": "fill: why", "evidence": "tb_x"}]}
            ),
            "chip.json: answers.flops_without_reset[0]: match, why and evidence each say something, and none "
            "starts with fill:",
        ),
        (
            lambda d: d.update(benches={"tb_probe": {"rtl_only": ""}}),
            'chip.json: benches.tb_probe: not {"rtl_only": the reason the bench cannot run on the netlist}',
        ),
        (
            lambda d: d.update(floorplan={"die_um": [80, -1], "source": "x"}),
            "chip.json: floorplan.die_um: [80, -1] is not [width, height] in micrometres",
        ),
    ],
)
def test_every_line_of_chip_json_a_gate_cannot_act_on_is_named(tmp_path, change, said):
    chip, problems = chipflow.read_chip(project(tmp_path, change))
    assert chip is None and problems == [said]


def test_a_chip_json_that_is_not_json_or_holds_no_number_is_a_problem_line(tmp_path):
    folder = project(tmp_path)
    (folder / "chip.json").write_text("{not json", encoding="utf-8")
    chip, problems = chipflow.read_chip(folder)
    assert chip is None and len(problems) == 1 and problems[0].startswith("chip.json: not JSON: ")
    # Python's json reads NaN: a value that is no number is no module name and no voltage
    (folder / "chip.json").write_text(json.dumps(GOOD).replace("1.8", "NaN"), encoding="utf-8")
    assert chipflow.read_chip(folder)[1] == ["chip.json: corners.supply.nominal: nan is not a voltage over 0"]
    (folder / "chip.json").unlink()
    assert chipflow.read_chip(folder)[1] == [f"chip.json: not found in {folder}"]


# --------------------------------------------------------------- the constraints

SDC = """# the constraints of reg8
create_clock -name clk -period 20 [get_ports clk] ;# source: REQ-CLK-01, 50 MHz
set_input_delay 4 -clock clk \\
    [get_ports {rst en d[*]}] ;# source: the driver's datasheet
set_output_delay 4 -clock clk [get_ports {q[*]}] ;# source: the reader's setup time
set_max_fanout 10 [get_ports clk] ;# source: the library's guide
"""
PORTS = {"clk": "input", "rst": "input", "en": "input", "d": "input", "q": "output"}
COMMANDS = (
    "create_clock, set_clock_uncertainty, set_input_delay, set_output_delay, set_driving_cell, "
    "set_input_transition, set_load, set_max_fanout, set_max_transition, set_timing_derate, set_false_path, "
    "set_multicycle_path"
)


def sdc(tmp_path: Path, text: str, ports: dict | None = None) -> chipflow.Sdc:
    path = tmp_path / "c.sdc"
    path.write_text(text, encoding="utf-8")
    return chipflow.read_sdc(path, ports)


def test_sound_constraints_give_the_clock_and_cover_every_port(tmp_path):
    read = sdc(tmp_path, SDC, PORTS)
    assert (read.clock_port, read.clock_name, read.period_ns, read.max_fanout) == ("clk", "clk", 20.0, True)
    # a bus named as `d[*]` inside braces covers the port d, and a statement may continue onto a line
    assert read.problems == []
    everything = "\n".join(SDC.splitlines()[:2]) + (
        "\nset_input_delay 4 -clock clk [all_inputs] ;# source: a\n"
        "set_output_delay 4 -clock clk [all_outputs] ;# source: b\n"
    )
    assert sdc(tmp_path, everything, PORTS).problems == []


@pytest.mark.parametrize(
    ("text", "said"),
    [
        (
            SDC + "set_clock_groups -asynchronous -group clk\n",
            [f"c.sdc: line 7: 'set_clock_groups' is not a command the gates take (they take: {COMMANDS})"],
        ),
        (
            SDC + "set_propagated_clock [all_clocks]\n",
            [
                "c.sdc: line 7: set_propagated_clock is not for the project to write: the gates set the "
                "clock's mode, estimated before the clock tree and propagated after it"
            ],
        ),
        (
            SDC + "set_load 0.05 [all_outputs] ; set_propagated_clock [all_clocks] ;# source: x\n",
            ["c.sdc: line 7: a second command after `;`: write 1 command on a line"],
        ),
        (
            SDC + "set_load [exec cat /etc/passwd] [all_outputs] ;# source: x\n",
            [
                "c.sdc: line 7: [exec ...] is not a query the gates take (they take: get_ports, get_clocks, "
                "get_pins, get_nets, all_inputs, all_outputs, all_clocks)"
            ],
        ),
        (
            SDC + "source other.sdc\n",
            [f"c.sdc: line 7: 'source' is not a command the gates take (they take: {COMMANDS})"],
        ),
        (
            SDC.replace(" ;# source: REQ-CLK-01, 50 MHz", ""),
            ["c.sdc: line 2: create_clock has no source: end the line with `;# source: <text>`"],
        ),
        (
            SDC.replace("REQ-CLK-01, 50 MHz", "fill: the requirement"),
            ["c.sdc: line 2: create_clock: the source says nothing yet: write where the number comes from"],
        ),
        (
            SDC + "create_clock -name clk2 -period 10 [get_ports en] ;# source: x\n",
            ["c.sdc: line 7: a second clock: the first flow takes 1 clock. Use 1 clock and an enable"],
        ),
        (
            "\n".join(SDC.splitlines()[2:]) + "\n",
            ["c.sdc: no create_clock: name the clock, its period and its port"],
        ),
        (
            SDC + "set_false_path -from [get_ports rst]\n",
            ["c.sdc: line 7: set_false_path has no source: end the line with `;# source: <text>`"],
        ),
        (
            SDC.replace("-period 20 ", ""),
            ["c.sdc: line 2: create_clock has no -period over 0, in ns"],
        ),
        (
            # Tcl takes the last of 2 values and this reader the first: the record would name 20 ns
            # where the engines take 2000 ns
            SDC.replace("-period 20 ", "-period 20 -period 2000 "),
            ["c.sdc: line 2: create_clock writes -period 2 times: write it 1 time"],
        ),
        (
            SDC + "set_clock_uncertainty -1 [get_clocks clk] ;# source: x\n",
            [
                "c.sdc: line 7: set_clock_uncertainty under 0 gives every path time that is not there: an "
                "uncertainty is 0 or more"
            ],
        ),
        (
            SDC + "set_clock_uncertainty -setup -0.5 [get_clocks clk] ;# source: x\n",
            [
                "c.sdc: line 7: set_clock_uncertainty under 0 gives every path time that is not there: an "
                "uncertainty is 0 or more"
            ],
        ),
        (
            SDC + "set_timing_derate -late 0.1 ;# source: x\n",
            [
                "c.sdc: line 7: set_timing_derate -late under 1 makes a late path faster than the library "
                "says: a late derate is 1 or more"
            ],
        ),
        (
            SDC + "set_timing_derate -early 1.2 ;# source: x\n",
            [
                "c.sdc: line 7: set_timing_derate -early over 1 makes an early path slower than the library "
                "says: an early derate is 1 or less"
            ],
        ),
        (
            SDC + "set_timing_derate 1.1 ;# source: x\n",
            [
                "c.sdc: line 7: set_timing_derate takes 1 of -late and -early: write which paths the factor "
                "is for"
            ],
        ),
        (
            SDC
            + "set_clock_uncertainty 0.25 [get_clocks clk] ;# source: x\n"
            + "set_timing_derate -late 1.05 ;# source: y\n"
            + "set_timing_derate -early 0.95 ;# source: z\n",
            [],
        ),
    ],
)
def test_constraints_hold_only_what_they_may(tmp_path, text, said):
    """A constraints file is Tcl. A command outside the list, a second command on a line, a bracket that
    runs anything but a query, and a number with no source are each refused with the line. So is a
    margin that gives time away, whatever its source says, and an option written 2 times."""
    assert sdc(tmp_path, text).problems == said


def test_a_variable_in_the_constraints_is_refused_where_it_is_set_and_where_it_is_used(tmp_path):
    read = sdc(tmp_path, "set p 20\n" + SDC.replace("-period 20", "-period $p"))
    assert read.problems == [
        f"c.sdc: line 1: 'set' is not a command the gates take (they take: {COMMANDS})",
        "c.sdc: line 3: a variable (`$`): write the value itself",
        "c.sdc: no create_clock: name the clock, its period and its port",
    ]


def test_each_port_needs_its_delay_and_the_clock_needs_none(tmp_path):
    only_clock = "\n".join(SDC.splitlines()[:2]) + "\n"
    assert sdc(tmp_path, only_clock, PORTS).problems == [
        "c.sdc: input d has no set_input_delay: STA cannot judge a path through it",
        "c.sdc: input en has no set_input_delay: STA cannot judge a path through it",
        "c.sdc: output q has no set_output_delay: STA cannot judge a path through it",
        "c.sdc: input rst has no set_input_delay: STA cannot judge a path through it",
    ]
    # without the ports the reader cannot know, and says nothing about them
    assert sdc(tmp_path, only_clock).problems == []
    assert chipflow.read_sdc(tmp_path / "nothere.sdc").problems == [
        "nothere.sdc: not found: write the clock, and a delay for each input and output"
    ]


WIDTHS = {"d": (7, 0), "q": (7, 0)}
CLOCK = "\n".join(SDC.splitlines()[:2]) + "\n"
INPUTS = "set_input_delay 4 -clock clk [get_ports {rst en d[*]}] ;# source: a\n"
OUTPUTS = "set_output_delay 4 -clock clk [get_ports {q[*]}] ;# source: b\n"
EARLY = INPUTS.replace("delay 4", "delay -min 1")
NO_INPUT = [
    f"c.sdc: input {port} has no set_input_delay: STA cannot judge a path through it"
    for port in ("d", "en", "rst")
]


@pytest.mark.parametrize(
    ("text", "said"),
    [
        (CLOCK + INPUTS + OUTPUTS, []),
        # a bus's bare name names each of its bits, and 2 delays may share setup and hold between them
        (CLOCK + INPUTS.replace("d[*]", "d") + OUTPUTS.replace("{q[*]}", "q"), []),
        (CLOCK + EARLY + INPUTS.replace("delay 4", "delay -max 4") + OUTPUTS, []),
        (
            # OpenSTA lists no port that has a -min delay as a port without one, and judges no setup
            # path from it: the reviewer's project was GREEN with 19.9 ns of a 20 ns period given away
            CLOCK + INPUTS.replace("delay 4", "delay -min 19.9") + OUTPUTS,
            [
                f"c.sdc: input {port}: a set_input_delay -min only: no setup path through it is judged. "
                "Write 1 delay without -min, or both"
                for port in ("d", "en", "rst")
            ],
        ),
        (
            CLOCK + INPUTS + OUTPUTS.replace("delay 4", "delay -max 4"),
            [
                "c.sdc: output q: a set_output_delay -max only: no hold path through it is judged. Write 1 "
                "delay without -max, or both"
            ],
        ),
        (
            CLOCK + INPUTS.replace(" -clock clk", "") + OUTPUTS,
            [
                "c.sdc: line 3: set_input_delay names no -clock: a delay is counted from the clock's edge",
                *NO_INPUT,
            ],
        ),
        (
            CLOCK + INPUTS.replace("delay 4", "delay -rise 4") + OUTPUTS,
            [
                "c.sdc: line 3: set_input_delay -rise is a delay for 1 edge of the port: write 1 delay for "
                "both",
                *NO_INPUT,
            ],
        ),
        (
            # 1 bit does not stand for its bus
            CLOCK + INPUTS + OUTPUTS.replace("{q[*]}", "{q[0]}"),
            [
                "c.sdc: output q: 7 of its 8 bits have no set_output_delay (q[1], q[2], q[3], q[4] ...): "
                "name the bus as q[*]"
            ],
        ),
        (
            CLOCK
            + INPUTS
            + OUTPUTS.replace("delay 4", "delay -max 4")
            + OUTPUTS.replace("delay 4", "delay -min 1").replace("q[*]", "q[7]"),
            [
                "c.sdc: output q: 7 of its 8 bits (q[0], q[1], q[2], q[3] ...): a set_output_delay -max "
                "only: no hold path through it is judged. Write 1 delay without -max, or both"
            ],
        ),
        (
            # the outputs do not stand for the inputs
            CLOCK + "set_input_delay 4 -clock clk [all_outputs] ;# source: a\n" + OUTPUTS,
            [
                "c.sdc: line 3: set_input_delay takes [all_inputs], not [all_outputs]: a delay of 1 "
                "direction is not a delay of the other",
                *NO_INPUT,
            ],
        ),
    ],
)
def test_a_delay_covers_a_port_only_for_each_bit_and_for_setup_and_hold(tmp_path, text, said):
    """STA judges a path through a pin only when the pin has a delay it can use. LINT holds each bit of
    each port to 1 for setup and 1 for hold, where STA would say so 35 s later or not at all."""
    path = tmp_path / "c.sdc"
    path.write_text(text, encoding="utf-8")
    assert chipflow.read_sdc(path, PORTS, WIDTHS).problems == said


# ------------------------------------------------------------ the process table


def test_the_committed_table_is_sound_and_names_the_kit_install_sh_pins():
    table, problems = chipflow.read_table("sky130A")
    assert problems == []
    script = (ROOT / "install.sh").read_text(encoding="utf-8")
    assert f'SKY130_COMMIT="{table["version"]["commit"]}"' in script
    assert table["version"]["value"] == VERSION
    corners = table["libraries"]["sky130_fd_sc_hd"]["corners"]
    assert len(corners) == 16
    assert {c["process"] for c in corners.values()} == {"slow", "typical", "fast"}
    # every block says what it was read from
    assert all(d["source"] for d in table["drc"]) and table["lvs"]["source"] and table["magic"]["source"]
    assert table["klayout"]["source"]
    assert {d["origin"] for d in table["drc"]} == {"community"}


@pytest.mark.parametrize(
    ("change", "said"),
    [
        (lambda t: t.update(extra=1), "unknown key 'extra'"),
        (lambda t: t.pop("lvs"), "pdks/broken.json: no lvs"),
        (lambda t: t.pop("klayout"), "pdks/broken.json: no klayout"),
        (lambda t: t["klayout"].pop("layer_map"), "pdks/broken.json: klayout: no layer_map"),
        (lambda t: t["klayout"].update(colours="x"), "pdks/broken.json: klayout: unknown key 'colours'"),
        (
            lambda t: t["libraries"]["sky130_fd_sc_hd"]["corners"]["tt_025C_1v80"].update(process="tt"),
            "corners.tt_025C_1v80: not {liberty, process (slow, typical, fast), volts, celsius}",
        ),
        (
            lambda t: t["libraries"]["sky130_fd_sc_hd"]["cells"].pop("tap"),
            "libraries.sky130_fd_sc_hd.cells: no tap",
        ),
        (
            lambda t: t["libraries"]["sky130_fd_sc_hd"]["floorplan"].update(sight="unithd"),
            "libraries.sky130_fd_sc_hd.floorplan: unknown key 'sight'",
        ),
        (
            lambda t: t["libraries"]["sky130_fd_sc_hd"]["floorplan"].pop("repair"),
            "libraries.sky130_fd_sc_hd.floorplan: no repair",
        ),
        (
            lambda t: t["libraries"]["sky130_fd_sc_hd"]["floorplan"]["repair"].pop("antenna_iterations"),
            "floorplan.repair: not {slew_margin_percent, capacitance_margin_percent, antenna_iterations}",
        ),
        (
            lambda t: t["libraries"]["sky130_fd_sc_hd"]["floorplan"]["repair"].update(
                slew_margin_percent=100
            ),
            "floorplan.repair: not {slew_margin_percent, capacitance_margin_percent, antenna_iterations}",
        ),
        (
            lambda t: t["libraries"]["sky130_fd_sc_hd"]["floorplan"]["repair"].update(antenna_iterations=0),
            "2 margins from 0 to under 100 and a count of 1 or more",
        ),
        (
            lambda t: t["libraries"]["sky130_fd_sc_hd"]["floorplan"].pop("wire_capacitance_ff_per_um"),
            "libraries.sky130_fd_sc_hd.floorplan: no wire_capacitance_ff_per_um",
        ),
        (
            lambda t: t["libraries"]["sky130_fd_sc_hd"]["floorplan"]["wire_capacitance_ff_per_um"].update(
                clock=0
            ),
            "floorplan.wire_capacitance_ff_per_um: not {signal, clock}, each a number over 0",
        ),
        (
            lambda t: t["libraries"]["sky130_fd_sc_hd"]["floorplan"]["wire_capacitance_ff_per_um"].pop(
                "signal"
            ),
            "floorplan.wire_capacitance_ff_per_um: not {signal, clock}, each a number over 0",
        ),
        (
            lambda t: t["libraries"]["sky130_fd_sc_hd"]["cells"].pop("dont_use"),
            "libraries.sky130_fd_sc_hd.cells: no dont_use",
        ),
        (
            lambda t: t["libraries"]["sky130_fd_sc_hd"]["cells"]["dont_use"].pop("layout"),
            "cells.dont_use: not {synthesis, layout}, each a list of files of the kit",
        ),
        (
            lambda t: t["libraries"]["sky130_fd_sc_hd"]["cells"]["dont_use"].update(
                synthesis="no_synth.cells"
            ),
            "cells.dont_use: not {synthesis, layout}, each a list of files of the kit",
        ),
        (
            lambda t: t["libraries"]["sky130_fd_sc_hd"]["cells"]["dont_use"].update(layout=["fill: a file"]),
            "cells.dont_use: not {synthesis, layout}, each a list of files of the kit",
        ),
        (lambda t: t["drc"][0].update(origin="vendor"), "drc[0]: not {name, engine (magic, klayout), origin"),
    ],
)
def test_a_table_the_gates_cannot_read_is_refused_with_the_key(tmp_path, monkeypatch, change, said):
    table = json.loads((ROOT / "pdks" / "sky130A.json").read_text(encoding="utf-8"))
    table["name"] = "broken"
    change(table)
    (tmp_path / "broken.json").write_text(json.dumps(table), encoding="utf-8")
    monkeypatch.setattr(chipflow, "PDK_DIR", tmp_path)
    read, problems = chipflow.read_table("broken")
    assert read is None and len(problems) == 1 and said in problems[0], problems
    assert chipflow.read_table("nothere") == (
        None,
        ["pdks/nothere.json: not found; this workcenter has a table for: broken"],
    )


@needs_kit
def test_the_table_says_what_the_installed_kit_says():
    """Volts and temperature come from each liberty file's own header, not from its name; the flops with
    and without a reset from the ff groups of the typical corner."""
    table, _ = chipflow.read_table("sky130A")
    library = table["libraries"]["sky130_fd_sc_hd"]
    assert chipflow.installed_version(KIT, table) == VERSION
    for name, corner in library["corners"].items():
        head = (KIT / corner["liberty"]).read_text(encoding="utf-8", errors="replace")[:20000]
        volts = float(re.search(r"nom_voltage\s*:\s*([-\d.]+)", head).group(1))
        celsius = float(re.search(r"nom_temperature\s*:\s*([-\d.]+)", head).group(1))
        assert (corner["volts"], corner["celsius"]) == (volts, celsius), name
    text = (KIT / library["corners"]["tt_025C_1v80"]["liberty"]).read_text(encoding="utf-8", errors="replace")
    starts = [(m.start(), m.group(1)) for m in re.finditer(r'^\s*cell \("([^"]+)"\) \{', text, re.M)]
    with_reset, without, latches, gates = set(), set(), set(), set()
    for i, (at, cell) in enumerate(starts):
        body = text[at : starts[i + 1][0] if i + 1 < len(starts) else len(text)]
        family = re.sub(r"_\d+$", "", cell.removeprefix(library["cells"]["prefix"]))
        flop = re.search(r"^\s*ff \(", body, re.M)
        if flop:
            group = body[flop.start() : flop.start() + 600]
            (with_reset if re.search(r"\b(clear|preset)\s*:", group) else without).add(family)
        elif re.search(r"^\s*latch \(", body, re.M):
            latches.add(family)
        if "clock_gating_integrated_cell" in body:
            gates.add(family)
    cells = library["cells"]
    assert set(cells["flop_with_reset"]) == with_reset and set(cells["flop_without_reset"]) == without
    assert set(cells["latch"]) == latches and set(cells["clock_gate"]) == gates
    # every file a gate will open is in the kit
    files = [c["liberty"] for c in library["corners"].values()]
    files += [w[k] for w in library["wires"].values() for k in ("techlef", "rcx")]
    files += [library["lef"], library["gds"], library["spice"], *library["verilog"]["files"]]
    files += [
        library["floorplan"]["tracks"],
        table["magic"]["rc"],
        table["magic"]["tech"],
        table["klayout"]["layer_properties"],
        table["klayout"]["layer_map"],
        table["lvs"]["setup"],
    ]
    files += [d["file"] for d in table["drc"]]
    # the kit's own lists of cells not to use are read from the kit, by the 2 names the table gives
    assert list(cells["dont_use"]) == list(chipflow.DONT_USE) == ["synthesis", "layout"]
    files += [name for names in cells["dont_use"].values() for name in names]
    assert [f for f in files if not (KIT / f).is_file()] == []
    listed = {
        kind: {n for f in names for n in (KIT / f).read_text(encoding="utf-8").split()}
        for kind, names in cells["dont_use"].items()
    }
    assert (len(listed["synthesis"]), len(listed["layout"])) == (185, 53)
    # every cell the build itself places by name is one the kit lets it place
    placed = [cells["tap"], cells["clock_root"], cells["diode"]["cell"], cells["tie_high"]["cell"]]
    placed += [*cells["fill"], *cells["clock_buffers"]]
    assert not [name for name in placed if name in listed["layout"]]


def test_a_projects_ranges_select_the_corners_at_or_beyond_each_end():
    """1.8 V within 5 % is 1.71 to 1.89 V. The slow corner at or below 1.71 V is 1.60 V: 1.76 V is nearer
    and above. The fast one at or above 1.89 V is 1.95 V. Each at -40 and 100 C, the corners beyond 0 and
    70 C. The typical corner at 25 C is inside both ranges. 5 library corners, 3 wire corners each."""
    corners, problems = chipflow.select_corners(table_pdk(), a_chip())
    assert problems == []
    assert [c.name for c in corners] == [
        f"{wire}_{name}"
        for wire in ("max", "min", "nom")
        for name in ("ss_n40C_1v60", "ss_100C_1v60", "ff_n40C_1v95", "ff_100C_1v95", "tt_025C_1v80")
    ]
    slow = corners[1]
    assert (slow.process, slow.volts, slow.celsius, slow.wire) == ("slow", 1.6, 100.0, "max")
    assert str(slow.liberty) == "/kit/libs.ref/sky130_fd_sc_hd/lib/sky130_fd_sc_hd__ss_100C_1v60.lib"
    assert slow.rcx.name == "rules.openrcx.sky130A.max.calibre" and slow.techlef.name.endswith("__max.tlef")
    # a tighter supply reaches the 1.76 V corner at the cold end; the hot end has none there, so 1.60 V
    tight = chipflow.select_corners(table_pdk(), a_chip(supply_tolerance=0.02))[0]
    assert [c.library_corner for c in tight if c.wire == "nom"] == [
        "ss_n40C_1v76",
        "ss_100C_1v60",
        "ff_n40C_1v95",
        "ff_100C_1v95",
        "tt_025C_1v80",
    ]


def test_a_range_no_library_corner_covers_is_a_problem_never_a_dropped_corner():
    assert chipflow.select_corners(table_pdk(), a_chip(temperature=(0.0, 125.0)))[1] == [
        "no slow library corner covers 1.71 V or less at 125 C or hotter",
        "no fast library corner covers 1.89 V or more at 125 C or hotter",
    ]
    assert chipflow.select_corners(table_pdk(), a_chip(supply=3.3, supply_tolerance=0.02))[1] == [
        "no fast library corner covers 3.366 V or more at 0 C or colder",
        "no fast library corner covers 3.366 V or more at 70 C or hotter",
    ]


@needs_kit
def test_the_project_is_held_to_the_kit_version_it_names(tmp_path):
    cli = load_cli()
    pdk, problems, absent = chipflow.read_pdk(cli, a_chip())
    assert (pdk.installed, problems, absent) == (VERSION, [], False)
    assert chipflow.read_pdk(cli, a_chip(pdk_version="1.0.999"))[1:] == (
        [
            f"chip.json: pdk.version is 1.0.999, and the installed sky130A states {VERSION}: the project is "
            "proven on 1 version"
        ],
        False,
    )
    assert chipflow.read_pdk(cli, a_chip(library="sky130_fd_sc_hs"))[1] == [
        "chip.json: pdk.library: 'sky130_fd_sc_hs' is not in pdks/sky130A.json (it has: sky130_fd_sc_hd)"
    ]


def test_a_kit_that_is_not_on_the_machine_is_absent_not_a_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("WORKCENTER_CHIP_TOOLS", str(tmp_path))
    pdk, problems, absent = chipflow.read_pdk(load_cli(), a_chip())
    assert pdk is None and absent is True
    assert problems == [f"the process kit sky130A is not installed in {tmp_path / 'pdk' / 'sky130A'}"]


# ---------------------------------------------------------- engines and the ledger


def a_run(tmp_path: Path, **more) -> chipflow.Run:
    return chipflow.Run(cli=load_cli(), project=tmp_path, out=tmp_path / "out", chip=a_chip(), **more)


def test_an_engine_starts_with_no_input_a_home_of_the_run_and_a_time_limit(tmp_path):
    run = a_run(tmp_path)
    folder = run.fresh("lint")
    # `cat` ends at once on an empty input; an engine that waited on a terminal would stand still
    started = run.start(["sh", "-c", "cat; echo home=$HOME"], cwd=tmp_path, log=folder / "a.log")
    assert (started.exit, started.timed_out, started.problem("lint")) == (0, False, None)
    assert started.text == f"home={tmp_path / 'out' / 'chip' / 'home'}\n"
    failed = run.start(["sh", "-c", "echo oops; exit 3"], cwd=tmp_path, log=folder / "b.log")
    assert (
        failed.problem("lint: verilator on rtl")
        == f"lint: verilator on rtl: sh exit 3 (log {folder / 'b.log'})"
    )
    stuck = run.start(["sh", "-c", "sleep 30 & sleep 30"], cwd=tmp_path, log=folder / "c.log", timeout=1)
    assert (stuck.exit, stuck.timed_out) == (None, True) and stuck.seconds < 10
    assert stuck.problem("layout") == (
        f"layout: sh passed its time limit of 1 s and was stopped (log {folder / 'c.log'})"
    )
    # every start is kept, for the gate's report
    assert [c["exit"] for c in run.commands] == [0, 3, None]
    # a report of an earlier run is gone before a gate writes its own
    assert list(run.fresh("lint").iterdir()) == []


def test_a_file_is_taken_only_with_the_hash_a_gate_recorded(tmp_path):
    run = a_run(tmp_path)
    netlist = run.mapped_netlist()
    netlist.parent.mkdir(parents=True)
    netlist.write_text("module reg8; endmodule\n", encoding="utf-8")
    assert run.take(netlist) == (netlist, "chip/synth/reg8.v: no gate of this run recorded it")
    digest = run.record("synth", netlist)
    assert len(digest) == 64 and run.take(netlist) == (netlist, None)
    netlist.write_text("module reg8; wire x; endmodule\n", encoding="utf-8")
    assert run.take(netlist)[1] == "chip/synth/reg8.v changed after SYNTH recorded it: its hash differs"
    assert run.take(run.gds())[1] == (
        f"chip/layout/reg8.gds is not there: the gate that writes it has not run in {tmp_path / 'out'}"
    )
    names = [run.final_netlist(), run.power_netlist(), run.def_file(), run.database(), run.spef("max")]
    assert [str(p.relative_to(run.out)) for p in names] == [
        "chip/layout/reg8.v",
        "chip/layout/reg8.pwr.v",
        "chip/layout/reg8.def",
        "chip/layout/reg8.odb",
        "chip/layout/reg8.max.spef",
    ]
    assert str(run.sdf("max_ss_100C_1v60").relative_to(run.out)) == "chip/sta/max_ss_100C_1v60/reg8.sdf"
    assert str(run.measures("sim", "tb_reg8").relative_to(run.out)) == "chip/sim/tb_reg8/measures.json"


def test_the_ledger_keeps_every_entry_that_the_threads_of_a_gate_record_at_once(tmp_path):
    """A gate's pool records from several threads. Each read the ledger, added its entry and wrote the
    whole file back: of 30 runs of SIM at 4 jobs, 5 lost entries and 1 left a file that was no JSON
    (2026-11-11), and GLSIM then skipped a sound design at 2 jobs. Here 8 threads record 40 files
    each while another thread reads the ledger: no entry is lost, and each read finds whole JSON."""
    run = a_run(tmp_path)
    folder = run.base / "sim"
    folder.mkdir(parents=True)
    files = []
    for n in range(320):
        path = folder / f"measures-{n}.json"
        path.write_text(f'{{"n": {n}}}\n', encoding="utf-8")
        files.append(path)
    torn, done = [], threading.Event()

    def read() -> None:
        target = run.base / "hashes.json"
        while not done.is_set():
            try:
                json.loads(target.read_text(encoding="utf-8"))
            except FileNotFoundError:
                pass
            except ValueError as problem:
                torn.append(str(problem))

    reader = threading.Thread(target=read)
    reader.start()
    with ThreadPoolExecutor(max_workers=8) as pool:
        digests = list(pool.map(lambda path: run.record("sim", path), files))
    done.set()
    reader.join()
    ledger = run.ledger()
    assert torn == []
    assert len(ledger) == 320 and len(set(digests)) == 320
    kept = {name: entry["sha256"] for name, entry in ledger.items() if entry["gate"] == "sim"}
    assert kept == {f"chip/sim/{path.name}": d for path, d in zip(files, digests, strict=True)}
    assert sorted(p.name for p in run.base.iterdir()) == ["hashes.json", "sim"]  # no part file is left
    # a gate that runs again drops its own entries and no other gate's
    other = run.base / "synth" / "reg8.v"
    other.parent.mkdir()
    other.write_text("module reg8; endmodule\n", encoding="utf-8")
    run.record("synth", other)
    run.forget("sim")
    assert list(run.ledger()) == ["chip/synth/reg8.v"]


@pytest.mark.parametrize("out", ["proj/build", ".", "elsewhere"])
def test_a_record_names_each_file_1_way_wherever_the_output_folder_is(tmp_path, out):
    """A record names a file the gates wrote from the output folder and a file of the project from the
    project's folder, and reads each name back to its file. With the output folder above the project,
    EXPORT named `proj/chip.json` and looked for `proj/proj/chip.json`: 5 files "gone" in a sound
    project. A project's own file under a folder `chip/layout` was read back as the gates' netlist of
    that name and never held: its RTL changed after GREEN and EXPORT handed the old layout out."""
    project = tmp_path / "proj"
    run = chipflow.Run(cli=load_cli(), project=project, out=tmp_path / out, chip=a_chip())
    files = {
        project / "rtl" / "reg8.v": "rtl/reg8.v",
        project / "chip" / "layout" / "reg8.v": "./chip/layout/reg8.v",
        project / "chip" / "notes.v": "./chip/notes.v",
        run.final_netlist(): "chip/layout/reg8.v",
        run.base / "lint" / "passed.json": "chip/lint/passed.json",
    }
    for path, name in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{name}\n", encoding="utf-8")
        assert run.name_of(path) == name
        assert run.file_of(name).resolve() == path.resolve()
    # the 2 files named reg8.v under a folder chip/layout are 2 names with 2 hashes
    assert len(set(run.judged(files).values())) == len(files)
    # a file outside both folders keeps its path
    assert run.name_of(Path("/kit/cells.v")) == "/kit/cells.v"


@needs_kit
def test_an_output_folder_that_the_gates_would_empty_the_project_in_is_refused(tmp_path):
    """The gates empty `<out>/chip/<gate>` before they write. A project named `chip` with `--out` set to
    its parent would lose its own folders named lint, sim, layout: the command ends before any gate."""
    own = tmp_path / "own" / "chip"
    command("chip", "init", own, "--top", "reg8")
    fill(own)
    (own / "lint").mkdir()
    (own / "lint" / "notes.txt").write_text("mine\n", encoding="utf-8")
    ran = command("chip", "lint", own, "--out", own.parent)
    assert (ran.returncode, ran.stdout) == (1, "")
    assert ran.stderr == (
        f"chip: --out {own.parent}: the gates empty the folders under {own}, and the project lies there. "
        "Name an output folder beside the project, or 1 inside it\n"
    )
    assert (own / "lint" / "notes.txt").read_text(encoding="utf-8") == "mine\n"
    # RTL under <out>/chip would be emptied the same way
    other = tmp_path / "other"
    command("chip", "init", other, "--top", "reg8")
    fill(other)
    (other / "chip" / "rtl").mkdir(parents=True)
    (other / "rtl" / "reg8.v").rename(other / "chip" / "rtl" / "reg8.v")
    data = json.loads((other / "chip.json").read_text(encoding="utf-8"))
    (other / "chip.json").write_text(json.dumps({**data, "rtl": ["chip/rtl/*.v"]}), encoding="utf-8")
    ran = command("chip", "lint", other, "--out", other)
    assert (ran.returncode, ran.stdout) == (1, "")
    assert ran.stderr == (
        f"chip: --out {other}: chip/rtl/reg8.v is a file of the project, and it lies under "
        f"{other / 'chip'}, which the gates empty. Name another output folder\n"
    )
    assert (other / "chip" / "rtl" / "reg8.v").is_file()


@needs_verilator
def test_the_gates_empty_only_a_folder_they_made(tmp_path):
    """`--out` can name any folder, and the gates empty `<out>/chip/<gate>` before they write. A folder
    `chip` that was there before, with someone's own `layout` in it, would lose that folder. The gates
    write their ledger first in a folder they make, and take a folder of that name only with it."""
    folder = tmp_path / "reg8"
    command("chip", "init", folder, "--top", "reg8")
    fill(folder)
    shared = tmp_path / "shared"
    mine = shared / "chip" / "layout" / "mine.txt"
    mine.parent.mkdir(parents=True)
    mine.write_text("not the gates'\n", encoding="utf-8")
    ran = command("chip", "lint", folder, "--out", shared)
    assert (ran.returncode, ran.stdout) == (1, "")
    assert ran.stderr == (
        f"chip: --out {shared}: {shared / 'chip'} is there, not empty, and holds no hashes.json: the gates "
        "did not make it, and they empty the folders under it. Name another output folder, or move that "
        "one away\n"
    )
    assert mine.read_text(encoding="utf-8") == "not the gates'\n"
    # an empty folder of that name is taken, and so is the folder the gates made, run after run
    empty = tmp_path / "empty"
    (empty / "chip").mkdir(parents=True)
    for _ in range(2):
        assert command("chip", "lint", folder, "--out", empty).returncode == 0
        assert command("chip", "lint", folder).returncode == 0
    assert sorted(p.name for p in (empty / "chip").iterdir()) == ["hashes.json", "home", "lint"]
    # a gate that fails before it records anything leaves the ledger too: the next run is not refused
    (folder / "rtl" / "reg8.v").write_text("module reg8; wire x = ; endmodule\n", encoding="utf-8")
    red = tmp_path / "red"
    for _ in range(2):
        ran = command("chip", "lint", folder, "--out", red)
        assert (ran.returncode, ran.stderr) == (1, "")
    assert (red / "chip" / "hashes.json").read_text(encoding="utf-8") == "{}"


def test_a_path_with_white_space_is_refused_before_an_engine_fails_on_it(tmp_path):
    """Yosys reads its script word by word: in a project under `my chips/` SYNTH failed with "Can't
    open input file `chips/reg8/rtl/reg8.v'", a line that names no cause. The command says it first."""
    folder = tmp_path / "my chips" / "reg8"
    command("chip", "init", folder, "--top", "reg8")
    fill(folder)
    ran = command("chip", "lint", folder)
    assert (ran.returncode, ran.stdout) == (1, "")
    assert ran.stderr == (
        f"chip: {folder}: the path holds white space, and Yosys ends a path there. Use a path with none\n"
    )
    assert not (folder / "build").exists()
    plain = tmp_path / "reg8"
    command("chip", "init", plain, "--top", "reg8")
    fill(plain)
    out = tmp_path / "my chips" / "out"
    ran = command("chip", "lint", plain, "--out", out)
    assert ran.returncode == 1 and ran.stderr.startswith(f"chip: {out}: the path holds white space")
    spaced = plain / "rtl" / "more rtl.v"
    spaced.write_text("module more; endmodule\n", encoding="utf-8")
    ran = command("chip", "lint", plain)
    assert ran.returncode == 1 and ran.stderr.startswith(f"chip: {spaced}: the path holds white space")


def test_a_gate_that_is_asked_to_run_takes_back_the_record_of_its_earlier_pass(tmp_path, monkeypatch):
    """A gate returns on several paths before it empties its folder: an engine that is absent, no layout
    to judge, no bench that runs on the netlist. The record of an earlier pass and the hand-off folder
    stayed then. The driver takes both back before the gate's function, on every path."""
    run = a_run(tmp_path)
    report = run.base / "glsim" / "tb_reg8" / "run.log"
    report.parent.mkdir(parents=True)
    report.write_text("errors = 0\n", encoding="utf-8")
    run.record("glsim", report)
    run.write_passed("glsim", {})
    run.write_passed("sim", {})
    (run.base / "tapeout").mkdir()
    (run.base / "tapeout" / "manifest.json").write_text("{}", encoding="utf-8")
    assert run.read_passed("glsim")[0] is not None
    monkeypatch.setattr(chipflow, "gate_function", lambda name: lambda run: run.skip(name, "no bench"))
    assert chipflow.run_gate(run, "glsim").status == "skip"
    assert run.read_passed("glsim") == (None, f"GLSIM did not pass in {run.out}", True)
    assert sorted(run.ledger()) == ["chip/glsim/tb_reg8/run.log", "chip/sim/passed.json"]
    assert report.is_file() and not (run.base / "tapeout").exists()
    # the record of another gate stays
    assert run.read_passed("sim")[0] is not None


def test_a_gates_result_fails_on_a_failure_and_with_strict_on_a_warning(tmp_path):
    run = a_run(tmp_path)
    red = run.result("sim", ["tb_reg8: errors=2 not in [None, 0]"], ["no mutation list"], "1 bench")
    assert (red.status, red.summary) == ("fail", "1 bench, 1 failures, 1 warnings")
    warned = run.result("sim", [], ["no mutation list"], "1 bench")
    assert (warned.status, warned.details["warnings"]) == ("pass", ["no mutation list"])
    run.strict = True
    strict = run.result("sim", [], ["no mutation list"], "1 bench")
    assert (strict.status, strict.summary) == ("fail", "1 bench, 1 failures")
    assert strict.details == {"failures": ["no mutation list"], "warnings": []}
    # An engine or a kit that is absent is a skip, and a run with no table read is never a pass. The
    # engine that is there is `sh`, which every machine has: this test named `openroad` for it, and
    # failed on a machine without the chip engines, which is what CI is (2026-11-12).
    skip = run.need_engines("layout", "sh", "no-such-engine")
    assert (skip.status, skip.details["engine_missing"]) == ("skip", True)
    assert skip.summary == "no-such-engine is not installed: `workcenter doctor` lists the chip engines"
    both = run.need_engines("layout", "no-such-engine", "nor-this-one")
    assert both.summary == (
        "no-such-engine, nor-this-one is not installed: `workcenter doctor` lists the chip engines"
    )
    assert run.need_engines("lint", "sh") is None
    unread = run.need_pdk("synth")
    assert (unread.status, unread.details["failures"]) == ("fail", ["the process table was not read"])


def test_the_verdict_needs_every_gate_and_a_gate_that_did_not_run_is_the_verdict():
    cli = load_cli()

    def verdict(statuses: list, whole: bool = True, warnings: int = 0) -> tuple[str, int]:
        results = [
            cli.Result(gate, status, "why", {"warnings": ["w"] * warnings if status == "pass" else []})
            for gate, status in statuses
        ]
        return chipflow.chip_verdict(results, whole)

    every = [(gate, "pass") for gate in chipflow.GATE_NAMES]
    assert chipflow.GATE_NAMES == (
        "lint",
        "sim",
        "synth",
        "layout",
        "sta",
        "glsim",
        "drc",
        "antenna",
        "lvs",
        "export",
    )
    assert verdict(every) == ("GREEN", 0)
    assert verdict(every, warnings=1) == ("GREEN with 10 warnings", 0)
    assert verdict(every[:9]) == ("SKIPPED (not every gate ran)", 2)
    assert verdict([*every[:3], ("layout", "fail")]) == ("RED", 1)
    assert verdict([*every[:1], ("sim", "skip")]) == ("SKIPPED (SIM: why)", 2)
    assert verdict([("sta", "pass")], whole=False) == ("GREEN", 0)
    assert verdict([("sta", "pass")], whole=False, warnings=1) == ("GREEN with 1 warning", 0)


# -------------------------------------------------------------------- the driver


def fill(folder: Path) -> None:
    """Write what the template leaves as `fill:`, the way a project does."""
    data = json.loads((folder / "chip.json").read_text(encoding="utf-8"))
    data["pdk"].update(version=VERSION, source="workcenter doctor on 2026-11-11")
    data["corners"]["temperature"]["source"] = "the test's premise: 0 to 70 C"
    data["corners"]["supply"]["source"] = "the test's premise: 1.8 V within 5 %"
    data["limits"]["utilization"]["source"] = "the proof flow's counter, routed at 0.6"
    (folder / "chip.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
    text = (folder / "constraints.sdc").read_text(encoding="utf-8")
    text = re.sub(r"source: fill: [^\n]*", "source: the test's premise", text)
    (folder / "constraints.sdc").write_text(text, encoding="utf-8")


def test_chip_init_writes_the_template_once_and_never_over_a_file(tmp_path):
    first = command("chip", "init", tmp_path / "reg8", "--top", "reg8")
    assert first.returncode == 0
    assert first.stdout.splitlines()[-1] == (
        f"chip init: 6 files written, 0 kept; next: workcenter next {tmp_path / 'reg8'}"
    )
    files = sorted(
        str(p.relative_to(tmp_path / "reg8")) for p in (tmp_path / "reg8").rglob("*") if p.is_file()
    )
    assert files == [".gitignore", "README.md", "chip.json", "constraints.sdc", "rtl/reg8.v", "tb/tb_reg8.v"]
    assert "__TOP__" not in "".join((tmp_path / "reg8" / f).read_text(encoding="utf-8") for f in files)
    (tmp_path / "reg8" / "rtl" / "reg8.v").write_text("// mine\n", encoding="utf-8")
    again = command("chip", "init", tmp_path / "reg8", "--top", "reg8")
    assert again.stdout.splitlines()[-1].startswith("chip init: 0 files written, 6 kept")
    assert (tmp_path / "reg8" / "rtl" / "reg8.v").read_text(encoding="utf-8") == "// mine\n"
    bad = command("chip", "init", tmp_path / "x", "--top", "8bit")
    assert bad.returncode == 1 and "--top '8bit' is not a module name" in bad.stderr


def test_the_template_as_written_fails_only_on_what_it_leaves_to_fill(tmp_path):
    command("chip", "init", tmp_path / "reg8", "--top", "reg8")
    red = command("chip", "gates", tmp_path / "reg8", "--out", tmp_path / "o")
    lines = red.stdout.splitlines()
    assert red.returncode == 1 and lines[0].startswith("FAIL   lint       5 failures")
    assert lines[1:6] == [
        "       - chip.json: pdk.version: not written (the text still starts with fill:)",
        "       - chip.json: pdk.source: not written (the text still starts with fill:)",
        "       - chip.json: corners.temperature: the source still starts with fill: write where the numbers "
        "come from",
        "       - chip.json: corners.supply: the source still starts with fill: write where the numbers come "
        "from",
        "       - chip.json: limits.utilization: the source still starts with fill: write where the numbers "
        "come from",
    ]
    # the scope line, then the verdict as the last line
    assert lines[-2].startswith("scope: open engines; no process kit was read; no foundry deck ran")
    assert lines[-1] == f"RED: reg8  report {tmp_path / 'o' / 'gates.json'}"
    read = chipflow.read_sdc(tmp_path / "reg8" / "constraints.sdc")
    assert len(read.problems) == 3 and all("the source says nothing yet" in p for p in read.problems)
    fill(tmp_path / "reg8")
    assert chipflow.read_chip(tmp_path / "reg8")[1] == []
    ports = {"clk": "input", "rst": "input", "en": "input", "d": "input", "q": "output"}
    assert chipflow.read_sdc(tmp_path / "reg8" / "constraints.sdc", ports).problems == []


@needs_verilator
@needs_iverilog
def test_the_templates_rtl_lints_clean_and_its_bench_prints_the_3_measures(tmp_path):
    command("chip", "init", tmp_path / "reg8", "--top", "reg8")
    rtl, bench = tmp_path / "reg8" / "rtl" / "reg8.v", tmp_path / "reg8" / "tb" / "tb_reg8.v"
    lint = subprocess.run(
        ["verilator", "--lint-only", "-Wall", "--top-module", "reg8", str(rtl)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert (lint.returncode, lint.stdout + lint.stderr) == (0, "")
    built = subprocess.run(
        ["iverilog", "-g2012", "-o", str(tmp_path / "tb.vvp"), str(bench), str(rtl)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert built.returncode == 0, built.stderr
    ran = subprocess.run(["vvp", "-n", str(tmp_path / "tb.vvp")], capture_output=True, text=True, check=False)
    assert ran.returncode == 0
    assert ran.stdout.splitlines()[:3] == ["errors = 0", "checks = 4", "x_outputs = 0"]


def fake_gates(monkeypatch, behaviour: dict) -> list[str]:
    """Stand-in gates: each passes unless `behaviour` names it. Returns the list of gates as they run."""
    ran: list[str] = []

    def make(name: str):
        def gate(run):
            ran.append(name)
            said = behaviour.get(name, "pass")
            if said == "skip":
                return run.skip(name, "its engine is absent", engine=True)
            failures = [f"{name} is wrong"] if said == "fail" else []
            warnings = ["a thing to look at"] if said == "warn" else []
            return run.result(name, failures, warnings, "1 thing")

        return gate

    monkeypatch.setattr(chipflow, "gate_function", make)
    return ran


def gates_args(folder: Path, out: Path, **more) -> types.SimpleNamespace:
    values = {
        "project": str(folder),
        "out": str(out),
        "strict": False,
        "jobs": None,
        "timeout": None,
        "corner": None,
    }
    return types.SimpleNamespace(**{**values, "json": False, **more})


@needs_kit
def test_the_gates_run_in_order_and_stop_at_the_first_that_does_not_pass(tmp_path, monkeypatch, capsys):
    cli = load_cli()
    command("chip", "init", tmp_path / "reg8", "--top", "reg8")
    fill(tmp_path / "reg8")
    ran = fake_gates(monkeypatch, {})
    assert chipflow.cmd_gates(gates_args(tmp_path / "reg8", tmp_path / "o"), cli) == 0
    assert ran == list(chipflow.GATE_NAMES)
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == f"GREEN: reg8  report {tmp_path / 'o' / 'gates.json'}"
    assert lines[-2].startswith(
        f"scope: open engines, sky130A {VERSION}, decks: magic (community), klayout-mr "
    )
    assert lines[-2].endswith("nom_tt_025C_1v80; no foundry deck ran; no shuttle's limits were checked")
    records = json.loads((tmp_path / "o" / "gates.json").read_text(encoding="utf-8"))
    assert [r["gate"] for r in records] == list(chipflow.GATE_NAMES)

    ran = fake_gates(monkeypatch, {"sta": "fail"})
    assert chipflow.cmd_gates(gates_args(tmp_path / "reg8", tmp_path / "o"), cli) == 1
    assert ran == ["lint", "sim", "synth", "layout", "sta"]
    lines = capsys.readouterr().out.splitlines()
    assert "       - sta is wrong" in lines and lines[-1].startswith("RED: reg8")

    ran = fake_gates(monkeypatch, {"synth": "skip"})
    assert chipflow.cmd_gates(gates_args(tmp_path / "reg8", tmp_path / "o"), cli) == 2
    assert ran == ["lint", "sim", "synth"]
    assert capsys.readouterr().out.splitlines()[-1] == (
        f"SKIPPED (SYNTH: its engine is absent): reg8  report {tmp_path / 'o' / 'gates.json'}"
    )

    ran = fake_gates(monkeypatch, {"drc": "warn"})
    assert chipflow.cmd_gates(gates_args(tmp_path / "reg8", tmp_path / "o"), cli) == 0
    lines = capsys.readouterr().out.splitlines()
    assert "       - warning: a thing to look at" in lines and lines[-1].startswith(
        "GREEN with 1 warning: reg8"
    )
    ran = fake_gates(monkeypatch, {"drc": "warn"})
    assert chipflow.cmd_gates(gates_args(tmp_path / "reg8", tmp_path / "o", strict=True), cli) == 1
    assert ran[-1] == "drc"


@needs_kit
def test_one_gate_runs_alone_and_one_corner_is_never_taken_for_all(tmp_path, monkeypatch, capsys):
    cli = load_cli()
    command("chip", "init", tmp_path / "reg8", "--top", "reg8")
    fill(tmp_path / "reg8")
    ran = fake_gates(monkeypatch, {})
    args = gates_args(tmp_path / "reg8", tmp_path / "o", corner="nom_tt_025C_1v80")
    assert chipflow.cmd_gates(args, cli, only="sta") == 0
    assert ran == ["sta"]
    lines = capsys.readouterr().out.splitlines()
    assert lines[1] == (
        "       - warning: --corner nom_tt_025C_1v80: 1 corner ran of the 15 the project's ranges select"
    )
    assert lines[-1] == "GREEN with 1 warning: reg8"
    assert not (tmp_path / "o" / "gates.json").exists()  # 1 gate alone writes no report of the whole run
    args = gates_args(tmp_path / "reg8", tmp_path / "o", corner="nom_tt_025C_1v80", strict=True)
    assert chipflow.cmd_gates(args, cli, only="sta") == 1


@needs_kit
def test_a_gate_that_is_not_built_is_a_skip_and_the_runs_verdict(tmp_path, monkeypatch, capsys):
    """The driver runs before all its gates exist: a gate whose function is absent did not run, and a
    chip run with a gate that did not run is SKIPPED with exit code 2, never GREEN."""
    cli = load_cli()
    command("chip", "init", tmp_path / "reg8", "--top", "reg8")
    fill(tmp_path / "reg8")
    real = chipflow.gate_function

    def lint_only(name: str):
        if name == "lint":
            return lambda run: run.result("lint", [], [], "1 thing")
        return None  # as gate_function answers for a module or a function that is not there

    monkeypatch.setattr(chipflow, "gate_function", lint_only)
    assert chipflow.cmd_gates(gates_args(tmp_path / "reg8", tmp_path / "o"), cli) == 2
    lines = capsys.readouterr().out.splitlines()
    assert lines[1].startswith("SKIP   sim        the SIM gate is not built in this workcenter")
    assert lines[-1] == (
        "SKIPPED (SIM: the SIM gate is not built in this workcenter): reg8  "
        f"report {tmp_path / 'o' / 'gates.json'}"
    )
    # a module that is not there is a gate that is not built; an error inside a module is an error
    monkeypatch.setattr(chipflow, "gate_function", real)
    monkeypatch.setattr(chipflow, "GATES", (("lint", "no_such_chip_module"),))
    assert chipflow.gate_function("lint") is None


def test_the_board_gates_name_the_chip_command_for_a_chip_folder(tmp_path):
    command("chip", "init", tmp_path / "reg8", "--top", "reg8")
    folder = tmp_path / "reg8"
    ran = command("gates", folder)
    assert ran.returncode == 1 and ran.stdout == ""
    assert ran.stderr.strip() == (
        f"{folder}: a chip project (it holds chip.json): run `workcenter chip gates {folder}`"
    )
    missing = command("chip", "gates", tmp_path / "nothing")
    assert missing.returncode == 1 and "no chip.json: a chip project is a folder with one" in missing.stderr


def test_the_doctor_lists_the_chip_engines_only_where_the_chip_step_ran(tmp_path):
    bare = command("--json", "doctor", env={"WORKCENTER_CHIP_TOOLS": str(tmp_path / "none")})
    said = json.loads(bare.stdout)
    assert (
        said["chip_engines"] is False
        and "verilator" not in said["checks"]
        and "pdk sky130A" not in said["checks"]
    )
    text = command("doctor", env={"WORKCENTER_CHIP_TOOLS": str(tmp_path / "none")}).stdout
    assert f"no chip engines in {tmp_path / 'none'}: `sudo ./install.sh --chip` adds them" in text
    # an empty chip folder is a chip step that lost its engines: each is then listed as absent
    (tmp_path / "chip").mkdir()
    there = json.loads(
        command("--json", "doctor", env={"WORKCENTER_CHIP_TOOLS": str(tmp_path / "chip")}).stdout
    )
    assert there["chip_engines"] is True
    assert there["checks"]["pdk sky130A"] == {
        "required": False,
        "ok": False,
        "version": "",
        "path": str(tmp_path / "chip" / "pdk" / "sky130A"),
    }
    assert set(chipflow.ENGINES) - {"sta"} | {"opensta"} <= set(there["checks"])
