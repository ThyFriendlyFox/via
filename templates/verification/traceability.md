# Traceability

One row per requirement.

- **Check** is a comparison on a deck's measure, for example
  `vbus_hotplug.hp_worst <= 30 V`. `workcenter verify` recomputes it and
  the verdict must agree. A requirement that no deck measures has `—`.
- **Evidence** links the writeup or the calculation.
- **Verdict** is PASS, FAIL or OPEN. OPEN means the evidence does not
  exist yet, for example a bench test.
- A requirement the owner withdrew has no row: it is in the requirements'
  Withdrawn table.

| ID | Check | Evidence | Measured | Verdict |
|---|---|---|---|---|
| REQ-PWR-01 | <!-- fill --> | | | OPEN |
