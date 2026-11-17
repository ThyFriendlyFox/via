"""A stand-in for the `gh` program: it records each call and answers from the canned files beside it.

The tests put a script named `gh` first on PATH that runs this file. Each call is appended to the
file BOARD_GH_LOG as 1 JSON line (the arguments). A `gh api graphql` call is answered by the kind of
its query: `projectV2(number` by BOARD_GH_PROJECT (default `project.json`), `addProjectV2ItemById` by
BOARD_GH_ADD (default `add.json`), `updateProjectV2ItemFieldValue` by `update.json`. With BOARD_GH_FAIL
set to a file name, every call prints that file to stderr and exits with BOARD_GH_FAIL_CODE (default
1), as gh does. With BOARD_GH_SLEEP set, every call first waits that many seconds.

For a run of `--all`: a query of a repository's issues (`issues(first`) is answered from the file
BOARD_GH_ISSUES names, and a query of a project's items (`items(first`) from BOARD_GH_ITEMS. Each file
holds 1 JSON object that maps a page's cursor to GitHub's answer for that page; the first page, asked
with no cursor, is the key "". With BOARD_GH_ADD_ECHO set, `addProjectV2ItemById` answers the item id
`PVTI_for_<content>`, so a test sees which issue each later write is for. With BOARD_GH_FAIL_ITEM set
to an item id, the `updateProjectV2ItemFieldValue` call for that item prints a stand-in failure and
exits 1, and every other call is answered.
"""

import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

args = sys.argv[1:]
with open(os.environ["BOARD_GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\n")

time.sleep(float(os.environ.get("BOARD_GH_SLEEP", "0")))

fail = os.environ.get("BOARD_GH_FAIL")
if fail:
    sys.stderr.write((HERE / fail).read_text(encoding="utf-8"))
    sys.exit(int(os.environ.get("BOARD_GH_FAIL_CODE", "1")))

query = next((a[len("query=") :] for a in args if a.startswith("query=")), "")
if args[:2] != ["api", "graphql"] or not query:
    sys.stderr.write(f"stand-in gh: no answer for {args!r}\n")
    sys.exit(1)
fields = dict(a.partition("=")[::2] for a in args[3::2])


def page(env: str) -> None:
    pages = json.loads(Path(os.environ[env]).read_text(encoding="utf-8"))
    cursor = fields.get("cursor", "")
    if cursor not in pages:
        sys.stderr.write(f"stand-in gh: no page for the cursor {cursor!r}\n")
        sys.exit(1)
    sys.stdout.write(json.dumps(pages[cursor]))
    sys.exit(0)


if "issues(first" in query:
    page("BOARD_GH_ISSUES")
elif "items(first" in query:
    page("BOARD_GH_ITEMS")
elif "addProjectV2ItemById" in query and os.environ.get("BOARD_GH_ADD_ECHO"):
    item = {"id": f"PVTI_for_{fields['content']}"}
    sys.stdout.write(json.dumps({"data": {"addProjectV2ItemById": {"item": item}}}))
    sys.exit(0)
elif "updateProjectV2ItemFieldValue" in query and fields.get("item") == os.environ.get("BOARD_GH_FAIL_ITEM"):
    sys.stderr.write("stand-in gh: this write is refused on purpose\n")
    sys.exit(1)

if "addProjectV2ItemById" in query:
    answer = os.environ.get("BOARD_GH_ADD", "add.json")
elif "updateProjectV2ItemFieldValue" in query:
    answer = "update.json"
elif "projectV2(number" in query:
    answer = os.environ.get("BOARD_GH_PROJECT", "project.json")
else:
    sys.stderr.write("stand-in gh: a query of no known kind\n")
    sys.exit(1)
sys.stdout.write((HERE / answer).read_text(encoding="utf-8"))
