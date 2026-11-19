"""`workcenter bench`: route design files with each router named and record, for each run, the time,
the share of connections joined, the DRC's count, the commands a model gives and the size of the
output it reads; then name the router each board takes (ROADMAP item 5).

A run is `workcenter design <file> --route` into its own folder, then `workcenter drc` on what it
wrote, both as a model would type them. The share joined is counted on the routed board: each net's
pads less 1 are the connections it asks for, and each of the DRC's unconnected items is 1 not made.
Standard library only, as the CLI is; the engines run in the commands it starts.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import kicadgen
import routers

RUN_FILE = "run.json"
TABLE_FILE = "bench.md"
HEADER = (
    "| Board | Router | Time (s) | Joined | DRC errors | Commands | Output read (bytes) | Run |\n"
    "|---|---|---|---|---|---|---|---|"
)


def board_connections(pcb: Path) -> int:
    """The connections a board asks for: for each net, the pads that carry it less 1. A pad with no
    net, the empty net or KiCad's `unconnected-(...)` net of an open pin asks for none."""
    root = kicadgen.parse(Path(pcb).read_text(encoding="utf-8"))
    pads: dict[str, int] = {}
    for fp in kicadgen.children(root, "footprint"):
        for pad in kicadgen.children(fp, "pad"):
            net = kicadgen.child(pad, "net")
            values = kicadgen.atoms(net) if net is not None else []
            name = str(values[-1]) if values else ""
            if name and not name.startswith("unconnected-("):
                pads[name] = pads.get(name, 0) + 1
    return sum(n - 1 for n in pads.values())


def drc_counts(report: Path) -> dict[str, int]:
    """Errors and warnings of a kicad-cli DRC report, as `workcenter drc` counts them, and its
    unconnected items."""
    data = json.loads(Path(report).read_text(encoding="utf-8"))
    items = [i for k in ("violations", "unconnected_items", "schematic_parity") for i in data.get(k, [])]
    return {
        "errors": sum(1 for i in items if i.get("severity") == "error"),
        "warnings": sum(1 for i in items if i.get("severity") == "warning"),
        "unconnected": len(data.get("unconnected_items", [])),
    }


def routed(run: dict) -> tuple[int, int]:
    """(connections joined, connections asked for) of a judged run."""
    return run["connections"] - run["unconnected"], run["connections"]


def share_text(run: dict) -> str:
    done, total = routed(run)
    pct = 100.0 * done / total if total else 100.0
    return f"{done}/{total} ({pct:.1f} %)"


def share(run: dict) -> float:
    done, total = routed(run)
    return done / total if total else 1.0


def choose(runs: list[dict], default: str) -> dict[str, tuple[str, str]]:
    """The router each board takes and why. Another router takes a board from the workcenter's own
    only when it joins at least as large a share, with no more DRC errors, in no more time, and is
    better in 1 of the 3: a router that is slower or leaves more unrouted does not become the default."""
    boards: dict[str, list[dict]] = {}
    for run in runs:
        boards.setdefault(run["board"], []).append(run)
    out = {}
    for board, rows in boards.items():
        done = [r for r in rows if r.get("status") == "judged"]
        if not done:
            out[board] = (default, "no run finished: the workcenter's router stays")
            continue
        base = next((r for r in done if r["router"] == default), None)

        def key(r: dict) -> tuple:
            return (-share(r), r["drc_errors"], r["seconds"])

        if base is None:
            # A router of unknown quality is not held against nothing (the scope guard compares with
            # the default's numbers): the comparison is not judged and the default stays.
            out[board] = (
                default,
                f"not judged: {default} did not finish, so no router is held against it; {default} stays",
            )
            continue
        better = [
            r
            for r in done
            if r is not base
            and share(r) >= share(base)
            and r["drc_errors"] <= base["drc_errors"]
            and r["seconds"] <= base["seconds"]
            and key(r) != key(base)
        ]
        if better:
            best = min(better, key=key)
            out[board] = (
                best["router"],
                f"joins {share_text(best)} with {best['drc_errors']} DRC errors in {best['seconds']:.1f} s; "
                f"{default} {share_text(base)}, {base['drc_errors']} in {base['seconds']:.1f} s",
            )
        elif len(done) == 1:
            out[board] = (default, "the only router run on this board")
        else:
            out[board] = (
                default,
                "no other router joined as many connections with as few DRC errors in as little time",
            )
    return out


def table_row(run: dict) -> str:
    if run.get("status") == "judged":
        cells = [
            share_text(run),
            str(run["drc_errors"]),
            str(len(run["commands"])),
            str(run["output_bytes"]),
            "judged",
        ]
    else:
        status = run.get("status", "?")
        cells = ["not judged", "not judged", "-", "-", f"{status}: {run.get('why', '')}".rstrip(": ")]
    seconds = run.get("seconds")
    time_cell = f"{seconds:.1f}" if is_number(seconds) else "-"
    return f"| {run['board']} | {run['router']} | {time_cell} | " + " | ".join(cells) + " |"


def is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# What a run file must hold to be read, and what a judged run must hold to be judged on.
RUN_KEYS = ("board", "router", "status")
JUDGED_NUMBERS = ("seconds", "connections", "unconnected", "drc_errors", "output_bytes")


def run_problem(run: object) -> str:
    """Why a run file's content cannot be used, or "" when it can."""
    if not isinstance(run, dict):
        return "not a JSON object"
    for key in RUN_KEYS:
        if key not in run:
            return f"no key {key!r}"
        if not isinstance(run[key], str):
            return f"{key!r} is not text"
    if run["status"] != "judged":
        return ""
    for key in (*JUDGED_NUMBERS, "commands"):
        if key not in run:
            return f"no key {key!r}"
    for key in JUDGED_NUMBERS:
        if not is_number(run[key]):
            return f"{key!r} is not a number"
    if not isinstance(run["commands"], list):
        return "'commands' is not a list"
    return ""


def read_runs(out: Path) -> tuple[list[dict], list[tuple[Path, str]]]:
    """Every run file in the folder, and (path, reason) for each that cannot be used. An unusable
    file is a run too, not judged, named by its folders: the table keeps a row for it."""
    runs, problems = [], []
    for path in sorted(out.glob(f"*/*/{RUN_FILE}")):
        try:
            run = json.loads(path.read_text(encoding="utf-8"))
            why = run_problem(run)
        except json.JSONDecodeError as exc:
            why = f"not JSON at line {exc.lineno} column {exc.colno}: {exc.msg}"
        except (OSError, UnicodeDecodeError) as exc:
            why = f"cannot be read: {exc}"
        if why:
            problems.append((path, why))
            run = {"board": path.parent.parent.name, "router": path.parent.name, "status": "unreadable"}
            run["why"] = why
        runs.append(run)
    return runs, problems


def write_table(out: Path, runs: list[dict], default: str) -> Path:
    lines = [HEADER, *(table_row(r) for r in sorted(runs, key=lambda r: (r["board"], r["router"])))]
    picks = choose(runs, default)
    lines += ["", "Router per board:", ""]
    lines += [f"- {board}: {router}, {why}" for board, (router, why) in sorted(picks.items())]
    path = out / TABLE_FILE
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def jar_name(jar: Path) -> str:
    """A FreeRouting jar's name as its file gives it: `freerouting.jar` is a link to the versioned file."""
    return jar.resolve().stem


def jar_version(jar: Path) -> str:
    """The jar's own word on its build, for the record: its manifest's Build-Revision."""
    try:
        with zipfile.ZipFile(jar) as z:
            text = z.read("META-INF/MANIFEST.MF").decode("utf-8", "replace")
    except (OSError, KeyError, zipfile.BadZipFile):
        return ""
    for line in text.splitlines():
        if line.startswith("Build-Revision:"):
            return line.split(":", 1)[1].strip()
    return ""


VERSION_RE = re.compile(r"v\d+(\.\d+)*")


def label_of(design: Path) -> str:
    """A board's name in the table: its design file's folders from the one above the last version
    folder (`v0.4`), which names the example or project: `ring-mouse/v0.4/cell`. With no version
    folder, the design file's folder and the one above it."""
    parts = design.resolve().parent.parts
    versions = [i for i, name in enumerate(parts) if i > 1 and VERSION_RE.fullmatch(name)]
    return "/".join(parts[versions[-1] - 1 :] if versions else parts[-2:])


def folder_of(out: Path, design: Path, router: str) -> Path:
    """A run's folder: <out>/<label with / as ->/<router>."""
    return out / label_of(design).replace("/", "-") / router


def timed_run(cmd: list[str], env: dict, limit: float) -> tuple[int | None, bytes, float]:
    """Run a command in its own process group; at `limit` seconds the whole group is stopped.
    Returns (exit code or None when stopped, stdout, seconds)."""
    t0 = time.monotonic()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, start_new_session=True
    )
    try:
        out, _ = proc.communicate(timeout=limit)
        return proc.returncode, out, time.monotonic() - t0
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        return None, out, time.monotonic() - t0


def bench_one(
    design: Path,
    router: str,
    jar: Path,
    out: Path,
    args,
    cli,
    order: bool = False,
    engine: str = "freerouting",
) -> dict:
    """1 run: `engine` is the router of routers.ROUTERS that `design --route --router` runs; for
    FreeRouting 1.9.0 (`freerouting`) `jar` is the jar it runs, for another router its own jar."""
    board = label_of(design)
    router = f"{router}+order" if order else router
    folder = folder_of(out, design, router)
    # Nothing an earlier run left is read as this run's: the board, the DRC report, the logs.
    shutil.rmtree(folder, ignore_errors=True)
    folder.mkdir(parents=True)
    run = {
        "board": board,
        "router": router,
        "jar": str(jar),
        "build": jar_version(jar) if jar.is_file() else "",
        "design": str(design),
        "limit": args.time_limit,
        "threads": args.threads,
        "passes": args.passes,
        "seconds": 0.0,
    }
    if engine == "freerouting" and not jar.is_file():
        run.update(status="not run", why=f"no router at {jar}")
        return run
    absent = routers.get(engine).absent() if engine != "freerouting" else ""
    if absent:
        run.update(status="not run", why=absent)
        return run
    wc = [sys.executable, str(Path(cli.__file__).resolve())]
    route = [
        "design",
        str(design),
        "--route",
        "--out",
        str(folder / "board"),
        "--passes",
        str(args.passes),
        "--timeout",
        str(args.time_limit),
        "--threads",
        str(args.threads),
        *(["--order"] if order else []),
        *(["--router", engine] if engine != "freerouting" else []),
    ]
    env = dict(os.environ, FREEROUTING_JAR=str(jar)) if engine == "freerouting" else dict(os.environ)
    # The JVM sizes its own pools by the processors it sees: held to the threads asked for.
    env["JAVA_TOOL_OPTIONS"] = (
        env.get("JAVA_TOOL_OPTIONS", "") + f" -XX:ActiveProcessorCount={args.threads}"
    ).strip()
    code, text, seconds = timed_run([*wc, *route], env, args.time_limit)
    (folder / "route.txt").write_bytes(text)
    run["seconds"] = round(seconds, 2)
    run["commands"] = [f"workcenter {' '.join(route)}"]
    run["output_bytes"] = len(text)
    run["design_exit"] = code
    if code is None:
        run.update(status="time limit", why=f"{args.time_limit} s")
        return run
    # `design` prints its `routed:` line only when the route ended with a summary; exit 1 with it is a
    # route that left connections open, which the DRC counts. Without it the route raised or was skipped.
    if not any(line.startswith("  routed: ") for line in text.decode("utf-8", "replace").splitlines()):
        run.update(
            status="error",
            why=f"the route ended with exit code {code} and no `routed:` line; see {folder / 'route.txt'}",
        )
        return run
    boards = sorted((folder / "board").glob("*.kicad_pcb"))
    if not boards:
        run.update(status="error", why=f"no board written; design exited {code}, see {folder / 'route.txt'}")
        return run
    drc = ["drc", str(folder / "board")]
    dcode, dtext, _ = timed_run([*wc, *drc], dict(os.environ), args.time_limit)
    (folder / "drc.txt").write_bytes(dtext)
    run["commands"].append(f"workcenter {' '.join(drc)}")
    run["output_bytes"] += len(dtext)
    report = folder / "board" / "build" / "drc.json"
    if dcode is None or not report.is_file():
        run.update(status="error", why=f"the DRC wrote no report; see {folder / 'drc.txt'}")
        return run
    counts = drc_counts(report)
    run.update(
        status="judged",
        connections=board_connections(boards[0]),
        unconnected=counts["unconnected"],
        drc_errors=counts["errors"],
        drc_warnings=counts["warnings"],
    )
    return run


def line_of(run: dict) -> str:
    head = f"bench {run['board']} {run['router']}"
    if run["status"] == "judged":
        return (
            f"{head}: {run['seconds']:.1f} s, {share_text(run)} joined, {run['drc_errors']} DRC errors, "
            f"{len(run['commands'])} commands, {run['output_bytes']} bytes read"
        )
    if run["status"] == "time limit":
        return f"{head}: stopped at the time limit ({run['limit']} s); not judged: no board was written"
    return f"{head}: {run['status']}: {run['why']}"


def parse_router(value: str) -> tuple[str, Path, str]:
    """`--router NAME=JAR`: a FreeRouting 1.9.0 jar under a name of its own; `--router NAME`: a router of
    routers.ROUTERS (`freerouting`, `freerouting2`). Returns (name in the table, jar, router)."""
    name, sep, jar = value.partition("=")
    if sep:
        if not name or not jar:
            raise ValueError(f"--router {value!r}: write NAME=JAR or the name of a router")
        return name, Path(jar), "freerouting"
    if value not in routers.ROUTERS:
        raise ValueError(f"--router {value!r}: write NAME=JAR or 1 of {', '.join(routers.ROUTERS)}")
    return value, routers.get(value).jar(), value


def cmd_bench(args, cli) -> int:
    out = Path(args.out).resolve()
    try:
        chosen = [parse_router(v) for v in args.router] if args.router else []
    except ValueError as exc:
        print(f"bench: {exc}")
        return cli.EXIT_FAIL
    if not chosen:
        chosen = [(jar_name(cli.FREEROUTING_JAR), cli.FREEROUTING_JAR, "freerouting")]
    default = chosen[0][0]
    designs = [Path(d).resolve() for d in args.designs]
    for d in designs:
        if not d.is_file():
            print(f"bench: no design file {d}")
            return cli.EXIT_FAIL
    plan = [
        (name, jar, order, engine)
        for name, jar, engine in chosen
        for order in ((False, True) if args.order else (False,))
    ]
    # 1 folder per board: 2 designs with 1 label, or a folder that holds another design's run, would
    # put 1 board's numbers under another's name.
    seen: dict[str, Path] = {}
    for design in designs:
        label = label_of(design).replace("/", "-")
        if label in seen and seen[label] != design:
            print(f"bench: {seen[label]} and {design} are both {label_of(design)}; bench them into 2 folders")
            return cli.EXIT_FAIL
        seen[label] = design
        for name, _, order, _ in plan:
            folder = folder_of(out, design, f"{name}+order" if order else name)
            held = held_design(folder / RUN_FILE)
            if held and held != str(design):
                print(f"bench: {folder} holds the run of {held}; give another --out")
                return cli.EXIT_FAIL
    out.mkdir(parents=True, exist_ok=True)
    for design in designs:
        for name, jar, order, engine in plan:
            run = bench_one(design, name, jar, out, args, cli, order, engine)
            folder = folder_of(out, design, run["router"])
            (folder / RUN_FILE).write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            print(line_of(run))
    runs, problems = read_runs(out)
    for path, why in problems:
        print(f"bench {path}: not judged: {why}")
    table = write_table(out, runs, default)
    picks = choose(runs, default)
    for board, (router, why) in sorted(picks.items()):
        print(f"  {board} takes {router}: {why}")
    print(f"wrote {table}")
    # The table is the verdict: a run in it that was not judged, or a board whose choice was not, is
    # not a pass, whether this call ran it or an earlier one did.
    unjudged = any(r["status"] != "judged" for r in runs)
    return cli.EXIT_SKIP if unjudged else cli.EXIT_PASS


def held_design(path: Path) -> str:
    """The design a folder's run file names, or "" when it names none or cannot be read."""
    try:
        run = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return run.get("design", "") if isinstance(run, dict) and isinstance(run.get("design"), str) else ""


def above_0(value: str) -> int:
    """A count of seconds, threads or passes: a whole number above 0. 0 s or -5 s is no time limit a
    route ever had, and the JVM refuses 0 processors."""
    try:
        n = int(value)
    except ValueError:
        n = 0
    if n <= 0:
        raise argparse.ArgumentTypeError(f"{value} is not a whole number above 0")
    return n


def register(sub, cli) -> None:
    """Add `bench` to the workcenter's parser; it sets `run` to its handler."""
    p = sub.add_parser(
        "bench",
        help="route design files with each router and record the time, the share of connections joined, "
        "the DRC's errors, the commands and the bytes of output; writes <out>/<board>/<router>/ (the "
        "board, route.txt, drc.txt, run.json) and <out>/bench.md, the table of every run in <out>",
    )
    p.add_argument("designs", nargs="*", help="design files; none rebuilds the table from <out>")
    p.add_argument("--out", required=True, help="the benchmark's folder")
    p.add_argument(
        "--router",
        action="append",
        metavar="NAME=JAR|NAME",
        help="a FreeRouting 1.9.0 jar to run under a name, or a router by name (freerouting, freerouting2), "
        "repeatable; the first is the default (default: the workcenter's)",
    )
    p.add_argument("--time-limit", type=above_0, default=300, help="seconds per route (default 300)")
    p.add_argument("--threads", type=above_0, default=2, help="router threads (default 2)")
    p.add_argument("--passes", type=above_0, default=20, help="router passes (default 20)")
    p.add_argument(
        "--order",
        action="store_true",
        help="also run each router as `design --route --order`, in stages, named <router>+order",
    )
    p.set_defaults(run=lambda a: cmd_bench(a, cli))
