# Changelog

All notable changes to EE Workcenter are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/) · Versioning: [SemVer](https://semver.org/).

## [Unreleased]
### Changed
- The router keeps each layer's hole clearance: `kicadgen` reads the fab's layer rules (`Design.hole_clearances()`, Sierra's 13 mil inner drill to copper) and writes every via and drilled pad into the DSN with its copper grown by that rule on the layers where it exceeds the copper clearance (a 0.6/0.25 mm via is 0.6104 mm on In2 at 0.15 mm). FreeRouting 1.9.0 ignores a `via_wire` clearance in the DSN's structure and applies one in a net class to that class's own pairs only, both measured on a fixture. Hand vias, the via placers and island stitching hold the same rule (M79, P17).
- `workcenter design` ends a red run (exit 1) with a line that names each failure and says the files are written for inspection only and a CI regenerate check fails on that exit code; `--json` adds `red` (M85).
- `install.sh`: apt's progress lines reach the log as they happen (the filter flushes per line and matches apt's `Get:<n>` lines, which it never did), and a silent mirror times out after 60 s and is retried (M86).
- P4 reads a route's verdict from `workcenter design`'s exit code, which is 1 on a refused hand via although every file is written; P14 runs a board repository's own CI checks locally before the push (M85).
- `workcenter sources` refuses a `sources.csv` row with more fields than its header (an unquoted comma in a note) instead of dropping the extra fields (M76).
- P8 names `pgrep -f` in a wait loop beside `pkill -f`; P9 writes a rewritten file to a new file first and reads a script's ranges from the file it edits; the verification skill's ngspice traps add `let`'s missing SI suffixes and `meas` results living in their own plot (M74 to M80).
- P28 and the verification skill: a limit computed from parts' values carries their tolerances; a fitted model's value away from the datasheet's rows is no maximum; a stand-in never clamps at an absolute maximum, and every output driving a capacitor has its peak current bounded; citations in code comments come from the document's text too (M81 to M84).

### Added
- `workcenter design --route --seed <board>`: a previous routed board's router tracks and vias go to FreeRouting held (`shove_fixed`), so the paths that still fit stay and only the rest are routed; seed copper that hangs from nothing goes in unfixed, for the router to reuse or remove. Hand copper, stitching vias, lost nets and arcs are left out, and copper that now meets another net's pad or copper, a keepout or the board edge is dropped, each counted on a `seed:` line with how many seed tracks the new route kept (`kicadgen.board_copper()`, `Design.seed_wiring()`, M89).
- `workcenter design` prints each via it drops through a pour's island after routing as a `stitch:` line: the net, the island's layer and pads, the layer the via reaches (`Design.stitches`; `--json` `stitches`).
- `workcenter verify <project>`: checks a verification package (`verification/`, P28): the files it holds, a requirements table with a source, method and inspection clause on every row, a writeup with every section for each circuit and for every deck, links that lead somewhere, a traceability row for every requirement; runs the SIM gate and compares every number quoted beside a `deck.meas` with the run (to half a unit of the quoted digit, SI prefixes understood) and recomputes each traceability check against its verdict. `--strict` fails on a FAIL or OPEN requirement; `--init` writes the skeleton from `templates/verification/`; `--package` names another folder. Writes `build/verify.json`.
- The `verification` skill and P28: conditions, sourced requirements judged at the corners, one cited nodal analysis per deck, models fitted to datasheets where the maker publishes none, a standards map (DO-160G, MIL-STD-461G, MIL-STD-810H, IEC 61000-4-2, USB, UM10204, EEE-INST-002 derating) with the editions read.
- The SIM gate takes a model under the deck's own folder (`sim/models/`) as the project's own: no library row is asked for it. An expect bound may name its requirement (`"req"`).
- `workcenter sources <project> --parts FILE`: every part on the schematic against the nearest `library/sources.csv` (datasheet, SPICE model and STEP rows: URL, file, revision as printed, date, `.SUBCKT`, ngspice fixes, SHA256): a datasheet for each part, a model or a note for each U, Q and D, each file present, unchanged and printing its revision, each model loading in ngspice with its sub-models, a model older than its datasheet named. `--fetch` reads each URL again under the workcenter's own name and records a refusal. P27, the `simulate` skill.
- The SIM gate runs a deck that includes a listed vendor model from `build/sim/run/<deck>/`, with the model translated where its row says (`res-model` folds PSpice RES models into their resistors, `tolerance` drops LOT and DEV, `ps` or `lt` mode in a `.spiceinit`); a model changed since its row fails the deck. An expect bound with `warn` holds a model to its datasheet and fails only `--strict`.
- The pull-resistor check: `kicadgen.Design.undefined_inputs()` finds every net with a gate, logic input, switch or I2C line that no output drives and no resistor holds at a rail (or a gate at its own source). `workcenter design` prints each as a `pull:` line and fails on them when the design sets `check_pulls`; `defined_nets` names a net held elsewhere with the reason. P16 step 5.
- Fabrication house rule sets in `rules/` (KiCad `.kicad_dru`), the first Sierra Circuits' Web PCB (`sierra-circuits-web`: 4 mil trace and gap, 6 mil hole and ring, 13 mil inner drill to copper, 5 mil legend text). `workcenter drc --fab NAME` and `gates --fab NAME` check a project against one on a copy; `kicadgen.Design.fab` writes it into the project as `<name>.kicad_dru` and raises the board's own minimums to its board-wide ones, so the via check refuses a via the fab would. Fixture `fail-fab-sierra`.
- kistack (American Embedded's KiCad agent skills) vendored at `641ade9` in `third_party/kistack/`, without its logo; the `kistack` skill names which of its skills to read at which step and where this workcenter's rules override it (no getting round bot protection, the design file is the source of truth, FreeRouting routes, the gates decide done).
- `workcenter placement <check> <board> [args]`: kistack's layout-placement checks (`pin_sides`, `placement_audit`, `route_check`, `local_search`, `group_search`) on a board file, headless. `tools/kistack_board.py` answers kistack's IPC reader from the file with pcbnew, since KiCad 10.0 has no headless API server. `move` is refused.
- The venv gets shapely, numpy and pygerber (kistack's placement checks and Gerber review).
- `kicadgen`: project symbol libraries (`Design.symbol_dirs`, a `sym-lib-table` in the generated project, `pins --lib NAME=FILE`), for a part the KiCad library lacks or draws only in several units, such as a dual common-drain MOSFET.
- `workcenter procure <project> --parts FILE --boards 1,10`: prices the schematic's BOM from parts files and writes `procure/bom.csv`, `parts.csv` and `parts.md` with the cheapest order per line and totals per supplier; fails on a line with no part or no price, `--strict` also on a line short of stock or a price older than 90 days. The `procurement` skill and P25 say how a parts file is filled (M54, M55).
- `kicadgen`: wired schematics (`Design.sch_wires`): a grid router (`SchRouter`) draws each net's wires round the parts, with junctions at tees, power symbols pointing away from their pins, and each net's name on its wire; `sch_rot` turns a symbol, `sch_label_nets` keeps labels for chosen nets, `sheet` picks the paper. Off by default, so existing schematics regenerate byte for byte (M51, P24).
- `workcenter render` names every part the 3D views draw without a body; `render --strict` fails on one (M52).
- `wrlgen`: `leadless` (QFN, DFN, SON) and `gullwing` (SOT-23, SOT-523, SC-70) bodies for packages whose library body KiCad does not ship.
- `tools/kicadgen.py`: design a KiCad 10 schematic and board in Python from the installed libraries; writes project, schematic, board, Specctra DSN; merges a routed session.
- `workcenter design <design.py> [--route]`: build a design file, optionally route it headless with FreeRouting.
- `workcenter render <project>`: schematic, board top and bottom, 3D top and isometric images.
- `board-design` skill.
- `install.sh` installs librsvg (`rsvg-convert`) for PNG output.
- `install.sh`, gates ERC, DRC, SIM, EXPORT, fixture boards, skills, kit, CI, cloud environment setup script, Dockerfile (2026-10-22).
- `kicadgen`: parts on the bottom face (`pcb_layer`), free silkscreen text (`d.text`), design-rule overrides (`d.rules`), per-part zone connection (`zone_connect`).
- `kicadgen`: copper pours (`d.zone`), filled headless on write; the router sees them as planes.
- `kicadgen`: hand-routed copper (`d.track`, `d.via`) passed to the router as fixed wiring; `stitch_pads` and `reserve_vias` for ground vias beside pads.
- `kicadgen`: after routing, pour islands are read with KiCad's `pcbnew` module and stitched with vias; `workcenter design --route --rounds N` reserves a via beside what is left and routes again.
- `install.sh` creates the venv with `--system-site-packages` so the workcenter's Python sees `pcbnew`.
- `kicadgen`: project footprint libraries (`Design.footprint_dirs`, an `fp-lib-table` in the generated project, `footprint --lib NAME=DIR`); stadium outlines (corner radius up to half the short side); circle courtyards read as centre and radius (M24).
- `tools/wrlgen.py`: `connector-510` (M7 x 0.5 internal thread), `cartridge-510`, `pouch-cell`, `display-module` presets; material transparency.
- `PROCESSES.md` P18 (firmware that drives power) with M32; `board-design` skill: ground corridors against split pours.
- `.claude/settings.json`: a PreToolUse hook (`tools/hooks/no_cd.py`) refuses a Bash command that runs `cd` (P8, M31).
- `tools/hooks/install_hooks.py`: puts the no-cd hook into a Claude Code settings file, user-wide by default, merged and idempotent; run by hand, never by `install.sh`. `workcenter doctor` reports whether the user-wide hook is there (M35).
- `kicadgen`: keep-out areas (`Design.keepout(polygon, layers, name)`, with `Design.circle(cx, cy, r)` for round ones): a KiCad rule area with no tracks or vias, a Specctra keepout for the router, and a refusal in the via check.
- `kicadgen`: `Design.corner_radius` rounds the board corners (Edge.Cuts arcs, polygon boundary in the DSN, rounded default pour, corner-aware via check); `Design.model()` attaches a 3D body to a part's footprint.
- `tools/wrlgen.py`: parametric VRML bodies in KiCad's 0.1 inch units: `usb-c-vertical`, `threaded-stud`.
- `workcenter render` adds `board-3d-bottom.png`.
- `kicadgen`: `Design.check_vias()` lists every via that hits a pad or track of another net on any layer, another via, a keep-out (by name) or the board edge; `workcenter design` prints the list before routing and exits 1 when it is not empty (M40, M41).
- `tools/hooks/no_script_test_edits.py`: a PreToolUse hook that refuses a Bash command writing under `tests/` by script (P9 step 6, M43).
- `kicadgen`: `Design.corner_radius` takes four radii (top-left, top-right, bottom-right, bottom-left), so a board can be a half circle at one end and flat at the other; `Design.thickness` sets the finished board and writes a stackup on two layers too (a 0.8 mm daughter board).
- `PROCESSES.md` P21 (moving files in a project): self-relative paths listed before the move, every README command run after it, each folder diffed against its source commit (M44).
- `kicadgen`: `Design.check_via_rules()` lists every via size (default, net class, hand via) below the board's minimum hole, via or annular ring; `workcenter design` runs it before routing and exits 1 (M46, `PROCESSES.md` P3 step 5). `Design.board_rules()` is the rule set the project file carries.
- `PROCESSES.md` P7 also covers handing a tool a rotation or an axis; the `board-design` skill writes down KiCad 10's model rotation convention (M47).
- `PROCESSES.md` P22 (versions of a project): every new feature is a new version folder, copied before the first edit (M48).
- `PROCESSES.md` P13 walks a new process through the case that caused it; P22's check allows the archive banner it asks for (M49).
- `workcenter render`: every layer with something on it, one PNG each with the outline (bottom layers seen from below), in `build/render/layers/`, and an overview sheet `layers.png`; `--views spin` writes `board-spin.gif`, the 3D board turning round (`--spin-frames`, `--spin-tilt`, `--spin-zoom`, `--spin-pivot`); `--views` picks what to draw. `install.sh` installs FFmpeg for the GIF; `workcenter doctor` reports it.
- `PROCESSES.md` P23 (pictures of a finished board version): every board's layer sheet and turning GIF, from below too when it has parts on both faces, the assembly's GIF, the framing checked on four test frames, all in the version's `docs/` and README.
- `docs/CONFIGURATION.md`: the `tools/workcenter` flag table whole again, with `--rounds` and the render flags; a test fails a PR whose flag has no row (M50, P10).
- `kicadgen`: four-layer (and any even count) boards: `Design.copper_layers` adds `In1.Cu`.. with a 1.6 mm stackup; `Design.plane_layers` gives an inner layer whole to a pour, which the router never sees; through pads and vias carry copper on every routing layer in the DSN; island stitching lands vias on any layer and keeps clear of other nets' copper on the layers a via passes.
- `docs/CONFIGURATION.md` names the FreeRouting pin that `install.sh` has carried since the 1.9.0 pin (M21).
- `ee-agent-kit/MISTAKES.md` (every mistake, its cost, its process) and `ee-agent-kit/PROCESSES.md` (binding checklists P1 to P21); `make verify` checks that each mistake names an existing process and each process has a "Done when" line.
### Changed
- `autoroute` skill: FreeRouting's result shifts with every hand track added, even far from the nets it then drops; find the culprit on a scratch copy and copy a routing run's own tracks for a net the next run drops (Last Hit v0.11).
- M53 records a sixth `cd`.
- `PROCESSES.md` P20 (swapping a part) step 3: list what the old part did besides its ratings (protection, how it was held and connected) and name the part that does each now (M56).
- `install.sh` prints apt progress and runs it non-interactively; the KiCad download from the PPA is slow on GitHub runners and a silent step was cancelled as hung.
- `workcenter render` leaves the fabrication layer out of the 2D top image.
- `merge_ses` drops the router's echoes of fixed wires and splits a track where the router joined onto it.
- `autoroute` skill: the generated-design path is headless end to end; the hand-drawn path still supplies the DSN.
- `doctor` reports `rsvg-convert` and the KiCad symbol libraries.
### Deprecated
### Removed
### Fixed
- The session merge keeps a short link that leaves a hand track at an angle, the joint of a T the router makes onto it. It took the link for an echo of the track and dropped it, and the wire after it ended off the track's centre line: Last Hit v0.16 routed with the new DSN showed one dangling HS_IN track.
- A fab's rule file no longer loosens a board: in KiCad a custom rule overrides every net class's clearance, so the Sierra set's board-wide 4 mil clearance and 6 mil hole had let pours fill 0.1 mm from pads and a 0.25 mm minimum hole pass at 0.1524 mm. Its board-wide limits are now the board's own minimums (`kicadgen.fab_project_rules`, the `--fab` copy's project file) and only its layer and condition rules are copied, each raised to the board's own setting (M62).
- `kicadgen`'s via check holds two nets to the larger of their net classes' clearances, as KiCad's DRC does, not to the board default (M62).
- FreeRouting session coordinates are read at the scale the session's placement block implies, not the declared resolution.
- FreeRouting pinned to 1.9.0: 2.1.0 hangs after routing in proxied environments because its GitHub version check fails.
- `kicadgen`'s via check treats a non-plated hole as board edge, as the DRC does; island stitching had put a via 0.2 mm from a receptacle's peg hole (M26).
- Island stitching after routing keeps its vias out of keepouts; one keepout check (`Design.in_keepout`) now serves both via placers (M30).
- The router sees a non-plated hole grown to the board-edge clearance the DRC applies to it, not the hole clearance (M33).
- Island stitching runs once per poured net, not once per zone: a net with two zones got two vias on one spot (M37).
- A custom pad on the bottom face is mirrored with its shapes, not only its position; its size is read from its shapes, not its anchor (M38).
- The generator's pad boxes leave out paste-only apertures, and measure a round pad as a circle, not as its box.
### Security
