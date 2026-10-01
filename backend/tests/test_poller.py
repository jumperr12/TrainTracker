from datetime import UTC, date, datetime, timedelta

import pytest

from app.config import Settings
from app.geo.rail import SegmentStore
from app.geo.stations import StationIndex
from app.plk.client import PlkAuthError, PlkRateLimited, PlkUnavailable, QuotaInfo
from app.plk.mock import MockPlkClient
from app.plk.models import OperationsResponse, SchedulesResponse
from app.state import LiveState
from app.sync.poller import MAX_BACKOFF_S, Poller


class FakeSource:
    def __init__(self, error: Exception | None = None):
        self.error = error
        self.quota = QuotaInfo()
        self.calls_made = 0
        self.last_snapshot_at = None
        self.schedule_calls: list[tuple[date, date]] = []

    async def operations(self, carriers):
        self.calls_made += 1
        if self.error:
            raise self.error
        return OperationsResponse()

    async def schedules(self, date_from, date_to, carriers):
        self.schedule_calls.append((date_from, date_to))
        return SchedulesResponse()

    async def stations(self):
        return []

    async def aclose(self):
        pass


def make(source, tmp_path, **kw):
    settings = Settings(_env_file=None, data_dir=tmp_path, plk_api_key="k", **kw)
    state = LiveState(settings, StationIndex(), SegmentStore(None))
    return Poller(settings, source, state), state


async def test_success_uses_tier_interval_and_caches_schedules(tmp_path):
    src = FakeSource()
    poller, state = make(src, tmp_path, plk_tier="standard")
    wait = await poller.tick()
    assert wait == 30
    assert state.last_poll_ok is not None and state.last_error is None
    assert len(src.schedule_calls) == 1
    frm, to = src.schedule_calls[0]
    assert to - frm == timedelta(days=1)  # yesterday + today, for trains running past midnight
    assert list((tmp_path / "cache").glob("schedules_*_IC.json"))

    # A restarted poller reads the cached schedules instead of spending quota.
    src2 = FakeSource()
    poller2, _ = make(src2, tmp_path, plk_tier="standard")
    await poller2.tick()
    assert src2.schedule_calls == []


async def test_auth_error_is_reported_and_backs_off(tmp_path):
    poller, state = make(FakeSource(PlkAuthError("HTTP 401")), tmp_path)
    assert await poller.tick() == MAX_BACKOFF_S
    assert state.auth_error and "401" in state.last_error


async def test_rate_limit_waits_until_reset(tmp_path):
    retry = datetime.now(UTC) + timedelta(minutes=20)
    poller, state = make(FakeSource(PlkRateLimited(retry)), tmp_path)
    wait = await poller.tick()
    assert 19 * 60 < wait <= 20 * 60
    assert "rate limited" in state.last_error


async def test_transient_errors_back_off_exponentially(tmp_path):
    poller, state = make(FakeSource(PlkUnavailable("boom")), tmp_path, plk_tier="basic")
    waits = [await poller.tick() for _ in range(3)]
    assert waits == [240, 480, 900]  # 120 * 2^n, capped at 15 min
    assert state.is_stale(datetime.now(UTC))


async def test_mock_source_populates_state(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, mock_mode=True)
    state = LiveState(settings, StationIndex(), SegmentStore(None))
    poller = Poller(settings, MockPlkClient(settings.tz), state)
    assert await poller.tick() == pytest.approx(15)
    assert state.operations and state.routes
