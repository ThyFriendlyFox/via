#!/usr/bin/env python3
"""stretch: grow a board at a cut, in its design file's code.

    python3 tools/stretch.py design.py --cut X --grow G [--out FILE] [--dry-run]

Every board x-coordinate east of x = X moves G mm east: parts, tracks, vias, texts, keep-outs, pour
corners and the outline's east edge. The file is read with Python's own parser, so a number in a
comment or a string never moves. A number is a board x-coordinate in these places only:

- the first of a pair (x, y) whose y lies on the board or is a name or an expression;
- the x of d.via(net, x, y), d.text(label, x, y, ...) and d.circle(cx, cy, r);
- x0 and x1 of the outline, `outline=(x0, y0, x1, y1)`.

The board's extent comes from that outline (or `--outline`), and a pair counts when it lies within
5 mm of it. Pairs under a keyword that starts with `sch` (the schematic) never move. Every other number
east of the cut and on the board is listed, unmoved, for a look by hand (PROCESSES.md P9 step 4).

Writes the result to a new file and moves it over the design (or to --out) once it is complete.
Standard library only. Exit codes: 0 written (or printed with --dry-run), 1 the file cannot be read.
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
from pathlib import Path

MARGIN = 5.0  # mm round the outline that still counts as the board (keep-outs, pours past the edge)
CALL_X = {"via": 1, "text": 1, "circle": 0}  # the x argument of these calls, by position


def number(node: ast.AST) -> float | None:
    """The value of a numeric literal, or of a minus sign before one."""
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = number(node.operand)
        return None if inner is None else -inner
    return None


def decimals(text: str) -> int:
    return len(text.split(".", 1)[1]) if "." in text else 0


def named_numbers(tree: ast.Module) -> dict[str, ast.AST]:
    """Module-level names bound to a number: `X1 = 143.0`, and `X0, X1 = 100.0, 143.0` member by member."""
    out: dict[str, ast.AST] = {}
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target, value = node.targets[0], node.value
        if isinstance(target, ast.Name) and number(value) is not None:
            out[target.id] = value
        elif (
            isinstance(target, ast.Tuple)
            and isinstance(value, ast.Tuple)
            and len(target.elts) == len(value.elts)
        ):
            for name, v in zip(target.elts, value.elts, strict=True):
                if isinstance(name, ast.Name) and number(v) is not None:
                    out[name.id] = v
    return out


def find_outline(tree: ast.Module) -> list[ast.AST] | None:
    """The four number nodes of the first `outline=(x0, y0, x1, y1)` keyword or `outline = (...)`
    assignment; a member that is a module-level name gives the number it is bound to."""
    names = named_numbers(tree)
    for node in ast.walk(tree):
        value = None
        if isinstance(node, ast.keyword) and node.arg == "outline":
            value = node.value
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if "outline" in [
                t.attr if isinstance(t, ast.Attribute) else getattr(t, "id", "") for t in targets
            ]:
                value = node.value
        if isinstance(value, ast.Tuple) and len(value.elts) == 4:
            found = [names.get(e.id) if isinstance(e, ast.Name) else e for e in value.elts]
            if all(f is not None and number(f) is not None for f in found):
                return found
    return None


def stretch(source: str, cut: float, grow: float, outline=None) -> tuple[str, list[str], list[str]]:
    """The source with every board x-coordinate east of `cut` moved `grow` mm east; the lines that say
    what moved, and the numbers east of the cut on the board that did not."""
    tree = ast.parse(source)
    edge = find_outline(tree)
    if outline is None and edge is None:
        raise ValueError("no outline=(x0, y0, x1, y1) of four numbers in the file; give --outline")
    x0, y0, x1, y1 = outline or [number(n) or 0.0 for n in edge or []]
    on_x = (x0 - MARGIN, x1 + MARGIN)
    on_y = (y0 - MARGIN, y1 + MARGIN)
    lines = source.encode("utf-8").splitlines(keepends=True)
    schematic: set[int] = set()  # nodes under a schematic keyword
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and (node.arg or "").startswith("sch"):
            schematic.update(id(n) for n in ast.walk(node.value))
    moves: dict[int, ast.AST] = {}  # id -> the x node to move
    taken: set[int] = set()  # ids of numbers accounted for (a moved x, its y, the outline)

    def east(node: ast.AST) -> bool:
        v = number(node)
        return v is not None and cut < v <= on_x[1]

    def a_y(node: ast.AST) -> bool:
        """A pair's second member: a number on the board, or a name or an expression (`BACK_ROW`)."""
        v = number(node)
        if v is None:
            return not isinstance(node, ast.Constant)
        return on_y[0] <= v <= on_y[1]

    for node in ast.walk(tree):
        if id(node) in schematic:
            continue
        if isinstance(node, ast.Tuple) and len(node.elts) == 2:
            x, y = node.elts
            if east(x) and a_y(y):
                moves[id(x)] = x
                taken.update((id(x), id(y)))
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in CALL_X:
            i = CALL_X[node.func.attr]
            if len(node.args) > i + 1 and east(node.args[i]):
                moves[id(node.args[i])] = node.args[i]
                taken.update((id(node.args[i]), id(node.args[i + 1])))
    for i, e in enumerate(edge or []):  # the outline's own numbers: its west and east edges move
        taken.add(id(e))
        if i in (0, 2) and (number(e) or 0.0) > cut:
            moves[id(e)] = e
    edits = []
    for node in moves.values():
        old = ast.get_source_segment(source, node) or ""
        value = (number(node) or 0.0) + grow
        places = max(decimals(old), decimals(repr(grow)) if grow != int(grow) else 0)
        new = f"{value:.{places}f}"
        edits.append((node.lineno, node.col_offset, node.end_lineno, node.end_col_offset, old, new))
    report = []
    for ln, col, end_ln, end_col, _old, new in sorted(edits, reverse=True):
        if ln != end_ln:
            raise ValueError(f"line {ln}: a number across lines")
        raw = lines[ln - 1]
        lines[ln - 1] = raw[:col] + new.encode("utf-8") + raw[end_col:]
    for ln, _, _, _, old, new in sorted(edits):
        code = source.splitlines()[ln - 1].strip()
        report.append(f"  line {ln}: {old} -> {new}   {code[:100]}")
    left = []
    for node in ast.walk(tree):
        if id(node) in taken or id(node) in schematic or not isinstance(node, ast.Constant):
            continue
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            continue
        if cut < float(node.value) <= on_x[1]:
            code = source.splitlines()[node.lineno - 1].strip()
            left.append(f"  line {node.lineno}: {ast.get_source_segment(source, node)}   {code[:100]}")
    return b"".join(lines).decode("utf-8"), report, sorted(set(left), key=lambda s: int(s.split()[1][:-1]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stretch.py", description=__doc__.splitlines()[0])
    parser.add_argument("design", help="the design file (design.py)")
    parser.add_argument(
        "--cut", type=float, required=True, help="x of the cut, mm: what lies east of it moves"
    )
    parser.add_argument(
        "--grow", type=float, required=True, help="how far it moves east, mm (negative: west)"
    )
    parser.add_argument(
        "--outline",
        type=float,
        nargs=4,
        metavar=("X0", "Y0", "X1", "Y1"),
        help="the board's extent when the file computes its outline",
    )
    parser.add_argument("--out", help="write here instead of over the design file")
    parser.add_argument("--dry-run", action="store_true", help="print what would move; write nothing")
    args = parser.parse_args(argv)
    path = Path(args.design)
    try:
        text, report, left = stretch(path.read_text(encoding="utf-8"), args.cut, args.grow, args.outline)
    except (OSError, SyntaxError, ValueError) as exc:
        print(f"stretch: {path}: {exc}", file=sys.stderr)
        return 1
    print(f"stretch {path}: x > {args.cut:g} moves {args.grow:+g} mm")
    print("\n".join(report) or "  nothing moved")
    if left:
        print(f"left as they were, east of the cut and on the board ({len(left)}): check each by hand")
        print("\n".join(left))
    print(f"moved {len(report)}, left {len(left)}")
    if args.dry_run:
        return 0
    target = Path(args.out) if args.out else path
    tmp = target.with_name(target.name + ".stretch-new")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
