# Board rule packs

A board rule pack holds a standard's limits for the copper of a board: the gap between 2 conductors for
the voltage between them, and the width of a track and the count of vias for the current they carry.
Each number stands with its document, clause, table and page. A pack never holds the standard's text.

A project names its pack in `board-rules.json` beside its board:

    {"pack": "ecss-q-st-70-12c-rev1"}

`workcenter drc` and `workcenter gates` then hold the board to it, after KiCad's own rules. The voltage
of each net and the current on it come from the project's `ratings.json` (`workcenter ratings`): its
`nets` give each net's span of volts, its `parts` give the amps on a pin, or through a part of 2 pins.
The DRC line names the pack: `board rules ecss-q-st-70-12c-rev1: 2 fail, 0 not judged`. A pack may also
be a file of the project's own, named by its path from the project's folder.

## How each limit is judged

- **Gap.** For each pair of nets with a voltage between them, the voltage is the most their 2 spans
  allow (13.8.2b asks the peak). KiCad's DRC measures every gap on a copy of the board with 1 rule for
  each pair and each copper layer, in `build/board-rules/`. Only the violations of those rules count.
  The file also holds 1 witness rule for each net, which fails on every item of the net. If KiCad's
  report names no violation of a net's witness, KiCad did not read that net's rules, and the gate is
  red: `kicad-cli did not read the pack's rules`.
- **A net name a rule cannot hold.** A rule quotes a net name in `'...'` inside `"..."`. A name with
  `'`, `"`, `\`, `*` or `?` gets no rule, and its gaps are not judged. So does a name that differs
  from another only in case: KiCad compares names in a rule without case.
- **Copper thickness.** An outer layer is its foil plus 25 um of plating (7.4.2c NOTE 2, page 44;
  tables 7-3 and 7-4, pages 45 and 46). 35 um foil is 60 um: table 13-7's Th <= 70 um column. 70 um foil
  is 95 um: its Th > 70 um column, and 70 um of width tolerance.
- **Track width.** For each track of a net with a current, the least width as designed: the model of
  annex D at the rise the pack allows, on the copper as manufactured (table 7-1), widened for the
  manufacturing tolerance (table 7-3). An outer layer carries 0.9 of the model (13.6.4.2a). A board of
  1.5 to 1.8 mm rises 1.2 times as much (13.6.4.2b).
- **The current on a net** is the sum of the currents `ratings.json` states on its pins; a part of 2
  pins counts on both its nets. A track that feeds 2 loads carries both. Where a source and its loads
  are all stated, the sum counts the current 2 times.
- **The board's area** is the area inside its outline on Edge.Cuts: lines and arcs joined end to end,
  rectangles, polygons and circles. The greatest outline is the board; the others are its holes. An
  outline that does not close, or holds a curve, has no area, and no width is judged.
- **Via count.** The vias of a net that join the same pieces of copper share the current. A via is a
  track of its wall's section (13.6.3f). A group holds at least the net's current divided by 1 via's.

## Layout packs

A layout pack (`"kind": "layout"`) holds rules a maker's note states about where parts and copper go.
A project names them in `board-rules.json` under `layout`, with or without `pack`, and states what the
board file cannot say:

    {"layout": ["ti-slva680a-esd", "ti-szza009-emi"],
     "connectors": {"J1": "the USB cable"}, "inside": ["J2"],
     "protectors": {"D1": "TPD2E2U06"}, "ground": ["GND"], "power": ["VBUS", "GND"]}

A connector is a part whose reference is J or P and digits (IEEE 315's letters), or whose footprint is in
a KiCad library whose name starts with `Connector` (`Connector_USB`, `Connector_JST`, ...). One not named
in `connectors` or `inside` is `not judged`. A `connectors` with no part is `not judged` too: the pack
then judges no line. A connector with another reference and a footprint of another library is found by
neither: name it in `connectors`. The DRC line names every pack:
`board rules ti-slva680a-esd + ti-szza009-emi: 0 fail, 0 not judged`.

Both packs read the copper of a net as a graph. Its points lie on the centre lines of the tracks: each
track's ends, where another track's end lands inside its copper, where 2 tracks cross, and where a via,
a pad or a pour touches it. A via joins its layers and ends nothing. A pad or a pour is an end. Lengths
are along the centre lines, from pad centre to pad centre.

### ti-slva680a-esd

TI SLVA680A, "ESD Protection Layout Guide", Rev. A, April 2022, https://www.ti.com/lit/an/slva680/slva680.pdf.
Read 2026-11-17, with no second reader yet. For each pin of a connector in `connectors` whose net is not
ground:

| Rule | Where | Judged |
|---|---|---|
| `protector` | section 1 and figure 1-2, page 2 | a part in `protectors` stands on the net, and has a pad on a net in `ground` |
| `nearest` | section 2.1, Summary, page 4 | the shortest copper from the connector's pad to the protector's meets no other part's pad; every other part's pad on the net stands further from the protector's pad than that pad from the connector's, centre to centre, and lies further along the copper too |
| `no-via` | section 2.1, page 4; section 2.3, page 6 | the connector's pad and the protector's pad lie in 1 piece of copper on 1 layer |

The protector is the nearest part of `protectors` with a pad on ground, centre to centre. A part at the
same distance as the protector fails: the note asks further. Not judged, and named in the pack: the stub
between the TVS and the line, whether the TVS's ground pad reaches the ground plane and by what
inductance, unprotected traces beside the path and its corners (section 2.2, page 6), the ground scheme
(section 2.4), and how much further the protected part stands ("much further"): the check holds further.

### ti-szza009-emi

TI SZZA009, "PCB Design Guidelines For Reduced EMI", November 1999, https://www.ti.com/lit/an/szza009/szza009.pdf.
Read 2026-11-17, with no second reader yet.

| Rule | Where | Judged |
|---|---|---|
| `power-ratio` | section 2.1.1, page 4; section 2.2.4, page 10 | on a board of 2 copper layers, each trace of a net in `power` or `ground` is at most 3 times as long as its narrowest width |

A trace runs between 2 ends, pads or pours, that the copper joins without passing another end. Its
length is the shortest way along the tracks, through vias, joins, overlaps and stubs; its width is the
narrowest track on that way. 2 tracks between the same 2 ends count as 1, the shorter. A pour is no trace
and is not judged. A board of another count of layers gets a note.

## Creepage packs

A creepage pack (`"kind": "creepage"`) holds a document's tables of clearance and creepage by voltage.
Clearance is the gap through air. Creepage is the way along the surface of the board. The 2 are
different quantities, and each table names which it is. A project names 1 creepage pack under
`creepage` in `board-rules.json`, with the conditions the pack asks:

    {"creepage": {"pack": "mil-hdbk-454c-g69", "condition": "A", "enclosure": "I"}}

The voltage between 2 nets is the most their spans in `ratings.json` allow, as for the gap of the
voltage pack. `tools/creepage.py` judges every pair of nets with a voltage between them, on each outer
layer:

- **The copper** is read as polygons: a track with round ends, an arc track as a band round its curve
  in 64 steps with its 2 round ends, a pad as its rectangle or circle, a via as a circle, a filled zone
  as KiCad filled it. A circle is drawn as 16 sides round it. A gap is never read larger than it is: at
  most r x (1 / cos(pi / 16) - 1) smaller at a round end of radius r, 0.0049 mm on a 0.5 mm track. A
  pad's angle is the one in its own `(at x y angle)`, the board's: KiCad leaves it out at 0 degrees,
  whatever the footprint's angle. A pad whose copper stands off its hole (`(drill ... (offset x y))`)
  is read as a square round its hole, widened by the offset on each side. A trapezoid pad is read as
  its rectangle. A custom pad is taken as a square of its anchor's greater side, and one with
  primitives is named `not judged`, as is a pad with a padstack and any shape drawn on an outer copper
  layer:
  `not judged creepage on F.Cu: 1 shape drawn on the copper is not read (a gr_line at (112.5, 105))`.
- **Copper with no net** (a pad, a track, a via or a zone) is a conductor the 2 nets' way can cross.
  The shortest way from 1 net to the other across 1 or more such conductors is the sum of the gaps;
  their own width counts nothing. A pair that holds on its straight gap but has such a way under the
  pack's distance is `not judged`: `... 1.6 mm across copper with no net (a pad with no net at
  (112.5, 107.5)), under the 3 mm asked at 400 V`.
- **Between the 2 faces.** A pair with 1 net on F.Cu and the other on B.Cu has a way round the board's
  edge or through a hole. It is not measured. The pair holds only when the least length such a way can
  have reaches the pack's distance: the 2 nets' gaps to the nearest side of Edge.Cuts or of a hole
  with no plating, plus the board's thickness; and never less than the way along 1 face between the 2
  outlines. Through air: sqrt((the 2 gaps)^2 + thickness^2), and never less than the straight gap in 3
  dimensions. Otherwise `not judged`: `creepage HV on F.Cu to GND on B.Cu at (109, 100.3): at least
  2.2 mm round the board's edge or through a hole, 3 mm asked at 400 V`. Copper with no net within the
  pack's distance of either net makes the pair `not judged` too. A shape on Edge.Cuts that is not read
  (a curve, a footprint's line) leaves only the thickness.
- **Clearance** is the straight gap between the 2 nets' copper.
- **Creepage** is the straight gap, unless a slot stands on it. A slot is an inner cut of Edge.Cuts with
  4 corners, convex. The way then goes round the slot's corners: the shortest way on a graph of the
  slots' corners and the copper's corners and nearest points. A slot narrower than the pack's least
  width is crossed as if it were not there. A pack with no least width prints the pair `not judged` when
  only a slot makes it pass. Any other inner cut near the pair (a circle, an arc, an outline that does
  not close) makes it `not judged`.
- **Between rows.** A table of ranges (`"between_rows": "range"`) takes the row whose range holds the
  voltage; at the boundary of 2 rows, the stricter. A table of points (`"points"`) passes a gap at or over
  the next row up and fails a gap under the row below; a gap between the 2 is `not judged`. Under the
  first row, a gap under its distance is `not judged`. Over the last row, every pair is `not judged`.
  A pack whose column falls as the voltage rises is refused: the rule needs each column to rise.
- **A slot too narrow.** When a pair fails and a slot narrower than the pack's least width stands on
  its straight gap, the slot fails on its own line: `fail slot /HV to GND on F.Cu at (112.1, 105): 0.8
  mm wide, at least 1 mm to lengthen the way (pollution degree 2)`.
- **Inner layers** have no surface: 1 `not judged` line for each inner layer that holds copper of 2 nets
  with a voltage between them.
- **A pack of a project's own** is refused, with its file and place, when a table of ranges does not
  start at 0 V, a condition's value holds a space, `slot.least_mm` is not an object, or a pack with no
  clearance table has no first `not_judged` line to say why.
- **Speed.** Each polygon keeps its box and its edges in a grid, and only a gap under the pack's
  distance is looked for. A board of 150 nets and a zone of 4000 corners is judged in seconds.

The DRC line names the pack: `board rules mil-hdbk-454c-g69: 1 fail, 0 not judged`. A failure is 1 line:

    fail creepage /HV to GND on F.Cu at (110.85, 106.65): 2 mm along the surface at 400 V, at least 3 mm (condition A, enclosure I) [MIL-HDBK-454C: guideline 69, 4.1 page 69-1; table 69-I, leakage distances, page 69-2]

### How to run it

1. State each net's voltage: `workcenter ratings <project> --init`, then fill `nets` in `ratings.json`
   with each net's span of volts and its source. A net with no span prints
   `not judged creepage of NET: ratings.json states no voltage for it`: give it a span.
2. Name the pack and its conditions in `board-rules.json` under `creepage`. A missing or unknown condition
   stops the run on 1 line that names it and lists the values the pack takes.
3. Run `workcenter drc <project> --strict`.
   - `fail clearance A to B on LAYER at (x, y): ...`: move the 2 nets' copper apart by at least the
     difference of the 2 numbers.
   - `fail creepage ...`: move them apart, or cut a slot between them at least as wide as the pack's
     least slot width (`ti-slup419-creepage`: 1.0 mm at pollution degree 2), then run step 3 again.
   - `not judged creepage ... lies between X mm (V0 V) and Y mm (V1 V)`: the document gives no number
     at this voltage. Move the copper to Y mm, or find a document with a row at this voltage.
   - `not judged ... the pack states no least width for a slot`: only a slot makes the way long enough,
     and the document does not say a slot counts. Move the copper apart.
   - `not judged creepage on In1.Cu`: no pack here judges copper inside the laminate. Keep the 2 nets on
     the outer layers, or judge them by another document.
   - `not judged creepage A on F.Cu to B on B.Cu ... round the board's edge or through a hole`: move
     the copper of either net away from the edge or the hole until the sum of the 2 gaps and the
     thickness reaches the distance.
   - `not judged ... across copper with no net`: give the copper a net, or move it out of the way.
   - `fail slot ...`: widen the slot to the pack's least width.
4. GREEN when the line reads `0 fail, 0 not judged`.

### mil-hdbk-454c-g69

MIL-HDBK-454C, "General Guidelines for Electronic Equipment", 21 September 2021, guideline 69, from
the Defense Logistics Agency's ASSIST (https://quicksearch.dla.mil/qsDocDetails.aspx?ident_number=115984,
image "Revision C", 158 pages). Free from its issuer. Read 2026-11-17, with no second reader yet. Each
download carries its own time stamp on every page, so each one has a SHA256 of its own: the index names
the copy the pack was written from. The pack's `text` holds what a second reader can match: the SHA256
of the text of PDF pages 129 and 130 (69-1 and 69-2), from `pdftotext -f 129 -l 130 -layout` (poppler
24.02.0), with each line that holds `Source: https://assist.dla.mil -- Downloaded: ` removed. 2
downloads of 2026-11-17 gave the same, b2547e85...

| What | Where | Numbers |
|---|---|---|
| Clearance and leakage (creepage) | 4.1, page 69-1; table 69-I, page 69-2 | by voltage ac (rms) or dc: up to 150, 150 to 300, 300 to 600, 600 to 1000 V |
| Condition | 4.2a to c, page 69-1 | A: a short circuit stays in the unit, at most 50 W; B: fused, at most 2000 W; C: fused, over 2000 W |
| Enclosure | 4.2d and e, page 69-1 | I: drip-proof from 0 to 15 degrees off the vertical; II: anything that protects less |
| Condition A, enclosure I | table 69-I, page 69-2 | clearance 1.5, 1.5, 1.5, 3 mm; leakage 1.5, 1.5, 3, 9.5 mm |

The handbook is for guidance (its cover page), and guideline 69 speaks of bare conductors such as
terminal strips and standoffs; the pack applies it to a board's copper. It states no least width for a
slot and no pollution degree or material: a slot that alone makes a pair pass is `not judged`.

### ti-slup419-creepage

TI SLUP419, "Demystifying Clearance and Creepage Distance for High-Voltage End Equipment", March 2024,
https://www.ti.com/lit/ml/slup419/slup419.pdf. Read 2026-11-17, with no second reader yet. A maker's
note, and a secondary source: its table 3 (page 7) reprints part of IEC 60664-1 table F.4, and its
reference 2 is IEC 60664-1 of May 26, 2020. IEC 60664-1 is paid; the pack holds only what the note
prints. A free primary document with these rows is still to be found.

| What | Where | Numbers |
|---|---|---|
| Creepage, basic isolation | table 3, page 7 | at 63, 400, 800, 1000 V rms; pollution degree 1 (all groups) 0.2, 1.0, 2.4, 3.2 mm; degree 2 group III 1.25, 4.0, 8.0, 10.0 mm |
| Material group | table 1, page 3 | I: CTI 600 and over; II: 400 to 600; IIIa: 175 to 400; IIIb: 100 to 175; most FR4 is IIIa |
| Least slot width | table 7, page 11 | 0.25, 1.0, 1.5 mm at pollution degree 1, 2, 3 |
| Working voltage | table 2 note (1), page 6 | the highest rms value of the ac or dc voltage across the insulation |

Not judged, and named in the pack: clearance (the note takes it from an impulse voltage, tables 4 and 5,
page 8), reinforced isolation (twice the distance, page 7), pollution degree 3 (table 3 has no column).

## ecss-q-st-70-12c-rev1

ECSS-Q-ST-70-12C Rev.1, "Space product assurance - Design rules for printed circuit boards", 30 April
2025, from https://ecss.nl/. Read 2026-11-17, with no second reader yet.

| What | Where | Numbers |
|---|---|---|
| Gap on an outer layer, without conformal coating | table 13-7 (2 of 4), page 130 | 250 um to 10 V, 350 um to 30 V on Th <= 70 um; 350 and 450 um over 70 um |
| Gap on an inner layer | table 13-7 (3 of 4), page 131 | 130 to 300 um by copper, then 1 um/V plus 30 to 70 um from 100 to 500 V |
| The voltage | 13.8.2b page 117; 13.8.2l page 119 | the peak; over 500 V not judged |
| Temperature rise of a track | 13.6.2a, page 112 | 10 C |
| Where the model holds | 13.6.3c and d, page 113 | thicker than 1.5 mm, more than 75 x 75 mm |
| Outer layer | 13.6.4.2a, page 114 | 0.9 of the model |
| Board of 1.5 to 1.8 mm | 13.6.4.2b, page 115 | 1.2 times the rise |
| The model | annex D: D.1.2b page 183, D.2c and D.2d page 184 | k0 0.0756, k1 0.4375, m0 0.5, m1 0.0301, c1 1550; to 30 A |
| Copper as manufactured | 7.1.2j, table 7-1, page 38 | 9, 12, 17, 35, 70 um give 6, 9, 11, 25, 56 um |
| Width tolerance | 7.4.2a and b, table 7-3, page 45 | 20 %, at most 30, 50, 50, 70 um by copper |
| Plating of an outer layer | 7.4.2c NOTE 2, page 44; table 7-3, page 45; table 7-4, page 46 | 25 um, added to the foil |

The annex's own example (D.1.3, page 184): 925 um by 25 um as manufactured carries 1.0002 A at 5 C;
`tests/test_boardrules.py` holds it, and 975 um as designed for 1 A.

What this pack does not judge, and says so:

- **Vias.** 13.6.3f rates a via as a track of its wall's section. The document gives the copper of a
  plated hole's wall for HDI boards alone (table 11-2, page 100). Each net with a current and a via is
  `not judged`, so such a board never passes `--strict` with this pack. A pack of the project's own,
  a copy of this one, may add `"via_wall": {"um": ..., "where": ...}` to `current` from its fab's own
  figure.
- **Over 30 V on an outer layer.** Table 13-7 does not permit it without coating, except on a
  connector's pads (13.8.4d). The check does not tell a connector's pad.
- **Copper of a thickness table 7-1 does not name**, such as KiCad's 15.2 um inner layers.
- **A board the model does not hold for**: 1.5 mm or thinner, or 75 x 75 mm or less.
- Fine pitch, HDI and conformal coating, whose columns the pack does not take.
- The gap in Z, to a hole's wall, to the edge and between holes; the current through a pad or a pour.

Choices this pack makes, each on the stricter side: copper as manufactured is the column for
non-plated inner layers on every layer; an outer layer is plated even on a board with no plated hole;
a board with no stackup has KiCad's own 35 um on each layer, and the DRC notes say so; the current on
a net is the sum of the currents `ratings.json` states on its pins.

A pack of the project's own is read as strictly as this one: every key the check uses must be there,
a number in its range, or the run is refused with the file and the place.
