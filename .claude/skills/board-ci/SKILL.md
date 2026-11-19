---
name: Board CI
description: Gives a board repository a check on every pull request - `workcenter gates` on each project folder, the gates table in the job's summary, a red check on a red gate - with 1 workflow file that calls Via's reusable workflow board-gates.yml.
---

# Board CI

A board repository gets `workcenter gates` on every pull request from 1
small workflow file. The file calls Via's reusable workflow
`.github/workflows/board-gates.yml`. Each project folder is 1 job. The
job's check is the gates' verdict: GREEN is green; RED and SKIPPED are
red. A GREEN with ERC, DRC or EXPORT at skip is red: no board was there to
judge. The job's summary holds the gates table, the same table
`workcenter gates --report` writes into `docs/gates.md`, and says where the
gates ran. Nothing is posted to the pull request.

## When

- A board repository has no CI, or its CI does not run the gates.
- A board repository's CI installs Via by hand and runs
  `workcenter gates` in a loop: 1 call replaces those steps.

## The caller

Save this as `.github/workflows/gates.yml` in the board repository. Change
`projects` to the folders that hold a `.kicad_pro`. Here `v1` is a board
gated without `--strict`, and `v1/display` a board gated with it. Replace
every `<sha>` with 1 full commit SHA of Via's `main` that holds
`.github/workflows/board-gates.yml`.

```yaml
name: Gates
on:
  pull_request:
  push:
    branches: [main]
  workflow_dispatch:
permissions:
  contents: read
jobs:
  gates:
    uses: ThyFriendlyFox/via/.github/workflows/board-gates.yml@<sha>
    with:
      projects: '["v1"]'
      workcenter-ref: <sha>
  gates-strict:
    uses: ThyFriendlyFox/via/.github/workflows/board-gates.yml@<sha>
    with:
      projects: '["v1/display"]'
      strict: true
      workcenter-ref: <sha>
```

Pin the same SHA in both places. The `uses:` ref picks the workflow's
text; `workcenter-ref` picks the tools it runs. The 2 do not follow each
other: a `uses:` line pinned to a commit still runs the tools of `main`
when `workcenter-ref` is left out. `main` moves, and GitHub's hardening
guide pins a third party's workflow to a full commit SHA. To take a newer
Via, change both SHAs in 1 commit.

`strict` holds for every project of 1 call. Gate each project as its own
contract says: the projects gated with `--strict` go in 1 call with
`strict: true`, the others in a second call. 1 call is enough when all of
them are gated the same way.

`permissions` gives `contents: read` alone. The image is public, so the
job pulls it with no login and holds no token of the job.

## Inputs

| Input | Default | What it does |
|---|---|---|
| `projects` | `["."]` | The project folders, as a JSON list. 1 job each. |
| `strict` | `false` | `true` passes `--strict`: a warning fails the gate. |
| `workcenter-repository` | `ThyFriendlyFox/via` | The repository of Via to run. Its owner also owns the image. |
| `workcenter-ref` | `main` | The commit, branch or tag of Via whose tools run. It does not follow the `uses:` ref: pass the same SHA. |
| `use-image` | `true` | `false` never asks the registry: always install.sh. |
| `apt-ubuntu-archive` | `true` | `false` leaves the runner's apt mirror as it is on the install path. |

## Where the gates run

1. The job names the image of the toolchain files at `workcenter-ref`:
   `ghcr.io/<owner>/via:tc-<16 digits>` (`tools/image.py tag`).
2. It pulls that image, with no login. Pulled: the gates run inside it,
   as the runner's user, with Via's checkout at `.via`.
3. Not pulled: the install path. `tools/ci/apt_archive.sh` turns apt to
   Ubuntu's own archive, then `install.sh` installs the toolchain with CI's
   2 apt bounds (120 s per index update, 570 s for the download). CI's own
   install path does the same: the runner's regional mirror crawled to the
   download's bound in 2 CI runs, and Ubuntu's own archive did not
   (`ee-agent-kit/CI.md`, "Toolchain step"). CI's install step took
   1 min 29 s on Ubuntu's own archive in CI run 44444183056 (the same
   section). No run of this workflow has timed it yet.

The image path is the normal path. The package `ghcr.io/thyfriendlyfox/via`
is public: on 2026-11-19 the registry gave its tag list and the manifest
of `tc-ad6cb1705e532dcc`, the tag of `main`'s toolchain, to a pull with no
login. The install path is taken when the registry holds no image of the
toolchain at `workcenter-ref` (a commit whose toolchain files changed and
whose image was not pushed), or when `use-image` is `false`. The step
`Where the gates run` says which path a run took, and why.

What only a run on GitHub shows of the image path: that `docker run
--user` with the runner's user id and group can write the board's
`build/` folder and the report in the runner's temp folder (`--user`);
that `image.py check` passes on Via's checkout inside the image
(`image.py check`); and that Via and KiCad run with no home of
that user in the image, where `HOME` is not the runner's home (`HOME`).
The same `docker run --user` runs `workcenter gates .` in the image's own
workflow, `.github/workflows/image.yml`, step `The gates on a fixture, as
the runner's user`.

## Steps

1. Write the caller above into the board repository, with its own
   `projects`. Commit it on a branch and open a pull request.
2. Open the run of the job `gates / gates <project>` and read the step
   `Where the gates run`. Its last line is 1 of:

   | The line says | It means |
   |---|---|
   | `where: image: the registry gave ghcr.io/...` | The gates run in the image. Nothing is installed. |
   | `where: install: the registry gave no ghcr.io/...: <docker's last line>` | The image could not be pulled: `manifest unknown` when no image of that toolchain was built, `denied` or `unauthorized` when the package is not public. The install path runs. |
   | `where: install: the input use-image is false` | The caller asked for the install path. |

3. Read the step `workcenter gates`. Its last line is the verdict:
   - `GREEN: <board>`: the check is green.
   - `RED: <board>`: the check is red. Fix the board with the
     `board-gates` skill, push, and the check runs again.
   - `SKIPPED (...)`: an engine was absent, and the check is red. Read
     the install step's log for the engine it names.
   - `RED: <project>: DRC not judged: no board in project; ...`: see
     "A board that is not there is red" below. The check is red.
   - `RED: <project>: the gates exited 0, but their report holds no GREEN
     line: nothing was judged`: exit code 0 alone is not green. The check
     is red.
   - `RED: the project name ... is not a folder the gates can be given`:
     the name in `projects` is empty or holds a control character. The
     project's name goes to the gates after `--`, so a folder named like an
     option (`--help`) is gated as a folder.
4. Open the run's summary page. Each project has its gates table, its
   decks when it has `sim/`, and a `Where:` line. A project with no table
   says `No gates table for <project>`: the gates step stopped before the
   gates ran; its log says why. A check that is red though its table says
   GREEN has the line `This check is red: ...` under the table, with 1
   line per gate that judged nothing.
5. Make the check required: the repository's Settings, Branches, the rule
   for `main`, Require status checks. Each call's checks carry its job's
   name: `gates / gates <project>` for each project of the call `gates`,
   and `gates-strict / gates <project>` for each project of the call
   `gates-strict`.

## A board that is not there is red

`workcenter gates` says GREEN when every gate that had something to run
passed, and names the others: a folder whose `.kicad_pcb` was deleted is
`GREEN (nothing to run for: drc, export)`. That board was not judged. So
after a GREEN the gates step reads the table, and for each of ERC, DRC and
EXPORT at `skip` prints 1 line and ends red:

```
RED: v1: DRC not judged: no board in project; this check is green only when ERC, DRC and EXPORT ran (...)
```

This holds with and without `strict`. SIM at `skip` (`no sim/*.cir in
project`) stays green: the board was judged, and the summary's table shows
the row.

## The pull request's own files run

The check runs code from the pull request, so a fork's check is only as
trustworthy as its diff. A fork's green check proves nothing until a
maintainer has read the whole diff. These files of a board repository can
run code during the gates:

- `.github/workflows/`: on a pull request GitHub runs the workflow files of
  the pull request's head, so a pull request can change the caller itself,
  and with it every step and input.
- `sim/*.cir`: ngspice runs a deck's `shell` lines with `/bin/sh` during
  SIM; `source` runs the commands of another file; `codemodel` and
  `pre_osdi` load a shared library, which is machine code.
- Every file a deck reads in with `.include` or `.lib`, wherever it is in
  the repository: its lines are the deck's lines.
- `sim/.spiceinit`: ngspice reads it before the deck, and the gates copy
  it into each run folder. The gates
  cannot start ngspice without start-up files: they write a `.spiceinit`
  of their own that sets a model's mode, and a deck folder's own
  `.spiceinit` is a documented setting (`WORKCENTER.md`).

What the gates refuse or never import:

- `panel.json`: a KiKit preset can name Python (a section's `code`, a
  text's `plugin`, `post.script`). The gates refuse such a preset on 1
  line, red, before KiKit reads it.
- Python modules in the repository, such as a `kikit/` folder, `pcbnew.py`
  or `sitecustomize.py`: a module of the board's folder or of the working
  directory is never imported. Via starts its probes (`python -c`) and
  KiKit isolated (`-I`); its other Python runs are scripts of `.via/tools`,
  whose own folder is the one on the import path.
- The KiCad files (`.kicad_pro`, `.kicad_sch`, `.kicad_pcb`, the library
  tables, a `.kicad_dru`), `parts.csv` and the `sim/` JSON files are read
  as data: Via starts no code they name.

In the image the gates run with `--network none`, with `.via` mounted
read-only, and with only `board-gates/` of the runner's temp folder
mounted, where the report goes. On the install path they run on the runner
as its user, who has sudo, and nothing holds them.

## What the workflow does not do

- It posts no comment to the pull request.
- It does not regenerate a project from its `design.py` and compare the
  files, run `workcenter verify`, or build firmware. A board repository
  that needs these keeps them as jobs of its own beside the call.
- It uploads no file. The gates write `<project>/build/` on the runner.

## Proof

This repository calls the workflow on its fixture
`tests/boards/pass-rc-divider` with `strict: true`, from
`.github/workflows/board-fixture.yml`, with Via at the commit
under test. `tests/test_board_gates_workflow.py` runs each step's text
with stand-ins for `docker`, `sudo` and `id`, walks the whole job on both
paths, and runs the gates step on this machine's toolchain on
`pass-rc-divider` (GREEN with `--strict`), `fail-drc-clearance` (RED at
DRC) and `pass-rc-divider` with its `.kicad_pcb` deleted (red: DRC and
EXPORT not judged). The fixture's workflow runs when either workflow, the
fixture, `tools/`, `install.sh`, `requirements.txt` or `Dockerfile`
changes.
