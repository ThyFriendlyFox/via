#!/usr/bin/env python3
"""The acc8 processor's assembler, ROM writer and instruction-level model.

Standard library only.

    acc8.py rom [--check]             write rtl/acc8_rom.v from programs/rom.list,
                                      or check that the file is that text
    acc8.py list                      print the ROM: address, word, instruction
    acc8.py run --boot N --in VALUE   run 1 program on the model
    acc8.py stim [--check]            write tb/random_stim.vh, the stream of tb_random.v with the
                                      model's answer for each word, or check that the file is that text
"""

import argparse
import os
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ROM_LIST = ROOT / "programs" / "rom.list"
ROM_VERILOG = ROOT / "rtl" / "acc8_rom.v"
STIM_HEADER = ROOT / "tb" / "random_stim.vh"

SLOTS = 4
SLOT_WORDS = 64
ROM_WORDS = SLOTS * SLOT_WORDS
STIM_WORDS = 1024
STIM_SEED = 1
STIM_BOOT = 2  # tb_random.v resets the core into the same slot
CORNERS = (0x00, 0x01, 0x0F, 0x7F, 0x80, 0xFF)

HLT, LD, ST, ADD, SUB, CMP, AND, OR, XOR, SHL, SHR, IN, OUT, JMP, JZ, JC = range(16)

# mnemonic: (opcode, operand, m). Operand: None, "src" (#value or register),
# "reg" or "addr". m None: 1 for #value, 0 for a register.
MNEMONICS = {
    "HLT": (HLT, None, 0),
    "LD": (LD, "src", None),
    "ST": (ST, "reg", 0),
    "ADD": (ADD, "src", None),
    "SUB": (SUB, "src", None),
    "CMP": (CMP, "src", None),
    "AND": (AND, "src", None),
    "OR": (OR, "src", None),
    "XOR": (XOR, "src", None),
    "SHL": (SHL, None, 0),
    "SHR": (SHR, None, 0),
    "IN": (IN, None, 0),
    "OUT": (OUT, None, 0),
    "JMP": (JMP, "addr", 0),
    "JZ": (JZ, "addr", 0),
    "JNZ": (JZ, "addr", 1),
    "JC": (JC, "addr", 0),
    "JNC": (JC, "addr", 1),
}

REGISTER = re.compile(r"^[rR](\d+)$")
NAME = r"[A-Za-z_]\w*"


class AsmError(Exception):
    pass


def encode(opcode, mode, arg):
    return opcode << 9 | mode << 8 | arg


def number_of(text):
    try:
        return int(text, 0)
    except ValueError:
        return None


def assemble(path, origin):
    """1 program -> [(address, word, source text)], placed from origin."""
    symbols = {}
    program = []
    address = origin

    def fail(lineno, message):
        raise AsmError(f"{path.name}:{lineno}: {message}")

    def define(lineno, name, value):
        if name in symbols or REGISTER.match(name) or name.upper() in MNEMONICS:
            fail(lineno, f"{name}: the name is taken")
        symbols[name] = value

    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = " ".join(raw.split(";", 1)[0].split())
        if not line:
            continue
        alias = re.match(rf"^({NAME}) ?= ?(\S+)$", line)
        if alias:
            name, value = alias.groups()
            if REGISTER.match(value):
                define(lineno, name, ("reg", int(value[1:])))
            elif number_of(value) is not None:
                define(lineno, name, ("num", number_of(value)))
            else:
                fail(lineno, f"{value}: neither a register nor a number")
            continue
        text = line
        label = re.match(rf"^({NAME}): ?(.*)$", line)
        if label:
            define(lineno, label.group(1), ("num", address))
            line = label.group(2)
            if not line:
                continue
        fields = line.split(None, 1)
        mnemonic = fields[0].upper()
        if mnemonic not in MNEMONICS:
            fail(lineno, f"{fields[0]}: no such instruction")
        program.append((lineno, address, mnemonic, fields[1] if len(fields) > 1 else "", text))
        address += 1
    if address - origin > SLOT_WORDS:
        raise AsmError(f"{path.name}: {address - origin} words, a slot holds {SLOT_WORDS}")

    def register(lineno, text):
        match = REGISTER.match(text)
        if match:
            index = int(match.group(1))
        elif symbols.get(text, ("", 0))[0] == "reg":
            index = symbols[text][1]
        else:
            fail(lineno, f"{text}: not a register (write #{text} for a value)")
        if index > 15:
            fail(lineno, f"{text}: the registers are r0 to r15")
        return index

    def number(lineno, text, low, high):
        value = number_of(text)
        if value is None:
            if symbols.get(text, ("", 0))[0] != "num":
                fail(lineno, f"{text}: neither a number nor a label")
            value = symbols[text][1]
        if not low <= value <= high:
            fail(lineno, f"{text}: outside {low} to {high}")
        return value & 0xFF

    words = []
    for lineno, address, mnemonic, operand, text in program:
        opcode, kind, mode = MNEMONICS[mnemonic]
        if (kind is None) != (operand == ""):
            fail(lineno, f"{mnemonic} takes {'no' if kind is None else '1'} operand")
        if kind is None:
            arg = 0
        elif kind == "addr":
            arg = number(lineno, operand, 0, ROM_WORDS - 1)
        elif kind == "reg":
            arg = register(lineno, operand)
        elif operand.startswith("#"):
            mode, arg = 1, number(lineno, operand[1:].strip(), -128, 255)
        else:
            mode, arg = 0, register(lineno, operand)
        words.append((address, encode(opcode, mode, arg), text))
    return words


def build_rom():
    """programs/rom.list -> (256 words, [(address, word, source text)], {slot: file name})."""
    rom = [encode(HLT, 0, 0)] * ROM_WORDS
    listing = []
    slots = {}
    for lineno, raw in enumerate(ROM_LIST.read_text(encoding="utf-8").splitlines(), 1):
        fields = raw.split("#", 1)[0].split()
        if not fields:
            continue
        if len(fields) != 2 or not fields[0].isdigit() or int(fields[0]) >= SLOTS:
            raise AsmError(f"{ROM_LIST.name}:{lineno}: want `<slot 0 to {SLOTS - 1}> <file>`")
        slot = int(fields[0])
        if slot in slots:
            raise AsmError(f"{ROM_LIST.name}:{lineno}: slot {slot} is named twice")
        slots[slot] = fields[1]
        for address, word, text in assemble(ROM_LIST.parent / fields[1], slot * SLOT_WORDS):
            rom[address] = word
            listing.append((address, word, text))
    return rom, listing, slots


def rom_verilog():
    _, listing, slots = build_rom()
    lines = [
        "// Generated by `python3 acc8.py rom` from programs/rom.list. Edit the",
        "// programs, never this file.",
        "//",
        f"// acc8_rom: the program store. {ROM_WORDS} words of 13 bits, {SLOTS} slots of {SLOT_WORDS} words.",
        "// A word no program fills reads as HLT.",
        "",
        "`default_nettype none",
        "",
        "module acc8_rom (",
        "    input  wire [7:0]  addr,",
        "    output reg  [12:0] data",
        ");",
        "",
        "    always @* begin",
        "        case (addr)",
    ]
    for slot in sorted(slots):
        lines.append(f"            // slot {slot}: {slots[slot]}")
        for address, word, text in listing:
            if address // SLOT_WORDS == slot:
                lines.append(f"            8'h{address:02x}: data = 13'h{word:04x};  // {text}")
    lines += [
        f"            default: data = 13'h{encode(HLT, 0, 0):04x};  // HLT",
        "        endcase",
        "    end",
        "",
        "endmodule",
        "",
        "`default_nettype wire",
        "",
    ]
    return "\n".join(lines)


def is_current(path, text):
    return path.exists() and path.read_text(encoding="utf-8") == text


class Model:
    """The processor, 1 instruction per step. step() is 1 clock of the RTL."""

    def __init__(self, rom):
        self.rom = rom
        self.reset(0)

    def reset(self, boot):
        self.pc = (boot & 3) * SLOT_WORDS
        self.acc = 0
        self.z = 0
        self.c = 0
        self.reg = [0] * 16
        self.out = 0
        self.out_valid = 0
        self.halted = 0

    def step(self, in_port, word=None):
        """Execute the word at pc, or the word given in its place."""
        if self.halted:
            return
        if word is None:
            word = self.rom[self.pc]
        opcode, mode, arg = word >> 9, word >> 8 & 1, word & 0xFF
        index = arg & 15
        src = arg if mode else self.reg[index]
        acc = self.acc
        result = carry = None
        target = (self.pc + 1) & 0xFF
        self.out_valid = 0
        if opcode == HLT:
            self.halted = 1
            target = self.pc
        elif opcode == LD:
            result = src
        elif opcode == ST:
            self.reg[index] = acc
        elif opcode == ADD:
            result = (acc + src) & 0xFF
            carry = int(acc + src > 0xFF)
        elif opcode == SUB:
            result = (acc - src) & 0xFF
            carry = int(acc < src)
        elif opcode == CMP:
            self.z = int(acc == src)
            carry = int(acc < src)
        elif opcode == AND:
            result = acc & src
        elif opcode == OR:
            result = acc | src
        elif opcode == XOR:
            result = acc ^ src
        elif opcode == SHL:
            result = (acc << 1) & 0xFF
            carry = acc >> 7
        elif opcode == SHR:
            result = acc >> 1
            carry = acc & 1
        elif opcode == IN:
            result = in_port
        elif opcode == OUT:
            self.out = acc
            self.out_valid = 1
        elif opcode == JMP:
            target = arg
        elif opcode == JZ:
            if self.z != mode:
                target = arg
        elif opcode == JC:
            if self.c != mode:
                target = arg
        if result is not None:
            self.acc = result
            self.z = int(result == 0)
        if carry is not None:
            self.c = carry
        self.pc = target


def stim_words():
    """tb_random.v's stream: [(in_port, word)], STIM_WORDS long.

    Random instructions without HLT, then HLT, then 6 words that would each
    change a core that did not stay halted.
    """
    rng = random.Random(STIM_SEED)

    def value():
        return rng.choice(CORNERS) if rng.random() < 0.5 else rng.getrandbits(8)

    stream = [
        (value(), encode(rng.randrange(1, 16), rng.getrandbits(1), value())) for _ in range(STIM_WORDS - 7)
    ]
    model = Model([])
    model.reset(STIM_BOOT)
    for in_port, word in stream:
        model.step(in_port, word)
    other = model.acc ^ 0xFF
    spare = next((i for i in range(16) if model.reg[i] != model.acc), 0)
    stream.append((value(), encode(HLT, rng.getrandbits(1), value())))
    stream += [
        (other, encode(OUT, 0, 0)),
        (other, encode(ST, 0, spare)),
        (other, encode(LD, 1, other)),
        (other, encode(IN, 0, 0)),
        (other, encode(SUB, 1, 1)),
        (other, encode(JMP, 0, model.pc ^ 0x80)),
    ]
    return stream


def stim_header():
    """tb/random_stim.vh: 1 `step` for each word of the stream, with the ports the model has after it."""
    lines = [
        "// Generated by `python3 acc8.py stim`. Edit acc8.py, never this file.",
        "//",
        f"// The stream of tb_random.v, seed {STIM_SEED}, {STIM_WORDS} words. Each line is",
        "// step({in_port, rom_data}, {rom_addr, out_port, out_valid, halted}): a word for acc8_core, and",
        "// the ports the model of acc8.py has after it.",
        "",
    ]
    model = Model([])
    model.reset(STIM_BOOT)
    for in_port, word in stim_words():
        model.step(in_port, word)
        want = model.pc << 10 | model.out << 2 | model.out_valid << 1 | model.halted
        lines.append(f"        step(21'h{in_port << 13 | word:06x}, 18'h{want:05x});")
    return "\n".join(lines) + "\n"


def run(boot, value):
    model = Model(build_rom()[0])
    model.reset(boot)
    cycle = 0
    while not model.halted and cycle < 100000:
        model.step(value)
        cycle += 1
        if model.out_valid:
            print(f"cycle {cycle}: output {model.out} (0x{model.out:02x})")
    if not model.halted:
        print(f"not halted after {cycle} cycles")
        return 1
    print(f"halted after {cycle} cycles, out_port {model.out} (0x{model.out:02x})")
    return 0


def write_or_check(name, path, text, source, check):
    """Write a generated file, or say whether the file on disk is the text its source gives."""
    if not check:
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")
        return 0
    if is_current(path, text):
        print(f"PASS {name}: {path.name} is what {source} gives")
        return 0
    print(f"FAIL {name}: {path.name} is not what {source} gives; run `python3 acc8.py {name}`")
    return 1


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    rom = commands.add_parser("rom")
    rom.add_argument("--check", action="store_true")
    commands.add_parser("list")
    runner = commands.add_parser("run")
    runner.add_argument("--boot", type=lambda text: int(text, 0), default=0)
    runner.add_argument("--in", dest="value", type=lambda text: int(text, 0), default=0)
    stim = commands.add_parser("stim")
    stim.add_argument("--check", action="store_true")
    args = parser.parse_args()

    try:
        if args.command == "rom":
            return write_or_check("rom", ROM_VERILOG, rom_verilog(), "programs/rom.list", args.check)
        if args.command == "list":
            _, listing, slots = build_rom()
            for slot in sorted(slots):
                print(f"slot {slot}: {slots[slot]}")
                for address, word, text in listing:
                    if address // SLOT_WORDS == slot:
                        print(f"  {address:02x}  {word:04x}  {text}")
            return 0
        if args.command == "run":
            return run(args.boot, args.value & 0xFF)
        return write_or_check("stim", STIM_HEADER, stim_header(), "the model", args.check)
    except AsmError as error:
        print(f"FAIL asm: {error}")
        return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        # `acc8.py list | head`: the reader has left. Without this, Python
        # prints a second error when it flushes stdout on the way out.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(1)
