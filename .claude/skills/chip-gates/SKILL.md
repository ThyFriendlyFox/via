---
name: Chip Gates
description: Runs the 10 chip gates (lint, simulation, synthesis, layout, timing, netlist simulation, DRC, antenna, LVS, export) on a chip project in order, then drives the fix loop until the chip is GREEN and its GDSII layout is handed out.
---

# Chip Gates

A chip is done when `workcenter chip gates <project> --strict` prints
`GREEN`. This skill runs the gates, reads the reports, and corrects the
design until they pass. The `chip-design` skill writes the project.

`workcenter next <project>` names the one next step at any point: the
command, the reason, the fix for the first failure or warning, and when
the step is done. Run it whenever the next step is not plain.

## When

- A chip project must be called done.
- A change touched the RTL, a bench, the constraints or `chip.json`.
- A human asks whether a chip passes, or asks for its GDS.

## Inputs

1. The project's folder: `chip.json`, `constraints.sdc`, `rtl/`, `tb/`.
2. `workcenter doctor` prints a version beside each chip engine and
   beside `pdk sky130A`. A line without one: `sudo ./install.sh --chip`.

## Steps

1. Run `workcenter chip gates <project>`. The 10 gates run in order and
   stop at the first that does not pass. Each prints 1 line, with its
   failures and warnings under it. The last line is the verdict:

   | Last line | Meaning | Exit code |
   |---|---|---|
   | `GREEN: <name>` | All 10 gates passed, with no warning. | 0 |
   | `GREEN with N warnings: <name>` | All 10 passed and named N things they did not fail on. Not done. | 0 |
   | `RED: <name>` | A gate failed. | 1 |
   | `SKIPPED (<GATE>: <reason>): <name>` | A gate did not run. Never GREEN. | 2 |

2. For a red gate, read its first failure line. Most lines say what to
   do. The section of the gate below says where its report is.
3. Correct the design, not the limit. A limit of `chip.json`, a bound of
   an expect file or a line of `constraints.sdc` is never changed to
   pass. An answer in `chip.json` (`answers`, `benches.<bench>.rtl_only`)
   needs its reason and its evidence.
4. Run `workcenter chip gates <project>` again: all 10 gates, every time.
   A gate run alone (`workcenter chip sta <project>`) is for a quick
   look; EXPORT hands out a layout only when all 9 gates before it
   passed on the files as they are.
5. On `GREEN with N warnings`, correct each warning, then run with
   `--strict`: a warning fails its gate there.
6. Done: the last line is `GREEN: <name>` with `--strict`. Report that
   line, the scope line above it, and the path of
   `<project>/build/chip/tapeout/manifest.json`.

`--out <dir>` writes elsewhere than `<project>/build`. `--jobs N` sets
how many engine runs go at once; the layout is the same at any count.
`workcenter --json chip gates <project>` prints each gate's record.

## The 10 gates

| Gate | Engine | What it holds |
|---|---|---|
| LINT | Verilator | The RTL reads the same to a simulator and to a synthesizer. `chip.json` and the constraints are sound, and every port has a delay. |
| SIM | Icarus Verilog | Every bench passes on the RTL, and every change of `rtl/mutations.json` fails a bench. |
| SYNTH | Yosys | The RTL maps onto the library's cells: no latch, no loop, a reset on every flop. |
| LAYOUT | OpenROAD, Magic | The cells are placed and routed with no violation, every supply pin on its grid, within the utilisation limit. Writes the GDS. |
| STA | OpenSTA | Setup, hold, slew, capacitance and skew hold at every corner the project's ranges select, with the routed wires. |
| GLSIM | Icarus Verilog | The benches pass on the routed netlist with the library's cell models. |
| DRC | Magic, KLayout | The layout breaks no rule of 2 decks. |
| ANTENNA | OpenROAD | No wire collects more charge during etch than its gates take. |
| LVS | Magic, Netgen | The layout is the netlist, device by device. |
| EXPORT | none | Each of the 9 gates passed on the files as they are now. Copies the layout into `build/chip/tapeout/` with `manifest.json`. |

Every gate writes into `<project>/build/chip/<gate>/`.

## LINT

Report: `build/chip/lint/verilator.log`.

| Line | Fix |
|---|---|
| `LATCH: ... Latch inferred for signal` | Assign the signal in every branch of its block: a default at the top, or a `default:` in the `case`. |
| `WIDTHTRUNC`, `SELRANGE` | Make the 2 sides the same width; name the bits you keep. |
| `UNDRIVEN`, `MULTIDRIVEN` | Give the net exactly 1 driver. |
| `CASEINCOMPLETE` | Add the missing cases or a `default:`. |
| `COMBDLY`, `BLKANDNBLK` | `<=` in a clocked block, `=` in a combinational one, never both for 1 signal. |
| `constraints.sdc: line N: a second clock` | Use 1 clock, and an enable where the second clock was. |
| `constraints.sdc: input X has no set_input_delay` | Add the delay for the port, with its source. |
| `rtl/x.v:N: lint_off LATCH turns off a class this gate fails on` | Remove the comment and change the code. |
| `chip.json: ...` | Correct `chip.json` as the line says: `chip-design`, "chip.json". |

## SIM

Report: `build/chip/sim/<bench>/run.log` and `compile.log`.

| Line | Fix |
|---|---|
| `tb_x: errors=N not in [None, 0]` | Read the first `mismatch` line of `run.log`. Correct the RTL, or the bench when its expected value is wrong by the spec. |
| `tb_x: x_outputs=N not in [None, 0]` | An output is unknown after the reset. Give every flop it depends on a reset. |
| `tb_x: does not compile: ...` | Correct the bench at the file and line named. Name its module as its file. |
| `tb_x: does not reach $finish` | End the bench with `$finish` after its last check. |
| `tb_x: does not print errors` | Print `errors`, `checks` and `x_outputs` as `name = value`. |
| `no rtl/mutations.json` (warning) | Write the list: `chip-design`, "The list of changes". |
| `the benches pass with the change X in F` | Add a check to a bench that fails on that change. Do not remove the change. |
| `rtl/mutations.json: the change X does not compile` | Correct its `new` text. |
| `rtl/mutations.json: X: F holds the old text N times` | Make `old` longer, until it stands in the file 1 time. |

## SYNTH

Report: `build/chip/synth/yosys.log`; the netlist is `<top>.v` beside it.

| Line | Fix |
|---|---|
| `N flops have no reset: a, b ...` | Give each a reset. For a flop with none on purpose, add an answer to `chip.json`'s `answers.flops_without_reset` with `match`, `why` and `evidence`. |
| `N latch bits: ...` | Assign the signal in every branch. |
| `check: found logic loop` | Break the loop with a flop. |
| `check: multiple conflicting drivers` | Give the net 1 driver. |
| `the netlist ties inputs to 1'bx` | A net has no driver: drive it, or remove what reads it. |
| `the netlist holds <cell>: the process kit lists it as not to use` | Do not name that cell in the RTL. |

The line of a pass can end `the mapping removed N flops that nothing
reads`. That is no failure. `workcenter --json chip synth <project>`
names each under `flops_removed_by_mapping`: remove the register from the
RTL, or read it.

## LAYOUT

Report: `build/chip/layout/openroad.log`.

| Line | Fix |
|---|---|
| `utilisation U is over the limit L of chip.json` | Name a larger die in `floorplan.die_um`, or cut logic. Do not raise the limit. |
| `the cells take N times the core's area` | The same: a larger die, or less logic. |
| `the router left N violations` | Give the design more room: a larger die. |
| `N pins of cells are on no net` | An input floats: drive it in the RTL. |
| `the supply grid leaves parts of VPWR unconnected` | Name a wider die: a stripe of each supply net must cross the core. |
| `chip.json names no floorplan.die_um and no limits.utilization` | Name 1 of the 2, with its source. |

The build repairs slow signals, heavy nets and antennas itself. A warning
`[WARNING RSZ-0062] Unable to repair all setup violations.` says that the
clock period is too short for the logic: STA names the paths.

## STA

Report: `build/chip/sta/<corner>/sta.log`, 1 folder for each corner.

| Line | Fix |
|---|---|
| `<corner>: setup slack -S ns, from A to B` | The path from A to B is too slow at that corner. Add a register stage, or do less between the 2 flops. The period stays. |
| `<corner>: hold slack -S ns, from A to B` | The build repairs hold itself. Report the line: its repair did not reach the path. |
| `<corner>: N pins break a limit of the library` | The build's repair left a slow signal or a heavy net. Name a larger die. When the line stays, report it. |
| `<corner>: clock skew S ns is over the limit` | The clock tree is the build's own. Report the line with the limit's source. |
| `chip.json names no limits.clock_skew_ns` (warning) | Name the limit with its source. |

A slow corner (`ss`, low supply) decides setup; a fast corner (`ff`, high
supply) decides hold. Every corner must pass.

## GLSIM

Report: `build/chip/glsim/<bench>/run.log`.

| Line | Fix |
|---|---|
| `tb_x: x_outputs=N not in [None, 0]` | A flop starts unknown on the netlist. An `initial` block does not exist in silicon: use the reset. |
| `tb_x: errors=N not in [None, 0]` | The netlist differs from the RTL: a race in the bench (change inputs on the falling edge), or RTL a simulator reads another way than Yosys. |
| `tb_x: checks=N on the netlist and M on the RTL` | The bench took another path: make it wait for cycles, not for values inside the design. |
| `every bench is marked rtl_only` | Write 1 bench that reads the top module's ports only. |

## DRC

Reports: `build/chip/drc/magic.rpt` and `build/chip/drc/klayout-mr.lyrdb`.

`<deck>: N items break a rule: <rules>`: the layout is made of the kit's
cells and the router's wires, so a broken rule is a fault of the build
and not of the RTL. Build again on a larger die. When the count stays,
report the line with the rule's name: it is a defect of the workcenter.

## ANTENNA

Report: `build/chip/antenna/antenna.rpt`.

`N nets and M pins collect more charge than their gates take`: the build
puts diodes in before the routing, and a long wire can still be over
after it. Name a larger die, so that the placer has room for the diodes,
or register a signal that crosses the whole die.

## LVS

Reports: `build/chip/lvs/lvs.rpt` and `extract.log`.

`the layout is not the netlist`: no change of the RTL causes this. Run
all the gates again. When it stays, report the line: it is a defect of
the workcenter.

## EXPORT

| Line | Fix |
|---|---|
| `<file> changed after <GATE> passed` | A file is not the one a gate passed. Run all the gates again. |
| `<file> was added after <GATE> passed` | The same: run all the gates again. |
| `SKIPPED (EXPORT: <GATE> did not pass ...)` | That gate is red or has not run: run all the gates. |
| `STA passed at N of the M corners` | STA ran with `--corner`. Run all the gates with no `--corner`. |

`build/chip/tapeout/` holds what leaves: the GDS, the DEF, 2 netlists, 3
SPEF files, 1 SDF file for each corner, the reports of the judging gates
and `manifest.json` with each file's SHA256.

## A gate that did not run

`SKIPPED (<GATE>: <reason>)` is never a pass. The reason says what the
gate waits for:

| Reason | Do |
|---|---|
| `... is not installed` | `sudo ./install.sh --chip`, then `workcenter doctor`. |
| `the process kit ... is not installed` | The same. |
| `tb/ holds no bench` | Write a bench: `chip-design`, "A bench". |
| `no file matches chip.json's rtl patterns` | Write the RTL: `chip-design`, "The RTL". |
| `<GATE> has not run`, `<file> is not there` | A gate was run alone before the gates it needs. Run `workcenter chip gates <project>`. |

## What GREEN says

The line above the verdict is the scope of the run:

```
scope: open engines, sky130A 1.0.470-0-g6d4d117, decks: magic (community),
klayout-mr (community), corners: ...; no foundry deck ran; no shuttle's
limits were checked
```

GREEN says that the open engines found no fault in these files, with
these decks, at these corners. It does not say that a foundry accepts the
layout, or that the silicon works. A shuttle or a foundry runs its own
deck and has its own limits (a die size, a pad frame, a density). Say so
whenever you report a GREEN chip.

## Done when

- `workcenter chip gates <project> --strict` ends with `GREEN: <name>`.
- `workcenter next <project>` answers `Nothing: all 10 chip gates are
  GREEN with no warning.`
