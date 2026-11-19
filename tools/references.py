"""`workcenter references`: the index of the documents the rules name, fetched once, checked by hash.

The index (`rules/references/index.json`) names each standard, application note and datasheet a rule
pack or a facts file cites: its maker or issuer, number, title, revision, URL and the SHA256 of the copy
the rule was written from. The repository holds the index and never the documents: their terms forbid a
copy. `fetch` asks each URL once under Via's own name and keeps what it gets in a folder
outside every repository, with a ledger of each answer; `check` judges a file a person downloaded;
`rules` fails each document a rule names that the index lacks.

Standard library only, as the CLI is (AGENTS.md invariant 3).
"""

from __future__ import annotations

import ast
import datetime
import hashlib
import json
import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlparse

import clock

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "rules" / "references" / "index.json"
# A held document: its copy is pinned by its SHA256. A report is a held copy that is no standard, note or
# datasheet: a project's technical papers, a laboratory's report (tests/test_xsection.py cites 2). A
# user's guide is a maker's family guide, held as a datasheet is (the MCU block's SLAU272D and SLAU278AH).
HELD = ("standard", "application note", "datasheet", "report", "user's guide")
# A web page has no fixed copy: it is held by the values read from it on a date.
WEB = "web page"
# A paper or a book with no free copy: cited and not held.
CITED = ("paper", "book")
KINDS = (*HELD, WEB, *CITED)
FIELDS = ("id", "kind", "number", "title", "revision", "url", "sha256", "read")
WEB_FIELDS = ("id", "kind", "title", "url", "read")
CITED_FIELDS = ("id", "kind", "authors", "title", "published", "edition", "cited", "no_copy")
VALUES_FORM = 'as [{"says": "...", "for": "..."}]'
CITES_FORM = 'CITES: a dict of index ids to where in each, as {"ti-slva477c": "equation 1"}'
# A place in a document beside its name makes the name a citation (CITES in tools and tests). The word
# is read in any case and abbreviated (Table, Fig., p., §); the number after it keeps its case.
PLACE_RE = re.compile(
    r"(?:(?i:\b(?:sections?|tables?|pages?|pp?\.|clauses?|equations?|eqs?\.|annex(?:es)?|figures?|figs?\.|"
    r"chapters?|ch\.))|§)"
    r"\s*(?:\([0-9A-Z][0-9A-Za-z.\-]*\)|[0-9A-Z](?:[0-9A-Za-z.\-]*[0-9A-Za-z])?)"
)
PLACE_REACH = 200
# A revision or an edition written right after a document's name, before its place: it must be the one
# the entry holds (Rev.1 of a standard the index holds as Rev.2 is another document).
REVISION_RES = (
    ("rev", re.compile(r"\bRev(?:ision)?\.?\s*([0-9]+|[A-Z])\b")),
    ("edition", re.compile(r"\b([0-9]+)(?:st|nd|rd|th)\s+ed(?:ition|\.)", re.IGNORECASE)),
    ("version", re.compile(r"^[\s,]*(?:version\s+|v)?([0-9]+(?:\.[0-9]+)+)\b", re.IGNORECASE)),
)
REVISION_REACH = 40
# A URL runs to white space or a quote; a ")" that closes no "(" of it is the text's, not the URL's.
URL_IN_TEXT_RE = re.compile(r"https?://[^\s\"'<>]+")
# The longest text " ... " may skip in a web page value. On 2026-11-17 the 5 split values of the index
# skipped 9 to 161 characters in the pages fetched that day (JLCPCB's via row is the 161).
GAP_REACH = 200
LEDGER = "ledger.json"
# A site's answer that holds until a person asks again: a refusal is never retried under another name.
FINAL = {"refused", "gone"}
SHA_RE = re.compile(r"[0-9a-f]{64}")
# A rule's own hash may be written in either case, as tools/ratings.py takes it.
RULE_SHA_RE = re.compile(r"[0-9a-fA-F]{64}")
ID_RE = re.compile(r"[a-z0-9][a-z0-9.-]*")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
URL_RE = re.compile(r"https?://[^\s/]+/\S*")
CITING_KEYS = ("document", "source")
# The words by which a source says it has no document to pin: `no datasheet: <why>`.
NONE_RE = re.compile(r"no (datasheet|document): \S.*")
GLOBS = 'rules: a list of globs from the repository\'s root is asked, as ["rules/ratings/*.json"]'
MEND = "mend it or delete it, and run again"
# The documents this file cites, by their ids in rules/references/index.json (`workcenter references rules`).
CITES = {
    "ietf-rfc6585": "section 4, page 3: 429 Too Many Requests",
    "ietf-rfc9110": "section 15.6: Server Error 5xx",
    "freedesktop-basedir-0.8": "section 2: a relative path is invalid and ignored",
}


def shown(path: Path) -> str:
    """A path as a reader types it: from the working folder when it lies under it."""
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def is_globs(value: object) -> bool:
    return isinstance(value, list) and all(
        isinstance(g, str) and g and not g.startswith("/") and ".." not in Path(g).parts for g in value
    )


def entry_problems(doc: dict, tag: str) -> list[str]:
    """The faults of 1 entry's fields that depend on its kind."""
    kind = doc.get("kind")
    fields = WEB_FIELDS if kind == WEB else CITED_FIELDS if kind in CITED else FIELDS
    problems = [
        f"fail {tag}: no {field}"
        for field in fields
        if not isinstance(doc.get(field), str) or not doc[field].strip()
    ]
    if kind in CITED:
        if "sha256" in doc or "url" in doc:
            problems.append(f"fail {tag}: a {kind} is cited and not held; drop url and sha256")
    elif ("maker" in doc) == ("issuer" in doc):
        problems.append(f"fail {tag}: names neither or both of maker and issuer; it names 1")
    if kind == WEB:
        values = doc.get("values")
        if "sha256" in doc:
            problems.append(f"fail {tag}: a web page is held by its values, not by a SHA256; drop sha256")
        if not isinstance(values, list) or not values:
            problems.append(
                f"fail {tag}: no values: a web page is held by the values read from it, {VALUES_FORM}"
            )
        else:
            for k, value in enumerate(values):
                if not isinstance(value, dict) or not all(
                    isinstance(value.get(key), str) and value[key].strip() for key in ("says", "for")
                ):
                    problems.append(f'fail {tag}: values[{k}]: "says" and "for" are asked, each a text')
                elif not parts_of(value["says"]):
                    problems.append(f'fail {tag}: values[{k}]: "says" has no text but " ... "')
    names = doc.get("names", [])
    if not isinstance(names, list) or not all(isinstance(x, str) and x.strip() for x in names):
        problems.append(f"fail {tag}: names: a list of the texts code names it by is asked")
    return problems


def load_numbers(data: dict, where: str) -> tuple[list[re.Pattern], list[str]]:
    """The index's families of document numbers, compiled: (patterns, 1 line per fault)."""
    numbers = data.get("numbers", [])
    if not isinstance(numbers, list):
        return [], [f'fail {where}: numbers: a list is asked, as [{{"pattern": "...", "family": "..."}}]']
    patterns, problems = [], []
    for n, item in enumerate(numbers):
        pattern = item.get("pattern") if isinstance(item, dict) else None
        if not isinstance(pattern, str) or not isinstance(item.get("family"), str):
            problems.append(f'fail {where}: numbers[{n}]: "pattern" and "family" are asked, each a text')
            continue
        try:
            patterns.append(re.compile(pattern))
        except re.error as exc:
            problems.append(
                f"fail {where}: numbers[{n}]: pattern {pattern!r} is not a regular expression ({exc})"
            )
    return patterns, problems


def load_index(path: Path) -> tuple[list[dict], dict, list[str]]:
    """(entries, {"rules": globs, "code": globs, "numbers": patterns}, 1 line per fault of the index)."""
    where = shown(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], {}, [f"fail {where}: no index there"]
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [], {}, [f"fail {where}: not JSON ({exc})"]
    docs = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(docs, list):
        return [], {}, [f"fail {where}: no list under documents"]
    covers = data.get("rules", [])
    if not is_globs(covers):
        return [], {}, [f"fail {where}: {GLOBS}"]
    code = data.get("code", [])
    if not is_globs(code):
        return (
            [],
            {},
            [f'fail {where}: code: a list of globs from the repository\'s root is asked, as ["tools/*.py"]'],
        )
    numbers, problems = load_numbers(data, where)
    ids: dict[str, int] = {}
    shas: dict[str, int] = {}
    for n, doc in enumerate(docs):
        if not isinstance(doc, dict):
            problems.append(f"fail {where} documents[{n}]: not an object")
            continue
        tag = f"{where} documents[{n}] {doc.get('id', '?')}"
        problems += entry_problems(doc, tag)
        checks = (
            ("id", ID_RE, "lower-case letters, digits, dots and hyphens"),
            ("sha256", SHA_RE, "64 lower-case hex digits"),
            ("url", URL_RE, "a whole URL, https://host/path"),
            ("read", DATE_RE, "a date, 2026-11-17"),
        )
        for field, pattern, form in checks:
            value = doc.get(field)
            if isinstance(value, str) and value and not pattern.fullmatch(value):
                problems.append(f"fail {tag}: {field} {value!r} is not {form}")
        if isinstance(doc.get("kind"), str) and doc["kind"] and doc["kind"] not in KINDS:
            problems.append(f"fail {tag}: kind {doc['kind']!r} is none of {', '.join(KINDS)}")
        for key, seen in (("id", ids), ("sha256", shas)):
            value = doc.get(key)
            if isinstance(value, str) and value:
                if value in seen:
                    problems.append(f"fail {tag}: {key} {value} is the {key} of documents[{seen[value]}] too")
                seen.setdefault(value, n)
    return docs, {"rules": covers, "code": code, "numbers": numbers}, problems


# ------------------------------------------------------------------ web pages


def page_text(body: bytes) -> str:
    """A page's text as a reader sees it: tags dropped, entities read, white space collapsed. Scripts are
    kept: a maker's graph data stands in one."""
    import html

    text = re.sub(r"<[^>]+>", " ", body.decode("utf-8", "replace"))
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def parts_of(says: str) -> list[str]:
    """The parts of a value split at " ... ", white space collapsed, the empty ones dropped."""
    return [p.strip() for p in re.sub(r"\s+", " ", says).split("...") if p.strip()]


def part_re(part: str) -> re.Pattern:
    """`part` as written, and where it starts or ends with a digit, at the bound of the page's number:
    0.2 does not stand in 0.25, nor 4 mil in 14 mil."""
    before = r"(?<![0-9.])" if part[0].isdigit() else ""
    after = r"(?!\.?[0-9])" if part[-1].isdigit() else ""
    return re.compile(before + re.escape(part) + after)


def stands(says: str, text: str) -> bool:
    """`says` stands in `text`: each of its parts split at " ... " is found, in order. A part after the
    first stands within GAP_REACH characters of the one before it, and where its first word first stands
    after it: a later row that says the old number does not hold a row whose number moved."""
    parts = parts_of(says)
    at = 0
    for k, part in enumerate(parts):
        found = part_re(part).search(text, at)
        if found is None:
            return False
        if k:
            head = part.split(" ", 1)[0]
            skipped = text[at : found.start()]
            if len(skipped) > GAP_REACH or re.search(rf"(?<!\S){re.escape(head)}(?!\S)", skipped):
                return False
        at = found.end()
    return bool(parts)


def values_gone(doc: dict, body: bytes) -> list[dict]:
    """The values of a web page entry that no longer stand on the page."""
    text = page_text(body)
    return [v for v in doc["values"] if not stands(v["says"], text)]


# ------------------------------------------------------------------ fetch


def default_folder() -> Path:
    """$XDG_CACHE_HOME/ee-workcenter/references, else ~/.cache/... A relative XDG_CACHE_HOME is ignored:
    XDG Base Directory Specification 0.8, section 2 calls such a path invalid. A relative one would also
    put the folder under the working folder, which may lie in a repository."""
    cache = os.environ.get("XDG_CACHE_HOME", "")
    base = Path(cache) if cache and Path(cache).is_absolute() else Path.home() / ".cache"
    return (base / "ee-workcenter" / "references").resolve()


def repository_of(path: Path) -> Path | None:
    """The work tree `path` lies in, if any: the nearest folder above it that holds `.git`."""
    for d in (path, *path.parents):
        if (d / ".git").exists():
            return d
    return None


def outside_repositories(to: Path) -> str:
    """'' when `to` may hold documents, else the 1 line that refuses it."""
    repo = repository_of(to)
    if repo is None:
        return ""
    return (
        f"references: {to} is inside the repository {repo}: a maker's document is never kept in one; "
        "name a folder outside it with --to"
    )


def folder_for(given: str | None) -> tuple[Path, str]:
    """(the folder for the copies, '' or the 1 line that refuses it). The folder is made when it may be."""
    to = Path(given).expanduser().resolve() if given else default_folder()
    refusal = outside_repositories(to)
    if refusal:
        return to, refusal
    if to.exists() and not to.is_dir():
        return to, f"references: {to} is a file; --to names a folder"
    try:
        to.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return to, f"references: {to}: the folder could not be made ({exc.strerror or exc})"
    return to, ""


def record_fault(rec: object) -> str:
    """'' when a ledger record has the shape `fetch` writes, else what is wrong with it."""
    if not isinstance(rec, dict):
        return "an object is asked"
    if not isinstance(rec.get("url"), str):
        return "url: a URL is asked"
    if rec.get("state") not in ("copy", *sorted(FINAL)):
        return f"state: one of copy, {', '.join(sorted(FINAL))} is asked"
    if rec["state"] != "copy":
        return ""
    if not isinstance(rec.get("sha256"), str) or not SHA_RE.fullmatch(rec["sha256"]):
        return "sha256: 64 lower-case hex digits are asked"
    file = rec.get("file")
    if not isinstance(file, str) or not file or Path(file).is_absolute() or ".." in Path(file).parts:
        return "file: a path inside the folder is asked"
    return ""


def read_ledger(to: Path) -> tuple[dict, str]:
    """(the records by id, '' or the 1 line that refuses the ledger). No ledger is an empty one."""
    path = to / LEDGER
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}, ""
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {}, f"references: {path}: not JSON ({exc}); {MEND}"
    docs = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(docs, dict):
        return {}, f"references: {path}: documents: an object of records by id is asked; {MEND}"
    for doc_id, rec in docs.items():
        fault = record_fault(rec)
        if fault:
            return {}, f"references: {path} documents.{doc_id}: {fault}; {MEND}"
    return docs, ""


def write_ledger(to: Path, ledger: dict) -> None:
    part = to / (LEDGER + ".part")
    part.write_text(json.dumps({"documents": ledger}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    part.replace(to / LEDGER)


def suffix_of(name: str) -> str:
    suffix = Path(urlparse(name).path).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,5}", suffix) else ".bin"


def keep(to: Path, doc_id: str, body: bytes, name: str) -> tuple[str, str]:
    """Write a copy as <to>/<id>/<first 16 hex of its SHA256><suffix>: (SHA256, path from `to`)."""
    digest = hashlib.sha256(body).hexdigest()
    rel = f"{doc_id}/{digest[:16]}{suffix_of(name)}"
    dest = to / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    if not dest.is_file() or file_sha256(dest) != digest:
        part = dest.with_name(dest.name + ".part")
        part.write_bytes(body)
        part.replace(dest)
    return digest, rel


def now() -> str:
    """The run's minute in UTC: every record 1 run files carries the same one."""
    return clock.moment().astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%MZ")


def answered(status: str, detail: str) -> str:
    """The state of a fetch that gave no copy. 401 and 403 refuse Via's name and 404 and 410
    say the file is gone: both are filed. 429 limits the rate (RFC 6585, section 4, p 3) and a 5xx says
    the server erred (RFC 9110, section 15.6): `not given`, filed nowhere and asked again. No answer at
    all is `not reached`."""
    if status == "refused" and detail != "HTTP 429":
        return "refused"
    if status == "gone":
        return "gone"
    return "not given" if status in ("refused", "error") else "not reached"


def still_held(to: Path, rec: dict) -> bool:
    """A copy the ledger names is on disk with the hash the ledger gives it."""
    if rec.get("state") != "copy":
        return True
    path = to / str(rec.get("file") or "")
    return path.is_file() and file_sha256(path) == rec.get("sha256")


def judge(doc: dict, rec: dict | None, to: Path) -> dict:
    """1 document's verdict from its ledger record (None: the site was not reached)."""
    out = {
        "id": doc["id"],
        "url": doc["url"],
        "index_sha256": doc.get("sha256"),
        "sha256": None,
        "file": None,
    }
    if rec is None:
        return out | {"state": "not reached"}
    out |= {"at": rec.get("at"), "detail": rec.get("detail")}
    if rec["state"] == "copy" and doc["kind"] == WEB:
        gone = values_gone(doc, (to / rec["file"]).read_bytes())
        state = "moved" if gone else "kept"
        return out | {"state": state, "sha256": rec["sha256"], "file": str(to / rec["file"]), "gone": gone}
    if rec["state"] == "copy":
        state = "kept" if rec["sha256"] == doc["sha256"] else "changed"
        return out | {"state": state, "sha256": rec["sha256"], "file": str(to / rec["file"])}
    return out | {"state": rec["state"]}


def line_of(doc: dict, result: dict, asked: bool) -> str:
    state, doc_id, url = result["state"], doc["id"], doc["url"]
    if state == "kept" and doc["kind"] == WEB:
        text = (
            f"kept {doc_id}: a web page, held by its values: all {len(doc['values'])} read on {doc['read']} "
            f"stand on it; its bytes are not judged [{result['file']}]"
        )
    elif state == "moved":
        first = result["gone"][0]
        text = (
            f'moved {doc_id}: {url} no longer says "{first["says"]}" ({first["for"]}), '
            f"read on {doc['read']}; "
            f"{len(result['gone'])} of {len(doc['values'])} values gone; the copy is in {result['file']}: "
            "read the page, change each rule that took the value, then the entry's values"
        )
    elif state == "kept":
        text = f"kept {doc_id}: {doc['number']}, {doc['revision']}, SHA256 {result['sha256']} "
        text += f"as the index names [{result['file']}]"
    elif state == "changed":
        text = (
            f"changed {doc_id}: {url} gives SHA256 {result['sha256']}, the index names {doc['sha256']}; "
            f"the copy is in {result['file']}: read it against the rules that cite {doc_id} before the "
            "index takes its hash"
        )
    elif state == "refused":
        text = (
            f"refused {doc_id}: {url} answered {result['detail']} to Via's name; not asked again, "
            f"under it or any other: download it by hand, then workcenter references check FILE --id {doc_id}"
        )
    elif state == "gone":
        text = (
            f"gone {doc_id}: {url} answered {result['detail']}; not asked again: find where the maker moved "
            "it and change the URL of its entry in the index"
        )
    elif state == "not given":
        return (
            f"not given {doc_id}: {url} answered {result['detail']}, which gives no copy and no verdict; "
            "nothing recorded, asked again on the next run"
        )
    else:
        return f"not reached {doc_id}: {url}: no answer ({result.get('detail')}); asked again on the next run"
    return text if asked else f"{text} (ledger of {result['at']})"


def cmd_fetch(args, cli) -> int:
    as_json = bool(getattr(args, "json", False) or args.references_json)
    docs, _, problems = load_index(Path(args.index))
    if problems:
        print("\n".join(problems))
        return 1
    by_id = {d["id"]: d for d in docs}
    unknown = [i for i in [*args.ids, *(args.again or [])] if i not in by_id]
    if unknown:
        print(f"references: {', '.join(unknown)} is not in the index {shown(Path(args.index))}")
        return 1
    to, refusal = folder_for(args.to)
    if not refusal:
        ledger, refusal = read_ledger(to)
    if refusal:
        print(refusal)
        return 1
    again = set(args.again or [])
    results, lines, asked = [], [], 0
    for doc in [by_id[i] for i in args.ids] if args.ids else docs:
        if doc["kind"] in CITED:
            results.append({"id": doc["id"], "state": "not held", "asked": False})
            lines.append(
                f"not held {doc['id']}: a {doc['kind']}, cited and not held ({doc['no_copy']}); "
                f"{doc['edition']}, {doc['cited']}: nothing to fetch, nothing judged"
            )
            continue
        rec = ledger.get(doc["id"])
        ask = doc["id"] in again or rec is None or rec.get("url") != doc["url"] or not still_held(to, rec)
        if ask:
            asked += 1
            # judged here by its SHA256 or its values; a web page entry is an HTML page by design
            status, body, detail = cli.fetch_url(doc["url"], judge=False)
            state = "copy" if body is not None else answered(status, detail)
            if body is not None:
                digest, rel = keep(to, doc["id"], body, doc["url"])
                rec = {"url": doc["url"], "state": "copy", "sha256": digest, "file": rel, "at": now()}
                rec["detail"] = detail
            elif state in FINAL:
                rec = {"url": doc["url"], "state": state, "detail": detail, "at": now()}
            else:
                rec = None
                ledger.pop(doc["id"], None)
            if rec is not None:
                ledger[doc["id"]] = rec
            write_ledger(to, ledger)
            result = judge(doc, rec, to)
            if rec is None:
                result |= {"state": state, "detail": detail}
        else:
            result = judge(doc, rec, to)
        results.append(result | {"asked": ask})
        lines.append(line_of(doc, result, ask))
    names = ("kept", "changed", "moved", "refused", "gone", "not given", "not reached", "not held")
    counts = {s: sum(r["state"] == s for r in results) for s in names}
    unjudged = counts["not given"] + counts["not reached"]
    code = (
        1
        if counts["changed"] + counts["moved"] + counts["refused"] + counts["gone"]
        else 2
        if unjudged
        else 0
    )
    if as_json:
        print(json.dumps({"to": str(to), "documents": results, "asked": asked, "counts": counts}, indent=2))
        return code
    held = f", {counts['not held']} not held" if counts["not held"] else ""
    lines.append(
        f"references fetch: {counts['kept']} kept, {counts['changed']} changed, {counts['moved']} moved, "
        f"{counts['refused']} refused, {counts['gone']} gone, {counts['not given']} not given, "
        f"{counts['not reached']} not reached{held}; {asked} asked now"
    )
    print("\n".join(lines))
    return code


# ------------------------------------------------------------------ check


def cmd_check(args, cli) -> int:
    docs, _, problems = load_index(Path(args.index))
    if problems:
        print("\n".join(problems))
        return 1
    path = Path(args.file)
    if not path.is_file():
        print(f"references: no file {path}")
        return 1
    digest = file_sha256(path)
    if args.id:
        doc = next((d for d in docs if d["id"] == args.id), None)
        if doc is None:
            print(f"references: {args.id} is not in the index {shown(Path(args.index))}")
            return 1
        if doc["kind"] in CITED:
            print(
                f"references: {args.id} is a {doc['kind']} the index cites and does not hold: "
                "nothing to check"
            )
            return 1
        if doc["kind"] == WEB:
            return check_page(args, doc, path, digest)
        if doc["sha256"] != digest:
            print(
                f"changed {path}: SHA256 {digest}, the index names {doc['sha256']} for {doc['id']} "
                f"({doc['number']}, {doc['revision']}): another revision, or a copy the site changed"
            )
            return 1
    else:
        doc = next((d for d in docs if d.get("sha256") == digest), None)
        if doc is None:
            print(f"unknown {path}: the index names no document with SHA256 {digest}")
            return 1
    lines = [
        f"same {path}: {doc['id']}, {doc['number']}, {doc['revision']}, SHA256 {digest}, the copy the "
        "index names"
    ]
    return keep_given(args, doc, path, digest, lines)


def check_page(args, doc: dict, path: Path, digest: str) -> int:
    """A saved web page: the same page when every value read from it stands in it."""
    gone = values_gone(doc, path.read_bytes())
    if gone:
        first = gone[0]
        print(f'moved {path}: no longer says "{first["says"]}" ({first["for"]}), read on {doc["read"]}')
        return 1
    lines = [
        f"same {path}: {doc['id']}, a web page: all {len(doc['values'])} values read on {doc['read']} "
        "stand in it"
    ]
    return keep_given(args, doc, path, digest, lines)


def keep_given(args, doc: dict, path: Path, digest: str, lines: list[str]) -> int:
    """Print `lines`, and with --keep file the given copy in the folder as `fetch` would have."""
    if args.keep:
        to, refusal = folder_for(args.to)
        if not refusal:
            ledger, refusal = read_ledger(to)
        if refusal:
            print(refusal)
            return 1
        _, rel = keep(to, doc["id"], path.read_bytes(), path.name)
        ledger[doc["id"]] = {
            "url": doc["url"],
            "state": "copy",
            "sha256": digest,
            "file": rel,
            "at": now(),
            "detail": f"given: {path.resolve()}",
        }
        write_ledger(to, ledger)
        lines.append(f"kept in {to / rel}")
    print("\n".join(lines))
    return 0


# ------------------------------------------------------------------ rules


def cited(data, pointer: str = ""):
    """Each (sort, pointer, value) of a rule file. `source`: an object it cites a document by, under a key
    `document` or `source` at any depth, or an object of a table `documents: {id: {...}}` (rules/copper's
    materials.json and rules/interfaces/ name their documents so, and each constant points at an id).
    `named`: a text under such a key. `text`: any other text, which is read for names as code is."""
    if isinstance(data, dict):
        for key, value in data.items():
            here = f"{pointer}.{key}" if pointer else key
            if key in CITING_KEYS and isinstance(value, dict):
                yield "source", here, value
            elif key in CITING_KEYS and isinstance(value, str):
                yield "named", here, value
            elif (
                key == "documents"
                and isinstance(value, dict)
                and all(isinstance(v, dict) for v in value.values())
            ):
                for doc_id, doc in value.items():
                    if isinstance(doc.get("document"), dict):
                        # an entry that holds its document under `document` (rules/blocks/usbc.json)
                        yield from cited(doc, f"{here}.{doc_id}")
                    else:
                        yield "source", f"{here}.{doc_id}", doc
            else:
                yield from cited(value, here)
    elif isinstance(data, list):
        for n, value in enumerate(data):
            yield from cited(value, f"{pointer}[{n}]")
    elif isinstance(data, str):
        yield "text", pointer, data


def rule_files(paths: list[str], globs: dict) -> list[Path]:
    """The files to read: those named (a folder gives its JSON, fab rule and Python files), else the
    files the index's `rules` and `code` globs find."""
    if paths:
        found: list[Path] = []
        for p in map(Path, paths):
            if p.is_dir():
                found += sorted(q for pattern in ("*.json", "*.kicad_dru", "*.py") for q in p.rglob(pattern))
            else:
                found.append(p)
        return found
    patterns = [*globs["rules"], *globs["code"]]
    return sorted({p for pattern in patterns for p in ROOT.glob(pattern) if p.is_file()})


def kind_of_file(path: Path) -> str:
    if path.suffix == ".json":
        return "json"
    if path.suffix == ".kicad_dru":
        return "dru"
    return "code"


def read_cites(tree, where: str, ids: set[str]) -> tuple[dict[str, str], list[str], int]:
    """(the file's CITES, its fail lines, the count of its ids in the index)."""
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else None
        target = node.target if isinstance(node, ast.AnnAssign) else target
        if isinstance(target, ast.Name) and target.id == "CITES" and node.value is not None:
            break
    else:
        return {}, [], 0
    try:
        cites = ast.literal_eval(node.value)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        # TypeError: a literal that cannot be built, as a list for a key (unhashable).
        cites = None
    if not isinstance(cites, dict) or not all(isinstance(k, str) for k in cites):
        return {}, [f"fail {where}:{node.lineno}: {CITES_FORM}"], 0
    fails = []
    for doc_id, place in cites.items():
        if not isinstance(place, str) or not place.strip():
            fails.append(f'fail {where}:{node.lineno}: CITES {doc_id}: where in it is asked, as "equation 1"')
        elif doc_id not in ids:
            fails.append(f"fail {where}:{node.lineno}: CITES names {doc_id}, which the index lacks")
    return cites, fails, sum(doc_id in ids for doc_id in cites)


def name_hits(
    text: str, docs: list[dict], numbers: list[re.Pattern]
) -> list[tuple[int, int, str, str | None]]:
    """Each document name in `text`, as (start, end, the name, the id of the entry it names or None): the
    `names` of the entries, and the numbers of the index's families. A number is matched to an entry's
    name with spaces and hyphens set aside (RFC6585 is RFC 6585). A URL is no name: its text is skipped.
    Overlapping hits keep the first."""
    by_name = {name: d["id"] for d in docs for name in d.get("names", [])}
    by_key = {name_key(name): doc_id for name, doc_id in by_name.items()}
    text = URL_IN_TEXT_RE.sub(lambda m: " " * len(m.group(0)), text)
    hits = []
    for name, doc_id in by_name.items():
        for m in re.finditer(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text):
            hits.append((m.start(), m.end(), name, doc_id))
    for pattern in numbers:
        for m in pattern.finditer(text):
            hits.append((m.start(), m.end(), m.group(0), by_key.get(name_key(m.group(0)))))
    kept: list[tuple[int, int, str, str | None]] = []
    for hit in sorted(hits, key=lambda h: (h[0], -h[1])):
        if not kept or hit[0] >= kept[-1][1]:
            kept.append(hit)
    return kept


def name_key(name: str) -> str:
    return re.sub(r"[\s-]", "", name).upper()


def urls_in(line: str) -> list[str]:
    """Each URL in a line of text: to white space or a quote, less the stops and the ")" that close no
    "(" of it."""
    found = []
    for m in URL_IN_TEXT_RE.finditer(line):
        url = m.group(0)
        while url and (url[-1] in ".,;:" or (url[-1] == ")" and url.count(")") > url.count("("))):
            url = url[:-1]
        found.append(url)
    return found


def place_after(text: str, end: int) -> tuple[str, str]:
    """(the first place in a document (section 2, equation (4), pp. 407) within PLACE_REACH characters
    after a name, the text between the name and it), comment marks and line breaks read as 1 space;
    ('', '') when there is none."""
    after = re.sub(r"\s*\n\s*(?:#\s*)?", " ", text[end : end + 3 * PLACE_REACH])[:PLACE_REACH]
    m = PLACE_RE.search(after)
    return (m.group(0), after[: m.start()]) if m else ("", "")


def other_revision(between: str, doc: dict) -> str:
    """The revision or edition written between a name and its place when the entry holds another one,
    as written ('Rev.1', '2nd edition', '0.6'); '' when none is written or it is the entry's."""
    between = between[:REVISION_REACH]
    held = " ".join(str(doc.get(k) or "") for k in ("id", "number", "title", "revision", "edition")).lower()
    for sort, pattern in REVISION_RES:
        m = pattern.search(between)
        if not m:
            continue
        mark = re.escape(m.group(1).lower())
        same = {
            "rev": rf"\brev(?:ision)?\.?\s*{mark}(?![0-9a-z])",
            "edition": rf"(?<![0-9]){mark}(?:st|nd|rd|th)\s+edition",
            "version": rf"(?<![0-9.]){mark}(?!\.?[0-9])",
        }[sort]
        if not re.search(same, held):
            return m.group(0).strip(" ,")
    return ""


def entry_label(doc: dict) -> str:
    name = doc.get("number") or doc.get("title") or doc["id"]
    return ", ".join(str(x) for x in (name, doc.get("revision") or doc.get("edition")) if x)


def names_in(
    text: str, docs: list[dict], numbers: list[re.Pattern], declared: dict
) -> tuple[list[tuple[int, str, str, str | None]], list[tuple[int, str, str, str, dict]], dict[str, int]]:
    """The documents a text names: (citations as (line, name, place, entry id or None), other revisions
    as (line, name, place, as written, the entry), mentions as {name: line}). A citation of an entry
    `declared` names is left out; each name counts once, at its first citation."""
    by_id = {d["id"]: d for d in docs}
    cited_at: dict[str, tuple[int, str, str, str | None]] = {}
    mentioned_at: dict[str, int] = {}
    others: list[tuple[int, str, str, str, dict]] = []
    for start, end, name, doc_id in name_hits(text, docs, numbers):
        line = text.count("\n", 0, start) + 1
        place, between = place_after(text, end)
        if place and doc_id is not None:
            mark = other_revision(between, by_id[doc_id])
            if mark:
                others.append((line, name, place, mark, by_id[doc_id]))
                continue
        if doc_id is not None and doc_id in declared:
            continue
        if place:
            cited_at.setdefault(name, (line, name, place, doc_id))
        else:
            mentioned_at.setdefault(name, line)
    mentions = {name: line for name, line in mentioned_at.items() if name not in cited_at}
    return list(cited_at.values()), others, mentions


UNKNOWN_NAME = (
    "the index has no document by that name; fetch it and add its entry "
    "(rules/references/README.md, An entry)"
)
IN_CITES = "the file's CITES"


def revision_fail(at: str, name: str, place: str, mark: str, doc: dict) -> str:
    return (
        f"fail {at}: {name}, {place}: {mark} is named beside it; the index holds {doc['id']} "
        f"({entry_label(doc)}): cite that copy, or fetch {mark} and add its entry"
    )


def mention_line(at: str, name: str) -> str:
    return (
        f"not judged {at}: {name} has no section, table, page, clause or equation beside it: "
        "a mention, not a citation"
    )


def check_code(
    path: Path, docs: list[dict], numbers: list[re.Pattern]
) -> tuple[list[str], list[str], int, int]:
    """(fail lines, not judged lines, documents named, documents held) of 1 file of tool code or tests."""
    where = shown(path)
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (OSError, UnicodeDecodeError) as exc:
        return [f"fail {where}: not read ({exc})"], [], 0, 0
    except SyntaxError as exc:
        return [f"fail {where}: not read as Python ({exc.msg}, line {exc.lineno})"], [], 0, 0
    cites, fails, held = read_cites(tree, where, {d["id"] for d in docs})
    citations, others, mentions = names_in(text, docs, numbers, cites)
    for line, name, place, doc_id in citations:
        if doc_id is None:
            fails.append(
                f"fail {where}:{line}: {name}, {place}: {UNKNOWN_NAME}, then name its id in {IN_CITES}"
            )
        else:
            fails.append(
                f"fail {where}:{line}: {name}, {place}: the file's CITES does not name {doc_id}; "
                f'add "{doc_id}": "<where in it>" to it'
            )
    fails += [revision_fail(f"{where}:{line}", *rest) for line, *rest in others]
    unjudged = [mention_line(f"{where}:{line}", name) for name, line in mentions.items()]
    return fails, unjudged, len(cites) + len(citations) + len(others), held


def check_texts(
    texts: list[tuple[Callable[[int], str], str]], docs: list[dict], numbers: list[re.Pattern]
) -> tuple[list[str], list[str], int, int]:
    """(fail lines, not judged lines, documents named, documents held) of the names in texts with no CITES,
    a fab rule file's or a JSON rule's, each given as (where its line n stands, the text). A citation of
    an entry is held, and of any other name fails. Each name counts once in all the texts."""
    fails, mentioned, counted = [], {}, set()
    named = held = 0
    for at, text in texts:
        citations, others, mentions = names_in(text, docs, numbers, {})
        for line, name, place, doc_id in citations:
            if name in counted:
                continue
            counted.add(name)
            named += 1
            if doc_id is None:
                fails.append(f"fail {at(line)}: {name}, {place}: {UNKNOWN_NAME}")
            else:
                held += 1
        for line, *rest in others:
            named += 1
            fails.append(revision_fail(at(line), *rest))
        for name, line in mentions.items():
            mentioned.setdefault(name, at(line))
    unjudged = [mention_line(at, name) for name, at in mentioned.items() if name not in counted]
    return fails, unjudged, named, held


def check_dru(
    path: Path, docs: list[dict], numbers: list[re.Pattern]
) -> tuple[list[str], list[str], int, int]:
    """(fail lines, not judged lines, documents named, documents held) of a KiCad rule file: each URL in it
    is an entry's URL, and each document it names by number is read as a JSON rule's text is."""
    where = shown(path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"fail {where}: not read ({exc})"], [], 0, 0
    urls = {d["url"] for d in docs if isinstance(d.get("url"), str)}
    seen: dict[str, int] = {}
    for n, line in enumerate(text.splitlines(), 1):
        for url in urls_in(line):
            seen.setdefault(url, n)
    fails = [
        f"fail {where}:{n}: {url} is not the URL of an entry of the index; add the page as a web page entry "
        "with the values the rules take from it"
        for url, n in seen.items()
        if url not in urls
    ]
    more, unjudged, named, held = check_texts([(lambda line: f"{where}:{line}", text)], docs, numbers)
    return fails + more, unjudged, len(seen) + named, len(seen) - len(fails) + held


def label_of(source: dict) -> str:
    name = source.get("number") or source.get("document") or source.get("title") or "a document"
    return ", ".join(str(x) for x in (name, source.get("revision")) if x)


def cmd_rules(args, cli) -> int:
    index = Path(args.index)
    docs, globs, problems = load_index(index)
    if problems:
        print("\n".join(problems))
        return 1
    files = rule_files(args.paths, globs)
    if not files:
        print(f"references: no rule file to read: name 1, or list globs under rules in {shown(index)}")
        return 1
    by_sha = {d["sha256"]: d for d in docs if "sha256" in d}
    pages = {d["url"] for d in docs if d["kind"] == WEB}
    fails, unjudged, named, held = [], [], 0, 0
    for path in files:
        where = shown(path)
        if kind_of_file(path) == "code":
            more, not_judged, n, h = check_code(path, docs, globs["numbers"])
            fails, unjudged, named, held = fails + more, unjudged + not_judged, named + n, held + h
            continue
        if kind_of_file(path) == "dru":
            more, not_judged, n, h = check_dru(path, docs, globs["numbers"])
            fails, unjudged, named, held = fails + more, unjudged + not_judged, named + n, held + h
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            fails.append(f"fail {where}: not read as JSON ({exc})")
            continue
        found = list(cited(data))
        local = {m.group(1) for _, p, _ in found if (m := re.search(r"(?:^|\.)documents\.(.+)$", p))}
        texts, ids_named = [], set()
        for sort, pointer, value in found:
            tag = f"{where} {pointer}"
            if sort == "text":
                texts.append(((lambda line, tag=tag: tag), value))
            elif sort == "named" and NONE_RE.fullmatch(value):
                unjudged.append(f"not judged {tag}: names no document with a URL and a SHA256 ({value})")
            elif sort == "named" and value in local:
                continue  # the file's own `documents` object holds it, and is judged there
            elif sort == "named" and value in {d["id"] for d in docs}:
                named, held = named + (value not in ids_named), held + (value not in ids_named)
                ids_named.add(value)
            elif sort == "named":
                named += 1
                fails.append(
                    f"fail {tag}: {value} names a document by name alone: write it as an object with its URL "
                    "and SHA256, or `no datasheet: <why>`"
                )
        for sort, pointer, source in found:
            if sort != "source":
                continue
            url, digest, label = source.get("url"), source.get("sha256"), label_of(source)
            # A document served in a zip (usb.org's): the zip is the copy the URL gives, and the index
            # holds it; `sha256` is then the file inside.
            if source.get("zip_sha256") is not None:
                digest = source["zip_sha256"]
            tag = f"{where} {pointer}"
            document = source.get("document")
            if not url and not digest and isinstance(document, str) and NONE_RE.fullmatch(document):
                unjudged.append(f"not judged {tag}: names no document with a URL and a SHA256 ({document})")
                continue
            named += 1
            if url is not None and not isinstance(url, str):
                fails.append(f"fail {tag}: url {url!r} is not a whole URL, https://host/path")
            elif url in pages:
                # A web page is held by its values; a SHA256 the source gives names its own copy.
                held += 1
            elif digest is not None and not (isinstance(digest, str) and RULE_SHA_RE.fullmatch(digest)):
                fails.append(f"fail {tag}: sha256 {digest!r} is not 64 hex digits")
            elif not url and not digest:
                fails.append(
                    f"fail {tag}: {label} names no URL and no SHA256: write both from the copy it was read "
                    "from, or `no datasheet: <why>` as its document"
                )
            elif not digest:
                fails.append(f"fail {tag}: {label} names {url} and no SHA256 of the copy it was written from")
            elif not url:
                fails.append(f"fail {tag}: {label} has SHA256 {digest} and no URL to fetch it from")
            elif digest.lower() not in by_sha:
                fails.append(f"fail {tag}: {label}, SHA256 {digest} is not in the index {shown(index)}")
            elif by_sha[digest.lower()]["url"] != url:
                entry = by_sha[digest.lower()]
                fails.append(
                    f"fail {tag}: {label} is at {url}, the index names {entry['id']} at {entry['url']}"
                )
            else:
                held += 1
        more, not_judged, n, h = check_texts(texts, docs, globs["numbers"])
        fails, unjudged, named, held = fails + more, unjudged + not_judged, named + n, held + h
    summary = (
        f"references rules: {named} documents named in {len(files)} files, {held} in the index, "
        f"{named - held} not; {len(unjudged)} not judged"
    )
    print("\n".join([*fails, *unjudged, summary]))
    return 1 if fails else 0


def register(sub, cli) -> None:
    """Add `references` to Via's parser; each command sets `run` to its handler."""
    p = sub.add_parser(
        "references",
        help="the index of the standards, makers' notes and datasheets the rules name: fetch each once "
        "into a folder outside the repository, check a file a person downloaded, and fail a rule that "
        "names a document the index lacks",
    )
    rsub = p.add_subparsers(dest="references_command", required=True)

    def add(name: str, help_text: str):
        q = rsub.add_parser(name, help=help_text)
        q.add_argument("--index", default=str(INDEX), help="the index (default rules/references/index.json)")
        return q

    q = add(
        "fetch",
        "GET each document of the index once, as Via, into --to; a later run answers from the "
        "folder's ledger.json and asks again for none",
    )
    q.add_argument("--json", dest="references_json", action="store_true", help="machine-readable output")
    q.add_argument("ids", nargs="*", help="the index ids to fetch (default: every one)")
    q.add_argument(
        "--to", help="the folder outside every repository (default ~/.cache/ee-workcenter/references)"
    )
    q.add_argument("--again", action="append", metavar="ID", help="ask once more for this id (repeatable)")
    q.set_defaults(run=lambda a: cmd_fetch(a, cli))
    q = add("check", "say whether a file a person downloaded is the copy the index names")
    q.add_argument("file", help="the downloaded file")
    q.add_argument("--id", help="the index id the file should be (default: found by its SHA256)")
    q.add_argument(
        "--keep", action="store_true", help="file the copy in --to, as fetch does, when it is the same"
    )
    q.add_argument("--to", help="the folder for --keep (default ~/.cache/ee-workcenter/references)")
    q.set_defaults(run=lambda a: cmd_check(a, cli))
    q = add("rules", "fail each document a rule pack or facts file names that the index lacks")
    q.add_argument("paths", nargs="*", help="rule files or folders (default: the globs the index lists)")
    q.set_defaults(run=lambda a: cmd_rules(a, cli))


if __name__ == "__main__":
    sys.exit("run as: workcenter references ...")
