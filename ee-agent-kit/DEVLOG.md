# DEVLOG.md — the live devlog

The plain history of this project. A person who knows nothing about the
code reads this file and knows what happened, in order, with no jargon.
Append only. Never rewrite an old entry — a wrong entry gets a
correction entry, not an edit.

Write every entry in the voice of `TONE.md`.

## Entry shape

Every entry has the same shape:

```
## YYYY-MM-DD — <one line: what happened>

<What we did. What worked. What broke. What we learned.
3–10 short sentences. Plain words. Past tense for what happened,
present tense for how things now stand.>

Evidence: <commit / tag / gate run / screenshot>
```

## When to write

- Every WEEKLY.md cycle writes one entry at step 5 (before merge).
- A failed or abandoned attempt gets an entry too. The devlog records
  what happened, not what succeeded. A week with no shipped feature
  still gets its entry.
- Out-of-band work (security patch, gate repair, big triage) gets one.
- SETUP.md writes the first entry: "Installed the agent kit."

## What does not go here

- Code detail that belongs in commit messages.
- Promises about the future — that is ROADMAP.md.
- State claims — that is STATUS.md. The devlog is the story; STATUS is
  the snapshot.

---

## 2026-11-11 — A second example: a microATX board for Threadripper

The owner asked for a compact, good-looking example of what the
workcenter makes: a microATX motherboard for a Threadripper. None
exists; the smallest TRX50 board is ATX. Basalt is in
`examples/threadripper-matx`, kept as version folders the way the
owner's vape prototype keeps its own, and built in a loop that ran 1
prompt again and again and logged each pass in `LOOP.md`.

v0.1 placed the 4844-land socket, the slots, the memory and 14 phases
from the microATX and PCI Express drawings. The router ran 20 minutes
twice on the 4 supply nets without finishing a pass, so the design
draws every supply as a pour now, as a real board carries it (M129).
v0.2 drew the 4 memory channels' 576 traces by rule, and the first DRC
found nothing. Midway the owner asked for the ports every desktop board
has; v0.3 adds 77 parts, from SATA ports and fan headers to the CMOS
battery. FreeRouting finished their nets in a third of a second with
none routed, so the project's own grid router learned to change layer
through a via and joined all 51.

The workcenter gained on the way: `kicadgen` wires a processor drawn
as banks on an A0 sheet, checks a socket's 3457 vias in 0.3 s where it
took 63, and `render` draws a board in its own colours. The PCI Express
and M.2 lanes are not on the board yet: 151 of 234 route, and the rest
need a trunk drawn by rule, like the memory's.

Evidence: `workcenter gates` GREEN with no warning on v0.1, v0.2 and
v0.3; `make verify` GREEN.

## 2026-11-11 — An example project: a controller that speaks to 5 consoles

The owner found the site's examples poor and asked for a prototype in the
manner of Agentcast and Last Hit: a universal controller with a switch that
picks a PS4, a PS5, an Xbox, a Switch or Bluetooth, with ideas that are
hard to do, and a site that moves. Rosetta is in
`examples/universal-controller/v0.1`: a routed 4-layer board in a
controller's outline, 140 parts. The knob is 1 analog reading from a
resistor ladder. Its first deck found that a 1 M pull-down and the ADC's
leakage read 1 V between detents, a position; the ladder is 1k and the
pull-down 100k now, and 6 decks hold each position at every corner. A
USB host port relays a console's signature to a licensed donor through a
second USB port the RP2040 runs in software. The ESP32's antenna hangs
over the gap between the grips.

This machine had no KiCad, and Launchpad reset every connection, so I ran
the workcenter in the repository's Docker image. The image could not
route: Debian's headless Java has no X11 library, and FreeRouting stops
without it. `install.sh` now adds the full runtime where the library is
missing. The wired schematic's first ERC found 3 faults the label sheet
had hidden (M127). The router needed many runs: 60 passes ran out of time (M128), the
RP2040's pins had no lanes until its caps moved to the corners and its
vias shrank to 0.45 mm, and from there FreeRouting closed every
connection in 1 run of 4. The IMU's supply pins stayed apart in 3 runs;
that link is drawn by hand now. The site draws the routed board
from its own files and turns the knob with Motion.

Evidence: `workcenter gates examples/universal-controller/v0.1` GREEN with
5 warnings (silkscreen over the edge the receptacles and the module hang
past), 6 decks and 370 corner runs; `make -C firmware test` passing;
`render --strict` naming no part without a body; in the Docker image,
`tests/` 524 passed, 1 failed (`test_simgate`'s bundle test expects ngspice
42's error lines and the image has ngspice 44), 3 skipped.

## 2026-11-11 — The front page shows a board

The owner asked again for the repository to look good. The README was
text under 1 banner. Its first screen now shows a board: lines of a design
file, then the schematic and the routed board that `workcenter design`
writes from the file, then 2 runs of the gates. I took the owner's own
apparatus repository as the pattern: real captures, light and dark, with a
line under each. The board is a new fixture, `pass-first-design`: the
template's design file, built, with a deck of 2 bounds. It is the first
fixture that goes from a design file through all 4 gates. The build wrote
the same 3 files 3 times in 3 folders. A test compares the schematic and
the project file only, because the router's tracks may differ on another
machine; the fixture's own DRC holds the board to the schematic. The 3D
views need the parts' bodies, and this machine has none. I fetched the 3
files the board names from KiCad's library into a scratch folder and
committed none of them. The template's board is 25 x 20 mm with 4 parts
on its left third, so the close view and the GIF frame the parts. Every
picture has its command in `site/media/README.md`. I drew each committed
picture with those commands, from fresh folders. The site's page shows
the same 3 cards in a new section, and the first picture is a capture of
those cards.

Evidence: `tests/test_docs.py` 16 passed and `tests/test_designfile.py`
14 passed; each new assertion failed on a broken copy first, 15 copies;
the README drawn with GitHub's stylesheet, light and dark, before the push.

## 2026-11-11 — One branch, and the owner's name on every commit

The owner asked for every branch collapsed into `main`, everything in 1
place, and my name off every commit. `main` now holds the gates work and
the site: 55 commits. Each names the owner as its author, and no message
carries a co-author line or a session line. I rewrote the history in a
scratch clone and pushed nothing before it was checked by others. 2
checkers read the first rewrite. It had 1 fault: a newline added to the 1
message that had no line to lose (M123). A third checker rebuilt the
second rewrite from the old commits, byte for byte: 59 of 59. Every commit
has a new name, and where this log named a commit of that day it now
gives the new name. Before the push I replayed Last Hit's CI with the old
workcenter and with the new: 55 steps, each exit 0 with both, and every
regenerated file equal. Vercel built production from `main` minutes after
the push. The 39 branches of merged pull requests are still on GitHub:
this session's git access refuses a deletion, so the owner deletes them.
The chip branch stays until its gates are tested. The old history is with
the owner, as 1 bundle file. P33 holds the steps.

Evidence: `make verify` GREEN on the pushed trees, 526 tests on `main` and 609 on the chip branch; the third checker's rebuild, 59 of 59 commit objects equal; Last Hit's CI replay, 55 of 55 steps exit 0.

## 2026-11-11 — Correction: the site is served, and it went live from the branch

The entry below says the site is not served yet. That stopped being true
the same hour. I linked a Vercel project to the repository and deployed
the branch, and expected a preview. Vercel makes a new project's first
deployment its production deployment. So the site is live at
<https://via-kappa-five.vercel.app>, built from commit `dced7bf` of the branch. The page answers 200
with its own address in the canonical link and the Open Graph tags. It
describes `workcenter next` and the corners, which `main` gets when this
branch merges. P32 now says to read a host's rule for a first deployment
before the first call (M122).

Evidence: `curl` on the address and on each file the page names, 200 each; an unknown path, 404 with the site's own page.

## 2026-11-11 — The repository got a face: a website, a mark and an Open Graph image

The owner asked for a professional open-source face that relies on the
kit, and then for a site in the look of the apparatus site. I read that
site and its repository first. Its look is paper and ink, 1 ink-blue
accent, Inter at 2 weights and no borders, with real captures in place of
drawings. I built `site/` in that look: 1 static page, 1 stylesheet, 1
script and no install step. The page shows 4 runs as the terminal printed
them. The tool prints no colour, so the runs have none. My first mark
looked like a magnifying glass. The mark is now a via in cross-section: a
trace on the top layer, the plated hole, a trace on the bottom layer. A
new test runs each command the documents show and compares the lines. It
failed on its first run: `next` printed "Run the gates." on a fresh copy,
because I had captured it after a gates run (M121). The site is not
served yet: the Vercel project deploys production from `main`, and this
work is on a branch.

Evidence: `tests/test_docs.py`, 14 tests pass; 20 mutants, 18 caught and the 2 masks holding.

## 2026-11-11 — Two reviews broke the corner search, and a small model built a board

Two reviewers read yesterday's gate with one aim: make it pass a circuit
that fails. They did: the first review holds 22 findings. The search ran
each part at the 2 ends of its tolerance. A series LC's gain is 0.239 and
0.072 at those ends and 1.0 between them. A bridge reads 0.064 V with 1
resistor off and 0.25 V with 4 off together. I wrote the search again. It
runs each part half-way too, follows a peak, and runs every combination of
the ends up to 64 runs. On the copy of Last Hit v0.16 it makes 678 corner
runs where it made 153. The board's own range still passes. The engineer's
85 C finding still fails, now with "and 8 more corners" beside it.

The second review read `workcenter next` as a small model does: it ran
every RUN line as written. 1 answer was no command, 1 looped, and 1
asked for an install for good. Each state now gives 1 command that runs.

The smallest model I can start then built a board. It took a low-pass
filter on an op-amp from a paragraph to ERC 0 errors, DRC 0 errors, 14
corner runs and 22 gerber files, in 38 tool calls. It met 8 traps. A
design file with no UUID gave a Python error. Parts placed from (0, 0)
gave a route of 0 tracks with exit code 0. Each trap now stops with the
line to write, and a first design file starts from a template that
passes as it stands.

1 trap has no gate yet. The model wrote the op-amp as 2 sources in its
deck, and every gate passed: nothing holds a deck to the board's parts.
The template now makes the design file name each part's model. The deck
is still typed by hand. That is the roadmap's "the board as one netlist".

The engineer left 2 notes on Last Hit's branch: the power path walked
stage by stage, and a breadboard plan. Both are queue items now. The
owner asked for chip design, down to the mask layout. 3 scouts showed the
open engines run here: a counter went from RTL to a layout in 82 s, with
0 DRC items, a matching LVS and 54 timing corners met. The chip gates are
not built. Helpers hit the account's usage limit 2 more times, so that
build starts at the limit's reset, on its own branch.

I made 5 mistakes worth a process step: the search itself, a reader that
did not read values as ngspice does, 2 counts typed from memory, tests
edited by script again, and a third helper past the budget.

Evidence: `make verify` green on this commit; `tests/test_designfile.py`
(14 tests) and the new tests in 5 files; the reviewers' 6 mutants, all
caught; the 2 reviews and the small model's project in the session's
scratch folder; `MISTAKES.md` M116 to M120.

## 2026-11-11 — The schematic simulates, and a small model followed `next`

Both items at the top of yesterday's queue moved. A design file now says
how each part simulates: `d.sim` binds a part to a model with a map from
every pin to a node, and `d.no_sim` leaves a part out with its reason. The
generator writes KiCad's Sim fields, and the netlist KiCad exports runs in
ngspice. On a copy of Last Hit v0.16 the exported netlist had 29 lines
ngspice could not read; with 10 parts declared it has none, and it gives
the engineer's current-sense numbers: 1.198 V at 27 C and 1.099 V at 85 C.

KiCad has a trap here. A pin map that leaves out a node of the model is
completed by position, with exit code 0 and no ERC line. I measured it: a
regulator's enable node took pin 3 though the map never named it. The
check refuses a map that is not whole before KiCad sees it.

The smallest model I can start built a supply filter from one paragraph,
reading only what `workcenter next` named. The first filter resonated at
the heater's 5 kHz PWM and the rail swung from 10.64 V to 13.19 V. The
frequency plan failed it, the model raised the capacitor to move the
resonance to 1.4 kHz, and the rail then held 11.77 V to 12.04 V over 131
corner runs. It reported 9 places where it had to guess. The worst was
ours: the skill's own example for measuring a resonance fails on a rail
with series resistance. Each is fixed in a gate, a hint or the skill.

I ran `workcenter sim <project> --json` and got a usage error. That was
M18 again, and the `board-gates` skill had taught that order all along.
The flag now reads on either side of the command, and a test holds every
flag a document gives a command to that command's `--help`.

The board half of the small-model run is not made yet. Two reviewers are
still reading the gate change; their findings come in a later commit.

Evidence: `make verify` green (433 tests); `tests/test_simfields.py` (16
tests); the small model's project and its report in the session's scratch
folder; `MISTAKES.md` M114 and M115.

## 2026-11-10 — An engineer checked the board, and the gates learned the questions

An electrical engineer reviewed Last Hit v0.16 by hand. The engineer could
not run our decks: 3 stopped with an error on that machine and 3 printed
other numbers. A sweep of the current sense over temperature found the 6 A
reading at 1.098 V at 85 C, outside our own bound. The engineer ran the
board's first frequency sweep, and started to redraw the schematic to test
it. Every one of these was a question the gates never asked.

The SIM gate now asks them. A project names its temperature range and its
parts' tolerances in `sim/corners.json`, and each deck runs at every
corner. On a copy of the board the gate finds the engineer's number
itself: 1.076 V at 85 C with 2 resistors 1 % low. Over the board's own 0
to 40 C the 12 decks hold in 153 corner runs. A project names what
switches and what resonates in `sim/frequency-plan.json`, and the gate
fails a harmonic that lands on a resonance until a deck drives it there.
`workcenter sim --bundle` writes a deck as a folder that plain ngspice
runs anywhere, and proves it from another folder.

Reading the gate for this turned up older faults. A transient ngspice gave
up on passed its bounds, because a later analysis made the exit code 0. A
misspelt key in an expect file held nothing and passed. `gates` printed
GREEN with the simulator absent, and `verify` printed PASS beside 2 failed
requirements. Each is fixed and has its test.

The owner wants a small model to reach the same working board as a large
one. `workcenter next` is the first step: it names the one next action,
its command, and the section to read. No small model has followed it yet.
A generated schematic still does not simulate inside KiCad, which is what
the engineer needs to stop redrawing. Both are at the top of the queue.

I started 8 helpers at once, then 3 more. The account's limit stopped 7
of them with nothing returned. P31 now sets a budget before any helper
starts.

Evidence: `make verify` green; `tests/test_corners.py`,
`test_freqplan.py`, `test_simgate.py`, `test_guide.py`, `test_docs.py`;
the runs on a scratch copy of Last Hit v0.16 in `STATUS.md`; `MISTAKES.md`
M103 to M114.

## 2026-11-07 — The Last Hit work's habits, written down

The owner asked for every tool and convention of the Last Hit work in the
workcenter, so the next agent given the same task produces the same
outputs. This part covers the conventions. A version's README and its
gates report now have templates, taken from Last Hit v0.16. P22 names the
commands that make a new version and keep its generated tables current.
One cost table had sat three versions behind because the checklist named
only one of its two copies.

`workcenter verify` now reads the owner's decisions. A withdrawn
requirement moves to a Withdrawn table with its date and who decided; the
check names it, leaves it out of the counts and refuses its old row. On
v0.16's package, REQ-USB-01 moved there and the counts stayed 56 PASS, 2
FAIL, 6 OPEN.

Seven mistakes from v0.15 and v0.16 became rules in P28. A divider moved
behind a fuse counted one current through it, not two. An inner track's
resistance was taken as outer copper. A deck run by hand skipped the gate's
model translation. Three came from briefs to helpers: an expectation the
deck contradicted, a path promised before the file existed, a fact that
changed after the brief went out. Helpers now get a brief that asks
questions and a facts file that holds each fact once.

Evidence: `tests/test_verify.py` (24 tests); the v0.16 package checked in
a scratch copy; `MISTAKES.md` M92 to M98.
## 2026-11-07 — The router starts from the last board and keeps the inner drill rule

The owner asked for every tool of the Last Hit work in the workcenter. This
part closes the router's gaps. On v0.16 one fuse landed on a path the router
had used in v0.15, and four hand routes and five routing runs followed
(M89). `workcenter design --route --seed <board>` now starts FreeRouting
from the previous board's router tracks. Given as unfixed wiring, they did
not hold: the display board kept 85 of v0.15's 117, where a route from
nothing repeats 116. FreeRouting's optimiser reworks every unfixed track.
Held as `shove_fixed`, which it may push but not rip up, the display board
keeps 116 and the base board 76 of 87 (63 from nothing). Tracks that hang
from nothing, such as a moved part's old ones, still go in unfixed, so the
router extends them or removes them.

M79 was a router via 3.5 µm inside Sierra's 13 mil inner drill rule. We
tried four ways to tell FreeRouting 1.9.0 and routed a fixture each time. A
via-to-wire clearance in the DSN's structure changed nothing, globally or
per layer. Inside a net class it held only between that class's own nets.
A via drawn larger on the inner layer worked for every pair, so the DSN now
does that. On the fixture the old file put a via hole 0.3281 mm from an
inner track and the DRC failed; the new one keeps 0.3581 mm. The hand-via
check, the via placers and island stitching keep the same rule.

The design command now ends a red run with a line that says so (M85), and
it names the island and pads behind each stitching via. The new route on
Last Hit showed a dangling track: the merge had dropped a short link from a
hand track as an echo. The merge now keeps such a link when it leads to the
router's own wire.

Evidence: `tests/test_routing.py`, 11 tests; Last Hit v0.16 routed both
ways into the scratchpad, DRC 0 errors and 0 unconnected on both boards.
## 2026-11-07 — The Last Hit documents, made by the workcenter

The owner asked for every tool the Last Hit work built outside the
workcenter to move into it. This stream took the document scripts: the
table of contents, the datasheet copies, the cost tables, the pictures,
the version copy, the block diagram and the assembly renders. Each is now
a command with tests. `workcenter costs` writes the totals into every file
that marks a place for them; the list table in Last Hit's
`parts/README.md` had stopped at v0.12 (M97). `workcenter pictures` runs
P23 from a manifest, and `tools/scene.py` holds what each assembly script
repeated. `workcenter version new` does P22's copying and banners,
`workcenter diagram` draws a block diagram from a spec, and `gates
--report` fills the gates report's tables round the prose.

I ran each on a copy of the Last Hit repository. `costs` gave all 26
lists byte for byte and every version's totals, $61.76 and $396.86 for
v0.16. `docs v0.16` gave the same datasheet table and removed two stale
copies the old script had left. `version new v0.17` left v0.16 differing
from its commit by its banner alone. `pictures v0.16` redrew 21 of the
README's 22 images in 15 minutes: 35 of its 51 files came out byte for
byte, and the 3D stills differ from the committed ones in under 0.2 % of
their pixels. `gates --report` refilled both boards' tables round the
report's prose.

The assembly rewritten on `tools/scene.py` showed a fault in the old
script. pcbnew hands out copies of a footprint's 3D models, so the
script's path rewrite never reached the saved board; only the two bodies
it also copied were drawn. The scene copies every body the board names,
and the landmine map now says why. Its four stills match the old
script's within 0.08 % of their pixels.

One slip: I wrote the starter diagram spec one folder above my worktree
and moved it in before any commit.

Evidence: `tests/test_doctools.py` (20 tests); `make verify` GREEN, 167
tests.
## 2026-11-07 — Datasheets, decks and CI checks without scratch scripts

The owner asked for every tool the Last Hit work built outside the
workcenter to move into it. This part covers datasheets, simulation and CI.
`workcenter fetch` keeps a part's file and writes its library row.
`workcenter curve` reads a datasheet's curve from the PDF's own lines.
`workcenter sim --deck` runs one deck the gate's way. `design --check` and
`ci` run a board repository's CI steps here. `mutate` runs a firmware's
mutation list. `kicadgen.py symbol-add` draws a symbol from a pin table.

On Last Hit v0.16, the heater deck read 0.505 V through `sim --deck`.
A bare `ngspice -b` read 3.0 V, the trap of M94. The fuse's 1.0 A curve
read 5.77 ms at 4 A, not the scratch script's 6.09 ms. That script
averaged the nearest points, which on a steep stretch weighs one edge more.
The middle of the two edges is 5.77 ms. The mutation run caught all 50
mutations, after one fix in a scratch copy: one mutation's text no longer
matched `app.c`, so the board's own script counts it as a survivor today.
The replay of the board's firmware job tested 12 versions and printed
`CI REPLAY GREEN`. One fetch of the fuse's datasheet returned the bytes its
library row records.

Evidence: `tests/test_fetch.py`, `test_curve.py`, `test_ci.py`,
`test_mutate.py`, new tests in `test_sources.py` and `test_kicadgen.py`;
`make verify` green on `feat/sources-sim`.
## 2026-11-07 — Looking at a routed board before changing it

Five mistakes on Last Hit v0.16 had one cause. A part or a via went onto a
routed board before anyone looked at what was there. Fuse F1 first landed
where the cell's strip stands, which only the assembly script knew. Fuse F2
split a ground pour. F1 also sat on the path the router had used for the
3.1 V feed, and the next route cost two hours. The scripts that found these were
written for one board. The owner asked for every such tool in the
workcenter.

`workcenter inspect` now reads a board with KiCad's own geometry. It draws
each layer of a window, lists what lies there, and probes a new via, track
or part against the DRC's rules and every keep-out by name. It also gives a
net's connected groups, a pour's islands, a path's resistance from the
stackup, and the nets that crossed a spot. On v0.16 the probe finds the
overlap and the keep-out that two of the mistakes hit. The joint's inner
run reads 56.8 mOhm, where an older deck took 10. A design can now keep
parts out of an area, and P29 says how to place a part on a routed board.

Evidence: `tests/test_inspect.py`; the fixture `tests/boards/inspect-four-layer`;
`MISTAKES.md` M87 to M91.

## 2026-11-05 — A verification package an inspector can check

An engineer reviewed the Last Hit board and asked how anyone could check
it: what it must survive, what each part is rated for, and the numbers
behind every claim. The user asked for that as a method in the
workcenter. We wrote it as P28 and the `verification` skill: conditions
first, then requirements with their sources, a cited nodal analysis for
every simulation, and a traceability table. `workcenter verify` now runs
the simulations again and compares every quoted number with the run, so
a reviewer does not have to trust the author.

The first package, on v0.14, found what earlier reviews missed. The
MCU's analog pin takes 4 V at most and has no clamp, so a live USB plug
overstresses it. The board draws 161 µA asleep, not the 50 µA the README
carried over from an older MCU. A shorted cartridge pulls the cell down
so far that the firmware's fast trip never fires. Fifteen of sixty
requirements fail; each has a measured size and a proposed fix. Four
helpers wrote the writeups in parallel, and their reviews caught three of
our own mistakes before the package was done.

Evidence: `tests/test_verify.py`; the Last Hit repository's
`v0.14/verification/`; `MISTAKES.md` M65 to M73.

<!-- Entries below, newest first. -->

## 2026-10-29 — Every input held while the MCU sleeps in reset

The user asked for pull-downs wherever a board needs one, suspecting one had
been missed. An MCU pin is high-impedance from power-up until firmware sets
it, so a MOSFET gate or an enable it drives floats for those milliseconds and
can switch a heater on by itself. The new check reads the schematic's pin
types: a net with a gate, a logic input, a switch or an I2C line, with no
output on it and no resistor to a rail (or a gate to its own source), is
reported. On Last Hit v0.11 it found three nets and no missed pull. The
button relies on the MCU's internal pull-up, which the firmware sets. The
display's I2C lines are pulled up on the display board. Every heater and
protection gate was already held. A design names such nets with their reason
and turns the check into a failure with `check_pulls`.

Evidence: `make verify` green on the branch; `tests/test_pulls.py`.

## 2026-10-29 — The fab's own limits in the DRC

The user asked for a DRC that says whether a board can be made, and chose
Sierra Circuits as the fab. KiCad's DRC already ran on every board, but
against the workcenter's own rules, which nobody had compared with what a
fab publishes. Sierra's Web PCB order page gives the numbers: 4 mil trace and
gap, 6 mil holes and rings, 13 mil from a hole to inner-layer copper, 5 mil
legend lines. They now live in `rules/` as a KiCad rule file, each rule with
the words it came from, and a board can carry them for good (its design
file names the fab) or be checked against them once (`--fab`). Last Hit
v0.11, GREEN on the workcenter's rules, fails 47 of Sierra's: every via's
ring is 0.150 mm against 0.152, its labels are stroked 0.10 mm against
0.127, and inner copper comes within 0.25 mm of the receptacle's plastic
pegs. All three are cheap to fix in the next version; none would have shown
up before the fab's review.

Evidence: `make verify` green on the branch; `tests/test_fab.py`.

## 2026-10-29 — kistack joins the workcenter

The user asked for kistack in the workflow. It is a set of agent skills for
KiCad written by hand at American Embedded: how to wire a schematic, place
parts, lay out, choose parts, make footprints and symbols, export, look at
Gerbers and panelize. Every one was read before it went in, because agents
follow these files. Most of it applies here as written. Three things do not:
it tells an agent to find ways round a site's bot protection, which this
workcenter refuses; it edits the open board in KiCad, where our boards come
from a design file; and its placement checks need a KiCad server, which
KiCad 10's command line cannot run. So the skills sit unchanged under
`third_party/`, a workcenter skill says which to read when and where our
rules win, and a small reader answers the placement checks from the board
file instead of a server. On kistack's own test board they give the answers
its own tests expect.

Evidence: `make verify` green on the branch; `tests/test_placement.py`.

## 2026-10-28 — A cell that was never wired in

The user asked why the Last Hit's battery floated over the board, then
noticed that it had a contact at each end and nothing joined either one.
They were right twice over. When v0.6 traded a pouch cell for a 10440, the
pouch's protection circuit and its plug went with it: the notes still said
the cell protected itself, but the cell chosen is sold unprotected, and its
contacts were a pad for a spring nobody picked and a lead nobody drew. P20
only asked for the old part's ratings, so this became M56 and P20 now asks
what the old part did as well. The fix needs a dual switch whose drains are
joined inside the package, which KiCad's library draws only as two separate
symbols; projects can now bring their own symbol library, the way they
already bring their own footprints.

Evidence: `make verify` green on the branch; the project-symbol test runs
ERC on a schematic that uses one.

## 2026-10-27 — A parts list you can order from

The user asked for every prototype's parts sourced from Digi-Key with the
full cost, and for it to be a workcenter skill. `workcenter procure` now
reads a board's BOM from its schematic, matches each line to a row of a
parts file (the part, its supplier number, the price breaks and stock as the
supplier's page showed them, the date and the page), and writes the list
with the cheapest order per line and the totals per supplier. Buying ten of
a part is sometimes cheaper than buying seven; the command picks the
cheaper. Items off the board, like the cell and the bare boards, are rows
too. Two mistakes on the way became M54 and M55: a product page guessed
from memory came back as the wrong part, and a page that refused a script
was retried in disguise, which the session refused. P25 says how to read a
supplier: its API, or its pages with the fetch tool where it allows that,
the part number checked on the page. Many common capacitors and resistors
show no stock at Digi-Key this month; the list says so line by line.

Evidence: `make verify` green on the branch; the fixture priced to the cent;
the Last Hit parts lists.

## 2026-10-27 — Schematics with wires, and the parts the 3D views left out

The user looked at the Last Hit board and found two things the gates never
did. The schematic was a list of parts with a net name on every pin and no
wire between them; they put it beside a Commodore 64 service sheet. And the
board's underside had no microcontroller in the 3D pictures: KiCad's
footprints name 3D bodies its library does not ship, for three of the
packages we use, and the renders drew bare pads without a word.

The generator now draws wires. A small grid router joins the pins of each
net round the parts, puts a dot where wires tee, turns each power symbol
away from its pin, and writes the net's name once along its wire so the
schematic and the board agree on names. It is off unless a design asks, so
every older version's schematic comes out exactly as before. The first try
drew a power symbol's wire through a neighbouring pin and shorted 3.3 V to
ground; ERC caught it before anything was kept. `workcenter render` now
lists every part drawn without a body, and the model generator makes small
QFN, DFN and SOT bodies from the package drawing.

Evidence: `make verify` green on the branch; the Last Hit v0.10 schematics,
ERC 0/0 and no parity warning; M51, M52, P24.

## 2026-10-23 — The board shrank to an inch and the tools had to grow up

The first board was 22 by 46 millimetres, parts on one face, headers for
the wires. The product is an inch by half an inch, so the second version
had to be that: both faces populated, 0402 parts, through-hole pads for the
battery, the coils and the puff sensor, and a USB-C port on the short edge.
The autorouter could not route it. Routed ground alone used up the board,
so the generator learned copper pours and KiCad fills them without a
window. Then the router, which treats a pour as a plane, let signal tracks
wall ground pads off from it; the generator now reads the filled board
with KiCad's own Python module, drops a via into every island it can, and
routes again with a via reserved beside the rest. The router also gives up
on links a person can see; the design file can now draw those by hand and
the router keeps them. Thirty-odd hand-drawn tracks later the board is
GREEN: no errors, no open connections, every ground pad on the pour. Two
mistakes cost hours: assuming where a mirrored part's pads land, and
hiding apt's output in the install script, which made a slow download look
like a hang in CI. Both are on the landmine map now.

Evidence: ThyFriendlyFox/vape-prototype v0.2 commit on main with `docs/gates.md` GREEN; this repository's PR with the generator changes and 6 new tests.

**Mistakes became a file.** The human asked that every mistake be recorded with a process that prevents it. `MISTAKES.md` now holds the eighteen from these two days, each with its cost and root cause, and `PROCESSES.md` holds the fourteen checklists they produced, from pad geometry before a hand route to closing out a change. `make verify` refuses a mistake with no process and a process with no "Done when". The one that cost most, two hours of hand-routing to pad positions I had worked out in my head, is M11; its process is P1.

## 2026-10-23 — First real board, and the tools it forced into existence

We designed the first real board with the workcenter: a 39-part,
2-layer controller with a battery charger, an LDO, an MCU, and two
switched power channels. The board lives in its own repository, as the
attached-repos rule says; this repository keeps only the tools.

Hand-writing KiCad files does not scale past a few parts, so we built
`kicadgen`: a design is Python, parts come from the installed KiCad
libraries, and the generator writes the schematic, the board, and the
project. The first schematic passed ERC with 0 errors and 0 warnings on
the first run.

Routing broke three times. `kicad-cli` 10 cannot export a Specctra DSN, so
we wrote the exporter. FreeRouting wrote the session at 10 times its
declared resolution, so every track landed off the board; the merge now
reads the scale from the session's placement block. Then 1.0 mm heater
tracks could not enter SOT-23 and TSSOP pads, which the router reports as
unrouted pins, not as an error; 0.6 mm and a sense resistor in front of
the ADC fixed it. FreeRouting 2.1.0 then never finished a job: it checks
GitHub for updates at start, the call fails behind a proxy, and its main
thread sleeps forever after routing. The engine is pinned to 1.9.0, which
has no network code and finishes in under a minute.

We added `workcenter design` and `workcenter render`, a `board-design`
skill, and tests that include a routed round trip.

Evidence: `tests/test_kicadgen.py` green with FreeRouting installed, 22
tests in `make verify`; the first board's gates report lives with that
board.

## 2026-10-22 — Installed the agent kit; the workcenter exists

This repository started empty. We made it the EE Workcenter: a
toolchain installer, a command line that runs 4 gates on a KiCad
project, 5 skills, 3 fixture boards, and the agent kit that governs
work here. The gates are ERC, DRC, SIM, and EXPORT. A board is done
when all 4 are green.

The first install run broke at once: `add-apt-repository` imports a
module that only the system Python has, and the cloud image sets
Python 3.13 as default. We replaced it with a sources file and a
pinned key fingerprint. The second run installed KiCad 10.0.7, ngspice,
Java 21, and the FreeRouting 2.1.0 JAR.

The queue holds 4 items: session import through the IPC API, a reusable
GitHub workflow for board repositories, fabrication rule sets, and an
MCP server. The human has not ranked them yet.

Evidence: `make verify` green at the install commit; the install log in
the session scratchpad; `tests/boards/README.md` for what each fixture
proves.
