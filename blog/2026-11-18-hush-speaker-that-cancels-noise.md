---
title: Hush, a speaker that plays the inverse of what it hears
date: 2026-11-18
tags: [examples, hush, acoustics, feedback, simulation]
image: /examples/hush/card.png
---

Hush is a ring-shaped circuit board that sits on the face of a 40 mm speaker. A microphone on its hub picks up the noise in front of the cone, and the speaker plays the opposite of that noise. We asked for it as an example for Via, the kit an AI agent uses to design circuit boards. The agent designed the board, and we read its work along with its check results and its mistakes.

![Hush on its speaker, seen from above and to the side: a black ring with gold mounting holes, the cone showing through three windows, the microphone on the hub, a USB-C socket and an audio jack at the edge](/examples/hush/card.png "Hush v0.1 on its CE40-4 speaker, rendered from the design files")

## What is on the ring

The ring is 62 mm across, and its 33 mm opening sits over the cone of a Dayton Audio CE40-4. Three spokes hold a hub, and the microphone on the hub is 4 mm from the cone. Two op-amps turn the microphone's signal into the anti-noise, and a class-D amplifier drives the speaker.

We like that Hush is still a speaker. Music from a phone plays through it, and the first op-amp subtracts the music from the microphone's signal so the loop doesn't cancel it too. The board has four layers and 62 parts, and it runs no firmware. You can turn it around in 3D on [its page](/examples/hush).

## Cancelling a 150 Hz hum

The 150 Hz hum in Hush's simulation swings the air pressure by 0.2 Pa. To cancel it, the speaker has to pull the pressure at the microphone down by as much as the hum pushes it up, so the two add to zero.

Paul Lueg patented the idea in 1936. The patent is US 2,043,416, "Process of silencing sound oscillations." In it, a microphone picks up the sound, and an amplifier and loudspeaker play it back in opposite phase.

In Hush's simulation, the speaker's wave reaches the microphone upside down, at 0.90 of the hum's size. What's left is 18.8 dB below the hum, about a ninth of its pressure.

## Why low notes cancel and high notes don't

The opposite wave has to arrive in step with the noise, and a fixed delay puts it further out of step the higher the frequency. The simulation models the air between cone and microphone as a 28 µs delay, and the amplifier adds 2 µs. Those 30 µs are under 2 degrees of a cycle at 150 Hz and 16 degrees at 1.5 kHz.

Wavelength matters too, since the quiet zone around the microphone spans only a fraction of one. A wavelength is 2.3 m at 150 Hz and 23 cm at 1.5 kHz.

In the simulation, the loop cancels noise from 50 to 500 Hz, and its loop gain falls to one near 1.5 kHz. Our favorite decision on the board comes out of those numbers. A digital processor would add tens of microseconds for its converters and arithmetic, and each microsecond of delay costs about half a degree of phase at 1.5 kHz. So the agent built the loop from analog parts.

## Feedback, after Olson and May

A feedforward system has a reference microphone that hears the noise early, and an error microphone at the quiet spot that hears what's left. Feedback uses just the one microphone at the quiet spot, and the circuit plays its signal back inverted.

Sen Kuo and Dennis Morgan surveyed both kinds in "[Active noise control: a tutorial review](https://doi.org/10.1109/5.763310)," which came out in the Proceedings of the IEEE in 1999. The systems in it run adaptive filters on a DSP. Their basic method is filtered-x least mean squares, or FxLMS, which adjusts the filter at each sample to shrink the error signal. The agent chose feedback over a DSP's adaptive feedforward, which needs a second microphone and firmware.

Harry Olson and Everett May described the feedback kind in 1953. Their paper, "[Electronic sound absorber](https://doi.org/10.1121/1.1907249)," appeared in the Journal of the Acoustical Society of America. The absorber in it is a microphone, an amplifier and a loudspeaker in a feedback loop, the same loop Hush uses. The paper's abstract reports 10 to 25 dB less sound near the microphone, over three octaves of low notes.

## The price of feedback

Hendrik Bode showed the waterbed effect, where quiet from a feedback loop in one band comes with a rise in another. He published it in 1945 in his book *Network Analysis and Feedback Amplifier Design*, from Van Nostrand.

If the loop's phase reaches 180 degrees where its gain is one, the loop oscillates on its own, and in Hush that would be a whistle. Capping the rise at 6 dB guarantees a phase margin of at least 29 degrees. Hush's requirements set that cap, and they ask for a phase margin of 45 degrees.

In simulation the rise is 2.6 dB at most. At the worst corner of temperature and part tolerances it reaches 5.9 dB, which is closer to the cap than we'd like. The phase margin is 76.9 degrees at the 1.5 kHz crossing and 50.7 degrees at the worst corner.

## How the design went

The agent logged seven mistakes while it made Hush, M139 to M145 in [the list of mistakes](ee-agent-kit/MISTAKES.md). Four of them were in the simulation, where each test is a deck for the simulator ngspice.

Diodes Incorporated publishes no simulation model for the PAM8302A amplifier, so the agent wrote one, and that model gave half the datasheet's gain. In M139, the agent ran the loop decks on it before the model's own test deck, and then it redid one round of tuning.

TI's op-amp model matches its datasheet, but in the closed loop it gave false operating points. In those, an op-amp's output sat pinned at its supply, and the numbers still passed their limits. Of the seven, that's the one we think matters most. The loop decks now run a model fitted to TI's, within 0.52 dB of it up to 10 kHz. After M143, each loop deck also checks two DC voltages, so a false operating point fails.

In M142, the FreeRouting autorouter connected none of the amplifier's pins, because the chip was turned 26 degrees to follow the ring. With the chip turned square, every pin connected.

Each round, a reviewer who hadn't seen the board read its pictures and named the three worst problems. In the first round, the wave art on the back ended in the jack's peg hole. The second round found the + and - marks by the speaker's pads turned to the ring's angle, so they read as "x" and "/". The agent fixed both.

![The back of Hush: two white waves circle the ring and merge into one line, beside the words NOISE + ITS INVERSE = SILENCE, with gold rims around the windows](/examples/hush/bottom.png "The back of the ring, which faces the speaker")

The last run of the checks reads `GREEN with 6 warnings`, and the electrical and design rules checks found no errors. Four warnings are for printed lettering where the jack and the switch hang over the board's edge. The other two come from TI's model in its test deck.

Seven decks made 986 runs at the corners. The noise at the microphone drops 7.5 dB at 50 Hz and 20.4 dB at 200 Hz, and at the worst corner those drops are 3.0 and 16.9 dB.

## What is open

Nobody has ordered or built a Hush board, so every result here comes from simulation. The 4 mm from cone to microphone is an estimate from the speaker's drawing, and the corners try 3 to 5 mm. The decks model the speaker in free air, and a box behind it would raise its resonance. We don't know how far the quiet spreads beyond the microphone, because nobody has measured it. The verification package, which ties each requirement to its proof, isn't written yet. [The README](examples/anc-speaker/v0.1/README.md) lists every open item.

We want v0.2 to start with the verification package. After that, we'd like a board on a bench, with a second microphone beside the first.
