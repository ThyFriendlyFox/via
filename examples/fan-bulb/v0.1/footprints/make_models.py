#!/usr/bin/env python3
"""Lark's 3D bodies for the parts KiCad's 3D library has none for, as VRML in each board's models/.

KiCad's library names a body for ESP32-C6-MINI-1, LED_PLCC_2835, Knowles_LGA-5_3.5x2.65mm and
L_Bourns_SDR0604 but holds no file for any of them; the project's own footprints (make_footprints.py)
name none. Each body here is the part's size from its datasheet, in the footprint's frame (wrlgen:
X right, Y toward the footprint's top, Z up out of the board), for the renders and the assembly.

    PYTHONPATH=<workcenter>/tools python3 footprints/make_models.py     # from the version's folder

Each design attaches its bodies with `d.model(ref, "${KIPRJMOD}/models/<name>.wrl", replace=True)`.
"""

from __future__ import annotations

import math
from pathlib import Path

import wrlgen as w

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
RESIN = (0.93, 0.93, 0.90)
PHOSPHOR = (0.98, 0.86, 0.35)
FERRITE = (0.16, 0.16, 0.17)
COPPER = (0.72, 0.45, 0.20)
SLEEVE = (0.12, 0.20, 0.45)  # Nichicon ULD's sleeve
CAN_TOP = (0.70, 0.70, 0.72)
CERAMIC = (0.36, 0.30, 0.24)
SOLDER = (0.80, 0.80, 0.82)
MODULE_PCB = (0.10, 0.10, 0.12)


def esp32_c6_mini_1() -> list[w.Mesh]:
    """Espressif ESP32-C6-MINI-1: 13.2 x 16.6 x 2.4 mm (datasheet v1.3, Module Dimensions). On
    KiCad's footprint the module spans y -11 to 5.6, the antenna's bare board is y -11 to -5.6, and
    the can covers the rest. In wrlgen's frame y is the footprint's -y."""
    pcb, shield = w.Mesh(MODULE_PCB), w.Mesh(SOLDER)
    w.box(pcb, 0.0, 2.7, 0.0, 13.2, 16.6, 0.8)
    w.box(shield, 0.0, 0.0, 0.8, 12.6, 10.6, 1.6)
    return [pcb, shield]


def led_2835() -> list[w.Mesh]:
    """A 2835 PLCC LED: 3.5 x 2.8 x 0.8 mm, the window 2.6 x 2.2 mm on top."""
    body, window = w.Mesh(RESIN), w.Mesh(PHOSPHOR)
    w.box(body, 0.2, 0.0, 0.0, 3.5, 2.8, 0.78)
    w.box(window, 0.2, 0.0, 0.78, 2.6, 2.2, 0.02)
    return [body, window]


def knowles_lga() -> list[w.Mesh]:
    """Knowles SPH0641LU4H-1: 3.50 x 2.65 x 0.98 mm (datasheet rev. B), the long side along the
    footprint's y; a laminate base under a metal lid."""
    base, lid = w.Mesh((0.30, 0.42, 0.20)), w.Mesh(SOLDER)
    w.box(base, 0.0, 0.0, 0.0, 2.65, 3.50, 0.30)
    w.box(lid, 0.0, 0.0, 0.30, 2.55, 3.40, 0.68)
    return [base, lid]


def sdr0604() -> list[w.Mesh]:
    """Bourns SDR0604: a drum core 5.8 mm across and 4.5 mm tall on its terminals (datasheet)."""
    core, wire = w.Mesh(FERRITE), w.Mesh(COPPER)
    w.cylinder(core, 0.0, 0.0, 0.0, 2.9, 0.6)
    w.cylinder(wire, 0.0, 0.0, 0.6, 2.6, 3.3)
    w.cylinder(core, 0.0, 0.0, 3.9, 2.9, 0.6)
    return [core, wire]


def along_y(m: w.Mesh, r: float, y0: float, y1: float, z: float, n: int = 40) -> None:
    """A closed cylinder of radius r on an axis along y, from y0 to y1, its axis z above the board."""
    ring0 = [m.vertex(r * math.cos(2 * math.pi * k / n), y0, z + r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    ring1 = [m.vertex(r * math.cos(2 * math.pi * k / n), y1, z + r * math.sin(2 * math.pi * k / n)) for k in range(n)]
    for k in range(n):
        j = (k + 1) % n
        m.face(ring0[k], ring0[j], ring1[j], ring1[k])
    m.face(*reversed(ring0))
    m.face(*ring1)


def cap_lying(d: float = 8.0, length: float = 11.5, pitch: float = 3.5) -> list[w.Mesh]:
    """Nichicon ULD 8 x 11.5 mm laid on the board (make_footprints.lying_cap): its leads rise from
    the holes to the can's axis, the can lies along the footprint's +y (wrlgen's -y) from 1.0 mm."""
    can, top, lead = w.Mesh(SLEEVE), w.Mesh(CAN_TOP), w.Mesh(SOLDER)
    r = d / 2
    along_y(can, r, -1.0, -(1.0 + length), r)
    along_y(top, r - 0.4, -(1.0 + length), -(1.5 + length), r)  # the vent end, past the sleeve
    for x in (-pitch / 2, pitch / 2):
        w.cylinder(lead, x, 0.0, 0.0, 0.3, r)
        w.box(lead, x, -0.5, r - 0.3, 0.6, 1.0, 0.6)
    return [can, top, lead]


def varistor_cu3225() -> list[w.Mesh]:
    """TDK (EPCOS) CU3225K150G2: 8.0 x 6.3 x 3.2 mm, a terminal at each end (SIOV CU catalog)."""
    body, ends = w.Mesh(CERAMIC), w.Mesh(SOLDER)
    w.box(body, 0.0, 0.0, 0.0, 6.4, 6.3, 3.2)
    for x in (-3.6, 3.6):
        w.box(ends, x, 0.0, 0.0, 0.8, 6.3, 3.2)
    return [body, ends]


BODIES = {
    "brain/models/esp32_c6_mini_1.wrl": (esp32_c6_mini_1, "ESP32-C6-MINI-1, 13.2 x 16.6 x 2.4 mm"),
    "light/models/led_2835.wrl": (led_2835, "2835 PLCC LED, 3.5 x 2.8 x 0.8 mm"),
    "ear/models/sph0641lu4h_1.wrl": (knowles_lga, "Knowles SPH0641LU4H-1, 3.50 x 2.65 x 0.98 mm"),
    "driver/models/sdr0604.wrl": (sdr0604, "Bourns SDR0604, 5.8 x 4.5 mm"),
    "driver/models/cap_lying_d8_l11.5.wrl": (cap_lying, "Nichicon ULD 8 x 11.5 mm, lying"),
    "driver/models/cu3225.wrl": (varistor_cu3225, "TDK CU3225K150G2, 8.0 x 6.3 x 3.2 mm"),
}


def main() -> None:
    for rel, (make, what) in BODIES.items():
        path = ROOT / rel
        nv, nf = w.write_wrl(path, make(), what)
        print(f"wrote {path.relative_to(ROOT)}: {nv} vertices, {nf} faces")


if __name__ == "__main__":
    main()
