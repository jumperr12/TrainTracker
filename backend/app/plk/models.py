"""Pydantic models mirroring the PKP PLK Open Data API DTOs (only the fields we use).

Field names follow the OpenAPI spec at https://pdp-api.plk-sa.pl/swagger (camelCase on the wire).
Unknown fields are ignored so that non-breaking API additions don't break parsing.
"""

from datetime import date, datetime, timedelta

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class ApiModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, extra="ignore")


# --- /api/v1/operations -----------------------------------------------------


class OperationStation(ApiModel):
    station_id: int
    planned_sequence_number: int | None = None
    actual_sequence_number: int | None = None
    planned_arrival: datetime | None = None
    planned_departure: datetime | None = None
    arrival_delay_minutes: int | None = None
    departure_delay_minutes: int | None = None
    actual_arrival: datetime | None = None
    actual_departure: datetime | None = None
    is_confirmed: bool = False
    is_cancelled: bool = False


class TrainOperation(ApiModel):
    schedule_id: int
    order_id: int
    train_order_id: int | None = None
    operating_date: date
    train_status: str | None = None  # S=NotStarted, P=InProgress, C=Completed, X=Cancelled, Q=PartialCancelled
    stations: list[OperationStation] = []


class Pagination(ApiModel):
    page: int = 1
    page_size: int = 0
    total_count: int = 0
    total_pages: int = 1
    has_next_page: bool = False


class OperationsResponse(ApiModel):
    generated_at: datetime | None = None
    pagination: Pagination | None = None
    trains: list[TrainOperation] = []
    stations: dict[str, str] = {}  # station id -> name


# --- /api/v1/schedules ------------------------------------------------------


class StationOnRoute(ApiModel):
    station_id: int
    order_number: int | None = None
    arrival_train_number: str | None = None
    arrival_platform: str | None = None
    arrival_track: str | None = None
    arrival_day: int | None = None
    arrival_time: str | None = None  # .NET TimeSpan, e.g. "14:35:00"
    departure_train_number: str | None = None
    departure_platform: str | None = None
    departure_track: str | None = None
    departure_day: int | None = None
    departure_time: str | None = None
    stop_type_id: int | None = None
    stop_type_name: str | None = None


class Route(ApiModel):
    schedule_id: int
    order_id: int
    train_order_id: int | None = None
    name: str | None = None
    carrier_code: str | None = None
    national_number: str | None = None
    international_arrival_number: str | None = None
    international_departure_number: str | None = None
    commercial_category_symbol: str | None = None
    operating_dates: list[date] = []
    stations: list[StationOnRoute] = []


class StationDict(ApiModel):
    id: int
    name: str


class Dictionaries(ApiModel):
    stations: dict[str, StationDict] = {}


class SchedulesResponse(ApiModel):
    generated_at: datetime | None = None
    routes: list[Route] = []
    dictionaries: Dictionaries | None = None


# --- /api/v1/dictionaries/stations -------------------------------------------


class Station(ApiModel):
    id: int
    name: str


class StationsResponse(ApiModel):
    stations: list[Station] = []
    total_count: int = 0
    page: int = 1
    page_size: int = 0
    total_pages: int = 1


class DataVersion(ApiModel):
    data_version: str | None = None
    schedules_version: str | None = None
    operations_version: str | None = None
    timestamp: datetime | None = None


def parse_timespan(value: str | None) -> timedelta | None:
    """Parse a .NET TimeSpan string: "hh:mm:ss", "hh:mm", "d.hh:mm:ss" (fraction of seconds allowed)."""
    if not value:
        return None
    days = 0
    rest = value
    if "." in value.split(":", 1)[0]:
        d, rest = value.split(".", 1)
        days = int(d)
    parts = rest.split(":")
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        s = float(parts[2]) if len(parts) > 2 else 0.0
    except ValueError:
        return None
    return timedelta(days=days, hours=h, minutes=m, seconds=s)
