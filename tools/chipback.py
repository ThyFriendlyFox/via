"""The back chip gates: LAYOUT, STA, DRC, ANTENNA, LVS and EXPORT. tools/chipflow.py holds the contract.

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
    EXPORT   the files a fabrication run takes, and that they are the files the gates judged
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
ROUTER_RE = re.compile(r"\[INFO DRT-0199\]\s+Number of violations = (\d+)\.")
AREA_RE = re.compile(r"Design area ([\d.]+) u\^2 ([\d.]+)% utilization")
ERROR_RE = re.compile(r"^\[ERROR [A-Z]+-\d+\].*$", re.M)
SLACK_RE = re.compile(r"^worst slack (-?[\d.]+)", re.M)
TNS_RE = re.compile(r"^tns (-?[\d.]+)", re.M)
# The headroom the build leaves under the utilisation limit when the project names no die: the clock
# tree and the timing repair add cells after the floorplan is set.
UTILIZATION_HEADROOM = 0.1


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


def taken(run, gate: str, path: Path):
    """A file a gate before this one handed on: (path, None), or (path, the gate's Result): a skip
    when the file is not there, a failure when it changed after it was recorded."""
    path, problem = run.take(path)
    if problem is None:
        return path, None
    if not path.is_file():
        return path, run.skip(gate, problem)
    return path, run.result(gate, [problem], [], "its input")


def gds_top_cells(data: bytes) -> list[str]:
    """The cells of a GDSII stream that no other cell places: its top cells. A stream is records of a
    2-byte length, a record type and a data type; STRNAME (0x06) names a cell and SNAME (0x12) a cell
    that is placed."""
    defined: list[str] = []
    placed: set[str] = set()
    at = 0
    while at + 4 <= len(data):
        length, kind = struct.unpack(">HB", data[at : at + 3])
        if length < 4:
            break
        if kind in (0x06, 0x12):
            name = data[at + 4 : at + length].rstrip(b"\0").decode("ascii", "replace")
            (defined.append if kind == 0x06 else placed.add)(name)
        at += length
    return [name for name in defined if name not in placed]


# ---------------------------------------------------------------------- LAYOUT


def judge_layout(text: str, limit: float | None) -> tuple[list[str], list[str], dict]:
    """OpenROAD's output as (failures, warnings, details). The build stands when no error is named,
    the script reached its last line, the detailed router's last count of violations is 0, and the
    core's utilisation is within the project's limit."""
    failures = [line.strip() for line in ERROR_RE.findall(text)][:5]
    for marker, stage in (
        ("WORKCENTER placement checked", "the placement was checked"),
        ("WORKCENTER routed", "the routing ended"),
        ("WORKCENTER layout written", "the layout was written"),
    ):
        if marker not in text:
            failures.append(f"OpenROAD stopped before {stage}")
            break
    counts = ROUTER_RE.findall(text)
    details: dict = {}
    if counts:
        details["router_violations"] = int(counts[-1])
        if int(counts[-1]) != 0:
            failures.append(
                f"the router left {counts[-1]} violations: shorts or spacing errors between wires. Give the "
                "design more room"
            )
    elif "WORKCENTER routed" in text:
        failures.append("the router printed no count of violations")
    area = AREA_RE.search(text)
    if area:
        details["area_um2"] = float(area.group(1))
        details["utilization"] = round(float(area.group(2)) / 100, 4)
        if limit is not None and details["utilization"] > limit:
            failures.append(
                f"utilisation {details['utilization']:g} is over the limit {limit:g} of chip.json: "
                "take a larger die, or cut logic. Do not raise the limit"
            )
    for net in re.findall(r"^WORKCENTER grid (\S+) open", text, re.M):
        failures.append(
            f"the supply grid leaves parts of {net} unconnected: its rails do not all reach a stripe"
        )
    warnings = sorted({line.strip() for line in text.splitlines() if "Unable to repair all" in line})
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


def gate_layout(run):
    missing = run.need_pdk("layout") or run.need_engines("layout", "openroad", "magic")
    if missing:
        return missing
    netlist, stopped = taken(run, "layout", run.mapped_netlist())
    if stopped:
        return stopped
    import chipfront

    chip, library = run.chip, run.pdk.library
    plan, cells, supply = library["floorplan"], library["cells"], library["supply"]
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
    folder = run.fresh("layout")
    wire = nominal_wire(library)
    margin_x, margin_y = plan["core_margin_um"]
    die = core = ""
    if chip.die_um:
        width, height = chip.die_um
        die = f"0 0 {width:g} {height:g}"
        core = f"{margin_x:g} {margin_y:g} {width - margin_x:g} {height - margin_y:g}"
    aim = max(0.05, (chip.utilization_max or plan["placement_density"]) - UTILIZATION_HEADROOM)
    (folder / "tracks.tcl").write_text(
        tracks_tcl(run.pdk.file(plan["tracks"]).read_text(encoding="utf-8")), encoding="utf-8"
    )
    write_vars(
        folder,
        {
            "top": chip.top,
            "out": folder,
            "netlist": netlist,
            "sdc": chip.constraints,
            "liberty": chipfront.synth_liberty(run),
            "tech_lef": run.pdk.file(library["wires"][wire]["techlef"]),
            "cell_lef": run.pdk.file(library["lef"]),
            "die_area": die,
            "core_area": core,
            "utilization": round(aim * 100),
            "core_space": max(margin_x, margin_y),
            "site": plan["site"],
            "pin_layer_h": plan["pin_layers"]["horizontal"],
            "pin_layer_v": plan["pin_layers"]["vertical"],
            "tap_cell": cells["tap"],
            "tap_distance": plan["tap_distance_um"],
            "wire_rc_signal": plan["wire_rc_layers"]["signal"],
            "wire_rc_clock": plan["wire_rc_layers"]["clock"],
            "density": plan["placement_density"],
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
            "rcx": [
                x for w in sorted(library["wires"]) for x in (w, run.pdk.file(library["wires"][w]["rcx"]))
            ],
        },
    )
    started = run.start(
        [run.engine("openroad"), "-no_init", "-exit", "-threads", max(1, run.jobs), SCRIPTS / "layout.tcl"],
        cwd=folder,
        log=folder / "openroad.log",
        timeout=chipflow.TIME_LIMITS["layout"],
    )
    failures, warnings, details = judge_layout(started.text, chip.utilization_max)
    stopped = started.problem("openroad")
    if stopped and not failures:
        failures.append(stopped)
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
            timeout=chipflow.TIME_LIMITS["layout"],
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
        if stopped or "WORKCENTER gds written" not in made.text or not run.gds().is_file():
            failures.append(stopped or f"Magic wrote no GDS (log {made.log})")
        else:
            tops = gds_top_cells(run.gds().read_bytes())
            details["gds_top_cells"] = tops
            if tops != [chip.top]:
                failures.append(f"the GDS's top cells are {', '.join(tops) or 'none'}, not {chip.top} alone")
    handed = [run.database(), run.def_file(), run.final_netlist(), run.power_netlist(), run.gds()]
    handed += [run.spef(w) for w in sorted(library["wires"])]
    if not failures:
        absent = [str(p.relative_to(run.out)) for p in handed if not p.is_file()]
        if absent:
            failures.append(f"the build did not write {', '.join(absent)}")
    if not failures:
        details["sha256"] = {str(p.relative_to(run.out)): run.record("layout", p) for p in handed}
    failures = [chipfront.short(line, run) for line in failures]
    summary = "the layout"
    if "utilization" in details:
        summary = f"{details['area_um2']:g} um2 of cells, utilisation {details['utilization']:g}"
    return run.result("layout", failures, warnings, summary, details, [run.gds(), folder / "openroad.log"])


# ------------------------------------------------------------------------- STA


def between(text: str, begin: str, end: str) -> str:
    start = text.find(begin)
    stop = text.find(end, start + len(begin)) if start >= 0 else -1
    return text[start + len(begin) : stop] if start >= 0 and stop >= 0 else ""


def worst_path(text: str, kind: str) -> str:
    """`from A to B` for the path of a report_checks block of that kind (`max` or `min`)."""
    for block in text.split("Startpoint: ")[1:]:
        if f"Path Type: {kind}" in block:
            start = block.split()[0]
            end = re.search(r"Endpoint: (\S+)", block)
            return f", from {start} to {end.group(1)}" if end else ""
    return ""


def judge_sta(
    text: str, corner: str, spef_nets: int | None, skew_limit: float | None, supply: tuple[str, ...] = ()
) -> tuple[list[str], dict]:
    """1 corner's OpenSTA output as (failures, details). The corner holds when the script reached its
    end, setup and hold slack are 0 or more, no path is negative, no slew, capacitance, pulse width or
    period limit is broken, the constraints leave nothing open, and every net has its parasitics."""
    failures: list[str] = []
    details: dict = {}
    if "WORKCENTER sta done" not in text:
        errors = [line.strip() for line in text.splitlines() if line.startswith("Error:")]
        return [
            f"{corner}: OpenSTA stopped before its end: {errors[0] if errors else 'its log says where'}"
        ], details
    setup = SLACK_RE.search(between(text, "WORKCENTER setup", "WORKCENTER hold"))
    hold = SLACK_RE.search(between(text, "WORKCENTER hold", "WORKCENTER violators begin"))
    tns = TNS_RE.search(text)
    for name, found, kind in (("setup", setup, "max"), ("hold", hold, "min")):
        if not found:
            failures.append(f"{corner}: no {name} slack was reported: no path is constrained")
            continue
        details[f"{name}_slack_ns"] = float(found.group(1))
        if float(found.group(1)) < 0:
            failures.append(f"{corner}: {name} slack {found.group(1)} ns{worst_path(text, kind)}")
    if tns:
        details["tns_ns"] = float(tns.group(1))
        if float(tns.group(1)) < 0 and not any("setup slack" in f for f in failures):
            failures.append(f"{corner}: total negative slack {tns.group(1)} ns")
    # check_setup names what the constraints leave open: each kind as a warning with its objects under
    # it. The supply nets are ports of the routed netlist and need no delay; a kind that names only
    # those names nothing.
    kind, named = "", []
    block = between(text, "WORKCENTER check_setup begin", "WORKCENTER check_setup end")
    for line in [*block.splitlines(), "Warning: end"]:
        if line.startswith("Warning:"):
            if kind and (named or not kind.startswith("There")):
                listed = f" {', '.join(named[:6])}{' ...' if len(named) > 6 else ''}" if named else ""
                failures.append(f"{corner}: {kind}{listed}")
            kind, named = line[len("Warning: ") :].strip(), []
        elif line.strip() and line.strip() not in supply:
            named.append(line.strip())
    broken = [
        line.strip()
        for line in between(text, "WORKCENTER violators begin", "WORKCENTER violators end").splitlines()
        if "(VIOLATED)" in line
    ]
    if broken:
        failures.append(
            f"{corner}: {len(broken)} pins break a slew, capacitance, pulse width or period limit: "
            f"{broken[0]}"
        )
    nets = re.search(r"WORKCENTER nets (\d+)", text)
    if nets and spef_nets is not None:
        details["nets"], details["nets_with_parasitics"] = int(nets.group(1)), spef_nets
        if spef_nets < int(nets.group(1)):
            failures.append(
                f"{corner}: {int(nets.group(1)) - spef_nets} of {nets.group(1)} nets have no parasitics "
                "in the SPEF: their wires count as nothing"
            )
    # report_clock_skew ends a clock's block with 3 numbers: latency, pessimism removed, skew.
    skew_block = between(text, "WORKCENTER skew begin", "WORKCENTER skew end")
    skews = [
        abs(float(v)) for v in re.findall(r"^\s*-?\d+\.\d+\s+-?\d+\.\d+\s+(-?\d+\.\d+)\s*$", skew_block, re.M)
    ]
    if skews:
        details["clock_skew_ns"] = max(skews)
        if skew_limit is not None and max(skews) > skew_limit:
            failures.append(
                f"{corner}: clock skew {max(skews):g} ns is over the limit {skew_limit:g} ns of chip.json"
            )
    return failures, details


def sta_corner(run, corner, netlist: Path) -> tuple[list[str], dict]:
    folder = run.base / "sta" / corner.name
    folder.mkdir(parents=True, exist_ok=True)
    spef, problem = run.take(run.spef(corner.wire))
    if problem:
        return [f"{corner.name}: {problem}"], {}
    both = run.pdk.library["supply"]
    supply = (both["power"]["net"], both["ground"]["net"])
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
        timeout=chipflow.TIME_LIMITS["sta"],
    )
    stopped = started.problem(corner.name)
    if stopped:
        return [stopped], {}
    spef_nets = len(re.findall(r"^\*D_NET ", spef.read_text(encoding="utf-8", errors="replace"), re.M))
    failures, details = judge_sta(started.text, corner.name, spef_nets, run.chip.clock_skew_max_ns, supply)
    if not failures and run.sdf(corner.name).is_file():
        run.record("sta", run.sdf(corner.name))
    return failures, details


def gate_sta(run):
    missing = run.need_pdk("sta") or run.need_engines("sta", "sta")
    if missing:
        return missing
    netlist, stopped = taken(run, "sta", run.final_netlist())
    if stopped:
        return stopped
    if run.corner_problems:
        return run.result("sta", list(run.corner_problems), [], "the corners")
    import chipfront

    run.fresh("sta")
    with ThreadPoolExecutor(max_workers=max(1, run.jobs)) as pool:
        results = list(pool.map(lambda c: sta_corner(run, c, netlist), run.corners))
    failures = [chipfront.short(line, run) for found, _ in results for line in found]
    by_corner = {c.name: d for c, (_, d) in zip(run.corners, results, strict=True)}
    warnings = []
    if run.chip.clock_skew_max_ns is None:
        warnings.append("chip.json names no limits.clock_skew_ns: the skew is reported and held to nothing")
    summary = f"{len(run.corners)} corners"
    for name in ("setup", "hold"):
        known = {c: d[f"{name}_slack_ns"] for c, d in by_corner.items() if f"{name}_slack_ns" in d}
        if known:
            worst = min(known, key=known.get)
            summary += f", least {name} slack {known[worst]:g} ns at {worst}"
    return run.result("sta", failures, warnings, summary, {"corners": by_corner})


# ------------------------------------------------------------------------- DRC


def lyrdb_items(xml_text: str) -> tuple[int | None, list[str]]:
    """A KLayout report database as (the count of its items, the rules they break)."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None, []
    items = root.findall(".//items/item")
    rules = sorted({(item.findtext("category") or "").strip("'") for item in items})
    return len(items), rules


def gate_drc(run):
    missing = run.need_pdk("drc") or run.need_engines("drc", "magic", "klayout")
    if missing:
        return missing
    gds, stopped = taken(run, "drc", run.gds())
    if stopped:
        return stopped
    folder = run.fresh("drc")
    failures: list[str] = []
    details: dict = {"decks": {}, "gds_sha256": chipflow.sha256(gds)}
    for deck in run.pdk.table["drc"]:
        name = deck["name"]
        if deck["engine"] == "magic":
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
                env=kit_env(run, GDS=gds, TOP=run.chip.top, OUT=folder),
            )
            count = re.search(r"WORKCENTER drc count (\d+)", started.text)
            stopped = started.problem(name)
            if stopped or not count:
                failures.append(stopped or f"{name}: Magic wrote no count (log {started.log})")
                continue
            details["decks"][name] = int(count.group(1))
            if int(count.group(1)):
                report = (folder / "magic.rpt").read_text(encoding="utf-8", errors="replace").splitlines()
                rule = next((line for line in report if line and not line.startswith(" ")), "")
                failures.append(f"{name}: {count.group(1)} boxes break a rule; the first rule: {rule}")
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
                env=kit_env(run),
            )
            stopped = started.problem(name)
            count, rules = (
                lyrdb_items(report.read_text(encoding="utf-8", errors="replace"))
                if report.is_file()
                else (None, [])
            )
            if stopped or count is None:
                failures.append(stopped or f"{name}: KLayout wrote no report (log {started.log})")
                continue
            details["decks"][name] = count
            if count:
                failures.append(f"{name}: {count} items break a rule: {', '.join(rules[:5])}")
    run.record("drc", gds)
    decks = ", ".join(f"{name} {count}" for name, count in details["decks"].items())
    return run.result("drc", failures, [], f"{len(run.pdk.table['drc'])} decks: {decks}", details)


# --------------------------------------------------------------------- ANTENNA


def judge_antenna(text: str) -> tuple[list[str], dict]:
    """OpenROAD's check_antennas output as (failures, counts): 0 net and 0 pin violations pass."""
    nets = re.search(r"Found (\d+) net violations", text)
    pins = re.search(r"Found (\d+) pin violations", text)
    if "WORKCENTER antenna done" not in text or not nets or not pins:
        errors = ERROR_RE.findall(text)
        return [
            f"OpenROAD wrote no antenna counts: {errors[0].strip() if errors else 'its log says where'}"
        ], {}
    counts = {"net_violations": int(nets.group(1)), "pin_violations": int(pins.group(1))}
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
    database, stopped = taken(run, "antenna", run.database())
    if stopped:
        return stopped
    folder = run.fresh("antenna")
    write_vars(folder, {"database": database, "out": folder})
    started = run.start(
        [run.engine("openroad"), "-no_init", "-exit", SCRIPTS / "antenna.tcl"],
        cwd=folder,
        log=folder / "openroad.log",
    )
    failures, counts = judge_antenna(started.text)
    stopped = started.problem("openroad")
    if stopped and not failures:
        failures.append(stopped)
    run.record("antenna", database)
    return run.result("antenna", failures, [], "the routed database", counts, [folder / "antenna.rpt"])


# ------------------------------------------------------------------------- LVS


def judge_lvs(report: str) -> list[str]:
    """Netgen's report as failures: the layout is the netlist only on `Circuits match uniquely.` with no
    property error."""
    result = re.search(r"Final result:\s*\n?\s*(.+)", report)
    if not result:
        return ["Netgen wrote no final result"]
    said = result.group(1).strip()
    failures = (
        [] if said == "Circuits match uniquely." else [f"the layout is not the netlist: Netgen says: {said}"]
    )
    if "Property errors were found." in report:
        failures.append(
            "a device's size in the layout differs from the netlist's: Netgen found property errors"
        )
    return failures


def gate_lvs(run):
    missing = run.need_pdk("lvs") or run.need_engines("lvs", "magic", "netgen")
    if missing:
        return missing
    gds, stopped = taken(run, "lvs", run.gds())
    if stopped:
        return stopped
    netlist, stopped = taken(run, "lvs", run.power_netlist())
    if stopped:
        return stopped
    library = run.pdk.library
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
    folder = run.fresh("lvs")
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
        env=kit_env(run, GDS=gds, TOP=run.chip.top, OUT=folder),
    )
    spice = folder / f"{run.chip.top}.lvs.spice"
    stopped = extracted.problem("magic, extracting the layout")
    if stopped or "WORKCENTER extracted" not in extracted.text or not spice.is_file():
        return run.result(
            "lvs", [stopped or f"Magic extracted no netlist (log {extracted.log})"], [], "the extraction"
        )
    compared = run.start(
        [run.engine("netgen"), "-batch", "source", SCRIPTS / "lvs.tcl"],
        cwd=folder,
        log=folder / "netgen.log",
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
    stopped = compared.problem("netgen")
    if stopped or not report.is_file():
        return run.result(
            "lvs", [stopped or f"Netgen wrote no report (log {compared.log})"], [], "the comparison"
        )
    failures = judge_lvs(report.read_text(encoding="utf-8", errors="replace"))
    run.record("lvs", gds)
    return run.result(
        "lvs", failures, [], "the layout against the netlist with its supply pins", {}, [report]
    )


# ---------------------------------------------------------------------- EXPORT


def gate_export(run):
    """The files a fabrication run takes, copied into chip/tapeout/ with a manifest: each file's SHA256,
    each engine's version, the process kit and its version, the corners. Every file is one a gate
    recorded, and the GDS is the one DRC, ANTENNA's database and LVS judged."""
    missing = run.need_pdk("export")
    if missing:
        return missing
    library = run.pdk.library
    wanted = [run.gds(), run.final_netlist(), run.power_netlist(), run.def_file()]
    wanted += [run.spef(w) for w in sorted(library["wires"])]
    wanted += [run.sdf(c.name) for c in run.corners]
    failures: list[str] = []
    for path in wanted:
        _, problem = run.take(path)
        if problem:
            failures.append(problem)
    ledger = run.ledger()
    judged = ledger.get(str(run.gds().relative_to(run.out)), {}).get("gate")
    if not failures and judged != "lvs":
        failures.append(
            f"the GDS was last recorded by {str(judged).upper()}, not by LVS: "
            "DRC and LVS judge the layout before it leaves"
        )
    if failures:
        absent = all("is not there" in f for f in failures)
        return (
            run.skip("export", failures[0]) if absent else run.result("export", failures, [], "the hand-off")
        )
    folder = run.fresh("tapeout")
    files = {}
    for path in wanted:
        target = folder / path.name if path.suffix != ".sdf" else folder / f"{path.parent.name}.sdf"
        shutil.copyfile(path, target)
        files[target.name] = chipflow.sha256(target)
    manifest = {
        "top": run.chip.top,
        "pdk": {"name": run.pdk.name, "version": run.pdk.installed, "library": run.pdk.library_name},
        "corners": [c.name for c in run.corners],
        "engines": {name: chipflow.engine_version(run.cli, name) for name in chipflow.ENGINES},
        "files": files,
        "scope": chipflow.scope_line(run),
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return run.result(
        "export",
        [],
        [],
        f"{len(files)} files and manifest.json in {folder.relative_to(run.out)}",
        manifest,
        [folder],
    )
