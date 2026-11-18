# The USB-C port block

`blocks.usbc` adds a USB Type-C receptacle as a sink, a device that takes
5 V from VBUS. It adds the receptacle, 2 Rd resistors on CC1 and CC2, 2 ESD
clamps (D+ and D-, CC1 and CC2) and 1 capacitor on VBUS. The code is
`tools/blocks_usbc.py`. The numbers are in `rules/blocks/usbc.json`, each
with its document, section, table and page:

| Number | Value | Source |
|---|---|---|
| Rd | 5.1 kohm, +-10 % to read the advertisement, +-20 % if not | USB Type-C R2.5, table 4-28, page 245 |
| Current at each advertisement | Default 500 mA, 1.5 A, 3.0 A | USB Type-C R2.5, section 4.6.2.1, page 226, table 4-20, page 227 |
| CC voltage of each advertisement | vRd-USB 0.277 to 0.612 V, vRd-1.5 0.746 to 1.164 V, vRd-3.0 1.369 to 2.042 V | USB Type-C R2.5, table 4-36, page 254 |
| CC thresholds | vRd-USB to vRd-1.5: set within 0.613 to 0.745 V; vRd-1.5 to vRd-3.0: set within 1.165 to 1.368 V | USB Type-C R2.5, table 4-36, page 254 |
| Before configuration | 1 unit load, 100 mA | USB 2.0, section 7.2.1, page 171 |
| D+ and D- shorts | A6 to B6 and A7 to B7 at most 3.5 mm | USB Type-C R2.5, table 3-5, note 2, page 77 |
| Rp of the source | 56k +-20 %, 22k +-5 %, 10k +-5 %, to 4.75 to 5.5 V | USB Type-C R2.5, table 4-27, page 245 |
| VBUS range | 4.75 to 5.50 V | USB 2.0 ECN VBUS Max Limit, table 7-7, page 4 |
| Capacitance on VBUS | 1.0 to 10.0 uF, more than 1.0 uF up to 5.25 V | USB 2.0 table 7-7 (CRPB), page 179; Device Capacitance ECN, page 2 |
| D+ and D- | 0 to 3.6 V | USB 2.0 table 7-7, pages 178 and 179 |
| Wiring | shell to ground; VBUS pins together; GND pins together; A6 and B6 together, A7 and B7 together; SBU and the unused pins open | USB Type-C R2.5, section 3.2.1 note 11, page 47; table 3-5, notes 1 to 5, page 77 |

The receptacle is GCT USB4115-03-C, vertical (5 A on VBUS, its drawing,
page 1). GCT USB4105, the horizontal one, is not taken: KiCad's footprint
puts its GND pads 0.19 mm from its pegs' holes, and the board asks
0.25 mm. The
clamp is TI TPD2E2U06DCKR (5.5 V stand-off, SLLSEG9C, page 4).

The block holds what these documents state and no more. USB Power
Delivery, a VBUS clamp, a fuse and the part that reads CC are the
designer's own, and `workcenter ratings` judges them.

What the block does not judge, its sums say, each with the reason:

- The copper from J1 to each clamp, and the length of the D+ and D-
  shorts. The router lays that copper after the block has run. Measure
  both on the routed board: the clamps as close to J1 as you can, each
  short 3.5 mm or less.
- The 100 mA before the USB host configures the device, at Default. The
  block cannot see the firmware. The port wires D+ and D-, so it is a
  USB 2.0 device and not a Power Sinking Device.
- Rp as a current source, or as a pull-up to 3.3 V (table 4-27). The
  deck models the pull-up to 4.75 to 5.5 V only.

## Steps

1. Write the facts of each part you stock into `library/facts/`, as the
   `ratings` skill says: a 5.1 kohm resistor with its `tolerance`, a
   capacitor with `tolerance`, `volts` and `kept` (its DC bias curve), and
   the clamp `TPD2E2U06DCKR` (`tests/boards/library/facts/ti-tpd2e2u06.json`
   is one).
2. Decide 2 numbers. `amps`: the most the design draws from VBUS. `detects`:
   the highest advertisement the design reads on CC: `"default"` when nothing
   reads CC, `"1.5A"` or `"3.0A"` when a part reads CC1 and CC2 against
   table 4-36.
3. In `design.py`, call the block:

   ```python
   import blocks

   block = blocks.usbc(d, amps=1.5, detects="1.5A",
                       nets=("VBUS", "GND", "D+", "D-", "CC1", "CC2"),
                       stock=STOCK, facts=Path(__file__).parent / "library" / "facts",
                       sch_at=(50.8, 88.9), pcb_at=(120.0, 121.0))
   d.files = {
       "ratings.json": blocks.ratings_json("nasa-eee-inst-002", block.ratings, own),
       "parts.csv": blocks.parts_csv(block.rows + my_rows),
       **block.files,
   }
   ```

   `pcb_at` is the receptacle's centre; the block puts Rd, the clamps and
   the capacitor up to 12 mm above it. `farads=(least, most)` adds the capacitance the rest of
   the design puts on VBUS. `tests/boards/block_usbc.py` is a whole example.
4. Run `workcenter design design.py`. What it prints:
   - `usbc J1: a load of X A is over the Y A that <level> ... allows`: the
     design draws more than the advertisement it reads allows. Read a higher
     advertisement (`detects`), or draw less.
   - `is over the 3 A of the highest advertisement`: more than 3 A needs USB
     Power Delivery, which this block does not build.
   - `no stocked resistor with facts is Rd of ...`: add a 5.1 kohm resistor of
     1 % or 5 % to the stock, with its facts.
   - `no stocked capacitor keeps VBUS within 1 uF to 10 uF`: the line says why
     each capacitor was passed over. Add a capacitor whose value with its
     tolerance stays under 10 uF and whose DC bias curve keeps more than 1 uF
     at 5.25 V, or lower `farads`.
   - `are on 1 net`: 2 of the 6 nets you passed are the same net. Give each
     signal its own net.
   - `amps=`, `nets=` or `farads=` with `is asked`: the argument is not what
     the block takes. The line says what it takes.
   - `usbc J1: <part> ...` with a pin or a net: the block's own check found a
     fault in what it built. Report it: the block is wrong, not the design.
   - `design ... green`: the parts, `ratings.json`, `parts.csv` and
     `sim/cc.cir` are written.
5. Open `sim/cc.cir`. Its lines after `* The sums:` are `block.sums`: 1 line
   per decision, each with its clause. Copy them into the version's README.
   A sum that says `draw over 500 mA only while CC1 or CC2 is over the
   threshold, which the part that reads CC sets within X V to Y V` is a
   requirement on the firmware or the part that reads CC. A 3.0 A port has a
   second line for over 1.5 A. A line with `not judged` is yours to check.
6. Run `workcenter ratings . --strict`. A `fail` line is a part outside its
   rating: fix it as the `ratings` skill says.
7. Run `workcenter design design.py --route`, then `workcenter gates . --strict`.
   The SIM gate runs `sim/cc.cir`: the CC pin under each advertisement, at
   each end of Rp, the pull-up and Rd, held to table 4-36 (table 4-35 when
   the design reads no advertisement).
