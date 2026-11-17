"""`workcenter now`: the card of 1 piece of work in progress, built from a scratch git tree.

Each tree here is made in a temporary folder: a branch with a known name, 1 commit with a known subject,
a roadmap with a known heading and, where a test needs one, a gate record that `make verify` leaves in
`build/verify.json`. The card's text is written out by hand in each test, from those inputs:

    branch     wip/item-7, its commit's subject `Add the first file`
    roadmap    `### 7. A card for each piece of work` -> the title
               `Work card: Roadmap item 7: A card for each piece of work`
    record     GREEN at 4/4 kit checks on the tree's HEAD at 2026-11-17T09:41:00Z
               -> GREEN on `<short HEAD>` at 2026-11-17 09:41 UTC

The card's first line is `**Status:**` and 1 of the project board's own 3 words, which tools/board.py
reads; the card repeats nothing else the board shows: the work is the issue's title, not a section.
The short hash is git's own (`git rev-parse --short HEAD`): the card prints what git prints.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
NOW_PY = ROOT / "tools" / "now.py"
TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "now.md"
SKILL = ROOT / ".claude" / "skills" / "now" / "SKILL.md"
STALE = ROOT / ".github" / "workflows" / "stale.yml"
sys.path.insert(0, str(ROOT / "tools"))
import board  # noqa: E402

BRANCH = "wip/item-7"
SUBJECT = "Add the first file"
TITLE = "Work card: Roadmap item 7: A card for each piece of work"
ROADMAP = "# Roadmap\n\n## Feature Queue\n\n### 7. A card for each piece of work\n- **Promise:** x\n"
GIT = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false"]
# The repository's own labels, which the skill uses; the 3 a first draft invented are in none of the files.
LABELS = ("enhancement", "help wanted", "question", "documentation")
INVENTED = ("working", "blocked on owner", "landed")


def git(tree: Path, *args: str) -> str:
    proc = subprocess.run([*GIT, "-C", str(tree), *args], capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def make_tree(base: Path, branch: str = BRANCH, roadmap: bool = True) -> Path:
    tree = base / "tree"
    (tree / "ee-agent-kit").mkdir(parents=True)
    git(tree, "init", "-q", "-b", branch)
    (tree / ".gitignore").write_text("build/\n", encoding="utf-8")
    if roadmap:
        (tree / "ee-agent-kit" / "ROADMAP.md").write_text(ROADMAP, encoding="utf-8")
    git(tree, "add", "-A")
    git(tree, "commit", "-q", "-m", SUBJECT)
    return tree


def put_record(tree: Path, **fields) -> None:
    record = {
        "gate": "make verify",
        "verdict": "GREEN",
        "step": "4/4 kit checks",
        "commit": git(tree, "rev-parse", "HEAD"),
        "branch": BRANCH,
        "dirty": False,
        "moved_to": None,
        "time": "2026-11-17T09:41:00Z",
    }
    record.update(fields)
    (tree / "build").mkdir(exist_ok=True)
    (tree / "build" / "verify.json").write_text(json.dumps(record), encoding="utf-8")


def now(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), "now", *argv], capture_output=True, text=True, check=False
    )


def without_updated(card: str) -> str:
    return card.split("## Updated")[0]


def headings(text: str) -> list[str]:
    return re.findall(r"^## (.+)$", text, re.M)


def test_the_card_holds_every_section_from_the_tree_and_the_options(tmp_path):
    tree = make_tree(tmp_path)
    put_record(tree)
    short = git(tree, "rev-parse", "--short", "HEAD")
    before = datetime.datetime.now(datetime.UTC).replace(second=0, microsecond=0)
    argv = (
        str(tree),
        "--item", "7",
        "--status", "In progress",
        "--doing", "Writing the tests",
        "--doing", "Reading verify.sh",
        "--left", "The skill",
        "--left", "The issue template",
    )  # fmt: skip
    proc = now(*argv)
    after = datetime.datetime.now(datetime.UTC)
    assert proc.returncode == 0, proc.stderr
    expected = (
        "**Status:** In progress\n\n"
        f"## Branch\n`{BRANCH}` at `{short}` {SUBJECT}\n\n"
        "## Doing now\n- Writing the tests\n- Reading verify.sh\n\n"
        f"## Health gate\nGREEN on `{short}` at 2026-11-17 09:41 UTC\n\n"
        "## Blocked on\nnothing\n\n"
        "## Left\n- The skill\n- The issue template\n\n"
    )
    assert without_updated(proc.stdout) == expected
    stamp = re.fullmatch(r"## Updated\n(\d{4}-\d\d-\d\d \d\d:\d\d) UTC\n", proc.stdout[len(expected) :])
    assert stamp, proc.stdout
    updated = datetime.datetime.strptime(stamp.group(1), "%Y-%m-%d %H:%M").replace(tzinfo=datetime.UTC)
    assert before <= updated <= after
    title = now(*argv, "--title")
    assert (title.returncode, title.stdout) == (0, f"{TITLE}\n")


def test_the_board_reads_the_status_of_the_card_the_command_prints(tmp_path):
    """tools/board.py's own reader takes the card `workcenter now` prints, and the issue's title the
    command prints is a work card's title to it: each of the board's 3 words comes back as it went in."""
    tree = make_tree(tmp_path)
    for status in ("Todo", "In progress", "Done"):
        proc = now(str(tree), "--item", "7", "--status", status)
        assert proc.returncode == 0, proc.stderr
        assert board.status_of(proc.stdout) == (status, "")
    title = now(str(tree), "--item", "7", "--status", "Todo", "--title").stdout.rstrip("\n")
    assert title.startswith(board.PREFIX)
    lower = now(str(tree), "--item", "7", "--status", "in progress")
    assert lower.stdout.startswith("**Status:** In progress\n")


def test_work_with_no_item_no_record_and_a_wait(tmp_path):
    """1 line of work is the title as given; no record is `none yet`; nothing doing or left is `nothing`.
    Work that waits on someone stays In progress and says so in its Blocked on line."""
    tree = make_tree(tmp_path, roadmap=False)
    short = git(tree, "rev-parse", "--short", "HEAD")
    argv = (str(tree), "--item", "Fix the stale label", "--status", "In progress", "--blocked", "the owner")
    proc = now(*argv)
    assert proc.returncode == 0, proc.stderr
    assert without_updated(proc.stdout) == (
        "**Status:** In progress\n\n"
        f"## Branch\n`{BRANCH}` at `{short}` {SUBJECT}\n\n"
        "## Doing now\nnothing\n\n"
        "## Health gate\nnone yet\n\n"
        "## Blocked on\nthe owner\n\n"
        "## Left\nnothing\n\n"
    )
    assert now(*argv, "--title").stdout == "Work card: Fix the stale label\n"


def test_the_gate_line_says_red_its_step_a_dirty_tree_and_an_older_commit(tmp_path):
    """A record of the commit before the last: `git rev-list --count <record>..HEAD` is 1."""
    tree = make_tree(tmp_path)
    first = git(tree, "rev-parse", "HEAD")
    first_short = git(tree, "rev-parse", "--short", "HEAD")
    put_record(tree, verdict="RED", step="3/4 tests", dirty=True)
    proc = now(str(tree), "--item", "7", "--status", "In progress")
    assert (
        f"## Health gate\nRED at 3/4 tests on `{first_short}` with uncommitted changes "
        "at 2026-11-17 09:41 UTC\n" in proc.stdout
    )
    (tree / "b.txt").write_text("b\n", encoding="utf-8")
    git(tree, "add", "b.txt")
    git(tree, "commit", "-q", "-m", "Add b")
    put_record(tree, commit=first)
    proc = now(str(tree), "--item", "7", "--status", "In progress")
    assert (
        f"## Health gate\nGREEN on `{first_short}` at 2026-11-17 09:41 UTC, 1 commit before the last\n"
        in proc.stdout
    )


def test_a_record_of_a_commit_the_branch_no_longer_holds(tmp_path):
    """After a rebase the record's commit is gone from the branch: its first 7 digits, and no count."""
    tree = make_tree(tmp_path)
    put_record(tree, commit="0123456789abcdef0123456789abcdef01234567")
    proc = now(str(tree), "--item", "7", "--status", "In progress")
    assert proc.returncode == 0, proc.stderr
    assert (
        "## Health gate\nGREEN on `0123456` at 2026-11-17 09:41 UTC, "
        "on a commit this branch no longer holds\n" in proc.stdout
    )
    put_record(tree, verdict="SKIPPED")
    proc = now(str(tree), "--item", "7", "--status", "In progress")
    assert proc.returncode == 1 and "holds the verdict 'SKIPPED'" in proc.stderr


def test_a_record_of_another_branch_is_none_yet(tmp_path):
    tree = make_tree(tmp_path)
    put_record(tree, branch="wip/other")
    proc = now(str(tree), "--item", "7", "--status", "In progress")
    assert "## Health gate\nnone yet\n" in proc.stdout


def test_json_holds_the_same_as_the_card(tmp_path):
    tree = make_tree(tmp_path)
    put_record(tree)
    head = git(tree, "rev-parse", "HEAD")
    short = git(tree, "rev-parse", "--short", "HEAD")
    argv = (str(tree), "--item", "7", "--status", "In progress", "--doing", "Tests", "--left", "Skill")
    data = json.loads(now(*argv, "--json").stdout)
    assert data["work"] == "Roadmap item 7: A card for each piece of work"
    assert data["title"] == TITLE
    assert data["item"] == "7"
    assert (data["branch"], data["commit"], data["short"], data["subject"]) == (BRANCH, head, short, SUBJECT)
    assert (data["status"], data["doing"], data["blocked_on"], data["left"]) == (
        "In progress",
        ["Tests"],
        "nothing",
        ["Skill"],
    )
    assert data["gate"]["verdict"] == "GREEN" and data["gate"]["commit"] == head
    assert data["gate"]["line"] == f"GREEN on `{short}` at 2026-11-17 09:41 UTC"
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d UTC", data["updated"])
    assert without_updated(data["card"]) == without_updated(now(*argv).stdout)
    assert data["card"].endswith(f"## Updated\n{data['updated']}\n")


def test_refusals_are_one_line_each(tmp_path):
    tree = make_tree(tmp_path)
    detached = make_tree(tmp_path / "d")
    git(detached, "checkout", "-q", "--detach")
    (tmp_path / "nowhere").mkdir()
    ok = ("--status", "In progress")
    cases = {
        "no status": ((str(tree), "--item", "7"), "--status is missing"),
        "unknown status": ((str(tree), "--item", "7", "--status", "paused"), "--status 'paused' is not 1 of"),
        **{
            f"the old word {word}": (
                (str(tree), "--item", "7", "--status", word),
                f"--status {word!r} is not 1 of Todo, In progress, Done",
            )
            for word in ("working", "blocked", "landed", "dropped")
        },
        "4 doing lines": (
            (str(tree), "--item", "7", *ok, *("--doing", "a") * 4),
            "4 --doing lines; the card holds at most 3",
        ),
        "no item": ((str(tree), *ok), "--item is missing"),
        "item not in the roadmap": (
            (str(tree), "--item", "99", *ok),
            "item 99 has no heading '### 99.' in ee-agent-kit/ROADMAP.md",
        ),
        "a line break": ((str(tree), "--item", "7", *ok, "--doing", "a\nb"), "1 line"),
        "a line break in --item": ((str(tree), "--item", "a\nb", *ok), "--item holds a line"),
        "a line break in --left": ((str(tree), "--item", "7", *ok, "--left", "a\rb"), "--left holds a line"),
        "a line break in --blocked": (
            (str(tree), "--item", "7", *ok, "--blocked", "a\nb"),
            "--blocked holds a line",
        ),
        "a heading in --item": ((str(tree), "--item", "## Health gate", *ok), "--item starts with '#'"),
        "a heading in --blocked": (
            (str(tree), "--item", "7", *ok, "--blocked", " ## Left"),
            "--blocked starts with '#'",
        ),
        "a Status line in --doing": (
            (str(tree), "--item", "7", *ok, "--doing", "**Status:** Done"),
            "--doing holds a **Status:** line",
        ),
        "not a git tree": ((str(tmp_path / "nowhere"), "--item", "x", *ok), "git"),
        "detached": ((str(detached), "--item", "x", *ok), "on no branch"),
    }
    for name, (argv, words) in cases.items():
        proc = now(*argv)
        assert proc.returncode == 1, name
        assert proc.stdout == "", name
        lines = proc.stderr.splitlines()
        assert len(lines) == 1 and lines[0].startswith("now: refused: ") and words in lines[0], (name, lines)


def make_status(base: Path) -> Path:
    """A checkout of the branch `status` that holds another branch's card and nothing else."""
    status = base / "status"
    (status / "now").mkdir(parents=True)
    git(status, "init", "-q", "-b", "status")
    (status / "now" / "wip-other.md").write_text("# Work card: Other\n\n## Branch\n`wip/other` at `x` y\n")
    git(status, "add", "-A")
    git(status, "commit", "-q", "-m", "now: wip/other In progress")
    return status


def files_of(folder: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(folder)): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(folder).parts
    }


def test_write_puts_exactly_one_file_in_the_status_checkout_and_runs_no_git(tmp_path):
    """With no issue there is no title: the file starts with it as its heading, then the card."""
    tree = make_tree(tmp_path)
    status = make_status(tmp_path)
    head_before = git(status, "rev-parse", "HEAD")
    before = files_of(status)
    argv = (str(tree), "--item", "7", "--status", "Done", "--doing", "Landed on main")
    card = now(*argv).stdout
    proc = now(*argv, "--write", str(status))
    assert proc.returncode == 0, proc.stderr
    after = files_of(status)
    changed = sorted(k for k in after.keys() | before.keys() if after.get(k) != before.get(k))
    assert changed == ["now/wip-item-7.md"]
    assert without_updated(after["now/wip-item-7.md"].decode()) == without_updated(f"# {TITLE}\n\n{card}")
    # it prints the commands and runs none of them: no new commit, the file not staged
    assert git(status, "rev-parse", "HEAD") == head_before
    assert git(status, "status", "--porcelain", "--untracked-files=all") == "?? now/wip-item-7.md"
    out = proc.stdout.splitlines()
    assert out[0] == f"wrote {status / 'now' / 'wip-item-7.md'}"
    assert out[1:] == [
        f"git -C {status} add now/wip-item-7.md",
        f"git -C {status} commit -m 'now: {BRANCH} Done'",
        f"git -C {status} pull --rebase origin status",
        f"git -C {status} push origin status",
    ]


def test_write_refuses_a_checkout_that_is_not_the_status_branch_alone(tmp_path):
    tree = make_tree(tmp_path)
    argv = (str(tree), "--item", "7", "--status", "In progress")
    other = make_tree(tmp_path / "o", branch="main")
    status = make_status(tmp_path)
    (status / "README.md").write_text("x\n", encoding="utf-8")
    git(status, "add", "README.md")
    git(status, "commit", "-q", "-m", "readme")
    taken = make_status(tmp_path / "t")
    (taken / "now" / "wip-item-7.md").write_text("# Work card: X\n\n## Branch\n`wip-item/7` at `x` y\n")
    cases = {
        "another branch": (other, "is on branch main, not status"),
        "a file outside now/": (status, "holds README.md outside now/"),
        "a card of another branch": (taken, "now/wip-item-7.md is the card of wip-item/7"),
    }
    for name, (checkout, words) in cases.items():
        before = files_of(checkout)
        proc = now(*argv, "--write", str(checkout))
        assert proc.returncode == 1, name
        lines = proc.stderr.splitlines()
        assert len(lines) == 1 and words in lines[0], (name, lines)
        assert files_of(checkout) == before, name


def record_cli(tree: Path, code: str, step: str, head: str, dirty: str) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(NOW_PY), "record", code, step, "--tree", str(tree), "--head", head]
    return subprocess.run([*argv, "--dirty", dirty], capture_output=True, text=True, check=False)


def test_the_gate_leaves_a_record_the_card_reads(tmp_path):
    """verify.sh calls `tools/now.py record <exit code> <step>` on exit; code 0 is GREEN, any other RED."""
    assert re.search(r"^trap .*tools/now\.py record ", (ROOT / "verify" / "verify.sh").read_text(), re.M)
    tree = make_tree(tmp_path)
    head = git(tree, "rev-parse", "HEAD")
    for code, verdict in (("0", "GREEN"), ("1", "RED"), ("2", "RED")):
        proc = record_cli(tree, code, "3/4 tests", head, "no")
        assert proc.returncode == 0, proc.stderr
        record = json.loads((tree / "build" / "verify.json").read_text())
        assert (record["verdict"], record["step"], record["commit"]) == (verdict, "3/4 tests", head)
        assert (record["branch"], record["dirty"], record["gate"]) == (BRANCH, False, "make verify")
        assert record["moved_to"] is None
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", record["time"])
    assert git(tree, "status", "--porcelain") == ""
    ignored = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "build/verify.json"], check=False)
    assert ignored.returncode == 0, "build/verify.json is not ignored by git in this repository"


def test_the_issue_template_has_the_cards_status_line_and_sections(tmp_path):
    tree = make_tree(tmp_path)
    card = now(str(tree), "--item", "7", "--status", "Todo").stdout
    template = TEMPLATE.read_text(encoding="utf-8")
    assert headings(template) == headings(card)
    assert headings(card) == ["Branch", "Doing now", "Health gate", "Blocked on", "Left", "Updated"]
    body = template.split("\n---\n", 1)[1]
    assert board.status_of(body) == ("Todo", "")
    assert re.search(r'^title: "Work card: ', template, re.M)
    assert re.search(r"^labels: enhancement$", template, re.M)


def test_the_skill_names_the_repositorys_own_labels_and_no_invented_one():
    """No new labels: a work card is `enhancement`, `help wanted` when it needs something from outside,
    `question` when it waits for the owner's decision, `documentation` for a document-only follow-up.
    The 3 labels a first draft invented are in no file, and the stale run spares no card for them."""
    skill = SKILL.read_text(encoding="utf-8")
    assert [x for x in LABELS if f"`{x}`" not in skill] == []
    for path in (SKILL, TEMPLATE, STALE):
        text = path.read_text(encoding="utf-8")
        named = [
            x
            for x in INVENTED
            if re.search(rf"[`'\"]{re.escape(x)}[`'\"]|label[^\n]*[ ,:'\"]{re.escape(x)}\b", text, re.I)
        ]
        assert named == [], path
    exempt = re.search(r"exempt-issue-labels: '([^']*)'", STALE.read_text(encoding="utf-8")).group(1)
    assert exempt.split(",") == ["blocked", "security", "accepted"]


def gate_lines() -> str:
    """verify.sh's own lines from `STEP=` up to its first step: what it notes at the start, and its trap."""
    text = (ROOT / "verify" / "verify.sh").read_text(encoding="utf-8")
    return text[text.index('STEP="0/4 start"') : text.index('step "1/4 lint"')]


def test_the_record_names_the_commit_the_gate_started_on(tmp_path):
    """The gate starts on commit A; during step 3/4 commit B lands; it exits 0. The record holds A, not
    B, and that the branch moved to B. The card: GREEN on `A` at 2026-11-17 09:41 UTC, the branch moved
    to `B` during the run, 1 commit before the last (`git rev-list --count A..B` is 1)."""
    tree = make_tree(tmp_path)
    (tree / "tools").mkdir()
    (tree / "tools" / "now.py").write_text(NOW_PY.read_text(encoding="utf-8"), encoding="utf-8")
    git(tree, "add", "tools/now.py")
    git(tree, "commit", "-q", "-m", "A")
    a, a_short = git(tree, "rev-parse", "HEAD"), git(tree, "rev-parse", "--short", "HEAD")
    gate = (
        f"set -euo pipefail\ncd {shlex.quote(str(tree))}\n{gate_lines()}"
        f'step "3/4 tests"\n{shlex.join(GIT)} commit -q --allow-empty -m B\n'
    )
    proc = subprocess.run(["bash", "-c", gate], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    b, b_short = git(tree, "rev-parse", "HEAD"), git(tree, "rev-parse", "--short", "HEAD")
    record = json.loads((tree / "build" / "verify.json").read_text(encoding="utf-8"))
    assert (record["verdict"], record["step"], record["commit"]) == ("GREEN", "3/4 tests", a)
    assert (record["moved_to"], record["dirty"]) == (b, False)
    put_record(tree, commit=a, moved_to=b)
    proc = now(str(tree), "--item", "7", "--status", "In progress")
    assert (
        f"## Health gate\nGREEN on `{a_short}` at 2026-11-17 09:41 UTC, the branch moved to `{b_short}` "
        "during the run, 1 commit before the last\n" in proc.stdout
    )


def test_the_record_counts_untracked_and_changed_files_as_uncommitted(tmp_path):
    """dirty is the tree's state at the start (--dirty) or at the end. Clean and `no`: false. Clean and
    `yes`: true. An untracked file, which pytest and ruff read: true. A changed tracked file: true."""
    tree = make_tree(tmp_path)
    head = git(tree, "rev-parse", "HEAD")

    def dirty(flag: str) -> bool:
        proc = record_cli(tree, "0", "4/4 kit checks", head, flag)
        assert proc.returncode == 0, proc.stderr
        return json.loads((tree / "build" / "verify.json").read_text(encoding="utf-8"))["dirty"]

    assert (dirty("no"), dirty("yes")) == (False, True)
    (tree / "test_new.py").write_text("def test_new():\n    pass\n", encoding="utf-8")
    assert dirty("no") is True
    (tree / "test_new.py").unlink()
    (tree / ".gitignore").write_text("build/\nx/\n", encoding="utf-8")
    assert dirty("no") is True


def test_a_record_two_commits_back_and_three_doing_lines(tmp_path):
    """2 commits after the record's: `git rev-list --count <record>..HEAD` is 2, so `2 commits`. 3
    --doing lines is the most a card holds, and is printed."""
    tree = make_tree(tmp_path)
    first, first_short = git(tree, "rev-parse", "HEAD"), git(tree, "rev-parse", "--short", "HEAD")
    for name in ("b", "c"):
        git(tree, "commit", "-q", "--allow-empty", "-m", f"Add {name}")
    put_record(tree, commit=first)
    proc = now(str(tree), "--item", "7", "--status", "In progress", *("--doing", "a") * 3)
    assert proc.returncode == 0, proc.stderr
    assert "## Doing now\n- a\n- a\n- a\n" in proc.stdout
    assert (
        f"## Health gate\nGREEN on `{first_short}` at 2026-11-17 09:41 UTC, 2 commits before the last\n"
        in proc.stdout
    )


def test_a_record_verify_sh_does_not_write_is_refused_in_one_line(tmp_path):
    tree = make_tree(tmp_path)
    good = {
        "gate": "make verify",
        "verdict": "GREEN",
        "step": "4/4 kit checks",
        "commit": git(tree, "rev-parse", "HEAD"),
        "branch": BRANCH,
        "dirty": False,
        "moved_to": None,
        "time": "2026-11-17T09:41:00Z",
    }
    cases = {
        "bad JSON": "{",
        "a list": "[]",
        "empty": "",
        "no verdict": json.dumps({k: v for k, v in good.items() if k != "verdict"}),
        "no moved_to": json.dumps({k: v for k, v in good.items() if k != "moved_to"}),
        "a null commit": json.dumps({**good, "commit": None}),
        "a short commit": json.dumps({**good, "commit": good["commit"][:7]}),
        "dirty as a string": json.dumps({**good, "dirty": "false"}),
        "a step that is no string": json.dumps({**good, "step": 3}),
        "moved_to no commit": json.dumps({**good, "moved_to": "x"}),
        "a time with no zone": json.dumps({**good, "time": "2026-11-17 09:41"}),
    }
    (tree / "build").mkdir()
    for name, text in cases.items():
        (tree / "build" / "verify.json").write_text(text, encoding="utf-8")
        proc = now(str(tree), "--item", "7", "--status", "In progress")
        lines = proc.stderr.splitlines()
        assert proc.returncode == 1 and proc.stdout == "", name
        assert len(lines) == 1 and "is not a gate record verify.sh writes" in lines[0], (name, lines)


def test_a_card_that_names_an_assistant_a_model_or_a_session_is_refused(tmp_path):
    """The card names no assistant, no model and no session (the skill; CLAUDE.md's rule for what the
    repository publishes). A file's name, `CLAUDE.md`, is no such name."""
    tree = make_tree(tmp_path)
    named = make_tree(tmp_path / "n", branch="claude/fix-gate-01UhK1vD")
    base = (str(tree), "--item", "7", "--status", "In progress")
    cases = {
        "--item": ((str(tree), "--item", "Claude Opus 5.5 work", "--status", "In progress"), "--item"),
        "--doing": ((*base, "--doing", "session https://claude.ai/code/session_01UhK1vD"), "--doing"),
        "a session id": ((*base, "--doing", "Resume session_01UhK1vD"), "--doing"),
        "--left": ((*base, "--left", "Ask Sonnet to review"), "--left"),
        "--blocked": ((*base, "--blocked", "Anthropic"), "--blocked"),
        "the branch": ((str(named), "--item", "x", "--status", "In progress"), "the branch claude/fix-gate"),
    }
    for name, (argv, words) in cases.items():
        proc = now(*argv)
        lines = proc.stderr.splitlines()
        assert proc.returncode == 1 and proc.stdout == "", name
        assert len(lines) == 1 and "names an assistant, a model or a session" in lines[0], (name, lines)
        assert words in lines[0], (name, lines)
    proc = now(*base, "--doing", "Editing CLAUDE.md and AGENTS.md")
    assert proc.returncode == 0, proc.stderr


def test_the_skills_gh_lines_give_gh_no_card_when_the_command_refuses(tmp_path):
    """The skill's lines write the card to build/now.md and run gh only when `workcenter now` exits 0:
    a refusal leaves the issue's body as it was. No line pipes the command into another."""
    skill = SKILL.read_text(encoding="utf-8")
    assert not re.search(r"workcenter now[^`\n]*\|", skill)
    lines = re.findall(
        r"`(mkdir -p build && workcenter now \. [^`]*> build/now\.md && gh issue [^`]*)`", skill
    )
    assert [("create" in x, "edit N" in x) for x in lines] == [(True, False), (False, True)]
    tree = make_tree(tmp_path)
    stubs = tmp_path / "bin"
    stubs.mkdir()
    called = tmp_path / "gh-called"
    (stubs / "workcenter").write_text(f'#!/bin/sh\nexec {sys.executable} {shlex.quote(str(CLI))} "$@"\n')
    (stubs / "gh").write_text(f'#!/bin/sh\nprintf "%s|" "$@" > {shlex.quote(str(called))}\n')
    for stub in stubs.iterdir():
        stub.chmod(0o755)
    env = {**os.environ, "PATH": f"{stubs}{os.pathsep}{os.environ['PATH']}"}
    for line in lines:
        line = line.replace("<branch>", BRANCH)
        for options, ok in (("--item 7 --status paused", False), ("--item 7 --status 'In progress'", True)):
            called.unlink(missing_ok=True)
            run = line.replace("<the same options>", options).replace("<options>", options)
            proc = subprocess.run(["bash", "-c", run], cwd=tree, env=env, capture_output=True, text=True)
            assert (proc.returncode == 0, called.exists()) == (ok, ok), (run, proc.stderr)
        # gh's short flags (-t, -l, -F): a long flag after `workcenter now` in 1 line reads, to
        # tests/test_docs.py and to a reader, as a flag of `workcenter now`.
        given = {
            f for part in line.split("workcenter now")[1:] for f in re.findall(r"(?<![\w-])--[a-z-]+", part)
        }
        assert given <= {"--item", "--status", "--doing", "--blocked", "--left", "--title", "--write"}, line
        args = called.read_text().rstrip("|").split("|")
        assert args[-2:] == ["-F", "build/now.md"]
        if "create" in line:
            assert args[args.index("-t") + 1] == TITLE
            assert args[args.index("-l") + 1] == "enhancement"
        card = (tree / "build" / "now.md").read_text(encoding="utf-8")
        assert card.startswith("**Status:** In progress\n\n## Branch\n")


def test_the_printed_git_commands_run_with_a_space_in_the_path_and_a_quote_in_the_branch(tmp_path):
    """A checkout `my status` and a branch `wip/it's`: the add and commit lines run in bash as printed,
    and the commit holds now/wip-it's.md with the message `now: wip/it's In progress`."""
    tree = make_tree(tmp_path, branch="wip/it's")
    status = tmp_path / "my status"
    status.mkdir()
    git(status, "init", "-q", "-b", "status")
    git(status, "commit", "-q", "--allow-empty", "-m", "init")
    proc = now(str(tree), "--item", "7", "--status", "In progress", "--write", str(status))
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.splitlines()
    env = {
        **os.environ,
        **{f"GIT_{who}_{what}": value for who in ("AUTHOR", "COMMITTER") for what, value in
           (("NAME", "Test"), ("EMAIL", "test@example.invalid"))},
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "commit.gpgsign",
        "GIT_CONFIG_VALUE_0": "false",
    }  # fmt: skip
    for line in out[1:3]:
        run = subprocess.run(["bash", "-c", line], env=env, capture_output=True, text=True, check=False)
        assert run.returncode == 0, (line, run.stderr)
    assert git(status, "log", "-1", "--format=%s") == "now: wip/it's In progress"
    assert git(status, "ls-tree", "-r", "--name-only", "HEAD") == "now/wip-it's.md"
    assert [shlex.split(x) for x in out[3:]] == [
        ["git", "-C", str(status), "pull", "--rebase", "origin", "status"],
        ["git", "-C", str(status), "push", "origin", "status"],
    ]
