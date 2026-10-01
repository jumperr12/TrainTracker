"""Download railway stations and track geometry for Poland from the Overpass API.

    python -m scripts.fetch_osm                  # stations + rail geometry (resumable 1x1 degree tiles)
    python -m scripts.fetch_osm --stations       # stations only
    python -m scripts.fetch_osm --rail           # rail tiles only; re-run to resume after failures
    python -m scripts.fetch_osm --rail --workers 1   # one request at a time (default 2, one per mirror)
    python -m scripts.fetch_osm --rail --country # one country-wide query (fast when servers are idle,
                                                 # but busy public servers usually time it out)

Queries run one at a time with a pause in between (Overpass fair-use policy). Output goes to
backend/data/osm/ which is git-ignored. OSM data is © OpenStreetMap contributors, ODbL.
"""

import argparse
import json
import queue
import sys
import threading
import time
from pathlib import Path

import httpx

from app.config import get_settings

ENDPOINTS = [
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]

# Poland's bounding box, split into 1°x1° tiles. The edges also pick up border stations in neighbouring countries.
LAT_RANGE = (49, 55)
LON_RANGE = (14, 25)
# Tiles (south lat, west lon) that contain no Polish territory.
SKIP_TILES = {(49, 23), (49, 24), (50, 24), (51, 24), (52, 24), (53, 24), (54, 14), (54, 24)}
PAUSE_S = 3.0

STATIONS_QUERY = """
[out:json][timeout:300];
area["ISO3166-1"="PL"][admin_level=2]->.pl;
(
  node["railway"~"^(station|halt|stop|junction|service_station|spur_junction)$"](area.pl);
  node["public_transport"="station"]["train"="yes"](area.pl);
)->.n;
way["railway"~"^(station|halt)$"](area.pl)->.w;
.n out body qt;
.w out tags center qt;
"""

RAIL_FILTER = '["railway"="rail"]["service"!~"^(yard|siding|spur)$"]["usage"!~"^(industrial|military|tourism)$"]'

RAIL_QUERY = """
[out:json][timeout:240];
way""" + RAIL_FILTER + """({s},{w},{n},{e});
out geom qt;
"""

# One request for the whole country. Only one query slot, but the response is large enough
# that busy public servers often hit their gateway timeout (HTTP 504).
COUNTRY_RAIL_QUERY = """
[out:json][timeout:900][maxsize:2000000000];
area["ISO3166-1"="PL"][admin_level=2]->.pl;
way""" + RAIL_FILTER + """(area.pl);
out geom qt;
"""


def overpass(client: httpx.Client, query: str, prefer: int = 0, attempts: int = 9) -> dict:
    """POST a query, starting with ENDPOINTS[prefer] and rotating through the mirrors on failure."""
    last_exc: Exception | None = None
    for attempt in range(attempts):
        url = ENDPOINTS[(prefer + attempt) % len(ENDPOINTS)]
        try:
            r = client.post(url, data={"data": query}, timeout=360)
            if r.status_code == 200:
                return r.json()
            if r.status_code in (429, 502, 503, 504):
                wait = 10 * (attempt // len(ENDPOINTS) + 1)
                print(f"  {url} -> {r.status_code}, trying next in {wait}s", file=sys.stderr)
                time.sleep(wait)
                continue
            r.raise_for_status()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            last_exc = exc
            print(f"  {url} failed: {exc!r}", file=sys.stderr)
            time.sleep(10)
    raise RuntimeError(f"Overpass query failed after {attempts} attempts") from last_exc


def fetch_stations(client: httpx.Client, out_dir: Path) -> None:
    print("Fetching stations ...")
    data = overpass(client, STATIONS_QUERY)
    elements = []
    for el in data.get("elements", []):
        if el["type"] == "node":
            lat, lon = el["lat"], el["lon"]
        elif "center" in el:
            lat, lon = el["center"]["lat"], el["center"]["lon"]
        else:
            continue
        elements.append({"id": f'{el["type"][0]}{el["id"]}', "lat": lat, "lon": lon, "tags": el.get("tags", {})})
    path = out_dir / "stations.json"
    path.write_text(json.dumps(elements, ensure_ascii=False), encoding="utf-8")
    print(f"  {len(elements)} station-like features -> {path}")


def _ways(data: dict) -> list[dict]:
    return [
        {"id": el["id"], "nodes": el["nodes"], "geometry": [[p["lat"], p["lon"]] for p in el["geometry"]]}
        for el in data.get("elements", [])
        if el["type"] == "way" and "geometry" in el and len(el.get("nodes", [])) == len(el["geometry"])
    ]


def fetch_rail(user_agent: str, out_dir: Path, workers: int) -> None:
    """Download missing tiles. Each worker prefers a different mirror, so no server gets more than
    one concurrent request from us."""
    tiles_dir = out_dir / "rail"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    tiles = [(s, w) for s in range(*LAT_RANGE) for w in range(*LON_RANGE) if (s, w) not in SKIP_TILES]
    todo: queue.Queue = queue.Queue()
    for t in tiles:
        if not (tiles_dir / f"tile_{t[0]}_{t[1]}.json").exists():
            todo.put(t)
    total = todo.qsize()
    done = [0]
    lock = threading.Lock()
    print(f"{total} of {len(tiles)} tiles to download with {workers} worker(s)")

    def worker(prefer: int) -> None:
        with httpx.Client(headers={"User-Agent": user_agent}) as client:
            while True:
                try:
                    s, w = todo.get_nowait()
                except queue.Empty:
                    return
                try:
                    ways = _ways(overpass(client, RAIL_QUERY.format(s=s, w=w, n=s + 1, e=w + 1), prefer))
                except RuntimeError as exc:
                    print(f"  tile ({s},{w}) failed: {exc} (re-run the script later to retry)", file=sys.stderr)
                    time.sleep(60)
                    continue
                path = tiles_dir / f"tile_{s}_{w}.json"
                tmp = path.with_suffix(".tmp")
                tmp.write_text(json.dumps(ways, separators=(",", ":")), encoding="utf-8")
                tmp.replace(path)
                with lock:
                    done[0] += 1
                    print(f"  [{ENDPOINTS[prefer].split('/')[2]}] tile ({s},{w}): {len(ways)} ways  {done[0]}/{total}")
                time.sleep(PAUSE_S)

    threads = [threading.Thread(target=worker, args=(i % len(ENDPOINTS),)) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


def fetch_rail_country(client: httpx.Client, out_dir: Path) -> None:
    tiles_dir = out_dir / "rail"
    tiles_dir.mkdir(parents=True, exist_ok=True)
    print("Fetching all rail ways in Poland in one query (can take several minutes) ...")
    ways = _ways(overpass(client, COUNTRY_RAIL_QUERY))
    path = tiles_dir / "country.json"
    path.write_text(json.dumps(ways, separators=(",", ":")), encoding="utf-8")
    print(f"  {len(ways)} ways -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--stations", action="store_true", help="only fetch stations")
    parser.add_argument("--rail", action="store_true", help="only fetch rail geometry")
    parser.add_argument("--country", action="store_true", help="fetch rail in one country-wide query instead of tiles")
    parser.add_argument("--workers", type=int, default=2, help=f"parallel tile downloads, max {len(ENDPOINTS)}")
    args = parser.parse_args()
    both = not args.stations and not args.rail

    settings = get_settings()
    out_dir = settings.data_dir / "osm"
    out_dir.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"User-Agent": settings.user_agent}) as client:
        if args.stations or both:
            fetch_stations(client, out_dir)
        if (args.rail or both) and args.country:
            fetch_rail_country(client, out_dir)
    if (args.rail or both) and not args.country:
        fetch_rail(settings.user_agent, out_dir, max(1, min(args.workers, len(ENDPOINTS))))


if __name__ == "__main__":
    main()
