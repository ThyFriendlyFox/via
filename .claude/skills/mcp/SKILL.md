---
name: MCP
description: Serves Via's doctor, gates, erc, drc, sim, export and autoroute to a host that is not Claude Code, as MCP tools over stdio, each tool running its own command and answering its lines and exit code.
---

# MCP

A host that is not Claude Code (another agent, an editor, a desktop app)
reaches the gates through MCP, the Model Context Protocol. `workcenter mcp`
is an MCP server on stdio. It offers 7 tools: `doctor`, `gates`, `erc`,
`drc`, `sim`, `export` and `autoroute`. Each tool runs the command of its
name, `workcenter <tool> <project> ...`, and answers with the lines the
command prints and its exit code. Nothing in the server judges a board.

The server speaks MCP revision 2025-11-25, the last revision with the
`initialize` handshake. A host of revision 2026-07-28 that also speaks the
older revisions falls back to it; a host that speaks only 2026-07-28 and
later does not. stdio only: no HTTP, no authentication.

## Inputs

| Input | Holds |
|---|---|
| ROOT, the server's 1 argument | The folder the tools may reach: 1 project, or a repository of versions (`v0.1/` to `v0.16/`). Every path a call names must lie inside it. ROOT is the only boundary, so the server refuses `/` and the home folder. |
| A tool's `project` | The project folder or a KiCad file, relative to ROOT. Default `.`. |
| `out`, `dsn`, `fab` | Paths inside ROOT. With no `out`, the server names `<project>/build` itself and holds it inside ROOT too: a `build` link out of ROOT is refused. `fab` may also be the name of a rule set in Via's `rules/`. |
| `jobs`, `passes`, `threads`, `timeout` | Whole numbers from 0 to the maximum in the tool's schema: 64, 1000, 64 and 86400 seconds. |

## Steps

1. Check the engines: `workcenter doctor`.
   - A line `ok` for an engine: that engine is there.
   - A line `MISSING` (a required engine) or `absent` (an optional one): the
     tools that need it answer a skip with exit code 2. Install it with
     `install.sh`, never another way.
2. Check the server by hand, from a shell, with 2 messages on its stdin:

   ```sh
   printf '%s\n' \
     '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"me","version":"1"}}}' \
     '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
     | workcenter mcp <project>
   ```

   - 2 lines of JSON come back: `"id":1` names `"protocolVersion":"2025-11-25"`,
     `"id":2` lists the 7 tools. Go on.
   - `workcenter mcp <project>: not a folder` on stderr, exit code 2: name a
     folder that exists.
   - `workcenter mcp <ROOT>: too wide a root` on stderr, exit code 2: ROOT
     was `/` or the home folder. Name the project or the repository.
   - A line on stderr that a SIGKILL to this server leaves its commands
     running: this system has no prctl PR_SET_PDEATHSIG. The server works;
     stop it with SIGTERM, not SIGKILL.
3. Give the host the server's command line. A host takes a command and its
   arguments; name the CLI by its full path, since a host may start it from
   any folder: `python3 <workcenter>/tools/workcenter mcp <project>`.
   - The host lists 7 tools: go on.
   - The host lists none: read its log. The server writes nothing but MCP
     messages to stdout; a message on its stderr is the CLI's own.
4. Call a tool from the host. Each answer is the command's lines, then the
   line `exit code N`. Read the lines as the command's own skill says:
   `board-gates` for `gates`, `erc`, `drc` and `export`, `simulate` for
   `sim`, `autoroute` for `autoroute`.
   - `exit code 0`: the command passed. `isError` is false.
   - `exit code 1`: the command failed. Each failure is its own line under
     the gate's line. `isError` is true.
   - `exit code 2`: a gate was skipped: an engine is missing. It is not a pass.
   - 1 line `refused: <what> <path> is outside <ROOT> ...`: the call named a
     path outside ROOT. Nothing ran. Name a path inside ROOT, or start the
     server on a wider ROOT.
   - 1 line `refused: <tool> takes ..., not ...` or `refused: <name> must be
     ...`: an argument the tool does not take, or of the wrong kind. Nothing
     ran. Fix the argument.
   - 1 line `refused: <what> "<value>" is not a path: ...`: the value cannot
     be a path, for example it holds a NUL byte. Nothing ran.
   - 1 line `refused: N calls are running or waiting, the most this server
     holds`: 4 commands run and 32 calls wait. Nothing ran. Call again once
     1 is answered.
   - A JSON-RPC error -32600 `id ... is in use by a call`: the host reused
     the id of a call still running. Nothing ran. Send a new id.
5. At most 4 commands run at once; a further call waits for a slot, and a
   long tool (`gates`, `sim`, `export`, `autoroute`) then waits its turn on
   the machine's engine lock, as the command does. Meanwhile the server still
   answers `ping` and other calls. A line on stdin longer than 4 MiB, or
   nested deeper than Python's JSON reader goes, is answered -32600 and the
   session goes on.
   - With `_meta.progressToken` on the call, each line the command prints
     comes as 1 `notifications/progress`; `waiting on the engine lock` is
     such a line.
   - To stop a call, the host sends `notifications/cancelled` with its id.
     The command and its engines stop, and no answer comes for that id.
6. End the session: the host closes the server's stdin. Calls still running
   are answered first, then the server exits 0. A SIGTERM stops every
   command it started and the server exits 143; a SIGINT (Ctrl-C) does the
   same and exits 130. Each command gets SIGTERM, and a SIGKILL after 10 s
   if it is still there; the server exits once they are gone. On Linux a
   SIGKILL to the server stops each command too: the command gets SIGTERM
   when its parent dies. On another system a command can outlive a server
   killed by SIGKILL, and the server says so on stderr and in its
   `initialize` instructions.

## What it does not do

- It holds no state between calls: each call is 1 run of 1 command.
- It offers no resources, no prompts and no HTTP transport.
- It runs nothing outside ROOT, and writes only where the command writes
  (`<project>/build` or `out`), both held inside ROOT, links followed.

## Tests

`tests/test_mcp.py` drives the server with a scripted JSON-RPC session over
a pipe: the 7 tools and their schemas, each option a flag of its command, the
refusals, the protocol's error codes, a `ping` answered while `sim` waits on
the engine lock, a cancel that stops the command's whole process group and
sends nothing after it, stdin closed, SIGTERM, SIGINT and SIGKILL, SIGKILL
after SIGTERM for a command that ignores it, the bound of 4 running commands
and its queue, a reused id, a line too deep or too long, the default `build`
held inside ROOT, and `erc` and `drc` answering the same lines and exit codes
as the commands.
