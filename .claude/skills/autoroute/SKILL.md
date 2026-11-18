---
name: Autoroute
description: Routes a board with FreeRouting headless (1.9.0 by default, 2.5.0 with --router freerouting2); generated designs round-trip through Specctra DSN and SES automatically, hand-drawn boards supply the DSN; lists the rules the workcenter keeps around every router.
---

# Autoroute

FreeRouting routes a board from a Specctra DSN file and writes a Specctra
session (`.ses`). There are 2 ways in:

- **A kicadgen design** (`design.py`, see the `board-design` skill):
  `workcenter design design.py --route` writes the DSN itself, runs the
  router, and merges the session into the generated board. Fully headless.
- **A hand-drawn board**: `kicad-cli` 10 has no Specctra export, so the
  DSN comes from KiCad (File, Export, Specctra DSN) and the session goes
  back in through KiCad (File, Import, Specctra Session).

## When

- `workcenter drc` reports unconnected items on a placed board.
- A generated design is ready for copper.

## Inputs

1. The project directory with a `.kicad_pcb` that has footprints placed
   and nets assigned, or the `design.py` that generates it.
2. `workcenter doctor` shows `freerouting ok` and `java ok`.

## Steps, generated design

1. `workcenter drc .` first. Fix courtyard overlaps and pad clearance in
   the placement; the router cannot.
2. `workcenter design design.py --route --passes 60`. The command prints
   the segment and via counts, how many rounds it took, a `stitch:` line
   for each via it dropped through a pour's island (the net, the island's
   layer and pads, the layer the via reaches), and any ground pad left on
   an island of its pour. Output: `build/route/<name>.dsn`, `.ses`,
   `freerouting.log`, and the routed `.kicad_pcb` with its pours filled.
   A 45-part board routes in under a minute; FreeRouting stops on its own
   when it gives up on a connection. The exit code is the verdict: exit 1
   writes every file and ends on a line that says `red` and names each
   failure (M85).
   - A new version of a routed board (a part added or moved, P22): add
     `--seed <previous>/<name>.kicad_pcb`. The previous board's router
     tracks and vias go in held, so FreeRouting keeps the paths that
     still fit and routes only the rest; the `seed:` line counts
     what was left out (hand copper, stitching vias, copper on a pad,
     other copper, a keepout or the edge) and how many seed tracks the
     new route kept. Without `--seed` the router starts from nothing and
     can move nets far from the change (M89).
3. `workcenter drc .` reports what stayed unrouted. Unrouted nets mean a
   track width that cannot enter a pad, a crowded region, or a part
   placed where the net cannot reach it. Change the design, run again.
   Do not lower clearances. A connection a person can see but the router
   does not find is drawn by hand in the design file (`d.track`, `d.via`;
   see `board-design`); the router keeps it and routes around it.
   FreeRouting's result is deterministic for one input but shifts with
   every hand track added, even one far from the nets it then drops: on
   Last Hit v0.11 a +BATT run along the front edge left the button, a VBUS
   link and a 3.3 V link unrouted on the other side of the board. Find the
   culprit by routing a scratch copy with the new hand copper removed (or
   cut down to its via), and when one run routes a net the next one drops,
   copy that run's tracks for it into the design file. Then route again:
   a run is kept only when the gates are GREEN on it.
4. `workcenter gates .` must be GREEN before the board is called routed.

## Steps, hand-drawn board

1. Export the DSN from KiCad to `<project>/<name>.dsn` or pass `--dsn`.
2. `workcenter autoroute . --passes 20` writes `build/route/<name>.ses`.
3. Import the session in KiCad and save. Without a display, hand the
   `.ses` path to the human with that instruction.
4. `workcenter drc .` again.

## Steps, the routing benchmark

`workcenter bench` routes design files with each router and compares the
runs. Run it before a router or a route option becomes a board's default.
It writes only into `--out`.

1. Copy the boards to a scratch folder first. A run writes the board
   into `--out`, never into the project, but a board that other people
   change while it runs gives numbers for no one version.
2. `workcenter bench <copy>/design.py --out <scratch>/bench --time-limit 300 --threads 2 --order`.
   One line per run:
   - `bench <board> <router>: 33.2 s, 54/54 (100.0 %) joined, 0 DRC errors, 2 commands, 2015 bytes read`:
     judged. The share joined is counted on the routed board (each net's
     pads less 1) against the DRC's unconnected items.
   - `stopped at the time limit (300 s); not judged`: the route did not
     end in time. No number of that run is used. Exit code 2.
   - `not run: no router at <jar>`: the jar is not there. Exit code 2.
   - ``error: the route ended with exit code 1 and no `routed:` line``:
     the route raised or was skipped. Read `route.txt`. Exit code 2.
   - `bench <path>/run.json: not judged: <reason>`: a run file in the
     folder that cannot be read. Its row says `unreadable`. Exit code 2.
   - `<board> takes <router>: <why>`: the router the board takes. Another
     router, or `<router>+order`, takes a board only when it joins as
     large a share with no more DRC errors in no more time, and is better
     in 1 of the 3. When the default did not finish, the line says `not
     judged` and the default stays.
3. `--router NAME=JAR` (repeatable) names each FreeRouting jar to run; the
   first is the default. Without it the workcenter's own jar runs.
   `--time-limit`, `--threads` and `--passes` take a whole number above 0.
4. `workcenter bench --out <scratch>/bench` with no design file rebuilds
   `bench.md`, the table of every run in the folder. It exits 2 when a
   run in the table was not judged.
5. Each run's folder `<out>/<board>/<router>/` holds the board, the
   route's output (`route.txt`), the DRC's (`drc.txt`) and `run.json`.
   A run empties its folder first. Read `route.txt` for a run that is not
   judged.
6. A board's name is its folders from the one above the last version
   folder: `ring-mouse/v0.4/cell`, `universal-controller/v0.2`. 2 designs
   with 1 name, or a folder that holds another design's run, are refused
   (exit 1): give another `--out`.

## Steps, a route in a fixed order

`workcenter design design.py --route --order` routes in 4 stages, 1
FreeRouting run each, each on the copper of the stages before it:

1. `pours`: the nets with a `d.zone`, and every net with copper drawn by
   hand (`d.track`, `d.via`). The router is handed a net's copper only
   with the net, so a net with hand copper is routed in this stage.
2. `fan-out`: the nets of each part whose pins stand 0.5 mm apart or
   closer (P4 step 11). A pin is a copper pad whose number no other pad
   has: an exposed pad and its thermal vias, and paste-only pads, are
   left out.
3. `pairs`: 2 nets whose names differ only in an ending `_P`/`_N`,
   `D+`/`D-` or `DP`/`DN`. A rail `V+`/`V-` or `BAT+`/`BAT-` is no pair.
4. `rest`: every other net with 2 pads or more.

A `stage <n> <name>: <nets> nets, <segments> segments, <vias> vias` line
follows the `routed:` line for each stage; `--json` lists each stage's
nets. `--order` takes no `--seed`.
It is not the default: on the 3-part board of `tests/test_routeorder.py`
it took 21.67 s where the plain route took 6.87 s, both with 0 DRC
errors. Bench it with `--order` before a board takes it.

## Steps, a second router

The routers live in `tools/routers.py`, each with a name, how its
presence and version are found, how it is run on the workcenter's DSN,
and how its log's count is read. `freerouting` (FreeRouting 1.9.0) is
the default. `freerouting2` (FreeRouting 2.5.0) is the second; it is not
the default, because no benchmark of it exists yet (the scope guard of
ROADMAP item 5).

1. `workcenter doctor`. The `freerouting2` row says `ok` when the jar
   and its Java 25 are there. `absent` with no folder: run
   `sudo ./install.sh --freerouting2` (or `INSTALL_FREEROUTING2=1` with
   the full install). It fetches the Temurin 25 JRE and the 2.5.0 jar,
   each checked by its SHA256.
2. `workcenter design design.py --route --router freerouting2 --out <scratch>`.
   Read the lines as for the default router. `route skipped: engine
   missing: freerouting2: ...` names what is missing (the jar, the Java,
   or a Java older than 25): exit 2, nothing routed, and nothing written,
   so a routed board in `--out` stays as it was.
3. `workcenter bench <copy>/design.py --out <scratch>/bench --router freerouting --router freerouting2`.
   The first router named is the default the others are held against.
   A board takes `freerouting2` only on the bench's rule.
4. KiCadRoutingTools is not behind the interface: it reads and writes a
   `.kicad_pcb`, not a DSN, so the DSN rules below would not reach it.

## The rules around a route

These are the workcenter's, not the router's. A second router runs inside
all of them; `tests/test_routers.py` holds each with a stand-in router
(a program that writes a known session), so none of them needs a real
router. The number is the test's rule number.

Before the route:
1. The DSN is written from the design in the same command, over any DSN
   left in `build/route` (P4 step 1). A `<board>.rules` beside it is
   removed before the router starts: FreeRouting 2.5.0 reads one when
   none is named and applies its clearances, net classes and vias over
   the DSN's (its `command_line_arguments.md`, the `-de` entry).
2. A session left by an earlier run is removed before the router starts;
   a router that writes none has failed.
3. An absent router skips the route as an absent engine (exit 2), names
   what is missing, and writes no file: a routed board stays as it was.
4. `--order` with `--seed` is refused before the router runs (exit 2).
   Also before the route, and not the router's: via sizes against the
   board's rules and hand vias' places (M46, M40, M41), parts in a
   keep-out or off the board, floating inputs, simulation problems; each
   makes the run red.

What the router is handed (the DSN):
5. A poured net (`d.zone`) is a plane: the router routes no track for it
   (P4 step 12).
6. Hand copper (`d.track`, `d.via`) is fixed wiring, `(type fix)`.
7. The router's echo of hand copper is dropped on the way back, and a T
   onto a hand track is split into 2 proper ends.
8. A seed (`--seed`) goes in held as `(type shove_fixed)`; its loose ends
   unfixed; what is left out is counted (M89, M147).
9. `--order` runs the router once per stage (pours, fan-out, pairs,
   rest), each DSN listing its nets and the ones before.
   Also in the DSN, held by `test_routing.py`: each via's and drilled
   pad's copper grown by the layer's hole clearance (M79), the net
   classes' widths and vias, and the vias reserved beside island pads.

The run:
10. Passes (`--passes`, `-mp`, default 60), threads (`--threads`, `-mt`
    only above 0) and `-dct 0` (no 20 s dialog wait) are the workcenter's.
11. The time limit (`--timeout`, default 900 s) stops the router and every
    process it started; nothing is read, since a session is written only
    at the end (M128). 1 line, exit 1, no board written.
12. FreeRouting 1.9.0 runs under `xvfb-run` where there is no display.
    FreeRouting 2.5.0 runs with `--gui.enabled=false` and needs none.
13. The router's output is kept in `build/route/freerouting.log` (a stage's
    in `<name>.<n>-<stage>.log`), and the `routed:` line names it.
14. A router that fails (exit code not 0) is 1 line, `route failed: ...`,
    exit 1; nothing is merged and no board is written.

What is read back:
15. The router's own count is the verdict: above 0, exit 1 and a red
    last line. FreeRouting 2.5.0 writes it in its score, `(N unrouted and
    M violations)`, after `final score:` (headless) or `with the score
    of` (with a window), 1 line per stage; the last line counts. Its `M`
    is printed as `router violations: M ...; not judged here`: the DRC
    judges clearances. FreeRouting 1.9.0 writes no count: rules 16 and 17.
16. No count and no copper on any net that needs it: every connection is
    counted open (each net's pads less 1).
17. No count and some copper: `DRC decides`, exit 0.
18. The DRC decides what stayed open: `workcenter drc` counts the
    unconnected items on the written board (P4 "Done when").
    Also after the route, held by `test_routing.py` with the real router:
    pours filled, a via dropped through each island, and the route run
    again with vias reserved, up to `--rounds` (default 4); it stops
    early when no island is left or no via can be reserved.

The second router:
19. `--router freerouting2` adds `-da`, `--gui.enabled=false` and its
    settings folder in `build/route/freerouting2`; every other rule is the
    same code.
20. On a Java older than 25 it is an absent engine: its classes are of
    version 69, which Java 21 (65) cannot read.

## Known behaviour

- FreeRouting writes session coordinates at 10 times the declared
  resolution. The merge takes the scale from the session's placement
  block, which echoes component positions it knows. Trust the DRC, not
  the resolution token.
- The engine is FreeRouting 1.9.0. Release 2.1.0 checks GitHub for
  updates and, when that fails, sleeps forever after routing without
  saving the session; `install.sh` pins 1.9.0 for that reason. Pass
  `--passes` to trade time for completion. Releases 2.2.2, 2.4.1 and
  2.5.0 hold class files of version 69 (the header of
  `app/freerouting/Freerouting.class` in each jar); the workcenter's
  Java 21.0.13 reads up to version 65 (`java -XshowSettings:properties
  -version` prints `java.class.version = 65.0`). None of them has been
  benchmarked.
- `-da` stops FreeRouting 2.5.0's usage data, not its version check. No
  flag or setting stops that: each run asks api.github.com for the latest
  release, under its own User-Agent `Freerouting-Version-Checker`, not
  the workcenter's `ee-workcenter/1.0` (read with `javap` in
  `app.freerouting.Freerouting` and `app.freerouting.util.VersionChecker`
  of the pinned jar). It runs on a daemon thread with a 5 s timeout, so it
  does not hold the route as 2.1.0's did.
- Per-net widths and vias come from `d.net_classes`; FreeRouting honours
  them through DSN classes. The DRC checks them through the project's
  net class patterns.
- A `d.zone` pour is a plane to the router: it routes no track for that
  net and treats its pads as connected. Other nets' tracks cross the
  plane and KiCad fills around them, so a pad can end up on an island.
  After each route the design command reads the filled board with
  KiCad's `pcbnew` module, drops a via through every island it can, and
  for the rest reserves a via beside the pad and routes again (up to
  `--rounds`, default 4). What it still reports as an island needs a
  placement change.
- Hand-routed tracks and vias go to the router as fixed wiring. The
  session echoes them, sometimes cut at another point or extended into a
  pad centre; the merge drops the echoes and splits a track where the
  router joined one onto it, so the DRC sees no dangling ends.
- Seed copper (`--seed`) that connects goes in as `(type shove_fixed)`:
  FreeRouting may push it aside but never rips it up or reworks it. Seed
  copper that hangs from nothing (a moved part's old tracks) goes in with
  no type, unfixed: the router extends it to the part's new pads or
  removes it as a tail. Seeded all unfixed, Last Hit v0.16's display board
  kept 85 of v0.15's 117 router tracks, where an unseeded run kept 116;
  held, it keeps 116 and the base board 76 of 87 (63 unseeded).
- A hole keeps each layer's hole clearance from other nets' copper (a
  fab's `(layer inner)` rule, Sierra's 13 mil). FreeRouting 1.9.0 knows
  copper clearances only: a `via_wire` clearance in the DSN's structure
  changes nothing, and one in a net class covers that class's own vias
  and wires, not a via beside another class's track (measured on a
  fixture). So the DSN grows each via's and drilled pad's copper on the
  layers where the hole rule is the larger one (a 0.6/0.25 mm via is
  0.6104 mm on In2 at a 0.15 mm clearance); the DRC sees the real via
  (M79).

## Checks

- DSN, SES, and the log stay in `build/`, never in the repository.
- A routed board goes through `board-gates` before it is called done.
- The `.kicad_pcb` is regenerated from the design, never patched by hand.
