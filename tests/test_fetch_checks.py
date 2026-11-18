"""`workcenter fetch` on a new project: it starts library/sources.csv, takes a file a person downloaded,
and refuses a body that is not what its name says; `workcenter sources` fails a kept file of that kind
(PROCESSES.md P27; user round 1 of 2026-11-17, candidates 6 and 13).

A local server plays the maker's site: each path serves a planted body with a planted Content-Type and
Content-Length. No test reaches the outside network. The bodies are short byte strings written here. The
rule judged is the item's own: a `.pdf` starts with the 4 bytes `%PDF`, as every PDF of the example
libraries does (their first bytes, read 2026-11-17: `%PDF-1.4` to `%PDF-1.7`).
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import http.server
import importlib.machinery
import json
import shutil
import subprocess
import sys
import threading
import types
import zipfile
from pathlib import Path

import pytest
from test_sources import PARTS  # the RC divider fixture's 3 parts with their MPNs

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
BOARDS = ROOT / "tests" / "boards"
HEADER = "MPN,Kind,URL,File,Member,Revision,Dated,Subckt,Ngspice,SHA256,Checked,Note"

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<< >>\nendobj\ntrailer\n<< >>\n%%EOF\n"
# The page Samsung served for a datasheet URL in user round 1: a UTF-8 byte order mark, then <html.
HTML = b'\xef\xbb\xbf<html lang="ko">\r\n<head>\r\n<title>Error</title></head><body>no file</body></html>\r\n'
GIF = b"GIF89a\x01\x00\x01\x00\x00\x00\x00;"
MODEL = b"* Acme divider\n.SUBCKT RDIV IN OUT GND\nR1 IN OUT 100\nR2 OUT GND 100\n.ENDS\n"
# Error pages that do not start with <html or <!doctype html (the review of 2026-11-18, finding F1).
HTML_HEAD = b"<head><title>404 Not Found</title></head>\n<body><h1>Not Found</h1></body>\n"
HTML_COMMENT = b"<!-- served by the CDN -->\n<html><body>Access denied</body></html>\n"
XHTML = (
    b'<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE html PUBLIC "-//W3C//DTD XHTML 1.0//EN">\n<html/>\n'
)
UTF16 = b"\xff\xfe" + "<!DOCTYPE html><html><body>error</body></html>".encode("utf-16-le")  # the BOM FF FE
SPACED = b"\r\n\r\n  <html><body>gone</body></html>\r\n"
# A fab's capability page: `workcenter references` holds it by the values read from it, so it must come
# back from fetch_url as the web page it is.
FAB_PAGE = b"<!doctype html><html><body><td>Minimum trace</td><td>4 mil (0.1016 mm)</td></body></html>\n"

# path: (Content-Type, body, Content-Length sent, bytes sent)
PAGES: dict[str, tuple[str, bytes, int | None]] = {
    "/good.pdf": ("application/pdf", PDF, None),
    "/typed.pdf": ("text/html; charset=utf-8", PDF, None),  # a true PDF's bytes, served as a web page
    "/xtyped.pdf": ("application/xhtml+xml", PDF, None),
    "/page.pdf": ("application/pdf", HTML, None),  # a web page's bytes, served as a PDF
    "/gif.pdf": ("application/pdf", GIF, None),
    "/empty.pdf": ("application/pdf", b"", None),
    "/cut.pdf": ("application/pdf", PDF[:16], 2048),  # 16 bytes sent of the 2048 promised
    "/page.lib": ("text/plain", HTML, None),
    "/head.lib": ("text/plain", HTML_HEAD, None),
    "/comment.lib": ("application/octet-stream", HTML_COMMENT, None),
    "/xhtml.step": ("application/octet-stream", XHTML, None),
    "/utf16.lib": ("application/octet-stream", UTF16, None),
    "/spaced.lib": ("text/plain", SPACED, None),
    "/fab.html": ("text/html; charset=utf-8", FAB_PAGE, None),  # a web page entry of the reference index
}
# path: the whole response, written as it stands, then the connection closes
RAW: dict[str, bytes] = {
    # 1 chunk of 0x800 bytes named, 16 sent; no Content-Length
    "/chunked.pdf": b"HTTP/1.1 200 OK\r\nContent-Type: application/pdf\r\nTransfer-Encoding: chunked\r\n\r\n"
    b"800\r\n" + PDF[:16],
    "/badstatus.pdf": b"HTTP/1.1 OK-ish\r\n\r\n",
}


def load_cli():
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_fetch_checks", str(CLI))
    module = types.ModuleType("workcenter_cli_fetch_checks")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module
    loader.exec_module(module)
    return module


def fetch(*args: object, json_out: bool = True) -> tuple[int, dict | str]:
    flags = ["--json"] if json_out else []
    proc = subprocess.run(
        [sys.executable, str(CLI), *flags, "fetch", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )
    if not json_out:
        return proc.returncode, proc.stdout + proc.stderr
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else {})


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Maker(http.server.BaseHTTPRequestHandler):
    """Serves PAGES; records every User-Agent it is sent."""

    agents: list[str] = []

    def do_GET(self):  # noqa: N802 (the handler's name is http.server's)
        Maker.agents.append(self.headers.get("User-Agent", ""))
        if self.path in RAW:
            self.wfile.write(RAW[self.path])
            self.close_connection = True
            return
        if self.path not in PAGES:
            self.send_response(404)
            self.end_headers()
            return
        ctype, body, length = PAGES[self.path]
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body) if length is None else length))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@pytest.fixture
def site(tmp_path):
    """(base URL, a project folder with no library yet)."""
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Maker)
    Maker.agents = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    project = tmp_path / "node"
    project.mkdir()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", project
    finally:
        server.shutdown()


# ------------------------------------------------------------ a new project's library


def test_the_first_row_starts_the_projects_library(site):
    """A project with no library/sources.csv: the first `fetch --row` writes the header from the code's
    1 header, then the row, and says so in 1 line."""
    url, project = site
    dest = project / "library" / "acme" / "acme-1.pdf"
    code, out = fetch(f"{url}/good.pdf", "--to", dest, "--mpn", "ACME-1", "--row", json_out=False)
    assert code == 0, out
    sources = project / "library" / "sources.csv"
    lines = sources.read_text(encoding="utf-8").splitlines()
    assert lines[0] == HEADER == ",".join(load_cli().SOURCES_HEADER)
    assert len(lines) == 2 and lines[1].startswith(f"ACME-1,datasheet,{url}/good.pdf,acme/acme-1.pdf,")
    assert dest.read_bytes() == PDF
    started = [ln for ln in out.splitlines() if ln.startswith("sources: started")]
    assert started == [f"sources: started {sources}"], out
    # the second row goes into the library the first one started, with no second header
    code, report = fetch(
        f"{url}/good.pdf", "--to", project / "library" / "acme" / "b.pdf", "--mpn", "ACME-2", "--row"
    )
    assert code == 0 and "started" not in report, report
    assert [r.mpn for r in load_cli().read_sources(sources)] == ["ACME-1", "ACME-2"]


def test_a_file_outside_any_library_folder_still_needs_one_named(site, tmp_path):
    """Nothing to start: --to names no library/ folder, so the row has no file to go in."""
    url, _ = site
    loose = tmp_path / "loose" / "acme" / "acme-1.pdf"
    code, report = fetch(f"{url}/good.pdf", "--to", loose, "--mpn", "ACME-1", "--row")
    assert code == 1 and "no sources.csv" in report["error"] and "library" in report["error"], report
    assert Maker.agents == [] and not loose.parent.exists()


# ------------------------------------------------------------ a file a person downloaded


def test_a_downloaded_file_is_kept_hashed_and_given_its_row(site, tmp_path):
    """The workcenter asks no site: the bytes are the person's file, the URL is the one they name, and
    the row says the workcenter did not fetch it."""
    _, project = site
    download = tmp_path / "Downloads" / "CL10A105KB8NNNC.pdf"
    download.parent.mkdir()
    download.write_bytes(PDF)
    dest = project / "library" / "samsung" / "CL10A105KB8NNNC.pdf"
    where = "https://product.samsungsem.com/front/www/data/component/mlcc/pdf/CL10A105KB8NNNC.pdf"
    code, report = fetch(
        "--file", download, "--url", where, "--to", dest, "--mpn", "CL10A105KB8NNNC", "--row"
    )
    assert code == 0, report
    assert dest.read_bytes() == PDF and download.read_bytes() == PDF  # copied, not moved
    rows = list(csv.DictReader((project / "library" / "sources.csv").open(encoding="utf-8")))
    assert len(rows) == 1
    row = rows[0]
    assert row["URL"] == where and row["File"] == "samsung/CL10A105KB8NNNC.pdf"
    assert row["SHA256"] == sha(PDF) and row["Kind"] == "datasheet"
    assert "not fetched by the workcenter" in row["Note"]
    assert Maker.agents == []  # no request to any site


def test_a_downloaded_file_needs_its_url_and_only_one_source(site, tmp_path):
    url, project = site
    download = tmp_path / "x.pdf"
    download.write_bytes(PDF)
    dest = project / "library" / "acme" / "x.pdf"
    for args, why in (
        (("--file", download), "--file needs --url"),
        ((f"{url}/good.pdf", "--url", f"{url}/good.pdf"), "--url goes with --file"),
        ((f"{url}/good.pdf", "--file", download, "--url", f"{url}/good.pdf"), "a URL or --file"),
        (("--mpn", "X"), "a URL or --file"),
    ):
        code, report = fetch(*args, "--to", dest, "--mpn", "X", "--row")
        assert code == 1 and why in report["error"], (args, report)
    assert Maker.agents == [] and not dest.exists()


def test_a_downloaded_zip_keeps_its_member_not_the_archive(site, tmp_path):
    """--file with --member reads the member out, as a fetched zip's is: the kept bytes and the row's
    SHA256 are the member's, so a later `sources --fetch` compares like with like."""
    _, project = site
    download = tmp_path / "Downloads" / "models.zip"
    download.parent.mkdir()
    with zipfile.ZipFile(download, "w") as zf:
        zf.writestr("m.lib", MODEL)
    dest = project / "library" / "acme" / "m.lib"
    where = "https://maker.example/models.zip"
    code, report = fetch(
        "--file", download, "--url", where, "--member", "m.lib", "--to", dest, "--mpn", "M1", "--row"
    )
    assert code == 0, report
    assert dest.read_bytes() == MODEL
    row = next(csv.DictReader((project / "library" / "sources.csv").open(encoding="utf-8")))
    assert row["Member"] == "m.lib" and row["SHA256"] == sha(MODEL) and row["URL"] == where
    # a member the archive does not hold: refused, nothing written
    other = project / "library" / "acme" / "n.lib"
    code, report = fetch(
        "--file", download, "--url", where, "--member", "n.lib", "--to", other, "--mpn", "N1", "--row"
    )
    assert code == 1 and report["error"].startswith(f"no member 'n.lib' in {download}"), report
    assert not other.exists()
    assert Maker.agents == []


def test_a_downloaded_web_page_is_refused_like_a_fetched_one(site, tmp_path):
    _, project = site
    download = tmp_path / "saved.pdf"
    download.write_bytes(HTML)
    dest = project / "library" / "acme" / "saved.pdf"
    code, report = fetch(
        "--file", download, "--url", "https://maker.example/a.pdf", "--to", dest, "--mpn", "A", "--row"
    )
    assert code == 1, report
    assert report["error"].startswith(f"{download} is an HTML page"), report
    assert not dest.exists() and not (project / "library").exists()


# ------------------------------------------------------------ bodies that are not what their names say


@pytest.mark.parametrize(
    ("path", "says"),
    [
        ("/typed.pdf", "an HTML page (Content-Type text/html), not a PDF"),
        ("/page.pdf", "an HTML page (it starts b'<html lang=\"ko\">'), not a PDF"),
        ("/gif.pdf", "a file that starts b'GIF89a\\x01\\x00', not %PDF"),
        ("/empty.pdf", "an empty file (0 bytes)"),
        ("/cut.pdf", "16 of the 2048 bytes its Content-Length names"),  # PDF[:16] sent, 2048 promised
        ("/page.lib", "an HTML page (it starts b'<html lang=\"ko\">'), not a SPICE model"),
        ("/xtyped.pdf", "an HTML page (Content-Type application/xhtml+xml), not a PDF"),
        # the first 16 bytes after the byte order mark and the white space: '<head>' 6 + '<title>' 7 + '404' 3
        ("/head.lib", "an HTML page (it starts b'<head><title>404'), not a SPICE model"),
        ("/comment.lib", "an HTML page (it starts b'<!-- served by t'), not a SPICE model"),
        ("/xhtml.step", "an HTML page (it starts b'<?xml version=\"1'), not a STEP file"),
        # UTF-16 LE read as text: '<!DOCTYPE html>' 15 characters + '<' 1
        ("/utf16.lib", "an HTML page (it starts b'<!DOCTYPE html><'), not a SPICE model"),
        # 2 CR LF and 2 spaces stripped, then '<html>' 6 + '<body>' 6 + 'gone' 4
        ("/spaced.lib", "an HTML page (it starts b'<html><body>gone'), not a SPICE model"),
        # PDF[:16] sent of the 0x800 = 2048 named by the chunk; the response names no Content-Length
        ("/chunked.pdf", "16 bytes, cut short inside a chunk (Transfer-Encoding chunked, no Content-Length)"),
    ],
)
def test_a_body_that_is_not_what_its_name_says_is_refused(site, path, says):
    """1 line names the URL and what came; no file, no library, no row."""
    url, project = site
    dest = project / "library" / "acme" / ("x" + Path(path).suffix)
    code, report = fetch(f"{url}{path}", "--to", dest, "--mpn", "ACME-1", "--row")
    assert code == 1, report
    error = report["error"]
    assert error.startswith(f"{url}{path} gave {says}; nothing written"), error
    assert "\n" not in error
    assert not dest.exists() and not (project / "library").exists()
    assert len(Maker.agents) == 1  # asked once, under the workcenter's own name
    code, out = fetch(f"{url}{path}", "--to", dest, "--mpn", "ACME-1", "--row", json_out=False)
    assert code == 1 and out.count("\n") == 1 and out.startswith(f"fetch: {url}{path} gave {says}"), out


def test_a_true_pdf_still_lands(site):
    url, project = site
    dest = project / "library" / "acme" / "good.pdf"
    code, report = fetch(f"{url}/good.pdf", "--to", dest, "--mpn", "ACME-1")
    assert code == 0 and report["sha256"] == sha(PDF) and report["bytes"] == len(PDF), report
    assert dest.read_bytes() == PDF


def test_a_response_that_is_not_http_is_1_line_not_a_traceback(site):
    """A status line with no number: http.client raises BadStatusLine from urlopen."""
    url, project = site
    dest = project / "library" / "acme" / "x.pdf"
    code, out = fetch(f"{url}/badstatus.pdf", "--to", dest, "--mpn", "ACME-1", "--row", json_out=False)
    assert code == 1 and "Traceback" not in out, out
    assert out.count("\n") == 1, out
    assert out.startswith(
        f"fetch: {url}/badstatus.pdf error (BadStatusLine: HTTP/1.1 OK-ish); nothing written"
    )
    assert not dest.exists() and not (project / "library").exists()


def test_references_fetch_still_keeps_a_web_page_entry_served_as_text_html(site, tmp_path):
    """`workcenter references fetch` reads its documents through fetch_url too. A web page entry is an
    HTML page by design and is judged by its values, not refused as a body that is not what its name
    says (the landing of 2026-11-18: fetch's new judgement made every web page entry 'not reached')."""
    url, _ = site
    entry = {
        "id": "fab-page",
        "kind": "web page",
        "maker": "A fab made up for the tests",
        "title": "Capabilities, a page made up for the tests",
        "url": f"{url}/fab.html",
        "read": "2026-11-17",
        "values": [
            {"says": "Minimum trace 4 mil (0.1016 mm)", "for": "fab: trace 4 mil, made up for the tests"}
        ],
    }
    index = tmp_path / "index.json"
    index.write_text(json.dumps({"documents": [entry]}), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(CLI), "references", "fetch", "--index", str(index), "--to", str(tmp_path / "r")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.startswith("kept fab-page: a web page, held by its values"), proc.stdout
    # the same page given to `workcenter fetch` as a datasheet is still refused
    code, report = fetch(f"{url}/fab.html", "--to", tmp_path / "library" / "acme" / "fab.pdf", "--mpn", "X")
    assert code == 1 and report["status"] == "wrong", report


def test_a_utf16_big_endian_page_is_an_html_page():
    """The byte order mark FE FF, then UTF-16 BE: read as text, its first 16 characters are
    '<html><head><tit' ('<html>' 6 + '<head>' 6 + '<tit' 4)."""
    page = b"\xfe\xff" + "<html><head><title>x</title></head></html>".encode("utf-16-be")
    assert load_cli().body_wrong("m.mod", page, len(page)) == (
        "an HTML page (it starts b'<html><head><tit'), not a SPICE model"
    )
    # a SPICE model and a STEP file pass: neither starts with '<'
    assert load_cli().body_wrong("m.lib", MODEL, len(MODEL)) == ""
    step = b"ISO-10303-21;\nHEADER;\n"
    assert load_cli().body_wrong("m.step", step, len(step)) == ""


# ------------------------------------------------------------ the sources check finds the old rows


def library_with(tmp_path: Path, files: dict[str, bytes]) -> list:
    """A library whose rows each hold the right SHA256 of their file: only the body can be wrong."""
    lib = tmp_path / "library"
    rows = [HEADER]
    for n, (name, body) in enumerate(files.items()):
        (lib / "acme").mkdir(parents=True, exist_ok=True)
        (lib / "acme" / name).write_bytes(body)
        rows.append(f"P{n},datasheet,https://maker.example/{name},acme/{name},,,,,,{sha(body)},2026-11-17,")
    (lib / "sources.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return load_cli().read_sources(lib / "sources.csv")


def test_the_sources_check_fails_a_kept_web_page_or_empty_file(tmp_path):
    """Rows written before fetch judged its bodies: each wrong file is 1 problem, and the row is judged
    on nothing more; a true PDF and a text datasheet pass this check."""
    cli = load_cli()
    rows = library_with(
        tmp_path,
        {
            "page.pdf": HTML,
            "empty.pdf": b"",
            "gif.pdf": GIF,
            "page.txt": HTML,
            "good.pdf": PDF,
            "ds.txt": b"Rev C\n",
        },
    )
    found = {}
    for row in rows:
        _, problems, _ = cli.check_source(row, tmp_path / "library", tmp_path / "work")
        found[row.file] = problems
    assert found["acme/page.pdf"] == [
        "P0 datasheet: acme/page.pdf is an HTML page (it starts b'<html lang=\"ko\">'), "
        "not a PDF (sources.csv:2)"
    ]
    assert found["acme/empty.pdf"] == [
        "P1 datasheet: acme/empty.pdf is an empty file (0 bytes) (sources.csv:3)"
    ]
    assert found["acme/gif.pdf"] == [
        "P2 datasheet: acme/gif.pdf is a file that starts b'GIF89a\\x01\\x00', not %PDF (sources.csv:4)"
    ]
    assert found["acme/page.txt"] == [
        "P3 datasheet: acme/page.txt is an HTML page (it starts b'<html lang=\"ko\">'), "
        "not the file its name says (sources.csv:5)"
    ]
    assert found["acme/good.pdf"] == [] and found["acme/ds.txt"] == []


def test_the_sources_check_fails_a_kept_page_that_does_not_start_with_html(tmp_path):
    """The 4 error pages of finding F1, kept as models and a body: each is 1 problem."""
    cli = load_cli()
    rows = library_with(
        tmp_path, {"head.lib": HTML_HEAD, "comment.lib": HTML_COMMENT, "utf16.lib": UTF16, "x.step": XHTML}
    )
    found = {}
    for row in rows:
        _, problems, _ = cli.check_source(row, tmp_path / "library", tmp_path / "work")
        found[row.file] = problems
    model = "not a SPICE model"
    assert found == {
        "acme/head.lib": [
            f"P0 datasheet: acme/head.lib is an HTML page (it starts b'<head><title>404'), "
            f"{model} (sources.csv:2)"
        ],
        "acme/comment.lib": [
            f"P1 datasheet: acme/comment.lib is an HTML page (it starts b'<!-- served by t'), "
            f"{model} (sources.csv:3)"
        ],
        "acme/utf16.lib": [
            f"P2 datasheet: acme/utf16.lib is an HTML page (it starts b'<!DOCTYPE html><'), "
            f"{model} (sources.csv:4)"
        ],
        "acme/x.step": [
            "P3 datasheet: acme/x.step is an HTML page (it starts b'<?xml version=\"1'), "
            "not a STEP file (sources.csv:5)"
        ],
    }


def test_a_kept_web_page_is_1_problem_whatever_else_its_row_says(tmp_path):
    """A row whose SHA256 is not its file's, with a Revision and a Subckt the page cannot hold: the web
    page is the 1 problem, and the SHA256, the revision and the subckt are not judged on it."""
    lib = tmp_path / "library"
    (lib / "acme").mkdir(parents=True)
    (lib / "acme" / "page.lib").write_bytes(HTML_HEAD)
    row = f"X1,spice,https://maker.example/page.lib,acme/page.lib,,Rev C,,RDIV,,{'0' * 64},2026-11-17,"
    (lib / "sources.csv").write_text(f"{HEADER}\n{row}\n", encoding="utf-8")
    cli = load_cli()
    (row,) = cli.read_sources(lib / "sources.csv")
    _, problems, _ = cli.check_source(row, lib, tmp_path / "work")
    assert problems == [
        "X1 spice: acme/page.lib is an HTML page (it starts b'<head><title>404'), not a SPICE model "
        "(sources.csv:2)"
    ]


@pytest.mark.engine
@pytest.mark.skipif(shutil.which("kicad-cli") is None, reason="kicad-cli is not installed")
def test_workcenter_sources_fails_a_board_whose_datasheet_is_a_web_page(tmp_path):
    """The RC divider fixture's 3 parts, each with a datasheet row; the resistor's kept datasheet is the
    page Samsung served. Exit 1 and that 1 problem."""
    lib = tmp_path / "library"
    (lib / "acme").mkdir(parents=True)
    (lib / "acme" / "rc.pdf").write_bytes(HTML)
    rows = [
        HEADER,
        f"RC0603FR-0710KL,datasheet,https://maker.example/rc.pdf,acme/rc.pdf,,,,,,{sha(HTML)},2026-11-17,",
        "CL10B104KB8NNNC,datasheet,https://maker.example/cl10,,,,,,,,2026-11-17,not kept",
        "PREC003SAAN-RC,datasheet,https://maker.example/prec,,,,,,,,2026-11-17,not kept",
    ]
    (lib / "sources.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    parts = tmp_path / "parts.csv"
    parts.write_text(PARTS.format(today=datetime.date.today().isoformat()), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--json",
            "sources",
            str(BOARDS / "pass-rc-divider"),
            "--parts",
            str(parts),
            "--sources",
            str(lib / "sources.csv"),
            "--out",
            str(tmp_path / "o"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    details = json.loads(proc.stdout)[0]["details"]
    assert details["problems"] == [
        "RC0603FR-0710KL datasheet: acme/rc.pdf is an HTML page (it starts b'<html lang=\"ko\">'), "
        "not a PDF (sources.csv:2)"
    ], details
