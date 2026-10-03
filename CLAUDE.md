# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

TrainTracker / "ICtracker": a live map of PKP Intercity trains. A FastAPI backend polls the PKP PLK
Open Data API, estimates each train's position from timetable + reported times, and snaps it onto
OpenStreetMap track geometry. A React + Leaflet frontend animates the markers between polls.

## Commands

Backend (run from `backend/`; on Windows the venv interpreter is `.venv/Scripts/python`, elsewhere `.venv/bin/python`):

```bash
python -m venv .venv && .venv/Scripts/python -m pip install -e ".[dev]"
cp .env.example .env                                   # set PLK_API_KEY, or MOCK_MODE=1 for no key
.venv/Scripts/python -m uvicorn app.main:app --reload  # http://localhost:8000, docs at /docs
.venv/Scripts/python -m pytest                         # all tests
.venv/Scripts/python -m pytest tests/test_estimator.py -k some_name   # single test
.venv/Scripts/python -m ruff check .                   # lint (line length 110)
```

Frontend (run from `frontend/`):

```bash
npm install
npm run dev        # http://localhost:5173, proxies /api to 127.0.0.1:8000
npm test           # vitest run
npx vitest run src/lib/interpolate.test.ts   # single test file
npm run typecheck
npm run build      # tsc --noEmit && vite build
```

Map data generation (from `backend/`, one-off; add `--mock` to the last two for mock station ids):

```bash
python -m scripts.fetch_osm               # download OSM stations + railways (resumable)
python -m scripts.build_rail_graph        # -> data/rail_graph.pkl
python -m scripts.build_station_coords    # match PLK stations to OSM -> data/stations_geo.json
python -m scripts.build_segments          # route station pairs -> data/rail_segments.json
```

Unmatched stations go to `data/reports/unmatched.csv`; fix them in `data/overrides/station_overrides.csv`.
Mock mode uses the committed `data/mock/` geo files (mock stations have fake ids, so they're kept separate
from the real ones — see `Settings.geo_dir`).

## Architecture

### Backend data flow (`backend/app/`)

`sync/poller.py` (writer) → `state.py` `LiveState` (in-memory) → `api/routes.py` (reader)

- **`plk/`** — `client.py` is the only HTTP client for the PLK API; `PlkSource` is the protocol that both
  `PlkClient` and `mock.py`'s `MockPlkClient` implement (synthetic trains on real-named stations).
  `models.py` mirrors PLK DTOs (camelCase on the wire, unknown fields ignored). PLK timestamps are
  **naive local times** interpreted in `PLK_NAIVE_TZ` — tests and the mock deliberately use naive datetimes.
- **`sync/poller.py`** — the only component that calls the API. Schedules once per day (cached to
  `data/cache/`), operations every poll, disruptions every 15 min. It **pauses when nobody views the map**:
  `/api/trains` and `/api/trains/{key}` call `poller.on_activity()`, which wakes the loop and waits up to
  `FRESH_WAIT_S` for fresh data. Other endpoints (`/meta`, `/stations`, …) do not count as activity.
  After each poll it routes any new station pairs on the rail graph in a background thread ("segment top-up").
- **`sync/quota.py`** — polling cadence derived from tier limits and remaining-quota response headers,
  plus the monthly maintenance window. These rules come from the PLK terms (Regulamin) — don't make polling
  more aggressive.
- **`position/timeline.py`** — turns one train's operation record into per-stop effective times (reported,
  else last delay carried forward; gaps before the last report are interpolated). See the module docstring.
- **`position/estimator.py`** — places a train at "virtual time" tau on its timeline, holding it before an
  unreported event for up to `hold_grace_min`, and interpolates along the routed track segment.
- **`geo/rail.py`** — OSM rail graph, turn-aware A* over directed edge states, and `SegmentStore`
  (segments keyed `"fromId-toId"`; falls back to straight lines when unrouted). `geo/stations.py` holds station
  coordinates; `geo/names.py` does fuzzy PLK↔OSM name matching for the build scripts.
- **`api/`** — `schemas.py` output models serialize as camelCase with timestamps as epoch milliseconds
  (`*_ms`). `LiveState.trains()` is cached for 2 s.
- **`main.py`** — `create_app(settings, source, stations, segments, start_poller)` allows dependency injection;
  tests build the app with `MockPlkClient`, `SegmentStore(None)` and a `tmp_path` data dir.

Train identity is `train_key()` in `state.py` (`scheduleId-orderId-trainOrderId-date`). Routes and
disruptions may be keyed by either `order_id` or `train_order_id`, so lookups try both.

### Frontend (`frontend/src/`)

- The browser only talks to the backend (`api/client.ts`); the PLK key never leaves the server.
  `api/types.ts` must stay in sync with `backend/app/api/schemas.py`.
- `hooks/useLiveTrains.ts` polls trains/detail every 15 s and meta every 30 s, and computes a server
  clock offset used for animation.
- `lib/segments.ts` is a module-level cache of track polylines fetched lazily in batches via `/api/segments`.
- `map/TrainLayer.tsx` manages Leaflet markers imperatively: React re-renders on each poll, while a 1 s timer
  moves markers along their segment using the segment's `depMs`/`arrMs`.

## Constraints

- `.env` (API key) must never be committed; raw PLK responses (`backend/tests/fixtures/real/`) must not be
  redistributed — both per the PLK terms of use.
- Generated data (`data/osm/`, `data/cache/`, `data/reports/`, `data/*.pkl`) is gitignored.
- Train/station icons in `frontend/public/icons/` are placeholders; see the README there for names and sizes.
