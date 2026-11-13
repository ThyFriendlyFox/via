---
name: Board Loop
description: Improves a board that already passes its gates by running 1 prompt again and again - gates, pictures, a reviewer who has not seen the earlier rounds, the 3 worst problems answered, a log - until every line of the project's checklist holds.
---

# Board Loop

A board that passes its gates works on paper. It is not yet a board someone
wants to hold: a part that looks dropped, a legend that touches a pad, a
schematic nobody can follow, a connector no hand can reach. No gate reads
those. The loop finds them. 1 prompt runs again and again; each pass starts
from what the last one left on disk and from a log; a pass ends when its
findings are answered and written down.

3 example projects were made this way, each with a prompt and a checklist
it wrote for itself: `examples/anc-speaker/LOOP.md`,
`examples/ring-mouse/LOOP.md`, `examples/threadripper-matx/LOOP.md`. Read 1
of them before the first pass.

Use it when the board is GREEN (the `board-gates` skill comes first) and
the owner asks for a board that is compact, correct and good to look at,
or for a version to be improved with no new feature named.

## The file

The project keeps `LOOP.md` beside its version folders. Copy
`templates/project/LOOP.md` once. It holds 3 things:

- **The prompt**, as it is run. Its first sentences say what the board is
  and what it must be, in the owner's words.
- **The checklist**. The loop is done when every line holds.
- **The log**, 1 entry a pass.

## The checklist

Write it before the first pass, 3 to 6 lines under each head. A line is
something a reader can judge from a gate's line, a file or a picture: it
holds or it does not. "Looks professional" is no line. "No legend text
touches a pad, a part or the edge" is.

| Head | What its lines hold | Lines like the 3 projects' own |
|---|---|---|
| Gates | what the commands print | `workcenter gates <version> --strict` prints GREEN, or each warning kept is named in the README with its reason. Every deck's bounds hold at every corner. `workcenter render <version> --strict` names no part without a 3D body. |
| Function | what the board must do that no gate reads | Every connector and control is reachable at the edge. The speaker's polarity is marked. The antenna points away from the finger and has no copper over it. |
| Looks | what a picture shows | Parts sit in blocks, on a grid, with 1 orientation; no part looks dropped. The finish in the renders is the stackup's. No picture shows an empty quarter of the board. |
| Schematic | what the sheet shows (`PROCESSES.md` P24) | Reads left to right in blocks; no wire wanders round the sheet; no text on a part or on other text. |
| README | what the words say | The status table, "What changed", the decisions and the open items say what the board is now. |

A stand-in for something not known (a pin map under NDA, a part not yet
chosen) gets a line that names it as a stand-in.

## One pass

1. Read `LOOP.md`: the prompt and the checklist. Do not read the log's
   last entry yet: step 4 needs eyes that have not seen it.
2. `workcenter next <version>`. What it names comes first. A board that is
   not GREEN is not looked at.
3. Draw the pictures and open every one: `workcenter pictures <version>`,
   or for a project with no `pictures.json`
   `workcenter render <version> --strict --views schematic,2d,3d,layers`.
4. Fresh eyes. A reviewer who has not seen the earlier rounds reads the
   pictures against the checklist and returns the 3 worst problems, each
   with where it is (the picture, the part's reference, the place) and why
   it matters. In a host that can start a helper, the reviewer is a helper
   whose brief holds the checklist and the pictures' paths and nothing of
   the log (`PROCESSES.md` P31). In a host that cannot, write your own 3
   now, before step 5.
5. Now read the log's last entry. A problem the last pass answered and
   that is back says the answer did not hold: it goes first.
6. Check each problem in the files before acting on it: a gate's line, a
   place from `workcenter inspect`, a number from a datasheet. A problem
   seen in a picture alone is looked at once more, larger. A problem that
   is not real is logged as not real, with what showed it.
7. Answer the problems that are real, in `design.py`, never in a
   `.kicad_*` file. Rule and gate failures first. A finding that needs a
   new feature, or changes what the version was made for, is the next
   version: `workcenter version new <project> <vNEXT>`, and every edit in
   the copy (`PROCESSES.md` P22).
8. Route, gate and draw again: `PROCESSES.md` P4 before the route, then
   `workcenter design <version>/design.py --route`,
   `workcenter gates <version> --strict`, and the pictures of step 3. A
   pass ends GREEN, with its pictures drawn after the last change to the
   board (`PROCESSES.md` P23).
9. Append to the log: the pass's number, the gates' verdict line as
   printed, the reviewer's 3 problems, what changed, what is next. A
   problem left open says why.
10. Stop. Do not start the next pass in this one: its reviewer must not
    have seen this pass.

## When the loop ends

Every line of the checklist holds, or a pass's reviewer finds nothing worth
a change. The log's last entry says which, and the version's README
carries what the reviews found and what changed.

## Rules

- Every number in the log or the README comes from a run of this pass.
- The reviewer judges and changes nothing. Whoever answers a problem
  checks it first (step 6): a reviewer reads pictures, and a picture can
  mislead.
- At most 3 problems a pass. A fourth waits for the next reviewer, who
  will find it again if it matters.
- A line of the checklist changes only with a line in the log that says
  why.
