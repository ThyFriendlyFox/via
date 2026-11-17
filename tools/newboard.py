"""`workcenter new <dir>`: a board project a user can edit, from the workcenter's template.

It writes the files `workcenter next` and the commands after it read first:

    design.py            templates/project/design.py, with the folder's name and a namespace of its own
    .gitignore           templates/project/gitignore: what the engines and KiCad write
    parts.csv            the header `procure` and `sources` read (PARTS_COLUMNS)
    library/sources.csv  the header `fetch --row` appends to (SOURCES_HEADER)

A file that is there is kept, and a library/sources.csv in a folder above serves the project. A
folder that holds a design (a design file, a KiCad project or a chip) is refused in 1 line, and
nothing is written. The last line names the next step. No engine runs.

Standard library only, as the CLI is (AGENTS.md invariant 3).
"""

from __future__ import annotations

import re
import shlex
import uuid
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "project"
# The files that make a folder a project already: `next` answers it, and `new` would write over a design.
DESIGNS = ("design.py", "chip.json", "*.kicad_pro", "*.kicad_sch", "*.kicad_pcb")
# The template's own name and namespace: each is replaced once, or the template changed under `new`.
NAME_LINE = 'name="divider",'
NAMESPACE_RE = re.compile(r'namespace=uuid\.UUID\("[0-9a-f-]{36}"\)')


def board_name(folder: Path) -> str:
    """The folder's name as a design's name: the generated files are `<name>.kicad_*`."""
    return re.sub(r"[^A-Za-z0-9_-]+", "-", folder.name).strip("-_") or "board"


def design_text(name: str, namespace: uuid.UUID) -> str:
    """The template's design file under `name`, with `namespace`."""
    text = (TEMPLATE / "design.py").read_text(encoding="utf-8")
    if text.count(NAME_LINE) != 1 or len(NAMESPACE_RE.findall(text)) != 1:
        raise SystemExit(f"new: {TEMPLATE / 'design.py'} no longer holds 1 {NAME_LINE} and 1 namespace")
    text = text.replace(NAME_LINE, f"name={name!r},".replace("'", '"'))
    return NAMESPACE_RE.sub(f'namespace=uuid.UUID("{namespace}")', text)


def held(folder: Path) -> list[str]:
    """The design files a folder holds already."""
    return sorted(p.name for pattern in DESIGNS for p in folder.glob(pattern))


def cmd_new(args, cli) -> int:
    target = Path(args.dir).resolve()
    quoted = shlex.quote(args.dir)
    if target.exists() and not target.is_dir():
        print(f"new: {target} is a file; name a folder. Nothing written.")
        return 1
    there = held(target) if target.is_dir() else []
    if there:
        named = ", ".join(there)
        print(
            f"new: {target} holds a design already ({named}); nothing written. Next: workcenter next {quoted}"
        )
        return 1
    above = cli.find_sources(target.parent)
    files = {
        "design.py": design_text(board_name(target), uuid.uuid4()),
        ".gitignore": (TEMPLATE / "gitignore").read_text(encoding="utf-8"),
        "parts.csv": ",".join(cli.PARTS_COLUMNS) + "\n",
    }
    if above is None:
        files["library/sources.csv"] = ",".join(cli.SOURCES_HEADER) + "\n"
    wrote, kept = [], []
    for relative, text in files.items():
        path = target / relative
        if path.exists():
            kept.append(relative)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        wrote.append(relative)
    for relative in wrote:
        print(f"wrote {target / relative}")
    for relative in kept:
        print(f"kept  {target / relative} (it is there already)")
    if above is not None:
        print(f"kept  {above} (the library above serves this project)")
    then = f"Next: edit {quoted}/design.py, then workcenter next {quoted}"
    print(f"new: {len(wrote)} files written, {len(kept)} kept. {then}")
    return 0


def register(sub, cli) -> None:
    """Add `new` to the workcenter's parser."""
    p = sub.add_parser(
        "new",
        help="start a board project in a folder: design.py from the template, .gitignore, parts.csv and "
        "library/sources.csv with their headers; refuses a folder that holds a design; runs no engine",
    )
    p.add_argument("dir", help="the project's folder (made when it is not there)")
    p.set_defaults(run=lambda a: cmd_new(a, cli))
