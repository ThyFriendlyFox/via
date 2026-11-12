"""Chip projects: what every chip gate shares.

A chip project is a folder with `chip.json`: RTL, test benches and timing constraints that go to a
GDSII layout on an open process. `workcenter chip gates <project>` runs 10 gates in order and stops
at the first that does not pass: LINT, SIM, SYNTH, LAYOUT, STA, GLSIM, DRC, ANTENNA, LVS, EXPORT.
This module reads `chip.json`, the constraints and a process table (`pdks/<name>.json`), selects the
timing corners, finds the engines, starts them, keeps the hash of each file a gate hands on, and
drives the gates to a verdict. It uses the standard library only.

THE CONTRACT A GATE IS WRITTEN TO

A gate is a function `gate_<name>(run)` that returns the command line's own `Result`. `GATES` says
which module holds it: LINT, SIM, SYNTH and GLSIM are in `tools/chipfront.py`, the others in
`tools/chipback.py`. A gate whose module or function is absent is skipped as "not built".

`run` is a `Run`:

    run.cli            the command-line module (tools/workcenter): `Result`, `read_expect`
    run.project        the project's folder; a gate never writes into it
    run.out            the output folder, <project>/build or --out; everything is under run.out/chip
    run.chip           the project as chip.json states it, read and found sound (`Chip`)
    run.pdk            the process table with its folder resolved (`Pdk`), or None; `run.need_pdk()`
    run.corners        the timing corners the project's ranges select (`Corner`), for STA
    run.corner_problems  lines STA fails on before it runs: a range no library corner covers
    run.strict, run.jobs, run.only_corner, run.timeout

    run.fresh(gate)            the gate's own folder, run.out/chip/<gate>, emptied: a report of an
                               earlier run can never be read as this run's
    run.engine(name)           the engine's path (`ENGINES` names them), or None when it is absent
    run.start(command, cwd, log, timeout=None, env=None) -> Started
                               the 1 place an engine starts: standard input from /dev/null, HOME in
                               the output folder, a time limit, output into `log`. Judge
                               `started.text` and the reports the engine wrote, never the exit code
                               alone; `started.problem(what)` is the failure line for an engine that
                               exited non-zero or passed its time limit, else None
    run.record(gate, path)     keep the SHA256 of a file this gate wrote or judged; safe from each
                               thread of a gate's pool
    run.forget(gate)           drop the entries of a gate's own folder, before the gate runs again
    run.take(path)             (path, None) when the file is there with the hash a gate recorded,
                               else (path, problem): a later gate judges only such files
    run.need_pdk(gate), run.need_engines(gate, *names)
                               a skip `Result` when the process kit or an engine is absent, else None
    run.result(gate, failures, warnings, summary, details=None, artifacts=())
                               the gate's `Result`: pass, or fail when a failure is named; with
                               --strict each warning is a failure too
    run.skip(gate, reason, engine=False)
                               a skip. Every chip gate is required, so a skip is the run's verdict

The files a gate hands on have fixed names (`top` is chip.json's `top`):

    run.mapped_netlist()       chip/synth/<top>.v           SYNTH writes it
    run.final_netlist()        chip/layout/<top>.v          LAYOUT; what STA, GLSIM and LVS judge
    run.power_netlist()        chip/layout/<top>.pwr.v      LAYOUT, with the supply pins, for LVS
    run.def_file()             chip/layout/<top>.def        LAYOUT
    run.database()             chip/layout/<top>.odb        LAYOUT, the routed database, for ANTENNA
    run.gds()                  chip/layout/<top>.gds        LAYOUT; what DRC and LVS judge
    run.spef(wire)             chip/layout/<top>.<wire>.spef    LAYOUT, 1 for each wire corner
    run.sdf(corner)            chip/sta/<corner>/<top>.sdf      STA
    run.measures(gate, bench)  chip/<gate>/<bench>/measures.json    SIM and GLSIM: {name: value}

A failure line of a gate starts with what is wrong and names the file and the number. The driver
prints it under the gate, and `workcenter next` keys its hints on `<gate>: <line>`.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent.parent
PDK_DIR = SRC_DIR / "pdks"
TEMPLATE_DIR = SRC_DIR / "templates" / "chip"
CHIP_FILE = "chip.json"
GATES = (
    ("lint", "chipfront"),
    ("sim", "chipfront"),
    ("synth", "chipfront"),
    ("layout", "chipback"),
    ("sta", "chipback"),
    ("glsim", "chipfront"),
    ("drc", "chipback"),
    ("antenna", "chipback"),
    ("lvs", "chipback"),
    ("export", "chipback"),
)
GATE_NAMES = tuple(name for name, _ in GATES)
# Seconds an engine may run in each gate; --timeout sets another. A build that stands still is a failure.
TIME_LIMITS = {"lint": 300, "sim": 600, "synth": 900, "layout": 7200, "sta": 900, "glsim": 900}
DEFAULT_LIMIT = 1800
# 1 change of the ledger of hashes at a time, whichever thread of a gate's pool makes it.
LEDGER_LOCK = threading.Lock()
# A gate that passes writes this file into its own folder; EXPORT asks each of the 9 gates for it.
PASSED = "passed.json"
# Each engine: where it is looked for ("path": on PATH; "chip": the chip folder's bin/, then PATH),
# the arguments that make it print its version, and the pattern that reads the version.
ENGINES = {
    "verilator": ("path", ["--version"], r"Verilator (\S+)"),
    "iverilog": ("path", ["-V"], r"Icarus Verilog version (\S+)"),
    "vvp": ("path", ["-V"], r"Icarus Verilog runtime version (\S+)"),
    "yosys": ("path", ["-V"], r"Yosys (\S+)"),
    "klayout": ("path", ["-v"], r"KLayout (\S+)"),
    "openroad": ("chip", ["-version"], r"^(\S+)"),
    "sta": ("chip", ["-version"], r"^(\S+)"),
    "magic": ("chip", ["--version"], r"^(\S+)"),
    "netgen": ("chip", ["-batch", "quit"], r"Netgen (\S+)"),
}
PROCESSES = ("slow", "typical", "fast")
# The keys of a library's blocks in a process table (pdks/README.md, "Keys").
TABLE_BLOCKS = {
    "verilog": ("files", "defines", "source"),
    "cells": (
        "prefix",
        "flop_with_reset",
        "flop_without_reset",
        "latch",
        "clock_gate",
        "tie_high",
        "tie_low",
        "tap",
        "fill",
        "decap",
        "diode",
        "clock_root",
        "clock_buffers",
        "dont_use",
        "source",
    ),
    "supply": ("power", "ground", "source"),
    "floorplan": (
        "site",
        "tracks",
        "tap_distance_um",
        "pin_layers",
        "wire_rc_layers",
        "wire_capacitance_ff_per_um",
        "routing_layers",
        "grid",
        "placement_density",
        "repair",
        "core_margin_um",
        "source",
    ),
}
# Where a cell of a `dont_use` list is kept out: of the mapping; of the mapping and of the layout build.
DONT_USE = ("synthesis", "layout")
# What the layout build's repair takes from the table: 2 margins in percent, then a count of passes.
REPAIR = ("slew_margin_percent", "capacitance_margin_percent", "antenna_iterations")
IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


# ----------------------------------------------------------------- chip.json


def stated(text: object) -> bool:
    """Whether a source or a reason says something: text, and not the template's own `fill: ...`."""
    return isinstance(text, str) and bool(text.strip()) and not text.strip().lower().startswith("fill:")


def number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass
class Chip:
    """A project as its chip.json states it. `rtl` holds the files the patterns match, in order."""

    top: str
    rtl: list[Path]
    constraints: Path
    pdk_name: str
    library: str
    pdk_version: str
    temperature: tuple[float, float]
    supply: float
    supply_tolerance: float
    die_um: tuple[float, float] | None = None
    utilization_max: float | None = None
    clock_skew_max_ns: float | None = None
    rtl_only: dict[str, str] = field(default_factory=dict)
    flops_without_reset: list[dict] = field(default_factory=list)


def unknown(block: dict, known: tuple[str, ...], where: str, problems: list[str]) -> None:
    for key in sorted(set(block) - set(known)):
        problems.append(f"{where}: unknown key {key!r} (it takes: {', '.join(known)})")


def sourced(block: object, where: str, problems: list[str], keys: tuple[str, ...]) -> dict:
    """A block that holds numbers and the `source` they come from. Returns it, or {} when it is no
    object; a problem is named for each key it may not hold and for a source that says nothing."""
    if not isinstance(block, dict):
        problems.append(f"{where}: not an object with {', '.join(keys)} and source")
        return {}
    unknown(block, (*keys, "source"), where, problems)
    if not stated(block.get("source")):
        left = isinstance(block.get("source"), str) and block["source"].strip()
        said = "the source still starts with fill:" if left else "no source:"
        problems.append(f"{where}: {said} write where the numbers come from")
    return block


def bound(block: object, where: str, problems: list[str]) -> float | None:
    """A limit as `{"max": number, "source": text}`; `req` may name a requirement."""
    block = sourced(block, where, problems, ("max", "req"))
    if not block:
        return None
    if not number(block.get("max")) or block["max"] <= 0:
        problems.append(f"{where}.max: {block.get('max')!r} is not a number over 0")
        return None
    return float(block["max"])


def read_chip(project: Path) -> tuple[Chip | None, list[str]]:
    """The project's chip.json: (Chip, []) when it is sound, else (None, problems). A problem is a line
    of the file a gate cannot act on: a key it does not know, a number without its source, text the
    template left as `fill:`. Every line starts with `chip.json: `."""
    path = project / CHIP_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return None, [f"{CHIP_FILE}: not found in {project}"]
    except ValueError as exc:
        return None, [f"{CHIP_FILE}: not JSON: {exc}"]
    if not isinstance(data, dict):
        return None, [f"{CHIP_FILE}: not an object"]
    problems: list[str] = []
    known = ("top", "rtl", "constraints", "pdk", "corners", "floorplan", "limits", "benches", "answers")
    unknown(data, known, "top level", problems)

    top = data.get("top")
    if not isinstance(top, str) or not IDENTIFIER_RE.match(top):
        problems.append(f"top: {top!r} is not a module name")
        top = ""
    patterns = data.get("rtl", ["rtl/*.v", "rtl/*.sv"])
    rtl: list[Path] = []
    if not isinstance(patterns, list) or not all(isinstance(p, str) and p for p in patterns):
        problems.append("rtl: not a list of file patterns")
    else:
        for pattern in patterns:
            found = sorted(p for p in project.glob(pattern) if p.is_file())
            outside = [p for p in found if project.resolve() not in p.resolve().parents]
            if outside or pattern.startswith("/") or ".." in Path(pattern).parts:
                problems.append(f"rtl: {pattern!r} leaves the project's folder")
                continue
            rtl += [p for p in found if p not in rtl]
    constraints = data.get("constraints", "constraints.sdc")
    if not isinstance(constraints, str) or not constraints or ".." in Path(constraints).parts:
        problems.append(f"constraints: {constraints!r} is not a file of the project")
        constraints = "constraints.sdc"

    pdk = data.get("pdk")
    if not isinstance(pdk, dict):
        problems.append("pdk: not an object with name, library, version and source")
        pdk = {}
    else:
        unknown(pdk, ("name", "library", "version", "source"), "pdk", problems)
        for key in ("name", "library", "version", "source"):
            if not stated(pdk.get(key)):
                problems.append(
                    f"pdk.{key}: not written"
                    + (" (the text still starts with fill:)" if pdk.get(key) else "")
                )

    corners = data.get("corners")
    temperature, supply, tolerance = (0.0, 0.0), 0.0, 0.0
    if not isinstance(corners, dict):
        problems.append("corners: not an object with temperature and supply: STA runs at the ranges it names")
    else:
        unknown(corners, ("temperature", "supply"), "corners", problems)
        block = sourced(corners.get("temperature"), "corners.temperature", problems, ("values",))
        values = block.get("values")
        if (
            isinstance(values, list)
            and len(values) == 2
            and all(number(v) for v in values)
            and values[0] <= values[1]
        ):
            temperature = (float(values[0]), float(values[1]))
        elif block:
            problems.append(f"corners.temperature.values: {values!r} is not [least, greatest] in C")
        block = sourced(corners.get("supply"), "corners.supply", problems, ("nominal", "tolerance"))
        if block:
            if number(block.get("nominal")) and block["nominal"] > 0:
                supply = float(block["nominal"])
            else:
                problems.append(f"corners.supply.nominal: {block.get('nominal')!r} is not a voltage over 0")
            if number(block.get("tolerance")) and 0 <= block["tolerance"] < 1:
                tolerance = float(block["tolerance"])
            else:
                problems.append(
                    f"corners.supply.tolerance: {block.get('tolerance')!r} is not a fraction from 0 to "
                    "under 1 (0.05 is 5 %)"
                )

    die = None
    if "floorplan" in data:
        block = sourced(data["floorplan"], "floorplan", problems, ("die_um",))
        size = block.get("die_um")
        if isinstance(size, list) and len(size) == 2 and all(number(v) and v > 0 for v in size):
            die = (float(size[0]), float(size[1]))
        elif block:
            problems.append(f"floorplan.die_um: {size!r} is not [width, height] in micrometres")
    utilization = skew = None
    if "limits" in data:
        limits = data["limits"]
        if not isinstance(limits, dict):
            problems.append("limits: not an object")
        else:
            unknown(limits, ("utilization", "clock_skew_ns"), "limits", problems)
            if "utilization" in limits:
                utilization = bound(limits["utilization"], "limits.utilization", problems)
                if utilization is not None and utilization > 1:
                    problems.append(f"limits.utilization.max: {utilization:g} is over 1 (0.6 is 60 %)")
            if "clock_skew_ns" in limits:
                skew = bound(limits["clock_skew_ns"], "limits.clock_skew_ns", problems)
    rtl_only: dict[str, str] = {}
    benches = data.get("benches", {})
    if not isinstance(benches, dict):
        problems.append("benches: not an object of bench: answer")
    else:
        for name, entry in benches.items():
            if not isinstance(entry, dict) or set(entry) != {"rtl_only"} or not stated(entry.get("rtl_only")):
                problems.append(
                    f'benches.{name}: not {{"rtl_only": the reason the bench cannot run on the netlist}}'
                )
            else:
                rtl_only[name] = entry["rtl_only"].strip()
    answers = data.get("answers", {})
    flops: list[dict] = []
    if not isinstance(answers, dict):
        problems.append("answers: not an object")
    else:
        unknown(answers, ("flops_without_reset",), "answers", problems)
        listed = answers.get("flops_without_reset", [])
        if not isinstance(listed, list):
            problems.append("answers.flops_without_reset: not a list")
            listed = []
        for n, entry in enumerate(listed):
            where = f"answers.flops_without_reset[{n}]"
            if not isinstance(entry, dict) or set(entry) != {"match", "why", "evidence"}:
                problems.append(f"{where}: not an object with match, why and evidence")
            elif not all(stated(entry[key]) for key in ("match", "why", "evidence")):
                problems.append(
                    f"{where}: match, why and evidence each say something, and none starts with fill:"
                )
            else:
                flops.append(entry)
    if problems:
        return None, [f"{CHIP_FILE}: {p}" for p in problems]
    return (
        Chip(
            top=top,
            rtl=rtl,
            constraints=project / constraints,
            pdk_name=pdk["name"].strip(),
            library=pdk["library"].strip(),
            pdk_version=pdk["version"].strip(),
            temperature=temperature,
            supply=supply,
            supply_tolerance=tolerance,
            die_um=die,
            utilization_max=utilization,
            clock_skew_max_ns=skew,
            rtl_only=rtl_only,
            flops_without_reset=flops,
        ),
        [],
    )


# ------------------------------------------------------------- the constraints

SDC_COMMANDS = (
    "create_clock",
    "set_clock_uncertainty",
    "set_input_delay",
    "set_output_delay",
    "set_driving_cell",
    "set_input_transition",
    "set_load",
    "set_max_fanout",
    "set_max_transition",
    "set_timing_derate",
    "set_false_path",
    "set_multicycle_path",
)
SDC_EXCEPTIONS = ("set_false_path", "set_multicycle_path")
# The commands a constraint may hold in brackets: each only names objects of the design.
SDC_QUERIES = ("get_ports", "get_clocks", "get_pins", "get_nets", "all_inputs", "all_outputs", "all_clocks")
SDC_MODE = ("set_propagated_clock", "set_ideal_network", "set_ideal_latency", "set_clock_latency")
SOURCE_RE = re.compile(r";\s*#\s*source:\s*(.*)\Z", re.IGNORECASE)
NUMBER_RE = re.compile(r"(?<![\w.{\[])-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?(?![\w.\]}*])")


@dataclass
class Sdc:
    """What the gates read from a constraints file. `problems` start with the file's name."""

    clock_port: str = ""
    clock_name: str = ""
    period_ns: float | None = None
    max_fanout: bool = False
    problems: list[str] = field(default_factory=list)


def sdc_statements(text: str) -> list[tuple[int, str]]:
    """(line number, text) for each statement: a line and the lines it continues onto with a `\\`."""
    out: list[tuple[int, str]] = []
    pending, first = "", 0
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not pending:
            first = n
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        out.append((first, (pending + line).strip()))
        pending = ""
    if pending:
        out.append((first, pending.strip()))
    return out


def port_patterns(statement: str) -> tuple[bool, list[str]]:
    """What a delay command covers: (every port of its direction, the port patterns it names)."""
    everything = bool(re.search(r"\[\s*all_(?:inputs|outputs)\b", statement))
    names: list[str] = []
    # A braced list may hold a bus as `d[*]`, whose `]` is not the end of the query.
    for braced, single in re.findall(r"\[\s*get_ports\s+(?:\{([^{}]*)\}|([^\s\]]+))", statement):
        names += (braced or single).split()
    return everything, [re.sub(r"\[[^\]]*\]\Z", "", name) for name in names]


def read_sdc(path: Path, ports: dict[str, str] | None = None) -> Sdc:
    """The constraints, read against what they may hold. `ports` is the top module's ports as
    {name: "input" | "output"} when the caller knows them: each then needs its delay.

    A constraints file is Tcl, and Tcl can do anything. So a statement is 1 command of `SDC_COMMANDS`,
    its brackets hold only the queries of `SDC_QUERIES`, it holds no variable and no second command,
    and a statement with a number or a path exception ends with `;# source: <where it comes from>`."""
    name = path.name
    sdc = Sdc()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        sdc.problems.append(f"{name}: not found: write the clock, and a delay for each input and output")
        return sdc
    clocks: list[tuple[int, str]] = []
    covered = {"input": (False, []), "output": (False, [])}
    for line, statement in sdc_statements(text):
        if not statement or statement.startswith("#"):
            continue
        where = f"{name}: line {line}"
        source = SOURCE_RE.search(statement)
        body = statement[: source.start()].rstrip() if source else statement
        command = body.split()[0] if body.split() else ""
        if command in SDC_MODE:
            sdc.problems.append(
                f"{where}: {command} is not for the project to write: the gates set the clock's mode, "
                "estimated before the clock tree and propagated after it"
            )
            continue
        if command not in SDC_COMMANDS:
            sdc.problems.append(
                f"{where}: {command or statement[:20]!r} is not a command the gates take "
                f"(they take: {', '.join(SDC_COMMANDS)})"
            )
            continue
        if ";" in body:
            sdc.problems.append(f"{where}: a second command after `;`: write 1 command on a line")
            continue
        if "$" in body:
            sdc.problems.append(f"{where}: a variable (`$`): write the value itself")
            continue
        asked = re.findall(r"\[\s*([A-Za-z_]\w*)", body)
        strange = [q for q in asked if q not in SDC_QUERIES]
        if strange:
            sdc.problems.append(
                f"{where}: [{strange[0]} ...] is not a query the gates take "
                f"(they take: {', '.join(SDC_QUERIES)})"
            )
            continue
        if NUMBER_RE.search(re.sub(r"\[[^\[\]]*\]", " ", body)) or command in SDC_EXCEPTIONS:
            if not source:
                sdc.problems.append(
                    f"{where}: {command} has no source: end the line with `;# source: <text>`"
                )
            elif not stated(source.group(1)):
                sdc.problems.append(
                    f"{where}: {command}: the source says nothing yet: write where the number comes from"
                )
        if command == "create_clock":
            clocks.append((line, body))
        elif command == "set_max_fanout":
            sdc.max_fanout = True
        elif command in ("set_input_delay", "set_output_delay"):
            direction = "input" if command == "set_input_delay" else "output"
            everything, names = port_patterns(body)
            covered[direction] = (covered[direction][0] or everything, covered[direction][1] + names)
    if not clocks:
        sdc.problems.append(f"{name}: no create_clock: name the clock, its period and its port")
    for line, _ in clocks[1:]:
        sdc.problems.append(
            f"{name}: line {line}: a second clock: the first flow takes 1 clock. Use 1 clock and an enable"
        )
    if clocks:
        body = clocks[0][1]
        period = re.search(r"-period\s+(-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?)", body)
        port = re.search(r"\[\s*get_ports\s+\{?\s*([^\s\]}]+)", body)
        label = re.search(r"-name\s+(\S+)", body)
        if not period or float(period.group(1)) <= 0:
            sdc.problems.append(f"{name}: line {clocks[0][0]}: create_clock has no -period over 0, in ns")
        else:
            sdc.period_ns = float(period.group(1))
        if not port:
            sdc.problems.append(f"{name}: line {clocks[0][0]}: create_clock names no port: [get_ports clk]")
        else:
            sdc.clock_port = port.group(1)
            sdc.clock_name = label.group(1) if label else sdc.clock_port
    for port, direction in sorted((ports or {}).items()):
        if direction not in covered or port == sdc.clock_port:
            continue
        everything, names = covered[direction]
        if not everything and not any(fnmatch.fnmatchcase(port, pattern) for pattern in names):
            sdc.problems.append(
                f"{name}: {direction} {port} has no set_{direction}_delay: STA cannot judge a path through it"
            )
    return sdc


# ------------------------------------------------------------ the process table


@dataclass
class Pdk:
    """A process table (`pdks/<name>.json`) with the folder its files are in. `library` is the table's
    block for the project's library. `installed` is the version the kit's own file states."""

    name: str
    root: Path
    table: dict
    library_name: str
    library: dict
    installed: str

    def file(self, relative: str) -> Path:
        return self.root / relative


@dataclass(frozen=True)
class Corner:
    """1 timing corner: a wire corner with a library corner. The name is `<wire>_<library corner>`."""

    name: str
    wire: str
    library_corner: str
    process: str
    volts: float
    celsius: float
    liberty: Path
    techlef: Path
    rcx: Path


def pdk_tables() -> list[str]:
    return sorted(p.stem for p in PDK_DIR.glob("*.json"))


def read_table(name: str) -> tuple[dict | None, list[str]]:
    """A process table by name: (table, []) or (None, problems). The reader holds the table to the
    keys the gates read; what a key means is in pdks/README.md."""
    path = PDK_DIR / f"{name}.json"
    where = f"pdks/{name}.json"
    try:
        table = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        return None, [
            f"{where}: not found; this workcenter has a table for: {', '.join(pdk_tables()) or 'no process'}"
        ]
    except ValueError as exc:
        return None, [f"{where}: not JSON: {exc}"]
    problems: list[str] = []
    top = ("name", "process", "source", "version", "magic", "klayout", "libraries", "drc", "lvs")
    if not isinstance(table, dict):
        return None, [f"{where}: not an object"]
    unknown(table, top, where, problems)
    for key in top:
        if key not in table:
            problems.append(f"{where}: no {key}")
    if table.get("name") != name:
        problems.append(f"{where}: name is {table.get('name')!r}, not the file's own name")
    version = table.get("version", {})
    if not isinstance(version, dict) or not all(
        stated(version.get(k)) for k in ("file", "pattern", "value", "source")
    ):
        problems.append(f"{where}: version: not an object with file, pattern, value and source")
    else:
        try:
            re.compile(version["pattern"])
        except re.error as exc:
            problems.append(f"{where}: version.pattern: {exc}")
    libraries = table.get("libraries", {})
    if not isinstance(libraries, dict) or not libraries:
        problems.append(f"{where}: libraries: not an object of library: block")
        libraries = {}
    for lib, block in libraries.items():
        at = f"{where}: libraries.{lib}"
        needed = (
            "source",
            "corners",
            "wires",
            "lef",
            "gds",
            "spice",
            "verilog",
            "cells",
            "supply",
            "floorplan",
        )
        if not isinstance(block, dict):
            problems.append(f"{at}: not an object")
            continue
        unknown(block, needed, at, problems)
        problems += [f"{at}: no {key}" for key in needed if key not in block]
        corners = block.get("corners", {})
        if not isinstance(corners, dict) or not corners:
            problems.append(f"{at}.corners: not an object of corner: block")
            corners = {}
        for corner, c in corners.items():
            sound = (
                isinstance(c, dict)
                and set(c) == {"liberty", "process", "volts", "celsius"}
                and isinstance(c["liberty"], str)
                and c["process"] in PROCESSES
                and number(c["volts"])
                and c["volts"] > 0
                and number(c["celsius"])
            )
            if not sound:
                problems.append(
                    f"{at}.corners.{corner}: not {{liberty, process ({', '.join(PROCESSES)}), volts, "
                    "celsius}"
                )
        wires = block.get("wires", {})
        if not isinstance(wires, dict) or not wires:
            problems.append(f"{at}.wires: not an object of wire corner: {{techlef, rcx}}")
            wires = {}
        for wire, w in wires.items():
            if (
                not isinstance(w, dict)
                or set(w) != {"techlef", "rcx"}
                or not all(isinstance(v, str) for v in w.values())
            ):
                problems.append(f"{at}.wires.{wire}: not {{techlef, rcx}}")
        # The blocks the gates' scripts read by key: each holds exactly the keys of TABLE_BLOCKS.
        for key, wanted in TABLE_BLOCKS.items():
            inner = block.get(key)
            if not isinstance(inner, dict):
                problems.append(f"{at}.{key}: not an object")
                continue
            unknown(inner, wanted, f"{at}.{key}", problems)
            problems += [f"{at}.{key}: no {k}" for k in wanted if k not in inner]
        # The kit's own lists of cells not to use are named by their files, never copied into the table.
        cells = block.get("cells")
        listed = cells.get("dont_use") if isinstance(cells, dict) else None
        if listed is not None and not (
            isinstance(listed, dict)
            and set(listed) == set(DONT_USE)
            and all(isinstance(v, list) and all(stated(f) for f in v) for v in listed.values())
        ):
            problems.append(
                f"{at}.cells.dont_use: not {{{', '.join(DONT_USE)}}}, each a list of files of the kit"
            )
        # The numbers the layout build repairs with: a number that is not one stops the build's script.
        plan = block.get("floorplan")
        wire = plan.get("wire_capacitance_ff_per_um") if isinstance(plan, dict) else None
        if wire is not None and not (
            isinstance(wire, dict)
            and set(wire) == {"signal", "clock"}
            and all(number(v) and v > 0 for v in wire.values())
        ):
            problems.append(
                f"{at}.floorplan.wire_capacitance_ff_per_um: not {{signal, clock}}, each a number over 0"
            )
        repair = plan.get("repair") if isinstance(plan, dict) else None
        if repair is not None and not (
            isinstance(repair, dict)
            and set(repair) == set(REPAIR)
            and all(number(repair[key]) and 0 <= repair[key] < 100 for key in REPAIR[:2])
            and isinstance(repair[REPAIR[2]], int)
            and not isinstance(repair[REPAIR[2]], bool)
            and repair[REPAIR[2]] >= 1
        ):
            problems.append(
                f"{at}.floorplan.repair: not {{{', '.join(REPAIR)}}}: 2 margins from 0 to under 100 and a "
                "count of 1 or more"
            )
    for key, wanted in (
        ("magic", ("rc", "tech", "needs", "source")),
        ("klayout", ("layer_properties", "layer_map", "source")),
        ("lvs", ("engine", "setup", "source")),
    ):
        inner = table.get(key)
        if isinstance(inner, dict):
            unknown(inner, wanted, f"{where}: {key}", problems)
            problems += [f"{where}: {key}: no {k}" for k in wanted if k not in inner]
        elif key in table:
            problems.append(f"{where}: {key}: not an object")
    decks = table.get("drc", [])
    if not isinstance(decks, list) or not decks:
        problems.append(f"{where}: drc: not a list of decks")
        decks = []
    for n, deck in enumerate(decks):
        sound = (
            isinstance(deck, dict)
            and stated(deck.get("name"))
            and deck.get("engine") in ("magic", "klayout")
            and deck.get("origin") in ("foundry", "community")
            and stated(deck.get("cannot"))
            and stated(deck.get("source"))
        )
        if not sound:
            problems.append(
                f"{where}: drc[{n}]: not {{name, engine (magic, klayout), origin (foundry, community), "
                "cannot, source}}"
            )
    return (None, problems) if problems else (table, [])


def chip_root(cli) -> Path:
    """The folder that holds the chip engines (`bin/`) and the process kits (`pdk/<name>/`)."""
    named = os.environ.get("WORKCENTER_CHIP_TOOLS")
    return Path(named) if named else Path(cli.WC_ROOT) / "chip"


def installed_version(root: Path, table: dict) -> str | None:
    """The version a process kit states in its own file, or None when the file is not there or says
    none: the kit is then not installed."""
    version = table["version"]
    try:
        text = (root / version["file"]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    found = re.search(version["pattern"], text, re.M)
    return found.group(1) if found else None


def read_pdk(cli, chip: Chip) -> tuple[Pdk | None, list[str], bool]:
    """The project's process: (Pdk, [], False) when the table is sound, the kit is installed and its
    version is the one chip.json names. Else (None, problems, absent): `absent` says the kit is not
    on this machine, which is a skip; every other problem is a failure."""
    table, problems = read_table(chip.pdk_name)
    if table is None:
        return None, problems, False
    library = table["libraries"].get(chip.library)
    if library is None:
        return (
            None,
            [
                f"{CHIP_FILE}: pdk.library: {chip.library!r} is not in pdks/{chip.pdk_name}.json "
                f"(it has: {', '.join(sorted(table['libraries']))})"
            ],
            False,
        )
    root = chip_root(cli) / "pdk" / chip.pdk_name
    installed = installed_version(root, table)
    if installed is None:
        return None, [f"the process kit {chip.pdk_name} is not installed in {root}"], True
    if installed != chip.pdk_version:
        return (
            None,
            [
                f"{CHIP_FILE}: pdk.version is {chip.pdk_version}, and the installed {chip.pdk_name} states "
                f"{installed}: the project is proven on 1 version"
            ],
            False,
        )
    return Pdk(chip.pdk_name, root, table, chip.library, library, installed), [], False


def select_corners(pdk: Pdk, chip: Chip) -> tuple[list[Corner], list[str]]:
    """The timing corners a project's ranges select from the table (pdks/README.md, "Corners").

    The supply's range is nominal less and plus its tolerance. A slow corner at or below the least
    supply decides setup; a fast corner at or above the greatest decides hold. For each of the 2, and
    for each end of the temperature range, the gate takes the library corner at or beyond that end
    that is nearest: nearest in volts first, then in temperature. An end with no such corner is a
    problem, never a dropped corner. Every typical corner inside both ranges runs too. Each selected
    library corner runs with every wire corner of the table."""
    low, high = chip.supply * (1 - chip.supply_tolerance), chip.supply * (1 + chip.supply_tolerance)
    cold, hot = chip.temperature
    eps = 1e-9
    corners = pdk.library["corners"]
    chosen: list[str] = []
    problems: list[str] = []

    def nearest(process: str, volts_ok, volts_far, temp_ok, temp_far, what: str) -> None:
        fit = [
            n
            for n, c in corners.items()
            if c["process"] == process and volts_ok(c["volts"]) and temp_ok(c["celsius"])
        ]
        if not fit:
            problems.append(f"no {process} library corner covers {what}")
            return
        best = min(fit, key=lambda n: (volts_far(corners[n]["volts"]), temp_far(corners[n]["celsius"]), n))
        if best not in chosen:
            chosen.append(best)

    for process, volts_ok, volts_far, supply_said in (
        ("slow", lambda v: v <= low + eps, lambda v: low - v, f"{low:g} V or less"),
        ("fast", lambda v: v >= high - eps, lambda v: v - high, f"{high:g} V or more"),
    ):
        nearest(
            process,
            volts_ok,
            volts_far,
            lambda t: t <= cold + eps,
            lambda t: cold - t,
            f"{supply_said} at {cold:g} C or colder",
        )
        nearest(
            process,
            volts_ok,
            volts_far,
            lambda t: t >= hot - eps,
            lambda t: t - hot,
            f"{supply_said} at {hot:g} C or hotter",
        )
    for name, c in sorted(corners.items()):
        inside = low - eps <= c["volts"] <= high + eps and cold - eps <= c["celsius"] <= hot + eps
        if c["process"] == "typical" and inside and name not in chosen:
            chosen.append(name)
    out: list[Corner] = []
    for wire, w in sorted(pdk.library["wires"].items()):
        for name in chosen:
            c = corners[name]
            out.append(
                Corner(
                    name=f"{wire}_{name}",
                    wire=wire,
                    library_corner=name,
                    process=c["process"],
                    volts=float(c["volts"]),
                    celsius=float(c["celsius"]),
                    liberty=pdk.file(c["liberty"]),
                    techlef=pdk.file(w["techlef"]),
                    rcx=pdk.file(w["rcx"]),
                )
            )
    return out, problems


# ------------------------------------------------------------------ the engines


def find_engine(cli, name: str) -> str | None:
    """An engine's path: the chip folder's bin/ for the engines the chip step installs, then PATH."""
    where = ENGINES.get(name, ("path",))[0]
    if where == "chip":
        local = chip_root(cli) / "bin" / name
        if local.exists():
            return str(local)
    return shutil.which(name)


def engine_version(cli, name: str) -> str | None:
    """What an engine prints as its version, or None when it is absent or prints none."""
    path = find_engine(cli, name)
    if path is None:
        return None
    _, arguments, pattern = ENGINES[name]
    try:
        proc = subprocess.run(
            [path, *arguments],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = re.search(pattern, proc.stdout + proc.stderr, re.M)
    return found.group(1) if found else None


def doctor_rows(cli) -> dict[str, dict]:
    """The chip rows of `workcenter doctor`: each engine and each process kit, none of them required."""
    rows: dict[str, dict] = {}
    for name in ENGINES:
        version = engine_version(cli, name)
        rows["opensta" if name == "sta" else name] = {
            "required": False,
            "ok": version is not None,
            "version": version,
        }
    for name in pdk_tables():
        table, _ = read_table(name)
        root = chip_root(cli) / "pdk" / name
        version = installed_version(root, table) if table else None
        rows[f"pdk {name}"] = {
            "required": False,
            "ok": version is not None,
            "version": version or "",
            "path": str(root),
        }
    return rows


@dataclass
class Started:
    """1 engine run. `exit` is None when the engine passed its time limit and was stopped."""

    command: list[str]
    exit: int | None
    timed_out: bool
    seconds: float
    limit: int
    log: Path
    text: str

    def problem(self, what: str) -> str | None:
        """The failure line for an engine that did not end well, or None. An exit code of 0 is not a
        verdict: the caller still judges what the engine wrote."""
        engine = Path(self.command[0]).name
        if self.timed_out:
            return (
                f"{what}: {engine} passed its time limit of {self.limit} s and was stopped (log {self.log})"
            )
        if self.exit != 0:
            return f"{what}: {engine} exit {self.exit} (log {self.log})"
        return None


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class Run:
    """1 run of the chip gates on 1 project: what a gate receives. The module's docstring is its
    contract."""

    cli: object
    project: Path
    out: Path
    chip: Chip
    pdk: Pdk | None = None
    pdk_problems: list[str] = field(default_factory=list)
    pdk_absent: bool = False
    corners: list[Corner] = field(default_factory=list)
    corner_problems: list[str] = field(default_factory=list)
    strict: bool = False
    jobs: int = 1
    only_corner: str | None = None
    timeout: int | None = None
    commands: list[dict] = field(default_factory=list)

    # ---- folders and the files gates hand on

    @property
    def base(self) -> Path:
        return self.out / "chip"

    def fresh(self, gate: str) -> Path:
        folder = self.base / gate
        if folder.exists():
            shutil.rmtree(folder)
        folder.mkdir(parents=True)
        return folder

    def mapped_netlist(self) -> Path:
        return self.base / "synth" / f"{self.chip.top}.v"

    def final_netlist(self) -> Path:
        return self.base / "layout" / f"{self.chip.top}.v"

    def power_netlist(self) -> Path:
        return self.base / "layout" / f"{self.chip.top}.pwr.v"

    def def_file(self) -> Path:
        return self.base / "layout" / f"{self.chip.top}.def"

    def database(self) -> Path:
        return self.base / "layout" / f"{self.chip.top}.odb"

    def gds(self) -> Path:
        return self.base / "layout" / f"{self.chip.top}.gds"

    def spef(self, wire: str) -> Path:
        return self.base / "layout" / f"{self.chip.top}.{wire}.spef"

    def sdf(self, corner: str) -> Path:
        return self.base / "sta" / corner / f"{self.chip.top}.sdf"

    def measures(self, gate: str, bench: str) -> Path:
        return self.base / gate / bench / "measures.json"

    # ---- engines

    def engine(self, name: str) -> str | None:
        return find_engine(self.cli, name)

    def start(
        self,
        command: list,
        cwd: Path,
        log: Path,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
        at_most: int | None = None,
    ) -> Started:
        """Start 1 engine and wait for it. Standard input is /dev/null (Magic and Netgen wait on a
        terminal), HOME is a folder of the run (an engine reads its start file from the user's home),
        the output goes to `log`, and an engine past its time limit is stopped with its children.
        `timeout` is the gate's limit, which --timeout replaces. `at_most` is a limit that --timeout
        cannot raise: a run that is meant to be stopped when it takes far longer than its like."""
        limit = self.timeout or timeout or DEFAULT_LIMIT
        if at_most is not None:
            limit = min(limit, at_most)
        home = self.base / "home"
        home.mkdir(parents=True, exist_ok=True)
        log.parent.mkdir(parents=True, exist_ok=True)
        words = [str(c) for c in command]
        t0 = time.monotonic()
        timed_out = False
        with log.open("w", encoding="utf-8") as fh:
            proc = subprocess.Popen(
                words,
                cwd=str(cwd),
                stdin=subprocess.DEVNULL,
                stdout=fh,
                stderr=subprocess.STDOUT,
                env={**os.environ, **(env or {}), "HOME": str(home)},
                start_new_session=True,
            )
            try:
                code: int | None = proc.wait(timeout=limit)
            except subprocess.TimeoutExpired:
                timed_out, code = True, None
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
        seconds = round(time.monotonic() - t0, 2)
        text = log.read_text(encoding="utf-8", errors="replace")
        self.commands.append(
            {"command": words, "cwd": str(cwd), "exit": code, "seconds": seconds, "log": str(log)}
        )
        return Started(words, code, timed_out, seconds, limit, log, text)

    # ---- the ledger of hashes

    def ledger(self) -> dict:
        try:
            return json.loads((self.base / "hashes.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _change_ledger(self, change) -> None:
        """Read the ledger, change it and write it back as 1 step, for every thread of this run. A gate
        runs its benches and its corners in a pool, and each records what it wrote: 2 threads that read
        the same ledger each wrote it back without the other's entry (5 of 30 runs of SIM at 4 jobs lost
        entries on 2026-11-11). The file is written beside itself and moved into place, so a reader
        finds a whole ledger at every moment. 2 processes that write 1 output folder are not held."""
        with LEDGER_LOCK:
            ledger = self.ledger()
            changed = change(ledger)
            if changed is None:
                return
            self.base.mkdir(parents=True, exist_ok=True)
            target = self.base / "hashes.json"
            beside = target.with_name(f"hashes.json.{os.getpid()}.{threading.get_ident()}.part")
            beside.write_text(json.dumps(changed, indent=2, sort_keys=True), encoding="utf-8")
            os.replace(beside, target)

    def record(self, gate: str, path: Path) -> str:
        """Keep the SHA256 of a file `gate` wrote or judged. Returns the hash."""
        digest = sha256(path)
        name = str(path.relative_to(self.out))

        def add(ledger: dict) -> dict:
            ledger[name] = {"sha256": digest, "gate": gate}
            return ledger

        self._change_ledger(add)
        return digest

    def forget(self, gate: str) -> None:
        """Drop each entry of a gate's own folder: what the gate handed on before stands for nothing
        until it writes it again."""

        def drop(ledger: dict) -> dict | None:
            kept = {name: entry for name, entry in ledger.items() if not name.startswith(f"chip/{gate}/")}
            return kept if kept != ledger else None

        self._change_ledger(drop)

    # ---- the record of a gate's pass

    def begin(self, gate: str) -> Path:
        """The gate's own folder, emptied, with nothing of it left in the ledger of hashes and no
        hand-off folder: what the gate handed on before stands for nothing until it passes again. A
        gate calls this before it reads any input, so a run that ends in any other way than a pass
        leaves no record of a pass and no report of an earlier run behind."""
        self.forget(gate)
        shutil.rmtree(self.base / "tapeout", ignore_errors=True)
        return self.fresh(gate)

    def name_of(self, path: Path) -> str:
        """A file's name in a record: from the output folder for what a gate wrote, from the project's
        folder for the project's own files."""
        path = Path(path)
        for folder in (self.out, self.project):
            try:
                return str(path.resolve().relative_to(folder.resolve()))
            except ValueError:
                continue
        return str(path)

    def file_of(self, name: str) -> Path:
        """The file a record's name stands for: `name_of`, read back."""
        return self.out / name if name.startswith("chip/") else self.project / name

    def judged(self, paths) -> dict[str, str]:
        """{name: SHA256} of the files a gate judged, for its record of a pass."""
        return {self.name_of(path): sha256(path) for path in paths if Path(path).is_file()}

    def write_passed(self, gate: str, judged: dict[str, str], reports=(), **more) -> None:
        """The record that `gate` passed, `chip/<gate>/passed.json`: the hash of each file it judged,
        and the reports that say so."""
        path = self.base / gate / PASSED
        record = {"gate": gate, "judged": judged, "reports": [self.name_of(p) for p in reports], **more}
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, sort_keys=True), encoding="utf-8")
        self.record(gate, path)

    def read_passed(self, gate: str) -> tuple[dict | None, str | None, bool]:
        """A gate's record of its pass as (record, None, False), or (None, why not, whether the gate
        only did not run or did not pass: a skip for the gate that asks, where a record that changed
        is a failure)."""
        folder = self.base / gate
        path = folder / PASSED
        if not path.is_file():
            said = "did not pass" if folder.is_dir() and any(folder.iterdir()) else "has not run"
            return None, f"{gate.upper()} {said} in {self.out}", True
        _, problem = self.take(path)
        if problem:
            return None, problem, False
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return None, f"{self.name_of(path)} is not JSON", False
        if not isinstance(record, dict) or not isinstance(record.get("judged"), dict):
            return None, f"{self.name_of(path)} names no judged files", False
        return record, None, False

    def changed_since(self, gate: str, record: dict) -> list[str]:
        """A line for each file of a gate's record that is not the bytes the gate judged."""
        said = []
        for name, digest in record["judged"].items():
            path = self.file_of(name)
            again = f"{gate.upper()} passed: its hash differs. Run the gates again"
            if not path.is_file():
                said.append(f"{name} is gone since {gate.upper()} passed on it. Run the gates again")
            elif sha256(path) != digest:
                said.append(f"{name} changed after {again}")
        return said

    def take(self, path: Path) -> tuple[Path, str | None]:
        """A file a gate before this one handed on: (path, None) when it is there with the hash that
        gate recorded, else (path, the problem). A file changed after a gate judged it is refused."""
        relative = str(path.relative_to(self.out))
        entry = self.ledger().get(relative)
        if not path.is_file():
            return path, f"{relative} is not there: the gate that writes it has not run in {self.out}"
        if entry is None:
            return path, f"{relative}: no gate of this run recorded it"
        if sha256(path) != entry["sha256"]:
            return path, f"{relative} changed after {entry['gate'].upper()} recorded it: its hash differs"
        return path, None

    # ---- results

    def need_pdk(self, gate: str):
        """None when the process kit is ready. Else the gate's Result: a skip when the kit is not
        installed, a failure for a table or a version the project does not match."""
        if self.pdk is not None:
            return None
        problems = list(self.pdk_problems) or ["the process table was not read"]
        if self.pdk_absent:
            return self.skip(gate, problems[0], engine=True)
        return self.result(gate, problems, [], "the process table")

    def need_engines(self, gate: str, *names: str):
        absent = [name for name in names if self.engine(name) is None]
        if not absent:
            return None
        said = ", ".join(absent)
        return self.skip(
            gate, f"{said} is not installed: `workcenter doctor` lists the chip engines", engine=True
        )

    def result(
        self,
        gate: str,
        failures: list[str],
        warnings: list[str],
        summary: str,
        details: dict | None = None,
        artifacts: tuple | list = (),
    ):
        failures = list(failures) + (list(warnings) if self.strict else [])
        warnings = [] if self.strict else list(warnings)
        counts = f"{len(failures)} failures" + (f", {len(warnings)} warnings" if warnings else "")
        return self.cli.Result(
            gate,
            "fail" if failures else "pass",
            f"{summary}, {counts}" if summary else counts,
            {**(details or {}), "failures": failures, "warnings": warnings},
            [str(a) for a in artifacts],
        )

    def skip(self, gate: str, reason: str, engine: bool = False):
        return self.cli.Result(gate, "skip", reason, {"engine_missing": engine, "reason": reason})


# -------------------------------------------------------------------- the driver


def gate_function(name: str):
    """The function of a gate, or None while its module or the function is not built."""
    module_name = dict(GATES)[name]
    sys.path.insert(0, str(SRC_DIR / "tools"))
    try:
        module = __import__(module_name)
    except ModuleNotFoundError as exc:
        if exc.name != module_name:
            raise
        return None
    return getattr(module, f"gate_{name}", None)


def find_chip(target: str) -> Path:
    path = Path(target).resolve()
    if path.is_file() and path.name == CHIP_FILE:
        path = path.parent
    if not (path / CHIP_FILE).is_file():
        raise SystemExit(
            f"{path}: no {CHIP_FILE}: a chip project is a folder with one (`workcenter chip init`)"
        )
    return path


def prepare(cli, project: Path, out: Path, args) -> tuple[Run | None, list[str]]:
    """The Run for a project, or (None, the problems of its chip.json)."""
    chip, problems = read_chip(project)
    if chip is None:
        return None, problems
    run = Run(
        cli=cli,
        project=project,
        out=out,
        chip=chip,
        strict=getattr(args, "strict", False),
        jobs=getattr(args, "jobs", None) or min(os.cpu_count() or 1, 8),
        only_corner=getattr(args, "corner", None),
        timeout=getattr(args, "timeout", None),
    )
    run.pdk, run.pdk_problems, run.pdk_absent = read_pdk(cli, chip)
    if run.pdk is not None:
        run.corners, run.corner_problems = select_corners(run.pdk, chip)
        if run.only_corner:
            named = [c for c in run.corners if c.name == run.only_corner]
            if not named:
                run.corner_problems.append(
                    f"--corner {run.only_corner} is not a corner of this project "
                    f"(it has: {', '.join(c.name for c in run.corners)})"
                )
            run.corners = named
    return run, []


def run_gate(run: Run, name: str):
    function = gate_function(name)
    if function is None:
        return run.skip(name, f"the {name.upper()} gate is not built in this workcenter")
    t0 = time.monotonic()
    result = function(run)
    result.seconds = round(time.monotonic() - t0, 2)
    return result


def chip_verdict(results: list, whole: bool) -> tuple[str, int]:
    """A chip run's verdict and exit code. Every chip gate is required: a gate that did not run is the
    verdict, `SKIPPED (GATE: reason)` with exit code 2, however many passed. GREEN needs all 10
    (`whole`) or, for 1 gate run alone, that gate; it names the count of warnings beside the word."""
    for r in results:
        if r.status in ("fail", "error"):
            return "RED", 1
    for r in results:
        if r.status == "skip":
            return f"SKIPPED ({r.gate.upper()}: {r.summary})", 2
    if whole and [r.gate for r in results] != list(GATE_NAMES):
        return "SKIPPED (not every gate ran)", 2
    warnings = sum(len(r.details.get("warnings", [])) for r in results)
    return "GREEN" + (f" with {warnings} warning{'' if warnings == 1 else 's'}" if warnings else ""), 0


def scope_line(run: Run | None) -> str:
    """What stands behind a verdict, on 1 line no flag removes: the engines are open, the process kit
    and its version, each rule deck with its origin, the corners. No foundry's deck runs here, and no
    shuttle's limits are held."""
    if run is None or run.pdk is None:
        return (
            "scope: open engines; no process kit was read; no foundry deck ran; no shuttle's limits were "
            "checked"
        )
    decks = ", ".join(f"{d['name']} ({d['origin']})" for d in run.pdk.table["drc"])
    foundry = any(d["origin"] == "foundry" for d in run.pdk.table["drc"])
    corners = ", ".join(c.name for c in run.corners) or "none"
    return (
        f"scope: open engines, {run.pdk.name} {run.pdk.installed}, decks: {decks}, corners: {corners}; "
        f"{'a foundry deck ran' if foundry else 'no foundry deck ran'}; no shuttle's limits were checked"
    )


def emit(cli, results: list, run: Run | None, project: Path, out: Path, args, whole: bool) -> int:
    verdict, code = chip_verdict(results, whole)
    records = [asdict(r) for r in results]
    if whole:
        out.mkdir(parents=True, exist_ok=True)
        (out / "gates.json").write_text(json.dumps(records, indent=2), encoding="utf-8")
    if getattr(args, "json", False):
        print(json.dumps(records, indent=2))
        return code
    for r in results:
        print(f"{r.status.upper():6} {r.gate:10} {r.summary}  [{r.seconds}s]")
        failures = r.details.get("failures", [])
        for line in failures:
            print(f"       - {line}")
        for line in [w for w in r.details.get("warnings", []) if w not in failures]:
            print(f"       - warning: {line}")
    print(scope_line(run))
    where = f"  report {out / 'gates.json'}" if whole else ""
    print(f"{verdict}: {project.name}{where}")
    return code


def cmd_gates(args, cli, only: str | None = None) -> int:
    """`chip gates`: the 10 gates in order, stopping at the first that does not pass. `only` runs 1
    gate on what the output folder holds."""
    project = find_chip(args.project)
    out = Path(args.out).resolve() if args.out else project / "build"
    run, problems = prepare(cli, project, out, args)
    results = []
    if run is None:
        # chip.json is the project: with a problem in it no gate can run, and LINT is where it is said.
        results.append(
            cli.Result("lint", "fail", f"{len(problems)} failures", {"failures": problems, "warnings": []})
        )
    else:
        for name in [only] if only else GATE_NAMES:
            result = run_gate(run, name)
            if name == "sta" and run.only_corner and result.status == "pass":
                # A quick run is never taken for a full one.
                every = len(select_corners(run.pdk, run.chip)[0])
                note = f"--corner {run.only_corner}: 1 corner ran of the {every} the project's ranges select"
                key = "failures" if run.strict else "warnings"
                result.details[key] = [*result.details.get(key, []), note]
                result.status = "fail" if run.strict else result.status
            results.append(result)
            if result.status != "pass":
                break
    return emit(cli, results, run, project, out, args, whole=only is None)


def cmd_init(args, cli) -> int:
    """`chip init <dir> --top NAME`: the template's files with the top module's name, never over a
    file that is there."""
    if not IDENTIFIER_RE.match(args.top):
        raise SystemExit(f"chip init: --top {args.top!r} is not a module name")
    target = Path(args.dir).resolve()
    wrote, kept = [], []
    for source in sorted(p for p in TEMPLATE_DIR.rglob("*") if p.is_file()):
        relative = str(source.relative_to(TEMPLATE_DIR)).replace("__TOP__", args.top)
        if relative.endswith(".template"):
            relative = relative[: -len(".template")]
        path = target / relative
        if path.exists():
            kept.append(relative)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source.read_text(encoding="utf-8").replace("__TOP__", args.top), encoding="utf-8")
        wrote.append(relative)
    for relative in wrote:
        print(f"wrote {target / relative}")
    for relative in kept:
        print(f"kept  {target / relative} (it is there already)")
    print(f"chip init: {len(wrote)} files written, {len(kept)} kept; next: workcenter next {target}")
    return 0


def cmd_render(args, cli) -> int:
    sys.path.insert(0, str(SRC_DIR / "tools"))
    try:
        import chipback
    except ModuleNotFoundError as exc:
        if exc.name != "chipback":
            raise
        raise SystemExit("chip render: not built in this workcenter") from None
    if not hasattr(chipback, "render"):
        raise SystemExit("chip render: not built in this workcenter")
    project = find_chip(args.project)
    out = Path(args.out).resolve() if args.out else project / "build"
    run, problems = prepare(cli, project, out, args)
    if run is None:
        raise SystemExit("\n".join(problems))
    return chipback.render(run, args)


def register(sub, cli) -> None:
    """Add `workcenter chip ...` to the command line's parser."""
    import argparse

    chip = sub.add_parser("chip", help="a chip project: RTL to a GDSII layout through 10 gates")
    parts = chip.add_subparsers(dest="chip_command", required=True)

    def flags(p, corner: bool = False) -> None:
        p.add_argument("project", help="the chip project's folder (it holds chip.json)")
        p.add_argument("--out", help="output directory (default <project>/build)")
        p.add_argument("--strict", action="store_true", help="warnings fail the gate")
        p.add_argument(
            "--jobs", type=cli.job_count, help="engine runs at once (default: one per processor, 8 at most)"
        )
        p.add_argument("--timeout", type=int, help="seconds an engine may run (default: by gate)")
        if corner:
            p.add_argument(
                "--corner", metavar="NAME", help="run STA at 1 corner only; the result names it as a warning"
            )
        p.add_argument(
            "--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output"
        )

    p = parts.add_parser("gates", help="run the 10 gates in order; the last line is the verdict")
    flags(p, corner=True)
    p.set_defaults(run=lambda a: cmd_gates(a, cli))
    for name in GATE_NAMES:
        p = parts.add_parser(name, help=f"run the {name.upper()} gate alone on what the output folder holds")
        flags(p, corner=name == "sta")
        p.set_defaults(run=lambda a, name=name: cmd_gates(a, cli, only=name))
    p = parts.add_parser("init", help="start a chip project from the template; never writes over a file")
    p.add_argument("dir", help="the folder to start the project in")
    p.add_argument("--top", required=True, help="the top module's name")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help=argparse.SUPPRESS)
    p.set_defaults(run=lambda a: cmd_init(a, cli))
    p = parts.add_parser("render", help="draw the layout into <out>/chip/render/")
    flags(p)
    p.set_defaults(run=lambda a: cmd_render(a, cli))
