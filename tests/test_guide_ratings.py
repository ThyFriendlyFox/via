"""`workcenter next` on a ratings run that refused a file: each kind of refusal has its own hint.

A refusal names the file before its fault. Before these hints, a parts file's row, a schematic and an
output folder got the general hint (read the report, which says nothing was judged), and a refusal of
ratings.json was sent to the skill's section on a part's facts. Each line here is one the command
prints, after `ratings: `.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import guide  # noqa: E402

RATINGS = ".claude/skills/ratings/SKILL.md"


@pytest.mark.parametrize(
    ("line", "said", "read"),
    [
        # parts_rows() in tools/ratings.py
        ("parts.csv:2: 3 fields, and the header names 13", "every field its header names", '"Inputs"'),
        # export_netlist(): the netlist reader's refusal, named by the schematic
        (
            "rc_divider.kicad_sch: net GND names R9, which is no part of the netlist",
            "Correct the schematic",
            '"Inputs"',
        ),
        # cmd_ratings(): --out names a file, or the default folder cannot be made
        ("--out /tmp/x/out.txt: a file stands there, and a folder is asked", "--out", '"Steps"'),
        ("/home/me/board/build: Permission denied", "--out", '"Steps"'),
        # read_project()
        (
            "ratings.json: `speed` is no key here; the keys are pack, nets",
            "Correct the file",
            '"ratings.json"',
        ),
    ],
)
def test_a_refusal_is_answered_by_the_file_it_names(line, said, read):
    do, where = guide.hint("ratings", line)
    assert said in do, do
    assert where == f"{RATINGS}, {read}"


def test_a_facts_file_s_refusal_still_goes_to_a_part_s_facts():
    do, where = guide.hint("ratings", "ti-tps62162.json: entry 1: pins: `role` is missing")
    assert do.startswith("Correct the file")
    assert where == f'{RATINGS}, "A part\'s facts"'
