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
- **The current on a track.** Where every pad of a net has a current in `ratings.json` (a pin, `J1.1`,
  or a part, `R5`, which counts on each of its nets) and the net's copper is 1 piece, the currents in
  balance the currents out. Taking a track away splits the net's pads into sides; the track carries at
  most the lesser of the currents stated on the 2 sides. A track in a loop carries at most half the
  pins' sum; a stub to no pad carries nothing. The net's vias are held to half the sum. On any other
  net, every track and via is held to the sum of the currents stated on its pins, which counts a source
  and its loads 2 times: state every pad's current, 0 included, to be held to less.
- **Parallel tracks (13.6.3g).** 2 straight tracks of 2 nets with a current, parallel and side by side on 1 layer,
  less than 25 mm apart edge to edge, are held as 1 conductor: the sum of their currents on the sum of
  their sections as manufactured (table 7-3's tolerance off the width, table 7-1's copper). The
  clause's NOTE names an equivalent section and an equivalent current; the pack takes the sums. 2
  tracks are parallel when their gap changes over their overlap by no more than the file's rounding
  can make: a .kicad_pcb holds a coordinate to 6 decimals of a mm, so 4 ends each off by half of 1 nm
  in x and y, 2.83 nm in all. 2 tracks at a greater angle that fail as 1 conductor are `not judged`,
  each pair by name with its angle and its least and greatest gap: the clause names no angle. 2 that
  hold as 1 conductor hold either way.
- **The board's area** is the area inside its outline on Edge.Cuts: lines, arcs and curves joined end
  to end, rectangles, polygons and circles, the board's own and those drawn inside a footprint, placed
  by the footprint's place and turn. The greatest outline is the board; the others are its holes. An
  outline that does not close has no area, and no width is judged.
- **Via count.** The vias of a net that join the same pieces of copper share the current. A via is a
  track of its wall's section (13.6.3f). A group holds at least the net's current divided by 1 via's.
  The wall is the pack's where it holds for the board, or the one `board-rules.json` states, and the
  lesser where both do:

      {"pack": "ecss-q-st-70-12c-rev1",
       "via_wall": {"um": 25.4, "source": "OSH Park, 2 Layer Prototype Service, docs.oshpark.com/services/two-layer, Via Plating Thickness 1mil (0.0254mm), read 2026-11-17"}}

  State the least wall the fab promises. An average, such as JLCPCB's "Average Hole Plating Thickness
  18μm", is not a least. A wall of half a judged via's drill or more fills the hole and is refused.
  The pack's 25 um wall holds for an HDI board alone, and HDI is how a board is built (3.2.31, page
  20; clause 11), so `board-rules.json` states it with the fab's order or document:
  `"hdi": {"source": "..."}`. A via does not make a board HDI.
- **Microvias.** A microvia is a blind via, exposed on 1 side of the board (3.2.13, page 18), under
  250 um across (3.2.40, page 22), read from the via's layers and drill; KiCad's `micro` or `blind`
  word does not count. It is copper filled (table 11-1, page 99) and is not judged.

## Layout packs

A layout pack (`"kind": "layout"`) holds rules a maker's note states about where parts and copper go.
A project names them in `board-rules.json` under `layout`, with or without `pack`, and states what the
board file cannot say:

    {"layout": ["ti-slva680a-esd", "ti-szza009-emi"],
     "connectors": {"J1": "the USB cable"}, "inside": ["J2"],
     "protectors": {"D1": "TPD2E2U06"}, "ground": ["GND"], "power": ["VBUS", "GND"]}

A connector is a part whose reference is J or P (IEEE 315's letters) or X and digits, or whose footprint is
in a KiCad library whose name starts with `Connector` or `TerminalBlock` (`Connector_USB`,
`TerminalBlock_Phoenix`, ...), or is `Battery`. One not named in `connectors` or `inside` is `not judged`;
a crystal named X1 goes under `inside`. A `connectors` with no part is `not judged` too: the pack then
judges no line. A connector with another reference and a footprint of a project's own library (`USB1` on
`MyProject:USB_C`) is found by neither, and the DRC line does not say so: name it in `connectors`. The
DRC line names every pack:
`board rules ti-slva680a-esd + ti-szza009-emi: 0 fail, 0 not judged`.

Both packs read the copper of a net as a graph. Its points lie on the centre lines of the tracks: each
track's ends, where another track's end lands inside its copper, where 2 tracks cross, and where a via,
a pad or a pour touches it. A via joins its layers and ends nothing; a via or a pad whose centre lies in
a pour of its net, on any of its layers, joins that pour. A pad or a pour is an end, and a pour is named
by the place the trace meets it. Lengths are along the centre lines, from pad centre to pad centre; an
arc is measured along the arc (its radius times its angle), not as the 2 chords it is drawn with.

### ti-slva680a-esd

TI SLVA680A, "ESD Protection Layout Guide", Rev. A, April 2022, https://www.ti.com/lit/an/slva680/slva680.pdf.
Read 2026-11-17, with no second reader yet. For each pin of a connector in `connectors` whose net is not
ground:

| Rule | Where | Judged |
|---|---|---|
| `protector` | section 1 and figure 1-2, page 2 | a part in `protectors` stands on the net, and has a pad on a net in `ground` |
| `nearest` | section 2.1, Summary, page 4; section 2.3, Case 2, page 6 | the shortest copper from the connector's pad to the protector's meets no other part's pad; every other part's pad on the net stands further from the protector's pad than the protector's pad from the connector's, centre to centre, and lies further along the copper too; and every other part's pad stands further from the connector's pad than the protector's pad, centre to centre and along the copper (no branch to the protected part before the TVS) |
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
| Parallel tracks | 13.6.3g, page 114 | under 25 mm apart: 1 conductor |
| A via's wall on an HDI board | table 11-1 (2 of 2), page 100; table 11-2, page 100; 11.6a and c, page 96 (shall: table 11-1); 11.6b, page 96, and 11.6d, page 97 (should: table 11-2) | core via 30 um (polyimide HDI) and 25 um (high speed HDI); plated through hole 25 um: the lesser, 25 um |
| HDI | 3.2.31, page 20; clause 11 | how a board is built: `board-rules.json` states it (`hdi`) |
| Microvia | 3.2.40, page 22; 3.2.13, page 18 | a blind via (exposed on 1 side) under 250 um |

The annex's own example (D.1.3, page 184): 925 um by 25 um as manufactured carries 1.0002 A at 5 C;
`tests/test_boardrules.py` holds it, and 975 um as designed for 1 A.

What this pack does not judge, and says so:

- **Vias of a board not stated HDI, without a stated wall.** 13.6.3f rates a via as a track of its
  wall's section, and the document states no wall for such a board. Read for it, and none found: 13.6.3f
  (page 114); 13.6.4.2c (page 115, a via to a plane, a may); 7.4.2c NOTE 2 (page 44) and table 7-1
  (page 38), the plating of an outer layer and not of a hole's wall; 7.5.3i (pages 52 and 53), the drill
  grown for the wall's plating with no thickness; tables 11-1 and 11-2 (page 100), for HDI boards by
  11.6 (pages 96 and 97). Each net with a current and a via is `not judged` until `board-rules.json`
  states the fab's wall (`via_wall`) or that the board is built as HDI (`hdi`, above).
- **Microvias**, copper filled (table 11-1, page 99): not judged.
- **13.6.3g beyond 2 straight tracks of 2 nets**: 2 tracks of 1 net, arcs, tracks stacked on 2 layers, and 3 or more tracks side by side are each held alone or in pairs.
  The DRC notes name them as not checked.
- **13.6.4.2c, d and e**, which let a via to a plane, a short track to a plane, and a track into a
  connector's footprint carry more: each is a "may", and the pack takes none of them.
- **Over 30 V on an outer layer.** Table 13-7 does not permit it without coating, except on a
  connector's pads (13.8.4d). The check does not tell a connector's pad.
- **Copper of a thickness table 7-1 does not name**, such as KiCad's 15.2 um inner layers.
- **A board the model does not hold for**: 1.5 mm or thinner, or 75 x 75 mm or less.
- Fine pitch, HDI and conformal coating, whose columns the pack does not take.
- The gap in Z, to a hole's wall, to the edge and between holes; the current through a pad or a pour.

Choices this pack makes, each on the stricter side: copper as manufactured is the column for
non-plated inner layers on every layer; an outer layer is plated even on a board with no plated hole;
a board with no stackup has KiCad's own 35 um on each layer, and the DRC notes say so; where not every
pad's current is stated, the current on a net is the sum of the currents `ratings.json` states on its
pins; on a board stated HDI with a stated wall, the lesser of the 2 walls; the pack takes table 11-2's
"should" (11.6b and d) as a least for a board its project states is HDI.

A pack of the project's own is read as strictly as this one: every key the check uses must be there,
a number in its range, or the run is refused with the file and the place.
