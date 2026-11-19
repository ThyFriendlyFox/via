#!/usr/bin/env python3
"""`workcenter mcp`: the gates as MCP tools over stdio, for a host that is not Claude Code.

The protocol is MCP's revision 2025-11-25 (modelcontextprotocol.io/specification/2025-11-25), the last
revision with the `initialize` handshake. Where each message's shape comes from:

- stdio, 1 JSON-RPC message per line on stdin and stdout, nothing else on stdout: basic/transports.
- `initialize`, its answer, `notifications/initialized`, the version answered: basic/lifecycle.
- requests, responses, notifications, an id that is a string or an integer: basic ("Messages").
- `tools/list`, `tools/call`, `isError` for a tool's own failure, -32602 for an unknown tool:
  server/tools.
- `ping`: basic/utilities/ping. `notifications/cancelled`: basic/utilities/cancellation.
  `notifications/progress` to a request's `_meta.progressToken`: basic/utilities/progress.
- the error codes -32700, -32600, -32601, -32602, -32603: JSON-RPC 2.0 (jsonrpc.org/specification, 5.1).

A client of revision 2026-07-28 and later sends `server/discover` first; this server answers -32601,
and a client of both eras then falls back to `initialize` (2026-07-28 basic/versioning, "Backward
Compatibility"). A client of the later era alone does not.

Each tool runs `tools/workcenter <command>` as a child process: the command's own code, its own engine
lock and its own lines; nothing here judges a board. The reader never waits on a tool: each call runs in
a thread of its own, so `ping` and a cancel are answered while a gate runs. Every path a call names
must lie inside the folder the server was given.

Standard library only, as the CLI is (AGENTS.md invariant 3).
"""

from __future__ import annotations

import json
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path

PROTOCOL = "2025-11-25"
CLI = Path(__file__).resolve().parent / "workcenter"
SERVER = {"name": "ee-workcenter", "version": "1.0"}
# Seconds between SIGTERM and SIGKILL for a cancelled command's process group.
GRACE = 10.0

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

DECK_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")


@dataclass(frozen=True)
class Option:
    """1 argument of a tool and the command-line word it becomes. `kind`: project (the positional
    project path), path (a path held inside the root), fab (a rule set's name, or a path held inside
    the root), name (a word with no slash), boolean, count (a whole number, 0 or more)."""

    name: str
    kind: str
    flag: str | None
    description: str


PROJECT = Option("project", "project", None, "the project folder or a KiCad file, relative to the root")
OUT = Option("out", "path", "--out", "output folder inside the root (default <project>/build)")
STRICT = Option("strict", "boolean", "--strict", "warnings fail the gate")
FAB = Option(
    "fab",
    "fab",
    "--fab",
    "also check a fab's limits: a rule set in the workcenter's rules/, or a .kicad_dru inside the root",
)
STEP = Option("step", "boolean", "--step", "also export a STEP model")

# The 7 tools, in the order `tools/list` gives them. Each description is the command's own, as its
# `--help` gives it; tests/test_mcp.py holds every flag here to that help.
TOOLS: dict[str, dict] = {
    "doctor": {
        "description": "report engine status: each engine, its version, the engine lock",
        "options": [],
    },
    "gates": {
        "description": "run erc, drc, sim, export in order; stop at the first red. The last line is the "
        "verdict: GREEN, RED or SKIPPED",
        "options": [PROJECT, OUT, STRICT, STEP, FAB],
    },
    "erc": {"description": "electrical rules check on the schematic", "options": [PROJECT, OUT, STRICT]},
    "drc": {
        "description": "design rules check on the board, with schematic parity",
        "options": [PROJECT, OUT, STRICT, FAB],
    },
    "sim": {
        "description": "run ngspice on sim/*.cir and hold every *.expect.json bound, as written and at each "
        "corner of sim/corners.json, then judge sim/frequency-plan.json",
        "options": [
            PROJECT,
            OUT,
            STRICT,
            Option("deck", "name", "--deck", "run only sim/DECK.cir; the frequency plan is not judged"),
            Option("nominal", "boolean", "--nominal", "each deck as written only; the corners are left out"),
            Option("jobs", "count", "--jobs", "corners run at once (default: 1 per processor, 8 at most)"),
        ],
    },
    "export": {
        "description": "fabrication outputs: gerbers, drill, BOM, schematic PDF",
        "options": [PROJECT, OUT, STRICT, STEP],
    },
    "autoroute": {
        "description": "run FreeRouting on the project's Specctra DSN, write a .ses",
        "options": [
            PROJECT,
            OUT,
            STRICT,
            Option("dsn", "path", "--dsn", "Specctra DSN inside the root (default <project>/<name>.dsn)"),
            Option("passes", "count", "--passes", "router passes (default 20)"),
            Option("threads", "count", "--threads", "router threads (default 0: its own)"),
            Option("timeout", "count", "--timeout", "seconds (default 600)"),
        ],
    },
}

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "command": {"type": "string", "description": "the command line the tool ran"},
        "exitCode": {"type": "integer", "description": "the command's exit code: 0 pass, 1 fail, 2 skip"},
    },
    "required": ["command", "exitCode"],
}


class Refused(Exception):
    """A call the server will not run; the message is its 1 line."""


def schema(tool: str) -> dict:
    types = {"project": "string", "path": "string", "fab": "string", "name": "string"}
    props = {}
    for opt in TOOLS[tool]["options"]:
        if opt.kind == "boolean":
            props[opt.name] = {"type": "boolean", "description": opt.description}
        elif opt.kind == "count":
            props[opt.name] = {"type": "integer", "minimum": 0, "description": opt.description}
        else:
            props[opt.name] = {"type": types[opt.kind], "description": opt.description}
    return {"type": "object", "properties": props, "additionalProperties": False}


def listing() -> list[dict]:
    return [
        {
            "name": name,
            "title": f"workcenter {name}",
            "description": tool["description"],
            "inputSchema": schema(name),
            "outputSchema": OUTPUT_SCHEMA,
        }
        for name, tool in TOOLS.items()
    ]


def inside(root: Path, value: str, what: str) -> str:
    """`value` resolved against the root, links followed; refused when it lies outside."""
    path = (root / value).resolve()
    if path != root and root not in path.parents:
        raise Refused(f"refused: {what} {value} is outside {root}, the folder this server was given")
    return str(path)


def command_line(root: Path, tool: str, arguments: dict) -> list[str]:
    """The `workcenter` words for 1 call, every value checked; raises Refused."""
    options = {opt.name: opt for opt in TOOLS[tool]["options"]}
    unknown = sorted(set(arguments) - set(options))
    if unknown:
        takes = ", ".join(options) or "no arguments"
        raise Refused(f"refused: {tool} takes {takes}, not {', '.join(unknown)}")
    words = [tool]
    if "project" in options:
        project = arguments.get("project", ".")
        if not isinstance(project, str):
            raise Refused(f"refused: project must be a string, not {json.dumps(project)}")
        words.append(inside(root, project, "project"))
    for name, opt in options.items():
        if name not in arguments or opt.kind == "project":
            continue
        value = arguments[name]
        if opt.kind == "boolean":
            if not isinstance(value, bool):
                raise Refused(f"refused: {name} must be true or false, not {json.dumps(value)}")
            if value:
                words.append(opt.flag)
            continue
        if opt.kind == "count":
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise Refused(f"refused: {name} must be a whole number, 0 or more, not {json.dumps(value)}")
            words += [opt.flag, str(value)]
            continue
        if not isinstance(value, str) or not value:
            raise Refused(f"refused: {name} must be a string, not {json.dumps(value)}")
        if opt.kind == "path" or (opt.kind == "fab" and ("/" in value or value.endswith(".kicad_dru"))):
            value = inside(root, value, name)
        elif not DECK_RE.match(value):
            raise Refused(f"refused: {name} must be a name of letters, digits, '.', '_' or '-', not {value}")
        words += [opt.flag, value]
    return words


class Server:
    """1 session on 1 stream pair. `serve` reads until stdin closes."""

    def __init__(self, root: Path, out=None, cli: Path = CLI):
        self.root = root
        self.out = out if out is not None else sys.stdout.buffer
        self.cli = cli
        self.write_lock = threading.Lock()
        self.state = threading.Lock()
        self.running: dict = {}  # request id -> Popen
        self.cancelled: set = set()
        self.threads: list[threading.Thread] = []

    def send(self, msg: dict) -> None:
        data = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        with self.write_lock:
            try:
                self.out.write(data)
                self.out.flush()
            except (BrokenPipeError, ValueError):
                pass

    def error(self, rid, code: int, message: str) -> None:
        self.send({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}})

    def result(self, rid, result: dict) -> None:
        self.send({"jsonrpc": "2.0", "id": rid, "result": result})

    def serve(self, stream) -> int:
        """Read until stdin closes, then answer the calls still running and return. A client that will
        not wait sends SIGTERM (basic/lifecycle, "Shutdown"), which `cmd_mcp` turns into `stop_all`."""
        for raw in stream:
            if raw.strip():
                self.handle(raw)
        for thread in self.threads:
            thread.join()
        return 0

    def handle(self, raw: bytes) -> None:
        try:
            msg = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            self.error(None, PARSE_ERROR, "Parse error: a line that is not UTF-8 JSON")
            return
        if not isinstance(msg, dict):
            self.error(None, INVALID_REQUEST, "Invalid Request: 1 JSON object per line, no batches")
            return
        rid = msg.get("id")
        is_request = "id" in msg and "method" in msg
        if msg.get("jsonrpc") != "2.0":
            if is_request and _valid_id(rid):
                self.error(rid, INVALID_REQUEST, 'Invalid Request: jsonrpc must be "2.0"')
            elif "method" in msg or "id" not in msg:
                self.error(None, INVALID_REQUEST, 'Invalid Request: jsonrpc must be "2.0"')
            return
        method = msg.get("method")
        if "method" not in msg:
            return  # a response: this server sends no requests, so there is nothing to match it to
        params = msg.get("params", {})
        if not is_request:
            self.notification(method, params if isinstance(params, dict) else {})
            return
        if not _valid_id(rid) or not isinstance(method, str):
            self.error(None, INVALID_REQUEST, "Invalid Request: an id is a string or an integer")
            return
        if not isinstance(params, dict):
            self.error(rid, INVALID_PARAMS, "Invalid params: params must be an object")
            return
        try:
            self.request(rid, method, params)
        except Exception as exc:  # a fault of this server is answered, never left without a response
            self.error(rid, INTERNAL_ERROR, f"Internal error: {type(exc).__name__}: {exc}")

    def request(self, rid, method: str, params: dict) -> None:
        if method == "initialize":
            self.result(
                rid,
                {
                    "protocolVersion": PROTOCOL,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER,
                    "instructions": f"The EE workcenter's gates on the projects under {self.root}. Each "
                    "tool runs `workcenter <tool>` and answers its lines and its exit code: 0 pass, 1 fail, "
                    "2 skip.",
                },
            )
        elif method == "ping":
            self.result(rid, {})
        elif method == "tools/list":
            self.result(rid, {"tools": listing()})
        elif method == "tools/call":
            self.call(rid, params)
        else:
            self.error(rid, METHOD_NOT_FOUND, f"Method not found: {method}")

    def notification(self, method, params: dict) -> None:
        if method == "notifications/cancelled":
            rid = params.get("requestId")
            if _valid_id(rid):
                self.cancel(rid)
        # notifications/initialized and any other notification: nothing to answer (basic, "Notifications").

    def call(self, rid, params: dict) -> None:
        name = params.get("name")
        if name not in TOOLS:
            self.error(rid, INVALID_PARAMS, f"Unknown tool: {name}")
            return
        arguments = params.get("arguments", {})
        if not isinstance(arguments, dict):
            self.error(rid, INVALID_PARAMS, "Invalid params: arguments must be an object")
            return
        meta = params.get("_meta")
        token = meta.get("progressToken") if isinstance(meta, dict) else None
        if not _valid_id(token):
            token = None
        try:
            words = command_line(self.root, name, arguments)
        except Refused as exc:
            self.result(rid, {"content": [{"type": "text", "text": str(exc)}], "isError": True})
            return
        thread = threading.Thread(target=self.run, args=(rid, words, token), daemon=True)
        self.threads.append(thread)
        thread.start()

    def run(self, rid, words: list[str], token) -> None:
        """Run 1 command and answer with its lines; a cancelled one is not answered."""
        env = dict(os.environ)
        env["PYTHONUNBUFFERED"] = "1"
        with self.state:
            if rid in self.cancelled:
                return
            try:
                proc = subprocess.Popen(
                    [sys.executable, str(self.cli), *words],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=self.root,
                    env=env,
                    start_new_session=True,
                )
            except OSError as exc:
                text = f"not run: workcenter {words[0]} could not start in {self.root}: {exc.strerror}"
                self.result(rid, {"content": [{"type": "text", "text": text}], "isError": True})
                return
            self.running[rid] = proc
        lines: list[str] = []
        for raw in proc.stdout:
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            lines.append(line)
            if token is not None:
                self.send(
                    {
                        "jsonrpc": "2.0",
                        "method": "notifications/progress",
                        "params": {"progressToken": token, "progress": len(lines), "message": line},
                    }
                )
        code = proc.wait()
        with self.state:
            self.running.pop(rid, None)
            if rid in self.cancelled:
                return
        # A command that died of a signal is reported as a shell reports it: 128 and the signal.
        code = 128 - code if code < 0 else code
        said = {"command": shlex.join(["workcenter", *words]), "exitCode": code}
        self.result(
            rid,
            {
                "content": [
                    {"type": "text", "text": "\n".join([*lines, f"exit code {code}"])},
                    {"type": "text", "text": json.dumps(said)},
                ],
                "structuredContent": said,
                "isError": code != 0,
            },
        )

    def cancel(self, rid) -> None:
        with self.state:
            if rid not in self.running:
                return  # unknown or finished: ignored (basic/utilities/cancellation, "Error Handling")
            self.cancelled.add(rid)
            proc = self.running[rid]
        stop(proc)

    def stop_all(self) -> None:
        with self.state:
            procs = list(self.running.items())
            self.cancelled.update(rid for rid, _ in procs)
        for _, proc in procs:
            stop(proc)


def stop(proc: subprocess.Popen) -> None:
    """SIGTERM to the command's process group, its engines with it; SIGKILL after GRACE seconds."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    def kill():
        try:
            proc.wait(timeout=GRACE)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    threading.Thread(target=kill, daemon=True).start()


def _valid_id(value) -> bool:
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


def cmd_mcp(args) -> int:
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"workcenter mcp: {args.root}: not a folder", file=sys.stderr)
        return 2
    server = Server(root)

    def stopped(signum, _frame):
        # Each command runs in a process group of its own, so a signal to the server reaches none of
        # them: the server stops them, then dies as a shell reports a signal, 128 and its number.
        server.stop_all()
        raise SystemExit(128 + signum)

    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, stopped)
    return server.serve(sys.stdin.buffer)


def register(sub, cli) -> None:
    """Add `mcp` to the workcenter's parser."""
    p = sub.add_parser(
        "mcp",
        help="serve doctor, gates, erc, drc, sim, export and autoroute as MCP tools over stdio (revision "
        "2025-11-25) for a host that is not Claude Code; every path a call names must lie inside ROOT. "
        "Writes only MCP messages to stdout",
    )
    p.add_argument("root", nargs="?", default=".", help="the folder the tools may reach (default .)")
    p.set_defaults(run=cmd_mcp)
