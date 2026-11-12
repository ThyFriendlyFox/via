"""The back chip gates: LAYOUT, STA, DRC, ANTENNA, LVS and EXPORT, and `chip render`. tools/chipflow.py
holds the contract.

LAYOUT builds: a mapped netlist becomes a placed and routed layout. The gates after it judge that
layout and build nothing. Each gate is a judge that reads what an engine wrote, and a runner that
starts the engine through `run.start` with a script of tools/chipscripts/. The runner writes every
value of the process into `vars.tcl` (or the engine's environment) from the process table: no script
and no line here names a file, a cell or a layer of a process. Standard library only.

    LAYOUT   OpenROAD, then Magic for the GDS: the netlist places and routes in the area named
    STA      OpenSTA, 1 run for each corner: setup, hold and the limits of the library hold
    DRC      Magic and each KLayout deck of the table: the layout obeys the process rules
    ANTENNA  OpenROAD: no wire collects charge that can break a gate oxide
    LVS      Magic and Netgen: the layout is the final netlist, supply pins included
    EXPORT   the files a fabrication run takes, and that they are the files the gates passed

A gate that passes writes `passed.json` in its own folder: the hash of each file it judged. The folder
is emptied when the gate runs again, so the record of a pass never outlives a later run that fails.
EXPORT copies a file only when LAYOUT, STA, DRC, ANTENNA and LVS each hold such a record for the bytes
it copies. A back gate that runs takes the hand-off folder away: `chip/tapeout/` is there only while
EXPORT was the last of them to run, and passed.
"""

from __future__ import annotations

import json
import re
import shutil
import struct
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import chipflow

SCRIPTS = Path(__file__).resolve().parent / "chipscripts"
PASSED = chipflow.PASSED
# Seconds an engine may run in the gates the spine names no limit for; --timeout sets another.
TIME_LIMITS = {"drc": 3600, "antenna": 900, "lvs": 3600, "render": 600}
ROUTER_RE = re.compile(r"\[INFO DRT-0199\]\s+Number of violations = (\d+)\.")
ERROR_RE = re.compile(r"^\[ERROR [A-Z]+-\d+\].*$", re.M)
# OpenROAD's 2 lines for a cell of the netlist that the liberty file or the LEF does not have: (cell,
# instance) and (instance, cell). It builds the layout without the instance and exits 0.
NO_LIBERTY_RE = re.compile(
    r"^\[WARNING STA-0198\] .* module (\S+) not found\. Creating black box for (\S+)\.$", re.M
)
NO_LEF_RE = re.compile(r"^\[WARNING ORD-1013\] instance (\S+) LEF master (\S+) not found\.$", re.M)
EARLY_RE = re.compile(r"^WORKCENTER utilization ([\d.]+) after the floorplan", re.M)
FINAL_RE = re.compile(r"^WORKCENTER utilization ([\d.]+) of the core, ([\d.]+) um2 of cells", re.M)
OPEN_PINS_RE = re.compile(r"^WORKCENTER open pins (\d+)", re.M)
KEPT_OUT_RE = re.compile(r"^WORKCENTER dont_use cells (\d+)", re.M)
WIRE_RE = re.compile(r"^WORKCENTER wire \S+ ohm/um and (\S+) fF/um for a signal, \S+ and (\S+) for a", re.M)
SLACK_RE = re.compile(r"^worst slack (-?[\d.]+)", re.M)
TNS_RE = re.compile(r"^tns (-?[\d.]+)", re.M)
BLACK_BOX_RE = re.compile(r"^Warning: .* module (\S+) not found\. Creating black box for (\S+)\.$", re.M)
CHECK_KINDS = ("max slew", "max capacitance", "max fanout", "min pulse width", "min period")
# The headroom the build leaves under the utilisation limit when the project names no die, and over
# what the cells take when it sets the placer's density: the clock tree and the timing repair add cells
# after the floorplan is set.
UTILIZATION_HEADROOM = 0.1
# The floorplans LAYOUT may make for a project that names a limit and no die, each with more room.
FLOORPLANS = 3
RENDER_PIXELS = 1600


# -------------------------------------------------------------------- helpers


def tcl_word(value: object) -> str:
    """A value as 1 Tcl word: a list as a braced list, a text in braces."""
    if isinstance(value, (list, tuple)):
        return "{" + " ".join(tcl_word(v) if isinstance(v, (list, tuple)) else str(v) for v in value) + "}"
    return "{" + str(value) + "}"


def write_vars(folder: Path, values: dict) -> Path:
    """`vars.tcl` in a gate's folder: 1 `set` for each value the gate's script reads."""
    path = folder / "vars.tcl"
    path.write_text(
        "".join(f"set {name} {tcl_word(value)}\n" for name, value in values.items()), encoding="utf-8"
    )
    return path


def kit_env(run, **more: object) -> dict[str, str]:
    """The environment of an engine that reads the kit's own start files. An open_pdks kit's files find
    the kit through PDK_ROOT, the folder the kit's folder is in; without it they name the path of the
    machine the kit was built on."""
    return {"PDK_ROOT": str(run.pdk.root.parent), "PDK": run.pdk.name, **{k: str(v) for k, v in more.items()}}


def nominal_wire(library: dict) -> str:
    """The wire corner a build reads: `nom` where the table has it, else its first."""
    wires = sorted(library["wires"])
    return "nom" if "nom" in wires else wires[0]


def time_limit(gate: str) -> int:
    """The seconds an engine of this gate may run: the spine's table, else this module's."""
    return chipflow.TIME_LIMITS.get(gate) or TIME_LIMITS.get(gate) or chipflow.DEFAULT_LIMIT


def relative(run, path: Path) -> str:
    return str(path.relative_to(run.out))


def read_text(path: Path) -> str | None:
    """A file an engine wrote, or None when it wrote none."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def taken(run, gate: str, path: Path):
    """A file a gate before this one handed on: (path, None), or (path, the gate's Result): a skip
    when the file is not there, a failure when it changed after it was recorded."""
    path, problem = run.take(path)
    if problem is None:
        return path, None
    if not path.is_file():
        return path, run.skip(gate, problem)
    return path, run.result(gate, [problem], [], "its input")


def need_files(run, gate: str, relatives: list[str]):
    """None when the process kit holds each file, else a skip that names what it lacks. A rule deck
    and a cell model are engines too: without one the gate did not run."""
    absent = [name for name in relatives if not run.pdk.file(name).is_file()]
    if not absent:
        return None
    return run.skip(gate, f"the process kit {run.pdk.name} has no {', '.join(absent)}", engine=True)


def begin(run, gate: str) -> Path:
    """The gate's own folder, emptied: `Run.begin` in the spine."""
    return run.begin(gate)


def write_passed(run, gate: str, judged: dict[str, str], reports: list[Path] | tuple = (), **more) -> None:
    """The record that `gate` passed: `Run.write_passed` in the spine."""
    run.write_passed(gate, judged, reports, **more)


def read_passed(run, gate: str) -> tuple[dict | None, str | None, bool]:
    """A gate's record of its pass: `Run.read_passed` in the spine."""
    return run.read_passed(gate)


def need_layout(run, gate: str):
    """None when LAYOUT passed in this output folder, else the gate's Result: no gate judges a layout
    whose build failed."""
    _, problem, absent = read_passed(run, "layout")
    if problem is None:
        return None
    if absent:
        return run.skip(gate, f"{problem}: {gate.upper()} judges only a layout that LAYOUT passed")
    return run.result(gate, [problem], [], "its input")


def unchanged(run, judged: dict[str, str]) -> list[str]:
    """A failure for each judged file that is no longer the bytes the gate took before its engines ran."""
    out = []
    for name, digest in judged.items():
        path = run.out / name
        if not path.is_file() or chipflow.sha256(path) != digest:
            out.append(f"{name} changed while the gate ran: its hash differs")
    return out


def gds_top_cells(data: bytes) -> list[str]:
    """The cells of a GDSII stream that no other cell places: its top cells. A stream is records of a
    2-byte length, a record type and a data type; STRNAME (0x06) names a cell, SNAME (0x12) a cell
    that is placed, and ENDLIB (0x04) ends the stream. A stream with a record cut short or with no
    ENDLIB is not whole, and has no top cell."""
    defined: list[str] = []
    placed: set[str] = set()
    at = 0
    while at + 4 <= len(data):
        length, kind = struct.unpack(">HB", data[at : at + 3])
        if length < 4 or at + length > len(data):
            return []
        if kind == 0x04:
            return [name for name in defined if name not in placed]
        if kind in (0x06, 0x12):
            name = data[at + 4 : at + length].rstrip(b"\0").decode("ascii", "replace")
            (defined.append if kind == 0x06 else placed.add)(name)
        at += length
    return []


def gds_undated(data: bytes) -> bytes:
    """A GDSII stream with the date each cell was changed set to the date it was made. BGNLIB (0x01) and
    BGNSTR (0x05) each hold 2 dates of 6 numbers of 2 bytes: made, then changed. With `gds nodatestamp
    yes` Magic 8.3.465 writes the first as 1970-01-01 and the time of the run as the second, and its
    help names no option for the second: 2 builds of 1 layout then differ in those bytes alone. A
    stream that is not whole comes back as it is."""
    out = bytearray(data)
    at = 0
    while at + 4 <= len(data):
        length, kind = struct.unpack(">HB", data[at : at + 3])
        if length < 4 or at + length > len(data):
            return data
        if kind == 0x04:
            return bytes(out)
        if kind in (0x01, 0x05) and length == 28:
            out[at + 16 : at + 28] = data[at + 4 : at + 16]
        at += length
    return data


def between(text: str, begin_mark: str, end_mark: str) -> str | None:
    """The text between 2 marker lines of a script's output, or None when either is not there."""
    start = text.find(begin_mark)
    stop = text.find(end_mark, start + len(begin_mark)) if start >= 0 else -1
    return text[start + len(begin_mark) : stop] if start >= 0 and stop >= 0 else None


def magic_read_errors(text: str) -> list[str]:
    """Magic's lines for a layout it could not read whole. It goes on with what it read and exits 0."""
    return [line.strip() for line in text.splitlines() if line.startswith("Error while reading cell")]


def with_error(line: str, text: str) -> str:
    """A failure line with what a script of tools/chipscripts/ printed as `ERROR: ...` before it stopped."""
    said = next((e.strip() for e in text.splitlines() if e.startswith("ERROR: ")), "")
    return f"{line}: {said[len('ERROR: ') :]}" if said else line


# ---------------------------------------------------------------------- LAYOUT


def judge_layout(
    text: str, limit: float | None, supply: tuple[str, ...] = (), wire: tuple[float, float] | None = None
) -> tuple[list[str], list[str], dict]:
    """OpenROAD's output as (failures, warnings, details). The build stands when no error is named,
    the script reached each of its marks, each supply net's grid is connected, the detailed router's
    last count of violations is 0, no pin of a cell is left open, no cell is one the process kit
    lists as not to place, and the cells take no more of the core than the project's limit. A mark
    that is not there is a failure, never a pass. `wire` is the capacitance of 1 um of signal wire and
    of clock wire in fF, as the process table gives them: the engine reads them back in its own units,
    and a build that estimated its wires with other values repaired the wrong design."""
    failures = [line.strip() for line in ERROR_RE.findall(text)][:5]
    dropped = {instance: cell for cell, instance in NO_LIBERTY_RE.findall(text)}
    dropped.update(dict(NO_LEF_RE.findall(text)))
    if dropped:
        instance, cell = sorted(dropped.items())[0]
        more = f" and {len(dropped) - 1} more" if len(dropped) > 1 else ""
        failures.append(
            f"the library has no cell {cell}: OpenROAD built the layout without {instance}{more}, so the "
            "layout is not the netlist SYNTH wrote"
        )
    warnings = sorted({line.strip() for line in text.splitlines() if "Unable to repair all" in line})
    details: dict = {}
    over = "take a larger die, or cut logic. Do not raise the limit"
    early = EARLY_RE.search(text)
    if "WORKCENTER stopped:" in text:
        # The script stops itself on a netlist that is over the limit before the clock tree adds cells.
        used = float(early.group(1)) if early else None
        if used is None or (limit is None and used <= 1.0):
            failures.append("OpenROAD stopped after the floorplan and named no utilisation over a limit")
        elif used > 1.0:
            details["utilization"] = used
            failures.append(
                f"the cells take {used:g} times the core's area after the floorplan: they do not fit. Take a "
                "larger die, or cut logic"
            )
        else:
            details["utilization"], details["over_limit"] = used, True
            failures.append(
                f"utilisation {used:g} is over the limit {limit:g} of chip.json after the floorplan, before "
                f"the clock tree adds cells: {over}"
            )
        return failures, warnings, details
    if "Stack trace:" in text:
        failures.append("OpenROAD crashed: its log ends with the stack trace")
    grid = [net for net in supply if not re.search(rf"^WORKCENTER grid {re.escape(net)} ", text, re.M)]
    final = FINAL_RE.search(text)
    open_pins = OPEN_PINS_RE.search(text)
    kept_out = KEPT_OUT_RE.search(text)
    estimated = WIRE_RE.search(text)
    for reached, stage in (
        (early, "the floorplan was made"),
        (estimated or wire is None, "the wires were given their resistance and capacitance"),
        (not grid, f"the supply grid of {', '.join(grid)} was checked"),
        ("WORKCENTER placement checked" in text, "the placement was checked"),
        ("WORKCENTER routed" in text, "the routing ended"),
        (open_pins, "the open pins were counted"),
        (kept_out, "the cells not to use were counted"),
        (final and "WORKCENTER layout written" in text, "the layout was written"),
    ):
        if not reached:
            failures.append(f"OpenROAD stopped before {stage}")
            break
    if estimated:
        details["wire_ff_per_um"] = {"signal": float(estimated.group(1)), "clock": float(estimated.group(2))}
        held = tuple(details["wire_ff_per_um"].values())
        if wire is not None and any(abs(a - b) > 0.001 * b for a, b in zip(held, wire, strict=True)):
            failures.append(
                f"the build estimated 1 um of signal wire at {held[0]:g} fF and of clock wire at {held[1]:g} "
                f"fF, and the process table gives {wire[0]:g} and {wire[1]:g}: the repair worked on other "
                "wires than the table's"
            )
    for net in re.findall(r"^WORKCENTER grid (\S+) open", text, re.M):
        failures.append(
            f"the supply grid leaves parts of {net} unconnected: its rails do not all reach a stripe"
        )
    counts = ROUTER_RE.findall(text)
    if counts:
        details["router_violations"] = int(counts[-1])
        if int(counts[-1]) != 0:
            failures.append(
                f"the router left {counts[-1]} violations: shorts or spacing errors between wires. Give the "
                "design more room"
            )
    elif "WORKCENTER routed" in text:
        failures.append("the router printed no count of violations")
    if open_pins:
        details["open_pins"] = int(open_pins.group(1))
        if details["open_pins"]:
            named = re.findall(r"^WORKCENTER open pin (\S+)", text, re.M)
            failures.append(
                f"{details['open_pins']} pins of cells are on no net: {', '.join(named)}"
                f"{' ...' if details['open_pins'] > len(named) else ''}: an open input floats"
            )
    if kept_out:
        details["dont_use_cells"] = int(kept_out.group(1))
        if details["dont_use_cells"]:
            named = re.findall(r"^WORKCENTER dont_use cell (\S+) (\S+)", text, re.M)
            said = ", ".join(f"{instance} ({cell})" for instance, cell in named)
            failures.append(
                f"{details['dont_use_cells']} cells of the layout are ones the process kit lists as not to "
                f"place: {said}{' ...' if details['dont_use_cells'] > len(named) else ''}: no step of the "
                "build may choose one"
            )
    if final:
        details["utilization"], details["area_um2"] = float(final.group(1)), float(final.group(2))
        if limit is not None and details["utilization"] > limit:
            details["over_limit"] = True
            failures.append(
                f"utilisation {details['utilization']:g} is over the limit {limit:g} of chip.json: {over}"
            )
    return failures, warnings, details


def tracks_tcl(tracks_info: str) -> str:
    """`make_tracks` for each layer of the kit's tracks file: lines of `layer X|Y offset pitch`."""
    layers: dict[str, dict[str, tuple[str, str]]] = {}
    for line in tracks_info.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[1] in ("X", "Y"):
            layers.setdefault(parts[0], {})[parts[1]] = (parts[2], parts[3])
    out = []
    for layer, both in layers.items():
        if set(both) == {"X", "Y"}:
            out.append(
                f"make_tracks {layer} -x_offset {both['X'][0]} -x_pitch {both['X'][1]} "
                f"-y_offset {both['Y'][0]} -y_pitch {both['Y'][1]}\n"
            )
    return "".join(out)


def layout_files(run) -> list[Path]:
    """What LAYOUT hands on: the files the gates after it judge and EXPORT copies."""
    wires = sorted(run.pdk.library["wires"])
    handed = [run.database(), run.def_file(), run.final_netlist(), run.power_netlist(), run.gds()]
    return handed + [run.spef(w) for w in wires]


def build_corners(run) -> dict[str, Path]:
    """The library corners the build times and repairs the design at, as {name: liberty file}: each one
    the project's ranges select, whatever --corner names, so the build aims at what STA judges. With
    none selected, the corner the mapping read: STA then fails on the range no corner covers."""
    import chipfront

    chosen = {c.library_corner: c.liberty for c in chipflow.select_corners(run.pdk, run.chip)[0]}
    if not chosen:
        liberty = chipfront.synth_liberty(run)
        chosen = {liberty.stem: liberty}
    return chosen


def gate_layout(run):
    missing = run.need_pdk("layout") or run.need_engines("layout", "openroad", "magic")
    if missing:
        return missing
    folder = begin(run, "layout")
    shutil.rmtree(run.base / "render", ignore_errors=True)
    import chipfront

    chip, library = run.chip, run.pdk.library
    plan, cells, supply = library["floorplan"], library["cells"], library["supply"]
    wire = nominal_wire(library)
    liberty = build_corners(run)
    missing = need_files(
        run,
        "layout",
        [
            *[str(path.relative_to(run.pdk.root)) for path in liberty.values()],
            *chipfront.dont_use_files(run, "layout"),
            library["lef"],
            library["gds"],
            plan["tracks"],
            run.pdk.table["magic"]["rc"],
            *[library["wires"][w][key] for w in sorted(library["wires"]) for key in ("techlef", "rcx")],
        ],
    )
    if missing:
        return missing
    netlist, stopped = taken(run, "layout", run.mapped_netlist())
    if stopped:
        return stopped
    # What the layout is built from: the mapped netlist, the constraints and chip.json. The record of a
    # pass names their hashes with the layout's own, so a layout stands for those bytes and no later ones.
    built_from = chipfront.inputs_taken(run, "layout", netlist)
    if chip.die_um is None and chip.utilization_max is None:
        return run.result(
            "layout",
            [
                "chip.json names no floorplan.die_um and no limits.utilization: "
                "the build has no size to aim at"
            ],
            [],
            "the floorplan",
        )
    margin_x, margin_y = plan["core_margin_um"]
    die = core = ""
    if chip.die_um:
        width, height = chip.die_um
        die = f"0 0 {width:g} {height:g}"
        core = f"{margin_x:g} {margin_y:g} {width - margin_x:g} {height - margin_y:g}"
    (folder / "tracks.tcl").write_text(
        tracks_tcl(run.pdk.file(plan["tracks"]).read_text(encoding="utf-8")), encoding="utf-8"
    )
    values = {
        "top": chip.top,
        "out": folder,
        "netlist": netlist,
        "sdc": chip.constraints,
        "liberty": [word for name, path in liberty.items() for word in (name, path)],
        "dont_use": chipfront.dont_use(run, "layout"),
        "diode": f"{cells['diode']['cell']}/{cells['diode']['pin']}",
        "slew_margin": plan["repair"]["slew_margin_percent"],
        "cap_margin": plan["repair"]["capacitance_margin_percent"],
        "antenna_iterations": plan["repair"]["antenna_iterations"],
        "tech_lef": run.pdk.file(library["wires"][wire]["techlef"]),
        "cell_lef": run.pdk.file(library["lef"]),
        "die_area": die,
        "core_area": core,
        "utilization_limit": "" if chip.utilization_max is None else chip.utilization_max,
        "core_space": max(margin_x, margin_y),
        "site": plan["site"],
        "pin_layer_h": plan["pin_layers"]["horizontal"],
        "pin_layer_v": plan["pin_layers"]["vertical"],
        "tap_cell": cells["tap"],
        "tap_distance": plan["tap_distance_um"],
        "wire_rc": [
            [kind, plan["wire_rc_layers"][kind], plan["wire_capacitance_ff_per_um"][kind]]
            for kind in ("signal", "clock")
        ],
        "density": plan["placement_density"],
        "density_headroom": UTILIZATION_HEADROOM,
        "clock_root": cells["clock_root"],
        "clock_buffers": cells["clock_buffers"],
        "fill_cells": cells["fill"],
        "power_net": supply["power"]["net"],
        "power_pins": supply["power"]["pins"],
        "ground_net": supply["ground"]["net"],
        "ground_pins": supply["ground"]["pins"],
        "rail_layer": plan["grid"]["rails"]["layer"],
        "rail_width": plan["grid"]["rails"]["width_um"],
        "stripe_layer": plan["grid"]["stripes"]["layer"],
        "stripe_width": plan["grid"]["stripes"]["width_um"],
        "stripe_pitch": plan["grid"]["stripes"]["pitch_um"],
        "stripe_offset": plan["grid"]["stripes"]["offset_um"],
        "route_bottom": plan["routing_layers"]["bottom"],
        "route_top": plan["routing_layers"]["top"],
        "rcx": [x for w in sorted(library["wires"]) for x in (w, run.pdk.file(library["wires"][w]["rcx"]))],
    }
    aim = max(0.05, (chip.utilization_max or plan["placement_density"]) - UTILIZATION_HEADROOM)
    floorplans = 0
    while True:
        floorplans += 1
        write_vars(folder, {**values, "utilization": round(aim * 100, 1)})
        started = run.start(
            [
                run.engine("openroad"),
                "-no_init",
                "-exit",
                "-threads",
                max(1, run.jobs),
                SCRIPTS / "layout.tcl",
            ],
            cwd=folder,
            log=folder / "openroad.log",
            timeout=time_limit("layout"),
        )
        failures, warnings, details = judge_layout(
            started.text,
            chip.utilization_max,
            (supply["power"]["net"], supply["ground"]["net"]),
            tuple(plan["wire_capacitance_ff_per_um"][kind] for kind in ("signal", "clock")),
        )
        stopped = started.problem("openroad")
        if stopped and not failures:
            failures.append(stopped)
        # With no die named the floorplan is this gate's own choice. One that ends over the project's
        # limit, and breaks nothing else, is made again with more room: the clock tree and the repair
        # add what no rule foretells.
        again = chip.die_um is None and details.get("over_limit") and len(failures) == 1
        if not again or floorplans == FLOORPLANS:
            break
        (folder / "openroad.log").rename(folder / f"openroad.{floorplans}.log")
        for path in layout_files(run):
            path.unlink(missing_ok=True)
        aim = max(0.05, aim * chip.utilization_max / details["utilization"] * 0.95)
    details["floorplans"] = floorplans
    if floorplans > 1 and details.get("over_limit"):
        failures.append(
            f"{floorplans} floorplans of the gate's own were each over the limit: name floorplan.die_um"
        )
    if not failures:
        made = run.start(
            [
                run.engine("magic"),
                "-dnull",
                "-noconsole",
                "-rcfile",
                run.pdk.file(run.pdk.table["magic"]["rc"]),
                SCRIPTS / "gds.tcl",
            ],
            cwd=folder,
            log=folder / "magic.log",
            timeout=time_limit("layout"),
            env=kit_env(
                run,
                CELL_GDS=run.pdk.file(library["gds"]),
                TECH_LEF=run.pdk.file(library["wires"][wire]["techlef"]),
                DEF=run.def_file(),
                TOP=chip.top,
                OUT=folder,
            ),
        )
        stopped = made.problem("magic, writing the GDS")
        unread = magic_read_errors(made.text)
        if stopped or "WORKCENTER gds written" not in made.text or not run.gds().is_file():
            failures.append(with_error(stopped or f"Magic wrote no GDS (log {made.log})", made.text))
        elif unread:
            failures.append(f"Magic did not read the cells' layouts whole: {unread[0]}")
        else:
            # The same layout is the same bytes, whenever it is built: a hash then names a layout.
            run.gds().write_bytes(gds_undated(run.gds().read_bytes()))
            tops = gds_top_cells(run.gds().read_bytes())
            details["gds_top_cells"] = tops
            if tops != [chip.top]:
                failures.append(f"the GDS's top cells are {', '.join(tops) or 'none'}, not {chip.top} alone")
    handed = layout_files(run)
    if not failures:
        absent = [relative(run, p) for p in handed if not p.is_file() or not p.stat().st_size]
        if absent:
            failures.append(f"the build did not write {', '.join(absent)}")
    failures = [chipfront.short(line, run) for line in failures]
    failures += chipfront.inputs_moved(run, "layout", built_from, netlist)
    summary = "the layout"
    if "area_um2" in details:
        summary = f"{details['area_um2']:g} um2 of cells, utilisation {details['utilization']:g}"
    result = run.result("layout", failures, warnings, summary, details, [run.gds(), folder / "openroad.log"])
    if result.status == "pass":
        # Only a build that passed hands its files on: a gate after it takes none of a build that failed.
        hashes = {relative(run, p): run.record("layout", p) for p in handed}
        result.details["sha256"] = hashes
        write_passed(run, "layout", {**built_from, **hashes}, [folder / "openroad.log"])
    return result


# ------------------------------------------------------------------------- STA


def worst_path(text: str, kind: str) -> str:
    """`from A to B` for the path of a report_checks block of that kind (`max` or `min`)."""
    for block in text.split("Startpoint: ")[1:]:
        if f"Path Type: {kind}" in block:
            start = block.split()[0]
            end = re.search(r"Endpoint: (\S+)", block)
            return f", from {start} to {end.group(1)}" if end else ""
    return ""


def spef_nets(text: str) -> set[str]:
    """The nets a SPEF file holds parasitics for: the name of each `*D_NET`, through the file's name
    map where it has one."""
    section = re.search(r"^\*NAME_MAP\s*\n(.*?)^\*[A-Z]", text, re.M | re.S)
    names = dict(re.findall(r"^(\*\d+)\s+(\S+)\s*$", section.group(1), re.M)) if section else {}
    return {names.get(key, key) for key in re.findall(r"^\*D_NET\s+(\S+)", text, re.M)}


def judge_sta(
    text: str,
    corner: str,
    nets: list[str] | None,
    wired: set[str] | None,
    skew_limit: float | None,
    supply: tuple[str, ...] = (),
    physical: tuple[str, ...] = (),
) -> tuple[list[str], dict]:
    """1 corner's OpenSTA output as (failures, details). The corner holds when the script reached its
    end, every cell but a tap or a fill cell has its timing model, the clock is the tree that was
    built, setup and hold slack are 0 or more, no path is negative, no slew, capacitance, fanout,
    pulse width or period limit is broken, the constraints leave nothing open, every net that joins
    pins has its parasitics, and the skew is within the project's limit. `nets` is what the script
    named in nets.txt and `wired` the nets of the corner's SPEF. A part of the output that is not
    there is a failure, never a pass."""
    failures: list[str] = []
    details: dict = {}
    if "WORKCENTER sta done" not in text:
        errors = [line.strip() for line in text.splitlines() if line.startswith("Error:")]
        return [
            f"{corner}: OpenSTA stopped before its end: {errors[0] if errors else 'its log says where'}"
        ], details
    boxes = sorted({module for module, _ in BLACK_BOX_RE.findall(text)} - set(physical))
    if boxes:
        more = " ..." if len(boxes) > 4 else ""
        failures.append(
            f"{corner}: the liberty file has no cell {', '.join(boxes[:4])}{more}: OpenSTA made a black box "
            "of each, and no path through one is judged"
        )
    # OpenSTA goes on after a file it could not read whole and a constraint that names nothing: it
    # prints a warning and exits 0. Each warning before the script's first mark is such a line.
    reading = text[: max(0, text.find("WORKCENTER nets"))]
    doubts = [
        line.strip()
        for line in reading.splitlines()
        if line.startswith("Warning:") and not BLACK_BOX_RE.match(line)
    ]
    for line in doubts[:3]:
        failures.append(f"{corner}: OpenSTA did not take all it read: {line[len('Warning: ') :]}")
    parts = {
        "check_setup": between(text, "WORKCENTER check_setup begin", "WORKCENTER check_setup end"),
        "paths": between(text, "WORKCENTER paths begin", "WORKCENTER paths end"),
        "setup": between(text, "WORKCENTER setup", "WORKCENTER hold"),
        "hold": between(text, "WORKCENTER hold", "WORKCENTER tns"),
        "tns": between(text, "WORKCENTER tns", "WORKCENTER violators begin"),
        "violators": between(text, "WORKCENTER violators begin", "WORKCENTER violators end"),
        "skew": between(text, "WORKCENTER skew begin", "WORKCENTER skew end"),
    }
    absent = [name for name, part in parts.items() if part is None]
    if absent:
        failures.append(
            f"{corner}: OpenSTA's output has no part for {', '.join(absent)}: nothing of it is judged"
        )
    paths = parts["paths"] or ""
    if "clock network delay (ideal)" in paths:
        failures.append(
            f"{corner}: a clock is ideal in the timing: hold and skew mean nothing without the clock tree"
        )
    for name, kind in (("setup", "max"), ("hold", "min")):
        found = SLACK_RE.search(parts[name] or "")
        if not found:
            failures.append(f"{corner}: no {name} slack was reported: no path is constrained")
            continue
        details[f"{name}_slack_ns"] = float(found.group(1))
        if float(found.group(1)) < 0:
            failures.append(f"{corner}: {name} slack {found.group(1)} ns{worst_path(paths, kind)}")
    tns = TNS_RE.search(parts["tns"] or "")
    if not tns:
        failures.append(f"{corner}: no total negative slack was reported")
    else:
        details["tns_ns"] = float(tns.group(1))
        if float(tns.group(1)) < 0 and not any("setup slack" in f for f in failures):
            failures.append(f"{corner}: total negative slack {tns.group(1)} ns")
    # check_setup names what the constraints leave open: each kind as a warning with its objects under
    # it. The supply nets are ports of the routed netlist and need no delay; a kind that names only
    # those names nothing.
    kind, named = "", []
    for line in [*(parts["check_setup"] or "").splitlines(), "Warning: end"]:
        if line.startswith("Warning:"):
            if kind and (named or not kind.startswith("There")):
                listed = f" {', '.join(named[:6])}{' ...' if len(named) > 6 else ''}" if named else ""
                failures.append(f"{corner}: {kind}{listed}")
            kind, named = line[len("Warning: ") :].strip(), []
        elif line.strip() and line.strip() not in supply:
            named.append(line.strip())
    violators = parts["violators"] or ""
    broken = [line.strip() for line in violators.splitlines() if "(VIOLATED)" in line]
    if broken:
        kinds = [k for k in CHECK_KINDS if re.search(rf"^{k}$", violators, re.M)]
        # The report has 1 row for each limit a pin breaks: a pin over 2 limits is 2 rows and 1 pin.
        pins = len({line.split()[0] for line in broken})
        failures.append(
            f"{corner}: {pins} pins break a limit of the library or the constraints"
            f"{f', {len(broken)} limits in all' if len(broken) != pins else ''} "
            f"({', '.join(kinds) or 'slew, capacitance, fanout, pulse width or period'}): "
            f"{' '.join(broken[0].split())}"
        )
    counted = re.search(r"^WORKCENTER nets (\d+)", text, re.M)
    if counted is None or nets is None or wired is None:
        failures.append(f"{corner}: the nets were not held to the SPEF: the parasitics are not judged")
    elif int(counted.group(1)) != len(nets):
        failures.append(
            f"{corner}: nets.txt names {len(nets)} nets and the log counts {counted.group(1)}: the list is "
            "not this run's"
        )
    elif not nets:
        failures.append(f"{corner}: the script named no net that joins 2 pins: the parasitics are not judged")
    else:
        # Verilog and SPEF escape a name's brackets and dots in 2 ways: the names are held bare.
        bare = {name.replace("\\", "") for name in wired}
        without = [name for name in nets if name.replace("\\", "") not in bare]
        details["nets"], details["nets_without_parasitics"] = len(nets), len(without)
        if without:
            failures.append(
                f"{corner}: {len(without)} of {len(nets)} nets have no parasitics in the SPEF "
                f"({', '.join(without[:4])}{' ...' if len(without) > 4 else ''}): OpenSTA gives their wires "
                "an estimate"
            )
    # report_clock_skew ends a clock's block with 3 numbers: latency, pessimism removed, skew.
    skews = [
        abs(float(v))
        for v in re.findall(r"^\s*-?\d+\.\d+\s+-?\d+\.\d+\s+(-?\d+\.\d+)\s*$", parts["skew"] or "", re.M)
    ]
    if skews:
        details["clock_skew_ns"] = max(skews)
        if skew_limit is not None and max(skews) > skew_limit:
            failures.append(
                f"{corner}: clock skew {max(skews):g} ns is over the limit {skew_limit:g} ns of chip.json"
            )
    elif skew_limit is not None:
        failures.append(
            f"{corner}: no clock skew was reported, so the limit {skew_limit:g} ns of chip.json holds "
            "nothing: no path runs from 1 flop to another"
        )
    return failures, details


def sta_corner(run, corner, netlist: Path, spef: Path) -> tuple[list[str], dict]:
    """1 corner in its own folder. It reads and writes nothing of the ledger: several run at once."""
    folder = run.base / "sta" / corner.name
    folder.mkdir(parents=True, exist_ok=True)
    library = run.pdk.library
    supply = (library["supply"]["power"]["net"], library["supply"]["ground"]["net"])
    cells = library["cells"]
    write_vars(
        folder,
        {
            "top": run.chip.top,
            "out": folder,
            "netlist": netlist,
            "sdc": run.chip.constraints,
            "liberty": corner.liberty,
            "spef": spef,
            "supply_nets": supply,
        },
    )
    shutil.copyfile(SCRIPTS / "sta.tcl", folder / "sta.tcl")
    started = run.start(
        [run.engine("sta"), "-no_init", "-no_splash", "-exit", folder / "sta.tcl"],
        cwd=folder,
        log=folder / "sta.log",
        timeout=time_limit("sta"),
    )
    stopped = started.problem(corner.name)
    if started.timed_out:
        return [stopped], {}
    names = read_text(folder / "nets.txt")
    failures, details = judge_sta(
        started.text,
        corner.name,
        None if names is None else names.split(),
        spef_nets(read_text(spef) or ""),
        run.chip.clock_skew_max_ns,
        supply,
        (cells["tap"], *cells["fill"], *cells["decap"]),
    )
    if stopped and not failures:
        failures.append(stopped)
    if not failures and not run.sdf(corner.name).is_file():
        failures.append(f"{corner.name}: OpenSTA wrote no SDF")
    return failures, details


def gate_sta(run):
    missing = run.need_pdk("sta") or run.need_engines("sta", "sta")
    if missing:
        return missing
    begin(run, "sta")
    missing = need_layout(run, "sta")
    if missing:
        return missing
    if run.corner_problems:
        return run.result("sta", list(run.corner_problems), [], "the corners")
    missing = need_files(run, "sta", sorted({str(c.liberty.relative_to(run.pdk.root)) for c in run.corners}))
    if missing:
        return missing
    netlist, stopped = taken(run, "sta", run.final_netlist())
    if stopped:
        return stopped
    spefs: dict[str, Path] = {}
    for wire in sorted({c.wire for c in run.corners}):
        spefs[wire], stopped = taken(run, "sta", run.spef(wire))
        if stopped:
            return stopped
    import chipfront

    judged = {relative(run, p): chipflow.sha256(p) for p in (netlist, *spefs.values())}
    constraints = chipflow.sha256(run.chip.constraints) if run.chip.constraints.is_file() else ""
    # The ledger of hashes is 1 file: it is read before the corners start and written after they end,
    # never by 2 corners at once.
    with ThreadPoolExecutor(max_workers=max(1, run.jobs)) as pool:
        results = list(pool.map(lambda c: sta_corner(run, c, netlist, spefs[c.wire]), run.corners))
    failures = [chipfront.short(line, run) for found, _ in results for line in found]
    failures += unchanged(run, judged)
    by_corner = {c.name: d for c, (_, d) in zip(run.corners, results, strict=True)}
    passed = [c.name for c, (found, _) in zip(run.corners, results, strict=True) if not found]
    for name in passed:
        run.record("sta", run.sdf(name))
    warnings = []
    if run.chip.clock_skew_max_ns is None:
        warnings.append("chip.json names no limits.clock_skew_ns: the skew is reported and held to nothing")
    summary = f"{len(run.corners)} corners"
    for name in ("setup", "hold"):
        known = {c: d[f"{name}_slack_ns"] for c, d in by_corner.items() if f"{name}_slack_ns" in d}
        if known:
            worst = min(known, key=known.get)
            summary += f", least {name} slack {known[worst]:g} ns at {worst}"
    result = run.result("sta", failures, warnings, summary, {"corners": by_corner})
    if result.status == "pass":
        logs = [run.base / "sta" / name / "sta.log" for name in passed]
        write_passed(run, "sta", judged, logs, corners=passed, constraints=constraints)
    return result


# ------------------------------------------------------------------------- DRC


def lyrdb_items(xml_text: str, top: str | None = None) -> tuple[int | None, list[str]]:
    """A KLayout report database as (the count of its items, the rules they break). The count is None
    for text that is no report database, that has no list of items, or that is the report of another
    top cell than `top`: none of them is a report of 0 items."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None, []
    listed = root.find("items")
    if root.tag != "report-database" or listed is None:
        return None, []
    if top is not None and (root.findtext("top-cell") or "").strip() != top:
        return None, []
    items = listed.findall("item")
    rules = sorted({(item.findtext("category") or "").strip("'") for item in items})
    return len(items), rules


def judge_magic_drc(log: str, report: str | None) -> tuple[list[str], int | None]:
    """Magic's rule check as (failures, the count of boxes that break a rule). The check stands when
    Magic read the layout whole, the script wrote its count in the log and in the report, the 2 are
    the same, and the count is 0."""
    unread = magic_read_errors(log)
    if unread:
        return [f"Magic did not read the layout whole: {unread[0]}"], None
    count = re.search(r"^WORKCENTER drc count (\d+)", log, re.M)
    written = re.search(r"^WORKCENTER drc count (\d+)", report or "", re.M)
    if not count or not written:
        return ["Magic wrote no count of the boxes that break a rule"], None
    if count.group(1) != written.group(1):
        return [f"Magic's report counts {written.group(1)} and its log {count.group(1)}"], None
    found = int(count.group(1))
    if not found:
        return [], 0
    rule = next((line for line in (report or "").splitlines() if line and not line.startswith(" ")), "")
    return [f"{found} boxes break a rule; the first rule: {rule}"], found


def gate_drc(run):
    missing = run.need_pdk("drc") or run.need_engines("drc", "magic", "klayout")
    if missing:
        return missing
    folder = begin(run, "drc")
    missing = need_layout(run, "drc")
    if missing:
        return missing
    decks = run.pdk.table["drc"]
    missing = need_files(
        run, "drc", [run.pdk.table["magic"]["rc"], *[d["file"] for d in decks if "file" in d]]
    )
    if missing:
        return missing
    gds, stopped = taken(run, "drc", run.gds())
    if stopped:
        return stopped
    judged = {relative(run, gds): chipflow.sha256(gds)}
    failures: list[str] = []
    details: dict = {"decks": {}, "gds_sha256": judged[relative(run, gds)]}
    reports: list[Path] = []
    for deck in decks:
        name = deck["name"]
        if deck["engine"] == "magic":
            report = folder / f"{name}.rpt"
            started = run.start(
                [
                    run.engine("magic"),
                    "-dnull",
                    "-noconsole",
                    "-rcfile",
                    run.pdk.file(run.pdk.table["magic"]["rc"]),
                    SCRIPTS / "drc.tcl",
                ],
                cwd=folder,
                log=folder / f"{name}.log",
                timeout=time_limit("drc"),
                env=kit_env(run, GDS=gds, TOP=run.chip.top, REPORT=report),
            )
            found, count = judge_magic_drc(started.text, read_text(report))
            found = [f"{name}: {line}" for line in found]
            stopped = started.problem(name)
            if stopped or count is None:
                # An engine that did not end well counted nothing the gate can hold.
                said = stopped or f"{found[0]} (log {started.log})"
                found, count = [with_error(said, started.text)], None
        else:
            report = folder / f"{name}.lyrdb"
            variables = {
                "input": gds,
                "top_cell": run.chip.top,
                "report": report,
                **deck.get("variables", {}),
            }
            started = run.start(
                [
                    run.engine("klayout"),
                    "-b",
                    "-r",
                    run.pdk.file(deck["file"]),
                    *[word for key, value in variables.items() for word in ("-rd", f"{key}={value}")],
                ],
                cwd=folder,
                log=folder / f"{name}.log",
                timeout=time_limit("drc"),
                env=kit_env(run),
            )
            stopped = started.problem(name)
            count, rules = lyrdb_items(read_text(report) or "", run.chip.top)
            if stopped or count is None:
                count = None
                found = [
                    stopped
                    or f"{name}: KLayout wrote no report database for {run.chip.top} (log {started.log})"
                ]
            else:
                found = [f"{name}: {count} items break a rule: {', '.join(rules[:5])}"] if count else []
        failures += found
        if count is not None:
            details["decks"][name] = count
            reports.append(report)
    import chipfront

    failures = [chipfront.short(line, run) for line in failures] + unchanged(run, judged)
    counts = ", ".join(f"{name} {count}" for name, count in details["decks"].items())
    result = run.result(
        "drc", failures, [], f"{len(decks)} decks: {counts or 'none counted'}", details, reports
    )
    if result.status == "pass":
        write_passed(run, "drc", judged, reports, decks=details["decks"])
    return result


# --------------------------------------------------------------------- ANTENNA


def judge_antenna(text: str, report: str | None) -> tuple[list[str], dict]:
    """OpenROAD's check_antennas as (failures, counts). It passes when the script reached its end,
    the log and the report each count 0 nets and 0 pins, and the 2 agree. A count that is not there
    is a failure."""
    nets = re.search(r"Found (\d+) net violations", text)
    pins = re.search(r"Found (\d+) pin violations", text)
    if "WORKCENTER antenna done" not in text or not nets or not pins:
        errors = ERROR_RE.findall(text)
        return [
            f"OpenROAD wrote no antenna counts: {errors[0].strip() if errors else 'its log says where'}"
        ], {}
    counts = {"net_violations": int(nets.group(1)), "pin_violations": int(pins.group(1))}
    listed_nets = re.search(r"^Number of nets violated: (\d+)", report or "", re.M)
    listed_pins = re.search(r"^Number of pins violated: (\d+)", report or "", re.M)
    if not listed_nets or not listed_pins:
        return ["OpenROAD wrote no antenna report with its counts"], counts
    if (int(listed_nets.group(1)), int(listed_pins.group(1))) != tuple(counts.values()):
        return [
            f"the antenna report counts {listed_nets.group(1)} nets and {listed_pins.group(1)} pins, and the "
            f"log {counts['net_violations']} and {counts['pin_violations']}"
        ], counts
    if counts["net_violations"] or counts["pin_violations"]:
        return [
            f"{counts['net_violations']} nets and {counts['pin_violations']} pins collect more charge "
            "than their gates take: build again with diodes or more repair"
        ], counts
    return [], counts


def gate_antenna(run):
    missing = run.need_pdk("antenna") or run.need_engines("antenna", "openroad")
    if missing:
        return missing
    folder = begin(run, "antenna")
    missing = need_layout(run, "antenna")
    if missing:
        return missing
    database, stopped = taken(run, "antenna", run.database())
    if stopped:
        return stopped
    judged = {relative(run, database): chipflow.sha256(database)}
    report = folder / "antenna.rpt"
    write_vars(folder, {"database": database, "out": folder})
    started = run.start(
        [run.engine("openroad"), "-no_init", "-exit", SCRIPTS / "antenna.tcl"],
        cwd=folder,
        log=folder / "openroad.log",
        timeout=time_limit("antenna"),
    )
    failures, counts = judge_antenna(started.text, read_text(report))
    stopped = started.problem("openroad")
    if stopped and not failures:
        failures.append(stopped)
    import chipfront

    failures = [chipfront.short(line, run) for line in failures] + unchanged(run, judged)
    result = run.result("antenna", failures, [], "the routed database", counts, [report])
    if result.status == "pass":
        write_passed(run, "antenna", judged, [report])
    return result


# ------------------------------------------------------------------------- LVS


def judge_extract(log: str, feedback: str | None) -> list[str]:
    """Magic's extraction as failures. It stands when Magic read the layout whole, the script reached
    its end, and Magic names no error: an overlap of 2 materials that do not connect is one, and Magic
    exits 0 with it."""
    unread = magic_read_errors(log)
    if unread:
        return [f"Magic did not read the layout whole: {unread[0]}"]
    if "WORKCENTER extracted" not in log:
        return ["Magic stopped before it wrote the layout's netlist"]
    failures = []
    total = re.search(r"^Total of (\d+) errors?", log, re.M)
    overlaps = re.findall(r'feedback add "(Illegal overlap[^"]*)"', feedback or "")
    if feedback is None:
        failures.append("Magic wrote no list of what it found while extracting")
    if total or overlaps:
        count = total.group(1) if total else str(len(overlaps))
        first = overlaps[0] if overlaps else "its feedback file names them"
        failures.append(f"the extraction names {count} errors: {first}")
    return failures


def judge_lvs(report: str) -> tuple[list[str], dict]:
    """Netgen's report as (failures, details). A report holds 1 comparison for each pair of cells, each
    ending in a line that starts with `Netlists`, and 1 final result for the top cells. The layout is
    the netlist only when that 1 result reads `Circuits match uniquely.`, every comparison reads
    `Netlists match uniquely.`, and no property error is named. Netgen writes the final result
    `Circuits match uniquely.` over a cell whose transistor has another size than the netlist's, and
    names the cell under it."""
    details: dict = {}
    results = [said.strip() for said in re.findall(r"^Final result:[ \t]*(.*)$", report, re.M)]
    if not results:
        return ["Netgen wrote no final result"], details
    if len(results) > 1:
        return [
            f"Netgen's report holds {len(results)} final results ({'; '.join(results)}): it is not the "
            "report of 1 comparison"
        ], details
    said = results[0]
    details["result"] = said
    failures = (
        [] if said == "Circuits match uniquely." else [f"the layout is not the netlist: Netgen says: {said}"]
    )
    compared = [line.strip() for line in re.findall(r"^Netlists .*$", report, re.M)]
    other = [line for line in compared if line != "Netlists match uniquely."]
    details["comparisons"] = len(compared)
    if not compared:
        failures.append("Netgen's report holds no comparison of 2 cells")
    elif other and not failures:
        failures.append(
            f"{len(other)} of the report's {len(compared)} comparisons do not read `Netlists match "
            f"uniquely.`, under a final result that does: {other[0]}"
        )
    listed = re.search(r"^The following cells had property errors:\n((?:[ \t]+\S+\n?)+)", report, re.M)
    if listed or "Property errors were found." in report or "with property errors" in report:
        cells = ", ".join(listed.group(1).split()) if listed else "a cell"
        failures.append(
            "a device's size in the layout differs from the netlist's: Netgen names property errors in "
            f"{cells}"
        )
    counted = re.findall(r"^Number of devices: (\d+)\s*\|Number of devices: (\d+)", report, re.M)
    if counted:
        details["devices"] = {"layout": int(counted[-1][0]), "netlist": int(counted[-1][1])}
    return failures, details


def gate_lvs(run):
    missing = run.need_pdk("lvs") or run.need_engines("lvs", "magic", "netgen")
    if missing:
        return missing
    folder = begin(run, "lvs")
    missing = need_layout(run, "lvs")
    if missing:
        return missing
    library = run.pdk.library
    missing = need_files(
        run, "lvs", [run.pdk.table["magic"]["rc"], library["spice"], run.pdk.table["lvs"]["setup"]]
    )
    if missing:
        return missing
    gds, stopped = taken(run, "lvs", run.gds())
    if stopped:
        return stopped
    netlist, stopped = taken(run, "lvs", run.power_netlist())
    if stopped:
        return stopped
    supply = [library["supply"]["power"]["pins"][0], library["supply"]["ground"]["pins"][0]]
    text = netlist.read_text(encoding="utf-8", errors="replace")
    without = [pin for pin in supply if f".{pin}(" not in text]
    if without:
        return run.result(
            "lvs",
            [
                f"the netlist has no {', '.join(without)} pins: LVS compares the supply too, "
                "so it takes the netlist written with them"
            ],
            [],
            "the netlist",
        )
    import chipfront

    judged = {relative(run, p): chipflow.sha256(p) for p in (gds, netlist)}
    (folder / "ext").mkdir()
    extracted = run.start(
        [
            run.engine("magic"),
            "-dnull",
            "-noconsole",
            "-rcfile",
            run.pdk.file(run.pdk.table["magic"]["rc"]),
            SCRIPTS / "extract.tcl",
        ],
        cwd=folder / "ext",
        log=folder / "extract.log",
        timeout=time_limit("lvs"),
        env=kit_env(run, GDS=gds, TOP=run.chip.top, OUT=folder),
    )
    spice = folder / f"{run.chip.top}.lvs.spice"
    stopped = extracted.problem("magic, extracting the layout")
    failures = judge_extract(extracted.text, read_text(folder / "extract.feedback.txt"))
    if stopped:
        failures = [with_error(stopped, extracted.text)]
    if not failures and not spice.is_file():
        failures.append("Magic extracted no netlist")
    if failures:
        failures = [
            chipfront.short(line if "(log " in line else f"{line} (log {extracted.log})", run)
            for line in failures
        ]
        return run.result("lvs", failures, [], "the extraction", {}, [folder / "extract.log"])
    compared = run.start(
        [run.engine("netgen"), "-batch", "source", SCRIPTS / "lvs.tcl"],
        cwd=folder,
        log=folder / "netgen.log",
        timeout=time_limit("lvs"),
        env=kit_env(
            run,
            LAYOUT_SPICE=spice,
            CELL_SPICE=run.pdk.file(library["spice"]),
            NETLIST=netlist,
            SETUP=run.pdk.file(run.pdk.table["lvs"]["setup"]),
            TOP=run.chip.top,
            OUT=folder,
        ),
    )
    report = folder / "lvs.rpt"
    written = read_text(report)
    stopped = compared.problem("netgen")
    if stopped or written is None or "WORKCENTER lvs done" not in compared.text:
        said = stopped or f"Netgen wrote no report of the comparison (log {compared.log})"
        return run.result(
            "lvs", [chipfront.short(with_error(said, compared.text), run)], [], "the comparison"
        )
    failures, details = judge_lvs(written)
    failures += unchanged(run, judged)
    summary = "the layout against the netlist with its supply pins"
    if "devices" in details:
        summary += f": {details['devices']['layout']} devices against {details['devices']['netlist']}"
    result = run.result("lvs", failures, [], summary, details, [report])
    if result.status == "pass":
        write_passed(run, "lvs", judged, [report])
    return result


# ---------------------------------------------------------------------- EXPORT


def gate_export(run):
    """The files a fabrication run takes, copied into chip/tapeout/ with the gates' reports and a
    manifest: each file's SHA256, each engine's version, the process kit and its version, the corners.
    A file is copied only when it is the bytes LAYOUT recorded and each gate that judges it passed on
    those bytes: STA on the netlist and the parasitics at every corner the project's ranges select,
    GLSIM on the netlist, DRC and LVS on the GDS, ANTENNA on the routed database, LVS on the netlist
    with its supply pins. And only while the project's own files are the bytes each gate passed on: the
    RTL and the headers it includes, the benches and their bounds, the constraints, chip.json, and the
    mapped netlist LAYOUT was built from. All 9 gates before EXPORT hold a record of their pass."""
    missing = run.need_pdk("export")
    if missing:
        return missing
    # The hand-off of an earlier run goes first: a run that is refused leaves none behind.
    shutil.rmtree(run.base / "tapeout", ignore_errors=True)
    library = run.pdk.library
    every = [c.name for c in chipflow.select_corners(run.pdk, run.chip)[0]]
    records: dict[str, dict] = {}
    for gate in chipflow.GATE_NAMES[:-1]:
        record, problem, absent = read_passed(run, gate)
        if record is None:
            said = f"{problem}: EXPORT hands out only a layout that every gate passed"
            return run.skip("export", said) if absent else run.result("export", [said], [], "the hand-off")
        records[gate] = record
    ran = records["sta"].get("corners", [])
    left = [name for name in every if name not in ran]
    if left:
        return run.skip(
            "export",
            f"STA passed at {len(every) - len(left)} of the {len(every)} corners the project's ranges select "
            f"({', '.join(left[:3])}{' ...' if len(left) > 3 else ''} did not run): EXPORT hands out only a "
            "layout whose timing every corner judged",
        )
    wanted = [run.gds(), run.final_netlist(), run.power_netlist(), run.def_file()]
    wanted += [run.spef(w) for w in sorted(library["wires"])]
    wanted += [run.sdf(name) for name in every]
    failures: list[str] = []
    # LINT, SIM, SYNTH, LAYOUT and GLSIM read the project's own files, and LAYOUT the mapped netlist:
    # each file must still be the bytes its gate passed on, and no file may have come since, or the
    # layout is of another design than the one that was proven. A file is named 1 time, with the first
    # gate that read it. The files of the layout's own folder are held below, to every gate that
    # judged them.
    import chipfront

    named: set[str] = set()
    for gate in chipfront.INPUT_GATES:
        lines = run.changed_since(gate, records[gate])
        lines += [
            f"{run.name_of(path)} was added after {gate.upper()} passed. Run the gates again"
            for path in chipfront.project_inputs(run, gate)
            if path.is_file() and run.name_of(path) not in records[gate]["judged"]
        ]
        for line in lines:
            name = line.split(" ", 1)[0]
            if name not in named and not name.startswith("chip/layout/"):
                named.add(name)
                failures.append(line)
    constraints = chipflow.sha256(run.chip.constraints) if run.chip.constraints.is_file() else ""
    if records["sta"].get("constraints") != constraints and run.name_of(run.chip.constraints) not in named:
        failures.append(
            f"{run.chip.constraints.name} changed after STA passed: its hash differs. Run STA again"
        )
    hashes: dict[Path, str] = {}
    for path in wanted:
        _, problem = run.take(path)
        if problem:
            failures.append(problem)
        else:
            hashes[path] = chipflow.sha256(path)
    # Each gate's record names the hash of what it judged: it must be the hash of what is copied.
    judges = {
        run.gds(): ("layout", "drc", "lvs"),
        run.final_netlist(): ("layout", "sta", "glsim"),
        run.power_netlist(): ("layout", "lvs"),
        run.def_file(): ("layout",),
        run.database(): ("layout", "antenna"),
        **{run.spef(w): ("layout", "sta") for w in sorted(library["wires"])},
    }
    database, problem = run.take(run.database())
    if problem:
        failures.append(problem)
    else:
        hashes[database] = chipflow.sha256(database)
    for path, gates in judges.items():
        for gate in gates:
            judged = records[gate]["judged"].get(relative(run, path))
            if path in hashes and judged != hashes[path]:
                failures.append(
                    f"{relative(run, path)} is not the file {gate.upper()} passed: its hash differs. Run "
                    f"{gate.upper()} again"
                    if judged
                    else f"{relative(run, path)}: {gate.upper()} did not judge it"
                )
    if failures:
        return run.result("export", failures, [], "the hand-off")
    folder = run.fresh("tapeout")
    files = {}
    for path in wanted:
        target = folder / path.name if path.suffix != ".sdf" else folder / f"{path.parent.name}.sdf"
        shutil.copyfile(path, target)
        files[target.name] = chipflow.sha256(target)
        if files[target.name] != hashes[path]:
            failures.append(f"{relative(run, path)} changed while it was copied: its hash differs")
    reports = {}
    for gate, record in records.items():
        for name in record.get("reports", []):
            source = run.out / name
            if not source.is_file():
                failures.append(f"{name}, the report of {gate.upper()}'s pass, is not there")
                continue
            parts = Path(name).parts[2:]
            target = folder / "reports" / gate / "-".join(parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            reports[str(target.relative_to(folder))] = chipflow.sha256(target)
    if failures:
        shutil.rmtree(folder)
        return run.result("export", failures, [], "the hand-off")
    manifest = {
        "top": run.chip.top,
        "pdk": {"name": run.pdk.name, "version": run.pdk.installed, "library": run.pdk.library_name},
        "corners": every,
        "decks": [{"name": d["name"], "origin": d["origin"]} for d in run.pdk.table["drc"]],
        "engines": {name: chipflow.engine_version(run.cli, name) for name in chipflow.ENGINES},
        "files": files,
        "constraints": {"file": run.chip.constraints.name, "sha256": constraints},
        "reports": reports,
        "judged": {gate: record["judged"] for gate, record in records.items()},
        "scope": chipflow.scope_line(run),
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return run.result(
        "export",
        [],
        [],
        f"{len(files)} files, {len(reports)} reports and manifest.json in {relative(run, folder)}",
        manifest,
        [folder],
    )


# ---------------------------------------------------------------------- render

# KLayout's own Python, run in batch mode with no display. It draws the top cell with the kit's layer
# properties: all layers, then 1 picture for each routing layer that holds a shape. `layers` is
# `name:layer/datatype,layer/datatype;name:...`, from the kit's layer map.
RENDER_SCRIPT = """import pya

view = pya.LayoutView()
view.load_layout(gds, True)
view.load_layer_props(lyp)
view.max_hier()
view.set_config("background-color", "#ffffff")
view.set_config("grid-visible", "false")
layout = view.active_cellview().layout()
cell = layout.cell(top)
if cell is None:
    raise SystemExit("WORKCENTER no cell " + top)
view.active_cellview().cell = cell
view.zoom_fit()
box = cell.dbbox()
side = int(pixels)
width = side if box.width() >= box.height() else max(1, int(side * box.width() / box.height()))
height = side if box.height() >= box.width() else max(1, int(side * box.height() / box.width()))
view.save_image(out + "/" + top + ".png", width, height)
print("WORKCENTER picture " + top + ".png all")
for entry in layers.split(";"):
    name, pairs = entry.split(":")
    wanted = set(tuple(int(n) for n in pair.split("/")) for pair in pairs.split(","))
    held = False
    for pair in wanted:
        index = layout.find_layer(pair[0], pair[1])
        if index is not None and not layout.begin_shapes(cell, index).at_end():
            held = True
    if not held:
        print("WORKCENTER empty " + name)
        continue
    for node in view.each_layer():
        node.visible = (node.source_layer, node.source_datatype) in wanted
    view.save_image(out + "/" + top + "." + name + ".png", width, height)
    print("WORKCENTER picture " + top + "." + name + ".png " + name)
print("WORKCENTER render done")
"""


def routing_layers(tracks_info: str, layer_map: str, bottom: str, top: str) -> list[tuple[str, list[str]]]:
    """The routing layers from `bottom` to `top` as (name, its GDS `layer/datatype` pairs). The kit's
    tracks file names the layers in order; the kit's layer map gives each name its numbers."""
    names: list[str] = []
    for line in tracks_info.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[1] in ("X", "Y") and parts[0] not in names:
            names.append(parts[0])
    if bottom not in names or top not in names:
        return []
    out = []
    for name in names[names.index(bottom) : names.index(top) + 1]:
        pairs = []
        for line in layer_map.splitlines():
            parts = line.split()
            if len(parts) == 4 and parts[0] == name and parts[2].isdigit() and parts[3].isdigit():
                pairs.append(f"{parts[2]}/{parts[3]}")
        if pairs:
            out.append((name, pairs))
    return out


def render(run, args) -> int:
    """`chip render`: PNG pictures of the layout the gates recorded, in <out>/chip/render/: the top cell
    with every layer, and 1 for each routing layer that holds a shape. Exit code 0 with the pictures
    written; 1 for a layout the gates did not record or a picture KLayout did not draw; 2 where the
    layout, KLayout or the process kit is not there."""

    def say(code: int, line: str) -> int:
        if getattr(args, "json", False):
            print(json.dumps({"pictures": [], "empty": [], "problem": line}, indent=2))
        else:
            print(f"chip render: {line}")
        return code

    if run.pdk is None:
        return say(
            2 if run.pdk_absent else 1, (list(run.pdk_problems) or ["the process table was not read"])[0]
        )
    if run.engine("klayout") is None:
        return say(2, "klayout is not installed: `workcenter doctor` lists the chip engines")
    drawn = run.pdk.table["klayout"]
    plan = run.pdk.library["floorplan"]
    absent = [
        f
        for f in (drawn["layer_properties"], drawn["layer_map"], plan["tracks"])
        if not run.pdk.file(f).is_file()
    ]
    if absent:
        return say(2, f"the process kit {run.pdk.name} has no {', '.join(absent)}")
    gds, problem = run.take(run.gds())
    if problem:
        return say(
            2 if not gds.is_file() else 1, f"{problem}: a picture is drawn of the layout LAYOUT recorded"
        )
    layers = routing_layers(
        run.pdk.file(plan["tracks"]).read_text(encoding="utf-8"),
        run.pdk.file(drawn["layer_map"]).read_text(encoding="utf-8"),
        plan["routing_layers"]["bottom"],
        plan["routing_layers"]["top"],
    )
    if not layers:
        return say(1, f"the kit's layer map names no routing layer of pdks/{run.pdk.name}.json")
    folder = run.fresh("render")
    script = folder / "render.py"
    script.write_text(RENDER_SCRIPT, encoding="utf-8")
    variables = {
        "gds": gds,
        "lyp": run.pdk.file(drawn["layer_properties"]),
        "out": folder,
        "top": run.chip.top,
        "pixels": RENDER_PIXELS,
        "layers": ";".join(f"{name}:{','.join(pairs)}" for name, pairs in layers),
    }
    started = run.start(
        [
            run.engine("klayout"),
            "-b",
            "-r",
            script,
            *[word for key, value in variables.items() for word in ("-rd", f"{key}={value}")],
        ],
        cwd=folder,
        log=folder / "klayout.log",
        timeout=time_limit("render"),
        env=kit_env(run),
    )
    stopped = started.problem("klayout")
    named = re.findall(r"^WORKCENTER picture (\S+) (\S+)$", started.text, re.M)
    empty = re.findall(r"^WORKCENTER empty (\S+)$", started.text, re.M)
    pictures = [folder / name for name, _ in named]
    bad = [p.name for p in pictures if not p.is_file() or p.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n"]
    if stopped or "WORKCENTER render done" not in started.text or bad or not pictures:
        return say(1, stopped or f"KLayout did not draw {', '.join(bad) or 'the layout'} (log {started.log})")
    if getattr(args, "json", False):
        print(json.dumps({"pictures": [str(p) for p in pictures], "empty": empty}, indent=2))
        return 0
    for path in pictures:
        print(f"wrote {path}")
    for name in empty:
        print(f"no picture of {name}: the layout holds no shape on it")
    print(f"chip render: {len(pictures)} pictures of {run.chip.top} in {folder}")
    return 0
