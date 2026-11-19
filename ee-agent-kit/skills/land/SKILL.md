---
name: Land
description: Brings finished pieces of work onto the work branch and then, at the owner's word, onto the default branch - each piece's own commits in a straight line, its docs file applied to the shared documents, the tests of everything it touches, a push on the fast checks, the health gate run by CI on the exact pushed commit, and a pull request merged with a merge commit only when its `verdict` is green on its head.
---

# Land

1 integrator brings finished pieces onto the work branch, 1 piece at a
time, and later brings the work branch onto the default branch. A piece
is finished when `ee-agent-kit/lead/landed.py` prints its
`=== LANDED <branch>` block (the `lead` skill, step 10).

This skill follows `ee-agent-kit/PROCESSES.md` P14 (closing out a
change) and P8 (shell discipline). Where they say more, they win.

The health gate (`make verify`) runs on GitHub, in CI's `full` job. A
push to the work branch needs the fast checks only (`make check`). The
default branch takes no commit whose `verdict` check is not green on that
exact commit (`ee-agent-kit/CI.md`, "Where the health gate runs"). A
machine with no CI runs the gate itself: "With no CI" below.

## Words

- `<scratch>`: the scratch folder of the `lead` skill, with its 2 locks.
- `<work>`: the work branch. Never the default branch.
- Tree A: the integration tree, a worktree on `<work>`. Every edit is made
  here.
- `<commit>`: the commit you pushed, from
  `git -C <scratch>/wt/int rev-parse HEAD`. Never typed from the keyboard
  (P8 step 6).

Make tree A once: `git worktree add <scratch>/wt/int <work>`.

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
5. Push on the fast checks, chained behind their verdict (P14 step 2):
   `make -C <scratch>/wt/int check && git -C <scratch>/wt/int push origin HEAD:refs/heads/<work>`.
   `make check` is `make lint` and the kit's own tests (the 2 copies of
   the lead's skills, the commits' authors, the rule's documents). It starts no
   engine and takes no lock, so it runs while helpers work.
   - The push prints `HEAD -> <work>`: check the remote holds it,
     `git -C <scratch>/wt/int ls-remote origin refs/heads/<work>` prints
     `<commit>`. Go on to step 6.
   - A line from ruff, shellcheck or pytest, and no push: fix it in A,
     commit, and go back to step 4.
   - `rejected` (`fetch first` or `non-fast-forward`): someone pushed to
     `<work>`. `git -C <scratch>/wt/int pull --no-rebase origin <work>`,
     then go back to step 4. Never force a push.
6. Let GitHub run the health gate on `<commit>`. With the pull request of
   `<work>` open (step 12), the push started CI on it. With none, ask for
   a run by hand: `gh workflow run ci.yml --ref <work>`. A run by hand is
   always `full`. Find the run of `<commit>`:
   `gh run list --workflow ci.yml --commit <commit> --json databaseId,event,status,conclusion`.
   When its `status` is `completed`, read its `verdict` job:
   `gh run view <databaseId> --json jobs --jq '.jobs[] | select(.name == "verdict") | .conclusion'`.
   - `success`: the gate passed `<commit>`. Go on to step 7.
   - `failure`: read why with `gh run view <databaseId> --log-failed`.
     Fix the cause in A with a test, and go back to step 4. The fix is a
     new commit; pushed history is never rewritten.
   - `cancelled`: a newer push to `<work>` cancelled this run. Read the
     run of the newer commit instead.
   - No run is listed for `<commit>` 2 minutes after the push: the branch
     has no open pull request. Ask for a run by hand, as above.
   While CI runs, go on with the next piece in tree A (steps 1 to 4).
   Until `verdict` is green on `<commit>`, nobody merges it, releases
   from it, or starts other work from it.
7. A push carries each piece as it lands, or all the pieces that landed in
   A while 1 run of CI ran: each push makes a new `<commit>` and a new
   run. Rewrite each landed piece's card with
   `--doing "Landed on <work> as <short hash>"`; its Status stays
   `In progress` (`.claude/skills/now/SKILL.md`, steps 5 and 6).
8. The quiet of the machine is no longer needed for a landing. The
   helpers' rules about the gate's lock (P31 steps 11 to 14) apply only
   when a gate runs on the machine ("With no CI" below).

### Onto the default branch: only at the owner's word

9. Wait for the owner's word. No agent moves the default branch on its own.
10. Bring the default branch in, in tree A:
    `git -C <scratch>/wt/int fetch origin` and
    `git -C <scratch>/wt/int merge --no-edit origin/main`.
    - `Already up to date` or a merge commit: go on to step 11.
    - `CONFLICT`: keep both sides' work, `git -C <scratch>/wt/int add <files>`,
      `git -C <scratch>/wt/int commit --no-edit`, and run step 4 on every
      conflicted file's tests.
11. Push the merged tree and let CI gate it: steps 5 and 6. A merge makes
    a new commit, and it waits for its own `verdict` (P14 step 4).
12. Open a pull request from `<work>` to the default branch, if it has
    none yet:
    `gh pr create --base main --head <work> --title "<the pieces in a few words>" --body-file <scratch>/pr-body.md`.
    The body names each piece, its commit, its reviews and what each
    found, and the link of the CI run whose `verdict` passed the head
    (P14 step 5).
13. Watch its checks to the end: `gh pr checks <number> --watch`.
    - Every check passes, `verdict` among them, on the head `<commit>`:
      go on to step 14.
    - A check fails: that is work now; fix it in A and go back to step 4.
    - `main` moved since the run started
      (`git -C <scratch>/wt/int merge-base --is-ancestor origin/main <commit>`
      exits 1 after a fetch): go back to step 10. CI tested the head
      merged with the `main` of its start, and a merge commit of the new
      `main` holds a tree no run has tested.
14. Merge with a merge commit, never a squash: a squash puts the pull
    request's text into a commit message. Name the head commit, so
    GitHub refuses the merge if the head moved after its `verdict`:
    `gh pr merge <number> --merge --match-head-commit <commit>`.
    Then check: `git -C <scratch>/wt/int ls-remote origin refs/heads/main`
    names the merge commit. The push to `main` runs CI once more.
15. Close each landed piece's card as Done (`.claude/skills/now/SKILL.md`,
    step 9), and delete the worktrees of the merged pieces (the `lead`
    skill, step 14).

### With no CI: the gate on the machine

A fork without Actions or an offline machine has no `verdict`. There
the gate runs on the machine, alone, and the push waits for its
`VERIFY GREEN`. It replaces steps 5 and 6.

16. Make tree B once: the gate tree, a worktree on its own branch
    `wip/gate`. It only ever moves to a commit of `<work>`, and the gate
    runs only here, so A can be edited while the gate runs on B:
    `git -C <scratch>/wt/int worktree add -b wip/gate <scratch>/wt/gate <work>`.
17. Move tree B to the commit to gate:
    `git -C <scratch>/wt/gate merge --ff-only <work>`.
    - `Fast-forward` or `Already up to date`: go on to step 18.
    - `Not possible to fast-forward`: B holds a commit `<work>` lacks. B
      takes no edits; find it with `git -C <scratch>/wt/gate log <work>..HEAD`
      and bring it to A first.
18. Run the health gate alone and push only on `VERIFY GREEN`. Take the 2
    hashes from git: `<commit>` is `git -C <scratch>/wt/gate rev-parse HEAD`,
    and `<lease>` is the hash `git -C <scratch>/wt/gate ls-remote origin refs/heads/<work>`
    prints. Then, in the background with its output in a file:
    `GATE_DIR=<scratch> bash ee-agent-kit/lead/gate-and-push.sh <scratch>/wt/gate wip/gate <commit> <lease> <label> <work>`.
    Give that background run a time limit of 2 hours: the gate waits for
    the engine lock and for quiet before `make verify`, and 1 such wait
    took 50 minutes (P31 step 12). While it runs, edit no tool it calls
    (`ee-agent-kit/lead/gate-and-push.sh`, `ee-agent-kit/lead/quiet.py`):
    write the new version beside it and move it into place in 1 step, or
    stop the gate first (P31 step 13).
    While it runs, go on with the next piece in tree A (steps 1 to 4); run
    no test until the lock is gone. When it ends, read its exit code:
    - 0: `PUSHED <commit> to <work>`. Check the remote holds it:
      `git -C <scratch>/wt/gate ls-remote origin refs/heads/<work>` prints
      `<commit>`. Go on to step 7.
    - 1: `RED: no push`. Read the end of `<scratch>/verify-<label>.log`,
      fix the cause in tree A with a test, and go back to step 4.
    - 2: a bad call, 1 line on stderr: `GATE_DIR` is not set or is no
      folder, or an argument is missing. Mend the call; no gate ran.
    - 3: `STOP: ...`: the line says what: HEAD or the branch is not
      `<commit>`, the tree is not clean or changed during the gate, or
      another gate holds the lock. Mend that, and go back to step 17.
    - 4: no quiet in an hour. `<scratch>/gate-<label>.status` lists the
      busy processes: wait for them, or ask their helper to stop, then
      step 18 again.
    - 5: `PUSH REFUSED: ...`: someone pushed to `<work>` after you read
      the lease. `git -C <scratch>/wt/gate fetch origin`, bring their work
      into tree A, and go back to step 4. `PUSH FAILED after 5 tries`: the
      network is down; step 18 again when it is back. Never push without a
      lease.
    - 6: the quiet check failed: run it by hand,
      `python3 ee-agent-kit/lead/quiet.py $$ <scratch>`, and mend what it
      prints on stderr.
    - 129, 130 or 143: the gate was stopped. It ended `make verify` before
      it removed the lock. Step 18 again.
    If `<scratch>/gate-<label>.foreign` is not empty, a helper ran a test or
    an engine during the gate: name it in your report, and remind it of the
    lock in its next brief.

## Done when

Every finished piece is on `<work>` with its documents, and CI's
`verdict` is green on the commit `<work>` names on the remote (with no
CI: a health gate passed it alone with `VERIFY GREEN`). After the
owner's word, the default branch holds `<work>` through a merge commit
of a head whose `verdict` was green, and every landed piece's card is
closed.
