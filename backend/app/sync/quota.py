"""Polling cadence that stays within the PLK API tier limits (Regulamin §4.1)."""

from datetime import datetime, timedelta

from app.plk.client import QuotaInfo

TIER_LIMITS = {"basic": (100, 1000), "standard": (500, 5000), "premium": (2000, 20000)}  # (per hour, per day)
DEFAULT_INTERVAL_S = {"basic": 120, "standard": 30, "premium": 15}
RESERVE_CALLS = 25  # schedule refreshes, retries and restarts during the day
MAINTENANCE_POLL_S = 600


def base_interval(tier: str, override: int | None = None) -> float:
    """Requested interval, but never faster than the tier's hourly and daily budgets allow."""
    hourly, daily = TIER_LIMITS[tier]
    floor = max(3600 / (hourly - 5), 86400 / (daily - RESERVE_CALLS))
    return max(float(override or DEFAULT_INTERVAL_S[tier]), floor)


def paced_interval(base: float, quota: QuotaInfo, now_local: datetime) -> float:
    """Stretch the interval when the remaining quota (from response headers) runs low."""
    interval = base
    if quota.daily_remaining is not None:
        midnight = (now_local + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        left = (midnight - now_local).total_seconds()
        usable = quota.daily_remaining - RESERVE_CALLS
        interval = max(interval, left / usable if usable > 0 else left)
    if quota.hourly_remaining is not None:
        next_hour = (now_local + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        left = (next_hour - now_local).total_seconds()
        usable = quota.hourly_remaining - 2
        interval = max(interval, left / usable if usable > 0 else left)
    return min(interval, 3600.0)


def in_maintenance_window(now_local: datetime) -> bool:
    """Planned maintenance: first Tuesday of every month, 20:00-24:00 Polish time (Regulamin §5.3)."""
    return now_local.weekday() == 1 and now_local.day <= 7 and now_local.hour >= 20
