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

## Decks a board asks for

A board can pass every gate with no deck while its schematic holds a
circuit an engineer would simulate. The SIM gate reads the schematic's
netlist and asks for 2 kinds of deck:

| Kind | The schematic holds | Template |
|---|---|---|
| `i2c-rise` | A net named SDA or SCL (a word of the net's name or of a pin's name on it: `I2C1_SDA`, `PB1/SDA`, `SCL2`) with a 2-pin resistor to a rail. A resistor is a `Device:R` symbol (`R_Small`, `R_US`, ...) or a reference `R<n>`. A rail is a net with a power pin on it that is no ground pin, or a name like `+3V3`, `VCC`, `VDD_IO`, `3V3`. A net named GND, VSS, VEE, 0V or COM, or one whose power pins are all ground pins, is ground: a resistor to it pulls down. | `templates/project/sim/i2c_rise.cir` |
| `load-step` | A part of KiCad's `Regulator_Linear` or `Regulator_Switching` library, on a board whose `ratings.json` states a load: a part or pin under `parts` with `amps` above 0. | `templates/project/sim/load_step.cir` |

The gate reads the root sheet and every sheet it names, in a subfolder or
not.

Not recognized: a line with no pull-up on this board, a bus by another
name, a regulator drawn with a symbol of another library, a load stated
anywhere but `ratings.json`. SPI and UART are not asked for. A resistor
array or network (`Device:R_Pack04`, `RN1`) on an I2C line is not read:
the gate prints `not judged: the I2C line SDA meets RN1 ...`, and no deck
answers it. Draw the pull-ups as 2-pin resistors to have them judged.

A deck answers a need by a line of its own: `* deck: i2c-rise SDA SCL`
names the nets it stands for, `* deck: load-step U1` the regulator. The
gate holds the line to the schematic:

- An I2C deck runs each pull-up of the nets it names by its reference, at
  the schematic's value (`R1 vdd sda 4.7k` for R1 4.7k), or runs another
  pull-up of the same value that stands for it. Otherwise it fails:
  `i2c_rise.cir: R1 is 4.7k in the deck and 47k in the schematic, on SDA`.
  A value the gate reads no number from (`{rp}`) is not judged.
- A load-step deck runs the regulator it names: an element `XU1` for U1.

1. Run `workcenter gates <project>`. A line `not judged: the I2C lines ...
   copy templates/project/sim/i2c_rise.cir` or `not judged: U1 (...) feeds
   the loads ratings.json states ...` is a deck the board asks for. It is a
   warning, and a failure with `--strict`.
2. Run `workcenter next <project>`. Its RUN line copies the template's deck
   and its expect file into `sim/`, under a name no file there has. Run it.
3. Open the copy. Each `* fill:` line names 1 value: write the board's value
   on the line under it, then delete the `* fill:` line. The gate fails a
   deck that still holds 1: `i2c_rise.cir:9: still says fill: ...`.
   - I2C: the nets on the `* deck:` line, VDD, the pull-up by its reference
     and value, CBUS. CBUS is each device pin's capacitance (10 pF at most,
     UM10204 Rev. 7.0, Table 10, page 43), plus the traces, the connector
     and what plugs in: 400 pF at most (Table 11, page 44).
   - Load step: the regulator's maker's model (`.include`, "A vendor's
     model" below), its pins on `XU1`, the input voltage, the capacitors by
     their references, the light load and the stated load.
4. Check each bound in the copied expect file.
   - I2C: `tr` is Fast-mode's, 20 to 300 ns (UM10204 Rev. 7.0, Table 11,
     page 44). For a 100 kHz bus write Standard-mode's row: `max` 1.0e-6
     and no `min`. `isink_share` is 1 at most: the deck divides the current
     the pull-up asks for by the least a device sinks, 3 mA for VDD over
     2 V, 2 mA at 2 V or below (Table 10, page 43). For VDD at 2 V or below
     also set Ron to 0.2 x VDD / 0.002, as the deck's comment says.
   - Load step: each source says `fill:` until it names the regulator's
     datasheet: its load-transient row or figure, revision and page. The
     gate refuses a bound whose source still says `fill:`.
5. Run `workcenter gates <project> --strict`. Read each line:

   | Line | Do |
   |---|---|
   | `<deck>.cir:<n>: still says fill: ...` | Write the value line `n` names, then delete line `n`. |
   | `<deck>.expect.json: <measure>: its source still says fill: ...` | Write the datasheet's document, table or figure and page as the source. |
   | `i2c_rise:tr=4.23654e-07 not in [2e-08, 3e-07] (UM10204 ...)` | The pull-up is too weak for the bus: a smaller resistor, or less capacitance. Never widen the bound. |
   | `i2c_rise:isink_share=... not in [None, 1.0] ...` | The pull-up is too strong: a larger resistor. |
   | `<deck>.cir: R1 is ... in the deck and ... in the schematic ...` or `... has no line in the deck ...` | The deck does not run the board's pull-up. Write each pull-up as the schematic names it, with its value. |
   | `<deck>.cir: says ... load-step U1 and no line runs U1 ...` | Name the regulator's element `XU1`. |
   | `load_step:undershoot=... not in ...` | The regulator dips past its datasheet's load transient: more output capacitance, or another regulator. |
   | `not judged: the I2C lines ...` again | The `* deck:` line does not name the nets the line lists. Write them as the line spells them. |
   | `not judged: the decks the schematic asks for: ...` | kicad-cli wrote no netlist. Run `workcenter erc <project>` and fix what it says. |

`tests/boards/pass-sim-bus` holds both decks with a board's values;
`tests/boards/fail-sim-i2c-weak` is a 10k pull-up on 50 pF: 423.65 ns.

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
| `tolerance.R`, `.C`, `.L` | A fraction: 0.01 is 1 %. Each element of that kind named like a board reference moves by it. |
| `tolerance.parts` | The same for 1 name: an R, C or L element, the DC value of a V or I source, or a `.param`. It wins over the kind. |
| `monte_carlo` | `runs` more runs. Each part is drawn evenly inside its tolerance, the temperature inside its range. `seed` fixes the draws. |
| `decks.<deck>.skip` | The deck runs as written only. The text says why. |
| `decks.<deck>.temperature`, `.tolerance`, `.monte_carlo` | `false` with `why`, or a block that replaces the project's for that deck. |
| `source` | Where the range comes from: a requirement, a datasheet, the parts list. The gate refuses a range without one. |

The gate picks the tolerance runs itself. No key asks for them.

| Runs | What |
|---|---|
| Each part alone | At both ends of its tolerance and half-way to each. A measure that peaks between the ends is followed toward its peak, for 5 rounds at most. |
| Every combination of the ends | Each part low or high, at the deck's own temperature and at each named one. The gate runs them when they are 64 runs or fewer. 4 parts over 2 temperatures: 16 x 3 = 48 runs. |
| The worst case | Above 64 runs. For each bound, 1 run with every range at the end that pushed its measure furthest alone. The gate then warns: 2 parts off together can hide a miss, so name `monte_carlo`. |

1. Take the temperature range from the requirement that states it. A
   wider range is a new requirement, not a habit.
2. Take each tolerance from the part's datasheet. Name a part under
   `parts` when it differs from its kind: a 0.1 % divider, a 20 % cell
   resistance. A supply's spread is named there too, by its source:
   `"VBAT": 0.05`.
3. Give each part its temperature behaviour in the deck: a resistor's
   coefficient from its datasheet (`R1 a b 10k tc1=100u`), a model that
   carries temperature. The gate warns when no measure of a deck moves
   with temperature: such a deck proves nothing about heat or cold. A deck
   that `sim/thermal.json` names is not warned: its corners' temperature is
   the ambient its junctions are judged at.
4. A bound holds at every corner. 2 kinds hold as written only: a bound
   with `warn` (a model against its datasheet's row, which is stated at
   the row's own conditions), and a bound that says `"at": "nominal"`.
   The second needs a `source` that says why; the gate refuses it without
   one.
5. 2 parts written from 1 `.param` move apart: each is scaled where it
   stands (`{(rdiv)*1.05}`). A `.param` that `parts` names moves as one,
   and the parts written from it move with it.
6. A value the deck sets again in `.control` moves with its part. The
   corner scales `alter rcoil 0.8`, `alter rcoil = 0.8`,
   `alter @rcoil[resistance] = 0.8` and `alterparam`. Write that value
   as a number: the gate fails on `alter r2 = $&rv`, which it cannot
   scale.
7. A deck that sets its own temperature in `.control` fails its
   temperature corners. So does an element held at its own temperature
   (`temp=` on its line). Remove the setting, or set the deck's
   `temperature` to `false` with `why`.
8. Write 4.7 k as `4.7k`. ngspice reads `4k7` as 4 k and says nothing;
   the gate fails the deck and names the value.
   Likewise 1 parameter to an `altermod` line, as a corner that
   switches a part to its maximum model does: ngspice 42 applies the
   first parameter of `altermod M vto=1.0 kp=550` and drops the rest
   without a word. The gate fails the deck and names what it dropped
   (M172).
9. Print each measure once. A name printed 2 times with 2 values is
   judged on each value.
10. Write a part in the deck, not in a file the deck includes. A corner
    reads the deck's own lines; the gate warns about a part it finds in
    an included file of the project. A part inside a `.subckt` placed
    more than once moves in every copy together, and the gate says so.
11. Read a failure as `<deck>:<measure>=<value> at <corner> (and N more
    corners) not in [min, max]`. The corner names the temperature and
    each part's end.
    `workcenter sim <project> --deck <deck>` prints every value with its
    least and greatest corner and its `margin`: the least distance to a
    limit at the worst corner. It also prints the elements no tolerance
    moved (`at its written value in every run: LCABLE`). An element with
    a word for a name moves only when `parts` names it: name each whose
    value has a spread, a cable, a cell, a contact. A corner ngspice did
    not finish names its first error and its log: `... 1 error lines:
    Error: measure f_lo when(WHEN) : out of interval (log <path>)`.
12. `--nominal` runs the decks as written only, for a quick look. The
    result names the corners as not run; such a run closes nothing.
    `--jobs N` sets how many corners run at once.

What a corner cannot move: a tolerance inside a maker's model. A range
that pushes a measure 1 way across its span has its worst case at an end.
The half-way runs, the combinations and the Monte Carlo draws look for
the rest.

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
    { "name": "I2C clock", "hz": [100000, 400000], "source": "UM10204 Table 11" }
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
   corner, so a resonance moves with its parts' tolerances. Give that
   deck its corners: a resonance read from a deck that runs no corner
   fails the plan. Print each measure the plan reads at every corner: one
   that is missing at a corner fails, since its least and its greatest
   are not known. A rail's
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
   elements run at 1 frequency. A resonance meets its source between the
   ends of its parts, where no end shows it. So the gate also runs that
   deck with L stepped against C between their ends, 2 % of a value at a
   step.
6. A PULSE with a period, or a SIN, on a V, I or B source in any deck is
   a source the plan names. Write a stimulus that is 1 event without a
   period.
7. Write a stimulus's frequency as a number. The gate reads the deck's
   text. It warns about a source whose frequency is a parameter or an
   expression, a PWL that repeats, an SFFM, an AM or a B source of
   `time`: no plan can place it.

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
| `run.sp` | The file to run: `ngspice -b run.sp`. It sets the mode the models need, changes to its own folder, then reads the deck. |
| `<deck>.cir` | The deck. Its includes point into `models/`. |
| `models/` | Every file the deck includes, translated where its library row says. |
| Other files | Each other file of the deck's folder, for a deck that reads one beside it (`source print_it.sp`, a file source). |
| `expect.json`, `measures.json` | The bounds, and the values the gate measured. |
| `README.md` | How to run it, the ngspice version, each model's part and revision. |

1. Send the folder, not the deck, to a person who runs it elsewhere.
2. The command runs each folder from a copy in another place and fails
   when a measure differs from the gate's, or when a file the deck
   includes is not there.
3. An earlier bundle in `<dir>/<deck>/` is replaced. A folder of that
   name that holds no `run.sp` is refused: name another folder, or remove
   it.
4. A translated model is a changed copy of its maker's file. Read the
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

### A part's file and its row

The same steps keep a datasheet or a 3D body. Each step is 1 command.

1. `workcenter fetch <url> --to <project>/library/<maker>/<file> --mpn <MPN> --row`
   - `fetch: <url> ok, ... wrote ...`: the file is kept and its row written.
     Fill `Revision` and `Dated` from the `revision?` lines.
   - `sources: started <path>`: the project had no `library/sources.csv`;
     this one is new, with the header
     `MPN,Kind,URL,File,Member,Revision,Dated,Subckt,Ngspice,SHA256,Checked,Note`.
     Nothing to do.
   - `fetch: <url> gave an HTML page ...`, `gave an empty file (0 bytes)`,
     `gave a file that starts ..., not %PDF`, `gave N of the M bytes its
     Content-Length names` or `gave N bytes, cut short inside a chunk ...`:
     the site served something that is not the file. Nothing was written.
     Go to step 2.
   - `fetch: <url> refused (HTTP 403) ...`: the site refuses the
     workcenter's name. Never ask again under another name. Go to step 2.
   - `fetch: <url> gone (HTTP 404) ...`: find the maker's current URL and
     run step 1 again.
   - `fetch: <url> error (...)`: the site's answer could not be read.
     Go to step 2.
2. A person downloads the file in a browser, then:
   `workcenter fetch --file <downloaded file> --url <url> --to <project>/library/<maker>/<file> --mpn <MPN> --row`.
   The row records `--url` and the note "downloaded by a person from the
   URL; not fetched by the workcenter". For a zip, add `--member <name>`:
   the member is read out and kept, not the zip.
   - `fetch: <file> is an HTML page ...`, `is an empty file (0 bytes)` or
     `is a file that starts ..., not %PDF`: the browser saved something
     that is not the file. Download it again from the maker.
   - `fetch: no member '<name>' in <file>`: list the zip and give the
     member's name as the zip holds it.
   - `fetch: <file> (downloaded from <url>), ...`: done.
3. `workcenter sources <project>` judges every kept file of the board's
   parts. It needs a schematic and a parts file; until both exist it
   judges nothing, and steps 1 and 2 are the only check of the file.
   - `<project>: no KiCad project, schematic, board or sim/ directory found`
     or a `SKIP` line for `sources` that ends `no schematic in project`:
     nothing was judged. Run step 3 again once the board has a schematic.
   - A `SKIP` line for `sources` that ends `no parts file: name one with
     --parts or add <path>`: nothing was judged. Give the parts file with `--parts <file>`.
   - `<MPN> <kind>: <file> is an HTML page ...`, `is an empty file (0 bytes)`
     or `is a file that starts ..., not %PDF`: a row written before fetch
     judged bodies keeps the wrong file. It is the row's only problem; its
     SHA256 is not judged. Delete the file and its row, then run step 1
     again.

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

## A part's value from its maker's data

A 10 uF ceramic capacitor on 3.3 V can keep under half its value, and an
inductor loses inductance with its current. The gate runs each deck
capacitor at its working voltage and temperature, and each inductor at its
current, from the curves in the part's facts (`library/facts/`, the
`ratings` skill). It takes a curve only from facts that name the part's
number in `mpn` or `mpns`, never by a `match` pattern (a series datasheet
covers every value), and whose source's `sha256` is a row of
`library/sources.csv` for that part. A share is above 0 and at most 1.5.
The fixture is `tests/boards/fail-sim-bias`.

| Key | Kind | Pairs |
|---|---|---|
| `kept` | capacitor | `[volts, share of the value kept]`, from the DC bias curve |
| `kept_celsius` | capacitor | `[celsius, share against 25 C]`, from the temperature curve with no bias |
| `kept_celsius_at` | capacitor | `{"volts": V, "kept": [celsius, share against 0 V and 25 C]}`, the maker's temperature curve at 1 bias (Samsung's BiasTCC) |
| `esr` | capacitor | `{"ohms": R, "hz": f}`, the series resistance at the frequency it was read at |
| `esl` | capacitor | `{"henries": L, "hz": f}`, the series inductance, where the maker gives a figure |
| `kept` | inductor | `[amps, share of the value kept]`, from the L vs current curve |

With `kept_celsius_at`, the share at its bias is the maker's combined
figure. Its shares are against the value at 0 V and 25 C, so at 25 C it
keeps about what `kept` keeps at that bias. The gate refuses a curve whose
25 C share is nearer 1 than that, a curve that does not reach 25 C, and
one with no `kept`. Between 0 V and that bias the temperature factor goes
from the 0 V curve's to the bias curve's in a straight line in volts.
That line is the gate's, not the maker's: the run says `not judged` for
it. Past the bias the factor stays the bias curve's. `esr` and `esl` go in series with the
capacitance in the run's copy; the curve reads the voltage across the
capacitance alone. Read `esr` at the deck's switching frequency, and say
in `note` between which points of the maker's graph. Never work out an
ESL from an impedance curve: enter `esl` only from a figure the maker
gives.

1. Fetch the maker's file: `workcenter fetch <url> --to library/<maker>/<file>
   --mpn <MPN> --row`. A maker that publishes the curve as numbers (a data
   page, a CSV) is read point by point. A curve in a PDF is read with
   `workcenter curve <pdf> --page N` from its vectors (P27 step 6). Never
   read a curve by eye.
2. Enter every point the maker gives, in the part's facts, with the file's
   SHA256 in `source.sha256`. Write in `note` which graph, its conditions
   and how each share was worked out.
3. Write the part in the deck by its board reference, at its nominal value:
   `C2 out 0 10u`, `L1 sw out 2.2u`. Write it in the deck's own lines: not
   inside a `.subckt`, not in a file the deck includes, at any depth: the
   gate does not rewrite those, and the part runs ideal. An inductor that a
   K element of the deck's top level couples runs ideal too (a warning, not
   a failure); a K inside a `.subckt` couples only that block's parts. With
   `uic` (on the `.tran` line or a `+` line after it), a capacitor's `ic=`
   goes to a 1 F capacitor whose current drives the part (`bc2_ic`,
   `cc2_ic` in the run's copy); that form carries no `m=`, `tc1=` or other
   parameter of the line, so such a part runs ideal. Without `uic` ngspice
   uses no `ic=`, and the gate takes it off; `m=` and the others stay.
4. Run `workcenter sim <project>`. The record names each part it ran on its
   data under `decks.<deck>.parts`, with its facts and its row.
5. Read each line:

   | The line says | Do |
   |---|---|
   | `<deck>:<measure>=... with the makers' data of C2 and L1; with them ideal it is ...; C2 alone on its data misses it` | The part named misses the bound on its own data. Fit a larger or a higher-rated part, or another dielectric, and enter its data. Never remove the data. |
   | `... with them ideal it misses it too` | The circuit misses the bound with any part. Fix the circuit first. |
   | `<ref> runs as an ideal part while the library holds its maker's data (...): no row of library/sources.csv ...` | Add the maker's file and its row (step 1), or correct `source.sha256` to the file's. |
   | `...: its facts speak of the symbol ...` | Enter the curve under the part number, not the symbol. |
   | `...: its facts name the parts by the pattern ...` | Enter the curve under the part number (`mpn`, or `mpns` for the part numbers of 1 value). |
   | `...: the file sources.csv:N keeps, ..., is not the one its SHA256 names` | Fetch the file again, or correct `source.sha256` and the row to the file's. |
   | `...: it stands inside .subckt ...` | Move the part into the deck's top level. |
   | `...: it stands in <file>, a file the deck includes ...` | Move the part from the included file into the deck. `<file> (from <other>)` is a file that `<other>` includes. |
   | `...: its ic= sets its starting current ...` or `...: its ic=... is no number ...` | The gate moves only a capacitor's `ic=` that is a number. Write the number, or take the `ic=` off and start the deck from its operating point (no `uic`). |
   | `...: its line also holds m=2, which the form the gate writes for an ic= under uic does not carry` | Write the part's whole value (`20u` for `10u m=2`), or start the deck from its operating point (no `uic`). |
   | `...: its kept_celsius_at keeps ... at 25 C, nearer 1 than ...` | Enter the curve's shares against the value at 0 V and 25 C, as the maker's data gives them. |
   | warning `not judged: C2's share at a temperature between 0 V and 5 V: ...` | The maker gives no curve between 0 V and the bias. If the working voltage is far from both, enter the maker's curve at a bias near it, where the maker gives one. |
   | warning `not judged: <deck>: <ref> runs as an ideal part ...: it is coupled by K..., and the gate models no coupled inductor's curve` | The deck runs the part at its written value. Check by hand that the core does not saturate at the deck's current: the coupled part's facts give its saturation current. |
   | `...: its value ... is no number and no expression` | Write the part's value as a number. |
   | warning `<ref>'s curve ends at ... under its rating` | Past the last point the deck holds the last share. Enter the maker's points up to the rating if the maker gives them. |
   | warning `<ref> runs on its maker's data, and whether that is its maker's file is not judged: ... keeps no file` | Keep the maker's file in the library with its row's `File`, when its terms allow. |
   | warning `not judged: C2 and L1 hold their makers' data, and no deck element carries their reference` | Name the deck's parts by their board references (step 3). |
   | warning `not judged: C2 and L1 hold their makers' data, and no deck holds a capacitor or an inductor` | The decks run no capacitor and no inductor. If a deck models one in another way (a subcircuit, a B source), write it as the part, by its reference. |
   | warning `not judged: whether C2 and L1 run on their makers' data: ... the project has no schematic ...` | The schematic gives each part its number. Draw it, or run the decks of a project that has one. |
   | warning `not judged: whether ... : ... kicad-cli ...` | Install KiCad (`sudo ./install.sh`) and run again. |

6. A corner moves the written value by its tolerance, and the curve applies
   on top. A temperature corner moves `kept_celsius` and `kept_celsius_at`
   with it.

What it does not do: an inductor's temperature, its DC resistance and a
coupled inductor's curve; a capacitor's ESR at more than 1 frequency.

## A bound that serves a requirement

In a project with a verification package (P28), a bound names its
requirement: `{"req": "REQ-USB-05", "max": 30.0, "source": "..."}`.
`workcenter verify` checks the name exists. A requirement the design fails
gets no bound: the package's traceability table says FAIL.

## A part's temperature

A part that dissipates power heats its junction above the ambient. The
gate computes the junction at every run it judged, the deck as written
and each corner, and holds it to the derated limit of the project's
rating pack. The sum is TJ = TA + RthetaJA x power (TI SPRA953D, section
1.1, equation 1, page 2). TA is the run's temperature: the deck's own, or
the corner's. `tests/boards/fail-sim-thermal` is a worked example.

Read what the sum rests on. EIA/JESD51 defines how RthetaJA is measured,
on a test board. SPRA953D, section 1.1, page 2, calls equation 1 a
misapplication on a system board, with erroneous results: the test board
is the heat sink, and RthetaJA changes with the board. Section 1.2, page
3: a JEDEC 2s2p board gives a best case, a 1s board a typical one. So a
part the gate holds is held on the datasheet's board, and the facts name
that board for each figure. The 2 boards are `1s0p` (the low-k board of
JESD 51-3) and `2s2p` (the high-k board of JESD 51-7), as SPRA953D names
them (table 3-1, note 11, page 9). A figure whose board the facts do not
name holds no part. Every printed `thermal` line names the board. JESD51
itself was not read: JEDEC refused the workcenter's client name.

Where the project knows the case, the board or the package top's
temperature (measured, or computed by `workcenter copper`), the gate takes
the junction from it: TJ = T(PCB) + psi_jb x power (SPRA953D, section
5.1, equation 9, page 11), TJ = TC + psi_jt x power (section 3, equation
8, page 8). theta_jc puts all of the power through the case, so the
junction it gives is above the real one (section 2.2, equation 4, page 7).
SPRA953D calls theta_jb useful for a first-pass estimation only, and gives
no bound on the junction it gives (section 4, page 10), so a junction from
theta_jb holds no part. Prefer psi_jb or psi_jt.

1. Give the part its thermal facts, in the facts file `workcenter
   ratings` reads (`library/facts/`, the `ratings` skill). Copy the
   figures from the datasheet's thermal table, in C/W, the absolute
   maximum junction temperature, and the JEDEC board of each figure
   (the table's footnote), with the pages:
   ```json
   "thermal": {"junction_max": 150, "theta_ja": 231.1, "psi_jb": 63.8, "page": [4, 5],
               "boards": {"theta_ja": "2s2p", "psi_jb": "2s2p", "page": 5}}
   ```
   The figures are `theta_ja`, `theta_jc`, `theta_jb`, `psi_jt` and
   `psi_jb`. Take the column of the part's package. A row measured on a
   maker's own board (an EVM row) is no JEDEC board: leave it out.
   `thermal` stands on an `ic`, a diode or a MOSFET. A second reader
   compares every number with the datasheet and sets `second_reader`.
2. Print the part's power from a deck, once per run: its input power
   less its output power.
   ```
   let p_u1 = -v(in) * i(vin) - v(out) * i(vu1)
   print p_u1
   ```
3. Name the part in `sim/thermal.json`, with the pack the project holds
   its parts to (`rules/ratings/`, or a path from the project's folder):
   ```json
   {"pack": "ecss-q-st-30-11c-rev2",
    "parts": {"U1": {"mpn": "TLV75533PDBVR", "watts": "ldo.p_u1",
                     "source": "the deck's input power less its output power"}}}
   ```
   When the board's, the case's or the top's temperature is known at an
   ambient, add `from` to the part: the figure, the temperature at each
   ambient of a run (the deck as written or a corner), and its source:
   ```json
   "from": {"figure": "psi_jb", "celsius": {"85": 101.5},
            "source": "workcenter copper, build/copper/report.json, hottest near U1, air 85 C"}
   ```
   A run within 0.01 C of an ambient `from` names is judged from that
   temperature; the other runs from theta_ja. A temperature at or under its
   own ambient is set aside, and the part is not held: the part's heat
   flows from its junction through its case and board to the air
   (SPRA953D, section 4, figure 4-1, page 10). So is a `from` whose figure
   the facts do not give: theta_ja judges every run. A junction from a
   stated temperature under the one theta_ja gives on a 2s2p board, which
   SPRA953D calls a best case (section 1.2, page 3), holds no part. Only
   that bound checks a stated temperature: when the facts give theta_ja on
   the 1s0p board, on no board, or no theta_ja, the stated temperature is
   checked against no board, and the part is not held (a warning, a
   failure with `--strict`). A case on a heat sink is what theta_jc was
   devised for (SPRA953D, section 2, page 6; section 2.2, equation 5, page
   7): with theta_jc, name what holds the case in `heat_sink`, and the
   2s2p bound does not apply; the statement and its source stand on their
   own. `heat_sink` is refused with any other figure (psi_jt is not used
   with a heat sink, section 3.2, page 10). 2 keys within 0.01 C of each
   other are refused. The part's `thermal` line names the stated
   temperature and its source when its worst run used it, and, when the
   facts give theta_ja, the junction theta_ja gives at those runs and its
   board, so the owner sees how far the statement moves the verdict.
   Without `sim/thermal.json` the gate judges no junction and prints 1
   line that says so.
4. Run `workcenter sim <project>`. Read each line that starts with
   `thermal:`, and each line that starts with `corners.json: decks.`:

   | Line | What to do |
   |---|---|
   | `thermal: U1 (MPN) at 85 C ambient: junction 124.97 C, over 110 C (...)` | The part runs too hot at that corner. Take power off it (a lower input voltage, a switching regulator, a lighter load), or choose a package with a lower figure. Never widen the corner. |
   | `thermal: U1 (MPN) not judged: no facts entry names ...` | Write the part's facts from its datasheet (the `ratings` skill). |
   | `... not judged: its facts give no thermal figure` | Add `thermal` from the datasheet's thermal table. |
   | `thermal: U1 (MPN) at 60 C ambient: junction 111.01 C, over 110 C (...): board 100 C at 60 C ambient (source) + ...` | The stated temperature puts the part too hot. Take power off it, or cool the board where the part stands. |
   | `... not judged: its facts give theta_jc ..., and no theta_ja` | The figure needs the case's, the board's or the top's temperature. State it in `from` with its source, or find RthetaJA in the datasheet. |
   | `... not judged: sim/thermal.json names psi_jb in from, and its facts ... give no psi_jb` | Name a figure the facts give, or add the figure from the datasheet. |
   | `... not judged as written: sim/thermal.json states its board temperature at 85 C ambient only, ...` | State the temperature at that run's ambient too, or add theta_ja to the facts. |
   | `thermal: U1 (MPN): sim/thermal.json states its board temperature at 70 C ambient, where no run of ldo stands` | The ambient matches no run: write the run's temperature (the deck's own or a corner's). |
   | `thermal: U1 (MPN) not held: its facts (...) name no JEDEC board for theta_ja` | Write `boards` from the thermal table's footnote. A figure on no JEDEC board holds no part. |
   | `... not held at 85 C: its stated board 85.001 C, which gives a junction of 96.035 C, was checked against no board: ...` | Nothing bounds the stated temperature. Judge the part on theta_ja (take `from` out), or, for a case on a heat sink, state theta_jc with `heat_sink`. |
   | `thermal: no part's junction is judged: sim/thermal.json is not there, ...` | Name each part that dissipates power in `sim/thermal.json` (step 3). |
   | `corners.json: decks.ldo.temperature runs -20 C and 60 C, so 85 C of the file's -20 C and 85 C is not run for ldo` | The deck's own block leaves out a temperature of the file, an end or an inner one. Add it to the deck's block, or take the block out so the deck runs the file's. |
   | `... not judged: its deck ... did not run to its end` | Fix the deck first; its errors are in the same result. |
   | `... not judged at the corners of sim/corners.json: the file skips deck ...` | The deck's `skip`, `--nominal`, `temperature: false` or a narrower `temperature` block left the corners out. Run the part's power in a deck the corners run. |
   | `... not judged as written: the deck ran at 25 C and 85 C, ...` | The deck sets more than 1 temperature, so the run that printed the power is not known. Run 1 temperature per deck; put the others in `sim/corners.json`. |
   | `thermal: U1: ldo.p_u1 is not printed at ...` | Print the measure in every analysis the corners run. |
   | `thermal: U1: ldo.p_u1 is -0.17 W ...` | The deck's sum has a sign wrong: a part's dissipation is not under 0. |
   | `thermal.json: ...` | The file is wrong in the place the line names. |

   A not judged line is a warning, and fails `--strict`. A part with a
   run or a corner not judged is not held, even when the runs judged are
   under the limit.
5. `--json` holds each part under `details.thermal.parts`: the figures
   used and their boards, the limit and its source, `assumes` (the board
   and the method of each figure), `read_once` (the facts or the rule no
   second reader compared), the run as written and the worst run, each
   with its ambient, its power, its figure, the stated temperature when
   there is one (`from`) and its junction. `held` is true, false, or null
   when a run or a corner was not judged or a figure has no board.

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
