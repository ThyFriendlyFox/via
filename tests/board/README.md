# The project board follows the work cards

A work card is a GitHub issue titled `Work card: ...`. Agents keep 1 card per piece of work and
rewrite its body as the work moves. Nobody moves a card on the board by hand, and nobody edits a
card to make the board right. The workflow `.github/workflows/board.yml` runs `tools/board.py`:

- on each issue that is opened, edited, closed or reopened: that 1 card (`--event`);
- once a day at 04:17 UTC, and by hand: every card of the repository, open and closed (`--all`). A
  card whose own run was missed (the token expired, GitHub was down, the card was on the project
  before the workflow) is put right by the next such run.

Every run of Board waits in 1 queue (the concurrency group `board`, `queue: max`), so 2 runs never
write the same card at the same moment.

## When the board looks wrong

1 step: run the workflow Board by hand. On GitHub: the repository's Actions tab, Board in the list on
the left, Run workflow, Run workflow. From a shell with `gh`: `gh workflow run board.yml`.

Then open the run, the job `card`, the step "Put the card in its column". It prints 1 line per card
and a last line with the counts. Read the lines as the table "Reading a run of every card" below
says. Do not drag a card on the board. A card whose line names a column is put back in that column by
the next run of Board. A card whose body names no column stays where it was dragged, and each run
prints it as `not moved`.

## The card's line

The body carries 1 line, in the board's own 3 words:

```
**Status:** Todo
**Status:** In progress
**Status:** Done
```

- The line is the card's own only where it renders as a line: not in a code block like the one above
  (fenced, or indented 4 spaces), and not inside an HTML comment `<!-- -->`. Examples there do not
  count (CommonMark 0.31.2, 4.4, 4.5, 4.6).
- A `<!--` that does not close: the card is left where it stands, and the run says why.
- The word is matched without regard to case. The column's name and id are read from the project.
- A closed issue is Done, whatever its body says.
- No such line, 2 such lines, or another word: the card is put on the board and left where it
  stands. The run says so in 1 line.
- An issue whose author is not the owner, a member or a collaborator (`author_association`) is never
  put on the board.

## Setting it up (the owner, once)

1. Make a personal access token (classic) with the `project` and `repo` scopes. GitHub's guide
   "Automating Projects using Actions" names both; GitHub's own token cannot edit a user's project.
2. Save it as the repository secret `BOARD_TOKEN`: `gh secret set BOARD_TOKEN`.
3. Only for another board: `gh variable set BOARD_URL --body https://github.com/users/<login>/projects/<n>`.
   Without the variable the workflow uses https://github.com/users/ThyFriendlyFox/projects/2.
4. The project's single-select field `Status` holds the options Todo, In progress and Done.

## Reading a run

Open the run of the workflow Board for the issue. The step "Put the card in its column" prints 1 line.

| The line starts with | It means | Do |
|---|---|---|
| `board: card #N stands in <column> on <url>` | Done. | Nothing. |
| `board: card #N is on <url> and left where it stands:` | The body has no line in the 3 words, 2 lines, its only lines in code or a comment, or a comment that does not close. | Fix the card's `**Status:**` line; the edit runs the workflow again. |
| `board: issue #N is no work card` | The title does not start with `Work card:`. | Nothing, or retitle the issue. |
| `board: card #N is not from the owner, a member or a collaborator` | A stranger's issue. | Nothing. |
| `board: no secret BOARD_TOKEN is set` | Step 2 is not done. | Do step 2. |
| `board: FAIL: ... has no Status option "<word>"` | The project lacks the column. | Add the option to the project's Status field. |
| `board: FAIL: gh api graphql (...) exited N: ...` | GitHub refused the call: a token without the `project` scope, an expired token, or no project at the URL. | Read the rest of the line; fix the token or the URL. |
| `board: FAIL: gh api graphql (...) answered with an error:` or `printed no JSON` | gh ended well, but GitHub's answer holds `errors` or is no JSON. | Read the rest of the line; run the workflow again. |
| `board: FAIL: ... could not be read as JSON`, `... is no issues event`, `... body is ...` | The event file is not what GitHub sends for an issue. | A run by hand: pass the right file. |

Every failure is 1 line on stderr and exit 1, a missing flag too. `--help` exits 0.

## Reading a run of every card

A run on the schedule or by hand prints 1 line per work card, in the order of the issue's number,
then 1 last line: `board: N cards: M moved, A added, T already there, X not moved, F failed`. An
issue whose title does not start with `Work card:` and a pull request get no line.

| The line | It means | Do |
|---|---|---|
| `#82 In Progress: moved from Todo` | The card stood in Todo; its body says In progress. Now it stands right. | Nothing. |
| `#77 Todo: added and placed` | The card was not on the project. It is now, in its column. | Nothing. |
| `#64 In Progress: already there` | Nothing was written. | Nothing. |
| `#70 Done: moved from In Progress (the issue is closed)` | A closed card is Done, whatever its body says. | Nothing. |
| `#90 not moved: its body has no **Status:** line ...`, `... has 2 **Status:** lines`, `... says "Blocked", not ...` | The body names no column. The card stays where it stands; `; added to the board` when it was not on the project. | Fix the card's `**Status:**` line; the edit runs Board again. |
| `#93 not moved: it is not from the owner, a member or a collaborator ...` | A stranger's issue: never put on the board. | Nothing. |
| `#82 FAIL: gh api graphql (set the Status) exited 1: ...` | That card's write failed. The others were still written. The run ends red. | Read the rest of the line; run Board again by hand. |
| `#82 FAIL: GitHub answered no authorAssociation` (or `body`, `state`, `title`, `number`, `id`) | The list of issues lacks a field the decision reads, so the card is not judged. A body that is `null` is no failure: it is read as empty. | A field was dropped from the query `ISSUES` in `tools/board.py`; put it back. |
| `#82 FAIL: the project ... has no Status option "<word>" ...` | The project lacks the column. | Add the option to the project's Status field. |
| `board: FAIL: gh api graphql (list the issues, page 2) ...` or `(list the project's items, page 1) ...` | A list could not be read whole, so no card was judged and nothing was written. | Read the rest of the line; run Board again by hand. |
| `board: FAIL: --all needs --repo ...`, `--repo "..." is no <owner>/<name>` | A run by hand with a wrong flag. | Pass `--all --repo <owner>/<name> --board <url>`. |

The run does not read the project's archived items (`items` lists only items not archived, by
default, in GitHub's public GraphQL schema). A card whose item is archived is added again; GitHub's
guide says adding an item that exists already returns that item ("Adding an item to a project").
Whether that brings the item back from the archive is not judged here.

### How many calls a run makes

For I issues in the repository, P items on the project, M cards moved and A cards added:
1 (the project) + max(1, ⌈I/100⌉) (pages of issues) + max(1, ⌈P/100⌉) (pages of items) + M + 2·A.
The first page is asked even when it comes back empty. A card already in its column costs no call of
its own. The test double counts them:

| Run (`tests/test_board.py`) | I | P | M | A | Calls |
|---|---|---|---|---|---|
| `test_all_does_not_write_a_card_in_the_right_column` | 1 | 1 | 0 | 0 | 3 |
| `test_all_moves_a_card_that_stands_in_the_wrong_column` | 1 | 1 | 1 | 0 | 4 |
| `test_all_adds_and_places_a_card_that_is_not_on_the_project` | 1 | 0 | 0 | 1 | 5 |
| `test_all_reads_2_pages_of_issues_and_of_items` | 101 | 101 | 1 | 0 | 6 |

A card with no column to set that is not on the project costs 1 call (it is added and left).

## The tests

`tests/test_board.py` runs the tool with no network: `gh.py` here stands in for the `gh` program. A
test puts a script named `gh` first on PATH that runs it; it records each call in a log and answers
from these files:

| File | Answer to | Source of its shape and ids |
|---|---|---|
| `project.json` | the project and its fields | GitHub's guide "Using the API to manage Projects", "Finding the node ID of a field": options Todo, In Progress, Done |
| `project-two-columns.json` | the same, with no In progress | `project.json` less 1 option |
| `project-priority-first.json` | the same, with a single-select field Priority (P1, P2) before Status | `project.json`; Priority's ids are stand-ins |
| `project-options-null.json` | the same, with Status's options `null` | `project.json`, broken on purpose |
| `project-errors.json` | full data and an `errors` list side by side | `project.json` plus an `errors` entry whose message is a stand-in |
| `project-errors-text.json` | an `errors` list whose entry is text | a stand-in, broken on purpose |
| `not-json.txt` | any call, as text that is no JSON | a stand-in |
| `add.json` | `addProjectV2ItemById` | the same guide, "Adding an item to a project" |
| `add-no-item.json` | the same, with `item: null` | `add.json`, broken on purpose |
| `update.json` | `updateProjectV2ItemFieldValue` | the same guide, "Updating a single select field" (its return field) |
| `gh-no-auth.txt` | any call, as a failure | what gh 2.89.0 printed on stderr with no token, exit 4, run on 2026-11-17 |

The project's id `PVT_stand-in-project` is a stand-in: the guide prints none for a user's project.
`BOARD_GH_PROJECT` and `BOARD_GH_ADD` pick the answer file; `BOARD_GH_SLEEP` makes each call wait, for
the test of the time limit.

The tests of `--all` write their pages into the test's own folder: `BOARD_GH_ISSUES` and
`BOARD_GH_ITEMS` name a JSON file that maps each page's cursor to GitHub's answer for that page (`""`
for the first). Their shape is GitHub's public GraphQL schema (docs.github.com/public/fpt/
schema.docs.graphql, read on 2026-11-17): `Repository.issues`, `ProjectV2.items`, `ProjectV2Item`,
`ProjectV2ItemFieldSingleSelectValue` (`name`, `optionId`, `field`) and `PageInfo`; ids and cursors
are stand-ins. `BOARD_GH_ADD_ECHO` makes an add answer `PVTI_for_<issue id>`, so a test sees which
card each later write is for; `BOARD_GH_FAIL_ITEM` refuses the write of 1 item.

`gh.py` cuts every answer to the query, as GitHub does: a key the query does not name is dropped,
and `states: [...]` keeps only the issues in those states. A field dropped from `ISSUES` or `ITEMS`
in `tools/board.py` is then missing in the tests too, and a test fails. 2 tests hold the cut itself.

`tests/test_board.py` also reads the workflow: its 3 triggers (the 4 issue events, a run by hand, 1
schedule at a minute that is not 0), its permissions, its 1 concurrency group `board` with
`queue: max`, a sparse checkout of the very file the step runs, no expression in a `run:`, and the
step run by bash with and without the secret, for an issue event, a schedule and a run by hand.
