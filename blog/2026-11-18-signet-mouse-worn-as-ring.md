---
title: Signet, a mouse worn as a ring of flat boards
date: 2026-11-18
tags: [examples, signet, geometry, gyroscope, capacitive touch]
image: /examples/signet/card.png
---

Signet is a computer mouse you wear as a ring on your index finger. It's made of eight small circuit boards that sit around the finger, each one soldered to the next along an edge. Turning your hand moves the cursor, and your thumb scrolls and clicks. We wanted an example of something people can make with Via that's small enough to wear.

![Signet v0.5 from the thumb's side: eight black tiles in a closed ring, the radio module on top, the six stripes of the scroll strip on the right](/examples/signet/card.png "Signet v0.5, rendered from the thumb's side")

We're Team Reagent, the electrical engineers who make Via, our set of tools and checks for AI agents that design boards. We wrote Signet's brief. An AI agent designed every board with Via, and we read all of its work, the checks and the mistakes included. [The Signet page](/examples/signet) shows the ring, and its files are in [`examples/ring-mouse`](examples/ring-mouse/README.md).

## Fitting flat boards around a finger

Via makes rigid boards, so the ring has to be a polygon of flat tiles. Each tile touches the circle inside it at one point, and its corners stick out past the circle. The ring turns a little at each corner, and the turns add up to 360 degrees. With more sides, each turn gets smaller and so does the bump at each corner. Around a 20 mm circle, a regular hexagon's corners stick out 1.55 mm and an octagon's stick out 0.82 mm. The bump shrinks roughly with the square of the number of sides.

We like how little math the tile widths need, since they all come from one rule in school geometry. The two sides that meet at a corner touch the circle at the same distance from that corner. That distance is the corner's tangent length, `t`, and a tile's width is just the sum of the tangent lengths at its two corners. Each corner turns the ring by `2 atan(t/R)`, where `R` is the circle's radius.

Signet's tiles touch a 20.0 mm cylinder, which leaves room for a 19.4 mm finger inside a 0.3 mm liner. The radio tile carries a Bluetooth module that's 7.99 mm wide with its courtyard, so it's the widest tile, at 13.2 mm. Its two corners turn 66.9 degrees each. That leaves 37.7 degrees for each of the other six corners.

## Turning a hand into cursor motion

Signet's motion tile carries an LSM6DSL, an accelerometer and a gyroscope in one chip, and the cursor code only reads the gyroscope's turn rate. Inside a gyroscope chip, a tiny mass on springs vibrates back and forth. When the chip turns, the Coriolis effect pushes the mass sideways in proportion to the turn rate, and electrodes read that as a change in capacitance. Navid Yazdi, Farrokh Ayazi and Khalil Najafi reviewed sensors like this in "Micromachined Inertial Sensors," a 1998 paper in Proceedings of the IEEE.

The motion tile sits 66.85 degrees around the ring from the radio tile, so the firmware rotates each reading back by that angle. After that, turning your hand left or right moves the cursor across the screen. Pointing it up or down moves the cursor up or down, and a roll doesn't move it.

A gyroscope reads some noise even when it's still, and a resting hand trembles a little. So the firmware treats any rate under 3 degrees a second as zero, and past that dead band the cursor moves 20 counts for each degree the hand turns.

The cursor only moves while the thumb rests on the scroll strip, so lifting the thumb works like lifting a desk mouse off its pad. Seven host tests check this code on a computer.

## A scroll strip read like a three-phase motor

The radio's touch controller charges a stripe, moves that charge into a 10 nF capacitor, and repeats, counting the transfers until the capacitor reaches a set voltage. A thumb near the stripe adds capacitance, so each transfer carries more charge and the count falls.

The touch tile has six stripes, each 1.2 mm wide, with their centers 1.55 mm apart. They're wired A B C A B C, and a thumb covers several of them at once. As it slides, the three channels rise and fall in turn, a third of a cycle apart, in the same pattern as the three currents in a three-phase motor.

So the firmware can read the strip with a tool from power engineering, which is our favorite trick in the ring. The Clarke transform turns three signals like these into a pair that gives an angle. Edith Clarke of General Electric set it out in "Circuit Analysis of A-C Power Systems," which Wiley published in 1943. The firmware forms `2A - B - C` and `√3 (B - C)`, which is her pair scaled by a constant. The angle of that pair gives the thumb's position within one cycle of three stripes, a span of 4.65 mm.

Each quarter cycle, 1.16 mm of travel, is one scroll step, the same as one click of a mouse wheel. A touch starts when the three signals add up to 120 counts and ends when they fall below 80. The gap between those two keeps a thumb that's right at the threshold from flickering on and off. Eight host tests slide a modeled thumb along the strip.

![The radio tile seen from above: the motion tile with the name and the light on the left, the module in the middle, the six stripes of the scroll strip on the right](/examples/signet/top.png "The radio tile and its two neighbors")

## How the design went

Our first ask just said "a compact board," so the agent drew flat boards. It drew the face of a signet ring, 22 mm across with 45 parts, and then a flat board shaped like a ring. We stopped both, because the circuit belongs on the ring's surface. Via's process now has the agent state a product's form before it writes the first design file.

The versions after that came out of a loop. On each pass the agent judged the last version against a checklist and then made the next one. It turned every face black in v0.2, and in v0.3 it moved the status light out from under the thumb.

On the third pass the agent measured the assembly and found an error in every assembly picture. The radio tile's two joints were 1.3 mm open, and the pictures showed their solder floating in the air. Every tile had been placed touching the finger at its middle, and next to a wider tile that breaks the tangent rule. The agent had taken the gap for the shape of the solder.

In v0.4 it closed the ring, and since then `ring.py` stops if two neighboring tiles miss their shared corner by more than 0.005 mm. Signet's loop had no fresh reviewer, and Via's loop skill now adds one.

For v0.5 we asked for more sections to make the ring smoother. That's a trade, because each extra tile makes the turn at each corner smaller but also leaves each tile less room. With eight tiles, the five small ones are 6.83 mm wide. Nine would bring them down to 5.8 mm, which is too narrow to fit a SOT-23 package between two joints.

The radio tile was the hard bit. The agent's first one was 12.7 mm wide, and every courtyard fit, but the router left 18 links open. The capacitors on that tile are 0.6 mm long, and there was no room next to them for vias down to ground. On the 13.2 mm tile the agent put filled vias inside the capacitors' pads, and it wrote the last short links into the design file itself.

In v0.5 all eight tiles pass the wiring and copper checks and the fab file export. The radio tile still has two warnings, because the module's printed outline runs past the tile's edge. The gauge tile halves the cell's voltage so the radio can read it, and its simulation stayed inside all three of its limits in 52 runs across the parts' tolerances.

## What is open

There's a lot about Signet we don't know yet. Nobody has ordered one. The firmware folder has the scroll decoder and the air mouse but no Bluetooth code yet, and neither one has run on a ring. The radio module's hookup hasn't been checked against ST's datasheet. ST tuned the antenna for free space, and nobody has measured its range on a hand. The cell holds about 20 mAh, and the ring's current draw hasn't been measured. The cell's pouch sticks out 1.6 mm past its tile, and nobody has tested how strong the solder joints are. [The v0.5 README](examples/ring-mouse/v0.5/README.md) lists every open item.

Next we'd like to try a cell that fits inside its tile. After that we want to order a first ring and measure it on a hand.
