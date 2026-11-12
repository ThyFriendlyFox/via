# Style

<!-- The writing rules for every user-facing text: docs, UI copy, error
     messages, release notes. Based on Simplified Technical English.
     AGENTS.md house style governs code; this file governs words. -->

EE Workcenter uses one voice for every text.
The rules keep the text short, clear and easy to translate.

## Rules

1. Write one instruction in one sentence.
2. Keep an instruction under 20 words.
3. Keep a descriptive sentence under 25 words.
4. Use the active voice.
5. Use the simple present tense.
6. Use one word for one idea. Do not use synonyms.
7. Do not use contractions.
8. Do not use marketing words.
9. Start an instruction with the verb.
10. Use a list for a sequence of steps.
11. Use a table for a set of values.
12. Write numbers as digits.

## Command-line output

The CLI prints the thing; it does not explain it. 1 line per gate:
status, name, summary, seconds. `--json` prints the same records as
JSON and nothing else. Error text names the engine, the exit code, and
the report path.

## Terms

| Use | Do not use |
|---|---|
| workcenter | toolbox, kit (the kit is `ee-agent-kit/`), environment (the cloud VM) |
| project | board repo, target, design folder |
| gate | check (that is `doctor`), test (those are in `tests/`), validation |
| engine | tool, backend, adapter, provider |
| fixture board | throwaway board, sample, demo, example |
| GREEN | passing, clean, all good |
| red | failing, broken, blocked |
| doctor | health check, status, preflight |
| session file | SES, routing result |
| report | log (a log is `build/sim/*.log`), output |

## The website

The website (`site/`) speaks to a person deciding whether to use Via. The
owner asked on 2026-11-12 for professional copy that says what Via does
for the reader. These rules win over the ones above on the site, and only
there.

1. Lead with what the reader gets, then how Via does it.
2. Write a headline as 1 plain sentence in sentence case, with no closing
   period: "Four checks before any board is released".
3. Do not write slogans: no run of fragments ("Design. Gate. Fix.
   Done."), no "X, not Y" ("Boards, not demos."), no maxim ("A bound holds
   at every corner, or it does not hold.").
4. In running text, write the numbers one to nine as words. Keep digits
   for measurements, for counts over nine, and on a specification line
   ("84.4 × 64 mm · 4 layers · 127 parts").
5. Name a check by what it does for the reader ("electrical rules",
   "simulation") before its short name (ERC, SIM).
6. Show the reader's kind of board: an example project. A fixture board is
   a test of this repository; it appears only to show a check catching a
   fault, and its caption calls it a test circuit.
7. A claim still needs its evidence (`PROCESSES.md` P5). Marketing copy
   claims nothing a run, a file or a test does not show.
