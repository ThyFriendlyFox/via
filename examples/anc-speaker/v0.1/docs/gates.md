# Gates report: hush

## hush

<!-- workcenter gates hush -->
| Gate | Status | Summary |
|---|---|---|
| ERC | pass | 0 errors, 0 warnings |
| DRC | pass | 0 errors, 4 warnings (0 unconnected, 0 parity) |
| SIM | pass | 7 decks, 986 corner runs, 0 failures, 2 warnings |
| EXPORT | pass | 4/4 outputs, 24 gerber files |

GREEN with 6 warnings on 2026-11-11: `workcenter gates` with KiCad 10.0.8, ngspice 42.
<!-- /workcenter gates hush -->

## Simulation: hush

<!-- workcenter decks hush -->
| Deck | What it simulates | Bounds | Corner runs | Result |
|---|---|---|---|---|
| `sim/anc_hum.cir` | Hush: a 150 Hz hum in time | 4 | 227 | pass |
| `sim/anc_loop.cir` | Hush: the noise-cancelling loop, closed, at full depth (RV1 at its end) | 8 | 230 | pass |
| `sim/anc_margin.cir` | Hush: the loop's gain and phase margins at full depth (RV1 at its end) | 5 | 227 | pass |
| `sim/anc_music.cir` | Hush: music through the loop | 5 | 225 | pass |
| `sim/pam_model.cir` | The PAM8302A model (sim/models/pam8302a.lib) against its datasheet (Diodes DS41333 Rev | 3 | none: the fitted model against its datasheet's rows, which are stated at 25 C | pass |
| `sim/rail_5v.cir` | Hush: the +5V rail's impedance at U5's VDD pin, for the frequency plan (PROCESSES.md P30) | 1 | 77 | pass |
| `sim/tlv9061_model.cir` | TI's TLV9062 model (library/ti/tlv9062.lib, Rev | 7 | none: TI's model against its datasheet's rows, which are stated at 25 C | 2 warnings |
<!-- /workcenter decks hush -->
