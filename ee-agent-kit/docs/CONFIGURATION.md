# Configuration

EE Workcenter reads environment variables and command-line flags. There
is no configuration file. Defaults apply when a variable is unset; an
unset variable never causes a failure.

| Platform | Path |
|---|---|
| Linux | `/opt/workcenters/ee` (install root), `/opt/workcenters/ee/env.sh` (generated, sourceable) |

## `install.sh`

| Field | Type | Default | Use |
|---|---|---|---|
| `WORKCENTER_ROOT` | path | `/opt/workcenters/ee` | Where the venv, the JAR, the manifest copy, and `env.sh` live. |
| `FREEROUTING_VERSION` | string | `1.9.0` | Release to download. 2.1.0 hangs after routing in a proxied session (landmine map). |
| `FREEROUTING_SHA256` | hex | pinned in the script | Expected JAR checksum. Empty skips the check with a warning. |
| `FREEROUTING_URL` | URL | GitHub release asset for the version | Alternate download location. |
| `REQUIRE_FREEROUTING` | `0`/`1` | `0` | `1` makes a failed JAR download fatal. CI sets `1`. |
| `SKIP_APT` | `0`/`1` | `0` | `1` skips the apt step entirely. |

## `tools/workcenter`

| Field | Type | Default | Use |
|---|---|---|---|
| `WORKCENTER_ROOT` | path | `/opt/workcenters/ee` | Locates the venv and the JAR. |
| `FREEROUTING_JAR` | path | `$WORKCENTER_ROOT/freerouting/freerouting.jar` | The autoroute engine. |
| `KICAD_CLI` | command | `kicad-cli` | The KiCad engine. |
| `NGSPICE` | command | `ngspice` | The simulation engine. |
| `JAVA` | command | `java` | Runs the JAR. |
| `KICAD10_3DMODEL_DIR` | path | `/usr/share/kicad/3dmodels` | Where `render` looks for the library 3D bodies footprints name, to list the parts drawn without one (`KICAD9_` and `KICAD8_3DMODEL_DIR` likewise). |
| `KISTACK_DIR` | path | `<checkout>/third_party/kistack` | The kistack copy whose `skills/layout-placement/scripts` `workcenter placement` runs. |

| Flag | Commands | Default | Use |
|---|---|---|---|
| `--json` | all | off | Machine-readable output. |
| `--out DIR` | gates, erc, drc, sim, export, autoroute, render, procure, sources, verify; design | `<project>/build`; design: the design file's folder | Where reports and artifacts go; for design, where the KiCad project is written. |
| `--strict` | gates, erc, drc, sim, export, render, procure, sources, verify | off | Warnings fail the gate; for verify, a requirement whose verdict is FAIL or OPEN; for render, a part the 3D views draw without a body fails it; for procure, a line short of stock or a price older than 90 days; for sim, a model outside a `warn` bound (its datasheet); for sources, a datasheet kept as a note only, a file with no SHA256 or revision recorded, a model older than its datasheet, or a load check skipped. |
| `--parts FILE` | procure, sources | `<project>/parts.csv` | A parts CSV, repeatable; the first row whose Value and Footprint match a BOM line prices it (procure) or names its MPN (sources), and every row with no Footprint is an item off the board. Columns in the `procurement` skill. |
| `--sources FILE` | sources | the nearest `library/sources.csv` at or above the project | The library's manifest: one row per datasheet, SPICE model or STEP file, the files beside it (`WORKCENTER.md`, "Project requirements"). The SIM gate finds it the same way. |
| `--fetch` | sources | off | Read each row's URL once more under the workcenter's own user agent into `<out>/sources/fetched/` and report each as same, changed, new, refused, gone or unreachable; a refusal is never retried. The library is not written. |
| `--package DIR` | verify | `<project>/verification` | The verification package (`PROCESSES.md` P28): requirements, system, simulations, calculations, traceability. |
| `--init` | verify | off | Copy `templates/verification/` into the package and a writeup per `sim/*.cir` into `simulations/<deck>/`, never over a file that exists. The new files fail the check until each `<!-- fill ... -->` is written. |
| `--boards LIST` | procure | `1,10` | Units to price, comma-separated; each gets its cheapest order and totals per supplier. |
| `--step` | gates, export | off | Also export a STEP model. |
| `--fab NAME` | gates, drc | none | Also check a fab's limits: a rule set in `rules/` (`sierra-circuits-web`) or a `.kicad_dru` path, laid over the project's own rules on a copy in `<out>/fab-<name>/`. A design file's `fab` field does the same for good (`rules/README.md`). |
| `--dsn FILE` | autoroute | `<project>/<name>.dsn`, then `build/route/<name>.dsn` | Specctra DSN exported from KiCad. Absent means the command skips. |
| `--passes N` | autoroute, design | `20` autoroute, `60` design | FreeRouting optimisation passes. |
| `--threads N` | autoroute | engine default | FreeRouting thread count. |
| `--timeout S` | autoroute, design | `600` autoroute, `900` design | Kill the router after S seconds. |
| `--route` | design | off | Export the DSN, run FreeRouting, merge the session before writing. |
| `--rounds N` | design | `4` | Route again, up to N rounds, with a via reserved beside each pad a pour lost. |
| `CHECK BOARD ARGS` | placement | none | `CHECK` is one of `pin_sides`, `placement_audit`, `route_check`, `local_search`, `group_search`; `BOARD` a project folder or `.kicad_pcb`; `ARGS` go to the check as kistack documents them (`U1`, `--ic U1`, `--track 0.15 --clear 0.1 --via 0.5 --edge 0.3` for a board with a `.kicad_dru`). |
| `VIEW BOARD` | inspect | none | `VIEW` is one of `map`, `list`, `probe`, `net`, `islands`, `resistance`, `crossed`; `BOARD` a project folder or `.kicad_pcb`. KiCad's `pcbnew` reads the board under the venv's Python; only `map` writes files. `--json` goes after the view too. |
| `--box X0 X1 Y0 Y1` | inspect map, list, crossed | none (required) | The window in board millimetres, the x range first. |
| `--layers L ...` | inspect map | every copper layer | The copper layers to draw, one PNG each (`F-Cu.png`); a back or inner layer is drawn as seen from the top, and the picture says so. |
| `--scale PX` | inspect map | `60` | Pixels per millimetre; the longest side stays at 6000 px or under. |
| `--out DIR` | inspect map | `<project>/build/inspect` | Where the PNGs go. |
| `--layer L` | inspect list, probe | none | list: one copper layer only; probe: the track's layer. |
| `--net NAME` | inspect list, probe, islands | none; islands `GND` | list: one net only; probe: the new via's or track's net; islands: the poured net. A local label's net is found as `NAME` or `/NAME`. |
| `--via X,Y` | inspect probe | none | A via at X,Y on `--net`, through every copper layer. |
| `--track "X,Y X,Y ..."` | inspect probe | none | A track through the points on `--layer` and `--net`. |
| `--part REF` | inspect probe | none | A part on the board, moved to `--at` for the probe; its own pads and courtyard go with it. A part the board does not have yet needs `--footprint`. |
| `--footprint LIB:NAME` | inspect probe | none | A new part's footprint, from the project's `fp-lib-table` or KiCad's footprint library. |
| `--nets PAD=NET,...` | inspect probe | none | A new part's pad nets; a pad without one is held clear of every net. |
| `--back` | inspect probe | off | A new part on the bottom face. |
| `--at X,Y` | inspect probe | none (required with `--part`) | Where the part's anchor goes. |
| `--rot DEG` | inspect probe | the part's angle | The part's angle, as the board file writes it. |
| `--size MM` | inspect probe | the net class's via diameter (`.kicad_pro`) | The new via's diameter. |
| `--drill MM` | inspect probe | the net class's via drill | The new via's hole. |
| `--width MM` | inspect probe | the net class's track width | The new track's width. |
| `--from REF.PAD` | inspect resistance | none (required) | One end of the path. |
| `--to REF.PAD` | inspect resistance | none (required) | The other end. |
| `--temp C` | inspect resistance | `20` | The copper's temperature: 1.72e-8 Ohm m at 20 °C, 0.393 % more per °C. |
| `--plating MM` | inspect resistance | the board's hole plating (KiCad's default 0.02 mm) | The copper of each via barrel, round a hole the size of the via's drill. |
| `--new BOARD` | inspect crossed | none | The board after the change: which of the nets that crossed the window it no longer connects (exit 1 on one). |
| `--width PX` | render | `1600` | Image width; the schematic PNG is twice that, the GIF's frames at most 640. |
| `--views LIST` | render | `schematic,2d,3d,layers` | What to draw, comma-separated, from `schematic`, `2d`, `3d`, `layers`, `spin`, or `all`. `layers` writes `render/layers/<layer>.png` for each layer with something on it and `render/layers.png`; `spin` writes `render/board-spin.gif`. |
| `--spin-frames N` | render | `36` | Frames in the turning GIF, 12 a second. |
| `--spin-tilt DEG` | render | `-55` | The GIF's tilt about the board's x axis (kicad-cli `--rotate x`): `-55` looks down at the top face, `-125` up at the bottom face. |
| `--spin-zoom Z` | render | `1.0` | The GIF's zoom; below 1 keeps long or tall parts in frame end-on. |
| `--spin-pivot X,Y,Z` | render | none | The GIF's pivot, in cm from the board's centre (kicad-cli `--pivot`); raise Z to the middle of a tall assembly. |

## `tools/wrlgen.py`

| Preset | Flags | Default | Use |
|---|---|---|---|
| `usb-c-vertical OUT` | `--height H`, `--base W D H`, `--shell W D WALL` | 7.0; 9.9 6.2 1.6; 9.0 3.6 0.25 | Vertical USB-C receptacle body: plastic base, metal shell, tongue. |
| `connector-510 OUT` | `--collar D`, `--height H`, `--tab-radius R` | 9.5; 4.0; 4.0 | PCB-mount 510 battery connector: collar with an M7 x 0.5 internal thread, insulator, spring pin, four tabs. |
| `cartridge-510 OUT` | `--diameter D`, `--length L`, `--fill F` | 10.5; 52; 0.6 | 510 cartridge for assembly renders; z = 0 is the collar top, the thread reaches down into it. |
| `pouch-cell OUT` | `--size W D H` | 25 8 35 | Li-polymer pouch cell standing on its long edge. |
| `display-module OUT` | `--pcb W D T` | 38 12 1.2 | 0.91 in 128 x 32 OLED module lying face up. |
| `leadless OUT` | `--body W D H`, `--pins NX NY`, `--pitch P`, `--terminal L W` | 4 4 0.55; 7 7; 0.5; 0.4 0.25 | QFN, DFN or SON body: moulding, a terminal at the foot of each side (NX per top and bottom edge, NY per left and right edge), a pin 1 dot top left. |
| `gullwing OUT` | `--body W D H`, `--leads LEFT RIGHT`, `--pitch P`, `--span S`, `--lead W T`, `--standoff H` | 0.8 1.6 0.75; 2 1; 1.0; 1.6; 0.22 0.12; 0.05 | SOT-23, SOT-523 or SC-70 body on a standoff, leads bent down to feet `S` apart tip to tip; the defaults are Diodes' SOT523 drawing. |
| `threaded-stud OUT` | `--major D`, `--pitch P`, `--height H`, `--tail D LEN`, `--shoulder D H` | 1.6; 0.35; 4.0; 0.7 1.6; 1.5 0.4 | Threaded contact stud in a through-hole pad; `--tail 0 0 --shoulder 0 0` for a bare threaded barrel. |

Every number is millimetres; the file is written in KiCad's VRML unit (0.1 inch).

## `tools/kicadgen.py`

| Command | Flags | Use |
|---|---|---|
| `pins LIB:SYMBOL...` | | Pin numbers, names, types and positions of library symbols. |
| `footprint LIB:FOOTPRINT...` | `--lib NAME=DIR` (repeatable) | Pads, layers, drills and courtyard; `--lib` reads a project `.pretty` folder. |

## `tools/kicadgen.py`

| Field | Type | Default | Use |
|---|---|---|---|
| `KICAD_SYMBOL_DIR` | path | `/usr/share/kicad/symbols` | Symbol libraries to read. |
| `KICAD_FOOTPRINT_DIR` | path | `/usr/share/kicad/footprints` | Footprint libraries to read. |
| `FREEROUTING_JAR` | path | `/opt/workcenters/ee/freerouting/freerouting.jar` | Used by `route()`. |

## `tools/stretch.py`

| Flag | Default | Use |
|---|---|---|
| `DESIGN` | none | The design file. Python's own parser reads it, so a number in a comment or a string never moves. |
| `--cut X` | none (required) | The x of the cut, mm: every board x-coordinate east of it moves. |
| `--grow G` | none (required) | How far, mm; a negative G moves west. |
| `--outline X0 Y0 X1 Y1` | the file's `outline=(...)` | The board's extent, when the file computes its outline. A pair counts as a point within 5 mm of it. |
| `--out FILE` | the design file | Write here instead. Either way the result goes to a new file first and replaces the target once it is complete. |
| `--dry-run` | off | Print what would move and what stays for a look by hand; write nothing. |

## `tools/hooks/install_hooks.py`

| Flag | Default | Use |
|---|---|---|
| `--settings PATH` | `~/.claude/settings.json` | The Claude Code settings file to add the no-cd PreToolUse hook to. Existing settings and hooks are kept; a second run changes nothing. Writes only that file. Run by hand: writing a user's settings is their decision. |

## `environment/setup.sh`

| Field | Type | Default | Use |
|---|---|---|---|
| `WORKCENTER_REPO` | URL | this repository | Where the cloud environment clones from. |
| `WORKCENTER_REF` | branch or tag | `main` | What it checks out. |

<!-- Rules for these tables:
     · Every shipped option appears here — an undocumented option is a
       defect.
     · New options land in this table in the same PR that adds them.
     · Defaults shown here are the real defaults in code, not intended
       ones. -->
