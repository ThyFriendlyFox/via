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
| `size` | A text's height or stroke is under the least the fab prints. | The fab's rule set in `rules/`, read from its own page; the line names the page. A project whose rule set was copied from a file outside `rules/` is held to its own copy. A board that names no fab: the least of the 4 fabs for each size (0.8 mm high, PCBWay; 0.0762 mm stroke, OSH Park). A fab whose page names no height leaves the height not judged. |
| `overlap` | A text is on another text of its layer, on a pad's opening in the solder mask of its side, on a hole or a via's hole, or off the board: over its edge, outside its outline, in a notch or in a cutout (a footprint's own Edge.Cuts slot included). | `rules/legend.json` |
| `hidden` | A designator is under a part's courtyard or body (its Fab drawing), its own or another's, on its side. A part is the hull of its courtyard and body, turned with it. | `rules/legend.json` |
| `nearest` | A designator is nearer another part's courtyard than its own, or further than 2.0 mm from its own. | `rules/legend.json`, `designator_reach_mm` |
| `direction` | Texts on 1 side read in more than 2 directions (180 degrees is a direction of its own: KiCad prints a board text at 180 upside down; a footprint's text it keeps upright, at 0, unless the text is written `(unlocked yes)`), or a text on the back is not mirrored. | `rules/legend.json`, `directions_per_side` |

The DRC gate also takes KiCad's own legend checks (`text_height`, `text_thickness`, `silk_overlap` of 2
texts, `silk_over_copper` and `silk_edge_clearance` of a text) as failures, whatever their severity. The
mask or the edge clipping a footprint's own silk outline is not a legend line.

A text's box is measured for KiCad's stroke font: 1.34 / 1.27 of the glyph width a character, plus the
stroke; the glyph height plus the stroke. That is the font's average advance, not each glyph's ink: wide
glyphs print wider than the box. kicad-cli 10.0.8 plotted "WWWWWW" (1 mm, 0.15 mm stroke) 6.722 mm wide
against a box of 6.481 mm, 0.121 mm out on each side (the second review's p1-probe), so
`workcenter legend` alone can miss an overlap of up to about 0.12 mm a side; the DRC gate's KiCad
`silk_overlap` and `silk_over_copper` measure the ink. A turned text is measured by the upright box round it. A text
justified top hangs half its height below its anchor; justified bottom, it stands half its height above.
A text with no `(thickness)` has KiCad's own stroke, 1/8 of its glyph width (the second number of `(size h w)`). A title block variable
(`${TITLE}`, `${REVISION}`, `${ISSUE_DATE}`, `${COMPANY}`, `${COMMENTn}`) is measured as its value.

These are printed `legend not judged:` with the reason, and fail with `--strict`: a text in another font
(a `face`), of more than 1 line, or holding another text variable; a knocked-out text (KiCad fills an
area round it larger than the box); a text box; a dimension, a table or a barcode on the silkscreen; a
designator whose part has no courtyard, body or pad, or is on the other side; the height or the stroke
where the fab names no least for it; the edge of a board with no outline on Edge.Cuts. A part's own field
shown on the silkscreen (an MPN) is judged as a text.

A board file the tool cannot read (no file, not a board, an item with no `(at)`, a text of size 0) is
refused: `legend: refused: <file>: <what>`, exit code 2; `<what>` names the item, and its place on the
board where it has one (`gr_text "AB" has no (at)`, `gr_text "AB" at (120, 110): its size 0 x 0 mm is not
a size`). A fault of the tool itself is refused the same way. Red is exit code 1.

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
- A glyph's width, or its width against its height: a text squashed to 0.2 mm wide is judged on its
  height and stroke only. No fab in `rules/` names a least glyph width (PCBWay's "Minimum Character
  Width (Legend) 0.15mm" is the stroke, `text_thickness`).
- Each glyph's ink: see the box above.
