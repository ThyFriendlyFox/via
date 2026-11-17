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
- `ports`: pads, `REF.PAD`. Each port stands at the free track end nearest
  its pad, from the nearest plane to the track, 50 ohm. Without `ports`,
  every free end of each net is a port. The first port of each net is
  driven, 1 run for each net.
- `measure`: `impedance_ohm` (min, max), `return_loss_db` (min),
  `insertion_loss_db` (max), `next_db` and `fext_db` (max, with `from`: the
  driven net). Loss and coupling are the worst over the band.
- `settings` (optional): `margin_mm`, `cells_per_wavelength`,
  `cells_across_width`, `cells_per_dielectric`, `port_ohm`, `frequencies`,
  `end_criteria_db`, `absorbing_cells`, `max_timesteps`, `timeout_s`.

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
3. `flock <engine lock> workcenter fields <project>`
   - `PASS fields N held, 0 failed, 0 not judged`: done.
   - `FAIL` with a line `<net> <measure> <value> at <f> GHz above max ...`:
     the copper does not meet the limit. Change the design (width,
     spacing, stack-up, the stub), regenerate the board, run this step
     again. Never change a limit to pass; a limit changes only with its
     document.
   - `FAIL` with `openEMS on port N ended without a result`: the line says
     why. `did not fall to the end criterion`: raise `max_timesteps` in
     `settings`. `a cell is too small`: report it with
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
- A reference plane is whole over the model's box. A cut-out under a track
  is not seen.
- Pads, parts, solder mask and every net outside the group are left out.

## Another solver

The command calls an engine through 3 functions: `prepare` writes its input
from `model.json`, `run` runs it, `column` returns S[receiver][driven] at
the model's frequencies. A solver that does those 3 takes openEMS's place
under its own name in `fields.json`'s `engine`, with the same model, ports
and limits.
