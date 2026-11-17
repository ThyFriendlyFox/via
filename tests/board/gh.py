"""A stand-in for the `gh` program: it records each call and answers from the canned files beside it.

The tests put a script named `gh` first on PATH that runs this file. Each call is appended to the
file BOARD_GH_LOG as 1 JSON line (the arguments). A `gh api graphql` call is answered by the kind of
its query: `projectV2(number` by BOARD_GH_PROJECT (default `project.json`), `addProjectV2ItemById` by
`add.json`, `updateProjectV2ItemFieldValue` by `update.json`. With BOARD_GH_FAIL set to a file name,
every call prints that file to stderr and exits with BOARD_GH_FAIL_CODE (default 1), as gh does.
"""

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

args = sys.argv[1:]
with open(os.environ["BOARD_GH_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\n")

fail = os.environ.get("BOARD_GH_FAIL")
if fail:
    sys.stderr.write((HERE / fail).read_text(encoding="utf-8"))
    sys.exit(int(os.environ.get("BOARD_GH_FAIL_CODE", "1")))

query = next((a[len("query=") :] for a in args if a.startswith("query=")), "")
if args[:2] != ["api", "graphql"] or not query:
    sys.stderr.write(f"stand-in gh: no answer for {args!r}\n")
    sys.exit(1)
if "addProjectV2ItemById" in query:
    answer = "add.json"
elif "updateProjectV2ItemFieldValue" in query:
    answer = "update.json"
elif "projectV2(number" in query:
    answer = os.environ.get("BOARD_GH_PROJECT", "project.json")
else:
    sys.stderr.write("stand-in gh: a query of no known kind\n")
    sys.exit(1)
sys.stdout.write((HERE / answer).read_text(encoding="utf-8"))
