---
title: Rosetta, a controller whose knob picks the console
date: 2026-11-18
tags: [examples, rosetta, usb, sensors, batteries]
image: /examples/rosetta/card.png
---

Rosetta is one game controller for a PS4, a PS5, an Xbox, a Switch or anything over Bluetooth. You pick the console with a five-position knob that sits where an Xbox 360 pad has its guide button. We asked for Rosetta to show what Via can make. Via is our kit for designing checked circuit boards. An AI agent designed this one with Via's tools, skills and gates.

![Rosetta v0.3 from above at an angle: a green board in a controller's outline with two thumbsticks, a small screen, the knob, the D-pad, the face buttons and two USB-C ports](/examples/rosetta/card.png "Rosetta v0.3, rendered by KiCad")

We're Team Reagent, the engineers who make Via. We wrote the brief, and we read the agent's work along with its checks and its mistakes. Version 0.1 had the sticks and the triggers on cables. For v0.2 we sent a picture of an Xbox 360 controller's main board and asked for one like it. The v0.3 brief asked for wireless play, a screen, lights around the sticks and turbo. [Rosetta's page](/examples/rosetta) shows the result in 3D, with 176 parts on six copper layers.

## How one knob becomes one number

The knob is a rotary switch with five stops. Behind it, six 1 kΩ resistors run in a chain from 3.3 V to ground. Each stop touches one of the joints between them, at 5/6, 4/6, 3/6, 2/6 or 1/6 of the supply. A chain like this is a voltage divider. Horowitz and Hill cover it in chapter 1 of *The Art of Electronics*, 3rd edition, published by Cambridge University Press in 2015.

An MCP3208, a 12-bit converter, reads the joint's voltage as one of 4096 steps. It uses the same 3.3 V as its reference. That makes the reading a ratio, so any error in the supply cancels out. Between stops, a 100 kΩ resistor pulls the reading close to zero, and the firmware takes that to mean no console.

The agent's first pull-down was 1 MΩ. The converter's input can leak 1 µA, and by Ohm's law that's 1 V across 1 MΩ. That's enough to read as a console. The simulation showed the problem, and the pull-down became 100 kΩ. Six simulation decks now run every resistor across its 1% tolerance, 370 runs in all. Each stop stays within 0.04 of full scale of its target, and the thresholds are 0.0833 away.

## How a console knows its controller

A USB device only sends data when the host asks for it. Here the host is the console, and it polls the controller on a fixed schedule. When a device plugs in, the host reads its device descriptor, a short table that holds a vendor number and a product number. The USB Implementers Forum defines it in chapter 9 of the [USB 2.0 Specification](https://www.usb.org/document-library/usb-20-specification), which came out in 2000.

Rosetta's firmware gives each USB mode the vendor and product numbers of that console's own controller. The host only reads them when a device connects, so turning the knob makes Rosetta disconnect and come back as a new device.

A PS4, a PS5 and an Xbox also send a challenge that only a licensed controller can answer. Rosetta's second USB-C port takes a licensed controller to act as a donor. The RP2040 runs a second USB port in software and relays each challenge to the donor. The modes for those three consoles rely on this relay, and nobody has tried it on a console yet.

Turbo depends on polling too. The firmware assumes every console polls at least every 8 ms. The fastest turbo is 20 presses a second, with the button 25 ms down and 25 ms up. Each half lasts at least three polls, so the console sees every press. The agent kept the timing fixed and regular, and it declined to build timing meant to slip past a game's detection.

## How a stick and a trigger become numbers

A classic thumbstick holds two potentiometers, one for each axis. Each one is a resistive track with a sliding contact that rubs along it. Wear from that rubbing is a common cause of stick drift, where the stick reports movement when nobody's touching it.

A Hall sensor doesn't need a contact. In 1879 Edwin Hall passed a current along gold leaf in a magnetic field, and a small voltage appeared across the leaf at right angles to the current. He reported it that year in a paper titled "On a New Action of the Magnet on Electric Currents," in the [American Journal of Mathematics](https://doi.org/10.2307/2369245). The voltage grows with the field, so a Hall sensor turns a magnet's distance into a voltage.

The stick footprint takes ALPS's RKJXV122400R, the potentiometer stick in PlayStation and Xbox pads. Hall sticks made for the same holes go in too. Each trigger is meant to carry a magnet over a DRV5055 Hall sensor on the board. Like the knob's, the sensor's output is a ratio of 3.3 V.

## How the cell charges and is counted

A lithium-ion cell charges in two phases. First the charger pushes a fixed current, and the cell's voltage climbs. Near full, at about 4.2 V for most cells, the charger holds the voltage steady and lets the current taper off. TI's datasheet for the BQ25895 charger, SLUSC88, describes this as constant current, then constant voltage.

On Rosetta the BQ25895 charges at up to 2.5 A. A 120 Ω resistor caps what it draws from a 5 V USB-C charger at 2.96 A. The firmware turns off the charger's 9 V and 12 V modes, because the same 5 V also feeds the donor controller. With a flat cell, the charger runs Rosetta straight from the cable as a wired controller.

The cell's voltage falls as it empties, but the electronics need a steady 3.3 V. A linear regulator can only take voltage away. The one on v0.1 needed about 3.66 V in to give 3.3 V out at 1 A. The cell spends the last part of its charge below that. Version 0.3 uses a TPS63001 buck-boost converter instead. A buck-boost stores energy in an inductor and releases it at a higher or lower voltage. Erickson and Maksimović cover it in *Fundamentals of Power Electronics*, and the 2nd edition came out from Kluwer Academic in 2001. On Rosetta the TPS63001 holds 3.3 V with the cell down to 2.5 V.

Charge is current times time, so a 3000 mAh cell can give 3 A for an hour. A 10 mΩ resistor in the cell's negative lead drops 25 mV at 2.5 A. The BQ27441 gauge tracks the cell's charge by coulomb counting. It measures the voltage across that resistor and adds it up over time.

![Rosetta v0.3 from the back: the ESP32 module at the top edge, the RP2040, the shift registers, and the power parts beside the white battery connector](/examples/rosetta/bottom.png "The back of Rosetta v0.3, where the electronics sit")

## How the design went

Each version is one Python file, `design.py`, and Via's tools turn it into a routed KiCad project. Then four checks run, for the electrical rules, the design rules, simulation and the fabrication files.

In v0.2 a 3D render showed a back paddle floating off the board. No check had reported it, because the checks read only the outline's bounding box. On four layers, every route left two to six of the RP2040's connections open. The agent drew links by hand for four routes before it moved to six layers. In [mistake M136](ee-agent-kit/MISTAKES.md) it logged the lesson that a chip failing route after route needs more room.

Version 0.3 grew to 176 parts. At first, each stick's ring of eight LEDs ran into the stick's rectangular body. Turning the ring by half a step, 22.5 degrees, cleared all eight. After a 12-pass route, six power links were still open at the charger, the gauge and the buck-boost. Their pins sit on a 0.5 mm pitch, which is too tight for a 0.4 mm power track. The agent drew a short, narrow neck out of each of those pins, and it drew three more links by hand.

The last run printed `GREEN with 5 warnings`. All five are silkscreen outlines of the two USB-C sockets and the radio module, which overhang on purpose.

## What is open

No Rosetta board has been made. The firmware has the decision code for the knob, turbo and the charger's setup, each with host tests. It doesn't have the USB descriptors and reports for each console yet. The software USB host, the relay and the Bluetooth stacks aren't in it either. The gauge hasn't been told the cell's capacity. Nobody has checked the inductors' saturation currents against the worst-case peaks. The triggers' magnets and pivots aren't designed yet. [The v0.3 README](examples/universal-controller/v0.3/README.md) lists every open item.

Next we want the agent to write the USB side of the firmware for one console. After that, we want to test the relay on a built board with a donor controller and a console.
