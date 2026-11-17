---
name: Standards
description: Lists each requirement of a product's kind, from free documents (eCFR parts, makers' notes), as held by a gate, held by a named test of the verification package, or not held - with the document and clause of each, the paid standards a test laboratory uses, and the documents that could not be had. A list from free documents is not a certificate.
---

# Standards

A product is sold under rules that name its kind: a vaping device with a
lithium cell answers to the FCC's rules for a digital device and to the
transport rules for lithium cells. `workcenter standards` reads the kind's
requirements from `rules/products/<kind>.json` and says, for each, what
holds it on this project.

The list is not a certificate. It holds free documents only. A test
laboratory judges the product to paid standards; the list names them and
holds none of their numbers.

## When

- A board is near release and someone asks what it must meet.
- A verification package (`verification/`, PROCESSES.md P28) is being
  written: the list names requirements it should hold.

## Inputs

| File | Holds | Who writes it |
|---|---|---|
| `product.json`, beside the board | `kind`, and `tests`: for a requirement, the IDs of the verification package that hold it | You |
| `verification/traceability.md` | each ID's verdict: PASS, FAIL or OPEN | You, by the verification skill |
| `board-rules.json`, beside the board | the layout packs (`layout`) that hold a requirement by the DRC gate | You, by the board-rules skill |
| `rules/products/<kind>.json`, in the workcenter | the requirements, each with its document and clause | The workcenter |

The worked example is `tests/products/last-hit`: Last Hit v0.16, a
vaping device with a lithium cell.

## Steps

1. Write `product.json` beside the board with the Write tool:
   `{"kind": "vaping-device-lithium-cell"}`. `ls rules/products/` in the
   workcenter names the kinds.
2. Run `workcenter standards <project>`. The first line counts:
   `STANDARDS <kind>: N held by a gate, M held by a test, K not held`.
3. For each line `- held by a gate: <id> [...] -- drc, pack <pack>: 0 fail, 0 not judged (board-rules.json, <board>.kicad_pcb)`:
   the command ran the layout pack on the board as it stands, and every
   rule of it held. Run it again after each change to the board.
4. For each line `- held by a test: <id> [...] -- <ID> PASS, ...`: the named
   requirements of the verification package hold it. Nothing to do.
5. For each line `- not held: <id> [...] -- <reason>`, act on the reason:
   - `board-rules.json names no <pack>`: add the pack to `layout` in
     `board-rules.json` and follow the board-rules skill until DRC passes.
   - `drc, pack <pack>: 3 fail, 0 not judged`, or any count that is not
     0 and 0: run `workcenter drc <project> --strict`, which prints each
     line, and act on it by the board-rules skill.
   - `drc, pack <pack>: ...; <pack> <rule>: the rule is for a board of 2 copper layers, and this one has 4`:
     the rule is not for this board, so nothing holds the requirement.
     Hold it by a test instead.
   - `drc, pack <pack>: no .kicad_pcb in the project to judge`: run the
     command on the folder that holds the board.
   - `product.json names no test for it`: write a requirement for it in
     the verification package, with this line's document and clause as
     its source, then add its ID under `tests` in `product.json`:
     `"tests": {"<id>": ["REQ-XXX-01"]}`.
   - `<ID> is OPEN` or `<ID> is FAIL`: the requirement exists and its
     evidence does not hold yet. Finish its evidence (a deck, a
     calculation, a bench test, a laboratory's report) and set its
     verdict in `traceability.md`.
   - `<ID> is not in verification/traceability.md`: correct the ID in
     `product.json`, or add the row.
6. Read the lines under `Paid standards a test laboratory uses`. Write in
   the version's README which laboratory test each `not held` line waits
   for.
7. Read the lines `left out: <document> <clause>: <reason>`. Each is a
   clause of a document the kind read and does not list, with the reason.
   If the reason is not true of your product, add the clause to the
   kind's `requirements`.
8. Read the lines `not had: ...`. Those documents could not be fetched;
   the list says nothing about them. Name them in the README as open.
9. Run step 2 again. `workcenter standards <project> --strict` exits 0
   only when no line is `not held`.

## Done when

Every line is held, or the version's README names, for each line that is
not held, the test or laboratory report that will hold it.
