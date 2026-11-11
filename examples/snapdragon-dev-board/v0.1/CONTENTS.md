# v0.1: contents

What this folder holds, for Wyvern — board prototype v0.1. Made by `workcenter docs v0.1` from the folder itself, the version's parts lists and `library/sources.csv`; run it again after a change.

## Read first

- [README.md](README.md): the version's spec, pin plan, BOM, decisions and open items.
  - [Images](README.md#images)
  - [What changed in v0.1: the first board](README.md#what-changed-in-v01-the-first-board)
  - [Architecture](README.md#architecture)
  - [The Snapdragon module](README.md#the-snapdragon-module)
  - [Power](README.md#power)
  - [USB-C](README.md#usb-c)
  - [The RP2350](README.md#the-rp2350)
  - [Pin plan](README.md#pin-plan)
  - [Datasheets, models and simulation](README.md#datasheets-models-and-simulation)
  - [Bill of materials](README.md#bill-of-materials)
  - [Working on this board](README.md#working-on-this-board)
  - [Decisions](README.md#decisions)
  - [Open items](README.md#open-items)
- [docs/gates.md](docs/gates.md): the gates report: ERC, DRC, simulation, export.

## Design

- The base board:
  - [design.py](design.py): the source of truth; the KiCad files are generated from it
  - [fp-lib-table](fp-lib-table): footprint libraries
  - [sym-lib-table](sym-lib-table): symbol libraries
  - [wyvern.kicad_dru](wyvern.kicad_dru): custom design rules (the fab's)
  - [wyvern.kicad_pcb](wyvern.kicad_pcb): board
  - [wyvern.kicad_pro](wyvern.kicad_pro): KiCad project
  - [wyvern.kicad_sch](wyvern.kicad_sch): schematic
  - [footprints/](footprints/): project footprints, 3 files
  - [symbols/](symbols/): project symbols, 2 files
  - [models/](models/): 3D bodies, 6 files
- [assembly.py](assembly.py): the assembly: the Snapdragon module on its 3 sockets.
- [open_q_845.py](open_q_845.py): The Lantronix Open-Q 845 uSOM: its 3 board-to-board connectors and where they sit.

## Simulation

- [sim/mcu_control.cir](sim/mcu_control.cir), bounds in [sim/mcu_control.expect.json](sim/mcu_control.expect.json): The Snapdragon resets the RP2350 and puts it in its bootloader through U6 and U7, 74LVC1G07 open-drain
- [sim/som_i2c.cir](sim/som_i2c.cir), bounds in [sim/som_i2c.expect.json](sim/som_i2c.expect.json): The Snapdragon's I2C on the pins (SOM_I2C_SDA, SOM_I2C_SCL: QUP10 on JT2 pins 68 and 70, the header's
- [sim/sys_rail_high.cir](sim/sys_rail_high.cir), bounds in [sim/sys_rail_high.expect.json](sim/sys_rail_high.expect.json): SOM_SYS at its highest: the TPS62130's reference at 822.4 mV (SLVSAG7F, 6.5) and 100 nA drawn into
- [sim/sys_rail_low.cir](sim/sys_rail_low.cir), bounds in [sim/sys_rail_low.expect.json](sim/sys_rail_low.expect.json): SOM_SYS, the Snapdragon module's supply (SOM_SYS_PWR on JT2), from the TPS62130 (U2) set by R1 374k
- [sim/vbus_pdn.cir](sim/vbus_pdn.cir), bounds in [sim/vbus_pdn.expect.json](sim/vbus_pdn.expect.json): VBUS, the 5 V input, as the TPS62130 (U2) draws from it: a USB-C charger behind its cable, and C1
- [sim/vbus_psm.cir](sim/vbus_psm.cir), bounds in [sim/vbus_psm.expect.json](sim/vbus_psm.expect.json): The TPS62130 (U2) in power save, its pulses at the resonance of the USB cable with C1 and C2

## Pictures and reports

- [pictures.json](pictures.json): what `workcenter pictures` draws and copies into docs/
- [docs/gates.md](docs/gates.md)

## Parts

- The base board's priced parts list: [../parts/lists/v0.1.md](../parts/lists/v0.1.md)

## Datasheets

Each part's datasheet as its maker publishes it, copied from [`../library/`](../library/) into [`datasheets/`](datasheets/); [`../library/sources.csv`](../library/sources.csv) records where each came from, its revision and its SHA256. A part with no file says why.

| Board | Refs | Part | Datasheet | Revision |
|---|---|---|---|---|
| base | C1,C2 | Murata GRM21BR61C106KE15L | none kept: no row in `../library/sources.csv` |  |
| base | C3-C5 | Murata GRM21BR61A226ME51L | none kept: no row in `../library/sources.csv` |  |
| base | C6 | Murata GRM155R71H332KA01D | none kept: no row in `../library/sources.csv` |  |
| base | C7,C8 | Murata GRM155R61A105KE15D | none kept: no row in `../library/sources.csv` |  |
| base | C9-C11 | Murata GRM155R61A475MEAAD | none kept: no row in `../library/sources.csv` |  |
| base | C12-C19,C22,C24 | Murata GRM155R71C104KA88D | none kept: no row in `../library/sources.csv` |  |
| base | C20,C21 | Murata GRM1555C1H150JA01D | none kept: no row in `../library/sources.csv` |  |
| base | C23 | Murata GRM188R61A475KE15D | none kept: no row in `../library/sources.csv` |  |
| base | D1 | Lite-On LTST-C191KRKT | none kept: no row in `../library/sources.csv` |  |
| base | D2,D4 | Lite-On LTST-C191KGKT | none kept: no row in `../library/sources.csv` |  |
| base | D3 | Lite-On LTST-C191TBKT | none kept: no row in `../library/sources.csv` |  |
| base | J1-J3 | Hirose DF40HC(3.0)-100DS-0.4V(51) | none kept: no row in `../library/sources.csv` |  |
| base | J4 | Amphenol ICC 12401610E4#2A | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. Amphenol's USB Type-C cut sheet: the receptacle's land pattern and the 9.59 mm from its face to its pegs; 0.6 MB |  |
| base | J5,J6 | Sullins PRPC024SAAN-RC | none kept: no row in `../library/sources.csv` |  |
| base | J7 | Molex 1040310811 | none kept: no row in `../library/sources.csv` |  |
| base | L1 | Coilcraft XAL4020-222MEB | none kept: no row in `../library/sources.csv` |  |
| base | L2 | Abracon AOTA-B201610S3R3-101-T | none kept: no row in `../library/sources.csv` |  |
| base | R1 | YAGEO RC0402FR-07374KL | none kept: no row in `../library/sources.csv` |  |
| base | R2,R10,R11,R14,R23 | YAGEO RC0402FR-07100KL | none kept: no row in `../library/sources.csv` |  |
| base | R3 | YAGEO RC0402FR-0733RL | none kept: no row in `../library/sources.csv` |  |
| base | R4,R8 | YAGEO RC0402FR-0710KL | none kept: no row in `../library/sources.csv` |  |
| base | R5,R9,R12,R13 | YAGEO RC0402FR-071KL | none kept: no row in `../library/sources.csv` |  |
| base | R6,R7 | YAGEO RC0402FR-0727RL | none kept: no row in `../library/sources.csv` |  |
| base | R15 | YAGEO RC0402JR-070RL | none kept: no row in `../library/sources.csv` |  |
| base | R16,R17 | YAGEO RC0402FR-072K2L | none kept: no row in `../library/sources.csv` |  |
| base | R18-R22 | YAGEO RC0402FR-0747KL | none kept: no row in `../library/sources.csv` |  |
| base | SW1 | C&K KMR221GLFS | none kept: no row in `../library/sources.csv` |  |
| base | SW2 | C&K KMR221GLFS | none kept: no row in `../library/sources.csv` |  |
| base | SW3 | C&K KMR221GLFS | none kept: no row in `../library/sources.csv` |  |
| base | SW4 | C&K KMR221GLFS | none kept: no row in `../library/sources.csv` |  |
| base | SW5 | C&K KMR221GLFS | none kept: no row in `../library/sources.csv` |  |
| base | TH1 | Murata NCP15WF104F03RC | none kept: no row in `../library/sources.csv` |  |
| base | U1 | STMicroelectronics USBLC6-2SC6 | none kept: no row in `../library/sources.csv` |  |
| base | U2 | Texas Instruments TPS62130RGTR | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the 3.8 V buck: 6.5 for the reference and FB; 8.4 for PWM and power save; 2.5 MB |  |
| base | U3 | Diodes AP2112K-3.3TRG1 | none kept: no row in `../library/sources.csv` |  |
| base | U4 | Raspberry Pi RP2350A | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. pins and functions (1.2.3), the core regulator (6.3 and Table 1689), input levels; with Hardware design with RP2350 at datasheets.raspberrypi.com/rp2350/hardware-design-with-rp2350.pdf for the minimal design; 10.6 MB |  |
| base | U5 | Winbond W25Q128JVPIQ | none kept: no row in `../library/sources.csv` |  |
| base | U6,U7 | Texas Instruments SN74LVC1G07DCKR | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the open-drain buffers on RUN and QSPI_SS: output low at 1.65 V; 2.9 MB |  |
| base | Y1 | Abracon ABM8-272-T3 | none kept: no row in `../library/sources.csv` |  |
| base | Lantronix Open-Q 845 uSOM, 4 GB / 32 GB | Lantronix QC-DB-P10004 | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. Open-Q 845 uSOM: pin names (Tables 2 to 4), supply (Table 7), power (Table 9), socket places (Figure 7); 1.3 MB |  |
| base | Wi-Fi and Bluetooth antennas, U.FL, 2.4 and 5 GHz |  | none: no part number chosen yet (the parts list's note says why) |  |
