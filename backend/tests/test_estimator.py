from datetime import timedelta

import pytest

from app.geo.polyline import angle_diff
from app.position.estimator import estimate
from app.position.timeline import build_timeline
from tests.helpers import LINE, TZ, empty_segments, line_stations, now_at, stop, train

GRACE = timedelta(minutes=10)


def run(op, minute, stations=None, grace=GRACE):
    tl = build_timeline(op, TZ)
    return tl, estimate(tl, op.train_status, now_at(minute), stations or line_stations(), empty_segments(), grace)


def basic_train(**kw):
    return train(
        stop(1, dep=0, a_dep=kw.get("d1")),
        stop(2, arr=10, dep=12, a_arr=kw.get("a2"), a_dep=kw.get("d2")),
        stop(3, arr=20, dep=21, a_arr=kw.get("a3"), a_dep=kw.get("d3")),
        stop(4, arr=30, a_arr=kw.get("a4")),
        status=kw.get("status", "P"),
    )


def test_moving_halfway_between_stations():
    _, est = run(basic_train(d1=0), 5)
    assert est.status == "moving"
    assert est.lon == pytest.approx(20.05, abs=1e-3)
    assert angle_diff(est.bearing, 90) < 1
    assert (est.seg_from, est.seg_to) == (0, 1)


def test_dwelling_at_station():
    _, est = run(basic_train(d1=0, a2=10), 11)
    assert est.status == "dwelling"
    assert (est.lat, est.lon) == pytest.approx(LINE[2])
    assert est.at_stop == 1


def test_awaiting_holds_before_next_station_and_raises_delay():
    # Left on time, predicted at station 2 by minute 10, but it's minute 14 and no report yet.
    _, est = run(basic_train(d1=0), 14)
    assert est.status == "awaiting"
    assert est.lon < LINE[2][1]  # still short of station 2
    assert est.lon > 20.09  # but close to it
    assert est.delay >= timedelta(minutes=4)


def test_after_grace_follows_prediction():
    # 12 minutes past the predicted arrival with no report: assume station 2 doesn't report.
    _, est = run(basic_train(d1=0), 22.5, grace=timedelta(minutes=10))
    assert est.status in ("moving", "dwelling")
    assert est.lon > LINE[2][1]


def test_awaiting_departure_when_dwell_is_over():
    _, est = run(basic_train(d1=0, a2=10), 15)  # arrived, planned departure 12, not reported
    assert est.status == "awaiting"
    assert (est.lat, est.lon) == pytest.approx(LINE[2])
    assert est.delay >= timedelta(minutes=3)


def test_not_started_shown_shortly_before_departure_only():
    _, est = run(basic_train(status="S"), -10)
    assert est.status == "not_started" and est.visible
    _, est = run(basic_train(status="S"), -40)
    assert not est.visible


def test_late_departure_waits_at_origin():
    _, est = run(basic_train(status="S"), 7)
    assert est.status == "awaiting"
    assert (est.lat, est.lon) == pytest.approx(LINE[1])
    assert est.delay == timedelta(minutes=7)


def test_finished_and_cancelled_are_hidden():
    _, est = run(basic_train(d1=0, d2=12, d3=21, a4=30), 31)
    assert est.visible and est.status == "dwelling"  # just arrived
    _, est = run(basic_train(d1=0, d2=12, d3=21, a4=30), 40)
    assert not est.visible
    _, est = run(basic_train(status="X"), 5)
    assert est.status == "cancelled" and not est.visible


def test_points_without_coordinates_are_merged_into_the_segment():
    stations = line_stations(ids=(1, 3, 4))  # station 2 unknown
    _, est = run(basic_train(d1=0, a2=10, d2=12), 16, stations=stations)
    assert est.status == "moving"
    assert (est.seg_from, est.seg_to) == (0, 2)
    assert LINE[2][1] < est.lon < LINE[3][1]


def test_partially_cancelled_train_skips_cancelled_stop():
    op = train(
        stop(1, dep=0, a_dep=0),
        stop(2, arr=10, dep=12, cancelled=True),
        stop(3, arr=20, dep=21),
        stop(4, arr=30),
        status="Q",
    )
    _, est = run(op, 10)
    assert est.status == "moving"
    assert (est.seg_from, est.seg_to) == (0, 1)  # timeline indexes: station 1 -> station 3


def test_delay_is_shown_for_next_stop():
    _, est = run(basic_train(d1=5), 8)
    assert est.delay == timedelta(minutes=5)
    assert est.next_stop == 1


def test_outside_coverage_when_route_leaves_known_area():
    stations = line_stations(ids=(1, 2))
    _, est = run(basic_train(d1=0, d2=12), 25, stations=stations, grace=timedelta(0))
    assert est.status == "out_of_coverage" and not est.visible


def test_origin_without_planned_time_does_not_crash():
    # Trains from abroad enter at a border point that has only PLK's forecast, no planned time.
    op = train(stop(1, f_dep=0), stop(2, arr=10, dep=12, f_arr=10, f_dep=12), stop(3, arr=20, f_arr=20), status="S")
    _, est = run(op, 3)  # the forecast departure has passed without a report
    assert est.status == "awaiting"
    assert est.delay == timedelta(minutes=3)
