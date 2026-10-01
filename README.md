# TrainTracker

Live map of PKP Intercity trains in Poland.

Train positions are estimated from timetables and reported arrival/departure times published by
PKP Polskie Linie Kolejowe, then placed on the actual railway track using OpenStreetMap data.
Markers move smoothly between updates and show the current delay.

## Features

- Live positions of PKP Intercity trains (EIP, EIC, IC, TLK, EC, EN)
- Trains follow the real track geometry instead of straight lines between stations
- Delay shown on every train (green / amber / red)
- Traffic disruptions (track works, failures) shown on affected trains
- Train details: route, stops, planned vs. reported/estimated times, platforms
- Search by train number, name or station; filter by category
- Mock mode with simulated trains for development without an API key
- Works on desktop and mobile

## Tech stack

- **Backend:** Python, FastAPI, httpx, SciPy
- **Frontend:** React, TypeScript, Leaflet, Vite
- **Data:** [PKP PLK Open Data API](https://pdp-api.plk-sa.pl), [OpenStreetMap](https://www.openstreetmap.org)

## Getting started

### Requirements

- Python 3.11+
- Node.js 20+
- A PKP PLK Open Data API key ([request one here](https://pdp-api.plk-sa.pl)), or use mock mode

### Backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # macOS/Linux: .venv/bin/python
cp .env.example .env
```

Edit `.env` and either set `PLK_API_KEY` or `MOCK_MODE=1`, then:

```bash
.venv/Scripts/python -m uvicorn app.main:app --reload
```

The API runs on http://localhost:8000 (interactive docs at `/docs`).

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:5173. The dev server proxies `/api` to the backend.

## Configuration

All settings live in `backend/.env` (see `.env.example`):

| Variable | Default | Description |
|---|---|---|
| `PLK_API_KEY` | – | PKP PLK Open Data API key |
| `PLK_TIER` | `basic` | API tier (`basic`, `standard`, `premium`), sets the polling rate |
| `CARRIERS` | `IC` | Carrier codes to track |
| `POLL_INTERVAL_S` | per tier | Override the polling interval (capped by the tier's daily limit) |
| `MOCK_MODE` | `0` | `1` = simulated trains, no API key needed |
| `IDLE_AFTER_MIN` | `5` | Stop polling the API after this many minutes without map viewers (`0` = always poll) |
| `PLK_NAIVE_TZ` | `Europe/Warsaw` | Timezone of the API's timestamps |

## Building map data

Station coordinates and track geometry come from OpenStreetMap and are generated once.
Run from `backend/`:

```bash
python -m scripts.fetch_osm                 # download stations and railway lines (resumable)
python -m scripts.build_rail_graph          # build the rail network graph
python -m scripts.build_station_coords      # match PLK stations to OSM (add --mock for mock data)
python -m scripts.build_segments            # route station-to-station track segments (add --mock)
```

Stations that can't be matched automatically are listed in `data/reports/unmatched.csv` and can
be fixed in `data/overrides/station_overrides.csv`.

## How it works

1. While someone is viewing the map, the backend polls the PKP PLK API for train runs
   (every 2 min on the Basic tier) and disruptions (every 15 min); timetables are fetched once a day.
   With no viewers for a few minutes, polling pauses and resumes on the next visit.
2. For each train it builds a timeline from reported times and carries the last known delay forward.
3. The train is placed on the routed track segment between its previous and next station.
4. The frontend animates markers along the segment every second and refreshes data every 15 s.

Positions are estimates and may differ from the real location of a train.

## Icons

Train and station icons are in `frontend/public/icons/`. The current files are transparent
placeholders — see [the icons README](frontend/public/icons/README.md) for names and sizes.

## Tests

```bash
cd backend && .venv/Scripts/python -m pytest
cd frontend && npm test
```

## Data sources & attribution

- Timetable and train data: **PKP Polskie Linie Kolejowe S.A.** (Open Data API, used under its terms of use)
- Map data and track geometry: © [OpenStreetMap](https://www.openstreetmap.org/copyright) contributors, ODbL

This project is not affiliated with PKP or PKP Intercity.
