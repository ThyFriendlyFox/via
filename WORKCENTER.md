# WORKCENTER.md — EE Workcenter

<!-- This file at the root marks the repository as a workcenter to
     skills/attached-repos. install.sh copies it to
     /opt/workcenters/ee/WORKCENTER.md so an environment without the
     repository attached still finds it. -->

The EE Workcenter turns a KiCad 10 project into fabrication outputs that
passed every gate. "Done" means `workcenter gates <project>` prints GREEN.
`workcenter next <project>` names the one step that is left at any point.

## Verdicts

The last line of `workcenter gates` is the verdict. Its exit code says the
same.

| Last line | Meaning | Exit code |
|---|---|---|
| `GREEN` | Every gate that had something to run passed, with no warning. | 0 |
| `GREEN with N warnings` | Every gate passed, and N things were named and not failed on. Each is printed. The project's gates report names each one it keeps, and why. `--strict` fails on all of them. | 0 |
| `RED` | A gate failed, or an engine stopped with an error. | 1 |
| `SKIPPED (GATE: engine missing)` | A gate did not run because its engine is absent. A run with an absent engine is never GREEN. | 2 |
| `SKIPPED` | No gate had anything to run. | 2 |

`workcenter doctor` reports each engine as ok, absent or MISSING. A gate
whose engine is absent is skipped with the engine's name.

`workcenter verify` ends with a line of its own. `REQUIREMENTS MET` needs
every requirement PASS, no problem in the package, and the decks run at
their corners. `REQUIREMENTS NOT MET (...)` names what is short. The gate's
own status, `PASS verify`, says only that the package agrees with a fresh
run: a package that records a FAIL honestly passes it.

## Tools

| Tool | Version | Command | Installed by |
|---|---|---|---|
| KiCad | 10.0 | `kicad-cli` | `install.sh` (PPA kicad/kicad-10.0-releases) |
| ngspice | 42 | `ngspice` | `install.sh` (Ubuntu 24.04 archive) |
| FreeRouting | 1.9.0 | `workcenter design <design.py> --route [--seed <previous .kicad_pcb>]` (generated boards, headless); `workcenter autoroute <project> [--dsn file]` (hand-drawn boards, DSN from KiCad) | `install.sh` (GitHub release, SHA-256 pinned; 2.1.0 hangs after routing when its GitHub version check cannot succeed) |
| kicad-python (kipy) | 0.8 | `/opt/workcenters/ee/venv/bin/python` | `install.sh` (PyPI) |
| librsvg | 2.58 | `rsvg-convert` (SVG to PNG for `workcenter render`) | `install.sh` (Ubuntu 24.04 archive) |
| FFmpeg | 6.1 | `ffmpeg` (the turning GIF of `workcenter render --views spin`) | `install.sh` (Ubuntu 24.04 archive) |
| kicadgen | this repo | `workcenter design <design.py> [--route [--seed <board>]\|--check]`; `python3 tools/kicadgen.py pins\|footprint\|symbol-add` | `install.sh` (part of the checkout) |
| pdfminer.six, PyYAML | 20260107, 6.0.3 | `workcenter curve` (a PDF page's vector paths), `workcenter ci` (a GitHub workflow), each run under the venv | `install.sh` (PyPI) |
| workcenter CLI | this repo | `workcenter` | `install.sh` (symlink to `tools/workcenter`) |
| scene | this repo | `tools/scene.py`: assembly scenes a project's script builds, run by `workcenter pictures` | the checkout; KiCad's `pcbnew` and FFmpeg by `install.sh` |
| kistack | `641ade9` | `.claude/skills/kistack/SKILL.md` routes to `third_party/kistack/skills/`; `workcenter placement <check> <board> [args]` runs its placement checks | the checkout (vendored, `third_party/kistack/VENDORED.md`); shapely, numpy and pygerber by `install.sh` (PyPI) |
| Board inspection | this repo | `workcenter inspect <view> <board> ...`, the views `map`, `list`, `probe`, `net`, `islands`, `resistance`, `crossed` (KiCad's `pcbnew` and Pillow under the venv); `python3 tools/stretch.py <design.py> --cut X --grow G` | `install.sh` (part of the checkout; Pillow from PyPI) |
| Corners and frequency plan | this repo | `sim/corners.json` and `sim/frequency-plan.json`, read by `workcenter sim` (`tools/simcorners.py`, `tools/freqplan.py`); `workcenter sim --bundle <dir>` for a deck that runs on any machine | the checkout; ngspice by `install.sh` |
| Next step | this repo | `workcenter next <project>` (`tools/guide.py`) | the checkout |

## Skills

A skill is a Markdown procedure at `.claude/skills/<name>/SKILL.md`. A
host that loads skills offers each by name. Any other reader opens the
file: it needs nothing else.

| Skill | Use when |
|---|---|
| `attached-repos` | The session holds more than 1 repository. Run first. |
| `board-design` | A board is designed from a spec, as a Python design file built from the KiCad libraries. |
| `board-gates` | A board must pass ERC, DRC, simulation, and export. The fix loop. |
| `autoroute` | A board has unrouted nets and FreeRouting should route them. Headless for generated designs. |
| `simulate` | A circuit must meet a measurable spec before layout; a part switches; a deck must run on another machine. Corners, the frequency plan, bundles. |
| `blog-post` | A human asks for a public write-up of recent work. |
| `procurement` | A human asks what a board costs, for its parts list, or to order its parts. |
| `kistack` | Placing parts, reviewing a schematic, a layout or the Gerbers, choosing a part's derating, a footprint or symbol, or a panel: it names the kistack skill for the step, and where this workcenter's rules win. |
| `verification` | A human asks for requirements, a review, an inspection, or proof that a design meets its parts' ratings: the verification package of P28, checked by `workcenter verify`. |

## Gates

| Gate | Command | Pass condition | Runs before |
|---|---|---|---|
| ERC | `workcenter erc <project>` | 0 errors in the ERC report | layout |
| DRC | `workcenter drc <project>` | 0 errors, 0 unconnected items, 0 parity errors; with the project's fab rules (`<name>.kicad_dru`) when its design names a fab | export |
| SIM | `workcenter sim <project>` | every `sim/*.cir` runs clean with no analysis aborted, every `*.expect.json` bound holds as written and at every corner of `sim/corners.json`, every overlap `sim/frequency-plan.json` shows is answered, and every library model a deck includes is unchanged since its `sources.csv` row | export |
| EXPORT | `workcenter export <project>` | gerbers, drill, BOM, schematic PDF produced | hand-off to fabrication |
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
writes KiCad's Sim fields on the symbols, so the schematic runs in KiCad's
simulator and `kicad-cli sch export netlist --format spice` writes a netlist
ngspice reads. It prints each problem as a `sim:` line and exits 1 on any: a
map that leaves a pin or a node out (KiCad would bind it by position and say
nothing), a file or a name that is not there, a node the model does not have.
With `check_sim` every part needs a `sim` or a `no_sim`, a plain R, C or L
excepted. The project raises KiCad's `simulation_model_issue` to an error, so
the ERC gate reports a model KiCad cannot load. A design that says nothing
about simulation regenerates byte for byte as before (the `board-design`
skill).

Its verdict is its exit code. It writes every file even when it exits 1 (a
hand via its check refuses, a floating input with `check_pulls`, a `sim:`
problem, an unrouted connection the router counts), and on exit 1 its last line says `red`, names
each failure, and says the files are for inspection only: a CI regenerate
check fails on that exit code (M85). Each via it drops through a pour's island
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

A board made for a particular fab checks that fab's published limits in the
DRC: `rules/` holds them as KiCad design rules (`sierra-circuits-web` for
Sierra Circuits' Web PCB: 4 mil trace and gap, 6 mil hole and ring, 13 mil
inner drill to copper, 5 mil legend). A design file's `fab = "<name>"`
writes the set into the project for good, and the router and the generator's
own via checks keep each layer's hole-to-copper rule (the 13 mil on the inner
layers, M79); `workcenter drc|gates --fab
<name> <project>` checks any project against one once, on a copy
(`rules/README.md` says what each set cannot check). A fab's limits only
add floors: its board-wide limits raise the board's own minimums, and only
its layer and condition rules go into the project's `.kicad_dru`, raised to
the board's own where those are stricter. A board-wide custom rule would
override every net class's clearance in KiCad's DRC.

Not a gate, but part of every hand-off: `workcenter render <project>` writes
the schematic, board top and bottom, and 3D images into `build/render/`, and
every layer that has something on it into `build/render/layers/` (one PNG per
layer with the outline, bottom layers seen from below) with an overview sheet,
`build/render/layers.png`. `--views spin` adds `build/render/board-spin.gif`,
the 3D board turning once round (`--spin-frames`, `--spin-tilt`, `--spin-zoom`,
`--spin-pivot`;
a minute or two of frames). `--views` takes any of schematic, 2d, 3d, layers,
spin, or all. Its summary names every part the 3D views draw without a body
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
with its source. The gate runs a deck once for each temperature, twice for
each part (its value less and plus the tolerance), once for the worst case
of each bound, and once for each Monte Carlo draw, each run in its own
folder under `build/sim/corners/<deck>/`. A bound holds when it holds at
every corner; a failure names the corner: `isense:v_6a=1.076259 at 85 C,
R16 -1 %, R7 -1 % not in [1.14, 1.26]`. A bound with `"warn"` or `"at":
"nominal"` is judged as written only. A project with decks and no
`sim/corners.json` gets a warning, as does a deck whose measures do not
move with temperature and a part named like a board reference that no
tolerance covers. `--nominal` leaves the corners out and says so.

The SIM gate judges the project's frequency plan (`tools/freqplan.py`, the
`simulate` skill's "The frequency plan"). `sim/frequency-plan.json` names
every periodic source with its frequency and every resonance an `.ac`
deck measured. The gate fails on a source whose harmonic lies in a
resonance's band, and on 2 sources that can run at 1 frequency, unless the
plan answers the overlap with a bounded measure of a deck that drives it.
It fails on a periodic stimulus in a deck that the plan does not name. A
project whose decks drive periodic sources and that has no plan gets a
warning.

The gate reads what it is given strictly. An expect file with a key it does
not know, a bound with neither `min` nor `max`, or text that is not JSON
fails the gate with the line that is wrong. An analysis ngspice gave up on
fails its deck even when a later analysis completes. A complex value is no
measure. The user's own `~/.spiceinit` does not reach a deck. A node that
floats (`singular matrix`) is a warning.

`workcenter sim <project> --bundle <dir>` writes each deck as a folder
that plain ngspice runs on any machine: `run.sp` (the file to run),
the deck with its includes pointing into `models/`, every included file
there (translated where its row says), `expect.json`, `measures.json` and
a README. The command runs each folder from a copy in another place and
fails when a measure differs from the gate's. Send the folder, not the
deck, to a person who runs it elsewhere: the deck alone stops with an
error or prints another number (M105).

Not a gate: `workcenter next <project>` names the one next step
(`tools/guide.py`): what to do, the command, why, what to read, and when
the step is done. It reads `build/gates.json` and `build/verify.json`,
asks for a new run when an input is newer than a report, and answers the
first failure or warning with the fix for its kind; a design file that
`workcenter design` refuses is answered with its first problem. It exits 0
when nothing is left and 1 when a step is. A finished project gets no `RUN`
line. It writes nothing.

Not a gate: `workcenter fetch <url> --to <library>/<maker>/<file>` fetches
one datasheet, model or body once under the workcenter's own name (a
refusal is reported, never retried), keeps it, and prints its
`sources.csv` row: the URL, the file, its SHA256, today as `Checked`, a
model's `.SUBCKT`, and lines of the file that may carry its revision.
`Revision` and `Dated` are left for the reader to fill from the file.
`--row` with `--mpn` appends the row and refuses a second row of one kind
for one part. For a part before any board names it; `workcenter sources`
then checks the row like any other (`PROCESSES.md` P27).

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
the design's own, the step a board repository's CI runs. It exits 1 on a
difference, and on the design step's own exit 1 even when every file is
the same (M85).

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
never written.

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
comments `workcenter gates <project> --report` fills.

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
  `<!-- workcenter costs lists -->` block (M97).
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

A project may add gates. It may not remove these.

## Paths

| Purpose | Path |
|---|---|
| Install root | `/opt/workcenters/ee` |
| Engine environment | `/opt/workcenters/ee/env.sh` |
| Tool cache | the session scratchpad; the engines write nothing outside the output directory |
| Project output | `<project>/build/` (reports, `fab/`, `sim/`, `route/`, `render/`) |

## Project requirements

- `.gitignore` entries: `build/`, `*.kicad_prl`
- Files: one `<name>.kicad_pro` with `<name>.kicad_sch` and `<name>.kicad_pcb` beside it
- Optional: `design.py` exposing `build() -> kicadgen.Design`, the source the KiCad files are generated from
- Optional: `sim/<deck>.cir` with `sim/<deck>.expect.json` for the SIM gate; `sim/models/` for the project's own fitted models
- With decks: `sim/corners.json`, the temperature range and the parts' tolerances every bound must hold over (start from `templates/project/corners.json`); the gate warns without it
- With decks that drive periodic sources: `sim/frequency-plan.json`, the sources and the measured resonances (start from `templates/project/frequency-plan.json`); the gate warns without it
- Optional: `verification/` for `workcenter verify` (P28)
- Optional, a project kept as version folders (`v0.1/`, `v0.2/`, ... at the
  repository's root, a nested board one folder down): `parts/catalog.csv`,
  `parts/version/<id>.csv` and `parts/offboard/<id>.csv` for `workcenter
  costs`, which writes `parts/lists/`; `<version>/pictures.json` for
  `workcenter pictures`; `library/series.csv` for `workcenter docs`
- Optional: `library/sources.csv` at or above the project, with the files it
  names beside it, for `workcenter sources` and the vendor models a deck
  includes. Columns: `MPN,Kind,URL,File,Member,Revision,Dated,Subckt,Ngspice,SHA256,Checked,Note`;
  `Kind` is `datasheet`, `spice` or `step`; a row with no `File` needs a `Note`;
  `workcenter fetch --row` adds one
- Optional: a firmware mutation list (JSON, or a Python file with `MUTATIONS`)
  kept with the firmware, for `workcenter mutate`
