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

Every answer is cut to the query, as GitHub answers: a key under `data` that the query does not name
is dropped, and the fields of a fragment (`... on X { }`) count at the level the fragment stands at.
A query of issues with `states: [...]` gets only the issues in those states. So a field dropped from
a query of the tool is missing in the answer, as it would be from GitHub, and the tests see it.
"""

import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def selection(query: str) -> dict | None:
    """The fields a query names, as a tree: {name: subtree or None for a leaf}. Arguments are skipped."""
    flat, depth = [], 0
    for ch in query:
        depth += ch == "("
        if not depth:
            flat.append(ch)
        depth -= ch == ")"
    tokens = re.findall(r"\.\.\.|[A-Za-z_][A-Za-z0-9_]*|[{}]", "".join(flat))
    pos = tokens.index("{") + 1

    def block() -> dict:
        nonlocal pos
        out: dict = {}
        while tokens[pos] != "}":
            if tokens[pos] == "...":
                pos += 4  # `...`, `on`, the type, `{`
                merge(out, block())
                continue
            name, pos = tokens[pos], pos + 1
            sub = None
            if pos < len(tokens) and tokens[pos] == "{":
                pos += 1
                sub = block()
            merge(out, {name: sub})
        pos += 1
        return out

    return block()


def merge(into: dict, more: dict) -> None:
    for key, sub in more.items():
        if isinstance(into.get(key), dict) and isinstance(sub, dict):
            merge(into[key], sub)
        else:
            into[key] = sub if sub is not None else into.get(key)


def cut(value, tree):
    """The value with only the keys the tree names."""
    if tree is None:
        return value
    if isinstance(value, list):
        return [cut(v, tree) for v in value]
    if isinstance(value, dict):
        return {k: cut(v, tree[k]) for k, v in value.items() if k in tree}
    return value


def answer_to(query: str, answer: dict) -> dict:
    """GitHub's answer for the query: `data` cut to its fields, issues filtered by `states`."""
    if not isinstance(answer, dict) or not isinstance(answer.get("data"), dict):
        return answer
    data = answer["data"]
    states = re.search(r"states:\s*\[([^\]]*)\]", query)
    issues = data.get("repository", {}).get("issues") if isinstance(data.get("repository"), dict) else None
    if states and isinstance(issues, dict) and isinstance(issues.get("nodes"), list):
        wanted = set(re.findall(r"[A-Z]+", states.group(1)))
        issues["nodes"] = [
            n for n in issues["nodes"] if not isinstance(n, dict) or n.get("state", "") in wanted | {""}
        ]
    return {**answer, "data": cut(data, selection(query))}


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
    sys.stdout.write(json.dumps(answer_to(query, pages[cursor])))
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
text = (HERE / answer).read_text(encoding="utf-8")
try:
    text = json.dumps(answer_to(query, json.loads(text)))
except json.JSONDecodeError:
    pass  # a file that is no JSON on purpose is printed as it is
sys.stdout.write(text)
