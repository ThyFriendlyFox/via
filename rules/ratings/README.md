# Rating rule packs

A pack is 1 derating standard as data for `workcenter ratings`: the share of a part's rating that each
stress may reach, with the clause, the table and the page the number stands on. A project names its
pack in `ratings.json`. No limit stands in the command's code, and a pack is never edited to pass.

| File | Document | Revision | Read | Second reader |
|---|---|---|---|---|
| `nasa-eee-inst-002.json` | NASA Goddard, EEE-INST-002 (NASA/TP-2003-212242), "Instructions for EEE Parts Selection, Screening, Qualification, and Derating" | May 2003, with Addendum 1 of April 2008 | 2026-11-17 | no |
| `ecss-q-st-30-11c-rev2.json` | ECSS-Q-ST-30-11C Rev.2, "Space product assurance - Derating - EEE components" | 23 June 2021 | 2026-11-17 | no |

Both documents are free to download and written for space flight hardware. They are stricter than a
consumer product needs, and they are the 2 derating standards that state every limit in public.
Each pack's `document` holds the URL and the SHA256 of the file that was read.

## What a pack holds

```json
{
  "id": "capacitor.tantalum.voltage",
  "stress": "capacitor.voltage",
  "kinds": ["capacitor.tantalum"],
  "max": 0.50,
  "above": {"temperature": "ambient", "celsius": 70, "falls_to": 0.30, "at": 110},
  "where": "section C1, table 4, page 23 of 23, with its note 3"
}
```

`stress` is 1 of the 7 the command computes: `capacitor.voltage`, `resistor.voltage`, `resistor.power`,
`diode.reverse`, `mosfet.drain_source`, `mosfet.gate_source` and `rail.load` (a regulator's output
current). `kinds` are the part kinds of the facts the rule covers: `capacitor` covers
`capacitor.ceramic`. `max` is the share of the rating. `above` makes the share fall in a line from
`celsius` to `falls_to` at `at`, by the project's ambient temperature. A stress with no rule in the pack
is held to the part's own rating, and its line says so.

## What the packs leave out

Limits the 2 documents state and the command does not compute yet, so no pack holds them: a diode's
forward and surge current, a transistor's current and power, every junction temperature, a connector's
voltage and current, a fuse's current, a tantalum capacitor's surge current and ripple, and the
insulation voltage of an inductor.

An integrated circuit's supply and input voltage are held another way. NASA's table M3 derates them
to 0.90 (digital) and 0.80 (linear) of the maximum, and its note sends a device under 5 V to the
maker's recommended operating conditions; ECSS table 6-19 holds a logic device's supply to the
maker's maximum recommended value. The command holds every supply pin to the recommended operating
range its facts state, and every pin to its absolute maximum.

NASA's resistor rows differ by style: the pack holds the row of film chip resistors (RM), 0.60 of the
rated power up to 70 C. Its note 2 also caps the voltage at the square root of the derated power times
the resistance, which the command covers by judging the power.

## A pack of a project's own

A project may name a file of its own as `pack`, by a path from its folder: a customer's derating
table, or a company's. It has the same keys, and each rule its `where`. The command refuses a pack with
an unknown stress, a rule with no `where`, or a document with no URL, SHA256 and date read.
