"""The front chip gates: LINT, SIM, SYNTH and GLSIM. tools/chipflow.py holds the contract.

Each gate is 2 parts. A judge reads what an engine wrote and returns failures and warnings; it starts
nothing, and tests hold it to real reports. A runner starts the engine through `run.start` and hands
the judge its output. Standard library only.

    LINT    Verilator: no construct that silicon and simulation read differently; the constraints
    SIM     Icarus Verilog: every bench reaches $finish with errors 0, x_outputs 0 and checks made
    SYNTH   Yosys: the RTL maps onto the library's cells with nothing left open
    GLSIM   Icarus Verilog: the same benches on the final netlist, every flop unknown at the start
"""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import chipflow

SCRIPTS = Path(__file__).resolve().parent / "chipscripts"

# The Verilator classes LINT fails on: each is a construct a simulator and a synthesizer read
# differently, or one that leaves a net with no driver or 2. Every other class is a warning.
LINT_FAIL = (
    "LATCH",
    "MULTIDRIVEN",
    "UNOPTFLAT",
    "COMBDLY",
    "CASEINCOMPLETE",
    "IMPLICIT",
    "PINMISSING",
    "SELRANGE",
    "WIDTHTRUNC",
    "UNDRIVEN",
    "STMTDLY",
    "ASSIGNDLY",
    "BLKANDNBLK",
)
VERILATOR_RE = re.compile(r"^%(Warning|Error)(?:-([A-Z0-9_]+))?: (.*)$")
# Text that makes 1 engine read another design than the next. LINT judges what Verilator reads, SIM
# what Icarus Verilog reads and SYNTH what Yosys reads: the 3 are 1 design only while no line speaks to
# 1 of them alone. Each entry: (pattern, whether it is looked for in comments too, what the line says).
# A comment that turns a check off is read in any case of letters and for any class: Verilator takes
# `widthtrunc` and the group name `WIDTH` as it takes `WIDTHTRUNC`.
TWO_DESIGNS = (
    (
        re.compile(r"verilator\s+lint_off\s+(-rule\s+)?(?P<what>\w+)", re.I),
        True,
        "lint_off {what} turns off a check of this gate: remove the comment and change the code",
    ),
    (
        re.compile(r"`verilator_config\b|^\s*lint_off\s+-", re.I),
        True,
        "a verilator_config block turns off checks of this gate: remove it and change the code",
    ),
    (
        re.compile(r"`(?:ifdef|ifndef|elsif)\s+(?P<what>VERILATOR|SYNTHESIS|YOSYS|__ICARUS__)\b"),
        False,
        "`{what}` is defined by 1 engine and by no other: each would read another design. Write 1 text "
        "for all of them",
    ),
    (
        re.compile(r"\b(?P<what>(?:translate|synthesis)_(?:off|on))\b", re.I),
        True,
        "{what} marks text that the synthesizer skips and the simulator reads: remove the comment",
    ),
    (
        re.compile(r"\b(?P<what>full_case|parallel_case)\b", re.I),
        True,
        "{what} tells the synthesizer what the simulator is not told: write the `default:` instead",
    ),
    (
        re.compile(r"(?P<what>\$readmem[bh])\b"),
        False,
        "{what} reads a file while an engine runs, and each engine looks for it in another folder: "
        "write the contents in the RTL, as a `case`",
    ),
)
# What every bench prints, and the bound each holds without an expect file.
BENCH_MEASURES = {"errors": {"max": 0}, "checks": {"min": 1}, "x_outputs": {"max": 0}}
MEASURE_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*$")
BENCH_SUFFIXES = (".v", ".sv")
# Yosys names a flop by what it has: $_DFF_P_ and $_DFFE_PP_ have a clock (and an enable) and no
# reset; $_SDFF..., $_DFF_PN0_, $_DFFSR... have one. A synchronous reset is read here, before the
# library's cells replace it with a plain flop and a gate in front of it.
NO_RESET_RE = re.compile(r"^\$_DFFE?_[NP]{1,2}_$")
FLOP_RE = re.compile(r"^\$_(S?DFF|DFFSR|ALDFF)")
LATCH_RE = re.compile(r"^\$_(DLATCH|SR_)")
YOSYS_NOTE_RE = re.compile(r"Found unsupported expression .* in pin attribute of cell")
CHECK_RE = re.compile(r"has no driver|conflicting drivers|logic loop|unmapped internal cell")
CONSTANT_RE = re.compile(r"\b\d+'[bhd][0-9a-fA-FxXzZ_]+")
LIBERTY_CELL_RE = re.compile(r'^\s*cell\s*\(\s*"?([^"\s)]+)"?\s*\)\s*\{')
QUOTED_RE = re.compile(r'"[^"]*"')
# A header that Verilog source names by a text in quotes. The engines take `include"x.vh"` with no
# space as they take it with one. A name written another way (through a macro) is not found here: each
# gate adds the files its engine says it read to its record.
NAMED_FILE_RE = re.compile(r'`include\s*"([^"\n]+)"')
# vvp's own line for a bench that ended, `<file>:<line>: $finish called at <time> (<unit>)`: a bench
# that prints the 2 words has not written this line.
FINISHED_RE = re.compile(r"^.+:\d+: \$finish called at \d+ \(\w+\)\s*$", re.M)
# The system tasks that read a file while a simulation runs. vvp opens such a file from the folder it
# runs in, which is the gate's own, and names no file it opened: no record of a pass could hold it.
READS_A_FILE = re.compile(r"\$(?:readmem[bh]?|fread|fscanf|fgets|fgetc|sdf_annotate)\b")
# The list a compile writes of the files it read, in the folder of its bench.
FILES_READ = "files.txt"
# The gates that read the project's own files, in the order they run.
INPUT_GATES = ("lint", "sim", "synth", "layout", "glsim")


def read_with(sources: list[Path], folders: list[Path]) -> list[Path]:
    """The sources and each header they name in an `include`, and each header those name, 1 time each.
    An engine looks for a header beside the file that names it or in a folder of its `-I` list, and
    which one it takes differs between the engines: every file of that name in any of those places is
    listed. A name with no file is left out: the engine's own error names it."""
    out: list[Path] = []
    seen: set[Path] = set()

    def read(path: Path) -> None:
        if path.resolve() in seen or not path.is_file():
            return
        seen.add(path.resolve())
        out.append(path)
        for name in NAMED_FILE_RE.findall(path.read_text(encoding="utf-8", errors="replace")):
            for folder in (path.parent, *folders):
                read(folder / name)

    for source in sources:
        read(Path(source))
    return out


def project_inputs(run, gate: str) -> list[Path]:
    """The project's own files that a gate reads, each whether it is there or not. A gate's record of
    a pass names the hash of each one that is there. EXPORT asks again: a file that is there now and
    not in the record came after the gate passed."""
    chip = run.chip
    own = run.project / chipflow.CHIP_FILE
    folders = [Path(flag[2:]) for flag in include_dirs(run)]
    found = benches(run)
    chosen = [b for b in found if b.stem not in chip.rtl_only]

    def expect_files(of: list[Path]) -> list[Path]:
        return [run.project / "tb" / f"{bench.stem}.expect.json" for bench in of]

    return {
        "lint": [*read_with(chip.rtl, folders), chip.constraints, own],
        "sim": [
            *read_with([*chip.rtl, *found], folders),
            *expect_files(found),
            run.project / MUTATIONS,
            own,
        ],
        "synth": [*read_with(chip.rtl, folders), own],
        "layout": [chip.constraints, own],
        "glsim": [*read_with(chosen, folders), *expect_files(chosen), own],
    }[gate]


def inputs_taken(run, gate: str, *more: Path) -> dict[str, str]:
    """{name: SHA256} of the files a gate reads, taken before its engines start: the project's own, and
    `more`, the files of the output folder that a gate before it handed on."""
    return run.judged([*project_inputs(run, gate), *more])


def inputs_moved(run, gate: str, taken: dict[str, str], *more: Path) -> list[str]:
    """A failure for each of those files that is other bytes, gone or new when the engines have ended:
    an engine read 1 of the 2, and the record of a pass names 1 hash."""
    now = inputs_taken(run, gate, *more)
    return [
        f"{name} changed while the gate ran: its hash differs"
        for name in sorted({*taken, *now})
        if taken.get(name) != now.get(name)
    ]


def not_as_passed(run, gate: str, record: dict) -> list[str]:
    """A line for each file that is not what a gate's record of its pass names: a file of the record
    that is other bytes now or gone, and a file the gate would read now that the record does not name.
    EXPORT holds the files to this before it hands a layout out, and `workcenter next` before it reads
    the report."""
    lines = run.changed_since(gate, record)
    lines += [
        f"{run.name_of(path)} was added after {gate.upper()} passed. Run the gates again"
        for path in project_inputs(run, gate)
        if path.is_file() and run.name_of(path) not in record["judged"]
    ]
    return lines


def passed(run, gate: str, result, taken: dict[str, str], *written: Path):
    """A gate's result, and on a pass the record of it: the hash of each file the gate judged. That is
    `taken`, the files it read, and `written`, the files it hands on. EXPORT asks every gate for its
    record and holds each file to it. So a layout is handed out only for the RTL, the headers, the
    benches, their bounds, the constraints and the chip.json that each gate passed on."""
    if result.status == "pass":
        run.write_passed(gate, {**taken, **run.judged(written)})
    return result


def short(text: str, run) -> str:
    """A line of an engine's output with the project's own folder taken off its paths."""
    return text.replace(f"{run.project}/", "").replace(f"{run.out}/", "")


# ------------------------------------------------------------------------ LINT


def judge_lint(text: str) -> tuple[list[str], list[str]]:
    """Verilator's output as (failures, warnings). An error fails; a warning of a class in LINT_FAIL
    fails with its class first; every other warning is a warning. The lines under a message (the
    source line, the hint) are left out."""
    failures: list[str] = []
    warnings: list[str] = []
    for line in text.splitlines():
        found = VERILATOR_RE.match(line)
        if not found:
            continue
        kind, name, rest = found.groups()
        if kind == "Error":
            if not rest.startswith("Exiting due to"):
                failures.append(rest if name is None else f"{name}: {rest}")
        elif name in LINT_FAIL:
            failures.append(f"{name}: {rest}")
        else:
            warnings.append(f"{name}: {rest}")
    return failures, warnings


def two_designs(files: list[Path], project: Path) -> list[str]:
    """A failure for each line of the RTL, and of each file it names, that makes 1 engine read another
    design than the next (`TWO_DESIGNS`). Verilator obeys such a line and prints nothing, so the gate
    reads the text itself."""
    out: list[str] = []
    root = project.resolve()
    for path in files:
        try:
            where = str(path.resolve().relative_to(root))
        except ValueError:
            where = str(path)
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            code = line.split("//", 1)[0]
            for pattern, in_comments, said in TWO_DESIGNS:
                found = pattern.search(line if in_comments else code)
                if found:
                    out.append(f"{where}:{n}: {said.format(**found.groupdict())}")
    return out


def xml_files(xml_text: str) -> list[Path]:
    """Each file Verilator says it read, from the `files` block of its XML: the RTL and every file an
    `include` of any spelling brought in. A name that is no file (`<built-in>`) is left out."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    found = [Path(node.get("filename", "")) for node in root.iter("file")]
    return list(dict.fromkeys(path for path in found if path.is_file()))


def port_widths(xml_text: str, top: str) -> dict[str, tuple[int, int]] | None:
    """The top module's buses as {name: (first index, last index)} from Verilator's XML, or None when
    it holds no such module. A port of 1 bit is not in it."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    ranges = {
        node.get("id"): (int(node.get("left")), int(node.get("right")))
        for node in root.iter("basicdtype")
        if node.get("left") is not None and node.get("right") is not None
    }
    for module in root.iter("module"):
        if module.get("topModule") == "1" or module.get("origName") == top:
            return {
                v.get("origName") or v.get("name"): ranges[v.get("dtype_id")]
                for v in module.findall("var")
                if v.get("dir") and v.get("dtype_id") in ranges
            }
    return None


def top_ports(xml_text: str, top: str) -> dict[str, str] | None:
    """The top module's ports as {name: direction} from Verilator's XML, or None when it holds none."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None
    for module in root.iter("module"):
        if module.get("topModule") == "1" or module.get("origName") == top:
            return {
                v.get("origName") or v.get("name"): v.get("dir")
                for v in module.findall("var")
                if v.get("dir")
            }
    return None


def include_dirs(run) -> list[str]:
    """`-I` for each folder that holds RTL or a bench: a file may include a header beside it."""
    folders = sorted({str(p.parent) for p in run.chip.rtl} | {str(run.project / "tb")})
    return [f"-I{folder}" for folder in folders]


def gate_lint(run):
    missing = run.need_engines("lint", "verilator")
    if missing:
        return missing
    chip = run.chip
    folder = run.begin("lint")
    if not chip.rtl:
        return run.skip(
            "lint", f"chip.json names top {chip.top} and no file matches its rtl patterns: write the RTL"
        )
    taken = inputs_taken(run, "lint")
    files = [str(p) for p in chip.rtl]
    started = run.start(
        [
            run.engine("verilator"),
            "--lint-only",
            "-Wall",
            "-Wno-fatal",
            "--top-module",
            chip.top,
            *include_dirs(run),
            *files,
        ],
        cwd=folder,
        log=folder / "verilator.log",
        timeout=chipflow.TIME_LIMITS["lint"],
    )
    failures, warnings = judge_lint(started.text)
    failures = [short(line, run) for line in failures]
    warnings = [short(line, run) for line in warnings]
    stopped = started.problem("verilator on the RTL")
    if stopped and not failures:
        # Verilator ended badly and named no error: the exit code is all there is.
        failures.append(stopped)
    folders = [Path(flag[2:]) for flag in include_dirs(run)]
    failures += two_designs(read_with(chip.rtl, folders), run.project)
    ports, widths, read = None, None, []
    if not failures:
        xml = run.start(
            [
                run.engine("verilator"),
                "--xml-only",
                "--Mdir",
                folder / "xml",
                "--top-module",
                chip.top,
                *include_dirs(run),
                *files,
            ],
            cwd=folder,
            log=folder / "ports.log",
            timeout=chipflow.TIME_LIMITS["lint"],
        )
        written = folder / "xml" / f"V{chip.top}.xml"
        said = written.read_text(encoding="utf-8", errors="replace") if written.is_file() else ""
        ports = top_ports(said, chip.top) if said else None
        if ports is None:
            failures.append(
                xml.problem("the top module's ports") or f"verilator wrote no ports for {chip.top}"
            )
        else:
            widths = port_widths(said, chip.top) or {}
            # What Verilator itself says it read. A file of the project among them that the gate did
            # not find by the text is read and goes into the record too: no spelling of an `include`
            # keeps a header out of either.
            read = [p for p in of_the_project(run, xml_files(said)) if run.name_of(p) not in taken]
            failures += two_designs(read, run.project)
    sdc = chipflow.read_sdc(chip.constraints, ports, widths)
    failures += sdc.problems
    if ports is not None and sdc.clock_port and ports.get(sdc.clock_port) != "input":
        failures.append(
            f"{chip.constraints.name}: create_clock names the port {sdc.clock_port}, and {chip.top} has no "
            "input of that name"
        )
    details = {
        "ports": ports or {},
        "clock": {"port": sdc.clock_port, "name": sdc.clock_name, "period_ns": sdc.period_ns},
    }
    failures += inputs_moved(run, "lint", taken)
    result = run.result(
        "lint",
        failures,
        warnings,
        f"{len(files)} RTL files, top {chip.top}",
        details,
        [folder / "verilator.log"],
    )
    return passed(run, "lint", result, taken, *read)


# ------------------------------------------------------------- SIM and GLSIM


def benches(run) -> list[Path]:
    """The project's benches: each file of `tb/` that is Verilog. A folder of such a name is none."""
    folder = run.project / "tb"
    if not folder.is_dir():
        return []
    return sorted(p for p in folder.iterdir() if p.suffix in BENCH_SUFFIXES and p.is_file())


def bench_measures(text: str) -> dict[str, list[float]]:
    """Every value a bench printed for each name, in order: a name printed 2 times with 2 values is
    held to its bound each time."""
    out: dict[str, list[float]] = {}
    for line in text.splitlines():
        found = MEASURE_RE.match(line)
        if found:
            values = out.setdefault(found.group(1), [])
            value = float(found.group(2))
            if value not in values:
                values.append(value)
    return out


def bound_text(bound: dict) -> str:
    return f"[{bound.get('min')}, {bound.get('max')}]"


def judge_bench(
    name: str, compiled, ran, expect: dict[str, dict]
) -> tuple[list[str], list[str], dict[str, float]]:
    """1 bench as (failures, warnings, measures). `compiled` and `ran` are the engine runs; `ran` is
    None when the bench did not compile. A bench passes when it reaches $finish, prints the 3 measures
    every bench prints, and every bound holds: the 3 the gate holds itself, and the expect file's."""
    failures: list[str] = []
    warnings = [f"{name}: {line.strip()}" for line in compiled.text.splitlines() if "warning:" in line]
    errors = [line.strip() for line in compiled.text.splitlines() if "error" in line.lower()]
    if compiled.exit != 0 or compiled.timed_out or ran is None:
        first = errors[0] if errors else (compiled.problem("iverilog") or "iverilog wrote no simulation")
        if "Unable to find the root module" in first:
            first += f": name the bench's module as its file, {name}"
        return [f"{name}: does not compile: {first}"], warnings, {}
    stopped = ran.problem(name)
    if stopped:
        return [stopped], warnings, {}
    if not FINISHED_RE.search(ran.text):
        failures.append(f"{name}: does not reach $finish: end the bench with $finish after its last check")
    printed = bench_measures(ran.text)
    measures = {key: values[-1] for key, values in printed.items()}
    for key in BENCH_MEASURES:
        if key not in printed:
            failures.append(
                f"{name}: does not print {key}: print errors, checks and x_outputs as `name = value`"
            )
    bounds = [(key, bound, "") for key, bound in BENCH_MEASURES.items()]
    bounds += [
        (key, bound, f" ({bound['source']})" if bound.get("source") else "") for key, bound in expect.items()
    ]
    for key, bound, source in bounds:
        if key not in printed:
            if key not in BENCH_MEASURES:
                failures.append(
                    f"{name}: {key} has a bound in {name}.expect.json and the bench does not print it"
                )
            continue
        for value in printed[key]:
            low, high = bound.get("min"), bound.get("max")
            if (low is not None and value < low) or (high is not None and value > high):
                line = f"{name}: {key}={value:g} not in {bound_text(bound)}{source}"
                if line not in failures:
                    failures.append(line)
    return failures, warnings, measures


def listed_files(path: Path) -> list[Path]:
    """The files Icarus Verilog says it read (`-Mall`), 1 on a line: each source, and every file an
    `include` of any spelling brought in."""
    if not path.is_file():
        return []
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return list(dict.fromkeys(Path(line) for line in lines if line.strip()))


def of_the_project(run, files) -> list[Path]:
    """Those of the files that lie in the project's folder and are not the gates' own output."""
    root, base = run.project.resolve(), run.base.resolve()
    return [
        path
        for path in files
        if root in path.resolve().parents and base not in path.resolve().parents and path.is_file()
    ]


def read_by(run, gate: str, chosen: list[Path]) -> list[Path]:
    """The project's files that the compiles of these benches read, as the engine lists them."""
    found = [p for bench in chosen for p in listed_files(run.base / gate / bench.stem / FILES_READ)]
    return of_the_project(run, dict.fromkeys(found))


def reads_a_file(files: list[Path], project: Path) -> list[str]:
    """A failure for each line that reads a file while a simulation runs (`READS_A_FILE`)."""
    out: list[str] = []
    root = project.resolve()
    for path in files:
        try:
            where = str(path.resolve().relative_to(root))
        except ValueError:
            where = str(path)
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            found = READS_A_FILE.search(line.split("//", 1)[0])
            if found:
                out.append(
                    f"{where}:{n}: {found.group(0)} reads a file while the bench runs. A bench runs in a "
                    "folder of the gate's own, and no record of a pass would hold the file. Write the "
                    "values in the text: in a header the bench includes, or as a `case` in the RTL"
                )
    return out


def read_alone(run, sources: list[Path], folder: Path) -> set[Path] | None:
    """The files the preprocessor reads for these sources and no other, each resolved: the sources and
    every file an `include` of any spelling brings in. None when the engine wrote no list."""
    folder.mkdir(parents=True, exist_ok=True)
    started = run.start(
        [
            run.engine("iverilog"),
            "-E",
            "-g2012",
            *include_dirs(run),
            f"-Mall={folder / FILES_READ}",
            "-o",
            os.devnull,
            *sources,
        ],
        cwd=folder,
        log=folder / "preprocess.log",
        timeout=chipflow.TIME_LIMITS["sim"],
    )
    listed = listed_files(folder / FILES_READ)
    return {path.resolve() for path in listed} if started.exit == 0 and listed else None


def bench_runs(run, bench: Path, sources: list, defines: list, includes: list, folder: Path, **limit):
    """Compile 1 bench with its sources and run it, in `folder`: (the compile, the run or None when the
    bench did not compile). `limit` is the time each engine may take, as `Run.start` reads it. The
    compile writes the list of the files it read beside its log (`FILES_READ`)."""
    name = bench.stem
    folder.mkdir(parents=True, exist_ok=True)
    compiled = run.start(
        [
            run.engine("iverilog"),
            "-g2012",
            "-Wall",
            "-Wno-timescale",
            *[f"-D{d}" for d in defines],
            "-s",
            name,
            *includes,
            f"-Mall={folder / FILES_READ}",
            "-o",
            folder / f"{name}.vvp",
            bench,
            *sources,
        ],
        cwd=folder,
        log=folder / "compile.log",
        **limit,
    )
    ran = None
    if compiled.exit == 0 and (folder / f"{name}.vvp").is_file():
        # -N: a $stop ends the run with exit code 1, where -n would end it like a $finish.
        ran = run.start(
            [run.engine("vvp"), "-N", folder / f"{name}.vvp"], cwd=folder, log=folder / "run.log", **limit
        )
    return compiled, ran


def run_bench(
    run, gate: str, bench: Path, sources: list[str], defines: list[str]
) -> tuple[list[str], list[str], dict, float]:
    """Compile and run 1 bench in its own folder: (failures, warnings, measures, the seconds its run
    took). `sources` is what the bench is compiled with: the RTL for SIM, the final netlist and the
    library's cell models for GLSIM."""
    name = bench.stem
    expect, problems = run.cli.read_expect(run.project / "tb" / f"{name}.expect.json", lower_case=False)
    if problems:
        return [f"{name}.expect.json: {p}" for p in problems], [], {}, 0.0
    compiled, ran = bench_runs(
        run,
        bench,
        sources,
        defines,
        include_dirs(run),
        run.base / gate / name,
        timeout=chipflow.TIME_LIMITS[gate],
    )
    failures, warnings, measures = judge_bench(name, compiled, ran, expect or {})
    failures = [short(line, run) for line in failures]
    warnings = [short(line, run) for line in warnings]
    path = run.measures(gate, name)
    path.write_text(json.dumps(measures, indent=2, sort_keys=True), encoding="utf-8")
    run.record(gate, path)
    return failures, warnings, measures, ran.seconds if ran else 0.0


def run_benches(
    run, gate: str, chosen: list[Path], sources: list[str], defines: list[str]
) -> tuple[list, list, dict, dict]:
    """Each bench in its own folder, `--jobs` at a time: (failures, warnings, {bench: measures},
    {bench: the seconds its run took})."""
    with ThreadPoolExecutor(max_workers=max(1, run.jobs)) as pool:
        results = list(pool.map(lambda b: run_bench(run, gate, b, sources, defines), chosen))
    failures = [line for f, _, _, _ in results for line in f]
    warnings = [line for _, w, _, _ in results for line in w]
    measures = {b.stem: m for b, (_, _, m, _) in zip(chosen, results, strict=True)}
    return failures, warnings, measures, {b.stem: s for b, (_, _, _, s) in zip(chosen, results, strict=True)}


MUTATIONS = "rtl/mutations.json"
# A changed copy of the RTL may run each bench 10 times as long as the RTL itself did, and 20 s at
# least: a change that makes a bench wait for ever is caught by the wait, not by the gate's own limit.
MUTANT_TIMES, MUTANT_SECONDS = 10, 20


def run_mutations(run, found: list[Path], seconds: dict[str, float]) -> tuple[list[str], list[str], dict]:
    """The project's list of changes to the RTL, each made in a copy of the sources and judged by the
    benches: (failures, warnings, {name: {"state", "by"}}). A bench that passes on every wrong design
    proves nothing about the right one, so each change must fail at least 1 bench: `by` is the line
    of the first bench that failed. A change that does not compile shows nothing, and is a failure of
    the list. The benches passed on the RTL as it is before this runs."""
    path = run.project / MUTATIONS
    if not path.is_file():
        return (
            [],
            [
                f"no {MUTATIONS}: nothing shows that the benches can fail. List 1 change of the RTL for "
                "each thing a bench must catch"
            ],
            {},
        )
    try:
        listed, _ = run.cli.read_mutations(path)
    except (OSError, ValueError, SyntaxError) as exc:
        return [f"{MUTATIONS}: {exc}"], [], {}
    if not listed:
        return [], [f"{MUTATIONS} lists no change: nothing shows that the benches can fail"], {}
    folders = sorted({p.parent.resolve() for p in run.chip.rtl} | {(run.project / "tb").resolve()})
    # Which text is the RTL's and which a bench's, from the engine: it reads each alone.
    reads = run.base / "sim" / "reads"
    of_rtl = read_alone(run, run.chip.rtl, reads / "rtl")
    of_bench = {bench: read_alone(run, [bench], reads / bench.stem) for bench in found}
    if of_rtl is None or None in of_bench.values():
        where = short(str(reads), run)
        return [f"iverilog wrote no list of the files it read: {where} holds its logs"], [], {}
    failures = []
    for change in listed:
        target = (run.project / change["file"]).resolve()
        count = target.read_bytes().count(change["old"].encode()) if target.is_file() else -1
        also = [bench for bench in found if target in of_bench[bench]]
        if target not in of_rtl:
            failures.append(
                f"{MUTATIONS}: {change['name']}: {change['file']} is no file the RTL is read from: a "
                "change is made in the RTL, and the benches stay as they are"
            )
        elif also:
            failures.append(
                f"{MUTATIONS}: {change['name']}: the bench {run.name_of(also[0])} reads {change['file']} "
                "too: the change would change the bench with the RTL. Make it in a file the RTL alone reads"
            )
        elif count != 1:
            failures.append(
                f"{MUTATIONS}: {change['name']}: {change['file']} holds the old text {count} times: it "
                "must name 1 place"
            )
    if failures:
        return failures, [], {}
    root, out = run.project.resolve(), run.out.resolve()
    # A file of another folder that a compile read, by a path from the file that names it.
    others = [p.resolve() for p in read_by(run, "sim", found) if p.resolve().parent not in folders]

    def not_the_output(folder: str, names: list[str]) -> list[str]:
        """A source folder is copied without the folder the gates write into."""
        return [name for name in names if (Path(folder) / name).resolve() == out]

    def one(item: tuple[int, dict]) -> tuple[str, str]:
        """(state, the line that says why): `caught` by a bench's failure, `survived`, or `no build`."""
        index, change = item
        folder = run.base / "sim" / "mutants" / f"{index:03d}"
        copies = {source: folder / "src" / source.relative_to(root) for source in folders}
        for source, copy in copies.items():
            shutil.copytree(source, copy, ignore=not_the_output, dirs_exist_ok=True)
        for source in others:
            copy = folder / "src" / source.relative_to(root)
            copy.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, copy)
        changed = folder / "src" / (run.project / change["file"]).resolve().relative_to(root)
        changed.write_bytes(changed.read_bytes().replace(change["old"].encode(), change["new"].encode(), 1))
        sources = [folder / "src" / p.resolve().relative_to(root) for p in run.chip.rtl]
        includes = [f"-I{copy}" for copy in copies.values()]
        for bench in found:
            name = bench.stem
            expect, _ = run.cli.read_expect(run.project / "tb" / f"{name}.expect.json", lower_case=False)
            compiled, ran = bench_runs(
                run,
                folder / "src" / bench.resolve().relative_to(root),
                sources,
                [],
                includes,
                folder / name,
                at_most=max(MUTANT_SECONDS, math.ceil(MUTANT_TIMES * seconds.get(name, 0.0))),
            )
            said, _, _ = judge_bench(name, compiled, ran, expect or {})
            if ran is None:
                return "no build", short(said[0], run)
            if said:
                return "caught", short(said[0], run)
        return "survived", ""

    with ThreadPoolExecutor(max_workers=max(1, run.jobs)) as pool:
        states = list(pool.map(one, enumerate(listed, 1)))
    for change, (state, line) in zip(listed, states, strict=True):
        if state == "survived":
            failures.append(
                f"the benches pass with the change {change['name']} in {change['file']}: add the check that "
                "fails on it"
            )
        elif state == "no build":
            failures.append(
                f"{MUTATIONS}: the change {change['name']} does not compile, so it shows nothing: {line}"
            )
    return (
        failures,
        [],
        {
            change["name"]: {"state": state, "by": line}
            for change, (state, line) in zip(listed, states, strict=True)
        },
    )


def gate_sim(run):
    missing = run.need_engines("sim", "iverilog", "vvp")
    if missing:
        return missing
    found = benches(run)
    if not found:
        return run.skip("sim", "tb/ holds no bench: write a bench that prints errors, checks and x_outputs")
    if not run.chip.rtl:
        return run.skip("sim", "no file matches chip.json's rtl patterns: write the RTL")
    run.begin("sim")
    taken = inputs_taken(run, "sim")
    folders = [Path(flag[2:]) for flag in include_dirs(run)]
    failures = reads_a_file(read_with([*run.chip.rtl, *found], folders), run.project)
    if failures:
        return run.result("sim", failures, [], f"{len(found)} benches, none run")
    sources = [str(p) for p in run.chip.rtl]
    failures, warnings, measures, seconds = run_benches(run, "sim", found, sources, [])
    # What the compiles themselves say they read. A file of the project among them that the gate did
    # not find by the text is read and goes into the record too.
    read = [p for p in read_by(run, "sim", found) if run.name_of(p) not in taken]
    failures += reads_a_file(read, run.project)
    for name in run.chip.rtl_only:
        if name not in measures:
            failures.append(f"chip.json: benches.{name}: tb/ holds no bench of that name")
    checks = sum(int(m.get("checks", 0)) for m in measures.values())
    summary = f"{len(found)} benches, {checks} checks"
    details: dict = {"benches": measures}
    if not failures:
        # The benches pass on the RTL as it is. Now each listed change of the RTL must fail 1 of them.
        failed, warned, states = run_mutations(run, found, seconds)
        failures += failed
        warnings += warned
        if states:
            details["mutations"] = states
            caught = sum(entry["state"] == "caught" for entry in states.values())
            summary += f", {caught} of {len(states)} changes of the RTL caught"
    failures += inputs_moved(run, "sim", taken)
    result = run.result("sim", failures, warnings, summary, details)
    return passed(run, "sim", result, taken, *read)


OPEN_PORT = re.compile(r"dangling input port \d+ \((\w+)\) floating")


def netlist_warnings(warnings: list[str], kit: str, supply: set[str]) -> list[str]:
    """The warnings of a run on the netlist that are the project's to answer.

    A warning inside the library's own cell models is not. Nor is the simulator's note on an open
    supply port of the top module: the layout build gives the netlist its supply ports, a bench drives
    the logic ports only, and the cells' models read no supply. An open logic port stays a warning.
    """
    kept = []
    for warning in warnings:
        port = OPEN_PORT.search(warning)
        if kit in warning or (port and port.group(1) in supply):
            continue
        kept.append(warning)
    return kept


def netlist_only(files: list[Path], defines: list[str], project: Path) -> list[str]:
    """A failure for each line of a bench, or of a header it includes, that asks whether a name is
    defined which the gate defines for the run on the netlist alone (the table's `defines`): the bench
    would be 1 text in SIM and another in GLSIM, and the 2 gates would not judge the same checks."""
    names = "|".join(re.escape(define.split("=", 1)[0]) for define in defines)
    if not names:
        return []
    asked = re.compile(rf"`(?:ifdef|ifndef|elsif)\s+(?P<what>{names})\b")
    out: list[str] = []
    root = project.resolve()
    for path in files:
        where = str(path.resolve().relative_to(root))
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            found = asked.search(line.split("//", 1)[0])
            if found:
                out.append(
                    f"{where}:{n}: `{found.group('what')}` is defined for the run on the netlist and not for "
                    "the run on the RTL: the bench would be another text in each. Write 1 text for both"
                )
    return out


def gate_glsim(run):
    missing = run.need_pdk("glsim") or run.need_engines("glsim", "iverilog", "vvp")
    if missing:
        return missing
    netlist, problem = run.take(run.final_netlist())
    if problem:
        if not netlist.is_file():
            return run.skip("glsim", problem)
        return run.result("glsim", [problem], [], "the final netlist")
    found = benches(run)
    chosen = [b for b in found if b.stem not in run.chip.rtl_only]
    if not chosen:
        said = (
            "tb/ holds no bench"
            if not found
            else "every bench is marked rtl_only, so none runs on the netlist"
        )
        return run.skip("glsim", f"{said}: a bench that reads only the top module's ports runs on both")
    before: dict[str, dict] = {}
    for bench in chosen:
        path, problem = run.take(run.measures("sim", bench.stem))
        if problem:
            return run.skip("glsim", f"{problem}: SIM runs first")
        before[bench.stem] = json.loads(path.read_text(encoding="utf-8"))
    models = run.pdk.library["verilog"]
    sources = [str(netlist), *[str(run.pdk.file(f)) for f in models["files"]]]
    run.begin("glsim")
    taken = inputs_taken(run, "glsim", netlist)
    failures, warnings, measures, _ = run_benches(run, "glsim", chosen, sources, list(models["defines"]))
    compiled_from = read_by(run, "glsim", chosen)
    read = [p for p in compiled_from if run.name_of(p) not in taken]
    failures += netlist_only(compiled_from, list(models["defines"]), run.project)
    supply = {run.pdk.library["supply"][side]["net"] for side in ("power", "ground")}
    warnings = netlist_warnings(warnings, str(run.pdk.root), supply)
    for name, after in measures.items():
        if "checks" in after and after["checks"] != before[name].get("checks"):
            failures.append(
                f"{name}: checks={after['checks']:g} on the netlist and {before[name].get('checks'):g} on "
                "the RTL: the bench took another path"
            )
    details = {"benches": measures, "rtl_only": dict(run.chip.rtl_only), "netlist": str(netlist)}
    skipped = f", {len(run.chip.rtl_only)} on the RTL only" if run.chip.rtl_only else ""
    failures += inputs_moved(run, "glsim", taken, netlist)
    result = run.result(
        "glsim", failures, warnings, f"{len(chosen)} benches on the final netlist{skipped}", details
    )
    return passed(run, "glsim", result, taken, *read)


# ----------------------------------------------------------------------- SYNTH


def problems_of(check_text: str) -> tuple[int | None, list[str]]:
    """What Yosys's `check` found: (the count it reports, its problems). A problem is a warning line
    with the indented lines under it, which name the cells of a loop or the drivers of a net. Problems
    that differ only in a cell's name are 1 line with their count."""
    found = re.search(r"Found and reported (\d+) problems?\.", check_text)
    problems: list[str] = []
    lines = check_text.splitlines()
    for i, line in enumerate(lines):
        if not line.startswith("Warning: "):
            continue
        said = line[len("Warning: ") :].strip()
        under = []
        for more in lines[i + 1 : i + 4]:
            if not more.startswith("    "):
                break
            under.append(more.strip())
        problems.append(said + (" " + "; ".join(under) if under else ""))
    grouped: dict[str, list[str]] = {}
    for said in problems:
        grouped.setdefault(re.sub(r"^Cell \S+ ", "Cell <name> ", said), []).append(said)
    out = [
        group[0] + (f" (and {len(group) - 1} more like it)" if len(group) > 1 else "")
        for group in grouped.values()
    ]
    return (int(found.group(1)) if found else None), out


def names(pattern: str, bit: str) -> bool:
    """Whether an answer's pattern names a register bit. `*` stands for any text and `?` for 1 character;
    every other character is itself, so `q[*]` and `core.pc[3]` read as they look. A pattern with no
    index names every bit of the register: `q` names `q[0]` to `q[7]`."""
    regex = "".join(".*" if ch == "*" else "." if ch == "?" else re.escape(ch) for ch in pattern)
    return bool(re.fullmatch(regex, bit) or re.fullmatch(regex, re.sub(r"\[\d+\]\Z", "", bit)))


def register_cells(generic: dict, top: str) -> list[tuple[str, str, str]]:
    """(cell name, cell type, register bit) for each flop and latch of the design before the library's
    cells replace them. A bit is named by the net its Q drives: `q[3]`, `core.pc[0]`."""
    module = generic.get("modules", {}).get(top, {})
    names: dict[int, str] = {}
    for name, net in module.get("netnames", {}).items():
        if net.get("hide_name"):
            continue
        bits = net.get("bits", [])
        for i, bit in enumerate(bits):
            names.setdefault(bit, f"{name}[{i}]" if len(bits) > 1 else name)
    out = []
    for cell_name, cell in module.get("cells", {}).items():
        kind = cell.get("type", "")
        if FLOP_RE.match(kind) or LATCH_RE.match(kind):
            bit = (cell.get("connections", {}).get("Q") or [None])[0]
            out.append((cell_name, kind, names.get(bit, cell_name)))
    return out


def register_names(generic: dict, top: str) -> dict[str, list[str]]:
    """{cell type: the register bits it holds} for each flop and latch of the design before the
    library's cells replace them."""
    out: dict[str, list[str]] = {}
    for _, kind, bit in register_cells(generic, top):
        out.setdefault(kind, []).append(bit)
    return {kind: sorted(bits) for kind, bits in out.items()}


def judge_synth(
    console: str,
    check_generic: str,
    check_mapped: str,
    stat: dict | None,
    generic: dict | None,
    mapped: dict | None,
    netlist: str | None,
    top: str,
    cells: dict,
    answers: list[dict],
) -> tuple[list[str], list[str], dict]:
    """Yosys's reports as (failures, warnings, details). The design maps onto the library when Yosys
    names no error, `check` finds 0 problems before and after the mapping, no internal cell and no
    latch is left, every flop has a reset or an answer in chip.json, and no input is tied to a
    constant without a tie cell. `generic` is the design before the library's cells and `mapped` the
    netlist that is handed on: the flops counted are the netlist's, and a flop of `generic` that the
    netlist does not hold is named as removed by the mapping."""
    failures = [line.strip() for line in console.splitlines() if line.startswith("ERROR:")]
    said = [
        line[len("Warning: ") :].strip()
        for line in dict.fromkeys(console.splitlines())
        if line.startswith("Warning: ") and not YOSYS_NOTE_RE.search(line)
    ]
    found: list[str] = []
    for stage, text in (("before the library's cells", check_generic), ("after them", check_mapped)):
        count, lines = problems_of(text)
        if count is None:
            failures.append(f"check wrote no count {stage}: Yosys stopped before it")
        for line in lines:
            if line not in found:
                found.append(line)
    # `synth` runs a check of its own before its last passes give an open net an unknown constant: a
    # problem it names there is a problem, though the 2 checks after it no longer see the net.
    for line in said:
        known = re.sub(r"^Cell \S+ ", "Cell <name> ", line)
        if CHECK_RE.search(line) and not any(
            known in re.sub(r"^Cell \S+ ", "Cell <name> ", f) for f in found
        ):
            found.append(line)
    failures += [f"check: {line}" for line in found]
    warnings = [w for w in said if not CHECK_RE.search(w)]
    details: dict = {}
    if stat is None or generic is None or mapped is None or netlist is None:
        if not failures:
            failures.append("Yosys wrote no netlist: its log says where it stopped")
        return failures, warnings, details
    design = stat.get("modules", {}).get(f"\\{top}") or stat.get("design") or {}
    counts = design.get("num_cells_by_type", {})
    internal = sorted(kind for kind in counts if kind.startswith("$"))
    if internal:
        failures.append(
            f"{sum(counts[k] for k in internal)} cells are not of the library: {', '.join(internal)}"
        )
    prefix = cells["prefix"]

    def family(kind: str) -> str:
        return re.sub(r"_\d+$", "", kind.removeprefix(prefix))

    registers = register_names(generic, top)
    latches = sorted(bit for kind, bits in registers.items() if LATCH_RE.match(kind) for bit in bits)
    library_latches = sorted(kind for kind in counts if family(kind) in cells["latch"])
    if latches or library_latches:
        said = (
            ", ".join(latches[:6]) + (" ..." if len(latches) > 6 else "")
            if latches
            else ", ".join(library_latches)
        )
        failures.append(
            f"{len(latches) or len(library_latches)} latch bits: {said}: assign the signal in every branch"
        )
    gates = sorted(kind for kind in counts if family(kind) in cells["clock_gate"])
    if gates:
        failures.append(f"a clock gate cell ({', '.join(gates)}): the first flow takes 1 clock, not gated")
    bare = sorted(bit for kind, bits in registers.items() if NO_RESET_RE.match(kind) for bit in bits)
    answered = [bit for bit in bare if any(names(a["match"], bit) for a in answers)]
    open_bits = [bit for bit in bare if bit not in answered]
    if open_bits:
        failures.append(
            f"{len(open_bits)} flops have no reset: {', '.join(open_bits[:6])}"
            f"{' ...' if len(open_bits) > 6 else ''}: reset each, or name it in chip.json's "
            "answers.flops_without_reset with why and the bench that proves it"
        )
    unused = [a["match"] for a in answers if not any(names(a["match"], bit) for bit in bare)]
    for match in unused:
        failures.append(
            f"chip.json: answers.flops_without_reset: {match!r} matches no flop without a reset: remove it"
        )
    body = re.sub(r"//[^\n]*", "", netlist)
    constants = sorted(set(CONSTANT_RE.findall(body)))
    if constants:
        failures.append(
            f"the netlist ties inputs to {', '.join(constants)} with no tie cell: a net there has no driver, "
            "or holds an unknown value"
        )
    # The flops counted are the netlist's. The mapping proves more than `synth` does, and the script's
    # last pass then removes a flop that nothing reads: the netlist can hold fewer flops than the design
    # had before the mapping. A flop keeps its cell's name through the mapping, so each one removed is
    # named by its register bit. A flop that `synth` itself removed is in neither file and is not named.
    flop_kinds = {*cells["flop_with_reset"], *cells["flop_without_reset"]}
    built = (mapped.get("modules", {}).get(top) or {}).get("cells", {})
    before = [(name, bit) for name, kind, bit in register_cells(generic, top) if FLOP_RE.match(kind)]
    details = {
        "cells": sum(counts.values()),
        "cells_by_type": dict(sorted(counts.items())),
        "flops": sum(n for kind, n in counts.items() if family(kind) in flop_kinds),
        "flops_before_mapping": len(before),
        "flops_removed_by_mapping": sorted(bit for name, bit in before if name not in built),
        "flops_without_reset": bare,
        "area_um2": (stat.get("design") or {}).get("area", design.get("area")),
    }
    return failures, warnings, details


def synth_liberty(run) -> Path:
    """The liberty file the mapping reads: the typical corner the project's ranges select, else the
    first corner they select, else the table's first typical corner."""
    for wanted in ("typical", None):
        for corner in run.corners:
            if wanted is None or corner.process == wanted:
                return corner.liberty
    corners = run.pdk.library["corners"]
    typical = sorted(name for name, c in corners.items() if c["process"] == "typical") or sorted(corners)
    return run.pdk.file(corners[typical[0]]["liberty"])


def dont_use_files(run, *kinds: str) -> list[str]:
    """The files of the kit that list the cells not to use for these kinds, as the table names them."""
    listed = run.pdk.library["cells"]["dont_use"]
    return list(dict.fromkeys(name for kind in kinds for name in listed[kind]))


def dont_use(run, *kinds: str) -> list[str]:
    """The cells the kit's own lists keep out, each once, in the lists' order. `synthesis` is what the
    mapping may not choose; `layout` is what no step may place: neither the mapping nor the layout
    build. A list is a file of the kit with 1 cell name on a line."""
    names: list[str] = []
    for relative in dont_use_files(run, *kinds):
        for line in run.pdk.file(relative).read_text(encoding="utf-8", errors="replace").splitlines():
            name = line.split("#")[0].strip()
            if name and name not in names:
                names.append(name)
    return names


def liberty_without(text: str, cells: set[str]) -> tuple[str, list[str]]:
    """A liberty file's text without the group of each named cell, and the names of the groups left
    out. A cell is a group `cell (name) { ... }` that starts a line; it ends at the brace that closes
    its first one, counted outside quoted text. Yosys 0.33 has no flag that keeps a cell out of the
    mapping, so the mapping reads a file that does not offer it."""
    kept: list[str] = []
    left: list[str] = []
    depth = 0
    for line in text.splitlines(keepends=True):
        if depth == 0:
            found = LIBERTY_CELL_RE.match(line)
            if not found or found.group(1) not in cells:
                kept.append(line)
                continue
            left.append(found.group(1))
        bare = QUOTED_RE.sub("", line)
        depth += bare.count("{") - bare.count("}")
    return "".join(kept), left


def gate_synth(run):
    missing = run.need_pdk("synth") or run.need_engines("synth", "yosys")
    if missing:
        return missing
    chip = run.chip
    if not chip.rtl:
        return run.skip("synth", "no file matches chip.json's rtl patterns: write the RTL")
    folder = run.begin("synth")
    taken = inputs_taken(run, "synth")
    cells = run.pdk.library["cells"]
    liberty = synth_liberty(run)
    # A liberty file and a list of cells are engines too: without one the gate did not run.
    lists = dont_use_files(run, *chipflow.DONT_USE)
    needed = (str(liberty.relative_to(run.pdk.root)), *lists)
    absent = [name for name in needed if not run.pdk.file(name).is_file()]
    if absent:
        return run.skip("synth", f"the process kit {run.pdk.name} has no {', '.join(absent)}", engine=True)
    kept_out = dont_use(run, *chipflow.DONT_USE)
    mapping = folder / "mapping.lib"
    offered, left_out = liberty_without(liberty.read_text(encoding="utf-8", errors="replace"), set(kept_out))
    mapping.write_text(offered, encoding="utf-8")
    values = {
        "LIBERTY": str(liberty),
        "MAPPING": str(mapping),
        "RTL": " ".join(f'"{p}"' for p in chip.rtl),
        "INCLUDES": " ".join(f'-I"{p.parent}"' for p in chip.rtl),
        "TOP": chip.top,
        "OUT": str(folder),
        "TIE_HIGH": f"{cells['tie_high']['cell']} {cells['tie_high']['pin']}",
        "TIE_LOW": f"{cells['tie_low']['cell']} {cells['tie_low']['pin']}",
    }
    script = (SCRIPTS / "synth.ys").read_text(encoding="utf-8")
    for key, value in values.items():
        script = script.replace(f"@{key}@", value)
    (folder / "synth.ys").write_text(script, encoding="utf-8")
    # -E: Yosys writes the files it read, as a Makefile rule: `<what it wrote>: <each file it read>`.
    reads = folder / "reads.d"
    started = run.start(
        [run.engine("yosys"), "-q", "-T", "-E", reads, "-l", folder / "yosys.log", "-s", folder / "synth.ys"],
        cwd=folder,
        log=folder / "console.log",
        timeout=chipflow.TIME_LIMITS["synth"],
    )
    listed = reads.read_text(encoding="utf-8", errors="replace") if reads.is_file() else ""
    # A file of the project among them that the gate did not find by the text goes into the record.
    read = [
        path
        for path in of_the_project(run, dict.fromkeys(map(Path, listed.partition(":")[2].split())))
        if run.name_of(path) not in taken
    ]

    def text_of(name: str) -> str:
        path = folder / name
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""

    def json_of(name: str) -> dict | None:
        try:
            return json.loads(text_of(name)) if text_of(name) else None
        except ValueError:
            return None

    written = folder / f"{chip.top}.v"
    failures, warnings, details = judge_synth(
        started.text,
        text_of("check_generic.txt"),
        text_of("check.txt"),
        json_of("stat.json"),
        json_of("generic.json"),
        json_of("mapped.json"),
        written.read_text(encoding="utf-8", errors="replace") if written.is_file() else None,
        chip.top,
        cells,
        chip.flops_without_reset,
    )
    stopped = started.problem("yosys")
    if stopped and not any(line.startswith("ERROR:") for line in failures):
        failures.insert(0, stopped)
    # The mapping was offered none of them: one in the netlist is a cell the RTL names itself.
    named = sorted(kind for kind in details.get("cells_by_type", {}) if kind in set(kept_out))
    if named:
        failures.append(
            f"the netlist holds {', '.join(named[:4])}{' ...' if len(named) > 4 else ''}: the process kit "
            f"lists {'it' if len(named) == 1 else 'them'} as not to use ({', '.join(lists)}). Name another "
            "cell in the RTL, or none"
        )
    failures = [short(line, run) for line in failures] + inputs_moved(run, "synth", taken)
    warnings = [short(line, run) for line in warnings]
    details["liberty"] = str(liberty)
    details["cells_not_offered"] = len(left_out)
    if written.is_file():
        details["sha256"] = run.record("synth", written)
    summary = f"{details.get('cells', 0)} cells, {details.get('flops', 0)} flops"
    if details.get("area_um2") is not None:
        summary += f", {details['area_um2']:.1f} um2"
    removed = details.get("flops_removed_by_mapping") or []
    if removed:
        summary += f", the mapping removed {len(removed)} flops that nothing reads (--json names each)"
    result = run.result("synth", failures, warnings, summary, details, [written, folder / "yosys.log"])
    return passed(run, "synth", result, taken, written, *read)
