---
title: Wyvern, a Snapdragon module on one flat board
date: 2026-11-18
tags: [examples, wyvern, usb-c, power, signal-integrity]
image: /examples/wyvern/card.png
---

Wyvern is a Snapdragon development board laid out like a Teensy, the small microcontroller board. A Qualcomm QCS6490 module for Linux or Android shares the board with an RP2350 microcontroller on 30 pins. We, Team Reagent, asked for it as an example of what Via, our board design workcenter, can make. An AI agent designed it with Via's tools, skills and checks. We read its work and its mistakes.

![Wyvern v0.2 in 3D: a black board with a large gray module at one end, a USB-C receptacle and five buttons at the other, and a row of gold pins along each long edge](/examples/wyvern/card.png "Wyvern v0.2, rendered by KiCad, with a stand-in body for the module")

The board is 76.2 x 53.34 mm. One USB-C cable powers it and carries USB 3. [The Wyvern page](/examples/wyvern) shows it in 3D.

## Why the Snapdragon comes on a module

A Snapdragon chip needs fast memory, flash and power chips around it. Those parts sit on a board with microvias, which are tiny laser-drilled holes between neighboring layers. Via's generator can only draw through vias, the kind drilled through every layer. So the processor comes on a module, a small board that holds it and all of those parts.

Vantron's VOSM6490 carries the QCS6490 with 8 GB of LPDDR5 memory and 64 GB of flash. The 45 x 45 mm module follows version 1.2 of SGET's Open Standard Module specification, OSM for short. An OSM module has no connector. The 662 flat pads on its underside solder to the board like any other chip's. The agent drew Wyvern's copy of those pads from the standard's contact map, and they match Antmicro's open footprint.

## Why a fast pair needs 90 ohm

The module's USB port runs at 5 Gbps, so each bit lasts 200 ps. In that time a signal moves about 3 cm along the board. The edges, where each bit switches, are shorter still.

A trace that's long compared with an edge acts as a transmission line, and the signal travels down it as a wave. The trace's shape sets the impedance the wave meets. Wherever that impedance changes, part of the wave reflects back and blurs the bits behind it.

USB sends each signal on a pair of traces, one carrying the mirror image of the other. The receiver reads the difference, so noise that lands on both traces cancels. USB pairs are built for 90 ohm across the two traces. A wider trace or a thinner insulating layer under it lowers that impedance. Moving the two traces closer lowers it too.

Wyvern's pairs are 0.25 mm traces 0.15 mm apart, 0.21 mm above a ground plane. The agent sized them with IPC-2141's formula for edge-coupled microstrip, which means two traces side by side over a plane. E. Hammerstad and Ø. Jensen published more exact formulas for a single microstrip line in 1980. Their paper, "Accurate Models for Microstrip Computer-Aided Design", is in the IEEE MTT-S International Microwave Symposium Digest. Brian C. Wadell's *Transmission Line Design Handbook*, from Artech House in 1991, collects formulas like these for coupled lines too.

The bottom layer's pairs need a ground plane as well, so Wyvern has six layers instead of four.

## A plug that fits both ways

A USB-C plug goes in either way up, so the receptacle has two mirrored rows of contacts. One wire in the cable, CC, lets each end work out how the plug sits. The charger pulls CC up, and the board pulls each of its two CC pins down through 5.1 kohm. The charger doesn't turn on its 5 V until it detects that pull-down. Whichever CC pin finds the pull-up tells the board which way up the plug is. The USB Implementers Forum sets these rules in its USB Type-C Cable and Connector Specification.

On Wyvern, a TI HD3SS3220 holds those pull-downs even when its own supply is off. So a charger can power up the board even when nothing on it is powered yet.

The module has one SuperSpeed lane, the fast USB 3 pairs that send and receive. The HD3SS3220 switches that lane to whichever side of the receptacle the plug is using. One pair has its two wires swapped so it can stay on one layer. A USB 3 receiver detects a swapped pair during link training and flips it back.

## The converter's negative input resistance

The module's supply has to stay between 4.8 and 5.2 V, at up to 3 A. A cable carrying 3 A can lose up to half a volt of a charger's 5 V. So a TI TPS552892 buck-boost converter, which can step voltage down or up, makes a steady 5.0 V. Via simulates it at every corner, with each part at the limits of its tolerance, and gets 4.86 to 5.17 V.

This converter holds its output steady, so it draws the same power whatever its input voltage is. If the input voltage goes up, the input current goes down, which is the opposite of what a resistor does. To the supply it looks like a negative resistance, equal to minus the input voltage squared divided by the power. At 4.0 V in and the charger's full 3 A, that's minus 1.33 ohm.

The cable's inductance and the board's input capacitors form a resonant circuit. At its resonant frequency, the input's impedance peaks. R. D. Middlebrook set the rule for this in 1976. His paper is "Input Filter Considerations in Design and Application of Switching Regulators", from the IEEE Industry Applications Society Annual Meeting. The rule is to keep the filter's impedance well under the converter's input impedance. Otherwise the two can oscillate.

Wyvern meets the rule with a damper across the input. It's a 22 uF capacitor, C42, in series with a 0.33 ohm resistor, R45. The resistor absorbs energy at the resonance, and the capacitor keeps DC out of the resistor. [The simulation](examples/snapdragon-dev-board/v0.2/sim/vbus_pdn.cir) puts the peak at 0.26 ohm at 37 kHz, and at 0.51 ohm at the worst corner. Both are under the converter's 1.33 ohm. The first version had no damper, and its margin was only 0.13 ohm.

A converter puts out energy at its switching frequency and at the whole multiples of it, its harmonics. Via's frequency plan marks a band from 12.8 to 122 kHz around the cable's resonance. None of the first 10 harmonics of the three clocks in the plan lands in that band. The converter runs in forced PWM, which means it switches at a fixed 746 kHz at any load. In power-save mode its rate would sweep through the band as the load changed.

## How the design went

We asked for Wyvern on 2026-11-11. We wanted a compact board like a Teensy, with a Snapdragon on it. The first version, v0.1, put a Snapdragon 845 module on three sockets above a 60.96 x 30.48 mm stick. Its first route left the RP2350's core pins bare, boxed in by capacitors and the crystal. The agent moved those parts and drew the core rail in the design file.

On 2026-11-12 we looked at v0.1. It had loose ends in power, data and routing, and it looked like two boards slapped together. So we asked for one flat board with a QCS6490 module soldered straight on.

For v0.2 the agent read the module's pin tables with a script, and the script lost three of the 17 power pads. So the agent read the 64 pads the board uses off the datasheet's pages instead. It's in our [list of mistakes](ee-agent-kit/MISTAKES.md) as M163.

Routing took seven tries. The first two cut the 5 V plane under the module into three pieces. A copper track laid along the line of the module's middle pads held the plane together.

The last run of Via's four checks came back GREEN with 16 warnings. The schematic and board checks found no errors and no unconnected nets. Seven simulation decks ran 397 times at their corners, with no failures. [The gates report](examples/snapdragon-dev-board/v0.2/docs/gates.md) explains each warning.

## What is still open

Nobody has made a Wyvern board, and it has no firmware yet. TI publishes no model of the TPS552892, so its control loop isn't simulated. Ceramic capacitors lose capacitance under voltage, so the input's 42 uF is about 21 uF at 5 V. USB Type-C allows a device 10 uF at plug-in, unless it limits its inrush current. The SuperSpeed lane has no clamps against static discharge. Vantron gives no thermal figures for the module. [The v0.2 README](examples/snapdragon-dev-board/v0.2/README.md) lists every open item.

For v0.3 we want a load switch that limits the inrush, and static clamps on the SuperSpeed lane.
