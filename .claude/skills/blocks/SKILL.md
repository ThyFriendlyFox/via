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
| `blocks.usbc` | USB Type-C R2.5, tables 4-20, 4-27, 4-28, 4-35, 4-36 and 3-5; USB 2.0 table 7-7 and 2 ECNs. Its steps: `usbc.md` beside this file | `rules/blocks/usbc.json` | GCT USB4105-GF-A, TI TPD2E2U06DCKR |

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

## Adding an IC to a block

1. Download the IC's datasheet under the workcenter's name into a folder
   outside every repository, and its SHA256 with `sha256sum`.
2. Add an entry to `ics` in `rules/blocks/<block>.json` with each number and
   its `where`: section, table and page. A number you cannot find in the
   datasheet is not entered; the block then refuses that IC on 1 line that
   names the missing key (`blocks.BUCK_NAMES` and `blocks.BUCK_NUMBERS` list
   what `buck` reads).
3. Add the datasheet to `rules/references/index.json`, and run
   `workcenter references rules`: it fails a source the index lacks.
4. Write the IC's facts into `library/facts/` (the `ratings` skill).
5. Run `python -m pytest tests/test_blocks.py`.
