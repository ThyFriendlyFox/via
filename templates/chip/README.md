# __TOP__

fill: 1 paragraph: what the chip does, for whom, and what proves that it works.

## Spec

| Requirement | Limit | Source |
|---|---|---|
| fill: the clock | fill: 50 MHz | fill: where the number comes from |

## Pins

| Pin | Direction | What it is |
|---|---|---|
| `clk` | in | the 1 clock |
| `rst` | in | synchronous reset, active high |

## How to test

fill: what a bench on a board does to see the chip work through its pins.

## Decisions

fill: each choice that is not obvious, with its reason.

## Commands

```
workcenter next .               the 1 next step
workcenter chip gates . --strict    the 10 gates; the last line is the verdict
```

`build/` holds everything a run writes. It is not committed.
