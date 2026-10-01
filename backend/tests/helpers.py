from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.geo.rail import SegmentStore
from app.geo.stations import StationGeo, StationIndex
from app.plk.models import OperationStation, TrainOperation

TZ = ZoneInfo("Europe/Warsaw")
DAY = date(2026, 9, 30)
T0 = datetime(2026, 9, 30, 12, 0)  # naive local, like the API


def at(minutes: float) -> datetime:
    return T0 + timedelta(minutes=minutes)


def now_at(minutes: float) -> datetime:
    return (T0 + timedelta(minutes=minutes)).replace(tzinfo=TZ)


def stop(sid, arr=None, dep=None, a_arr=None, a_dep=None, seq=None, cancelled=False) -> OperationStation:
    """Minutes relative to T0; a_* are actual (reported) times."""
    return OperationStation(
        station_id=sid,
        planned_sequence_number=seq,
        planned_arrival=at(arr) if arr is not None else None,
        planned_departure=at(dep) if dep is not None else None,
        actual_arrival=at(a_arr) if a_arr is not None else None,
        actual_departure=at(a_dep) if a_dep is not None else None,
        is_cancelled=cancelled,
    )


def train(*stops: OperationStation, status: str = "P", operating_date: date = DAY) -> TrainOperation:
    numbered = [
        s.model_copy(update={"planned_sequence_number": s.planned_sequence_number or i + 1})
        for i, s in enumerate(stops)
    ]
    return TrainOperation(
        schedule_id=26, order_id=1, operating_date=operating_date, train_status=status, stations=numbered
    )


# Four stations on a straight east-west line, 0.1° of longitude (~6.9 km) apart.
LINE = {1: (52.0, 20.0), 2: (52.0, 20.1), 3: (52.0, 20.2), 4: (52.0, 20.3)}


def line_stations(ids=(1, 2, 3, 4)) -> StationIndex:
    return StationIndex({i: StationGeo(i, f"S{i}", *LINE[i], "test") for i in ids})


def empty_segments() -> SegmentStore:
    return SegmentStore(None)
