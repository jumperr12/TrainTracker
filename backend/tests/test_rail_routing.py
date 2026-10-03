"""Routing on tiny synthetic rail networks."""

import itertools

import pytest

from app.geo.polyline import haversine_m
from app.geo.rail import RailRouter, RouteResult, SegmentStore, build_graph_from_ways

_ids = itertools.count(1)


def way(*pts):
    """A way through the given (lat, lon, node_id) points."""
    return [p[2] for p in pts], [(p[0], p[1]) for p in pts]


def node(lat, lon):
    return (lat, lon, next(_ids))


def passes_near(result: RouteResult, lat: float, lon: float, tol_m: float = 30) -> bool:
    return any(haversine_m(lat, lon, a, b) < tol_m for a, b in result.path)


def test_contraction_line_and_tee():
    a, b, c, d, e = (node(52.0, 20.0 + i * 0.01) for i in range(5))
    g = build_graph_from_ways([way(a, b, c), way(c, d, e)])
    assert g.n_edges == 1  # c has degree 2 even though two ways meet there
    assert len(g.pt_lat) == 5

    t = node(52.01, 20.02)
    g = build_graph_from_ways([way(a, b, c, d, e), way(c, t)])
    assert g.n_edges == 3  # c becomes a junction


def test_route_follows_curved_track():
    pts = [node(52.0 + 0.01 * i, 20.0 + 0.02 * (i % 2)) for i in range(6)]  # zig-zag line
    router = RailRouter(build_graph_from_ways([way(*pts)]))
    r = router.route(pts[0][:2], pts[-1][:2])
    assert r.source == "rail"
    assert all(passes_near(r, p[0], p[1], 1) for p in pts)
    assert r.length_m > r.straight_m


def _v_junction_network():
    w0, w, j, e = node(52.0, 19.97), node(52.0, 20.0), node(52.0, 20.02), node(52.0, 20.05)
    s1, s2 = node(52.01, 20.0), node(52.015, 20.005)
    c1, c2, c3, c4 = node(51.99, 19.99), node(51.99, 19.96), node(52.02, 19.96), node(52.02, 19.99)
    ways = [
        way(w0, w, j, e),  # main line
        way(j, s1),  # sharp spur back towards the north-west: needs a reversal at j
        way(w, c1, c2, c3, c4, s1),  # long legal curve
        way(s1, s2),  # stub so s1 is a junction
    ]
    return build_graph_from_ways(ways), w, j, s1, c2


def test_turn_restriction_forces_legal_path():
    g, w, j, s1, c2 = _v_junction_network()
    strict = RailRouter(g, max_turn_deg=50, max_ratio=100)
    r = strict.route(w[:2], s1[:2])
    assert r.source == "rail"
    assert passes_near(r, *c2[:2]) and not passes_near(r, *j[:2])

    permissive = RailRouter(g, max_turn_deg=180, max_ratio=100)
    r = permissive.route(w[:2], s1[:2])
    assert passes_near(r, *j[:2]) and not passes_near(r, *c2[:2])


def test_no_legal_path_falls_back_to_straight_line():
    w, j, e = node(52.0, 20.0), node(52.0, 20.02), node(52.0, 20.05)
    s1, s2 = node(52.01, 20.0), node(52.015, 20.005)
    g = build_graph_from_ways([way(w, j, e), way(j, s1, s2)])
    r = RailRouter(g, max_turn_deg=50, max_ratio=100).route(w[:2], s2[:2])
    assert r.source == "straight"
    assert r.path == [w[:2], s2[:2]]


def test_ratio_check_rejects_absurd_detours():
    pts = [node(52.0, 20.0), node(52.2, 20.1), node(52.0, 20.2)]  # 45 km detour for 14 km
    r = RailRouter(build_graph_from_ways([way(*pts)]), max_ratio=1.8).route(pts[0][:2], pts[-1][:2])
    assert r.source == "straight" and "longer" in r.reason


def test_multi_candidate_snapping_picks_connected_line():
    # Station A sits between two parallel lines; only the farther one leads to B.
    far1, far2, far3 = node(52.0, 20.0), node(52.0, 20.05), node(52.0, 20.1)
    near1, near2 = node(52.0027, 19.99), node(52.0027, 20.02)  # ~300 m north, dead end
    g = build_graph_from_ways([way(far1, far2, far3), way(near1, near2)])
    a = (52.0018, 20.0)  # ~100 m from the dead-end line, ~200 m from the through line
    r = RailRouter(g).route(a, far3[:2])
    assert r.source == "rail"
    assert passes_near(r, *far2[:2])


def test_route_runs_on_to_the_station_past_a_junction_inside_the_snap_radius():
    a, j, st, e = node(52.0, 20.0), node(52.0, 20.0165), node(52.0, 20.02), node(52.0, 20.03)
    branch = node(52.005, 20.02)
    router = RailRouter(build_graph_from_ways([way(a, j, st, e), way(j, branch)]))
    r = router.route(a[:2], st[:2])  # j is ~240 m before the station
    assert r.source == "rail"
    assert haversine_m(*r.path[-1], *st[:2]) < 20


def test_no_track_nearby():
    pts = [node(52.0, 20.0), node(52.0, 20.1)]
    r = RailRouter(build_graph_from_ways([way(*pts)])).route((53.0, 20.0), pts[1][:2])
    assert r.source == "straight" and "origin" in r.reason


def test_segment_store_roundtrip_and_reversal(tmp_path):
    path = [(52.0, 20.0), (52.0, 20.05), (52.05, 20.05)]
    store = SegmentStore(tmp_path / "seg.json")
    store.put(7, 3, RouteResult(path, 9000.0, 7000.0, "rail"))
    store.save()

    loaded = SegmentStore(tmp_path / "seg.json")
    assert loaded.has(3, 7) and loaded.has(7, 3)
    fwd, back = loaded.get(7, 3), loaded.get(3, 7)
    assert fwd.path[0] == pytest.approx(path[0]) and fwd.path[-1] == pytest.approx(path[-1])
    assert back.path == fwd.path[::-1]
    assert fwd.length_m == pytest.approx(back.length_m)

    straight = loaded.get_or_straight(1, 2, (52.0, 20.0), (52.1, 20.0))
    assert straight.source == "straight" and len(straight.path) == 2

    # The path was stored as 7 -> 3. Moving station 7 by ~11 km makes the segment stale.
    assert loaded.drop_stale({7: path[0], 3: path[-1]}) == 0
    assert loaded.drop_stale({7: (52.1, 20.0), 3: path[-1]}) == 1
    assert not loaded.has(3, 7)
