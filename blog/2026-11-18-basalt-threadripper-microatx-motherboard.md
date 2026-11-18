---
title: Basalt: fitting a Threadripper onto a microATX board
date: 2026-11-18
tags: [examples, basalt, ddr5, power delivery, escape routing]
image: /examples/basalt/card.png
---

Basalt is a motherboard for AMD's Threadripper 7000 and 9000 processors, on a microATX board 244 mm square. Every board made for this platform, TRX50, is ATX or larger, and we asked for a smaller one. An AI agent designed it with Via, our tools and checks for building KiCad boards. We wrote the brief, then read the agent's work, including its checks and its mistakes.

![Basalt v0.3 in 3D: a black board with a large socket in the middle, two memory modules on each side, finned heatsinks on the left and above, and expansion slots below](/examples/basalt/card.png "Basalt v0.3, rendered from its board file")

## Why the outline comes first

On a motherboard the case sets the shape before any circuit is drawn. A microATX board measures 244 by 244 mm, and it has to line up with the case's posts, port window and slot openings. The holes and the port window are drawn in version 2.2 of Intel's ATX Specification. Where each slot's connector sits comes from PCI-SIG's PCI Express Card Electromechanical Specification, revision 4.0.

The agent used every position those drawings give, including nine mounting holes of 3.96 mm. The slots' center lines are 20.32 mm apart, which is 0.8 inch, the spacing of the case's openings. Inside the outline are the socket, three PCI Express x16 slots and four DDR5 memory slots, two on each side. There are also two M.2 sockets for solid-state drives.

## Getting 4844 contacts out from under one chip

The processor's package measures 58.5 by 75.4 mm. Its underside has 4844 lands, 0.94 mm apart along a row and 0.81 mm between rows. Each signal land needs a trace that leaves the grid through the gaps between rows.

The neat part is how regular Basalt's answer is. Each gap carries one trace on each copper layer. The outer column's traces leave on the top layer, and traces from the next column in drop through a via and leave on the next signal layer. The memory bands are four signal columns deep, so the memory needs four routing layers. Basalt has 10 copper layers, which leaves room for the PCI Express traces out of the socket and for four planes of ground and power.

![The back of Basalt v0.3: a speckled field of vias under the socket, the memory slots' pin rows on each side, and white rings round the mounting holes](/examples/basalt/bottom.png "The back of Basalt v0.3: the speckled field in the middle is the socket's vias")

## Memory buses and timing inside a byte

Each of Basalt's four DDR5 channels has 144 traces, for data, strobes, check bits, commands, addresses and clocks. The data moves in byte lanes of eight lines, each with a strobe beside it, and the receiver times each read from the strobe's edges. JEDEC defines this scheme in its DDR5 standard, JESD79-5, from 2020.

A signal in a trace buried inside this board travels about 141 mm per nanosecond. That's the speed of light divided by the square root of 4.5, the board's dielectric constant. Howard Johnson and Martin Graham work this out in their 1993 book *High-Speed Digital Design*, from Prentice Hall.

At 4800 million transfers a second, one of DDR5's standard rates, a bit lasts about 208 picoseconds. In a trace like this, 12.3 mm of extra length adds about 87 picoseconds of delay, more than 40% of the bit. That's why designers match the lengths inside each byte lane. Basalt's lengths aren't matched yet. Its byte lanes spread by 0.5 mm at the median, and by that same 12.3 mm at the worst.

The agent drew all 576 traces itself with four rules in [`buses.py`](examples/threadripper-matx/v0.3/buses.py), and none went to a router. The trick we like is in the ordering. On each layer, 72 lands and 72 slot pins pair up in order, so no two traces cross. The first design-rule check on these traces found no errors.

The traces on In2 and In3 are striplines, running between the ground planes In1 and In4, so their impedance depends on the trace's width and the spacing of the planes. The files don't set one for Basalt's 0.1 mm memory traces yet.

## Hundreds of amps at about 1 V

A 350 W processor near 1.1 V draws near 320 A. The power arrives at 12 V through two EPS 8-pin connectors. A buck converter takes it down to about 1.1 V by switching the 12 V on for about 9% of each cycle. Robert Erickson and Dragan Maksimović derive this in *Fundamentals of Power Electronics*, whose 3rd edition Springer put out in 2020.

That much current gets split across phases running in parallel. Basalt has 14, each a Texas Instruments CSD95490Q5MC power stage rated 75 A with a 150 nH choke. Twelve feed the core supply, VDDCR_CPU. The other two feed the SoC, the part of the chip outside the cores.

The controller that staggers the phases in time isn't on the board yet, because AMD only shares the processor's regulator interface under a nondisclosure agreement.

The current reaches the socket through copper planes. A square of copper foil has the same resistance from edge to edge whatever its size, because a bigger square is longer and wider by the same amount. That resistance is the copper's sheet resistance. Eric Bogatin explains it in the 3rd edition of *Signal and Power Integrity, Simplified*, from Prentice Hall in 2018. One square of copper 15 µm thick measures about 1.1 milliohm. At 320 A, that's a drop of more than a third of a volt from a supply near 1.1 V.

Basalt carries VDDCR_CPU to the socket on one plane, In5, of 15 µm copper. A second plane in parallel would halve the drop, and doubling the copper's thickness would halve it again. None of the gates that passed measures this drop, and no check of it has run yet, so we don't know yet what the drop on Basalt really is.

## How the design went

The agent built Basalt in a loop, running one prompt again and again on the same files. [`LOOP.md`](examples/threadripper-matx/LOOP.md) logs all 12 passes.

In v0.1 the agent gave the four supply nets to FreeRouting, an automatic router. Twice, it ran for 20 minutes without finishing a pass. So the agent drew the supplies itself, as three copper pours and one track, the way a motherboard carries them. The next check found nothing unconnected. The agent logged giving the supplies to the router as M150 in [the list of mistakes](ee-agent-kit/MISTAKES.md).

The design-rule check also found each phase's switch node shorted to ground. Each switch node's 2.0 mm track began at the center of a 0.8 mm pad and reached the ground pad. The tracks now start at the pad's outer edge.

Midway through, we asked for "basically a bunch of ports that all modern motherboards have". Version 0.3 added 77 parts, among them SATA ports, five fan headers and the CMOS battery. FreeRouting ran on their 51 nets for 0.3 s and routed none of them. The agent extended the project's own grid router so it could change layers through a via, and then the router joined all 51.

Each version passed Via's gates with no warning. On v0.3 that means no electrical or design-rule errors, nothing unconnected, and 30 Gerber files for the fab. The simulation gate had nothing to run, because the board doesn't have a circuit with a test deck yet. On [Basalt's page](/examples/basalt) you can follow every track.

## What is not done

No one has ordered or built a Basalt. The PCI Express and M.2 lanes aren't drawn. On a scratch copy, 151 of the 234 routed. The processor's land map is a stand-in, because AMD keeps its own under NDA. The socket's housing, frame and cooler holes are estimates. The regulator's controller, the rear ports' controllers and the board controller's firmware aren't done. [The v0.3 README](examples/threadripper-matx/v0.3/README.md) lists every open item.

Next, we want the agent to draw the PCI Express and M.2 lanes by rule, like the memory. After that we intend to add the regulator's controller, which brings the board's first simulation deck.
