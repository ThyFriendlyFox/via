# Gates report — Wyvern v0.2

The 4 gates on Wyvern v0.2, in their order: ERC on the schematic, DRC on the routed board at Sierra
Circuits' limits, every simulation deck at every corner, and the fabrication outputs. `workcenter
gates . --report docs/gates.md` runs them and rewrites the table below; the sections after it say
what each gate held the board to.

## Wyvern

<!-- workcenter gates wyvern -->
| Gate | Status | Summary |
|---|---|---|
| ERC | pass | 0 errors, 0 warnings |
| DRC | pass | 0 errors, 9 warnings (0 unconnected, 0 parity) |
| SIM | pass | 7 decks, 397 corner runs, 0 failures, 7 warnings |
| EXPORT | pass | 4/4 outputs, 26 gerber files |

GREEN with 16 warnings on 2026-11-12: `workcenter gates` with KiCad 10.0.8, ngspice 42.
<!-- /workcenter gates wyvern -->

## Simulation

Each deck stands in for its parts with their datasheets' worst numbers and runs at every corner of
the board's 1 % resistors, C30, C31 and C42 at 50 % either way, a cable from 0.5 to 1.5 m, 32 Monte
Carlo draws and 0 and 40 C (`sim/corners.json`). The bounds in `sim/<deck>.expect.json` come from
the datasheets each deck names.

<!-- workcenter decks wyvern -->
| Deck | What it simulates | Bounds | Corner runs | Result |
|---|---|---|---|---|
| `sim/mcu_control.cir` | The Snapdragon resets the RP2350 and puts it in its bootloader through U7 and U8, 74LVC1G07 open-drain buffers on the module's 1.8 V. Each output low is 0.45 V at most sinking 4 mA at VCC 1.65 V (SN74LVC1G07 datasheet SCES296AG, VOL): 112.5 Ohm | 4 | 70 | 1 warning |
| `sim/som_i2c.cir` | The Snapdragon's I2C on the pins (SOM_I2C_SDA, SOM_I2C_SCL: APPS_I2C on the module's AA16 and AA15, the header's SDA and SCL), pulled up by R40 and R41, 2.2k, to +1V8 (the module's VCC_OUT_IO) | 3 | 42 | 1 warning |
| `sim/sys_rail_high.cir` | +5V at its highest: VREF at its 1.212 V maximum (SLVSH28A, 6.5), and the FB pin sinking its most: 100 nA of leakage (IFB_LKG) and 0.3 uA of the cable-droop current (IFB_CDC; ISP and ISN are tied together, so the CDC current is at its 0 mV figure), which R30 must carry too | 1 | 54 | 1 warning |
| `sim/sys_rail_low.cir` | +5V, the module's supply, at its lowest | 1 | 54 | 1 warning |
| `sim/vbus_pdn.cir` | VBUS, the converter's input, as U3 draws from it: a USB-C charger behind its cable, C30 and C31 at U3's input, and the damper C42 with R45 | 1 | 69 | 1 warning |
| `sim/vbus_uvlo_high.cir` | Where U3 starts, at the latest: as vbus_uvlo_low.cir, with VUVLO at its 1.26 V maximum (SLVSH28A, 6.5): the highest VBUS it may need before it starts | 1 | 54 | 1 warning |
| `sim/vbus_uvlo_low.cir` | Where U3 starts, at the earliest | 1 | 54 | 1 warning |
<!-- /workcenter decks wyvern -->

- `sys_rail_low`, `sys_rail_high`: the TPS552892's feedback divider, R30 over R31, holds +5V inside
  the module's 4.8 to 5.2 V (VOSM6490 datasheet) at the reference's and the FB pin's limits
  (SLVSH28A, 6.5): 4.86 to 5.17 V.
- `vbus_uvlo_low`, `vbus_uvlo_high`: R34 over R35 on EN/UVLO start the converter between 3.51 and
  3.78 V of VBUS, inside the 3.0 to 4.0 V the decks hold: above the converter's own 3.0 V floor
  (SLVSH28A, 6.3), below the 4.0 V the board must start from (a USB-C source's 4.75 V less the drop
  of a cable carrying 3 A).
- `vbus_pdn`: the USB input's peak impedance with a USB-C cable of 0.5 to 1.5 m, C30, C31 and the
  damper (C42 with R45), stays under the converter's input resistance at its most negative, VIN /
  3 A at 4.0 V (1.33 ohm), and gives the frequency plan its resonance and Q.
- `som_i2c`: the Snapdragon's I2C on the pins rises in 300 ns or less with 100 pF on it, and its low
  level and sink current stay inside UM10204's Fast-mode limits for a bus under 2 V.
- `mcu_control`: the Snapdragon's buffers (and BOOT) pull the RP2350's RUN and QSPI_SS below its
  0.8 V input low (RP2350 datasheet, Table 1683) against its pull-ups at their strongest.

Each deck warns that no measure moves with temperature: nothing in them has a temperature
coefficient, which is true of the circuits they model. The buck-boost's loop (R32, C41) is not
simulated: TI publishes no model of the TPS552892.

## Schematics

One sheet (A0), drawn with wires in blocks the way the signal flows (`lay_out_schematic` in
`design.py`): each IC or connector with its own parts, a label for a net that joins 2 blocks. The
module's 662 pins are drawn as 13 banks, one for each interface, named from the OSM standard and,
for the 64 the board uses, from Vantron's datasheet (`symbols/make_symbols.py`, `osm_l_pins.csv`).

## DRC warnings

9 warnings. 5 are `silk_edge_clearance`: the outlines of the 2 rows of 30 pins (J2, J3) on the back
silkscreen run along the board's long edges, as a Teensy's rows do. The holes sit 1.27 mm in from
the edge; the outline is KiCad's library footprint's, and the fab clips silkscreen at the edge.

4 are `via_dangling`: a via joined on 1 layer only, a stub with nothing on its other end.

- SOM_VBUS_DET and SOM_SPI_CS, under the module: `module_fanout` gives every module pad the board
  uses a via, and the router took these 2 signals from their pads on the top layer instead.
- VBUS behind the receptacle's B row (`usb_lane`): the router joined B4 and B9 to the rest of VBUS
  on the top layer, as on v0.1.
- GP25's escape via beside the RP2350 (`core_rail`): the router took GP25 from its pad another way.

None carries a signal past its via. Removing them changes the route.

## Pull check

`check_pulls` is on (workcenter PROCESSES.md P16 step 5). Every control input has a resistor to a
rail or a driver, or is named in `defined_nets` with what holds it: the module's power, reset and
recovery keys and its SD command and card-detect lines (each pulled up on the module, PU 10K in
Vantron's pin table); the RP2350's own pull-ups on RUN, QSPI_SS, SWCLK and SWDIO; the converter's
EN/UVLO divider from VBUS; the HD3SS3220's VBUS_DET through R36; the Snapdragon's SD clock; and each
GPIO on the pins (firmware or Linux sets it).

## Fabrication outputs

`workcenter export .` writes `build/fab/`: the Gerbers of all 6 copper layers, masks, pastes,
silkscreens and the outline; the drill files; the positions; the BOM. The board file carries the 6
layer, 1.6 mm stackup (`kicadgen`'s 7628 prepregs, 35 um outer and 15 um inner copper; black masks,
white legends and ENIG, from `WyvernDesign` in `design.py`) and Sierra Circuits' Web PCB limits as
`wyvern.kicad_dru` (`rules/sierra-circuits-web.kicad_dru`): 4 mil track and gap, 6 mil hole and
ring, 13 mil from a hole to inner-layer copper. The vias under the module are tented: an open via
beside an LGA pad draws its solder away.

## Routing

FreeRouting 1.9.0 through `workcenter design design.py --route --passes 100 --timeout 3600 --rounds
2 --seed wyvern.kicad_pcb`: 1007 segments and 76 vias of its own, on top of the copper `design.py`
draws by hand (the buck-boost's power pads in `power_stage`; the SuperSpeed lane, the receptacle's
B row and the mux's control vias in `usb_lane`; v0.1's RP2350 copper, turned, in `core_rail`; the
module's 184 vias in `module_fanout`; the 5 V spine in `five_volt_spine`). 0 unconnected, 0 islands.

It took 7 routes. The first 2 left the 5 V plane under the module (In3) in 3 pieces: the router
crossed its narrow strip. A spine of 0.38 mm copper along the module's middle pad line, which no
fan-out via touches, held it together; the next route left only the converter's output off the
plane, and 3 vias closed it. The same command without a seed then left SD_VDD's last link open
(C23 to J4); seeded with the route before it, the router kept all 1001 of its seed's tracks and
closed it. FreeRouting is deterministic, so the committed board is what that command writes from
the committed board.
