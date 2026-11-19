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

import ctypes
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

PROTOCOL = "2025-11-25"
CLI = Path(__file__).resolve().parent / "workcenter"
SERVER = {"name": "ee-workcenter", "version": "1.0"}
# Seconds between SIGTERM and SIGKILL for a stopped command's process group.
GRACE = 10.0
# Commands that run at once. A further call waits for a slot in a thread of its own; the reader goes on.
SLOTS = 4
# Calls that may wait for a slot. A call beyond SLOTS + QUEUE is refused in 1 line.
QUEUE = 32
# The longest line read from stdin, in bytes. A longer line is answered -32600 and skipped to its end.
LINE_LIMIT = 4 * 1024 * 1024
# prctl options 1 and 2: set and get the signal a child gets when its parent dies (Linux <linux/prctl.h>).
PR_SET_PDEATHSIG = 1
PR_GET_PDEATHSIG = 2
UNGUARDED = "This system has no prctl PR_SET_PDEATHSIG: a SIGKILL to this server leaves its commands running."

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
    maximum: int | None = None


PROJECT = Option("project", "project", None, "the project folder or a KiCad file, relative to the root")
OUT = Option("out", "path", "--out", "output folder inside the root (default <project>/build)")
STRICT = Option("strict", "boolean", "--strict", "warnings fail the gate")
FAB = Option(
    "fab",
    "fab",
    "--fab",
    "also check a fab's limits: a rule set in Via's rules/, or a .kicad_dru inside the root",
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
            Option(
                "jobs", "count", "--jobs", "corners run at once (default: 1 per processor, 8 at most)", 64
            ),
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
            Option("passes", "count", "--passes", "router passes (default 20)", 1000),
            Option("threads", "count", "--threads", "router threads (default 0: its own)", 64),
            Option("timeout", "count", "--timeout", "seconds (default 600, 1 day at most)", 86400),
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
            if opt.maximum is not None:
                props[opt.name]["maximum"] = opt.maximum
        else:
            props[opt.name] = {"type": types[opt.kind], "description": opt.description}
    return {"type": "object", "properties": props, "additionalProperties": False}


def listing() -> list[dict]:
    return [
        {
            "name": name,
            "title": f"workcenter {name}",
            "description": f"{tool['description']}. The server runs {SLOTS} commands at once; a further "
            f"call waits its turn, and 1 beyond {SLOTS + QUEUE} held is refused",
            "inputSchema": schema(name),
            "outputSchema": OUTPUT_SCHEMA,
        }
        for name, tool in TOOLS.items()
    ]


def inside(root: Path, value: str, what: str) -> str:
    """`value` resolved against the root, links followed; refused when it lies outside."""
    try:
        path = (root / value).resolve()
    except (ValueError, OSError) as exc:  # a NUL byte, a loop of links
        raise Refused(f"refused: {what} {json.dumps(value)} is not a path: {exc}") from None
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
    if "out" in options and "out" not in arguments:
        # The command's default, <project>/build, named here so that it is held inside the root as a
        # named `out` is: a `build` link out of the root is refused, not followed.
        folder = Path(words[1]).parent if Path(words[1]).is_file() else Path(words[1])
        words += ["--out", inside(root, str((folder / "build").relative_to(root)), "out")]
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
            # JSON Schema's "integer" matches any number with a zero fractional part (2020-12,
            # draft-bhutton-json-schema-validation-01, 6.1.1 "type"): 3.0 is 3.
            if isinstance(value, float) and value.is_integer():
                value = int(value)
            top = opt.maximum
            if (
                isinstance(value, bool)
                or not isinstance(value, int)
                or value < 0
                or (top is not None and value > top)
            ):
                most = f"from 0 to {top}" if top is not None else "0 or more"
                raise Refused(f"refused: {name} must be a whole number {most}, not {json.dumps(value)}")
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

    def __init__(self, root: Path, out=None, cli: Path | None = None):
        self.root = root
        self.out = out if out is not None else sys.stdout.buffer
        self.cli = cli if cli is not None else CLI
        self.write_lock = threading.Lock()
        self.state = threading.Lock()
        self.active: set = set()  # ids of the calls accepted and not yet answered or dropped
        self.running: dict = {}  # request id -> Popen
        self.cancelled: set = set()
        self.threads: list[threading.Thread] = []
        self.slots = threading.BoundedSemaphore(SLOTS)
        self.room = SLOTS + QUEUE
        self.guarded = pdeathsig_works()

    def send(self, msg: dict) -> None:
        try:
            data = json.dumps(msg, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        except (RecursionError, ValueError, TypeError) as exc:  # never a half line on stdout
            text = f"Internal error: an answer that is not JSON: {type(exc).__name__}"
            rid = msg.get("id") if _valid_id(msg.get("id")) else None
            data = json.dumps(
                {"jsonrpc": "2.0", "id": rid, "error": {"code": INTERNAL_ERROR, "message": text}}
            )
            data = data.encode("utf-8") + b"\n"
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
        while raw := stream.readline(LINE_LIMIT):
            if len(raw) == LINE_LIMIT and not raw.endswith(b"\n"):
                while raw and not raw.endswith(b"\n"):  # the rest of the line, read and dropped
                    raw = stream.readline(LINE_LIMIT)
                self.error(None, INVALID_REQUEST, f"Invalid Request: a line longer than {LINE_LIMIT} bytes")
                continue
            if raw.strip():
                self.handle(raw)
        for thread in self.threads:
            thread.join()
        return 0

    def handle(self, raw: bytes) -> None:
        try:
            msg = json.loads(raw.decode("utf-8"))
        except RecursionError:
            self.error(None, INVALID_REQUEST, "Invalid Request: nested deeper than this server reads")
            return
        except (UnicodeDecodeError, ValueError) as exc:
            # Valid JSON, but a number of more digits than Python reads: not a parse error.
            if "integer string conversion" in str(exc):
                self.error(None, INVALID_REQUEST, f"Invalid Request: a number of too many digits: {exc}")
            else:
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
            if "id" in msg and ("result" in msg or "error" in msg):
                return  # a response: this server sends no requests, so there is nothing to match it to
            self.error(rid if _valid_id(rid) else None, INVALID_REQUEST, "Invalid Request: no method")
            return
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
                    "instructions": f"Via's gates on the projects under {self.root}. Each "
                    "tool runs `workcenter <tool>` and answers its lines and its exit code: 0 pass, 1 fail, "
                    f"2 skip. {SLOTS} commands run at once; a further call waits its turn, and 1 beyond "
                    f"{SLOTS + QUEUE} held is refused." + ("" if self.guarded else " " + UNGUARDED),
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
        with self.state:
            if rid in self.active:  # basic, "Messages": an id "MUST NOT" be reused
                self.error(rid, INVALID_REQUEST, f"Invalid Request: id {json.dumps(rid)} is in use by a call")
                return
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
        with self.state:
            if len(self.active) >= self.room:
                text = (
                    f"refused: {len(self.active)} calls are running or waiting, the most this server holds; "
                    "call again once 1 is answered"
                )
                self.result(rid, {"content": [{"type": "text", "text": text}], "isError": True})
                return
            self.active.add(rid)
        self.threads = [thread for thread in self.threads if thread.is_alive()]
        thread = threading.Thread(target=self.run, args=(rid, words, token), daemon=True)
        self.threads.append(thread)
        thread.start()

    def run(self, rid, words: list[str], token) -> None:
        """Wait for a slot, run 1 command and answer with its lines; a cancelled one is not answered."""
        try:
            with self.slots:
                self.run_now(rid, words, token)
        finally:
            with self.state:
                self.active.discard(rid)
                self.cancelled.discard(rid)

    def run_now(self, rid, words: list[str], token) -> None:
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
                    preexec_fn=_dies_with(os.getpid()) if self.guarded else None,
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
            with self.state:
                if rid in self.cancelled:  # basic/utilities/cancellation: "Stop processing"
                    continue
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
            if rid not in self.active:
                return  # unknown or finished: ignored (basic/utilities/cancellation, "Error Handling")
            self.cancelled.add(rid)  # a call that waits for a slot never starts
            proc = self.running.get(rid)
        if proc is not None:
            stop(proc)

    def stop_all(self) -> None:
        """SIGTERM to every command's process group, then SIGKILL to each still there after GRACE seconds.
        It returns when every command it started is gone, so the server exits after them."""
        with self.state:
            self.cancelled.update(self.active)
            procs = list(self.running.values())
        for proc in procs:
            _signal_group(proc, signal.SIGTERM)
        end = time.monotonic() + GRACE
        for proc in procs:
            try:
                proc.wait(timeout=max(0.0, end - time.monotonic()))
            except subprocess.TimeoutExpired:
                _signal_group(proc, signal.SIGKILL)


def _signal_group(proc: subprocess.Popen, signum: int) -> bool:
    try:
        os.killpg(proc.pid, signum)
    except ProcessLookupError:
        return False
    return True


def stop(proc: subprocess.Popen) -> None:
    """SIGTERM to the command's process group, its engines with it; SIGKILL after GRACE seconds."""
    if not _signal_group(proc, signal.SIGTERM):
        return

    def kill():
        try:
            proc.wait(timeout=GRACE)
        except subprocess.TimeoutExpired:
            _signal_group(proc, signal.SIGKILL)

    threading.Thread(target=kill, daemon=True).start()


def _prctl():
    try:
        return ctypes.CDLL(None, use_errno=True).prctl
    except (OSError, AttributeError):
        return None


def pdeathsig_works() -> bool:
    """True when prctl is there and answers: asked once, in the server, with PR_GET_PDEATHSIG, which
    changes nothing."""
    prctl = _prctl()
    if prctl is None:
        return False
    value = ctypes.c_int(0)
    return prctl(PR_GET_PDEATHSIG, ctypes.byref(value), 0, 0, 0) == 0


def _dies_with(parent: int):
    """A child's first step on Linux: SIGTERM to itself when the thread that started it dies, SIGKILL to
    the server among the ways (prctl PR_SET_PDEATHSIG; the command passes SIGTERM on to its engines).
    A server already gone between the fork and the prctl is caught by the parent pid. On another system
    nothing is set, a command can outlive a server killed by SIGKILL, and the server says so (UNGUARDED)."""
    if not pdeathsig_works():
        return None
    prctl = _prctl()

    def first():
        prctl(PR_SET_PDEATHSIG, signal.SIGTERM, 0, 0, 0)
        if os.getppid() != parent:
            os.kill(os.getpid(), signal.SIGTERM)

    return first


def _valid_id(value) -> bool:
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


def cmd_mcp(args) -> int:
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"workcenter mcp: {args.root}: not a folder", file=sys.stderr)
        return 2
    try:
        home = Path.home().resolve()
    except (RuntimeError, KeyError):
        home = None
    if root == Path(root.anchor) or root == home:
        print(
            f"workcenter mcp: {args.root}: too wide a root ({root}); every path a call names is held inside "
            "it, so name a project or a repository of versions",
            file=sys.stderr,
        )
        return 2
    server = Server(root)
    if not server.guarded:
        print(f"workcenter mcp: {UNGUARDED}", file=sys.stderr)

    def stopped(signum, _frame):
        # Each command runs in a process group of its own, so a signal to the server reaches none of
        # them: the server stops them, then dies as a shell reports a signal, 128 and its number.
        server.stop_all()
        raise SystemExit(128 + signum)

    # SIGINT is a terminal's Ctrl-C: the same stop, exit 130, and no traceback.
    for signum in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(signum, stopped)
    return server.serve(sys.stdin.buffer)


def register(sub, cli) -> None:
    """Add `mcp` to the CLI's parser."""
    p = sub.add_parser(
        "mcp",
        help="serve doctor, gates, erc, drc, sim, export and autoroute as MCP tools over stdio (revision "
        "2025-11-25) for a host that is not Claude Code; every path a call names must lie inside ROOT. "
        "Writes only MCP messages to stdout",
    )
    p.add_argument("root", nargs="?", default=".", help="the folder the tools may reach (default .)")
    p.set_defaults(run=cmd_mcp)
