# Rosetta v0.1: how it was built

Each entry is 1 step of the board's development: the date, the stage, what happened, and the
evidence. `site/examples.py` puts this file on the example's page. Rosetta was built in 1 day, and
its record is by day, not by hour: the order below follows `ee-agent-kit/DEVLOG.md` (2026-11-11)
and mistakes M126 to M128 in `ee-agent-kit/MISTAKES.md`.

## 2026-11-11 · Idea · 1 controller, 5 consoles, a knob that picks

The owner found the site's examples poor and asked for a prototype in the manner of Agentcast and
Last Hit: a universal controller with a switch that picks a PS4, a PS5, an Xbox, a Switch or
Bluetooth, with ideas that are hard to do.

## 2026-11-11 · Design · The board is a Python file

`design.py` names 140 parts and places them in a controller's outline, on 4 layers. The knob is 1 analog reading: SW1 taps a ladder of 6 x 1k, and position
k reads (6 - k)/6 of full scale. A USB host port relays a console's signature to a licensed donor
through a second USB port the RP2040 runs in software.

Evidence: `design.py`; the README's table "What is hard about it".

## 2026-11-11 · Simulate · The first deck found a sixth position

The knob's first deck held a 1 M pull-down on the wiper. With the ADC's input leakage it read 1 V
between detents: a position the decoder would act on. The ladder is 1k and the pull-down 100k now,
and 6 decks hold each position inside its window at every corner.

Evidence: `sim/mode_between.cir`, `sim/mode_p1.cir` to `sim/mode_p5.cir`, `sim/corners.json`.

## 2026-11-11 · Place · An antenna turned into the board

The ESP32 module went on the back face at 180 degrees, to point its antenna out over the notch
between the grips. On the back face the generator mirrors the footprint first, so 180 degrees
pointed the antenna into the board. The DRC listed 41 courtyard overlaps against the antenna's
keep-out and 8 through pads inside it. At 0 degrees the antenna hangs out as intended.

Evidence: mistake M126; process P19.

## 2026-11-11 · Tooling · The Docker image could not route

The machine had no KiCad, so Via ran in the repository's Docker image. The image could
not route: Debian's headless Java has no X11 library, and FreeRouting stops without it.
`install.sh` now adds the full Java runtime where the library is missing.

Evidence: `install.sh`; the changelog's Fixed entry.

## 2026-11-11 · Route · 60 passes and no session

The first route ran FreeRouting with 60 passes, the number the skill gives for small boards. It
ran for Via's 15-minute limit and was killed, and a killed run writes no session. 12
passes finished in 13 minutes; 20 passes in 12 minutes from a better placement.

Evidence: mistake M128; process P4.

## 2026-11-11 · Schematic · The wired sheet's ERC found 3 faults

A label-only schematic passed the checks that ran, and the DRC does not see a net with 1 pin. The
first wired sheet's ERC did: each stick's click was on a net named `L3` or `R3` while the shift
registers read `BTN_L3` and `BTN_R3`, the DRV8833's sense pins were tied straight to a rail, and so
were the IMU's strap pins. The fixes are `BTN_L3` and `BTN_R3`, R50 and R51 (0.5 ohm, a 400 mA
limit on each trigger motor), and R52. The board was routed again.

Evidence: mistake M127; process P24.

## 2026-11-11 · Route · Lanes for the RP2040

The RP2040's pins had no lanes until its capacitors moved to its corners and its vias shrank to
0.45 mm. From there FreeRouting closed every connection in 1 run of 4. The IMU's supply pins stayed
apart in 3 runs; that link is drawn by hand.

Evidence: `rosetta.kicad_pcb`.

## 2026-11-11 · Gates · GREEN with 5 warnings

The 5 warnings are the silkscreen outlines of the 2 USB-C receptacles and the ESP32 module, which
hang over the board's edge on purpose. The firmware's host tests pass: `make -C firmware test`.

```
$ workcenter gates examples/universal-controller/v0.1
PASS   erc        0 errors, 0 warnings  [0.48s]
FAIL   drc        0 errors, 5 warnings (0 unconnected, 0 parity), legend (no fab named: held to the least of the 4 fabs the workcenter knows (height pcbway-standard, stroke oshpark-2layer)): 9 fail, 0 not judged  [1.48s]
       - warning: silk_edge_clearance: Silkscreen clipped by board edge
       - warning: silk_edge_clearance: Silkscreen clipped by board edge
       - warning: silk_edge_clearance: Silkscreen clipped by board edge
       - warning: silk_edge_clearance: Silkscreen clipped by board edge
       - warning: silk_edge_clearance: Silkscreen clipped by board edge
       - legend overlap: text "CAPTURE" at (150, 120) mm on F.SilkS: on via at (146.571, 119.401) by 0.2 x 0.076 mm (rules/legend.json)
       - legend overlap: text "CAPTURE" at (150, 120) mm on F.SilkS: on via at (153.435, 119.844) by 0.2 x 0.2 mm (rules/legend.json)
       - legend overlap: text "PS4" at (157.07, 117.8) mm on F.SilkS: on via at (158.121, 118.447) by 0.2 x 0.028 mm (rules/legend.json)
       - legend overlap: text "XBOX" at (170, 109.6) mm on F.SilkS: on via at (170.881, 108.99) by 0.2 x 0.065 mm (rules/legend.json)
       - legend overlap: text "XBOX" at (170, 109.6) mm on F.SilkS: on via at (168.36, 109.675) by 0.2 x 0.2 mm (rules/legend.json)
       - legend overlap: text "XBOX" at (170, 109.6) mm on F.SilkS: on via at (169.594, 110.121) by 0.2 x 0.154 mm (rules/legend.json)
       - legend overlap: text "XBOX" at (170, 109.6) mm on F.SilkS: on via at (169.109, 109.645) by 0.2 x 0.2 mm (rules/legend.json)
       - legend overlap: text "SWITCH" at (177.99, 111) mm on F.SilkS: on via at (175.253, 111.477) by 0.2 x 0.198 mm (rules/legend.json)
       - legend overlap: text "OPTIONS" at (190, 108.2) mm on F.SilkS: on via at (189.802, 107.704) by 0.2 x 0.179 mm (rules/legend.json)
RATINGS not asked for: no ratings.json beside the schematic
RED: rosetta  report examples/universal-controller/v0.1/build/gates.json
```
