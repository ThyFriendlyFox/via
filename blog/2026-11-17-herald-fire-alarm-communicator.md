---
title: Herald: answering a fire panel's phone call in firmware
date: 2026-11-17
tags: [examples, herald, dtmf, signal processing, fire alarms]
image: /examples/herald/card.png
---

Herald is a board designed to sit beside a fire alarm panel and pass on its reports. Many panels report by dialing a monitoring station on a phone line, and Herald stands in for that line. The reports then leave over LTE-M, a low-power form of the 4G cell network, or Wi-Fi. We made it as an example for Via, our toolkit for circuit boards designed by AI.

![Herald's routed board in 3D: a red board with the LTE-M modem, a nano SIM holder, the ESP32-S3 module, a relay, five status lights and black screw terminals along its front edge](/examples/herald/card.png "Herald v0.1, rendered by KiCad")

We are Team Reagent, the electrical engineers who build Via. An AI agent designed Herald with Via's tools, skills and checks. We asked for a compact board and read the agent's work, checks and mistakes. The board is 84.4 by 64 mm, with four copper layers and 127 parts. [Herald's page](/examples/herald) shows it in 3D.

## How a fire panel places a call

A landline is a pair of wires from the phone exchange. While the phone rests, the exchange holds about 48 V across them. Lifting the handset closes a loop, and the exchange senses the current and plays dial tone. Engineers call this loop start signaling, and the lifted state "off hook". A fire panel's built-in dialer takes the line the same way.

Herald takes the exchange's place. Two transistors feed the line from the panel's 24 V output, limited to 20 to 28 mA. A 47 ohm resistor turns that current into a voltage for the ESP32-S3, the board's microcontroller. In simulation, off hook reads 0.776 V or more, and on hook 0.040 V or less.

Herald's design then plays dial tone: 350 and 440 Hz together. After the dialer dials, Herald answers with a handshake: 1400 then 2300 Hz, 100 ms each. The dialer sends its message as touch-tone digits. Herald confirms a good message with a "kissoff" tone, 1400 Hz for 800 ms.

The message follows Contact ID, the alarm maker Ademco's format, now standard SIA DC-05. Its 16 digits hold an account, a zone and an event code, where 110 means fire alarm. The last digit makes the sum of all 16 a multiple of 15, with each 0 counted as 10. A wrong digit breaks the sum, so Herald sends no kissoff, and the dialer sends the message again. The agent took these values from open-source receivers and makers' documents, not the DC-05 text.

## Eight tones for 16 keys

Each key on a touch-tone phone sounds two tones at once. That scheme is DTMF, for dual-tone multi-frequency. The rows use 697, 770, 852 and 941 Hz; the columns use 1209, 1336, 1477 and 1633 Hz. ITU-T Recommendation [Q.23](https://www.itu.int/rec/T-REC-Q.23/en) (1988) fixes these frequencies. Its companion, [Q.24](https://www.itu.int/rec/T-REC-Q.24/en), says what a receiver must accept and refuse.

Herald's limits come from Table A-1 of Q.24. A dBm is a power level against one milliwatt. The decoder must take tones from 0 down to -25 dBm, a span of about 300 to 1. A tone 1.5 % off frequency must pass, and one 3.5 % off must not. A 40 ms digit must count, and a 23 ms burst must not.

## How the firmware hears one tone

Picture a child on a swing. Pushes in time with the swing send it higher. Pushes out of time cancel out. Gerald Goertzel's algorithm works like that swing, tuned to one frequency. He published it as "An Algorithm for the Evaluation of Finite Trigonometric Series". It appeared in The American Mathematical Monthly in 1958 ([doi:10.2307/2310304](https://doi.org/10.2307/2310304)).

Each new sample updates two running numbers with one multiply, by a constant set from the target frequency. If the signal holds that frequency, the numbers grow, as the swing does. If not, they stay small. At the end, one formula turns the two numbers into the power at that frequency.

Herald has no DTMF chip; its decoder, [`dtmf.c`](examples/fire-alarm-communicator/v0.1/firmware/src/dtmf.c), runs eight of these filters, one per tone. Each window holds 205 samples at 8 kHz, or 25.6 ms. That length separates tones about 39 Hz apart, and the closest DTMF pair is 73 Hz apart.

The usual tool, the fast Fourier transform or FFT, measures every frequency in a window. Herald needs eight. Goertzel costs one multiply per sample per tone: 205 times eight is 1640. A 256-point FFT takes 1024 steps, each with a complex multiply worth four ordinary ones. Its answers also fall on a 31.25 Hz grid that misses every DTMF tone. Goertzel tunes to each tone exactly.

Host tests play all 16 keys through the decoder, plus tones it must refuse.

## Telling an alarm from a cut wire

Other panels report by closing a relay contact, a switch. If a bare switch's wire breaks, the circuit looks like an open switch, the quiet state. Fire systems add an end-of-line resistor across the switch, at its far end.

Each of Herald's three inputs has a 4.7 kilohm pull-up to 3.3 V. The end-of-line resistor matches it, so a whole loop reads about half. A closed switch pulls the reading near zero. A cut wire leaves only the pull-up, and the reading rises to 3.3 V.

Four simulations test the cases at 0 and 50 °C and at each part's tolerance limits. The worst readings are 0.151 V closed, 1.555 to 1.798 V whole and 3.186 V cut. Each stays 0.2 V or more from the firmware's thresholds.

## How the design went

The agent writes the whole board as one Python file, [`design.py`](examples/fire-alarm-communicator/v0.1/design.py). Via makes it a KiCad project, routes it, then checks electrical rules, design rules, simulation and fabrication files. Simulation covers eight circuit files, called decks, in 573 runs across temperature and part tolerance. On the last run, all four checks passed, with seven warnings for white printing at the edge.

In six of the eight rounds, a reviewer new to the board read its pictures against one fixed prompt. The reviewer's list became the next round's work. The board shrank from 96 to 84.4 mm wide, and the terminals turned black.

The ESP32 makes tones as fast pulses, and two resistor-capacitor filters smooth them into a sine wave. The first filter used 10 kilohm resistors and 10 nF capacitors. The simulation showed 28 mV on the line, where the deck asks for 62 mV, about -25 dBm. Behind 10 kilohms, the line's 600 ohm load kept little of the tone. The agent changed the filter to 1 kilohm and 68 nF. The deck now reads 191 to 204 mV peak at 350 Hz, at every corner.

FreeRouting, the open-source router, connected all but three nets, and the agent wrote those tracks into `design.py`. Two mistakes with keep-outs, areas where no copper may run, cost extra routes. In M137, a keep-out drawn after placement covered a surge diode's pad, and the route left one net open. In M138, keep-outs banned vias, plated holes through every layer, but the agent checked only the back for pads. Our [list of mistakes](ee-agent-kit/MISTAKES.md) records both, with the process step each one broke.

## What is open

Nobody has built a Herald board or priced its parts. The firmware for the inputs, the hook, DTMF and Contact ID has run only in tests on a computer. The agent has not written the tone player, the modem's commands or the relay's watchdog. We have not chosen a protocol to the station yet.

A communicator that a fire alarm system relies on carries a listing to UL 864 or a local equivalent. UL 864 is the standard for control units and accessories for fire alarm systems. A listing means an approved lab tested the product to it. Herald has none: no surge test, no supervision timing check, no listing. [The README](examples/fire-alarm-communicator/v0.1/README.md) lists every open item.

For v0.2, we would like to win back the 3 mm of height the last review found. If a panel needs more than about 23 V on the line, we would add a 48 V converter.
