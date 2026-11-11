# EE Workcenter

A workcenter is a pre-packaged environment an agent steps into to do one
kind of work well. This one does electronics: it turns a KiCad 10
project into fabrication outputs that passed every gate.

- **Engines:** KiCad 10 (`kicad-cli`), ngspice, FreeRouting.
- **Gates:** ERC, DRC, SIM, EXPORT, in that order. A board is done when
  `workcenter gates <project>` prints GREEN.
- **Design as code:** `workcenter design design.py --route` builds a
  schematic and a routed board from a Python file that names parts from
  the KiCad libraries. No GUI at any step.
- **Corners:** the SIM gate runs every deck at each temperature and part
  tolerance the project names, at the worst case of each bound, and at
  Monte Carlo draws. A bound holds at every corner or it does not hold.
- **Frequency plan:** the SIM gate holds every switching frequency and its
  harmonics against every resonance a deck measured.
- **The next step:** `workcenter next <project>` names the one step that is
  left, its command, and the fix for the first failure. A person or an
  agent of any size follows the same path.
- **Skills:** procedures for each kind of step, as Markdown files.
- **Fixture boards:** the tests. Each passes everything or fails 1 named
  gate.

## Quick start

```sh
sudo ./install.sh                 # Ubuntu 24.04; KiCad 10 PPA, ngspice, Java 21, FreeRouting, venv
workcenter doctor                 # every engine present?
workcenter gates tests/boards/pass-rc-divider        # GREEN
workcenter gates tests/boards/fail-drc-clearance     # red at DRC, on purpose
workcenter sim tests/boards/fail-sim-corner          # red at 85 C and at a 5 % corner, on purpose
workcenter sim tests/boards/fail-freq-overlap        # red on a harmonic that sits on a resonance
workcenter next tests/boards/pass-rc-divider         # the one next step
```

Output goes to `<project>/build/`: `erc.json`, `drc.json`, `sim/`,
`fab/` (gerbers, drill, BOM, schematic PDF), `gates.json`.

## Commands

`workcenter <command> --help` says what each writes and where.
`ee-agent-kit/docs/CONFIGURATION.md` has every flag.

| Command | What |
|---|---|
| `doctor` | Report each engine's status. |
| `next` | Name the one next step for a project. |
| `design` | Build a design file into a KiCad project; `--route` routes it; `--check` compares. |
| `erc`, `drc`, `sim`, `export` | One gate. |
| `gates` | The 4 gates in order; the last line is the verdict. |
| `verify` | Check a verification package against a fresh run; say whether the requirements are met. |
| `autoroute` | Route a hand-drawn board's DSN with FreeRouting. |
| `inspect` | Read a routed board: `map`, `list`, `probe`, `net`, `islands`, `resistance`, `crossed`. |
| `placement` | Run a kistack placement check on a board. |
| `render`, `pictures` | Images of the schematic, the board, every layer; turning GIFs; assembly scenes. |
| `procure`, `costs` | Price a board's parts; price every board of every version. |
| `sources`, `fetch`, `curve` | Check each part's datasheet and model; fetch one; read a curve from a PDF. |
| `mutate` | Prove a firmware's host tests can fail. |
| `ci` | Replay a repository's GitHub workflow here. |
| `docs`, `version`, `diagram` | A version's contents page and datasheets; a new version folder; a block diagram. |

## As a Claude Code cloud environment

The environment carries the software; the board repository carries the
board. Create an environment whose setup script is the 3 lines in
`environment/setup.sh`, with the network hosts from
`environment/README.md`. Open any board repository in it. Attach this
repository as a second repository when its skills should load.

## With another agent host

`AGENTS.md` at the root is the entry for a host that does not read
`CLAUDE.md`; the 2 files are the same text. Every procedure is a Markdown
file under `.claude/skills/`, and every check is a command: `workcenter
next <project>` gives the step, `make verify` the repository's health.

## As a Docker image

`docker build -t ee-workcenter .` on the official `kicad/kicad:10.0`
base. `release.yml` publishes it to GHCR on every tag.

## Repository map

| Path | What |
|---|---|
| `install.sh` | The single source of the toolchain. |
| `tools/workcenter` | The CLI and the gates. Standard library only. |
| `tools/kicadgen.py` | Design a board in Python from the KiCad libraries; writes the KiCad project and routes it headless. |
| `tools/simcorners.py`, `tools/freqplan.py` | The corners a deck runs at; the frequency plan. Read by the SIM gate. |
| `tools/guide.py` | `workcenter next`: the one next step and the fix for each kind of failure. |
| `tools/inspect_board.py`, `tools/stretch.py` | Read a routed board with KiCad's geometry; grow a design at a cut. |
| `tools/doctools.py`, `tools/scene.py`, `tools/wrlgen.py` | Document commands; assembly scenes; 3D bodies. |
| `tools/pdfcurve.py`, `tools/kistack_board.py` | A PDF page's vector paths; the board reader kistack's checks run on. |
| `tools/hooks/` | Claude Code hooks: no `cd` in a command, no test written by a script. |
| `WORKCENTER.md` | The contract a project gets from this workcenter. |
| `AGENTS.md`, `CLAUDE.md` | Where an agent starts. The same text. |
| `.claude/skills/` | `attached-repos`, `autoroute`, `blog-post`, `board-design`, `board-gates`, `kistack`, `procurement`, `simulate`, `verification`. |
| `templates/` | A version's README and gates report, `corners.json`, `frequency-plan.json`, the verification package. |
| `rules/` | Fabrication houses' limits as KiCad design rules. |
| `tests/boards/` | Fixture boards and what each proves. |
| `third_party/kistack/` | The vendored kistack skills. |
| `environment/` | Cloud environment setup script and hosts. |
| `ee-agent-kit/` | How work on this repository is run. Start at `ee-agent-kit/ROUTING.md`. |

## Working on this repository

`make verify` must be green before any push. `ee-agent-kit/AGENTS.md` is
binding; `ee-agent-kit/ROADMAP.md` decides what gets built.

MIT licensed. KiCad, ngspice, and FreeRouting keep their own licenses.
