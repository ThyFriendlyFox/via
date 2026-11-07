"""`workcenter curve`: a datasheet's curve read from the PDF's own vectors.

The PDF is written by the test: a frame from (100, 100) to (500, 400) points, log axes from 0.1 to 100
across and from 1e-3 to 1e3 up, thin grid lines, a leader line, two tick labels, and two known curves:
A, y = 1/x**2, stroked 2 points wide; B, y = 10/x**2, drawn the way a datasheet often draws a thick
line, as a filled outline of its two edges 3 points apart. The expected values were computed from the
same formulas before the test was written (P9 step 8).
"""

from __future__ import annotations

import importlib.machinery
import json
import math
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "tools" / "workcenter"
FRAME = ("--frame", "100,100,500,400", "--x", "log:0.1:100", "--y", "log:1e-3:1e3")
VENV_PY = Path("/opt/workcenters/ee/venv/bin/python")


@pytest.mark.skipif(not VENV_PY.exists(), reason="the workcenter venv is not installed")
def test_the_venv_holds_pdfminer_and_pyyaml_at_their_pins():
    """`curve` and `ci` run under the venv and skip without these (P12). Where the venv is installed (CI,
    the cloud environment) a skip would hide that; this test turns it red, and a lost pin with it (P6).
    The venv runs as the commands run it, without -s: it imports what pip installed and reports."""
    pins = {}
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        name, _, version = line.partition("==")
        if version:
            pins[name.strip().lower()] = version.strip()
    proc = subprocess.run(
        [str(VENV_PY), "-c", "import pdfminer, yaml; print(pdfminer.__version__, yaml.__version__)"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.split() == [pins["pdfminer.six"], pins["pyyaml"]]


def load_cli():
    loader = importlib.machinery.SourceFileLoader("workcenter_cli_curve", str(CLI))
    module = types.ModuleType("workcenter_cli_curve")
    module.__file__ = str(CLI)
    sys.modules[module.__name__] = module
    loader.exec_module(module)
    return module


def page_x(lx: float) -> float:
    return 100 + (lx + 1) * 400 / 3


def page_y(ly: float) -> float:
    return 100 + (ly + 3) * 50


def pdf_with(content: str) -> bytes:
    """A one-page PDF around a content stream, with Helvetica as /F1."""
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 500] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for n, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def plot_pdf(path: Path) -> Path:
    ops = ["q", "0.65 w 100 100 400 300 re S", "0.25 w"]
    ops += [f"{page_x(lx):.3f} 100 m {page_x(lx):.3f} 400 l S" for lx in (0, 1)]
    ops += [f"100 {y} m 500 {y} l S" for y in (150, 200, 250, 300, 350)]
    a = [(page_x(lx), page_y(-2 * lx)) for lx in (-1 + 0.25 * k for k in range(11))]
    ops += ["2 w", " ".join(f"{x:.3f} {y:.3f} {'m' if i == 0 else 'l'}" for i, (x, y) in enumerate(a)) + " S"]
    centre = [(page_x(lx), page_y(1 - 2 * lx)) for lx in (-0.75 + 0.25 * k for k in range(11))]
    nx, ny = 0.6, 0.8  # the unit normal of B, whose direction on the page is (0.8, -0.6)
    edges = [(x + 1.5 * nx, y + 1.5 * ny) for x, y in centre] + [
        (x - 1.5 * nx, y - 1.5 * ny) for x, y in centre
    ][::-1]
    ops += [
        "0 0 0 rg",
        " ".join(f"{x:.3f} {y:.3f} {'m' if i == 0 else 'l'}" for i, (x, y) in enumerate(edges)) + " h f",
    ]
    ops += [
        "0.5 w 300 300 m 350 330 l S",
        "BT /F1 8 Tf 230 88 Td (1) Tj ET",
        "BT /F1 8 Tf 362 88 Td (10) Tj ET",
        "Q",
    ]
    path.write_bytes(pdf_with("\n".join(ops)))
    return path


def curve(*args: object) -> tuple[int, dict, str]:
    proc = subprocess.run(
        [sys.executable, str(CLI), *map(str, args)], capture_output=True, text=True, check=False, timeout=300
    )
    data = json.loads(proc.stdout) if args and args[0] == "--json" and proc.stdout.strip() else {}
    return proc.returncode, data, proc.stdout + proc.stderr


# ------------------------------------------------------------ pure logic


def test_an_outline_is_reduced_to_its_middle():
    cli = load_cli()
    # a straight band 2 wide round y = x from (0, 0) to (10, 10): out along one edge, back along the other
    d = 1 / math.sqrt(2)
    one = [(x - d, x + d) for x in range(11)]
    other = [(x + d, x - d) for x in range(11)]
    middle = cli.outline_middle(one + other[::-1] + [one[0]])
    # A midpoint at every point of either chain: 11 + 11 points, the two ends shared, plus the two ends.
    assert len(middle) == 22
    # The ends are the outline's farthest pair, one[0] and other[10]: corners of the stroke's caps.
    assert middle[0] == pytest.approx(one[0]) and middle[-1] == pytest.approx(other[10])
    off = [abs(x - y) / math.sqrt(2) for x, y in middle]
    assert max(off) == pytest.approx(1.0)  # half the stroke's width, at the caps only
    assert all(o < 1e-9 for o in off[2:-2]), off  # beyond a stroke's width of each cap, on the middle
    along = [(x + y) / math.sqrt(2) for x, y in middle]
    assert along == sorted(along)  # in order along the line, no zig-zag


def test_crossings_interpolate_in_decades_on_a_log_axis():
    cli = load_cli()
    axes = (("log", 0.1, 100.0), ("log", 1e-3, 1e3))
    line = [(0.1, 100.0), (100.0, 1e-4)]  # y = 1/x**2
    assert cli.crossings(line, 10, 0, axes) == [pytest.approx(0.01)]
    assert cli.crossings(line, 1, 1, axes) == [pytest.approx(1.0)]
    assert cli.crossings(line, 1000, 0, axes) == []
    lin = (("lin", 0.0, 10.0), ("lin", 0.0, 10.0))
    assert cli.crossings([(0, 0), (4, 8), (8, 0)], 4, 1, lin) == [pytest.approx(2), pytest.approx(6)]
    assert cli.axis_value(300, 100, 500, ("log", 0.1, 100.0)) == pytest.approx(10**0.5)


def test_axes_and_frames_are_refused_when_malformed():
    cli = load_cli()
    assert cli.curve_axis("log:1e-6:10") == ("log", 1e-6, 10.0)
    for bad in ("log:0:10", "lin:5:5", "ln:1:10", "log:1"):
        with pytest.raises(Exception, match="an axis is"):
            cli.curve_axis(bad)
    with pytest.raises(Exception, match="a frame is"):
        cli.curve_frame("100,100,100,400")


# --------------------------------------------------- the PDF through pdfminer


def test_the_listing_groups_paths_and_names_the_frame(tmp_path):
    pytest.importorskip("pdfminer")
    pdf = plot_pdf(tmp_path / "plot.pdf")
    code, listing, _ = curve("--json", "curve", pdf, "--page", "1")
    assert code == 0, listing
    groups = {(g["kind"], g["width"], g["fill"]): g for g in listing["groups"]}
    assert len(groups[("line", 0.25, False)]["ids"]) == 7  # the grid
    assert len(groups[("path", 2.0, False)]["ids"]) == 1  # curve A
    assert len(groups[("path", 2.0, True)]["ids"]) == 1  # curve B, filled under the same 2 point width
    assert len(groups[("line", 0.5, False)]["ids"]) == 1  # the leader line
    assert listing["frames"] == [[100.0, 100.0, 500.0, 400.0]]
    assert {lab["text"] for lab in listing["labels"]} == {"1", "10"}
    code, _, text = curve("curve", pdf)
    assert code == 0
    assert "frame? --frame 100.00,100.00,500.00,400.00" in text
    assert "outline" in text


def test_curves_inside_the_frame_map_onto_the_axes(tmp_path):
    pytest.importorskip("pdfminer")
    pdf = plot_pdf(tmp_path / "plot.pdf")
    code, data, _ = curve("--json", "curve", pdf, *FRAME, "--at", "1,10", "--at-y", "1")
    assert code == 0, data
    a, b = data["curves"]  # left to right; the leader line and the grid are not curves
    assert not a["outline"] and a["points"] == 11
    assert [c["y"] for c in a["at"]] == [[pytest.approx(1.0, rel=1e-3)], [pytest.approx(0.01, rel=1e-3)]]
    assert a["at_y"][0]["x"] == [pytest.approx(1.0, rel=1e-3)]
    # 22 points and pdfminer's copy of the first, where the path closes; a midpoint at each of 2 x 12
    # chain points, the two shared ends counted once
    assert b["outline"] and b["points"] == 23 and len(b["data"]) == 22
    assert [c["y"] for c in b["at"]] == [[pytest.approx(10.0, rel=1e-3)], [pytest.approx(0.1, rel=1e-3)]]
    assert b["at_y"][0]["x"] == [pytest.approx(10**0.5, rel=1e-3)]
    # one path by its id, and the text output
    code, data, _ = curve("--json", "curve", pdf, *FRAME, "--paths", b["path"])
    assert code == 0 and [c["path"] for c in data["curves"]] == [b["path"]]
    code, _, text = curve("curve", pdf, *FRAME, "--at", "1000")
    assert code == 0
    assert "at x=1000: y=outside the curve" in text


def test_a_page_that_is_not_there_and_a_frame_without_axes(tmp_path):
    pytest.importorskip("pdfminer")
    pdf = plot_pdf(tmp_path / "plot.pdf")
    code, _, text = curve("curve", pdf, "--page", "2")
    assert code == 1 and "no page 2" in text
    code, _, text = curve("curve", pdf, "--frame", "100,100,500,400")
    assert code == 1 and "go together" in text
    code, _, text = curve("curve", pdf, "--frame", "0,0,10,10", "--x", "lin:0:1", "--y", "lin:0:1")
    assert code == 1 and "no path" in text
