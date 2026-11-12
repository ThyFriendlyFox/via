"""The board's heatsinks and covers: where each screws down and the body it carries.

Each one's footprint is its screws' holes (footprints/make_footprints.py); its body is drawn by
models/make_models.py. Positions are in mech.py's frame (u right, v down, from the board's top left
corner); a footprint's origin is its first hole.

- VRM top: over the 4 phases above the socket.
- VRM left and the I/O cover: one piece over the 10 phases left of the memory and the rear connectors.
- M.2: a finned plate over each drive.
"""

from __future__ import annotations

HEATSINKS = {
    "Heatsink_VRM_Top": {
        "descr": "Aluminium heatsink over the 4 phases above the socket, 2 M3 screws",
        "holes_uv": [(110.0, 31.0), (134.0, 8.0)],  # below the chokes, between the cooler holes; past the row
        "box_uv": (82.5, 1.5, 136.5, 33.5),  # the body's footprint on the board
        "base": 10.6,  # its underside, over the chokes
        "top": 36.0,
    },
    "Heatsink_VRM_Left": {
        "descr": "Aluminium heatsink over the 10 phases left of the memory, merged with the rear I/O cover, 2 M3 screws",
        "holes_uv": [(46.5, 16.2), (46.5, 150.0)],
        "box_uv": (-1.0, 12.0, 52.0, 152.0),
        "base": 10.6,
        "top": 42.0,
    },
}


def holes(name: str) -> list[tuple[float, float]]:
    """A heatsink's holes from its own origin (its first hole), in KiCad's frame (y down)."""
    pts = HEATSINKS[name]["holes_uv"]
    u0, v0 = pts[0]
    return [(round(u - u0, 4), round(v - v0, 4)) for u, v in pts]


for _name, _spec in HEATSINKS.items():
    _spec["holes"] = holes(_name)
