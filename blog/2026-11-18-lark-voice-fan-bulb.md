---
title: Lark, a voice-controlled ceiling-fan bulb on four boards
date: 2026-11-18
tags: [examples, lark, led drivers, flicker, mains safety]
image: /examples/lark/card.png
---

Lark is a ceiling-fan light bulb designed for voice control, with the speech recognition inside the bulb. It screws into the fan's E26 socket and runs on 120 V mains. We asked for it after our Matter smart-home devices didn't work well. An AI agent designed its four circuit boards with Via, our tools and checks for KiCad board design.

![Lark's light disc in 3D: 16 LEDs on a ring round 3 slots, on an aluminum disc](/examples/lark/card.png "The light disc of Lark v0.1, one of its four boards, drawn from its design file")

We wrote the brief and read what the agent made, along with its check results and the mistakes it logged. No Lark has been built, and its voice and radio firmware isn't written.

## Why an LED needs a set current

Above a certain voltage, a small rise in an LED's voltage makes a large rise in its current. Lark's LEDs drop 8.8 V to 9.6 V at 100 mA, depending on which voltage bin they come from. They drop less as they warm up. A fixed voltage would set a different current in each LED, so an LED driver controls the current instead.

The driver board rectifies the mains into a bus near 165 V. Each of its two LED strings, warm white and cool white, needs about 73 V. A buck converter steps the voltage down with a switch, a diode and a choke, which is a coil. While the switch is on, the current through the LEDs and the choke climbs. When the switch turns off, the choke keeps the current going through the diode, and it falls. The output is the input times the duty cycle, the share of time the switch is on. Erickson and Maksimović derive this in their book *Fundamentals of Power Electronics*. The 2nd edition came out from Kluwer in 2001.

Each string has a Microchip HV9961 controller. It senses the current in a 2.74 ohm resistor, then holds the switch off for 2.5 µs. [Its datasheet](examples/fan-bulb/library/microchip/HV9961-DS20005588B.pdf) says it regulates the average current, while the older HV9910B regulates the peak. The current is 0.185 times the LD pin's voltage, divided by the sense resistor, so 1.48 V on LD gives 100 mA. A third buck converter makes 3.3 V from the same bus. Its chip, a Power Integrations [LinkSwitch-TN2](examples/fan-bulb/library/power-integrations/linkswitch-tn2_family_datasheet.pdf), holds a 725 V switch and its controller.

## Steady light under turning blades

If a light pulses, the eye sees a passing fan blade at only a few places. The blades then seem to stand still or to move in steps. Brad Lehman and Arnold Wilkins describe this stroboscopic effect in "Designing to Mitigate Effects of Flicker in LED Lighting". Their paper came out in IEEE Power Electronics Magazine in 2014.

IEEE Std 1789-2015 measures flicker as percent modulation, which is the highest light minus the lowest, divided by their sum. At 120 Hz, its low-risk level is 9.6 percent.

Rectified 60 Hz mains peaks 120 times a second, and the bus sags between peaks. A buck can only lower a voltage. The HV9961 regulates up to a duty cycle of 0.75. So the bus has to stay above the highest string voltage, 77.5 V, divided by 0.75, which comes to 103.3 V. Below that, the LED current would dip 120 times a second. In simulation, 9.9 µF of bulk capacitance holds the bus's lowest point at 117.0 V at the worst corner of temperature and part tolerance.

A common way to dim LEDs is pulse-width modulation, or PWM, which switches them fully on and off fast. Under a fan, those pulses strobe too. Lark dims by lowering the steady current instead. A resistor-capacitor filter turns the brain board's 20 kHz PWM into a steady voltage on the LD pin.

## A bulb with no isolation

Lark has no isolation, the break a transformer makes between the mains and what you touch. Every node sits at mains potential, the 3.3 V logic included. The plastic housing insulates it all from a hand.

Inside the bulb, the logic can differ from the mains nets by up to 198 V. IPC-2221B, the *Generic Standard on Printed Board Design*, gives copper gaps by voltage in Table 6-1. For 151 to 250 V, it sets 0.8 mm on an outer layer beside a part's lead. On an inner layer, in solid glass-epoxy, it allows 0.2 mm. The agent wrote both into the [rule file](examples/fan-bulb/v0.1/rules/lark.kicad_dru). The design rule check, or DRC, holds every gap to them.

We asked for a DIP switch on the side to choose between Alexa and Apple Home. Its contacts would sit at mains potential under a finger. The agent chose a magnet in a slider outside the sealed housing instead, sitting over two Hall switches inside. In the Hall effect, a magnetic field pushes moving charges to one side of a thin plate, and a small voltage appears across it.

## Where the microphones go

Lark hangs base-up, so the dome's tip faces the room. Since warm air rises, the tip is also the coolest place. The agent put the two microphones there, on a 15 mm disc named the ear. Air in a shell with a small opening, a bottle for one, is a Helmholtz resonator. The air in the opening is the mass, and the air in the shell is the spring. The ear's design file puts the dome's resonance near 400 Hz, which would weaken the higher tones of speech. So each microphone's port opens through the ear to its own hole in the dome.

The microphones are 10.4 mm apart. They feed an ESP32-S3 that's meant to run Espressif's ESP-SR speech models. A two-microphone beamformer uses the delay between the microphones to favor one direction. Sound crosses 10.4 mm in about 30 µs. One sample at ESP-SR's 16 kHz is 62.5 µs, so the delay is under half a sample. ESP-SR's beamforming gains little here, since its two-microphone front end is tuned for spacings of 4 to 6.5 cm.

## How the design went

The agent tried an A15 bulb first, 47.6 mm across. Each of the driver's 56 parts fit on its own, but they didn't all fit together. We answered, "expand the design as well if it cannot fit, or use multiple dimensions of stacked boards". The housing grew to an A19, 60 mm across and 108 mm long. Its inside is a cone, a sphere and a 20 mm tube.

So Lark is four boards in two directions. The driver stands in the neck, and the aluminum light disc lies across its top. The brain board stands in the dome at 90 degrees to the driver, reaching up to the ear. Tongues on the standing boards pass through slots in the lying boards, and solder fillets join them.

The driver took the most routing work. With two layers, the FreeRouting autorouter left 26 connections open. After the move to four layers, the router's file left out the new ground plane, and 37 stayed open. Our [list of mistakes](ee-agent-kit/MISTAKES.md) records that and the spacing errors in the next fix as M207 and M208. The agent wrote code for the links the router left open, 94 track segments and 23 vias. FreeRouting routed the rest.

The simulation check also failed once, in M210. The bus deck's 9.1 W load was meant to be both strings at full current, but it was one string's worth. At the corners, one bulk capacitor carried more alternating current than its 47 mA rating. The agent added a firmware rule that warm and cool together draw at most 90 percent of one string. Now the deck's load is 8.3 W, and at the worst corner the capacitor carries 44.7 mA.

All four boards pass Via's checks, with 12 warnings between them.

## What is open

No firmware has run on a board. With the light off, the logic stays on and would draw about 0.9 W from the mains. California's Title 20 holds a state-regulated LED lamp's standby to 0.2 W. Version 0.1 doesn't handle a fan's triac dimmer, which cuts away part of each mains half-cycle. A lamp sold in the US is listed to UL 1993, and its driver to UL 8750. Neither listing has been started. [The Lark README](examples/fan-bulb/v0.1/README.md) lists every open item, and [the Lark page](/examples/lark) shows the assembly.

Next, we want to try a wake-word chip that draws a few milliwatts and wakes the voice chip. We also want to settle the microphones' spacing, then build a bulb and measure it.
