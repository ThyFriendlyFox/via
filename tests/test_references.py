"""`workcenter references`: the index of the documents the rules name, fetched once, checked by hash.

A local server plays the makers' sites. It serves 3 documents: 1 as the index names it, 1 that changed
since (its index entry holds the SHA256 of the text before the change), and 1 behind a 403. It counts
the requests for each path and keeps every User-Agent. 2 runs of `fetch` ask each path once: the second
run answers from the ledger the first one wrote.

`references rules` holds every document a rule pack or a facts file names to the index. The fixtures of
tests/boards/references/ each plant 1 fault, and `make verify` runs the check on the repository itself.
"""

from __future__ import annotations

import hashlib
import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
FIXTURES = ROOT / "tests" / "boards" / "references"
INDEX = ROOT / "rules" / "references" / "index.json"

KEPT = b"%PDF-1.4 Acme AN-17 Layout of a buck converter, Rev. B\n"
BEFORE = b"%PDF-1.4 Acme AN-18 Input filters, Rev. A\n"
AFTER = b"%PDF-1.4 Acme AN-18 Input filters, Rev. B\n"
WALLED = b"%PDF-1.4 Acme AN-19 Thermal vias, Rev. A\n"
# The same name `fetch` sends (tools/workcenter FETCH_AGENT).
AGENT = "EE-Workcenter/1 (+https://github.com/ThyFriendlyFox/via)"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run(*args: object, cwd: Path = ROOT) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "references", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
    )
    return proc.returncode, proc.stdout + proc.stderr


def run_json(*args: object) -> tuple[int, dict]:
    code, out = run(*args, "--json")
    return code, json.loads(out)


class Maker(http.server.BaseHTTPRequestHandler):
    """Serves `files` by path; a path under /refused answers 403, as a bot wall does."""

    files: dict[str, bytes] = {}
    asked: dict[str, int] = {}
    agents: list[str] = []

    def do_GET(self):  # noqa: N802 (the handler's name is http.server's)
        Maker.asked[self.path] = Maker.asked.get(self.path, 0) + 1
        Maker.agents.append(self.headers.get("User-Agent", ""))
        body = Maker.files.get(self.path)
        if self.path.startswith("/refused"):
            self.send_response(403)
            self.end_headers()
        elif body is not None:
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def entry(doc_id: str, url: str, digest: str) -> dict:
    return {
        "id": doc_id,
        "kind": "application note",
        "maker": "Acme, a maker made up for the tests",
        "number": doc_id.upper(),
        "title": "A note made up for the tests",
        "revision": "Rev. A",
        "url": url,
        "sha256": digest,
        "read": "2026-11-17",
    }


@pytest.fixture
def site(tmp_path):
    """(index path, reference folder): an index of 3 documents on a local server."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Maker)
    Maker.files = {"/an-17.pdf": KEPT, "/an-18.pdf": AFTER, "/refused/an-19.pdf": WALLED}
    Maker.asked, Maker.agents = {}, []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"
    index = tmp_path / "index.json"
    docs = [
        entry("an-17", f"{base}/an-17.pdf", sha(KEPT)),
        entry("an-18", f"{base}/an-18.pdf", sha(BEFORE)),
        entry("an-19", f"{base}/refused/an-19.pdf", sha(WALLED)),
    ]
    index.write_text(json.dumps({"documents": docs}), encoding="utf-8")
    try:
        yield index, tmp_path / "refs"
    finally:
        server.shutdown()


def states(report: dict) -> dict[str, str]:
    return {d["id"]: d["state"] for d in report["documents"]}


def test_fetch_keeps_1_names_1_changed_and_1_refused_and_asks_each_once_in_2_runs(site):
    """The Evidence of ROADMAP item 2. Run 1 asks the 3 paths once each: 3 requests. Run 2 finds all 3
    in the ledger and asks none: 0 requests. The server's count stays 1 + 0 = 1 for each path."""
    index, refs = site
    code, first = run_json("fetch", "--index", index, "--to", refs)
    assert code == 1
    assert states(first) == {"an-17": "kept", "an-18": "changed", "an-19": "refused"}
    assert first["asked"] == 3
    code, second = run_json("fetch", "--index", index, "--to", refs)
    assert code == 1
    assert states(second) == {"an-17": "kept", "an-18": "changed", "an-19": "refused"}
    assert second["asked"] == 0
    assert Maker.asked == {"/an-17.pdf": 1, "/an-18.pdf": 1, "/refused/an-19.pdf": 1}
    assert Maker.agents == [AGENT] * 3
    kept = {d["id"]: d for d in second["documents"]}
    assert Path(kept["an-17"]["file"]).read_bytes() == KEPT
    # The changed copy is kept for a reader to compare, under its own hash; the index entry is not.
    assert Path(kept["an-18"]["file"]).read_bytes() == AFTER
    assert kept["an-18"]["sha256"] == sha(AFTER) and kept["an-18"]["index_sha256"] == sha(BEFORE)
    assert kept["an-19"]["file"] is None


def test_fetch_prints_1_line_per_document_and_a_count(site):
    """The text: a line for each answer, the ledger's date on the second run, and a last line of counts
    (1 kept, 1 changed, 1 refused out of 3; 0 asked in run 2)."""
    index, refs = site
    run("fetch", "--index", index, "--to", refs)
    code, out = run("fetch", "--index", index, "--to", refs)
    lines = out.splitlines()
    assert code == 1
    assert lines[0].startswith(f"kept an-17: AN-17, Rev. A, SHA256 {sha(KEPT)} as the index names [")
    assert lines[1].startswith(f"changed an-18: {url_of(index, 'an-18')} gives SHA256 {sha(AFTER)}")
    assert f"the index names {sha(BEFORE)}" in lines[1]
    assert lines[2].startswith(f"refused an-19: {url_of(index, 'an-19')} answered HTTP 403")
    assert "not asked again" in lines[2] and "references check FILE --id an-19" in lines[2]
    assert all("(ledger of 20" in line for line in lines[:3])
    assert lines[-1] == "references fetch: 1 kept, 1 changed, 1 refused, 0 gone, 0 not reached; 0 asked now"


def url_of(index: Path, doc_id: str) -> str:
    return next(d["url"] for d in json.loads(index.read_text())["documents"] if d["id"] == doc_id)


def test_fetch_again_asks_the_named_document_once_more(site):
    """`--again an-19` asks that 1 path a second time: 1 + 1 = 2 requests; the other 2 stay at 1."""
    index, refs = site
    run("fetch", "--index", index, "--to", refs)
    code, report = run_json("fetch", "--index", index, "--to", refs, "--again", "an-19")
    assert code == 1 and report["asked"] == 1
    assert Maker.asked == {"/an-17.pdf": 1, "/an-18.pdf": 1, "/refused/an-19.pdf": 2}


def test_fetch_says_a_site_not_reached_is_not_judged_and_asks_it_again(tmp_path):
    """A port nothing listens on: no answer, so no verdict. Exit 2 (not judged, as a skipped gate), and
    the ledger keeps nothing, so the next run asks again: 2 runs, 2 attempts, both `not reached`."""
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    index = tmp_path / "index.json"
    doc = entry("an-20", f"http://127.0.0.1:{port}/an-20.pdf", sha(KEPT))
    index.write_text(json.dumps({"documents": [doc]}), encoding="utf-8")
    for _ in range(2):
        code, report = run_json("fetch", "--index", index, "--to", tmp_path / "refs")
        assert code == 2 and states(report) == {"an-20": "not reached"} and report["asked"] == 1


def test_fetch_names_ids_the_index_lacks_and_asks_nothing(site):
    index, refs = site
    code, out = run("fetch", "an-99", "--index", index, "--to", refs)
    assert code == 1
    assert out.splitlines()[0].startswith("references: an-99 is not in the index")
    assert Maker.asked == {}


def test_fetch_refuses_a_folder_inside_a_repository(site, tmp_path):
    """A maker's document never lands in a repository: a folder under a `.git` is refused unasked."""
    index, _ = site
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    code, out = run("fetch", "--index", index, "--to", tmp_path / "repo" / "refs")
    assert code == 1
    assert "is inside the repository" in out and Maker.asked == {}
    assert not (tmp_path / "repo" / "refs").exists()


def test_check_says_whether_a_downloaded_file_is_the_copy_the_index_names(site, tmp_path):
    index, refs = site
    given = tmp_path / "downloads"
    given.mkdir()
    (given / "an-17.pdf").write_bytes(KEPT)
    (given / "an-18.pdf").write_bytes(AFTER)
    (given / "other.pdf").write_bytes(b"%PDF-1.4 something else\n")
    code, out = run("check", given / "an-17.pdf", "--index", index)
    assert code == 0 and out.startswith(
        f"same {given / 'an-17.pdf'}: an-17, AN-17, Rev. A, SHA256 {sha(KEPT)}"
    )
    code, out = run("check", given / "an-18.pdf", "--id", "an-18", "--index", index)
    assert code == 1
    assert out.startswith(
        f"changed {given / 'an-18.pdf'}: SHA256 {sha(AFTER)}, the index names {sha(BEFORE)}"
    )
    code, out = run("check", given / "other.pdf", "--index", index)
    assert code == 1 and "the index names no document with SHA256" in out
    assert Maker.asked == {}


def test_check_keep_files_the_copy_so_fetch_asks_nothing(site, tmp_path):
    """A person downloads an-19 by hand past the 403; `--keep` files it, and fetch then asks 0 times."""
    index, refs = site
    given = tmp_path / "an-19.pdf"
    given.write_bytes(WALLED)
    code, _ = run("check", given, "--index", index, "--keep", "--to", refs)
    assert code == 0
    code, report = run_json("fetch", "an-19", "--index", index, "--to", refs)
    assert code == 0 and states(report) == {"an-19": "kept"} and report["asked"] == 0
    assert Maker.asked == {}


def rules(*paths: Path, index: Path = FIXTURES / "index.json") -> tuple[int, list[str]]:
    code, out = run("rules", *paths, "--index", index)
    return code, out.splitlines()


def test_rules_pass_when_every_named_document_is_in_the_index():
    """pass/: the pack names AN-17, facts.json names it once more and has 1 part with no document:
    2 named, 2 in the index, 1 not judged."""
    code, lines = rules(FIXTURES / "pass")
    assert code == 0
    assert lines[-1] == "references rules: 2 documents named in 2 files, 2 in the index, 0 not; 1 not judged"
    assert [ln for ln in lines if ln.startswith("not judged")] == [
        "not judged tests/boards/references/pass/facts.json parts[0].source: names no document with a URL "
        "and a SHA256 (no datasheet: a part made up for the tests)"
    ]


@pytest.mark.parametrize(
    ("fixture", "fault"),
    [
        (
            "fail-lacks",
            "fail tests/boards/references/fail-lacks/pack.json document: AN-17, Rev. C, SHA256 "
            "9fcbf443f5691343a99ae18238472974b6a2185384ec8e4da56ceb037b4efbee is not in the index "
            "tests/boards/references/index.json",
        ),
        (
            "fail-url",
            "fail tests/boards/references/fail-url/pack.json document: AN-17, Rev. B is at "
            "https://example.com/mirror/an-17.pdf, the index names acme-an-17 at https://example.com/an-17.pdf",
        ),
        (
            "fail-no-sha",
            "fail tests/boards/references/fail-no-sha/pack.json document: AN-17, Rev. B names "
            "https://example.com/an-17.pdf and no SHA256 of the copy it was written from",
        ),
    ],
)
def test_rules_fail_on_1_line_for_the_planted_fault(fixture, fault):
    code, lines = rules(FIXTURES / fixture)
    assert code == 1
    assert [ln for ln in lines if ln.startswith("fail ")] == [fault]


def test_rules_refuse_an_index_entry_with_a_field_left_out():
    code, lines = rules(FIXTURES / "pass", index=FIXTURES / "fail-index" / "index.json")
    assert code == 1
    assert lines[0] == (
        "fail tests/boards/references/fail-index/index.json documents[0] acme-an-17: no revision"
    )


def test_every_document_a_rule_of_the_repository_names_is_in_the_index():
    """`make verify` runs this. The packs name 2 standards, the 3 facts files of 1 part 3 datasheets,
    passives.json 4: 2 + 3 + 4 = 9 named. made-up.json's 4 parts name no document: 4 not judged."""
    code, out = run("rules")
    assert code == 0, out
    files = 2 + 5
    assert out.splitlines()[-1] == (
        f"references rules: 9 documents named in {files} files, 9 in the index, 0 not; 4 not judged"
    )


def test_the_repository_holds_no_document_the_index_names():
    """The Scope guard: no tracked file has the SHA256 of a document in the index."""
    names = {d["sha256"] for d in json.loads(INDEX.read_text(encoding="utf-8"))["documents"]}
    tracked = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"], capture_output=True, check=True
    ).stdout.split(b"\0")
    held = [
        p
        for p in tracked
        if p and (ROOT / p.decode()).is_file() and sha((ROOT / p.decode()).read_bytes()) in names
    ]
    assert held == []
