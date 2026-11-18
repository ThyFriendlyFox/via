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
