"""Draw Herald, the fire alarm communicator, for the site, and the label of every part on it.

    workcenter gates examples/fire-alarm-communicator/v0.1   # first: the labels read its report
    python3 site/showcase/draw_face.py                       # from the repository's root

It reads examples/fire-alarm-communicator/v0.1/design.py (the outline, every pad, every part and
where it sits, the silkscreen's words and mark) and herald.kicad_pcb (the routed tracks and vias),
and writes the drawing into site/index.html between the `face:begin` and `face:end` comments. Every
coordinate is the board's own, in mm: the drawing is the board, not a picture of it.

Beside the drawing it writes what Via holds on each part, as JSON the page labels the parts from:
the value, footprint and nets from the design file; the description and datasheet from the KiCad
library symbol; the README's reason for the part and the problem it answers; and each deck of the
gates report that varies it, with what the deck measured at every corner. The parts come in the
design file's sections, 4 or fewer at a time. Draw it again when the board, the README or the
report changes.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ROOT / "examples" / "fire-alarm-communicator" / "v0.1"
REPORT = PROJECT / "build" / "gates.json"
SHEETS = ROOT / "site" / "showcase" / "datasheets"  # first pages, from datasheets.py
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(PROJECT))

import kicadgen  # noqa: E402

REF = re.compile(r"\b([A-Z]{1,3})(\d+)(?:-(?:\1)?(\d+))?\b")


def f(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def path_of(points: list[tuple[float, float]], close: bool = True) -> str:
    d = "M" + " L".join(f"{f(x)} {f(y)}" for x, y in points)
    return d + (" Z" if close else "")


def refs_in(text: str, known: set[str]) -> list[str]:
    """The board's references a text names, a range such as R25-R27 or J1-J3 taken whole."""
    found: list[str] = []
    for m in REF.finditer(text):
        prefix, a, b = m.group(1), int(m.group(2)), m.group(3)
        for n in range(a, (int(b) if b else a) + 1):
            ref = f"{prefix}{n}"
            if ref in known and ref not in found:
                found.append(ref)
    return found


def table_after(md: str, heading: str) -> list[list[str]]:
    """The rows of the first table under a heading, without its header and rule."""
    rows: list[list[str]] = []
    start = md.index(heading)
    for line in md[start:].splitlines()[1:]:
        if line.startswith("|"):
            rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif rows:
            break
    return rows[2:]


def plain(text: str) -> str:
    """A table cell as text: no backticks."""
    return text.replace("`", "")


def prop(node: list, name: str) -> str:
    """A property of a library symbol's node, or ''."""
    for item in node:
        if isinstance(item, list) and len(item) > 2 and item[0] == "property" and str(item[1]) == name:
            return str(item[2])
    return ""


def sections(d: kicadgen.Design) -> dict[str, str]:
    """Each part's section of the design file: the `# ---- name` comment above the line that names
    it. A reference the file builds in a loop (`f"H{k + 1}"`) takes the first section at or after
    the last one met whose loop builds that prefix."""
    titles: list[str] = []
    literal: dict[str, int] = {}
    built: list[tuple[str, int]] = []
    for line in (PROJECT / "design.py").read_text(encoding="utf-8").splitlines():
        if titles and line.strip() and not line[0].isspace():
            break  # the end of build(): the schematic's block lists below name parts too
        head = re.match(r"^\s+# ---- (.+?) -{3,}\s*$", line)
        if head:
            name = head.group(1).split(":")[0].strip()
            titles.append(name[0].upper() + name[1:])
        if not titles:
            continue
        for ref in re.findall(r'"([A-Z]{1,3}\d+)"', line):
            literal.setdefault(ref, len(titles) - 1)
        for prefix in re.findall(r'\bf"([A-Z]{1,3})\{', line):
            built.append((prefix, len(titles) - 1))
    out, at = {}, 0
    for p in d.parts:
        if p.ref in literal:
            at = literal[p.ref]
        else:
            prefix = re.match(r"[A-Z]+", p.ref).group(0)
            later = [i for pre, i in built if pre == prefix and i >= at]
            at = min(later) if later else at
        out[p.ref] = titles[at]
    return out


def nets_text(part: kicadgen.Part) -> str:
    pins = {pin: net for pin, net in part.nets.items() if net and not net.startswith("unconnected")}
    if len(part.nets) <= 4:
        return " · ".join(f"{pin} {net}" for pin, net in sorted(pins.items(), key=lambda kv: kv[0]))
    nets = sorted(set(pins.values()))
    signals = [n for n in nets if n != "GND" and not n.startswith("+")]
    shown = ", ".join(signals[:8]) + (", …" if len(signals) > 8 else "")
    return f"{len(part.nets)} pins on {len(nets)} nets: {shown}"


def sim_lines(report: list[dict], known: set[str]) -> dict[str, list[str]]:
    """For each part a deck names, what the deck did with it and what it measured at every corner."""
    sim = next(g for g in report if g["gate"] == "sim")
    lines: dict[str, list[str]] = {}
    for deck, run in sim["details"]["decks"].items():
        corners = run.get("corners") or {}
        checks = run.get("checks") or {}
        envelope = corners.get("envelope") or {}
        measure = next(iter(checks), None)
        said = ""
        if measure:
            env, check = envelope.get(measure) or {}, checks[measure]
            lo, hi = env.get("min", check.get("value")), env.get("max", check.get("value"))
            low, high = check.get("min"), check.get("max")  # a bound the deck does not set is null
            bound = (
                f"bound {low:.3g} to {high:.3g}"
                if low is not None and high is not None
                else f"bound at most {high:.3g}"
                if high is not None
                else f"bound at least {low:.3g}"
            )
            said = f": {measure} {lo:.3g} to {hi:.3g} ({bound})"
        temps = " and ".join(f"{t:g}" for t in corners.get("temperatures", [])) + " C"
        for item in corners.get("varied", []):
            if item["name"] in known:
                tol = f"±{item['tolerance'] * 100:g} %"
                text = f"sim/{deck}.cir varies it {tol} at {temps}, {corners.get('runs', 0)} runs{said}"
                lines.setdefault(item["name"], []).append(text)
        for name in corners.get("fixed", []):
            if name in known:
                lines.setdefault(name, []).append(f"sim/{deck}.cir holds it at its written value{said}")
    return lines


def groups_of(order: list[str], section: dict[str, str]) -> list[dict]:
    """The parts in their sections, each section cut into groups of as near 4 as it divides."""
    out: list[dict] = []
    i = 0
    while i < len(order):
        title = section[order[i]]
        j = i
        while j < len(order) and section[order[j]] == title:
            j += 1
        run = order[i:j]
        k = math.ceil(len(run) / 4)
        size, extra = divmod(len(run), k)
        at = 0
        for n in range(k):
            step = size + (1 if n < extra else 0)
            out.append({"t": title, "p": run[at : at + step]})
            at += step
        i = j
    return out


def main() -> int:
    if not REPORT.is_file():
        print(f"{REPORT.relative_to(ROOT)} is missing: run the gates on the example first", file=sys.stderr)
        return 1
    d = kicadgen.load_design(PROJECT / "design.py")
    copper = kicadgen.board_copper(PROJECT / "herald.kicad_pcb")
    parts = {p.ref: p for p in d.parts if p.pcb_at}
    known = set(parts)
    out: list[str] = []
    x1, y1, x2, y2 = d.outline
    pad = 3.0
    out.append(
        f'<svg class="face-svg" viewBox="{f(x1 - pad)} {f(y1 - pad)} {f(x2 - x1 + 2 * pad)} {f(y2 - y1 + 2 * pad)}" '
        'role="img" aria-labelledby="face-title">'
    )
    out.append(
        f'<title id="face-title">Herald v0.1 from the front: its outline, its copper on 3 signal layers and the '
        f"{len(parts)} parts on it, each labelled in turn</title>"
    )
    out.append(f'<path class="pcb" d="{path_of(d.outline_polygon(0.0, 10))}"/>')

    # The copper, the drawing's subject: the back first, then the inner signal layer, then the front,
    # each layer in a group of its own (`data-copper`) that the page sweeps in.
    for layer, cls in (("B.Cu", "cu-b"), ("In2.Cu", "cu-i"), ("F.Cu", "cu-f")):
        widths: dict[float, list[str]] = {}
        for _, a, b, w, lay in copper["segments"]:
            if lay == layer:
                widths.setdefault(round(w, 2), []).append(f"M{f(a[0])} {f(a[1])}L{f(b[0])} {f(b[1])}")
        out.append(f'<g class="{cls}" data-copper="{layer}">')
        for w, segs in sorted(widths.items()):
            out.append(f'<path stroke-width="{f(w)}" d="{"".join(segs)}"/>')
        out.append("</g>")
    out.append('<g class="vias" data-copper="vias">' + "".join(
        f'<circle cx="{f(at[0])}" cy="{f(at[1])}" r="{f(size / 2)}"/>' for _, at, size, _ in copper["vias"]
    ) + "</g>")  # fmt: skip

    # The front's pads.
    rects = []
    for b in d.pad_boxes():
        if b.layer != "F.Cu" or b.kind == "np_thru_hole":
            continue
        rects.append(
            f'<rect x="{f(b.x1)}" y="{f(b.y1)}" width="{f(b.x2 - b.x1)}" height="{f(b.y2 - b.y1)}"/>'
        )
    out.append('<g class="pads">' + "".join(rects) + "</g>")

    # The silkscreen's art on the front: the mark, the rules, the boxes, the words.
    for item in d.art:  # the loaded design's own list
        kind = item[0]
        layer = item[2] if kind == "poly" else item[3]  # ("poly", pts, layer, fill, w)
        if layer != "F.SilkS":
            continue
        if kind == "line":
            (ax, ay), (bx, by), w = item[1], item[2], item[4]
            out.append(
                f'<path class="silk-line" stroke-width="{f(w)}" d="M{f(ax)} {f(ay)}L{f(bx)} {f(by)}"/>'
            )
        elif kind == "rect":
            (ax, ay), (bx, by), w = item[1], item[2], item[5]
            out.append(
                f'<rect class="silk-line" stroke-width="{f(w)}" x="{f(min(ax, bx))}" y="{f(min(ay, by))}" '
                f'width="{f(abs(bx - ax))}" height="{f(abs(by - ay))}"/>'
            )
        elif kind == "poly":
            pts, fill, w = item[1], item[3], item[4]
            cls = "silk-fill" if fill else "silk-line"
            out.append(f'<path class="{cls}" stroke-width="{f(w)}" d="{path_of(pts)}"/>')
        elif kind == "text":
            text, (x, y), size, justify, angle = item[1], item[2], item[4], item[6], item[7]
            # The stylesheet centres every text; a style beats it where the board's text is not.
            anchor = {"left": "start", "right": "end"}.get(justify)
            style = f' style="text-anchor:{anchor}"' if anchor else ""
            turn = f' transform="rotate({f(-angle)} {f(x)} {f(y)})"' if angle else ""
            out.append(
                f'<text class="silk"{style} x="{f(x)}" y="{f(y + size * 0.35)}" '
                f'font-size="{f(size)}"{turn}>{html.escape(text)}</text>'
            )

    # Every part, as the outline of its courtyard: the page lights the ones it labels, and a click
    # on one labels its group.
    for ref, part in parts.items():
        bx = d.courtyard_box(part)
        if bx is None:
            px, py = part.pcb_at
            bx = (px - 1.0, py - 1.0, px + 1.0, py + 1.0)
        a, b_, c, e = bx
        out.append(
            f'<rect class="body" data-ref="{ref}" x="{f(a)}" y="{f(b_)}" width="{f(c - a)}" height="{f(e - b_)}" rx="0.4">'
            f"<title>{ref} {html.escape(part.value)}</title></rect>"
        )
    out.append("</svg>")

    # What Via holds on each part.
    md = (PROJECT / "README.md").read_text(encoding="utf-8")
    why: dict[str, str] = {}
    for row in table_after(md, "## Parts and why"):
        for ref in refs_in(row[0], known):
            why[ref] = f"{plain(row[1])}: {plain(row[2])}"
    pins: dict[str, str] = {}
    for row in table_after(md, "### Connectors"):
        for ref in refs_in(row[0], known):
            pins[ref] = f"{plain(row[1])}. {plain(row[2])}"
    role: dict[str, str] = {}
    for row in table_after(md, "## What is hard about it"):
        for ref in refs_in(row[1], known):
            role.setdefault(ref, plain(row[0]))
    sims = sim_lines(json.loads(REPORT.read_text(encoding="utf-8")), known)
    section = sections(d)

    data: dict[str, dict] = {}
    for ref, part in parts.items():
        node = part.symbol.node
        descr = re.sub(r",? script generated.*$", "", part.descr or prop(node, "Description")).strip()
        sheet = part.datasheet if part.datasheet not in ("", "~") else prop(node, "Datasheet")
        if sheet.startswith("www."):
            sheet = "https://" + sheet
        entry = {
            "v": part.value,
            "d": descr,
            "fp": part.footprint.name if part.footprint else "",
            "n": nets_text(part),
        }
        if sheet.startswith(("http://", "https://")):
            entry["ds"] = sheet
            # The datasheet's first page, where datasheets.py could draw it.
            preview = SHEETS / f"{hashlib.sha1(sheet.encode()).hexdigest()[:12]}.png"
            if preview.is_file():
                width, height = struct.unpack(">II", preview.read_bytes()[16:24])
                entry["dp"] = [f"showcase/datasheets/{preview.name}", width, height]
        for key, source in (("r", role), ("w", why), ("c", pins)):
            if ref in source:
                entry[key] = source[ref]
        if ref in sims:
            entry["s"] = sims[ref]
        data[ref] = entry
    payload = {"groups": groups_of(list(parts), section), "parts": data}
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    drawing = "\n".join(out) + f'\n<script type="application/json" id="herald-parts">{blob}</script>'

    page = ROOT / "site" / "index.html"
    text = page.read_text(encoding="utf-8")
    new, n = re.subn(
        r"(<!-- face:begin -->).*?(\n[ \t]*<!-- face:end -->)",
        lambda m: m.group(1) + "\n" + drawing + m.group(2),
        text,
        flags=re.S,
    )
    if n != 1:
        print("site/index.html has no face:begin / face:end pair", file=sys.stderr)
        return 1
    page.write_text(new, encoding="utf-8")
    counted = {k: sum(1 for e in data.values() if k in e) for k in ("ds", "dp", "r", "w", "c", "s")}
    print(
        f"site/index.html: the face drawn, {len(drawing) // 1024} KB, {len(copper['segments'])} tracks, "
        f"{len(copper['vias'])} vias, {len(data)} parts in {len(payload['groups'])} groups; with a datasheet "
        f"{counted['ds']} ({counted['dp']} with its first page), a problem {counted['r']}, a reason {counted['w']}, "
        f"pins {counted['c']}, a deck {counted['s']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
