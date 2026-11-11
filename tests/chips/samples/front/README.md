# Reports of the front engines

Real output of Verilator 5.020, Icarus Verilog 12.0 and Yosys 0.33, written
on 2026-11-11 by the chip gates on copies of the template project
(`workcenter chip init reg8 --top reg8`) with 1 thing changed. The judges
in `tools/chipfront.py` read them in `tests/test_chipfront.py`, with no
engine. 2 paths are rewritten in each file: the project's folder is
`/work/reg8`, the process kit is `/kit`. Nothing else is changed.

| Sample | What was run |
|---|---|
| `verilator-clean.log` | `--lint-only -Wall` on the template: no output |
| `verilator-latch-width-undriven.log` | a branch that assigns nothing, an 8-bit value into 4 bits, an output with no driver |
| `verilator-syntax-error.log` | a module with 2 semicolons left out |
| `verilator-ports.xml` | `--xml-only` on the template: the top module's ports |
| `vvp-pass.log` | the template's bench |
| `vvp-errors.log` | the bench on RTL that ignores its enable |
| `vvp-x-output.log` | the bench on RTL whose reset does not reset |
| `vvp-no-finish.log` | a bench that runs out of events with no `$finish` |
| `vvp-no-measures.log` | a bench that prints `errors` only |
| `iverilog-no-root.log` | a bench whose module is not named as its file |
| `iverilog-open-supply.log` | the template's bench compiled on its routed netlist: the 2 supply ports open |
| `yosys-ok/` | the template through the SYNTH gate's script |
| `yosys-latch/` | the latch design: 8 latch bits, 12 flops with no reset, an open net |
| `yosys-loop/` | 2 gates that feed each other |
| `yosys-two-drivers/` | 1 net assigned 2 times |
| `yosys-no-reset/` | 1 flop with no reset and a constant output |

A new failure shape of an engine gets a sample here in the commit that
teaches a judge to read it.
