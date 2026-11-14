"""The documents name what exists (PROCESSES.md P5).

Each test holds a document to the code or the tree it describes: the commands, the skills, the tool
files, the fixture boards, the mistakes and processes a file cites, and the repository's own name. A
command added without its line in the README fails here, not in a reader's hands.
"""

from __future__ import annotations

import html
import os
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
    assert f"<summary>The {len(found)} commands</summary>" in README
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
        SITE / "media" / "README.md",
        SITE / "media" / "hero.html",
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


def test_a_count_of_tests_in_the_status_file_is_what_pytest_collects():
    """STATUS.md gives a test file's count beside its name: `tests/test_gates.py` (26 tests). 2 of the
    18 counts were stale on 2026-11-12: 21 for 25, 11 for 13. The count is what pytest collects."""
    status = (ROOT / "ee-agent-kit" / "STATUS.md").read_text(encoding="utf-8")
    stated = {name: int(count) for name, count in re.findall(r"`tests/(test_\w+\.py)` \((\d+)\b", status)}
    assert len(stated) >= 15
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", "tests"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    collected: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        if line.startswith("tests/") and "::" in line:
            name = line.split("::")[0].removeprefix("tests/")
            collected[name] = collected.get(name, 0) + 1
    assert collected, proc.stdout + proc.stderr
    wrong = {name: (count, collected.get(name)) for name, count in stated.items()}
    assert {name: pair for name, pair in wrong.items() if pair[0] != pair[1]} == {}
    # The same row of counts names the last mistake and the last process: it read M145 while the log
    # held M157.
    last = {
        letter: max(int(n) for n in re.findall(rf"^## {letter}(\d+) ", text, re.M))
        for letter, text in (("M", MISTAKES), ("P", PROCESSES))
    }
    assert f"`MISTAKES.md` M1 to M{last['M']}, `PROCESSES.md` P1 to P{last['P']};" in status


def test_a_pointer_to_a_roadmap_item_gives_its_number_and_its_title():
    """The queue is renumbered when an item ships. STATUS.md pointed at `ROADMAP item 2` for the
    autoroute work after that item had become item 4 (M160). A pointer carries the item's title, and
    the pair is a heading of the roadmap. ENGINES.md kept 2 bare `ROADMAP item 1` for that work through
    3 renumberings, until the chip item shipped on 2026-11-12: it is read here too."""
    roadmap = (ROOT / "ee-agent-kit" / "ROADMAP.md").read_text(encoding="utf-8")
    items = dict(re.findall(r"^### (\d+)\. (.+)$", roadmap, re.M))
    assert len(items) >= 4
    pointers = []
    documents = ("README.md", "WORKCENTER.md", "ee-agent-kit/STATUS.md", "ee-agent-kit/CHANGELOG.md")
    for rel in (*documents, "ee-agent-kit/docs/USE-CASES.md", "ee-agent-kit/docs/ENGINES.md"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        pointers += [(rel, n, title) for n, title in re.findall(r'ROADMAP item (\d+)(?:, "([^"]+)")?', text)]
    assert len(pointers) >= 4
    assert [p for p in pointers if items.get(p[1]) != p[2]] == []


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


def chip_engines_absent() -> list[str]:
    """Each chip engine, and the process kit, that this machine lacks: a chip's run needs them all."""
    sys.path.insert(0, str(ROOT / "tests"))
    from test_chips import EVERY, absent

    return absent(EVERY)


def masked(line: str) -> str:
    """A printed line without what differs between 2 runs of 1 command: the seconds, and the folder
    the checkout is in."""
    line = re.sub(r"\[\d+\.\d+s\]", "[s]", line)
    return re.sub(r"(report )\S*?((?:tests/boards|tests/chips|examples)/)", r"\1\2", line)


@pytest.mark.skipif(
    shutil.which("kicad-cli") is None or shutil.which("ngspice") is None,
    reason="kicad-cli and ngspice run the gates the documents show",
)
def test_every_run_a_document_shows_is_what_the_command_prints(tmp_path):
    """The README, the site and its example pages show runs on fixture boards, on the example projects
    and on the fixture processor. A gate's summary changes when the gate does: 46 corner runs were 18.
    A run typed once and not run again goes stale. The chip's run is made where the chip engines are
    installed: they install on request, and it takes 4 minutes."""
    documents = {
        "README.md": README,
        "site/index.html": as_document(SITE / "index.html"),
        **{str(p.relative_to(ROOT)): as_document(p) for p in example_pages() if runs_in(as_document(p))},
    }
    shown = {
        (name, argv): lines for name, text in documents.items() for argv, lines in runs_in(text) if lines
    }
    assert len(shown) == 8 and {name for name, _ in shown} == set(documents)
    assert [argv for _, argv in shown if argv[0] == "chip"] == [
        ("chip", "gates", "tests/chips/pass-acc8", "--strict")
    ]
    if chip_engines_absent():
        shown = {key: lines for key, lines in shown.items() if key[1][0] != "chip"}
    kept = ("tests/boards/", "tests/chips/", "examples/")
    boards = {arg for _, argv in shown for arg in argv if arg.startswith(kept)}
    for board in boards:
        shutil.copytree(ROOT / board, tmp_path / board, ignore=shutil.ignore_patterns("build", "__pycache__"))
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


# Each command of the README's quick start, in its order: the exit code it ends with, and the start
# of a line it prints ("^" for its first line). From runs of 2026-11-11 on fresh copies.
QUICK_START = {
    "workcenter doctor": (0, "^workcenter ee: "),
    "workcenter gates tests/boards/pass-first-design": (0, "GREEN: divider  report "),
    "workcenter gates tests/boards/fail-drc-clearance": (1, "RED: rc_divider  report "),
    "workcenter next tests/boards/fail-drc-clearance": (
        1,
        "^NEXT       Move the track or the pad apart; check the net class clearance.",
    ),
    "workcenter sim tests/boards/fail-sim-corner": (
        1,
        "^FAIL   sim        2 decks, 32 corner runs, 2 failures, 1 warnings",
    ),
    "workcenter sim tests/boards/fail-freq-overlap": (1, "       - frequency plan: load's harmonic 3 "),
    "mkdir ~/divider": (0, ""),
    "cp templates/project/design.py ~/divider/": (0, ""),
    "workcenter design ~/divider/design.py --route": (0, "  routed: "),
    "workcenter gates ~/divider --strict": (0, "GREEN (nothing to run for: sim): divider  report "),
}


@pytest.mark.skipif(
    shutil.which("kicad-cli") is None
    or shutil.which("ngspice") is None
    or shutil.which("java") is None
    or not Path("/opt/workcenters/ee/freerouting/freerouting.jar").is_file(),
    reason="kicad-cli, ngspice and FreeRouting run the commands of the quick start",
)
def test_the_quick_start_runs_as_written_and_ends_as_its_comments_say(tmp_path):
    """No test held the quick start: with a fixture's name misspelt in it every test here passed (a
    review of 2026-11-11). Each line of its 2 blocks runs as written and in its order. `workcenter`
    is this tree's CLI, the fixtures and the templates are copies, and `~` is a folder of the test."""
    section = README.split("\n## Quick start\n", 1)[1].split("\n## ", 1)[0]
    lines = [line for block in re.findall(r"```sh\n(.*?)```", section, re.S) for line in block.splitlines()]
    written = {line.partition("#")[0].strip(): line.partition("#")[2] for line in lines if line.strip()}
    assert list(written) == ["sudo ./install.sh", *QUICK_START]
    for command, (code, _) in QUICK_START.items():
        assert ("GREEN" in written[command]) <= (code == 0), command
        assert ("red" in written[command]) <= (code == 1), command
    work = tmp_path / "checkout"
    words = [word for command in QUICK_START for word in command.split()]
    for board in {word.split("/")[-1] for word in words if "/boards/" in word}:
        shutil.copytree(
            ROOT / "tests" / "boards" / board,
            work / "tests" / "boards" / board,
            ignore=shutil.ignore_patterns("build", "__pycache__"),
        )
    shutil.copytree(ROOT / "templates", work / "templates")
    shim = tmp_path / "bin" / "workcenter"
    shim.parent.mkdir()
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{CLI}" "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    env = {**os.environ, "PATH": f"{shim.parent}{os.pathsep}{os.environ['PATH']}", "HOME": str(home)}
    for command, (code, said) in QUICK_START.items():
        ran = subprocess.run(
            ["bash", "-c", command], cwd=work, env=env, capture_output=True, text=True, check=False
        )
        printed = ran.stdout.splitlines()
        assert ran.returncode == code, f"{command}: {ran.stdout}{ran.stderr}"
        if said.startswith("^"):
            assert printed[0].startswith(said[1:]), (command, printed[0])
        elif said:
            assert any(line.startswith(said) for line in printed), (command, printed)


def links_of(page: Path) -> list[str]:
    """Each address a page names: its links, its pictures and its scripts, and what a `url()` in its
    markup loads."""
    text = page.read_text(encoding="utf-8")
    return re.findall(r'(?:href|src)="([^"]+)"', text) + re.findall(r"url\(([^)\s]+)\)", text)


def example_pages() -> list[Path]:
    """The pages site/examples.py writes: the list of examples, and 1 page for each."""
    return [SITE / "examples.html", *sorted((SITE / "examples").glob("*.html"))]


def beside_page(page: Path, link: str) -> bool:
    """Whether a link read from the page's own folder names a file: `agents.svg#cursor` is
    agents.svg, `site.css?v=1` is site.css, and a folder is its index.html."""
    target = page.parent / link.split("#")[0].split("?")[0]
    return target.is_file() or (target / "index.html").is_file()


def test_every_link_on_the_site_names_what_exists():
    """A link to the repository names a path on `main`: a path the tree does not hold is a 404 after
    the merge. A link into the page names an id, and a link beside the page names a file."""
    blob = "https://github.com/ThyFriendlyFox/via/blob/main/"
    missing, to_repo, into_page, beside = [], 0, 0, 0
    for page in (SITE / "index.html", SITE / "404.html", SITE / "og.html", *example_pages()):
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
                found = beside_page(page, link)
            if not found:
                missing.append(f"{page.relative_to(SITE)}: {link}")
    assert to_repo >= 20 and into_page >= 8 and beside >= 70, "the site's links are no longer found"
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
    pages = ["index.html", "404.html", *(str(p.relative_to(SITE)) for p in example_pages())]
    example = (served / "examples" / "rosetta.html").read_text(encoding="utf-8")
    assert '<link rel="canonical" href="https://example.org/via/examples/rosetta">' in example
    # A host may keep a stylesheet or a script for hours while it asks again for the page (M157): the
    # built page names each with its checksum, so a new page never runs with the last build's. An
    # example's page names them from its folder, as ../site.css.
    for built, names in (
        (page, ("site.css", "site.js", "effects.js")),
        (example, ("site.css", "example.js")),
    ):
        for name in names:
            named = re.findall(rf'"(?:\.\./)*{re.escape(name)}\?v=(\d+)"', built)
            cksum = subprocess.run(
                ["cksum"], input=(SITE / name).read_bytes(), capture_output=True, check=True
            )
            assert named == [cksum.stdout.split()[0].decode()], f"the built page names {name} with no version"
    looked_up = 0
    for name in pages:
        assert "%ORIGIN%" not in (served / name).read_text(encoding="utf-8")
        for link in links_of(served / name):
            if not re.match(r"https?://|#|\./$", link):
                looked_up += 1
                assert beside_page(served / name, link), f"{name} names {link}, and build.sh does not copy it"
    assert looked_up >= 60
    # A part's label names the first page of its datasheet in the page's JSON, not in an attribute,
    # so each is looked up here, with the size the label reserves for it.
    parts = re.search(r'<script type="application/json" id="herald-parts">(.*?)</script>', page, re.S)
    sheets = {tuple(entry) for entry in re.findall(r'"dp":\["([^"]+)",(\d+),(\d+)\]', parts.group(1))}
    assert len(sheets) >= 5, "the labels no longer show their datasheets' first pages"
    for path, width, height in sheets:
        assert (served / path).is_file(), f"a label names {path}, and build.sh does not copy it"
        assert png_size(served / path) == (int(width), int(height)), path

    plain = tmp_path / "plain"
    assert build(plain).returncode == 0
    for name in pages:
        text = (plain / name).read_text(encoding="utf-8")
        for absent in ("%ORIGIN%", "og:image", "og:url", 'rel="canonical"', "<base"):
            assert absent not in text, f"{name} keeps {absent} with no address to write into it"

    again = build(plain)
    assert again.returncode == 2 and "is not empty" in again.stderr
    for bad in ("ftp://example.org", "https://", "example.org", "https://example.org/a|b"):
        refused = build(tmp_path / "refused", bad)
        assert refused.returncode == 2 and bad in refused.stderr, bad
        assert not (tmp_path / "refused").exists(), bad


def png_size(path: Path) -> tuple[int, int]:
    """A PNG's width and height, from its header."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path.name
    return struct.unpack(">II", data[16:24])


def picture_size(path: Path) -> tuple[int, int]:
    """A PNG's or a GIF's width and height, from its header."""
    data = path.read_bytes()
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    return png_size(path)


def test_the_open_graph_image_has_the_size_the_page_states():
    """GitHub asks 1280 x 640 and under 1 MB of a social preview. The page states the size to a
    crawler, so the file and the page say 1 size."""
    page = (SITE / "index.html").read_text(encoding="utf-8")
    stated = tuple(
        int(re.search(rf'og:image:{side}" content="(\d+)"', page).group(1)) for side in ("width", "height")
    )
    assert stated == (1280, 640)
    assert png_size(SITE / "og.png") == stated
    assert (SITE / "og.png").stat().st_size < 1_000_000


def local_links(path: Path) -> list[str]:
    """Each file a Markdown document links to or shows, as the document writes it: `](path)`, and the
    `src`, `srcset` and `href` of its HTML. A link to a place inside a file names the file: the part
    from `#` on is left out. An address on the web is left out."""
    found = re.findall(
        r'\]\(([^)#\s]+)(?:#[^)\s]*)?\)|(?:src|srcset|href)="([^"#]+)(?:#[^"]*)?"',
        path.read_text(encoding="utf-8"),
    )
    return [a or b for a, b in found if not (a or b).startswith(("http://", "https://"))]


def test_every_picture_and_link_in_a_readme_names_a_file():
    """GitHub draws a missing picture as a broken image, and a missing link is a 404. A path is read
    from the document's own folder, as GitHub reads it. The 2 documents are the root's README and the
    README of `site/media/`: the front page and the page of its pictures. The test holds that a
    picture is a file of a size, not what the picture shows."""
    media = SITE / "media"
    shown = {
        ROOT / "README.md": {
            "LICENSE",
            "site/fonts/LICENSE",
            "site/media/README.md",
            "site/media/hero.png",
            "site/media/hero-dark.png",
            "site/media/board-spin.gif",
            "site/media/layers.png",
            "site/media/diagram.png",
            "site/media/diagram-dark.png",
            "site/media/chip.png",
            "site/media/chip-met2.png",
        },
        media / "README.md": {
            "hero.png",
            "hero-dark.png",
            "schematic.png",
            "board.png",
            "board-spin.gif",
            "layers.png",
            "diagram.png",
            "diagram-dark.png",
            "chip.png",
            "chip-met1.png",
            "chip-met2.png",
            "chip-met3.png",
            "chip-met4.png",
        },
    }
    for document, expected in shown.items():
        local = local_links(document)
        assert expected <= set(local), document.relative_to(ROOT)
        assert [target for target in local if not (document.parent / target).is_file()] == []
    # Every picture in the folder is shown by its README, and a picture and its dark twin have 1 size.
    pictures = {p.name for p in media.iterdir() if p.suffix in (".png", ".gif")}
    assert pictures == set(local_links(media / "README.md")) == shown[media / "README.md"]
    for name in ("hero", "diagram"):
        assert png_size(media / f"{name}.png") == png_size(media / f"{name}-dark.png"), name
    assert all((media / name).stat().st_size < 2_000_000 for name in pictures)


def test_the_code_a_page_shows_is_a_run_of_lines_of_its_file():
    """The site's page shows lines of its example's design file, and `site/media/hero.html`, the page
    the README's first picture is a capture of, lines of the fixture's. A `<pre data-file>` names its
    file, and its lines are a run of that file's lines, so a page shows no call the file does not
    make. Each page's 2 pictures, the schematic and the board, are files at the path the page gives."""
    shows = {
        SITE / "index.html": (
            "examples/fire-alarm-communicator/v0.1/design.py",
            7,
            ["showcase/herald-schematic.png", "showcase/herald-top.png"],
        ),
        SITE / "media" / "hero.html": (
            "tests/boards/pass-first-design/design.py",
            12,
            ["schematic.png", "board.png"],
        ),
    }
    for page, (file, count, drawn) in shows.items():
        text = page.read_text(encoding="utf-8")
        shown = re.findall(r'<pre data-file="([^"]+)">(.*?)</pre>', text, re.S)
        assert [name for name, _ in shown] == [file], page.name
        code = html.unescape(re.sub(r"<[^>]+>", "", shown[0][1]))
        lines = [line.strip() for line in code.splitlines()]
        source = [line.strip() for line in (ROOT / file).read_text(encoding="utf-8").splitlines()]
        assert len(lines) == count, page.name
        starts = [i for i in range(len(source)) if source[i : i + len(lines)] == lines]
        assert len(starts) == 1, f"{page.name}: the code is no run of lines of {file}"
        links = links_of(page)
        assert all(picture in links for picture in drawn), page.name
        for link in links:
            if not re.match(r"https?://|#|\./$|%ORIGIN%", link):
                assert beside_page(page, link), f"{page.name}: {link}"
    # Each page states each picture's size, so the cards keep their place while a picture loads.
    for page in (SITE / "index.html", *example_pages()):
        text = page.read_text(encoding="utf-8")
        pictures = re.findall(r'<img [^>]*?src="([^"]+\.(?:png|gif))"', text)
        stated = {
            src: (int(width), int(height))
            for src, width, height in re.findall(
                r'<img [^>]*?src="([^"]+\.(?:png|gif))" width="(\d+)" height="(\d+)"', text
            )
        }
        assert sorted(stated) == sorted(set(pictures)), page.name
        assert stated == {name: picture_size(page.parent / name) for name in stated}, page.name
        if page.name == "index.html":
            herald = {"examples/herald/card.png", "showcase/herald-schematic.png", "showcase/herald-top.png"}
            assert herald <= set(stated)


def test_the_example_pages_are_what_site_examples_writes():
    """An example's page is written from its README, its versions' TIMELINE.md or "What changed"
    sections, and its board. A page edited by hand, or an example changed and its page not written
    again, differs from what the script writes."""
    proc = subprocess.run(
        [sys.executable, str(SITE / "examples.py"), "--check"], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stderr
    sys.path.insert(0, str(SITE))
    import examples

    found = {ex.slug: ex for ex in examples.examples()}
    assert set(found) == {p.stem for p in (SITE / "examples").glob("*.html")}
    # Rosetta shows v0.2, its board and its card's numbers, and v0.1's steps from v0.1's TIMELINE.md.
    rosetta = found["rosetta"]
    board = examples.draw_board(rosetta.board)
    page = examples.example_page(rosetta, board, {"spin.webp", "top.png", "bottom.png"})
    assert rosetta.version == "v0.2" and (board.layers, board.parts) == (6, 135)
    assert len(rosetta.timeline) >= 8 and {entry.version for entry in rosetta.timeline} == {"v0.1"}
    assert f"{board.segments:,} track segments" in page
    # Wyvern's steps are its README's "What changed" sections, oldest first; its verdict is its report's.
    wyvern = found["wyvern"]
    assert [entry.stage for entry in wyvern.timeline] == ["v0.1", "v0.2"]
    assert wyvern.verdict.startswith("GREEN")
    assert [gate for gate, _, _ in wyvern.checks] == ["ERC", "DRC", "SIM", "EXPORT"]
    # Signet is 6 boards: 1 verdict each, and no board drawing.
    signet = found["signet"]
    assert signet.board is None and len(signet.per_board) == 6 and signet.verdict == "GREEN on all 6 boards"
    # The page follows its sources: a step's title, changed, changes the page.
    rosetta.timeline[0].title = "A title no step has"
    assert "A title no step has" in examples.example_page(rosetta, board, set())


def numbers(text: str) -> list[str]:
    """The numbers with a decimal point in a text, as written: 0.4216, 15.9."""
    return re.findall(r"(?<![\w.])\d+\.\d+(?![\w.]*\d)", text)


def test_the_gates_drawings_hold_numbers_their_boards_give():
    """Each drawing of the gates on the home page names the board it shows under it. A value it marks
    (0.4216 V, 15.9 kHz) is a number of that board's files, of the fixtures' README, or of a run the
    page shows, to the places the drawing gives: a drawing does not make up a reading."""
    text = (SITE / "index.html").read_text(encoding="utf-8")
    runs = " ".join(re.findall(r"<pre data-run[^>]*>(.*?)</pre>", text, re.S))
    drawings = re.findall(r'<article class="draw[^"]*">(.*?)</article>', text, re.S)
    assert len(drawings) == 7
    checked = 0
    for drawing in drawings:
        svg = re.search(r"<svg.*?</svg>", drawing, re.S)
        if not svg:
            continue
        name = re.search(r'<p class="fname">([^<]+)</p>', drawing).group(1)
        project = ROOT / Path(*Path(name).parts[:3])  # tests/boards/<board>, examples/<name>/<version>
        sources = [p for p in project.rglob("*") if p.suffix in (".cir", ".json", ".md", ".py")]
        corpus = runs + (ROOT / "tests" / "boards" / "README.md").read_text(encoding="utf-8")
        corpus += " ".join(p.read_text(encoding="utf-8") for p in sources)
        known = [float(n) for n in numbers(corpus)]
        # An axis's tick is a place on the paper, not a reading: it is marked `tick`.
        for attrs, label in re.findall(r"<text([^>]*)>(.*?)</text>", svg.group(0)):
            if "tick" in attrs:
                continue
            for shown in numbers(html.unescape(label)):
                places = len(shown.split(".")[1])
                checked += 1
                found = any(round(n, places) == float(shown) for n in known)
                assert found, f"{name}: {shown} is in no source"
    assert checked >= 12


LOG_FORMAT = "--format=%H%x00%an <%ae>%x00%cn <%ce>%x00%B%x01"
ASSISTANT = re.compile(r"claude|anthropic", re.I)
CREDIT = re.compile(
    r"^[ \t]*(co-authored-by:.*(?:claude|anthropic).*|claude-session:.*|.*generated with \[claude code\].*)$",
    re.I | re.M,
)


def credits(log: str) -> list[str]:
    """Each place where a `git log` in LOG_FORMAT names an assistant as a commit's author or committer,
    or where a message credits one, as `<subject>: <what>`. A message may name a file or a product:
    `CLAUDE.md` and `Claude Code` are no credit."""
    found = []
    for entry in log.split("\x01"):
        if not entry.strip():
            continue
        _, author, committer, message = entry.strip("\n").split("\x00")
        subject = message.split("\n")[0]
        found += [f"{subject}: author {author}"] if ASSISTANT.search(author) else []
        found += [f"{subject}: committer {committer}"] if ASSISTANT.search(committer) else []
        found += [f"{subject}: {line.group(0).strip()}" for line in CREDIT.finditer(message)]
    return found


def test_no_commit_names_an_assistant_as_its_author(tmp_path):
    """The owner's decision of 2026-11-11: a commit names the repository's owner as its author, and no
    message credits an assistant. The check reads the history of the checked-out branch, not the
    remote's other branches; CI's shallow clone holds the newest commit. It is proven first on a
    history made here."""

    def git(repo: Path, *args: str, name: str = "Owner", email: str = "owner@example.org") -> str:
        identity = ["-c", f"user.name={name}", "-c", f"user.email={email}", "-c", "commit.gpgsign=false"]
        ran = subprocess.run(["git", "-C", str(repo), *identity, *args], capture_output=True, text=True)
        assert ran.returncode == 0, ran.stderr
        return ran.stdout

    made = tmp_path / "made"
    made.mkdir()
    git(made, "init", "-q")
    git(made, "commit", "-q", "--allow-empty", "-m", "Rule: CLAUDE.md and Claude Code hooks are files")
    git(
        made,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "By the tool",
        name="Claude",
        email="noreply@anthropic.com",
    )
    git(
        made,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "Credited\n\nCo-Authored-By: Claude <noreply@anthropic.com>",
    )
    git(
        made,
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "Session\n\nBody.\n\nClaude-Session: https://example.org/s",
    )
    git(made, "commit", "-q", "--allow-empty", "-m", "With a person\n\nCo-authored-by: Ada <ada@example.org>")
    assert credits(git(made, "log", "--reverse", LOG_FORMAT)) == [
        "By the tool: author Claude <noreply@anthropic.com>",
        "By the tool: committer Claude <noreply@anthropic.com>",
        "Credited: Co-Authored-By: Claude <noreply@anthropic.com>",
        "Session: Claude-Session: https://example.org/s",
    ]

    here = subprocess.run(["git", "-C", str(ROOT), "log", LOG_FORMAT], capture_output=True, text=True)
    if here.returncode != 0:
        pytest.skip("this checkout is no git repository")
    assert credits(here.stdout) == []
