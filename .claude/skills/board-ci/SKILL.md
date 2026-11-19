---
name: Board CI
description: Gives a board repository a check on every pull request - `workcenter gates` on each project folder, the gates table in the job's summary, a red check on a red gate - with 1 workflow file that calls the workcenter's reusable workflow board-gates.yml.
---

# Board CI

A board repository gets `workcenter gates` on every pull request from 1
small workflow file. The file calls the workcenter's reusable workflow
`.github/workflows/board-gates.yml`. Each project folder is 1 job. The
job's check is the gates' verdict: GREEN is green; RED and SKIPPED are
red. The job's summary holds the gates table, the same table
`workcenter gates --report` writes into `docs/gates.md`, and says where the
gates ran. Nothing is posted to the pull request.

## When

- A board repository has no CI, or its CI does not run the gates.
- A board repository's CI installs the workcenter by hand and runs
  `workcenter gates` in a loop: 1 call replaces those steps.

## The caller

Save this as `.github/workflows/gates.yml` in the board repository. Change
`projects` to the folders that hold a `.kicad_pro`.

```yaml
name: Gates
on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
  packages: read
jobs:
  gates:
    uses: ThyFriendlyFox/via/.github/workflows/board-gates.yml@main
    with:
      projects: '["v0.16", "v0.16/display"]'
      strict: true
```

`permissions` must give `packages: read`: the called job asks for it, and
GitHub refuses a called job more than its caller gives.

## Inputs

| Input | Default | What it does |
|---|---|---|
| `projects` | `["."]` | The project folders, as a JSON list. 1 job each. |
| `strict` | `false` | `true` passes `--strict`: a warning fails the gate. |
| `workcenter-repository` | `ThyFriendlyFox/via` | The workcenter to run. Its owner also owns the image. |
| `workcenter-ref` | `main` | The workcenter's branch, tag or commit. A tag such as `v0.1.0` holds the gates still while `main` moves. |
| `use-image` | `true` | `false` never asks the registry: always install.sh. |
| `apt-ubuntu-archive` | `true` | `false` leaves the runner's apt mirror as it is on the install path. |

## Where the gates run

1. The job names the image of the toolchain files at `workcenter-ref`:
   `ghcr.io/<owner>/via:tc-<16 digits>` (`tools/image.py tag`).
2. It logs in to ghcr.io with the job's token and pulls that image. Pulled:
   the gates run inside it, as the runner's user, with the workcenter's
   checkout at `.via`.
3. Not pulled: the install path. `tools/ci/apt_archive.sh` turns apt to
   Ubuntu's own archive, then `install.sh` installs the toolchain with CI's
   2 apt bounds (120 s per index update, 570 s for the download). CI's own
   install path does the same: the runner's regional mirror crawled to the
   download's bound in 2 CI runs, and Ubuntu's own archive did not
   (`ee-agent-kit/CI.md`, "Toolchain step"). The install path takes about
   2 to 10 minutes before the gates start.

A package is private until its owner makes it public
(`ee-agent-kit/CI.md`, "The container image: what the owner does once",
step 3). While it is private, a board repository's token is refused it,
and every run takes the install path. The owner can also add the board
repository under the package's "Manage Actions access". The step `Where
the gates run` says which path a run took, and why.

## Steps

1. Write the caller above into the board repository, with its own
   `projects`. Commit it on a branch and open a pull request.
2. Open the run of the job `gates / gates <project>` and read the step
   `Where the gates run`. Its last line is 1 of:

   | The line says | It means |
   |---|---|
   | `where: image: the registry gave ghcr.io/...` | The gates run in the image. Nothing is installed. |
   | `where: install: the registry gave no ghcr.io/...: <docker's last line>` | The image could not be pulled: `denied` or `unauthorized` while the package is private, `manifest unknown` when no image of that toolchain was built. The install path runs. |
   | `where: install: the input use-image is false` | The caller asked for the install path. |

3. Read the step `workcenter gates`. Its last line is the verdict:
   - `GREEN: <board>`: the check is green.
   - `RED: <board>`: the check is red. Fix the board with the
     `board-gates` skill, push, and the check runs again.
   - `SKIPPED (...)`: an engine was absent, and the check is red. Read
     the install step's log for the engine it names.
4. Open the run's summary page. Each project has its gates table, its
   decks when it has `sim/`, and a `Where:` line. A project with no table
   says `No gates table for <project>`: the gates step stopped before the
   gates ran; its log says why.
5. Make the check required: the repository's Settings, Branches, the rule
   for `main`, Require status checks, `gates / gates <project>` for each
   project.

## What the workflow does not do

- It posts no comment to the pull request.
- It does not regenerate a project from its `design.py` and compare the
  files, run `workcenter verify`, or build firmware. A board repository
  that needs these keeps them as jobs of its own beside the call.
- It uploads no file. The gates write `<project>/build/` on the runner.

## Proof

This repository calls the workflow on its fixture
`tests/boards/pass-rc-divider` with `strict: true`, from
`.github/workflows/board-fixture.yml`, with the workcenter at the commit
under test. `tests/test_board_gates_workflow.py` runs each step's text
with stand-ins for `docker`, `sudo` and `id`, walks the whole job on both
paths, and runs the gates step on this machine's toolchain on
`pass-rc-divider` (GREEN with `--strict`) and `fail-drc-clearance` (RED at
DRC).
