### Added
- SIM asks for every part of the board whose facts carry a thermal figure. One that `sim/thermal.json` does not name is not judged, on 1 line that gives the row to write; `--strict` fails on it. `details.thermal.board` holds the board's line, the parts asked for (`asked`), those left out (`unplanned`) and the rows for no fitted part (`strays`).
- SIM: a project with no deck is asked for its parts with a thermal figure all the same. A project with decks and no schematic is asked for each facts entry with a figure whose part number a deck names.
- SIM: a part with no part number and no facts entry, whose pins fit an entry with a thermal figure, is not judged. This can be a false alarm; giving the part its number in `parts.csv` beside the schematic clears it.
- `workcenter next`: each new thermal line names its own step.
