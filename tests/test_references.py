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


def run(*args: object, cwd: Path = ROOT, env: dict | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "references", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=env,
    )
    return proc.returncode, proc.stdout + proc.stderr


def run_json(*args: object) -> tuple[int, dict]:
    code, out = run(*args, "--json")
    return code, json.loads(out)


class Maker(http.server.BaseHTTPRequestHandler):
    """Serves `files` by path; a path under /refused answers 403, as a bot wall does, under /busy 429
    (too many requests) and under /err 500 (the server erred). Any other path it lacks answers 404."""

    files: dict[str, bytes] = {}
    asked: dict[str, int] = {}
    agents: list[str] = []

    def do_GET(self):  # noqa: N802 (the handler's name is http.server's)
        Maker.asked[self.path] = Maker.asked.get(self.path, 0) + 1
        Maker.agents.append(self.headers.get("User-Agent", ""))
        body = Maker.files.get(self.path)
        walls = {"/refused": 403, "/busy": 429, "/err": 500}
        wall = next((code for prefix, code in walls.items() if self.path.startswith(prefix)), None)
        if wall is not None:
            self.send_response(wall)
            self.send_header("Content-Length", "0")
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
    assert lines[-1] == (
        "references fetch: 1 kept, 1 changed, 1 refused, 0 gone, 0 not given, 0 not reached; 0 asked now"
    )


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


# ------------------------------------------------------------------ the guards a mutation run found untested


def base_of(index: Path) -> str:
    return url_of(index, "an-17").rsplit("/", 1)[0]


def add_entry(index: Path, doc: dict) -> None:
    data = json.loads(index.read_text(encoding="utf-8"))
    data["documents"].append(doc)
    index.write_text(json.dumps(data), encoding="utf-8")


def test_fetch_files_a_404_as_gone_and_does_not_ask_it_again(site):
    """/an-21.pdf is no file of the server: 404. Run 1 asks it once and files `gone`; run 2 answers from
    the ledger: 1 + 0 = 1 request."""
    index, refs = site
    add_entry(index, entry("an-21", f"{base_of(index)}/an-21.pdf", sha(KEPT + b"21")))
    for n in (1, 2):
        code, report = run_json("fetch", "an-21", "--index", index, "--to", refs)
        assert code == 1 and states(report) == {"an-21": "gone"} and report["asked"] == 2 - n
    assert Maker.asked == {"/an-21.pdf": 1}


def test_fetch_asks_again_for_a_copy_deleted_from_the_folder(site):
    """Run 1 keeps an-17. Its copy is deleted; run 2 asks /an-17.pdf again: 1 + 1 = 2 requests."""
    index, refs = site
    _, first = run_json("fetch", "an-17", "--index", index, "--to", refs)
    Path(first["documents"][0]["file"]).unlink()
    code, second = run_json("fetch", "an-17", "--index", index, "--to", refs)
    assert code == 0 and states(second) == {"an-17": "kept"} and second["asked"] == 1
    assert Maker.asked == {"/an-17.pdf": 2}


def test_fetch_asks_again_when_the_index_moves_a_url(site):
    """Run 1 keeps an-17 at /an-17.pdf. The index then names /moved/an-17.pdf; run 2 asks the new URL
    once: 1 request for each path."""
    index, refs = site
    run("fetch", "an-17", "--index", index, "--to", refs)
    data = json.loads(index.read_text(encoding="utf-8"))
    data["documents"][0]["url"] = f"{base_of(index)}/moved/an-17.pdf"
    index.write_text(json.dumps(data), encoding="utf-8")
    Maker.files["/moved/an-17.pdf"] = KEPT
    code, report = run_json("fetch", "an-17", "--index", index, "--to", refs)
    assert code == 0 and report["asked"] == 1
    assert Maker.asked == {"/an-17.pdf": 1, "/moved/an-17.pdf": 1}


@pytest.mark.parametrize(("path", "status"), [("/busy/an-22.pdf", 429), ("/err/an-23.pdf", 500)])
def test_fetch_records_nothing_for_an_answer_that_gives_no_copy_and_asks_it_again(site, path, status):
    """429 limits the rate (RFC 6585, section 4, p 3) and 500 says the server erred (RFC 9110, section
    15.6): neither refuses the workcenter's name nor says the file is gone. Each of 2 runs asks once:
    2 requests, exit 2 (not judged) both times."""
    index, refs = site
    doc_id = path.rsplit("/", 1)[1].removesuffix(".pdf")
    url = f"{base_of(index)}{path}"
    add_entry(index, entry(doc_id, url, sha(KEPT + path.encode())))
    for _ in range(2):
        code, out = run("fetch", doc_id, "--index", index, "--to", refs)
        assert code == 2
        assert out.splitlines()[0] == (
            f"not given {doc_id}: {url} answered HTTP {status}, which gives no copy and no verdict; "
            "nothing recorded, asked again on the next run"
        )
    assert Maker.asked == {path: 2}


def test_fetch_ignores_a_relative_xdg_cache_home(site, tmp_path):
    """XDG Base Directory Specification 0.8, section 2: a relative path in these variables is invalid
    and is ignored. Run from repo/sub with XDG_CACHE_HOME=cache, the copy goes to $HOME/.cache, and the
    repository gains no file."""
    import os

    index, _ = site
    repo, home = tmp_path / "repo", tmp_path / "home"
    (repo / ".git").mkdir(parents=True)
    (repo / "sub").mkdir()
    home.mkdir()
    env = dict(os.environ, XDG_CACHE_HOME="cache", HOME=str(home))
    code, out = run("fetch", "an-17", "--index", index, cwd=repo / "sub", env=env)
    assert code == 0, out
    assert [p for p in repo.rglob("*") if p.is_file()] == []
    assert (home / ".cache" / "ee-workcenter" / "references" / "ledger.json").is_file()


@pytest.mark.parametrize(
    ("ledger", "fault"),
    [
        ({"documents": []}, "documents: an object of records by id is asked"),
        ({"documents": {"an-17": {"url": "https://example.com/an-17.pdf"}}}, "documents.an-17: state: "),
        ("{not json", "not JSON"),
    ],
)
def test_fetch_refuses_a_ledger_of_the_wrong_shape_on_1_line_and_asks_nothing(site, ledger, fault):
    index, refs = site
    refs.mkdir()
    text = ledger if isinstance(ledger, str) else json.dumps(ledger)
    (refs / "ledger.json").write_text(text, encoding="utf-8")
    code, out = run("fetch", "--index", index, "--to", refs)
    assert code == 1
    assert len(out.splitlines()) == 1 and out.startswith(f"references: {refs / 'ledger.json'}")
    assert fault in out and "mend it or delete it" in out
    assert Maker.asked == {}


def test_fetch_refuses_a_to_that_is_a_file(site, tmp_path):
    index, _ = site
    afile = tmp_path / "afile"
    afile.write_text("x", encoding="utf-8")
    code, out = run("fetch", "--index", index, "--to", afile)
    assert code == 1 and out == f"references: {afile} is a file; --to names a folder\n"
    assert Maker.asked == {}


def test_check_keep_refuses_a_folder_inside_a_repository(site, tmp_path):
    index, _ = site
    (tmp_path / "repo" / ".git").mkdir(parents=True)
    given = tmp_path / "an-17.pdf"
    given.write_bytes(KEPT)
    code, out = run("check", given, "--index", index, "--keep", "--to", tmp_path / "repo" / "refs")
    assert code == 1 and "is inside the repository" in out
    assert not (tmp_path / "repo" / "refs").exists()


GOOD = {
    "id": "acme-an-17",
    "kind": "application note",
    "maker": "Acme, a maker made up for the tests",
    "number": "AN-17",
    "title": "Layout of a buck converter",
    "revision": "Rev. B",
    "url": "https://example.com/an-17.pdf",
    "sha256": "d3d0f188f5b9b632e69a0942046d751e98cb9ef103e8c319a3c72fe046f4a3dd",
    "read": "2026-11-17",
}
OTHER_SHA = "0" * 64


@pytest.mark.parametrize(
    ("docs", "fault"),
    [
        (
            [GOOD, GOOD | {"sha256": OTHER_SHA}],
            "documents[1] acme-an-17: id acme-an-17 is the id of documents[0] too",
        ),
        (
            [GOOD, GOOD | {"id": "acme-an-18"}],
            f"documents[1] acme-an-18: sha256 {GOOD['sha256']} is the sha256 of documents[0] too",
        ),
        (
            [GOOD | {"issuer": "Acme"}],
            "documents[0] acme-an-17: names neither or both of maker and issuer; it names 1",
        ),
        (
            [{k: v for k, v in GOOD.items() if k != "maker"}],
            "documents[0] acme-an-17: names neither or both of maker and issuer; it names 1",
        ),
        (
            [GOOD | {"kind": "note"}],
            "documents[0] acme-an-17: kind 'note' is none of standard, application note, datasheet",
        ),
        (
            [GOOD | {"id": "AN-17"}],
            "documents[0] AN-17: id 'AN-17' is not lower-case letters, digits, dots and hyphens",
        ),
        ([GOOD | {"sha256": "ABC"}], "documents[0] acme-an-17: sha256 'ABC' is not 64 lower-case hex digits"),
        (
            [GOOD | {"url": "example.com/an-17.pdf"}],
            "documents[0] acme-an-17: url 'example.com/an-17.pdf' is not a whole URL, https://host/path",
        ),
        (
            [GOOD | {"read": "17 Nov 2026"}],
            "documents[0] acme-an-17: read '17 Nov 2026' is not a date, 2026-11-17",
        ),
    ],
)
def test_rules_refuse_an_index_entry_of_the_wrong_form(tmp_path, docs, fault):
    """Each case plants 1 fault the README says the command refuses; the 1 line names the entry."""
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"documents": docs}), encoding="utf-8")
    code, lines = rules(FIXTURES / "pass", index=index)
    assert code == 1 and lines == [f"fail {index} {fault}"]


@pytest.mark.parametrize("globs", ["rules/ratings/*.json", ["/rules/ratings/*.json"], [""], [3]])
def test_rules_refuse_an_index_whose_rules_are_no_list_of_globs(tmp_path, globs):
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"rules": globs, "documents": [GOOD]}), encoding="utf-8")
    code, lines = rules(index=index)
    assert code == 1
    assert lines == [
        f"fail {index}: rules: a list of globs from the repository's root is asked, "
        'as ["rules/ratings/*.json"]'
    ]


def facts_with(tmp_path: Path, source: dict) -> Path:
    path = tmp_path / "facts.json"
    path.write_text(
        json.dumps({"parts": [{"kind": "capacitor.ceramic", "source": source}]}), encoding="utf-8"
    )
    return path


@pytest.mark.parametrize(
    ("source", "fault"),
    [
        (
            {"document": "Murata GRM188R71E104KA01 datasheet", "read": "2026-11-17", "second_reader": "no"},
            "Murata GRM188R71E104KA01 datasheet names no URL and no SHA256: write both from the copy it was "
            "read from, or `no datasheet: <why>` as its document",
        ),
        (
            {"document": "Acme AN-17", "revision": "Rev. B", "sha256": GOOD["sha256"]},
            f"Acme AN-17, Rev. B has SHA256 {GOOD['sha256']} and no URL to fetch it from",
        ),
        (
            {"document": "Acme AN-17", "url": GOOD["url"], "sha256": ["d3d0"]},
            "sha256 ['d3d0'] is not 64 hex digits",
        ),
        (
            {"document": "Acme AN-17", "url": 17, "sha256": GOOD["sha256"]},
            "url 17 is not a whole URL, https://host/path",
        ),
    ],
)
def test_rules_fail_a_source_that_names_a_document_it_does_not_pin(tmp_path, source, fault):
    """A source with no URL and no SHA256 is not judged only when its document says `no datasheet: why`
    or `no document: why`; a real datasheet named by name alone fails, as does a hash of the wrong type."""
    path = facts_with(tmp_path, source)
    code, lines = rules(path)
    assert code == 1
    assert [ln for ln in lines if ln.startswith("fail ")] == [f"fail {path} parts[0].source: {fault}"]
    assert lines[-1] == "references rules: 1 documents named in 1 files, 0 in the index, 1 not; 0 not judged"


def test_rules_read_a_table_of_documents_by_id(tmp_path):
    """rules/copper/materials.json (roadmap item 10) names its documents in a table, `documents: {id:
    {...}}`, and each constant points at an id. A document of that table the index lacks fails, as one
    under `document` or `source` does; before, the table was not read and 0 documents were named."""
    path = tmp_path / "materials.json"
    entry = {"number": "AN-99", "url": "https://maker.example/an-99.pdf", "sha256": "ab" * 32}
    path.write_text(json.dumps({"documents": {"an-99": entry}, "k": {"document": "an-99"}}), encoding="utf-8")
    code, lines = rules(path)
    assert code == 1
    assert [ln for ln in lines if ln.startswith("fail ")] == [
        f"fail {path} documents.an-99: AN-99, SHA256 {'ab' * 32} is not in the index "
        f"{(FIXTURES / 'index.json').relative_to(ROOT)}"
    ]
    assert lines[-1] == "references rules: 1 documents named in 1 files, 0 in the index, 1 not; 0 not judged"


def test_every_document_a_rule_of_the_repository_names_is_in_the_index():
    """`make verify` runs this. The rating packs name 2 standards, the board pack 1, the 4 facts files
    of 1 part 4 datasheets, passives.json 4, fail-sim-bias's parts.json 2 (Samsung's page and Coilcraft's
    806, which passives.json names too), rules/copper/materials.json 2, the 2 layout packs of rules/board/
    2 (SLVA680A, SZZA009), the 2 creepage packs 2 (MIL-HDBK-454C, SLUP419):
    2 + 1 + 4 + 4 + 2 + 2 + 2 + 2 = 19 named. made-up.json's 4 parts name no document: 4 not judged."""
    code, out = run("rules")
    assert code == 0, out
    files = 2 + 1 + 1 + 7 + 2 + 2
    assert out.splitlines()[-1] == (
        f"references rules: 19 documents named in {files} files, 19 in the index, 0 not; 4 not judged"
    )


def names_a_document(data: object) -> bool:
    if isinstance(data, dict):
        return any(k in data for k in ("document", "source")) or any(map(names_a_document, data.values()))
    return isinstance(data, list) and any(map(names_a_document, data))


def test_the_index_globs_cover_every_rule_file_under_rules():
    """A pack in a new folder of rules/ (rules/board/, roadmap item 6) is read by `make verify` only when
    a glob of the index covers it; a pack outside them named a document the index lacked and passed."""
    globbed = {
        p for pattern in json.loads(INDEX.read_text(encoding="utf-8"))["rules"] for p in ROOT.glob(pattern)
    }
    naming = [
        p
        for p in sorted((ROOT / "rules").rglob("*.json"))
        if p != INDEX and names_a_document(json.loads(p.read_text(encoding="utf-8")))
    ]
    assert naming
    assert [str(p.relative_to(ROOT)) for p in naming if p not in globbed] == []


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
