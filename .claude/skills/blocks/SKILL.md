---
name: Blocks
description: Adds a circuit block to a design file in 1 call - today a buck regulator by TI SLVA477C - from the input range, the output voltage and the load current; the block works out each part's value by the note's equations, takes each part from the designer's stock, writes its ratings.json entries, its parts.csv rows and its deck, and fails on 1 line that names the equation no stocked part meets.
---

# Blocks

A block is a part of a schematic that a maker's note tells how to build.
`tools/blocks.py` holds the blocks. A design file calls 1 and gets the parts
on its sheet and on its board, the sums that chose each value, and the files
that `workcenter ratings` and the SIM gate read.

| Block | Note | Rules | ICs |
|---|---|---|---|
| `blocks.buck` | TI SLVA477C, equations 1, 2, 3, 4 and 11, sections 3, 6 and 7; the datasheet's equations 1 (7.3.2) and 2, table 4 and sections 6.3, 6.5, 8.2.2.4 and 8.2.2.5 | `rules/blocks/buck.json` | TLV62569DBVR |
| `blocks.usbc` | USB Type-C R2.5, tables 4-20, 4-27, 4-28, 4-35, 4-36 and 3-5; USB 2.0 table 7-7 and 2 ECNs. Its steps: `usbc.md` beside this file | `rules/blocks/usbc.json` | GCT USB4115-03-C, TI TPD2E2U06DCKR |
| `blocks.i2c` | TI SLVA689A, equations 1, 5 and 6, table 2-1, section 3 | `rules/blocks/i2c.json` | any device whose facts give its bus pins (see "The I2C block" below) |
| `blocks.mcu` | TI SLAA322D, equations 1, 3 and 5 and table 2; the datasheet SLASE35C, sections 5.3 and 5.13; SLAU278AH figure 2-3; SLAU272D table 1-4 | `rules/blocks/mcu.json` | MSP430FR5720IRGE |
| `blocks.ldo` | TI SLVA079, equations 1, 8, 10 and 11; the datasheet's equations 6 and 7, tables 6-1 and 8-1 and sections 5.3, 5.5 and 7.1.1 | `rules/blocks/ldo.json` | TLV75533PDBVR, TLV75533PDRVR |

A block holds what its note states and no more. A part the note does not
cover is your own schematic, and `workcenter ratings` judges it.

## What a block reads

- `rules/blocks/<block>.json`: the note's equations with their pages, and per IC
  the numbers of its datasheet the note asks for (the current limit, the
  inductor, R2, the output capacitance), each with its section, table and page.
- `library/facts/`: each part's own ratings, the same entries `workcenter ratings`
  reads. The IC's reference, operating input range and least switching
  frequency; each inductor's saturation current, tolerance and DC resistance
  at the most (`ohms_dc`); each capacitor's rating, tolerance and the value it
  keeps under voltage. A stocked part with no facts is not taken; a capacitor
  whose facts give no `volts` or no `tolerance` is passed over and named. An
  inductor with no `ohms_dc` is taken, and its dropout sum says its DCR is not
  judged.
- The spec: `vin=(least, greatest)`, `vout` and `amps`, each a finite number.
  An input range written greatest first is refused.
- Your stock: a list of `blocks.Stock(maker, mpn, value, footprint)` in the
  order you want them tried. The Value is what the schematic shows.

## Steps

1. Write the facts of each part you stock into `library/facts/`, as the
   `ratings` skill says. Then run `workcenter ratings --facts <REF>` on a board
   that holds the part, or read the facts file again against the datasheet.
2. In `design.py`, call the block after your own parts:

   ```python
   import blocks

   block = blocks.buck(d, ic="TLV62569DBVR", vin=(4.75, 5.25), vout=3.3, amps=0.5,
                       nets=("+5V", "+3V3", "GND"), stock=STOCK,
                       facts=Path(__file__).parent / "library" / "facts",
                       sch_at=(76.2, 76.2), pcb_at=(108.0, 104.0))
   d.files = {
       "ratings.json": blocks.ratings_json("nasa-eee-inst-002", block.ratings, own),
       "parts.csv": blocks.parts_csv(block.rows + my_rows),
       **block.files,
   }
   ```

   `own` holds what your part of the board states: the ground net, each
   connector's load. `tests/boards/block_buck.py` is a whole example.
3. Run `workcenter design design.py`. What it prints:
   - `file: line N: buck U1: ...`: the block refused. The line names the value,
     the limit, the equation and the page. Do as the line asks:
     - `no stocked inductor holds the peak of X A with 20 % of margin, Y A`:
       add an inductor of the datasheet's value whose facts saturate at Y A or
       more and carry the load in rms current, or lower the load. The block
       counts the inductance at its least: the part's tolerance or the
       datasheet's own derating, the larger.
     - `IMAXOUT = ... under the load`: the IC cannot give the load (equation 3).
       Take another IC.
     - `the load of X A is over ...`, `a load of 0 A`, `the input reaches X V`,
       `VOUT of X V is under ...` or `is over the least input`, `D = ... over 1`:
       the IC's datasheet or the note does not allow the spec. Change the spec
       or take another IC.
     - `R1 of ... and R2 of ... set VOUT to X V, A to B ..., and Y V is asked`,
       or `... set VOUT to X V, N % under the Y V asked`: the stock has no
       resistor near the R1 the line names. Add one; the output it sets must
       hold the asked voltage between the reference's limits and the
       resistors' tolerances, and lie within the reference's own accuracy of
       it (2 % for the TLV62569: VFB of 588 mV to 612 mV).
     - `VIN(MIN) = ... over the least input`: at the least input the IC runs at
       100 % duty cycle and cannot hold the top of the output's span (the
       datasheet's equation 1, section 7.3.2). Raise the least input, lower the
       load, or stock an inductor of lower DCR.
     - `the facts of ... give no ...` or `... gives ... no ...`: the IC's facts
       or its rules entry lack a number the block reads. Add it from the
       datasheet with its page.
     - `no stocked resistor of ...`, `no stocked capacitor ...`: add the part
       the line names to the stock, with its facts. A capacitor is taken only
       when its facts name a dielectric the datasheet names (X5R or X7R for the
       TLV62569) and the value it keeps under voltage, less its tolerance, at
       the output's highest voltage; at the input, at the greatest input, or
       its written value less its tolerance when its facts give no kept value,
       which its sum says is not judged. The line says why each stocked
       capacitor was passed over.
   - `design ... green`: the parts, `ratings.json`, `parts.csv` and
     `sim/buck.cir` are written.
4. Open `sim/buck.cir`. Its comment lines after `* The sums:` are `block.sums`:
   1 line per value, each with its equation and page. Copy them into the
   version's README under the block's decisions.
5. Run `workcenter ratings . --strict`. Each `fail` line is a part the block
   did not choose or a rating the note does not cover: fix it as the `ratings`
   skill says. Each `not judged` line names what is missing.
6. Run `workcenter design design.py --route`, then `workcenter gates . --strict`,
   as the `board-gates` skill says. The SIM gate runs `sim/buck.cir` and holds
   the inductor's peak current to its saturation current.

## The microcontroller block

`blocks.mcu` adds an MSP430 with its 32768 Hz crystal and the crystal's 2
load capacitors, a bulk capacitor and 1 bypass capacitor on each supply
pin, VCORE's capacitor, the reset pull-up and capacitor, and the 14-pin
Spy-Bi-Wire header. `tests/boards/block_mcu.py` is a whole example.

1. Write the facts of each crystal you stock into `library/facts/` with
   `"kind": "crystal"`: `hertz`, `ohms_esr` (the datasheet's R1 or ESR at
   the most), `farads_load`, `farads_shunt_max` (C0 at the most) or, when
   the datasheet states only a typical C0, `farads_shunt`, and
   `watts_drive`. Add `terminals`: the 2 pins the maker's outline drawing
   puts the crystal between, and where it says so, as
   `{"pads": ["1", "4"], "where": "page 2, ..."}`. Read them from the
   drawing: a 4-pad crystal is often not on pads 1 and 2.
   Write the facts of each load capacitor with its `dielectric`, `volts`
   and `tolerance`. The block takes only C0G.
2. Measure or estimate the board's capacitance on each crystal pin, in
   farads: the block's `stray`. Call:

   ```python
   block = blocks.mcu(d, ic="MSP430FR5720IRGE", vcc=(3.2505, 3.3495), stray=1e-12,
                      nets=("+3V3", "GND"), stock=STOCK, facts=FACTS,
                      sch_at=(50.8, 63.5), pcb_at=(105.0, 102.0))
   ```
3. Run `workcenter design design.py`. What it prints:
   - `mcu U1: no stocked crystal starts with a safety factor of 3: ...`:
     each crystal is named with the reason. `SF = ... under 3`: stock a
     crystal of lower ESR or of lower C0 (equations 1 and 5). `its shunt
     capacitance ... is over 1.6 pF`: the datasheet does not allow it. `its
     load ... is no load OALF is stated at`: stock a crystal of 6 pF or
     12 pF. `its facts give no shunt capacitance`: add `farads_shunt_max`
     or `farads_shunt`. `its facts name no 2 terminal pads`: add
     `terminals`.
   - `no stocked capacitor is C0G, rated for ... and within its own
     tolerance of it`: the line names the 3 nearest capacitors and why
     each is not taken. Stock a C0G capacitor whose value is within its
     tolerance of the CL1 the line gives.
   - `CL1 = ... for ...: the pins and the board hold more than its load`:
     the stray is too large for the crystal's load (equation 3). Shorten
     the traces or take a crystal of a larger load.
   - `no stocked capacitor of ...` or `no stocked resistor of ...`: add the
     part the line names, with its facts.
   - `the supply reaches ...`: the supply is outside the IC's range.
   - `vcc = ...`, `stray = ...` or `nets = ...`: an argument is wrong; the
     line names it and its value.
   - `the board as built: ...`: the block's own check (check()) found a
     fault after it placed the parts. It checks the crystal's terminal
     pads, the load capacitors' value by equation 3, VCORE, the ratio at
     VCC, the pull-up's value, the reset capacitor and the header. Report
     it: it is a fault of the block.
4. The sums name each passed-over crystal, the ESR and SF of the one
   taken, the pads XIN and XOUT go to, the load capacitor and the CLoad it
   gives, the decoupling and its ratio, the reset network and the header.
   Copy them into the README. The drive level is printed as not judged:
   the documents state none. A crystal whose datasheet gives only a
   typical C0 is printed as not judged against the 1.6 pF limit.
5. Run `workcenter ratings . --strict`, then `workcenter design design.py
   --route` and `workcenter gates . --strict`.

## The linear regulator, `blocks.ldo`

The block takes the first stocked IC of `rules/blocks/ldo.json` that holds 6
checks, then 1 input and 1 output capacitor. List the ICs in your stock in the
order you want them tried; a package with a lower RthetaJA after a smaller one
lets the block move to it when the junction runs hot.

1. In `design.py`, call it after your own parts:

   ```python
   block = blocks.ldo(d, vin=(4.75, 5.25), vout=3.3, amps=0.1, ambient=(0, 30),
                      pack="nasa-eee-inst-002", nets=("+5V", "+3V3", "GND"),
                      stock=STOCK, facts=Path(__file__).parent / "library" / "facts",
                      sch_at=(76.2, 76.2), pcb_at=(111.0, 108.0))
   ```

   `vin` is (least, greatest) in V and `ambient` is the least and the greatest
   air temperature around the board, in C, each a finite number. `pack` is the
   pack of your `ratings.json`. `tests/boards/block_ldo.py` is a whole example.
2. Run `workcenter design design.py`. What it prints:
   - `ldo U1: vin=(A, B) is written greatest first` or `ambient=(A, B) is
     written greatest first`: write the range least first.
   - `ldo U1: <name>=...: each number of the spec must be finite`: give a
     number, not NaN or infinity.
   - `ldo U1: ldo.json: its note gives no page of equation N`: the rules file
     is damaged. Enter the page from TI SLVA079.
   - `ldo U1: no stocked IC holds the spec: <MPN>: ...`: each stocked IC and
     why it missed, with its equation and page. Do as each says:
     - `regulates to VOUT(NOM) = A V, not the X V asked`: the IC is fixed at
       another output (table 8-1 of its datasheet). Stock the IC of the output
       you ask.
     - `ldo.json gives it no <keys>` or `ldo.json holds <key> as <value>,
       not <shape>`: the IC's entry lacks those numbers or their `where`, or
       holds one the block cannot read. Enter them from the datasheet (see
       "Adding an IC to a block" below).
     - `<file> gives no <keys>: the block judges no IC whose facts lack it`:
       the IC's facts lack its RthetaJA (`thermal theta_ja`), its input's range
       (`IN operating`) or its ground current (`IN amps`). Enter them from the
       datasheet (the `ratings` skill).
     - `the input reaches X V, IN operates from ...`: change the input range
       or the IC.
     - `IOUT of X A is over ...`: the IC cannot give the load.
     - `VDO = ...; VOUT(NOM) + VDO = X V, not under the least input`: the
       least input is too low for the full load (SLVA079 equation 1). Raise
       the least input, lower the load, or stock an IC of lower dropout.
     - `TJ = ... C, over ... C`: the junction at the greatest ambient passes
       the pack's limit. The dissipation is taken at the greatest input and
       the least output the IC's accuracy gives. Stock a package of lower
       RthetaJA, lower the input, the load or the ambient.
     - `TJ from the least ambient, A C, to B C, not within TJ's ...`: the
       ambient is colder, or the junction hotter, than the datasheet's
       recommended junction span. Change the ambient or the IC.
   - `ldo U1: no stocked capacitor holds C2 at X V: ...`: each stocked
     capacitor and why it missed: its dielectric, its rating, its value
     outside the datasheet's span, no curve of the value it keeps, a curve
     over temperature (`kept_celsius`) that does not cover the ambient, or
     what it keeps at the pin's voltage and the worst ambient less its
     tolerance not over 0.47 uF. Stock a part that holds, with its facts and
     its curves.
   - `ldo U1: a load of 0 A`: give the load you draw.
3. Read `block.sums` in `sim/ldo.cir` after `* The sums:`. A line
   `U1: <MPN> passed over: ...` names an IC the block tried first. The line
   `its CSR is not judged` says the datasheet gives no stable CSR range: the
   block does not judge the output capacitor's ESR. A capacitor line that
   says `its value over temperature is not judged` names a part whose facts
   give no `kept_celsius`: add its maker's curve. The junction line ends with
   what RthetaJA rests on: the datasheet's JEDEC test board. A board unlike
   it changes RthetaJA (SPRA953D, section 1.1, page 2): say in the README how
   yours differs. Copy the sums into the version's README.
4. Run `workcenter ratings . --strict`, then `workcenter design design.py
   --route` and `workcenter gates . --strict`. The SIM gate runs `sim/ldo.cir`
   at each temperature of `sim/corners.json` and holds U1's junction under the
   pack's limit (`sim/thermal.json`), and the load to the IC's IOUT
   (`sim/ldo.expect.json`). The deck draws U1's output at the least its
   accuracy gives, where it dissipates the most; it does not model the IC's
   regulation, so no bound holds `vout`.

## Adding an IC to a block

1. Download the IC's datasheet under the workcenter's name into a folder
   outside every repository, and its SHA256 with `sha256sum`.
2. Add an entry to `ics` in `rules/blocks/<block>.json` with each number and
   its `where`: section, table and page. A number you cannot find in the
   datasheet is not entered; the block then refuses that IC on 1 line that
   names the missing key (`blocks.BUCK_NAMES` and `blocks.BUCK_NUMBERS` list
   what `buck` reads; `blocks_ldo.LDO_NAMES`, `LDO_NUMBERS` and `LDO_WHERES`
   what `ldo` reads).
3. Add the datasheet to `rules/references/index.json`, and run
   `workcenter references rules`: it fails a source the index lacks.
4. Write the IC's facts into `library/facts/` (the `ratings` skill).
5. Run `python -m pytest tests/test_blocks.py`.

## The I2C block

`blocks.i2c` (`tools/blocks_i2c.py`) adds the 2 pull-ups of an I2C bus, from
the bus voltage, the speed and the bus capacitance, by TI SLVA689A. It takes
the first stocked resistor that holds RP(min) and RP(max) at its tolerance.
NXP's specification UM10204 could not be had; the note's table 2-1 gives the
specification's tr, Cb and VOL.

1. Add every device on the bus to the design first, with its own parts. A
   connector stands for what is off the board.
2. Give each device facts in `library/facts/` (the `ratings` skill). Each pin
   on SDA or SCL needs its role (`open_drain`, `io` or `input`), `abs`, and
   `operating`. An `open_drain` or `io` pin needs `"sink": {"amps": A,
   "volts": V}`: the least current its datasheet says it sinks at that low
   voltage. Add `"farads"`, the pin's greatest capacitance, where the datasheet
   gives one. `tests/boards/library/facts/ti-tca9534.json` is an example.
3. In `design.py`, after the devices:

   ```python
   block = blocks.i2c(d, volts=(3.135, 3.465), speed="fast",
                      nets=("SDA", "SCL", "+3V3"), devices={"U1": "TCA9534DWR"},
                      stock=STOCK, facts=Path(__file__).parent / "library" / "facts",
                      farads=100e-12, sch_at=(101.6, 63.5), pcb_at=(112.0, 104.0))
   ```

   `speed` is `standard`, `fast` or `fast-plus`. `nets` is (SDA, SCL, the
   supply the pull-ups go to): 3 different nets. `volts` is the supply's
   span, least first. `farads` is the bus
   capacitance of each line, stated by you. With no connector on the bus you
   may give `track=(mm, farads_per_mm, "where the figure comes from")` in its
   place: the block sums each device's `farads` and the track, and refuses a
   device pin whose facts give no `farads`. Each number is finite and over 0.
   Put `block.ratings`, `block.rows` and `block.files` into `d.files` as for the
   buck block. `block.ratings` states the supply's span, `volts`;
   `blocks.ratings_json` refuses a design that states another span for the
   same net. `tests/boards/block_i2c.py` is a whole example.
4. Run `workcenter design design.py`. What it prints:
   - `i2c R1 R2: no stocked resistor lies between RP(min) = X and RP(max) = Y`:
     the line names each stocked resistor and the bound it misses at its
     tolerance. Add a resistor whose value less its tolerance is X or more and
     plus its tolerance is Y or less.
   - `RP(max) = ... is under RP(min)`: the bounds cross. Lower the bus
     capacitance (a shorter bus, fewer devices), or take a slower speed.
   - `Cb of X is over the Y of fast mode`: the same.
   - `U1 SDA: RP(min) = ..., its sink` in the sums: that device sinks less
     than table 2-1 asks, and its bound is the one held.
   - `i2c U1 SDA: the bus reaches X V, over its absolute maximum` or
     `operating limit`: the device cannot sit on this bus. Take another
     device or a level shifter.
   - `i2c U1 SCL: pin 14 is on SDA, not on SCL`: a device's pin named SDA
     or SCL is on the other line or on no net. Fix the wiring.
   - `the pull-ups go to GND, and U1 GND ... is on it`: `nets` names a ground
     as the supply. Name the supply.
   - `ratings.json +3V3: ... 1 net holds 1 span`: the design states a span
     for the supply that is not `volts`. Make them agree.
   - `its role is output`, `its facts give no sink`, `no facts of`,
     `give no pins`, `devices names no part number`, `a connector on SDA ...
     state the bus capacitance`, `its facts give no capacitance`, `the stated
     Cb ... is under ...`, `written greatest first`, `a finite number over 0`:
     fix what the line names.
   - `its facts give no capacitance: not in the devices' sum` in the sums:
     with `farads=`, that pin's capacitance is not judged; your stated Cb
     must hold it.
   - `design ... green`: the pull-ups, `ratings.json`, `parts.csv` and
     `sim/i2c.cir` are written.
5. Read the sums after `* The sums:` in `sim/i2c.cir`. A line that says
   `not judged here` names a limit `workcenter ratings` judges in step 6.
   The line `the devices' greatest clock is not judged` means: read each
   device's datasheet for its greatest clock against the speed you asked.
6. Run `workcenter ratings . --strict`, then `workcenter design design.py
   --route` and `workcenter gates . --strict`. The SIM gate runs
   `sim/i2c.cir` at the resistor's tolerance and holds SDA's rise to the
   speed's tr.

The block writes `sim/corners.json` for its own deck. A design with 2 blocks
that both write it must merge the 2 by hand.
