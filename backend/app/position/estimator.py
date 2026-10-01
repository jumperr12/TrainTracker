"""Where is the train right now? Places a train on its routed track from its timeline.

The train is placed at a "virtual time" tau on the predicted timeline. Normally tau = now,
but a train cannot be ahead of its next unreported event (departure from the station it
was last reported at, or arrival at the next point): if the prediction says that event
should already have happened, the train is held just before it ("awaiting") for up to
`hold_grace`. After that we assume the point simply doesn't report and follow the prediction.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from app.geo.polyline import LatLon, bearing_deg, interpolate_along
from app.geo.rail import Segment, SegmentStore, segment_key
from app.geo.stations import StationIndex
from app.position.timeline import Timeline, TimelineStop

HOLD_BEFORE = timedelta(seconds=30)
SHOW_BEFORE_DEPARTURE = timedelta(minutes=15)
HIDE_AFTER_ARRIVAL = timedelta(minutes=2)

VISIBLE_STATUSES = {"not_started", "dwelling", "moving", "awaiting"}


@dataclass
class Estimate:
    status: str  # not_started | dwelling | moving | awaiting | finished | cancelled | out_of_coverage | unknown
    lat: float | None = None
    lon: float | None = None
    bearing: float | None = None
    delay: timedelta = timedelta(0)
    at_stop: int | None = None  # timeline index when dwelling/not started
    seg_from: int | None = None  # timeline indexes of the current segment's ends
    seg_to: int | None = None
    seg_dep: datetime | None = None
    seg_arr: datetime | None = None
    next_stop: int | None = None  # timeline index of the next passenger stop

    @property
    def visible(self) -> bool:
        return self.status in VISIBLE_STATUSES and self.lat is not None


@dataclass
class _Located:
    index: int
    stop: TimelineStop
    latlon: LatLon


def estimate(
    tl: Timeline,
    train_status: str | None,
    now: datetime,
    stations: StationIndex,
    segments: SegmentStore,
    hold_grace: timedelta = timedelta(minutes=10),
) -> Estimate:
    if train_status == "X":
        return Estimate("cancelled")
    stops = tl.stops
    located = [
        _Located(i, s, ll) for i, s in enumerate(stops) if (ll := stations.latlon(s.station_id)) is not None
    ]
    if not located or stops[0].t_out is None:
        return Estimate("unknown")

    terminus = stops[-1]
    if terminus.actual_arr is not None and now > terminus.actual_arr + HIDE_AFTER_ARRIVAL:
        return Estimate("finished")
    if train_status == "C":
        return Estimate("finished")

    tau, status, delay_floor = _virtual_time(tl, train_status, now, hold_grace)
    est = _place(located, tau, segments, len(stops))
    if status is not None and est.status in VISIBLE_STATUSES:
        est.status = status

    # Delay shown = expected delay at the next event, never below the delay implied by a hold.
    est.delay = _delay_at(stops, tau)
    if delay_floor is not None and delay_floor > est.delay:
        est.delay = delay_floor

    est.next_stop = next(
        (i for i, s in enumerate(stops) if s.is_passenger_stop and s.t_in and s.t_in > tau), None
    )
    if est.status == "not_started" and stops[0].t_out - now > SHOW_BEFORE_DEPARTURE:
        est.lat = est.lon = None  # too early to show
    if est.status == "finished" and terminus.t_in and now <= terminus.t_in + HIDE_AFTER_ARRIVAL:
        est.status = "dwelling"  # just arrived at the terminus
    return est


def _virtual_time(
    tl: Timeline, train_status: str | None, now: datetime, grace: timedelta
) -> tuple[datetime, str | None, timedelta | None]:
    """Returns (tau, forced status or None, minimum delay implied by a hold)."""
    stops = tl.stops
    lr = tl.last_reported
    origin = stops[0]

    if lr < 0:
        if now < origin.t_out:
            return now, "not_started", None
        late = now - origin.planned_out
        if train_status == "S" or now - origin.t_out <= grace:
            return origin.t_out, "awaiting", max(late, timedelta(0))
        return now, None, None

    s = stops[lr]
    if s.actual_dep is None and s.planned_dep is not None:
        # Reported arrived at station lr but not departed yet.
        event_t, planned_t, hold_t = s.est_dep, s.planned_dep, s.est_dep
    elif lr + 1 < len(stops):
        nxt = stops[lr + 1]
        event_t, planned_t = nxt.t_in, nxt.planned_in
        hold_t = event_t - HOLD_BEFORE if event_t else None
        if hold_t is not None and s.t_out is not None and hold_t < s.t_out:
            hold_t = s.t_out
    else:
        return now, None, None

    if event_t is None or now < event_t:
        return now, None, None
    if now - event_t <= grace:
        floor = now - planned_t if planned_t else None
        return hold_t, "awaiting", floor
    return now, None, None


def _segment(segments: SegmentStore, a: _Located, b: _Located) -> Segment:
    return segments.get_or_straight(a.stop.station_id, b.stop.station_id, a.latlon, b.latlon)


def _place(located: list[_Located], tau: datetime, segments: SegmentStore, n_stops: int) -> Estimate:
    first, last = located[0], located[-1]

    if tau < (first.stop.t_in or first.stop.t_out):
        if first.index == 0:
            return _at(located, 0, segments, "not_started")
        return Estimate("out_of_coverage")  # still abroad / before the first located point

    for k, loc in enumerate(located):
        t_in, t_out = loc.stop.t_in, loc.stop.t_out
        if t_in <= tau <= t_out:
            return _at(located, k, segments, "not_started" if loc.index == 0 else "dwelling")
        if k + 1 < len(located):
            nxt = located[k + 1]
            if t_out < tau < nxt.stop.t_in:
                seg = _segment(segments, loc, nxt)
                dep, arr = t_out, nxt.stop.t_in
                f = (tau - dep) / (arr - dep) if arr > dep else 1.0
                lat, lon, brg = interpolate_along(seg.path, seg.cum, f * seg.length_m)
                return Estimate(
                    "moving", lat, lon, brg,
                    seg_from=loc.index, seg_to=nxt.index, seg_dep=dep, seg_arr=arr,
                )

    # Past the last located point: either at the terminus, or it left the area we have coordinates for.
    if last.index == n_stops - 1:
        return _at(located, len(located) - 1, segments, "finished")
    return Estimate("out_of_coverage")


def _at(located: list[_Located], k: int, segments: SegmentStore, status: str) -> Estimate:
    """Train standing at located[k]: put it on the track end of the adjacent segment."""
    loc = located[k]
    if k + 1 < len(located):
        seg = _segment(segments, loc, located[k + 1])
        (lat, lon), brg = seg.path[0], _initial_bearing(seg.path)
    elif k > 0:
        seg = _segment(segments, located[k - 1], loc)
        (lat, lon), brg = seg.path[-1], _final_bearing(seg.path)
    else:
        (lat, lon), brg = loc.latlon, 0.0
    return Estimate(status, lat, lon, brg, at_stop=loc.index)


def _initial_bearing(path: list[LatLon]) -> float:
    return bearing_deg(*path[0], *path[1]) if len(path) > 1 else 0.0


def _final_bearing(path: list[LatLon]) -> float:
    return bearing_deg(*path[-2], *path[-1]) if len(path) > 1 else 0.0


def _delay_at(stops: list[TimelineStop], tau: datetime) -> timedelta:
    """Expected delay at the next timeline event after tau (or the last one)."""
    for s in stops:
        if s.est_arr is not None and s.est_arr > tau and s.planned_arr is not None:
            return s.est_arr - s.planned_arr
        if s.est_dep is not None and s.est_dep >= tau and s.planned_dep is not None:
            return s.est_dep - s.planned_dep
    return stops[-1].delay


def current_segment_key(tl: Timeline, est: Estimate) -> str | None:
    if est.seg_from is None or est.seg_to is None:
        return None
    return segment_key(tl.stops[est.seg_from].station_id, tl.stops[est.seg_to].station_id)
