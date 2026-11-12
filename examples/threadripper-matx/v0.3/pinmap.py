"""The processor's contacts: 4844 lands in an interstitial array, and what each one carries.

AMD's sTR5 pin map is under NDA. This one is a stand-in, laid out the way a processor's is: each
memory channel on the side of the package nearest its slot, the PCI Express lanes on the side
nearest the expansion slots, the slow signals on the far side, and the power and ground lands in
the middle. A licensee replaces `assign()` with AMD's table; the footprint, the symbol and the
routes are written from whatever it returns.

The array: rows run along u, 0.94 mm apart along a row, rows 0.81 mm apart, every other row offset
by half a pitch. The routing plan sets which land carries what:

- Left and right bands, 5 columns deep: the 4 memory channels. A trace leaves a land of column k on
  layer k (F.Cu, In2, In3, In6) through the gap between 2 rows; every via sits on a land, never in
  a gap, so each gap carries 1 trace on every layer. Column 4 is ground, the bands' return.
- Bottom band, 8 rows deep: the PCI Express lanes. Rows 0 and 1 leave on F.Cu between the lands of
  the row below; rows 2 and 3 on In2; each deeper row on a layer of its own, zig-zagging between the
  vias of the rows outside it.
- Top band: the slow signals, for the router.
- The core: VDDCR_CPU and ground in alternate lands, VDDCR_SOC and VDD_18 in blocks.
"""

from __future__ import annotations

from dataclasses import dataclass

import mech

ROWS, COLS = 89, 57
A, H = mech.PITCH_A, mech.PITCH_H
LANE_COLS = 5  # the memory bands' depth, in columns
BOTTOM_ROWS = 8  # the PCI Express band's depth, in rows
TOP_ROWS = 6
# The layer a memory land of column k leaves on, and a PCI Express land of bottom row k.
DDR_LAYERS = ("F.Cu", "In2.Cu", "In3.Cu", "In6.Cu")
PCIE_LAYERS = ("F.Cu", "F.Cu", "In2.Cu", "In2.Cu", "In3.Cu", "In6.Cu", "In7.Cu", "B.Cu")
LETTERS = "ABCDEFGHJKLMNPRTUVWY"  # JEDEC row names: no I, O, Q, S, X or Z


def row_name(r: int) -> str:
    if r < len(LETTERS):
        return LETTERS[r]
    return LETTERS[r // len(LETTERS) - 1] + LETTERS[r % len(LETTERS)]


def land_name(r: int, c: int) -> str:
    return f"{row_name(r)}{c + 1}"


def land_uv(r: int, c: int) -> tuple[float, float]:
    """A land's centre from the package centre, mm: u along a row, v down the rows."""
    off = A / 4 if r % 2 else -A / 4
    return ((c - (COLS - 1) / 2) * A + off, (r - (ROWS - 1) / 2) * H)


def _corner(r: int, c: int, k: int) -> bool:
    """In a corner's chamfer: k lands across, counted from both edges."""
    dr = min(r, ROWS - 1 - r)
    dc = min(c, COLS - 1 - c)
    return dr + dc < k


CHAMFER = 3  # lands cut from each corner, pin 1's twice as deep: the package's orientation mark


def present() -> list[tuple[int, int]]:
    """The 4844 lands: the full array less a chamfer at each corner and a window in the middle, where
    a package carries capacitors on its land side. The chamfers stay small: the memory bands need
    72 lands in each of their columns."""
    full = [(r, c) for r in range(ROWS) for c in range(COLS)]
    kept = [
        (r, c) for r, c in full
        if not _corner(r, c, CHAMFER) and not (r + c < 2 * CHAMFER)
    ]
    extra = len(kept) - mech.CONTACTS
    cr, cc = (ROWS - 1) / 2, (COLS - 1) / 2
    # The window: the lands nearest the centre, measured so that it comes out as tall as the core.
    order = sorted(kept, key=lambda rc: (((rc[0] - cr) / 2.2) ** 2 + (rc[1] - cc) ** 2, rc))
    drop = set(order[:extra])
    out = [rc for rc in kept if rc not in drop]
    assert len(out) == mech.CONTACTS, len(out)
    return out


@dataclass
class Land:
    r: int
    c: int
    name: str
    u: float  # from the package centre
    v: float
    role: str  # "ddr", "pcie", "top", "rail", "nc"
    side: str = ""  # "L", "R" (ddr), "B" (pcie), "T"
    depth: int = 0  # columns or rows from the band's edge
    net: str = ""  # a rail's name, or the signal assign() gave it


def lands() -> list[Land]:
    out = []
    for r, c in present():
        u, v = land_uv(r, c)
        name = land_name(r, c)
        if c < LANE_COLS:
            out.append(Land(r, c, name, u, v, "ddr", "L", c))
        elif c >= COLS - LANE_COLS:
            out.append(Land(r, c, name, u, v, "ddr", "R", COLS - 1 - c))
        elif r >= ROWS - BOTTOM_ROWS:
            out.append(Land(r, c, name, u, v, "pcie", "B", ROWS - 1 - r))
        elif r < TOP_ROWS:
            out.append(Land(r, c, name, u, v, "top", "T", r))
        else:
            out.append(Land(r, c, name, u, v, "rail"))
    for land in out:
        if land.role == "rail":
            land.net = core_rail(land.r, land.c)
        elif land.role == "ddr" and land.depth == LANE_COLS - 1:
            land.role, land.net = "rail", "GND"
    return out


def core_rail(r: int, c: int) -> str:
    """The middle: VDD_18 and VDD_33 in solid blocks at the top corners and VDDIO_MEM in a solid block
    beside each memory band, each block under a pour of its own on the back; VDDCR_SOC in a band under
    the slow signals and VDDCR_CPU everywhere else, each on alternate lands with ground between, so
    every one of their lands has a ground land beside it."""
    if r < TOP_ROWS + 4 and c < LANE_COLS + 6:
        return "VDD_18"
    if r < TOP_ROWS + 4 and c >= COLS - LANE_COLS - 6:
        return "VDD_33"
    if 30 <= r <= 58 and (c < LANE_COLS + 3 or c >= COLS - LANE_COLS - 3):
        return "VDDIO_MEM"
    if (r + c) % 2 == 0 or r >= ROWS - BOTTOM_ROWS - 3:
        return "GND"
    if r < TOP_ROWS + 14:
        return "VDDCR_SOC"
    return "VDDCR_CPU"


# The rails this version carries; a land of any other is left unnumbered, off the symbol and with no
# via. The small rails come with their regulators.
ACTIVE_RAILS = ("GND", "VDDCR_CPU", "VDDCR_SOC")


RAILS = ("VDDCR_CPU", "VDDCR_SOC", "VDDIO_MEM", "VDD_18", "VDD_33", "GND")


def land_net(land: Land, assigned: dict[str, str]) -> str:
    """The net a land carries: its rail's (when this version carries the rail), its signal's, ground
    for a memory land no trace takes (the bands' return path), or none."""
    if land.role == "rail":
        return land.net if land.net in ACTIVE_RAILS else ""
    if land.name in assigned:
        return assigned[land.name]
    return "GND" if land.role == "ddr" else ""


def ddr_lands(side: str, depth: int) -> list[Land]:
    """The memory lands of one band at one depth, top to bottom."""
    return sorted((x for x in lands() if x.role == "ddr" and x.side == side and x.depth == depth), key=lambda x: x.r)


if __name__ == "__main__":
    ls = lands()
    from collections import Counter

    print(len(ls), Counter(x.role for x in ls), Counter(x.net for x in ls if x.role == "rail"))
    print("rows", ROWS, "cols", COLS, "span u", round(land_uv(0, COLS - 1)[0] - land_uv(0, 0)[0], 2),
          "span v", round(land_uv(ROWS - 1, 0)[1] - land_uv(0, 0)[1], 2))


def assign() -> dict[str, str]:
    """Each signal land's net, by land name. The buses fill this in as they are routed (buses.py);
    a land not in it is left unnumbered on the footprint and off the symbol."""
    import buses  # noqa: PLC0415  the routes decide which land carries which signal

    return buses.land_nets()


def symbol(assigned: dict[str, str]) -> str:
    """The processor's symbol: a bank for its supplies and a bank for each interface's signals."""
    from make_symbols import banked  # noqa: PLC0415

    rails = [{"number": r, "name": r, "type": "power_in"} for r in ACTIVE_RAILS]
    banks = [("SUPPLIES", rails[: (len(rails) + 1) // 2], rails[(len(rails) + 1) // 2 :])]
    groups: dict[str, list[dict]] = {}
    for land, net in sorted(assigned.items(), key=lambda kv: kv[1]):
        groups.setdefault(net.split("_")[0], []).append({"number": land, "name": net, "type": "bidirectional"})
    for title, items in groups.items():
        for i in range(0, len(items), 80):
            part = items[i : i + 80]
            half = (len(part) + 1) // 2
            banks.append((f"{title} {i // 80 + 1}" if len(items) > 80 else title, part[:half], part[half:]))
    return banked("sTR5_STANDIN", "U", banks, 5, "Basalt:sTR5_LGA4844",
                  "AMD Threadripper (sTR5) socket; the pin map is a stand-in, AMD's is under NDA")
