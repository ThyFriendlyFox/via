"""Copy RF_Module:ESP32-WROOM-32E into a project library with its stacked GND pin split into 4 pins.

    python3 symbols/split_stacked.py /usr/share/kicad/symbols/RF_Module.kicad_sym symbols/rosetta.kicad_sym

KiCad 10 draws the module's 4 ground pins as 1 pin numbered "[1,15,38,39]", which kicadgen does
not split. The copy has pin 1 where the stacked pin was, and pins 15, 38 and 39 hidden on the same
spot as passive pins, the way KiCad's own RP2040 symbol draws its extra supply pins.
"""

import re
import sys

src, out = sys.argv[1], sys.argv[2]
t = open(src, encoding="utf-8").read()
start = t.index('\t(symbol "ESP32-WROOM-32E"\n')
nxt = t.index('\n\t(symbol "', start + 10)  # the symbol ends where the next one starts
sym = t[start:nxt]
m = re.search(r'(\t+\(pin [^\n]*\n(?:(?!\t+\(pin ).*\n)*?\t+\(number "\[1,15,38,39\]"[\s\S]*?\n\t\t\t\))', sym)
pin = m.group(1)
copies = [pin.replace('"[1,15,38,39]"', '"1"')]
for n in ("15", "38", "39"):
    p = pin.replace('"[1,15,38,39]"', f'"{n}"').replace("(pin power_in", "(pin passive", 1)
    p = re.sub(r"\(pin (\w+) (\w+)", r"(pin \1 \2\n\t\t\t\t(hide yes)", p, count=1) if "(hide yes)" not in p else p
    copies.append(p)
sym = sym.replace(pin, "\n".join(copies))
with open(out, "w", encoding="utf-8") as f:
    f.write('(kicad_symbol_lib\n\t(version 20241209)\n\t(generator "rosetta")\n' + sym + "\n)\n")
