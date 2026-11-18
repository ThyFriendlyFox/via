---
name: Charger block
description: Adds a linear charger for 1 lithium cell to a design file in 1 call - TI's BQ21040 with a BQ29700 protector and its 2 CSD17313Q2 transistors - from the input range, the charge current, the cell's limits, the system's load and the ambient; every value from the 2 datasheets with its page, and a charge current the IC or its dissipation does not allow refused on 1 line with the equation.
---

# Charger block

`blocks.charger` (in `tools/blocks_charger.py`) puts on the sheet and on the
board a BQ21040 linear charger, its programming resistor, its TS resistor and
its 2 capacitors, and a BQ29700 protector with its filter, its sense resistor
and its 2 transistors. It checks what it builds before it returns. The `blocks`
skill says how blocks work; this skill is the charger's own steps.

| Value | From | Page |
|---|---|---|
| RISET | `RISET = KISET / IOUT`, KISET's typical value of the current's row | SLUSCE2D equation 1, page 13; KISET, page 5 |
| The charge current's span | KISET's MIN and MAX and the resistor's tolerance | page 5 |
| The charger's power and junction | `P = (VIN - VBAT) x IOUT` at the greatest input, the greatest current and the least cell voltage in fast charge; `TJ = TA + RthetaJA x P` at the greatest ambient, held to the least of 125 C and the rating pack's limit (110 C in `ecss-q-st-30-11c-rev2`), the limit the SIM gate holds | equation 8, page 23; RthetaJA, page 4; TJ, page 4 |
| The ambient | -40 C to 85 C for the BQ29700; 0 C at the least for the BQ21040's junction | SLUSBU9I 6.3, page 5; SLUSCE2D 7.3, page 4 |
| C1, C2 | 1 uF to 10 uF, effective at the voltage each sees | pin table, page 3; figure 10, page 17 |
| R2 (TS) | 10 kohm: no thermistor | section 9.2.2.1.3, page 18 |
| Overcharge, overdischarge | the BQ29700's thresholds and tolerances against the cell's limits and the charger's regulation | SLUSBU9I table 4, page 3; section 6.6, page 6 |
| Q1, Q2 | 2 x RDS(on) MAX x the load under VOCD's least; x the charge current under OCC's least | SLUSBU9I section 9.2.2, pages 19 and 20; SLPS260E page 3 |
| R3, C3, R4 | 330 ohm, 0.1 uF, 2.2 kohm | SLUSBU9I figure 9-1, page 19; sections 5.1.1 and 5.1.3, page 4 |

## Steps

1. Write the facts of each part you stock into `library/facts/`, as the
   `ratings` skill says. `tests/boards/library/facts/` holds the BQ21040's,
   the BQ29700's and the CSD17313Q2's.
2. In `design.py`, state the cell from its datasheet and call the block:

   ```python
   import blocks

   cell = blocks.Cell(volts=(2.5, 4.3), charge_amps=0.5, discharge_amps=3.0,
                      source="the cell's datasheet, its document, clause and page")
   block = blocks.charger(d, ic="BQ21040DBVR", protector="BQ29700DSER",
                          vin=(4.75, 5.25), amps=0.15, cell=cell, load=1.0,
                          ambient=(0.0, 40.0), pack="ecss-q-st-30-11c-rev2",
                          nets={"in": "+5V", "bat": "+BATT", "gnd": "GND",
                                "cell": "-BATT", "chg": "CHG"},
                          stock=STOCK, facts=HERE / "library" / "facts",
                          sch_at=(50.8, 63.5), pcb_at=(108.0, 104.0))
   ```

   `gnd` is the system's ground, Pack-; `cell` is the cell's negative, behind
   the 2 transistors. Put a PWR_FLAG on the cell's negative
   (`d.power_nets["-BATT"] = "-BATT"` and `"-BATT"` in `d.flagged_nets`) and
   none on `bat`: the charger's OUT drives it. Write `block.ratings`,
   `block.rows` and `block.files` as the `blocks` skill shows.
   `tests/boards/block_charger.py` is a whole example.
3. Run `workcenter design design.py`. What it prints:
   - `charger U1: P = ... TJ = ... over 110 C: at X C the charge current reaches
     Y A at the most`: the charger would run hot. Ask Y A or less, lower the
     greatest input or the ambient, or take a charger in a package with a
     lower RthetaJA. The limit is the least of the datasheet's 125 C and the
     pack's; the line's source names both.
   - `` `vin`'s first number ... is above its second``, `` `nets` lacks ...``,
     `a load of X is asked`: the call is wrong. Spans go least first.
   - `the ambient reaches X C, outside BQ29700DSER's ...` or `... under
     BQ21040DBVR's least, 0 C`: the parts do not run there.
   - `charger U1: a charge current of X is outside ...`, `RISET = ... outside
     ...`, `the input reaches X V`: the datasheet does not allow the spec.
   - `RISET of ... sets ..., and X is asked`: the stock has no resistor near
     the one the line names. Add it, 1 %.
   - `the charge current reaches X, over the cell's Y`: the greatest current,
     KISET's MAX over the resistor's least, is over the cell's limit. Ask less.
   - `charger U2: the overcharge threshold reaches ...` or `the overdischarge
     threshold reaches ...`: the BQ29700 does not fit the cell. Take another
     BQ297xx whose thresholds do: add it to `rules/blocks/charger.json` with
     its row of table 4.
   - `no stocked transistor holds the load ...`: the line says why each was
     passed over. Add a transistor of lower RDS(on), with its facts and its
     `rds_on` in `rules/blocks/charger.json`, or lower the load.
   - `no stocked capacitor ...`, `no stocked resistor ...`: add the part the
     line names, with its facts.
   - `design ... green`: the parts, `ratings.json`, `parts.csv` and `sim/` are
     written.
4. Open `sim/charger.cir`. Its lines after `* The sums:` are `block.sums`: 1
   line per value with its equation and page. The lines that start
   `not judged:` are what the block cannot judge. The fixture has 4: the
   overdischarge threshold's tolerance (stated at 25 C only), the 2
   transistors' drop at heat and at a gate under 3 V, the trip under the
   typical on-resistance, and the value C3 keeps. A fifth comes when the
   ambient leaves 0 C to 60 C: the overcharge threshold's tolerance. Copy them
   into the version's README with the sums.
5. Run `workcenter ratings .`. It holds each pin, each capacitor and each
   transistor to its rating, and the 3 capacitors the 2 ICs need. The block
   writes its `not judged` items into `ratings.json` under `not_judged`, and
   the command prints each as `not judged`: the last line is
   `RATINGS HELD, 4 NOT JUDGED`, exit 0. `--strict` fails on them: no
   number in the datasheets judges them, so the block cannot close them. Name
   each in the version's README.
6. Run `workcenter design design.py --route`, then `workcenter gates .`. The
   SIM gate runs `sim/charger.cir` at each corner of `sim/corners.json`: the
   charge current against the cell's, the charger's power against the power
   that keeps the block's limit, and, through `sim/thermal.json`, the junction
   against the rating pack's derated limit.
