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
