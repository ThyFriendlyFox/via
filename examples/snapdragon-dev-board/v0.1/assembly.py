#!/usr/bin/env python3
"""Wyvern v0.1 assembly: the routed carrier with the Snapdragon module on its 3 sockets.

The Lantronix Open-Q 845 uSOM stands 3.0 mm above the board's top face on the DF40HC(3.0)
receptacles (its datasheet, 6.3), turned 180 degrees as `design.py` turns its land pattern, its
Wi-Fi shield over the right end and its 2 U.FL antenna sockets at the far corner. The module's body
is `models/open_q_845.wrl`. None of this changes the copper. The scene, the bodies the board names,
the renders and the GIF come from the EE Workcenter's `tools/scene.py`; this file holds only
Wyvern's placement.

    workcenter design design.py --route    # the routed board this reads
    workcenter pictures .                  # runs this with the workcenter's tools/ on PYTHONPATH

Writes build/assembly/: the scene's bodies, wyvern_assembly.kicad_pcb, the images
assembly-{iso,top,bottom,end}.png and assembly-spin.gif, the assembly turning round once.
"""

from __future__ import annotations

import scene

# The module's centre on the board (design.py's SOM_X0 and CY) and its height: the gap the 3.0 mm
# stack leaves between the two boards.
SOM_CENTRE = (110.1 + 25.0, 115.24)
STACK = 3.0
VIEWS = {
    "assembly-iso": {"rotate": "-58,0,32", "perspective": True, "zoom": 0.85, "pivot": "0,0,0.25"},
    "assembly-top": {"zoom": 0.95},
    "assembly-bottom": {"side": "bottom", "zoom": 0.95},
    "assembly-end": {"rotate": "-90,0,-90", "zoom": 1.3, "pivot": "0,0,0.25"},  # the USB-C end
}

s = scene.Scene("wyvern.kicad_pcb", out="build/assembly", name="wyvern_assembly")
s.place(s.copy("models/open_q_845.wrl"), (*SOM_CENTRE, STACK), rotate=(0.0, 0.0, 180.0))
s.stills(VIEWS)
s.spin("assembly-spin.gif", tilt=-60, zoom=0.8, pivot="0,0,0.3")
