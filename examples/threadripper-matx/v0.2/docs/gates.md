# Gates report — Basalt v0.2

`workcenter gates . --report docs/gates.md`, run from this folder on 2026-11-11 with KiCad 10.0.8
and ngspice 42; nothing was routed, so FreeRouting did not run. The raw results are in
`build/gates.json`, `build/erc.json` and `build/drc.json` after a run. The board is GREEN with no
warning: `--strict` would pass it. SIM has nothing to run; v0.2 has no deck (its README, "Simulation").

## basalt

<!-- workcenter gates basalt -->
| Gate | Status | Summary |
|---|---|---|
| ERC | pass | 0 errors, 0 warnings |
| DRC | pass | 0 errors, 0 warnings (0 unconnected, 0 parity) |
| SIM | skip | no sim/*.cir in project |
| EXPORT | pass | 4/4 outputs, 30 gerber files |

GREEN (nothing to run for: sim) on 2026-11-11: `workcenter gates` with KiCad 10.0.8, ngspice 42.
<!-- /workcenter gates basalt -->

## Simulation

<!-- workcenter decks basalt -->
<!-- /workcenter decks basalt -->
