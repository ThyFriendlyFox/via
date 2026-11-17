#!/usr/bin/env python3
"""standards — the requirements of a product's kind, and what holds each.

A product kind (`rules/products/<kind>.json`) lists the requirements its free documents state, each with
its document and clause, and says whether a gate or a test can hold it. A project names its kind in
`product.json` beside its board, and for each requirement a test may hold, the IDs of its verification
package (PROCESSES.md P28) that hold it. `workcenter standards` lists each requirement as held by a
gate, held by a test, or not held. A list from free documents is not a certificate: the report says which
document each requirement comes from and which paid standards a test laboratory uses. Standard library
only.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import ratings
from ratings import Refusal

KINDS = Path(__file__).resolve().parent.parent / "rules" / "products"
PROJECT_FILE = "product.json"
TRACE = Path("verification") / "traceability.md"
SCOPE = (
    "A list from free documents is not a certificate. Each line names the document and clause it comes "
    "from; a test laboratory judges the product to the paid standards below."
)


def read_kind(name: str) -> dict:
    """A product kind by its name: each requirement names a document of the kind, a clause, and how it
    is held (`gate` with the pack that holds it, or `test`)."""
    path = KINDS / f"{name}.json"
    if "/" in name or not path.is_file():
        known = ", ".join(sorted(p.stem for p in KINDS.glob("*.json")))
        raise Refusal(f"{PROJECT_FILE}: kind: `{name}` is no product kind; the workcenter holds {known}")
    at = path.name
    data = ratings._keys(
        at,
        ratings._json(path),
        ("kind", "title", "documents", "requirements", "left_out", "laboratory", "not_had"),
    )
    for key, doc in data["documents"].items():
        ratings._keys(f"{at}: documents: {key}", doc, ratings.DOCUMENT_KEYS)
        ratings._source(f"{at}: documents: {key}", doc)
    seen: set[str] = set()
    for i, req in enumerate(data["requirements"], start=1):
        where = f"{at}: requirements {i}"
        ratings._keys(where, req, ("id", "document", "clause", "says", "held_by"), ("pack", "helped_by"))
        if req["id"] in seen:
            raise Refusal(f"{where}: id `{req['id']}` stands 2 times")
        seen.add(req["id"])
        if req["document"] not in data["documents"]:
            raise Refusal(f"{where}: document `{req['document']}` is not under documents")
        if req["held_by"] not in ("gate", "test") or (req["held_by"] == "gate") != ("pack" in req):
            raise Refusal(f"{where}: held_by is `gate` with a `pack`, or `test` without one")
    for i, gone in enumerate(data["left_out"], start=1):
        where = f"{at}: left_out {i}"
        ratings._keys(where, gone, ("document", "clause", "why"))
        if gone["document"] not in data["documents"]:
            raise Refusal(f"{where}: document `{gone['document']}` is not under documents")
    for i, lab in enumerate(data["laboratory"], start=1):
        ratings._keys(f"{at}: laboratory {i}", lab, ("standard", "for"))
    for i, gone in enumerate(data["not_had"], start=1):
        ratings._keys(f"{at}: not_had {i}", gone, ("document", "url", "why"))
    return data


@dataclass
class Row:
    id: str
    status: str  # held by a gate, held by a test, not held
    source: str  # the document's number and the clause
    says: str
    how: str


def verdicts(project: Path, cli) -> dict[str, str]:
    """Each requirement ID of the project's traceability table, and its verdict."""
    path = project / TRACE
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for table in cli.md_tables(path.read_text(encoding="utf-8")):
        if tuple(c.lower() for c in table[0][: len(cli.TRACE_HEADER)]) != cli.TRACE_HEADER:
            continue
        for row in table[1:]:
            row = row + [""] * (len(cli.TRACE_HEADER) - len(row))
            out[cli.plain_id(row[0])] = cli.plain_id(row[4]).upper()
    return out


def _cli():
    import importlib.machinery
    import importlib.util
    import sys

    if "workcenter_cli" not in sys.modules:
        path = Path(__file__).resolve().parent / "workcenter"
        loader = importlib.machinery.SourceFileLoader("workcenter_cli", str(path))
        spec = importlib.util.spec_from_loader("workcenter_cli", loader)
        module = importlib.util.module_from_spec(spec)
        sys.modules["workcenter_cli"] = module
        loader.exec_module(module)
    return sys.modules["workcenter_cli"]


def gate(project: Path, name: str) -> tuple[bool, str]:
    """Whether the layout pack `name` holds on the project's board: board-rules.json names it, and the
    pack's rules, run on the board as it stands, give 0 fail, 0 not judged and no rule left aside. The
    reason, either way."""
    import boardrules
    import layoutrules

    path = project / boardrules.PROJECT_FILE
    if not path.is_file():
        return False, f"board-rules.json names no {name}"
    try:
        data = boardrules.project_keys(ratings._json(path))
    except Refusal as exc:
        return False, f"drc, pack {name}: {exc}"
    if name not in data.get("layout", []):
        return False, f"board-rules.json names no {name}"
    at = f"drc, pack {name}"
    pcbs = sorted(project.glob("*.kicad_pcb"))
    if len(pcbs) != 1:
        return False, f"{at}: {'no' if not pcbs else len(pcbs)} .kicad_pcb in the project to judge"
    try:
        board = boardrules.read_board(pcbs[0].read_text(encoding="utf-8"))
        pack = layoutrules.read_pack(boardrules.find_pack(name, project)[0])
        found = layoutrules.findings(board, pack, data)
    except (Refusal, OSError) as exc:
        return False, f"{at}: {exc}"
    fail = sum(f.status == "fail" for f in found)
    count = f"{at}: {fail} fail, {len(found) - fail} not judged"
    aside = layoutrules.notes(board, pack)
    if found or aside:
        return False, "; ".join([count, *aside])
    return True, f"{count} ({boardrules.PROJECT_FILE}, {pcbs[0].name})"


def judge(project: Path, cli=None) -> list[Row]:
    """Each requirement of the project's kind, and what holds it."""
    cli = cli or _cli()
    path = project / PROJECT_FILE
    if not path.is_file():
        raise Refusal(f'{PROJECT_FILE}: there is none in {project}; write {{"kind": "<kind>"}} there')
    data = ratings._keys(PROJECT_FILE, ratings._json(path), ("kind",), ("tests",))
    kind = read_kind(ratings._text(f"{PROJECT_FILE}: kind", data["kind"]))
    ids = {r["id"] for r in kind["requirements"]}
    tests = data.get("tests", {})
    if not isinstance(tests, dict):
        raise Refusal(f"{PROJECT_FILE}: tests: an object of requirement: [IDs] is asked")
    for key, names in tests.items():
        if key not in ids:
            raise Refusal(f"{PROJECT_FILE}: tests: `{key}` is no requirement of {kind['kind']}")
        ratings._names(f"{PROJECT_FILE}: tests: {key}", names)
    found = verdicts(project, cli)
    rows: list[Row] = []
    for req in kind["requirements"]:
        doc = kind["documents"][req["document"]]
        source = f"{doc['number']} {req['clause']}"
        why: list[str] = []
        status, how = "not held", ""
        if req["held_by"] == "gate":
            held, reason = gate(project, req["pack"])
            if held:
                status, how = "held by a gate", reason
            else:
                why.append(reason)
        if status == "not held" and req["id"] in tests:
            got = [(rid, found.get(rid)) for rid in tests[req["id"]]]
            missing = [rid for rid, v in got if v is None]
            short = [f"{rid} is {v}" for rid, v in got if v not in (None, "PASS")]
            if missing:
                why.append(
                    f"{', '.join(missing)} {'is' if len(missing) == 1 else 'are'} not in {TRACE.as_posix()}"
                )
            elif short:
                why.append(f"{'; '.join(short)} ({TRACE.as_posix()})")
            else:
                status = "held by a test"
                how = ", ".join(f"{rid} PASS" for rid, _ in got) + f" ({TRACE.as_posix()})"
        elif status == "not held" and req["held_by"] == "test":
            why.append(f"{PROJECT_FILE} names no test for it")
        rows.append(Row(req["id"], status, source, req["says"], how or "; ".join(why)))
    return rows


def report(project: Path, cli) -> tuple[str, list[str], list[Row]]:
    rows = judge(project, cli)
    kind = read_kind(ratings._json(project / PROJECT_FILE)["kind"])
    count = {s: sum(r.status == s for r in rows) for s in ("held by a gate", "held by a test", "not held")}
    head = (
        f"STANDARDS {kind['kind']}: {count['held by a gate']} held by a gate, "
        f"{count['held by a test']} held by a test, {count['not held']} not held"
    )
    lines = [head]
    lines += [f"- {r.status}: {r.id} [{r.source}] {r.says} -- {r.how}" for r in rows]
    lines += ["", SCOPE, "Documents:"]
    lines += [
        f"  {d['number']}, {d['title']} ({d['revision']}), {d['url']}, sha256 {d['sha256']}"
        for d in kind["documents"].values()
    ]
    lines += [
        f"left out: {kind['documents'][g['document']]['number']} {g['clause']}: {g['why']}"
        for g in kind["left_out"]
    ]
    lines += ["Paid standards a test laboratory uses (named only; no number of theirs is held here):"]
    lines += [f"  {lab['standard']}: {lab['for']}" for lab in kind["laboratory"]]
    lines += [f"not had: {g['document']}, {g['url']}: {g['why']}" for g in kind["not_had"]]
    return head, lines, rows


def cmd_standards(args, cli) -> int:
    project = Path(args.project).resolve()
    if project.is_file():
        project = project.parent
    try:
        _, lines, rows = report(project, cli)
    except (Refusal, OSError) as exc:
        print(f"standards: {exc}")
        return cli.EXIT_FAIL
    print("\n".join(lines))
    if args.strict and any(r.status == "not held" for r in rows):
        return cli.EXIT_FAIL
    return cli.EXIT_PASS


def register(sub, cli) -> None:
    """Add `standards` to the workcenter's parser."""
    p = sub.add_parser(
        "standards",
        help="list each requirement of the product kind product.json names, from free documents, as held "
        "by a gate, held by a named test of the verification package, or not held",
    )
    p.add_argument("project", help="project directory")
    p.add_argument("--strict", action="store_true", help="a requirement not held fails the run")
    p.set_defaults(run=lambda a: cmd_standards(a, cli))
