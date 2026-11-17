#!/usr/bin/env python3
"""highspeed — a board's fast nets held to the rules of their interfaces.

A project names each interface in `interfaces.json`, 1 line each: the interface (a file in
rules/interfaces/) and its 2 nets, and the pair's gap where the board's default clearance is not it.
Each limit of an interface file names its document, clause, table and page. For each layer a fast track
runs on, the cross-section solver (tools/xsection.py, under the venv) gives the widths for the
impedance band on the board's own stackup, and the gaps for that band at the nominal width.

The command writes KiCad's rules (`track_width`, `diff_pair_gap`, `length`, `skew`) into
<out>/highspeed/highspeed.kicad_dru, for KiCad's DRC, and judges 4 rules itself on the board file:

    width   every segment of a fast net within the band the solver gave for its layer
    length  each net's track length (or its delay, where the document sets a delay) under the limit
    skew    the difference of the pair's 2 lengths under the limit
    plane   every point of a fast track's centre line over copper of its reference plane: the nearest
            copper layer that holds a pour, judged on the pours' fills as KiCad last saved them

Via barrels are not counted in a length. The pair's gap is written for KiCad's DRC and not judged here.
A limit the documents do not set is printed as not judged, with the reason. Standard library only.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kicadgen  # noqa: E402  S-expressions

SPEC_DIR = Path(__file__).resolve().parents[1] / "rules" / "interfaces"
CONSTANTS = json.loads((SPEC_DIR / "constants.json").read_text(encoding="utf-8"))
C0 = CONSTANTS["c0_m_per_s"]["value"]
STEP = 0.01  # mm between the points of a track's centre line the plane check looks under


@dataclass
class Finding:
    status: str  # held, fail, not judged
    rule: str
    text: str


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    rules: str = ""
    bands: dict = field(default_factory=dict)

    def fails(self) -> list[Finding]:
        return [f for f in self.findings if f.status == "fail"]

    def not_judged(self) -> list[Finding]:
        return [f for f in self.findings if f.status == "not judged"]


@dataclass
class Track:
    net: str
    layer: str
    points: list[tuple[float, float]]  # a segment's 2 ends, an arc's start, middle and end
    width: float

    def length(self) -> float:
        if len(self.points) == 2:
            (x1, y1), (x2, y2) = self.points
            return math.hypot(x2 - x1, y2 - y1)
        return _arc_length(*self.points)

    def samples(self) -> list[tuple[float, float]]:
        """Points along the centre line, STEP apart (an arc as its 2 chords through the middle)."""
        out = []
        for (x1, y1), (x2, y2) in zip(self.points, self.points[1:], strict=False):
            n = max(1, math.ceil(math.hypot(x2 - x1, y2 - y1) / STEP))
            out += [(x1 + (x2 - x1) * i / n, y1 + (y2 - y1) * i / n) for i in range(n + 1)]
        return out


@dataclass
class Board:
    stack: list[tuple]  # ("copper", name, thickness) and ("dielectric", thickness, er), top to bottom
    tracks: list[Track]
    vias: dict[str, int]  # net -> count
    fills: dict[str, list[list[tuple[float, float]]]]  # layer -> filled polygons of every pour
    outlines: dict[str, list[list[tuple[float, float]]]]  # layer -> pour outlines
    nets: set[str]
    holes: list[tuple[str, float, float, float]] = field(default_factory=list)  # net, x, y, half diagonal
    margins: dict[str, float] = field(default_factory=dict)  # layer -> pour clearance + min thickness


def _arc_length(a, m, b) -> float:
    (ax, ay), (mx, my), (bx, by) = a, m, b
    d = 2 * (ax * (my - by) + mx * (by - ay) + bx * (ay - my))
    if abs(d) < 1e-12:
        return math.hypot(bx - ax, by - ay)
    ux = ((ax**2 + ay**2) * (my - by) + (mx**2 + my**2) * (by - ay) + (bx**2 + by**2) * (ay - my)) / d
    uy = ((ax**2 + ay**2) * (bx - mx) + (mx**2 + my**2) * (ax - bx) + (bx**2 + by**2) * (mx - ax)) / d
    r = math.hypot(ax - ux, ay - uy)
    chord = math.hypot(bx - ax, by - ay)
    angle = 2 * math.asin(min(1.0, chord / (2 * r)))
    # The middle point on the far side of the chord's centre makes the arc the major one.
    cx, cy = (ax + bx) / 2, (ay + by) / 2
    if (mx - cx) * (ux - cx) + (my - cy) * (uy - cy) > 0:
        angle = 2 * math.pi - angle
    return r * angle


def _xy(node) -> tuple[float, float]:
    vals = kicadgen.atoms(node)
    return (kicadgen.num(vals[0]), kicadgen.num(vals[1]))


def _pts(node) -> list[tuple[float, float]]:
    pts = kicadgen.child(node, "pts")
    return [_xy(p) for p in kicadgen.children(pts, "xy")] if pts else []


def _text(node, head: str) -> str:
    c = kicadgen.child(node, head)
    return kicadgen.atoms(c)[0] if c is not None and kicadgen.atoms(c) else ""


def read_board(text: str) -> Board:
    root = kicadgen.parse(text)
    setup = kicadgen.child(root, "setup")
    stackup = kicadgen.child(setup, "stackup") if setup is not None else None
    stack: list[tuple] = []
    if stackup is not None:
        for layer in kicadgen.children(stackup, "layer"):
            kind = _text(layer, "type")
            thick = _text(layer, "thickness")
            if kind == "copper":
                stack.append(("copper", kicadgen.atoms(layer)[0], kicadgen.num(thick)))
            elif kind in ("core", "prepreg") and thick:
                er = _text(layer, "epsilon_r")
                stack.append(("dielectric", kicadgen.num(thick), kicadgen.num(er) if er else None))
    tracks, vias, nets = [], {}, set()
    for net in kicadgen.children(root, "net"):
        vals = kicadgen.atoms(net)
        if vals:
            nets.add(vals[-1])
    for head in ("segment", "arc"):
        for item in kicadgen.children(root, head):
            net = _text(item, "net")
            nets.add(net)
            keys = ("start", "end") if head == "segment" else ("start", "mid", "end")
            points = [_xy(kicadgen.child(item, k)) for k in keys]
            tracks.append(Track(net, _text(item, "layer"), points, kicadgen.num(_text(item, "width"))))
    holes: list[tuple[str, float, float, float]] = []
    for item in kicadgen.children(root, "via"):
        net = _text(item, "net")
        vias[net] = vias.get(net, 0) + 1
        x, y = _xy(kicadgen.child(item, "at"))
        holes.append((net, x, y, kicadgen.num(_text(item, "size")) / 2))
    fills: dict[str, list] = {}
    outlines: dict[str, list] = {}
    margins: dict[str, float] = {}
    for zone in kicadgen.children(root, "zone"):
        if kicadgen.child(zone, "keepout") is not None:
            continue
        layers = [_text(zone, "layer")] if kicadgen.child(zone, "layer") is not None else []
        many = kicadgen.child(zone, "layers")
        if many is not None:
            layers = kicadgen.atoms(many)
        for layer in layers:
            outlines.setdefault(layer, []).append(_pts(kicadgen.child(zone, "polygon")))
        for filled in kicadgen.children(zone, "filled_polygon"):
            fills.setdefault(_text(filled, "layer"), []).append(_pts(filled))
        clearance = kicadgen.child(zone, "connect_pads")
        clear = (
            kicadgen.num(_text(clearance, "clearance"))
            if clearance is not None and _text(clearance, "clearance")
            else 0.0
        )
        thick = kicadgen.num(_text(zone, "min_thickness")) if _text(zone, "min_thickness") else 0.0
        for layer in layers:
            margins[layer] = max(margins.get(layer, 0.0), clear + thick)
    for item in kicadgen.children(root, "footprint"):
        fx, fy, *rot = (kicadgen.num(v) for v in kicadgen.atoms(kicadgen.child(item, "at")))
        angle = math.radians(rot[0]) if rot else 0.0
        for pad in kicadgen.children(item, "pad"):
            n = _text(pad, "net")
            if n:
                nets.add(n)
            if "thru_hole" not in kicadgen.atoms(pad):
                continue  # only a hole through the board makes a hole in an inner plane
            px, py = _xy(kicadgen.child(pad, "at"))
            sx, sy = _xy(kicadgen.child(pad, "size"))
            x = fx + px * math.cos(angle) + py * math.sin(angle)
            y = fy - px * math.sin(angle) + py * math.cos(angle)
            holes.append((n, x, y, math.hypot(sx, sy) / 2))
    return Board(stack, tracks, vias, fills, outlines, nets, holes, margins)


def section_for(board: Board, layer: str) -> tuple[dict | None, list[str]]:
    """The cross-section of a track on `layer`: the slabs from its reference plane to it (and on to a
    second plane, or to the board's face), the strip's height and thickness. The planes are the nearest
    copper layers above and below that hold a pour. (None, []) when no layer does."""
    names = [s[1] for s in board.stack if s[0] == "copper"]
    if layer not in names:
        return None, []
    idx = next(i for i, s in enumerate(board.stack) if s[0] == "copper" and s[1] == layer)
    planes = set(board.outlines)

    def nearest(step: int) -> int | None:
        i = idx + step
        while 0 <= i < len(board.stack):
            if board.stack[i][0] == "copper" and board.stack[i][1] in planes:
                return i
            i += step
        return None

    below, above = nearest(+1), nearest(-1)
    base, other = (below, above) if below is not None else (above, None)
    if base is None:
        return None, []
    step = -1 if base > idx else 1
    end = other if other is not None else (-1 if step == -1 else len(board.stack))
    slabs: list[list[float]] = []
    height, y, t, er_last = 0.0, None, 0.0, 1.0
    i = base + step
    while i != end:
        item = board.stack[i]
        if item[0] == "dielectric":
            er_last = item[2] if item[2] is not None else er_last
            slabs.append([item[1], er_last])
            height += item[1]
        elif item[1] == layer:
            y, t = height, item[2]
            # The copper's own height beside the strip: the next slab's resin, or air on the face.
            j = i + step
            while j != end and board.stack[j][0] != "dielectric":
                j += step
            if j != end:
                slabs.append([t, board.stack[j][2] or er_last])
                height += t
        else:
            slabs.append([item[2], er_last])
            height += item[2]
        i += step
    refs = [board.stack[base][1]] + ([board.stack[other][1]] if other is not None else [])
    section = {"slabs": [[round(h, 6), er] for h, er in slabs], "top_plane": other is not None}
    section.update({"y": round(y, 6), "t": t})
    return section, refs


def net_length(board: Board, net: str) -> float:
    return sum(t.length() for t in board.tracks if t.net == net)


def _inside(pt: tuple[float, float], poly: list[tuple[float, float]]) -> bool:
    x, y = pt
    hit = False
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1], strict=True):
        if (y1 > y) != (y2 > y) and x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
            hit = not hit
    return hit


def load_spec(name: str) -> dict:
    path = SPEC_DIR / f"{name}.json"
    if name == "constants" or not path.is_file():
        known = ", ".join(sorted(p.stem for p in SPEC_DIR.glob("*.json") if p.stem != "constants"))
        raise ValueError(f"no interface {name!r} in rules/interfaces/: it holds {known}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_interfaces(project: Path) -> list[dict]:
    path = project / "interfaces.json"
    if not path.is_file():
        raise ValueError(f"{path}: no interfaces.json; name each interface and its nets there")
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("interfaces", [])


def cite(spec: dict, limit: dict) -> str:
    doc = spec["documents"][limit["doc"]]
    return f"{doc['maker']} {doc['number']} ({doc['revision']}), {limit['where']}"


def _board_net(board: Board, name: str) -> str:
    for candidate in (name, f"/{name}"):
        if candidate in board.nets:
            return candidate
    raise ValueError(f"no net {name!r} on the board")


def _rule_block(name: str, layer: str | None, condition: str, constraint: str) -> str:
    lines = [f'(rule "{name}"']
    if layer:
        lines.append(f'  (layer "{layer}")')
    lines += [f'  (condition "{condition}")', f"  (constraint {constraint}))"]
    return "\n".join(lines)


def check(pcb: Path, interfaces: list[dict], solver, default_gap: float | None = None) -> Report:
    """Judge the board's fast nets. `solver` takes an xsection request and returns its answer."""
    board = read_board(pcb.read_text(encoding="utf-8"))
    report = Report()
    blocks = [
        "(version 1)",
        "# Written by `workcenter highspeed` from interfaces.json and rules/interfaces/.",
    ]
    if not board.stack:
        raise ValueError(f"{pcb.name}: the board has no stackup; the solver needs its layers and their er")
    for entry in interfaces:
        spec = load_spec(entry.get("interface", ""))
        if len(entry.get("nets", [])) != 2:
            raise ValueError(f"{spec['interface']}: name the pair's 2 nets, P then N")
        nets = [_board_net(board, n) for n in entry["nets"]]
        gap = entry.get("gap", default_gap)
        if gap is None:
            raise ValueError(f"{spec['interface']}: no gap given and no default clearance in the project")
        limits = spec["limits"]
        label = f"{spec['interface']} {'/'.join(entry['nets'])}"
        cond = " || ".join(f"A.NetName == '{n}'" for n in nets)
        imp = limits["impedance"]
        layers = sorted({t.layer for t in board.tracks if t.net in nets})
        eps_by_layer: dict[str, float] = {}

        # ---- width, per layer, from the solver
        for layer in layers:
            section, refs = section_for(board, layer)
            if section is None:
                report.findings.append(
                    Finding(
                        "not judged",
                        "width",
                        f"{label} on {layer}: no pour on any copper layer to stand as its plane",
                    )
                )
                continue
            section.update({"widths": [0.3, 0.3], "gap": gap})
            band = "min" in imp and "max" in imp
            req = {"section": section, "target": imp["nominal"]}
            if band:
                req.update({"low": imp["min"], "high": imp["max"]})
            ans = solver(req)
            if "error" in ans:
                report.findings.append(Finding("not judged", "width", f"{label} on {layer}: {ans['error']}"))
                continue
            eps_by_layer[layer] = ans["line"]["eps_eff"]
            report.bands[layer] = {**ans, "refs": refs}
            src = cite(spec, imp)
            blocks.append(f"# {label} on {layer}: {imp['nominal']} ohm {imp['mode']}; {src}")
            if not band:
                blocks.append(
                    _rule_block(
                        f"{label} width {layer}", layer, cond, f"track_width (opt {ans['width']:.4f}mm)"
                    )
                )
                report.findings.append(
                    Finding("not judged", "width", f"{label} on {layer}: {imp['band_not_stated']}")
                )
                continue
            wmin, wmax = round(ans["width_min"], 4), round(ans["width_max"], 4)
            blocks.append(
                _rule_block(
                    f"{label} width {layer}",
                    layer,
                    cond,
                    f"track_width (min {wmin:.4f}mm) (opt {ans['width']:.4f}mm) (max {wmax:.4f}mm)",
                )
            )
            gmin, gmax = ans.get("gap_min"), ans.get("gap_max")
            if gmin and gmax:
                blocks.append(
                    _rule_block(
                        f"{label} gap {layer}",
                        layer,
                        cond,
                        f"diff_pair_gap (min {gmin:.4f}mm) (opt {gap:.4f}mm) (max {gmax:.4f}mm)",
                    )
                )
            for net in nets:
                widths = [t.width for t in board.tracks if t.net == net and t.layer == layer]
                worst = min(widths) if min(widths) < wmin else max(widths)
                where = f"{net.lstrip('/')} on {layer}"
                if wmin <= worst <= wmax:
                    report.findings.append(
                        Finding("held", "width", f"{where}: {worst:g} mm in {wmin:g} to {wmax:g} mm")
                    )
                else:
                    report.findings.append(
                        Finding(
                            "fail",
                            "width",
                            f"{where} is {worst:g} mm wide; limit {wmin:g} to {wmax:g} mm, the widths the "
                            f"solver gives for {imp['min']:g} to {imp['max']:g} ohm {imp['mode']} at a "
                            f"{gap:g} mm gap over "
                            f"{', '.join(refs)}; source: {src}",
                        )
                    )

        # ---- length, or delay
        lengths = {n: net_length(board, n) for n in nets}
        vias = sum(board.vias.get(n, 0) for n in nets)
        tail = f" ({vias} via barrels not counted)" if vias else ""
        if "max" in limits.get("length", {}):
            lim = limits["length"]
            blocks.append(f"# {label} length: {cite(spec, lim)}")
            blocks.append(_rule_block(f"{label} length", None, cond, f"length (max {lim['max']:.4f}mm)"))
            for net, value in lengths.items():
                text = (
                    f"{net.lstrip('/')} is {value:.4f} mm long{tail}; limit {lim['max']:g} mm; "
                    f"source: {cite(spec, lim)}"
                )
                report.findings.append(Finding("fail" if value > lim["max"] else "held", "length", text))
        elif "max" in limits.get("delay", {}):
            lim = limits["delay"]
            for net in nets:
                delays = [
                    t.length() * math.sqrt(eps_by_layer[t.layer]) / C0 * 1e6
                    for t in board.tracks
                    if t.net == net and t.layer in eps_by_layer
                ]
                if len(delays) < sum(1 for t in board.tracks if t.net == net):
                    report.findings.append(
                        Finding("not judged", "length", f"{net.lstrip('/')}: a layer had no solution")
                    )
                    continue
                value = sum(delays)
                text = (
                    f"{net.lstrip('/')} delays {value:.4f} ns{tail}; limit {lim['max']:g} ns; "
                    f"source: {cite(spec, lim)}"
                )
                report.findings.append(Finding("fail" if value > lim["max"] else "held", "length", text))
        else:
            why = limits.get("length", {}).get("not_stated", "the interface file sets no length")
            report.findings.append(Finding("not judged", "length", f"{label}: {why}"))

        # ---- skew
        lim = limits.get("skew", {})
        if "max" in lim:
            blocks.append(f"# {label} skew: {cite(spec, lim)}")
            blocks.append(_rule_block(f"{label} skew", None, cond, f"skew (max {lim['max']:.4f}mm)"))
            value = abs(lengths[nets[0]] - lengths[nets[1]])
            text = (
                f"{label}: the 2 tracks differ by {value:.4g} mm{tail}; limit {lim['max']:g} mm; "
                f"source: {cite(spec, lim)}"
            )
            report.findings.append(Finding("fail" if value > lim["max"] + 1e-9 else "held", "skew", text))
        else:
            report.findings.append(
                Finding("not judged", "skew", f"{label}: {lim.get('not_stated', 'no skew set')}")
            )

        # ---- plane
        lim = limits.get("plane", {})
        if "doc" not in lim:
            report.findings.append(
                Finding("not judged", "plane", f"{label}: {lim.get('not_stated', 'no plane set')}")
            )
            continue
        for net in nets:
            for layer in layers:
                refs = report.bands.get(layer, {}).get("refs") or section_for(board, layer)[1]
                if not refs:
                    report.findings.append(
                        Finding("not judged", "plane", f"{net.lstrip('/')} on {layer}: no plane")
                    )
                    continue
                ref = refs[0]
                polys = board.fills.get(ref)
                if not polys:
                    report.findings.append(
                        Finding(
                            "not judged",
                            "plane",
                            f"{net.lstrip('/')} on {layer}: the pours on {ref} are not filled",
                        )
                    )
                    continue
                gaps = _gaps(board, net, layer, ref, polys)
                where = f"{net.lstrip('/')} on {layer}"
                if not gaps:
                    report.findings.append(
                        Finding("held", "plane", f"{where}: over {ref} along its whole length")
                    )
                    continue
                (x1, y1), (x2, y2), run = gaps[0]
                more = f", and {len(gaps) - 1} more" if len(gaps) > 1 else ""
                report.findings.append(
                    Finding(
                        "fail",
                        "plane",
                        f"{where} crosses a gap in the plane on {ref} from ({x1:g}, {y1:g}) to "
                        f"({x2:g}, {y2:g}) mm: {run:.2f} mm with no copper under it{more}; limit: a solid "
                        f"plane; source: {cite(spec, lim)}",
                    )
                )
    blocks.append("# The pair's gap holds only where its tracks run side by side; KiCad's DRC judges it.")
    report.rules = "\n".join(blocks) + "\n"
    return report


def _gaps(board: Board, net: str, layer: str, ref: str, polys: list) -> list:
    """Runs of a net's centre line on a layer with no fill of `ref` under them: (first point, last
    point, length). A point within the hole the plane keeps round a through pad or a via of the same
    net (half its diagonal, the pour's clearance and its least thickness) is no gap: the track enters
    that pad there."""
    margin = board.margins.get(ref, 0.0)
    own = [(x, y, r + margin) for n, x, y, r in board.holes if n == net]
    runs = []
    for track in (t for t in board.tracks if t.net == net and t.layer == layer):
        current: list = []
        for pt in track.samples():
            near = any(math.hypot(pt[0] - x, pt[1] - y) <= r for x, y, r in own)
            if near or any(_inside(pt, p) for p in polys):
                if current:
                    runs.append(current)
                    current = []
            else:
                current.append(pt)
        if current:
            runs.append(current)
    out = []
    for run in runs:
        (x1, y1), (x2, y2) = run[0], run[-1]
        out.append(((round(x1, 2), round(y1, 3)), (round(x2, 2), round(y2, 3)), math.hypot(x2 - x1, y2 - y1)))
    return out


def default_clearance(pro: Path | None) -> float | None:
    if pro is None or not pro.is_file():
        return None
    data = json.loads(pro.read_text(encoding="utf-8"))
    for c in data.get("net_settings", {}).get("classes", []):
        if c.get("name") == "Default":
            return c.get("clearance")
    return None


def cmd_highspeed(args, cli) -> int:
    project = cli.find_project(args.project)
    if not project.pcb:
        print(f"SKIPPED highspeed: no board in {project.dir}")
        return cli.EXIT_SKIP
    script = Path(__file__).resolve().parent / "xsection.py"

    def solver(req: dict) -> dict:
        proc = cli.run([cli.venv_python(), "-s", str(script), json.dumps(req)], timeout=900)
        if proc.returncode != 0:
            last = (proc.stderr.strip().splitlines() or ["no output"])[-1]
            return {"error": f"the solver under {cli.venv_python()} ended with {proc.returncode}: {last}"}
        return json.loads(proc.stdout)

    try:
        interfaces = read_interfaces(project.dir)
        report = check(project.pcb, interfaces, solver, default_clearance(project.pro))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"FAIL highspeed: {exc}")
        return cli.EXIT_FAIL
    folder = cli.out_dir_for(project, args.out) / "highspeed"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "highspeed.kicad_dru").write_text(report.rules, encoding="utf-8")
    record = {"findings": [f.__dict__ for f in report.findings], "bands": report.bands}
    (folder / "report.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    for f in report.findings:
        word = {"fail": "FAIL", "held": "held", "not judged": "NOT JUDGED"}[f.status]
        if f.status != "held" or args.verbose:
            print(f"{word} highspeed.{f.rule}: {f.text}")
    for layer, band in report.bands.items():
        print(
            f"rules {layer}: width {band['width']:.4f} mm"
            + (f" ({band['width_min']:.4f} to {band['width_max']:.4f})" if band.get("width_min") else "")
            + f", eps_eff {band['line']['eps_eff']:.3f}, over {', '.join(band['refs'])}"
        )
    print(f"wrote {folder / 'highspeed.kicad_dru'}")
    fails, unjudged = len(report.fails()), len(report.not_judged())
    held = sum(1 for f in report.findings if f.status == "held")
    if fails or (args.strict and unjudged):
        print(f"HIGHSPEED FAIL: {fails} failed, {unjudged} not judged, {held} held")
        return cli.EXIT_FAIL
    print(f"HIGHSPEED HELD: {held} held, {unjudged} not judged")
    return cli.EXIT_PASS


def register(sub, cli) -> None:
    """Add `highspeed` to the workcenter's parser; it sets `run` to its handler."""
    p = sub.add_parser(
        "highspeed",
        help="hold the fast nets that interfaces.json names to their interface's rules: width from the "
        "cross-section solver, length, skew and the reference plane; writes <out>/highspeed/"
        "highspeed.kicad_dru for KiCad's DRC",
    )
    p.add_argument("project", help="project directory or a .kicad_pro/.kicad_pcb file")
    p.add_argument("--out", help="output directory (default <project>/build)")
    p.add_argument("--strict", action="store_true", help="what is not judged fails the run")
    p.add_argument("--verbose", action="store_true", help="print the rules that held too")
    p.set_defaults(run=lambda a: cmd_highspeed(a, cli))
