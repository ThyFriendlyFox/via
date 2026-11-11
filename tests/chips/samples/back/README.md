# Reports of the back engines

Real output of OpenROAD `f12e2f47`, OpenSTA 2.3.1, Magic 8.3.465, Netgen
1.5.272 and KLayout 0.28.16, written on 2026-11-11. The judges in
`tools/chipback.py` read them in `tests/test_chipback.py`, with no engine.

Each sample is a run on a copy of the template project
(`workcenter chip init reg8 --top reg8`) with 1 thing changed. 4 paths are
rewritten in each file: the project's folder is `/work/reg8`, the process
kit is `/kit`, the workcenter is `/workcenter`, the folder of the chip
engines is `/chip`. Nothing else is changed, and no file is typed.

A gate takes a file only with the hash that the gate before it recorded.
So a sample that needs a changed netlist, SPEF or layout records the
changed file as that gate's. The tests do the same with `hand_on`.

## LAYOUT: OpenROAD's output of `tools/chipscripts/layout.tcl`

| Sample | What was run |
|---|---|
| `layout-pass.log` | the template: utilisation 0.5975, 0 violations |
| `layout-slow-clock.log` | a clock period of 0.5 ns: the build passes with `Unable to repair all setup violations` |
| `layout-does-not-fit.log` | a die of 30 by 30 um: the cells take 3.4 times the core, and the script stops |
| `layout-over-limit.log` | a die of 42 by 42 um: 0.6687 after the floorplan, over the limit 0.6, and the script stops |
| `layout-over-limit-after-build.log` | the same die with a limit of 0.7: 0.6687 before the clock tree, 0.7234 after it |
| `layout-router-violations.log` | the script with the router held to its first pass (`-droute_end_iter 1`): 8 violations left |
| `layout-grid-open.log` | the script without its lines for a core narrower than the stripe pitch: 1 supply net is open |
| `layout-open-pin.log` | 1 input of 1 cell on no net in the mapped netlist |
| `layout-unknown-cell.log` | 1 cell of the mapped netlist renamed to a cell the library does not have: OpenROAD warns, builds without it and exits 0 |
| `openroad-crash.log` | `check_power_grid` on the routed database with no liberty file read: a stack trace and exit 1 |

## STA: OpenSTA's output of `tools/chipscripts/sta.tcl` at 1 corner

The constraints change after the layout is built, so only STA runs again.

| Sample | What was run |
|---|---|
| `sta-pass.log`, `sta-pass.nets.txt` | the template at `nom_tt_025C_1v80`, and the nets the script names |
| `reg8.nom.spef` | the SPEF of that run: 38 nets |
| `sta-setup.log` | a clock period of 0.5 ns at `max_ss_n40C_1v60` |
| `sta-hold.log` | `set_clock_uncertainty -hold 1` at `min_ff_n40C_1v95` |
| `sta-load.log` | `set_load 5` on every output: slew and capacitance limits break |
| `sta-fanout.log` | `set_max_fanout 1`: 5 pins break it |
| `sta-open-constraints.log` | no delay on `d` and none on `q`: 3 warnings of `check_setup` |
| `sta-port-not-there.log` | a `set_false_path` from a port the design does not have: 2 warnings and exit 0 |
| `sta-spef-cut-short.log`, `reg8.cut-short.spef` | the SPEF cut at 9000 bytes: `syntax error`, exit 0, and 17 nets with no parasitics |
| `sta-ideal-clock.log` | the script without its `set_propagated_clock` line |
| `sta-skew.log`, `sta-skew.nets.txt` | a shift register in place of the register: each flop feeds the next, and the skew is 0.001 ns |
| `sta-no-flop-to-flop.log`, `sta-no-flop-to-flop.nets.txt` | a register with no path from a flop to a flop: `No launch/capture paths found.` |
| `sta-stopped.log` | a liberty file that is not there: 1 `Error:` line and exit 1 |

## DRC: Magic's output of `tools/chipscripts/drc.tcl`, and KLayout's report database

| Sample | What was run |
|---|---|
| `magic-drc-pass.log`, `magic-drc-pass.rpt`, `klayout-drc-pass.lyrdb` | the template's layout: 0 and 0 |
| `magic-drc-spacing.log`, `magic-drc-spacing.rpt`, `klayout-drc-spacing.lyrdb` | 2 squares of met3 added 0.1 um apart: 2 boxes in Magic, 1 item in KLayout |
| `magic-drc-cut-short.log`, `magic-drc-cut-short.rpt`, `klayout-drc-cut-short.log` | the layout file cut at 60000 bytes: Magic goes on and exits 0, KLayout exits 1 |
| `magic-drc-no-top-cell.log` | the script for a top cell the layout does not hold: `ERROR: cell other is empty` and exit 2 |

## ANTENNA: OpenROAD's output of `tools/chipscripts/antenna.tcl`, and its report

| Sample | What was run |
|---|---|
| `antenna-pass.log`, `antenna-pass.rpt` | the template's routed database: 0 nets, 0 pins |
| `antenna-violations.log`, `antenna-violations.rpt` | the template built with a copy of the technology LEF that allows each metal 4 times the gate's area, where the kit allows 400: 38 nets, 58 pins |

## LVS: Magic's extraction and Netgen's report

| Sample | What was run |
|---|---|
| `extract-pass.log` | the template's layout; Magic's feedback file is empty |
| `extract-overlap.log`, `extract-overlap.feedback.txt` | 1 bar of poly added across the cells: 69 errors and exit 0 |
| `lvs-pass.rpt` | the template: 5 comparisons, `Circuits match uniquely.` |
| `lvs-nets-swapped.rpt` | the D pins of 2 flops swapped in the netlist: `Netlists do not match.` |
| `lvs-wire-cut.rpt` | the longest met2 wire deleted from the layout: `Top level cell failed pin matching.` |
| `lvs-property-error.rpt` | 1 transistor of the extracted netlist made 139 times wider: the final result still reads `Circuits match uniquely.`, and the cell is named under it |

A new failure shape of an engine gets a sample here in the commit that
teaches a judge to read it.
