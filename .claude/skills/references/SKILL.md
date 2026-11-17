---
name: References
description: Keeps the index of the standards, makers' application notes and datasheets the workcenter's rules cite - each with its maker or issuer, number, title, revision, URL and SHA256 - fetches each once under the workcenter's own name into a folder outside every repository, checks a file a person downloaded against it, and fails a rule that names a document the index lacks.
---

# References

A rule is only as good as the document it was read from. A limit read from
revision B is wrong once the maker publishes revision C, and a reader who
cannot get the same copy cannot check the rule. `rules/references/index.json`
names the copy each rule was written from by its SHA256.
`workcenter references` fetches those copies, says when a site changed one,
and fails a rule whose document the index lacks.

The repository holds the index and the rules, never a document: the makers'
and the issuers' terms forbid a copy. A site that refuses the workcenter's
name is not asked under another.

## When

- Before a schematic review: get the documents the rules cite, so each
  limit can be read where the rule says it stands.
- A rule pack or a facts file gains a document, or its document's revision
  changes.
- `make verify` fails in `tests/test_references.py`.

## Steps

1. Check that every document a rule names is in the index:

   ```sh
   python3 tools/workcenter references rules
   ```

   - `fail <file> <place>: <document>, SHA256 <hash> is not in the index ...`:
     the rule cites a copy the index does not name. Fetch that copy (step 3
     with its URL in a new entry), read its first page, and add an entry
     with every field (`rules/references/README.md`, "An entry"). Never
     change the rule's SHA256 to one the index has: the rule was read from
     its own copy.
   - `fail ... is at <url>, the index names <id> at <url>`: 1 copy, 2 URLs.
     Write the URL the index names into the rule, or move the entry to the
     new URL when the maker moved the file.
   - `fail ... names <url> and no SHA256 ...`: the rule cites a document
     with no copy. Fetch it, and write the SHA256 into the rule and the
     index.
   - `fail ... names no URL and no SHA256 ...`: the rule names a document
     by name alone. Fetch its copy and write the URL and the SHA256 into
     the rule and the index. If the part truly has no datasheet, write
     `no datasheet: <why>` as the source's `document`.
   - `fail ... sha256 ... is not 64 hex digits` or `url ... is not a whole
     URL`: write the field as a string, in that form.
   - `not judged <file> <place>: names no document ... (no datasheet:
     <why>)`: a part made up or with no datasheet, as its source says.
     Nothing to do; the line says why it is not judged.
   - The last line counts the documents. Exit 0: done.

2. If a run prints `fail rules/references/index.json documents[N] <id>:
   ...`, the index itself has a fault: fill the field it names, in the form
   it names. No other line is judged until the index is whole.

3. Get the documents, once:

   ```sh
   python3 tools/workcenter references fetch
   ```

   Name ids to fetch some (`references fetch ti-slvsdg1`). The copies go to
   `~/.cache/ee-workcenter/references`, or to `--to DIR` outside every
   repository. Each line is 1 document:

   - `kept <id>: ...`: the copy is the one the rules were written from.
     Read the limits there.
   - `changed <id>: <url> gives SHA256 <a>, the index names <b>; the copy
     is in <file>`: the maker changed the document. Read the new copy
     against each rule that cites the id (`grep -rn <b> rules tests`). Only
     when every such rule still holds, or is changed to the new copy's
     numbers with their pages, write the new SHA256 and revision into the
     rules and the index, in 1 commit.
   - `refused <id>: <url> answered HTTP 403 ...`: the site refused the
     workcenter's name. Do not ask again under another name. Download the
     file by hand in a browser and go to step 4.
   - `gone <id>: ... HTTP 404`: the URL moved. Find the maker's new URL,
     change the entry's URL, and run step 3 again.
   - `not given <id>: <url> answered HTTP 429 ...` or `HTTP 500 ...`: the
     site answered, but with no copy and no verdict (too many requests, or
     its own error). Nothing is recorded; run step 3 again later.
   - `not reached <id>: ...`: no answer from the site (network). Nothing is
     recorded; run step 3 again later. Exit code 2 means only `not given`
     or `not reached`.
   - `references: <folder>/ledger.json ...: ...; mend it or delete it`: the
     ledger is not the shape `fetch` writes. Mend the key it names, or
     delete the ledger and fetch again.
   - A line that ends in `(ledger of <date>)` was answered by an earlier run
     and not asked again. `--again <id>` asks once more.

4. Check a file a person downloaded:

   ```sh
   python3 tools/workcenter references check ~/Downloads/tlv62569.pdf --id ti-slvsdg1 --keep
   ```

   - `same <file>: <id> ...`: it is the copy the index names. With `--keep`
     it is filed beside the fetched copies, and `fetch` asks no more for it.
   - `changed <file>: SHA256 ...`: another revision or another copy. Treat
     it as `changed` in step 3.
   - `unknown <file>: the index names no document with SHA256 ...`: without
     `--id` no entry has that copy.

## Done when

`references rules` exits 0, and each document a rule you work from cites
is `kept` in the folder of step 3.
