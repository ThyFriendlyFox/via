# Copper and board constants

`materials.json` holds the 5 numbers `workcenter copper` takes from documents, each with the document,
its revision, the clause or table and the page. No such number stands in `tools/copper.py`. A project
states its own limits and its air in `copper.json`; it may state its own `h` there, with its source.
The barrels' plating is not a constant of this file: it is the board's own setting, or `copper.json`'s
`plating` with its source (the fab's specification), and the report names which.

| Key | Value | Document | Where |
|---|---|---|---|
| `copper_resistivity` | 1.7241e-8 Ohm m at 20 C | NBS Handbook 100, Copper Wire Tables, issued February 21, 1966 | section 2a, page 3 |
| `copper_temperature_coefficient` | 0.00393 per C from 20 C | the same | section 2b, page 3 |
| `copper_thermal_conductivity` | 400 W/m K | TI SNVA419C (AN-2020), Thermal Design By Insight, Not Hindsight, revised April 2013 | table 1, page 4 |
| `fr4_thermal_conductivity` | 0.23 W/m K | the same | table 1, page 4 |
| `air_natural_convection` | 10 W/m2 K on each face | the same | table 1, page 4: "a first order approximation" for natural convection |

Both documents are free to download; `materials.json` holds each URL and the SHA256 of the file read.
The TI note gives typical values: a laminate's own datasheet, or a measured `h` for the product's
enclosure, is better, and a reading of the built board replaces both.
