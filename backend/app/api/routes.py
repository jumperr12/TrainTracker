from datetime import datetime, timedelta
from itertools import pairwise

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.schemas import (
    BoardEntryOut,
    DisruptionOut,
    MetaOut,
    NextStop,
    QuotaOut,
    SegmentRef,
    StationBoardOut,
    StationOut,
    StopOut,
    TrainDetailOut,
    TrainOut,
    TrainsOut,
)
from app.geo.rail import parse_segment_key, segment_key
from app.plk.models import Disruption, StationOnRoute
from app.position.estimator import current_segment_key
from app.state import LiveState, LiveTrain, utcnow

ATTRIBUTION = [
    "Źródło danych: PKP Polskie Linie Kolejowe S.A.",
    "© OpenStreetMap contributors",
]
DISCLAIMER = "Train positions are estimates interpolated from timetable and reported times."
MAX_SEGMENT_KEYS = 300
BOARD_KEEP_AFTER = timedelta(minutes=10)  # a train stays on a station board this long after its time
BOARD_MAX_ENTRIES = 40

router = APIRouter(prefix="/api")


def _state(request: Request) -> LiveState:
    return request.app.state.live


async def _map_activity(request: Request) -> None:
    """Map requests keep the poller awake (it pauses when nobody is looking)."""
    poller = getattr(request.app.state, "poller", None)
    if poller is not None:
        await poller.on_activity()


def _disruption_out(st: LiveState, d: Disruption) -> DisruptionOut:
    return DisruptionOut(
        id=d.disruption_id,
        type=st.disruption_types.get(d.disruption_type_code or "", d.disruption_type_code),
        message=d.message,
        from_station=st.name(d.start_station_id) if d.start_station_id else None,
        to_station=st.name(d.end_station_id) if d.end_station_id else None,
        affected_trains=len({(a.schedule_id, a.order_id, a.operating_date) for a in d.affected_routes}),
    )


def ms(dt: datetime | None) -> int | None:
    return int(dt.timestamp() * 1000) if dt else None


def _minutes(td) -> int:
    return round(td.total_seconds() / 60) if td is not None else 0


def _number(lt: LiveTrain) -> str:
    """Display number such as "EIP 5352"."""
    r = lt.route
    category = r.commercial_category_symbol if r else None
    number = (r.national_number or r.international_departure_number) if r else None
    return " ".join(x for x in (category, number) if x) or f"#{lt.op.order_id}"


def _train_out(st: LiveState, lt: LiveTrain, cls=TrainOut, **extra):
    r = lt.route
    est = lt.est
    stops = lt.timeline.stops
    category = r.commercial_category_symbol if r else None
    display = _number(lt)

    segment = None
    if est.status == "moving" and est.seg_dep and est.seg_arr:
        segment = SegmentRef(key=current_segment_key(lt.timeline, est), dep_ms=ms(est.seg_dep), arr_ms=ms(est.seg_arr))
    next_stop = None
    if est.next_stop is not None:
        s = stops[est.next_stop]
        next_stop = NextStop(
            station_id=s.station_id, name=st.name(s.station_id), eta_ms=ms(s.t_in), delay_min=_minutes(s.arr_delay)
        )
    return cls(
        key=lt.key,
        number=display,
        name=(r.name.title() if r and r.name else None),
        category=category,
        carrier=r.carrier_code if r else None,
        status=est.status,
        delay_min=max(0, _minutes(est.delay)),
        lat=est.lat,
        lon=est.lon,
        bearing=round(est.bearing or 0.0, 1),
        segment=segment,
        next_stop=next_stop,
        origin=st.name(stops[0].station_id),
        destination=st.name(stops[-1].station_id),
        last_report_ms=ms(lt.timeline.last_report_time),
        disrupted=bool(st.disruptions_for(lt.op)),
        **extra,
    )


@router.get("/trains", response_model=TrainsOut)
async def list_trains(request: Request) -> TrainsOut:
    await _map_activity(request)
    st = _state(request)
    now = utcnow()
    trains = [_train_out(st, lt) for lt in st.trains(now) if lt.est.visible]
    return TrainsOut(generated_at_ms=ms(now), snapshot_at_ms=ms(st.snapshot_at), stale=st.is_stale(now), trains=trains)


def _schedule_rows(lt: LiveTrain) -> dict[tuple[int, int], StationOnRoute]:
    """Schedule entries keyed by (station id, occurrence) so looping routes stay aligned."""
    rows: dict[tuple[int, int], StationOnRoute] = {}
    if lt.route:
        seen: dict[int, int] = {}
        for s in lt.route.stations:
            n = seen.get(s.station_id, 0)
            rows[(s.station_id, n)] = s
            seen[s.station_id] = n + 1
    return rows


@router.get("/trains/{key}", response_model=TrainDetailOut)
async def train_detail(key: str, request: Request) -> TrainDetailOut:
    await _map_activity(request)
    st = _state(request)
    now = utcnow()
    lt = st.find(key, now)
    if lt is None:
        raise HTTPException(404, "train not found")
    tl, est = lt.timeline, lt.est
    rows = _schedule_rows(lt)
    seen: dict[int, int] = {}
    tau_index = est.seg_to if est.seg_to is not None else (est.at_stop if est.at_stop is not None else -1)

    stops_out = []
    for i, s in enumerate(tl.stops):
        n = seen.get(s.station_id, 0)
        seen[s.station_id] = n + 1
        row = rows.get((s.station_id, n))
        geo = st.stations.get(s.station_id)
        delay = s.arr_delay if s.arr_delay is not None else s.dep_delay
        stops_out.append(
            StopOut(
                station_id=s.station_id,
                name=st.name(s.station_id),
                lat=geo.lat if geo else None,
                lon=geo.lon if geo else None,
                planned_arrival_ms=ms(s.planned_arr),
                planned_departure_ms=ms(s.planned_dep),
                actual_arrival_ms=ms(s.actual_arr),
                actual_departure_ms=ms(s.actual_dep),
                est_arrival_ms=ms(s.est_arr),
                est_departure_ms=ms(s.est_dep),
                delay_min=_minutes(delay),
                platform=(row.departure_platform or row.arrival_platform) if row else None,
                track=(row.departure_track or row.arrival_track) if row else None,
                is_stop=s.is_passenger_stop,
                reported=s.reported,
                passed=i <= tl.last_reported or (tau_index >= 0 and i < tau_index),
            )
        )

    located = [s.station_id for s in tl.stops if s.station_id in st.stations]
    keys = [segment_key(a, b) for a, b in pairwise(located) if a != b]
    current = current_segment_key(tl, est)
    return _train_out(
        st, lt, cls=TrainDetailOut,
        operating_date=lt.op.operating_date.isoformat(),
        train_status=lt.op.train_status,
        stops=stops_out,
        segment_keys=keys,
        current_segment_index=keys.index(current) if current in keys else None,
        disruptions=[_disruption_out(st, d) for d in st.disruptions_for(lt.op)],
    )


@router.get("/disruptions", response_model=list[DisruptionOut])
def disruptions(request: Request) -> list[DisruptionOut]:
    st = _state(request)
    return [_disruption_out(st, d) for d in st.disruptions]


@router.get("/segments")
def segments(request: Request, keys: str = Query(..., description="comma-separated fromId-toId keys")):
    st = _state(request)
    out: dict[str, list[list[float]]] = {}
    for key in keys.split(",")[:MAX_SEGMENT_KEYS]:
        try:
            a, b = parse_segment_key(key.strip())
        except ValueError:
            continue
        pa, pb = st.stations.latlon(a), st.stations.latlon(b)
        if pa is None or pb is None:
            continue
        seg = st.segments.get_or_straight(a, b, pa, pb)
        out[key.strip()] = [[round(lat, 5), round(lon, 5)] for lat, lon in seg.path]
    return out


@router.get("/stations", response_model=list[StationOut])
def stations(request: Request) -> list[StationOut]:
    st = _state(request)
    out = []
    for sid in sorted(st.passenger_station_ids()):
        geo = st.stations.get(sid)
        if geo:
            out.append(StationOut(id=sid, name=st.name(sid), lat=geo.lat, lon=geo.lon))
    return out


@router.get("/stations/{station_id}/board", response_model=StationBoardOut)
def station_board(station_id: int, request: Request) -> StationBoardOut:
    """Trains calling at the station: those still to come and those that left a moment ago."""
    st = _state(request)
    if station_id not in st.stations:
        raise HTTPException(404, "station not found")
    now = utcnow()
    found: list[tuple[datetime, BoardEntryOut]] = []
    for lt in st.trains(now):
        if lt.op.train_status == "X":
            continue
        stops = lt.timeline.stops
        rows = _schedule_rows(lt)
        seen = 0
        for s in stops:
            if s.station_id != station_id:
                continue
            row = rows.get((station_id, seen))
            seen += 1
            when = s.t_out or s.t_in
            if when is None or not s.is_passenger_stop or when < now - BOARD_KEEP_AFTER:
                continue
            r = lt.route
            entry = BoardEntryOut(
                key=lt.key,
                number=_number(lt),
                name=(r.name.title() if r and r.name else None),
                category=r.commercial_category_symbol if r else None,
                origin=st.name(stops[0].station_id),
                destination=st.name(stops[-1].station_id),
                planned_arrival_ms=ms(s.planned_arr),
                planned_departure_ms=ms(s.planned_dep),
                est_arrival_ms=ms(s.est_arr),
                est_departure_ms=ms(s.est_dep),
                delay_min=max(0, _minutes(s.delay)),
                platform=(row.departure_platform or row.arrival_platform) if row else None,
                track=(row.departure_track or row.arrival_track) if row else None,
                reported=s.reported,
            )
            found.append((when, entry))
    found.sort(key=lambda x: x[0])
    return StationBoardOut(
        id=station_id,
        name=st.name(station_id),
        generated_at_ms=ms(now),
        entries=[e for _, e in found[:BOARD_MAX_ENTRIES]],
    )


@router.get("/meta", response_model=MetaOut)
def meta(request: Request) -> MetaOut:
    st = _state(request)
    now = utcnow()
    trains = st.trains(now)
    q = st.quota
    return MetaOut(
        mode=st.mode,
        attribution=ATTRIBUTION,
        disclaimer=DISCLAIMER,
        carriers=st.settings.carrier_list,
        poll_interval_s=st.poll_interval_s,
        last_poll_ok_ms=ms(st.last_poll_ok),
        snapshot_at_ms=ms(st.snapshot_at),
        stale=st.is_stale(now),
        idle=st.idle,
        last_error=st.last_error,
        auth_error=st.auth_error,
        disruption_count=len(st.disruptions),
        quota=QuotaOut(
            hourly_limit=q.hourly_limit, hourly_remaining=q.hourly_remaining,
            daily_limit=q.daily_limit, daily_remaining=q.daily_remaining,
        ),
        api_calls=st.calls_made,
        train_count=len(trains),
        visible_train_count=sum(1 for t in trains if t.est.visible),
        located_station_count=len(st.stations),
        segment_count=len(st.segments),
    )


@router.get("/health")
def health() -> dict:
    return {"ok": True}
