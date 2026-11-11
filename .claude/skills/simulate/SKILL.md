---
name: Simulate
description: Runs ngspice on the project's sim decks and holds every measured value to its bound, as written and at each corner of temperature and part tolerance; checks switching frequencies against measured resonances; writes decks that run on any machine.
---

# Simulate

The SIM gate runs every `sim/*.cir` deck in the project with ngspice in
batch mode and compares printed values against `sim/<deck>.expect.json`.
It runs each deck as written, then at every corner `sim/corners.json`
names. A circuit meets its spec when every bound holds at every corner.

## When

- A circuit has a measurable spec: a voltage, a gain, a cutoff, a
  settling time.
- Before layout, so the values on the schematic are right before they
  become copper.
- A part switches: a regulator, a PWM output, a charge pump, a clock.

## Inputs

1. `sim/<deck>.cir`: an ngspice batch deck. It ends with a `.control`
   block that prints the values under test, then `.endc` and `.end`.
2. `sim/<deck>.expect.json`: `{ "<name>": { "min": <n>, "max": <n> } }`.
   A name is a variable the `.control` block prints as `name = value`,
   in lower case. A bound has `min`, `max` or both, and may carry
   `source`, `warn`, `req` and `"at": "nominal"`. The gate refuses any
   other key, so a misspelt one never passes as a bound.
3. `sim/corners.json`: the ranges every bound must hold over ("Corners").
4. `sim/frequency-plan.json`: what switches and what resonates ("The
   frequency plan").

## Steps

1. Name each deck element after the board part it models: `R7`, `C5`.
   Give every other element a word: `RCELL`, `LSTRIP`. The corners move
   an element named like a board reference by its kind's tolerance.
   `kicad-cli sch export netlist --format spice` gives each R, C and L
   with its nets and its value; copy the values from it. It writes every
   other part as a placeholder, so those lines are written by hand.
2. Write the `.control` block so each value under test is 1 line:
   ```
   .control
   op
   let vout = v(out)
   print vout
   .endc
   .end
   ```
   `print` writes `vout = 2.500000e+00`, which the gate parses. A complex
   value prints no measure: print its magnitude, `let hm = vm(out)`.
3. Write `sim/<deck>.expect.json` with the bounds from the spec, not from
   the first result. A limit that holds "at every moment" is measured over
   the whole run, from its start: `meas tran vmin min v(rail) from=0
   to=12m`. A window that starts later leaves the start-up out; the bound's
   `source` then names the requirement that allows it.
4. Run `workcenter sim <project>`. The record has `decks.<deck>.measures`
   (every printed value), `decks.<deck>.checks` (bound by bound),
   `decks.<deck>.corners` (each value's least and greatest), and
   `failures`.
5. A failed bound means the circuit misses the spec. Change component
   values in the design, change the deck to match, re-run. Do not widen
   the bound to pass.
6. An `errors` list that is not empty means ngspice rejected the deck or
   gave up on an analysis. Read `build/sim/<deck>.log`; the line number
   in the message points at the deck. An analysis that aborts
   (`Timestep too small`) fails the deck even when a later one completes.
7. Run `workcenter next <project>` when a line of the result is not
   clear. It names the fix for the first failure or warning.

## Corners

A deck is written at 1 condition: 27 C, every part at its written value.
`sim/corners.json` names the ranges the board meets. The gate runs each
deck at every one. Copy `templates/project/corners.json` and fill it.

```json
{
  "temperature": { "values": [-20, 85], "source": "REQ-ENV-01: -20 to 85 C" },
  "tolerance": { "R": 0.01, "C": 0.2, "parts": { "R12": 0.001 }, "source": "the parts list" },
  "monte_carlo": { "runs": 100, "seed": 1 },
  "decks": { "mosfets": { "skip": "fitted models against their datasheets' 25 C rows" } }
}
```

| Key | What the gate does |
|---|---|
| `temperature.values` | 1 run for each value, with `.options temp=<value>` and the parts as written. |
| `tolerance.R`, `.C`, `.L` | A fraction: 0.01 is 1 %. Each element of that kind named like a board reference runs at its value less and plus the fraction. |
| `tolerance.parts` | The same for 1 element or `.param` by name. It wins over the kind. |
| worst case | For each bound, 1 run with every range at the end that pushed its measure furthest. No key: the gate adds it. |
| `monte_carlo` | `runs` more runs. Each part is drawn evenly inside its tolerance, the temperature inside its range. `seed` fixes the draws. |
| `decks.<deck>.skip` | The deck runs as written only. The text says why. |
| `decks.<deck>.temperature`, `.tolerance`, `.monte_carlo` | `false` with `why`, or a block that replaces the project's for that deck. |
| `source` | Where the range comes from: a requirement, a datasheet, the parts list. The gate refuses a range without one. |

1. Take the temperature range from the requirement that states it. A
   wider range is a new requirement, not a habit.
2. Take each tolerance from the part's datasheet. Name a part under
   `parts` when it differs from its kind: a 0.1 % divider, a 20 % cell
   resistance.
3. Give each part its temperature behaviour in the deck: a resistor's
   coefficient from its datasheet (`R1 a b 10k tc1=100u`), a model that
   carries temperature. The gate warns when no measure of a deck moves
   with temperature: such a deck proves nothing about heat or cold.
4. A bound holds at every corner. 2 kinds hold as written only: a bound
   with `warn` (a model against its datasheet's row, which is stated at
   the row's own conditions), and a bound that says `"at": "nominal"`,
   whose `source` says why.
5. A value the deck sets again in `.control` (`alter rcoil 0.8`) moves
   with its part: the corner scales it too.
6. A deck that sets its own temperature in `.control` fails its
   temperature corners. Remove the line, or set the deck's `temperature`
   to `false` with `why`.
7. Read a failure as `<deck>:<measure>=<value> at <corner> not in
   [min, max]`. The corner names the temperature and each part's end.
   `workcenter sim <project> --deck <deck>` prints every value with its
   least and greatest corner, and the elements no tolerance moved (`at its
   written value in every run: LCABLE`). An element with a word for a
   name moves only when `parts` names it: name each whose value has a
   spread, a cable, a cell, a contact. A corner ngspice did not finish
   names its first error and its log: `... 1 error lines: Error: measure
   f_lo when(WHEN) : out of interval (log <path>)`.
8. `--nominal` runs the decks as written only, for a quick look. The
   result names the corners as not run; such a run closes nothing.

What a corner cannot move: a tolerance inside a maker's model, and a value
written as an expression. The worst case assumes each range pushes a
measure 1 way across its span; the Monte Carlo draws cover the rest.

## The frequency plan

2 parts that switch at 1 frequency put their energy on 1 line of the
spectrum. A line that lands on a resonance is amplified by it: a 1 A
load at a third of a filter's resonance swings a 5 V rail by 6.8 V while
the rail's average stays inside its bound (`tests/boards/fail-freq-overlap`).
`sim/frequency-plan.json` names what switches and what resonates. Copy
`templates/project/frequency-plan.json` and fill it.

```json
{
  "sources": [
    { "name": "heater PWM", "hz": 1000, "tolerance": 0.01, "source": "config.h LH_PWM_HZ; HSI 1 %" },
    { "name": "I2C clock", "hz": [100000, 400000], "source": "UM10204 Table 10" }
  ],
  "resonances": [
    { "name": "cell strips with C5", "hz": "pdn.f_peak", "q": "pdn.q_peak", "source": "sim/pdn.cir" }
  ],
  "overlaps": [
    { "between": ["I2C clock", "cell strips with C5"], "evidence": "pdn_ripple.v_pp",
      "stimulus": "ICLK", "why": "the clock's edges at the peak move the rail 4 mV" }
  ]
}
```

1. List every periodic source: each PWM output, each regulator's
   switching frequency, each charge pump, each clock. Give its frequency
   with `tolerance`, or its range, and where the number comes from: the
   firmware's constant, the datasheet's row, the owner's spec in its own
   words. `tolerance` is the oscillator's. A frequency with none stated
   is taken as exact, and the band's `guard` is the margin.
2. Find each resonance with an `.ac` deck. For a supply rail, put a 1 A
   AC current source at the load: the rail's voltage is its impedance in
   ohms.
   ```
   I1 0 rail DC 0 AC 1
   .control
   ac dec 400 10 10Meg
   meas ac z_peak max vm(rail)
   meas ac f_peak max_at vm(rail)
   meas ac z_floor find vm(rail) at=10
   let half = z_floor + (z_peak - z_floor) / sqrt(2)
   meas ac f_lo when vm(rail)=$&half rise=1
   meas ac f_hi when vm(rail)=$&half fall=1
   let q_peak = f_peak / (f_hi - f_lo)
   print z_peak f_peak q_peak
   .endc
   ```
   Name the measures under `resonances`. The gate reads them at every
   corner, so a resonance moves with its parts' tolerances. A rail's
   impedance has a floor at low frequency: the resistance of the cable and
   the inductor. The half height is taken above that floor. Taken from
   zero it can lie under the floor: the crossing then does not exist at
   some corner, the `meas` fails there, and the corner fails.
3. Run `workcenter sim <project>`. The gate finds each overlap: a
   source's harmonic (1 to `harmonics`, 10 unless the plan says) inside a
   resonance's band, or 2 sources that can run at 1 frequency. A band
   reaches `guard` (0.1 unless the plan says) or 1/(2 Q), whichever is
   wider, past each end of the resonance.
4. Remove an overlap first: move the frequency, move the resonance, or
   damp it. A changed value is another part: take its series resistance
   and its tolerance from that part's datasheet, not from the part it
   replaces.
5. Answer an overlap that stays. Write a deck that runs the source at the
   resonance and bounds what it does to the rail. Name it under
   `overlaps`: `evidence` is the bounded measure, `stimulus` the deck's
   element that runs each source. The gate checks that the element runs
   at the source's frequency with a harmonic in the band, or that 2
   elements run at 1 frequency.
6. A PULSE with a period, or a SIN, in any deck is a source the plan
   names. Write a stimulus that is 1 event without a period.

The plan holds each harmonic against each resonance. It does not see an
edge that rings a resonance once: a transient deck with the real edge
shows that.

## A deck on another machine

A deck that includes a maker's model runs right only as the gate runs it.
Bare, the same deck stops with an error or prints another number with
exit code 0 (M105). `workcenter sim <project> --bundle <dir>` writes each
deck as a folder that plain ngspice runs anywhere:

| File | What |
|---|---|
| `run.sp` | The file to run: `ngspice -b run.sp`. It sets the mode the models need, then reads the deck. |
| `<deck>.cir` | The deck. Its includes point into `models/`. |
| `models/` | Every file the deck includes, translated where its library row says. |
| `expect.json`, `measures.json` | The bounds, and the values the gate measured. |
| `README.md` | How to run it, the ngspice version, each model's part and revision. |

1. Send the folder, not the deck, to a person who runs it elsewhere.
2. The command runs each folder from a copy in another place and fails
   when a measure differs from the gate's.
3. A translated model is a changed copy of its maker's file. Read the
   maker's notice before the folder goes to a third party.

## A deck by hand

Run one deck only through `workcenter sim <project> --deck <deck>`, never
with a bare `ngspice -b`. The command runs the deck the gate's way and
prints every value the deck printed, each beside its bound. A bare run in
`sim/` reads a vendor's model untranslated and in ngspice's own mode: a
PSpice current monitor read 3.0 V there where the gate reads 0.505 V
(M94).

1. `workcenter sim <project> --deck <deck> --keep --out <scratch>` leaves
   the run folder, `<scratch>/sim/run/<deck>/`: the deck with its includes
   made absolute, the translated models, the `.spiceinit` with the mode.
   It prints the command that reruns it: `env -C <run folder> ngspice -b
   <deck>.cir`.
2. Edit the copy in the run folder to probe a node or step a value, and
   rerun with that command. The project's deck stays as it is.
3. A number a writeup or a calculation quotes comes from `workcenter sim`
   or `workcenter verify` on the project's own deck, never from a probe
   run.

## A vendor's model

A part with a published model is simulated with that model, kept in the
project's `library/` and listed in `library/sources.csv` (`PROCESSES.md`
P27; `workcenter sources` checks the rows). Fetch a model the part has no
row for yet with `workcenter fetch <url> --to library/<maker>/<file> --mpn
<MPN> --row` (`--member` for a file inside a zip), then fill the row's
`Revision`, `Dated` and `Ngspice` from the file.

A number the deck needs from a datasheet's curve (a fuse's melting time at
a current, a MOSFET's safe operating area) is read from the PDF's vectors
with `workcenter curve <pdf> --page N`: the listing first, for the frame and
the curve's path, then `--frame`, `--x`, `--y` and `--at`. Cite the page and
the figure with the number.

1. Include it by its library path from the deck, as the vendor ships it:
   `.include "../../library/ti/TLV75533P_TRANS.lib"`. The gate runs the deck
   from `build/sim/run/<deck>/` with the model translated where its row's
   `Ngspice` column says (`ps`, `res-model`, `tolerance`); never edit the
   vendor's file.
2. Check the model before trusting it: drive it at its datasheet's own
   test conditions and print each electrical-table value, and bound each
   in the expect file with the table's min and max and a `"warn"` naming
   the row: `{"min": 0.975, "max": 1.025, "warn": "the model against its
   datasheet: IOUT at VSENSE 100 mV"}`. A warn bound outside is reported,
   and fails only `--strict`; a bound without `warn` is the design's.
3. Then drive it as the board does (the board's parts, its load, its
   supply's range) with bounds from the design: a firmware constant, the
   next part's operating range.
4. Where a model is off its datasheet, the datasheet governs: say so in
   the version's README with both values, and keep the warn bound so the
   next model revision shows whether it was fixed.

## A part with no model

A part whose maker publishes no model (a MOSFET, say) is fitted to its
datasheet's table in `sim/models/`, the project's own file, which needs no
library row; the `verification` skill gives the method. Check the fit as a
vendor's model is checked: every table row a `warn` bound, the rows the
fit did not use included.

## A bound that serves a requirement

In a project with a verification package (P28), a bound names its
requirement: `{"req": "REQ-USB-05", "max": 30.0, "source": "..."}`.
`workcenter verify` checks the name exists. A requirement the design fails
gets no bound: the package's traceability table says FAIL.

## Checks

- Every bound in an expect file traces to a line in the spec or the
  schematic notes.
- A deck with no expect file still has to run clean; it proves nothing
  about the spec, and the gate names it as a warning.
- Every range in `sim/corners.json` and every frequency in
  `sim/frequency-plan.json` has its `source`.
- `workcenter sim <project> --strict` passes before a board is called
  done: no deck without corners, no source without a plan.
- `build/sim/` is not committed.
