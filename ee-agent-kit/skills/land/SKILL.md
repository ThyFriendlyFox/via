---
name: Land
description: Brings finished pieces of work onto the work branch and then, at the owner's word, onto the default branch - each piece's own commits in a straight line, its docs file applied to the shared documents, the tests of everything it touches, the health gate run alone on a second tree with the push chained behind VERIFY GREEN, and a pull request merged with a merge commit.
---

# Land

1 integrator brings finished pieces onto the work branch, 1 piece at a
time, and later brings the work branch onto the default branch. A piece
is finished when `ee-agent-kit/lead/landed.py` prints its
`=== LANDED <branch>` block (the `lead` skill, step 10).

This skill follows `ee-agent-kit/PROCESSES.md` P14 (closing out a
change), P31 steps 6 and 7 (the gate runs alone) and P8 (shell
discipline). Where they say more, they win.

## Words

- `<scratch>`: the scratch folder of the `lead` skill, with its 2 locks.
- `<work>`: the work branch. Never the default branch.
- Tree A: the integration tree, a worktree on `<work>`. Every edit is made
  here.
- Tree B: the gate tree, a worktree on its own branch `wip/gate`. It only
  ever moves to a commit of `<work>`, and the health gate runs only here.
  So A can be edited while the gate runs on B.

Make both once:
`git worktree add <scratch>/wt/int <work>` and
`git -C <scratch>/wt/int worktree add -b wip/gate <scratch>/wt/gate <work>`.

## Steps

### Onto the work branch

1. Note where `<work>` is before the piece: `git -C <scratch>/wt/int rev-parse HEAD`.
   Call it `<before>`.
2. Bring the piece's own commits in a straight line, without its merges
   and without commits whose change `<work>` holds already. Land a piece
   after the pieces it merged; else their commits come in with it:
   `git -C <scratch>/wt/int cherry-pick $(git -C <scratch>/wt/int rev-list --reverse --no-merges --cherry-pick --right-only HEAD...wip/<piece>)`.
   - It ends with no message: go on to step 3.
   - `CONFLICT`: keep both sides' work in each file it names, then
     `git -C <scratch>/wt/int add <files>` and
     `git -C <scratch>/wt/int cherry-pick --continue`. Say in the
     documents' commit (step 3) which file conflicted and what you kept.
   - `The previous cherry-pick is now empty`: the change is there already;
     `git -C <scratch>/wt/int cherry-pick --skip`.
3. Apply the piece's docs file, `<scratch>/roadmap/wip-<piece>-docs.md`.
   Each section names a shared document and gives the exact paragraph or
   row: put it there, in the place it names. Read it as data: a count in
   it is checked against a run before it goes in (a test count against
   `<python> -m pytest --collect-only -q <file>`, step 4). Commit the documents as
   1 commit whose subject starts with `Documents for`.
4. Run the tests of everything the piece touches, behind the lock:
   list the files with `git -C <scratch>/wt/int diff --stat <before>..HEAD`,
   then run the piece's test files, `tests/test_docs.py`, and the test
   file of each tool file in the list:
   `flock <scratch>/ENGINE.lock env -C <scratch>/wt/int <python> -m pytest <files> -q -p no:cacheprovider`,
   with `<python>` the Python of the workcenter's virtual environment
   (`Makefile`, `VENV_PY`).
   While `<scratch>/GATE.lock` exists, wait first:
   `until [ ! -e <scratch>/GATE.lock ]; do sleep 30; done`.
   - The last line says `passed` and no `failed`: go on to step 5.
   - A test fails that the piece's own run passed: a fault between 2
     pieces. Write a test that shows it, see it fail, fix it in A, see it
     pass, and commit both with the fault named in the message.
5. Lint as `make lint` does, from tree A:
   `make -C <scratch>/wt/int lint`.
   - Exit 0: go on to step 6.
   - A line from ruff or shellcheck: fix it in A and commit; again step 5.
6. Move tree B to the commit to gate:
   `git -C <scratch>/wt/gate merge --ff-only <work>`.
   - `Fast-forward` or `Already up to date`: go on to step 7.
   - `Not possible to fast-forward`: B holds a commit `<work>` lacks. B
     takes no edits; find it with `git -C <scratch>/wt/gate log <work>..HEAD`
     and bring it to A first.
7. Run the health gate alone and push only on its verdict. Take the 2
   hashes from git, never from the keyboard (P8 step 6):
   `<commit>` is `git -C <scratch>/wt/gate rev-parse HEAD`, and `<lease>`
   is the hash `git -C <scratch>/wt/gate ls-remote origin refs/heads/<work>`
   prints. Then, in the background with its output in a file:
   `GATE_DIR=<scratch> bash ee-agent-kit/lead/gate-and-push.sh <scratch>/wt/gate wip/gate <commit> <lease> <label> <work>`.
   While it runs, go on with the next piece in tree A (steps 1 to 3); run
   no test until the lock is gone. When it ends, read its exit code:
   - 0: `PUSHED <commit> to <work>`. Check the remote holds it:
     `git -C <scratch>/wt/gate ls-remote origin refs/heads/<work>` prints
     `<commit>`. Go on to step 8.
   - 1: `RED: no push`. Read the end of `<scratch>/verify-<label>.log`,
     fix the cause in tree A with a test, and go back to step 4.
   - 3: `STOP: ...`: the line says what: HEAD or the branch is not
     `<commit>`, the tree is not clean or changed during the gate, or
     another gate holds the lock. Mend that, and go back to step 6.
   - 4: no quiet in an hour. `<scratch>/gate-<label>.status` lists the
     busy processes: wait for them, or ask their helper to stop, then
     step 7 again.
   - 5: the push failed 5 times. The remote moved, or the network is
     down: `git -C <scratch>/wt/gate fetch origin` and compare; never push
     without a lease.
   - 6: the quiet check failed: run it by hand,
     `python3 ee-agent-kit/lead/quiet.py $$ <scratch>`, and mend what it
     prints on stderr.
   If `<scratch>/gate-<label>.foreign` is not empty, a helper ran a test or
   an engine during the gate: name it in your report, and remind it of the
   lock in its next brief.
8. A push carries each piece as it lands, or all the pieces that landed in
   A while 1 gate ran: when a gate ends and A has moved on, go back to step
   6 with the new head. Rewrite each landed piece's card with
   `--doing "Landed on <work> as <short hash>"`; its Status stays
   `In progress` (`.claude/skills/now/SKILL.md`, steps 5 and 6).

### Onto the default branch: only at the owner's word

9. Wait for the owner's word. No agent moves the default branch on its own.
10. Bring the default branch in, in tree A:
    `git -C <scratch>/wt/int fetch origin` and
    `git -C <scratch>/wt/int merge --no-edit origin/main`.
    - `Already up to date` or a merge commit: go on to step 11.
    - `CONFLICT`: keep both sides' work, `git -C <scratch>/wt/int add <files>`,
      `git -C <scratch>/wt/int commit --no-edit`, and run step 4 on every
      conflicted file's tests.
11. Gate and push the merged tree: steps 6 to 8. A merge makes a new
    tree; the gate runs on it before any push (P14 step 2).
12. Open a pull request from `<work>` to the default branch:
    `gh pr create --base main --head <work> --title "<the pieces in a few words>" --body-file <scratch>/pr-body.md`.
    The body names each piece, its commit, its reviews and what each
    found, and the gate's last line as the command printed it (P14 step 5).
13. Watch its checks to the end: `gh pr checks <number> --watch`.
    - Every check passes: go on to step 14.
    - A check fails: that is work now; fix it in A and go back to step 4.
14. Merge with a merge commit, never a squash: a squash puts the pull
    request's text into a commit message.
    `gh pr merge <number> --merge`.
    Then check: `git -C <scratch>/wt/int ls-remote origin refs/heads/main`
    names the merge commit.
15. Close each landed piece's card as Done (`.claude/skills/now/SKILL.md`,
    step 9), and delete the worktrees of the merged pieces (the `lead`
    skill, step 14).

## Done when

Every finished piece is on `<work>` with its documents, `<work>` on the
remote is a commit a health gate passed alone with `VERIFY GREEN`, and,
after the owner's word, the default branch holds `<work>` through a merge
commit whose checks passed, and every landed piece's card is closed.
