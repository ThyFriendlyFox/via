# Wyvern board

This folder is a **project**: a series of board prototypes that use the EE Workcenter (this
repository's `tools/`) for its tools and gates, laid out the way a board repository lays itself out
(compare thyfriendlyfox/vape-prototype). It is the workcenter's example of what a design file can
make; the workcenter itself stays as it is during board work.

- Each prototype is a folder, `v0.1/` and on, and each folder is a whole KiCad project. The highest
  version is the one in work. Every new feature is a new version: `workcenter version new . v0.2`
  copies the latest folder and does the bookkeeping (workcenter PROCESSES.md P22).
- `design.py` is the source of truth. Edit it, then regenerate: `workcenter design v0.1/design.py
  --route`. Never hand-edit the `.kicad_*` files.
- A board is done when `workcenter gates v0.1 --report v0.1/docs/gates.md` prints GREEN.
- `workcenter pictures v0.1` draws what `v0.1/pictures.json` names (the board, every layer, the
  turning GIFs, the assembly with the Snapdragon module) and copies them into `v0.1/docs/`.
- `open_q_845.py` holds the module's 300 pins, named from its public datasheet; the symbols, the
  design and the assembly read it. `symbols/make_symbols.py`, `footprints/make_footprints.py` and
  `models/make_models.py` write the project's own symbols, footprints and bodies.
- `parts/catalog.csv` names an orderable part for every value and footprint; `workcenter costs .`
  prices each version into `parts/lists/`. `library/sources.csv` names each part's datasheet;
  `workcenter docs v0.1` writes the version's `CONTENTS.md` and `datasheets/`.
- Spec, pin plan, BOM, and decisions live in the version's `README.md`. Change them in the same
  commit as the design change they describe.
