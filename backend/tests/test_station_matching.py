import pytest

from app.geo.names import NameIndex, OsmFeature, features_from_overpass, match_stations, normalize
from app.geo.stations import StationIndex


@pytest.mark.parametrize(
    "a, b",
    [
        ("Kraków Gł.", "Kraków Główny"),
        ("Opole Główne", "Opole Gł"),
        ("Iława Główna", "IŁAWA GŁ."),
        ("Warszawa Zach.", "Warszawa Zachodnia"),
        ("Gdańsk-Wrzeszcz", "Gdańsk Wrzeszcz"),
        ("Grodzisk Maz.", "Grodzisk Mazowiecki"),
        ("Łódź Fabryczna", "Lodz Fabryczna"),
    ],
)
def test_normalize_equivalents(a, b):
    assert normalize(a) == normalize(b)


def test_normalize_keeps_distinct_stations_apart():
    assert normalize("Warszawa Wschodnia") != normalize("Warszawa Zachodnia")


def feat(osm_id, lat, lon, *names, kind="station"):
    return OsmFeature(osm_id, lat, lon, kind, list(names))


def test_exact_fuzzy_and_missing():
    index = NameIndex([feat("n1", 50.07, 19.95, "Kraków Główny"), feat("n2", 54.04, 19.04, "Malbork")])
    matches, problems = match_stations({1: "Kraków Gł.", 2: "Malborkk", 3: "Nowhere"}, index)
    assert matches[1].source == "osm" and matches[1].osm_id == "n1"
    assert matches[2].source == "osm-fuzzy" and matches[2].osm_id == "n2"
    assert problems == [(3, "Nowhere", "no match")]


def test_station_node_and_area_of_same_place_are_not_ambiguous():
    index = NameIndex([
        feat("w1", 52.2290, 21.0030, "Warszawa Centralna"),
        feat("n1", 52.2288, 21.0032, "Warszawa Centralna", kind="halt"),
    ])
    matches, problems = match_stations({7: "Warszawa Centralna"}, index)
    assert not problems and matches[7].osm_id == "w1"


def test_ambiguous_name_resolved_by_route_neighbour():
    index = NameIndex([
        feat("k-north", 54.0, 18.0, "Kolonia"),
        feat("k-south", 50.0, 20.0, "Kolonia"),
        feat("t", 50.05, 20.1, "Tarnówek"),
    ])
    matches, problems = match_stations({1: "Kolonia", 2: "Tarnówek"}, index, neighbours={1: {2}, 2: {1}})
    assert not problems
    assert matches[1].osm_id == "k-south" and matches[1].source == "osm-context"


def test_ambiguous_without_context_is_reported():
    index = NameIndex([feat("a", 54.0, 18.0, "Kolonia"), feat("b", 50.0, 20.0, "Kolonia")])
    matches, problems = match_stations({1: "Kolonia"}, index)
    assert not matches and "ambiguous" in problems[0][2]


def test_features_from_overpass_uses_alternative_names():
    feats = features_from_overpass([
        {"id": "n5", "lat": 53.3, "lon": 15.0, "tags": {"railway": "station", "name": "Stargard", "old_name": "Stargard Szczeciński"}},
        {"id": "n6", "lat": 53.0, "lon": 15.0, "tags": {"railway": "station"}},  # unnamed: skipped
    ])
    assert len(feats) == 1
    matches, _ = match_stations({1: "Stargard Szczeciński"}, NameIndex(feats))
    assert matches[1].osm_id == "n5"


def test_overrides_win(tmp_path):
    geo = tmp_path / "geo.json"
    geo.write_text('{"stations": {"1": {"name": "A", "lat": 50.0, "lon": 20.0}}}', encoding="utf-8")
    overrides = tmp_path / "o.csv"
    overrides.write_text("# comment\nid,name,lat,lon\n1,A,51.0,21.0\n2,B,52.0,22.0\n", encoding="utf-8")
    idx = StationIndex.load(geo, overrides)
    assert idx.latlon(1) == (51.0, 21.0) and idx.latlon(2) == (52.0, 22.0)
    assert idx.get(1).source == "override"
