"""The documents name what exists (PROCESSES.md P5).

Each test holds a document to the code or the tree it describes: the commands, the skills, the tool
files, the fixture boards, the mistakes and processes a file cites, and the repository's own name. A
command added without its line in the README fails here, not in a reader's hands.
"""

from __future__ import annotations

import html
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
SITE = ROOT / "site"
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


def as_document(path: Path) -> str:
    """A file's text as these tests read a document. A page of the site gives each `<code>` span as
    code, with its tags left out and its entities read."""
    text = path.read_text(encoding="utf-8")
    if path.suffix != ".html":
        return text
    return html.unescape(re.sub(r"<[^>]+>", "", re.sub(r"</?code>", "`", text)))


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
        SITE / "index.html",
    ]
    assert "`workcenter design design.py --route`" in as_document(SITE / "index.html")
    wrong, checked = [], 0
    for doc in documents:
        for name, given in written_commands(as_document(doc)):
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


def runs_in(text: str) -> list[tuple[tuple[str, ...], list[str]]]:
    """Each `$ workcenter ...` line of a document, with the lines printed under it up to the next
    blank line or the end of its block."""
    runs: list[tuple[tuple[str, ...], list[str]]] = []
    in_run = False
    for line in text.splitlines():
        if line.startswith("$ workcenter "):
            runs.append((tuple(line.split()[2:]), []))
            in_run = True
        elif not line.strip() or line.startswith("```"):
            in_run = False
        elif in_run:
            runs[-1][1].append(line.rstrip())
    return runs


def masked(line: str) -> str:
    """A printed line without what differs between 2 runs of 1 command: the seconds, and the folder
    the checkout is in."""
    line = re.sub(r"\[\d+\.\d+s\]", "[s]", line)
    return re.sub(r"(report )\S*?(tests/boards/)", r"\1\2", line)


@pytest.mark.skipif(
    shutil.which("kicad-cli") is None or shutil.which("ngspice") is None,
    reason="kicad-cli and ngspice run the gates the documents show",
)
def test_every_run_a_document_shows_is_what_the_command_prints(tmp_path):
    """The README, the site and the Open Graph image show runs on fixture boards. A gate's summary
    changes when the gate does: 46 corner runs were 18. A run typed once and not run again goes stale."""
    documents = {
        "README.md": README,
        "site/index.html": as_document(SITE / "index.html"),
        "site/og.html": as_document(SITE / "og.html"),
    }
    shown = {
        (name, argv): lines for name, text in documents.items() for argv, lines in runs_in(text) if lines
    }
    assert len(shown) == 7 and {name for name, _ in shown} == set(documents)
    boards = {arg.split("/")[-1] for _, argv in shown for arg in argv if arg.startswith("tests/boards/")}
    for board in boards:
        shutil.copytree(
            ROOT / "tests" / "boards" / board,
            tmp_path / "tests" / "boards" / board,
            ignore=shutil.ignore_patterns("build", "__pycache__"),
        )
    printed: dict[tuple[str, ...], list[str]] = {}
    for _, argv in shown:
        if argv not in printed:
            if argv[0] == "next":
                # `next` reads the last gates report. The page shows it after a run of the gates; before
                # one, its first line is "Run the gates."
                subprocess.run(
                    [sys.executable, str(CLI), "gates", *argv[1:]],
                    cwd=tmp_path,
                    capture_output=True,
                    check=False,
                )
            proc = subprocess.run(
                [sys.executable, str(CLI), *argv], cwd=tmp_path, capture_output=True, text=True, check=False
            )
            printed[argv] = [masked(line.rstrip()) for line in proc.stdout.splitlines() if line.strip()]
    for (name, argv), lines in shown.items():
        assert [masked(line) for line in lines] == printed[argv], f"{name}: workcenter {' '.join(argv)}"


def links_of(page: Path) -> list[str]:
    return re.findall(r'(?:href|src)="([^"]+)"', page.read_text(encoding="utf-8"))


def test_every_link_on_the_site_names_what_exists():
    """A link to the repository names a path on `main`: a path the tree does not hold is a 404 after
    the merge. A link into the page names an id, and a link beside the page names a file."""
    blob = "https://github.com/ThyFriendlyFox/via/blob/main/"
    missing, to_repo, into_page, beside = [], 0, 0, 0
    for page in (SITE / "index.html", SITE / "404.html", SITE / "og.html"):
        text = page.read_text(encoding="utf-8")
        for link in links_of(page):
            if link.startswith(blob):
                to_repo += 1
                found = (ROOT / link[len(blob) :]).is_file()
            elif link.startswith("#"):
                into_page += 1
                found = f'id="{link[1:]}"' in text
            elif re.match(r"https?://|\./$|%ORIGIN%", link):
                continue
            else:
                beside += 1
                found = (SITE / link).is_file()
            if not found:
                missing.append(f"{page.name}: {link}")
    assert to_repo >= 11 and into_page >= 7 and beside >= 11, "the site's links are no longer found"
    assert missing == []


def test_the_site_builds_for_an_address_and_without_one(tmp_path):
    """`site/build.sh` writes what a host serves. A page that names a file the script does not copy
    breaks only after the deploy, so each link of a built page is looked up in the built folder."""

    def build(*args: object) -> subprocess.CompletedProcess:
        command = ["sh", str(SITE / "build.sh"), *map(str, args)]
        return subprocess.run(command, capture_output=True, text=True, check=False)

    served = tmp_path / "served"
    assert build(served, "https://example.org/via/").returncode == 0
    page = (served / "index.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://example.org/via/">' in page
    assert '<meta property="og:image" content="https://example.org/via/og.png">' in page
    assert '<base href="https://example.org/via/">' in (served / "404.html").read_text(encoding="utf-8")
    assert (served / "og.png").is_file() and (served / "fonts" / "LICENSE").is_file()
    looked_up = 0
    for name in ("index.html", "404.html"):
        assert "%ORIGIN%" not in (served / name).read_text(encoding="utf-8")
        for link in links_of(served / name):
            if not re.match(r"https?://|#|\./$", link):
                looked_up += 1
                assert (served / link).is_file(), f"{name} names {link}, and build.sh does not copy it"
    assert looked_up >= 10

    plain = tmp_path / "plain"
    assert build(plain).returncode == 0
    for name in ("index.html", "404.html"):
        text = (plain / name).read_text(encoding="utf-8")
        for absent in ("%ORIGIN%", "og:image", "og:url", 'rel="canonical"', "<base"):
            assert absent not in text, f"{name} keeps {absent} with no address to write into it"

    again = build(plain)
    assert again.returncode == 2 and "is not empty" in again.stderr
    for bad in ("ftp://example.org", "https://", "example.org", "https://example.org/a|b"):
        refused = build(tmp_path / "refused", bad)
        assert refused.returncode == 2 and bad in refused.stderr, bad
        assert not (tmp_path / "refused").exists(), bad


def test_the_open_graph_image_has_the_size_the_page_states():
    """GitHub asks 1280 x 640 and under 1 MB of a social preview. The page states the size to a
    crawler, so the 2 files and the page say 1 size."""
    page = (SITE / "index.html").read_text(encoding="utf-8")
    stated = tuple(
        int(re.search(rf'og:image:{side}" content="(\d+)"', page).group(1)) for side in ("width", "height")
    )
    assert stated == (1280, 640)
    for name in ("og.png", "og-dark.png"):
        data = (SITE / name).read_bytes()
        assert data[:8] == b"\x89PNG\r\n\x1a\n", name
        assert struct.unpack(">II", data[16:24]) == stated, name
        assert len(data) < 1_000_000, name


def test_every_picture_and_link_in_the_readme_names_a_file():
    found = re.findall(r'\]\(([^)#\s]+)\)|(?:src|srcset)="([^"]+)"', README)
    local = [a or b for a, b in found if not (a or b).startswith(("http://", "https://"))]
    assert {"site/og.png", "site/og-dark.png", "LICENSE", "site/fonts/LICENSE"} <= set(local)
    assert [target for target in local if not (ROOT / target).is_file()] == []
