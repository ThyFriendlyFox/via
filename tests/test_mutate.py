"""`workcenter mutate`: each mutation in a project's list, in its own copy of the firmware, must fail
the project's tests (PROCESSES.md P18 step 4).

The firmware is written by each test: a clamp in C with a host test that checks below, above and inside
the range, built by make with -Werror. Its build/ folder holds a stale test binary that always passes:
a copy that kept build/ would run it and let every mutation survive.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"

pytestmark = pytest.mark.skipif(
    shutil.which("cc") is None or shutil.which("make") is None,
    reason="a C compiler and make are not installed",
)

CLAMP = """#include "clamp.h"

int clamp(int v, int lo, int hi)
{
    if (v < lo)
        return lo;
    if (v > hi)
        return hi;
    return v;
}
"""
TEST = """#include <stdio.h>
#include "clamp.h"

static int failed;

static void check(int got, int want, const char *what)
{
    if (got != want) {
        printf("FAILED %s: %d, not %d\\n", what, got, want);
        failed = 1;
    }
}

int main(void)
{
    check(clamp(-1, 0, 10), 0, "below");
    check(clamp(11, 0, 10), 10, "above");
    check(clamp(5, 0, 10), 5, "inside");
    puts(failed ? "tests: failed" : "tests: passed");
    return failed;
}
"""
MAKEFILE = """.RECIPEPREFIX = >
test: build/test_clamp
> ./build/test_clamp
build/test_clamp: clamp.c clamp.h test_clamp.c
> mkdir -p build
> cc -Wall -Werror -o $@ clamp.c test_clamp.c
"""
MUTATIONS = [
    # caught: clamp(-1, 0, 10) returns -1
    {
        "name": "below not clamped",
        "file": "clamp.c",
        "old": "    if (v < lo)\n        return lo;\n",
        "new": "",
    },
    # survives: 10 is returned either way, and no test sits on the boundary
    {"name": "above from hi on", "file": "clamp.c", "old": "if (v > hi)", "new": "if (v >= hi)"},
    # does not build: proves nothing about the tests
    {"name": "a name not declared", "file": "clamp.c", "old": "return v;", "new": "return w;"},
]


def firmware(tmp_path: Path) -> Path:
    fw = tmp_path / "fw"
    (fw / "build").mkdir(parents=True)
    (fw / "clamp.c").write_text(CLAMP, encoding="utf-8")
    (fw / "clamp.h").write_text("int clamp(int v, int lo, int hi);\n", encoding="utf-8")
    (fw / "test_clamp.c").write_text(TEST, encoding="utf-8")
    (fw / "Makefile").write_text(MAKEFILE, encoding="utf-8")
    stale = fw / "build" / "test_clamp"
    stale.write_text("#!/bin/sh\necho stale\n", encoding="utf-8")
    stale.chmod(0o755)
    later = time.time() + 3600
    os.utime(stale, (later, later))  # newer than every source: make would not rebuild it
    return fw


def mutate(fw: Path, mutations: Path, *extra: object, json_out: bool = True) -> tuple[int, dict, str]:
    cmd = [
        sys.executable,
        str(CLI),
        *(["--json"] if json_out else []),
        "mutate",
        fw,
        "--mutations",
        mutations,
    ]
    proc = subprocess.run([*map(str, cmd), *map(str, extra)], capture_output=True, text=True, check=False)
    data = json.loads(proc.stdout) if json_out and proc.stdout.strip() else {}
    return proc.returncode, data, proc.stdout + proc.stderr


def test_each_mutation_is_caught_survives_or_does_not_build(tmp_path):
    fw = firmware(tmp_path)
    listed = tmp_path / "mutations.json"
    listed.write_text(json.dumps({"test": "make -k test", "mutations": MUTATIONS}), encoding="utf-8")
    sources = {p.name: p.read_bytes() for p in fw.rglob("*") if p.is_file()}
    code, data, text = mutate(fw, listed, "--jobs", "2")
    assert code == 1, text
    states = {m["name"]: m["state"] for m in data["mutations"]}
    assert states == {
        "below not clamped": "caught",
        "above from hi on": "survived",
        "a name not declared": "no build",
    }
    caught = next(m for m in data["mutations"] if m["state"] == "caught")
    assert caught["line"] == "FAILED below: -1, not 0"
    built = next(m for m in data["mutations"] if m["state"] == "no build")
    assert built["build_error"].startswith("clamp.c:9:12: error:") and "undeclared" in built["build_error"]
    assert data["counts"] == {"caught": 1, "survived": 1, "no build": 1}
    assert {
        p.name: p.read_bytes() for p in fw.rglob("*") if p.is_file()
    } == sources  # the tree is not written
    code, _, text = mutate(fw, listed, "--only", "below", json_out=False)
    assert code == 0, text
    assert text.splitlines()[-1].startswith("mutate: 1 mutations, 1 caught, 0 survived, 0 did not build")


def test_a_python_list_is_read_as_literals_and_its_copies_kept_with_work(tmp_path):
    fw = firmware(tmp_path)
    listed = tmp_path / "mutate.py"
    listed.write_text(
        "import sys\n"
        "TEST = 'make test'\n"
        "MUTATIONS = [\n"
        "    ('below not clamped', 'clamp.c', '    if (v < lo)\\n'\n"
        "     '        return lo;\\n', ''),\n"
        "]\n"
        "sys.exit(3)  # never run: the list is read as a literal\n",
        encoding="utf-8",
    )
    code, data, text = mutate(fw, listed, "--work", tmp_path / "work")
    assert code == 0, text
    assert data["test"] == "make test" and data["counts"]["caught"] == 1
    copy = tmp_path / "work" / "m000"
    assert "if (v < lo)" not in (copy / "clamp.c").read_text()
    assert (copy / "build" / "test_clamp").read_bytes()[
        :4
    ] == b"\x7fELF"  # built afresh, not the stale script


def test_anchors_are_checked_before_anything_runs(tmp_path):
    fw = firmware(tmp_path)
    listed = tmp_path / "mutations.json"
    twice = {"name": "every return", "file": "clamp.c", "old": "return", "new": "exit"}
    gone = {"name": "a file not there", "file": "nope.c", "old": "x", "new": "y"}
    listed.write_text(json.dumps([MUTATIONS[0], twice, gone]), encoding="utf-8")
    code, _, text = mutate(fw, listed, "--work", tmp_path / "work", json_out=False)
    assert code == 1
    assert "anchor: every return: clamp.c holds the old text 3 times" in text
    assert "anchor: a file not there: nope.c is not there" in text
    assert not (tmp_path / "work").exists()  # nothing ran
    listed.write_text(json.dumps(MUTATIONS[:1]), encoding="utf-8")
    code, _, text = mutate(fw, listed, "--test", "make test && false", json_out=False)
    assert code == 1 and "fails before any mutation" in text
    listed.write_text(json.dumps([{"name": "x", "file": "clamp.c"}]), encoding="utf-8")
    code, _, text = mutate(fw, listed, json_out=False)
    assert code == 1 and "needs name, file, old and new" in text
