# acc8

An 8-bit accumulator processor with its program in a ROM. It is the
acceptance design of the chip gates: small enough to read in 1 sitting, and
large enough that every gate has work to do. 4 Verilog files, 1 clock, a
synchronous reset, no latch, no tri-state, no memory macro.

## The processor

| Part | What it is |
|---|---|
| Accumulator | `A`, 8 bits |
| Flags | `Z` and `C` |
| Registers | `r0` to `r15`, 8 bits each, in flip-flops: the data store |
| Program counter | `pc`, 8 bits |
| Program store | 256 words of 13 bits in a `case` statement, 4 slots of 64 words |
| Speed | 1 instruction per clock, every instruction |

A word is `opcode[12:9] m[8] arg[7:0]`. An operand `src` is the value `arg`
when `m` is 1 (written `#5`) and the register `r[arg[3:0]]` when `m` is 0
(written `r5`). Numbers are unsigned.

| Opcode | Instruction | What it does | Z becomes | C becomes |
|---|---|---|---|---|
| 0 | `HLT` | stops: `halted` goes high and `pc` stays on the `HLT` | | |
| 1 | `LD src` | A = src | A == 0 | |
| 2 | `ST r` | r = A | | |
| 3 | `ADD src` | A = A + src | A == 0 | the carry out of bit 7 |
| 4 | `SUB src` | A = A - src | A == 0 | the borrow: A < src before |
| 5 | `CMP src` | compares, A stays | A == src | A < src |
| 6 | `AND src` | A = A & src | A == 0 | |
| 7 | `OR src` | A = A \| src | A == 0 | |
| 8 | `XOR src` | A = A ^ src | A == 0 | |
| 9 | `SHL` | A = A << 1 | A == 0 | the bit 7 that left |
| a | `SHR` | A = A >> 1 | A == 0 | the bit 0 that left |
| b | `IN` | A = `in_port` | A == 0 | |
| c | `OUT` | `out_port` = A, and `out_valid` is high for the next cycle | | |
| d | `JMP addr` | pc = addr | | |
| e | `JZ addr`, `JNZ addr` | jumps when Z is 1; `JNZ` is the same opcode with `m` = 1 and jumps when Z is 0 | | |
| f | `JC addr`, `JNC addr` | jumps when C is 1; `JNC` is the same opcode with `m` = 1 and jumps when C is 0 | | |

An empty cell: the instruction leaves the flag as it was. A word no program
fills is 0, which is `HLT`.

## Pins

| Pin | Width | Direction | What it is |
|---|---|---|---|
| `clk` | 1 | in | the clock; every flip-flop takes its rising edge |
| `rst` | 1 | in | synchronous reset, active high: 1 rising edge with `rst` high clears A, Z, C, `r0` to `r15`, `out_port`, `out_valid` and `halted`, and sets pc = `boot` x 64 |
| `boot` | 2 | in | the ROM slot the program starts in, read while `rst` is high |
| `in_port` | 8 | in | read by `IN` on the rising edge that ends the instruction |
| `out_port` | 8 | out | the last value `OUT` wrote; a flip-flop output |
| `out_valid` | 1 | out | high for the 1 cycle after an `OUT`; a flip-flop output |
| `halted` | 1 | out | high after a `HLT` until the next reset; a flip-flop output |

Nothing synchronises `rst`, `boot` or `in_port`. Hold each steady around the
rising edges that read it.

## The programs

The program is part of the chip. `programs/rom.list` names 1 assembly file
for each slot, and `python3 acc8.py rom` assembles them into
`rtl/acc8_rom.v`.

| Slot | Program | `in_port` | `out_port` when halted | Worked by hand |
|---|---|---|---|---|
| 0 | `sum.asm` | N | 1 + 2 + ... + N, after 1 output for each term | N = 10: 55 |
| 1 | `mul.asm` | A in bits 7 to 4, B in bits 3 to 0 | A x B by repeated addition | 6 x 7 = 42 |
| 2 | `gcd.asm` | A in bits 7 to 4, B in bits 3 to 0 | gcd(A, B) by subtraction | gcd(12, 8) = 4 |
| 3 | `crc.asm` | a byte | its CRC-8, polynomial 0x07 | 0x80 gives 0x89 |

An assembly line is `label: INSTRUCTION operand ; comment`. `name = r3` names
a register and `name = 10` a number. `#` marks a value (`ADD #1`); without it
the operand is a register (`ADD total`). A jump takes a label.

## How to test

1. Hold `boot` at the slot and `in_port` at the input.
2. Hold `rst` high for 1 rising edge of `clk`, then low.
3. Clock until `halted` is high.
4. Read `out_port`. Count the cycles with `out_valid` high.

The 4 program benches do these steps on the top module's pins, on the RTL
and on the routed netlist. `tb_sum` also resets the processor in the middle
of a program. `tb_random` drives the core alone with 1024 instruction words
and compares its ports with the model of `acc8.py` after each word.

## Decisions

| Decision | Reason |
|---|---|
| The 2 top bits of `pc` have no fixed reset value. | The reset loads them from `boot`. `chip.json` answers for both flops, and the benches start in every slot. |
| `tb_random` runs on the RTL only. | It drives `acc8_core`, and the routed netlist of `acc8` holds no module of that name. `chip.json` says so. |
| The benches read the pins only. | The same bench then runs on the RTL and on the netlist. |
| `rtl/acc8_rom.v` and `tb/random_stim.vh` are generated. | `python3 acc8.py rom --check` and `python3 acc8.py stim --check` compare each with what `acc8.py` writes. |

## Commands

```
python3 acc8.py list                     the ROM: address, word, instruction
python3 acc8.py run --boot 1 --in 0x67   1 program on the model
python3 acc8.py rom                      write rtl/acc8_rom.v from the programs
python3 acc8.py stim                     write tb/random_stim.vh from the model
workcenter chip gates . --strict         the 10 gates; the last line is the verdict
```

`build/` holds everything a run writes. It is not committed.
