# Style

<!-- The writing rules for every user-facing text: docs, UI copy, error
     messages, release notes. Based on Simplified Technical English.
     AGENTS.md house style governs code; this file governs words. -->

Via uses one voice for every text.
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
| Via (the product: capital V, no article); `workcenter` is its command, in a code span | `EE Workcenter`, `the workcenter` (the owner's words of 2026-11-19; `tests/test_product_name.py`) |
| workcenter (the kind of thing Via is) | toolbox, kit (the kit is `ee-agent-kit/`), environment (the cloud VM) |
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

Every word on the website, its blog included, follows
[`WEBSITE-WRITING.md`](WEBSITE-WRITING.md), the owner's rules of
2026-11-18: contractions, 1 idea in a sentence, plain sentences with a
number in them, and none of its ban list. Where a rule below and that file
disagree, the file wins.

1. Lead with what the reader gets, then how Via does it.
2. Write a headline as 1 plain sentence in sentence case, with no closing
   period: "How we check a board".
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
8. Justify a paragraph to its column, with hyphenation on. On a phone
   (640 px wide or less) its lines start at the left: a justified line
   there had too few words, and its gaps grew wide (the owner's
   screenshot, 2026-11-19). A part's label
   on the example's board is too narrow for it, and stays ragged.
9. Write a blog post, and the blog's own words, by `WEBSITE-WRITING.md`.
   It replaced `TONE.md`'s Simplified Technical English on the blog on
   2026-11-18.
10. A post about an example board speaks as the engineers who made it,
    "we": how we came to make it, the science and the papers behind the
    device, and how the design went. It explains each idea in plain words
    a slightly technical reader follows, with its number, and with no
    staged scene or made-up comparison (the owner's asks of 2026-11-18). It cites a paper only when the paper says
    what the post says, and states no fact about the board that its files
    do not.

The owner's own wording stands as the owner wrote it, and is the only
exception to these rules:

- The hero's headline, of 2026-11-12, in title case on 2 lines since
  2026-11-19 (it was 3, "Circuit Boards / From / AI"): "Circuit Boards /
  From AI".
- The hero's paragraph, of 2026-11-14: "Via is our dream for lowering the
  difficulty to getting into electronics design. It's a package of tools,
  skills and gates an agent needs to make production-ready PCBs. Designed
  by EE's in Florida."
- The design-as-code section's headline, of 2026-11-14, in title case:
  "How a Python File Becomes a Board".
- The blog's message to its reader, of 2026-11-17, at the head of the
  blog and after each post: "We're making Via better every day!", then
  "Subscribe here to keep up to date with our progress. Give us
  suggestions here!" The first "here" is the subscribe form under the
  message, which takes the reader's email. The second is the feedback
  page, `/feedback`. The blog does not explain what a blog is.
- The heading of the home page's example, of 2026-11-18, with its
  exclamation mark: "Here's a board made with Via!"
- The heading over Herald's run of the checks on the home page, of
  2026-11-19: "What Via looks like in the CLI".
- The heading of the home page's checks, of 2026-11-19: "How we check a
  board". The section after it keeps "Free and open source under the MIT
  license".
- The line at the bottom of every page, of 2026-11-18, in title case:
  "Made by Team Reagent for Builders", a link to `reagent-systems.com`.
  The menu's and the footer's "Community" is the team's Discord server,
  `discord.reagent-systems.com`.
- The lines on the news bar, of 2026-11-18, each after a post, with no
  quote marks:
  "Only Cool Kids Allowed!", "Building Tomorrow Today!", "We have a
  dog", "Check out our community!" (a link to the Discord server) and
  "Free inference found here!". They live in `QUIPS` in `site/blog.py`.
- The button on the hero's guide card, of 2026-11-19, with its exclamation
  mark: "Ask us for help!", a link to the Discord server. The card's
  other button leads to the guide, `/guide`.
