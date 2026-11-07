"""`workcenter fetch`: one file for a library, fetched once under the workcenter's own name, and its
sources.csv row (PROCESSES.md P27).

A local server plays the maker's site: it serves the test's files, answers 403 under /refused, and
records every User-Agent it is sent. The library is built in each test's tmp_path.
"""

from __future__ import annotations

import datetime
import hashlib
import http.server
import importlib.machinery
import io
import json
import subprocess
import sys
import threading
import types
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"

MODEL = (
    "* Acme divider model\n* Model Version: 2.1, Date: 02/02/2007\n.SUBCKT RDIV IN OUT GND\nR1 IN OUT 100\n"
)
MODEL += "R2 OUT GND 100\n.ENDS\n"
DATASHEET = "ACME-1 buck regulator\nDatasheet Rev C, 2025-11\n"
HEADER = "MPN,Kind,URL,File,Member,Revision,Dated,Subckt,Ngspice,SHA256,Checked,Note"
# A row already in the library, written by hand with CRLF line ends, which the append must keep.
OLD_ROW = "ACME-1,datasheet,https://example.com/acme-1.pdf,acme/acme-1.pdf,,Rev B,2024-01,,,,"
OLD_ROW += '2026-10-01,"kept, by hand"'


def load_cli():
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_fetch", str(CLI))
    module = types.ModuleType("workcenter_cli_fetch")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module
    loader.exec_module(module)
    return module


def fetch(*args: object) -> tuple[int, dict]:
    proc = subprocess.run(
        [sys.executable, str(CLI), "--json", "fetch", *map(str, args)],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, (json.loads(proc.stdout) if proc.stdout.strip() else {})


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Maker(http.server.BaseHTTPRequestHandler):
    """Serves the test's files; /refused answers 403 the way a bot wall does."""

    root: Path = Path()
    agents: list[str] = []

    def do_GET(self):  # noqa: N802 (the handler's name is http.server's)
        Maker.agents.append(self.headers.get("User-Agent", ""))
        path = Maker.root / self.path.lstrip("/")
        if self.path.startswith("/refused"):
            self.send_response(403)
            self.end_headers()
        elif path.is_file():
            body = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


@pytest.fixture
def site(tmp_path):
    """(base URL, served folder, library folder with a CRLF sources.csv holding one row)."""
    served = tmp_path / "served"
    served.mkdir()
    (served / "rdiv.lib").write_text(MODEL, encoding="utf-8")
    (served / "acme-2.txt").write_text(DATASHEET, encoding="utf-8")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("models/RDIV.lib", MODEL)
        zf.writestr("readme.txt", "not a model")
    (served / "models.zip").write_bytes(buf.getvalue())
    lib = tmp_path / "library"
    lib.mkdir()
    (lib / "sources.csv").write_bytes(f"{HEADER}\r\n{OLD_ROW}\r\n".encode())
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Maker)
    Maker.root, Maker.agents = served, []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}", served, lib
    finally:
        server.shutdown()


def test_fetch_keeps_the_file_and_prints_its_row(site):
    url, served, lib = site
    before = (lib / "sources.csv").read_bytes()
    code, report = fetch(f"{url}/rdiv.lib", "--to", lib / "acme" / "rdiv.lib", "--mpn", "ACME-R")
    assert code == 0, report
    kept = lib / "acme" / "rdiv.lib"
    assert kept.read_bytes() == (served / "rdiv.lib").read_bytes()
    assert report["state"] == "written"
    row = report["row"]
    assert list(row) == HEADER.split(",")  # in the library's own column order
    assert row["MPN"] == "ACME-R" and row["Kind"] == "spice"  # the kind from the suffix
    assert row["URL"] == f"{url}/rdiv.lib" and row["File"] == "acme/rdiv.lib"
    assert row["SHA256"] == sha(MODEL.encode()) and row["Subckt"] == "RDIV"
    assert row["Checked"] == datetime.date.today().isoformat()
    assert row["Revision"] == "" and row["Dated"] == ""  # the reader fills these from the file
    assert report["revision_lines"] == ["Model Version: 2.1, Date: 02/02/2007"]
    assert Maker.agents == [load_cli().FETCH_AGENT]  # one request, under the workcenter's own name
    assert (lib / "sources.csv").read_bytes() == before  # without --row the library's rows stay as they are
    # the same file again: nothing to write
    code, report = fetch(f"{url}/rdiv.lib", "--to", kept)
    assert code == 0 and report["state"] == "unchanged", report


def test_fetch_row_appends_once_in_the_files_own_line_ends(site):
    url, _, lib = site
    before = (lib / "sources.csv").read_bytes()
    args = ("--to", lib / "acme" / "acme-2.txt", "--mpn", "ACME-2", "--kind", "datasheet", "--row")
    code, report = fetch(f"{url}/acme-2.txt", *args)
    assert code == 0, report
    after = (lib / "sources.csv").read_bytes()
    assert after.startswith(before)  # the rows already there keep their bytes
    added = after[len(before) :]
    assert added.endswith(b"\r\n") and added.count(b"\n") == 1, added
    digest = sha(DATASHEET.encode())
    today = datetime.date.today().isoformat()
    assert added == f"ACME-2,datasheet,{url}/acme-2.txt,acme/acme-2.txt,,,,,,{digest},{today},\r\n".encode()
    assert load_cli().read_sources(lib / "sources.csv")[-1].mpn == "ACME-2"
    # a second row for the same part and kind is refused before anything is asked of the site
    requests = len(Maker.agents)
    code, report = fetch(f"{url}/acme-2.txt", *args)
    assert code == 1
    assert "already has a datasheet row for ACME-2" in report["error"]
    assert len(Maker.agents) == requests
    assert (lib / "sources.csv").read_bytes() == after


def test_a_refusal_is_the_sites_answer_and_nothing_is_written(site):
    url, _, lib = site
    before = (lib / "sources.csv").read_bytes()
    dest = lib / "acme" / "walled.pdf"
    code, report = fetch(f"{url}/refused/walled.pdf", "--to", dest, "--mpn", "ACME-3", "--row")
    assert code == 1
    assert report["status"] == "refused" and "HTTP 403" in report["error"]
    assert len(Maker.agents) == 1  # asked once, never again in another guise
    assert not dest.exists() and not dest.parent.exists()
    assert (lib / "sources.csv").read_bytes() == before


def test_an_existing_file_that_differs_is_left_alone(site):
    url, _, lib = site
    dest = lib / "acme" / "rdiv.lib"
    dest.parent.mkdir()
    dest.write_text("* an older model kept by hand\n", encoding="utf-8")
    code, report = fetch(f"{url}/rdiv.lib", "--to", dest)
    assert code == 1
    assert "exists and differs" in report["error"]
    assert dest.read_text(encoding="utf-8") == "* an older model kept by hand\n"


def test_a_zip_members_bytes_are_kept(site):
    url, _, lib = site
    dest = lib / "acme" / "RDIV.lib"
    code, report = fetch(f"{url}/models.zip", "--to", dest, "--member", "models/RDIV.lib", "--mpn", "ACME-R")
    assert code == 0, report
    assert dest.read_text(encoding="utf-8") == MODEL
    assert report["row"]["Member"] == "models/RDIV.lib" and report["row"]["URL"] == f"{url}/models.zip"
    code, report = fetch(f"{url}/models.zip", "--to", lib / "acme" / "x.lib", "--member", "models/none.lib")
    assert code == 1 and "no member" in report["error"]


def test_a_row_needs_a_library_and_a_part_number(site, tmp_path):
    url, _, lib = site
    loose = tmp_path / "loose" / "maker" / "rdiv.lib"
    code, report = fetch(f"{url}/rdiv.lib", "--to", loose, "--mpn", "ACME-R", "--row")
    assert code == 1 and "no sources.csv" in report["error"]
    code, report = fetch(f"{url}/rdiv.lib", "--to", lib / "acme" / "rdiv.lib", "--row")
    assert code == 1 and "--row needs --mpn" in report["error"]
    assert Maker.agents == []  # refused before any request
    # without --row a loose file still gets its row printed, the path taken as <library>/<maker>/<file>
    code, report = fetch(f"{url}/rdiv.lib", "--to", loose, "--mpn", "ACME-R")
    assert code == 0 and report["row"]["File"] == "maker/rdiv.lib", report
    # --sources may name a library not started yet: it gets the header, then the row
    fresh = tmp_path / "fresh" / "sources.csv"
    code, report = fetch(
        f"{url}/rdiv.lib",
        "--to",
        fresh.parent / "acme" / "rdiv.lib",
        "--mpn",
        "ACME-R",
        "--sources",
        fresh,
        "--row",
    )
    assert code == 0, report
    assert fresh.read_text(encoding="utf-8").splitlines()[0] == HEADER
    assert [r.mpn for r in load_cli().read_sources(fresh)] == ["ACME-R"]
