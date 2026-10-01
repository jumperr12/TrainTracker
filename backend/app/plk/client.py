"""Async client for the PKP PLK Open Data API (https://pdp-api.plk-sa.pl).

The API key is sent in the X-API-Key header and must never leave the backend.
Quota headers are tracked so the poller can pace itself within the tier's limits.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

import httpx

from app.config import Settings
from app.plk.models import (
    DataVersion,
    OperationsResponse,
    SchedulesResponse,
    Station,
    StationsResponse,
)

log = logging.getLogger(__name__)


class PlkError(Exception):
    pass


class PlkAuthError(PlkError):
    """401/403 — missing, invalid or deactivated key."""


class PlkRateLimited(PlkError):
    def __init__(self, retry_at: datetime) -> None:
        super().__init__(f"rate limited until {retry_at.isoformat()}")
        self.retry_at = retry_at


class PlkUnavailable(PlkError):
    """Network failure or 5xx after retries (e.g. the monthly maintenance window)."""


@dataclass
class QuotaInfo:
    hourly_limit: int | None = None
    hourly_remaining: int | None = None
    daily_limit: int | None = None
    daily_remaining: int | None = None
    updated_at: datetime | None = None

    def update(self, headers: httpx.Headers) -> None:
        def num(name: str) -> int | None:
            v = headers.get(name)
            try:
                return int(v) if v is not None else None
            except ValueError:
                return None

        changed = False
        for attr, header in (
            ("hourly_limit", "X-RateLimit-Hourly-Limit"),
            ("hourly_remaining", "X-RateLimit-Hourly-Remaining"),
            ("daily_limit", "X-RateLimit-Daily-Limit"),
            ("daily_remaining", "X-RateLimit-Daily-Remaining"),
        ):
            v = num(header)
            if v is not None:
                setattr(self, attr, v)
                changed = True
        if changed:
            self.updated_at = datetime.now(UTC)


class PlkSource(Protocol):
    """What the poller needs; implemented by PlkClient and MockPlkClient."""

    quota: QuotaInfo
    calls_made: int
    last_snapshot_at: datetime | None

    async def operations(self, carriers: list[str]) -> OperationsResponse: ...
    async def schedules(self, date_from: date, date_to: date, carriers: list[str]) -> SchedulesResponse: ...
    async def stations(self) -> list[Station]: ...
    async def aclose(self) -> None: ...


def _next_full_hour(now: datetime) -> datetime:
    return (now + timedelta(hours=1)).replace(minute=0, second=5, microsecond=0)


class PlkClient:
    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        if not settings.plk_api_key:
            raise PlkAuthError("PLK_API_KEY is not set (see backend/.env.example)")
        self._http = http or httpx.AsyncClient(base_url=settings.plk_base_url, timeout=60)
        self._headers = {
            "X-API-Key": settings.plk_api_key,
            "Accept": "application/json",
            "User-Agent": settings.user_agent,
        }
        self.quota = QuotaInfo()
        self.calls_made = 0
        self.last_snapshot_at: datetime | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, path: str, params: dict | None = None, retries: int = 2) -> httpx.Response:
        delay = 2.0
        for attempt in range(retries + 1):
            try:
                self.calls_made += 1
                r = await self._http.get(path, params=params, headers=self._headers)
            except httpx.TransportError as exc:
                if attempt == retries:
                    raise PlkUnavailable(f"{path}: {exc!r}") from exc
                await asyncio.sleep(delay)
                delay *= 2.5
                continue
            self.quota.update(r.headers)
            if r.status_code in (401, 403):
                raise PlkAuthError(f"{path}: HTTP {r.status_code} {r.text[:200]}")
            if r.status_code == 429:
                raise PlkRateLimited(_next_full_hour(datetime.now(UTC)))
            if r.status_code >= 500:
                if attempt == retries:
                    raise PlkUnavailable(f"{path}: HTTP {r.status_code}")
                await asyncio.sleep(delay)
                delay *= 2.5
                continue
            if r.status_code >= 400:
                raise PlkError(f"{path}: HTTP {r.status_code} {r.text[:300]}")
            return r
        raise PlkUnavailable(path)  # pragma: no cover

    async def operations(self, carriers: list[str]) -> OperationsResponse:
        params = {"fullRoutes": "true", "withPlanned": "true", "pageSize": 5000, "page": 1}
        if carriers:
            params["carriersInclude"] = ",".join(carriers)
        merged: OperationsResponse | None = None
        while True:
            r = await self._get("/api/v1/operations", params)
            page = OperationsResponse.model_validate(r.json())
            snap = r.headers.get("X-Snapshot-Timestamp")
            if snap:
                try:
                    self.last_snapshot_at = datetime.fromisoformat(snap)
                except ValueError:
                    pass
            if merged is None:
                merged = page
            else:
                merged.trains.extend(page.trains)
                merged.stations.update(page.stations)
            if not (page.pagination and page.pagination.has_next_page):
                return merged
            params["page"] += 1

    async def schedules(self, date_from: date, date_to: date, carriers: list[str]) -> SchedulesResponse:
        params = {
            "dateFrom": date_from.isoformat(),
            "dateTo": date_to.isoformat(),
            "fullRoute": "true",
            "dictionaries": "true",
        }
        if carriers:
            params["carriersInclude"] = ",".join(carriers)
        r = await self._get("/api/v1/schedules", params)
        return SchedulesResponse.model_validate(r.json())

    async def stations(self) -> list[Station]:
        out: list[Station] = []
        page = 1
        while True:
            r = await self._get("/api/v1/dictionaries/stations", {"page": page, "pageSize": 10000})
            resp = StationsResponse.model_validate(r.json())
            out.extend(resp.stations)
            if page >= resp.total_pages or not resp.stations:
                return out
            page += 1

    async def data_version(self) -> DataVersion:
        r = await self._get("/api/v1/data-version")
        return DataVersion.model_validate(r.json())
