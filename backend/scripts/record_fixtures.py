"""Save real PLK API responses as test fixtures and print a sanity report (needs PLK_API_KEY).

    python -m scripts.record_fixtures

Uses 4 API calls: carriers, operations, schedules and data-version. It writes to
tests/fixtures/real/ (git-ignored, because the raw data must not be redistributed, Regulamin §3.4)
and prints what to check by hand: the carrier code for PKP Intercity, whether naive timestamps are
local time, and how many operation stations have coordinates.
"""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

from app.config import get_settings
from app.geo.stations import StationIndex
from app.plk.client import PlkClient
from app.position.timeline import build_timeline

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "real"


async def main() -> None:
    settings = get_settings()
    client = PlkClient(settings)
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        r = await client._get("/api/v1/dictionaries/carriers")
        (OUT / "carriers.json").write_text(r.text, encoding="utf-8")
        print("carriers:", ", ".join(f"{c.get('code')}={c.get('name')}" for c in r.json().get("carriers", [])[:30]))

        ops = await client.operations(settings.carrier_list)
        (OUT / "operations.json").write_text(ops.model_dump_json(by_alias=True), encoding="utf-8")
        today = datetime.now(settings.tz).date()
        sch = await client.schedules(today - timedelta(days=1), today, settings.carrier_list)
        (OUT / "schedules.json").write_text(sch.model_dump_json(by_alias=True), encoding="utf-8")
        dv = await client.data_version()
        print("data version:", dv.model_dump(by_alias=True, mode="json"))
    finally:
        await client.aclose()

    print(f"\n{len(ops.trains)} trains in operations, {len(sch.routes)} routes in schedules")
    statuses: dict[str, int] = {}
    for t in ops.trains:
        statuses[t.train_status or "?"] = statuses.get(t.train_status or "?", 0) + 1
    print("train statuses:", statuses)

    # Timezone check: the most recent confirmed time should be a little before the local wall clock.
    # (Unconfirmed stops carry PLK's forecast in the same fields, so they're left out.)
    now_local = datetime.now(settings.tz).replace(tzinfo=None)
    actuals = [s.actual_arrival or s.actual_departure for t in ops.trains for s in t.stations if s.is_confirmed]
    actuals = [a for a in actuals if a is not None]
    if actuals:
        latest = max(a.replace(tzinfo=None) for a in actuals)
        lag = (now_local - latest).total_seconds() / 60
        print(f"latest reported time {latest} vs local now {now_local:%H:%M:%S} -> lag {lag:.1f} min")
        if abs(lag) > 45:
            print("  !! more than 45 min apart: the timestamps are probably NOT local time. Check PLK_NAIVE_TZ")
    tz_aware = sum(1 for a in actuals if a.tzinfo is not None)
    print(f"{tz_aware}/{len(actuals)} actual timestamps carry an explicit offset")

    stations = StationIndex.load(settings.stations_geo_path, settings.overrides_path)
    ids = {s.station_id for t in ops.trains for s in t.stations}
    located = sum(1 for i in ids if i in stations)
    print(f"{located}/{len(ids)} operation stations have coordinates ({settings.stations_geo_path.name})")
    reported = sum(1 for t in ops.trains for s in t.stations if s.is_confirmed)
    filled = sum(1 for t in ops.trains for s in t.stations if s.actual_arrival or s.actual_departure)
    total = sum(len(t.stations) for t in ops.trains)
    print(f"{reported}/{total} operation stations are confirmed ({filled} carry an actual or forecast time)")
    if ops.trains:
        tl = build_timeline(ops.trains[0], settings.tz, as_of=datetime.now(settings.tz))
        print(f"example timeline: {len(tl.stops)} stops, last reported index {tl.last_reported}")
    print(f"\nsaved to {OUT}")
    print(json.dumps(client.quota.__dict__, default=str))


if __name__ == "__main__":
    asyncio.run(main())
