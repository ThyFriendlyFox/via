"""`workcenter now`: the card of 1 piece of work in progress, built from a scratch git tree.

Each tree here is made in a temporary folder: a branch with a known name, 1 commit with a known subject,
a roadmap with a known heading and, where a test needs one, a gate record that `make verify` leaves in
`build/verify.json`. The card's text is written out by hand in each test, from those inputs:

    branch     wip/item-7, its commit's subject `Add the first file`
    roadmap    `### 7. A card for each piece of work` -> `Roadmap item 7: A card for each piece of work`
    record     GREEN at 4/4 kit checks on the tree's HEAD at 2026-11-17T09:41:00Z
               -> GREEN on `<short HEAD>` at 2026-11-17 09:41 UTC

The short hash is git's own (`git rev-parse --short HEAD`): the card prints what git prints.
"""

from __future__ import annotations

import datetime
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
NOW_PY = ROOT / "tools" / "now.py"
TEMPLATE = ROOT / ".github" / "ISSUE_TEMPLATE" / "now.md"
SKILL = ROOT / ".claude" / "skills" / "now" / "SKILL.md"

BRANCH = "wip/item-7"
SUBJECT = "Add the first file"
ROADMAP = "# Roadmap\n\n## Feature Queue\n\n### 7. A card for each piece of work\n- **Promise:** x\n"
GIT = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false"]


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
    proc = now(
        str(tree),
        "--item", "7",
        "--state", "working",
        "--doing", "Writing the tests",
        "--doing", "Reading verify.sh",
        "--left", "The skill",
        "--left", "The issue template",
    )  # fmt: skip
    after = datetime.datetime.now(datetime.UTC)
    assert proc.returncode == 0, proc.stderr
    expected = (
        "## Work\nRoadmap item 7: A card for each piece of work\n\n"
        f"## Branch\n`{BRANCH}` at `{short}` {SUBJECT}\n\n"
        "## State\nworking\n\n"
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


def test_work_with_no_item_no_record_and_a_block(tmp_path):
    """1 line of work stands as given; no record is `none yet`; nothing doing or left is `nothing`."""
    tree = make_tree(tmp_path, roadmap=False)
    short = git(tree, "rev-parse", "--short", "HEAD")
    proc = now(str(tree), "--item", "Fix the stale label", "--state", "blocked", "--blocked", "the owner")
    assert proc.returncode == 0, proc.stderr
    assert without_updated(proc.stdout) == (
        "## Work\nFix the stale label\n\n"
        f"## Branch\n`{BRANCH}` at `{short}` {SUBJECT}\n\n"
        "## State\nblocked\n\n"
        "## Doing now\nnothing\n\n"
        "## Health gate\nnone yet\n\n"
        "## Blocked on\nthe owner\n\n"
        "## Left\nnothing\n\n"
    )


def test_the_gate_line_says_red_its_step_a_dirty_tree_and_an_older_commit(tmp_path):
    """A record of the commit before the last: `git rev-list --count <record>..HEAD` is 1."""
    tree = make_tree(tmp_path)
    first = git(tree, "rev-parse", "HEAD")
    first_short = git(tree, "rev-parse", "--short", "HEAD")
    put_record(tree, verdict="RED", step="3/4 tests", dirty=True)
    proc = now(str(tree), "--item", "7", "--state", "working")
    assert (
        f"## Health gate\nRED at 3/4 tests on `{first_short}` with uncommitted changes "
        "at 2026-11-17 09:41 UTC\n" in proc.stdout
    )
    (tree / "b.txt").write_text("b\n", encoding="utf-8")
    git(tree, "add", "b.txt")
    git(tree, "commit", "-q", "-m", "Add b")
    put_record(tree, commit=first)
    proc = now(str(tree), "--item", "7", "--state", "working")
    assert (
        f"## Health gate\nGREEN on `{first_short}` at 2026-11-17 09:41 UTC, 1 commit before the last\n"
        in proc.stdout
    )


def test_a_record_of_a_commit_the_branch_no_longer_holds(tmp_path):
    """After a rebase the record's commit is gone from the branch: its first 7 digits, and no count."""
    tree = make_tree(tmp_path)
    put_record(tree, commit="0123456789abcdef0123456789abcdef01234567")
    proc = now(str(tree), "--item", "7", "--state", "working")
    assert proc.returncode == 0, proc.stderr
    assert (
        "## Health gate\nGREEN on `0123456` at 2026-11-17 09:41 UTC, "
        "on a commit this branch no longer holds\n" in proc.stdout
    )
    put_record(tree, verdict="SKIPPED")
    proc = now(str(tree), "--item", "7", "--state", "working")
    assert proc.returncode == 1 and "holds the verdict 'SKIPPED'" in proc.stderr


def test_a_record_of_another_branch_is_none_yet(tmp_path):
    tree = make_tree(tmp_path)
    put_record(tree, branch="wip/other")
    proc = now(str(tree), "--item", "7", "--state", "working")
    assert "## Health gate\nnone yet\n" in proc.stdout


def test_json_holds_the_same_as_the_card(tmp_path):
    tree = make_tree(tmp_path)
    put_record(tree)
    head = git(tree, "rev-parse", "HEAD")
    short = git(tree, "rev-parse", "--short", "HEAD")
    argv = (str(tree), "--item", "7", "--state", "working", "--doing", "Tests", "--left", "Skill")
    data = json.loads(now(*argv, "--json").stdout)
    assert data["work"] == "Roadmap item 7: A card for each piece of work"
    assert data["item"] == "7"
    assert (data["branch"], data["commit"], data["short"], data["subject"]) == (BRANCH, head, short, SUBJECT)
    assert (data["state"], data["doing"], data["blocked_on"], data["left"]) == (
        "working",
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
    cases = {
        "no state": ((str(tree), "--item", "7"), "--state is missing"),
        "unknown state": ((str(tree), "--item", "7", "--state", "paused"), "--state 'paused' is not 1 of"),
        "4 doing lines": (
            (str(tree), "--item", "7", "--state", "working", *("--doing", "a") * 4),
            "4 --doing lines; the card holds at most 3",
        ),
        "blocked without --blocked": ((str(tree), "--item", "7", "--state", "blocked"), "--blocked"),
        "no item": ((str(tree), "--state", "working"), "--item is missing"),
        "item not in the roadmap": (
            (str(tree), "--item", "99", "--state", "working"),
            "item 99 has no heading '### 99.' in ee-agent-kit/ROADMAP.md",
        ),
        "a line break": ((str(tree), "--item", "7", "--state", "working", "--doing", "a\nb"), "1 line"),
        "not a git tree": ((str(tmp_path / "nowhere"), "--item", "x", "--state", "working"), "git"),
        "detached": ((str(detached), "--item", "x", "--state", "working"), "on no branch"),
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
    (status / "now" / "wip-other.md").write_text("## Work\nOther\n\n## Branch\n`wip/other` at `x` y\n")
    git(status, "add", "-A")
    git(status, "commit", "-q", "-m", "now: wip/other working")
    return status


def files_of(folder: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(folder)): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file() and ".git" not in p.relative_to(folder).parts
    }


def test_write_puts_exactly_one_file_in_the_status_checkout_and_runs_no_git(tmp_path):
    tree = make_tree(tmp_path)
    status = make_status(tmp_path)
    head_before = git(status, "rev-parse", "HEAD")
    before = files_of(status)
    argv = (str(tree), "--item", "7", "--state", "landed", "--doing", "Landed on main")
    card = now(*argv).stdout
    proc = now(*argv, "--write", str(status))
    assert proc.returncode == 0, proc.stderr
    after = files_of(status)
    changed = sorted(k for k in after.keys() | before.keys() if after.get(k) != before.get(k))
    assert changed == ["now/wip-item-7.md"]
    assert without_updated(after["now/wip-item-7.md"].decode()) == without_updated(card)
    # it prints the commands and runs none of them: no new commit, the file not staged
    assert git(status, "rev-parse", "HEAD") == head_before
    assert git(status, "status", "--porcelain", "--untracked-files=all") == "?? now/wip-item-7.md"
    out = proc.stdout.splitlines()
    assert out[0] == f"wrote {status / 'now' / 'wip-item-7.md'}"
    assert out[1:] == [
        f"git -C {status} add now/wip-item-7.md",
        f"git -C {status} commit -m 'now: {BRANCH} landed'",
        f"git -C {status} pull --rebase origin status",
        f"git -C {status} push origin status",
    ]


def test_write_refuses_a_checkout_that_is_not_the_status_branch_alone(tmp_path):
    tree = make_tree(tmp_path)
    argv = (str(tree), "--item", "7", "--state", "working")
    other = make_tree(tmp_path / "o", branch="main")
    status = make_status(tmp_path)
    (status / "README.md").write_text("x\n", encoding="utf-8")
    git(status, "add", "README.md")
    git(status, "commit", "-q", "-m", "readme")
    taken = make_status(tmp_path / "t")
    (taken / "now" / "wip-item-7.md").write_text("## Work\nX\n\n## Branch\n`wip-item/7` at `x` y\n")
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


def test_the_gate_leaves_a_record_the_card_reads(tmp_path):
    """verify.sh calls `tools/now.py record <exit code> <step>` on exit; code 0 is GREEN, any other RED."""
    assert re.search(r"^trap .*tools/now\.py record ", (ROOT / "verify" / "verify.sh").read_text(), re.M)
    tree = make_tree(tmp_path)
    head = git(tree, "rev-parse", "HEAD")
    for code, verdict in (("0", "GREEN"), ("1", "RED"), ("2", "RED")):
        proc = subprocess.run(
            [sys.executable, str(NOW_PY), "record", code, "3/4 tests", "--tree", str(tree)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        record = json.loads((tree / "build" / "verify.json").read_text())
        assert (record["verdict"], record["step"], record["commit"]) == (verdict, "3/4 tests", head)
        assert (record["branch"], record["dirty"], record["gate"]) == (BRANCH, False, "make verify")
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", record["time"])
    assert git(tree, "status", "--porcelain") == ""
    ignored = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "build/verify.json"], check=False)
    assert ignored.returncode == 0, "build/verify.json is not ignored by git in this repository"


def test_the_issue_template_has_the_cards_sections(tmp_path):
    tree = make_tree(tmp_path)
    card = now(str(tree), "--item", "7", "--state", "working").stdout
    template = TEMPLATE.read_text(encoding="utf-8")
    assert headings(template) == headings(card)
    assert headings(card) == [
        "Work",
        "Branch",
        "State",
        "Doing now",
        "Health gate",
        "Blocked on",
        "Left",
        "Updated",
    ]
    assert re.search(r"^labels: working$", template, re.M)


def test_the_skill_names_the_labels_and_the_stale_run_spares_open_cards():
    skill = SKILL.read_text(encoding="utf-8")
    labels = ("working", "blocked on owner", "landed")
    assert [x for x in labels if f"`{x}`" not in skill] == []
    stale = (ROOT / ".github" / "workflows" / "stale.yml").read_text(encoding="utf-8")
    exempt = re.search(r"exempt-issue-labels: '([^']*)'", stale).group(1).split(",")
    assert {"working", "blocked on owner"} <= set(exempt)
