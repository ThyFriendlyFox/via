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
| `blocks.buck` | TI SLVA477C, equations 1, 2, 3, 4 and 11, sections 3, 6 and 7; the datasheet's equation 2, table 4 and sections 6.3, 8.2.2.4 and 8.2.2.5 | `rules/blocks/buck.json` | TLV62569DBVR |
| `blocks.i2c` | TI SLVA689A, equations 1, 5 and 6, table 2-1, section 3 | `rules/blocks/i2c.json` | any device whose facts give its bus pins (see "The I2C block" below) |

A block holds what its note states and no more. A part the note does not
cover is your own schematic, and `workcenter ratings` judges it.

## What a block reads

- `rules/blocks/<block>.json`: the note's equations with their pages, and per IC
  the numbers of its datasheet the note asks for (the current limit, the
  inductor, R2, the output capacitance), each with its section, table and page.
- `library/facts/`: each part's own ratings, the same entries `workcenter ratings`
  reads. The IC's reference, operating input range and least switching
  frequency; each inductor's saturation current and tolerance; each
  capacitor's rating and the value it keeps under voltage. A stocked part with
  no facts is not taken.
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
     - `R1 of ... and R2 of ... set VOUT to X V, A to B ..., and Y V is asked`:
       the stock has no resistor near the R1 the line names. Add one; the
       output it sets must hold the asked voltage between the reference's
       limits and the resistors' tolerances.
     - `no stocked resistor of ...`, `no stocked capacitor ...`: add the part
       the line names to the stock, with its facts. A capacitor is taken only
       when its facts name a dielectric the datasheet names (X5R or X7R for the
       TLV62569) and, at the output, the value it keeps under voltage. The line
       says why each stocked capacitor was passed over.
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

## Adding an IC to a block

1. Download the IC's datasheet under the workcenter's name into a folder
   outside every repository, and its SHA256 with `sha256sum`.
2. Add an entry to `ics` in `rules/blocks/<block>.json` with each number and
   its `where`: section, table and page. A number you cannot find in the
   datasheet is not entered; the block then refuses that IC.
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

   `speed` is `standard`, `fast` or `fast-plus`. `farads` is the bus
   capacitance of each line, stated by you. With no connector on the bus you
   may give `track=(mm, farads_per_mm, "where the figure comes from")` in its
   place: the block sums each device's `farads` and the track. Put
   `block.ratings`, `block.rows` and `block.files` into `d.files` as for the
   buck block. `tests/boards/block_i2c.py` is a whole example.
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
   - `its role is output`, `its facts give no sink`, `no facts of`,
     `devices names no part number`, `a connector on SDA ... state the bus
     capacitance`, `the stated Cb ... is under ...`: fix what the line names.
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
