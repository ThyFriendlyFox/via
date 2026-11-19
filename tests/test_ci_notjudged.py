"""ee-agent-kit/CI.md's section "What GitHub does not judge" against a collection made as on GitHub.

On 2026-11-19 a test that needs root was skipped by its mark on GitHub and failed wherever it ran (M307).
The section counts, file by file, the tests a mark skips on a runner of GitHub's `full` job. Here the
suite is collected with `-p github_full` (verify/github_full.py: user id 1001, no chip folder and no chip
engine on PATH, no FreeRouting 2.5.0, no WORKCENTER_TEST_IMAGE_BUILD) and `-p testshards`, which writes
each test's skip marks as evaluated in that process. No test runs and no engine starts. A new skipif
that holds on GitHub makes the first test fail and name its file, so the section changes with it.
"""

from __future__ import annotations

import collections
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "verify"))
import github_full  # noqa: E402
import kicadgen  # noqa: E402

CI = ROOT / "ee-agent-kit" / "CI.md"
TITLE = "## What GitHub does not judge"
ROW = re.compile(r"^\| `(tests/[\w/]+\.py)` \| (\d+) \| (\d+) \|$")
ALL = re.compile(r"^\| all \| (\d+) \| (\d+) \|$")

# The collection must see what GitHub's `full` runner has, apart from what the plugin takes away: the
# fast lane (`make verify-site`) hides KiCad's libraries and refuses engines, and a machine with no
# kicad-cli lacks them.
like_full = pytest.mark.skipif(
    shutil.which("kicad-cli") is None
    or not (kicadgen.SYMBOL_DIR / "Device.kicad_sym").is_file()
    or bool(os.environ.get("WORKCENTER_NO_ENGINES")),
    reason="GitHub's full job has kicad-cli and KiCad's symbol libraries, and refuses no engine",
)


def section() -> str:
    text = CI.read_text(encoding="utf-8")
    assert TITLE in text, f"{CI} has no section {TITLE!r}"
    return text.split(TITLE, 1)[1].split("\n## ", 1)[0]


def stated() -> tuple[dict[str, tuple[int, int]], tuple[int, int]]:
    """The section's table: each file's tests skipped by a mark and inside the test, and its row `all`."""
    rows, total = {}, None
    for line in section().splitlines():
        m = ROW.match(line)
        if m:
            rows[m.group(1)] = (int(m.group(2)), int(m.group(3)))
        m = ALL.match(line)
        if m:
            total = (int(m.group(1)), int(m.group(2)))
    assert rows and total, f"{CI}, {TITLE!r}: no table of files with a row `all`"
    return rows, total


def collect(root: Path, log: Path, tests: str = "tests", env: dict | None = None) -> list[dict]:
    """`pytest --collect-only` in `root` as on GitHub's full runner: each collected test's record.

    The collection runs no test. A module's probe as it is collected (test_copper.py's `import pcbnew`)
    is no test's engine, as tools/ci/engine_marker.py says: the child writes its own log of engine starts
    beside `log`, not this test's."""
    base = dict(os.environ if env is None else env)
    for name in [k for k in base if k.startswith("TESTSHARDS_")]:
        del base[name]
    base["TESTSHARDS_LOG"] = str(log)
    base["WORKCENTER_ENGINE_LOG"] = str(log.with_suffix(".engines.log"))
    base["PYTHONPATH"] = os.pathsep.join(p for p in (str(ROOT / "verify"), base.get("PYTHONPATH", "")) if p)
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "github_full", "-p", "testshards"]
    cmd += ["-p", "no:cacheprovider", tests]
    ran = subprocess.run(cmd, cwd=root, env=base, capture_output=True, text=True, timeout=600, check=False)
    assert ran.returncode == 0, ran.stdout[-3000:] + ran.stderr[-3000:]
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
    return [rec for rec in records if "collected" in rec]


@like_full
def test_the_sections_counts_are_the_tests_a_mark_skips_on_githubs_full_job(tmp_path):
    """File by file, the tests whose marks skip them as on GitHub's full runner, against the table."""
    records = collect(ROOT, tmp_path / "log.jsonl")
    assert not any("marks" in rec for rec in records), "this pytest cannot evaluate skip marks"
    skipped = [rec for rec in records if rec.get("skip") is not None]
    got = collections.Counter(rec["collected"].split("::")[0] for rec in skipped)
    rows, _ = stated()
    wrong = []
    for name in sorted(set(got) | set(rows)):
        said = rows.get(name, (0, 0))[0]
        if got[name] != said:
            reasons = sorted({rec["skip"] for rec in skipped if rec["collected"].startswith(f"{name}::")})
            wrong.append(
                f"{name}: {got[name]} skipped by a mark as on GitHub's full job, CI.md says {said}; "
                f"reasons: {'; '.join(r[:120] for r in reasons[:3])}"
            )
    assert wrong == [], f"correct {CI}, {TITLE!r}, in the same change:\n" + "\n".join(wrong)


def test_the_sections_row_all_and_its_sum_are_its_rows_added():
    """The row `all` adds the rows, and the prose's sum (`66 + 3 = 69`) is that row's."""
    rows, (marks, inside) = stated()
    assert sum(m for m, _ in rows.values()) == marks
    assert sum(i for _, i in rows.values()) == inside
    assert f"{marks} + {inside} = {marks + inside}" in section()


def test_the_plugin_hides_each_chip_engine_the_chip_flow_looks_for():
    import chipflow

    assert set(github_full.CHIP_ENGINES) == set(chipflow.ENGINES)


CONDITIONS = """import os
import shutil
from pathlib import Path

import pytest


@pytest.mark.skipif(os.geteuid() != 0, reason="root")
def test_root():
    pass


@pytest.mark.skipif(os.getuid() != 0, reason="root by getuid")
def test_root_by_getuid():
    pass


@pytest.mark.skipif(shutil.which("verilator") is None, reason="verilator")
def test_verilator():
    pass


@pytest.mark.skipif(shutil.which("netgen") is None, reason="netgen")
def test_netgen():
    pass


@pytest.mark.skipif(
    not Path(os.environ.get("WORKCENTER_CHIP_TOOLS") or "/opt/workcenters/ee/chip").is_dir(), reason="chip"
)
def test_chip_folder():
    pass


@pytest.mark.skipif(not Path(os.environ.get("FREEROUTING2_JAR", "")).is_file(), reason="freerouting2")
def test_freerouting2():
    pass


@pytest.mark.skipif(os.environ.get("WORKCENTER_TEST_IMAGE_BUILD") != "1", reason="image build")
def test_image_build():
    pass


@pytest.mark.skipif(shutil.which("sh") is None, reason="sh")
def test_sh():
    pass
"""


def test_the_plugin_makes_the_process_look_like_githubs_full_runner_whatever_this_machine_is(tmp_path):
    """Each condition of GitHub's full runner, against a machine that is root, has the chip folder, a
    verilator and a netgen on PATH, FreeRouting 2.5.0 and WORKCENTER_TEST_IMAGE_BUILD=1: every test of
    the 7 is skipped. A tool GitHub has (sh) stays."""
    root = tmp_path / "proj"
    (root / "tests").mkdir(parents=True)
    (root / "tests" / "test_conditions.py").write_text(CONDITIONS, encoding="utf-8")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("verilator", "netgen"):
        (bin_dir / name).write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (bin_dir / name).chmod(0o755)
    (tmp_path / "chip").mkdir()
    jar = tmp_path / "freerouting.jar"
    jar.write_bytes(b"")
    env = dict(os.environ)
    env.update(
        PATH=f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
        WORKCENTER_CHIP_TOOLS=str(tmp_path / "chip"),
        FREEROUTING2_JAR=str(jar),
        WORKCENTER_TEST_IMAGE_BUILD="1",
    )
    records = collect(root, tmp_path / "log.jsonl", env=env)
    skips = {rec["collected"].split("::")[1]: rec.get("skip") for rec in records}
    assert skips == {
        "test_root": "root",
        "test_root_by_getuid": "root by getuid",
        "test_verilator": "verilator",
        "test_netgen": "netgen",
        "test_chip_folder": "chip",
        "test_freerouting2": "freerouting2",
        "test_image_build": "image build",
        "test_sh": None,
    }
