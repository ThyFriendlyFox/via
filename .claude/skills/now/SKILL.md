---
name: Now
description: Keeps 1 work card per piece of work in progress - its Status for the project board, its branch and last commit, what is done now, the last health gate, what it waits for and what is left - in the body of 1 GitHub issue, or in a file on the status branch, so a maintainer can follow every agent at once.
---

# Now

Several agents work at once, each on its own branch of 1 repository. A
maintainer follows them on the project board and on their cards: 1 card
per piece of work, rewritten in place, never appended to. `workcenter now`
prints the card. A piece of work is known by its branch. The card names
no assistant, no model and no session.

## The card

The issue's title is `Work card: <the work>`: a roadmap item's number and
title, or 1 line for work with none. `workcenter now ... --title` prints
it. The Board workflow takes an issue whose title starts `Work card:`.

The body's first line is `**Status:**` and 1 of the board's own 3 words:
`Todo`, `In progress` or `Done`. The Board workflow reads that line and
puts the card in that column; a closed issue is Done. There is no other
state word. Work that waits on someone stays `In progress` and says so in
its Blocked on line.

Then 6 sections, in this order, and no others. The card repeats nothing
else the board shows.

| Section | Holds | From |
|---|---|---|
| Branch | the branch, the last commit's short hash and subject | git |
| Doing now | at most 3 lines, or `nothing` | `--doing`, repeatable |
| Health gate | the last `make verify` on this branch: verdict, commit, time; or `none yet` | `build/verify.json`, which `verify/verify.sh` writes on exit |
| Blocked on | who or what, or `nothing` | `--blocked` |
| Left | a short list, or `nothing` | `--left`, repeatable |
| Updated | the UTC date and time the card was printed | the clock |

The health gate line reads like this, with the hash and the time of the
run:

```
GREEN on `abc1234` at 2026-11-17 09:41 UTC
RED at 3/4 tests on `abc1234` at 2026-11-17 09:41 UTC
```

The commit is the one the gate started on. The line adds `with uncommitted
changes` when the tree differed from that commit at the start or at the
end, untracked files included; `, the branch moved to <hash> during the
run` when a commit landed while the gate ran; and `, 2 commits before the
last` when the branch moved on after the gate's commit. A record of
another branch is `none yet`. A record `verify.sh` would not write is
refused in 1 line.

## Where the card goes

1. First choice: the body of 1 GitHub issue per piece of work, titled
   `Work card: <the work>`. The body is rewritten, never commented on: a
   comment notifies every watcher, an edit does not.
2. A host with no access to GitHub: `workcenter now --write <checkout>`
   writes the card under its title to `now/<branch, / as ->.md` in a
   checkout of the branch `status`, which holds those files and nothing
   else. 1 file per branch, so 2 agents never edit 1 file.

## Labels

No new labels: the repository's own 4.

- `enhancement`: every work card. The issue template sets it.
- `help wanted`: the work needs something from outside: a key, an
  account, a document no session may fetch.
- `question`: the work waits for the owner's decision.
- `documentation`: a follow-up that changes documents only.

## Steps

Run each from the root of your work tree. Below, `N` is the card's issue
number and `<branch>` your branch.

### When a card is opened: before the first edit of the work

1. `workcenter now . --item <number or 1 line> --status Todo --left "<step>" --left "<step>"`,
   or `--status "In progress" --doing "<what you start with>"` when you
   start at once.
   - It prints the card: go on to step 2.
   - `now: refused: <reason>`: fix what the line names and run it again.
     `--item is missing`, a status that is not Todo, In progress or Done,
     more than 3 `--doing`, a value with a line break or a `**Status:**`
     line of its own, `--item` or `--blocked` that starts with `#`, a
     value, branch or commit subject that names an assistant, a model or a
     session, or a detached HEAD (make a branch first) are the usual ones.
2. Find a card this branch has already:
   `gh issue list --state open --search "in:body <branch>"`.
   - A row whose title starts `Work card:`: that is `N`. Go to "When it
     is rewritten".
   - No row: go on to step 3.
3. Open the issue with the card as its body:
   `mkdir -p build && workcenter now . <the same options> > build/now.md && gh issue create -t "$(workcenter now . <the same options> --title)" -l enhancement -F build/now.md`.
   The card goes to a file first, and `gh` runs only when the command
   printed one: never pipe `workcenter now` into `gh`, as a refusal then
   gives the issue an empty body. The line gives `gh` its short flags
   (`-t` the title, `-l` the label, `-F` the body's file), so no flag of
   `gh` stands after `workcenter now` as if it were that command's. It prints the issue's URL; its last
   number is `N`. A host with its own GitHub tool creates the issue with
   the title `--title` prints, the label `enhancement` and the card's
   text as its body instead.
   - `gh` is not there, or answers that it is not logged in, and the host
     has no GitHub tool: use the status branch, step 4.
4. The status branch, once per machine. If the remote has it:
   `git fetch origin status` then
   `git worktree add ../status status`. If it does not:
   `git worktree add --orphan -b status ../status`.
   Then `workcenter now . <the same options> --write ../status`.
   - It prints `wrote <path>` and 4 git commands. Run them in order. It
     runs none of them itself.
   - `now: refused: ... is on branch X, not status`: the folder is not a
     checkout of `status`.
   - `now: refused: ... holds <file> outside now/`: the folder is another
     branch's checkout. Take a new one.
   - `now: refused: now/<file>.md is the card of <other branch>`: 2
     branch names give 1 file name. Rename your branch.

### When it is rewritten: at each landing, at each block, when the health gate ends

5. After each commit that lands a step, at each block, and after each
   `make verify`, print the card with what is true now:
   `workcenter now . --item <same> --status "In progress" --doing "<now>" --left "<what is left>"`.
   When the work waits on someone, it stays In progress: add
   `--blocked "<who or what>"`.
6. Rewrite the body, never comment:
   `mkdir -p build && workcenter now . <options> > build/now.md && gh issue edit N -F build/now.md`.
   On `now: refused:` gh does not run and the issue keeps its last card:
   fix what the line names and run it again. Or the host's own GitHub
   tool that updates an issue's body (for example the GitHub MCP server's
   `issue_write` with method `update`), with the card's text as the body.
   On the status branch: `--write ../status` and the 4 commands it prints.
7. Labels follow what the work waits for:
   - it needs something from outside: `gh issue edit N --add-label "help wanted"`;
   - it waits for the owner's decision: `gh issue edit N --add-label question`;
   - it waits no more: remove that label with `--remove-label`.

### When it is closed: landed, or dropped

8. Landed: when the work's commit is on `main`, rewrite the card with
   `--status Done --doing "Landed on main as <short hash>"`, then
   `gh issue close N --reason completed`.
9. Dropped: rewrite the card with `--status Done --doing "Dropped: <the reason>"`,
   then `gh issue close N --reason "not planned"`.
10. On the status branch, steps 8 and 9 rewrite the file with `--write` and
    leave it there: the maintainer reads the last state of every branch.

## For the maintainer

- The project board shows each card in its column. Open cards:
  `gh issue list --search "in:title Work card:"`. Waiting for you:
  `gh issue list --label question`.
- Without GitHub's issues: `git fetch origin status` and read `now/` on
  that branch.

## Done when

Every branch with work in progress has 1 card, the card's Updated line is
no older than its branch's last commit, and every landed or dropped card's
issue is closed.
