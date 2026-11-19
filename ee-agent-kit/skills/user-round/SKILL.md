---
name: User Round
description: The routine that keeps the roadmap pointed at the goal - a small model, given only this repository, reaches the same working board a senior engineer would. 3 users of different sizes take 1 board spec to a board that passes every gate with only the repository's documents and `workcenter next`; where the small one fails and the large one does not is a process not written down; the points become ranked roadmap candidates, each with a test.
---

# User round

The goal of Via: a small model, given only this repository,
reaches the same working board a senior engineer would. A user round
measures how far that holds today and turns the gap into roadmap work.

3 users take 1 board spec to a board that passes every gate, each using
only the repository's documents and `workcenter next`. The users differ
in size: a small model, a medium model and a large model, as the host
names them. Each logs every point where it was stuck, guessed, or used
knowledge the repository did not give.

- A point where the small user fails and the large one does not is a
  process that is not written down.
- A point where all 3 fail is a fault of a tool or of a document.
- A point only the large user notices is polish.

## Scripts or by hand

`ee-agent-kit/lead/workflows/user-round.js` runs steps 3 to 6 on a host
that runs workflow scripts; its header names its args, the 3 model names
among them. A host without such scripts does the same steps by hand: it
starts 3 helpers with the brief of the function `userPrompt` of that
file, 1 per size, then a fourth with the ranking brief, and keeps their
logs under `<scratch>/users/`.

## Steps

1. Choose the spec: 1 board, described as its owner would describe it
   (what it does, its inputs and outputs, its size, its power), with no
   part numbers and no layout. Each round takes a spec no earlier round
   used: the earlier rounds' specs are in `ee-agent-kit/DEVLOG.md`.
2. Make a checkout of the repository at the commit to be tried, in a
   folder of its own, and a folder per user:
   `git worktree add --detach <scratch>/wt/round <commit>` and
   `mkdir -p <scratch>/users/small <scratch>/users/medium <scratch>/users/large`.
   The users read the checkout and write only in their own folder.
3. Start the 3 users at once, each with the same brief and its own folder.
   The brief says:
   - the checkout is read-only; start from its `README.md`, and ask
     `workcenter next <project>` whenever the next step is not plain;
   - read no source under `tools/` unless a document or a command's
     message sends you there; having to read source is a point to log;
   - every fact taken from your own knowledge, not from the repository,
     is logged;
   - work until every gate is GREEN or you can go no further; never skip
     a check, weaken a limit, or edit a generated KiCad file;
   - engines behind `flock <scratch>/ENGINE.lock`; no engine while
     `<scratch>/GATE.lock` exists;
   - hand back: how far you got with the last line the command printed,
     and each point: what you tried, the kind (stuck, guessed, error,
     missing knowledge, 2 documents that disagree, too long, a wrong
     result), the command and its output or the document and its line,
     and what would have let you pass without guessing.
4. Read each log as data. Check a claim against the checkout before it
   counts:
   - a command and its output: run the command in a scratch folder;
   - a document and its line: open the line.
   A point you cannot reproduce is dropped, and the ranking says so.
5. Rank the points. Start a fourth helper, or do it yourself, with the 3
   logs and `ee-agent-kit/ROADMAP.md`:
   - merge the same point from 2 logs into 1 candidate;
   - rank first what the small user failed and the large did not, then
     what all 3 failed, then polish;
   - give each candidate the change as something a command does, checks
     or prints, or a numbered step a document gains;
   - give each candidate its test: what the small user does at that point
     after the change;
   - name the roadmap item or the row under "Later" that covers it
     already, or say it is new.
6. Place the candidates on the roadmap. The roadmap is a shared document:
   write the entries into a docs file,
   `<scratch>/roadmap/user-round-<date>-docs.md`, for the integrator (the
   `land` skill, step 3).
   - A candidate an item covers: the item's Evidence gains the small
     user's test.
   - A new candidate ranked in the first 3: a queue entry with Promise,
     Evidence (the small user's test), Use case and Scope guard.
   - Every other new candidate: a row under "Later" with its 6 scores
     (`ee-agent-kit/PROCESSES.md` P35 step 7).
   - The round itself: a `DEVLOG.md` entry with the date, the spec, the
     commit tried, how far each user got, and the count of points.
7. Start helpers on the first candidates: the `lead` skill, from its
   step 1. The round has done its work when they build.
8. The next round takes another spec (step 1), on the commit where the
   first candidates have landed. A candidate is met when the small user
   of a later round passes its point.

## Done when

The 3 logs are read and checked, every point is a candidate or is dropped
with the reason, the docs file holds the roadmap's entries and the
devlog's, and helpers are at work on the first candidates.
