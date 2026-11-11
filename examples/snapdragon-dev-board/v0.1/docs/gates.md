# Gates report — Wyvern v0.1

The 4 gates on Wyvern v0.1, in their order: ERC on the schematic, DRC on the routed board at Sierra
Circuits' limits, every simulation deck at every corner, and the fabrication outputs. `workcenter
gates . --report docs/gates.md` runs them and rewrites the table below; the sections after it say
what each gate held the board to.

## Wyvern

<!-- workcenter gates wyvern -->
| Gate | Status | Summary |
|---|---|---|
| ERC | | |
| DRC | | |
| SIM | | |
| EXPORT | | |
<!-- /workcenter gates wyvern -->

## Simulation

Each deck stands in for its parts with their datasheets' worst numbers and runs at every corner of
the board's 1 % resistors, C1 and C2 at 50 % either way, a cable from 0.5 to 1.5 m, 32 Monte Carlo
draws and 0 and 40 C (`sim/corners.json`). The bounds in
`sim/<deck>.expect.json` come from the datasheets each deck names.

<!-- workcenter decks wyvern -->
| Deck | Bounds | Failures | Warnings |
|---|---|---|---|
| | | | |
<!-- /workcenter decks wyvern -->

- `sys_rail_low`, `sys_rail_high`: the TPS62130's feedback divider holds SOM_SYS inside the
  module's 3.45 to 4.75 V (PDS-0007 Rev C, Table 7) at the reference's and the FB pin's limits
  (SLVSAG7F, 6.5).
- `som_i2c`: the Snapdragon's I2C on the pins rises in 300 ns or less with 100 pF on it, and its low
  level and sink current stay inside UM10204's Fast-mode limits for a bus under 2 V.
- `mcu_control`: the Snapdragon's buffers (and BOOT) pull the RP2350's RUN and QSPI_SS below its
  0.8 V input low (RP2350 datasheet, Table 1683) against its pull-ups at their strongest.
- `vbus_pdn`: the 5 V input's peak impedance with a USB-C cable of 0.5 to 1.5 m stays under the
  buck's negative input resistance at the module's 8.7 W boot peak from 4.75 V (2.29 ohm), and gives
  the frequency plan its resonance and Q.
- `vbus_psm`: the buck's power-save pulses (SLVSAG7F 8.4.2) at that resonance move the input 50 mV
  or less; the gate also steps the cable against C1 and C2 between their ends.

Each deck warns that no measure moves with temperature: nothing in them has a temperature
coefficient, which is true of the circuits they model.

## Schematics

One sheet (A1), drawn with wires in blocks the way the signal flows (`lay_out_schematic` in
`design.py`): each IC or connector with its own parts, a label for a net that joins 2 blocks. The
SOM's 3 connectors are drawn with its own pin names (`symbols/make_symbols.py`).

## DRC warnings

<!-- drcwarn -->

## Pull check

`check_pulls` is on (workcenter PROCESSES.md P16 step 5). Every control input has a resistor to a
rail or a driver, or is named in `defined_nets` with what holds it: the RP2350's own pull-ups on RUN,
QSPI_SS, SWCLK and SWDIO (its datasheet's pin list), the PMIC's power key and RESIN inputs (the
SOM's datasheet has them grounded by a button), the TPS62130's soft-start current source, the
Snapdragon's SD clock, and each GPIO on the pins (firmware sets it).

## Fabrication outputs

`workcenter export .` writes `build/fab/`: the Gerbers of all 6 copper layers, masks, pastes,
silkscreens and the outline; the drill files; the positions; the BOM. The board file carries the 6
layer, 1.6 mm stackup (`kicadgen`'s 7628 prepregs, 35 um outer and 15 um inner copper) and Sierra
Circuits' Web PCB limits as `wyvern.kicad_dru` (`rules/sierra-circuits-web.kicad_dru`): 4 mil track
and gap, 6 mil hole and ring, 13 mil from a hole to inner-layer copper.

## Routing

<!-- routing -->
