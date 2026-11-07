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
| `--out DIR` | gates, erc, drc, sim, export, autoroute, render, procure, sources, verify; design; ci | `<project>/build`; design: the design file's folder (with `--check`, a temporary folder); ci: `<repo>/build/ci` | Where reports and artifacts go; for design, where the KiCad project is written; for ci, each step's script, `$GITHUB_ENV` file and log. |
| `--strict` | gates, erc, drc, sim, export, render, procure, sources, verify | off | Warnings fail the gate; for verify, a requirement whose verdict is FAIL or OPEN; for render, a part the 3D views draw without a body fails it; for procure, a line short of stock or a price older than 90 days; for sim, a model outside a `warn` bound (its datasheet); for sources, a datasheet kept as a note only, a file with no SHA256 or revision recorded, a model older than its datasheet, or a load check skipped. |
| `--parts FILE` | procure, sources | `<project>/parts.csv` | A parts CSV, repeatable; the first row whose Value and Footprint match a BOM line prices it (procure) or names its MPN (sources), and every row with no Footprint is an item off the board. Columns in the `procurement` skill. |
| `--sources FILE` | sources, fetch | sources: the nearest `library/sources.csv` at or above the project; fetch: the nearest `sources.csv` at or above `--to` | The library's manifest: one row per datasheet, SPICE model or STEP file, the files beside it (`WORKCENTER.md`, "Project requirements"). The SIM gate finds it the same way. For fetch, a file not there yet is started with the header. |
| `--deck NAME` | sim | every deck | Run only `sim/NAME.cir` (with or without `.cir`), the gate's way: the model rows' translation and mode, the expect bounds. Prints every value the deck printed, with its bound. An unknown name is an error that lists the decks. |
| `--keep` | sim | off | Run each deck from `<out>/sim/run/<deck>/`, a deck the gate runs in place too (with the deck folder's own `.spiceinit`), leave the folder, and print the one command that reruns it by hand: `env -C <run folder> ngspice -b <deck>.cir` (M94). |
| `URL` | fetch | none | The maker's URL for one file. Fetched once under the workcenter's own user agent; a refusal is reported and never retried. |
| `--to FILE` | fetch | none (required) | Where the library keeps it, `<library>/<maker>/<file>`. An existing file that differs from the download is refused; the same file is left as it is. |
| `--mpn MPN` | fetch | none | The part number the row names. Needed for `--row`. |
| `--kind KIND` | fetch | from the file's suffix: `.pdf` datasheet, `.lib` `.mod` `.cir` `.sub` `.spi` `.sp` `.ckt` spice, `.step` `.stp` step | `datasheet`, `spice` or `step`. A spice file that defines one `.SUBCKT` fills the row's `Subckt`. |
| `--member NAME` | fetch | none | The file inside a zip at the URL; the row records it in `Member`. |
| `--row` | fetch | off | Append the row to `sources.csv`, as text after the file's own bytes and in its line ends. Refused, before any request, when the MPN already has a row of that kind. `Revision` and `Dated` stay empty for the reader to fill from the file. |
| `PDF` | curve | none | The datasheet. |
| `--page N` | curve | `1` | The page, counted from 1. |
| `--frame X0,Y0,X1,Y1` | curve | none | The plot's frame in PDF points, y up (the listing names each stroked rectangle as a candidate). Without it, the command lists the page's paths grouped by kind, width, paint and colour, the frames and the numeric labels. |
| `--x SCALE:MIN:MAX` | curve | none | The x axis from `X0` to `X1`: `log:0.1:100` or `lin:0:5`. Goes with `--frame` and `--y`. |
| `--y SCALE:MIN:MAX` | curve | none | The y axis from `Y0` to `Y1`. |
| `--paths IDS` | curve | every path of 4 points or more inside the frame | The path ids (`#N` in the listing) to map, comma-separated. |
| `--at X,...` | curve | none | Print each curve's y at these x values, interpolated in decades on a log axis. |
| `--at-y Y,...` | curve | none | Print each curve's x at these y values. |
| `--check` | design | off | Regenerate into a temporary folder (or `--out`) and compare the `.kicad_pro` and `.kicad_sch` with the design's own, as a board repository's CI does. Exit 1 on a difference or on the design step's own exit 1 (M85). Writes nothing in the project. Refuses `--route`. |
| `REPO` | ci | `.` | The repository whose `.github/workflows/*.yml` the replay runs, from its root, as the runner's checkout. |
| `--job ID` | ci | every job, each after the jobs it `needs` | Replay only this job (repeatable). |
| `--workflow FILE` | ci | every workflow | One workflow: a file name in `.github/workflows/` or a path. |
| `--skip REGEX` | ci | `(?i)\b(install\|upload)` | Skip the steps whose name matches; `uses:` steps are always skipped. A step whose `${{ }}` the replay cannot read (only `env.*`, `github.workspace`, `runner.temp` and `runner.os` are read) is red until its name is skipped. |
| `FIRMWARE` | mutate | none | The firmware folder the test command runs in; each mutation gets its own copy, without `build/`. |
| `--mutations FILE` | mutate | none (required) | The project's list. JSON: `[{"name", "file", "old", "new"}]` or `{"test": CMD, "mutations": [...]}`. Python: a top-level `MUTATIONS = [(name, file, old, new), ...]` and an optional `TEST = "..."`, read as literals and never run. Every `old` must be in its file exactly once; the command checks each before running any. |
| `--test CMD` | mutate | the list's `test`, else `make -k test` | The test command, run under `bash -c` in each copy. It must pass unmutated. A mutation that fails it is caught; one that a compiler's `file:line: error:` stops did not build, and fails the run as a survivor does. |
| `--only TEXT` | mutate | every mutation | Run only the mutations whose name holds this text (repeatable). |
| `--jobs N` | mutate | `1` | Mutations run at once. |
| `--work DIR` | mutate | a temporary folder, removed after | Keep the copies here, one folder per mutation. |
| `--fetch` | sources | off | Read each row's URL once more under the workcenter's own user agent into `<out>/sources/fetched/` and report each as same, changed, new, refused, gone or unreachable; a refusal is never retried. The library is not written. |
| `--package DIR` | verify | `<project>/verification` | The verification package (`PROCESSES.md` P28): requirements, system, simulations, calculations, traceability. |
| `--init` | verify | off | Copy `templates/verification/` into the package and a writeup per `sim/*.cir` into `simulations/<deck>/`, never over a file that exists. The new files fail the check until each `<!-- fill ... -->` is written. |
| `--boards LIST` | procure | `1,10` | Units to price, comma-separated; each gets its cheapest order and totals per supplier. |
| `--step` | gates, export | off | Also export a STEP model. |
| `--fab NAME` | gates, drc | none | Also check a fab's limits: a rule set in `rules/` (`sierra-circuits-web`) or a `.kicad_dru` path, laid over the project's own rules on a copy in `<out>/fab-<name>/`. A design file's `fab` field does the same for good (`rules/README.md`). |
| `--dsn FILE` | autoroute | `<project>/<name>.dsn`, then `build/route/<name>.dsn` | Specctra DSN exported from KiCad. Absent means the command skips. |
| `--passes N` | autoroute, design | `20` autoroute, `60` design | FreeRouting optimisation passes. |
| `--threads N` | autoroute | engine default | FreeRouting thread count. |
| `--timeout S` | autoroute, design, mutate | `600` autoroute, `900` design, `600` mutate | Kill the router after S seconds; for mutate, a test run past it counts as caught (the tests did not pass). |
| `--route` | design | off | Export the DSN, run FreeRouting, merge the session before writing. |
| `--rounds N` | design | `4` | Route again, up to N rounds, with a via reserved beside each pad a pour lost. |
| `CHECK BOARD ARGS` | placement | none | `CHECK` is one of `pin_sides`, `placement_audit`, `route_check`, `local_search`, `group_search`; `BOARD` a project folder or `.kicad_pcb`; `ARGS` go to the check as kistack documents them (`U1`, `--ic U1`, `--track 0.15 --clear 0.1 --via 0.5 --edge 0.3` for a board with a `.kicad_dru`). |
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
| `symbol-add LIB.kicad_sym` | `--from PINS.csv` (required), `--name NAME` (default the CSV's stem), `--reference R` (default `U`), `--footprint LIB:FP`, `--datasheet URL`, `--description TEXT` | A one-unit symbol from a datasheet's pin table, a CSV of `Number,Name,Type,Side` (KiCad's electrical types; `left`, `right`, `top`, `bottom`; an empty name is `~`): each pin on its side in the table's order, 2.54 mm apart, every pin end on the 1.27 mm grid, the body sized round the names. Appended as text before the library's closing parenthesis, so the symbols there keep their bytes; a new library is started. Refuses a name already in the library, an unknown type or side, a pin number twice. Writes only `LIB`. |

## `tools/kicadgen.py`

| Field | Type | Default | Use |
|---|---|---|---|
| `KICAD_SYMBOL_DIR` | path | `/usr/share/kicad/symbols` | Symbol libraries to read. |
| `KICAD_FOOTPRINT_DIR` | path | `/usr/share/kicad/footprints` | Footprint libraries to read. |
| `FREEROUTING_JAR` | path | `/opt/workcenters/ee/freerouting/freerouting.jar` | Used by `route()`. |

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
