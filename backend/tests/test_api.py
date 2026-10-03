import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.geo.rail import SegmentStore
from app.geo.stations import StationGeo, StationIndex
from app.main import create_app
from app.plk.mock import STATIONS, MockPlkClient
from app.state import utcnow

COORDS = json.loads((Path(__file__).parent / "fixtures" / "mock_station_coords.json").read_text(encoding="utf-8"))


@pytest.fixture
def client(tmp_path):
    settings = Settings(_env_file=None, mock_mode=True, data_dir=tmp_path)
    stations = StationIndex(
        {int(k): StationGeo(int(k), STATIONS[int(k)], v[0], v[1], "test") for k, v in COORDS.items()}
    )
    app = create_app(settings, source=MockPlkClient(settings.tz), stations=stations, segments=SegmentStore(None))
    with TestClient(app) as c:
        # The poller sleeps until someone opens the map; the first map request waits for fresh data.
        assert c.get("/api/meta").json()["apiCalls"] == 0  # nothing is fetched before the map is opened
        assert c.get("/api/trains").json()["trains"]
        yield c


def test_meta(client):
    meta = client.get("/api/meta").json()
    assert meta["mode"] == "mock"
    assert any("PKP Polskie Linie Kolejowe" in a for a in meta["attribution"])
    assert meta["trainCount"] > 0 and not meta["stale"] and meta["lastError"] is None


def test_trains_are_placed_in_poland(client):
    data = client.get("/api/trains").json()
    assert data["trains"], "mock should always have trains running"
    for t in data["trains"]:
        assert 49.0 < t["lat"] < 55.0 and 14.0 < t["lon"] < 24.5
        assert t["status"] in {"not_started", "dwelling", "moving", "awaiting"}
        assert t["number"] and t["origin"] and t["destination"]
        if t["status"] == "moving":
            a, b = t["segment"]["key"].split("-")
            assert int(a) in STATIONS and int(b) in STATIONS
            assert t["segment"]["arrMs"] > t["segment"]["depMs"]


def test_train_detail_and_segments(client):
    moving = [t for t in client.get("/api/trains").json()["trains"] if t["status"] == "moving"]
    assert moving
    detail = client.get(f"/api/trains/{moving[0]['key']}").json()
    assert detail["stops"][0]["name"] == detail["origin"]
    assert detail["segmentKeys"] and detail["currentSegmentIndex"] is not None
    assert detail["segmentKeys"][detail["currentSegmentIndex"]] == moving[0]["segment"]["key"]
    assert any(s["passed"] for s in detail["stops"])

    keys = ",".join(detail["segmentKeys"])
    segs = client.get("/api/segments", params={"keys": keys}).json()
    assert set(segs) == set(detail["segmentKeys"])
    assert all(len(path) >= 2 for path in segs.values())


def test_detail_of_hidden_train_has_no_position(client):
    state = client.app.state.live
    hidden = [t for t in state.trains(utcnow()) if not t.est.visible]
    assert hidden, "mock keeps finished trains for an hour after arrival"
    detail = client.get(f"/api/trains/{hidden[0].key}").json()
    assert detail["status"] in {"finished", "cancelled", "out_of_coverage", "unknown"}
    assert detail["lat"] is None and detail["stops"]


def test_disruptions_listed_and_attached_to_affected_trains(client):
    listed = client.get("/api/disruptions").json()
    assert len(listed) == 2 and client.get("/api/meta").json()["disruptionCount"] == 2
    kutno = next(d for d in listed if d["fromStation"] == "Kutno")
    assert kutno["toStation"] == "Łowicz Główny" and kutno["type"] == "Awaria infrastruktury"

    trains = client.get("/api/trains").json()["trains"]
    hit = [t for t in trains if t["disrupted"]]
    assert hit, "some current WARTA/ODRA runs pass the mock disruptions"
    assert all(t["name"] in ("Warta", "Odra") for t in hit)
    detail = client.get(f"/api/trains/{hit[0]['key']}").json()
    assert detail["disruptions"] and detail["disruptions"][0]["message"]
    clean = next(t for t in trains if not t["disrupted"])
    assert client.get(f"/api/trains/{clean['key']}").json()["disruptions"] == []


def test_unknown_train_is_404(client):
    assert client.get("/api/trains/nope").status_code == 404


def test_stations_only_located_ones(client):
    stations = client.get("/api/stations").json()
    ids = {s["id"] for s in stations}
    assert 90002 in ids and 90099 not in ids  # the test point has no coordinates


def test_station_board_lists_upcoming_trains_soonest_first(client):
    board = client.get("/api/stations/90002/board").json()  # Warszawa Centralna
    assert board["name"] == "Warszawa Centralna" and board["entries"]
    now = board["generatedAtMs"]
    times = [e["estDepartureMs"] or e["estArrivalMs"] for e in board["entries"]]
    assert times == sorted(times)
    assert all(t >= now - 10 * 60_000 for t in times)
    first = board["entries"][0]
    assert first["number"] and first["origin"] and first["destination"]
    assert client.get(f"/api/trains/{first['key']}").status_code == 200
    assert client.get("/api/stations/1/board").status_code == 404
