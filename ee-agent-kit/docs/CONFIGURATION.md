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
| `REQUIRE_OPENEMS` | `0`/`1` | `0` | `1` makes a failed openEMS step fatal, a wrong checksum among them; else it warns and `workcenter fields` skips. |
| `OPENEMS_POOL` | URL | `https://deb.debian.org/debian/pool/main/o/openems` | Where Debian 12's 4 openEMS packages are fetched; each is checked against the SHA256 pinned in the script. |

## `tools/workcenter`

| Field | Type | Default | Use |
|---|---|---|---|
| `WORKCENTER_ROOT` | path | `/opt/workcenters/ee` | Locates the venv and the JAR. |
| `FREEROUTING_JAR` | path | `$WORKCENTER_ROOT/freerouting/freerouting.jar` | The autoroute engine. |
| `KICAD_CLI` | command | `kicad-cli` | The KiCad engine. |
| `NGSPICE` | command | `ngspice` | The simulation engine. |
| `JAVA` | command | `java` | Runs the JAR. |
| `KICAD10_3DMODEL_DIR` | path | `/usr/share/kicad/3dmodels` | Where `render` looks for the library 3D bodies footprints name, to list the parts drawn without one (`KICAD9_` and `KICAD8_3DMODEL_DIR` likewise). |
| `OPENEMS` | command | `$WORKCENTER_ROOT/openems/bin/openEMS`, else `openEMS` on `PATH` | The field solver `workcenter fields` runs; `doctor` reports it. |
| `KIKIT_PYTHON` | command | the venv's Python (`$WORKCENTER_ROOT/venv/bin/python`) | The Python that imports KiKit; EXPORT runs `tools/panel.py` with it for a project that holds `panel.json`. |
| `KISTACK_DIR` | path | `<checkout>/third_party/kistack` | The kistack copy whose `skills/layout-placement/scripts` `workcenter placement` runs. |

| Flag | Commands | Default | Use |
|---|---|---|---|
| `--json` | all | off | Machine-readable output. Read before the command or after it. |
| `--out DIR` | gates, erc, drc, sim, export, autoroute, render, procure, sources, verify, ratings, copper, fields, highspeed; design; ci | `<project>/build`; design: the design file's folder (with `--check`, a temporary folder); ci: `<repo>/build/ci` | Where reports and artifacts go; for design, where the KiCad project is written; for ci, each step's script, `$GITHUB_ENV` file and log. |
| `--strict` | gates, erc, drc, sim, export, render, procure, sources, verify, ratings, copper | off | Warnings fail the gate; for ratings, a stress that was not judged; for copper, a net with a stated current, or named in `ratings.json`, that `copper.json` does not name, a pin of a judged net with no stated current, a pin of the entry's part that `from` does not name, a part's heat with no pad on the board, or a limit it does not state; for verify, a requirement whose verdict is FAIL or OPEN, and decks that ran without corners; for render, a part the 3D views draw without a body fails it; for procure, a line short of stock or a price older than 90 days; for sim, a model outside a `warn` bound (its datasheet), a project with no `sim/corners.json` or with decks that drive periodic sources and no `sim/frequency-plan.json`, a deck with no bound, a deck whose measures do not move with temperature, a part named like a board reference that no tolerance covers, and an operating point ngspice doubts (`singular matrix`); for sources, a datasheet kept as a note only, a file with no SHA256 or revision recorded, a model older than its datasheet, or a load check skipped. |
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
| `--check` | design | off | Regenerate into a temporary folder (or `--out`) and compare the `.kicad_pro` and `.kicad_sch` with the design's own, as a board repository's CI does, and the project's `fp-lib-table` and `sym-lib-table` with what the design writes in its own folder. Exit 1 on a difference or on the design step's own exit 1 (M85). Writes nothing in the project. Refuses `--route`. |
| `REPO` | ci | `.` | The repository whose `.github/workflows/*.yml` the replay runs, from its root, as the runner's checkout. |
| `--job ID` | ci | every job, each after the jobs it `needs` | Replay only this job (repeatable). |
| `--workflow FILE` | ci | every workflow | One workflow: a file name in `.github/workflows/` or a path. |
| `--skip REGEX` | ci | `(?i)\b(install\|upload)` | Skip the steps whose name matches; `uses:` steps are always skipped. A step whose `${{ }}` the replay cannot read (only `env.*`, `github.workspace`, `runner.temp` and `runner.os` are read) is red until its name is skipped. |
| `FIRMWARE` | mutate | none | The firmware folder the test command runs in; each mutation gets its own copy, without `build/`. |
| `--mutations FILE` | mutate | none (required) | The project's list. JSON: `[{"name", "file", "old", "new"}]` or `{"test": CMD, "mutations": [...]}`. Python: a top-level `MUTATIONS = [(name, file, old, new), ...]` and an optional `TEST = "..."`, read as literals and never run. Every `old` must be in its file exactly once; the command checks each before running any. |
| `--test CMD` | mutate | the list's `test`, else `make -k test` | The test command, run under `bash -c` in each copy. It must pass unmutated. A mutation that fails it is caught; one that a compiler's `file:line: error:` stops did not build, and fails the run as a survivor does. |
| `--only TEXT` | mutate | every mutation | Run only the mutations whose name holds this text (repeatable). |
| `--jobs N` | mutate, sim | mutate: `1`; sim: one per processor, 8 at most | Mutations run at once; for sim, corner runs of one deck at once. A whole number, 0 or more: anything else is a usage error, exit 2. |
| `--work DIR` | mutate | a temporary folder, removed after | Keep the copies here, one folder per mutation. |
| `--fetch` | sources | off | Read each row's URL once more under the workcenter's own user agent into `<out>/sources/fetched/` and report each as same, changed, new, refused, gone or unreachable; a refusal is never retried. The library is not written. |
| `--package DIR` | verify | `<project>/verification` | The verification package (`PROCESSES.md` P28): requirements, system, simulations, calculations, traceability. |
| `--init` | verify | off | Copy `templates/verification/` into the package and a writeup per `sim/*.cir` into `simulations/<deck>/`, never over a file that exists. `BRIEF.md` and `FACTS.md`, the helpers' brief and facts file, stay out. The new files fail the check until each `<!-- fill ... -->` is written. |
| `--boards LIST` | procure, costs | `1,10` | Units to price, comma-separated; each gets its cheapest order and totals per supplier; for costs, a column each in the totals table, the largest also judging stock. |
| `--step` | gates, export | off | Also export a STEP model. |
| `--fab NAME` | gates, drc | none | Also check a fab's limits: a rule set in `rules/` (`sierra-circuits-web`, `jlcpcb-2layer`, `pcbway-standard`, `oshpark-2layer`) or a `.kicad_dru` path, laid over the project's own rules on a copy in `<out>/fab-<name>/`. A design file's `fab` field does the same for good (`rules/README.md`). |
| `--dsn FILE` | autoroute | `<project>/<name>.dsn`, then `build/route/<name>.dsn` | Specctra DSN exported from KiCad. Absent means the command skips. |
| `--passes N` | autoroute, design, bench | `20` autoroute and bench, `60` design | FreeRouting optimisation passes. bench takes a whole number above 0. |
| `--threads N` | autoroute, design, bench | engine default; bench `2` | FreeRouting thread count (`-mt`). bench takes a whole number above 0 and also holds the JVM to N processors. |
| `--order` | design (with `--route`), bench | off | design: route in 4 stages, 1 FreeRouting run each, each on the copper of the stages before it: poured nets and every net with copper drawn by hand, the nets of each part of 0.5 mm pitch or less, pairs (names that end in `_P`/`_N`, `D+`/`D-` or `DP`/`DN`), the rest. Writes `build/route/<name>.<n>-<stage>.dsn`, `.ses`, `.log`. Refuses `--seed`. bench: also run each router as `<router>+order`. |
| `--router NAME=JAR` | bench | the workcenter's FreeRouting | A FreeRouting jar to run, repeatable; the first is the default router. |
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

## `ratings.json` (beside a schematic, for `workcenter ratings`)

| Field | Type | Default | Use |
|---|---|---|---|
| `pack` | name or path | none (required) | The rule pack: a file of `rules/ratings/` without `.json` (`nasa-eee-inst-002`, `ecss-q-st-30-11c-rev2`), or the path of a pack from the project's folder. |
| `nets` | object | none (required) | Each net a source off the board holds: `{"volts": [least, greatest], "source": "..."}` under the net's name, with or without its sheet's slash; 1 net named both ways is refused. `[0, 0]` is the reference. |
| `ambient` | object | none | `{"max": C, "source": "..."}`: the highest air temperature. A limit that falls with temperature is judged there. |
| `parts` | object | none | What the board cannot say of a part: `REF.PIN` with `amps` for the load behind a connector's pin, `REF` with `amps` for the current through a part (RMS for a resistor, a transistor, a fuse, a ferrite and a switch, the average for a diode, the peak for an inductor), `REF` with `volts` for the greatest voltage across a capacitor or a resistor whose 2 nets move together; each with a `source`. A number the command would hold to nothing is refused once the part has facts: the `ratings` skill lists them. `REF` or `REF.PIN` with `watts`: the heat a part gives off, W, split over its pads by copper area, or on 1 pad (`U1.2`), the heat that leaves by that pad; not both for 1 part. `workcenter copper` reads it; `ratings` does not judge it. A 2-pin resistor with `amps` (on the part or on a pin) and a numeric Value gives I^2 R itself. |
| `accepted` | list | none | Failures the owner takes on: `{"part", "rule", "why", "by"}`, `by` as `the owner's decision of YYYY-MM-DD`. An entry accepts 1 failure: where 2 of 1 part stand under 1 rule, `line` holds words of the line the entry means. An entry nothing fails under fails the run. |

A part's facts are 1 entry of a file in `library/facts/`, in the project's
folder or a folder above it; a rule pack is 1 file of `rules/ratings/`. The
`ratings` skill has every key of both.

The SIM gate reads 2 keys of a part's facts, from an entry that names the
part by `mpn` or `mpns` and whose `source.sha256` is a row of
`library/sources.csv`:

| Key | Facts of | Type | Use |
|---|---|---|---|
| `kept` | a capacitor | pairs `[volts, share of the value kept]` | The maker's DC bias curve; the volts rise from pair to pair; each share above 0 and at most 1.5. `workcenter ratings` reads it too. |
| `kept_celsius` | a capacitor | pairs `[celsius, share against 25 C]` | The maker's temperature curve; each share above 0 and at most 1.5. |
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

## The workflow Board (`.github/workflows/board.yml`, `tools/board.py`)

| Field | Type | Default | Use |
|---|---|---|---|
| `BOARD_TOKEN` | repository secret | none | A classic personal access token with the `project` and `repo` scopes; the board is changed with it. Without it the job prints 1 line and ends green. |
| `BOARD_URL` | repository variable | `https://github.com/users/ThyFriendlyFox/projects/2` | The project board the work cards stand on (`https://github.com/users/<login>/projects/<n>` or `https://github.com/orgs/<login>/projects/<n>`). |
| `--event` | flag of `tools/board.py` | required | The issues event's JSON file (`GITHUB_EVENT_PATH`). |
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
| `pack` | name or path | none (required) | The board rule pack the DRC holds the board to: a file of `rules/board/` without `.json` (`ecss-q-st-70-12c-rev1`), or the path of a pack from the project's folder. The volts and amps come from the project's `ratings.json`, which must stand beside the board. No file: no pack. |

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
