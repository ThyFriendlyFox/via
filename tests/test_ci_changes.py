"""A change's changelog line in a file of its own (tools/ci/changes.py, ee-agent-kit/changes/).

On 2026-11-19 `main` moved under an open pull request 5 times, and each time the pull request
conflicted in `ee-agent-kit/CHANGELOG.md` alone: both sides added a line at the top of
`## [Unreleased]` (M279). A change now adds 1 file under `ee-agent-kit/changes/`; a release folds
the files into CHANGELOG.md. A line written straight under `## [Unreleased]` stays valid, so every
reader reads both places. The script runs here on a folder of each test's own.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "ci" / "changes.py"

CHANGELOG = """\
# Changelog

All notable changes are documented here.

## [Unreleased]
### Changed
- An old line under Unreleased.
### Fixed
- An old fix under Unreleased.

## [0.1.0] - 2026-11-19
### Added
- The first release's line.
"""

README = "# Change files\n\nThe rule.\n"


def tree(tmp_path: Path, files: dict[str, str], changelog: str = CHANGELOG) -> Path:
    kit = tmp_path / "ee-agent-kit"
    (kit / "changes").mkdir(parents=True)
    (kit / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    (kit / "changes" / "README.md").write_text(README, encoding="utf-8")
    for name, text in files.items():
        (kit / "changes" / name).write_text(text, encoding="utf-8")
    return tmp_path


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--root", str(root), *args], capture_output=True, text=True
    )


def snapshot(root: Path) -> dict[str, str]:
    kit = root / "ee-agent-kit"
    return {
        str(p.relative_to(root)): p.read_text(encoding="utf-8") for p in sorted(kit.rglob("*")) if p.is_file()
    }


GOOD = {
    "2026-11-19-changes-folder.md": "### Added\n- A change writes its line in a file of its own.\n",
    "2026-11-20-quiet-fix.md": (
        "### Fixed\n- The quiet check leaves out a sleeping script.\n- And a second line.\n"
    ),
}
IN = "this line is already in ee-agent-kit/CHANGELOG.md"


# ---------------------------------------------------------------- check


def test_check_passes_well_formed_files_and_the_folder_readme_is_not_a_change_file(tmp_path):
    root = tree(tmp_path, GOOD)
    done = run(root, "check")
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout == "changes: 2 files, 3 lines; ok\n"


def test_check_names_the_file_and_line_of_each_fault(tmp_path):
    root = tree(
        tmp_path,
        {
            "2026-11-19-heading.md": "### Improved\n- A line.\n",
            "2026-11-19-empty.md": "### Added\n",
            "2026-11-19-prose.md": "### Changed\n- A line.\n\nSome prose.\n",
            "2026-11-19-bare.md": "### Changed\n- \n",
            "2026-11-19-again.md": "### Changed\n- A fresh line.\n- An old line under Unreleased.\n",
            "2026-11-19-released.md": "### Added\n- The first release's line.\n",
        },
    )
    done = run(root, "check")
    assert done.returncode == 1
    lines = done.stdout.splitlines()
    assert lines[:-1] == [
        f"ee-agent-kit/changes/2026-11-19-again.md:3: {IN}, line 7",
        "ee-agent-kit/changes/2026-11-19-bare.md:2: a '- ' line with no words",
        "ee-agent-kit/changes/2026-11-19-empty.md:1: no '- ' line under the heading",
        "ee-agent-kit/changes/2026-11-19-heading.md:1: the first line is '### Improved'; it must be 1 of "
        "### Added, ### Changed, ### Deprecated, ### Removed, ### Fixed, ### Security",
        "ee-agent-kit/changes/2026-11-19-prose.md:3: not a '- ' line: ''",
        "ee-agent-kit/changes/2026-11-19-prose.md:4: not a '- ' line: 'Some prose.'",
        f"ee-agent-kit/changes/2026-11-19-released.md:2: {IN}, line 13",
    ]
    assert lines[-1] == "changes: 7 faults in 6 files (ee-agent-kit/changes/README.md says the form)"


def test_check_refuses_a_name_out_of_the_form(tmp_path):
    root = tree(
        tmp_path,
        {
            "changes-folder.md": "### Added\n- A.\n",
            "2026-13-01-month.md": "### Added\n- B.\n",
            "2026-11-19-Upper.md": "### Added\n- C.\n",
            "2026-11-19-note.txt": "### Added\n- D.\n",
            "2026-11-19-.md": "### Added\n- E.\n",
        },
    )
    done = run(root, "check")
    assert done.returncode == 1
    form = "the name is not <yyyy-mm-dd>-<slug>.md (slug: a-z, 0-9 and -)"
    assert done.stdout.splitlines()[:-1] == [
        f"ee-agent-kit/changes/2026-11-19-.md:1: {form}",
        f"ee-agent-kit/changes/2026-11-19-Upper.md:1: {form}",
        f"ee-agent-kit/changes/2026-11-19-note.txt:1: {form}",
        "ee-agent-kit/changes/2026-13-01-month.md:1: the name's date 2026-13-01 is not a day",
        f"ee-agent-kit/changes/changes-folder.md:1: {form}",
    ]


def test_check_reads_the_unreleased_section_as_a_release_will(tmp_path):
    """fold takes CHANGELOG.md's Unreleased lines too: a line there with no heading above it, or a
    heading that is not Keep a Changelog's, would stop the release. check says so first."""
    bad = CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n- A line with no heading.\n").replace(
        "### Fixed\n", "### Improved\n"
    )
    done = run(tree(tmp_path, {}, changelog=bad), "check")
    assert done.returncode == 1
    assert done.stdout.splitlines()[:-1] == [
        "ee-agent-kit/CHANGELOG.md:6: a '- ' line under no heading of ## [Unreleased]",
        "ee-agent-kit/CHANGELOG.md:9: '### Improved' is not 1 of ### Added, ### Changed, ### Deprecated, "
        "### Removed, ### Fixed, ### Security",
    ]
    gone = run(tree(tmp_path / "b", {}, changelog=CHANGELOG.replace("## [Unreleased]\n", "")), "check")
    assert gone.returncode == 1
    assert gone.stdout.splitlines()[0] == "ee-agent-kit/CHANGELOG.md:1: no '## [Unreleased]' line"


def test_check_on_this_repository_passes_well_under_a_second():
    t0 = time.monotonic()
    done = subprocess.run([sys.executable, str(SCRIPT), "check"], capture_output=True, text=True)
    seconds = time.monotonic() - t0
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout.startswith("changes: ") and done.stdout.endswith("; ok\n")
    assert seconds < 1.0, seconds


def test_the_kit_checks_of_both_gates_run_check():
    """verify.sh's kit_checks runs in `make verify` (step 2/4) and in `make verify-site` (step 4/4)."""
    text = (ROOT / "verify" / "verify.sh").read_text(encoding="utf-8")
    body = text.split("kit_checks() {", 1)[1].split('echo "kit checks ok"', 1)[0]
    assert "python3 tools/ci/changes.py check" in body
    assert text.count("\nkit_checks\n") == 1 and text.count("\n  kit_checks\n") == 1


# ---------------------------------------------------------------- show


def test_show_prints_the_unreleased_lines_of_both_places_under_their_headings_newest_first(tmp_path):
    root = tree(
        tmp_path,
        {
            **GOOD,
            "2026-11-21-later.md": "### Fixed\n- The newest fix.\n",
            "2026-11-18-older.md": "### Changed\n- An older change file's line.\n",
        },
    )
    done = run(root, "show")
    assert done.returncode == 0, done.stdout + done.stderr
    assert done.stdout == (
        "## [Unreleased]\n"
        "### Added\n"
        "- A change writes its line in a file of its own.\n"
        "### Changed\n"
        "- An older change file's line.\n"
        "- An old line under Unreleased.\n"
        "### Fixed\n"
        "- The newest fix.\n"
        "- The quiet check leaves out a sleeping script.\n"
        "- And a second line.\n"
        "- An old fix under Unreleased.\n"
    )


def test_show_with_nothing_unreleased_prints_the_heading_alone(tmp_path):
    empty = (
        CHANGELOG.split("## [Unreleased]\n")[0]
        + "## [Unreleased]\n\n## [0.1.0]"
        + CHANGELOG.split("## [0.1.0]")[1]
    )
    done = run(tree(tmp_path, {}, changelog=empty), "show")
    assert (done.returncode, done.stdout) == (0, "## [Unreleased]\n")


# ---------------------------------------------------------------- fold


def test_fold_writes_the_release_leaves_an_empty_unreleased_and_deletes_the_folded_files(tmp_path):
    root = tree(tmp_path, GOOD)
    done = run(root, "fold", "0.2.0", "2026-11-20")
    assert done.returncode == 0, done.stdout + done.stderr
    text = (root / "ee-agent-kit" / "CHANGELOG.md").read_text(encoding="utf-8")
    assert text == (
        "# Changelog\n"
        "\n"
        "All notable changes are documented here.\n"
        "\n"
        "## [Unreleased]\n"
        "\n"
        "## [0.2.0] - 2026-11-20\n"
        "### Added\n"
        "- A change writes its line in a file of its own.\n"
        "### Changed\n"
        "- An old line under Unreleased.\n"
        "### Fixed\n"
        "- The quiet check leaves out a sleeping script.\n"
        "- And a second line.\n"
        "- An old fix under Unreleased.\n"
        "\n"
        "## [0.1.0] - 2026-11-19\n"
        "### Added\n"
        "- The first release's line.\n"
    )
    left = sorted(p.name for p in (root / "ee-agent-kit" / "changes").iterdir())
    assert left == ["README.md"]
    assert done.stdout == (
        "fold: ## [0.2.0] - 2026-11-20 holds 5 lines, 2 from CHANGELOG.md and 3 from 2 change files\n"
        "fold: deleted ee-agent-kit/changes/2026-11-19-changes-folder.md\n"
        "fold: deleted ee-agent-kit/changes/2026-11-20-quiet-fix.md\n"
    )
    assert run(root, "check").returncode == 0


def test_fold_a_second_time_changes_nothing(tmp_path):
    root = tree(tmp_path, GOOD)
    assert run(root, "fold", "0.2.0", "2026-11-20").returncode == 0
    before = snapshot(root)
    again = run(root, "fold", "0.2.0", "2026-11-20")
    assert again.returncode == 0, again.stdout + again.stderr
    assert again.stdout == "fold: ## [0.2.0] is there and nothing is unreleased; nothing changed\n"
    assert snapshot(root) == before


def test_fold_refuses_a_version_that_is_already_there(tmp_path):
    root = tree(tmp_path, GOOD)
    before = snapshot(root)
    done = run(root, "fold", "0.1.0", "2026-11-20")
    assert done.returncode == 1
    assert done.stdout == "fold: ee-agent-kit/CHANGELOG.md already has ## [0.1.0]; nothing changed\n"
    assert snapshot(root) == before


def test_fold_refuses_a_bad_version_a_bad_date_nothing_to_fold_and_a_failed_check(tmp_path):
    root = tree(tmp_path, GOOD)
    before = snapshot(root)
    bad_version = run(root, "fold", "v0.2", "2026-11-20")
    assert (bad_version.returncode, bad_version.stdout) == (
        1,
        "fold: the version 'v0.2' is not X.Y.Z; nothing changed\n",
    )
    bad_date = run(root, "fold", "0.2.0", "2026-02-30")
    assert (bad_date.returncode, bad_date.stdout) == (
        1,
        "fold: the date '2026-02-30' is not a day; nothing changed\n",
    )
    assert snapshot(root) == before

    empty = (
        CHANGELOG.split("## [Unreleased]\n")[0]
        + "## [Unreleased]\n\n## [0.1.0]"
        + CHANGELOG.split("## [0.1.0]")[1]
    )
    nothing = run(tree(tmp_path / "b", {}, changelog=empty), "fold", "0.2.0", "2026-11-20")
    assert (nothing.returncode, nothing.stdout) == (1, "fold: nothing is unreleased; nothing changed\n")

    faulty = tree(tmp_path / "c", {"2026-11-19-x.md": "### Improved\n- A line.\n"})
    before = snapshot(faulty)
    refused = run(faulty, "fold", "0.2.0", "2026-11-20")
    assert refused.returncode == 1
    assert refused.stdout.splitlines()[-1] == "fold: check failed; nothing changed"
    assert snapshot(faulty) == before


# ---------------------------------------------------------------- the rule's text


def test_every_place_that_tells_a_contributor_to_write_a_changelog_line_names_the_change_files():
    """The places of 2026-11-19 that told a contributor to write under `## [Unreleased]`. The shared
    documents (PROCESSES.md, STATUS.md) are the integrator's and are not held here."""
    places = (
        "ee-agent-kit/RELEASING.md",
        "ee-agent-kit/MAINTENANCE.md",
        "ee-agent-kit/WEEKLY.md",
        "ee-agent-kit/SETUP.md",
        "ee-agent-kit/ROUTING.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        "ee-agent-kit/skills/lead/SKILL.md",
        "ee-agent-kit/skills/blog-post/SKILL.md",
        "ee-agent-kit/lead/workflows/roadmap-lane.js",
        "ee-agent-kit/lead/workflows/second-attack.js",
    )
    lacking = [p for p in places if "ee-agent-kit/changes/" not in (ROOT / p).read_text(encoding="utf-8")]
    assert lacking == []
    assert "tools/ci/changes.py fold" in (ROOT / "ee-agent-kit" / "RELEASING.md").read_text(encoding="utf-8")
    for name in ("lead", "blog-post"):
        kit = ROOT / "ee-agent-kit" / "skills" / name / "SKILL.md"
        assert kit.read_bytes() == (ROOT / ".claude" / "skills" / name / "SKILL.md").read_bytes(), name


def test_the_folder_readme_says_the_rule_in_10_lines_or_fewer():
    text = (ROOT / "ee-agent-kit" / "changes" / "README.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 10
    for word in ("<yyyy-mm-dd>-<slug>.md", "### Added", "tools/ci/changes.py", "fold"):
        assert word in text, word


def test_the_module_reads_the_lines_of_both_places_for_other_readers(tmp_path):
    """tests/test_docs.py reads the roadmap pointers of the Unreleased lines through `unreleased_texts`."""
    spec = importlib.util.spec_from_file_location("changes", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tree(tmp_path, GOOD)
    texts = module.unreleased_texts(root)
    assert [rel for rel, _ in texts] == [
        "ee-agent-kit/CHANGELOG.md",
        "ee-agent-kit/changes/2026-11-20-quiet-fix.md",
        "ee-agent-kit/changes/2026-11-19-changes-folder.md",
    ]
    assert texts[0][1] == CHANGELOG
