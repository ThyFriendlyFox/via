# Verification package

<!-- fill: one paragraph: which board and version this package verifies, at which commit, and who asked. -->

This package states what the board must do, under which conditions, and
the evidence that it does. `workcenter verify .` checks it: every
requirement has a source and a row in the traceability table, every
simulation has a writeup, and every number in a table is the number a
fresh ngspice run gives.

## How to read it

| Folder | What it holds |
|---|---|
| [`requirements/`](requirements/README.md) | the operating profile, the expected and unexpected conditions, and the numbered requirements with their sources |
| [`system/`](system/README.md) | the block diagram and how charge moves in each mode |
| [`simulations/`](simulations/) | one folder per circuit: inputs, outputs, expected and measured values, and the nodal analysis |
| [`calculations/`](calculations/README.md) | the hand calculations that no simulation covers |
| [`traceability.md`](traceability.md) | each requirement, its evidence, the measured value and the verdict |

## Verdicts

<!-- fill: the counts of PASS, FAIL and OPEN from `workcenter verify .`, then one line per FAIL: what fails, by how much, and the proposed fix. Name each requirement the owner withdrew or restated, with the decision's date. -->

## Re-run

```sh
workcenter verify .          # the package against a fresh run of sim/*.cir
workcenter verify . --strict # a FAIL or an OPEN requirement also fails the run
```
