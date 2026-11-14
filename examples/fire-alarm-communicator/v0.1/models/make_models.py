"""3D bodies for the 3 parts KiCad's 3D library has none for, for the renders and the STEP export,
and the black screw terminals.

    python3 models/make_models.py      # from the board's folder; writes the 3 .wrl files here
                                       # and, with $KICAD10_3DMODEL_DIR set, the 3 terminal bodies

Each body is sized from its maker's outline, in the footprint's own frame: origin at the footprint's
origin, X right, Y toward the footprint's top, Z out of the board (tools/wrlgen.py's convention).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[3] / "tools"))

import wrlgen  # noqa: E402
from wrlgen import Mesh, box, cylinder, write_wrl  # noqa: E402

SUBSTRATE = (0.10, 0.22, 0.14)
SHIELD = (0.58, 0.59, 0.62)
LABEL = (0.95, 0.95, 0.93)
INK = (0.15, 0.15, 0.16)
DARK = (0.08, 0.08, 0.09)
GOLD = (0.86, 0.70, 0.30)


def bg95() -> None:
    """Quectel BG95: an LGA module 19.9 x 23.6 x 2.2 mm, a shield can over its substrate and a label
    on the can. The footprint's pad 1 is its top-left corner."""
    sub, can, label, ink = Mesh(SUBSTRATE), Mesh(SHIELD), Mesh(LABEL), Mesh(INK)
    box(sub, 0.0, 0.0, 0.0, 19.9, 23.6, 0.9)
    box(can, 0.0, 0.0, 0.9, 19.3, 23.0, 1.3)
    box(label, 0.0, -1.0, 2.2, 15.0, 15.0, 0.02)
    # Lines of print on the label, and the pad 1 mark in its corner.
    for k in range(4):
        box(ink, -1.5 + (1.0 if k == 0 else 0.0), 4.0 - 2.2 * k, 2.22, 9.0 if k else 7.0, 0.7, 0.01)
    box(ink, 5.4, -6.2, 2.22, 2.6, 2.6, 0.01)  # the 2D code
    cylinder(ink, -8.4, 10.6, 2.2, 0.45, 0.02, 24)
    write_wrl(HERE / "bg95.wrl", [sub, can, label, ink], "Quectel BG95 LTE-M module")


def esp32_s3_mini_1u() -> None:
    """Espressif ESP32-S3-MINI-1U: 15.4 x 15.4 x 2.4 mm, a shield can over most of the substrate and a
    u.FL receptacle on the free strip at the footprint's top."""
    sub, can, ufl, pin = Mesh(DARK), Mesh(SHIELD), Mesh(SHIELD), Mesh(GOLD)
    box(sub, 0.0, 0.0, 0.0, 15.4, 15.4, 0.8)
    box(can, 0.0, -1.3, 0.8, 14.6, 12.2, 1.6)
    box(ufl, 5.2, 6.1, 0.8, 2.6, 2.6, 0.3)
    cylinder(ufl, 5.2, 6.1, 1.1, 1.0, 0.8, 32)
    cylinder(pin, 5.2, 6.1, 1.9, 0.3, 0.02, 16)
    write_wrl(HERE / "esp32_s3_mini_1u.wrl", [sub, can, ufl, pin], "Espressif ESP32-S3-MINI-1U")


def polymer_3528() -> None:
    """A polymer capacitor in the EIA 3528 (B) case, KEMET T520B: a black moulding 3.5 x 2.8 x 1.9 mm
    with a grey band over its anode (pad 1, the footprint's left end), on 2 tinned end caps."""
    body, band, cap = Mesh(DARK), Mesh((0.45, 0.45, 0.48)), Mesh((0.75, 0.75, 0.78))
    box(body, 0.0, 0.0, 0.1, 2.9, 2.8, 1.8)
    box(band, -1.05, 0.0, 1.9, 0.5, 2.8, 0.01)
    for x in (-1.6, 1.6):
        box(cap, x, 0.0, 0.0, 0.5, 2.2, 0.9)
    write_wrl(HERE / "polymer_3528.wrl", [body, band, cap], "KEMET T520B polymer capacitor, 3528")


# KiCad's PT 1,5 body is green; the board's terminals are the black variant ("BK"). The library's
# STEP, with its body colour (the only green in the file) made black and its licence kept.
PT15_GREEN = "COLOUR_RGB('',0.339999993741,0.679999990811,0.445000007484)"
PT15_BLACK = "COLOUR_RGB('',0.11,0.11,0.12)"


def black_terminals() -> None:
    """The 2-, 3- and 4-way PT 1,5 3.5 mm bodies from KiCad's library, recoloured black, as
    `pt15_<n>_bk.step`. The library's files are CC-BY-SA 4.0; so are these."""
    root = os.environ.get("KICAD10_3DMODEL_DIR")
    if not root:
        print("KICAD10_3DMODEL_DIR is not set: the terminal bodies are left as they are")
        return
    for n in (2, 3, 4):
        name = f"TerminalBlock_Phoenix_PT-1,5-{n}-3.5-H_1x{n:02d}_P3.50mm_Horizontal.step"
        text = (Path(root) / "TerminalBlock_Phoenix.3dshapes" / name).read_text()
        if text.count(PT15_GREEN) != 1:
            raise SystemExit(f"{name}: the body colour is not the one this script knows")
        # The note goes inside the header: a STEP file starts with its ISO line.
        note = f"/* Recoloured from KiCad's {name}: the body black (PT 1,5 ... BK). CC-BY-SA 4.0, as below. */\n"
        text = text.replace("HEADER;\n", "HEADER;\n" + note, 1).replace(PT15_GREEN, PT15_BLACK)
        (HERE / f"pt15_{n}_bk.step").write_text(text)


if __name__ == "__main__":
    bg95()
    esp32_s3_mini_1u()
    polymer_3528()
    black_terminals()
    print(f"wrote 3 bodies into {HERE}, with {wrlgen.__name__}")
