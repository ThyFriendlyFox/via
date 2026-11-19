"""Where the health gate runs: 1 rule, the same in every document (the owner's decision of 2026-11-19).

`main` takes no commit that its gate did not pass on that exact commit: `make verify` for a change
`make scope` calls `full`, `make verify-site` for one it calls `fast`. Where CI runs, that is the
`verdict` check; a pull request merges only when `verdict` is green on its head and the branch holds
`main`'s tip, by `gh pr merge <number> --merge --match-head-commit <sha>`. A push to a work branch
needs the fast checks only: `make check`. The rule stands in many documents, and before this change
they said "`make verify` green before every push". These tests hold the documents to the new rule:
the old sentences are gone from every document that is not history, the documents a reader meets
first name the same commands, and `make check` is what they say it is. They read files and run
`make -n` and the kit checks on a small copy; nothing here starts an engine.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The old rule's sentences, as they stood on 2026-11-19, each in the place a reader met it.
OLD = (
    "`make verify` green before every push",  # AGENTS.md
    "full health gate — must pass before any push",  # AGENTS.md's commands
    "`make verify` must be green before any push",  # README.md
    "`make verify` passes locally",  # the pull request template
    "`main` green: `make verify`.",  # RELEASING.md step 1
    "Run `make verify` — the baseline must be green",  # WEEKLY.md
    "run `make verify` on it before its push",  # PROCESSES.md P14 step 2
    "the gate runs on it before any push",  # the land skill
    "Run `make verify` on the exact trees that will be pushed.",  # PROCESSES.md P33
    "push only on its verdict",  # the land skill's gate step
    "`main` takes no commit that `make verify` did not pass on that exact commit",  # README.md, CI.md
)

# The old rule in other words: `make verify` and "before <a> push" in 1 clause. Nothing between them
# ends a clause, a list item or a code comment. Allowed only where the text speaks of a machine with
# no CI, where the old rule still holds.
PARAPHRASE = re.compile(
    r"make verify(?!-)[^.;:#\-\[]{0,80}?before (?:each|every|any|a|the|its) push"
    r"|before (?:each|every|any|a|the|its) push[^.;:#\-\[]{0,80}?make verify(?!-)",
    re.I,
)

# The rule's headline in its 1 wording: what the gate is for each scope.
RULE = "`make verify` for a change `make scope` calls `full`, and `make verify-site` for one it calls `fast`"

# What lets a pull request merge: the head holds `main`'s tip, and the merge names the head.
MERGE = ("`main`'s tip", "--match-head-commit")

# History keeps its words: the dated logs, and the roadmap, whose entries keep the words of the day
# they were entered and are written by the trunk's keeper from each change's docs file.
HISTORY = {
    "ee-agent-kit/DEVLOG.md",
    "ee-agent-kit/MISTAKES.md",
    "ee-agent-kit/CHANGELOG.md",
    "ee-agent-kit/ROADMAP.md",
}

# What the fast checks are, as `make check` runs them: lint, then the kit's own tests.
KIT_TESTS = (
    "tests/test_gate_rule.py",
    "tests/test_lead_skills.py",
    "tests/test_docs.py::test_no_commit_names_an_assistant_as_its_author",
)

# The documents a reader meets first, and the words each must hold.
FIRST = {
    "ee-agent-kit/AGENTS.md": (
        "`make check`",
        "`verdict`",
        "`make verify`",
        "`make verify-site`",
        RULE,
        *MERGE,
    ),
    "README.md": ("`make check`", "`verdict`", "`make verify`", "`make verify-site`", RULE, *MERGE),
    ".github/PULL_REQUEST_TEMPLATE.md": (
        "`make check`",
        "`verdict`",
        "`make verify`",
        "`make verify-site`",
        *MERGE,
    ),
    "ee-agent-kit/CI.md#Where the health gate runs": (
        "`make check`",
        "`verdict`",
        "`make verify`",
        "`make verify-site`",
        "`workflow_dispatch`",
        RULE,
        *MERGE,
    ),
    "ee-agent-kit/PROCESSES.md#P14 — Closing out a change": ("`make check`", "`verdict`", "`make verify`"),
    "ee-agent-kit/VERIFICATION.md": ("`verdict`", RULE),
    "ee-agent-kit/RELEASING.md": ("`verdict`", "`full` job", "gh workflow run ci.yml --ref main"),
    "ee-agent-kit/WEEKLY.md": ("--commit $(git rev-parse origin/main)", "`verdict` job"),
    ".claude/skills/land/SKILL.md": (
        "`make check`",
        "`verdict`",
        "gh workflow run ci.yml",
        "--match-head-commit",
    ),
    ".claude/skills/lead/SKILL.md": ("`make check`", "`verdict`"),
    "ee-agent-kit/lead/README.md": ("`make check`", "`verdict`"),
}

# What `verify/verify.sh` reads in its kit checks: a copy of these is enough to run them.
KIT_FILES = (
    "verify/verify.sh",
    "CLAUDE.md",
    "AGENTS.md",
    "WORKCENTER.md",
    "ee-agent-kit/MISTAKES.md",
    "ee-agent-kit/PROCESSES.md",
    # The kit checks run `tools/ci/changes.py check` on the changelog and the change files.
    "tools/ci/changes.py",
    "ee-agent-kit/CHANGELOG.md",
)


def documents() -> list[str]:
    """Every document that may state the rule: the Markdown of the root, the kit, the skills, the
    GitHub folder, the tools' and the gate's READMEs, and the Makefile. Not examples/, site/, blog/ or
    third_party/: those are projects and pages, not the rules of work on this repository."""
    found = [*ROOT.glob("*.md"), ROOT / "Makefile"]
    for folder in ("ee-agent-kit", ".claude/skills", ".github", "tools", "verify"):
        found += (ROOT / folder).rglob("*.md")
    return sorted(str(p.relative_to(ROOT)) for p in found if p.is_file())


def section(rel: str) -> str:
    """A file's text, or with `#<heading>` the text of that `##` section alone."""
    path, _, heading = rel.partition("#")
    text = (ROOT / path).read_text(encoding="utf-8")
    if not heading:
        return text
    match = re.search(rf"^## {re.escape(heading)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match, f"{path} has no section '## {heading}'"
    return match.group(1)


def unwrapped(text: str) -> tuple[str, list[int]]:
    """The text with every run of spaces and line ends made 1 space, so a sentence wrapped over lines
    is found whole, and the line number of each of its words."""
    words, lines = [], []
    for number, line in enumerate(text.splitlines(), 1):
        for word in line.split():
            words.append(word)
            lines.append(number)
    return " ".join(words), lines


def line_of(flat: str, lines: list[int], at: int) -> int:
    """The line of the word that holds offset `at` of the unwrapped text."""
    return lines[flat.count(" ", 0, at)]


def old_rule_in(rel: str, text: str) -> list[str]:
    """Each place in 1 document that states the old rule, as `path:line: the words`; a line an old
    sentence names is not named again for its paraphrase."""
    flat, lines = unwrapped(text)
    found, named = [], set()
    for old in OLD:
        for m in re.finditer(re.escape(old), flat):
            named.add(line_of(flat, lines, m.start()))
            found.append(f"{rel}:{line_of(flat, lines, m.start())}: {old}")
    for m in PARAPHRASE.finditer(flat):
        line = line_of(flat, lines, m.start())
        if line not in named and "no CI" not in flat[max(0, m.start() - 200) : m.end()]:
            found.append(f"{rel}:{line}: {m.group(0)}")
    return found


def test_the_old_rule_is_found_at_its_line_and_in_other_words():
    """The scan names the line of an old sentence, finds the old rule said in other words, and lets a
    sentence about a machine with no CI stand."""
    text = (
        "# Title\n\nSome words.\nRun `make verify`\nbefore each push.\n\n"
        "Then\n`make verify` green before every push.\n"
    )
    assert old_rule_in("X.md", text) == [
        "X.md:8: `make verify` green before every push",
        "X.md:4: make verify` before each push",
    ]
    assert (
        old_rule_in("X.md", "Where there is no CI, run `make verify` on the machine before the push.") == []
    )
    assert old_rule_in("X.md", "- `make check` before each push\n- `make verify` in CI\n") == []


def test_no_document_that_is_not_history_keeps_the_old_rule():
    """The old rule asked for the whole gate before any push. A document that keeps 1 of its sentences
    tells a reader to wait for a gate the rule no longer asks for, or to push to `main` on it."""
    names = documents()
    assert "ee-agent-kit/AGENTS.md" in names and ".github/PULL_REQUEST_TEMPLATE.md" in names
    found = []
    for rel in names:
        if rel in HISTORY:
            continue
        found += old_rule_in(rel, (ROOT / rel).read_text(encoding="utf-8"))
    assert found == []


def test_the_documents_a_reader_meets_first_name_the_same_commands():
    """AGENTS.md, README.md, the pull request template, CI.md's section, P14 and the lead's kit each
    name the fast checks (`make check`), the gate (`make verify`) and the check that lets a commit
    merge (`verdict`); those that speak of a push to `main` name `make verify-site` too."""
    missing = []
    for rel, words in FIRST.items():
        text = " ".join(section(rel).split())
        missing += [f"{rel}: {word}" for word in words if word not in text]
    assert missing == []


def test_make_check_is_lint_and_the_kit_tests_and_starts_no_engine():
    """`make check` runs `make lint`, then the gate's kit checks (`verify/verify.sh kit`), then pytest
    on the kit's own tests and the files in TESTS, with engine starts refused and the tests marked
    `engine` left out, as `make verify-site` does. It takes no lock and runs no doctor and no gate: it
    does not need the machine alone."""
    ran = subprocess.run(
        ["make", "-n", "--no-print-directory", "-C", str(ROOT), "check", "TESTS=tests/test_ci_scope.py"],
        capture_output=True,
        text=True,
    )
    assert ran.returncode == 0, ran.stderr
    lines = ran.stdout.splitlines()
    lint = subprocess.run(
        ["make", "-n", "--no-print-directory", "-C", str(ROOT), "lint"], capture_output=True, text=True
    ).stdout.splitlines()
    assert lines[: len(lint)] == lint and any(line.startswith("shellcheck ") for line in lint)
    kit_line, pytest_line = lines[len(lint) :]
    assert kit_line == "verify/verify.sh kit"
    assert pytest_line.startswith("WORKCENTER_NO_ENGINES=1 ")
    assert '-m pytest -q -p no:cacheprovider -m "not engine" ' in pytest_line
    assert pytest_line.endswith(" ".join(KIT_TESTS) + " tests/test_ci_scope.py")
    for test in KIT_TESTS:
        assert (ROOT / test.split("::")[0]).is_file(), test
    assert [w for w in ("enginelock", "verify.sh", "doctor", "install.sh") if w in pytest_line] == []
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert {"check", "kit"} <= set(re.search(r"^\.PHONY: (.+)$", makefile, re.M).group(1).split())


def kit_copy(dest: Path) -> Path:
    """A copy of what the kit checks read, and nothing else: no tools/, so a kit run that reached for
    the engine lock (`tools/enginelock.py`) would fail."""
    files = [*KIT_FILES]
    files += [str(p.relative_to(ROOT)) for p in sorted(ROOT.glob(".claude/skills/*/SKILL.md"))]
    files += [str(p.relative_to(ROOT)) for p in sorted(ROOT.glob("ee-agent-kit/skills/*/SKILL.md"))]
    files += [str(p.relative_to(ROOT)) for p in sorted(ROOT.glob("ee-agent-kit/changes/*.md"))]
    for rel in files:
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, dest / rel)
    return dest


def kit_run(tree: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(tree / "verify/verify.sh"), "kit"], capture_output=True, text=True, timeout=60
    )


KIT_SKILLS = sorted(p.name for p in (ROOT / "ee-agent-kit/skills").iterdir() if p.is_dir())


def test_the_kit_checks_pass_on_this_tree_and_take_no_lock(tmp_path):
    """`verify/verify.sh kit` runs the gate's kit checks alone: the skills' frontmatter, the 2 copies
    of every kit skill, CLAUDE.md = AGENTS.md, every mistake's process and every process's Done when.
    It passes on this tree, with no tools/ beside it."""
    ran = kit_run(kit_copy(tmp_path))
    assert (ran.returncode, ran.stdout.splitlines()[-1:]) == (0, ["kit checks ok"]), ran.stdout + ran.stderr


@pytest.mark.parametrize("skill", KIT_SKILLS)
def test_a_drifted_copy_of_any_kit_skill_fails_the_kit_checks(tmp_path, skill):
    """Every folder in ee-agent-kit/skills/ has its copy in .claude/skills/, byte for byte (AGENTS.md).
    One added word in the kit's copy fails `make check`, whichever skill it is."""
    assert {"attached-repos", "blog-post", "land", "lead", "user-round"} <= set(KIT_SKILLS)
    tree = kit_copy(tmp_path)
    kit = tree / f"ee-agent-kit/skills/{skill}/SKILL.md"
    kit.write_text(kit.read_text(encoding="utf-8") + "drift\n", encoding="utf-8")
    ran = kit_run(tree)
    assert ran.returncode == 1
    assert f"ee-agent-kit/skills/{skill} drifted from .claude/skills/{skill}" in ran.stdout
