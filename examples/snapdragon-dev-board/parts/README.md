# Parts and cost

Every prototype's parts as something you can order: a manufacturer part, a supplier number, the
price breaks and the stock for each line, priced for 1 and for 10 units. Prices are in USD, as each
supplier's page showed them on 2026-11-11, before shipping and tax.

- `catalog.csv`: one row per value and footprint, for every version.
- `offboard/<version>.csv`: what a version needs that is not on its board: the Snapdragon module,
  the bare board, the antennas.
- `lists/`: each version's priced list, made by `workcenter costs ..` from the schematic and the
  two files above.

<!-- workcenter costs lists -->
| Version | Lists |
|---|---|
| v0.1 | [base](lists/v0.1.md) ([csv](lists/v0.1.csv)) |
<!-- /workcenter costs lists -->

## Totals

The board and the priced items off it, for one unit and for ten (each line bought at the cheapest
quantity that covers it, so ten units cost less than ten times one):

<!-- workcenter costs -->
| Version | 1 unit | 10 units | Per unit at 10 | Not priced | Short of stock |
|---|---|---|---|---|---|
| v0.1 | $32.76 | $257.08 | $25.71 | C7,C8; C23; L1; U4; Lantronix Open-Q 845 uSOM, 4 GB / 32 GB; PCB 60.96 x 30.48 mm, 6 layers, 1.6 mm; Wi-Fi and Bluetooth antennas, U.FL, 2.4 and 5 GHz | C1,C2; C3-C5; C9-C11; C12-C19,C22,C24; J1-J3; R15; U2; U6,U7 |
<!-- /workcenter costs -->

Made by `workcenter costs ..` from the lists.

## What the totals leave out

The Snapdragon module is the board's most expensive part and the totals do not hold it: Digi-Key
lists the Open-Q 845 uSOM as obsolete with no price, and Lantronix sells it to order. Four lines on
the board are not priced either, each with its reason in `catalog.csv`: the RP2350 (sold through
Raspberry Pi's resellers, not found on Digi-Key under its own name), the Coilcraft inductor
(Coilcraft sells direct; its page refused the fetch), and two Murata capacitors Digi-Key now lists
as obsolete. Several lines were out of stock on the day; each row's note gives the date Digi-Key
expects them.
