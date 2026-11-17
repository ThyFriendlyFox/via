# Fabrication house rule sets

Each file is one fab's published limits as KiCad design rules (`.kicad_dru`, KiCad's own format), with
the page and the words each rule comes from. A project uses one in two ways:

- **For good:** set `fab = "<name>"` in the design file (`kicadgen.Design.fab`). The board's own
  minimums (`board_rules()`) rise to the fab's board-wide limits where they were looser, so the via
  check before routing (M46) refuses a via the fab would. `workcenter design` copies the file's layer
  and condition rules into the project as `<name>.kicad_dru`, which KiCad's DRC, and so
  `workcenter gates`, reads with the project.
- **Once:** `workcenter drc --fab <name> <project>` or `workcenter gates --fab <name> <project>` does the
  same on a copy for that run: the copy's minimums raised, the layer and condition rules after the
  project's own. Nothing in the project changes.

A fab's limits only add floors. In KiCad's DRC a custom rule overrides the board's own constraints and
every net class's, so a board-wide rule here (no layer, no condition) would put a 0.2 mm net class
clearance down to the fab's 4 mil, and a stricter board minimum (a 0.25 mm hole) down to the fab's. The
workcenter therefore never copies a board-wide rule into a project: it carries it as the board's own
minimum, and raises each rule it keeps to the board's own setting where that is stricter
(`kicadgen.fab_project_rules`; M62).

`<name>` is a file name here without `.kicad_dru`, or a path to any `.kicad_dru`.

`ratings/` is another kind of rule set: derating standards as packs for `workcenter ratings`
(`ratings/README.md`). `board/` holds board rule packs from standards: the gap for a net's voltage and
the width and vias for its current, which `workcenter drc` judges when a project names one
(`board/README.md`).

Each fab's page was fetched under the workcenter's own client name, `ee-workcenter/1.0`; each file
names the page's SHA256 as fetched.

| File | Fab and service | Read |
|---|---|---|
| `sierra-circuits-web.kicad_dru` | Sierra Circuits (Protoexpress), Web PCB: the online order, "Standard PCBs", IPC-6012 Class 2 | 2026-10-29 |
| `jlcpcb-2layer.kicad_dru` | JLCPCB, 2-layer FR-4, 1 oz copper | 2026-11-17 |
| `pcbway-standard.kicad_dru` | PCBWay, standard rigid PCB | 2026-11-17 |
| `oshpark-2layer.kicad_dru` | OSH Park, 2 layer prototype service | 2026-11-17 |

## JLCPCB, 2-layer

From https://jlcpcb.com/capabilities/pcb-capabilities. Checked: track and spacing 0.10 mm (1 oz), via
hole 0.15 mm, via ring 0.05 mm ((0.25 - 0.15) / 2 from their 0.15 / 0.25 mm via), plated pad ring
0.18 mm (their absolute minimum; 0.25 mm recommended), hole to hole 0.2 mm (vias) and 0.45 mm (pad
holes), copper to a routed edge 0.2 mm, legend text 0.15 mm stroke and 1.0 mm high.

Not checked: the width of legend lines and arcs, pad to silkscreen 0.15 mm, the 2 oz and multilayer
limits (another file each), and the extra cost of holes under 0.2 mm.

## PCBWay, standard

From https://www.pcbway.com/capabilities.html. Checked: trace and spacing 0.1 mm, drill 0.15 mm (under
0.2 mm costs extra), annular ring 0.15 mm, legend characters 0.15 mm wide and 0.8 mm high.

Not checked: copper to the board's edge and hole to hole, whose rows in the page's second table stand
in columns the text does not name; the width of legend lines.

## OSH Park, 2 layer

From https://docs.oshpark.com/services/two-layer/. Checked: trace width and spacing 6 mil (0.1524 mm),
drill 10 mil (0.254 mm), annular ring 5 mil (0.127 mm), copper 15 mil (0.381 mm) from the edge, legend
text stroke 3 mil (0.0762 mm), their limit for text; 5 mil is their recommendation.

Not checked: the 5 mil they recommend between holes, the 4 mil soldermask web, the width of legend
lines.

## Sierra Circuits, Web PCB

Checked: trace width and air gap 4 mil (0.1016 mm), finished hole 6 mil (0.1524 mm), annular ring 6 mil
(0.1524 mm), inner-layer drill to copper 13 mil (0.3302 mm) for plated and non-plated holes, legend
text stroke 5 mil (0.127 mm).

Sierra publishes these too, and KiCad's rule language cannot check them here: the legend's 5 mil applies
to silkscreen lines and arcs as well (KiCad's own footprints draw silkscreen at 0.12 mm, under it); a
3 to 4 mil solder mask dam for green (5 mil for black and blue); at most 100 holes a square inch; a 20 mil
inside radius and 40 mil width for notches, cutouts and slots; 0.8 mm boards held to ±10 %.

Not found on Sierra's pages, so not checked by this file and left to the board's own rules: copper to a
routed edge, copper to a non-plated hole on the outer layers, hole to hole, silkscreen text height and
clearance to pads, solder mask expansion. Their rigid-PCB "Standard" tier is looser (4 mil hole, 4 mil
ring) and is a different order; the pages also disagree in places (a "2 mil trace/space" card, a 5 mil
"preferred" ring). Ask Sierra before relying on anything looser than this file.
