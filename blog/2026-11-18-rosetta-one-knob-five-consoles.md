---
title: Rosetta, a controller whose knob picks the console
date: 2026-11-18
tags: [examples, rosetta, usb, sensors, batteries]
image: /examples/rosetta/card.png
---

Rosetta is one game controller for a PS4, a PS5, an Xbox, a Switch or anything over Bluetooth. You pick the console with a five-position knob that sits where an Xbox 360 pad has its guide button. Via is our kit for designing checked circuit boards, and we asked for Rosetta to show what it can make. An AI agent designed it with Via's tools, skills and gates.

![Rosetta v0.3 from above at an angle: a green board in a controller's outline with two thumbsticks, a small screen, the knob, the D-pad, the face buttons and two USB-C ports](/examples/rosetta/card.png "Rosetta v0.3, rendered by KiCad")

We're Team Reagent, the engineers who make Via. We wrote the brief and read all of the agent's work, its checks and its mistakes too. Version 0.1 had the sticks and the triggers on cables. For v0.2 we sent a picture of an Xbox 360 controller's main board and asked for one like it. The v0.3 brief asked for wireless play, a screen, lights around the sticks and turbo. [Rosetta's page](/examples/rosetta) shows the result in 3D, with 176 parts on six copper layers.

## How one knob becomes one number

The knob is a rotary switch with five stops that taps a plain voltage divider. Six 1 kΩ resistors run in a chain from 3.3 V to ground. Each stop touches one of the joints between them, at 5/6, 4/6, 3/6, 2/6 or 1/6 of the supply. Horowitz and Hill cover the divider in chapter 1 of *The Art of Electronics*, 3rd edition, published by Cambridge University Press in 2015.

An MCP3208, a 12-bit converter, reads that joint's voltage as one of 4096 steps. The neat part is that it uses the same 3.3 V as its reference, so the reading is a ratio and any error in the supply cancels out. Between stops, a 100 kΩ resistor pulls the reading close to zero, and the firmware takes that to mean no console.

The agent's first pull-down was 1 MΩ. The converter's input can leak 1 µA, and 1 µA through 1 MΩ is 1 V, which is enough to read as a console. The simulation showed the problem, and the pull-down became 100 kΩ. Six simulation decks now run every resistor across its 1% tolerance, 370 runs in all. Each stop stays within 0.04 of full scale of its target, and the thresholds are 0.0833 away.

## How a console knows its controller

Over USB the console is the host, and the controller only sends data when the console polls it, on a fixed schedule. When a controller connects, the console reads a vendor number and a product number from its device descriptor. The USB Implementers Forum defines that descriptor in chapter 9 of the [USB 2.0 Specification](https://www.usb.org/document-library/usb-20-specification), which came out in 2000.

The way Rosetta changes consoles is the part of the design we like best, because there's so little to it. The firmware gives each USB mode the vendor and product numbers of that console's own controller. A console only reads them when a device connects, so turning the knob makes Rosetta disconnect and come back as a new device.

A PS4, a PS5 and an Xbox also send a challenge that only a licensed controller can answer. For those, Rosetta's second USB-C port takes a licensed controller to act as a donor. The RP2040 runs a second USB port in software and relays each challenge to the donor. The modes for those three consoles rely on this relay. It's the part of Rosetta we're least sure of, because nobody has tried it on a console yet.

Turbo depends on polling too. The firmware assumes every console polls at least every 8 ms. The fastest turbo is 20 presses a second, with the button 25 ms down and 25 ms up, so each half lasts at least three polls and the console sees every press. The agent kept the timing fixed and regular, and it declined to build timing meant to slip past a game's detection.

## How a stick and a trigger become numbers

A classic thumbstick holds two potentiometers, one for each axis, and wear on their sliding contacts is a common cause of stick drift. A Hall sensor has no contact to wear. In 1879 Edwin Hall passed a current along gold leaf in a magnetic field, and a small voltage appeared across the leaf at right angles to the current. He reported it that year in a paper titled "On a New Action of the Magnet on Electric Currents," in the [American Journal of Mathematics](https://doi.org/10.2307/2369245). The voltage grows with the field, so a Hall sensor turns a magnet's distance into a voltage.

Rosetta's stick footprint takes ALPS's RKJXV122400R, the potentiometer stick in PlayStation and Xbox pads, and Hall sticks made for the same holes go in too. Each trigger is meant to carry a magnet over a DRV5055 Hall sensor on the board. Like the knob's, the sensor's output is a ratio of 3.3 V.

## How the cell charges and is counted

The BQ25895 charges the cell the usual lithium-ion way, at constant current and then at constant voltage near full, about 4.2 V for most cells. TI's datasheet for the charger, SLUSC88, describes both phases.

On Rosetta it charges at up to 2.5 A, and a 120 Ω resistor caps what it draws from a 5 V USB-C charger at 2.96 A. The firmware turns off the charger's 9 V and 12 V modes, because the same 5 V also feeds the donor controller. With a flat cell, the charger runs Rosetta straight from the cable as a wired controller.

The linear regulator on v0.1 needed about 3.66 V in to give 3.3 V out at 1 A, and the cell spends the last part of its charge below that. Version 0.3 uses a TPS63001 buck-boost converter instead, which holds 3.3 V with the cell down to 2.5 V. Erickson and Maksimović cover buck-boost converters in *Fundamentals of Power Electronics*, and the 2nd edition came out from Kluwer Academic in 2001.

The BQ27441 gauge tracks the cell's charge by coulomb counting. It adds up, over time, the voltage across a 10 mΩ resistor in the cell's negative lead, and at 2.5 A that resistor drops 25 mV.

![Rosetta v0.3 from the back: the ESP32 module at the top edge, the RP2040, the shift registers, and the power parts beside the white battery connector](/examples/rosetta/bottom.png "The back of Rosetta v0.3, where the electronics sit")

## How the design went

Each version is one Python file, `design.py`, that Via's tools turn into a routed KiCad project. Four checks then run on it, for the electrical rules, the design rules, simulation and the fabrication files.

In v0.2 a 3D render showed a back paddle floating off the board. No check had reported it, because the checks read only the outline's bounding box.

The hard bit in v0.2 was the RP2040. On four layers, every route left two to six of its connections open. The agent drew links by hand for four routes before it moved to six layers. In [mistake M136](ee-agent-kit/MISTAKES.md) it logged the lesson that a chip failing route after route needs more room.

Version 0.3 grew to 176 parts. At first, each stick's ring of eight LEDs ran into the stick's rectangular body, and turning the ring by half a step, 22.5 degrees, cleared all eight. We like that fix for how small it is. After a 12-pass route, six power links were still open at the charger, the gauge and the buck-boost. Their pins sit on a 0.5 mm pitch, which is too tight for a 0.4 mm power track. The agent drew a short, narrow neck out of each of those pins, and it drew three more links by hand.

The last run printed `GREEN with 5 warnings`. All five are silkscreen outlines of the two USB-C sockets and the radio module, which overhang on purpose.

## What is open

No Rosetta board has been made yet. The firmware has the decision code for the knob, turbo and the charger's setup, each with host tests. It doesn't have each console's USB descriptors and reports yet, and the software USB host, the relay and the Bluetooth stacks aren't in it either. The gauge hasn't been told the cell's capacity. We don't know yet whether the inductors' saturation currents cover the worst-case peaks, because nobody has checked them. The triggers' magnets and pivots aren't designed yet. [The v0.3 README](examples/universal-controller/v0.3/README.md) lists every open item.

Next we want the agent to write the USB side of the firmware for one console. After that, we want to test the relay on a built board with a donor controller and a console.
