# Fixture boards

These projects are the tests of the gates. Each one exists to make 1 gate
behave in a known way.

| Project | Expected | Why |
|---|---|---|
| `pass-rc-divider` | GREEN on `workcenter gates`, with `--strict` too | A 2-resistor divider with an RC filter. Schematic, board, and a sim deck with bounds. Its `sim/corners.json` names -40 and 85 C, 1 % resistors, a 10 % capacitor and 8 Monte Carlo draws: 18 corner runs, the output between 2.4605 and 2.5417 V. |
| `fail-drc-clearance` | ERC pass, DRC fail with a `clearance` violation | The same board with 1 track moved inside the clearance of a pad. |
| `fail-sim-spec` | SIM fail on the `vout` bound | The divider deck with bounds that the circuit cannot meet. No board, no corners: the gate names their absence as a warning. |
| `fail-sim-corner` | SIM fail at a corner, each bound holding as written | 2 decks, no board. `diode_ref`: a diode's forward voltage, 0.548 V at 27 C and 0.42 V at 85 C against a 0.50 to 0.60 V window. `divider`: 2.5 V as written, 2.375 V with its 5 % resistors at their worst against 2.45 to 2.55 V. |
| `pass-lc-filter` | SIM pass with `--strict` | 3 decks, no board: a 15.9 kHz input filter swept with `.ac`, a 100 kHz load clear of it, and a 16 kHz clock on its resonance. `sim/frequency-plan.json` names both sources and the resonance, and answers the clock's overlap with the deck that drives it. |
| `fail-freq-overlap` | SIM fail on the frequency plan alone | The same filter with a load at 5.3 kHz, whose third harmonic is the resonance: the rail swings 6.8 V on a 5 V supply while the deck's one bound, on the average, holds. Only the plan sees it. |
| `inspect-four-layer` | `workcenter inspect` answers as `tests/test_inspect.py` expects; DRC fails with 1 unconnected item, the pour island it keeps on purpose | Generated from its own `design.py` (regenerate with `workcenter design`; a test compares). Four layers, VIN's 10 mm run on In2.Cu between two vias, a T-junction, a copper keep-out over the island, a parts keep-out, Sierra's rule file. |
| `fail-fab-sierra` | GREEN on `workcenter gates --strict`, DRC fail with `--fab sierra-circuits-web` (`annular_width`, `text_thickness`) | The divider with a 0.6/0.3 mm via (0.15 mm ring, under Sierra's 6 mil) on a bottom-face return of VOUT, and a legend label stroked 0.10 mm (under 5 mil). |

Symbols and footprints are embedded in the files, so no library tables are
needed to run them. `build/` output is ignored by git.

`kicad-cli` writes a `<name>.kicad_prl` next to the project when it runs.
It is a KiCad side file with no design content and is ignored by git.
