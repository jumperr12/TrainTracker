# ICtracker: a live map of PKP Intercity trains

ICtracker estimates where every PKP Intercity train is right now. It combines two things:

- **Timetable and reported run data** from the official PKP PLK **Open Data API** ("Otwarte Dane Kolejowe").
- **Real track geometry** from OpenStreetMap.

Between reports, trains are interpolated along the routed railway line and animated once per second.

- **Backend:** Python (FastAPI). It polls the PLK API and estimates positions. It is the only place the API key lives.
- **Frontend:** React, TypeScript and Leaflet (Vite).

```
PKP PLK API ──(key, server-side only)──> poller ──> LiveState ──> FastAPI /api/* ──> React + Leaflet
OSM (Overpass, one-off) ──> stations_geo.json + rail graph ──> rail_segments.json (track polylines)
```

## Data source and terms

- PKP PLK publishes a free public API: https://pdp-api.plk-sa.pl, with docs at `/api-documentation`. **No scraping is needed.**
- portalpasazera.pl has no `robots.txt`, and this app never contacts it.
- You apply for a key at https://pdp-api.plk-sa.pl and get an answer by email in 3–5 business days. Ask for the **Standard** tier if you want polling every 30 s.
- Terms of use: https://pdp-api.plk-sa.pl/api/v1/terms/html. In short:
  - Credit **"PKP Polskie Linie Kolejowe S.A."** when you publish data. The status bar does this.
  - Don't share the key. It stays in `backend/.env` and never reaches the browser.
  - Don't resell raw data.
  - Stay within the rate limits. The poller paces itself using the quota headers.
- Map data and track geometry are © OpenStreetMap contributors (ODbL). The generated
  `stations_geo.json` and `rail_segments.json` files are derivative databases.
- Positions are **estimates**, not GPS.

## Quick start (mock data, no key needed)

The repository includes coordinates for the mock stations, so this runs right after cloning. Without
`rail_segments.json` the mock trains move in straight lines; build the track geometry (below) to snap
them to real rails.

**Backend:**

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
cp .env.example .env
```

Set `MOCK_MODE=1` in `.env`, then start the server:

```bash
.venv/Scripts/python -m uvicorn app.main:app --reload
```

**Frontend:**

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The Vite dev server proxies `/api` to the backend on port 8000. On
macOS or Linux, use `.venv/bin/python` instead of `.venv/Scripts/python`.

## Building the geodata

The OSM steps don't need a PLK key. Run everything from `backend/`.

| Step | Command | Output |
|---|---|---|
| 1. Download OSM stations and rail tiles (resumable; about 1 min per tile on busy public servers) | `python -m scripts.fetch_osm` | `data/osm/` |
| 2. Build the rail graph | `python -m scripts.build_rail_graph` | `data/rail_graph.pkl` |
| 3. Match station names to OSM | `python -m scripts.build_station_coords [--mock]` | `stations_geo.json`, `data/reports/unmatched*.csv` |
| 4. Route station pairs along the track | `python -m scripts.build_segments [--mock]` | `rail_segments.json`, `data/reports/segment_issues*.csv` |

For real data:

- Step 3 downloads the PLK station dictionary, so it needs the key.
- Step 3 disambiguates duplicate station names using route neighbours from the schedules the running backend caches in `data/cache/`.
- Step 4 routes the pairs from those cached schedules.

Fix any unmatched or wrong stations in `data/overrides/station_overrides.csv`, then re-run step 4.
While the backend runs, it also routes any new station pairs it meets in the background. Restart it
after rebuilding the geodata.

## Going live with a real key

1. Put the key in `backend/.env` (`PLK_API_KEY=sk_live_...`), set `PLK_TIER`, and set `MOCK_MODE=0`.
2. `python -m scripts.record_fixtures` uses 4 API calls. It prints:
   - the carrier codes (check that `IC` is PKP Intercity);
   - a timezone sanity check on the naive timestamps;
   - how many stations have coordinates.
3. Start the backend once. It caches today's schedules in `data/cache/`.
4. `python -m scripts.build_station_coords --nominatim`, then `python -m scripts.build_segments`.
5. Restart the backend, then start the frontend as above.

## How positions are estimated

- **Timeline** (`app/position/timeline.py`):
  - Reported times are used as they are.
  - After the last report, the delay is carried forward. A train can recover delay at stops with long planned dwell: `est_dep = max(planned_dep, est_arr + min(dwell, 1 min))`.
  - Points without a report between two reports get an interpolated delay.
- **Estimator** (`app/position/estimator.py`):
  - The train is placed on the routed track at the predicted time.
  - It is never shown past its next unreported event. If that event is overdue, the train is held just before it ("awaiting report", with a growing delay) for up to `HOLD_GRACE_MIN` (10 min by default). After that we assume the point doesn't report.
- **Routing** (`app/geo/rail.py`):
  - A* runs over directed edges, so a train can't make a sharp turn through a switch.
  - Stations snap to several nearby track candidates (sampled every 40 m).
  - A route falls back to a straight line if no rail path exists or the path is more than 1.8× the straight-line distance.
- **Frontend:** the backend sends each moving train's segment key with departure and arrival times. The browser animates the marker along the cached polyline once per second, and a poll every 15 s corrects it.

## Polling and quota

| Tier | Limits | Default interval |
|---|---|---|
| Basic | 100 per hour, 1000 per day | 120 s |
| Standard | 500 per hour, 5000 per day | 30 s |
| Premium | 2000 per hour, 20000 per day | 15 s |

- `POLL_INTERVAL_S` can override the interval, but it is clamped to the daily budget.
- The poller stretches its interval when `X-RateLimit-*-Remaining` runs low.
- On HTTP 429 it waits until the next full hour.
- During the monthly maintenance window (first Tuesday, 20:00–24:00) it polls rarely.
- Schedules are cached on disk, so restarts don't use up quota.

## Icons

`frontend/public/icons/` contains **transparent placeholder PNGs**. See
[frontend/public/icons/README.md](frontend/public/icons/README.md) for the file names, sizes and
orientation. Replace them with real artwork, then set `SHOW_FALLBACK_LABEL = false` in
`frontend/src/lib/icons.ts`.

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest
cd frontend && npm test && npm run typecheck
```

The two test suites check the TS and Python interpolation code against the same vectors
(`backend/tests/fixtures/interp_cases.json`).

## API (for the frontend)

| Endpoint | Returns |
|---|---|
| `GET /api/trains` | Visible trains: position, bearing, delay, status, current segment and next stop |
| `GET /api/trains/{key}` | Full stop list: planned, reported and estimated times, platforms |
| `GET /api/segments?keys=A-B,...` | Track polylines |
| `GET /api/stations` | Located stations on the tracked routes |
| `GET /api/meta` | Mode, attribution, freshness, quota, errors |

Interactive docs are at http://localhost:8000/docs.
