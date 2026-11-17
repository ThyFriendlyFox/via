---
name: Now
description: Keeps 1 work card per piece of work - a GitHub issue titled `Work card: ...` whose body `workcenter now` rewrites, with a `**Status:**` line in the project board's own 3 words (Todo, In progress, Done) - so the board shows where every piece stands by itself and a maintainer can follow every agent at once.
---

# Now: work cards and the project board

Several agents work at once, each on its own branch of 1 repository. A
maintainer follows them on the project board. Each piece of work has 1
work card: 1 GitHub issue, titled `Work card: <the work in a few words>`.
Its body is rewritten in place, never commented on: a comment notifies
every watcher, an edit does not. `workcenter now` prints the body. The
card names no assistant, no model and no session.

Nobody moves a card on the board by hand. The workflow
`.github/workflows/board.yml` runs `tools/board.py` each time a card is
opened, edited, closed or reopened, and puts the card in the column its
`**Status:**` line names.

## The card

The body has these sections, in this order:

| Section | Holds | From |
|---|---|---|
| Work | `Roadmap item 7: <its title>`, or 1 line for work with no item | `--item`; the title from `ee-agent-kit/ROADMAP.md` |
| Branch | the branch, the last commit's short hash and subject | git |
| Status | 1 line: `**Status:** Todo`, `**Status:** In progress` or `**Status:** Done` | `--state` |
| Doing now | at most 3 lines, or `nothing` | `--doing`, repeatable |
| Health gate | the last `make verify` on this branch: verdict, commit, time; or `none yet` | `build/verify.json`, which `verify/verify.sh` writes on exit |
| Blocked on | who or what, or `nothing` | `--blocked` |
| Left | a short list, or `nothing` | `--left`, repeatable |
| Updated | the UTC date and time the card was printed | the clock |

The Status line holds the board's own 3 words and no other state word.
A block is said in `Blocked on` and by a label, not by the Status line.
A closed card stands in Done, whatever its body says. The rules the board
holds the line to (1 line, not in a code block, not in a comment) are in
`tests/board/README.md`, "The card's line".

The health gate line reads like this, with the hash and the time of the
run:

```
GREEN on `abc1234` at 2026-11-17 09:41 UTC
RED at 3/4 tests on `abc1234` at 2026-11-17 09:41 UTC
```

It adds `with uncommitted changes`, `, the branch moved to <hash> during
the run`, or `, 2 commits before the last` when those hold. A record of
another branch is `none yet`.

## Labels

The card uses 4 labels the repository has, and makes no new one:

- `enhancement`: every card, from when it is opened.
- `documentation`: in place of `enhancement`, for a card whose work is a
  document only, such as a follow-up to a document.
- `help wanted`: the work needs something from outside: a document that
  cannot be had, an install, a key, an account.
- `question`: the work waits for the owner's decision.

## The board, set up once by the owner

An agent cannot do these; it names them to the owner in 1 line each when
a run says one is missing.

1. A personal access token (classic) with the `project` and `repo` scopes,
   saved as the repository secret `BOARD_TOKEN`: `gh secret set BOARD_TOKEN`.
   GitHub's own token cannot edit a user's project.
2. Only for a board other than the default one: the repository variable
   `BOARD_URL`, `gh variable set BOARD_URL --body https://github.com/users/<login>/projects/<n>`.
3. The project's single-select field `Status` holds the options Todo,
   In progress and Done.
4. The workflow is on the default branch. GitHub runs a workflow for an
   issue event from the default branch's copy of the file only: on a work
   branch, `board.yml` does nothing, and no run is no error.

## Steps

Run each from the root of your work tree. Below, `N` is the card's issue
number and `<branch>` your branch.

### When a card is opened: when the work is decided, or before its first edit

1. Print the card. Work you begin now is `In progress`:
   `workcenter now . --item <number or 1 line> --state "In progress" --doing "<what you start with>" --left "<step>" --left "<step>"`.
   Work that is decided but not begun is `Todo`:
   `workcenter now . --item <number or 1 line> --state Todo --left "<step>"`.
   - It prints the card: go on to step 2.
   - `now: refused: <reason>`: fix what the line names and run it again.
     `--item is missing`, a state that is not 1 of the 3 words, more than 3
     `--doing`, a value with a line break, `--item` or `--blocked` that
     starts with `#`, a value, branch or commit subject that names an
     assistant, a model or a session, or a detached HEAD (make a branch
     first) are the usual ones.
2. Find a card this branch has already:
   `gh issue list --state open --search "in:title Work card in:body <branch>"`.
   - A row whose title starts with `Work card:`: that is `N`. Go to step 5.
   - No such row: go on to step 3.
3. Open the issue with the card as its body:
   `mkdir -p build && workcenter now . <the same options> > build/now.md && gh issue create --title "Work card: <the work in a few words>" --label enhancement --body-file build/now.md`.
   The card goes to a file first, and `gh` runs only when the command
   printed one: never pipe `workcenter now` into `gh`, as a refusal then
   gives the issue an empty body. It prints the issue's URL; its last
   number is `N`. A host with its own GitHub tool creates the issue with
   that title, the label and the card's text as its body instead. For a
   document-only card, `--label documentation`.
   - `gh` is not there, or answers that it is not logged in, and the host
     has no GitHub tool: use the status branch, step 4. The board does not
     see that branch; say so in your report.
4. The status branch, once per machine. If the remote has it:
   `git fetch origin status` then `git worktree add ../status status`.
   If it does not: `git worktree add --orphan -b status ../status`.
   Then `workcenter now . <the same options> --write ../status`.
   - It prints `wrote <path>` and 4 git commands. Run them in order. It
     runs none of them itself.
   - `now: refused: ... is on branch X, not status`: the folder is not a
     checkout of `status`.
   - `now: refused: ... holds <file> outside now/`: the folder is another
     branch's checkout. Take a new one.
   - `now: refused: now/<file>.md is the card of <other branch>`: 2
     branch names give 1 file name. Rename your branch.

### When it is rewritten: at each landing, at each block, at each end of a health gate

5. After each commit that lands a step, at each block and when it ends,
   and after each `make verify`, print the card with what is true now:
   `workcenter now . --item <same> --state "In progress" --doing "<now>" --left "<what is left>"`.
   For a block, add `--blocked "<who or what>"`; the Status line stays
   `In progress`.
6. Rewrite the body, never comment:
   `mkdir -p build && workcenter now . <options> > build/now.md && gh issue edit N --body-file build/now.md`.
   On `now: refused:` gh does not run and the issue keeps its last card:
   fix what the line names and run it again. Or the host's own GitHub
   tool that updates an issue's body, with the card's text as the body.
   On the status branch: `--write ../status` and the 4 commands it prints.
7. Labels follow the block:
   - it needs something from outside: `gh issue edit N --add-label "help wanted"`;
   - it waits for the owner's decision: `gh issue edit N --add-label "question"`;
   - the block ends: `gh issue edit N --remove-label "help wanted"` or
     `--remove-label "question"`.
8. Check the board once after the first rewrite of a card (steps 12 to 14).

### When it is closed: done, or dropped

9. Done: when the work's commit is on the default branch, rewrite the card
   with `--state Done --doing "Landed on main as <short hash>"`, then
   `gh issue close N --reason completed`.
10. Dropped: rewrite the card with `--state Done --doing "Dropped: <the reason>"`,
    then `gh issue close N --reason "not planned"`. The board shows it in
    Done, as every closed card; the Doing now line says why.
11. On the status branch, steps 9 and 10 rewrite the file with `--write`
    and leave it there: the maintainer reads the last state of every branch.

### Reading a run of the board

12. List the last runs: `gh run list --workflow board.yml --limit 5`.
    - No run at all: the workflow is not on the default branch yet (setup
      step 4). Nothing to do; say so in your report.
    - A run: take its id, go on to step 13.
13. Read its line: `gh run view <run id> --log`, and find the line that
    starts with `board:`. Each line and what to do is in
    `tests/board/README.md`, "Reading a run". The usual ones:
    - `board: card #N stands in <column> on <url>`: done.
    - `board: card #N is on <url> and left where it stands: ...`: the
      body's Status line is missing, doubled, in a code block, or another
      word. Print the card again (step 5) and rewrite it (step 6).
    - `board: no secret BOARD_TOKEN is set`: setup step 1 is not done.
      Tell the owner in 1 line.
    - `board: FAIL: ... has no Status option "<word>"`: setup step 3. Tell
      the owner in 1 line.
14. A permission error: `board: FAIL: gh api graphql (...) exited N: ...`.
    GitHub refused the call; the rest of the line is GitHub's answer. The
    causes are a token without the `project` scope, a token that expired,
    or no project at `BOARD_URL`. An agent cannot mend a token. Tell the
    owner in 1 line, with the run's link: "make a classic token with the
    `project` and `repo` scopes and save it with `gh secret set
    BOARD_TOKEN`", or "set `BOARD_URL` to the board's URL". Do not run the
    workflow again until the owner says it is done; then
    `gh run rerun <run id>`, once, and read it as in step 13.

## For the maintainer

- The board shows every card in its column. Open cards from the shell:
  `gh issue list --search "in:title Work card" --state open`. Waiting on
  you: `gh issue list --label question`.
- Without GitHub's issues: `git fetch origin status` and read `now/` on
  that branch.

## Done when

Every branch with work in progress has 1 card, the card's Updated line is
no older than its branch's last commit, every card stands on the board in
the column its Status line names, and every finished or dropped card's
issue is closed.
