# {project} — board prototype {version}

> The current version of the [{project} prototype series](../README.md), started as a copy of [`../{previous}/`](../{previous}/). The earlier versions are the sibling folders, [`../v0.1/`](../v0.1/) to [`../{previous}/`](../{previous}/).

<!-- The layout of a version's README in a project kept as version folders
     (PROCESSES.md P22). `workcenter version new <repo> <vNEXT>` copies the
     previous version's README and rewrites its banner; this file is the
     layout that copy keeps, and the first version's README. Replace each
     {name}: {project}, {version}, {previous}, {next}. The sections, in order:

     1. The banner, what the device is, and the status table.
     2. Images (P23).
     3. "What changed in {version}", above the older versions' sections,
        newest first; each opens with the findings, the owner's answers and
        what the version does, then Board, Simulation, Firmware, Parts and
        cost, Verification summary.
     4. The standing sections: the board as it is now.
     5. Decisions, newest first, each with its version.
     6. Open items: "Candidates for {next}" and "On the bench".

     When {next} starts, this banner becomes the archived one, and nothing
     else in the folder changes:

     > Archived: {version} of the [{project} prototype series](../README.md),
     > as of commit `<its last commit>`. The design and KiCad files are the
     > ones that commit holds; CI still regenerates the project from
     > `design.py` and runs the gates on every push. The next version,
     > [`../{next}/`](../{next}/), <what it answers or adds>.

     Delete this comment. -->

<!-- fill: one paragraph: what the device is and does, for a reader who has never seen it. -->

<!-- fill: one paragraph: what this repository holds, and that the EE Workcenter supplies the tools and gates. -->

| Item | State |
|---|---|
| Schematics | <!-- fill: drawn with wires; ERC errors and warnings; the parity check (P24) --> |
| <!-- fill: one row per board --> | <!-- fill: size, layers, what it carries and on which face; the fab's limits it is made to --> |
| Gates | <!-- fill: every board GREEN, see [`docs/gates.md`](docs/gates.md) --> |
| Datasheets and models | <!-- fill: the files kept in the library (`workcenter sources`), the makers' models used, the fitted ones, the number of decks --> |
| Verification | <!-- fill: [`verification/`](verification/README.md): requirements, PASS, FAIL and OPEN from `workcenter verify .`; withdrawn requirements by ID --> |
| Firmware | <!-- fill: host tests and checks, the build's size against the flash, what runs in CI, whether it has run on a board --> |
| <!-- fill: one row per subsystem a reader asks about first --> | <!-- fill --> |

<!-- fill: one paragraph per earlier version, newest first: what it was and its last commit, "v0.15 (...) is under [`../v0.15/`](../v0.15/); its last commit is `f8aa018`." -->

## Images

<!-- fill: what P23 asks, with the command that drew each picture beside it:
     the assembly's turning GIF and stills (the project's scene script); per
     board the top and bottom, the 3D views, the turning GIF from the face
     that carries the parts (and from below when both faces do), and the
     layer sheet (`workcenter render`, `--views spin` with its tilt, zoom and
     pivot). `workcenter pictures .` draws them from `pictures.json`. -->

| Assembly | Turning |
|---|---|
| ![assembly](docs/assembly-iso.png) | ![assembly turning](docs/assembly-spin.gif) |

| Top face | Bottom face (mirrored) |
|---|---|
| ![top](docs/board-top.png) | ![bottom](docs/board-bottom.png) |

| Turning, from above | Every layer |
|---|---|
| ![turning](docs/board-spin.gif) | ![layers](docs/layers-base.png) |

## What changed in {version}: <!-- fill: one line -->

<!-- fill: the findings that started this version, with a link to where they are (the previous version's verification package, a bench test, the owner's request), and the date the owner answered them. -->

| Finding | The owner's answer | What {version} does |
|---|---|---|
| <!-- fill: one row per finding, a requirement's ID where it has one --> | <!-- fill: the answer in the owner's terms; "not asked in this round" where there is none --> | <!-- fill: the change, and the section that describes it --> |

### Board

<!-- fill: each part placed, moved or removed and why there; each spot tried first and why it moved; what is hand-routed now and why; what the router did (segments, vias, rounds). -->

### Simulation

<!-- fill: each deck changed or added, and the numbers that moved, old → new (`workcenter sim .`); each model added or fitted. -->

### Firmware

<!-- fill: each behaviour and constant changed, with its name; the host tests and checks; the build's size. -->

### Parts and cost

<!-- fill: the parts new, changed and removed with their part numbers; where their datasheets are in the library; the parts files changed; one device and ten from `workcenter costs`, against the previous version's. -->

### Verification summary

<!-- fill: the counts from `workcenter verify .` (requirements, PASS, FAIL, OPEN) against the previous version's; the requirements withdrawn, restated and new, each with the owner's decision and its date; mistakes the package found in this version's own first try. -->

| Requirement | {version} | Proposed fix |
|---|---|---|
| <!-- fill: one row per FAIL --> | <!-- fill: its size --> | <!-- fill --> |

<!-- The older versions' "What changed" sections follow here, newest first, as each version left them. -->

## Architecture

<!-- fill: the power and signal paths as a block sketch or a diagram, every net by its design name. -->

### Stackup

| Layer | Copper | Use |
|---|---|---|
| F.Cu | <!-- fill: thickness --> | <!-- fill --> |
| B.Cu | <!-- fill: thickness --> | <!-- fill --> |

<!-- fill: one section per subsystem (the cell, its protection, the heater, the sensing, a second board, the contacts): what it does, the parts, the numbers and their sources. -->

## Datasheets, models and simulation

<!-- fill: the library (`../library/`, `sources.csv`, `workcenter sources`), each maker's model and how it compares with its datasheet, the fitted models, and one line per deck in `sim/`. -->

## Verification

<!-- fill: what [`verification/`](verification/README.md) holds, its counts, and the history of the earlier packages' findings. -->

## Pin plan

| Pin | Port | Signal | Function |
|---|---|---|---|
| <!-- fill: every pin of the MCU, from the maker's pin data (P16) --> | | | |

## Bill of materials

| Ref | Value | Package | Face | Part |
|---|---|---|---|---|
| <!-- fill: every part, with the version that added or changed it --> | | | | |

## Regulation and safety

<!-- fill: the rules the product falls under and what the boards and firmware do for each; delete the section when none applies. -->

## Working on this board

Run the commands from this folder. From the repository root, name the
folder instead.

```sh
workcenter design design.py --route   # regenerate the KiCad project from the design file
workcenter gates .                    # ERC, DRC, simulation, export; GREEN means done
workcenter sim .                      # the sim/ decks alone; one deck: --deck NAME --keep
workcenter sources . --parts ../parts/catalog.csv   # every part against ../library/sources.csv
workcenter verify .                   # the verification package against a fresh run
workcenter pictures .                 # the renders, turning GIFs and scenes into docs/ (P23)
workcenter docs .                     # CONTENTS.md and datasheets/
```

<!-- fill: each nested board's commands, the firmware's, and what is generated from what. -->

## Decisions

<!-- Newest first. Each starts with its title in bold and its version in parentheses, and says what the choice was, what it was chosen over, and who chose it. -->

- **<!-- fill: the decision -->** ({version}). <!-- fill: what, over what, why, and whose call -->

## Open items

Candidates for {next}, from {version}'s work:

- <!-- fill: each FAIL with its proposed fix, each gap a finding left, each workcenter gap -->

On the bench and elsewhere:

- <!-- fill: each check only a built board, a bench test or the owner can close -->
