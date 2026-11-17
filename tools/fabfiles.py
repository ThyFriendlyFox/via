"""The files EXPORT writes for a fab and an assembler, read back against the board they came from.

Standard library only, as the CLI is. Each check takes the text kicad-cli (or KiKit) wrote and the
facts of the board file, and returns 1 line per disagreement: the file, what it says, what the board
says. An empty list is a file that agrees with the board on every point checked here.
"""

from __future__ import annotations

import csv
import io
import re
import sys
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

SIDE = {"F.Cu": "top", "B.Cu": "bottom"}
# KiCad writes these in a placement file's header (kicad-cli pcb export pos --format csv).
POS_REF, POS_SIDE = "Ref", "Side"
POS_PLACE = ("PosX", "PosY", "Rot")
# The file writes 6 decimals (mm, degrees); a place that differs by 1 um or 0.001 degree differs.
POS_TOLERANCE = 1e-3
# The property popup KiCad's PDF plotter writes for each footprint of a plotted layer.
PDF_REF = re.compile(rb"Reference designator = ([^\"\]\)]+)")


def kicadgen():
    """tools/kicadgen.py: its S-expression reader."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import kicadgen as module

    return module


def _child(node: list, head: str) -> list | None:
    return next((c for c in node[1:] if isinstance(c, list) and c and c[0] == head), None)


def _children(node: list, head: str) -> list[list]:
    return [c for c in node[1:] if isinstance(c, list) and c and c[0] == head]


def _reference(fp: list) -> str:
    for prop in _children(fp, "property"):
        if len(prop) > 2 and prop[1] == "Reference":
            return str(prop[2])
    ref = next((c for c in _children(fp, "fp_text") if len(c) > 2 and c[1] == "reference"), None)
    return str(ref[2]) if ref else ""


def _hidden(node: list) -> bool:
    """A text or property KiCad does not draw: `(hide yes)` or a bare `hide`, at any depth."""
    for c in node[1:]:
        if c == "hide":
            return True
        if isinstance(c, list) and c:
            if c[0] == "hide" and (len(c) == 1 or c[1] == "yes"):
                return True
            if c[0] == "effects" and _hidden(c):
                return True
    return False


def _draws_designator_on_fab(fp: list) -> bool:
    """The footprint draws its designator on a Fab layer: a `${REFERENCE}` text there, or its
    Reference property placed there, either not hidden."""
    for node in _children(fp, "fp_text") + _children(fp, "property"):
        layer = _child(node, "layer")
        if not layer or not str(layer[1]).endswith(".Fab") or _hidden(node):
            continue
        if node[0] == "fp_text" and len(node) > 2 and node[2] == "${REFERENCE}":
            return True
        if node[0] == "property" and len(node) > 1 and node[1] == "Reference":
            return True
    return False


def board_facts(text: str) -> dict:
    """What the board file says a fab and an assembler get: each placed part with its side, the parts
    kept out of the placement file and why, each net with the pads on it, the copper layers, how many
    footprints carry each reference, and the parts that draw their designator on a Fab layer."""
    root = kicadgen().parse(text)
    placed: dict[str, str] = {}
    not_placed: dict[str, str] = {}
    nets: dict[str, list[str]] = {}
    count: dict[str, int] = {}
    fab_ref: set[str] = set()
    at: dict[str, tuple[float, float, float]] = {}
    for fp in _children(root, "footprint"):
        ref = _reference(fp)
        count[ref] = count.get(ref, 0) + 1
        if _draws_designator_on_fab(fp):
            fab_ref.add(ref)
        where = _child(fp, "at")
        if where and len(where) > 2:
            at[ref] = (float(where[1]), float(where[2]), float(where[3]) if len(where) > 3 else 0.0)
        layer = _child(fp, "layer")
        side = SIDE.get(str(layer[1]) if layer else "", "top")
        attr = _child(fp, "attr") or []
        if "exclude_from_pos_files" in attr:
            not_placed[ref] = "excluded from the placement file"
        elif "dnp" in attr:
            not_placed[ref] = "not fitted (DNP)"
        else:
            placed[ref] = side
        for pad in _children(fp, "pad"):
            net = _child(pad, "net")
            name = str(net[-1]) if net and len(net) > 1 else ""
            if name:
                nets.setdefault(name, []).append(f"{ref} pad {pad[1]}")
    layers = _child(root, "layers") or []
    copper = [
        str(entry[1]) for entry in layers[1:] if isinstance(entry, list) and str(entry[1]).endswith(".Cu")
    ]
    return {
        "placed": placed,
        "not_placed": not_placed,
        "nets": nets,
        "copper": copper,
        "count": count,
        "fab_ref": fab_ref,
        "at": at,
        "size": outline(root)[:2],
    }


def _edges(root: list) -> list[tuple[tuple[float, float], tuple[float, float]] | tuple[float, ...]]:
    """The Edge.Cuts items of a board: (start, end) of each open item, and the box of each closed one
    (a rectangle, a circle, a polygon), which has no end to meet."""
    items: list = []
    for node in root[1:]:
        if not (isinstance(node, list) and node and str(node[0]).startswith("gr_")):
            continue
        layer = _child(node, "layer")
        if not layer or layer[1] != "Edge.Cuts":
            continue
        start, end = _child(node, "start"), _child(node, "end")
        if node[0] in ("gr_line", "gr_arc") and start and end:
            items.append(((float(start[1]), float(start[2])), (float(end[1]), float(end[2]))))
        elif node[0] == "gr_rect" and start and end:
            xs, ys = (float(start[1]), float(end[1])), (float(start[2]), float(end[2]))
            items.append((min(xs), min(ys), max(xs), max(ys)))
        elif node[0] == "gr_circle" and start and end:
            cx, cy = float(start[1]), float(start[2])
            r = ((float(end[1]) - cx) ** 2 + (float(end[2]) - cy) ** 2) ** 0.5
            items.append((cx - r, cy - r, cx + r, cy + r))
        elif node[0] == "gr_poly":
            pts = [(float(p[1]), float(p[2])) for p in _children(_child(node, "pts") or [], "xy")]
            if pts:
                items.append(
                    (
                        min(x for x, _ in pts),
                        min(y for _, y in pts),
                        max(x for x, _ in pts),
                        max(y for _, y in pts),
                    )
                )
    return items


def outline(root: list) -> tuple[float, float, list[tuple[float, float]]]:
    """The width and height of the outline's box, in mm, and each end held by an odd count of
    Edge.Cuts items: a closed outline has none. Ends meet when they agree to 1 um."""
    xs: list[float] = []
    ys: list[float] = []
    ends: dict[tuple[float, float], int] = {}
    for item in _edges(root):
        if len(item) == 2:
            for x, y in item:
                xs.append(x)
                ys.append(y)
                key = (round(x, 3), round(y, 3))
                ends[key] = ends.get(key, 0) + 1
        else:
            xs += [item[0], item[2]]
            ys += [item[1], item[3]]
    if not xs:
        return 0.0, 0.0, []
    open_ends = sorted(p for p, n in ends.items() if n % 2)
    return round(max(xs) - min(xs), 3), round(max(ys) - min(ys), 3), open_ends


def _same_angle(a: float, b: float) -> bool:
    return abs((a - b + 180.0) % 360.0 - 180.0) < POS_TOLERANCE


def check_placement(text: str, facts: dict, name: str) -> list[str]:
    """A placement file holds each placed part once, on the board's side, at the board's place and
    rotation, and no other part. kicad-cli 10 (no origin option, mm) writes PosX = x and PosY = -y of the
    footprint's (at x y rot), and Rot = rot: so it wrote all 83 parts of Last Hit v0.16 and its display
    on 2026-11-17."""
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0] if rows else []
    if POS_REF not in header or POS_SIDE not in header:
        return [f"{name}: no {POS_REF} and {POS_SIDE} columns in the header {','.join(header)!r}"]
    ref_col, side_col = header.index(POS_REF), header.index(POS_SIDE)
    place = [header.index(c) if c in header else None for c in POS_PLACE]
    seen: dict[str, list[list[str]]] = {}
    for row in rows[1:]:
        if len(row) > max(ref_col, side_col):
            seen.setdefault(row[ref_col], []).append(row)
    lines = []
    if None in place:
        lines.append(f"{name}: no {', '.join(POS_PLACE)} columns in the header {','.join(header)!r}")
    for ref, side in facts["placed"].items():
        found = seen.get(ref)
        footprints = facts.get("count", {}).get(ref, 1)
        if footprints > 1:
            lines.append(
                f"{name}: the board has {footprints} footprints called {ref}; each part needs its own"
            )
        elif not found:
            lines.append(f"{name}: {ref} is not in the file; the board places it on the {side}")
        elif len(found) > 1:
            lines.append(f"{name}: {ref} is in the file {len(found)} times; the board has it once")
        elif found[0][side_col] != side:
            lines.append(f"{name}: {ref} is on the {found[0][side_col]}; the board places it on the {side}")
        elif None not in place and ref in facts.get("at", {}):
            x, y, rot = facts["at"][ref]
            try:
                px, py, pr = (float(found[0][i]) for i in place)
            except (ValueError, IndexError):
                lines.append(f"{name}: {ref} has no number in {', '.join(POS_PLACE)}")
                continue
            if abs(px - x) >= POS_TOLERANCE or abs(py + y) >= POS_TOLERANCE or not _same_angle(pr, rot):
                lines.append(
                    f"{name}: {ref} is at ({px:g}, {py:g}) rotated {pr:g}; the board puts it at "
                    f"({x:g}, {-y:g}) rotated {rot:g}"
                )
    for ref in seen:
        if ref not in facts["placed"]:
            why = facts["not_placed"].get(ref, "no such part")
            lines.append(f"{name}: {ref} is in the file; the board says {why}")
    return lines


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def check_ipc2581(text: str, facts: dict, name: str) -> list[str]:
    """IPC-2581 is well-formed XML that names each copper layer as a CONDUCTOR layer, each net that has
    a pad, and each placed part as a Component on the board's side."""
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return [f"{name}: not well-formed XML: {exc}"]
    conductors, nets, parts = set(), set(), {}
    for el in root.iter():
        tag = _local(el.tag)
        if tag == "Layer" and el.get("layerFunction") == "CONDUCTOR":
            conductors.add(el.get("name"))
        if el.get("net") is not None:
            nets.add(el.get("net"))
        if tag == "Component" and el.get("refDes"):
            parts[el.get("refDes")] = SIDE.get(el.get("layerRef", ""), el.get("layerRef", ""))
    lines = [
        f"{name}: copper layer {layer} is not a CONDUCTOR layer of the file"
        for layer in facts["copper"]
        if layer not in conductors
    ]
    lines += [
        f"{name}: net {net} is not named; the board has it on {pads[0]}"
        for net, pads in facts["nets"].items()
        if net not in nets
    ]
    for ref, side in facts["placed"].items():
        if ref not in parts:
            lines.append(f"{name}: {ref} is not a Component; the board places it on the {side}")
        elif parts[ref] != side:
            lines.append(f"{name}: {ref} is on the {parts[ref]}; the board places it on the {side}")
    return lines


PDF_OBJ = re.compile(rb"(\d+) 0 obj(.*?)endobj", re.S)
PDF_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)
# KiCad 10's PDF plotter draws each glyph of a stroke-font text as its own Type 3 text object at its
# own place: `q a b c d e f cm BT ... /<font> <size> Tf (<code>) Tj ET`.
PDF_GLYPH = re.compile(
    rb"q ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) ([-\d.]+) cm BT [^/]*/(\S+) ([\d.]+) Tf "
    rb"\(((?:\\.|[^\\)])*)\) Tj ET"
)
PDF_CHAR = re.compile(rb"<([0-9A-Fa-f]{2})> <([0-9A-Fa-f]{4})>")


def _pdf_string(raw: bytes) -> bytes:
    """A PDF literal string's bytes: octal escapes and escaped characters undone."""
    out = bytearray()
    i = 0
    while i < len(raw):
        if raw[i] == 0x5C and i + 1 < len(raw):
            octal = re.match(rb"[0-7]{1,3}", raw[i + 1 : i + 4])
            if octal:
                out.append(int(octal.group(0), 8) & 0xFF)
                i += 1 + len(octal.group(0))
                continue
            out.append(raw[i + 1])
            i += 2
            continue
        out.append(raw[i])
        i += 1
    return bytes(out)


def drawn_words(data: bytes) -> list[str]:
    """The words a KiCad PDF draws: each glyph mapped to its character by its font's ToUnicode map,
    and glyphs of 1 font run together into a word while each starts within 1.5 font sizes of the one
    before."""
    objects = {int(m.group(1)): m.group(2) for m in PDF_OBJ.finditer(data)}
    streams: dict[int, bytes] = {}
    for num, body in objects.items():
        m = PDF_STREAM.search(body)
        if m:
            try:
                streams[num] = zlib.decompress(m.group(1))
            except zlib.error:
                streams[num] = m.group(1)
    fonts: dict[bytes, dict[int, str]] = {}
    for body in objects.values():
        font = re.search(rb"/Name /(\S+)", body)
        cmap = re.search(rb"/ToUnicode (\d+) 0 R", body)
        if font and cmap and b"/Font" in body:
            pairs = PDF_CHAR.findall(streams.get(int(cmap.group(1)), b""))
            fonts[font.group(1)] = {int(code, 16): chr(int(uni, 16)) for code, uni in pairs}
    words: list[str] = []
    for text in streams.values():
        word, last = "", None
        for g in PDF_GLYPH.finditer(text):
            font, size = g.group(7), float(g.group(8))
            x, y = float(g.group(5)), float(g.group(6))
            chars = "".join(fonts.get(font, {}).get(b, "") for b in _pdf_string(g.group(9)))
            near = last and last[0] == font and ((x - last[1]) ** 2 + (y - last[2]) ** 2) ** 0.5 <= 1.5 * size
            if not near and word:
                words.append(word)
                word = ""
            word += chars
            last = (font, x, y)
        if word:
            words.append(word)
    return words


def check_assembly(data: bytes, facts: dict, side: str, name: str) -> list[str]:
    """An assembly page is a PDF that draws the designator of each part of its side, and none of a
    part of the other side or of a part not fitted. Read from the drawn text, not from KiCad's property
    popups, which name every footprint plotted on the page whether its designator is drawn or not."""
    if not data.startswith(b"%PDF-"):
        return [f"{name}: not a PDF (it starts {data[:16].decode('latin-1')!r})"]
    drawn = set(drawn_words(data))
    fab_ref = facts.get("fab_ref", set())
    lines = [
        f"{name}: {ref} is not drawn; the board places it on the {where}"
        + ("" if ref in fab_ref else ", and its footprint holds no ${REFERENCE} text on a Fab layer")
        for ref, where in facts["placed"].items()
        if where == side and ref not in drawn
    ]
    lines += [
        f"{name}: {ref} is drawn; the board places it on the {where}"
        for ref, where in facts["placed"].items()
        if where != side and ref in drawn
    ]
    lines += [
        f"{name}: {ref} is drawn; the board says {why}"
        for ref, why in facts["not_placed"].items()
        if why.startswith("not fitted") and ref in drawn
    ]
    return lines


def check_panel(text: str, facts: dict, rows: int, cols: int, name: str) -> tuple[list[str], dict]:
    """A panel holds each placed part of the board on rows x cols boards, inside a closed outline."""
    root = kicadgen().parse(text)
    count: dict[str, int] = {}
    for fp in _children(root, "footprint"):
        ref = _reference(fp)
        count[ref] = count.get(ref, 0) + 1
    want = rows * cols
    lines = [
        f"{name}: {ref} is on {count.get(ref, 0)} boards; the preset asks for {rows} x {cols} = {want}"
        for ref in facts["placed"]
        if count.get(ref, 0) != want
    ]
    width, height, open_ends = outline(root)
    if not width or not height:
        lines.append(f"{name}: no outline on Edge.Cuts (its box is {width:g} x {height:g} mm)")
    elif open_ends:
        lines.append(f"{name}: the outline is open at {', '.join(f'({x:g}, {y:g})' for x, y in open_ends)}")
    w, h = facts.get("size", (0.0, 0.0))
    # A preset may turn the boards a quarter turn; the panel is too small only if neither way fits.
    fits = (width >= cols * w and height >= rows * h) or (width >= cols * h and height >= rows * w)
    if width and height and not fits:
        lines.append(
            f"{name}: the panel is {width:g} x {height:g} mm; {rows} x {cols} boards of {w:g} x {h:g} mm "
            f"need at least {cols * w:g} x {rows * h:g} mm"
        )
    counts = {count.get(ref, 0) for ref in facts["placed"]}
    boards = counts.pop() if len(counts) == 1 else min(counts, default=0)
    return lines, {"boards": boards, "width": width, "height": height}
