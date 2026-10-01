"""Synthetic PLK data source for development without an API key (MOCK_MODE=1).

Trains run on real corridors between real stations (so geocoding and track routing are
exercised end to end) every two hours around the clock, in both directions. Station ids
are fake (9xxxx). Times are generated relative to the current time, delays are
deterministic per train run, and "actual" times appear one minute after they happen,
like dispatcher reports would.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.plk.client import QuotaInfo
from app.plk.models import (
    AffectedRoute,
    Disruption,
    DisruptionsResponse,
    OperationsResponse,
    OperationStation,
    Pagination,
    Route,
    SchedulesResponse,
    Station,
    StationOnRoute,
    TrainOperation,
)

SCHEDULE_ID = 26
REPORT_LAG = timedelta(minutes=1)
PERIOD = timedelta(hours=2)

STATIONS: dict[int, str] = {
    90001: "Warszawa Wschodnia", 90002: "Warszawa Centralna", 90003: "Warszawa Zachodnia",
    90004: "Włoszczowa Północ", 90005: "Kraków Główny",
    90010: "Gdynia Główna", 90011: "Sopot", 90012: "Gdańsk Wrzeszcz", 90013: "Gdańsk Główny",
    90014: "Tczew", 90015: "Malbork", 90016: "Iława Główna", 90017: "Działdowo",
    90020: "Poznań Główny", 90021: "Konin", 90022: "Kutno", 90023: "Łowicz Główny",
    90030: "Wrocław Główny", 90031: "Brzeg", 90032: "Opole Główne", 90033: "Gliwice",
    90034: "Zabrze", 90035: "Katowice",
    90040: "Szczecin Główny", 90041: "Stargard", 90042: "Choszczno", 90043: "Krzyż", 90044: "Wronki",
    90050: "Tarnów", 90051: "Dębica", 90052: "Rzeszów Główny", 90053: "Przeworsk",
    90054: "Jarosław", 90055: "Przemyśl Główny",
    90060: "Łódź Fabryczna", 90061: "Łódź Widzew", 90062: "Koluszki", 90063: "Skierniewice",
    # Not in OpenStreetMap on purpose: exercises timetable points without coordinates.
    90099: "Posterunek Testowy",
}


@dataclass(frozen=True)
class Template:
    category: str
    number: int  # national number of the first run; later runs add 2
    name: str
    phase_min: int  # first departure, minutes after midnight
    stops: tuple[tuple[int, int, int], ...]  # (station id, minutes from start, dwell minutes)


TEMPLATES: tuple[Template, ...] = (
    Template("EIC", 1300, "WAWEL", 5, (
        (90001, 0, 0), (90002, 7, 3), (90003, 14, 1), (90004, 95, 1), (90005, 150, 0))),
    Template("EIP", 5400, "NEPTUN", 35, (
        (90010, 0, 0), (90011, 8, 1), (90012, 15, 1), (90013, 21, 2), (90014, 38, 1),
        (90015, 52, 1), (90016, 84, 1), (90017, 108, 1), (90002, 185, 0))),
    Template("IC", 7300, "WARTA", 50, (
        (90020, 0, 0), (90021, 55, 2), (90022, 100, 2), (90099, 112, 0), (90023, 125, 1),
        (90003, 165, 1), (90002, 172, 0))),
    Template("TLK", 6100, "ODRA", 20, (
        (90030, 0, 0), (90031, 30, 1), (90032, 55, 3), (90033, 115, 2), (90034, 125, 1), (90035, 142, 0))),
    Template("TLK", 8300, "PRZEMYSŁAW", 65, (
        (90040, 0, 0), (90041, 25, 1), (90042, 50, 1), (90043, 85, 2), (90044, 110, 1), (90020, 140, 0))),
    Template("IC", 3500, "SAN", 80, (
        (90005, 0, 0), (90050, 60, 2), (90051, 80, 1), (90052, 110, 3), (90053, 135, 1),
        (90054, 145, 1), (90055, 170, 0))),
    Template("IC", 1800, "ŁODZIANIN", 95, (
        (90060, 0, 0), (90061, 8, 1), (90062, 20, 1), (90063, 45, 1), (90003, 75, 1),
        (90002, 82, 2), (90001, 90, 0))),
)

_DELAYS = (0, 0, 0, 0, 2, 3, 5, 8, 12, 15, 25, 40)

MOCK_DISRUPTION_TYPES = {"utr_02": "Awaria infrastruktury", "utr_10": "Prace torowe"}
# (type code, start station, end station, message)
MOCK_DISRUPTIONS = (
    ("utr_02", 90022, 90023, "Awaria rozjazdu na stacji Kutno. Pociągi mogą być opóźnione do 20 minut."),
    ("utr_10", 90032, 90032, "Prace torowe na stacji Opole Główne. Ruch jednotorowy, możliwe opóźnienia."),
)


def _reverse(t: Template) -> Template:
    total = t.stops[-1][1]
    stops = []
    for sid, off, dwell in reversed(t.stops):
        stops.append((sid, total - off - dwell, dwell))
    return Template(t.category, t.number + 1, t.name, (t.phase_min + 60) % 120, tuple(stops))


ALL_TEMPLATES: tuple[Template, ...] = tuple(x for t in TEMPLATES for x in (t, _reverse(t)))


@dataclass
class _Run:
    template_index: int
    template: Template
    k: int
    operating_date: date
    start: datetime  # naive local

    @property
    def order_id(self) -> int:
        return 1000 * (self.template_index + 1) + self.k

    @property
    def rng(self) -> random.Random:
        return random.Random(f"{self.operating_date}-{self.template_index}-{self.k}")

    def planned(self) -> list[tuple[int, datetime | None, datetime | None]]:
        out = []
        n = len(self.template.stops)
        for i, (sid, off, dwell) in enumerate(self.template.stops):
            arr = self.start + timedelta(minutes=off) if i > 0 else None
            dep = self.start + timedelta(minutes=off + dwell) if i < n - 1 else None
            out.append((sid, arr, dep))
        return out


class MockPlkClient:
    def __init__(self, tz: ZoneInfo, now_fn=None) -> None:
        self.tz = tz
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self.quota = QuotaInfo(daily_limit=None)
        self.calls_made = 0
        self.last_snapshot_at: datetime | None = None

    async def aclose(self) -> None:
        pass

    def _local_now(self) -> datetime:
        return self._now_fn().astimezone(self.tz).replace(tzinfo=None)

    def _runs_for_day(self, d: date) -> list[_Run]:
        runs = []
        midnight = datetime.combine(d, time())
        for ti, t in enumerate(ALL_TEMPLATES):
            k = 0
            while True:
                start = midnight + timedelta(minutes=t.phase_min) + k * PERIOD
                if start.date() != d:
                    break
                runs.append(_Run(ti, t, k, d, start))
                k += 1
        return runs

    # -- PlkSource interface ----------------------------------------------------
    async def stations(self) -> list[Station]:
        self.calls_made += 1
        return [Station(id=i, name=n) for i, n in STATIONS.items()]

    async def schedules(self, date_from: date, date_to: date, carriers: list[str]) -> SchedulesResponse:
        self.calls_made += 1
        routes = []
        d = date_from
        while d <= date_to:
            for run in self._runs_for_day(d):
                routes.append(self._route(run))
            d += timedelta(days=1)
        return SchedulesResponse(generated_at=self._now_fn(), routes=routes)

    async def operations(self, carriers: list[str]) -> OperationsResponse:
        self.calls_made += 1
        now = self._local_now()
        trains = []
        for d in (now.date() - timedelta(days=1), now.date()):
            for run in self._runs_for_day(d):
                op = self._operation(run, now)
                if op is not None:
                    trains.append(op)
        self.last_snapshot_at = self._now_fn()
        return OperationsResponse(
            generated_at=self.last_snapshot_at,
            pagination=Pagination(page=1, page_size=5000, total_count=len(trains), total_pages=1),
            trains=trains,
            stations={str(k): v for k, v in STATIONS.items()},
        )

    async def disruptions(self, carriers: list[str]) -> DisruptionsResponse:
        """Two standing disruptions affecting every current run that passes through them."""
        self.calls_made += 1
        now = self._local_now()
        out = []
        for did, (code, a, b, message) in enumerate(MOCK_DISRUPTIONS, 1):
            affected = []
            for d in (now.date() - timedelta(days=1), now.date()):
                for run in self._runs_for_day(d):
                    if self._operation(run, now) is None:
                        continue
                    for seq, (sid, _, _) in enumerate(run.template.stops, 1):
                        if sid in (a, b):
                            affected.append(AffectedRoute(
                                schedule_id=SCHEDULE_ID, order_id=run.order_id, operating_date=run.operating_date,
                                station_id=sid, sequence_number=seq,
                            ))
                            break
            out.append(Disruption(
                disruption_id=did, disruption_type_code=code, start_station_id=a, end_station_id=b,
                message=message, affected_routes=affected,
            ))
        return DisruptionsResponse(
            generated_at=self._now_fn(),
            disruptions=out,
            disruption_types={code: name for code, name in MOCK_DISRUPTION_TYPES.items()},
            stations={str(k): v for k, v in STATIONS.items()},
        )

    # -- generation -----------------------------------------------------------------
    def _route(self, run: _Run) -> Route:
        t = run.template
        rng = run.rng
        stations = []
        for i, (sid, arr, dep) in enumerate(run.planned()):
            passing = sid == 90099
            platform = None if passing else str(rng.randint(1, 5))
            track = None if passing else str(rng.randint(1, 12))

            def ts(x: datetime | None) -> tuple[str | None, int | None]:
                if x is None:
                    return None, None
                return x.strftime("%H:%M:%S"), (x.date() - run.operating_date).days

            at, ad = ts(arr)
            dt, dd = ts(dep)
            stations.append(StationOnRoute(
                station_id=sid, order_number=i + 1,
                arrival_time=at, arrival_day=ad, departure_time=dt, departure_day=dd,
                arrival_platform=platform if arr else None, arrival_track=track if arr else None,
                departure_platform=platform if dep else None, departure_track=track if dep else None,
                stop_type_name="bez postoju" if passing else "postój handlowy",
            ))
        return Route(
            schedule_id=SCHEDULE_ID, order_id=run.order_id, name=t.name, carrier_code="IC",
            national_number=str(t.number + 2 * run.k), commercial_category_symbol=t.category,
            operating_dates=[run.operating_date], stations=stations,
        )

    def _operation(self, run: _Run, now: datetime) -> TrainOperation | None:
        planned = run.planned()
        first_dep = planned[0][2]
        last_arr = planned[-1][1]
        if now < first_dep - timedelta(minutes=30) or now > last_arr + timedelta(minutes=60):
            return None
        rng = run.rng
        roll = rng.random()
        delay = timedelta(minutes=rng.choice(_DELAYS))
        delay_from = rng.randint(1, len(planned) - 1)
        cancelled_run = roll < 0.02
        cancelled_stop = rng.randint(1, len(planned) - 2) if 0.02 <= roll < 0.06 and len(planned) > 3 else None

        stations = []
        reported_any = False
        finished = False
        for i, (sid, arr, dep) in enumerate(planned):
            d = delay if i >= delay_from else timedelta(minutes=rng.choice((0, 0, 1)))
            act_arr = arr + d if arr else None
            if dep and act_arr:
                min_dwell = timedelta(minutes=1) if dep > arr else timedelta(0)
                act_dep = max(dep, act_arr + min_dwell)
            else:
                act_dep = dep + d if dep else None
            if dep and i == 0:
                act_dep = dep + timedelta(minutes=rng.choice((0, 0, 1)))
            seen_arr = act_arr if act_arr and act_arr + REPORT_LAG <= now else None
            seen_dep = act_dep if act_dep and act_dep + REPORT_LAG <= now else None
            is_cancelled = cancelled_run or i == cancelled_stop
            if is_cancelled:
                seen_arr = seen_dep = None
            reported_any = reported_any or bool(seen_arr or seen_dep)
            if i == len(planned) - 1 and seen_arr:
                finished = True

            def minutes(actual: datetime | None, plan: datetime | None) -> int | None:
                return round((actual - plan).total_seconds() / 60) if actual and plan else None

            stations.append(OperationStation(
                station_id=sid, planned_sequence_number=i + 1, actual_sequence_number=i + 1,
                planned_arrival=arr, planned_departure=dep,
                actual_arrival=seen_arr, actual_departure=seen_dep,
                arrival_delay_minutes=minutes(seen_arr, arr), departure_delay_minutes=minutes(seen_dep, dep),
                is_confirmed=bool(seen_arr or seen_dep), is_cancelled=is_cancelled,
            ))

        if cancelled_run:
            status = "X"
        elif finished:
            status = "C"
        elif cancelled_stop is not None:
            status = "Q"
        elif reported_any:
            status = "P"
        else:
            status = "S"
        return TrainOperation(
            schedule_id=SCHEDULE_ID, order_id=run.order_id, operating_date=run.operating_date,
            train_status=status, stations=stations,
        )
