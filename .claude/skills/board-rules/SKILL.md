---
name: Board Rules
description: Holds a routed board to a rule pack from a free standard (ECSS-Q-ST-70-12C Rev.1) - each gap to the voltage between its nets, each track's width to the current it carries, and each net's vias when the pack gives a via's wall - with every failure naming its clause, table and page; and to a fab's published limits (JLCPCB, PCBWay, OSH Park, Sierra Circuits). The shipped ECSS pack gives no wall, so a board with a via on a net that carries current needs a pack of the project's own with its fab's via plating.
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
| `board-rules.json`, beside the board | `{"pack": "ecss-q-st-70-12c-rev1"}`: the pack the board is held to | You |
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
   The shipped pack prints no such line: it gives no via's wall, so it
   prints `not judged vias of <net>` instead (step 7).
7. For each line `- not judged ...` (`- warning: not judged ...` without
   `--strict`): do what the reason asks.
   - `ratings.json states no voltage for it` or `no current on it`: add
     the net or the pin to `ratings.json` with its source.
   - `the board is ... thick` or `the board's outline holds ... mm2`: the
     standard's current model does not hold for this board (13.6.3c). Show
     the width another way, and write in the version's README how.
   - `the pack gives no copper thickness of a via's wall`: copy the pack
     into the project, name the copy in `board-rules.json` by its path,
     and add to its `current` a `via_wall` from the fab's own page, with
     the page in `where`. OSH Park's two-layer page, for one, states "Via
     Plating Thickness 1mil (0.0254mm)":
     `"via_wall": {"um": 25.4, "where": "docs.oshpark.com/services/two-layer, Via Plating Thickness, page 1"}`.
     Without it, no board with such a via passes `--strict`.
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
    `"ground": ["GND"]`; `"power": ["VBUS", "GND"]`, every power and
    ground net. `"pack"` may stay or go: a board can name layout packs
    alone.
12. Run `workcenter drc <project> --strict`. Act on each line:
    - `fail esd J1.2 <net>: no protector on the net`: put a TVS from that
      net to ground, at the connector.
    - `fail esd J1.2 <net>: R1.1 stands 1.41 mm from D2.1, and D2.1 stands 4.35 mm from J1.2`:
      move the TVS nearer the connector, or the part further from the TVS.
    - `fail esd J1.1 <net>: joined to D1.1 through a via`: route the
      connector's pin to the TVS on 1 layer.
    - `fail length to width <net> on <layer> ...: 3.69 mm by 1.2 mm, 3.07 to 1, limit 3 to 1`:
      widen the trace, shorten it, or make the net a pour.
    - `not judged esd J2: board-rules.json does not say whether it leaves the device`:
      add J2 to `connectors` or to `inside`.
    - `not judged esd ...: no copper joins it to D1.1`: route the net.
13. A run that names `ti-szza009-emi` on a board of 4 layers prints the
    note `the rule is for a board of 2 copper layers`: the rule is not
    for this board, and nothing is judged.

## Done when

`workcenter gates <project> --strict` prints GREEN, and its DRC line names
the pack with `0 fail, 0 not judged`. With `ecss-q-st-70-12c-rev1` as
shipped, a board reaches this only if no net with a current has a via;
otherwise it needs the project's own pack with `via_wall` (step 7).
