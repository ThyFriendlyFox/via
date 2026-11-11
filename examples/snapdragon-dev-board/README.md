# Wyvern — prototype series

A development board the size of a Teensy with a Snapdragon on it. A Snapdragon 845 (8 Kryo cores
to 2.65 GHz, an Adreno 630, 4 GB of LPDDR4X, 32 GB of UFS, Wi-Fi 5 and Bluetooth 5) runs Linux or
Android on a module that plugs into the top of a 61 x 30.5 mm stick; an RP2350 under it drives 30
pins at 3.3 V the way a Teensy's microcontroller does, and the Snapdragon resets it, flashes it and
talks to it over USB. One USB-C cable powers the board and carries USB 3.1 and a DisplayPort
monitor.

This folder is the hardware. Each prototype is its own folder, and each folder is a whole KiCad
project: `design.py`, the generated `.kicad_*` files, its footprints, symbols and 3D models, its
README with the spec, pin plan, BOM and decisions, its images under `docs/`, its simulation decks
under `sim/`. It is laid out the way a board repository is (compare
[thyfriendlyfox/vape-prototype](https://github.com/ThyFriendlyFox/vape-prototype)), and it is the
EE Workcenter's example of what a design file can make: the workcenter, this repository's `tools/`,
supplies the tools and gates; this folder supplies the board.

The latest version, [v0.1](v0.1/), with the Snapdragon module on its sockets
([`v0.1/assembly.py`](v0.1/assembly.py), `workcenter pictures v0.1`):

<img src="v0.1/docs/assembly-spin.gif" width="616" alt="Wyvern v0.1 with the Open-Q 845 module on top, turning">

| The carrier, from above | From below: the pins named, the power, the microSD |
|---|---|
| <img src="v0.1/docs/board-spin.gif" width="300" alt="the carrier turning, from above"> | <img src="v0.1/docs/board-spin-bottom.gif" width="300" alt="the carrier turning, from below"> |

## Versions

| Version | Board | What it is | Firmware | Commit |
|---|---|---|---|---|
| [v0.1](v0.1/) (current) | 60.96 x 30.48 mm, 6 layers, 1.6 mm; 2 rows of 24 pins 1.1 inch apart | the first board: the Open-Q 845 uSOM on 3 DF40 sockets, USB-C with USB 3.1 and DisplayPort, a 3 A buck for the module, an RP2350 on the pins, a microSD slot | no | in work |

The commit is where that version was finished; its folder holds the files from that commit.

## The folders

| Folder | Holds |
|---|---|
| [`v0.1/`](v0.1/) | the board: `design.py` and what it generates, `sim/`, `docs/`, `assembly.py` |
| [`parts/`](parts/) | an orderable part for every line (`catalog.csv`), what is off the board (`offboard/`), the priced lists |
| [`CLAUDE.md`](CLAUDE.md) | the commands, for an agent or a person working on the series |
