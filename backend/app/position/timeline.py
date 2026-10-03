"""Turn one train's operations record into a timeline of effective (actual or predicted) times.

Rules:
- Cancelled stops are dropped; stops are ordered by actual (else planned) sequence number.
- The API fills the "actual" fields of stops the train hasn't reached with PLK's own forecast.
  Only times of confirmed stops (isConfirmed) that aren't later than the fetch time are reports;
  everything else is a forecast.
- Reported times are used as-is. Beyond the last report, PLK's forecast is used where there is
  one; otherwise the last known delay is carried forward: est_arr = planned_arr + delay,
  est_dep = max(planned_dep, est_arr + min(planned dwell, MIN_DWELL)), so a late train
  recovers time at stops with long planned dwell.
- Unreported stops *before* the last report get a delay interpolated between the reports
  around them (a missing report doesn't mean the train is still there).
- Naive timestamps (the API omits the offset) are interpreted in the configured timezone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo

from app.plk.models import OperationStation, TrainOperation

MIN_DWELL = timedelta(seconds=60)
# A confirmed time up to this far past the fetch time still counts as reported (minute rounding).
REPORT_TOLERANCE = timedelta(minutes=1)


def aware(dt: datetime | None, tz: tzinfo) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=tz) if dt.tzinfo is None else dt


@dataclass
class TimelineStop:
    station_id: int
    seq: int
    planned_arr: datetime | None
    planned_dep: datetime | None
    actual_arr: datetime | None  # reported times only
    actual_dep: datetime | None
    forecast_arr: datetime | None = None  # PLK's prediction for a time not reported yet
    forecast_dep: datetime | None = None
    est_arr: datetime | None = None
    est_dep: datetime | None = None

    @property
    def reported(self) -> bool:
        return self.actual_arr is not None or self.actual_dep is not None

    @property
    def t_in(self) -> datetime | None:
        return self.est_arr or self.est_dep

    @property
    def t_out(self) -> datetime | None:
        return self.est_dep or self.est_arr

    @property
    def planned_in(self) -> datetime | None:
        return self.planned_arr or self.planned_dep

    @property
    def planned_out(self) -> datetime | None:
        return self.planned_dep or self.planned_arr

    @property
    def is_passenger_stop(self) -> bool:
        """Origin, terminus, or a planned dwell. Passing points have arrival == departure."""
        if self.planned_arr is None or self.planned_dep is None:
            return True
        return self.planned_dep > self.planned_arr

    @property
    def arr_delay(self) -> timedelta | None:
        if self.est_arr and self.planned_arr:
            return self.est_arr - self.planned_arr
        return None

    @property
    def dep_delay(self) -> timedelta | None:
        if self.est_dep and self.planned_dep:
            return self.est_dep - self.planned_dep
        return None

    @property
    def delay(self) -> timedelta:
        d = self.dep_delay
        if d is None:
            d = self.arr_delay
        return d if d is not None else timedelta(0)


@dataclass
class Timeline:
    stops: list[TimelineStop] = field(default_factory=list)
    last_reported: int = -1  # index into stops, -1 = nothing reported yet

    @property
    def last_report_time(self) -> datetime | None:
        if self.last_reported < 0:
            return None
        s = self.stops[self.last_reported]
        return s.actual_dep or s.actual_arr


def _stop(raw: OperationStation, seq: int, tz: tzinfo, as_of: datetime | None) -> TimelineStop:
    arr, dep = aware(raw.actual_arrival, tz), aware(raw.actual_departure, tz)
    horizon = as_of + REPORT_TOLERANCE if as_of is not None else None

    def is_report(t: datetime | None) -> bool:
        return raw.is_confirmed and t is not None and (horizon is None or t <= horizon)

    return TimelineStop(
        station_id=raw.station_id,
        seq=seq,
        planned_arr=aware(raw.planned_arrival, tz),
        planned_dep=aware(raw.planned_departure, tz),
        actual_arr=arr if is_report(arr) else None,
        actual_dep=dep if is_report(dep) else None,
        forecast_arr=None if is_report(arr) else arr,
        forecast_dep=None if is_report(dep) else dep,
    )


def build_timeline(
    op: TrainOperation, tz: tzinfo, min_dwell: timedelta = MIN_DWELL, as_of: datetime | None = None
) -> Timeline:
    """`as_of` is when the data was fetched: confirmed times after it are forecasts, not reports."""
    raw = [s for s in op.stations if not s.is_cancelled]
    order = sorted(
        range(len(raw)),
        key=lambda i: (raw[i].actual_sequence_number or raw[i].planned_sequence_number or 0, i),
    )
    stops = [
        _stop(raw[i], raw[i].actual_sequence_number or raw[i].planned_sequence_number or i, tz, as_of)
        for i in order
    ]
    tl = Timeline(stops)
    if not stops:
        return tl

    reported = [i for i, s in enumerate(stops) if s.reported]
    tl.last_reported = reported[-1] if reported else -1

    # 1) Reported stops keep their actual times; a missing half comes from the forecast or the other half.
    for i in reported:
        s = stops[i]
        _fill(s, s.actual_arr or s.forecast_arr, s.actual_dep or s.forecast_dep, min_dwell)

    # 2) Unreported stops before the last report: interpolate the delay between surrounding reports.
    prev_r: int | None = None
    for i in range(tl.last_reported):
        if stops[i].reported:
            prev_r = i
            continue
        nxt = next(j for j in reported if j > i)
        d_next = stops[nxt].delay
        if prev_r is None:
            d = d_next
        else:
            d_prev = stops[prev_r].delay
            t0, t1, t = stops[prev_r].planned_out, stops[nxt].planned_in, stops[i].planned_in
            if t0 and t1 and t and t1 > t0:
                frac = min(1.0, max(0.0, (t - t0) / (t1 - t0)))
                d = d_prev + (d_next - d_prev) * frac
            else:
                d = d_next
        _shift(stops[i], d)

    # 3) Stops after the last report: PLK's forecast, else carry the delay forward with dwell recovery.
    delay = stops[tl.last_reported].delay if tl.last_reported >= 0 else timedelta(0)
    for i in range(tl.last_reported + 1, len(stops)):
        s = stops[i]
        if s.forecast_arr is not None or s.forecast_dep is not None:
            _fill(s, s.forecast_arr, s.forecast_dep, min_dwell)
            delay = s.delay
            continue
        s.est_arr = s.planned_arr + delay if s.planned_arr else None
        if s.planned_dep is not None:
            if s.est_arr is not None:
                dwell = s.planned_dep - s.planned_arr if s.planned_arr else timedelta(0)
                s.est_dep = max(s.planned_dep, s.est_arr + min(dwell, min_dwell))
            else:  # origin not yet departed: it leaves on time or, if it is already late, now-ish
                s.est_dep = s.planned_dep + max(delay, timedelta(0))
            delay = s.est_dep - s.planned_dep

    # 4) Times never run backwards along the route.
    last: datetime | None = None
    for s in stops:
        if s.est_arr is not None:
            if last is not None and s.est_arr < last:
                s.est_arr = last
            last = s.est_arr
        if s.est_dep is not None:
            if last is not None and s.est_dep < last:
                s.est_dep = last
            last = s.est_dep
    return tl


def _fill(s: TimelineStop, arr: datetime | None, dep: datetime | None, min_dwell: timedelta) -> None:
    """Use the given times; a missing half is derived from the other half and the plan."""
    if arr is not None:
        s.est_arr = arr
    elif s.planned_arr is not None and dep is not None:  # only the departure is known
        dep_delay = dep - s.planned_dep if s.planned_dep else timedelta(0)
        s.est_arr = min(dep, s.planned_arr + dep_delay)
    s.est_dep = dep
    if s.est_dep is None and s.planned_dep is not None:
        base = s.est_arr or s.planned_dep
        dwell = (s.planned_dep - s.planned_arr) if s.planned_arr else timedelta(0)
        s.est_dep = max(s.planned_dep, base + min(dwell, min_dwell))


def _shift(s: TimelineStop, d: timedelta) -> None:
    s.est_arr = s.planned_arr + d if s.planned_arr else None
    s.est_dep = s.planned_dep + d if s.planned_dep else None
