# The reference library

`index.json` names each document a rule of the workcenter cites: the standards of the rating packs
(`rules/ratings/*.json`) and of the board rule pack (`rules/board/*.json`), the documents of the
constants of `workcenter copper` (`rules/copper/*.json`, a table `documents: {id: {...}}`), the
documents of the fast interfaces (`rules/interfaces/*.json`, the same table), the fab pages of the fab
rule files (`rules/*.kicad_dru`), the datasheets of the fixtures' facts (`tests/boards/**/facts/*.json`),
and each document the tools and the tests cite in their code (`tools/*.py`, `tools/workcenter`,
`tests/*.py`, `tests/boards/*.py`, the lead's tools `ee-agent-kit/lead/*.py`). A document served in a zip (usb.org's specifications) is held by the
zip's SHA256: the rule names it as `zip_sha256`, beside the `sha256` of the file inside. The repository
holds the index and the rules, never a document: the makers' and the issuers' terms forbid a copy.

An entry is 1 of 3 sorts:

- **Held** (`standard`, `application note`, `datasheet`, `report`): the URL and the SHA256 of the copy
  the rule was written from. A report is a held copy that is no standard, note or datasheet: the Qucs
  project's technical papers, a laboratory's report.
- **A web page** (`web page`): a page has no fixed copy. Samsung's part page carries a session token
  and a time stamp, so its bytes differ on every fetch. The entry holds the values read from it on a
  date, each as the text the page says (`says`) and the rule that takes it (`for`).
- **Cited and not held** (`paper`, `book`): no free copy. The entry names the authors, where it was
  published, the edition, where the cited equations stand, and why no copy is held.

| Id | Kind | Number | Revision |
|---|---|---|---|
| `nasa-eee-inst-002` | standard | EEE-INST-002 (NASA/TP-2003-212242) | May 2003, with Addendum 1 of April 2008 |
| `ecss-q-st-30-11c-rev2` | standard | ECSS-Q-ST-30-11C Rev.2 | 23 June 2021 |
| `ecss-q-st-70-12c-rev1` | standard | ECSS-Q-ST-70-12C Rev.1 | 30 April 2025 |
| `ti-spraar7j` | application note | SPRAAR7J | J, November 2018, revised February 2023 |
| `usb-20` | standard | usb_20.pdf in usb_20_20250603.zip | 2.0, April 27, 2000, as the zip of 2025-06-03 holds it |
| `usb-31-legacy-cable` | standard | USB 3.1 Legacy Cable and Connector Revision 1.0.pdf | 1.0, September 22, 2017 |
| `usb-32` | standard | USB 3.2 Revision 1.1.pdf in usb_32_202206_1.zip | 1.1, June 2022 |
| `ti-slvsdg1` | datasheet | SLVSDG1C (TLV62569) | December 2016, revised October 2017 |
| `ti-sces579` | datasheet | SCES579J (SN74AUP1G17) | June 2004, revised September 2017 |
| `ti-sces351` | datasheet | SCES351Y (SN74LVC1G17) | July 2001, revised October 2025 |
| `vishay-20035` | datasheet | 20035 (D/CRCW e3) | 14-Apr-2026 |
| `vishay-45199` | datasheet | 45199 (VJ Commercial Series) | 08-May-2026 |
| `samsung-cl10a106kp8nnn` | web page | CL10A106KP8NNN | 5 values read on 2026-11-17 |
| `coilcraft-806` | datasheet | 806 (XAL40xx) | Revised 02/25/26 |
| `bourns-srn2010ta` | datasheet | SRN2010TA | REV. 06/25 |
| `ti-sbvs320` | datasheet | SBVS320D (TLV755P) | November 2017, revised September 2024 |
| `ti-slva477c` | application note | SLVA477C | December 2011, revised September 2026 |
| `ti-spra953d` | application note | SPRA953D | December 2003, revised March 2024 |
| `ti-snva419c` | application note | SNVA419C (AN-2020) | April 2010, revised April 2013 |
| `nbs-hb100` | standard | NBS Handbook 100 | issued February 21, 1966 |
| `ietf-rfc6585` | standard | RFC 6585 | April 2012 |
| `ietf-rfc9110` | standard | RFC 9110 (STD 97) | June 2022 |
| `freedesktop-basedir-0.8` | standard | XDG Base Directory Specification 0.8 | Version 0.8, 08th May 2021 |
| `bipm-si-brochure-9` | standard | SI Brochure, 9th edition | 2019, V4.01 of June 2026 |
| `hammerstad-jensen-1980` | paper | IEEE MTT-S Int. Microwave Symp. Digest 1980 | pp. 407-409 |
| `incropera-heat-and-mass-transfer` | book | Fundamentals of Heat and Mass Transfer | edition not named where cited |
| `pozar-microwave-engineering-4` | book | Microwave Engineering | 4th edition |
| `sierra-web-pcb-order` | web page | Sierra Circuits, Online PCB Fab Capabilities | 6 values read on 2026-11-17 |
| `sierra-web-pcb-specs` | web page | Sierra Circuits, Web PCB specs | 4 values read on 2026-11-17 |
| `jlcpcb-pcb-capabilities` | web page | JLCPCB, PCB Capabilities | 8 values read on 2026-11-17 |
| `pcbway-capabilities` | web page | PCBWay, PCB Manufacturing Capabilities | 6 values read on 2026-11-17 |
| `oshpark-two-layer` | web page | OSH Park, 2 Layer Prototype Service | 6 values read on 2026-11-17 |
| `nist-codata-2022-z0` | web page | NIST, CODATA Value: characteristic impedance of vacuum | 2 values read on 2026-11-17 |
| `nist-codata-2022-c` | web page | NIST, CODATA Value: speed of light in vacuum | 2 values read on 2026-11-17 |
| `nist-dlmf-19.8` | web page | NIST DLMF, section 19.8 | 1 value read on 2026-11-17 |
| `qucs-technical-papers` | report | Qucs Technical Papers | the PDF of 2014-10-18 |
| `matthaei-ad0402852` | report | DTIC AD0402852 (Matthaei, Young, Jones, Volume I) | January 1963 |
| `nxp-um10204` | standard | UM10204 | Rev. 7.0, 1 October 2021 |

The last 5 entries joined on 2026-11-17 when the index's check met the high-speed pieces:
`rules/interfaces/constants.json` takes its 2 constants from NIST's 2 pages, and
`tests/test_xsection.py` holds the cross-section solver to the 2 reports and to DLMF 19.8.5. Each copy
was fetched that day under the workcenter's own name. `workcenter references check` called each copy
`same`: the 2 reports by the SHA256 their citing file gives in part, the 3 pages by their values.

The last entry joined on 2026-11-18: `tools/freqplan.py` and `tests/test_freqplan.py` give NXP's I2C-bus
specification as the source of an I2C clock, and no family read NXP's numbers. Its copy was fetched that
day, and `workcenter references check` called it `same`. Rev. 7.0 gives the SCL clock frequency in
table 11, page 44; the 2 files said table 10, the I/O stages, and now say table 11.

On 2026-11-17 `workcenter references fetch` asked for the 25 held documents and web pages of the index
as it stood before the documents of `rules/interfaces/` joined it, under the workcenter's own name:
`24 kept, 1 changed, 0 moved, 0 refused, 0 gone, 0 not given, 0 not reached, 3 not held`. The title,
number and revision of each held entry were read from the first page of its copy. The 1 changed is
`ti-sbvs320`: TI's copy of that day prints the same revision, SBVS320D of September 2024, with other
bytes than the copy of 2026-10-29 the index names. Its rule's numbers were not read again from the new
copy, so the index keeps the old SHA256. `ti-spraar7j`, `usb-20`, `usb-31-legacy-cable` and `usb-32`,
the documents of `rules/interfaces/`, were fetched together the same day: `4 kept, 0 changed, 0
refused`; usb.org gave each specification as the zip the index names.

The values of each web page were read on 2026-11-17 from the page as fetched that day. Each fab page's
values carry the numbers its `.kicad_dru` file takes; some fab files quote a page with other punctuation
than the page has today, so an entry's `says` is the page's own text. Samsung's 5 values are its
part table and 4 points of its graph data: DC bias -71.71164046920306 % at 5 V and -88.79327416302891 %
at 10 V; temperature +2.279548422744333 % at -55 C and -14.72482795860936 % at 85 C. The facts of
`tests/boards/fail-sim-bias` take each as 1 + its value / 100. On 2026-11-17, 3 fetches each of
Samsung's, JLCPCB's and OSH Park's pages gave 3 SHA256s for each page. Every value stood on the first
copy and on the third; the second was not read for its values.

## The 3 commands

- `workcenter references fetch [ID ...] [--to DIR]` asks each URL once and keeps what it gets in DIR,
  by default `$XDG_CACHE_HOME/ee-workcenter/references` or `~/.cache/ee-workcenter/references`. A
  relative `XDG_CACHE_HOME` is ignored (XDG Base Directory Specification 0.8, section 2). DIR may not
  lie inside a repository, and may not be a file. `DIR/ledger.json` holds each answer, and a later run
  reads it and asks again for none. `--again ID` asks once more. A ledger of another shape is refused on
  1 line that names the file and the key.
- `fetch` judges a held copy by its SHA256 (`kept` or `changed`) and a web page by its values: `kept`
  when every value stands on the page, `moved` when 1 is gone. A value stands when its text, split at
  ` ... `, is found in order in the page's text: tags dropped, entities read, white space collapsed. A
  part that starts or ends with a digit stands only at the bounds of the page's number: `0.2` does not
  stand in `0.25`. ` ... ` skips 200 characters at most, and skips no text where the next part's first
  word stands: a later row that says the old number does not hold a row whose number moved. On
  2026-11-17 the 5 split values of the index skipped 9 to 161 characters on the pages fetched that day.
  A page whose token moved is `kept`; a page whose number moved is `moved`. A paper or a book is printed
  `not held`, with why, and nothing is fetched for it.
- `fetch` files 3 answers in the ledger: a copy, a refusal (HTTP 401 or 403) and a file gone (HTTP 404
  or 410). It files nothing for an answer that gives no copy and no verdict: HTTP 429 (RFC 6585,
  section 4, p 3: too many requests) or a 5xx (RFC 9110, section 15.6: the server erred) is `not given`,
  and no answer at all is `not reached`. Both are asked again on the next run, and exit with 2.
- `workcenter references check FILE [--id ID] [--keep]` says whether a file a person downloaded is the
  copy an entry names, or, for a web page, whether every value stands in it. `--keep` files it in DIR,
  as `fetch` would have, with the same refusals of DIR.
- `workcenter references rules [PATH ...]` reads each document a rule file names, under a key `document`
  or `source` or in a `documents` object of documents by id, and fails 1 line for each one the index
  lacks or names at another URL, or that has no URL and no SHA256. A source whose URL is a web page's is
  held by that URL. It reads each URL of a `.kicad_dru` file, to white space or a quote, and fails 1 the
  index has no entry for. It reads tool code and tests (next section). It reads the text of a
  `.kicad_dru` file and every other text of a JSON rule file for documents' names as it reads code's,
  with no `CITES`: a citation of an entry's name is held, a citation of any other name fails, and a name
  with no place beside it is printed `not judged`. With no PATH it reads the files the globs under
  `rules` and `code` in `index.json` find. `make verify` runs it (`tests/test_references.py`,
  `tests/test_references_code.py`).
- A source with no document to pin says so in its `document`: `no datasheet: <why>` or
  `no document: <why>`. Only such a source is printed as `not judged`, with its reason. A source that
  names a datasheet by name alone fails, as does a `source` or `document` that is a text other than an
  index id or an id of the file's own `documents` object.

## A document cited in code

A tool or a test names the documents it cites in 1 declared way, a module-level `CITES`:

```python
# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {"ti-slva477c": "section 2, the efficiency; equations 1, 2, 4 and 11"}
```

`references rules` reads `CITES` without running the file. It fails an id the index lacks, a place
that is not a text, and a `CITES` that is no dict of texts. Then it finds each document's name in the
file: each entry's `names`, and each number of a family under `numbers` in `index.json` (TI's
literature numbers, RFCs, ECSS, EEE-INST, JESD, J-STD, IPC and its test methods, IEC, MIL, IEEE,
Analog Devices' notes, NBS handbooks, NXP's user manuals and notes). A family's number names an entry when it is the entry's name
with spaces and hyphens set aside: `RFC6585` is `RFC 6585`. The text of a URL is no name. A name with a
section, table, page, clause, equation, annex, figure or chapter within 200 characters after it is a
citation. The place is read in any case and abbreviated: `Table 6-1`, `Fig. 3`, `p. 12`, `pp. 407`,
`eq. 4`, `§2.1`. A citation fails unless it is an entry's name and `CITES` names that entry. A name
with none of them beside it is a mention, printed as `not judged` with that reason, unless `CITES`
names it.

A revision or an edition written between an entry's name and its place must be the entry's:
`Rev.1`, `2nd edition` or a version such as `0.6` right after the name. Another one fails, though
`CITES` names the entry: the index holds 1 copy, and Rev.1 is another document.

## An entry

```json
{
  "id": "ti-slvsdg1",
  "kind": "datasheet",
  "maker": "Texas Instruments",
  "number": "SLVSDG1C",
  "names": ["SLVSDG1C"],
  "title": "TLV62569 2-A High Efficiency Synchronous Buck Converter in SOT Package",
  "revision": "December 2016, revised October 2017",
  "url": "https://www.ti.com/lit/ds/symlink/tlv62569.pdf",
  "sha256": "1ba6f55dfe678d06d563acd6632f1f950a497d812270806021097b55cd81d3c4",
  "read": "2026-11-17"
}
```

A held entry has every field above but `names`. A standard names its `issuer`, a note or a datasheet
its `maker`. `read` is the date the copy was read. `names` lists the texts code names it by; give it
only a text no other thing is called.

A web page has `id`, `kind`, `maker` or `issuer`, `title`, `url`, `read` and `values`, and no `sha256`:

```json
"values": [{"says": "Minimum Trace and Space 4 mil (0.004 in/0.1016 mm)", "for": "sierra-web: trace width 4 mil"}]
```

A paper or a book has `id`, `kind`, `authors`, `title`, `published`, `edition`, `cited` and `no_copy`,
and no `url` or `sha256`.

The command refuses an entry with a field of its sort left out, a SHA256 that is not 64 lower-case hex
digits, a URL that is not whole, a web page with a SHA256 or with no values, a value with no text but
` ... `, or an id or a SHA256 that another entry has. It refuses an index whose `rules` or `code` is not a list of globs from the
repository's root, and a `numbers` pattern that is not a regular expression.

## What the index does not cover

- A document cited in code by a name that is no entry's `names` and no family's number, such as
  CODATA 2018 in `tools/fields.py`, is not found. A family covers the numbers of its pattern only:
  a TI number written in lower case (`slva477c`) or a maker's note of a family the index does not list
  is not found either.
- A revision is read only when it is written between the name and its place, as `Rev.N`, `Nth
  edition` or a version right after the name. A revision written another way (a date, `revised 2019`)
  is not judged.
- 3 mentions of IPC-2581 (the file format of `workcenter fabfiles`), 1 of JESD51 in
  `tools/thermal.py` and 1 of IPC-6012 (the class of Sierra's order, `rules/sierra-circuits-web.kicad_dru`)
  have no place beside them and are printed `not judged`.
- The edition of Incropera is not named where `tests/test_copper.py` cites it, and the 3 cited works
  were not read on 2026-11-17: their places are those the citing files give.
