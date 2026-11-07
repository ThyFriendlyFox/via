# WORKCENTER.md — EE Workcenter

<!-- This file at the root marks the repository as a workcenter to
     skills/attached-repos. install.sh copies it to
     /opt/workcenters/ee/WORKCENTER.md so an environment without the
     repository attached still finds it. -->

The EE Workcenter turns a KiCad 10 project into fabrication outputs that
passed every gate. "Done" means `workcenter gates <project>` prints GREEN.

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

## Skills

| Skill | Use when |
|---|---|
| `attached-repos` | The session holds more than 1 repository. Run first. |
| `board-design` | A board is designed from a spec, as a Python design file built from the KiCad libraries. |
| `board-gates` | A board must pass ERC, DRC, simulation, and export. The fix loop. |
| `autoroute` | A board has unrouted nets and FreeRouting should route them. Headless for generated designs. |
| `simulate` | A circuit must meet a measurable spec before layout. |
| `blog-post` | A human asks for a public write-up of recent work. |
| `procurement` | A human asks what a board costs, for its parts list, or to order its parts. |
| `kistack` | Placing parts, reviewing a schematic, a layout or the Gerbers, choosing a part's derating, a footprint or symbol, or a panel: it names the kistack skill for the step, and where this workcenter's rules win. |
| `verification` | A human asks for requirements, a review, an inspection, or proof that a design meets its parts' ratings: the verification package of P28, checked by `workcenter verify`. |

## Gates

| Gate | Command | Pass condition | Runs before |
|---|---|---|---|
| ERC | `workcenter erc <project>` | 0 errors in the ERC report | layout |
| DRC | `workcenter drc <project>` | 0 errors, 0 unconnected items, 0 parity errors; with the project's fab rules (`<name>.kicad_dru`) when its design names a fab | export |
| SIM | `workcenter sim <project>` | every `sim/*.cir` runs clean, every `*.expect.json` bound holds, and every library model a deck includes is unchanged since its `sources.csv` row | export |
| EXPORT | `workcenter export <project>` | gerbers, drill, BOM, schematic PDF produced | hand-off to fabrication |
| ALL | `workcenter gates <project>` | the 4 gates above in order, none red | a board is called done |

`workcenter design` also lists every control input that can float while the
MCU is in reset (a gate, a logic input, a switch or an I2C line that no output
drives and no resistor holds), as `pull:` lines; a design that sets
`check_pulls` fails on one, and `defined_nets` names the nets held elsewhere
with the reason (`PROCESSES.md` P16).

Its verdict is its exit code. It writes every file even when it exits 1 (a
hand via its check refuses, a floating input with `check_pulls`, an unrouted
connection the router counts), and on exit 1 its last line says `red`, names
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
against the stated verdict. A FAIL verdict is a finding, not a problem;
`--strict` fails on a FAIL or an OPEN requirement too. `--init` copies
`templates/verification/` into the package, a writeup per deck, never over
a file that exists. It writes `build/verify.json` and the decks' logs.

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
