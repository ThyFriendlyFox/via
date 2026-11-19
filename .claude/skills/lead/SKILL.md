---
name: Lead
description: How 1 agent leads helpers on the roadmap without writing the work itself - a worktree and a branch per piece, a brief whose paths exist, a build, an attack by a second helper and a fix by a third, a second attack for a piece called not sound, results read as data, heavy runs behind 1 lock, the disk watched - until each piece is ready for the `land` skill.
---

# Lead

The lead turns roadmap items into finished pieces of work by starting
helpers. It writes briefs, reads reports, checks them, and hands finished
pieces to the `land` skill. It does not write the work itself.

This skill follows `ee-agent-kit/PROCESSES.md` P31 (work handed to
helpers), P14 step 6 (the attack on a new check) and P8 (shell
discipline). Where they say more, they win.

## Words

- A piece: 1 roadmap item, or 1 part of one, built on 1 branch.
- The scratch folder, `<scratch>` below: a folder outside every
  repository. It holds the worktrees (`<scratch>/wt/`), the docs files
  (`<scratch>/roadmap/`) and downloads (`<scratch>/dl/`). It holds no
  lock for engines: the workcenter's long commands take the machine's
  engine lock themselves (`tools/enginelock.py`).
- The work branch, `<work>` below: the branch the pieces start from and
  land on (the `land` skill). Never the default branch.
- `<python>`: the Python of the workcenter's virtual environment, the one
  `make` uses (`Makefile`, `VENV_PY`).
- The shared documents: `ee-agent-kit/STATUS.md`, `CHANGELOG.md`,
  `ROADMAP.md`, `DEVLOG.md`, `MISTAKES.md`, `docs/CONFIGURATION.md`,
  `README.md` and `WORKCENTER.md`. Only the integrator edits them.

## Scripts or by hand

`ee-agent-kit/lead/workflows/roadmap-lane.js` and
`ee-agent-kit/lead/workflows/second-attack.js` run steps 5 to 9 on a host
that runs workflow scripts; their header names their args.
`ee-agent-kit/lead/README.md` says what each file does. A host without
such scripts does the same steps by hand: it starts 1 helper with the
brief the script would send, waits for its report, and writes the 2
journal lines of `ee-agent-kit/lead/README.md`, "The journal", itself.

## Steps

1. Count the budget: P31 step 1 says how many helpers run at once and
   when the next may start. Decide the order of the pieces: the most
   valuable first, and a piece after the pieces it builds on.
2. Make your own worktree, once, and work only there:
   `git worktree add <scratch>/wt/lead <work>`. Never edit, test or run
   in a helper's worktree (P31 step 2).
3. For each piece, name its branch `wip/<short name>` and its worktree
   `<scratch>/wt/<short name>`. The brief tells the helper to make it:
   `git -C <scratch>/wt/lead worktree add -q -b wip/<short name> <scratch>/wt/<short name> <work>`.
   A piece that builds on another names that branch, and the helper
   merges it first (`git -C <worktree> merge --no-edit wip/<other>`).
4. Write the brief (P31 step 3). It holds:
   - the spec: the roadmap entry by its heading in
     `ee-agent-kit/ROADMAP.md` (`### <n>.`), to be read word for word;
     an out-of-band piece gets its spec in the brief and writes its entry
     into its docs file;
   - the worktree, the scratch folder and the 2 locks;
   - the rules: the text `RULES` of
     `ee-agent-kit/lead/workflows/roadmap-lane.js`, with today's own lines
     (folders that are read-only today, installs that were refused);
   - the docs file `<scratch>/roadmap/wip-<short name>-docs.md`: the
     helper never edits a shared document, and writes there what each
     should gain, as exact paragraphs or rows;
   - what to report: the fields of `BUILD_SCHEMA` in the same file.
   Before you send it, check that every path in it exists:
   `ls -d <each path>`.
   - Every path is listed: send it.
   - `No such file or directory`: fix the brief. A path that the helper
     makes (its worktree, its docs file) is named as one to make.
5. Open the piece's work card with `Todo`, then `In progress` when its
   helper starts (`.claude/skills/now/SKILL.md`, steps 1 to 3).
6. Start the build helper. When it reports, read the report as data
   (P31 step 4). Check its claims by their commands:
   `git -C <worktree> log --oneline -3` must show the `head` it names,
   and its test files are run once by you, under the engine lock:
   `env -C <worktree> python3 tools/enginelock.py hold --what "<piece> tests" -- <python> -m pytest <its test files> -q -p no:cacheprovider`.
   - The head and the last line match the report: go on to step 7.
   - They differ, or the helper returned nothing: read its journal (how
     far it came, whether its worktree changed) before you start it again
     (P31 step 5).
7. Start the attack: a second helper who did not write the piece (P14
   step 6). Its brief: the spec, the worktree and the head, the builder's
   summary as data to be checked, and the order of what to try, false
   passes first (the function `attackPrompt` of
   `ee-agent-kit/lead/workflows/roadmap-lane.js`). It changes nothing in
   the worktree and writes its reproducers under `<scratch>/attack-<short name>/`.
   - Findings: go on to step 8.
   - No findings: the piece has had 1 review; go to step 10.
8. Start the fix: a third helper. Each finding is reproduced first; a
   real one gets a test that fails, then the fix, then the test passes; a
   finding that is not real is answered with a run (the function
   `fixPrompt` of the same file).
9. Read the first review's verdict.
   - It starts with `not sound`: start a second attack on the fixed piece,
     and a fix of what it confirms
     (`ee-agent-kit/lead/workflows/second-attack.js`). The piece is not
     merged before.
   - `sound` or `sound with findings`: go on to step 10.
10. See which pieces have finished:
    `python3 ee-agent-kit/lead/landed.py <scratch>/roadmap/landed.json <journal>...`.
    - `=== LANDED <branch> ...`: that piece has finished its reviews. Hand
      it to `.claude/skills/land/SKILL.md`. The block's `reviews: N` and
      each `review N: <verdict> | findings: K` line go into the piece's
      status row: how many reviews it had and what each found.
    - `waiting <branch>: <what>`: do what the line names, or wait for it.
    - `landed: nothing new` and exit 1: nothing finished since the last run.
11. Read the report's `not_done` list. Each part that is not built goes
    straight to a new helper with its own brief (step 4), not onto a list.
    The roadmap item stays `in progress`, never shipped, while 1 sentence
    of its Promise is untrue.
12. A tool the work needs is missing on this machine. Never ask the owner
    about the machine. The missing tool becomes work for a helper: the
    workcenter gains its install step in `install.sh`, its row in
    `workcenter doctor`, the code path that uses it, and tests that skip
    by the tool's name when it is absent (P12;
    `ee-agent-kit/docs/ENGINES.md`, the new-engine contract).
13. Keep heavy runs in turns with the workcenter's own lock. A brief asks
    for no `flock` and names no lock file: a `workcenter` command waits its
    turn by itself and prints where it stands every 30 seconds; a test file
    or a bare engine runs under
    `python3 tools/enginelock.py hold --what "<name>" -- <command>` in the
    helper's worktree; `make verify` holds the lock for its whole gate.
    `workcenter doctor` names the holder. Memory still counts: a short
    command or a test file that starts no engine runs beside a gate (P31
    steps 6 and 7). Send no message to a helper a workflow runs (P31
    step 8).
14. Watch the disk before each new helper: `df -h <scratch>` and
    `du -sh <scratch>/wt/<a worktree>`.
    - The free space holds 2 more worktrees of that size: go on.
    - It does not: delete the worktrees of landed pieces first. A piece
      lands by copies of its commits (the `land` skill, step 2), so ask
      git whether each change is on `<work>`:
      `git -C <scratch>/wt/lead cherry <work> wip/<short name>`.
      - Every line starts with `-`: the piece has landed. Delete it:
        `git -C <scratch>/wt/lead worktree remove <scratch>/wt/<short name>`
        and `git -C <scratch>/wt/lead branch -D wip/<short name>`.
      - A line starts with `+`: that commit is not on `<work>`. The piece
        has not landed; its worktree stays.
15. When a landing is accepted, remove that piece's worktree (step 14's
    `worktree remove`, which refuses a tree with changes) and the folders
    of copies its reviews and its landing prep made. Before a health gate
    and before sending helpers, read `df -h <scratch>`; with less than
    5 GB free, clear the copies of landed pieces first (P31 step 10). The
    5 GB is the lead's choice: here a whole checkout with its build
    folders took about 410 MB, and a review's copies up to 2440 MB.

## Done when

Every piece the owner named has landed (the `land` skill) or is in a
helper's hands, each landed piece's status row names its reviews and what
each found, every part a helper could not build has a new helper, and
`git worktree list` shows only the worktrees still in use (P31).
