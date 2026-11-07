#!/usr/bin/env python3
"""pdfcurve — one PDF page's vector paths and text lines, as JSON, for `workcenter curve`.

    /opt/workcenters/ee/venv/bin/python tools/pdfcurve.py datasheet.pdf 3

Runs under the workcenter venv: it needs pdfminer.six (requirements.txt). The CLI does the rest
(groups, the plot's frame, the mapping onto its axes) with the standard library.

Each path: its points in PDF points with y up (pdfminer drops Bezier control points and splits a
path at each moveto), its stroke width, whether it is stroked or filled, its colours, and whether it
closes. Exit 1 when the page does not exist.
"""

from __future__ import annotations

import json
import sys

from pdfminer.high_level import extract_pages
from pdfminer.layout import LTCurve, LTLine, LTRect, LTTextLine


def colour(value: object) -> str:
    """A colour as text: a tuple of components rounded, a grey level, or what pdfminer holds."""
    if isinstance(value, (tuple, list)):
        return "(" + ",".join(f"{float(c):g}" for c in value) + ")"
    if isinstance(value, (int, float)):
        return f"{float(value):g}"
    return "" if value is None else str(value)


def page_items(pdf: str, page_no: int) -> dict | None:
    pages = list(extract_pages(pdf, page_numbers=[page_no - 1]))
    if not pages:
        return None
    page = pages[0]
    paths, texts = [], []

    def walk(obj: object) -> None:
        for item in getattr(obj, "_objs", []):
            if isinstance(item, LTCurve):
                kind = "rect" if isinstance(item, LTRect) else "line" if isinstance(item, LTLine) else "path"
                ops = [seg[0] for seg in (item.original_path or [])]
                pts = [[round(float(x), 3), round(float(y), 3)] for x, y in item.pts]
                paths.append(
                    {
                        "id": len(paths) + 1,
                        "kind": kind,
                        "pts": pts,
                        "width": round(float(item.linewidth or 0), 3),
                        "stroke": bool(item.stroke),
                        "fill": bool(item.fill),
                        "color": colour(item.stroking_color),
                        "fill_color": colour(item.non_stroking_color),
                        "closed": (ops[-1:] == ["h"]) or (len(pts) > 2 and pts[0] == pts[-1]),
                    }
                )
            elif isinstance(item, LTTextLine):
                text = item.get_text().strip()
                if text:
                    texts.append({"text": text, "bbox": [round(v, 2) for v in item.bbox]})
                continue
            walk(item)

    walk(page)
    return {"page": page_no, "width": page.width, "height": page.height, "paths": paths, "texts": texts}


def main(argv: list[str]) -> int:
    if len(argv) != 2 or not argv[1].isdigit():
        print(__doc__, file=sys.stderr)
        return 2
    data = page_items(argv[0], int(argv[1]))
    if data is None:
        print(f"pdfcurve: {argv[0]} has no page {argv[1]}", file=sys.stderr)
        return 1
    json.dump(data, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
