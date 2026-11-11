# Basalt — a microATX board for Threadripper

A workstation motherboard for an AMD Threadripper 7000 or 9000 on the sTR5 socket (the TRX50
platform), on a microATX board: 244 x 244 mm. No microATX TRX50 board has been made; the smallest is
ATX. Basalt fits the platform's 4 memory channels, its 48 PCI Express 5.0 lanes and a 350 W
processor into the smaller form, 2 memory slots each side of the socket.

This folder is a prototype series made with the EE Workcenter, laid out the way a board repository
lays out its versions (`PROCESSES.md` P22). Each version is its own folder and a whole KiCad project:
`design.py` and the modules beside it are the board, the `.kicad_*` files are what
`workcenter design` writes from them, and its README holds the spec, the decisions and what changed.
Each version adds one thing and is GREEN before the next starts.

## Versions

| Version | Board | What changed | Commit |
|---|---|---|---|
| [v0.1](v0.1/) | 244 x 244 mm, 10 layers | the floor plan: every big part where the microATX drawings put it, the processor's 4844 lands, power in, 14 phases of power stages, the planes | `4c25dc0` |
| [v0.2](v0.2/) (current) | as v0.1 | the DDR5 buses: 576 traces from the processor's lands to its 4 slots, drawn by rule | in work |

The commit is where that version was finished; its folder holds the files from that commit.

## Working on the boards

From this folder, name the version's folder:

```sh
workcenter design v0.2/design.py                                         # the KiCad project from the design
workcenter gates v0.2                                                    # ERC, DRC, SIM, EXPORT
workcenter pictures v0.2                                                 # the renders into v0.2/docs/
workcenter version new . v0.3                                            # the next version's folder (P22)
```

The renders need KiCad's 3D bodies for the library parts the board names:
`python3 v0.2/models/fetch_library_bodies.py v0.2/basalt.kicad_pcb ~/kicad-bodies`, then
`export KICAD10_3DMODEL_DIR=~/kicad-bodies`.
