---
name: Ratings
description: Holds a schematic to its parts' ratings - each pin's voltage limits, each capacitor's, resistor's, diode's and transistor's derating by a named standard, each regulator's output, load and support parts - from facts read off the datasheets, each entry with its document and each pin's numbers with their page.
---

# Ratings

An electrical rules check knows a pin's type. It does not know that the pin
dies above 4.6 V, that a 6.3 V capacitor on a 5 V rail is past its derating,
or that an inductor saturates below the current its regulator draws.
`workcenter ratings` judges those before the board is routed. Every line
that holds a stress to a limit names the document the limit comes from:
a pack's limit with its table and page, a pin's limit and a needed
part's with the page of the datasheet. The own rating of a resistor, a
capacitor, an inductor, a diode or a transistor is named with its
datasheet and no page: the facts of those kinds hold none.

## When

- A schematic exists and the board is not routed yet: a part that fails is
  a line to change now, and a respin later.
- A part, a value, a rail's voltage or a load changed.
- A human asks whether the parts are inside their ratings, or for a
  derating review.

## Inputs

| File | Holds | Who writes it |
|---|---|---|
| The schematic | The parts, their Values and their nets. The command exports the netlist with `kicad-cli`. | The design |
| `ratings.json`, beside the schematic | The rule pack, and what the board cannot say of itself: the voltage of each net a source off the board fixes, a load's current, the ambient temperature, a failure the owner accepts. | You, each entry with its source |
| `library/facts/*.json`, in the project's folder or a folder above it | What each part's datasheet says: 1 entry for a part or a family of parts. | You, each entry with its source and each pin's numbers with their page |
| `parts.csv` | The manufacturer part number of each Value and Footprint, as `procure` and `sources` read it. A part with no number is named by its symbol. | The procurement skill |
| `rules/ratings/<pack>.json`, in the workcenter | The limits of a derating standard, each with its table and page. | The workcenter. Never edit one to pass |

The worked example is `tests/boards/pass-ratings-node` with the facts in
`tests/boards/library/facts/`: a buck regulator, 2 logic buffers and their
parts, each entry read from its datasheet.

## Steps

1. Run `workcenter ratings <project> --init`. It writes `ratings.json` with
   the pack `nasa-eee-inst-002` and no net.
2. State each net a source off the board holds, under `nets`: the net's
   name as the schematic has it, `volts` as `[least, greatest]`, and
   `source`, the document or the requirement the 2 numbers come from.
   Ground is `[0, 0]`. A regulator's output is not stated: the command
   works it out.
3. Run `workcenter ratings <project>`. Take the `not judged` lines first,
   top to bottom. Each has 1 cause:

   | The line says | Do |
   |---|---|
   | `no facts for <part number>` | Write the part's facts: step 4. |
   | `<pin> can put a voltage on <net> that nothing states` | A connector's pin. A source stands behind it: state the net in `nets`. A load stands behind it: state its current under `parts`, as `"J2.1": {"amps": 1.1, "source": "..."}`; 0 for a pin that takes none. |
   | `feeds a load nothing states` | The line names what takes a current nothing states. A supply pin: add `amps` to its facts, from the datasheet's supply current. A part with no facts: write them, or state the pin's current under `parts`. A resistor with no number: state its current under `parts`. |
   | `stands there and has no facts` | A part stands where a datasheet asks for a capacitor or an inductor. Write its facts: step 4. |
   | `its divider is ...`, `stands on <net> too` or `nothing sets the output` | The command reads 1 resistor to the output and 1 to a net at 0 V. State the output's net in `nets`, with the sum as its source. |
   | `accepts a failure of ..., and <part> is not judged now` | Give the part what its own `not judged` line asks for. The acceptance then meets its failure again. |
   | `no source holds <net>` | Nothing the command knows drives the net. State it in `nets`, or correct the facts of the part that drives it. For the net behind a sense resistor, state the resistor's current under `parts`: the net then follows the resistor's other net. |
   | `has no data on the value it keeps` | Add `kept` to the capacitor's facts from its maker's DC bias curve, or fit a part that has one. |
   | `its facts hold no voltage rating` or `has no tolerance in its facts` | Add `volts` or `tolerance` to the capacitor's facts from its datasheet. With no datasheet in `library/`, get it first. |
   | `its facts hold no current rating` | `ratings.json` states a current through the part. Add the rating to its facts from its datasheet: `amps_forward` for a diode, `amps_drain` for a transistor, `amps` for a ferrite or a switch. |

4. Write 1 part's facts. `workcenter ratings <project> --facts U1` prints
   the entry to fill, with the part's number and its pins; save it as
   `library/facts/<maker>-<part>.json`. Open the datasheet the project's
   `library/` holds (PROCESSES.md P27). Fill each key from the page it
   stands on, as the tables below say. Rules:
   - A number is the one the datasheet prints, in volts, amps, ohms,
     farads, henries, hertz or watts: `4.7e-6` for 4.7 uF. The command
     takes 0 and numbers from 1e-18 to 1e15, either side of 0.
   - `page` is the page a number stands on; a list when the numbers of 1
     pin stand on 2 pages. A pin, a needed part and `switching` hold a
     `page`. An entry of another kind holds none: write the page of its
     numbers in its `note`.
   - The absolute maximum ratings go in `abs`. The recommended operating
     conditions go in `operating`. Never one in place of the other.
   - A number the datasheet does not state is left out. The command then
     says what it could not judge. Never fill a key from memory or from
     another part's datasheet.
   - A pin's number is the symbol's, which is the footprint's pad. Find
     each pin on the datasheet's package drawing by its place, not by its
     number: a datasheet may number a SOT-23 another way than the
     footprint does. Where the 2 differ, the `note` says so.
   - A capacitor whose datasheet cannot be had is entered with its `kind`
     alone, and its `source` says why. The command then knows it passes no
     steady current, and reports the capacitor itself as not judged.
   - What the entry leaves out goes in `note`: the report prints it.
5. Have each entry read a second time, by a reader who did not write it
   and who has the datasheet and the entry and nothing else. The reader
   checks every number against its page and sets `second_reader` to the
   date. Until then the first line of every run counts the entry among the
   `sources not read a second time`.
6. Run the command again. A `fail` line is a fault of the design: fit a
   part with a higher rating, add the capacitor, lower the load, divide
   the signal. Never change a fact, a net's voltage or a pack to pass.
   2 kinds of `fail` line are checked before the design is changed:
   - `the 2 number the pins differently`: hold the facts and the symbol to
     the datasheet's package drawing, and correct the one that is wrong.
   - A part between 2 nets that 1 source moves together: the 2 ends of a
     cell, a bootstrap capacitor. The command subtracts the extremes of
     the 2 nets, which never meet. State the part's voltage under `parts`,
     with its source.
7. A failure the owner takes on is written under `accepted` with the
   owner's reason, as `"by": "the owner's decision of 2026-11-17"`; the
   part and the rule to name stand under the failure in
   `build/ratings/report.md`. The line then prints as `accepted`. An entry
   whose failure is gone fails the run until it is taken out. An entry
   accepts 1 failure. Where 2 failures of 1 part stand under 1 rule,
   neither is accepted until each entry says which it means, with words of
   that failure's line: `"line": "pin IN"`. Facts that number the pins
   differently are no stress and cannot be accepted: the page names no
   rule under that failure.
8. The last line is the verdict: `RATINGS HELD`, `RATINGS HELD, N NOT
   JUDGED`, `NOTHING JUDGED` or `RATINGS NOT HELD`. Run with `--strict` in
   CI once nothing is left not judged: what is not judged then fails.

A file the command does not take stops the run before any judgement. The
run prints `a file is not as the command reads it` and 1 line that names
the file, the place in it and the fault, and exits 1. It prints no
verdict, and `build/ratings/report.md` says that nothing was judged.
Correct the file at that place and run again.

## ratings.json

```json
{
  "pack": "nasa-eee-inst-002",
  "ambient": {"max": 60, "source": "the enclosure's limit, requirement R4"},
  "nets": {
    "GND": {"volts": [0, 0], "source": "the reference: J1 pin 2"},
    "+5V": {"volts": [4.75, 5.25], "source": "USB 2.0, table 7-7"}
  },
  "parts": {
    "J2.1": {"amps": 1.1, "source": "the load's datasheet, page 3"},
    "R7": {"amps": 2.0, "source": "the heater at 4.2 V, sim/heater.cir"},
    "C9": {"volts": 5.5, "source": "the regulator's datasheet, page 4: BOOT to SW"}
  },
  "accepted": []
}
```

- `pack`: `nasa-eee-inst-002` or `ecss-q-st-30-11c-rev2`, or the path of
  a pack of your own from the project's folder. A run that a pack of
  your own judged says so in its first line:
  `pack house.json (the project's own)`.
- `ambient`: the highest air temperature. A limit that falls with
  temperature is judged there; without it, as under the temperature where
  it starts to fall, and the report says so.
- `parts`: `REF.PIN` with `amps` is the load behind a connector's pin.
  `REF` with `amps` is the current through a part that the board cannot
  say: a sense resistor's, an inductor's peak, a rectifier diode's, a
  transistor's drain current, a fuse's, a ferrite's, a switch's. State
  the RMS current for a resistor, a transistor, a fuse, a ferrite and a
  switch, the average for a diode and the peak for an inductor: each
  rating is held to that one. `REF` with `volts` is the greatest voltage
  across a capacitor or a resistor whose 2 nets move together: a
  bootstrap capacitor, a capacitor across a cell.
- The command refuses a number in `parts` that it would hold to nothing,
  once the part has facts. `REF` with `amps` is refused for an IC, a
  capacitor, a clamp diode, a link, a test point, a mechanical part and
  a connector named with no pin (`J2` for `J2.1`). `REF.PIN` with `amps`
  is refused for a pin of any part but a connector and an IC, and for a
  pin of an IC that is no `output`, `io` or `open_drain` pin. `REF` with
  `volts` is refused for any part but a capacitor and a resistor. 1
  current is taken and held to nothing yet: the one behind an `output`,
  `io` or `open_drain` pin of an IC. A note of the report names it.

## A part's facts

Each entry names its parts 1 way: `mpn`, `mpns` (a list), `match` (a part
number with `*` and `?`), or `symbol` (the library symbol, and `footprint`
to narrow it). A symbol's entry speaks only of a part with no part
number. The closest wins: the part number, before a pattern, before
the symbol. Each entry has a `source`: `document`, `revision`, `url`,
`sha256`, `read` (the date) and `second_reader` (`no`, or the date). A
date is written `2026-11-17`, a URL whole and a SHA256 as its 64 hex
digits. Another word in their place is refused: any word but `no` would
count as a second reading.

| `kind` | Keys | Keys it may hold |
|---|---|---|
| `resistor` | `tolerance` (0.01 for 1 %), `watts`, `volts` | `ohms` |
| `capacitor.ceramic`, `.tantalum`, `.film`, `.electrolytic` | | `volts`, `tolerance`, `farads`, `dielectric`, `kept`: pairs `[volts, share of the value kept]` from the DC bias curve; `kept_celsius`: pairs `[celsius, share against 25 C]`, which the SIM gate alone reads |
| `inductor` | `tolerance`, `amps_saturation` | `henries`, `amps_rms`, `kept`: pairs `[amps, share of the value kept]`, which the SIM gate alone reads |
| `diode.rectifier` (rectifier, switching, Schottky) | `diodes`: `[{"anode": "2", "cathode": "1"}]`, `volts_reverse` | `amps_forward`: held to the current the project states for the part |
| `diode.clamp` (zener, TVS) | `diodes`, `volts_standoff` | |
| `transistor.mosfet` | `transistors`: `[{"gate": "1", "drain": "3", "source": "2"}]`, `volts_drain_source`, `volts_gate_source` | `amps_drain`: a number, or pairs `[celsius, amps]` when the datasheet states it at 2 temperatures; held to the current the project states. `watts` |
| `connector` | | `pins`: `[{"numbers": ["1"], "outside": "source"}]`, with `source`, `load` or `nothing` |
| `fuse.cartridge`, `fuse.cermet` (metal film on ceramic), `fuse` (any other style) | `amps`: the rated current, held to the current the project states for the part | `volts` |
| `ferrite`, `switch` | | `amps`: held to the current the project states. `volts` |
| `link`, `testpoint`, `mechanical` | | |
| `ic` | `family`: `digital`, `linear`, `regulator.linear` or `regulator.switching`; `pins` | `needs`, `switching` |

A resistor's, a capacitor's or an inductor's value is read from the
schematic's Value: `4k7`, `100n`, `100 nF`, `2.2u XAL4020`. Without a
number there, or with a bare number before a second value (`0402 10k`),
the entry holds `ohms`, `farads` or `henries`.

An end of a diode or a transistor is 1 pin number, or a list when the
package has several pins for it: `"source": ["1", "2", "3"]`. Every pin
of the part stands in 1 end.

Each pin of an `ic` is 1 entry of `pins`: `numbers`, `name`, `role`,
`page`, and the keys of its role. Every pin of the symbol is named. A
pin number stands in 1 entry and a name names 1 entry: pins that share a
name share an entry, as `"numbers": ["2", "5"]`.

| `role` | The pin | Keys | May hold |
|---|---|---|---|
| `supply` | takes the part's current | `abs` | `operating`, `amps` |
| `ground` | the part's reference | | |
| `input`, `analog` | drives nothing | `abs` | `operating` |
| `output`, `io` | swings between 2 of the part's pins | `abs`, `swing`: `["GND", "VCC"]` | `amps`, `operating` |
| `open_drain` | pulls to 1 pin, or lets go: an open drain to ground, a current output from a supply pin | `abs`, `swing`: `["GND"]` | `amps`, `operating` |
| `regulated` | a regulator's output, a reference's | `volts`, or `set_by` (its feedback pin) | `abs`, `amps`, `from` |
| `feedback` | the tap of the divider that sets the output | `abs`, `volts` | `amps`, `from` |
| `switched` | a converter's switch node | `abs`, `swing` | |
| `nc` | not connected inside | | |

- `abs` is `[least, greatest]`. Each is a number, or
  `{"pin": "VCC", "plus": 0.5}` for a limit that follows another pin, or a
  list of both when 2 limits apply. The 2 ends written the other way
  round are refused. A `regulated` pin that stands in no
  table of limits, as a reference's output may, has no `abs`: a note of
  the report says that nothing holds the pin to a limit.
- `operating` of a supply pin is its working range, 2 numbers:
  `[2.5, 5.5]`. Of a signal pin it is the range the recommended operating
  conditions give its voltage, in the forms `abs` takes:
  `[0, {"pin": "VCC", "plus": 0}]` for "0 to VCC". A pin that holds its
  limits and stands outside this range fails on it.
- `swing` names pins of this part by their `name`. Where it names 2, they
  are 2 pins: 1 pin written 2 times is refused.
- `volts` of a `regulated` pin is the output's span, `[3.234, 3.366]`. Of
  a `feedback` pin it is the reference's span, `[0.588, 0.612]`.
- A rating is above 0, and so are `farads`, `henries` and the `amps` of a
  `regulated` or `feedback` pin: a stress is divided by its rating, and
  a ripple by its inductance. `ohms` may be 0, for a link.
- `amps` of a `regulated` or `feedback` pin is what the regulator gives.
  `from` names the supply pin that current comes from, when the part has 2.
- `needs` lists the parts the datasheet asks for:
  `{"capacitor": {"from": "VIN", "to": "GND", "farads_min": 4.7e-6}, "page": 10}`,
  with `"effective": true` when the datasheet asks for the capacitance
  that is left under voltage, and
  `{"inductor": {"from": "SW", "to": "FB", "henries": [0.7e-6, 2.64e-6]}, "page": 9}`.
  An inductor's need holds `henries`, the least current it saturates at
  as `amps_saturation_min`, or both.
  An end that names a `feedback` pin is the output's net. `from` and
  `to` are 2 pins, and a need asks for more than 0.
- `switching`, for a buck converter:
  `{"topology": "buck", "hertz": [1.5e6, 1.5e6], "page": 5}`, and
  `efficiency` when the datasheet states one.

Recorded and held to nothing yet: `volts` of a fuse, a ferrite and a
switch; `amps` of an `output`, `io` and `open_drain` pin; `watts` of a
transistor; a capacitor's `dielectric`. A connector's facts take no
rating.

## How the command reads a circuit

- Each net has 2 spans. The first is every voltage it can stand at, with
  its sources on or off: a rating is held to it, and 0 V is always inside.
  The second is what its sources hold it to while on: a supply pin's
  working range is held to that.
- A part marked DNP in the schematic is not on the board: it stands in no
  line, and a note of the report names it.
- A pin is judged against what every other pin puts on its net, never
  against its own drive. Another pin of its part is another source: a
  regulator's sense pin stands the output its own divider sets. A limit
  that follows a rail is judged with the rail at the end where the limit
  is tightest. A least limit that follows a pin is judged where the pin's
  own sources hold it while on: with every source off, no limit between 2
  pins is broken. Of 2 limits on 1 end, each is judged on its own. A
  signal pin inside its limits is then held to the range its datasheet
  recommends, when its facts state it.
- A datasheet's limits are against the part's ground pin. Where that pin's
  net is not at the board's 0 V, each limit is taken from that pin: a part
  on a negative rail, a part that floats on a cell.
- A net the project states has its source off the board. A resistor to a
  higher rail lifts it when that source is away: a pull-up to 5 V puts 5 V
  on a signal stated at 3.3 V. What its source holds it at stays as stated.
- While its sources are on, a net that 1 resistor alone feeds stands at
  the net behind the resistor, less the drop of what its pins take: a
  supply pin behind its filter resistor is held to its working range.
- A transistor's drain current, a diode's forward current and the
  current through a fuse, a ferrite and a switch are held to the current
  `ratings.json` states for the part. A rating the datasheet gives at 2
  temperatures is read at the project's ambient. Neither pack holds a
  rule for a ferrite or a switch: each is held to its own rating. A fuse
  is held by its style: NASA's pack holds a `fuse.cartridge` to the row of
  its table 4 that lists its rating, ECSS's pack holds a `fuse.cermet` to
  its table 6-17, and every other fuse is held to its own rating
  (`rules/ratings/README.md`, "A fuse"). A cartridge fuse whose rating
  table 4 does not list, 6.3 A, is not judged. A stated current whose part
  has no current rating in its facts is not judged.
- The nets a wire joins are 1 node: a fuse, a ferrite, a link, a 0 ohm
  resistor, an inductor. A part between 2 nets of 1 node has 0 V across
  it, and its line says `2 nets that a wire joins`.
- A resistor whose current or voltage `ratings.json` states holds its 2
  nets within its drop of each other, whichever way the current runs:
  3.8 A through 20 mohm of 1 % is 76.8 mV. Where a source holds 1 of the
  2 nets, the other is held within that drop of it: the pins behind a
  shunt are judged. A part between the 2 nets stands the drop, and a
  limit between 2 pins on the 2 nets is judged with it. Such a line
  names the resistor: `R7 holds the 2 nets within 76.8 mV`.
- A resistor does not move a net a source holds; a released output follows
  its pull-up. A divider's tap is solved at the corners of its tolerances.
- A resistor is judged with the greatest voltage between its 2 nets. In a
  divider or a row of resistors that nothing else loads, that is its
  share, solved with its nets at the corners of the tolerances. 2 kinds
  are judged with their current: one whose current `ratings.json` states,
  and one that alone feeds supply pins, which carries what the facts of
  those pins say they take.
- An entry that gives a pin's name to another number than the symbol does
  fails: every line of the part would be judged on the wrong net.
- A transistor's channel and a switch may conduct: their 2 nets can meet.
  A diode lifts its cathode. A fuse, a ferrite and an inductor are a wire,
  except an inductor behind a `switched` pin: it carries the average,
  which is the regulator's output. A diode that 2 sources hold forward
  fails: nothing limits its current.
- An output a divider sets is the reference times (1 + top / bottom), at
  the 4 corners of the reference and the tolerances. The top resistor ends
  on the output and the bottom one on a net at 0 V, or on one a link joins
  to it. Any other divider is not judged. The report's notes hold the sum.
- A rail is the nets a current reaches without passing a resistor. A diode
  is passed from its anode to its cathode only. The rail's load is the
  `amps` of each supply pin on it, each current `ratings.json` states for
  a pin there, and each resistor's current as the resistor itself is
  judged. A part with no facts, or a resistor with no number, makes the
  load unknown: the line then fails only when what is known is over the
  limit, as `its loads take at least`. A linear regulator passes its load
  to its input; a switching one passes its load's power, over its
  efficiency (0.9 when its facts state none). A regulator on a net the
  project states shares its loads with that source: a note, and no line.
- A buck's inductor is held to the load plus half the ripple, at the
  greatest input, the least frequency and the least inductance. 2
  inductors side by side carry half the load each.
- A support part stands where the datasheet asks when it joins the 2
  nodes: a fuse, a ferrite, a link or a 0 ohm resistor before it is a
  wire. A part with no facts there is not judged, and is not absent.
- The capacitors between 2 nets are shared: each need takes its own, in
  the order of the parts, and the one that finds too little left fails.

## What it does not judge

Transients, ripple current, a part's temperature, the current in a pin or
a track, a regulator's dropout, the order rails come up in, and anything
of the board: spacing, placement, a capacitor's distance to its pin. A run
that holds says the steady voltages and the stated currents are inside the
ratings the facts hold, and no more.

4 readings are coarser than the circuit, and can fail a part that is
sound. Check such a line by hand before the design changes:

- 2 nets that 1 source moves together are subtracted at their extremes.
  `parts` states the voltage of a part of 2 pins between them.
- A resistor whose network of resistors holds a part that takes a
  current, as a supply pin on a divider's tap does, is judged with the
  greatest voltage between its 2 nets, which may be more than it stands.
  `parts` states its current.
- A part that conducts 1 way or in 1 state is read as able to join its 2
  nets at any time: the transistor of a level shifter, a zener that clamps
  its node, an LED behind its resistor.
- 2 needs on 1 pair of nets take their capacitors in the order of the
  parts' references, each in its own unit.

## Done when

`workcenter ratings <project> --strict` exits 0 and prints `RATINGS HELD`,
every entry of `library/facts/` that the run used has a `second_reader`
date, and each `accepted` entry is the owner's.
