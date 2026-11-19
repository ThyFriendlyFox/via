"""Where the health gate runs: 1 rule, the same in every document (the owner's decision of 2026-11-19).

`main` takes no commit that `make verify` did not pass on that exact commit: CI's `full` job on the
pull request (the `verdict` check), or `make verify` on the machine where there is no CI. A push to a
work branch needs the fast checks only: `make check`. The rule stands in many documents, and before
this change they said "`make verify` green before every push". These tests hold the documents to the
new rule: the old sentences are gone from every document that is not history, the documents a reader
meets first name the same commands, and `make check` is what they say it is. They read files and ask
`make -n`; nothing here starts an engine.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

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
)

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
    "ee-agent-kit/AGENTS.md": ("`make check`", "`verdict`", "`make verify`", "`make verify-site`"),
    "README.md": ("`make check`", "`verdict`", "`make verify`", "`make verify-site`"),
    ".github/PULL_REQUEST_TEMPLATE.md": ("`make check`", "`verdict`", "`make verify`"),
    "ee-agent-kit/CI.md#Where the health gate runs": (
        "`make check`",
        "`verdict`",
        "`make verify`",
        "`make verify-site`",
        "`workflow_dispatch`",
    ),
    "ee-agent-kit/PROCESSES.md#P14 — Closing out a change": ("`make check`", "`verdict`", "`make verify`"),
    ".claude/skills/land/SKILL.md": ("`make check`", "`verdict`", "gh workflow run ci.yml"),
    ".claude/skills/lead/SKILL.md": ("`make check`", "`verdict`"),
    "ee-agent-kit/lead/README.md": ("`make check`", "`verdict`"),
}


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


def test_no_document_that_is_not_history_keeps_the_old_rule():
    """The old rule asked for the whole gate before any push. A document that keeps 1 of its sentences
    tells a reader to wait for a gate the rule no longer asks for, or to push to `main` on it."""
    names = documents()
    assert "ee-agent-kit/AGENTS.md" in names and ".github/PULL_REQUEST_TEMPLATE.md" in names
    found = []
    for rel in names:
        if rel in HISTORY:
            continue
        text = (ROOT / rel).read_text(encoding="utf-8")
        found += [f"{rel}: {old}" for old in OLD if old in " ".join(text.split())]
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
    """`make check` runs `make lint`, then pytest on the kit's own tests and the files in TESTS, with
    engine starts refused and the tests marked `engine` left out, as `make verify-site` does. It takes
    no lock and runs no doctor and no gate: it does not need the machine alone."""
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
    (pytest_line,) = lines[len(lint) :]
    assert pytest_line.startswith("WORKCENTER_NO_ENGINES=1 ")
    assert '-m pytest -q -p no:cacheprovider -m "not engine" ' in pytest_line
    assert pytest_line.endswith(" ".join(KIT_TESTS) + " tests/test_ci_scope.py")
    for test in KIT_TESTS:
        assert (ROOT / test.split("::")[0]).is_file(), test
    assert [w for w in ("enginelock", "verify.sh", "doctor", "install.sh") if w in pytest_line] == []
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "check" in re.search(r"^\.PHONY: (.+)$", makefile, re.M).group(1).split()
