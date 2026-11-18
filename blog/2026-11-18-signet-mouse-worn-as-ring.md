---
title: Signet, a mouse worn as a ring of flat boards
date: 2026-11-18
tags: [examples, signet, geometry, gyroscope, capacitive touch]
image: /examples/signet/card.png
---

Signet is a computer mouse you wear as a ring on your index finger. Eight small circuit boards sit round the finger, each soldered to the next along its edge. Turning your hand moves the cursor, and your thumb scrolls and clicks. We wanted an example of what people can make with Via, small enough to wear.

![Signet v0.5 from the thumb's side: eight black tiles in a closed ring, the radio module on top, the six stripes of the scroll strip on the right](/examples/signet/card.png "Signet v0.5, rendered from the thumb's side")

Via is our set of tools and checks for AI agents that design boards. We are Team Reagent, the electrical engineers who make Via. We wrote Signet's brief, and an AI agent designed every board with Via. We read its work, its checks and its mistakes. [The Signet page](/examples/signet) shows the ring, and [`examples/ring-mouse`](examples/ring-mouse/README.md) holds its files.

## Flat boards round a round finger

Via makes rigid boards, so the ring is a polygon of flat tiles. Picture a pencil with six flat sides. Each side touches the circle inside it at one point, and the corners stand out. Walk round the pencil and you turn at each corner, 360 degrees in all. More sides give smaller turns and smaller bumps. Round a 20 mm circle, a regular hexagon's corners stand 1.55 mm out, and an octagon's 0.82 mm. The gap shrinks roughly with the square of the number of sides.

One rule from school geometry sets the widths. From any corner, the two sides that meet there touch the circle at the same distance. Call that distance the corner's tangent length, `t`. A tile's width is the sum of its two corners' tangent lengths. Each corner turns the ring by `2 atan(t/R)`, where `R` is the circle's radius.

Signet's tiles touch a 20.0 mm cylinder, room for a 19.4 mm finger in a 0.3 mm liner. The radio tile holds a Bluetooth module 7.99 mm wide with its courtyard, the keep-clear zone round a part. So that tile is the widest, 13.2 mm, and its two corners turn 66.9 degrees each. The other six corners turn 37.7 degrees each.

## Turning a hand into cursor motion

Walk outward on a turning merry-go-round and you feel a push sideways, the Coriolis effect. Inside a gyroscope chip, a tiny mass on springs vibrates back and forth. When the chip turns, that sideways push moves the mass in proportion to the turn rate. Electrodes sense the motion as a change in capacitance. Navid Yazdi, Farrokh Ayazi and Khalil Najafi review such sensors in "Micromachined Inertial Sensors," Proceedings of the IEEE, 1998.

Signet's motion tile carries an LSM6DSL, an accelerometer and a gyroscope in one chip. The cursor code reads only the gyroscope's turn rate. That tile sits 66.85 degrees round the ring from the radio tile. So the firmware turns each reading back by that angle. A turn of the hand left or right then moves the cursor across. Pointing up or down moves it up or down, and a roll moves nothing.

A mouse reports motion in counts, small steps the computer scales into pixels. A gyroscope at rest still reads some noise, and a resting hand trembles. So the firmware treats every rate under 3 degrees a second as zero, a dead band. Past the dead band, the cursor moves 20 counts for each degree the hand turns. The cursor moves only while the thumb rests on the scroll strip. Lifting the thumb works like lifting a desk mouse off its pad. Seven host tests check this code on a computer.

## A scroll strip read like a three-phase motor

A thumb near a copper stripe adds capacitance: the stripe holds more charge at the same voltage. The radio's touch controller charges a stripe, then pours that charge into a 10 nF capacitor. It counts the pours until that capacitor reaches a set voltage. A bigger cup fills a bucket in fewer trips, so a thumb makes the count fall.

The touch tile carries six stripes, each 1.2 mm wide, their centers 1.55 mm apart. They are wired A B C A B C. A thumb covers several stripes. As it slides, the three channels rise and fall in turn, a third of a cycle apart. The three currents in a three-phase motor follow the same pattern.

The Clarke transform from power engineering turns three such signals into a pair that points at an angle. Edith Clarke of General Electric set it out in "Circuit Analysis of A-C Power Systems" (Wiley, 1943). The firmware forms `2A - B - C` and `√3 (B - C)`. That is her pair up to a constant factor. Their angle is the thumb's place within one cycle of three stripes, 4.65 mm.

Every quarter cycle, 1.16 mm of travel, is one scroll detent, one click of a wheel. A touch starts when the three signals sum to 120 counts and ends below 80. That gap keeps a thumb at the threshold from flickering. Eight host tests slide a modeled thumb along the strip.

![The radio tile seen from above: the motion tile with the name and the light on the left, the module in the middle, the six stripes of the scroll strip on the right](/examples/signet/top.png "The radio tile and its two neighbors")

## How the design went

Our first ask named "a compact board", so the agent drew flat boards. It drew the face of a signet ring, 22 mm across with 45 parts, then a flat ring-shaped board. We stopped both: the circuit belongs on the ring's surface. Via's process now has the agent state a product's form before its first design file.

The versions came from a loop. In each pass the agent judged the last version against a checklist, then made the next. In v0.2 it turned every face black. In v0.3 it moved the status light out from under the thumb.

In the third pass the agent measured the assembly and found an error in every assembly picture. The radio tile's two joints stood 1.3 mm open, their solder drawn in the air. Every tile had touched the finger at its middle, and that breaks the tangent rule beside a wider tile. The agent had read the gap as the shape of the solder. In v0.4 it closed the ring. Now `ring.py` stops if two neighbors miss their shared corner by more than 0.005 mm. Via's loop skill now adds a fresh reviewer, which Signet's loop lacked.

For v0.5 we asked for more sections, for a smoother ring. Each extra tile turns the ring less at each corner and leaves each tile less room. Eight tiles leave the five small ones 6.83 mm. Nine would leave 5.8 mm, too narrow for a SOT-23 package between two joints.

The agent's first radio tile, 12.7 mm wide, fitted every courtyard, and the routing software left 18 links open. Its capacitors, 0.6 mm long, had no room beside them for vias, the plated holes down to ground. At 13.2 mm the agent put filled vias inside their pads. It wrote the last short links into the design file itself.

In v0.5 all eight tiles pass the checks of their wiring and copper, and the export of fab files. The radio tile keeps two warnings: the module's printed outline runs past the tile's edge. The gauge tile halves the cell's voltage for the radio to read. Its simulation held all three limits in 52 runs across the parts' tolerances.

## What is open

Nobody has ordered a Signet. The firmware folder holds the scroll decoder and the air mouse, with no Bluetooth code yet. Neither has run on a ring. The radio module's hookup is not yet checked against ST's datasheet. Nobody has measured the antenna's range on a hand; ST tuned it for free space. The cell holds about 20 mAh, and nobody has measured the ring's draw. Its pouch reaches 1.6 mm past its tile. Nobody has tested the solder joints' strength. [The v0.5 README](examples/ring-mouse/v0.5/README.md) lists every open item.

Next we would like to try a cell that fits inside its tile. Then we want to order a first ring and measure it on a hand.
