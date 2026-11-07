# Brief: {board} {version} verification package, {task}

<!-- The lead's template for helpers who work on one verification package at
     the same time (PROCESSES.md P28, the verification skill's "Helpers").
     Copy BRIEF.md and FACTS.md into one folder of the session's scratchpad,
     never into the project: `workcenter verify --init` leaves both out.
     Replace each {name} with its value: {board}, {version}, {previous}, {task},
     {repo} (the project repository's absolute path), {workcenter} (the
     workcenter's absolute path) and {scratch} (the folder that holds this
     file). Write every path absolute and in backticks. Fill each "fill"
     comment, delete this comment, then run the checks in the verification
     skill's "Helpers" section before you send the brief. -->

You are updating part of the verification package of {board}, version
{version}, in the repository at `{repo}`. The package is
`{repo}/{version}/verification/`. <!-- fill: its state, for example "It was copied from {previous} and still describes {previous} in places." -->
Your job is to bring the files assigned to you below up to {version},
exactly and checkably.

## Your files

Each helper owns the files in its row and changes nothing else. A file you
do not own may be wrong: report it, do not fix it.

| Helper | Files it owns | Decks it explains |
|---|---|---|
| <!-- fill: one row per helper --> | <!-- fill: absolute paths --> | <!-- fill: `sim/<deck>.cir` --> |

## The facts

Every fact of this round is in one file, `{scratch}/FACTS.md`. This brief
copies none of them (M98).

- Read FACTS.md before you start and again before you report.
- Each row names the file that holds the fact. Where FACTS.md and that file
  differ, the file wins: use it, and report the difference.
- When a fact changes during the work, the lead changes its file first, then
  its row and the change log at the top of FACTS.md, and sends every helper
  one line that names the row. Read the row again before you go on.

## Read first

- The verification skill: the package's rules, headings, citation rules,
  nodal analysis and traps:
  `{workcenter}/.claude/skills/verification/SKILL.md`.
- The requirements, already updated: use their IDs and limits, and do not
  edit the file: `{repo}/{version}/verification/requirements/README.md`.
- Your decks and their bounds: `{repo}/{version}/sim/<deck>.cir` and
  `<deck>.expect.json`. The decks are final. Do not edit a deck, an expect
  file, a design file or the firmware. If a deck looks wrong, say so in
  the report.
- The design source: `{repo}/{version}/design.py`. <!-- fill: each nested board's design.py -->
- The firmware's constants: <!-- fill: the absolute path of the file that holds them -->.
- The datasheets: `{repo}/library/` by maker, and
  `{repo}/{version}/datasheets/`. Read each section, table and figure number
  from the PDF's text (`pdftotext -layout <file> -`), never from memory (M72).

Every path in this brief and in FACTS.md is a file that exists now (M96).
A document still to be filed is named by the path where it is today, never
by the path it will get.

## The numbers

A number comes from a run, never from this brief, FACTS.md or memory.

- Every deck: `workcenter --json sim {repo}/{version} --out <a new folder
  of your own in the scratchpad>`. The measures are in
  `details.decks.<deck>.measures`. Each helper writes to its own `--out`:
  runs that share a folder mix their reports (M73).
- One deck by hand: only `workcenter sim {repo}/{version} --deck <name>
  --keep --out <your folder>`. It prepares the deck as the gate does (the
  vendor models' translation and the PSpice mode) and prints the one
  command that runs it again. A bare `ngspice -b` reads a vendor model
  differently (M94).
- A track's resistance: `workcenter inspect resistance <board file> <NET>
  --from <REF.PAD> --to <REF.PAD>`, which takes each layer's copper
  thickness from the board's stackup (M93). Never an estimate.
- `workcenter verify` compares every number quoted beside a `deck.meas` in a
  table with a fresh run, to half a unit of its last quoted digit, SI
  prefixes allowed (`4.7 mV`, `125 ns`). Quote to the digits the run
  supports.

## Questions

The lead asks and the deck answers. This brief states no behaviour that a
run has not shown (M95).

<!-- fill: each question with the measure or the vector that answers it, for example "How much current do C5 and C15 deliver through F1 at the heater's edge? Read i(vf1) from 0 to 1 µs." Never write an expectation, such as "C5 barely takes part". -->

Answer each question from the deck's measures or waveforms, and name the
vector or the measure you read.

## Rules

- Never use `cd`. Use absolute paths, and `env -C <dir> <command>` to run a
  command in a folder.
- No git command that changes anything: no commit, checkout, stash, reset or
  push.
- No AI model names or identifiers in any file you write.
- Keep the package's voice: plain, short sentences, measured claims, every
  equation with its source. Read a section before you change it; change
  what {version} changed and keep what still holds.
- Each writeup keeps the headings Purpose, Circuit, Inputs, Outputs,
  Expected, Results, "Why it is required, and what is not", Nodal analysis,
  Sources, Re-run, and names each deck it explains as `sim/<deck>.cir`.
- A hand analysis agrees with the deck. When the circuit changed, redo the
  equations it touches, with numbers, and say where {previous} differed.
- A reading behind a series part (a fuse, a shunt, a switch, a track) lists
  every current through that part, in both directions, each at its corner
  (M92).
- A fuse, or any series part, is checked at every event that moves charge
  through it: each edge, surge, plug-in and fault, not one of them (M95).
- A requirement the design fails stays a FAIL, with its size and its
  proposed fix. Never soften it.
- "{previous}" in a sentence that tells the history is fine. A sentence that
  describes the board describes {version}.

## Report

Report at the end, in this order:

1. The files you changed.
2. Every number you changed, old → new, with the measure or the
   calculation it comes from.
3. The answer to each question, with the measure or the vector you read.
4. Anything that looks wrong in a deck, a requirement, FACTS.md or another
   helper's file, with the evidence.
5. The lines of `workcenter verify {repo}/{version} --out <your folder>`
   that name your files. There must be none. Problems in other files are
   other helpers' work in progress: leave them.
6. Anything you could not source.
