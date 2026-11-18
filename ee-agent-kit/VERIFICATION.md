# VERIFICATION.md — one command answers "is this repo healthy"

`make verify` runs `verify/verify.sh`. It first waits its turn on the
machine's engine lock and holds it to its end (`tools/enginelock.py`); the
commands its tests start, in every shard, are its children and do not
wait. Then, in order, the steps with no engine first so that their
failures show early:

1. Lint — `shellcheck` on every shell script, `ruff check` and
   `ruff format --check` on `tools/`, `tests/` and `verify/`.
2. Kit checks — no unfilled placeholder outside `ee-agent-kit/SETUP.md`;
   every `SKILL.md` has frontmatter with `name` and `description`;
   `ee-agent-kit/skills/*` and `.claude/skills/*` are identical;
   `WORKCENTER.md` exists at the root.
3. Doctor — `python3 tools/workcenter doctor`. A missing required engine
   (kicad-cli 10, ngspice, python 3.12) fails here, before any test.
4. Tests — `verify/testshards.py run`: the files of `tests/` in 1 pytest
   process per processor, split by the seconds `verify/shards.csv` gives
   each (`verify/README.md`). The step is red when a shard fails, when a
   shard ends before pytest's end of session, when the collection in 1
   process fails, when the ids the shards ran are not the ids 1 process
   collects, or when a test's skip or xfail marks differ between its
   shard and 1 process. The fixture boards under `tests/boards`
   are the gate tests: `pass-rc-divider` must be GREEN,
   `fail-drc-clearance` must stop at DRC with a `clearance` violation,
   `fail-sim-spec` must fail its `vout` bound. KiCad-dependent tests skip
   loudly without `kicad-cli`; step 3 already failed in that case.

The last lines print each step's seconds; step 4 prints each shard's
seconds and the 10 slowest test files.

## Rules

- CI runs **the same command** as local. No CI-only logic.
- A gate that can't run in some environment **skips loudly**, never
  passes silently.
- New behavior lands with its gate in the same PR whenever feasible.
- A feature's completion promise (ROADMAP.md) should be backed by a gate
  here whenever it can be — evidence that keeps proving itself beats
  evidence produced once.
- Fixing a flaky or broken gate is always in scope, for any task.
- A new engine or gate lands with a fixture board that turns it red and
  one that keeps it green.
