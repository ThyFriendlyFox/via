# Gates report — Signet v0.2

`workcenter gates <tile> --report docs/gates.md` for each of the 6 tiles, from this
version's folder, on 2026-11-11, with KiCad 10.0.8, ngspice 42 and FreeRouting 1.9.0. Each tile's
raw results are in its `build/gates.json`. Every tile is GREEN. `--strict` fails on 2 warnings, both
on the radio tile: the module's silkscreen outline runs past the tile's fingertip edge, where its
antenna end sits.

## signet_radio

<!-- workcenter gates signet_radio -->
| Gate | Status | Summary |
|---|---|---|
| ERC | pass | 0 errors, 0 warnings |
| DRC | pass | 0 errors, 2 warnings (0 unconnected, 0 parity) |
| SIM | skip | no sim/*.cir in project |
| EXPORT | pass | 4/4 outputs, 24 gerber files |

GREEN with 2 warnings (nothing to run for: sim) on 2026-11-11: `workcenter gates` with KiCad 10.0.8, ngspice 42.
<!-- /workcenter gates signet_radio -->

## signet_touch

<!-- workcenter gates signet_touch -->
| Gate | Status | Summary |
|---|---|---|
| ERC | pass | 0 errors, 0 warnings |
| DRC | pass | 0 errors, 0 warnings (0 unconnected, 0 parity) |
| SIM | skip | no sim/*.cir in project |
| EXPORT | pass | 4/4 outputs, 24 gerber files |

GREEN (nothing to run for: sim) on 2026-11-11: `workcenter gates` with KiCad 10.0.8, ngspice 42.
<!-- /workcenter gates signet_touch -->

## signet_clicks

<!-- workcenter gates signet_clicks -->
| Gate | Status | Summary |
|---|---|---|
| ERC | pass | 0 errors, 0 warnings |
| DRC | pass | 0 errors, 0 warnings (0 unconnected, 0 parity) |
| SIM | skip | no sim/*.cir in project |
| EXPORT | pass | 4/4 outputs, 24 gerber files |

GREEN (nothing to run for: sim) on 2026-11-11: `workcenter gates` with KiCad 10.0.8, ngspice 42.
<!-- /workcenter gates signet_clicks -->

## signet_cell

<!-- workcenter gates signet_cell -->
| Gate | Status | Summary |
|---|---|---|
| ERC | pass | 0 errors, 0 warnings |
| DRC | pass | 0 errors, 0 warnings (0 unconnected, 0 parity) |
| SIM | skip | no sim/*.cir in project |
| EXPORT | pass | 4/4 outputs, 24 gerber files |

GREEN (nothing to run for: sim) on 2026-11-11: `workcenter gates` with KiCad 10.0.8, ngspice 42.
<!-- /workcenter gates signet_cell -->

## signet_power

<!-- workcenter gates signet_power -->
| Gate | Status | Summary |
|---|---|---|
| ERC | pass | 0 errors, 0 warnings |
| DRC | pass | 0 errors, 0 warnings (0 unconnected, 0 parity) |
| SIM | pass | 1 decks, 52 corner runs, 0 failures |
| EXPORT | pass | 4/4 outputs, 24 gerber files |

GREEN on 2026-11-11: `workcenter gates` with KiCad 10.0.8, ngspice 42.
<!-- /workcenter gates signet_power -->

## Simulation: signet_power

<!-- workcenter decks signet_power -->
| Deck | What it simulates | Bounds | Corner runs | Result |
|---|---|---|---|---|
| `sim/vbat_sense.cir` | The cell's gauge on the power tile: R2 (1M) from the cell to VBAT_SENSE, R3 (1M) to ground, C5 (100n) holding the node for the radio's ADC (PC3, ADC1_IN4) | 3 | 52 | pass |
<!-- /workcenter decks signet_power -->

## signet_motion

<!-- workcenter gates signet_motion -->
| Gate | Status | Summary |
|---|---|---|
| ERC | pass | 0 errors, 0 warnings |
| DRC | pass | 0 errors, 0 warnings (0 unconnected, 0 parity) |
| SIM | skip | no sim/*.cir in project |
| EXPORT | pass | 4/4 outputs, 24 gerber files |

GREEN (nothing to run for: sim) on 2026-11-11: `workcenter gates` with KiCad 10.0.8, ngspice 42.
<!-- /workcenter gates signet_motion -->
