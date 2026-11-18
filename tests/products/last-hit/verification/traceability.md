# Traceability

The rows of Last Hit v0.16's `verification/traceability.md` (commit 2f04cfc of the project) that
`product.json` beside this folder names, copied as they stand there.

| ID | Check | Evidence | Measured | Verdict |
|---|---|---|---|---|
| REQ-ESD-01 | — | [esd_port](simulations/esd_port/README.md) | D2 takes the edge; 9.0 A left for the pin, 37 % of the 24.1 A without D2; the MCU's own limit is unpublished | OPEN |
| REQ-PRT-03 | `master_switch.t_trip_us <= 1000` | [master_switch](simulations/master_switch/README.md) | 11.73 | PASS |
| REQ-PRT-06 | — | [calculations](calculations/README.md#the-cells-protection) | F1, F2 open from 2.5 A within 5 s (the fuse's table); 4 A in 5.8 ms and a hard short in 24 to 49 µs (its typical curve), before the BQ29728's 6.4 ms | PASS |
| REQ-ENV-06 | — | [calculations](calculations/README.md#environment) | not tested | OPEN |
