# Requirements

## Operating profile

<!-- fill: what the device is for, who uses it, how often, for how long, and what it must never do. -->

## Expected conditions

<!-- fill: a table of every condition the board meets in normal use, with its range and source: each power source (for USB: a USB-C charger with and without Power Delivery, a Battery Charging 1.2 port, a computer's USB 2.0 port, a long thin cable), each use mode, storage, temperature, altitude. -->

## Unexpected conditions

<!-- fill: a table of every abnormal condition the board must survive or stop safely: a faulty charger at 9 to 20 V, a live plug, a shorted or open load, a cell at its cut-off, an electrostatic discharge, a drop, a pressure change. For each: what the board must do (survive, stop, ignore). -->

## Electrical requirements

Each requirement has an ID, a limit, the source of the limit, a
verification method, and the clause it would be inspected under.

- **Method** is one of analysis, simulation, examination,
  demonstration, test.
- **Inspection** names the standard and clause, for example RTCA
  DO-160G section 17 (voltage spike) or MIL-STD-461G CS118 (ESD).
- A requirement the owner restated or added names the decision in its
  **Source**: "the owner's decision of 2026-11-06", with the date written
  year, month, day. `workcenter verify` checks the date.

| ID | Requirement | Limit | Source | Method | Inspection |
|---|---|---|---|---|---|
| REQ-PWR-01 | <!-- fill: the requirement --> | | | | |

## Withdrawn

A requirement the owner withdraws moves from the tables above to this
table, with the date of the decision, the decision in the owner's terms,
and who made it. `workcenter verify` names each withdrawn ID, leaves it
out of the counts, and fails on a traceability row or an expect bound that
still names it. A withdrawn ID is never given to a new requirement.

| ID | Date | Decision | By |
|---|---|---|---|

## Standards

<!-- fill: a table of each standard named above: its number, title, revision, and the clauses this package uses. Say where a standard is licensed and was not read. -->
