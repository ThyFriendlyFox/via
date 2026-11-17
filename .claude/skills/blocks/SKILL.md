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
| `blocks.buck` | TI SLVA477C, equations 1, 2, 3, 4 and 11, sections 3 and 7 | `rules/blocks/buck.json` | TLV62569DBVR |

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
     - `no stocked inductor holds the peak of X A`: add an inductor of the
       datasheet's value whose facts saturate above X A to the stock, or lower
       the load.
     - `IMAXOUT = ... under the load`: the IC cannot give the load (equation 3).
       Take another IC.
     - `the load of X A is over ...` or `the input reaches X V`: the IC's
       datasheet does not allow it. Take another IC or change the spec.
     - `no stocked resistor of ...`, `no stocked capacitor ...`: add the part
       the line names to the stock, with its facts.
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
