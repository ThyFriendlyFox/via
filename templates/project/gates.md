# Gates report — {project} {version}

<!-- The layout of a version's gates report, `docs/gates.md` (PROCESSES.md
     P22 and P23). `workcenter gates <project> --report docs/gates.md` writes
     what sits between a pair of marker comments: a board's gates table
     between `workcenter gates {name}` and `/workcenter gates {name}`, its
     decks between `workcenter decks {name}` and `/workcenter decks {name}`,
     where {name} is the board's project name (its .kicad_pro without the
     suffix). It leaves every line outside the markers as it is: the prose
     is written by hand, from the reports the run leaves in build/. Run it once
     per board of the version. Replace each {name}; fill each "fill"
     comment; delete this comment. -->

<!-- fill: one paragraph: the commands that made this report (`workcenter gates .`, each nested board's, with `--strict` where it was used), the date, the KiCad, ngspice and FreeRouting versions, where the raw results are (`gates.json`), whether every board is GREEN, and each warning `--strict` would fail on with the section that explains it. -->

## {board}

<!-- workcenter gates {name} -->
| Gate | Status | Summary |
|---|---|---|
| ERC | <!-- fill --> | |
| DRC | | |
| SIM | | |
| EXPORT | | |
<!-- /workcenter gates {name} -->

<!-- One section like the one above per board of the version, in the order the README names them. -->

## Simulation

<!-- fill: what the decks check as a whole: the bounds in `sim/<deck>.expect.json`, the requirement each bound carries (`"req"`), and the verification package that explains each deck (`workcenter verify .`). -->

<!-- workcenter decks {name} -->
| Deck | Bounds | Failures | Warnings |
|---|---|---|---|
| <!-- fill --> | | | |
<!-- /workcenter decks {name} -->

<!-- fill: one line per deck: the circuit question it answers, and what changed in it in this version. Then each warning: the bound, the value, the datasheet's limit, and what the design trusts there instead. -->

## Schematics

<!-- fill: ERC errors and warnings, the DRC's parity check, and how the schematics are drawn (P24). -->

## DRC warnings

<!-- fill: each warning with its position and why it is accepted, or "None". Then the boards' outlines and the rules they are checked against: their own clearances and the fab's limits (`rules/`), the via and the smallest hole. -->

## Pull check

<!-- fill: whether `check_pulls` is on (P16 step 5), the inputs it names, and what holds each one. -->

## Fabrication outputs

<!-- fill: the files in `build/fab/` for each board after `workcenter export`, and the stackup each board file carries. -->

## Routing

<!-- fill: per board, what `design.py` routes by hand and why, what the router routed (segments, vias, rounds), the totals on the board, and what the router does not know (P11). -->
