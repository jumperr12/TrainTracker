from datetime import date, datetime

import httpx
import pytest
import respx

from app.config import Settings
from app.plk import client as client_mod
from app.plk.client import PlkAuthError, PlkClient, PlkRateLimited, PlkUnavailable
from app.plk.models import parse_timespan

BASE = "https://pdp-api.plk-sa.pl"


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr(client_mod.asyncio, "sleep", instant)


@pytest.fixture
def plk():
    return PlkClient(Settings(_env_file=None, plk_api_key="sk_test_123"))


def ops_page(page, has_next, train_ids):
    return {
        "generatedAt": "2026-09-30T10:00:00Z",
        "pagination": {"page": page, "pageSize": 1, "totalCount": 2, "totalPages": 2, "hasNextPage": has_next},
        "trains": [
            {
                "scheduleId": 26, "orderId": i, "operatingDate": "2026-09-30", "trainStatus": "P",
                "stations": [{
                    "stationId": 5100, "plannedSequenceNumber": 1, "plannedDeparture": "2026-09-30T12:05:00",
                    "actualDeparture": "2026-09-30T12:07:00", "isConfirmed": True, "isCancelled": False,
                    "somethingNew": "ignored",
                }],
            }
            for i in train_ids
        ],
        "stations": {"5100": "Warszawa Centralna"},
    }


@respx.mock
async def test_operations_sends_key_follows_pages_and_reads_quota(plk):
    route = respx.get(f"{BASE}/api/v1/operations").mock(
        side_effect=[
            httpx.Response(200, json=ops_page(1, True, [1]), headers={
                "X-RateLimit-Daily-Remaining": "998", "X-RateLimit-Hourly-Remaining": "98",
                "X-Snapshot-Timestamp": "2026-09-30T09:59:30Z",
            }),
            httpx.Response(200, json=ops_page(2, False, [2]), headers={"X-RateLimit-Daily-Remaining": "997"}),
        ]
    )
    resp = await plk.operations(["IC"])
    assert [t.order_id for t in resp.trains] == [1, 2]
    req = route.calls[0].request
    assert req.headers["X-API-Key"] == "sk_test_123"
    assert req.url.params["carriersInclude"] == "IC"
    assert req.url.params["withPlanned"] == "true" and req.url.params["fullRoutes"] == "true"
    assert route.calls[1].request.url.params["page"] == "2"
    assert plk.quota.daily_remaining == 997 and plk.quota.hourly_remaining == 98
    assert plk.last_snapshot_at == datetime.fromisoformat("2026-09-30T09:59:30+00:00")
    st = resp.trains[0].stations[0]
    assert st.planned_departure == datetime(2026, 9, 30, 12, 5) and st.planned_departure.tzinfo is None
    assert plk.calls_made == 2


@respx.mock
async def test_rate_limit_raises_with_retry_time(plk):
    respx.get(f"{BASE}/api/v1/operations").mock(return_value=httpx.Response(429))
    with pytest.raises(PlkRateLimited) as exc:
        await plk.operations(["IC"])
    assert exc.value.retry_at.minute == 0


@respx.mock
async def test_bad_key_raises_auth_error(plk):
    respx.get(f"{BASE}/api/v1/operations").mock(return_value=httpx.Response(401, json={"error": "Unauthorized"}))
    with pytest.raises(PlkAuthError):
        await plk.operations(["IC"])


@respx.mock
async def test_server_errors_are_retried_then_reported(plk):
    route = respx.get(f"{BASE}/api/v1/schedules").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"routes": []})]
    )
    resp = await plk.schedules(date(2026, 9, 29), date(2026, 9, 30), ["IC"])
    assert resp.routes == [] and route.call_count == 2

    respx.get(f"{BASE}/api/v1/dictionaries/stations").mock(return_value=httpx.Response(500))
    with pytest.raises(PlkUnavailable):
        await plk.stations()


def test_missing_key_is_an_auth_error():
    with pytest.raises(PlkAuthError):
        PlkClient(Settings(_env_file=None, plk_api_key=""))


@pytest.mark.parametrize(
    "raw, minutes",
    [("14:35:00", 875), ("07:05", 425), ("1.02:00:00", 1560), ("00:00:30.5", 0.5 + 0.00833), (None, None)],
)
def test_parse_timespan(raw, minutes):
    td = parse_timespan(raw)
    if minutes is None:
        assert td is None
    else:
        assert td.total_seconds() / 60 == pytest.approx(minutes, abs=0.01)
