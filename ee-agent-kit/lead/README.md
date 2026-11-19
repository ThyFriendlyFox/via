# The lead's tools

The files the skills `lead`, `land` and `user-round` name. Each takes
its paths as arguments or environment variables; none holds a path of a
machine or a session, and none names a model.

| File | Does | Skill |
|---|---|---|
| `landed.py` | Reads the helpers' journals and says which piece of work has finished its build, its reviews and its fixes, and what each other piece waits for. | `lead`, step 10 |
| `gate-and-push.sh` | For a machine with no CI (a fork without Actions, an offline machine): takes the lock, waits until no helper's engine or test runs, runs `make -C <tree> verify` alone, and pushes only on `VERIFY GREEN` with the tree unchanged. Where CI runs, a landing is pushed on `make check` and CI's `verdict` gates it instead (`land`, steps 5 and 6). | `land`, step 18 |
| `quiet.py` | Prints each process that is a helper's engine, test run or script; nothing means quiet. A script that only waits is left out: a shell script with only a `sleep` below it, and a Python script with nothing below it that sleeps and used no processor time for 2 s (`time.sleep`, M277). `gate-and-push.sh` calls it. | `land`, step 18 |
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

An agent id names 1 helper in 1 journal; 2 journals may use the same
ids. 1 id started under 2 labels in 1 journal is refused.

A review counts when its result gives a `verdict` that is not empty and
a list `findings`; a fix, when it gives a list `fixed` and, if it gives
`not_fixed`, a list. Any other result waits, named in 1 line. A review
started again counts every result it got: the findings are added up, and
it is `not sound` when 1 result says so. A build or a fix with 2 results
lands on neither: read both, and land the head that is on the branch by
hand.

## Running them

```sh
python3 ee-agent-kit/lead/landed.py <scratch>/roadmap/landed.json <journal>...
GATE_DIR=<scratch> bash ee-agent-kit/lead/gate-and-push.sh <tree> <branch> <commit> <lease> <label> [remote branch]
python3 ee-agent-kit/lead/quiet.py <pid whose tree is left out> [folder]...
```

`landed.py` exits 0 when a piece finished since its last run, 1 when none
did, 2 on a bad call or a journal it cannot read. `gate-and-push.sh`
exits 0 when it pushed, 1 on a red gate, 2 on a bad call (no `GATE_DIR`,
or no such folder), 3 when it stopped (HEAD, branch, tree or lock), 4
with no quiet in time, 5 when the push failed (the remote branch is no
longer the lease, or 5 tries failed), 6 when the quiet check failed. A
gate stopped by a signal ends `make verify` and every process it started
before it removes the lock. Its header names its environment variables.
`tests/test_lead.py` holds all 3 and the 3 scripts.

## Where the gate runs

The health gate runs on GitHub, in CI's `full` job
(`ee-agent-kit/CI.md`, "Where the health gate runs"). A landing is pushed
to the work branch on `make check`: `make lint` and the kit's own tests,
with no engine and no lock. Nothing from the work branch is merged,
released, or used as the start of other work until CI's `verdict` is
green on that exact commit. So a landing does not need the machine alone,
and the helpers go on working while it is gated. `gate-and-push.sh` and
the rules below are for a gate on the machine, where there is no CI.

A gate in the background gets a time limit of 2 hours: it waits for the
engine lock and for quiet before its run, and 1 such wait took 50 minutes
(PROCESSES.md P31 step 12, M273). A helper's loop of runs looks for
`GATE.lock` in `GATE_DIR` before each run and waits in a sleep while it
exists (P31 step 11). While a gate runs, `quiet.py` and
`gate-and-push.sh` are not edited in place: the new version is written
beside the old one and moved into place in 1 step, or the gate is
stopped first (P31 step 13, M278).
