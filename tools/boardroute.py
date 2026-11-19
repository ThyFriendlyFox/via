"""A hand-drawn board in front of kicadgen's router: `workcenter autoroute --apply`.

ROADMAP item 15, "Headless autoroute for hand-drawn boards".

kicad-cli 10 has no Specctra export, and a board drawn in KiCad has no design file. This module reads
the `.kicad_pcb` (footprints, pads, outline, nets, tracks and vias) and its `.kicad_pro` (net classes,
board rules) into a `kicadgen.Design`, so the DSN writer, the router run and the session merge are the
ones a generated design uses (`kicadgen.route()`, the autoroute skill's "The rules around a route").
The routed copper goes back into the board file's own text: the route only adds, and every node already
there, the person's tracks and vias among them, stays byte for byte.

What this first cut does not hand to the router is said, never dropped (the item's scope guard): zones,
arc tracks, Edge.Cuts drawn inside a footprint, tracks with no net. An outline other than a rectangle is
refused. There are no routing heuristics here: FreeRouting routes.

Standard library only, as the CLI is.
"""

from __future__ import annotations

import copy
import fnmatch
import json
import os
import stat
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import kicadgen
from kicadgen import Q, atoms, child, children, fmt, num, parse, quote

# The inverse of kicadgen.Design._FLIP_LAYERS: a back footprint's layers as its library names them.
UNFLIP = {back: front for front, back in kicadgen.Design._FLIP_LAYERS.items()}
EDGE_SHAPES = ("gr_line", "gr_rect", "gr_arc", "gr_poly", "gr_circle", "gr_curve")
NOT_HANDED = "not handed to the router: "


@dataclass
class BoardDesign(kicadgen.Design):
    """A Design read from a board file: its nets are the board's own names, in the board's order, and
    no pin is left for the schematic to name (there is no schematic writer here)."""

    board_nets: list[str] = field(default_factory=list)

    def pcb_net_name(self, name: str) -> str:
        return name

    def net_ids(self) -> dict[str, int]:
        return {name: i + 1 for i, name in enumerate(self.board_nets)}

    def unconnected_nets(self) -> dict[tuple[str, str], str]:
        return {}


def _layer(node: list) -> str:
    lay = child(node, "layer")
    return str(atoms(lay)[0]) if lay is not None and atoms(lay) else ""


def _outline(root: list) -> tuple[float, float, float, float]:
    """The board's rectangle (x1, y1, x2, y2) from its Edge.Cuts: 1 gr_rect, or gr_lines that close an
    axis-aligned rectangle. Anything else raises ValueError naming what is drawn there."""
    edges = [
        n for n in root[1:] if isinstance(n, list) and n and n[0] in EDGE_SHAPES and _layer(n) == "Edge.Cuts"
    ]
    shapes = sorted(Counter(str(e[0]) for e in edges).items())
    drawn = ", ".join(f"{count} {kind}" for kind, count in shapes) or "nothing"

    def refuse(why: str) -> ValueError:
        return ValueError(
            f"Edge.Cuts: {drawn}: {why}; this first cut routes inside 1 rectangular outline with nothing "
            "cut inside it (1 gr_rect, or gr_lines that close one)"
        )

    def point(node: list, head: str) -> tuple[float, float]:
        vals = atoms(child(node, head))
        return (num(vals[0]), num(vals[1]))

    if len(edges) == 1 and edges[0][0] == "gr_rect":
        (ax, ay), (bx, by) = point(edges[0], "start"), point(edges[0], "end")
        return (min(ax, bx), min(ay, by), max(ax, bx), max(ay, by))
    if not edges:
        raise refuse("no outline")
    if any(n[0] == "gr_rect" for n in edges):
        raise refuse("a cutout or a second outline beside the board's rectangle")
    if any(n[0] != "gr_line" for n in edges):
        raise refuse("no rectangle")
    refuse_lines = refuse("they close no rectangle")
    lines = [(point(n, "start"), point(n, "end")) for n in edges]
    xs = sorted({p[0] for line in lines for p in line})
    ys = sorted({p[1] for line in lines for p in line})
    if len(xs) != 2 or len(ys) != 2 or any(a[0] != b[0] and a[1] != b[1] for a, b in lines):
        raise refuse_lines
    sides = {tuple(sorted(line)) for line in lines}
    corners = [(x, y) for x in xs for y in ys]
    needed = {
        tuple(sorted((a, b))) for a in corners for b in corners if a < b and (a[0] == b[0]) != (a[1] == b[1])
    }
    if sides != needed:
        raise refuse_lines
    return (xs[0], ys[0], xs[1], ys[1])


def _project_rules(d: BoardDesign, pro: Path) -> None:
    """The .kicad_pro's board rules and net classes onto the design: the Default class gives the track
    width, clearance and via; every other class takes the nets its patterns and assignments name."""
    data = _project(pro)
    if data is None:
        return

    def table(node: object, where: str) -> dict:
        """A JSON object of the file, or {} where the file has none; any other value is refused."""
        if node is None:
            return {}
        if not isinstance(node, dict):
            raise ValueError(f"{pro.name}: {where}: {json.dumps(node)[:60]} is no JSON object")
        return node

    def mm(spec: dict, key: str, where: str, fallback: float) -> float:
        value = spec.get(key, fallback)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{pro.name}: {where}.{key}: {json.dumps(value)[:60]}")
        return float(value)

    design = table(table(data.get("board"), "board").get("design_settings"), "board.design_settings")
    rules = table(design.get("rules"), "board.design_settings.rules")
    known = d.board_rules()
    d.rules = {k: v for k, v in rules.items() if k in known}
    d.edge_clearance = mm(rules, "min_copper_edge_clearance", "board.design_settings.rules", d.edge_clearance)
    settings = table(data.get("net_settings"), "net_settings")
    listed = settings.get("classes") or []
    if not isinstance(listed, list) or not all(isinstance(c, dict) for c in listed):
        raise ValueError(f"{pro.name}: net_settings.classes: no list of JSON objects")
    classes = {c.get("name"): c for c in listed}
    default = classes.get("Default", {})
    at = "net_settings.classes[Default]"
    d.track_width = mm(default, "track_width", at, d.track_width)
    d.clearance = mm(default, "clearance", at, d.clearance)
    d.via_size = mm(default, "via_diameter", at, d.via_size)
    d.via_drill = mm(default, "via_drill", at, d.via_drill)
    member: dict[str, str] = {}
    for net, names in table(
        settings.get("netclass_assignments"), "net_settings.netclass_assignments"
    ).items():
        names = [names] if isinstance(names, str) else list(names)
        if names:
            member.setdefault(net, names[0])
    patterns = settings.get("netclass_patterns") or []
    if not isinstance(patterns, list) or not all(isinstance(r, dict) for r in patterns):
        raise ValueError(f"{pro.name}: net_settings.netclass_patterns: no list of JSON objects")
    for rule in patterns:
        for net in d.board_nets:
            if fnmatch.fnmatchcase(net, str(rule.get("pattern", ""))):
                member.setdefault(net, str(rule.get("netclass", "")))
    for name, spec in classes.items():
        nets = [n for n in d.board_nets if member.get(n) == name]
        if name == "Default" or not nets:
            continue
        at = f"net_settings.classes[{name}]"
        d.net_classes[name] = {
            "width": mm(spec, "track_width", at, d.track_width),
            "clearance": mm(spec, "clearance", at, d.clearance),
            "via": mm(spec, "via_diameter", at, d.via_size),
            "via_drill": mm(spec, "via_drill", at, d.via_drill),
            "nets": nets,
        }


def _project(pro: Path) -> dict | None:
    """The .kicad_pro as a JSON object, or None when there is none. A file that is no JSON object is
    refused by its name."""
    if not pro.is_file():
        return None
    try:
        data = json.loads(pro.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{pro.name}: not JSON (line {exc.lineno}, column {exc.colno}: {exc.msg})") from None
    if not isinstance(data, dict):
        raise ValueError(f"{pro.name}: the file holds a {type(data).__name__}, not a JSON object")
    return data


def unconnected_ignored(pcb: Path) -> str:
    """Why KiCad's DRC of `pcb` cannot list open connections, or "" when it can: the .kicad_pro beside
    it sets board.design_settings.rule_severities.unconnected_items to "ignore", and the DRC then runs
    no connection check at all. The caller judges by the router's own count where its log gives one."""
    pro = Path(pcb).with_suffix(".kicad_pro")
    data = _project(pro) or {}
    design = (data.get("board") or {}).get("design_settings") or {}
    if str((design.get("rule_severities") or {}).get("unconnected_items", "")) != "ignore":
        return ""
    return (
        f"{pro.name} sets unconnected_items to ignore (board.design_settings.rule_severities), so KiCad's "
        "DRC lists no open connection, and the router's log gives no count; set it to error"
    )


def read_board(pcb: Path) -> tuple[BoardDesign, list[str]]:
    """The board file `pcb` (and the .kicad_pro and .kicad_dru beside it) as a Design the DSN writer
    takes, and the lines that say what it does not hand to the router. Raises ValueError on a board
    this first cut cannot hand over whole: an outline that is no rectangle, copper layers out of KiCad's
    order, a surface pad on the side opposite its footprint."""
    pcb = Path(pcb)
    root = parse(pcb.read_text(encoding="utf-8"))
    table = {str(a[0]): str(a[1]) for a in (atoms(n) for n in children(root, "net")) if len(a) >= 2}

    def net_of(node: list) -> str:
        n = child(node, "net")
        vals = atoms(n) if n is not None else []
        named = [v for v in vals if isinstance(v, Q)]
        if named:
            return str(named[-1])
        return table.get(str(vals[0]), "") if vals else ""

    layers = child(root, "layers")
    copper = [
        str(e[1])
        for e in (layers or [])[1:]
        if isinstance(e, list) and len(e) > 1 and str(e[1]).endswith(".Cu")
    ]
    d = BoardDesign(
        name=pcb.stem, namespace=uuid.uuid5(uuid.NAMESPACE_URL, f"workcenter-autoroute:{pcb.stem}")
    )
    d.copper_layers = len(copper)
    if copper != d.copper_names():
        raise ValueError(f"copper layers {copper}: this first cut takes {d.copper_names()}")
    d.outline = _outline(root)
    notes: list[str] = []

    order = [n for n in table.values() if n]
    seen_images: dict[str, tuple] = {}
    for fp in children(root, "footprint"):
        lib_id = str(fp[1])
        lib, _, fp_name = lib_id.partition(":")
        at = atoms(child(fp, "at"))
        x, y, rot = num(at[0]), num(at[1]), (num(at[2]) if len(at) > 2 else 0.0)
        back = _layer(fp) == "B.Cu"
        ref = next((str(p[2]) for p in children(fp, "property") if str(p[1]) == "Reference"), "")
        if not ref:
            ref = next((str(t[2]) for t in children(fp, "fp_text") if str(t[1]) == "reference"), "?")
        edge = [str(g[0]) for g in fp[1:] if isinstance(g, list) and g and _layer(g) == "Edge.Cuts"]
        if edge:
            notes.append(
                f"{NOT_HANDED}Edge.Cuts drawn in footprint {ref} ({len(edge)} shapes; the DRC judges them)"
            )
        pads: list[kicadgen.Pad] = []
        nets: dict[str, str] = {}
        for i, p in enumerate(children(fp, "pad")):
            number, kind, shape = str(p[1]), str(p[2]), str(p[3])
            pat = atoms(child(p, "at"))
            px, py = num(pat[0]), num(pat[1])
            angle = ((num(pat[2]) if len(pat) > 2 else 0.0) - rot) % 360
            pad_layers = [str(a) for a in atoms(child(p, "layers"))]
            node = p
            if back:
                # The file holds the footprint flipped about its X axis (kicadgen.Design._flip, KiCad's
                # Flip): turn it back, as the library draws it, and the DSN writer flips it again.
                py, angle = -py, (-angle) % 360
                pad_layers = [UNFLIP.get(a, a) for a in pad_layers]
                node = copy.deepcopy(p)
                kicadgen.Design._flip(node)
            if not any(a.endswith(".Cu") for a in pad_layers):
                continue  # a paste or mask window: no copper, on its footprint's side, nothing to route
            if kind == "smd" and "F.Cu" not in pad_layers:
                raise ValueError(
                    f"{ref} pad {number or f'@{i}'}: a surface pad on {pad_layers} of a footprint on "
                    f"{_layer(fp)}; this first cut takes surface pads on their footprint's side only"
                )
            size = atoms(child(p, "size"))
            w, h = num(size[0]), num(size[1])
            drill = child(p, "drill")
            drill_vals = [a for a in atoms(drill) if a != "oval"] if drill is not None else []
            outline: tuple[tuple[float, float], ...] = ()
            if shape == "custom":
                outline = kicadgen._custom_pad_outline(node, w, h)
                w, h = kicadgen._custom_pad_extent(node, w, h)
            pin = number or f"@{i}"  # a pad with no number still stands in the router's way
            pads.append(
                kicadgen.Pad(
                    pin,
                    kind,
                    shape,
                    px,
                    py,
                    round(angle, 6),
                    w,
                    h,
                    pad_layers,
                    num(drill_vals[0]) if drill_vals else 0.0,
                    outline,
                )  # fmt: skip
            )
            net = net_of(p)
            if net and number:
                nets.setdefault(number, net)
                if net not in order:
                    order.append(net)
        if not any(any(a.endswith(".Cu") for a in pad.layers) for pad in pads):
            continue  # a logo or a fiducial drawing: no copper for the router
        shape_key = tuple(
            (p.number, p.kind, p.shape, p.x, p.y, p.angle, p.w, p.h, p.drill, p.outline) for p in pads
        )
        if seen_images.setdefault(lib_id, shape_key) != shape_key:
            fp_name = f"{fp_name}@{ref}"  # the same library name with other pads: an image of its own
        footprint = kicadgen.Footprint(lib, fp_name, fp, pads, None)
        d.parts.append(
            kicadgen.Part(
                ref,
                None,
                "",
                footprint,
                (0.0, 0.0),
                pcb_at=(x, y),
                pcb_rot=rot,
                pcb_layer="B.Cu" if back else "F.Cu",
                nets=nets,
            )  # fmt: skip
        )
    d.board_nets = order
    _project_rules(d, pcb.with_suffix(".kicad_pro"))
    dru = pcb.with_suffix(".kicad_dru")
    if dru.is_file():
        d.fab = str(dru)

    held = kicadgen.board_copper(pcb)
    ids = d.net_ids()
    d.segments = [s for s in held["segments"] if s[0] in ids]
    d.vias = [v for v in held["vias"] if v[0] in ids]
    loose = len(held["segments"]) - len(d.segments) + len(held["vias"]) - len(d.vias)
    if loose:
        notes.append(f"{NOT_HANDED}{loose} tracks and vias on no net of a pad (the DRC judges them)")
    for z in children(root, "zone"):
        where = ", ".join(str(a) for head in ("layer", "layers") for a in atoms(child(z, head) or [head]))
        if child(z, "keepout") is not None:
            notes.append(
                f"{NOT_HANDED}keepout zone on {where} (zones are out of this first cut; the DRC judges it)"
            )
        else:
            net = net_of(z) or "no net"
            notes.append(
                f"{NOT_HANDED}zone of {net} on {where} (zones are out of this first cut; the DRC judges it)"
            )
    if held["arcs"]:
        many = "arc tracks" if held["arcs"] > 1 else "arc track"
        notes.append(
            f"{NOT_HANDED}{held['arcs']} {many} (arcs are out of this first cut; the DRC judges them)"
        )
    return d, notes


def _top_nodes(text: str) -> list[tuple[str, int, int]]:
    """(head, start, end) of each node directly inside the file's root node; text[start:end] is the
    node, brackets included. Quoted strings are skipped, so a bracket in a value cannot cut one short."""
    out: list[tuple[str, int, int]] = []
    depth, start, i, quoted = 0, -1, 0, False
    while i < len(text):
        ch = text[i]
        if quoted:
            if ch == "\\":
                i += 1
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch == "(":
            depth += 1
            if depth == 2:
                start = i
        elif ch == ")":
            if depth == 2:
                head = text[start + 1 :].split(None, 1)[0].rstrip(")")
                out.append((head, start, i + 1))
            depth -= 1
        i += 1
    return out


def _seg_key(net: str, a, b, width: float, layer: str) -> tuple:
    ends = sorted(((fmt(a[0]), fmt(a[1])), (fmt(b[0]), fmt(b[1]))))
    return (net, layer, *ends, fmt(width))


def _via_key(net: str, at, size: float, drill: float) -> tuple:
    return (net, fmt(at[0]), fmt(at[1]), fmt(size), fmt(drill))


def _locked(node: list) -> bool:
    """KiCad 10 writes `(locked yes)`; older files a bare `locked` after the head."""
    lock = child(node, "locked")
    return "locked" in node[1:] or (lock is not None and str((atoms(lock) or ["yes"])[0]) == "yes")


def _uuid(node: list) -> str:
    vals = atoms(child(node, "uuid") or ["uuid"])
    return str(vals[0]) if vals else "(no uuid)"


def write_board(text: str, d: BoardDesign, said: list[str] | None = None) -> str:
    """The board file's text with the design's tracks and vias: a track or via node the design holds
    stays as it was written, one it no longer holds goes (a line for each in `said`, when given), and
    each new one is appended in the net form the file uses: `(net N)` with a table of numbered nets,
    else `(net "name")`. A locked track or via the design no longer holds is refused (ValueError)."""
    root = parse(text)
    table = {str(a[1]): str(a[0]) for a in (atoms(n) for n in children(root, "net")) if len(a) >= 2}
    by_number = {v: k for k, v in table.items()}
    ids = d.net_ids()
    want_s = Counter(_seg_key(*s) for s in d.segments)
    want_v = Counter(_via_key(*v) for v in d.vias)

    def node_net(node: list) -> str:
        n = child(node, "net")
        vals = atoms(n) if n is not None else []
        named = [v for v in vals if isinstance(v, Q)]
        return str(named[-1]) if named else by_number.get(str(vals[0]), "") if vals else ""

    def pt(node: list, head: str) -> tuple[float, float]:
        vals = atoms(child(node, head))
        return (num(vals[0]), num(vals[1]))

    cut: list[tuple[int, int]] = []
    for head, start, end in _top_nodes(text):
        if head not in ("segment", "via"):
            continue
        node = parse(text[start:end])
        net = node_net(node)
        if net not in ids:
            continue  # never handed to the router: it stays
        if head == "segment":
            key = _seg_key(
                net, pt(node, "start"), pt(node, "end"), num(atoms(child(node, "width"))[0]), _layer(node)
            )
            pool = want_s
        else:
            size, drill = num(atoms(child(node, "size"))[0]), num(atoms(child(node, "drill"))[0])
            key, pool = _via_key(net, pt(node, "at"), size, drill), want_v
        if pool[key] > 0:
            pool[key] -= 1
            continue
        what = f"hand {'track' if head == 'segment' else 'via'} {_uuid(node)} on {net}"
        if _locked(node):
            raise ValueError(f"locked {what}: the route would remove it; nothing written")
        if said is not None:
            said.append(f"removed {what}: the route holds it no more")
        line = text.rfind("\n", 0, start) + 1
        stop = end + 1 if text[end : end + 1] == "\n" else end
        cut.append((line if not text[line:start].strip() else start, stop))

    def net_form(name: str) -> str:
        return f"(net {table[name]})" if table and name in table else f"(net {quote(name)})"

    def uid(key: tuple) -> str:
        return str(uuid.uuid5(d.namespace, "route/" + "/".join(map(str, key))))

    added: list[str] = []
    for net, a, b, w, layer in d.segments:
        key = _seg_key(net, a, b, w, layer)
        if want_s[key] > 0:
            want_s[key] -= 1
            added.append(
                f"\t(segment (start {fmt(a[0])} {fmt(a[1])}) (end {fmt(b[0])} {fmt(b[1])}) (width {fmt(w)}) "
                f'(layer {quote(layer)}) {net_form(net)} (uuid "{uid(key)}"))\n'
            )
    for net, at, size, drill in d.vias:
        key = _via_key(net, at, size, drill)
        if want_v[key] > 0:
            want_v[key] -= 1
            added.append(
                f"\t(via (at {fmt(at[0])} {fmt(at[1])}) (size {fmt(size)}) (drill {fmt(drill)}) "
                f'(layers "F.Cu" "B.Cu") {net_form(net)} (uuid "{uid(key)}"))\n'
            )
    # The new copper goes in before `(embedded_fonts ...)`, which KiCad writes last, else before the
    # root's closing bracket, at the start of its line.
    tail = next((s for h, s, _ in _top_nodes(text) if h == "embedded_fonts"), text.rstrip().rfind(")"))
    line = text.rfind("\n", 0, tail) + 1
    new = "".join(added)
    if text[line:tail].strip():
        new = "\n" + new
    else:
        tail = line
    edits = sorted([*((start, stop, "") for start, stop in cut), (tail, tail, new)])
    out, pos = [], 0
    for start, stop, piece in edits:
        out += [text[pos:start], piece]
        pos = max(pos, stop)
    return "".join(out) + text[pos:]


class NotWritten(Exception):
    """The route was not written into the board file, and the message says why; the file is as it was."""


# A router end this close to another end (a hand track's, a hand via's, the router's own) is that end.
SNAP_MM = 0.001


def _router_copper(d: BoardDesign, hand_s: list, hand_v: list) -> tuple[list, list]:
    """The router's own tracks and vias in `d` after the route. The session merge splits a hand track
    where the router ends on it, and keeps 1 of 2 tracks that overlap; those pieces of the person's
    tracks are left out, so the hand tracks stay whole (KiCad joins a track end on a track's middle).
    Each router end within SNAP_MM of an end before it is written at that end."""

    def on(p: tuple[float, float], h: tuple) -> bool:
        return kicadgen._seg_dist(p, h[1], h[2]) < 1e-4

    own = [
        s
        for s in d.segments
        if not any(s[0] == h[0] and s[4] == h[4] and on(s[1], h) and on(s[2], h) for h in hand_s)
    ]
    anchors = [p for h in hand_s for p in (h[1], h[2])] + [v[1] for v in hand_v]

    def snap(p: tuple[float, float]) -> tuple[float, float]:
        near = next((q for q in anchors if abs(p[0] - q[0]) < SNAP_MM and abs(p[1] - q[1]) < SNAP_MM), None)
        if near is None:
            anchors.append(p)
        return near or p

    segments = [(n, snap(a), snap(b), w, ly) for n, a, b, w, ly in own]
    vias = [(n, snap(at), size, drill) for n, at, size, drill in d.vias[len(hand_v) :]]
    return [s for s in segments if s[1] != s[2]], vias


def _lock_file(pcb: Path, target: Path) -> Path | None:
    """KiCad's lock file of the board, `~<name>.lck` beside it (or beside the file a link names)."""
    return next(
        (lock for p in (pcb, target) if (lock := p.with_name(f"~{p.name}.lck")).exists()),
        None,
    )


def _check_writable(pcb: Path, target: Path) -> None:
    """Refuse (NotWritten) a board file with no write bit or one KiCad holds open."""
    mode = target.stat().st_mode
    if not mode & 0o222 or not os.access(target, os.W_OK):
        raise NotWritten(f"{pcb.name} is read-only; nothing written")
    lock = _lock_file(pcb, target)
    if lock is not None:
        raise NotWritten(
            f"{pcb.name} is open in KiCad ({lock.name} beside it); close it there (or remove a lock file "
            "KiCad left behind) and run again; nothing written"
        )


def _before_path(build_dir: Path, name: str) -> Path:
    """The first free `<name>.before.kicad_pcb`, `<name>.before-2.kicad_pcb`, ...: no run writes over
    an earlier run's copy, so the first is the board as the person drew it."""
    path, i = build_dir / f"{name}.before.kicad_pcb", 1
    while path.exists():
        i += 1
        path = build_dir / f"{name}.before-{i}.kicad_pcb"
    return path


def apply(
    pcb: Path,
    build_dir: Path,
    passes: int = 60,
    threads: int = 0,
    timeout: int = 900,
    router: str = "freerouting",
) -> dict:
    """Route the board file `pcb` in place: read it, run the router through `kicadgen.route()` (which
    writes the DSN, the session and the log in `build_dir`), add the router's copper to the board's own
    text (the person's tracks and vias stay as they are written). The board before the route is kept as
    `build_dir/<name>.before.kicad_pcb`, or `.before-2`, ... when an earlier run's copy is there. A link
    is written through to the file it names, and the file keeps its mode. Returns route()'s summary with
    "notes", the lines of what was not handed to the router, and "before". A router that fails or is
    absent raises, and the board file is not touched; a board that is read-only, open in KiCad, changed
    while the router ran, or that cannot be written raises NotWritten, and the file is as it was."""
    pcb = Path(pcb)
    target = pcb.resolve()
    _check_writable(pcb, target)
    raw = target.read_bytes()
    text = raw.decode("utf-8")
    d, notes = read_board(pcb)
    hand_s, hand_v = list(d.segments), list(d.vias)
    summary = kicadgen.route(
        d, Path(build_dir), passes=passes, threads=threads, timeout=timeout, router=router
    )
    segments, vias = _router_copper(d, hand_s, hand_v)
    d.segments, d.vias = hand_s + segments, hand_v + vias
    removed: list[str] = []
    routed = write_board(text, d, removed)
    fresh = target.with_name(target.name + ".routing")
    before = _before_path(Path(build_dir), d.name)
    try:
        _check_writable(pcb, target)
        if target.read_bytes() != raw:
            raise NotWritten(f"{pcb.name} changed while the router ran; nothing written")
        before.write_text(text, encoding="utf-8")
        fresh.write_text(routed, encoding="utf-8")
        os.chmod(fresh, stat.S_IMODE(target.stat().st_mode))
        fresh.replace(target)
    except OSError as exc:
        fresh.unlink(missing_ok=True)
        raise NotWritten(f"{pcb.name} not written ({exc}); the board is as it was") from None
    except NotWritten:
        fresh.unlink(missing_ok=True)
        raise
    return {
        **summary,
        "segments": len(segments),
        "vias": len(vias),
        "notes": notes + removed,
        "board": str(pcb),
        "before": str(before),
    }
