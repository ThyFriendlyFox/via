---
title: Hush, a speaker that plays the inverse of what it hears
date: 2026-11-18
tags: [examples, hush, acoustics, feedback, simulation]
image: /examples/hush/card.png
---

Hush is a ring-shaped circuit board that sits on the face of a 40 mm speaker. A microphone on its hub picks up the noise in front of the cone. The speaker then plays the opposite of that noise. We asked for it as an example for Via, the kit an AI agent uses to design circuit boards. The agent designed the board, and we read its work along with its check results and its mistakes.

![Hush on its speaker, seen from above and to the side: a black ring with gold mounting holes, the cone showing through three windows, the microphone on the hub, a USB-C socket and an audio jack at the edge](/examples/hush/card.png "Hush v0.1 on its CE40-4 speaker, rendered from the design files")

## What is on the ring

The ring is 62 mm across. Its 33 mm opening sits over the cone of a Dayton Audio CE40-4. Three spokes hold a hub, and the microphone on the hub is 4 mm from the cone. Two operational amplifiers, or op-amps, turn the microphone's signal into the anti-noise. An op-amp is the basic analog gain block. A class-D amplifier, whose outputs switch fully on and off, drives the speaker.

Music from a phone plays through the same speaker. The first op-amp subtracts the music from the microphone's signal, so the loop doesn't cancel it. The board has four layers and 62 parts, and it runs no firmware. [Its page](/examples/hush) shows it in 3D.

## Sound is a push in the air

Sound is a small, fast swing in air pressure. Air at sea level presses at about 101,000 pascals (Pa). The 150 Hz hum in Hush's simulation swings that by 0.2 Pa, about two parts in a million. Where two sounds meet, their pressures add. In destructive interference, one sound raises the pressure while the other lowers it by the same amount, and the sum is zero.

Paul Lueg patented its use in 1936. The patent is US 2,043,416, "Process of silencing sound oscillations." In it, a microphone picks up the sound, and an amplifier and loudspeaker play it back in opposite phase. In Hush's simulation, the speaker's wave reaches the microphone upside down, at 0.90 of the hum's size. What's left is 18.8 dB below the hum, which is about a ninth of its pressure.

## Why low notes cancel and high notes don't

The opposite wave has to arrive in step with the noise. Any delay puts it out of step. The phase error is how far out of step it is, and for a fixed delay it grows with frequency. The simulation models the air between cone and microphone as a 28 µs delay, and the amplifier adds 2 µs. Those 30 µs are under 2 degrees of a cycle at 150 Hz and 16 degrees at 1.5 kHz.

Wavelength, the distance from one pressure peak to the next, matters too. The quiet zone around the microphone spans only a fraction of a wavelength. A wavelength is 2.3 m at 150 Hz and 23 cm at 1.5 kHz.

In the simulation, the loop cancels noise from 50 to 500 Hz. Hush's loop gain, the factor one trip around the loop multiplies a signal by, falls to one near 1.5 kHz. A digital processor would add tens of microseconds for its converters and arithmetic. Each microsecond of delay costs about half a degree of phase at 1.5 kHz. So the agent built the loop from analog parts.

## Feedback, after Olson and May

A feedforward system has a reference microphone that hears the noise early. Its error microphone, at the quiet spot, hears what's left. Feedback uses just one microphone, at the quiet spot, and the circuit plays its signal back inverted.

Sen Kuo and Dennis Morgan surveyed both kinds in "[Active noise control: a tutorial review](https://doi.org/10.1109/5.763310)," which came out in the Proceedings of the IEEE in 1999. The systems in it run adaptive filters on a digital signal processor, or DSP. An adaptive filter changes its settings to follow the noise. Their basic method is filtered-x least mean squares, or FxLMS, which adjusts the filter at each sample to shrink the error signal. The agent chose feedback over a DSP's adaptive feedforward, which needs a second microphone and firmware.

Harry Olson and Everett May described the feedback kind in 1953. Their paper, "[Electronic sound absorber](https://doi.org/10.1121/1.1907249)," appeared in the Journal of the Acoustical Society of America. The absorber in it is a microphone, an amplifier and a loudspeaker in a feedback loop, the same loop Hush uses. The paper's abstract reports 10 to 25 dB less sound near the microphone, over three octaves of low notes.

## The price of feedback

Hendrik Bode showed the waterbed effect, where quiet from a feedback loop in one band comes with a rise in another. He published it in 1945 in his book *Network Analysis and Feedback Amplifier Design*, from Van Nostrand.

A feedback loop subtracts its output from its input. A half turn of phase, 180 degrees, turns that subtraction into an addition. If the loop gain is one at that phase, the loop oscillates on its own, which in Hush would be a whistle. Phase margin is how far the phase is from that half turn at the frequency where the loop gain is one. Capping the rise at 6 dB guarantees a phase margin of at least 29 degrees. Hush's requirements set that cap and require 45 degrees.

In simulation the rise is 2.6 dB at most. At the worst corner, meaning the worst mix of temperature and part tolerances, it reaches 5.9 dB. The phase margin is 76.9 degrees at the 1.5 kHz crossing and 50.7 degrees at the worst corner.

## How the design went

The agent logged seven mistakes while it made Hush. They're M139 to M145 in [the list of mistakes](ee-agent-kit/MISTAKES.md). Four of them were in the simulation, where each test is a deck, a circuit file for the simulator ngspice.

Diodes Incorporated publishes no simulation model for the PAM8302A amplifier, so the agent wrote one. That model gave half the datasheet's gain. In M139, the agent ran the loop decks on it before the model's own test deck, and then it redid one round of tuning.

TI's op-amp model matches its datasheet, but in the closed loop it gave false operating points. An operating point is the set of DC voltages a circuit rests at. In the false ones, an op-amp's output sat pinned at its supply, and the numbers still passed their limits. The loop decks now run a model fitted to TI's, within 0.52 dB of it up to 10 kHz. After M143, each loop deck also checks two DC voltages, so a false operating point fails.

FreeRouting is the autorouter that lays the copper tracks. In M142, it connected none of the amplifier's pins, because the chip was turned 26 degrees to follow the ring. With the chip turned square, every pin connected.

Each round, a reviewer who hadn't seen the board read its pictures and named the three worst problems. In the first round, the wave art on the back ended in the jack's peg hole. In the second, the + and - marks by the speaker's pads were turned to the ring's angle, so they read as "x" and "/". The agent fixed both.

![The back of Hush: two white waves circle the ring and merge into one line, beside the words NOISE + ITS INVERSE = SILENCE, with gold rims around the windows](/examples/hush/bottom.png "The back of the ring, which faces the speaker")

The last run of the checks reads `GREEN with 6 warnings`. The electrical rules check and the design rules check found no errors. Four warnings are for printed lettering where the jack and the switch hang over the board's edge. The other two come from TI's model in its test deck. Seven decks made 986 runs at the corners. The noise at the microphone drops 7.5 dB at 50 Hz and 20.4 dB at 200 Hz. At the worst corner, those drops are 3.0 and 16.9 dB.

## What is open

Nobody has ordered or built a Hush board, so every result here comes from simulation. The 4 mm from cone to microphone is an estimate from the speaker's drawing, and the corners try 3 to 5 mm. The decks model the speaker in free air. A box behind it would raise its resonance. Nobody has measured how far the quiet spreads beyond the microphone. The verification package, which ties each requirement to its proof, isn't written yet. [The README](examples/anc-speaker/v0.1/README.md) lists every open item.

We want v0.2 to start with the verification package. After that, we'd like a board on a bench, with a second microphone beside the first.
