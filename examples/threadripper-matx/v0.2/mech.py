"""Basalt's mechanics: the microATX outline, its holes and slots, and where each big part sits.

One frame for everything, the way the board is photographed: seen from the component side, the
rear I/O edge on the left, the expansion slots across the bottom. u runs right and v runs down, in
millimetres from the board's top left corner. `at(u, v)` gives board coordinates (the design's
outline starts at ORIGIN).

The numbers come from the ATX 2.2 and PCI Express CEM 4.0 drawings (figures 2-5, 86 and 87), which
place a microATX board's holes, slots and I/O aperture from hole B. Those drawings put the rear edge
at the top; turned to this frame, a drawing point (x, y) is (y, 243.84 - x) here. Numbers that no
drawing gave are marked as estimates where they are set.
"""

from __future__ import annotations

W = H = 243.84  # 9.6 x 9.6 in
ORIGIN = (20.0, 20.0)


def at(u: float, v: float) -> tuple[float, float]:
    return (round(ORIGIN[0] + u, 4), round(ORIGIN[1] + v, 4))


# ---- mounting holes, 3.96 mm (0.156 in), ATX 2.2 fig. 2 and 3 --------------------------------------
HOLES = {
    "F": (33.02, 6.35),
    "J": (165.10, 6.35),
    "M": (237.49, 6.35),
    "C": (10.16, 163.83),
    "H": (165.10, 163.83),
    "L": (237.49, 163.83),
    "B": (10.16, 209.55),
    "S": (165.10, 209.55),
    "R": (165.10, 229.87),
}
HOLE_KEEPOUT = 5.08  # half the 0.400 in square kept clear round each hole (ATX 2.2 3.4.2)

# ---- expansion slots: 4 positions 20.32 mm apart, CEM 4.0 fig. 86 ------------------------------------
SLOT_V = {1: 162.255, 2: 182.575, 3: 202.895, 4: 223.215}  # connector centrelines
PCIE_PEG_U = 57.099  # datum Z: the key's alignment hole; pin A1/B1 is 11.65 mm toward the rear edge
PCIE_BODY = (42.599, 131.599)  # the x16 body along u
PCIE_HALF_W = 3.75  # the body is 7.50 wide

# ---- the rear I/O aperture, 158.75 x 44.45 mm, ATX 2.2 fig. 4 ------------------------------------------
IO_APERTURE = (-2.44, 156.31)  # along v, at the left edge
IO_FACE_U = -1.14  # the connectors' faces stand 1.14 mm proud of the edge (ATX 2.2 fig. 5)
CARD_AREA_V = 157.48  # below this line the parts stand at most 15.24 mm (the cards' area)

# ---- the processor: sTR5, LGA 4844, a 58.5 x 75.4 mm package ------------------------------------------
# Its long side runs along v, as on the TRX50 boards, so 2 memory channels leave from each side.
CPU = (110.0, 85.0)  # the package centre
PACKAGE = (58.5, 75.4)
# The contacts: an interstitial array 0.94 mm along a row, rows 0.81 mm apart. A secondary source
# (the SP5/SP6 family's figure); AMD's socket drawing is under NDA.
PITCH_A, PITCH_H = 0.94, 0.81
CONTACTS = 4844
# The socket's housing and its rail frame, and the 4 holes its cooler bracket uses: estimates. The TR4
# family's cooler pattern is reported as 105 mm by 65.2 and 46 (a secondary source); the holes here
# are 105 by 46 on both sides, which keeps them out of the memory buses beside the socket.
HOUSING = (66.0, 84.0)
FRAME = (78.0, 100.0)
COOLER_HOLES = [(-23.0, -52.5), (23.0, -52.5), (-23.0, 52.5), (23.0, 52.5)]  # from CPU, mm

# ---- memory: 4 DDR5 RDIMM slots, 2 each side of the socket, 1 per channel -------------------------------
# Amphenol DDR516112010E, SMT, drawing C-DDR516 rev 5: 142 mm long, 6.10 wide, 21.3 tall.
DIMM_PITCH = 10.16  # 0.4 in between slot centrelines (an estimate: a common desktop spacing)
DIMM_NEAR = 43.3  # from the processor's centre to the nearer slot's centreline
DIMM_V = 84.1  # the slots' centre along v: clear of the EPS connectors above and of a row of capacitors over slot 1
DIMMS = {
    "A": CPU[0] - DIMM_NEAR,  # channel A, left, near
    "B": CPU[0] - DIMM_NEAR - DIMM_PITCH,  # channel B, left, far
    "C": CPU[0] + DIMM_NEAR,  # channel C, right, near
    "D": CPU[0] + DIMM_NEAR + DIMM_PITCH,  # channel D, right, far
}

# ---- M.2: Foxconn 2E0BC2*-S64BM, 2280 standoff 78.25 mm from the connector's peg axis -----------------
M2_STANDOFF = 78.25
M2_1 = (131.0, SLOT_V[2])  # in slot 2's place, the connector at the slots' right end
M2_2 = (160.0, 186.7)  # right of the slots, between holes H and S
