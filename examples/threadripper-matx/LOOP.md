# The loop that built Basalt

Basalt was built in a Ralph loop: 1 prompt, run again and again against the same files, each pass
reading where the board stands, doing the next thing, and checking it, until the prompt's last line
holds. The prompt is below as it was run; the passes are logged under it.

## The prompt

> Basalt is a microATX motherboard for an AMD Threadripper on sTR5, made with the EE Workcenter in
> `examples/threadripper-matx/`, one version folder per feature (`PROCESSES.md` P22). Read the series
> README, the latest version's README and its last gates report. Then do the 1 thing that moves the
> board furthest, in this order of need:
>
> 1. The latest version is not GREEN: fix the first failure `workcenter next` names.
> 2. Its pictures are missing or older than its board: `workcenter pictures`, then look at every
>    picture and write down what looks wrong.
> 3. Something in the pictures looks wrong, cheap or empty: fix the worst one.
> 4. The version's README does not say what the board is now: write it.
> 5. Everything above holds: start the next version (`workcenter version new`) with the next feature
>    from the list: the DDR5 buses, the ports and headers, the PCI Express and M.2 lanes.
>
> Every number in a README comes from a run of this pass. A stand-in for what AMD keeps under NDA is
> named as one. Stop when the list is done, the latest version is GREEN, its pictures are current and
> its README is true.

The list read "the DDR5 buses, the PCI Express and M.2 lanes, the control and I/O parts" until pass 8.
On 2026-11-11 the owner asked for the ports and headers every modern board carries (SATA, fan and RGB
headers and their controllers, the CMOS battery, the front panel's and USB headers), and they moved
up the list.

## The scorecard

Each pass ends by scoring the latest version on these lines; a pass that cannot raise one says why.

| Line | Done when |
|---|---|
| Gates | `workcenter gates <version>` prints GREEN |
| Pictures | `workcenter pictures <version>` exits 0 and every picture was looked at after the last board change |
| Look | no picture shows a bare pad, a body through another, an empty quarter of the board or a colour that glares |
| Fidelity | every position the microATX and CEM drawings give is the drawing's; every estimate is named |
| README | the status table, What changed, Decisions and Open items say what the board is now |

## The passes

| Pass | Version | What it did | Verdict |
|---|---|---|---|
| 1 | v0.1 | the floor plan from the ATX 2.2 and CEM 4.0 drawings; the socket, slots, sockets and connectors from makers' drawings; 14 phases | ERC 0/0; DRC red: courtyards, shorts, symbols overlapping on the sheet |
| 2 | v0.1 | the sheet laid out by each symbol's real extent; each phase drawn from the stage's land pattern; the jacks 20 mm apart | ERC 0/0; DRC only unconnected supply vias |
| 3 | v0.1 | the plane polygons widened to the land field; the cooler holes and the top phases moved out of the memory buses' path (found while planning v0.2) | DRC only connections left for the router |
| 4 | v0.1 | first renders: near-black mask, darker metals, a grooved I/O cover; a headline script on a dark ground | the look holds; the right and lower quarters are empty until v0.4 |
| 5 | v0.1 | the first route ran 20 minutes without an end: 10 stages' driver-supply pins were boxed in by their own sense tracks. Each phase's bootstrap, sense and supply links drawn by hand; BOOTR its own net (the switch node inside the package); the M.2 sockets turned to face the lanes' trunk; the DIMMs 0.9 mm up for a row of slot 1's capacitors (all found while planning v0.2 and v0.3) | ERC 0/0; DRC only the router's connections |
| 6 | v0.1 | the second route of the 4 supply nets ran 20 minutes without finishing a pass and was stopped; the supplies drawn instead, as a motherboard carries them: +12V and +3V3 as pours round the whole of In5 and In7, +12V_CPU as a pour on In7 under the phases' inputs, +5V as 1 track on In6 (`supply.py`); the workcenter's via check made 200 times faster | ERC 0/0; DRC 0 errors, 0 unconnected, 4 warnings: the jacks' legend past the board edge |
| 7 | v0.1 | the jacks' legend cut at the edge; the sheet wired, each phase's 5 parts together; pictures looked at: the gold rings glared and the translucent mask rendered brown, so immersion silver and an opaque mask, rendered again | GREEN with no warning |
| 8 | v0.1 | the sheet's phases packed tighter, a phase never split across 2 shelves; the owner asked for the ports and headers of a modern board, which became the next version | GREEN with no warning; pictures current |
| 9 | v0.2 | `workcenter version new`; the 4 channels' buses drawn by `buses.py` (576 traces, 864 vias), first tried on a scratch copy; the bus nets as labels on the sheet, after the wired sheet took 10 minutes drawing them | GREEN with no warning, DRC 0 unconnected on the first run |
| 10 | v0.3 | the owner's ports and headers, 77 parts (`ports.py`): SATA, 5 fan headers and the EMC2305, ARGB and 12 V RGB headers and an STM32G0B1 to drive them, the CMOS battery and its clear jumper, the front panel, USB 3, USB 2.0 and TPM headers, the BIOS flash, buttons, status LEDs, a 3.3 V standby rail. FreeRouting finished their 51 nets in 0.3 s with none routed, so `gridroute.py` learned to change layer through a via; 11 courtyard overlaps, a walled-in escape and 2 vias on the +5V track fixed on the way | ERC 0/0, DRC 0 errors and 0 unconnected; pictures: SYS_FAN1 stood on the BASALT legend |
| 11 | v0.3 | SYS_FAN1 moved under the fan controller, off the legend; the 2 lines to SYS_FAN2 routed first, before their neighbours wall in their pin's escape; rendered again | GREEN with no warning |
| 12 | v0.4 (scratch) | the PCI Express and M.2 lanes tried on a copy: the grid router's lanes and its pads carried different names for 1 net, so every lane was walled in by its own capacitor; fixed, 151 of 234 route. The M.2 lanes fail even routed first: the lanes before them fill the way to the trunk beside the slots, which needs drawing by rule like the memory's | not a version yet |
