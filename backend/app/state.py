"""In-memory live state shared by the poller (writer) and the API (reader)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.geo.rail import SegmentStore
from app.geo.stations import StationIndex
from app.plk.client import QuotaInfo
from app.plk.models import OperationsResponse, Route, SchedulesResponse, TrainOperation
from app.position.estimator import Estimate, estimate
from app.position.timeline import Timeline, build_timeline

VIEW_CACHE_TTL = timedelta(seconds=2)


def train_key(op: TrainOperation) -> str:
    return f"{op.schedule_id}-{op.order_id}-{op.train_order_id or op.order_id}-{op.operating_date.isoformat()}"


@dataclass
class LiveTrain:
    key: str
    op: TrainOperation
    route: Route | None
    timeline: Timeline
    est: Estimate


class LiveState:
    def __init__(self, settings: Settings, stations: StationIndex, segments: SegmentStore) -> None:
        self.settings = settings
        self.stations = stations
        self.segments = segments
        self.mode = "mock" if settings.mock_mode else "live"
        self.routes: dict[tuple[int, int], Route] = {}
        self.station_names: dict[int, str] = {}
        self.operations: list[TrainOperation] = []
        self._timelines: dict[str, Timeline] = {}
        self.snapshot_at: datetime | None = None
        self.last_poll_ok: datetime | None = None
        self.schedules_loaded_at: datetime | None = None
        self.last_error: str | None = None
        self.last_error_at: datetime | None = None
        self.auth_error = False
        self.poll_interval_s: float | None = None
        self.quota: QuotaInfo = QuotaInfo()
        self.calls_made = 0
        self._cache: tuple[datetime, list[LiveTrain]] | None = None

    # -- writers (poller) ---------------------------------------------------------
    def set_schedules(self, resp: SchedulesResponse, now: datetime) -> None:
        routes: dict[tuple[int, int], Route] = {}
        for r in resp.routes:
            routes[(r.schedule_id, r.order_id)] = r
            if r.train_order_id:
                routes.setdefault((r.schedule_id, r.train_order_id), r)
        self.routes = routes
        if resp.dictionaries:
            for s in resp.dictionaries.stations.values():
                self.station_names[s.id] = s.name
        self.schedules_loaded_at = now
        self._cache = None

    def set_operations(self, resp: OperationsResponse, snapshot_at: datetime | None, now: datetime) -> None:
        for sid, name in resp.stations.items():
            try:
                self.station_names[int(sid)] = name
            except ValueError:
                continue
        tz = self.settings.tz
        self.operations = resp.trains
        self._timelines = {train_key(op): build_timeline(op, tz) for op in resp.trains}
        self.snapshot_at = snapshot_at or resp.generated_at or now
        self.last_poll_ok = now
        self.last_error = None
        self.auth_error = False
        self._cache = None

    def record_error(self, message: str, now: datetime, auth: bool = False) -> None:
        self.last_error = message
        self.last_error_at = now
        self.auth_error = auth

    # -- readers (API) ----------------------------------------------------------------
    def route_for(self, op: TrainOperation) -> Route | None:
        r = self.routes.get((op.schedule_id, op.order_id))
        if r is None and op.train_order_id:
            r = self.routes.get((op.schedule_id, op.train_order_id))
        return r

    def name(self, sid: int) -> str:
        if sid in self.station_names:
            return self.station_names[sid]
        geo = self.stations.get(sid)
        return geo.name if geo else str(sid)

    def trains(self, now: datetime) -> list[LiveTrain]:
        if self._cache and now - self._cache[0] < VIEW_CACHE_TTL:
            return self._cache[1]
        grace = timedelta(minutes=self.settings.hold_grace_min)
        out = []
        for op in self.operations:
            key = train_key(op)
            tl = self._timelines.get(key)
            if tl is None or not tl.stops:
                continue
            est = estimate(tl, op.train_status, now, self.stations, self.segments, grace)
            out.append(LiveTrain(key, op, self.route_for(op), tl, est))
        self._cache = (now, out)
        return out

    def find(self, key: str, now: datetime) -> LiveTrain | None:
        return next((t for t in self.trains(now) if t.key == key), None)

    def is_stale(self, now: datetime) -> bool:
        if self.last_poll_ok is None:
            return True
        limit = max(3 * (self.poll_interval_s or 120), 300)
        return (now - self.last_poll_ok).total_seconds() > limit

    def station_sequences(self) -> list[list[int]]:
        seqs = [[s.station_id for s in tl.stops] for tl in self._timelines.values()]
        seqs += [[s.station_id for s in r.stations] for r in self.routes.values()]
        return seqs

    def passenger_station_ids(self) -> set[int]:
        """Stations where some tracked train stops for passengers (not junctions or passing points)."""
        ids: set[int] = set()
        for r in self.routes.values():
            last = len(r.stations) - 1
            for i, s in enumerate(r.stations):
                dwell = s.arrival_time is not None and s.departure_time is not None and s.arrival_time != s.departure_time
                if i in (0, last) or dwell or s.arrival_platform or s.departure_platform:
                    ids.add(s.station_id)
        return ids


def utcnow() -> datetime:
    return datetime.now(UTC)
