"""Railway geometry: OSM rail graph construction, turn-aware routing and the segment store.

The graph is built from OSM `railway=rail` ways. Chains of degree-2 nodes are collapsed
into edges that keep their full geometry, so the graph only has junction/end nodes.

Routing is an A* over *directed edge states* rather than nodes, so that a transition
between two edges at a junction is only allowed when the turn is gentle (a train cannot
reverse through a switch). Stations are snapped onto the nearest points of nearby edges
(several candidates per station) and the best candidate pair wins.
"""

from __future__ import annotations

import heapq
import json
import math
import pickle
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from pathlib import Path

import numpy as np

from app.geo.polyline import (
    LatLon,
    angle_diff,
    bearing_deg,
    cumulative,
    haversine_m,
    interpolate_along,
    round_path,
    simplify,
)

GRAPH_VERSION = 1
SEGMENTS_VERSION = 1
HEADING_LOOKBACK_M = 30.0
_M_PER_DEG_LAT = 110_540.0
_M_PER_DEG_LON_EQ = 111_320.0
_PROJ_LAT0 = 52.0  # Poland-centred equirectangular projection for the KD-tree


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


@dataclass
class RailGraphData:
    """Compact, picklable graph. Edge i's geometry is pt_lat/pt_lon[edge_ptr[i]:edge_ptr[i+1]]."""

    edge_u: np.ndarray  # int32 key-node index
    edge_v: np.ndarray
    edge_ptr: np.ndarray  # int64 offsets into the point arrays, len = n_edges + 1
    pt_lat: np.ndarray  # float64
    pt_lon: np.ndarray
    version: int = GRAPH_VERSION

    @property
    def n_edges(self) -> int:
        return len(self.edge_u)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump(self.__dict__, f, protocol=pickle.HIGHEST_PROTOCOL)

    @classmethod
    def load(cls, path: Path) -> RailGraphData:
        with path.open("rb") as f:
            d = pickle.load(f)
        if d.get("version") != GRAPH_VERSION:
            raise ValueError(f"{path} has graph version {d.get('version')}, expected {GRAPH_VERSION}")
        return cls(**d)


def build_graph_from_ways(ways: Iterable[tuple[Sequence[int], Sequence[LatLon]]]) -> RailGraphData:
    """Build the contracted graph from (node_ids, coords) pairs, one per OSM way."""
    coords: dict[int, LatLon] = {}
    pairs: set[tuple[int, int]] = set()
    for node_ids, pts in ways:
        if len(node_ids) != len(pts):
            raise ValueError("node id and coordinate lists differ in length")
        for nid, p in zip(node_ids, pts):
            coords[nid] = (p[0], p[1])
        for a, b in pairwise(node_ids):
            if a != b:
                pairs.add((a, b) if a < b else (b, a))

    neighbors: dict[int, list[int]] = defaultdict(list)
    for a, b in pairs:
        neighbors[a].append(b)
        neighbors[b].append(a)
    del pairs

    key_nodes = [n for n, nb in neighbors.items() if len(nb) != 2]
    key_index = {n: i for i, n in enumerate(key_nodes)}

    edge_u: list[int] = []
    edge_v: list[int] = []
    edge_ptr: list[int] = [0]
    pt_lat: list[float] = []
    pt_lon: list[float] = []
    visited: set[tuple[int, int]] = set()

    def walk(start: int, first: int) -> list[int]:
        chain = [start, first]
        prev, cur = start, first
        while cur not in key_index:
            a, b = neighbors[cur]
            nxt = b if a == prev else a
            chain.append(nxt)
            prev, cur = cur, nxt
        return chain

    for u in key_nodes:
        for first in neighbors[u]:
            if (u, first) in visited:
                continue
            chain = walk(u, first)
            v = chain[-1]
            visited.add((u, chain[1]))
            visited.add((v, chain[-2]))
            if u == v and len(chain) <= 3:
                continue  # degenerate self-loop
            edge_u.append(key_index[u])
            edge_v.append(key_index[v])
            for n in chain:
                lat, lon = coords[n]
                pt_lat.append(lat)
                pt_lon.append(lon)
            edge_ptr.append(len(pt_lat))

    return RailGraphData(
        edge_u=np.asarray(edge_u, dtype=np.int32),
        edge_v=np.asarray(edge_v, dtype=np.int32),
        edge_ptr=np.asarray(edge_ptr, dtype=np.int64),
        pt_lat=np.asarray(pt_lat, dtype=np.float64),
        pt_lon=np.asarray(pt_lon, dtype=np.float64),
    )


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def _project(lat: np.ndarray | float, lon: np.ndarray | float):
    k = math.cos(math.radians(_PROJ_LAT0))
    return np.column_stack((np.atleast_1d(lon) * _M_PER_DEG_LON_EQ * k, np.atleast_1d(lat) * _M_PER_DEG_LAT))


@dataclass
class RouteResult:
    path: list[LatLon]
    length_m: float
    straight_m: float
    source: str  # "rail" or "straight"
    reason: str = ""


@dataclass
class _Candidate:
    edge: int
    s: float  # distance along the edge from its u end, in metres
    snap_m: float


SNAP_SAMPLE_M = 40.0  # spacing of the points indexed for snapping (OSM vertices can be km apart)


@dataclass
class RailRouter:
    data: RailGraphData
    snap_radius_m: float = 400.0
    max_turn_deg: float = 50.0
    snap_weight: float = 1.0
    max_ratio: float = 1.8
    max_expansions: int = 2_000_000
    _edge_len: np.ndarray = field(init=False, repr=False)
    _head_out_u: np.ndarray = field(init=False, repr=False)
    _head_in_v: np.ndarray = field(init=False, repr=False)
    _adj: dict[int, list[int]] = field(init=False, repr=False)
    _cum_cache: dict[int, list[float]] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        from scipy.spatial import cKDTree

        d = self.data
        n = d.n_edges
        self._edge_len = np.zeros(n)
        self._head_out_u = np.zeros(n)
        self._head_in_v = np.zeros(n)
        self._adj = defaultdict(list)
        self._cum_cache = {}
        s_edge: list[int] = []
        s_dist: list[float] = []
        s_lat: list[float] = []
        s_lon: list[float] = []
        for e in range(n):
            pts = self.geom(e)
            cum = cumulative(pts)
            self._edge_len[e] = cum[-1]
            self._head_out_u[e] = _heading_from_start(pts, cum)
            self._head_in_v[e] = _heading_into_end(pts, cum)
            self._adj[int(d.edge_u[e])].append(e)
            if d.edge_v[e] != d.edge_u[e]:
                self._adj[int(d.edge_v[e])].append(e)
            # Snap samples: every vertex plus points every SNAP_SAMPLE_M along long pieces.
            for i in range(len(pts)):
                s_edge.append(e)
                s_dist.append(cum[i])
                s_lat.append(pts[i][0])
                s_lon.append(pts[i][1])
                if i + 1 < len(pts):
                    piece = cum[i + 1] - cum[i]
                    k = int(piece // SNAP_SAMPLE_M)
                    for j in range(1, k + 1):
                        t = j * SNAP_SAMPLE_M / piece
                        if t >= 1.0:
                            break
                        s_edge.append(e)
                        s_dist.append(cum[i] + t * piece)
                        s_lat.append(pts[i][0] + (pts[i + 1][0] - pts[i][0]) * t)
                        s_lon.append(pts[i][1] + (pts[i + 1][1] - pts[i][1]) * t)
        self._s_edge = np.asarray(s_edge, dtype=np.int32)
        self._s_dist = np.asarray(s_dist)
        self._s_lat = np.asarray(s_lat)
        self._s_lon = np.asarray(s_lon)
        self._tree = cKDTree(_project(self._s_lat, self._s_lon))

    # -- geometry helpers ---------------------------------------------------
    def geom(self, e: int) -> list[LatLon]:
        s, t = int(self.data.edge_ptr[e]), int(self.data.edge_ptr[e + 1])
        return list(zip(self.data.pt_lat[s:t].tolist(), self.data.pt_lon[s:t].tolist()))

    def cum(self, e: int) -> list[float]:
        c = self._cum_cache.get(e)
        if c is None:
            c = cumulative(self.geom(e))
            if len(self._cum_cache) > 50_000:
                self._cum_cache.clear()
            self._cum_cache[e] = c
        return c

    def node_latlon(self, key_node: int, via_edge: int) -> LatLon:
        d = self.data
        if int(d.edge_u[via_edge]) == key_node:
            i = int(d.edge_ptr[via_edge])
        else:
            i = int(d.edge_ptr[via_edge + 1]) - 1
        return float(d.pt_lat[i]), float(d.pt_lon[i])

    def point_at(self, e: int, s: float) -> LatLon:
        lat, lon, _ = interpolate_along(self.geom(e), self.cum(e), s)
        return lat, lon

    def cut(self, e: int, s0: float, s1: float) -> list[LatLon]:
        """Track geometry of edge e from distance s0 to s1 (s1 < s0 walks backwards)."""
        pts, cum = self.geom(e), self.cum(e)
        inner = [pts[i] for i in range(len(pts)) if min(s0, s1) < cum[i] < max(s0, s1)]
        if s1 < s0:
            inner.reverse()
        return [self.point_at(e, s0), *inner, self.point_at(e, s1)]

    def candidates(self, lat: float, lon: float) -> list[_Candidate]:
        """Closest track point of every edge within the snap radius."""
        idxs = self._tree.query_ball_point(_project(lat, lon)[0], r=self.snap_radius_m)
        best: dict[int, _Candidate] = {}
        for gi in idxs:
            e = int(self._s_edge[gi])
            dist = haversine_m(lat, lon, float(self._s_lat[gi]), float(self._s_lon[gi]))
            cur = best.get(e)
            if cur is None or dist < cur.snap_m:
                best[e] = _Candidate(e, float(self._s_dist[gi]), dist)
        return sorted(best.values(), key=lambda c: c.snap_m)[:24]

    # -- search ---------------------------------------------------------------
    def _arrive(self, e: int, d: int) -> tuple[int, float]:
        """Key node reached and heading on arrival when traversing edge e in direction d (0 = u->v)."""
        if d == 0:
            return int(self.data.edge_v[e]), float(self._head_in_v[e])
        return int(self.data.edge_u[e]), (float(self._head_out_u[e]) + 180.0) % 360.0

    def _leave_heading(self, e: int, from_node: int) -> list[tuple[int, float]]:
        out = []
        if int(self.data.edge_u[e]) == from_node:
            out.append((0, float(self._head_out_u[e])))
        if int(self.data.edge_v[e]) == from_node:
            out.append((1, (float(self._head_in_v[e]) + 180.0) % 360.0))
        return out

    def route(self, a: LatLon, b: LatLon) -> RouteResult:
        straight = haversine_m(a[0], a[1], b[0], b[1])

        def fallback(reason: str) -> RouteResult:
            return RouteResult([a, b], straight, straight, "straight", reason)

        ca, cb = self.candidates(*a), self.candidates(*b)
        if not ca:
            return fallback("no track near origin")
        if not cb:
            return fallback("no track near destination")

        best_cost = math.inf
        best_goal: tuple | None = None
        W = self.snap_weight

        # Both stations on the same edge: travel along it directly.
        for sa in ca:
            for sb in cb:
                if sa.edge == sb.edge:
                    cost = abs(sb.s - sa.s) + W * (sa.snap_m + sb.snap_m)
                    if cost < best_cost:
                        best_cost, best_goal = cost, ("direct", sa, sb)

        # Target edges can be entered from either end: from u heading towards v, or from v towards u.
        targets: dict[int, list[tuple[_Candidate, int, float]]] = defaultdict(list)
        for sb in cb:
            u, v = int(self.data.edge_u[sb.edge]), int(self.data.edge_v[sb.edge])
            targets[u].append((sb, 0, float(self._head_out_u[sb.edge])))
            targets[v].append((sb, 1, (float(self._head_in_v[sb.edge]) + 180.0) % 360.0))

        slack = self.snap_radius_m

        def h(node_lat: float, node_lon: float) -> float:
            return max(0.0, haversine_m(node_lat, node_lon, b[0], b[1]) - slack)

        g: dict[tuple[int, int], float] = {}
        parent: dict[tuple[int, int], tuple] = {}
        heap: list[tuple[float, float, int, int]] = []
        for sa in ca:
            L = float(self._edge_len[sa.edge])
            for d, part in ((0, L - sa.s), (1, sa.s)):
                cost = W * sa.snap_m + part
                st = (sa.edge, d)
                if cost < g.get(st, math.inf):
                    g[st] = cost
                    parent[st] = ("src", sa)
                    node, _ = self._arrive(sa.edge, d)
                    nlat, nlon = self.node_latlon(node, sa.edge)
                    heapq.heappush(heap, (cost + h(nlat, nlon), cost, sa.edge, d))

        cost_cap = 3.0 * straight + 10_000.0
        expansions = 0
        while heap:
            f, cost, e, d = heapq.heappop(heap)
            if f >= best_cost or cost > cost_cap:
                break
            if cost > g.get((e, d), math.inf):
                continue
            expansions += 1
            if expansions > self.max_expansions:
                break
            node, arr_head = self._arrive(e, d)

            for sb, d_enter, leave_head in targets.get(node, ()):
                if sb.edge == e or angle_diff(arr_head, leave_head) > self.max_turn_deg:
                    continue
                part = sb.s if d_enter == 0 else float(self._edge_len[sb.edge]) - sb.s
                total = cost + part + W * sb.snap_m
                if total < best_cost:
                    best_cost, best_goal = total, ("via", (e, d), sb, d_enter)

            for e2 in self._adj.get(node, ()):
                for d2, leave_head in self._leave_heading(e2, node):
                    if e2 == e and d2 != d:
                        continue  # straight back along the same edge
                    if angle_diff(arr_head, leave_head) > self.max_turn_deg:
                        continue
                    nc = cost + float(self._edge_len[e2])
                    st = (e2, d2)
                    if nc < g.get(st, math.inf):
                        g[st] = nc
                        parent[st] = ("edge", (e, d))
                        n2, _ = self._arrive(e2, d2)
                        nlat, nlon = self.node_latlon(n2, e2)
                        heapq.heappush(heap, (nc + h(nlat, nlon), nc, e2, d2))

        if best_goal is None:
            return fallback("no rail path")

        path = self._reconstruct(best_goal, parent)
        length = cumulative(path)[-1]
        if straight > 1000 and length > self.max_ratio * straight:
            return fallback(f"rail path {length / straight:.2f}x longer than straight line")
        if straight <= 1000 and length > straight + 1500:
            return fallback("short hop with long detour")
        return RouteResult(path, length, straight, "rail")

    def _reconstruct(self, goal: tuple, parent: dict) -> list[LatLon]:
        if goal[0] == "direct":
            _, sa, sb = goal
            return self.cut(sa.edge, sa.s, sb.s)

        _, last_state, sb, d_enter = goal
        states = []
        st = last_state
        while True:
            states.append(st)
            p = parent[st]
            if p[0] == "src":
                src = p[1]
                break
            st = p[1]
        states.reverse()

        pieces: list[list[LatLon]] = []
        e0, d0 = states[0]
        pieces.append(self.cut(e0, src.s, float(self._edge_len[e0]) if d0 == 0 else 0.0))
        for e, d in states[1:]:
            pts = self.geom(e)
            pieces.append(pts if d == 0 else pts[::-1])
        end_len = float(self._edge_len[sb.edge])
        pieces.append(self.cut(sb.edge, 0.0 if d_enter == 0 else end_len, sb.s))

        out: list[LatLon] = []
        for piece in pieces:
            for p in piece:
                if not out or out[-1] != p:
                    out.append(p)
        return out


def _heading_from_start(pts: list[LatLon], cum: list[float]) -> float:
    j = next((i for i, c in enumerate(cum) if c >= HEADING_LOOKBACK_M), len(pts) - 1)
    j = max(j, 1)
    return bearing_deg(pts[0][0], pts[0][1], pts[j][0], pts[j][1])


def _heading_into_end(pts: list[LatLon], cum: list[float]) -> float:
    total = cum[-1]
    j = next((i for i in range(len(pts) - 1, -1, -1) if total - cum[i] >= HEADING_LOOKBACK_M), 0)
    j = min(j, len(pts) - 2)
    return bearing_deg(pts[j][0], pts[j][1], pts[-1][0], pts[-1][1])


# ---------------------------------------------------------------------------
# Segment store (runtime)
# ---------------------------------------------------------------------------


def segment_key(a: int, b: int) -> str:
    return f"{a}-{b}"


def parse_segment_key(key: str) -> tuple[int, int]:
    a, b = key.split("-", 1)
    return int(a), int(b)


@dataclass
class Segment:
    path: list[LatLon]
    cum: list[float]
    source: str

    @property
    def length_m(self) -> float:
        return self.cum[-1] if self.cum else 0.0


class SegmentStore:
    """Routed station-to-station polylines, stored once per unordered pair (min id -> max id)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._raw: dict[str, dict] = {}
        self._cache: dict[str, Segment] = {}
        if path is not None and path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("version") == SEGMENTS_VERSION:
                self._raw = data.get("segments", {})

    def __len__(self) -> int:
        return len(self._raw)

    def clear(self) -> None:
        self._raw.clear()
        self._cache.clear()

    def drop_fallbacks(self) -> int:
        """Forget straight-line fallbacks so they get routed again. Returns how many were dropped."""
        bad = [k for k, v in self._raw.items() if v.get("source") != "rail"]
        for k in bad:
            del self._raw[k]
        self._cache.clear()
        return len(bad)

    def drop_stale(self, coords: dict[int, LatLon], tolerance_m: float = 600.0) -> int:
        """Forget segments whose ends no longer match their stations (e.g. after a coordinate override)."""
        stale = []
        for key, raw in self._raw.items():
            a, b = parse_segment_key(key)
            if a not in coords or b not in coords:
                continue
            (s_lat, s_lon), (e_lat, e_lon) = raw["path"][0], raw["path"][-1]
            if (
                haversine_m(s_lat, s_lon, *coords[a]) > tolerance_m
                or haversine_m(e_lat, e_lon, *coords[b]) > tolerance_m
            ):
                stale.append(key)
        for key in stale:
            del self._raw[key]
        self._cache.clear()
        return len(stale)

    def has(self, a: int, b: int) -> bool:
        lo, hi = sorted((a, b))
        return segment_key(lo, hi) in self._raw

    def get(self, a: int, b: int) -> Segment | None:
        key = segment_key(a, b)
        seg = self._cache.get(key)
        if seg is not None:
            return seg
        lo, hi = sorted((a, b))
        raw = self._raw.get(segment_key(lo, hi))
        if raw is None:
            return None
        path = [(p[0], p[1]) for p in raw["path"]]
        if a > b:
            path.reverse()
        seg = Segment(path, cumulative(path), raw.get("source", "rail"))
        self._cache[key] = seg
        return seg

    def get_or_straight(self, a: int, b: int, pa: LatLon, pb: LatLon) -> Segment:
        seg = self.get(a, b)
        if seg is not None:
            return seg
        path = [pa, pb]
        return Segment(path, cumulative(path), "straight")

    def put(self, a: int, b: int, result: RouteResult, tolerance_m: float = 5.0) -> None:
        lo, hi = sorted((a, b))
        path = result.path if a == lo else result.path[::-1]
        path = simplify(path, tolerance_m)
        self._raw[segment_key(lo, hi)] = {
            "path": round_path(path),
            "len": round(result.length_m, 1),
            "source": result.source,
            **({"reason": result.reason} if result.reason else {}),
        }
        self._cache.pop(segment_key(a, b), None)
        self._cache.pop(segment_key(b, a), None)

    def save(self, path: Path | None = None) -> None:
        target = path or self.path
        if target is None:
            raise ValueError("no path to save segments to")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"version": SEGMENTS_VERSION, "segments": self._raw}, separators=(",", ":")),
            encoding="utf-8",
        )
        tmp.replace(target)


def located_pairs(sequences: Iterable[Sequence[int]], has_coords) -> set[tuple[int, int]]:
    """Consecutive station pairs along each route, skipping stations without coordinates."""
    pairs: set[tuple[int, int]] = set()
    for seq in sequences:
        located = [s for s in seq if has_coords(s)]
        for a, b in pairwise(located):
            if a != b:
                pairs.add((a, b))
    return pairs


def route_missing_pairs(
    router: RailRouter,
    store: SegmentStore,
    pairs: Iterable[tuple[int, int]],
    coords: dict[int, LatLon],
    on_issue=None,
) -> int:
    """Route every pair not yet in the store. Returns the number of pairs added."""
    added = 0
    for a, b in pairs:
        if a == b or store.has(a, b) or a not in coords or b not in coords:
            continue
        result = router.route(coords[a], coords[b])
        store.put(a, b, result)
        added += 1
        if result.source != "rail" and on_issue is not None:
            on_issue(a, b, result)
    return added
