---
name: fabrication
description: Writes the files a fab and an assembler take - Gerbers, drill, placement file, assembly drawing, IPC-2581 and a panel - each read back against the board, and the plan of measurements for the built board, from the project's own sim bounds.
---

# Fabrication files and the plan of measurements

EXPORT writes what a fab and an assembler take, and reads each file back
against the board it came from. `workcenter measure` writes what to probe
on the built board, with which instrument, and the span each reading must
fall in. Ordering, assembling and measuring are the owner's acts: this
skill writes the files and the plan, and claims neither an order nor a
reading.

## What EXPORT writes

All into `<out>/fab/` (`<project>/build/fab/` by default).

| File | From | Read back for |
|---|---|---|
| `gerbers/*`, `gerbers/*.drl` | `kicad-cli pcb export gerbers`, `drill` | made, not read |
| `placement.csv` | `kicad-cli pcb export pos --format csv --units mm --side both --exclude-dnp` | each placed part once, on the board's side, at the board's place and rotation (PosX = x, PosY = -y, Rot = rotation, to 0.001); no part the board keeps out; no 2 footprints with 1 reference |
| `assembly-top.pdf`, `assembly-bottom.pdf` | `kicad-cli pcb export pdf` of F.Fab or B.Fab (mirrored) with the outline, DNP parts hidden (`--hide-DNP-footprints-on-fab-layers`); a side with no part has no page | the designator of each part of that side drawn on its page; no designator of a part of the other side or of a DNP part. Read from the drawn text, not from KiCad's property popups, which name each footprint plotted whether its designator is drawn or not |
| `<name>.ipc2581.xml` | `kicad-cli pcb export ipc2581` | well-formed XML; each copper layer a CONDUCTOR layer; each net that has a pad; each placed part a Component on its side |
| `panel/<name>-panel.kicad_pcb`, `panel/gerbers/` | KiKit, when the project holds `panel.json` | the count of boards against the preset's rows x cols; an outline on Edge.Cuts with no open end; a panel at least rows x cols boards in size |

A part not fitted (DNP) is in no placement file and is hidden on the
assembly pages. A part kept out of the placement file alone
(`exclude_from_pos_files`: a hole, a fiducial) is drawn on its page as its
footprint draws it.

Not judged: the panel's exact size against the preset's gaps and rails,
and where on the page a designator is drawn.

## Steps for the fab files

1. Run `workcenter gates <project>` (or `workcenter export <project>` on a
   board that passed DRC). Read the `export` line:

   | The line says | Do |
   |---|---|
   | `PASS export N/N outputs, ... K files read back` | The files agree with the board. Go to step 3 if you want a panel. |
   | `FAIL export` with `- placement.csv: R2 is not in the file; the board places it on the bottom` | The file and the board disagree. The board is the design: regenerate it (`workcenter design`), never edit the file. A part that should not be placed gets `exclude_from_pos_files` in the design. |
   | `- <job>: kicad-cli exit N, wrote no <file>` | kicad-cli failed. Run the command of the table above by hand on the board and read its error. |
   | `- b.xml: net X is not named` or `copper layer ... is not a CONDUCTOR layer` | KiCad wrote IPC-2581 without a part of the board. Report it with the board; do not hand the file to a fab. |
   | `- placement.csv: R1 is at (x, y) rotated r; the board puts it at ...` | The file puts the part elsewhere than the board. Report it with the board; do not hand the file to an assembler. |
   | `- placement.csv: the board has 2 footprints called R1; each part needs its own` | The board's fault, not the file's. Give each part its own reference in the design and regenerate. |
   | `- assembly-top.pdf: R24 is not drawn; ..., and its footprint holds no ${REFERENCE} text on a Fab layer` | The footprint draws no designator on its Fab layer, so the assembler cannot find the part on the page. Add a `${REFERENCE}` text on F.Fab (B.Fab for a back part) to the footprint in the project's library, as KiCad's own footprints have, and regenerate. |
   | `- assembly-top.pdf: R2 is not drawn; the board places it on the top` | The footprint has the text and the page does not draw it. Look at the page; report it with the board. |
   | `- assembly-top.pdf: C9 is drawn; the board says not fitted (DNP)` or `R2 is drawn; the board places it on the bottom` | The page shows a part the assembler must not fit on that side. Report it with the board. |

2. Hand the fab `fab/gerbers/` and the assembler `placement.csv`,
   `assembly-*.pdf` and `bom.csv`, or `<name>.ipc2581.xml` alone if they
   take IPC-2581.

3. For a panel, put `panel.json` in the project: a KiKit preset. Start from
   `tests/samples/fab/panel.json` (kistack's starting values, with their
   source); read `third_party/kistack/skills/panelize/SKILL.md` before you
   change a section. Run `workcenter export <project>` again:

   | The line says | Do |
   |---|---|
   | `..., panel 2 x 2 boards, 52 x 56 mm` | Made and read back. The fab takes `fab/panel/gerbers/`. |
   | `SKIP ... panel not judged: KiKit does not import under <python>` | KiKit is not installed in that Python. `install.sh` puts it in the venv (`requirements.txt`). Elsewhere, set `KIKIT_PYTHON` to a Python that imports `kikit`. Exit code 2: the run is not GREEN. |
   | `- panel...: R1 is on 3 boards; the preset asks for 2 x 2 = 4` | KiKit left a board out. Read its messages in the run's details (`--json`) and fix the preset. |
   | `- panel...: the outline is open at (x, y)` | The panel's Edge.Cuts has an end that meets nothing. Look at the panel in KiCad at that point; usually a tab or a cut the preset asks for. |
   | `panel not judged: a <type> layout has no count of boards to hold` | Only a `grid` layout is checked. Use a grid, or check the panel by eye and say so. |
   | `- panel...: no outline on Edge.Cuts (its box is 0 x 0 mm)` | KiKit wrote no frame or board edge. Read its messages and the preset's `framing` and `cuts`. |
   | `- panel...: the panel is W x H mm; 2 x 2 boards of w x h mm need at least ...` | The panel's outline is smaller than its boards. Look at the panel in KiCad; fix the preset. |

## Steps for the plan of measurements

1. Run `workcenter measure <project>`. It runs SIM fresh, then writes
   `<out>/measure/plan.md` and `plan.json`.
2. Read each line:

   | The line says | Do |
   |---|---|
   | `PLAN <deck> <measure>: <instrument> at <pad> to <pad>; span ...; predicted ...` | Planned. Nothing to do. |
   | `NOT PLANNED ... deck node X names no net of the board` | The deck's node has another name than the board's net, or the deck models a part alone. Rename the node in the deck to the net's name (`out` meets `/OUT`; `0` meets `GND`), or leave the bound unplanned and say why in the README. |
   | `NOT PLANNED ... it reads i(...), a current` | A current is measured in series. Add a sense resistor or a jumper to the design, or leave it unplanned. |
   | `NOT PLANNED ... the deck computes no measure called X` | The expect file holds a bound the deck never computes. Fix the name in the expect file or the deck. |
   | `NOT PLANNED ... the plan cannot read <expression>` | The plan reads 1 vector (`v(out)`, `-v(out)`), 1 difference (`v(a) - v(b)`, probed at a against b), 1 measure, or 1 of these times or plus constants. A product, a ratio of 2 measures, a function (`db()`, `abs()`) or 2 vectors otherwise is no reading of 1 probe. Add a `meas` of the vector it is worked from, with its own bound, or say how to measure it in the README. |
   | `NOT PLANNED ... it is a meas over the let vector X, and ...` | The `meas` reads a `let` vector the plan cannot read; the rest of the line says why. As above. |
   | `NOT PLANNED ... no instrument is named for ...` | The plan knows op, dc, tran and ac with voltages, levels, times and frequencies. Say how to measure it in the README. |

3. The last line counts what is planned. The run exits 0 only when every
   bound is planned.
4. Read the Conditions column of `plan.md`. A deck that measures after
   `alter` lines (a higher supply, another cable, another capacitor) names
   them there, in force when that bound was measured. Set the bench to
   them, or write in the README that the board cannot be set so (a
   capacitor's value at a corner) and the reading is taken as stated.
5. After the board is built, whoever measures fills the Reading and
   Inside? columns of `plan.md`, and the board's README takes that table.
   A reading outside its span is written with the difference explained,
   never moved into the span.

## Done when

- `workcenter export` (or `gates`) prints PASS on the export line, with a
  panel line if the project holds `panel.json`.
- `workcenter measure` printed a PLAN line for each bound that the built
  board can be probed for, and each NOT PLANNED line is fixed or named in
  the README.
