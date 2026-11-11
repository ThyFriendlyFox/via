# Fixture chips

These projects are the tests of the chip gates, as `tests/boards/` is for
the board gates. Each one passes every gate, or fails 1 named gate for 1
reason with every gate before it passing. `tests/test_chips.py` runs each
and holds its exit code, its last line, the gate that fails and that gate's
first failure line.

| Project | Proves | Its run ends with |
|---|---|---|
| `pass-counter` | GREEN on `workcenter chip gates`, with `--strict` too. An 8-bit counter with an enable and a synchronous reset: 31 cells and 8 flops on a die of 50 um by 50 um, a 20 ns clock, 15 timing corners, 1 bench with 8 checks. Its `rtl/mutations.json` lists 5 changes of the RTL, and the bench catches each. | `GREEN: pass-counter  report <project>/build/gates.json` |
| `pass-acc8` | The acceptance design: acc8, an 8-bit processor with 4 programs in its ROM, 770 cells and 156 flops, a 40 ns clock. Its 5 benches make 1098 checks and catch each of the 18 changes of `rtl/mutations.json`. LINT, SIM, SYNTH and LAYOUT pass with `--strict`. STA fails: see "What `pass-acc8` shows". | `RED: pass-acc8  report <project>/build/gates.json` |
| `fail-lint-latch` | LINT fails on a latch. 1 branch of a combinational block assigns nothing: `LATCH: rtl/counter.v:11:5: Latch inferred for signal 'counter.next' (not all control paths of combinational always assign a value)`. | `RED: fail-lint-latch  report <project>/build/gates.json` |
| `fail-lint-second-clock` | LINT fails on a second clock in the constraints. The RTL is the passing counter's: `constraints.sdc: line 4: a second clock: the first flow takes 1 clock. Use 1 clock and an enable`. | `RED: fail-lint-second-clock  report <project>/build/gates.json` |
| `fail-sim-spec` | SIM fails on a bench that counts an error. The counter counts by 2, and 5 of the bench's 8 comparisons fail: `tb_counter: errors=5 not in [None, 0]`. | `RED: fail-sim-spec  report <project>/build/gates.json` |
| `fail-synth-noreset` | SYNTH fails on a flop with no reset and no answer in `chip.json`. The flop `en_q` registers the enable, and SIM passes with 10 checks: `1 flops have no reset: en_q: reset each, or name it in chip.json's answers.flops_without_reset with why and the bench that proves it`. | `RED: fail-synth-noreset  report <project>/build/gates.json` |
| `fail-layout-area` | LAYOUT fails on a die too small for the cells. On a die of 46 um by 46 um the build of the passing counter stops after the floorplan: `utilisation 0.5223 is over the limit 0.5 of chip.json after the floorplan, before the clock tree adds cells: take a larger die, or cut logic. Do not raise the limit`. | `RED: fail-layout-area  report <project>/build/gates.json` |
| `fail-sta-corner` | STA fails at the slow corners alone, as `fail-sim-corner` does for a board. The passing counter with a clock period of 5.4 ns: each typical and each fast corner meets it, and each of the 6 slow corners misses it. The first line: `max_ss_n40C_1v60: setup slack -0.5704 ns, from en to _49_`. | `RED: fail-sta-corner  report <project>/build/gates.json` |
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
judged it. Real reports of the engines hold the failures of those 4 gates,
under `tests/chips/samples/back/`.

## Run one

```
workcenter chip gates tests/chips/fail-sim-spec --out <scratch> --jobs 1
workcenter chip gates tests/chips/pass-counter --out <scratch> --strict --jobs 1
```

`--out` keeps the run out of the repository, and the last line then names
`<scratch>/gates.json`. Without it the run writes `build/` beside
`chip.json`, which git ignores. `tests/test_chips.py` runs each fixture
with `--jobs 1`, 1 engine at a time: run a fixture the same way.

Measured on 2026-11-11 on 4 processors, 1 fixture at a time: a fixture that
stops at LINT, SIM or SYNTH takes under 2 s. `fail-layout-area` takes under
3 s: its build stops after the floorplan. `fail-sta-corner`, `fail-glsim-x` and
`pass-counter` take 52 to 60 s. `pass-acc8` takes 11 minutes to its STA
failure: its layout build takes 668 s.

## The mutation lists

A passing fixture carries `rtl/mutations.json`: 1 change of the RTL for
each thing a bench must catch, and the command that judges a changed copy,
`workcenter chip sim .`. `workcenter mutate` proves the list. It makes each
change in its own copy of the project and runs the command there:

```
workcenter mutate tests/chips/pass-counter --mutations tests/chips/pass-counter/rtl/mutations.json
```

Its last line is `mutate: 5 mutations, 5 caught, 0 survived, 0 did not build`
and the seconds; for `pass-acc8` the counts are 18 and 18.

## What `pass-acc8` shows

The processor is the first design here that the layout build must repair,
and the build of 2026-11-11 does not. Its run with `--strict` stops at STA:

| Gate | What it prints for `pass-acc8` |
|---|---|
| LAYOUT | `6909.13 um2 of cells, utilisation 0.528, 0 failures` on a die of 136.665 um by 136.665 um |
| STA | 13 of the 15 corners fail. The first line starts `max_ss_n40C_1v60: 477 pins break a limit of the library or the constraints (max slew, max capacitance)`. The least setup slack is 15.4277 ns at `max_ss_n40C_1v60`, and the least hold slack 0.2841 ns at `min_ff_n40C_1v95`. |
| GLSIM, run alone on that layout | `4 benches on the final netlist, 1 on the RTL only, 0 failures` |
| DRC, run alone | `2 decks: magic 0, klayout-mr 8, 1 failures`: `klayout-mr: 8 items break a rule: npc.2, nsd.2, psd.2` |
| ANTENNA, run alone | `1 nets and 1 pins collect more charge than their gates take: build again with diodes or more repair` |
| LVS, run alone | `the layout against the netlist with its supply pins: 787 devices against 787, 0 failures` |

The fixture stays as it is. `tests/test_chips.py` holds the STA failure as
a known fault of the build and fails on the day the run is GREEN: change
the row of `pass-acc8` and remove the known fault then.
