---
name: Fields
description: Simulates the nets a design names as critical (a fast line, a pair, an antenna's feed) with a field solver, openEMS, from the board file with no hand-written mesh, and holds impedance, return loss, insertion loss and coupling to limits that each name their document.
---

# Fields

A track's impedance, its loss and what it couples into its neighbour are
set by its copper and the stack-up, not by the schematic. `workcenter
fields` writes a model from the `.kicad_pcb`, runs a field solver on it and
holds each measure to a limit in the project. openEMS is the solver. It runs
as its own program; none of its code is in this repository.

## When

- A board is routed and it carries a fast interface (USB 3, PCIe, Ethernet,
  DDR) or an antenna.
- A fast track, the stack-up or a reference plane changed.
- A human asks for a track's impedance, loss or crosstalk.

## Inputs

| File | Holds | Who writes it |
|---|---|---|
| The `.kicad_pcb` | The tracks, arcs and vias of each net, the zones of the reference net, the pads, and the stack-up (Board Setup, Physical Stackup) with each dielectric's thickness, epsilon_r and loss tangent. | The design |
| `fields.json`, beside the board | The groups of nets, each with its band and its limits; every limit with its source: document, revision, clause, table and page. | You |

`fields.json`:

```json
{
  "engine": "openems",
  "reference": "GND",
  "groups": [
    {
      "name": "usb3-tx1",
      "nets": ["/SS_TX1_P", "/SS_TX1_N"],
      "ports": ["J1.A3", "U2.17", "J1.A2", "U2.16"],
      "band_ghz": [0.1, 10],
      "limits": [
        {"measure": "insertion_loss_db", "net": "/SS_TX1_P", "max": 1.5,
         "source": "<document, revision, clause, table, page>"}
      ]
    }
  ]
}
```

- `nets`: 1 net is a line, 2 or more are lines that couple, 2 nets of 2
  ports each are also a differential pair. `kind: "antenna"` is 1 net fed
  at 1 pad.
- A zone of a group's net is copper of the group: a patch, a pour of the
  pair's own net. It must be 1 ring with no hole, and the reference pour
  must lie under its corners and an 11 x 11 grid over it.
- `ports`: pads, `REF.PAD`. Each port stands at the free track end of the
  pad's own net nearest the pad, from the nearest plane to the track, 50
  ohm. The end must lie on the pad: no farther from its centre than half
  its diagonal. A pad of another net, a pad named 2 times, a pad far from
  every end and 2 pads on 1 end are refused.
- Without `ports`, the free ends of each net are its ports. A net with more
  than 2 free ends is refused: an open end (a stub) is part of what is
  judged, and a port there would end it in 50 ohm. Name the pads.
- Order: the first port of each net is driven, 1 run for each net. The
  other net's first port is its near end: NEXT is read there, FEXT at its
  last port. Name the pads of each pair in the same order, near end first.
  On 2 nets of 2 ports each, N's near end must lie by P's near end:
  dist(P near, N near) + dist(P far, N far) is less than the sum the other
  way round. Named pads out of that order are refused (`P and N are named
  in opposite orders`: the names do not say which of the 2 nets was named
  far end first); unnamed free ends are put in it.
- `measure`: `impedance_ohm` (min, max), `return_loss_db` (min),
  `insertion_loss_db` (max), `next_db` and `fext_db` (max, with `from`: the
  driven net). Loss and coupling are the worst over the band.
- A pair's measures, with `net` (P, the group's first net) and `pair` (N,
  its second), on a group of 2 nets; another order is refused: `diff_insertion_loss_db`
  (max), `diff_return_loss_db` (min), `diff_impedance_ohm` (min, max). They
  come from Sdd21 = (S21 - S23 - S41 + S43) / 2 and Sdd11 = (S11 - S13 -
  S31 + S33) / 2, ports in the order P near, P far, N near, N far: name the
  pads so. The differential impedance is the symmetric 2-port's formula on
  Sdd11 and Sdd21 with a reference of 2 x `port_ohm`, judged only when both
  nets are uniform.
- An antenna's measure: `resonance_ghz` (min, max), the frequency where
  |S11| is least over the band, and `return_loss_db`. The least is no
  resonance on the band's first or last frequency (`the resonance is not in
  the band`: widen the band), nor where it lies less than 3 dB under the most
  |S11| on either side of it. A dip of 3 dB takes an antenna matched well
  enough or lossy enough: the patch fixture on a lossless substrate
  (`loss_tangent` 0) dips 2.10 dB at 5.74 GHz and gets no resonance (`not
  judged`), where tan d 0.02 gives 5.80 GHz. A low-loss patch fed at its
  edge may show no 3 dB dip; state the substrate's real loss tangent, or
  feed it nearer its match.
- `unstated` in place of min, max and source: the document gives no bound
  for this measure. Write the document, revision, clause and page and why.
  The run prints the measure and `not judged, <your text>`. A measure the
  run made and no limit names prints `not judged, fields.json states no
  limit for it`. `--strict` fails both kinds. Impedance is
  the median over the band of a symmetric 2-port's formula: the image
  impedance of whatever lies between the 2 ports (sections of 30, 80 and 30
  ohm read 49.32). It is the track's impedance only on a uniform line, so it
  is judged only on a net of 2 ports, 1 width, 1 layer and no branch;
  elsewhere its limit is `not judged` with the reason. Its line says `the
  median over N frequencies`. On the line fixture (0.36 mm over 0.2 mm of
  4.5) it reads within 3% of Hammerstad and Jensen's 51.34 ohm, for copper
  as a sheet; 35 um of copper lowers that line to 48.94 ohm (Hammerstad and
  Jensen's thickness correction), which `"copper": "thick"` models.
- `settings` (optional): `copper`, `conductivity_s_m`, `margin_mm`,
  `cells_per_wavelength`, `cells_across_width`, `cells_per_dielectric`,
  `port_ohm`, `frequencies`, `end_criteria_db`, `absorbing_cells`,
  `max_timesteps`, `timeout_s`. `settings` is an object. The counts
  (`cells_across_width`, `cells_per_dielectric`, `absorbing_cells`,
  `max_timesteps`) are whole numbers of 1 or more, `frequencies` 2 or more,
  and `end_criteria_db` is below 0.
- `copper`: `sheet` (the default: a perfect conductor of no thickness),
  `thick` (a perfect conductor of its layer's stack-up thickness, grown
  away from the dielectric; outer layers only, an inner layer is refused) or
  `lossy` (the group's copper and the planes are openEMS conducting sheets
  of `conductivity_s_m` and their layer's thickness: the loss of the copper,
  not its thickness to the field). `conductivity_s_m` is 58e6 S/m unless
  set: the International Annealed Copper Standard, 58 m/(ohm mm2) at 20 C
  (NIST Handbook 100, 1966, 1.2a, p. 2). A run is 1 kind: thick and lossy
  are not both modelled. `thick` and `lossy` take each copper layer's
  thickness from the stack-up; a layer they use with none is refused.
- Each dielectric's `loss_tangent` must be in the stack-up (0 for a
  lossless one); a layer with none, or with one under 0 (a gain medium), is
  refused. One so large that the Debye terms leave eps_inf under 1 is
  refused with the largest that models (0.258 for er 4.5 over 0.1 to 10
  GHz). A lossy dielectric is an
  openEMS Debye material: 2 terms to a decade from 1.5 decades under the
  band to 1.5 over it hold eps'' within 1 % of er tan d over the band, and
  eps' is er at half the band's top, following the loss elsewhere
  (`left_out` gives it at both ends of the band).

The worked examples are `tests/boards/pass-fields-microstrip`,
`tests/boards/fail-fields-stub` and `tests/boards/pass-fields-patch`. Their
limits are made up and say so, but for the patch's resonance, worked out by
hand.

## USB 3: what the specification gives a board

The USB 3.2 Specification, Revision 1.1 (June 2022, free at usb.org),
states 1 number for a host's or a device's own board: an informative
insertion-loss budget of 8.5 dB for the host/device, in Gen 2 (Appendix E,
E.6.4.8, p. 536). That sentence names no frequency; E.6.4.3, p. 532 names
5 GHz as Gen 2's Nyquist frequency. It states no differential impedance and
no return loss for a board: 6.2.1, p. 55 leaves the compliance channels to
white papers outside the specification and the layout to the silicon
maker's guidelines; the 85 ohm and the -17 dB of E.6.4.5, p. 534 are a
re-driver's. So a USB 3 pair's `fields.json` holds:

```json
{"measure": "diff_insertion_loss_db", "net": "/SS_TX1_P", "pair": "/SS_TX1_N", "max": 8.5,
 "source": "USB 3.2 Specification Revision 1.1 (June 2022), Appendix E, E.6.4.8, p. 536 ..."},
{"measure": "diff_impedance_ohm", "net": "/SS_TX1_P", "pair": "/SS_TX1_N",
 "unstated": "USB 3.2 Specification Revision 1.1 (June 2022) states no differential impedance ..."}
```

with `band_ghz` [0.1, 10]: the budget names no frequency, so it is held
at every frequency up to twice Gen 2's Nyquist, the strict side. A band
that ended at 5 GHz gave no result on the Wyvern lane: openEMS samples its
probes for the band's top and wrote 45 samples, too few for the ports to
settle (`did not settle 40 dB under their peak`). The whole text of each entry is in
`tests/test_fields_solver.py` (`USB32_TX1`). A silicon maker's layout
guideline with an impedance is a limit of its own: cite it.

## Steps

1. `workcenter doctor`
   - `ok openems 0.0.35`: go on.
   - `absent openems`: run `sudo ./install.sh --openems`, then this step
     again. If it still says absent, stop: `fields` skips without it.
2. `workcenter fields <project> --model`
   - `fields: wrote the model of N groups`: open
     `build/fields/<group>/model.json`. Check `ports`: 1 port at each end
     you meant, on the right net. Check `planes`: the reference layer
     under the tracks.
   - `FAIL fields ... a file is not as the command reads it`: the next line
     names the file and what is wrong in it. Fix that file and run this
     step again.
   - `... has no GND pour on <layer> under (x, y)`: the reference pour does
     not lie under the whole track. Pour it there, or the model is not the
     board. A zone's cutout is a hole: a track over it is refused the same
     way. `... has a <net> pour on <layer> at (x, y), between it and the GND
     plane`: that pour carries the return current and the model has no
     other net; make the reference that pour's net, or move the pour. `... the
     via ... crosses the GND plane`: the model cuts no antipad; such a group
     is not run (see below).
3. `flock <engine lock> workcenter fields <project>`
   - `PASS fields N held, 0 failed, 0 not judged`: done.
   - `FAIL` with a line `<net> <measure> <value> at <f> GHz above max ...`:
     the copper does not meet the limit. Change the design (width,
     spacing, stack-up, the stub), regenerate the board, run this step
     again. Never change a limit to pass; a limit changes only with its
     document.
   - `FAIL` with `openEMS on port N ended without a result`: the line says
     why. `did not fall to the end criterion`: raise `max_timesteps` in
     `settings`. `did not settle 40 dB under their peak`: the run ended
     before the ports' energy settled after its last loud sample; report
     it with `build/fields/<group>/` (the run is ended only once they have
     settled). `a cell is too small`: report it with
     `build/fields/<group>/model.json`. `Unused
     primitive`: a piece of copper or a port lies on no mesh line; report it
     with `build/fields/<group>/model.json`.
   - `warning: ... not judged, the run gave no such measure`: the limit
     names a measure the run did not make (a coupling from a net that has 1
     port, a loss on an antenna, a pair's measure on nets without 2 ports
     each). Fix the limit or the ports.
   - `warning: ... not judged, fields.json states no limit for it`: the run
     made this measure and no limit names it. Find the limit in the
     interface's document and add it with its source, or add an `unstated`
     entry that names the clause saying there is none.
   - `warning: ... not judged, <text>`: an `unstated` entry. Leave it; report
     it as not judged.
   - `--strict` makes every `not judged` line fail.
   - `SKIP fields engine missing: openEMS`: go back to step 1.
   - `SKIP fields no limit stated: nothing judged`: the run measured and
     wrote its report, and held nothing. Add each limit with its source to
     `fields.json`, then run this step again. It is not a pass.
4. Read `build/fields/report.md`: the measures of each net, the limits, and
   what the model leaves out (copper thickness or conductor loss, plane
   cut-outs, pads, the board's edge). Report a result with those lines.
5. For a fast pair whose loss matters, run step 3 again with `"copper":
   "lossy"` in `settings`, and for one whose impedance matters, with
   `"copper": "thick"`. Report each run's numbers with its kind.

## What a run does not judge

- `sheet` copper has no thickness and no conductor loss; `thick` copper has
  no conductor loss; `lossy` copper has its loss and no thickness to the
  field. On the line fixture `thick` and `lossy` are held to Qucs Technical
  Papers (2014): eq. 11.22 to 11.24, p. 165 (thickness) and eq. 11.80 to
  11.83, p. 171 (conductor loss), in `tests/test_fields_solver.py`. Thick
  copper read 49.60 ohm against 48.94 (1.3 % over, margin 3 %). Lossy
  copper added 0.480 Np/m at 4.5 to 5.5 GHz against 0.741: 35 % under, out
  of its 30 % margin, so the test stands as a strict xfail and a lossy run's
  conductor loss is low by about a third. No surface roughness is modelled. The mesh puts a straight track's edges a third of a
  cell inside its metal (openEMS 0.0.35, Tutorials/MSL_NotchFilter.m, lines
  36 to 39); with the edges on mesh lines the line fixture read 43.14 ohm
  against 51.34. A slanted track has no such lines: its sheet is a stair.
- The dielectric's loss over the band: on the line fixture made 40 mm long
  (copper a sheet) the run reads 1.05 to 1.10 times Qucs Technical Papers
  (2014) eq. 11.79, p. 170, from 2 GHz up, on a band of 0.1 to 10 GHz and
  on one of 0.1 to 20 GHz alike: 3.668 Np/m at 10 GHz against 3.490, 1.926
  at 5 GHz against 1.745 (`tests/test_fields_solver.py`; the 5 GHz margin
  of 10 % is missed, a strict xfail). Under 2 GHz, where the line loses
  little, it scattered from 0.95 to 2.1 times. With `cells_per_dielectric`
  8 it read 1.01 to 1.06 times (0.1 to 10 GHz). The report's `left_out`
  line says so. The loss is on the high side from 2 GHz up: a loss limit's
  pass stands there, a near fail is worth a finer run. The Debye cells
  also move eeff more than their eps' does: the 40 mm line's eeff at 5.05
  GHz, where eps' is er, read 3.3954 against 3.3742 with a plain material
  (+0.6 %), and the patch fixture resonates at 5.80 GHz with tan d 0.02 (a
  Debye material) against 5.74 GHz with `loss_tangent` 0 (a plain one).
  The Debye terms can double a run's time (the 40 mm line: 18 s before
  them, 36 s with them).
- A reference plane is whole over the model's box. The pour, its fill or
  its outline less its cutouts, is checked under each track, at its centre
  and both edges every half its width along it, a point on the pour's edge
  counting as on it; a track with no pour under it is refused. A cut-out
  narrower than half the track's width, or one beside the track, is not
  seen. A pour of another net between a track and its plane is refused.
- No antipad is cut: a group with a via that crosses a reference plane is
  refused, not run.
- An antenna is modelled over a reference plane whole over the box: a
  patch over its ground. A printed monopole or an inverted F, whose copper
  lies off the ground, is refused by the pour check: the model would put a
  plane under it. The air above the board is `margin_mm` deep, then the
  absorbing layers; the patch fixture uses 8 mm. No far field, gain or
  efficiency is computed.
- Pads, parts, solder mask and every net outside the group are left out.
- A |S| of 0 (no wave reached the port) is no measure: its limit is not
  judged, with the reason.

## Where the spectra end

openEMS checks its own end criterion every 4 s of the clock (its log prints
the energy at 4 s, 8 s, 12 s), so where it stopped hung on the machine's
load: 4 runs of 1 stub file stopped after 7189 to 8453 steps, and the Wyvern
lane stopped at 13410 steps in 1 run (46 samples, the ports not settled) and
at 13708 in 3 (47 samples, settled). The command turns that criterion off
and ends the run itself, by openEMS's `ABORT` file, once the ports' energy
has stayed `end_criteria_db` under its peak for 5 samples after its last
sample above that and the box's energy has printed under
`end_criteria_db` too; then it reads the ports' samples only up to that settle
sample. Every sample is the same from run to run, whatever the load or
openEMS's threads (the lane's 46 samples on 4 threads and on 1: alike to the
digit), and a run that ends later adds only quiet samples, so the same file
gives the same numbers. A run that never settles ends at `max_timesteps`, a
fault. On a line longer than the pulse every port is quiet while the wave
crosses: a cut at the first quiet 5 samples missed the far port's wave
(the probes of a 10 mm run with port 2 delayed by 40 samples gave |S21| of
-85 to -66 dB; after its last loud sample, -0.2 to -0.1 dB).

## Another solver

The command calls an engine through 3 functions: `prepare` writes its input
from `model.json`, `run` runs it, `column` returns S[receiver][driven] at
the model's frequencies. A solver that does those 3 takes openEMS's place
under its own name in `fields.json`'s `engine`, with the same model, ports
and limits.
