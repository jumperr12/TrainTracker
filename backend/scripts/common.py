"""Helpers shared by the offline scripts."""

import asyncio
import json
from pathlib import Path

from app.config import Settings
from app.plk.client import PlkClient
from app.plk.mock import ALL_TEMPLATES, STATIONS
from app.plk.models import SchedulesResponse, Station


def cached_schedules(settings: Settings) -> list[SchedulesResponse]:
    return [
        SchedulesResponse.model_validate_json(p.read_text(encoding="utf-8"))
        for p in sorted(settings.cache_dir.glob("schedules_*.json"))
    ]


def station_sequences(settings: Settings, mock: bool) -> list[list[int]]:
    """Station id sequences of every known route (mock templates or cached real schedules)."""
    if mock:
        return [[sid for sid, _, _ in t.stops] for t in ALL_TEMPLATES]
    seqs = []
    for resp in cached_schedules(settings):
        seqs += [[s.station_id for s in r.stations] for r in resp.routes]
    return seqs


def plk_station_dictionary(settings: Settings, mock: bool, refresh: bool = False) -> dict[int, str]:
    if mock:
        return dict(STATIONS)
    path: Path = settings.cache_dir / "stations_dict.json"
    if path.exists() and not refresh:
        return {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8")).items()}

    async def fetch() -> list[Station]:
        client = PlkClient(settings)
        try:
            return await client.stations()
        finally:
            await client.aclose()

    stations = asyncio.run(fetch())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({s.id: s.name for s in stations}, ensure_ascii=False), encoding="utf-8")
    return {s.id: s.name for s in stations}


def settings_for(mock: bool) -> Settings:
    from app.config import get_settings

    return get_settings().model_copy(update={"mock_mode": mock})
