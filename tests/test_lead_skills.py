"""The skills for leading work name only what exists, and name no assistant or model as required.

1 test per skill: `now` (work cards and the project board), `lead`, `land` and `user-round`. Every
repository path a skill writes as code exists in the repository, every `workcenter <command>` is a
command of the CLI, every `make <target>` a target of the Makefile, and every process it cites is in
PROCESSES.md. A path that holds a placeholder (`<branch>`) or a pattern (`*`) is the reader's to
fill, and is passed over. A kit skill has the same bytes in ee-agent-kit/skills/ as in .claude/skills/.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
SKILLS = ("now", "lead", "land", "user-round")
KIT_SKILLS = ("lead", "land", "user-round")
# The names CLAUDE.md's rule keeps out of what the repository publishes, as tools/now.py reads them.
# The file CLAUDE.md and the folder .claude/ are names of files, not of an assistant.
NAMED = re.compile(
    r"\b(?:(?<!\.)claude(?!\.md\b)|anthropic|opus|sonnet|haiku|gpt-?\d|gemini|copilot)|session_[0-9a-z]{6,}",
    re.I,
)


def tracked_tops() -> set[str]:
    listing = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True)
    return {line.split("/")[0] for line in listing.stdout.split()}


def commands() -> set[str]:
    proc = subprocess.run([sys.executable, str(CLI), "--help"], capture_output=True, text=True, check=True)
    return set(re.search(r"\{([a-z,]+)\}", proc.stdout).group(1).split(","))


def code_spans(text: str) -> list[str]:
    """Each inline code span and each line of a fenced block."""
    fences = re.findall(r"^```.*?^```", text, re.S | re.M)
    spans = [line for block in fences for line in block.splitlines()[1:-1]]
    spans += re.findall(r"`([^`\n]+)`", re.sub(r"^```.*?^```", "", text, flags=re.S | re.M))
    return spans


def named(text: str) -> dict[str, set[str]]:
    """The repository paths, `workcenter` commands and `make` targets a skill writes as code."""
    tops = tracked_tops()
    paths, cmds, targets = set(), set(), set()
    for span in code_spans(text):
        for word in span.split():
            word = word.strip("\"'(),;:")
            if "/" in word and word.split("/")[0] in tops and not re.search(r"[<>*{}$]", word):
                paths.add(word.split(":")[0].rstrip("."))
        cmds.update(re.findall(r"\bworkcenter ([a-z][a-z-]*)", span))
        targets.update(re.findall(r"\bmake (?:-C \S+ )?([a-z][a-z-]*)", span))
    return {"paths": paths, "commands": cmds, "targets": targets}


@pytest.mark.parametrize("name", SKILLS)
def test_every_path_command_and_target_the_skill_names_exists(name):
    skill = ROOT / ".claude" / "skills" / name / "SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert text.startswith("---\nname: ") and "\ndescription: " in text.split("\n---\n")[0]
    found = named(text)
    assert found["paths"], f"{name}: the skill names no repository path; the pattern is off"
    assert sorted(p for p in found["paths"] if not (ROOT / p).exists()) == []
    assert sorted(found["commands"] - commands()) == []
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    phony = set(re.search(r"^\.PHONY: (.+)$", makefile, re.M).group(1).split())
    assert sorted(found["targets"] - phony) == []
    processes_md = (ROOT / "ee-agent-kit" / "PROCESSES.md").read_text(encoding="utf-8")
    processes = {int(n) for n in re.findall(r"^## P(\d+) ", processes_md, re.M)}
    assert len(processes) >= 35
    cited = {int(n) for n in re.findall(r"\bP(\d{1,2})\b", text)}
    assert sorted(cited - processes) == []
    assert NAMED.findall(text) == []
    if name in KIT_SKILLS:
        kit = ROOT / "ee-agent-kit" / "skills" / name / "SKILL.md"
        assert kit.read_bytes() == skill.read_bytes(), f"{kit} drifted from {skill}"


CARD_LABELS = {"enhancement", "help wanted", "question", "documentation"}


def test_the_card_skill_keeps_the_owners_decision():
    """The owner's decision of 2026-11-17: a card carries `**Status:**` with the board's own 3 words and
    no other state word, and uses 4 of the labels the repository has (GitHub's label list of the
    repository, read on 2026-11-17, held them all) and makes none. The title's prefix and the 3 words
    are the ones tools/board.py acts on."""
    text = (ROOT / ".claude" / "skills" / "now" / "SKILL.md").read_text(encoding="utf-8")
    board = (ROOT / "tools" / "board.py").read_text(encoding="utf-8")
    prefix = re.search(r'^PREFIX = "([^"]+)"', board, re.M).group(1)
    words = re.findall(r'"([^"]+)"', re.search(r"^WORDS = \(([^)]*)\)", board, re.M).group(1))
    assert prefix == "Work card:" and words == ["Todo", "In progress", "Done"]
    # The issue's title is the one `workcenter now --title` prints, `Work card: <the work>`.
    assert f"`{prefix} <the work>`" in text
    assert '-t "$(workcenter now . <the same options> --title)"' in text
    assert [w for w in words if f"`**Status:** {w}`" not in text] == []
    assert re.findall(r"--(?:state|status) (?:working|blocked|landed|dropped)\b", text) == []
    given = [a or b for a, b in re.findall(r'--(?:add-|remove-)?label (?:"([^"]+)"|([a-z]+))', text)]
    assert given and sorted(set(given) - CARD_LABELS) == []
    assert "gh label create" not in text
    for name in ("BOARD_TOKEN", "BOARD_URL", ".github/workflows/board.yml", "tests/board/README.md"):
        assert name in text, name


@pytest.mark.parametrize("name", SKILLS)
def test_every_status_a_skill_gives_workcenter_now_is_1_it_takes(name, tmp_path):
    """Each `--status` value a skill writes is run through `workcenter now` on a scratch tree: it prints
    a card, with the board's word on its **Status:** line. The `now` skill writes all 3 words."""
    text = (ROOT / ".claude" / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
    # gh's own `--state open` is gh's and no flag of `workcenter now`; `--status` is the command's.
    lines = [span for span in code_spans(text) if "--status" in span and not span.startswith("gh ")]
    states = {a or b for line in lines for a, b in re.findall(r'--status (?:"([^"]+)"|([A-Za-z]+))', line)}
    if name == "now":
        assert states == {"Todo", "In progress", "Done"}
    tree = tmp_path / "tree"
    tree.mkdir()
    identity = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false"]
    for args in (["init", "-q", "-b", "wip/x"], ["commit", "-q", "--allow-empty", "-m", "Start"]):
        subprocess.run(["git", "-C", str(tree), *identity, *args], check=True, capture_output=True)
    for state in sorted(states):
        argv = [sys.executable, str(CLI), "now", str(tree), "--item", "A card", "--status", state]
        proc = subprocess.run(argv, capture_output=True, text=True)
        assert proc.returncode == 0, (name, state, proc.stderr)
        assert f"**Status:** {state}" in proc.stdout.splitlines(), (name, state)


def test_the_pattern_finds_what_a_skill_names_and_passes_over_placeholders():
    """The reader of the test above, on a made-up skill: 2 paths, 1 command, 1 target; the path with
    `<branch>` and the one under no tracked folder are passed over."""
    text = (
        "Run `python3 ee-agent-kit/lead/landed.py <state> <journal>`.\n"
        "```sh\nworkcenter now . --item 7\nmake -C /x verify\n```\n"
        "Read `tests/test_lead.py`, `build/now.md` and `wt/<branch>/tools/x.py`.\n"
    )
    assert named(text) == {
        "paths": {"ee-agent-kit/lead/landed.py", "tests/test_lead.py"},
        "commands": {"now"},
        "targets": {"verify"},
    }
