# ROADMAP.md — the source of all work

**This file is not optional.** Every feature the agent builds flows down
from here. If it isn't on this roadmap, it doesn't get built; if it needs
building, it gets added here first. One item ships per weekly cycle
(see `WEEKLY.md`).

`provisional: true` — the queue below was seeded at setup by the agent.
The human re-orders it.

## North star

EE Workcenter is the environment an agent steps into to take a KiCad
project from schematic to fabrication outputs with every gate green,
without a human running a tool by hand. Everything here serves that:
the toolchain installs itself, the gates are the definition of done, and
the skills tell the agent which gate comes next.

The owner's measure, 2026-11-10: a small model reaches the same working
design as a large one, and no electrical engineer has to find afterwards
what the gates left out. So what an engineer would ask lives in a gate
that runs it (corners, the frequency plan), and what comes next lives in a
command that says it (`workcenter next`), never in the reader's judgement.

## Feature Queue — ordered; top unblocked item ships next

### 1. A generated schematic that simulates
- **Promise:** A design file says how each part simulates (`d.sim(ref, library, name, pins)`, `d.no_sim(ref, reason)`, directives), `kicadgen` writes those as Sim fields on the symbols, and `kicad-cli sch export netlist --format spice` on the generated schematic gives a netlist ngspice runs. `workcenter design` refuses a part with neither declaration and a pin map that leaves a pin out, as `sim:` lines. A design that declares nothing regenerates to the bytes it has today.
- **Evidence:** A test that generates a design with a resistor, a library diode and a part bound to a subcircuit, exports its netlist with `kicad-cli`, runs it in ngspice and holds a value computed by hand; the byte-for-byte test of `tests/boards/inspect-four-layer` still green.
- **Use case:** Simulate before layout (`docs/USE-CASES.md`).
- **Scope guard:** No netlist written without KiCad. No change to the SIM gate. A symbol that holds 2 devices is refused or excluded, not wrapped. Facts from runs on KiCad 10.0.8: instance fields are enough; without `Sim.Pins` KiCad binds by position and says nothing (a rail read 1981 V with exit 0); a relative `Sim.Library` resolves against the project folder; `.param` goes in as a schematic text item; `simulation_model_issue` raised to an error makes the ERC gate report a broken binding.
- **Status:** ready. An engineer reviewing Last Hit v0.16 is redrawing its schematic by hand because the generated one carries no model (29 of 66 parts export as placeholders).

### 2. A small model builds a board with `next` alone
- **Promise:** The smallest model a session can start builds a board of a kind the workcenter has not seen (a switching regulator, an active filter) from a one-paragraph spec to `workcenter gates --strict` GREEN, reading only what `workcenter next` names. Every place it stops is recorded as a defect of the workcenter, with the line that should have told it what to do.
- **Evidence:** The run's transcript, the board's `gates.json`, and the list of defects with the commit that closes each.
- **Use case:** Design a board from a spec; Fix a red board.
- **Scope guard:** The model gets no hint outside the repository. A defect is fixed in a gate, a hint or a template, never in the brief.
- **Status:** ready. `workcenter next` exists; the run has not been made.

### 3. Headless autoroute for hand-drawn boards
- **Promise:** `workcenter autoroute --apply <project>` reads any `.kicad_pcb` (footprints, pads, outline, nets, existing tracks) into the DSN writer that `kicadgen` already has, runs FreeRouting, merges the session into the board file, and the new fixture `route-me` passes DRC with 0 unconnected items afterwards, with no KiCad GUI step.
- **Evidence:** `tests/test_gates.py::test_autoroute_apply_routes_fixture` green in `make verify`; the fixture's DRC report attached to the PR.
- **Use case:** Route a board (`docs/USE-CASES.md`).
- **Scope guard:** No routing heuristics of our own. No GUI automation. The generated-design path already works (`workcenter design --route`); this item is the board-file parser in front of it. Zones and arcs may be out of scope for the first cut and must be reported, not silently dropped.
- **Status:** ready

### 4. Board gates as a reusable GitHub workflow for board repositories
- **Promise:** A board repository that adds 1 workflow calling `ThyFriendlyFox/via/.github/workflows/board-gates.yml@main` gets `workcenter gates` run on every PR, with the gates table in the job summary and a red check on a red gate.
- **Evidence:** A run link from a board repository, plus `tests/boards/pass-rc-divider` run through the workflow in this repository's CI.
- **Use case:** Review a board PR.
- **Scope guard:** No comments posted to the PR; the check and the summary are the output.
- **Status:** ready

### 5. MCP server for hosts that are not Claude Code
- **Promise:** `workcenter mcp` serves `doctor`, `gates`, `erc`, `drc`, `sim`, `export`, and `autoroute` as MCP tools over stdio, and the MCP inspector lists all 7 with their schemas.
- **Evidence:** An inspector screenshot and a test that drives the server with a scripted JSON-RPC session.
- **Use case:** Build another workcenter from this one.
- **Scope guard:** stdio only; no HTTP transport, no auth.
- **Status:** ready

## Later — candidates, not yet specced

- Copper pours in `kicadgen` — a zone per power net with `kicad-cli pcb drc --refill-zones`, so heater returns stop depending on 0.4 mm tracks.
- Pad-entry width check before routing — warn in `workcenter design` when a net class is wider than its narrowest pad allows.
- SIM gate from the schematic — export the SPICE netlist automatically and apply a stimulus template, so a project without a hand-written deck still gets a simulation.
- `workcenter new <name>` — scaffold a board project with the `.gitignore`, `sim/`, and a passing starter board.
- Publish the workcenter as an account-level Claude Code plugin — skills and the MCP server arrive in every cloud session without touching board repositories.
- BOM availability gate — `workcenter procure --strict` already fails on a line short of stock; a gate would run it before export. Needs a project-wide parts file first.
- Digi-Key API refresh for `procure` — re-read every Digi-Key row's breaks and stock through Product Information v4 with the user's own credentials, instead of page by page.
- STEP export in the EXPORT gate by default once the fixture proves it runs headless in CI within the time budget.
- Per-run output folders for the gates, or a lock on `build/`: two runs on one project at once mix their reports (M73).
- `workcenter sources --fetch` compares PDFs by their bytes; onsemi serves each download with a new trailer ID, so an unchanged datasheet reads as changed. Compare the page content, not the trailer.
- `workcenter placement route_check` at a heater class's widths (0.6 mm) fails links the router and the DRC pass on a dense board; let it take a class per net, as the DRC does.
- `workcenter verify` reads a calculation's verdict as written; an equation checker for the calculations (each numbered line recomputed) would close the gap that M71 fell into.
- Deck values held to the schematic: `kicad-cli sch export netlist --format spice` gives every R and C with its value, so a deck element named like a board reference can be compared with the part it models, a derated value needing its reason. Last Hit's decks write C5 as 2.5 uF in two decks and 4.7 uF in a third.
- A maker's own tolerances as corners: the `tolerance` fix deletes the LOT and DEV specs of a vendor model; kept as a side table they would move the model's internal parts too (`alter r.xu4.r1` reaches one). Last Hit's current sense crosses its bound inside 0 to 40 C once the monitor's 1.5 % is counted.
- What a model carries, declared: a `sources.csv` column, or a probe at 2 temperatures, saying whether a model has temperature in it, so a requirement that rests on one that has none is named. The gate today warns only when no measure of a whole deck moves.
- A requirement that rests on a model off its datasheet: a `warn` bound that fails names the model, and every traceability row whose deck includes that model would carry the name. Last Hit's REQ-REG-01 passes by 13 mV on a dropout its own warn bound calls wrong.
- Accepted warnings as a file the gates read: each warning a project keeps, with its reason, who accepted it and when, so `--strict` passes on those and fails on a new one or on an entry that no longer matches.
- Measures from ngspice's own data: a `wrdata` or raw file the gate reads, so a deck's `echo "vout = 2.5"` cannot stand for a measure.
- A rail's impedance deck written from the board: the capacitors with their ESR and bias, the track's resistance from `inspect resistance`, an inductance from its geometry, so the frequency plan's resonances are not typed by hand.
- Ratings as data: each part's absolute maximum, voltage rating and power in a parts column, so a pin's worst net voltage, a capacitor's derating and a resistor's dissipation are checked by a command, not in a calculation's prose.
- The board as one netlist: once a schematic carries its models (queue item 1), a deck is the board's netlist plus an overlay of sources and measures, and the 12 retyped circuits of a project become 1.

## Shipped

| Week | Feature | Release | Evidence |
|---|---|---|---|
| 2026-11-10 | The SIM gate asks an engineer's questions: corners (`sim/corners.json`: each temperature, each tolerance, a worst case per bound, Monte Carlo draws), a frequency plan (`sim/frequency-plan.json`, P30), bundles that run on any machine (`sim --bundle`); an analysis ngspice gave up on and a malformed expect file refused; verdicts that say what ran (`GREEN with N warnings`, `SKIPPED (SIM: engine missing)`, `REQUIREMENTS MET` or `NOT MET`); `workcenter next`; a root `AGENTS.md`; the documents held to the code by tests | unreleased | 168 new tests, 405 in all: `tests/test_corners.py`, `test_freqplan.py`, `test_simgate.py`, `test_guide.py`, `test_docs.py`, 4 in `test_verify.py`; fixtures `fail-sim-corner`, `pass-lc-filter`, `fail-freq-overlap`; a scratch copy of Last Hit v0.16: 153 corner runs, the reviewing engineer's 85 C finding found by the gate (1.0763 V against 1.14 to 1.26 V), 12 bundles giving the gate's numbers from another folder; `MISTAKES.md` M103 to M113; `DEVLOG.md` 2026-11-10 |
| 2026-11-07 | The Last Hit work's conventions: `templates/project/` (a version's README and gates report), `templates/verification/BRIEF.md` and `FACTS.md` for helpers on one package, the owner's decisions in `workcenter verify` (a Withdrawn table, "the owner's decision of <date>"), P22 and P28 extended, the verification skill's "Helpers" and traps | unreleased | `tests/test_verify.py` (8 new tests, 24 in all); the Last Hit v0.16 package with REQ-USB-01 in a Withdrawn table: 64 requirements, the withdrawn ID named, its old traceability row refused, 276 quoted values matching the run; `MISTAKES.md` M92 to M98; `DEVLOG.md` 2026-11-07 |
| 2026-11-07 | Router and generator gaps: `workcenter design --route --seed <board>` (a previous route held as the router's starting wiring, loose ends unfixed, what no longer fits dropped and counted, M89); each layer's hole clearance in the DSN as grown via and drilled-pad copper and in every via check (the Later item for M79; FreeRouting 1.9.0 ignores a structure `via_wire` clearance and holds a class's to that class); a `stitch:` line per island via; the red last line of `workcenter design` (M85); the merge keeps a T-link onto a hand track | unreleased | `tests/test_routing.py` (11 tests): the M79 fixture's router via 0.3281 mm from an inner track before, 0.3581 after; a moved part rerouted from the seed with the five untouched lines kept. Last Hit v0.16 seeded from v0.15: base board 76 of 87 router tracks kept (63 unseeded), display 116 of 117 (116 unseeded; 85 with the seed all unfixed), DRC 0 errors and 0 unconnected on both either way; `DEVLOG.md` 2026-11-07 |
| 2026-11-07 | Document curation: `workcenter docs`, `costs`, `pictures`, `gates --report`, `version new`, `diagram`, and `tools/scene.py`, from Last Hit's scripts | unreleased | `tests/test_doctools.py` (20 tests); on a copy of Last Hit: `docs v0.16` and `costs` reproduce the committed `CONTENTS.md` datasheet table and every list and total ($61.76 and $396.86 for v0.16), `version new v0.17` passes P22 step 4, `pictures v0.16` redraws the README's images; `DEVLOG.md` 2026-11-07 |
| 2026-11-07 | Datasheets, simulation and CI from the Last Hit work: `workcenter fetch` (a library file and its `sources.csv` row), `workcenter curve` (a datasheet's curve from the PDF's vectors), `workcenter sim --deck --keep` (one deck the gate's way, and its hand-run command), `workcenter design --check`, `workcenter ci` (a GitHub workflow replayed), `workcenter mutate` (a firmware's mutation list), `kicadgen.py symbol-add` | unreleased | `tests/test_fetch.py`, `test_curve.py`, `test_ci.py`, `test_mutate.py`, and new tests in `test_sources.py` and `test_kicadgen.py` (26 tests); on Last Hit v0.16: `fw_is` 0.505 V through `sim --deck heater_pulse`, `design --check` exit 0, AccuGuard's 1.0 A curve 0.310 s at 2.5 A and 24.2 µs at 17.7 A, 50 of 50 mutations caught, the firmware CI job replayed GREEN on a copy; `DEVLOG.md` 2026-11-07 |
| 2026-11-07 | Board inspection: `workcenter inspect` (map, list, probe, net, islands, resistance, crossed) reads a routed board with KiCad's geometry and the board's own rules; `tools/stretch.py` grows a design at a cut; `d.keepout(..., parts=True)` keeps parts out of an area; P29 | unreleased | `tests/test_inspect.py` (21 tests) on the new fixture `inspect-four-layer`, `tests/test_kicadgen.py` (parts keep-outs, `parse_all`); Last Hit v0.16: its In2 run to the joint 56.8 mOhm, C5 to U2 64.3 mOhm, M90's overlap and M91's keep-out found again; `DEVLOG.md` 2026-11-07 |
| 2026-11-05 | Verification packages: `workcenter verify` (every quoted number against a fresh ngspice run, every traceability check recomputed), `templates/verification/`, P28, the `verification` skill; project-fitted models in `sim/models/`; `"req"` on expect bounds | unreleased | `tests/test_verify.py` (16 tests), `tests/test_sources.py` (the own-model rule); the Last Hit v0.14 package: 60 requirements, 175 quoted values matching the run; `DEVLOG.md` 2026-11-05 |
| 2026-10-29 | Pull-resistor check: `Design.undefined_inputs()`, `check_pulls`, `defined_nets` | unreleased | `tests/test_pulls.py`; Last Hit v0.11 checked; `DEVLOG.md` 2026-10-29 |
| 2026-10-29 | Fabrication house rule sets: `rules/sierra-circuits-web.kicad_dru`, `workcenter drc|gates --fab`, `Design.fab` | unreleased | `tests/test_fab.py` (fixture `fail-fab-sierra` GREEN plain, red with the fab; the board-wide minimums; the project untouched); Last Hit v0.11 checked: 47 errors under Sierra's limits; `DEVLOG.md` 2026-10-29 |
| 2026-10-29 | kistack vendored with the `kistack` skill; `workcenter placement` runs its placement checks headless | unreleased | `tests/test_placement.py`; `third_party/kistack/VENDORED.md`; `DEVLOG.md` 2026-10-29 |
| 2026-10-27 | `workcenter procure` and the `procurement` skill: a schematic's BOM priced from a parts file, cheapest order per line, totals per supplier | unreleased | `tests/test_gates.py` (the fixture priced to the cent at 1 and 10 units; unmatched, unpriced and short-of-stock lines; the skip); the Last Hit parts lists; `DEVLOG.md` 2026-10-27 |
| 2026-10-27 | Wired schematics in `kicadgen` (`sch_wires`, `sch_rot`); `render` names parts drawn without a 3D body; `wrlgen` `leadless` and `gullwing` bodies | unreleased | `tests/test_kicadgen.py` and `tests/test_gates.py` (wired divider ERC-clean with its declared netlist and no parity warning; pin positions at each angle as KiCad's ERC reports them; the bare-part report); Last Hit v0.10's two schematics; `DEVLOG.md` 2026-10-27 |
| 2026-10-23 | `kicadgen` design-as-code generator; `workcenter design --route` headless autoroute for generated boards; `workcenter render`; `board-design` skill | unreleased | `tests/test_kicadgen.py` incl. the routed round trip; the first real board, GREEN in its own repository; `DEVLOG.md` 2026-10-23 |
| 2026-10-22 | Install the kit; `install.sh`; gates ERC, DRC, SIM, EXPORT; fixture boards; skills | unreleased | `make verify` green at the install commit; `DEVLOG.md` 2026-10-22 |

## Explicitly not doing

- Reverse engineering KiCad with REA or similar — KiCad is open source with an official IPC API and CLI. REA belongs to workcenters built on closed tools.
- GUI or screen automation of KiCad — every operation goes through `kicad-cli` or the IPC API.
- Bundling a patched KiCad — the workcenter installs the upstream PPA build or uses the upstream image.
- Installing `kicad-packages3d` by default — 3.3 GB for 3D models no gate reads.

## Queue changes

- 2026-10-22 — queue seeded at setup, 4 items, provisional.
- 2026-10-27 — `workcenter procure` shipped out of band: the user asked for every prototype's parts sourced from Digi-Key with the full cost, as a workcenter skill.
- 2026-10-27 — the Later item "`kicadgen` schematic layout" shipped out of band: the user found the Last Hit schematics unreadable (M51).
- 2026-10-23 — item 1 re-scoped: the generated-design half shipped out of band while building the first board; the remaining half is a `.kicad_pcb` reader in front of the same DSN writer.
- 2026-10-29 — kistack shipped out of band: the user asked for it in the workflow.
- 2026-10-29 — item 3 (fab rule sets) re-scoped from JLCPCB to Sierra Circuits' Web PCB, the user's fab, and shipped; `Design.fab` added so a generated board carries its fab's rules for good. The MCP server moves up to 3.
- 2026-11-05 — verification packages shipped out of band: the user asked for requirements fit for a MIL-STD or DO-160 inspection, simulations traced to the requirements' sources, cited nodal analysis, and this method in the workcenter.
- 2026-10-29 — the pull-resistor check shipped out of band: the user asked for pull-downs wherever one is needed, in case one was missed.
- 2026-11-07 — the Last Hit work's conventions, templates and verification rules shipped out of band: the owner asked for every tool and convention of the Last Hit work in the workcenter.
- 2026-11-07 — router and generator gaps (`design --route --seed`, the inner drill clearance in the DSN from the Later list, the stitching report, the red last line) shipped out of band: the owner asked for every tool and convention of the Last Hit work in the workcenter.
- 2026-11-07 — document curation (`workcenter docs`, `costs`, `pictures`, `gates --report`, `version new`, `diagram`, `tools/scene.py`) shipped out of band: the owner asked for every tool and convention of the Last Hit work in the workcenter.
- 2026-11-07 — `workcenter fetch`, `curve`, `sim --deck`, `design --check`, `ci`, `mutate` and `kicadgen.py symbol-add` shipped out of band: the owner asked for every tool and convention of the Last Hit work in the workcenter.
- 2026-11-07 — board inspection (`workcenter inspect`, `tools/stretch.py`, parts keep-outs, P29) shipped out of band: the owner asked for every tool and convention of the Last Hit work in the workcenter.
- 2026-11-10 — corners, the frequency plan, bundles, the verdict lines and `workcenter next` shipped out of band: an engineer's review of Last Hit v0.16 found what the gates left out, and the owner asked for a core a small model can follow to the same working design as a large one. Items 1 (a generated schematic that simulates) and 2 (a small model builds a board with `next` alone) enter at the top for the same reason; the autoroute, workflow and MCP items move to 3, 4 and 5. Nine candidates join Later.
