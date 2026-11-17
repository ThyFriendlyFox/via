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

- `nets`: 1 net is a line, 2 or more are lines that couple. `kind:
  "antenna"` is 1 net fed at 1 pad.
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
- `measure`: `impedance_ohm` (min, max), `return_loss_db` (min),
  `insertion_loss_db` (max), `next_db` and `fext_db` (max, with `from`: the
  driven net). Loss and coupling are the worst over the band. Impedance is
  the median over the band of a symmetric 2-port's formula, and only a net
  of 2 ports has one; its line says `the median over N frequencies`.
- `settings` (optional): `margin_mm`, `cells_per_wavelength`,
  `cells_across_width`, `cells_per_dielectric`, `port_ohm`, `frequencies`,
  `end_criteria_db`, `absorbing_cells`, `max_timesteps`, `timeout_s`.
  `settings` is an object. The counts (`cells_across_width`,
  `cells_per_dielectric`, `absorbing_cells`, `max_timesteps`) are whole
  numbers of 1 or more, `frequencies` 2 or more, and `end_criteria_db` is
  below 0.

The worked examples are `tests/boards/pass-fields-microstrip` and
`tests/boards/fail-fields-stub`. Their limits are made up and say so.

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
     board. `... the via ... crosses the GND plane`: the model cuts no
     antipad; such a group is not run (see below).
3. `flock <engine lock> workcenter fields <project>`
   - `PASS fields N held, 0 failed, 0 not judged`: done.
   - `FAIL` with a line `<net> <measure> <value> at <f> GHz above max ...`:
     the copper does not meet the limit. Change the design (width,
     spacing, stack-up, the stub), regenerate the board, run this step
     again. Never change a limit to pass; a limit changes only with its
     document.
   - `FAIL` with `openEMS on port N ended without a result`: the line says
     why. `did not fall to the end criterion`: raise `max_timesteps` in
     `settings`. `did not settle 40 dB under their peak`: openEMS stopped
     before the ports' energy settled; lower `end_criteria_db` (-50). `a cell is too small`: report it with
     `build/fields/<group>/model.json`. `Unused
     primitive`: a piece of copper or a port lies on no mesh line; report it
     with `build/fields/<group>/model.json`.
   - `warning: ... not judged, the run gave no such measure`: the limit
     names a measure the run did not make (a coupling from a net that has 1
     port, a loss on an antenna). Fix the limit or the ports.
     `--strict` makes these lines fail.
   - `SKIP fields engine missing: openEMS`: go back to step 1.
   - `SKIP fields no limit stated: nothing judged`: the run measured and
     wrote its report, and held nothing. Add each limit with its source to
     `fields.json`, then run this step again. It is not a pass.
4. Read `build/fields/report.md`: the measures of each net, the limits, and
   what the model leaves out (copper thickness, conductor loss, plane
   cut-outs, pads, the board's edge). Report a result with those lines.

## What a run does not judge

- Copper is a sheet: no thickness and no conductor loss. Loss is the
  dielectric's alone.
- A reference plane is whole over the model's box. The pour is checked
  under each track, at its centre and both edges every half its width
  along it; a track with no pour under it is refused. A cut-out narrower
  than half the track's width, or one beside the track, is not seen.
- No antipad is cut: a group with a via that crosses a reference plane is
  refused, not run.
- Pads, parts, solder mask and every net outside the group are left out.
- A |S| of 0 (no wave reached the port) is no measure: its limit is not
  judged, with the reason.

## Where the spectra end

openEMS checks its end criterion every 4 s of the clock (its log prints the
energy at 4 s, 8 s, 12 s), so where it stops hangs on the machine's load:
4 runs of 1 stub file stopped after 7189 to 8453 steps. The command lets openEMS run until the box's
energy falls 10 dB past `end_criteria_db`, then reads the ports' samples
only up to the first sample where the ports' energy has stayed
`end_criteria_db` under its peak for 5 samples. Every sample up to there is
the same from run to run, so the same file gives the same numbers.

## Another solver

The command calls an engine through 3 functions: `prepare` writes its input
from `model.json`, `run` runs it, `column` returns S[receiver][driven] at
the model's frequencies. A solver that does those 3 takes openEMS's place
under its own name in `fields.json`'s `engine`, with the same model, ports
and limits.
