---
name: Now
description: Keeps 1 card per piece of work in progress - what it is, its branch and last commit, its state, what is done now, the last health gate, what it waits for and what is left - in the body of 1 GitHub issue, or in a file on the status branch, so a maintainer can follow every agent at once.
---

# Now

Several agents work at once, each on its own branch of 1 repository. A
maintainer follows them by their cards: 1 card per piece of work, rewritten
in place, never appended to. `workcenter now` prints the card. A piece of
work is known by its branch. The card names no assistant, no model and no
session.

## The card

8 sections, in this order, and no others:

| Section | Holds | From |
|---|---|---|
| Work | `Roadmap item 7: <its title>`, or 1 line for work with no item | `--item`; the title from `ee-agent-kit/ROADMAP.md` |
| Branch | the branch, the last commit's short hash and subject | git |
| State | `working`, `blocked`, `landed` or `dropped` | `--state` |
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
   `now: <branch>`. The body is rewritten, never commented on: a comment
   notifies every watcher, an edit does not.
2. A host with no access to GitHub: `workcenter now --write <checkout>`
   writes the card to `now/<branch, / as ->.md` in a checkout of the branch
   `status`, which holds those files and nothing else. 1 file per branch,
   so 2 agents never edit 1 file.

## Labels

3 labels, made once by the owner:
`gh label create working`, `gh label create "blocked on owner"`,
`gh label create landed`.

- `working`: an open card. The issue template sets it.
- `blocked on owner`: the work waits for the owner's word.
- `landed`: the work is on `main`; the issue is closed.

The weekly stale run (`.github/workflows/stale.yml`) spares `working` and
`blocked on owner`.

## Steps

Run each from the root of your work tree. Below, `N` is the card's issue
number and `<branch>` your branch.

### When a card is opened: before the first edit of the work

1. `workcenter now . --item <number or 1 line> --state working --doing "<what you start with>" --left "<step>" --left "<step>"`
   - It prints the card: go on to step 2.
   - `now: refused: <reason>`: fix what the line names and run it again.
     `--item is missing`, a state that is not 1 of the 4, more than 3
     `--doing`, a value with a line break, `--item` or `--blocked` that
     starts with `#`, a value, branch or commit subject that names an
     assistant, a model or a session, or a detached HEAD (make a branch
     first) are the usual ones.
2. Find a card this branch has already:
   `gh issue list --state open --search "in:title now: <branch>"`.
   - A row: that is `N`. Go to "When it is rewritten".
   - No row: go on to step 3.
3. Open the issue with the card as its body:
   `mkdir -p build && workcenter now . <the same options> > build/now.md && gh issue create --title "now: <branch>" --label working --body-file build/now.md`.
   The card goes to a file first, and `gh` runs only when the command
   printed one: never pipe `workcenter now` into `gh`, as a refusal then
   gives the issue an empty body. It prints the issue's URL; its last
   number is `N`. A host with its own
   GitHub tool creates the issue with that title, the label `working` and
   the card's text as its body instead.
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
   `workcenter now . --item <same> --state working --doing "<now>" --left "<what is left>"`.
   For a block: `--state blocked --blocked "<who or what>"`; without
   `--blocked` the command refuses.
6. Rewrite the body, never comment:
   `mkdir -p build && workcenter now . <options> > build/now.md && gh issue edit N --body-file build/now.md`.
   On `now: refused:` gh does not run and the issue keeps its last card:
   fix what the line names and run it again. Or the host's own GitHub tool that updates an issue's body (for
   example the GitHub MCP server's `issue_write` with method `update`),
   with the card's text as the body. On the status branch: `--write
   ../status` and the 4 commands it prints.
7. Labels follow the state:
   - blocked on the owner: `gh issue edit N --add-label "blocked on owner"`;
   - unblocked: `gh issue edit N --remove-label "blocked on owner"`.

### When it is closed: landed, or dropped

8. Landed: when the work's commit is on `main`, rewrite the card with
   `--state landed --doing "Landed on main as <short hash>"`, then
   `gh issue edit N --add-label landed --remove-label working` and
   `gh issue close N --reason completed`.
9. Dropped: rewrite the card with `--state dropped --doing "Dropped: <the reason>"`,
   then `gh issue close N --reason "not planned"`.
10. On the status branch, steps 8 and 9 rewrite the file with `--write` and
    leave it there: the maintainer reads the last state of every branch.

## For the maintainer

- Open cards: `gh issue list --label working`, or the issues page filtered
  by `label:working`. Blocked on you: `gh issue list --label "blocked on owner"`.
- Without GitHub's issues: `git fetch origin status` and read `now/` on
  that branch.

## Done when

Every branch with work in progress has 1 card, the card's Updated line is
no older than its branch's last commit, and every landed or dropped card's
issue is closed.
