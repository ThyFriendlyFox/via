"""`tools/harvest.py`: what the projects taught Via, read from the repository itself.

Each test builds a small repository with git and reads it back: branches that landed, a branch from
before main's history was rewritten, a branch whose mistake and step were renumbered when they landed,
a branch that holds a tool main lacks. No engine runs.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import harvest  # noqa: E402

TOOL = ROOT / "tools" / "harvest.py"
IDENTITY = ("-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false")
A = "def first_tool_of_the_workcenter():\n    return 'a line long enough to be told apart'\n"
LOG = """# MISTAKES

## M1 — 2026-01-01 — A route started before the rules were set
What happened: the first mistake of the log, told in a sentence.
Process: P1
"""
STEPS = """# PROCESSES

## P1 — Before every route

1. Set the design rules before the first route of a board.

Done when: the rules are in the design file.
"""
# What the branch `rewritten` adds, with the numbers the branch gave them ...
ENTRY = """
## M2 — 2026-01-02 — A second route started the same way, after M1
What happened: the same mistake made again on another board (M1).
Process: P1
"""
STEP = "2. Read the rules back from the board file before the route starts (M2).\n"
LATE = "def second_tool_added_by_the_branch():\n    return 'another line of the workcenter'\n"
# ... and what another branch landed on main first: 1 entry and 1 step, so the 2 above moved up by 1.
OTHER_ENTRY = """
## M2 — 2026-01-02 — A count typed from memory
What happened: a number in a document that no command gave.
Process: P9
"""
OTHER_STEP = "2. Name the board's fab before its rules are written.\n"
B = "def a_tool_main_never_took():\n    first = 'held by the branch alone'\n    return first.upper()\n"


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(repo), *IDENTITY, *args], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def commit(repo: Path, message: str, files: dict[str, str]) -> str:
    for name, text in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def kit(log: str, steps: str) -> dict[str, str]:
    return {"ee-agent-kit/MISTAKES.md": log, "ee-agent-kit/PROCESSES.md": steps}


@pytest.fixture
def repo(tmp_path) -> Path:
    """main: c1 (a tool, the 2 logs), c2 (a project), c3 (what 2 branches landed). Beside it 5 branches."""
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    first = {"tools/a.py": A, **kit(LOG, STEPS)}
    c1 = commit(path, "c1", first)
    git(path, "branch", "merged", c1)
    c2 = commit(path, "c2", {"examples/blink/v0.1/design.py": "# a project's design file\n"})
    # a branch from before a rewrite: other commits, the same tree as c1, then work of its own
    git(path, "checkout", "-q", "--orphan", "rewritten")
    git(path, "rm", "-rq", "--cached", ".")
    (path / "examples" / "blink" / "v0.1" / "design.py").unlink()
    commit(path, "the tree of c1 under another commit", first)
    git(path, "branch", "stale")
    with_step = STEPS.replace("\nDone when", STEP + "\nDone when")
    commit(path, "a tool, a mistake and a step", {"tools/a.py": A + LATE, **kit(LOG + ENTRY, with_step)})
    # a branch that holds a tool main never took, 1 line main has, and a project's file
    git(path, "checkout", "-q", "-b", "open", c2)
    commit(
        path,
        "a tool main lacks",
        {
            "tools/a.py": A + LATE.splitlines()[0] + "\n",
            "tools/b.py": B,
            "examples/blink/v0.2/design.py": "# the next version\n",
        },
    )
    git(path, "checkout", "-q", "-b", "project-only", c2)
    commit(path, "a project's own script", {"examples/blink/v0.1/notes.py": "print('a project note')\n"})
    # main takes the other branch's entry and step first, then `rewritten`'s work under the next numbers
    git(path, "checkout", "-q", "main")
    moved_step = STEP.replace("2. ", "3. ").replace("(M2)", "(M3)")
    both_steps = STEPS.replace("\nDone when", OTHER_STEP + moved_step + "\nDone when")
    both_entries = LOG + OTHER_ENTRY + ENTRY.replace("## M2", "## M3")
    commit(path, "c3", {"tools/a.py": A + LATE, **kit(both_entries, both_steps)})
    return path


def test_each_branch_is_read_for_what_it_added_to_the_workcenter_and_main_lacks(repo):
    found = {entry["branch"]: entry for entry in harvest.branches(repo, "main", "refs/heads")}
    assert {name: entry["state"] for name, entry in found.items()} == {
        "main": "is main",
        "merged": "in main's history",
        "stale": "a state main had: nothing of its own",
        "rewritten": "landed: every line it added to Via is on main",
        "open": "3 of 4 lines it added to Via are not on main",
        "project-only": "its own commits change nothing of Via itself",
    }
    # A branch from before a rewrite shares no commit with main. Its base is the commit whose tree
    # main's history holds, and only the commit after it is its own.
    rewritten = found["rewritten"]
    assert rewritten["own_commits"] == 1 and rewritten["base_found_by"].startswith("the tree of main's ")
    # Its entry was M2 and its step 2 on the branch; on main they are M3 and step 3, and still its
    # lines. 5 are counted: 2 of the tool, the entry's heading and its first line, the step. The
    # entry's `Process: P1` is under 14 characters and tells nothing apart.
    added = (rewritten["own_lines_added"], rewritten["own_lines_on_main"], rewritten["lacking"])
    assert added == (5, 5, [])
    # A branch cut from main: 1 of its 4 lines is on main, and the 3 of a file main never took are named.
    opened = found["open"]
    assert (opened["base_found_by"], opened["own_commits"]) == ("merge base", 1)
    assert opened["share_on_main"] == 0.25
    assert opened["lacking"] == [
        {
            "path": "tools/b.py",
            "area": "tools",
            "file_on_main": False,
            "added": 3,
            "missing": 3,
            "first": [
                "def a_tool_main_never_took():",
                "first = 'held by the branch alone'",
                "return first.upper()",
            ],
        }
    ]
    assert opened["areas"] == {"examples": {"files": 1, "added": 1}, "tools": {"files": 2, "added": 4}}
    assert found["project-only"]["areas"] == {"examples": {"files": 1, "added": 1}}


def test_a_short_line_counts_only_when_main_does_not_hold_it(repo):
    """A version pin or a 1-line fix is short, and it is a branch's whole work: 2 pins of a dependency
    branch were under the limit, and the branch read as one that changes nothing of Via.
    A short line that main's file holds anywhere proves nothing, and is left out as before."""
    pins = "ruff==0.1\npytest==9.1\n"
    commit(repo, "main pins 2 tools", {"requirements.txt": pins, "tools/a.py": A + LATE})
    git(repo, "checkout", "-q", "-b", "pins")
    commit(repo, "1 pin moves", {"requirements.txt": pins.replace("0.1", "0.2")})
    git(repo, "checkout", "-q", "-b", "short", "main")
    commit(repo, "2 short lines", {"tools/a.py": A + "    return 1\n" + LATE + "x = 1\n"})
    git(repo, "checkout", "-q", "main")
    commit(repo, "main gets 1 of them", {"tools/a.py": A + LATE + "x = 1\n"})
    found = {entry["branch"]: entry for entry in harvest.branches(repo, "main", "refs/heads")}
    assert found["pins"]["state"] == "1 of 1 lines it added to Via are not on main"
    assert found["pins"]["lacking"][0]["first"] == ["ruff==0.2"]
    # `x = 1` is in main's file and proves nothing; `return 1` is in no line of it and is missing
    assert found["short"]["state"] == "1 of 1 lines it added to Via are not on main"
    assert found["short"]["lacking"][0]["first"] == ["return 1"]


def test_a_line_is_held_without_the_numbers_that_move_when_another_branch_lands():
    assert harvest.plain("  7. Read the rules back (M162, P9).  ") == "#. Read the rules back (M#, P#)."
    assert harvest.plain("## M12 — 2026-01-02 — A title") == "## M# — 2026-01-02 — A title"
    # a number inside a word, a value or a sentence is no mistake's number and no step
    kept = "RM12 is 4.7 k; FM3 and 12. are kept"
    assert harvest.plain(kept) == kept
    paths = ("tools/x.py", "ee-agent-kit/MISTAKES.md", "examples/a/b.py", "x.txt", ".github/workflows/ci.yml")
    assert [harvest.area(p) for p in paths] == ["tools", "kit", "examples", "other", "ci"]
    # CI is Via's own: a branch that moves an action's version holds a line main lacks
    assert "ci" in harvest.OWN and "examples" not in harvest.OWN and "site" not in harvest.OWN


def test_the_scripts_projects_wrote_for_themselves_are_listed_by_name(repo):
    models = "def box(w, d, h):\n    return (w, d, h)\n\n\ndef main():\n    box(1, 2, 3)\n"
    tube = "\n\ndef tube(r, h):\n    return (r, h)\n"
    commit(
        repo,
        "2 projects write their own scripts",
        {
            "examples/blink/v0.1/models/make_models.py": models,
            "examples/blink/v0.2/models/make_models.py": models + tube,
            "examples/lamp/v0.1/models/make_models.py": "def box(w, d, h):\n    return w * d * h\n" + tube,
            "examples/lamp/v0.1/ring.py": "def tile(n):\n    return n\n",
            "examples/lamp/v0.1/firmware/tool.py": "def flash():\n    return 0\n",
            "examples/lamp/v0.1/design.py": "# every project has one\n",
        },
    )
    blink = "examples/blink"
    assert harvest.scripts(repo, "HEAD") == [
        {
            "script": "make_models.py",
            "projects": 2,
            "files": 3,
            "where": {
                "blink": [f"{blink}/v0.1/models/make_models.py", f"{blink}/v0.2/models/make_models.py"],
                "lamp": ["examples/lamp/v0.1/models/make_models.py"],
            },
            # read from each project's newest version: blink's v0.2 has `tube` too
            "functions_in_2_or_more": {"box": 2, "tube": 2},
        },
        {
            "script": "ring.py",
            "projects": 1,
            "files": 1,
            "where": {"lamp": ["examples/lamp/v0.1/ring.py"]},
            "functions_in_2_or_more": {},
        },
    ]


def test_a_mistake_made_again_is_an_entry_that_names_an_earlier_one_of_its_process():
    undated = "\n## M4 — A heading with no date\nWhat happened: it cites M2, of process P9.\nProcess: P1\n"
    counted = "\n## M5 — 2026-01-05 — Another count from memory (M2)\nWhat happened: again.\nProcess: P9\n"
    log = LOG + OTHER_ENTRY + ENTRY.replace("## M2", "## M3") + undated + counted
    steps = STEPS + "\n## P9 — Scripted edits\n\n1. A count comes from a command.\n\nDone when: it does.\n"
    second = "A second route started the same way, after M1"
    assert harvest.mistakes(log, steps) == [
        {
            "process": "P1",
            "name": "Before every route",
            "entries": [1, 3, 4],
            "again": [{"entry": 3, "title": second, "names": [1]}],
        },
        {
            "process": "P9",
            "name": "Scripted edits",
            "entries": [2, 5],
            "again": [{"entry": 5, "title": "Another count from memory (M2)", "names": [2]}],
        },
    ]


def test_the_command_prints_each_listing_and_writes_nothing(repo):
    def state() -> list[str]:
        files = (p for p in repo.rglob("*") if p.is_file() and ".git" not in p.parts)
        return sorted(str(p.relative_to(repo)) for p in files)

    before = state()

    def run(*args: str) -> subprocess.CompletedProcess:
        command = [sys.executable, str(TOOL), "--repo", str(repo), *args]
        return subprocess.run(command, capture_output=True, text=True, check=False)

    listed = run("branches", "--main", "main", "--refs", "refs/heads")
    assert (listed.returncode, listed.stderr) == (0, "")
    lines = listed.stdout.splitlines()
    assert lines[-1] == (
        "6 branches: 1 hold lines of Via that main lacks, 1 landed, 1 change nothing of "
        "Via itself, 3 hold nothing of their own"
    )
    # the branch that holds the most of its own comes first, with the file and its first lines
    assert lines[0].split()[0] == "open" and lines[0].endswith(
        "25% on main   3 of 4 lines it added to Via are not on main"
    )
    assert lines[1:3] == [
        "    tools/b.py: 3 of 3 lines (main has no file of this path)",
        "        | def a_tool_main_never_took():",
    ]
    as_data = run("--json", "branches", "--main", "main", "--refs", "refs/heads")
    names = [entry["branch"] for entry in json.loads(as_data.stdout)]
    assert names == ["main", "merged", "open", "project-only", "rewritten", "stale"]
    again = run("mistakes", "--ref", "main")
    assert again.returncode == 0 and again.stdout.splitlines() == [
        "P1      2 entries,  1 again  Before every route",
        "    M3 (after M1)",
        "P9      1 entries,  0 again  ",
        "3 entries under 2 processes; 1 name an earlier entry of their own process",
    ]
    none = run("scripts", "--ref", "main").stdout.splitlines()
    assert none == ["0 script names; 0 written by 2 or more projects"]
    refused = run("branches", "--main", "no-such-ref")
    assert refused.returncode != 0 and refused.stderr.startswith("harvest: git rev-parse no-such-ref: ")
    assert state() == before


def test_a_listing_cut_short_by_its_reader_ends_without_a_traceback():
    """`harvest.py mistakes | head -4` closes the pipe after 4 lines. The tool printed Python's
    traceback of a BrokenPipeError for it; a reader that has what it asked for is no error."""
    tool = subprocess.Popen(
        [sys.executable, str(TOOL), "mistakes"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    first = tool.stdout.readline()
    tool.stdout.close()
    said = tool.stderr.read()
    tool.stderr.close()
    assert first.startswith("P") and " entries, " in first
    assert (tool.wait(), said) == (0, "")


# ------------------------------------------------------------------ the rated candidates

HEAD = (
    "| Rating | Candidate | Evidence | f | c | l | g | e | r | Checked |\n"
    "|---|---|---|---|---|---|---|---|---|---|\n"
)
ROW_9 = (
    "| 9 | **Pads checked before a route.** A class wider than its pad. | M1 "
    "| 3 | 3 | 3 | 3 | 2 | 1 | 2026-11-12 |\n"
)
ROW_5 = (
    "| 5 | **A legend cut at the edge.** One switch. | `tools/a.py` line 2 | 2 | 1 | 2 | 2 | 1 | 1 | no |\n"
)
ONE_ENTRY = ROW_5.replace("`tools/a.py` line 2", "M1")


def roadmap(rows: str, before: str = "") -> str:
    head = "# Roadmap\n\n## Later — candidates\n\nWhat a rating is.\n"
    return f"{head}{before}\n{HEAD}{rows}\n## Shipped\n\n- a thing\n"


def test_the_candidates_under_later_are_held_to_their_scores_their_order_and_their_evidence(tmp_path):
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "a.py").write_text(A, encoding="utf-8")
    good = harvest.later(roadmap(ROW_9 + ROW_5), LOG, tmp_path)
    assert good["problems"] == []
    assert good["candidates"] == [
        {
            "line": 9,
            "title": "Pads checked before a route",
            "rating": 9,
            "scores": {"f": 3, "c": 3, "l": 3, "g": 3, "e": 2, "r": 1},
            "checked": "2026-11-12",
        },
        {
            "line": 10,
            "title": "A legend cut at the edge",
            "rating": 5,
            "scores": {"f": 2, "c": 1, "l": 2, "g": 2, "e": 1, "r": 1},
            "checked": "no",
        },
    ]

    def problems(rows: str, before: str = "") -> list[str]:
        return harvest.later(roadmap(rows, before), LOG, tmp_path)["problems"]

    # a rating its scores do not give; the row above it in the order; a score outside its anchors
    assert problems(ROW_9.replace("| 9 |", "| 10 |", 1)) == [
        "line 9: Pads checked before a route: rated 10, and its scores give 9"
    ]
    assert problems(ROW_5 + ROW_9) == ["line 10: Pads checked before a route: rated 9, under a row rated 5"]
    assert problems(ROW_9.replace("| 3 | 3 | 3 | 3 | 2 | 1 |", "| 4 | 3 | 3 | 3 | 3 | 1 |")) == [
        "line 9: Pads checked before a route: f is 4, outside 1 to 3"
    ]
    # leverage alone can be 0: a cosmetic change
    cosmetic = ROW_5.replace("| 5 |", "| 3 |", 1).replace("| 2 | 1 | 2 | 2 |", "| 2 | 1 | 0 | 2 |")
    assert problems(cosmetic) == []
    assert problems(ROW_5.replace("| 5 |", "| 2 |", 1).replace("| 2 | 1 | 2 | 2 |", "| 0 | 1 | 1 | 2 |")) == [
        "line 9: A legend cut at the edge: f is 0, outside 1 to 3"
    ]
    # evidence a reader can open: an entry of the log, a file of the tree
    assert problems(ROW_9.replace("| M1 |", "| M7 |")) == [
        "line 9: Pads checked before a route: the evidence names M7, and the log has no such entry"
    ]
    assert problems(ROW_5.replace("tools/a.py", "tools/gone.py")) == [
        "line 9: A legend cut at the edge: the evidence names `tools/gone.py`, and no such file is there"
    ]
    assert problems(ROW_9.replace("| M1 |", "| three projects met it |")) == [
        "line 9: Pads checked before a route: the evidence names no mistake (M150) and no file in backticks"
    ]
    # a line of a file is a line the file has: `tools/a.py` has 2
    assert problems(ROW_5.replace("line 2", "line 3")) == [
        "line 9: A legend cut at the edge: the evidence names line 3 of `tools/a.py`, which has 2 lines"
    ]
    assert problems(ROW_5.replace("`tools/a.py` line 2", "`tools/` line 3")) == []
    # a word in backticks that names no folder of the repository is no file: a function's name
    assert problems(ROW_5.replace("line 2", "(`first_tool_of_the_workcenter`)")) == []
    # a candidate that is not a row, a row without its title, a day that is no day
    assert problems(ROW_9, before="- Copper pours in kicadgen, a zone per power net with a refill\n") == [
        "line 6: a candidate outside the table: Copper pours in kicadgen, a zone per power net w..."
    ]
    assert problems(ROW_9.replace("**Pads checked before a route.**", "Pads checked before a route.")) == [
        "line 9: the candidate does not start with its title in bold"
    ]
    assert problems(ROW_9.replace("2026-11-12", "yes")) == [
        "line 9: Pads checked before a route: Checked is the day a reader checked it, or `no`"
    ]
    short = ROW_9.replace("| 2 | 1 | 2026", "| 2 | 2026")
    assert problems(short) == ["line 9: 9 cells where the table has 10"]
    assert problems(ROW_9.replace("| 9 |", "| nine |", 1)) == [
        "line 9: Pads checked before a route: the rating and the 6 scores are whole numbers"
    ]
    assert harvest.later("# Roadmap\n\n## Queue\n", LOG, tmp_path)["problems"] == ['no "## Later" heading']
    assert harvest.later("# Roadmap\n\n## Later\n\nNothing yet.\n", LOG, tmp_path)["problems"] == [
        'no table under "## Later"'
    ]
    bad_head = roadmap(ROW_9).replace("| Checked |", "| Seen |")
    assert harvest.later(bad_head, LOG, tmp_path)["problems"][0] == (
        "line 7: the table's columns are not Rating | Candidate | Evidence | f | c | l | g | e | r | Checked"
    )


def test_the_later_command_fails_on_a_row_that_does_not_hold(tmp_path):
    kit = tmp_path / "ee-agent-kit"
    kit.mkdir()
    (kit / "MISTAKES.md").write_text(LOG, encoding="utf-8")
    (kit / "ROADMAP.md").write_text(roadmap(ROW_9 + ONE_ENTRY), encoding="utf-8")

    def later() -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(TOOL), "--repo", str(tmp_path), "later"], capture_output=True, text=True
        )

    listed = later()
    assert (listed.returncode, listed.stderr) == (0, "")
    assert listed.stdout.splitlines() == [
        "  9  f3 c3 l3 g3  e2 r1  checked 2026-11-12 Pads checked before a route",
        "  5  f2 c1 l2 g2  e1 r1  not checked        A legend cut at the edge",
        "2 candidates; 1 not yet checked by a reader",
    ]
    (kit / "ROADMAP.md").write_text(roadmap(ONE_ENTRY + ROW_9), encoding="utf-8")
    listed = later()
    assert listed.returncode == 1
    assert listed.stdout.splitlines()[-1] == (
        "  line 10: Pads checked before a route: rated 9, under a row rated 5"
    )


def test_the_roadmaps_own_candidates_are_rated_and_in_order():
    """P35's "Done when", held by `make verify`: every candidate under "Later" is a row with its
    evidence and its 6 scores, its rating is what they give, and the rows stand highest first."""
    kit = ROOT / "ee-agent-kit"
    roadmap_text = (kit / "ROADMAP.md").read_text(encoding="utf-8")
    rated = harvest.later(roadmap_text, (kit / "MISTAKES.md").read_text(encoding="utf-8"), ROOT)
    assert rated["problems"] == []
    assert len(rated["candidates"]) >= 10
