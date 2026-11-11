# Via

[![CI](https://github.com/ThyFriendlyFox/via/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/ThyFriendlyFox/via/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-1e49b7)](LICENSE)

Via is the EE Workcenter. A workcenter is a pre-packaged environment an
agent steps into to do one kind of work well. This one does electronics:
it turns a KiCad 10 project into fabrication outputs that passed every gate.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="site/og-dark.png">
  <img alt="Via, an electronics workcenter for agents, beside a run of its 4 gates on a fixture board that ends in GREEN" src="site/og.png">
</picture>

2 runs on fixture boards, as the terminal printed them. The second board
has a clearance error on purpose.

```text
$ workcenter gates tests/boards/pass-rc-divider
PASS   erc        0 errors, 0 warnings  [0.27s]
PASS   drc        0 errors, 0 warnings (0 unconnected, 0 parity)  [0.59s]
PASS   sim        1 decks, 46 corner runs, 0 failures  [0.16s]
PASS   export     4/4 outputs, 22 gerber files  [1.21s]
GREEN: rc_divider  report /home/user/via/tests/boards/pass-rc-divider/build/gates.json

$ workcenter gates tests/boards/fail-drc-clearance
PASS   erc        0 errors, 0 warnings  [0.27s]
FAIL   drc        1 errors, 1 warnings (0 unconnected, 0 parity)  [0.63s]
       - error: clearance: Clearance violation ( clearance 0.2000 mm; actual 0.0500 mm)
       - warning: track_dangling: Track has unconnected end
RED: rc_divider  report /home/user/via/tests/boards/fail-drc-clearance/build/gates.json
```

- **Engines:** KiCad 10 (`kicad-cli`), ngspice, FreeRouting.
- **Gates:** ERC, DRC, SIM, EXPORT, in that order. A board is done when
  `workcenter gates <project>` prints GREEN.
- **Design as code:** `workcenter design design.py --route` builds a
  schematic and a routed board from a Python file that names parts from
  the KiCad libraries. No GUI at any step.
- **A schematic that simulates:** the design file says how each part
  simulates (`d.sim`, `d.no_sim`), and the schematic KiCad opens exports a
  netlist ngspice runs. A pin map KiCad would complete by position is
  refused first.
- **Corners:** the SIM gate runs every deck at each temperature the
  project names and with each part at both ends of its tolerance. It runs
  every combination of those ends where they are few, and Monte Carlo
  draws. A bound holds at every corner or it does not hold.
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

## The website

`site/` is the project's website: 1 static page with real runs of the
commands. `python3 -m http.server 8000 --directory site` serves it at
http://localhost:8000. Vercel deploys it: every push to `main` deploys
production, and every other branch gets a preview. `site/README.md` has
the commands, the files and how the images are drawn.

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
| `templates/` | A first design file, a version's README and gates report, `corners.json`, `frequency-plan.json`, the verification package. |
| `rules/` | Fabrication houses' limits as KiCad design rules. |
| `tests/boards/` | Fixture boards and what each proves. |
| `third_party/kistack/` | The vendored kistack skills. |
| `environment/` | Cloud environment setup script and hosts. |
| `site/` | The website: 1 static page, its stylesheet, the Open Graph image. |
| `ee-agent-kit/` | How work on this repository is run. Start at `ee-agent-kit/ROUTING.md`. |

## Working on this repository

`make verify` must be green before any push. `ee-agent-kit/AGENTS.md` is
binding; `ee-agent-kit/ROADMAP.md` decides what gets built.
`ee-agent-kit/CONTRIBUTING.md` has the rules for a pull request.
`ee-agent-kit/SECURITY.md` says how to report a vulnerability.

## Where things stand

`ee-agent-kit/STATUS.md` has each area's state with its evidence. In
short: the gates, the corners, the frequency plan and `workcenter next`
run on the fixture boards in `make verify`. Via has no release yet. The
cloud setup script and the Docker build have not run yet.

## License

MIT; see [LICENSE](LICENSE). KiCad, ngspice, and FreeRouting keep their
own licenses. Inter, the website's font, is under the SIL Open Font
License: [site/fonts/LICENSE](site/fonts/LICENSE).
