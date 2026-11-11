"""The documents name what exists (PROCESSES.md P5).

Each test holds a document to the code or the tree it describes: the commands, the skills, the tool
files, the fixture boards, the mistakes and processes a file cites, and the repository's own name. A
command added without its line in the README fails here, not in a reader's hands.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
README = (ROOT / "README.md").read_text(encoding="utf-8")
CONTRACT = (ROOT / "WORKCENTER.md").read_text(encoding="utf-8")
MISTAKES = (ROOT / "ee-agent-kit" / "MISTAKES.md").read_text(encoding="utf-8")
PROCESSES = (ROOT / "ee-agent-kit" / "PROCESSES.md").read_text(encoding="utf-8")
# The files that cite a mistake as (M12) or a process as P12: the code a reader meets first, and the
# documents a project reads. kicadgen and the 3D tools use M2 and M3 for screws.
CITING = (
    "tools/workcenter",
    "tools/simcorners.py",
    "tools/freqplan.py",
    "tools/guide.py",
    "tools/doctools.py",
    "WORKCENTER.md",
    "ee-agent-kit/AGENTS.md",
    "ee-agent-kit/docs/CONFIGURATION.md",
    *(str(p.relative_to(ROOT)) for p in sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md"))),
)


def commands() -> list[str]:
    """The CLI's subcommands, from its own help."""
    proc = subprocess.run([sys.executable, str(CLI), "--help"], capture_output=True, text=True, check=True)
    return re.search(r"\{([a-z,]+)\}", proc.stdout).group(1).split(",")


def test_every_command_is_in_the_readme_and_in_the_contract():
    found = commands()
    assert len(found) >= 24 and "next" in found and "gates" in found
    assert [c for c in found if f"`{c}`" not in README] == []
    assert [c for c in found if not re.search(rf"workcenter {c}\b", CONTRACT)] == []


def help_of(*words: str) -> str:
    proc = subprocess.run(
        [sys.executable, str(CLI), *words, "--help"], capture_output=True, text=True, check=True
    )
    return proc.stdout


def flags_of(command: str) -> set[str]:
    """A command's flags, from its own help and the help of each command under it (`inspect map`)."""
    text = help_of(command)
    under = re.search(r"\{([a-z_,]+)\}", text.split("\n\n")[0])
    for word in under.group(1).split(",") if under else []:
        text += help_of(command, word)
    return set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", text))


def written_commands(text: str) -> list[tuple[str, set[str]]]:
    """Each `workcenter <command> ...` a document writes as code, with the flags it gives the command:
    the lines of a fenced block, and each inline span, which may wrap onto the next line."""
    fences = re.findall(r"^```.*?^```", text, re.S | re.M)
    spans = [line for block in fences for line in block.splitlines()]
    spans += re.findall(r"`([^`]+)`", re.sub(r"^```.*?^```", "", text, flags=re.S | re.M))
    found = []
    for span in spans:
        for part in re.split(r"\bworkcenter (?=[a-z])", " ".join(span.split()))[1:]:
            names = part.split()[0]
            found += [
                (name, set(re.findall(r"(?<![\w-])--[a-z][a-z0-9-]*", part))) for name in names.split("|")
            ]
    return found


def test_every_flag_a_document_gives_a_command_is_a_flag_of_that_command():
    """A reader copies a command as it is written. A flag the command does not take ends in a usage
    error with exit code 2, which is also the code of a skipped run."""
    flags = {c: flags_of(c) for c in commands()}
    assert "--bundle" in flags["sim"] and "--box" in flags["inspect"] and "--from" in flags["version"]
    documents = [
        ROOT / "README.md",
        ROOT / "WORKCENTER.md",
        ROOT / "AGENTS.md",
        ROOT / "ee-agent-kit" / "AGENTS.md",
        ROOT / "ee-agent-kit" / "PROCESSES.md",
        ROOT / "ee-agent-kit" / "ROUTING.md",
        ROOT / "ee-agent-kit" / "docs" / "CONFIGURATION.md",
        *sorted((ROOT / ".claude" / "skills").glob("*/SKILL.md")),
        *sorted((ROOT / "templates").rglob("*.md")),
    ]
    wrong, checked = [], 0
    for doc in documents:
        for name, given in written_commands(doc.read_text(encoding="utf-8")):
            if name in flags:
                checked += 1
                wrong += [
                    f"{doc.relative_to(ROOT)}: workcenter {name} {f}" for f in sorted(given - flags[name])
                ]
    assert checked > 150, "the documents' commands are no longer found: the pattern is off"
    assert wrong == []


def test_json_is_read_on_either_side_of_the_command():
    """The skills write `workcenter gates <project> --json`. argparse alone reads a flag of the whole
    program only before the command, and answers the other order with a usage error."""
    for command in commands():
        assert "--json" in help_of(command), command
    runs = [
        subprocess.run([sys.executable, str(CLI), *argv], capture_output=True, text=True, check=False)
        for argv in (["--json", "doctor"], ["doctor", "--json"], ["doctor"])
    ]
    before, after, plain = runs
    assert after.returncode == before.returncode == plain.returncode
    assert after.stdout == before.stdout and after.stdout.lstrip().startswith("{")
    assert not plain.stdout.lstrip().startswith("{")


def test_every_skill_is_in_the_readme_and_in_the_contract():
    skills = sorted(p.name for p in (ROOT / ".claude" / "skills").iterdir() if (p / "SKILL.md").is_file())
    assert len(skills) >= 9
    assert [s for s in skills if f"`{s}`" not in README] == []
    assert [s for s in skills if f"| `{s}` |" not in CONTRACT] == []


def test_every_tool_file_is_in_the_readme():
    tools = sorted(p.name for p in (ROOT / "tools").iterdir() if p.is_file())
    assert "workcenter" in tools and "simcorners.py" in tools
    assert [t for t in tools if f"tools/{t}`" not in README] == []


def test_every_fixture_board_has_its_row():
    rows = (ROOT / "tests" / "boards" / "README.md").read_text(encoding="utf-8")
    boards = sorted(p.name for p in (ROOT / "tests" / "boards").iterdir() if p.is_dir())
    assert "pass-rc-divider" in boards and "fail-freq-overlap" in boards
    assert [b for b in boards if f"| `{b}` |" not in rows] == []


def test_every_mistake_and_process_a_file_cites_exists():
    mistakes = {int(n) for n in re.findall(r"^## M(\d+) ", MISTAKES, re.M)}
    processes = {int(n) for n in re.findall(r"^## P(\d+) ", PROCESSES, re.M)}
    assert max(mistakes) >= 115 and max(processes) >= 31
    for rel in CITING:
        text = (ROOT / rel).read_text(encoding="utf-8")
        # a mistake is cited in parentheses, alone or in a list: (M94), (M42, M47)
        groups = re.findall(r"\(((?:M\d{1,3}(?:, )?)+)\)", text)
        cited = {int(n) for group in groups for n in re.findall(r"\d+", group)}
        assert sorted(cited - mistakes) == [], f"{rel} cites a mistake that MISTAKES.md does not hold"
        # a process is cited after the file's name or in parentheses: `PROCESSES.md` P27, (P23)
        cited = {int(n) for n in re.findall(r"(?:PROCESSES\.md`?,? |\()P(\d{1,2})\b", text)}
        assert sorted(cited - processes) == [], f"{rel} cites a process that PROCESSES.md does not hold"


def test_no_file_names_the_repository_by_its_old_name():
    """The repository was `workspace-ee-test`. The mistakes log keeps the name where an entry tells
    what happened then; no command, script or document that is read today does."""
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True, check=True
    ).stdout.split()
    holders = []
    for rel in tracked:
        if rel.startswith("third_party/") or rel == "ee-agent-kit/MISTAKES.md" or rel == "tests/test_docs.py":
            continue
        path = ROOT / rel
        if path.is_file() and b"workspace-ee-test" in path.read_bytes():
            holders.append(rel)
    assert holders == []


def test_the_root_instruction_files_are_one_text():
    assert (ROOT / "AGENTS.md").read_bytes() == (ROOT / "CLAUDE.md").read_bytes()
    text = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    for named in re.findall(r"`((?:ee-agent-kit/)?[A-Z]+\.md|ee-agent-kit/[A-Z]+\.md)`", text):
        assert (ROOT / named).is_file(), named
