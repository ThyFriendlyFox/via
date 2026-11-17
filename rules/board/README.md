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
- **Track width.** For each track of a net with a current, the least width as designed: the model of
  annex D at the rise the pack allows, on the copper as manufactured (table 7-1), widened for the
  manufacturing tolerance (table 7-3). An outer layer carries 0.9 of the model (13.6.4.2a). A board of
  1.5 to 1.8 mm rises 1.2 times as much (13.6.4.2b).
- **Via count.** The vias of a net that join the same pieces of copper share the current. A via is a
  track of its wall's section (13.6.3f). A group holds at least the net's current divided by 1 via's.

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

The annex's own example (D.1.3, page 184): 925 um by 25 um as manufactured carries 1.0002 A at 5 C;
`tests/test_boardrules.py` holds it, and 975 um as designed for 1 A.

What this pack does not judge, and says so:

- **Vias.** 13.6.3f rates a via as a track of its wall's section. The document gives the copper of a
  plated hole's wall for HDI boards alone (table 11-2, page 100). Each net with a current and a via is
  `not judged`. A pack of the project's own may add `"via_wall": {"um": ..., "where": ...}` from its
  fab's own figure.
- **Over 30 V on an outer layer.** Table 13-7 does not permit it without coating, except on a
  connector's pads (13.8.4d). The check does not tell a connector's pad.
- **Copper of a thickness table 7-1 does not name**, such as KiCad's 15.2 um inner layers.
- **A board the model does not hold for**: 1.5 mm or thinner, or 75 x 75 mm or less.
- Fine pitch, HDI and conformal coating, whose columns the pack does not take.
- The gap in Z, to a hole's wall, to the edge and between holes; the current through a pad or a pour.

Choices this pack makes, each on the stricter side: copper as manufactured is the column for
non-plated inner layers on every layer; a board with no stackup has KiCad's own 35 um on each layer, and
the DRC notes say so; the current on a net is the greatest one `ratings.json` states for a pin on it.
