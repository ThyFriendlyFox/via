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
| `blocks.mcu` | TI SLAA322D, equations 1, 3 and 5 and table 2; the datasheet SLASE35C, sections 5.3 and 5.13; SLAU278AH figure 2-3; SLAU272D table 1-4 | `rules/blocks/mcu.json` | MSP430FR5720IRGE |

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

## The microcontroller block

`blocks.mcu` adds an MSP430 with its 32768 Hz crystal and the crystal's 2
load capacitors, a bulk capacitor and 1 bypass capacitor on each supply
pin, VCORE's capacitor, the reset pull-up and capacitor, and the 14-pin
Spy-Bi-Wire header. `tests/boards/block_mcu.py` is a whole example.

1. Write the facts of each crystal you stock into `library/facts/` with
   `"kind": "crystal"`: `hertz`, `ohms_esr` (the datasheet's R1 or ESR at
   the most), `farads_load`, `farads_shunt` (C0) and `watts_drive`.
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
     12 pF. `its facts give no shunt capacitance`: add `farads_shunt`.
   - `CL1 = ... for ...: the pins and the board hold more than its load`:
     the stray is too large for the crystal's load (equation 3). Shorten
     the traces or take a crystal of a larger load.
   - `no stocked capacitor of ...` or `no stocked resistor of ...`: add the
     part the line names, with its facts.
   - `the supply reaches ...`: the supply is outside the IC's range.
   - `the board as built: ...`: the block's own check found a part missing
     or wrong after it placed them. Report it: it is a fault of the block.
4. The sums name each passed-over crystal, the ESR and SF of the one
   taken, the load capacitor and the CLoad it gives, the decoupling and its
   ratio, the reset network and the header. Copy them into the README.
   The drive level is printed as not judged: the documents state none.
5. Run `workcenter ratings . --strict`, then `workcenter design design.py
   --route` and `workcenter gates . --strict`.

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
