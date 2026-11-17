# The reference library

`index.json` names each document a rule of the workcenter cites: the standards of the rating packs
(`rules/ratings/*.json`) and the datasheets of the fixtures' facts (`tests/boards/**/facts/*.json`).
Each entry holds the maker or the issuer, the number, the title, the revision, the URL and the SHA256 of
the copy the rule was written from. The repository holds the index and the rules, never a document:
the makers' and the issuers' terms forbid a copy.

| Id | Kind | Number | Revision |
|---|---|---|---|
| `nasa-eee-inst-002` | standard | EEE-INST-002 (NASA/TP-2003-212242) | May 2003, with Addendum 1 of April 2008 |
| `ecss-q-st-30-11c-rev2` | standard | ECSS-Q-ST-30-11C Rev.2 | 23 June 2021 |
| `ti-slvsdg1` | datasheet | SLVSDG1C (TLV62569) | December 2016, revised October 2017 |
| `ti-sces579` | datasheet | SCES579J (SN74AUP1G17) | June 2004, revised September 2017 |
| `ti-sces351` | datasheet | SCES351Y (SN74LVC1G17) | July 2001, revised October 2025 |
| `vishay-20035` | datasheet | 20035 (D/CRCW e3) | 14-Apr-2026 |
| `vishay-45199` | datasheet | 45199 (VJ Commercial Series) | 08-May-2026 |
| `coilcraft-806` | datasheet | 806 (XAL40xx) | Revised 02/25/26 |
| `bourns-srn2010ta` | datasheet | SRN2010TA | REV. 06/25 |

On 2026-11-17 `workcenter references fetch` got all 9 under the workcenter's own name, and each copy
had the SHA256 its entry names: `9 kept, 0 changed, 0 refused`. The title, number and revision of each
entry were read from the first page of that copy.

## The 3 commands

- `workcenter references fetch [ID ...] [--to DIR]` asks each URL once and keeps what it gets in DIR,
  by default `~/.cache/ee-workcenter/references`. DIR may not lie inside a repository. `DIR/ledger.json`
  holds each answer, and a later run reads it and asks again for none. `--again ID` asks once more.
- `workcenter references check FILE [--id ID] [--keep]` says whether a file a person downloaded is the
  copy an entry names. `--keep` files it in DIR, as `fetch` would have.
- `workcenter references rules [PATH ...]` reads each document a rule file names, under a key `document`
  or `source`, and fails 1 line for each one the index lacks or names at another URL. With no PATH it
  reads the files the globs under `rules` in `index.json` find. `make verify` runs it
  (`tests/test_references.py`).

## An entry

```json
{
  "id": "ti-slvsdg1",
  "kind": "datasheet",
  "maker": "Texas Instruments",
  "number": "SLVSDG1C",
  "title": "TLV62569 2-A High Efficiency Synchronous Buck Converter in SOT Package",
  "revision": "December 2016, revised October 2017",
  "url": "https://www.ti.com/lit/ds/symlink/tlv62569.pdf",
  "sha256": "1ba6f55dfe678d06d563acd6632f1f950a497d812270806021097b55cd81d3c4",
  "read": "2026-11-17"
}
```

`kind` is `standard`, `application note` or `datasheet`. A standard names its `issuer`, a note or a
datasheet its `maker`. `read` is the date the copy was read. The command refuses an entry with a field
left out, a SHA256 that is not 64 lower-case hex digits, a URL that is not whole, or an id or a SHA256
that another entry has.

## What the index does not cover

`rules/sierra-circuits-web.kicad_dru` cites 2 web pages of the fab by URL. A web page has no fixed copy
to hash, so the index holds no entry for it, and `references rules` reads no `.kicad_dru` file.
