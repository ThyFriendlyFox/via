# The lead's tools

The files the skills `lead`, `land` and `user-round` name. Each takes
its paths as arguments or environment variables; none holds a path of a
machine or a session, and none names a model.

| File | Does | Skill |
|---|---|---|
| `landed.py` | Reads the helpers' journals and says which piece of work has finished its build, its reviews and its fixes, and what each other piece waits for. | `lead`, step 10 |
| `gate-and-push.sh` | Takes the lock, waits until no helper's engine or test runs, runs `make -C <tree> verify` alone, and pushes only on `VERIFY GREEN` with the tree unchanged. | `land`, step 7 |
| `quiet.py` | Prints each process that is a helper's engine, test run or script; nothing means quiet. `gate-and-push.sh` calls it. | `land`, step 7 |
| `workflows/roadmap-lane.js` | An example for a host that runs workflow scripts: build, attack and fix, 1 item per helper, rounds of items. | `lead`, steps 5 to 9 |
| `workflows/second-attack.js` | The same: a second review of a piece the first called `not sound`, and its fix. | `lead`, step 9 |
| `workflows/user-round.js` | The same: 3 users of different sizes on 1 board spec, and the ranking of what they hit. | `user-round`, steps 3 to 6 |

A host that runs no workflow scripts does the steps of the skill by hand:
it starts each helper with the brief the script would send, waits for its
report, and keeps the journal below itself.

## The journal

`landed.py` reads files of JSON lines, 1 event per line:

```
{"type": "started", "agentId": "a1", "label": "build:r3"}
{"type": "result", "agentId": "a1", "result": {"head": "<40 hex>", "summary": "...", "tests_last_line": "..."}}
```

A label is `<stage>:<branch>`. The stages are `build`, `attack`, `fix`,
`attack2` and `fix2`, as the 3 scripts name their helpers. A result is
the helper's report: an object, the same as JSON text, or `null` when the
helper ended with none. A host whose helpers keep no such journal writes
these lines itself, 1 when a helper starts and 1 when it reports.

## Running them

```sh
python3 ee-agent-kit/lead/landed.py <scratch>/roadmap/landed.json <journal>...
GATE_DIR=<scratch> bash ee-agent-kit/lead/gate-and-push.sh <tree> <branch> <commit> <lease> <label> [remote branch]
python3 ee-agent-kit/lead/quiet.py <pid whose tree is left out> [folder]...
```

`landed.py` exits 0 when a piece finished since its last run, 1 when none
did, 2 on a bad call. `gate-and-push.sh` exits 0 when it pushed, 1 on a
red gate, 3 when it stopped (HEAD, branch, tree or lock), 4 with no quiet
in time, 5 when the push failed 5 times, 6 when the quiet check failed.
Its header names its environment variables. `tests/test_lead.py` holds
all 3 and the 3 scripts.
