# PROCESSES.md — the checklists you follow

Every process here exists because a mistake in `MISTAKES.md` cost real
time. They are binding the way `AGENTS.md` is: before you do a thing a
process names, you follow its steps, in order, and you do not call the
thing done until its "Done when" line holds. A process you cannot follow
is a blocker to report, not a step to skip.

`make verify` checks that every mistake names a process that exists and
that every process says when it is done.

Numbering is permanent. A process is never deleted; one that no longer
applies is marked retired with the date and the reason.

## P1 — Pad geometry before a hand route

When: before `d.track`, `d.via`, `reserve_vias`, or any coordinate that
must clear or land on a pad.

1. Read the footprint with `python3 tools/kicadgen.py footprint Lib:Fp`.
   List every pad, including a connector's unused ones (USB-C D+/D−,
   shield, mounting holes).
2. Generate the unrouted board and run `workcenter drc .`. The report
   names each pad with its board position. Those positions are the only
   source for a coordinate; never a position computed in your head. A
   part moved in the same change is regenerated and its pads read after
   the move; its tracks are never written in the edit that moves it.
3. A part on `B.Cu` is mirrored about the X axis: at rotation 0 its pad 1
   is on the left and its pads' y are flipped. Confirm against the DRC
   report, every time.
4. Track widths come from the pad: the widest track into a pad is pitch
   minus pad width minus 2 x clearance. A sense tap on a heavy net is
   drawn thinner with `width=`.
5. End a track on the pad centre, when the track is no wider than the
   pad. A wider track starts at the pad's edge on the side it leaves by:
   its round end reaches half its width past where it starts (M131). Route one net, run `workcenter drc .`,
   read every clearance line it prints, fix, then the next net.
6. A via is on every copper layer. Before writing `d.via`, look at what
   sits on the other face and the inner layers at that spot; then
   `workcenter design` lists every hand via that hits a pad, a track, a
   via, a keep-out or the edge (and exits 1). Fix those before routing.
7. A slot's or an oval pad's long axis comes from the placed board as
   well: the footprint file draws it at rotation 0. Read the hole's size
   and the footprint's rotation from the generated `.kicad_pcb`, turn the
   slot by that rotation (and mirror it for `B.Cu`), and draw a keep-out
   round it from those ends, never from the footprint file (M57).

Done when: the pre-routed board's DRC shows only unconnected items and
`workcenter design` reports no via problem.

## P2 — CI and install steps

When: writing or changing a workflow, `install.sh`, `environment/setup.sh`,
or any step that downloads, installs, or runs for more than a minute.

1. Output stays visible. Never `>/dev/null` a network or install step;
   print a line per fetched package, downloaded file, or finished stage.
   A filter in a pipe flushes per line (`grep --line-buffered`, `sed -u`,
   `awk` with `fflush()`), and its pattern is tested against the tool's
   real lines with a slow producer, each line arriving as it is printed
   (M86).
2. Non-interactive: `DEBIAN_FRONTEND=noninteractive`, `-y`, explicit
   `Dpkg::Options` for config prompts. Nothing may wait on a terminal.
3. A timeout on every long step (`timeout-minutes`, `curl --max-time`,
   `--connect-timeout`, `--retry`, apt's `Acquire::http::Timeout`).
4. Assume nothing about the host: not the default `python3`, not that
   `add-apt-repository` works, not that a keyserver answers quickly.
5. The verdict steps (gates, verify) come before convenience steps
   (artifact upload, render for humans). A convenience step is
   `continue-on-error: true` with a short retention; it must not turn a
   green verdict red.
6. After pushing a CI change, watch its run to the end. A run that
   looks stuck is read, not waited out: fetch the job log and find the
   last line printed.

Done when: the run is green, its log shows progress lines in every long
step, and no step depended on a terminal.

## P3 — Design rules before geometry

When: starting a board, or changing clearances, text sizes, or net
classes.

1. Set `d.rules`, `d.net_classes`, `track_width`, `clearance`,
   `edge_clearance`, via sizes first, with the fab's limits in the README.
2. Silkscreen text below 0.8 mm needs `min_text_height` and
   `min_text_thickness` in `d.rules` or the DRC flags every label.
3. Generate and run `workcenter erc .` and `workcenter drc .` on the
   unrouted board. Every error except unconnected items is a placement or
   rule mistake; fix it here, not after routing.
4. List the area rules before placing: each keep-out, what it forbids
   (tracks, vias, pours) and on which layers. A keep-out that forbids
   vias forbids them on every layer, since a via passes them all. Mark the
   via-free areas; a part placed in one is wired out on its own face to a
   via outside, so give it a path there.
5. Via sizes are rules too. The default via, each net class's and each
   hand via must meet the board's minimum hole (0.3 mm), minimum via
   (0.5 mm) and annular ring (0.1 mm), as `Design.board_rules()` gives
   them with `d.rules` laid over. The router places most vias, so the
   unrouted DRC of step 3 cannot see them; `workcenter design` checks the
   sizes (`Design.check_via_rules()`) and exits 1 before routing. A
   smaller via needs the fab's limit in the README and `d.rules` set to it
   (M46).
6. A rule file only adds floors. In KiCad a custom rule in a `.kicad_dru`
   overrides the board's own constraints and every net class's, so a
   rule with no layer and no condition replaces them all, looser or not.
   A fab's board-wide limit goes into the board's minimums
   (`Design.board_rules()`), never into the rule file; a rule that stays
   is at least as strict as the board setting it shadows. To prove it,
   take the rule file away from a copy of the board and run its DRC: no
   new error may appear (M62).

Done when: ERC 0/0 and DRC shows only unconnected items before the first
route, `workcenter design` reports no via problem, and the via-free areas
are named in a comment in the design file.

## P4 — Before every route

When: about to run `workcenter design --route` or `workcenter autoroute`.

1. Regenerate from the design file in the same command. A DSN from an
   earlier generation routes against parts that have moved and ships
   shorts that look like the router's fault.
2. P3's "Done when" holds on this exact design.
3. One route per design change. Its verdict is the exit code: `workcenter
   design` exits 1 on a hand via its own check refuses (a `via:` line)
   even though it writes every file (M85). Read the printed summary:
   segments, vias, rounds, islands. Then `workcenter drc .` for what
   stayed open.
4. kistack's placement checks before the route run at the board's own
   limits or stricter (`--track --clear --via --edge` for a board with a
   `.kicad_dru`). `--rules-override` is used only when the user asks for
   it (kistack's layout-placement skill); a result it produced is
   discarded (M66).
5. A route run only to evaluate (an archived version, a what-if) writes
   with `--out` to the scratchpad: without it `workcenter design` rewrites
   the project's KiCad files in place (M67).
6. A board of more than about 50 parts routes with `--passes 12` to 20
   and a `--timeout` of an hour, in the background. FreeRouting writes its
   session only when it ends, so a run the timeout stops leaves nothing:
   60 passes on 140 parts ran past the 15-minute default (M128).
7. A net that spans the board and carries a supply (a 12 V or 3.3 V
   rail to slots and connectors far apart, a regulator's input across a
   row of stages) is a pour on a layer the design gives it, drawn by the
   design, and goes to the router as a plane net: 1 pin, its vias
   obstacles. A motherboard's 4 supply nets as tracks ran 20 minutes
   without finishing a pass, twice (M129).

Done when: the DRC after the route lists 0 errors, or every remaining
error is named in the next design change.

## P5 — Docs name what exists

When: writing a tag, commit, branch, URL, run link, or path into a
README, devlog, status line, or PR body.

1. Confirm it on the remote first: `git ls-remote --heads --tags origin`,
   the run's page, the file in the merged tree.
2. A push that is refused (tags are refused by the session's git proxy
   with HTTP 403) changes the document, not the claim: name the commit
   hash instead of the tag.
3. Numbers in a document (segments, vias, warnings) are copied from the
   gate report of the committed board, not from an earlier run.

Done when: every name in the document resolves on the remote at the time
of the push.

## P6 — Pinning or changing an engine version

When: changing the version of kicad-cli, ngspice, FreeRouting, Java, or a
Python package in `requirements.txt`.

1. Reproduce the fault or the gain with the exact version, in the
   environment that showed it (proxied cloud session, GitHub runner).
2. Pin with the reason in `install.sh` (a comment with the symptom), a
   row in the landmine map, a CHANGELOG line, `docs/ENGINES.md`, and
   every table that repeats the default (`docs/CONFIGURATION.md`):
   `grep -rn` the old version string across the kit before the commit.
3. Keep a check that fails when the pin is lost: a doctor line, a test,
   or a checksum.

Done when: `make verify` is green with the new version and the landmine
map says why it is that version.

## P7 — Parsing another tool's output

When: reading a version string, a report, a session file, a log, or any
file another program wrote; or handing another tool a value whose sign or
axis it defines (a 3D model's rotation or offset, an export's origin).

1. Anchor the pattern on a token the tool guarantees (`version "`, a
   section header), never on free text that a proxy or a locale can
   change.
2. Derive scales and units from data the file contains (the placement
   block of a session), not from a declaration the writer may not honour.
3. Keep a real sample of the output in `tests/` and parse it there, one
   for every shape the format allows (a courtyard can be a rectangle,
   lines, a polygon or a circle).
4. A sign convention (which way a rotation turns, which axis is up) is
   read from the tool, never assumed: render or export once with an
   asymmetric body and look at the result before building on it. Write
   the convention down where its next use will read it (the skill for
   that tool), and use the written one instead of working it out again.
   KiCad 10's is in the `board-design` skill (M42, M47).
5. Keep a sample of what the tool prints when it fails, one for every way
   it fails: an error, a run it gave up on part of the way, a result it
   doubts. An exit code of 0 is not a verdict: ngspice exits 0 when one
   analysis aborts and a later one completes (M103).
6. A file a person writes for a tool to read (an expect file,
   `corners.json`, `frequency-plan.json`) is read against the keys it may
   hold. A key the reader does not know, a value of the wrong kind, and
   text that is not the format are each a problem named with its line,
   never passed over and never a traceback (M104).
7. A format with many spellings is read the way its tool reads it. List
   the spellings from the tool's manual before the reader is written: for
   a SPICE value a scale suffix, a continuation line, `r=`, an expression
   in braces, and `4k7`. Run each through the tool once and keep each as
   a test. Where the tool reads a spelling as another number and says
   nothing, the gate fails on that spelling (M117).

Done when: a test parses a real sample of each shape, failures among them,
and the parser's assumptions are written next to it.

## P8 — Shell discipline

When: every shell command.

1. Absolute paths, and no `cd`. Parallel tool calls share one shell, so a
   `cd` in one command is undone by the next without an error: a
   `cd X && ...` chain stops or runs in the wrong repository. Use
   `make -C`, `git -C`, `python3 /abs/script.py`, and absolute paths in
   every heredoc. In this repository a PreToolUse hook
   (`tools/hooks/no_cd.py`) refuses a Bash command that runs `cd`. A
   session opened outside this repository does not load it: check
   `workcenter doctor` for the "no-cd hook" and "test hook" lines, and
   where one is absent, ask the human whether to install both user-wide
   (`python3 tools/hooks/install_hooks.py`); never write their settings
   unasked.
2. `--help` before a flag you have not used in this session. `--json`
   is read before the command or after it (M114).
3. `pkill -x name`, never `pkill -f` with a pattern that matches the
   shell running it. The same holds for `pgrep -f` in a wait loop: the
   loop's own command line holds the pattern (M75). Wait on a file the job
   writes last, or on the PID it printed.
4. Long jobs run in the background with a log file; foreground commands
   stay under the tool's timeout.
5. A helper given a worktree writes only under it. A path is built from the
   worktree, never from its parent; before the report, `git -C <worktree>
   status` and a listing of the parent show nothing of the helper's outside
   it (M102).

Done when: the command ran where and how you meant, and the paths it
printed are the ones you expected.

## P9 — Scripted edits

When: changing a file with a script (python replace, sed) instead of the
Edit tool.

1. Run the formatter first (`ruff format`), so the anchors you copy are
   the text that is on disk.
2. Copy every anchor from the current file, not from memory or from an
   earlier version of this conversation.
3. Check every anchor before writing anything; a script that writes the
   first half and fails on the second leaves a file nobody has read. A
   file rewritten whole (a CSV through `csv.DictWriter`) is written to a
   new file first and moved over the old one only when the write ended
   (M76).
4. A range in a script (every x between two values) comes from the file
   it edits: read the outline or the coordinates' own extent, and after
   the run count what it moved against what lay in the range (M77).
5. A change of a few lines goes through the Edit tool after a Read.
6. Inside a quoted heredoc (`<<'EOF'`) the shell passes text through as
   written. Write no backslash escapes in it at all: `chr(10)` for a line
   break, real line breaks inside a triple-quoted string.
7. Tests are written with the Write or Edit tool, not appended by a
   script, and read back before they run: every assertion must be able
   to fail. The `no_script_test_edits.py` hook refuses a Bash command
   that writes under `tests/` (M43). The hook does not load in a session
   with two repositories; the step holds there all the same (M61). There
   `workcenter doctor` shows the "test hook" line as absent: say so to the
   human at the start, with the command that installs it (P8 step 1,
   M119).
8. A test's geometric expectation (inside or outside, how far, which
   side) is computed before it is written: one `python3 -c` with the
   distance printed, not a judgement by eye (M45). A timing expectation
   (the tick an event lands on) likewise, counted from the code's own
   start: a debounce's first sample, a timer's first period (M60).
9. Rows added to a data file (a CSV, a table) go in as text inside the
   file's own bytes, keeping its line ends and quoting; a round trip
   through a reader and a writer rewrites every line. After the edit,
   `git diff --stat` shows only the rows meant (M59).
10. A count in a commit message or a document is copied from the output
    of the command that gives it: tests passed, corner runs, findings.
    Run that command first, on the tree the text describes. Never type a
    count from memory, and never carry one over from an earlier run
    (M112, M118). A threshold in a test and a version in a document are
    counts too: read each from a run or from the file that states it.
11. A run a document shows is captured on a fresh copy of its project,
    or the text beside it names what ran before. A command that reads
    the last report prints something else on a fresh copy (M121).

Done when: the script reported every anchor found, and the formatter and
linter pass on the result.

## P10 — Adding or changing a CLI command

When: touching `tools/workcenter` or `tools/kicadgen.py`'s command line.

1. Write down every file the command creates, overwrites, or deletes. A
   partial run (one gate) never rewrites a whole-run report
   (`gates.json`).
2. The `--help` text says what the command writes and where.
3. One test per exit code and one per written file.
4. `docs/CONFIGURATION.md` gets the new flag in the same PR, in its
   command's table; `test_every_cli_flag_is_in_the_configuration_table`
   fails the PR when a flag has no row (M50).
5. A reader copies a command as a document writes it. A flag of the
   whole program is read on either side of the command, and
   `tests/test_docs.py` holds each flag a document gives a command to
   that command's own `--help` (M114). A rule that tells the reader to
   reorder a command is not a fix.

Done when: `make verify` is green, the configuration table names the
flag, and every document that writes the command writes one the parser
takes.

## P11 — Changing what the router sees

When: changing the DSN writer, net classes, fixed wiring, planes, via
reservations, or part spacing in a design to help the router.

1. One change at a time.
2. Measure before and after on the same design: unconnected items from
   `workcenter drc .`, pour islands, segments, vias. The scratchpad
   variant script runs the alternatives side by side.
3. Adopt only what reduces the open items; revert the rest even when it
   looked right.
4. Record the numbers in the commit message.
5. A hand-routed track is a wall on its layer. Before drawing one longer
   than three pad pitches, list the pads on each side of it whose nets
   must cross it. If one of them cannot cross on the other layer, move a
   part instead of drawing the lane.

Done when: the commit says what was measured and the number went down.

## P12 — Optional engines in tests

When: a test depends on FreeRouting, `pcbnew`, ngspice, or any engine
that may be absent.

1. The skip is explicit and named: a marker with a reason.
2. Where the engine is expected (CI, the cloud environment), the skip is
   a failure: a test asserts the engine is importable or on `PATH`.
3. `make verify` runs the tests with the same Python the CLI uses; the
   venv is created with `--system-site-packages` so it sees `pcbnew`.
4. Read the test summary for skips before calling a run green.
5. A gate has 2 kinds of skip, and they are told apart: nothing to run
   (no deck, no board), and an engine that is absent. The second carries
   the engine's name, and a run that holds one is SKIPPED with exit code
   2, never GREEN, however many other gates passed (M106).

Done when: the summary shows no unexpected skips, the engine test is
green on the runner, and a run with an engine taken away is not GREEN.

## P13 — Recording a mistake

When: you did something wrong, a step surprised you, a run was red for a
reason you caused, or you had to redo work.

1. Add an entry to `MISTAKES.md` in the same PR as the fix, in the entry
   shape: what happened, what it cost, the root cause, `Process: P<n>`.
2. Point at the process that prevents it. If none does, add one here or
   extend one, with a "Done when" line. Walk a new or changed process
   through the case that caused it, step by step, before the PR: each step
   must be one that case can follow and each check one it passes. Two
   steps that cannot both hold are a mistake in the process.
3. If a machine can check the process, add the check to
   `verify/verify.sh` or a test in the same PR.
4. If the cause is the environment (a tool, a proxy, a runner), add a row
   to the landmine map in `AGENTS.md` too.
5. Say it in the report to the human: the mistake, the cost, the process.

Done when: `make verify` is green with the entry, and the process it
names has a "Done when" line.

## P14 — Closing out a change

When: a change is about to be called done.

1. `make verify` green locally; for a board, `workcenter gates .` GREEN
   and the project's own CI checks run locally the way CI runs them (a
   board repository regenerates every project with `workcenter design
   <p>/design.py --out <scratch>` and needs exit 0, M85; `workcenter design
   <p>/design.py --check` is that step for one project, and `workcenter ci
   <repo>` replays the whole workflow and prints `CI REPLAY GREEN`). Run them
   with an absolute path (`make -C /path verify`), never behind a `cd`, and
   in the background with a log.
2. Chain the commit and the push behind the verdict itself, never behind
   a look at the log: `grep -q 'VERIFY GREEN' log && git push ...`. A
   `tail` succeeds whatever the log says. Every check you run before a
   push is in the chain (`ruff check ... && make test && git push`); a
   check whose result only prints is not a gate.
3. Push, then confirm the remote holds it: `git ls-remote`.
4. Watch CI to the end; red CI is work now, not later.
5. The report names the commit, the run link, and the numbers from the
   gate report; a skipped or blocked part is named as such. A board
   version's report carries its pictures (P23). It gives each verdict as
   the command printed it, the whole line: `GREEN with 7 warnings`,
   `REQUIREMENTS NOT MET (56 of 64 pass; 2 fail: ...; 6 open)`. Never a
   shorter word for it: `PASS verify` says the package agrees with the
   run, not that the requirements are met (M109).
6. A change to what a gate judges is attacked before it is called done. A
   reader who did not write it builds cases the gate must fail. For a
   search over corners: a measure that peaks inside a range, parts that
   act only together, 2 values written from 1 parameter. Each case that
   the gate passes is a defect, and each case becomes a test. The
   author's own cases show only what the method was built to find
   (M116).

Done when: the remote has the commit, its CI run is green, and the report
has been sent. For a gate's method: the attack's cases are tests.

## P15 — A question that reveals a mismatch

When: a human asks whether the work is a certain way (an orientation, a
size, a part, a behaviour) and the honest answer is that it is not.

1. Answer the question in one sentence.
2. Name the mismatch as a decision: what the design does now, what the
   question assumed, what changing it costs and touches.
3. If the change is reversible and inside the task's scope (a board
   revision, a document, a tool default), do it in the same turn and say
   so. Ask first only when it widens the scope or spends real money.
4. Never close with "that would be a vN change" and no owner. The reply
   carries either the change or an explicit question.

Done when: the reply holds the answer and either the finished change or a
direct question, and nothing is left as a note for later.

## P16 — A pin plan

When: choosing or changing which MCU pin carries which signal.

1. Read the alternate-function table from the vendor's data: ST's open
   pin data (`STM32_open_pin_data`, the MCU and GPIO-modes XML) or the
   datasheet. Never from memory.
2. Write the plan as a table: pin, port, and the exact function each
   signal uses (AF number and timer channel, ADC channel, EXTI line, I2C
   or UART instance).
3. Check the shared resources: no two interrupt or wake inputs on one EXTI
   line (same pin number, different port); PWM channels that must run
   together on one timer; analog inputs on ADC channels; no pin in analog
   mode at reset sees a voltage above VDD; multi-bonded pins (several
   ports on one package pin) keep the unused ones as inputs.
   Every pin a source off the board can reach (a divider from VBUS, a
   monitor's output) is held to the datasheet's absolute maximum for that
   pin's type and mode, read from the table, not assumed: an STM32 FT pin
   takes no positive injection, and in analog mode at most 4 V (DS14693
   Table 21 note 3). No clamp diode is assumed that the datasheet does not
   draw (M68).
4. Write the firmware's pin set-up from the same table and build it.
5. Give every control input a level while the MCU is in reset: a gate, an
   enable, a switch, an I2C line that only an MCU pin drives floats until
   firmware sets that pin. Set `check_pulls = True` in the design file;
   `workcenter design` then fails on each net with no output driving it and
   no resistor to a rail (or, for a gate, to its own source). Add the pull,
   or name the net in `defined_nets` with the reason: the datasheet line
   for an internal pull and the firmware line that sets it, or the part on
   the other board of a joint.

Done when: the README's pin table names the function of every used pin,
the shared-resource checks are written next to it, the firmware that
configures those pins compiles, and `workcenter design` reports no
`pull:` line for a design with `check_pulls`.

## P17 — Copper the tools add

When: changing code in the workcenter that places copper on its own
(stitching vias, reserved vias, generated tracks or pours).

1. List every code path that places that copper: grep the generator for
   every place a via or track is appended (stitching and reserved vias
   before routing, island stitching after it, generated tracks), and the
   obstacles the DSN gives the router, whose tracks are copper the tool
   chain adds too.
2. List every DRC rule that applies to that copper: copper to copper by
   net, hole to hole, copper to board edge, non-plated holes, which the
   DRC treats as board edge, and keepouts.
3. Each rule is one check, with the same numbers the board's design rules
   use, read from the `Design`, not typed again; every path from step 1
   calls it.
4. One test per rule and per path: place the copper just inside and just
   outside each kind of obstacle and expect refused and accepted.
5. Test with two of everything the code loops over: two zones of one net,
   more than two copper layers, a via that passes layers it does not join.
   A loop written against one of each double-counts or skips the second
   (M37).

Done when: every rule on the list has a test, and a routed board with the
change passes the DRC with no item placed by the tool.

## P18 — Firmware that drives power

When: writing or changing firmware that switches a heater, a motor, a
charger, or any other load from a battery.

1. For every safety cut-off, write down the worst-case time from the fault
   to the cut, and test it against a fake timer on the host.
2. Every retry has a limit and a give-up state; a dead peripheral must not
   keep the MCU awake or the load on.
3. Every elapsed-time comparison is wrap-safe (subtract, then compare),
   and a test runs the counter across its wrap.
4. Prove the tests can fail: break each safety behaviour once (a mutation
   list kept with the firmware, run by `workcenter mutate <firmware>
   --mutations <list>`) and see a named test fail.
5. Every output that drives a load is off at reset, in every fault
   handler, and when the loop that commands it stops (a deadman).
6. After any firmware change, `workcenter mutate <firmware> --mutations
   <list>` runs again. A mutation whose anchor no longer matches is fixed
   in the same commit as the edit that moved it, never left to count as a
   survivor (M101).

Done when: the host tests cover steps 1, 2, 3 and 5, the mutation run
catches every mutation after the last firmware change, and the cut-off
times are in the firmware README.

## P19 — Footprint geometry the generator transforms

When: changing how the generator copies, flips or rotates a footprint, or
placing a footprint with a pad shape no board here has used (custom pads,
chamfered rectangles, paste-only apertures).

1. List the footprint's pad shapes and, for a custom pad, its primitive
   kinds (polygon, line, rectangle, circle, arc).
2. Place it on the face and at the rotation the board uses, generate the
   unrouted board and run `workcenter drc .`. A clearance between two pads
   of one footprint is the generator's bug, never the board's.
3. Add a test that places the new shape on the bottom face and runs the
   DRC, and one that reads its pad size as the copper, not the anchor.
4. A part on the back face whose direction matters (an antenna, a
   connector's opening, a keep-out in its courtyard): generate the unrouted
   board and read 2 of its named pads from `pad_boxes()` or `workcenter
   inspect list` before anything else is placed round it. On the back face
   the footprint is mirrored before it is turned (M126).

Done when: the unrouted board's DRC shows no clearance inside any
footprint, and the tests for the shape are in the suite.

## P20 — Swapping a part

When: replacing a part with another (a cell, a connector, a regulator, a
switch) or changing its rating.

1. List every value on the board chosen from the old part's ratings:
   charge current, current limits and sense ranges, cut-off voltages,
   fuse ratings, thermal budget, pull values that assume its thresholds.
2. Recompute each from the new part's datasheet and write the value and
   the rating it comes from in the project README's BOM or decisions.
3. List what the old part did besides its ratings: protection it carried
   (a cell's protection circuit, a fuse, a thermistor), how it was held,
   and how it was connected (a plug, tabs, a holder). For each, read the
   new part's datasheet or listing: either it does the same, or the job
   moves to the board or the assembly with a part chosen for it, in this
   change (M56). A pad for a part not yet chosen is an open item in the
   README, never a contact, and the README never claims a function no
   chosen part performs.
4. Recompute every budget the part enters, not only its own ratings: the
   standby current (the MCU's Stop or Standby current from its own
   table), the power and thermal budgets, the input and output ranges of
   the parts beside it. A figure carried over from the old part is
   struck from the README until it is recomputed (M69).

Done when: every value on the list cites the new part's rating in the
README, every function on the step 3 list names the part that does
it now, and every budget the part enters is recomputed.

## P21 — Moving files in a project

When: moving or renaming files or folders in a project: a version into
its own folder, a script into a subfolder, a library to a new path.

1. Before the move, list every path a moved file computes from its own
   location and every reference to a moved file from elsewhere:
   `grep -rn -E '__file__|\.parent|parents\[|\.\./|KIPRJMOD'` over the
   moved files, and a grep for each moved name over READMEs, CI and
   library tables. Read every hit in full; a line that uses a path is not
   the line that builds it.
2. After the move, run every command the moved files' READMEs name from
   the new location, not only the ones CI runs. A script CI never runs
   breaks without a red check.
3. Diff each moved or restored folder against the commit it came from
   (`git archive <commit> | tar -x` into the scratchpad, then
   `diff -rq`). The only differences are the ones the commit message
   names.

Done when: every command the READMEs name ran from the new location, and
the diff against each source commit shows only the named edits.

## P22 — Versions of a project

When: changing a project kept as version folders (`v0.1/`, `v0.2/`, ...),
before the first edit of a request.

1. A new feature is a new version. A feature is anything the boards or the
   firmware do or carry that the latest version does not: a part, a pad, a
   net, a connection, a board, a dimension, a firmware behaviour. Copy the
   latest folder to the next number first and make every edit in the copy.
   When unsure whether a change is a feature, it is one.
   `workcenter version new <repo> <vNEXT>` makes the copy (`--from <vPREV>`
   names another source): the folder without its `build/` folders, the new
   README's banner naming where it came from, the previous README's banner
   archived with its last commit, the root README's new row
   (`(current) ... in work`) and the previous row's commit, CLAUDE.md's
   version references, and the version's parts files. It prints what stays
   by hand (the labels in `design.py`, the README's "What changed"): do each.
2. The latest version takes only what finishes the request it was made
   for: gate fixes, renders, documents, what its own CI asks for. Once it is
   pushed and a new feature is asked for, it is finished: its README banner
   says archived, with its last commit.
3. In the new folder, the README banner names the version it came from; the
   series index gets a row; the project's CLAUDE.md names the new version
   as the one in work. Read each after `version new`.
4. The version's README keeps the layout of
   `templates/project/README-version.md`: the status table under the
   title; "What changed in vX" above the older versions' sections, opening
   with the findings, the owner's answers and what the version does (one
   table), then Board, Simulation, Firmware, Parts and cost, Verification
   summary; the standing sections, which describe the board as it is now;
   Decisions, newest first, each with its version; Open items as
   "Candidates for vNEXT" and "On the bench". The gates report,
   `docs/gates.md`, keeps the layout of `templates/project/gates.md`.
5. A generated table is never edited by hand, and every copy of it carries
   its markers. The cost totals, in the root README and in
   `parts/README.md`, sit between `<!-- workcenter costs -->` and
   `<!-- /workcenter costs -->`, and `workcenter costs <repo>` writes every
   marked copy (M97); a copy without markers gets them or goes. The gates
   tables come from `workcenter gates <project> --report docs/gates.md`, once
   per board. The version's `CONTENTS.md` and `datasheets/` come from
   `workcenter docs <version dir>`, after any change to the version's parts,
   files or a datasheet.
6. `git diff --stat <its last commit> -- <previous version>/` shows one
   file, its README, with one line changed: the banner of step 2.
7. Before the first version of a board whose later versions add buses
   (a processor's memory and expansion lanes), plan each bus's path: which
   layers, where it turns, where its vias stand. Then place what lies in
   those paths. Placed from the mechanical drawings alone, the first
   version of a motherboard moved 4 groups of parts while its buses were planned
   (M132).

Done when: the request's edits sit only in the new folder, the previous
folder matches its commit but for the banner, the index and CLAUDE.md name
the new version, the README keeps the template's layout, and `workcenter
costs` and `workcenter docs` run last leave `git status` unchanged.

## P23 — Pictures of a finished board version

When: a board version's gates are GREEN and P14's close-out is next; again
after any change to what the boards look like in that version.

1. The version's `pictures.json` says what is drawn: every board (its
   stills, its layer sheet, each turning GIF with its tilt, zoom and
   pivot), every scene script (an assembly, a close-up) and the name each
   file takes in `docs/`. `workcenter pictures <version>` writes one with
   the defaults when there is none: each board seen from the face that
   carries the parts, from below too (tilt `-125`) when it has parts on
   both faces, and each script at the version's top that imports `scene`.
   An assembly is a scene script on `tools/scene.py`, so it is redrawn
   with the stills; the script holds only its placements.
2. Check the framing before any GIF is kept: `workcenter pictures
   <version> --frames 4` (under two minutes for a version of two boards
   and an assembly) writes one sheet per GIF with the frames at 0, 90, 180
   and 270 degrees, and leaves `docs/` alone. The end-on frames crop first:
   lower `zoom`, and raise the pivot's z to the middle of a tall assembly,
   in the manifest, until all four are whole.
3. `workcenter pictures <version>`: every board's stills and every layer
   (`render --strict`: a part the 3D views draw without a body fails its
   board, and nothing of that board is copied; give the part its body,
   M52), the GIFs, the scenes, then the copies into `docs/` and
   `docs/layers/`. It exits 1 on any failure.
4. The README shows the GIFs beside the stills and the layer sheets, and
   names `workcenter pictures <version>` and its `pictures.json`, which
   the next version copies with the folder and so draws the same way.
5. Send the GIFs and the layer sheets with the report.
6. An assembly scene draws every body its boards name. Build it with
   `tools/scene.py`, which copies each 3D model the board names and reports
   one it cannot find; then look at the bottom face in a still. A path
   rewrite on a footprint's models changes a copy and draws nothing (M99).

Done when: `workcenter pictures <version>` exits 0, the version's `docs/`
holds a layer sheet and a turning GIF for every board and for the
assembly, all four test frames of each GIF are whole, the README shows
them and names the command, and the report carried them.

## P24 — A schematic someone reads

When: writing or changing a board's schematic, and before a board version's
close-out.

1. The design sets `sch_wires = True` and keeps its layout in one table of
   positions and angles (`SCHEMATIC`), in blocks the way the signal flows:
   power left to right along the top, each support part beside the pin it
   serves, connectors facing the circuit they feed.
   A position computed from a symbol's size reads `kicadgen.symbol_box`,
   which is in the library's frame, y up; the sheet's y runs down (M130).
2. Labels only for nets that cross the whole sheet (`sch_label_nets`), each
   named in a comment; every other net is a wire.
3. Check the drawing against the design: ERC 0 errors and 0 warnings, and
   the DRC shows no parity warning, so every wired net carries the board's
   name. Do it before the first route: a net named on 1 pin joins nothing,
   the DRC does not see it, and the wired sheet's ERC names it as an
   isolated label (M127).
4. Plot the sheet (`workcenter render . --views schematic`) and read it:
   follow each signal in the README's pin table from its MCU pin to its part.
   Move a part when a wire wanders round the sheet or text lands on a part,
   and plot again.

Done when: ERC is 0/0, the DRC shows no parity warning, and the plot in the
README is the one that was read.

## P25 — Prices and part numbers from a distributor

When: looking up a part, its price or its stock at a distributor, or
writing a parts file (the `procurement` skill).

1. Reach the supplier the sanctioned way: its API with the user's own
   credentials, or its pages with the fetch tool where its robots.txt allows
   (Digi-Key's allows Claude-User). A script that gets a 403 has been
   refused; never retry it with a browser's user agent or any other disguise
   (M55).
2. Find the product page by search, never by a URL from memory, and confirm
   the manufacturer part number printed on the page before reading a price
   (M54).
3. One part per value and footprint, meeting the strictest use on every
   board that names it (voltage, dielectric, power), read from the design's
   notes.
4. Record what the page shows: the supplier number of the cut tape or bulk
   packaging, every price break, the stock (0 when out of stock, the expected
   date in the note), the date read and the URL. No price from memory or a
   search snippet.
5. A part the supplier does not carry gets the supplier that does, or no
   price and a note saying where it was looked for; never a part with
   another footprint without a design change.
6. `workcenter procure` prices the BOM; its "Not priced", "Short of stock"
   and "Prices to check again" lists go into the report.

Done when: every priced row in the parts file has the URL it was read from
and the date, and the report carries `procure`'s totals and its three lists.

## P26 — A feature the user reaches

When: adding or changing a way the user reaches a feature on the device:
a button gesture, a port, a mode, a firmware update.

1. Write the user's steps on the device as assembled, from the state it
   sits in: what powers it, whether it is ever off, when the MCU resets,
   and what is running at that moment (a watchdog, timers, a load, the
   display).
2. Every step must work in that state. A step that needs a reset, a
   removed cell, a debugger or a jumper is not a user's step; it may stay
   as a bench path, named as one in the README.
3. A hand-over to other code (a ROM bootloader, an updater, a second
   image) lists what the hand-over leaves running and what the other code
   expects at entry, each from its documentation, cited. What would not
   survive the hand-over is stopped or reset before it (M58).
4. Whatever the user keeps across it (a schedule, a calibration) is saved
   before the hand-over, and a host test drives the user's steps through
   the app: the hand-over happens only in the intended state, after the
   save.

Done when: the version's README gives the user's steps, each hand-over's
entry conditions cite their source, and a host test runs the steps.

## P27 — A part's datasheet, SPICE model and 3D model

When: a part enters a BOM, a simulation uses a vendor's model, or a 3D body
comes from a vendor.

1. Every part on the schematic gets rows in the project's
   `library/sources.csv`: a datasheet for each, a spice row for each U, Q
   and D (a model file, or a note saying why there is none), a step row
   where the vendor publishes a body. Fetch the sanctioned way (P25 step 1):
   `workcenter sources --fetch` asks once under its own name and records a
   refusal, and `workcenter fetch <url> --to <library>/<maker>/<file> --mpn
   <MPN> --row` does the same for a file the library does not hold yet; a
   file no site will serve is left for the user to download, and its row's
   note says so and from where.
2. Keep each file as the vendor publishes it, its notice intact; a model
   that ngspice reads differently is translated into a copy in `build/`,
   never in the library. The row records what the file itself prints: the
   revision string as printed, its date, its SHA256, the day it was checked;
   a model's row also its `.SUBCKT` and the fixes ngspice needs (`ps`,
   `res-model`, `tolerance`).
3. A model older than its datasheet: read the datasheet's revision history
   for every change after the model's date (curves, a new manufacturing
   flow, a changed limit) and write down what it touches.
4. Before a model serves a design deck, run it at its datasheet's own test
   conditions in a deck whose expect file holds each table row's min and
   max as a `warn` bound. A model off its datasheet is named in the
   version's README with the datasheet value the design trusts there, and
   the design's own bounds come from the design (the firmware's constants,
   the parts' operating ranges), never from the model's first result.
5. A reference's whole letter prefix says what it is: D1 is a diode, DS1 a
   display, and a check that reads one letter takes one for the other (M63).
6. A value read from a datasheet's curve comes from `workcenter curve` on
   the PDF's vectors, the middle of the drawn line, with the figure and
   page named beside the value. A hand reading or a script of one's own is
   checked against a curve of known values first (M100).
7. A deck that goes to a person outside the project goes as a bundle:
   `workcenter sim <project> --bundle <dir>` writes each deck with its
   models, translated as the gate reads them, and the file that sets the
   mode, and proves the folder prints the gate's numbers from another
   place. The deck alone stops with an error or prints another number
   with exit code 0 (M105). A translated model is a changed copy of its
   maker's file: read the maker's notice before the folder goes to a
   third party.

Done when: `workcenter sources` passes for every board of the version, each
model a deck uses has its datasheet rows as `warn` bounds, the README
names each model that is off its datasheet and what the design trusts
instead, and what left the project for another machine left as a bundle.

## P28 — A board's verification package

When: the user asks for requirements, a review, an inspection, or proof
that a design meets its parts' ratings; before a version is called ready
for anything beyond the bench; after a part swap or a feature, for the
circuits it touches. The `verification` skill is the how-to.

1. `workcenter verify <project> --init` writes the skeleton:
   `verification/` with the requirements, the system, a writeup per deck,
   the calculations and the traceability table.
2. Write the operating profile and the conditions, expected and
   unexpected: every source class the power input can meet at its range's
   ends, a live plug, a faulty source up to the next standard voltage and
   the input part's rating; every load and its faults; storage, shutdown,
   the environment. Ask the user for what only they know.
3. One requirement per limit, each with its source (a datasheet table or
   figure and its revision, a standard's clause and edition, a firmware
   constant), its method, and the clause it would be inspected under.
   Read every section, table and figure number from the document's text,
   never from memory (M72), in the package and in any code comment that
   cites a standard or datasheet (M84). A limit computed from parts'
   values carries the tolerances its source names (M82). A requirement the
   owner restates or adds names "the owner's decision of <date>" in its
   Source; one the owner withdraws moves to the requirements' Withdrawn
   table (ID, date, decision, by), and its traceability row and every
   `"req"` naming it go.
4. Judge every limit at its corners: the datasheets' minimum and maximum
   rows, the source's range, each setting resistor's tolerance, the
   temperature. The SIM gate runs the temperature and the tolerances:
   write `sim/corners.json` first, the temperature range from the
   requirement that states it and each tolerance from its part's
   datasheet, each with its source (the `simulate` skill, "Corners").
   `verify` then judges each check at its measure's least and greatest
   corner (M107). A corner moves only what the deck and its models
   carry: give each resistor its coefficient, and where a model says it
   has no temperature in it, rest the requirement on the datasheet's own
   range in a calculation. A typical value is a check of the model, never
   a verdict (M70). A fitted model's value at a condition the datasheet does not
   tabulate is no maximum: take the nearest maximum row as flat, unless a
   figure read from the datasheet says otherwise (M83). Write the limit
   before the number it is compared with, then compare (M71).
   - A measurement behind a series part (a fuse, a shunt, a switch, a
     track) lists every current through that part, in both directions: the
     charge current, each rail's load, each load's edge. Each takes its
     corner (M92).
   - A fuse, or any series part, is checked at every event that moves
     charge through it: each load edge, the surge at assembly, a plug-in, a
     fault. Not only the event that put it there (M95).
5. One deck per circuit question; each bound that holds carries
   `"req": "<ID>"`. A requirement the design fails gets no bound and a
   FAIL in the traceability table, with its size and a proposed fix; a fix
   that changes the board is a new version (P22). A part with no maker's
   model is fitted to its datasheet and checked row by row; a stand-in
   never clamps at an absolute maximum, which is a bound on a measure
   instead. Every output that drives a capacitor gets its peak current
   measured and bounded by the pin's rating (M81).
   - Every track resistance a deck uses comes from `workcenter inspect
     resistance <board> <NET> --from <REF.PAD> --to <REF.PAD>`, which reads
     each layer's copper thickness from the stackup; the deck's comment
     names the command and its result (M93).
   - One deck run by hand runs only through `workcenter sim <project>
     --deck <name> --keep`, which prepares it as the gate does (the vendor
     models' translation, the PSpice mode). Never a bare `ngspice -b` on a
     deck that includes a vendor model (M94).
6. One writeup per circuit with the template's sections; the nodal
   analysis solves the circuit by hand, cites each equation, and is
   compared with the deck.
7. Several runs at once on one project write to their own `--out`: runs
   sharing `build/` mix their reports (M73).
8. Helpers who write parts of one package at the same time work from
   `templates/verification/BRIEF.md` and `FACTS.md`, filled in a folder of
   the session's scratchpad (the `verification` skill's "Helpers"):
   - Each helper owns named files and edits nothing else.
   - Every fact is in FACTS.md with its home in the project; the brief
     points at FACTS.md and copies no fact (M98). A fact that changes is
     changed in its home, then in its FACTS.md row and change log, and
     every helper is told which row moved.
   - Every path in either file is a file that exists when the brief is
     sent; a document still to be filed is named where it is (M96).
   - The brief asks questions and states no behaviour that a run has not
     shown (M95).
   - The skill's two checks print nothing before the brief is sent.
9. `workcenter verify <project>` until it reports no problems.

Done when: `workcenter verify <project>` reports no problems with the decks
run at their corners, the package's README lists each FAIL with its size
and its proposed fix, each track resistance in a deck names the `workcenter
inspect resistance` run it came from, and the report to the user gives the
command's last line, the counts of PASS, FAIL and OPEN, and each withdrawn
requirement.

## P29 — Placing a part on a routed board

When: before a part goes onto a board that has been routed, or moves on
one: a fuse into a feed, a part shifted to make room. A spot is chosen
from what the board holds on every layer, never from courtyards alone.

1. The board's mechanical neighbours are in the design. Each strip,
   spacer, cell, shell or body that stands on or over the board is a
   `d.keepout(polygon, layers, name, parts=True)`, with `copper=False`
   where tracks and vias may pass under it. An assembly script is not the
   design: `workcenter design` and the DRC know only what `build()` holds
   (M87).
2. `workcenter inspect map <board> --box X0 X1 Y0 Y1` round the spot, and
   read every layer: pads, tracks, vias, pours, keep-outs, courtyards.
3. `workcenter inspect crossed <board> --box ...` on the spot lists the
   nets the router ran through it. Write a path for each before the part
   goes in: round the part, on another layer, or a hand route. A net with
   no path means another spot (M89).
4. `workcenter inspect islands <board>` (and `--net` for each other pour):
   which piece of the pour holds the spot, what that piece holds, and how
   many vias join it to the plane. A part that cuts the only path or via
   of a piece's pads makes an island; check that the inner layers there
   leave room for a new via, with `inspect probe --via` (M88).
5. `workcenter inspect probe <board> --part REF --at X,Y [--rot DEG]`, with
   `--footprint LIB:NAME --nets 1=NET,2=NET` for a part the board does not
   have yet: its courtyard against the others, its pads against the copper
   round them, and the keep-outs by name. A spot is taken only when the
   probe says `clear` (M90).
6. Every hand via and track the change needs goes through `workcenter
   inspect probe --via X,Y --net N` or `--track "X,Y X,Y" --layer L --net
   N` before it is written into `design.py`: the probe knows the keep-outs
   and the project's inner-layer drill rule, which a check of copper and
   holes alone misses (M91).
7. Write the position and the hand copper into `design.py`. Route once
   with `workcenter design design.py --route`, then run `workcenter
   inspect islands` again and `workcenter inspect crossed <old board>
   --box ... --new <board>`. A net it reports open gets the path step 3
   wrote, not a second guess.
8. `workcenter gates <project>`.

Done when: `workcenter design` prints no `part:`, `via:` or `island:` line,
`inspect crossed --new` reports no net open, and `workcenter gates` is
GREEN after one route.

## P30 — A frequency plan

When: a board has a part that switches or a clock (a PWM output, a
switching regulator, a charge pump, a bus), before its SIM gate is called
done; again after a change of a frequency, or of an inductor or a
capacitor on a supply rail.

1. List every periodic source with its frequency, or its range, and where
   the number comes from: the firmware's constant, the datasheet's row.
2. Sweep each supply rail a source loads with an `.ac` deck. A 1 A AC
   current source at the load reads the rail's impedance in ohms. Measure
   each peak's frequency and its Q (the `simulate` skill, "The frequency
   plan").
3. Write both lists into `sim/frequency-plan.json`.
4. Run `workcenter sim <project>`. It names each overlap: a source's
   harmonic in a resonance's band, or 2 sources that can run at 1
   frequency. Remove each: move the frequency, move the resonance, or
   damp it.
5. An overlap that stays is answered with a deck that runs the source at
   the resonance and bounds what it does to the rail. Name the deck's
   measure and its stimulus under `overlaps`. A bound on an average does
   not answer: the fixture `fail-freq-overlap` swings 6.8 V with its
   average inside 2 %.
6. A table of frequencies in a document is copied from the plan, never the
   other way (M108).

Done when: `workcenter sim <project> --strict` passes with the plan in
place, every source and resonance carries its source, and every overlap
the gate names is removed or answered.

## P31 — Work handed to helpers

When: before starting a helper (a subagent, a second session) on a part of
a task.

1. Count the budget first: how many helpers the session runs at once (its
   processors less 2). Start the 2 most valuable, and no third until 1 of
   them has reported. What the account has left to spend cannot be read
   from a session: a helper that stops at the usage limit is the reading.
   Note the reset time its message names, start no helper before that
   time, and do the work that needs none meanwhile (M113, M120).
2. The lead writes in a worktree of its own (`git worktree add`), never in
   the checkout its helpers read or run.
3. Each helper gets a brief: its worktree or scratch folder, the files it
   owns, what is out of scope, when it is done, what to report. Every path
   in the brief exists when it is sent (M96), and it states no behaviour a
   run has not shown (M95). A helper writes only under what the brief
   names (P8 step 5).
4. A helper's report is data. Check a claim by its command before building
   on it.
5. A helper that returned nothing is read before it is started again: its
   journal says how far it came and whether its worktree changed. One the
   usage limit stopped is resumed by its own name after the reset, not
   started anew: its work so far is kept.
6. Count the machine too: its memory, not only its processors. Helpers
   that run engines, a health gate and a browser do not run together.
   The health gate that gates a push runs alone (M124).
7. The signal for "the gate runs" is a file, not a message. The brief
   names 1 lock file. The lead makes it before a health gate and removes
   it after. A helper looks for it before each command that runs an
   engine or a test, and starts none while it is there. The lead starts
   the gate when the lock is there and no engine of a helper runs (M125).
8. Send no message to a helper that a workflow runs. A message to its id
   starts a second runner from its transcript, and the 2 write the same
   files. The brief tells each helper the same: it sends no message to
   another helper's id or to its own. Talk to a running helper through
   the files its brief names: the lock, and its notes file (M125).
9. A helper has stopped when its task says so: the workflow's notice, or
   the stop the lead asked for. A quiet transcript is no stop. Change no
   file a helper owns before that (M125).

Done when: every report is read, each helper's changes are merged or
removed, and `git worktree list` shows only what is still in use.

## P32 — A deploy to an outside host

When: creating a project on a host that serves pages (Vercel, GitHub
Pages), or sending it a first deployment.

1. Before the first call, read what the host does with a project's first
   deployment. Vercel makes it the production deployment, whatever branch
   it comes from (M122).
2. A page that describes work on a branch goes to a preview. Where the
   host cannot give a new project a preview first, say so to the owner
   before the call, and name what production will show.
3. After the deploy, fetch the address the host reports: the status code,
   the canonical link, and each file the page names.
4. Write an address into a document only after that fetch (P5), with the
   deployment's target as the host reports it.

Done when: the address answers with the page of the commit the document
names, and the document names the target the host reports.

## P33 — Rewriting a history

When: the owner asks for commits to change that are already pushed: an
author, a message line, a file that must leave every commit.

1. Give the owner the old history first, as 1 bundle of every ref
   (`git bundle create <file> --all`).
2. Rewrite in a fresh clone, never in a work tree. Change only what was
   asked: a message that loses no line keeps every byte (M123).
3. A commit that a file cites gets its new name in that file too, in the
   same rewrite: rewrite once to learn the name, then again with it.
4. Before the push, have the result rebuilt from the old commits by a
   check that is not yours: each new commit object from its old one and
   the rules, hashed, equal to the new id. Fix what it finds and have it
   checked again.
5. Run `make verify` on the exact trees that will be pushed.
6. Name what follows the default branch before it moves: CI, a deploy,
   another repository that clones it. Replay that repository's checks
   with the old tree and with the new one.
7. Push every rewritten branch in 1 atomic push, with a lease on each
   branch at its full old hash.
8. Afterwards move each work tree to its new commit. Tell the owner what
   the push cannot change: the commits a pull request page keeps, a
   branch this session cannot delete, a clone that holds the old history.

Done when: the remote's branches are the checked commits, `make verify`
is GREEN on them, and the owner holds the old history and the list of
step 8.
