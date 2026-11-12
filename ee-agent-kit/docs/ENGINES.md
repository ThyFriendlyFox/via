# Engines

An engine is the external program a gate runs. EE Workcenter has 3
engines and 1 planned. Select an engine's binary with its environment
variable (`docs/CONFIGURATION.md`); the gate that uses it is fixed.

## kicad-cli

KiCad 10's command line. Powers the ERC, DRC, and EXPORT gates and the
DSN export step of autoroute. Headless; needs no display. Installed from
the KiCad PPA by `install.sh`, or present in the official
`kicad/kicad:10.0` image.

```sh
KICAD_CLI=kicad-cli   # default
```

Reports are JSON (`--format json`). Exit code 5 with
`--exit-code-violations` means "ran, found violations"; the CLI parses
the report rather than trusting the code.

## ngspice

Batch SPICE simulator. Powers the SIM gate. Runs `sim/*.cir` decks with
`ngspice -b -o <log>`; the gate parses `name = value` lines that the
deck's `.control` block prints. Installed from the Ubuntu archive.

```sh
NGSPICE=ngspice       # default
```

## FreeRouting

Java autorouter, release 1.9.0. Powers `workcenter design --route` and the
autoroute command: Specctra DSN in, Specctra session out. Needs Java 21.
`install.sh` downloads the pinned release JAR and checks its SHA-256; a
blocked download leaves the engine absent and `doctor` reports
`degraded, without freerouting`. Release 2.1.0 is not used: it checks
GitHub for updates at start and never finishes a job when that call fails,
which it does in every proxied environment. Both commands start the router
with `-de`, `-do`, `-mp` and `-dct 0`. Without `-dct 0` release 1.9.0 waits
20 s before each route, for a click on a dialog. For a hand-drawn board `kicad-cli` 10 cannot
export a DSN, so the autoroute command takes one exported from KiCad
(`<project>/<name>.dsn` or `--dsn`) and skips loudly without it.

```sh
FREEROUTING_JAR=/opt/workcenters/ee/freerouting/freerouting.jar   # default
JAVA=java
```

For a kicadgen design the whole round trip is headless: `tools/kicadgen.py`
writes the DSN from the design model (0.1 um units, y up, pads as rect or
circle padstacks, a custom pad as the polygon of its shapes' hull (a box
round them covered a mic's other pads, M140), non-plated holes as
unconnected pins, net classes with
their own widths and vias) and merges the session back into the board.
FreeRouting writes session coordinates at 10 times its declared
resolution; the merge takes the scale from the session's placement block.
What 1.9.0 honours, measured by routing a fixture (`tests/test_routing.py`):
a wire or via with `(type fix)` stays; `(type shove_fixed)` may be pushed
aside but is never ripped up or reworked by the optimiser; one with no type
(or `normal`) is unfixed, and the optimiser moves it, rips it up or removes
it as a tail (`design --seed` holds connected seed copper and leaves loose
ends unfixed); any other type is fixed by the user; a typed clearance such as `(clearance N (type via_wire))`
is read but has no effect in the structure, globally or in a layer's
`(rule ...)`, and inside a net class it holds only between that class's own
vias and wires. A hole's clearance per layer therefore reaches it as grown
copper on that layer (M79).
For a hand-drawn `.kicad_pcb` both ends still happen in KiCad. Reading an
arbitrary board file into the DSN writer is
ROADMAP item 3, "Headless autoroute for hand-drawn boards".

## kicadgen

`tools/kicadgen.py` is not an engine but the way designs reach the
engines without a GUI. It parses the KiCad symbol and footprint libraries
(`KICAD_SYMBOL_DIR`, `KICAD_FOOTPRINT_DIR`), flattens derived symbols,
strips the KiCad 10 library tokens the 9.0 file formats do not know, and
writes the schematic (stub wires and labels, power symbols, PWR_FLAG
pairs, no-connects with KiCad's `unconnected-(...)` pad nets), the board
(footprint instances with rotation, nets, outline, segments, vias), and
the project file (net classes, severities for the embedded-library
warnings). `workcenter design <design.py> [--route]` drives it.

## librsvg

`rsvg-convert` turns the SVGs that `kicad-cli` exports into PNGs for
`workcenter render`. Absent, the render command keeps the SVGs and says
which PNGs it skipped. It also flattens the layer overview sheet, an SVG
that places the per-layer PNGs in a grid.

## FFmpeg

`ffmpeg` joins the 3D frames that `kicad-cli pcb render` draws into the
turning GIF of `workcenter render --views spin`, with a palette made from
the frames themselves. Absent, the GIF is skipped with the reason; nothing
else needs it, and the CLI stays standard-library Python.

## kistack placement checks

Not an engine of its own: kistack's layout-placement scripts
(`third_party/kistack/skills/layout-placement/scripts`), run by
`workcenter placement` in the venv with shapely and numpy. kistack reads the
board through the IPC API, which needs a KiCad server with the board open;
KiCad 10.0's `kicad-cli` has no API server, so `tools/kistack_board.py`
answers the same `ipc_board.load()` from the board file with pcbnew: pads as
KiCad's own polygons, courtyards, the outline, netted copper shapes, and the
net classes and clearance overrides kistack's rules module asks for. The
scripts themselves are unchanged. Absent shapely or pcbnew, the command
skips (exit 2) and says which.

```sh
KISTACK_DIR=<checkout>/third_party/kistack   # default
```

## pygerber

`pygerber raster-2d <layer> -o <png> -d 1000 -s copper_alpha` draws one
Gerber layer as an image, for kistack's Gerber review. Release 2.4.3, from
PyPI into the venv. kistack's skill names the 3.x command
(`pygerber gerber convert png`); 2.4.3 is the newest stable release and has
`raster-2d` instead. No gate runs it yet.

## pdfminer.six

Reads one PDF page's vector paths and text lines for `workcenter curve`:
`tools/pdfcurve.py` runs under the venv and prints them as JSON; the CLI
maps them onto a plot's axes with the standard library. Release 20260107,
from PyPI into the venv. pdfminer keeps a path's end points only, drops
Bezier control points, splits a path at each moveto, and repeats the first
point of a path closed with `h`. Absent, the command skips (exit 2) and
says so.

## PyYAML

Reads a GitHub workflow for `workcenter ci`: the venv turns the YAML into
JSON, and the CLI runs the steps. Release 6.0.3, from PyPI into the venv.
YAML 1.1 reads the key `on:` as true; the replay never reads it. The venv
runs without `-s`, so it imports the copy pip reports: Ubuntu's
python3-yaml 6.0.1 in the system packages comes second. Absent, the
command skips (exit 2) and says so.

## kipy (planned)

`kicad-python`, the official IPC API client, is installed in the venv
but no gate uses it yet. It needs a running KiCad, which under Xvfb is
possible in the cloud environment (`xvfb` is installed). First use:
session import (ROADMAP item 3, "Headless autoroute for hand-drawn boards").

## The chip engines

The engines that take RTL to a GDSII layout. A board needs none of them,
so they install on request: `sudo INSTALL_CHIP=1 ./install.sh`, or
`sudo ./install.sh --chip` for this step alone. The step takes 32 s and
1.9 GB on the workcenter's machine. A second run downloads nothing.

| Engine | Version | From | Where |
|---|---|---|---|
| Verilator | 5.020 | Ubuntu's archive | `PATH` |
| Icarus Verilog (`iverilog`, `vvp`) | 12.0 | Ubuntu's archive | `PATH` |
| Yosys | 0.33 | Ubuntu's archive | `PATH` |
| KLayout | 0.28.16 | Ubuntu's archive | `PATH` |
| OpenROAD | commit `f12e2f47`, a build of 2022-03-17 | conda, channel litex-hub | `<root>/chip/bin/openroad` |
| OpenSTA | 2.3.1 | inside the OpenROAD package | `<root>/chip/bin/sta` |
| Magic | 8.3.465 | conda, channel litex-hub | `<root>/chip/bin/magic` |
| Netgen | 1.5.272 | conda, channel litex-hub | `<root>/chip/bin/netgen` |
| The sky130A process kit, library `sky130_fd_sc_hd` | open_pdks commit `6d4d117` | ciel 3.2.0 | `<root>/chip/pdk/sky130A` |

`<root>` is `WORKCENTER_ROOT`, `/opt/workcenters/ee` unless set.
`WORKCENTER_CHIP_TOOLS` names another folder that holds `bin/` and `pdk/`.

Every download is pinned: micromamba by its SHA256, each conda package by
its URL and MD5 (`environment/chip/openroad.explicit.txt`,
`layout.explicit.txt`), ciel and each package under it by version
(`ciel.requirements.txt`), the process kit by its commit. On 2026-11-11
these engines took an 8-bit counter from RTL to a layout on this machine:
the router's last count 0, Magic's DRC count 0, 0 items in the KLayout
deck, Netgen's "Circuits match uniquely.", 54 timing corners met.

The traps found here:

| Trap | What happens | What the workcenter does |
|---|---|---|
| Magic and Netgen read standard input | Started from a terminal with no input, each waits. An install stood still for 10 minutes on Netgen's version line. | Every call gets `< /dev/null`. |
| The process kit is pinned to the Magic | The kit's technology file states the Magic it needs: `requires magic-8.3.411` for commit `6d4d117`. The newest kit asks for 8.3.693. With an older Magic the file loads with errors and `def read` never returns. | The kit's commit and the Magic's version change together, and every engine call has a time limit. |
| Ubuntu's Magic is too old | `apt install magic` gives 8.3.105, which refuses the kit: `Magic version 8.3.411 is required by this techfile`. | The step takes Magic from conda. Ubuntu's package is not installed. |
| The OpenROAD is a build of 2022 | It is the newest litex-hub build that conda-forge's packages can feed. Later builds ask for a `libboost` that only Anaconda's `main` channel has, and that channel has other terms of service. Its help lacks `check_antennas -net` and the scan commands of the current documents. | The lock names this build. A newer one is a roadmap item. |
| micromamba makes a folder in the home it is given | `~/.mamba/pkgs` appears in the user's home. | The step gives it a home inside `<root>/chip/mamba`. |
| OpenROAD-flow-scripts' own flow | Its first step stops with Yosys 0.33: it asks for Yosys 0.58 with the slang plugin. | The workcenter runs the engines with its own scripts. |

## Writing a new engine

A new engine PR includes all of these:

1. The install step in `install.sh`, idempotent, with a pinned version
   and a checksum where the source allows one.
2. A `doctor` check in `tools/workcenter` with `required` set honestly.
3. A `gate_<name>` function returning a `Result`, with `skip` when the
   engine is absent and `error` when it crashes.
4. 2 fixture boards under `tests/boards`: 1 that the gate passes, 1 that
   it fails for a named reason, and the tests that assert both.
5. Its row here, its variables in `docs/CONFIGURATION.md`, its gate in
   `WORKCENTER.md`, and the skill that tells the agent when to run it.
