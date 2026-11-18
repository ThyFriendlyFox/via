# WORKCENTER.md — EE Workcenter

<!-- This file at the root marks the repository as a workcenter to
     skills/attached-repos. install.sh copies it to
     /opt/workcenters/ee/WORKCENTER.md so an environment without the
     repository attached still finds it. -->

The EE Workcenter turns a KiCad 10 project into fabrication outputs that
passed every gate. "Done" means `workcenter gates <project>` prints GREEN.
`workcenter next <project>` names the one step that is left at any point.

It also turns a chip project (RTL, benches, timing constraints and
`chip.json`) into a GDSII mask layout on an open process. "Done" there
means `workcenter chip gates <project> --strict` prints GREEN; see "Chip
gates". `workcenter next <project>` names the one step for a chip too.

## Verdicts

The last line of `workcenter gates` is the verdict, also with `--report`.
Its exit code says the same. Every failure and every warning is printed
above it, each on its own line.

| Last line | Meaning | Exit code |
|---|---|---|
| `GREEN` | Every gate that had something to run passed, with no warning. | 0 |
| `GREEN with N warnings` | Every gate passed, and N things were named and not failed on. Each is printed. The project's gates report names each one it keeps, and why. `--strict` fails on all of them. | 0 |
| `GREEN ... (nothing to run for: erc, drc, export)` | As above, for a project that gives some gates nothing to run: decks and no board. The line names those gates. | 0 |
| `RED` | A gate failed, or an engine stopped with an error. | 1 |
| `SKIPPED (GATE: engine missing)` | A gate did not run because its engine is absent. A run with an absent engine is never GREEN. | 2 |
| `SKIPPED` | No gate had anything to run. | 2 |

`workcenter doctor` reports each engine as ok, absent or MISSING. A gate
whose engine is absent is skipped with the engine's name. Its first line
reads `ok`, or `degraded` or `fail` with the names of what is absent:
`workcenter ee: degraded, without freerouting`. `fail` is a required
engine. The 2 hook lines are for a Claude Code session (P8 step 1); an
absent hook does not make the line `degraded`.

`workcenter verify` ends with a line of its own. `REQUIREMENTS MET` needs
every requirement PASS, no problem in the package, and the decks run at
their corners. `REQUIREMENTS NOT MET (...)` names what is short. A
requirement whose deck ran no corner is "judged as written only": the
line counts it, the requirements are not met, and `--strict` fails on it.
A requirement's check is judged at the corners whatever its deck's own
bound says about them. The gate's own status, `PASS verify`, says only
that the package agrees with a fresh run: a package that records a FAIL
honestly passes it.

## Tools

| Tool | Version | Command | Installed by |
|---|---|---|---|
| KiCad | 10.0 | `kicad-cli` | `install.sh` (PPA kicad/kicad-10.0-releases) |
| ngspice | 42 | `ngspice` | `install.sh` (Ubuntu 24.04 archive) |
| FreeRouting | 1.9.0 | `workcenter design <design.py> --route [--seed <previous .kicad_pcb>\|--order] [--threads N]` (generated boards, headless); `workcenter bench <design.py>... --out <dir>` (the routing benchmark); `workcenter autoroute <project> [--dsn file]` (hand-drawn boards, DSN from KiCad) | `install.sh` (GitHub release, SHA-256 pinned; 2.1.0 hangs after routing when its GitHub version check cannot succeed) |
| FreeRouting 2 | 2.5.0 | `workcenter design <design.py> --route --router freerouting2`; `workcenter bench <design.py>... --out <dir> --router freerouting2` | `install.sh --freerouting2` (GitHub release, SHA-256 pinned, with a Temurin 25.0.5+8 JRE, SHA-256 pinned); opt-in. The default router stays FreeRouting 1.9.0. |
| openEMS | 0.0.35 (Debian 12's `0.0.35+git20190103.6a75e98+dfsg.1-3.2`) | `workcenter fields <project>`, as its own program on an XML file the command writes; `OPENEMS` overrides the path | `install.sh` and `install.sh --openems` (Debian 12's 4 packages from `deb.debian.org`, each SHA-256 pinned; Ubuntu 24.04 has no package) |
| KiKit | 1.8.1 | `tools/panel.py` under `KIKIT_PYTHON` (EXPORT's panel, for a project with `panel.json`); its `doPanelization`, not the `kikit` command, which imports wxPython | `install.sh` (PyPI, `requirements.txt`) |
| kicad-python (kipy) | 0.8 | `/opt/workcenters/ee/venv/bin/python` | `install.sh` (PyPI) |
| librsvg | 2.58 | `rsvg-convert` (SVG to PNG for `workcenter render`) | `install.sh` (Ubuntu 24.04 archive) |
| FFmpeg | 6.1 | `ffmpeg` (the turning GIF of `workcenter render --views spin`) | `install.sh` (Ubuntu 24.04 archive) |
| kicadgen | this repo | `workcenter design <design.py> [--route [--seed <board>]\|--check]`; `python3 tools/kicadgen.py pins\|footprint\|symbol-add` | `install.sh` (part of the checkout) |
| pdfminer.six, PyYAML | 20260107, 6.0.3 | `workcenter curve` (a PDF page's vector paths), `workcenter ci` (a GitHub workflow), each run under the venv | `install.sh` (PyPI) |
| workcenter CLI | this repo | `workcenter` | `install.sh` (symlink to `tools/workcenter`) |
| Engine lock | this repo | `tools/enginelock.py`: a long command (`design --route`, `gates`, `sim`, `measure`, `export`, `render`, `copper`, `highspeed`, `fields`, `mutate` and the others of docs/CONFIGURATION.md's table) waits its turn on the machine's engine lock and prints where it stands every 30 s; the others never wait. `make verify` holds it for the whole gate, and `make verify-site` for the whole fast gate. `WORKCENTER_LOCK=off` turns it off; `workcenter doctor` shows it; `python3 tools/enginelock.py hold -- <command>` puts any other command under it | the checkout |
| scene | this repo | `tools/scene.py`: assembly scenes a project's script builds, run by `workcenter pictures` | the checkout; KiCad's `pcbnew` and FFmpeg by `install.sh` |
| kistack | `641ade9` | `.claude/skills/kistack/SKILL.md` routes to `third_party/kistack/skills/`; `workcenter placement <check> <board> [args]` runs its placement checks | the checkout (vendored, `third_party/kistack/VENDORED.md`); shapely, numpy and pygerber by `install.sh` (PyPI) |
| Board inspection | this repo | `workcenter inspect <view> <board> ...`, the views `map`, `list`, `probe`, `net`, `islands`, `resistance`, `crossed` (KiCad's `pcbnew` and Pillow under the venv); `python3 tools/stretch.py <design.py> --cut X --grow G` | `install.sh` (part of the checkout; Pillow from PyPI) |
| Corners, frequency plan and junctions | this repo | `sim/corners.json`, `sim/frequency-plan.json` and `sim/thermal.json`, read by `workcenter sim` (`tools/simcorners.py`, `tools/freqplan.py`, `tools/thermal.py`); `workcenter sim --bundle <dir>` for a deck that runs on any machine | the checkout; ngspice by `install.sh` |
| Next step | this repo | `workcenter next <project>` (`tools/guide.py`; `tools/chipguide.py` for a chip project) | the checkout |
| Chip projects | this repo | `workcenter chip init <dir> --top NAME`, `workcenter chip gates <project>` (`tools/chipflow.py`, `tools/chipfront.py`, `tools/chipback.py`, a process table in `pdks/`); all 10 gates run and tests hold each; the acceptance processor (760 cells, a 40 ns clock, the sky130A process) is GREEN with `--strict` | the checkout; the engines in `<root>/chip` (`sudo ./install.sh --chip`) |

## Skills

A skill is a Markdown procedure at `.claude/skills/<name>/SKILL.md`. A
host that loads skills offers each by name. Any other reader opens the
file: it needs nothing else.

| Skill | Use when |
|---|---|
| `attached-repos` | The session holds more than 1 repository. Run first. |
| `board-design` | A board is designed from a spec, as a Python design file built from the KiCad libraries. |
| `board-gates` | A board must pass ERC, DRC, simulation, and export. The fix loop. |
| `board-loop` | A board that passes its gates is to become compact, correct and good to look at: 1 prompt run again and again, with a reviewer who has not seen the earlier rounds. The project's `LOOP.md` holds the prompt, the checklist and the log. |
| `chip-design` | A chip is designed from a spec: `chip.json`, the RTL, the benches, the constraints, the list of changes the benches must catch. |
| `chip-gates` | A chip must pass the 10 chip gates to its GDSII layout. The fix loop, gate by gate. |
| `autoroute` | A board has unrouted nets and FreeRouting should route them. Headless for generated designs. |
| `simulate` | A circuit must meet a measurable spec before layout; a part switches; a deck must run on another machine. Corners, the frequency plan, bundles. |
| `blog-post` | A human asks for a public write-up of recent work. |
| `procurement` | A human asks what a board costs, for its parts list, or to order its parts. |
| `ratings` | A schematic is to be held to its parts' ratings before layout: each part's facts from its datasheet, with the page of each pin's and each needed part's numbers, the voltages and currents the board cannot say, and `workcenter ratings` until every stress holds. |
| `board-rules` | A routed board is to be held to a standard: each gap to the voltage between its nets and each track's width to its net's current, from `ratings.json`, with `board-rules.json` naming the pack; or to a fab's published limits. |
| `standards` | A board is near release and someone asks what its product must meet: `product.json` names the kind, and `workcenter standards` lists each requirement of the kind's free documents as held by a gate, held by a named test, or not held. |
| `references` | A rule cites a standard or a datasheet: get the copy it was written from with `workcenter references fetch`, judge a file a person downloaded with `workcenter references check`, and keep `workcenter references rules` passing. |
| `now` | Several agents work at once and a maintainer follows them on the project board: 1 work card per piece of work with `workcenter now`, its `**Status:**` line Todo, In progress or Done, in 1 GitHub issue's body rewritten at each landing, block and health gate, or on the `status` branch with `--write`. |
| `lead` | Roadmap work is to be done by helpers: a worktree and a brief per piece, a build, an attack and a fix, a second attack for a piece called not sound, and `ee-agent-kit/lead/landed.py` to see which pieces have finished. |
| `land` | Finished pieces are to go onto the work branch, and later onto the default branch: commits in a straight line, docs files applied, the health gate alone with the push behind VERIFY GREEN (`ee-agent-kit/lead/gate-and-push.sh`), a merge commit only at the owner's word. |
| `user-round` | The roadmap is to be checked against the goal: 3 users of different sizes, 1 board spec, their logs checked and ranked into roadmap candidates, each with what the small user does after the change. |
| `highspeed` | A board carries a fast interface (USB 2.0, USB 3.x): `interfaces.json` names each pair, and `workcenter highspeed` until every width, gap, length, skew, via count and ground plane holds; then `workcenter drc --fab build/highspeed/highspeed.kicad_dru`. |
| `copper` | A routed board carries a stated current or a part's stated heat: each power net's drop and current density, in its copper and in each barrel, and the board's temperature, against the limits of `copper.json`, with a picture of each and `workcenter copper` until every limit holds. |
| `fields` | A fast interface or an antenna on a routed board: a track's impedance, loss or crosstalk, held by `workcenter fields` to the limits `fields.json` states, each with its source. |
| `fabrication` | The files a fab and an assembler take, each read back against the board, a panel from `panel.json`, and `workcenter measure`: the plan of measurements for the built board, from the project's own sim bounds. |
| `kistack` | Placing parts, reviewing a schematic, a layout or the Gerbers, choosing a part's derating, a footprint or symbol, or a panel: it names the kistack skill for the step, and where this workcenter's rules win. |
| `verification` | A human asks for requirements, a review, an inspection, or proof that a design meets its parts' ratings: the verification package of P28, checked by `workcenter verify`. |

## Gates

| Gate | Command | Pass condition | Runs before |
|---|---|---|---|
| ERC | `workcenter erc <project>` | 0 errors in the ERC report | layout |
| DRC | `workcenter drc <project>` | 0 errors, 0 unconnected items, 0 parity errors; with the project's fab rules (`<name>.kicad_dru`) when its design names a fab | export |
| SIM | `workcenter sim <project>` | every `sim/*.cir` runs clean with no analysis aborted, every `*.expect.json` bound holds as written and at every corner of `sim/corners.json`, every overlap `sim/frequency-plan.json` shows is answered, every part `sim/thermal.json` names keeps its junction under its pack's derated limit at every run, and every library model a deck includes is unchanged since its `sources.csv` row | export |
| EXPORT | `workcenter export <project>` | gerbers, drill, BOM, schematic PDF, placement file (each part at its place and rotation), an assembly page per side that holds a part (DNP parts hidden; each designator of that side drawn, read from the page's text), IPC-2581 produced, and each of the last 3 read back against the board; with `panel.json`, a KiKit panel of rows x cols boards in a closed outline at least their size, and its Gerbers | hand-off to fabrication |
| ALL | `workcenter gates <project>` | the 4 gates above in order, none red, none skipped for a missing engine | a board is called done |

`workcenter design` also lists every control input that can float while the
MCU is in reset (a gate, a logic input, a switch or an I2C line that no output
drives and no resistor holds), as `pull:` lines; a design that sets
`check_pulls` fails on one, and `defined_nets` names the nets held elsewhere
with the reason (`PROCESSES.md` P16).

A design may say how each part simulates: `d.sim` binds a part to a `.subckt`
or a `.model` in a file with a map from every pin to a node, or gives it a
value of its own; `d.no_sim` leaves a part out with the reason;
`d.sim_directives` puts SPICE lines on the sheet. `workcenter design` then
writes KiCad's Sim fields on the symbols, and hidden on their footprints so
the DRC's parity check finds the same fields on both (M141), so the
schematic runs in KiCad's simulator and `kicad-cli sch export netlist --format spice` writes a netlist
ngspice reads. It prints each problem as a `sim:` line and exits 1 on any: a
map that leaves a pin or a node out (KiCad would bind it by position and say
nothing), a file or a name that is not there, a node the model does not have.
With `check_sim` every part needs a `sim` or a `no_sim`, a plain R, C or L
excepted. The project raises KiCad's `simulation_model_issue` to an error, so
the ERC gate reports a model KiCad cannot load. A design that says nothing
about simulation regenerates byte for byte as before (the `board-design`
skill).

Its verdict is its exit code. It writes every file even when it exits 1.
The causes of exit 1: a hand via its check refuses; a part in a keep-out or
with every pad outside the outline; a floating input with `check_pulls`; a
`sim:` problem; an unrouted connection the router counts; a route that left
every connection without copper. On exit 1 its last line says `red`, names
each failure, and says the files are for inspection only: a CI regenerate
check fails on that exit code (M85). The generator refuses some design
files when it loads them: a namespace that is no UUID, `power_nets` that is
no dict. That refusal is 1 `file:` line with the file's line number and
what to write. Its exit code is 1, and nothing is written. A first design
file starts from a copy of `templates/project/design.py`, a divider that
generates, routes and passes ERC and DRC as it stands. Each via it drops through a pour's island
after routing is printed as a `stitch:` line with the net, the island's layer,
the pads the island holds and the layer the via reaches, so a via that moved
between two runs can be traced to its pads.

`workcenter design --route --seed <board>` starts the router from a previous
routed board, usually the version the design was copied from: its router
tracks and vias go to FreeRouting held (pushed aside if need be, never
ripped up), so the paths that still fit stay and only the rest are routed;
seed copper that hangs from nothing goes in unfixed, for the router to reuse
or remove. The design's own hand copper, stitching
vias, nets the design lost, and copper that now meets another net's pad or
copper, a keepout or the board edge are left out first and counted on a
`seed:` line, with how many seed tracks the new route kept. The seed board is
only read.

`workcenter design --route --order` routes in 4 stages, 1 FreeRouting run
each, each on the copper of the stages before it: the poured nets and every
net with hand copper, the nets of each part of 0.5 mm pitch or less, pairs
(names that end in `_P`/`_N`, `D+`/`D-` or `DP`/`DN`), then the rest. It is
not the default: on ring-mouse v0.4's power board it joined 32 of 34
connections where the plain route joined all 34.

Not a gate: `workcenter bench <design.py>... --out <dir>` routes each
design with each router it is given (`--router NAME=JAR`, the first the
default) and runs `workcenter drc` on each result. It records the time, the
share of connections joined, the DRC's errors, the 2 commands and the bytes
of their output in `<dir>/<board>/<router>/run.json`, and writes
`<dir>/bench.md`. Each run empties its own folder first. A route past
`--time-limit` (default 300 s) is stopped and not judged, exit 2. A router,
or `--order`, becomes a board's default only when the table shows it joins
as many connections with no more DRC errors in no more time.

A board made for a particular fab checks that fab's published limits in the
DRC: `rules/` holds them as KiCad design rules (`sierra-circuits-web` for
Sierra Circuits' Web PCB: 4 mil trace and gap, 6 mil hole and ring, 13 mil
inner drill to copper, 5 mil legend; `jlcpcb-2layer`, `pcbway-standard`
and `oshpark-2layer` for those fabs' services). A design file's `fab = "<name>"`
writes the set into the project for good, and the router and the generator's
own via checks keep each layer's hole-to-copper rule (the 13 mil on the inner
layers, M79); `workcenter drc|gates --fab
<name> <project>` checks any project against one once, on a copy
(`rules/README.md` says what each set cannot check). A fab's limits only
add floors: its board-wide limits raise the board's own minimums, and only
its layer and condition rules go into the project's `.kicad_dru`, raised to
the board's own where those are stricter. A board-wide custom rule would
override every net class's clearance in KiCad's DRC.

A project that holds `board-rules.json` (`{"pack": "<name>"}`) beside its
board is held to that board rule pack too, after KiCad's own rules:
`rules/board/<name>.json` (`ecss-q-st-70-12c-rev1`), or a pack of the
project's own by its path from the project's folder. The voltage of each
net and the current on it come from `ratings.json`; without that file the
DRC is red with 1 line. Each gap is held to the voltage between its 2 nets
and each track's width to its net's current. Each net's vias are held to
its current against the wall `board-rules.json` states: `via_wall` from the
fab, or `hdi` for a board built as HDI (25 um); with neither, the vias are
not judged.
KiCad measures the pack's gaps on a copy in `build/board-rules/`, with 1
witness rule per net that shows KiCad read the rule file; the project's
files do not change. The DRC line ends `board rules <pack>: N fail, M not
judged`, and each failure names its document, clause, table and page. A
net whose name a KiCad rule cannot hold is not judged. With `--strict`, a
line not judged fails the gate. The `board-rules` skill is the procedure.

`board-rules.json` also takes `layout`, a list of layout packs, with or
without `pack` (`rules/board/README.md`, "Layout packs"):
`ti-slva680a-esd` (TI SLVA680A: a TVS at each line of a connector that
leaves the device) and `ti-szza009-emi` (TI SZZA009: power and ground
traces at most 3:1 on a 2-layer board). The project states what the board
file cannot: `connectors`, `inside`, `protectors`, `ground`, `power`.

Not a gate, but part of every hand-off: `workcenter render <project>` writes
the schematic, board top and bottom, and 3D images into `build/render/`, and
every layer that has something on it into `build/render/layers/` (one PNG per
layer with the outline, bottom layers seen from below) with an overview sheet,
`build/render/layers.png`. `--views spin` adds `build/render/board-spin.gif`,
the 3D board turning once round (`--spin-frames`, `--spin-tilt`, `--spin-zoom`,
`--spin-pivot`;
a minute or two of frames). `--views` takes any of schematic, 2d, 3d, layers,
spin, or all. The 3D views and the GIF are drawn in the board stackup's
colours (its masks, silkscreens and finish). Its summary names every part the 3D views draw without a body
(a footprint naming a model that is not on disk); `--strict` fails on one.
A finished board version shows its layer sheets and a turning
GIF of every board and its assembly in its README (`PROCESSES.md` P23), and
a wired schematic someone has read (`sch_wires`, P24).

Not a gate either: `workcenter procure <project> --parts parts.csv` prices the
schematic's BOM from a parts file (supplier, supplier number, price breaks,
stock, date and URL per part, items off the board too) and writes
`build/procure/bom.csv`, `parts.csv` and `parts.md`: the orderable list with
the cheapest order per line and totals per supplier for each `--boards`
count. It fails on a line with no part or no price; `--strict` also on a
line short of stock or a price older than 90 days (`PROCESSES.md` P25).

Not a gate: `workcenter placement <check> <board> [args]` runs one of
kistack's layout-placement checks on the board file (`pin_sides`,
`placement_audit`, `route_check`, `local_search`, `group_search`) with KiCad's
Python module reading the board, where kistack itself needs a KiCad server.
Run `placement_audit` and `route_check` on each IC whose parts moved, before
routing (the `kistack` skill). `move` is refused: a generated board changes in
its design file.

Not a gate: `workcenter inspect <view> <board>` reads a routed board with
KiCad's own geometry, for a change made on it (`PROCESSES.md` P29). `map
--box X0 X1 Y0 Y1` draws one PNG per copper layer of the window into
`build/inspect/` (or `--out`): courtyards, pads with their names and nets,
tracks with their nets, vias, keep-outs, pours, a 1 mm grid, back and inner
layers as seen from the top. `list --box` prints what lies in the window,
or `--json`. `probe` places a via (`--via X,Y --net N`), a track (`--track
"X,Y X,Y" --layer L --net N`) or a part (`--part REF --at X,Y`) and lists
every conflict the DRC would report: copper clearance by net class, hole to
copper with the project's `.kicad_dru` (Sierra's 13 mil on inner layers),
hole to hole, the board edge, courtyard overlaps, and each keep-out by name;
exit 1 on a conflict. `net N` prints the net's connected groups and the
pads each holds; `islands [--net GND]` the pour's pieces per layer, what
each holds, and each island no via reaches; both exit 1 on a group cut off.
`resistance N --from R.P --to R.P` gives the copper path's resistance: each
track from its layer's thickness in the board's stackup, each via barrel
from its drill and plating, copper at 20 °C (`--temp`). `crossed <old
board> --box ... --new <board>` names the nets whose copper crossed the
window and which of them the new board no longer connects (exit 1).

`python3 tools/stretch.py design.py --cut X --grow G` grows a design at a
cut: every board x-coordinate east of X in the file's code moves G mm east.
It lists what it moved and every number it left that a person should check.

`d.keepout(polygon, layers, name, parts=True)` keeps footprints out of an
area: the board's mechanical neighbours (a strip standing on it, a spacer,
a body above it) go in the design. KiCad gets a rule area with footprints
disallowed, and `workcenter design` lists each part whose courtyard enters
one as a `part:` line and exits 1. `copper=False` lets tracks and vias
through the area.

Not a gate: `workcenter sources <project> --parts parts.csv` checks every
part on the schematic against the nearest `library/sources.csv` at or above
the project: a datasheet row for each part, a spice row (a model file, or a
note why there is none) for each U, Q and D, each kept file present and
unchanged since its SHA256 was recorded, printing the revision its row
records, each model defining its `.SUBCKT` and loading in ngspice with its
sub-models, and a model older than its datasheet named. `--fetch` reads each
row's URL once more, under the workcenter's own name, and says which files
differ from the library's (a refusal is recorded, never retried). It writes
`build/sources/sources.md` and `sources.json` and never writes the library
(`PROCESSES.md` P27).

The SIM gate runs a deck that includes a listed vendor model from
`build/sim/run/<deck>/`: the includes made absolute, the model translated
into a copy where its row's `Ngspice` column lists fixes (`res-model` folds a
PSpice RES model into its resistors, `tolerance` drops LOT and DEV), and a
`.spiceinit` setting the row's mode (`ps`, `lt`). The library's file stays as
the vendor published it. An expect bound with `"warn"` holds a model to its
own datasheet rather than the design to its spec: outside it, the deck is
named in the warnings, and only `--strict` fails.

A deck is run by hand only through `workcenter sim <project> --deck NAME`:
one deck, the gate's way, with every value it printed beside its bound.
`--keep` runs it from `build/sim/run/<deck>/` (a deck the gate runs in
place is copied there too, with the deck folder's own `.spiceinit`), leaves
the folder, and prints the one command that reruns it:
`env -C <run folder> ngspice -b <deck>.cir`. A bare `ngspice -b` in `sim/`
reads a vendor model untranslated and in ngspice's own mode (M94).

The SIM gate runs every deck at its corners (`tools/simcorners.py`, the
`simulate` skill's "Corners"). `sim/corners.json` names the temperature
range, each part's tolerance and a count of Monte Carlo runs, each range
with its source. The gate runs a deck once for each temperature. It runs
each part alone at both ends of its tolerance and half-way to each, and
follows a measure that peaks between the ends toward its peak. It runs
every combination of the ends when that is 64 runs or fewer; above that
it runs 1 worst case for each bound and warns that 2 parts off together
can hide a miss. It runs once for each Monte Carlo draw. Each run has its
own folder under `build/sim/corners/<deck>/`. A tolerance moves R, C and L
elements, the DC value of a V or I source, and a `.param`; 2 parts written
from 1 parameter move apart. A bound holds when it holds at
every corner; a failure names the worst corner and how many more miss:
`divider:vout=2.625 at R1 -5 %, R2 +5 % (and 9 more corners) not in [2.45,
2.55]`, from `tests/boards/fail-sim-corner`. A bound with `"warn"` or `"at": "nominal"` is judged as
written only; the second needs a `source` that says why. A project with
decks and no `sim/corners.json` gets a warning, as does a deck whose
measures do not move with temperature and a part named like a board
reference that no tolerance covers. `--nominal` leaves the corners out and
says so.

The SIM gate judges the project's frequency plan (`tools/freqplan.py`, the
`simulate` skill's "The frequency plan"). `sim/frequency-plan.json` names
every periodic source with its frequency and every resonance an `.ac`
deck measured. The gate fails on a source whose harmonic lies in a
resonance's band, and on 2 sources that can run at 1 frequency, unless the
plan answers the overlap with a bounded measure of a deck that drives it.
It fails on a periodic stimulus in a deck that the plan does not name. A
project whose decks drive periodic sources and that has no plan gets a
warning. A deck that answers an overlap is also run with L stepped
against C between their ends: a resonance meets its source there, where no
end shows it. A resonance read from a deck that runs no corner fails the
plan, as does a measure of the plan that some corner does not print. A
source whose frequency the deck gives as no number is named in a warning.

The SIM gate runs each deck capacitor and inductor named like a board
reference on its maker's data (`tools/partdata.py`, the `simulate`
skill). It does so when the project's `library/facts/` holds a curve for
the part's number (`kept`, `kept_celsius`) in an entry that names that
number (`mpn` or `mpns`), and `library/sources.csv` has the row of the
maker's file with the SHA256 the facts name. A capacitor takes its value
at its working voltage and at the run's temperature, the 2 curves
multiplied; an inductor takes its value at its current. The gate needs
the schematic and `parts.csv` to know each part's number. A part whose
data the gate cannot apply fails the deck with the reason: no row, an
entry that names the part by a pattern or a symbol, a place inside a
`.subckt` or in a file the deck includes, an `ic=`, a K element that
couples it, or a value that is no number. A bound that fails on the data
names the parts that miss it alone, and the value with every part ideal:
`tests/boards/fail-sim-bias` gives 6.755 mV of ripple on its 5 mV bound,
3.04 mV with ideal parts, and names C2. A row that keeps no file leaves
the SHA256 not judged, with a warning. A deck that holds a C or L under a
name that is no board reference, while board parts hold data, gets a
warning. A bundle carries the rewritten deck.

The SIM gate holds the junction of each part `sim/thermal.json` names
(`tools/thermal.py`, the `simulate` skill). At every run it judges, the
deck as written and each corner, TJ = TA + RthetaJA x P, with the run's
temperature as TA and the power the named deck measure prints (TI SPRA953D,
section 1.1, equation 1). RthetaJA and the greatest junction temperature
come from the part's facts (`thermal`), and the derated limit from the
pack's `junction.temperature` rules. A part past its limit fails on 1 line
with the part, the ambient, the junction, the limit and the worst run.
Every printed junction says that RthetaJA is the datasheet's test board's:
SPRA953D calls the sum a misapplication on a system board, and a 2s2p
board a best case. A part with no RthetaJA, only a case, board or top
figure, or no facts is not judged: a warning, a failure with `--strict`.
So is a part whose deck's corners were not all run (a `skip`,
`temperature: false`, `--nominal`), and a run whose temperature is not
known; such a part is never held.

The gate reads what it is given strictly. An expect file with a key it does
not know, a bound with neither `min` nor `max`, a bound that is no finite
number, or text that is not JSON fails the gate with the line that is
wrong. An analysis ngspice gave up on fails its deck even when a later
analysis completes. A complex value is no measure. A name printed 2 times
with 2 values is judged on each. A value ngspice reads as another number
than it looks (`4k7` is 4 k) fails its deck, and so does an `altermod`
line with more than 1 parameter: ngspice 42 applies the first and drops
the rest. The user's own `~/.spiceinit`
does not reach a deck or a corner. A node that floats (`singular matrix`)
is a warning.

`workcenter sim <project> --bundle <dir>` writes each deck as a folder
that plain ngspice runs on any machine: `run.sp` (the file to run),
the deck with its includes pointing into `models/`, every included file
there (translated where its row says), the other files of the deck's
folder, `expect.json`, `measures.json` and a README. The command runs each
folder from a copy in another place and fails when a measure differs from
the gate's. It replaces an earlier bundle and refuses a folder of that
name that holds no `run.sp`. Send the folder, not the deck, to a person
who runs it elsewhere: the deck alone stops with an error or prints
another number (M105).

Not a gate: `workcenter fields <project> [--strict] [--model] [--spec
FILE] [--out DIR]` reads `<project>/fields.json` and the `.kicad_pcb`. For
each group of nets it builds a model from the board file with no
hand-written mesh: the copper, the reference pour under each track, the
dielectrics, a 50 ohm port at each end. It runs openEMS as its own
program and holds impedance, return loss, insertion loss, NEXT and FEXT
to the limits, each with its source. It writes
`build/fields/<group>/model.json`, the solver's input under
`build/fields/<group>/openems/`, and `build/fields/report.md` and
`report.json`. It refuses a track with no reference pour under it, a pour
of another net between a track and its plane, a via through a plane, an
open end as a port and a port on another net's pad. The impedance is
judged only on a net of 2 ports, 1 width, 1 layer and no branch. The
model has no conductor loss and no copper thickness. Exit 0 when every
limit holds, 1 on a failure, a solver fault or a file it does not take, 2
when openEMS is absent, there is no `fields.json`, or no limit was held.
The `fields` skill is the procedure.

Not a gate: `workcenter measure <project>` runs SIM and writes
`build/measure/plan.md` and `plan.json`. For each bound of each deck it
names the pad of the net the deck's node names (a test point first, then a
connector pin), the reference pad, the instrument, the span the reading
must fall in, the predicted value as written and over the corners, and the
`alter` lines in force. `v(a) - v(b)` is probed at a against b. A bound it
cannot place to a pad is listed as NOT PLANNED with the reason, and the run
exits 1. Ordering, assembling and measuring the board are the owner's acts;
the plan's Reading column is theirs to fill. The `fabrication` skill is the
procedure.

Not a gate: `workcenter new <dir>` starts a board project
(`tools/newboard.py`). It writes `design.py` from
`templates/project/design.py` under the folder's name with a namespace of
its own, `.gitignore`, `parts.csv` with the header `procure` reads, and
`library/sources.csv` with the header `fetch --row` appends to; a
`library/sources.csv` above, found as `fetch --row` finds it (it stops
at the project's own `.git`), serves instead. A file that is there is
kept. A folder that holds `design.py`, `chip.json` or a KiCad project
file is refused in 1 line, and so are an empty name and a path that
cannot be written; every path is judged before the first write, so
nothing is written. It runs no engine. `workcenter next` names it on a
folder with no design.

Not a gate: `workcenter next <project>` names the one next step
(`tools/guide.py`): what to do, the command, why, what to read, and when
the step is done. It reads `build/gates.json`, `build/verify.json` and
`build/ratings/report.json`, asks for a new run when an input is newer
than a report, and answers the first failure or warning with the fix for
its kind; a design file that `workcenter design` refuses is answered with
its first problem. A project with a `ratings.json` is held to its parts'
ratings in 2 places: a stress that fails, or a file `ratings` does not
take, comes before the gates, since a part that changes takes its routes
with it; what is left not judged comes after them, and the project is not
done until the last line is `RATINGS HELD`. A board generated without
`--route` is told to route before the gates: the answer counts the pads
on nets with no track, via or pour. It exits 0 when nothing is left and 1
when a step is named; exit 1 is no error, it means do the step. A finished
project gets no `RUN`
line. It writes nothing. For a chip project (`tools/chipguide.py`) the
order is `chip.json`, the engines and the process kit, the RTL, a bench,
a file that is still the example `chip init` wrote, the chip gates'
report, its first failure, its first warning, and a `README.md` that
still says `fill:`.

Not a gate: `workcenter fetch <url> --to <library>/<maker>/<file>` fetches
one datasheet, model or body once under the workcenter's own name (a
refusal is reported, never retried), keeps it, and prints its
`sources.csv` row: the URL, the file, its SHA256, today as `Checked`, a
model's `.SUBCKT`, and lines of the file that may carry its revision.
`Revision` and `Dated` are left for the reader to fill from the file.
A body that is empty, cut short, served as `text/html`, starting as an
HTML page, or a `.pdf` that does not start `%PDF` is refused in 1 line
and nothing is written.
`--file <path> --url <url>` keeps a file a person downloaded instead: it is
judged the same way, copied, hashed, and its row's Note says the workcenter
did not fetch it. `--row` with `--mpn` appends the row and refuses a second
row of one kind for one part. With no `sources.csv` at or above `--to`,
and `--to` under a folder named `library`, it starts that folder's
`sources.csv` with its header and prints `sources: started <path>`. For a
part before any board names it; `workcenter sources` then checks the row
like any other, and fails a kept file that is empty, an HTML page, or a
`.pdf` without `%PDF` (`PROCESSES.md` P27).

Not a gate: `workcenter curve <pdf> --page N` lists the page's vector
paths grouped by kind, stroke width, paint and colour, with the stroked
rectangles as candidate frames and the numeric labels where they stand.
With `--frame x0,y0,x1,y1 --x log|lin:MIN:MAX --y log|lin:MIN:MAX` it maps
each curve inside the frame onto the plot's axes and prints it; `--at`
gives each curve's y at the x values named, `--at-y` the x at the y values.
A line drawn as a filled outline of its two edges is reduced to its middle.
pdfminer reads the PDF under the venv. Use it for a curve the decks or the
calculations take a number from (a fuse's time-current curve, a safe
operating area), instead of reading the picture by eye.

Not a gate: `workcenter design <design.py> --check` regenerates the design
into a temporary folder and compares the `.kicad_pro` and `.kicad_sch` with
the design's own, the step a board repository's CI runs. It holds the
project's library tables (`fp-lib-table`, `sym-lib-table`) to what the
design writes in its own folder: each project library named from that
folder, never by an absolute path. It exits 1 on a difference, and on the
design step's own exit 1 even when every file is the same (M85).

Not a gate: `workcenter ci [repo]` replays a repository's GitHub workflow
here: every `run` step in order under `bash -e`, from the repository root,
`$GITHUB_ENV` and `$GITHUB_PATH` carried between steps, `${{ env.X }}`
read, steps whose name matches `--skip` (install and upload by default)
and `uses:` steps skipped. It prints `CI REPLAY GREEN` only when every step
it ran exited 0, and writes each step's script and log in `build/ci/`. Run
it before a board repository's push (`PROCESSES.md` P14); the steps write
what the workflow writes, so run it on a copy where the repository is
read-only.

Not a gate: `workcenter mutate <firmware> --mutations <file>` proves a
firmware's host tests can fail (`PROCESSES.md` P18): each mutation in the
project's list (JSON, or a Python file's `MUTATIONS` read as a literal) is
applied to its own copy of the firmware without `build/`, and the test
command (`make -k test` unless the list or `--test` names another) must
fail on it. Every mutation's text must be in its file exactly once, checked
before anything runs, and the tests must pass unmutated. A mutation that
survives, or that a compiler stops, fails the run. The project's tree is
never written. A list may name `COPY`, the paths each copy holds.
`make mutate-ratings` runs the ratings engine's list.

Not a gate: `workcenter ratings <project>` holds the schematic to its parts'
ratings, for a project with a `ratings.json` beside its schematic (`--init`
writes the first one; without the file the command skips, exit 2). It
exports the netlist with `kicad-cli`, takes each part's manufacturer part
number from the parts files (`--parts`, default `<project>/parts.csv`) and
each part's facts from `library/facts/*.json` in the project's folder or a
folder above it, and works out the voltage span of every net from the nets
`ratings.json` states and from what each part's facts say the part does.
Then it holds every stress to a limit: a pin's voltage to its absolute
maximum; a supply pin to its working range; a capacitor's, a resistor's, a
diode's and a transistor's voltage and a resistor's power to the share of
the rating that the rule pack allows (`rules/ratings/nasa-eee-inst-002.json`,
`ecss-q-st-30-11c-rev2.json`, or a pack of the project's own); a
regulator's load to what it gives; an output a divider sets to that
divider's sum; a buck converter's inductor to its peak current; and the
capacitors and the inductor a datasheet asks for to what stands in the
schematic. A fuse's facts name its style: `fuse.cartridge` (NASA
EEE-INST-002 F3 table 4), `fuse.cermet` (ECSS table 6-17), or `fuse`. A
fuse no row covers, or that ECSS grants no share (clause 6.17.1a), fails
over its own rating, and at or under it its derating is not judged. An
entry of facts that gives a pin's name to another number
than the schematic's symbol does fails too. A line is `fail`, `accepted`,
`not judged` or `hold`. A line that holds a stress to a limit names the
limit's document; a pack's rule, a pin's limit and a needed part name
the page too. The last line is `RATINGS HELD`,
`RATINGS HELD, N NOT JUDGED`, `NOTHING JUDGED` or `RATINGS NOT HELD`. Exit
1 on a failure, on a run that judged nothing, on a file the command does
not take, and with `--strict` on what was not judged. `--facts REF` prints
an entry of facts to fill for 1 part. It writes `build/ratings/netlist.xml`,
`report.md` (every line, the holds too) and `report.json`. It judges steady
voltages and stated currents: no transient, no temperature, nothing of the
board. `ratings.json` may state a part's heat, `"U1": {"watts": 0.4,
"source": ...}`, or the heat that leaves by 1 pad, `"U1.2"` (not both);
`ratings` does not judge it, and `workcenter copper` spreads it through the
board. The `ratings` skill is the procedure and holds both file formats.

Not a gate: `workcenter now [TREE] --item N --status Todo|"In progress"|Done
[--doing LINE]... [--blocked WHO] [--left LINE]... [--title] [--write
CHECKOUT]` prints the work card of 1 piece of work in progress. Its first
line is `**Status:**` and the project board's own word; then 6 sections:
Branch, Doing now, Health gate, Blocked on, Left, Updated. Work that waits
on someone stays In progress and says so in Blocked on. The work is the
issue's title, `Work card: <the work>`, which `--title` prints; the card
repeats nothing else the board shows. It reads the branch, the last commit
and the roadmap item's title from the tree, and the last `make verify`
verdict from `build/verify.json`, which `verify/verify.sh` writes on exit
with the commit the gate started on. It refuses, in 1 line, a card with no
status or another word, more than 3 `--doing` lines, a value with a line
break or a `**Status:**` line of its own, `--item` or `--blocked` that
starts with `#`, or a value, branch or commit subject that names an
assistant, a model or a session. `--write` writes the card under its title
to `now/<branch>.md` in a checkout of the `status` branch and prints the
git commands to commit and push it; it runs none. The workflow Board
(`.github/workflows/board.yml`, `tools/board.py`) puts each issue titled
`Work card: ...` in the column its `**Status:**` line names, and a closed
card in Done: on the card's own event, and once a day and by hand for every
card (`--all`), so a missed run is put right; it needs the repository secret
`BOARD_TOKEN`.

Not a gate: `workcenter highspeed <project> [--strict] [--verbose] [--out
DIR]` holds the fast pairs `interfaces.json` names to their interface's
file in `rules/interfaces/`, each limit with its document, clause and page.
It reads the stackup from the `.kicad_pcb`, sublayer by sublayer, and
measures each pair's gap on the board. A 2-D cross-section solver
(`tools/xsection.py`, under the venv) gives the width band for the
interface's impedance at that gap. It judges each segment's width, every
run's gap, the stretches with no partner, the length (or delay), the skew
within the pair, the vias, and every point over the ground pour that
bounds the track above and below; under the TI files also the 30 mil to
other signals' tracks and a ground via beside a via that changes the
planes. A width beside ground on the track's own layer, a half-routed
net's length, skew and plane, and a limit the documents set that the
command does not judge are printed as not judged; with `--strict` they
fail. It writes KiCad's rules (`track_width`, `diff_pair_gap`, `length`,
`skew`) into `build/highspeed/highspeed.kicad_dru`, which `workcenter drc
--fab` reads; KiCad's `diff_pair_gap` reads only nets named `_P`/`_N` or
`+`/`-`. The last line is `HIGHSPEED HELD: N held, M not judged` or
`HIGHSPEED FAIL: ...`. The `highspeed` skill is the procedure.

Not a gate: `workcenter copper <project>` solves the board's own copper for
a project with a `.kicad_pcb`, a `ratings.json` and a `copper.json` beside
it. It reads the copper with KiCad's `pcbnew` module (pads, tracks, arcs,
vias, filled pours) onto a grid of square cells, 0.05 mm by default; each
cell holds the part of its area that is copper, so a straight track along
x or y of any width reads R = rho L / (w t). Copper at an angle reads high,
on the safe side: at 45 degrees a 0.127 mm track reads 23 % high on the
drop, and the skill gives the figures. A `grid.drop` wider than the
narrowest track of a judged net, and a `grid.heat` that is not a whole
number of it, are refused. For each power net `copper.json` names, the
net's entry pins (`from`, 1 pin or a list for a supply on several
contacts) are held at 0 V and each other pin with a current in
`ratings.json` draws it. A pin of the net with no stated current is taken
as 0 A and printed as not judged, and so is a pin of the entry's part that
`from` does not name. The drop and the heat are solved in turn, each
cell's copper at its own temperature, until the drops settle. A via or a
plated hole joins its layers through the ring of cells round its drill.
The greatest drop of a drawing pin, the greatest current density in the
copper, and the greatest current density in a barrel, pi ((r + plating)^2
- r^2), are held to the net's `volts` and `amps_per_mm2`. The plating is
`copper.json`'s `plating` with its source, or the board's own setting, and
the report names which. The board's temperature is a steady state on a
grid of 0.25 mm: each layer's copper and its share of the FR-4, the layers
joined through the laminate and the barrels, `h` on the 2 faces to air at
the stated ambient. The heat comes from each part's `watts` in
`ratings.json` (on the part, split over its pads by copper area, or on 1
pad), or a stated current through a resistor's Value, entering at its pads
on the board, and from each net's own I^2 R. A part's heat with no pad on
the board is not judged. The hottest cell is held to `temperature`. The
constants are `rules/copper/materials.json`'s, each with its document and
page; `h` is 10 W/m2 K (TI SNVA419C, table 1, page 4) unless `copper.json`
states its own. An ambient at or below -234.5 C, where copper's
resistivity by NBS Handbook 100's linear coefficient reaches 0, is
refused. A net that carries a stated current, or that `ratings.json`
names, and is not in `copper.json`, and a limit not stated, are `not
judged`. The last line is `COPPER HELD`, `COPPER HELD, N NOT JUDGED`,
`NOTHING JUDGED` or `COPPER NOT HELD`. Exit 1 on a failure, on a run that
judged nothing, on a file refused, and with `--strict` on what was not
judged; exit 2 when numpy, pcbnew or Pillow is missing. It writes
`build/copper/report.md`, `report.json` and a PNG of each net's drop and
density on each layer it has copper on, and of the temperature on each
layer. The report states its assumptions: a steady state, no enclosure and
no air flow, a part's heat leaving by the board alone. The `copper` skill
is the procedure and holds `copper.json`'s format.

Not a gate: `workcenter references` keeps the index of the documents the
rules cite, `rules/references/index.json`: each standard and datasheet
with its maker or issuer, number, title, revision, URL and the SHA256 of
the copy the rule was written from. The repository holds the index, never
a document. `workcenter references fetch [ID ...] [--to DIR]` asks each
URL once under the workcenter's own name. It keeps each answer in DIR
(default `~/.cache/ee-workcenter/references`, never inside a repository)
with a `ledger.json`, and a later run asks again for none (`--again ID`
asks once more). Each document is `kept` (the indexed copy), `changed`
(another SHA256; the copy is kept for a reader), `refused` (401 or 403;
never asked under another name), `gone` (404 or 410), `not given` (429 or
a 5xx: no copy and no verdict) or `not reached` (no answer). `not given`
and `not reached` are not recorded and are asked again. Exit 1 on a
`changed`, `refused` or `gone` document, else exit 2 on a `not given` or
`not reached` one. A ledger of another shape is refused on 1 line.
`workcenter references check FILE [--id ID] [--keep]` says whether a file
a person downloaded is the copy an entry names. `workcenter references
rules [PATH ...]` fails each document a rule file names under `document`
or `source`, or in a table `documents: {id: {...}}`, that the index lacks,
names at another URL, or names without both a URL and a SHA256. Only a
source whose `document` is `no datasheet: <why>` or `no document: <why>`
is not judged. A document served in a zip names the zip's SHA256 as
`zip_sha256`, and the index holds the zip. It reads the names in a
`.kicad_dru` file and in a JSON rule's texts, and each URL of a
`.kicad_dru` file. It reads tool code and tests: a file declares each
document it cites in a module-level `CITES = {"<id>": "<where>"}`, and a
name with a section, table, page, clause or equation beside it fails when
the index or `CITES` lacks it. A web page is held by the values read from
it, not by a SHA256: `fetch` says `kept` when each stands on the page,
`moved` when 1 is gone. A paper or a book is cited and not held.
`make verify` runs it on the globs the index lists under `rules` and `code`
through `tests/test_references.py` and `tests/test_references_code.py`.
The `references` skill is the procedure.

Not a gate: `workcenter standards <project> [--strict]` reads
`product.json` (`kind`, `tests`), `verification/traceability.md` and
`board-rules.json`, and prints 1 line for each requirement of the kind in
`rules/products/`: `held by a gate`, `held by a test` or `not held`, with
the document and clause. A gate holds a requirement only when every board
of the project, nested ones too, runs its layout pack with 0 fail and 0
not judged. Exit 1 with `--strict` when any is not held. It writes
nothing. The `standards` skill is the procedure.

Not a gate: `workcenter verify <project>` checks the project's verification
package (`PROCESSES.md` P28, the `verification` skill) in
`<project>/verification/`: the files it must hold, a requirements table
whose every row has a source, a method and an inspection clause, a writeup
with every section for each circuit that names its `sim/<deck>.cir`, a
writeup for every deck, links that lead somewhere, and a traceability row
for every requirement. It runs the SIM gate and compares every number
quoted beside a `deck.meas` in a table with the run, to half a unit of the
quoted digit, and recomputes each traceability check (`deck.meas <= 30 V`)
against the stated verdict, at the least and the greatest value its measure
takes over the deck's corners: a row that says PASS while a corner fails is
a problem. A FAIL verdict is a finding, not a problem;
`--strict` fails on a FAIL or an OPEN requirement too, and on decks that
ran without corners. `--init` copies
`templates/verification/` into the package, a writeup per deck, never over
a file that exists. It writes `build/verify.json` and the decks' logs.

The owner's decisions are part of the package. A requirement the owner
withdrew moves to the requirements' Withdrawn table (`| ID | Date |
Decision | By |`): `verify` names each withdrawn ID in its summary, leaves
it out of the counts, and fails on a traceability row or an expect bound
that still names it, or on a withdrawn ID still in a requirements table. A
requirement the owner restated or added names "the owner's decision of
2026-11-06" in its Source, and `verify` checks that the date is one.
`templates/verification/BRIEF.md` and `FACTS.md` are the lead's brief and
facts file for helpers who write parts of one package at the same time
(the `verification` skill's "Helpers"); `--init` leaves them out.

A project kept as version folders (`PROCESSES.md` P22) lays out each
version's README as `templates/project/README-version.md` and its gates
report, `docs/gates.md`, as `templates/project/gates.md`, whose marker
comments `workcenter gates <project> --report` fills. A project that is
improved in a review loop keeps the loop's prompt, its checklist and its
log in `LOOP.md` beside the version folders, from
`templates/project/LOOP.md` (the `board-loop` skill).

A model under the deck's own folder (`sim/models/`) is the project's own,
fitted to a datasheet when the maker publishes none: the SIM gate needs no
library row for it. An expect bound may name the requirement it serves:
`"req": "REQ-USB-05"`.

The documents a version carries come from commands too, so no copy goes
stale (`tools/doctools.py`):

- `workcenter gates <project> --report docs/gates.md` also writes the gates
  table between `<!-- workcenter gates NAME -->` and
  `<!-- /workcenter gates NAME -->`, and the deck list (each `sim/*.cir`, what
  it simulates, its bounds and its result) between `<!-- workcenter decks
  NAME -->` and `<!-- /workcenter decks NAME -->`, NAME being the project's
  `.kicad_pro` name. A missing block is added at the end, a new file gets a
  title; the prose round the blocks stays as written. The exit code is the
  gates'.
- `workcenter docs <version>` writes the version's `CONTENTS.md` (its
  README's sections, design and KiCad files, scene scripts, decks, the
  verification package, firmware, pictures, parts lists) and copies each
  part's datasheet from the library into `<version>/datasheets/` by
  `sources.csv`, with its revision, or says why there is none. It reads the
  priced lists `costs` writes; a part whose datasheet is a series sheet
  kept under another part number is named in `library/series.csv`
  (`Pattern,MPN`). A copy of a library file no part names any more is
  removed; with a board's list missing it copies and removes nothing and
  exits 1.
- `workcenter costs <repo>` runs `procure` on every board of every version
  with `parts/version/<id>.csv` ahead of `parts/catalog.csv` and
  `parts/offboard/<id>.csv`, `<id>` being the version (`v0.16`) or the
  version and a nested board's folder (`v0.16-display`). It keeps the
  lists in `parts/lists/<id>.csv` and `.md`, and writes the totals table
  into every Markdown file holding `<!-- workcenter costs -->` ...
  `<!-- /workcenter costs -->`, and the links to the lists into every
  `<!-- workcenter costs lists -->` block (M97). A marker counts only alone
  on its line, as the command writes it: one named in a sentence is prose
  (M176).
- `workcenter pictures <version>` is `PROCESSES.md` P23 in one command,
  from the version's `pictures.json` (written with the defaults when
  absent): each board's `render --strict` stills and layers, its turning
  GIFs, the scene scripts, then the copies into `docs/` and `docs/layers/`.
  `--frames 4` is the framing check: one sheet of frames per GIF under
  `build/pictures/check/`, `docs/` untouched.
- `tools/scene.py` is the general part of an assembly: it loads a routed
  board with KiCad's `pcbnew`, makes bodies (`cylinder`, `box`, a `wrlgen`
  preset, another board through kicad-cli's VRML export), places each at
  board coordinates, renders named views and turns the scene into a GIF.
  A project's scene script holds only its placements; `pictures` runs it
  with `tools/` on `PYTHONPATH`.
- `workcenter version new <repo> <vNEXT>` does `PROCESSES.md` P22's
  mechanical steps: the latest folder copied without `build/`, the new
  README's banner naming where it came from, the previous README's banner
  archived with its last commit, the root README's table row (`(current)`,
  `in work`) and the previous row's commit, `CLAUDE.md`'s version
  references moved, the parts files copied. It prints what stays by hand.
- `workcenter diagram <spec.json> --out <file.svg> [--png]` draws a block
  diagram from a spec: blocks, rails as bars, arrows coloured by what flows
  in them (power, load, logic, sense, return, data), boards as dashed
  groups, a legend of the styles used. `templates/verification/system/
  block-diagram.json` is the starter `verify --init` copies.

`SOURCE_DATE_EPOCH`, when set, is the day and the time every command
writes into a file (the gates report's day among them), in UTC: a build
that pins it gets the same report from the same files on any day. It
never sets the day a price's age is judged on, the `Checked` day `fetch`
writes, or the engine lock's times: those are the machine's clock.

A project may add gates. It may not remove these.

### Chip gates

A chip project is a folder that holds `chip.json`. Its gates run in this
order and stop at the first that does not pass. Every one is required: a
gate that did not run is the verdict, `SKIPPED (GATE: reason)`, however
many passed.

| Gate | Command | Pass condition |
|---|---|---|
| LINT | `workcenter chip lint <project>` | Verilator names no construct that a simulator and a synthesizer read differently, and no line of the RTL speaks to 1 engine alone (a `lint_off` comment, an `` `ifdef `` on an engine's own macro, `translate_off`, `$readmemh`); `chip.json` is sound, with a source for each number; the constraints name 1 clock, a delay for setup and for hold on each bit of each port, each option 1 time, and no margin that gives time away |
| SIM | `workcenter chip sim <project>` | every bench in `tb/` ends at `$finish` with `errors = 0`, 1 check at least and `x_outputs = 0`, holds the bounds of its expect file, and reads no file while it runs; every change of `rtl/mutations.json`, each made in a file the RTL alone reads, fails a bench |
| SYNTH | `workcenter chip synth <project>` | Yosys maps the RTL onto the library's cells with 0 problems: no latch, no loop, no net with 2 drivers, a reset on every flop or an answer in `chip.json` |
| LAYOUT | `workcenter chip layout <project>` | OpenROAD places and routes with 0 violations and no open pin, each supply net's grid connected, within the utilisation limit; Magic writes the GDS with the top cell alone |
| STA | `workcenter chip sta <project>` | at every corner the project's ranges select: setup and hold slack 0 or more, no pin over a slew, capacitance or fanout limit, the skew within its limit, every net with its extracted parasitics |
| GLSIM | `workcenter chip glsim <project>` | the benches pass on the routed netlist with the library's cell models, with the count of checks they made on the RTL; no bench asks for a name the gate defines for this run alone |
| DRC | `workcenter chip drc <project>` | 0 items in each deck of the process table: Magic's and KLayout's |
| ANTENNA | `workcenter chip antenna <project>` | no net and no pin over its antenna ratio on the routed database |
| LVS | `workcenter chip lvs <project>` | Netgen matches the extracted layout and the netlist with its supply pins, every comparison uniquely |
| EXPORT | `workcenter chip export <project>` | each of the 9 gates holds a record of its pass on the files as they are now; the layout, the netlists, the parasitics and 1 SDF file for each corner are copied to `build/chip/tapeout/` with `manifest.json` |
| ALL | `workcenter chip gates <project>` | the 10 gates above in order; `--strict` makes each warning a failure |

The last line is the verdict with the project's name and the report:
`GREEN: uart  report <project>/build/gates.json`. The words and the exit
codes are those of "Verdicts". The line above it is the scope of the run:
the engines are open, the process kit and its version, each rule deck
with its origin, the corners. GREEN says that these engines found no
fault in these files. It does not say that a foundry accepts the layout
or that the silicon works: no foundry deck runs here, and no shuttle's
limits are held.

The process is a table in `pdks/` (`pdks/README.md`): `sky130A` with the
library `sky130_fd_sc_hd`. The first flow takes 1 clock, no memory macro
and no analog block. The engines install on request:
`sudo ./install.sh --chip`.

## Paths

| Purpose | Path |
|---|---|
| Install root | `/opt/workcenters/ee` |
| Engine environment | `/opt/workcenters/ee/env.sh` |
| Tool cache | the session scratchpad; the engines write nothing outside the output directory |
| Project output | `<project>/build/` (reports, `fab/`, `sim/`, `route/`, `render/`, `ratings/`, `board-rules/`, `measure/`, `fields/`, `copper/`, `highspeed/`) |
| Chip project output | `<project>/build/gates.json`, the report, and `<project>/build/chip/`: 1 folder for each gate that ran, and `hashes.json` with the hash of each file a gate wrote or judged. `<gate>/passed.json` is there when that gate passed: the hash of each file it read, taken before its engines started and held to the same bytes after, and of each file it hands on. The files of the project in it are those the gate finds by the text and those its engine says it read (Verilator's XML, the list Icarus Verilog writes, the rule Yosys writes): a header is in the record however the RTL names it. A file of the project is named from the project's folder (`rtl/top.v`, and `./chip/notes.v` for one under a folder `chip`) and a file the gates wrote from the output folder (`chip/layout/top.gds`), wherever `--out` points. EXPORT asks each of the 9 gates before it for that record and holds every file to it: the RTL and each header it includes, the benches and their bounds, the constraints, `chip.json`, the mapped netlist the layout was built from, and the layout's own files. A file of the project that came after a gate passed is refused too. `workcenter next` holds the files to the same records before it reads the report. `tapeout/` holds the files EXPORT hands out, `manifest.json` and the judging gates' reports; a gate that is asked to run takes it away, with the record of its own earlier pass. `render/` holds the pictures of `workcenter chip render`. The gates empty the folders under `<out>/chip`, and only in a folder they made: `--out` is refused when that folder is the project's, holds a file of it, or is there with files and without `hashes.json`. A path with white space is refused too. |

## Project requirements

- `.gitignore` entries: `build/`, `*.kicad_prl`
- Files: one `<name>.kicad_pro` with `<name>.kicad_sch` and `<name>.kicad_pcb` beside it
- Optional: `design.py` exposing `build() -> kicadgen.Design`, the source the KiCad files are generated from
- Optional: `sim/<deck>.cir` with `sim/<deck>.expect.json` for the SIM gate; `sim/models/` for the project's own fitted models
- With decks: `sim/corners.json`, the temperature range and the parts' tolerances every bound must hold over (start from `templates/project/corners.json`); the gate warns without it
- With decks that drive periodic sources: `sim/frequency-plan.json`, the sources and the measured resonances (start from `templates/project/frequency-plan.json`); the gate warns without it
- With parts that dissipate power: `sim/thermal.json`, the rating pack and, for each part, its number and the deck measure that prints its power; the part's facts give `thermal` (the `simulate` skill, "A part's temperature")
- Optional: `verification/` for `workcenter verify` (P28)
- Optional: `ratings.json` beside the schematic, and `library/facts/*.json`
  in the project's folder or a folder above it, for `workcenter ratings`;
  the `ratings` skill has both formats
- Optional: `interfaces.json` beside the board, `{"interfaces":
  [{"interface": "<file in rules/interfaces/>", "nets": ["<P>", "<N>"],
  "gap": <mm>}]}`, for `workcenter highspeed`; `gap` is optional and is
  held to the gap the tracks have
- Optional: `copper.json` beside the board, each power net's entry and
  limits for `workcenter copper`; it needs `ratings.json`
- Optional: `fields.json` beside the board, the critical nets and their
  limits for `workcenter fields`
- Optional: `panel.json` beside the board, a KiKit preset; it asks EXPORT
  for a panel
- Optional: `board-rules.json` beside the board, `{"pack": "<name>"}` or
  `{"layout": [...]}`, for the board rule pack the DRC holds the board to; a
  `pack` needs `ratings.json`
- Optional: `product.json` beside the board, `{"kind": "<kind>"}`, for
  `workcenter standards`
- Optional, a project kept as version folders (`v0.1/`, `v0.2/`, ... at the
  repository's root, a nested board one folder down): `parts/catalog.csv`,
  `parts/version/<id>.csv` and `parts/offboard/<id>.csv` for `workcenter
  costs`, which writes `parts/lists/`; `<version>/pictures.json` for
  `workcenter pictures`; `library/series.csv` for `workcenter docs`
- Optional: `library/sources.csv` at or above the project, with the files it
  names beside it, for `workcenter sources` and the vendor models a deck
  includes. Columns: `MPN,Kind,URL,File,Member,Revision,Dated,Subckt,Ngspice,SHA256,Checked,Note`;
  `Kind` is `datasheet`, `spice` or `step`; a row with no `File` needs a `Note`;
  `workcenter fetch --row` adds one, and starts the file with this header when the project has none
- Optional: a firmware mutation list (JSON, or a Python file with `MUTATIONS`)
  kept with the firmware, for `workcenter mutate`
- A chip project (`workcenter chip init <dir> --top <module>` writes its
  first files): `chip.json`, the constraints (`constraints.sdc`), the RTL
  (`rtl/*.v`, `rtl/*.sv`) and 1 bench at least (`tb/tb_<name>.v`);
  `.gitignore` entry `build/`. With benches: `rtl/mutations.json`, the
  changes of the RTL that the benches must catch (the SIM gate warns
  without it). Optional: `tb/<bench>.expect.json`, bounds on what a bench
  prints
