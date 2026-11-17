"""`workcenter procure` on a parts file whose row holds fewer or more fields than its header.

csv.DictReader fills a short row's missing fields with None and puts a long row's extra fields under
the key None. The reader called `.strip()` on None and the command ended in an AttributeError. A row
that does not fit its header is refused with its file and its line.
"""

from __future__ import annotations

import shutil

import pytest
from test_gates import BOARDS, PARTS, load_cli_module, parts_file, run

HEADER = PARTS.splitlines()[0]  # 13 columns


def test_a_short_row_is_refused_with_its_file_and_line(tmp_path):
    """The header names 13 fields, line 3 holds 3: `100n,C_0603,1`."""
    cli = load_cli_module()
    path = parts_file(tmp_path, PARTS.replace(PARTS.splitlines()[2], "100n,C_0603,1"))  # line 3, index 2
    with pytest.raises(ValueError) as caught:
        cli.read_parts(path)
    assert str(caught.value) == "parts.csv:3: 3 fields, and the header names 13"


def test_a_long_row_is_refused_with_its_file_and_line(tmp_path):
    """Line 2 holds the 13 fields of the header and 2 more: 15."""
    cli = load_cli_module()
    first = PARTS.splitlines()[1]
    path = parts_file(tmp_path, PARTS.replace(first, first + ",x,y"))
    with pytest.raises(ValueError) as caught:
        cli.read_parts(path)
    assert str(caught.value) == "parts.csv:2: 15 fields, and the header names 13"


@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
def test_procure_on_a_row_of_3_fields_is_an_error_that_names_the_line(tmp_path):
    """The whole command: an error record, not a traceback."""
    path = parts_file(tmp_path, f"{HEADER}\n100n,C_0603,1\n")
    code, records = run("procure", BOARDS / "pass-rc-divider", "--out", tmp_path / "out", "--parts", path)
    assert code == 1, records
    assert records[0]["status"] == "error"
    assert records[0]["summary"] == "parts.csv:2: 3 fields, and the header names 13"
