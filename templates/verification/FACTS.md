# Facts: {board} {version}, {task}

<!-- The one file that holds the facts of a round of parallel work on a
     verification package (the verification skill's "Helpers"). BRIEF.md
     points here and copies nothing from it (M98). Keep it beside BRIEF.md in
     the session's scratchpad, never in the project. Replace each {name} as
     in BRIEF.md, fill each "fill" comment, and delete this comment. -->

Each row gives a fact, its value, and its home: the file in the project
that holds it (a line of `design.py`, a firmware constant, a requirement's
row, a datasheet's table or figure with its revision) or the run that
measured it. Every home is an absolute path to a file that exists now
(M96). Where this file and the home differ, the home wins: tell the lead.

A behaviour (a part that takes no part in an edge, a current that stays
small) goes into this file only with the measure or the waveform that
shows it (M95). A deck's numbers are not copied here: they come from the
runs at the end.

## Changes during the work

Newest first. When a fact changes, the lead changes its home first, then
its row below, then adds a line here and tells every helper which row
moved (M98).

| When | Row | Was | Now | Why |
|---|---|---|---|---|

## What changed in {version}

One row per change against {previous}, in the order the version's README
gives them.

| # | Fact | Value | Home |
|---|---|---|---|
| 1 | <!-- fill: the change, for example "F1, the system branch's fuse" --> | <!-- fill: for example "1 A; 0.130 Ohm at most" --> | <!-- fill: an absolute path, and the line, the constant, the row or the table --> |

## Parts and values

| Ref | Value | Home |
|---|---|---|
| <!-- fill --> | | |

## Firmware constants

| Constant | Value | Home |
|---|---|---|
| <!-- fill --> | | |

## Requirements

The requirements changed this round. A restated or new requirement names
"the owner's decision of <date>" in its Source; a withdrawn one is in the
Withdrawn table. Their home is
`{repo}/{version}/verification/requirements/README.md`.

| ID | Change | Decision |
|---|---|---|
| <!-- fill: new, restated or withdrawn --> | | |

## Datasheets

Each document a helper cites, at the path where it is now.

| Part | Document and revision | File |
|---|---|---|
| <!-- fill --> | | |

## Runs

The lead's fresh runs. A helper runs its own before it quotes a number.

| Run | Command | File |
|---|---|---|
| every deck | `workcenter --json sim {repo}/{version} --out {scratch}/sim > {scratch}/sim.json` | `{scratch}/sim.json` |
