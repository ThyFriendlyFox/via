# Rating rule packs

A pack is 1 derating standard as data for `workcenter ratings`: the share of a part's rating that each
stress may reach, with the clause, the table and the page the number stands on. A project names its
pack in `ratings.json`. No limit stands in the command's code, and a pack is never edited to pass.

| File | Document | Revision | Read | Second reader |
|---|---|---|---|---|
| `nasa-eee-inst-002.json` | NASA Goddard, EEE-INST-002 (NASA/TP-2003-212242), "Instructions for EEE Parts Selection, Screening, Qualification, and Derating" | May 2003, with Addendum 1 of April 2008 | 2026-11-17 | 2026-11-17 |
| `ecss-q-st-30-11c-rev2.json` | ECSS-Q-ST-30-11C Rev.2, "Space product assurance - Derating - EEE components" | 23 June 2021 | 2026-11-17 | 2026-11-17 |

Both documents are free to download, and both are written for space flight hardware: NASA's for
parts on its Goddard flight projects, ECSS's for parts approved for space. The workcenter ships them
because every limit in them is public and stands in a table. A product on the ground may hold them, or
a pack of its own. Each pack's `document` holds the URL and the SHA256 of the file that was read.

## What a pack holds

```json
{
  "id": "capacitor.tantalum.voltage",
  "stress": "capacitor.voltage",
  "kinds": ["capacitor.tantalum"],
  "max": 0.50,
  "above": {"temperature": "ambient", "celsius": 70, "falls_to": 0.30, "at": 110},
  "where": "section C1, table 4, page 23 of 23, the row Tantalum, Solid, ..."
}
```

`stress` is 1 of the 12 the command computes: `capacitor.voltage`, `resistor.voltage`, `resistor.power`,
`diode.reverse`, `diode.forward_current`, `mosfet.drain_source`, `mosfet.gate_source`,
`mosfet.drain_current`, `fuse.current`, `ferrite.current`, `switch.current` and `rail.load` (a
regulator's output current). The current of a diode, a transistor, a fuse, a ferrite and a switch is
judged when the project states the current through the part.

`kinds` are the part kinds of the facts the rule covers: `capacitor` covers `capacitor.ceramic`. For
`rail.load` the kind is `ic.` and the part's family, so `ic.regulator` covers both kinds of regulator
and `ic` every part. The first rule of the file that covers a part is the one that holds it. A kind
that is no kind of the facts and no start of one is refused: its rule would hold nothing, and its parts
would be held to their own ratings.

`max` is the share of the rating. `above` makes the share fall in a line from `celsius` to `falls_to`
at `at`; past `at` the share is 0, since the document allows the part no further. The temperature is
the project's ambient. ECSS states its temperatures at the part's case: the command judges them at the
ambient all the same, the part's own heating not counted, and the report's notes say so. With no
ambient stated a rule is judged as under its `celsius`, and the notes say that too.

A stress with no rule in the pack is held to the part's own rating, and its line says so.

## How each pack reads its document

NASA's document is written for hermetic parts of military styles, and the workcenter's parts are
plastic and commercial. Where the document has a row for such parts the pack holds that row:

- A regulator's output current: table 4 of section M4, for plastic parts: 0.7 for a linear or
  mixed-signal part and 0.8 for a digital one. Section M3, for hermetic parts, has 0.8 for both.
- A resistor's power: the row "Others" of section R2's table 4, 0.5, for a part of no military style.
  Its note 4 takes the 2 temperatures from the maker and puts zero power half-way between them. The
  pack holds them for a chip resistor rated at 70 C that reaches zero power at 155 C: 112.5 C. A
  part with other temperatures needs a pack of the project's own.
- A diode and a transistor: table 4 of section S1. The section says it does not cover plastic parts,
  and the document has no other row for them.
- A tantalum capacitor: the row of the solid kind, 0.50 up to 70 C and 0.30 at 110 C, for every
  tantalum kind, with a line between the 2 points as note 3 draws it for the wet-slug row.

Not held from NASA's capacitor table: its greatest ambient temperatures for ceramic (110 C) and
film (85 C) parts, and its note 2, which asks military ceramic styles on under 10 V for a 100 V rating.

In the ECSS pack the 2 resistor rules are the chip table (6-30) of 8 resistor tables, and the film
capacitor rule is table 6-4 for a part rated above 100 C. Where a table adds "or the SEE safe
operating area, whichever is lower", the pack holds the factor alone.

## What the packs leave out

Limits the 2 documents state and the command does not compute, among others: every junction
temperature and power dissipation, a diode's surge current, a zener's and a suppressor's power, a
connector's voltage and current, a switch's voltage, a tantalum capacitor's surge current, reverse
voltage and ripple, the insulation voltage of an inductor, and a regulator's input less its output.
Both documents derate the sum of a capacitor's steady voltage and its ripple; the command judges
the steady voltage.

3 stresses the command computes have no rule in either pack: the current through a fuse, a ferrite and
a switch. Each is held to the part's own rating. NASA's table 4 of section F3 derates a cartridge fuse
by its rating, from 50 % for 2 A and above to 25 % for 1/8 A, and ECSS's table 6-17 a cermet fuse. A
rule of a pack is 1 share for a kind of part, and neither table is in a pack yet.

An integrated circuit's supply and input voltage are held another way. Table 4 of NASA's section M3
derates a hermetic part's to 0.90 (digital) and 0.80 (linear) of the maximum, and its note 1.1 sends
a device under 5 V to the maker's recommended operating conditions; section M4 holds a plastic part's
supply between its nominal and its maximum rating. ECSS table 6-19 holds a logic device's supply to
the maker's maximum recommended value, and table 6-21 a linear device's to 90 % of the maximum
rated value. The command applies none of these factors. It holds every supply pin to the recommended
operating range its facts state, every signal pin to the range its facts recommend, and every pin
to its absolute maximum.

NASA's note 2 on resistors also caps the voltage at the square root of the derated power times the
resistance, which the command covers by judging the power.

## A pack of a project's own

A project may name a file of its own as `pack`, by a path from its folder: a customer's derating
table, or a company's. It has the same keys, and each rule its `where`. The command refuses a pack with
an unknown stress, a rule with no `where`, a share that rises with the temperature (`falls_to` above
`max`), or a document with no URL, SHA256 and date read. A URL is written whole, as
`https://example.com/file.pdf`, a SHA256 as 64 hex digits and a date as `2026-11-17`; `second_reader`
is `no` or the date.

A run that such a file judged says so. The first line, `report.md` and `report.json` name the pack
by the path `ratings.json` gives, with `(the project's own)` after it:
`pack house.json (the project's own)`. The name inside the file is not printed, so a copy of a shipped
pack with rules taken out does not pass for the shipped pack. A file of `rules/ratings/` is the
workcenter's pack by whatever path a project names it.
