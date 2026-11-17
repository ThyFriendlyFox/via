---
name: Highspeed
description: Holds a board's fast nets to their interface's rules - the track width a cross-section solver gives for the interface's impedance on the board's own stackup, the length, the skew within a pair and an unbroken reference plane - and writes the same limits as KiCad rules for length, skew, width and pair gap. Every limit names its document, clause and page.
---

# Highspeed

A USB pair routed at the default width is the wrong impedance, and nothing in
ERC or DRC says so. `workcenter highspeed` takes the limits from the
interface's own document, solves the width on the board's stackup, and judges
the board file. Each line that fails names the net, the layer, the value, the
limit and the document with its clause and page.

## Files

- `interfaces.json` beside the board, 1 line for each interface:

      {"interfaces": [
        {"interface": "ti-am57xx-usb2", "nets": ["USB_D_P", "USB_D_N"], "gap": 0.2}
      ]}

  `nets` is the pair, P then N, as the schematic names them. `gap` is the
  gap you mean between the 2 tracks, edge to edge, in mm. It may be left
  out. The command measures the gap on the board either way and solves the
  width at the measured gap; a `gap` the board does not have fails.
- `rules/interfaces/<name>.json` in the workcenter: 1 file for each
  interface, each limit with its document, revision, clause, table and page
  (`rules/interfaces/README.md` lists them).

## Steps

1. Write `interfaces.json` as above. Pick the interface whose document
   governs the chip: the chip maker's layout note when the chip has one
   (`ti-am57xx-usb2`), else the bus's own (`usb2`, `usb3`).
2. Run `workcenter highspeed <project>`. It takes 10 to 20 s for each layer
   a pair runs on.
   - `rules F.Cu: width 0.3122 mm (0.2517 to 0.3865) at the board's 0.2 mm
     gap ...`: the width the solver gives for the nominal impedance at the
     gap the tracks have, and the band for the limits. Draw the pair at the
     first number: set the net class width, or `d.track(..., width=)` in
     the design file.
   - `FAIL highspeed.width: ...`: a track is outside the band. Change its
     width in the design file to the first number of the `rules` line and
     regenerate.
   - `FAIL highspeed.gap: ... mm of the pair runs ... mm apart ...; limit
     ... the gap interfaces.json gives`: that part of the pair runs at
     another gap than `interfaces.json` gives (each part is judged, not only
     the most of the length). Move the tracks, or correct `gap`.
   - `highspeed.gap: ... Z_diff ... ohm there at its tracks' widths`: with
     no `gap` given, the width is judged at the gap of the most of the
     length and each other gap is solved at the tracks' own widths; out of
     the band, it fails. Bring that part to the main gap.
   - `NOT JUDGED highspeed.coupling: ... has no parallel track of <net>
     beside it ...`: a stretch of one net with no partner (the 2 tracks part
     in a V, a loop, a stub), with its length and where it is. Route the 2
     together. Under a TI file a stretch within 6.35 mm (0.25 in) of the
     pair's pads is break-out and holds (SPRAAR7J 3.3, page 10).
   - `NOT JUDGED highspeed.width: GND is poured on <layer> itself ...`:
     ground on the track's own layer within 3 times its height over the
     plane (coplanar ground). The solver puts no ground there, so the width
     is not judged. Pull the pour back past that distance, or judge the
     width with a coplanar field solver by hand.
   - `NOT JUDGED highspeed.length` (and `skew`, `plane`): `... its tracks do
     not reach J2 pad 1 ...`: the route is not finished. Finish it.
   - `FAIL highspeed.stitching: ...`: a via of the pair moves it to a layer
     over other ground planes with no ground via within 5.08 mm (200 mil,
     SPRAAR7J 2.4, page 8). Add one beside it.
   - `FAIL highspeed.spacing: ...`: a track of another signal runs nearer
     the pair than 0.762 mm (30 mil, Table A-2). Move it.
   - `NOT JUDGED highspeed.width: ... has no track on ...` or `... never
     run side by side ...`: the 2 nets do not run together on that layer.
     Route them side by side.
   - `NOT JUDGED highspeed.<rule>: ... no track of <net> on the board`: the
     pair is not routed. Route it and run again.
   - `FAIL highspeed.vias: ...`: a net has more vias than the document
     allows. Route it with fewer layer changes.
   - `FAIL highspeed.length: ...`: a net is longer than the limit (or its
     delay, when the document sets a delay). Move the parts closer, or route
     shorter.
   - `FAIL highspeed.skew: ...`: the 2 tracks differ by more than the limit.
     Add length to the shorter track near the end where they part.
   - `FAIL highspeed.plane: ...`: the track runs over a gap in a ground
     plane that bounds it (below, and above for an inner layer), between
     the 2 points it gives. Route the pair where the plane is whole, or
     close the gap in the pours. `... is of VBUS, not a ground`: the
     nearest pour is a power net; put a ground pour there.
   - `NOT JUDGED highspeed.<rule>: ...`: the interface's documents set no
     such limit, or set one the command does not judge (`single_ended`,
     `stubs`, `test_points`, `clock_spacing`, `plane_edge`, `voids`); the
     line says which. It does not fail the
     run; with `--strict` it does. Do not type a number to fill it: add a
     document that sets it (step 4), or judge it by hand and say so in the
     project's README.
   - `NOT JUDGED highspeed.width: the stackup gives no epsilon_r ...`: set
     the dielectric's er in the board's stackup.
   - `FAIL highspeed: ...` with no rule: the files are wrong (an unknown
     interface, a net the board does not have, no stackup, a stackup layer
     or sublayer with no thickness, a gap that is not a number above 0, an
     `interfaces.json` of another shape). Correct what it names. A
     dielectric of several sublayers is read sublayer by sublayer, each with
     its own er.
3. Run KiCad's DRC with the rules the command wrote:
   `workcenter drc <project> --fab <project>/build/highspeed/highspeed.kicad_dru`.
   It judges the same width, length and skew. Its `diff_pair_gap` rule
   reads only nets whose names end in `_P`/`_N` or `+`/`-`: for a pair
   named `USB_DP`/`USB_DM` it judges no gap, and step 2's gap line is the
   only judge. Each violation names the rule it broke,
   `ti-am57xx-usb2 USB_D_P/USB_D_N width F.Cu` and the like (on the
   fixtures: `track_width` and `skew_out_of_range`).
4. A new interface: copy the closest file in `rules/interfaces/`, read every
   number from the document (never from memory), and write its clause, table
   and page in `where`. A limit the document does not set gets
   `not_stated` with what the document says instead.
5. Done when `workcenter highspeed <project>` prints `HIGHSPEED HELD`,
   each `NOT JUDGED` line is answered in the project's README, and step 3
   prints no violation. With `--strict` a `NOT JUDGED` line fails the run:
   the TI files' `single_ended`, `stubs`, `test_points`, `clock_spacing`,
   `plane_edge` and `voids` lines always do.

## What it does not judge

- Via barrels in a length; the line says how many it left out.
- TI's single-ended impedance, stubs, test points, the 50 mil to a clock,
  the 90 mil from the plane's edge and the 1.5 W from its voids
  (`NOT JUDGED` lines).
- The impedance of a stretch of one net with no partner beside it
  (`NOT JUDGED highspeed.coupling`).
- A width beside ground poured on its own layer within 3 heights
  (`NOT JUDGED highspeed.width`).
- The length, skew and plane of a net whose tracks do not reach every pad
  of it (`NOT JUDGED`).
- The solder mask over an outer layer: the solver puts air there.
- A pad, the edge of the board or a pour of a signal net beside a track:
  only the spacing to another signal's tracks is judged.
- A ground is a net named GND or VSS, or whose name begins or ends with
  GND; a pour of any other net is not a reference plane.
- Any interface not in `rules/interfaces/` (DDR is not there: JEDEC's
  documents need an account).
