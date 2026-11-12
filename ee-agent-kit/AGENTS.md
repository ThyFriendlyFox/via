# AGENTS.md — the binding contract

In effect whenever code in this repo is touched, by agent or human.
When this conflicts with intuition, this wins.

## Commands

```sh
make doctor      # build: a working toolchain is this repo's build artifact
make test        # gate tests on the fixture boards
make lint        # shellcheck + ruff
make verify      # full health gate — must pass before any push
```

Requires Ubuntu 24.04, Python 3.12, KiCad 10.0, Java 21. `sudo ./install.sh`
provides them. `python3 tools/workcenter doctor` says what is present.

## Invariants — never regress these

1. `install.sh` is the single source of the toolchain. The cloud
   environment setup script, the Dockerfile, and CI all run it. No tool
   is installed by any other path.
2. `install.sh` is idempotent and exits non-zero on a required failure.
   A cloud environment that runs it fails to start rather than starting
   without KiCad.
3. `tools/workcenter` uses the standard library only and runs with a
   bare `python3`. The venv holds test and lint tooling and kipy; the
   CLI never imports from it.
4. Gates run in the order ERC, DRC, SIM, EXPORT and stop at the first
   red. Export never runs on a board that failed DRC.
5. A gate that cannot run reports `skip` with a reason and exit code 2.
   It never reports `pass`.
6. The fixture boards under `tests/boards` are the tests of the gates.
   A change to a gate's behavior lands with the fixture that proves it.
7. Engines write only inside the output directory (`<project>/build` or
   `--out`). Nothing is written into a project's source files or into
   this repository by a gate run.
8. `WORKCENTER.md` is the contract projects consume. A gate, tool, or
   path change lands in `WORKCENTER.md` in the same commit.
9. Symbols and footprints in fixture boards are embedded. Tests never
   depend on KiCad library tables or on the 3D package.
10. Kit skills in `ee-agent-kit/skills/*` and their installed copies in
    `.claude/skills/*` are byte-identical. `make verify` checks it.
11. `tools/kicadgen.py` uses the standard library only and reads the
    KiCad libraries from disk; it never embeds a copied symbol or
    footprint in this repository.
12. A generated board is regenerated from its design file. No commit
    edits a generated `.kicad_*` file by hand. Board projects live in
    their own repositories; this one holds tools, fixtures, and docs.
13. A verdict is never stronger than its run. A run that holds a gate
    skipped for an absent engine is SKIPPED with exit code 2, never
    GREEN. GREEN names the count of warnings beside it. `PASS verify`
    is followed by a line that says whether the requirements are met.
14. `tools/simcorners.py`, `tools/freqplan.py` and `tools/guide.py` use
    the standard library only, as the CLI does. They run no engine:
    `tools/workcenter` does.
15. A bound holds at every corner the project names, or it does not hold.
    A corner run is a copy of the deck in its own folder; no corner
    writes into the project.
16. `CLAUDE.md` and `AGENTS.md` at the repository's root are the same
    text. `make verify` checks it.
17. The chip gates run in the order LINT, SIM, SYNTH, LAYOUT, STA, GLSIM,
    DRC, ANTENNA, LVS, EXPORT and stop at the first that does not pass.
    Every one is required: a chip gate that did not run is the verdict,
    `SKIPPED (GATE: reason)`, however many passed.
18. A chip gate that passes writes a record: the hash of each file it
    read, taken before its engines start and held after, and of each file
    it hands on. EXPORT copies a layout only when all 9 records agree
    with the files as they are.
19. No file, cell, layer or number of a process is written in
    `tools/chip*.py` or `tools/chipscripts/`: each comes from a table in
    `pdks/`, with its source. A test holds it.
20. `tools/chipflow.py`, `tools/chipfront.py`, `tools/chipback.py` and
    `tools/chipguide.py` use the standard library only, as the CLI does.
21. A number a gate prints about a file is counted in that file (M167).

## Landmine map

| Area | Why it bites |
|---|---|
| `install.sh` PPA step | `add-apt-repository` needs the system python's `apt_pkg`. Images with another default `python3` break it. The script writes the sources file and verifies the key fingerprint itself. Keep it that way. |
| `install.sh` PPA key | Some proxies reset every connection to keyserver.ubuntu.com. The step falls back to Launchpad's API (`getSigningKeyData`), which returns the same key as a JSON string; the fingerprint check decides either way (M133). |
| `install.sh` package list | `kicad-packages3d` is 3.3 GB installed and pushes the cloud setup past the 5-minute snapshot window. Never add it to the default list. |
| `tools/workcenter` exit codes | `--exit-code-violations` makes `kicad-cli` return 5 on violations. The CLI treats 0 and 5 as "ran" and parses the JSON report. Every other code is an engine error. |
| `tools/workcenter` doctor | `java -version` prints to stderr, and some images inject `JAVA_TOOL_OPTIONS` with a proxy address. The version regex anchors on `version "`. |
| FreeRouting | The JAR comes from a GitHub release asset host, which some network policies block. The step warns and continues unless `REQUIRE_FREEROUTING=1`. CI sets it; the cloud setup script does not. |
| Fixture boards | They are hand-written KiCad 10 S-expressions. Opening and saving them in KiCad rewrites UUIDs and ordering. Commit such a rewrite on its own, with "regenerated by KiCad" in the message. |
| `.claude/settings.json` | Hooks here load only in a single-repository session. In a session with several repositories nothing here runs; the attached-repos skill carries the behavior instead. |
| `verify/verify.sh` placeholder gate | `ee-agent-kit/SETUP.md` documents the placeholders and is the only file allowed to contain them. |
| FreeRouting version | 2.1.0 calls the GitHub releases API at start; when that call fails (proxied or offline environments, including the cloud sessions) its completion chain breaks and the main thread sleeps forever after routing, never saving the session. 1.9.0 makes a version check too (`VersionChecker` in its log); when the check fails the run goes on and finishes. Stay on 1.9.0 until a 2.x release can be told not to call home. |
| FreeRouting's start | 1.9.0 waits 20 s for a click on a dialog that asks to confirm the start, on a headless display too: 22.5 s lay between `Opening` and `Starting auto-routing` in its log. `-dct 0` starts at once and writes the same session file, in 4 s where the run took 24 s. Both commands that start the router pass it. `-help` needs a display, so the option is read from the JAR's `StartupOptions` class. |
| FreeRouting's wires | 1.9.0 writes 2 wires of 1 net that share a stretch. `merge_ses` splits each at the other's end, and the shared piece came out 2 times in the board file. `_split_junctions` keeps 1 of 2 segments that the file would write with the same ends. |
| FreeRouting session scale | The `.ses` declares `(resolution um 10)` but its coordinates are 10 times that. `merge_ses` reads the scale from the session's placement block. Trusting the token puts every track off the board. |
| Net class widths | A track cannot enter a pad wider than pitch minus pad width minus 2 x clearance: 0.6 mm for SOT-23 and 0603, 0.5 mm for 0402, 0.4 mm for TSSOP. Wider heavy nets leave FreeRouting with unrouted pins, not an error. A sense tap on a heavy net may be drawn thinner with `d.track(..., width=)`. |
| KiCad 10 library tokens | `.kicad_sym` 20251024 and `.kicad_mod` 20260206 carry tokens the 9.0 schematic and board formats reject. `kicadgen` strips `DROP_SYMBOL_TOKENS` and `DROP_FOOTPRINT_TOKENS`; extend those sets, do not bump the file versions blindly. |
| Open pins and parity | KiCad names the pad net of an unconnected pin `unconnected-(REF-PINNAME-PadN)` with `/` written `{slash}`. A pad left without that net fails schematic parity. |
| `kicad-cli sch export svg` | Names the file after the sheet, not the project. `gate_render` picks the newest `.svg` in the output directory. |
| VRML bodies are in 0.1 inch | A `.wrl` body KiCad loads is scaled by 2.54; a body written in millimetres renders 2.54 times too large. `wrlgen` divides on output; a hand-made `.wrl` must too. | `tools/wrlgen.py` `MM` |
| Shell cwd is shared | Parallel tool calls run in one shell; a `cd` in one command is clobbered by the next, so a relative path or a `cd && ...` chain lands in the wrong directory without an error. Absolute paths, `make -C`, `git -C`, `python3 /abs/script.py`. | P8 |
| Back-side pad order | A part on `B.Cu` is mirrored about the X axis. At rotation 0 its pad 1 sits on the left and its pads' y are flipped: a SOT-23 has gate bottom-left, source top-left, drain right; a vertical 1206 has pad 1 at the bottom. Hand routes to a back-side pad are checked against `workcenter drc` output, not against memory. |
| FreeRouting clearance types | 1.9.0 reads `(clearance N (type via_wire))` and similar but no item uses the structure's classes, and a net class's typed rule covers only its own vias and wires. A rule the router must keep for every pair (a hole's inner-layer clearance, M79) goes into the shapes: `dsn()` grows a drilled item's copper on that layer. Wiring with no type is unfixed and its optimiser reworks it; copper that must stay where it is but may yield goes in as `(type shove_fixed)` (`design --seed`). Prove any new DSN keyword by routing a fixture, never from the spec. |
| FreeRouting gives up | 1.9.0 stops when it decides a connection cannot be made; it stops after seconds, and more passes change nothing. The fix is in the design: give the router room, or draw the link with `d.track`/`d.via` as fixed wiring. Fixed wires come back in the session, sometimes cut elsewhere or extended to a pad centre; `merge_ses` drops echoes and splits T-junctions. |
| FreeRouting at an angle | 1.9.0 reached none of an MSOP's 0.65 mm pins with the part turned 26 degrees, and all of them at 0. A fine-pitch part stands at a multiple of 90 degrees (P4 step 10, M142). |
| Pour islands | A `d.zone` is a plane to the router, so it routes no track for that net, then other nets' tracks wall pads off from the pour. `write()` fills the pour with `kicad-cli pcb drc --refill-zones --save-board`, reads the pieces with KiCad's `pcbnew` module, and stitches islands with vias; `workcenter design --route` reserves a via beside what is left and routes again. Both need `pcbnew`, which the venv sees only because `install.sh` creates it with `--system-site-packages`. |
| pcbnew 3D model paths | `footprint.Models()` hands out copies: a path set on one (`m.m_Filename = ...`) never reaches the saved board, and nothing says so. A board saved elsewhere then resolves `${KIPRJMOD}` against its new folder and draws those parts bare. `tools/scene.py` copies the board's own bodies to the same path beside the saved scene. |
| `install.sh` apt output | KiCad is a large download from a PPA that GitHub runners fetch slowly. The install step prints each fetched and unpacked package; a silent 30-minute step looked hung and got cancelled. Keep it visible and non-interactive. |
| ngspice's exit code | ngspice 42 exits 0 when one analysis of a `.control` block aborts (`doAnalyses: TRAN:  Timestep too small`, `tran simulation(s) aborted`) and a later one completes; `meas` then reads the cut vectors. `NGSPICE_ERROR_RE` takes both lines for errors. A new failure shape gets its sample in `tests/test_simgate.py` (M103). |
| ngspice's step control in a loop | A transient through a feedback loop whose signals are microvolts can drop its step to 1 ns at the start and never finish, for one part value and not its neighbour (6.2k, not 6.8k). `.options method=gear reltol=1e-3 vntol=1e-5 chgtol=1e-12` runs it in a second; check the answer against `method=trap` (P27 step 10, M144). |
| ngspice's `.spiceinit` | It reads the working directory's file, else the home folder's. A deck with none of its own would take the user's. `ngspice_run` points `HOME` at the output folder. |
| ngspice's temperature | The last `.options temp` of a netlist wins, and `set temp` or `option temp` inside `.control` wins over both. A corner writes its line just before `.control`, then reads `Doing analysis at TEMP = ...` back for each analysis: a deck that sets its own fails the corner, it does not pass at the wrong temperature. |
| ngspice `.meas ac` in batch | A deck with `.ac` and `.meas ac ... vm(x)` as netlist lines and no `.control` block saves nothing (`no data saved for A.C. Small signal analysis`). Run the analysis and the `meas` lines inside `.control`. |
| A deck outside the gate | A deck that includes a maker's model needs the gate's mode (`set ngbehavior=ps`) and translation. Bare, TI's models stop with `no such function 'if'` and Diodes' print other numbers with exit 0. A deck leaves the machine only as a bundle (`sim --bundle`), whose `run.sp` sets the mode and reads the deck through `$inputdir` (M105). |
| Expect files | A measure's name is lower case as ngspice prints it. A complex value (`h = 8.4e-01,-5.3e-01`) is no measure: the deck prints its magnitude. `read_expect` refuses a key it does not know (M104). |
| KiCad's Sim.Pins | KiCad 10.0.8 binds a model's node that `Sim.Pins` leaves out to a pin by position, with exit code 0 and no ERC violation: a 5-pin regulator on a 4-node subcircuit with `1=IN 2=GND 5=OUT` still gets its EN node from pin 3. A `.model` of a 4-terminal MOSFET on a 3-pin part gets a bulk on a node of its own (`NC-Q1-0`). `Design.sim_problems()` refuses both; a map names every pin and every node (`tests/test_simfields.py`). |
| KiCad's passive values | A part with no Sim field whose reference starts with R, C or L is written as that passive, with its value as KiCad reads it: `4k7` is `4.7k`, `1M` is `1Meg`, `10k 1%` and `100nF/50V` go in as written, `10µ` leaves `R13 __R13`, and `LED1` with the value `red` is the line `LED1 GND /F red`. `PLAIN_VALUE_RE` holds only forms seen to come out as numbers; `check_sim` excuses only a reference of R, C or L and digits. |
| A design that says nothing new | `workcenter design --check` and board repositories' CI compare a regenerated `.kicad_sch` and `.kicad_pro` with the committed ones byte for byte. Anything new the generator writes (a field, a severity, a text item) is written only for a design that asks for it (`Design.simulates()`), and the fixture `inspect-four-layer` regenerates to its committed bytes in `tests/test_inspect.py`. |
| ngspice's value spellings | ngspice 42 reads `4k7` as 4 k and drops the 7 without a word; KiCad writes that form for 4.7 k. `5a` is 5e-18. A value can stand on a continuation line, behind `r=`, or as an expression in braces. The corner code reads each the way ngspice does, and the gate fails a deck whose value ngspice reads as another number (M117). |
| ngspice's `temp=` on an element | It holds that element at its own temperature while every analysis still prints the circuit's (`Doing analysis at TEMP = ...`), so the read-back cannot see it. The gate reads the deck's text for it and fails the temperature corners. |
| ngspice's nested `source` | A `source file` inside `.control`, and a file source, are read against the working directory, not the deck's folder. A corner's folder links the deck's sibling files, and a bundle's `run.sp` runs `cd $inputdir` before it reads the deck. |
| FreeRouting's exit code | FreeRouting 1.9.0 ends with exit code 0 and logs no count on a board where it joined nothing: every part outside the outline, a width that enters no pad. `route()` counts the connections of a board that holds copper for none of them, and `workcenter design` exits 1 on that count. |
| The account's usage limit | A helper stops with `You've hit your 5-hour limit` and the time the limit resets. A session cannot read what is left before that. P31 step 1: 2 helpers at most until 1 reports, and none before the reset a stopped helper names (M113, M120). |
| A shell tool call | The host runs a call's text inside a list, where bash ignores `errexit`: `set -e; false; echo went on` prints `went on`. Join commands that depend on each other with `&&`, or run them in `bash -e -c '...'` (M159). | P8 |
| OpenSTA's `read_spef` | A SPEF with a syntax error is read up to the error: `Warning: ... line N, syntax error.`, exit 0. A net the SPEF leaves out gets an estimate from the library and no line at all. The STA gate holds the SPEF's net names to the design's (`tests/chips/samples/back/sta-spef-cut-short.log`). |
| OpenSTA's digits | 2 digits print a slack of -0.004 ns as `-0.00`, which reads as 0. `tools/chipscripts/sta.tcl` asks for 4. |
| OpenROAD's `link_design` | A cell the liberty file or the LEF lacks is dropped: `[WARNING STA-0198]`, `[WARNING ORD-1013]`, exit 0, and a layout built without the cell. The LAYOUT gate fails on either line (`tests/chips/samples/back/layout-unknown-cell.log`). |
| OpenROAD's `report_design_area` | It rounds the utilisation to 1 %: `Design area 299 u^2 60% utilization.` for 0.5975. `tools/chipscripts/layout.tcl` counts it from the database and prints 4 digits. |
| Magic's exit code | Magic exits 0 after a layout file it read in part (`Error while reading cell`) and after an extraction with illegal overlaps (`Total of N errors`). The gates read both lines (`magic-drc-cut-short.log` and `extract-overlap.log` under `tests/chips/samples/back/`). |
| Netgen's final result | `Final result: Circuits match uniquely.` stands over a cell whose transistor has another size. That cell's comparison reads `Netlists match uniquely with property errors.`, and the cell is named under the final result. The line `Property errors were found.` is not in such a report (`tests/chips/samples/back/lvs-property-error.rpt`). |
| Magic's GDS writer | With its hierarchy output on, Magic 8.3.465 works out the implant layers again where 2 cells meet and writes its own shapes into the top cell. They differ from the kit's drawn ones by slivers of 5 nm, and the kit's KLayout deck counts each: 8 items (`npc.2`, `nsd.2`, `psd.2`) on the processor of 2026-11-11, none of them a fault of a cell. `tools/chipscripts/gds.tcl` sets `cif *hier write disable` and `cif *array write disable` before `gds write`, as the kit's own scripts do. `cif help` lists neither option. |
| Magic's GDS dates | Magic writes the date a library and each cell were made as 1970-01-01, and the date they changed as the minute of the run: 2 builds of 1 layout differ in 128 bytes. `gds_undated` in `tools/chipback.py` sets each date of change to the date made, so 1 layout has 1 hash. |
| OpenROAD's wire estimate | `set_wire_rc -layer met2` reads the technology LEF: 0.078 fF/um. The kit's extraction rules give the routed wires of the processor 0.166 fF/um for a signal and 0.151 for a clock. With the LEF's value the repair after placement passed 2 nets that STA then failed. `pdks/sky130A.json` holds the measured values (`wire_capacitance_ff_per_um`), `layout.tcl` hands them to `set_wire_rc`, and LAYOUT holds the line the engine prints to the table. |
| OpenROAD's `repair_antennas` | 3 things in build f12e2f47. It takes 1 library pin, and `get_lib_pins` gives 1 for each corner the build read: `TypeError in method 'repair_antennas', argument 1`. It keeps a diode off cells that are FIRM and not off cells that are LOCKED, so a diode lands on a tap cell: `[ERROR DPL-0033]`. It deletes every fill cell when it puts a diode in: `[INFO GRT-0011] Deleted 61 filler cells.`, and a layout with fill placed only before it fails DRC and LVS. `layout.tcl` takes the first pin, sets the taps FIRM before the repair and places the fill after it. |
| OpenROAD's second `detailed_route` | A second routing in 1 run of build f12e2f47 crashes: `vector::_M_range_check`. The build routes once. The repair works on the global route, and it does not see what the detailed router then leaves: a gate that still collects too much charge is ANTENNA's failure. |
| Yosys's flop count | Yosys removes a flop that nothing reads. `synth` removes some before `generic.json` is written, and the full `abc` proves more: on the acceptance processor 24 of 156 flops go after the mapping. A count of flops is true only of the file it was counted in (M167). SYNTH counts the flop cells of `stat.json` and names each flop of `generic.json` that `mapped.json` no longer holds. A flop that `synth` itself removed is in neither file, and nothing names it yet. |
| Yosys 0.33's mapping | `abc` and `dfflibmap` have no option that keeps a cell out. A cell stays out of the mapping only when the liberty file does not offer it: SYNTH writes `mapping.lib` without the cells of the kit's `no_synth.cells` and `drc_exclude.cells`, and counts what the netlist holds of either list. |

## House style

- Match the surrounding code's idiom, naming, and comment density.
- No demo scaffolding, no leftover diagnostics, no dead flags.
- Comments state constraints the code can't show — never narration.
- User-facing copy states the thing plainly; no reassurance microcopy.

## Process rules

- Branch from `main`; never commit to it directly.
- `make verify` green before every push. Flaky gate → fix or
  quarantine in the same PR; never route around it.
- After adding/removing/renaming source files, run the stack's
  regeneration step (project gen, lockfile, tidy) and commit the result.
- Commit at boundaries; message says what changed and cites evidence.
- A commit's author and committer are the repository's owner. No message
  carries a `Co-Authored-By` line for an assistant or a session line (the
  owner's decision of 2026-11-11). `tests/test_docs.py` fails on a commit
  that does.
- Docs move with behavior — same commit or PR.
- Report outcomes faithfully; failing is failing, with output.
- `PROCESSES.md` is binding: before an action it names, follow its steps;
  a change is done when the process's "Done when" holds.
- Every mistake gets an entry in `MISTAKES.md` and a process that prevents
  it, in the same PR as the fix (`P13`). `make verify` checks the link.
