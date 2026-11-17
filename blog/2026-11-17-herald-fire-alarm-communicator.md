---
title: Herald, a fire alarm communicator designed with Via
date: 2026-11-17
tags: [examples, herald, simulation]
---

Herald is a fire alarm communicator. An AI agent designed it with Via from a written brief. The design file, the routed board and the results of the checks are in the Via repository.

![Herald's routed board in 3D: a red board with an LTE-M module, a nano SIM, an ESP32-S3 module, a relay, status lights and black screw terminals](/examples/herald/card.png "Herald v0.1, rendered by KiCad")

## What Herald does

Herald connects to a fire alarm control panel. It sends the reports of the panel to a monitoring station. It uses LTE-M first. When LTE-M is not available, it uses Wi-Fi.

Fire panels send their reports on a phone line. Herald connects to the dialer of the panel and operates as the phone line. Herald also reads three supervised relay contacts. A relay on Herald tells the panel when Herald has a fault.

The board has no DTMF chip. The firmware decodes the DTMF digits with a Goertzel filter. Host tests examine the decoder against the limits in ITU-T Q.24.

The board is 84.4 × 64 mm. It has four layers and 127 parts. All of the parts are on the front. [The Herald page](/examples/herald) shows the board in 3D and shows each track.

## The checks

One Python file, [`design.py`](examples/fire-alarm-communicator/v0.1/design.py), contains the parts, the connections and the placement. These two commands make the KiCad project, route the board and do the four checks:

```sh
workcenter design design.py --route
workcenter gates .
```

The result of the last run is `GREEN with 7 warnings`:

- Electrical rules (ERC): no errors and no warnings.
- Design rules (DRC): no errors and no unconnected items. The seven warnings are for silkscreen at the edge of the board.
- Simulation (SIM): eight decks, with 573 runs at the corners of temperature and part tolerance.
- Fabrication files (EXPORT): 24 Gerber files, the drill files, the bill of materials and the schematic.

## Problems found during the design

The design had eight rounds. In each round, the agent made, routed and rendered the board. In six rounds, a reviewer examined the pictures with one fixed prompt. The reviewer had not seen the board before. The list of problems from the reviewer was the work for the next round. The width of the board decreased from 96 mm to 84.4 mm, and the terminals changed to black.

The simulation found a fault in the tone filter. The first filter put 28 mV on the phone line. The deck requires 62 mV. The 600 ohm load of the line decreased the level of the tone. The filter parts changed from 10k and 10n to 1k and 68n. The deck now reads 191 mV to 204 mV at 350 Hz at all corners.

FreeRouting did not connect three nets, so these tracks are drawn by hand. One of them goes to the normally open contact of the relay. A keep-out area blocks the path of the router to that contact.

Two keep-out areas caused errors. The first was added after the parts were placed, and it covered pads. The second was on the back. The check of its pads did not include the front pads. Each error caused an open net in a route. The [list of mistakes](ee-agent-kit/MISTAKES.md) records them as M137 and M138, with the change to the process for each.

## Open items

Nobody has made a Herald board. The firmware has not run on a board, and the protocol for the station is not selected. A communicator for a fire alarm system must have a listing to UL 864 or a local equivalent. Herald does not have this listing. [The Herald README](examples/fire-alarm-communicator/v0.1/README.md) gives all of the open items.

The next two items on [the Via roadmap](ee-agent-kit/ROADMAP.md) are these:

- Item 1, "A circuit walked stage by stage": a page for the review of a circuit.
- Item 2, "A bench plan with the readings the decks predict".
