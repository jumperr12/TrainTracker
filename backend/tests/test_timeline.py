from datetime import date, datetime, timedelta

from app.position.timeline import build_timeline
from tests.helpers import TZ, at, stop, train


def minutes(td: timedelta) -> float:
    return td.total_seconds() / 60


def test_naive_times_are_local():
    tl = build_timeline(train(stop(1, dep=0), stop(2, arr=10)), TZ)
    assert tl.stops[0].planned_dep == datetime(2026, 9, 30, 12, 0, tzinfo=TZ)
    assert tl.stops[0].planned_dep.utcoffset() == timedelta(hours=2)  # CEST on 30 Sep


def test_nothing_reported_follows_plan():
    tl = build_timeline(train(stop(1, dep=0), stop(2, arr=10, dep=12), stop(3, arr=20)), TZ)
    assert tl.last_reported == -1
    assert [s.t_in for s in tl.stops] == [at(0).replace(tzinfo=TZ), at(10).replace(tzinfo=TZ), at(20).replace(tzinfo=TZ)]


def test_delay_propagates_and_recovers_on_long_dwell():
    op = train(
        stop(1, dep=0, a_dep=5),  # left 5 min late
        stop(2, arr=10, dep=11),  # 1 min dwell: no recovery possible
        stop(3, arr=20, dep=24),  # 4 min planned dwell: can recover 3 min
        stop(4, arr=40),
    )
    tl = build_timeline(op, TZ)
    s = tl.stops
    assert minutes(s[1].arr_delay) == 5 and minutes(s[1].dep_delay) == 5
    assert minutes(s[2].arr_delay) == 5
    assert minutes(s[2].dep_delay) == 2  # arrives 20+5, leaves max(24, 25+1) = 26
    assert minutes(s[3].arr_delay) == 2


def test_train_early_does_not_leave_early():
    op = train(stop(1, dep=0, a_dep=0), stop(2, arr=10, dep=12, a_arr=8), stop(3, arr=20))
    tl = build_timeline(op, TZ)
    assert tl.stops[1].est_dep == at(12).replace(tzinfo=TZ)


def test_unreported_points_between_reports_get_interpolated_delay():
    op = train(
        stop(1, dep=0, a_dep=0),
        stop(2, arr=10, dep=10),  # passing point, no report
        stop(3, arr=20, dep=21, a_arr=30),  # 10 min late here
        stop(4, arr=40),
    )
    tl = build_timeline(op, TZ)
    assert tl.last_reported == 2
    assert 4 <= minutes(tl.stops[1].arr_delay) <= 6  # halfway between 0 and 10
    # Stop 3 has a 1 min planned dwell, so no recovery: leaves max(21, 30 + 1) = 31, still 10 late.
    assert minutes(tl.stops[3].arr_delay) == 10


def test_cancelled_stops_are_dropped_and_order_follows_sequence():
    op = train(
        stop(1, dep=0, seq=1),
        stop(3, arr=20, dep=21, seq=3),
        stop(2, arr=10, dep=11, seq=2, cancelled=True),
        stop(4, arr=30, seq=4),
    )
    tl = build_timeline(op, TZ)
    assert [s.station_id for s in tl.stops] == [1, 3, 4]


def test_midnight_crossing_uses_full_datetimes():
    # Night train from yesterday: planned times already carry the date.
    op = train(stop(1, dep=-13 * 60), stop(2, arr=-1 * 60), status="P", operating_date=date(2026, 9, 29))
    tl = build_timeline(op, TZ)
    assert tl.stops[0].planned_dep.date() == date(2026, 9, 29)
    assert tl.stops[1].planned_arr.date() == date(2026, 9, 30)


def test_only_departure_reported_fills_arrival():
    op = train(stop(1, dep=0, a_dep=0), stop(2, arr=10, dep=12, a_dep=15), stop(3, arr=20))
    tl = build_timeline(op, TZ)
    s = tl.stops[1]
    assert s.est_arr == at(13).replace(tzinfo=TZ)  # planned arrival + 3 min departure delay
    assert s.est_dep == at(15).replace(tzinfo=TZ)
