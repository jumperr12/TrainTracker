"""Background loop: the only component that talks to the PLK API."""

from __future__ import annotations

import asyncio
import csv
import logging
import time
from datetime import date, datetime, timedelta

from app.config import Settings
from app.geo.rail import RailGraphData, RailRouter, located_pairs, route_missing_pairs
from app.plk.client import PlkAuthError, PlkError, PlkRateLimited, PlkSource
from app.plk.models import SchedulesResponse
from app.state import LiveState, utcnow
from app.sync.quota import MAINTENANCE_POLL_S, base_interval, in_maintenance_window, paced_interval

log = logging.getLogger(__name__)

SCHEDULES_MAX_AGE = timedelta(hours=24)  # plus a refresh whenever the local date changes
DISRUPTIONS_INTERVAL = timedelta(minutes=15)
MAX_BACKOFF_S = 900.0
FRESH_WAIT_S = 10.0


class Poller:
    """Polls the PLK API only while someone is using the map.

    Requests to /api/trains or /api/trains/{key} count as activity. After `idle_after_min`
    minutes without activity the loop pauses and makes no API calls; the next request wakes it
    up and waits (up to FRESH_WAIT_S) for fresh data before answering.
    """

    def __init__(self, settings: Settings, source: PlkSource, state: LiveState) -> None:
        self.settings = settings
        self.source = source
        self.state = state
        self.base_interval = 15.0 if settings.mock_mode else base_interval(settings.plk_tier, settings.poll_interval_s)
        state.poll_interval_s = self.base_interval
        self.idle_after = timedelta(minutes=settings.idle_after_min)
        self.last_activity: datetime | None = None
        self._schedules_for: date | None = None
        self._failures = 0
        self._routing: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()
        self._polled = asyncio.Event()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def _is_idle(self, now: datetime) -> bool:
        if self.idle_after <= timedelta(0):
            return False  # idle mode disabled
        return self.last_activity is None or now - self.last_activity > self.idle_after

    async def on_activity(self) -> None:
        """Called by the API for each map request. Wakes the loop and, if the data is old, waits for a poll."""
        now = utcnow()
        self.last_activity = now
        last = self.state.last_poll_ok
        if last is not None and (now - last).total_seconds() <= max(2 * self.base_interval, 60.0):
            return
        self._polled.clear()
        self._wake.set()
        try:
            await asyncio.wait_for(self._polled.wait(), timeout=FRESH_WAIT_S)
        except TimeoutError:
            pass

    async def run(self) -> None:
        while not self._stop.is_set():
            if self._is_idle(utcnow()):
                if not self.state.idle:
                    log.info("no map activity for %s, pausing API polling", self.idle_after)
                    self.state.idle = True
                self._wake.clear()
                await self._wake.wait()
                continue
            if self.state.idle:
                log.info("map opened, resuming API polling")
                self.state.idle = False
            wait = await self.tick()
            self._polled.set()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
            except TimeoutError:
                pass

    async def tick(self) -> float:
        """One polling cycle. Returns seconds to wait before the next one."""
        now = utcnow()
        local = now.astimezone(self.settings.tz)
        # During planned maintenance the API is expected to be down: try rarely, serve the last snapshot.
        maintenance = in_maintenance_window(local) and not self.settings.mock_mode
        try:
            try:
                await self._ensure_schedules(local.date())
            except (PlkRateLimited, PlkAuthError):
                raise
            except PlkError as exc:  # trains still move without metadata; retry next cycle
                log.warning("schedule refresh failed: %s", exc)
            resp = await self.source.operations(self.settings.carrier_list)
            self.state.set_operations(resp, self.source.last_snapshot_at, utcnow())
            self._failures = 0
            try:
                await self._ensure_disruptions()
            except (PlkRateLimited, PlkAuthError):
                raise
            except PlkError as exc:  # optional extra information; keep the old list
                log.warning("disruptions refresh failed: %s", exc)
            self._start_segment_topup()
            wait = paced_interval(self.base_interval, self.source.quota, local.replace(tzinfo=None))
        except PlkRateLimited as exc:
            self.state.record_error(str(exc), now)
            wait = max((exc.retry_at - now).total_seconds(), 60.0)
        except PlkAuthError as exc:
            log.error("PLK API rejected the key: %s", exc)
            self.state.record_error(str(exc), now, auth=True)
            wait = MAX_BACKOFF_S
        except PlkError as exc:
            self._failures += 1
            log.warning("PLK poll failed (%d in a row): %s", self._failures, exc)
            self.state.record_error(str(exc), now)
            wait = min(self.base_interval * 2 ** min(self._failures, 6), MAX_BACKOFF_S)
        except Exception as exc:  # never let the loop die
            self._failures += 1
            log.exception("poll cycle crashed")
            self.state.record_error(f"internal error: {exc!r}", now)
            wait = min(self.base_interval * 2 ** min(self._failures, 6), MAX_BACKOFF_S)
        if maintenance:
            wait = max(wait, MAINTENANCE_POLL_S)
        self.state.quota = self.source.quota
        self.state.calls_made = self.source.calls_made
        return wait

    # -- disruptions ------------------------------------------------------------------
    async def _ensure_disruptions(self) -> None:
        loaded = self.state.disruptions_loaded_at
        if loaded is not None and utcnow() - loaded < DISRUPTIONS_INTERVAL:
            return
        resp = await self.source.disruptions(self.settings.carrier_list)
        self.state.set_disruptions(resp, utcnow())

    # -- schedules --------------------------------------------------------------------
    async def _ensure_schedules(self, today: date) -> None:
        stale = self.state.schedules_loaded_at is None or utcnow() - self.state.schedules_loaded_at > SCHEDULES_MAX_AGE
        if self._schedules_for == today and not stale:
            return
        date_from, date_to = today - timedelta(days=1), today
        resp = None if self.settings.mock_mode else self._read_schedule_cache(date_from, date_to)
        if resp is None:
            resp = await self.source.schedules(date_from, date_to, self.settings.carrier_list)
            if not self.settings.mock_mode:
                self._write_schedule_cache(date_from, date_to, resp)
        self.state.set_schedules(resp, utcnow())
        self._schedules_for = today

    def _schedule_cache_path(self, date_from: date, date_to: date):
        carriers = "-".join(self.settings.carrier_list) or "all"
        return self.settings.cache_dir / f"schedules_{date_from}_{date_to}_{carriers}.json"

    def _read_schedule_cache(self, date_from: date, date_to: date) -> SchedulesResponse | None:
        path = self._schedule_cache_path(date_from, date_to)
        if not path.exists():
            return None
        age = time.time() - path.stat().st_mtime
        if age > SCHEDULES_MAX_AGE.total_seconds():
            return None
        return SchedulesResponse.model_validate_json(path.read_text(encoding="utf-8"))

    def _write_schedule_cache(self, date_from: date, date_to: date, resp: SchedulesResponse) -> None:
        path = self._schedule_cache_path(date_from, date_to)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(resp.model_dump_json(by_alias=True), encoding="utf-8")

    # -- segment top-up -----------------------------------------------------------------
    def _start_segment_topup(self) -> None:
        """Route station pairs we have no track geometry for yet (background thread)."""
        if self._routing is not None and not self._routing.done():
            return
        if not self.settings.rail_graph_path.exists():
            return
        pairs = located_pairs(self.state.station_sequences(), lambda s: s in self.state.stations)
        missing = [p for p in pairs if not self.state.segments.has(*p)]
        if missing:
            self._routing = asyncio.create_task(asyncio.to_thread(self._route_pairs, missing))

    def _route_pairs(self, pairs: list[tuple[int, int]]) -> None:
        log.info("routing %d new station pairs on the rail graph", len(pairs))
        router = RailRouter(RailGraphData.load(self.settings.rail_graph_path))
        issues = []
        added = route_missing_pairs(
            router, self.state.segments, pairs, self.state.stations.coords(),
            on_issue=lambda a, b, r: issues.append((a, b, self.state.name(a), self.state.name(b), r.reason)),
        )
        self.state.segments.save()
        if issues:
            self.settings.reports_dir.mkdir(parents=True, exist_ok=True)
            with (self.settings.reports_dir / "segment_issues_runtime.csv").open("a", encoding="utf-8", newline="") as f:
                csv.writer(f).writerows(issues)
        log.info("routed %d pairs (%d fell back to straight lines)", added, len(issues))
