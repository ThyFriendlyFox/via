#!/usr/bin/env python3
"""boardrules — a board held to a rule pack from a standard.

A fab's rule set holds what a fab can make. A standard asks more of a board as its voltages and currents
rise: the gap between 2 conductors grows with the voltage between them, and a track's width and a via's
count with the current they carry. A project names its pack in `board-rules.json` beside its board; the
voltage of each net and the current on it come from the project's `ratings.json`, where `workcenter
ratings` reads them too. Each number of a pack names its document, clause, table and page
(`rules/board/README.md`).

KiCad's DRC measures the gaps: `clearance_rules` writes 1 rule for each pair of nets with a voltage
between them and each copper layer, and `clearance_findings` reads back the violations of those rules
alone. Widths and vias are judged here, from the board file. `tools/workcenter` runs kicad-cli.
Standard library only.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import kicadgen
import ratings
from ratings import Refusal

PACKS = Path(__file__).resolve().parent.parent / "rules" / "board"
PROJECT_FILE = "board-rules.json"
DEFAULT_CU_UM = 35.0  # KiCad's own copper on a board whose file holds no stackup
EPS = 1e-9
PAGE_RE = re.compile(r"\bpages? \d+")

# ---------------------------------------------------------------- the pack


@dataclass
class Pack:
    name: str
    document: dict[str, str]
    voltage: dict
    spacing: list[dict]
    current: dict

    def cite(self, *where: str) -> str:
        """A finding's source: the document's number and the places in it."""
        return f"{self.document['number']}: " + "; ".join(w for w in where if w)


def _where(at: str, value: object) -> str:
    text = ratings._text(f"{at}: where", value)
    if not PAGE_RE.search(text):
        raise Refusal(f"{at}: where: name the page, as `table 13-7, page 130`")
    return text


def _num(at: str, value: object, least: float = 0) -> float:
    return ratings._number(at, value, least)


def read_pack(path: Path) -> Pack:
    """A board rule pack. Every number stands with a `where` that names its page; the document has its
    URL, SHA256 and the dates it was read."""
    name = path.name
    data = ratings._keys(name, ratings._json(path), ("pack", "document", "voltage", "spacing", "current"))
    document = ratings._keys(f"{name}: document", data["document"], ratings.DOCUMENT_KEYS)
    for key in ratings.DOCUMENT_KEYS:
        ratings._text(f"{name}: document: {key}", document[key])
    ratings._source(f"{name}: document", document)
    voltage = ratings._keys(f"{name}: voltage", data["voltage"], ("where", "most", "most_where"))
    _where(f"{name}: voltage", voltage["where"])
    _num(f"{name}: voltage: most", voltage["most"])
    _where(f"{name}: voltage: most", voltage["most_where"])
    if not isinstance(data["spacing"], list) or not data["spacing"]:
        raise Refusal(f"{name}: spacing: a list of rows is asked")
    for i, row in enumerate(data["spacing"], start=1):
        at = f"{name}: spacing {i}"
        ratings._keys(at, row, ("layers", "copper_um", "steps", "where"), ("above",))
        _where(at, row["where"])
        if row["layers"] not in ("outer", "inner"):
            raise Refusal(f"{at}: layers is `outer` or `inner`")
        if not isinstance(row["copper_um"], list) or len(row["copper_um"]) != 2:
            raise Refusal(f"{at}: copper_um: [over, up to] is asked, the second null for no end")
        low, high = row["copper_um"]
        _num(f"{at}: copper_um", low)
        if high is not None and _num(f"{at}: copper_um", high) <= low:
            raise Refusal(f"{at}: copper_um: the second number is not above the first")
        if "above" in row:
            _where(f"{at}: above", row["above"])
        last = 0.0
        for j, step in enumerate(row["steps"] if isinstance(row["steps"], list) else [None], start=1):
            sat = f"{at}: step {j}"
            ratings._keys(sat, step, ("volts",), ("um", "um_per_volt", "plus_um", "at_least_um"))
            volts = _num(f"{sat}: volts", step["volts"])
            if volts <= last:
                raise Refusal(f"{sat}: volts: the steps rise")
            last = volts
            if ("um" in step) == ("um_per_volt" in step):
                raise Refusal(f"{sat}: `um`, or `um_per_volt` with `plus_um` and `at_least_um`, is asked")
            for key in ("um", "um_per_volt", "plus_um", "at_least_um"):
                if key in step:
                    _num(f"{sat}: {key}", step[key])
    current = data["current"]
    keys = ("rise_c", "rise_where", "model", "valid", "outer_share", "outer_where", "thin_board", "copper")
    ratings._keys(f"{name}: current", current, (*keys, "tolerance", "via_where"), ("via_wall",))
    _where(f"{name}: current: rise", current["rise_where"])
    _where(f"{name}: current: outer", current["outer_where"])
    _where(f"{name}: current: via", current["via_where"])
    model = ratings._keys(
        f"{name}: current: model",
        current["model"],
        ("k0", "k1", "m0", "m1", "c1", "most_amps", "most_rise_c", "where"),
    )
    for key in (
        "model",
        "valid",
        "thin_board",
        "copper",
        "tolerance",
        *(("via_wall",) * ("via_wall" in current)),
    ):
        _where(
            f"{name}: current: {key}", current[key].get("where") if isinstance(current[key], dict) else None
        )
    for key in ("k0", "k1", "m0", "m1", "c1", "most_amps", "most_rise_c"):
        _num(f"{name}: current: model: {key}", model[key])
    return Pack(ratings._text(f"{name}: pack", data["pack"]), document, voltage, data["spacing"], current)


def find_pack(name: str, project_dir: Path) -> tuple[Path, str]:
    """A pack by its name among the workcenter's, or by a path from the project's folder; and the name a
    report gives it."""
    shipped = PACKS / f"{name}.json"
    if "/" not in name and shipped.is_file():
        return shipped, name
    if (project_dir / name).is_file():
        return project_dir / name, f"{name} (the project's own)"
    known = ", ".join(sorted(p.stem for p in PACKS.glob("*.json")))
    raise Refusal(f"{PROJECT_FILE}: pack: `{name}` is no pack; the workcenter holds {known}")


# ---------------------------------------------------------------- the current model of annex D


def amps_for(area_mm2: float, rise_c: float, model: dict) -> float:
    """The current a conductor of this section carries at this rise: I = k0 dT^k1 (c1 A)^(m0 dT^m1)."""
    exponent = model["m0"] * rise_c ** model["m1"]
    return model["k0"] * rise_c ** model["k1"] * (model["c1"] * area_mm2) ** exponent


def area_for(amps: float, rise_c: float, model: dict) -> float:
    """The section, mm2, that carries this current at this rise: the model turned round."""
    exponent = model["m0"] * rise_c ** model["m1"]
    return (amps / (model["k0"] * rise_c ** model["k1"])) ** (1 / exponent) / model["c1"]


@dataclass
class Need:
    mm: float | None  # the least as designed, or None when it is not judged
    where: str = ""  # the places of the pack it comes from
    why: str = ""  # for None: the reason


def _tolerance(pack: Pack, cu_um: float) -> tuple[float, float] | None:
    """Table 7-3: the share of a width or a gap that manufacture takes, and the most it takes, in mm."""
    tol = pack.current["tolerance"]
    for up_to, most in tol["rows"]:
        if cu_um <= up_to + EPS:
            return tol["share"], most / 1000
    return None


def designed_width(made_mm: float, cu_um: float, pack: Pack) -> float | None:
    """The width to draw so that the width made is at least `made_mm`: the made width is the drawn one
    less its share, or less the most, whichever takes less."""
    tol = _tolerance(pack, cu_um)
    if tol is None:
        return None
    share, most = tol
    return min(made_mm / (1 - share), made_mm + most)


def _rise(pack: Pack, board_mm: float) -> tuple[float, list[str]]:
    cur = pack.current
    thin = cur["thin_board"]
    if thin["over_mm"] < board_mm <= thin["up_to_mm"] + EPS:
        return cur["rise_c"] / thin["rise_factor"], [cur["rise_where"], thin["where"]]
    return cur["rise_c"], [cur["rise_where"]]


def track_need(pack: Pack, amps: float, outer: bool, cu_um: float, board_mm: float) -> Need:
    """The least width as designed of a track that carries `amps` on a layer of `cu_um` copper."""
    cur, model = pack.current, pack.current["model"]
    rise, places = _rise(pack, board_mm)
    if outer:
        places.insert(1, cur["outer_where"])
    need = amps / cur["outer_share"] if outer else amps
    where = "; ".join([*places, model["where"], cur["copper"]["where"], cur["tolerance"]["where"]])
    if need > model["most_amps"]:
        return Need(None, why=f"{need:.3g} A in the model is over its {model['most_amps']:g} A (D.2c)")
    made = next((m for d, m in cur["copper"]["rows"] if abs(d - cu_um) < 0.05), None)
    if made is None:
        rows = ", ".join(f"{d:g}" for d, _ in cur["copper"]["rows"])
        return Need(None, why=f"{cu_um:g} um copper is none of {rows} um of {cur['copper']['where']}")
    width = designed_width(area_for(need, rise, model) / (made / 1000), cu_um, pack)
    if width is None:
        return Need(None, why=f"{cu_um:g} um copper is over every row of {cur['tolerance']['where']}")
    return Need(width, where)


def via_amps(pack: Pack, drill_mm: float, board_mm: float) -> float | None:
    """The current 1 via carries: a track of its wall's section (13.6.3f), at the board's rise."""
    wall = pack.current.get("via_wall")
    if wall is None:
        return None
    t = wall["um"] / 1000
    area = math.pi / 4 * (drill_mm**2 - max(drill_mm - 2 * t, 0) ** 2)
    rise, _ = _rise(pack, board_mm)
    return amps_for(area, rise, pack.current["model"])


# ---------------------------------------------------------------- spacing


def between(a: tuple[float, float], b: tuple[float, float]) -> float:
    """The most voltage that can stand between 2 nets of these spans."""
    return max(abs(a[1] - b[0]), abs(b[1] - a[0]))


def spacing_need(pack: Pack, layers: str, cu_um: float, volts: float) -> Need:
    """The least gap as designed between 2 conductors on an `outer` or `inner` layer of `cu_um` copper
    with `volts` between them."""
    if volts > pack.voltage["most"] + EPS:
        return Need(None, why=f"{volts:g} V is over {pack.voltage['most']:g} V: {pack.voltage['most_where']}")
    for row in pack.spacing:
        low, high = row["copper_um"]
        if row["layers"] != layers or not (low < cu_um <= (math.inf if high is None else high) + EPS):
            continue
        for step in row["steps"]:
            if volts <= step["volts"] + EPS:
                if "um" in step:
                    um = step["um"]
                else:
                    um = max(step["um_per_volt"] * volts + step["plus_um"], step["at_least_um"])
                return Need(um / 1000, row["where"])
        return Need(None, why=f"{volts:g} V: {row.get('above') or 'over the last step of ' + row['where']}")
    return Need(None, why=f"no {layers} row of the pack holds {cu_um:g} um copper")


# ---------------------------------------------------------------- the board


@dataclass
class Track:
    net: str
    layer: str
    width: float
    start: tuple[float, float]
    end: tuple[float, float]


@dataclass
class Via:
    net: str
    at: tuple[float, float]
    size: float
    drill: float
    layers: list[str]


@dataclass
class Pad:
    ref: str
    number: str
    net: str
    at: tuple[float, float]
    reach: float  # half the pad's greater side
    layers: list[str]


@dataclass
class Zone:
    net: str
    layer: str
    polygons: list[list[tuple[float, float]]]


@dataclass
class Board:
    thickness: float
    copper: list[str]
    cu_um: dict[str, float]
    stated_stackup: bool
    area_mm2: float | None
    tracks: list[Track] = field(default_factory=list)
    vias: list[Via] = field(default_factory=list)
    pads: list[Pad] = field(default_factory=list)
    zones: list[Zone] = field(default_factory=list)
    nets: set[str] = field(default_factory=set)

    def outer(self, layer: str) -> bool:
        return layer in (self.copper[0], self.copper[-1])


def _xy(node) -> tuple[float, float]:
    a = kicadgen.atoms(node)
    return (float(a[0]), float(a[1]))


def _copper_order(name: str) -> tuple[int, int]:
    if name == "F.Cu":
        return (0, 0)
    if name == "B.Cu":
        return (2, 0)
    return (1, int(re.sub(r"\D", "", name) or 0))


def read_board(text: str) -> Board:
    """The copper of a .kicad_pcb: its layers and their thickness, its outline's area, and the tracks,
    arcs (as chords), vias, pads and filled zones of each net."""
    root = kicadgen.parse(text)
    ids: dict[str, str] = {}
    for node in kicadgen.children(root, "net"):
        a = kicadgen.atoms(node)
        if len(a) >= 2:
            ids[str(a[0])] = str(a[1])

    def net_of(node) -> str:
        found = kicadgen.child(node, "net")
        if found is None:
            return ""
        a = kicadgen.atoms(found)
        quoted = [x for x in a if isinstance(x, kicadgen.Q)]
        return str(quoted[0]) if quoted else ids.get(str(a[0]), "") if a else ""

    layers_node = kicadgen.child(root, "layers")
    copper = sorted(
        (str(ly[1]) for ly in (layers_node or [])[1:] if isinstance(ly, list) and str(ly[1]).endswith(".Cu")),
        key=_copper_order,
    )
    general = kicadgen.child(root, "general")
    thick = kicadgen.child(general, "thickness") if general else None
    thickness = float(kicadgen.atoms(thick)[0]) if thick else 1.6
    cu_um: dict[str, float] = {}
    setup = kicadgen.child(root, "setup")
    stack = kicadgen.child(setup, "stackup") if setup else None
    for ly in kicadgen.children(stack, "layer") if stack else []:
        kind = kicadgen.child(ly, "type")
        t = kicadgen.child(ly, "thickness")
        if kind and str(kicadgen.atoms(kind)[0]) == "copper" and t:
            cu_um[str(ly[1])] = round(float(kicadgen.atoms(t)[0]) * 1000, 3)
    stated = all(name in cu_um for name in copper)
    if not stated:
        cu_um = dict.fromkeys(copper, DEFAULT_CU_UM)
    board = Board(thickness, copper, cu_um, stated, _area(root))

    def span(names: list[str]) -> list[str]:
        """A via's layers: the 2 it names and every layer between them."""
        if any(n in ("*.Cu", "F&B.Cu") for n in names):
            return list(copper)
        on = sorted(copper.index(n) for n in names if n in copper)
        return copper[on[0] : on[-1] + 1] if on else []

    for node in root[1:]:
        if not isinstance(node, list) or not node:
            continue
        head = node[0]
        if head in ("segment", "arc"):
            layer = str(kicadgen.atoms(kicadgen.child(node, "layer"))[0])
            width = float(kicadgen.atoms(kicadgen.child(node, "width"))[0])
            start, end = _xy(kicadgen.child(node, "start")), _xy(kicadgen.child(node, "end"))
            net = net_of(node)
            if head == "arc":  # 2 chords through the middle: the copper the width is judged on
                mid = _xy(kicadgen.child(node, "mid"))
                board.tracks += [Track(net, layer, width, start, mid), Track(net, layer, width, mid, end)]
            else:
                board.tracks.append(Track(net, layer, width, start, end))
        elif head == "via":
            names = [str(x) for x in kicadgen.atoms(kicadgen.child(node, "layers"))]
            board.vias.append(
                Via(
                    net_of(node),
                    _xy(kicadgen.child(node, "at")),
                    float(kicadgen.atoms(kicadgen.child(node, "size"))[0]),
                    float(kicadgen.atoms(kicadgen.child(node, "drill"))[0]),
                    span(names),
                )
            )
        elif head == "footprint":
            fx, fy, *rot = (float(v) for v in kicadgen.atoms(kicadgen.child(node, "at")))
            ref = ""
            for prop in kicadgen.children(node, "property"):
                if str(prop[1]) == "Reference":
                    ref = str(prop[2])
            for pad in kicadgen.children(node, "pad"):
                px, py, *_ = (float(v) for v in kicadgen.atoms(kicadgen.child(pad, "at")))
                r = math.radians(rot[0] if rot else 0.0)
                at = (fx + px * math.cos(r) + py * math.sin(r), fy - px * math.sin(r) + py * math.cos(r))
                size = kicadgen.child(pad, "size")
                reach = max(_xy(size)) / 2 if size else 0.0
                names = [str(x) for x in kicadgen.atoms(kicadgen.child(pad, "layers") or ["layers"])]
                on = list(copper) if "*.Cu" in names else [n for n in names if n in copper]
                board.pads.append(Pad(ref, str(pad[1]), net_of(pad), at, reach, on))
        elif head == "zone":
            net = net_of(node)
            for filled in kicadgen.children(node, "filled_polygon"):
                layer = str(kicadgen.atoms(kicadgen.child(filled, "layer"))[0])
                pts = [_xy(p) for p in kicadgen.children(kicadgen.child(filled, "pts"), "xy")]
                board.zones.append(Zone(net, layer, [pts]))
    board.nets = {t.net for t in board.tracks} | {v.net for v in board.vias} | {p.net for p in board.pads}
    board.nets.discard("")
    return board


def _area(root) -> float | None:
    """The area inside the board's outline: a rectangle's own, or else its bounding box's."""
    points: list[tuple[float, float]] = []
    rects = []
    for node in root[1:]:
        if not isinstance(node, list) or not node or not str(node[0]).startswith("gr_"):
            continue
        layer = kicadgen.child(node, "layer")
        if layer is None or str(kicadgen.atoms(layer)[0]) != "Edge.Cuts":
            continue
        if node[0] == "gr_rect":
            rects.append((_xy(kicadgen.child(node, "start")), _xy(kicadgen.child(node, "end"))))
        for key in ("start", "mid", "end", "center"):
            if kicadgen.child(node, key) is not None:
                points.append(_xy(kicadgen.child(node, key)))
        pts = kicadgen.child(node, "pts")
        points += [_xy(p) for p in kicadgen.children(pts, "xy")] if pts else []
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return round((max(xs) - min(xs)) * (max(ys) - min(ys)), 6)


def netlist(board: Board) -> ratings.Netlist:
    """The board's parts and nets, as ratings.json is held to a netlist: a part is a footprint, a pin
    its pad."""
    parts: dict[str, ratings.Part] = {}
    nets: dict[str, list[ratings.Node]] = {}
    for pad in board.pads:
        if not pad.ref or not pad.net:
            continue
        part = parts.setdefault(pad.ref, ratings.Part(pad.ref, "", "", "", True))
        part.pins[pad.number] = pad.net
        nets.setdefault(pad.net, []).append(ratings.Node(pad.ref, pad.number, "", "passive", False))
    for name in board.nets:
        nets.setdefault(name, [])
    return ratings.Netlist(parts, nets)


def net_amps(project: ratings.Project, net: ratings.Netlist) -> dict[str, float]:
    """The current on each net: the greatest that ratings.json states for a pin on it, or for a part of
    2 pins, whose current runs through both of its nets."""
    out: dict[str, float] = {}
    for key, amps in project.amps.items():
        ref, _, pin = key.partition(".")
        pins = net.parts[ref].pins
        for name in [pins[pin]] if pin else pins.values():
            out[name] = max(out.get(name, 0.0), amps)
    return out


# ---------------------------------------------------------------- findings


@dataclass
class Finding:
    status: str  # fail, not judged
    text: str
    source: str = ""

    @property
    def line(self) -> str:
        return f"{self.status} {self.text}" + (f" [{self.source}]" if self.source else "")


def _p(xy: tuple[float, float]) -> str:
    return f"({xy[0]:g}, {xy[1]:g})"


def _mm(value: float) -> str:
    """A least width or gap, up to the next micrometre: a limit is never printed under itself."""
    return f"{math.ceil(value * 1000 - 1e-6) / 1000:g}"


def _valid(board: Board, pack: Pack) -> str:
    """Why the current model does not hold for this board, or ''."""
    valid = pack.current["valid"]
    if board.thickness <= valid["board_over_mm"]:
        return f"the board is {board.thickness:g} mm thick"
    if board.area_mm2 is None:
        return "the board has no outline on Edge.Cuts"
    if board.area_mm2 <= valid["area_over_mm2"]:
        return f"the board's outline holds {board.area_mm2:g} mm2"
    return ""


def width_findings(board: Board, amps: dict[str, float], pack: Pack) -> list[Finding]:
    """Each track of a net with a current, held to the least width that carries it."""
    out: list[Finding] = []
    nets = sorted({t.net for t in board.tracks if t.net})
    for name in [n for n in nets if n not in amps]:
        out.append(Finding("not judged", f"track width {name}: ratings.json states no current on it"))
    carrying = [n for n in nets if amps.get(n, 0.0) > 0]
    if not carrying:
        return out
    why = _valid(board, pack)
    if why:
        model = pack.current["valid"]
        text = f"track widths of {', '.join(carrying)}: {why}, and the model holds only over that"
        return [*out, Finding("not judged", text, pack.cite(model["where"]))]
    needs: dict[tuple[str, str], Need] = {}
    for track in board.tracks:
        if amps.get(track.net, 0.0) <= 0:
            continue
        key = (track.net, track.layer)
        if key not in needs:
            needs[key] = track_need(
                pack, amps[track.net], board.outer(track.layer), board.cu_um[track.layer], board.thickness
            )
            if needs[key].mm is None:
                out.append(
                    Finding("not judged", f"track width {track.net} on {track.layer}: {needs[key].why}")
                )
        need = needs[key]
        if need.mm is not None and track.width < need.mm - 1e-6:
            text = (
                f"track width {track.net} on {track.layer} from {_p(track.start)} to {_p(track.end)}: "
                f"{track.width:g} mm, limit {_mm(need.mm)} mm for {amps[track.net]:g} A"
            )
            out.append(Finding("fail", text, pack.cite(need.where)))
    return out


def _touch(a: tuple, b: tuple, c: tuple, d: tuple, reach: float) -> bool:
    """Segment ab and segment cd come within `reach` of each other."""
    if kicadgen._segments_cross(a, b, c, d):
        return True
    near = min(kicadgen._seg_dist(a, c, d), kicadgen._seg_dist(b, c, d))
    return min(near, kicadgen._seg_dist(c, a, b), kicadgen._seg_dist(d, a, b)) <= reach + 1e-6


def _pieces(board: Board, net: str, layer: str) -> tuple[list[tuple], dict[int, int]]:
    """The copper of 1 net on 1 layer, each item a shape, and the piece of copper each item lies in."""
    items: list[tuple] = []  # ("seg", a, b, half width) | ("dot", at, reach) | ("zone", polygon)
    for t in board.tracks:
        if t.net == net and t.layer == layer:
            items.append(("seg", t.start, t.end, t.width / 2))
    for p in board.pads:
        if p.net == net and layer in p.layers:
            items.append(("seg", p.at, p.at, p.reach))
    for z in board.zones:
        if z.net == net and z.layer == layer:
            items += [("zone", poly) for poly in z.polygons]
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for a in range(len(items)):
        for b in range(a + 1, len(items)):
            if _meets(items[a], items[b]):
                parent[find(a)] = find(b)
    return items, {i: find(i) for i in range(len(items))}


def _meets(x: tuple, y: tuple) -> bool:
    if x[0] == "zone" and y[0] == "zone":
        return any(kicadgen._inside_polygon(*p, y[1]) for p in x[1][:1])
    if x[0] == "zone" or y[0] == "zone":
        zone, seg = (x, y) if x[0] == "zone" else (y, x)
        return kicadgen._inside_polygon(*seg[1], zone[1]) or kicadgen._inside_polygon(*seg[2], zone[1])
    return _touch(x[1], x[2], y[1], y[2], x[3] + y[3])


def via_findings(board: Board, amps: dict[str, float], pack: Pack) -> list[Finding]:
    """The vias of each net with a current, in groups that join the same pieces of copper: a group
    carries the net's whole current, and holds as many vias as that asks."""
    out: list[Finding] = []
    via_where = pack.current["via_where"]
    for name in sorted({v.net for v in board.vias if amps.get(v.net, 0.0) > 0}):
        vias = [v for v in board.vias if v.net == name]
        if pack.current.get("via_wall") is None:
            text = f"vias of {name}: the pack gives no copper thickness of a via's wall"
            out.append(Finding("not judged", text, pack.cite(via_where)))
            continue
        why = _valid(board, pack)
        if why:
            text = f"vias of {name}: {why}, and the model holds only over that"
            out.append(Finding("not judged", text, pack.cite(pack.current["valid"]["where"])))
            continue
        layers = sorted({ly for v in vias for ly in v.layers}, key=board.copper.index)
        pieces = {ly: _pieces(board, name, ly) for ly in layers}
        groups: dict[frozenset, list[Via]] = {}
        for via in vias:
            joined = set()
            for ly in via.layers:
                items, root = pieces[ly]
                dot = ("seg", via.at, via.at, via.size / 2)
                joined |= {(ly, root[i]) for i, item in enumerate(items) if _meets(dot, item)}
            if len({ly for ly, _ in joined}) >= 2:  # a via that joins copper on 1 layer carries nothing
                groups.setdefault(frozenset(joined), []).append(via)
        for group in groups.values():
            each = min(via_amps(pack, v.drill, board.thickness) for v in group)
            asked = math.ceil(amps[name] / each - 1e-9)
            if len(group) < asked:
                first = group[0]
                rise, places = _rise(pack, board.thickness)
                text = (
                    f"vias {name} between {first.layers[0]} and {first.layers[-1]} at {_p(first.at)}: "
                    f"{len(group)}, limit {asked} for {amps[name]:g} A ({each:.3g} A each at {rise:.3g} C)"
                )
                where = [
                    via_where,
                    pack.current["via_wall"]["where"],
                    *places,
                    pack.current["model"]["where"],
                ]
                out.append(Finding("fail", text, pack.cite(*where)))
    return out


@dataclass
class Rule:
    nets: tuple[str, str]
    layer: str
    mm: float
    volts: float
    source: str


def clearance_rules(
    board: Board, spans: dict[str, tuple[float, float]], pack: Pack
) -> tuple[str, dict[str, Rule], list[Finding]]:
    """KiCad rules for every pair of nets on the board with a voltage between them, on each copper
    layer: the rule file's text, its rules by name, and what is not judged."""
    lines = ["(version 1)"]
    rules: dict[str, Rule] = {}
    missing: list[Finding] = []
    known = sorted(n for n in board.nets if n in spans)
    for name in sorted(n for n in board.nets if n not in spans):
        missing.append(Finding("not judged", f"spacing of {name}: ratings.json states no voltage for it"))
    for i, a in enumerate(known):
        for b in known[i + 1 :]:
            volts = between(spans[a], spans[b])
            if volts <= 0:
                continue
            for layer in board.copper:
                kind = "outer" if board.outer(layer) else "inner"
                need = spacing_need(pack, kind, board.cu_um[layer], volts)
                if need.mm is None:
                    missing.append(Finding("not judged", f"spacing {a} to {b} on {layer}: {need.why}"))
                    continue
                name = f"{pack.name} {len(rules) + 1}"
                rules[name] = Rule((a, b), layer, need.mm, volts, pack.cite(need.where))
                ab, ba = (
                    f"A.NetName == '{a}' && B.NetName == '{b}'",
                    f"A.NetName == '{b}' && B.NetName == '{a}'",
                )
                both = f"({ab}) || ({ba})"
                lines.append(
                    f'(rule "{name}"\n\t(layer "{layer}")\n\t(condition "{both}")\n'
                    f"\t(constraint clearance (min {need.mm:g}mm)))"
                )
    return "\n".join(lines) + "\n", rules, missing


RULE_RE = re.compile(r"\(rule '([^']*)' clearance [\d.]+ mm; actual ([\d.]+) mm\)")


def clearance_findings(report: dict, rules: dict[str, Rule]) -> list[Finding]:
    """The violations of a KiCad report that break a rule of `clearance_rules`, 1 line each."""
    out: list[Finding] = []
    for v in report.get("violations", []):
        found = RULE_RE.search(str(v.get("description", "")))
        if not found or found.group(1) not in rules:
            continue
        rule = rules[found.group(1)]
        pos = next((i["pos"] for i in v.get("items", []) if "pos" in i), None)
        at = f" at {_p((pos['x'], pos['y']))}" if pos else ""
        text = (
            f"clearance {rule.nets[0]} to {rule.nets[1]} on {rule.layer}{at}: {float(found.group(2)):g} mm, "
            f"limit {rule.mm:g} mm at {rule.volts:g} V"
        )
        out.append(Finding("fail", text, rule.source))
    return out


# ---------------------------------------------------------------- the run

NOT_CHECKED = (
    "not checked by any pack here: the gap in Z between layers, to a hole's wall, to the board's edge and "
    "between holes; the current through a pad or a pour, and through a plated pad's barrel as a path "
    "beside a via"
)


def judge(project, out: Path, cli) -> tuple[str, list[Finding], list[str]]:
    """The board held to the pack its board-rules.json names: the pack's name for the report, the
    findings, and the notes. Refuses a file it does not take; raises RuntimeError when kicad-cli did
    not measure the gaps."""
    data = ratings._keys(PROJECT_FILE, ratings._json(project.dir / PROJECT_FILE), ("pack",))
    path, label = find_pack(ratings._text(f"{PROJECT_FILE}: pack", data["pack"]), project.dir)
    pack = read_pack(path)
    board = read_board(project.pcb.read_text(encoding="utf-8"))
    net = netlist(board)
    stated = project.dir / "ratings.json"
    if not stated.is_file():
        raise Refusal(
            f"{PROJECT_FILE}: the voltage of each net and the current on it come from ratings.json, and "
            f"there is none beside the board: `workcenter ratings {project.dir} --init` writes one"
        )
    asked = ratings.read_project(stated, net)
    amps = net_amps(asked, net)
    notes = [f"board rules: {label}, {pack.document['number']} ({pack.document['revision']})", NOT_CHECKED]
    if not board.stated_stackup:
        notes.append(f"the board states no stackup: KiCad's own {DEFAULT_CU_UM:g} um on each copper layer")
    text, rules, findings = clearance_rules(board, asked.nets, pack)
    if rules:
        folder = out / "board-rules"
        folder.mkdir(parents=True, exist_ok=True)
        for f in project.dir.iterdir():
            if f.suffix in (".kicad_pcb", ".kicad_pro"):
                (folder / f.name).write_bytes(f.read_bytes())
        (folder / f"{project.pcb.stem}.kicad_dru").write_text(text, encoding="utf-8")
        report = folder / "drc.json"
        report.unlink(missing_ok=True)
        cmd = [cli.KICAD_CLI, "pcb", "drc", "--output", report, "--format", "json", "--severity-all"]
        proc = cli.run([*cmd, folder / project.pcb.name], cwd=folder)
        if proc.returncode not in (0, 5) or not report.is_file():
            raise RuntimeError(f"kicad-cli exited {proc.returncode} on the pack's gaps: {proc.stderr[-500:]}")
        findings = clearance_findings(cli.load_json(report), rules) + findings
    findings += width_findings(board, amps, pack) + via_findings(board, amps, pack)
    return label, findings, notes


def gate(project, out: Path, strict: bool, cli) -> dict:
    """The DRC gate's part: red on a failure, and with --strict on what was not judged. `summary` goes
    after the gate's own; `failures` and `warnings` are printed 1 line each."""
    try:
        label, findings, notes = judge(project, out, cli)
    except (ValueError, OSError, RuntimeError) as exc:
        return {"red": True, "summary": "board rules: not run", "failures": [str(exc)], "warnings": []}
    fails = [f.line for f in findings if f.status == "fail"]
    unjudged = [f.line for f in findings if f.status != "fail"]
    return {
        "red": bool(fails) or (strict and bool(unjudged)),
        "summary": f"board rules {label}: {len(fails)} fail, {len(unjudged)} not judged",
        "pack": label,
        "failures": fails + (unjudged if strict else []),
        "warnings": [] if strict else unjudged,
        "notes": notes,
    }
