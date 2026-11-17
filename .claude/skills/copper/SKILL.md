---
name: Copper
description: Holds a routed board's power nets to a greatest voltage drop and current density on their real copper, and the board to a greatest temperature from its parts' heat spread through copper and vias, with a picture of each; currents and heat come from ratings.json, limits and the air from copper.json.
---

# Copper

DRC knows a track's width. It does not know that 1 A goes through a 0.3 mm neck, or that a regulator
4 mm from a connector cooks the pads between them. `workcenter copper` solves the board's own copper:
each power net's voltage and current density, and the board's temperature in a steady state. Each limit
is the project's; each constant names its document (`rules/copper/README.md`).

## When

- A board is routed, and `ratings.json` states a current on a pin or a part's heat.
- A track, a pour, a via or a part's place changed on such a board.
- A human asks for the voltage drop, the current density or a heat map.

## Inputs

| File | Holds | Who writes it |
|---|---|---|
| `<name>.kicad_pcb` | The copper: pads, tracks, arcs, vias and filled pours. Fill pours first: `workcenter design` does. | The design |
| `ratings.json` | Each current: `"J2.1": {"amps": 1}` on a pin, `"R1": {"amps": 0.024}` through a 2-pin part. Each part's heat: `"U1": {"watts": 0.4}`. A resistor with a current, on the part or on a pin, and a Value gives I^2 R itself. Each pin of a judged net states its current, 0 too. | The designer, with a source for each |
| `copper.json` | The air (`ambient`, an optional `h`, and the words of the assumption), the greatest board temperature, and for each power net its entry pin (`from`) and its greatest drop (`volts`) and density (`amps_per_mm2`), each with a source. | The designer |

```json
{
  "air": {"ambient": 25, "source": "still air, no enclosure: the product's own assumption"},
  "temperature": {"max": 105, "source": "the laminate's limit less a margin: name the document"},
  "nets": {
    "+5V": {
      "from": "J1.1",
      "volts": {"max": 0.05, "source": "U2's supply tolerance: name the datasheet and page"},
      "amps_per_mm2": {"max": 50, "source": "the project's own rule: name it"}
    }
  }
}
```

`grid` may set the cells: `{"drop": 0.05, "heat": 0.25}` in mm. The heat's cell is a whole number of
the drop's.

## Steps

1. `workcenter copper <project>`. It prints 1 line of counts, then 1 line per finding, then the verdict.
   It writes `build/copper/report.md`, `report.json` and the PNGs beside them.
2. For each line, by its start:
   - `copper: fail <net> current density ...`: the line names the place, x and y in mm and the layer.
     Widen the copper there, add a pour, or put the current on 2 layers with vias; change `design.py`
     and run `workcenter design <project>/design.py --route` again. Then step 1.
   - `copper: fail <net> barrel current density ...`: the current through a via's or a plated hole's
     barrel, over its copper section, pi ((r + plating)^2 - r^2). Add vias beside it, or a larger drill.
     Then step 1.
   - `copper: fail <net> drop ...`: the line names the pin that sees the most drop. Widen the path
     from the entry to that pin or shorten it, as above. Then step 1.
   - `copper: fail board temperature ...`: the line names the place and the nearest part. Give that
     part's pads more copper on the same net, add vias to a plane under it, or move it from other heat.
     Then step 1.
   - `copper: not judged <net>: ratings.json states ... and copper.json names no entry for it`: add the
     net to `copper.json` with its entry pin and its limits. Then step 1.
   - `copper: not judged <net>: ratings.json names this net and copper.json names no entry for it`: the
     same; a supply net of `ratings.json` is judged, or said not to be.
   - `copper: not judged <net>: ratings.json states no current at <pins>; taken as 0 A`: state each pin's
     current in `ratings.json`, `"amps": 0` for a pin that draws none.
   - `copper: not judged R1: ... gives no ohms`: state the resistor's `watts`.
   - `copper: not judged ... copper.json states no ... limit`: add the limit, with its source.
   - `copper: not judged ... a part of N pins`: name the pin in `ratings.json` (`U1.5`, not `U1`).
   - `copper: copper.json: ...` or `copper: ratings.json: ...` (no status word): the file is refused;
     the line names the key. Fix it. Then step 1.
   - `copper: hold ...`: nothing to do.
3. Open `build/copper/report.md`. Look at each picture: the density picture shows where current crowds,
   and the heat picture where heat stays. A hot spot on a pad with no copper round it is the place to
   add copper.
4. `workcenter copper <project> --strict`. Done when it prints `COPPER HELD` and exits 0.

## What the result is not

- A steady state: a current or a heat that lasts only a moment is judged as if it lasted.
- The air is the stated assumption, with no enclosure and no air flow. A reading of the built board
  replaces it (ROADMAP item 12).
- A part's heat enters by its pads; its body gives none to the air, so its pads read hotter than they
  are.
- The heat of every part `ratings.json` states nothing for is not counted. The report lists what is.
- Each cell's sheet is weighted by the part of the cell that is copper, so a straight track of any width
  reads R = rho L / (w t). The greatest density sits where copper turns a corner, and there it moves a
  little with the grid. Halve `grid.drop` to see how much. A `grid.drop` wider than the narrowest track
  of a judged net is refused.
