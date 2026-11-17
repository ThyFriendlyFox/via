"""`workcenter bench`: route design files with each router named and record, for each run, the time,
the share of connections joined, the DRC's count, the commands a model gives and the size of the
output it reads; then name the router each board takes (ROADMAP item 5).

A run is `workcenter design <file> --route` into its own folder, then `workcenter drc` on what it
wrote, both as a model would type them. The share joined is counted on the routed board: each net's
pads less 1 are the connections it asks for, and each of the DRC's unconnected items is 1 not made.
Standard library only, as the CLI is; the engines run in the commands it starts.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import kicadgen

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
            best = min(done, key=key)
            out[board] = (best["router"], f"{default} did not finish; {best['router']} {share_text(best)}")
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
    return f"| {run['board']} | {run['router']} | {run.get('seconds', 0.0):.1f} | " + " | ".join(cells) + " |"


def read_runs(out: Path) -> list[dict]:
    runs = []
    for path in sorted(out.glob(f"*/*/{RUN_FILE}")):
        try:
            runs.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return runs


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


def label_of(design: Path) -> str:
    """A board's name in the table: its design file's folder and the one above it."""
    parts = design.resolve().parent.parts
    return "/".join(parts[-2:])


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


def bench_one(design: Path, router: str, jar: Path, out: Path, args, cli) -> dict:
    board = label_of(design)
    folder = out / board.replace("/", "-") / router
    folder.mkdir(parents=True, exist_ok=True)
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
    if not jar.is_file():
        run.update(status="not run", why=f"no router at {jar}")
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
    ]
    env = dict(os.environ, FREEROUTING_JAR=str(jar))
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


def parse_router(value: str) -> tuple[str, Path]:
    name, sep, jar = value.partition("=")
    if not sep or not name or not jar:
        raise ValueError(f"--router {value!r}: write NAME=JAR")
    return name, Path(jar)


def cmd_bench(args, cli) -> int:
    out = Path(args.out).resolve()
    try:
        routers = [parse_router(v) for v in args.router] if args.router else []
    except ValueError as exc:
        print(f"bench: {exc}")
        return cli.EXIT_FAIL
    if not routers:
        routers = [(jar_name(cli.FREEROUTING_JAR), cli.FREEROUTING_JAR)]
    default = routers[0][0]
    designs = [Path(d).resolve() for d in args.designs]
    for d in designs:
        if not d.is_file():
            print(f"bench: no design file {d}")
            return cli.EXIT_FAIL
    out.mkdir(parents=True, exist_ok=True)
    unjudged = 0
    for design in designs:
        for name, jar in routers:
            run = bench_one(design, name, jar, out, args, cli)
            folder = out / run["board"].replace("/", "-") / name
            (folder / RUN_FILE).write_text(json.dumps(run, indent=2) + "\n", encoding="utf-8")
            unjudged += run["status"] != "judged"
            print(line_of(run))
    runs = read_runs(out)
    table = write_table(out, runs, default)
    for board, (router, why) in sorted(choose(runs, default).items()):
        print(f"  {board} takes {router}: {why}")
    print(f"wrote {table}")
    return cli.EXIT_SKIP if unjudged else cli.EXIT_PASS


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
        metavar="NAME=JAR",
        help="a FreeRouting jar to run, repeatable; the first is the default (default: the workcenter's)",
    )
    p.add_argument("--time-limit", type=int, default=300, help="seconds per route (default 300)")
    p.add_argument("--threads", type=int, default=2, help="router threads (default 2)")
    p.add_argument("--passes", type=int, default=20, help="router passes (default 20)")
    p.set_defaults(run=lambda a: cmd_bench(a, cli))
