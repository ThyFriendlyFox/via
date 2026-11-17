---
title: Herald, a fire alarm communicator designed with Via
date: 2026-11-17
tags: [examples, herald, simulation]
---

Via's repository now holds a complete fire alarm communicator, Herald, designed by an agent from a written brief. Its design file, its routed four-layer board and the run of every check it passed are in the repository for you to read and run.

![Herald's routed board in 3D: a red board with an LTE-M module, a nano SIM, an ESP32-S3 module, a relay, status lights and black screw terminals](/examples/herald/card.png "Herald v0.1, as KiCad renders its routed board")

## What Herald does

Herald sits in a cabinet beside a fire alarm control panel. It reports what the panel reports to a monitoring station: over LTE-M first, and over Wi-Fi when the cell path is down. Fire panels report by phone, so Herald answers the panel's own dialer as if it were the phone line. It also reads three supervised relay contacts, and a relay of its own tells the panel when Herald is in trouble.

There is no DTMF chip. The firmware reads the dialer's digits with a Goertzel filter, and host tests hold it to the limits of ITU-T Q.24. The board is 84.4 × 64 mm, with four layers and 127 parts, all on the front. [Its page](/examples/herald) turns it in 3D and lets you follow every track.

## The checks it passed

One Python file, [`design.py`](examples/fire-alarm-communicator/v0.1/design.py), holds the parts, the connections and the placement. Two commands write the KiCad project, route it and run the four checks:

```sh
workcenter design design.py --route
workcenter gates .
```

The last run ends `GREEN with 7 warnings`. Electrical rules (ERC) report no errors and no warnings. Design rules (DRC) report no errors and no unconnected items; the seven warnings are silkscreen that reaches the edge of the board. Simulation (SIM) runs eight decks at every corner of temperature and part tolerance, 573 runs in all. The fabrication files (EXPORT) are 24 Gerber files, the drill files, the bill of materials and the schematic.

## What broke on the way

The design took eight rounds. In each round the agent generated, routed and rendered the board. In six of them, a reviewer who had not seen the board read its pictures against one fixed prompt, and the list that came back was the next round's work. The board went from 96 to 84.4 mm wide, and its terminals turned black.

The simulations caught a real fault. The first tone filter put 28 mV on the phone line, where its deck asks for 62 mV: the line's 600 ohm load took the tone. The filter's parts changed from 10k and 10n to 1k and 68n. The deck now reads 191 to 204 mV at 350 Hz at every corner.

The router did not finish alone. A keep-out drawn after the parts were placed covered pads, and the route left one net open. FreeRouting found no way to the relay's normally open contact past the strip that keeps tracks off the terminals' names, so that track is drawn by hand. Three nets in all are drawn by hand. Both keep-out mistakes are in [the repository's list of mistakes](ee-agent-kit/MISTAKES.md), as M137 and M138, each with the process step it changed.

## What is still open

Herald v0.1 has not been made. Nothing has run on a board, and no station protocol is chosen. A communicator that a fire alarm system relies on is listed to UL 864 or a local equivalent; Herald has been through none of it. [Its README](examples/fire-alarm-communicator/v0.1/README.md) lists every open item.

Next, Via is to walk a circuit stage by stage for a review, and to write a bench plan with the readings its simulations predict. Both are at the top of [the roadmap](ee-agent-kit/ROADMAP.md).
