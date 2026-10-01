import json
from pathlib import Path

import pytest

from app.geo.polyline import (
    angle_diff,
    bearing_deg,
    cumulative,
    haversine_m,
    interpolate_along,
    simplify,
)

CASES = json.loads((Path(__file__).parent / "fixtures" / "interp_cases.json").read_text(encoding="utf-8"))


def test_haversine_warsaw_krakow():
    # Warszawa Centralna -> Kraków Główny, ~252 km as the crow flies
    d = haversine_m(52.2289, 21.0032, 50.0677, 19.9476)
    assert 250_000 < d < 255_000


@pytest.mark.parametrize(
    "p2, expected",
    [((53.0, 20.0), 0.0), ((52.0, 21.0), 90.0), ((51.0, 20.0), 180.0), ((52.0, 19.0), 270.0)],
)
def test_bearing_cardinal(p2, expected):
    assert angle_diff(bearing_deg(52.0, 20.0, *p2), expected) < 1.0


def test_angle_diff_wraps():
    assert angle_diff(350, 10) == pytest.approx(20)
    assert angle_diff(10, 190) == pytest.approx(180)


def test_interpolate_clamps_and_hits_vertices():
    path = [(52.0, 20.0), (52.0, 20.01), (52.01, 20.01)]
    cum = cumulative(path)
    assert interpolate_along(path, cum, -5)[:2] == path[0]
    assert interpolate_along(path, cum, cum[-1] + 5)[:2] == pytest.approx(path[-1])
    lat, lon, _ = interpolate_along(path, cum, cum[1])
    assert (lat, lon) == pytest.approx(path[1])


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_interpolation_cases(case):
    """Same vectors are checked by frontend/src/lib/interpolate.test.ts."""
    path = [tuple(p) for p in case["path"]]
    cum = cumulative(path)
    lat, lon, brg = interpolate_along(path, cum, case["fraction"] * cum[-1])
    assert lat == pytest.approx(case["expected"][0], abs=1e-6)
    assert lon == pytest.approx(case["expected"][1], abs=1e-6)
    assert angle_diff(brg, case["expected"][2]) < 0.01


def test_simplify_drops_collinear_points_keeps_corners():
    line = [(52.0, 20.0 + i * 0.001) for i in range(11)] + [(52.01, 20.01)]
    out = simplify(line, tolerance_m=1.0)
    assert out[0] == line[0] and out[-1] == line[-1]
    assert (52.0, 20.01) in out
    assert len(out) == 3
