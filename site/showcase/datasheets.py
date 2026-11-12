"""Draw the first page of each datasheet the example's part labels link, small, for the labels.

    python3 site/showcase/draw_face.py      # the labels, with each part's datasheet address
    python3 site/showcase/datasheets.py     # this: fetches each datasheet, draws its first page
    python3 site/showcase/draw_face.py      # again: each label now names its picture

It reads the datasheet addresses from the labels' JSON in site/index.html (`#herald-parts`), fetches
each PDF, and writes its first page, 160 px wide, to site/showcase/datasheets/<name>.png, where
<name> is the first 12 hex digits of the address's SHA-1. A datasheet that does not download or
is not a PDF is named on stderr and left out: its label keeps the link alone. pdftoppm (poppler)
draws the page.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "site" / "index.html"
OUT = ROOT / "site" / "showcase" / "datasheets"


def name_of(url: str) -> str:
    return hashlib.sha1(url.encode()).hexdigest()[:12]


def main() -> int:
    text = PAGE.read_text(encoding="utf-8")
    found = re.search(r'<script type="application/json" id="herald-parts">(.*?)</script>', text, re.S)
    if not found:
        print("site/index.html holds no #herald-parts: run draw_face.py first", file=sys.stderr)
        return 1
    parts = json.loads(found.group(1).replace("<\\/", "</"))["parts"]
    urls = sorted({p["ds"] for p in parts.values() if p.get("ds")})
    OUT.mkdir(parents=True, exist_ok=True)
    drawn, failed = 0, 0
    for url in urls:
        target = OUT / f"{name_of(url)}.png"
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "via-site/1.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read()
            if not data.startswith(b"%PDF"):
                raise ValueError("not a PDF")
            with tempfile.TemporaryDirectory() as tmp:
                pdf = Path(tmp) / "sheet.pdf"
                pdf.write_bytes(data)
                stem = Path(tmp) / "page"
                subprocess.run(
                    [
                        "pdftoppm",
                        "-f",
                        "1",
                        "-l",
                        "1",
                        "-singlefile",
                        "-png",
                        "-scale-to-x",
                        "160",
                        "-scale-to-y",
                        "-1",
                        str(pdf),
                        str(stem),
                    ],
                    check=True,
                    capture_output=True,
                )
                target.write_bytes(stem.with_suffix(".png").read_bytes())
            drawn += 1
            print(f"{target.relative_to(ROOT)}  {url}")
        except Exception as error:  # noqa: BLE001 - every failure is named, and the label keeps its link
            failed += 1
            print(f"not drawn: {url}: {error}", file=sys.stderr)
    print(f"{drawn} datasheets drawn, {failed} not drawn, of {len(urls)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
