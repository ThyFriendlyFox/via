# Interfaces

1 file for each interface `workcenter highspeed` knows. A project names one in its `interfaces.json`
(`.claude/skills/highspeed/SKILL.md`). Each limit names its document (`doc`, a key of `documents`) and
the clause, table and page it comes from (`where`). A limit the documents do not set has `not_stated`
with what they say instead. A limit they set that the command does not judge has `not_judged` with the
reason. The command prints both as not judged.

| File | Impedance | Length | Skew | Vias | Plane | Not judged | Document |
|---|---|---|---|---|---|---|---|
| `usb2.json` | 90 ohm differential, 76.5 to 103.5 (+-15 %) | 4 ns of delay, both boards together | not stated | - | not stated | - | USB 2.0, 7.1.1.3 (page 129), 7.1.6.1 (page 142) |
| `usb3.json` | 90 ohm differential, no band for a board | not stated | not stated | - | not stated | - | USB 3.1 Legacy Connector and Cable, revision 1.0, 5.6.1.3.2.1 (page 54) |
| `ti-am57xx-usb2.json` | 81 to 99 ohm differential | 304.8 mm (12000 mil) | 1.27 mm (50 mil) | 4 a net | solid ground | single-ended 40.5 to 49.5 ohm; 0 stubs | TI SPRAAR7J, Table A-2 (page 16), section 2.4 (page 6) |
| `ti-am57xx-usb3.json` | 83.7 to 96.3 ohm differential | 88.9 mm (3500 mil) | 0.127 mm (5 mil) | 2 a net | solid ground | 0 stubs | TI SPRAAR7J, Table A-2 (page 16), section 2.4 (page 6) |

`-`: the file has no such limit, and the command prints nothing for it.

A mil is 0.0254 mm. `constants.json` holds the impedance of vacuum and the speed of light, CODATA 2022.

Each document was fetched as `ee-workcenter/1.0` on 2026-11-17; its URL and SHA256 are in the file. The
repository holds the numbers, not the documents.
