"""The constructive routes of the board's buses: DDR5 to the 4 slots, PCI Express to the 3 slots and
the 2 M.2 sockets. Each bus is drawn as tracks and vias from the processor's lands to its connector,
and the lands it starts from are the pin map (pinmap.assign()).
"""

from __future__ import annotations


def land_nets() -> dict[str, str]:
    """Land name -> net of every signal land a bus starts from."""
    return {}
