"""Match PLK station ids to OpenStreetMap coordinates.

    python -m scripts.build_station_coords --mock          # the synthetic stations used by MOCK_MODE
    python -m scripts.build_station_coords                 # real PLK dictionary (needs PLK_API_KEY)
    python -m scripts.build_station_coords --nominatim     # also ask Nominatim for leftovers (1 req/s)

Needs backend/data/osm/stations.json (python -m scripts.fetch_osm --stations).
Writes stations_geo.json (in data/ or data/mock/) and data/reports/unmatched*.csv.
Fix remaining problems in data/overrides/station_overrides.csv (applied at load time).
"""

import argparse
import csv
import json
import time
from collections import defaultdict
from datetime import UTC, datetime
from itertools import pairwise

import httpx

from app.geo.names import Match, NameIndex, features_from_overpass, match_stations
from app.geo.stations import read_overrides
from scripts.common import plk_station_dictionary, settings_for, station_sequences

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def nominatim_lookup(client: httpx.Client, name: str) -> tuple[float, float, str] | None:
    r = client.get(NOMINATIM_URL, params={"q": f"{name} railway station", "format": "jsonv2", "limit": 5})
    time.sleep(1.1)  # Nominatim usage policy: max 1 request per second
    if r.status_code != 200:
        return None
    for hit in r.json():
        if hit.get("category") in ("railway", "public_transport") or hit.get("type") in ("station", "halt"):
            return float(hit["lat"]), float(hit["lon"]), hit.get("display_name", "")
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock", action="store_true", help="match the mock stations instead of the real dictionary")
    parser.add_argument("--nominatim", action="store_true", help="query Nominatim for unmatched stations")
    parser.add_argument("--refresh", action="store_true", help="re-download the PLK station dictionary")
    parser.add_argument("--only-routes", action="store_true", help="only stations that appear on cached routes")
    args = parser.parse_args()

    settings = settings_for(args.mock)
    osm_path = settings.data_dir / "osm" / "stations.json"
    if not osm_path.exists():
        raise SystemExit(f"{osm_path} missing. Run: python -m scripts.fetch_osm --stations")
    index = NameIndex(features_from_overpass(json.loads(osm_path.read_text(encoding="utf-8"))))

    plk = plk_station_dictionary(settings, args.mock, refresh=args.refresh)
    sequences = station_sequences(settings, args.mock)
    if args.only_routes:
        on_routes = {s for seq in sequences for s in seq}
        plk = {k: v for k, v in plk.items() if k in on_routes}

    neighbours: dict[int, set[int]] = defaultdict(set)
    for seq in sequences:
        for a, b in pairwise(seq):
            neighbours[a].add(b)
            neighbours[b].add(a)

    matches, problems = match_stations(plk, index, neighbours)
    overrides = read_overrides(settings.overrides_path)
    problems = [p for p in problems if p[0] not in overrides]

    if args.nominatim and problems:
        print(f"Asking Nominatim about {len(problems)} stations ...")
        still = []
        with httpx.Client(headers={"User-Agent": settings.user_agent}, timeout=30) as client:
            for pid, name, why in problems:
                hit = nominatim_lookup(client, name)
                if hit:
                    matches[pid] = Match(pid, name, hit[0], hit[1], "nominatim", None, hit[2])
                else:
                    still.append((pid, name, why))
        problems = still

    out = {
        "version": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "license": "Coordinates derived from OpenStreetMap data, © OpenStreetMap contributors, ODbL 1.0",
        "stations": {
            str(m.plk_id): {
                "name": m.plk_name, "lat": round(m.lat, 6), "lon": round(m.lon, 6), "source": m.source,
                "osmId": m.osm_id, "osmName": m.osm_name,
                **({"score": round(m.score, 1)} if m.score is not None else {}),
            }
            for m in sorted(matches.values(), key=lambda m: m.plk_id)
        },
    }
    settings.stations_geo_path.parent.mkdir(parents=True, exist_ok=True)
    settings.stations_geo_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    report = settings.reports_dir / ("unmatched_mock.csv" if args.mock else "unmatched.csv")
    with report.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "name", "problem"])
        w.writerows(problems)

    by_source: dict[str, int] = defaultdict(int)
    for m in matches.values():
        by_source[m.source] += 1
    print(f"{len(matches)}/{len(plk)} stations located {dict(by_source)} -> {settings.stations_geo_path}")
    print(f"{len(problems)} unresolved -> {report} (add fixes to {settings.overrides_path})")


if __name__ == "__main__":
    main()
