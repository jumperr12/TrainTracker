from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.plk.mock import ALL_TEMPLATES, STATIONS, MockPlkClient

TZ = ZoneInfo("Europe/Warsaw")


def client_at(iso: str) -> MockPlkClient:
    fixed = datetime.fromisoformat(iso).astimezone(UTC)
    return MockPlkClient(TZ, now_fn=lambda: fixed)


async def test_trains_run_at_any_hour():
    for hour in ("03:10", "12:00", "23:40"):
        resp = await client_at(f"2026-09-30T{hour}:00+02:00").operations(["IC"])
        assert sum(1 for t in resp.trains if t.train_status in ("P", "Q")) >= 5, hour


async def test_operations_are_stable_between_polls():
    c = client_at("2026-09-30T12:00:00+02:00")
    a, b = await c.operations(["IC"]), await c.operations(["IC"])
    assert a.model_dump() == b.model_dump()


async def test_reports_lag_behind_now_and_times_are_naive():
    resp = await client_at("2026-09-30T12:00:00+02:00").operations(["IC"])
    now_local = datetime(2026, 9, 30, 12, 0)
    for t in resp.trains:
        for s in t.stations:
            for v in (s.actual_arrival, s.actual_departure):
                if v is not None:
                    assert v.tzinfo is None
                    if s.is_confirmed:
                        assert v <= now_local


async def test_stops_not_reached_carry_forecasts_like_the_real_api():
    resp = await client_at("2026-09-30T12:00:00+02:00").operations(["IC"])
    upcoming = [s for t in resp.trains for s in t.stations if not s.is_confirmed and not s.is_cancelled]
    assert upcoming
    assert all(s.actual_arrival or s.actual_departure for s in upcoming)


async def test_schedules_cover_every_run_and_known_stations():
    resp = await client_at("2026-09-30T12:00:00+02:00").schedules(date(2026, 9, 29), date(2026, 9, 30), ["IC"])
    assert len(resp.routes) == 2 * 12 * len(ALL_TEMPLATES)
    assert all(s.station_id in STATIONS for r in resp.routes for s in r.stations)
    assert {r.commercial_category_symbol for r in resp.routes} == {"EIC", "EIP", "IC", "TLK"}
