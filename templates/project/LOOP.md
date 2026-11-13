# The loop that made NAME

NAME is improved in a loop: 1 prompt, run again and again, each pass
starting from what the last one left on disk and from the log below. The
workcenter's `board-loop` skill says what a pass is. Say here whether a
pass stays inside 1 version or makes the next one (`PROCESSES.md` P22).

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
