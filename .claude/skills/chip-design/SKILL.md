---
name: Chip Design
description: Writes a chip project (RTL, benches, timing constraints, chip.json and the list of changes the benches must catch) for an open process, ready for the 10 chip gates that take it to a GDSII mask layout.
---

# Chip Design

A chip project is a folder: RTL, benches, timing constraints and
`chip.json`. `workcenter chip gates <project>` takes it through 10 gates
to a GDSII mask layout. This skill writes the project. The `chip-gates`
skill runs the gates and corrects what they name.

`workcenter next <project>` names the one next step at any point: what to
do, the command, why, what to read, and when the step is done. Run it
after every step.

## When

- A design must become a layout: a block, a peripheral, a small processor.
- A human asks for a chip, an ASIC, a mask layout or a GDS.

## What this flow takes

- 1 clock. Every flop takes its rising edge.
- Gates and flops of 1 cell library on 1 open process: `sky130_fd_sc_hd`
  on `sky130A`, 130 nm. `pdks/` holds the process table.
- No memory macro, no analog block, no pad ring.

GREEN says that the open engines found no fault in the files. It does not
say that a foundry accepts the layout or that the silicon works: no
foundry deck runs here. Every run prints that scope on its line before
the last.

## Inputs

1. `workcenter doctor` prints a version beside `verilator`, `iverilog`,
   `vvp`, `yosys`, `klayout`, `openroad`, `opensta`, `magic`, `netgen`
   and `pdk sky130A`. A line without one: run `sudo ./install.sh --chip`.
2. The spec: what the chip does, its pins, its clock, and where each
   number comes from.

## Steps

1. Start the project: `workcenter chip init <dir> --top <module>`. It
   writes `chip.json`, `constraints.sdc`, `rtl/<module>.v`,
   `tb/tb_<module>.v` and `README.md`. It never writes over a file. The
   RTL, the bench and the constraints it writes are an example, an 8-bit
   register with its bench and its ports' delays: replace all 3 with the
   design's. `workcenter next` names a file that is still the example.
   The project's path holds no white space: Yosys ends a path at a space.
2. Fill `chip.json`: see "chip.json".
3. Write the RTL in `rtl/`: see "The RTL".
4. Write 1 bench in `tb/` for each thing the spec promises: see "A bench".
5. Write the constraints: see "The constraints".
6. List the changes of the RTL that the benches must catch: see "The
   list of changes".
7. Run `workcenter chip gates <dir>`, and go on with the `chip-gates`
   skill until the last line is `GREEN`.
8. Fill `README.md`: the spec with its sources, the pins, how to test the
   chip through its pins, each decision with its reason.

A limit, a bound or a constraint is never changed to pass a gate: the
design changes.

## chip.json

Every number carries a `source`: where it comes from. Text that still
starts with `fill:` is a problem, and no gate runs on a file with one.

| Key | What it holds |
|---|---|
| `top` | The top module's name. |
| `rtl` | File patterns of the RTL. Left out: `rtl/*.v` and `rtl/*.sv`. |
| `constraints` | The constraints file. Left out: `constraints.sdc`. |
| `pdk` | `name`, `library` and `version` of the process kit, and the `source` of the version. The version is what `workcenter doctor` prints on its `pdk` line. |
| `corners.temperature` | `values`: the least and the greatest temperature in C, with their `source`. |
| `corners.supply` | `nominal` in volts and `tolerance` as a fraction (0.05 is 5 %), with their `source`. |
| `floorplan.die_um` | The die's width and height in um. Left out: the build chooses a square die from the utilisation limit. |
| `limits.utilization` | `max`: the part of the core the cells may take (0.6 is 60 %). "The 2 limits" says where the number comes from. |
| `limits.clock_skew_ns` | `max`: the clock skew STA holds, in ns. Left out: STA warns that it holds none. "The 2 limits" says where the number comes from. |
| `benches.<bench>.rtl_only` | The reason a bench cannot run on the routed netlist. Only a bench that reads signals inside the design needs one. |
| `answers.flops_without_reset` | For a flop that has no reset on purpose: `match` (its name), `why`, and `evidence` (the bench that proves it starts known). |

STA runs at every corner of the cell library that the 2 ranges select: on
`sky130A` with 0 to 70 C and 1.8 V within 5 % that is 15 corners.
`chip.json` names 1 of `floorplan.die_um` and `limits.utilization` at
least: the build needs a size to aim at.

### The 2 limits

A limit comes from the spec when the spec names it. When it names none,
the limit is the project's own budget, and the source says so.

1. `limits.utilization.max`: 0.6 is the density the build spreads the
   cells to on `sky130A` (`pdks/sky130A.json`, `placement_density`). Take
   0.6 with the source `pdks/sky130A.json, placement_density: the build
   spreads the cells to 0.6 of the core`, unless a shuttle's guide or the
   spec gives another number.
2. `limits.clock_skew_ns.max`: the greatest difference between the times
   the clock reaches 2 flops. STA holds setup and hold with the clock
   tree as it is built; this limit holds the tree itself. With no number
   in the spec, take a twentieth of the clock period (1 ns for a 20 ns
   clock) and write the source as `the project's budget: a twentieth of
   the 20 ns clock period`.
3. Write each budget the project sets itself under "Decisions" in
   `README.md`, with its reason.

```json
"limits": {
  "utilization": {"max": 0.6, "source": "pdks/sky130A.json, placement_density: the build spreads the cells to 0.6 of the core"},
  "clock_skew_ns": {"max": 1.0, "source": "the project's budget: a twentieth of the 20 ns clock period"}
}
```

## The RTL

1. Verilog-2005 or SystemVerilog that Yosys 0.33 reads. Start each file
   with `` `default_nettype none `` and end it with
   `` `default_nettype wire ``.
2. 1 clock port. No gated clock, no second clock: use an enable.
3. Every flop has a reset. A synchronous reset is the simplest:
   `if (rst) q <= 8'd0; else if (en) q <= d;`.
4. No latch: a combinational block assigns each signal in every branch.
   Give a default at the block's top, or a `default:` in each `case`.
5. No loop of gates, no net with 2 drivers, no tri-state inside the chip.
6. No `initial` block in the RTL: silicon has none. A value at power-up
   comes from the reset.
7. No delay (`#5`) in the RTL.
8. A memory is flops here: a `reg [7:0] store [0:15]` becomes 128 flops.
   Keep it small.
9. A register that nothing reads is not built. SYNTH names each flop
   that the mapping removed: read the names, and remove the register or
   read it.
10. The RTL is 1 text for every engine. LINT judges what Verilator reads,
    SIM what Icarus Verilog reads and SYNTH what Yosys reads. LINT fails
    each line that speaks to 1 of them alone:
    - a `verilator lint_off` comment, in any spelling and for any class,
      and a `verilator_config` block;
    - an `` `ifdef ``, `` `ifndef `` or `` `elsif `` on a name that an
      engine defines: `VERILATOR`, `SYNTHESIS`, `YOSYS`, `__ICARUS__`;
    - a `translate_off` comment, `full_case` and `parallel_case`.
11. No `$readmemh` and no `$readmemb` in the RTL: each engine looks for
    the file in another folder. Write the contents as a `case`.
12. A header is named in quotes: `` `include "widths.vh" ``. It lies
    beside the file that names it, or in `tb/`.

## A bench

A bench is a Verilog file in `tb/` whose module has the file's name
(`tb/tb_uart.v` holds `module tb_uart`). `tb/tb_<module>.v` from the
template is a working example.

1. Drive the top module's ports only. Such a bench runs on the RTL (SIM)
   and on the routed netlist (GLSIM).
2. Compare each output with a value worked out by hand or by a model,
   with `!==`. Count each comparison in `checks` and each mismatch in
   `errors`.
3. Count in `x_outputs` each clock edge after the reset at which an
   output is unknown: `if (^q === 1'bx) x_outputs = x_outputs + 1;`.
4. Print the 3 measures, each on its own line, then end:
   `$display("errors = %0d", errors);`, the same for `checks` and
   `x_outputs`, then `$finish;`. A bench that runs out of events with no
   `$finish` has not ended.
5. The gate holds `errors` to 0, `checks` to 1 at least and `x_outputs`
   to 0. Another printed measure gets its bound in
   `tb/<bench>.expect.json`:
   `{"latency": {"max": 4, "source": "the spec's line"}}`. The name in
   the file is the name as the bench prints it, letter for letter.
6. Change inputs on the falling edge of the clock and compare there too,
   so that no input changes at the edge that reads it.
7. A bench that waits for an event stops after a count of cycles:
   a design that never answers must end the bench, with an error.
8. A bench reads no file while it runs: no `$readmemh`, `$readmemb`,
   `$fscanf`, `$fgets`, `$fgetc` and no `$fread`. The simulator opens such
   a file from the folder the gate runs the bench in, and no record of a
   pass would hold it. Write the values as text in a header that the
   bench includes: `tb/program.vh` with 1 assignment on a line
   (`rom[0] = 8'h3A;`), and `` `include "program.vh" `` inside an
   `initial` block. SIM fails a bench that reads a file, before it runs.
9. A bench is 1 text for SIM and GLSIM. No `` `ifdef `` on a name that
   GLSIM defines for the cells' models: `FUNCTIONAL` and `UNIT_DELAY` on
   `sky130A`. GLSIM fails a bench that asks for one.

GLSIM fails a bench that makes another count of `checks` on the netlist
than on the RTL: the bench took another path.

## The constraints

`constraints.sdc` holds the clock and the timing at the pins. A line with
a number ends with `;# source: <where the number comes from>`.

1. `create_clock -name clk -period <ns> [get_ports clk]`: 1 clock, on the
   clock port.
2. `set_input_delay <ns> -clock clk [get_ports {...}]` for every input
   but the clock: how long after the clock edge the input is valid.
3. `set_output_delay <ns> -clock clk [get_ports {...}]` for every output:
   how long before the clock edge the output is read.
4. A delay covers each bit of each port. Name a bus as `d[*]` or by its
   bare name `d`: `d[0]` names 1 bit. `[all_inputs]` in `set_input_delay`
   names every input, and `[all_outputs]` in `set_output_delay` every
   output. A port, or a bit of a bus, with no delay is a failure of LINT:
   STA cannot judge a path through it.
5. A delay with no `-min` and no `-max` is the delay for setup and for
   hold. With `-max` it is for setup alone, and with `-min` for hold
   alone: write both lines, or neither flag. A delay names its `-clock`.
   `-rise` and `-fall` are not taken: 1 delay is for both edges.
6. Write 1 command on a line, with each value itself and no variable,
   and each option 1 time: of 2 `-period` values Tcl takes the last. The
   gates take `create_clock`, `set_clock_uncertainty`,
   `set_input_delay`, `set_output_delay`, `set_driving_cell`,
   `set_input_transition`, `set_load`, `set_max_fanout`,
   `set_max_transition`, `set_timing_derate`, `set_false_path` and
   `set_multicycle_path`. An exception (`set_false_path`,
   `set_multicycle_path`) carries its source too.
7. A margin takes time away from a path, never gives it:
   `set_clock_uncertainty` is 0 or more, `set_timing_derate -late` is 1
   or more, and `set_timing_derate -early` is 1 or less. LINT fails the
   other sign whatever the source says.

The period is a requirement of the spec. A path that is too slow is
shortened in the RTL; the period does not grow to pass STA.

## The list of changes

`rtl/mutations.json` lists changes of the RTL, each a fault that a bench
must catch. SIM makes each change in a copy of the RTL and runs the
benches on it. A change that every bench passes on is a failure: the
benches do not check what the change breaks.

```json
{
  "mutations": [
    {"name": "enable-ignored", "file": "rtl/counter.v",
     "old": "else if (en) count", "new": "else count"}
  ]
}
```

1. Write 1 change for each thing the spec promises: a reset value, an
   enable, a carry, a wrap, each branch of each `case`, each flag.
2. `old` is text that stands in `file` exactly 1 time. `new` replaces it.
   `file` is a file that the RTL alone reads: an RTL file, or a header
   that no bench includes. A change in a header that a bench includes too
   would change the bench with the RTL, and SIM refuses it.
3. A change must compile. One that does not shows nothing, and SIM fails
   the list on it.
4. A change that changes nothing a pin can show is not a fault: remove
   it from the list, or remove the logic it touches from the RTL.
5. When a change survives, add the check that fails on it to a bench.
   Do not remove the change.

`tests/chips/pass-counter` (5 changes) and `tests/chips/pass-acc8`, an
8-bit processor (18 changes), are whole projects to read.

## Done when

- `workcenter next <dir>` names a step of the gates ("Run the chip
  gates."), not a step of this skill.
- `README.md` holds no line that starts with `fill:`.
