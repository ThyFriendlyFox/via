"""The mutation list of the ratings engine holds to the engine as it is (PROCESSES.md P18 step 6).

`make mutate-ratings` runs the list, which takes minutes; this file runs in `make verify` and fails as
soon as an edit of `tools/ratings.py` moves an anchor, so the list is fixed in the same commit. A
mutation that does not compile would fail the tests for that alone and count as caught: each must
compile.
"""

from __future__ import annotations

import ast
import re

import pytest
from test_gates import ROOT, load_cli_module

LIST = ROOT / "tests" / "ratings_mutations.py"
CLI = load_cli_module()
MUTATIONS, TEST, COPY = CLI.read_mutation_list(LIST)


def literal(name: str):
    """A top-level name of the list, read as the command reads it."""
    for node in ast.parse(LIST.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and node.targets[0].id == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{LIST.name} has no {name}")


def test_the_list_names_its_test_files_and_the_paths_a_copy_holds():
    for path in re.findall(r"tests/\S+\.py", TEST):
        assert (ROOT / path).is_file(), path
    assert "tests/test_ratings.py" in TEST and "tests/test_ratings_edges.py" in TEST
    for path in COPY:
        assert (ROOT / path).exists(), path


def test_no_mutation_the_list_runs_is_one_it_calls_equivalent_or_gone():
    names = {m["name"].split()[0] for m in MUTATIONS}
    assert len(names) == len(MUTATIONS)
    assert not names & set(literal("EQUIVALENT")), names & set(literal("EQUIVALENT"))
    assert not names & set(literal("GONE"))
    assert all(why for why in {**literal("EQUIVALENT"), **literal("GONE")}.values())


@pytest.mark.parametrize("mutation", MUTATIONS, ids=[m["name"].split()[0] for m in MUTATIONS])
def test_each_anchor_stands_once_in_the_engine_and_its_change_compiles(mutation):
    text = (ROOT / mutation["file"]).read_text(encoding="utf-8")
    assert text.count(mutation["old"]) == 1, (
        f"{mutation['name']}: the old text stands {text.count(mutation['old'])} times"
    )
    compile(text.replace(mutation["old"], mutation["new"], 1), mutation["file"], "exec")
