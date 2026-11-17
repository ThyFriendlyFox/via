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
  gap between the 2 tracks in mm; without it the board's Default net class
  clearance is the gap.
- `rules/interfaces/<name>.json` in the workcenter: 1 file for each
  interface, each limit with its document, revision, clause, table and page
  (`rules/interfaces/README.md` lists them).

## Steps

1. Write `interfaces.json` as above. Pick the interface whose document
   governs the chip: the chip maker's layout note when the chip has one
   (`ti-am57xx-usb2`), else the bus's own (`usb2`, `usb3`).
2. Run `workcenter highspeed <project>`. It takes 10 to 20 s for each layer
   a pair runs on.
   - `rules F.Cu: width 0.3122 mm (0.2517 to 0.3865) ...`: the width the
     solver gives for the nominal impedance, and the band for the limits.
     Draw the pair at the first number: set the net class width, or
     `d.track(..., width=)` in the design file.
   - `FAIL highspeed.width: ...`: a track is outside the band. Change its
     width in the design file to the first number of the `rules` line and
     regenerate.
   - `FAIL highspeed.length: ...`: a net is longer than the limit (or its
     delay, when the document sets a delay). Move the parts closer, or route
     shorter.
   - `FAIL highspeed.skew: ...`: the 2 tracks differ by more than the limit.
     Add length to the shorter track near the end where they part.
   - `FAIL highspeed.plane: ...`: the track runs over a gap in the plane on
     the layer the line names, between the 2 points it gives. Route the pair
     where the plane is whole, or close the gap in the pours.
   - `NOT JUDGED highspeed.<rule>: ...`: the interface's documents set no
     such limit; the line says what they do say. It does not fail the run;
     with `--strict` it does. Do not type a number to fill it: add a document
     that sets it (step 4).
   - `FAIL highspeed: ...` with no rule: the files are wrong (an unknown
     interface, a net the board does not have, no stackup). Correct what it
     names.
3. Run KiCad's DRC with the rules the command wrote:
   `workcenter drc <project> --fab <project>/build/highspeed/highspeed.kicad_dru`.
   It judges the same width, length and skew, and the pair's gap, which
   `highspeed` writes but does not judge itself. Each violation names the
   rule it broke, `ti-am57xx-usb2 USB_D_P/USB_D_N width F.Cu` and the like
   (on the fixtures: `track_width` and `skew_out_of_range`).
4. A new interface: copy the closest file in `rules/interfaces/`, read every
   number from the document (never from memory), and write its clause, table
   and page in `where`. A limit the document does not set gets
   `not_stated` with what the document says instead.
5. Done when `workcenter highspeed <project> --strict` prints
   `HIGHSPEED HELD` and step 3 prints no violation.

## What it does not judge

- Via barrels in a length; the line says how many it left out.
- The pair's gap (KiCad's DRC does, step 3).
- The solder mask over an outer layer: the solver puts air there.
- Any interface not in `rules/interfaces/` (DDR is not there: JEDEC's
  documents need an account).
