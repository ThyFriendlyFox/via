# Gates report — Lark v0.1

`workcenter gates <board> --report docs/gates.md` for each of the 4 boards, from this version's
folder, on 2026-11-17, with KiCad 10.0.8, ngspice 42 and FreeRouting 1.9.0. Each board's raw results
are in its `build/gates.json`. Every board is GREEN. `--strict` fails on 12 warnings:

- DRC, 3: the silkscreen past the board's edge. On the brain, the C6 module's outline (2) round its
  antenna, which stands past the mast's edge by design; on the driver, L2's outline at the neck's
  edge.
- SIM, 9: 7 decks whose parts are resistors and capacitors with no temperature term (`dim_filter`,
  `rail_vbus` and `vbus_sense` on the driver; `en_delay`, `ntc_divider` and `rail_3v3` on the brain;
  `mic_supply` on the ear), so no measure moves between 0 and 85 C; the ear's frequency plan, which
  names no resonance, since its supply is an RC filter with none; and ngspice's "source stepping
  failed" in `hv9961_model`, whose operating point then meets every datasheet row it is held to.

## driver

<!-- workcenter gates lark_driver -->
| Gate | Status | Summary |
|---|---|---|
| ERC | pass | 0 errors, 0 warnings |
| DRC | pass | 0 errors, 1 warnings (0 unconnected, 0 parity) |
| SIM | pass | 7 decks, 252 corner runs, 0 failures, 4 warnings |
| EXPORT | pass | 4/4 outputs, 24 gerber files |

GREEN with 5 warnings on 2026-11-17: `workcenter gates` with KiCad 10.0.8, ngspice 42.
<!-- /workcenter gates lark_driver -->

## light

<!-- workcenter gates lark_light -->
| Gate | Status | Summary |
|---|---|---|
| ERC | pass | 0 errors, 0 warnings |
| DRC | pass | 0 errors, 0 warnings (0 unconnected, 0 parity) |
| SIM | pass | 2 decks, 10 corner runs, 0 failures |
| EXPORT | pass | 4/4 outputs, 22 gerber files |

GREEN on 2026-11-17: `workcenter gates` with KiCad 10.0.8, ngspice 42.
<!-- /workcenter gates lark_light -->

## brain

<!-- workcenter gates lark_brain -->
| Gate | Status | Summary |
|---|---|---|
| ERC | pass | 0 errors, 0 warnings |
| DRC | pass | 0 errors, 2 warnings (0 unconnected, 0 parity) |
| SIM | pass | 3 decks, 181 corner runs, 0 failures, 3 warnings |
| EXPORT | pass | 4/4 outputs, 24 gerber files |

GREEN with 5 warnings on 2026-11-17: `workcenter gates` with KiCad 10.0.8, ngspice 42.
<!-- /workcenter gates lark_brain -->

## ear

<!-- workcenter gates lark_ear -->
| Gate | Status | Summary |
|---|---|---|
| ERC | pass | 0 errors, 0 warnings |
| DRC | pass | 0 errors, 0 warnings (0 unconnected, 0 parity) |
| SIM | pass | 1 decks, 74 corner runs, 0 failures, 2 warnings |
| EXPORT | pass | 4/4 outputs, 22 gerber files |

GREEN with 2 warnings on 2026-11-17: `workcenter gates` with KiCad 10.0.8, ngspice 42.
<!-- /workcenter gates lark_ear -->

## Simulation

Every bound is in its board's `sim/<deck>.expect.json`, with the source of its number beside it, and each deck runs at its board's corners (`sim/corners.json`). The README's Simulation table says what each deck holds.

### driver

<!-- workcenter decks lark_driver -->
| Deck | What it simulates | Bounds | Corner runs | Result |
|---|---|---|---|---|
| `sim/bus_valley.cir` | Lark: the bus through each 120 Hz valley at full power, 120 V rms | 5 | 37 | pass |
| `sim/dim_filter.cir` | Lark: DIM_W through R5, R6 and C7 to the warm controller's LD pin (DIM_C, R7, R8, C8 are the same) | 4 | 8 | 1 warning |
| `sim/hv9961_model.cir` | Lark: the HV9961 model (models/hv9961.lib) against its datasheet's rows (DS20005588B, p.3-4) | 6 | none: the model against its datasheet's rows, stated at 25 C | 1 warning |
| `sim/led_channel.cir` | Lark: one LED channel at full current, the warm string (U1, Q1, D1, L2, R1, C14) | 5 | 127 | pass |
| `sim/mb10s_model.cir` | Lark: the MB10S model (models/mb10s.lib) against onsemi's MB10S rev | 1 | none: the model against its datasheet's row, stated at 25 C | pass |
| `sim/rail_vbus.cir` | Lark: VBUS's impedance where the LED channels draw their switching current (PROCESSES.md P30) | 1 | 72 | 1 warning |
| `sim/vbus_sense.cir` | Lark: VBUS to the brain's ADC through R13, R14 (1 Meg each, 1206: 200 V each) and R15 (24.9k), filtered by C16 (10 n) | 4 | 8 | 1 warning |
<!-- /workcenter decks lark_driver -->

### light

<!-- workcenter decks lark_light -->
| Deck | What it simulates | Bounds | Corner runs | Result |
|---|---|---|---|---|
| `sim/led_model.cir` | Lark: the LED model against its datasheet | 3 | none: the model against its datasheet's rows, which are stated at 25 C and 85 C and swept in the deck | pass |
| `sim/led_string.cir` | Lark: a string of 8 LEDs at full current, the voltage the driver's buck must stay over | 2 | 10 | pass |
<!-- /workcenter decks lark_light -->

### brain

<!-- workcenter decks lark_brain -->
| Deck | What it simulates | Bounds | Corner runs | Result |
|---|---|---|---|---|
| `sim/en_delay.cir` | Lark: the 2 chips' enables at power-up | 3 | 74 | 1 warning |
| `sim/ntc_divider.cir` | Lark: the LED disc's temperature at the C6's ADC. RT1 on the disc, a 100k NTC (Murata NCP15WF104F03RC: B25/50 4250 K, +-1 %; R25 +-1 %), from NTC to GND; R8 (10k, 0.1 %) up to +3V3; C16 (100 n) at the pin | 4 | 74 | 1 warning |
| `sim/rail_3v3.cir` | Lark: +3V3's impedance where the brain draws it (PROCESSES.md P30) | 1 | 33 | 1 warning |
<!-- /workcenter decks lark_brain -->

### ear

<!-- workcenter decks lark_ear -->
| Deck | What it simulates | Bounds | Corner runs | Result |
|---|---|---|---|---|
| `sim/mic_supply.cir` | Lark: the microphones' supply | 2 | 74 | 1 warning |
<!-- /workcenter decks lark_ear -->
