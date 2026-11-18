---
title: Wyvern, a Snapdragon module on one flat board
date: 2026-11-18
tags: [examples, wyvern, usb-c, power, signal-integrity]
image: /examples/wyvern/card.png
---

Wyvern is a Snapdragon development board laid out like a Teensy. A Qualcomm QCS6490 module, which runs Linux or Android, shares the board with an RP2350 microcontroller on 30 pins. We're Team Reagent, and we asked for Wyvern as an example of what Via, our board design workcenter, can make. An AI agent designed it with Via's tools, skills and checks, and we read its work and its mistakes.

![Wyvern v0.2 in 3D: a black board with a large gray module at one end, a USB-C receptacle and five buttons at the other, and a row of gold pins along each long edge](/examples/wyvern/card.png "Wyvern v0.2, rendered by KiCad, with a stand-in body for the module")

The board is 76.2 x 53.34 mm, and one USB-C cable powers it and carries USB 3. On [the Wyvern page](/examples/wyvern) you can turn it around in 3D.

## Why the Snapdragon comes on a module

A Snapdragon needs fast memory, flash and power chips around it, on a board with microvias. Via's generator can't draw a board like that, because it only makes through vias. So the processor comes on a module, a small board that holds it and all of those parts.

Vantron's VOSM6490 carries the QCS6490 with 8 GB of LPDDR5 memory and 64 GB of flash. The 45 x 45 mm module follows version 1.2 of SGET's Open Standard Module specification, OSM for short. We like that an OSM module has no connector. Its 662 flat pads solder to the board like any other chip's. The agent drew Wyvern's copy of those pads from the standard's contact map, and they match Antmicro's open footprint.

## Why a fast pair needs 90 ohm

Each bit on the module's 5 Gbps USB port lasts 200 ps, about 3 cm of travel along the board, and the edges between bits are shorter still. At that speed the pairs act as transmission lines, and wherever their impedance changes, part of the wave reflects back and blurs the bits behind it. USB pairs are built for 90 ohm across the two traces.

Wyvern's pairs are 0.25 mm traces 0.15 mm apart, 0.21 mm above a ground plane. The agent sized them with IPC-2141's formula for edge-coupled microstrip, which is the simple one. E. Hammerstad and Ø. Jensen published more exact formulas for a single microstrip line in 1980. Their paper, "Accurate Models for Microstrip Computer-Aided Design", is in the IEEE MTT-S International Microwave Symposium Digest. Brian C. Wadell's *Transmission Line Design Handbook*, from Artech House in 1991, collects formulas like these for coupled lines too.

The bottom layer's pairs need a ground plane under them as well, which is why Wyvern has six layers instead of four.

## A plug that fits both ways

The board pulls each of its two CC pins down through 5.1 kohm, and the charger pulls CC up from its end. A charger doesn't turn on its 5 V until it sees that pull-down. Whichever CC pin finds the pull-up tells the board which way up the plug went in. The USB Implementers Forum sets these rules in its USB Type-C Cable and Connector Specification.

On Wyvern a TI HD3SS3220 holds those pull-downs even while its own supply is off. The board needs that, since it runs off the same port it's reading and nothing on it has power until the charger turns on its 5 V.

The module has one SuperSpeed lane, and the HD3SS3220 switches it to whichever side of the receptacle the plug is using. One pair in that lane has its two wires swapped so it can stay on one layer. We like this trick, and it works because a USB 3 receiver detects a swapped pair during link training and flips it back.

## The converter's negative input resistance

The module wants its supply between 4.8 and 5.2 V, at up to 3 A. A cable carrying 3 A can lose up to half a volt of a charger's 5 V, so a TI TPS552892 buck-boost converter makes a steady 5.0 V for it. Via simulates it at every corner, with each part at the limits of its tolerance, and gets 4.86 to 5.17 V.

The part of the power design we find most interesting is how that converter looks from the cable's side. It holds its output steady, so it draws the same power whatever its input voltage is. When the input voltage goes up, the input current goes down. To the supply that's a negative resistance, equal to minus the input voltage squared divided by the power. At 4.0 V in and the charger's full 3 A, it comes to minus 1.33 ohm.

The cable's inductance and the board's input capacitors form a resonant circuit, and at its resonant frequency the input's impedance peaks. R. D. Middlebrook set the rule for this in 1976. His paper is "Input Filter Considerations in Design and Application of Switching Regulators", from the IEEE Industry Applications Society Annual Meeting. The rule is to keep the filter's impedance well under the converter's input impedance, since otherwise the two can oscillate.

Wyvern meets the rule with a damper across the input. It's a 22 uF capacitor, C42, in series with a 0.33 ohm resistor, R45. The resistor absorbs energy at the resonance, and the capacitor keeps DC out of the resistor. [The simulation](examples/snapdragon-dev-board/v0.2/sim/vbus_pdn.cir) puts the peak at 0.26 ohm at 37 kHz, and at 0.51 ohm at the worst corner. Both are under the converter's 1.33 ohm. The first version had no damper, and its margin was only 0.13 ohm.

Via's frequency plan marks a band from 12.8 to 122 kHz around the cable's resonance. None of the first 10 harmonics of the plan's three clocks lands in that band. The converter runs in forced PWM to keep it that way, switching at a fixed 746 kHz at any load. In power-save mode its rate would sweep through the band as the load changed.

## How the design went

We asked for Wyvern on 2026-11-11, because we wanted a compact board like a Teensy with a Snapdragon on it. The first version, v0.1, put a Snapdragon 845 module on three sockets above a 60.96 x 30.48 mm stick. Its first route left the RP2350's core pins bare, boxed in by capacitors and the crystal. The agent moved those parts and drew the core rail in the design file.

On 2026-11-12 we looked at v0.1. It had loose ends in power, data and routing, and to us it looked like two boards slapped together. So we asked for one flat board with a QCS6490 module soldered straight on.

For v0.2 the agent read the module's pin tables with a script, and the script lost three of the 17 power pads. The agent read the 64 pads the board uses off the datasheet's pages instead. That one's M163 in our [list of mistakes](ee-agent-kit/MISTAKES.md).

Routing was the hard bit, and it took seven tries. The first two cut the 5 V plane under the module into three pieces. A copper track laid along the line of the module's middle pads held the plane together.

The last run of Via's four checks came back GREEN with 16 warnings. The schematic and board checks found no errors and no unconnected nets. Seven simulation decks ran 397 times at their corners with no failures. [The gates report](examples/snapdragon-dev-board/v0.2/docs/gates.md) explains each warning.

## What is still open

Nobody has made a Wyvern board yet, and it has no firmware. TI publishes no model of the TPS552892, so we haven't simulated its control loop. The input's 42 uF of ceramic capacitors is about 21 uF at 5 V of DC bias. That's still more than the 10 uF USB Type-C allows a device at plug-in, unless the device limits its inrush current. The SuperSpeed lane has no clamps against static discharge. Vantron gives no thermal figures for the module, so we don't know yet how hot it runs. [The v0.2 README](examples/snapdragon-dev-board/v0.2/README.md) lists every open item.

For v0.3 we want a load switch that limits the inrush, and static clamps on the SuperSpeed lane.
