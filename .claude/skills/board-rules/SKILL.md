---
name: Board Rules
description: Holds a routed board to a rule pack from a free standard (ECSS-Q-ST-70-12C Rev.1) - each gap to the voltage between its nets, each track's width to the current it carries (worked out per track from the net's copper, and 2 parallel tracks under 25 mm apart as 1), and each net's via count to its current on the wall of a board the project states is HDI or the wall the fab states - with every failure naming its clause, table and page; and to a fab's published limits (JLCPCB, PCBWay, OSH Park, Sierra Circuits).
---

# Board Rules

KiCad's DRC holds a board to the gaps and widths its net classes name. It
does not know that 12 V needs a wider gap than 3.3 V, or that a 0.25 mm
track carries less than 1 A. A board rule pack holds those limits from a
standard. `workcenter drc` and `workcenter gates` judge them after KiCad's
own rules, and each failure names the clause it breaks.

## When

- A board is routed, and a net carries more than a few volts or a current
  of 100 mA or more.
- A requirement or a customer names ECSS-Q-ST-70-12C.
- A fab is chosen: hold the board to its limits before ordering.

## Inputs

| File | Holds | Who writes it |
|---|---|---|
| `board-rules.json`, beside the board | `{"pack": "ecss-q-st-70-12c-rev1"}`: the pack the board is held to; and `via_wall`, the least copper of a via's wall your fab promises, with its source (step 7) | You |
| `ratings.json`, beside the board | `nets`: each net's span of volts. `parts`: the amps on a pin (`J1.1`) or through a part of 2 pins (`R5`). The same file `workcenter ratings` reads: never state a number 2 times | You, each entry with its source |
| `rules/board/<pack>.json`, in the workcenter | The standard's numbers, each with its clause, table and page | The workcenter. Never edit one to pass |
| `rules/<fab>.kicad_dru`, in the workcenter | A fab's published limits | The workcenter |

The worked example is `tests/boards/pass-board-ecss`, and
`tests/boards/fail-board-ecss` with 1 gap and 1 track too small.

## Steps

1. Write `board-rules.json` beside the board, with the Write tool:
   `{"pack": "ecss-q-st-70-12c-rev1"}`. `rules/board/README.md` names the
   packs and what each judges.
2. Open `ratings.json`. If there is none, run
   `workcenter ratings <project> --init`, and fill it as the ratings skill
   says. Give every net on the board a span of volts in `nets`, and every
   pin that brings a current in or out an entry in `parts` with `amps`.
   Each entry gets a `source`: the requirement or the part that sets it.
   To have each track held to its own current, state every pad of the
   net, 0 A included; otherwise each track of the net is held to the sum
   of the currents stated on it, which counts a source and its loads 2
   times.
3. Run `workcenter drc <project> --strict`. Read the line `PASS drc` or
   `FAIL drc`. It ends `board rules <pack>: N fail, M not judged`.
4. For each line `- fail clearance <net> to <net> on <layer> at (x, y): <gap> mm, limit <mm> mm at <V> V [...]`:
   move the copper of 1 of the 2 nets apart at (x, y) until the gap is the
   limit or more. Change `design.py` and regenerate; never edit a
   `.kicad_pcb` by hand.
5. For each line `- fail track width <net> on <layer> from (x, y) to (x, y): <w> mm, limit <mm> mm for <A> A [...]`:
   draw that track at the limit or wider (`d.track(..., width=)` or the
   net class's width). If no room is left, move it to a layer with thicker
   copper or split the current.
6. For each line `- fail vias <net> between <layer> and <layer> at (x, y): <n>, limit <m> for <A> A`:
   put `m - n` more vias beside the first, each touching the same tracks.
   For each line `- fail parallel tracks <net> and <net> on <layer> from (x, y) and (x, y), <g> mm apart: <s> mm2 as manufactured, limit <l> mm2 for <A> A`:
   widen the 2 tracks until their sections add up to the limit, or move
   them 25 mm or more apart (13.6.3g).
7. For each line `- not judged ...` (`- warning: not judged ...` without
   `--strict`): do what the reason asks.
   - `ratings.json states no voltage for it` or `no current on it`: add
     the net or the pin to `ratings.json` with its source.
   - `the board is ... thick` or `the board's outline holds ... mm2`: the
     standard's current model does not hold for this board (13.6.3c). Show
     the width another way, and write in the version's README how.
   - `the pack states no copper of a via's wall for this board`: the
     standard states a wall for HDI boards alone. Find the least wall your
     fab promises on its own page, and add it to `board-rules.json` with
     the Write tool. OSH Park's two-layer page states "Via Plating
     Thickness 1mil (0.0254mm)":
     `{"pack": "ecss-q-st-70-12c-rev1", "via_wall": {"um": 25.4, "source": "OSH Park, docs.oshpark.com/services/two-layer, Via Plating Thickness 1mil (0.0254mm), read <date>"}}`.
     An average is not a least: JLCPCB's page gives "Average Hole Plating
     Thickness 18μm"; ask the fab for its least, or write in the
     version's README why the average stands. The wall must be under half
     the least drill of a via with a current, or the run is refused. If
     the fab builds the board as HDI under ECSS-Q-ST-70-12C Rev.1 11.6,
     add `"hdi": {"source": "<the fab's order or document>"}` instead,
     and the pack's 25 um holds. A via flagged `micro` in KiCad does not
     make a board HDI.
   - `parallel tracks ... at <d> degrees, <g1> to <g2> mm apart`: the 2
     tracks fail as 1 conductor and are not quite parallel. Draw them
     parallel and widen them as in step 6, widen them until they hold as
     1 conductor, or move them 25 mm or more apart.
   - `... um of wall fills the hole of the via at ...`: the pack's wall is
     half the drill or more. Use a larger drill.
   - `microvias of <net>`: a blind via under 250 um (3.2.40), filled, is
     not rated by the pack.
     Show its current another way, and write in the version's README how.
   - `its name holds ...` or `takes it for ...`: rename the net in the
     schematic so a KiCad rule can quote it.
   - `over 30 V`, `over 500 V`, `copper ... is none of ...`: the pack
     cannot judge this. Ask the owner, and write the answer in the
     version's README.
8. If the run prints `kicad-cli did not read the pack's rules`, KiCad
   could not read the rule file in `build/board-rules/`. Do not pass the
   board; report the file and the KiCad version to the workcenter's owner.
9. Run step 3 again until it prints `PASS drc` with `0 fail, 0 not judged`.
10. For a fab, run `workcenter drc <project> --fab <name>` with a name from
   `rules/README.md` (`jlcpcb-2layer`, `pcbway-standard`, `oshpark-2layer`,
   `sierra-circuits-web`). Each `- error: ...` line names the fab's rule.
   To keep the fab for good, set `fab = "<name>"` in the design file.

## Layout packs: ESD at each connector, and power traces for emissions

A layout pack holds rules a maker's note states (`rules/board/README.md`,
"Layout packs"). The worked examples are `tests/boards/pass-layout`, and
`fail-layout-esd` and `fail-layout-emi` that break each rule once.

11. Add to `board-rules.json` the packs and what they ask you to state:
    `"layout": ["ti-slva680a-esd", "ti-szza009-emi"]`;
    `"connectors": {"J1": "<why it leaves the device>"}` for each connector
    a cable or a user reaches; `"inside": ["J2"]` for each that stays
    inside; `"protectors": {"D1": "<the TVS part and its datasheet>"}`;
    `"ground": ["GND"]`, every ground net; `"power": ["VBUS"]`, every
    power net. The 3:1 rule judges the nets of both. `"pack"` may stay or
    go: a board can name layout packs alone.
12. Run `workcenter drc <project> --strict`. Act on each line:
    - `fail esd J1.2 <net>: no protector on the net`: put a TVS from that
      net to ground, at the connector.
    - `fail esd J1.2 <net>: D2 stands on the net and has no pad on ground (GND)`:
      connect the TVS's other pin to ground, or add its ground net to `ground`.
    - `fail esd J1.2 <net>: R1.1 stands 1.41 mm from D2.1, and D2.1 stands 4.35 mm from J1.2`:
      move the TVS nearer the connector, or the part further from the TVS.
    - `fail esd J1.1 <net>: the copper from J1.1 reaches R1.1 before D1.1`:
      route the line from the connector to the TVS first, then on.
    - `fail esd J1.1 <net>: C1.1 lies 2.89 mm of copper from D1.1, and D1.1 lies 4.67 mm of copper from J1.1`:
      shorten the copper from the connector to the TVS, or lengthen it to the part.
    - `fail esd J1.1 <net>: joined to D1.1 through a via`: route the
      connector's pin to the TVS on 1 layer.
    - `fail length to width <net> on <layer> ...: 3.69 mm by 1.2 mm, 3.07 to 1, limit 3 to 1`:
      widen the trace, shorten it, or make the net a pour.
    - `not judged esd J2: board-rules.json does not say whether it leaves the device`:
      add J2 to `connectors` or to `inside`. A connector is found by its
      reference (J, P) or its footprint's library (`Connector_...`); name
      any other connector in `connectors` yourself.
    - `not judged esd: board-rules.json names no part under connectors`:
      name each connector a cable or a user reaches.
    - `not judged esd ...: no copper joins it to D1.1`: route the net.
13. A run that names `ti-szza009-emi` on a board of 4 layers prints the
    note `the rule is for a board of 2 copper layers`: the rule is not
    for this board, and nothing is judged.

## Done when

`workcenter gates <project> --strict` prints GREEN, and its DRC line names
the pack with `0 fail, 0 not judged`. A board with a via on a net with a
current reaches this only with `via_wall` or `hdi` in `board-rules.json`
(step 7).
