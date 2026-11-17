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
from pathlib import Path

SIDE = {"F.Cu": "top", "B.Cu": "bottom"}
# KiCad writes these in a placement file's header (kicad-cli pcb export pos --format csv).
POS_REF, POS_SIDE = "Ref", "Side"
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


def board_facts(text: str) -> dict:
    """What the board file says a fab and an assembler get: each placed part with its side, the parts
    kept out of the placement file and why, each net with the pads on it, the copper layers."""
    root = kicadgen().parse(text)
    placed: dict[str, str] = {}
    not_placed: dict[str, str] = {}
    nets: dict[str, list[str]] = {}
    for fp in _children(root, "footprint"):
        ref = _reference(fp)
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
    return {"placed": placed, "not_placed": not_placed, "nets": nets, "copper": copper}


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


def check_placement(text: str, facts: dict, name: str) -> list[str]:
    """A placement file holds each placed part once, on the board's side, and no other part."""
    rows = list(csv.reader(io.StringIO(text)))
    header = rows[0] if rows else []
    if POS_REF not in header or POS_SIDE not in header:
        return [f"{name}: no {POS_REF} and {POS_SIDE} columns in the header {','.join(header)!r}"]
    ref_col, side_col = header.index(POS_REF), header.index(POS_SIDE)
    seen: dict[str, list[str]] = {}
    for row in rows[1:]:
        if len(row) > max(ref_col, side_col):
            seen.setdefault(row[ref_col], []).append(row[side_col])
    lines = []
    for ref, side in facts["placed"].items():
        sides = seen.get(ref)
        if not sides:
            lines.append(f"{name}: {ref} is not in the file; the board places it on the {side}")
        elif len(sides) > 1:
            lines.append(f"{name}: {ref} is in the file {len(sides)} times; the board has it once")
        elif sides[0] != side:
            lines.append(f"{name}: {ref} is on the {sides[0]}; the board places it on the {side}")
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


def check_assembly(data: bytes, facts: dict, side: str, name: str) -> list[str]:
    """An assembly page is a PDF that names each part of its side (KiCad's property popup)."""
    if not data.startswith(b"%PDF-"):
        return [f"{name}: not a PDF (it starts {data[:16].decode('latin-1')!r})"]
    named = {m.group(1).decode("latin-1").strip() for m in PDF_REF.finditer(data)}
    return [
        f"{name}: {ref} is not named; the board places it on the {where}"
        for ref, where in facts["placed"].items()
        if where == side and ref not in named
    ]


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
    if open_ends:
        lines.append(f"{name}: the outline is open at {', '.join(f'({x:g}, {y:g})' for x, y in open_ends)}")
    counts = {count.get(ref, 0) for ref in facts["placed"]}
    boards = counts.pop() if len(counts) == 1 else min(counts, default=0)
    return lines, {"boards": boards, "width": width, "height": height}
