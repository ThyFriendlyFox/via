# Fixture boards

These projects are the tests of the gates. Each one exists to make 1 gate
behave in a known way.

| Project | Expected | Why |
|---|---|---|
| `pass-rc-divider` | GREEN on `workcenter gates`, with `--strict` too | A 2-resistor divider with an RC filter. Schematic, board, and a sim deck with bounds. Its `sim/corners.json` names -40 and 85 C, 1 % resistors, a 10 % capacitor and 8 Monte Carlo draws: 46 corner runs, the output between 2.4605 and 2.54175 V, 8.25 mV inside its nearer bound. |
| `pass-first-design` | GREEN on `workcenter gates`, with `--strict` too | The first design file, built: the 1 fixture that goes from a design file through all 4 gates. `design.py` is `templates/project/design.py` to the byte. The schematic and the project file are what `workcenter design` writes from it; a test compares. `workcenter design design.py --route` wrote the board, and DRC holds the board to the schematic. On a 5 V supply the deck holds 2 bounds over 46 corner runs. The output stays between 2.4605 and 2.5417 V, and `f3` between 280.2 and 365.5 Hz. `f3` is the frequency where the output is 0.3536 of the input: the low-pass corner at a gain of 0.5. The pictures of the root `README.md` are of this board. |
| `fail-drc-clearance` | ERC pass, DRC fail with a `clearance` violation | The same board with 1 track moved inside the clearance of a pad. |
| `fail-sim-spec` | SIM fail on the `vout` bound | The divider deck with bounds that the circuit cannot meet. No board, no corners: the gate names their absence as a warning. |
| `fail-sim-corner` | SIM fail at a corner, each bound holding as written | 2 decks, no board. `diode_ref`: a diode's forward voltage, 0.548 V at 27 C and 0.42 V at 85 C against a 0.50 to 0.60 V window. `divider`: 2.5 V as written, 2.375 V and 2.625 V with its 5 % resistors apart against 2.45 to 2.55 V. 32 corner runs; each failure line names the worst corner and how many more miss. |
| `pass-lc-filter` | SIM pass with `--strict` | 3 decks, no board: a 15.9 kHz input filter swept with `.ac`, a 100 kHz load clear of it, and a 16 kHz clock on its resonance. `sim/frequency-plan.json` names both sources and the resonance, and answers the clock's overlap with the deck that drives it. 94 corner runs: the deck that answers the overlap is also run with L stepped against C between their ends. |
| `fail-freq-overlap` | SIM fail on the frequency plan alone | The same filter with a load at 5.3 kHz, whose third harmonic is the resonance: the rail swings 6.8 V on a 5 V supply while the deck's one bound, on the average, holds. Only the plan sees it. |
| `inspect-four-layer` | `workcenter inspect` answers as `tests/test_inspect.py` expects; DRC fails with 1 unconnected item, the pour island it keeps on purpose | Generated from its own `design.py` (regenerate with `workcenter design`; a test compares). Four layers, VIN's 10 mm run on In2.Cu between two vias, a T-junction, a copper keep-out over the island, a parts keep-out, Sierra's rule file. |
| `fail-fab-sierra` | GREEN on `workcenter gates --strict`, DRC fail with `--fab sierra-circuits-web` (`annular_width`, `text_thickness`) | The divider with a 0.6/0.3 mm via (0.15 mm ring, under Sierra's 6 mil) on a bottom-face return of VOUT, and a legend label stroked 0.10 mm (under 5 mil). |

| `pass-ratings-node` | `workcenter ratings --strict` prints `RATINGS HELD` | The board of `ratings_node.py`, schematic only: a TLV62569 buck regulator from 5 V to 3.3 V, 2 logic buffers in a row and a 1.1 A load on a header. 453k over 100k under the regulator's 0.588 to 0.612 V puts the output at 3.199 to 3.440 V. Its `ratings.json` states the 5 V rail, the signal and the load; `parts.csv` names each part's number. |
| `fail-ratings-pin` | `ratings` fails on 1 line, `pin.voltage` | U3 and its capacitor stand on +5V. Its output puts the rail's 5.25 V on U2's input, which takes 4.6 V. |
| `fail-ratings-load` | `ratings` fails on 1 line, `output.current.linear` | The schematic of `pass-ratings-node`. Its `ratings.json` states 1.9 A for the load: 0.95 of the 2 A the regulator gives, and the pack allows a plastic linear part 0.70. |
| `fail-ratings-decoupling` | `ratings` fails on 1 line, `needs.capacitor` | C1 is left out. The regulator's supply pin has no capacitor, and its datasheet asks for 4.7 uF. |
| `fail-ratings-inductor` | `ratings` fails on 1 line, `inductor.current` | L1 is a 2.0 x 1.6 mm part that saturates at 1.26 A. At the least output the ripple is (5.25 - 3.199) x 3.199 / (5.25 x 0.9) / (1.35e6 x 1.76e-6) = 0.584 A; the 1.1 A load and half of it is 1.392 A. |
| `fail-ratings-bias` | `ratings` fails on 1 line, `needs.capacitor` | C3 is left out. C2, 10 uF less 20 %, keeps 0.50 - 0.12 x 0.440 = 0.447 of its value at 3.440 V: 3.58 uF. The 2 bypass capacitors have no curve and give 0.11 uF each at the most: 3.80 uF, under the 5 uF the datasheet asks for. |
| `pass-highspeed` | `workcenter highspeed` prints `HIGHSPEED HELD: 10 held, 2 not judged` (TI's single-ended impedance and stubs, which the command does not judge; `--strict` fails on them); KiCad's DRC with the rules it writes passes | The board of `highspeed_pair.py`: a USB 2.0 pair on F.Cu between 2 headers, 0.31 mm wide and 0.2 mm apart, 30.1136 mm a track, over a ground plane on In1.Cu. Its `interfaces.json` names `ti-am57xx-usb2`. |
| `fail-highspeed-width` | `highspeed` fails on `width` alone, 2 lines | Both tracks are 0.2 mm wide, their centres 0.51 mm apart: a 0.31 mm gap, the gap its `interfaces.json` gives. The solver gives 0.2971 to 0.4368 mm for 81 to 99 ohm at that gap. |
| `fail-highspeed-skew` | `highspeed` fails on `skew` alone, 1 line | USB_D_N steps 1 mm aside and back: 32.1136 mm against 30.1136 mm, 2 mm of skew against 1.27 mm (50 mil). The 1 mm of the step runs 1.2 mm apart, printed as a gap not judged. |
| `fail-highspeed-plane` | `highspeed` fails on `plane` alone, 2 lines | The plane on In1.Cu is 2 pours with a 1 mm gap at x = 120 to 121 mm; both tracks cross it. |
| `library` | No board: the facts of the ratings fixtures' parts | `library/facts/`, found by `workcenter ratings` as a project's own library is: in a folder above the project. The regulator, the 2 buffers, the resistors, the bypass capacitors and the 2 inductors are real parts, each entry read from its maker's datasheet with the URL, the SHA256 and the pages. The 10 uF capacitors and the headers are made up, and their entries say so. |

Symbols and footprints are embedded in the files, so no library tables are
needed to run them. `build/` output is ignored by git.

The 6 ratings fixtures are 1 design, `ratings_node.py`, with 1 fault
planted in each of 5. A fixture's `design.py` names its fault; its
`node.kicad_sch` and `node.kicad_pro` are what `workcenter design` writes
from it, and a test compares. To write them again, and no board with them:

    workcenter design tests/boards/<fixture>/design.py --out <a scratch folder>

and copy the 2 files in. The boards are not routed and not built: `ratings`
reads the schematic alone.

The 4 high-speed fixtures are 1 design, `highspeed_pair.py`, with 1 fault planted in each of 3. Every
track is drawn in the design; the boards are written, not routed:

    workcenter design tests/boards/<fixture>/design.py

`kicad-cli` writes a `<name>.kicad_prl` next to the project when it runs.
It is a KiCad side file with no design content and is ignored by git.
