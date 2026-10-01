"""Response models of our own API (camelCase JSON, timestamps as epoch milliseconds)."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Out(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class SegmentRef(Out):
    key: str  # "fromStationId-toStationId", resolve with /api/segments
    dep_ms: int
    arr_ms: int


class NextStop(Out):
    station_id: int
    name: str
    eta_ms: int | None
    delay_min: int


class TrainOut(Out):
    key: str
    number: str
    name: str | None
    category: str | None
    carrier: str | None
    # /api/trains lists only not_started | dwelling | moving | awaiting (always with a position);
    # the detail endpoint can also report finished | cancelled | out_of_coverage | unknown (no position).
    status: str
    delay_min: int
    lat: float | None
    lon: float | None
    bearing: float
    segment: SegmentRef | None  # set while moving: the client animates along it
    next_stop: NextStop | None
    origin: str
    destination: str
    last_report_ms: int | None


class TrainsOut(Out):
    generated_at_ms: int
    snapshot_at_ms: int | None
    stale: bool
    trains: list[TrainOut]


class StopOut(Out):
    station_id: int
    name: str
    lat: float | None
    lon: float | None
    planned_arrival_ms: int | None
    planned_departure_ms: int | None
    actual_arrival_ms: int | None
    actual_departure_ms: int | None
    est_arrival_ms: int | None
    est_departure_ms: int | None
    delay_min: int
    platform: str | None
    track: str | None
    is_stop: bool
    reported: bool
    passed: bool


class TrainDetailOut(TrainOut):
    operating_date: str
    train_status: str | None
    stops: list[StopOut]
    segment_keys: list[str]  # consecutive located stops along the whole route
    current_segment_index: int | None


class StationOut(Out):
    id: int
    name: str
    lat: float
    lon: float


class QuotaOut(Out):
    hourly_limit: int | None
    hourly_remaining: int | None
    daily_limit: int | None
    daily_remaining: int | None


class MetaOut(Out):
    mode: str  # live | mock
    attribution: list[str]
    disclaimer: str
    carriers: list[str]
    poll_interval_s: float | None
    last_poll_ok_ms: int | None
    snapshot_at_ms: int | None
    stale: bool
    last_error: str | None
    auth_error: bool
    quota: QuotaOut
    api_calls: int
    train_count: int
    visible_train_count: int
    located_station_count: int
    segment_count: int
