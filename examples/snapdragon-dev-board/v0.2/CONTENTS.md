# v0.2: contents

What this folder holds, for Wyvern — board prototype v0.2. Made by `workcenter docs v0.2` from the folder itself, the version's parts lists and `library/sources.csv`; run it again after a change.

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
  - [footprints/](footprints/): project footprints, 4 files
  - [symbols/](symbols/): project symbols, 2 files
  - [models/](models/): 3D bodies, 6 files
- [osm_l.py](osm_l.py): The Vantron VOSM6490: a Qualcomm QCS6490 on an OSM Size-L module, 45 x 45 mm, 662 LGA pads.

## Simulation

- [sim/mcu_control.cir](sim/mcu_control.cir), bounds in [sim/mcu_control.expect.json](sim/mcu_control.expect.json): The Snapdragon resets the RP2350 and puts it in its bootloader through U7 and U8, 74LVC1G07 open-drain
- [sim/som_i2c.cir](sim/som_i2c.cir), bounds in [sim/som_i2c.expect.json](sim/som_i2c.expect.json): The Snapdragon's I2C on the pins (SOM_I2C_SDA, SOM_I2C_SCL: APPS_I2C on the module's AA16 and AA15,
- [sim/sys_rail_high.cir](sim/sys_rail_high.cir), bounds in [sim/sys_rail_high.expect.json](sim/sys_rail_high.expect.json): +5V at its highest: VREF at its 1.212 V maximum (SLVSH28A, 6.5), and the FB pin sinking its most:
- [sim/sys_rail_low.cir](sim/sys_rail_low.cir), bounds in [sim/sys_rail_low.expect.json](sim/sys_rail_low.expect.json): +5V, the module's supply, at its lowest
- [sim/vbus_pdn.cir](sim/vbus_pdn.cir), bounds in [sim/vbus_pdn.expect.json](sim/vbus_pdn.expect.json): VBUS, the converter's input, as U3 draws from it: a USB-C charger behind its cable, C30 and C31 at
- [sim/vbus_uvlo_high.cir](sim/vbus_uvlo_high.cir), bounds in [sim/vbus_uvlo_high.expect.json](sim/vbus_uvlo_high.expect.json): Where U3 starts, at the latest: as vbus_uvlo_low.cir, with VUVLO at its 1.26 V maximum (SLVSH28A,
- [sim/vbus_uvlo_low.cir](sim/vbus_uvlo_low.cir), bounds in [sim/vbus_uvlo_low.expect.json](sim/vbus_uvlo_low.expect.json): Where U3 starts, at the earliest

## Pictures and reports

- [pictures.json](pictures.json): what `workcenter pictures` draws and copies into docs/
- [docs/board-3d-bottom.png](docs/board-3d-bottom.png)
- [docs/board-3d-iso.png](docs/board-3d-iso.png)
- [docs/board-3d-top.png](docs/board-3d-top.png)
- [docs/board-bottom.png](docs/board-bottom.png)
- [docs/board-spin-bottom.gif](docs/board-spin-bottom.gif)
- [docs/board-spin.gif](docs/board-spin.gif)
- [docs/board-top.png](docs/board-top.png)
- [docs/layers.png](docs/layers.png)
- [docs/schematic.png](docs/schematic.png)
- [docs/layers/](docs/layers/): every copper and technical layer, 17 images
- [docs/gates.md](docs/gates.md)

## Parts

- The base board's priced parts list: [../parts/lists/v0.2.md](../parts/lists/v0.2.md)

## Datasheets

Each part's datasheet as its maker publishes it, copied from [`../library/`](../library/) into [`datasheets/`](datasheets/); [`../library/sources.csv`](../library/sources.csv) records where each came from, its revision and its SHA256. A part with no file says why.

| Board | Refs | Part | Datasheet | Revision |
|---|---|---|---|---|
| base | C9-C11,C40 | Murata GRM155R61A475MEAAD | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. 4.7 uF 10 V X5R 0402; 20.2 MB |  |
| base | C12-C19,C22,C24,C32,C37-C39,C45-C48 | Murata GRM155R71C104KA88D | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. 100 nF 16 V X7R; 2.0 MB |  |
| base | C20,C21 | Murata GRM1555C1H150JA01D | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. 15 pF C0G, the crystal's load; 2.0 MB |  |
| base | C23 | Murata GRM188R61A475KE15D | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. 4.7 uF 10 V X5R 0603, the microSD's supply; 0.8 MB |  |
| base | C30,C31 | Murata GRM21BR61C106KE15L | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. 10 uF 16 V X5R 0805 (its loss at 5 V of DC bias is taken as 50 % in sim/corners.json: this catalog has no curve for it); 20.2 MB |  |
| base | C33-C36,C42,C50,C51 | Murata GRM21BR61A226ME51L | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. 22 uF 10 V X5R 0805 (its loss at 5 V of DC bias is taken as 50 % in sim/corners.json: this catalog has no curve for it); 20.2 MB |  |
| base | C41 | Murata GRM155R71H103KA88D | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. 10 nF 50 V X7R, the buck-boost's compensation; 2.0 MB |  |
| base | C43,C44,C49 | Murata GRM155R61A105KE15D | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. 1 uF 10 V X5R; 0.8 MB |  |
| base | D1 | Lite-On LTST-C191KRKT | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the red light's forward voltage; 0.4 MB |  |
| base | D2 | Lite-On LTST-C191KGKT | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the green light's forward voltage; 0.5 MB |  |
| base | D3 | Lite-On LTST-C191TBKT | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the blue light's forward voltage; 0.8 MB |  |
| base | J1 | Amphenol ICC 12401610E4#2A | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. Amphenol's USB Type-C cut sheet: the receptacle's land pattern and the 9.59 mm from its face to its pegs; 0.6 MB |  |
| base | J2,J3 | Sullins PRPC030SAAN-RC | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the 1 x 30 headers; 0.3 MB |  |
| base | J4 | Molex 1040310811 | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the microSD socket and its card detect; 0.2 MB |  |
| base | L1 | Coilcraft XAL6030-222MEC | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. L1: 2.2 uH, Isat 15.9 A at 30 % drop, DCR 13.97 mOhm at most, 6.36 x 6.56 x 3.1 mm; 0.2 MB |  |
| base | L2 | Abracon AOTA-B201610S3R3-101-T | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the RP2350 core regulator's 3.3 uH inductor; 0.7 MB |  |
| base | R3 | YAGEO RC0402FR-0733RL | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the resistors: 1 %, 1/16 W, their temperature coefficient; 0.5 MB |  |
| base | R4,R8,R38 | YAGEO RC0402FR-0710KL | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the resistors: 1 %, 1/16 W, their temperature coefficient; 0.5 MB |  |
| base | R5,R9,R12,R44 | YAGEO RC0402FR-071KL | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the resistors: 1 %, 1/16 W, their temperature coefficient; 0.5 MB |  |
| base | R6,R7 | YAGEO RC0402FR-0727RL | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the resistors: 1 %, 1/16 W, their temperature coefficient; 0.5 MB |  |
| base | R10,R11,R30,R34 | YAGEO RC0402FR-07100KL | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the resistors: 1 %, 1/16 W, their temperature coefficient; 0.5 MB |  |
| base | R18-R21 | YAGEO RC0402FR-0747KL | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the resistors: 1 %, 1/16 W, their temperature coefficient; 0.5 MB |  |
| base | R31 | YAGEO RC0402FR-0731K6L | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the resistors: 1 %, 1/16 W, their temperature coefficient; 0.5 MB |  |
| base | R32 | YAGEO RC0402FR-074K7L | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the resistors: 1 %, 1/16 W, their temperature coefficient; 0.5 MB |  |
| base | R33 | YAGEO RC0402FR-0726K1L | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the resistors: 1 %, 1/16 W, their temperature coefficient; 0.5 MB |  |
| base | R35 | YAGEO RC0402FR-0751KL | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the resistors: 1 %, 1/16 W, their temperature coefficient; 0.5 MB |  |
| base | R36 | YAGEO RC0402FR-07910KL | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the resistors: 1 %, 1/16 W, their temperature coefficient; 0.5 MB |  |
| base | R37 | YAGEO RC0402FR-07200KL | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the resistors: 1 %, 1/16 W, their temperature coefficient; 0.5 MB |  |
| base | R39-R43 | YAGEO RC0402FR-072K2L | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the resistors: 1 %, 1/16 W, their temperature coefficient; 0.5 MB |  |
| base | R45 | Panasonic ERJ-2BQFR33X | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the 0.33 ohm damper resistor, 1 %, its power rating; 0.9 MB |  |
| base | SW1 | C&K KMR221GLFS | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the 5 buttons; 0.1 MB |  |
| base | SW2 | C&K KMR221GLFS | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the 5 buttons; 0.1 MB |  |
| base | SW3 | C&K KMR221GLFS | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the 5 buttons; 0.1 MB |  |
| base | SW4 | C&K KMR221GLFS | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the 5 buttons; 0.1 MB |  |
| base | SW5 | C&K KMR221GLFS | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the 5 buttons; 0.1 MB |  |
| base | U1 | Vantron VOSM6490 | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. The QCS6490 module on OSM Size-L: its pin tables (the names in v0.2/osm_l_pins.csv), VCC_IN_5V 4.8 to 5.2 V, 5 V / 3 A, VCC_OUT_IO 1.8 V under 100 mA; 1.1 MB |  |
| base | U2 | Texas Instruments HD3SS3220RNHR | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. The USB-C controller and SuperSpeed mux: pin table (section 4), dead battery (6.4.3), the UFP design (7.2.4: 900K to VBUS_DET, 200K on DIR, 100 nF on TX only); 1.5 MB |  |
| base | U3 | Texas Instruments TPS552892RYQR | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. The 5.0 V buck-boost: pins (Table 5-1), VREF, EN/UVLO and the FB pin currents (6.5), fSW (equation 3), compensation (8.2.2.7), the RYQ0021A land pattern and stencil (pages 33, 34); 4.0 MB |  |
| base | U4 | Diodes AP2112K-3.3TRG1 | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the 3.3 V regulator: 600 mA, its pinout; 0.8 MB |  |
| base | U5 | Raspberry Pi RP2350A | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. pins and functions (1.2.3), the core regulator (6.3 and Table 1689), input levels; with Hardware design with RP2350 at datasheets.raspberrypi.com/rp2350/hardware-design-with-rp2350.pdf for the minimal design; 10.6 MB |  |
| base | U6 | Winbond W25Q128JVPIQ | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the RP2350's flash: pinout, 3.3 V; 2.6 MB |  |
| base | U7,U8 | Texas Instruments SN74LVC1G07DCKR | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the open-drain buffers on RUN and QSPI_SS: output low at 1.65 V; 2.9 MB |  |
| base | U9 | STMicroelectronics USBLC6-2SC6 | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the USB 2 clamp's pinout; 0.2 MB |  |
| base | Y1 | Abracon ABM8-272-T3 | none kept: Not kept in the repository, to keep the workcenter small; SHA256 is of the copy the design was read from. the RP2350's 12 MHz crystal and its load; 0.3 MB |  |
| base | Heatsink for the module, 40 x 40 mm, with thermal tape |  | none: no part number chosen yet (the parts list's note says why) |  |
