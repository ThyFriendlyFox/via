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
| `INSTALL_FREEROUTING2` | `0`/`1` | `0` | `1` also installs FreeRouting 2.5.0 and its Java 25 (as `--freerouting2`). |
| `REQUIRE_FREEROUTING2` | `0`/`1` | `0` | `1` makes a failed second-router step fatal. |
| `SKIP_APT` | `0`/`1` | `0` | `1` skips the apt step entirely. |
| `REQUIRE_OPENEMS` | `0`/`1` | `0` | `1` makes a failed openEMS step fatal, a wrong checksum among them; else it warns and `workcenter fields` skips. |
| `OPENEMS_POOL` | URL | `https://deb.debian.org/debian/pool/main/o/openems` | Where Debian 12's 4 openEMS packages are fetched; each is checked against the SHA256 pinned in the script. |

## `tools/workcenter`

| Field | Type | Default | Use |
|---|---|---|---|
| `WORKCENTER_ROOT` | path | `/opt/workcenters/ee` | Locates the venv and the JAR. |
| `FREEROUTING_JAR` | path | `$WORKCENTER_ROOT/freerouting/freerouting.jar` | The autoroute engine. |
| `FREEROUTING2_JAR` | path | `$WORKCENTER_ROOT/freerouting2/freerouting.jar` | The jar of `--router freerouting2`, FreeRouting 2.5.0. |
| `FREEROUTING2_JAVA` | command | `$WORKCENTER_ROOT/java25/bin/java` | The Java that runs it; Java 25 or newer, else the router is absent. |
| `KICAD_CLI` | command | `kicad-cli` | The KiCad engine. |
| `NGSPICE` | command | `ngspice` | The simulation engine. |
| `JAVA` | command | `java` | Runs the FreeRouting 1.9.0 JAR, for `autoroute` and for `design --route`. |
| `KICAD10_3DMODEL_DIR` | path | `/usr/share/kicad/3dmodels` | Where `render` looks for the library 3D bodies footprints name, to list the parts drawn without one (`KICAD9_` and `KICAD8_3DMODEL_DIR` likewise). |
| `OPENEMS` | command | `$WORKCENTER_ROOT/openems/bin/openEMS`, else `openEMS` on `PATH` | The field solver `workcenter fields` runs; `doctor` reports it. |
| `KIKIT_PYTHON` | command | the venv's Python (`$WORKCENTER_ROOT/venv/bin/python`) | The Python that imports KiKit; EXPORT runs `tools/panel.py` with it for a project that holds `panel.json`. |
| `KISTACK_DIR` | path | `<checkout>/third_party/kistack` | The kistack copy whose `skills/layout-placement/scripts` `workcenter placement` runs. |
| `SOURCE_DATE_EPOCH` | integer, seconds since 1970-01-01 00:00:00 UTC | unset: the clock, read once at the command's start | Pins the day and the time a command writes into a file: the gates report's `GREEN on <day>`, the ledger's `at` of `references`, the card's `Updated` and `build/verify.json`'s `time`. It does not pin a judgement of now: `procure` and `costs` judge a price's age, and `fetch` writes its `Checked`, on the machine's day of the same run; the engine lock's times are the machine's clock. The pinned day is the moment's day in UTC; unset, the machine's local day. A value that is no integer, or a moment outside years 1 to 9999, ends the command with exit 1 and 1 line (SOURCE_DATE_EPOCH specification, revision 1.1, section SOURCE_DATE_EPOCH). A shell that exports it for other builds pins those days too. |
| `WORKCENTER_LOCK_DIR` | absolute path | `/tmp/workcenter-lock-<uid>` (`/tmp/workcenter-lock-0` for root), whatever TMPDIR says | The engine lock's folder: 1 per machine and user, never inside a project. Each run of a long command keeps 1 ticket file there while it waits and runs. A path that is a file, a link, relative or not writable, or (the default only) another user's folder, is refused in 1 line that names the setting, the path and why (exit 2). |
| `WORKCENTER_LOCK` | `off` or empty | empty (on) | `off` (or `0`, `no`, `false`): no command takes the lock or waits on it. |
| `WORKCENTER_LOCK_EVERY` | seconds | `30` | How often a waiting run repeats its line (at least 0.05). |

| Flag | Commands | Default | Use |
|---|---|---|---|
| `--json` | all | off | Machine-readable output. Read before the command or after it. `gates --json`: stdout holds the gates' records alone; the ratings line and the verdict line go to stderr. |
| `--out DIR` | gates, erc, drc, sim, export, autoroute, render, procure, sources, verify, ratings, copper, fields, highspeed; design; ci | `<project>/build`; design: the design file's folder (with `--check`, a temporary folder); ci: `<repo>/build/ci` | Where reports and artifacts go; for design, where the KiCad project is written; for ci, each step's script, `$GITHUB_ENV` file and log. |
| `--strict` | gates, erc, drc, sim, export, render, procure, sources, verify, ratings, copper, standards, legend | off | Warnings fail the gate; for gates, ratings that are not held (`RED (ratings not held)`), for a project with a `ratings.json`; for ratings, a stress that was not judged; for copper, a net with a stated current, or named in `ratings.json`, that `copper.json` does not name, a pin of a judged net with no stated current, a pin of the entry's part that `from` does not name, a part's heat with no pad on the board, or a limit it does not state; for verify, a requirement whose verdict is FAIL or OPEN, and decks that ran without corners; for render, a part the 3D views draw without a body fails it; for procure, a line short of stock or a price older than 90 days; for sim, a model outside a `warn` bound (its datasheet), a project with no `sim/corners.json` or with decks that drive periodic sources and no `sim/frequency-plan.json`, a deck with no bound, a deck whose measures do not move with temperature, a part named like a board reference that no tolerance covers, and an operating point ngspice doubts (`singular matrix`), and a circuit the schematic implies that no deck answers (an I2C line with a pull-up, a regulator with a load stated in ratings.json; tools/simneeds.py); for sources, a datasheet kept as a note only, a file with no SHA256 or revision recorded, a model older than its datasheet, or a load check skipped; for standards, a requirement not held. |
| `--parts FILE` | procure, sources, ratings | `<project>/parts.csv` | A parts CSV, repeatable; the first row whose Value and Footprint match a BOM line prices it (procure) or names its MPN (sources, ratings), and every row with no Footprint is an item off the board. Columns in the `procurement` skill. |
| `--init` | ratings | off | Write `ratings.json` beside the schematic, with the pack `nasa-eee-inst-002` and no net, when there is none; never over a file that exists. Nothing is judged, and no output folder is made. |
| `--facts REF` | ratings | none | Print an entry of facts to fill for 1 part of the schematic: its part number or its symbol, its pins, an empty source. Nothing is judged: the netlist it reads is left in `<out>/ratings/`, with no record and no page of a run. |
| `--index FILE` | references | `rules/references/index.json` | The index of the documents the rules cite. |
| `--to DIR` | references fetch, references check | `$XDG_CACHE_HOME/ee-workcenter/references` when that variable is an absolute path (a relative one is ignored: XDG Base Directory Specification 0.8, section 2), else `~/.cache/ee-workcenter/references` | The folder the copies and `ledger.json` go to. Refused when it lies inside a repository (a `.git` in it or above it) or is a file. |
| `--again ID` | references fetch | none | Ask once more for a document the ledger already holds an answer for; repeatable. |
| `--id ID` | references check | found by the file's SHA256 | The entry the downloaded file should be. |
| `--keep` | references check | off | File a downloaded copy that is the indexed one in `--to`, as `fetch` would have. |
| `ID`, `PATH`, `FILE` | references fetch, references rules, references check | fetch: every id of the index; rules: the globs the index lists under `rules` | fetch: the ids to ask for; rules: the rule files or folders to read; check: the downloaded file. |
| `--sources FILE` | sources, fetch | sources: the nearest `library/sources.csv` at or above the project; fetch: the nearest `sources.csv` at or above `--to` | The library's manifest: one row per datasheet, SPICE model or STEP file, the files beside it (`WORKCENTER.md`, "Project requirements"). The SIM gate finds it the same way. For fetch, a file not there yet is started with the header. |
| `--deck NAME` | sim | every deck | Run only `sim/NAME.cir` (with or without `.cir`), the gate's way: the model rows' translation and mode, the expect bounds, the deck's corners. Prints every value the deck printed, with its bound and its least and greatest value over the corners. The frequency plan is not judged: it needs every deck. An unknown name is an error that lists the decks. |
| `--keep` | sim | off | Run each deck from `<out>/sim/run/<deck>/`, a deck the gate runs in place too (with the deck folder's own `.spiceinit`), leave the folder, and print the one command that reruns it by hand: `env -C <run folder> ngspice -b <deck>.cir` (M94). |
| `PROJECT` | next | none | The project directory. `next` prints the one next step for it: `NEXT` (what to do), `RUN` (the command), `WHY`, `READ` (the section that explains it) and `DONE WHEN`; with `--json`, the same as an object. Exit 0 when nothing is left, 1 when a step is; a finished project gets no `RUN` line. It reads `build/gates.json` and `build/verify.json` and writes nothing. |
| `--trust-design` | next | off | Do not run `design --check` on the project's design file. That check takes a few seconds and needs the KiCad libraries; without it the KiCad files are taken to match the design file. |
| `--nominal` | sim | off | Run each deck as written only. The corners of `sim/corners.json` are left out, and the result names that as a warning, so a quick run is never taken for a full one. |
| `--bundle DIR` | sim | none | Also write each deck into `DIR/<deck>/` as a folder any machine with ngspice runs: `run.sp` (sets the mode the models need, changes to its own folder, then reads the deck), the deck with its includes pointing into `models/`, every included file there (the translated copy where its row lists fixes), the other files of the deck's folder, `expect.json`, `measures.json` and `README.md`. The command then runs each folder from a copy in another place with an empty home folder and fails when a measure differs from the gate's (M105). An earlier bundle in `DIR/<deck>/` is replaced; a folder of that name that holds no `run.sp` is refused. The receiver runs `ngspice -b run.sp`. |
| `URL` | fetch | none; give it or `--file` | The maker's URL for one file. Fetched once under the workcenter's own user agent; a refusal is reported and never retried. A body that is empty, cut short, served as `text/html`, starting as an HTML page, or a `.pdf` that does not start `%PDF` is refused and nothing is written. |
| `--to FILE` | fetch | none (required) | Where the library keeps it, `<library>/<maker>/<file>`. An existing file that differs from the download is refused; the same file is left as it is. |
| `--file FILE` | fetch | none | A file a person downloaded, taken instead of a fetch: judged like a fetched body, copied into `--to`, hashed, and its row's Note says the workcenter did not fetch it. Needs `--url`; refused with a URL argument. With `--member`, the member is read out of the zip and kept. |
| `--url URL` | fetch | none | With `--file`: where the person downloaded it from; it is the row's `URL`. Refused without `--file`. |
| `--mpn MPN` | fetch | none | The part number the row names. Needed for `--row`. |
| `--kind KIND` | fetch | from the file's suffix: `.pdf` datasheet, `.lib` `.mod` `.cir` `.sub` `.spi` `.sp` `.ckt` spice, `.step` `.stp` step | `datasheet`, `spice` or `step`. A spice file that defines one `.SUBCKT` fills the row's `Subckt`. |
| `--member NAME` | fetch | none | The file inside a zip at the URL; the row records it in `Member`. |
| `--row` | fetch | off | Append the row to `sources.csv`, as text after the file's own bytes and in its line ends. Refused, before any request, when the MPN already has a row of that kind. With no `sources.csv` at or above `--to`, and `--to` under a folder named `library`, it starts that folder's `sources.csv` with the header and prints `sources: started <path>`. `Revision` and `Dated` stay empty for the reader to fill from the file. |
| `PDF` | curve | none | The datasheet. |
| `--page N` | curve | `1` | The page, counted from 1. |
| `--frame X0,Y0,X1,Y1` | curve | none | The plot's frame in PDF points, y up (the listing names each stroked rectangle as a candidate). Without it, the command lists the page's paths grouped by kind, width, paint and colour, the frames and the numeric labels. |
| `--x SCALE:MIN:MAX` | curve | none | The x axis from `X0` to `X1`: `log:0.1:100` or `lin:0:5`. Goes with `--frame` and `--y`. |
| `--y SCALE:MIN:MAX` | curve | none | The y axis from `Y0` to `Y1`. |
| `--paths IDS` | curve | every path of 4 points or more inside the frame | The path ids (`#N` in the listing) to map, comma-separated. |
| `--at X,...` | curve | none | Print each curve's y at these x values, interpolated in decades on a log axis. |
| `--at-y Y,...` | curve | none | Print each curve's x at these y values. |
| `--check` | design | off | Regenerate into a temporary folder (or `--out`) and compare the `.kicad_pro` and `.kicad_sch` with the design's own, as a board repository's CI does, and the project's `fp-lib-table` and `sym-lib-table` with what the design writes in its own folder. Exit 1 on a difference or on the design step's own exit 1 (M85). Writes nothing in the project. Refuses `--route`. |
| `REPO` | ci | `.` | The repository whose `.github/workflows/*.yml` the replay runs, from its root, as the runner's checkout. |
| `--job ID` | ci | every job, each after the jobs it `needs` | Replay only this job (repeatable). |
| `--workflow FILE` | ci | every workflow | One workflow: a file name in `.github/workflows/` or a path. |
| `--skip REGEX` | ci | `(?i)\b(install\|upload)` | Skip the steps whose name matches; `uses:` steps are always skipped. A step whose `${{ }}` the replay cannot read (only `env.*`, `github.workspace`, `runner.temp` and `runner.os` are read) is red until its name is skipped. |
| `FIRMWARE` | mutate | none | The firmware folder the test command runs in; each mutation gets its own copy, without `build/`. |
| `--mutations FILE` | mutate | none (required) | The project's list. JSON: `[{"name", "file", "old", "new"}]` or `{"test": CMD, "mutations": [...]}`. Python: a top-level `MUTATIONS = [(name, file, old, new), ...]` and an optional `TEST = "..."`, read as literals and never run. Every `old` must be in its file exactly once; the command checks each before running any. |
| `COPY` (Python) / `copy` (JSON) | mutate | the whole tree but `build/` | The paths, from the tree's root, each copy holds. A path that is absolute or holds `..`, a path that is not there, and a mutation of a file no `COPY` path holds are refused before anything runs. |
| `--test CMD` | mutate | the list's `test`, else `make -k test` | The test command, run under `bash -c` in each copy. It must pass unmutated. A mutation that fails it is caught; one that a compiler's `file:line: error:` stops did not build, and fails the run as a survivor does. |
| `--only TEXT` | mutate | every mutation | Run only the mutations whose name holds this text (repeatable). |
| `--jobs N` | mutate, sim | mutate: `1`; sim: one per processor, 8 at most | Mutations run at once; for sim, corner runs of one deck at once. A whole number, 0 or more: anything else is a usage error, exit 2. |
| `--work DIR` | mutate | a temporary folder, removed after | Keep the copies here, one folder per mutation. |
| `--fetch` | sources | off | Read each row's URL once more under the workcenter's own user agent into `<out>/sources/fetched/` and report each as same, changed, new, refused, gone or unreachable; a refusal is never retried. The library is not written. |
| `--package DIR` | verify | `<project>/verification` | The verification package (`PROCESSES.md` P28): requirements, system, simulations, calculations, traceability. |
| `--init` | verify | off | Copy `templates/verification/` into the package and a writeup per `sim/*.cir` into `simulations/<deck>/`, never over a file that exists. `BRIEF.md` and `FACTS.md`, the helpers' brief and facts file, stay out. The new files fail the check until each `<!-- fill ... -->` is written. |
| `--boards LIST` | procure, costs | `1,10` | Units to price, comma-separated; each gets its cheapest order and totals per supplier; for costs, a column each in the totals table, the largest also judging stock. |
| `--step` | gates, export | off | Also export a STEP model. |
| `--fab NAME` | gates, drc, legend | none | Also check a fab's limits: a rule set in `rules/` (`sierra-circuits-web`, `jlcpcb-2layer`, `pcbway-standard`, `oshpark-2layer`) or a `.kicad_dru` path, laid over the project's own rules on a copy in `<out>/fab-<name>/`. A design file's `fab` field does the same for good (`rules/README.md`). |
| `--place OUT` | legend | none | Write a copy of the board to OUT (`.kicad_pcb`), every designator placed round its part; the project is not changed. |
| `--show` | legend | off | Put every hidden designator back on the silkscreen first, where its footprint has it. |
| `--dsn FILE` | autoroute | `<project>/<name>.dsn`, then `build/route/<name>.dsn` | Specctra DSN exported from KiCad. Absent means the command skips. |
| `--passes N` | autoroute, design, bench | `20` autoroute and bench, `60` design | FreeRouting optimisation passes. bench takes a whole number above 0. |
| `--threads N` | autoroute, design, bench | engine default; bench `2` | FreeRouting thread count (`-mt`). bench takes a whole number above 0 and also holds the JVM to N processors. |
| `--order` | design (with `--route`), bench | off | design: route in 4 stages, 1 FreeRouting run each, each on the copper of the stages before it: poured nets and every net with copper drawn by hand, the nets of each part of 0.5 mm pitch or less, pairs (names that end in `_P`/`_N`, `D+`/`D-` or `DP`/`DN`), the rest. Writes `build/route/<name>.<n>-<stage>.dsn`, `.ses`, `.log`. Refuses `--seed`. bench: also run each router as `<router>+order`. |
| `--router NAME` | design (with `--route`), bench | design: `freerouting`; bench: the workcenter's FreeRouting | design: the router, `freerouting` (FreeRouting 1.9.0) or `freerouting2` (FreeRouting 2.5.0). bench: a router by name, or `NAME=JAR` for a FreeRouting 1.9.0 jar, repeatable; the first is the default router. |
| `--time-limit S` | bench | `300` | Seconds per route, a whole number above 0; a route past it is stopped and not judged (exit 2). |
| `--out DIR` | bench (required) | none | The benchmark's folder: `<board>/<router>/` with the board, `route.txt`, `drc.txt` and `run.json`, and `bench.md`. A run empties its own folder first. |
| `--strict` (highspeed) | highspeed | off | A limit not judged fails the run: one the documents do not set, and one they set that the command does not judge (TI's single-ended impedance and stubs, among others). |
| `--verbose` | highspeed | off | Print the rules that held too. |
| `--item` | now | none (required) | A roadmap item's number, whose title is read from `ee-agent-kit/ROADMAP.md`, or 1 line for work with none. The issue's title is `Work card: <it>`. |
| `--status` | now | none (required) | The project board's word: `Todo`, `In progress` or `Done`, in any case. Work that waits on someone stays `In progress`. |
| `--doing` | now | none | 1 line of what is done now; repeatable, 3 at most. |
| `--blocked` | now | `nothing` | Who or what the work waits for. |
| `--left` | now | `nothing` | 1 thing left; repeatable. |
| `--title` | now | off | Print the issue's title, `Work card: <the work>`, and nothing else. |
| `--write` | now | off | A checkout of the `status` branch: the card goes under its title to its `now/<branch>.md`. |
| `--spec FILE` | fields | `<project>/fields.json` | The groups of nets, each group's band and its limits, each limit with its `source`. |
| `--model` | fields | off | Write each group's `model.json` and the engine's input under `<out>/fields/<group>/`; run nothing. |
| `--strict` (fields) | fields | off | A limit that is not judged fails the run. Without it the run exits 2 when no limit was held (`no limit stated: nothing judged`). |
| `DESIGN` | bench | none: rebuild `bench.md` from `<out>` | The design files to route. |
| `PROJECT` | measure | none | The project whose plan of measurements to write: `<out>/measure/plan.md` and `plan.json`, from a fresh SIM run. `--out DIR` names the output folder (default `<project>/build`). Exit 1 when a bound is not planned. |
| `--timeout S` | autoroute, design, mutate | `600` autoroute, `900` design, `600` mutate | Kill the router after S seconds; for mutate, a test run past it counts as caught (the tests did not pass). |
| `--route` | design | off | Export the DSN, run FreeRouting, merge the session before writing. |
| `--rounds N` | design | `4` | Route again, up to N rounds, with a via reserved beside each pad a pour lost. |
| `--seed BOARD` | design (with `--route`) | none | A routed `.kicad_pcb`, read only, usually the previous version's: its router tracks and vias go to FreeRouting held (`shove_fixed`: pushed aside, never ripped up), so the router keeps the paths that still fit and routes only the rest; seed copper that hangs from nothing goes in unfixed. Left out first and counted: the design's own hand copper, nets the design lost, stitching vias, arcs, and copper that now meets another net's pad or copper, a keepout or the board edge. Prints a `seed:` line with the counts and how many tracks the new route kept. |
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
| `--report FILE` | gates | none | Also write the gates table and the deck list into FILE (a version's `docs/gates.md`) between `<!-- workcenter gates NAME -->` and `<!-- workcenter decks NAME -->` markers, NAME the project's `.kicad_pro` name; the prose outside them stays. The one file a gate run writes outside `--out`. |
| `--library DIR` | docs | the nearest `library/` at or above the version | The library whose `sources.csv` names each part's datasheet; a `series.csv` beside it (`Pattern,MPN`) names the parts a series sheet covers. |
| `--lists DIR` | docs | `<repo>/parts/lists` | The priced lists `costs` writes, `<id>.csv` and `<id>.md` per board. |
| `--frames N` | pictures | `0`, off | The framing check: each GIF drawn with N frames into `build/pictures/check/` with one sheet of its frames; scene scripts draw no stills; `docs/` is not written. |
| `--from VERSION` | version new | the latest version folder | The folder the new version copies. |
| `--out FILE` | diagram | required | The SVG to write. |
| `--png` | diagram | off | Also write `<out>.png` with `rsvg-convert`, at the drawing's width. |

## `tools/enginelock.py` (the engine lock)

A long command waits its turn on the machine's engine lock and holds it to its end. The other
commands never take it and never wait. `tools/enginelock.py` names each command of
`workcenter --help` in `LONG` or in `SHORT`, and `tests/test_enginelock.py` fails on a command
named in neither. A command is long when it ran over 3 s on the largest input measured, or when
the project and not the command sets its length (a deck's transient, a corner list, a mutation
list, a router's time limit).

| Flag | Of | Default | Meaning |
|---|---|---|---|
| `hold -- CMD` | enginelock.py | | Run CMD under the lock. The exit code is CMD's (128 and the signal for a command a signal killed). |
| `--what NAME` | enginelock.py hold | the command | The name the waiting line and `doctor` show for this run. |
| `held` | enginelock.py | | Exit 0 when this process may run a long command without waiting (the lock is off, or the holder is this process or an ancestor), else 1. |
| `state [--json]` | enginelock.py | | Who holds the lock, since when, and how many wait. |

Times measured on 2026-11-18 on this machine (4 processors, other agents running) with
`WORKCENTER_LOCK=off`, on copies of the fixtures under `tests/boards/` and `tests/chips/` and of
Last Hit v0.16: the wall time of 1 run. The Last Hit rows of `sim`, `measure` and `verify` are from
a 2nd copy that keeps `library/` and `parts/` beside `v0.16/`, where all 12 decks ran; each of those
exited 1 on the board's own findings.

| Command | Takes the lock | Measured | On |
|---|---|---|---|
| `design --route` | yes | 5.25 s | pass-first-design |
| `gates` | yes | 4.01 s; 14.39 s | pass-rc-divider; Last Hit v0.16 |
| `sim` | yes: its length is the decks' and the corners' | 0.43 s; 11.15 s | pass-rc-divider; Last Hit v0.16 (12 decks) |
| `measure` | yes: it runs the project's sim, every deck and corner, as `sim` does | 0.38 s; 11.47 s | pass-rc-divider; Last Hit v0.16 (12 decks) |
| `legend` | yes: it starts no engine, but judges every text against every other | 6.14 s; 14.95 s (`--show --place`); 0.26 s | a copy of basalt v0.3 (179 parts); the same; pass-legend-dense |
| `export` | yes | 2.52 s; 4.98 s | pass-rc-divider; Last Hit v0.16 |
| `render` | yes | 38.93 s | pass-rc-divider |
| `pictures` | yes: it runs `render` for each board | not measured | |
| `copper` | yes | 16.45 s | pass-copper-strip |
| `highspeed` | yes | 10.58 s | pass-highspeed |
| `fields` | yes | 10.22 s | pass-fields-microstrip |
| `inspect map` | yes | 7.00 s | Last Hit v0.16 |
| `chip` (all but `chip init`) | yes | 38.17 s (`chip gates`) | tests/chips/pass-counter |
| `mutate` | yes | 1210.74 s (`--jobs 4`) | Last Hit v0.16 firmware |
| `verify` (not `--init`) | yes: it runs the decks again | 11.23 s | Last Hit v0.16 (12 decks) |
| `autoroute` | yes: FreeRouting, as `design --route` | not measured | |
| `bench` | yes: it routes each board with each router | not measured | |
| `ci` | yes: it replays a workflow, `make verify` among its steps | not measured | |
| `design` (no `--route`) | no | 1.51 s | pass-first-design |
| `drc` | no | 0.84 s; 1.21 s | pass-rc-divider; Last Hit v0.16 |
| `erc` | no | 0.49 s; 0.60 s | pass-rc-divider; Last Hit v0.16 |
| `sources` | no | 1.36 s | Last Hit v0.16 |
| `costs` | no | 0.77 s | the Last Hit repository |
| `doctor` | no | 0.69 s | |
| `procure` | no | 0.54 s | Last Hit v0.16 |
| `placement` | no | 0.53 s (`pin_sides`); 0.48 s (`placement_audit`) | Last Hit v0.16 |
| `ratings` | no | 0.47 s | pass-ratings-node |
| `inspect` (all views but `map`) | no | 0.47 s (`list`) | Last Hit v0.16 |
| `now` | no | 0.26 s (it refused: no `--item`) | this tree |
| `standards` | no | 0.24 s | pass-layout with a `product.json` |
| `references` | no | 0.22 s (`check`) | tests/boards/references/pass/pack.json |
| `docs` | no | 0.21 s | Last Hit v0.16 |
| `diagram` | no | 0.21 s | Last Hit v0.16 |
| `next` | no | 0.18 s | pass-rc-divider |
| `new` | no | 0.17 s | an empty folder |
| `fetch`, `curve`, `version` | no | not measured | |

A waiting command prints, on stderr, 1 line at once and 1 every 30 s:

    workcenter: waiting on the engine lock: 2 runs ahead; held by `workcenter gates v0.16` (pid 4242) since 10:02:13, 3 min 5 s ago; lock folder /tmp/workcenter-lock-0

and `workcenter: took the engine lock after 4 min 12 s` when it starts. A run that ended while an
engine it started still runs is named `..., which ended; 1 process it started still runs (pid N)
and keeps the lock until it ends`. A run stopped by SIGTERM or SIGHUP prints
`workcenter: stopped by signal 15 (SIGTERM) after waiting ...` (or `after holding the engine lock
for ...`) and frees its place; a holder first passes the signal to the processes it started and
adds `; passed it to 1 process it started`. A run killed by SIGKILL frees its place when the last
process it started ends. `workcenter doctor` prints `engine lock  free (<folder>)`, or
`held by ... since ..., N waiting (<folder>)`, or `not judged: <why>`; `workcenter --json doctor`
carries `engine_lock`.

How to use it:

1. Run the command as it is. No `flock` in front.
2. A line `waiting on the engine lock: N runs ahead` means the command waits its turn. Do not
   start it again. Read the next line in 30 s; `N` falls as the runs ahead end.
3. `workcenter doctor` names the holder and how many wait.
4. A command that is not a `workcenter` command and starts an engine (a bare `kicad-cli`,
   `ngspice`, a `pytest` file of engine tests) runs as
   `python3 tools/enginelock.py hold --what "<name>" -- <command>`.
5. A script that holds the lock and starts a long command through a process that is not its
   child or grandchild (a service, a process reparented to init) waits on itself forever: run
   the command as a child, or with `WORKCENTER_LOCK=off`.

## `ratings.json` (beside a schematic, for `workcenter ratings`)

| Field | Type | Default | Use |
|---|---|---|---|
| `pack` | name or path | none (required) | The rule pack: a file of `rules/ratings/` without `.json` (`nasa-eee-inst-002`, `ecss-q-st-30-11c-rev2`), or the path of a pack from the project's folder. |
| `nets` | object | none (required) | Each net a source off the board holds: `{"volts": [least, greatest], "source": "..."}` under the net's name, with or without its sheet's slash; 1 net named both ways is refused. `[0, 0]` is the reference. |
| `ambient` | object | none | `{"max": C, "source": "..."}`: the highest air temperature. A limit that falls with temperature is judged there. |
| `parts` | object | none | What the board cannot say of a part: `REF.PIN` with `amps` for the load behind a connector's pin, `REF` with `amps` for the current through a part (RMS for a resistor, a transistor, a fuse, a ferrite and a switch, the average for a diode, the peak for an inductor), `REF` with `volts` for the greatest voltage across a capacitor or a resistor whose 2 nets move together; each with a `source`. A number the command would hold to nothing is refused once the part has facts: the `ratings` skill lists them. `REF` or `REF.PIN` with `watts`: the heat a part gives off, W, split over its pads by copper area, or on 1 pad (`U1.2`), the heat that leaves by that pad; not both for 1 part. `workcenter copper` reads it; `ratings` does not judge it. A 2-pin resistor with `amps` (on the part or on a pin) and a numeric Value gives I^2 R itself. |
| `accepted` | list | none | Failures the owner takes on: `{"part", "rule", "why", "by"}`, `by` as `the owner's decision of YYYY-MM-DD`. An entry accepts 1 failure: where 2 of 1 part stand under 1 rule, `line` holds words of the line the entry means. An entry nothing fails under fails the run. |
| `not_judged` | object | none | Items a block or the designer could not judge: under each item's name, `{"parts": [...], "why": "...", "source": "..."}`, `parts` a list of parts of the schematic. Each is printed as `not judged <name>: <why>`; `--strict` fails on it. The charger block writes it. |

A part's facts are 1 entry of a file in `library/facts/`, in the project's
folder or a folder above it; a rule pack is 1 file of `rules/ratings/`. The
`ratings` skill has every key of both.

An inductor's facts may give `ohms_dc`, its DC resistance at the most, in ohms (0 or more); `blocks.buck` reads it in its dropout sum. A pin of role `input`, `io` or `open_drain` may give `farads`, its greatest capacitance, and a pin of role `io` or `open_drain` `sink`, `{"amps", "volts"}`, the current it sinks at that low voltage; `blocks.i2c` reads both. A part of kind `crystal` gives `hertz`, `ohms_esr` and `farads_load`, and may give `farads_shunt` (C0 typical), `farads_shunt_max` (C0 at the most), `watts_drive` and `terminals` (the 2 pads of the crystal and where its datasheet says so); `blocks.mcu` reads them, and `workcenter ratings` judges none of them.

The SIM gate reads these keys of a part's facts, from an entry that names the
part by `mpn` or `mpns` and whose `source.sha256` is a row of
`library/sources.csv`:

| Key | Facts of | Type | Use |
|---|---|---|---|
| `kept` | a capacitor | pairs `[volts, share of the value kept]` | The maker's DC bias curve; the volts rise from pair to pair; each share above 0 and at most 1.5. `workcenter ratings` reads it too. |
| `kept_celsius` | a capacitor | pairs `[celsius, share against 25 C]` | The maker's temperature curve; each share above 0 and at most 1.5. |
| `kept_celsius_at` | a capacitor | `{"volts": V, "kept": [[celsius, share against 0 V and 25 C], ...]}` | The maker's temperature curve at 1 bias; at that bias the share is the maker's. Refused when its 25 C share is nearer 1 than the share `kept` gives at its bias, when it does not reach 25 C, or when the part has no `kept`. |
| `esr` | a capacitor | `{"ohms": R, "hz": f}` | Series resistance at the frequency it was read at; the SIM gate writes it in series. |
| `esl` | a capacitor | `{"henries": L, "hz": f}` | Series inductance from a figure the maker gives; the SIM gate writes it in series. |
| `kept` | an inductor | pairs `[amps, share of the value kept]` | The maker's L vs current curve; each share above 0 and at most 1.5. |

## `interfaces.json` (beside a board, for `workcenter highspeed`)

| Field | Type | Default | Use |
|---|---|---|---|
| `interfaces` | list | none (required) | Each entry: `interface`, a file of `rules/interfaces/` without `.json` (`usb2`, `usb3`, `ti-am57xx-usb2`, `ti-am57xx-usb3`); `nets`, the pair's 2 nets; optional `gap` (mm, above 0). The command measures each pair's gap on the board and fails a `gap` the board does not have. An empty list is refused. |

## `build/verify.json` (written by `make verify`)

| Field | Type | Default | Use |
|---|---|---|---|
| `--head`, `--dirty`, `--tree` | flags of `python3 tools/now.py record <code> <step>` | `--tree .` | What `verify/verify.sh` runs on exit: the commit the gate started on, whether the tree differed from it then (`yes` or `no`), the repository's root. |
| the file | object | none until a gate has run | Written by `verify/verify.sh` on exit: gate, verdict (GREEN on exit 0, else RED), last step, the commit it started on, branch, dirty (at the start or the end, untracked files included), moved_to (the commit HEAD moved to during the run, or null), UTC time. Ignored by git. `workcenter now` reads it, and refuses a record that does not have this shape. |

## `make scope`, `make verify-site` and the `engine` marker

| Field | Type | Default | Use |
|---|---|---|---|
| `SCOPE_BASE` (make) | git ref | `origin/main` | `make scope` compares the working tree with `git merge-base SCOPE_BASE HEAD`. |
| `WORKCENTER_NO_ENGINES` | `1` or unset | unset | `1` refuses every engine start in a test run (`make verify-site` sets it): the start raises FileNotFoundError, read as an absent engine. |
| `WORKCENTER_ENGINE_LOG` | path | a temp file per pytest run | Where each engine start of a test run is written; the `engine` marker is held against it. |
| `--repo`, `--base`, `--head`, `--paths`, `--github-output` | `tools/ci/scope.py` flags | repo: here; head: the working tree | The change to judge; an empty `--base` is full; `--github-output` appends `scope=<answer>` to `$GITHUB_OUTPUT`. |

## `verify/testshards.py` and `verify/shards.csv` (the tests step of `make verify`)

| Field | Type | Default | Use |
|---|---|---|---|
| `verify/shards.csv` | CSV: `file`, `seconds`, `engine`, `alone` | 68 rows and `*` | Each test file's seconds in a shard, whether it starts an engine (its `no` files run first in a shard), and why it must run alone (it runs in the shard `serial`, after the others). `*` is the row for a file not listed (41.9 s). `verify/README.md` says how to keep it true. |
| `--jobs` | flag of `verify/testshards.py run` | the processors (`os.cpu_count()`) | How many shards run side by side. |
| `--work` | flag of `verify/testshards.py run` | a new folder under `$TMPDIR` | Where the shards' logs go. A folder named here is kept, and must be empty or new; a folder of its own is deleted when green and kept when red. |
| `--table` | flag of `verify/testshards.py run` and `table` | `verify/shards.csv` | The table the files are split by, or written from. |

## The workflow Board (`.github/workflows/board.yml`, `tools/board.py`)

| Field | Type | Default | Use |
|---|---|---|---|
| `BOARD_TOKEN` | repository secret | none | A classic personal access token with the `project` and `repo` scopes; the board is changed with it. Without it the job prints 1 line and ends green. |
| `BOARD_URL` | repository variable | `https://github.com/users/ThyFriendlyFox/projects/2` | The project board the work cards stand on (`https://github.com/users/<login>/projects/<n>` or `https://github.com/orgs/<login>/projects/<n>`). |
| `--event` | flag of `tools/board.py` | 1 of `--event` and `--all` is required | The issues event's JSON file (`GITHUB_EVENT_PATH`): that 1 card. |
| `--all` | flag of `tools/board.py` | off | Every work card of `--repo`, open and closed; the workflow passes it on its schedule and when run by hand. |
| `--repo` | flag of `tools/board.py` | required with `--all` | The repository, `<owner>/<name>` (`GITHUB_REPOSITORY`). |
| `--board` | flag of `tools/board.py` | required | The project's URL. |

## `copper.json` (beside a board, for `workcenter copper`)

| Field | Type | Default | Use |
|---|---|---|---|
| the file | object | none: the command stops with `no copper.json beside <board>` | The limits of `workcenter copper`. The currents and the heat come from `ratings.json`. |
| `air` | object | none (required) | `ambient` C, above -234.5; optional `h` W/m2 K (10, TI SNVA419C table 1, page 4); `source`. A stated assumption. |
| `temperature` | object | none: not judged | `max` C and `source`: the greatest board temperature. |
| `grid` | object | `drop` 0.05, `heat` 0.25 (mm) | `drop` no wider than the narrowest track of a judged net; `heat` a whole number of `drop`. |
| `plating` | object | the board's own setting | `mm` and `source`: the copper in each barrel. |
| `nets` | object | none (required) | For each power net: `from` (`REF.PAD`, the entry, or a list of them), optional `volts` and `amps_per_mm2` (`max`, `source`; `amps_per_mm2` holds the copper and each barrel). |

## `fields.json` (beside a board, for `workcenter fields`)

| Field | Type | Default | Use |
|---|---|---|---|
| `engine` | name | `openems` | The field solver. |
| `reference` | net | `GND` | The net whose pours are the reference planes. |
| `groups` | list | none (required) | Each group: `name`, `nets`, `kind` (`lines`, the default, or `antenna`), `band_ghz` `[low, high]`, optional `ports` (pads that name a net's ends), and `limits`: `{"measure", "net", "min" and/or "max", "source"}`, the measure one of `impedance_ohm`, `return_loss_db`, `insertion_loss_db`, `next_db`, `fext_db`. |
| `settings` | object | `margin_mm` 3, `cells_per_wavelength` 20, `cells_across_width` 3, `cells_per_dielectric` 4, `port_ohm` 50, `frequencies` 201, `end_criteria_db` -40, `absorbing_cells` 8, `max_timesteps` 200000, `timeout_s` 3600 | The model and the run. `cells_across_width` is the cells across a straight track inside its metal; its edges lie a third of a cell inside the outer 2 lines. `cells_across_width`, `cells_per_dielectric`, `absorbing_cells` and `max_timesteps` are whole numbers of 1 or more, `frequencies` 2 or more, `end_criteria_db` below 0 (openEMS itself runs 10 dB further). |

## `sim/thermal.json` (for the SIM gate's junction temperatures)

| Field | Type | Default | Use |
|---|---|---|---|
| `pack` | name or path | none (required) | The rating pack whose `junction.temperature` rules give the derated limit: a file of `rules/ratings/` without `.json`, or a path from the project's folder. |
| `parts` | object | none (required) | `{"U1": {"mpn": ..., "watts": "deck.measure", "source": ...}}`: each part's number and the deck measure that prints its power. No file: no junction is judged. |

A part's facts take `thermal` on an `ic`, a diode or a MOSFET:
`{"junction_max": C, "page": n or [n, ...]}` and 1 or more of `theta_ja`,
`theta_jc`, `theta_jb`, `psi_jt`, `psi_jb` in C/W. Only `theta_ja` is
judged. A pack's rule of stress `junction.temperature` holds `celsius`,
`share` or `below_rating`, 1 at least; the limit is the least of those it
names.

## `panel.json` (beside a board, for EXPORT)

| Field | Type | Default | Use |
|---|---|---|---|
| the file | KiKit preset, JSON with `//` comments | none: no panel | Asks EXPORT for a panel through KiKit 1.8.1's `doPanelization`, its Gerbers and drill files, and a check of the count of boards against rows x cols and of a closed outline at least their size. Only a `grid` layout is judged. Without KiKit the panel is not judged and EXPORT is SKIPPED, exit 2. `tests/samples/fab/panel.json` holds kistack's starting values with their source. |

## `board-rules.json` (beside a board, for `workcenter drc` and `gates`)

| Field | Type | Default | Use |
|---|---|---|---|
| `pack` | name or path | none; required when there is no `layout` and no `creepage` | The board rule pack the DRC holds the board to: a file of `rules/board/` without `.json` (`ecss-q-st-70-12c-rev1`), or the path of a pack from the project's folder. The volts and amps come from the project's `ratings.json`, which must stand beside the board. No file: no pack. |
| `via_wall` | `{"um": number, "source": text}` | none: no stated wall | The least copper of a via's wall the fab promises, um, with the fab's document, the place and the date read. Under half the least drill of a judged via, or the file is refused. With `hdi` the lesser of it and the pack's 25 um is taken. |
| `hdi` | `{"source": text}` | none: not HDI | The order or document by which the board is built as HDI under ECSS-Q-ST-70-12C Rev.1, 11.6. The pack's 25 um wall then holds its vias (tables 11-1 and 11-2, page 100). A via's KiCad flag never makes a board HDI. |
| `layout` | list of layout pack names | none | The layout packs the DRC gate holds the board to (`rules/board/`, `"kind": "layout"`): `ti-slva680a-esd`, `ti-szza009-emi`. With or without `pack`. |
| `creepage` | `{"pack": name or path, ...conditions}` | none | The creepage pack the DRC holds every pair of nets to (`rules/board/`, `"kind": "creepage"`), with the conditions it asks. `mil-hdbk-454c-g69` asks `condition` (A, B or C) and `enclosure` (I or II); `ti-slup419-creepage` asks `pollution_degree` ("1" or "2") and `material_group` (I, II or III). With or without `pack` and `layout`. The voltages come from `ratings.json` beside the board. |
| `connectors` | object, reference: why | none | The connectors that leave the device; asked by `ti-slva680a-esd`. A part with a reference J, P or X and digits, or a footprint in a `Connector...` or `TerminalBlock...` library or the `Battery` library, must be named here or under `inside`. |
| `inside` | list of references | none | Connectors that stay inside the device; not judged for ESD. |
| `protectors` | object, reference: what | none | The parts that protect against ESD; each needs a pad on a `ground` net. |
| `ground` | list of nets | none | Ground nets: their connector pins need no protector, and they are judged by the 3:1 rule. |
| `power` | list of nets | none | Power nets held to `ti-szza009-emi`'s 3:1. |

## `product.json` (beside a board, for `workcenter standards`)

| Field | Type | Default | Use |
|---|---|---|---|
| `kind` | a file of `rules/products/` without `.json` | none (required) | The product kind whose requirements `workcenter standards` lists (`vaping-device-lithium-cell`). |
| `tests` | object, requirement: [IDs] | none | The IDs of the verification package whose PASS in `verification/traceability.md` holds a requirement. |

## `rules/legend.json` (for `workcenter legend` and the DRC gate)

The workcenter's own numbers for the legend; none is from a standard. The least height and stroke come from the fab's rule set in `rules/`.

| Key | Type | Default | Use |
|---|---|---|---|
| `designator_reach_mm` | mm | 2.0 | A designator further than this from its own part's courtyard fails `nearest`. |
| `placer_gap_mm` | mm | 0.15 | The gap the placer leaves between a designator and its part's courtyard. |
| `size_step_mm` | mm | 0.1 | The placer's step down in text height, to the fab's least. |
| `directions_per_side` | count | 2 | More directions on 1 side fail `direction`. |

## `rules/references/index.json` (for `workcenter references`)

| Key | Type | Default | Use |
|---|---|---|---|
| `rules` | list of globs from the repository's root | none | The rule files `references rules` reads with no PATH: JSON rules, facts and `.kicad_dru` files. |
| `code` | list of globs from the repository's root | none | The tool code and tests `references rules` reads for citations: `["tools/*.py", "tools/workcenter", "tests/*.py", "tests/boards/*.py", "ee-agent-kit/lead/*.py"]`. |
| `numbers` | list of `{"pattern", "family"}` | none | The families of document numbers looked for in code, fab rule files and JSON rules' texts. A pattern that is not a regular expression is refused. |
| an entry's `kind` | `standard`, `application note`, `datasheet`, `report`, `user's guide`, `web page`, `paper` or `book` | none | The first 5 are held by `sha256`; a web page by its `values`; a paper or a book is cited and not held. |
| an entry's `names` | list of texts | `[]` | The texts code names the document by, e.g. `["SLVA477C"]`. |
| a web page entry's `values` | list of `{"says", "for"}` | none | Each value the rules take from the page: the page's own text and the rule that takes it. |
| a tool's or a test's `CITES` | `{"<index id>": "<where in it>"}` at module level | none | The documents the file cites. |

## `pictures.json` (a version's, for `workcenter pictures`)

| Key | Type | Default | Use |
|---|---|---|---|
| `boards[].path` | path | `.` | The board's project folder, relative to the version. |
| `boards[].name` | string | `base`, or the nested folder's name | The layer images' prefix in `docs/layers/` (`base-F-Cu.png`). |
| `boards[].prefix` | string | empty, or `<name>-` | Put before each still's name in `docs/` (`display-board-top.png`). |
| `boards[].strict` | bool | `true` | A part the 3D views draw without a body fails the board (`render --strict`). |
| `boards[].stills` | list | the five board views and `schematic.png` | The images of `build/render/` copied into `docs/`. |
| `boards[].layers` | file name | `layers-<name>.png` | The layer sheet's name in `docs/`; `null` copies no layers. |
| `boards[].spins[]` | list | from above; from below too with parts on both faces | Each turning GIF: `as` (its name in `docs/`), `tilt`, `zoom`, `pivot`, `frames` (36). |
| `scenes[].script` | path | each top-level script that imports `scene` | Run with the venv's Python from the version folder. |
| `scenes[].what` | string | the script's docstring | What the script draws; `workcenter docs` lists the script with it. |
| `scenes[].copy` | map | none | Files the script writes, relative to the version, and their names in `docs/`. |

## `tools/scene.py`

| Field | Type | Default | Use |
|---|---|---|---|
| `WORKCENTER_SPIN_FRAMES` | integer | the script's `frames` (36) | Frames in each turning GIF; `pictures --frames` sets it. |
| `WORKCENTER_PICTURES_CHECK` | `0`/`1` | unset | Set by `pictures --frames`: `stills` draws nothing, `spin` writes a sheet of its frames and prints `frames: <path>`. |
| `WORKCENTER_SRC` | path | set by `pictures` | The workcenter checkout, for a script that looks for its tools. |

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

## `tools/harvest.py`

What the projects taught the workcenter, read from the repository itself
(`PROCESSES.md` P35). The first 3 listings read git objects; `later` reads
the checkout's files. None writes anything. `--repo DIR` (default this
checkout) and `--json` stand before the listing's name.

| Command | Flags | Use |
|---|---|---|
| `branches` | `--main REF` (default `origin/main`), `--refs PREFIX` (default `refs/remotes/origin`) | Every branch under the prefix: its own commits, and the share of the lines they added to the workcenter itself that main holds. A line counts without the number of a mistake, a process or a step. |
| `scripts` | `--ref REF` (default `HEAD`), `--root DIR` (default `examples`) | The scripts the projects wrote for themselves, by file name: the projects that wrote each, and the functions 2 or more of them define. |
| `mistakes` | `--ref REF` (default `HEAD`) | The mistakes log by process: its entries, and the entries that name an earlier entry of the same process. |
| `later` | none | The candidates under "Later" in the checkout's `ee-agent-kit/ROADMAP.md`, as the file stands: each row's rating against its 6 scores, each score against its anchors, the order, and the evidence (an entry of the mistakes log, a file in backticks, a line that the file has). Exit 1 with 1 line for each row that does not hold. |

## `tools/kicadgen.py`

| Field | Type | Default | Use |
|---|---|---|---|
| `KICAD_SYMBOL_DIR` | path | `/usr/share/kicad/symbols` | Symbol libraries to read. |
| `KICAD_FOOTPRINT_DIR` | path | `/usr/share/kicad/footprints` | Footprint libraries to read. |
| `FREEROUTING_JAR` | path | `/opt/workcenters/ee/freerouting/freerouting.jar` | Used by `route()`. |
| `Design.files` | dict | `{}` | Text files `workcenter design` writes beside the project, by path under it: a block's deck, `ratings.json`, `parts.csv`. A path that is absolute, climbs out with `..`, names the project folder, or names a file `write()` makes itself is refused before anything is written. |
| `place_designators` | bool | `False` | `True`: the board is written with every designator placed round its part (tools/legend.py), the same on every run. |
| `designator(ref, x, y, angle)` | method | none | Fixes 1 designator by hand; the placer leaves it, the DRC gate judges it. |

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
| `--settings PATH` | `~/.claude/settings.json` | The Claude Code settings file to add the 2 PreToolUse hooks to: the one that refuses `cd` and the one that refuses a test edited by a script. Existing settings and hooks are kept; each hook is added once, and a second run changes nothing. Writes only that file. Run by hand: writing a user's settings is their decision. |

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
