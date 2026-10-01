"""Small geodesy helpers shared by the routing scripts and the live estimator.

Paths are lists of (lat, lon) pairs. `frontend/src/lib/interpolate.ts` mirrors
`cumulative`, `interpolate_along` and `bearing_deg`; keep the two in sync
(tests/fixtures/interp_cases.json is checked by both test suites).
"""

import math
from bisect import bisect_right
from collections.abc import Sequence
from itertools import pairwise

EARTH_RADIUS_M = 6_371_008.8

LatLon = tuple[float, float]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial compass bearing from point 1 to point 2, 0 = north, clockwise."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def angle_diff(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings, in degrees (0..180)."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


def cumulative(path: Sequence[LatLon]) -> list[float]:
    out = [0.0]
    for (a_lat, a_lon), (b_lat, b_lon) in pairwise(path):
        out.append(out[-1] + haversine_m(a_lat, a_lon, b_lat, b_lon))
    return out


def interpolate_along(path: Sequence[LatLon], cum: Sequence[float], dist: float) -> tuple[float, float, float]:
    """Point at `dist` metres along `path` plus the local bearing. `dist` is clamped to the path."""
    if not path:
        raise ValueError("empty path")
    if len(path) == 1:
        return path[0][0], path[0][1], 0.0
    total = cum[-1]
    dist = max(0.0, min(dist, total))
    i = min(max(bisect_right(cum, dist) - 1, 0), len(path) - 2)
    # Skip zero-length pieces so the bearing is always defined.
    while i < len(path) - 2 and cum[i + 1] - cum[i] <= 0:
        i += 1
    seg = cum[i + 1] - cum[i]
    t = 0.0 if seg <= 0 else (dist - cum[i]) / seg
    (a_lat, a_lon), (b_lat, b_lon) = path[i], path[i + 1]
    lat = a_lat + (b_lat - a_lat) * t
    lon = a_lon + (b_lon - a_lon) * t
    return lat, lon, bearing_deg(a_lat, a_lon, b_lat, b_lon)


def _to_xy(lat: float, lon: float, lat0: float) -> tuple[float, float]:
    k = math.cos(math.radians(lat0))
    return lon * 111_320.0 * k, lat * 110_540.0


def simplify(path: Sequence[LatLon], tolerance_m: float) -> list[LatLon]:
    """Douglas–Peucker simplification in a local equirectangular projection. Keeps both endpoints."""
    n = len(path)
    if n <= 2:
        return list(path)
    lat0 = sum(p[0] for p in path) / n
    xy = [_to_xy(lat, lon, lat0) for lat, lon in path]
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        s, e = stack.pop()
        if e <= s + 1:
            continue
        (x1, y1), (x2, y2) = xy[s], xy[e]
        dx, dy = x2 - x1, y2 - y1
        seg_len2 = dx * dx + dy * dy
        best_d, best_i = -1.0, -1
        for i in range(s + 1, e):
            px, py = xy[i]
            if seg_len2 == 0:
                d = math.hypot(px - x1, py - y1)
            else:
                t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / seg_len2))
                d = math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))
            if d > best_d:
                best_d, best_i = d, i
        if best_d > tolerance_m:
            keep[best_i] = True
            stack.append((s, best_i))
            stack.append((best_i, e))
    return [p for p, k in zip(path, keep) if k]


def round_path(path: Sequence[LatLon], ndigits: int = 5) -> list[list[float]]:
    return [[round(lat, ndigits), round(lon, ndigits)] for lat, lon in path]
