"""Write the site's example pages from the examples' own files.

    python3 site/examples.py              # site/examples.html, and per example a page and its board
    python3 site/examples.py --check      # exit 1 when a page or a board drawing is not what it writes
    python3 site/examples.py --pictures   # also each example's 3D pictures (numpy and Pillow)

An example is a folder `examples/<name>/` whose version folders `v0.1`, `v0.2`, ... each hold a
README.md; the newest version is the one shown. Its page is `site/examples/<slug>.html`, where the
slug is the README title's first word (`# Herald v0.1: ...` and `# Hush — board prototype v0.1` are
`herald` and `hush`), and the files it shows are in `site/examples/<slug>/`:

- From the newest README: the name, the version, the line under the name (the title's words after
  its colon, else the introduction's first sentence), the first paragraph, the table under "What is
  hard about it", and the list under "What is open" or "Open items".
- How it was built, oldest first: for each version, its TIMELINE.md's `## <date> · <stage> ·
  <title>` entries when it has one, else the newest README's "What changed in <version>: <title>"
  section, its first paragraphs. A fenced run of `workcenter gates` in the newest version's
  TIMELINE.md is shown as it stands.
- The checks: the verdict and the 4 gates' lines of that run, else of `docs/gates.md`.
- From the board (`*.kicad_pcb` in the version folder): the size, the copper layers, the parts, the
  tracks and the vias, and `board.svg`, the board drawn from the file for the page's explorer. An
  example of several boards, each in a folder of its own, has no explorer.
- With --pictures, from `docs/`: the board's 3D renders from the top, the bottom and the side (or
  the assembly's, for an example with no board of its own) with KiCad's backdrop taken out
  (`site/showcase/key.py`), and its turning render as `spin.webp`, its frames side by side.

The pages and the drawings are committed; the docs tests write them again and compare.
"""

# ruff: noqa: E501 - the page's templates are HTML, with its lines as long as the site's pages'.
from __future__ import annotations

import argparse
import html
import json
import math
import posixpath
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
OUT = SITE / "examples"
REPO = "https://github.com/ThyFriendlyFox/via"
sys.path.insert(0, str(ROOT / "tools"))

import kicadgen as k  # noqa: E402

SPIN_COLUMNS = 6  # the turntable's frames, 6 to a row of spin.webp
OPEN_ITEMS = 8  # the most open items a page lists; the README has the rest
WORDS = ["zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]
# docs/ names for each of an example's pictures, the board's first.
PICTURES = {
    "top.png": ("board-3d-top.png", "assembly-top.png", "assembly-front.png"),
    "bottom.png": ("board-3d-bottom.png", "assembly-back.png", "assembly-iso-back.png"),
    "iso.png": ("board-3d-iso.png", "assembly-iso.png"),
    "spin.webp": ("board-spin.gif", "assembly-spin.gif"),
    # The card that names the example on the site: the made thing, where there is more than a board.
    "card.png": ("assembly-iso.png", "board-3d-iso.png"),
}


def words(n: int) -> str:
    """A count as the site writes it in running text: one to nine in words (docs/STYLE.md)."""
    return WORDS[n] if 0 < n < 10 else f"{n:,}"


# ---------------------------------------------------------------- reading an example


@dataclass
class Entry:
    date: str
    stage: str
    title: str
    blocks: list[tuple[str, str]]  # ("p", text) or ("pre", text)
    version: str = ""


@dataclass
class Example:
    folder: Path
    slug: str
    name: str
    version: str
    tagline: str
    intro: str
    hard: list[tuple[str, str]] = field(default_factory=list)
    still_open: list[str] = field(default_factory=list)
    timeline: list[Entry] = field(default_factory=list)
    board: Path | None = None
    verdict: str = ""
    checks: list[tuple[str, str, str]] = field(default_factory=list)  # (gate, status, summary)
    per_board: list[tuple[str, str]] = field(default_factory=list)  # (board, verdict), several boards
    run: str = ""  # the newest version's gates run, as the terminal printed it

    @property
    def rel(self) -> str:
        return self.folder.relative_to(ROOT).as_posix()


def version_key(path: Path) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", path.name))


def sections(text: str) -> dict[str, str]:
    """A Markdown file's `## ` sections by heading."""
    out: dict[str, str] = {}
    for part in re.split(r"^## ", text, flags=re.M)[1:]:
        head, _, body = part.partition("\n")
        out[head.strip()] = body
    return out


def paragraphs(text: str) -> list[str]:
    """The plain paragraphs of a piece of Markdown, up to its first table or sub-heading: a quote, a
    list, a picture and a comment are left out."""
    out = []
    for block in re.split(r"\n\s*\n", re.sub(r"<!--.*?-->", "", text, flags=re.S)):
        block = block.strip()
        if not block:
            continue
        if block.startswith(("|", "#")):
            break
        if block.startswith((">", "- ", "* ", "<", "```", "!")):
            continue
        out.append(" ".join(block.split()))
    return out


def first_sentence(text: str) -> str:
    sentence = re.split(r"(?<=[.:;])\s", text, maxsplit=1)[0]
    return sentence.rstrip(".:;")


def table(text: str) -> list[tuple[str, str]]:
    rows = [line for line in text.splitlines() if line.startswith("|")]
    out = []
    for line in rows[2:]:
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2:
            out.append((cells[0], cells[1]))
    return out


def bullets(text: str) -> list[str]:
    items: list[str] = []
    for line in text.splitlines():
        if line.startswith("- "):
            items.append(line[2:].strip())
        elif line.startswith("  ") and items:
            items[-1] += " " + line.strip()
    return items


def timeline(path: Path) -> list[Entry]:
    if not path.is_file():
        return []
    entries = []
    for part in re.split(r"^## ", path.read_text(encoding="utf-8"), flags=re.M)[1:]:
        head, _, body = part.partition("\n")
        date, stage, title = (s.strip() for s in head.split("·", 2))
        blocks: list[tuple[str, str]] = []
        for chunk in re.split(r"(```[^\n]*\n.*?\n```)", body, flags=re.S):
            if chunk.startswith("```"):
                blocks.append(("pre", chunk.split("\n", 1)[1].rsplit("\n```", 1)[0]))
            else:
                blocks += [("p", " ".join(p.split())) for p in re.split(r"\n\s*\n", chunk) if p.strip()]
        entries.append(Entry(date, stage, title, blocks))
    return entries


def changes(readme: str) -> dict[str, Entry]:
    """The README's "What changed in <version>: <title>" sections, by version, each its first 2
    paragraphs and the first date it names."""
    out = {}
    for heading, body in sections(readme).items():
        m = re.match(r"What changed in (v[\d.]+): (.+)", heading)
        if m:
            date = re.search(r"\d{4}-\d{2}-\d{2}", body)
            blocks = [("p", p) for p in paragraphs(body)[:2]]
            out[m.group(1)] = Entry(date.group(0) if date else "", m.group(1), m.group(2), blocks)
    return out


def gates_report(path: Path) -> tuple[str, list[tuple[str, str, str]], list[tuple[str, str]]]:
    """The verdict and the gates' rows of a `workcenter gates --report` file. A report on several
    boards gives each board's verdict, and 1 verdict for them all."""
    if not path.is_file():
        return "", [], []
    text = path.read_text(encoding="utf-8")
    verdicts = re.findall(
        r"^## (\S+)\n(?:(?!^## ).*\n)*?((?:GREEN|RED|SKIPPED).*?) on \d{4}-\d{2}-\d{2}:", text, re.M
    )
    rows = re.findall(r"^\| (ERC|DRC|SIM|EXPORT) \| (\w+) \| ([^|]+?) \|$", text, re.M)
    if len(verdicts) == 1:
        return verdicts[0][1], rows, []
    if not verdicts:
        return "", rows, []
    red = [board for board, verdict in verdicts if not verdict.startswith("GREEN")]
    total = (
        f"GREEN on all {len(verdicts)} boards" if not red else f"RED on {len(red)} of {len(verdicts)} boards"
    )
    return total, [], verdicts


def checks_of(run: str) -> tuple[str, list[tuple[str, str, str]]]:
    """The verdict and the gates' lines of a run of `workcenter gates`."""
    lines = run.rstrip().splitlines()
    rows = []
    for line in lines:
        m = re.match(r"^(PASS|FAIL|SKIP)\s+(erc|drc|sim|export)\s+(.*?)\s*(?:\[[\d.]+s\])?$", line)
        if m:
            rows.append((m.group(2).upper(), m.group(1).lower(), m.group(3).strip()))
    return lines[-1].split(":")[0], rows


def read(versions: list[Path]) -> Example:
    newest = versions[-1]
    text = (newest / "README.md").read_text(encoding="utf-8")
    title = text.splitlines()[0].lstrip("# ").strip()
    name = title.split()[0]
    version = (re.search(r"\bv\d+(?:\.\d+)*\b", title) or re.search(r"v[\d.]+", newest.name)).group(0)
    intro = (paragraphs(text.split("\n", 1)[1]) or [""])[0]
    tagline = title.partition(":")[2].strip()
    if not tagline:
        # The introduction's first sentence names the board; the page shows it once, under the name.
        tagline = first_sentence(intro)
        intro = intro[len(tagline) :].lstrip(".:; ")
    parts = sections(text)
    hard = next((table(body) for heading, body in parts.items() if heading.startswith("What is hard")), [])
    still_open = bullets(parts.get("What is open", "") or parts.get("Open items", ""))
    changed = changes(text)
    history: list[Entry] = []
    for folder in versions:
        kept = timeline(folder / "TIMELINE.md")
        for entry in kept:
            entry.version = folder.name
        history += kept or ([changed[folder.name]] if folder.name in changed else [])
    runs = [b for e in timeline(newest / "TIMELINE.md") for kind, b in e.blocks if kind == "pre"]
    run = next((b for b in runs if b.startswith("$ workcenter gates")), "")
    verdict, checks, per_board = (*checks_of(run), []) if run else gates_report(newest / "docs" / "gates.md")
    boards = sorted(newest.glob("*.kicad_pcb"))
    return Example(
        folder=newest,
        slug=name.lower(),
        name=name,
        version=version,
        tagline=tagline,
        intro=intro,
        hard=hard,
        still_open=still_open,
        timeline=history,
        board=boards[0] if boards else None,
        verdict=verdict,
        checks=checks,
        per_board=per_board,
        run=run,
    )


def examples() -> list[Example]:
    found = []
    for project in sorted((ROOT / "examples").iterdir()):
        versions = sorted((p for p in project.glob("v*") if (p / "README.md").is_file()), key=version_key)
        if versions:
            found.append(read(versions))
    return found


# ---------------------------------------------------------------- the board, drawn from its file


def f(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def arc_points(start, mid, end, steps: int = 48) -> list[tuple[float, float]]:
    """The points of a 3-point arc, start to end through mid."""
    (x1, y1), (x2, y2), (x3, y3) = start, mid, end
    d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
    if abs(d) < 1e-9:
        return [start, end]
    ux = ((x1**2 + y1**2) * (y2 - y3) + (x2**2 + y2**2) * (y3 - y1) + (x3**2 + y3**2) * (y1 - y2)) / d
    uy = ((x1**2 + y1**2) * (x3 - x2) + (x2**2 + y2**2) * (x1 - x3) + (x3**2 + y3**2) * (x2 - x1)) / d
    r = math.hypot(x1 - ux, y1 - uy)
    a1, a2, a3 = (math.atan2(y - uy, x - ux) for x, y in (start, mid, end))

    def sweep(a: float, b: float) -> float:
        return (b - a) % (2 * math.pi)

    total = sweep(a1, a3)
    if sweep(a1, a2) > total:  # mid is on the other way round
        total -= 2 * math.pi
    return [
        (ux + r * math.cos(a1 + total * i / steps), uy + r * math.sin(a1 + total * i / steps))
        for i in range(steps + 1)
    ]


def outline(root) -> list[list[tuple[float, float]]]:
    """Edge.Cuts as closed loops of points."""
    pieces = []
    for g in k.children(root, "gr_line"):
        if k.atoms(k.child(g, "layer"))[0] == "Edge.Cuts":
            pieces.append([tuple(map(float, k.atoms(k.child(g, h))[:2])) for h in ("start", "end")])
    for g in k.children(root, "gr_arc"):
        if k.atoms(k.child(g, "layer"))[0] == "Edge.Cuts":
            start, mid, end = (tuple(map(float, k.atoms(k.child(g, h))[:2])) for h in ("start", "mid", "end"))
            pieces.append(arc_points(start, mid, end))
    loops = []
    # A circle, a rectangle and a polygon are closed loops of their own.
    for g in k.children(root, "gr_circle"):
        if k.atoms(k.child(g, "layer"))[0] == "Edge.Cuts":
            (cx, cy), (ex, ey) = (tuple(map(float, k.atoms(k.child(g, h))[:2])) for h in ("center", "end"))
            r = math.hypot(ex - cx, ey - cy)
            loops.append(
                [
                    (cx + r * math.cos(2 * math.pi * i / 96), cy + r * math.sin(2 * math.pi * i / 96))
                    for i in range(97)
                ]
            )
    for g in k.children(root, "gr_rect"):
        if k.atoms(k.child(g, "layer"))[0] == "Edge.Cuts":
            (x1, y1), (x2, y2) = (tuple(map(float, k.atoms(k.child(g, h))[:2])) for h in ("start", "end"))
            loops.append([(x1, y1), (x2, y1), (x2, y2), (x1, y2), (x1, y1)])
    for g in k.children(root, "gr_poly"):
        if k.atoms(k.child(g, "layer"))[0] == "Edge.Cuts":
            points = [
                (float(k.atoms(p)[0]), float(k.atoms(p)[1])) for p in k.children(k.child(g, "pts"), "xy")
            ]
            loops.append(points + points[:1])
    while pieces:
        loop = pieces.pop(0)
        joined = True
        while joined:
            joined = False
            for i, piece in enumerate(pieces):
                if math.dist(piece[0], loop[-1]) < 0.01:
                    loop += piece[1:]
                elif math.dist(piece[-1], loop[-1]) < 0.01:
                    loop += piece[::-1][1:]
                else:
                    continue
                pieces.pop(i)
                joined = True
                break
        loops.append(loop)
    return loops


def simplify(points: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float]]:
    """Ramer-Douglas-Peucker, iterative: the points that keep the line within `tolerance`."""
    if len(points) < 3:
        return points
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = points[a], points[b]
        length = math.hypot(bx - ax, by - ay) or 1e-12
        far, index = 0.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            d = abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / length
            if d > far:
                far, index = d, i
        if far > tolerance and index > 0:
            keep[index] = True
            stack += [(a, index), (index, b)]
    return [p for p, kept in zip(points, keep, strict=True) if kept]


def net_name(name: str) -> str:
    return name.lstrip("/")


def pad_place(fp_at: list[float], pad_at: list[float]) -> tuple[float, float]:
    """A pad's place on the board: its offset turned by the footprint's angle, as KiCad turns it."""
    fx, fy = fp_at[0], fp_at[1]
    angle = math.radians(fp_at[2] if len(fp_at) > 2 else 0.0)
    px, py = pad_at[0], pad_at[1]
    return (
        fx + px * math.cos(angle) + py * math.sin(angle),
        fy - px * math.sin(angle) + py * math.cos(angle),
    )


@dataclass
class Board:
    svg: str
    width: float
    height: float
    layers: int
    parts: int
    segments: int
    vias: int
    nets: int
    signal: list[str]


def draw_board(path: Path) -> Board:
    root = k.parse(path.read_text(encoding="utf-8"))
    copper = k.board_copper(path)
    loops = outline(root)
    xs = [x for loop in loops for x, _ in loop]
    ys = [y for loop in loops for _, y in loop]
    x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    pad = 2.0
    signal = [
        str(k.atoms(layer)[0])
        for layer in k.child(root, "layers")[1:]
        if str(k.atoms(layer)[0]).endswith(".Cu")
    ]

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" class="board" viewBox="{f(x1 - pad)} {f(y1 - pad)} {f(x2 - x1 + 2 * pad)} {f(y2 - y1 + 2 * pad)}">',
        f"<!-- {path.name}, drawn by site/examples.py: every coordinate is the board's own, in mm. -->",
    ]
    out.append(
        '<path class="edge" fill-rule="evenodd" d="'
        + " ".join("M" + " L".join(f"{f(x)} {f(y)}" for x, y in loop) + " Z" for loop in loops)
        + '"/>'
    )

    # Pours, by layer: each filled polygon, its points kept within 0.05 mm; on a board over 250 mm
    # across, within 0.3 mm and to 0.1 mm, where its planes would be megabytes of points.
    large = math.hypot(x2 - x1, y2 - y1) > 250
    tolerance, at = (0.3, lambda v: f"{v:.1f}".rstrip("0").rstrip(".")) if large else (0.05, f)
    for zone in k.children(root, "zone"):
        layer = k.child(zone, "layer")
        if layer is None:
            continue
        name = str(k.atoms(layer)[0])
        net = k.child(zone, "net_name") or k.child(zone, "net")
        net_label = net_name(str(k.atoms(net)[0])) if net is not None and k.atoms(net) else ""
        for poly in k.children(zone, "filled_polygon"):
            points = [
                (float(k.atoms(p)[0]), float(k.atoms(p)[1])) for p in k.children(k.child(poly, "pts"), "xy")
            ]
            points = simplify(points, tolerance)
            d = "M" + " L".join(f"{at(x)} {at(y)}" for x, y in points) + " Z"
            out.append(
                f'<path class="pour" data-layer="{name}" data-net="{html.escape(net_label)}" d="{d}"/>'
            )

    # Tracks, back layer first: 1 path per net and width, with its count of segments.
    order = [layer for layer in reversed(signal)]
    for layer in order:
        groups: dict[tuple[str, float], list[str]] = {}
        for net, a, b, width, lay in copper["segments"]:
            if lay == layer:
                groups.setdefault((net_name(net), round(width, 3)), []).append(
                    f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}"
                )
        if not groups:
            continue
        out.append(f'<g class="tracks" data-layer="{layer}">')
        for (net, width), segs in sorted(groups.items()):
            out.append(
                f'<path data-net="{html.escape(net)}" data-n="{len(segs)}" stroke-width="{f(width)}" d="{"".join(segs)}"/>'
            )
        out.append("</g>")

    out.append('<g class="vias">')
    for net, (x, y), size, _drill in copper["vias"]:
        out.append(
            f'<circle data-net="{html.escape(net_name(net))}" cx="{f(x)}" cy="{f(y)}" r="{f(size / 2)}"/>'
        )
    out.append("</g>")

    # Pads, by footprint, back side first; a through-hole pad shows on both sides.
    parts = 0
    footprints = k.children(root, "footprint")
    by_side = sorted(footprints, key=lambda fp: str(k.atoms(k.child(fp, "layer"))[0]) != "B.Cu")
    labels = []
    for fp in by_side:
        props = {
            str(k.atoms(p)[0]): str(k.atoms(p)[1]) for p in k.children(fp, "property") if len(k.atoms(p)) >= 2
        }
        ref = props.get("Reference", "")
        if not ref:
            continue
        parts += 1
        side = "back" if str(k.atoms(k.child(fp, "layer"))[0]) == "B.Cu" else "front"
        fp_at = [float(a) for a in k.atoms(k.child(fp, "at"))]
        shapes = []
        corners = []
        for pad in k.children(fp, "pad"):
            number, kind, shape = (str(a) for a in k.atoms(pad)[:3])
            at = [float(a) for a in k.atoms(k.child(pad, "at"))]
            w, h = (float(a) for a in k.atoms(k.child(pad, "size"))[:2])
            x, y = pad_place(fp_at, at)
            angle = at[2] if len(at) > 2 else 0.0
            net = k.child(pad, "net")
            net_label = net_name(str(k.atoms(net)[-1])) if net is not None and k.atoms(net) else ""
            through = kind == "thru_hole"
            cls = "th" if through else ""
            data = f' data-net="{html.escape(net_label)}"' if net_label else ""
            data += f' data-pad="{html.escape(number)}"' if number else ""
            if shape == "circle":
                shapes.append(f'<circle class="{cls or "p"}"{data} cx="{f(x)}" cy="{f(y)}" r="{f(w / 2)}"/>')
            else:
                rr = 0.0
                if shape == "oval":
                    rr = min(w, h) / 2
                elif shape == "roundrect":
                    ratio = k.child(pad, "roundrect_rratio")
                    rr = float(k.atoms(ratio)[0]) * min(w, h) if ratio is not None else 0.0
                turn = f' transform="rotate({f(-angle)} {f(x)} {f(y)})"' if angle % 360 else ""
                rounded = f' rx="{f(rr)}"' if rr else ""
                shapes.append(
                    f'<rect class="{cls or "p"}"{data} x="{f(x - w / 2)}" y="{f(y - h / 2)}" width="{f(w)}" height="{f(h)}"{rounded}{turn}/>'
                )
            drill = k.child(pad, "drill")
            if through and drill is not None and k.atoms(drill):
                dia = [a for a in k.atoms(drill) if re.match(r"^[\d.]+$", str(a))]
                if dia:
                    shapes.append(
                        f'<circle class="hole" cx="{f(x)}" cy="{f(y)}" r="{f(float(dia[0]) / 2)}"/>'
                    )
            half = max(w, h) / 2
            corners += [(x - half, y - half), (x + half, y + half)]
        if not shapes:
            continue
        value = props.get("Value", "")
        out.append(
            f'<g class="part" data-ref="{html.escape(ref)}" data-value="{html.escape(value)}" data-side="{side}">'
            + "".join(shapes)
            + "</g>"
        )
        cx = (min(c[0] for c in corners) + max(c[0] for c in corners)) / 2
        cy = (min(c[1] for c in corners) + max(c[1] for c in corners)) / 2
        labels.append(f'<text x="{f(cx)}" y="{f(cy)}" data-side="{side}">{html.escape(ref)}</text>')
    out.append('<g class="refs">' + "".join(labels) + "</g>")
    out.append("</svg>")
    nets = {net_name(s[0]) for s in copper["segments"]} | {net_name(v[0]) for v in copper["vias"]}
    nets.discard("")
    return Board(
        svg="\n".join(out) + "\n",
        width=x2 - x1,
        height=y2 - y1,
        layers=len(signal),
        parts=parts,
        segments=len(copper["segments"]),
        vias=len(copper["vias"]),
        nets=len(nets),
        signal=signal,
    )


# ---------------------------------------------------------------- writing a page


def inline(text: str, base: str) -> str:
    """Markdown's inline marks: `code`, **bold**, [a link](path). A path is read from the example's
    folder and named on GitHub."""
    out = html.escape(text, quote=False)
    out = re.sub(r"`([^`]+)`", r"<code>\1</code>", out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", out)

    def link(m: re.Match) -> str:
        label, target = m.group(1), m.group(2)
        if not re.match(r"https?://", target):
            # A path in the repository, as GitHub shows it: a file's blob, a folder's tree.
            path = posixpath.normpath(posixpath.join(base, target.split("#")[0]))
            kind = "tree" if (ROOT / path).is_dir() else "blob"
            target = f"{REPO}/{kind}/main/{path}"
        return f'<a class="link" href="{html.escape(target)}">{label}</a>'

    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", link, out)


def run_block(text: str) -> str:
    """A run as the terminal printed it, marked up as the site's other runs are."""
    lines = text.splitlines()
    command = html.escape(lines[0][2:])
    body = "\n".join(html.escape(line) for line in lines[1:-1])
    verdict = html.escape(lines[-1])
    return f'<pre data-run="example"><span class="prompt">$ </span><span class="cmd">{command}</span>\n<span class="out">{body}</span>\n<span class="verdict">{verdict}</span></pre>'


GH_PATH = (
    "M8 0c4.42 0 8 3.58 8 8a8.013 8.013 0 0 1-5.45 7.59c-.4.08-.55-.17-.55-.38 0-.27.01-1.13.01-2.2 0-.75-.25-1.23-.54-1.48 "
    "1.78-.2 3.65-.88 3.65-3.95 0-.88-.31-1.59-.82-2.15.08-.2.36-1.02-.08-2.12 0 0-.67-.22-2.2.82-.64-.18-1.32-.27-2-.27-.68 "
    "0-1.36.09-2 .27-1.53-1.03-2.2-.82-2.2-.82-.44 1.1-.16 1.92-.08 2.12-.51.56-.82 1.28-.82 2.15 0 3.06 1.86 3.75 3.64 "
    "3.95-.23.2-.44.55-.51 1.07-.46.21-1.61.55-2.33-.66-.15-.24-.6-.83-1.23-.82-.67.01-.27.38.01.53.34.19.73.9.82 1.13.16.45.68 "
    "1.31 2.69.94 0 .67.01 1.3.01 1.49 0 .21-.15.45-.55.38A7.995 7.995 0 0 1 0 8c0-4.42 3.58-8 8-8Z"
)
LOGO = (
    '<svg class="logo" data-logo viewBox="283 202 394 136" fill="currentColor" stroke="currentColor" stroke-width="12" '
    'stroke-linejoin="round" aria-hidden="true"><path class="lg-letter" d="m378.4252 269.28348-44.566925-60.472458h-44.566925'
    'l89.13385 120.9449z"/><path class="lg-pad" d="M389.88452 208.81102h39.46457v33.10237h-39.46457z"/><path class="lg-letter" '
    'd="M464.09186 210.2441h39.46457v120.94487h-39.46457z"/><path class="lg-letter" d="m581.5748 269.28348 44.566895 60.472443'
    'h44.566956l-89.13385-120.9449z"/><path class="lg-pad" d="M570.1155 329.75592h-39.46454v-33.102386h39.46454z"/><g fill="none">'
    '<path class="lg-trace" d="M409.6168 241.91339v57.606293h-31.181091"/><path class="lg-trace" d="M503.55643 270.71652h46.834625'
    'v25.952759"/><path class="lg-trace" d="M570.1155 313.2047h18.233643v-13.669281h15.498657"/><path class="lg-trace" '
    'd="M429.3491 225.3622h17.37146v45.354324h17.368683"/></g></svg>'
)


def shell(title: str, description: str, canonical: str, up: str, body: str, scripts: list[str]) -> str:
    """A page in the site's frame: its head, its header and its footer. `up` leads back to the site's root."""
    script_tags = "\n".join(f'    <script src="{up}{s}" defer></script>' for s in scripts)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{html.escape(title)}</title>
    <meta name="description" content="{html.escape(description)}">
    <link rel="canonical" href="%ORIGIN%/{canonical}">
    <link rel="icon" href="{up}favicon-32.png" sizes="32x32" type="image/png">
    <link rel="icon" href="{up}favicon.svg" type="image/svg+xml">
    <link rel="apple-touch-icon" href="{up}apple-touch-icon.png">
    <link rel="preload" href="{up}fonts/inter-latin-wght-normal.woff2" as="font" type="font/woff2" crossorigin>
    <link rel="stylesheet" href="{up}site.css">
    <meta name="theme-color" content="#fbfaf7" media="(prefers-color-scheme: light)">
    <meta name="theme-color" content="#1b1917" media="(prefers-color-scheme: dark)">
    <!-- Before first paint: the theme the address asks for, else the stored one, else the system's;
         and `motion` unless the reader asked for reduced motion or the page is a capture. -->
    <script>
      (() => {{
        const root = document.documentElement;
        const asked = new URLSearchParams(location.search);
        let stored = asked.get("theme");
        try {{
          stored = stored || localStorage.getItem("theme");
        }} catch {{}}
        const dark = stored ? stored === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
        root.classList.toggle("dark", dark);
        if (stored) for (const m of document.querySelectorAll('meta[name="theme-color"]')) m.content = dark ? "#1b1917" : "#fbfaf7";
        if (asked.get("shot")) root.dataset.shot = asked.get("shot");
        if (!asked.get("shot") && !matchMedia("(prefers-reduced-motion: reduce)").matches) {{
          root.classList.add("motion");
          setTimeout(() => root.dataset.motionReady || root.classList.remove("motion"), 3000);
        }}
      }})();
    </script>
{script_tags}
  </head>
  <body>
    <a class="skip" href="#main">Skip to content</a>

    <header class="site-header">
      <div class="progress" data-progress aria-hidden="true"></div>
      <div class="wrap">
        <a class="brand" href="{up or "./"}" aria-label="Via, home">
          {LOGO}
        </a>
        <nav class="site-nav" aria-label="Site">
          <ul>
            <li><a href="{up}index.html#herald">Example</a></li>
            <li><a href="{up}examples.html">Boards</a></li>
            <li><a href="{up}index.html#gates">Checks</a></li>
            <li><a href="{up}index.html#run">Get started</a></li>
          </ul>
        </nav>
        <div class="header-end">
          <button class="icon-btn" type="button" data-theme-toggle aria-pressed="false" aria-label="Dark theme">
            <svg class="moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20.2 14.6A8.4 8.4 0 1 1 9.4 3.8a6.6 6.6 0 0 0 10.8 10.8Z"/></svg>
            <svg class="sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2.5v2M12 19.5v2M2.5 12h2M19.5 12h2M5.3 5.3l1.4 1.4M17.3 17.3l1.4 1.4M5.3 18.7l1.4-1.4M17.3 6.7l1.4-1.4"/></svg>
          </button>
          <a class="gh-pill" href="{REPO}" aria-label="Via on GitHub">
            <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="{GH_PATH}"/></svg>
            <span>GitHub</span>
          </a>
        </div>
      </div>
    </header>

    <main id="main" tabindex="-1">
{body}
    </main>

    <footer class="site-footer">
      <div class="wrap">
        <div class="row">
          <p class="brand"><a href="{up or "./"}" aria-label="Via, home">{LOGO.replace(" data-logo", "")}</a></p>
          <nav aria-label="Footer">
            <ul>
              <li><a href="{REPO}">GitHub</a></li>
              <li><a href="{REPO}/blob/main/WORKCENTER.md">Contract</a></li>
              <li><a href="{REPO}/blob/main/ee-agent-kit/STATUS.md">Status</a></li>
              <li><a href="{REPO}/blob/main/ee-agent-kit/ROADMAP.md">Roadmap</a></li>
              <li><a href="{REPO}/blob/main/LICENSE">MIT License</a></li>
            </ul>
          </nav>
        </div>
        <p class="small">Via is built under the MIT License.</p>
      </div>
    </footer>

  </body>
</html>
"""


def mm(v: float) -> str:
    """A length to 0.1 mm, without a trailing .0."""
    s = f"{v:.1f}"
    return s[:-2] if s.endswith(".0") else s


def stats(ex: Example, board: Board | None) -> list[str]:
    """The board's specification line: digits, as the site writes a specification (docs/STYLE.md)."""
    out = [ex.version]
    if board:
        out += [
            f"{mm(board.width)} × {mm(board.height)} mm",
            f"{board.layers} layers",
            f"{board.parts} parts",
            f"{board.segments:,} track segments",
            f"{board.vias:,} vias",
        ]
    if ex.verdict:
        out.append(ex.verdict)
    return out


GATES = {
    "ERC": "Electrical rules (ERC)",
    "DRC": "Design rules (DRC)",
    "SIM": "Simulation (SIM)",
    "EXPORT": "Fabrication files (EXPORT)",
}
LAYER_NAMES = {"F.Cu": "Front", "B.Cu": "Back"}


def made(ex: Example) -> dict:
    """What --pictures wrote: the docs/ render each picture came from, and the turntable's frames."""
    path = OUT / ex.slug / "pictures.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


# A still's caption by the render it came from: a board's sides, or an assembly seen from a side.
CAPTIONS = {
    "board-3d-top.png": "The front",
    "board-3d-bottom.png": "The back",
    "assembly-top.png": "From above",
    "assembly-front.png": "From the front",
    "assembly-back.png": "From behind",
    "assembly-iso-back.png": "From behind",
}


def example_page(ex: Example, board: Board | None, pictures: set[str]) -> str:
    folder = f"{ex.slug}/"
    chips = "".join(
        ('<li class="ok">' if s.startswith("GREEN") else "<li>") + html.escape(s) + "</li>"
        for s in stats(ex, board)
    )
    parts = []

    # The board in 3D: the turntable, then the front and the back.
    spin = ""
    record = made(ex)
    turn = record.get("spin", {})
    if "spin.webp" in pictures and turn:
        spin = f"""
          <div class="turntable" data-turntable data-frames="{turn["frames"]}" data-columns="{SPIN_COLUMNS}" tabindex="0" role="img" aria-label="{html.escape(ex.name)} in 3D, turning; drag or use the arrow keys to turn it">
            <div class="tt-frames" style="aspect-ratio:{turn["width"]} / {turn["height"]};background-image:url({folder}spin.webp)"></div>
          </div>
          <p class="tt-hint">Drag to turn the board. KiCad's render of it, {turn["frames"]} views, {round(360 / turn["frames"])} degrees apart.</p>"""
    stills = ""
    if {"top.png", "bottom.png"} <= pictures:
        figures = []
        for name in ("top.png", "bottom.png"):
            caption = CAPTIONS.get(
                record.get("sources", {}).get(name, ""), "The front" if name == "top.png" else "The back"
            )
            w, h = pictures_size(ex, name)
            figures.append(
                f'            <figure><img src="{folder}{name}" width="{w}" height="{h}" loading="lazy" alt="{html.escape(ex.name)}, {caption.lower()}"><figcaption>{caption}</figcaption></figure>'
            )
        stills = '\n          <div class="stills">\n' + "\n".join(figures) + "\n          </div>"
    parts.append(f"""      <section class="ex-hero" aria-labelledby="ex-title">
        <div class="wrap">
          <div data-reveal data-stagger>
            <p class="eyebrow"><a class="crumb" href="../examples.html">Examples</a> · <code>{html.escape(ex.rel)}</code></p>
            <h1 class="display" id="ex-title">{html.escape(ex.name)}</h1>
            <p class="ex-tagline">{html.escape(ex.tagline[:1].upper() + ex.tagline[1:])}</p>
            <p class="lede">{inline(ex.intro, ex.rel)}</p>
            <ul class="chips" aria-label="The board">{chips}</ul>
          </div>{spin}{stills}
        </div>
      </section>""")

    if ex.hard:
        cards = "".join(
            f"<div><h3>{inline(problem, ex.rel)}</h3><p>{inline(answer, ex.rel)}</p></div>"
            for problem, answer in ex.hard
        )
        parts.append(f"""      <section class="section" id="hard" aria-labelledby="hard-title">
        <div class="wrap">
          <div class="head" data-reveal data-stagger>
            <p class="eyebrow">The hard parts</p>
            <h2 class="title" id="hard-title">What is hard about it, and where each part lives</h2>
          </div>
          <div class="hard" data-reveal data-stagger>{cards}</div>
        </div>
      </section>""")

    if board:
        buttons = "\n".join(
            f'                <button type="button" aria-pressed="true" data-layer="{layer}"><i></i>{LAYER_NAMES.get(layer, layer.split(".")[0])}</button>'
            for layer in board.signal
        )
        parts.append(f"""      <section class="section band" id="board" aria-labelledby="board-title">
        <div class="wrap">
          <div class="head" data-reveal data-stagger>
            <p class="eyebrow">Explore the board</p>
            <h2 class="title" id="board-title">Every track and part of the routed board, drawn from its file</h2>
            <p class="lede">The board as <code>{html.escape(board_rel(ex))}</code> holds it: {words(board.layers)} copper layers, {board.segments:,} track segments, {words(board.vias)} vias and {words(board.nets)} nets. Point at a pad to see its part, and click a track, a via or a pad to follow its connection across the board.</p>
          </div>
          <div class="explorer" data-explorer data-src="{folder}board.svg">
            <div class="ex-tools" role="toolbar" aria-label="The drawing">
              <div class="ex-layers" aria-label="Layers">
{buttons}
                <button type="button" aria-pressed="false" data-layer="refs"><i></i>Names</button>
              </div>
              <div class="ex-zoom">
                <button type="button" data-zoom="out" aria-label="Zoom out">&#8722;</button>
                <button type="button" data-zoom="in" aria-label="Zoom in">+</button>
                <button type="button" data-zoom="home">Whole board</button>
              </div>
            </div>
            <div class="ex-view" data-view></div>
            <p class="ex-info" data-info aria-live="polite">Drag to move. Pinch, or hold Ctrl and scroll, to zoom.</p>
          </div>
        </div>
      </section>""")

    if ex.run or ex.checks or ex.per_board:
        if ex.run:
            shown = f'<div class="run">\n{run_block(ex.run)}\n</div>'
            where = f'<a class="link" href="{REPO}/blob/main/{ex.rel}/TIMELINE.md">its timeline</a>'
        elif ex.per_board:
            shown = (
                '<ul class="checks">'
                + "".join(
                    f"<li><span>{html.escape(name)}</span><b>{html.escape(verdict)}</b></li>"
                    for name, verdict in ex.per_board
                )
                + "</ul>"
            )
            where = f'<a class="link" href="{REPO}/blob/main/{ex.rel}/docs/gates.md">its gates report</a>'
        else:
            shown = (
                '<ul class="checks">'
                + "".join(
                    f"<li><span>{GATES.get(gate, gate)}</span><b>{html.escape(summary)}</b></li>"
                    for gate, _, summary in ex.checks
                )
                + "</ul>"
            )
            where = f'<a class="link" href="{REPO}/blob/main/{ex.rel}/docs/gates.md">its gates report</a>'
        parts.append(f"""      <section class="section" id="checks" aria-labelledby="checks-title">
        <div class="wrap">
          <div class="head" data-reveal data-stagger>
            <p class="eyebrow">Checks</p>
            <h2 class="title" id="checks-title">The four checks on {html.escape(ex.name)} {html.escape(ex.version)}</h2>
            <p class="lede">The verdict of the last run, as {where} records it: <b>{html.escape(ex.verdict)}</b>.</p>
          </div>
          <div class="checks-run" data-reveal>{shown}</div>
        </div>
      </section>""")

    if ex.timeline:
        items = []
        for entry in ex.timeline:
            body = []
            for kind, text in entry.blocks:
                if kind == "pre" and text.startswith("$ workcenter "):
                    body.append(f'<div class="run">\n{run_block(text)}\n</div>')
                elif kind == "pre":
                    body.append(f"<pre>{html.escape(text)}</pre>")
                elif text.startswith("Evidence:"):
                    body.append(f'<p class="evidence">{inline(text, ex.rel)}</p>')
                else:
                    body.append(f"<p>{inline(text, ex.rel)}</p>")
            meta = f'<time datetime="{entry.date}">{entry.date}</time>' if entry.date else ""
            meta += f'<span class="stage">{html.escape(entry.version or entry.stage)}</span>'
            if entry.version and entry.stage != entry.version:
                meta += f'<span class="step">{html.escape(entry.stage)}</span>'
            items.append(
                f'<li data-reveal><div class="tl-meta">{meta}</div>'
                f'<div class="tl-body"><h3>{inline(entry.title[:1].upper() + entry.title[1:], ex.rel)}</h3>'
                + "\n".join(body)
                + "</div></li>"
            )
        sources = sorted({f"{e.version}/TIMELINE.md" for e in ex.timeline if e.version})
        records = " and ".join(
            f'<a class="link" href="{REPO}/blob/main/{ex.folder.parent.relative_to(ROOT).as_posix()}/{s}">{s}</a>'
            for s in sources
        )
        if any(not e.version for e in ex.timeline):
            readme = f'the README\'s "What changed" sections (<a class="link" href="{REPO}/blob/main/{ex.rel}/README.md">{html.escape(ex.version)}/README.md</a>)'
            records = f"{records} and {readme}" if records else readme
        parts.append(f"""      <section class="section" id="timeline" aria-labelledby="timeline-title">
        <div class="wrap">
          <div class="head" data-reveal data-stagger>
            <p class="eyebrow">How it was built</p>
            <h2 class="title" id="timeline-title">Every step of the design, with what it changed</h2>
            <p class="lede">Each step as {records} records it, oldest first.</p>
          </div>
          <ol class="timeline">
{chr(10).join("            " + item for item in items)}
          </ol>
        </div>
      </section>""")

    if ex.still_open:
        items = "".join(f"<li>{inline(item, ex.rel)}</li>" for item in ex.still_open[:OPEN_ITEMS])
        more = len(ex.still_open) - OPEN_ITEMS
        rest = (
            f'<p class="after">{words(more).capitalize()} more in <a class="link" href="{REPO}/blob/main/{ex.rel}/README.md">its README</a>.</p>'
            if more > 0
            else ""
        )
        parts.append(f"""      <section class="section band" id="open" aria-labelledby="open-title">
        <div class="wrap">
          <div class="head" data-reveal data-stagger>
            <p class="eyebrow">What is open</p>
            <h2 class="title" id="open-title">What is still to be done on this board</h2>
          </div>
          <ul class="open" data-reveal data-stagger>{items}</ul>{rest}
          <div class="actions">
            <a class="btn btn-primary" href="{REPO}/tree/main/{ex.rel}"><svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="{GH_PATH}"/></svg>Browse the project's files</a>
            <a class="btn btn-fill" href="{REPO}/blob/main/{ex.rel}/README.md">Read its README</a>
          </div>
        </div>
      </section>""")

    return shell(
        f"{ex.name}, designed with Via",
        f"{ex.name} {ex.version}: {ex.intro}",
        f"examples/{ex.slug}",
        "../",
        "\n\n".join(parts),
        ["vendor/motion-14.6.0.js", "site.js", "effects.js", "example.js"],
    )


def board_rel(ex: Example) -> str:
    return ex.board.relative_to(ROOT).as_posix() if ex.board else ""


def pictures_size(ex: Example, name: str) -> tuple[int, int]:
    data = (OUT / ex.slug / name).read_bytes()
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def index_page(found: list[tuple[Example, Board | None]]) -> str:
    cards = []
    for ex, board in found:
        picture = OUT / ex.slug / "iso.png"
        shot = ""
        if picture.is_file():
            w, h = pictures_size(ex, "iso.png")
            shot = f'<div class="shot3d"><img src="examples/{ex.slug}/iso.png" width="{w}" height="{h}" loading="lazy" alt="{html.escape(ex.name)} in 3D"></div>'
        spec = " · ".join(html.escape(s) for s in stats(ex, board)[:4])
        cards.append(
            f'<a class="proj" href="examples/{ex.slug}.html">{shot}<div><h3>{html.escape(ex.name)}</h3>'
            f'<p>{html.escape(ex.tagline[:1].upper() + ex.tagline[1:])}.</p><p class="spec">{spec}</p></div></a>'
        )
    body = f"""      <section class="section" aria-labelledby="examples-title">
        <div class="wrap">
          <div class="head" data-reveal data-stagger>
            <p class="eyebrow">Examples</p>
            <h1 class="title" id="examples-title">Boards designed with Via</h1>
            <p class="lede">Each example is a complete KiCad project in this repository, designed with Via from a Python design file. Open one to turn it in 3D, explore every track on the board, and read how it was built.</p>
          </div>
          <div class="built" data-reveal data-stagger>
            {"".join(cards)}
          </div>
        </div>
      </section>"""
    return shell(
        "Examples: boards designed with Via",
        "Each example is a complete KiCad project designed with Via from a Python design file: its board in 3D, every track, and how it was built.",
        "examples",
        "",
        body,
        ["vendor/motion-14.6.0.js", "site.js", "effects.js"],
    )


# ---------------------------------------------------------------- pictures


def write_pictures(ex: Example) -> None:
    sys.path.insert(0, str(SITE / "showcase"))
    import key
    from PIL import Image

    def keyed(picture: Image.Image, holes: bool) -> Image.Image:
        """The picture with KiCad's backdrop taken out, or as it is when its corners are clear. An
        assembly's render (a ring round a finger) has the backdrop in its middle too."""
        rgba = picture.convert("RGBA")
        w, h = rgba.size
        if all(rgba.getpixel(c)[3] == 0 for c in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))):
            return rgba
        return key.key(picture, holes=holes)

    docs = ex.folder / "docs"
    folder = OUT / ex.slug
    folder.mkdir(parents=True, exist_ok=True)
    record: dict = {"sources": {}}
    for name, sources in PICTURES.items():
        source = next((docs / s for s in sources if (docs / s).is_file()), None)
        if source is None:
            continue
        record["sources"][name] = source.name
        if name == "spin.webp":
            gif = Image.open(source)
            frames = []
            for i in range(gif.n_frames):
                gif.seek(i)
                frames.append(keyed(gif, source.name.startswith("assembly")))
            w, h = frames[0].size
            rows = math.ceil(len(frames) / SPIN_COLUMNS)
            sheet = Image.new("RGBA", (w * SPIN_COLUMNS, h * rows), (0, 0, 0, 0))
            for i, frame in enumerate(frames):
                sheet.paste(frame, ((i % SPIN_COLUMNS) * w, (i // SPIN_COLUMNS) * h))
            sheet.save(folder / name, quality=82, method=6)
            record["spin"] = {"frames": len(frames), "width": w, "height": h}
            print(
                f"site/examples/{ex.slug}/{name}: {len(frames)} frames of {w} x {h}, {(folder / name).stat().st_size // 1024} KB"
            )
            continue
        picture = keyed(Image.open(source), source.name.startswith("assembly"))
        box = picture.getchannel("A").getbbox()
        picture = picture.crop(box) if box else picture
        if picture.width > 1200:
            picture = picture.resize((1200, round(picture.height * 1200 / picture.width)), Image.LANCZOS)
        picture.save(folder / name, optimize=True)
        print(f"site/examples/{ex.slug}/{name}: {picture.width} x {picture.height}, from {source.name}")
    (folder / "pictures.json").write_text(json.dumps(record, indent=1) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- main


def pages() -> dict[Path, str]:
    """Every file this script writes, but the pictures, with its text."""
    found = examples()
    written: dict[Path, str] = {}
    pairs = []
    for ex in found:
        board = draw_board(ex.board) if ex.board else None
        pictures = {p.name for p in (OUT / ex.slug).glob("*")} if (OUT / ex.slug).is_dir() else set()
        if board:
            written[OUT / ex.slug / "board.svg"] = board.svg
        written[OUT / f"{ex.slug}.html"] = example_page(ex, board, pictures)
        pairs.append((ex, board))
    written[SITE / "examples.html"] = index_page(pairs)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check", action="store_true", help="exit 1 when a written file differs from the committed one"
    )
    parser.add_argument(
        "--pictures", action="store_true", help="also write each example's 3D pictures (numpy, Pillow)"
    )
    args = parser.parse_args()
    if args.pictures:
        for ex in examples():
            write_pictures(ex)
    written = pages()
    if args.check:
        stale = [p for p, text in written.items() if not p.is_file() or p.read_text(encoding="utf-8") != text]
        for p in stale:
            print(f"{p.relative_to(ROOT)}: not what site/examples.py writes; run it again", file=sys.stderr)
        return 1 if stale else 0
    for path, text in written.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"{path.relative_to(ROOT)}: {len(text) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
