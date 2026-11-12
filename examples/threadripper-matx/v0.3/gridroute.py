"""A small router for one layer at a time: A* on a square grid, for the stretches of a bus between
its constructive ends.

The grid's pitch is 0.25 mm. A cell is free for a net when no copper of another net (a pad, a via, a
track already drawn) comes within `CLEAR` of its centre, CLEAR being the copper's own half size plus
the clearance, the track's half width, and the farthest a step's middle strays from its ends. Steps go
to the 8 neighbours; a diagonal step is refused when either cell it cuts past is taken, so 2 diagonals
never cross and none passes a corner closer than the clearance. Each routed track takes its cells
and, for later nets, the cells round them.
"""

from __future__ import annotations

import heapq
import math

G = 0.25  # grid pitch, mm
W = 0.1  # track width
C = 0.1  # clearance
STRAY = 0.18  # how far a step's middle can lie from both its ends (half a diagonal step)


class Grid:
    def __init__(self, box: tuple[float, float, float, float]):
        self.x0, self.y0, x1, y1 = box
        self.nx = int((x1 - self.x0) / G) + 1
        self.ny = int((y1 - self.y0) / G) + 1
        self.owner = bytearray(self.nx * self.ny)  # 0 free, 1 blocked for all
        self.net = [None] * (self.nx * self.ny)  # the net whose own copper a cell is in (free for that net)

    def cell(self, x: float, y: float) -> tuple[int, int]:
        return round((x - self.x0) / G), round((y - self.y0) / G)

    def xy(self, i: int, j: int) -> tuple[float, float]:
        return round(self.x0 + i * G, 4), round(self.y0 + j * G, 4)

    def inside(self, i: int, j: int) -> bool:
        return 0 <= i < self.nx and 0 <= j < self.ny

    def _mark_disc(self, x: float, y: float, r: float, net: str | None) -> None:
        """Block every cell whose centre is within r of (x, y) for every net but `net`."""
        i0, j0 = self.cell(x - r, y - r)
        i1, j1 = self.cell(x + r, y + r)
        for i in range(max(i0, 0), min(i1, self.nx - 1) + 1):
            for j in range(max(j0, 0), min(j1, self.ny - 1) + 1):
                cx, cy = self.x0 + i * G, self.y0 + j * G
                if (cx - x) ** 2 + (cy - y) ** 2 <= r * r:
                    self._take(i, j, net)

    def _take(self, i: int, j: int, net: str | None) -> None:
        k = j * self.nx + i
        if self.owner[k] == 1:
            return
        if net is None or (self.net[k] is not None and self.net[k] != net):
            self.owner[k] = 1
            self.net[k] = None
        else:
            self.net[k] = net

    def block_rect(self, x1: float, y1: float, x2: float, y2: float, net: str | None) -> None:
        """A pad's box, grown by the clearance a track keeps from it."""
        g = C + W / 2 + STRAY
        i0, j0 = self.cell(x1 - g, y1 - g)
        i1, j1 = self.cell(x2 + g, y2 + g)
        for i in range(max(i0, 0), min(i1, self.nx - 1) + 1):
            for j in range(max(j0, 0), min(j1, self.ny - 1) + 1):
                cx, cy = self.x0 + i * G, self.y0 + j * G
                dx = max(x1 - cx, 0.0, cx - x2)
                dy = max(y1 - cy, 0.0, cy - y2)
                if dx * dx + dy * dy <= g * g:
                    self._take(i, j, net)

    def block_disc(self, x: float, y: float, radius: float, net: str | None) -> None:
        """A via or a round pad of `radius`."""
        self._mark_disc(x, y, radius + C + W / 2 + STRAY, net)

    def block_segment(self, a: tuple[float, float], b: tuple[float, float], width: float, net: str | None) -> None:
        r = width / 2 + C + W / 2 + STRAY
        n = max(1, int(math.hypot(b[0] - a[0], b[1] - a[1]) / (G / 2)))
        for k in range(n + 1):
            t = k / n
            self._mark_disc(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, r, net)

    def free(self, i: int, j: int, net: str) -> bool:
        k = j * self.nx + i
        return self.owner[k] == 0 and (self.net[k] is None or self.net[k] == net)

    def route(self, net: str, a: tuple[float, float], b: tuple[float, float], limit: int = 400_000) -> list[tuple[float, float]] | None:
        """The shortest path of 0, 45 and 90 degree steps from a to b for `net`, with a small cost on
        each bend; None when there is none."""
        s, t = self.cell(*a), self.cell(*b)
        if not (self.inside(*s) and self.inside(*t)):
            return None
        steps = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
                 (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]

        def h(i: int, j: int) -> float:
            dx, dy = abs(i - t[0]), abs(j - t[1])
            return max(dx, dy) + 0.4142 * min(dx, dy)

        start = (s[0], s[1], -1)
        best = {start: 0.0}
        came: dict = {}
        heap = [(h(*s), 0.0, start)]
        seen = 0
        while heap:
            _f, g, node = heapq.heappop(heap)
            i, j, d = node
            if (i, j) == t:
                path = [(i, j)]
                while node in came:
                    node = came[node]
                    path.append((node[0], node[1]))
                path.reverse()
                return [self.xy(*p) for p in _corners(path)]
            if g > best.get(node, 1e18):
                continue
            seen += 1
            if seen > limit:
                return None
            for k, (di, dj, cost) in enumerate(steps):
                ni, nj = i + di, j + dj
                if not self.inside(ni, nj) or not ((ni, nj) == t or self.free(ni, nj, net)):
                    continue
                if di and dj and not (self.free(i + di, j, net) and self.free(i, j + dj, net)):
                    continue
                ng = g + cost + (0.6 if d not in (-1, k) else 0.0)
                nxt = (ni, nj, k)
                if ng < best.get(nxt, 1e18):
                    best[nxt] = ng
                    came[nxt] = node
                    heapq.heappush(heap, (ng + h(ni, nj), ng, nxt))
        return None

    def claim(self, net: str, pts: list[tuple[float, float]]) -> None:
        """A routed track: its copper is the net's own, and the cells round it are taken for others."""
        for a, b in zip(pts, pts[1:], strict=False):
            self.block_segment(a, b, W, net)


def _corners(path: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The cells where the path turns, with its ends."""
    if len(path) < 3:
        return path
    out = [path[0]]
    for p, q, r in zip(path, path[1:], path[2:], strict=False):
        if (q[0] - p[0], q[1] - p[1]) != (r[0] - q[0], r[1] - q[1]):
            out.append(q)
    out.append(path[-1])
    return out


def via_ok(grids: list[Grid], net: str, i: int, j: int) -> bool:
    """A via (0.4 mm) fits at a cell when the cell and its 8 neighbours are free for the net on every
    layer it joins: its copper is 0.15 mm wider than a track's half, under a cell's pitch."""
    return all(
        g.inside(i + di, j + dj) and g.free(i + di, j + dj, net) for g in grids for di in (-1, 0, 1) for dj in (-1, 0, 1)
    )


def route2(grids: list[Grid], net: str, a, b, a_layers, b_layers, via_cost: float = 12.0, limit: int = 800_000,
           via_grids: list[Grid] | None = None):
    """The shortest path on 2 layers of the same grid geometry, changing layer through a via where
    both layers are free: [(layer index, [points])...] and the via points, or None. `a_layers` and
    `b_layers` are the layers each end may be met on (a surface pad 1, a through pad both). A via also
    passes the layers between: `via_grids` adds their copper to its check."""
    held = grids + (via_grids or [])
    g0 = grids[0]
    s, t = g0.cell(*a), g0.cell(*b)
    if not (g0.inside(*s) and g0.inside(*t)):
        return None
    steps = [(1, 0, 1.0), (-1, 0, 1.0), (0, 1, 1.0), (0, -1, 1.0),
             (1, 1, 1.4142), (1, -1, 1.4142), (-1, 1, 1.4142), (-1, -1, 1.4142)]  # fmt: skip

    def h(i: int, j: int) -> float:
        dx, dy = abs(i - t[0]), abs(j - t[1])
        return max(dx, dy) + 0.4142 * min(dx, dy)

    best: dict = {}
    came: dict = {}
    heap = []
    for lay in a_layers:
        node = (s[0], s[1], lay, -1)
        best[node] = 0.0
        heapq.heappush(heap, (h(*s), 0.0, node))
    seen = 0
    while heap:
        _f, gc, node = heapq.heappop(heap)
        i, j, lay, d = node
        if (i, j) == t and lay in b_layers:
            path = [(i, j, lay)]
            while node in came:
                node = came[node]
                path.append((node[0], node[1], node[2]))
            path.reverse()
            return _split(g0, path)
        if gc > best.get(node, 1e18):
            continue
        seen += 1
        if seen > limit:
            return None
        g = grids[lay]
        for k, (di, dj, cost) in enumerate(steps):
            ni, nj = i + di, j + dj
            if not g.inside(ni, nj) or not ((ni, nj) == t or g.free(ni, nj, net)):
                continue
            if di and dj and not (g.free(i + di, j, net) and g.free(i, j + dj, net)):
                continue
            ng = gc + cost + (0.6 if d not in (-1, k) else 0.0)
            nxt = (ni, nj, lay, k)
            if ng < best.get(nxt, 1e18):
                best[nxt] = ng
                came[nxt] = node
                heapq.heappush(heap, (ng + h(ni, nj), ng, nxt))
        other = 1 - lay
        if (i, j) not in (s, t) and via_ok(held, net, i, j):
            ng = gc + via_cost
            nxt = (i, j, other, -1)
            if ng < best.get(nxt, 1e18):
                best[nxt] = ng
                came[nxt] = node
                heapq.heappush(heap, (ng + h(i, j), ng, nxt))
    return None


def _split(g: Grid, path: list[tuple[int, int, int]]):
    """A path of cells with layers into each layer's runs (corners only) and the vias between them."""
    runs, vias, cur = [], [], [path[0]]
    for p in path[1:]:
        if p[2] != cur[-1][2]:
            runs.append((cur[-1][2], cur))
            vias.append(g.xy(p[0], p[1]))
            cur = [p]
        else:
            cur.append(p)
    runs.append((cur[-1][2], cur))
    out = []
    for lay, cells in runs:
        pts = [g.xy(i, j) for i, j in _corners([(c[0], c[1]) for c in cells])]
        if len(pts) >= 2:
            out.append((lay, pts))
    return out, vias
