# The project board follows the work cards

A work card is a GitHub issue titled `Work card: ...`. Agents keep 1 card per piece of work and
rewrite its body as the work moves. Nobody moves a card on the board by hand: the workflow
`.github/workflows/board.yml` runs `tools/board.py` on each issue that is opened, edited, closed or
reopened, and the card stands in the column its body names.

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
the test of the time limit. `tests/test_board.py` also reads the workflow: its 4 triggers, its
permissions, its concurrency group per issue, a sparse checkout of the very file the step runs, no
expression in a `run:`, and the step run by bash with and without the secret.
