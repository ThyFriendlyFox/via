"""doctools — the documents a board version carries, made by the workcenter. Standard library only.

`tools/workcenter` registers these commands with `register(sub, cli)`, passing itself as `cli`, so they
report through its `Result` and `emit` and reach its gates (`gate_procure`, `gate_render`):

    docs <version>                 CONTENTS.md and datasheets/ for a version folder
    costs <repo>                   every board of every version priced; the totals in every marked file
    pictures <version>             P23 in one command, from the version's pictures.json
    version new <repo> <vNEXT>     P22's mechanical steps
    diagram <spec.json> --out F    a block diagram from a spec

and `gates_report()` fills the tables of a gates report (`workcenter gates <project> --report <file>`).
A marked block is the text between `<!-- workcenter NAME -->` and `<!-- /workcenter NAME -->`; the
commands rewrite only what lies between the two markers, so the prose round them stays by hand.
"""

from __future__ import annotations

import argparse
import ast
import csv
import datetime
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from xml.sax.saxutils import escape

VERSION_RE = re.compile(r"^v\d+(?:\.\d+)*$")
# A version named in prose: `v0.16`, `v0.16/`, `v0.16.` at a sentence's end; never part of v0.161.
VERSION_TOKEN_RE = re.compile(r"(?<![\w.])(v\d+(?:\.\d+)+)(?!\.?\d)")
SKIP_DIRS = {"build", "__pycache__", "node_modules"}
KICAD_SUFFIXES = (".kicad_pro", ".kicad_sch", ".kicad_pcb", ".kicad_dru")
IMAGE_SUFFIXES = (".png", ".gif", ".jpg", ".svg")


# ------------------------------------------------------------------ shared


def version_key(name: str) -> tuple[int, ...]:
    return tuple(int(x) for x in name[1:].split("."))


def version_dirs(repo: Path) -> list[Path]:
    """The repository's version folders, oldest first: `v0.1/` before `v0.10/`."""
    found = (p for p in repo.iterdir() if p.is_dir() and VERSION_RE.match(p.name))
    return sorted(found, key=lambda p: version_key(p.name))


def next_version(name: str) -> str:
    head, _, last = name.rpartition(".")
    return f"{head}.{int(last) + 1}" if head else f"v{int(name[1:]) + 1}"


def is_project(folder: Path) -> bool:
    return any(folder.glob("*.kicad_pro")) or any(folder.glob("*.kicad_sch"))


@dataclass
class Board:
    """A KiCad project in a version: the version folder's own, or one nested a level down."""

    label: str  # "base" for the version folder's project, the folder's name for a nested one
    id: str  # the name of its parts files and lists: <version> or <version>-<folder>
    path: Path


def boards_of(vdir: Path) -> list[Board]:
    boards = [Board("base", vdir.name, vdir)] if is_project(vdir) else []
    for sub in sorted(p for p in vdir.iterdir() if p.is_dir()):
        if sub.name not in SKIP_DIRS and not sub.name.startswith(".") and is_project(sub):
            boards.append(Board(sub.name, f"{vdir.name}-{sub.name}", sub))
    return boards


def block_pattern(name: str) -> re.Pattern:
    """A block is its 2 markers, each alone on its line, as `wrap_block` writes them. A marker named
    inside a sentence (`` the `<!-- workcenter costs -->` markers ``) is prose, not a block."""
    n = re.escape(name)
    return re.compile(
        rf"(^[ \t]*<!-- workcenter {n} -->[ \t]*\r?\n)(.*?)(^[ \t]*<!-- /workcenter {n} -->)",
        re.S | re.M,
    )


def fill_block(text: str, name: str, body: str) -> tuple[str, int]:
    """Replace what lies between the block's two markers; the count is how many blocks were found."""
    return block_pattern(name).subn(lambda m: m.group(1) + body.rstrip("\n") + "\n" + m.group(3), text)


def wrap_block(name: str, body: str) -> str:
    return f"<!-- workcenter {name} -->\n{body.rstrip(chr(10))}\n<!-- /workcenter {name} -->\n"


def unclosed(text: str, name: str) -> bool:
    """An opening marker alone on its line with no closing one after it."""
    opening = re.compile(rf"^[ \t]*<!-- workcenter {re.escape(name)} -->[ \t]*\r?$", re.M)
    return bool(opening.search(text)) and not block_pattern(name).search(text)


def git(repo: Path, *args: str) -> str | None:
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)
    except OSError:
        return None
    return proc.stdout if proc.returncode == 0 else None


def project_files(root: Path) -> set[str]:
    """The files a folder holds as the project sees them, relative to it: git's tracked and untracked
    files without the ignored ones (build/, caches), or a walk that skips build/ and dot folders."""
    listed = git(root, "ls-files", "-co", "--exclude-standard", "-z", ".")
    if listed is not None:
        return {p for p in listed.split("\0") if p and (root / p).is_file()}
    found = set()
    for d, dirs, files in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS and not x.startswith(".")]
        found.update((Path(d) / f).relative_to(root).as_posix() for f in files)
    return found


def md_cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def md_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def md_link(text: str, target: str) -> str:
    return f"[{text}]({target.replace(' ', '%20')})"


def plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def anchor(heading: str) -> str:
    """GitHub's anchor for a Markdown heading."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def first_sentence(text: str) -> str:
    para = " ".join(text.strip().split("\n\n")[0].split())
    return re.split(r"(?<=[a-z0-9)])\. ", para)[0].rstrip(".")


def script_summary(path: Path) -> str:
    """A Python script's docstring, first sentence."""
    try:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    except (SyntaxError, ValueError, OSError):
        doc = None
    return first_sentence(doc) if doc else ""


def finish(cli, result, t0: float, args) -> int:
    result.seconds = round(time.monotonic() - t0, 2)
    return cli.emit([result], args, None)


# -------------------------------------------------------------------- docs
#
# A version's CONTENTS.md (what the folder holds, with each part's datasheet) and datasheets/ (those
# datasheets, copied from the library by its sources.csv): Last Hit's library/version_docs.py, general.

READ_FIRST = {
    "docs/gates.md": "the gates report: ERC, DRC, simulation, export",
    "firmware/README.md": "the firmware: building, testing, uploading",
    "models/README.md": "the 3D bodies and the commands that made them",
}
DESIGN_FILES = {
    "design.py": "the source of truth; the KiCad files are generated from it",
    "fp-lib-table": "footprint libraries",
    "sym-lib-table": "symbol libraries",
    ".kicad_pro": "KiCad project",
    ".kicad_sch": "schematic",
    ".kicad_pcb": "board",
    ".kicad_dru": "custom design rules (the fab's)",
}
DESIGN_DIRS = (("footprints", "project footprints"), ("symbols", "project symbols"), ("models", "3D bodies"))
VERIFY_PAGES = (
    ("requirements/README.md", "the operating profile, the conditions and the requirements"),
    ("system/README.md", "the block diagram and how charge moves in each mode"),
    ("calculations/README.md", "the requirements no deck measures"),
    ("traceability.md", "each requirement's evidence, value and verdict"),
)
FIRMWARE_DIRS = {"tests": "host tests", "tools": "tools", "vendor": "vendored code", "sim": "host simulation"}
# A firmware's mutation list, read by `workcenter mutate` (P18 step 4).
MUTATION_LISTS = ("mutations.py", "mutations.json")
SPLIT_DIRS = {"src"}
# A bare board's row (the fab's order, as the procurement skill writes it) has no datasheet.
BARE_BOARD = "bare board"


def read_series(library: Path) -> list[tuple[re.Pattern, str]]:
    """library/series.csv: a part whose datasheet is a series or family sheet kept under another
    part number. Columns Pattern (a regular expression matched against the MPN) and MPN."""
    path = library / "series.csv"
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as fh:
        return [(re.compile(r["Pattern"]), r["MPN"]) for r in csv.DictReader(fh) if r.get("Pattern")]


def datasheet_rows(sources: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    with sources.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            if (r.get("Kind") or "").strip().lower() == "datasheet":
                rows.setdefault(
                    (r.get("MPN") or "").strip(), {k: (v or "").strip() for k, v in r.items() if k}
                )
    return rows


def datasheet_for(mpn: str, rows: dict[str, dict], series: list[tuple[re.Pattern, str]]) -> dict | None:
    if mpn in rows:
        return rows[mpn]
    for pattern, stand_in in series:
        if pattern.match(mpn) and stand_in in rows:
            return rows[stand_in]
    return None


def list_lines(boards: list[Board], lists: Path) -> tuple[list[dict], list[str]]:
    """Each board's priced lines from its list (parts/lists/<id>.csv), the boards with no list."""
    lines, missing = [], []
    for b in boards:
        path = lists / f"{b.id}.csv"
        if not path.is_file():
            missing.append(b.id)
            continue
        with path.open(encoding="utf-8", newline="") as fh:
            for r in csv.DictReader(fh):
                if (r.get("MPN") or "").lower().startswith(BARE_BOARD) or (
                    r.get("Supplier") or ""
                ).lower() == "none":
                    continue
                lines.append({**r, "board": b.label})
    return lines, missing


def contents_text(
    vdir: Path,
    boards: list[Board],
    lines: list[dict],
    rows: dict[str, dict],
    series: list,
    sources: Path,
    lists: Path,
    scripts: dict[str, str],
) -> str:
    version = vdir.name
    files = project_files(vdir)
    rel = lambda p: os.path.relpath(p, vdir).replace(os.sep, "/")  # noqa: E731

    def here(pattern_dir: str = "") -> list[str]:
        """The files directly in a folder of the version, by name."""
        prefix = f"{pattern_dir}/" if pattern_dir else ""
        return sorted(f for f in files if f.startswith(prefix) and "/" not in f[len(prefix) :])

    def count_under(d: str) -> int:
        return sum(1 for f in files if f.startswith(d + "/"))

    readme = vdir / "README.md"
    title = (
        readme.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip() if readme.is_file() else ""
    )
    lib = rel(sources.parent)
    out = [
        f"# {version}: contents",
        "",
        f"What this folder holds{', for ' + title if title else ''}. Made by `workcenter docs {version}` "
        f"from the folder itself, the version's parts lists and `{os.path.relpath(sources, vdir.parent)}`; "
        "run it again after a change.",
        "",
        "## Read first",
        "",
    ]
    if readme.is_file():
        out.append(
            f"- {md_link('README.md', 'README.md')}: "
            "the version's spec, pin plan, BOM, decisions and open items."
        )
        for ln in readme.read_text(encoding="utf-8").splitlines():
            if ln.startswith("## "):
                h = ln[3:].strip()
                out.append(f"  - {md_link(h, 'README.md#' + anchor(h))}")
    for path, what in READ_FIRST.items():
        if path in files:
            out.append(f"- {md_link(path, path)}: {what}.")
    out.append("")

    out += ["## Design", ""]
    for b in boards:
        sub = rel(b.path) if b.path != vdir else ""
        names = [f for f in here(sub) if Path(f).name in DESIGN_FILES or Path(f).suffix in KICAD_SUFFIXES]
        if not names:
            continue
        out.append(f"- The {b.label} board:")
        for f in names:
            what = DESIGN_FILES.get(Path(f).name) or DESIGN_FILES.get(Path(f).suffix, "")
            out.append(f"  - {md_link(f, f)}" + (f": {what}" if what else ""))
        for d, what in DESIGN_DIRS:
            folder = f"{sub}/{d}" if sub else d
            if count_under(folder):
                out.append(
                    f"  - {md_link(folder + '/', folder + '/')}: "
                    f"{what}, {plural(count_under(folder), 'file')}"
                )
    for b in boards:
        sub = rel(b.path) if b.path != vdir else ""
        for f in here(sub):
            if f.endswith(".py") and Path(f).name != "design.py":
                what = scripts.get(f) or script_summary(vdir / f)
                out.append(f"- {md_link(f, f)}" + (f": {what}." if what else ""))
    out.append("")

    decks = [f for f in here("sim") if f.endswith(".cir")]
    if decks:
        out += ["## Simulation", ""]
        for d in decks:
            exp = d[: -len(".cir")] + ".expect.json"
            line = f"- {md_link(d, d)}" + (f", bounds in {md_link(exp, exp)}" if exp in files else "")
            first = (vdir / d).read_text(encoding="utf-8", errors="replace").splitlines()
            first = first[0].lstrip("* ").strip() if first else ""
            first = re.split(r"(?<=[a-z0-9)])\. ", first)[0].rstrip(".")
            out.append(f"{line}: {first}" if first else line)
        out.append("")

    if "verification/README.md" in files:
        out += [
            "## Verification",
            "",
            f"- {md_link('verification/README.md', 'verification/README.md')}: "
            "the package's index and verdicts; "
            "`workcenter verify` checks it against a fresh run of the decks.",
        ]
        for sub, what in VERIFY_PAGES:
            if f"verification/{sub}" in files:
                out.append(f"- {md_link('verification/' + sub, 'verification/' + sub)}: {what}.")
        for w in sorted(f for f in files if re.fullmatch(r"verification/simulations/[^/]+/README\.md", f)):
            head = (vdir / w).read_text(encoding="utf-8").splitlines()
            out.append(
                f"- {md_link(w, w)}: the simulation writeup, {head[0].lstrip('# ').strip() if head else ''}"
            )
        out.append("")

    if any(f.startswith("firmware/") for f in files):
        out += ["## Firmware", ""]
        tops = sorted({f.split("/")[1] for f in files if f.count("/") >= 2 and f.startswith("firmware/")})
        for top in tops:
            folder = f"firmware/{top}"
            direct = here(folder)
            subs = sorted(
                {f.split("/")[2] for f in files if f.startswith(folder + "/") and f.count("/") >= 3}
            )
            # A source tree is listed by its parts (src/core, src/board); any other folder as one.
            for d in (
                [f"{folder}/{s}" for s in subs] if top in SPLIT_DIRS and subs and not direct else [folder]
            ):
                what = FIRMWARE_DIRS.get(Path(d).name, "")
                readme_d = f"{d}/README.md"
                if readme_d in files:
                    head = (vdir / readme_d).read_text(encoding="utf-8").splitlines()
                    what = head[0].lstrip("# ").strip() if head else what
                n = plural(count_under(d), "file")
                out.append(f"- {md_link(d + '/', d + '/')}: " + (f"{what}, {n}" if what else n))
        if "firmware/Makefile" in files:
            targets = re.findall(r"^([a-z][\w-]*):(?!=)", (vdir / "firmware/Makefile").read_text(), re.M)
            names = ["`make`", *[f"`make {t}`" for t in targets[1:] if t != "clean"]]
            out.append(
                f"- {md_link('firmware/Makefile', 'firmware/Makefile')}: {', '.join(dict.fromkeys(names))}"
            )
        for m in MUTATION_LISTS:
            if f"firmware/{m}" in files:
                out.append(
                    f"- {md_link('firmware/' + m, 'firmware/' + m)}: the mutation list "
                    "`workcenter mutate` runs; every mutation must fail a host test"
                )
        out.append("")

    pictures = [f for f in here("docs") if Path(f).suffix in IMAGE_SUFFIXES]
    data = [f for f in here("docs") if Path(f).suffix in (".json", ".md")]
    layers = [f for f in files if f.startswith("docs/layers/")]
    manifest = PICTURES_FILE in files
    if pictures or data or layers or manifest:
        out += ["## Pictures and reports", ""]
        if manifest:
            out.append(
                f"- {md_link(PICTURES_FILE, PICTURES_FILE)}: what `workcenter pictures` draws "
                "and copies into docs/"
            )
        out += [f"- {md_link(f, f)}" for f in pictures]
        if layers:
            out.append(
                f"- {md_link('docs/layers/', 'docs/layers/')}: every copper and technical layer, "
                f"{plural(len(layers), 'image')}"
            )
        out += [f"- {md_link(f, f)}" for f in data]
        out.append("")

    out += ["## Parts", ""]
    for b in boards:
        md = lists / f"{b.id}.md"
        if md.is_file():
            out.append(f"- The {b.label} board's priced parts list: {md_link(rel(md), rel(md))}")
    out.append("")

    out += [
        "## Datasheets",
        "",
        "Each part's datasheet as its maker publishes it, copied from "
        f"[`{lib}/`]({lib}/) into [`datasheets/`](datasheets/); "
        f"[`{lib}/{sources.name}`]({lib}/{sources.name}) records where each came from, its revision and "
        "its SHA256. A part with no file says why.",
        "",
        "| Board | Refs | Part | Datasheet | Revision |",
        "|---|---|---|---|---|",
    ]
    for r in lines:
        mpn = (r.get("MPN") or "").strip()
        row = datasheet_for(mpn, rows, series)
        part = f"{r.get('Manufacturer', '')} {mpn}".strip()
        refs = r.get("Refs") or r.get("Value", "")
        rev = ""
        if not mpn:
            sheet = "none: no part number chosen yet (the parts list's note says why)"
        elif row and row.get("File"):
            sheet = md_link(row["File"], f"datasheets/{row['File']}")
            if row["MPN"] != mpn:
                sheet += " (series sheet)"
            rev = row.get("Revision", "")
        elif row:
            sheet = f"none kept: {row.get('Note', '')}"
        else:
            sheet = f"none kept: no row in `{lib}/{sources.name}`"
        out.append(md_row([r["board"], refs, part, sheet, rev]))
    out.append("")
    return "\n".join(out)


def cmd_docs(args, cli) -> int:
    t0 = time.monotonic()
    vdir = Path(args.version).resolve()
    if not vdir.is_dir():
        raise SystemExit(f"docs: {vdir} is not a folder")
    sources = (Path(args.library).resolve() / "sources.csv") if args.library else cli.find_sources(vdir)
    if sources is None or not sources.is_file():
        return finish(
            cli, cli.Result("docs", "skip", "no library/sources.csv at or above the version"), t0, args
        )
    lists = Path(args.lists).resolve() if args.lists else vdir.parent / "parts" / "lists"
    boards = boards_of(vdir)
    rows = datasheet_rows(sources)
    series = read_series(sources.parent)
    lines, missing = list_lines(boards, lists)
    scripts = {}
    manifest = vdir / PICTURES_FILE
    if manifest.is_file():
        try:
            scripts = {
                s["script"]: s.get("what", "") for s in json.loads(manifest.read_text()).get("scenes", [])
            }
        except (ValueError, KeyError, AttributeError):
            scripts = {}
    copied: dict[str, Path] = {}
    if not missing:
        for r in lines:
            row = datasheet_for((r.get("MPN") or "").strip(), rows, series)
            if row and row.get("File") and row["File"] not in copied:
                src = sources.parent / row["File"]
                if src.is_file():
                    dest = vdir / "datasheets" / row["File"]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(src, dest)
                    copied[row["File"]] = dest
    removed = []
    ddir = vdir / "datasheets"
    if not missing and ddir.is_dir():
        # Only a copy of a library file goes: anything else in datasheets/ was put there by hand.
        for f in sorted(p for p in ddir.rglob("*") if p.is_file()):
            name = f.relative_to(ddir).as_posix()
            if name not in copied and (sources.parent / name).is_file():
                f.unlink()
                removed.append(name)
    text = contents_text(vdir, boards, lines, rows, series, sources, lists, scripts)
    (vdir / "CONTENTS.md").write_text(text, encoding="utf-8")
    absent = sorted(
        {r.get("MPN", "") for r in lines if not datasheet_for(r.get("MPN", ""), rows, series)} - {""}
    )
    summary = f"{len(lines)} parts, {len(copied)} datasheets in datasheets/, CONTENTS.md written"
    details = {
        "copied": sorted(copied),
        "removed": removed,
        "no_row": absent,
        "boards": [b.id for b in boards],
    }
    if removed:
        summary += f"; {len(removed)} stale copies removed"
    if missing:
        summary = f"no parts list for {', '.join(missing)} in {lists} (run `workcenter costs`); " + summary
        details["failures"] = [f"{m}: no {lists / (m + '.csv')}" for m in missing]
    status = "fail" if missing else "pass"
    return finish(cli, cli.Result("docs", status, summary, details, [str(vdir / "CONTENTS.md")]), t0, args)


# ------------------------------------------------------------------- costs
#
# Every board of every version priced with the repository's parts files, the lists kept in
# parts/lists/, and the totals table written into every file that marks a place for it (M97: one
# table in two files went stale in the one the checklist did not name).

COSTS_BLOCK = "costs"
LISTS_BLOCK = "costs lists"


def money(d: Decimal) -> str:
    return f"${d:.2f}"


def list_totals(path: Path, counts: tuple[int, ...]) -> tuple[dict[int, Decimal], list[str], list[str]]:
    """A priced list's totals per count, the lines not priced, and the lines short of stock at the
    largest count."""
    totals = {n: Decimal(0) for n in counts}
    unpriced, short = [], []
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            if (row.get("Supplier") or "").lower() == "none":
                continue
            name = row.get("Refs") or row.get("Value") or ""
            if not row.get(f"Cost for {counts[0]}"):
                unpriced.append(name)
                continue
            try:
                for n in counts:
                    totals[n] += Decimal(row[f"Cost for {n}"])
                stock, order = row.get("Stock", ""), row.get(f"Order for {max(counts)}", "")
                if stock and order and int(stock) < int(order):
                    short.append(name)
            except (InvalidOperation, ValueError, KeyError, TypeError):
                unpriced.append(name)
    return totals, unpriced, short


def totals_table(repo: Path, lists: Path, counts: tuple[int, ...]) -> list[str]:
    big = max(counts)
    head = ["Version", *[f"{n} unit" + ("" if n == 1 else "s") for n in counts]]
    head += [f"Per unit at {big}", "Not priced", "Short of stock"]
    rows = [md_row(head), "|---" * len(head) + "|"]
    for vdir in version_dirs(repo):
        totals = {n: Decimal(0) for n in counts}
        unpriced, short, found = [], [], False
        for b in boards_of(vdir):
            path = lists / f"{b.id}.csv"
            if not path.is_file():
                continue
            found = True
            t, u, s = list_totals(path, counts)
            prefix = "" if b.label == "base" else f"{b.label} "
            for n in counts:
                totals[n] += t[n]
            unpriced += [prefix + x for x in u]
            short += [prefix + x for x in s]
        if found:
            cells = [vdir.name, *[money(totals[n]) for n in counts], money(totals[big] / big)]
            rows.append(md_row(cells + ["; ".join(unpriced) or "none", "; ".join(short) or "none"]))
    return rows


def lists_table(repo: Path, lists: Path, at: Path) -> list[str]:
    rel = os.path.relpath(lists, at).replace(os.sep, "/")
    rows = ["| Version | Lists |", "|---|---|"]
    for vdir in version_dirs(repo):
        links = [
            f"[{b.label}]({rel}/{b.id}.md) ([csv]({rel}/{b.id}.csv))"
            for b in boards_of(vdir)
            if (lists / f"{b.id}.md").is_file()
        ]
        if links:
            rows.append(f"| {vdir.name} | {', '.join(links)} |")
    return rows


def marked_files(repo: Path, prefix: str) -> list[Path]:
    """Every Markdown file in the repository that holds a block named `prefix...`."""
    found = []
    for d, dirs, files in os.walk(repo):
        dirs[:] = sorted(x for x in dirs if x not in SKIP_DIRS and not x.startswith("."))
        for f in sorted(files):
            if f.endswith(".md"):
                p = Path(d) / f
                if f"<!-- workcenter {prefix}" in p.read_text(encoding="utf-8", errors="replace"):
                    found.append(p)
    return found


def cmd_costs(args, cli) -> int:
    t0 = time.monotonic()
    repo = Path(args.repo).resolve()
    parts = repo / "parts"
    catalog = parts / "catalog.csv"
    if not catalog.is_file():
        return finish(cli, cli.Result("costs", "skip", f"no parts catalog: {catalog}"), t0, args)
    lists = parts / "lists"
    lists.mkdir(exist_ok=True)
    priced, failures, n_boards = [], [], 0
    for vdir in version_dirs(repo):
        for b in boards_of(vdir):
            n_boards += 1
            files = [p for p in (parts / "version" / f"{b.id}.csv", catalog) if p.is_file()]
            if (parts / "offboard" / f"{b.id}.csv").is_file():
                files.append(parts / "offboard" / f"{b.id}.csv")
            project = cli.find_project(str(b.path))
            result = cli.gate_procure(project, cli.out_dir_for(project, None), files, args.boards)
            made = project.dir / "build" / "procure"
            if result.status in ("pass", "fail") and (made / "parts.csv").is_file():
                shutil.copyfile(made / "parts.csv", lists / f"{b.id}.csv")
                shutil.copyfile(made / "parts.md", lists / f"{b.id}.md")
                priced.append(f"{b.id}: {result.summary}")
            else:
                failures.append(f"{b.id}: {result.status}: {result.summary}")
    table = totals_table(repo, lists, args.boards)
    written, problems = [], []
    for path in marked_files(repo, COSTS_BLOCK):
        text = path.read_text(encoding="utf-8")
        new, n = fill_block(text, COSTS_BLOCK, "\n".join(table))
        new, m = fill_block(new, LISTS_BLOCK, "\n".join(lists_table(repo, lists, path.parent)))
        for name in (COSTS_BLOCK, LISTS_BLOCK):
            if unclosed(text, name):
                problems.append(
                    f"{path.relative_to(repo)}: `<!-- workcenter {name} -->` has no closing marker"
                )
        if new != text:
            path.write_text(new, encoding="utf-8")
        if n or m:
            written.append(str(path.relative_to(repo)))
    summary = f"{len(priced)} of {n_boards} boards priced into {lists.relative_to(repo)}/"
    summary += "; totals in " + (
        ", ".join(written) if written else "no file (no `<!-- workcenter costs -->` block)"
    )
    details = {"boards": priced, "failures": failures + problems, "table": table, "files": written}
    status = "fail" if failures or problems else "pass"
    code = finish(cli, cli.Result("costs", status, summary, details, written), t0, args)
    if not args.json and not written:
        print("\n".join(["", wrap_block(COSTS_BLOCK, "\n".join(table))]))
    return code


# ------------------------------------------------------------ gates report


def gates_report(report: Path, project, results: list, cli) -> list[str]:
    """Write or refresh the project's gates table and deck list in a Markdown report, between markers
    named after the project; prose outside the markers is left as it is. Returns the blocks written."""
    ran = {r.gate: r for r in results}
    verdict = cli.gates_verdict(results)[0]
    kicad = cli.tool_version([cli.KICAD_CLI, "version"]) or "absent"
    ngspice = cli.tool_version([cli.NGSPICE, "--version"], r"(?<=ngspice-)\d+") or "absent"
    rows = ["| Gate | Status | Summary |", "|---|---|---|"]
    for gate in cli.GATE_ORDER:
        r = ran.get(gate)
        rows.append(
            md_row(
                [gate.upper(), r.status if r else "not run", r.summary if r else "an earlier gate was red"]
            )
        )
    rows += [
        "",
        f"{verdict} on {datetime.date.today().isoformat()}: "
        f"`workcenter gates` with KiCad {kicad}, ngspice {ngspice}.",
    ]
    blocks = {f"gates {project.name}": "\n".join(rows)}
    decks = sorted((project.dir / "sim").glob("*.cir")) if (project.dir / "sim").is_dir() else []
    if decks:
        sim = ran.get("sim")
        details = sim.details if sim else {}
        lines = ["| Deck | What it simulates | Bounds | Corner runs | Result |", "|---|---|---|---|---|"]
        for deck in decks:
            # The first sentence of the deck's opening comment, which may run over several lines.
            head = []
            for ln in deck.read_text(encoding="utf-8", errors="replace").splitlines():
                if not ln.startswith("*") or not ln.lstrip("* ").strip():
                    break
                head.append(ln.lstrip("* ").strip())
            what = first_sentence(" ".join(head)) if head else ""
            expect = deck.with_suffix(".expect.json")
            try:
                bounds = len(json.loads(expect.read_text(encoding="utf-8"))) if expect.is_file() else 0
            except ValueError:
                bounds = 0
            if not sim or sim.status == "skip" or deck.stem not in details.get("decks", {}):
                result = "not run"
            else:
                fails = sum(1 for f in details.get("failures", []) if f.startswith(f"{deck.stem}:"))
                warns = sum(1 for w in details.get("warnings", []) if w.startswith(f"{deck.stem}:"))
                result = (
                    ", ".join(
                        x
                        for x in (
                            plural(fails, "failure") if fails else "",
                            plural(warns, "warning") if warns else "",
                        )
                        if x
                    )
                    or "pass"
                )
            # The runs beside the deck as written (sim/corners.json): none without the file, and the
            # project's own reason for a deck it keeps out.
            corners = details.get("decks", {}).get(deck.stem, {}).get("corners")
            if corners is None:
                runs = "none"
            else:
                runs = f"none: {corners['skip']}" if "skip" in corners else str(corners["runs"])
            lines.append(md_row([f"`sim/{deck.name}`", what, str(bounds), runs, result]))
        blocks[f"decks {project.name}"] = "\n".join(lines)
    text = report.read_text(encoding="utf-8") if report.is_file() else f"# Gates report: {project.name}\n"
    for name, body in blocks.items():
        if unclosed(text, name):
            raise SystemExit(f"{report}: `<!-- workcenter {name} -->` has no closing marker")
        text, n = fill_block(text, name, body)
        if not n:
            heading = f"## {project.name}" if name.startswith("gates") else f"## Simulation: {project.name}"
            text = text.rstrip("\n") + f"\n\n{heading}\n\n" + wrap_block(name, body)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(text, encoding="utf-8")
    return list(blocks)


# ----------------------------------------------------------------- pictures
#
# P23 in one command: each board's stills, layer images and turning GIFs, the project's scene scripts
# (an assembly, a close-up), and the copies into the version's docs/, from a manifest in the version.

PICTURES_FILE = "pictures.json"
STILLS = ("board-top.png", "board-bottom.png", "board-3d-top.png", "board-3d-bottom.png", "board-3d-iso.png")
SPIN_TOP, SPIN_BOTTOM = -55.0, -125.0


def both_faces(pcb: Path) -> bool:
    """Whether the board carries footprints on both faces."""
    text = pcb.read_text(encoding="utf-8", errors="replace")
    layers = set(re.findall(r'\(footprint\s+"[^"]*"\s*(?:\(locked[^)]*\)\s*)?\(layer\s+"([FB])\.Cu"\)', text))
    return layers == {"F", "B"}


def default_manifest(vdir: Path) -> dict:
    boards = []
    for b in boards_of(vdir):
        prefix = "" if b.path == vdir else f"{b.label}-"
        pcbs = sorted(b.path.glob("*.kicad_pcb"))
        spins = [{"as": f"{prefix}board-spin.gif", "tilt": SPIN_TOP, "zoom": 1.0}]
        if pcbs and both_faces(pcbs[0]):
            spins.append({"as": f"{prefix}board-spin-bottom.gif", "tilt": SPIN_BOTTOM, "zoom": 1.0})
        boards.append(
            {
                "path": os.path.relpath(b.path, vdir).replace(os.sep, "/"),
                "name": b.label,
                "prefix": prefix,
                "strict": True,
                "stills": [*STILLS, "schematic.png"],
                "layers": f"layers-{b.label}.png",
                "spins": spins,
            }
        )
    scenes = []
    for script in sorted(vdir.glob("*.py")):
        if script.name != "design.py" and re.search(
            r"^\s*(import scene|from scene import)", script.read_text(), re.M
        ):
            scenes.append({"script": script.name, "what": script_summary(script), "copy": {}})
    return {"boards": boards, "scenes": scenes}


def manifest_problems(manifest: dict, vdir: Path) -> list[str]:
    problems = []
    for i, b in enumerate(manifest.get("boards", [])):
        if not (vdir / b.get("path", ".")).is_dir():
            problems.append(f"boards[{i}]: no folder {b.get('path')}")
        for j, s in enumerate(b.get("spins", [])):
            if not s.get("as", "").endswith(".gif"):
                problems.append(f"boards[{i}].spins[{j}]: `as` names the GIF in docs/, ending .gif")
    for i, s in enumerate(manifest.get("scenes", [])):
        if not (vdir / s.get("script", "")).is_file():
            problems.append(f"scenes[{i}]: no script {s.get('script')}")
    return problems


def tile_frames(gif: Path, png: Path, frames: int) -> bool:
    """Every frame of a GIF side by side in one image, for the framing check (P23 step 3)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not gif.is_file():
        return False
    cols = min(frames, 4)
    rows = math.ceil(frames / cols)
    proc = subprocess.run(
        [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(gif),
            "-vf",
            f"tile={cols}x{rows}",
            "-frames:v",
            "1",
            str(png),
        ],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0 and png.is_file()


def scene_env(cli, frames: int | None) -> dict:
    env = {**os.environ, "WORKCENTER_SRC": str(cli.SRC_DIR), "PYTHONDONTWRITEBYTECODE": "1"}
    env["PYTHONPATH"] = os.pathsep.join(
        x for x in (str(cli.SRC_DIR / "tools"), env.get("PYTHONPATH", "")) if x
    )
    if frames:
        env["WORKCENTER_SPIN_FRAMES"] = str(frames)
        env["WORKCENTER_PICTURES_CHECK"] = "1"
    return env


def cmd_pictures(args, cli) -> int:
    t0 = time.monotonic()
    vdir = Path(args.version).resolve()
    path = vdir / PICTURES_FILE
    notes = []
    if not path.is_file():
        path.write_text(json.dumps(default_manifest(vdir), indent=2) + "\n", encoding="utf-8")
        notes.append(f"wrote {path.name} with the defaults; edit it and run again to change what is drawn")
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return finish(cli, cli.Result("pictures", "error", f"{path}: {exc}"), t0, args)
    problems = manifest_problems(manifest, vdir)
    if problems:
        return finish(
            cli, cli.Result("pictures", "error", f"{path}: {problems[0]}", {"failures": problems}), t0, args
        )
    docs = vdir / "docs"
    failures, copied, checks = [], [], []

    def keep(src: Path, name: str) -> None:
        if not src.is_file():
            failures.append(f"{name}: {src} was not drawn")
            return
        dest = docs / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        copied.append(name)

    for b in manifest.get("boards", []):
        project = cli.find_project(str(vdir / b.get("path", ".")))
        name, prefix = b.get("name", project.name), b.get("prefix", "")
        build = project.dir / "build"
        if not args.frames:
            r = cli.gate_render(project, build, strict=b.get("strict", True))
            if r.status != "pass":
                failures.append(f"{name}: render {r.status}: {r.summary}")
            else:
                rdir = build / "render"
                for still in b.get("stills", [*STILLS, "schematic.png"]):
                    keep(rdir / still, prefix + still)
                if b.get("layers"):
                    keep(rdir / "layers.png", b["layers"])
                    for layer in sorted((rdir / "layers").glob("*.png")):
                        keep(layer, f"layers/{name}-{layer.name}")
        for s in b.get("spins", []):
            stem = Path(s["as"]).stem
            out = build / "pictures" / ("check" if args.frames else "spin") / stem
            r = cli.gate_render(
                project,
                out,
                views=("spin",),
                spin_frames=args.frames or s.get("frames", 36),
                spin_tilt=float(s.get("tilt", SPIN_TOP)),
                spin_zoom=float(s.get("zoom", 1.0)),
                spin_pivot=s.get("pivot"),
            )
            gif = out / "render" / "board-spin.gif"
            if r.status != "pass":
                failures.append(f"{s['as']}: render {r.status}: {r.summary}")
            elif args.frames:
                sheet = out / f"{stem}-frames.png"
                checks.append(str(sheet) if tile_frames(gif, sheet, args.frames) else str(gif))
            else:
                keep(gif, s["as"])
    for s in manifest.get("scenes", []):
        proc = subprocess.run(
            [cli.venv_python(), str(vdir / s["script"])],
            cwd=vdir,
            env=scene_env(cli, args.frames),
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout).strip().splitlines()[-1:] or ["no output"]
            failures.append(f"{s['script']}: exit {proc.returncode}: {tail[0]}")
            continue
        if args.frames:
            checks += re.findall(r"^frames: (\S+)$", proc.stdout, re.M)
            continue
        for src, dest in s.get("copy", {}).items():
            keep(vdir / src, dest)
    if args.frames:
        summary = f"framing check, {args.frames} frames: {len(checks)} sheets to look at; docs/ untouched"
        details = {"failures": failures, "sheets": checks, "notes": notes}
        code = finish(
            cli, cli.Result("pictures", "fail" if failures else "pass", summary, details, checks), t0, args
        )
        if not args.json:
            for c in checks:
                print(f"       look at {c}")
        return code
    summary = f"{len(copied)} files into {docs.relative_to(vdir.parent)}/" + (
        f"; {notes[0]}" if notes else ""
    )
    details = {"failures": failures, "copied": copied, "notes": notes}
    return finish(cli, cli.Result("pictures", "fail" if failures else "pass", summary, details), t0, args)


# ----------------------------------------------------------------- version
#
# P22's mechanical steps for a new version folder; what needs judgement is printed as a checklist.


def banner_span(lines: list[str]) -> tuple[int, int] | None:
    """The blockquote under the README's title: (first line, line after it)."""
    i = next((n for n, ln in enumerate(lines) if ln.startswith("# ")), None)
    if i is None:
        return None
    j = i + 1
    while j < len(lines) and not lines[j].strip():
        j += 1
    if j >= len(lines) or not lines[j].startswith(">"):
        return None
    k = j
    while k < len(lines) and lines[k].startswith(">"):
        k += 1
    return j, k


def series_name(prev_readme: str, repo: Path) -> str:
    m = re.search(r"\[([^\]]+)\]\(\.\./README\.md\)", prev_readme)
    if m:
        return m.group(1)
    root = repo / "README.md"
    if root.is_file():
        title = next(
            (ln[2:].strip() for ln in root.read_text(encoding="utf-8").splitlines() if ln.startswith("# ")),
            "",
        )
        if title:
            return title
    return f"{repo.name} series"


def archived_banner(repo: Path, prev: str, nxt: str, commit: str, series: str) -> str:
    """The previous version's banner, archived: the series' latest archived banner with the version and
    the commit changed, or a plain one when no version is archived yet."""
    tail = f" The next version, [`../{nxt}/`](../{nxt}/), is in work."
    for vdir in reversed(version_dirs(repo)):
        if version_key(vdir.name) >= version_key(prev) or not (vdir / "README.md").is_file():
            continue
        lines = (vdir / "README.md").read_text(encoding="utf-8").splitlines()
        span = banner_span(lines)
        text = " ".join(ln.lstrip("> ").strip() for ln in lines[span[0] : span[1]]) if span else ""
        if not text.startswith("Archived: "):
            continue
        text = re.sub(r"^Archived: \S+ of", f"Archived: {prev} of", text)
        text = re.sub(r"as of commit `[^`]*`", f"as of commit `{commit}`", text)
        cut = text.find(" The next version")
        return "> " + (text[:cut] if cut >= 0 else text) + tail
    return (
        f"> Archived: {prev} of the [{series}](../README.md), as of commit `{commit}`. The design and KiCad "
        f"files are the ones that commit holds.{tail}"
    )


def current_banner(series: str, first: str, prev: str) -> str:
    return (
        f"> The current version of the [{series}](../README.md), "
        f"started as a copy of [`../{prev}/`](../{prev}/). "
        f"The earlier versions are the sibling folders, "
        f"[`../{first}/`](../{first}/) to [`../{prev}/`](../{prev}/)."
    )


def version_row(lines: list[str], prev: str, nxt: str, commit: str) -> tuple[list[str], bool]:
    """Add the new version's row to the series table and give the previous row its commit."""
    link = f"[{prev}]({prev}/)"
    i = next((n for n, ln in enumerate(lines) if ln.startswith("|") and link in md_cells(ln)[0]), None)
    if i is None:
        return lines, False
    top = i
    while top > 0 and lines[top - 1].startswith("|"):
        top -= 1
    header = [c.lower() for c in md_cells(lines[top])]
    commit_col = header.index("commit") if "commit" in header else None
    prev_cells = md_cells(lines[i])
    below = md_cells(lines[i + 1]) if i + 1 < len(lines) and lines[i + 1].startswith("|") else []
    above = md_cells(lines[i - 1]) if i - 1 > top + 1 else []
    older = below if below and re.search(r"\[(v[\d.]+)\]", below[0]) else above
    descending = older is below
    new = []
    for j, cell in enumerate(prev_cells):
        if j == 0:
            new.append(cell.replace(link, f"[{nxt}]({nxt}/)"))
        elif j == commit_col:
            new.append("in work")
        elif older and j < len(older) and older[j] == cell:
            new.append(cell)
        else:
            new.append(f"as {prev}")
    if "(current)" not in new[0]:
        new[0] += " (current)"
    prev_cells[0] = prev_cells[0].replace(" (current)", "")
    if commit_col is not None:
        prev_cells[commit_col] = f"`{commit}`"
    out = list(lines)
    out[i] = md_row(prev_cells)
    out.insert(i if descending else i + 1, md_row(new))
    return out, True


def move_versions(text: str, prev: str, nxt: str) -> tuple[str, int]:
    """Every mention of the previous version becomes the new one, and a mention of the new one (an
    example such as "`v0.17/` from `v0.16/`") moves one further, in one pass."""
    mapping = {prev: nxt, nxt: next_version(nxt)}
    moved = len([m for m in VERSION_TOKEN_RE.finditer(text) if m.group(1) in mapping])
    return VERSION_TOKEN_RE.sub(lambda m: mapping.get(m.group(1), m.group(1)), text), moved


def ignore_build(_dir: str, names: list[str]) -> list[str]:
    return [n for n in names if n in ("build", "__pycache__")]


def cmd_version(args, cli) -> int:
    t0 = time.monotonic()
    repo = Path(args.repo).resolve()
    nxt = args.next
    if not VERSION_RE.match(nxt):
        raise SystemExit(f"version new: {nxt!r} is not a version name like v0.17")
    versions = version_dirs(repo)
    if not versions:
        raise SystemExit(f"version new: {repo} has no version folders (v0.1/, v0.2/, ...)")
    prev = args.from_version or versions[-1].name
    pdir, ndir = repo / prev, repo / nxt
    if not pdir.is_dir():
        raise SystemExit(f"version new: {pdir} is not a folder")
    if ndir.exists():
        raise SystemExit(f"version new: {ndir} exists already")
    if version_key(nxt) <= version_key(versions[-1].name):
        raise SystemExit(f"version new: {nxt} is not after {versions[-1].name}, the latest version")
    commit = (git(repo, "log", "-1", "--format=%h", "--", f"{prev}/") or "").strip() or "uncommitted"
    dirty = (git(repo, "status", "--porcelain", "--", f"{prev}/") or "").strip()
    written, todo = [], []

    shutil.copytree(pdir, ndir, symlinks=True, ignore=ignore_build)
    written.append(f"{nxt}/ (a copy of {prev}/ without build/)")
    readme_p, readme_n = pdir / "README.md", ndir / "README.md"
    series = series_name(readme_p.read_text(encoding="utf-8") if readme_p.is_file() else "", repo)
    if readme_n.is_file():
        lines = readme_n.read_text(encoding="utf-8").splitlines(keepends=True)
        t = next((n for n, ln in enumerate(lines) if ln.startswith("# ")), None)
        if t is not None:
            lines[t] = VERSION_TOKEN_RE.sub(lambda m: nxt if m.group(1) == prev else m.group(1), lines[t])
        span = banner_span([ln.rstrip("\n") for ln in lines])
        banner = current_banner(series, versions[0].name, prev) + "\n"
        if span:
            lines[span[0] : span[1]] = [banner]
        elif t is not None:
            lines[t + 1 : t + 1] = ["\n", banner]
        readme_n.write_text("".join(lines), encoding="utf-8")
        written.append(f"{nxt}/README.md: title and banner")
    if readme_p.is_file():
        lines = readme_p.read_text(encoding="utf-8").splitlines(keepends=True)
        span = banner_span([ln.rstrip("\n") for ln in lines])
        banner = archived_banner(repo, prev, nxt, commit, series) + "\n"
        if span:
            lines[span[0] : span[1]] = [banner]
            readme_p.write_text("".join(lines), encoding="utf-8")
            written.append(f"{prev}/README.md: the banner says archived, as of commit {commit}")
        else:
            todo.append(f"{prev}/README.md has no banner under its title: write the archived one by hand")
    root = repo / "README.md"
    if root.is_file():
        text = root.read_text(encoding="utf-8")
        lines, ok = version_row(text.splitlines(), prev, nxt, commit)
        if ok:
            root.write_text("\n".join(lines) + ("\n" if text.endswith("\n") else ""), encoding="utf-8")
            written.append(f"README.md: the row of {nxt} (current, in work) and {prev}'s commit {commit}")
            rest = [
                f"README.md:{n}: {ln.strip()[:100]}"
                for n, ln in enumerate(lines, 1)
                if not ln.startswith("|") and re.search(rf"(?<![\w.]){re.escape(prev)}(?!\.?\d)", ln)
            ]
            if rest:
                todo.append(
                    f"the root README names {prev} outside its table ({len(rest)} lines); "
                    f"move what now means {nxt}:"
                )
                todo += [f"    {r}" for r in rest[:12]]
        else:
            todo.append(f"README.md: no table row links [{prev}]({prev}/); add the row of {nxt} by hand")
    guide = repo / "CLAUDE.md"  # the project's instructions to an agent, which name the version in work
    if guide.is_file():
        text, n = move_versions(guide.read_text(encoding="utf-8"), prev, nxt)
        if n:
            guide.write_text(text, encoding="utf-8")
            written.append(f"CLAUDE.md: {plural(n, 'version reference')} moved ({prev} -> {nxt})")
    for b in boards_of(pdir):
        new_id = nxt + b.id[len(prev) :]
        for kind in ("version", "offboard"):
            src, dest = repo / "parts" / kind / f"{b.id}.csv", repo / "parts" / kind / f"{new_id}.csv"
            if src.is_file() and not dest.exists():
                shutil.copyfile(src, dest)
                written.append(f"parts/{kind}/{new_id}.csv (from {b.id}.csv)")
    if dirty:
        todo.insert(
            0, f"{prev}/ has changes no commit holds; its banner names {commit}, which does not have them"
        )
    for f in sorted(project_files(ndir)):
        if f.endswith(".py"):
            hits = [
                n for n, ln in enumerate((ndir / f).read_text(encoding="utf-8").splitlines(), 1) if prev in ln
            ]
            if hits:
                todo.append(
                    f"{nxt}/{f} names {prev} on lines {', '.join(map(str, hits[:10]))}: labels and notes"
                )
    todo += [
        f'{nxt}/README.md: write "What changed in {nxt}" and the status table; the root README row\'s cells',
        f"{prev}/README.md: the banner's last sentence says what {nxt} changes once that is known",
        f"workcenter design {nxt}/design.py (and each nested design.py), then workcenter gates {nxt}",
        f"workcenter costs {args.repo}, then workcenter docs {nxt}",
        f"P22 step 4: git diff --stat {commit} -- {prev}/ shows only {prev}/README.md, one line",
    ]
    summary = f"{nxt} from {prev}: {len(written)} steps done, {len(todo)} by hand"
    details = {"written": written, "todo": todo, "commit": commit}
    code = finish(cli, cli.Result("version", "pass", summary, details, [str(ndir)]), t0, args)
    if not args.json:
        print("\n".join(["done:", *[f"  {w}" for w in written], "by hand:", *[f"  - {t}" for t in todo]]))
    return code


# ----------------------------------------------------------------- diagram
#
# A block diagram from a spec, in the style of a verification package's system drawing: blocks as
# rounded boxes, rails as bars, arrows coloured by what flows in them, boards as dashed groups, and a
# legend of the styles used. Coordinates are the spec's own, in pixels; arrows route themselves
# between blocks unless the spec gives their points.

STYLES = {
    "power": {"color": "#1b8a3a", "width": 3, "label": "power"},
    "load": {"color": "#c62828", "width": 3, "label": "load current"},
    "logic": {"color": "#1565c0", "width": 2, "label": "logic and control"},
    "sense": {"color": "#777777", "width": 1.5, "dash": True, "label": "sensing"},
    "return": {"color": "#444444", "width": 3, "label": "return"},
    "data": {"color": "#7b1fa2", "width": 1.5, "label": "data"},
}
LINE_STEP, FIRST_LINE = 16.5, 20


def tint(color: str, amount: float = 0.1) -> str:
    """The colour mixed into white: a block's fill from its style's line colour."""
    c = color.lstrip("#")
    rgb = [int(c[i : i + 2], 16) for i in (0, 2, 4)] if len(c) == 6 else [119, 119, 119]
    return "#" + "".join(f"{round(v * amount + 255 * (1 - amount)):02x}" for v in rgb)


def num(v: float) -> str:
    return f"{v:g}"


class Diagram:
    def __init__(self, spec: dict):
        self.spec = spec
        self.styles = {**STYLES, **spec.get("styles", {})}
        self.out: list[str] = []
        self.boxes: dict[str, tuple[float, float, float, float]] = {}
        self.used: list[str] = []
        self.problems: list[str] = []

    def style(self, name: str, line: bool = True) -> dict:
        """A style by name; `line` marks it used by a line, so the legend and the arrowheads carry it."""
        if name not in self.styles:
            self.problems.append(f"style {name!r} is not one of {', '.join(self.styles)}")
            return {"color": "#333333", "width": 1.5}
        if line and name not in self.used:
            self.used.append(name)
        return self.styles[name]

    def text(self, x, y, s, fill="#222", anchor="start", size=12, weight=None, rot=None) -> None:
        attrs = f' x="{num(x)}" y="{num(y)}"'
        attrs += f' text-anchor="{anchor}"' if anchor != "start" else ""
        attrs += f' font-weight="{weight}"' if weight else ""
        attrs += f' fill="{fill}"' if fill != "#222" else ""
        attrs += f' font-size="{num(size)}"' if size != 12 else ""
        attrs += f' transform="rotate({num(rot)} {num(x)} {num(y)})"' if rot is not None else ""
        self.out.append(f"  <text{attrs}>{escape(str(s))}</text>")

    def block(self, b: dict) -> None:
        x, y, w = float(b["x"]), float(b["y"]), float(b.get("w", 200))
        lines = [(b["title"], "title")] if b.get("title") else []
        lines += [(s, "line") for s in b.get("lines", [])] + [(s, "note") for s in b.get("notes", [])]
        h = float(b.get("h", FIRST_LINE + LINE_STEP * max(len(lines) - 1, 0) + 11))
        kind = b.get("style")
        stroke = self.style(kind, line=False)["color"] if kind else "#333333"
        fill = b.get("fill") or (tint(stroke) if kind else "#f3f3f3")
        dash = ' stroke-dasharray="4 3"' if b.get("dash") else ""
        self.out.append(
            f'  <rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" rx="6" fill="{fill}" '
            f'stroke="{stroke}"{dash}/>'
        )
        left = b.get("align") == "left"
        tx = x + 12 if left else x + w / 2
        for n, (s, role) in enumerate(lines):
            ty = y + FIRST_LINE + n * LINE_STEP
            anchor = "start" if left else "middle"
            if role == "title":
                self.text(tx, ty, s, anchor=anchor, size=13, weight="bold")
            else:
                self.text(tx, ty, s, anchor=anchor, fill="#555" if role == "note" else "#222")
        self.boxes[b["id"]] = (x, y, x + w, y + h)

    def rail(self, r: dict) -> None:
        st = self.style(r.get("style", "power"))
        x, y = float(r["x"]), float(r["y"])
        w, h = (float(r["w"]), 12.0) if "w" in r else (12.0, float(r.get("h", 400)))
        self.out.append(
            f'  <rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" '
            f'fill="{st["color"]}" opacity="0.85"/>'
        )
        label = r.get("label", r["id"])
        if "w" in r:
            self.text(x, y - 6, label, fill=st["color"], size=13, weight="bold")
        else:
            self.text(x + w / 2, y - 6, label, fill=st["color"], anchor="middle", size=13, weight="bold")
        self.boxes[r["id"]] = (x, y, x + w, y + h)

    def group(self, g: dict) -> None:
        x, y, w, h = (float(g[k]) for k in ("x", "y", "w", "h"))
        self.out.append(
            f'  <rect x="{num(x)}" y="{num(y)}" width="{num(w)}" height="{num(h)}" rx="10" fill="#fbfbfb" '
            'stroke="#999999" stroke-dasharray="8 4"/>'
        )
        self.text(x + 12, y + 20, g.get("label", ""), size=13, weight="bold", fill="#444")

    def route(self, a: dict) -> list[tuple[float, float]] | None:
        if a.get("points"):
            return [(float(p[0]), float(p[1])) for p in a["points"]]
        missing = [k for k in ("from", "to") if a.get(k) not in self.boxes]
        if missing:
            self.problems.append(
                f"arrow {a.get('from')} -> {a.get('to')}: no block or rail {a.get(missing[0])!r}"
            )
            return None
        s, t = self.boxes[a["from"]], self.boxes[a["to"]]
        if t[0] >= s[2] or t[2] <= s[0]:  # side by side: leave from a side, enter the other
            right = t[0] >= s[2]
            xo, xi = (s[2], t[0] - 2) if right else (s[0], t[2] + 2)
            lo, hi = max(s[1], t[1]), min(s[3], t[3])
            if "y" in a or lo < hi:
                y = float(a.get("y", (lo + hi) / 2))
                return [(xo, y), (xi, y)]
            ys, yt = (s[1] + s[3]) / 2, (t[1] + t[3]) / 2
            xm = float(a.get("x", (xo + xi) / 2))
            return [(xo, ys), (xm, ys), (xm, yt), (xi, yt)]
        down = t[1] >= s[3]
        yo, yi = (s[3], t[1] - 2) if down else (s[1], t[3] + 2)
        lo, hi = max(s[0], t[0]), min(s[2], t[2])
        if "x" in a or lo < hi:
            x = float(a.get("x", (lo + hi) / 2))
            return [(x, yo), (x, yi)]
        xs, xt = (s[0] + s[2]) / 2, (t[0] + t[2]) / 2
        ym = float(a.get("y", (yo + yi) / 2))
        return [(xs, yo), (xs, ym), (xt, ym), (xt, yi)]

    def arrow(self, a: dict) -> None:
        pts = self.route(a)
        if not pts:
            return
        name = a.get("style", "logic")
        st = self.style(name)
        d = "M" + " L".join(f"{num(round(x, 1))},{num(round(y, 1))}" for x, y in pts)
        if a.get("halo", st.get("halo", False)):
            self.out.append(
                f'  <path d="{d}" fill="none" stroke="#ffffff" stroke-width="{num(st["width"] + 4.5)}"/>'
            )
        dash = ' stroke-dasharray="4 3"' if st.get("dash") else ""
        end = "" if a.get("head") is False else f' marker-end="url(#m-{name})"'
        self.out.append(
            f'  <path d="{d}" fill="none" stroke="{st["color"]}" '
            f'stroke-width="{num(st["width"])}"{dash}{end}/>'
        )
        if a.get("label"):
            # On the run `label_on` names, else on the longest, where it has room.
            runs = list(zip(pts, pts[1:], strict=False))
            (x0, y0), (x1, y1) = (
                runs[min(int(a["label_on"]), len(runs) - 1)]
                if "label_on" in a
                else max(runs, key=lambda s: abs(s[1][0] - s[0][0]) + abs(s[1][1] - s[0][1]))
            )
            if abs(y1 - y0) < abs(x1 - x0):
                self.text(min(x0, x1) + 5, y0 - 6, a["label"], fill=st["color"], size=11)
            else:
                self.text(
                    x0 - 6, (y0 + y1) / 2, a["label"], fill=st["color"], anchor="middle", size=11, rot=-90
                )

    def legend(self, at: tuple[float, float], dots: bool, groups: bool) -> float:
        x, y = at
        entries = len(self.used) + dots + groups
        h = 34 + 22 * entries
        self.out.append(
            f'  <rect x="{num(x)}" y="{num(y)}" width="230" height="{h}" rx="6" '
            'fill="#ffffff" stroke="#999"/>'
        )
        self.text(x + 10, y + 22, "Legend", size=13, weight="bold")
        cy = y + 42
        for name in self.used:
            st = self.styles[name]
            dash = ' stroke-dasharray="4 3"' if st.get("dash") else ""
            self.out.append(
                f'  <line x1="{num(x + 10)}" y1="{num(cy)}" x2="{num(x + 50)}" y2="{num(cy)}" '
                f'stroke="{st["color"]}" '
                f'stroke-width="{num(st["width"])}"{dash}/>'
            )
            self.text(x + 58, cy + 4, st.get("label", name))
            cy += 22
        if dots:
            self.out.append(f'  <circle cx="{num(x + 30)}" cy="{num(cy)}" r="3.5" fill="#444"/>')
            self.text(x + 58, cy + 4, "a junction")
            cy += 22
        if groups:
            self.out.append(
                f'  <rect x="{num(x + 10)}" y="{num(cy - 7)}" width="40" height="14" rx="3" fill="#fbfbfb" '
                'stroke="#999999" stroke-dasharray="8 4"/>'
            )
            self.text(x + 58, cy + 4, "a board or an assembly")
        return y + h

    def render(self) -> str:
        spec = self.spec
        for g in spec.get("groups", []):
            self.group(g)
        for r in spec.get("rails", []):
            self.rail(r)
        for b in spec.get("blocks", []):
            if "id" not in b or "x" not in b or "y" not in b:
                self.problems.append(f"block {b.get('id', b.get('title', '?'))!r}: needs id, x and y")
                continue
            self.block(b)
        for a in spec.get("arrows", []):
            self.arrow(a)
        for p in spec.get("dots", []):
            self.out.append(
                f'  <circle cx="{num(float(p[0]))}" cy="{num(float(p[1]))}" r="3.5" fill="#444"/>'
            )
        right = max(
            [b[2] for b in self.boxes.values()]
            + [float(g["x"]) + float(g["w"]) for g in spec.get("groups", [])]
            + [400]
        )
        bottom = max(
            [b[3] for b in self.boxes.values()]
            + [float(g["y"]) + float(g["h"]) for g in spec.get("groups", [])]
            + [80]
        )
        lg = spec.get("legend", {})
        if lg is not False:
            at = (float(lg.get("x", 20)), float(lg.get("y", bottom + 30)))
            bottom = max(bottom, self.legend(at, bool(spec.get("dots")), bool(spec.get("groups"))))
            right = max(right, at[0] + 230)
        width = int(spec.get("width", math.ceil(right + 20)))
        height = int(spec.get("height", math.ceil(bottom + 20)))
        head = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
            f'viewBox="0 0 {width} {height}" '
            'font-family="Helvetica, Arial, sans-serif" font-size="12">',
            f"  <title>{escape(spec.get('title', 'Block diagram'))}</title>",
            "  <defs>",
        ]
        for name in self.used:
            head.append(
                f'    <marker id="m-{name}" viewBox="0 0 10 10" refX="9" refY="5" '
                'markerUnits="userSpaceOnUse" markerWidth="11" markerHeight="11" '
                f'orient="auto"><path d="M0,0 L10,5 L0,10 z" fill="{self.styles[name]["color"]}"/></marker>'
            )
        head += ["  </defs>", f'  <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff"/>']
        title: list[str] = []
        saved, self.out = self.out, title
        if spec.get("title"):
            self.text(20, 30, spec["title"], size=18, weight="bold")
        if spec.get("subtitle"):
            self.text(20, 50, spec["subtitle"], fill="#444", size=13)
        self.out = saved
        return "\n".join(head + title + self.out + ["</svg>"]) + "\n"


def cmd_diagram(args, cli) -> int:
    t0 = time.monotonic()
    spec_path = Path(args.spec).resolve()
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return finish(cli, cli.Result("diagram", "error", f"{spec_path}: {exc}"), t0, args)
    diagram = Diagram(spec)
    svg = diagram.render()
    if diagram.problems:
        result = cli.Result(
            "diagram",
            "fail",
            f"{spec_path.name}: {diagram.problems[0]}; nothing written",
            {"failures": diagram.problems},
        )
        return finish(cli, result, t0, args)
    out = Path(args.out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    artifacts = [str(out)]
    status, summary = (
        "pass",
        f"{out.name}: {len(diagram.boxes)} blocks and rails, {len(spec.get('arrows', []))} arrows",
    )
    if args.png:
        rsvg = shutil.which("rsvg-convert")
        png = out.with_suffix(".png")
        if not rsvg:
            status, summary = "skip", summary + "; PNG skipped: rsvg-convert missing"
        else:
            width = re.search(r'width="(\d+)"', svg).group(1)
            proc = subprocess.run(
                [rsvg, "-w", width, "-o", str(png), str(out)], capture_output=True, check=False
            )
            if proc.returncode == 0 and png.is_file():
                artifacts.append(str(png))
                summary += f"; {png.name}"
            else:
                status, summary = "fail", summary + f"; rsvg-convert exit {proc.returncode}"
    return finish(cli, cli.Result("diagram", status, summary, {}, artifacts), t0, args)


# ---------------------------------------------------------------- commands


def board_counts(value: str) -> tuple[int, ...]:
    try:
        counts = tuple(int(v) for v in value.split(",") if v.strip())
    except ValueError:
        counts = ()
    if not counts or min(counts) < 1:
        raise argparse.ArgumentTypeError(f"--boards takes counts like 1,10, not {value!r}")
    return counts


def register(sub, cli) -> None:
    """Add this module's commands to the workcenter's parser; each sets `run` to its handler."""
    p = sub.add_parser(
        "docs",
        help="a version folder's CONTENTS.md and datasheets/: writes CONTENTS.md, copies each part's "
        "datasheet from the library into datasheets/ and removes a copy no part names any more",
    )
    p.add_argument("version", help="the version folder, e.g. v0.16")
    p.add_argument("--library", help="the library folder holding sources.csv (default: the nearest library/)")
    p.add_argument(
        "--lists", help="the priced parts lists (default <repo>/parts/lists, from `workcenter costs`)"
    )
    p.set_defaults(run=lambda a: cmd_docs(a, cli))

    p = sub.add_parser(
        "costs",
        help="price every board of every version with parts/version/<id>.csv, parts/catalog.csv and "
        "parts/offboard/<id>.csv; writes parts/lists/<id>.csv and .md, each board's build/procure/, and the "
        "totals into every Markdown file's <!-- workcenter costs --> block",
    )
    p.add_argument("repo", help="the repository holding the version folders and parts/")
    p.add_argument(
        "--boards", type=board_counts, default="1,10", help="units to price, comma-separated (default 1,10)"
    )
    p.set_defaults(run=lambda a: cmd_costs(a, cli))

    p = sub.add_parser(
        "pictures",
        help="P23 in one command from the version's pictures.json (written with defaults when absent): "
        "renders, turning GIFs, scene scripts, then copies into docs/ and docs/layers/",
    )
    p.add_argument("version", help="the version folder, e.g. v0.16")
    p.add_argument(
        "--frames",
        type=int,
        default=0,
        help="the framing check: every GIF with this many frames into build/pictures/check/, one sheet of "
        "frames each; docs/ untouched",
    )
    p.set_defaults(run=lambda a: cmd_pictures(a, cli))

    p = sub.add_parser("version", help="a project's version folders (P22)")
    vs = p.add_subparsers(dest="version_command", required=True)
    n = vs.add_parser(
        "new",
        help="copy the latest version folder without build/; set both READMEs' banners, the root README's "
        "row, CLAUDE.md's version references and the parts files; print what stays by hand",
    )
    n.add_argument("repo", help="the repository holding the version folders")
    n.add_argument("next", help="the new version's name, e.g. v0.17")
    n.add_argument("--from", dest="from_version", help="the version to copy (default: the latest)")
    n.set_defaults(run=lambda a: cmd_version(a, cli))

    p = sub.add_parser(
        "diagram", help="a block diagram from a JSON spec: writes the SVG, and with --png a PNG beside it"
    )
    p.add_argument("spec", help="the spec, e.g. verification/system/block-diagram.json")
    p.add_argument("--out", required=True, help="the SVG to write")
    p.add_argument("--png", action="store_true", help="also write <out>.png with rsvg-convert")
    p.set_defaults(run=lambda a: cmd_diagram(a, cli))


if __name__ == "__main__":
    sys.exit(
        "doctools is part of the workcenter command line: "
        "run `workcenter docs|costs|pictures|version|diagram`"
    )
