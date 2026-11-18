"""`workcenter references` on a web page: held by the values read from it on a date, not by a SHA256.

A local server plays 2 fab pages. Each answer of the first carries a new session token, as Samsung's
part page does: its bytes differ on every fetch and its number stands. The second page's number moved
from 4 mil to 5 mil since the index read it. `fetch` keeps the first on every run and names the second
`moved`, with the value that is gone.
"""

from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"

SAYS = "Minimum trace 4 mil (0.1016 mm)"
RULE = "fab: trace 4 mil, made up for the tests"


def run(*args: object) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "references", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    return proc.returncode, proc.stdout + proc.stderr


class Fab(http.server.BaseHTTPRequestHandler):
    """/token.html: the value in tags, and a new token on each answer. /moved.html: the value moved."""

    asked: dict[str, int] = {}

    def do_GET(self):  # noqa: N802 (the handler's name is http.server's)
        Fab.asked[self.path] = Fab.asked.get(self.path, 0) + 1
        if self.path == "/token.html":
            body = (
                "<html><body><td>Minimum trace</td>\n  <td><b>4 mil</b> (0.1016&nbsp;mm)</td>"
                f'<input name="session" value="{Fab.asked[self.path]:08d}"></body></html>'
            ).encode()
        elif self.path == "/moved.html":
            body = b"<html><body><td>Minimum trace</td><td>5 mil (0.127 mm)</td></body></html>"
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def page(doc_id: str, url: str) -> dict:
    return {
        "id": doc_id,
        "kind": "web page",
        "maker": "A fab made up for the tests",
        "title": "Capabilities, a page made up for the tests",
        "url": url,
        "read": "2026-11-17",
        "values": [{"says": SAYS, "for": RULE}],
    }


@pytest.fixture
def fab(tmp_path):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Fab)
    Fab.asked = {}
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    index = tmp_path / "index.json"
    docs = [page("fab-token", f"{base}/token.html"), page("fab-moved", f"{base}/moved.html")]
    index.write_text(json.dumps({"documents": docs}), encoding="utf-8")
    try:
        yield index, tmp_path / "refs", base
    finally:
        server.shutdown()


def test_fetch_keeps_a_page_whose_token_moves_and_names_one_whose_number_moved(fab):
    """Run 1 asks both pages: token.html is kept, moved.html is moved. Run 2 asks token.html again
    (--again): its bytes differ (token 00000002 for 00000001), and it is kept again. moved.html is asked
    1 time in all."""
    index, refs, base = fab
    code, out = run("fetch", "--index", index, "--to", refs, "--json")
    first = json.loads(out)
    assert code == 1
    assert {d["id"]: d["state"] for d in first["documents"]} == {"fab-token": "kept", "fab-moved": "moved"}
    code, out = run("fetch", "--index", index, "--to", refs, "--json", "--again", "fab-token")
    second = json.loads(out)
    assert {d["id"]: d["state"] for d in second["documents"]} == {"fab-token": "kept", "fab-moved": "moved"}
    shas = [r["documents"][0]["sha256"] for r in (first, second)]
    assert shas[0] != shas[1]
    assert Fab.asked == {"/token.html": 2, "/moved.html": 1}


def test_fetch_prints_what_moved_and_what_holds(fab):
    index, refs, base = fab
    code, out = run("fetch", "--index", index, "--to", refs)
    lines = out.splitlines()
    assert code == 1
    assert lines[0].startswith(
        "kept fab-token: a web page, held by its values: all 1 read on 2026-11-17 stand on it; its bytes "
        "are not judged ["
    )
    assert lines[1].startswith(
        f'moved fab-moved: {base}/moved.html no longer says "{SAYS}" ({RULE}), read on 2026-11-17; '
        "1 of 1 values gone; the copy is in "
    )
    assert lines[1].endswith(": read the page, change each rule that took the value, then the entry's values")
    assert lines[-1] == (
        "references fetch: 1 kept, 0 changed, 1 moved, 0 refused, 0 gone, 0 not given, 0 not reached; "
        "2 asked now"
    )


def test_check_judges_a_saved_page_by_its_values(fab, tmp_path):
    index, refs, base = fab
    held = tmp_path / "held.html"
    held.write_text("<p>Minimum trace <i>4 mil</i> (0.1016 mm)</p><p>session 77</p>", encoding="utf-8")
    code, out = run("check", held, "--id", "fab-token", "--index", index)
    assert code == 0, out
    assert out.splitlines() == [
        f"same {held}: fab-token, a web page: all 1 values read on 2026-11-17 stand in it"
    ]
    gone = tmp_path / "gone.html"
    gone.write_text("<p>Minimum trace 5 mil (0.127 mm)</p>", encoding="utf-8")
    code, out = run("check", gone, "--id", "fab-token", "--index", index)
    assert code == 1
    assert out.splitlines() == [f'moved {gone}: no longer says "{SAYS}" ({RULE}), read on 2026-11-17']


@pytest.mark.parametrize(
    ("change", "fault"),
    [
        ({"sha256": "1" * 64}, "a web page is held by its values, not by a SHA256; drop sha256"),
        (
            {"values": []},
            'no values: a web page is held by the values read from it, as [{"says": "...", "for": "..."}]',
        ),
        ({"values": [{"says": "4 mil"}]}, 'values[0]: "says" and "for" are asked, each a text'),
    ],
)
def test_the_index_refuses_a_web_page_entry_of_the_wrong_form(tmp_path, change, fault):
    index = tmp_path / "index.json"
    index.write_text(
        json.dumps({"documents": [page("fab-x", "https://fab.example/x") | change]}), encoding="utf-8"
    )
    code, out = run("fetch", "--index", index, "--to", tmp_path / "refs")
    assert code == 1
    assert out.splitlines() == [f"fail {index} documents[0] fab-x: {fault}"]


def check_says(tmp_path: Path, says: str, html: str) -> tuple[int, list[str]]:
    """`check` a saved page against 1 entry whose only value is `says`."""
    index = tmp_path / "index.json"
    entry = page("fab-x", "https://fab.example/x") | {"values": [{"says": says, "for": RULE}]}
    index.write_text(json.dumps({"documents": [entry]}), encoding="utf-8")
    saved = tmp_path / "saved.html"
    saved.write_text(html, encoding="utf-8")
    code, out = run("check", saved, "--id", "fab-x", "--index", index)
    return code, out.splitlines()


SPLIT = "Min. track width and spacing (1 oz) ... 1- and 2-layer: 0.10 / 0.10 mm (4 / 4 mil)"


@pytest.mark.parametrize(
    ("says", "html", "verdict"),
    [
        # The 1 oz row grew to 0.127 mm; the old 0.10 mm stands only in a later row. Before the fix the
        # second part was found anywhere after the first: same.
        (
            SPLIT,
            "<table><tr><td>Min. track width and spacing (1 oz)</td><td>1- and 2-layer: 0.127 / 0.127 mm "
            "(5 / 5 mil)</td></tr><tr><td>Min. track width and spacing (inner layer, 0.5 oz)</td><td>1- and "
            "2-layer: 0.10 / 0.10 mm (4 / 4 mil)</td></tr></table>",
            "moved",
        ),
        (
            SPLIT,
            "<table><tr><td>Min. track width and spacing (1 oz)</td><td>1- and 2-layer: 0.10 / 0.10 mm "
            "(4 / 4 mil)</td></tr></table>",
            "same",
        ),
        # The parts out of order. Before the fix with `text.find(part)` from 0 this read same.
        ("Minimum trace ... 4 mil (0.1016 mm)", "<p>4 mil (0.1016 mm)</p><p>Minimum trace</p>", "moved"),
        # Gaps in the page's text: "Minimum trace" + " " + x * k + " " + "4 mil": k + 2 characters, 200 at
        # most (GAP_REACH). k = 198 gives 200, k = 199 gives 201.
        (
            "Minimum trace ... 4 mil (0.1016 mm)",
            f"<p>Minimum trace</p><p>{'x' * 198}</p><p>4 mil (0.1016 mm)</p>",
            "same",
        ),
        (
            "Minimum trace ... 4 mil (0.1016 mm)",
            f"<p>Minimum trace</p><p>{'x' * 199}</p><p>4 mil (0.1016 mm)</p>",
            "moved",
        ),
        # A value that ends in a digit stands only where the page's number ends: 0.2 is not 0.25.
        ("Minimum drill 0.2", "<p>Minimum drill 0.25 mm</p>", "moved"),
        ("Minimum drill 0.2", "<p>Minimum drill 0.2 mm</p>", "same"),
        # ... and one that starts with a digit only where the page's number starts: 4 mil is not 14 mil.
        ("4 mil minimum trace", "<p>14 mil minimum trace</p>", "moved"),
    ],
)
def test_a_value_stands_only_in_order_near_and_at_the_numbers_bounds(tmp_path, says, html, verdict):
    code, lines = check_says(tmp_path, says, html)
    assert (code, lines[0].split(" ")[0]) == ((1, "moved") if verdict == "moved" else (0, "same")), lines


@pytest.mark.parametrize("says", ["...", " ... ", "... ..."])
def test_the_index_refuses_a_value_with_no_text_but_dots(tmp_path, says):
    """A value of dots alone stands on any page: before the fix a page that said only 'This page has
    moved.' was the same page."""
    code, lines = check_says(tmp_path, says, "<p>This page has moved.</p>")
    assert code == 1
    assert lines == [
        f'fail {tmp_path / "index.json"} documents[0] fab-x: values[0]: "says" has no text but " ... "'
    ]


def test_the_index_holds_each_fab_page_and_samsungs_page_as_web_pages():
    """The 2 pages rules/sierra-circuits-web.kicad_dru names, the 3 of the other fab rule files, and
    Samsung's part page, whose bytes differ on every fetch; and NIST's 3 pages, 2 CODATA values that
    rules/interfaces/constants.json takes and DLMF 19.8 that tests/test_xsection.py cites."""
    docs = json.loads((ROOT / "rules" / "references" / "index.json").read_text(encoding="utf-8"))["documents"]
    pages = {d["url"] for d in docs if d["kind"] == "web page"}
    assert pages == {
        "https://www.protoexpress.com/products/online-pcb-manufacturing/",
        "https://www.protoexpress.com/kb/web-pcb-specs/",
        "https://jlcpcb.com/capabilities/pcb-capabilities",
        "https://www.pcbway.com/capabilities.html",
        "https://docs.oshpark.com/services/two-layer/",
        "https://weblib.samsungsem.com/mlcc/mlcc-ec-data-sheet.do?partNumber=CL10A106KP8NNN",
        "https://physics.nist.gov/cgi-bin/cuu/Value?z0",
        "https://physics.nist.gov/cgi-bin/cuu/Value?c",
        "https://dlmf.nist.gov/19.8",
    }
