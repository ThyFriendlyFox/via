---
name: Legend
description: Makes every text printed on a board readable on the built board - each designator placed round its part by the generator, and every text held by the DRC gate to the fab's least height and stroke, to no overlap with another text, a pad's opening, a hole or the edge, to no designator under a part, near the wrong part or too far from its own, and to 2 directions a side.
---

# Legend

The legend is the board's silkscreen text: each part's designator, a value printed on it, and the texts a
design adds. A text the fab cannot print, or one that sits on a pad, under a part or by the wrong part,
cannot be read once the board is built. `tools/legend.py` judges each text from the board file, and places
the designators itself.

## When

- A design is written or changed, and its board prints designators or texts on the silkscreen.
- `workcenter drc` or `workcenter gates` prints a line that starts `legend `.
- A human asks for the labels on the board to be legible, or not to overlap.

## The rules

| Rule | Fails when | Limit and source |
|---|---|---|
| `size` | A text's height or stroke is under the least the fab prints. | The fab's rule set in `rules/`, read from its own page; the line names the page. A board that names no fab: the least of the 4 fabs (0.8 mm high, PCBWay; 0.0762 mm stroke, OSH Park). A fab whose page names no height leaves the height not judged. |
| `overlap` | A text is on another text of its layer, on a pad's opening in the solder mask of its side, on a hole or a via's hole, or over the board's edge. | `rules/legend.json` |
| `hidden` | A designator is under a part's courtyard or body (its Fab drawing), its own or another's, on its side. | `rules/legend.json` |
| `nearest` | A designator is nearer another part's courtyard than its own, or further than 2.0 mm from its own. | `rules/legend.json`, `designator_reach_mm` |
| `direction` | Texts on 1 side read in more than 2 directions (0 and 180 degrees are 1 direction), or a text on the back is not mirrored. | `rules/legend.json`, `directions_per_side` |

The DRC gate also takes KiCad's own legend checks (`text_height`, `text_thickness`, `silk_overlap` of 2
texts, `silk_over_copper` and `silk_edge_clearance` of a text) as failures, whatever their severity.

A text's box is measured for KiCad's stroke font: 1.34 / 1.27 of the glyph width a character, plus the
stroke; the glyph height plus the stroke. A turned text is measured by the upright box round it. A text in
another font (a `face`), or of more than 1 line, is printed `legend not judged:` with the reason.

## Steps

1. Run the check alone, without KiCad:

       workcenter legend <project>

   - `legend size: ...` - make the text larger in the design (`d.text(..., size=, thickness=)`), or name
     the fab the board is made at (`fab = "<name>"`); the line names the least and its page.
   - `legend overlap: ...`, `legend hidden: ...`, `legend nearest: ...` on a designator - go to step 2.
   - The same on a design's own text - move the text in the design file. The placer never moves it.
   - `legend direction: ...` - turn the design's texts so a side reads in 2 directions; mirror back text.
   - `legend not judged: ...` - use KiCad's stroke font, or 1 line a text, or look at the text in the
     3D render and say so in the README. With `--strict` it fails.
   - `LEGEND HELD` - go to step 4.

2. Let the generator place the designators: in the design file set

       d.place_designators = True

   and to fix 1 designator by hand, `d.designator("U1", x, y, angle)`: the placer leaves it, the check
   still judges it.

3. Write the board again:

       workcenter design <project>/design.py --route

   - `legend: R7 has no place on F.SilkS; its designator is kept on F.Fab` - R7 is still named on the
     assembly drawing. Give it room (move the part), or fix its designator by hand, or leave it and say so
     in the README.
   - Then run step 1 again.

4. Run the gate:

       workcenter drc <project>

   - The summary ends `legend (<fab>): 0 fail, 0 not judged`: the legend is done.
   - A line `legend overlap: KiCad silk_overlap ...` is KiCad's own check: KiCad measured the strokes and
     found 2 texts touching that the boxes did not. Move the text it names.

## A board's designators, seen once

`workcenter legend <project> --show --place <scratch>/<name>.kicad_pcb` puts every designator a design
hid back on the silkscreen, places them all, and judges the copy. The project is not changed.

## What it does not judge

- A design's own art (a logo, a drawing) is judged as a text only when it is a text; drawings are not
  moved or measured.
- Text inside a footprint on a layer that is not the silkscreen.
- The legend's lines and arcs: a fab's least line width is in `rules/README.md`, not here.
