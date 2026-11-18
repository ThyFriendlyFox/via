"""`workcenter references`: the index of the documents the rules name, fetched once, checked by hash.

The index (`rules/references/index.json`) names each standard, application note and datasheet a rule
pack or a facts file cites: its maker or issuer, number, title, revision, URL and the SHA256 of the copy
the rule was written from. The repository holds the index and never the documents: their terms forbid a
copy. `fetch` asks each URL once under the workcenter's own name and keeps what it gets in a folder
outside every repository, with a ledger of each answer; `check` judges a file a person downloaded;
`rules` fails each document a rule names that the index lacks.

Standard library only, as the CLI is (AGENTS.md invariant 3).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import clock

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "rules" / "references" / "index.json"
KINDS = ("standard", "application note", "datasheet")
FIELDS = ("id", "kind", "number", "title", "revision", "url", "sha256", "read")
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


def load_index(path: Path) -> tuple[list[dict], list[str], list[str]]:
    """(entries, the globs of the files whose documents it covers, 1 line per fault of the index)."""
    where = shown(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], [], [f"fail {where}: no index there"]
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return [], [], [f"fail {where}: not JSON ({exc})"]
    docs = data.get("documents") if isinstance(data, dict) else None
    if not isinstance(docs, list):
        return [], [], [f"fail {where}: no list under documents"]
    covers = data.get("rules", [])
    if not isinstance(covers, list) or not all(
        isinstance(g, str) and g and not g.startswith("/") and ".." not in Path(g).parts for g in covers
    ):
        return [], [], [f"fail {where}: {GLOBS}"]
    problems: list[str] = []
    ids: dict[str, int] = {}
    shas: dict[str, int] = {}
    for n, doc in enumerate(docs):
        if not isinstance(doc, dict):
            problems.append(f"fail {where} documents[{n}]: not an object")
            continue
        tag = f"{where} documents[{n}] {doc.get('id', '?')}"
        for field in FIELDS:
            if not isinstance(doc.get(field), str) or not doc[field].strip():
                problems.append(f"fail {tag}: no {field}")
        if ("maker" in doc) == ("issuer" in doc):
            problems.append(f"fail {tag}: names neither or both of maker and issuer; it names 1")
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
    return docs, covers, problems


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
    """The state of a fetch that gave no copy. 401 and 403 refuse the workcenter's name and 404 and 410
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
    out = {"id": doc["id"], "url": doc["url"], "index_sha256": doc["sha256"], "sha256": None, "file": None}
    if rec is None:
        return out | {"state": "not reached"}
    out |= {"at": rec.get("at"), "detail": rec.get("detail")}
    if rec["state"] == "copy":
        state = "kept" if rec["sha256"] == doc["sha256"] else "changed"
        return out | {"state": state, "sha256": rec["sha256"], "file": str(to / rec["file"])}
    return out | {"state": rec["state"]}


def line_of(doc: dict, result: dict, asked: bool) -> str:
    state, doc_id, url = result["state"], doc["id"], doc["url"]
    if state == "kept":
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
            f"refused {doc_id}: {url} answered {result['detail']} to the workcenter's name; not asked again, "
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
        rec = ledger.get(doc["id"])
        ask = doc["id"] in again or rec is None or rec.get("url") != doc["url"] or not still_held(to, rec)
        if ask:
            asked += 1
            status, body, detail = cli.fetch_url(doc["url"])
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
    names = ("kept", "changed", "refused", "gone", "not given", "not reached")
    counts = {s: sum(r["state"] == s for r in results) for s in names}
    unjudged = counts["not given"] + counts["not reached"]
    code = 1 if counts["changed"] + counts["refused"] + counts["gone"] else 2 if unjudged else 0
    if as_json:
        print(json.dumps({"to": str(to), "documents": results, "asked": asked, "counts": counts}, indent=2))
        return code
    lines.append(
        f"references fetch: {counts['kept']} kept, {counts['changed']} changed, {counts['refused']} refused, "
        f"{counts['gone']} gone, {counts['not given']} not given, {counts['not reached']} not reached; "
        f"{asked} asked now"
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
        if doc["sha256"] != digest:
            print(
                f"changed {path}: SHA256 {digest}, the index names {doc['sha256']} for {doc['id']} "
                f"({doc['number']}, {doc['revision']}): another revision, or a copy the site changed"
            )
            return 1
    else:
        doc = next((d for d in docs if d["sha256"] == digest), None)
        if doc is None:
            print(f"unknown {path}: the index names no document with SHA256 {digest}")
            return 1
    lines = [
        f"same {path}: {doc['id']}, {doc['number']}, {doc['revision']}, SHA256 {digest}, the copy the "
        "index names"
    ]
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
    """Each (pointer, object) a rule file cites a document by: the object under a key `document` or
    `source`, at any depth, and each object of a table `documents: {id: {...}}` (rules/copper's
    materials.json names its documents so, and each constant points at an id)."""
    if isinstance(data, dict):
        for key, value in data.items():
            here = f"{pointer}.{key}" if pointer else key
            if key in CITING_KEYS and isinstance(value, dict):
                yield here, value
            elif key == "documents" and isinstance(value, dict):
                for name, doc in value.items():
                    if isinstance(doc, dict):
                        yield f"{here}.{name}", doc
            else:
                yield from cited(value, here)
    elif isinstance(data, list):
        for n, value in enumerate(data):
            yield from cited(value, f"{pointer}[{n}]")


def rule_files(paths: list[str], covers: list[str]) -> list[Path]:
    if paths:
        found: list[Path] = []
        for p in map(Path, paths):
            found += sorted(p.rglob("*.json")) if p.is_dir() else [p]
        return found
    return sorted({p for pattern in covers for p in ROOT.glob(pattern) if p.is_file()})


def label_of(source: dict) -> str:
    name = source.get("number") or source.get("document") or source.get("title") or "a document"
    return ", ".join(str(x) for x in (name, source.get("revision")) if x)


def cmd_rules(args, cli) -> int:
    index = Path(args.index)
    docs, covers, problems = load_index(index)
    if problems:
        print("\n".join(problems))
        return 1
    files = rule_files(args.paths, covers)
    if not files:
        print(f"references: no rule file to read: name 1, or list globs under rules in {shown(index)}")
        return 1
    by_sha = {d["sha256"]: d for d in docs}
    fails, unjudged, named, held = [], [], 0, 0
    for path in files:
        where = shown(path)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            fails.append(f"fail {where}: not read as JSON ({exc})")
            continue
        for pointer, source in cited(data):
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
    summary = (
        f"references rules: {named} documents named in {len(files)} files, {held} in the index, "
        f"{named - held} not; {len(unjudged)} not judged"
    )
    print("\n".join([*fails, *unjudged, summary]))
    return 1 if fails else 0


def register(sub, cli) -> None:
    """Add `references` to the workcenter's parser; each command sets `run` to its handler."""
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
        "GET each document of the index once, as the workcenter, into --to; a later run answers from the "
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
