"""`workcenter mcp`: the gates as MCP tools over stdio, driven by a scripted JSON-RPC session over a pipe.

The client below speaks the protocol as the specification's revision 2025-11-25 writes it
(modelcontextprotocol.io/specification/2025-11-25): 1 JSON-RPC message per line on the server's stdin and
stdout (basic/transports, "stdio"), `initialize` then `notifications/initialized` (basic/lifecycle),
`tools/list` and `tools/call` (server/tools), `ping` (basic/utilities/ping), `notifications/cancelled`
(basic/utilities/cancellation) and `notifications/progress` (basic/utilities/progress). The error codes
are JSON-RPC 2.0's (jsonrpc.org/specification, 5.1): -32700 parse error, -32600 invalid request,
-32601 method not found, -32602 invalid params.

Every line the server writes to stdout must be 1 JSON object: the reader fails the test on any other.
Each test that runs the server gives it a lock folder of its own (WORKCENTER_LOCK_DIR), so a run of
another agent on the machine neither waits on it nor is waited on.
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
from conftest import engine

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
LOCK_PY = ROOT / "tools" / "enginelock.py"
sys.path.insert(0, str(ROOT / "tools"))

TOOLS = ["doctor", "gates", "erc", "drc", "sim", "export", "autoroute"]
needs_kicad = engine(pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli not installed"))
needs_ngspice = engine(pytest.mark.skipif(shutil.which("ngspice") is None, reason="ngspice not installed"))


class Client:
    """A test client: starts `workcenter mcp ROOT` and speaks to it over its stdin and stdout."""

    def __init__(self, root: Path, lock_dir: Path, every: str = "0.2"):
        env = dict(os.environ)
        env["WORKCENTER_LOCK_DIR"] = str(lock_dir)
        env["WORKCENTER_LOCK_EVERY"] = every
        env.pop("WORKCENTER_LOCK_TICKET", None)
        env.pop("WORKCENTER_LOCK", None)
        # A test session sends the lock's waiting lines to a file of its own (tests/conftest.py); the
        # server passes a command's lines on, so they must reach the command's stderr here.
        env.pop("WORKCENTER_LOCK_LOG", None)
        self.proc = subprocess.Popen(
            [sys.executable, str(CLI), "mcp", str(root)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
        self.inbox: queue.Queue = queue.Queue()
        self.kept: list[dict] = []
        self.bad: list[bytes] = []
        self.next_id = 0
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        for raw in self.proc.stdout:
            try:
                msg = json.loads(raw)
            except ValueError:
                self.bad.append(raw)
                continue
            if not isinstance(msg, dict):
                self.bad.append(raw)
                continue
            self.inbox.put(msg)
        self.inbox.put(None)

    def send_raw(self, text: str):
        self.proc.stdin.write(text.encode() + b"\n")
        self.proc.stdin.flush()

    def send(self, msg: dict):
        self.send_raw(json.dumps(msg))

    def request(self, method: str, params: dict | None = None) -> int:
        self.next_id += 1
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)
        return self.next_id

    def notify(self, method: str, params: dict | None = None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self.send(msg)

    def wait_for(self, match, timeout: float = 30.0) -> dict:
        """The first message, kept or new, that `match` takes; the others are kept in order."""
        for i, msg in enumerate(self.kept):
            if match(msg):
                return self.kept.pop(i)
        end = time.monotonic() + timeout
        while True:
            left = end - time.monotonic()
            assert left > 0, f"no such message in {timeout} s; kept {self.kept}"
            try:
                msg = self.inbox.get(timeout=left)
            except queue.Empty:
                continue
            assert msg is not None, f"the server closed its stdout; stderr {self.stderr()}"
            if match(msg):
                return msg
            self.kept.append(msg)

    def answer(self, rid, timeout: float = 30.0) -> dict:
        return self.wait_for(lambda m: m.get("id") == rid and ("result" in m or "error" in m), timeout)

    def call(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        return self.answer(self.request(method, params), timeout)

    def start(self) -> dict:
        reply = self.call(
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "test_mcp", "version": "1.0"},
            },
        )
        self.notify("notifications/initialized")
        return reply

    def stderr(self) -> str:
        return "" if self.proc.poll() is None else self.proc.stderr.read().decode(errors="replace")

    def close(self, timeout: float = 20.0) -> int:
        if self.proc.stdin and not self.proc.stdin.closed:
            self.proc.stdin.close()
        try:
            return self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
            raise


@pytest.fixture
def lock_dir(tmp_path):
    folder = tmp_path / "lock"
    folder.mkdir(mode=0o700)
    return folder


def served(root: Path, lock_dir: Path, request, every: str = "0.2"):
    client = Client(root, lock_dir, every)

    def done():
        if client.proc.poll() is None:
            client.proc.kill()
            client.proc.wait()

    request.addfinalizer(done)
    return client


def tool_text(result: dict) -> list[str]:
    return result["content"][0]["text"].splitlines()


def untimed(lines: list[str]) -> list[str]:
    """A gate's line carries its run time, `[0.34s]`: 2 runs of 1 command differ there alone."""
    return [re.sub(r"\[\d+(\.\d+)?s\]", "[t]", line) for line in lines]


def test_initialize_answers_the_revision_and_tools_list_names_the_7_tools(tmp_path, lock_dir, request):
    """The Promise's 7 tools, by name, each with an input schema that takes only its own options.
    A client that asks for another revision gets the 1 the server speaks (basic/lifecycle, "Version
    Negotiation": "the server MUST respond with another protocol version it supports")."""
    client = served(tmp_path, lock_dir, request)
    reply = client.start()["result"]
    assert reply["protocolVersion"] == "2025-11-25"
    assert reply["capabilities"]["tools"] == {"listChanged": False}
    assert reply["serverInfo"]["name"] == "ee-workcenter"
    tools = client.call("tools/list")["result"]["tools"]
    assert [t["name"] for t in tools] == TOOLS
    for tool in tools:
        schema = tool["inputSchema"]
        assert schema["type"] == "object" and schema["additionalProperties"] is False, tool["name"]
        assert tool["description"], tool["name"]
        assert tool["outputSchema"]["required"] == ["command", "exitCode"], tool["name"]
    by_name = {t["name"]: t["inputSchema"]["properties"] for t in tools}
    assert by_name["doctor"] == {}
    for name in TOOLS[1:]:
        assert {"project", "out", "strict"} <= set(by_name[name]), name
    assert by_name["autoroute"]["passes"]["type"] == "integer"
    assert by_name["sim"]["nominal"]["type"] == "boolean"
    other = Client(tmp_path, lock_dir)
    request.addfinalizer(lambda: other.proc.kill())
    old = other.call(
        "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "x"}}
    )
    assert old["result"]["protocolVersion"] == "2025-11-25"
    assert client.close() == 0 and other.close() == 0
    assert client.bad == [] and other.bad == []


def test_every_option_of_a_tool_is_a_flag_its_command_takes():
    """No second list of options: each option the server offers becomes a flag that the command's own
    `--help` names, so a renamed flag fails here, not in a host's hands."""
    import mcpserver

    assert list(mcpserver.TOOLS) == TOOLS
    for name, tool in mcpserver.TOOLS.items():
        text = subprocess.run(
            [sys.executable, str(CLI), name, "--help"], capture_output=True, text=True, check=True
        ).stdout
        for option in tool["options"]:
            if option.flag:
                assert re.search(rf"(?<![\w-]){re.escape(option.flag)}\b", text), (name, option.flag)


def test_a_path_outside_the_project_is_refused_and_nothing_runs(tmp_path, lock_dir, request):
    """`project`, `out`, `dsn` and a `fab` given as a path must lie inside the folder the server was
    given, after links are followed. Each refusal is 1 line, `isError` is true, and the command is not
    started: no `build/` appears beside the root."""
    root = tmp_path / "root"
    shutil.copytree(BOARDS / "pass-rc-divider", root)
    (root / "away").symlink_to(tmp_path)
    client = served(root, lock_dir, request)
    client.start()
    cases = [
        ("erc", {"project": ".."}),
        ("erc", {"project": "/etc"}),
        ("erc", {"project": "away"}),
        ("drc", {"project": ".", "out": "../out"}),
        ("drc", {"project": ".", "fab": "../rules.kicad_dru"}),
        ("autoroute", {"project": ".", "dsn": "/tmp/x.dsn"}),
        ("gates", {"project": "away/lock"}),
    ]
    for tool, args in cases:
        result = client.call("tools/call", {"name": tool, "arguments": args})["result"]
        lines = tool_text(result)
        assert result["isError"] is True, (tool, args)
        assert len(lines) == 1 and "outside" in lines[0] and str(root) in lines[0], (tool, args, lines)
        assert "structuredContent" not in result
    assert not (root / "build").exists() and not (tmp_path / "out").exists()
    assert client.close() == 0


def test_an_argument_of_the_wrong_kind_is_refused_in_1_line(tmp_path, lock_dir, request):
    """Input validation is a tool execution error, with isError (server/tools, "Error Handling"), not a
    protocol error. A name the tool does not take, a string for a boolean, a boolean or a negative number
    for a count, a deck name with a slash."""
    client = served(tmp_path, lock_dir, request)
    client.start()
    cases = [
        ("erc", {"colour": "red"}, "colour"),
        ("erc", {"strict": "yes"}, "strict"),
        ("autoroute", {"passes": True}, "passes"),
        ("autoroute", {"passes": -1}, "passes"),
        ("sim", {"deck": "../x"}, "deck"),
        ("doctor", {"project": "."}, "project"),
    ]
    for tool, args, named in cases:
        result = client.call("tools/call", {"name": tool, "arguments": args})["result"]
        lines = tool_text(result)
        assert result["isError"] is True and len(lines) == 1 and named in lines[0], (tool, args, lines)
    assert client.close() == 0


def test_a_command_that_cannot_start_is_answered_in_1_line(tmp_path, lock_dir, request):
    """The root removed while the server runs: the command cannot start in it. The call is still
    answered, in 1 line that names the root, with isError and no exit code, since nothing ran."""
    root = tmp_path / "gone"
    root.mkdir()
    client = served(root, lock_dir, request)
    client.start()
    root.rmdir()
    result = client.call("tools/call", {"name": "erc", "arguments": {}})["result"]
    lines = tool_text(result)
    assert result["isError"] is True and "structuredContent" not in result
    assert len(lines) == 1 and lines[0].startswith("not run: ") and str(root) in lines[0], lines
    assert client.call("ping")["result"] == {}
    assert client.close() == 0


def test_protocol_errors_carry_json_rpc_codes(tmp_path, lock_dir, request):
    """-32700 for a line that is not JSON, with a null id; -32600 for a message that is not an object
    (a batch: the transport carries "individual JSON-RPC requests, notifications, or responses"); -32601
    for a method the server does not have, `server/discover` among them, so a client of both eras falls
    back to `initialize` (2026-07-28 basic/versioning, "Backward Compatibility"); -32602 for an unknown
    tool (server/tools, "Error Handling"). A notification gets no answer: the ping after it is the next
    message."""
    client = served(tmp_path, lock_dir, request)
    client.start()
    client.send_raw("{not json")
    parse = client.wait_for(lambda m: "error" in m)
    assert parse["error"]["code"] == -32700 and parse["id"] is None
    client.send_raw(json.dumps([{"jsonrpc": "2.0", "id": 90, "method": "ping"}]))
    batch = client.wait_for(lambda m: "error" in m)
    assert batch["error"]["code"] == -32600 and batch["id"] is None
    client.send({"jsonrpc": "1.0", "id": 91, "method": "ping"})
    assert client.answer(91)["error"]["code"] == -32600
    assert client.call("server/discover")["error"]["code"] == -32601
    assert client.call("resources/list")["error"]["code"] == -32601
    unknown = client.call("tools/call", {"name": "route", "arguments": {}})
    assert unknown["error"]["code"] == -32602 and "route" in unknown["error"]["message"]
    assert client.call("tools/call", {"arguments": {}})["error"]["code"] == -32602
    client.notify("notifications/whatever")
    pong = client.call("ping")
    assert pong["result"] == {} and client.kept == []
    assert client.close() == 0 and client.bad == []


def test_a_waiting_gate_leaves_ping_answered_and_is_cancelled(tmp_path, lock_dir, request):
    """A long tool must not block the protocol's own messages. `sim` is a long command: while another
    process holds the engine lock it waits, and prints that it waits. The server answers `ping` in that
    time (basic/utilities/ping: "The receiver MUST respond promptly"), passes the waiting line on as a
    progress notification to the token the call named, and on `notifications/cancelled` stops the command
    and sends no response for it (basic/utilities/cancellation: "Not send a response for the cancelled
    request"). The command's process is gone after the cancel: its pid no longer exists."""
    root = tmp_path / "root"
    shutil.copytree(BOARDS / "pass-rc-divider", root)
    env = dict(os.environ, WORKCENTER_LOCK_DIR=str(lock_dir))
    env.pop("WORKCENTER_LOCK_TICKET", None)
    holder = subprocess.Popen(
        [sys.executable, str(LOCK_PY), "hold", "--what", "test holder", "--", "sleep", "120"], env=env
    )
    request.addfinalizer(lambda: (holder.kill(), holder.wait()))
    end = time.monotonic() + 20
    while not list(lock_dir.glob("*.held")):
        assert time.monotonic() < end, "the holder never took the lock"
        time.sleep(0.05)
    client = served(root, lock_dir, request)
    client.start()
    sim = client.request(
        "tools/call", {"name": "sim", "arguments": {"project": "."}, "_meta": {"progressToken": "s1"}}
    )
    told = client.wait_for(lambda m: m.get("method") == "notifications/progress")
    assert told["params"]["progressToken"] == "s1" and told["params"]["progress"] == 1
    assert "waiting on the engine lock" in told["params"]["message"]
    # The progress value "MUST increase with each notification" (basic/utilities/progress). The command
    # says it still waits every WORKCENTER_LOCK_EVERY = 0.2 s, so a second line comes: 1 line, then 2.
    again = client.wait_for(lambda m: m.get("method") == "notifications/progress")
    assert again["params"]["progress"] > told["params"]["progress"]
    started = time.monotonic()
    assert client.call("ping", timeout=5)["result"] == {}
    assert time.monotonic() - started < 5
    pids = client.call("tools/list")["result"]  # a second request between, answered too
    assert len(pids["tools"]) == 7
    waiting = [p for p in Path("/proc").iterdir() if p.name.isdigit() and _runs_sim(p, root)]
    assert len(waiting) == 1
    client.notify("notifications/cancelled", {"requestId": sim, "reason": "test"})
    end = time.monotonic() + 20
    while waiting[0].exists():
        assert time.monotonic() < end, "the cancelled command still runs"
        time.sleep(0.05)
    assert client.call("ping")["result"] == {}
    time.sleep(0.5)
    assert client.close() == 0
    late = [m for m in client.kept if m.get("id") == sim]
    while True:
        msg = client.inbox.get(timeout=5)
        if msg is None:
            break
        late += [msg] if msg.get("id") == sim else []
        late += [msg] if "stopped by signal" in msg.get("params", {}).get("message", "") else []
    # Nothing more for the cancelled request, not even a progress notification of the line the command
    # prints when the cancel's SIGTERM stops it (basic/utilities/cancellation: "Stop processing").
    late += [m for m in client.kept if "stopped by signal" in m.get("params", {}).get("message", "")]
    assert late == [] and client.bad == []
    assert holder.poll() is None


def test_a_call_sent_before_stdin_closes_is_still_answered(tmp_path, lock_dir, request):
    """A client ends a session by closing the server's stdin and then waits for it to exit
    (basic/lifecycle, "Shutdown", stdio). A call already sent is answered first. `erc` on a folder with
    no KiCad file stops in the command's own project lookup, before any engine: 1 line, exit 1."""
    (tmp_path / "empty").mkdir()
    client = served(tmp_path, lock_dir, request)
    client.start()
    rid = client.request("tools/call", {"name": "erc", "arguments": {"project": "empty"}})
    client.proc.stdin.close()
    result = client.answer(rid)["result"]
    lines = tool_text(result)
    assert lines == [
        f"{tmp_path / 'empty'}: no KiCad project, schematic, board or sim/ directory found",
        "exit code 1",
    ]
    assert result["isError"] is True and result["structuredContent"]["exitCode"] == 1
    assert client.close() == 0


def test_sigterm_stops_the_server_and_the_commands_it_started(tmp_path, lock_dir, request):
    """The client's next step when the server does not exit is SIGTERM (basic/lifecycle, "Shutdown").
    The server then stops each command it started, here a `sim` that waits on a held engine lock, and
    exits with 128 + 15."""
    root = tmp_path / "root"
    shutil.copytree(BOARDS / "pass-rc-divider", root)
    env = dict(os.environ, WORKCENTER_LOCK_DIR=str(lock_dir))
    env.pop("WORKCENTER_LOCK_TICKET", None)
    holder = subprocess.Popen(
        [sys.executable, str(LOCK_PY), "hold", "--what", "test holder", "--", "sleep", "120"], env=env
    )
    request.addfinalizer(lambda: (holder.kill(), holder.wait()))
    end = time.monotonic() + 20
    while not list(lock_dir.glob("*.held")):
        assert time.monotonic() < end, "the holder never took the lock"
        time.sleep(0.05)
    client = served(root, lock_dir, request)
    client.start()
    client.request(
        "tools/call", {"name": "sim", "arguments": {"project": "."}, "_meta": {"progressToken": 7}}
    )
    client.wait_for(lambda m: m.get("method") == "notifications/progress")
    waiting = [p for p in Path("/proc").iterdir() if p.name.isdigit() and _runs_sim(p, root)]
    assert len(waiting) == 1
    client.proc.terminate()
    assert client.proc.wait(timeout=20) == 128 + 15
    end = time.monotonic() + 20
    while waiting[0].exists():
        assert time.monotonic() < end, "the command outlived the server"
        time.sleep(0.05)


def _waiting_sim(tmp_path: Path, lock_dir: Path, request, every: str = "0.2"):
    """A served `sim` that waits on an engine lock held by a holder of the test's own: the client and the
    /proc folder of the waiting command. `every`: seconds between the command's waiting lines."""
    root = tmp_path / "root"
    shutil.copytree(BOARDS / "pass-rc-divider", root)
    env = dict(os.environ, WORKCENTER_LOCK_DIR=str(lock_dir))
    env.pop("WORKCENTER_LOCK_TICKET", None)
    holder = subprocess.Popen(
        [sys.executable, str(LOCK_PY), "hold", "--what", "test holder", "--", "sleep", "120"], env=env
    )
    request.addfinalizer(lambda: (holder.kill(), holder.wait()))
    end = time.monotonic() + 20
    while not list(lock_dir.glob("*.held")):
        assert time.monotonic() < end, "the holder never took the lock"
        time.sleep(0.05)
    client = served(root, lock_dir, request, every)
    client.start()
    client.request(
        "tools/call", {"name": "sim", "arguments": {"project": "."}, "_meta": {"progressToken": 7}}
    )
    client.wait_for(lambda m: m.get("method") == "notifications/progress")
    waiting = [p for p in Path("/proc").iterdir() if p.name.isdigit() and _runs_sim(p, root)]
    assert len(waiting) == 1
    request.addfinalizer(lambda: _kill(int(waiting[0].name)))
    return client, waiting[0]


def test_sigint_stops_the_commands_and_exits_130_without_a_traceback(tmp_path, lock_dir, request):
    """A terminal's Ctrl-C is SIGINT. It stops the commands the server started, as SIGTERM does, and the
    server exits as a shell reports a signal: 128 + 2 = 130. stderr carries no Python traceback."""
    client, waiting = _waiting_sim(tmp_path, lock_dir, request)
    client.proc.send_signal(2)
    assert client.proc.wait(timeout=20) == 130
    assert "Traceback" not in client.proc.stderr.read().decode(errors="replace")
    end = time.monotonic() + 20
    while _alive(waiting):
        assert time.monotonic() < end, "the command outlived the server"
        time.sleep(0.05)


def test_sigkill_to_the_server_stops_the_commands_it_started(tmp_path, lock_dir, request):
    """SIGKILL is the client's last step (basic/lifecycle, "Shutdown"); the server cannot trap it. Each
    command learns that its parent died and stops: no command lives on to take the engine lock for a host
    that is gone. The command writes its waiting line at the default interval, 30 s (enginelock.py EVERY),
    so it is not stopped by a write into the dead server's pipe within the test's 20 s."""
    client, waiting = _waiting_sim(tmp_path, lock_dir, request, every="30")
    client.proc.kill()
    assert client.proc.wait(timeout=20) == -9
    end = time.monotonic() + 20
    while _alive(waiting):
        assert time.monotonic() < end, "the command outlived the server"
        time.sleep(0.05)


def test_a_path_with_a_nul_byte_is_refused_in_1_line(tmp_path, lock_dir, request):
    """A NUL byte cannot be in a path. The call is refused as a tool execution error, in 1 line that
    names the argument (server/tools, "Error Handling"), not answered with a protocol error."""
    client = served(tmp_path, lock_dir, request)
    client.start()
    for args, named in (({"project": "x\u0000"}, "project"), ({"out": "x\u0000"}, "out")):
        reply = client.call("tools/call", {"name": "drc", "arguments": args})
        assert "result" in reply, reply
        lines = tool_text(reply["result"])
        assert reply["result"]["isError"] is True and len(lines) == 1, lines
        assert lines[0].startswith(f"refused: {named} ") and "not a path" in lines[0], lines
    assert client.close() == 0


def test_a_count_with_a_zero_fractional_part_is_a_whole_number(tmp_path):
    """The schema says `"type": "integer"`, which "matches any number with a zero fractional part" (JSON
    Schema 2020-12, draft-bhutton-json-schema-validation-01, 6.1.1 "type"). So 3.0 passes as 3, and
    3.5 and -1.0 are refused."""
    import mcpserver

    words = mcpserver.command_line(tmp_path, "autoroute", {"passes": 3.0})
    assert words == ["autoroute", str(tmp_path), "--passes", "3"]
    for value in (3.5, -1.0):
        with pytest.raises(mcpserver.Refused):
            mcpserver.command_line(tmp_path, "autoroute", {"passes": value})


STUB = """\
import subprocess, sys
child = subprocess.Popen(["sleep", "120"])
print(child.pid, flush=True)
child.wait()
"""


class Collector:
    """The server's stdout in the test's own process: each message it writes, parsed, into a queue."""

    def __init__(self):
        self.inbox: queue.Queue = queue.Queue()

    def write(self, data: bytes):
        self.inbox.put(json.loads(data))

    def flush(self):
        pass


def test_a_cancel_stops_the_commands_whole_process_group(tmp_path, request):
    """A command's engines are its children. A cancel stops them with it. A stub in place of the CLI
    starts `sleep 120`, prints its pid and waits on it; after the cancel the sleep is gone too, not only
    the stub."""
    import mcpserver

    stub = tmp_path / "stub.py"
    stub.write_text(STUB)
    out = Collector()
    server = mcpserver.Server(tmp_path, out=out, cli=stub)
    call = {"name": "doctor", "arguments": {}, "_meta": {"progressToken": "g"}}
    server.handle(json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": call}).encode())
    told = out.inbox.get(timeout=20)
    pid = int(told["params"]["message"])
    request.addfinalizer(lambda: _kill(pid))
    assert _alive(Path(f"/proc/{pid}"))
    cancel = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}
    server.handle(json.dumps(cancel).encode())
    end = time.monotonic() + 20
    while _alive(Path(f"/proc/{pid}")):
        assert time.monotonic() < end, "the command's child outlived the cancel"
        time.sleep(0.05)


def _alive(proc: Path) -> bool:
    """A process that exists and is not a zombie waiting to be reaped."""
    try:
        stat = (proc / "stat").read_text()
    except OSError:
        return False
    return stat.rsplit(")", 1)[1].split()[0] != "Z"


def _kill(pid: int):
    try:
        os.kill(pid, 9)
    except OSError:
        pass


def _runs_sim(proc: Path, root: Path) -> bool:
    try:
        words = (proc / "cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    return b"sim" in words and str(root).encode() in words and str(CLI).encode() in words


@needs_kicad
def test_erc_and_drc_answer_with_the_commands_own_lines_and_exit_code(tmp_path, lock_dir, request):
    """The tool runs the command: its lines are the lines `workcenter erc` and `workcenter drc` print
    on the same folder, run times aside, then `exit code N`. pass-rc-divider passes ERC: exit 0;
    fail-drc-clearance fails DRC on 1 clearance (0.0500 mm against 0.2000 mm): exit 1, isError true."""
    root = tmp_path / "root"
    shutil.copytree(BOARDS / "pass-rc-divider", root / "rc")
    shutil.copytree(BOARDS / "fail-drc-clearance", root / "drc")
    env = dict(os.environ, WORKCENTER_LOCK_DIR=str(lock_dir))
    expected = {}
    for tool, folder in (("erc", "rc"), ("drc", "drc")):
        run = subprocess.run(
            [sys.executable, str(CLI), tool, str(root / folder), "--out", str(tmp_path / f"cli-{tool}")],
            capture_output=True,
            text=True,
            env=env,
        )
        expected[tool] = (untimed((run.stdout + run.stderr).splitlines()), run.returncode)
    assert expected["erc"][1] == 0 and expected["drc"][1] == 1
    client = served(root, lock_dir, request)
    client.start()
    for tool, folder in (("erc", "rc"), ("drc", "drc")):
        result = client.call("tools/call", {"name": tool, "arguments": {"project": folder}}, timeout=120)[
            "result"
        ]
        lines, code = expected[tool]
        assert untimed(tool_text(result)) == [*lines, f"exit code {code}"]
        assert result["structuredContent"]["exitCode"] == code
        assert result["structuredContent"]["command"].startswith(f"workcenter {tool} ")
        assert result["isError"] is (code != 0)
        assert json.loads(result["content"][1]["text"]) == result["structuredContent"]
    assert "clearance 0.2000 mm; actual 0.0500 mm" in tool_text(result)[1]
    assert client.close() == 0 and client.bad == []


@needs_ngspice
def test_a_gate_that_waited_on_the_lock_finishes_with_its_verdict(tmp_path, lock_dir, request):
    """The other half of not blocking: a `sim` call that waited while the lock was held runs when it is
    free and answers with the command's own verdict, exit 0 on pass-rc-divider. A ping sent while it
    waited is answered before it."""
    root = tmp_path / "root"
    shutil.copytree(BOARDS / "pass-rc-divider", root)
    env = dict(os.environ, WORKCENTER_LOCK_DIR=str(lock_dir))
    env.pop("WORKCENTER_LOCK_TICKET", None)
    holder = subprocess.Popen(
        [sys.executable, str(LOCK_PY), "hold", "--what", "test holder", "--", "sleep", "3"], env=env
    )
    request.addfinalizer(lambda: (holder.kill(), holder.wait()))
    end = time.monotonic() + 20
    while not list(lock_dir.glob("*.held")):
        assert time.monotonic() < end, "the holder never took the lock"
        time.sleep(0.05)
    client = served(root, lock_dir, request)
    client.start()
    sim = client.request("tools/call", {"name": "sim", "arguments": {"project": ".", "nominal": True}})
    pong = client.request("ping")
    first = client.wait_for(lambda m: m.get("id") in (sim, pong) and "result" in m)
    assert first["id"] == pong
    result = client.answer(sim, timeout=300)["result"]
    lines = tool_text(result)
    assert any("waiting on the engine lock" in line for line in lines)
    assert any(line.startswith("PASS   sim") for line in lines), lines
    assert lines[-1] == "exit code 0" and result["structuredContent"]["exitCode"] == 0
    assert result["isError"] is False
    assert client.close() == 0 and client.bad == []
