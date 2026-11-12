# Fixture chips

These projects are the tests of the chip gates, as `tests/boards/` is for
the board gates. Each one passes every gate, or fails 1 named gate for 1
reason with every gate before it passing. `tests/test_chips.py` runs each
and holds its exit code, its last line, the gate that fails and that gate's
first failure line.

| Project | Proves | Its run ends with |
|---|---|---|
| `pass-counter` | GREEN on `workcenter chip gates`, with `--strict` too. An 8-bit counter with an enable and a synchronous reset: 29 cells and 8 flops on a die of 50 um by 50 um, a 20 ns clock, 15 timing corners, 1 bench with 8 checks. Its `rtl/mutations.json` lists 5 changes of the RTL, and the bench catches each. | `GREEN: pass-counter  report <project>/build/gates.json` |
| `pass-acc8` | The acceptance design, GREEN with `--strict`: acc8, an 8-bit processor with 4 programs in its ROM, 760 cells and 132 flops on a die of 152.38 um by 152.38 um, a 40 ns clock. Its 5 benches make 1098 checks and catch each of the 18 changes of `rtl/mutations.json`. See "What `pass-acc8` shows". | `GREEN: pass-acc8  report <project>/build/gates.json` |
| `fail-lint-latch` | LINT fails on a latch. 1 branch of a combinational block assigns nothing: `LATCH: rtl/counter.v:11:5: Latch inferred for signal 'counter.next' (not all control paths of combinational always assign a value)`. | `RED: fail-lint-latch  report <project>/build/gates.json` |
| `fail-lint-second-clock` | LINT fails on a second clock in the constraints. The RTL is the passing counter's: `constraints.sdc: line 4: a second clock: the first flow takes 1 clock. Use 1 clock and an enable`. | `RED: fail-lint-second-clock  report <project>/build/gates.json` |
| `fail-sim-spec` | SIM fails on a bench that counts an error. The counter counts by 2, and 5 of the bench's 8 comparisons fail: `tb_counter: errors=5 not in [None, 0]`. | `RED: fail-sim-spec  report <project>/build/gates.json` |
| `fail-synth-noreset` | SYNTH fails on a flop with no reset and no answer in `chip.json`. The flop `en_q` registers the enable, and SIM passes with 10 checks: `1 flops have no reset: en_q: reset each, or name it in chip.json's answers.flops_without_reset with why and the bench that proves it`. | `RED: fail-synth-noreset  report <project>/build/gates.json` |
| `fail-layout-area` | LAYOUT fails on a die too small for the cells. On a die of 46 um by 46 um the build of the passing counter stops after the floorplan: `utilisation 0.6451 is over the limit 0.5 of chip.json after the floorplan, before the clock tree adds cells: take a larger die, or cut logic. Do not raise the limit`. | `RED: fail-layout-area  report <project>/build/gates.json` |
| `fail-sta-corner` | STA fails at the slow corners alone, as `fail-sim-corner` does for a board. The passing counter with a clock period of 5 ns: each typical and each fast corner meets it by 0.36 ns or more, and each of the 6 slow corners misses it by 0.29 to 0.33 ns. The layout build says so first, as a warning of LAYOUT: `[WARNING RSZ-0062] Unable to repair all setup violations.` The first line of STA: `max_ss_n40C_1v60: setup slack -0.3277 ns, from _49_ to count[3]`. | `RED: fail-sta-corner  report <project>/build/gates.json` |
| `fail-glsim-x` | GLSIM fails on an output that is unknown on the netlist while the RTL run hides it. An `initial` block stands where the reset should clear the count, and `chip.json` answers for the 8 flops. SIM passes with `x_outputs = 0`. On the routed netlist the count is never known: `tb_counter: errors=8 not in [None, 0]`, then `tb_counter: x_outputs=266 not in [None, 0]`. | `RED: fail-glsim-x  report <project>/build/gates.json` |

Each failing fixture is the passing counter with 1 fault. It differs from
`pass-counter` only in the files that hold the fault, and it has no
mutation list: SIM names that absence as a warning. `fail-synth-noreset`
and `fail-glsim-x` have a bench of their own too, because their counter
acts in another way.

## The gates after GLSIM

DRC, ANTENNA, LVS and EXPORT have no failing fixture. A fixture holds RTL,
and the engines make its layout: no line of RTL asks for a spacing error, a
wire that collects charge, a swapped net or a file changed after a gate
judged it. Real reports of the engines hold the failures of DRC, ANTENNA
and LVS, under `tests/chips/samples/back/`. Runs in
`tests/test_chipback.py` hold what EXPORT refuses.

## Run one

```
workcenter chip gates tests/chips/fail-sim-spec --out <scratch>
workcenter chip gates tests/chips/pass-counter --out <scratch> --strict
```

`--out` keeps the run out of the repository, and the last line then names
`<scratch>/gates.json`. Without it the run writes `build/` beside
`chip.json`, which git ignores. `tests/test_chips.py` runs a copy of each
fixture the same way, with the default of `--jobs`.

Measured on 2026-11-12 on 4 processors, 1 fixture at a time: a fixture that
stops at LINT, SIM or SYNTH takes under 2 s. `fail-layout-area` takes 5 s:
its build stops after the floorplan. `fail-sta-corner` and `fail-glsim-x`
take 36 s and `pass-counter` 42 s. `pass-acc8` takes 217 s: its layout
build takes 192 s of them.

## The mutation lists

A passing fixture carries `rtl/mutations.json`: 1 change of the RTL for
each thing a bench must catch. The SIM gate proves the list on every run.
When the benches pass on the RTL, it makes each change in its own copy of
the sources under `build/chip/sim/mutants/` and runs the benches there. A
change that every bench passes on fails the gate, and so does a change
that does not compile: it shows nothing.

SIM's line for `pass-counter` ends `5 of 5 changes of the RTL caught`, and
for `pass-acc8` `18 of 18`. A failing fixture has no list, and SIM names
that as a warning.

## What `pass-acc8` shows

The processor is the first design here that the layout build must repair.
After the placement the build's log reads `Found 2 slew violations.`,
`Found 2 capacitance violations.`, `Inserted 3 buffers in 2 nets.` and
`Resized 647 instances.` After the global route it reads
`Antenna violations: 0`. The run with `--strict` ends GREEN:

| Gate | What it prints for `pass-acc8` |
|---|---|
| LINT | `4 RTL files, top acc8, 0 failures` |
| SIM | `5 benches, 1098 checks, 18 of 18 changes of the RTL caught, 0 failures` |
| SYNTH | `760 cells, 132 flops, 8530.7 um2, the mapping removed 24 flops that nothing reads (--json names each), 0 failures` |
| LAYOUT | `8379.29 um2 of cells, utilisation 0.493, 0 failures` |
| STA | `15 corners, least setup slack 25.1717 ns at max_ss_n40C_1v60, least hold slack 0.2974 ns at min_ff_n40C_1v95, 0 failures` |
| GLSIM | `4 benches on the final netlist, 1 on the RTL only, 0 failures` |
| DRC | `2 decks: magic 0, klayout-mr 0, 0 failures` |
| ANTENNA | `the routed database, 0 failures` |
| LVS | `the layout against the netlist with its supply pins: 792 devices against 792, 0 failures` |
| EXPORT | `22 files, 20 reports and manifest.json in chip/tapeout, 0 failures` |

The RTL describes 16 registers and the chip holds 13. With these 4
programs in the ROM nothing reads `r6`, `r9` and `r10`: the mapping proves
it and removes their 24 flops. SYNTH counts the flops of the netlist, and
its record names each flop the mapping removed. `tb_random` drives the
core alone, so `chip.json` keeps that bench on the RTL.

1 set of files gives 1 layout: 5 builds at 1, 2, 4 and 8 jobs wrote the
same GDS, and `tests/test_chips.py` holds the run to its hash, which
starts `0c51debe623a0a18`. A change of a script or of the process table
that moves 1 wire changes it.

GREEN says what the run's scope line says: the open engines found no fault
in these files, with the community decks, at the 15 corners the project's
ranges select. No foundry deck ran.

The round of 2026-11-11 ended RED here. STA failed 13 of the 15 corners,
the first with 477 slew and capacitance limits broken; KLayout's deck
counted 8 items; 1 net collected too much charge. The gates were right and
the build was short. `pdks/README.md` says what the build does now, and
the landmine map in `ee-agent-kit/AGENTS.md` what each engine did.
