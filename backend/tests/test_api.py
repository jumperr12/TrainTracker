import json
import time
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
        deadline = time.time() + 10
        while c.get("/api/meta").json()["trainCount"] == 0 and time.time() < deadline:
            time.sleep(0.05)
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


def test_unknown_train_is_404(client):
    assert client.get("/api/trains/nope").status_code == 404


def test_stations_only_located_ones(client):
    stations = client.get("/api/stations").json()
    ids = {s["id"] for s in stations}
    assert 90002 in ids and 90099 not in ids  # the test point has no coordinates
