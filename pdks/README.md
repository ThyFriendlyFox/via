# Process tables

A process table holds everything the chip gates need to know about 1
process: `pdks/<name>.json`. No gate and no engine script names a file, a
cell or a layer of a process. A second process is a second table and no new
code.

| Table | Process | Installed by |
|---|---|---|
| `sky130A.json` | SkyWater SKY130, 130 nm, library `sky130_fd_sc_hd` | `sudo ./install.sh --chip` |

The kit itself is not in this repository. It is in the chip folder:
`<root>/chip/pdk/<name>/`, where `<root>` is `WORKCENTER_ROOT`
(`/opt/workcenters/ee` unless set), or `WORKCENTER_CHIP_TOOLS` names the
chip folder. Every path in a table starts at the kit's folder.

## Keys

`tools/chipflow.py` (`read_table`) reads a table and refuses a key it does
not know. Each block has a `source`: what the values were read from.

| Key | Holds |
|---|---|
| `name` | The table's name, the same as the file's. A project's `chip.json` names it as `pdk.name`. |
| `process` | 1 line for a reader: the foundry, the node, the build. |
| `version` | `file` and `pattern`: where the kit states its own version. `value`: the version this table was read from. `commit`: what `install.sh` pins. A project names the version it is proven on as `pdk.version`; a gate fails when the installed kit states another. |
| `magic` | The start file (`rc`) and the technology file (`tech`) Magic reads, and the Magic version the kit asks for (`needs`). |
| `klayout` | What `workcenter chip render` draws with: the layer properties file (`layer_properties`), and the map from a layer's name to its GDS layer and datatype (`layer_map`). |
| `libraries.<library>.corners` | Each library corner: its `liberty` file, its `process` (`slow`, `typical` or `fast`), its `volts` and its `celsius`. |
| `libraries.<library>.wires` | Each wire corner: its technology LEF (`techlef`) and its extraction rules (`rcx`). |
| `libraries.<library>.lef`, `gds`, `spice` | The cells' abstract views, layouts and transistor netlists. |
| `libraries.<library>.verilog` | The cell models for simulation (`files`) and the defines they are compiled with. |
| `libraries.<library>.cells` | The cells of each kind. `flop_with_reset`, `flop_without_reset`, `latch` and `clock_gate` are families: a cell's name without `prefix` and without its drive strength. `tie_high`, `tie_low` and `diode` are a cell and its pin. `tap`, `fill`, `decap`, `clock_root` and `clock_buffers` are cell names. `dont_use` names files of the kit, 1 cell name on a line: see "Cells the kit keeps out". |
| `libraries.<library>.supply` | The power and the ground net, and the cell pins that connect to each. |
| `libraries.<library>.floorplan` | What the layout build needs: the placement site, the tracks file, the tap distance, the pin, wire and routing layers, the supply grid, the placement density, the margin from the die's edge to the core. `wire_capacitance_ff_per_um` and `repair` are the numbers the build repairs with: see "Wires before the routing". |
| `drc` | Each rule deck: its `name`, its `engine` (`magic` or `klayout`), its `file`, its `origin` (`foundry` or `community`), and what it `cannot` judge. A KLayout deck's `variables` are passed as `-rd name=value`. |
| `lvs` | The engine and its setup file. |

## Corners

A project names 2 ranges in `chip.json`: the temperature it works in, and
its supply with a tolerance. It names no process corner and no wire corner.
The STA gate takes those from the table (`select_corners`):

1. The supply's range is the nominal less and plus the tolerance.
2. A slow library corner at or below the least supply decides setup. A fast
   one at or above the greatest decides hold.
3. For each of those 2, and for each end of the temperature range, the gate
   takes the corner at or beyond that end. Where the table has several, it
   takes the nearest in volts, then the nearest in temperature.
4. An end with no corner at or beyond it fails the gate: `no slow library
   corner covers 1.71 V or less at 125 C or hotter`. A corner is never
   dropped to make a range fit.
5. Each typical corner inside both ranges runs too.
6. Each library corner that is selected runs with every wire corner.

A worked case: 1.8 V within 5 % from 0 to 70 C on `sky130_fd_sc_hd`. The
supply's range is 1.71 to 1.89 V.

| Side | Cold end, 0 C | Hot end, 70 C |
|---|---|---|
| Slow, 1.71 V or less | `ss_n40C_1v60` | `ss_100C_1v60` |
| Fast, 1.89 V or more | `ff_n40C_1v95` | `ff_100C_1v95` |

`tt_025C_1v80` is inside both ranges and runs too. `ss_n40C_1v76` is nearer
to 1.71 V than 1.60 V is, and it is above 1.71 V, so it is not at or below
the least supply. 5 library corners with 3 wire corners are 15 timing runs:
`max_ss_100C_1v60`, `min_ff_n40C_1v95` and the rest.

The library's corners are measured points, not a grid: it has no slow
corner between 1.60 and 1.76 V. So a project is held to 1.60 V, which is
further out than its own 1.71 V. That errs to the safe side.

## Cells the kit keeps out

A kit can ship lists of cells that a flow must not choose. The table names
each list by its file in the kit, and the gates read the file: no cell name
of a list is copied into the table.

| Key | Who keeps the cells out | `sky130A` |
|---|---|---|
| `cells.dont_use.synthesis` | SYNTH: the mapping is offered none of them. The layout build places them: its repair changes a cell's drive strength when each net's load is known. | `no_synth.cells`, 185 cells: the weakest drive of each gate and flop, the clock buffers, the delay cells |
| `cells.dont_use.layout` | SYNTH and LAYOUT: no step places one. LAYOUT counts them in the layout and fails on 1. | `drc_exclude.cells`, 53 cells |

The kit's own flow file (`libs.tech/openlane/config.tcl`) makes the same
split: it names a "no synth" list for synthesis, and gives the library a
flow optimises with a DRC exclude list alone. A table that names a file in
both lists keeps its cells out of the layout build too.

SYNTH writes `build/chip/synth/mapping.lib`: the liberty file without the
cells of both lists. Yosys 0.33 has no flag that keeps a cell out of the
mapping, so the mapping reads that file. A cell of a list that the RTL
names itself fails SYNTH.

## Wires before the routing

The layout build repairs each slew and each capacitance limit before it
routes. For that it estimates a wire: its length times a resistance and a
capacitance for 1 um.

1. The resistance is the layer's own in the technology LEF
   (`floorplan.wire_rc_layers`).
2. The capacitance is `floorplan.wire_capacitance_ff_per_um`. It is
   measured on routed wires. The technology LEF leaves out the capacitance
   between a wire and the wires beside it: for `sky130A` its numbers give
   0.078 fF for 1 um of met2. The extraction of the routed acceptance
   processor finds 0.166 fF: 0.090 fF to ground and 0.076 fF to other nets.
3. `floorplan.repair` holds 2 margins in percent: `slew_margin_percent` and
   `capacitance_margin_percent`. The build repairs a slew and a capacitance
   to its limit less the margin. The margin is for what the routed wires
   add to the estimate: the STA gate judges them as they are.
4. `floorplan.repair.antenna_iterations` is the number of passes of the
   antenna repair. Each pass puts a diode at each gate that is still over
   its ratio. The repair works on the global route, and the ANTENNA gate
   judges the wires as routed: a gate can still be over there.

The build reads every library corner that the project's ranges select, and
repairs at the worst of them. The LAYOUT gate reads the capacitance back
from the engine and fails a build that estimated with another value.

Measure the capacitance for a new table in 4 steps:

1. Take a first value from the technology LEF: the layer's width times
   `CAPACITANCE CPERSQDIST`, plus 2 times `EDGECAPACITANCE`.
2. Build a fixture chip with that value.
3. Add the capacitance of every net in the nominal SPEF file.
4. Divide the sum by the routed length of those nets in the DEF file.

## A new process

1. Install its kit under `<root>/chip/pdk/<name>/`, with its version
   pinned in `install.sh`.
2. Write `pdks/<name>.json` from the kit's own files, each block with its
   `source`. Read each library corner's volts and temperature from its
   liberty file, not from its name.
3. Measure `floorplan.wire_capacitance_ff_per_um` on a routed fixture, as
   "Wires before the routing" says.
4. Run the fixture chips of `tests/chips/` on it.
