from datetime import datetime

import pytest

from app.plk.client import QuotaInfo
from app.sync.quota import base_interval, in_maintenance_window, paced_interval


def test_base_interval_defaults_fit_daily_budget():
    assert base_interval("basic") == 120
    assert base_interval("standard") == 30
    for tier, daily in (("basic", 1000), ("standard", 5000), ("premium", 20000)):
        assert 86400 / base_interval(tier) < daily


def test_override_is_clamped_to_budget():
    assert base_interval("basic", override=10) == pytest.approx(86400 / 975)
    assert base_interval("standard", override=300) == 300


def test_paced_interval_stretches_when_quota_is_low():
    now = datetime(2026, 9, 30, 18, 0)  # 6 h = 21600 s left today
    assert paced_interval(120, QuotaInfo(daily_remaining=900), now) == 120
    assert paced_interval(120, QuotaInfo(daily_remaining=125), now) == pytest.approx(216)
    assert paced_interval(120, QuotaInfo(daily_remaining=10), now) == 3600  # capped


def test_paced_interval_respects_hourly_quota():
    now = datetime(2026, 9, 30, 18, 30)  # 1800 s left this hour
    assert paced_interval(30, QuotaInfo(hourly_remaining=12), now) == pytest.approx(180)


@pytest.mark.parametrize(
    "dt, expected",
    [
        (datetime(2026, 10, 6, 21, 0), True),  # first Tuesday of October 2026
        (datetime(2026, 10, 6, 19, 59), False),
        (datetime(2026, 10, 13, 21, 0), False),  # second Tuesday
        (datetime(2026, 10, 5, 21, 0), False),  # Monday
    ],
)
def test_maintenance_window(dt, expected):
    assert in_maintenance_window(dt) is expected
