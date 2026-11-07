---
name: Autoroute
description: Routes a board with FreeRouting headless; generated designs round-trip through Specctra DSN and SES automatically, hand-drawn boards supply the DSN.
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

## Known behaviour

- FreeRouting writes session coordinates at 10 times the declared
  resolution. The merge takes the scale from the session's placement
  block, which echoes component positions it knows. Trust the DRC, not
  the resolution token.
- The engine is FreeRouting 1.9.0. Release 2.1.0 checks GitHub for
  updates and, when that fails, sleeps forever after routing without
  saving the session; `install.sh` pins 1.9.0 for that reason. Pass
  `--passes` to trade time for completion.
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
