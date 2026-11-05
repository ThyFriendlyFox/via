# {deck}

Deck: [`sim/{deck}.cir`](../../../sim/{deck}.cir). Requirements: <!-- fill: the IDs this deck verifies -->.

## Purpose

<!-- fill: the question this simulation answers, in one paragraph. -->

## Circuit

<!-- fill: the circuit as the deck models it: each element, its value, and where the value comes from (a datasheet table or figure with its revision, a measurement, or a convention). Say what the deck leaves out and why that does not change the answer. -->

## Inputs

<!-- fill: a table of each source and corner: the value, and why that value. -->

## Outputs

<!-- fill: a table of each `.meas` name, written `{deck}.<name>`, and what it measures. -->

## Expected

<!-- fill: for each output, the expected value from the nodal analysis below and the limit from the requirement. -->

## Results

| Measure | Value | Limit | Verdict |
|---|---|---|---|
| `{deck}.<name>` | <!-- fill: the number this deck prints, with its unit --> | | |

## Why it is required, and what is not

<!-- fill: why each check is required, and which checks are not required here and why. -->

## Nodal analysis

<!-- fill: the circuit solved by hand, step by step. Number each equation. Cite the source of each one: a datasheet's table, figure or equation with its revision, or the convention of electrical engineering it uses (Kirchhoff's current law at node X, Ohm's law, the RLC step response). Compare the result with the simulation. -->

## Sources

<!-- fill: a list of every datasheet, figure, table, standard and textbook this writeup cites. -->

## Re-run

```sh
workcenter sim .      # every deck, with the bounds in sim/*.expect.json
workcenter verify .   # and this writeup's numbers against the run
```
