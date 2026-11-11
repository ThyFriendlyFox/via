# Gates report — Wyvern v0.1

The 4 gates on Wyvern v0.1, in their order: ERC on the schematic, DRC on the routed board at Sierra
Circuits' limits, every simulation deck at every corner, and the fabrication outputs. `workcenter
gates . --report docs/gates.md` runs them and rewrites the table below; the sections after it say
what each gate held the board to.

## Wyvern

<!-- workcenter gates wyvern -->
| Gate | Status | Summary |
|---|---|---|
| ERC | pass | 0 errors, 0 warnings |
| DRC | pass | 0 errors, 7 warnings (0 unconnected, 0 parity) |
| SIM | pass | 6 decks, 488 corner runs, 0 failures, 6 warnings |
| EXPORT | pass | 4/4 outputs, 26 gerber files |

GREEN with 13 warnings on 2026-11-11: `workcenter gates` with KiCad 10.0.8, ngspice 42.
<!-- /workcenter gates wyvern -->

## Simulation

Each deck stands in for its parts with their datasheets' worst numbers and runs at every corner of
the board's 1 % resistors, C1 and C2 at 50 % either way, a cable from 0.5 to 1.5 m, 32 Monte Carlo
draws and 0 and 40 C (`sim/corners.json`). The bounds in
`sim/<deck>.expect.json` come from the datasheets each deck names.

<!-- workcenter decks wyvern -->
| Deck | What it simulates | Bounds | Corner runs | Result |
|---|---|---|---|---|
| `sim/mcu_control.cir` | The Snapdragon resets the RP2350 and puts it in its bootloader through U6 and U7, 74LVC1G07 open-drain buffers on the SOM's 1.8 V. Each output low is 0.45 V at most sinking 4 mA at VCC 1.65 V (SN74LVC1G07 datasheet SCES296AG, VOL): 112.5 Ohm | 4 | 70 | 1 warning |
| `sim/som_i2c.cir` | The Snapdragon's I2C on the pins (SOM_I2C_SDA, SOM_I2C_SCL: QUP10 on JT2 pins 68 and 70, the header's SDA and SCL), pulled up by R16 and R17, 2.2k, to +1V8 (the SOM's VREG_S4A) | 3 | 42 | 1 warning |
| `sim/sys_rail_high.cir` | SOM_SYS at its highest: the TPS62130's reference at 822.4 mV (SLVSAG7F, 6.5) and 100 nA drawn into the FB pin (ILKG_FB), which R1 must carry too | 1 | 54 | 1 warning |
| `sim/sys_rail_low.cir` | SOM_SYS, the Snapdragon module's supply (SOM_SYS_PWR on JT2), from the TPS62130 (U2) set by R1 374k over R2 100k: VOUT = VFB x (1 + R1/R2) + IFB x R1 | 1 | 54 | 1 warning |
| `sim/vbus_pdn.cir` | VBUS, the 5 V input, as the TPS62130 (U2) draws from it: a USB-C charger behind its cable, and C1 and C2 at the buck's input | 1 | 70 | 1 warning |
| `sim/vbus_psm.cir` | The TPS62130 (U2) in power save, its pulses at the resonance of the USB cable with C1 and C2 (vbus_pdn.cir) | 1 | 198 | 1 warning |
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

7 warnings. 5 are `silk_edge_clearance`: the outlines of the 2 rows of 24 pins (J5, J6) on the back
silkscreen run along the board's long edges, as a Teensy's rows do. The holes sit 1.27 mm in from the
edge; the outline is KiCad's library footprint's, and the fab clips silkscreen at the edge.

2 are `via_dangling`: a via joined on 1 layer only, so a stub with nothing on its other end. The
VBUS via behind the receptacle's B row (`usb_pairs`): the router joined B4 and B9 to the rest of
VBUS on the top layer. QSPI_SD0's escape via under the resistor row (`core_rail`): the router took
SD0 from its pad another way. Neither carries a signal past its via; removing either changes the
route, and the route of every other design tried left a connection open.

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

FreeRouting 1.9.0 through `workcenter design design.py --route --passes 100 --timeout 3600 --rounds
2`: 789 segments and 51 vias of its own, on top of the copper `design.py` draws by hand (the USB
pairs in `usb_pairs`; the RP2350's supplies, its fan-out on 3 sides, the crystal's lines and the
module's sense pins in `core_rail`; the RGB lines). 0 unconnected.

It took about 40 routes, most of them run 3 at a time. The router left 3 to 17 connections open round the RP2350 until the crystal moved
to the back, each 100 nF faced its pin, and the pins were fanned out to vias by hand; then 5 mil
tracks with 4.3 mil of clearance (`track_width=0.127`, `clearance=0.11`, inside Sierra's 4 mil)
gave it the last room. The route is deterministic: 100 and 150 passes gave the same board, and the
same command in this folder gives the board that is committed. A route seeded from a previous one
lost connections its seed had, so none is used (workcenter MISTAKES.md M129, M130).
