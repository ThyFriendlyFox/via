# The loop that made NAME

NAME is improved in a loop: 1 prompt, run again and again, each pass
starting from what the last one left on disk and from the log below. Via's
`board-loop` skill says what a pass is. Say here which shape
this loop has, and delete the other 2:

- Passes inside 1 version: every pass changes VERSION, until its first
  push.
- A version a pass: each pass copies the latest version to the next
  number and answers its findings there (`PROCESSES.md` P22). The
  version's README holds what the pass found and changed.
- A list of features: each pass does the 1 thing that moves the board
  furthest, a failing gate first, then the next feature of a list that
  the prompt holds.

## The prompt

```text
NAME is WHAT THE BOARD IS, IN 1 SENTENCE. It must be WHAT THE OWNER ASKED
FOR, IN THEIR WORDS. Read LOOP.md, do 1 pass as the workcenter's skill
.claude/skills/board-loop/SKILL.md gives it, and append to the log. Stop
after 1 pass.
```

## The checklist

Done when every line holds. Each line is judged from a gate's line, a file
or a picture. Replace the lines in capitals; keep the rest.

Gates

- `workcenter gates VERSION --strict` prints GREEN, or each warning kept is
  named in the README with its reason.
- Every deck's bounds hold at every corner.
- `workcenter render VERSION --strict` names no part without a 3D body.

Function

- A LINE FOR EACH THING THE BOARD MUST DO THAT NO GATE READS.

Looks

- Parts sit in blocks, on a grid, with 1 orientation; no part looks dropped.
- No legend text touches a pad, a part or the edge.
- A LINE FOR WHAT THE OWNER ASKED THE BOARD TO LOOK LIKE.

Schematic

- Reads left to right in blocks; no text on a part or on other text.

README

- The status table, "What changed", the decisions and the open items say
  what the board is now.

## The log

| Pass | Version | Verdict, as printed | The reviewer's 3 problems | What changed | Next |
|---|---|---|---|---|---|
